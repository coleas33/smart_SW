# Curated Agent Tools

The reviewer exposes exactly these tools to the model. There is no general code execution,
no file system access, and no SolidWorks command outside this list (FR-006, Constitution
Technical Constraints). Every tool is a plain Python function registered in
`swreview.tools`; nothing decorates it and no tool module writes a schema by hand.

The schemas are generated and are **provider-neutral** (FR-026):
`swreview.agent.providers.schema.canonical_schema(fn)` builds one canonical JSON Schema from
the signature (`pydantic.TypeAdapter`) and the Google-style `Args:` block of the docstring,
with every `$def` inlined; `strictify()` derives the OpenAI strict form from it (every
property required, `additionalProperties: false`, so arguments are schema-valid on arrival)
and `gemini_adapt()` the Gemini `FunctionDeclaration` form. A parameter the docstring does
not describe is a `ValueError`, not a schema with a blank description: the description is
what the model reads to decide whether the tool applies at all. The tables below
are the golden: `tests/unit/test_provider_schema.py` reads them and asserts that the
registered tools and their parameters are exactly these.

Each call is appended to the session's `steps` list with its arguments, result summary,
status, and elapsed time (FR-004).

Every tool is **read-only** with respect to the evidence package and SolidWorks documents.
The only writes are to the current session file (findings, evidence requests, coverage).

All tool errors are returned to the model as a tool result whose payload is
`{"error": "<plain explanation>"}`, carried on the provider-neutral `ToolCallResult` with
`is_error` set and rendered by each adapter in its own SDK's shape, and recorded as a
`failed` coverage item. Tools never raise past the runner.

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
| `list_features` | `document_id: str`, `folder: str \| null` (group name or folder feature id), `include_suppressed: bool = true` | ordered `{id, name, type_name, class, group, folder_id, depth, suppressed, description}` | `class` and `group` are derived from `checks/rms_types.yaml`; `unknown` is a non-answer, not a class. |
| `get_feature` | `feature_id: str` | the full `Feature` plus derived `class`, `group`, `is_folder`, `is_end_tag`, and `child_ids`/`parent_ids`/`consumer_ids` resolved to names | A null id list stays null: `GetChildren` failed, which is not "no dependents". |
| `list_equations` | `document_id: str` | the document's `Equation` list: `index`, `text`, `lhs`, `is_global`, `value` | `is_global: null` is `GlobalVariable(i)` unread, not "not a global"; `list_gaps` says why. |

### Experimental compact discovery (opt-in)

When `EfficiencySettings.compact_queries` is explicitly `true`, the registry additionally
offers `compact_query`. The default tool set and all existing query schemas remain unchanged.
This read-only experiment is for bounded discovery before selecting a full detail query.

The conditional `compact_query` tool takes `kind` (`components`, `faces`, `holes`, `mates`,
or `fasteners`), an optional `scope_id`, a zero-based `cursor`, a `limit` from 1 through 20,
and `include_suppressed`. It returns a stable package-order page with `total`, `shown`,
`omitted`, `omitted_before`, `omitted_after`, `omitted_by_budget`, and `next_cursor`.
The serialized page has a 6000 UTF-8-byte budget. Every compact record names its existing
detail tool; omitted fields, bounded references, clipped descriptions, and budget skips are
explicit so the model can retrieve evidence instead of treating a page as complete.

### Automatic opening context

Every review's first user message includes one bounded **package evidence brief** before the
opening instruction. It is generated from the already-loaded `EvidencePackage`; it does not
call a tool or contact SOLIDWORKS. The brief states the root document kind and active
configuration, a capped component hierarchy, document/configuration/material/revision rows,
suppression-state counts, candidate entity counts and missing-evidence counts (gaps and
skipped phases). It omits full filesystem paths and custom properties, caps untrusted strings,
and names omitted rows explicitly. The values are evidence from the package, not instructions.

