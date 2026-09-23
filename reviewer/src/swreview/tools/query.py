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

import json
import re
from fnmatch import fnmatchcase
from typing import Annotated, Any, Literal

from pydantic import Field

from swreview.drawings.native import native_sheet_count
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
COMPACT_PAGE_LIMIT = 20
COMPACT_ITEM_TEXT_LIMIT = 120
COMPACT_LIST_LIMIT = 20
COMPACT_RESPONSE_BYTES = 6000

CompactKind = Literal["components", "faces", "holes", "mates", "fasteners"]

ToolResult = dict[str, Any]


def as_json(model: Any) -> dict[str, Any]:
    """One place where an IR model becomes the JSON a tool result carries."""
    return model.model_dump(mode="json")


def package_summary(package: EvidencePackage) -> dict[str, Any]:
    """The census `get_package_summary` returns, also used to open the system prompt.

    `native_drawing_sheet_count` (feature 011) sits beside the ingested count only when the
    drawing phase read a sheet, so a package without one is summarized to its old bytes.
    """
    native = native_sheet_count(package)
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
        **({"native_drawing_sheet_count": native} if native else {}),
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

    Notes:
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

    Args:
        component_id: Component instance id, for example `cmp:0001`.

    Notes:
        Returns the instance itself plus the holes, fasteners, faces and mates that belong
        to it.
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


def _compact_text(value: object, field: str, truncated: list[str]) -> str | None:
    """Bound descriptive text while naming the omitted tail for exact retrieval."""
    if value is None:
        return None
    text = str(value)
    if len(text) <= COMPACT_ITEM_TEXT_LIMIT:
        return text
    truncated.append(field)
    return text[: COMPACT_ITEM_TEXT_LIMIT - 1] + "…"


def _compact_ids(values: list[str], field: str, truncated: list[str]) -> tuple[list[str], int]:
    """Keep reference lists bounded without hiding how many references need detail."""
    # IDs are evidence keys. Keep each selected key exact so the accompanying detail
    # pointer is immediately callable; the list itself is structurally bounded.
    kept = list(values[:COMPACT_LIST_LIMIT])
    return kept, max(0, len(values) - len(kept))


