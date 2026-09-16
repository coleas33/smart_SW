"""The four assembly-scope rule evaluators, `MateGraph` and `evaluate_assembly` (T033).

One pure function per evaluable assembly rule of `specs/003-resilient-modeling/
contracts/rules.md`, each decorated `@bind("<rule id>")` and returning `list[RuleResult]` -
one result per outcome it reaches, exactly as `part.py` does, so a rule that fails on one
mate and cannot read another lands in two buckets of the report rather than averaging them.

Three conventions decide what these rules may look at, and each is one of the contract's
normative paragraphs rather than a style choice:

- **the root assembly document only.** `MateDumper` walks the root document's feature tree
  and `Mate` carries no owning document, so every result names
  `design.root_assembly_document_id`. Subassembly documents are never subject documents
  here; they surface once per review through the coverage-only rule
  `rms.assembly.subassemblies`, which `report.py` writes as an undispatched item
  (`rules.md`, "Assembly scope").
- **a missing input is unresolved for that subject, never a pass and never a fail**
  (constitution Principle I). An entity kind in neither table list - a sketch entity, or
  the dumper's `unknown(<n>)` fallback - a mate one of whose entities the dumper could not
  read, a constrained status that was never read, a mate whose suppression could not be
  read, a component the graph cannot reach, and a component whose Toolbox identity could
  not be read are each unresolved for that subject.
- **the two entity-kind lists and the chain limit come from `rms_types.yaml`.** No rule
  spells a `swSelType_e` name or a depth of its own; the table is the calibrated data and
  `AssemblyTable` is how a rule reads it.

**Subjects.** A finding's inputs are `<id> <name> [<type_name>] persist_ref=<ref>
scope=<document_id>` for a feature, a mate *or* a component (data-model section 2), and
`results.py` builds every one of them. The IR's `Mate` and `ComponentInstance` are not
`Feature`s and carry no `name`/`type_name` pair, so `Subject` below presents each of them
in that shape - the one place in this module that decides a mate is labelled by its mate
type and a component by its full instance path. Nothing is invented: every field is read
off the IR row.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from swreview.checks.rms.registry import RULES, RmsRule, bind, evaluable
from swreview.checks.rms.results import (
    RuleResult,
    finding,
    passed,
    skipped,
    subject_reasons,
    unresolved,
)
from swreview.checks.rms_types import ConstrainedStatus, RmsTypeTable
from swreview.ir.models import ComponentInstance, EvidencePackage, Mate

__all__ = [
    "Assembly",
    "MateGraph",
    "Subject",
    "assembly_rules_unresolved",
    "assembly_tree",
    "evaluate_assembly",
    "first_component_fixed",
    "mate_chain_depth",
    "mates_to_reference_geometry",
    "toolbox_parts_not_configurations",
]

SCOPE = "assembly"

MATES_TO_REFERENCE_GEOMETRY = "rms.assembly.mates_to_reference_geometry"
FIRST_COMPONENT_FIXED = "rms.assembly.first_component_fixed"
MATE_CHAIN_DEPTH = "rms.assembly.mate_chain_depth"
TOOLBOX_PARTS_NOT_CONFIGURATIONS = "rms.assembly.toolbox_parts_not_configurations"

NO_MATES = "the root assembly has no mates"
NO_CHILDREN = "the root assembly has no child components"
NO_FIXED_CHILD = "no fixed child of the root assembly"

CONSTRAINED_PASSES: frozenset[ConstrainedStatus] = frozenset({"fully_defined"})
CONSTRAINED_FAILS: frozenset[ConstrainedStatus] = frozenset(
    {"under_defined", "over_defined", "solver_error"}
)
"""How `rms.assembly.first_component_fixed` reads a component's constrained status
(`rules.md`, assembly scope). Everything else - `unknown` and `unavailable` - is neither,
and is unresolved."""

MATE_SUPPRESSION_GAP = "mate_suppression"
"""`MateDumper` records this gap, keyed by the mate id, when `IsSuppressed2` was
unreadable; `Mate.suppressed` is then `false` on failure, so the flag alone cannot be
trusted and the mate is not an edge."""

MATE_GAP_ENTITY_KIND = "mate"
MATE_ENTITY_GAP_PREFIX = "read entity "
"""How a partly read entity list is recognised. `MateDumper.ReadEntities` wraps each entity
in `Gaps.TryStep("mate", <mate id>, "read entity <i> of mate '<name>'")`, so a failed read
leaves that entity out of `Mate.entities` and records this gap under the mate's own id -
the reason is what tells it apart from the two other `mate`-kind gaps keyed to a mate (no
persistent reference, and a distance or angle value that was not read), which say nothing
about the entity list and must not make every distance mate unresolved. Matched as a
prefix, because `TryStep` records the step description verbatim as the reason."""

TOOLBOX_GAP_ENTITY_KIND = "component"
TOOLBOX_GAP_MARKER = "Toolbox identity"
"""How a Toolbox-identity gap is recognised. `ComponentTreeDumper.ReadIsToolbox` records
it with *no* `entity_id` and names the component's `IComponent2.Name2` key - which is
`ComponentInstance.full_path` - in single quotes inside the reason, so the reason is the
only link back to the component and the quotes are what keep `'screw-1'` from matching
`'gearbox-1/screw-1b'`. `is_toolbox` is false-on-failure in the dumper, so without this
the rule would read an unreadable component as "not Toolbox" (research R4)."""


# --- the subjects a rule names ----------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """A mate or a component instance in the shape `results.py` renders a subject in.

    Structural, not nominal: `passed`, `skipped`, `unresolved` and `finding` read exactly
    these seven attributes off a subject and are annotated `Feature` because the part
    rules were written first. Duplicating those constructors for two more row types would
    be the second mechanism this feature exists to avoid (constitution Principle V).
    """

    id: str
    name: str
    type_name: str
    persist_ref: str
    persist_ref_scope: str
    suppressed: bool
    configuration: str


def _mate_subject(mate: Mate, configuration: str) -> Subject:
    """A mate as a subject: the IR carries no mate name, so its type is the label."""
    return Subject(
        id=mate.id,
        name=mate.type,
        type_name="mate",
        persist_ref=mate.persist_ref,
        persist_ref_scope=mate.persist_ref_scope,
        suppressed=mate.suppressed,
        configuration=configuration,
    )


def _component_subject(component: ComponentInstance, configuration: str) -> Subject:
    """A component instance as a subject, labelled by the path that is unique in the
    assembly. Only a `suppressed` component is suppressed: `lightweight` and `unloaded`
    are states of the load, not of the configuration, and are said in the reason instead."""
    return Subject(
        id=component.id,
        name=component.full_path,
        type_name="component",
        persist_ref=component.persist_ref,
        persist_ref_scope=component.persist_ref_scope,
        suppressed=component.suppression == "suppressed",
        configuration=configuration,
    )


# --- the mate graph ---------------------------------------------------------------


@dataclass(frozen=True)
class MateGraph:
    """The root assembly's components and the mates that join them (`rules.md`,
    `rms.assembly.mate_chain_depth`).

    Nodes are every component instance except the root assembly's own (`cmp:0001` is the
    document, not something mated to it); edges are the root mates whose suppression is
    both readable and false, a mate joining every pair of distinct instances its entities
    name. A suppressed mate is not an edge, and neither is a mate whose suppression could
    not be read: its `suppressed` flag is false-on-failure, so treating it as active could
    report a component as three mates from the root when it is not connected at all.
    """

    nodes: tuple[ComponentInstance, ...]
    neighbours: Mapping[str, tuple[str, ...]]
    roots: tuple[ComponentInstance, ...]
    """The fixed children of the root instance, in package order; the first is the chain
    root and the rest are named in the finding."""

    unreadable: tuple[Mate, ...]
    """The mates whose suppression was not readable, in package order."""

    @classmethod
    def of(cls, package: EvidencePackage) -> MateGraph:
        """Build the graph of one package's root assembly."""
        root = _root_instance(package)
        root_id = None if root is None else root.id
        nodes = tuple(row for row in package.components if row.id != root_id)
        known = {row.id for row in nodes}

        unreadable_ids = {
            gap.entity_id
            for gap in package.gaps
            if gap.entity_kind == MATE_SUPPRESSION_GAP and gap.entity_id is not None
        }
        unreadable = tuple(row for row in package.mates if row.id in unreadable_ids)

        adjacency: dict[str, list[str]] = {row.id: [] for row in nodes}
        for mate in package.mates:
            if mate.suppressed or mate.id in unreadable_ids:
                continue
            joined: list[str] = []
            for entity in mate.entities:
                if entity.component_id in known and entity.component_id not in joined:
                    joined.append(entity.component_id)
            for one in joined:
                for other in joined:
                    if one != other and other not in adjacency[one]:
                        adjacency[one].append(other)

        return cls(
            nodes=nodes,
            neighbours={node: tuple(edges) for node, edges in adjacency.items()},
            roots=tuple(row for row in nodes if row.parent_id == root_id and row.is_fixed),
            unreadable=unreadable,
        )

    def depths(self) -> dict[str, int]:
        """How many mates each reachable node is from the chain root, breadth-first.

        Empty when there is no fixed child: without a root the method's question - how far
        is this component from what holds the assembly still - has no answer at all.
        """
        if not self.roots:
            return {}
        start = self.roots[0].id
        depths = {start: 0}
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            for neighbour in self.neighbours.get(current, ()):
                if neighbour not in depths:
                    depths[neighbour] = depths[current] + 1
                    queue.append(neighbour)
        return depths


