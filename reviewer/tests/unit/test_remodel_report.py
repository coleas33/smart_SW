"""`report.md`, the product of a re-model run (T092).

The nine sections and their order are `contracts/run-artifacts.md`'s table, and the order
is asserted **as an order and not as a set**, because section 9 is the sentence that keeps
a clean rebuild from reading as an approval and a long report is exactly where it would
get dropped.

What the report has to carry, and what each claim is protecting against:

- **the change list with an outcome per change**, and the copy path stated from
  `remodel.log`'s per-request target and from each `ChangeRecord.target_path` rather than
  from intent (FR-041). A run that cannot show both is not allowed to claim it;
- **the grade before and after**, counts per bucket with the unresolved rule ids named
  beside them, then the per-rule delta;
- **the geometry verdict and what the gate cannot detect**, on every run including a
  passing one;
- **the rebuild list**, one named reason and one blocking edge per entry;
- **a headline that never reads as success**: a run that moved 3 of 200 features says
  "this part needs rebuilding" in its first line; a truncated run says `truncated` there;
  a changed source attestation says so there ahead of everything else;
- **the three FR-056 sentences**, each asserted on its own because each is a distinct
  claim: the Resilient Modeling Strategy is credited as the source of the rules and the
  group vocabulary; every judgement item names the provider and the model **from the
  proposal's own fields** and never from a run-level default; and the copy is a proposal
  the engineer accepts or discards, **not an engineering acceptance result**;
- **every rejected proposal listed with its reason** (FR-016, US4 scenario 7), because a
  proposal the rules refused is the one thing a reader cannot see anywhere else;
- **the sentence that the added globals drive nothing yet** (FR-030).

The last test is a golden: the whole rendered report over one fixture, compared with
`pytest-regressions`, so a change to any sentence above is a change somebody has to look
at rather than a diff nobody sees.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from pytest_regressions.file_regression import FileRegressionFixture

from swreview.remodel.apply import TRUNCATING, StopReason
from swreview.remodel.apply_log import (
    CHANGES_FILE_NAME,
    RECORD_KINDS,
    ChangeRecord,
    changes_path,
    read_changes,
)
from swreview.remodel.artifacts import GradedRun, grade_remodel_run
from swreview.remodel.feasibility import Edge, Pin, RebuildEntry
from swreview.remodel.geometry import GeometryArtifact, GeometryReading, evaluate
from swreview.remodel.plan import (
    CHANGE_ORDER,
    DescriptionProposal,
    Deviation,
    GlobalEvidence,
    GlobalProposal,
    RejectedProposal,
    RemodelPlan,
    SourceAttestation,
    plan_reorganize,
)
from swreview.remodel.report import (
    ENGINEER_STOP,
    LOG_FILE_NAME,
    REPORT_FILE_NAME,
    SAVE,
    SECTIONS,
    read_log_targets,
    render_report,
    write_report,
)
from swreview.remodel.scope import Refusal, ScopeSignals
from swreview.remodel.tolerances import IDENTITY
from tests.support.features import FeatureSpec, feature, fillet_feature, folder
from tests.support.remodel import remodel_package, scope_signals

AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
COPY_PATH = "C:\\runs\\20260916-142201-bracket-remodel\\copy\\bracket-RMS.SLDPRT"
SOURCE_PATH = "C:\\work\\bracket.SLDPRT"
SOURCE_SHA = "4c" * 32
CALIBRATED = IDENTITY.model_copy(
    update={"calibrated": True, "calibration_ref": "PROBE-8 2026-09-16"}
)

HEADING = re.compile(r"^#{1,2} (.+)$", re.MULTILINE)


# --- the fixture run ---------------------------------------------------------------


def features() -> list[FeatureSpec]:
    return [
        feature("Boss-Extrude1", "Extrusion"),
        fillet_feature("Fillet5"),
        feature("Hole1", "HoleWzd", description=""),
    ]


def plan_of(specs: Sequence[FeatureSpec]) -> RemodelPlan:
    package = remodel_package(list(specs), document_id="doc:copy", name="bracket-RMS")
    return plan_reorganize(
        package,
        signals=ScopeSignals(**scope_signals()),
        probe_id="probe:1",
        now=AT,
    )


def attestation(**overrides: Any) -> SourceAttestation:
    return SourceAttestation(
        **{
            "path": SOURCE_PATH,
            "length_bytes": 482913,
            "last_write_utc": datetime(2026, 9, 14, 9, 11, 3, tzinfo=UTC),
            "sha256": SOURCE_SHA,
            "source_design_id": "dsn:4f2a91c0d3b7",
            "recorded_at": AT,
            "rechecked_at": datetime(2026, 9, 16, 14, 41, 55, tzinfo=UTC),
            "matches": True,
            "vault_path": None,
            "vault_revision": None,
            "copy_path": COPY_PATH,
            "copy_sha256_after_save": "77" * 32,
            **overrides,
        }
    )


def geometry(**overrides: Any) -> GeometryArtifact:
    baseline: dict[str, Any] = {
        "at": "2026-09-16T14:22:01Z",
        "source_sha256": SOURCE_SHA,
        "subject": "copy_at_open",
        "status": 0,
        "accuracy_level": 2,
        "recalculated": True,
        "volume_m3": 1.23456789e-3,
        "surface_area_m2": 4.56e-2,
        "center_of_mass_m": (0.01, 0.02, 0.03),
        "principal_moments": (1.1e-5, 2.2e-5, 3.3e-5),
        "mass_kg": 3.21,
        "density": 2600.0,
        "material_name": "1060 Alloy",
        "solid_body_count": 1,
        "sheet_body_count": 0,
        "face_count": 214,
        "edge_count": 642,
        "residual": None,
    }
    before = GeometryReading(**baseline)
    after = GeometryReading(
        **{**baseline, "subject": "copy_at_end", "at": "2026-09-16T14:41:55Z", **overrides}
    )
    return GeometryArtifact(
        before=before,
        after=after,
        gate=evaluate(before, after, CALIBRATED),
        tolerances=CALIBRATED,
    )


def change(
    seq: int, kind: str, name: str, status: str, **overrides: Any
) -> ChangeRecord:
    """One `changes.jsonl` line, as `contracts/run-artifacts.md` writes it.

    An `attempting` line carries nothing about the outcome, because it is written
    before the bridge call: `ChangeRecord` refuses one that does.
    """
    pending = status == "attempting"
    return ChangeRecord.model_validate(
        {
            "seq": seq,
            "at": "2026-09-16T14:22:31.481Z",
            "kind": kind,
            "subject": {
                "feature_id": f"feat:{seq:04d}",
                "name": name,
                "persist_ref": "<b64>",
            },
            "before": {},
            "after": {},
            "undo": None,
            "rebuild_errors_before": 0,
            "rebuild_errors_after": None if pending else 0,
            "status": status,
            "error_code": None,
            "error": None,
            "target_path": COPY_PATH,
            "elapsed_ms": None if pending else 310,
            **overrides,
        }
    )


def changes() -> list[ChangeRecord]:
    return [
        change(1, "rename", "Fillet1", "applied"),
        change(2, "describe", "Hole1", "applied"),
        change(
            3,
            "reorder",
            "Fillet5",
            "failed",
            error_code="not_addressable",
            error="could not be addressed after change 2",
        ),
    ]


def name_of(row: ChangeRecord) -> str:
    """The recorded subject name of a change that has one."""
    assert row.subject is not None
    return row.subject.name


def log_lines() -> list[str]:
    return [
        f"[2026-09-16T14:22:31.0000000+00:00] id=1 command=remodel.rename status=ok "
        f"elapsed_ms=310 gated=IFeature.set_Name target={COPY_PATH}",
        "[2026-09-16T14:22:32.0000000+00:00] id=2 command=remodel.rebuild status=ok "
        "elapsed_ms=90 gated=IModelDoc2.ForceRebuild3",
        f"[2026-09-16T14:22:33.0000000+00:00] id=3 command=remodel.describe status=ok "
        f"elapsed_ms=120 gated=IFeature.Description target={COPY_PATH}",
    ]


def judged(plan: RemodelPlan, **overrides: Any) -> RemodelPlan:
    """The plan as the judgement phase and the executor leave it."""
    hole = next(row for row in plan.targets if row.name == "Hole1")
    fillet = next(row for row in plan.targets if row.name == "Fillet5")
    return plan.model_copy(
        update={
            "plan_revision": 2,
            "state": "saved",
            "copy_path": COPY_PATH,
            "source": attestation(),
            "targets": tuple(
                row.model_copy(
                    update={
                        "decided_by": "model",
                        "rationale": "a slot, not a hole",
                        "provider": "gemini",
                        "model": "gemini-2.5-pro",
                    }
                )
                if row.feature_id == hole.feature_id
                else row
                for row in plan.targets
            ),
            "rebuild": (
                RebuildEntry(
                    feature_id="feat:0044",
                    name="Fillet7",
                    reason="backward_reference",
                    detail="parent feat:0061 is in 6-Quarantine",
                    blocking_edge=Edge(parent_id="feat:0061", child_id="feat:0044"),
                ),
            ),
            "pins": (
                Pin(
                    feature_id="feat:0031",
                    desired_index=4,
                    achievable_index=12,
                    blocking_edge=Edge(parent_id="feat:0012", child_id="feat:0031"),
                    reason="held below its parent feat:0012",
                ),
            ),
            "descriptions": (
                DescriptionProposal(
                    feature_id=hole.feature_id,
                    before="",
                    text="Mounting slot",
                    source="model",
                    rationale="the sketch is a slot profile",
                    provider="openai",
                    model="gpt-5-mini",
                    validation="accepted",
                ),
            ),
            "globals": (
                GlobalProposal(
                    name="shell_thickness",
                    expression="3",
                    rationale="three features share the wall",
                    evidence=(
                        GlobalEvidence(
                            feature_id=hole.feature_id,
                            parameter="shell_thickness",
                            value_m=0.003,
                            document_length_unit="mm",
                            value_document_units=3.0,
                            equation_text='"shell_thickness" = 3',
                        ),
                    ),
                    provider="gemini",
                    model="gemini-2.5-pro",
                    validation="accepted",
                    order_index=1,
                ),
            ),
            "rejected_proposals": (
                RejectedProposal(
                    at=AT,
                    tool="propose_global",
                    arguments={"name": "PlateWidth", "expression": "50"},
                    reason="global name must be lower_snake_case, 2 to 32 characters",
                    rule="global.name_pattern",
                    provider="openai",
                    model="gpt-5-mini",
                ),
            ),
            "deviations": (
                Deviation(
                    kind="fillet_default_core",
                    feature_id=fillet.feature_id,
                    chosen="3-Core",
                    rationale="no evidence it is cosmetic",
                    report_line="reviewed as structural; move to Quarantine if cosmetic",
                ),
            ),
            **overrides,
        }
    )


@pytest.fixture
def graded(tmp_path: Path) -> GradedRun:
    """Both grades of one run, over a tree whose one blank description is described."""
    before = remodel_package(
        [folder("3-Core", feature("Boss-Extrude1", "Extrusion", description=""))],
        document_id="doc:copy",
        name="bracket-RMS",
    )
    after = remodel_package(
        [folder("3-Core", feature("Boss-Extrude1", "Extrusion"))],
        document_id="doc:copy",
        name="bracket-RMS",
    )
    return grade_remodel_run(
        tmp_path / "run",
        before=before,
        after=after,
        source_design_id="dsn:4f2a91c0d3b7",
    )


def report(graded: GradedRun, **overrides: Any) -> str:
    plan = overrides.pop("plan", None) or judged(plan_of(features()))
    return render_report(
        plan=plan,
        changes=overrides.pop("changes", changes()),
        graded=graded,
        geometry=overrides.pop("geometry", geometry()),
        attestation=overrides.pop("attestation", plan.source or attestation()),
        log_targets=overrides.pop("log_targets", (COPY_PATH, COPY_PATH)),
        **overrides,
    )


# --- 1. the nine sections, in order -------------------------------------------------


def test_the_sections_are_the_nine_of_the_contract_in_that_order(graded: GradedRun) -> None:
    text = report(graded)

    headings = HEADING.findall(text)
    assert headings[1:] == list(SECTIONS[1:])
    assert len(SECTIONS) == 9


def test_the_first_heading_is_the_headline_itself(graded: GradedRun) -> None:
    """Section 1 is the report's first line, because that is where a truncated run and a
    changed attestation have to say so."""
    text = report(graded)

    assert text.splitlines()[0].startswith("# ")
    assert HEADING.findall(text)[0] == text.splitlines()[0][2:]


# --- 2. the headline ----------------------------------------------------------------


class TestHeadline:
    def test_a_run_that_moved_3_of_200_features_says_this_part_needs_rebuilding(
        self, graded: GradedRun
    ) -> None:
        big = plan_of([feature(f"Extrude{index}", "Extrusion") for index in range(200)])
        plan = big.model_copy(
            update={
                "state": "saved",
                "copy_path": COPY_PATH,
                "source": attestation(),
                "rebuild": (
                    RebuildEntry(
                        feature_id="feat:0044",
                        name="Extrude44",
                        reason="backward_reference",
                        detail="parent feat:0061 is in 6-Quarantine",
                        blocking_edge=Edge(parent_id="feat:0061", child_id="feat:0044"),
                    ),
                ),
            }
        )
        assert len(plan.targets) == 200
        moves = [change(seq, "reorder", f"Extrude{seq}", "applied") for seq in (1, 2, 3)]

        first = report(graded, plan=plan, changes=moves).splitlines()[0]

        assert "this part needs rebuilding" in first
        assert "3 of 200" in first
        assert "success" not in first.lower()

    def test_no_run_calls_itself_a_success_anywhere(self, graded: GradedRun) -> None:
        assert "success" not in report(graded).lower()

    def test_a_truncated_run_says_so_in_the_first_line(self, graded: GradedRun) -> None:
        plan = judged(plan_of(features()), state="truncated")

        first = report(graded, plan=plan).splitlines()[0]

        assert "truncated" in first

    def test_a_run_a_bound_stopped_names_the_limit(self, graded: GradedRun) -> None:
        plan = judged(plan_of(features()), state="truncated")

        first = report(graded, plan=plan, stop_reason="max_changes").splitlines()[0]

        assert "truncated by one of its limits" in first

    def test_a_run_the_engineer_stopped_names_the_stop_and_no_limit(
        self, graded: GradedRun
    ) -> None:
        """`truncated` is one state reached two ways, and the report says which.

        A run a person ended after one change and a run that ran out of room are different
        runs, and a headline that told the first it had hit a limit would assert a cause
        the evidence does not support (Principle I).
        """
        plan = judged(plan_of(features()), state="truncated")

        first = report(graded, plan=plan, stop_reason=ENGINEER_STOP).splitlines()[0]

        assert "the engineer stopped this run" in first
        assert "limit" not in first

    def test_the_save_is_never_counted_as_one_of_the_planned_changes(
        self, graded: GradedRun
    ) -> None:
        """A run that passed the gate writes a `save` line whose `seq` is the next free one
        in the log, not a plan index. Counting it would say a stopped run applied one more
        change than it did and would name the planned change of that number as applied,
        which is the change the stop prevented (Principle I)."""
        plan = judged(plan_of(features()), state="truncated")
        stopped = [
            change(1, "rename", "Fillet1", "applied"),
            change(2, "save", "", "applied", subject=None),
        ]
        missing = ", ".join(f"#{item.seq}" for item in plan.changes if item.seq != 1)

        text = report(graded, plan=plan, changes=stopped, stop_reason=ENGINEER_STOP)

        assert f"1 of {len(plan.changes)} planned changes were applied" in text
        assert "of which 1 were applied" in text
        assert f"Planned changes that were not applied: {missing}." in text

    def test_the_stop_the_headline_selects_on_is_the_executors_own_token(self) -> None:
        """One spelling of the engineer's stop, checked rather than kept in step by hand:
        the report reads the token `apply_changes` writes, and a rename of one that left
        the other behind would silently take the headline back to the limit sentence."""
        assert ENGINEER_STOP in get_args(StopReason)
        assert ENGINEER_STOP in TRUNCATING

    def test_the_save_kind_the_arithmetic_leaves_out_is_the_logs_own(self) -> None:
        """`save` is a record the run writes and never a change the plan proposes, which
        is why the "planned changes applied" count leaves it out."""
        assert SAVE in RECORD_KINDS
        assert SAVE not in CHANGE_ORDER

    def test_a_changed_source_attestation_says_so_ahead_of_everything_else(
        self, graded: GradedRun
    ) -> None:
        changed = attestation(matches=False)
        plan = judged(plan_of(features()), state="failed")

        first = report(graded, plan=plan, attestation=changed).splitlines()[0]

        assert SOURCE_PATH in first
        assert "changed" in first
        assert "rebuilding" not in first

    def test_a_gate_that_did_not_pass_is_in_the_headline(self, graded: GradedRun) -> None:
        moved = geometry(volume_m3=2.0e-3)
        assert moved.gate.verdict == "fail"

        first = report(graded, geometry=moved).splitlines()[0]

        assert "geometry" in first


# --- 3. the change list -------------------------------------------------------------


class TestChangeList:
    def test_every_attempted_change_is_listed_with_its_outcome(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        for row in changes():
            assert row.subject is not None
            assert row.subject.name in text
            assert row.status in text
        assert "could not be addressed after change 2" in text

    def test_a_change_left_in_flight_is_named_rather_than_dropped(
        self, graded: GradedRun
    ) -> None:
        """A hard crash mid-change leaves an `attempting` line naming exactly what was in
        flight; a report that showed two of three changes would hide it."""
        in_flight = [*changes(), change(4, "folder.create", "3-Core", "attempting")]

        text = report(graded, changes=in_flight)

        assert "in flight" in text
        assert "3-Core" in text

    def test_the_copy_path_is_stated_from_the_log_and_from_every_change_record(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        assert COPY_PATH in text
        assert LOG_FILE_NAME in text
        assert CHANGES_FILE_NAME in text
        assert "3 of 3" in text

    def test_a_write_to_another_path_is_reported_rather_than_claimed_away(
        self, graded: GradedRun
    ) -> None:
        """The claim is made from evidence, so evidence that contradicts it is printed."""
        elsewhere = [*changes()[:2], change(3, "reorder", "Fillet5", "applied",
                                            target_path="C:\\work\\bracket.SLDPRT")]

        text = report(graded, changes=elsewhere,
                      log_targets=(COPY_PATH, "C:\\work\\bracket.SLDPRT"))

        assert "C:\\work\\bracket.SLDPRT" in text
        assert "cannot claim" in text

    def test_the_planned_changes_that_were_not_applied_are_named(
        self, graded: GradedRun
    ) -> None:
        plan = judged(plan_of(features()), state="truncated")
        applied = [change(1, "rename", "Fillet1", "applied")]

        text = report(graded, plan=plan, changes=applied)

        assert f"1 of {len(plan.changes)}" in text


# --- 4. the grade ------------------------------------------------------------------


class TestGrade:
    def test_the_counts_are_given_before_and_after_with_the_unresolved_ids_named(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        assert f"| failed | {graded.before.grade.failed} | {graded.after.grade.failed} |" in text
        for rule_id in graded.before.grade.unresolved_rule_ids:
            assert rule_id in text

    def test_the_per_rule_delta_is_listed(self, graded: GradedRun) -> None:
        text = report(graded)

        assert graded.per_rule
        for row in graded.per_rule:
            assert row.rule_id in text
            assert f"{row.before_outcome}" in text

    def test_there_is_no_letter_grade(self, graded: GradedRun) -> None:
        text = report(graded)

        assert not re.search(r"\bgrade [A-F][+-]?\b", text)


# --- 5. the geometry ----------------------------------------------------------------


class TestGeometry:
    def test_the_verdict_the_profile_and_the_calibration_reference_are_named(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        assert "pass" in text
        assert "IDENTITY" in text
        assert "PROBE-8 2026-09-16" in text

    def test_what_the_gate_cannot_detect_is_printed_on_a_passing_run(
        self, graded: GradedRun
    ) -> None:
        artifact = geometry()
        text = report(graded, geometry=artifact)

        assert artifact.gate.verdict == "pass"
        for limit in artifact.gate.coverage_limits:
            assert limit in text

    def test_the_compared_quantities_are_listed(self, graded: GradedRun) -> None:
        artifact = geometry()
        text = report(graded, geometry=artifact)

        for delta in artifact.gate.deltas:
            assert delta.quantity in text


# --- 6. the rebuild list ------------------------------------------------------------


def test_every_rebuild_entry_names_a_reason_and_a_blocking_edge(graded: GradedRun) -> None:
    text = report(graded)

    assert "Fillet7" in text
    assert "backward_reference" in text
    assert "feat:0061" in text and "feat:0044" in text
    assert "parent feat:0061 is in 6-Quarantine" in text


def test_a_pin_is_listed_with_the_edge_that_holds_it(graded: GradedRun) -> None:
    text = report(graded)

    assert "held below its parent feat:0012" in text


# --- 7. the deviations and the coverage ---------------------------------------------


class TestDeviations:
    def test_a_fillet_defaulted_to_core_is_listed_as_reviewed_as_structural(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        assert "reviewed as structural; move to Quarantine if cosmetic" in text
        assert "Fillet5" in text

    def test_every_group_the_model_assigned_names_its_provider_and_model(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        assert "Hole1" in text
        assert "gemini" in text and "gemini-2.5-pro" in text

    def test_the_coverage_names_what_was_not_covered_and_every_scope_refusal(
        self, graded: GradedRun
    ) -> None:
        refused = Refusal(
            code="multibody",
            message="the part has 3 solid bodies",
            signal="solid_body_count",
        )
        plan = judged(plan_of(features()))
        plan = plan.model_copy(
            update={"scope": plan.scope.model_copy(update={"refusals": (refused,)})}
        )

        text = report(graded, plan=plan)

        assert "sketch dimensions" in text
        assert "not carried by IR 1.2.0" in text
        assert "the part has 3 solid bodies" in text
        assert "solid_body_count" in text


# --- 8. the judgement, and the three FR-056 claims -----------------------------------


class TestJudgement:
    def test_every_accepted_proposal_names_the_provider_and_the_model_that_made_it(
        self, graded: GradedRun
    ) -> None:
        """Read from the proposal's own fields, never from a run-level default: this run
        has a description from one provider and a global from another, and both are named
        beside their own item."""
        text = report(graded)

        description = next(
            line for line in text.splitlines() if "Mounting slot" in line
        )
        global_line = next(
            line for line in text.splitlines() if "shell_thickness" in line
        )
        assert "openai" in description and "gpt-5-mini" in description
        assert "gemini" in global_line and "gemini-2.5-pro" in global_line

    def test_every_rejected_proposal_is_listed_with_its_reason_and_rule(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        assert "PlateWidth" in text
        assert "global name must be lower_snake_case, 2 to 32 characters" in text
        assert "global.name_pattern" in text

    def test_the_added_globals_are_said_to_drive_nothing_yet(self, graded: GradedRun) -> None:
        text = report(graded)

        assert "drive nothing yet" in text

    def test_the_resilient_modeling_strategy_is_credited(self, graded: GradedRun) -> None:
        text = report(graded)

        assert "Resilient Modeling Strategy" in text

    def test_the_copy_is_called_a_proposal_and_not_an_engineering_acceptance(
        self, graded: GradedRun
    ) -> None:
        text = report(graded)

        assert "not an engineering acceptance result" in text
        assert "accepts or discards" in text


# --- 9. the attestation -------------------------------------------------------------


def test_the_attestation_section_carries_the_recorded_and_rechecked_values(
    graded: GradedRun,
) -> None:
    text = report(graded)

    assert SOURCE_PATH in text
    assert "482913" in text
    assert SOURCE_SHA in text


# --- 10. reading the run folder, and the whole report --------------------------------


def test_the_changes_and_the_log_targets_are_read_from_the_run_folder(
    tmp_path: Path, graded: GradedRun
) -> None:
    run_dir = tmp_path / "read"
    run_dir.mkdir()
    (run_dir / CHANGES_FILE_NAME).write_text(
        "".join(
            change(row.seq, row.kind, name_of(row), "attempting").model_dump_json()
            + "\n"
            + row.model_dump_json()
            + "\n"
            for row in changes()
        ),
        encoding="utf-8",
    )
    (run_dir / LOG_FILE_NAME).write_text(
        "\n".join(log_lines()) + "\n", encoding="utf-8"
    )

    assert [row.seq for row in read_changes(changes_path(run_dir))] == [
        1,
        1,
        2,
        2,
        3,
        3,
    ]
    assert read_log_targets(run_dir) == (COPY_PATH, COPY_PATH)


def logged(run_dir: Path, *lines: str) -> Path:
    """A `remodel.log` holding exactly `lines`, written the way the host writes it."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / LOG_FILE_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir


