"""The 17 part-scope rule evaluators, and `evaluate_part` (T020).

One pure function per rule of `specs/003-resilient-modeling/contracts/rules.md`, each
decorated `@bind("<rule id>")` and returning `list[RuleResult]` - one result per outcome
it reaches, so a rule that fails on two features and cannot read a third lands in two
buckets of the report and never averages the two into one verdict.

Four conventions hold across every rule here, and each of them is one of the contract's
normative paragraphs rather than a style choice:

- **groups come from `assign_groups` and nothing else.** No rule reads `name`, `depth` or
  `folder_id` to decide where a feature sits; `PartTree` asks the assignment, which is
  what makes the nested and the flat traversal shapes give identical answers
  (`rules.md`, "Group assignment").
- **classes come from `class_of`.** A rule that needs a specific class reports a feature
  of class `unknown` as unresolved, and `ambiguous` as unresolved unless the rule reads
  material (`rules.md`, "Class vocabulary"). The rules that need no class - grouping,
  descriptions, references, sketches - treat an unrecognised feature like any other
  content feature.
- **a missing input is unresolved for that subject, never a pass and never a fail**
  (constitution Principle I). `_verdict` is the one place that decides: a violation wins,
  otherwise the resolvable subjects pass, and a rule whose every subject was unresolved
  does not also report a pass.
- **the six groups are named by role, not by table name.** `rms_types.yaml` may be
  recalibrated to other spellings than `1-Ref`; the reasons an engineer reads say "no
  Quarantine group" either way, and the table's own order is the method's order.

`rms.detail.individually_suppressible` is the one rule that reads more than the tree: it
grades the Detail content features against `package.rms_suppress_test`, the run the US4
console command appends, and reports what that run covered as well as what it found.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from swreview import units
from swreview.checks.rms.groups import GroupAssignment
from swreview.checks.rms.registry import RULES, RmsRule, bind, evaluable
from swreview.checks.rms.results import (
    RuleResult,
    finding,
    passed,
    skipped,
    subject_reasons,
    unresolved,
)
from swreview.checks.rms_types import Classification, RmsTypeTable, class_of
from swreview.ir.models import EvidencePackage, Feature, SuppressTestRow

__all__ = [
    "PartTree",
    "chamfers_before_fillets",
    "document_gap",
    "evaluate_part",
    "every_feature_described",
    "folders_ordered",
    "folders_present",
    "grouping_all_features_in_a_group",
    "holes_last",
    "individually_suppressible",
    "largest_fillet_first",
    "no_internal_references",
    "no_solids_in_ref_or_construction",
    "one_sketch_per_feature",
    "only_fillets_and_chamfers",
    "part_tree",
    "quarantine_has_no_children",
    "refs_direction",
    "shell_last",
    "sketches_fully_defined",
    "sketches_not_over_defined",
    "transform_before_replicate",
    "tree_not_read",
]

SCOPE = "part"

ROLES: tuple[str, ...] = (
    "Reference",
    "Construction",
    "Core",
    "Detail",
    "Modify",
    "Quarantine",
)
"""What the six groups are for, in the method's order; `rms_types.yaml` carries the names
they have in a tree (`1-Ref`, ...) and this is what a reason calls them."""

REFERENCE, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = range(len(ROLES))

MATERIAL: frozenset[str] = frozenset({"solid", "cut", "hole", "ambiguous"})
"""What `rms.groups.no_solids_in_ref_or_construction` calls material: the three material
classes plus `ambiguous`, which is the one rule that reads material and therefore the one
rule for which `ICE` is an answer rather than a question (`rules.md`, "Class vocabulary")."""

UNCLASSIFIED: frozenset[str] = frozenset({"unknown", "ambiguous"})
"""The two classifications no class-dependent rule may act on."""

FOLDERS_PRESENT = "rms.folders.present"
FOLDERS_ORDERED = "rms.folders.ordered"
GROUPING = "rms.grouping.all_features_in_a_group"
NO_SOLIDS = "rms.groups.no_solids_in_ref_or_construction"
SHELL_LAST = "rms.core.shell_last"
HOLES_LAST = "rms.detail.holes_last"
TRANSFORM_BEFORE_REPLICATE = "rms.modify.transform_before_replicate"
CHAMFERS_BEFORE_FILLETS = "rms.quarantine.chamfers_before_fillets"
LARGEST_FILLET_FIRST = "rms.quarantine.largest_fillet_first"
ONLY_FILLETS_AND_CHAMFERS = "rms.quarantine.only_fillets_and_chamfers"
REFS_DIRECTION = "rms.refs.direction"
QUARANTINE_HAS_NO_CHILDREN = "rms.refs.quarantine_has_no_children"
NO_INTERNAL_REFERENCES = "rms.detail.no_internal_references"
EVERY_FEATURE_DESCRIBED = "rms.intent.every_feature_described"
SKETCHES_FULLY_DEFINED = "rms.sketches.fully_defined"
SKETCHES_NOT_OVER_DEFINED = "rms.sketches.not_over_defined"
ONE_SKETCH_PER_FEATURE = "rms.sketches.one_sketch_per_feature"
INDIVIDUALLY_SUPPRESSIBLE = "rms.detail.individually_suppressible"


# --- the tree a rule reads --------------------------------------------------------


@dataclass(frozen=True)
class PartTree:
    """One part document, with the answers every rule would otherwise recompute.

    Built once per document by `part_tree` and handed to each rule, so the content set,
    the id index and the set of groups present are computed once rather than eighteen
    times, and so a rule's signature says exactly what a rule may read.
    """

    document_id: str
    rows: tuple[Feature, ...]
    """Every row of the document's tree in `index` order, folders and end tags included."""

    content: tuple[Feature, ...]
    """The rows the method holds to its rules (`rules.md`, "Content features")."""

    by_id: Mapping[str, Feature]
    groups_present: frozenset[str]
    table: RmsTypeTable
    assignment: GroupAssignment
    package: EvidencePackage

    def group_name(self, role: int) -> str:
        """The tree name of the group in `role`, e.g. `4-Detail` for `DETAIL`."""
        return self.table.groups[role]

    def has_group(self, role: int) -> bool:
        return self.table.groups[role] in self.groups_present

    def group_of(self, row: Feature) -> str | None:
        return self.assignment.by_feature_id[row.id]

    def in_group(self, role: int) -> tuple[Feature, ...]:
        """The content features of one group, in `index` order."""
        name = self.table.groups[role]
        return tuple(row for row in self.content if self.group_of(row) == name)

    def subfolder_of(self, row: Feature) -> str | None:
        return self.assignment.subfolder_by_feature_id[row.id]

    def class_of(self, row: Feature) -> Classification:
        return class_of(row, self.table)

    def rank_of(self, row: Feature) -> int | None:
        """Where a feature's group sits in the method's order; `None` for no group."""
        group = self.group_of(row)
        return None if group is None else self.table.groups.index(group)


