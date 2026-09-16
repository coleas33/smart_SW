"""The global seeding step of the executor (T089): C6, and the FR-027 unit sequence.

`data-model.md` section 1.11 puts new globals last, at C6, "in `order_index` order, each
added after every global its expression names, each literal seeded from
`GlobalEvidence.value_document_units`", and research R3.5 adds the other half of the rule:
they are **removed in reverse order**, because deleting a lower index renumbers every
higher one.

**There is no dimension step, in either direction.** The brief carried a dimension-rename
step between C1 and C2 and a dimension-equation step after the globals; FR-030 removes
both, because the IR carries no dimensions in v1, so the planner can neither name one nor
prove what an equation on it would drive. A v1 global names a value and drives nothing.

The six steps this file follows per global are FR-027's, which are R3.6's minus its
dimension step:

1. read the justifying value in metres from the package's feature data;
2. convert it to the document's length unit;
3. seed the literal with that **exact** value;
4. assert the equation landed and evaluated;
5. rebuild;
6. re-read the equation and assert its text and value round-trip at the document's stored
   precision - `==`, not an epsilon.

Steps 4 to 6 run against `tests/support/remodel_bridge.py`, the executor's one fake seat,
which scripts a failure at change N. Everything above them is pure: a proposal in, a
`PlannedChange` out, with no seat in the signature at all.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from swreview.bridge.remodel_client import CircuitOpen, RemodelChangeError
from swreview.remodel import apply, units
from swreview.remodel.apply_log import ChangeRecord, derive_undo
from swreview.remodel.plan import (
    CHANGE_ORDER,
    ChangeSubject,
    GlobalEvidence,
    GlobalProposal,
    PlannedChange,
)
from swreview.remodel.scope import WHICH_CONFIGS_ALL, WHICH_CONFIGS_THIS
from tests.support.remodel_bridge import FakeRemodelBridge, Script, tree

MM = "mm"
ADD3 = "add3"
"""`RemodelEquationHelperPaths.Add3`: which member of the ladder wrote."""

TARGET = r"C:\runs\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT"


def evidence(value_m: float, name: str, *, unit: str = MM) -> GlobalEvidence:
    """One evidence row, composed the one way it is ever composed."""
    value = units.document_length(value_m, unit)
    return GlobalEvidence(
        feature_id="feat:0019",
        parameter="default_radius",
        value_m=value_m,
        document_length_unit=unit,
        value_document_units=value,
        equation_text=units.global_equation_text(name, value),
    )


def proposal(
    name: str,
    *,
    expression: str | None = None,
    value_m: float | None = 0.003,
    order_index: int = 0,
    unit: str = MM,
) -> GlobalProposal:
    """One accepted global. A literal one carries evidence; a derived one names others."""
    rows = () if value_m is None else (evidence(value_m, name, unit=unit),)
    return GlobalProposal(
        name=name,
        expression=expression
        if expression is not None
        else str(units.document_length(value_m or 0.0, unit)),
        rationale="the fillet radius this part repeats",
        evidence=rows,
        provider="openai",
        model="gpt-5",
        validation="accepted",
        order_index=order_index,
    )


def changes(*globals_: GlobalProposal, **kwargs: Any) -> tuple[PlannedChange, ...]:
    kwargs.setdefault("document_length_unit", MM)
    kwargs.setdefault("which_configs", WHICH_CONFIGS_THIS)
    return apply.global_changes(globals_, **kwargs)


def equation_params(bridge: FakeRemodelBridge) -> list[dict[str, Any]]:
    """The `params` of every `remodel.equation` request, in the order they were sent."""
    return [
        params for command, params in bridge.calls if command == "remodel.equation"
    ]


def value_at(bridge: FakeRemodelBridge, index: int) -> float | None:
    """One row's value as the manager would answer it."""
    rows = bridge.snapshot()["equations"]
    return next(row["value"] for row in rows if row["index"] == index)


