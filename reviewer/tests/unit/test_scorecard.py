"""The scorer: a finding credits only what it actually found (feature 014 T036, for T038).

`contracts/scoring.md` 3.1, 3.2, 3.3's first bullet, 5.5, 6, 7's slice-1 fields and 8 (FR-001,
FR-002, FR-004 to FR-006, FR-008). A finding matches an entry through the one matcher,
`benchmark/matching.py` (its own tests are `test_benchmark_matching.py`); this file pins what the
scorer makes of the matches:

1. **Known defects, 13A's table** (3.1). Of the findings matching a defect, any demonstrated or
   suspected one credits it (a status mismatch when it was expected unresolved); else an
   unresolved one flags it (expected unresolved) or leaves it flagged below expected; else it is
   missed only when nothing matched at all. Any `checked_within_scope` match clears it, whatever
   the row. Detected is credited or flagged (`matched_defect_ids`). Order never matters.
2. **Correct conditions** (3.2): contradicted by a demonstrated or suspected match, confirmed by a
   `checked_within_scope` one, `null` when the key holds none.
3. **False alarms** (3.3's first bullet): every demonstrated or suspected finding of the final
   state that credits no known defect, a contradiction included.
4. **Origins, graded items and recall** (5.5, 6): every finding's origin, every entry's id, kind
   and tag copied, recall read from the item tags by producer and tag, the set's flag checked
   against its key.

Every key is written through `tests/support/answer_keys.write_key` and every package is a
`tests/support/packages.build_package` saved at its set entry's path, so the loader's rows run as
they do in a real score. The tests of this file at `be01974` are each named where they went:
the prefix rule's tests (`:74-105`) and `test_score_run_classifies_findings_by_the_matching_rule`
(`:205`) are deleted with the rule, which the table tests replace; the rest are kept or moved, each
saying so. Every id and description is fictional.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest
from jsonschema import Draft202012Validator

from swreview.benchmark import scorecard as scorecard_module
from swreview.benchmark.answer_key_model import AnswerKey
from swreview.benchmark.scorecard import (
    Aggregate,
    PackageScore,
    Scorecard,
    render_scorecard_md,
    score_run,
)
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet
from swreview.checks.fastener import CHECK_BOTTOMING, check_fastener_joint
from swreview.findings import Finding
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from swreview.report.session import ReviewSession, Timing, save_session
from swreview.tools.context import context_for, use_context
from swreview.tools.recording import result_to_finding
from swreview.tools.refs import resolve_dimension
from tests.support.answer_keys import write_key
from tests.support.contracts import load_contract
from tests.support.findings import make_finding
from tests.support.packages import build_package, persist_ref
from tests.unit.test_checks_fastener import layer, mm, screw, tapped_hole
from tests.unit.test_drawing_finding_number_guard import (
    FIRST,
    INGESTED,
    SECOND,
    guarded_package,
    record,
)

PACKAGE = build_package()

TIMING = Timing(
    baseline_minutes=90.0,
    assisted_supervision_minutes=10.0,
    assisted_verification_minutes=8.0,
    false_alarm_handling_minutes=2.0,
    unattended_runtime_minutes=25.0,
)

JOINT = {"fastener": "fst:1", "hole": "hole:1"}
"""`build_package`'s one joint: the screw `fst:1` on the cover `cmp:0002` in the tapped hole
`hole:1` of the housing `cmp:0001`."""

BOTH_PARTS = ["cmp:0001", "cmp:0002"]

DRAWINGS = guarded_package(build_package)
"""`build_package`'s assembly with two drawings beside it: `INGESTED` (`doc:3`), whose two sheets
carry one dimension each, and a native one (`doc:4`)."""

BORE = {"document_id": INGESTED, "sheet": FIRST, "annotation": "DIM-1"}
SHAFT = {"document_id": INGESTED, "sheet": SECOND, "annotation": "DIM-2"}


def finding_with(status: str, finding_id: str = "F-001", **overrides: object) -> Finding:
    """A `hygiene.revision_present` finding of `status` on the housing, with the evidence each
    status needs: a cited step for a numeric one, a coverage limit for an unresolved one."""
    evidence: dict[str, object] = {
        "demonstrated": {"tool_result_ids": [0]},
        "checked_within_scope": {"tool_result_ids": [0]},
        "unresolved": {"coverage_limits": ["gap: the revision block was not read"]},
        "suspected": {},
    }[status]
    fields: dict[str, object] = {
        "finding_id": finding_id,
        "check": "hygiene.revision_present",
        "status": status,
        **evidence,
        **overrides,
    }
    return make_finding(**fields)


def make_session(session_id: UUID, findings: Sequence[Finding], timing: Timing) -> ReviewSession:
    return ReviewSession(
        session_id=session_id,
        package_id=PACKAGE.package_id,
        design_id=PACKAGE.design.design_id,
        started_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC),
        ended_at=datetime(2026, 9, 12, 9, 30, tzinfo=UTC),
        model="claude-opus-5",
        findings=list(findings),
        timing=timing,
    )


# --- the section 3.1 invariants, asserted on every scorecard this file builds (test 3) -------


def assert_invariants(scorecard: Scorecard) -> None:
    """Data-model section 8: matched, flagged below expected and missed are disjoint; every other
    defect is cleared; flagged and mismatches lie within matched and are disjoint; missed and
    cleared are disjoint."""
    for score in scorecard.per_package:
        defects = [item.id for item in score.graded_items if item.kind == "known_defect"]
        matched = set(score.matched_defect_ids)
        below = set(score.flagged_below_expected_defect_ids)
        missed = set(score.missed_defect_ids)
        cleared = set(score.cleared_defect_ids)
        flagged = set(score.flagged_defect_ids)
        mismatched = set(score.status_mismatch_defect_ids)
        assert not matched & below and not matched & missed and not below & missed, score
        assert set(defects) - matched - below - missed <= cleared, score
        assert flagged <= matched and mismatched <= matched and not flagged & mismatched, score
        assert not missed & cleared, score
        for listed in (
            score.matched_defect_ids,
            score.flagged_defect_ids,
            score.status_mismatch_defect_ids,
            score.flagged_below_expected_defect_ids,
            score.cleared_defect_ids,
            score.missed_defect_ids,
        ):
            assert listed == [defect for defect in defects if defect in listed], "key order"


def scored(run_dir: Path, answer_keys_dir: Path, benchmark_set: BenchmarkSet) -> Scorecard:
    """`score_run`, with the section 3.1 invariants asserted on what it returns."""
    scorecard = score_run(run_dir, answer_keys_dir, benchmark_set)
    assert_invariants(scorecard)
    return scorecard


# --- one package, written as a run leaves it ---------------------------------------------------


def write_package(
    tmp_path: Path,
    package_id: str,
    findings: Sequence[Finding],
    *,
    known_defects: Sequence[Mapping[str, Any]] = (),
    correct_conditions: Sequence[Mapping[str, Any]] = (),
    held_out: bool = False,
    package: EvidencePackage = PACKAGE,
    timing: Timing = TIMING,
) -> BenchmarkPackageRef:
    """One package of a run under `tmp_path`: its key in `tmp_path/answer_keys`, its package at
    its set entry's path and its session in `tmp_path/run/<package_id>`."""
    write_key(
        tmp_path / "answer_keys",
        package_id,
        known_defects=known_defects,
        correct_conditions=correct_conditions,
    )
    package_dir = tmp_path / "packages" / package_id
    save_package(package, package_dir)
    session_id = uuid5(UUID("33333333-4444-4555-8666-777777777777"), package_id)
    save_session(
        make_session(session_id, findings, timing), tmp_path / "run" / package_id / "session.json"
    )
    return BenchmarkPackageRef(package_id=package_id, path=package_dir, held_out=held_out)


