"""Fixed Umami 3.5 aggregate reads, combined with authoritative landing registrations.

API shapes: docs.umami.is/docs/api-reference/get-website-{stats,pageviews,metrics}.
No visitor records, arbitrary dimensions, raw referrers or caller-controlled hosts.
"""

import json
import os
import re
from datetime import UTC, datetime, time, timedelta
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID
from zoneinfo import ZoneInfo

from ..crm.database import connect
from .models import SummaryInput

TIMEZONE = "America/Bogota"
ZONE = ZoneInfo(TIMEZONE)
MAX_RESPONSE = 131072
EVENT_NAMES = frozenset(
    {
        "whatsapp_click",
        "group_click",
        "visit_click",
        "plan_open",
        "registration_open",
    }
)
CLICK_EVENTS = EVENT_NAMES
SOURCES = frozenset({"facebook", "instagram", "tiktok", "google", "whatsapp", "direct", "other"})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("analytics_upstream_redirect")


def _configuration():
    if os.getenv("UMAMI_ENABLED") != "1":
        return None
    website, token = os.getenv("UMAMI_WEBSITE_ID"), os.getenv("UMAMI_API_KEY")
    if not website or not token:
        return None
    if str(UUID(website)) != website or len(token) > 4096:
        raise ValueError("analytics_configuration_invalid")
    if not all(33 <= ord(char) <= 126 for char in token):
        raise ValueError("analytics_configuration_invalid")
    base = os.getenv("UMAMI_BASE_URL", "http://umami:3000").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise ValueError("analytics_configuration_invalid")
    # Plaintext bearer credentials may only reach the owner-provisioned local service.
    if parsed.scheme == "http" and parsed.hostname not in {
        "umami",
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("analytics_configuration_invalid")
    return base, website, token


def _request(base, website, token, endpoint, params):
    if endpoint not in {"stats", "pageviews", "metrics"}:
        raise ValueError("analytics_endpoint_invalid")
    request = Request(
        f"{base}/api/websites/{website}/{endpoint}?{urlencode(params)}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    # Do not inherit ambient proxy settings or follow credential-bearing redirects.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=3) as response:
        if response.status != 200:
            raise ValueError("analytics_upstream_unavailable")
        if (
            response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise ValueError("analytics_upstream_invalid")
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("analytics_upstream_too_large")
    return json.loads(raw, parse_constant=lambda value: _invalid())


def _invalid():
    raise ValueError("analytics_upstream_invalid")


def _count(value):
    if type(value) is not int or not 0 <= value <= 9007199254740991:
        _invalid()
    return value


def _rows(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        _invalid()
    if any(not isinstance(row, dict) for row in value):
        _invalid()
    return value


def _date(value):
    if (
        not isinstance(value, str)
        or len(value) > 40
        or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", value)
    ):
        _invalid()
    # Umami 3.5 getDateSQL already applies the requested timezone before adding Z.
    # A daily x value labels a local calendar bucket, not an event timestamp.
    # Validate the complete ISO value but never apply another timezone conversion.
    parsed = datetime.fromisoformat(value)
    return parsed.date().isoformat()


def _series(value, expected):
    result = dict.fromkeys(expected, 0)
    seen = set()
    for row in _rows(value, 31):
        day, count = _date(row.get("x")), _count(row.get("y"))
        if day in seen:
            _invalid()
        seen.add(day)
        if day in result:
            result[day] = count
    return result


def _registration_days(db, start, end):
    return db.execute(
        """SELECT (created_at AT TIME ZONE %s)::date AS day, count(*) AS count
           FROM crm.landing_registrations
           WHERE created_at >= %s AND created_at <= %s GROUP BY 1 ORDER BY 1""",
        (TIMEZONE, start, end),
    ).fetchall()


def summary(data: SummaryInput, *, db=None, now=None):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    today = now.astimezone(ZONE).date()
    first = today - timedelta(days=data.days - 1)
    start = datetime.combine(first, time.min, tzinfo=ZONE)
    dates = [(first + timedelta(days=offset)).isoformat() for offset in range(data.days)]
    if db is None:
        with connect() as connection:
            registrations = _registration_days(connection, start, now)
    else:
        registrations = _registration_days(db, start, now)
    registered = dict.fromkeys(dates, 0)
    for row in registrations:
        day = row["day"].isoformat()
        if day in registered:
            registered[day] = int(row["count"])
    result = {
        "status": "not_configured",
        "timezone": TIMEZONE,
        "days": data.days,
        "updated_at": None,
        "totals": {
            "visitors": None,
            "sessions": None,
            "pageviews": None,
            "clicks": None,
            "registrations": sum(registered.values()),
        },
        "daily": [
            {"date": day, "pageviews": None, "sessions": None, "registrations": registered[day]}
            for day in dates
        ],
        "events": [],
        "sources": [],
    }
    try:
        config = _configuration()
        if config is None:
            return result
        params = {
            "startAt": int(start.timestamp() * 1000),
            "endAt": int(now.timestamp() * 1000),
            "timezone": TIMEZONE,
            "hostname": "jardinesdelencanto.site",
        }
        stats = _request(*config, "stats", params)
        series = _request(*config, "pageviews", {**params, "unit": "day"})
        events = _request(*config, "metrics", {**params, "type": "event", "limit": 100})
        sources = _request(*config, "metrics", {**params, "type": "utmSource", "limit": 100})
        if not isinstance(stats, dict) or not isinstance(series, dict):
            _invalid()
        counts = {
            "visitors": _count(stats.get("visitors")),
            "sessions": _count(stats.get("visits")),
            "pageviews": _count(stats.get("pageviews")),
        }
        pageviews = _series(series.get("pageviews"), dates)
        sessions = _series(series.get("sessions"), dates)
        safe_events = dict.fromkeys(sorted(EVENT_NAMES), 0)
        for row in _rows(events, 100):
            name = row.get("x")
            count = _count(row.get("y"))
            if isinstance(name, str) and name in safe_events:
                safe_events[name] += count
        safe_sources = {}
        for row in _rows(sources, 100):
            name = row.get("x")
            count = _count(row.get("y"))
            if name is not None and not isinstance(name, str):
                _invalid()
            normalized = "direct" if not name else name if name in SOURCES else "other"
            safe_sources[normalized] = safe_sources.get(normalized, 0) + count
        counts["clicks"] = sum(safe_events[name] for name in CLICK_EVENTS)
        result["totals"].update(counts)
        result.update(status="ready", updated_at=now.isoformat())
        result["daily"] = [
            {
                "date": day,
                "pageviews": pageviews[day],
                "sessions": sessions[day],
                "registrations": registered[day],
            }
            for day in dates
        ]
        result["events"] = [{"name": name, "count": count} for name, count in safe_events.items()]
        result["sources"] = [
            {"name": name, "count": count}
            for name, count in sorted(safe_sources.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        # Provider payloads, exception details, credentials and visitor data never reach clients.
        result["status"] = "unavailable"
        return result