# --- 1. what an expression names --------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("3", ()),
        ('"corner_radius"', ("corner_radius",)),
        ('"corner_radius" * 2', ("corner_radius",)),
        ('"aa" + "bb"', ("aa", "bb")),
        ('"bb" + "aa"', ("bb", "aa")),
        ('"aa" + "aa"', ("aa",)),
        ('sqr("aa") + sin(45)', ("aa",)),
    ],
)
def test_the_names_an_expression_references_are_its_quoted_ones(
    expression: str, expected: tuple[str, ...]
) -> None:
    """A quoted name is a reference to a global; the documented function set is not.

    First-appearance order and no duplicates, because this list is what the seeding order
    is built from and a name counted twice would be a dependency counted twice.
    """
    assert apply.referenced_globals(expression) == expected


def test_an_unquoted_name_is_refused_rather_than_ignored() -> None:
    """SOLIDWORKS reads a global by its quoted name. An unquoted word that is not one of
    the documented functions is a reference this step would silently drop, and dropping it
    would order an add before the global it depends on."""
    with pytest.raises(apply.EquationStepError, match="corner_radius"):
        apply.referenced_globals("corner_radius * 2")


# --- 2. the order the globals are added in ----------------------------------------


def test_new_globals_are_added_in_order_index_order() -> None:
    ordered = apply.seed_order(
        (
            proposal("cc", order_index=2),
            proposal("aa", order_index=0),
            proposal("bb", order_index=1),
        )
    )

    assert [item.name for item in ordered] == ["aa", "bb", "cc"]


def test_a_global_is_added_after_every_global_its_expression_names() -> None:
    """`order_index` is the plan's preference and the dependency is the part's rule: a
    global added before the one it reads is an equation with an undefined name in it."""
    ordered = apply.seed_order(
        (
            proposal("outer", expression='"inner" * 2', value_m=None, order_index=0),
            proposal("inner", order_index=1),
        )
    )

    assert [item.name for item in ordered] == ["inner", "outer"]


def test_order_index_still_decides_between_two_globals_neither_depends_on() -> None:
    """The dependency edge is a constraint, not a re-sort: everything it does not order
    keeps the plan's own order, so the change list is deterministic."""
    ordered = apply.seed_order(
        (
            proposal("outer", expression='"inner" + 1', value_m=None, order_index=2),
            proposal("inner", order_index=1),
            proposal("alone", order_index=0),
        )
    )

    assert [item.name for item in ordered] == ["alone", "inner", "outer"]


def test_a_cycle_among_the_proposed_globals_is_refused() -> None:
    with pytest.raises(apply.EquationStepError, match="circular"):
        apply.seed_order(
            (
                proposal("aa", expression='"bb" + 1', value_m=None, order_index=0),
                proposal("bb", expression='"aa" + 1', value_m=None, order_index=1),
            )
        )


def test_a_global_that_names_itself_is_refused() -> None:
    with pytest.raises(apply.EquationStepError, match="circular"):
        apply.seed_order(
            (proposal("aa", expression='"aa" + 1', value_m=None, order_index=0),)
        )


def test_an_expression_naming_a_global_this_plan_does_not_add_is_refused() -> None:
    """The executor adds what the plan carries. A name from outside it cannot be ordered
    against, and a global added before the name it reads exists is a broken equation."""
    with pytest.raises(apply.EquationStepError, match="thickness"):
        apply.seed_order(
            (proposal("aa", expression='"thickness" * 2', value_m=None, order_index=0),)
        )


def test_two_globals_with_the_same_name_are_refused() -> None:
    with pytest.raises(apply.EquationStepError, match="twice"):
        apply.seed_order((proposal("aa", order_index=0), proposal("aa", order_index=1)))


def test_two_globals_with_the_same_order_index_are_refused() -> None:
    """`order_index` is the application order. Two globals claiming one position leave the
    step to decide by accident, and this run's change list has to be replayable."""
    with pytest.raises(apply.EquationStepError, match="order_index"):
        apply.seed_order((proposal("aa", order_index=0), proposal("bb", order_index=0)))


