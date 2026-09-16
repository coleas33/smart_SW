"""The re-modeler's judgement tools (T109, T111, T113, T115).

One function per row of the tool table in
`specs/004-resilient-remodeler/contracts/tools.md`. The model **proposes intent into the
plan** through these five and does nothing else: it decides no order, no move, no folder,
no rollback and no verdict, and nothing here can reach SOLIDWORKS. That is Principle II
held exactly, and it is what lets stage 1's apply loop run with no model in it.

Three rules carry the module:

- **validation is on the tool side, not in the prompt.** Every row of the rule tables in
  `contracts/tools.md` is a pure function over the plan and the package, enforced here
  before anything is written. A prompt is guidance; this is the contract;
- **a rejection is a result, and it is also written down.** The tool returns
  `{"error": ...}`, which `swreview.tools.registry.RecordedTool.call` already turns into a
  `tool_result` with `is_error: true` and no exception raised - this feature adds no error
  path - and it appends a `RejectedProposal` to the plan, because FR-016 and US4 scenario 7
  have the report list every refusal with its reason and a tool result is persisted nowhere
  the report reads;
- **the only thing a proposal writes is the plan object on `ToolContext.remodel`.** No file,
  no session, no bridge, no document. `RemodelToolContext` is that object: the pure
  planner's revision 1 beside the lists the judgement phase fills, which
  `remodel/runner.py` composes into revision 2 once the judgement turns are over.

Why the accumulators are separate lists rather than a mutated `RemodelPlan`: the plan is
frozen and revision 1 is *defined* as carrying no model decision, so a tool that edited it
in place would have to build an invalid object first. Keeping the four lists beside it
means a half-finished judgement phase is never a plan anybody could write to disk.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Any

from pydantic_core import to_jsonable_python

from swreview.checks.rms.part import CORE, QUARANTINE
from swreview.checks.rms_types import RmsTypeTable, class_of, load_table
from swreview.ir.models import Feature
from swreview.remodel.intent import global_candidates
from swreview.remodel.plan import (
    GLOBAL_NAME_PATTERN,
    DescriptionProposal,
    Deviation,
    GlobalProposal,
    PlanTarget,
    RejectedProposal,
    RemodelPlan,
)
from swreview.remodel.units import DocumentUnitError, global_evidence
from swreview.tools.context import ToolContext, current_context, error_result
from swreview.tools.query import ToolResult

__all__ = [
    "DESCRIPTION_RATIONALE",
    "MAX_DESCRIPTION",
    "MAX_RATIONALE",
    "SECTIONS",
    "UNKNOWN_CLASSIFIED_LINE",
    "RemodelToolContext",
    "classify_unknown",
    "decide_fillet",
    "get_remodel_plan",
    "propose_description",
    "propose_global",
]

MAX_DESCRIPTION = 200
"""`contracts/tools.md`: a feature description is 1 to 200 characters. The same bound is a
`StringConstraints` on `DescriptionProposal.text`, so a proposal that slipped past this
check would still be refused - louder, and by an exception nobody could act on."""

MAX_RATIONALE = 300
"""A rationale is 1 to 300 characters, for all three tools that take one."""

DESCRIPTION_RATIONALE = (
    "proposed through propose_description, which takes no rationale argument"
)
"""`DescriptionProposal.rationale` is required and `propose_description` has no such
argument (the contract's signature is `feature_id, text`), so the provenance is recorded
as what it is rather than invented per call."""

UNKNOWN_CLASSIFIED_LINE = "group assigned by the model, not by the type table"
"""The sentence `report.md` prints beside a feature the model classified, so a reader is
never left to infer that a group came from anything but the method (FR-020)."""

SECTIONS: tuple[str, ...] = (
    "summary",
    "targets",
    "order",
    "pins",
    "rebuild",
    "folders",
    "descriptions",
    "globals",
    "deviations",
    "rejected_proposals",
)
"""Every section `get_remodel_plan` reads back, in the contract's order. The change list,
the copy's path and the source attestation are deliberately absent: the read-back exists so
the model can see what its own proposals became, not so it can learn where anything is."""

_NAME = re.compile(GLOBAL_NAME_PATTERN)


@dataclass
class RemodelToolContext:
    """The plan object the five tools read and write, carried on `ToolContext.remodel`.

    `plan` is the pure planner's revision 1 and is never mutated; the five lists are what
    the judgement phase adds to it, named exactly as the plan's own fields so "writes into
    `plan.descriptions[]`" reads true. `provider` and `model` are stamped onto every
    accepted proposal and every rejection, because FR-056 has the report name both beside
    each judgement item and FR-020 has it keep a model's decision apart from the table's.

    `document_length_unit` is `remodel.open`'s reading of the copy (FR-027). `None` means it
    was not read, and an unread unit is not metres: `propose_global` refuses rather than
    seeding a literal from that assumption, which is the one way stage 1 could build a part
    a thousand times too small (research R3.6).
    """

    plan: RemodelPlan
    provider: str
    model: str
    document_length_unit: str | None = None
    descriptions: list[DescriptionProposal] = field(default_factory=list)
    globals: list[GlobalProposal] = field(default_factory=list)
    targets: list[PlanTarget] = field(default_factory=list)
    deviations: list[Deviation] = field(default_factory=list)
    rejected_proposals: list[RejectedProposal] = field(default_factory=list)


# --- what a tool reads ------------------------------------------------------------


def _judgement() -> tuple[ToolContext, RemodelToolContext]:
    """The active context and its remodel plan.

    Raises `ValueError` when the context carries no plan, exactly as
    `ToolContext.require_session` does for a tool that writes to a session: these five are
    registered only when `ToolContext.remodel` is set, so reaching here without one is a
    caller bypassing the registry rather than anything the model did.
    """
    context = current_context()
    remodel = context.remodel
    if not isinstance(remodel, RemodelToolContext):
        raise ValueError(
            "this tool proposes into a remodel plan and this context carries none; the "
            "remodel tools are registered only when ToolContext.remodel is set"
        )
    return context, remodel


def _rows(context: ToolContext, remodel: RemodelToolContext) -> dict[str, Feature]:
    """The tree of the one document this plan is about, by feature id."""
    return {
        row.id: row
        for row in context.ir.features
        if row.document_id == remodel.plan.document_id
    }


def _package_globals(context: ToolContext, remodel: RemodelToolContext) -> set[str]:
    """Every name the document's equation manager already declares on its left side.

    Every row, not only the rows whose `IEquationMgr.GlobalVariable` flag read back true: a
    flag nobody could read does not make the name free, and proposing a global over it would
    be a silent collision (Principle I).
    """
    return {
        row.lhs
        for row in context.ir.equations
        if row.document_id == remodel.plan.document_id
    }


def _dependents(
    row: Feature, rows: dict[str, Feature], table: RmsTypeTable
) -> tuple[str, ...] | None:
    """The content features of this document that depend on `row`; `None` when unreadable.

    `checks/rms/part.py` asks the same question of a `PartTree` for
    `rms.refs.quarantine_has_no_children`; this asks it of the plan's row index, which is
    what the tool layer has. The two agree on what counts: a child id this document does not
    carry, or one that names a folder or an end-tag marker, is not a dependent.
    """
    if row.child_ids is None:
        return None
    return tuple(
        child_id
        for child_id in row.child_ids
        if (child := rows.get(child_id)) is not None and table.is_content(child)
    )


def _reject(
    remodel: RemodelToolContext,
    tool: str,
    arguments: dict[str, Any],
    reason: str,
    rule: str,
) -> ToolResult:
    """Write the refusal into the plan, then hand the model the same sentence.

    Both halves, always: the model needs the error to act on and the report needs the row,
    and a tool that did only one of the two would leave FR-016 unsatisfiable or the model
    guessing (contracts/tools.md, "A rejection is also written down").
    """
    remodel.rejected_proposals.append(
        RejectedProposal(
            at=datetime.now(UTC),
            tool=tool,  # type: ignore[arg-type]
            arguments=arguments,
            reason=reason,
            rule=rule,
            provider=remodel.provider,
            model=remodel.model,
        )
    )
    return error_result(reason)


def _model_target(
    row: Feature, group: str, rationale: str, remodel: RemodelToolContext, table: RmsTypeTable
) -> PlanTarget:
    """One resolved target the model decided, with the provenance FR-056 requires.

    `current_group` is carried across from the planner's own target rather than recomputed:
    where a feature is now is the planner's reading, and a second reading of it here is how
    the plan and the report start to disagree.
    """
    planned = {item.feature_id: item for item in remodel.plan.targets}
    current = planned[row.id].current_group if row.id in planned else None
    return PlanTarget(
        feature_id=row.id,
        name=row.name,
        type_name=row.type_name,
        feature_class=class_of(row, table),
        current_group=current,
        target_group=group,
        basis="model_judgement",
        decided_by="model",
        state="resolved",
        candidates=(),
        rationale=rationale,
        provider=remodel.provider,
        model=remodel.model,
    )


# --- 1. propose_description -------------------------------------------------------


def propose_description(feature_id: str, text: str) -> ToolResult:
    """Propose a one-line description for one content feature of the part being re-modeled.

    Args:
        feature_id: Feature id as the package carries it, for example `feat:0004`.
        text: The description to write: 1 to 200 characters, one line, not the feature name.

    Notes:
        Accepted, it lands in the plan's description list and nowhere else; the executor is
        what writes it into the copy, later and on its own. Refused, the reason comes back
        as an error result and is recorded in the plan so the report can list it.

        A feature whose current description could not be read is refused outright: writing
        over something unreadable has no recoverable inverse, and that feature is on the
        rebuild list instead.
    """
    context, remodel = _judgement()
    arguments = {"feature_id": feature_id, "text": text}
    reject = partial(_reject, remodel, "propose_description", arguments)
    table = load_table()
    row = _rows(context, remodel).get(feature_id)

    if row is None:
        return reject("unknown feature id", "propose_description.unknown_feature")
    if not table.is_content(row):
        return reject("not a content feature", "propose_description.not_content")
    if not 1 <= len(text) <= MAX_DESCRIPTION:
        return reject(
            f"description must be 1 to {MAX_DESCRIPTION} characters",
            "propose_description.length",
        )
    if "\n" in text or "\r" in text:
        return reject(
            "description must be a single line", "propose_description.single_line"
        )
    if _folds_to(text, row.name) or _folds_to(text, row.type_name):
        return reject(
            "description repeats the feature name", "propose_description.repeats_name"
        )
    if row.description is None:
        return reject(
            "current description is unreadable; this feature is on the rebuild list",
            "propose_description.unreadable",
        )
    if any(item.feature_id == feature_id for item in remodel.descriptions):
        return reject(
            "already proposed for this feature", "propose_description.duplicate"
        )

    remodel.descriptions.append(
        DescriptionProposal(
            feature_id=feature_id,
            before=row.description,
            text=text,
            source="model",
            rationale=DESCRIPTION_RATIONALE,
            provider=remodel.provider,
            model=remodel.model,
            validation="accepted",
        )
    )
    return {"feature_id": feature_id, "text": text}


def _folds_to(text: str, name: str) -> bool:
    """Whether `text` is `name` once trimmed and case-folded, which is not a description."""
    return text.strip().casefold() == name.strip().casefold()


def _references(expression: str) -> tuple[str, ...] | None:
    """The globals `expression` reads, or `None` when it does not parse.

    `remodel/apply.py` is imported inside the function rather than at module scope: it
    reaches `checks/rms/run.py`, which imports `agent/runner.py`, which imports
    `tools/registry.py`, which imports this module - a cycle that would break every import
    of the tool layer. One deferred import is the whole cost of validating a proposal with
    the very reader the executor will use on it, and two readers of one syntax is how the
    tool would accept an expression the executor then refuses.
    """
    from swreview.remodel.apply import EquationStepError, referenced_globals

    try:
        return referenced_globals(expression)
    except EquationStepError:
        return None


# --- 2. propose_global ------------------------------------------------------------


def propose_global(
    name: str, expression: str, rationale: str, evidence: list[str]
) -> ToolResult:
    """Propose one global variable, justified by feature data the package already carries.

    Args:
        name: Lower_snake_case, 2 to 32 characters, unused in this part.
        expression: SOLIDWORKS equation syntax; quoted global names, `sin cos tan atn arcsin
            sqr`, degrees.
        rationale: Why this part wants this global, 1 to 300 characters.
        evidence: Feature ids whose readings justify the value; empty only for an expression
            over globals proposed earlier in this run.

    Notes:
        A global proposed here **names a value and drives nothing**: no sketch dimension is
        rewired to it, because this version's evidence package carries no dimensions. The
        argument is called `evidence` and not `drives` for exactly that reason.

        Only readings the package actually holds can justify a value, so a feature carrying
        no such parameter is refused rather than accepted on a number nobody read.
    """
    context, remodel = _judgement()
    arguments = {
        "name": name,
        "expression": expression,
        "rationale": rationale,
        "evidence": list(evidence),
    }
    reject = partial(_reject, remodel, "propose_global", arguments)

    if not _NAME.fullmatch(name):
        return reject(
            "global name must be lower_snake_case, 2 to 32 characters",
            "propose_global.name_pattern",
        )
    proposed = {item.name for item in remodel.globals}
    if name in proposed:
        return reject("already proposed", "propose_global.already_proposed")
    existing = _package_globals(context, remodel)
    if name in existing:
        return reject(
            "a global with this name already exists", "propose_global.existing_global"
        )

    references = _references(expression)
    if references is None:
        return reject("expression does not parse", "propose_global.expression_parse")
    if name in references:
        return reject("expression is circular", "propose_global.circular")
    if any(reference not in proposed | existing for reference in references):
        return reject(
            "expression references an undeclared name",
            "propose_global.undeclared_reference",
        )

    table = load_table()
    rows = _rows(context, remodel)
    for feature_id in evidence:
        row = rows.get(feature_id)
        if row is None or not table.is_content(row):
            return reject(
                "evidence names an unknown feature", "propose_global.unknown_evidence"
            )
    candidates = {
        item.feature_id: item
        for item in global_candidates(list(rows.values()), table)
    }
    if any(feature_id not in candidates for feature_id in evidence):
        return reject(
            "no parameter data for this feature in the package",
            "propose_global.no_parameter_data",
        )
    # A global whose expression reads only globals this run proposed earlier takes its
    # number from those; anything else carries a literal, and a literal nobody can point at
    # a reading for is a number the model invented.
    derived = bool(references) and all(
        reference in proposed for reference in references
    )
    if not evidence and not derived:
        return reject(
            "a literal global needs feature data behind it",
            "propose_global.evidence_required",
        )
    if not 1 <= len(rationale) <= MAX_RATIONALE:
        return reject("rationale required", "propose_global.rationale")

    try:
        rows_of_evidence = tuple(
            global_evidence(
                candidates[feature_id],
                name=name,
                document_length_unit=remodel.document_length_unit,
            )
            for feature_id in evidence
        )
    except DocumentUnitError as exc:
        return reject(str(exc), "propose_global.document_unit")

    remodel.globals.append(
        GlobalProposal(
            name=name,
            expression=expression,
            rationale=rationale,
            evidence=rows_of_evidence,
            provider=remodel.provider,
            model=remodel.model,
            validation="accepted",
            order_index=len(remodel.globals),
        )
    )
    return {"name": name, "expression": expression, "evidence": list(evidence)}


# --- 3. decide_fillet -------------------------------------------------------------


def decide_fillet(feature_id: str, group: str, rationale: str) -> ToolResult:
    """Say whether one fillet is structural or cosmetic, and nothing else about it.

    Args:
        feature_id: Feature id of a fillet, for example `feat:0004`.
        group: `3-Core` for a structural fillet, `6-Quarantine` for a cosmetic one.
        rationale: What makes it one or the other, 1 to 300 characters.

    Notes:
        A fillet nobody decides stays in `3-Core`, which is the safe default and never
        violates the rule that nothing may depend on a quarantined feature; the report lists
        it as reviewed as structural. So declining to call this costs nothing.

        `6-Quarantine` is refused for a fillet anything depends on, and refused again when
        the dependency list could not be read: not knowing is not the same as knowing there
        are none.
    """
    context, remodel = _judgement()
    arguments = {"feature_id": feature_id, "group": group, "rationale": rationale}
    reject = partial(_reject, remodel, "decide_fillet", arguments)
    table = load_table()
    rows = _rows(context, remodel)
    row = rows.get(feature_id)

    if row is None:
        return reject("unknown feature id", "decide_fillet.unknown_feature")
    if not table.is_content(row) or class_of(row, table) != "fillet":
        return reject("not a fillet", "decide_fillet.not_a_fillet")
    core, quarantine = table.groups[CORE], table.groups[QUARANTINE]
    if group not in (core, quarantine):
        return reject(
            f"a fillet belongs in {core} or {quarantine}", "decide_fillet.group"
        )
    if group == quarantine:
        dependents = _dependents(row, rows, table)
        if dependents is None:
            return reject(
                "this fillet's dependents could not be read; Quarantine requires none",
                "decide_fillet.dependents_unreadable",
            )
        if dependents:
            return reject(
                "this fillet has dependents; Quarantine requires none",
                "decide_fillet.quarantine_has_dependents",
            )
    if not 1 <= len(rationale) <= MAX_RATIONALE:
        return reject("rationale required", "decide_fillet.rationale")
    if any(item.feature_id == feature_id for item in remodel.targets):
        return reject("already decided for this feature", "decide_fillet.already_decided")

    remodel.targets.append(_model_target(row, group, rationale, remodel, table))
    return {"feature_id": feature_id, "group": group}


# --- 4. classify_unknown ----------------------------------------------------------


def classify_unknown(feature_id: str, group: str, rationale: str) -> ToolResult:
    """Put one feature the type table could not classify into one of the six groups.

    Args:
        feature_id: Feature id whose type name the method does not recognise.
        group: One of `1-Ref`, `2-Construction`, `3-Core`, `4-Detail`, `5-Modify`,
            `6-Quarantine`.
        rationale: What this feature does, and why that group, 1 to 300 characters.

    Notes:
        Only a feature the table calls unknown or ambiguous may be classified here; one the
        table already placed is not yours to move. A feature you do not classify stays
        unclassified and is never moved, so declining is always safe.

        Every accepted call is recorded as a deviation, so the report can say that this
        group came from the model rather than from the method's type table.
    """
    context, remodel = _judgement()
    arguments = {"feature_id": feature_id, "group": group, "rationale": rationale}
    reject = partial(_reject, remodel, "classify_unknown", arguments)
    table = load_table()
    row = _rows(context, remodel).get(feature_id)

    if row is None:
        return reject("unknown feature id", "classify_unknown.unknown_feature")
    if not table.is_content(row):
        return reject("not a content feature", "classify_unknown.not_content")
    if class_of(row, table) not in ("unknown", "ambiguous"):
        return reject(
            "this feature already has a class", "classify_unknown.already_classified"
        )
    if group not in table.groups:
        return reject("group must be one of the six", "classify_unknown.group")
    if not 1 <= len(rationale) <= MAX_RATIONALE:
        return reject("rationale required", "classify_unknown.rationale")
    if any(item.feature_id == feature_id for item in remodel.targets):
        return reject(
            "already decided for this feature", "classify_unknown.already_decided"
        )

    remodel.targets.append(_model_target(row, group, rationale, remodel, table))
    remodel.deviations.append(
        Deviation(
            kind="unknown_classified_by_model",
            feature_id=feature_id,
            chosen=group,
            rationale=rationale,
            report_line=UNKNOWN_CLASSIFIED_LINE,
        )
    )
    return {"feature_id": feature_id, "group": group}


# --- 5. get_remodel_plan ----------------------------------------------------------


def get_remodel_plan(section: str) -> list[dict[str, Any]] | ToolResult:
    """Read one section of the plan back, after validation. Writes nothing.

    Args:
        section: `summary`, `targets`, `order`, `pins`, `rebuild`, `folders`,
            `descriptions`, `globals`, `deviations` or `rejected_proposals`.

    Notes:
        This is how you see what your own proposals became: an accepted one appears in its
        section, a refused one appears under `rejected_proposals` with the reason it was
        refused. `targets` shows the whole partition, with your decisions in place of the
        planner's for the features you decided.

        Nothing outside the plan is readable here: no file, no path, no change log.
    """
    _, remodel = _judgement()
    plan = remodel.plan
    if section == "summary":
        return _summary(remodel)
    if section == "targets":
        return _rows_of(_targets(remodel))
    if section == "order":
        return _json(plan.order)
    if section == "pins":
        return _rows_of(plan.pins)
    if section == "rebuild":
        return _rows_of(plan.rebuild)
    if section == "folders":
        return _json(plan.folders)
    if section == "descriptions":
        return _rows_of(remodel.descriptions)
    if section == "globals":
        return _rows_of(remodel.globals)
    if section == "deviations":
        return _rows_of((*plan.deviations, *remodel.deviations))
    if section == "rejected_proposals":
        return _rows_of(remodel.rejected_proposals)
    return error_result("unknown section")


def _json(value: Any) -> dict[str, Any]:
    """One plan member as the JSON a tool result carries.

    `to_jsonable_python` rather than `tools/query.as_json`, because the plan is not all
    pydantic: `Pin`, `RebuildEntry`, `Move` and `FolderPlan` are the planner modules' own
    frozen dataclasses, carried across into the plan rather than redefined as models, and
    `model_dump` is not a member of any of them.
    """
    return dict(to_jsonable_python(value))


def _rows_of(values: Sequence[Any]) -> list[dict[str, Any]]:
    """One section that is a list, row by row."""
    return [_json(value) for value in values]


def _targets(remodel: RemodelToolContext) -> tuple[PlanTarget, ...]:
    """The partition as it stands: the planner's targets, with the model's in their place.

    In their place and not beside them - two targets for one feature is not a partition, and
    the plan is a partition of the tree by construction (`data-model.md` section 1.1).
    """
    decided = {item.feature_id: item for item in remodel.targets}
    return tuple(
        decided.get(item.feature_id, item) for item in remodel.plan.targets
    )


def _summary(remodel: RemodelToolContext) -> dict[str, Any]:
    """The counts, so a model can see the shape of the plan without pulling every row."""
    plan = remodel.plan
    return {
        "document_id": plan.document_id,
        "configuration": plan.configuration,
        "state": plan.state,
        "plan_revision": plan.plan_revision,
        "targets": len(plan.targets),
        "pins": len(plan.pins),
        "rebuild": len(plan.rebuild),
        "move_count": plan.order.move_count,
        "descriptions": len(remodel.descriptions),
        "globals": len(remodel.globals),
        "deviations": len(plan.deviations) + len(remodel.deviations),
        "rejected_proposals": len(remodel.rejected_proposals),
    }
