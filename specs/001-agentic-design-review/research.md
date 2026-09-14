# Research: SOLIDWORKS Agentic Design Review Pilot

**Feature**: `001-agentic-design-review` | **Date**: 2026-09-12 | **Plan**: [plan.md](plan.md)

Phase 0 output. Each item records a decision, its rationale, and the alternatives
considered. Sources are pinned where the research could verify them; items that could not
be verified are marked and carried into the plan as risks.

Research was performed by three subagents (SOLIDWORKS API verification on Opus; Python
stack and connector research on Sonnet) plus the Anthropic API reference bundled with this
session.

## R1. Where extraction runs: in-process C# add-in with a console host

**Decision**: Extraction, interference detection and view capture run in C# against the
SOLIDWORKS 2024 API, packaged as one class library used two ways: an in-process add-in
(Task Pane buttons) and an out-of-process console host for scripting and for the live
bridge. Target .NET Framework 4.8.

**Rationale**: ADR-001 (the architecture proposal) already chose this, and the connector
research confirmed the reasons: in-process calls avoid COM marshaling entirely and are
10 to 100x faster for fine-grained traversal; late-bound Python COM fails on several
SOLIDWORKS methods with many parameters (documented in the `solidworks-skills` repository's
`UNAVAILABLE_APIS` list); and the team already has a C# add-in skeleton. The console host
gives process isolation for the bridge and a place to attach to a running instance
(`GetObject` first, `CreateInstance` fallback), the same pattern SwpilotCLI uses.

**Alternatives considered**: Python plus pywin32 for everything (rejected as the primary
extractor: marshaling gotchas and slower traversal; kept as an option for ad hoc scripts);
SwpilotCLI console tools directly (rejected for reuse: custom license permits internal use
only and forbids redistribution; its drawing reader multiplies values by 1000 and mislabels
angles; useful only as an API reference); FreeCAD/OCCT review on exported STEP (rejected per
ADR-001: loses threads, fasteners, mates, configurations).

## R2. Agent loop: Anthropic Python SDK tool runner with curated tools

> **Amended 2026-09-13.** This build targets OpenAI and Google Gemini only; no Anthropic
> path exists in deployed code. Feature `002-task-pane-assistant` replaces the Anthropic
> tool runner with a provider layer (OpenAI Responses API by default, Gemini
> `generate_content`) behind one `AgentProvider` protocol, and removes the `anthropic`
> dependency. The curated-tool, step-recording and session rules below are unchanged; only
> the loop's SDK changes. See `specs/002-task-pane-assistant/research.md`.


**Decision**: The reviewer is a Python program that drives Claude through the Anthropic SDK's
beta tool runner (`client.beta.messages.tool_runner` with `@beta_tool` functions), model
`claude-opus-5`, adaptive thinking (default), `output_config.effort` set per run (default
`high`), streaming for long turns, and `strict: true` on every tool. Tools are the curated
list in `contracts/agent-tools.md`; there is no code-execution tool. Every tool call is
mirrored into the session's `steps` list.

**Rationale**: The pilot needs a headless, reproducible loop that can run over a benchmark set
with the answer key withheld, record every step, and be tested with golden fixtures. The
tool runner supplies the loop without a hand-written `while stop_reason == "tool_use"`;
its per-turn hooks give approval gates and result interception. Structured `Finding` output
comes from check tools, not from free text, so the model's prose is never the source of a
number. Claude Fable 5.1 is not used because forced tool choice is unavailable on it and its
pricing exceeds Opus tier; Opus 5 is the skill's default for non-trivial agents.

**Alternatives considered**: Exposing tools as an MCP server to Claude Code (rejected for the
core loop: no control over step recording, benchmark isolation, or the system prompt; kept
as a later wrapper for interactive sessions, since the same `@beta_tool` functions can be
registered with the `mcp` SDK); Managed Agents (rejected: tools must run on the workstation
next to SOLIDWORKS and the pilot wants a local, inspectable loop); manual loop (rejected:
the runner covers the needs; drop to manual only if `pause_turn` handling or a custom
transport becomes necessary).

## R3. Live bridge: named pipe to the C# console host, one STA thread

