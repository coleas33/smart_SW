"""The plan itself: `RemodelPlan` (T025) and `plan_reorganize` (T027).

`plan.json` is the one artifact the pane, the executor and the report all read, so
`data-model.md` section 1 is normative for every field name here and this module spells
none of its own. Two halves:

1. **the models.** `RemodelPlan` and the types only it needs (`PlanTarget`, `OrderPlan`,
   `PlannedChange`, the proposal types, `Limits`, `PlanCoverage`, `ScopeReport`,
   `SourceAttestation`). Everything else is the planner module's own type, carried across
   rather than copied: `FeatureRank` from `rank.py`, `Pin` and `RebuildEntry` from
   `feasibility.py`, `FolderPlan` from `folders.py`, `RenamePlan` from `names.py`, `Move`
   from `order.py`. A second definition of any of them is how the checker and the planner
   start to disagree;
2. **the composition.** `plan_reorganize` runs target, rank, names, order, feasibility,
   folders, intent and scope over one part document, in that order, and emits the change
   list. It reads a package and nothing else: no SOLIDWORKS, no provider, no I/O.

Three properties the models hold rather than the call sites:

- **the plan is one object rewritten in place.** There is no `revisions[]` array and no
  `stage` field; `plan_revision` says whether the judgement phase has run and `state` says
  where the run is, so the pane can never read a state that is no longer true;
- **the change list is in the fixed order of section 1.11** (C1 rename, C2 describe, C3
  reorder, C4 folders, C5 repair a global, C6 add a global). The model refuses a list that
  is not, so the order is a property of the type and not a comment beside the one function
  that builds it;
- **provenance is not optional.** A target, a description or a global the model decided
  carries the provider and the exact model id (FR-056); one the planner decided carries
  neither, so the report can keep the two apart (FR-020) rather than implying a model read
  a type table.

**Revision 1 is pure**: no description, no global, no target the model decided, and
therefore no `describe`, `equation.edit` or `equation.add` change. Those arrive with the
judgement phase, which rewrites this same object as revision 2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from swreview.agent.providers import ProviderName
from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.part import PartTree, part_tree
from swreview.checks.rms_types import RmsTypeTable, load_table
from swreview.ir.models import Document, Equation, EvidencePackage, Feature
from swreview.remodel.feasibility import NonContiguousGroup, Pin, RebuildEntry, assess
from swreview.remodel.folders import FolderPlan, plan_folders
from swreview.remodel.intent import (
    ADMISSIBLE_PARAMETERS,
    description_gaps,
    equation_inventory,
    global_candidates,
)
from swreview.remodel.names import RenamePlan, plan_renames
from swreview.remodel.order import Move, OrderResult, plan_order
from swreview.remodel.rank import FeatureRank, rank_features
from swreview.remodel.scope import Refusal, ScopeGate, ScopeSignals
from swreview.remodel.target import Basis, NotContent, Resolved, target_group

__all__ = [
    "CHANGE_ORDER",
    "ENTERED_FROM",
    "GLOBAL_NAME_PATTERN",
    "PACKAGE_BEFORE",
    "PLAN_FILE_NAME",
    "PLAN_SCHEMA",
    "UNREAD_SIGNALS",
    "ChangeKind",
    "ChangeSubject",
    "DescriptionProposal",
    "Deviation",
    "DeviationKind",
    "GlobalEvidence",
    "GlobalProposal",
    "Limits",
    "OrderPlan",
    "PlanCoverage",
    "PlanTarget",
    "PlannedChange",
    "RejectedProposal",
    "RemodelPlan",
    "RunState",
    "ScopeReport",
    "SourceAttestation",
    "TargetState",
    "non_contiguous_groups",
    "part_document_ids",
    "plan_path",
    "plan_reorganize",
    "require_runnable_plan",
    "record_state",
    "scope_report",
]

PLAN_SCHEMA = "1.0"
"""The one `plan_schema` this reader knows. A plan carrying another is rejected rather
than read part-way, exactly as the IR's major version is (Principle IV)."""

GLOBAL_NAME_PATTERN = r"^[a-z][a-z0-9_]{1,31}$"
"""The naming rule a global has to match (`contracts/tools.md`), spelled once: the model
refuses a proposal by it and `remodel/units.py` refuses to compose a text with a name it
does not match, and two spellings of it is two rules."""

PACKAGE_BEFORE = "package-before.json"
"""The run folder's dump of the copy at open, named relative to the run folder so the
plan stays valid when the folder is moved."""

_MODEL = ConfigDict(strict=True, extra="forbid", frozen=True)


class _Model(BaseModel):
    """Strict, frozen, closed: an unexpected field is a defect, not something to carry."""

    model_config = _MODEL


# --- 1. Scope and the source ------------------------------------------------------


class ScopeReport(_Model):
    """`data-model.md` section 4.2: the verdict, the signals it was made from, and both.

    `signals_probe` is read from the open source **before any copy exists**, and is the
    only reading the verdict is made from, because FR-001 requires the refusal to precede
    the copy. `signals` is the re-reading on the copy at `remodel.open` step 12 and is
    `None` on a refused run, which never got that far, and on a dry run, which opens no
    document at all.
    """

    verdict: Literal["ok", "refused", "unresolved"]
    signals_probe: ScopeSignals
    signals: ScopeSignals | None
    probe_id: str | None
    refusals: tuple[Refusal, ...]
    notes: tuple[str, ...]

    @property
    def refused(self) -> bool:
        """Whether a definite refusal fired. An unresolved signal is not one: it is a
        question nobody answered, and it stops a run without condemning the part."""
        return self.verdict == "refused"

    @property
    def message(self) -> str:
        """Every refusal in one sentence, in the gate's own order, because a message that
        names one of two reasons sends the engineer back twice (`research.md` R4.1)."""
        return "; ".join(refusal.message for refusal in self.refusals)


