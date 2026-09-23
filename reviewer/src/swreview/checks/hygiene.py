"""The house rules: part numbers, descriptions, revisions, unread components (feature 010 US7).

`contracts/hygiene.md` is normative. Five document-scope checks over the part and assembly
documents the component tree reaches, each once, with no argument a model chooses:

- `hygiene.part_number_matches_file`: the part-number property - the active configuration's
  first, then the document's - equals the file name's stem, compared stripped and without
  regard to case;
- `hygiene.duplicate_description` and `hygiene.duplicate_part_number`: two or more
  **different** documents with the same non-empty value, one finding per value naming every
  document that shares it;
- `hygiene.revision_present`: the profile's revision property on every model;
- `hygiene.component_not_resolved`: every lightweight or suppressed component of the
  reviewed configuration, one finding per document with its instances (an unloaded one is
  left to coverage).

**No property name is in this file** (research R2.17): the part-number and description
names come from the standards profile's version 2 `hygiene` section and the revision name
from its `revision.property`, so a company's names are data. A check whose setting is
absent, empty, or has no profile at all records one skipped item naming the setting. These
are rules with no calculation, so a document that satisfies one is counted in one `checked`
item per check, never a finding (research R2.21). A document whose properties were not read
is named in one skipped `hygiene.coverage` item and left out of the property checks.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from swreview.checks.documents import DocumentTree
from swreview.checks.result import CheckResult, DocumentResult
from swreview.checks.standards.profile import StandardsProfile
from swreview.checks.standards.results import properties_gap
from swreview.ir.models import ComponentInstance, Document, EvidencePackage
from swreview.report.session import CoverageItem, CoverageScope

__all__ = [
    "CHECK_COMPONENT_NOT_RESOLVED",
    "CHECK_COVERAGE",
    "CHECK_DUPLICATE_DESCRIPTION",
    "CHECK_DUPLICATE_PART_NUMBER",
    "CHECK_PART_NUMBER",
    "CHECK_REVISION",
    "HYGIENE_CHECKS",
    "HygieneChecks",
    "run_hygiene_checks",
]

CHECK_PART_NUMBER = "hygiene.part_number_matches_file"
CHECK_DUPLICATE_DESCRIPTION = "hygiene.duplicate_description"
CHECK_DUPLICATE_PART_NUMBER = "hygiene.duplicate_part_number"
CHECK_REVISION = "hygiene.revision_present"
CHECK_COMPONENT_NOT_RESOLVED = "hygiene.component_not_resolved"
CHECK_COVERAGE = "hygiene.coverage"

HYGIENE_CHECKS: tuple[str, ...] = (
    CHECK_PART_NUMBER,
    CHECK_DUPLICATE_DESCRIPTION,
    CHECK_DUPLICATE_PART_NUMBER,
    CHECK_REVISION,
    CHECK_COMPONENT_NOT_RESOLVED,
)

MODEL_KINDS = ("part", "assembly")
NOT_RESOLVED = ("lightweight", "suppressed")
SOLIDWORKS_EXTENSIONS = (".sldprt", ".sldasm")


@dataclass(frozen=True)
class HygieneChecks:
    """The five checks' findings, their counted passes, and what they did not evaluate."""

    findings: tuple[DocumentResult, ...]
    checked: tuple[CoverageItem, ...]
    skipped: tuple[CoverageItem, ...]
    documents: int


@dataclass(frozen=True)
class _Setting:
    """A property name a check reads, and the words that say where it would be set."""

    name: str | None
    label: str
    key: str


def _settings(profile: StandardsProfile | None) -> dict[str, _Setting]:
    hygiene = None if profile is None else profile.hygiene
    part_number = _Setting(
        None if hygiene is None else hygiene.part_number_property,
        "part-number property",
        "hygiene.part_number_property",
    )
    return {
        CHECK_PART_NUMBER: part_number,
        CHECK_DUPLICATE_PART_NUMBER: part_number,
        CHECK_DUPLICATE_DESCRIPTION: _Setting(
            None if hygiene is None else hygiene.description_property,
            "description property",
            "hygiene.description_property",
        ),
        CHECK_REVISION: _Setting(
            None if profile is None else profile.revision.property,
            "revision property",
            "revision.property",
        ),
    }


