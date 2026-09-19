"""The session builder every attention fixture is written by (T001).

Feature 007 ranks findings that already exist, so its fixtures are *sessions*, not
packages: eight findings shaped like the 2026-09-18 review of a four-component dowel-pin
assembly, and three shaped like the model check that followed it. Both were read off the
pilot workstation's handover folders, which are **not** in this repository; what is
mirrored here is their shape - the check ids, the statuses and severities, how many
components each finding names, the disposition and exception state, the five bucket counts
and which check ids the unresolved rows carry. Every string is this builder's own.

Three things this module pins, because each of them is a way a fixture rots:

1. **The contract.** A session the builder writes validates against
   `review-session.schema.json`, provenance and `tool_result_ids` included; a fixture that
   cannot be loaded by the product is not evidence of anything.
2. **Regeneration.** Re-running the builder reproduces every committed fixture byte for
   byte. A drifted fixture is therefore a red test and never a quiet rewrite by hand -
   which is what makes `uv run python -m tests.support.attention --write` safe to run.
3. **Research R2.4.** No fixture finding uses a rule id in a family's `high_severity` set.
   `_status_and_severity` promotes those to `high`, and a fixture built on one would let
   the severity key do the consequence key's work and prove nothing about the ranking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from swreview.agent.checklist import load_checklist
from swreview.checks.rms.registry import RMS_FAMILY, RULES
from swreview.checks.rms.run import is_check_folder
from swreview.checks.standards.registry import STANDARDS_FAMILY
from swreview.findings import Disposition
from swreview.ir.models import SourceRef
from swreview.report.session import ReviewSession, load_session
from tests.support.attention import (
    ASSEMBLY_DOCUMENT,
    CHECK_FOLDER,
    CHECK_SESSION_FILE,
    FIXTURE_DIR,
    PART_COMPONENT,
    REVIEW_FOLDER,
    REVIEW_SESSION_FILE,
    CoverageRow,
    CoverageSpec,
    FindingSpec,
    attention_package,
    build_attention_session,
    check_session,
    review_session,
    write_fixtures,
)
from tests.support.contracts import contract_validator

CHECKLIST_ITEM_IDS: frozenset[str] = frozenset(item.id for item in load_checklist().items)
"""The nine ids a close-out row's `check` equals (`Checklist.bucket_of`, research R2.5)."""

CENSUS_CHECK = "rms.types.unknown"
"""The one coverage check the rms family writes that is not a rule id (`rms/grade.py`)."""

REVIEW_SHAPE: tuple[tuple[str, str, str, str, int], ...] = (
    ("F-001", "rms.folders.present", "suspected", "low", 1),
    ("F-002", "rms.grouping.all_features_in_a_group", "demonstrated", "medium", 1),
    ("F-003", "rms.sketches.fully_defined", "demonstrated", "medium", 1),
    ("F-004", "rms.assembly.mates_to_reference_geometry", "demonstrated", "medium", 1),
    ("F-005", "rms.params.global_variables_present", "demonstrated", "medium", 1),
    ("F-006", "rms.params.dimensions_driven_by_equations", "suspected", "low", 1),
    ("F-007", "interference.static", "demonstrated", "medium", 2),
    ("F-008", "interference.static", "demonstrated", "medium", 2),
)
"""`(id, check, status, severity, distinct component ids)` of the 2026-09-18 review."""

CHECK_SHAPE: tuple[tuple[str, str, str, str, int], ...] = (
    ("F-001", "rms.folders.present", "suspected", "low", 1),
    ("F-002", "rms.grouping.all_features_in_a_group", "demonstrated", "medium", 1),
    ("F-003", "rms.sketches.fully_defined", "demonstrated", "medium", 1),
)
"""The same three rows the 2026-09-18 model check of the part produced."""

REVIEW_COVERAGE: tuple[int, int, int, int, int] = (5, 11, 39, 0, 7)
CHECK_COVERAGE: tuple[int, int, int, int, int] = (5, 11, 5, 0, 6)
"""checked, skipped, unresolved, failed, out of scope - the two runs' bucket counts."""


def shape_of(session: ReviewSession) -> tuple[tuple[str, str, str, str, int], ...]:
    return tuple(
        (
            finding.id,
            finding.check,
            finding.status,
            finding.severity,
            len(set(finding.component_ids)),
        )
        for finding in session.findings
    )


def bucket_counts(session: ReviewSession) -> tuple[int, int, int, int, int]:
    coverage = session.coverage
    return (
        len(coverage.checked),
        len(coverage.skipped),
        len(coverage.unresolved),
        len(coverage.failed),
        len(coverage.out_of_scope),
    )


