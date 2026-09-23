"""The contact list on the review session (feature 010 T019, `data-model.md` section 9).

A contact is its own record on its own optional list: not a finding (the ranking never
reads it) and not coverage (a list hidden in a bucket would be found by string convention).
The list is additive - omitted from `session.json` when empty - so every session written
before this feature round-trips to its own bytes (FR-028).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from swreview.report.session import Contact, ContactIdAllocator, ReviewSession, load_session
from tests.support.contracts import contract_validator
from tests.unit.test_session import build_session

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def contact(**overrides: object) -> Contact:
    fields: dict[str, object] = {
        "id": "C-001",
        "kind": "zero_volume",
        "group_key": "cmp:0001|cmp:0003",
        "configuration": "Default",
        "interference_ids": ["int:0001", "int:0002"],
        "component_ids": ["cmp:0001", "cmp:0003"],
        "volume_mm3": 0.0,
        "joint_id": None,
        "reason": (
            "cmp:0001 and cmp:0003 touch at nominal in configuration Default: SOLIDWORKS "
            "reported 0.0 mm3 (2 pairs); this is a contact, not an interference."
        ),
        "tool_result_ids": [3],
    }
    fields.update(overrides)
    return Contact(**fields)  # type: ignore[arg-type]


def test_a_contact_validates() -> None:
    record = contact()

    assert record.kind == "zero_volume"
    assert record.volume_mm3 == 0.0


def test_a_contact_refuses_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        contact(severity="high")


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", "F-001"), ("id", "C-1"), ("kind", "overlap"), ("component_ids", ["cmp:0001"])],
    ids=["finding id", "short id", "unknown kind", "one part"],
)
def test_a_contact_refuses_what_it_cannot_be(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        contact(**{field: value})


def test_a_possible_only_contact_carries_no_volume() -> None:
    assert contact(kind="possible_only", volume_mm3=None).volume_mm3 is None


def test_contact_ids_are_allocated_from_c_001() -> None:
    ids = ContactIdAllocator()

    assert [next(ids), next(ids), next(ids)] == ["C-001", "C-002", "C-003"]


def test_the_list_defaults_to_empty_and_is_omitted_from_session_json() -> None:
    session = build_session()

    assert session.contacts == []
    assert "contacts" not in session.model_dump(mode="json")
    assert '"contacts"' not in session.model_dump_json()


def test_a_session_with_contacts_writes_and_reads_them_back() -> None:
    session = build_session(
        contacts=[contact(), contact(id="C-002", kind="possible_only", volume_mm3=None)]
    )

    loaded = ReviewSession.model_validate_json(session.model_dump_json())

    assert loaded.contacts == session.contacts


def test_a_session_with_contacts_validates_against_the_contract() -> None:
    session = build_session(contacts=[contact()])

    contract_validator("review-session.schema.json").validate(session.model_dump(mode="json"))


def test_contacts_is_a_property_of_the_contract_and_not_required() -> None:
    schema = contract_validator("review-session.schema.json").schema

    assert "contacts" in schema["properties"]
    assert "contacts" not in schema["required"]
    assert schema["properties"]["contacts"]["items"] == {"$ref": "#/$defs/Contact"}


def committed_sessions() -> list[Path]:
    paths = sorted(FIXTURES.rglob("session*.json"))
    assert paths, "no committed session fixture to round-trip"
    return paths


@pytest.mark.parametrize("path", committed_sessions(), ids=lambda path: path.name)
def test_every_committed_session_round_trips_to_its_own_bytes(path: Path) -> None:
    """A session written before this feature has no `contacts` key and must not gain one."""
    written = path.read_text(encoding="utf-8").replace("\r\n", "\n")

    session = load_session(path)

    assert session.model_dump_json(indent=2) + "\n" == written
