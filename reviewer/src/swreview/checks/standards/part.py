"""The four part-scope checks (T044).

One pure function per check of `specs/006-standards-check/contracts/rules.md`, each
decorated `@bind("<check id>")` and returning `list[RuleResult]`, exactly as `assembly.py`
does. Four conventions decide what they may look at:

- **every feature and every sketch the package records is a subject, at any depth**
  (difference z). The macro walks the top level of the tree only, so a defect inside a
  folder, or in a sketch consumed by another feature, never reaches its report. Each
  subject names the **chain of parent features** that reaches it, so a name that appears
  twice in a tree is still locatable;
- **the profile's four library lists are matched independently** (FR-006).
  `library.skip_prefixes` makes all four of these checks skipped coverage naming the matched
  prefix; `library.sketch_exempt_prefixes` makes one of them skipped and affects no other.
  An **empty** list exempts nothing and is never itself a skip, which is what keeps an
  unconfigured profile from silently grading nothing;
- **the counts are as the document stood.** Nothing is rebuilt to obtain a rebuild-error
  count (FR-044), so the finding and its coverage limits say so rather than implying a
  freshness the reviewer cannot offer (difference g);
- **a reading that was not made is unresolved** for that subject, naming what was missing
  and the gap the dump recorded beside it - never a pass and never a fail (FR-029).

FR-005's document-evidence half applies to all four: a part reached only through suppressed,
lightweight or unloaded instances was never opened, so what the package records about it is
not a reading of the document this assembly uses, and each check says so instead of grading
it. The condition is `results.document_evidence_unresolved`, written once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from swreview.checks.rms_types import load_table
from swreview.checks.standards.library import PrefixMatch, PrefixMatcher
from swreview.checks.standards.profile import StandardsProfile
from swreview.checks.standards.registry import RULES, bind
from swreview.checks.standards.results import (
    CUT_LIST_PHASE_GAPS,
    FEATURE_PHASE_GAPS,
    NO_REBUILD_NOTE,
    RuleResult,
    Subject,
    cut_list_subject,
    document_evidence_unresolved,
    document_subject,
    finding,
    gap_note,
    outcome,
    passed,
    phase_gap_note,
    properties_gap,
    properties_gap_note,
    skipped,
    unresolved,
)
from swreview.checks.standards.traversal import CheckedDocument
from swreview.ir.models import CutListItem, Document, EvidencePackage, Feature

__all__ = [
    "HOLE_WIZARD_TYPE_NAMES",
    "Part",
    "cut_list_excluded",
    "evaluate_part",
    "material_assigned",
    "part_scope",
    "rebuild_errors",
    "sketches_fully_defined",
]

SCOPE = "part"

SKETCHES_FULLY_DEFINED = "standards.part.sketches_fully_defined"
REBUILD_ERRORS = "standards.part.rebuild_errors"
MATERIAL_ASSIGNED = "standards.part.material_assigned"
CUT_LIST_EXCLUDED = "standards.part.cut_list_excluded"

SKIP_PREFIXES = "skip_prefixes"
SKETCH_EXEMPT_PREFIXES = "sketch_exempt_prefixes"

NO_SKETCHES = "the part records no sketches"
NO_CUT_LIST = (
    "the part records no cut-list items, which is not the same as every item being "
    "excluded (difference aa)"
)

NO_FEATURE_TREE = (
    "{name} records no features and the dump did not read its feature tree, so whether it "
    "has any is not something this package can say"
)
NO_CUT_LIST_READ = (
    "{name} records no cut-list items and the dump did not read its cut list, so whether it "
    "has any is not something this package can say"
)
"""An empty array is two different facts, and only one of them is a skip.