def part_tree(
    document_id: str,
    features: Sequence[Feature],
    table: RmsTypeTable,
    assignment: GroupAssignment,
    package: EvidencePackage,
) -> PartTree:
    """Index one part document's rows for the rules; `features` is that document's tree."""
    if len(table.groups) != len(ROLES):
        raise ValueError(
            f"the type table names {len(table.groups)} groups {list(table.groups)}; the "
            f"method has {len(ROLES)}: {list(ROLES)}"
        )
    rows = tuple(sorted(features, key=lambda row: row.index))
    for row in rows:
        if row.document_id != document_id:
            raise ValueError(
                f"{row.id} belongs to {row.document_id}, not to {document_id}; "
                "a part rule evaluates one document's tree"
            )
        if row.id not in assignment.by_feature_id:
            raise ValueError(f"{row.id} is not in the group assignment of {document_id}")
    return PartTree(
        document_id=document_id,
        rows=rows,
        content=tuple(row for row in rows if table.is_content(row)),
        by_id={row.id: row for row in rows},
        groups_present=frozenset(name for name, _ in assignment.groups_seen),
        table=table,
        assignment=assignment,
        package=package,
    )


# --- shared shapes ----------------------------------------------------------------


def _verdict(
    rule: RmsRule,
    tree: PartTree,
    *,
    violation: RuleResult | None = None,
    passing: Sequence[Feature] = (),
    unknown: Sequence[tuple[Feature, str]] = (),
) -> list[RuleResult]:
    """The outcomes of a per-subject rule: at most one verdict, plus the unresolved half.

    A violation replaces the pass rather than joining it - a rule that failed on this
    document is not also `checked` for it - and a rule whose every subject was unresolved
    reports only that, while a rule with nothing to look at at all passes vacuously.
    """
    results: list[RuleResult] = []
    if violation is not None:
        results.append(violation)
    elif passing or not unknown:
        results.append(passed(rule, tree.document_id, passing))
    if unknown:
        results.append(
            unresolved(
                rule,
                tree.document_id,
                subject_reasons(unknown),
                [row for row, _ in unknown],
            )
        )
    return results


def _ordered(rows: Sequence[Feature]) -> list[Feature]:
    """The rows in tree order, each named once, however the caller collected them."""
    unique: dict[str, Feature] = {}
    for row in rows:
        unique.setdefault(row.id, row)
    return sorted(unique.values(), key=lambda row: row.index)


def _named(rows: Sequence[Feature]) -> str:
    return ", ".join(row.name for row in rows)


def _typed(rows: Sequence[Feature]) -> str:
    return ", ".join(f"{row.name} [{row.type_name}]" for row in rows)


def _dependents(tree: PartTree, row: Feature) -> list[Feature]:
    """The content features of this document that depend on `row`.

    A child id this document does not carry, or one that names a folder or an end-tag
    marker, is not a dependent a rule reports: the contract keeps end tags out of every
    subject list, and a reference into another document is not this rule's business.
    """
    dependents: list[Feature] = []
    for child_id in row.child_ids or ():
        child = tree.by_id.get(child_id)
        if child is not None and tree.table.is_content(child):
            dependents.append(child)
    return dependents


def _children_unavailable(rows: Sequence[Feature]) -> list[tuple[Feature, str]]:
    return [(row, "children unavailable") for row in rows if row.child_ids is None]


def _consumers(tree: PartTree, row: Feature) -> list[Feature]:
    """A sketch's consumers as rows, in the order the extractor read them."""
    assert row.sketch is not None
    consumers: list[Feature] = []
    for consumer_id in row.sketch.consumer_ids or ():
        consumer = tree.by_id.get(consumer_id)
        if consumer is not None:
            consumers.append(consumer)
    return consumers


def _sketch_subjects(tree: PartTree, rows: Sequence[Feature]) -> list[Feature]:
    """Each sketch followed by its consumers - the contract's "sketch and consumers"."""
    subjects: list[Feature] = []
    seen: set[str] = set()
    for row in rows:
        for subject in (row, *_consumers(tree, row)):
            if subject.id not in seen:
                seen.add(subject.id)
                subjects.append(subject)
    return subjects


def _sketches(tree: PartTree) -> list[Feature]:
    return [row for row in tree.content if row.sketch is not None]


# --- rms.folders.present ----------------------------------------------------------


