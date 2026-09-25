"""Unit tests for `RemodelPlan` and the models it holds (T024).

`data-model.md` section 1 is **normative for every field name**, so this file compares the
model's fields against that section written out here rather than against itself. A field
the section names and the model does not - or the reverse - is a defect in one of the two,
and the assertion says which way round.

The five shapes the section is most easily got wrong are asserted by name, because each of
them was a different shape in an earlier draft:

- `rebuild`, not `rebuild_list`. The rebuild list is the product of stage 1, and the
  artifact readers (`contracts/run-artifacts.md`, the report, the pane) read `rebuild`;
- `rejected_proposals`, a first-class list the **tool** writes. Returning the rejection to
  the model alone would leave FR-016 and US4 scenario 7 unsatisfiable, because nothing the
  report reads would carry it;
- `folders` is a `FolderPlan{actions, refusals}`, not a bare list of actions: a refusal is
  a folder the run cannot repair, and it is not an action;
- there is **no `revisions[]` array and no `stage` field**. The plan is one object
  rewritten in place: `plan_revision` says whether the judgement phase has run and `state`
  says where the run is, so the pane can never read a state that is no longer true;
- `state` is a single `RunState` field, on the plan, rewritten at every transition
  (section 11), so the state survives a crash and is readable from disk.

Three invariants beyond the field names are asserted here because nothing downstream would
catch them:

1. **provenance.** Every accepted `DescriptionProposal` and `GlobalProposal`, every
   `RejectedProposal` and every `PlanTarget` the model decided carries the provider and the
   exact model id (FR-056), and a planner decision carries neither: a group that came from
   the type table names no provider, and the report keeps the two apart (FR-020);
2. **addressing.** A change to a feature carries the feature's persistent reference, never
   its name and never its index, because a reorder changes both;
3. **order.** `changes[]` is in the fixed order of section 1.11 (C1 to C6) and the model
   refuses a list that is not, so the order is a property of the type rather than a comment
   at the one call site that builds it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from swreview.checks.rms_types import load_table
from swreview.remodel.feasibility import Edge, Pin, RebuildEntry
from swreview.remodel.folders import FolderAction, FolderPlan, FolderRefusal
from swreview.remodel.names import RenamePlan
from swreview.remodel.order import Move
from swreview.remodel.plan import (
    CHANGE_ORDER,
    PACKAGE_BEFORE,
    PLAN_SCHEMA,
    ChangeSubject,
    DescriptionProposal,
    Deviation,
    GlobalEvidence,
    GlobalProposal,
    Limits,
    OrderPlan,
    PlanCoverage,
    PlannedChange,
    PlanTarget,
    RejectedProposal,
    RemodelPlan,
    RunState,
    SourceAttestation,
    scope_report,
)
from swreview.remodel.rank import FeatureRank
from swreview.remodel.scope import ScopeSignals
from tests.support.remodel import scope_signals

TABLE = load_table()
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups

AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)

FIELDS: tuple[str, ...] = (
    "plan_schema",
    "plan_revision",
    "run_id",
    "created_at",
    "updated_at",
    "state",
    "source",
    "copy_path",
    "document_id",
    "configuration",
    "configuration_names",
    "package_before",
    "type_table_version",
    "type_table_calibrated_version",
    "scope",
    "targets",
    "ranks",
    "order",
    "pins",
    "rebuild",
    "folders",
    "renames",
    "descriptions",
    "globals",
    "rejected_proposals",
    "deviations",
    "changes",
    "limits",
    "coverage",
)
"""Every field of `data-model.md` section 1, in the section's own order. Written out
here so the model is compared against the document and not against itself."""

STATES: tuple[str, ...] = (
    "planned",
    "judging",
    "applying",
    "verifying",
    "saved",
    "truncated",
    "failed",
    "discarded",
)
"""`data-model.md` section 11's table, in its order."""


# --- helpers ----------------------------------------------------------------------


def signals(**overrides: Any) -> ScopeSignals:
    return ScopeSignals(**scope_signals(**overrides))


