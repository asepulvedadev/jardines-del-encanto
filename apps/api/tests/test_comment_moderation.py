"""Durable authorization, once-only writes and cross-project isolation."""

# ruff: noqa: F811, SIM117
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row
from test_crm import authenticated  # noqa: F401

from app.crm.database import connect
from app.social import comment_moderation as mod
from app.social import comment_provider as provider

CREDENTIALS = {"api_key": "test-private", "profile_id": provider.PROFILE, "generation": "fixture"}
ADS = {"api_key": "test-ads", "profile_id": provider.PROFILE}


@pytest.fixture
def moderation(authenticated, monkeypatch):
    _client, url, _password = authenticated
    monkeypatch.setattr(mod.config, "required", lambda: deepcopy(CREDENTIALS))
    monkeypatch.setattr(provider, "ads_credentials", lambda: deepcopy(ADS))
    monkeypatch.setattr(mod.control, "require_connections", lambda *_: None)
    monkeypatch.setattr(mod, "verify_source", lambda *_: None)
    monkeypatch.setattr(mod.config, "locked", __import__("contextlib").nullcontext)
    source_id = uuid4()
    with psycopg.connect(url, row_factory=dict_row) as db:
        db.execute("TRUNCATE crm.comment_moderation_sources CASCADE")
        owner = db.execute("SELECT id FROM crm.users").fetchone()["id"]
        db.execute(
            """INSERT INTO crm.comment_moderation_config(singleton,owner_id,profile_id,credential_revision,ads_revision,enabled,since_at)
            VALUES(true,%s,%s,%s,%s,true,now()-interval '1 day')""",
            (owner, provider.PROFILE, mod.digest(CREDENTIALS), mod.digest(ADS)),
        )
        db.execute(
            """INSERT INTO crm.comment_moderation_sources(id,account_id,platform,post_id,ad_id,content_hash)
            VALUES(%s,%s,'facebook','735902652941803_post','aabbccddeeff001122334455',%s)""",
            (source_id, provider.FACEBOOK, mod.digest("Jardines del Encanto")),
        )
    raw = {
        "id": "comment_1",
        "message": "Quiero información",
        "from": {"id": "visitor"},
        "createdTime": datetime.now(UTC).isoformat(),
        "canReply": True,
        "canHide": True,
        "replyCount": 0,
    }
    monkeypatch.setattr(mod, "comments", lambda *_: (deepcopy([raw]), None))
    calls = []

    def send(credentials, source, operation, **kwargs):
        calls.append(operation)
        if operation == "getInboxPostComments":
            return {"comment": deepcopy(raw)}
        return {"status": "success", "commentId": raw["id"]}

    monkeypatch.setattr(provider, "inbox", send)
    monkeypatch.setattr(
        mod,
        "classify",
        lambda *_: {
            "category": "inquiry",
            "confidence": 0.99,
            "reply": "Conoce el proyecto en https://jardinesdelencanto.site/.",
        },
    )
    with connect() as db:
        source = db.execute(
            "SELECT * FROM crm.comment_moderation_sources WHERE id=%s", (source_id,)
        ).fetchone()
        mod.sweep(db, source)
        row = db.execute("SELECT * FROM crm.comment_moderation_observations").fetchone()
    return url, source, row, raw, calls


def test_missing_policy_is_inactive_and_no_calls(authenticated, monkeypatch):
    monkeypatch.setattr(
        mod.config, "required", lambda: pytest.fail("No credentials without owner policy")
    )
    mod.tick()
    assert mod.status()["enabled"] is False


def test_repeated_scan_and_process_send_once_only(moderation):
    _url, source, row, _raw, calls = moderation
    with connect() as db:
        mod.sweep(db, source)
        assert (
            db.execute("SELECT count(*) AS n FROM crm.comment_moderation_observations").fetchone()[
                "n"
            ]
            == 1
        )
        mod.process(db, source, row)
        mod.process(db, source, row)
        actions = db.execute("SELECT * FROM crm.comment_moderation_actions").fetchall()
        assert len(actions) == 1 and actions[0]["state"] == "accepted"
    assert calls.count("replyToInboxPost") == 1


