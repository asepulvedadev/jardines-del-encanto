"""Forward-compatible provider preferences without live providers or databases."""

from unittest.mock import patch

from app.control import service


class Database:
    def execute(self, *args):
        return self

    def fetchall(self):
        return [
            {"key": "zernio", "enabled": False, "version": 1},
            {"key": "future_provider_unknown", "enabled": False, "version": 1},
        ]


def test_unknown_provider_preferences_do_not_break_existing_catalogue():
    with (
        patch("app.hermes.bridge.health", return_value={"available": False}),
        patch("app.voice.service.state", return_value={"available": False, "verified": False}),
        patch(
            "app.social.routes.settings",
            return_value={"configured": False, "oauth": {}, "connections": []},
        ),
    ):
        assert [row["key"] for row in service.connection_views(Database())] == ["zernio"]