A phase that failed, aborted or was switched off records its loss as a gap, and the array it
would have filled is empty for that reason rather than because the document has nothing in
it. Answering `skip` there would report a part whose tree the dump lost as a part with no
sketches - the silent skip FR-029 forbids - so the gap is consulted before the skip and the
answer is unresolved naming it (`results.phase_gap`).
"""

UNDER_DEFINED = "under_defined"
DEFINED = frozenset({"fully_defined", "over_defined"})
"""`standards.part.sketches_fully_defined` fails on `under_defined` alone; a defined or
over-defined sketch is compliant. `unknown`, `unavailable` and `solver_error` are neither,
and are unresolved - a sketch whose solver errored cannot be shown to be fully defined."""

HOLE_WIZARD_TYPE_NAMES: frozenset[str] = frozenset({"HoleWzd"})
"""The feature type whose sketches the contract asks be named beside the sketch itself
(difference z): a hole-wizard sketch is not edited where an ordinary sketch is, so an
engineer needs to be told which feature owns it. A simple hole is an ordinary feature and
is not one of these."""

# --- the document one set of checks is evaluated over -------------------------------------


@dataclass(frozen=True)
class Part:
    """One graded part document and everything the four checks read about it."""

    document: CheckedDocument
    row: Document
    package: EvidencePackage
    features: tuple[Feature, ...]
    cut_list: tuple[CutListItem, ...]
    profile: StandardsProfile
    match: PrefixMatch
    """What the profile's four library lists say about this part's path, answered once."""

    by_id: Mapping[str, Feature]

    @property
    def document_id(self) -> str:
        return self.document.document_id

    @property
    def name(self) -> str:
        return self.document.file_name or self.document.document_id

    def itself(self) -> Subject:
        return document_subject(self.document)

    def why(self, entity_id: str, *kinds: str) -> str:
        return gap_note(self.package, entity_id, *kinds)

    def tree_lost(self) -> str | None:
        """Why `features` is empty for a reason other than a part with no features.

        `None` once the package records **any** feature row for this part: the tree was
        then read, and what it holds is the answer rather than the gap.
        """
        if self.features:
            return None
        return phase_gap_note(self.package, self.document_id, *FEATURE_PHASE_GAPS)

    def cut_list_lost(self) -> str | None:
        """Why `cut_list` is empty for a reason other than a part with no cut list."""
        if self.cut_list:
            return None
        return phase_gap_note(self.package, self.document_id, *CUT_LIST_PHASE_GAPS)

    def prefix_skip(self, list_name: str) -> str | None:
        """Why this part is exempt under one list, naming **every** entry it matched.

        The longest match decides, and every match is named, so a surprising answer can be
        traced to the line the engineer wrote (`contracts/profile.md`, prefix semantics 5).
        """
        matched = self.match.all_matches[list_name]
        if not matched:
            return None
        return (
            f"the part's path matches library.{list_name} "
            + ", ".join(repr(entry) for entry in matched)
        )

    def chain(self, feature: Feature) -> tuple[Feature, ...]:
        """The parent features that reach `feature`, outermost first."""
        parents: list[Feature] = []
        seen: set[str] = set()
        current = feature.folder_id
        while current is not None and current not in seen:
            seen.add(current)
            parent = self.by_id.get(current)
            if parent is None:
                break
            parents.append(parent)
            current = parent.folder_id
        return tuple(reversed(parents))

    def where(self, feature: Feature) -> str:
        """Where in the tree `feature` sits, as the finding says it."""
        parents = self.chain(feature)
        if not parents:
            return "at the top level of the feature tree"
        return "under " + " > ".join(parent.name for parent in parents)

    def hole_wizard(self, feature: Feature) -> str | None:
        """The hole-wizard feature this sketch belongs to, by parent or by consumer."""
        consumers = (feature.sketch.consumer_ids or ()) if feature.sketch is not None else ()
        candidates = [
            *self.chain(feature),
            *(self.by_id[consumer] for consumer in consumers if consumer in self.by_id),
        ]
        return next(
            (row.name for row in candidates if row.type_name in HOLE_WIZARD_TYPE_NAMES), None
        )


def part_scope(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> Part:
    """Everything the four checks read about `document`, gathered once."""
    if document.kind != SCOPE:
        raise ValueError(
            f"{document.document_id} is a {document.kind} document; the part checks grade a "
            f"{SCOPE} document"
        )
    row = next(item for item in package.documents if item.document_id == document.document_id)
    features = tuple(
        item for item in package.features if item.document_id == document.document_id
    )
    return Part(
        document=document,
        row=row,
        package=package,
        features=features,
        cut_list=tuple(
            item for item in package.cut_list_items if item.document_id == document.document_id
        ),
        profile=profile,
        match=PrefixMatcher.from_profile(profile).match(document.path or ""),
        by_id={item.id: item for item in features},
    )


def evaluate_part(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> list[RuleResult]:
    """Every part check over one graded part document, in catalogue order."""
    scope = part_scope(document, package, profile)
    results: list[RuleResult] = []
    for rule in RULES.values():
        if rule.scope == SCOPE:
            assert rule.fn is not None, f"{rule.id} has no evaluator"
            results.extend(rule.fn(scope))
    return results


def _blocked(scope: Part, rule_id: str, *lists: str) -> list[RuleResult] | None:
    """The two rows that answer for a whole check before any subject is looked at.

    FR-005's document-evidence half first - a document nobody opened has no readings to
    grade - then the library lists this check is exempt under. `None` when the check runs.
    """
    rule = RULES[rule_id]
    missing = document_evidence_unresolved(scope.document)
    if missing is not None:
        return [unresolved(rule, scope.document_id, missing)]
    for list_name in lists:
        exempt = scope.prefix_skip(list_name)
        if exempt is not None:
            return [skipped(rule, scope.document_id, exempt)]
    return None


# --- standards.part.sketches_fully_defined ------------------------------------------------


@bind(SKETCHES_FULLY_DEFINED)
def sketches_fully_defined(scope: Part) -> list[RuleResult]:
    """Every sketch is fully defined (FR-014)."""
    rule = RULES[SKETCHES_FULLY_DEFINED]
    blocked = _blocked(scope, SKETCHES_FULLY_DEFINED, SKIP_PREFIXES, SKETCH_EXEMPT_PREFIXES)
    if blocked is not None:
        return blocked

    sketches = [row for row in scope.features if row.sketch is not None]
    if not sketches:
        lost = scope.tree_lost()
        if lost is not None:
            return [
                unresolved(
                    rule,
                    scope.document_id,
                    f"{NO_FEATURE_TREE.format(name=scope.name)}; {lost}",
                )
            ]
        return [skipped(rule, scope.document_id, NO_SKETCHES)]

    table = load_table()
    offenders: list[Feature] = []
    observed: list[str] = []
    passing: list[Feature] = []
    skips: list[tuple[Feature, str]] = []
    unknown: list[tuple[Feature, str]] = []
    for row in sketches:
        assert row.sketch is not None
        segments = row.sketch.text_segment_count
        if segments is None:
            unknown.append(
                (
                    row,
                    "its sketch text-segment count was not read, so the sketch-text exemption "
                    f"can neither be applied nor ruled out; {scope.why(row.id, 'sketch_text')}",
                )
            )
            continue
        if segments > 0:
            skips.append(
                (
                    row,
                    f"it carries {segments} sketch text segment(s): connector-label text "
                    "cannot easily be fully defined, which is the sketch-text exemption",
                )
            )
            continue
        status = table.constrained_status(row.sketch.raw_status)
        if status != UNDER_DEFINED and status not in DEFINED:
            unknown.append(
                (
                    row,
                    f"its constrained status is {status}; "
                    + scope.why(row.id, "sketch_status"),
                )
            )
            continue
        if status in DEFINED:
            passing.append(row)
            continue
        offenders.append(row)
        wizard = scope.hole_wizard(row)
        observed.append(
            f"{row.name} is under-defined, {scope.where(row)}"
            + (f", and belongs to the hole-wizard feature {wizard}" if wizard else "")
        )

    violation = None
    if offenders:
        violation = finding(
            rule,
            scope.document_id,
            offenders,
            observed="; ".join(observed),
            recommended_action=(
                "Add the relations or dimensions the sketch needs, so it is fully defined."
            ),
        )
    return outcome(
        rule,
        scope.document_id,
        violation=violation,
        passing=passing,
        skips=skips,
        unknown=unknown,
    )


# --- standards.part.rebuild_errors --------------------------------------------------------


@bind(REBUILD_ERRORS)
def rebuild_errors(scope: Part) -> list[RuleResult]:
    """A part carries no rebuild errors, as it stood (FR-015).

    Any non-zero `error_code` counts, so a feature *warning* counts too - the macro ignores
    `GetErrorCode2`'s warning out-parameter and this keeps its condition - and the code is
    named, so an engineer can tell the two apart (difference u).
    """
    rule = RULES[REBUILD_ERRORS]
    blocked = _blocked(scope, REBUILD_ERRORS, SKIP_PREFIXES)
    if blocked is not None:
        return blocked

    offenders: list[Feature] = []
    observed: list[str] = []
    passing: list[Feature] = []
    unknown: list[tuple[Feature, str]] = []
    for row in scope.features:
        if row.error_code is None:
            unknown.append(
                (row, f"its error code was not read; {scope.why(row.id, 'feature')}")
            )
            continue
        if row.error_code == 0:
            passing.append(row)
            continue
        offenders.append(row)
        observed.append(
            f"{row.name} carries error code {row.error_code}, {scope.where(row)}"
        )

    # What is unknown about the DOCUMENT rather than about one feature: one entry, because
    # both halves name the same subject and two would list it twice.
    notes: list[str] = []
    lost = scope.tree_lost()
    if lost is not None:
        notes.append(f"{NO_FEATURE_TREE.format(name=scope.name)}; {lost}")

    count = scope.row.rebuild_error_count
    subjects: list[Feature] = list(offenders)
    if count is None:
        notes.append(
            f"the rebuild-error count of {scope.name} was not read; "
            + scope.why(scope.document_id, "rebuild_error_count")
        )
    elif count > 0:
        subjects.append(scope.itself())
        observed.append(f"{scope.name} records {count} rebuild error(s)")

    if notes:
        unknown.append((scope.itself(), "; ".join(notes)))

    violation = None
    if subjects and observed:
        violation = finding(
            rule,
            scope.document_id,
            subjects,
            observed="; ".join(observed)
            + "; the counts are as the document stood when they were read and nothing was "
            "rebuilt to obtain them",
            recommended_action=(
                "Rebuild the part in SOLIDWORKS, fix what it reports, and run the check again."
            ),
            coverage_limits=[NO_REBUILD_NOTE],
        )

    # A part with no feature rows and a count of zero reached no subject at all, and
    # `outcome` writes no vacuous pass: without this the check would land in **no** bucket
    # for the document, which `contracts/rules.md` forbids ("every check lands in at least
    # one bucket for every document it applies to"). The document's count of zero is what
    # was checked, so the document is what the pass names.
    if violation is None and not passing and not unknown:
        passing.append(scope.itself())

    return outcome(
        rule, scope.document_id, violation=violation, passing=passing, unknown=unknown
    )


# --- standards.part.material_assigned -----------------------------------------------------


@bind(MATERIAL_ASSIGNED)
def material_assigned(scope: Part) -> list[RuleResult]:
    """A material, or a deliberately overridden mass - and not both (FR-016).

    All four cells of the contract's truth table are live here. The macro sets its status
    flag without its error flag in the headline case, so its reporter drops the row and
    "part has no material" is never reported (difference b, limitation L1).
    """
    rule = RULES[MATERIAL_ASSIGNED]
    blocked = _blocked(scope, MATERIAL_ASSIGNED, SKIP_PREFIXES)
    if blocked is not None:
        return blocked

    configured = scope.profile.material.configuration
    recorded = scope.row.material_configuration
    if recorded is None:
        return [
            unresolved(
                rule,
                scope.document_id,
                "the configuration the material was read in was not recorded, so it cannot be "
                f"compared with the profile's material configuration {configured!r}; "
                + properties_gap_note(scope.package, scope.document_id),
            )
        ]
    if configured.casefold() not in {name.casefold() for name in scope.row.configurations}:
        return [
            unresolved(
                rule,
                scope.document_id,
                f"{scope.name} has no configuration {configured!r}, which is the profile's "
                f"material configuration; the material recorded is the one in {recorded!r}",
            )
        ]
    if recorded.casefold() != configured.casefold():
        return [
            unresolved(
                rule,
                scope.document_id,
                f"the material was read in configuration {recorded!r} and the profile's "
                f"material configuration is {configured!r}",
            )
        ]

    overridden = scope.row.mass_overridden
    if overridden is None:
        return [
            unresolved(
                rule,
                scope.document_id,
                "whether the mass is overridden was not read, and a material and an override "
                "are the two signals this check is decided by; "
                + scope.why(scope.document_id, "mass_override"),
            )
        ]

    # The gap that says the MATERIAL was not read, and not any `document`-kind gap: the same
    # kind carries four mass-property facts, and both of the truth table's failing cells are
    # states that record one. A part whose mass is overridden always records the OVERRIDDEN
    # gap, so reading the kind alone would make the (no material, overridden) = checked cell
    # unreachable; a surface-only part always records the no-solid-volume gap, so it would
    # suppress difference b - the (no material, not overridden) = fail cell this check
    # exists to revive (`results.MASS_PROPERTY_GAP_MARKERS`).
    material = scope.row.material
    if material is None and properties_gap(scope.package, scope.document_id) is not None:
        return [
            unresolved(
                rule,
                scope.document_id,
                "the material was not read, which is not the same as no material being "
                f"assigned; {properties_gap_note(scope.package, scope.document_id)}",
            )
        ]

    if material is None and not overridden:
        observed = (
            f"no material is assigned in configuration {configured} and the mass is not "
            "overridden, so the recorded mass stands for nothing"
        )
    elif material is not None and overridden:
        observed = (
            f"material {material} is assigned in configuration {configured} and the mass is "
            "overridden; the recorded mass is not computed from the geometry"
        )
    else:
        return [passed(rule, scope.document_id)]

    return [
        finding(
            rule,
            scope.document_id,
            [scope.itself()],
            observed=observed,
            recommended_action=(
                "Assign the material the part is made of, or override the mass deliberately - "
                "one of the two, not neither and not both."
            ),
        )
    ]


# --- standards.part.cut_list_excluded -----------------------------------------------------


@bind(CUT_LIST_EXCLUDED)
def cut_list_excluded(scope: Part) -> list[RuleResult]:
    """Every cut-list item is excluded from the cut list (FR-017).

    **Each row is its own body folder.** `CutListDumper.ReadItem` calls
    `IBodyFolder.GetBodyCount()` on the *item's* folder, while `folder_name` is the name of
    the enclosing `Cut list` feature, which every item of a real weldment shares. So
    displayability is decided per row: grouping by `folder_name` and reading one member's
    count would switch the whole check off for a part the moment one item folder came back
    empty, and would drop the rest of a part's items into no bucket at all the moment the
    first item's count could not be read.

    A folder that holds no bodies is not displayed by SOLIDWORKS and is not a subject; the
    skipped reason says how many folders were seen and how many were displayable, so the
    difference between "nothing to check" and "nothing was checked" is on the row.
    """
    rule = RULES[CUT_LIST_EXCLUDED]
    blocked = _blocked(scope, CUT_LIST_EXCLUDED, SKIP_PREFIXES)
    if blocked is not None:
        return blocked

    if not scope.cut_list:
        lost = scope.cut_list_lost()
        if lost is not None:
            return [
                unresolved(
                    rule,
                    scope.document_id,
                    f"{NO_CUT_LIST_READ.format(name=scope.name)}; {lost}",
                )
            ]
        return [skipped(rule, scope.document_id, NO_CUT_LIST)]

    displayable = sum(1 for item in scope.cut_list if (item.body_count or 0) > 0)
    census = f"{len(scope.cut_list)} cut-list folder(s) seen, {displayable} displayable"

    graded: list[CutListItem] = []
    skips: list[tuple[Subject, str]] = []
    unknown: list[tuple[Subject, str]] = []
    for item in scope.cut_list:
        bodies = item.body_count
        if bodies is None:
            unknown.append(
                (
                    cut_list_subject(item),
                    f"the body count of the cut-list folder {item.name} was not read, so "
                    "whether SOLIDWORKS displays it is unknown and it cannot be graded; "
                    + scope.why(item.id, "cut_list_body_count"),
                )
            )
            continue
        if bodies == 0:
            skips.append(
                (
                    cut_list_subject(item),
                    "it holds no bodies and is not displayed by SOLIDWORKS "
                    f"({census})",
                )
            )
            continue
        graded.append(item)

    offenders: list[Subject] = []
    observed: list[str] = []
    passing: list[Subject] = []
    for item in graded:
        if item.excluded_from_cut_list is None:
            unknown.append(
                (
                    cut_list_subject(item),
                    "whether it is excluded from the cut list was not read; "
                    + scope.why(item.id, "cut_list_exclusion"),
                )
            )
            continue
        if item.excluded_from_cut_list:
            passing.append(cut_list_subject(item))
            continue
        offenders.append(cut_list_subject(item))
        observed.append(
            f"{item.name} in the cut-list folder {item.folder_name} is not excluded from the "
            "cut list"
        )

    violation = None
    if offenders:
        violation = finding(
            rule,
            scope.document_id,
            offenders,
            observed="; ".join(observed),
            recommended_action=(
                "Tick Exclude from cut list on the item, so the released cut list carries "
                "only what is cut."
            ),
        )
    return outcome(
        rule,
        scope.document_id,
        violation=violation,
        passing=passing,
        skips=skips,
        unknown=unknown,
    )
