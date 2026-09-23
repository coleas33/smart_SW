# ADR-001: Where the SolidWorks reviewer and drawing automation should live

**Status:** Proposed
**Date:** 2026-09-12
**Deciders:** engineering team (design-check add-in owners)

## Context

We are building an AI/smart reviewer for SolidWorks assemblies and parts (programmatic and/or agentic) plus automated drawing creation for parts. Constraints and current state:

- SolidWorks is the required end target for drawings. Reviewing does not have to happen inside SolidWorks.
- A clean SolidWorks add-in skeleton (C#) already exists. v1 scope is deterministic checks plus visual review documents; the LLM/chat layer is deferred.
- v1 checks: static interference (summary plus zoomed screenshots compiled into a review document), fastener thread engagement, hole alignment (tolerance stack-up later), tool access above screw heads, mass/material for all geometry, hygiene (part numbers, etc.).
- Open question: keep the review in the SolidWorks API, or export geometry into open-source CAD tooling (FreeCAD, OCCT/CadQuery/build123d) and review there?

The framing that matters is not "SolidWorks API vs. open-source CAD." It is: **where does the semantic data live, and where does the reasoning run?**

## Decision (proposed)

Adopt a **hybrid, three-layer architecture**:

1. **Extraction and SW-native checks inside SolidWorks** (in-process C# add-in) that dump a rich intermediate representation (IR) of the model.
2. **Reasoning, checks, and the agent layer in Python** operating on the IR, outside SolidWorks.
3. **Drawing generation back in SolidWorks** via the API, driven by a drawing plan produced in layer 2, using SW 2026's Auto-Generate Drawing as the first pass where it proves usable.

Open-source geometry libraries (OCCT via OCP/CadQuery, trimesh) are used as *libraries in layer 2*, never as a host CAD application.

## Options considered

### Option A: Everything inside SolidWorks (add-in only)

All checks, the review document, and any agent loop run in C# against the SolidWorks COM API.

**Pros**
- Full access to features, mates, Hole Wizard data, Toolbox metadata, custom properties, configurations.
- Best-in-class interference detection and mass properties for free.
- One codebase, one deployment target (the add-in that already exists).

**Cons**
- COM is Windows-only, single-threaded (STA), and needs a licensed, running SW instance for every run.
- No parallelism, no CI on Linux, no replaying a review 50 times while tuning prompts without burning a SW seat.
- Hosting an LLM tool-calling loop in C#/COM is slow to iterate and awkward to test.

### Option B: Export to open-source CAD for review

Export STEP/Parasolid/meshes, review in FreeCAD or an OCCT-based Python stack, then generate drawings in SolidWorks.

**Pros**
- Python-native, cross-platform, parallel, CI-friendly, and pleasant for agent tooling.
- Reviews can run on any machine without a SolidWorks license.

**Cons**
- **Information loss at export is the killer.** STEP drops Hole Wizard thread spec/depth, cosmetic threads, Toolbox fastener identity (size, length, head/drive type), mates, most custom properties, and configurations.
- Thread engagement, hole alignment, tool access over screw heads, and hygiene checks are trivial with feature/metadata access and become hard geometry-recognition problems from raw B-rep or meshes.
- Interference via OCCT booleans on re-imported STEP is slower and produces false hits from tolerance mismatches and healing artifacts.
- Two sources of truth and a fragile export step in the loop.

### Option C: Hybrid (recommended)

SolidWorks does what only SolidWorks can do (read semantics, run interference, capture views, make drawings). Python does the reasoning on an IR that carries the semantics across.

**Pros**
- Keeps every piece of semantic data the checks depend on.
- Agent and geometry checks run anywhere, in parallel, against replayable dumps; SolidWorks is out of the loop during review iteration.
- Extraction is a thin, fast dump, so SW instance time per review is minimized.
- The same IR is what a URDF/MJCF simulation exporter wants, so sim export and review share one representation.

**Cons**
- Two languages (C# for the add-in, Python for reasoning) and an IR schema to own and version.
- Some checks need face-level geometry in the IR, so the dump has to be designed deliberately rather than grown ad hoc.

## Trade-off summary

| Dimension | A: All-in-SW | B: Open-source CAD | C: Hybrid |
|---|---|---|---|
| Semantic fidelity (holes, fasteners, mates, props) | High | Low | High |
| Interference quality | High | Medium (false hits) | High (done in SW) |
| Agent/LLM iteration speed | Low | High | High |
| Parallelism / CI | None | High | High |
| SW license needed per review run | Yes | No | Only for extraction and drawings |
| Implementation complexity | Medium | High (geometry recognition) | Medium |
| Team familiarity | High (add-in exists) | Medium | High + Python |
| Maintenance risk | Low | High (export drift) | Medium (IR schema) |

## Architecture detail

### Layer 1: Extraction and SW-native checks (in-process C# add-in)

Use the existing add-in skeleton. In-process calls are 10 to 100x faster than out-of-process COM, which matters on large assemblies.

**Dump to the IR (JSON + mesh files + PNG captures):**
- Component tree with transforms, suppression state, and active configuration (`IComponent2`, `Transform2`).
- Mates: type, entities, alignment (`IMate2`).
- Holes: type, standard, size, thread type and depth (`IWizardHoleFeatureData2`); cosmetic threads (`ICosmeticThreadFeatureData`).
- Toolbox fasteners: part type plus size/length/head from Toolbox properties (`IModelDocExtension.ToolboxPartType` and the component's properties).
- Materials and mass properties (`GetMaterialPropertyName2`, `IMassProperty2`).
- Custom and configuration-specific properties (`ICustomPropertyManager`).
- Face-level geometry needed by checks: cylinder axis/radius and plane normal/origin (`IFace2.GetSurface` -> `ISurface.CylinderParams` / `PlaneParams`), face bounding boxes.
- Persistent reference IDs for every entity emitted (`GetPersistReference3`) so layer-2 findings can point back to SW entities for screenshots and drawing notes.
- Tessellated bodies (`IBody2.GetTessellation` or per-body STL export).

**Run here, because SolidWorks does these best:**
- Interference detection via `IInterferenceDetectionManager` (coincident-face handling, multibody options, fastener treatment), returning interfering component pairs and volumes.
- Mass properties per body and overall.
- Zoomed captures of each finding for the review document (zoom to selection, save image).

**Hygiene checks at scale:** use the SolidWorks Document Manager API to read custom properties, configurations, and references without launching SolidWorks. Hundreds of files in seconds. Requires the Document Manager license key (available to subscription customers via the customer portal).

### Layer 2: Reasoning and agent (Python, on the IR)

- **Schema:** typed IR (pydantic), versioned. Meshes as GLB or STL. Captures as PNG keyed by persistent reference.
- **Deterministic checks:**
  - Thread engagement: fastener length vs. clamped stack thickness plus tapped depth, against a per-material engagement rule.
  - Hole alignment: coaxiality of hole axes across mating parts from the cylinder-face data; later, feed the tolerance stack-up.
  - Tool access: raycast a driver/tool envelope above each screw head against the tessellated assembly (trimesh + embree).
  - Edge margins, minimum wall, and similar mesh/B-rep checks.
- **Agent layer:** LLM tool-calling over the IR (query components, holes, fasteners, findings; request captures; propose drawing plans). Runs anywhere, in parallel, with golden-assembly regression tests.
- **Geometry libraries:** OCP/CadQuery only when geometry must be *constructed* (tool envelopes, offsets, clearance solids). Not as a host.
- **Output:** a findings report (feeds the visual review document) and a **drawing plan** per part (views, sections, dimensions to force, notes derived from findings).

### Layer 3: Drawings (SolidWorks API)

SolidWorks is the only drawing target, so this layer is non-negotiable.

**First pass: SW 2026 Auto-Generate Drawing (Beta).** SolidWorks 2026 can generate drawings for selected parts and assemblies automatically: it picks a template and sheet size, inserts and scales views to avoid overlap, adds section views, hole callouts, tolerances and reference dimensions, and for assemblies inserts BOMs, auto-balloons, and revision tables. It runs in the background. Vendor write-ups say results usually still need cleanup, and the feature is still marked Beta. That changes the plan: **do not build view and dimension placement from scratch.** Let SolidWorks draft, then validate and clean up.

**Second pass: API-driven validation and cleanup**, driven by the layer-2 drawing plan:
- Enforce company template, sheet format, and standards.
- Confirm required views/sections exist; add missing ones (`CreateDrawViewFromModelView3`, `Create3rdAngleViews2`, `CreateSectionViewAt5`).
- Confirm required dimensions exist; insert missing driving dimensions (`InsertModelAnnotations3`) and reposition.
- Insert notes tied to review findings; BOM tables and balloons for assemblies (`InsertBomTable4`, `AutoBalloon5`).
- Verify API method names against the API help for the installed SW version.

**Fallback:** if Auto-Generate Drawing is unusable (no API exposure, licensing, quality), the second pass becomes a rule-based generator: template-driven view sets by part class (turned part: two views plus section; sheet metal: flat pattern plus bend table; plate: one view plus thickness note) with rules in a YAML config the agent fills in.

### Amendment 2026-09-22: checks first, and drawings in two stages

The pilot showed where the tokens and the value go (`docs/roadmap-2026-09-22.md`). Two
changes to the layers above, both decided by the owner on 2026-09-22:

- **Layer 2 runs code first.** Every check that code can enumerate from the IR runs before
  the first model turn - modelling practice, equations, assembly, standards, interference
  (including the live detection call), and, as feature 010 lands them, the joint map,
  alignment, fastener engagement, tool access, mass and hygiene checks. The agent reads a
  digest, not the payloads; it explains, asks the engineer targeted questions, and
  investigates what no enumerator can scope. Old tool results leave the conversation as
  short stubs while their full payloads stay in the run folder, and calls run in parallel.
  The agent layer is where judgement happens, not where checks are driven.
- **Layer 3 is reached in two stages.** Stage one is read-only drawing context: drawings
  attached to part and assembly dumps, their native dimensions, tolerances and tables
  extracted, and a per-part drawing brief that tells a model what the part is, how it is
  assembled and which interfaces need a callout. Stage two is creation, and only after a
  constitution amendment and seat probes: the model proposes a drawing plan citing real
  entities, the engineer reviews it, and a gated executor writes a new drawing into the run
  folder. SOLIDWORKS 2024 SP5 has no auto-generate drawing API, so the fallback above - a
  rule-based generator by part class - is the first pass, not the second.
- **Creation starts from the owner's existing base.** The owner has an outline and base
  repository for programmatically creating drawings. It is evaluated first - what it
  draws, with which API members, from which inputs - and stage two is designed around it
  rather than built from scratch (`docs/roadmap-2026-09-22.md`, "Start from the existing
  drawing-creation base").

## Consequences

**Easier**
- Every v1 check keeps its native data source; no geometry-recognition research project.
- Agent development and testing happen in Python against saved dumps, with no SolidWorks in the loop.
- Reviews can run in parallel on cheap machines; SolidWorks seats are used only for extraction and drawing generation.
- One IR can serve the reviewer and a simulation exporter.

**Harder**
- Owning and versioning the IR schema; any new check may need new fields in the dump.
- Two-language codebase (C# add-in, Python reasoning).
- Round-tripping findings back into SolidWorks depends on persistent references being emitted consistently.

**Revisit later**
- Whether the agent should drive SolidWorks live (via an MCP server) for interactive review sessions, versus batch dumps only.
- Whether Document Manager plus the IR makes the visual review document generatable without opening every assembly.

## Open questions to verify before committing

- [ ] Is Auto-Generate Drawing callable from the API, or GUI-only? Does it run in batch?
- [ ] Does it (or the Virtual Companion natural-language drawing generation) require 3DEXPERIENCE/cloud connectivity or a specific license tier?
- [ ] Does SW 2026's automatic fastener recognition expose data the tool-access check can consume?
- [ ] Document Manager license key availability for the team.
- [ ] Licensing for an unattended SolidWorks automation seat if reviews are to run on check-in.

## Implementation notes and gotchas

- If SolidWorks is wrapped as an MCP server (Python + pywin32), marshal every COM call onto one STA thread; cross-thread COM calls fail intermittently.
- Keep out-of-process tool calls coarse (one call = one big operation). Per-call COM overhead across processes is high; fine-grained traversal belongs in the in-process add-in.
- Emit persistent reference IDs from day one. Retrofitting them is the most painful change.
- Version the IR schema and keep golden assemblies for regression tests of both the dump and the checks.
- Treat the agent as a consumer of the IR and a producer of plans; keep SolidWorks execution deterministic and template-driven.

## Action items

1. [ ] Define the IR schema v0 (components, mates, holes, fasteners, materials, props, faces, meshes, captures, persistent refs).
2. [ ] Add "dump IR" as a first-class command in the existing add-in; keep interference, mass properties, and captures in the add-in.
3. [ ] Stand up the Python package: IR loader, thread-engagement and hole-alignment checks, golden-assembly tests.
4. [ ] Prototype tool-access raycasting on one real assembly.
5. [ ] Trial Auto-Generate Drawing on five representative parts; record what it gets right and what needs cleanup.
6. [ ] Decide first-pass drawing strategy (Auto-Generate + cleanup vs. rule-based generator) from the trial results.
7. [ ] Prototype Document Manager hygiene sweep across a project folder.

## Sources

- SOLIDWORKS 2026 Help, Auto-Generate Drawings: https://help.solidworks.com/2026/English/SolidWorks/sldworks/c_auto_generate_drawings.htm
- SOLIDWORKS blog, What's New in SOLIDWORKS 2026 Design: https://blogs.solidworks.com/products/solidworks/whats-new-in-solidworks-2026-design/
- SOLIDWORKS AI overview (drawing generation via Virtual Companions, fastener recognition): https://www.solidworks.com/product/solidworks-design/ai-overview
- SolidProfessor, SOLIDWORKS 2026 What's New for Drawings: https://solidprofessor.com/blog/solidworks-2026-whats-new-for-drawings/
