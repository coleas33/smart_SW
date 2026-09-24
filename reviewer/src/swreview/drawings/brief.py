"""The per-part drawing brief: what a part is, how it goes together, what its drawing covers (011).

`contracts/brief.md` is normative. `build_brief` gives, for one part or assembly document of a
package, compact JSON in a fixed key order:

- `document` - the document, its configurations, its description (the profile's
  `hygiene.description_property` names the property; only the property's value is shown),
  material, mass and instance count;
- `assembly` - feature 010's joint map folded by pattern group: joint ids, kind, partners,
  the fastener, the largest offset; the session's contacts and interference findings naming it;
- `interfaces` - every tolerance subject feature 010's stack-up asks about on the document,
  what it resolves to (with 011's drawing source), the drawing record bound or why none, and
  feature 010's position budget callout for its joint;
- `drawing` - per drawing showing the document, what its views and sheets say, and the
  same-name candidate files;
- `answers` - the engineer's answered questions about the document or its components;
- `conformance` - the profile by identity and each drawing's comparison (User Story 7);
- `omitted` - per list, how many items were left out.

**Reused, never recomputed** (FR-042): the joint map is `joint_map_with_fasteners` (the tool
passes the context's cached one), the subjects are `joint_alignment.tolerance_subjects`, the
callout `check_nominal_alignment`'s, the tolerances `ResolverLookup`'s, the drawing answers
`drawing_answer`'s. **Bounded** (FR-040): each list is first cut to its bound, then items are
removed from the end of the currently longest list until the compact JSON is at most
`BRIEF_MAX_BYTES`, each removal counted; a brief never fails for size. **Deterministic**: every
list is in id order, so shuffling the package's arrays changes no byte. **Reference- and
profile-value-free** (FR-041): entities are named by package id; the profile by the first 12 hex
of its sha256, its settings never by value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from swreview.checks.drawing_context import compare_with_profile
from swreview.checks.fastener_identity import joint_map_with_fasteners
from swreview.checks.joint_alignment import check_nominal_alignment, tolerance_subjects
from swreview.checks.joints import Joint, JointMap
from swreview.checks.result import round_length
from swreview.checks.tolerances import (
    ResolvedTolerance,
    ResolverLookup,
    drawing_answer,
    drawing_record_states_limits,
    profile_sha256,
)
from swreview.drawings.evidence import DrawingIndex, ViewEvidence, file_name, id_order
from swreview.drawings.native import table_kind
from swreview.ir.models import Document, EvidencePackage

__all__ = [
    "BOUNDS",
    "BRIEF_MAX_BYTES",
    "BRIEF_VERSION",
    "TEXT_LIMIT",
    "BriefRefused",
    "DrawingBrief",
    "build_brief",
]

BRIEF_VERSION = 1
"""Feature 012 extends the brief additively under a new version (FR-043)."""

BRIEF_MAX_BYTES = 6_000
"""The compact JSON's bound: about 1,500 tokens, cheap to resend (research R2.16)."""

TEXT_LIMIT = 200
"""The longest note, reason, question or answer the brief carries, in characters."""

BOUNDS: dict[str, int] = {
    "assembly.joints": 20,
    "interfaces": 20,
    "drawing.notes": 10,
    "drawing.tables": 5,
    "drawing.table_rows": 10,
    "drawing.candidates": 10,
    "answers": 10,
}
"""Each list's bound before the byte bound (`contracts/brief.md` section 2); a list a drawing
entry holds is bounded per drawing."""

NO_DRAWING = "no open drawing shows it"
GTOL, DATUM, SURFACE_FINISH = 5, 2, 7
"""`swAnnotationType_e` of a geometric tolerance, a datum tag and a surface finish symbol."""


class BriefRefused(ValueError):
    """The document cannot be briefed; the message names the ones that can."""


@dataclass(frozen=True)
class DrawingBrief:
    """One document's brief, its keys in the contract's order."""

    content: dict[str, Any]

    def to_json(self) -> str:
        """The compact JSON (`separators=(",", ":")`, UTF-8) the bound is measured on."""
        return _compact(self.content)


def _compact(content: Any) -> str:
    return json.dumps(content, separators=(",", ":"), ensure_ascii=False)


def _short(text: str | None) -> str | None:
    """`text`, cut to `TEXT_LIMIT` characters with an ellipsis when it is longer."""
    if text is None or len(text) <= TEXT_LIMIT:
        return text
    return f"{text[: TEXT_LIMIT - 1]}…"


