---

description: "Task list for the SOLIDWORKS Agentic Design Review Pilot"
---

# Tasks: SOLIDWORKS Agentic Design Review Pilot

**Input**: Design documents from `/specs/001-agentic-design-review/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. The constitution (Principle III) makes tests non-negotiable: every check,
parser, loader and tool has unit tests written first, and every check has a golden fixture.
Test tasks precede implementation tasks in every phase and must fail before the
implementation exists.

**Organization**: Tasks are grouped by user story so each story is an independently testable
increment. US1 is the MVP and needs no SOLIDWORKS seat.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 through US6)
- Paths are relative to the repository root

## Path Conventions

- Python reviewer: `reviewer/src/swreview/`, tests in `reviewer/tests/`
- C# extractor: `extractor/SwReview.Extractor/`, `extractor/SwReview.AddIn/`,
  `extractor/SwReview.Extractor.Console/`, tests in `extractor/SwReview.Extractor.Tests/`
- Benchmarks: `benchmarks/packages/`, `benchmarks/native/`, `benchmarks/answer_keys/`, `benchmarks/sets/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeletons for both languages, tooling, and the benchmark layout.

- [X] T001 Create the monorepo directories `extractor/`, `reviewer/`, `benchmarks/{packages,native,answer_keys,sets}/` per plan.md Project Structure, each with a one-line `README.md`
- [X] T002 Initialize the Python project: `reviewer/pyproject.toml` (uv, src layout, package `swreview`, Python `>=3.11`, console script `swreview = swreview.cli:app`, dependencies `anthropic`, `pydantic>=2`, `pint`, `trimesh`, `pymupdf`, `pdfplumber`, `typer`, `numpy`; optional extra `raycast = ["embreex"]`; dev group `pytest`, `pytest-regressions`, `ruff`, `jsonschema`) and empty `reviewer/src/swreview/__init__.py`
- [X] T003 [P] Configure tooling in `reviewer/pyproject.toml`: ruff (line length 100), pytest (`testpaths = ["tests"]`, markers `integration`, `raycast`), and `reviewer/tests/conftest.py` skipping `integration` tests when `benchmarks/packages/bracket-assy/native/package.json` is absent
- [X] T004 [P] Create `extractor/SwReview.sln` with projects `SwReview.Extractor` (class library, net48), `SwReview.AddIn` (class library, net48, COM-visible), `SwReview.Extractor.Console` (console, net48, `[STAThread] Main`), `SwReview.Extractor.Tests` (xUnit, net48); reference `SolidWorks.Interop.sldworks`, `swconst`, `swpublished` 2024 with `EmbedInteropTypes=false`; add `System.Text.Json` package
- [X] T005 [P] Add `benchmarks/README.md` describing package layout (`package.json`, `manifest.json`, `bom.csv`, `drawings/*.pdf`, `geometry/*.step`, `exceptions.json`) and the rule that `benchmarks/answer_keys/` is never passed to the reviewer
- [X] T006 [P] Update root `.gitignore`: ignore `reviewer/runs/`, `extractor/**/bin/`, `extractor/**/obj/`, `*.user`; keep `benchmarks/` tracked except `benchmarks/native/**/*.SLD*` (binary CAD files, tracked separately)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The IR models, units, finding builder, session model, golden harness and C# DTOs that every story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 Write unit tests for the units module in `reviewer/tests/unit/test_units.py`: `Length("mm")`/`Length("in")` conversion returns `{source, converted}` with both values; `Angle` cannot be converted to a length and raises `DimensionalityError`; unknown unit string raises `ValueError`; conversions round-trip to 1e-9
- [X] T008 Implement `reviewer/src/swreview/units.py`: one shared `pint.UnitRegistry`, `to_length(q: Quantity)`, `to_angle(a: Angle)`, `convert(q, unit) -> Converted{source, converted}`, `as_mm(q) -> float`; nothing else exported
- [X] T009 Write unit tests for IR models in `reviewer/tests/unit/test_ir_models.py`: `ConfigDict(strict=True, extra="forbid")` rejects an unknown field; `schema_version` `"2.0.0"` raises `UnsupportedSchemaVersionError`, `"1.3.0"` loads; `Hole.thread_depth` may be `None`; `Fastener.identity_source` enum enforced; `ComponentInstance.id` pattern `cmp:NNNN`; `Interference.volume.unit` restricted to `mm3|in3|m3`; `SourceRef` with no locator fails
- [X] T010 Implement `reviewer/src/swreview/ir/models.py` with every type in data-model.md sections 1 and 2 (`Quantity`, `Angle`, `Volume`, `Vec3`, `Axis`, `Transform`, `SourceRef`, `Tolerance`, `Dimension`, `ManifestEntry`, `Discrepancy`, `Manifest`, `Design`, `Document`, `MassProperties`, `ComponentInstance`, `Mate`, `Hole`, `CosmeticThread`, `Fastener`, `FaceGeometry`, `BodyRef`, `Interference`, `Capture`, `Note`, `DrawingSheet`, `Gap`, `EvidencePackage`) and `UnsupportedSchemaVersionError`
- [X] T011 Write unit tests for the package loader in `reviewer/tests/unit/test_ir_loader.py`: loads `package.json` from a directory; resolves `mesh_file`/`captures` relative paths; refuses any directory whose resolved path contains a `benchmarks/answer_keys` segment with `AnswerKeyAccessError`; reports major-version mismatch distinctly from malformed JSON
- [X] T012 Implement `reviewer/src/swreview/ir/loader.py`: `load_package(dir) -> LoadedPackage` (package + base dir), `save_package(pkg, dir)`, `AnswerKeyAccessError`
- [X] T013 Write `reviewer/tests/unit/test_schema_sync.py` asserting that `swreview.ir.schema.export_schema()` equals `specs/001-agentic-design-review/contracts/ir.schema.json` (normalized JSON) and that a sample package validates with `jsonschema`
- [X] T014 Implement `reviewer/src/swreview/ir/schema.py`: `export_schema()` from `EvidencePackage.model_json_schema()` with `$id` and title set; `python -m swreview.ir.schema --write` regenerates the contract file
- [X] T015 Write unit tests for the finding builder in `reviewer/tests/unit/test_findings.py`: `demonstrated` without calculation or tool result raises; `unresolved` without coverage limits raises; a finding must name a component or a drawing location; provenance is attached from the manifest for every referenced document; `record_drawing_finding`-style status restriction (`suspected|unresolved` only) is enforced by a `numeric=False` flag
- [X] T016 Implement `reviewer/src/swreview/findings.py`: `Finding`, `Calculation`, `Disposition` models (data-model.md section 3), `build_finding(...)`, `FindingIdAllocator`
- [X] T017 Write unit tests for the session model in `reviewer/tests/unit/test_session.py`: `ReviewSession` round-trips to JSON matching `contracts/review-session.schema.json` (validate with `jsonschema`); `Coverage` has all five buckets; `Timing.net_saved_minutes` is `None` when baseline is `None`; `EvidenceRequest` id pattern
- [X] T018 Implement `reviewer/src/swreview/report/session.py`: `ReviewSession`, `InvestigationStep`, `EvidenceRequest`, `Coverage`, `CoverageItem`, `Timing`, `load_session`, `save_session`
- [X] T019 Create `reviewer/tests/conftest.py` fixtures: `make_package(**overrides)` building a minimal valid `EvidencePackage`, `tmp_package_dir`, `fake_manifest`; and `reviewer/tests/golden/test_golden.py` parametrized over `reviewer/tests/golden/fixtures/*/` comparing check output with `data_regression`
- [X] T020 [P] Create C# IR DTOs in `extractor/SwReview.Extractor/Ir/*.cs` mirroring `contracts/ir.schema.json` (snake_case JSON names, nullable value types, `PersistRef` as base64 string) and `PackageSerializer.cs`
- [X] T021 [P] Write `extractor/SwReview.Extractor.Tests/IrSerializerTests.cs`: serialize a sample package, validate against `contracts/ir.schema.json` (JsonSchema.Net or NJsonSchema), round-trip equality, `thread_depth` null preserved
- [X] T022 [P] Write `extractor/SwReview.Extractor.Tests/GuardTests.cs` then implement `extractor/SwReview.Extractor/Guard/ReadOnlyGuard.cs` (allowlist of permitted interop members; `Assert(memberName)` throws `MutatingCallError` for `EditRebuild3`, `Save3`, `Delete2`, `Feature*` creation) and `CircuitBreaker.cs` (trips after 3 consecutive COM failures)

