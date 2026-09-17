"""The standards family's `RuleResult` constructors, and the subjects they name.

What one check concluded about one document is the same shape in every family, so the type,
the outcome invariant, the evidence format and the six constructors live in
`checks/rules/results.py`. Two of them need to know whose checks these are - `finding`,
which turns a check's severity into a `Finding` status and severity, and `severity_of` -
and this module binds them to `STANDARDS_FAMILY`, exactly as `checks/rms/results.py` binds
the other family. Read `checks/rules/results.py` for what the constructors do.

Three more things live here because **all four** evaluator modules need them and none of
them belongs to one scope (constitution Principle V, DRY):

- **`Subject`**, the shape `results.py` renders a subject in. The IR's `ComponentInstance`,
  `Mate` and `CutListItem` are not `Feature`s and carry no `name`/`type_name` pair, and a
  data-card property is not an IR row at all, so each is presented here in the seven
  attributes the constructors read. Nothing is invented: every field is read off the row;
- **the gap lookups.** A null reading is unresolved *naming the reason*, and the reason is
  the `Gap` the dump recorded beside it - or, said explicitly, that it recorded none. One
  reading of `package.gaps`, so no check invents its own phrasing for "not read". Three
  questions are asked of it and they are not the same question: which gap sits beside
  *this* reading (`gap_note`), whether the document's **properties** were read at all
  (`properties_gap`, which a mass-property gap does not answer), and whether an **empty
  array** is an empty document or a phase the dump lost (`phase_gap`);
- **FR-005's document-evidence half.** A document reached only through suppressed,
  lightweight or unloaded instances was never opened, so the readings a check would grade
  it on are not evidence about it. That is one condition, cited by seven checks, and it is
  written here once. The instance-signal half is per check and stays in `assembly.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from swreview.checks.rules.results import (
    RuleOutcome,
    RuleResult,
    passed,
    skipped,
    subject_input,
    subject_reasons,
    unresolved,
    verdict,
)
from swreview.checks.rules.results import finding as _finding
from swreview.checks.rules.results import severity_of as _severity_of
from swreview.checks.standards.registry import STANDARDS_FAMILY, StandardsRule
from swreview.checks.standards.traversal import CheckedDocument
from swreview.findings import Severity
from swreview.ir.models import (
    ComponentInstance,
    CutListItem,
    EvidencePackage,
    Feature,
    Gap,
    Mate,
)

__all__ = [
    "CUT_LIST_PHASE_GAPS",
    "DOCUMENT_GAP",
    "FEATURE_PHASE_GAPS",
    "MASS_PROPERTY_GAP_MARKERS",
    "MATE_PHASE_GAPS",
    "NO_GAP",
    "NO_REBUILD_NOTE",
    "RuleOutcome",
    "RuleResult",
    "Subject",
    "component_subject",
    "cut_list_subject",
    "document_evidence_unresolved",
    "document_subject",
    "finding",
    "find_gap",
    "gap_note",
    "mate_subject",
    "note_of",
    "outcome",
    "passed",
    "phase_gap",
    "phase_gap_note",
    "properties_gap",
    "properties_gap_note",
    "property_subject",
    "severity_of",
    "skipped",
    "subject_input",
    "subject_reasons",
    "unresolved",
    "verdict",
]

NO_REBUILD_NOTE = "counts as the document stood; nothing was rebuilt"
"""What the two rebuild-error checks carry in `coverage_limits` (data-model section 3).

