"""The seven assembly-scope checks, and the transparency polarity (T042).

One pure function per check of `specs/006-standards-check/contracts/rules.md`, each
decorated `@bind("<check id>")` and returning `list[RuleResult]` - one result per outcome it
reaches, so a check that fails on one component, skips a suppressed one and cannot read a
third lands in three buckets of the report rather than averaging them.

Four conventions decide what these checks may look at, and each is a normative paragraph of
the contract rather than a style choice:

- **every assembly document the traversal reaches is graded**, the root assembly and every
  sub-assembly alike (difference v). The macro dropped the exploded and rebuild checks for
  sub-assemblies although its top-level versions already scanned every component at every
  level; making them document-scoped removes that inconsistency without removing coverage;
- **the immediate children only.** A component nested in a sub-assembly is that
  sub-assembly's row, not this document's, so every component check reads the instances
  whose parent instance belongs to *this* document;
- **FR-005, the instance-signal half.** A suppressed, lightweight or unloaded instance is
  not a subject of the four checks whose signal sits on the instance; it is named in that
  check's *skipped* coverage with its state. Where the signal itself could not be read the
  row is unresolved instead, because a state cannot excuse a reading nobody made. Nothing
  here resolves, loads or opens an instance to obtain evidence (FR-025, FR-044);
- **a missing input is unresolved for that subject**, never a pass and never a fail
  (FR-029). Every null reading has a reason naming what was missing and the gap the dump
  recorded beside it - or that it recorded none.

**The transparency polarity is one constant.** `TRANSPARENCY_POLARITY` is `unsettled` until
PROBE-2 answers on a real model, and while it is, `standards.assembly.not_transparent` is
unresolved for **every** component of every assembly on every run - including a component
with no appearance override, because the polarity decides how the recorded value is read for
all of them (research R2.8, SC-014, difference d). Flipping this one constant is the whole
of that probe's landing.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from swreview.checks.rms_types import ConstrainedStatus, load_table
from swreview.checks.standards.library import PrefixMatcher
from swreview.checks.standards.profile import StandardsProfile
from swreview.checks.standards.registry import RULES, bind, rules_in
from swreview.checks.standards.results import (
    MATE_PHASE_GAPS,
    NO_REBUILD_NOTE,
    RuleResult,
    Subject,
    component_subject,
    document_evidence_unresolved,
    document_subject,
    find_gap,
    finding,
    gap_note,
    mate_subject,
    outcome,
    passed,
    phase_gap_note,
    skipped,
    unresolved,
)
from swreview.checks.standards.traversal import CheckedDocument
from swreview.ir.models import ComponentInstance, Document, EvidencePackage, Mate

__all__ = [
    "TRANSPARENCY_POLARITY",
    "Assembly",
    "ChildGroup",
    "assembly_scope",
    "evaluate_assembly",
    "fully_mated",
    "mate_references",
    "not_exploded",
    "not_hidden",
    "not_transparent",
    "one_fixed",
    "rebuild_errors",
]

SCOPE = "assembly"

NOT_EXPLODED = "standards.assembly.not_exploded"
REBUILD_ERRORS = "standards.assembly.rebuild_errors"
MATE_REFERENCES = "standards.assembly.mate_references"
ONE_FIXED = "standards.assembly.one_fixed"
FULLY_MATED = "standards.assembly.fully_mated"
NOT_TRANSPARENT = "standards.assembly.not_transparent"
NOT_HIDDEN = "standards.assembly.not_hidden"

TRANSPARENCY_POLARITY = "unsettled"
"""Which recorded transparency value means transparent - **PROBE-2's one edit**.

`unsettled` until the workstation probe reads a known-transparent and a known-opaque
component on the pilot's build. Two answers are possible and they are opposite:

- `zero_is_opaque` - the SDK's reading: `0` is opaque and anything above it is transparent;
- `one_is_opaque` - the macro's reading: `1` is acceptable and every other value is not.