def score_packages(tmp_path: Path, *refs: BenchmarkPackageRef) -> Scorecard:
    return scored(
        tmp_path / "run", tmp_path / "answer_keys", BenchmarkSet(name="pilot", packages=list(refs))
    )


def score_one(tmp_path: Path, findings: Sequence[Finding], **fields: Any) -> PackageScore:
    """The one package `pkg-a`'s score."""
    scorecard = score_packages(tmp_path, write_package(tmp_path, "pkg-a", findings, **fields))
    (score,) = scorecard.per_package
    return score


def outcome(score: PackageScore) -> dict[str, list[str]]:
    """The six defect lists of 3.1, by their short names."""
    return {
        "matched": score.matched_defect_ids,
        "flagged": score.flagged_defect_ids,
        "status_mismatch": score.status_mismatch_defect_ids,
        "flagged_below_expected": score.flagged_below_expected_defect_ids,
        "cleared": score.cleared_defect_ids,
        "missed": score.missed_defect_ids,
    }


def only(**lists: list[str]) -> dict[str, list[str]]:
    """`outcome`'s six lists, each empty but those named."""
    return {
        name: lists.get(name, [])
        for name in (
            "matched",
            "flagged",
            "status_mismatch",
            "flagged_below_expected",
            "cleared",
            "missed",
        )
    }


# --- the scoring fixture: six findings over four entries -------------------------------------


def build_scoring_fixture(
    tmp_path: Path, *, held_out: bool = True
) -> tuple[Path, Path, BenchmarkSet]:
    """One package exercising every classification, rewritten to format 2 on `DRAWINGS`.

    F-001 credits D-1 through its joint, F-002 credits D-3 (which took F-002's exact check: AK-4
    refuses `fastener.*` on a known defect), D-2 is missed, F-003 is a false alarm and F-004,
    the suspected fit on the correct condition's dimensions, contradicts C-1 and is a false alarm
    too (`scoring.md` 3.2). F-005 is unresolved and F-006 within scope. Every entry is tagged
    held out when the set flags the package held out, and tuned on otherwise.
    """
    tags: dict[str, Any] = {"tag": "held_out" if held_out else "tuned_on"}
    findings = [
        make_finding(
            finding_id="F-001",
            check="fastener.bottoming",
            status="suspected",
            component_ids=["cmp:0001"],
            inputs=["fst:1", "hole:1"],
        ),
        make_finding(
            finding_id="F-002",
            check="fastener.thread_mismatch",
            status="suspected",
            component_ids=["cmp:0002"],
        ),
        make_finding(
            finding_id="F-003",
            check="tolerance.stack",
            status="demonstrated",
            component_ids=["cmp:0001"],
            tool_result_ids=[0],
        ),
        make_finding(
            finding_id="F-004",
            check="fit.size_only",
            status="suspected",
            component_ids=["cmp:0001"],
            inputs=[resolve_dimension(DRAWINGS, BORE), resolve_dimension(DRAWINGS, SHAFT)],
        ),
        make_finding(
            finding_id="F-005",
            check="fastener.engagement",
            status="unresolved",
            component_ids=["cmp:0002"],
            coverage_limits=["gap: usable thread depth unknown"],
        ),
        make_finding(
            finding_id="F-006",
            check="mate.alignment",
            status="checked_within_scope",
            component_ids=["cmp:0001"],
            tool_result_ids=[0],
        ),
    ]
    ref = write_package(
        tmp_path,
        "pkg-a",
        findings,
        known_defects=[
            {
                "check": "fastener.bottoming",
                "component_ids": BOTH_PARTS,
                "references": [JOINT],
                **tags,
            },
            {"check": "drawing.manufacturing_inputs", "component_ids": ["cmp:0002"], **tags},
            {"check": "fastener.thread_mismatch", "component_ids": ["cmp:0002"], **tags},
        ],
        correct_conditions=[
            {
                "check": "fit.size_only",
                "component_ids": ["cmp:0001"],
                "document_ids": [INGESTED],
                "references": [{"bore": BORE, "shaft": SHAFT}],
                **tags,
            }
        ],
        held_out=held_out,
        package=DRAWINGS,
    )
    return tmp_path / "run", tmp_path / "answer_keys", BenchmarkSet(name="pilot", packages=[ref])


