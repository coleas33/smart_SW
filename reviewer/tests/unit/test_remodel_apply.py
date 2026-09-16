"""The executor: the happy path, the failure paths and the three limits (T078, T080, T082).

`remodel/apply.py` is the one module that writes to a document, and every test here drives
it over `tests/support/remodel_bridge.py` - a fake seat that models the tree, the rebuild
error count and the copy, and **scripts a failure at change N**. No SOLIDWORKS, no bridge,
no provider.

What is pinned, in the order the tasks name it:

- **one bridge call per change, in the plan's fixed order** (C1 rename, C2 describe, C3
  reorder, C4 folders, C5 `equation.edit`, C6 `equation.add`), each followed by
  `ForceRebuild3(false)` and a count compared against the **run's baseline** - not against
  the reading before the change, because a part that already had errors at baseline is
  refused before the run starts and the baseline is what "worse than we found it" means;
- **the attempting and terminal pair**, two lines per change, so a crash leaves exactly one
  line naming what was in flight;
- **a change that raises the count is undone**, the undo is confirmed by a second rebuild,
  the record says `rolled_back`, and **the run continues**. An undo that itself fails says
  `rollback_failed` and ends the run with the log intact, because only that outcome leaves
  a tree nothing after it can be attributed to;
- **the three limits**, `max_changes` 250, `max_minutes` 20 and `max_rebuild_seconds` 120,
  each finalizing as `truncated` and naming what was applied and what was not. Never a
  silent partial success, and never a limit the model can read or move;
- **the run never auto-resumes.** A run folder that already carries a change log is refused,
  because a resumed run over a tree nobody re-verified is exactly the wrong risk.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from swreview.bridge.client import BridgeError
from swreview.bridge.remodel_client import (
    REORDER_LOCATIONS,
    RemodelAddressError,
    RemodelChangeError,
    RemodelContractError,
    RemodelLimitError,
    RemodelTargetError,
)
from swreview.remodel.apply import (
    BRIDGE_METHOD,
    EXPECTATIONS,
    TRUNCATING,
    ApplyResult,
    ResumeRefused,
    UnknownExpectation,
    apply_changes,
    open_log,
)
from swreview.remodel.apply_log import ApplyLog, derive_undo, read_changes
from swreview.remodel.plan import CHANGE_ORDER, ChangeSubject, Limits, PlannedChange
from tests.support.remodel_bridge import (
    COPY_PATH,
    FakeRemodelBridge,
    Script,
    StepClock,
    tree,
)

START = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)

SKETCH, BOSS, CUT, FILLET = "pr:sketch1", "pr:boss1", "pr:cut1", "pr:fillet1"


def part() -> Any:
    """Four features in tree order and one equation the run repairs."""
    return tree(
        (SKETCH, "Sketch1"),
        (BOSS, "Boss-Extrude1"),
        (CUT, "Cut-Extrude1"),
        (FILLET, "Fillet1"),
        equations=['"w" = 50'],
    )


def subject(feature_id: str, name: str, persist_ref: str | None) -> ChangeSubject:
    return ChangeSubject(feature_id=feature_id, name=name, persist_ref=persist_ref)


def changes() -> tuple[PlannedChange, ...]:
    """One change of every kind the executor applies, in the fixed C1 to C6 order.

    There is no dimension step between C1 and C2 and none after the globals: FR-030 puts
    both out of v1, and `BRIDGE_METHOD` carries no kind that could reach one.
    """
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
            kind="describe",
            subject_kind="feature",
            subject=subject("feat:0002", "Boss-Extrude1", BOSS),
            params={"persist_ref": BOSS, "text": "Mounting boss"},
            expect={"rebuild_errors_delta": 0},
        ),
        PlannedChange(
            seq=3,
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
            seq=4,
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
            seq=5,
            kind="equation.edit",
            subject_kind="equation",
            subject=None,
            params={"op": "set", "index": 0, "text": '"w" = 60', "which_configs": 1},
            expect={"equation_count_delta": 0, "rebuild_errors_delta": 0},
        ),
        PlannedChange(
            seq=6,
            kind="equation.add",
            subject_kind="equation",
            subject=None,
            params={"op": "add", "index": None, "text": '"t" = 3', "which_configs": 1},
            expect={"equation_count_delta": 1, "rebuild_errors_delta": 0},
        ),
    )


def run(
    tmp_path: Path,
    *,
    script: Script | None = None,
    planned: tuple[PlannedChange, ...] | None = None,
    limits: Limits | None = None,
    step_seconds: float = 0.31,
    baseline: int = 0,
    stop_after: int | None = None,
) -> tuple[ApplyResult, FakeRemodelBridge, Path]:
    """One executor run over one fake seat, with everything the run folder needs.

    `stop_after` is the engineer's stop, expressed the way the pane raises it: the flag goes
    up while the run is under way - here, once the seat has taken `stop_after` mutating
    calls - and the executor reads it when it reads it.
    """
    run_dir = tmp_path / "20260916-142201-bracket-remodel"
    bridge = FakeRemodelBridge(part(), baseline=baseline, script=script)
    kwargs: dict[str, Any] = {}
    if stop_after is not None:
        kwargs["stop_requested"] = lambda: bridge.mutations >= stop_after
    result = apply_changes(
        client=bridge,
        log=open_log(run_dir),
        changes=changes() if planned is None else planned,
        target_path=COPY_PATH,
        baseline=baseline,
        limits=limits or Limits(),
        now=StepClock(START, step_seconds),
        **kwargs,
    )
    return result, bridge, run_dir


def rebuilds_per_change(bridge: FakeRemodelBridge) -> list[int]:
    """How many rebuilds followed each mutating call, before the next one.

    The count and not the exact command sequence, because an equation change reads a
    snapshot either side of its write (`apply_equation_change` owns the FR-027 sequence)
    and the property under test is "one rebuild per change", not "two calls per change".
    """
    counts: list[int] = []
    for command, _ in bridge.calls:
        if command not in ("remodel.rebuild", "remodel.snapshot", "remodel.geometry"):
            counts.append(0)
        elif command == "remodel.rebuild" and counts:
            counts[-1] += 1
    return counts


def records(run_dir: Path) -> list[Any]:
    return list(read_changes(run_dir / "changes.jsonl"))


def terminal(run_dir: Path) -> dict[int, Any]:
    """The closing line of every change that reached one, by `seq`."""
    return {row.seq: row for row in records(run_dir) if row.status != "attempting"}


# --- T078 the happy path -----------------------------------------------------------


def test_one_bridge_call_per_change_in_the_plan_order(tmp_path: Path) -> None:
    result, bridge, _ = run(tmp_path)

    assert result.status == "complete"
    assert [command for command, _ in bridge.mutating_calls] == [
        "remodel.rename",
        "remodel.describe",
        "remodel.reorder",
        "remodel.folder",
        "remodel.equation",
        "remodel.equation",
    ]
    assert bridge.mutations == len(changes())


def test_every_kind_the_executor_applies_is_a_planner_kind_and_no_dimension() -> None:
    """The translation table is the plan's seven kinds and nothing else.

    `save` is absent because the copy is saved once, at the end, by the gate and not by the
    change loop, and there is no dimension kind to translate because v1 addresses none.
    """
    assert tuple(BRIDGE_METHOD) == CHANGE_ORDER
    assert not [kind for kind in BRIDGE_METHOD if "dimension" in kind]


def test_the_plan_params_are_sent_unchanged(tmp_path: Path) -> None:
    """The executor is a translator, never a second model of the operation."""
    _, bridge, _ = run(tmp_path)

    sent = [params for _, params in bridge.mutating_calls]
    assert sent == [change.params for change in changes()]


def test_a_rebuild_follows_every_change_and_is_compared_to_the_baseline(
    tmp_path: Path,
) -> None:
    result, bridge, run_dir = run(tmp_path)

    assert rebuilds_per_change(bridge) == [1] * len(changes())
    assert bridge.rebuilds == len(changes())
    assert result.applied == tuple(change.seq for change in changes())
    for row in terminal(run_dir).values():
        assert (row.rebuild_errors_before, row.rebuild_errors_after) == (0, 0)


def test_the_attempting_and_terminal_pair_is_written_around_every_call(
    tmp_path: Path,
) -> None:
    _, _, run_dir = run(tmp_path)

    written = records(run_dir)
    assert [row.status for row in written] == ["attempting", "applied"] * len(changes())
    assert [row.seq for row in written] == [
        change.seq for change in changes() for _ in range(2)
    ]
    for row in written:
        assert row.target_path == COPY_PATH
    assert [row.elapsed_ms for row in written if row.status == "attempting"] == [
        None
    ] * len(changes())


def test_the_terminal_line_carries_the_inverse_the_pure_function_derives(
    tmp_path: Path,
) -> None:
    _, _, run_dir = run(tmp_path)

    rows = terminal(run_dir)
    assert rows[1].undo == derive_undo(rows[1])
    assert rows[1].undo.params == {"persist_ref": FILLET, "new_name": "Fillet1"}
    assert rows[3].undo.params == {
        "feature_persist_ref": FILLET,
        "anchor_persist_ref": CUT,
        "location": "after",
    }
    assert rows[4].undo is None


def test_every_reorder_carries_a_location_from_the_closed_set(tmp_path: Path) -> None:
    _, bridge, _ = run(tmp_path)

    sent = [
        params["location"]
        for command, params in bridge.mutating_calls
        if command == "remodel.reorder"
    ]
    assert sent and all(location in REORDER_LOCATIONS for location in sent)


def test_the_seat_refuses_a_location_outside_the_closed_set() -> None:
    """The other end of the same agreement: the planner composes two values and the host
    accepts two, so a third cannot be composed at one end and honoured at the other."""
    bridge = FakeRemodelBridge(part())

    with pytest.raises(BridgeError, match="location='middle'"):
        bridge.reorder(
            feature_persist_ref=FILLET, anchor_persist_ref=BOSS, location="middle"
        )
    assert bridge.mutations == 0


def test_a_folder_wraps_a_contiguous_run_and_every_member_is_verified(
    tmp_path: Path,
) -> None:
    _, bridge, run_dir = run(tmp_path)

    assert bridge.tree.folder_location == {BOSS: "3-Core", FILLET: "3-Core"}
    created = terminal(run_dir)[4]
    assert created.after["name"] == "3-Core"
    assert created.after["member_persist_refs"] == [BOSS, FILLET]


def test_a_folder_that_wrapped_a_narrower_run_than_the_plan_asked_for_is_not_a_success(
    tmp_path: Path,
) -> None:
    """T078 verifies every member with `IFeatureManager.FeatureFolderLocation`, so the
    membership the host reports back is asserted and not just the name it echoed.

    A host that wrapped one feature of the two and answered with the asked-for name is a
    folder around the wrong run, and there is no inverse for a creation in v1.
    """
    script = Script(folder_members_answered={4: (FILLET,)})
    result, bridge, run_dir = run(tmp_path, script=script)

    created = terminal(run_dir)[4]
    assert (created.status, created.error_code) == ("rollback_failed", "expect_unmet")
    assert created.after["member_persist_refs"] == [FILLET]
    assert BOSS in created.error and FILLET in created.error
    assert bridge.tree.folder_location == {FILLET: "3-Core"}
    assert result.status == "aborted"
    assert result.escalates_to_replay is True


def test_a_folder_over_a_non_contiguous_run_is_refused_and_never_attempted() -> None:
    bridge = FakeRemodelBridge(part())

    with pytest.raises(RemodelContractError) as refused:
        bridge.folder(
            op="create", name="3-Core", member_persist_refs=[SKETCH, CUT], folder_persist_ref=None
        )
    assert refused.value.error_code == "folder_members_not_contiguous"
    assert bridge.tree.folder_names == {}


def test_the_equation_steps_repair_before_they_add(tmp_path: Path) -> None:
    _, bridge, run_dir = run(tmp_path)

    assert bridge.tree.equations == ['"w" = 60', '"t" = 3']
    assert terminal(run_dir)[5].before["equation_text"] == '"w" = 50'
    assert terminal(run_dir)[6].after["index"] == 1


def test_the_run_goes_to_completion_and_never_asks_for_approval(tmp_path: Path) -> None:
    """Run to completion is the owner's decision, and it is structural here: the executor
    takes no callback it could ask a human through."""
    result, _, _ = run(tmp_path)

    assert result.status == "complete"
    assert result.stop is None
    assert result.not_attempted == ()
    taken = set(inspect.signature(apply_changes).parameters)
    assert not {name for name in taken if "approv" in name or "confirm" in name}


def test_an_expectation_the_executor_cannot_assert_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    """`expect` is asserted, never assumed, so a key nothing asserts stops the run at the
    door rather than travelling as an expectation nobody checked."""
    planned = changes()
    invented = planned[0].model_copy(update={"expect": {"mass_unchanged": True}})

    with pytest.raises(UnknownExpectation, match="mass_unchanged"):
        run(tmp_path, planned=(invented, *planned[1:]))
    assert EXPECTATIONS == frozenset(
        {
            "rebuild_errors_delta",
            "folder_location",
            "equation_count_delta",
            "equation_value",
        }
    )


def test_an_unmet_expectation_is_never_believed(tmp_path: Path) -> None:
    """A folder the host reports as landing somewhere the plan did not ask for is a folder
    around the wrong run, and there is no inverse for that in v1."""
    planned = changes()
    wrong = planned[3].model_copy(
        update={"expect": {"folder_location": "4-Detail", "rebuild_errors_delta": 0}}
    )

    result, _, run_dir = run(tmp_path, planned=(*planned[:3], wrong, *planned[4:]))

    refused = terminal(run_dir)[4]
    assert (refused.status, refused.error_code) == ("rollback_failed", "expect_unmet")
    assert "4-Detail" in refused.error and "3-Core" in refused.error
    assert result.status == "aborted"
    assert result.escalates_to_replay is True


# --- T080 the failure paths ---------------------------------------------------------


def test_a_change_that_raises_the_count_is_undone_and_the_run_continues(
    tmp_path: Path,
) -> None:
    result, bridge, run_dir = run(tmp_path, script=Script(errors_after={2: 1}))

    rolled = terminal(run_dir)[2]
    assert rolled.status == "rolled_back"
    assert (rolled.rebuild_errors_before, rolled.rebuild_errors_after) == (0, 1)
    assert rolled.error_code == "rebuild_regressed"
    assert rolled.after["rollback_rebuild_errors"] == 0
    assert result.status == "complete"
    assert result.rolled_back == (2,)
    assert result.applied == (1, 3, 4, 5, 6)
    assert bridge.tree.descriptions[BOSS] == ""


def test_the_inverse_is_the_recorded_one_and_is_confirmed_by_a_second_rebuild(
    tmp_path: Path,
) -> None:
    _, bridge, run_dir = run(tmp_path, script=Script(errors_after={2: 1}))

    undo = terminal(run_dir)[2].undo
    assert undo.command == "remodel.describe"
    assert bridge.mutating_calls[2] == ("remodel.describe", undo.params)
    # change, rebuild, inverse, rebuild: the confirmation is a reading, not an assumption.
    assert bridge.commands[2:6] == (
        "remodel.describe",
        "remodel.rebuild",
        "remodel.describe",
        "remodel.rebuild",
    )


def test_an_inverse_that_fails_stops_the_run_with_the_log_intact(tmp_path: Path) -> None:
    script = Script(
        errors_after={2: 1},
        raises={3: RemodelChangeError("the seat refused the inverse", "bad_request", {})},
    )
    result, bridge, run_dir = run(tmp_path, script=script)

    stuck = terminal(run_dir)[2]
    assert stuck.status == "rollback_failed"
    assert result.status == "aborted"
    assert result.stop.reason == "rollback_failed"
    assert result.stop.seq == 2
    assert "2" in result.stop.detail
    assert result.rollback_failed == (2,)
    assert result.failed == ()
    assert result.not_attempted == (3, 4, 5, 6)
    assert bridge.mutations == 3
    # The log is intact: every line that was written is still readable and closed out.
    assert [row.status for row in records(run_dir)] == [
        "attempting",
        "applied",
        "attempting",
        "rollback_failed",
    ]


def test_an_inverse_that_does_not_restore_the_count_is_a_rollback_failure(
    tmp_path: Path,
) -> None:
    result, _, run_dir = run(tmp_path, script=Script(errors_after={2: 1, 3: 1}))

    assert terminal(run_dir)[2].status == "rollback_failed"
    assert terminal(run_dir)[2].after["rollback_rebuild_errors"] == 1
    assert result.status == "aborted"
    assert result.escalates_to_replay is False


def test_a_folder_creation_that_regresses_has_no_inverse_and_escalates_to_the_replay(
    tmp_path: Path,
) -> None:
    """Dissolving a folder needs a member the owner kept off the stage-1 allowlist, so the
    only way back from a bad creation is the catastrophic fallback."""
    result, _, run_dir = run(tmp_path, script=Script(errors_after={4: 2}))

    created = terminal(run_dir)[4]
    assert (created.status, created.undo) == ("rollback_failed", None)
    assert created.rebuild_errors_after == 2
    assert result.status == "aborted"
    assert result.stop.reason == "rollback_failed"
    assert result.escalates_to_replay is True


def test_a_target_error_aborts_immediately(tmp_path: Path) -> None:
    """`VerifyTarget` failing means the document being written is not provably the copy.
    Nothing is inverted, because an inverse would be a second write to the same unknown."""
    refusal = RemodelTargetError(
        "the open document is not this run's copy", "target_mismatch", {}
    )
    script = Script(raises={2: refusal})
    result, bridge, run_dir = run(tmp_path, script=script)

    refused = terminal(run_dir)[2]
    assert (refused.status, refused.error_code) == ("failed", "target_mismatch")
    assert refused.rebuild_errors_after == 0
    assert result.status == "aborted"
    assert result.stop.reason == "target_mismatch"
    assert bridge.mutations == 2
    assert result.not_attempted == (3, 4, 5, 6)


def test_a_persist_ref_that_stops_resolving_names_the_change_it_stopped_after(
    tmp_path: Path,
) -> None:
    """RK-13: a reference that resolved at plan time and does not now is a tree this run
    can no longer reason about. It is recorded, never retried and never searched for."""
    script = Script(
        raises={3: RemodelAddressError("no object", "persist_ref_unresolved", {})}
    )
    result, _, run_dir = run(tmp_path, script=script)

    lost = terminal(run_dir)[3]
    assert (lost.status, lost.error_code) == ("failed", "not_addressable")
    assert lost.error == "could not be addressed after change 2"
    assert result.status == "aborted"
    assert result.stop.reason == "not_addressable"


def test_an_open_circuit_aborts_and_the_call_was_never_sent(tmp_path: Path) -> None:
    result, bridge, run_dir = run(tmp_path, script=Script(circuit_open_at=3))

    unsent = terminal(run_dir)[3]
    assert (unsent.status, unsent.error_code) == ("failed", "circuit_open")
    assert result.status == "aborted"
    assert result.stop.reason == "circuit_open"
    assert bridge.tree.order == [SKETCH, BOSS, CUT, FILLET]


def test_a_change_the_seat_refused_fails_and_the_run_carries_on(tmp_path: Path) -> None:
    """`equation_unverified` is the host proving the change did **not** land, so the tree is
    where it was and the next change is safe to attempt."""
    script = Script(
        raises={5: RemodelChangeError("neither helper wrote", "equation_unverified", {})}
    )
    result, _, run_dir = run(tmp_path, script=script)

    assert terminal(run_dir)[5].status == "failed"
    assert result.status == "complete"
    assert result.failed == (5,)
    assert result.applied == (1, 2, 3, 4, 6)


def test_an_equation_that_landed_and_will_not_verify_is_taken_back_off_the_copy(
    tmp_path: Path,
) -> None:
    """`failed` means the change never landed, so a row that is on the document cannot be
    recorded as one: the write went out, its own re-read refused it, and the recorded
    inverse takes it off again."""
    planned = list(changes())
    planned[5] = planned[5].model_copy(
        update={
            "expect": {
                "equation_count_delta": 1,
                "equation_value": 999.0,
                "rebuild_errors_delta": 0,
            }
        }
    )
    result, bridge, run_dir = run(tmp_path, planned=tuple(planned))

    taken_back = terminal(run_dir)[6]
    assert (taken_back.status, taken_back.error_code) == ("rolled_back", "equation_unverified")
    assert taken_back.undo == derive_undo(taken_back)
    assert taken_back.undo.params["op"] == "delete"
    assert bridge.tree.equations == ['"w" = 60']
    assert result.status == "complete"
    assert result.rolled_back == (6,)
    assert result.failed == ()


def test_an_equation_whose_round_trip_text_disagrees_is_taken_back_off_the_copy(
    tmp_path: Path,
) -> None:
    """The repair at C5 overwrote the row before the host answered with another text. The
    inverse of an edit is another edit, so the previous text goes back in place."""
    result, bridge, run_dir = run(
        tmp_path, script=Script(equation_round_trip={5: '"w" = 41'})
    )

    taken_back = terminal(run_dir)[5]
    assert (taken_back.status, taken_back.error_code) == ("rolled_back", "equation_unverified")
    assert taken_back.undo.params == {
        "op": "set",
        "index": 0,
        "text": '"w" = 50',
        "which_configs": 1,
    }
    assert bridge.tree.equations == ['"w" = 50', '"t" = 3']
    assert result.status == "complete"
    assert result.rolled_back == (5,)


def test_a_host_that_answered_an_add_and_moved_no_count_records_no_inverse(
    tmp_path: Path,
) -> None:
    """PROBE-6 watched `Add3` answer and add nothing. The count either side of the call is
    the evidence, and a count that contradicts the call this run made is a document nothing
    after it can address: no row is claimed, no inverse is recorded, and the run stops."""
    result, bridge, run_dir = run(tmp_path, script=Script(equation_wrote_nothing=frozenset({6})))

    unaddressable = terminal(run_dir)[6]
    assert unaddressable.status == "rollback_failed"
    assert unaddressable.error_code == "equation_unverified"
    assert unaddressable.undo is None
    assert unaddressable.after == {}
    assert bridge.tree.equations == ['"w" = 60']
    assert result.status == "aborted"
    assert result.stop.reason == "rollback_failed"
    assert result.rollback_failed == (6,)


def test_a_circuit_that_opens_after_an_equation_write_leaves_the_change_in_flight(
    tmp_path: Path,
) -> None:
    """The write went out and the reading after it did not come back. Closing that line
    with `rebuild_errors_after` would record a count nobody took, so the change keeps its
    `attempting` line and the run stops - exactly as the non-equation path already does."""
    result, bridge, run_dir = run(
        tmp_path, script=Script(circuit_open_on_rebuild_after=5)
    )

    written = records(run_dir)
    assert written[-1].status == "attempting"
    assert written[-1].seq == 5
    assert 5 not in terminal(run_dir)
    assert result.in_flight == 5
    assert result.status == "aborted"
    assert result.stop.reason == "circuit_open"
    assert bridge.tree.equations == ['"w" = 60']


def test_a_description_whose_previous_text_will_not_read_is_never_recorded_as_applied(
    tmp_path: Path,
) -> None:
    """T076 refuses a `before` of `null` up front, so a feature whose description reads
    back unreadable at the seat is the plan and the document disagreeing. The write landed
    and there is nothing to put back: it is recorded as such and the run stops, rather than
    closing `applied` with `undo: null` and carrying an un-undoable edit forward."""
    unreadable = part()
    unreadable.descriptions[BOSS] = None
    run_dir = tmp_path / "20260916-142201-bracket-remodel"
    bridge = FakeRemodelBridge(unreadable, baseline=0)
    result = apply_changes(
        client=bridge,
        log=open_log(run_dir),
        changes=changes(),
        target_path=COPY_PATH,
        baseline=0,
        limits=Limits(),
        now=StepClock(START, 0.31),
    )

    described = terminal(run_dir)[2]
    assert described.status == "rollback_failed"
    assert described.error_code == "no_inverse_recorded"
    assert described.undo is None
    assert described.before == {"text": None}
    assert result.status == "aborted"
    assert result.applied == (1,)
    assert result.rollback_failed == (2,)
    assert result.not_attempted == (3, 4, 5, 6)


def test_resume_is_refused(tmp_path: Path) -> None:
    """FR-031. A run folder that already carries a change log is not continued: a resumed
    run over a tree nobody re-verified is exactly the risk the whole feature exists around."""
    _, _, run_dir = run(tmp_path, script=Script(circuit_open_at=3))

    with pytest.raises(ResumeRefused, match="changes.jsonl"):
        open_log(run_dir)


def test_a_fresh_run_folder_opens_a_log(tmp_path: Path) -> None:
    log = open_log(tmp_path / "20260916-142201-bracket-remodel")

    assert isinstance(log, ApplyLog)
    assert not log.path.exists()


# --- T082 the three limits ----------------------------------------------------------


def test_the_documented_limits_are_the_defaults() -> None:
    assert (Limits().max_changes, Limits().max_minutes, Limits().max_rebuild_seconds) == (
        250,
        20,
        120,
    )
    # The three bounds and the engineer's stop are the four reasons that finalize a run as
    # `truncated`. `stopped` is not a limit - it is the one of the four a person raises -
    # and it is here because `remodel.stop` reports the run as `truncated`
    # (`contracts/pane-remodel-messages.md`).
    assert TRUNCATING == frozenset(
        {"max_changes", "max_minutes", "max_rebuild_seconds", "stopped"}
    )


def test_max_changes_truncates_and_names_what_was_not_applied(tmp_path: Path) -> None:
    result, bridge, run_dir = run(tmp_path, limits=Limits(max_changes=2))

    assert result.status == "truncated"
    assert result.stop.reason == "max_changes"
    assert result.applied == (1, 2)
    assert result.not_attempted == (3, 4, 5, 6)
    assert bridge.mutations == 2
    assert len(terminal(run_dir)) == 2


def test_max_minutes_truncates_on_the_wall_clock(tmp_path: Path) -> None:
    result, bridge, _ = run(tmp_path, limits=Limits(max_minutes=1), step_seconds=25)

    assert result.status == "truncated"
    assert result.stop.reason == "max_minutes"
    assert result.applied == (1,)
    assert result.not_attempted == (2, 3, 4, 5, 6)
    assert bridge.mutations == 1


def test_max_rebuild_seconds_truncates_on_the_reading_the_seat_reported(
    tmp_path: Path,
) -> None:
    result, bridge, run_dir = run(tmp_path, script=Script(rebuild_ms_after={1: 121_000}))

    assert result.status == "truncated"
    assert result.stop.reason == "max_rebuild_seconds"
    assert result.applied == (1,)
    assert terminal(run_dir)[1].status == "applied"
    assert bridge.mutations == 1


def test_a_rebuild_that_never_came_back_truncates_and_leaves_the_change_in_flight(
    tmp_path: Path,
) -> None:
    """The host gave up on the rebuild, so nothing read the error count: the change is left
    with its `attempting` line and the run says so, rather than closing it out with a count
    that was never taken."""
    refusal = RemodelLimitError("the rebuild ran past its bound", "rebuild_timeout", {})
    script = Script(rebuild_raises={2: refusal})
    result, _, run_dir = run(tmp_path, script=script)

    assert result.status == "truncated"
    assert result.stop.reason == "max_rebuild_seconds"
    assert result.in_flight == 2
    assert [row.status for row in records(run_dir)][-1] == "attempting"


def test_a_truncated_run_is_never_a_silent_partial_success(tmp_path: Path) -> None:
    for limits, script in (
        (Limits(max_changes=2), None),
        (Limits(max_minutes=1), None),
        (Limits(), Script(rebuild_ms_after={1: 121_000})),
    ):
        result, _, _ = run(
            tmp_path / f"{limits.max_changes}-{limits.max_minutes}",
            limits=limits,
            script=script,
            step_seconds=25,
        )
        assert result.status == "truncated"
        assert result.stop is not None and result.stop.reason in TRUNCATING
        assert result.not_attempted
        assert len(result.applied) + len(result.not_attempted) <= len(changes())


def test_the_limits_are_neither_readable_nor_settable_by_the_model() -> None:
    """They are the executor's, and the model's surface never names them: a bound the model
    can read is a bound it can argue with."""
    root = Path(__file__).resolve().parents[3] / "reviewer" / "src" / "swreview"
    surface = [*sorted((root / "agent").rglob("*.py")), root / "remodel" / "intent.py"]
    assert surface

    for path in surface:
        text = path.read_text(encoding="utf-8")
        for name in ("max_changes", "max_minutes", "max_rebuild_seconds"):
            assert name not in text, f"{path} names {name}"


# --- T134c the engineer's stop ---------------------------------------------------------


def test_the_stop_flag_is_read_between_changes_and_truncates_the_run(
    tmp_path: Path,
) -> None:
    """A stop raised before change 3 leaves changes 1 and 2 and attempts nothing after.

    The flag goes up after the second mutating call, which is inside change 2's window, and
    change 2 still closes: the executor reads the flag between changes, so the change in
    flight is finished, recorded and only then is the run ended.
    """
    result, bridge, _ = run(tmp_path, stop_after=2)

    assert result.status == "truncated"
    assert result.stop is not None and result.stop.reason == "stopped"
    assert result.applied == (1, 2)
    assert result.not_attempted == (3, 4, 5, 6)
    assert result.in_flight is None
    assert bridge.mutations == 2


def test_a_stopped_run_leaves_the_changes_before_it_and_no_line_in_flight(
    tmp_path: Path,
) -> None:
    """N-1 changes on disk when the stop lands before change N, each one closed out."""
    _, _, run_dir = run(tmp_path, stop_after=2)

    written = records(run_dir)
    assert [row.status for row in written] == ["attempting", "applied"] * 2
    assert len(terminal(run_dir)) == 2
    assert [row.seq for row in written] == [1, 1, 2, 2]


def test_the_changes_applied_a_stopped_run_reports_are_read_from_the_folder(
    tmp_path: Path,
) -> None:
    """`remodel.stopped {changes_applied}` is answered from `changes.jsonl`, not from a
    process that may be gone: the count is the terminal `applied` lines on disk."""
    result, _, run_dir = run(tmp_path, stop_after=2)

    applied = [row.seq for row in records(run_dir) if row.status == "applied"]
    assert applied == [1, 2] == list(result.applied)


def test_a_stop_that_lands_after_the_last_change_completes_the_run(
    tmp_path: Path,
) -> None:
    """Nothing was left to do, so there is nothing to truncate and no stop to record."""
    result, _, _ = run(tmp_path, stop_after=len(changes()))

    assert result.status == "complete"
    assert result.stop is None
    assert result.applied == tuple(change.seq for change in changes())


def test_a_run_nobody_stopped_never_reads_a_stop(tmp_path: Path) -> None:
    """The default is a flag that is never up, so every existing caller is unaffected."""
    default = inspect.signature(apply_changes).parameters["stop_requested"].default
    assert default() is False

    result, _, _ = run(tmp_path)
    assert result.status == "complete"
    assert result.stop is None
