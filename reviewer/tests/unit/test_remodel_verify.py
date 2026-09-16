"""The VERIFY phase, and the SAVE it gates (T104).

`apply.verify` is the last thing the executor does to a document, and it is the one place
the constitution's mutation exception is honoured: the copy is saved "only after the
geometry comparison has passed". Three readings decide that, and all three have to hold:

- `GetWhatsWrongCount()` reads **zero**, which is the corroborating reading;
- every `IFeature.GetErrorCode2` equals `swFeatureErrorNone = 0`, which is the **primary**
  one (`contracts/bridge-remodel.md`: `whats_wrong[]`'s element type is UNVERIFIED and
  re-joining it by name is fragile, so the per-feature walk is what the phase reads);
- the gate returns `pass` under `IDENTITY`, calibrated.

Any one of the three failing discards the copy, keeps every other artifact, writes
`report.md` saying why, and **does not save**. A `pass` is never inferred from a rebuild
that answered without errors: the verdict comes from `evaluate()` over two readings of the
copy, and a run that never took the second one cannot reach one.

Everything here drives `tests/support/remodel_bridge.py`, which scripts the failure. No
SOLIDWORKS, no provider, and no live bridge.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from swreview.bridge.client import BridgeError
from swreview.bridge.remodel_client import RemodelSaveError
from swreview.remodel.apply import (
    FEATURE_ERROR_NONE,
    FEATURE_ERRORS,
    GATE_NOT_PASSED,
    REBUILD_ERRORS,
    UNANSWERED,
    VERIFY_CHECKS,
    VERIFY_PROFILE,
    ApplyResult,
    VerifyRefused,
    open_log,
    verify,
)
from swreview.remodel.apply_log import ChangeRecord, changes_path, read_changes
from swreview.remodel.artifacts import GRADES_FILE_NAME, GradedRun, grade_remodel_run
from swreview.remodel.attestation import (
    ATTESTATION_FILE_NAME,
    attestation_from_open,
    read_attestation,
)
from swreview.remodel.geometry import (
    GEOMETRY_FILE_NAME,
    GeometryArtifact,
    GeometryReading,
    reading_from_reply,
)
from swreview.remodel.plan import (
    PACKAGE_BEFORE,
    PLAN_FILE_NAME,
    RemodelPlan,
    SourceAttestation,
    plan_path,
    plan_reorganize,
    record_state,
)
from swreview.remodel.report import (
    ATTESTATION_CHANGED,
    GATE_DID_NOT_PASS,
    GEOMETRY_NOT_READ,
    REPORT_FILE_NAME,
)
from swreview.remodel.scope import ScopeSignals
from swreview.remodel.tolerances import EQUIVALENCE, IDENTITY, UncalibratedProfileError
from tests.support.features import FeatureSpec, feature, fillet_feature
from tests.support.remodel import remodel_package, scope_signals
from tests.support.remodel_bridge import (
    COPY_PATH,
    FakeRemodelBridge,
    FakeTree,
    Script,
    StepClock,
    tree,
)

AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
SOURCE_SHA = "4c" * 32
RUN_ID = "20260916-142201-bracket-remodel"

BOSS, FILLET = "pr:boss1", "pr:fillet1"

CALIBRATED = IDENTITY.model_copy(
    update={"calibrated": True, "calibration_ref": "PROBE-8 2026-09-16"}
)
"""`IDENTITY` as PROBE-8 will leave it. The profile refuses to decide a run until then,
so a test that wants a verdict says so here rather than by reaching past the refusal."""


# --- the fixture run ----------------------------------------------------------------


def part(**overrides: Any) -> FakeTree:
    """Two features in tree order, neither of them in error unless a test says so."""
    return replace(tree((BOSS, "Boss-Extrude1"), (FILLET, "Fillet1")), **overrides)


def reading(**overrides: Any) -> dict[str, Any]:
    """One `remodel.geometry` reply **as JSON**: every vector is a list, not a tuple.

    That is what the bridge answers with, and `GeometryReading` is strict, so a reading
    that validated only from hand-built tuples would prove nothing about the wire.
    """
    return {
        "at": "2026-09-16T14:22:01Z",
        "source_sha256": SOURCE_SHA,
        "subject": "copy_at_open",
        "status": 0,
        "accuracy_level": 2,
        "recalculated": True,
        "volume_m3": 1.23456789e-3,
        "surface_area_m2": 4.56e-2,
        "center_of_mass_m": [0.01, 0.02, 0.03],
        "principal_moments": [1.1e-5, 2.2e-5, 3.3e-5],
        "mass_kg": 3.21,
        "density": 2600.0,
        "material_name": "1060 Alloy",
        "solid_body_count": 1,
        "sheet_body_count": 0,
        "face_count": 214,
        "edge_count": 642,
        "residual": None,
        **overrides,
    }


def features() -> list[FeatureSpec]:
    return [feature("Boss-Extrude1", "Extrusion"), fillet_feature("Fillet1")]


SOURCE_CONTENT = b"the engineer's file, byte for byte"


def source_file(run_dir: Path) -> Path:
    """The engineer's file, on disk beside the run folder.

    A real file, because the VERIFY phase re-checks the attestation itself before it
    decides anything (FR-040): a fixture naming a path that does not exist would make
    every run in this module a run whose source could not be re-read, which is a failure
    and not a pass.
    """
    path = run_dir.parent / "bracket.SLDPRT"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(SOURCE_CONTENT)
    return path


def attestation(run_dir: Path, **overrides: Any) -> SourceAttestation:
    """The recorded half, measured from that file the way `remodel.open` records it.

    Read through the product's own `attestation_from_open`, so the fixture has no second
    idea of what the record is, and with `matches` and `rechecked_at` unset: the verdict
    is the phase's to reach.
    """
    source = source_file(run_dir)
    return attestation_from_open(
        {
            "path": str(source),
            "length_bytes": source.stat().st_size,
            "last_write_utc": _last_write_utc(source).isoformat().replace("+00:00", "Z"),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_design_id": "dsn:4f2a91c0d3b7",
            "recorded_at": AT.isoformat().replace("+00:00", "Z"),
            "vault_path": None,
            "vault_revision": None,
            "copy_path": COPY_PATH,
            **overrides,
        }
    )


def _last_write_utc(path: Path) -> datetime:
    """The file's last-write time truncated to whole microseconds, the precision both
    halves of the comparison are made at (`remodel/attestation.py`)."""
    seconds, nanoseconds = divmod(path.stat().st_mtime_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanoseconds // 1000)


def plan_of(run_dir: Path, state: str = "applying") -> RemodelPlan:
    """The plan as the executor leaves it: the copy made, the source attested."""
    package = remodel_package(features(), document_id="doc:copy", name="bracket-RMS")
    plan = plan_reorganize(
        package,
        signals=ScopeSignals(**scope_signals()),
        probe_id="probe:1",
        now=AT,
    )
    return plan.model_copy(
        update={
            "state": state,
            "run_id": RUN_ID,
            "copy_path": COPY_PATH,
            "source": attestation(run_dir),
        }
    )


def in_flight_line() -> ChangeRecord:
    """The one line the T082 rebuild-timeout path leaves behind: announced, never closed.

    Written by hand rather than by running the apply phase, because what VERIFY has to do
    about it is decided from `ApplyResult.in_flight` and the log's own last line, and both
    are what a crashed run leaves on disk.
    """
    return ChangeRecord(
        seq=1,
        at="2026-09-16T14:22:01Z",
        kind="rename",
        subject=None,
        before={},
        after={},
        undo=None,
        rebuild_errors_before=0,
        rebuild_errors_after=None,
        status="attempting",
        error_code=None,
        error=None,
        target_path=COPY_PATH,
        elapsed_ms=None,
    )


def applied(status: str = "complete") -> ApplyResult:
    """What the apply phase reported. Only its `status` decides the run's final state."""
    return ApplyResult(
        status=status,  # type: ignore[arg-type]
        planned=(1,),
        applied=(1,),
        rolled_back=(),
        failed=(),
        rollback_failed=(),
        not_attempted=(),
        in_flight=None,
        stop=None,
        escalates_to_replay=False,
    )


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / RUN_ID


