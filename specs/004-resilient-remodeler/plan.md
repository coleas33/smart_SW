# Implementation Plan: Resilient Re-modeler

**Branch**: `004-resilient-remodeler` | **Date**: 2026-09-16 (revision 1) | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-resilient-remodeler/spec.md`

## Summary

Given one part, produce a **copy** that grades better against the Resilient Modeling Strategy
with its geometry proven unchanged, and make the unfixable part of the problem legible.

The copy is made by a filesystem copy into the run folder before any SOLIDWORKS document handle
exists, so the engineer's file is never opened for writing. v1 ships **stage 1 only**:
reorganize (duplicate-name repair, descriptions, reorder into the RMS-closest legal order, the
six group folders, global variables) with the geometry proven unchanged at the `IDENTITY`
tolerance profile. **Stage 2 (rebuild what blocks the rules) is out of scope for v1** and is
re-specified after stage 1 has run on real parts; the geometry gate ships with its tri-state
`GateResult` and its tolerance-profile seam from day one so stage 2 adds a tier rather than
changing a type.

The work splits three ways and the split is the design. A **pure Python planner** decides every
order, move, folder and refusal from the IR, with no SOLIDWORKS and no model in it. A **bounded
LLM phase** proposes description text, global-variable names and the two judgement calls the
modeling method itself says to ask about, into the plan, and never mutates anything. A
**deterministic C# executor path** applies the plan through an allowlisting, document-scoped
guard, one change at a time, each with a recorded inverse.

Feature 003 US6 is a hard prerequisite: a part opened alone currently dumps zero features
(`ComponentTreeDumper.Traverse` takes the tree from `IConfiguration.GetRootComponent3(false)`),
and the re-modeler's entire subject is a part opened alone. 004 consumes 003's part-root node,
`DumpProfile.ModelCheck`, `checks/rms/run.py::run_rms_check`, `checks/rms/grade.py::RmsGrade`,
`AddIn/Review/PaneActions.cs`, `AddIn/Review/FeatureSelection.cs` and `AddIn/web/shared/dom.js`
rather than re-creating any of them.

Every interop member named in this plan and in `contracts/` is marked VERIFIED or UNVERIFIED.
VERIFIED means exactly this: the member exists with that signature, or the enum constant has
that integer value, on SOLIDWORKS 2024 SP5 interop `32.5.0.48`, confirmed by reflection on the
pilot machine. It never means the call behaves. UNVERIFIED means behavior that needs the
workstation, and every UNVERIFIED item that gates a decision is a numbered probe in
[research.md](research.md).

## Technical Context

**Language/Version**: C# on .NET Framework 4.8 x64 (guard, document scope, bridge commands,
add-in pane host, console probe); Python 3.11+ (planner, executor, geometry verdict, tools,
CLI); JavaScript with no framework (the Remodel page).

**Primary Dependencies**: **No new packages on either side.** C#: existing interop, `SwGate`
and the `ICallGuard` seam feature 003 adds, `ReadOnlyGuard` (read unchanged, delegated to),
`CircuitBreaker`, `BridgeProtocol` and `BridgeDispatcher`, `ScopedSecretPolicy` (one new scope),
`ToolServiceHost`, `RunFolders`, `SwReviewDump` with 003's `DumpProfile.ModelCheck`,
`PaneActions`, `FeatureSelection`, `SwEntityResolver`, and `TaskPaneControl`'s shared
`CoreWebView2Environment`. Python: existing `ir/models.py` (IR 1.2.0 read, no new field),
`checks/rms_types.py` and `checks/rms_types.yaml` (one new key, `default_group_by_class`),
`checks/rms/run.py`, `checks/rms/grade.py`, `tools/registry.py` (one new `Registration`),
`tools/recording.py`, `tools/context.py`, `bridge/client.py` (subclassed, not forked),
`agent/providers` (OpenAI and Gemini only), `exceptions.py`, `pydantic`, `pyyaml`, `typer`.

**Storage**: Files only, all under one run folder per run:
`copy/<doc>-RMS.SLDPRT`, `plan.json`, `changes.jsonl`, `package-before.json`,
`package-after.json`, `rms-before.json`, `rms-after.json`, `grades.json`, `geometry.json`,
`source-attestation.json`, `exceptions.json` (carried forward), `report.md`, `events.jsonl`,
`session.json`, `remodel.log`. Schemas in [contracts/run-artifacts.md](contracts/run-artifacts.md).

**Testing**: pytest over builder fixtures for every planner module, the executor against a fake
bridge that scripts a failure at change N, the geometry verdict as a table test, the tools
against a `FakeProvider` including one that proposes garbage; xUnit for `RemodelGuard`'s
allow and deny table, `RemodelScope.VerifyTarget` over an `IRemodelTarget` fake, `AssertSaveTarget`,
the option-composition integers, the bridge command dispatch, and the two interop-manifest tests;
host-message tests for `RemodelHost` mirroring `ReviewHostTests`; page contract and injection
tests; four golden plans plus one fixture per refusal category. Workstation probes per
[quickstart.md](quickstart.md).

**Target Platform**: as features 001, 002 and 003. SOLIDWORKS 2024 SP5 with EPDM on the pilot
workstation; the Python side runs with no SOLIDWORKS licence and in CI.

**Project Type**: extends both trees and adds a fifth pane tab.

**Performance Goals**: the planner evaluates a 1000-feature package in under 2 s with no seat
(marked perf test); the ModelCheck dump of the copy inherits 003's budget (under 2 s for a
150-feature part, PROBE-14); a stage-1 run is bounded, not optimized, by `max_changes` 250,
`max_minutes` 20 wall clock and `max_rebuild_seconds` 120 per rebuild.

**Constraints**: the re-modeler writes to exactly one document, a copy it created in this run's
folder, and the guard refuses every other write; `SaveAs*` to any path is refused, only
`Save3` (no filename) is permitted, and only after the geometry gate passes; the reviewer and
the Model check tab stay read-only and gain no exception; parts only, single solid body; stage 2
does not ship; dimensions are not in the IR in v1, so globals are named, repaired and added only
where feature data justifies them; providers are OpenAI (default) and Gemini through the existing
provider layer, never Claude; goldens of 001, 002 and 003 stay byte-identical; the feature 001
finding contract is unchanged; no code is copied from the source checker repository.

**Scale/Scope**: parts to 1000 features, one solid body, configuration count recorded and carried
on every equation write. Assemblies, drawings, multibody, sheet metal, weldments, mesh and
graphics bodies, 3D Interconnect and in-context references are refused before anything is copied.

## Constitution Check

| Principle | Gate | How this plan meets it | Status |
|-----------|------|------------------------|--------|
| I. Evidence before conclusions | Unknown stays unknown | A feature whose type is not in `rms_types.yaml` is `unclassified` on the rebuild list, never "movable"; a feature whose `child_ids` and `parent_ids` are both null is `graph_unreadable` and is never moved; a fillet with `default_radius is None` is `radius_unreadable`, never given an arbitrary position; a description read as `None` (unreadable) is refused up front rather than overwritten as if it were `""`; the geometry gate returns `unresolved` and never infers a pass from a clean rebuild; a run that hits a limit reports `truncated` with the applied and unapplied counts, never a silent partial success | PASS |
| II. Deterministic numerics | No LLM judgement in verdicts | The model's whole surface is four `propose_*` tools plus one read-back, all of which write to the plan and none of which name a document, a move, an order, a rollback or a verdict (`contracts/tools.md`); the planner, the executor, the limits and the gate are pure functions and deterministic code; stage 1's apply loop runs with no model in it | PASS |
| III. Test-first with goldens | Tests precede code | Every planner module has its test task before its implementation task; four golden plans and one fixture per refusal category; the geometry gate's full case table (identical, inside and outside tolerance, mirrored, translated, scaled, one sliver, many slivers, null bounding box, each boolean error code, mass-properties status not OK, zero-volume baseline reading) is written before `evaluate`; the executor's rollback paths are tested against a fake bridge scripted to fail at change N; 001, 002 and 003 goldens untouched | PASS |
| IV. Semantic fidelity | Persistent refs, versioned IR | Every change is addressed by persistent reference and never by name or index, because names change and indices change on every reorder; `GetObjectByPersistReference3`'s ByRef error code is read on every resolve; the IR is read at 1.2.0 and gains no field; `plan.json` and `changes.jsonl` carry `plan_schema` and are versioned with the feature | PASS |
| V. Engineered enough | No speculative abstraction | `EventSink` is **extracted** from `agent/runner.py` into `agent/events.py` and shared rather than copied; the pane delegates `entity.show`, `report.open`, `folder.open` and `log.open` to 003's `PaneActions` and loads 003's `web/shared/dom.js`; `run_rms_check` and `RmsGrade` come from 003; `RunFolders` names the folder; `bridge/remodel_client.py` subclasses the existing client rather than forking the transport; `ReviewRun` is **not** reused because it is review-shaped (checklist, findings, evidence requests, coverage buckets, finalization) and none of it fits a remodel run; one verified equation helper, one selection assertion, one undo derivation, each with one call path | PASS |
| VI. Inspectable findings, coverage tracked | Every run ends in evidence | Every attempted change is two `changes.jsonl` lines (before and after the call) so a crash mid-change names what was in flight; the report states the change list, the before and after grade with its unresolved rule ids, the geometry comparison **and what tier 1 cannot detect**; every feature that could not be reorganized is named with a reason from a closed taxonomy and its blocking dependency edge; Discard keeps every artifact except the `.SLDPRT`, so "what did it propose" stays answerable after the engineer says no | PASS |
| Technical constraints: documents are read, not written | No mutation outside a written exception | Constitution 1.1.0, Technical Constraints, **"Documents are read, not written", exception 2 (the re-modeler)** is the governing text, and this feature is bounded by it clause for clause: the copy is a filesystem copy that refuses to overwrite, made before any document handle exists; source size, last-write time and content hash are recorded before the run and re-checked before the report, and a difference is a hard failure; only `Save3` is permitted and only after the gate passes; writes go through an interface-qualified allowlist plus a target re-verified immediately before every write; no bridge command and no model-facing tool names a document; every applied change carries its inverse; the run is bounded and a truncated run says so; the model proposes intent and a deterministic executor applies it; equivalence is `pass`, `fail` or `unresolved` | **PASS via the amendment** (Complexity Tracking) |
| Technical constraints: read-only reviewer and Model check | The exception does not spread | 004 adds nothing to `ReadOnlyGuard`; `RemodelGuard` delegates to it unchanged for everything off the allowlist; the reviewer's existing `SwGate.Call("GetChildren", ...)` call sites keep bare-name keys and are untouched; the Model check tab (003 US6) registers no tool and no mutation and is explicitly outside this exception | PASS |
| Technical constraints: 2026 dependencies confirmed on the workstation before entering a plan | Nothing here depends on a 2026-only feature | Every member and enum value is VERIFIED present on the 2024 SP5 interop by reflection; **behavior is not verified**, and the blocking unknowns (whether `ReorderFeature` moves and refuses cleanly, whether folders need contiguous members, what unit an equation number is in, whether the custom-property tag round-trips, what tolerance the mass-property engine attains, whether `CommandInProgress` suppresses the modal) are gated by Phase 2's probe before any write code is trusted, and the tolerance profiles do not ship until PROBE-8 has compared them against a part of exactly known analytic volume | **PASS with a documented risk** (RK-1, RK-2, RK-3, RK-8, and the calibration gate on PROBE-8) |
| Technical constraints: third-party reuse respects licenses | Source repository is unlicensed | The RMS semantics this feature plans against are feature 003's, reused by the author's permission dated 2026-09-15 and recorded in NOTICE; no code is copied, semantics only; 004 adds no third-party dependency and vendors nothing | PASS |
| Technical constraints: no generic code execution tools | The model's surface stays curated | The four `propose_*` tools and `get_remodel_plan` are the whole model-facing surface; they validate their arguments before writing to the plan, and a rejected proposal returns `{"error": ...}` through the existing `RecordedTool.call` error-result path; the remodel bridge secret authorizes `ping` and `remodel.*` and nothing else, and the general-chat secret authorizes no `remodel.*` command at all | PASS |
| Technical constraints: reasoning side runs without a licence | Python testable in CI | The planner, the executor's decision logic, the geometry verdict, the plan and change schemas, the tool validation and the agent loop are all pure or filesystem-only and run with no seat; only the probe (Phase 2) and bring-up (Phase 9) need SOLIDWORKS | PASS |

Post-design re-check: one written constitution exception (the whole feature operates under it),
one documented risk family gated by Phase 2 and PROBE-8, four Complexity Tracking rows.

## Project Structure

### Documentation (this feature)

```text
specs/004-resilient-remodeler/
├── plan.md, spec.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, bridge-remodel.md, tools.md, pane-remodel-messages.md,
│              run-artifacts.md, guard-allowlist.md, interop-manifest.md}
└── checklists/requirements.md
```

### Source Code (repository root)

```text
reviewer/src/swreview/
├── remodel/__init__.py
├── remodel/target.py          # row -> Resolved | NeedsJudgement | NotContent; reads default_group_by_class
├── remodel/rank.py            # (group_index, intra_rank, original_index) from the rules part.py grades
├── remodel/order.py           # Kahn with a rank-keyed priority queue, then LIS -> minimal edit script
├── remodel/feasibility.py     # pins, non-contiguous groups, the rebuild list with one reason each
├── remodel/folders.py         # create and rename plan; a correct folder is a no-op; a mis-membered
│                              #   RMS-named folder is a refusal in v1 (there is no dissolve path)
├── remodel/intent.py          # description gaps (None unreadable is not "" absent); equation inventory
├── remodel/names.py           # duplicate feature names: detection and the rename plan
├── remodel/scope.py           # ScopeGate.evaluate(signals) -> Ok | Refusal(reasons[]); no COM
├── remodel/geometry.py        # evaluate(before, after, tolerances) -> GateResult; no COM; IDENTITY/EQUIVALENCE
├── remodel/plan.py            # RemodelPlan (pydantic, plan_schema 1.0); plan_reorganize()
├── remodel/apply_log.py       # ChangeRecord + derive_undo(change), one pure inverse per kind
├── remodel/apply.py           # the deterministic executor: change -> bridge -> rebuild -> verify -> inverse
├── remodel/runner.py          # phases A to D; the one provider entry point (delegates to
│                              #   cli.provider_factory: owner decision 4A, 2026-09-23)
├── remodel/report.py          # report.md, grades.json, geometry.json, source-attestation.json
├── tools/remodel_plan.py      # propose_description, propose_global, decide_fillet, classify_unknown,
│                              #   get_remodel_plan; registered only when ToolContext.remodel is set
├── tools/registry.py          # + one Registration, conditional exactly as bridge_tools() is
├── bridge/remodel_client.py   # RemodelClient(BridgeClient): the remodel.* vocabulary and its errors
├── agent/events.py            # EventSink EXTRACTED from agent/runner.py, shared with the review run
├── agent/prompts/remodel_v1.md
├── checks/rms_types.yaml      # + default_group_by_class (one new key, so the checker and the planner
│                              #   cannot disagree about what "should" means)
└── cli.py                     # + remodel plan <package.json> --json, remodel report <run_dir>

