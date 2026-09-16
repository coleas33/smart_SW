"""FR-029's in-place repair of an existing global (T089a), the path C5 exists for.

**Never delete a global in order to change it.** Confirmed upstream failure, recorded as
research.md R3.5: while a referenced global is missing, every equation that depends on it
enters an error state that does **not** clear when the global returns, and SOLIDWORKS then
rejects any non-constant equation for that name. So the repair is its own change kind -
`equation.edit`, `remodel.equation` with `op: "set"` - and delete-and-re-add is not a third
fallback and is not reachable from it. That claim is asserted here against a seat that
fails any `delete`: the repair succeeds anyway, and no delete was ever attempted.

The ladder itself lives on the C# side and is pinned there by `AddEquationVerifiedTests`
(T067): `get_Equation(index)` read **before** the write, `set_Equation(index, text)`, then
`SetEquationAndConfigurationOption` once, then the change fails with `equation_unverified`.
What this file pins is the executor's half: the row is read before it is overwritten and
that reading becomes the inverse, the count is asserted **unchanged**, the text is asserted
to round-trip after the rebuild, a previous text that will not read refuses the change
before anything is written, a rename-only repair carries the existing number across
untouched, and every repair is ordered at C5, before every `equation.add`, so a repair
never competes with an add for the same name.
"""

from __future__ import annotations

from typing import Any

import pytest

from swreview.bridge.remodel_client import RemodelChangeError, RemodelContractError
from swreview.remodel import apply
from swreview.remodel.apply_log import ChangeRecord, derive_undo
from swreview.remodel.plan import GlobalEvidence, GlobalProposal, PlannedChange
from swreview.remodel.scope import WHICH_CONFIGS_THIS
from tests.support.remodel_bridge import FakeRemodelBridge, FakeTree, Script, tree

EXISTING = '"plate_width" = 120'
"""The row the part already carries, in the document's own length unit."""

REPAIRED = '"plate_width" = 125'

SET_EQUATION = "set_equation"
SET_WITH_CONFIGURATION_OPTION = "set_equation_and_configuration_option"
"""`RemodelEquationHelperPaths`, as the result records which member wrote."""

TARGET = r"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT"


def repair(index: int = 0, text: str = REPAIRED, seq: int = 1) -> PlannedChange:
    (change,) = apply.repair_changes(
        (apply.GlobalRepair(index=index, text=text),),
        which_configs=WHICH_CONFIGS_THIS,
        first_seq=seq,
    )
    return change


def seat(*rows: str, unreadable: tuple[int, ...] = (), **kwargs: Any) -> FakeRemodelBridge:
    part: FakeTree = tree(equations=list(rows))
    part.unreadable_equations = unreadable
    return FakeRemodelBridge(part, **kwargs)


def equation_ops(bridge: FakeRemodelBridge) -> list[str]:
    """Every `op` this run asked for, which is how "a delete was never attempted" is
    asserted over the whole run rather than one call at a time."""
    return [
        params["op"] for command, params in bridge.calls if command == "remodel.equation"
    ]


def literal_global(name: str, order_index: int) -> GlobalProposal:
    row = GlobalEvidence(
        feature_id="feat:0019",
        parameter="default_radius",
        value_m=0.003,
        document_length_unit="mm",
        value_document_units=3.0,
        equation_text=f'"{name}" = 3',
    )
    return GlobalProposal(
        name=name,
        expression="3",
        rationale="the fillet radius this part repeats",
        evidence=(row,),
        provider="openai",
        model="gpt-5",
        validation="accepted",
        order_index=order_index,
    )


# --- 1. the change itself ----------------------------------------------------------


def test_a_repair_is_an_equation_edit_addressed_by_its_index_in_the_manager() -> None:
    """An equation row has no persistent reference; the manager addresses it by index, so
    `params` carries the index and the change carries no subject."""
    change = repair()

    assert change.kind == "equation.edit"
    assert change.subject_kind == "equation"
    assert change.subject is None
    assert change.params == {
        "op": "set",
        "index": 0,
        "text": REPAIRED,
        "which_configs": WHICH_CONFIGS_THIS,
    }


def test_the_expectation_is_that_the_count_does_not_move() -> None:
    """An in-place edit that changed the count added or removed a row as well, which is
    the delete-and-re-add this path exists to make unreachable."""
    assert repair().expect == {"equation_count_delta": 0, "rebuild_errors_delta": 0}