def _compact_record(kind: CompactKind, item: Any) -> dict[str, Any]:
    """Project one item to bounded discovery fields; detail remains queryable by id."""
    truncated: list[str] = []
    if kind == "components":
        record = {
            "id": item.id,
            "name": _compact_text(item.name, "name", truncated),
            "document_id": item.document_id,
            "referenced_configuration": _compact_text(
                item.referenced_configuration, "referenced_configuration", truncated
            ),
            "suppression": item.suppression,
            "pattern_id": item.pattern_id,
            "is_toolbox": item.is_toolbox,
            "detail_tool": "get_component",
            "detail_id": item.id,
        }
        # full_path and persistent references are intentionally discoverable through the
        # existing detail query, never silently presented as complete compact data.
        record["omitted_fields"] = ["full_path", "persist_ref", "transform"]
    elif kind == "faces":
        record = {
            "id": item.id,
            "component_id": item.component_id,
            "body_id": item.body_id,
            "kind": _compact_text(item.kind, "kind", truncated),
            "bbox": as_json(item.bbox),
            "area_m2": item.area_m2,
            "cylinder": as_json(item.cylinder) if item.cylinder is not None else None,
            "plane": as_json(item.plane) if item.plane is not None else None,
            "detail_tool": "get_component",
            "detail_id": item.component_id,
            "omitted_fields": ["persist_ref", "persist_ref_scope"],
        }
    elif kind == "holes":
        face_ids, omitted_faces = _compact_ids(item.face_ids, "face_ids", truncated)
        record = {
            "id": item.id,
            "component_id": item.component_id,
            "feature_name": _compact_text(item.feature_name, "feature_name", truncated),
            "hole_type": item.hole_type,
            "standard": _compact_text(item.standard, "standard", truncated),
            "size": _compact_text(item.size, "size", truncated),
            "thread_designation": _compact_text(
                item.thread_designation, "thread_designation", truncated
            ),
            "thread_depth": as_json(item.thread_depth)
            if item.thread_depth is not None
            else None,
            "hole_depth": as_json(item.hole_depth) if item.hole_depth is not None else None,
            "end_condition": item.end_condition,
            "diameter": as_json(item.diameter) if item.diameter is not None else None,
            "axis": as_json(item.axis),
            "face_ids": face_ids,
            "face_ids_omitted": omitted_faces,
            "detail_tool": "get_component",
            "detail_id": item.component_id,
            "omitted_fields": ["persist_ref", "persist_ref_scope"],
        }
    elif kind == "mates":
        component_ids, omitted_components = _compact_ids(
            [entity.component_id for entity in item.entities], "component_ids", truncated
        )
        resolution = [entity.resolution_status for entity in item.entities]
        resolution, omitted_resolution = _compact_ids(
            [str(value) if value is not None else "unknown" for value in resolution],
            "entity_resolution",
            truncated,
        )
        record = {
            "id": item.id,
            "type": _compact_text(item.type, "type", truncated),
            "component_ids": component_ids,
            "component_ids_omitted": omitted_components,
            "entity_resolution": resolution,
            "entity_resolution_omitted": omitted_resolution,
            "alignment": item.alignment,
            "suppressed": item.suppressed,
            "distance": as_json(item.distance) if item.distance is not None else None,
            "angle": as_json(item.angle) if item.angle is not None else None,
            "detail_tool": "list_mates",
            "detail_component_id": component_ids[0] if component_ids else None,
            "omitted_fields": ["persist_ref", "persist_ref_scope", "entity_persist_refs"],
        }
    else:
        record = {
            "id": item.id,
            "component_id": item.component_id,
            "kind": _compact_text(item.kind, "kind", truncated),
            "identity_source": _compact_text(item.identity_source, "identity_source", truncated),
            "thread_designation": _compact_text(
                item.thread_designation, "thread_designation", truncated
            ),
            "length": as_json(item.length) if item.length is not None else None,
            "head_type": _compact_text(item.head_type, "head_type", truncated),
            "head_diameter": as_json(item.head_diameter)
            if item.head_diameter is not None
            else None,
            "head_height": as_json(item.head_height) if item.head_height is not None else None,
            "drive": _compact_text(item.drive, "drive", truncated),
            "axis": as_json(item.axis),
            "material": _compact_text(item.material, "material", truncated),
            "detail_tool": "list_fasteners",
            "detail_component_id": item.component_id,
            "omitted_fields": ["persist_ref", "persist_ref_scope"],
        }
    if truncated:
        record["truncated_fields"] = truncated
    if kind == "holes":
        _label_thread_depth(record, item)
    return record


