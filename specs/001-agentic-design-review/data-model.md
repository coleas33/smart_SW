# Data Model: SOLIDWORKS Agentic Design Review Pilot

**Feature**: `001-agentic-design-review` | **Date**: 2026-09-12 | **Spec**: [spec.md](spec.md)

Two families of data exist. The **Intermediate Representation (IR)** is what extraction
writes and every check reads. The **Review** family is what the reviewer produces and the
engineer dispositions. Both are typed, versioned, JSON-serialized documents.

Conventions used throughout:

- Every length is stored as a `Quantity` with an explicit unit; angles are a distinct
  `Angle` type and cannot be assigned to a length field (Principle II, FR-022).
- Every IR entity carries an `id` (stable within the package) and a `persist_ref`
  (opaque bytes, base64-encoded, from `GetPersistReference3`) so findings can point back
  (FR-015). Each ref also carries `persist_ref_scope`, the `document_id` whose extension
  produced it (the assembly for components and mates, the owning part for faces, holes,
  threads and bodies). Refs are never compared by bytes; the bridge resolves them with the
  scoped document and compares with `IsSamePersistentID`.
- Any field whose value could not be obtained is `null` **and** the reason is recorded in
  the package's `gaps` list. Absence is never defaulted (FR-008).

## 1. Shared value types

| Type | Fields | Rules |
|------|--------|-------|
| `Quantity` | `value: float`, `unit: "mm" \| "in" \| "m"` | Stored in source unit; converted on read via the unit module; conversion output keeps `source` and `converted`. |
| `Angle` | `value: float`, `unit: "deg" \| "rad"` | Separate type; no arithmetic with `Quantity`. |
| `Tolerance` | `kind: "symmetric" \| "bilateral" \| "limits" \| "basic" \| "none"`, `upper: Quantity \| Angle \| null`, `lower: Quantity \| Angle \| null`, `source: SourceRef` | `kind == "none"` means no tolerance found; checks treat it as unknown. Angle tolerances belong to angular dimensions only. |
| `Dimension` | `nominal: Quantity \| Angle`, `tolerance: Tolerance`, `source: SourceRef`, `text_as_read: str` | `text_as_read` is the raw drawing text. |
| `SourceRef` | `document_id`, `sheet: str \| null`, `view: str \| null`, `annotation: str \| null`, `persist_ref: bytes \| null`, `page: int \| null`, `bbox: [x0,y0,x1,y1] \| null` | Where a value came from. At least one locator must be set. |
| `Transform` | bare 4x4 float array (row-major, meters) | Always in SolidWorks internal units (meters). |
| `Vec3` | `x, y, z: float` | Meters. |

## 2. Intermediate Representation (IR)

### `EvidencePackage` (root)

| Field | Type | Rules |
|-------|------|-------|
| `schema_version` | `str` semver, e.g. `"1.0.0"` | Consumers reject a different **major** (FR-016). |
| `package_id` | `uuid` | |
| `created_at` | ISO 8601 | |
| `extractor` | `{name, version, sw_version, machine}` | Which tool produced it. |
| `manifest` | `Manifest` | Provenance for every document (FR-002). |
| `design` | `Design` | The reviewed design. |
| `documents` | `list[Document]` | Every part, assembly, drawing referenced. |
| `components` | `list[ComponentInstance]` | Flat list; tree via `parent_id`. |
| `mates` | `list[Mate]` | |
| `holes` | `list[Hole]` | |
| `threads` | `list[CosmeticThread]` | |
| `fasteners` | `list[Fastener]` | |
| `faces` | `list[FaceGeometry]` | Only faces a check needs. |
| `bodies` | `list[BodyRef]` | Points at mesh files. |
| `interferences` | `list[Interference]` | From SolidWorks detection, if run. |
| `captures` | `list[Capture]` | Screenshots keyed by persist_ref. |
| `drawings` | `list[DrawingSheet]` | Parsed from PDFs or native. |
| `gaps` | `list[Gap]` | Everything that could not be extracted. |

### `Manifest`

| Field | Type | Rules |
|-------|------|-------|
| `entries` | `list[ManifestEntry]` | One per document. |
| `discrepancies` | `list[Discrepancy]` | Filled by comparison of manifest to files reviewed (FR-003). |