# --- the refusals (section 5) -----------------------------------------------------------------


def _refuse(package: EvidencePackage, index: DrawingIndex, document_id: str) -> Document:
    documents = {document.document_id: document for document in package.documents}
    document = documents.get(document_id)
    if document is None:
        briefable = sorted(
            (item.document_id for item in package.documents if item.kind != "drawing"),
            key=id_order,
        )
        raise BriefRefused(
            f"document {document_id} is not in this package; the documents that can be briefed "
            f"are: {', '.join(briefable[:20])}"
        )
    if document.kind == "drawing":
        shown = sorted(
            {view.document_id for view in index.views if view.drawing_id == document_id},
            key=id_order,
        )
        raise BriefRefused(
            f"{document_id} is a drawing; a brief is of a part or assembly. The documents it "
            f"shows: {', '.join(shown) or 'none'}"
        )
    return document


# --- the sections ---------------------------------------------------------------------------------


def _description(document: Document, profile: Any) -> str | None:
    hygiene = getattr(profile, "hygiene", None) if profile is not None else None
    name = hygiene.description_property if hygiene is not None else ""
    return _short(document.custom_properties.get(name)) if name else None


def _document_section(
    package: EvidencePackage, document: Document, components: list[str], profile: Any
) -> dict[str, Any]:
    used = [
        item.referenced_configuration
        for item in sorted(package.components, key=lambda item: id_order(item.id))
        if item.id in components and item.referenced_configuration
    ]
    configurations = list(dict.fromkeys(used)) or (
        [document.active_configuration] if document.active_configuration else []
    )
    return {
        "id": document.document_id,
        "file_name": document.file_name,
        "kind": document.kind,
        "configuration": configurations,
        "description": _description(document, profile),
        "material": document.material,
        "mass_kg": None if document.mass is None else document.mass.mass_kg,
        "instances": len(components),
    }


def _joints_on(joint_map: JointMap, components: set[str]) -> list[Joint]:
    return [joint for joint in joint_map.joints if components.intersection(joint.component_ids)]


def _assembly_section(
    package: EvidencePackage,
    session: Any,
    joint_map: JointMap,
    joints: list[Joint],
    components: set[str],
) -> dict[str, Any]:
    names = {document.document_id: document.file_name for document in package.documents}
    documents_of = {item.id: item.document_id for item in package.components}
    on = {joint.id for joint in joints}
    groups: list[dict[str, Any]] = []
    for joint_ids in joint_map.pattern_groups().values():
        members = [joint for joint in joint_map.joints if joint.id in joint_ids and joint.id in on]
        if not members:
            continue
        partners = sorted(
            {
                names.get(documents_of[component], documents_of[component])
                for joint in members
                for component in joint.component_ids
                if component not in components and component in documents_of
            }
        )
        fastener = next(
            (joint.fastener.designation for joint in members if joint.fastener is not None), None
        )
        groups.append(
            {
                "joint_ids": [joint.id for joint in members],
                "kind": members[0].kind,
                "partners": partners,
                "fastener": fastener,
                "offset_mm": round_length(max(joint.offset_mm for joint in members)),
            }
        )
    contacts = None
    interferences = None
    if session is not None:
        contacts = sum(
            1 for contact in session.contacts if components.intersection(contact.component_ids)
        )
        interferences = [
            finding.id
            for finding in session.findings
            if finding.check == "interference.static"
            and components.intersection(finding.component_ids)
        ]
    return {"joints": groups, "contacts": contacts, "interference_finding_ids": interferences}


def _tolerance_entry(answer: Any) -> dict[str, Any]:
    if isinstance(answer, ResolvedTolerance):
        entry: dict[str, Any] = {"source": answer.source_kind, "cited": _short(answer.cited)}
        if answer.also_found:
            entry["also_found"] = list(answer.also_found)
        if answer.conflict is not None:
            entry["conflict"] = _short(answer.conflict)
        return entry
    return {"unresolved": [[source, _short(why)] for source, why in answer.searched]}