def coverage() -> tuple[PlanCoverage, ...]:
    """The one coverage item every plan carries, so `coverage` is never empty."""
    return (
        PlanCoverage(
            item="sketch dimensions",
            reason="not carried by IR 1.2.0",
            feature_ids=(),
        ),
    )


def plan(**overrides: Any) -> RemodelPlan:
    """A valid revision-1 plan: pure, no copy yet, nothing the model decided."""
    body: dict[str, Any] = {
        "plan_revision": 1,
        "created_at": AT,
        "updated_at": AT,
        "state": "planned",
        "document_id": "doc:1",
        "configuration": "Default",
        "configuration_names": ("Default",),
        "type_table_version": str(TABLE.version),
        "type_table_calibrated_version": TABLE.calibrated_version,
        "scope": scope_report(signals()),
        "order": OrderPlan(achievable=(), kept=(), edit_script=(), move_count=0, cycle=None),
        "folders": FolderPlan(actions=(), refusals=()),
        "limits": Limits(),
        "coverage": coverage(),
    }
    body.update(overrides)
    return RemodelPlan(**body)


def subject(feature_id: str = "feat:0007") -> ChangeSubject:
    return ChangeSubject(feature_id=feature_id, name="Cut-Extrude1", persist_ref="cGVyc2lzdA==")


def described(**overrides: Any) -> DescriptionProposal:
    body: dict[str, Any] = {
        "feature_id": "feat:0007",
        "before": "",
        "text": "Mounting slot",
        "source": "model",
        "rationale": "the cut carries the fastener clearance",
        "provider": "openai",
        "model": "a-model-id",
        "validation": "accepted",
    }
    body.update(overrides)
    return DescriptionProposal(**body)


def evidence(**overrides: Any) -> GlobalEvidence:
    body: dict[str, Any] = {
        "feature_id": "feat:0019",
        "parameter": "default_radius",
        "value_m": 0.003,
        "document_length_unit": "mm",
        "value_document_units": 3.0,
        "equation_text": '"corner_radius" = 3',
    }
    body.update(overrides)
    return GlobalEvidence(**body)


def proposed_global(**overrides: Any) -> GlobalProposal:
    body: dict[str, Any] = {
        "name": "corner_radius",
        "expression": "3",
        "rationale": "every outer corner uses the same radius",
        "evidence": (evidence(),),
        "provider": "openai",
        "model": "a-model-id",
        "validation": "accepted",
        "order_index": 1,
    }
    body.update(overrides)
    return GlobalProposal(**body)


def target(**overrides: Any) -> PlanTarget:
    body: dict[str, Any] = {
        "feature_id": "feat:0007",
        "name": "Cut-Extrude1",
        "type_name": "Cut",
        "feature_class": "cut",
        "current_group": None,
        "target_group": DETAIL,
        "basis": "type_table",
        "decided_by": "planner",
        "state": "resolved",
        "candidates": (),
        "rationale": None,
        "provider": None,
        "model": None,
    }
    body.update(overrides)
    return PlanTarget(**body)


def change(**overrides: Any) -> PlannedChange:
    body: dict[str, Any] = {
        "seq": 1,
        "kind": "rename",
        "subject_kind": "feature",
        "subject": subject(),
        "params": {"persist_ref": "cGVyc2lzdA==", "new_name": "Fillet1_2"},
        "expect": {"rebuild_errors_delta": 0},
    }
    body.update(overrides)
    return PlannedChange(**body)


# --- the field names are the data model's ------------------------------------------


def test_the_plan_carries_exactly_the_fields_the_data_model_names_in_its_order() -> None:
    assert tuple(RemodelPlan.model_fields) == FIELDS


def test_the_plan_names_rebuild_and_not_rebuild_list() -> None:
    assert "rebuild" in RemodelPlan.model_fields
    assert "rebuild_list" not in RemodelPlan.model_fields


