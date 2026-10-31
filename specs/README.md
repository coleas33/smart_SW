# Feature specifications

Each feature of the product is specified, planned and built with
[Spec Kit](https://github.com/github/spec-kit), one folder per feature under `specs/NNN-name/`.
This page lists them with a status derived from each feature's own `tasks.md`.

## How a feature is written

The project's constitution, [`.specify/memory/constitution.md`](../.specify/memory/constitution.md),
governs every feature and supersedes everything here. Its "Development Workflow" sets the cycle:
constitution, specify, plan, tasks, implement, converge. The spec says what and why; the plan
decides how and checks itself against the constitution; the tasks put the work in order. Work is
test first: every behaviour change starts with a failing test, named in its task (constitution
Principle III).

Read a feature's files in this order:

1. `spec.md` - what the feature does and why: user stories, requirements (FR-), success criteria
   (SC-), and the owner's decisions that shaped it.
2. `plan.md` - how it is built, its Constitution Check and its risks.
3. `research.md` - why each choice was made; owner decisions (`NNA`, see the
   [decision log](../docs/decisions.md)) and defaults are recorded here.
4. `data-model.md` and `contracts/` - the exact shapes and behaviours the code is held to.
5. `tasks.md` - the ordered work, each task ticked only when its acceptance holds.
6. `quickstart.md` - how to run and validate the feature.

Feature 016 is shaped differently: `spec.md`, `plan.md`, `tasks.md`, `quickstart.md`,
`contracts/`, and its gate records `validation.md`, `native-entry.md` and
`offline-gate-native-entry.md`; it has no `research.md` or `data-model.md`.

## Task tags

Some `tasks.md` files mark tasks that cannot run on a development machine:

| Tag | Meaning | Defined in |
|---|---|---|
| `[W]` | Needs the pilot workstation: SOLIDWORKS 2024 SP5, the add-in registered, a real document open. | [005 tasks.md](005-llm-efficiency/tasks.md), "Format" |
| `[K]` | Needs a live provider key and spends real money. | [005 tasks.md](005-llm-efficiency/tasks.md), "Format" |
| `[paid]` | Needs an OpenAI or Gemini key on the paid machine and spends money (feature 014). | [014 tasks.md](014-design-review-eval/tasks.md), "Format" |
| `[O]` | Waits on an answer only the owner can give (feature 011). | [011 tasks.md](011-drawing-context/tasks.md), "Format" |

Features 003 and 004 also mark a workstation task as one whose text, after its tags, begins
`Workstation`, and 004 T303 carries both marks. The workstation tasks of 001, 002 and 016 said so
only in their text until 2026-10-31, when they were tagged `[W]` (decision 166A).
`reviewer/tests/support/seat_tasks.py` reads both marks in every feature, and the workstation
test plan's pins hold every open task so marked to a place in the plan.

## Features and their status

The counts are the `- [x]` and `- [ ]` lines of each `tasks.md` (every such line is a numbered
task), taken at commit `9da0057` and updated for decision 127A of 2026-10-18. An unticked task
whose description begins `SUPERSEDED (127A):` is counted as superseded, not open: it will not
run, because a later decision replaced it, and its text links to that decision (feature 005's
lever 5 and 6 tasks). "Code complete" means every open task needs the pilot workstation, a key,
a paid run or the owner; it does not mean the feature has been validated on the seat. Each
`spec.md`'s Status line starts with the status below, in the same words with the task lists left
here, then "Drafted as:" and the status it was written with (most say "Draft"; 016's
"implementation authorized 2026-10-14") (decision 127A). The status comes from the tasks, not
from the drafting status.

| No. | Feature | Purpose | Done / open / superseded | Status | Documents |
|---|---|---|---|---|---|
| 001 | Agentic design review | An assistant that investigates assemblies and drawings, gathers engineering evidence, and reports verifiable fit-up, tolerance, fastener and drawing findings. | 99 / 6 / 0 | Built; 6 open: benchmark packages and the pilot set (T044, T098, T099), workstation runs (T061, T076), and the end-to-end quickstart run (T103). | [spec](001-agentic-design-review/spec.md), [plan](001-agentic-design-review/plan.md), [tasks](001-agentic-design-review/tasks.md), [quickstart](001-agentic-design-review/quickstart.md) |
| 002 | Task Pane assistant | A SOLIDWORKS Task Pane with a review chat driving the reviewer, plus an embedded CLI terminal for read-only general chat (its Ask tab is built but hidden since 2026-09-19). | 71 / 5 / 0 | Built; 5 open: workstation and credential runs (T044, T051, T067, the last partly done), and the Gemini terminal, deferred (T055a, T063). | [spec](002-task-pane-assistant/spec.md), [plan](002-task-pane-assistant/plan.md), [tasks](002-task-pane-assistant/tasks.md), [quickstart](002-task-pane-assistant/quickstart.md) |
| 003 | Resilient Modeling checks | The Resilient Modeling Strategy rules as deterministic findings, an engineer-run suppressibility test, and the Model check tab. | 89 / 3 / 0 | Code complete; 3 workstation tasks open (T062, T088, T089). T088's PROBE-15 also blocks feature 004. | [spec](003-resilient-modeling/spec.md), [plan](003-resilient-modeling/plan.md), [tasks](003-resilient-modeling/tasks.md), [quickstart](003-resilient-modeling/quickstart.md) |
| 004 | Resilient re-modeler | Given one part, produce a copy that is measurably more resilient under the Resilient Modeling Strategy, with the geometry proven unchanged. | 178 / 21 / 0 | Stage 1 built; Start ships switched off (T172); the owner signed the go on 2026-10-18 (decision 127A), retroactively, after phases 2 to 9 were built. 21 open: the real-part dry run T003, and T004, which stays open until T003's numbers are in [phase0-decision.md](004-resilient-remodeler/phase0-decision.md), seat probes T033 to T039, workstation runs T135 to T141 and T164, the PROBE-8 follow-up T187, and three review follow-ups not built (T180, T182, T188). | [spec](004-resilient-remodeler/spec.md), [plan](004-resilient-remodeler/plan.md), [tasks](004-resilient-remodeler/tasks.md), [quickstart](004-resilient-remodeler/quickstart.md) |
| 005 | LLM efficiency | Instrument token use and speed, then try each efficiency lever behind a flag, default off, adopted only on measured evidence. | 74 / 35 / 4 | Instrumentation and lever flags built; measurement open. 35 open: live-key probes (T025 to T030, T036), the `rms-part` workstation build (T034), the pilot set (T035), the A/B runs and adoption decisions of levers 2, 3, 4 and 7 (13 tasks, T050 to T085), the workstation harness and levers 9 to 11 (12 tasks, T085a to T109), and lever 12's standing practice (T110). 4 superseded (decision 127A): levers 5 and 6 became pane defaults on 2026-09-22 through feature 008's replay gate instead ([ADR 0006](../docs/adr/0006-checks-first-and-token-budget.md)), so their A/B runs and adoption decisions (T073, T074, T078, T079) will not run. | [spec](005-llm-efficiency/spec.md), [plan](005-llm-efficiency/plan.md), [tasks](005-llm-efficiency/tasks.md), [quickstart](005-llm-efficiency/quickstart.md) |
| 006 | Standards check | The release-checklist checks run automatically, in a separate Standards Check tab. | 101 / 11 / 0 | Code complete; 11 workstation tasks open (T100 to T110: the real profile, probes 1 to 10, scenarios 7 to 12). | [spec](006-standards-check/spec.md), [plan](006-standards-check/plan.md), [tasks](006-standards-check/tasks.md), [quickstart](006-standards-check/quickstart.md) |
| 007 | Attention policy and procedural gate | Rank which findings the engineer reads first, and let the model start where the procedural checks stopped. | 58 / 5 / 0 | Code complete; 5 workstation tasks open (T059 to T063), three of them needing a key. | [spec](007-attention-policy-gate/spec.md), [plan](007-attention-policy-gate/plan.md), [tasks](007-attention-policy-gate/tasks.md), [quickstart](007-attention-policy-gate/quickstart.md) |
| 008 | Checks-first review and the token budget | Code runs every check it can before the model's first turn, and an offline replay prices a review before anyone pays for it. | 123 / 6 / 0 | Code complete; 6 workstation tasks open (T101 to T106), four needing a key; T106 needs a Gemini key. | [spec](008-checks-first-review/spec.md), [plan](008-checks-first-review/plan.md), [tasks](008-checks-first-review/tasks.md), [quickstart](008-checks-first-review/quickstart.md) |
| 009 | The engineer's workspace | The Review tab's summary, questions and kept reviews, so a non-developer gets the critical details fast. | 80 / 7 / 0 | Code complete; 7 workstation tasks open (T079 to T085). | [spec](009-engineer-workspace/spec.md), [plan](009-engineer-workspace/plan.md), [tasks](009-engineer-workspace/tasks.md), [quickstart](009-engineer-workspace/quickstart.md) |
| 010 | Automatic mechanical checks | Interference, thread engagement, hole alignment, tool access, mass and hygiene checks run in code; amended 2026-10-08 with the fine-pitch thread check. | 119 / 7 / 0 | Code complete; 7 workstation tasks open (T103 to T107, T123, T124). | [spec](010-mechanical-checks/spec.md), [plan](010-mechanical-checks/plan.md), [tasks](010-mechanical-checks/tasks.md), [quickstart](010-mechanical-checks/quickstart.md) |
| 011 | Drawing context, read only | Drawings as read-only context: open drawings attached to a review, their dimensions, tolerances, notes and tables read, and a per-part drawing brief. | 91 / 11 / 0 | Code complete; 10 workstation tasks open (T062 to T068, T077, T095, T101) and one owner task (T061: evaluate the drawing-creation base repository, not yet provided). Both drawing switches ship off. | [spec](011-drawing-context/spec.md), [plan](011-drawing-context/plan.md), [tasks](011-drawing-context/tasks.md), [quickstart](011-drawing-context/quickstart.md) |
| 012 | Drawing creation | Reserved; no folder. | - | Reserved. The number is kept for drawing creation, layer 3's second stage. No feature package exists yet; the [D0 inventory](../docs/drawing-creation-d0-inventory.md) (first phase 2026-10-18) comes before it is specified, and creation needs a constitution amendment first ([roadmap](../docs/future-capabilities-roadmap-2026-10-14.md), [ADR 0001](../docs/adr/0001-agentic-review-architecture.md) "Amendment 2026-09-22"). | - |
| 013 | Engineer-first review | Fixes from the 2026-09-26 sitting: bought parts out of the grading, every finding grouped by type, no question the review can answer itself, drawing offers the seat can honour. | 154 / 5 / 0 | Code complete; 5 workstation tasks open (T141 to T144, T153). | [spec](013-engineer-first-review/spec.md), [plan](013-engineer-first-review/plan.md), [tasks](013-engineer-first-review/tasks.md), [quickstart](013-engineer-first-review/quickstart.md) |
| 014 | Design-review eval | Fix the benchmark's scorer and build the cases, report and verdict for a study of the Task Pane's defaults against all levers off; its headline is recall on defects only the model can find, plus false alarms. | 242 / 24 / 0 | Offline work complete through slice 8's offline gate (T243). 24 open: the seat's smoke review T221, the paid runs T244, T245, T260 and T265, and 19 tasks that follow them (T246 to T259, T261 to T264, T266). | [spec](014-design-review-eval/spec.md), [plan](014-design-review-eval/plan.md), [tasks](014-design-review-eval/tasks.md), [quickstart](014-design-review-eval/quickstart.md) |
| 015 | Review send gate | A checkbox, ticked by default, that lets an engineer run the code checks without sending anything to the model until they press Send. | 118 / 1 / 0 | Code complete, merged to `main` (owner decision 99A); 1 workstation task open (T119). | [spec](015-review-send-gate/spec.md), [plan](015-review-send-gate/plan.md), [tasks](015-review-send-gate/tasks.md), [quickstart](015-review-send-gate/quickstart.md) |
| 016 | Engineering context | Requirements and applied forces attached to a saved part, occurrence or face, confirmed by the engineer and given to a review as read-only context. | 25 / 2 / 0 | Offline delivery and pane entry complete; 2 workstation tasks open (T010, T015: native selection and freshness). | [spec](016-engineering-context/spec.md), [plan](016-engineering-context/plan.md), [tasks](016-engineering-context/tasks.md), [quickstart](016-engineering-context/quickstart.md) |

## Where to go next

- The [decision log](../docs/decisions.md) indexes the owner's numbered decisions and the
  architecture decision records.
- The [architecture overview](../docs/architecture.md) and the [glossary](../docs/glossary.md)
  explain the parts and the terms these specs use.
- The workstation tasks are gathered into one test plan, run in short sittings (S1 first,
  decision 167A), in
  [`docs/test-plan-2026-09-27/`](../docs/test-plan-2026-09-27/workstation-test-plan.md).