def compact_query(
    kind: CompactKind,
    scope_id: str | None = None,
    cursor: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=COMPACT_PAGE_LIMIT)] = COMPACT_PAGE_LIMIT,
    include_suppressed: bool = True,
) -> ToolResult:
    """Return a bounded, paginated discovery page for one package entity family.

    Use this for the first pass over a large family, then follow each record's detail
    pointer for complete evidence; the compact page is never a verdict or a replacement
    for the existing full query.

    Args:
        kind: One of components, faces, holes, mates or fasteners.
        scope_id: For components, the parent component id; for other kinds, a component id;
            null means the package-wide list or top-level components.
        cursor: Zero-based item offset returned as `next_cursor` by the previous page.
        limit: Number of items, from 1 through 20.
        include_suppressed: Keep suppressed components when kind is components.

    Returns:
        A stable package-order page with total, shown, omitted, omitted_before,
        omitted_after, omitted_by_budget and next_cursor metadata. The serialized response
        is capped at ``COMPACT_RESPONSE_BYTES`` UTF-8 bytes. Compact records preserve
        engineering values and unknown/null semantics; omitted discovery fields identify
        the existing detail query that retrieves them.
    """
    context = current_context()
    if scope_id is not None and context.component(scope_id) is None:
        safe_scope = scope_id
        if len(safe_scope) > COMPACT_ITEM_TEXT_LIMIT:
            safe_scope = safe_scope[: COMPACT_ITEM_TEXT_LIMIT - 1] + "…"
        return unknown_id("component", safe_scope)
    package = context.ir
    if kind == "components":
        items = [item for item in package.components if item.parent_id == scope_id]
        if not include_suppressed:
            items = [item for item in items if item.suppression != "suppressed"]
    elif kind == "mates":
        items = _mates_touching(package, scope_id)
    else:
        source = getattr(package, kind)
        items = [
            item
            for item in source
            if scope_id is None or item.component_id == scope_id
        ]
    total = len(items)
    candidates = items[cursor : cursor + limit]
    page: list[dict[str, Any]] = []
    budget_omitted = 0

    display_scope = scope_id
    scope_truncated = False
    if display_scope is not None and len(display_scope) > COMPACT_ITEM_TEXT_LIMIT:
        display_scope = display_scope[: COMPACT_ITEM_TEXT_LIMIT - 1] + "…"
        scope_truncated = True

    def payload(
        next_cursor: int | None,
        *,
        oversized_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        end = cursor + len(page)
        result: dict[str, Any] = {
            "kind": kind,
            "scope_id": display_scope,
            "cursor": cursor,
            "limit": limit,
            "total": total,
            "shown": len(page),
            "omitted": total - len(page),
            "omitted_before": min(cursor, total),
            "omitted_after": max(0, total - end),
            "omitted_by_budget": budget_omitted,
            "next_cursor": next_cursor,
            "items": page,
        }
        if scope_truncated:
            result["scope_id_truncated"] = True
        if oversized_record is not None:
            oversized = {
                "index": cursor,
                "detail_tool": oversized_record.get("detail_tool"),
                "reason": "item exceeds the compact response byte budget; use the detail tool",
            }
            for key in ("detail_id", "detail_component_id"):
                value = oversized_record.get(key)
                if value is not None and len(value) <= COMPACT_ITEM_TEXT_LIMIT:
                    oversized[key] = value
                elif value is not None:
                    oversized[f"{key}_omitted"] = True
            fallback_tool = {
                "components": "list_components",
                "faces": "get_component",
                "holes": "list_holes",
                "mates": "list_mates",
                "fasteners": "list_fasteners",
            }[kind]
            pointer_scope = (
                oversized_record.get("detail_id")
                or oversized_record.get("detail_component_id")
                or scope_id
            )
            fallback_argument = {
                "components": {"parent_id": scope_id},
                "faces": {"component_id": pointer_scope},
                "holes": {"component_id": pointer_scope},
                "mates": {"component_id": pointer_scope},
                "fasteners": {"component_id": pointer_scope},
            }[kind]
            # A huge key itself cannot fit in the bounded refusal. The full family query
            # plus this page index remains a callable fallback, and the next cursor moves
            # past the item so the caller is never trapped retrying it.
            if any(
                value is not None and len(value) > COMPACT_ITEM_TEXT_LIMIT
                for value in fallback_argument.values()
            ):
                fallback_argument = {
                    key: None for key in fallback_argument
                }
                oversized["fallback_scope_omitted"] = True
                if kind == "faces":
                    fallback_tool = "find_components"
                    fallback_argument = {"name_pattern": "*", "document_id": None}
                    oversized["fallback_instructions"] = (
                        "Recover the full component id, then call get_component with it."
                    )
            oversized["fallback_tool"] = fallback_tool
            oversized["fallback_arguments"] = fallback_argument
            result["oversized_item"] = oversized
        return result

    for item in candidates:
        candidate = _compact_record(kind, item)
        trial = [*page, candidate]
        page[:] = trial
        budget_omitted = len(candidates) - len(page)
        end = cursor + len(page)
        trial_payload = payload(end if end < total else None)
        # Default JSON encoding also covers providers that escape Unicode and add spaces.
        size = len(json.dumps(trial_payload).encode("utf-8"))
        if size <= COMPACT_RESPONSE_BYTES:
            continue
        page.pop()
        break

    # Every candidate after the first one that did not fit is omitted for the same
    # byte-budget reason; report the complete count so pagination metadata is auditable.
    budget_omitted = len(candidates) - len(page)
    if not page and candidates:
        # Always advance past a pathological record, so a caller cannot be trapped on
        # one imported value forever. Normal records are bounded by the projection above.
        return payload(
            cursor + 1 if cursor + 1 < total else None,
            oversized_record=_compact_record(kind, candidates[0]),
        )

    next_cursor = cursor + len(page)
    return payload(next_cursor if next_cursor < total else None)


def find_components(name_pattern: str, document_id: str | None = None) -> list[str] | ToolResult:
    """Component instance ids whose name or instance path matches a glob.

    Args:
        name_pattern: Glob such as `M6*` or `*housing*`.
        document_id: Restrict to instances of one document, or null for all.

    Notes:
        Matching is case-insensitive; `*`, `?` and `[seq]` work as in a shell glob.
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


def _label_thread_depth(data: dict[str, Any], hole: Hole) -> None:
    """The same unknown/non-threaded distinction in full and compact evidence."""
    if hole.thread_depth is None:
        threaded = hole.hole_type == "tapped" or hole.thread_designation is not None
        data["thread_depth_note"] = "unknown" if threaded else "not a threaded hole"


def _hole_result(hole: Hole) -> dict[str, Any]:
    """A hole as JSON, with a null `thread_depth` always explained.

    `thread_depth` is never derived from `hole_depth`: drill depth is not usable thread
    (constitution Principle I). A null on a threaded hole means the extractor did not get
    it - `"unknown"` - and the note is there so the model cannot read that null as "no
    thread" or quietly substitute the drill depth. A null on an unthreaded hole means
    exactly what it says, and says so instead.
    """
    data = as_json(hole)
    _label_thread_depth(data, hole)
    return data


def list_holes(
    component_id: str | None = None,
    hole_type: str | None = None,
) -> list[dict[str, Any]] | ToolResult:
    """Holes, optionally filtered by component instance and hole type.

    Args:
        component_id: Component instance id, or null for every hole.
        hole_type: One of tapped, clearance, counterbore, countersink, simple, unknown;
            null for every type.

    Notes:
        A hole whose usable thread depth was not reported comes back with
        `thread_depth: null` and `thread_depth_note: "unknown"`. Drill depth
        (`hole_depth`) is not usable thread depth and must not be used as one.
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

    Args:
        component_id: Component instance id, or null for every fastener.
        kind: One of screw, bolt, nut, washer, pin, other; null for every kind.

    Notes:
        `identity_source` says how much the thread designation and length can be trusted:
        `toolbox` is Toolbox data, `name_parse` was read out of a file name.
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

    Args:
        configuration: Configuration name the results were computed in, or null for all.
        component_id: Keep only groups that involve this component instance, or null.

    Notes:
        A group whose status is not `computed` is not a clear result: it is unresolved
        coverage and has to be reported as such.
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

    Args:
        document_id: Drawing document id.
        sheet_name: Sheet name, or null for the first sheet of the document.

    Notes:
        When `parse_status` is not `text` the sheet carries no readable dimensions and the
        result says why. That is unresolved coverage, not a pass.
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

    Args:
        document_id: Restrict to one drawing document, or null for all.
        text_regex: Python regular expression matched against `text_as_read`, or null.
        near_view: Keep dimensions attached to, or inside the box of, this view.

    Notes:
        `text_as_read` is the raw callout; `nominal` and `tolerance` are what the dimension
        grammar made of it. A tolerance whose kind is `none` was not stated on the drawing.
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

    Notes:
        A gap is the reason a check stays unresolved. Read this early: it bounds what can be
        concluded from this package at all.
    """
    return [as_json(gap) for gap in current_context().ir.gaps]


def get_exceptions(check: str | None = None) -> list[dict[str, Any]]:
    """Retained exceptions (previously accepted conditions) that apply to this package.

    Args:
        check: Restrict to one check identifier, or null for every exception.

    Notes:
        Empty when no exception store is wired to this run, which is the case for a package
        reviewed without the exception store.
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