def test_a_repair_never_composes_a_delete() -> None:
    """The one composition rule, asserted over the params rather than over one call."""
    assert repair().params["op"] == "set"


def test_a_repair_needs_a_configuration_scope_like_every_other_equation_write() -> None:
    with pytest.raises(apply.EquationStepError, match="which_configs"):
        apply.repair_changes(
            (apply.GlobalRepair(index=0, text=REPAIRED),), which_configs=None
        )


# --- 2. read the previous text before writing --------------------------------------


def test_the_previous_text_is_read_before_the_write_and_becomes_the_inverse() -> None:
    """`derive_undo` records a reading, never a guess: the executor reads the row it is
    about to overwrite before it overwrites it."""
    bridge = seat(EXISTING)

    outcome = apply.apply_equation_change(bridge, repair())

    assert bridge.commands.index("remodel.snapshot") < bridge.commands.index(
        "remodel.equation"
    )
    assert outcome.previous_text == EXISTING
    assert outcome.before == {
        "index": 0,
        "equation_text": EXISTING,
        "which_configs": WHICH_CONFIGS_THIS,
    }


def test_the_recorded_repair_inverts_to_another_in_place_edit() -> None:
    """The inverse of an in-place edit is another in-place edit. That is why the repair is
    its own kind instead of a delete plus an add."""
    bridge = seat(EXISTING)

    outcome = apply.apply_equation_change(bridge, repair())
    undo = derive_undo(edited_record(outcome.before))

    assert undo is not None
    assert undo.command == "remodel.equation"
    assert undo.params == {
        "op": "set",
        "index": 0,
        "text": EXISTING,
        "which_configs": WHICH_CONFIGS_THIS,
    }


def test_applying_the_inverse_puts_the_original_text_back_exactly() -> None:
    bridge = seat(EXISTING)

    outcome = apply.apply_equation_change(bridge, repair())
    undo = derive_undo(edited_record(outcome.before))
    assert undo is not None
    bridge.equation(**undo.params)

    assert bridge.tree.equations == [EXISTING]
    assert equation_ops(bridge) == ["set", "set"]


def test_a_previous_text_that_will_not_read_refuses_the_change_up_front() -> None:
    """`null` is unreadable, and an edit over something unreadable has no inverse. The
    refusal happens before the write, so there is no half-made change to undo."""
    bridge = seat(EXISTING, unreadable=(0,))

    with pytest.raises(RemodelChangeError) as raised:
        apply.apply_equation_change(bridge, repair())

    assert raised.value.error_code == "equation_unverified"
    assert equation_ops(bridge) == []
    assert bridge.mutations == 0
    assert bridge.tree.equations == [EXISTING]


def test_an_index_no_equation_sits_at_refuses_the_change_up_front() -> None:
    """The plan was made against a snapshot; a row that is no longer there is a plan this
    run cannot apply, not a row to create."""
    bridge = seat(EXISTING)

    with pytest.raises(RemodelContractError):
        apply.apply_equation_change(bridge, repair(index=4))

    assert equation_ops(bridge) == []


def test_a_bridge_that_read_a_different_row_than_the_plan_did_fails_the_change() -> None:
    """The inverse has to be the text that was actually there. Two readings that disagree
    mean the run is writing over something it did not look at."""
    bridge = MisreportingBridge(tree(equations=[EXISTING]))

    refused = apply.apply_equation_change(bridge, repair())

    assert isinstance(refused, apply.EquationRefused)
    assert refused.error_code == "equation_unverified"
    # The `set` overwrote the row before the disagreement could be noticed, so the row is
    # on the document and the inverse is recorded from the text the **bridge** reported
    # having replaced. Writing the plan's reading back would write something nobody read.
    assert refused.before["equation_text"] == '"plate_width" = 999'


# --- 3. the count is unchanged and the text round-trips ----------------------------


def test_the_repair_lands_with_the_count_unchanged_and_the_text_round_tripping() -> None:
    bridge = seat('"a" = 1', EXISTING, '"b" = 2')

    outcome = apply.apply_equation_change(bridge, repair(index=1))

    assert outcome.count_before == outcome.count_after == 3
    assert outcome.round_trip_text == REPAIRED
    assert outcome.helper_path == SET_EQUATION
    assert outcome.value == 125.0
    assert bridge.tree.equations == ['"a" = 1', REPAIRED, '"b" = 2']


