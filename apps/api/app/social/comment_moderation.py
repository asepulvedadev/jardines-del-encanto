"""Owner-scoped, durable comment review. Unknown writes are never replayed."""

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from ..control import service as control
from ..crm.database import connect
from ..hermes import bridge
from ..inbox import service as inbox_service
from ..sara import profile as shared_profile
from . import comment_policy as policy
from . import comment_provider as provider
from . import config

LOCK = 9142082
INTERVAL = 300


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def guard(db, source=None, version=None):
    if not db.execute("SELECT crm.lock_comment_moderation_owner() AS allowed").fetchone()[
        "allowed"
    ]:
        raise ValueError("moderation_owner_disabled")
    cfg = db.execute("SELECT * FROM crm.comment_moderation_config WHERE singleton").fetchone()
    if (
        not cfg
        or not cfg["enabled"]
        or cfg["profile_id"] != provider.PROFILE
        or (version is not None and cfg["version"] != version)
    ):
        raise ValueError("moderation_disabled")
    control.require_connections(db, "zernio", "hermes", *((source["platform"],) if source else ()))
    credentials, ads = config.required(), provider.ads_credentials()
    if (
        credentials["profile_id"] != cfg["profile_id"]
        or digest(credentials) != cfg["credential_revision"]
        or digest(ads) != cfg["ads_revision"]
    ):
        raise ValueError("moderation_credentials_changed")
    if source:
        actual = db.execute(
            "SELECT * FROM crm.comment_moderation_sources WHERE id=%s FOR SHARE", (source["id"],)
        ).fetchone()
        fields = ("account_id", "platform", "post_id", "ad_id", "content_hash")
        if (
            not actual
            or any(actual[k] != source[k] for k in fields)
            or source["account_id"]
            != {"facebook": provider.FACEBOOK, "tiktok": provider.TIKTOK}.get(source["platform"])
        ):
            raise ValueError("moderation_scope_changed")
    return cfg, credentials, ads


def verify_source(source, credentials, ads):
    """Never infer project ownership from a shared Page/profile alone."""
    selected = inbox_service.account(credentials, source["account_id"])
    if selected["platform"] != source["platform"]:
        raise ValueError("moderation_platform_changed")
    if source["platform"] == "facebook":
        inbox_service.account(credentials, provider.ADS)
        result = provider.ads_get(ads, source["ad_id"], detail=True)
        ad = result.get("ad", result)
        creative = ad.get("creative") or {}
        text = creative.get("body") or ""
        if (
            ad.get("accountId") != provider.ADS
            or ad.get("profileId") != provider.PROFILE
            or creative.get("pageId") != provider.PAGE
            or creative.get("effectiveObjectStoryId") != source["post_id"]
        ):
            raise ValueError("moderation_ad_scope_changed")
    else:
        from ..inbox.models import Execute, validate

        spec, args = validate(
            Execute(
                operation="listInboxComments",
                account_id=provider.TIKTOK,
                query={"platform": "tiktok", "limit": 100},
            ),
            credentials,
        )
        result = provider.provider.request(credentials, spec, args)
        if (result.get("meta") or {}).get("accountsFailed") or (result.get("meta") or {}).get(
            "accountsSkipped"
        ):
            raise ValueError("moderation_partial_source")
        rows = [
            r
            for r in result.get("data", [])
            if r.get("id") == source["post_id"]
            and r.get("accountId") == provider.TIKTOK
            and r.get("platform") == "tiktok"
        ]
        if len(rows) != 1:
            raise ValueError("moderation_source_unavailable")
        text = rows[0].get("content") or ""
    if not policy.project_content(text) or digest(text) != source["content_hash"]:
        raise ValueError("moderation_project_changed")