UNREAD_SIGNALS = ScopeSignals(
    document_type=None,
    solid_body_count=None,
    sheet_body_count=None,
    is_weldment=None,
    sheet_metal_folder_present=None,
    mesh_body_present=None,
    graphics_body_present=None,
    is_3d_interconnect=None,
    imported_file_names=None,
    configuration_names=None,
    rms_named_folders=None,
    external_reference_count=None,
    save_flag_dirty=None,
    read_only=None,
    rebuild_error_count=None,
    vault=None,
)
"""Every scope signal unread, which is what a **dry run** holds: the signals are COM
readings taken by `remodel.probe_scope` from the engineer's open document, and a package
carries none of them. The gate answers `unresolved` over this, naming each signal, which
is the honest answer - "nobody looked" is not "nothing was there" (Principle I). The one
signal a package could be made to yield, the folder listing, is deliberately not
synthesised: the gate refuses on the **presence** of a group-named folder, so deriving it
from a dump would refuse every part the method has already been applied to."""


def scope_report(
    signals: ScopeSignals,
    *,
    probe_id: str | None = None,
    signals_on_copy: ScopeSignals | None = None,
) -> ScopeReport:
    """Run the pure gate over `signals` and record the verdict as the plan carries it.

    One helper, so the plan, the host and the report reach the same verdict from the same
    readings rather than three call sites each running the gate their own way.
    """
    result = ScopeGate.evaluate(signals)
    return ScopeReport(
        verdict=result.verdict,
        signals_probe=signals,
        signals=signals_on_copy,
        probe_id=probe_id,
        refusals=result.refusals,
        notes=result.notes,
    )


class SourceAttestation(_Model):
    """`data-model.md` section 5: what the engineer's file was when the copy was made.

    Recorded before any document handle to the source could exist and re-checked at report
    time; `matches is False` is a **hard failure** of the run whatever the copy looks like.
    The re-check itself is `remodel/runner.py`'s (T086); this is the record it writes.
    """

    path: str
    length_bytes: int = Field(ge=0)
    last_write_utc: datetime
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    source_design_id: str
    recorded_at: datetime
    rechecked_at: datetime | None
    matches: bool | None
    vault_path: str | None
    vault_revision: str | None
    copy_path: str
    copy_sha256_after_save: str | None


# --- 2. What each feature should become -------------------------------------------

TargetState = Literal["resolved", "needs_judgement", "not_content", "unresolved"]
"""`data-model.md` section 1.1. `unresolved` is terminal: the feature is never moved."""

_PROVIDERS: frozenset[str] = frozenset(name.value for name in ProviderName)
"""The provider ids this product has adapters for. A proposal naming anything else is
refused at the model, so a vendor with no adapter can never be recorded as having decided
anything (FR-026, FR-056)."""


def _known_provider(value: str | None) -> str | None:
    if value is not None and value not in _PROVIDERS:
        raise ValueError(
            f"{value!r} is not a provider this product has an adapter for "
            f"({sorted(_PROVIDERS)}); a decision cannot be attributed to one it does not"
        )
    return value


class PlanTarget(_Model):
    """One feature and the group it should be in (`data-model.md` section 1.1).

    One per row of the tree, folders and end tags included, so the plan is a **partition**
    of the tree rather than a list of the rows it happened to place.
    """

    feature_id: str
    name: str
    type_name: str
    feature_class: str
    current_group: str | None
    target_group: str | None
    basis: Basis | None
    decided_by: Literal["planner", "model"]
    state: TargetState
    candidates: tuple[str, ...]
    rationale: str | None
    provider: str | None
    model: str | None

    @model_validator(mode="after")
    def _consistent(self) -> PlanTarget:
        _known_provider(self.provider)
        resolved = self.state == "resolved"
        if resolved != (self.target_group is not None):
            raise ValueError(
                f"{self.feature_id} is {self.state} with target_group "
                f"{self.target_group!r}; a group is recorded when, and only when, the "
                "state is resolved"
            )
        if resolved != (self.basis is not None):
            raise ValueError(
                f"{self.feature_id} is {self.state} with basis {self.basis!r}; the basis "
                "is the rule that chose the group, so it exists exactly when the group does"
            )
        if self.candidates and self.state != "needs_judgement":
            raise ValueError(
                f"{self.feature_id} is {self.state} and offers candidates "
                f"{list(self.candidates)}; candidates are what the judgement phase is "
                "offered, and nothing else takes them"
            )
        if self.decided_by == "model":
            missing = [
                field
                for field in ("rationale", "provider", "model")
                if getattr(self, field) is None
            ]
            if missing:
                raise ValueError(
                    f"{self.feature_id} is decided_by model but names no {missing}; "
                    "FR-056 has the report name the provider, the model and the reason "
                    "beside every judgement"
                )
        elif self.provider is not None or self.model is not None:
            raise ValueError(
                f"{self.feature_id} is decided_by planner and names provider "
                f"{self.provider!r} and model {self.model!r}; a group that came from the "
                "type table names neither, so the report keeps the two apart (FR-020)"
            )
        return self


# --- 3. The order ------------------------------------------------------------------


class OrderPlan(_Model):
    """`data-model.md` section 1.3: the legal order, what it keeps, and what it costs."""

    achievable: tuple[str, ...]
    kept: tuple[str, ...]
    edit_script: tuple[Move, ...]
    move_count: int = Field(ge=0)
    cycle: tuple[str, ...] | None

    @model_validator(mode="after")
    def _consistent(self) -> OrderPlan:
        if self.move_count != len(self.edit_script):
            raise ValueError(
                f"move_count is {self.move_count} and the edit script has "
                f"{len(self.edit_script)} moves; the headline number of the dry run is the "
                "script's length and is never recorded separately from it"
            )
        if self.cycle is not None and (self.achievable or self.edit_script):
            raise ValueError(
                f"the order names the cycle {list(self.cycle)} and still carries an "
                "achievable order; a cycle is a refusal, and there is no legal order to "
                "carry beside it"
            )
        return self


def _order_plan(result: OrderResult) -> OrderPlan:
    """`order.py`'s record as the plan carries it; `move_count` is counted once, here."""
    return OrderPlan(
        achievable=result.achievable,
        kept=result.kept,
        edit_script=result.edit_script,
        move_count=result.move_count,
        cycle=result.cycle,
    )


# --- 4. What the judgement phase proposes ------------------------------------------