def test_a_repair_that_moved_the_count_is_not_a_success() -> None:
    """A set that changed the number of rows is a delete plus an add by another name, and
    it is failed here rather than recorded as an edit that landed."""
    bridge = CountMovingBridge(tree(equations=[EXISTING]))

    refused = apply.apply_equation_change(bridge, repair())

    assert isinstance(refused, apply.EquationRefused)
    assert "count" in refused.error
    assert (refused.before, refused.after) == ({}, {})


def test_a_row_that_does_not_read_back_as_written_is_not_a_success() -> None:
    """The re-read after the rebuild is the evidence, not the host's own claim."""
    bridge = DriftingBridge(tree(equations=[EXISTING]))

    refused = apply.apply_equation_change(bridge, repair())

    assert isinstance(refused, apply.EquationRefused)
    assert refused.error_code == "equation_unverified"


def test_the_second_member_of_the_ladder_is_recorded_when_it_is_what_wrote() -> None:
    """`set_Equation` first, then `SetEquationAndConfigurationOption` once: the ladder is
    the C# helper's and is pinned by `AddEquationVerifiedTests`. What the executor does
    with it is record which member wrote, so the report can say what the seat did."""
    bridge = SecondMemberBridge(tree(equations=[EXISTING]))

    outcome = apply.apply_equation_change(bridge, repair())

    assert outcome.helper_path == SET_WITH_CONFIGURATION_OPTION
    assert outcome.round_trip_text == REPAIRED


def test_a_second_failure_fails_the_change_with_equation_unverified() -> None:
    """Neither member could be proven to have written. The change fails and is inverted;
    it is never traded for a delete and an add."""
    bridge = seat(
        EXISTING,
        script=Script(
            raises={
                1: RemodelChangeError(
                    "neither set_Equation nor SetEquationAndConfigurationOption wrote",
                    "equation_unverified",
                )
            }
        ),
    )

    with pytest.raises(RemodelChangeError) as raised:
        apply.apply_equation_change(bridge, repair())

    assert raised.value.error_code == "equation_unverified"
    assert bridge.tree.equations == [EXISTING]


# --- 4. delete-and-re-add is unreachable from here ---------------------------------


def test_a_repair_succeeds_against_a_seat_that_fails_every_delete() -> None:
    """The assertion R3.5 asks for by name: nothing on this path sends a `delete`, so a
    seat that refuses every one of them cannot affect the outcome."""
    bridge = NoDeleteBridge(tree(equations=[EXISTING]))

    outcome = apply.apply_equation_change(bridge, repair())

    assert outcome.round_trip_text == REPAIRED
    assert equation_ops(bridge) == ["set"]


def test_a_failed_repair_never_falls_back_to_a_delete_either() -> None:
    """The failure path is the one a delete would be tempting on. It is not taken: the
    change fails with the global still in the document, broken but present."""
    bridge = NoDeleteBridge(
        tree(equations=[EXISTING]),
        script=Script(raises={1: RemodelChangeError("no member wrote", "equation_unverified")}),
    )

    with pytest.raises(RemodelChangeError):
        apply.apply_equation_change(bridge, repair())

    assert "delete" not in equation_ops(bridge)
    assert bridge.tree.equations == [EXISTING]


# --- 5. a rename-only repair carries the number across -----------------------------


@pytest.mark.parametrize(
    ("previous", "new_name", "expected"),
    [
        ('"w" = 120', "plate_width", '"plate_width" = 120'),
        ('"w" = 1.23456789', "thickness", '"thickness" = 1.23456789'),
        ('"w" = "a" * 2', "outer", '"outer" = "a" * 2'),
        ('"w" =  120 ', "plate_width", '"plate_width" =  120 '),
    ],
)
def test_a_rename_only_repair_carries_the_existing_text_across_unchanged(
    previous: str, new_name: str, expected: str
) -> None:
    """FR-029: **unchanged**, not recomputed. The number in the document is the number the
    part was built with, and re-deriving it from a package reading would silently move the
    part if the two ever disagreed. Even the spacing survives, because the text is carried
    and not re-composed."""
    assert apply.renamed_global_text(previous, new_name) == expected


def test_a_rename_only_repair_reaches_the_bridge_with_the_same_number() -> None:
    bridge = seat('"w" = 120')

    outcome = apply.apply_equation_change(
        bridge, repair(text=apply.renamed_global_text('"w" = 120', "plate_width"))
    )

    assert bridge.tree.equations == ['"plate_width" = 120']
    assert outcome.value == 120.0


