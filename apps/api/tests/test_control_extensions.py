"""Sara-owned typed extensions never grant host or policy authority."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from test_control_plane import controlled, item  # noqa: F401
from test_crm import authenticated  # noqa: F401
from test_hermes_broker import issue

from app.control import service


def lifecycle(client, action, arguments):
    return client.post(
        "/crm/hermes/actions",
        json={
            "action": "control.extension." + action,
            "arguments": arguments,
        },
    )


def draft(client, kind="tool", definition=None):
    response = lifecycle(
        client,
        "create",
        {
            "kind": kind,
            "name": "Extensión Sara",
            "definition": definition
            or {"action": "crm.contact.create", "defaults": {"source": "web"}},
        },
    )
    assert response.status_code == 200, response.text
    assert "proposals" not in response.json()
    return response.json()["result"]


def test_extension_draft_install_test_and_business_write_still_requires_approval(controlled):
    client, owner, _ = controlled
    extension = draft(client)
    assert extension["origin"] == "sara" and extension["enabled"] is False
    preview = lifecycle(client, "test", {"id": extension["id"], "version": 1})
    assert preview.status_code == 200 and preview.json()["result"]["valid"] is True
    assert preview.json()["result"]["side_effects"] is False
    assert client.get("/crm/workspace").json()["contacts"] == []
    installed = lifecycle(client, "install", {"id": extension["id"], "version": 1})
    assert installed.status_code == 200
    assert installed.json()["result"]["effective"] is True
    assert installed.json()["result"]["version"] == 2
    response = client.post(
        "/crm/hermes/actions",
        json={
            "action": "custom." + extension["id"],
            "arguments": {"name": "Cliente", "phone": "3001234567"},
        },
    )
    assert response.status_code == 200 and len(response.json()["proposals"]) == 1
    assert response.json()["proposals"][0]["action"] == "crm.contact.create"
    assert client.get("/crm/workspace").json()["contacts"] == []
    with psycopg.connect(owner) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM crm.control_audit WHERE action='control.extension.test'"
            ).fetchone()[0]
            == 1
        )
    assert "control.item.create" not in service.READ_ACTIONS
    assert "control.extension.create" not in service.READ_ACTIONS
    original = client.post(
        "/crm/hermes/actions",
        json={
            "action": "control.item.create",
            "arguments": {"kind": "skill", "name": "Humana", "definition": {"content": "# Guía"}},
        },
    )
    assert original.status_code == 200 and original.json()["proposals"]


@pytest.mark.parametrize(
    ("kind", "definition"),
    [
        ("tool", {"action": "control.connection.update"}),
        ("plugin", {"actions": ["crm.workspace", "control.item.create"]}),
        ("script", {"steps": [{"action": "control.extension.create", "arguments": {}}]}),
        ("tool", {"action": "social.connect"}),
        ("tool", {"action": "custom.00000000-0000-0000-0000-000000000001"}),
        ("script", {"code": "print(1)"}),
        ("connection", {"adapter": "application", "actions": ["crm.workspace"]}),
    ],
)
def test_privileged_nested_unknown_and_code_definitions_are_rejected(controlled, kind, definition):
    client, owner, _ = controlled
    response = lifecycle(
        client, "create", {"kind": kind, "name": "No autorizada", "definition": definition}
    )
    assert response.status_code == 422
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.control_items").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0


def test_only_own_sara_items_can_be_managed_and_updates_require_reinstall(controlled):
    client, owner, _ = controlled
    human = item(client, "skill", {"content": "# Humana"})
    for action in ("install", "test", "update"):
        assert lifecycle(client, action, {"id": human["id"], "version": 1}).status_code == 404
    extension = draft(client, "skill", {"content": "# Primera guía"})
    assert lifecycle(client, "install", {"id": extension["id"], "version": 1}).status_code == 200
    updated = lifecycle(
        client,
        "update",
        {"id": extension["id"], "version": 2, "definition": {"content": "# Segunda guía"}},
    )
    assert updated.status_code == 200
    assert updated.json()["result"]["enabled"] is False and updated.json()["result"]["version"] == 3
    assert lifecycle(client, "install", {"id": extension["id"], "version": 2}).status_code == 409
    with psycopg.connect(owner) as db:
        db.execute("INSERT INTO crm.users(username,password_hash) VALUES ('other','unusable')")
        db.execute(
            "UPDATE crm.control_items SET actor_id=(SELECT id FROM crm.users WHERE username='other') WHERE id=%s",
            (extension["id"],),
        )
    assert lifecycle(client, "test", {"id": extension["id"], "version": 3}).status_code == 404


def test_additive_alias_never_overrides_disabled_canonical_or_protected_human_tool(controlled):
    client, _, _ = controlled
    protected = item(client, definition={"action": "crm.workspace"}, enabled=True)
    first = draft(client, definition={"action": "crm.workspace"})
    second = draft(client, definition={"action": "crm.workspace"})
    assert first["id"] != second["id"]
    assert lifecycle(client, "install", {"id": first["id"], "version": 1}).status_code == 200
    assert (
        client.patch(
            "/crm/control/items/" + protected["id"], json={"version": 1, "enabled": False}
        ).status_code
        == 200
    )
    assert lifecycle(client, "install", {"id": second["id"], "version": 1}).status_code == 409
    catalog = client.get("/crm/control/catalog").json()
    assert (
        next(row for row in catalog["capabilities"] if row["key"] == "crm.workspace")["enabled"]
        is False
    )
    assert next(row for row in catalog["items"] if row["id"] == first["id"])["effective"] is False
    denied = client.patch(
        "/crm/control/items/" + first["id"],
        json={
            "version": 2,
            "definition": {"action": "control.connection.update"},
            "enabled": True,
        },
    )
    assert denied.status_code == 422


def test_next_claim_only_and_call_dedup_preserve_frozen_authority(controlled):
    client, owner, _ = controlled
    _, _, headers = issue(client, owner)
    before = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert before.status_code == 200, before.text
    call = {
        "call_id": "create",
        "action": "control.extension.create",
        "arguments": {
            "kind": "tool",
            "name": "Lectura",
            "definition": {"action": "crm.workspace"},
        },
    }
    created = client.post("/internal/hermes/call", json=call, headers=headers)
    assert created.status_code == 200
    assert client.post("/internal/hermes/call", json=call, headers=headers).json() == created.json()
    extension = created.json()["result"]
    installed = client.post(
        "/internal/hermes/call",
        headers=headers,
        json={
            "call_id": "install",
            "action": "control.extension.install",
            "arguments": {"id": extension["id"], "version": 1},
        },
    )
    assert installed.json()["result"]["effective"] is True
    custom = "custom." + extension["id"]
    denied = client.post(
        "/internal/hermes/call",
        headers=headers,
        json={"call_id": "use", "action": custom, "arguments": {}},
    )
    assert denied.json()["result"]["error"] == "capability_not_in_run"
    _, _, fresh = issue(client, owner)
    claimed = client.post("/internal/hermes/claim", json={}, headers=fresh)
    assert claimed.status_code == 200, claimed.text
    schema = claimed.json()["tools"][0]["function"]
    assert custom in schema["parameters"]["properties"]["action"]["enum"]
    assert len(schema["description"].encode()) <= 16384
    assert (
        client.post(
            "/internal/hermes/call",
            headers=fresh,
            json={"call_id": "use", "action": custom, "arguments": {}},
        ).json()["result"]["contacts"]
        == []
    )


def test_install_race_optimistic_version_and_invalid_inputs_are_atomic(controlled):
    client, owner, _ = controlled
    extension = draft(
        client, "script", {"steps": [{"action": "crm.workspace", "arguments": {"limit": 1}}]}
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: (
                    lifecycle(client, "install", {"id": extension["id"], "version": 1}).status_code
                ),
                range(2),
            )
        )
    assert sorted(results) == [200, 409]
    assert (
        lifecycle(
            client,
            "create",
            {
                "kind": "skill",
                "name": "No atajo",
                "definition": {"content": "# Hola"},
                "enabled": True,
            },
        ).status_code
        == 422
    )
    invalid = lifecycle(
        client,
        "create",
        {
            "kind": "script",
            "name": "Inválida",
            "definition": {"steps": [{"action": "crm.contact.create", "arguments": {}}]},
        },
    )
    assert invalid.status_code == 422
    preview = lifecycle(client, "test", {"id": extension["id"], "version": 2}).json()["result"]
    assert preview["valid"] is True and preview["side_effects"] is False
    with psycopg.connect(owner) as db:
        assert db.execute("SELECT count(*) FROM crm.hermes_proposals").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM crm.control_items").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("kind", "definition", "arguments"),
    [
        ("skill", {"content": "# Revisar clientes sin inventar datos"}, None),
        ("tool", {"action": "crm.workspace", "defaults": {"limit": 1}}, {}),
        (
            "plugin",
            {"actions": ["crm.workspace"], "instructions": "Consultar antes de proponer."},
            {"action": "crm.workspace", "arguments": {}},
        ),
        ("script", {"steps": [{"action": "crm.workspace", "arguments": {"limit": 1}}]}, {}),
    ],
)
def test_each_extension_kind_installs_and_only_dispatches_fixed_actions(
    controlled, kind, definition, arguments
):
    client, _, _ = controlled
    extension = draft(client, kind, definition)
    assert lifecycle(client, "test", {"id": extension["id"], "version": 1}).json()["result"][
        "valid"
    ]
    result = lifecycle(client, "install", {"id": extension["id"], "version": 1})
    assert result.status_code == 200 and result.json()["result"]["effective"]
    if arguments is not None:
        response = client.post(
            "/crm/hermes/actions",
            json={
                "action": "custom." + extension["id"],
                "arguments": arguments,
            },
        )
        assert response.status_code == 200 and not response.json().get("proposals")
    assert client.get("/crm/workspace").json()["contacts"] == []


def test_failed_update_leaves_installed_definition_and_human_permissions_unchanged(controlled):
    client, owner, _ = controlled
    extension = draft(client, "tool", {"action": "crm.workspace"})
    assert lifecycle(client, "install", {"id": extension["id"], "version": 1}).status_code == 200
    with psycopg.connect(owner) as db:
        before = db.execute(
            "SELECT definition,enabled,version FROM crm.control_items WHERE id=%s",
            (extension["id"],),
        ).fetchone()
        audit_before = db.execute("SELECT count(*) FROM crm.control_audit").fetchone()[0]
    response = lifecycle(
        client,
        "update",
        {
            "id": extension["id"],
            "version": 2,
            "definition": {"action": "control.extension.install"},
        },
    )
    assert response.status_code == 422
    with psycopg.connect(owner) as db:
        assert (
            db.execute(
                "SELECT definition,enabled,version FROM crm.control_items WHERE id=%s",
                (extension["id"],),
            ).fetchone()
            == before
        )
        assert db.execute("SELECT count(*) FROM crm.control_audit").fetchone()[0] == audit_before
    assert (
        lifecycle(
            client, "update", {"id": extension["id"], "version": 2, "enabled": False}
        ).status_code
        == 422
    )


def test_extensions_cannot_bypass_revoked_claim_or_pending_business_approval(controlled):
    client, owner, _ = controlled
    human = item(client, definition={"action": "crm.contact.create"}, enabled=True)
    extension = draft(client)
    assert lifecycle(client, "install", {"id": extension["id"], "version": 1}).status_code == 200
    _, _, headers = issue(client, owner)
    claim = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert claim.status_code == 200, claim.text
    response = client.post(
        "/internal/hermes/call",
        headers=headers,
        json={
            "call_id": "propose",
            "action": "custom." + extension["id"],
            "arguments": {"name": "Propuesta", "phone": "3001234567"},
        },
    )
    proposal = response.json()["proposals"][0]
    assert (
        client.patch(
            "/crm/control/items/" + human["id"], json={"version": 1, "enabled": False}
        ).status_code
        == 200
    )
    replay = client.post(
        "/internal/hermes/call",
        headers=headers,
        json={
            "call_id": "revoked",
            "action": "custom." + extension["id"],
            "arguments": {"name": "No autorizada", "phone": "3001234568"},
        },
    )
    assert replay.json()["result"]["error"] == "item_disabled"
    assert (
        client.post(
            "/crm/hermes/proposals/" + proposal["id"] + "/approve",
            json={"version": proposal["version"]},
        ).status_code
        == 409
    )
    assert client.get("/crm/workspace").json()["contacts"] == []


def test_default_manifest_fits_runtime_and_lifecycle_permission_can_be_paused(controlled):
    client, owner, _ = controlled
    _, _, headers = issue(client, owner)
    claim = client.post("/internal/hermes/claim", json={}, headers=headers)
    assert claim.status_code == 200, claim.text
    function = claim.json()["tools"][0]["function"]
    actions = function["parameters"]["properties"]["action"]["enum"]
    assert service.EXTENSION_ACTIONS <= set(actions)
    assert len(function["description"].encode()) <= 16384
    human = item(client, definition={"action": "control.extension.create"}, enabled=False)
    assert (
        lifecycle(
            client,
            "create",
            {"kind": "skill", "name": "Pausada", "definition": {"content": "# Guía"}},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/crm/control/items/" + human["id"], json={"version": 1, "enabled": True}
        ).status_code
        == 200
    )
    assert draft(client, "skill", {"content": "# Disponible"})["enabled"] is False