def test_the_scoring_fixture_scores_as_the_matcher_reads_it(tmp_path: Path) -> None:
    score = scored(*build_scoring_fixture(tmp_path)).per_package[0]

    assert outcome(score) == only(matched=["D-1", "D-3"], missed=["D-2"])
    assert score.valid_findings == 2
    assert score.missed_known_defects == 1
    assert score.false_alarm_finding_ids == ["F-003", "F-004"]
    assert score.false_alarms == 2
    assert score.unresolved_count == 1
    assert score.contradicted_condition_ids == ["C-1"]
    assert score.confirmed_condition_ids == []


def test_score_run_computes_timing_fields(tmp_path: Path) -> None:
    """Kept from `be01974` (`:221`), what it asserts unchanged."""
    scorecard = scored(*build_scoring_fixture(tmp_path))

    score = scorecard.per_package[0]
    assert score.baseline_minutes == pytest.approx(90.0)
    assert score.assisted_minutes == pytest.approx(20.0)
    assert score.unattended_runtime_minutes == pytest.approx(25.0)
    assert score.net_saved_minutes == pytest.approx(70.0)


def test_score_run_recall_is_read_from_the_item_tags(tmp_path: Path) -> None:
    """Moved by design from `be01974`'s `:233`, recall scoped to held-out packages by the set's
    flag: now read from the item tags (test 9). Every item of its key held out, it still reads
    2 of 3."""
    scorecard = scored(*build_scoring_fixture(tmp_path, held_out=True))

    assert scorecard.aggregate.recall == pytest.approx(2 / 3)
    assert scorecard.aggregate.held_out_packages == 1


def test_score_run_recall_of_a_key_whose_items_are_all_tuned_on_is_null(tmp_path: Path) -> None:
    """Moved by design from `be01974`'s `:243`, recall ignoring defects of packages the set did
    not hold out: every item tuned on, under the set flag of false test 10 requires, reads
    `null`."""
    scorecard = scored(*build_scoring_fixture(tmp_path, held_out=False))

    assert scorecard.aggregate.recall is None
    assert scorecard.aggregate.held_out_packages == 0


def test_score_run_false_alarm_rate(tmp_path: Path) -> None:
    """Moved by design from `be01974`'s `:252`: 2 of 4 where it read 1 of 3, since F-004, the
    suspected finding on the correct condition the scorer used to excuse
    (`scorecard.py:274-276`), is now a false alarm (`scoring.md` 3.2)."""
    scorecard = scored(*build_scoring_fixture(tmp_path))

    assert scorecard.aggregate.false_alarm_rate == pytest.approx(2 / 4)


def test_false_alarm_rate_is_none_with_zero_findings(tmp_path: Path) -> None:
    """Kept from `be01974` (`:286`), what it asserts unchanged."""
    timing = TIMING.model_copy(update={"baseline_minutes": 30.0})
    scorecard = score_packages(tmp_path, write_package(tmp_path, "pkg-c", [], timing=timing))

    assert scorecard.aggregate.false_alarm_rate is None


# --- 1. 13A's table, row by row (US1-3, US1-4, FR-002) ---------------------------------------


@pytest.mark.parametrize(
    ("expected", "status", "lists"),
    [
        ("unresolved", "unresolved", only(matched=["D-1"], flagged=["D-1"])),
        ("unresolved", "demonstrated", only(matched=["D-1"], status_mismatch=["D-1"])),
        ("unresolved", "suspected", only(matched=["D-1"], status_mismatch=["D-1"])),
        ("unresolved", "checked_within_scope", only(cleared=["D-1"])),
        ("unresolved", None, only(missed=["D-1"])),
        ("demonstrated", "demonstrated", only(matched=["D-1"])),
        ("demonstrated", "suspected", only(matched=["D-1"])),
        ("demonstrated", "unresolved", only(flagged_below_expected=["D-1"])),
        ("demonstrated", "checked_within_scope", only(cleared=["D-1"])),
        ("demonstrated", None, only(missed=["D-1"])),
        ("suspected", "demonstrated", only(matched=["D-1"])),
        ("suspected", "unresolved", only(flagged_below_expected=["D-1"])),
    ],
)
def test_13a_s_table_row_by_row(
    tmp_path: Path, expected: str, status: str | None, lists: dict[str, list[str]]
) -> None:
    """Demonstrated against suspected is never a mismatch (SP-8); a defect flagged below expected
    is in no recall figure and is no false alarm."""
    findings = [] if status is None else [finding_with(status)]
    defect = {
        "check": "hygiene.revision_present",
        "component_ids": ["cmp:0001"],
        "expected_status": expected,
        "tag": "held_out",
    }

    scorecard = score_packages(
        tmp_path, write_package(tmp_path, "pkg-a", findings, known_defects=[defect], held_out=True)
    )

    score = scorecard.per_package[0]
    assert outcome(score) == lists
    assert score.false_alarm_finding_ids == []
    assert scorecard.aggregate.recall == (1.0 if lists["matched"] else 0.0)