def test_the_plan_has_no_revisions_array_and_no_stage_field() -> None:
    assert "revisions" not in RemodelPlan.model_fields
    assert "stage" not in RemodelPlan.model_fields


def test_folders_is_a_folder_plan_with_actions_and_refusals_not_a_bare_list() -> None:
    refusal = FolderRefusal(
        existing_folder_id="feat:0002",
        name=CORE,
        expected_member_ids=("feat:0003",),
        actual_member_ids=("feat:0004",),
        reason="rms_named_folder_wrong_members",
    )
    action = FolderAction(
        op="create",
        name=DETAIL,
        member_feature_ids=("feat:0007",),
        contiguous=True,
        existing_folder_id=None,
        status="planned",
    )
    body = plan(folders=FolderPlan(actions=(action,), refusals=(refusal,)))

    assert body.folders.actions == (action,)
    assert body.folders.refusals == (refusal,)
    assert body.folders.refused is True


def test_an_unknown_plan_schema_is_refused() -> None:
    with pytest.raises(ValidationError, match="plan_schema"):
        plan(plan_schema="1.1")


def test_the_plan_schema_defaults_to_the_one_version_this_reader_knows() -> None:
    assert plan().plan_schema == PLAN_SCHEMA == "1.0"


def test_package_before_is_the_relative_path_the_run_folder_carries() -> None:
    assert plan().package_before == PACKAGE_BEFORE == "package-before.json"


def test_the_run_state_vocabulary_is_the_eight_states_of_section_11() -> None:
    assert get_args(RunState) == STATES


def test_the_state_is_one_field_on_the_plan_and_every_state_validates() -> None:
    for state in STATES:
        assert plan(state=state).state == state


def test_a_state_the_table_does_not_carry_is_refused() -> None:
    with pytest.raises(ValidationError, match="state"):
        plan(state="finished")


# --- revision 1 is pure, revision 2 carries the judgement phase ---------------------


def test_revision_1_validates_with_nothing_the_model_decided() -> None:
    body = plan()

    assert body.plan_revision == 1
    assert body.descriptions == ()
    assert body.globals == ()
    assert body.rejected_proposals == ()
    assert [item.decided_by for item in body.targets] == []


def test_revision_2_validates_with_the_proposals_the_judgement_phase_accepted() -> None:
    body = plan(
        plan_revision=2,
        targets=(
            target(
                feature_class="unknown",
                type_name="Deform",
                target_group=QUARANTINE,
                basis="model_judgement",
                decided_by="model",
                state="resolved",
                rationale="a cosmetic deformation",
                provider="openai",
                model="a-model-id",
            ),
        ),
        descriptions=(described(),),
        globals=(proposed_global(),),
        rejected_proposals=(
            RejectedProposal(
                at=AT,
                tool="propose_global",
                arguments={"name": "PlateWidth", "expression": "50"},
                reason="global name must be lower_snake_case, 2 to 32 characters",
                rule="global.name_pattern",
                provider="openai",
                model="a-model-id",
            ),
        ),
    )

    assert body.plan_revision == 2
    assert body.descriptions[0].provider == "openai"
    assert body.globals[0].model == "a-model-id"
    assert body.rejected_proposals[0].rule == "global.name_pattern"


def test_a_revision_1_plan_may_not_carry_a_proposal_the_model_made() -> None:
    with pytest.raises(ValidationError, match="revision 1"):
        plan(descriptions=(described(),))


def test_a_revision_1_plan_may_not_carry_a_target_the_model_decided() -> None:
    with pytest.raises(ValidationError, match="revision 1"):
        plan(
            targets=(
                target(
                    decided_by="model",
                    basis="model_judgement",
                    rationale="a cosmetic deformation",
                    provider="openai",
                    model="a-model-id",
                ),
            )
        )


def test_a_revision_the_plan_does_not_know_is_refused() -> None:
    with pytest.raises(ValidationError):
        plan(plan_revision=3)


# --- provenance: who decided, and with what model ----------------------------------


