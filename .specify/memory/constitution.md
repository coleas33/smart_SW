<!--
Sync Impact Report
- Version change: 1.0.0 → 1.1.0
- Modified principles: none
- Added sections: Technical Constraints → "Documents are read, not written" (the read-only rule,
  previously implicit in Principle II and enforced only in per-plan Constitution Checks, plus the
  two bounded exceptions: 003 suppress-test, 004 re-modeler copy)
- Removed sections: none
- Templates: no edits required
- Migration: specs/003-resilient-modeling/plan.md's Complexity Tracking row for `suppress-test`
  now cites this section rather than standing alone.
-->

# smart_SW Constitution

Governs the SOLIDWORKS agentic design review project: an assistant that investigates
assemblies and drawings, gathers engineering evidence, and reports findings an engineer
can verify.

## Core Principles

### I. Evidence Before Conclusions

Every finding MUST carry the evidence that supports it: affected component instances,
governing drawing sheet or annotation, file version, revision, configuration, source
dimensions with units and tolerances, the tool result or calculation with its assumptions,
and a status of `demonstrated`, `suspected`, `unresolved`, or `checked-within-scope`.

- A missing input MUST stay unknown. The system MUST NOT infer a favorable value
  (for example usable thread depth from drill depth) and clear a check on it.
- A successful API call, a rebuild that succeeds, or a healthy feature tree is NOT an
  engineering acceptance result and MUST NOT be reported as one.
- Unsupported, missing, truncated, and failed checks MUST remain visible in the report as
  unresolved coverage, never silently dropped.

Rationale: the pilot's value is findings an engineer can trust quickly. A confident but
unsupported finding costs more review time than no finding at all.

### II. Deterministic Numerics, Agentic Investigation

Geometry measurement, unit conversion, interference detection, fit and stack
calculations, and every other numerical result MUST come from checked, tested software
functions. The language model MAY decide what to investigate, request evidence, interpret
results, and explain them; it MUST NOT perform the arithmetic that produces a verdict.