class DescriptionProposal(_Model):
    """One accepted description (`data-model.md` section 1.8).

    A feature whose current description read back as `None` is **refused as a change
    target up front**: writing `""` back over something unreadable is a silent edit, so
    there is no recoverable inverse and no proposal is accepted for it.
    """

    feature_id: str
    before: str | None
    text: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    source: Literal["model"]
    rationale: str
    provider: str
    model: str
    validation: Literal["accepted"]

    @model_validator(mode="after")
    def _describable(self) -> DescriptionProposal:
        _known_provider(self.provider)
        if self.before is None:
            raise ValueError(
                f"{self.feature_id}'s description was unreadable, so it is refused as a "
                "change target: there is no recoverable inverse to write back"
            )
        if "\n" in self.text or "\r" in self.text:
            raise ValueError(
                f"{self.feature_id}'s description carries a newline; a feature description "
                "is one line"
            )
        return self


class GlobalEvidence(_Model):
    """The feature reading that justifies a global's value (`data-model.md` section 1.9).

    Both numbers are recorded because the package carries metres and the equation text
    carries the document's length unit, and the inversion of the two is the highest-risk
    single error in stage 1 (research.md R3.6).
    """

    feature_id: str
    parameter: str
    value_m: float
    document_length_unit: str
    value_document_units: float
    equation_text: str

    @model_validator(mode="after")
    def _admissible(self) -> GlobalEvidence:
        if self.parameter not in ADMISSIBLE_PARAMETERS:
            raise ValueError(
                f"{self.parameter!r} is not a parameter the IR carries "
                f"({list(ADMISSIBLE_PARAMETERS)}); in particular no dimension is, under "
                "any spelling (FR-030)"
            )
        return self


class GlobalProposal(_Model):
    """One accepted global variable (`data-model.md` section 1.9).

    **A v1 global names a value and drives nothing.** `evidence` records why the number is
    what it is; nothing in the copy is rewired to it, because the IR carries no dimensions
    (FR-030). The report says so in those words.
    """

    name: Annotated[str, StringConstraints(pattern=GLOBAL_NAME_PATTERN)]
    expression: str
    rationale: str
    evidence: tuple[GlobalEvidence, ...]
    provider: str
    model: str
    validation: Literal["accepted"]
    order_index: int = Field(ge=0)

    @model_validator(mode="after")
    def _attributed(self) -> GlobalProposal:
        _known_provider(self.provider)
        return self


class RejectedProposal(_Model):
    """A proposal the tool layer refused (`data-model.md` section 1.9.1).

    Written into the plan **and** returned to the model. Returning it to the model alone
    would leave FR-016 and US4 scenario 7 unsatisfiable, because nothing the report reads
    would carry the rejection.
    """

    at: datetime
    tool: Literal[
        "propose_description", "propose_global", "decide_fillet", "classify_unknown"
    ]
    arguments: dict[str, Any]
    reason: str
    rule: str
    provider: str
    model: str

    @model_validator(mode="after")
    def _attributed(self) -> RejectedProposal:
        _known_provider(self.provider)
        return self


DeviationKind = Literal[
    "fillet_default_core",
    "unknown_classified_by_model",
    "description_skipped",
    "global_declined",
]
"""`data-model.md` section 1.10. Closed: a choice the report must call out is one of
these four, and a fifth is a defect rather than a new sentence invented at runtime."""


class Deviation(_Model):
    """One choice the report must call out, with the sentence it prints."""

    kind: DeviationKind
    feature_id: str | None
    chosen: str
    rationale: str
    report_line: str


class PlanCoverage(_Model):
    """What the plan could not decide, so a gap is visible rather than absent."""

    item: str
    reason: str
    feature_ids: tuple[str, ...]


class Limits(_Model):
    """`data-model.md` section 1.10, enforced by the executor and never by the model."""

    max_changes: int = Field(default=250, ge=1)
    max_minutes: int = Field(default=20, ge=1)
    max_rebuild_seconds: int = Field(default=120, ge=1)


# --- 5. The executor's input -------------------------------------------------------

ChangeKind = Literal[
    "rename",
    "describe",
    "reorder",
    "folder.create",
    "folder.rename",
    "equation.edit",
    "equation.add",
]

CHANGE_ORDER: tuple[ChangeKind, ...] = get_args(ChangeKind)
"""The fixed order of `data-model.md` section 1.11, C1 to C6: rename the duplicates (the
reorder is name-addressed), describe (cheap to fail), reorder (the minimal script),
create the folders (contiguity is only true once the order is achieved, and a creation has
no in-place inverse), repair an existing global in place, then add the new ones (so a
repair never competes with an add for the same name)."""

_STEP: Mapping[ChangeKind, int] = {
    "rename": 1,
    "describe": 2,
    "reorder": 3,
    "folder.create": 4,
    "folder.rename": 4,
    "equation.edit": 5,
    "equation.add": 6,
}
"""Which of the six steps each kind belongs to. `folder.create` and `folder.rename` share
C4, so two folder changes may come in either order relative to each other."""

_SUBJECT_KIND: Mapping[ChangeKind, str] = {
    "rename": "feature",
    "describe": "feature",
    "reorder": "feature",
    "folder.create": "folder",
    "folder.rename": "folder",
    "equation.edit": "equation",
    "equation.add": "equation",
}

_SUBJECTLESS: frozenset[str] = frozenset({"folder.create", "equation.add", "equation.edit"})
"""The kinds whose subject does not exist as a resolvable object when the plan is written:
the folder a `create` makes does not exist yet, and an equation row is addressed by its
index in the manager, which is what `params` carries. Every other kind names a feature or
an existing folder and carries its persistent reference."""


class ChangeSubject(_Model):
    """What a change is about. **Addressed by persistent reference, never by name and
    never by index**: a reorder changes both. `name` is recorded for the report only."""

    feature_id: str | None
    name: str
    persist_ref: str | None