def _skip_reason(check: str, setting: _Setting, profile: StandardsProfile | None) -> str:
    if profile is None:
        return (
            f"{check} not evaluated: no standards profile is attached, so no {setting.label} "
            f"is named ({setting.key})"
        )
    return (
        f"{check} not evaluated: the standards profile names no {setting.label} "
        f"({setting.key})"
    )


def _value(document: Document, name: str) -> str | None:
    """The property `name`, the active configuration's first, matched without regard to
    case as SOLIDWORKS matches property names; `None` when neither carries it."""
    wanted = name.casefold()
    for properties in (
        document.config_properties.get(document.active_configuration, {}),
        document.custom_properties,
    ):
        for key, value in properties.items():
            if key.casefold() == wanted:
                return value
    return None


def _stem(file_name: str) -> str:
    lowered = file_name.lower()
    for extension in SOLIDWORKS_EXTENSIONS:
        if lowered.endswith(extension):
            return file_name[: -len(extension)]
    return file_name


def _found(
    check: str,
    observed: str,
    action: str,
    documents: Sequence[Document],
    tree: DocumentTree,
) -> DocumentResult:
    return DocumentResult(
        result=CheckResult(
            check=check,
            status="demonstrated",
            severity="low",
            observed=observed,
            requirement={
                CHECK_PART_NUMBER: "a model's part-number property is its file name's stem",
                CHECK_DUPLICATE_DESCRIPTION: "no two different documents share a description",
                CHECK_DUPLICATE_PART_NUMBER: "no two different documents share a part number",
                CHECK_REVISION: "every part and assembly carries its revision",
                CHECK_COMPONENT_NOT_RESOLVED: (
                    "every component of the reviewed configuration is resolved, so every check "
                    "sees it"
                ),
            }[check],
            inputs=[document.document_id for document in documents],
            calculation=None,
            coverage_limits=[],
            recommended_action=action,
        ),
        documents=tuple(document.document_id for document in documents),
        component_ids=tuple(
            cid for document in documents for cid in tree.component_ids(document)
        ),
    )


def _per_document(
    check: str,
    name: str,
    documents: Sequence[Document],
    tree: DocumentTree,
    judge: Callable[[Document, str], str | None],
    action: Callable[[Document, str], str],
) -> tuple[list[DocumentResult], int]:
    """A rule judged one document at a time: the findings and how many passed."""
    findings = []
    for document in documents:
        observed = judge(document, name)
        if observed is not None:
            findings.append(_found(check, observed, action(document, name), [document], tree))
    return findings, len(documents) - len(findings)


def _part_number_action(document: Document, name: str) -> str:
    return f"Set the {name} of {document.file_name} to its file name, or rename the file."


def _revision_action(document: Document, name: str) -> str:
    return f"Give {document.file_name} its {name}."


def _part_number(document: Document, name: str) -> str | None:
    value = _value(document, name)
    if value is None:
        return f"{document.file_name} has no {name}"
    stem = _stem(document.file_name)
    if value.strip().casefold() == stem.strip().casefold():
        return None
    return f"{document.file_name} has {name} {value.strip()!r}, which is not its file name {stem!r}"


def _revision(document: Document, name: str) -> str | None:
    value = _value(document, name)
    return f"{document.file_name} carries no {name}" if value is None or not value.strip() else None


def _duplicates(
    check: str, name: str, documents: Sequence[Document], tree: DocumentTree
) -> tuple[list[DocumentResult], int]:
    """One finding per shared value, naming every document that carries it."""
    by_value: dict[str, list[Document]] = {}
    for document in documents:
        value = _value(document, name)
        if value is not None and value.strip():
            by_value.setdefault(value.strip().casefold(), []).append(document)
    findings = []
    shared = 0
    for group in by_value.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda item: item.file_name)
        shared += len(group)
        value = (_value(group[0], name) or "").strip()
        findings.append(
            _found(
                check,
                f"{len(group)} documents share the {name} {value!r}: "
                + ", ".join(item.file_name for item in group),
                f"Give each of these documents its own {name}, or confirm they are one part.",
                group,
                tree,
            )
        )
    return findings, len(documents) - shared


