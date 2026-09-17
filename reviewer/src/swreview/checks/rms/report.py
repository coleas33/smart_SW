"""What the RMS family adds to `checks/rules/report.py`, and nothing else (T022).

The three `check_rms_*` tools differ only in which rules they dispatch; everything that
happens to the results afterwards is the same for every family, and
`checks/rules/report.py` is that once - findings, exceptions, aggregated coverage and the
family's summary item, in that order, so a rule author never writes a `Finding` and a tool
author never writes a `CoverageItem`.

Three things are this family's own, and they are what is left here (`specs/006-standards-
check/research.md` R7):

1. **the group stamp.** Every subject of an RMS finding carries the RMS group its feature
   is in, which `checks/rms/groups.py` decides from the calibrated type table. That is the
   per-family subject decorator, prepared once per document and asked once per subject;
2. **the unknown-type census** (`rms.types.unknown`), which reads the same table and says
   which `GetTypeName2` names the shipped one does not know;
3. **the ten never-dispatched rules**, emitted once per session in their own buckets, with
   `rms.assembly.subassemblies` naming the subassembly documents the assembly rules did not
   reach.

(2) and (3) are the family's extra coverage steps, supplied to the moved layer in that
order, and they run after the aggregated coverage and before the summary - which is where
they ran before the move, and where the golden baselines expect to find them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

from swreview.checks.rms.groups import assign_groups
from swreview.checks.rms.registry import RMS_FAMILY, RULES, coverage_only
from swreview.checks.rms.results import RuleResult
from swreview.checks.rms_types import load_table, unknown_types
from swreview.checks.rules.report import NO_PERSIST_REF, scope_over, session_holds
from swreview.checks.rules.report import report_results as _report_results
from swreview.ir.models import EvidencePackage
from swreview.report.session import CoverageItem, ReviewSession
from swreview.tools.context import ToolContext
from swreview.tools.query import ToolResult

__all__ = ["NO_PERSIST_REF", "SUMMARY_CHECK", "UNKNOWN_TYPES_CHECK", "report_results"]

SUMMARY_CHECK = RMS_FAMILY.summary_check
"""The checklist item these rules answer; its coverage item is the one-line verdict on
the whole method for this review (`agent/checklist_v1.yaml`). A fact on the family, read
here under the name the tools and their tests have always called it."""

UNKNOWN_TYPES_CHECK = "rms.types.unknown"
"""Not a rule: the census of `GetTypeName2` names the shipped table does not know, which
is how a recalibration finds out what it is missing (`contracts/rules.md`, "Content
features")."""


def report_results(context: ToolContext, results: Sequence[RuleResult]) -> ToolResult:
    """Write `results` to the session as findings and coverage; report what was written.

    The moved layer does the work; this call is which family, which catalogue, and the
    three things above.
    """
    return _report_results(
        RMS_FAMILY,
        RULES,
        context,
        results,
        decorate_subjects=_group_stamp,
        extra_coverage=(_write_unknown_types, _write_undispatched),
    )


# --- 1. the group stamp on every subject ------------------------------------------


def _group_stamp(
    package: EvidencePackage, document_ids: Sequence[str]
) -> Callable[[str, str], Mapping[str, object]]:
    """The RMS group each subject's feature is in, prepared once for these documents.

    `group` is null for a subject that is not a feature of a graded part document - a mate
    and a component instance are subjects too, and neither is in a group.
    """
    groups = _groups_by_document(package, document_ids)

    def stamp(document_id: str, subject_id: str) -> Mapping[str, object]:
        return {"group": groups.get((document_id, subject_id))}

    return stamp


def _groups_by_document(
    package: EvidencePackage, document_ids: Iterable[str]
) -> dict[tuple[str, str], str | None]:
    """Which group each feature of `document_ids` is in, keyed by (document, feature).

    `checks/rms/groups.py` is the one place group membership is decided, so this asks it
    rather than re-deriving anything; it is asked once per document per call rather than
    once per finding. Keyed by the pair because a feature id is unique within a document's
    tree, not across a package.
    """
    table = load_table()
    assigned: dict[tuple[str, str], str | None] = {}
    for document_id in dict.fromkeys(document_ids):
        rows = [row for row in package.features if row.document_id == document_id]
        if not rows:
            continue
        for feature_id, group in assign_groups(rows, table).by_feature_id.items():
            assigned[(document_id, feature_id)] = group
    return assigned


# --- 2. the census and the undispatched rules -------------------------------------


def _write_unknown_types(
    context: ToolContext, session: ReviewSession, results: Sequence[RuleResult]
) -> list[dict[str, str]]:
    """The `rms.types.unknown` item over the documents this call evaluated, or nothing.

    What counts as unclassified is `checks/rms_types.unknown_types`, which `swreview rms
    types` asks for the whole package and this item asks for the documents one check
    evaluated: only content features, and only `unknown` rather than `ambiguous` (a
    folder and an end tag are structure, and the table classifies neither -
    `contracts/rules.md`, "Content features"). The census here is that answer rendered,
    and the scope is the documents it came back naming.
    """
    document_ids = []
    for result in results:
        if result.document_id not in document_ids:
            document_ids.append(result.document_id)

    rows = unknown_types(row for row in context.ir.features if row.document_id in document_ids)
    if not rows:
        return []

    documents: list[str] = []
    for row in rows:
        for document_id in row.document_ids:
            if document_id not in documents:
                documents.append(document_id)
    census = ", ".join(f"{row.type_name} x{row.count}" for row in rows)
    context.replace_coverage(
        UNKNOWN_TYPES_CHECK,
        "unresolved",
        CoverageItem(
            check=UNKNOWN_TYPES_CHECK,
            scope=scope_over(context, documents),
            reason=f"feature type names not in the calibrated table: {census}",
            error=None,
        ),
    )
    return [{"bucket": "unresolved", "check": UNKNOWN_TYPES_CHECK}]


def _write_undispatched(
    context: ToolContext, session: ReviewSession, results: Sequence[RuleResult]
) -> list[dict[str, str]]:
    """The ten rules that are never evaluated, once per session.

    `rms.assembly.subassemblies` names the subassembly documents it did not reach; the
    other nine are about the package as a whole and name no document.
    """
    written: list[dict[str, str]] = []
    subassemblies = _subassembly_document_ids(context.ir)
    for rule in coverage_only():
        if rule.coverage is None or session_holds(session, rule.id):
            continue
        bucket, reason = rule.coverage
        documents = subassemblies if rule.id == "rms.assembly.subassemblies" else []
        context.record_coverage(
            bucket,
            CoverageItem(
                check=rule.id,
                scope=scope_over(context, documents),
                reason=reason,
                error=None,
            ),
        )
        written.append({"bucket": bucket, "check": rule.id})
    return written


def _subassembly_document_ids(package: EvidencePackage) -> list[str]:
    """Every assembly document that is not the root, in package order."""
    root = package.design.root_assembly_document_id
    return [
        document.document_id
        for document in package.documents
        if document.kind == "assembly" and document.document_id != root
    ]
