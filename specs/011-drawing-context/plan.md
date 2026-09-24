# Implementation Plan: Drawing Context, Read Only

**Branch**: `011-drawing-context` (worked on `main`) | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/011-drawing-context/spec.md`, the owner's direction of
2026-09-22, and the Phase 0 reading and reflection pass in [research.md](research.md).

## Summary

Make drawings read-only evidence for reviews, in the order the next sitting needs them:

1. **The guard first** (Foundational): every writer of the 28 drawing families and the document
   activation, closing, creation, opening and macro members of the application refused, the
   membership generated from the 2024 SP5 interop and proved complete by a reflection test
   (research R2.2). Beside it: evidence schema 1.6.0 in both languages, drawing ids allocated per
   package, the drawing reader parameterised by document, and three synthetic fixtures.
2. **A drawing on its own** (US1): `AttachForDump` accepts a drawing with no configuration; the
   Standards tab grades a drawing live; every tool that needs a model still declines one.
3. **Open drawings attached** (US2): a review extraction discovers the drawings open in SOLIDWORKS
   whose views show the design, reads at most ten of them, records same-name drawing files beside
   reviewed documents as candidates, and opens nothing.
4. **Dimensions, precision and the resolver** (US3): each drawing dimension's text parts, written
   precision, unit, tolerance and attachments are read; profile version 3 names the unit the general
   tolerance's decimals are counted in; feature 010's drawing slot binds a subject through a usable
   view by attached face or by model dimension - **disabled until the seat validates it** - and hands
   the written precision to the general tolerance; the model's dimension and sheet tools read native
   sheets.
5. **Callouts, symbols, notes and tables** (US4): geometric tolerances, datums, surface finish, hole
   callouts and every table read onto the records feature 006 writes; a drawing's position tolerance
   feeds the stack-up.
6. **The drawing check and its questions** (US5): an argument-free check, offered and planned only
   when a package carries drawing evidence, records drawing coverage per document and raises at most
   four questions through the evidence-request writer the pane already shows. **Amended
   2026-09-23** (owner, research R5 Q2, R2.23): when the engineer confirms a candidate, the backend
   asks the add-in over the bridge (`drawing.read`, protocol 1.3, a document id and never a path);
   the add-in opens the drawing read-only and hidden through a guarded seam with its own allowlist,
   reads it into the run's package, and closes it when it opened it - shipped off until probe D14.
7. **The brief** (US6): a bounded, deterministic brief per part from feature 010's joint map,
   callouts and resolver, served on demand by a tool and a command.
8. **Conformance** (US7): each drawing compared with the profile's drawing section, one finding per
   drawing outside the release verdict and the checklist's drawing item.

Everything but the seat probes lands with no licence: the extractor half is tested with fakes and a
reflection test, the reasoning half with fixtures.

## Technical Context

**Language/Version**: C# (.NET, the existing extractor, add-in and console projects) for the guard,
the attach, discovery, the new reads, the IR mirrors and the probe command; Python 3.11+ for the IR,
the drawing evidence index, the conversion, the binding, the resolver change, the check, the brief,
the tools, the profile and the fixtures; PowerShell 5.1 for the one metadata script that generates
the guard table.

**Primary Dependencies**: no new packages. Reused rather than rebuilt: feature 006's `DrawingDumper`
and `DrawingTraversal` (the walk, the id rules, the revision-table cell loop, now shared by every
table), `DenylistTable.Parse` and the recording observer; feature 010's `ToleranceDumper.KindOf` and
`IsFitType` (one tolerance mapping for model and drawing dimensions), `IModelAnnotationReader`'s frame
and datum members, `GtolFrame`, `RevisionTableRow`, `checks/tolerances.py` (`resolve_tolerance`,
`iso_dimension`, `_doubled`, `_frame_zone`, `ResolverLookup`), `checks/joints.build_joint_map`,
`tools/joint_context.joint_analysis`, `checks/joint_alignment.check_nominal_alignment`'s `callout`;
feature 009's `EvidenceRequest` and panel; feature 008's `planned_calls`, `repeat_key`, answer batch
and model view; `ir/models.omit_additive`; `tests/support/mechanical.py`,
`tests/support/fixture_denylist.py`.

**Storage**: files only. `package.json` gains optional members at IR 1.6.0 (written by the extractor
only); the standards profile gains version 3; `session.json` gains nothing new in shape (questions are
`EvidenceRequest`s). No new run-folder file.

**Testing**: xUnit for the guard (parsed table, reflection completeness, read audit), the attach
refusal, discovery, the new reads, the IR serializer and `PackageWriter`, all with fakes; pytest for
the IR round trips, the index, the conversion, the binding, the resolver, the tools, the check, the
brief, the profile and the fixtures, over three committed synthetic packages; the drawing arm of the
payload pins; the replay of every recorded review. The tests that go red by design are named in
research R3 and in the task that lands each change.

**Target Platform**: as features 001 to 010. The interop assemblies are read as metadata by the
generating script and the completeness test; SOLIDWORKS is never started off the seat.

**Project Type**: extends the extractor, the add-in's dump path, the console, and the reasoning side;
no pane page changes (feature 009's panel shows the questions as they are).

**Performance Goals**: discovery with thirty open documents under 1 s on the seat (probe D2 records
it); reading ten attached drawings adds under 10 s per six-sheet drawing, feature 006's SC-013 budget;
`DrawingIndex.for_package` under 50 ms and `build_brief` under 200 ms on the fixtures (a marked perf
test).

**Constraints**: the constitution's Principles I to VI; the read-only rule with no new exception; no
drawing value in a calculation before T066; no tolerance, precision or unit inferred - a missing one
is unresolved; nothing opened, activated, selected, rebuilt or saved (the one open is a candidate
the engineer confirms, read-only, hidden, closed again - owner 2026-09-23); every new evidence field
additive; every existing tool signature, docstring and payload pin unmoved; `ARRAY_CEILING` 38,000;
replay unchanged; nothing from any recorded package or company in the repository.

**Scale/Scope**: seven user stories; one new argument-free check and one new query tool in a
conditional family; one new finding id; eleven new gap kinds; evidence schema 1.6.0; profile version
3; three fixtures; 580 generated guard denials; about 77 tasks, 8 of them on the seat (T069 to T077 added 2026-09-23 for the owner's Q2 answer).

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design (result at the end of the
table).*

| Principle | Gate | How this plan meets it | Status |
|---|---|---|---|
| I. Evidence before conclusions | Unknown stays unknown | A drawing binds a subject only through a usable view (its configuration the reviewed one, read as up to date, its model loaded) and an attached face or the one model dimension that sizes it (R2.8); an unread flag, precision, unit or configuration is a reason, never a default; the general tolerance binds only with a written precision in the profile's declared unit (R2.9); a `GENERAL`-table dimension binds nothing; disagreeing drawings are a conflict, disagreeing precisions bind nothing; a candidate drawing is named, never opened; every unreadable value is a gap. | PASS |
| II. Deterministic numerics, agentic investigation | The model computes no verdict | Every limit, precision and conformance result comes from `checks/` and `drawings/`; the new check takes no argument; the brief is built by code from feature 010's functions; the model reads counts and the brief and asks nothing it could compute. | PASS |
| III. Test-first with golden fixtures | Tests precede code; no unverified tool output in a calculation | Every task pair is test then implementation; three synthetic fixtures reproduced byte for byte; every read tested with fakes first; the drawing source ships behind `DRAWING_BINDING_VALIDATED = False`, and the same switch makes `resolve_dimension` refuse a native dimension, so no fit, stack or alignment check computes with one (R2.11, corrected 2026-09-23); it is enabled only after probes D6 and D8 pass on a known drawing and D4 and D5 agree with the conversion (T066), exactly the rule "MUST NOT enter a calculation until a test against a known case passes". | PASS |
| IV. Semantic fidelity and traceability | Persistent refs; versioned schema; native over exported | Every new record carries its persistent reference when SOLIDWORKS gives one, scoped to its own drawing; attachments carry the model face's reference scoped to its part; IR 1.6.0 is additive and versioned; tolerances come from native drawing data, never from a PDF where a native sheet exists (a native sheet wins over an ingested one of the same name). | PASS |
| V. Engineered enough | DRY; explicit; no speculation | One tolerance mapping for model and drawing dimensions; one table walk for every table; one annotation record enriched by type; one conversion for three tools; one evidence-request writer for the model and the check; the brief reuses 010's joint map, callout and resolver; the guard table generated, not typed; two named attach entry points instead of a flag. No new transport, provider or agent stage. The templates in the profile are data for 012 and are named as such. | PASS |
| VI. Findings inspectable, coverage tracked | Reproducible findings; coverage visible | Drawing coverage per reviewed document (read, unusable and why, candidate); the limit gap names every unread drawing; the brief counts every omission; the one new finding names each difference with the drawing's value; nothing is a blanket exclusion. | PASS |
| Technical constraint: documents are read, not written | No mutation | Every change is a read; 580 writers newly refused before any new read lands; the gate log of a drawing extraction shows no writer, activation, open or close member (FR-007). The owner's Q2 answer adds one read-only open of a confirmed candidate: it writes and saves nothing, activates nothing, closes only what it opened, and goes through an allowlist of three keys (`contracts/confirmed-open.md`); a read-only open is a read, so no exception is needed. | PASS |
| Technical constraint: 2026 dependencies | None | Every member named was reflected on the 2024 SP5 interop (32.5.0.48); Auto-Generate Drawing (2026) is not used. | PASS |
| Technical constraint: pilot scope | Findings, not GD&T creation | The brief reports each interface's existing tolerance and feature 010's recommended callout; nothing dimensions or tolerances a drawing. | PASS |
| Technical constraint: curated tools only | No generic execution | One argument-free check and one query tool; the application's macro members are newly refused. | PASS |

**Post-design re-check**: no exception, no Complexity Tracking row.

## Project Structure

### Documentation (this feature)

```text
specs/011-drawing-context/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, attach.md, guard.md, open-drawings.md, native-evidence.md,
│              drawing-source.md, questions.md, brief.md, profile.md, fixtures.md, probes.md}
└── checklists/requirements.md
```

### Source Code (repository root)

Every file this feature adds or changes. A file not named here is not touched; in particular
`findings.py`, `checks/joints.py`, `checks/joint_alignment.py`, `checks/standards/*` other than
`profile.py`, `checks/rms/*`, every provider, `agent/runner.py`, every page script and
`report/markdown.py` are **reused unchanged**.

```text
reviewer/src/swreview/
├── drawings/__init__.py                # NEW
├── drawings/evidence.py                # NEW: ViewEvidence, DrawingIndex (which views are usable, why not)
├── drawings/native.py                  # NEW: native_dimension, written_precision, written_unit, native_sheets
├── drawings/binding.py                 # NEW: DRAWING_BINDING_VALIDATED, DrawingBinding, bindings_for
├── drawings/brief.py                   # NEW: BRIEF_VERSION, BRIEF_MAX_BYTES, DrawingBrief, build_brief
├── checks/drawing_context.py           # NEW: run_drawing_context (coverage, question specs), compare_with_profile
├── checks/tolerances.py                # CHANGED: DrawingAnswer, drawing_answer (replaces drawing_tolerance),
│                                       #          the precision hand-off, holds_any_source, _frame_zone on frames
├── checks/standards/profile.py         # CHANGED: version 3, DrawingSection
├── ir/models.py                        # CHANGED: 1.6.0 - the fields of data-model sections 1 and 2
├── tools/drawings.py                   # NEW: drawing_evidence, check_drawings, get_drawing_brief
├── tools/registry.py                   # CHANGED: drawing_tools(), offered by _offered on drawing evidence
├── tools/session.py                    # CHANGED: record_evidence_request, the writer request_evidence delegates to
├── tools/query.py                      # CHANGED: get_drawing_sheet, find_dimensions read native sheets;
│                                       #          get_package_summary's native count only when non-zero
├── tools/refs.py                       # CHANGED: resolve_dimension reads native sheets, refusing them until T066
├── agent/package_brief.py              # CHANGED: native sheet counts only when non-zero
├── prerun.py                           # CHANGED: planned_calls' drawing branch; repeat_key for check_drawings
├── report/attention_policy_v1.yaml     # CHANGED: drawing_profile.conformance -> manufacturing
└── cli.py                              # CHANGED: the `drawing` sub-application, `drawing brief`

reviewer/tests/
├── support/drawings.py                                                          # NEW
├── fixtures/drawings/{generate_fixtures.py, plate-drawing/, drawing-root/, assembly-drawings/}  # NEW
├── unit/test_ir_drawing_context.py, test_support_drawings.py,
│   test_drawing_fixtures_are_fictional.py                                       # NEW
├── unit/test_standards_drawing_root_1_6.py                                      # NEW
├── unit/test_drawing_evidence.py, test_package_counts_native.py                 # NEW
├── unit/test_native_dimension.py, test_drawing_binding.py, test_tools_native_drawing.py,
│   test_drawing_source_acceptance.py                                            # NEW
├── unit/test_drawing_annotations.py                                             # NEW
├── unit/test_session_writer.py, test_drawing_context.py, test_tools_check_drawings.py,
│   test_replay_without_drawings.py                                              # NEW
├── unit/test_drawing_brief.py, test_tools_get_drawing_brief.py                  # NEW
├── unit/test_drawing_conformance.py                                             # NEW
├── perf/test_drawing_brief_perf.py                                              # NEW
├── unit/test_tolerances.py, test_standards_profile.py, test_standards_no_company_values.py,
│   test_tool_payload.py, test_attention_catalogue.py, test_schema_sync.py      # CHANGED
└── golden/test_golden/standards-*.yml (the profile sha256 lines only)          # CHANGED

extractor/SwReview.Extractor/
├── Guard/ReadOnlyGuard.cs              # CHANGED: `partial`, nothing else
├── Guard/ReadOnlyGuard.Drawing.cs      # NEW: the generated feature 011 names
├── Sw/SwSession.cs                     # CHANGED: AttachPurpose, AttachForDump, ConfigurationName, nullable
│                                       #          Configuration on ISwSession, the not-open drawing refusal
├── Sw/SwScope.cs                       # CHANGED: ConfigurationName
├── Dump/OpenDrawingDiscovery.cs        # NEW: OpenDocument, AttachedDrawings, Discover (pure)
├── Dump/SwOpenDrawingReader.cs         # NEW: IOpenDrawingSource over GetDocuments, GetViews, File.Exists
├── Dump/DumpContracts.cs               # CHANGED: IOpenDrawingSource; DumpScope's drawing allocators and
│                                       #          Drawings; ComponentTreeResult.AttachedDrawings
├── Dump/PackageWriter.cs               # CHANGED: discovery before the document phase (and in the probe),
│                                       #          DocumentPaths, BuildDesign, the drawing loop, the gap sentences
├── Dump/ComponentTreeDumper.cs         # CHANGED: the root kind read before any configuration
├── Dump/DrawingDumper.cs               # CHANGED: the new reads, attachments, typed annotations, every table
├── Dump/DrawingTraversal.cs            # CHANGED: allocators from the scope; tables
├── Dump/SwDrawingReader.cs             # CHANGED: Drawing(document), PersistRef(document, entity), new reads
├── Dump/ToleranceDumper.cs             # CHANGED: the tolerance read and mapping shared with DrawingDumper
├── Dump/SwDump.cs                      # CHANGED: AttachForDump; the open-drawing source wired
├── Guard/DrawingOpenGuard.cs           # NEW (Q2): the confirmed open's three-key allowlist
├── Sw/DrawingOpenScope.cs              # NEW (Q2): the guarded seam, close-if-we-opened-it, the switch
├── Dump/ConfirmedDrawingRead.cs        # NEW (Q2): drawing.read's host side; PackageAppender.MergeDrawing
├── Bridge/{BridgeDispatcher.cs, BridgeProtocol.cs, SecretPolicy.cs}  # CHANGED (Q2): drawing.read, 1.3, review scope
└── Ir/DrawingRecord.cs, Ir/DrawingTable.cs (NEW), Ir/EvidencePackage.cs   # CHANGED: 1.6.0
extractor/SwReview.AddIn/Review/{SwReviewDump.cs, ReviewHost.cs}           # CHANGED: AttachForDump; the sentence
extractor/SwReview.AddIn/ToolService/ToolServiceHost.cs                    # CHANGED (Q2): the confirmed-drawing source
extractor/SwReview.Extractor.Console/Program.cs                            # CHANGED: dump and probe standards
                                                                           #          use AttachForDump; probe drawings
extractor/tools/list-writer-members.ps1                                    # NEW: generates the guard table
extractor/SwReview.Extractor.Tests/
├── GuardTests.cs, RemodelGuardTests.cs                                    # CHANGED: the three new test classes
├── SwSessionAttachTests.cs, DrawingDumperTests.cs, DrawingTraversalTests.cs,
│   PackageWriterTests.cs, ComponentTreeDumperTests.cs, IrSerializerTests.cs   # CHANGED
├── OpenDrawingDiscoveryTests.cs                                           # NEW
└── Fakes/                                                                 # CHANGED: a second drawing, open documents
extractor/SwReview.AddIn.Tests/                                            # CHANGED: the Review refusal sentence

specs/
├── 001-agentic-design-review/contracts/{agent-tools.md, cli.md, ir.schema.json}
├── 004-resilient-remodeler/contracts/guard-allowlist.md                   # the generated "Feature 011" table
├── 006-standards-check/{spec.md (FR-025), contracts/ir-additions.md (s7), contracts/profile.md, research.md (R5)}
├── 007-attention-policy-gate/contracts/attention.md
├── 008-checks-first-review/contracts/checks-first.md                      # section 5, the (tool,) key
└── 010-mechanical-checks/contracts/tolerances.md                          # section 6, the slot's new return
config/standards.example.yaml, reviewer/tests/fixtures/standards/profile-{a,b}.yaml   # CHANGED: version 3
README.md                                                                  # CHANGED
```

#### Landed as (T060, reconciled 2026-09-23)

The block above is the plan. What landed differs as follows; every other line of it landed as
written. The file list is `git diff 62a9b2e~1 HEAD` over the product trees on the day, feature 011's
commits only.

| Plan | Landed as |
|---|---|
| `agent/runner.py` reused unchanged | *landed as* CHANGED: `answer_evidence_batch` calls `read_confirmed_candidates` before the resumed turn (T076), and restates `check_drawings` over a package a read reloaded (`_restate_drawing_check`, review 2026-09-23); `ReviewRun` takes the dispatch and the pre-run guard |
| `checks/joint_alignment.py` reused unchanged | *landed as* CHANGED: `tolerance_subjects(joint, package)` extracted, so the brief and the stack-up name the same subjects (FR-042, T051) |
| (not named) | *landed as* CHANGED: `tools/context.py` (`reload_package`, T076); `bridge/client.py` and `bridge/PROTOCOL.md` (`drawing.read`, protocol 1.3, T072; `BridgeRefusedError`, review); `report/review_words_v1.yaml` (`drawing_profile.` joins the drawings goal's prefixes, T057); `report/names.py` and `tools/checks_mechanical.py` (one `plural`, review DRY) |
| `prerun.py`: the drawing branch and `repeat_key` | *landed as* also `recorded_call` and `PrerunGuard.answer_repeats_with` (review 2026-09-23) |
| `Dump/ToleranceDumper.cs` shares the tolerance read | *landed as* NEW `Dump/DimensionTolerance.cs` (`IDimensionToleranceReads`, `DimensionTolerance.Read`), called by both dumpers (T027) |
| `Dump/DrawingDumper.cs` typed annotations | *landed as* also NEW `Dump/AnnotationSymbols.cs` (`IAnnotationSymbolReads`, `GtolFrames.Read`, T040) |
| `Dump/ConfirmedDrawingRead.cs`; `PackageAppender.MergeDrawing` | *landed as* written, with `Dump/PackageAppender.cs` CHANGED and `Ir/Enums.cs` CHANGED (T008's new enumerations) |
| `Bridge/*` | *landed as* written, and `extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md` CHANGED (1.3) |
| `Guard/ReadOnlyGuard.cs`: `partial`, nothing else | *landed as* `partial` (T004), and on review a qualified key is judged by its member half too (2026-09-23); `ReadOnlyGuard.Drawing.cs` holds the writers of 28 families, the four callout-variable interfaces joining on review |
| `SwReview.AddIn/ToolService/ToolServiceHost.cs` CHANGED (Q2) | **not landed**: T074 is partial - `ReviewHost.ReviewRunDirectory` is in, `ToolServiceHost`'s source is not, so `drawing.read` has no source in the add-in yet |
| `SwReview.AddIn/Review/ReviewHost.cs`: the sentence | *landed as* also `ReviewRunDirectory(run_id)` (T074's half) |
| `SwReview.AddIn.Tests/`: the Review refusal sentence | *landed as* also `ReviewHostTests`' run-directory section and `ReviewPageDrawingQuestionsTests` over the generated `Fixtures/review-drawing-questions.json` (`reviewer/tests/fixtures/pane/generate_drawing_questions.py`, `test_pane_drawing_fixture.py`) |
| extractor tests | *landed as* also NEW `DrawingOpenTests.cs`, `ConfirmedDrawingReadTests.cs`, `Fakes/DrawingOpenFakes.cs`, `Fakes/ConfirmedDrawingFakes.cs`, and CHANGED `BridgeDispatcherTests.cs`, `BridgeSecretPolicyTests.cs`, `PackageAppenderTests.cs`, `StandardsGateLogTests.cs`, `RemodelInteropManifestTests.cs` |
| reviewer tests | *landed as* also NEW `test_confirmed_drawing_read.py`, `test_pane_drawing_fixture.py`, and CHANGED `test_bridge_client.py`, `test_general_tolerance.py`, `test_report_names.py`, the `test_ir_*` schema pins, `test_support_*` and `tests/support/{mechanical,review_bridge,fixture_denylist}.py`; the replay fixtures' `events.jsonl` regenerated with their generator (008 `contracts/replay.md` section 8) |

**Structure Decision**: both trees extended in place, as every feature since 002. The drawing
evidence readers form a new `drawings/` package because they are neither checks nor tools: the index,
the conversion, the binding and the brief are pure readings of the package that `checks/`, `tools/`
and the command all consume. The drawing check's logic is under `checks/` like every other check; its
two tools share one module because they are one conditional family.

## Phase 0 and Phase 1

Research in [research.md](research.md) (R1 to R6). Design in [data-model.md](data-model.md) and
[contracts/](contracts/). Twelve points tasks must honour:

1. **The guard lands before any new read**, generated from the interop, complete by reflection, and
   narrowing nothing feature 004 allows (R2.2).
2. **Two attach entry points.** Model callers keep `Attach` and its refusal; only extraction uses
   `AttachForDump`; a drawing session binds no configuration and the type says so (R2.1).
3. **Only open drawings, only those that show the design, at most ten, matched by full path**;
   discovery precedes the document phase and runs in the reuse probe; no phase row (R2.3).
4. **A candidate is a name, never a file the extraction opens**; one exact name, one folder (R2.4);
   only the engineer's confirmation opens it, read-only, through its own allowlist (R2.23).
5. **Ids are the package's**, not the drawing's; a root drawing numbers as before (R2.5).
6. **Usable views only**: the reviewed configuration, up to date, model loaded, not detailing (R2.6).
7. **One tolerance mapping, one table walk, one annotation record** (R2.7, R2.12).
8. **The binding ships disabled** and is enabled by one edit after probes D6 and D8 pass (R2.8); the
   same switch keeps native dimensions out of the calculating tools until then (R2.11).
9. **The general tolerance needs a written precision and the profile's unit**; profile version 3's
   section lands with US3 for that reason; `GENERAL`-table dimensions bind nothing (R2.9, R2.17).
10. **Feature 010 changes in its slot and nowhere else**; with no drawing record, every answer is
    today's but source 1's wording (R2.10).
11. **The drawing family is conditional**, planned like `check_standards`, pinned in its own arm; with
    no drawing evidence nothing the model sees changes (R2.14, R2.20).
12. **The brief is bounded, deterministic, reference-free and profile-value-free**, and reuses 010
    (R2.16).

## Delivery order

| Order | Story | Deliverable | Needs SOLIDWORKS |
|---|---|---|---|
| 1 | Setup | 006 FR-025 and 010's slot decisions recorded | No |
| 2 | Foundational | the guard; IR 1.6.0 in both languages; package-scoped drawing ids and the reader by document; the three fixtures | No |
| 3 | **US1** (P1) | `AttachForDump`, the refusal by purpose, a drawing root with no configuration, the Review sentence; Standards over the drawing-root fixture | Validation only |
| 4 | **US2** (P1) | discovery, candidates, the ten-drawing bound, the wiring into `PackageWriter`, the gap sentences, the reuse key; the Python index; the non-zero native counts | Validation only |
| 5 | **US3** (P1) | the dimension, view, drawing and sheet reads; profile version 3; the conversion; the binding (disabled); the resolver's drawing answer; the tools on native sheets; the acceptance | Validation only |
| 6 | **US4** (P2) | typed annotations, attachments and every table; the position source | Validation only |
| 7 | **US5** (P2) | the evidence-request writer; the coverage and questions; the conditional family and plan; the replay proof | No |
| 7B | **US5, part B** (P2, owner 2026-09-23) | the guarded seam and its allowlist; `drawing.read` and the merge; the add-in wiring; the backend's trigger and reload | Validation only (D14) |
| 8 | **US6** (P2) | the brief, its tool and command; the drawing arm pinned | No |
| 9 | **US7** (P3) | conformance and its class | No |
| 10 | Polish | README, the 001, 007 and 008 contract rows, the quickstart, the checklist | No |
| 11 | Workstation | probes D1 to D13, feature 006's T103, T105, T107, the binding enabled, the pane and the profile on real drawings | Yes |

**Sequencing that is not negotiable.** The guard before every new read (T003-T004 before T009 and
everything after). IR 1.6.0 before any reader writes a new field. Package-scoped ids before a second
drawing is read (T010 before T019). The fixtures before any Python acceptance test. Profile version 3
before the resolver's unit rule (T029 before T035). The evidence-request writer before the check
writes a question (T044 before T048). The drawing arm pinned only after both tools exist (T055 after
T053), with `--write`, in a commit of its own. `DRAWING_BINDING_VALIDATED` set only by T066.
The guard before the confirmed open's seam (T004 before T069); `DrawingOpenScope.SeatValidated` set
only by T077.

**Sequencing against the other features.** 011 needs 008, 009 and 010 on main, which they are. The
files 011 shares with other features' likely changes - `prerun.py`, `tools/registry.py`,
`tools/query.py`, `tools/session.py`, `checks/tolerances.py`, `checks/standards/profile.py`,
`ir/models.py`, `test_tool_payload.py`, `attention_policy_v1.yaml`, `PackageWriter.cs`,
`ReadOnlyGuard.cs`, the 001, 004, 006 and 010 contracts - are listed per task in `tasks.md` so no two
features edit one at once. Feature 012 starts after this feature's seat tasks and a constitution
amendment; nothing here prepares a write path beyond refusing every one.

**External dependencies**: the licensed seat for the probes; the owner's version 3 profile values; the
location of the owner's drawing-creation base repository for T061.

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | A binding ties a callout to the wrong hole and a stack-up reports a wrong verdict with authority. | Two routes only, both exact; usable views only; the switch off until a known drawing passes D6 and D8 (T066); the known case becomes a regression row. |
| RK-2 | The persistent reference of a drawing entity's model face never equals the face phase's (scope, assembly context). | D6 records it for a part and an assembly drawing; the model-dimension route stands alone for model items; the attached-face route stays off for the case that fails, and the brief says why. |
| RK-3 | `GetDocuments` misses a drawing, or `GetViews` activates something. | D2 and D3; activation members are refused by the guard, so an activating path fails loudly rather than silently. |
| RK-4 | The generated denylist refuses a read the extractor needs. | The read audit test over every gated literal; the probe gate logs at the seat. |
| RK-5 | Thirty open drawings make a review slow to start. | The ten-drawing bound, root drawings first, the rest named; D2 times discovery. |
| RK-6 | The candidate existence check fetches a vault file or stalls. | D13; a rule that skips candidates under a vault view if it does, one gap saying so. |
| RK-7 | The drawing tools push the array over the ceiling or move the recorded figures. | The family is conditional; its arm is pinned separately under 38,000 with per-tool budgets; the replay proof (T049). The bridged arrays were over the ceiling before this feature and stay unasserted; their drawing arm is pinned so growth shows (R2.20, R5 Q9). |
| RK-8 | A document-precision dimension's precision is misread and the wrong general band binds. | Both defaults recorded; D4 decides; disagreeing precisions bind nothing; the switch off until T066. |
| RK-9 | Profile version 3 breaks the owner's real profile. | The loader keeps reading versions 1 and 2; the drawing sources stay absent until the owner writes version 3. |
| RK-10 | The questions flood the pane on a large assembly. | One aggregated candidate question; at most three governing questions; coverage for the rest. |
| RK-11 | The conformance finding closes the checklist's drawing item. | The `drawing_profile.` prefix; a test asserts the item stays open. |
| RK-12 | The confirmed open activates the drawing, takes focus, locks or writes the file, or closes a document the engineer had open. | A three-key allowlist; options asserted as the integer 3; hidden around the open; close only what the seam opened, after a COM-identity check; the switch off until probe D14 passes (T077). |

## Complexity Tracking

None. No constitution exception, no mutation path, no new transport, provider or agent stage. The
second attach entry point replaces a boolean flag; the conditional tool family follows the three that
exist; the generated guard table replaces a hand list of 580 names.
