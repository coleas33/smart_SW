"""Feature 013's four optional record fields (T006, `data-model.md` section 3).

| Record | Field | Default | Omitted from the dump when |
|---|---|---|---|
| `Finding` | `source` | `code` | `code` |
| `EvidenceRequest` | `source` | `model` | `model` |
| `EvidenceRequest` | `allow_text` | false | false |
| `CoverageItem` | `source` | `code` | `code` |
| `ReviewSession` | `drawing_read` | `None` | `None` |

Every one is optional and omitted at its default (FR-053), so every committed session - the
attention, replay and any later fixture - round-trips to its own bytes, and the tool results
that carry a record at its kind's default keep theirs (`contracts/sources.md` section 1). The
defaults differ on purpose: each is the record kind's usual author, so an older session reads
as it was written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from swreview.findings import Finding, build_finding
from swreview.report.session import (
    CoverageItem,
    CoverageScope,
    EvidenceRequest,
    ReviewSession,
    load_session,
    save_session,
)
from tests.support.contracts import load_contract
from tests.unit.test_session import PACKAGE, build_session, session_validator

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def committed_sessions() -> list[Path]:
    """Every committed file shaped like a `session.json`, wherever a feature put it."""
    found: list[Path] = []
    for path in sorted(FIXTURES.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(document, dict) and {"session_id", "timing", "coverage"} <= set(document):
            found.append(path)
    return found


def a_finding(**changes: Any) -> Finding:
    finding = build_session().findings[0]
    return finding.model_copy(update=changes) if changes else finding


def a_request(**changes: Any) -> EvidenceRequest:
    fields: dict[str, Any] = {
        "id": "ER-001",
        "what": "The usable thread depth of the tapped hole",
        "why": "fastener.engagement",
        "entity_ids": ["hol:0001"],
        "status": "open",
        "answer": None,
        "answered_at": None,
    }
    fields.update(changes)
    return EvidenceRequest(**fields)


def an_item(**changes: Any) -> CoverageItem:
    fields: dict[str, Any] = {
        "check": "fasteners",
        "scope": CoverageScope(component_ids=["cmp:0001"]),
        "reason": "every screw engages its thread",
        "error": None,
    }
    fields.update(changes)
    return CoverageItem(**fields)


# --- the defaults, and the dump that omits them ------------------------------------------------


def test_a_finding_is_code_written_by_default_and_says_so_only_when_it_is_not() -> None:
    finding = a_finding()

    assert finding.source == "code"
    assert "source" not in finding.model_dump(mode="json")
    assert a_finding(source="model").model_dump(mode="json")["source"] == "model"


def test_build_finding_writes_the_default() -> None:
    """The one constructor every check uses is code; the model's one writer says `model` (T097)."""
    finding = build_finding(
        finding_id="F-002",
        check="fit.clearance",
        title="Clearance fit",
        status="suspected",
        severity="low",
        package=PACKAGE,
        configuration="Default",
        observed="observed",
        requirement="requirement",
        recommended_action="action",
        component_ids=["cmp:0001"],
    )
    assert finding.source == "code"


def test_a_request_is_model_written_by_default_and_offers_no_text_box() -> None:
    request = a_request()

    assert (request.source, request.allow_text) == ("model", False)
    assert {"source", "allow_text"}.isdisjoint(request.model_dump(mode="json"))


def test_a_code_question_with_a_text_box_dumps_both_fields() -> None:
    request = a_request(source="code", allow_text=True, question="Are these bought parts?")
    dumped = request.model_dump(mode="json")

    assert (dumped["source"], dumped["allow_text"]) == ("code", True)


def test_a_coverage_item_is_code_written_by_default() -> None:
    item = an_item()

    assert item.source == "code"
    assert "source" not in item.model_dump(mode="json")
    assert an_item(source="model").model_dump(mode="json")["source"] == "model"


def test_drawing_read_is_absent_until_recorded() -> None:
    session = build_session()

    assert session.drawing_read is None
    assert "drawing_read" not in session.model_dump(mode="json")