`ManifestEntry`: `document_id`, `vault_path`, `vault_version: int | null`, `revision: str | null`, `configuration: str`, `local_modified: bool | null`, `export_method: "native" | "pdf" | "step" | "manual"`.

`Discrepancy`: `document_id`, `kind: "version_mismatch" | "local_modification" | "missing_document" | "config_mismatch"`, `expected`, `actual`, `note`.

### `Design`

`design_id`, `name`, `root_assembly_document_id`, `active_configuration`, `drawing_document_ids: list`. One design is the unit of review and of time measurement.

### `Document`

`document_id`, `kind: "part" | "assembly" | "drawing"`, `file_name`, `path`, `configurations: list[str]`, `active_configuration`, `custom_properties: dict[str, str]`, `config_properties: dict[str, dict[str, str]]`, `material: str | null` (parts), `mass: MassProperties | null`.

`MassProperties`: `mass_kg`, `volume_m3`, `center_of_mass: Vec3`, `configuration`.

### `ComponentInstance`

| Field | Type | Rules |
|-------|------|-------|
| `id` | str | e.g. `"cmp:0012"`. |
| `persist_ref` | bytes | Required (FR-015). |
| `persist_ref_scope` | str | `document_id` of the assembly whose extension produced the ref. |
| `full_path` | str | `IComponent2.Name2` full instance path, e.g. `sub-2/bracket-3`; unique in the assembly. |
| `name` | str | SolidWorks component name incl. instance suffix (`bracket-3`). |
| `document_id` | str | The part/assembly it instances. |
| `parent_id` | str \| null | Null for the root. |
| `referenced_configuration` | str | |
| `transform` | Transform | World transform. |
| `suppression` | `"resolved" \| "lightweight" \| "suppressed" \| "unloaded"` | Non-resolved => dependent checks unresolved. |
| `is_fixed` | bool | |
| `pattern_id` | str \| null | Set when the instance belongs to a component pattern; used for grouping (FR-011). |
| `is_toolbox` | bool | |

### `Mate`

`id`, `persist_ref`, `type` (SolidWorks mate type enum name), `entities: list[{component_id, persist_ref, entity_kind}]`, `alignment: "aligned" | "anti_aligned" | "closest"`, `suppressed: bool`, `distance: Quantity | null`, `angle: Angle | null`.

### `Hole`

| Field | Type | Rules |
|-------|------|-------|
| `id`, `persist_ref` | | |
| `component_id` | str | Owning instance. |
| `feature_name` | str | |
| `hole_type` | `"tapped" \| "clearance" \| "counterbore" \| "countersink" \| "simple" \| "unknown"` | |
| `standard` | str \| null | e.g. `"ISO"`, `"ANSI Metric"`. |
| `size` | str \| null | e.g. `"M6"`. |
| `thread_designation` | str \| null | e.g. `"M6x1.0"`. |
| `thread_depth` | Quantity \| null | Usable thread depth. **Null means unknown**; never derived from `hole_depth`. |
| `hole_depth` | Quantity \| null | Drill depth. |
| `end_condition` | `"blind" \| "through" \| "unknown"` | |
| `diameter` | Quantity \| null | Nominal hole diameter. |
| `axis` | `{origin: Vec3, direction: Vec3}` | World frame. |
| `face_ids` | list[str] | Cylindrical faces belonging to the hole. |

### `CosmeticThread`

`id`, `persist_ref`, `component_id`, `face_id`, `designation: str`, `depth: Quantity | null`, `is_external: bool`.

### `Fastener`

| Field | Type | Rules |
|-------|------|-------|
| `id`, `persist_ref`, `component_id` | | |
| `kind` | `"screw" \| "bolt" \| "nut" \| "washer" \| "pin" \| "other"` | |
| `identity_source` | `"toolbox" \| "custom_property" \| "name_parse" \| "manual"` | Confidence ordering; `name_parse` results are flagged as `suspected` in findings. |
| `thread_designation` | str \| null | e.g. `"M6x1.0"`. |
| `length` | Quantity \| null | Under-head length for screws. |
| `head_type` | str \| null | e.g. `"socket head cap"`. |
| `head_diameter` | Quantity \| null | |
| `head_height` | Quantity \| null | |
| `drive` | str \| null | |
| `axis` | `{origin: Vec3, direction: Vec3}` | Points from head toward tip. |
| `material` | str \| null | |