@bind(FOLDERS_PRESENT)
def folders_present(tree: PartTree) -> list[RuleResult]:
    """Every one of the six groups exists as a folder. Never skips."""
    rule = RULES[FOLDERS_PRESENT]
    missing = [name for name in tree.table.groups if name not in tree.groups_present]
    if not missing:
        return [passed(rule, tree.document_id)]
    return [
        finding(
            rule,
            tree.document_id,
            (),
            observed=f"missing group folder(s): {', '.join(missing)}",
            recommended_action=(
                "Add the missing group folders and move the features that belong in them."
            ),
        )
    ]


# --- rms.folders.ordered ----------------------------------------------------------


@bind(FOLDERS_ORDERED)
def folders_ordered(tree: PartTree) -> list[RuleResult]:
    """Group folders appear once each, in the method's order."""
    rule = RULES[FOLDERS_ORDERED]
    seen = tree.assignment.groups_seen
    if len(seen) < 2:
        return [skipped(rule, tree.document_id, "fewer than two groups")]

    order = [tree.table.groups.index(name) for name, _ in seen]
    offenders: list[Feature] = []
    for before in range(len(seen)):
        for after in range(before + 1, len(seen)):
            if order[before] > order[after]:
                offenders += [tree.by_id[seen[before][1]], tree.by_id[seen[after][1]]]
    for name, folder_id in tree.assignment.duplicates:
        first = next(other_id for other_name, other_id in seen if other_name == name)
        offenders += [tree.by_id[first], tree.by_id[folder_id]]

    folders = [tree.by_id[folder_id] for _, folder_id in seen]
    if not offenders:
        return [passed(rule, tree.document_id, folders)]

    parts = []
    if tree.assignment.duplicates:
        duplicated = sorted({name for name, _ in tree.assignment.duplicates})
        parts.append(f"duplicated group folder(s): {', '.join(duplicated)}")
    parts.append(f"group folders in tree order: {', '.join(name for name, _ in seen)}")
    parts.append(f"the method's order is {', '.join(tree.table.groups)}")
    return [
        finding(
            rule,
            tree.document_id,
            _ordered(offenders),
            observed="; ".join(parts),
            recommended_action=(
                "Reorder the group folders into the method's order and merge any duplicate."
            ),
        )
    ]


# --- rms.grouping.all_features_in_a_group -----------------------------------------


@bind(GROUPING)
def grouping_all_features_in_a_group(tree: PartTree) -> list[RuleResult]:
    """Every content feature lives inside a group. Never skips: no folders means all loose."""
    rule = RULES[GROUPING]
    loose = [row for row in tree.content if tree.group_of(row) is None]
    grouped = [row for row in tree.content if tree.group_of(row) is not None]
    violation = None
    if loose:
        violation = finding(
            rule,
            tree.document_id,
            loose,
            observed=(
                f"{len(loose)} content feature(s) sit outside every group: {_named(loose)}"
            ),
            recommended_action="Move each feature into the group folder its role belongs to.",
        )
    return _verdict(rule, tree, violation=violation, passing=grouped)


# --- rms.groups.no_solids_in_ref_or_construction ----------------------------------


@bind(NO_SOLIDS)
def no_solids_in_ref_or_construction(tree: PartTree) -> list[RuleResult]:
    """Reference and Construction hold no material; `ambiguous` counts as material."""
    rule = RULES[NO_SOLIDS]
    roles = [role for role in (REFERENCE, CONSTRUCTION) if tree.has_group(role)]
    if not roles:
        return [
            skipped(
                rule,
                tree.document_id,
                f"no {ROLES[REFERENCE]} or {ROLES[CONSTRUCTION]} group",
            )
        ]

    rows = _ordered([row for role in roles for row in tree.in_group(role)])
    unknown: list[tuple[Feature, str]] = []
    offenders: list[Feature] = []
    passing: list[Feature] = []
    for row in rows:
        kind = tree.class_of(row)
        if kind == "unknown":
            unknown.append((row, f"class of {row.type_name} is unknown"))
        elif kind in MATERIAL:
            offenders.append(row)
        else:
            passing.append(row)

    violation = None
    if offenders:
        located = ", ".join(
            f"{row.name} [{row.type_name}] in {tree.group_of(row)}" for row in offenders
        )
        violation = finding(
            rule,
            tree.document_id,
            offenders,
            observed=f"material feature(s) in a reference or construction group: {located}",
            recommended_action=(
                f"Move the material features into {ROLES[CORE]} or {ROLES[DETAIL]}."
            ),
        )
    return _verdict(rule, tree, violation=violation, passing=passing, unknown=unknown)


# --- rms.core.shell_last ----------------------------------------------------------


@bind(SHELL_LAST)
def shell_last(tree: PartTree) -> list[RuleResult]:
    """The shell is the last feature in Core."""
    rule = RULES[SHELL_LAST]
    if not tree.has_group(CORE):
        return [skipped(rule, tree.document_id, f"no {ROLES[CORE]} group")]
    rows = tree.in_group(CORE)
    shells = [row for row in rows if tree.class_of(row) == "shell"]
    if not shells:
        return [skipped(rule, tree.document_id, f"no shell in {ROLES[CORE]}")]

    last = shells[-1]
    after = [row for row in rows if row.index > last.index]
    violation = None
    if after:
        violation = finding(
            rule,
            tree.document_id,
            [last, *after],
            observed=(
                f"{last.name} is not the last feature in {ROLES[CORE]}; "
                f"{len(after)} feature(s) follow it: {_named(after)}"
            ),
            recommended_action=f"Move the shell to the end of {ROLES[CORE]}.",
        )
    return _verdict(rule, tree, violation=violation, passing=[last])