Guessing either way silently mislabels every component that carries an appearance override,
in one direction or the other, and neither failure is visible to an engineer reading the
result (research R2.8). So while this says `unsettled`, the check grades nothing and reports
unresolved for every component, on fixtures and on the workstation alike (FR-012, SC-014).
"""

UNSETTLED = "unsettled"
ZERO_IS_OPAQUE = "zero_is_opaque"
ONE_IS_OPAQUE = "one_is_opaque"

UNSETTLED_REASON = (
    "the transparency polarity is unsettled: PROBE-2 has not settled which recorded value "
    "means transparent on this build, so no component of any assembly can be graded against "
    "this check and none is reported as compliant"
)

NO_CHILDREN = "the document records no immediate child components"
NO_MATES = "no mates"
"""`contracts/rules.md` names this reason verbatim. Difference e: the macro dereferences a
null mate-group feature here and raises a run-time error instead."""

SUB_ASSEMBLY_MATES = (
    "the package records no mate data for the sub-assembly {name}: the dump walks only the "
    "root assembly's mate group (difference h)"
)

RESOLVED = "resolved"
HIDDEN = 0
VISIBLE = 1
VISIBILITY_UNKNOWN = -1
"""`swComponentVisibilityState_e`, named here because the extractor classifies nothing."""

UNDER_CONSTRAINED: frozenset[ConstrainedStatus] = frozenset({"under_defined"})
CONSTRAINED: frozenset[ConstrainedStatus] = frozenset({"fully_defined", "over_defined"})
"""How `standards.assembly.fully_mated` reads a component's constrained status: only
`under_defined` is a candidate for the check, and only `fully_defined` and `over_defined`
are compliant. `unknown`, `unavailable` and `solver_error` are none of the three and are
unresolved, because a component whose solver errored has no answer to give."""

FIXED_GAP = "component_fixed"
"""The gap kind that says `IComponent2.IsFixed()` could not be read.

`ComponentInstance.is_fixed` is a non-nullable bool that is `false` on a failed read, so the
flag alone cannot say "not read" and the gap is the only signal there is. No dumper records
this kind today; when one does, it records it keyed to the component id and this check
answers unresolved with no further edit (FR-029)."""

_SEPARATORS = re.compile(r"[\\/]")

ChildBucket = Literal["offends", "compliant", "skip", "unresolved"]

BUCKET_ORDER: tuple[ChildBucket, ...] = ("offends", "unresolved", "compliant", "skip")
"""How one child's occurrences are reduced to the one row it lands in, strongest first.

A sub-assembly used twice carries one instance of each of its children per occurrence, and
what these checks read sits on the **instance**: one occurrence may be hidden where the
other is shown, transparent where the other is opaque, suppressed where the other is
resolved. Keeping the first occurrence and discarding the rest would report a child whose
second occurrence is hidden as compliant - a silent pass on the defect the check exists to
find - so every occurrence is graded and the strongest answer is the child's:

- a demonstrated defect on any occurrence **is** the answer, whatever the others show;
- else a reading that was not made leaves the child unknown, and a compliant occurrence
  beside it does not clear it (FR-029);
- else a graded, compliant occurrence is the answer;
- else every occurrence was skipped, and the child is that skip.

The child is still **one** row, which is what keeps a gearbox used twice from reporting each
of its components twice, and a single fixed component inside it from reading as two (FR-003).
"""


# --- the document one set of checks is evaluated over -------------------------------------


@dataclass(frozen=True)
class ChildGroup:
    """Every occurrence of one immediate child of this assembly, in package order."""

    path: str
    """The component's name **within this assembly** - the last segment of `full_path`."""

    instances: tuple[ComponentInstance, ...]


@dataclass(frozen=True)
class ChildOutcome:
    """What one occurrence of one immediate child amounts to for one check."""

    instance: ComponentInstance
    bucket: ChildBucket
    note: str | None = None
    """The reason, for a skipped or unresolved occurrence; the observed text, for an
    offending one whose check writes it per occurrence. `None` where the check writes its
    own observed text from the rows instead."""


@dataclass(frozen=True)
class ChildRows:
    """One row per immediate child, in the shapes `outcome` takes them in."""

    offenders: tuple[ComponentInstance, ...]
    compliant: tuple[ComponentInstance, ...]
    graded: tuple[ComponentInstance, ...]
    """The offending and the compliant children together, in child order: what `one_fixed`
    reports as checked, because being fixed is not on its own a defect."""

    skips: tuple[tuple[Subject, str], ...]
    unknown: tuple[tuple[Subject, str], ...]
    notes: tuple[str, ...]
    """The observed text each offending child carries, in child order; empty for a check
    that writes its own."""