class PlannedChange(_Model):
    """One intended write (`data-model.md` section 1.11).

    `params` mirrors the bridge command's payload exactly, so the executor is a translator
    and not a second model of the operation; `expect` is what must be true afterwards and
    is asserted by the executor, never assumed.
    """

    seq: int = Field(ge=1)
    kind: ChangeKind
    subject_kind: Literal["feature", "folder", "equation"]
    subject: ChangeSubject | None
    params: dict[str, Any]
    expect: dict[str, Any]

    @model_validator(mode="after")
    def _addressable(self) -> PlannedChange:
        expected = _SUBJECT_KIND[self.kind]
        if self.subject_kind != expected:
            raise ValueError(
                f"change {self.seq} is a {self.kind} whose subject_kind is "
                f"{self.subject_kind!r}; a {self.kind} is about a {expected}"
            )
        if self.kind in _SUBJECTLESS:
            if self.subject is not None:
                raise ValueError(
                    f"change {self.seq} is a {self.kind} and carries a subject; the object "
                    "it names does not exist when the plan is written, and its params "
                    "carry what the bridge resolves instead"
                )
            return self
        if self.subject is None:
            raise ValueError(
                f"change {self.seq} is a {self.kind} and carries no subject; every change "
                "to a live object names it"
            )
        if not self.subject.persist_ref:
            raise ValueError(
                f"change {self.seq} names {self.subject.name!r} with no persist_ref; a "
                "change is addressed by persistent reference, never by a name or an index "
                "a reorder changes"
            )
        if self.subject_kind == "feature" and not self.subject.feature_id:
            raise ValueError(
                f"change {self.seq} names a feature with no feature_id; the plan and the "
                "package address one feature by one id"
            )
        return self


# --- 6. The plan -------------------------------------------------------------------

RunState = Literal[
    "planned",
    "judging",
    "applying",
    "verifying",
    "saved",
    "truncated",
    "failed",
    "discarded",
]
"""`data-model.md` section 11, in the table's order. One field on the plan, rewritten to
`plan.json` at every transition, so the state survives a crash and the pane reads it from
disk rather than from a process that may be gone."""


class RemodelPlan(_Model):
    """`plan.json` (`data-model.md` section 1), written twice and rewritten in place.

    `run_id`, `copy_path` and `source` are `None` together for a **dry run**: the planner
    is a deliverable in its own right (`plan.md` point 10) and runs over a package with no
    SOLIDWORKS, no copy and therefore nothing to attest. They are present together for a
    run that made a copy; a plan that knew the copy's path but not what it was copied from
    is one nobody could attest, so the three are refused apart.
    """

    plan_schema: Literal["1.0"] = PLAN_SCHEMA
    plan_revision: Literal[1, 2]
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    state: RunState
    source: SourceAttestation | None = None
    copy_path: str | None = None
    document_id: str
    configuration: str
    configuration_names: tuple[str, ...]
    package_before: str = PACKAGE_BEFORE
    type_table_version: str
    type_table_calibrated_version: str
    scope: ScopeReport
    targets: tuple[PlanTarget, ...] = ()
    ranks: tuple[FeatureRank, ...] = ()
    order: OrderPlan
    pins: tuple[Pin, ...] = ()
    rebuild: tuple[RebuildEntry, ...] = ()
    folders: FolderPlan
    renames: tuple[RenamePlan, ...] = ()
    descriptions: tuple[DescriptionProposal, ...] = ()
    globals: tuple[GlobalProposal, ...] = ()
    rejected_proposals: tuple[RejectedProposal, ...] = ()
    deviations: tuple[Deviation, ...] = ()
    changes: tuple[PlannedChange, ...] = ()
    limits: Limits = Limits()
    coverage: tuple[PlanCoverage, ...]

    @model_validator(mode="after")
    def _coherent(self) -> RemodelPlan:
        self._check_attestation()
        self._check_revision()
        self._check_changes()
        if not self.coverage:
            raise ValueError(
                "the plan carries no coverage item; a plan with nothing unresolved says "
                "so explicitly, because an empty list reads as 'nobody looked' "
                "(Principle VI)"
            )
        return self

    def _check_attestation(self) -> None:
        recorded = {
            "run_id": self.run_id,
            "copy_path": self.copy_path,
            "source": self.source,
        }
        present = sorted(name for name, value in recorded.items() if value is not None)
        if present and len(present) != len(recorded):
            raise ValueError(
                f"this plan records {present} and not "
                f"{sorted(set(recorded) - set(present))}; a copy and its source "
                "attestation are recorded together or not at all, because a copy nobody "
                "attested is a copy nobody can compare"
            )

    def _check_revision(self) -> None:
        if self.plan_revision != 1:
            return
        judged = [item.feature_id for item in self.targets if item.decided_by == "model"]
        if judged or self.descriptions or self.globals or self.rejected_proposals:
            raise ValueError(
                "this plan is revision 1, which is the pure planner's output, and carries "
                f"{len(self.descriptions)} description(s), {len(self.globals)} global(s), "
                f"{len(self.rejected_proposals)} rejection(s) and {len(judged)} target(s) "
                "the model decided; the judgement phase writes revision 2"
            )

    def _check_changes(self) -> None:
        for index, change in enumerate(self.changes, start=1):
            if change.seq != index:
                raise ValueError(
                    f"change {index} carries seq {change.seq}; the seq numbers start at 1 "
                    "and have no holes, because each one names the ChangeRecord written "
                    "for it"
                )
        steps = [_STEP[change.kind] for change in self.changes]
        if steps != sorted(steps):
            raise ValueError(
                f"the change list is out of order: steps {steps} against the fixed order "
                f"{list(CHANGE_ORDER)} (data-model.md section 1.11). A reorder before a "
                "rename is name-ambiguous, a folder before a reorder wraps the wrong run, "
                "and an added global before a repaired one competes for the same name"
            )


# --- 7. Composing the plan ---------------------------------------------------------

PART_KIND = "part"

_CORE_ROLE = 2
"""`3-Core`'s position in `RmsTypeTable.groups`, counted from zero exactly as
`checks/rms/part.py` counts its roles. Named once, here, because the only thing this
module needs it for is the fillet deviation below."""


