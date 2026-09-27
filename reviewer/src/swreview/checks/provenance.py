"""Provenance, closed by code from the package before the first turn (feature 013 T060).

`contracts/re-ask-guard.md` section 2 is normative. The review reads the files open in
SOLIDWORKS as they stand, so each reviewed document's path, configuration and revision are
already in the package: nothing about provenance is the engineer's to answer. With no manifest
discrepancy - always on the native path, since only `ingest/manifest.py` writes them - that is one
`checked` coverage row; an ingested package's discrepancies are one finding each, most severe
first, and close the item by its prefix. Nothing here ever writes a question.

Pure: it reads the package and returns what to record; `agent/runner.record_provenance` writes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from swreview.checks.result import CheckResult
from swreview.findings import Calculation, Severity
from swreview.ingest.manifest import DISCREPANCY_SEVERITY
from swreview.ir.models import Discrepancy, EvidencePackage
from swreview.report.names import plural
from swreview.report.session import CoverageItem, CoverageScope

__all__ = [
    "CLOSED_REASON",
    "DISCREPANCY_SEVERITY_OF",
    "PROVENANCE_CHECK",
    "DiscrepancyFinding",
    "ProvenanceOutcome",
    "close_provenance",
]

PROVENANCE_CHECK = "provenance"
"""The checklist item's id, and the check of the row that closes it."""

CLOSED_REASON = (
    "Reviewed as open in SOLIDWORKS: {documents}, each at its own path in its active "
    "configuration; revision read on {k} of {n}. The open files are taken as the latest: vault "
    "version and local modification are not read and never asked. A missing revision is "
    "reported by the hygiene checks."
)
"""`contracts/re-ask-guard.md` section 2's sentence; `{documents}` is the count with its noun
(`report/names.plural`: "1 document", "2 documents")."""

DISCREPANCY_SEVERITY_OF: dict[str, Severity] = {
    "missing_document": "high",
    "local_modification": "high",
    "version_mismatch": "high",
    "config_mismatch": "medium",
}
"""Each discrepancy kind's finding severity, never rising down `DISCREPANCY_SEVERITY`'s order:
an absent document, a locally modified one and a stale version are each not the released design;
a wrong configuration is the wrong variant of the right one."""

DISCREPANCY_REQUIREMENT = "The reviewed document is the one the manifest names, as released"
DISCREPANCY_ACTION = "Review the released document, or correct the manifest, and review again"


@dataclass(frozen=True)
class DiscrepancyFinding:
    """One discrepancy as a finding to record: its result, and the document it is bound to."""

    result: CheckResult
    document_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProvenanceOutcome:
    """What closes the provenance item: the `checked` row, or the discrepancy findings."""

    coverage: CoverageItem | None
    findings: tuple[DiscrepancyFinding, ...] = ()


def close_provenance(package: EvidencePackage) -> ProvenanceOutcome:
    """How code closes provenance for `package` (`contracts/re-ask-guard.md` section 2)."""
    discrepancies = package.manifest.discrepancies
    if discrepancies:
        ordered = sorted(
            discrepancies,
            key=lambda item: (DISCREPANCY_SEVERITY.index(item.kind), item.document_id),
        )
        return ProvenanceOutcome(
            coverage=None, findings=tuple(_finding(package, item) for item in ordered)
        )
    reviewed = [
        document.document_id
        for document in package.documents
        if document.kind in ("part", "assembly")
    ]
    entries = {entry.document_id: entry for entry in package.manifest.entries}
    revised = sum(
        1
        for document_id in reviewed
        if document_id in entries and entries[document_id].revision
    )
    return ProvenanceOutcome(
        coverage=CoverageItem(
            check=PROVENANCE_CHECK,
            scope=CoverageScope(
                document_ids=reviewed, configuration=package.design.active_configuration
            ),
            reason=CLOSED_REASON.format(
                documents=plural(len(reviewed), "document"), n=len(reviewed), k=revised
            ),
            error=None,
        )
    )


def _finding(package: EvidencePackage, discrepancy: Discrepancy) -> DiscrepancyFinding:
    """One discrepancy's finding: the manifest comparison is its calculation.

    Bound to the document it names when the manifest holds that document - a finding cites the
    manifest entry of every document it names - and otherwise to the root, the design it is a
    discrepancy of, naming the missing document in what it observed.
    """
    manifested = {entry.document_id for entry in package.manifest.entries}
    bound = (
        discrepancy.document_id
        if discrepancy.document_id in manifested
        else package.design.root_assembly_document_id
    )
    observed = (
        f"{discrepancy.document_id}: {discrepancy.note} (the manifest says "
        f"{discrepancy.expected!r}; the package holds {discrepancy.actual!r})"
    )
    return DiscrepancyFinding(
        result=CheckResult(
            check=f"{PROVENANCE_CHECK}.{discrepancy.kind}",
            status="demonstrated",
            severity=DISCREPANCY_SEVERITY_OF[discrepancy.kind],
            observed=observed,
            requirement=DISCREPANCY_REQUIREMENT,
            inputs=[discrepancy.document_id],
            calculation=Calculation(
                model="manifest comparison",
                inputs={
                    "expected": str(discrepancy.expected),
                    "actual": str(discrepancy.actual),
                },
                assumptions=[],
                excluded_effects=[],
                result={"matches": False, "kind": discrepancy.kind},
                units_out="",
                function="checks.provenance.close_provenance",
                function_version="1",
            ),
            coverage_limits=[],
            recommended_action=DISCREPANCY_ACTION,
        ),
        document_ids=(bound,),
    )