@dataclass(frozen=True)
class Assembly:
    """One graded assembly document and everything the seven checks read about it."""

    document: CheckedDocument
    row: Document
    package: EvidencePackage
    is_root: bool
    children: tuple[ChildGroup, ...]
    """The immediate children, one group per component of this assembly, in package order.

    A sub-assembly used twice is walked twice, so the package carries one instance per
    occurrence of each of its children. They are grouped here by the last segment of
    `full_path`, which is the component's name **within this assembly** and is unique in it,
    so each child is one row (FR-003) - and **every occurrence in the group is graded**,
    because the readings these checks make sit on the instance and differ between them
    (`BUCKET_ORDER`).
    """

    mates: tuple[Mate, ...]
    has_mate_data: bool
    """Whether the package records this document's mates at all. True for the root, whose
    mate group is the one the dump walks, and for any document the package happens to carry
    mates for; false for a sub-assembly, whose mate data is simply missing (difference h)."""

    matcher: PrefixMatcher
    paths: Mapping[str, str | None]
    """Every document's path, for matching a component's referenced document against the
    profile's mate-count prefixes."""

    @property
    def document_id(self) -> str:
        return self.document.document_id

    @property
    def name(self) -> str:
        return self.document.file_name or self.document.document_id

    @property
    def configuration(self) -> str:
        return self.document.configuration or ""

    def subject(self, component: ComponentInstance) -> Subject:
        return component_subject(component, self.configuration)

    def mate(self, mate: Mate) -> Subject:
        return mate_subject(mate, self.configuration)

    def itself(self) -> Subject:
        return document_subject(self.document)

    def why(self, entity_id: str, *kinds: str) -> str:
        """The gap the dump recorded for `entity_id`, or that it recorded none."""
        return gap_note(self.package, entity_id, *kinds)

    def component_path(self, component: ComponentInstance) -> str | None:
        """The path of the document `component` instantiates, or `None` if unrecorded."""
        return self.paths.get(component.document_id)

    def unsuppressed_mates(self, component: ComponentInstance) -> int:
        """How many of this document's unsuppressed mates name `component`.

        A suppressed mate constrains nothing, which the macro's own note records as a known
        limitation it did not act on (difference s).
        """
        return sum(
            1
            for mate in self.mates
            if not mate.suppressed
            and any(entity.component_id == component.id for entity in mate.entities)
        )