# --- 1. the contract -------------------------------------------------------------------


@pytest.mark.parametrize("session", [review_session(), check_session()], ids=["review", "check"])
def test_a_built_session_validates_against_the_review_session_contract(
    session: ReviewSession,
) -> None:
    validator = contract_validator("review-session.schema.json")

    errors = sorted(validator.iter_errors(session.model_dump(mode="json")), key=str)

    assert errors == [], [f"{list(error.absolute_path)}: {error.message}" for error in errors]


def test_a_finding_spec_carries_every_field_the_policy_reads() -> None:
    """The nine keys read status, severity, components, disposition and carry-over."""
    carried_from = UUID("11111111-1111-4111-8111-111111111111")
    carried_at = datetime(2026, 9, 18, 21, 0, tzinfo=UTC)
    session = build_attention_session(
        session_id=UUID("22222222-2222-4222-8222-222222222222"),
        findings=[
            FindingSpec(
                check="fit.size_only",
                status="checked_within_scope",
                severity="info",
                component_ids=(PART_COMPONENT,),
                drawing_locations=(SourceRef(document_id=ASSEMBLY_DOCUMENT, sheet="Sheet1"),),
                tool_result_ids=(0,),
                disposition=Disposition(
                    decision="deferred",
                    note="waiting on the engineer",
                    by="engineer@example.com",
                    at=datetime(2026, 9, 18, 22, 0, tzinfo=UTC),
                ),
                exception_id="EXC-001",
                carried_over_from=carried_from,
                carried_over_at=carried_at,
                carry_over_key="fixture-key",
            )
        ],
        coverage=CoverageSpec(),
        steps=("check_fit",),
    )

    finding = session.findings[0]
    assert (finding.id, finding.check) == ("F-001", "fit.size_only")
    assert (finding.status, finding.severity) == ("checked_within_scope", "info")
    assert finding.component_ids == [PART_COMPONENT]
    assert [location.sheet for location in finding.drawing_locations] == ["Sheet1"]
    assert finding.disposition is not None and finding.disposition.decision == "deferred"
    assert finding.exception_id == "EXC-001"
    assert finding.carried_over_from == carried_from
    assert finding.carried_over_at == carried_at
    assert finding.carry_over_key == "fixture-key"


@pytest.mark.parametrize("session", [review_session(), check_session()], ids=["review", "check"])
def test_every_tool_result_id_names_a_step_the_session_holds(session: ReviewSession) -> None:
    indices = {step.index for step in session.steps}

    dangling = {
        finding.id: sorted(set(finding.tool_result_ids) - indices)
        for finding in session.findings
        if set(finding.tool_result_ids) - indices
    }

    assert dangling == {}


@pytest.mark.parametrize("session", [review_session(), check_session()], ids=["review", "check"])
def test_every_finding_cites_provenance_from_the_packages_manifest(
    session: ReviewSession,
) -> None:
    entries = {entry.document_id: entry for entry in attention_package().manifest.entries}

    for finding in session.findings:
        assert finding.provenance, f"{finding.id} carries no provenance"
        for entry in finding.provenance:
            assert entries.get(entry.document_id) == entry, (
                f"{finding.id} cites {entry.document_id}, which is not this package's entry"
            )


# --- 2. the builder's two dials ---------------------------------------------------------


def test_coverage_is_settable_by_count_per_bucket() -> None:
    session = build_attention_session(
        session_id=UUID("33333333-3333-4333-8333-333333333333"),
        findings=[],
        coverage=CoverageSpec(checked=2, skipped=3, unresolved=4, failed=1, out_of_scope=5),
    )

    assert bucket_counts(session) == (2, 3, 4, 1, 5)


def test_coverage_is_settable_by_check_id_with_a_reason() -> None:
    session = build_attention_session(
        session_id=UUID("44444444-4444-4444-8444-444444444444"),
        findings=[],
        coverage=CoverageSpec(
            unresolved=[
                CoverageRow(check="fasteners", reason="no fastener instance was extracted."),
                CoverageRow(check="coverage.evidence_request", reason="ER-001 is still open."),
            ]
        ),
    )

    rows = [(item.check, item.reason) for item in session.coverage.unresolved]
    assert rows == [
        ("fasteners", "no fastener instance was extracted."),
        ("coverage.evidence_request", "ER-001 is still open."),
    ]


# --- 3. the two 2026-09-18 shapes --------------------------------------------------------