def test_a_target_the_model_decided_must_name_its_provider_model_and_rationale() -> None:
    decided: dict[str, Any] = {
        "decided_by": "model",
        "basis": "model_judgement",
        "rationale": "a cosmetic deformation",
        "provider": "openai",
        "model": "a-model-id",
    }
    assert target(**decided).decided_by == "model"

    for missing in ("rationale", "provider", "model"):
        with pytest.raises(ValidationError, match="decided_by"):
            target(**{**decided, missing: None})


def test_a_target_the_planner_decided_names_no_provider_and_no_model() -> None:
    assert target().provider is None
    assert target().model is None

    with pytest.raises(ValidationError, match="decided_by"):
        target(provider="openai", model="a-model-id")


def test_a_proposal_may_not_name_a_provider_this_product_does_not_have() -> None:
    with pytest.raises(ValidationError, match="provider"):
        described(provider="a-vendor-with-no-adapter")
    with pytest.raises(ValidationError, match="provider"):
        proposed_global(provider="a-vendor-with-no-adapter")


def test_a_rejected_proposal_records_the_tool_the_arguments_the_rule_and_the_model() -> None:
    rejected = RejectedProposal(
        at=AT,
        tool="propose_description",
        arguments={"feature_id": "feat:0007", "text": "x" * 400},
        reason="a description is 1 to 200 characters",
        rule="description.length",
        provider="gemini",
        model="a-model-id",
    )

    assert rejected.tool == "propose_description"
    assert rejected.arguments == {"feature_id": "feat:0007", "text": "x" * 400}
    assert (rejected.reason, rejected.rule) == (
        "a description is 1 to 200 characters",
        "description.length",
    )
    assert (rejected.provider, rejected.model) == ("gemini", "a-model-id")


def test_a_rejected_proposal_names_one_of_the_four_tools_that_can_refuse_one() -> None:
    with pytest.raises(ValidationError, match="tool"):
        RejectedProposal(
            at=AT,
            tool="reorder_feature",
            arguments={},
            reason="...",
            rule="x",
            provider="openai",
            model="a-model-id",
        )


# --- a description with no readable previous text is refused as a change target -----


def test_a_description_proposal_whose_before_is_unreadable_is_refused() -> None:
    with pytest.raises(ValidationError, match="inverse"):
        described(before=None)


def test_a_description_proposal_whose_before_is_blank_is_accepted() -> None:
    assert described(before="").before == ""


def test_a_description_is_one_line_of_1_to_200_characters() -> None:
    with pytest.raises(ValidationError):
        described(text="")
    with pytest.raises(ValidationError):
        described(text="x" * 201)
    with pytest.raises(ValidationError, match="newline"):
        described(text="two\nlines")


# --- a global names a value and carries the evidence for it ------------------------


def test_a_global_carries_both_numbers_because_the_text_is_in_document_units() -> None:
    row = evidence()

    assert row.value_m == 0.003
    assert (row.value_document_units, row.document_length_unit) == (3.0, "mm")
    assert row.equation_text == '"corner_radius" = 3'


def test_a_global_may_only_cite_a_parameter_the_ir_carries() -> None:
    with pytest.raises(ValidationError, match="parameter"):
        evidence(parameter="D1@Sketch1")


def test_a_global_name_is_lower_snake_case() -> None:
    with pytest.raises(ValidationError):
        proposed_global(name="CornerRadius")


# --- addressing: persistent reference, never a name and never an index -------------


def test_a_change_to_a_feature_carries_that_feature_s_persistent_reference() -> None:
    assert change().subject.persist_ref == "cGVyc2lzdA=="


def test_a_change_to_a_feature_with_no_persistent_reference_is_refused() -> None:
    with pytest.raises(ValidationError, match="persist_ref"):
        change(subject=ChangeSubject(feature_id="feat:0007", name="Cut-Extrude1", persist_ref=None))