def assembly_scope(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> Assembly:
    """Everything the seven checks read about `document`, gathered once."""
    if document.kind != SCOPE:
        raise ValueError(
            f"{document.document_id} is a {document.kind} document; the assembly checks grade "
            f"an {SCOPE} document"
        )
    row = next(item for item in package.documents if item.document_id == document.document_id)
    mates = tuple(
        mate for mate in package.mates if mate.persist_ref_scope == document.document_id
    )
    is_root = document.document_id == package.design.root_assembly_document_id
    return Assembly(
        document=document,
        row=row,
        package=package,
        is_root=is_root,
        children=_immediate_children(package, document.document_id),
        mates=mates,
        has_mate_data=is_root or bool(mates),
        matcher=PrefixMatcher.from_profile(profile),
        paths={item.document_id: item.path or None for item in package.documents},
    )


def evaluate_assembly(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> list[RuleResult]:
    """Every assembly check over one graded assembly document, in catalogue order.

    The caller grades a document the package records a kind and a path for; a document the
    traversal reached and could not resolve is unresolved coverage for every check that
    would have applied to it, which is the report layer's row and not a result.
    """
    scope = assembly_scope(document, package, profile)
    results: list[RuleResult] = []
    for rule in rules_in(SCOPE):
        results.extend(rule.fn(scope))
    return results


def _immediate_children(
    package: EvidencePackage, document_id: str
) -> tuple[ChildGroup, ...]:
    """The instances whose parent instance is an instance of `document_id`, grouped.

    One group per component of this assembly, in the package order of its first occurrence,
    carrying **every** occurrence of it (`Assembly.children`, `BUCKET_ORDER`).
    """
    owners = {row.id for row in package.components if row.document_id == document_id}
    groups: dict[str, list[ComponentInstance]] = {}
    for row in package.components:
        if row.parent_id in owners:
            groups.setdefault(_SEPARATORS.split(row.full_path)[-1], []).append(row)
    return tuple(ChildGroup(path, tuple(rows)) for path, rows in groups.items())


def _occurrence(
    child: ComponentInstance, unreadable: Callable[[ComponentInstance], str | None]
) -> ChildOutcome | None:
    """FR-005 for one occurrence, or `None` when it is the check's to grade.

    One order for all four instance-signal checks: a reading that was not made is
    unresolved whatever the instance's state, and an instance that is not resolved is
    skipped with that state as the reason (FR-005).
    """
    why = unreadable(child)
    if why is not None:
        return ChildOutcome(child, "unresolved", why)
    if child.suppression != RESOLVED:
        return ChildOutcome(
            child,
            "skip",
            f"the instance is {child.suppression} in this configuration, so it is not part "
            "of the assembly being graded (FR-005)",
        )
    return None


def _decide(outcomes: Sequence[ChildOutcome]) -> ChildOutcome:
    """The one row a child lands in, and the occurrence that decided it (`BUCKET_ORDER`)."""
    for bucket in BUCKET_ORDER:
        found = next((item for item in outcomes if item.bucket == bucket), None)
        if found is not None:
            return found
    raise ValueError(  # pragma: no cover - a group holds at least one occurrence
        "a child group with no occurrence cannot be decided"
    )


def _grade(
    scope: Assembly,
    unreadable: Callable[[ComponentInstance], str | None],
    classify: Callable[[ComponentInstance], ChildOutcome],
) -> ChildRows:
    """One row per immediate child, whatever the number of occurrences it has.

    `unreadable` answers FR-005 for one occurrence and `classify` grades one this check may
    look at; `_decide` reduces a child's occurrences to the row it lands in.
    """
    decided: list[ChildOutcome] = []
    for group in scope.children:
        outcomes: list[ChildOutcome] = []
        for child in group.instances:
            blocked = _occurrence(child, unreadable)
            outcomes.append(classify(child) if blocked is None else blocked)
        decided.append(_decide(outcomes))

    return ChildRows(
        offenders=tuple(item.instance for item in decided if item.bucket == "offends"),
        compliant=tuple(item.instance for item in decided if item.bucket == "compliant"),
        graded=tuple(
            item.instance for item in decided if item.bucket in ("offends", "compliant")
        ),
        skips=tuple(
            (scope.subject(item.instance), item.note or "")
            for item in decided
            if item.bucket == "skip"
        ),
        unknown=tuple(
            (scope.subject(item.instance), item.note or "")
            for item in decided
            if item.bucket == "unresolved"
        ),
        notes=tuple(
            item.note for item in decided if item.bucket == "offends" and item.note
        ),
    )


# --- standards.assembly.not_exploded ------------------------------------------------------


@bind(NOT_EXPLODED)
def not_exploded(scope: Assembly) -> list[RuleResult]:
    """An assembly is not left in an exploded state (FR-007)."""
    rule = RULES[NOT_EXPLODED]
    missing = document_evidence_unresolved(scope.document)
    if missing is not None:
        return [unresolved(rule, scope.document_id, missing)]

    if scope.row.is_exploded is None:
        return [
            unresolved(
                rule,
                scope.document_id,
                f"the exploded state of {scope.name} was not read; "
                f"{scope.why(scope.document_id, 'assembly_exploded')}",
            )
        ]
    if not scope.row.is_exploded:
        return [passed(rule, scope.document_id)]
    return [
        finding(
            rule,
            scope.document_id,
            [scope.itself()],
            observed=f"{scope.name} is left in an exploded state",
            recommended_action=(
                "Collapse the exploded view in SOLIDWORKS before releasing the assembly."
            ),
        )
    ]


# --- standards.assembly.rebuild_errors ----------------------------------------------------


@bind(REBUILD_ERRORS)
def rebuild_errors(scope: Assembly) -> list[RuleResult]:
    """An assembly carries no rebuild errors, as it stood (FR-008).

    The document-level count is the reading, and per-feature error codes are **not**
    substituted for it: the document count also covers mate errors that no feature carries.
    """
    rule = RULES[REBUILD_ERRORS]
    missing = document_evidence_unresolved(scope.document)
    if missing is not None:
        return [unresolved(rule, scope.document_id, missing)]

    count = scope.row.rebuild_error_count
    if count is None:
        return [
            unresolved(
                rule,
                scope.document_id,
                f"the rebuild-error count of {scope.name} was not read, and a per-feature "
                "error code is not a substitute for it: the document count also covers mate "
                "errors that no feature carries; "
                + scope.why(scope.document_id, "rebuild_error_count"),
            )
        ]
    if count == 0:
        return [passed(rule, scope.document_id)]
    return [
        finding(
            rule,
            scope.document_id,
            [scope.itself()],
            observed=(
                f"{scope.name} carries {count} rebuild error(s); the count is as the document "
                "stood when it was read and nothing was rebuilt to obtain it"
            ),
            recommended_action=(
                "Rebuild the assembly in SOLIDWORKS, fix what it reports, and run the check "
                "again."
            ),
            coverage_limits=[NO_REBUILD_NOTE],
        )
    ]


# --- standards.assembly.mate_references ---------------------------------------------------


@bind(MATE_REFERENCES)
def mate_references(scope: Assembly) -> list[RuleResult]:
    """No mate has lost a reference (FR-009)."""
    rule = RULES[MATE_REFERENCES]
    if not scope.mates:
        if not scope.has_mate_data:
            return [
                unresolved(
                    rule, scope.document_id, SUB_ASSEMBLY_MATES.format(name=scope.name)
                )
            ]
        # An empty mate group and a mate phase the dump lost are two different facts, and
        # only the first is a skip: answering "no mates" for an assembly whose mates were
        # never read is the silent skip FR-029 forbids (`results.phase_gap`).
        lost = phase_gap_note(scope.package, scope.document_id, *MATE_PHASE_GAPS)
        if lost is not None:
            return [
                unresolved(
                    rule,
                    scope.document_id,
                    f"{scope.name} records no mates and the dump did not read its mate "
                    f"group, so whether it has any is not something this package can say; "
                    f"{lost}",
                )
            ]
        return [skipped(rule, scope.document_id, NO_MATES)]

    names = {row.id: row.full_path for row in scope.package.components}
    offenders: list[Subject] = []
    observed: list[str] = []
    passing: list[Subject] = []
    unknown: list[tuple[Subject, str]] = []
    for mate in scope.mates:
        entities = mate.entities
        unread = [
            entity for entity in entities if entity.resolution_status in (None, "unknown")
        ]
        if unread:
            unknown.append(
                (
                    scope.mate(mate),
                    "the reference of "
                    + ", ".join(
                        f"{entity.entity_kind} on "
                        + names.get(entity.component_id, entity.component_id)
                        for entity in unread
                    )
                    + f" was not read; {scope.why(mate.id, 'mate_entity_reference')}",
                )
            )
            continue
        lost = [entity for entity in entities if entity.resolution_status != RESOLVED]
        if not lost:
            passing.append(scope.mate(mate))
            continue
        offenders.append(scope.mate(mate))
        observed.append(
            f"{mate.type} mate {mate.id} resolves {len(entities) - len(lost)} of "
            f"{len(entities)} entities; "
            + ", ".join(
                f"{entity.entity_kind} on {names.get(entity.component_id, entity.component_id)} "
                "did not resolve"
                for entity in lost
            )
        )

    violation = None
    if offenders:
        violation = finding(
            rule,
            scope.document_id,
            offenders,
            observed="; ".join(observed),
            recommended_action=(
                "Open the mate in SOLIDWORKS and re-select the face, edge or reference "
                "geometry it lost, or delete the mate."
            ),
        )
    return outcome(
        rule,
        scope.document_id,
        violation=violation,
        passing=passing,
        unknown=unknown,
    )


# --- standards.assembly.one_fixed ---------------------------------------------------------


@bind(ONE_FIXED)
def one_fixed(scope: Assembly) -> list[RuleResult]:
    """At most one immediate child of an assembly is fixed (FR-010)."""
    rule = RULES[ONE_FIXED]
    if not scope.children:
        return [skipped(rule, scope.document_id, NO_CHILDREN)]

    def unreadable(component: ComponentInstance) -> str | None:
        if find_gap(scope.package, component.id, FIXED_GAP) is None:
            return None
        return f"its fixed state was not read; {scope.why(component.id, FIXED_GAP)}"

    def classify(component: ComponentInstance) -> ChildOutcome:
        return ChildOutcome(component, "offends" if component.is_fixed else "compliant")

    # One count per immediate child and not per occurrence: a sub-assembly used twice does
    # not give this assembly two grounds (FR-003, `BUCKET_ORDER`).
    rows = _grade(scope, unreadable, classify)
    fixed = rows.offenders
    violation = None
    if len(fixed) > 1:
        violation = finding(
            rule,
            scope.document_id,
            [scope.subject(component) for component in fixed],
            observed=(
                f"{len(fixed)} immediate children of {scope.name} are fixed: "
                + ", ".join(component.full_path for component in fixed)
            ),
            recommended_action=(
                "Float all but one component and mate the rest, so the assembly has one "
                "ground and the solver can move what it must."
            ),
        )
    return outcome(
        rule,
        scope.document_id,
        violation=violation,
        passing=[scope.subject(component) for component in rows.graded],
        skips=list(rows.skips),
        unknown=list(rows.unknown),
    )


# --- standards.assembly.fully_mated -------------------------------------------------------


@bind(FULLY_MATED)
def fully_mated(scope: Assembly) -> list[RuleResult]:
    """Every under-constrained component is mated, or carries its library minimum (FR-011).

    The library minimum is decided by one longest-match rule across the two mate-count
    lists (`checks/standards/library.py`), never by which list was tested first.
    """
    rule = RULES[FULLY_MATED]
    if not scope.children:
        return [skipped(rule, scope.document_id, NO_CHILDREN)]

    table = load_table()

    def unreadable(component: ComponentInstance) -> str | None:
        status = table.constrained_status(component.constrained_status_raw)
        if status not in UNDER_CONSTRAINED and status not in CONSTRAINED:
            return (
                f"its constrained status is {status}; "
                f"{scope.why(component.id, 'component_constrained_status')}"
            )
        if component.is_pattern_instance is None:
            return (
                "whether it is a pattern instance was not read, and a patterned instance is "
                "positioned by its pattern rather than by mates; "
                + scope.why(component.id, "component_pattern")
            )
        return None

    def classify(component: ComponentInstance) -> ChildOutcome:
        if component.is_pattern_instance:
            return ChildOutcome(
                component,
                "skip",
                "it is an instance of the component pattern "
                f"{component.pattern_id or '(the package records no pattern name)'}, which "
                "positions it (difference t)",
            )
        if table.constrained_status(component.constrained_status_raw) in CONSTRAINED:
            return ChildOutcome(component, "compliant")

        path = scope.component_path(component)
        if path is None:
            return ChildOutcome(
                component,
                "unresolved",
                "it is under-constrained and the package records no path for the document "
                "it instantiates, so no mate-count library prefix can be matched",
            )
        match = scope.matcher.match(path)
        if match.mate_requirement == 0:
            return ChildOutcome(
                component,
                "offends",
                f"{component.full_path} is under-constrained and matches no mate-count "
                "library prefix, so it is required to be fully mated",
            )
        if not scope.has_mate_data:
            return ChildOutcome(
                component,
                "unresolved",
                f"it is under-constrained and its path matches the "
                f"{match.mate_requirement}-mate library prefix {match.mate_prefix!r}, and "
                + SUB_ASSEMBLY_MATES.format(name=scope.name),
            )
        found = scope.unsuppressed_mates(component)
        if found >= match.mate_requirement:
            return ChildOutcome(component, "compliant")
        return ChildOutcome(
            component,
            "offends",
            f"{component.full_path} is under-constrained and carries {found} unsuppressed "
            f"mate(s), below the {match.mate_requirement} its library prefix "
            f"{match.mate_prefix!r} requires (a suppressed mate constrains nothing)",
        )

    rows = _grade(scope, unreadable, classify)
    violation = None
    if rows.offenders:
        violation = finding(
            rule,
            scope.document_id,
            [scope.subject(component) for component in rows.offenders],
            observed="; ".join(rows.notes),
            recommended_action=(
                "Mate the component fully, or add the mates its library class requires."
            ),
        )
    return outcome(
        rule,
        scope.document_id,
        violation=violation,
        passing=[scope.subject(component) for component in rows.compliant],
        skips=list(rows.skips),
        unknown=list(rows.unknown),
    )


# --- standards.assembly.not_transparent ---------------------------------------------------


@bind(NOT_TRANSPARENT)
def not_transparent(scope: Assembly) -> list[RuleResult]:
    """No component is left in a transparent state (FR-012, SC-014).

    While `TRANSPARENCY_POLARITY` is `unsettled` this grades nothing: every component of
    every assembly is unresolved, on every run, because the polarity decides how the
    recorded value is read for all of them - including one with no override at all.
    """
    rule = RULES[NOT_TRANSPARENT]
    settled = TRANSPARENCY_POLARITY != UNSETTLED
    if not scope.children:
        if settled:
            return [passed(rule, scope.document_id)]
        return [unresolved(rule, scope.document_id, UNSETTLED_REASON)]

    def unreadable(component: ComponentInstance) -> str | None:
        if component.has_appearance_override is None:
            return (
                "whether it carries a component-level appearance override was not read; "
                f"{scope.why(component.id, 'component_transparency')}"
            )
        if component.has_appearance_override and component.transparency_raw is None:
            return (
                "it carries a component-level appearance override whose transparency value "
                f"was not read; {scope.why(component.id, 'component_transparency')}"
            )
        return None

    def classify(component: ComponentInstance) -> ChildOutcome:
        if not settled:
            return ChildOutcome(component, "unresolved", UNSETTLED_REASON)
        if _is_transparent(component):
            return ChildOutcome(component, "offends")
        return ChildOutcome(component, "compliant")

    rows = _grade(scope, unreadable, classify)
    violation = None
    if rows.offenders:
        violation = finding(
            rule,
            scope.document_id,
            [scope.subject(component) for component in rows.offenders],
            observed="; ".join(
                f"{component.full_path} carries a component-level appearance override whose "
                f"recorded transparency is {component.transparency_raw}, which means "
                f"transparent under the {TRANSPARENCY_POLARITY} polarity"
                for component in rows.offenders
            ),
            recommended_action=(
                "Clear the component's appearance override so it is displayed opaque."
            ),
        )
    return outcome(
        rule,
        scope.document_id,
        violation=violation,
        passing=[scope.subject(component) for component in rows.compliant],
        skips=list(rows.skips),
        unknown=list(rows.unknown),
    )


def _is_transparent(component: ComponentInstance) -> bool:
    """Whether the recorded value means transparent under the settled polarity.

    A component with no appearance override carries no component-level transparency, so
    there is nothing for either polarity to call transparent.
    """
    if not component.has_appearance_override or component.transparency_raw is None:
        return False
    value = component.transparency_raw
    if TRANSPARENCY_POLARITY == ZERO_IS_OPAQUE:
        return not math.isclose(value, 0.0, abs_tol=1e-9)
    return not math.isclose(value, 1.0, abs_tol=1e-9)


# --- standards.assembly.not_hidden --------------------------------------------------------


@bind(NOT_HIDDEN)
def not_hidden(scope: Assembly) -> list[RuleResult]:
    """No component is left hidden, and suppression is never hidden (FR-013).

    Difference c: the macro asks for hidden *considering suppressed*, so it reports every
    suppressed component as hidden. Three states with three different remedies are three
    different rows here, and a suppressed instance is FR-005's skipped row.
    """
    rule = RULES[NOT_HIDDEN]
    if not scope.children:
        return [passed(rule, scope.document_id)]

    def unreadable(component: ComponentInstance) -> str | None:
        visibility = component.visibility_raw
        if visibility is None:
            return (
                "its visibility was not read; "
                f"{scope.why(component.id, 'component_visibility')}"
            )
        if visibility == VISIBILITY_UNKNOWN:
            return (
                f"its recorded visibility is {VISIBILITY_UNKNOWN}, which SOLIDWORKS names "
                "unknown"
            )
        if visibility not in (HIDDEN, VISIBLE):
            return (
                f"its recorded visibility is {visibility}, which is not a value this build "
                "names"
            )
        return None

    def classify(component: ComponentInstance) -> ChildOutcome:
        if component.visibility_raw == HIDDEN:
            return ChildOutcome(component, "offends")
        return ChildOutcome(component, "compliant")

    rows = _grade(scope, unreadable, classify)
    violation = None
    if rows.offenders:
        violation = finding(
            rule,
            scope.document_id,
            [scope.subject(component) for component in rows.offenders],
            observed="; ".join(
                f"{component.full_path} is hidden" for component in rows.offenders
            ),
            recommended_action=(
                "Show the component, or suppress it out of the configuration if it does not "
                "belong in this build."
            ),
        )
    return outcome(
        rule,
        scope.document_id,
        violation=violation,
        passing=[scope.subject(component) for component in rows.compliant],
        skips=list(rows.skips),
        unknown=list(rows.unknown),
    )