# --- rms.detail.holes_last --------------------------------------------------------


@bind(HOLES_LAST)
def holes_last(tree: PartTree) -> list[RuleResult]:
    """Holes are the trailing block of Detail; sketches are ignored."""
    rule = RULES[HOLES_LAST]
    if not tree.has_group(DETAIL):
        return [skipped(rule, tree.document_id, f"no {ROLES[DETAIL]} group")]

    unknown: list[tuple[Feature, str]] = []
    graded: list[tuple[Feature, Classification]] = []
    for row in tree.in_group(DETAIL):
        kind = tree.class_of(row)
        if kind == "sketch":
            continue
        if kind in UNCLASSIFIED:
            unknown.append((row, f"class of {row.type_name} is {kind}"))
        else:
            graded.append((row, kind))

    holes = [row for row, kind in graded if kind == "hole"]
    if not holes:
        results = [skipped(rule, tree.document_id, f"no hole in {ROLES[DETAIL]}")]
        if unknown:
            results.append(
                unresolved(
                    rule,
                    tree.document_id,
                    subject_reasons(unknown),
                    [row for row, _ in unknown],
                )
            )
        return results

    first = holes[0]
    block = [row for row, _ in graded if row.index >= first.index]
    offenders = [row for row, kind in graded if row.index > first.index and kind != "hole"]
    violation = None
    if offenders:
        violation = finding(
            rule,
            tree.document_id,
            block,
            observed=(
                f"{_named(offenders)} follow the first hole {first.name} in {ROLES[DETAIL]}"
            ),
            recommended_action=f"Move the holes to the end of {ROLES[DETAIL]}.",
        )
    return _verdict(rule, tree, violation=violation, passing=block, unknown=unknown)


# --- rms.modify.transform_before_replicate ----------------------------------------


@bind(TRANSFORM_BEFORE_REPLICATE)
def transform_before_replicate(tree: PartTree) -> list[RuleResult]:
    """Drafts precede patterns in Modify."""
    rule = RULES[TRANSFORM_BEFORE_REPLICATE]
    if not tree.has_group(MODIFY):
        return [skipped(rule, tree.document_id, f"no {ROLES[MODIFY]} group")]

    rows = tree.in_group(MODIFY)
    drafts = [row for row in rows if tree.class_of(row) == "draft"]
    patterns = [row for row in rows if tree.class_of(row) == "pattern"]
    absent = [what for what, found in (("no draft", drafts), ("no pattern", patterns)) if not found]
    if absent:
        return [skipped(rule, tree.document_id, f"{' and '.join(absent)} in {ROLES[MODIFY]}")]

    draft, pattern = drafts[-1], patterns[0]
    violation = None
    if pattern.index < draft.index:
        violation = finding(
            rule,
            tree.document_id,
            _ordered([pattern, draft]),
            observed=(
                f"the pattern {pattern.name} precedes the draft {draft.name} "
                f"in {ROLES[MODIFY]}"
            ),
            recommended_action=f"Move the drafts ahead of the patterns in {ROLES[MODIFY]}.",
        )
    return _verdict(rule, tree, violation=violation, passing=_ordered([draft, pattern]))


# --- rms.quarantine.chamfers_before_fillets ---------------------------------------


@bind(CHAMFERS_BEFORE_FILLETS)
def chamfers_before_fillets(tree: PartTree) -> list[RuleResult]:
    """Chamfers precede fillets in Quarantine."""
    rule = RULES[CHAMFERS_BEFORE_FILLETS]
    skip = _quarantine_skip(tree, rule)
    if skip is not None:
        return [skip]

    rows = tree.in_group(QUARANTINE)
    fillets = [row for row in rows if tree.class_of(row) == "fillet"]
    chamfers = [row for row in rows if tree.class_of(row) == "chamfer"]
    violation = None
    for fillet in fillets:
        later = [chamfer for chamfer in chamfers if chamfer.index > fillet.index]
        if later:
            violation = finding(
                rule,
                tree.document_id,
                [fillet, later[0]],
                observed=(
                    f"the fillet {fillet.name} precedes the chamfer {later[0].name} "
                    f"in {ROLES[QUARANTINE]}"
                ),
                recommended_action=(
                    f"Move the chamfers ahead of the fillets in {ROLES[QUARANTINE]}."
                ),
            )
            break
    return _verdict(
        rule, tree, violation=violation, passing=_ordered([*fillets, *chamfers])
    )


def _quarantine_skip(tree: PartTree, rule: RmsRule) -> RuleResult | None:
    """The skip the three Quarantine-content rules share, worded as the contract words it."""
    if not tree.has_group(QUARANTINE):
        return skipped(rule, tree.document_id, f"no {ROLES[QUARANTINE]} group")
    if not tree.in_group(QUARANTINE):
        return skipped(rule, tree.document_id, f"{ROLES[QUARANTINE]} is empty")
    return None


# --- rms.quarantine.largest_fillet_first ------------------------------------------