def part_document_ids(
    package: EvidencePackage, document_ids: Sequence[str] | None = None
) -> tuple[str, ...]:
    """The part documents of `package`, in package order, or the named ones in the
    caller's order.

    `tools/rms_checks.part_documents` answers the same question for the graders, and it
    takes a `ToolContext`: a session, an exception store and a coverage recorder, none of
    which the planner has or should acquire. This is the same question asked of a package
    alone, which is all the dry run has.

    Raises:
        ValueError: the package carries no part document, or a named id is one the package
            does not carry or is not a part.
    """
    parts = [
        document.document_id
        for document in package.documents
        if document.kind == PART_KIND
    ]
    if not parts:
        raise ValueError(
            "this package carries no part document; the re-modeler's subject is a part "
            "opened alone (parts only, owner decision)"
        )
    if document_ids is None:
        return tuple(parts)

    kinds = {document.document_id: document.kind for document in package.documents}
    selected: list[str] = []
    for document_id in document_ids:
        if document_id not in kinds:
            raise ValueError(
                f"{document_id} is not a document of this package; its part documents are "
                f"{parts}"
            )
        if kinds[document_id] != PART_KIND:
            raise ValueError(
                f"{document_id} is a {kinds[document_id]} document; the re-modeler plans "
                f"part documents, and this package's are {parts}"
            )
        if document_id not in selected:
            selected.append(document_id)
    return tuple(selected)


def plan_reorganize(
    package: EvidencePackage,
    *,
    document_id: str | None = None,
    table: RmsTypeTable | None = None,
    signals: ScopeSignals | None = None,
    probe_id: str | None = None,
    now: datetime | None = None,
) -> RemodelPlan:
    """Plan the reorganize stage for one part document. Pure: a package in, a plan out.

    The eight modules are asked in `data-model.md`'s own order - target, rank, names,
    order, feasibility, folders, intent, scope - because each one consumes the answer
    before it: a rank needs a target, an order needs a rank, feasibility needs both orders,
    a folder needs the order the reorder will actually achieve, and the change list needs
    all of them.

    Args:
        package: the evidence package, `model_check` or `full` profile.
        document_id: which part to plan; required when the package carries more than one.
        table: the type table; the shipped one by default.
        signals: the scope readings `remodel.probe_scope` took from the engineer's open
            source. `None` is the **dry run**: no document was ever opened, so every signal
            is unread and the scope verdict is `unresolved`, naming each one.
        probe_id: the probe those readings came from; `None` for a dry run.
        now: the instant stamped on the plan; the current time by default. Passed in by the
            golden harness so a baseline is comparable across runs.

    Raises:
        ValueError: the package carries no part document, the named document is not one, or
            the document's tree was never dumped.
    """
    table = load_table() if table is None else table
    at = datetime.now(UTC) if now is None else now
    document = _document(package, document_id)
    tree = _tree(package, document, table)

    targets, resolved = _targets(tree)
    ranks = tuple(rank_features(tree.rows, resolved, table))
    names = plan_renames(tree.rows, _equations(package, document), table)
    desired = _desired(tree, ranks)
    order = _order(tree, table, desired)
    feasibility = assess(
        tree,
        target_groups={row.id: resolved.get(row.id) for row in tree.rows},
        desired=desired,
        achievable=order.achievable,
        cycle=order.cycle,
        ambiguous_names=names.blocked,
    )
    folders = _folders(tree, table, order, resolved)
    scope = scope_report(
        UNREAD_SIGNALS if signals is None else signals, probe_id=probe_id
    )

    refused = scope.refused or folders.refused or order.cycle is not None
    changes = () if refused else _changes(tree, names.renames, order, folders)
    return RemodelPlan(
        plan_revision=1,
        created_at=at,
        updated_at=at,
        state="failed" if refused else "planned",
        document_id=document.document_id,
        configuration=document.active_configuration,
        configuration_names=tuple(document.configurations),
        type_table_version=str(table.version),
        type_table_calibrated_version=table.calibrated_version,
        scope=scope,
        targets=targets,
        ranks=ranks,
        order=_order_plan(order),
        pins=feasibility.pins,
        rebuild=feasibility.rebuild,
        folders=folders,
        renames=names.renames,
        deviations=_deviations(table, targets),
        changes=changes,
        coverage=_coverage(
            tree,
            table,
            targets,
            folders,
            scope,
            changes,
            package,
            document,
            order,
            feasibility.non_contiguous,
        ),
    )


# --- 7.1 the document and its tree -------------------------------------------------


def _document(package: EvidencePackage, document_id: str | None) -> Document:
    """The one part document this plan is about, or the reason there is no such one."""
    parts = part_document_ids(package, None if document_id is None else [document_id])
    if document_id is None and len(parts) > 1:
        raise ValueError(
            f"this package carries {len(parts)} part documents {list(parts)}; a plan is "
            "about one part, so name the one to plan"
        )
    selected = parts[0]
    return next(
        document for document in package.documents if document.document_id == selected
    )


def _tree(package: EvidencePackage, document: Document, table: RmsTypeTable) -> PartTree:
    """The document's tree, indexed as every feature 003 rule reads it."""
    rows = [row for row in package.features if row.document_id == document.document_id]
    if not rows:
        raise ValueError(
            f"{document.document_id} ({document.file_name}) carries no features rows, so "
            f"its tree was never dumped; the extractor profile was "
            f"{package.extractor.profile!r}, and the planner needs a model_check or a full "
            "dump. An empty tree is 'we never looked', not 'nothing to reorganize'"
        )
    return part_tree(document.document_id, rows, table, assign_groups(rows, table), package)


def _equations(package: EvidencePackage, document: Document) -> list[Equation]:
    """This document's equation rows."""
    return [row for row in package.equations if row.document_id == document.document_id]


# --- 7.2 target, rank and the desired order ----------------------------------------


def _targets(tree: PartTree) -> tuple[tuple[PlanTarget, ...], dict[str, str]]:
    """One `PlanTarget` per row, and the resolved targets keyed by id.

    Every row gets one, folders and end tags included, so the plan is a partition of the
    tree rather than a list of the rows it managed to place. A `NeedsJudgement` whose
    `candidates` are empty is **unresolved**, not a question: nobody is offered a choice,
    and the feature is never moved (`target.py`).
    """
    current = tree.assignment.by_feature_id
    targets: list[PlanTarget] = []
    resolved: dict[str, str] = {}
    for row in tree.rows:
        decision = target_group(row, tree.rows, tree.table)
        group: str | None = None
        basis: Basis | None = None
        candidates: tuple[str, ...] = ()
        if isinstance(decision, Resolved):
            state: TargetState = "resolved"
            group, basis = decision.group, decision.basis
            resolved[row.id] = decision.group
        elif isinstance(decision, NotContent):
            state = "not_content"
        else:
            candidates = decision.candidates
            state = "needs_judgement" if candidates else "unresolved"
        targets.append(
            PlanTarget(
                feature_id=row.id,
                name=row.name,
                type_name=row.type_name,
                feature_class=tree.table.classify(row.type_name),
                current_group=current.get(row.id),
                target_group=group,
                basis=basis,
                decided_by="planner",
                state=state,
                candidates=candidates,
                rationale=None,
                provider=None,
                model=None,
            )
        )
    return tuple(targets), resolved