- Every calculation exposes its inputs, units, sign conventions, assumptions, and the
  calculation model it used (for example "size-only fit; position, form, coating not
  included").
- SolidWorks does what only SolidWorks can do (read feature and mate semantics, run
  interference, capture views, make drawings). Reasoning runs on an intermediate
  representation (IR) outside SolidWorks so it can be replayed and tested without a
  CAD seat.

Rationale: LLM output is not reproducible; engineering evidence must be.

### III. Test-First With Golden Fixtures (NON-NEGOTIABLE)

Well-tested code is non-negotiable. Too many tests beats too few.

- Every check, calculation, parser, and IR loader MUST have unit tests written before or
  alongside the implementation, and the tests MUST fail before the implementation exists.
- Every check MUST have tests for invalid input, missing input, unit mismatch, and its
  boundary conditions, and MUST assert that an incomplete or failed computation is
  reported as `unresolved`, not as pass.
- Golden assemblies (saved IR dumps plus expected findings) MUST be kept for regression
  of both the extraction and the checks. A change to the IR schema or to a check MUST
  update or add a golden fixture.
- Findings from tool output whose correctness is unverified on the pilot workstation
  (for example a drawing reader with known unit bugs) MUST NOT enter a calculation until a
  test against a known case passes.

Rationale: fit-up and tolerance defects are exactly the class of bug that silent numeric
errors hide; tests are the only defense that scales.

### IV. Semantic Fidelity and Traceability

The IR MUST preserve the semantic data the checks depend on: component tree with
transforms and configurations, mates, Hole Wizard and cosmetic thread data, Toolbox
fastener identity, materials, custom properties, and the face-level geometry each check
needs.

- Every entity emitted into the IR MUST carry a persistent reference ID so a finding can
  point back to the exact SolidWorks entity for screenshots, navigation, and drawing
  notes. Persistent references are emitted from day one; retrofitting them is prohibited
  as a plan.
- The IR schema MUST be versioned. Consumers MUST reject an IR whose major version they
  do not support.
- Exported geometry (STEP, meshes) is supplementary evidence only. It MUST NOT be the
  source of thread, fastener, mate, or tolerance data when native data exists.

Rationale: information lost at export becomes a geometry-recognition research project.

### V. Engineered Enough

Code is neither fragile nor speculative.

- DRY is enforced aggressively: repeated logic across checks, parsers, or scripts MUST be
  extracted once it appears twice with the same intent.
- Explicit beats clever. No abstraction for single-use code, no configurability that
  was not asked for, no error handling for impossible scenarios.
- Handle more edge cases rather than fewer; thoughtfulness over speed. Edge cases MUST
  be named in the spec or plan, not discovered in production.
- Changes are surgical: touch only what the task requires, match existing style, and
  remove only the orphans your own change created.
- Success criteria are stated before coding ("write tests for invalid inputs, then make
  them pass"), so a task can be verified without asking.

Rationale: the CLAUDE.md preferences of the project owner; a mechanical engineer owns
this codebase and must be able to read every line.

### VI. Findings Are Inspectable and Coverage Is Tracked

The review report is the product. It MUST let an engineer reproduce any finding.

- Each finding lists the components or drawing location, source inputs, assumptions,
  reasoning, recommended next action, and the engineer's eventual disposition.
- The report MUST record what was checked, skipped, unresolved, or out of scope.
  Checking selected positions of a mechanism does NOT establish clearance across its
  motion path and MUST be reported as such.
- Intentional interference exceptions MUST be bound to the reviewed geometry and
  configuration. Blanket exclusions that could hide defects are prohibited.
- Requiring every modeling dimension to appear on a drawing is NOT a valid completeness
  test; drawing checks target meaningful manufacturing requirements.
- Net time saved and review quality (valid findings, missed known defects, false alarms,
  unresolved coverage) MUST be measured per design, not only on the best example.

Rationale: the pilot's success criterion is at least 60 minutes of net engineering effort
saved per design without degrading review quality.

## Technical Constraints

- **CAD environment**: SOLIDWORKS 2024 with EPDM is the production workstation named in
  the pilot README. The architecture proposal (ADR-001) references SOLIDWORKS 2026
  features (Auto-Generate Drawing, fastener recognition); any dependency on a 2026
  feature MUST be confirmed available on the pilot workstation before it enters a plan.
- **SolidWorks-side code** runs on Windows. In-process C# add-in code is preferred for
  fine-grained traversal (10 to 100x faster than out-of-process COM). Out-of-process
  calls (Python plus pywin32, MCP servers) MUST be coarse (one call, one large operation)
  and MUST marshal every COM call onto a single STA thread.

- **Documents are read, not written.** The reviewer, every check, every tool exposed to a
  model, and every add-in command MUST treat every document SOLIDWORKS has open as read-only.
  `ReadOnlyGuard` is the enforcement point, and its denylist grows the moment a phase touches
  an API family that can write. There are exactly two exceptions, both bounded below; a third
  requires an amendment to this file.

  1. **The suppressibility test** (feature 003): console-only, behind an explicit flag, driven
     by a reviewer-written plan, under a guard that exempts exactly `IFeature.SetSuppression2`
     and `IModelDoc2.ForceRebuild3`, over a saved and not-rolled-back document with no
     pre-existing rebuild errors, with a whole-tree snapshot and a verified restore. It never
     saves.

  2. **The re-modeler** (feature 004): the re-modeler MAY create and modify exactly one
     document, a copy it created during this session, and no other.
     - The copy is made by a filesystem copy that refuses to overwrite, into the run folder,
       before any SOLIDWORKS document handle exists. The engineer's file is never opened for
       writing, never saved, never renamed and never deleted. The run records the source file's
       size, last-write time and content hash before it starts and re-checks all three before
       it reports; a difference is a hard failure of the run.
     - **The re-modeler MUST NOT save over a file that already existed.** Only
       `IModelDoc2.Save3` is permitted, which takes no filename and therefore writes only to
       the copy's own path, and only after the geometry comparison has passed. `SaveAs3` to any
       path, and any write to any document that is not this run's copy, are refused by the
       guard, not by convention.
     - Writes go through a document-scoped guard that (a) **allowlists** the specific
       interface-qualified interop members the run needs and refuses every other write, and
       (b) re-verifies the target document's path, its session tag, and its COM identity
       immediately before each write. No command in the bridge protocol, and no tool exposed to
       the language model, names a document.
     - Every applied change is recorded with its before state, its after state, and the inverse
       operation that undoes it. A change that raises the rebuild-error count above the run's
       baseline is undone and recorded as undone. The run is bounded by a change count and a
       wall-clock limit, and a truncated run says so.
     - The language model does not perform the mutation. It proposes intent (descriptions,
       global-variable names, and the judgement calls the modeling method itself says to ask
       about) into a plan; a deterministic executor applies the plan. Where a stage genuinely
       requires generative modeling, the model's tools are the same guarded, document-scoped
       commands, and each change is created, verified and rolled back individually.
     - Geometric equivalence is reported as `pass`, `fail` or `unresolved`, never as a Boolean,
       and never inferred from a successful rebuild.

  A mutation exception is not an engineering result. A copy that rebuilds cleanly, has the same
  volume, and grades better against the Resilient Modeling Strategy is a **proposal** the
  engineer accepts or discards; Principle I applies to it unchanged.

- **Reasoning-side code** is Python 3.11+ with a typed, versioned IR (pydantic). It MUST
  run without a SolidWorks license so reviews can run in parallel on cheap machines and
  in CI.
- **Third-party reuse** MUST respect each repository's license. SwpilotCLI's custom
  license permits internal organizational use only; GPL-3.0 code (CADAM) MUST NOT be
  linked into distributed components without a license decision.
- **Scope boundary of the pilot**: the pilot produces review findings. Autonomous GD&T
  creation, general drawing dimensioning, and structural approval are out of scope and
  require separate specification and validation.
- **Generic code execution tools** (for example an `execute_python` tool with
  application and OS access) MUST NOT be exposed to the agent. Expose a curated set of
  inspection operations and validate new tool code on benchmark copies before admitting
  it to the reusable tool set.

## Development Workflow

- Work follows the Spec Kit cycle: constitution → specify → plan → tasks → implement →
  converge. A spec describes WHAT and WHY; the plan decides HOW.
- Review gates: the spec is reviewed before planning; the plan is reviewed before task
  generation. Each user story is independently testable and delivered as an increment.
- Before implementing, the engineer states assumptions explicitly, presents multiple
  interpretations when they exist, and asks when something is unclear rather than picking
  silently.
- Every pull request or review MUST verify compliance with Principles I through VI.
  A Constitution Check in the plan lists each gate and how it is met.
- Complexity beyond what a senior engineer would call necessary MUST be justified in the
  plan's Complexity Tracking table with the simpler alternative and why it was rejected.
- Benchmark packages (5 to 10 representative designs with known defects and correct
  designs, answer key withheld from the agent) are the acceptance suite. Some packages
  are held out for evaluation only.

## Governance

This constitution supersedes all other practices in this repository. CLAUDE.md remains
the runtime guidance for day-to-day agent behavior and MUST stay consistent with it.

- **Amendments**: propose the change with rationale, update this file, bump the version,
  record the change in the Sync Impact Report comment, and note any migration needed for
  existing specs, plans, or tasks.
- **Versioning**: semantic. MAJOR for removing or redefining a principle; MINOR for a new
  principle or section or materially expanded guidance; PATCH for clarifications and
  wording.
- **Compliance review**: every spec, plan, and task list is checked against this file at
  creation and at each review gate. Violations are either fixed or justified in the
  plan's Complexity Tracking table.

**Version**: 1.1.0 | **Ratified**: 2026-09-12 | **Last Amended**: 2026-09-16
