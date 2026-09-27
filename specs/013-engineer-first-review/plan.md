# Implementation Plan: Engineer-First Review

**Branch**: `013-engineer-first-review` (worked on `main`) | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/013-engineer-first-review/spec.md`, the 2026-09-26
sitting and its six analysts' reports, and the defaults of the same day recorded in
[research.md](research.md) R2. Numbered 013 so that 012 stays reserved for drawing creation.

## Summary

Make the review grade what an engineer owns, ask only what it cannot know, and say where every line
came from - in the order the next sitting needs it:

1. **Bought parts out of the grading** (US1): standards profile version 4's `part_roles` section and
   an upgrade helper that proposes it; one pure classifier (custom, bought, unclear, each with its
   rule) attached before the pre-run; RMS and hygiene grade custom and unclear parts only; bought
   parts named once; the mates rule judges the custom side; one code question for the unclear parts,
   with buttons and a text box, whose answer regrades in the same session and withdraws what no longer
   holds.
2. **Every finding, grouped by type** (US2): `rank()` never amplifies a pass; one grouped view built
   from the attention order and feature 009's goals (each goal naming its group; Standards split from
   Hygiene); the Review tab's one grouped section replaces Start here, "Show all" and the flat list;
   the report's "Findings by type"; the check tabs keep a pass-free preview.
3. **No question the review can answer itself** (US3): provenance closed by code at setup; code-owned
   checklist items answered `closed_by_code`; the re-ask guard (`already_answered`, `already_asked`);
   the ids the tools hand out accepted; the brief printing only known provenance; the extractor's two
   per-document vault gaps removed, separately.
4. **Drawings that follow the seat** (US4): the add-in reports its drawing-read capability on ping;
   one drawing state per document (attached, candidate, absent, bought); no question while the seat is
   not validated, an instruction line instead; one question and one read per drawing file; code
   answers drawing requests; refusal outcomes reach the model.
5. **Sources everywhere** (US5): a `source` token on findings, questions and coverage; "Checked by
   code" and "AI guidance"; a deterministic basis line on every model answer; no fallback explanation;
   the explanation pass keeps valid items and logs rejections.
6. **Cheaper answer turns** (US6): the close-out closed by code; `open_items` on coverage results;
   lever 14 (earlier turns' reasoning out of the request view), adopted only on the replay's say-so;
   the replay gate for every change that moves what the model reads.
7. **Readings that match SOLIDWORKS** (US7): each sheet's own view read; the revision check honest
   about a missed table; one feature-tree reading shared by the grading checks and the planner.
8. **Test debt** (U24): probe 1's watchdog decided by a signal, not a race; flag-set first.

Everything lands with no licence: the C# with fakes, the Python with fictional fixtures and the
replay. The seat tasks (phase W) validate on the next sitting.

## Technical Context

**Language/Version**: Python 3.11+ (the reviewer: profile, classifier, checks, tools, runner, report,
words, replay); C# on .NET Framework 4.8 (the bridge's ping, the confirmed-drawing source, the merge,
the drawing phase's sheet view, the manifest gaps, the probe watchdog); JavaScript in the Review page
and the shared attention script, under the pane's CSP.

**Primary Dependencies**: no new packages. Reused rather than rebuilt: feature 006's `PrefixMatcher`
and `part_number_matches` (split into `PrefixList` and `name_matches`), the profile loader; feature
007's rank keys and fold; feature 008's pre-run, re-call guard, `_verdict_key` reconcile, answer batch,
model view and replay; feature 009's goals, `goal_of`, `GoalLine`, questions panel and words file;
feature 010's hygiene checks and `DocumentTree`; feature 011's drawing index, candidate question,
confirmed read, brief and `DrawingOpenScope`; feature 004's `tree_nodes` (moved, re-exported).

**Storage**: files only. The profile gains version 4 (owner's file, never committed). `session.json`
gains four optional fields; `events.jsonl` gains `text.done.basis` and `finding.withdrawn`. No
evidence schema change; no new run-folder file.

**Testing**: pytest (`SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts=""`,
with `-m "not live"` where the live tests cannot run) and `uv run ruff check src tests`; xUnit for the
C# (`dotnet build extractor/SwReview.sln -c Release`, zero warnings, then `dotnet test`); the pane's
page tests in `SwReview.AddIn.Tests`; the replay of every recorded review (the replay gate,
`contracts/tokens.md` section 5).

**Target Platform**: as features 001 to 011. SOLIDWORKS is never started off the seat.

**Project Type**: extends the reasoning side, the extractor, the add-in and the Review page.

**Performance Goals**: `classify_parts` under 50 ms and `findings_by_type` under 100 ms on the
big-assembly pane fixture (a marked perf test); the Review page renders 1,000 findings grouped within
feature 009's `views.md` section 7 budget; one extra bridge round trip (ping) only on reviews with a
custom-document candidate.

**Constraints**: the constitution's Principles I to VI; no new read-only exception; no tool signature
or docstring change; every new field optional and omitted at its default; the page never sorts; no
company value anywhere (the standards census, the tracked-files guard); the replay's absolute rule.

**Scale/Scope**: seven user stories and one test-debt phase; profile version 4; four session fields;
two event changes; one new lever; six new modules (`checks/part_roles.py`, `checks/provenance.py`,
`checks/feature_nodes.py`, `checks/questions.py`, `report/finding_groups.py`, `report/sources.py`);
144 tasks, 4 of them on the seat.

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after Phase 1 design.*

| Principle | Gate | How this plan meets it | Status |
|---|---|---|---|
| I. Evidence before conclusions | Unknown stays unknown; nothing silently dropped | A part no rule decides is unclear and graded, never assumed bought; an unknown input (no path, unread properties) is never a match; a bought part is named once, never silently absent; a missing drawing is unresolved coverage; the revision check never claims absence over a read gap; a withdrawn finding has an event and a reason | PASS |
| II. Deterministic numerics, agentic investigation | The model computes no verdict | Classification, grouping, the basis line, drawing states and the close-out are code; the model's answers are labelled as guidance and never parsed | PASS |
| III. Test-first with golden fixtures | Tests precede code; fixtures follow the code | Every implementation task follows its failing test task; fictional fixtures for every new function; the replay fixtures regenerated by the change that moves them (decision 3A); the sheet-view reader validated on the seat before its tables are trusted (phase W) | PASS |
| IV. Semantic fidelity and traceability | Native data; versioned schemas | Roles read native signals (Toolbox, the path, the properties); the profile is versioned (4) and older versions still load; the bridge protocol's minor version rises; the sheet's own view is native | PASS |
| V. Engineered enough | DRY; explicit; no speculation | One classifier, one prefix matcher, one pattern matcher, one question shape and duplicate test, one taxonomy for goals and groups, one `_file_key`, one tree reading, one `_restate`; the upgrade helper proposes and decides nothing; lever 14 off until measured | PASS |
| VI. Findings inspectable, coverage tracked | Reproducible; coverage visible | Every skip, withdrawal and code closure is a coverage row or an event with a reason; every record says its source; the report and the pane list every finding | PASS |
| Documents are read, not written | No mutation | Nothing writes a document; the drawing open stays feature 011's read-only seam, unchanged | PASS |
| Pilot scope; curated tools | Findings only; no generic execution | No new tool; new behaviour arrives as statuses and fields | PASS |

**Post-design re-check**: no exception, no Complexity Tracking row.

## Project Structure

### Documentation (this feature)

```text
specs/013-engineer-first-review/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/{README.md, part-roles-profile.md, part-roles.md, grouped-list.md,
│              re-ask-guard.md, drawing-capability.md, sources.md, tokens.md, readings.md}
└── checklists/requirements.md
```

### Source Code (repository root)

Every file this feature adds or changes, with the lane that owns it (tasks.md, "Lanes").

```text
reviewer/src/swreview/
├── checks/standards/profile.py      # P: version 4, PartRolesSection, SECTIONS_BY_VERSION-derived later-section check
├── checks/standards/library.py      # P: PrefixList extracted
├── checks/standards/traversal.py    # P: name_matches(wildcards)
├── checks/part_roles.py             # P: NEW classify_parts, PartRoles, answered_roles, note_unclear
├── checks/questions.py              # S: NEW QuestionSpec, the shared duplicate test (moved)
├── checks/provenance.py             # S: NEW close_provenance
├── checks/hygiene.py                # P: graded documents
├── checks/rms/assembly.py (+ rules) # P: the mates rule's custom side
├── checks/drawing_context.py        # D: drawing_states, candidate_files, the offer by mode, the item closed by code
├── checks/feature_nodes.py          # T: NEW tree_nodes (moved)
├── checks/rms/part.py               # T: the shared tree
├── checks/standards/part.py         # T: the shared tree
├── checks/standards/drawing.py      # X: revision_matches
├── drawings/evidence.py             # D: file_key (moved)
├── drawings/brief.py                # D: states, dedup, outcomes
├── remodel/nodes.py                 # T: re-exports
├── tools/rms_checks.py              # P: part_documents over graded documents
├── tools/checks_mechanical.py       # P: review_profile(context); hygiene reads roles
├── tools/session.py                 # S: closed_by_code, the guard, drawing answers, open_items, allow_text/source writes
├── tools/drawings.py                # D: one read per file, the rebuilt question
├── tools/context.py                 # S: entity kinds, withdraw_findings, drawing_read_mode
├── tools/registry.py                # S: PART_ROLES_ATTRIBUTE
├── report/session.py                # S: allow_text, source, drawing_read, covering_requests
├── findings.py                      # S: Finding.source
├── report/attention.py              # R: ranked_rows, top_n, legacy fallback filtered
├── report/finding_groups.py         # R: NEW findings_by_type
├── report/summary.py                # R: groups, the summary block, bought parts, drawings words, QuestionView
├── report/review_words_v1.yaml      # R: groups and row words, goals, labels.source, answer_basis, bought_parts.heading, text_placeholder, drawings words
├── report/markdown.py               # R: Findings by type, Source column, AI guidance label, Bought parts
├── report/explanations.py           # R: partial acceptance, logging, keep_explained
├── report/sources.py                # R: NEW answer_basis
├── report/titles.py, report/snapshot.py   # R: source on pane bodies
├── agent/checklist.py, agent/checklist_v1.yaml   # S: owner, wording
├── agent/package_brief.py           # S: known provenance only, role=
├── agent/prompts/system_v1.md       # S: three sentences
├── agent/runner.py                  # S: roles attach, provenance, the question, _restate, outcome lines, basis marker, closeout
├── agent/settings.py                # E: lever 14
├── agent/providers/openai_provider.py   # E: lever 14's request view
├── bridge/client.py, bridge/PROTOCOL.md # D: drawing_read_mode, the minor version
├── benchmark/replay*.py             # E: lever 14 pricing
├── prerun.py                        # P: the two NotEvaluated lines; attach_standards takes the loaded profile
├── carry_over.py                    # P: no RMS carry for a bought document
└── cli.py                           # P: `profile upgrade`