def _desired(tree: PartTree, ranks: Sequence[FeatureRank]) -> tuple[str, ...]:
    """The order the method wants, with everything it cannot place left where it is.

    The ranked features are permuted among the slots they already occupy; a feature with no
    resolved target, and a fillet whose radius could not be read, keeps its exact current
    position. That is what `order.py` asks of a caller - what you must not move, you keep
    in place by giving it its current position - and it makes "a feature the planner could
    not place is never moved" a property of the construction rather than a later check.
    """
    key = {rank.feature_id: rank.sort_key for rank in ranks if rank.rankable}
    content = [row.id for row in tree.content]
    slots = [index for index, feature_id in enumerate(content) if feature_id in key]
    placed = sorted((row for row in content if row in key), key=lambda row: key[row])
    desired = list(content)
    for slot, feature_id in zip(slots, placed, strict=True):
        desired[slot] = feature_id
    return tuple(desired)


def _order(tree: PartTree, table: RmsTypeTable, desired: Sequence[str]) -> OrderResult:
    """Kahn plus LIS over every feature row, with every readable edge kept.

    A row the rules do not hold to the method - a reference plane, an origin, a tolerated
    system row - is **not** moved, but it still occupies a tree position and it is still a
    real `GetParents` parent, and `IModelDocExtension.ReorderFeature` cannot lift a feature
    past its own parent. So those rows go into the order as `immovable`, holding their
    current positions, rather than being dropped with their edges: dropping the edge is how
    a planner decides to put a sketch above the plane it is drawn on and reports nothing.

    The folders and the end-tag markers are the rows that stay out. They are organisational
    and never a `parent_ids` parent, the six group folders are created after the reorder
    (C3 then C4), and an existing group folder is already either correct or a refusal - so
    there is no edge to honour and nothing to hold in place.

    The result is projected back onto the content features, because that is what the rest
    of the plan means by an order: the achievable order and the kept set are the content
    rows of the full order, in it. The edit script needs no projection - an immovable row is
    always kept, so no `Move` names one as its subject - but a move may *anchor* to one,
    which is exactly how a feature lands after the plane it is built on.
    """
    sequence = [
        row for row in tree.rows if not table.is_folder(row) and not table.is_end_tag(row)
    ]
    inside = {row.id for row in sequence}
    result = plan_order(
        [row.id for row in sequence],
        {
            row.id: [parent for parent in (row.parent_ids or ()) if parent in inside]
            for row in sequence
        },
        _full_rank(sequence, table, desired),
        immovable=[row.id for row in sequence if not table.is_content(row)],
    )
    content = {row.id for row in tree.content}
    return OrderResult(
        achievable=tuple(one for one in result.achievable if one in content),
        kept=tuple(one for one in result.kept if one in content),
        edit_script=result.edit_script,
        cycle=result.cycle,
    )


def _full_rank(
    sequence: Sequence[Feature], table: RmsTypeTable, desired: Sequence[str]
) -> dict[str, int]:
    """The desired position of every row of `sequence`, in that sequence's own index space.

    A row the method does not grade wants the position it already has; a content feature
    wants the slot `desired` gives it, and the slots are the positions the content features
    occupy now. So the ranks are one permutation of `range(len(sequence))` and the order
    Kahn aims at is the whole tree as the method would have it, not the content half of it.
    """
    rank = {
        row.id: index
        for index, row in enumerate(sequence)
        if not table.is_content(row)
    }
    slots = [index for index, row in enumerate(sequence) if table.is_content(row)]
    rank.update(zip(desired, slots, strict=True))
    return rank


def _folders(
    tree: PartTree, table: RmsTypeTable, order: OrderResult, resolved: Mapping[str, str]
) -> FolderPlan:
    """The folder plan over the order the reorder will actually achieve.

    A refused order has no achievable order and therefore no run to wrap: the folder plan
    is empty and the refusal is the cycle, not a folder.
    """
    if order.cycle is not None:
        return FolderPlan(actions=(), refusals=())
    return plan_folders(
        tree.rows, table, order=order.achievable, target_group_by_id=dict(resolved)
    )


# --- 7.3 the change list -----------------------------------------------------------


def _subject(row: Feature) -> ChangeSubject:
    """A live object the bridge resolves by persistent reference; `name` is for the report."""
    return ChangeSubject(feature_id=row.id, name=row.name, persist_ref=row.persist_ref)


def _changes(
    tree: PartTree,
    renames: Sequence[RenamePlan],
    order: OrderResult,
    folders: FolderPlan,
) -> tuple[PlannedChange, ...]:
    """The executor's input, in the fixed order of `data-model.md` section 1.11.

    Revision 1 emits C1 (rename), C3 (reorder) and C4 (folders) and nothing else: C2, C5
    and C6 are descriptions and equations, which only the judgement phase proposes. The
    order of what is here is the order of the six steps, and `RemodelPlan` refuses a list
    that is not in it, so this function cannot quietly emit one that is not.
    """
    rows = tree.by_id
    changes: list[PlannedChange] = []

    for rename in renames:
        row = rows[rename.feature_id]
        changes.append(
            PlannedChange(
                seq=len(changes) + 1,
                kind="rename",
                subject_kind="feature",
                subject=_subject(row),
                params={"persist_ref": row.persist_ref, "new_name": rename.after_name},
                expect={"rebuild_errors_delta": 0},
            )
        )

    for move in order.edit_script:
        row = rows[move.feature_id]
        anchor = rows[move.anchor_feature_id]
        changes.append(
            PlannedChange(
                seq=len(changes) + 1,
                kind="reorder",
                subject_kind="feature",
                subject=_subject(row),
                params={
                    "feature_persist_ref": row.persist_ref,
                    "anchor_persist_ref": anchor.persist_ref,
                    "location": move.location,
                },
                expect={"rebuild_errors_delta": 0},
            )
        )

    for action in folders.actions:
        if action.status != "planned":
            continue
        existing = (
            None
            if action.existing_folder_id is None
            else rows[action.existing_folder_id]
        )
        create = action.op == "create"
        if not create and existing is None:
            raise ValueError(
                f"the folder plan renames {action.name} without naming the folder to "
                "rename; a rename is addressed by the existing folder's persistent "
                "reference, never by the name it currently carries"
            )
        changes.append(
            PlannedChange(
                seq=len(changes) + 1,
                kind="folder.create" if create else "folder.rename",
                subject_kind="folder",
                subject=None if create else _subject(existing),
                params={
                    "op": action.op,
                    "name": action.name,
                    "member_persist_refs": [
                        rows[member].persist_ref for member in action.member_feature_ids
                    ],
                    "folder_persist_ref": None if existing is None else existing.persist_ref,
                },
                expect={"folder_location": action.name, "rebuild_errors_delta": 0},
            )
        )
    return tuple(changes)