def _root_instance(package: EvidencePackage) -> ComponentInstance | None:
    """The root assembly's own instance (`cmp:0001`): the top-level instance of the root
    assembly document. Found by what it is rather than by its id, because an id is an
    allocation of the extractor and the document is the contract."""
    root_document = package.design.root_assembly_document_id
    return next(
        (
            row
            for row in package.components
            if row.parent_id is None and row.document_id == root_document
        ),
        None,
    )


# --- what a rule reads ------------------------------------------------------------


@dataclass(frozen=True)
class Assembly:
    """One root assembly, with the answers every rule would otherwise recompute.

    Built once by `assembly_tree` and handed to each rule, the way `PartTree` is: a rule's
    signature then says exactly what a rule may read, and the graph is walked once.
    """

    document_id: str
    configuration: str
    package: EvidencePackage
    table: RmsTypeTable
    root: ComponentInstance | None
    children: tuple[ComponentInstance, ...]
    """The instances whose `parent_id` is the root instance, in package order."""

    instances: tuple[ComponentInstance, ...]
    """Every instance but the root assembly's own, in package order."""

    by_id: Mapping[str, ComponentInstance]
    mates: tuple[Mate, ...]
    graph: MateGraph

    def mate(self, row: Mate) -> Subject:
        return _mate_subject(row, self.configuration)

    def component(self, row: ComponentInstance) -> Subject:
        return _component_subject(row, self.configuration)

    def joined_by(self, row: Mate) -> list[ComponentInstance]:
        """The instances a mate's entities name, each once, in entity order."""
        joined: list[ComponentInstance] = []
        seen: set[str] = set()
        for entity in row.entities:
            component = self.by_id.get(entity.component_id)
            if component is not None and component.id not in seen:
                seen.add(component.id)
                joined.append(component)
        return joined

    def mate_subjects(self, row: Mate) -> list[Subject]:
        """The contract's "mate and its components", in that order."""
        return [self.mate(row), *(self.component(item) for item in self.joined_by(row))]


