# Implementation Plan: SOLIDWORKS Agentic Design Review Pilot

**Branch**: `001-agentic-design-review` | **Date**: 2026-09-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-agentic-design-review/spec.md`

## Summary

Build a design-review assistant for SOLIDWORKS 2024 assemblies and drawings that
investigates a review package, gathers evidence through a curated tool set, runs
deterministic checks (fit, stack, fastener, interference grouping, hole alignment), and
writes a findings report the engineer can navigate and disposition. The architecture is
ADR-001's hybrid: a C# extractor inside SOLIDWORKS dumps a versioned intermediate
representation (IR); a Python reviewer runs the checks and the Claude tool-calling loop on
the IR anywhere; an optional bridge back to SOLIDWORKS provides captures and measurements on
demand. Drawing generation (ADR-001 layer 3) is a separate future feature.

## Technical Context

**Language/Version**: Python 3.11+ (reviewer, checks, agent) and C# on .NET Framework 4.8
(extractor add-in and console host; SOLIDWORKS 2024 interop targets .NET Framework).

**Primary Dependencies**: Python: `anthropic` (beta tool runner, `@beta_tool`), `pydantic` v2,
`pint`, `trimesh` (+ optional `embreex`), `PyMuPDF`, `pdfplumber` (tables only), `typer` (CLI),
`pytest`, `pytest-regressions`. C#: `SolidWorks.Interop.sldworks`, `swconst`, `swpublished`
(2024), `Newtonsoft.Json` or `System.Text.Json`, an MSTest or xUnit project.

**Storage**: Files only. One directory per evidence package (`package.json`, `meshes/`,
`captures/`, `drawings/`), one directory per review run (`session.json`, `report.md`),
`exceptions.json` per package, `benchmarks/` with `answer_keys/` isolated.

**Testing**: `pytest` with unit tests per check and golden fixture directories
(`pytest-regressions`); C# unit tests for the IR serializer and pure helpers; integration
tests against a saved native package (skipped when absent); one manual round-trip test on
the workstation for persistent references.

**Target Platform**: Reviewer: Windows, macOS, Linux (no SOLIDWORKS needed). Extractor and
bridge: Windows 11 workstation with SOLIDWORKS 2024 and EPDM working copy.

**Project Type**: Two-language monorepo: `extractor/` (C# library + add-in + console) and
`reviewer/` (Python package + CLI).

**Performance Goals**: A review of a 200-component assembly package completes in under
15 minutes unattended; extraction of the same assembly in under 5 minutes in-process;
a deterministic check returns in under 1 second; report re-render in under 1 second.

**Constraints**: LLM never produces a number used in a verdict; no code-execution tool; all
COM calls on one STA thread; persistent references on every emitted entity; missing input
stays unknown; SwpilotCLI code not redistributed; GPL code not linked.

**Scale/Scope**: Pilot: 5 to 10 benchmark packages, assemblies up to roughly 500 components,
drawing packages up to roughly 30 sheets, one reviewer agent, single workstation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | How this plan meets it | Status |
|-----------|------|------------------------|--------|
| I. Evidence before conclusions | Every finding carries the required fields; unknown stays unknown | `Finding` schema enforces fields and status rules (contracts/review-session.schema.json `allOf`); check functions return `unresolved` on null inputs; `Gap` list feeds coverage | PASS |
| II. Deterministic numerics | No LLM arithmetic; SolidWorks does SolidWorks things | Numbers enter findings only through check tools; `record_drawing_finding` cannot mark `demonstrated`; interference and captures run in C# | PASS |
| III. Test-first with golden fixtures | Tests before implementation; goldens per check | tasks.md orders test tasks before implementation in every story; golden fixture directory per check; schema-vs-model equality test | PASS |
| IV. Semantic fidelity and traceability | Persistent refs day one; versioned IR; native over export | `persist_ref` required on every IR entity; `schema_version` gate; `ingest` lets native data override PDF/STEP data | PASS |
| V. Engineered enough | DRY, explicit, no speculative abstraction | One `units` module, one `SourceRef` type, one finding builder shared by all checks; no plugin framework; bridge is optional and thin | PASS |
| VI. Inspectable findings, coverage tracked | Coverage buckets; exceptions bound to geometry; measurement | `Coverage` with five buckets required in every session; `Exception.geometry_fingerprint`; `Timing` and `Scorecard` | PASS |
| Technical constraints | SW 2024, STA COM, no exec tool, licenses | R1, R3, R4, R14 in research.md | PASS |
| Development workflow | Spec → plan → tasks; review gates | This document; tasks.md follows | PASS |

Post-design re-check (after Phase 1): no violations. Complexity Tracking below is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-agentic-design-review/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── README.md
│   ├── ir.schema.json
│   ├── review-session.schema.json
│   ├── scorecard.schema.json
│   ├── agent-tools.md
│   └── cli.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
extractor/                                  # C#, .NET Framework 4.8
├── SwReview.sln
├── SwReview.Extractor/                     # class library: all SOLIDWORKS API access
│   ├── Ir/                                 # IR DTOs mirroring contracts/ir.schema.json
│   ├── Dump/                               # component tree, mates, holes, fasteners, props, faces, meshes
│   ├── Interference/                       # IInterferenceDetectionManager wrapper
│   ├── Capture/                            # zoom-to-selection + PNG save
│   ├── PersistRefs/                        # GetPersistReference3 / GetObjectByPersistReference3
│   └── Guard/                              # read-only allowlist, circuit breaker
├── SwReview.AddIn/                         # in-process add-in: Task Pane buttons
├── SwReview.Extractor.Console/             # dump | interference | capture | resolve | serve
└── SwReview.Extractor.Tests/               # serializer + pure helper tests

reviewer/                                   # Python 3.11+, uv, src layout
├── pyproject.toml
├── src/swreview/
│   ├── ir/                                 # pydantic models, loader, version gate, schema export
│   ├── units.py                            # pint wrapper: Length, Angle, convert()
│   ├── ingest/                             # manifest, BOM, PDF drawing parser, STEP (optional)
│   ├── geometry/                           # mesh loading, axis distance, face gap, envelope raycast
│   ├── checks/                             # fit, stack, fastener, hole_alignment, interference, drawing
│   ├── findings.py                         # Finding builder shared by all checks
│   ├── exceptions.py                       # Exception store + geometry fingerprint
│   ├── tools/                              # @beta_tool wrappers (contracts/agent-tools.md)
│   ├── agent/                              # runner, system prompt, checklist, step recorder
│   ├── bridge/                             # named-pipe client for the C# serve mode
│   ├── report/                             # session.json I/O, Markdown renderer, dispositions
│   ├── benchmark/                          # set runner, answer-key isolation, scorecard
│   └── cli.py                              # typer app: contracts/cli.md
└── tests/
    ├── unit/                               # per module; invalid/missing/unit/boundary cases
    ├── golden/fixtures/<case>/             # package.json + expected findings (pytest-regressions)
    └── integration/                        # needs a saved native package; skipped if absent

benchmarks/
├── packages/<name>/                        # review packages (exported and/or native)
├── native/<name>/                          # SOLIDWORKS files for extraction tests (workstation)
├── answer_keys/<name>.json                 # never readable by the reviewer process
└── sets/pilot.json                         # which packages, which are held out
```

