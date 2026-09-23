"""T082: `record_partial_evidence` over **any** reduced dump profile (FR-037).

Feature 003 wrote the rule for one profile name: a package whose `extractor.profile` was
`"model_check"` got a `skipped` coverage item naming the four phases that profile switches
off, and every other package got nothing. Feature 006 adds a second reduced profile, so a
rule written per profile name would need a third copy the next time one arrives - and, worse,
a `standards` package would meanwhile be handed to a review as **full** evidence and read as a
design with no holes and no fasteners, which is the one reading of a partial extract that is
worse than no reading at all.

Three things are asserted here, and they are the three halves of FR-037's Python site:

1. **The guard widens.** Any profile that is not `full` records the item; `full` records
   nothing, which is what keeps every feature 001 and 002 golden byte-identical.
2. **The phases come from the package's own phase rows.** A standards dump of a drawing ran
   the drawing phase and a standards dump of a part did not, and the sentence says which -
   read off `extractor.phases`, not off a second literal list of profile names.
3. **The model-check sentence is byte-identical.** `test_chat_server.py`,
   `test_chat_checks_routes.py`, `test_rms_run.py` and `test_prerun_digest.py` all read that
   sentence and none of them is edited by this feature, so it is pinned here in full.

Written against `record_partial_evidence` directly rather than through a scripted review: the
function takes a session and a package and decides one thing, and a review around it would only
make the failure harder to read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from swreview.agent.runner import (
    FULL_PROFILE_ONLY_PHASES,
    GEOMETRY_PHASES,
    PROFILE_CHECK,
    REDUCED_PROFILE_SKIPPED,
    STANDARDS_EVIDENCE_PHASES,
    record_partial_evidence,
)
from swreview.ir.models import DumpPhase, EvidencePackage
from swreview.report.session import ReviewSession, Timing
from tests.support.packages import build_package
from tests.unit.test_ir_phases import PHASE_ORDER

SESSION_ID = UUID("00000000-0000-4000-8000-00000000f037")

MODEL_CHECK_SENTENCE = (
    "the evidence was written by the 'model_check' dump profile: the hole, fastener, face "
    "and body or mesh phases were never run, so holes, fasteners, faces and bodies are "
    "empty because nothing read them - not because this design has none. Extract full "
    "evidence and review again to cover anything that depends on them (FR-022)."
)
"""Feature 003's sentence, byte for byte. Four unedited test modules read it."""

STANDARDS_PART_SENTENCE = (
    "the evidence was written by the 'standards' dump profile: the drawing, hole, fastener, "
    "face and body or mesh phases were never run, so drawings, holes, fasteners, faces and "
    "bodies are empty because nothing read them - not because this design has none. Extract "
    "full evidence and review again to cover anything that depends on them (FR-022)."
)
"""What a standards dump of a part rendered before the `tolerance` phase existed, byte for
byte: feature 006's generalization of feature 003's template (FR-037)."""

STANDARDS_DRAWING_SENTENCE = (
    "the evidence was written by the 'standards' dump profile: the hole, fastener, face and "
    "body or mesh phases were never run, so holes, fasteners, faces and bodies are empty "
    "because nothing read them - not because this design has none. Extract full evidence and "
    "review again to cover anything that depends on them (FR-022)."
)
"""What a standards dump of a drawing rendered before the `tolerance` phase existed."""


def session() -> ReviewSession:
    package = build_package()
    return ReviewSession(
        session_id=SESSION_ID,
        package_id=package.package_id,
        design_id=package.design.design_id,
        started_at=datetime(2026, 9, 17, 10, 15, tzinfo=UTC),
        ended_at=datetime(2026, 9, 17, 10, 16, tzinfo=UTC),
        model="gpt-5.6",
        timing=Timing(
            baseline_minutes=None,
            assisted_supervision_minutes=0.0,
            assisted_verification_minutes=0.0,
            false_alarm_handling_minutes=0.0,
            unattended_runtime_minutes=0.0,
        ),
    )


def package(profile: str, phases: dict[str, str] | None = None) -> EvidencePackage:
    """A package written by `profile`, whose phase rows record `phases` (name -> status)."""
    rows = [
        DumpPhase(name=name, status=status, elapsed_ms=1 if status == "ok" else None)
        for name, status in (phases or {}).items()
    ]
    base = build_package()
    return base.model_copy(
        update={"extractor": base.extractor.model_copy(update={"profile": profile, "phases": rows})}
    )


def written(recorded: ReviewSession) -> list[str]:
    """The reasons of every partial-evidence item in the session, in every bucket."""
    coverage = recorded.coverage
    return [
        item.reason
        for bucket in (
            coverage.checked,
            coverage.skipped,
            coverage.unresolved,
            coverage.failed,
            coverage.out_of_scope,
        )
        for item in bucket
        if item.check == PROFILE_CHECK
    ]


# --- 1. the guard ---------------------------------------------------------------------------