def test_a_folder_creation_carries_no_subject_because_the_folder_does_not_exist_yet() -> None:
    created = PlannedChange(
        seq=1,
        kind="folder.create",
        subject_kind="folder",
        subject=None,
        params={
            "op": "create",
            "name": CORE,
            "member_persist_refs": ["cGVyc2lzdA=="],
            "folder_persist_ref": None,
        },
        expect={"folder_location": CORE, "rebuild_errors_delta": 0},
    )

    assert created.subject is None
    assert created.params["member_persist_refs"] == ["cGVyc2lzdA=="]


def test_every_other_kind_of_change_must_carry_its_subject() -> None:
    with pytest.raises(ValidationError, match="subject"):
        change(subject=None)


def test_a_kind_and_a_subject_kind_that_disagree_are_refused() -> None:
    with pytest.raises(ValidationError, match="subject_kind"):
        change(kind="reorder", subject_kind="equation")


def test_there_is_no_dimension_subject_because_v1_addresses_no_dimension() -> None:
    with pytest.raises(ValidationError, match="subject_kind"):
        change(subject_kind="dimension")


# --- the change list is in the fixed order of section 1.11 -------------------------


def test_the_change_order_is_the_six_steps_of_section_1_11() -> None:
    assert CHANGE_ORDER == (
        "rename",
        "describe",
        "reorder",
        "folder.create",
        "folder.rename",
        "equation.edit",
        "equation.add",
    )


def ordered_changes() -> tuple[PlannedChange, ...]:
    """One change of every kind, in the order section 1.11 fixes them in."""
    return tuple(
        change(
            seq=index + 1,
            kind=kind,
            subject_kind=(
                "equation"
                if kind.startswith("equation")
                else "folder"
                if kind.startswith("folder")
                else "feature"
            ),
            subject=(
                None
                if kind in ("folder.create", "equation.add", "equation.edit")
                else subject()
            ),
        )
        for index, kind in enumerate(CHANGE_ORDER)
    )


def test_a_change_list_in_the_fixed_order_validates() -> None:
    body = plan(changes=ordered_changes())

    assert [item.kind for item in body.changes] == list(CHANGE_ORDER)


def test_a_reorder_before_a_rename_is_refused_because_a_reorder_is_name_addressed() -> None:
    first, second = ordered_changes()[0], ordered_changes()[2]
    with pytest.raises(ValidationError, match="order"):
        plan(
            changes=(
                second.model_copy(update={"seq": 1}),
                first.model_copy(update={"seq": 2}),
            )
        )


def test_a_folder_creation_before_a_reorder_is_refused() -> None:
    reorder = ordered_changes()[2]
    created = ordered_changes()[3]
    with pytest.raises(ValidationError, match="order"):
        plan(
            changes=(
                created.model_copy(update={"seq": 1}),
                reorder.model_copy(update={"seq": 2}),
            )
        )


def test_a_new_global_may_not_be_added_before_an_existing_one_is_repaired() -> None:
    edit = ordered_changes()[5]
    add = ordered_changes()[6]
    with pytest.raises(ValidationError, match="order"):
        plan(
            changes=(
                add.model_copy(update={"seq": 1}),
                edit.model_copy(update={"seq": 2}),
            )
        )


def test_the_sequence_numbers_start_at_one_and_have_no_holes() -> None:
    with pytest.raises(ValidationError, match="seq"):
        plan(changes=(change(seq=2),))
    with pytest.raises(ValidationError, match="seq"):
        plan(changes=(change(seq=1), change(seq=3, kind="describe")))


@pytest.mark.parametrize("kind", ["rename", "reorder"])
def test_one_persist_ref_is_the_subject_of_at_most_one_change_of_a_planner_kind(
    kind: str,
) -> None:
    """T142 (decision 17A): the edit script moves each feature it moves once, and the
    rename plan renames each duplicate once, so a second `reorder` or `rename` naming one
    persist ref is a planner that read one feature as two - the real dump's second listing
    of an absorbed sketch did exactly this - and the plan refuses it rather than handing the
    executor a move of a feature it already moved."""
    one = change(seq=1, kind=kind)
    with pytest.raises(ValidationError, match="persist ref"):
        plan(changes=(one, one.model_copy(update={"seq": 2})))


