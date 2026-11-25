"""The new inbound campaign never advertises the expired fair."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.social import onboarding


def test_campaign_closes_after_sunday_29_in_colombia():
    assert onboarding.WELCOME_UNTIL == datetime(2026, 11, 30, 5, tzinfo=UTC)
    assert (
        onboarding.WELCOME_UNTIL.astimezone(ZoneInfo("America/Bogota")).isoformat()
        == "2026-11-30T00:00:00-05:00"
    )


def test_welcome_uses_new_date_without_unconfirmed_venue_or_time():
    assert "domingo veintinueve de noviembre" in onboarding.SCRIPT
    assert "veintidós" not in onboarding.SCRIPT
    assert "Cámara de Comercio" not in onboarding.SCRIPT
    assert "8:00" not in onboarding.SCRIPT
    assert "Acacías, Meta" in onboarding.SCRIPT


def test_website_is_unchanged():
    assert onboarding.WEBSITE == "https://jardinesdelencanto.site/"