@bind(LARGEST_FILLET_FIRST)
def largest_fillet_first(tree: PartTree) -> list[RuleResult]:
    """Fillet radii in Quarantine are non-increasing.

    Radii are compared in mm through `swreview.units` and reported in the unit they were
    stored in (constitution Principle II). A fillet whose radius is unreadable - a
    variable fillet, or a failed read - is unresolved rather than assumed to fit
    wherever it sits; with fewer than two readable radii there is no order to check at
    all and the rule skips, naming them.
    """
    rule = RULES[LARGEST_FILLET_FIRST]
    if not tree.has_group(QUARANTINE):
        return [skipped(rule, tree.document_id, f"no {ROLES[QUARANTINE]} group")]

    fillets = [row for row in tree.in_group(QUARANTINE) if tree.class_of(row) == "fillet"]
    readable = [
        row for row in fillets if row.fillet is not None and row.fillet.default_radius is not None
    ]
    unknown = [
        (row, "fillet radius unreadable")
        for row in fillets
        if row.fillet is None or row.fillet.default_radius is None
    ]
    if len(readable) < 2:
        reason = f"fewer than two readable fillet radii in {ROLES[QUARANTINE]}"
        if unknown:
            reason = f"{reason}; {subject_reasons(unknown)}"
        return [skipped(rule, tree.document_id, reason)]

    growing = [
        (before, after)
        for before, after in pairwise(readable)
        if _radius_mm(after) > _radius_mm(before)
    ]
    violation = None
    if growing:
        violation = finding(
            rule,
            tree.document_id,
            _ordered([row for pair in growing for row in pair]),
            observed="; ".join(
                f"{after.name} {_radius_text(after)} follows the smaller "
                f"{before.name} {_radius_text(before)}"
                for before, after in growing
            ),
            recommended_action=(
                f"Order the {ROLES[QUARANTINE]} fillets largest radius first."
            ),
        )
    return _verdict(rule, tree, violation=violation, passing=readable, unknown=unknown)


def _radius_mm(row: Feature) -> float:
    assert row.fillet is not None and row.fillet.default_radius is not None
    return units.as_mm(row.fillet.default_radius)


def _radius_text(row: Feature) -> str:
    assert row.fillet is not None and row.fillet.default_radius is not None
    radius = row.fillet.default_radius
    return f"{radius.value} {radius.unit}"


# --- rms.quarantine.only_fillets_and_chamfers -------------------------------------


@bind(ONLY_FILLETS_AND_CHAMFERS)
def only_fillets_and_chamfers(tree: PartTree) -> list[RuleResult]:
    """Quarantine holds only fillets and chamfers."""
    rule = RULES[ONLY_FILLETS_AND_CHAMFERS]
    skip = _quarantine_skip(tree, rule)
    if skip is not None:
        return [skip]

    unknown: list[tuple[Feature, str]] = []
    offenders: list[Feature] = []
    passing: list[Feature] = []
    for row in tree.in_group(QUARANTINE):
        kind = tree.class_of(row)
        if kind in UNCLASSIFIED:
            unknown.append((row, f"class of {row.type_name} is {kind}"))
        elif kind in ("fillet", "chamfer"):
            passing.append(row)
        else:
            offenders.append(row)

    violation = None
    if offenders:
        violation = finding(
            rule,
            tree.document_id,
            offenders,
            observed=(
                f"{ROLES[QUARANTINE]} holds {len(offenders)} feature(s) that are neither "
                f"fillet nor chamfer: {_typed(offenders)}"
            ),
            recommended_action=(
                f"Move anything that is not a fillet or a chamfer out of "
                f"{ROLES[QUARANTINE]}."
            ),
        )
    return _verdict(rule, tree, violation=violation, passing=passing, unknown=unknown)


# --- rms.refs.direction -----------------------------------------------------------


@bind(REFS_DIRECTION)
def refs_direction(tree: PartTree) -> list[RuleResult]:
    """No feature is depended on by a feature in an earlier group.

    A feature outside every group has no place in the order, so it is not compared here:
    `rms.grouping.all_features_in_a_group` is the rule that reports it. Its children are
    still an input this rule wanted, so the unresolved half is every content feature
    whose `child_ids` is null, grouped or not, as the contract words it.
    """
    rule = RULES[REFS_DIRECTION]
    grouped = [row for row in tree.content if tree.group_of(row) is not None]
    unknown = _children_unavailable(tree.content)
    readable = [row for row in grouped if row.child_ids is not None]

    pairs: list[tuple[Feature, Feature]] = []
    for row in readable:
        rank = tree.rank_of(row)
        assert rank is not None
        for dependent in _dependents(tree, row):
            dependent_rank = tree.rank_of(dependent)
            if dependent_rank is not None and dependent_rank < rank:
                pairs.append((row, dependent))

    violation = None
    if pairs:
        violation = finding(
            rule,
            tree.document_id,
            _ordered([row for pair in pairs for row in pair]),
            observed="; ".join(
                f"{dependent.name} in {tree.group_of(dependent)} depends on "
                f"{row.name} in {tree.group_of(row)}"
                for row, dependent in pairs
            ),
            recommended_action=(
                "Reorder the features so that every dependency points at an earlier group."
            ),
        )
    return _verdict(rule, tree, violation=violation, passing=readable, unknown=unknown)


# --- rms.refs.quarantine_has_no_children ------------------------------------------


@bind(QUARANTINE_HAS_NO_CHILDREN)
def quarantine_has_no_children(tree: PartTree) -> list[RuleResult]:
    """Nothing depends on a Quarantine feature."""
    rule = RULES[QUARANTINE_HAS_NO_CHILDREN]
    if not tree.has_group(QUARANTINE):
        return [skipped(rule, tree.document_id, f"no {ROLES[QUARANTINE]} group")]

    rows = tree.in_group(QUARANTINE)
    unknown = _children_unavailable(rows)
    readable = [row for row in rows if row.child_ids is not None]

    depended: list[tuple[Feature, list[Feature]]] = []
    for row in readable:
        dependents = _dependents(tree, row)
        if dependents:
            depended.append((row, dependents))

    violation = None
    if depended:
        subjects = [row for owner, dependents in depended for row in (owner, *dependents)]
        violation = finding(
            rule,
            tree.document_id,
            _ordered(subjects),
            observed="; ".join(
                f"{owner.name} in {ROLES[QUARANTINE]} is depended on by "
                f"{_named(dependents)}"
                for owner, dependents in depended
            ),
            recommended_action=(
                f"Remove the dependency, or move the feature out of {ROLES[QUARANTINE]}."
            ),
        )
    return _verdict(rule, tree, violation=violation, passing=readable, unknown=unknown)