@pytest.fixture
def graded(run_dir: Path) -> GradedRun:
    """Both grades of the run, written into the run folder before VERIFY starts.

    `data-model.md` section 11 puts `grades.json` among the artifacts that are complete
    when `verifying` is entered, which is why this is a fixture and not something the
    phase produces.
    """
    package = remodel_package(features(), document_id="doc:copy", name="bracket-RMS")
    return grade_remodel_run(
        run_dir,
        before=package,
        after=package,
        source_design_id="dsn:4f2a91c0d3b7",
    )


def bridge_with(
    readings: Sequence[dict[str, Any]] | None = None,
    *,
    tree_: FakeTree | None = None,
    script: Script | None = None,
) -> FakeRemodelBridge:
    return FakeRemodelBridge(
        tree_ or part(),
        script=script,
        readings=list(readings if readings is not None else (reading(), reading())),
    )


def opened(bridge: FakeRemodelBridge) -> GeometryReading:
    """The baseline reading, taken the way the run takes it: from the copy, at open.

    The host stamps the subject from its own phase, so the first reading of a run is
    `copy_at_open` and every later one is `copy_at_end`. Taking it here rather than
    hand-building one is also what makes the save's own rule true: the host refuses a
    reported `pass` from a run it did not take both readings for.
    """
    return reading_from_reply(bridge.geometry())