extractor/SwReview.Extractor/
├── Guard/RemodelGuard.cs      # ICallGuard; interface-qualified ALLOWLIST; delegates to ReadOnlyGuard
├── Rms/RemodelScope.cs        # the only object holding the copy's IModelDoc2; VerifyTarget before
│                              #   every write; AssertSaveTarget; AssertFolderSelection (refusal helper)
├── Rms/RemodelScopeProbe.cs   # remodel.probe_scope: reads the scope signals off the engineer's
│                              #   already-open source, read members only, returns no IModelDoc2,
│                              #   so FR-001's refusal lands before any copy exists
├── Rms/IRemodelTarget.cs      # the fake seam the scope tests drive
├── Rms/RemodelTargetError.cs
├── Rms/RemodelCopy.cs         # File.Copy with overwrite:false, FileShare.ReadWrite stream fallback,
│                              #   tag write and read-back, source attestation
├── Rms/GeometryReading.cs     # the plain record remodel.geometry returns
├── Bridge/BridgeProtocol.cs   # + the remodel.* commands (contracts/bridge-remodel.md)
├── Bridge/BridgeDispatcher.cs # + remodel dispatch behind the remodel scope of the secret policy
└── Bridge/SecretPolicy.cs     # ScopedSecretPolicy gains the remodel scope: ping | remodel.* only
extractor/SwReview.Extractor.Console/Program.cs   # probe remodel (PROBE-1..7, 10, 12, 13, 20 and
                                                  #   PROBE-8's tolerance calibration)