def test_a_previous_text_with_no_right_hand_side_cannot_be_renamed() -> None:
    """There is no number to carry across, so there is nothing to rename in place."""
    with pytest.raises(apply.EquationStepError, match="right-hand side"):
        apply.renamed_global_text('"w"', "plate_width")


def test_a_rename_to_a_name_the_plan_would_refuse_is_refused_here_too() -> None:
    """One naming rule, `plan.py`'s, applied wherever a global name is written."""
    with pytest.raises(ValueError, match="name"):
        apply.renamed_global_text('"w" = 120', "PlateWidth")


# --- 6. C5 comes before C6 ---------------------------------------------------------


def test_every_repair_is_ordered_before_every_added_global() -> None:
    """C5 then C6 (`data-model.md` section 1.11), so a repair never competes with an add
    for the same name: the name the repair frees is free before the add asks for it."""
    composed = apply.equation_changes(
        repairs=(apply.GlobalRepair(index=0, text=REPAIRED),),
        globals_=(literal_global("aa", 0), literal_global("bb", 1)),
        document_length_unit="mm",
        which_configs=WHICH_CONFIGS_THIS,
    )

    assert [change.kind for change in composed] == [
        "equation.edit",
        "equation.add",
        "equation.add",
    ]
    assert [change.seq for change in composed] == [1, 2, 3]


def test_the_equation_step_continues_the_seq_numbers_the_plan_already_used() -> None:
    composed = apply.equation_changes(
        repairs=(apply.GlobalRepair(index=0, text=REPAIRED),),
        globals_=(literal_global("aa", 0),),
        document_length_unit="mm",
        which_configs=WHICH_CONFIGS_THIS,
        first_seq=9,
    )

    assert [change.seq for change in composed] == [9, 10]


def test_a_step_with_nothing_to_do_composes_no_changes() -> None:
    """An empty list is a run with no equations to write, which is a common part and not
    an error."""
    assert (
        apply.equation_changes(
            repairs=(),
            globals_=(),
            document_length_unit="mm",
            which_configs=WHICH_CONFIGS_THIS,
        )
        == ()
    )


def test_two_repairs_of_the_same_row_are_refused() -> None:
    """The second would be composed against a row the first has already rewritten, so its
    recorded `before` would be a text that is no longer there."""
    with pytest.raises(apply.EquationStepError, match="twice"):
        apply.repair_changes(
            (
                apply.GlobalRepair(index=0, text=REPAIRED),
                apply.GlobalRepair(index=0, text='"plate_width" = 130'),
            ),
            which_configs=WHICH_CONFIGS_THIS,
        )


# --- the seats a failure needs -----------------------------------------------------


class NoDeleteBridge(FakeRemodelBridge):
    """A seat that refuses every `delete`, so a repair that needed one could not pass."""

    def equation(self, **params: Any) -> Any:
        if params.get("op") == "delete":
            raise RemodelContractError(
                "this seat refuses every delete", "bad_request", params
            )
        return super().equation(**params)


class SecondMemberBridge(FakeRemodelBridge):
    """A seat where `set_Equation` did not write and the configuration-option member did."""

    def equation(self, **params: Any) -> Any:
        result = super().equation(**params)
        result["helper_path"] = SET_WITH_CONFIGURATION_OPTION
        return result


class CountMovingBridge(FakeRemodelBridge):
    """A seat whose `set` added a row as well as writing one."""

    def equation(self, **params: Any) -> Any:
        result = super().equation(**params)
        self.tree.equations.append('"stray" = 1')
        result["count_after"] = len(self.tree.equations)
        return result


class DriftingBridge(FakeRemodelBridge):
    """A seat where the row does not read back as written once the rebuild is done."""

    def snapshot(self) -> Any:
        self.tree.equations[0] = '"plate_width" = 125.0000001'
        return super().snapshot()


class MisreportingBridge(FakeRemodelBridge):
    """A seat that read a different row than the one the plan was made against."""

    def equation(self, **params: Any) -> Any:
        result = super().equation(**params)
        result["previous_text"] = '"plate_width" = 999'
        return result


# --- the record, built the way the executor's log builds it ------------------------


def edited_record(before: dict[str, Any]) -> ChangeRecord:
    return ChangeRecord(
        seq=1,
        at="2026-09-16T10:00:00Z",
        kind="equation.edit",
        subject=None,
        before=before,
        after={"index": before["index"]},
        undo=None,
        rebuild_errors_before=0,
        rebuild_errors_after=0,
        status="applied",
        error_code=None,
        error=None,
        target_path=TARGET,
        elapsed_ms=33,
    )
