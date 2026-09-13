"""Package query tools: everything the model can read out of the evidence package.

One function per row of the "Package query tools" table in contracts/agent-tools.md.
They are pure with respect to the package - nothing here writes to the session, loads a
mesh, or talks to SOLIDWORKS - and they return JSON-serializable dicts and lists that
`swreview.tools.registry` serializes and records.

Two rules run through all of them (constitution Principle I):

- a value the extractor could not obtain stays `null` and is labelled, never estimated;
  `list_holes` is the case that matters most, so an unknown usable thread depth comes
  back as `thread_depth: null` plus `thread_depth_note: "unknown"`;
- an argument that names nothing in the package comes back as an error result, so the
  model sees the mistake as a tool result instead of the run dying.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Any

from swreview.exceptions import ExceptionStore
from swreview.ir.models import (
    BBox2D,
    Dimension,
    DrawingSheet,
    EvidencePackage,
    Hole,
)
from swreview.tools.context import (
    current_context,
    error_result,
    not_one_of,
    unknown_id,
)

HOLE_TYPES: tuple[str, ...] = (
    "tapped",
    "clearance",
    "counterbore",
    "countersink",
    "simple",
    "unknown",
)
FASTENER_KINDS: tuple[str, ...] = ("screw", "bolt", "nut", "washer", "pin", "other")

ToolResult = dict[str, Any]


def as_json(model: Any) -> dict[str, Any]:
    """One place where an IR model becomes the JSON a tool result carries."""
    return model.model_dump(mode="json")


def package_summary(package: EvidencePackage) -> dict[str, Any]:
    """The census `get_package_summary` returns, also used to open the system prompt."""
    return {
        "design_id": package.design.design_id,
        "design_name": package.design.name,
        "configuration": package.design.active_configuration,
        "root_assembly_document_id": package.design.root_assembly_document_id,
        "drawing_document_ids": list(package.design.drawing_document_ids),
        "document_count": len(package.documents),
        "component_count": len(package.components),
        "mate_count": len(package.mates),
        "hole_count": len(package.holes),
        "fastener_count": len(package.fasteners),
        "interference_count": len(package.interferences),
        "drawing_sheet_count": len(package.drawings),
        "capture_count": len(package.captures),
        "gap_count": len(package.gaps),
        "manifest_discrepancies": [as_json(item) for item in package.manifest.discrepancies],
        "extractor": {
            "name": package.extractor.name,
            "version": package.extractor.version,
            "sw_version": package.extractor.sw_version,
        },
    }


def get_package_summary() -> ToolResult:
    """Census of the evidence package under review. Call this first.

    Reports the design, its active configuration, how many documents, components, holes,
    fasteners and drawing sheets were extracted, every manifest discrepancy, and how many
    gaps the extractor recorded.
    """
    return package_summary(current_context().ir)


def list_components(
    parent_id: str | None = None,
    include_suppressed: bool = True,
) -> list[dict[str, Any]] | ToolResult:
    """List the component instances directly under one parent.

    Args:
        parent_id: Parent component instance id, or null for the top level of the
            assembly.
        include_suppressed: Keep instances whose suppression state is `suppressed`.
    """
    context = current_context()
    if parent_id is not None and context.component(parent_id) is None:
        return unknown_id("component", parent_id)
    components = [item for item in context.ir.components if item.parent_id == parent_id]
    if not include_suppressed:
        components = [item for item in components if item.suppression != "suppressed"]
    return [
        {
            "id": item.id,
            "name": item.name,
            "full_path": item.full_path,
            "document_id": item.document_id,
            "referenced_configuration": item.referenced_configuration,
            "suppression": item.suppression,
            "pattern_id": item.pattern_id,
            "is_toolbox": item.is_toolbox,
        }
        for item in components
    ]


def get_component(component_id: str) -> ToolResult:
    """Everything the package holds about one component instance.

    Returns the instance itself plus the holes, fasteners, faces and mates that belong
    to it.

    Args:
        component_id: Component instance id, for example `cmp:0001`.
    """
    context = current_context()
    component = context.component(component_id)
    if component is None:
        return unknown_id("component", component_id)
    package = context.ir
    return {
        "component": as_json(component),
        "document": as_json(context.document(component.document_id))
        if context.document(component.document_id) is not None
        else None,
        "holes": [as_json(item) for item in package.holes if item.component_id == component_id],
        "fasteners": [
            as_json(item) for item in package.fasteners if item.component_id == component_id
        ],
        "faces": [as_json(item) for item in package.faces if item.component_id == component_id],
        "mates": [as_json(item) for item in _mates_touching(package, component_id)],
    }


def find_components(name_pattern: str, document_id: str | None = None) -> list[str] | ToolResult:
    """Component instance ids whose name or instance path matches a glob.

    Matching is case-insensitive; `*`, `?` and `[seq]` work as in a shell glob.

    Args:
        name_pattern: Glob such as `M6*` or `*housing*`.
        document_id: Restrict to instances of one document, or null for all.
    """
    context = current_context()
    if document_id is not None and context.document(document_id) is None:
        return unknown_id("document", document_id)
    pattern = name_pattern.lower()
    return [
        item.id
        for item in context.ir.components
        if (document_id is None or item.document_id == document_id)
        and (
            fnmatchcase(item.name.lower(), pattern)
            or fnmatchcase(item.full_path.lower(), pattern)
        )
    ]


def _mates_touching(package: EvidencePackage, component_id: str | None) -> list[Any]:
    if component_id is None:
        return list(package.mates)
    return [
        mate
        for mate in package.mates
        if any(entity.component_id == component_id for entity in mate.entities)
    ]


def list_mates(component_id: str | None = None) -> list[dict[str, Any]] | ToolResult:
    """Mates, optionally only those that touch one component instance.

    Args:
        component_id: Component instance id, or null for every mate in the assembly.
    """
    context = current_context()
    if component_id is not None and context.component(component_id) is None:
        return unknown_id("component", component_id)
    return [as_json(mate) for mate in _mates_touching(context.ir, component_id)]


def _hole_result(hole: Hole) -> dict[str, Any]:
    """A hole as JSON, with a null `thread_depth` always explained.

    `thread_depth` is never derived from `hole_depth`: drill depth is not usable thread
    (constitution Principle I). A null on a threaded hole means the extractor did not get
    it - `"unknown"` - and the note is there so the model cannot read that null as "no
    thread" or quietly substitute the drill depth. A null on an unthreaded hole means
    exactly what it says, and says so instead.
    """
    data = as_json(hole)
    if hole.thread_depth is None:
        threaded = hole.hole_type == "tapped" or hole.thread_designation is not None
        data["thread_depth_note"] = "unknown" if threaded else "not a threaded hole"
    return data


def list_holes(
    component_id: str | None = None,
    hole_type: str | None = None,
) -> list[dict[str, Any]] | ToolResult:
    """Holes, optionally filtered by component instance and hole type.

    A hole whose usable thread depth was not reported comes back with
    `thread_depth: null` and `thread_depth_note: "unknown"`. Drill depth
    (`hole_depth`) is not usable thread depth and must not be used as one.

    Args:
        component_id: Component instance id, or null for every hole.
        hole_type: One of tapped, clearance, counterbore, countersink, simple, unknown;
            null for every type.
    """
    context = current_context()
    if component_id is not None and context.component(component_id) is None:
        return unknown_id("component", component_id)
    if hole_type is not None and hole_type not in HOLE_TYPES:
        return not_one_of("hole_type", hole_type, HOLE_TYPES)
    return [
        _hole_result(hole)
        for hole in context.ir.holes
        if (component_id is None or hole.component_id == component_id)
        and (hole_type is None or hole.hole_type == hole_type)
    ]


def list_fasteners(
    component_id: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]] | ToolResult:
    """Fasteners with the source their identity came from.

    `identity_source` says how much the thread designation and length can be trusted:
    `toolbox` is Toolbox data, `name_parse` was read out of a file name.

    Args:
        component_id: Component instance id, or null for every fastener.
        kind: One of screw, bolt, nut, washer, pin, other; null for every kind.
    """
    context = current_context()
    if component_id is not None and context.component(component_id) is None:
        return unknown_id("component", component_id)
    if kind is not None and kind not in FASTENER_KINDS:
        return not_one_of("kind", kind, FASTENER_KINDS)
    return [
        as_json(fastener)
        for fastener in context.ir.fasteners
        if (component_id is None or fastener.component_id == component_id)
        and (kind is None or fastener.kind == kind)
    ]


def list_interferences(
    configuration: str | None = None,
    component_id: str | None = None,
) -> list[dict[str, Any]] | ToolResult:
    """Interference results grouped by `group_key`, including truncated and failed ones.

    A group whose status is not `computed` is not a clear result: it is unresolved
    coverage and has to be reported as such.

    Args:
        configuration: Configuration name the results were computed in, or null for all.
        component_id: Keep only groups that involve this component instance, or null.
    """
    context = current_context()
    if component_id is not None and context.component(component_id) is None:
        return unknown_id("component", component_id)
    groups: dict[str, list[Any]] = {}
    for item in context.ir.interferences:
        if configuration is not None and item.configuration != configuration:
            continue
        if component_id is not None and component_id not in item.component_ids:
            continue
        groups.setdefault(item.group_key, []).append(item)
    return [
        {
            "group_key": group_key,
            "count": len(items),
            "statuses": sorted({item.status for item in items}),
            "configurations": sorted({item.configuration for item in items}),
            "interferences": [as_json(item) for item in items],
        }
        for group_key, items in groups.items()
    ]


def sheet_reason(package: EvidencePackage, sheet: DrawingSheet) -> str | None:
    """Why a sheet is not readable, taken from the gap the ingester recorded."""
    if sheet.parse_status == "text":
        return None
    for gap in package.gaps:
        if gap.entity_id in (sheet.document_id, sheet.sheet_name):
            return gap.reason
    return f"sheet parse_status is {sheet.parse_status!r}; no dimension text is available"


def get_drawing_sheet(document_id: str, sheet_name: str | None = None) -> ToolResult:
    """One drawing sheet: its notes, dimensions, views and parse status.

    When `parse_status` is not `text` the sheet carries no readable dimensions and the
    result says why. That is unresolved coverage, not a pass.

    Args:
        document_id: Drawing document id.
        sheet_name: Sheet name, or null for the first sheet of the document.
    """
    context = current_context()
    if context.document(document_id) is None:
        return unknown_id("document", document_id)
    sheets = [sheet for sheet in context.ir.drawings if sheet.document_id == document_id]
    if not sheets:
        return error_result(f"document {document_id!r} has no extracted drawing sheets")
    if sheet_name is None:
        sheet = sheets[0]
    else:
        matching = [item for item in sheets if item.sheet_name == sheet_name]
        if not matching:
            return error_result(
                f"document {document_id!r} has no sheet {sheet_name!r}; "
                f"available: {[item.sheet_name for item in sheets]}"
            )
        sheet = matching[0]
    result = as_json(sheet)
    result["available_sheets"] = [item.sheet_name for item in sheets]
    result["reason"] = sheet_reason(context.ir, sheet)
    return result


def _bbox_contains(view_bbox: BBox2D, bbox: BBox2D) -> bool:
    x0, y0, x1, y1 = view_bbox
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return min(x0, x1) <= center_x <= max(x0, x1) and min(y0, y1) <= center_y <= max(y0, y1)


def _near_view(sheet: DrawingSheet, dimension: Dimension, view_name: str) -> bool:
    """True when the dimension names the view, or sits inside the view's box."""
    if dimension.source.view == view_name:
        return True
    if dimension.source.bbox is None:
        return False
    for view in sheet.views:
        if view.name == view_name:
            return _bbox_contains(view.bbox, dimension.source.bbox)
    return False


