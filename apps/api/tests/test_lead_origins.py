"""Dashboard groups reconcile all contacts without rewriting their provenance."""

from test_template_cohorts import authenticated, intake, seed_native  # noqa: F401

from app.crm.database import connect


def test_origin_totals_and_filters_are_complete_exclusive_and_read_only(intake):  # noqa: F811
    client, _ = intake
    records = []
    for index, source in enumerate(
        [
            "social_campaign",
            "social_campaign",
            "social_campaign",
            "web",
            "whatsapp",
            "in_person",
            "referral",
            "other",
        ]
    ):
        response = client.post(
            "/crm/contacts",
            json={
                "name": f"Contacto {index}",
                "phone": f"300123456{7 + index}" if index < 3 else f"301123456{index}",
                "source": source,
            },
        )
        assert response.status_code == 201, response.text
        records.append(response.json())
    with connect() as db:
        before = db.execute("SELECT * FROM crm.contacts ORDER BY id").fetchall()
        seed_native(db, records[0]["id"])
        owner = db.execute("SELECT id FROM crm.users LIMIT 1").fetchone()["id"]
        broadcast = db.execute(
            """INSERT INTO crm.whatsapp_broadcasts
            (id,actor_id,fingerprint,name,account_id,credential_revision,template_name,
             template_language,template_revision,template_payload,preview,consent_note)
            VALUES(gen_random_uuid(),%s,'fixture','Base de prueba','fixture','fixture',
                   'fixture','es','fixture','{}','fixture','fixture') RETURNING id""",
            (owner,),
        ).fetchone()["id"]
        for record in records[:2]:
            db.execute(
                "INSERT INTO crm.whatsapp_cold_leads VALUES(%s,%s,now())", (record["id"], broadcast)
            )
    data = client.get("/crm/workspace").json()
    origins = data["lead_origins"]
    assert {key: origins[key] for key in ("campaign", "template", "imported", "other")} == {
        "campaign": 1,
        "template": 1,
        "imported": 1,
        "other": 5,
    }
    assert (
        sum(origins[key] for key in ("campaign", "template", "imported", "other"))
        == data["counts"]["contacts"]
        == 8
    )
    assert {row["source"]: row["count"] for row in origins["other_sources"]} == {
        "web": 1,
        "whatsapp": 1,
        "in_person": 1,
        "referral": 1,
        "other": 1,
    }
    groups = {}
    for group in ("campaign", "template", "imported", "other"):
        filtered = client.post("/crm/broadcasts/filter", json={"cohort": group})
        assert filtered.status_code == 200, filtered.text
        body = filtered.json()
        groups[group] = {c["id"] for c in body["contacts"]}
        assert len(groups[group]) == origins[group]
        assert all(c["lead_origin"] == group for c in body["contacts"])
        assert {d["contact_id"] for d in body["deals"]} == groups[group]
        assert body["lead_origins"] == origins  # Global totals do not become filtered totals.
    assert sum(map(len, groups.values())) == len(set().union(*groups.values())) == 8
    # Existing raw import and broadcast filters retain their membership, including overlap.
    legacy = client.post("/crm/broadcasts/filter", json={"cold_only": True}).json()
    assert len(legacy["contacts"]) == data["counts"]["cold_leads"] == 2
    assert (
        client.post("/crm/broadcasts/filter", json={"campaign_id": str(broadcast)}).json()[
            "contacts"
        ]
        == []
    )
    with connect() as db:
        assert db.execute("SELECT * FROM crm.contacts ORDER BY id").fetchall() == before


def test_empty_origin_summary_is_real_zero(intake):  # noqa: F811
    client, _ = intake
    assert client.get("/crm/workspace").json()["lead_origins"] == {
        "campaign": 0,
        "template": 0,
        "imported": 0,
        "other": 0,
        "other_sources": [],
    }


def test_origin_summary_does_not_use_the_capped_contact_list(intake):  # noqa: F811
    client, _ = intake
    with connect() as db:
        db.execute("""INSERT INTO crm.contacts(name,phone,source)
            SELECT 'Fixture', '+57300' || lpad(n::text,7,'0'),
                   CASE WHEN n<=550 THEN 'social_campaign' ELSE 'web' END
            FROM generate_series(1,600) n""")
    data = client.get("/crm/workspace").json()
    assert len(data["contacts"]) == 500 and data["limited"]
    assert data["lead_origins"] == {
        "campaign": 550,
        "template": 0,
        "imported": 0,
        "other": 50,
        "other_sources": [{"source": "web", "count": 50}],
    }
    filtered = client.post("/crm/broadcasts/filter", json={"cohort": "other"}).json()
    assert len(filtered["contacts"]) == 50
    assert filtered["lead_origins"] == data["lead_origins"]