def comments(source, credentials, ads, cursor=None):
    if source["platform"] == "facebook":
        result = provider.ads_get(ads, source["ad_id"], cursor)
        meta = result.get("meta") or {}
        if (
            meta.get("facebookAccountId") != provider.FACEBOOK
            or meta.get("effectiveStoryId") != source["post_id"]
            or meta.get("platform") != "facebook"
        ):
            raise ValueError("moderation_comment_scope_changed")
    else:
        result = provider.inbox(credentials, source, "getInboxPostComments", cursor=cursor)
    rows, page = result.get("comments"), result.get("pagination") or {}
    if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(r, dict) for r in rows):
        raise ValueError("moderation_page_invalid")
    next_cursor = page.get("cursor") or page.get("nextCursor")
    if page.get("hasMore") is False:
        next_cursor = None
    if page.get("hasMore") is True and not next_cursor:
        raise ValueError("moderation_cursor_missing")
    if next_cursor is not None and (
        not isinstance(next_cursor, str) or len(next_cursor) > 4000 or next_cursor == cursor
    ):
        raise ValueError("moderation_cursor_invalid")
    return rows, next_cursor


def normalize(row, source, since):
    cid, content, author = row.get("id"), row.get("message"), row.get("from") or {}
    author_id = author.get("id")
    if (
        not isinstance(cid, str)
        or not re.fullmatch(r"[A-Za-z0-9_:-]{1,200}", cid)
        or not isinstance(content, str)
        or not 1 <= len(content) <= 1600
        or not isinstance(author_id, str)
        or not 1 <= len(author_id) <= 200
        or author.get("isOwner") is True
        or author_id in (provider.PAGE, source["account_id"])
        or row.get("parentId")
        or row.get("isHidden") is True
    ):
        return None
    try:
        created = datetime.fromisoformat(row.get("createdTime") or row.get("created_time") or "")
        if (
            created.tzinfo is None
            or created < since
            or created > datetime.now(UTC) + timedelta(minutes=5)
        ):
            return None
    except (ValueError, TypeError):
        return None
    # Existing discussions may already have a human/agent response; don't double-answer.
    replies = row.get("replies") or []
    has_reply = bool(row.get("replyCount", 0) or replies)
    return {
        "id": cid,
        "message": content,
        "author_id": author_id,
        "created_at": created.isoformat(),
        "can_reply": row.get("canReply", source["platform"] == "facebook") is True,
        "can_hide": row.get("canHide", source["platform"] == "facebook") is True,
        "has_reply": has_reply,
    }


