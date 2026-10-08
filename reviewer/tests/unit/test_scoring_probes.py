"""The oracle and null builders and the SC-001 and SC-002 assertion, on fictional keys (T039).

`tests/support/scoring_probes.py` builds the reviews `test_committed_answer_keys.py` and the golden
scorecards score (`contracts/scoring.md` 9.2). The committed keys reach only some of its branches
today (demonstrated, suspected and unresolved defects, on parts and on a document); this file
reaches the rest on fictional keys over `tests/support` packages: a reference-keyed defect of each
reading (a joint's ids, a fit's dimensions), a family's `.oracle` check, the stand-in package, the
folder each review is written as, a key with no condition and one with no defect, and the
assertion failing when a finding matches two defects. Every id and description is fictional.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.checklist import load_checklist
from swreview.agent.events import EVENTS_FILE_NAME
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.benchmark.answer_key import current_stamp, load_answer_key
from swreview.benchmark.answer_key_model import AnswerKey
from swreview.benchmark.questions import CountRow
from swreview.report.session import ORIGIN_MARKS_VERSION, load_session
from swreview.report.summary import load_words
from swreview.tools.refs import resolve_dimension
from tests.support.answer_keys import write_key
from tests.support.packages import build_package
from tests.support.scoring_probes import (
    assert_oracle_and_null,
    assert_oracle_matches_only_its_own_defects,
    null_review,
    oracle_review,
    stand_in_package,
)
from tests.unit.test_drawing_finding_number_guard import FIRST, INGESTED, SECOND, guarded_package

PACKAGE = guarded_package(build_package)
"""`build_package`'s joint (the screw `fst:1` on `cmp:0002` in the tapped hole `hole:1` of
`cmp:0001`) and an ingested drawing `doc:3` whose two sheets carry one dimension each."""

BORE = {"document_id": INGESTED, "sheet": FIRST, "annotation": "DIM-1"}
SHAFT = {"document_id": INGESTED, "sheet": SECOND, "annotation": "DIM-2"}


def entry(entry_id: str, check: str, **fields: Any) -> dict[str, Any]:
    """A tuned-on entry on no parts and no documents, each replaced by what `fields` states."""
    return {
        "id": entry_id,
        "check": check,
        "component_ids": [],
        "document_ids": [],
        "tag": "tuned_on",
        "description": f"Fictional entry {entry_id}.",
        **fields,
    }


def defect(entry_id: str, check: str, status: str, **fields: Any) -> dict[str, Any]:
    """A known defect the model produces at `status`, each field replaced by what `fields`
    states."""
    return entry(entry_id, check, **{"producer": "model", "expected_status": status, **fields})


EVERY_KIND = [
    defect(
        "D-1",
        "fastener.bottoming",
        "unresolved",
        component_ids=["cmp:0001", "cmp:0002"],
        references=[{"fastener": "fst:1", "hole": "hole:1"}],
    ),
    defect(
        "D-2",
        "fit.size_only",
        "demonstrated",
        document_ids=[INGESTED],
        references=[{"bore": BORE, "shaft": SHAFT}],
        producer="code",
    ),
    defect(
        "D-3",
        "hygiene.*",
        "suspected",
        component_ids=["cmp:0001"],
        tag="held_out",
        held_out_against=current_stamp().model_dump(),
    ),
    defect("D-4", "drawing.manufacturing_inputs", "unresolved", document_ids=[INGESTED]),
]
"""One known defect of each shape the oracle builds: a joint on two parts, a fit on a drawing
document alone, a held-out family on a part, a drawing defect on a document."""

CONDITION = entry("C-1", "rms.folders.present", component_ids=["cmp:0002"])


def key(known_defects: list[dict[str, Any]], correct_conditions: list[dict[str, Any]]) -> AnswerKey:
    return AnswerKey.model_validate(
        {
            "key_format": 2,
            "package_id": "fict-oracle",
            "known_defects": known_defects,
            "correct_conditions": correct_conditions,
        }
    )


def events(folder: Path) -> list[dict[str, Any]]:
    lines = (folder / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


# --- the stand-in package --------------------------------------------------------------------


def test_the_stand_in_holds_each_named_component_once_and_each_named_document_with_its_entry() -> (
    None
):
    named = key(
        [defect("D-1", "rms.folders.ordered", "suspected", component_ids=["cmp:0007"])],
        [
            entry("C-1", "rms.folders.present", component_ids=["cmp:0008", "cmp:0007"]),
            entry("C-2", "hygiene.revision_present", document_ids=["doc:9"]),
        ],
    )

    stand_in = stand_in_package(named)

    assert [component.id for component in stand_in.components] == ["cmp:0007", "cmp:0008"]
    assert "doc:9" in [document.document_id for document in stand_in.documents]
    assert "doc:9" in [entry.document_id for entry in stand_in.manifest.entries]
    assert (stand_in.holes, stand_in.fasteners, stand_in.gaps) == ([], [], [])


def key_only_with_every_extension(folder: Path) -> AnswerKey:
    """A key-only key, read as `test_committed_answer_keys.py` reads one, holding a known defect,
    a forbidden entry on a part and a document, an unanswerable request on another document, and
    a question-count rule with `min` 1 naming a part and that document on another item, so its
    oracle question matches no unanswerable request."""
    path = write_key(
        folder,
        "fict-key-only",
        known_defects=[{"check": "hygiene.revision_present", "component_ids": ["cmp:0007"]}],
        forbidden=[{"checks": ["rms.*"], "component_ids": ["cmp:0008"], "document_ids": ["doc:9"]}],
        unanswerable_requests=[{"documents": ["doc:10"], "item": "interference"}],
        question_counts=[
            {"item": "interfaces.fit", "ids": ["cmp:0011", "doc:10"], "min": 1, "max": 1}
        ],
        key_only=True,
    )
    return load_answer_key(path, package=None, checklist=load_checklist(), words=load_words())


def test_the_stand_in_also_holds_every_id_the_extension_lists_name(tmp_path: Path) -> None:
    """A forbidden entry's parts and documents, an unanswerable request's documents, and a
    question-count rule's ids: a rule's id is a document where the key names it one, and a
    component instance otherwise."""
    stand_in = stand_in_package(key_only_with_every_extension(tmp_path))

    assert [component.id for component in stand_in.components] == [
        "cmp:0007",
        "cmp:0008",
        "cmp:0011",
    ]
    documents = [document.document_id for document in stand_in.documents]
    assert documents[-2:] == ["doc:9", "doc:10"]
    assert [entry.document_id for entry in stand_in.manifest.entries][-2:] == ["doc:9", "doc:10"]


def test_a_key_only_key_s_question_rule_naming_ids_gets_an_oracle_that_asks_it(
    tmp_path: Path,
) -> None:
    """The oracle's one `request_evidence` call names the rule's ids, which the stand-in holds, so
    the call is recorded and counted and SC-001 holds on every column the key grades."""
    key = key_only_with_every_extension(tmp_path / "answer_keys")

    oracle, null = assert_oracle_and_null(key, stand_in_package(key), tmp_path / "reviews")

    assert oracle.question_counts == [CountRow(entry="Q-1", count=1, min=1, max=1)]
    assert null.question_counts == [CountRow(entry="Q-1", count=0, min=1, max=1)]


# --- the oracle ------------------------------------------------------------------------------


def test_the_oracle_is_a_package_folder_with_origin_marks_and_one_session_started_event(
    tmp_path: Path,
) -> None:
    oracle_review(key(EVERY_KIND, [CONDITION]), PACKAGE, tmp_path)

    assert load_session(tmp_path / SESSION_FILE_NAME).origin_marks == ORIGIN_MARKS_VERSION
    assert [event["type"] for event in events(tmp_path)] == ["session.started"]


def test_the_oracle_states_one_finding_per_known_defect_as_its_entry_reads(tmp_path: Path) -> None:
    session = oracle_review(key(EVERY_KIND, [CONDITION]), PACKAGE, tmp_path)

    joint, fit, family, drawing = session.findings
    assert [finding.source for finding in session.findings] == ["model"] * 4
    assert [finding.status for finding in session.findings] == [
        "unresolved",
        "demonstrated",
        "suspected",
        "unresolved",
    ]
    assert (joint.check, joint.component_ids, joint.inputs) == (
        "fastener.bottoming",
        ["cmp:0001", "cmp:0002"],
        ["fst:1", "hole:1"],
    )
    assert joint.coverage_limits
    dimensions = [resolve_dimension(PACKAGE, BORE), resolve_dimension(PACKAGE, SHAFT)]
    assert (fit.component_ids, fit.inputs) == ([], dimensions)
    assert fit.drawing_locations == [dimension.source for dimension in dimensions]
    assert fit.tool_result_ids == [step.index for step in session.steps]
    assert family.check == "hygiene.oracle"
    assert drawing.component_ids == [] and drawing.drawing_locations == []
    assert [entry.document_id for entry in drawing.provenance] == [INGESTED]
    assert drawing.coverage_limits


def test_an_oracle_with_no_demonstrated_defect_holds_no_step(tmp_path: Path) -> None:
    session = oracle_review(key(EVERY_KIND[2:], []), PACKAGE, tmp_path)

    assert session.steps == []


def test_a_folder_already_holding_a_review_is_refused(tmp_path: Path) -> None:
    null_review(PACKAGE, tmp_path)

    with pytest.raises(FileExistsError, match="its own folder"):
        oracle_review(key(EVERY_KIND, []), PACKAGE, tmp_path)


# --- the null review -------------------------------------------------------------------------


def test_the_null_review_is_an_empty_session_with_origin_marks_and_its_one_event(
    tmp_path: Path,
) -> None:
    session = null_review(PACKAGE, tmp_path)

    assert load_session(tmp_path / SESSION_FILE_NAME) == session
    assert session.origin_marks == ORIGIN_MARKS_VERSION
    assert (session.steps, session.findings, session.evidence_requests) == ([], [], [])
    assert [event["type"] for event in events(tmp_path)] == ["session.started"]


# --- the assertion ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("known_defects", "correct_conditions"),
    [(EVERY_KIND, [CONDITION]), (EVERY_KIND, []), ([], [CONDITION])],
    ids=["defects-and-a-condition", "no-condition", "no-defect"],
)
def test_sc_001_and_sc_002_hold_on_every_kind_of_key(
    known_defects: list[dict[str, Any]],
    correct_conditions: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    graded = key(known_defects, correct_conditions)

    oracle, null = assert_oracle_and_null(graded, PACKAGE, tmp_path)

    assert oracle.matched_defect_ids == [defect["id"] for defect in known_defects]
    assert null.false_alarm_finding_ids == []


def test_sc_002_fails_naming_an_oracle_finding_that_matches_two_defects(tmp_path: Path) -> None:
    overlapping = key(
        [
            defect("D-1", "hygiene.revision_present", "suspected", component_ids=["cmp:0001"]),
            defect(
                "D-2",
                "hygiene.revision_present",
                "suspected",
                component_ids=["cmp:0001", "cmp:0002"],
            ),
        ],
        [],
    )
    session = oracle_review(overlapping, PACKAGE, tmp_path)

    with pytest.raises(AssertionError, match="the oracle finding for D-1 matches"):
        assert_oracle_matches_only_its_own_defects(overlapping, session)