def test_removing_the_adds_goes_in_reverse_order() -> None:
    """R3.5's other half: `Delete(index)` renumbers every higher index, so the inverses
    are applied newest first and each one's recorded index is still the row's own."""
    records = tuple(applied_record(seq, index) for seq, index in ((7, 0), (8, 1), (9, 2)))

    assert [record.seq for record in apply.removal_order(records)] == [9, 8, 7]


def test_only_the_adds_this_run_made_are_ever_removed() -> None:
    """A delete is only ever the inverse of an add this run made: an edit is undone by
    another edit, and a rename by a rename."""
    records = (applied_record(7, 0), edited_record(8, 3))

    assert [record.seq for record in apply.removal_order(records)] == [7]


# --- 3. the changes the step composes ----------------------------------------------


def test_each_new_global_is_one_equation_add_addressed_by_no_persist_ref() -> None:
    """An equation row is addressed by its index in the manager, which is why an
    `equation.add` carries no subject: the row does not exist when the plan is written."""
    (change,) = changes(proposal("corner_radius"))

    assert change.kind == "equation.add"
    assert change.subject_kind == "equation"
    assert change.subject is None


def test_the_params_mirror_the_bridge_command_exactly() -> None:
    """`params` is the payload, keyed as `RemodelClient.equation` names its arguments, so
    the executor is a translator and not a second model of the operation. `index` is null,
    which means append at the current count - the only position an add takes in v1."""
    (change,) = changes(proposal("corner_radius"), which_configs=WHICH_CONFIGS_ALL)

    assert change.params == {
        "op": "add",
        "index": None,
        "text": '"corner_radius" = 3',
        "which_configs": WHICH_CONFIGS_ALL,
    }


def test_the_expectation_is_one_row_added_no_new_rebuild_error_and_that_value() -> None:
    """`expect` is what must be true afterwards and is asserted, never assumed."""
    (change,) = changes(proposal("corner_radius"))

    assert change.expect == {
        "equation_count_delta": 1,
        "rebuild_errors_delta": 0,
        "equation_value": 3.0,
    }


def test_the_seq_numbers_continue_from_the_changes_already_planned() -> None:
    """C6 is last: the globals follow every rename, description, reorder, folder and
    repair, and `seq` has no holes because each one names a `ChangeRecord`."""
    composed = changes(
        proposal("aa", order_index=0), proposal("bb", order_index=1), first_seq=12
    )

    assert [change.seq for change in composed] == [12, 13]


def test_the_changes_are_composed_in_the_seeding_order() -> None:
    composed = changes(
        proposal("outer", expression='"inner" * 2', value_m=None, order_index=0),
        proposal("inner", order_index=1),
    )

    assert [change.params["text"] for change in composed] == [
        '"inner" = 3',
        '"outer" = "inner" * 2',
    ]


def test_a_derived_global_is_written_as_the_expression_the_model_proposed() -> None:
    """A global whose expression names other globals has no literal to seed: its text is
    the expression itself, and the numbers in it are already in the document's unit."""
    composed = changes(
        proposal("inner", order_index=0),
        proposal("outer", expression='"inner" * 2', value_m=None, order_index=1),
    )

    assert composed[1].params["text"] == '"outer" = "inner" * 2'


def test_a_derived_global_expects_no_particular_value() -> None:
    """There is no literal to seed, so there is no number to re-read against. The row is
    still asserted to have landed and to read back as written; inventing an expected value
    for it would be arithmetic this side never did (Principle I)."""
    composed = changes(
        proposal("inner", order_index=0),
        proposal("outer", expression='"inner" * 2', value_m=None, order_index=1),
    )

    assert "equation_value" not in composed[1].expect
    assert composed[1].expect == {"equation_count_delta": 1, "rebuild_errors_delta": 0}


def test_a_literal_globals_text_is_re_derived_from_the_metres_the_package_carries() -> None:
    """The evidence row is the audit and the metres reading is the source. The step
    re-derives the literal through the one unit module and refuses a recorded text that
    does not agree, so an evidence row edited by hand cannot become the write."""
    wrong = GlobalEvidence(
        feature_id="feat:0019",
        parameter="default_radius",
        value_m=0.003,
        document_length_unit=MM,
        value_document_units=3.0,
        equation_text='"corner_radius" = 4',
    )
    item = proposal("corner_radius").model_copy(update={"evidence": (wrong,)})

    with pytest.raises(apply.EquationStepError, match="does not agree"):
        changes(item)