def _not_resolved(tree: DocumentTree) -> list[DocumentResult]:
    findings = []
    for document_id, instances in sorted(tree.instances.items()):
        document = tree.documents.get(document_id)
        if document is None:
            continue
        for state in NOT_RESOLVED:
            matching: list[ComponentInstance] = [
                item for item in instances if item.suppression == state
            ]
            if not matching:
                continue
            count = len(matching)
            ids = ", ".join(item.id for item in matching)
            findings.append(
                DocumentResult(
                    result=CheckResult(
                        check=CHECK_COMPONENT_NOT_RESOLVED,
                        status="demonstrated",
                        severity="low",
                        observed=(
                            f"{count} instance{'s' if count != 1 else ''} of "
                            f"{document.file_name} {'is' if count == 1 else 'are'} {state} in "
                            f"the reviewed configuration: {ids}"
                        ),
                        requirement=(
                            "every component of the reviewed configuration is resolved, so "
                            "every check sees it"
                        ),
                        inputs=[item.id for item in matching],
                        calculation=None,
                        coverage_limits=[],
                        recommended_action=(
                            f"Resolve the {state} instances of {document.file_name} and re-run "
                            "the review, or confirm they are meant to be left out."
                        ),
                    ),
                    documents=(document_id,),
                    component_ids=tuple(item.id for item in matching),
                )
            )
    return findings


def _counted(check: str, passed: int, what: str, scope: Sequence[str]) -> CoverageItem:
    return CoverageItem(
        check=check,
        scope=CoverageScope(component_ids=sorted(scope)),
        reason=f"{passed} document{'s' if passed != 1 else ''}: {what}",
        error=None,
    )


def run_hygiene_checks(
    package: EvidencePackage, profile: StandardsProfile | None = None
) -> HygieneChecks:
    """The five checks, as plain values (`contracts/code-first.md` section 6)."""
    tree = DocumentTree(package)
    models = [document for document in tree.reached if document.kind in MODEL_KINDS]
    unread = [document for document in models if properties_gap(package, document.document_id)]
    read = [document for document in models if document not in unread]
    scope = [cid for document in read for cid in tree.component_ids(document)]
    findings: list[DocumentResult] = []
    checked: list[CoverageItem] = []
    skipped: list[CoverageItem] = []

    passes = {
        CHECK_PART_NUMBER: "the part number matches the file name",
        CHECK_DUPLICATE_DESCRIPTION: "the description is theirs alone",
        CHECK_DUPLICATE_PART_NUMBER: "the part number is theirs alone",
        CHECK_REVISION: "the model carries its revision",
    }
    for check, setting in _settings(profile).items():
        if not setting.name:
            skipped.append(
                CoverageItem(
                    check=check,
                    scope=CoverageScope(),
                    reason=_skip_reason(check, setting, profile),
                    error=None,
                )
            )
            continue
        if check == CHECK_PART_NUMBER:
            found, passed = _per_document(
                check, setting.name, read, tree, _part_number, _part_number_action
            )
        elif check == CHECK_REVISION:
            found, passed = _per_document(
                check, setting.name, read, tree, _revision, _revision_action
            )
        else:
            found, passed = _duplicates(check, setting.name, read, tree)
        findings.extend(found)
        if passed:
            checked.append(_counted(check, passed, passes[check], scope))

    findings.extend(_not_resolved(tree))
    if unread:
        count = len(unread)
        whose = "1 document's" if count == 1 else f"{count} documents'"
        skipped.append(
            CoverageItem(
                check=CHECK_COVERAGE,
                scope=CoverageScope(
                    component_ids=sorted(
                        cid for document in unread for cid in tree.component_ids(document)
                    )
                ),
                reason=(
                    f"{whose} properties were not read, so the property checks did not see "
                    f"{'it' if count == 1 else 'them'}: "
                    + ", ".join(document.file_name for document in unread)
                ),
                error=None,
            )
        )
    return HygieneChecks(
        findings=tuple(findings),
        checked=tuple(checked),
        skipped=tuple(skipped),
        documents=len(models),
    )