# --- 7.4 what the report must call out ---------------------------------------------


def _deviations(
    table: RmsTypeTable, targets: Sequence[PlanTarget]
) -> tuple[Deviation, ...]:
    """Every fillet the table defaulted into the structural group (`data-model.md` 1.10).

    The table sends every fillet to `3-Core` because that is the safe default: moving a
    structural fillet to Quarantine is a modelling change, and only the judgement phase may
    propose it (OQ-4). Safe is not the same as right, so each one is a deviation the report
    prints rather than a silent choice.
    """
    core = table.groups[_CORE_ROLE]
    return tuple(
        Deviation(
            kind="fillet_default_core",
            feature_id=item.feature_id,
            chosen=core,
            rationale=(
                f"{item.name} is a fillet and the type table sends every fillet to {core}; "
                "no judgement phase has run, so nothing has looked at whether it is "
                "structural or cosmetic"
            ),
            report_line="reviewed as structural; move to Quarantine if cosmetic",
        )
        for item in targets
        if item.feature_class == "fillet"
        and item.target_group == core
        and item.basis == "type_table"
    )


def _coverage(
    tree: PartTree,
    table: RmsTypeTable,
    targets: Sequence[PlanTarget],
    folders: FolderPlan,
    scope: ScopeReport,
    changes: Sequence[PlannedChange],
    package: EvidencePackage,
    document: Document,
    order: OrderResult,
    non_contiguous: Sequence[NonContiguousGroup] = (),
) -> tuple[PlanCoverage, ...]:
    """What this plan did not decide, one item per question, always all of them.

    Every item is written on every run, including the ones with nothing in them: "no
    description is missing" is an answer and "the description question was never asked" is
    a different one, and a list that carried only the non-empty items could not tell them
    apart (Principle VI).

    One further item is written **per group that cannot be folded**, and its `item` is the
    group's own name. That is what `non_contiguous_groups` reads them back by: a coverage
    item naming one of the six groups is a group no folder can wrap, and its `feature_ids`
    are the interlopers that split it. `data-model.md` section 1 has no field for this -
    the rebuild list carries the features, one entry each with reason `splits_group` - and
    a group is not a feature, so the gap belongs in coverage rather than in a ninth
    rebuild reason.
    """
    gaps = description_gaps(tree.rows, table)
    inventory = equation_inventory(_equations(package, document))
    candidates = global_candidates(tree.rows, table)
    undecided = [
        item.feature_id
        for item in targets
        if item.state in ("needs_judgement", "unresolved")
    ]
    unreadable = [gap.feature_id for gap in gaps if gap.kind == "unreadable"]
    planned = [action for action in folders.actions if action.status == "planned"]
    correct = [action for action in folders.actions if action.status == "no_op"]

    return (
        PlanCoverage(
            item="scope",
            reason=(
                scope.message
                if scope.refusals
                else "every scope signal was read and none of them refuses this part"
            ),
            feature_ids=(),
        ),
        PlanCoverage(
            item="target group",
            reason=(
                f"{len(undecided)} of {len(tree.content)} content feature(s) have no target "
                "group; the judgement phase has not run, and an undecided feature is never "
                "moved"
            ),
            feature_ids=tuple(undecided),
        ),
        PlanCoverage(
            item="feature descriptions",
            reason=(
                f"{len(unreadable)} description(s) unreadable and "
                f"{len(gaps) - len(unreadable)} blank of {len(tree.content)} content "
                "feature(s); the planner never invents description prose, so revision 1 "
                "proposes none, and an unreadable one is refused as a change target "
                "because it has no recoverable inverse"
            ),
            feature_ids=tuple(gap.feature_id for gap in gaps),
        ),
        PlanCoverage(
            item="global variables",
            reason=(
                f"{len(candidates)} feature reading(s) could justify a global; revision 1 "
                "proposes none, and a v1 global names a value and drives nothing"
            ),
            feature_ids=tuple(candidate.feature_id for candidate in candidates),
        ),
        PlanCoverage(
            item="equations",
            reason=(
                f"{len(inventory.rows)} equation row(s): {len(inventory.globals)} global, "
                f"{len(inventory.dimension_driven)} driving a dimension, "
                f"{len(inventory.broken)} broken, {len(inventory.unresolved)} unjudgeable; "
                "revision 1 repairs none and adds none"
            ),
            feature_ids=(),
        ),
        PlanCoverage(
            item="sketch dimensions",
            reason=(
                "not carried by IR 1.2.0, so this version can neither name a dimension, "
                "rename one, nor drive one from a global (FR-030)"
            ),
            feature_ids=(),
        ),
        PlanCoverage(
            item="folders",
            reason=(
                f"{len(planned)} folder(s) to create, {len(correct)} already correct, "
                f"{len(folders.refusals)} refused"
                + (
                    "; an existing group-named folder holding the wrong members refuses "
                    "the part in this version, because there is no dissolve path"
                    if folders.refusals
                    else ""
                )
            ),
            feature_ids=tuple(refusal.existing_folder_id for refusal in folders.refusals),
        ),
        PlanCoverage(
            item="changes",
            reason=_why_changes(tree, changes, folders, scope, order),
            feature_ids=(),
        ),
    ) + tuple(
        PlanCoverage(
            item=split.group,
            reason=(
                f"{split.group} cannot be folded: "
                f"{', '.join(tree.by_id[member].name for member in split.interloper_ids)} "
                f"sit(s) inside its span "
                f"({tree.by_id[split.first_id].name} .. {tree.by_id[split.last_id].name}) "
                "in the achievable order, and a folder wraps a contiguous run"
            ),
            feature_ids=split.interloper_ids,
        )
        for split in non_contiguous
    )