def test_a_literal_global_with_no_evidence_behind_it_is_refused() -> None:
    """The value comes from a reading the package carries, never from the expression the
    model wrote: a literal with nothing behind it is a number nobody measured."""
    item = proposal("corner_radius").model_copy(update={"evidence": ()})

    with pytest.raises(apply.EquationStepError, match="evidence"):
        changes(item)


def test_a_120_mm_value_never_reaches_the_bridge_as_0_12() -> None:
    """The units trap, asserted where the write is composed rather than only where the
    text is. `"w" = 0.12` in a millimetre document is a 120 micron feature."""
    (change,) = changes(proposal("width", value_m=0.12))

    assert change.params["text"] == '"width" = 120'
    assert "0.12" not in change.params["text"]


def test_a_document_unit_the_evidence_was_not_composed_in_is_refused() -> None:
    """Both the evidence and the write name the document's unit, and they have to be the
    same unit: a plan composed in millimetres applied to an inch document is the same
    thousandfold error by another route."""
    with pytest.raises(units.DocumentUnitError, match="in"):
        changes(proposal("corner_radius"), document_length_unit="in")


def test_a_document_whose_unit_could_not_be_read_composes_no_change_at_all() -> None:
    with pytest.raises(units.DocumentUnitError, match="metres"):
        changes(proposal("corner_radius"), document_length_unit=None)


def test_an_unknown_configuration_scope_blocks_every_add_rather_than_guessing() -> None:
    """`which_configs` comes from the configuration count `remodel.open` recorded. An
    unreadable listing drives nothing, and a global added to one configuration of several
    would be invisible in the others (`contracts/bridge-remodel.md`)."""
    with pytest.raises(apply.EquationStepError, match="which_configs"):
        changes(proposal("corner_radius"), which_configs=None)


def test_no_change_this_step_composes_is_about_a_dimension() -> None:
    """FR-030, from the composition side: the only kind this step emits is `equation.add`,
    and no kind in the whole fixed order names a dimension."""
    composed = changes(proposal("aa", order_index=0), proposal("bb", order_index=1))

    assert {change.kind for change in composed} == {"equation.add"}
    assert not [kind for kind in CHANGE_ORDER if "dimension" in kind]


def test_nothing_in_this_module_names_the_dimension_interface() -> None:
    """The same claim over the file: its one member is off the stage-1 allowlist, and v1
    addresses no dimension under any spelling."""
    source = inspect.getsource(apply)

    assert "IDimension" not in source


# --- 4. steps 4 to 6, against a seat that answers ----------------------------------


def test_the_add_lands_rebuilds_and_round_trips_at_the_documents_precision() -> None:
    """The whole sequence for one global: the row landed, the count moved by one, the
    text reads back byte-identical after a rebuild and the value is `==` the seeded one.
    """
    bridge = FakeRemodelBridge(tree())
    (change,) = changes(proposal("thickness", value_m=0.00123456789))

    outcome = apply.apply_equation_change(bridge, change)

    assert outcome.index == 0
    assert outcome.count_before == 0
    assert outcome.count_after == 1
    assert outcome.round_trip_text == '"thickness" = 1.23456789'
    assert outcome.value == 1.23456789
    assert outcome.helper_path == ADD3
    assert outcome.rebuild_errors == 0


def test_the_equation_is_re_read_after_a_rebuild_and_not_before_one() -> None:
    """Step 5 is a rebuild and step 6 is a re-read, in that order: a value read before the
    rebuild is the value the manager had, not the one the document now carries."""
    bridge = FakeRemodelBridge(tree())
    (change,) = changes(proposal("corner_radius"))

    apply.apply_equation_change(bridge, change)

    assert bridge.commands == (
        "remodel.equation",
        "remodel.rebuild",
        "remodel.snapshot",
    )