def sweep(db, source):
    cfg, credentials, ads = guard(db, source)
    db.commit()
    verify_source(source, credentials, ads)
    # Always revisit the head; a backfill cursor must not starve new arrivals.
    rows, cursor = comments(source, credentials, ads)
    pages = [(rows, None)]
    if source["cursor"]:
        older, cursor = comments(source, credentials, ads, source["cursor"])
        pages.append((older, source["cursor"]))
    for rows, page_cursor in pages:
        for row in rows:
            item = normalize(row, source, cfg["since_at"])
            if item:
                db.execute(
                    """INSERT INTO crm.comment_moderation_observations(source_id,comment_id,content,content_hash,page_cursor)
                    VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (source["id"], item["id"], Jsonb(item), digest(item), page_cursor),
                )
    db.execute(
        """UPDATE crm.comment_moderation_sources SET cursor=%s,last_scan_at=now(),
        next_scan_at=now()+interval '300 seconds',last_error=NULL WHERE id=%s""",
        (cursor, source["id"]),
    )
    db.commit()


def classify(item, published):
    result = bridge.request("/public-reply", policy.payload(item["message"], published), timeout=48)
    if result.get("ok") is not True or type(result.get("tools")) is not int or result["tools"] != 0:
        raise ValueError("moderation_classifier_unavailable")
    return policy.parse(result.get("response"))


def dispatch(db, source, row, action, reply, cfg_version, profile_version):
    """Commit once-only reservation before network; revalidate every external action."""
    if action not in ("reply", "hide", "private_reply"):
        raise ValueError("moderation_action_invalid")
    item = row["content"]
    if action == "private_reply" and (
        source["platform"] != "facebook"
        or not policy.private_requested(item["message"])
        or datetime.fromisoformat(item["created_at"]) < datetime.now(UTC) - timedelta(days=7)
    ):
        return
    saved = db.execute(
        """INSERT INTO crm.comment_moderation_actions(source_id,comment_id,action,
        config_version,profile_version,content_hash) VALUES(%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING id""",
        (
            source["id"],
            row["comment_id"],
            action,
            cfg_version,
            profile_version,
            row["content_hash"],
        ),
    ).fetchone()
    db.commit()
    if not saved:
        return
    sent = False
    try:
        with config.locked():
            control.lock(db)
            cfg, credentials, ads = guard(db, source, cfg_version)
            published = db.execute(
                "SELECT version FROM crm.sara_profile WHERE singleton FOR SHARE"
            ).fetchone()
            if not published or published["version"] != profile_version:
                raise ValueError("moderation_knowledge_changed")
            verify_source(source, credentials, ads)
            # A focused live read returns the requested original comment on Facebook.
            if source["platform"] == "facebook":
                fresh = provider.inbox(
                    credentials, source, "getInboxPostComments", comment=item["id"]
                )
                rows = [fresh.get("comment")] if fresh.get("comment") else []
            else:
                cursor = row.get("page_cursor")
                rows = []
                for _ in range(3):
                    page, next_cursor = comments(source, credentials, ads, cursor)
                    rows.extend(page)
                    if any(r.get("id") == item["id"] for r in page) or not next_cursor:
                        break
                    cursor = next_cursor
            current = [normalize(r, source, cfg["since_at"]) for r in rows if isinstance(r, dict)]
            current = [r for r in current if r and r["id"] == item["id"]]
            if len(current) != 1 or digest(current[0]) != row["content_hash"]:
                raise ValueError("moderation_comment_changed")
            if (action == "hide" and not current[0]["can_hide"]) or (
                action in ("reply", "private_reply")
                and (not current[0]["can_reply"] or current[0]["has_reply"])
            ):
                raise ValueError("moderation_action_unavailable")
            total = db.execute(
                "SELECT count(*) AS n FROM crm.comment_moderation_actions WHERE created_at>now()-interval '24 hours'"
            ).fetchone()["n"]
            if total > 100:
                raise ValueError("moderation_daily_limit")
            operation = {
                "reply": "replyToInboxPost",
                "private_reply": "sendPrivateReplyToComment",
                "hide": "hideInboxComment",
            }[action]
            sent = True
            result = provider.inbox(
                credentials,
                source,
                operation,
                comment=item["id"],
                message=reply if action != "hide" else None,
                key=str(saved["id"]),
            )
            receipt = {
                k: result[k]
                for k in ("status", "commentId", "messageId", "hidden", "platform")
                if k in result
            }
            db.execute(
                "UPDATE crm.comment_moderation_actions SET state='accepted',receipt=%s,updated_at=now() WHERE id=%s",
                (Jsonb(receipt), saved["id"]),
            )
            db.commit()
    except Exception:  # noqa: BLE001 - never log provider bodies or commenters
        db.rollback()
        db.execute(
            "UPDATE crm.comment_moderation_actions SET state=%s,error=%s,updated_at=now() WHERE id=%s",
            (
                "unknown" if sent else "blocked",
                "moderation_write_unknown" if sent else "moderation_guard_rejected",
                saved["id"],
            ),
        )
        db.commit()


def process(db, source, row):
    cfg, _, _ = guard(db, source)
    published = shared_profile.get(db)
    db.commit()
    verdict = classify(row["content"], published)
    action = policy.action(row["content"]["message"], verdict)
    if row["content"]["has_reply"]:
        action = "review"
    db.execute(
        """UPDATE crm.comment_moderation_observations SET category=%s,confidence=%s,
        state=%s,updated_at=now(),error=NULL WHERE source_id=%s AND comment_id=%s""",
        (
            verdict["category"],
            verdict["confidence"],
            "review" if action == "review" else "skipped" if action == "skip" else "processed",
            source["id"],
            row["comment_id"],
        ),
    )
    db.commit()
    if action in ("reply", "hide"):
        # Private reply first: a subsequent public reply changes replyCount and freshness.
        if action == "reply" and policy.private_requested(row["content"]["message"]):
            dispatch(
                db,
                source,
                row,
                "private_reply",
                verdict["reply"],
                cfg["version"],
                published["version"],
            )
        dispatch(db, source, row, action, verdict["reply"], cfg["version"], published["version"])


def tick():
    with connect() as db:
        if not db.execute("SELECT pg_try_advisory_lock(%s) AS held", (LOCK,)).fetchone()["held"]:
            return
        db.commit()
        cfg = db.execute("SELECT * FROM crm.comment_moderation_config WHERE singleton").fetchone()
        if not cfg or not cfg["enabled"]:
            return
        sources = db.execute(
            "SELECT * FROM crm.comment_moderation_sources ORDER BY next_scan_at LIMIT 20"
        ).fetchall()
        db.commit()
        for source in sources:
            if source["next_scan_at"] > datetime.now(UTC):
                continue
            try:
                sweep(db, source)
            except Exception:  # noqa: BLE001
                db.rollback()
                db.execute(
                    "UPDATE crm.comment_moderation_sources SET last_error='moderation_scan_failed',next_scan_at=now()+interval '300 seconds' WHERE id=%s",
                    (source["id"],),
                )
                db.commit()
        # Durable rate limit leaves most shared public-model capacity for WhatsApp.
        claimed = db.execute(
            "UPDATE crm.comment_moderation_runtime SET next_model_at=now()+interval '30 seconds' WHERE singleton AND next_model_at<=now() RETURNING singleton"
        ).fetchone()
        db.commit()
        if claimed:
            row = db.execute(
                "SELECT * FROM crm.comment_moderation_observations WHERE state='pending' AND next_attempt<=now() ORDER BY created_at LIMIT 1"
            ).fetchone()
            db.commit()
            if row:
                source = next((s for s in sources if s["id"] == row["source_id"]), None)
                try:
                    if not source:
                        raise ValueError("moderation_source_removed")
                    process(db, source, row)
                except Exception:  # noqa: BLE001
                    db.rollback()
                    db.execute(
                        "UPDATE crm.comment_moderation_observations SET attempts=attempts+1,state=CASE WHEN attempts>=2 THEN 'review' ELSE 'pending' END,next_attempt=now()+interval '300 seconds',error='moderation_classification_failed',updated_at=now() WHERE source_id=%s AND comment_id=%s",
                        (row["source_id"], row["comment_id"]),
                    )
                    db.commit()
        db.execute(
            "UPDATE crm.comment_moderation_runtime SET heartbeat_at=now(),last_error=NULL WHERE singleton"
        )
        db.commit()


def status():
    with connect() as db:
        cfg = db.execute(
            "SELECT enabled,version FROM crm.comment_moderation_config WHERE singleton"
        ).fetchone()
        runtime = db.execute(
            "SELECT heartbeat_at,last_error FROM crm.comment_moderation_runtime WHERE singleton"
        ).fetchone()
        sources = db.execute(
            "SELECT account_id,platform,post_id,last_scan_at,next_scan_at,last_error FROM crm.comment_moderation_sources ORDER BY platform,post_id"
        ).fetchall()
        counts = db.execute(
            "SELECT state,count(*) AS count FROM crm.comment_moderation_actions GROUP BY state"
        ).fetchall()
        reviews = db.execute(
            "SELECT count(*) AS n FROM crm.comment_moderation_observations WHERE state='review'"
        ).fetchone()["n"]
    return {
        "enabled": bool(cfg and cfg["enabled"] and os.getenv("SARA_COMMENT_WORKER_ENABLED") == "1"),
        "policy_enabled": bool(cfg and cfg["enabled"]),
        "interval_seconds": INTERVAL,
        "runtime": runtime,
        "sources": sources,
        "actions": counts,
        "needs_review": reviews,
    }