def non_contiguous_groups(
    plan: RemodelPlan, table: RmsTypeTable
) -> tuple[PlanCoverage, ...]:
    """The coverage items naming a group no folder can wrap, in the plan's own order.

    A coverage item whose `item` is one of the six group names is one of these, which is a
    membership test rather than a string prefix: the six names come from the same table the
    planner and the checker read, so a recalibrated table cannot leave a reader parsing for
    a name that is no longer a group.
    """
    groups = set(table.groups)
    return tuple(item for item in plan.coverage if item.item in groups)


def _why_changes(
    tree: PartTree,
    changes: Sequence[PlannedChange],
    folders: FolderPlan,
    scope: ScopeReport,
    order: OrderResult,
) -> str:
    """Why the change list is the length it is, said in words on every run.

    An empty list is a legitimate plan - a part already in the method's order whose folders
    already hold their members has nothing to change - and it is also what a refusal
    produces. The two are never the same sentence, so every refusal `plan_reorganize`
    recognises has a branch here: the scope gate, the mis-membered group folder, and the
    dependency cycle, which is the one input for which no legal order exists at all.
    """
    if changes:
        return f"{len(changes)} change(s) planned, in the fixed order of section 1.11"
    if scope.refused:
        return f"no change is planned: the scope gate refused this part ({scope.message})"
    if folders.refused:
        return (
            "no change is planned: this part already carries a group-named folder holding "
            "the wrong members, and this version has no dissolve path"
        )
    if order.cycle is not None:
        named = " -> ".join(
            tree.by_id[feature_id].name if feature_id in tree.by_id else feature_id
            for feature_id in order.cycle
        )
        return (
            f"no change is planned: the dependency graph has a cycle through {named}, so "
            "no legal order exists and the planner refuses rather than breaking an edge"
        )
    return (
        "no change is planned, and nothing refused this part: the tree is already in the "
        "order the method wants and every group folder it needs already holds exactly its "
        "features"
    )


# --- 8. Run-entry validation and state on disk ----------------------------------------


def require_runnable_plan(plan: RemodelPlan) -> RemodelPlan:
    """Validate the revision-1 hand-off before judgement or document writes begin.

    Dry-run and refused plans are valuable artifacts, but they are not inputs to phases B
    through D. Keeping this check beside the plan model gives the backend runner one
    deterministic rule and prevents a caller from bypassing the pane's state check.
    """
    if plan.state != "planned":
        raise ValueError(
            f"the remodel plan is {plan.state!r}; only a plan in 'planned' state can run"
        )
    if plan.scope.verdict != "ok":
        raise ValueError(
            f"the remodel plan scope is {plan.scope.verdict!r}; the scope probe must "
            "finish without refusals before a run can start"
        )
    if plan.run_id is None or plan.copy_path is None or plan.source is None:
        raise ValueError(
            "the remodel plan has no attested copy; a dry-run plan cannot enter the "
            "mutation phases"
        )
    return plan


# --- 8. The run's state on disk ------------------------------------------------------

PLAN_FILE_NAME = "plan.json"
"""The file, in the run folder (`contracts/run-artifacts.md`). One spelling, here."""

ENTERED_FROM: Mapping[RunState, frozenset[RunState]] = MappingProxyType(
    {
        "planned": frozenset(),
        "judging": frozenset({"planned"}),
        "applying": frozenset({"planned", "judging"}),
        "verifying": frozenset({"applying"}),
        "saved": frozenset({"verifying"}),
        "truncated": frozenset({"verifying"}),
        "failed": frozenset(get_args(RunState)) - {"failed", "discarded"},
        "discarded": frozenset({"saved", "truncated"}),
    }
)
"""Which state each state of `data-model.md` section 11 may be entered from.

The table's rules, read as a graph rather than as prose:

- **the only path into `saved` or `truncated` runs through `verifying`**, which is the
  rule the whole mutation exception rests on: a run that skipped the three checks cannot
  record that it saved;
- `judging` is skippable, so `applying` is entered from `planned` as well as from it;
- **any state a run is still in can fail.** A scope refusal, a contract violation, a
  failed gate, a save error and a source attestation mismatch all reach `failed`, and the
  last of those is re-checked after the save, so `saved -> failed` is a real transition
  and not a slip;
- `discarded` is the engineer's, on a run that reached `saved` or `truncated`. It is not
  reachable from a run that failed, because that run's copy is already gone.

`planned` is entered from nothing: it is the first state written, by the planner, and a
run that reached it again would be a second run in one folder."""


def plan_path(run_dir: Path | str) -> Path:
    """Where the plan of `run_dir` lives."""
    return Path(run_dir) / PLAN_FILE_NAME


def record_state(
    run_dir: Path | str, plan: RemodelPlan, state: RunState, *, at: datetime
) -> RemodelPlan:
    """Move the run to `state`, rewrite `plan.json` in place, and return the moved plan.

    The state is a single field on the plan and the file is rewritten at every transition,
    so the run's state survives a crash and the pane reads it from disk rather than from a
    process that may be gone (section 11).

    Raises:
        ValueError: `state` cannot be entered from the plan's current one. The refusal is
            here rather than at the call sites because the transition that matters -
            nothing reaches `saved` without passing through `verifying` - is the one a
            caller in a hurry would take, and a rule checked only by the caller is a rule
            the caller can skip.
    """
    allowed = ENTERED_FROM[state]
    if plan.state not in allowed:
        raise ValueError(
            f"this run is {plan.state!r} and {state!r} is entered from "
            f"{sorted(allowed) or 'nothing'} (data-model.md section 11); the transition "
            "was not recorded and plan.json still says what the run last did"
        )
    moved = plan.model_copy(update={"state": state, "updated_at": at})
    target = plan_path(run_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(moved.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return moved