def _interfaces_section(
    package: EvidencePackage, lookup: ResolverLookup, joints: list[Joint], document_id: str
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for joint in joints:
        subjects = [
            subject
            for subject in tolerance_subjects(joint, package)
            if subject.document_id == document_id
        ]
        if not subjects:
            continue
        alignment = check_nominal_alignment(joint, package, lookup)
        calculation = None if alignment is None else alignment.calculation
        callout = None if calculation is None else calculation.result.get("callout")
        for subject in subjects:
            drawing = drawing_answer(package, subject, index=lookup.index)
            entries.append(
                {
                    "subject": subject.label,
                    "joint_id": joint.id,
                    "tolerance": _tolerance_entry(lookup.resolve(subject)),
                    "drawing": (
                        {"record": drawing.record_id}
                        if drawing.record_id is not None
                        else {"why": _short(drawing.why)}
                    ),
                    "callout": callout,
                }
            )
    return entries


def _drawing_entry(
    package: EvidencePackage, index: DrawingIndex, drawing_id: str, views: list[ViewEvidence]
) -> dict[str, Any]:
    record = index.records[drawing_id]
    names = {document.document_id: document.file_name for document in package.documents}
    dimensions = [item for view in views for item in view.view.display_dimensions]
    annotations = [item for view in views for item in view.view.annotations]
    sheets = list(dict.fromkeys(view.sheet.id for view in views))
    on_sheets = [sheet for sheet in sorted(record.sheets, key=lambda s: s.index)
                 if sheet.id in sheets]
    notes = [
        _short(note.text)
        for sheet in on_sheets
        for view in sorted(sheet.views, key=lambda item: id_order(item.id))
        for note in sorted(view.notes, key=lambda item: id_order(item.id))
        if note.text is not None
    ]
    tables = [
        {
            "kind": table_kind(table.table_type_raw),
            "title": table.title,
            "rows": [list(row.cells) for row in sorted(table.rows, key=lambda row: row.index)],
        }
        for sheet in on_sheets
        for table in sorted(sheet.tables, key=lambda item: id_order(item.id))
    ]
    return {
        "document_id": drawing_id,
        "file_name": names.get(drawing_id, drawing_id),
        "sheets": len(record.sheets),
        "views_of_document": len(views),
        "usable_views": sum(1 for view in views if view.usable),
        "unusable": [_short(view.why) for view in views if not view.usable],
        "dimensions": len(dimensions),
        "toleranced": sum(1 for item in dimensions if drawing_record_states_limits(item)),
        "hole_callouts": sum(1 for item in dimensions if item.is_hole_callout),
        "gtols": sum(1 for item in annotations if item.type_raw == GTOL),
        "datums": [
            item.datum_label
            for item in annotations
            if item.type_raw == DATUM and item.datum_label is not None
        ],
        "surface_finishes": sum(1 for item in annotations if item.type_raw == SURFACE_FINISH),
        "notes": notes,
        "tables": tables,
    }


def _subtree_documents(package: EvidencePackage, components: set[str]) -> list[str]:
    """The documents instanced under `components`, at any depth: an assembly's own tree."""
    children: dict[str | None, list[str]] = {}
    for item in package.components:
        children.setdefault(item.parent_id, []).append(item.id)
    documents_of = {item.id: item.document_id for item in package.components}
    found: list[str] = []
    stack = list(components)
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(documents_of[child])
            stack.append(child)
    return found


def _drawing_section(
    package: EvidencePackage, index: DrawingIndex, document_id: str, components: set[str]
) -> dict[str, Any]:
    views = index.views_of(document_id)
    attached = [
        _drawing_entry(
            package, index, drawing, [view for view in views if view.drawing_id == drawing]
        )
        for drawing in index.drawings_of(document_id)
    ]
    covered = sorted({document_id, *_subtree_documents(package, components)}, key=id_order)
    candidates = [
        file_name(candidate.path)
        for covered_id in covered
        if (candidate := index.candidate_of(covered_id)) is not None
    ]
    section: dict[str, Any] = {"attached": attached, "candidates": candidates}
    if not attached:
        section = {"attached": [], "why": NO_DRAWING, "candidates": candidates}
    return section


def _answers_section(session: Any, subjects: set[str]) -> list[dict[str, Any]]:
    if session is None:
        return []
    return [
        {
            "request_id": request.id,
            "question": _short(request.question if request.question is not None else request.what),
            "answer": _short(request.answer),
        }
        for request in session.evidence_requests
        if request.status == "answered" and subjects.intersection(request.entity_ids)
    ]


def _conformance_section(
    package: EvidencePackage, index: DrawingIndex, profile: Any, document_id: str
) -> list[dict[str, Any]]:
    """Each drawing showing the document, compared with the profile's drawing standard: the
    settings that differ and those skipped, by name, never by value (User Story 7)."""
    showing = set(index.drawings_of(document_id))
    return [
        {"document_id": item.document_id, "differs": list(item.differs),
         "skipped": list(item.skipped)}
        for item in compare_with_profile(package, profile).drawings
        if item.document_id in showing
    ]


def _profile_identity(profile: Any) -> str | None:
    """The brief's `conformance.profile`: the profile's sha256 as `profile_sha256` reads it."""
    if profile is None:
        return None
    sha256 = profile_sha256(profile)
    if sha256 is None:
        return "a profile built in memory, with no file to name"
    return f"sha256 {sha256}"


# --- the bound (section 3) ---------------------------------------------------------------------


def _lists(content: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """Every list the bound may cut, by the name `omitted` counts it under, in key order."""
    found: list[tuple[str, list[Any]]] = [("assembly.joints", content["assembly"]["joints"])]
    if isinstance(content["assembly"]["interference_finding_ids"], list):
        found.append(
            ("assembly.interference_finding_ids", content["assembly"]["interference_finding_ids"])
        )
    found.append(("interfaces", content["interfaces"]))
    for drawing in content["drawing"]["attached"]:
        found.append(("drawing.unusable", drawing["unusable"]))
        found.append(("drawing.notes", drawing["notes"]))
        found.append(("drawing.tables", drawing["tables"]))
        found.extend(("drawing.table_rows", table["rows"]) for table in drawing["tables"])
    found.append(("drawing.attached", content["drawing"]["attached"]))
    found.append(("drawing.candidates", content["drawing"]["candidates"]))
    found.append(("answers", content["answers"]))
    found.append(("conformance.drawings", content["conformance"]["drawings"]))
    return found


def _bounded(content: dict[str, Any]) -> dict[str, Any]:
    """`content` with every list cut to its bound, then cut until it fits, each cut counted."""
    omitted: dict[str, int] = {}

    def cut(name: str, items: list[Any], keep: int) -> None:
        if len(items) > keep:
            omitted[name] = omitted.get(name, 0) + len(items) - keep
            del items[keep:]

    for bounded, keep in BOUNDS.items():  # in order, so a dropped table's rows are not counted
        for name, items in _lists(content):
            if name == bounded:
                cut(name, items, keep)
    content["omitted"] = omitted
    while len(_compact(content).encode("utf-8")) > BRIEF_MAX_BYTES:
        candidates = [(name, items) for name, items in _lists(content) if items]
        if not candidates:
            break
        longest = max(len(items) for _, items in candidates)
        name, items = next(entry for entry in candidates if len(entry[1]) == longest)
        cut(name, items, len(items) - 1)
    content["omitted"] = dict(sorted(omitted.items()))
    return content


# --- the brief ------------------------------------------------------------------------------------


def build_brief(
    package: EvidencePackage,
    session: Any,
    profile: Any,
    document_id: str,
    *,
    joint_map: JointMap | None = None,
) -> DrawingBrief:
    """The brief of one part or assembly document (`contracts/brief.md`).

    `session` supplies the answers, contacts and interference findings, `profile` the
    description property's name, the general tolerance and the drawing standard; either may be
    `None`, and the sections that need them say so rather than guess. `joint_map` is the
    context's cached map when a tool asks, built here otherwise. Raises `BriefRefused` for an
    id that is not a document of the package, or that is a drawing.
    """
    lookup = ResolverLookup(package, profile)
    index = lookup.index
    document = _refuse(package, index, document_id)
    components = [
        item.id
        for item in sorted(package.components, key=lambda item: id_order(item.id))
        if item.document_id == document_id
    ]
    component_set = set(components)
    joint_map = joint_map if joint_map is not None else joint_map_with_fasteners(package)[1]
    joints = _joints_on(joint_map, component_set)
    content: dict[str, Any] = {
        "brief_version": BRIEF_VERSION,
        "document": _document_section(package, document, components, profile),
        "assembly": _assembly_section(package, session, joint_map, joints, component_set),
        "interfaces": _interfaces_section(package, lookup, joints, document_id),
        "drawing": _drawing_section(package, index, document_id, component_set),
        "answers": _answers_section(session, {document_id, *component_set}),
        "conformance": {
            "profile": _profile_identity(profile),
            "drawings": _conformance_section(package, index, profile, document_id),
        },
        "omitted": {},
    }
    return DrawingBrief(content=_bounded(content))