def assembly_tree(package: EvidencePackage, table: RmsTypeTable) -> Assembly:
    """Index one package's root assembly for the rules."""
    root = _root_instance(package)
    instances = tuple(row for row in package.components if root is None or row.id != root.id)
    return Assembly(
        document_id=package.design.root_assembly_document_id,
        configuration=package.design.active_configuration,
        package=package,
        table=table,
        root=root,
        children=tuple(
            row for row in instances if root is not None and row.parent_id == root.id
        ),
        instances=instances,
        by_id={row.id: row for row in instances},
        mates=tuple(package.mates),
        graph=MateGraph.of(package),
    )


# --- shared shapes ----------------------------------------------------------------


def _verdict(
    rule: RmsRule,
    document_id: str,
    *,
    violation: RuleResult | None = None,
    passing: Sequence[Subject] = (),
    unknown: Sequence[tuple[Subject, str]] = (),
) -> list[RuleResult]:
    """The outcomes of a per-subject rule: at most one verdict, plus the unresolved half.

    The same shape as `part._verdict` - a violation replaces the pass, and a rule whose
    every subject was unresolved does not also report a pass - over subjects that are
    mates and components rather than features. A shared home for it would be `results.py`,
    which this task does not own.
    """
    results: list[RuleResult] = []
    if violation is not None:
        results.append(violation)
    elif passing or not unknown:
        results.append(passed(rule, document_id, passing))
    if unknown:
        results.append(
            unresolved(
                rule,
                document_id,
                subject_reasons(unknown),
                [subject for subject, _ in unknown],
            )
        )
    return results