extractor/SwReview.Extractor/
├── Bridge/BridgeDispatcher.cs, Bridge/BridgeProtocol.cs   # D: OpensClosedDrawings, PingResult.DrawingRead, version
├── Dump/ConfirmedDrawingRead.cs, Sw/DrawingOpenScope.cs   # D: the property
├── Dump/PackageAppender.cs                                # D: the merge removes every row of the path
├── Dump/DrawingDumper.cs, Dump/SwDrawingReader.cs, Dump/SwOpenDrawingReader.cs   # X: the sheet's own view
├── Dump/ManifestBuilder.cs                                # X: the two gaps
└── Rms/RemodelProbeWatchdog.cs, Rms/RemodelProbeExecutors.cs, Rms/RemodelProbe.cs   # U: the watchdog
extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md      # D
extractor/SwReview.Extractor.Console/Program.cs             # X: the comment
extractor/SwReview.AddIn/Review/ReviewPage/{render.js, app.js, app.css, index.html}   # W
extractor/SwReview.AddIn/web/shared/{attention.js, check-page.js}                     # W
extractor/SwReview.Extractor.Tests/, extractor/SwReview.AddIn.Tests/                  # the lane of the code under test

config/standards.example.yaml, reviewer/tests/fixtures/standards/profile-{a,b}.yaml    # P: version 4
reviewer/tests/fixtures/replay/*, reviewer/tests/fixtures/pane/*                       # G: regenerated only (the pane drawing fixture: R, T093)
docs/test-plan-2026-09-27/workstation-test-plan.md, reviewer/tests/support/seat_tasks.py         # R (T057, T094), U (T137: step 5.6), Polish (T138)
specs/{001,002,003,005,006,007,008,009,010,011}/contracts/*   # the amendment text, with the task that lands it
```

#### Landed as (T139, reconciled 2026-09-27)

The block above is the plan. What landed differs as follows; every other line of it landed as
written. The file list is `git diff 712ac9e HEAD` over the product trees on the day, feature 013's
commits only (with feature 004's T171, which is 013 T137).

| Plan | Landed as |
|---|---|
| `checks/rms/part.py`, `checks/standards/part.py` (T): the shared tree | *landed 2026-09-27* with the replay gate T134: T132-T133, backed out of `main` at integration, land once the owner's questions T134-Q1 and T134-Q2 are answered by defaults (T145-T146; research R2.47, `benchmark/replay.narrowable`); `checks/feature_nodes.py` (T130-T131, with `carried_rows` from T133) is read by both, and `remodel/nodes.py` re-exports its three names |
| `checks/standards/traversal.py`: `name_matches(wildcards)` | *landed as* `PrefixList`, `name_matches` and `property_key` in `checks/standards/profile.py`, re-exported by `traversal.py` (T003 with T014), because `traversal.py` imports the rules runner, which the classifier's consumers cannot import at the top |
| `checks/standards/profile.py` (P): version 4 | *landed as* written, and `PartRolesSection.signals_unused` (the review of 2026-09-27): a section with every signal unused - the upgrade helper's output before the owner fills it - is read as the version 3 profile it was proposed from (`part-roles.md` section 1) |
| `checks/part_roles.py` (P) | *landed as* written, with the review of 2026-09-27's changes: the root rule's label carried by the bought-parts sentence (FR-008), and a whole answer equal to an option ignoring case, spacing and a closing stop read as that option |
| `Bridge/BridgeProtocol.cs` (D) | *landed as* unchanged: the protocol's minor version (1.4) and `PingResult.DrawingRead` live in `Bridge/BridgeDispatcher.cs` (T073) |
| `web/shared/{attention,check-page}.js` (W) | *landed as* unchanged: the check tabs' five-row preview holds no pass once `top_n` never counts one (T044, T055) |
| `tools/session.py`, `report/session.py`, `findings.py` (S): sources | *landed as* also `tools/query.py` (`as_json(record, exclude=)`, T097), `get_finding` echoing a record without `source` like the two writers (T097), `findings.MODEL_FINDING_CHECK` and the load rule of an older drawing finding (T097), and `EvidenceRequest.pane_body()`, the one body the `evidence.requested` event and the snapshot send (T101-T102) |
| `agent/runner.py` (S), in task order | *landed as* written: T022, T032, T038, T060, T064, T089, T108 (`_emit_turn_event`, `_close_basis`), T113 (`keep_explained`; `fill_fallbacks` removed from `report/explanations.py`), T117 |
| `agent/providers/openai_provider.py` (E): lever 14's request view | *landed as* written, and `_unlinked` (the review of 2026-09-27): the other items of an earlier message that lost a reasoning item are sent without item ids |
| `report/titles.py`, `report/snapshot.py` (R): the source on pane bodies | *landed as* `pane_finding` stating `source` always and the snapshot's requests through `EvidenceRequest.pane_body()`; a coverage body states it only when `model` (`sources.md` section 1's landed-as note) |
| (not named) | *landed as* CHANGED: `agent/providers/__init__.py` (`PriorReasoningAware`, T121); `benchmark/compare.py` (lever 14's name, T121); `handoff.py` (the model's explanations counted, a legacy fallback not; the review of 2026-09-27); `Dump/DrawingTraversal.cs` and `Ir/DrawingRecord.cs` (the sheet's own view and the `drawing_sheet_view` gap, T127) |
| tests | *landed as* 158 files under `reviewer/tests`, `SwReview.Extractor.Tests` and `SwReview.AddIn.Tests`: NEW `tests/support/{sitting,sitting_review,roles_review,fake_part_roles}.py`, the sitting fixture `tests/fixtures/sitting/` (generator and `small-assembly/`), `tests/live/test_openai_live_prior_reasoning.py`; profile A and B at version 4; the replay and pane fixtures regenerated by the replay gates (the pane drawing fixture by T093) |
| `docs/test-plan-2026-09-27/workstation-test-plan.md`, `reviewer/tests/support/seat_tasks.py` | *landed as* T057, T094, T137 and T138, and the seat plan of 2026-09-27 for the next sitting: the plan, its results sheet, the handover and the runbook |

**Structure Decision**: both trees extended in place. The classifier, provenance and the question
shape are `checks/` modules because they are pure readings of the package that tools and the runner
consume; the grouped view and the basis line are `report/` modules beside the ranking and summary they
compose; the feature-tree reading moves to `checks/` because checks now read it and the planner
re-exports it.

## Phase 0 and Phase 1

Research in [research.md](research.md) (R1 to R7). Design in [data-model.md](data-model.md) and
[contracts/](contracts/). Points the tasks must honour:

1. **The classifier is computed once and read everywhere**; an unknown id is graded; no reason quotes a
   profile value (R2.3, `part-roles.md`).
2. **Version 4 is additive**; the owner's version 3 keeps loading; the example, the two fixtures and
   feature 006's contract block move together and keep differing pairwise (R2.1).
3. **Nothing is bought until the owner says so**: the helper proposes commented entries only (R2.2).
4. **A pass is never amplified**, by `top_n`, so every surface follows with no page change (R2.16).
5. **One taxonomy**: goals name their group; the words file and the `Words` model land together
   (R2.14).
6. **The page moves cards, never orders them** (R2.19).
7. **Non-error statuses, not refusals**, for everything the model may legitimately try: no failed rows
   (R2.20, R2.22).
8. **The capability is read from the object that enforces it**, lazily, once, and absent means unable
   (R2.24).
9. **Sources are omitted at their defaults, and never echoed in a tool result**, so nothing the
   model reads moves (R2.29).
10. **No tool signature or docstring changes** (R3 C14).
11. **The replay gate for every change that moves what the model reads**, serialized on `main` after
    each story's merges, with a freeze until the gate lands, one regeneration per commit (R3 C12,
    R5, `contracts/tokens.md` section 5).
12. **The planner's output is byte-identical** after the tree reading moves (R2.38).

## Delivery order

| Order | Phase | Deliverable | Needs SOLIDWORKS |
|---|---|---|---|
| 1 | Setup | the one-line amendment notes (done with this package) | No |
| 2 | Foundational | shared matchers; the question shape and duplicate test; `source` and `allow_text` on the records; the checklist's `owner`; `file_key` moved | No |
| 3 | **US1** (P1) | profile version 4 and the helper; the classifier; consumers; the bought-parts line; the question; the regrade and `finding.withdrawn`; the page's text box; replay gate | Validation only |
| 4 | **US2** (P1) | `top_n`; `ranked_rows`; goals and groups; `findings_by_type`; the summary block; the page; the report; replay gate | No |
| 5 | **US3** (P1) | provenance at setup; `closed_by_code`; the guard; entity kinds; the brief; the prompt; the manifest gaps (separate); replay gate | No |
| 6 | **US4** (P1) | the ping capability; drawing states; the offer by mode; one read per file; code-answered requests; outcomes to the model; replay gate | Validation only (D14) |
| 7 | **US5** (P2) | source words and chips; the basis line; explanations; replay gate (proves nothing moved) | No |
| 8 | **US6** (P2) | the close-out; `open_items`; lever 14 and its decision; replay gate | No |
| 9 | **US7** (P2) | the sheet's own view; the revision check; the shared tree; replay gate | Validation only |
| 10 | Test debt | the probe 1 watchdog | No (the seat's probe run is 004's) |
| 11 | Polish | the test plan and its test; `seat_tasks` gains 013; contracts landed-as | No |
| 12 | Workstation | the profile upgraded; D14; the small assembly re-reviewed; Standards on the drawing | Yes |

**Sequencing that is not negotiable.** The shared matchers before the profile's patterns (T002-T003
before T014). The records' `source` and `allow_text` before any code question is written (T007 before
T032). The checklist's `owner` before any code-owned item (T009 before T060, T062, T087 and T117). The
classifier before its consumers and before the drawing states (T018 before T020-T030 and T079).
`top_n` before the grouped view and the check tabs' tests (T044 before T048 and T055). The words file and the `Words` model in one
commit. Each replay gate after its story's last lane merges, on `main`, in merge order, each
regeneration a commit of its own, with a freeze: from a story's last merge until its gate commit, no
other change that moves what the model reads merges, so the gate commit follows that story's merges
with no such change between them, and lane S merges a later story's model-read change only after the
earlier story's gate (`contracts/tokens.md` section 5). Lever 14's adoption only by its own commit after the replay decides. The C# protocol
constants and the Python ones in one commit.

**Sequencing against other features.** 013 needs 008 to 011 on main, which they are. Feature 004's
seat lanes touch `BridgeDispatcher.cs` and `ToolServiceHost.cs`; 013 lane D's `BridgeDispatcher.cs`
edit is confined to `PingResult`, `Ping()` and `IConfirmedDrawingSource` (T073), its test cases go
into `BridgeDispatcherTests.cs` and `ToolServiceWiringTests.cs` (T072), which 004 lane D owns, and
T072 and T073 land in one commit that 004 lane D rebases over. Across features the lanes are named
"013 lane D" (drawings) and "004 lane D" (the bridge); 013 lane U and 004 lane U are the same probe
watchdog change (004 T171). `remodel/nodes.py` keeps its public names (lane T), so 004's planner is untouched.
The replay fixtures are shared by every feature: only the replay gate regenerates them.

## Lanes and file ownership

A task that edits a file is done by the lane that owns the file; tasks.md notes each task's lane.

| Lane | Owns | Tags |
|---|---|---|
| P - profile and part roles | `checks/standards/{profile,library,traversal}.py`, `checks/part_roles.py`, `checks/hygiene.py`, `checks/rms/assembly.py` and the assembly rules, `tools/rms_checks.py`, `tools/checks_mechanical.py`, `prerun.py`, `carry_over.py`, `cli.py`, `config/standards.example.yaml`, `tests/fixtures/standards/` | [py] |
| R - report | `report/{attention,attention_record,finding_groups,summary,markdown,explanations,sources,titles,snapshot}.py`, `report/review_words_v1.yaml` | [py] |
| S - session, tools, prompt, runner | `report/session.py`, `findings.py`, `tools/{session,context,registry}.py`, `checks/{questions,provenance}.py`, `agent/{checklist.py,checklist_v1.yaml,package_brief.py,runner.py}`, `agent/prompts/system_v1.md` | [py] |
| D - drawings | `checks/drawing_context.py`, `drawings/{evidence,brief}.py`, `tools/drawings.py`, `bridge/{client.py,PROTOCOL.md}`; C# `Bridge/BridgeDispatcher.cs`, `Bridge/BridgeProtocol.cs`, `Dump/ConfirmedDrawingRead.cs`, `Sw/DrawingOpenScope.cs`, `Dump/PackageAppender.cs`, `Console/Serve/PROTOCOL.md` | [py], [C#] |
| W - pane pages | `Review/ReviewPage/*`, `web/shared/{attention,check-page}.js`, their `SwReview.AddIn.Tests` | [page] |
| X - extractor readings | `Dump/{DrawingDumper,SwDrawingReader,SwOpenDrawingReader,ManifestBuilder}.cs`, `Console/Program.cs` (comment), `checks/standards/drawing.py` | [C#], [py] |
| T - tree reading | `checks/feature_nodes.py`, `remodel/nodes.py`, `checks/rms/part.py`, `checks/standards/part.py` | [py] |
| E - efficiency | `agent/settings.py`, `agent/providers/openai_provider.py`, `benchmark/replay*.py`, `specs/005-llm-efficiency/contracts/levers.md` | [py] |
| U - test debt | `Rms/RemodelProbe{Watchdog,Executors,}.cs`, their tests and fakes; T137 also edits test-plan step 5.6 and its pin in `test_workstation_test_plan.py`, one edit each, in that task | [C#] |
| G - replay gate | `tests/fixtures/replay/*`, `tests/fixtures/pane/*` except the pane drawing fixture, `specs/008-checks-first-review/contracts/replay.md` section 9. The pane drawing fixture (`tests/fixtures/pane/generate_drawing_questions.py` and `Fixtures/review-drawing-questions.json`) is regenerated by lane R in T093, a commit of its own after T093's code and after US4's lane D and S tasks are on `main`: it plays a scripted fictional review, not a recording, and its content is the summary's drawings words T093 changes, so no replay gate regenerates it (added on review, 2026-09-26) | [py] |

Generated goldens and their order (added on review, 2026-09-26): `reviewer/tests/golden/test_golden/*.yml`
are generated whole, and four tasks in four lanes move them - T014 (P, the standards goldens'
profile sha256 lines), T060 (S, the provenance row), T129 (X, the standards goldens re-pinned) and
T133 (T, the feature 001 to 003 goldens) - plus T127 (X) where a golden there pins a drawing view
id. They regenerate in that order, T014, T060, T129 (with T127), T133, each as a regeneration commit
of its own on `main`, made from the code on `main` after rebasing over the previous one; no lane
merges another lane's regenerated golden, and no two of them regenerate in parallel.

Hot files and their order: `agent/runner.py` (S: T022 roles attach, T032 question, T038 regrade,
T060 provenance, T064 finalization reason, T089 outcome lines, T108 basis marker, T113
`keep_explained`, T117 close-out, in that order); `tools/session.py` (S: T032, T062, T064, T087, T097,
T119); `report/summary.py` and the words file (R: T034, T046, T048, T050, T093, T101, T106);
`render.js` and `app.js` (W: T036, T040, T054, T104, T110, T114).

## Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | A custom part classed bought hides real defects | Every skip named in coverage and the summary; explicit profile rules; unclear parts graded; the root always graded; an unknown id graded; the upgrade helper proposes only |
| RK-2 | A misconfigured profile asks about every part | The zero-match guard; the no-profile state asks nothing |
| RK-3 | A regrade leaves the page or the guard inconsistent (the first finding ever to leave a session) | `finding.withdrawn` with page handling; the reconcile keeps ids; lever 13's withheld set and the guard's ledger tested across a regrade |
| RK-4 | The grouped list is slow or long on the big assembly | One-line rows, collapsible groups, Modelling practice collapsed; the 1,000-finding render re-measured |
| RK-5 | The guard refuses a genuinely new question | The subset rule on exact ids; a question with no checklist item and no ids is never covered; a code-written request covers only itself (R2.22, revised on review); the note tells the model how to ask differently (name the specific entity) |
| RK-6 | The capability and the host disagree | Read from the object that answers `drawing.read`; absent means unable; D14 at the seat |
| RK-7 | Replay drift from many prompt and result changes | One gate per story, serialized; the drift rule for the recordings; every moved figure recorded with its reason |
| RK-8 | Lever 14 weakens cross-turn coherence | Off by default; adopted only on the replay's no-loss and cut; recorded either way |
| RK-9 | The sheet-view reader reads a wrong view or a controlled title block's notes | Index, type and name confirmed; a mismatch falls back with a gap; seat validation on known drawings (phase W) before its tables are trusted |
| RK-10 | Moving the tree reading changes findings the carried-finding comparison holds | Regenerated fixtures; 008 T128 and T129's comparisons re-read; the planner byte-identical |
| RK-11 | A company value leaks into an example | FICT values only; the census and the guard run in the gate; reasons never quote a profile value |

## Complexity Tracking

None. No constitution exception, no new tool, no new transport. The new modules each replace a
duplicated or missing reading (one classifier, one grouped view, one basis rule, one tree reading,
one question shape).