def test_a_full_package_records_nothing() -> None:
    """The unchanged half: a full dump is not annotated as a partial one."""
    recorded = session()
    record_partial_evidence(recorded, package("full"))

    assert written(recorded) == []


@pytest.mark.parametrize("profile", ["model_check", "standards"])
def test_every_reduced_profile_records_exactly_one_skipped_item(profile: str) -> None:
    """One item, in `skipped`, whatever the reduced profile is called."""
    recorded = session()
    record_partial_evidence(recorded, package(profile))

    assert len(written(recorded)) == 1
    assert len(recorded.coverage.skipped) == 1
    assert recorded.coverage.skipped[0].check == PROFILE_CHECK
    assert recorded.coverage.skipped[0].error is None
    assert profile in recorded.coverage.skipped[0].reason


def test_the_guard_is_not_a_second_list_of_profile_names() -> None:
    """The sentence names no profile but the package's own, so a third reduced profile needs
    no edit here at all: `REDUCED_PROFILE_SKIPPED` is a template, and the only profile name in
    it is the one substituted in."""
    assert "model_check" not in REDUCED_PROFILE_SKIPPED
    assert "standards" not in REDUCED_PROFILE_SKIPPED
    assert "{profile!r}" in REDUCED_PROFILE_SKIPPED


# --- 2. the phases come from the package ------------------------------------------------------


def test_the_model_check_sentence_is_byte_identical() -> None:
    """Four unedited test modules read this sentence; it does not move."""
    recorded = session()
    record_partial_evidence(recorded, package("model_check"))

    assert written(recorded) == [MODEL_CHECK_SENTENCE]


def test_a_package_that_timed_no_phase_still_names_the_four_geometry_phases() -> None:
    """A package written before phase rows existed - or by a build that timed none - is still
    a reduced package, and the four phases every reduced profile switches off are the floor.
    Silence about what was skipped is the failure this whole item exists to prevent."""
    recorded = session()
    record_partial_evidence(recorded, package("standards"))

    reason = written(recorded)[0]
    for phase in ("hole", "fastener", "face", "body or mesh"):
        assert phase in reason, f"the coverage item does not name {phase}: {reason}"
    assert "'standards'" in reason


def test_the_skipped_phases_are_read_off_the_packages_own_rows() -> None:
    """A standards dump of a part ran the cut-list phase and skipped the drawing phase, so the
    sentence names drawings and does not name cut lists."""
    recorded = session()
    record_partial_evidence(
        recorded,
        package(
            "standards",
            {
                "document": "ok",
                "feature": "ok",
                "cutlist": "ok",
                "drawing": "skipped",
                "hole": "skipped",
                "fastener": "skipped",
                "face": "skipped",
                "body": "skipped",
            },
        ),
    )

    reason = written(recorded)[0]

    assert "drawing, hole, fastener, face and body or mesh phases" in reason
    assert "drawings, holes, fasteners, faces and bodies are empty" in reason
    assert "cut list" not in reason


def test_a_phase_row_that_ran_is_never_reported_as_skipped() -> None:
    """The drawing-rooted standards dump: the drawing phase ran, so nothing says it did not."""
    recorded = session()
    record_partial_evidence(
        recorded,
        package(
            "standards",
            {
                "drawing": "ok",
                "cutlist": "skipped",
                "hole": "skipped",
                "fastener": "skipped",
                "face": "skipped",
                "body": "skipped",
            },
        ),
    )

    reason = written(recorded)[0]

    assert "drawing" not in reason
    assert "cut list, hole, fastener, face and body or mesh phases" in reason


def test_a_failed_phase_is_not_a_skipped_one() -> None:
    """`failed` is evidence the dump lost and is reported as a gap; only `skipped` means the
    phase never ran (`DumpPhase.status`), and only that belongs in this sentence."""
    recorded = session()
    record_partial_evidence(
        recorded,
        package(
            "model_check",
            {
                "hole": "failed",
                "fastener": "skipped",
                "face": "skipped",
                "body": "skipped",
            },
        ),
    )

    reason = written(recorded)[0]

    assert "fastener, face and body or mesh phases" in reason
    assert "hole," not in reason


# --- 3. against a package shaped the way the extractor really writes one -----------------------


def extractor_rows(ran: set[str]) -> dict[str, str]:
    """The phase rows `PackageWriter` writes, with `ran` recorded `ok`.

    A real package records a row for **every** name in `PackageWriter.PhaseOrder`
    (`extractor/SwReview.Extractor/Dump/PackageWriter.cs` and `PhaseLog.Rows()`): a phase the
    dump never reached is `skipped` with no elapsed time rather than absent. Building the
    package any other way - with no rows at all, as `build_package()` does - exercises a shape
    no dump ever produces, which is how the sentence below can be pinned everywhere and still
    come out differently on the workstation.

    The names are `test_ir_phases.PHASE_ORDER`, the Python pin of that order (the C# pin is
    `PackageReuseTests`), so a phase the extractor adds - feature 010's `tolerance` - reaches
    these tests the day it reaches the dump instead of being missed by a copied list.
    """
    return {name: ("ok" if name in ran else "skipped") for name in PHASE_ORDER}