The reviewer never rebuilds (FR-044), so a count of zero is a count that was zero when the
engineer last rebuilt, and a reader has to be told which claim is being made (difference g).
"""

NO_GAP = "the dump recorded no gap for it"
"""Said out loud rather than left blank: a reading that is absent with no gap beside it is
still unresolved, and the reason says that the dump did not explain itself."""


# --- the subjects a check names -----------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """A component, a mate, a cut-list item, a document or a data-card property, in the
    shape `checks/rules/results.py` renders a subject in.

    Structural, not nominal: `passed`, `skipped`, `unresolved` and `finding` read exactly
    these seven attributes and are annotated `Feature` because the feature-tree rules were
    written first. Duplicating those constructors per row type would be the second
    mechanism this family exists to avoid.
    """

    id: str
    name: str
    type_name: str
    persist_ref: str | None
    persist_ref_scope: str
    suppressed: bool
    configuration: str


def component_subject(component: ComponentInstance, configuration: str) -> Subject:
    """A component instance, labelled by the path that is unique in the assembly.

    Only a `suppressed` component is `suppressed`: lightweight and unloaded are states of
    the load rather than of the configuration, and each check says so in its own reason.
    """
    return Subject(
        id=component.id,
        name=component.full_path,
        type_name="component",
        persist_ref=component.persist_ref,
        persist_ref_scope=component.persist_ref_scope,
        suppressed=component.suppression == "suppressed",
        configuration=configuration,
    )


def mate_subject(mate: Mate, configuration: str) -> Subject:
    """A mate: the IR carries no mate name, so its type is the label."""
    return Subject(
        id=mate.id,
        name=mate.type,
        type_name="mate",
        persist_ref=mate.persist_ref,
        persist_ref_scope=mate.persist_ref_scope,
        suppressed=mate.suppressed,
        configuration=configuration,
    )


def cut_list_subject(item: CutListItem) -> Subject:
    """A cut-list item, labelled by its folder and its own name.

    `persist_ref` may be null (PROBE-10), and then `id` is the within-dump identity the
    package recorded instead - which is what FR-026 requires be visible rather than
    presented as a persistent reference.
    """
    return Subject(
        id=item.id,
        name=f"{item.folder_name}/{item.name}",
        type_name="cut list item",
        persist_ref=item.persist_ref,
        persist_ref_scope=item.persist_ref_scope or item.document_id,
        suppressed=False,
        configuration=item.configuration,
    )


def document_subject(document: CheckedDocument) -> Subject:
    """The graded document itself, for the checks whose subject is the document.

    A document has no persistent reference of its own: it *is* the scope every other
    reference resolves against.
    """
    return Subject(
        id=document.document_id,
        name=document.file_name or document.document_id,
        type_name="document",
        persist_ref=None,
        persist_ref_scope=document.document_id,
        suppressed=False,
        configuration=document.configuration or "",
    )


def property_subject(name: str, document: CheckedDocument) -> Subject:
    """One data-card property name, which is a subject with no IR row behind it.

    Its identity is the property name inside the document, so `id` says both; there is
    nothing in SOLIDWORKS to select, which is what a null `persist_ref` states.
    """
    return Subject(
        id=f"property:{name}",
        name=name,
        type_name="data card property",
        persist_ref=None,
        persist_ref_scope=document.document_id,
        suppressed=False,
        configuration=document.configuration or "",
    )


# --- what the dump could not read ---------------------------------------------------------


def find_gap(package: EvidencePackage, entity_id: str, *kinds: str) -> Gap | None:
    """The first gap `package` records for `entity_id`, of `kinds` when any are named."""
    return next(
        (
            gap
            for gap in package.gaps
            if gap.entity_id == entity_id and (not kinds or gap.entity_kind in kinds)
        ),
        None,
    )


def gap_note(package: EvidencePackage, entity_id: str, *kinds: str) -> str:
    """Why a reading is missing: the gap the dump recorded, or that it recorded none."""
    return note_of(find_gap(package, entity_id, *kinds))


def note_of(gap: Gap | None) -> str:
    """One gap as a check says it, or `NO_GAP` when the dump recorded none."""
    if gap is None:
        return NO_GAP
    return f"the dump recorded a {gap.entity_kind} gap: {gap.reason}"


# --- the document gap that speaks for the property read -----------------------------------

DOCUMENT_GAP = "document"
"""The gap kind `PropertyDumper` records. It is **not** one condition: the dumper records it
for the two whole-document failures (the document is not open, or `Read` threw and the row
is a placeholder) **and** for four mass-property facts that say nothing about the custom
properties or the material - which is why no check may read the kind alone."""

MASS_PROPERTY_GAP_MARKERS: tuple[str, ...] = (
    "CreateMassProperty2 returned nothing",
    "Mass properties could not be recalculated",
    "The model has no solid volume",
    "The mass properties are OVERRIDDEN",
)
"""The four `document` gaps `PropertyDumper.ReadMass` records about the **mass** alone.

A surface-only part and a part whose mass an engineer deliberately overrode each carry one
of these, and both are states the release checklist permits. Read as "the properties were
not read" they suppress `standards.document.data_card_complete` on a large share of real
parts and make two cells of `standards.part.material_assigned`'s truth table unreachable -
including difference b, the macro's dead branch this feature exists to revive.

A denylist rather than an allowlist, because the two directions fail differently: a
`document` gap this build has never seen leaves the reading unresolved, which is the honest
answer, where an unrecognised gap missing from an allowlist would be a silent pass.
"""


def properties_gap(package: EvidencePackage, document_id: str) -> Gap | None:
    """The gap that says this document's properties and material were not read at all.

    A `document` gap naming a mass-property fact is not one of those: it speaks for the
    mass alone (`MASS_PROPERTY_GAP_MARKERS`).
    """
    return next(
        (
            gap
            for gap in package.gaps
            if gap.entity_kind == DOCUMENT_GAP
            and gap.entity_id == document_id
            and not any(marker in gap.reason for marker in MASS_PROPERTY_GAP_MARKERS)
        ),
        None,
    )


def properties_gap_note(package: EvidencePackage, document_id: str) -> str:
    """Why the property read is missing, or that the dump recorded no gap for it."""
    return note_of(properties_gap(package, document_id))


# --- the gap that says a whole phase's rows are missing ------------------------------------

FEATURE_PHASE_GAPS: tuple[str, ...] = ("feature", "feature_tree_unavailable")
CUT_LIST_PHASE_GAPS: tuple[str, ...] = ("cutlist", "cut_list_folder")
MATE_PHASE_GAPS: tuple[str, ...] = ("mate",)
"""The gap kinds that say an **array** is empty because the dump lost it.