# --- rms.detail.no_internal_references --------------------------------------------


@bind(NO_INTERNAL_REFERENCES)
def no_internal_references(tree: PartTree) -> list[RuleResult]:
    """Detail features do not depend on each other, but for the two carve-outs.

    (a) a sketch consumed by exactly one feature is the sketch that feature owns - and a
    sketch is what the extractor read as one (`Feature.sketch`), never what the type
    table recognises, so an unlisted sketch type keeps the carve-out - and
    (b) two features sharing one derived subfolder inside Detail are a coupled pair the
    method allows. The subfolder is the assigner's derived one, never `Feature.folder_id`
    (`rules.md`, "Group assignment"), so two features merely loose in Detail are not a
    pair.
    """
    rule = RULES[NO_INTERNAL_REFERENCES]
    if not tree.has_group(DETAIL):
        return [skipped(rule, tree.document_id, f"no {ROLES[DETAIL]} group")]

    rows = tree.in_group(DETAIL)
    in_detail = {row.id for row in rows}
    unknown = _children_unavailable(rows)
    readable = [row for row in rows if row.child_ids is not None]

    pairs: list[tuple[Feature, Feature]] = []
    for row in readable:
        if row.sketch is not None and len(row.child_ids or ()) == 1:
            continue
        subfolder = tree.subfolder_of(row)
        for dependent in _dependents(tree, row):
            if dependent.id not in in_detail:
                continue
            if subfolder is not None and subfolder == tree.subfolder_of(dependent):
                continue
            pairs.append((row, dependent))

    violation = None
    if pairs:
        violation = finding(
            rule,
            tree.document_id,
            _ordered([row for pair in pairs for row in pair]),
            observed="; ".join(
                f"{dependent.name} depends on {row.name}, both in {ROLES[DETAIL]}"
                for row, dependent in pairs
            ),
            recommended_action=(
                "Break the reference between the Detail features, or put a coupled pair "
                "in one subfolder."
            ),
        )
    return _verdict(rule, tree, violation=violation, passing=readable, unknown=unknown)


# --- rms.intent.every_feature_described -------------------------------------------


@bind(EVERY_FEATURE_DESCRIBED)
def every_feature_described(tree: PartTree) -> list[RuleResult]:
    """Every content feature carries a description, whatever its class."""
    rule = RULES[EVERY_FEATURE_DESCRIBED]
    unknown = [
        (row, "description unreadable") for row in tree.content if row.description is None
    ]
    readable = [row for row in tree.content if row.description is not None]
    offenders = [row for row in readable if not (row.description or "").strip()]
    passing = [row for row in readable if (row.description or "").strip()]

    violation = None
    if offenders:
        violation = finding(
            rule,
            tree.document_id,
            offenders,
            observed=(
                f"{len(offenders)} content feature(s) carry no description: "
                f"{_named(offenders)}"
            ),
            recommended_action="Describe what each feature is for, not what it is.",
        )
    return _verdict(rule, tree, violation=violation, passing=passing, unknown=unknown)


# --- rms.sketches.fully_defined and rms.sketches.not_over_defined -----------------


@bind(SKETCHES_FULLY_DEFINED)
def sketches_fully_defined(tree: PartTree) -> list[RuleResult]:
    """Every sketch is fully defined; only `under_defined` fails."""
    return _sketch_status_rule(
        tree,
        RULES[SKETCHES_FULLY_DEFINED],
        failing=("under_defined",),
        recommended_action="Fully define the sketch.",
    )


@bind(SKETCHES_NOT_OVER_DEFINED)
def sketches_not_over_defined(tree: PartTree) -> list[RuleResult]:
    """No sketch is over defined or in solver error."""
    return _sketch_status_rule(
        tree,
        RULES[SKETCHES_NOT_OVER_DEFINED],
        failing=("over_defined", "solver_error"),
        recommended_action="Remove the conflicting relations or dimensions.",
    )


def _sketch_status_rule(
    tree: PartTree,
    rule: RmsRule,
    *,
    failing: Sequence[str],
    recommended_action: str,
) -> list[RuleResult]:
    """The half the two sketch-status rules share: which statuses this one calls a failure.

    `unavailable` (nothing was read) and `unknown` (the solver's own answer, autosolve
    off included) are unresolved for both rules; neither is ever a defined sketch.
    """
    unknown: list[tuple[Feature, str]] = []
    graded: list[tuple[Feature, str]] = []
    for row in _sketches(tree):
        assert row.sketch is not None
        status = tree.table.constrained_status(row.sketch.raw_status)
        if status in ("unknown", "unavailable"):
            unknown.append((row, f"sketch constrained status is {status}"))
        else:
            graded.append((row, status))

    offenders = [row for row, status in graded if status in failing]
    passing = [row for row, status in graded if status not in failing]
    violation = None
    if offenders:
        violation = finding(
            rule,
            tree.document_id,
            _sketch_subjects(tree, offenders),
            observed="; ".join(
                f"{row.name} constrained status is {status}"
                for row, status in graded
                if status in failing
            ),
            recommended_action=recommended_action,
        )
    return _verdict(
        rule,
        tree,
        violation=violation,
        passing=_sketch_subjects(tree, passing),
        unknown=unknown,
    )