def _paths(rows: Sequence[ComponentInstance]) -> str:
    return ", ".join(row.full_path for row in rows)


def _mates_with_unread_entities(package: EvidencePackage) -> frozenset[str]:
    """The ids of the mates whose `entities` is missing an entity the dumper could not
    read. The same shape as `MateGraph`'s suppression-gap lookup: the gap names the mate,
    so what the gap withholds is unresolved for that mate rather than assumed away."""
    return frozenset(
        gap.entity_id
        for gap in package.gaps
        if gap.entity_kind == MATE_GAP_ENTITY_KIND
        and gap.entity_id is not None
        and gap.reason.startswith(MATE_ENTITY_GAP_PREFIX)
    )


# --- rms.assembly.mates_to_reference_geometry -------------------------------------


@bind(MATES_TO_REFERENCE_GEOMETRY)
def mates_to_reference_geometry(tree: Assembly) -> list[RuleResult]:
    """Mates reference planes, axes, points or coordinate systems, not faces, edges or
    vertices.

    A geometry kind is evidence of the violation, so a mate carrying one fails however its
    other entities read: it is reported `fail` and *not* also unresolved, because a kind
    nobody could classify and an entity nobody could read leave nothing open once the face
    is in hand. A mate with no geometry kind passes only when every entity is a reference
    kind *and* every entity was read - the table's two lists are not exhaustive, so an
    unlisted kind is a question, and an entity the dumper dropped
    (`MATE_ENTITY_GAP_PREFIX`) may have been the face that violates the rule.
    """
    rule = RULES[MATES_TO_REFERENCE_GEOMETRY]
    if not tree.mates:
        return [skipped(rule, tree.document_id, NO_MATES)]

    reference = frozenset(tree.table.assembly.reference_entity_kinds)
    geometry = frozenset(tree.table.assembly.geometry_entity_kinds)
    incomplete = _mates_with_unread_entities(tree.package)

    offenders: list[Subject] = []
    observed: list[str] = []
    passing: list[Subject] = []
    unknown: list[tuple[Subject, str]] = []
    for mate in tree.mates:
        on_geometry = [entity for entity in mate.entities if entity.entity_kind in geometry]
        unlisted = sorted(
            {
                entity.entity_kind
                for entity in mate.entities
                if entity.entity_kind not in geometry and entity.entity_kind not in reference
            }
        )
        if on_geometry:
            offenders.extend(tree.mate_subjects(mate))
            named = ", ".join(
                f"{entity.entity_kind} on "
                f"{tree.by_id[entity.component_id].full_path}"
                if entity.component_id in tree.by_id
                else entity.entity_kind
                for entity in on_geometry
            )
            observed.append(f"{mate.id} ({mate.type}) references {named}")
            continue

        reasons: list[str] = []
        if mate.id in incomplete:
            reasons.append("entity list incomplete: an entity of this mate was not read")
        if unlisted:
            reasons.append(
                f"entity kind(s) {', '.join(unlisted)} are in neither the reference "
                f"nor the geometry list"
            )
        if reasons:
            subjects = tree.mate_subjects(mate)
            unknown.append((subjects[0], "; ".join(reasons)))
            unknown.extend((subject, "on that mate") for subject in subjects[1:])
        else:
            passing.extend(tree.mate_subjects(mate))

    violation = None
    if offenders:
        violation = finding(
            rule,
            tree.document_id,
            offenders,
            observed="; ".join(observed),
            recommended_action=(
                "Re-mate to reference planes, axes, points or coordinate systems so the "
                "mates survive a change to the faces and edges they sit on."
            ),
        )
    return _verdict(rule, tree.document_id, violation=violation, passing=passing, unknown=unknown)