`PackageWriter.RunPhase` records the phase name with a null `entity_id` when a phase fails
or aborts, `--features none` records `feature_tree_unavailable` the same way, and
`FeatureDumper` and `CutListDumper` record the document's own id when they drop one
document's rows. Without consulting them an empty `features[]`, `cut_list_items[]` or
`mates[]` reads as "this document has none", which is the silent skip FR-029 forbids.
"""


def phase_gap(package: EvidencePackage, document_id: str, *kinds: str) -> Gap | None:
    """The gap that says `document_id`'s rows of one phase are missing, if there is one.

    `entity_id` is null for a phase the dump lost whole and the document's own id for a
    document whose rows one dumper dropped. A gap naming some other entity - a feature, a
    mate, a cut-list item - speaks for that entity and not for the array being empty.
    """
    return next(
        (
            gap
            for gap in package.gaps
            if gap.entity_kind in kinds and gap.entity_id in (None, document_id)
        ),
        None,
    )


def phase_gap_note(package: EvidencePackage, document_id: str, *kinds: str) -> str | None:
    """Why an empty array is not evidence of an empty document, or `None` when it is."""
    gap = phase_gap(package, document_id, *kinds)
    return None if gap is None else note_of(gap)


def document_evidence_unresolved(document: CheckedDocument) -> str | None:
    """FR-005's document-evidence half: why this document's readings are not evidence.

    A document every one of whose instances is suppressed, lightweight or unloaded was
    never opened by the dump, so what the package records about it is not a reading of the
    document as this assembly uses it. `None` when at least one instance resolved, which is
    the ordinary case: the document is then graded normally and the unresolved instances
    are named in the finding's coverage limits (`contracts/rules.md`).
    """
    if not document.instances or len(document.unresolved_instances) < len(document.instances):
        return None
    states = ", ".join(f"{name} is {state}" for name, state in document.unresolved_instances)
    return (
        f"{document.file_name or document.document_id} is reached only through component "
        f"instances that are not resolved ({states}), so the evidence this check reads was "
        "not read from the document; the reviewer does not resolve, load or open an "
        "instance to obtain it"
    )


# --- the family's constructors ------------------------------------------------------------


def outcome(
    rule: StandardsRule,
    document_id: str,
    *,
    violation: RuleResult | None = None,
    passing: Sequence[Feature] = (),
    skips: Sequence[tuple[Feature, str]] = (),
    unknown: Sequence[tuple[Feature, str]] = (),
) -> list[RuleResult]:
    """One check's results over the subjects of one document: at most one verdict, plus
    its skipped and unresolved halves.

    `checks/rules/results.py`'s `verdict` is the same shape without the skipped half, which
    every standards check that reads subjects one at a time needs: a suppressed instance, an
    exempt sketch and an empty cut-list folder are all *skipped* beside the subjects that
    were graded. Two rules it keeps from `verdict`:

    - a violation **replaces** the pass - a check that failed on this document is not also
      checked for it;
    - an empty `passing` yields **no vacuous pass**, so a check whose every subject was
      skipped or unresolved does not also claim to have checked something.

    It returns an empty list when the check reached nothing at all, which is a case each
    check answers for itself (no children, no sketches, no cut-list items), because what
    "nothing to look at" means is the check's own business and not this function's.
    """
    results: list[RuleResult] = []
    if violation is not None:
        results.append(violation)
    elif passing:
        results.append(passed(rule, document_id, passing))
    if skips:
        results.append(
            skipped(rule, document_id, subject_reasons(skips), [row for row, _ in skips])
        )
    if unknown:
        results.append(
            unresolved(rule, document_id, subject_reasons(unknown), [row for row, _ in unknown])
        )
    return results


def severity_of(rule: StandardsRule) -> Severity:
    """The `Finding` severity of `rule`: `high` for the four data-integrity checks."""
    return _severity_of(STANDARDS_FAMILY, rule)


def finding(
    rule: StandardsRule,
    document_id: str,
    subjects: Sequence[Feature],
    *,
    observed: str,
    recommended_action: str,
    coverage_limits: Sequence[str] = (),
) -> RuleResult:
    """A violation of `rule`: outcome `fail` for an error check, `warn` for a warning one.

    `observed` states what the package shows and `recommended_action` what to do about it;
    the requirement, the inputs, the status and the severity come from `rule` and
    `subjects` through `STANDARDS_FAMILY`. `inputs` is restamped in this family's format by
    `checks/standards/report.py`, which owns the `Subject.kind` vocabulary it names.
    """
    return _finding(
        STANDARDS_FAMILY,
        rule,
        document_id,
        subjects,
        observed=observed,
        recommended_action=recommended_action,
        coverage_limits=coverage_limits,
    )