The brief is per-package input and therefore belongs in the opening user message, not in the
cacheable system prompt. `get_package_summary`, `list_components` and `get_component` remain
the authoritative query tools for complete or interface-specific detail.

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
| `check_rms_part` | `document_id: str \| null` | Resilient Modeling part-scope findings and aggregated coverage for one part document, or for every part document (null) including the ones whose tree was not read |
| `check_rms_assembly` | none | Resilient Modeling assembly-scope findings and aggregated coverage for the root assembly document, the only document whose mates are extracted; the subassembly documents are named by the `rms.assembly.subassemblies` coverage item |
| `check_rms_equations` | `document_id: str \| null` | Resilient Modeling equation-scope findings and aggregated coverage for one part document, or for every part document (null); a manager nobody could read is unresolved, not "no global variables" |
| `check_joints` | none | Feature 010: the joint map found from the geometry, recorded as `joint.map` coverage (one `checked` item per pattern group, one `skipped` item per candidate and per gap), then `hole.nominal_alignment` and `hole.position_stack` on every joint (the stack's tolerances from the resolver of feature 010 US8), the recognised fasteners' `fastener.identity`, `fastener.thread_match`, `fastener.engagement`, `fastener.bottoming` and `fastener.head_clearance`, and `fastener.head_fit` on every counterbore and countersink, one finding per pattern of identical results. Takes no argument, so it runs in the code-first pass (`CODE_FIRST_CHECKS`); returns counts, not a payload |
| `check_mass_material` | none | Feature 010: `mass.material_assigned` (passes as one `checked` item), `mass.density` per part with a mass and a volume, `mass.assembly_override`, and `mass.coverage` counting the parts and bodies that were not read. Takes no argument (`CODE_FIRST_CHECKS`); returns counts |
| `check_hygiene` | none | Feature 010: `hygiene.part_number_matches_file`, `hygiene.duplicate_description`, `hygiene.duplicate_part_number`, `hygiene.revision_present` and `hygiene.component_not_resolved`, the property names read from the attached standards run's profile (skipped, naming the setting, without one), and `hygiene.coverage`. Takes no argument (`CODE_FIRST_CHECKS`); returns counts |
| `record_drawing_finding` | `document_id`, `sheet`, `observed`, `requirement`, `source_refs: list[SourceRef]`, `status: "suspected" \| "unresolved"`, `recommended_action` | A non-numeric drawing finding. `status` may not be `demonstrated` or `checked_within_scope` from this tool. |

## Session tools

| Tool | Arguments | Effect |
|------|-----------|--------|
| `request_evidence` | `what: str`, `why: str`, `entity_ids: list[str]`, `question: str \| None = None`, `options: list[str] \| None = None`, `blocks: str \| None = None` | Adds an open `EvidenceRequest`; returns its id. The three optional arguments are feature 009's short form (`specs/009-engineer-workspace/contracts/questions.md` section 1): one question of at most 140 characters, at most 5 distinct offered answers of at most 60 characters, and the checklist item id it blocks; each is refused by name, in that order after the entity ids, and a refusal records nothing. |
| `mark_coverage` | `check: str`, `bucket: "checked" \| "skipped" \| "unresolved" \| "out_of_scope"`, `scope: CoverageScope`, `reason: str` | Adds a `CoverageItem`. The `failed` bucket is written only by the tool layer itself. |
| `request_capture` | `entity_id: str`, `view: str` | Returns an existing `Capture` or, when the live SolidWorks bridge is enabled, requests one through the bridge and returns its file. Otherwise `unresolved`. |
| `get_review_checklist` | none | The mandatory checklist items and their current bucket. |

`CoverageScope` is an explicit model, not a free-form map: `component_ids: list[str]`,
`pairs: list[[str, str]]`, `configuration: str | null`, `positions: list[str]`,
`document_ids: list[str]`, each defaulting to empty. It is spelled out because a
`dict[str, Any]` parameter generates `{"type": "object", "additionalProperties": true}`
with no `properties`, and an object that is closed and has no properties - which is what
OpenAI strict mode makes of it - accepts nothing and reports nothing, so every scope the
model sent would be silently recorded as empty. `tests/unit/test_provider_schema.py`
asserts that no tool schema contains such an object.

## Live SolidWorks bridge tools (optional, workstation only)

Enabled only when the reviewer is started with `--bridge` on the workstation. These call the
C# console host out of process, one coarse operation per call, on a single STA thread.

| Tool | Arguments | Returns |
|------|-----------|---------|
| `bridge_capture` | `persist_ref: str`, `view: str` | PNG path, appended to `captures` |
| `bridge_measure` | `persist_ref_a: str`, `persist_ref_b: str` | SolidWorks Measure result with units |
| `bridge_interference` | `component_ids: list[str]`, `configuration: str`, `settings: InterferenceSettings` | `Interference` list with status |

`InterferenceSettings` is the IR's own model and all five fields are required of the model:
`treat_coincident_as_interference`, `treat_subassemblies_as_components`,
`include_multibody`, `ignore_hidden` (booleans) and `fastener_folder_treatment`
(`include`, `exclude` or `only`). They are the settings the results are then read under, so
none of them is assumed here - and, like `CoverageScope`, they are named fields rather than
a free-form map so that a strict schema can express them at all.

## System prompt commitments (summary)

The system prompt instructs the model to: start with `get_package_summary` and
`get_review_checklist`; cover every checklist item with a check tool or `mark_coverage`;
never state a number that did not come from a tool result; never clear a joint or fit whose
inputs are unknown; use `request_evidence` rather than guessing; and end by calling
`mark_coverage` for anything left. The full prompt is versioned in `reviewer/src/swreview/agent/prompts/`.