**Decision**: When the reviewer runs on the workstation with `--bridge`, the Python side
sends one JSON request per line over a named pipe to `SwReview.Extractor.Console.exe serve`,
which owns a single STA worker thread with the `SldWorks.Application` reference. Requests
are coarse: capture, measure, interference. Every response carries a status and error text.

**Rationale**: COM interface pointers are bound to the thread that created them; calls from
another thread fail with "interface that was marshalled for a different thread". A single
worker draining a queue is the accepted fix (confirmed by the connector research and by
ADR-001's gotchas). Keeping the worker in the C# process rather than in Python avoids the
late-bound COM parameter problems and keeps one attach per session instead of one per call.

**Alternatives considered**: Python STA worker thread with `win32com.client.gencache.EnsureDispatch`
(viable; rejected for the pilot to keep one COM codebase); per-call console exe (rejected as
default: one to two seconds of attach overhead per call; kept as a fallback to isolate any
call that destabilizes the session).

## R4. Guardrails on the tool surface

**Decision**: No tool whose schema accepts code or a shell string. Tool arguments are ids,
enums, and `SourceRef`s validated twice (SDK schema with `strict: true`, then application
checks: ids must exist in the package, paths must be under the package directory, view
names from an enum). The bridge exposes an allowlist of SOLIDWORKS members and refuses
known mutating calls (`EditRebuild3`, `Save3`, `Delete2`, feature creation). A circuit breaker
stops the bridge after three consecutive COM failures and reports `failed` coverage.

**Rationale**: The `alisamsam/Solidworks-MCP` server exposes an `execute_python` tool that runs
arbitrary code with the application and OS in scope; the constitution forbids that. The
`solidworks-skills` repository's verified-API allowlist and circuit breaker are the pattern to
adapt.

## R5. IR schema: pydantic v2, strict, discriminated unions, semver gate

**Decision**: `EvidencePackage` and its entities are pydantic v2 models with
`ConfigDict(strict=True, extra="forbid")`, entity unions discriminated on a `kind` field,
loaded with `model_validate_json` from bytes. A validator on `schema_version` raises a
dedicated `UnsupportedSchemaVersionError` when the major is not supported. Minor bumps add
optional fields only. The JSON Schema in `contracts/ir.schema.json` is generated from the
models and committed; a test asserts the two match.

**Rationale**: Strict mode and `extra="forbid"` catch extractor drift loudly instead of
dropping data. Discriminated unions give direct dispatch and readable errors. A dedicated
exception lets callers distinguish version mismatch from malformed data.

**Alternatives considered**: plain unions (ambiguous errors); an integer version field
(loses the additive-minor/breaking-major rule); dataclasses plus hand validation (reinvents
pydantic).

## R6. Units: pint behind a small explicit module

**Decision**: A `swreview.units` module wraps one shared `pint.UnitRegistry` and exposes only
`Length` and `Angle` helpers plus `convert(q, to_unit)` returning `{source, converted}`.
Schema types `Quantity` and `Angle` are distinct and are converted to pint quantities at
the boundary of each calculation. Hot loops use `.magnitude` floats after conversion.

**Rationale**: pint's dimensional analysis raises on length-versus-angle mixing, the exact
bug class the spec names. The wrapper keeps the vocabulary small and explicit, per the
constitution's "explicit over clever".

**Alternatives considered**: suffix naming conventions (`_mm`) with bare floats (no runtime
enforcement); a hand-rolled unit system (reinvents pint).

## R7. Mesh interchange and raycasting: GLB plus trimesh with optional embreex

**Decision**: The extractor writes one GLB per body (node transform in meters, metadata with
`persist_ref`). Python loads with trimesh; raycasting uses `trimesh.ray.ray_pyembree` when
the `embreex` wheel is installed and falls back to the pure-Python intersector otherwise.
Tool envelopes are `trimesh.creation.cylinder` placed along the fastener axis.

**Rationale**: GLB carries units and hierarchy; STL is unitless and loses hierarchy. `embreex`
is the maintained fork of pyembree with Windows wheels for CPython 3.11 and 3.12; it must
stay optional because wheels lag new CPython releases.

**Alternatives considered**: STL (kept only as a debug export); Open3D or pyrender
(heavier, worse Windows story).

## R8. Drawing PDFs: PyMuPDF for text with positions, regex for dimension grammar

**Decision**: `PyMuPDF` (`fitz`) extracts spans with bounding boxes via `page.get_text("dict")`.
A small grammar parses SOLIDWORKS dimension text (`Ø10.00 ±0.02`, `M6x1.0 - 6H ↧ 12`,
`10.02/10.00`, angular `45° ±0°30'`). Spans are clustered by proximity into a `Dimension`
with `text_as_read` preserved. `pdfplumber` is used only for tabular blocks (hole tables,
BOM). Pages with no text layer set `parse_status: "no_text"` and produce a `Gap`; OCR is out
of scope.

**Rationale**: PyMuPDF is materially faster than pdfplumber and gives positions; the
grammar keeps units and angle-versus-length explicit. Mapping spans to views is heuristic
(view bounding regions) and is reported as `suspected`, never `demonstrated`.

**Alternatives considered**: pypdf (weak position fidelity); SwpilotCLI's drawing reader
(license and correctness problems); native drawing extraction through the C# extractor
(preferred when available and planned as US2 follow-on; PDF parsing remains for day one).

## R9. Testing: pytest with golden fixture directories and pytest-regressions

**Decision**: `tests/golden/fixtures/<case>/package.json` (hand-curated input) plus expected
findings compared with `pytest-regressions` `data_regression` (regenerate intentionally with
`--force-regen`). One parametrized test discovers fixture directories. Unit tests cover every
check's invalid, missing, unit-mismatch, and boundary inputs, and assert `unresolved` on
incomplete inputs. Integration tests requiring a native package are marked and skipped
when the package is absent.

**Rationale**: Purpose-built golden comparison with diff-friendly regeneration; adding a case
is adding a directory. Satisfies Constitution Principle III.

**Alternatives considered**: syrupy (fine for rendered Markdown snapshots, weaker diffs for
nested data); hand-rolled JSON comparison (reinvents regeneration tooling).

## R10. Report format: JSON session as source of truth, Markdown rendering

**Decision**: `session.json` (validated against `contracts/review-session.schema.json`) is the
only source of truth; `report.md` is rendered from it and re-rendered after dispositions.
Navigation is a `swreview://` style link per finding carrying `persist_ref` and document
id, which the add-in resolves to a selection and zoom.

**Rationale**: Machine-readable for the scorecard and golden tests; diff-friendly and
readable without tooling. No HTML templating surface for the pilot.

**Alternatives considered**: HTML report (deferred); JSON only (not engineer-friendly).

## R11. Project layout: monorepo with `extractor/` (C#) and `reviewer/` (Python, src layout)

**Decision**: `reviewer/` is a `uv` project with `src/swreview/` and top-level `tests/`;
`extractor/` is a Visual Studio solution with `SwReview.Extractor` (library),
`SwReview.AddIn`, `SwReview.Extractor.Console`, and `SwReview.Extractor.Tests`. Benchmarks
live under `benchmarks/` with `answer_keys/` excluded from the reviewer's readable roots.

**Rationale**: Two languages, one repository, one IR contract; src layout forces tests to
run against the installed package.

## R12. SOLIDWORKS 2024 API surface for extraction

Verified against the 2024 API help (`help.solidworks.com/2024/english/api/sldworksapi/`,
`.../swconst/`, the persistent-reference programming guide) and CodeStack. Every member
ADR-001 listed exists in 2024; the notes below change how tasks use them.

| Area | Decision | Gotchas confirmed |
|------|----------|-------------------|
| Component tree | Traverse `ConfigurationManager.ActiveConfiguration` → `IConfiguration.GetRootComponent` → recursive `IComponent2.GetChildren` (immediate children only). Key instances by full `Name2` path plus persistent reference. | `GetID` collides across subassemblies. `GetModelDoc2` returns null for suppressed and lightweight components. Setting `ReferencedConfiguration` invalidates a previous `GetChildren` array. `Transform2` is always relative to the root; `ArrayData` is 16 doubles, translation in meters. |
| Suppression | `GetSuppression2` → `swComponentSuppressionState_e`: 0 suppressed, 1 and 4 lightweight, 2 and 3 resolved, 5 internal-id mismatch (record as `unloaded` plus a `Gap`). | Prefer it over `IsSuppressed`, which is configuration dependent. |
| Mates | `IMate2.Type`, `Alignment`, `GetMateEntityCount`/`MateEntity(i)` → `IMateEntity2.EntityParams` (8 doubles, assembly space, meters), `ReferenceType2`, `ReferenceComponent`. | Interpretation of the 8 doubles depends on the mate entity type. |
| Hole Wizard | `IFeature.GetDefinition` → `IWizardHoleFeatureData2`; read scalars (`Diameter`, `HoleDepth`, `ThreadDepth`, `ThreadDiameter`, `EndCondition`, `ThreadEndCondition`, `TapType`, `FastenerSize`, `Standard2`) without `AccessSelections`. | `Standard2` returns −1 for copied or custom standards (fall back to `Standard`). `AccessSelections` rolls the model back; any use must pair with `ReleaseSelectionAccess` in a `finally`. Filter by `GetTypeName2` first; `GetDefinition` returns null for unsupported features. |
| Cosmetic threads | `ICosmeticThreadFeatureData`: `Standard`, `Size`, `Diameter`, `BlindDepth`, `EndCondition`, `ThreadCallout`, `Edge`, patterned transforms. | Same access/release pairing. |
| Toolbox identity | `IModelDocExtension.ToolboxPartType` gives only 0 not Toolbox, 1 standard, 2 copied. Size, length and head come from the referenced configuration name and configuration-specific custom properties (Description, Length, Size, Part Number), parsed per standard. | There is no `IToolboxPartInfo`; the `toolboxapi` namespace is PDM/browser integration only. The parser is unavoidable work and its output is `identity_source: "custom_property"` or `"name_parse"`. |
| Materials and mass | `IPartDoc.GetMaterialPropertyName2(config, out db)`; `IModelDocExtension.CreateMassProperty2` with `UseSystemUnits = true` (kg, m, m³), preselect bodies or components, `Recalculate` after changing options; record `GetOverrideOptions`. | Returns null for surface-only models. |
| Custom properties | `ICustomPropertyManager.GetAll3` per configuration and at document level; `Get6(useCached: true)` for spot reads without activating the configuration. | Cut-list configuration-specific values need the assembly-context cut-list feature pointer. |
| Face geometry | `IFace2.GetSurface` → `ISurface.IsCylinder`/`IsPlane`; `CylinderParams` is 7 doubles (origin, axis, radius, meters); `PlaneParams` is 6 doubles (normal first, then root point). Transform to assembly space with `Transform2`. | `IFace2.GetBox` is documented as approximate and may change after rebuild; use it only for the `bbox` field, never for axes or distances. |
| Persistent references | `IModelDocExtension.GetPersistReference3(obj)` → byte array; `GetObjectByPersistReference3(id, out error)` with `swPersistReferencedObjectStates_e` (0 ok, 1 invalid, 2 suppressed, 4 deleted). Works for components, faces, features; survives sessions, rebuilds and releases. | The bytes for the same entity may differ; compare with `IsSamePersistentID`, never by bytes. The `...3` family is incompatible with the obsolete `GetPersistReference`. **Not verified**: whether a face inside a component must be resolved through the assembly's extension or the part's. The IR therefore records the scope (`persist_ref_scope`) and the bridge resolves against the same document that produced the id; quickstart Scenario 2 tests it. |
| Tessellation | `IBody2.GetTessellation(faceList)` → `ITessellation` with `CurveChordTolerance`, `SurfacePlaneTolerance`, `NeedFaceFacetMap`, `NeedVertexNormal`; facets map back to faces. | `IFace2.GetTessTriangles` is display quality only; kept as a fast fallback. |
| Interference | `IAssemblyDoc.InterferenceDetectionManager` → `IInterferenceDetectionMgr` with `TreatCoincidenceAsInterference`, `TreatSubAssembliesAsComponents`, `IncludeMultibodyPartInterferences`, `IgnoreHiddenBodies`, `CreateFastenersFolder`; `GetInterferenceCount`, `GetInterferences` → `IInterference.Volume`, `Components`, `IsFastener`, `IsPossibleInterference`; always call `Done()`. | **`Volume` units are not documented**; assume m³ and verify on the workstation against a known box overlap before any finding uses it. Record `IsFastener` and `IsPossibleInterference` for triage. |
| View capture | `SelectByID2` → `IModelDoc2.ViewZoomToSelection` → `IModelDoc2.SaveBMP(path, w, h)` or `IModelDocExtension.SaveAs3` with a PNG name. | `ViewZoomToSelection` lives on `IModelDoc2`, not the extension. `IModelView.EnableGraphicsUpdate` only affects refresh during selection. |
| Add-in hosting | COM-visible class implementing `ISwAddin` (`ConnectToSW`/`DisconnectFromSW`), `regasm /codebase` (x64, elevated) plus the `HKLM\SOFTWARE\SOLIDWORKS\AddIns\{GUID}` key; interops from `<install>\api\redist` with Embed Interop Types false; build x64. Target .NET Framework 4.8. | No official statement supports .NET 6/8 add-ins for 2024; the `SolidWorks.Interop.*` NuGet packages are community published. Out-of-process ProgID `SldWorks.Application.32` is 2024; `Activator.CreateInstance` may spawn a new session with no add-ins, so attach through the running object table first. No headless mode exists. |
| Fastener recognition, TolAnalyst, DimXpert | Smart Fasteners have no API in 2024. TolAnalyst has no API (no `ITolAnalyst*` in the namespace; negative evidence only). DimXpert is fully readable through `SolidWorks.Interop.swdimxpert` (`IModelDocExtension.DimXpertManager` → `IDimXpertPart.GetFeatures/GetAnnotations`, `IDimXpertDimensionTolerance.GetUpperAndLowerLimit`). | Decision: tolerance stack math stays in Python (US4); DimXpert tolerances become an optional IR enrichment after the pilot when a model carries a scheme. |

## R13. Document Manager API and licensing

**Decision**: Not on the critical path for this feature. Kept in reserve as a fast metadata
pre-pass (custom and configuration properties, configurations, where-used, drawing sheets)
across large file sets without opening SOLIDWORKS, once a key is obtained.

**Rationale**: The Document Manager API reads properties, configurations, references,
component transforms, cut lists, drawing sheets and DimXpert data, but not mates, faces,
feature parameters or Hole Wizard data, so it cannot produce the IR. The license key is
requested through the SOLIDWORKS Customer Portal, requires an active subscription, and is
version-gated (a key opens its own and older file versions only, so it must be renewed per
major release). DLLs (`SwDocumentMgr.dll`, `zlib.dll`) are redistributable from
`C:\Program Files\Common Files\SOLIDWORKS Shared`.

**Alternatives considered**: Using it for the hygiene sweep now (deferred; the pilot's checks
need native feature data first).

## R14. Third-party code reuse policy

**Decision**: Reuse patterns and API call sequences only from SwpilotCLI (internal-use
license; no redistribution); reuse code from MIT repositories (`solidworks-skills` connection
manager and circuit breaker ideas, `text-to-cad` STEP inspection as a later optional input)
with attribution; do not link GPL-3.0 code (CADAM). `Multi-Agent-CAD` patterns (evidence
contracts, bounded retries) are adopted as design ideas, not code.

## Open questions carried into the plan as risks

1. Where manufacturing tolerances are stored and how consistently (README next action 1).
   Until answered, missing tolerances stay unresolved by design.
2. Document Manager license key availability for the hygiene sweep (see R13).
3. Whether SOLIDWORKS 2024 exposes enough fastener identity for Toolbox parts inserted
   from a customized library (identity falls back to custom properties, then name parsing,
   flagged `suspected`).
4. Reliability of `GetPersistReference3` for face-level entities across saves by other
   users in EPDM, and which document's extension resolves a face inside a component
   (mitigated by `persist_ref_scope`, the re-resolution test in quickstart Scenario 2, and
   component-level refs as a fallback locator).
5. `IInterference.Volume` units are undocumented; verify against a known overlap before
   any interference finding reports a volume.
6. `AccessSelections` rolls the model back; every hole or thread read that needs it must
   release in a `finally` block, and the add-in must never leave a document rolled back.