# --- rms.sketches.one_sketch_per_feature ------------------------------------------


@bind(ONE_SKETCH_PER_FEATURE)
def one_sketch_per_feature(tree: PartTree) -> list[RuleResult]:
    """No sketch is consumed by more than one feature; no consumer at all passes."""
    rule = RULES[ONE_SKETCH_PER_FEATURE]
    sketches = _sketches(tree)
    unknown = [
        (row, "sketch consumers unavailable")
        for row in sketches
        if row.sketch is not None and row.sketch.consumer_ids is None
    ]
    readable = [
        row for row in sketches if row.sketch is not None and row.sketch.consumer_ids is not None
    ]
    offenders = [row for row in readable if len(row.sketch.consumer_ids or ()) > 1]
    passing = [row for row in readable if len(row.sketch.consumer_ids or ()) <= 1]

    violation = None
    if offenders:
        violation = finding(
            rule,
            tree.document_id,
            _sketch_subjects(tree, offenders),
            observed="; ".join(
                f"{row.name} is consumed by {len(row.sketch.consumer_ids or ())} features: "
                f"{_named(_consumers(tree, row))}"
                for row in offenders
            ),
            recommended_action="Give each feature its own sketch.",
        )
    return _verdict(
        rule,
        tree,
        violation=violation,
        passing=_sketch_subjects(tree, passing),
        unknown=unknown,
    )


# --- rms.detail.individually_suppressible (US4) -----------------------------------


SUPPRESS_SKIPPED: frozenset[str] = frozenset({"already_suppressed", "truncated"})
"""The two row outcomes that are not an answer about the feature: it was already
suppressed before the run, or the run never reached it (`rules.md`, outcome table)."""

SUPPRESS_ANSWERED: frozenset[str] = frozenset({"ok", "rebuild_errors"})
"""The two row outcomes that answer the rule's question for a feature - it was suppressed
alone and the rebuild either held or did not. Every other outcome leaves the feature
ungraded, so only these count as `tested` in the coverage line."""


def _suppress_coverage(tested: int, present: int, unused: Sequence[SuppressTestRow]) -> str:
    """The coverage line the outcome table requires of every reason this rule writes.

    `present` is the Detail content set of the tree - the same set `suppress-plan` writes
    - and `tested` the features of it the run answered for (`SUPPRESS_ANSWERED`), so a run
    cut short by `--limit`, or one that walked past a feature that was already suppressed,
    reads as the partial answer it is. A feature the run did not answer for stays visible
    as not covered rather than being folded into the count, because the same reason often
    names it as skipped or unresolved in the same sentence. A row naming a feature that is
    not in that set is ignored by the grading and named here instead, because a plan row
    the package no longer recognises must be reported and not dropped (`spec.md`, edge
    cases).
    """
    line = f"suppress-test tested {tested}/{present} {ROLES[DETAIL]} content feature(s)"
    if not unused:
        return line
    listed = ", ".join(f"{row.feature_id} {row.name}" for row in unused)
    return (
        f"{line}; {len(unused)} run row(s) unused, "
        f"not {ROLES[DETAIL]} content in this package: {listed}"
    )


def _rebuild_errors(row: Feature, tried: SuppressTestRow) -> str:
    """One failing feature's count and messages, as an engineer would read them."""
    messages = ", ".join(tried.messages) if tried.messages else "no message recorded"
    if tried.messages_truncated:
        messages += f" (+{tried.messages_truncated} more)"
    return f"{row.name}: {tried.whats_wrong_count} rebuild error(s) after suppression: {messages}"