**Checkpoint**: Foundation ready. `uv run pytest` passes with schema sync green; `dotnet test` passes.

---

## Phase 3: User Story 1 - Evidence-Linked Review of a Design Package (Priority: P1) 🎯 MVP

**Goal**: Review an exported package (PDFs, BOM, manifest) with the agent loop and produce `session.json` plus `report.md` with evidence-linked findings, open evidence requests, coverage, and dispositions.

**Independent Test**: quickstart Scenario 1 on `benchmarks/packages/cover-blind-tap`.

### Tests for User Story 1

- [X] T023 [P] [US1] Unit tests for manifest ingest in `reviewer/tests/unit/test_ingest_manifest.py`: parse `manifest.json`; detect `version_mismatch`, `local_modification`, `missing_document`, `config_mismatch` against a package's documents; discrepancies sorted to the top
- [X] T024 [P] [US1] Unit tests for BOM ingest in `reviewer/tests/unit/test_ingest_bom.py`: CSV with item, part number, description, quantity, configuration; quantity mismatch with component count becomes a `Gap`
- [X] T025 [P] [US1] Unit tests for the dimension grammar in `reviewer/tests/unit/test_dimension_grammar.py`: `Ø10.00 ±0.02`, `10.02/10.00`, `10 +0.05/-0.00`, `M6x1.0 - 6H ↧ 12`, `45° ±0°30'` (Angle, not Length), `.3937 ±.0005` with sheet units `in`, `2X Ø6.6 THRU`; unknown text yields `tolerance.kind == "none"` and preserves `text_as_read`
- [X] T026 [P] [US1] Unit tests for the PDF drawing parser in `reviewer/tests/unit/test_pdf_parser.py` using tiny PDFs generated with PyMuPDF in the test: spans clustered into dimensions with bbox and page; general notes detected; a page with no text layer yields `parse_status == "no_text"` and a `Gap`; sheet units read from the title block or defaulted to `unknown`
- [X] T027 [P] [US1] Unit tests for package query tools in `reviewer/tests/unit/test_tools_query.py`: every tool in contracts/agent-tools.md "Package query tools" against `make_package`; `list_holes` returns `"unknown"` text alongside `None` thread depth; unknown ids return an error result, never raise
- [X] T028 [P] [US1] Unit tests for session tools in `reviewer/tests/unit/test_tools_session.py`: `request_evidence` creates an open request; `mark_coverage` rejects bucket `failed`; `record_drawing_finding` rejects `demonstrated`/`checked_within_scope`; `get_review_checklist` reflects buckets
- [X] T029 [P] [US1] Unit tests for the report renderer and dispositions in `reviewer/tests/unit/test_report.py`: every finding field appears in Markdown; discrepancies render first; coverage renders all five buckets; `disposition` writes to `session.json` and re-render shows it; navigation link contains `persist_ref` and document id
- [X] T030 [US1] Unit tests for the agent runner in `reviewer/tests/unit/test_agent_runner.py` with a fake Anthropic client: each tool call becomes an `InvestigationStep`; a tool raising becomes `is_error` plus a `failed` coverage item; `--max-steps` stops the loop with coverage noted; `--fail-tool` hook; final session validates against the schema
- [X] T031 [US1] Create golden fixture `reviewer/tests/golden/fixtures/cover-blind-tap/package.json` (cover, housing with blind tapped hole, `thread_depth: null`, `hole_depth` set, screws, one drawing sheet with `no_text`) and expected output for the query tools and `record_drawing_finding`

