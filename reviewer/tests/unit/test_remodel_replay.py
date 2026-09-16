"""The catastrophic fallback: delete the copy, re-copy the source, replay (T084).

`data-model.md` section 2.2's tier 2, driven over the same fake seat the executor's tests
use, so the whole sequence - close with discard, re-open, replay - is a real sequence here
and not an assertion about intent. The trigger is the one kind with no forward inverse in
v1: a `folder.create` that lands and raises the rebuild-error count, which cannot be undone
in place because dissolving a folder needs a member the owner kept off the stage-1
allowlist.

What is pinned:

- **the order.** The source attestation is re-checked *before* anything is deleted, so a
  source that moved refuses the fallback with the copy and the log still intact. A replay
  that re-copied a file nobody re-checked would produce a copy this run could claim nothing
  about;
- **what is replayed.** The changes whose record says `applied`, in `seq` order. Not the
  rolled-back ones, which left no mark, and never the change that triggered the fallback;
- **determinism.** Every replayed call is addressed by persistent reference, which a
  byte-for-byte re-copy carries across, so the replayed tree is the tree the run had
  reached;
- **it never loops.** A replayed pass that ends the same way says so and stops. Exactly one
  re-copy is made, whatever happens;
- **tier 3 does not exist.** No file of the stage-1 surface, Python or C#, names the
  document undo member at all.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from swreview.remodel.apply import apply_changes, open_log
from swreview.remodel.apply_log import changes_path, read_changes
from swreview.remodel.attestation import SourceChanged, attestation_from_open
from swreview.remodel.plan import ChangeSubject, Limits, PlannedChange, SourceAttestation
from swreview.remodel.replay import ReplayResult, applied_changes, replay_run
from tests.support.remodel import code_lines, stage_1_sources
from tests.support.remodel_bridge import FakeRemodelBridge, Script, StepClock, tree

START = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
RECORDED_AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
CONTENT = b"the engineer's file, byte for byte"

SKETCH, BOSS, CUT, FILLET = "pr:sketch1", "pr:boss1", "pr:cut1", "pr:fillet1"

RUN_ID = "20260916-142201-bracket-remodel"
PROBE_ID = "probe:7f2a"


def part() -> Any:
    return tree(
        (SKETCH, "Sketch1"),
        (BOSS, "Boss-Extrude1"),
        (CUT, "Cut-Extrude1"),
        (FILLET, "Fillet1"),
    )


def last_write_utc(path: Path) -> datetime:
    """The file's last-write time at the precision both halves of the comparison use."""
    seconds, nanoseconds = divmod(path.stat().st_mtime_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanoseconds // 1000)


def attested(tmp_path: Path) -> tuple[Path, Path, SourceAttestation]:
    """A real source file on disk and the attestation `remodel.open` recorded of it."""
    source = tmp_path / "bracket.SLDPRT"
    source.write_bytes(CONTENT)
    copy = tmp_path / RUN_ID / "copy" / "bracket-RMS.SLDPRT"
    recorded = attestation_from_open(
        {
            "path": str(source),
            "length_bytes": source.stat().st_size,
            "last_write_utc": last_write_utc(source).isoformat().replace("+00:00", "Z"),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_design_id": "dsn:4f2a91c0d3b7",
            "recorded_at": RECORDED_AT.isoformat().replace("+00:00", "Z"),
            "copy_path": str(copy),
            "vault_path": None,
            "vault_revision": None,
        }
    )
    return source, copy, recorded


def subject(feature_id: str, name: str, persist_ref: str) -> ChangeSubject:
    return ChangeSubject(feature_id=feature_id, name=name, persist_ref=persist_ref)


def changes() -> tuple[PlannedChange, ...]:
    """A rename, a reorder and two folder creations: C1, C3, then C4 twice."""
    return (
        PlannedChange(
            seq=1,
            kind="rename",
            subject_kind="feature",
            subject=subject("feat:0004", "Fillet1", FILLET),
            params={"persist_ref": FILLET, "new_name": "Fillet1_2"},
            expect={"rebuild_errors_delta": 0},
        ),
        PlannedChange(
            seq=2,
            kind="reorder",
            subject_kind="feature",
            subject=subject("feat:0004", "Fillet1", FILLET),
            params={
                "feature_persist_ref": FILLET,
                "anchor_persist_ref": BOSS,
                "location": "after",
            },
            expect={"rebuild_errors_delta": 0},
        ),
        PlannedChange(
            seq=3,
            kind="folder.create",
            subject_kind="folder",
            subject=None,
            params={
                "op": "create",
                "name": "3-Core",
                "member_persist_refs": [BOSS, FILLET],
                "folder_persist_ref": None,
            },
            expect={"folder_location": "3-Core", "rebuild_errors_delta": 0},
        ),
        PlannedChange(
            seq=4,
            kind="folder.create",
            subject_kind="folder",
            subject=None,
            params={
                "op": "create",
                "name": "1-Ref",
                "member_persist_refs": [SKETCH],
                "folder_persist_ref": None,
            },
            expect={"folder_location": "1-Ref", "rebuild_errors_delta": 0},
        ),
    )


WRITES: frozenset[str] = frozenset(
    {
        "remodel.rename",
        "remodel.reorder",
        "remodel.folder",
        "remodel.describe",
        "remodel.equation",
    }
)
"""The five commands that write to the tree. `remodel.open` and `remodel.close` are not
among them: they make and unmake the copy, which is the fallback's own mechanism."""


def writes(bridge: FakeRemodelBridge) -> list[tuple[str, dict[str, Any]]]:
    return [call for call in bridge.calls if call[0] in WRITES]


def first_pass(
    tmp_path: Path, *, script: Script | None = None
) -> tuple[FakeRemodelBridge, Path, SourceAttestation]:
    """A run whose last folder creation raises the error count and cannot be undone."""
    source, copy, recorded = attested(tmp_path)
    assert source.exists()
    run_dir = tmp_path / RUN_ID
    bridge = FakeRemodelBridge(
        part(), script=script or Script(errors_after={4: 2}), copy_path=str(copy)
    )
    result = apply_changes(
        client=bridge,
        log=open_log(run_dir),
        changes=changes(),
        target_path=str(copy),
        baseline=0,
        limits=Limits(),
        now=StepClock(START, 0.4),
    )
    assert result.escalates_to_replay is True
    assert result.rollback_failed == (4,)
    return bridge, run_dir, recorded


def replay(
    bridge: FakeRemodelBridge, run_dir: Path, recorded: SourceAttestation
) -> ReplayResult:
    return replay_run(
        client=bridge,
        run_dir=run_dir,
        changes=changes(),
        attestation=recorded,
        run_id=RUN_ID,
        probe_id=PROBE_ID,
        baseline=0,
        limits=Limits(),
        now=StepClock(START, 0.4),
    )


# --- the fallback ------------------------------------------------------------------


def test_the_fallback_deletes_the_copy_and_re_copies_the_source(tmp_path: Path) -> None:
    bridge, run_dir, recorded = first_pass(tmp_path)
    before = len(bridge.calls)

    result = replay(bridge, run_dir, recorded)

    assert bridge.calls[before] == ("remodel.close", {"discard_copy": True})
    assert bridge.calls[before + 1] == (
        "remodel.open",
        {
            "source_path": recorded.path,
            "copy_path": recorded.copy_path,
            "run_id": RUN_ID,
            "probe_id": PROBE_ID,
        },
    )
    assert (bridge.discards, bridge.opens, bridge.copy_exists) == (1, 1, True)
    assert result.status == "replayed"


def test_only_the_changes_that_landed_are_replayed(tmp_path: Path) -> None:
    bridge, run_dir, recorded = first_pass(tmp_path)

    result = replay(bridge, run_dir, recorded)

    assert result.replayed == (1, 2, 3)
    assert result.apply.applied == (1, 2, 3)
    assert applied_changes(changes(), read_changes(changes_path(run_dir))) == changes()[:3]


def test_a_rolled_back_change_is_not_replayed(tmp_path: Path) -> None:
    """It left no mark on the tree, so replaying it would put back what the run took out."""
    # The rename regresses and its inverse takes an ordinal of its own, which is why the
    # last folder creation is the fifth mutating call here and the fourth everywhere else.
    bridge, run_dir, recorded = first_pass(tmp_path, script=Script(errors_after={1: 1, 5: 2}))

    result = replay(bridge, run_dir, recorded)

    assert result.replayed == (2, 3)
    assert result.apply.applied == (2, 3)


def test_the_replay_reproduces_the_tree_the_run_had_reached(tmp_path: Path) -> None:
    """Deterministic because every change is addressed by persistent reference, and a
    byte-for-byte re-copy carries the same references."""
    bridge, run_dir, recorded = first_pass(tmp_path)

    replay(bridge, run_dir, recorded)

    assert bridge.tree.order == [SKETCH, BOSS, FILLET, CUT]
    assert bridge.tree.names[FILLET] == "Fillet1_2"
    assert bridge.tree.folder_location == {BOSS: "3-Core", FILLET: "3-Core"}


def test_every_replayed_call_is_addressed_by_persistent_reference(tmp_path: Path) -> None:
    bridge, run_dir, recorded = first_pass(tmp_path)
    before = len(writes(bridge))

    replay(bridge, run_dir, recorded)

    replayed = writes(bridge)[before:]
    assert replayed
    for _, params in replayed:
        addressed = [key for key in params if key.startswith(("persist_ref", "member_persist"))]
        addressed += [key for key in params if key.endswith("persist_ref")]
        assert addressed, params
        assert "index" not in params
        assert "name" not in params or params["name"] in ("3-Core", "1-Ref")


def test_the_replayed_records_continue_the_append_only_log(tmp_path: Path) -> None:
    """A replayed change is a new attempt and takes the next free `seq`: the file records
    both attempts, because a line never rewrites an earlier one."""
    bridge, run_dir, recorded = first_pass(tmp_path)

    replay(bridge, run_dir, recorded)

    written = read_changes(changes_path(run_dir))
    assert [row.seq for row in written] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7]
    assert [row.kind for row in written[8:]] == [
        "rename",
        "rename",
        "reorder",
        "reorder",
        "folder.create",
        "folder.create",
    ]
    assert [row.status for row in written[8:]] == ["attempting", "applied"] * 3


