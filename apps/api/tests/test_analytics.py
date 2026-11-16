"""Deterministic private analytics contract; no provider calls or customer writes."""

import io
import json
from contextlib import nullcontext
from datetime import UTC, date, datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.crm import security
from app.main import app

WEBSITE = "b3626251-a835-4832-939d-85f4c2bc598d"
NOW = datetime(2026, 11, 17, 4, 30, tzinfo=UTC)


class Database:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchall(self):
        return self.rows


@pytest.fixture
def analytics(monkeypatch):
    from app.analytics import service

    monkeypatch.delenv("UMAMI_ENABLED", raising=False)
    monkeypatch.delenv("UMAMI_API_KEY", raising=False)
    monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
    monkeypatch.delenv("UMAMI_BASE_URL", raising=False)
    db = Database()
    monkeypatch.setattr(service, "connect", lambda: nullcontext(db))
    return service, db


@pytest.fixture
def client(analytics):
    app.dependency_overrides[security.session] = lambda: {"id": "test-admin", "role": "admin"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(security.session, None)


def configured(monkeypatch):
    monkeypatch.setenv("UMAMI_ENABLED", "1")
    monkeypatch.setenv("UMAMI_API_KEY", "umami_test_private_credential")
    monkeypatch.setenv("UMAMI_WEBSITE_ID", WEBSITE)


def provider(monkeypatch, service, responses=None):
    payloads = responses or {
        "stats": {"pageviews": 15, "visitors": 4, "visits": 6},
        "pageviews": {
            "pageviews": [{"x": "2026-11-16 00:00:00", "y": 15}],
            "sessions": [{"x": "2026-11-16T00:00:00", "y": 6}],
        },
        "event": [
            {"x": "whatsapp_click", "y": 3},
            {"x": "plan_open", "y": 8},
            {"x": "secret_customer_phone_123", "y": 90},
        ],
        "utmSource": [
            {"x": "facebook", "y": 3},
            {"x": None, "y": 2},
            {"x": "private@example.test", "y": 1},
        ],
    }
    calls = []

    def read(base, website, token, endpoint, params):
        calls.append((base, website, token, endpoint, params))
        return payloads[params.get("type", endpoint)]

    monkeypatch.setattr(service, "_request", read)
    return calls


def test_anonymous_rejected_before_configuration_or_database():
    response = TestClient(app).get("/crm/analytics/summary?days=7")
    assert response.status_code == 401
    assert response.json() == {"detail": "authentication_required"}
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("query", ["days=2", "days=07", "days=7&days=7", "url=x", "days=7&key=x"])
def test_query_rejects_unknown_duplicate_or_invalid_keys(client, analytics, query):
    _, db = analytics
    response = client.get("/crm/analytics/summary?" + query)
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_input"}
    assert db.calls == []


def test_unconfigured_is_not_fake_zero_and_keeps_authoritative_registrations(client, analytics):
    _, db = analytics
    db.rows = [
        {
            "day": datetime.now(UTC).astimezone(ZoneInfo("America/Bogota")).date(),
            "count": 503,
        }
    ]
    result = client.get("/crm/analytics/summary").json()
    assert result["status"] == "not_configured"
    assert result["days"] == 7
    assert result["totals"]["visitors"] is None
    assert result["totals"]["pageviews"] is None
    assert result["totals"]["registrations"] == 503
    assert all(point["pageviews"] is None for point in result["daily"])
    assert len(db.calls) == 1
    assert "crm.landing_registrations" in db.calls[0][0]
    assert "LIMIT" not in db.calls[0][0].upper()
    assert "crm.contacts" not in db.calls[0][0]


def test_bogota_day_range_and_direct_sql_counts_exceed_workspace_limit(analytics):
    from app.analytics.models import SummaryInput

    service, db = analytics
    db.rows = [{"day": date(2026, 11, 16), "count": 503}]
    result = service.summary(SummaryInput(days=7), now=NOW)
    assert result["totals"]["registrations"] == 503
    assert result["daily"][-1]["date"] == "2026-11-16"
    assert result["daily"][0]["date"] == "2026-11-10"
    assert result["daily"][-1]["registrations"] == 503
    assert result["timezone"] == "America/Bogota"
    zone, start, end = db.calls[0][1]
    assert zone == "America/Bogota"
    assert start.isoformat() == "2026-11-10T00:00:00-05:00"
    assert end == NOW


def test_ready_whitelists_events_sources_and_fills_days(analytics, monkeypatch):
    from app.analytics.models import SummaryInput

    service, _ = analytics
    configured(monkeypatch)
    calls = provider(monkeypatch, service)
    result = service.summary(SummaryInput(days=7), now=NOW)
    assert result["status"] == "ready"
    assert result["totals"] == {
        "visitors": 4,
        "sessions": 6,
        "pageviews": 15,
        "clicks": 11,
        "registrations": 0,
    }
    assert result["daily"][0]["pageviews"] == 0
    assert result["daily"][-1]["sessions"] == 6
    assert {event["name"] for event in result["events"]} <= service.EVENT_NAMES
    assert {row["name"] for row in result["sources"]} == {"facebook", "direct", "other"}
    serialized = json.dumps(result)
    assert "private" not in serialized and "secret_customer" not in serialized
    assert len(calls) == 4
    assert all(call[4]["timezone"] == "America/Bogota" for call in calls)
    assert all(call[4]["hostname"] == "jardinesdelencanto.site" for call in calls)
    assert calls[0][4]["startAt"] == 1794286800000
    assert result["updated_at"] == "2026-11-17T04:30:00+00:00"


def test_valid_zero_provider_is_ready_not_unavailable(analytics, monkeypatch):
    from app.analytics.models import SummaryInput

    service, _ = analytics
    configured(monkeypatch)
    provider(
        monkeypatch,
        service,
        {
            "stats": {"pageviews": 0, "visitors": 0, "visits": 0},
            "pageviews": {"pageviews": [], "sessions": []},
            "event": [],
            "utmSource": [],
        },
    )
    result = service.summary(SummaryInput(days=1), now=NOW)
    assert result["status"] == "ready"
    assert result["totals"]["visitors"] == 0
    assert result["daily"] == [
        {"date": "2026-11-16", "pageviews": 0, "sessions": 0, "registrations": 0}
    ]


@pytest.mark.parametrize("failure", [ValueError("private-token"), TimeoutError("private-token")])
def test_provider_error_is_sanitized_and_registration_facts_survive(
    analytics, monkeypatch, failure
):
    from app.analytics.models import SummaryInput

    service, db = analytics
    configured(monkeypatch)
    db.rows = [{"day": date(2026, 11, 16), "count": 2}]
    monkeypatch.setattr(service, "_request", Mock(side_effect=failure))
    result = service.summary(SummaryInput(days=1), now=NOW)
    assert result["status"] == "unavailable"
    assert result["totals"]["clicks"] is None
    assert result["totals"]["registrations"] == 2
    assert result["events"] == [] and result["sources"] == []
    assert "private-token" not in json.dumps(result)


def test_malformed_provider_counts_fail_closed(analytics, monkeypatch):
    from app.analytics.models import SummaryInput

    service, _ = analytics
    configured(monkeypatch)
    provider(
        monkeypatch,
        service,
        {
            "stats": {"pageviews": True, "visitors": 0, "visits": 0},
            "pageviews": {"pageviews": [], "sessions": []},
            "event": [],
            "utmSource": [],
        },
    )
    assert service.summary(SummaryInput(days=7), now=NOW)["status"] == "unavailable"


def test_transport_bounded_no_redirect_no_proxy_and_private_bearer(analytics, monkeypatch):
    service, _ = analytics
    raw = io.BytesIO(b'{"visitors":0}')
    raw.headers = {"Content-Type": "application/json"}
    raw.status = 200
    opener = Mock()
    opener.open.return_value = raw
    build = Mock(return_value=opener)
    monkeypatch.setattr(service, "build_opener", build)
    assert service._request("http://umami:3000", WEBSITE, "private-token", "stats", {}) == {
        "visitors": 0
    }
    request = opener.open.call_args.args[0]
    assert request.full_url == f"http://umami:3000/api/websites/{WEBSITE}/stats?"
    assert request.get_header("Authorization") == "Bearer private-token"
    assert opener.open.call_args.kwargs["timeout"] == 3
    assert any(handler.__class__.__name__ == "NoRedirect" for handler in build.call_args.args)
    assert any(getattr(handler, "proxies", None) == {} for handler in build.call_args.args)
    large = io.BytesIO(b" " * (service.MAX_RESPONSE + 1))
    large.headers = {"Content-Type": "application/json"}
    large.status = 200
    opener.open.return_value = large
    with pytest.raises(ValueError):
        service._request("http://umami:3000", WEBSITE, "private-token", "stats", {})


def test_sara_and_dashboard_use_same_read_service(client, analytics, monkeypatch):
    from app.control import extensions
    from app.control import service as control
    from app.hermes import broker, developer

    service, db = analytics
    result = {"status": "not_configured", "contract": "shared"}
    read = Mock(return_value=result)
    monkeypatch.setattr(service, "summary", read)
    assert client.get("/crm/analytics/summary?days=30").json() == result
    args = control.validate("analytics.summary", {"days": 30})
    assert control.execute(db, "analytics.summary", args, {"id": "admin"}) == result
    monkeypatch.setattr(control, "lock", Mock())
    monkeypatch.setattr(control, "revisions", Mock(return_value={}))
    assert broker.dispatch(db, "analytics.summary", {"days": 30}, {"id": "admin"}) == {
        "result": result
    }
    assert db.calls == []
    assert read.call_count == 3
    assert all(call.args[0].days == 30 for call in read.call_args_list)
    assert "analytics.summary" in control.READ_ACTIONS
    assert "analytics.summary" in developer.ACTIONS
    assert "analytics.summary" in extensions.SAFE_ACTIONS
    with pytest.raises(HTTPException):
        control.validate("analytics.summary", {"days": 30, "token": "not-allowed"})


@pytest.mark.parametrize(
    "base",
    [
        "http://outside.test",
        "https://user:password@umami.test",
        "https://umami.test/path",
        "https://umami.test?token=private",
        "file:///private",
        "https://umami.test/#private",
    ],
)
def test_owner_configuration_still_rejects_unsafe_credential_destinations(
    analytics, monkeypatch, base
):
    from app.analytics.models import SummaryInput

    service, _ = analytics
    configured(monkeypatch)
    monkeypatch.setenv("UMAMI_BASE_URL", base)
    read = Mock(side_effect=AssertionError("must_not_fetch"))
    monkeypatch.setattr(service, "_request", read)
    assert service.summary(SummaryInput(), now=NOW)["status"] == "unavailable"
    read.assert_not_called()


def test_redirect_refusal_and_invalid_json_are_bounded(analytics, monkeypatch):
    service, _ = analytics
    with pytest.raises(ValueError):
        service.NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://external.test")
    opener = Mock()
    monkeypatch.setattr(service, "build_opener", lambda *args: opener)
    for payload, content_type, status in [
        (b'{"visitors":NaN}', "application/json", 200),
        (b'{"visitors":0}', "text/html", 200),
        (b'{"visitors":0}', "application/json", 302),
    ]:
        response = io.BytesIO(payload)
        response.headers = {"Content-Type": content_type}
        response.status = status
        opener.open.return_value = response
        with pytest.raises(ValueError):
            service._request("http://umami:3000", WEBSITE, "private-token", "stats", {})


@pytest.mark.parametrize("days", [True, "7", 0, 14, 31])
def test_sara_period_model_is_strict(days):
    from pydantic import ValidationError

    from app.analytics.models import SummaryInput

    with pytest.raises(ValidationError):
        SummaryInput(days=days)


def test_disabled_collection_does_not_report_provider_as_ready(analytics, monkeypatch):
    from app.analytics.models import SummaryInput

    service, _ = analytics
    configured(monkeypatch)
    monkeypatch.delenv("UMAMI_ENABLED")
    read = Mock(side_effect=AssertionError("must_not_fetch"))
    monkeypatch.setattr(service, "_request", read)
    assert service.summary(SummaryInput(), now=NOW)["status"] == "not_configured"
    read.assert_not_called()


def test_umami_35_day_bucket_z_suffix_is_not_shifted_twice(analytics, monkeypatch):
    from app.analytics.models import SummaryInput

    service, _ = analytics
    configured(monkeypatch)
    provider(
        monkeypatch,
        service,
        {
            "stats": {"pageviews": 6, "visitors": 4, "visits": 4},
            "pageviews": {
                "pageviews": [{"x": "2026-11-16T00:00:00Z", "y": 6}],
                "sessions": [{"x": "2026-11-16T00:00:00Z", "y": 4}],
            },
            "event": [],
            "utmSource": [],
        },
    )
    result = service.summary(SummaryInput(days=7), now=NOW)
    assert result["status"] == "ready"
    assert result["daily"][-1] == {
        "date": "2026-11-16",
        "pageviews": 6,
        "sessions": 4,
        "registrations": 0,
    }
    assert result["daily"][-2]["pageviews"] == 0


@pytest.mark.parametrize(
    "label",
    [
        "2026-11-16T00:00:00Z",
        "2026-11-16T00:00:00+00:00",
        "2026-11-16T00:00:00-05:00",
        "2026-11-16T00:00:00+05:00",
        "2026-11-16 00:00:00",
        "2026-11-16",
    ],
)
def test_valid_iso_bucket_labels_preserve_calendar_date(analytics, label):
    service, _ = analytics
    assert service._date(label) == "2026-11-16"


@pytest.mark.parametrize(
    "label",
    [
        "2026-02-30T00:00:00Z",
        "2026-11-16T29:00:00Z",
        "2026-11-16T00:00:00Zinvalid",
        "20261116",
        1794787200000,
    ],
)
def test_invalid_iso_bucket_labels_remain_rejected(analytics, label):
    service, _ = analytics
    with pytest.raises(ValueError):
        service._date(label)


def test_day_series_does_not_expand_requested_date_range(analytics):
    service, _ = analytics
    assert service._series(
        [
            {"x": "2026-11-15T00:00:00Z", "y": 3},
            {"x": "2026-11-16T00:00:00Z", "y": 6},
            {"x": "2026-11-17T00:00:00Z", "y": 4},
        ],
        ["2026-11-16"],
    ) == {"2026-11-16": 6}