### Implementation for User Story 1

- [X] T032 [P] [US1] Implement `reviewer/src/swreview/ingest/manifest.py` (`read_manifest`, `find_discrepancies`)
- [X] T033 [P] [US1] Implement `reviewer/src/swreview/ingest/bom.py`
- [X] T034 [US1] Implement `reviewer/src/swreview/ingest/dimension_grammar.py` (regex grammar returning `Dimension` with `Quantity` or `Angle`, tolerance kinds `symmetric|bilateral|limits|basic|none`, thread callouts)
- [X] T035 [US1] Implement `reviewer/src/swreview/ingest/pdf_drawing.py` (PyMuPDF spans, proximity clustering, `pdfplumber` for tables, `DrawingSheet` output, `Gap` on `no_text`/failure)
- [X] T036 [US1] Implement `reviewer/src/swreview/ingest/package_builder.py`: build or augment `package.json` from manifest, BOM, PDFs; native entities win over exported ones for the same `document_id`; `extractor.sw_version` null for exported-only packages
- [X] T037 [US1] Implement `reviewer/src/swreview/tools/query.py` (all package query tools as `@beta_tool` functions over a `ToolContext`)
- [X] T038 [US1] Implement `reviewer/src/swreview/tools/session.py` (`request_evidence`, `mark_coverage`, `record_drawing_finding`, `get_review_checklist`, `request_capture` returning existing captures or `unresolved`)
- [X] T039 [US1] Implement `reviewer/src/swreview/tools/registry.py`: builds the tool list with `strict: true`, validates ids and paths before dispatch, records `InvestigationStep` with elapsed time, converts exceptions to `is_error` results and `failed` coverage
- [X] T040 [US1] Write `reviewer/src/swreview/agent/prompts/system_v1.md` (commitments in contracts/agent-tools.md "System prompt commitments") and `reviewer/src/swreview/agent/checklist_v1.yaml` (mandatory review checklist: provenance, drawing completeness of manufacturing inputs, interfaces, fasteners, interference, tolerances, coverage close-out)
- [X] T041 [US1] Implement `reviewer/src/swreview/agent/runner.py`: `client.beta.messages.tool_runner(model="claude-opus-5", max_tokens=64000, output_config={"effort": effort}, tools=..., messages=...)` with streaming, message mirroring, `pause_turn` restart cap, `max_steps`, and session finalization (open requests and unchecked checklist items become `unresolved` coverage)
- [X] T042 [US1] Implement `reviewer/src/swreview/report/markdown.py` (discrepancies, findings grouped by severity, evidence requests, coverage, navigation links) and `reviewer/src/swreview/report/dispositions.py`
- [X] T043 [US1] Implement `reviewer/src/swreview/cli.py` commands `validate`, `ingest`, `review`, `report`, `disposition` per contracts/cli.md with exit codes 0/1/2 and `--json`
- [ ] T044 [US1] Assemble `benchmarks/packages/cover-blind-tap/` (manifest, BOM, drawing PDFs with one flattened page, seeded drill-depth-only hole) and run quickstart Scenario 1; record the day-one result and time in `benchmarks/packages/cover-blind-tap/notes.md`