CORE_PHASES = {"document", "manifest", "mate", "feature", "equation"}
"""The five phases every profile runs."""


def test_a_real_model_check_package_renders_the_model_check_sentence() -> None:
    """The regression: the sentence is byte-identical against the rows the *extractor* writes.

    A `model_check` dump runs the five core phases and records the other six as skipped - the
    cut-list and drawing phases among them, because those run only for a dump asked for
    standards evidence (`PackageWriter.cs:257-289`). Reading every skipped row would name cut
    lists and drawings here and change feature 003's wording on every real package (FR-037).
    """
    recorded = session()
    record_partial_evidence(recorded, package("model_check", extractor_rows(CORE_PHASES)))

    assert written(recorded) == [MODEL_CHECK_SENTENCE]


def test_a_real_standards_package_of_a_part_names_the_drawing_it_did_not_get() -> None:
    """A standards dump of a part ran the cut-list phase, so the drawing phase it skipped is
    evidence this dump was asked for and did not get, and the sentence says so."""
    recorded = session()
    record_partial_evidence(
        recorded, package("standards", extractor_rows(CORE_PHASES | {"cutlist"}))
    )

    reason = written(recorded)[0]

    assert "drawing, hole, fastener, face and body or mesh phases" in reason
    assert "drawings, holes, fasteners, faces and bodies are empty" in reason
    assert "cut list" not in reason


def test_a_real_standards_package_of_a_drawing_names_only_the_geometry_phases() -> None:
    """The drawing-rooted standards dump ran both standards-evidence phases, so what it
    skipped is the geometry floor and nothing else."""
    recorded = session()
    record_partial_evidence(
        recorded, package("standards", extractor_rows(CORE_PHASES | {"cutlist", "drawing"}))
    )

    reason = written(recorded)[0]

    assert "the hole, fastener, face and body or mesh phases were never run" in reason
    assert "drawing" not in reason
    assert "cut list" not in reason


# --- 4. the tolerance phase (feature 010) keeps FR-037's wording --------------------------------


def test_the_rows_are_the_twelve_the_extractor_writes_with_tolerance_skipped() -> None:
    """Every reduced profile skips `tolerance` with the geometry phases (`PackageWriter`, schema
    1.5.0), so the rows these tests hand the sentence carry it skipped, as a real package does."""
    for rows in (
        extractor_rows(CORE_PHASES),
        extractor_rows(CORE_PHASES | {"cutlist"}),
        extractor_rows(CORE_PHASES | {"cutlist", "drawing"}),
    ):
        assert list(rows) == PHASE_ORDER
        assert rows["tolerance"] == "skipped"


def test_a_real_model_check_package_is_byte_identical_with_tolerance_skipped() -> None:
    recorded = session()
    record_partial_evidence(recorded, package("model_check", extractor_rows(CORE_PHASES)))

    assert written(recorded) == [MODEL_CHECK_SENTENCE]


def test_a_real_standards_package_of_a_part_is_byte_identical_with_tolerance_skipped() -> None:
    recorded = session()
    record_partial_evidence(
        recorded, package("standards", extractor_rows(CORE_PHASES | {"cutlist"}))
    )

    assert written(recorded) == [STANDARDS_PART_SENTENCE]


def test_a_real_standards_package_of_a_drawing_is_byte_identical_with_tolerance_skipped() -> None:
    recorded = session()
    record_partial_evidence(
        recorded, package("standards", extractor_rows(CORE_PHASES | {"cutlist", "drawing"}))
    )

    assert written(recorded) == [STANDARDS_DRAWING_SENTENCE]


def test_a_full_package_that_ran_tolerance_is_not_a_reduced_one() -> None:
    """A full dump ran `tolerance` with the geometry phases; the profile is `full`, so there is
    no partial-evidence sentence to write, whatever its drawing row says."""
    for ran in (set(PHASE_ORDER), set(PHASE_ORDER) - {"drawing"}):
        rows = extractor_rows(ran)
        assert rows["tolerance"] == "ok"

        recorded = session()
        record_partial_evidence(recorded, package("full", rows))

        assert written(recorded) == []


def test_the_full_profile_only_phases_are_a_named_list_of_their_own() -> None:
    """One named tuple, dropped the way the standards-evidence phases are dropped: never one of
    the geometry floor, never a standards-evidence phase, and a phase the extractor writes."""
    assert FULL_PROFILE_ONLY_PHASES == ("tolerance",)
    assert set(FULL_PROFILE_ONLY_PHASES).isdisjoint(GEOMETRY_PHASES)
    assert set(FULL_PROFILE_ONLY_PHASES).isdisjoint(STANDARDS_EVIDENCE_PHASES)
    assert set(FULL_PROFILE_ONLY_PHASES) <= set(PHASE_ORDER)