# --- the refusals ------------------------------------------------------------------


def test_a_source_that_moved_refuses_the_replay_before_anything_is_deleted(
    tmp_path: Path,
) -> None:
    bridge, run_dir, recorded = first_pass(tmp_path)
    Path(recorded.path).write_bytes(CONTENT + b" and one byte more")
    before = len(bridge.calls)

    with pytest.raises(SourceChanged, match="is not what it was"):
        replay(bridge, run_dir, recorded)

    assert len(bridge.calls) == before
    assert (bridge.discards, bridge.opens, bridge.copy_exists) == (0, 0, True)


def test_a_source_that_is_gone_refuses_the_replay(tmp_path: Path) -> None:
    bridge, run_dir, recorded = first_pass(tmp_path)
    Path(recorded.path).unlink()

    with pytest.raises(SourceChanged):
        replay(bridge, run_dir, recorded)

    assert bridge.opens == 0


def test_a_replay_that_hits_the_same_failure_stops_rather_than_looping(
    tmp_path: Path,
) -> None:
    """The replayed folder creation regresses the way the one that triggered the fallback
    did. The result says so and exactly one re-copy was made: twice is where it stops."""
    bridge, run_dir, recorded = first_pass(
        tmp_path, script=Script(errors_after={4: 2, 7: 2})
    )

    result = replay(bridge, run_dir, recorded)

    assert result.status == "stopped"
    assert result.escalated_again is True
    assert result.apply.rollback_failed == (3,)
    assert result.apply.escalates_to_replay is True
    assert bridge.opens == 1
    assert bridge.discards == 1