def test_two_changes_of_one_kind_on_two_persist_refs_validate() -> None:
    other = ChangeSubject(feature_id="feat:0008", name="Cut-Extrude2", persist_ref="b3RoZXI=")
    body = plan(
        changes=(
            change(seq=1, kind="reorder"),
            change(seq=2, kind="reorder", subject=other),
        )
    )

    assert len(body.changes) == 2


# --- the run state field, the copy and the attestation -----------------------------


def test_a_pure_plan_names_no_copy_no_run_id_and_no_attestation() -> None:
    body = plan()

    assert (body.run_id, body.copy_path, body.source) == (None, None, None)


def attestation(**overrides: Any) -> SourceAttestation:
    body: dict[str, Any] = {
        "path": r"C:\work\bracket.SLDPRT",
        "length_bytes": 482913,
        "last_write_utc": datetime(2026, 9, 14, 9, 11, 3, tzinfo=UTC),
        "sha256": "a" * 64,
        "source_design_id": "dsn:4f2a91c0d3b7",
        "recorded_at": AT,
        "rechecked_at": None,
        "matches": None,
        "vault_path": None,
        "vault_revision": None,
        "copy_path": r"C:\runs\r\copy\bracket-RMS.SLDPRT",
        "copy_sha256_after_save": None,
    }
    body.update(overrides)
    return SourceAttestation(**body)


def test_a_plan_over_a_copy_records_the_source_attestation() -> None:
    body = plan(
        run_id="20260916-142201-bracket-remodel",
        copy_path=r"C:\runs\r\copy\bracket-RMS.SLDPRT",
        source=attestation(),
    )

    assert body.source is not None
    assert body.source.sha256 == "a" * 64
    assert body.source.length_bytes == 482913
    assert body.source.matches is None


def test_an_epdm_source_records_the_vault_path_and_revision() -> None:
    body = plan(
        run_id="r",
        copy_path=r"C:\runs\r\copy\bracket-RMS.SLDPRT",
        source=attestation(vault_path=r"\\vault\Designs\bracket.SLDPRT", vault_revision="B"),
    )

    assert body.source is not None
    assert (body.source.vault_path, body.source.vault_revision) == (
        r"\\vault\Designs\bracket.SLDPRT",
        "B",
    )


def test_a_copy_path_with_no_attestation_is_refused() -> None:
    with pytest.raises(ValidationError, match="attestation"):
        plan(copy_path=r"C:\runs\r\copy\bracket-RMS.SLDPRT", run_id="r")


def test_an_attestation_with_no_copy_path_is_refused() -> None:
    with pytest.raises(ValidationError, match="attestation"):
        plan(source=attestation())


# --- the lists the plan composes are the modules' own types ------------------------


def test_the_plan_carries_the_planner_modules_types_rather_than_copies_of_them() -> None:
    rank = FeatureRank(
        feature_id="feat:0007",
        group_index=4,
        intra_rank=2,
        intra_rule_id="rms.detail.holes_last",
        original_index=7,
        rankable=True,
    )
    pin = Pin(
        feature_id="feat:0031",
        desired_index=4,
        achievable_index=12,
        blocking_edge=Edge(parent_id="feat:0012", child_id="feat:0031"),
        reason="held below its parent feat:0012",
    )
    entry = RebuildEntry(
        feature_id="feat:0044",
        name="Fillet7",
        reason="backward_reference",
        detail=f"parent feat:0061 is in {QUARANTINE}",
        blocking_edge=Edge(parent_id="feat:0061", child_id="feat:0044"),
    )
    rename = RenamePlan(feature_id="feat:0019", before_name="Fillet1", after_name="Fillet1_2")

    body = plan(
        targets=(target(),), ranks=(rank,), pins=(pin,), rebuild=(entry,), renames=(rename,)
    )

    assert body.ranks == (rank,)
    assert body.pins[0].blocking_edge.parent_id == "feat:0012"
    assert body.rebuild[0].reason == "backward_reference"
    assert body.renames[0].reason == "duplicate_name"


