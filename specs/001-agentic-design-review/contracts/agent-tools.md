# Curated Agent Tools

The reviewer exposes exactly these tools to Claude. There is no general code execution,
no file system access, and no SolidWorks command outside this list (FR-006, Constitution
Technical Constraints). Every tool is a Python function decorated with the Anthropic SDK's
`@beta_tool`, declared with `strict: true` (schema-valid arguments guaranteed), and
registered in `swreview.tools`. Each call is appended to the session's `steps` list with its
arguments, result summary, status, and elapsed time (FR-004).

Every tool is **read-only** with respect to the evidence package and SolidWorks documents.
The only writes are to the current session file (findings, evidence requests, coverage).

All tool errors are returned to the model as `tool_result` with `is_error: true` and a
plain explanation, and recorded as a `failed` coverage item. Tools never raise past the
runner.

## Package query tools (pure, no SolidWorks)

| Tool | Arguments | Returns | Notes |
|------|-----------|---------|-------|
| `get_package_summary` | none | design name, configuration, document count, component count, manifest discrepancies, gap count | Always the first call. |
| `list_components` | `parent_id: str \| null`, `include_suppressed: bool = true` | list of `{id, name, document_id, referenced_configuration, suppression, pattern_id, is_toolbox}` | Flat listing under a parent. |
| `get_component` | `component_id: str` | full `ComponentInstance` plus its holes, fasteners, faces, mates | |
| `find_components` | `name_pattern: str` (glob), `document_id: str \| null` | matching ids | |
| `list_mates` | `component_id: str \| null` | mates touching the component | |
| `list_holes` | `component_id: str \| null`, `hole_type: str \| null` | `Hole` list | `thread_depth == null` is returned as `"unknown"` text plus the null; never estimated. |
| `list_fasteners` | `component_id: str \| null`, `kind: str \| null` | `Fastener` list with `identity_source` | |
| `list_interferences` | `configuration: str \| null`, `component_id: str \| null` | grouped interferences with status | Truncated/failed entries included with status. |
| `get_drawing_sheet` | `document_id: str`, `sheet_name: str \| null` | notes, dimensions with `text_as_read`, views, `parse_status` | `parse_status != "text"` returns the reason. |
| `find_dimensions` | `document_id: str \| null`, `text_regex: str \| null`, `near_view: str \| null` | matching `Dimension` list with source refs | |
| `list_gaps` | none | `Gap` list | What extraction could not provide. |
| `get_exceptions` | `check: str \| null` | active and needs-review exceptions matching this package | |

## Measurement tools (deterministic Python; may load meshes)

| Tool | Arguments | Returns | Calculation model |
|------|-----------|---------|-------------------|
| `measure_axis_distance` | `hole_id_a: str`, `hole_id_b: str` | perpendicular distance and angle between axes, as `Quantity`/`Angle`, in world frame | `geometry.axis_distance` |
| `measure_face_gap` | `face_id_a: str`, `face_id_b: str` | signed gap between two parallel planes or coaxial cylinders, or `unsupported` | `geometry.face_gap` |
| `check_tool_envelope` | `fastener_id: str`, `tool: "hex_key" \| "socket" \| "screwdriver"`, `length: Quantity` | list of intersecting component ids and first-hit distance, or `unresolved` if meshes are missing | `geometry.envelope_raycast` (trimesh + embreex when available) |
| `bounding_box` | `component_id: str` | world AABB | |

## Check tools (deterministic Python; produce Findings)

Each check tool writes a `Finding` to the session and returns it. Inputs must be explicit
ids or `Dimension`s already present in the package; a check never accepts a raw number
typed by the model.

| Tool | Arguments | Produces |
|------|-----------|----------|
| `check_fit` | `bore_dimension_ref: SourceRef`, `shaft_dimension_ref: SourceRef` | `fit.size_only` finding: min/max clearance or interference |
| `check_axial_stack` | `dimension_refs: list[SourceRef]`, `signs: list[+1 \| -1]`, `target_gap: SourceRef \| null` | `stack.worst_case` finding; `unresolved` if any tolerance kind is `none` |
| `check_fastener_joint` | `fastener_id: str`, `hole_id: str`, `clamped_component_ids: list[str]` | `fastener.bottoming`, `fastener.engagement`, `fastener.thread_match`, `fastener.head_clearance` findings; `unresolved` when `thread_depth` is null |
| `check_hole_alignment` | `hole_id_a: str`, `hole_id_b: str`, `tolerance: SourceRef \| null` | `hole.coaxiality` finding |
| `check_interference_group` | `group_key: str` | grouped `interference.static` finding, honoring exceptions |
| `record_drawing_finding` | `document_id`, `sheet`, `observed`, `requirement`, `source_refs: list[SourceRef]`, `status: "suspected" \| "unresolved"`, `recommended_action` | A non-numeric drawing finding. `status` may not be `demonstrated` or `checked_within_scope` from this tool. |

## Session tools

| Tool | Arguments | Effect |
|------|-----------|--------|
| `request_evidence` | `what: str`, `why: str`, `entity_ids: list[str]` | Adds an open `EvidenceRequest`; returns its id. |
| `mark_coverage` | `check: str`, `bucket: "checked" \| "skipped" \| "unresolved" \| "out_of_scope"`, `scope: object`, `reason: str` | Adds a `CoverageItem`. The `failed` bucket is written only by the tool layer itself. |
| `request_capture` | `entity_id: str`, `view: str` | Returns an existing `Capture` or, when the live SolidWorks bridge is enabled, requests one through the bridge and returns its file. Otherwise `unresolved`. |
| `get_review_checklist` | none | The mandatory checklist items and their current bucket. |

## Live SolidWorks bridge tools (optional, workstation only)

Enabled only when the reviewer is started with `--bridge` on the workstation. These call the
C# console host out of process, one coarse operation per call, on a single STA thread.

| Tool | Arguments | Returns |
|------|-----------|---------|
| `bridge_capture` | `persist_ref: str`, `view: str` | PNG path, appended to `captures` |
| `bridge_measure` | `persist_ref_a: str`, `persist_ref_b: str` | SolidWorks Measure result with units |
| `bridge_interference` | `component_ids: list[str]`, `configuration: str`, `settings: object` | `Interference` list with status |

## System prompt commitments (summary)

The system prompt instructs the model to: start with `get_package_summary` and
`get_review_checklist`; cover every checklist item with a check tool or `mark_coverage`;
never state a number that did not come from a tool result; never clear a joint or fit whose
inputs are unknown; use `request_evidence` rather than guessing; and end by calling
`mark_coverage` for anything left. The full prompt is versioned in `reviewer/src/swreview/agent/prompts/`.