def test_unknown_write_is_reserved_and_never_replayed(moderation, monkeypatch):
    _url, source, row, raw, _calls = moderation
    calls = []

    def send(_credentials, _source, operation, **kwargs):
        calls.append(operation)
        if operation == "getInboxPostComments":
            return {"comment": raw}
        raise HTTPException(502, "inbox_delivery_unknown")

    monkeypatch.setattr(provider, "inbox", send)
    with connect() as db:
        mod.process(db, source, row)
        mod.process(db, source, row)
        assert (
            db.execute("SELECT state FROM crm.comment_moderation_actions").fetchone()["state"]
            == "unknown"
        )
    assert calls.count("replyToInboxPost") == 1


def test_disabled_owner_or_connection_cannot_dispatch(moderation, monkeypatch):
    url, source, row, _raw, calls = moderation
    with psycopg.connect(url) as owner:
        owner.execute("UPDATE crm.users SET enabled=false")
    with connect() as db:
        with pytest.raises(ValueError, match="owner_disabled"):
            mod.process(db, source, row)
    assert not calls
    with psycopg.connect(url) as owner:
        owner.execute("UPDATE crm.users SET enabled=true")

    def disabled(*_):
        raise HTTPException(409, "connection_disabled")

    monkeypatch.setattr(mod.control, "require_connections", disabled)
    with connect() as db:
        with pytest.raises(HTTPException):
            mod.process(db, source, row)
    assert not calls


def test_fresh_comment_change_blocks_after_reservation(moderation):
    _url, source, row, raw, calls = moderation
    raw["message"] = "New edited content"
    with connect() as db:
        mod.process(db, source, row)
        assert (
            db.execute("SELECT state FROM crm.comment_moderation_actions").fetchone()["state"]
            == "blocked"
        )
    assert "replyToInboxPost" not in calls


def test_credential_rotation_blocks_before_model_or_write(moderation, monkeypatch):
    _url, source, row, _raw, calls = moderation
    monkeypatch.setattr(mod.config, "required", lambda: {**CREDENTIALS, "api_key": "rotated"})
    with connect() as db:
        with pytest.raises(ValueError, match="credentials_changed"):
            mod.process(db, source, row)
    assert not calls


def test_tiktok_never_receives_comment_private_dm(moderation):
    _url, source, row, _raw, calls = moderation
    source = {**source, "platform": "tiktok", "account_id": provider.TIKTOK}
    with connect() as db:
        mod.dispatch(db, source, row, "private_reply", "Texto", 1, 1)
    assert calls == []


def test_complaint_never_hidden_even_if_model_misclassifies(moderation, monkeypatch):
    _url, source, row, raw, calls = moderation
    raw["message"] = "¿Son una estafa? Quiero ver la licencia"
    row = {**row, "content": {**row["content"], "message": raw["message"]}}
    monkeypatch.setattr(
        mod, "classify", lambda *_: {"category": "abuse", "confidence": 1.0, "reply": ""}
    )
    with connect() as db:
        mod.process(db, source, row)
    assert not calls