def test_the_order_plan_carries_the_moves_and_counts_them() -> None:
    move = Move(feature_id="feat:0042", anchor_feature_id="feat:0031", location="after")
    order = OrderPlan(
        achievable=("feat:0031", "feat:0042"),
        kept=("feat:0031",),
        edit_script=(move,),
        move_count=1,
        cycle=None,
    )

    assert plan(order=order).order.move_count == 1


def test_an_order_plan_whose_move_count_does_not_match_its_script_is_refused() -> None:
    move = Move(feature_id="feat:0042", anchor_feature_id="feat:0031", location="after")
    with pytest.raises(ValidationError, match="move_count"):
        OrderPlan(
            achievable=("feat:0031", "feat:0042"),
            kept=("feat:0031",),
            edit_script=(move,),
            move_count=2,
            cycle=None,
        )


def test_an_order_plan_that_names_a_cycle_carries_no_achievable_order() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        OrderPlan(
            achievable=("feat:0001",),
            kept=(),
            edit_script=(),
            move_count=0,
            cycle=("feat:0001", "feat:0002"),
        )


# --- scope, limits and coverage ----------------------------------------------------


def test_the_scope_report_carries_the_probe_signals_the_verdict_was_made_from() -> None:
    report = scope_report(signals(), probe_id="probe:1")

    assert report.verdict == "ok"
    assert report.signals_probe.solid_body_count == 1
    assert report.signals is None
    assert report.probe_id == "probe:1"
    assert report.refusals == ()


def test_the_scope_report_names_every_refusing_signal_not_only_the_first() -> None:
    report = scope_report(signals(solid_body_count=3, is_weldment=True))

    assert report.verdict == "refused"
    assert [refusal.code for refusal in report.refusals] == ["multibody", "weldment"]


def test_an_unread_signal_is_unresolved_and_never_a_pass() -> None:
    report = scope_report(signals(is_weldment=None))

    assert report.verdict == "unresolved"
    assert [refusal.code for refusal in report.refusals] == ["signal_unresolved"]
    assert report.refusals[0].signal == "is_weldment"


def test_the_limits_are_the_three_the_executor_enforces() -> None:
    assert (Limits().max_changes, Limits().max_minutes, Limits().max_rebuild_seconds) == (
        250,
        20,
        120,
    )


def test_a_plan_with_nothing_unresolved_says_so_rather_than_carrying_an_empty_list() -> None:
    with pytest.raises(ValidationError, match="coverage"):
        plan(coverage=())


def test_a_deviation_carries_the_sentence_the_report_prints() -> None:
    deviation = Deviation(
        kind="fillet_default_core",
        feature_id="feat:0052",
        chosen=CORE,
        rationale="the type table sends every fillet to the structural group",
        report_line="reviewed as structural; move to Quarantine if cosmetic",
    )

    assert plan(deviations=(deviation,)).deviations[0].report_line.endswith("if cosmetic")


def test_a_deviation_kind_outside_the_closed_set_is_refused() -> None:
    with pytest.raises(ValidationError, match="kind"):
        Deviation(
            kind="fillet_moved_to_quarantine",
            feature_id="feat:0052",
            chosen=QUARANTINE,
            rationale="...",
            report_line="...",
        )


# --- the artifact round-trips ------------------------------------------------------


def test_a_plan_round_trips_through_json_unchanged() -> None:
    body = plan(
        plan_revision=2,
        targets=(target(),),
        descriptions=(described(),),
        globals=(proposed_global(),),
        changes=ordered_changes(),
    )

    assert RemodelPlan.model_validate_json(body.model_dump_json()) == body


def test_a_plan_refuses_a_field_the_data_model_does_not_name() -> None:
    with pytest.raises(ValidationError):
        plan(stage="reorganize")