def test_several_globals_reach_the_bridge_in_the_seeding_order() -> None:
    bridge = FakeRemodelBridge(tree())
    composed = changes(
        proposal("outer", expression='"inner" * 2', value_m=None, order_index=0),
        proposal("inner", order_index=1),
    )

    for change in composed:
        apply.apply_equation_change(bridge, change)

    assert [params["text"] for params in equation_params(bridge)] == [
        '"inner" = 3',
        '"outer" = "inner" * 2',
    ]
    assert bridge.tree.equations == ['"inner" = 3', '"outer" = "inner" * 2']
    assert value_at(bridge, 1) == 6.0


def test_a_value_that_reads_back_in_the_wrong_unit_fails_the_change() -> None:
    """PROBE-2 is blocking precisely here: if `get_Value` answers metres, the assertion
    fails the change rather than leaving a part a thousand times off behind it."""
    bridge = MetreValueBridge(tree())
    (change,) = changes(proposal("width", value_m=0.12))

    refused = apply.apply_equation_change(bridge, change)

    assert isinstance(refused, apply.EquationRefused)
    assert refused.error_code == "equation_unverified"
    assert "120" in refused.error
    # The row is on the document, so the refusal carries the inverse that takes it off.
    assert refused.after == {"index": 0}


def test_a_value_that_will_not_read_at_all_fails_the_change() -> None:
    """`null` is unreadable, and an equation whose value nobody can read is not evidence
    that the seeded number landed."""
    bridge = UnreadableValueBridge(tree())
    (change,) = changes(proposal("width", value_m=0.12))

    refused = apply.apply_equation_change(bridge, change)

    assert isinstance(refused, apply.EquationRefused)
    assert refused.error_code == "equation_unverified"


def test_a_row_that_does_not_read_back_as_written_fails_the_change() -> None:
    """The host's own claim is not the evidence: the re-read is. A row that came back
    different after the rebuild is a change that did not land as asked."""
    bridge = DriftingBridge(tree())
    (change,) = changes(proposal("corner_radius"))

    refused = apply.apply_equation_change(bridge, change)

    assert isinstance(refused, apply.EquationRefused)
    assert refused.error_code == "equation_unverified"


def test_an_add_the_host_reports_without_moving_the_count_fails_the_change() -> None:
    """PROBE-6 observed `Add3` answering and adding nothing. The count delta `expect`
    carries is asserted on this side too, because this side is what writes the record."""
    bridge = OverclaimingBridge(tree())
    (change,) = changes(proposal("corner_radius"))

    refused = apply.apply_equation_change(bridge, change)

    assert isinstance(refused, apply.EquationRefused)
    assert "count" in refused.error
    # The count contradicts the call, so no row is claimed and no inverse is recorded: a
    # delete at an index nothing proved is this run's would take somebody else's row.
    assert (refused.before, refused.after) == ({}, {})


def test_a_failure_scripted_at_change_n_leaves_the_earlier_globals_added() -> None:
    """The run is run-to-completion: the second global's refusal is the executor's to
    record and invert, and the first is still in the document, exactly as it was written.
    """
    bridge = FakeRemodelBridge(
        tree(),
        script=Script(
            raises={2: RemodelChangeError("neither member wrote", "equation_unverified")}
        ),
    )
    composed = changes(proposal("aa", order_index=0), proposal("bb", order_index=1))

    first = apply.apply_equation_change(bridge, composed[0])
    with pytest.raises(RemodelChangeError) as raised:
        apply.apply_equation_change(bridge, composed[1])

    assert first.index == 0
    assert raised.value.error_code == "equation_unverified"
    assert bridge.tree.equations == ['"aa" = 3']


def test_an_open_circuit_is_returned_and_not_raised() -> None:
    """The run has to record "the bridge stopped answering" against the change it was
    making rather than unwind out of the loop, so `CircuitOpen` is a value here too."""
    bridge = FakeRemodelBridge(tree(), script=Script(circuit_open_at=1))
    (change,) = changes(proposal("corner_radius"))

    outcome = apply.apply_equation_change(bridge, change)

    assert isinstance(outcome, CircuitOpen)
    assert outcome.command == "remodel.equation"
    assert bridge.tree.equations == []