def request_line(target: str, *, trailing: str = "") -> str:
    """One mutating `remodel.log` line, composed as `ToolServiceRequestLogger.Format`
    does: the target is appended **raw**, so a space inside it ends no field."""
    return (
        "[2026-09-16T14:22:31.0000000+00:00] id=1 command=remodel.rename status=ok "
        f"elapsed_ms=310 gated=IFeature.set_Name target={target}{trailing}"
    )


def test_a_target_path_containing_a_space_is_read_whole(tmp_path: Path) -> None:
    """A run root under `C:\\Users\\First Last\\` is an ordinary Windows path.

    The host appends the target unescaped, so the field ends where the next field begins
    and not at the first space. A parse that stopped there would hand the report a
    truncated token that never equals the attested copy path, and the report would say
    this run cannot claim its writes went to the copy - on a run where every one did.
    """
    spaced = r"C:\runs\First Last\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT"

    run_dir = logged(tmp_path / "spaced", request_line(spaced))

    assert read_log_targets(run_dir) == (spaced,)


def test_a_target_is_read_to_the_field_the_host_writes_next(tmp_path: Path) -> None:
    """`refused=` and `error=` follow `target=` in `Format`'s order, and end it."""
    spaced = r"C:\runs\First Last\run\copy\bracket-RMS.SLDPRT"

    run_dir = logged(
        tmp_path / "trailing",
        request_line(spaced, trailing=" refused=IDimension.set_Name"),
        request_line(COPY_PATH, trailing=' error="Save3 answered error 1"'),
    )

    assert read_log_targets(run_dir) == (spaced, COPY_PATH)


def test_one_request_that_wrote_to_two_paths_names_both(tmp_path: Path) -> None:
    """The host joins several targets with a comma, which is the only thing the comma
    means here: one entry per path, so the report counts writes and not lines."""
    other = r"C:\runs\First Last\run\copy\bracket-RMS-2.SLDPRT"

    run_dir = logged(tmp_path / "two", request_line(f"{COPY_PATH},{other}"))

    assert read_log_targets(run_dir) == (COPY_PATH, other)


def test_write_report_writes_the_rendered_report_into_the_run_folder(
    tmp_path: Path, graded: GradedRun
) -> None:
    run_dir = tmp_path / "written"
    run_dir.mkdir()
    plan = judged(plan_of(features()))

    path = write_report(
        run_dir,
        plan=plan,
        changes=changes(),
        graded=graded,
        geometry=geometry(),
        attestation=attestation(),
        log_targets=(COPY_PATH,),
    )

    assert path == run_dir / REPORT_FILE_NAME
    assert path.read_text(encoding="utf-8").startswith("# ")


def test_the_whole_report(graded: GradedRun, file_regression: FileRegressionFixture) -> None:
    file_regression.check(report(graded), extension=".md", encoding="utf-8", newline="")