def test_the_replayed_pass_is_under_the_same_bounds(tmp_path: Path) -> None:
    """A fallback is not a licence to run longer: the replayed pass carries the limits."""
    bridge, run_dir, recorded = first_pass(tmp_path)

    result = replay_run(
        client=bridge,
        run_dir=run_dir,
        changes=changes(),
        attestation=recorded,
        run_id=RUN_ID,
        probe_id=PROBE_ID,
        baseline=0,
        limits=Limits(max_changes=1),
        now=StepClock(START, 0.4),
    )

    assert result.status == "stopped"
    assert result.apply.status == "truncated"
    assert result.apply.not_attempted == (2, 3)
    assert result.escalated_again is False


def test_the_document_undo_member_is_never_the_mechanism_at_any_tier() -> None:
    """Tier 3 does not exist. It returns void, so a caller cannot tell whether it did
    anything, and it shares the undo stack the engineer can also touch.

    The scan is for a **call**, not for the name: the stage-1 surface names it on purpose, in
    the guard that refuses it and in the two docstrings that say no inverse produces it, and
    a scan that failed on those would be a scan nobody could keep true.
    """
    scanned = stage_1_sources()
    assert scanned

    for path in scanned:
        called = [line for line in code_lines(path) if "EditUndo2(" in line]
        assert not called, path

    guard = (
        Path(__file__).resolve().parents[3]
        / "extractor"
        / "SwReview.Extractor"
        / "Guard"
        / "RemodelGuard.cs"
    )
    assert '"EditUndo2",' in guard.read_text(encoding="utf-8")