def test_the_table_scores_two_defects_of_both_expectations_side_by_side(tmp_path: Path) -> None:
    """One defect expected unresolved (D-1, on the housing) and one expected demonstrated (D-2, on
    the cover), each met by an unresolved finding: the first flagged, the second below expected."""
    defects = [
        {
            "check": "hygiene.revision_present",
            "component_ids": ["cmp:0001"],
            "expected_status": "unresolved",
        },
        {
            "check": "hygiene.revision_present",
            "component_ids": ["cmp:0002"],
            "expected_status": "demonstrated",
        },
    ]
    findings = [
        finding_with("unresolved", "F-001"),
        finding_with("unresolved", "F-002", component_ids=["cmp:0002"]),
    ]

    score = score_one(tmp_path, findings, known_defects=defects)

    assert outcome(score) == only(matched=["D-1"], flagged=["D-1"], flagged_below_expected=["D-2"])
    assert score.unresolved_count == 2
    assert score.false_alarm_finding_ids == []


# --- 2. two findings on one defect, in both orders (spec Edge Cases, US1-9, FR-005) ----------


@pytest.mark.parametrize("reverse", [False, True], ids=["in order", "reversed"])
@pytest.mark.parametrize(
    ("expected", "statuses", "lists"),
    [
        pytest.param(
            "unresolved",
            ("unresolved", "demonstrated"),
            only(matched=["D-1"], status_mismatch=["D-1"]),
            id="an unresolved and a demonstrated match on a defect expected unresolved",
        ),
        pytest.param(
            "demonstrated",
            ("checked_within_scope", "demonstrated"),
            only(matched=["D-1"], cleared=["D-1"]),
            id="cleared beside a credit",
        ),
        pytest.param(
            "demonstrated",
            ("checked_within_scope", "unresolved"),
            only(flagged_below_expected=["D-1"], cleared=["D-1"]),
            id="cleared beside an unresolved match on a defect expected demonstrated",
        ),
        pytest.param(
            "unresolved",
            ("checked_within_scope", "checked_within_scope"),
            only(cleared=["D-1"]),
            id="cleared alone, neither detected nor missed",
        ),
    ],
)
def test_two_findings_on_one_defect_score_the_same_in_either_order(
    tmp_path: Path,
    expected: str,
    statuses: tuple[str, str],
    lists: dict[str, list[str]],
    reverse: bool,
) -> None:
    ordered = reversed(statuses) if reverse else statuses
    findings = [
        finding_with(status, f"F-00{number}") for number, status in enumerate(ordered, start=1)
    ]
    defect = {
        "check": "hygiene.revision_present",
        "component_ids": ["cmp:0001"],
        "expected_status": expected,
    }

    score = score_one(tmp_path, findings, known_defects=[defect])

    assert outcome(score) == lists
    assert score.false_alarm_finding_ids == []


# --- 4. correct conditions, contradictions and the sibling rule (US1-8, US1-1, US1-6, US1-17) --

FOLDERS_DEFECT = {"check": "rms.folders.ordered", "component_ids": ["cmp:0001"]}
FOLDERS_CONDITION = {"check": "rms.folders.present", "component_ids": ["cmp:0001"]}
"""A correct condition and a known defect of its family on one part, which do not overlap: one
finding can match only one of the two exact checks."""


def test_a_demonstrated_finding_contradicting_a_condition_beside_a_defect_of_its_family(
    tmp_path: Path,
) -> None:
    """One false alarm, one contradiction, and the defect missed (US1-8)."""
    findings = [finding_with("demonstrated", check="rms.folders.present")]

    score = score_one(
        tmp_path, findings, known_defects=[FOLDERS_DEFECT], correct_conditions=[FOLDERS_CONDITION]
    )

    assert score.false_alarm_finding_ids == ["F-001"]
    assert score.contradicted_condition_ids == ["C-1"]
    assert score.confirmed_condition_ids == []
    assert outcome(score) == only(missed=["D-1"])


def test_a_within_scope_finding_agreeing_with_a_condition_confirms_it(tmp_path: Path) -> None:
    findings = [finding_with("checked_within_scope", check="rms.folders.present")]

    score = score_one(
        tmp_path, findings, known_defects=[FOLDERS_DEFECT], correct_conditions=[FOLDERS_CONDITION]
    )

    assert score.confirmed_condition_ids == ["C-1"]
    assert score.contradicted_condition_ids == []
    assert score.false_alarm_finding_ids == []


def test_an_unresolved_finding_on_a_condition_counts_in_neither(tmp_path: Path) -> None:
    findings = [finding_with("unresolved", check="rms.folders.present")]

    score = score_one(
        tmp_path, findings, known_defects=[FOLDERS_DEFECT], correct_conditions=[FOLDERS_CONDITION]
    )

    assert score.contradicted_condition_ids == []
    assert score.confirmed_condition_ids == []
    assert score.false_alarm_finding_ids == []
    assert score.unresolved_count == 1