**Checkpoint**: US1 delivers an evidence-linked review on exported files with no SOLIDWORKS process.

---

## Phase 4: User Story 2 - Native Evidence Extraction from the Workstation (Priority: P2)

**Goal**: The C# extractor dumps a complete IR with persistent references from an open SOLIDWORKS 2024 assembly, via Task Pane button or console host.

**Independent Test**: quickstart Scenario 2 against `benchmarks/native/bracket-assy` and its answer key.

### Tests for User Story 2

- [X] T045 [P] [US2] `extractor/SwReview.Extractor.Tests/PersistRefTests.cs`: byte[] to base64 and back; empty ref rejected
- [X] T046 [P] [US2] `extractor/SwReview.Extractor.Tests/TransformTests.cs`: SOLIDWORKS 16-element `MathTransform.ArrayData` to row-major 4x4 in meters, including scale element handling
- [X] T047 [P] [US2] `extractor/SwReview.Extractor.Tests/FastenerNameParserTests.cs`: Toolbox-style names (`socket head cap screw_am`, `M6 x 20`) to designation and length with `identity_source == "name_parse"`; unparseable names yield nulls, not guesses
- [X] T048 [P] [US2] `extractor/SwReview.Extractor.Tests/GapCollectorTests.cs`: every failed extraction step becomes a `Gap` with kind and error, and the dump still completes

### Implementation for User Story 2