def test_the_review_fixture_is_shaped_like_the_2026_09_18_review() -> None:
    session = load_session(REVIEW_SESSION_FILE)

    assert shape_of(session) == REVIEW_SHAPE
    assert bucket_counts(session) == REVIEW_COVERAGE
    assert [finding.disposition for finding in session.findings] == [None] * 8
    assert [finding.exception_id for finding in session.findings] == [None] * 8
    assert [finding.carried_over_from for finding in session.findings] == [None] * 8


def test_the_review_fixtures_unresolved_rows_are_the_close_out_the_run_wrote() -> None:
    """Seven checklist rows then `coverage.closeout`, three evidence requests, 28 rules.

    The order matters: the coverage block prints the first five close-out rows, so the five
    an engineer can act on most directly are the five the session holds first.
    """
    unresolved = load_session(REVIEW_SESSION_FILE).coverage.unresolved

    close_out = [item for item in unresolved if item.check in CHECKLIST_ITEM_IDS]
    evidence = [item for item in unresolved if item.check == "coverage.evidence_request"]
    rules = [
        item
        for item in unresolved
        if item.check not in CHECKLIST_ITEM_IDS and item.check != "coverage.evidence_request"
    ]

    assert [item.check for item in close_out] == [
        "fasteners",
        "holes.alignment",
        "interfaces.fit",
        "interfaces.stack",
        "drawing.manufacturing_inputs",
        "provenance",
        "modeling.resilience",
        "coverage.closeout",
    ]
    assert all(item.reason.endswith(".") for item in close_out), (
        "a close-out row's reason is the sentence the report prints verbatim"
    )
    assert len(evidence) == 3
    assert len(rules) == 28


def test_the_check_fixture_is_shaped_like_the_2026_09_18_model_check() -> None:
    session = load_session(CHECK_SESSION_FILE)

    assert shape_of(session) == CHECK_SHAPE
    assert bucket_counts(session) == CHECK_COVERAGE

    close_out = [item for item in session.coverage.unresolved if item.check in CHECKLIST_ITEM_IDS]
    assert close_out == [], "a check closes one checklist item and writes no close-out rows"


def test_the_check_folder_reads_back_as_an_rms_check_folder() -> None:
    """`check.json` names the session beside it, which is what makes the folder a check."""
    assert is_check_folder(CHECK_FOLDER)
    assert not is_check_folder(REVIEW_FOLDER)


def test_every_coverage_check_id_is_one_the_product_could_write() -> None:
    allowed = set(RULES) | set(CHECKLIST_ITEM_IDS) | {CENSUS_CHECK, "coverage.evidence_request"}
    for path in (REVIEW_SESSION_FILE, CHECK_SESSION_FILE):
        coverage = load_session(path).coverage
        checks = {
            item.check
            for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
            for item in getattr(coverage, bucket)
        }

        assert checks <= allowed, f"{path.name} invents coverage checks: {sorted(checks - allowed)}"


# --- 4. research R2.4: the severity key must not do the consequence key's work -----------


def test_no_fixture_finding_uses_a_high_severity_rule_id() -> None:
    high = RMS_FAMILY.high_severity | STANDARDS_FAMILY.high_severity
    assert high, "the families report no high-severity ids; this assertion would pass vacuously"

    used = {
        finding.check
        for session in (review_session(), check_session())
        for finding in session.findings
    }

    assert used & high == set()


# --- 5. regeneration: a drifted fixture is a failure, not a rewrite ----------------------


def test_the_committed_fixtures_regenerate_byte_for_byte(tmp_path: Path) -> None:
    written = write_fixtures(tmp_path)
    assert written, "write_fixtures wrote nothing"

    differing = [
        path.relative_to(tmp_path).as_posix()
        for path in written
        if (FIXTURE_DIR / path.relative_to(tmp_path)).read_bytes() != path.read_bytes()
    ]

    assert differing == [], (
        f"{differing} no longer match the builder; regenerate them deliberately with "
        "`uv run python -m tests.support.attention --write` and commit the diff"
    )


def test_the_builder_writes_exactly_the_committed_fixture_tree(tmp_path: Path) -> None:
    """An orphan left behind by an earlier shape is as wrong as a drifted byte."""
    written = {path.relative_to(tmp_path).as_posix() for path in write_fixtures(tmp_path)}

    committed = {
        path.relative_to(FIXTURE_DIR).as_posix()
        for path in FIXTURE_DIR.rglob("*")
        if path.is_file()
    }

    assert committed == written