FOUR_SCREWS = [{"fastener": f"fst:000{n}", "hole": f"hol:000{n}"} for n in range(1, 5)]
"""Four screws of the cover in four tapped holes of the housing, each a joint element."""


def four_screw_package() -> EvidencePackage:
    """`build_package` with the four joints of `FOUR_SCREWS` in place of its one."""
    return build_package(
        holes=[
            tapped_hole().model_copy(
                update={"id": joint["hole"], "persist_ref": persist_ref(joint["hole"])}
            )
            for joint in FOUR_SCREWS
        ],
        fasteners=[
            screw().model_copy(
                update={"id": joint["fastener"], "persist_ref": persist_ref(joint["fastener"])}
            )
            for joint in FOUR_SCREWS
        ],
        gaps=[],
    )


def test_a_thread_match_finding_on_one_of_four_keyed_screws_is_a_false_alarm(
    tmp_path: Path,
) -> None:
    """US1-1: `fastener.bottoming` keyed on four screws; `fastener.thread_match` demonstrated on
    one names that screw's joint exactly and is still another rule: the defect is missed and the
    finding is scored on its own merits, one false alarm."""
    defect = {"check": "fastener.bottoming", "component_ids": BOTH_PARTS, "references": FOUR_SCREWS}
    finding = make_finding(
        check="fastener.thread_match",
        status="demonstrated",
        inputs=["fst:0001", "hol:0001"],
        tool_result_ids=[0],
    )

    score = score_one(tmp_path, [finding], known_defects=[defect], package=four_screw_package())

    assert outcome(score) == only(missed=["D-1"])
    assert score.false_alarm_finding_ids == ["F-001"]


def test_the_real_drawing_finding_on_a_drawing_document_scores_by_the_table(
    tmp_path: Path,
) -> None:
    """US1-6: `record_drawing_finding` (`tools/session.py:456-531`) on the drawing `doc:3`, keyed
    as a defect on that document: credited, with no false alarm."""
    context = context_for(DRAWINGS)
    with use_context(context):
        recorded = record()
    assert recorded["status"] == "recorded"
    findings = context.require_session().findings
    defect = {"check": "drawing.manufacturing_inputs", "document_ids": [INGESTED]}

    score = score_one(tmp_path, findings, known_defects=[defect], package=DRAWINGS)

    assert outcome(score) == only(matched=["D-1"])
    assert score.false_alarm_finding_ids == []


def test_one_joint_s_unresolved_bottoming_flags_its_own_defect_and_no_other(
    tmp_path: Path,
) -> None:
    """US1-17's scored half: four screws in one plate, each joint's `fastener.bottoming` keyed as
    its own defect expected unresolved; a session holding only the third joint's unresolved
    finding, built through the real `check_fastener_joint` (T025), flags that defect only."""
    joint = FOUR_SCREWS[2]
    fastener = screw().model_copy(update={"id": joint["fastener"]})
    hole = tapped_hole(thread_depth=None).model_copy(update={"id": joint["hole"]})
    [bottoming] = [
        result
        for result in check_fastener_joint(
            fastener, hole, [layer(mm(3.0))], hole_material="6061-T6"
        )
        if result.check == CHECK_BOTTOMING
    ]
    finding = result_to_finding(context_for(build_package()), bottoming, component_ids=BOTH_PARTS)
    assert finding.status == "unresolved"
    defects = [
        {
            "check": CHECK_BOTTOMING,
            "component_ids": BOTH_PARTS,
            "references": [each],
            "expected_status": "unresolved",
        }
        for each in FOUR_SCREWS
    ]

    score = score_one(tmp_path, [finding], known_defects=defects, package=four_screw_package())

    assert outcome(score) == only(matched=["D-3"], flagged=["D-3"], missed=["D-1", "D-2", "D-4"])
    assert score.false_alarm_finding_ids == []


# --- 8. an empty key, and a key with only conditions (SC-001) --------------------------------


def test_with_an_empty_key_every_demonstrated_or_suspected_finding_is_a_false_alarm(
    tmp_path: Path,
) -> None:
    findings = [
        finding_with("demonstrated", "F-001"),
        finding_with("suspected", "F-002"),
        finding_with("unresolved", "F-003"),
        finding_with("checked_within_scope", "F-004"),
    ]

    scorecard = score_packages(tmp_path, write_package(tmp_path, "pkg-a", findings))

    assert scorecard.per_package[0].false_alarm_finding_ids == ["F-001", "F-002"]
    assert scorecard.aggregate.recall is None


def test_a_key_with_only_conditions_reads_recall_null_and_its_null_review_no_false_alarm(
    tmp_path: Path,
) -> None:
    """Moved by design from `be01974`'s `:260`, recall `None` for a held-out package with no
    known defect: its key holds one held-out condition, which the set's flag now requires."""
    condition = {**FOLDERS_CONDITION, "tag": "held_out"}

    scorecard = score_packages(
        tmp_path,
        write_package(tmp_path, "pkg-b", [], correct_conditions=[condition], held_out=True),
    )

    assert scorecard.aggregate.recall is None
    assert scorecard.aggregate.false_alarm_rate is None
    assert scorecard.per_package[0].false_alarm_finding_ids == []
    assert scorecard.per_package[0].contradicted_condition_ids == []