- [X] T049 [US2] Implement `extractor/SwReview.Extractor/PersistRefs/PersistRefService.cs` (`Get(doc, object) -> (base64, scopeDocumentId)` via that document's `IModelDocExtension.GetPersistReference3`; `Resolve(scopeDoc, base64) -> object` via `GetObjectByPersistReference3` with `swPersistReferencedObjectStates_e` surfaced; `IsSame(a, b)` via `IsSamePersistentID`, never byte comparison)
- [X] T050 [US2] Implement `extractor/SwReview.Extractor/Dump/ComponentTreeDumper.cs` (`ConfigurationManager.ActiveConfiguration` → `IConfiguration.GetRootComponent` → recursive `IComponent2.GetChildren`; `full_path` from `Name2`; `Transform2.ArrayData` to 4x4 meters; `ReferencedConfiguration`; `GetSuppression2` mapped 0→`suppressed`, 1 and 4→`lightweight`, 2 and 3→`resolved`, 5→`unloaded` plus a `Gap`; `IsFixed`; pattern membership; `is_toolbox` from `IModelDocExtension.ToolboxPartType != 0`; never rely on `GetID` for identity)
- [X] T051 [US2] Implement `extractor/SwReview.Extractor/Dump/MateDumper.cs` (`IMate2` type, `MateEntity2` component and persist ref, alignment, suppression, distance and angle values with units)
- [X] T052 [US2] Implement `extractor/SwReview.Extractor/Dump/HoleDumper.cs` (filter features by `GetTypeName2`, `GetDefinition` → `IWizardHoleFeatureData2`; read scalars `Type`, `Standard2` falling back to `Standard` when −1, `FastenerSize`, `ThreadDiameter`, `ThreadDepth`, `HoleDepth`, `Diameter`, `EndCondition`, `ThreadEndCondition`, `TapType` without `AccessSelections`; `thread_depth` null when the feature has no thread; any `AccessSelections` use paired with `ReleaseSelectionAccess` in `finally`; `ICosmeticThreadFeatureData` (`Standard`, `Size`, `Diameter`, `BlindDepth`, `EndCondition`, `ThreadCallout`, `Edge`) for cosmetic threads; hole axis from the cylindrical face's `CylinderParams`, not `GetBox`)
- [X] T053 [US2] Implement `extractor/SwReview.Extractor/Dump/FastenerDumper.cs` (for `ToolboxPartType != 0`: parse size, length and head from the referenced configuration name and configuration-specific custom properties `Description`, `Length`, `Size`, `Part Number` per standard → `identity_source: "custom_property"`; otherwise `FastenerNameParser` → `"name_parse"`; axis from the shank cylinder `CylinderParams`; head dimensions from geometry when not in properties)
- [X] T054 [US2] Implement `extractor/SwReview.Extractor/Dump/PropertyDumper.cs` (`ICustomPropertyManager.GetAll3` for document and each configuration, `IPartDoc.GetMaterialPropertyName2(config, out db)`, `IModelDocExtension.CreateMassProperty2` with `UseSystemUnits = true` after preselecting bodies, `Recalculate`, and `GetOverrideOptions` recorded so overridden masses are visible; null mass plus `Gap` for surface-only models)
- [X] T055 [US2] Implement `extractor/SwReview.Extractor/Dump/FaceDumper.cs` (`IFace2.GetSurface` → `ISurface.IsCylinder`/`IsPlane`; `CylinderParams` 7 doubles origin, axis, radius; `PlaneParams` 6 doubles normal then root point; both transformed to assembly space with `Transform2`; `GetBox` only for the approximate `bbox`; area; persist ref scoped to the owning part document; only faces referenced by holes, fasteners, mates, or `--faces all`)
- [X] T056 [US2] Implement `extractor/SwReview.Extractor/Dump/MeshExporter.cs` (per-body `IBody2.GetTessellation` → `ITessellation` with `CurveChordTolerance`, `SurfacePlaneTolerance`, `NeedFaceFacetMap`, `NeedVertexNormal`; GLB with node transform in meters, `persist_ref` and face-facet map in extras; `--meshes stl` fallback)
- [X] T057 [US2] Implement `extractor/SwReview.Extractor/Dump/ManifestBuilder.cs` (vault path, local version and revision from EPDM custom properties or the PDM API when available, active configuration; nulls plus `Gap` otherwise)
- [X] T058 [US2] Implement `extractor/SwReview.Extractor/Dump/PackageWriter.cs` orchestrating the dumpers, `GapCollector`, id allocation (`cmp:NNNN`), and `package.json` plus `meshes/` output
- [X] T059 [US2] Implement `extractor/SwReview.Extractor.Console/Program.cs` commands `dump` and `resolve` per contracts/cli.md (attach to running SOLIDWORKS via `GetObject`, else create; `extract.log`)
- [X] T060 [US2] Implement `extractor/SwReview.AddIn/` (COM registration, Task Pane with **Dump IR** button calling `PackageWriter` on the active document, progress and error dialog)
- [ ] T061 [US2] On the workstation, prepare `benchmarks/native/bracket-assy/` (assembly with tapped holes, Toolbox screws, a suppressed component, a pattern) and `benchmarks/native/bracket-assy/answer-key.json`; run quickstart Scenario 2 including the reopen and `resolve` round trip; record results in `benchmarks/native/bracket-assy/notes.md`

**Checkpoint**: Native packages load in the reviewer (`swreview validate`) and US1 reviews run against them.

---

## Phase 5: User Story 3 - Interference and Clearance Review (Priority: P3)

**Goal**: Interference results with grouping, retained exceptions bound to geometry, truncation reported as unresolved, and the optional live bridge for captures and measurements.

**Independent Test**: quickstart Scenario 3.

### Tests for User Story 3

- [X] T062 [P] [US3] Unit tests in `reviewer/tests/unit/test_checks_interference.py`: same pattern pair collapses into one grouped finding with member list; `truncated`/`failed` entries become `unresolved` coverage and no `checked_within_scope` is emitted for the run; volume unit preserved; mechanism positions produce the coverage statement text
- [X] T063 [P] [US3] Unit tests in `reviewer/tests/unit/test_exceptions.py`: `geometry_fingerprint` stable across reorderings; changing a face radius or configuration flips `active` to `needs_review`; accepting a finding creates an exception bound to its persist refs; `exceptions.json` round-trips
- [X] T064 [P] [US3] Unit tests in `reviewer/tests/unit/test_bridge_client.py` with a fake named-pipe server: request/response framing, timeout, error status mapped to `failed` coverage, circuit breaker after three failures
- [X] T065 [P] [US3] `extractor/SwReview.Extractor.Tests/InterferenceSettingsTests.cs`: settings map to `IInterferenceDetectionManager` properties and are echoed into the IR; `--truncate-after` marks remaining pairs `truncated`

### Implementation for User Story 3

- [X] T066 [US3] Implement `reviewer/src/swreview/checks/interference.py` (`group_interferences`, `check_interference_group` honoring exceptions, coverage items for truncated/failed and for mechanism positions)
- [X] T067 [US3] Implement `reviewer/src/swreview/exceptions.py` (`Exception` model, `fingerprint(package, component_ids)`, `ExceptionStore` load/save/match/`needs_review`)
- [X] T068 [US3] Add tools `list_interferences`, `check_interference_group`, `get_exceptions` to `reviewer/src/swreview/tools/checks.py` and register them
- [X] T069 [US3] Implement `extractor/SwReview.Extractor/Interference/InterferenceRunner.cs` (`IAssemblyDoc.InterferenceDetectionManager` → `IInterferenceDetectionMgr` with `TreatCoincidenceAsInterference`, `TreatSubAssembliesAsComponents`, `IncludeMultibodyPartInterferences`, `IgnoreHiddenBodies`, `CreateFastenersFolder = true`; `GetInterferenceCount`/`GetInterferences`; per result `Volume`, `Components` to persist refs, `IsFastener`, `IsPossibleInterference`; `Done()` in `finally`; per-pair status; `group_key` from pattern ids). Include a one-time workstation check of `Volume` units against a known box overlap (units are undocumented) and record the verified unit in the IR
- [X] T070 [US3] Implement `extractor/SwReview.Extractor/Capture/CaptureService.cs` (resolve persist ref → `SelectByID2` → `IModelDoc2.ViewZoomToSelection` → optional standard view → `IModelDoc2.SaveBMP` or `IModelDocExtension.SaveAs3` PNG; `Capture` record)
- [X] T071 [US3] Add console commands `interference` and `capture` to `extractor/SwReview.Extractor.Console/Program.cs`
- [X] T072 [US3] Implement `extractor/SwReview.Extractor.Console/Serve/PipeServer.cs` (named pipe, one JSON request per line, single STA worker thread owning the `SldWorks` reference, `ReadOnlyGuard` on every request, `CircuitBreaker`, commands `capture|measure|interference`)
- [X] T073 [US3] Implement `reviewer/src/swreview/bridge/client.py` and the tools `bridge_capture`, `bridge_measure`, `bridge_interference` in `reviewer/src/swreview/tools/bridge.py`, registered only with `--bridge`; `request_capture` uses the bridge when present
- [X] T074 [US3] Add CLI commands `exceptions accept` and `exceptions list` to `reviewer/src/swreview/cli.py`
- [X] T075 [US3] Create golden fixture `reviewer/tests/golden/fixtures/bracket-assy-interference/` (three seeded interferences, one six-instance pattern, one accepted exception, one truncated pair) with expected grouped findings and coverage
- [ ] T076 [US3] Add Task Pane buttons **Interference** and **Capture selection** to `extractor/SwReview.AddIn/`; run quickstart Scenario 3 on the workstation and record results in `benchmarks/native/bracket-assy/notes.md`

**Checkpoint**: Interference findings are grouped, excepted, and re-flagged on change; the bridge serves captures.

---

## Phase 6: User Story 4 - Guided Fit and Tolerance Checks (Priority: P4)

**Goal**: Deterministic diameter fit and axial stack checks from explicit drawing dimensions, with unknown tolerances staying unresolved.

**Independent Test**: quickstart Scenario 4.

### Tests for User Story 4

- [X] T077 [P] [US4] Unit tests in `reviewer/tests/unit/test_checks_fit.py`: limits, symmetric and bilateral tolerances give correct min/max clearance and interference; `tolerance.kind == "none"` on either side yields `unresolved` naming the missing side; mixed units (inch bore, mm shaft) report `source` and `converted`; an `Angle` input raises before calculation; result includes `model == "fit.size_only"` and `excluded_effects`
- [X] T078 [P] [US4] Unit tests in `reviewer/tests/unit/test_checks_stack.py`: worst-case stack with signs; a single untoleranced dimension yields `unresolved`; a general-note tolerance supplied through `Tolerance.source` is used and cited; target gap comparison; zero-length stack rejected

### Implementation for User Story 4

- [X] T079 [P] [US4] Implement `reviewer/src/swreview/checks/fit.py` (`check_fit(bore: Dimension, shaft: Dimension) -> CheckResult`)
- [X] T080 [P] [US4] Implement `reviewer/src/swreview/checks/stack.py` (`check_axial_stack(dims, signs, target) -> CheckResult`, worst-case model)
- [X] T081 [US4] Add tools `check_fit` and `check_axial_stack` to `reviewer/src/swreview/tools/checks.py` (resolve `SourceRef`s to `Dimension`s in the package; refuse raw numbers) and CLI `check fit|stack`
- [X] T082 [US4] Create golden fixtures `reviewer/tests/golden/fixtures/{shaft-bore,plate-stack,mixed-units,angle-not-length}/` with expected findings; `angle-not-length` must produce an error result, never a number

**Checkpoint**: Fit and stack checks reproduce hand calculations and never default a tolerance.

---

## Phase 7: User Story 5 - Fastener and Hole Compatibility (Priority: P5)

**Goal**: Screw bottoming, engagement, thread match, head/washer clearance, and hole alignment from native hole and fastener data plus mesh raycasting.

**Independent Test**: quickstart Scenario 5.

### Tests for User Story 5

- [X] T083 [P] [US5] Unit tests in `reviewer/tests/unit/test_checks_fastener.py`: bottoming margin and engagement ratio computed from screw length, clamped stack, washer, and usable thread depth; `thread_depth is None` yields `unresolved` naming usable thread depth; thread designation mismatch yields `demonstrated`; engagement rule chosen by hole material with the rule cited; unsupported joint kind (`pin`, rivet) yields `out_of_scope`; missing clamped component yields `unresolved`
- [X] T084 [P] [US5] Unit tests in `reviewer/tests/unit/test_geometry.py`: `axis_distance` and angle between skew, parallel and coincident axes; `face_gap` for parallel planes and coaxial cylinders, `unsupported` otherwise; `envelope_raycast` against a box mesh with and without `embreex` (marker `raycast`), and `unresolved` when a mesh file is missing
- [X] T085 [P] [US5] Unit tests in `reviewer/tests/unit/test_checks_hole_alignment.py`: coaxiality from two hole axes; tolerance from a `SourceRef` or `unresolved` when none

### Implementation for User Story 5

- [X] T086 [P] [US5] Implement `reviewer/src/swreview/geometry/mesh.py` (GLB/STL loading via trimesh with unit handling), `axis.py` (`axis_distance`, `face_gap`), `envelope.py` (`envelope_raycast` with optional embreex)
- [X] T087 [P] [US5] Create `reviewer/src/swreview/checks/engagement_rules.yaml` (minimum engagement as a multiple of nominal diameter per material class: steel, aluminum, cast iron, plastic; source noted per row) and a loader with tests in `reviewer/tests/unit/test_engagement_rules.py`
- [X] T088 [US5] Implement `reviewer/src/swreview/checks/fastener.py` (`check_fastener_joint(fastener, hole, clamped, washers) -> list[CheckResult]` for `fastener.bottoming`, `fastener.engagement`, `fastener.thread_match`, `fastener.head_clearance`)
- [X] T089 [US5] Implement `reviewer/src/swreview/checks/hole_alignment.py`
- [X] T090 [US5] Add tools `measure_axis_distance`, `measure_face_gap`, `check_tool_envelope`, `bounding_box`, `check_fastener_joint`, `check_hole_alignment` to `reviewer/src/swreview/tools/` and CLI `check fastener|alignment`
- [X] T091 [US5] Create golden fixtures `reviewer/tests/golden/fixtures/{joint-bottoming,joint-ok,joint-unsupported,thread-mismatch,tool-envelope}/` with expected findings

**Checkpoint**: Fastener findings cite fastener, hole, stack and rule; unknown thread depth is never cleared.

---

## Phase 8: User Story 6 - Benchmark Evaluation and Scorecard (Priority: P6)

**Goal**: Run the reviewer across the benchmark set with answer keys withheld and produce the scorecard for the 2026-10-03 checkpoint.

**Independent Test**: quickstart Scenario 6.

### Tests for User Story 6

- [X] T092 [P] [US6] Tests in `reviewer/tests/unit/test_answer_key_isolation.py` and `reviewer/tests/integration/test_answer_key_isolation.py`: the loader refuses `benchmarks/answer_keys/`; the benchmark runner never passes an answer-key path to the reviewer; a symlinked package pointing into `answer_keys` is refused
- [X] T093 [P] [US6] Tests in `reviewer/tests/unit/test_scorecard.py`: matching findings to known defects by check and component ids; recall and false-alarm rate with null handling; median net saved minutes; distribution order matches `per_package`; output validates against `contracts/scorecard.schema.json`
- [X] T094 [P] [US6] Tests in `reviewer/tests/unit/test_timing.py`: `net_saved_minutes = baseline - (supervision + verification + false_alarm_handling)`; unattended runtime excluded; `None` baseline gives `None`

### Implementation for User Story 6

- [X] T095 [P] [US6] Implement `reviewer/src/swreview/benchmark/sets.py` (`pilot.json` schema: package dirs, held-out flags) and `answer_key.py` (loaded only by the scorer)
- [X] T096 [US6] Implement `reviewer/src/swreview/benchmark/runner.py` (runs `review` per package into a run directory; records unattended runtime) and `scorecard.py` (matching, aggregates, `scorecard.json` and `scorecard.md`)
- [X] T097 [US6] Add CLI commands `benchmark run|score|time` to `reviewer/src/swreview/cli.py`
- [ ] T098 [US6] Assemble `benchmarks/sets/pilot.json` with 5 to 10 packages (including a shaft/bearing fit, a bolted plate stack, a sheet-metal or welded assembly, at least two held out) and their answer keys in `benchmarks/answer_keys/`; record human baseline times with `swreview benchmark time`
- [ ] T099 [US6] Run `swreview benchmark run` and `score` on the pilot set; commit `runs/benchmark-<date>/scorecard.md` to `benchmarks/results/` and summarize the continue/narrow/revise/stop evidence in `benchmarks/results/checkpoint-2026-10-03.md`

**Checkpoint**: A scorecard with per-package and aggregate results exists for the checkpoint.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T100 [P] Write the root `README.md`: purpose, layout, how to build the extractor and run the reviewer, link to `specs/001-agentic-design-review/quickstart.md`
- [X] T101 [P] Add `NOTICE.md` attributing MIT-derived patterns (`solidworks-skills` connection manager and circuit breaker ideas) and stating that SwpilotCLI is referenced only
- [X] T102 [P] Add a CI workflow `.github/workflows/reviewer.yml` running `uv run pytest` on Windows and Ubuntu (integration tests skipped) and `ruff check`
- [ ] T103 Run every quickstart scenario end to end; fix discrepancies between quickstart, contracts, and behavior
- [X] T104 DRY and constitution review across `reviewer/src/swreview/checks/` and `tools/`: one finding builder, one unit module, no duplicated id resolution; update `research.md` with any decision changes
- [X] T105 Regenerate `contracts/ir.schema.json` from the models (`python -m swreview.ir.schema --write`) and confirm `test_schema_sync` and the C# serializer test still pass *(Done as verification: `test_schema_sync` proves the generated schema is semantically equal to the hand-authored contract and the cover-blind-tap package validates against both; the contract file is kept hand-authored for readability.)*

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks all user stories
- **US1 (Phase 3)**: depends on Foundational; no SOLIDWORKS needed
- **US2 (Phase 4)**: depends on Foundational (C# DTOs); needs the workstation for T061
- **US3 (Phase 5)**: Python half depends on Foundational; C# half depends on US2 dumpers (component ids, persist refs); bridge tools depend on US1 tool registry
- **US4 (Phase 6)**: depends on Foundational and US1 tool registry; runs on hand-curated fixtures
- **US5 (Phase 7)**: depends on Foundational and US1 tool registry; mesh tests use fixture GLBs, real meshes come from US2
- **US6 (Phase 8)**: depends on US1 (review command); scoring of interference, fit and fastener defects needs US3 through US5
- **Polish (Phase 9)**: depends on all desired stories

### User Story Dependencies

- **US1 (P1)**: independent MVP
- **US2 (P2)**: independent of US1 at code level; its output feeds US1 reviews
- **US3 (P3)**: needs US2 for native interference; grouping and exceptions testable on fixtures alone
- **US4 (P4)**: independent of US2 and US3
- **US5 (P5)**: independent of US3 and US4; needs US2 only for real meshes
- **US6 (P6)**: needs US1; benefits from all others

### Within Each User Story

- Tests are written and fail before implementation
- Models before checks, checks before tools, tools before CLI and agent wiring
- Golden fixture added before the story's checkpoint

### Parallel Opportunities

- Phase 1: T003, T004, T005, T006 in parallel after T001 and T002
- Phase 2: T020, T021, T022 (C#) in parallel with T007 through T019 (Python)
- Phase 3: T023 through T029 in parallel; T032 and T033 in parallel
- Phase 4: T045 through T048 in parallel; dumpers T050 through T057 can be split across people once T049 exists
- Phases 6 and 7 can run in parallel with Phase 4 on a machine without SOLIDWORKS
- Phase 8: T092 through T095 in parallel

---

## Parallel Example: User Story 1

```bash
# Tests first, in parallel (different files):
Task: "Unit tests for manifest ingest in reviewer/tests/unit/test_ingest_manifest.py"
Task: "Unit tests for the dimension grammar in reviewer/tests/unit/test_dimension_grammar.py"
Task: "Unit tests for the PDF drawing parser in reviewer/tests/unit/test_pdf_parser.py"
Task: "Unit tests for package query tools in reviewer/tests/unit/test_tools_query.py"

# Then implementations that share no files:
Task: "Implement reviewer/src/swreview/ingest/manifest.py"
Task: "Implement reviewer/src/swreview/ingest/bom.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1
4. **STOP and VALIDATE**: run quickstart Scenario 1 on a real package (T044); this is the
   README's day-one objective
5. Decide from the first investigation's missing evidence which of US2 through US5 to pull
   forward

### Incremental Delivery

1. Setup + Foundational → schemas and harness green
2. US1 → first evidence-linked review on exported files (MVP)
3. US2 → native packages; US1 reviews get threads, fasteners, mates
4. US4 and US5 in parallel with US2 on fixtures → numeric checks
5. US3 → interference, exceptions, bridge
6. US6 → scorecard for the 2026-10-03 checkpoint

### Parallel Team Strategy

- Developer with the workstation: US2, then US3 C# half
- Developer without SOLIDWORKS: US1, then US4 and US5, then US6
- Both: Phase 9

---

## Notes

- [P] tasks touch different files and have no dependency on incomplete tasks
- Every check task pairs with a golden fixture; a schema change requires T105
- Commit after each task or logical group; stop at any checkpoint to validate the story
- Avoid cross-story file conflicts: `tools/checks.py` is extended by US3, US4, US5 in
  separate functions; coordinate merges or split per story (`tools/checks_fit.py`, etc.) if
  working in parallel