### `FaceGeometry`

`id`, `persist_ref`, `component_id`, `body_id`, `kind: "cylinder" | "plane" | "cone" | "torus" | "other"`, `cylinder: {axis_origin: Vec3, axis_dir: Vec3, radius_m: float} | null`, `plane: {origin: Vec3, normal: Vec3} | null`, `bbox: {min: Vec3, max: Vec3}`, `area_m2: float | null`.

### `BodyRef`

`id`, `persist_ref`, `component_id`, `mesh_file: str` (relative path, GLB or STL), `triangle_count: int`, `is_solid: bool`.

### `Interference`

`id`, `configuration`, `component_ids: [str, str]`, `volume: Volume | null` (units `mm3 | in3 | m3`; the extractor records the unit it verified, see research R12), `settings: {treat_coincident_as_interference, treat_subassemblies_as_components, include_multibody, ignore_hidden, fastener_folder_treatment}`, `is_fastener: bool` (SolidWorks placed it in the fasteners folder), `is_possible: bool` (`IsPossibleInterference`, coincident or touching), `status: "computed" | "truncated" | "failed"`, `error: str | null`, `group_key: str` (derived from pattern_id pairs for grouping).

### `Capture`

`id`, `persist_ref` (target), `component_ids`, `file: str` (PNG relative path), `view: str`, `note`.

### `DrawingSheet`

`document_id`, `sheet_name`, `page: int`, `scale: str | null`, `units: "mm" | "in" | "unknown"`, `general_notes: list[Note]`, `dimensions: list[Dimension]`, `views: list[{name, bbox}]`, `parse_status: "text" | "no_text" | "failed"`, `parser: str`.

`Note`: `text`, `source: SourceRef`, `kind: "general_tolerance" | "material" | "finish" | "other"`.

### `Gap`

`kind: "not_extracted" | "unsupported" | "tool_error" | "no_text"`, `entity_kind`, `entity_id: str | null`, `reason: str`, `error: str | null`. Every gap becomes an unresolved coverage item.

## 3. Review family

### `ReviewSession`

| Field | Type | Rules |
|-------|------|-------|
| `session_id` | uuid | |
| `package_id` | uuid | The EvidencePackage reviewed. |
| `design_id` | str | |
| `started_at`, `ended_at` | ISO 8601 | |
| `model` | str | LLM model id used. |
| `steps` | `list[InvestigationStep]` | Ordered trace (FR-004). |
| `evidence_requests` | `list[EvidenceRequest]` | Open until answered (FR-007). |
| `findings` | `list[Finding]` | |
| `coverage` | `Coverage` | |
| `timing` | `Timing` | |

`InvestigationStep`: `index`, `tool`, `arguments` (JSON), `result_summary`, `status: "ok" | "error"`, `error: str | null`, `elapsed_s`.

`EvidenceRequest`: `id`, `what` (free text), `why` (which check), `entity_ids`, `status: "open" | "answered"`, `answer: str | null`, `answered_at`.

### `Finding`

| Field | Type | Rules |
|-------|------|-------|
| `id` | str | `F-001` style within a session. |
| `check` | str | Check identifier, e.g. `fastener.bottoming`. |
| `title` | str | One line. |
| `status` | `"demonstrated" \| "suspected" \| "unresolved" \| "checked_within_scope"` | FR-009. |
| `severity` | `"high" \| "medium" \| "low" \| "info"` | |
| `component_ids` | list[str] | Affected instances. Required unless `drawing_locations` is set. |
| `drawing_locations` | list[SourceRef] | |
| `provenance` | list[ManifestEntry] | Version, revision, configuration of each document involved. |
| `configuration` | str | Configuration the finding is bound to. |
| `observed` | str | Observed condition. |
| `requirement` | str | Governing requirement with its source. |
| `inputs` | list[Dimension \| Quantity \| str] | Source dimensions with units and tolerances. |
| `calculation` | `Calculation \| null` | Required for numeric checks. |
| `tool_result_ids` | list[int] | `InvestigationStep.index` values that produced evidence. |
| `coverage_limits` | list[str] | What the check did not consider. |
| `recommended_action` | str | |
| `group` | `{key, member_component_ids} \| null` | For grouped repeated findings (FR-011). |
| `capture_ids` | list[str] | |
| `disposition` | `Disposition \| null` | Engineer-owned. |
| `exception_id` | str \| null | Set when matched to a retained exception. |