# --- 9. recall per producer and tag, from the item tags (US1-10, FR-006, FR-032, US5-6) -----


def recall_run(tmp_path: Path, *, tuned_on_detected: bool) -> Scorecard:
    """Two packages. `pkg-a`, held out: D-1 (model, held out) detected, D-2 (model, held out)
    missed, D-3 (code, held out) detected, and D-4 (model, tuned on) detected or not. `pkg-b`,
    not held out: D-1 (code, tuned on) missed."""
    held = {"tag": "held_out"}
    found = [
        finding_with("demonstrated", "F-001"),
        finding_with("demonstrated", "F-002", check="rms.folders.present"),
    ]
    if tuned_on_detected:
        found.append(finding_with("demonstrated", "F-003", check="mass.material_assigned"))
    first = write_package(
        tmp_path,
        "pkg-a",
        found,
        known_defects=[
            {"check": "hygiene.revision_present", "component_ids": ["cmp:0001"], **held},
            {"check": "hygiene.revision_present", "component_ids": ["cmp:0002"], **held},
            {
                "check": "rms.folders.present",
                "component_ids": ["cmp:0001"],
                "producer": "code",
                **held,
            },
            {"check": "mass.material_assigned", "component_ids": ["cmp:0001"]},
        ],
        held_out=True,
    )
    second = write_package(
        tmp_path,
        "pkg-b",
        [],
        known_defects=[
            {
                "check": "hygiene.revision_present",
                "component_ids": ["cmp:0001"],
                "producer": "code",
            },
        ],
    )
    return score_packages(tmp_path, first, second)


def test_recall_is_read_from_the_item_tags_by_producer_and_tag(tmp_path: Path) -> None:
    """Held out of both producers: 2 of 3, `pkg-a`'s tuned-on D-4 left out though its package is
    flagged held out; each group of producer and tag on its own; the held-out count names the
    held-out model-produced defects of every package's key."""
    aggregate = recall_run(tmp_path, tuned_on_detected=True).aggregate

    assert aggregate.recall == pytest.approx(2 / 3)
    by_producer = aggregate.recall_by_producer
    assert by_producer.model.held_out == pytest.approx(1 / 2)
    assert by_producer.model.tuned_on == pytest.approx(1.0)
    assert by_producer.code.held_out == pytest.approx(1.0)
    assert by_producer.code.tuned_on == pytest.approx(0.0)
    assert aggregate.held_out_model_defects == 2
    assert aggregate.detected == 3


def test_a_detected_tuned_on_defect_moves_its_own_group_and_never_held_out_recall(
    tmp_path: Path,
) -> None:
    """US5-6: a tuned-on item is graded as a regression guard, never in held-out recall."""
    found = recall_run(tmp_path / "found", tuned_on_detected=True).aggregate
    missed = recall_run(tmp_path / "missed", tuned_on_detected=False).aggregate

    assert found.recall_by_producer.model.tuned_on == pytest.approx(1.0)
    assert missed.recall_by_producer.model.tuned_on == pytest.approx(0.0)
    assert found.recall == missed.recall
    assert found.recall_by_producer.model.held_out == missed.recall_by_producer.model.held_out