# --- rms.assembly.first_component_fixed -------------------------------------------


@bind(FIRST_COMPONENT_FIXED)
def first_component_fixed(tree: Assembly) -> list[RuleResult]:
    """The first component is fixed, or fully constrained.

    The subject is the first child of the root instance in package order - a component
    nested in a subassembly is not a child of the root, and a fixed component further down
    the list does not answer for the first one.
    """
    rule = RULES[FIRST_COMPONENT_FIXED]
    if not tree.children:
        return [skipped(rule, tree.document_id, NO_CHILDREN)]

    first = tree.children[0]
    subject = tree.component(first)
    if first.is_fixed:
        return [passed(rule, tree.document_id, [subject])]

    status = tree.table.constrained_status(first.constrained_status_raw)
    if status in CONSTRAINED_PASSES:
        return [passed(rule, tree.document_id, [subject])]
    if status not in CONSTRAINED_FAILS:
        return [
            unresolved(
                rule,
                tree.document_id,
                subject_reasons(
                    [(subject, f"not fixed and the constrained status is {status}")]
                ),
                [subject],
            )
        ]
    return [
        finding(
            rule,
            tree.document_id,
            [subject],
            observed=f"the first component {first.full_path} is not fixed and is {status}",
            recommended_action=(
                "Fix the first component, or fully constrain it against the assembly's "
                "reference geometry, so the rest of the assembly has something to build on."
            ),
        )
    ]


# --- rms.assembly.mate_chain_depth ------------------------------------------------


@bind(MATE_CHAIN_DEPTH)
def mate_chain_depth(tree: Assembly) -> list[RuleResult]:
    """No component is more than `mate_chain_depth_limit` mates from the fixed root.

    Breadth-first from the first fixed child of the root instance over the mates that are
    known to be active. A component the walk does not reach - no mates of its own, a
    disconnected graph, or a path that runs only through a suppressed or unreadable mate -
    is unresolved rather than deep: how far it is from the root is exactly what could not
    be established.
    """
    rule = RULES[MATE_CHAIN_DEPTH]
    if not tree.mates:
        return [skipped(rule, tree.document_id, NO_MATES)]

    graph = tree.graph
    unknown: list[tuple[Subject, str]] = [
        (tree.mate(mate), "suppression state not readable") for mate in graph.unreadable
    ]
    if not graph.roots:
        reasons = [NO_FIXED_CHILD]
        if unknown:
            reasons.append(subject_reasons(unknown))
        return [
            unresolved(
                rule,
                tree.document_id,
                "; ".join(reasons),
                [subject for subject, _ in unknown],
            )
        ]

    limit = tree.table.assembly.mate_chain_depth_limit
    root = graph.roots[0]
    depths = graph.depths()

    deep = [node for node in graph.nodes if depths.get(node.id, 0) > limit]
    passing = [
        tree.component(node)
        for node in graph.nodes
        if node.id in depths and depths[node.id] <= limit
    ]
    unknown.extend(
        (
            tree.component(node),
            f"not reachable from the fixed root {root.full_path} through the mates that "
            f"are known to be active",
        )
        for node in graph.nodes
        if node.id not in depths
    )

    violation = None
    if deep:
        observed = (
            f"{len(deep)} component(s) are more than {limit} mate(s) from the fixed root "
            f"{root.full_path}: "
            + ", ".join(f"{node.full_path} at {depths[node.id]}" for node in deep)
        )
        if len(graph.roots) > 1:
            observed += f"; other fixed component(s): {_paths(graph.roots[1:])}"
        violation = finding(
            rule,
            tree.document_id,
            [tree.component(node) for node in deep],
            observed=observed,
            recommended_action=(
                f"Mate these components to the fixed root or to a component nearer it, so "
                f"no chain is longer than {limit} mate(s)."
            ),
        )
    return _verdict(rule, tree.document_id, violation=violation, passing=passing, unknown=unknown)


# --- rms.assembly.toolbox_parts_not_configurations --------------------------------