# --- 5. what the record carries, and what it inverts to ----------------------------


def test_the_record_fields_carry_what_the_inverse_needs_and_nothing_else() -> None:
    bridge = FakeRemodelBridge(tree())
    (change,) = changes(proposal("corner_radius"))

    outcome = apply.apply_equation_change(bridge, change)

    assert outcome.before == {}
    assert outcome.after == {"index": 0}


def test_the_recorded_add_inverts_to_a_delete_at_the_index_it_landed_at() -> None:
    """The inverse is `derive_undo`'s, unchanged: this step feeds it the readings and
    composes no second idea of the operation."""
    bridge = FakeRemodelBridge(tree(equations=['"existing" = 10']))
    (change,) = changes(proposal("corner_radius"))

    outcome = apply.apply_equation_change(bridge, change)
    undo = derive_undo(applied_record(1, outcome.after["index"]))

    assert outcome.after == {"index": 1}
    assert undo is not None
    assert undo.params == {"op": "delete", "index": 1, "text": None, "which_configs": None}


def test_a_change_that_is_not_an_equation_never_reaches_this_step() -> None:
    """One step, one pair of kinds. A rename handed to it is a bug in the caller and is
    refused before anything is sent."""
    bridge = FakeRemodelBridge(tree(("pr:a", "Sketch1")))
    rename = PlannedChange(
        seq=1,
        kind="rename",
        subject_kind="feature",
        subject=ChangeSubject(feature_id="feat:1", name="Sketch1", persist_ref="pr:a"),
        params={"persist_ref": "pr:a", "new_name": "Sketch2"},
        expect={"rebuild_errors_delta": 0},
    )

    with pytest.raises(apply.EquationStepError, match="rename"):
        apply.apply_equation_change(bridge, rename)

    assert bridge.calls == []


# --- the seats a failure needs -----------------------------------------------------


class MetreValueBridge(FakeRemodelBridge):
    """A seat whose `get_Value` answers metres rather than the document's unit."""

    def snapshot(self) -> Any:
        reading = super().snapshot()
        for row in reading["equations"]:
            row["value"] = 0.12
        return reading


class UnreadableValueBridge(FakeRemodelBridge):
    """A seat whose `get_Value` will not read at all."""

    def snapshot(self) -> Any:
        reading = super().snapshot()
        for row in reading["equations"]:
            row["value"] = None
        return reading


class DriftingBridge(FakeRemodelBridge):
    """A seat where the row does not read back as it was written once the rebuild is done."""

    def snapshot(self) -> Any:
        self.tree.equations[0] = '"corner_radius" = 3.0000001'
        return super().snapshot()


class OverclaimingBridge(FakeRemodelBridge):
    """`Add3` answering and adding nothing, silently, which PROBE-6 observed on 2026."""

    def equation(self, **params: Any) -> Any:
        result = super().equation(**params)
        result["count_after"] = result["count_before"]
        return result


# --- records, built the way the executor's log builds them -------------------------


def applied_record(seq: int, index: int) -> ChangeRecord:
    return ChangeRecord(
        seq=seq,
        at="2026-09-16T10:00:00Z",
        kind="equation.add",
        subject=None,
        before={},
        after={"index": index},
        undo=None,
        rebuild_errors_before=0,
        rebuild_errors_after=0,
        status="applied",
        error_code=None,
        error=None,
        target_path=TARGET,
        elapsed_ms=41,
    )


def edited_record(seq: int, index: int) -> ChangeRecord:
    return ChangeRecord(
        seq=seq,
        at="2026-09-16T10:00:01Z",
        kind="equation.edit",
        subject=None,
        before={
            "index": index,
            "equation_text": '"w" = 100',
            "which_configs": WHICH_CONFIGS_THIS,
        },
        after={"index": index},
        undo=None,
        rebuild_errors_before=0,
        rebuild_errors_after=0,
        status="applied",
        error_code=None,
        error=None,
        target_path=TARGET,
        elapsed_ms=38,
    )