def test_runtime_cannot_expand_scope_or_erase_audit(moderation):
    with connect() as db:
        for sql in (
            "UPDATE crm.comment_moderation_config SET enabled=false",
            "UPDATE crm.comment_moderation_sources SET post_id='foreign'",
            "DELETE FROM crm.comment_moderation_actions",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(sql)
            db.rollback()


def test_normalization_rejects_old_own_or_unscoped_content():
    source = {"platform": "tiktok", "account_id": provider.TIKTOK}
    raw = {
        "id": "123",
        "message": "Info",
        "from": {"id": "visitor"},
        "createdTime": datetime.now(UTC).isoformat(),
    }
    since = datetime.now(UTC) - timedelta(days=1)
    assert mod.normalize(raw, source, since)
    for patch in (
        {"from": {"id": "visitor", "isOwner": True}},
        {"createdTime": "not-date"},
        {"parentId": "parent"},
        {"id": "../../admin"},
        {"message": "x" * 1601},
        {"createdTime": datetime.now().isoformat()},
    ):
        assert mod.normalize({**raw, **patch}, source, since) is None


def test_classifier_requires_tool_free_closed_json(monkeypatch):
    for result in (
        {"ok": True, "tools": 1, "response": "{}"},
        {"ok": True, "tools": False, "response": "{}"},
        {"ok": True, "tools": 0, "response": "not json"},
    ):
        monkeypatch.setattr(mod.bridge, "request", lambda *_, value=result, **__: value)
        with pytest.raises(ValueError):
            mod.classify({"message": "info"}, {"knowledge": "Acacías"})


def test_ads_route_does_not_broaden_inbox_provider(monkeypatch):
    class Conn:
        def request(self, method, path, **kwargs):
            assert method == "GET"
            assert path.startswith(
                "/api/v1/ads/aabbccddeeff001122334455/comments?placement=facebook"
            )

        def getresponse(self):
            class Response:
                status = 200

                def read(self, _n):
                    return b'{"comments":[]}'

            return Response()

        def close(self):
            pass

    monkeypatch.setattr(provider, "https_connection", lambda host, timeout: Conn())
    assert provider.ads_get({"api_key": "test"}, "aabbccddeeff001122334455") == {"comments": []}
    with pytest.raises(ValueError):
        provider.ads_get({"api_key": "test"}, "../../accounts")


def test_tiktok_observed_page_cursor_is_used_for_freshness(moderation, monkeypatch):
    url, source, row, raw, calls = moderation
    with psycopg.connect(url, row_factory=dict_row) as db:
        db.execute(
            "UPDATE crm.comment_moderation_sources SET platform='tiktok',account_id=%s,ad_id=NULL WHERE id=%s",
            (provider.TIKTOK, source["id"]),
        )
        db.execute(
            "UPDATE crm.comment_moderation_observations SET page_cursor='page-two' WHERE source_id=%s",
            (source["id"],),
        )
        source = db.execute(
            "SELECT * FROM crm.comment_moderation_sources WHERE id=%s", (source["id"],)
        ).fetchone()
        row = db.execute(
            "SELECT * FROM crm.comment_moderation_observations WHERE source_id=%s", (source["id"],)
        ).fetchone()
    cursors = []

    def pages(_source, _credentials, _ads, cursor=None):
        cursors.append(cursor)
        return ([deepcopy(raw)] if cursor == "page-two" else []), None

    monkeypatch.setattr(mod, "comments", pages)
    with connect() as db:
        mod.process(db, source, row)
    assert cursors == ["page-two"]
    assert calls.count("replyToInboxPost") == 1


def test_guard_locks_before_reading_policy_revision(moderation):
    _url, source, _row, _raw, _calls = moderation
    with connect() as db:

        class Ordered:
            def __init__(self):
                self.queries = []

            def execute(self, query, *args):
                self.queries.append(query)
                return db.execute(query, *args)

        ordered = Ordered()
        mod.guard(ordered, source)
        assert "lock_comment_moderation_owner()" in ordered.queries[0]
        assert "SELECT * FROM crm.comment_moderation_config" in ordered.queries[1]


def test_backfill_keeps_reading_new_head_comments(moderation, monkeypatch):
    _url, source, _row, raw, _calls = moderation
    source = {**source, "cursor": "older-page"}
    cursors = []

    def pages(_source, _credentials, _ads, cursor=None):
        cursors.append(cursor)
        return ([{**raw, "id": "new-head"}] if cursor is None else []), None

    monkeypatch.setattr(mod, "comments", pages)
    with connect() as db:
        mod.sweep(db, source)
        assert db.execute(
            "SELECT 1 FROM crm.comment_moderation_observations WHERE comment_id='new-head'"
        ).fetchone()
    assert cursors == [None, "older-page"]