@bind(TOOLBOX_PARTS_NOT_CONFIGURATIONS)
def toolbox_parts_not_configurations(tree: Assembly) -> list[RuleResult]:
    """Toolbox hardware is inserted as parts, not as configurations of one file.

    The condition is one Toolbox document carrying instances of more than one referenced
    configuration: that is the same file standing in for several sizes. A component whose
    Toolbox identity was not readable is unresolved, and its presence is what keeps the
    rule from skipping - "no Toolbox component here" would be a reading nobody took.
    """
    rule = RULES[TOOLBOX_PARTS_NOT_CONFIGURATIONS]
    unreadable = _toolbox_unreadable(tree)
    unreadable_ids = {row.id for row in unreadable}
    toolbox = [
        row for row in tree.instances if row.is_toolbox and row.id not in unreadable_ids
    ]
    if not toolbox and not unreadable:
        return [skipped(rule, tree.document_id, "no Toolbox component")]

    unknown = [
        (tree.component(row), "Toolbox identity not readable") for row in unreadable
    ]

    by_document: dict[str, list[ComponentInstance]] = {}
    for row in toolbox:
        by_document.setdefault(row.document_id, []).append(row)

    offenders: list[ComponentInstance] = []
    observed: list[str] = []
    passing: list[ComponentInstance] = []
    for document_id, rows in by_document.items():
        configurations: list[str] = []
        for row in rows:
            if row.referenced_configuration not in configurations:
                configurations.append(row.referenced_configuration)
        if len(configurations) > 1:
            offenders.extend(rows)
            observed.append(
                f"Toolbox document {document_id} is inserted as {len(configurations)} "
                f"configuration(s) ({', '.join(configurations)}) across "
                f"{len(rows)} instance(s): {_paths(rows)}"
            )
        else:
            passing.extend(rows)

    violation = None
    if offenders:
        violation = finding(
            rule,
            tree.document_id,
            [tree.component(row) for row in offenders],
            observed="; ".join(observed),
            recommended_action=(
                "Insert each Toolbox size as its own part file rather than as another "
                "configuration of one file, so a size change cannot follow every instance."
            ),
        )
    return _verdict(
        rule,
        tree.document_id,
        violation=violation,
        passing=[tree.component(row) for row in passing],
        unknown=unknown,
    )


def _toolbox_unreadable(tree: Assembly) -> list[ComponentInstance]:
    """The instances a Toolbox-identity gap names, in package order.

    The dumper records the gap with no `entity_id` and quotes the component's key in the
    reason, so the quoted `full_path` is the link back; `is_toolbox` is `false` on failure
    and must not be read for these.
    """
    reasons = [
        gap.reason
        for gap in tree.package.gaps
        if gap.entity_kind == TOOLBOX_GAP_ENTITY_KIND and TOOLBOX_GAP_MARKER in gap.reason
    ]
    if not reasons:
        return []
    return [
        row
        for row in tree.instances
        if any(f"'{row.full_path}'" in reason for reason in reasons)
    ]


# --- the evaluator ----------------------------------------------------------------


def evaluate_assembly(package: EvidencePackage, table: RmsTypeTable) -> list[RuleResult]:
    """Every evaluable assembly rule over the root assembly document, in contract order."""
    tree = assembly_tree(package, table)
    results: list[RuleResult] = []
    for rule in evaluable():
        if rule.scope != SCOPE:
            continue
        if rule.fn is None:  # pragma: no cover - this module binds every assembly rule
            raise RuntimeError(f"{rule.id} has no evaluator")
        results.extend(rule.fn(tree))
    return results


def assembly_rules_unresolved(document_id: str, reason: str) -> list[RuleResult]:
    """Every evaluable assembly rule as unresolved for `document_id`, with one reason.

    For the caller that finds there is no root assembly to grade at all: the rules are
    then unresolved rather than skipped, because "the root assembly has no mates" is a
    reading of an assembly and there is none here (constitution Principle I). The
    `document_id` is the one `design.root_assembly_document_id` names - a coverage item
    must be scoped to something, and that is the document the claim would have been about
    - so the reason is what says it is not an assembly.
    """
    return [
        unresolved(rule, document_id, reason)
        for rule in evaluable()
        if rule.scope == SCOPE
    ]