def find_dimensions(
    document_id: str | None = None,
    text_regex: str | None = None,
    near_view: str | None = None,
) -> list[dict[str, Any]] | ToolResult:
    """Dimensions read off drawing sheets, with the text exactly as it was read.

    `text_as_read` is the raw callout; `nominal` and `tolerance` are what the dimension
    grammar made of it. A tolerance whose kind is `none` was not stated on the drawing.

    Args:
        document_id: Restrict to one drawing document, or null for all.
        text_regex: Python regular expression matched against `text_as_read`, or null.
        near_view: Keep dimensions attached to, or inside the box of, this view.
    """
    context = current_context()
    if document_id is not None and context.document(document_id) is None:
        return unknown_id("document", document_id)
    pattern = None
    if text_regex is not None:
        try:
            pattern = re.compile(text_regex)
        except re.error as exc:
            return error_result(f"text_regex {text_regex!r} is not a valid regex: {exc}")
    results: list[dict[str, Any]] = []
    for sheet in context.ir.drawings:
        if document_id is not None and sheet.document_id != document_id:
            continue
        for dimension in sheet.dimensions:
            if pattern is not None and pattern.search(dimension.text_as_read) is None:
                continue
            if near_view is not None and not _near_view(sheet, dimension, near_view):
                continue
            entry = as_json(dimension)
            entry["document_id"] = sheet.document_id
            entry["sheet_name"] = sheet.sheet_name
            results.append(entry)
    return results


def list_gaps() -> list[dict[str, Any]]:
    """Everything the extractor could not provide, and why.

    A gap is the reason a check stays unresolved. Read this early: it bounds what can be
    concluded from this package at all.
    """
    return [as_json(gap) for gap in current_context().ir.gaps]


def get_exceptions(check: str | None = None) -> list[dict[str, Any]]:
    """Retained exceptions (previously accepted conditions) that apply to this package.

    Empty when no exception store is wired to this run, which is the case for a package
    reviewed without the exception store.

    Args:
        check: Restrict to one check identifier, or null for every exception.
    """
    context = current_context()
    if not context.exceptions:
        return []
    if isinstance(context.exceptions, ExceptionStore):
        return [as_json(item) for item in context.exceptions.for_check(check)]
    entries = [
        item if isinstance(item, dict) else as_json(item)
        for item in context.exceptions
        if item is not None
    ]
    active = [entry for entry in entries if entry.get("status") in ("active", "needs_review")]
    if check is None:
        return active
    return [entry for entry in active if entry.get("check") == check]

