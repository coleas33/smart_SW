"""Which group a feature should be in (T009).

The planner's half of `rms_types.yaml`. Feature 003's checker grades the group a feature
*is* in; `default_group_by_class` names the group it *should* be in, and both read one
file, so the checker and the planner cannot disagree about what "should" means. This
module is the only place feature 004 turns a class into a group.

Three answers, and the difference between the last two is the point
(`research.md` R6.1, `data-model.md` section 1.1):

- `Resolved(group, basis)` - the group, and why it is that group;
- `NeedsJudgement(reason, candidates)` - the planner did not decide. `candidates` says
  whether anyone else can: the six groups when the judgement phase may be asked
  (`classify_unknown` accepts one of the six, `contracts/tools.md`), and empty when no one
  is offered a choice and the feature is reported unresolved and never moved;
- `NotContent()` - the row is not a subject of the grouping rules at all (a folder, an
  end-tag marker, one of the excluded default names, a tolerated system row). "No target
  because it is not a subject" and "no target because nobody could decide" are different
  sentences in the report and are never collapsed here.

Two rules are code rather than table, exactly as the table's own comment says:

1. a **consumed sketch follows its single consumer** into that consumer's group, followed
   through a chain of sketches to the feature that ends it. A sketch with more than one
   consumer is `shared_sketch`: it can be contiguous with one consumer and not the other,
   so the planner names the problem rather than picking a consumer;
2. an **unconsumed sketch** takes the table's sketch default (`2-Construction`). A sketch
   whose consumers were not read is neither: `null` is unreadable, `[]` is read and empty,
   and only the second takes the default.

The third code rule of R6.1 - a fillet or chamfer with dependents may never target
`6-Quarantine` - has nothing to bite on here: the table sends every fillet and chamfer to
`3-Core`, so only the judgement phase can propose Quarantine and the rule is enforced
inside `decide_fillet`'s validation, where the proposal arrives.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from swreview.checks.rms_types import NEEDS_JUDGEMENT, RmsTypeTable
from swreview.ir.models import Feature

__all__ = [
    "BASES",
    "JUDGEMENT_REASONS",
    "Basis",
    "JudgementReason",
    "NeedsJudgement",
    "NotContent",
    "Resolved",
    "TargetDecision",
    "target_group",
]

Basis = Literal[
    "type_table",
    "sketch_follows_consumer",
    "unconsumed_sketch",
    "model_judgement",
    "quarantine_has_children",
]
"""Why a feature has the target group it has (`data-model.md` section 1.1). The pure
planner emits the first three; the last two are the judgement phase's, and they are
declared here so `PlanTarget.basis` has one vocabulary rather than two."""

BASES: tuple[Basis, ...] = get_args(Basis)

JudgementReason = Literal[
    "unclassified",
    "ambiguous_type",
    "shared_sketch",
    "graph_unreadable",
    "cycle",
]
"""Why the planner did not decide. Each one has a home in the rebuild-list taxonomy
(`data-model.md` section 1.5): `unclassified` and `ambiguous_type` both become
`unclassified` when judgement declines or is not asked, and the other three carry the
taxonomy's own names."""

JUDGEMENT_REASONS: tuple[JudgementReason, ...] = get_args(JudgementReason)

_FROZEN = ConfigDict(strict=True, extra="forbid", frozen=True)


class Resolved(BaseModel):
    """The group this feature should be in, and the rule that says so."""

    model_config = _FROZEN

    group: str
    basis: Basis


class NeedsJudgement(BaseModel):
    """No group, and why. `candidates` is what the judgement phase may be offered; empty
    means the question is not one a model can answer and the feature stays unresolved."""

    model_config = _FROZEN

    reason: JudgementReason
    candidates: tuple[str, ...] = ()


class NotContent(BaseModel):
    """This row is not a subject of the grouping rules."""

    model_config = _FROZEN


TargetDecision = Resolved | NeedsJudgement | NotContent


def target_group(
    row: Feature, tree: Sequence[Feature], table: RmsTypeTable
) -> TargetDecision:
    """The group `row` should be in, decided from `table` and, for a sketch, from `tree`.

    `tree` is the whole document's feature list: a sketch is placed by its consumer, and
    the consumer is looked up there by id, never by name.
    """
    return _target(row, tree, table, seen=())


def _target(
    row: Feature,
    tree: Sequence[Feature],
    table: RmsTypeTable,
    seen: tuple[str, ...],
) -> TargetDecision:
    """`target_group` plus the ids already visited while following a sketch chain, so a
    graph that loops back on itself is answered rather than followed forever."""
    if not table.is_content(row):
        return NotContent()

    classification = table.classify(row.type_name)
    default = table.default_group(classification)
    if default == NEEDS_JUDGEMENT:
        reason: JudgementReason = (
            "unclassified" if classification == "unknown" else "ambiguous_type"
        )
        return NeedsJudgement(reason=reason, candidates=table.groups)
    if classification != "sketch":
        return Resolved(group=default, basis="type_table")

    return _sketch_target(row, tree, table, seen, default)


def _sketch_target(
    row: Feature,
    tree: Sequence[Feature],
    table: RmsTypeTable,
    seen: tuple[str, ...],
    default: str,
) -> TargetDecision:
    """A sketch's group: its single consumer's, or the table's default when it has none.

    A consumer that is not content (a tolerated system row) carries no group, so a sketch
    whose only consumer is one has nothing to follow and takes the unconsumed default;
    that is the same outcome as having no consumer at all and is recorded with the same
    basis.
    """
    consumers = row.sketch.consumer_ids if row.sketch is not None else row.child_ids
    if consumers is None:
        return NeedsJudgement(reason="graph_unreadable")

    distinct = list(dict.fromkeys(consumers))
    if not distinct:
        return Resolved(group=default, basis="unconsumed_sketch")
    if len(distinct) > 1:
        return NeedsJudgement(reason="shared_sketch")

    consumer = _row_by_id(distinct[0], tree)
    if consumer is None:
        return NeedsJudgement(reason="graph_unreadable")
    if consumer.id in seen or consumer.id == row.id:
        return NeedsJudgement(reason="cycle")

    decision = _target(consumer, tree, table, seen=(*seen, row.id))
    if isinstance(decision, Resolved):
        return Resolved(group=decision.group, basis="sketch_follows_consumer")
    if isinstance(decision, NotContent):
        return Resolved(group=default, basis="unconsumed_sketch")
    return decision


def _row_by_id(feature_id: str, tree: Sequence[Feature]) -> Feature | None:
    """The row with this id, or `None` when the graph names one this document has not."""
    for row in tree:
        if row.id == feature_id:
            return row
    return None
