"""Unit tests for the shared `RuleResult` constructors of `checks/rms/results.py` (T061).

`verdict` is the one under test here. It was written twice - once in `checks/rms/part.py`
over `Feature` subjects and once in `checks/rms/assembly.py` over mate and component
`Subject`s - and the two copies were the same four branches, which is the second mechanism
the constitution's DRY principle (Principle V) exists to refuse. The branches are asserted
here, once, on both subject shapes, so neither evaluator module can grow a private copy
that answers "a rule whose every subject was unresolved" differently from the other.

The rule evaluators' own tests (`test_rms_part_rules.py`, `test_rms_assembly_rules.py`)
still cover what each rule concludes; what is pinned here is only the shape the shared
helper gives that conclusion.
"""

from __future__ import annotations

import pytest

from swreview.checks.rms.assembly import Subject
from swreview.checks.rms.registry import RULES
from swreview.checks.rms.results import RuleResult, finding, verdict
from swreview.ir.models import Feature

DOCUMENT = "doc:2"
FAIL_RULE = RULES["rms.core.shell_last"]
WARN_RULE = RULES["rms.detail.holes_last"]


def _rows() -> tuple[object, object]:
    """One feature subject and one assembly subject, to pin the structural typing."""
    row = Feature(
        id="feat:0001",
        persist_ref="cmVm",
        persist_ref_scope=DOCUMENT,
        document_id=DOCUMENT,
        configuration="Default",
        name="Shell1",
        type_name="Shell",
        description="intent",
        index=0,
        depth=0,
        folder_id=None,
        suppressed=False,
        error_code=0,
        child_ids=[],
        parent_ids=[],
        sketch=None,
        fillet=None,
    )
    subject = Subject(
        id="mate:0001",
        name="COINCIDENT",
        type_name="mate",
        persist_ref="cmVm",
        persist_ref_scope=DOCUMENT,
        suppressed=False,
        configuration="Default",
    )
    return row, subject


def _violation(rule: object, row: object) -> RuleResult:
    return finding(
        rule,  # type: ignore[arg-type]
        DOCUMENT,
        [row],  # type: ignore[list-item]
        observed="something is out of order",
        recommended_action="put it back",
    )


@pytest.mark.parametrize("which", [0, 1])
def test_a_violation_replaces_the_pass(which: int) -> None:
    """A rule that failed on this document is not also `checked` for it."""
    row = _rows()[which]
    results = verdict(
        FAIL_RULE, DOCUMENT, violation=_violation(FAIL_RULE, row), passing=[row]
    )

    assert [item.outcome for item in results] == ["fail"]


@pytest.mark.parametrize("which", [0, 1])
def test_passing_subjects_alone_are_one_pass(which: int) -> None:
    row = _rows()[which]
    results = verdict(FAIL_RULE, DOCUMENT, passing=[row])

    assert [item.outcome for item in results] == ["pass"]
    assert results[0].subjects == [row.id]  # type: ignore[attr-defined]


@pytest.mark.parametrize("which", [0, 1])
def test_a_violation_and_an_unreadable_subject_land_in_two_buckets(which: int) -> None:
    row = _rows()[which]
    results = verdict(
        FAIL_RULE,
        DOCUMENT,
        violation=_violation(FAIL_RULE, row),
        passing=[row],
        unknown=[(row, "children unavailable")],
    )

    assert [item.outcome for item in results] == ["fail", "unresolved"]
    assert "children unavailable" in (results[1].reason or "")


@pytest.mark.parametrize("which", [0, 1])
def test_every_subject_unresolved_reports_only_that(which: int) -> None:
    """No vacuous pass beside it: the rule saw nothing it could grade."""
    row = _rows()[which]
    results = verdict(FAIL_RULE, DOCUMENT, unknown=[(row, "children unavailable")])

    assert [item.outcome for item in results] == ["unresolved"]
    assert results[0].subjects == [row.id]  # type: ignore[attr-defined]


def test_nothing_to_look_at_passes_vacuously() -> None:
    """A rule with no subject at all and no gap passes for the document itself."""
    results = verdict(WARN_RULE, DOCUMENT)

    assert [item.outcome for item in results] == ["pass"]
    assert results[0].subjects == []
    assert results[0].document_id == DOCUMENT