extractor/SwReview.Extractor.Tests/Fixtures/InteropSurface/remodel-interop-manifest.json

extractor/SwReview.AddIn/
├── Remodel/RemodelHost.cs     # ready + remodel.*; everything else delegates to 003's PaneActions
├── Remodel/RemodelRun.cs      # one run per host; the stop flag; the run folder
├── Remodel/RemodelPage/{index.html, remodel.js, remodel.css}
├── ToolService/ToolServiceHost.cs  # + RemodelSecret, handed only to the remodel backend session
└── TaskPaneControl.cs         # the fifth TabPage, WebView created LAZILY on first activation
```

**Structure Decision**: the same split feature 003 chose, one step further. C# stays a recorder
and an applier: it resolves a persistent reference, reads a name, makes one guarded call and
reports what happened. Every decision about what should move, where it should go, whether a
group is contiguous, what cannot be fixed, and whether the geometry is unchanged is Python data
plus pure functions with no COM in any signature, so recalibrating for 2024 touches YAML, a
tolerance ledger and tests rather than C#. The model sits beside that pipeline, never inside it.

## Phase 0 and Phase 1

Research in [research.md](research.md); design in [data-model.md](data-model.md) and
[contracts/](contracts/). Key points tasks must honor:

1. **Persistent-reference addressing everywhere.** No `remodel.*` command, no `ChangeRecord` and
   no plan entry addresses a feature by name or by index. The C# side resolves a persist ref to
   an `IFeature` through `IModelDocExtension.GetObjectByPersistReference3(Object, Int32&)`
   (VERIFIED, ByRef error code read on every resolve), reads `IFeature.get_Name` (VERIFIED), and
   only then calls the name-based API, in one breath. A ref that stops resolving after a change
   is a failed change recorded as "could not be addressed after change N", never a silent skip.

2. **No document parameter anywhere.** No bridge command, no tool argument and no pane message
   names a document. `RemodelScope` holds the only `IModelDoc2` the run can reach, so the target
   is not validated, it is unreachable. This is stronger than checking a path the caller supplied
   and it is the property the Constitution Check's exception rests on.

3. **One verified equation helper, never inlined.** `AddEquationVerified(text, whichConfigs)`
   calls `IEquationMgr.Add3` (VERIFIED), asserts `GetCount()` incremented **and**
   `get_Equation(i)` round-trips, falls back to `Add2` (VERIFIED) and asserts again, and fails
   the change on a second failure. Upstream observed `Add3` returning `-1` and adding nothing,
   silently, on 2026 (PROBE-6), so the assertion is the only evidence the add happened and it
   exists in exactly one place. A global is created by equation **syntax** (`"name" = expr`, a
   quoted left-hand side with no `@`): `IEquationMgr.set_GlobalVariable` is a VERIFIED ABSENCE,
   so no design may assume a flag.

4. **Never delete a global in order to change it, and there is no dimension step.** The apply
   order is fixed: duplicate feature names, then descriptions, then reorders, then folders, then
   in-place global repairs, then new globals (data-model.md section 1.11, C1 to C6). Repairing a
   global is its own change kind, `equation.edit`, carried by `remodel.equation` with
   `op: "set"`: prefer `set_Equation(i, text)` (VERIFIED), then
   `SetEquationAndConfigurationOption` (VERIFIED), and **never** fall back to delete-and-re-add,
   because while a referenced global is missing the dependent equations enter an error state that
   does not clear when it returns. If neither member can be proven to have written, the change
   fails and is inverted. The brief's dimension-rename step and dimension-equation step are both
   out: FR-030 forbids driving a dimension the planner never saw, the IR carries no dimensions in
   v1, and `IDimension.set_Name` is therefore off the stage-1 allowlist. The rename-before-
   equations ordering rule is preserved in research.md R3.5 for the later dimensions feature and
   is implemented by nothing here.

5. **The units sequence is normative.** The number in an equation text is in the **document's**
   length unit, not metres, which is the exact opposite of every length the IR carries. Getting it
   backwards builds a 120-metre part that rebuilds cleanly and passes every non-geometric check.
   Per global: read the justifying value from the package's feature data (metres); convert it to
   the document's length unit and seed the global's literal with that exact value; add the global
   through `AddEquationVerified` and assert it landed and evaluated; `ForceRebuild3(false)`,
   re-read the equation and assert the text and value round-trip at the document's stored
   precision, not at a loose epsilon; compare the geometry snapshot against the pre-change one,
   which must be identical because a global that drives nothing cannot move geometry. A document
   whose length unit cannot be read refuses the change instead of assuming metres. Whether
   `EquationMgr.get_Value(i)` returns document units or metres is **UNVERIFIED** and blocking
   (PROBE-2). One pure regression test: a 120 mm value never produces `"w" = 0.12`.

6. **Limits are the executor's, never the model's.** `max_changes` 250, `max_minutes` 20 wall
   clock, `max_rebuild_seconds` 120. Hitting one is `truncated`: stop, finalize, and report how
   many planned changes were applied and which were not.

7. **The frozen interop-surface manifest** ships with the guard, not after it. A checked-in JSON
   fixture of `{interface, member, arity, ordered parameter names, return type}` for every member
   the re-modeler calls, with two tests: pure (the code's argument builders match the fixture)
   and workstation-only (regenerate from the installed DLL and diff, skipped when the interop
   assembly is absent). See [contracts/interop-manifest.md](contracts/interop-manifest.md). This
   turns a SOLIDWORKS upgrade from a runtime surprise into a red build.

8. **`EventSink` is extracted, not copied.** The sink that stamps `seq` and `at`, appends to
   `events.jsonl` and fans out is currently private to the review run; it moves to
   `agent/events.py` and both runs use it, with the review run's tests green and unedited as the
   regression proof. The per-turn step budget, `TurnEndReason` handling, `build_system_prompt`
   and the redactor hand-off (`no_redaction`) are shared the same way.

9. **Do not reuse `ReviewRun`.** `agent/runner.py` is review-shaped (checklist, findings,
   evidence requests, coverage buckets, finalization) and none of it fits a remodel run.
   `remodel/runner.py` is its own loop over the shared pieces in point 8.

10. **The planner is Phase 0's deliverable and runs before any C# write code exists.**
    `swreview remodel plan <package.json> --json` prints, per part, how many features reach their
    target group, how many are pinned and by which dependency edge, how many groups come out
    non-contiguous, and the rebuild list with a reason each. It is run over the benchmark
    packages and 3 to 5 real parts, and the numbers decide how much of stage 1 is worth building.
    Stage 1's stated output is **a partition with reasons**, and success is measured on the
    quality of the partition, not on the size of the reorganized fraction.

11. **Duplicate feature names are a precondition, not a surprise.** `ReorderFeature` is
    name-addressed (`String FeatureToMove, String TargetFeature`, VERIFIED), and SOLIDWORKS
    permits two features in different folders to share a name, in which case the call is
    ambiguous and there is no error code to say so. The planner asserts name uniqueness across
    the whole tree; a duplicate is either renamed first, as a recorded reversible change applied
    before any reorder, or both features go on the rebuild list as `ambiguous_name`.

12. **An illegal reorder is never attempted.** `ReorderFeature` returns a bare `false` with no
    code and no reason, and a refusal can raise a modal box on the add-in's STA thread, which is
    a hang rather than an error. Legality is decided from the dependency graph in `order.py`
    before the call. A `false` return is therefore a **contract violation**: log it, discard the
    copy, stop the run. Never retry, never search.

13. **Refusals are reported coverage, never silent skips.** The scope gate refuses multibody,
    weldment, sheet metal, mesh and graphics bodies, and 3D Interconnect before anything is
    copied; a part whose tree already carries an RMS-named folder holding the wrong members is
    refused in v1, because `IModelDoc2.EditDelete` is deliberately not on the stage-1 allowlist;
    an imported dumb solid is allowed, with the reorganize stage reported as a no-op; surface
    bodies are allowed, with the gate's surface coverage reported as **uncovered**, never as
    passed.

14. **Fillet judgement defaults to safety and is always listed.** A fillet the method calls
    ambiguous defaults to `3-Core` (Core never violates `rms.quarantine.has_no_children`) and
    every one of them appears in the report as "reviewed as structural; move to Quarantine if
    cosmetic". The run is never blocked on an evidence request, because the run is
    non-interactive by design.

15. **Exceptions are copied forward, not centralized.** Before the plan is written, the newest
    `exceptions.json` under `run_root` whose run resolves to the same **source** `design_id` is
    copied into this run folder, byte-identical, so the before and after grades are measured
    against the same waivers the engineer already granted. The match is on the source's id, never
    on this run's: `DocumentIds.DesignId` is path-derived and this run's packages are dumps of the
    copy, so a `-check` candidate is matched through `package.json`'s `design.design_id` and a
    prior `-remodel` candidate through `source-attestation.json`'s `source_design_id`. The carried
    exceptions are rebound to the copy's `document_id` and fingerprint-refreshed once, against
    `package-before.json`, with that store applied unchanged to both grades
    (`contracts/run-artifacts.md`). A different source `design_id` is not copied, no candidate is
    not an error, and an unreadable candidate is a refusal rather than a silent empty store.
    There is no per-design store in v1.

## Delivery order

Cannot start before feature 003 US6 sub-phases 9a (the part-root node and
`DumpProfile.ModelCheck`) and 9b (`run_rms_check` and `RmsGrade`) land.

| Phase | Deliverable | Needs SOLIDWORKS | Fully fakeable |
|-------|-------------|------------------|----------------|
| **0. Decide** | Run the Phase 1 planner over the benchmark packages and 3 to 5 real parts; publish the per-part partition numbers; decide from them how much of stage 1 to build | No | n/a |
| **1. Planner** | `remodel/{target,rank,order,feasibility,folders,intent,names,scope,geometry,plan}.py`, `default_group_by_class` in `rms_types.yaml`, `swreview remodel plan --json`, four golden plans and one fixture per refusal category | No | Yes |
| **2. Probe** | `swreview-extract probe remodel` over a throwaway part the probe builds itself: PROBE-1, 2, 3, 4, 5, 6, 7, 10, 12, 13, 20, plus **PROBE-8**, the tolerance calibration on a box and a cylinder of exactly known analytic volume | **Yes** | n/a |
| **3. Guard and scope** | `RemodelGuard` (interface-qualified allowlist), `RemodelScope` with `VerifyTarget`, `IRemodelTarget`, `AssertSaveTarget`, `AssertFolderSelection` (built and tested now as a pure refusal predicate; its only write-precondition call site arrives in stage 2), `RemodelCopy` (copy, tag, attestation), `RemodelTargetError`, the frozen interop manifest and its two tests | No | Yes, over fakes |
| **4. Bridge and host** | the `remodel.*` commands in `BridgeProtocol` and `BridgeDispatcher`, the third secret in `ToolServiceHost` and `ScopedSecretPolicy`, `remodel.log` with the target path per mutating call, `bridge/remodel_client.py` | No | Yes, over fakes |
| **5. Executor and artifacts** | `remodel/apply.py`, `apply_log.py`, `changes.jsonl`, `grades.json`, `source-attestation.json`, `report.md`, the three limits, the per-change inverse, the catastrophic replay fallback | No | Yes, fake bridge scripting a failure at change N |
| **6. Geometry gate** | `remodel.geometry` in C#, `remodel/geometry.py::evaluate`, the `IDENTITY` and `EQUIVALENCE` profiles, the full case table | No, readings come from fakes | Yes |
| **7. LLM phase** | `tools/remodel_plan.py` and the four `propose_*` tools with their validation, `remodel/runner.py`, prompt `remodel_v1.md`, `EventSink` extracted to `agent/events.py` | No | Yes, `FakeProvider` including one that proposes garbage |
| **8. Pane** | `RemodelPage/`, the fifth `TabPage` with lazy WebView creation, the host messages, `remodel.show_change` through 003's `FeatureSelection` | Manual verification only | Host-message and page tests yes |
| **9. Workstation bring-up** | Stage 1 end to end on a real part; calibrate `default_group_by_class` and the type table against what 2024 returns; record in NOTICE, quickstart and the native benchmark notes | **Yes** | n/a |

**Stage 2 (rebuild) is out of scope for v1.** It is re-specified as its own feature after stage 1
has run on real parts, with those numbers in hand. Three seams exist now so that stage 2 adds a
tier rather than changing a type: `GateResult` is tri-state (`pass`, `fail`, `unresolved`) from
day one; the tolerance profiles are named records consumed by one pure function, so `EQUIVALENCE`
is selected rather than written; and the allowlist is a closed set that stage 2 extends with a
**second additive list, reviewed on its own**, rather than by widening stage 1's.

## Risks and mitigations

| # | Risk | Mitigation | Residual |
|---|------|------------|----------|
| RK-1 | **`ReorderFeature` cannot move past a dependency, so stage 1 changes almost nothing on a real part.** The highest-risk unknown in the feature; nothing upstream exercised it, because the source method builds in order instead | Phase 0 runs the planner as a pure dry-run over the benchmark packages and real parts **before any C# write code exists**; stage 1's stated output is a partition with reasons, and a run that moves 3 of 200 features says "this part needs rebuilding" in the report's first line rather than "success" | The owner may conclude stage 1 is not worth building. That is what Phase 0 is for |
| RK-2 | A refused reorder raises a modal "Cannot reorder" box on the add-in's STA thread, which is a hang, not an error; the call returns a bare `false` with no code, no reason and no out-parameter | Legality is decided from the dependency graph before the call; a `false` return is a contract violation that stops the run, never a retry or a search; `ISldWorks.CommandInProgress = true` is set for the run (PROBE-1, blocking) | If PROBE-1 fails, stage 1 cannot run unattended and the feature stops at Phase 2 |
| RK-3 | Equation units inverted, producing a 120-metre part that rebuilds cleanly and passes every non-geometric check | The six-step units sequence (key point 5), the pure regression test, and PROBE-2 before any equation write ships | None once PROBE-2 answers |
| RK-4 | `EditDelete` on a mis-selection deletes real features | `IModelDoc2.EditDelete` is **not on the stage-1 allowlist**: a part carrying an RMS-named folder with the wrong members is refused in v1. `AssertFolderSelection` (selected count is 1 **and** `GetTypeName2() == "FtrFolder"`) is specified and tested now as the precondition any future dissolve must pass | A legacy part with mis-membered RMS folders cannot be re-modeled in v1; the refusal names the folder |
| RK-5 | Duplicate feature names make the name-addressed `ReorderFeature` ambiguous | The planner asserts tree-wide name uniqueness; duplicates are renamed first as recorded reversible changes, or go on the rebuild list as `ambiguous_name` | None |
| RK-6 | `GetWhatsWrong`'s out-array element type (names or `Feature` objects) is UNVERIFIED, and re-joining by name is fragile with duplicate names inside folders | The per-feature `IFeature.GetErrorCode2` walk is the **primary** error reading and the one the verify step gates on; `GetWhatsWrong` is corroborating only; PROBE-9 pins the shape | None |
| RK-7 | The `___EndTag___` folder marker keeps the folder's default name after a rename, so any code matching on the folder name is wrong | Match on the `___EndTag___` suffix and never on the name; already encoded as `end_tag_suffix` in `rms_types.yaml`; PROBE-10 confirms on 2024 | None |
| RK-8 | `GetTypeName2` strings were calibrated on 2026 (`ICE` covering both cuts and some bosses; `CommentsFolder`, `SelectionSetFolder` and `InkMarkupFolder` may not exist on 2024) | Feature 003's `probe rms --dump-types` against real parts, `calibrated_version` in `rms_types.yaml`, and an unknown type is `unclassified` on the rebuild list, never "movable" | The reorganizable fraction may shrink until Phase 9 calibrates |
| RK-9 | `File.Copy` fails because SOLIDWORKS holds the open `.SLDPRT` | Fall back to `new FileStream(src, Open, Read, FileShare.ReadWrite)` plus a stream copy, with the refuse-to-overwrite semantics preserved by creating the destination with `FileMode.CreateNew`; PROBE-13 | None |
| RK-10 | Two remodel runs at once | One run per host, refused with `error {error_class: "RunInProgress"}`, the shape `settings.save` already uses for `TurnRunning`; `ToolServiceGate` already enforces one tool service per add-in instance | None |
| RK-11 | Five tabs mean four WebView2 renderer processes, tens of MB each, inside the SOLIDWORKS process | The browser process and `CoreWebView2Environment` are already shared; the Remodel WebView is created **lazily on first tab activation**, not at add-in load; `WebViewFallbackTests` extended | Measure on the pilot workstation in Phase 9 |
| RK-12 | SOLIDWORKS dies mid-run | The existing `CircuitBreaker` trips after three consecutive failures into `circuit_open`; the copy and `changes.jsonl` survive on disk. **The run never auto-resumes**: a resumed run on a tree that was not re-verified is exactly the wrong risk, and a test asserts resume is refused | Manual recovery, documented in the quickstart |
| RK-13 | A persistent reference stops resolving after a reorder | The ByRef error code from `GetObjectByPersistReference3` is read on every resolve; an unresolved ref is a failed change recorded as "could not be addressed after change N", and the run stops with the log intact | None |
| RK-14 | The engineer edits or closes the copy mid-run | `VerifyTarget`'s four checks (path, session tag, COM identity, run-folder containment) run before every write; a changed feature count or an unresolvable ref aborts the change and the run with the log intact; a `document.changed` naming the copy aborts the run from the pane side | None |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| The re-modeler creates and modifies a document, against the Technical Constraints' read-only rule | The feature's whole product is a more resilient copy of a part, which cannot be produced without writing one document. Constitution 1.1.0 writes the rule down and bounds this exception: a copy created this session by a filesystem copy that refuses to overwrite, inside the run folder, before any document handle exists; only `Save3`, only after the gate passes; an allowlisting document-scoped guard; a target re-verified before every write; no document named anywhere in the protocol or in the model's tools; an inverse per change; a bounded run; tri-state equivalence | Proposing edits as a script the engineer runs by hand moves every one of the guard's guarantees onto the engineer and produces no geometry evidence at all. Writing into the engineer's file, even with an undo stack, cannot be made safe: `IModelDoc2.EditUndo2` returns **void** (VERIFIED), so there is no way to tell whether it did anything, and it shares the UI undo stack the engineer can also touch |
| A second guard (`RemodelGuard`, an allowlist) alongside `ReadOnlyGuard` (a denylist) | The reviewer's read surface is unbounded and grows every phase, so a denylist is right for it; the re-modeler's write surface is a closed set of about twenty members the spec enumerates, and a denylist's gaps are exactly what this workload finds (`ReadOnlyGuard` blocks `InsertFeatureTreeFolder2` through its `InsertFeature` prefix while leaving `FeatureFillet3`, `InsertMirrorFeature2`, `InsertPart3` and `IModelDoc2.Save` open). Keys are **interface-qualified** because the bare-name collisions are real: `ICustomPropertyManager.Delete2` is refused today by a rule meant for `IEntity.Delete2`, and an allowlist entry written as `"Add3"` would silently also permit `ICustomPropertyManager.Add3` | Widening `ReadOnlyGuard` with exceptions would put the write surface inside the artifact SC-004 audits as read-only, and would make every future denial a two-feature decision. A single guard parameterized by mode is the same thing with more indirection |
| A third bridge secret scope and a fifth pane tab | The remodel backend session must be able to call `remodel.*` and nothing else, and the general-chat secret must authorize no `remodel.*` at all; that is a scope, and `ScopedSecretPolicy` already exists to express one. The tab is the only place a run can be started, watched, and its copy opened or discarded | One secret for everything would give general chat the write surface. Driving the run from the CLI only would leave the engineer with no change list, no Show, and no Discard |
| A `remodel` package rather than extending `agent/runner.py` | A remodel run has no checklist, no findings, no evidence requests and no coverage buckets; it has a plan, a change log, a gate and a grade delta | Extending `ReviewRun` would make both runs carry the other's vocabulary. What is genuinely shared (`EventSink`, the step budget, `TurnEndReason`, `build_system_prompt`, the redactor hand-off) is **extracted** into `agent/events.py` and reused, which is the DRY answer that does not merge the two run shapes |