@pytest.mark.parametrize("mode", ["none", "open_only", "opens_closed"])
def test_each_drawing_read_mode_is_dumped(mode: str) -> None:
    assert build_session(drawing_read=mode).model_dump(mode="json")["drawing_read"] == mode


@pytest.mark.parametrize(
    ("build", "field", "value"),
    [
        (a_finding, "source", "engineer"),
        (a_request, "source", "engineer"),
        (an_item, "source", "engineer"),
        (a_request, "allow_text", "yes"),
    ],
)
def test_a_value_outside_the_vocabulary_is_refused(build: Any, field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        type(build()).model_validate({**build().model_dump(mode="json"), field: value})


def test_an_unknown_drawing_read_mode_is_refused() -> None:
    with pytest.raises(ValidationError):
        build_session(drawing_read="always")


# --- the file: round trips, and the contract -----------------------------------------------------


def test_there_are_committed_sessions_to_round_trip() -> None:
    assert len(committed_sessions()) >= 7


@pytest.mark.parametrize(
    "path", committed_sessions(), ids=lambda path: f"{path.parent.name}/{path.name}"
)
def test_every_committed_session_round_trips_to_its_own_bytes(path: Path, tmp_path: Path) -> None:
    target = save_session(load_session(path), tmp_path / "session.json")

    assert target.read_text(encoding="utf-8") == path.read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    )


def test_every_new_value_round_trips_and_validates(tmp_path: Path) -> None:
    session = build_session(
        findings=[a_finding(source="model")],
        evidence_requests=[a_request(source="code", allow_text=True)],
        drawing_read="open_only",
    )
    session.coverage.checked.append(an_item(source="model"))
    path = save_session(session, tmp_path / "session.json")

    written = json.loads(path.read_text(encoding="utf-8"))
    session_validator().validate(written)
    loaded = load_session(path)
    assert loaded == session
    assert isinstance(loaded, ReviewSession)


def test_every_default_value_validates_with_the_fields_absent(tmp_path: Path) -> None:
    written = build_session().model_dump(mode="json")

    session_validator().validate(written)


DEFINITIONS = load_contract("review-session.schema.json")


@pytest.mark.parametrize(
    ("definition", "field", "values"),
    [
        ("Finding", "source", ["code", "model"]),
        ("EvidenceRequest", "source", ["code", "model"]),
        ("CoverageItem", "source", ["code", "model"]),
    ],
)
def test_the_contract_carries_each_source_as_an_optional_token(
    definition: str, field: str, values: list[str]
) -> None:
    schema = DEFINITIONS["$defs"][definition]

    assert sorted(schema["properties"][field]["enum"]) == values
    assert field not in schema["required"]
    assert "omitted" in schema["properties"][field]["description"]


def test_the_contract_carries_allow_text_and_drawing_read_as_optional() -> None:
    request = DEFINITIONS["$defs"]["EvidenceRequest"]
    allow_text = request["properties"]["allow_text"]
    drawing_read = DEFINITIONS["properties"]["drawing_read"]

    assert allow_text["type"] == "boolean" and "allow_text" not in request["required"]
    assert sorted(drawing_read["enum"]) == ["none", "open_only", "opens_closed"]
    assert "drawing_read" not in DEFINITIONS["required"]
    assert "omitted" in allow_text["description"] and "omitted" in drawing_read["description"]


@pytest.mark.parametrize(
    ("definition", "model"),
    [("Finding", Finding), ("EvidenceRequest", EvidenceRequest), ("CoverageItem", CoverageItem)],
)
def test_the_contract_names_exactly_the_models_fields(definition: str, model: Any) -> None:
    assert set(DEFINITIONS["$defs"][definition]["properties"]) == set(model.model_fields)


def test_the_contract_names_exactly_the_sessions_fields() -> None:
    assert set(DEFINITIONS["properties"]) == set(ReviewSession.model_fields)
