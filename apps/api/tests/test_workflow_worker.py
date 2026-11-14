"""Pure workflow policy tests: no database or real provider calls."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.workflows.models import Document
from app.workflows.worker import scheduled_at


def document(nodes=None):
    return {
        "entry_id": "one",
        "nodes": nodes
        or [
            {
                "id": "one",
                "kind": "end",
                "label": "Fin",
                "position": {"x": 0, "y": 0},
                "settings": {},
            }
        ],
        "schedule": {
            "timezone": "America/Bogota",
            "days": [1, 2, 3, 4, 5],
            "start_time": "09:00",
            "end_time": "17:00",
            "daily_limit": 10,
        },
        "stop_on_reply": True,
    }


def test_valid_graph_and_schedule():
    value = Document.model_validate(document())
    monday = datetime(2026, 11, 16, 15, tzinfo=UTC)
    assert scheduled_at(value.schedule.model_dump(), monday) == monday
    assert scheduled_at(
        value.schedule.model_dump(), datetime(2026, 11, 14, 15, tzinfo=UTC)
    ) == datetime(2026, 11, 16, 14, tzinfo=UTC)
    assert scheduled_at(
        value.schedule.model_dump(), datetime(2026, 11, 16, 22, tzinfo=UTC)
    ) == datetime(2026, 11, 17, 14, tzinfo=UTC)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["nodes"][0].update(next_id="one"),
        lambda d: d["nodes"].append(
            {
                "id": "two",
                "kind": "end",
                "label": "Fin",
                "position": {"x": 0, "y": 0},
                "settings": {},
            }
        ),
        lambda d: d["nodes"][0].update(settings={"url": "https://evil.test"}),
        lambda d: d["schedule"].update(days=[]),
        lambda d: d["schedule"].update(start_time="23:00", end_time="09:00"),
        lambda d: d["nodes"][0].update(kind="wait", settings={"hours": 721}),
        lambda d: d["nodes"][0].update(kind="crm_note", settings={"body": "{{secret}}"}),
    ],
)
def test_invalid_graph_is_rejected(change):
    data = document()
    change(data)
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_fixed_placeholders_and_branch_edges():
    data = document(
        [
            {
                "id": "one",
                "kind": "condition",
                "label": "Etapa",
                "position": {"x": 0, "y": 0},
                "settings": {"field": "stage", "operator": "equals", "value": "new"},
                "on_true": "two",
                "on_false": "two",
            },
            {
                "id": "two",
                "kind": "crm_note",
                "label": "Nota",
                "position": {"x": 0, "y": 0},
                "settings": {"body": "Hola {{nombre}}"},
                "next_id": "three",
            },
            {
                "id": "three",
                "kind": "end",
                "label": "Fin",
                "position": {"x": 0, "y": 0},
                "settings": {},
            },
        ]
    )
    assert len(Document.model_validate(data).nodes) == 3