def run_verify(
    run_dir: Path,
    graded: GradedRun,
    bridge: FakeRemodelBridge,
    **overrides: Any,
) -> Any:
    """Drive the VERIFY phase over `bridge`, with the baseline already read."""
    before = overrides.pop("before", None) or opened(bridge)
    plan = overrides.pop("plan", None) or plan_of(run_dir)
    return verify(
        client=bridge,
        log=overrides.pop("log", None) or open_log(run_dir),
        run_dir=run_dir,
        plan=plan,
        applied=overrides.pop("applied", None) or applied(),
        before=before,
        tolerances=overrides.pop("tolerances", CALIBRATED),
        graded=graded,
        attestation=overrides.pop("attestation", None) or attestation(run_dir),
        now=overrides.pop("now", None) or StepClock(AT, 1.0),
        **overrides,
    )


def state_on_disk(run_dir: Path) -> str:
    body = json.loads(plan_path(run_dir).read_text(encoding="utf-8"))
    return str(body["state"])


# --- 1. the three checks -------------------------------------------------------------


class TestTheThreeChecks:
    """`GetWhatsWrongCount`, the per-feature walk and the gate. All three, or no save."""

    def test_the_checks_are_the_three_the_contract_names(self) -> None:
        assert VERIFY_CHECKS == ("rebuild_errors", "feature_errors", "geometry_gate")

    def test_the_profile_is_identity(self) -> None:
        assert VERIFY_PROFILE == "IDENTITY"

    def test_a_clean_tree_and_an_unmoved_geometry_passes_and_saves(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with()
        result = run_verify(run_dir, graded, bridge)

        assert result.passed is True
        assert result.reasons == ()
        assert result.rebuild_errors == 0
        assert result.feature_errors == ()
        assert result.gate is not None and result.gate.verdict == "pass"
        assert result.saved is True
        assert result.state == "saved"
        assert bridge.saves == 1

    def test_a_rebuild_error_count_above_zero_does_not_save(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with()
        bridge.rebuild_errors = 2
        result = run_verify(run_dir, graded, bridge)

        assert result.passed is False
        assert result.saved is False
        assert bridge.saves == 0
        assert result.rebuild_errors == 2
        assert REBUILD_ERRORS.format(count=2) in result.reasons

    def test_a_feature_error_code_other_than_none_does_not_save(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """The per-feature walk is the primary reading, so it fails a run on its own.

        `GetWhatsWrongCount()` reads zero here and the gate passes: a run that read only
        the corroborating count would save this part.
        """
        bridge = bridge_with(tree_=part(feature_errors={FILLET: 4}))
        result = run_verify(run_dir, graded, bridge)

        assert bridge.rebuild_errors == 0
        assert result.passed is False
        assert result.saved is False
        assert bridge.saves == 0
        assert [row["persist_ref"] for row in result.feature_errors] == [FILLET]
        assert any(FEATURE_ERRORS.split("{")[0] in reason for reason in result.reasons)
        assert any("Fillet1" in reason and "4" in reason for reason in result.reasons)

    def test_a_feature_error_flagged_as_a_warning_still_fails(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """`GetErrorCode2`'s out Boolean says a code is a warning; the code is what is
        read. `swFeatureErrorNone = 0` is the only acceptable value at verify time."""
        bridge = bridge_with(
            tree_=part(feature_errors={BOSS: 1}, feature_warnings=(BOSS,))
        )
        result = run_verify(run_dir, graded, bridge)

        assert result.passed is False
        assert result.feature_errors[0]["is_warning"] is True
        assert bridge.saves == 0

    def test_feature_error_none_is_zero(self) -> None:
        assert FEATURE_ERROR_NONE == 0

    def test_a_gate_that_fails_does_not_save(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        moved = reading(volume_m3=1.3e-3)
        bridge = bridge_with((reading(), moved))
        result = run_verify(run_dir, graded, bridge)

        assert result.gate is not None and result.gate.verdict == "fail"
        assert result.passed is False
        assert result.saved is False
        assert bridge.saves == 0
        assert any(GATE_NOT_PASSED.split("{")[0] in reason for reason in result.reasons)

    def test_a_gate_that_is_unresolved_does_not_save(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """An `unresolved` gate does **not** save (data-model section 11). A reading the
        mass-properties call could not complete is not a difference and not an absence."""
        bridge = bridge_with((reading(), reading(status=3)))
        result = run_verify(run_dir, graded, bridge)

        assert result.gate is not None and result.gate.verdict == "unresolved"
        assert result.passed is False
        assert result.saved is False
        assert bridge.saves == 0

    def test_every_failing_check_is_named_and_none_is_swallowed(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with((reading(), reading(volume_m3=1.3e-3)))
        bridge.rebuild_errors = 1
        bridge.tree.feature_errors = {BOSS: 1}
        result = run_verify(run_dir, graded, bridge)

        assert len(result.reasons) == len(VERIFY_CHECKS)
        assert result.state == "failed"


# --- 2. a pass is never inferred ------------------------------------------------------


class TestThePassIsNeverInferred:
    """A rebuild that answered is not a gate, and a gate nobody ran is not a pass."""

    def test_a_rebuild_with_no_errors_is_not_on_its_own_a_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with((reading(), reading(face_count=213)))
        result = run_verify(run_dir, graded, bridge)

        assert result.rebuild_errors == 0
        assert result.feature_errors == ()
        assert result.passed is False
        assert bridge.saves == 0

    def test_the_gate_is_read_from_a_second_geometry_reading_of_the_copy(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with()
        result = run_verify(run_dir, graded, bridge)

        assert bridge.commands.count("remodel.geometry") == 2
        artifact = GeometryArtifact.model_validate_json(
            (run_dir / GEOMETRY_FILE_NAME).read_text(encoding="utf-8")
        )
        assert artifact.before.subject == "copy_at_open"
        assert artifact.after.subject == "copy_at_end"
        assert artifact.gate == result.gate

    def test_a_geometry_reading_that_never_came_back_is_not_a_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with(script=Script(geometry_raises={2: BridgeError("no answer")}))
        result = run_verify(run_dir, graded, bridge)

        assert result.gate is None
        assert result.passed is False
        assert result.saved is False
        assert bridge.saves == 0
        assert any(UNANSWERED.split("{")[0] in reason for reason in result.reasons)
        # Section 11 lists `report.md` among the artifacts of a failed run without
        # exception: an engineer left with a discarded copy and no account of why is
        # exactly what the report exists to prevent.
        assert result.copy_discarded is True
        assert result.report_path is not None and result.report_path.is_file()
        assert GEOMETRY_NOT_READ in result.report_path.read_text(encoding="utf-8")

    def test_a_rebuild_reply_with_no_feature_error_reading_is_not_a_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """`feature_errors[]` is the primary reading, and a reply that carries none is a
        host that did not take it. Absent is not none, and it is not an exception out of
        the phase either: it reaches the same discard-and-report path as a dead bridge."""
        bridge = bridge_with(script=Script(rebuild_omits=frozenset({"feature_errors"})))
        result = run_verify(run_dir, graded, bridge)

        assert result.passed is False
        assert result.rebuild_errors is None
        assert result.feature_errors == ()
        assert bridge.saves == 0
        assert result.copy_discarded is True
        assert result.report_path is not None and result.report_path.is_file()
        assert any("remodel.rebuild" in reason for reason in result.reasons)

    def test_a_rebuild_reply_with_no_error_count_is_not_a_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with(script=Script(rebuild_omits=frozenset({"rebuild_errors"})))
        result = run_verify(run_dir, graded, bridge)

        assert result.passed is False
        assert result.rebuild_errors is None
        assert bridge.saves == 0
        assert result.copy_discarded is True

    def test_a_change_left_in_flight_is_never_verified_into_a_save(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """T082's `rebuild_timeout` path leaves a change with its `attempting` line and no
        terminal partner. Nobody read what that change did, so the run is not verified: it
        finalizes, discards the copy and writes the report rather than saving or raising."""
        log = open_log(run_dir)
        log.append(in_flight_line())
        truncated = replace(applied("truncated"), in_flight=1)
        bridge = bridge_with()
        result = run_verify(run_dir, graded, bridge, applied=truncated, log=log)

        assert result.passed is False
        assert result.saved is False
        assert bridge.saves == 0
        assert result.state == "failed"
        assert state_on_disk(run_dir) == "failed"
        assert result.copy_discarded is True
        assert result.report_path is not None and result.report_path.is_file()
        assert any("1" in reason and "in flight" in reason for reason in result.reasons)
        # The log is left exactly as the apply phase left it: nothing closed the line.
        assert [row.status for row in read_changes(changes_path(run_dir))] == ["attempting"]

    def test_a_rebuild_reading_that_never_came_back_is_not_a_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with(script=Script(rebuild_raises={0: BridgeError("no answer")}))
        result = run_verify(run_dir, graded, bridge)

        assert result.rebuild_errors is None
        assert result.passed is False
        assert bridge.saves == 0

    def test_the_verdict_handed_to_the_bridge_is_the_gates_own(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with()
        result = run_verify(run_dir, graded, bridge)

        assert ("remodel.save", {"verdict": "pass"}) in bridge.calls
        assert result.gate is not None and result.gate.verdict == "pass"

    def test_the_bridge_refuses_a_save_this_side_did_not_gate(self) -> None:
        """The clause is enforced beside `Save3` too, and the fake stands in for that:
        a clause checked only by the caller is a clause the caller can skip."""
        bridge = bridge_with()
        bridge.geometry()
        bridge.geometry()
        with pytest.raises(BridgeError):
            bridge.save("fail")
        assert bridge.saves == 0

    def test_an_aborted_apply_phase_never_reaches_a_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """An abort leaves a tree nothing after it can be attributed to. The three
        readings may still be clean, and the run is failed anyway."""
        bridge = bridge_with()
        result = run_verify(run_dir, graded, bridge, applied=applied("aborted"))

        assert result.passed is False
        assert result.state == "failed"
        assert bridge.saves == 0


# --- 3. the discard, and what survives it ---------------------------------------------


class TestTheDiscard:
    """A verification failure deletes `copy/` and nothing else."""

    def test_the_copy_is_discarded_when_the_gate_does_not_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with((reading(), reading(volume_m3=1.3e-3)))
        result = run_verify(run_dir, graded, bridge)

        assert result.copy_discarded is True
        assert bridge.discards == 1
        assert bridge.copy_exists is False
        assert ("remodel.close", {"discard_copy": True}) in bridge.calls

    def test_the_discard_keeps_every_other_artifact(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """Deleting the run folder would lose the evidence Principle VI asks for: "what
        did it propose" has to stay answerable after the run says no."""
        bridge = bridge_with((reading(), reading(volume_m3=1.3e-3)))
        run_verify(run_dir, graded, bridge)

        for name in (
            PLAN_FILE_NAME,
            GEOMETRY_FILE_NAME,
            REPORT_FILE_NAME,
            GRADES_FILE_NAME,
            PACKAGE_BEFORE,
        ):
            assert (run_dir / name).is_file(), name

    def test_a_pass_does_not_discard_the_copy(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """Discard is the engineer's, on a run that reached `saved` (section 11)."""
        bridge = bridge_with()
        result = run_verify(run_dir, graded, bridge)

        assert result.copy_discarded is False
        assert bridge.discards == 0
        assert bridge.copy_exists is True

    def test_nothing_is_saved_on_the_discard_path(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with((reading(), reading(volume_m3=1.3e-3)))
        run_verify(run_dir, graded, bridge)

        assert "remodel.save" not in bridge.commands
        assert [row.kind for row in read_changes(changes_path(run_dir))] == []


# --- 4. the save, gated behind the verification ----------------------------------------


class TestTheSaveIsGatedBehindVerify:
    """The copy is saved once, at the end, and only after the three checks hold."""

    def test_the_save_is_the_last_command_and_follows_both_readings(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with()
        run_verify(run_dir, graded, bridge)

        assert bridge.commands == (
            "remodel.geometry",
            "remodel.rebuild",
            "remodel.geometry",
            "remodel.save",
        )

    def test_the_save_is_recorded_as_the_attempting_and_terminal_pair(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with()
        run_verify(run_dir, graded, bridge)

        rows = read_changes(changes_path(run_dir))
        assert [(row.kind, row.status) for row in rows] == [
            ("save", "attempting"),
            ("save", "applied"),
        ]
        assert all(row.subject is None for row in rows)
        assert all(row.target_path == COPY_PATH for row in rows)

    def test_a_save_that_answers_an_error_is_a_failed_run(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        refusal = RemodelSaveError(
            "Save3 answered error 1", "save_failed", {"saved": "false"}
        )
        bridge = bridge_with(script=Script(save_raises=refusal))
        result = run_verify(run_dir, graded, bridge)

        assert result.saved is False
        assert result.state == "failed"
        assert any("save_failed" in reason for reason in result.reasons)
        rows = read_changes(changes_path(run_dir))
        assert rows[-1].status == "failed"
        assert rows[-1].error_code == "save_failed"

    def test_a_rebuild_error_warning_is_a_failed_run_with_a_saved_artifact(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """`warnings & swFileSaveWarning_RebuildError` leaves a file on disk and the run
        failed; the run says exactly that rather than counting it a success."""
        refusal = RemodelSaveError(
            "saved with a rebuild error warning", "save_failed", {"saved": "true"}
        )
        bridge = bridge_with(script=Script(save_raises=refusal))
        result = run_verify(run_dir, graded, bridge)

        assert result.state == "failed"
        assert result.saved is False
        assert result.copy_discarded is False
        assert "success" not in " ".join(result.reasons).lower()

    def test_a_failed_save_does_not_discard_the_copy(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """The copy is discarded on a **verification** failure. A save that failed may
        have left an artifact, and whether the engineer has a file to look at is the
        difference the host reports on."""
        refusal = RemodelSaveError("Save3 answered error 1", "save_failed", {})
        bridge = bridge_with(script=Script(save_raises=refusal))
        result = run_verify(run_dir, graded, bridge)

        assert result.copy_discarded is False
        assert bridge.discards == 0


# --- 5. the run state, as section 11 fixes it -------------------------------------------


class TestTheRunState:
    """One field on the plan, rewritten to `plan.json` at every transition."""

    def test_a_passing_run_is_saved_on_disk_and_in_the_result(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        result = run_verify(run_dir, graded, bridge_with())

        assert result.state == "saved"
        assert result.plan.state == "saved"
        assert state_on_disk(run_dir) == "saved"

    def test_a_truncated_apply_phase_finalizes_as_truncated(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """`truncated` is never silent: a distinct state and a distinct report line."""
        result = run_verify(
            run_dir, graded, bridge_with(), applied=applied("truncated")
        )

        assert result.state == "truncated"
        assert state_on_disk(run_dir) == "truncated"
        assert result.saved is True

    def test_a_failed_verification_writes_failed(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with((reading(), reading(volume_m3=1.3e-3)))
        result = run_verify(run_dir, graded, bridge)

        assert result.state == "failed"
        assert state_on_disk(run_dir) == "failed"

    def test_the_run_passes_through_verifying(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """The only path into `saved` runs through `verifying`, so a plan that never
        entered it cannot be moved there."""
        run_verify(run_dir, graded, bridge_with())
        with pytest.raises(ValueError, match="verifying"):
            record_state(run_dir, plan_of(run_dir, "applying"), "saved", at=AT)

    def test_saved_and_truncated_are_entered_only_from_verifying(
        self, run_dir: Path
    ) -> None:
        for state in ("planned", "judging", "applying"):
            for wanted in ("saved", "truncated"):
                with pytest.raises(ValueError):
                    record_state(run_dir, plan_of(run_dir, state), wanted, at=AT)

    def test_discarded_is_entered_only_from_saved_or_truncated(
        self, run_dir: Path
    ) -> None:
        for state in ("saved", "truncated"):
            moved = record_state(run_dir, plan_of(run_dir, state), "discarded", at=AT)
            assert moved.state == "discarded"
        with pytest.raises(ValueError):
            record_state(run_dir, plan_of(run_dir, "applying"), "discarded", at=AT)

    def test_any_state_can_fail(self, run_dir: Path) -> None:
        for state in ("planned", "judging", "applying", "verifying", "saved"):
            assert record_state(run_dir, plan_of(run_dir, state), "failed", at=AT).state == "failed"

    def test_the_transition_stamps_updated_at_and_leaves_the_rest_alone(
        self, run_dir: Path
    ) -> None:
        before = plan_of(run_dir, "applying")
        after = record_state(run_dir, before, "verifying", at=AT)

        assert after.updated_at == AT
        assert after.model_dump(exclude={"state", "updated_at"}) == before.model_dump(
            exclude={"state", "updated_at"}
        )


# --- 6. the report ----------------------------------------------------------------------


class TestTheReport:
    """`report.md` is written whatever the verdict, and it says why."""

    def test_the_report_is_written_on_the_passing_path(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        result = run_verify(run_dir, graded, bridge_with())

        assert result.report_path == run_dir / REPORT_FILE_NAME
        assert result.report_path.is_file()

    def test_a_failed_gate_says_why_in_the_report(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with((reading(), reading(volume_m3=1.3e-3)))
        result = run_verify(run_dir, graded, bridge)

        text = result.report_path.read_text(encoding="utf-8")
        assert GATE_DID_NOT_PASS in text.splitlines()[0]
        assert result.gate is not None and result.gate.diagnosis is not None
        assert result.gate.diagnosis in text

    def test_no_report_calls_a_failed_verification_a_success(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with((reading(), reading(volume_m3=1.3e-3)))
        result = run_verify(run_dir, graded, bridge)

        assert "success" not in result.report_path.read_text(encoding="utf-8").lower()


# --- 7. what the phase refuses before it reads anything ----------------------------------


class TestWhatVerifyRefuses:
    """A profile nobody calibrated, a profile this stage does not decide under, and a
    plan with no copy: each is refused before a document is touched."""

    def test_an_uncalibrated_profile_refuses_the_run(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        bridge = bridge_with()
        with pytest.raises(UncalibratedProfileError):
            run_verify(run_dir, graded, bridge, tolerances=IDENTITY)
        assert "remodel.rebuild" not in bridge.commands

    def test_a_profile_other_than_identity_is_refused(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        other = EQUIVALENCE.model_copy(
            update={"calibrated": True, "calibration_ref": "PROBE-8"}
        )
        bridge = bridge_with()
        with pytest.raises(VerifyRefused, match="IDENTITY"):
            run_verify(run_dir, graded, bridge, tolerances=other)
        assert "remodel.rebuild" not in bridge.commands

    def test_a_plan_with_no_copy_is_refused(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        dry = plan_of(run_dir).model_copy(
            update={"run_id": None, "copy_path": None, "source": None}
        )
        bridge = bridge_with()
        with pytest.raises(VerifyRefused, match="copy"):
            run_verify(run_dir, graded, bridge, plan=dry)
        assert "remodel.rebuild" not in bridge.commands


# --- 8. the source attestation, re-checked here ------------------------------------------


class TestTheSourceAttestation:
    """The re-check of FR-040 happens in this phase, and a difference fails the run.

    `contracts/run-artifacts.md` calls a `matches` of `false` "a hard failure of the run …
    recorded as failed regardless of how well everything else went", and the report says so
    in its first line. A phase that reported that headline while saving the copy and writing
    `plan.json` as `saved` would leave two artifacts of one run contradicting each other, so
    the re-check is taken here, before the save decision, and the copy is discarded on it.
    """

    def test_a_completed_run_leaves_the_rechecked_half_on_disk(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """`source-attestation.json` carries the verdict after the run, not `null`."""
        recorded = attestation(run_dir)

        run_verify(run_dir, graded, bridge_with(), attestation=recorded)

        written = read_attestation(run_dir)
        assert (run_dir / ATTESTATION_FILE_NAME).is_file()
        assert written.matches is True
        assert written.rechecked_at is not None and written.rechecked_at >= AT
        assert written.model_dump(exclude={"rechecked_at", "matches"}) == recorded.model_dump(
            exclude={"rechecked_at", "matches"}
        )

    def test_a_source_that_changed_during_the_run_is_not_saved(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """Every other reading is clean here: the attestation alone fails the run."""
        recorded = attestation(run_dir)
        source_file(run_dir).write_bytes(b"the engineer saved over it mid-run")
        bridge = bridge_with()

        result = run_verify(run_dir, graded, bridge, attestation=recorded)

        assert result.passed is False
        assert result.saved is False
        assert bridge.saves == 0
        assert result.state == "failed"
        assert state_on_disk(run_dir) == "failed"
        assert any("is not what it was" in reason for reason in result.reasons)

    def test_a_changed_source_discards_the_copy_and_files_the_difference(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """The evidence is on disk before the run fails on it."""
        recorded = attestation(run_dir)
        source_file(run_dir).write_bytes(b"the engineer saved over it mid-run")
        bridge = bridge_with()

        result = run_verify(run_dir, graded, bridge, attestation=recorded)

        assert result.copy_discarded is True
        assert bridge.discards == 1
        written = read_attestation(run_dir)
        assert written.matches is False
        assert written.rechecked_at is not None

    def test_a_source_that_could_not_be_reread_is_not_a_pass(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """"Could not check" is never "unchanged" (constitution Principle I)."""
        recorded = attestation(run_dir)
        plan = plan_of(run_dir)
        source_file(run_dir).unlink()
        bridge = bridge_with()

        result = run_verify(run_dir, graded, bridge, attestation=recorded, plan=plan)

        assert result.saved is False
        assert result.state == "failed"
        assert read_attestation(run_dir).matches is False
        assert any("no file at this path" in reason for reason in result.reasons)

    def test_the_headline_of_a_changed_source_run_says_so(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """Section 1 of the report, ahead of everything else, and no contradiction with
        `plan.json`: the report is written from the re-checked record this phase reached."""
        recorded = attestation(run_dir)
        source_file(run_dir).write_bytes(b"the engineer saved over it mid-run")

        result = run_verify(run_dir, graded, bridge_with(), attestation=recorded)

        text = result.report_path.read_text(encoding="utf-8")
        assert text.splitlines()[0] == f"# {ATTESTATION_CHANGED.format(path=recorded.path)}"
        assert state_on_disk(run_dir) == "failed"

    def test_an_unchanged_source_saves_exactly_as_before(
        self, run_dir: Path, graded: GradedRun
    ) -> None:
        """The fourth gate costs the passing run nothing: one re-check, no extra command."""
        bridge = bridge_with()

        result = run_verify(run_dir, graded, bridge)

        assert result.passed is True
        assert result.saved is True
        assert result.state == "saved"
        assert bridge.commands == (
            "remodel.geometry",
            "remodel.rebuild",
            "remodel.geometry",
            "remodel.save",
        )