@bind(INDIVIDUALLY_SUPPRESSIBLE)
def individually_suppressible(tree: PartTree) -> list[RuleResult]:
    """Each Detail feature can be suppressed alone without rebuild errors.

    The outcome table of `contracts/rules.md` in full, graded per Detail content feature
    of *the tree* rather than per row of the run: the run is evidence about the features
    the method holds to this rule, not the list of them, so a row the package no longer
    recognises is unused and a feature with no row is `not tested`, never a pass.

    Unlike the other per-subject rules this one does not use `_verdict`: a fail here does
    not replace the passes, because one fragile Detail feature says nothing about the
    others and the expected report of `quickstart.md` scenario 1 names both buckets for
    the same document. Every reason it writes for a document with a run ends with the
    coverage line, and when the run left nothing else to explain that line is a `skip` of
    its own, so `<tested>/<present>` is never absent from the report.
    """
    rule = RULES[INDIVIDUALLY_SUPPRESSIBLE]
    if not tree.has_group(DETAIL):
        return [skipped(rule, tree.document_id, f"no {ROLES[DETAIL]} group")]
    rows = tree.in_group(DETAIL)
    if not rows:
        return [skipped(rule, tree.document_id, f"{ROLES[DETAIL]} holds no content feature")]

    run = tree.package.rms_suppress_test
    if run is None or run.document_id != tree.document_id:
        return [unresolved(rule, tree.document_id, "no suppress-test run", rows)]

    by_feature_id = {row.feature_id: row for row in run.rows}
    planned = {row.id for row in rows}
    unused = [row for row in run.rows if row.feature_id not in planned]
    tested = sum(
        1
        for row in rows
        if row.id in by_feature_id and by_feature_id[row.id].outcome in SUPPRESS_ANSWERED
    )
    coverage = _suppress_coverage(tested, len(rows), unused)

    configuration = tree.package.design.active_configuration
    if run.configuration != configuration:
        return [
            unresolved(
                rule,
                tree.document_id,
                f"suppress-test ran in configuration {run.configuration}, "
                f"the review reads {configuration}; {coverage}",
                rows,
            )
        ]
    if not run.restore_verified:
        return [unresolved(rule, tree.document_id, f"restore not verified; {coverage}", rows)]

    failing: list[tuple[Feature, SuppressTestRow]] = []
    passing: list[Feature] = []
    skipping: list[tuple[Feature, str]] = []
    unknown: list[tuple[Feature, str]] = []
    for row in rows:
        tried = by_feature_id.get(row.id)
        if tried is None:
            unknown.append((row, "not tested"))
        elif tried.outcome == "ok":
            passing.append(row)
        elif tried.outcome == "rebuild_errors":
            # Errors reported without a count is a missing input, and a missing input is
            # never a fail (constitution Principle I).
            if tried.whats_wrong_count is None:
                unknown.append((row, "rebuild_errors with no rebuild-error count"))
            else:
                failing.append((row, tried))
        elif tried.outcome in SUPPRESS_SKIPPED:
            skipping.append((row, tried.outcome))
        else:
            reason = tried.outcome if tried.error is None else f"{tried.outcome}: {tried.error}"
            unknown.append((row, reason))

    results: list[RuleResult] = []
    if failing:
        results.append(
            finding(
                rule,
                tree.document_id,
                [row for row, _ in failing],
                observed=(
                    # The feature names lead, because the first 70-odd characters of
                    # `observed` are the finding's title in the report.
                    f"{_named([row for row, _ in failing])} cannot be suppressed alone; "
                    f"run baseline {run.baseline_whats_wrong_count} rebuild error(s). "
                    + "; ".join(_rebuild_errors(row, tried) for row, tried in failing)
                ),
                recommended_action=(
                    f"Rework the listed {ROLES[DETAIL]} feature(s) so each can be suppressed "
                    "on its own - remove the references that break the rebuild - and re-run "
                    "the suppress-test."
                ),
            )
        )
    if passing:
        results.append(passed(rule, tree.document_id, passing))
    if skipping:
        results.append(
            skipped(
                rule,
                tree.document_id,
                f"{subject_reasons(skipping)}; {coverage}",
                [row for row, _ in skipping],
            )
        )
    if unknown:
        results.append(
            unresolved(
                rule,
                tree.document_id,
                f"{subject_reasons(unknown)}; {coverage}",
                [row for row, _ in unknown],
            )
        )
    if not skipping and not unknown:
        results.append(skipped(rule, tree.document_id, coverage))
    return results


# --- the whole document -----------------------------------------------------------


def evaluate_part(
    document_id: str,
    features: Sequence[Feature],
    table: RmsTypeTable,
    assignment: GroupAssignment,
    package: EvidencePackage,
) -> list[RuleResult]:
    """Every part-scope rule over one part document, in the contract's order.

    A document whose tree was never read - no `features[]` rows and no resolved component
    instance - is not evaluated feature by feature: every part-scope *and* equation-scope
    rule is unresolved for it, naming the component state, because the equation rules
    read the same document and would otherwise report "no global variable" about a tree
    nobody opened (`rules.md`, "Unresolved part documents").
    """
    tree = part_tree(document_id, features, table, assignment, package)
    not_read = tree_not_read(document_id, tree.rows, package)
    if not_read is not None:
        return [
            unresolved(rule, document_id, not_read)
            for rule in evaluable()
            if rule.scope in (SCOPE, "equations")
        ]

    results: list[RuleResult] = []
    for rule in evaluable():
        if rule.scope != SCOPE:
            continue
        if rule.fn is None:  # pragma: no cover - this module binds every part rule
            raise RuntimeError(f"{rule.id} has no evaluator")
        results.extend(rule.fn(tree))
    return results


def tree_not_read(
    document_id: str, rows: Sequence[Feature], package: EvidencePackage
) -> str | None:
    """Why this document's tree is unreadable, or `None` when it was read.

    The contract's condition is both halves at once: no rows *and* no resolved instance.
    A document with one resolved instance is evaluated normally however many of its other
    instances are lightweight, suppressed or unloaded.

    A resolved instance is not on its own proof that the tree was read, though: the
    extractor also drops a document's rows whole when its configuration, its walk, its
    indexing or one feature's persistent reference could not be read, and `--features none`
    reads no tree at all. Each of those records a `feature_tree_unavailable` gap, and
    without consulting it an empty `features[]` would be graded as an empty tree - six
    fail-severity rules passing over a tree nobody opened (constitution Principle I).

    Public because `equations.py` asks the same question of the same document: "Unresolved
    part documents" holds for every part-scope *and* every equation-scope rule, and one
    reading of it is what keeps the two scopes from disagreeing about one document.
    """
    if rows:
        return None
    instances = [
        component for component in package.components if component.document_id == document_id
    ]
    if any(component.suppression == "resolved" for component in instances):
        return document_gap(package, "feature_tree_unavailable", document_id)
    if not instances:
        return f"no component instance for {document_id}; tree not read"
    return "; ".join(
        f"component {component.full_path} {component.suppression}; tree not read"
        for component in instances
    )


def document_gap(package: EvidencePackage, entity_kind: str, document_id: str) -> str | None:
    """The reason a recorded `entity_kind` gap gives for `document_id`'s data being absent.

    The extractor names the document when the data it dropped was this document's, and
    names nothing when the phase read nothing at all (`--features none`, `--equations
    off`). A gap naming some other entity - a component, a feature - speaks for that
    entity and not for the document: `feature_tree_unavailable` naming a *component* is
    the per-instance state gap, which `tree_not_read` has already ruled out by finding a
    resolved instance.
    """
    for gap in package.gaps:
        if gap.entity_kind == entity_kind and gap.entity_id in (None, document_id):
            return gap.reason
    return None