**Structure Decision**: Two top-level projects sharing one IR contract. `extractor/` holds
every line that touches the SOLIDWORKS API so the reviewer never needs a CAD seat.
`reviewer/` uses a src layout so tests run against the installed package. `benchmarks/`
sits outside both so packages are shared and answer keys can be permission-isolated.

## Phase 0: Research

Completed in [research.md](research.md): extraction placement (R1), agent loop (R2), live
bridge (R3), guardrails (R4), IR schema approach (R5), units (R6), meshes (R7), drawing
PDFs (R8), testing (R9), report format (R10), layout (R11), SOLIDWORKS API surface (R12),
Document Manager (R13), reuse policy (R14). Open questions are listed there and tracked as
risks below.

## Phase 1: Design

Completed: [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md).

Key design points that tasks must honor:

1. **One finding builder.** `swreview.findings.build_finding(...)` is the only way a
   `Finding` is created. It validates status rules (evidence for `demonstrated`, coverage
   limits for `unresolved`) and attaches provenance from the manifest.
2. **Checks are pure functions** taking IR entities and returning a `CheckResult`
   (`Calculation` + status + limits). Tools wrap them; the CLI `check` subcommands call
   them directly. No check reads files or calls the network.
3. **Unknown propagates.** Any `None` input to a calculation yields `unresolved` naming
   the field. No defaults, no inference.
4. **Steps are recorded by the tool layer**, not by the model, using the tool runner's
   per-turn hook. A tool exception becomes `is_error: true` plus a `failed` coverage item.
5. **The bridge is optional.** Everything in US1, US4, US5 and the grouping half of US3 runs
   with no SOLIDWORKS process.
6. **Answer keys are unreadable by construction.** The package loader refuses any path
   under `benchmarks/answer_keys/`; the benchmark runner passes only package directories.

## Delivery order (maps to user stories)

| Order | Story | Deliverable | Needs SOLIDWORKS |
|-------|-------|-------------|------------------|
| 1 | US1 | IR models, units, PDF ingest, findings, tools, agent loop, report, disposition | No |
| 2 | US2 | C# extractor dump, persist refs, add-in buttons, console host | Yes |
| 3 | US3 | C# interference, Python grouping, exceptions, bridge | Yes (interference) |
| 4 | US4 | fit and stack checks | No |
| 5 | US5 | fastener checks, envelope raycast | No (meshes from US2) |
| 6 | US6 | benchmark runner, timing, scorecard | No |

US4 and US5 depend only on the IR and can be built in parallel with US2 against
hand-curated fixture packages.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Tolerance storage is inconsistent across drawings (open question 1) | Missing stays `unresolved`; the first real package answers the question; `ingest` records where each tolerance was found |
| Toolbox identity not exposed for customized libraries | `identity_source` field; `name_parse` results marked `suspected` |
| Face-level persistent references break after other users save, or must be resolved through a different document's extension than expected | `persist_ref_scope` recorded per entity; compare with `IsSamePersistentID`; component-level ref as fallback locator; quickstart Scenario 2 round-trip test |
| `IInterference.Volume` units are undocumented | One-time workstation verification against a known overlap (T069); unit recorded in the IR; no interference volume reported before verification |
| `AccessSelections` leaves a model rolled back on an exception | Every use paired with `ReleaseSelectionAccess` in `finally` (T052); scalar reads avoid it entirely |
| Toolbox size and length have no first-class API | Per-standard parser of configuration name and configuration-specific properties (T053); `identity_source` recorded; unparseable yields nulls |
| `embreex` wheel missing for the workstation's Python | Optional dependency with pure-Python fallback; tests marked |
| Agent over-calls tools or loops | `--max-steps`, effort setting, mandatory checklist ends the loop; step trace in session |
| Late-bound COM failures if a Python bridge is ever attempted | Bridge stays in C#; R3 |
| SwpilotCLI license | Reference only; no code copied (R14) |

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None.