def test_a_group_with_no_defect_reads_recall_null(tmp_path: Path) -> None:
    defect = {"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}

    aggregate = score_packages(
        tmp_path, write_package(tmp_path, "pkg-a", [], known_defects=[defect])
    ).aggregate

    assert aggregate.recall_by_producer.model.tuned_on == pytest.approx(0.0)
    assert aggregate.recall_by_producer.model.held_out is None
    assert aggregate.recall_by_producer.code.held_out is None
    assert aggregate.recall_by_producer.code.tuned_on is None
    assert aggregate.recall is None
    assert aggregate.held_out_model_defects == 0


# --- 10 and 11: the set's flag against its key, and key-only keys (US5-12, D7) ---------------


@pytest.mark.parametrize(
    ("held_out", "tag", "line"),
    [
        (
            True,
            "tuned_on",
            "pkg-a: the set marks it held_out=true, but its key holds 0 held-out items; the "
            "flag is derived from the key",
        ),
        (
            False,
            "held_out",
            "pkg-a: the set marks it held_out=false, but its key holds 2 held-out items; the "
            "flag is derived from the key",
        ),
    ],
)
def test_a_set_flag_that_disagrees_with_its_key_is_refused_naming_the_package(
    tmp_path: Path, held_out: bool, tag: str, line: str
) -> None:
    ref = write_package(
        tmp_path,
        "pkg-a",
        [],
        known_defects=[
            {"check": "hygiene.revision_present", "component_ids": ["cmp:0001"], "tag": tag}
        ],
        correct_conditions=[{**FOLDERS_CONDITION, "tag": tag}],
        held_out=held_out,
    )

    with pytest.raises(ValueError) as caught:
        score_packages(tmp_path, ref)

    assert str(caught.value) == line


def test_held_out_flag_error_is_the_line_and_none_when_the_flag_agrees() -> None:
    key = AnswerKey.model_validate(
        {
            "key_format": 2,
            "package_id": "pkg-a",
            "known_defects": [],
            "correct_conditions": [
                {
                    **FOLDERS_CONDITION,
                    "id": "C-1",
                    "document_ids": [],
                    "tag": "held_out",
                    "held_out_against": {
                        "prompt": "a" * 64,
                        "checklist": "b" * 64,
                        "tools": "c" * 64,
                    },
                    "description": "The fictional plate's feature tree is foldered.",
                }
            ],
        }
    )

    assert scorecard_module.held_out_flag_error("pkg-a", True, key) is None
    assert scorecard_module.held_out_flag_error("pkg-a", False, key) == (
        "pkg-a: the set marks it held_out=false, but its key holds 1 held-out items; the flag is "
        "derived from the key"
    )


def test_a_set_naming_a_key_only_key_is_refused(tmp_path: Path) -> None:
    write_key(tmp_path / "answer_keys", "pkg-a", known_defects=[FOLDERS_DEFECT], key_only=True)
    unbuilt = tmp_path / "packages" / "pkg-a"
    unbuilt.mkdir(parents=True)
    ref = BenchmarkPackageRef(package_id="pkg-a", path=unbuilt, held_out=False)

    with pytest.raises(ValueError) as caught:
        score_packages(tmp_path, ref)

    assert str(caught.value) == (
        "pkg-a: its key is key-only (package not built); it cannot be scored"
    )


# --- 12. not assessed, never 0 (US3-8, FR-021) -----------------------------------------------

NO_CONDITION = "the key holds no correct condition"


def test_a_key_with_no_condition_reads_both_condition_columns_null_with_their_reasons(
    tmp_path: Path,
) -> None:
    defect = {"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}

    scorecard = score_packages(
        tmp_path, write_package(tmp_path, "pkg-a", [], known_defects=[defect])
    )

    score = scorecard.per_package[0]
    assert score.contradicted_condition_ids is None
    assert score.confirmed_condition_ids is None
    assert score.not_assessed == {
        "contradicted_condition_ids": NO_CONDITION,
        "confirmed_condition_ids": NO_CONDITION,
    }
    assert scorecard.aggregate.contradictions is None
    assert scorecard.aggregate.confirmations is None
    rendered = render_scorecard_md(scorecard)
    assert row_cells(rendered, "pkg-a")[header_cells(rendered).index("contradictions")] == (
        "not assessed"
    )
    assert "- contradictions: not assessed" in rendered
    assert "- confirmations: not assessed" in rendered


def test_a_key_with_conditions_assesses_both_columns(tmp_path: Path) -> None:
    score = score_one(tmp_path, [], correct_conditions=[FOLDERS_CONDITION])

    assert score.not_assessed == {}
    assert score.contradicted_condition_ids == []


def test_an_aggregate_column_some_packages_assess_sums_over_those_and_says_how_many(
    tmp_path: Path,
) -> None:
    contradicting = [finding_with("demonstrated", check="rms.folders.present")]
    assessed = write_package(
        tmp_path, "pkg-a", contradicting, correct_conditions=[FOLDERS_CONDITION]
    )
    unassessed = write_package(tmp_path, "pkg-b", [])

    scorecard = score_packages(tmp_path, assessed, unassessed)

    assert scorecard.aggregate.contradictions == 1
    assert scorecard.aggregate.confirmations == 0
    rendered = render_scorecard_md(scorecard)
    assert "- contradictions: 1 (1 of 2 packages)" in rendered
    assert "- confirmations: 0 (1 of 2 packages)" in rendered


def header_cells(rendered: str) -> list[str]:
    header = next(line for line in rendered.splitlines() if line.startswith("| package "))
    return [cell.strip() for cell in header.strip("|").split("|")]


def row_cells(rendered: str, package_id: str) -> list[str]:
    row = next(line for line in rendered.splitlines() if line.startswith(f"| {package_id} "))
    return [cell.strip() for cell in row.strip("|").split("|")]


# --- 14. the amended contract ----------------------------------------------------------------


def contract_errors(scorecard: Scorecard) -> list[str]:
    validator = Draft202012Validator(
        load_contract("scorecard.schema.json"), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    payload = scorecard.model_dump(mode="json")
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    return [f"{list(error.absolute_path)}: {error.message}" for error in errors]


def test_scorecard_validates_against_the_contract(tmp_path: Path) -> None:
    """Kept from `be01974` (`:359`), folded into test 14 against the amended schema."""
    scorecard = scored(*build_scoring_fixture(tmp_path))

    assert contract_errors(scorecard) == []


def test_a_scorecard_with_null_condition_columns_validates_against_the_contract(
    tmp_path: Path,
) -> None:
    scorecard = score_packages(tmp_path, write_package(tmp_path, "pkg-a", []))

    assert contract_errors(scorecard) == []


def test_the_contract_requires_every_new_field() -> None:
    contract = load_contract("scorecard.schema.json")

    assert {"scoring_rules_version", "key_sha256"} <= set(contract["required"])
    for model in (PackageScore, Aggregate):
        definition = contract["$defs"][model.__name__]
        assert set(definition["required"]) == set(definition["properties"]), model.__name__
        assert set(definition["properties"]) == set(model.model_fields), model.__name__


# --- 15. key_sha256, finding_origins and graded_items ----------------------------------------


def test_key_sha256_names_each_key_file_s_raw_bytes_digest(tmp_path: Path) -> None:
    run_dir, keys, benchmark_set = build_scoring_fixture(tmp_path)

    scorecard = scored(run_dir, keys, benchmark_set)

    raw = (keys / "pkg-a.json").read_bytes()
    assert scorecard.key_sha256 == {"pkg-a": hashlib.sha256(raw).hexdigest()}


def test_finding_origins_names_every_final_state_finding(tmp_path: Path) -> None:
    """A session written as data carries no origin-marks record: its code findings read
    `unknown` (`scoring.md` 5.3 rule 3); the scorer never refuses on origin."""
    run_dir, keys, benchmark_set = build_scoring_fixture(tmp_path)

    score = scored(run_dir, keys, benchmark_set).per_package[0]

    assert score.finding_origins == {f"F-00{n}": "unknown" for n in range(1, 7)}


def test_graded_items_copy_every_entry_s_id_kind_tag_producer_and_status(tmp_path: Path) -> None:
    run_dir, keys, benchmark_set = build_scoring_fixture(tmp_path, held_out=False)

    score = scored(run_dir, keys, benchmark_set).per_package[0]

    assert [item.model_dump() for item in score.graded_items] == [
        {
            "id": "D-1",
            "kind": "known_defect",
            "tag": "tuned_on",
            "producer": "model",
            "expected_status": "suspected",
        },
        {
            "id": "D-2",
            "kind": "known_defect",
            "tag": "tuned_on",
            "producer": "model",
            "expected_status": "suspected",
        },
        {
            "id": "D-3",
            "kind": "known_defect",
            "tag": "tuned_on",
            "producer": "model",
            "expected_status": "suspected",
        },
        {
            "id": "C-1",
            "kind": "correct_condition",
            "tag": "tuned_on",
            "producer": None,
            "expected_status": None,
        },
    ]


def test_the_aggregate_counts_findings_and_false_alarms_by_origin(tmp_path: Path) -> None:
    model_written = make_finding(
        finding_id="F-002",
        check="drawing.manufacturing_inputs",
        status="suspected",
        source="model",
        numeric=False,
    )
    findings = [finding_with("demonstrated", "F-001"), model_written]

    aggregate = score_packages(tmp_path, write_package(tmp_path, "pkg-a", findings)).aggregate

    assert aggregate.findings_by_origin["unknown"] == 1
    assert aggregate.findings_by_origin["model"] == 1
    assert sum(aggregate.findings_by_origin.values()) == 2
    assert aggregate.false_alarms_by_origin["model"] == 1
    assert sum(aggregate.false_alarms_by_origin.values()) == 2


# --- distribution, median, and packages without timing ---------------------------------------


def test_distribution_matches_per_package_order(tmp_path: Path) -> None:
    """Kept from `be01974` (`:314`), what it asserts unchanged."""
    refs: list[BenchmarkPackageRef] = []
    expected_net_saved: list[float | None] = []
    for name, baseline in (("pkg-x", 100.0), ("pkg-y", None), ("pkg-z", 40.0)):
        timing = Timing(
            baseline_minutes=baseline,
            assisted_supervision_minutes=5.0,
            assisted_verification_minutes=5.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=1.0,
        )
        refs.append(write_package(tmp_path, name, [], timing=timing))
        expected_net_saved.append(None if baseline is None else baseline - 10.0)

    scorecard = score_packages(tmp_path, *refs)

    assert [p.package_id for p in scorecard.per_package] == ["pkg-x", "pkg-y", "pkg-z"]
    assert len(scorecard.distribution) == len(expected_net_saved)
    for actual, expected in zip(scorecard.distribution, expected_net_saved, strict=True):
        if expected is None:
            assert actual is None
        else:
            assert actual == pytest.approx(expected)
    assert scorecard.aggregate.packages_with_timing == 2
    assert scorecard.aggregate.median_net_saved_minutes == pytest.approx(60.0)  # median(90, 30)


# --- the rendered page -----------------------------------------------------------------------


def test_render_scorecard_md_lists_each_package_and_the_aggregate(tmp_path: Path) -> None:
    """Kept from `be01974` (`:373`), what it asserts unchanged."""
    scorecard = scored(*build_scoring_fixture(tmp_path))

    rendered = render_scorecard_md(scorecard)

    assert "pkg-a" in rendered
    assert "## Aggregate" in rendered
    assert "recall" in rendered.lower()
    assert "false-alarm rate" in rendered.lower() or "false alarm" in rendered.lower()


def test_the_page_adds_the_outcome_columns_per_package(tmp_path: Path) -> None:
    scorecard = scored(*build_scoring_fixture(tmp_path))

    rendered = render_scorecard_md(scorecard)

    cells = dict(zip(header_cells(rendered), row_cells(rendered, "pkg-a"), strict=True))
    assert cells["detected"] == "2"
    assert cells["flagged"] == "0"
    assert cells["below expected"] == "0"
    assert cells["cleared"] == "0"
    assert cells["false alarms"] == "2"
    assert cells["of model origin"] == "0"
    assert cells["contradictions"] == "1"


def test_the_page_adds_recall_by_producer_false_alarms_by_origin_and_the_held_out_count(
    tmp_path: Path,
) -> None:
    rendered = render_scorecard_md(recall_run(tmp_path, tuned_on_detected=True))

    assert (
        "- recall by producer and tag: model held out 50%, model tuned on 100%, "
        "code held out 100%, code tuned on 0%"
    ) in rendered
    assert "- false alarms by origin: none" in rendered
    assert "- held-out model-produced defects: 2" in rendered


def test_the_scoring_rules_version_is_written_on_the_scorecard(tmp_path: Path) -> None:
    scorecard = scored(*build_scoring_fixture(tmp_path))

    assert scorecard.scoring_rules_version == scorecard_module.SCORING_RULES_VERSION
    assert json.loads(scorecard.model_dump_json())["scoring_rules_version"] == 2