Validation: a finding with `status == "checked_within_scope"` or `"demonstrated"` MUST have a `calculation` or at least one `tool_result_id`; a finding with `status == "unresolved"` MUST list at least one `Gap` or open `EvidenceRequest` id in `coverage_limits`.

### `Calculation`

`model: str` (e.g. `"fit.size_only"`), `inputs: dict[str, Quantity | Angle | str]`, `assumptions: list[str]`, `excluded_effects: list[str]`, `result: dict[str, Quantity | bool | str]`, `units_out: str`, `function: str` (dotted Python path), `function_version: str`.

### `Coverage`

`checked: list[CoverageItem]`, `skipped: list[CoverageItem]`, `unresolved: list[CoverageItem]`, `failed: list[CoverageItem]`, `out_of_scope: list[CoverageItem]`. Each `CoverageItem`: `check`, `scope` (component ids, pairs, configuration, positions), `reason`, `error: str | null`. FR-010, FR-019, FR-020.

### `Disposition`

`decision: "accepted" | "rejected" | "deferred"`, `note`, `by`, `at`. Written by the engineer; never by the reviewer.

### `Exception`

| Field | Type | Rules |
|-------|------|-------|
| `id` | str | |
| `check` | str | |
| `component_persist_refs` | list[bytes] | Bound geometry. |
| `configuration` | str | |
| `geometry_fingerprint` | str | Hash of the involved faces' parameters and transforms at acceptance time. |
| `accepted_by`, `accepted_at`, `note` | | |
| `status` | `"active" \| "needs_review" \| "retired"` | `needs_review` when fingerprint or configuration no longer matches (FR-013). |

### `Timing`

`baseline_minutes: float | null` (human review, recorded separately), `assisted_supervision_minutes`, `assisted_verification_minutes`, `false_alarm_handling_minutes`, `unattended_runtime_minutes`, `net_saved_minutes: float | null` (computed as baseline minus the sum of assisted minutes, excluding unattended runtime; FR-026).

### `BenchmarkPackage` and `Scorecard`

`BenchmarkPackage`: `package_id`, `held_out: bool`, `answer_key_path` (a path the reviewer process cannot read; enforced by directory permissions and by the loader refusing paths under `benchmarks/answer_keys/`).

`AnswerKey`: `known_defects: list[{id, check, component_ids, description}]`, `correct_conditions: list[{check, component_ids}]`.

`Scorecard`: `run_id`, `per_package: list[{package_id, valid_findings, missed_known_defects, false_alarms, unresolved_count, net_saved_minutes}]`, `aggregate: {…same counts…, median_net_saved_minutes, recall, false_alarm_rate}`, `distribution: list[net_saved_minutes]`.

## 4. Relationships

```text
Design 1..* Document
Document 1..* ComponentInstance (instances of it)
ComponentInstance 0..1 parent ComponentInstance
ComponentInstance 1..* FaceGeometry, 0..* Hole, 0..* Fastener, 0..* BodyRef
Mate 2..* entity refs -> ComponentInstance/FaceGeometry
Interference -> 2 ComponentInstance
DrawingSheet -> Document ; Dimension -> SourceRef -> Document
ReviewSession 1 EvidencePackage
ReviewSession 0..* Finding ; Finding 0..* ComponentInstance ; Finding 0..1 Calculation
Finding 0..1 Disposition ; Finding 0..1 Exception
Exception -> component persist_refs + configuration + geometry_fingerprint
BenchmarkPackage 1 EvidencePackage + 1 AnswerKey ; Scorecard 1..* BenchmarkPackage
```

## 5. State transitions

**Finding.status** is set once by the check that produced it and does not change; a
re-run produces a new session. **Disposition** transitions: none → accepted | rejected |
deferred; deferred → accepted | rejected.

**Exception.status**: `active` → `needs_review` when a later package's fingerprint or
configuration differs; `needs_review` → `active` (engineer re-accepts) or `retired`.

**EvidenceRequest.status**: `open` → `answered`. Findings depending on an open request stay
`unresolved`.

**Interference.status** and **DrawingSheet.parse_status** are terminal per package; any
value other than `computed` / `text` produces a `Gap`.
