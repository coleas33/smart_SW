# Decision log

This page indexes the decisions that shape the project: the owner's numbered decisions, taken
while features were specified, planned, built and reviewed, and points to the architecture
decision records (ADRs), whose own index is [`docs/adr/README.md`](adr/README.md). It points to
where each decision is recorded; the recorded text is authoritative, and this index only names
it.

## What an owner decision is

An owner decision answers a numbered question put to the project owner, usually with lettered
options and the recommended option first. Its id is the question's number followed by the letter
of the option the owner took: `112A` is question 112, option A. A letter other than A means the
owner chose another option (`11B`); the letters of options not taken (`31B`, `33C`, `50B`) appear
beside some decisions as the alternatives. Feature 014 describes the form in
[`specs/014-design-review-eval/research.md`](../specs/014-design-review-eval/research.md#1-owner-decisions-log),
"§1 Owner decisions log", and feature 015 in
[`specs/015-review-send-gate/research.md`](../specs/015-review-send-gate/research.md#r7-owner-decisions-of-the-plan-review-2026-10-09),
R7.

Decisions are recorded in the feature they bind: mostly in its `research.md` (often under a
heading that starts with the id), and sometimes in `spec.md`, `tasks.md`, a contract or the
workstation test plan. Defaults ("default taken ..., the owner may revise", or the numbered `Dnn`
defaults of features 010 and 014) are not owner decisions and are not listed here.

## How the numbers run

The numbers are **not** one sequence for the whole project. The repository shows three runs, and
the same id can therefore name different decisions:

1. **2026-09-23 to 2026-09-25**: 2A to 25A, in features 003, 004, 008, 009 and 011 and the seat
   test plan. Ids 1A, 5A to 8A, 12A and 19A of this run appear nowhere in the tracked tree, and question 11
   was answered B (11B).
2. **2026-09-28 to 2026-10-17**: 1A to 120A. The run starts at feature 014's interview of
   2026-09-28 and continues **across features** 010, 014, 015 and 016: feature 014 records under
   81A that "the owner's decisions are numbered across features", and feature 015 under R8 that
   87A to 90A are "the next numbers no branch uses". Ids 42A, 43A, 45A, 46A and 49A appear nowhere
   in the tracked tree. Number order is date order with one exception: 94A is dated 2026-10-15,
   95A and 96A 2026-10-14.
3. **2026-10-18**: 2A, 3A and 4A, first given in commit messages and recorded on this page
   from now on (repository housekeeping, below).

Ids 2A, 3A, 4A, 9A, 10A, 13A to 18A and 20A to 25A each name two different decisions, one in
run 1 and one in run 2; 2A, 3A and 4A name a third in run 3. Cite a decision with its feature
and date, not by its id alone.

The tables below follow the runs: one table per run, in number order. A single table sorted by id
would put unrelated decisions that share an id side by side; within run 2, number order is
already date order, and the Feature column shows where each decision applies.

## Run 1: 2026-09-23 to 2026-09-25

| Id | Date | Feature | Decision | Recorded in |
|---|---|---|---|---|
| 2A | 2026-09-23 | 009 | Display titles: "Whole, named titles where a person reads them; the model's title stays" (`Finding.title` keeps the recorded title). | [009 research.md: R2.28 Whole, named titles where a person reads them; the...](../specs/009-engineer-workspace/research.md#r228-whole-named-titles-where-a-person-reads-them-the-models-title-stays-owner-decision-2a) |
| 3A | 2026-09-23 | 008 | "The replay fixtures follow the code": a deliberate change regenerates the three replay fixtures with the generator, never by hand; the 1% bar stays. | [008 research.md: Amendment 2026-09-23 (owner decision 3A): the replay fixt...](../specs/008-checks-first-review/research.md#amendment-2026-09-23-owner-decision-3a-the-replay-fixtures-follow-the-code) |
| 4A | 2026-09-23 | 004 | "The remodel run's adapter is built by the same body as the review's": `remodel/runner.py::build_provider` delegates to `cli.provider_factory`. | [004 research.md: R7. The LLM phase and its tools](../specs/004-resilient-remodeler/research.md#r7-the-llm-phase-and-its-tools) |
| 9A | 2026-09-23 | 008 (also 005, 011) | `ARRAY_CEILING` "is asserted only on the tool arrays the pane sends by default"; every other array a review can send is pinned for both providers and not asserted. | [008 research.md: Amendment 2026-09-23 (owner decision 9A): what the array...](../specs/008-checks-first-review/research.md#amendment-2026-09-23-owner-decision-9a-what-the-array-ceiling-holds) |
| 10A | 2026-09-23 | 009, 011 | "The Review tab's summary shows one line about drawings": the drawings read and the same-name drawings found but not open. | [009 contracts/review-summary.md: 4. The other lines](../specs/009-engineer-workspace/contracts/review-summary.md#4-the-other-lines) |
| 11B | 2026-09-24 | 008 (whole repository) | "The design numbers leave the tree": the recorded assemblies' design numbers appear in no tracked file; a test checks it against the owner's denylist. | [008 contracts/replay.md: 8. The fixtures](../specs/008-checks-first-review/contracts/replay.md#8-the-fixtures) |
| 13A | 2026-09-24 | 008 (whole repository) | "No design's number or folder name stays in the tree": extends 11B to every design, with a second, hand-written identifier list kept outside the repository. | [008 contracts/replay.md: 8. The fixtures](../specs/008-checks-first-review/contracts/replay.md#8-the-fixtures) |
| 14A | 2026-09-24 | seat sitting | When a **Before this review** panel appears: "write down its first line, press **Review available evidence**, and never resolve or unsuppress a part". | [docs/test-plan-2026-09-27/workstation-test-plan.md: 0.1 What the owner brings, and decides](../docs/test-plan-2026-09-27/workstation-test-plan.md#01-what-the-owner-brings-and-decides) |
| 15A | 2026-09-24 | 006, 007 (seat sitting) | Four earlier seat tasks join the sitting: 006 T101 and T102, 007 T059 and T060. | [docs/test-plan-2026-09-27/workstation-test-plan.md: Workstation test plan: the sitting for features 008 to 011](../docs/test-plan-2026-09-27/workstation-test-plan.md#workstation-test-plan-the-sitting-for-features-008-to-011) |
| 16A | 2026-09-24 | whole repository | "Puts people on the same list: the owner's surname and every Windows username the tree once carried". Recorded only in a test's docstring. | [test_tracked_files_carry_no_recorded_number.py](../reviewer/tests/unit/test_tracked_files_carry_no_recorded_number.py) |
| 17A | 2026-09-25 | 004 | Work found on three real packages: a provisional T003 (T148), the FeatureWorks correction (T149), planner fixes (T142 to T147, T162), FeatureWorks and import-repair members refused by `ReadOnlyGuard` (T150, T151), and the production seat adapter tracked (T152 to T160). | [004 contracts/guard-allowlist.md: Denials added after stage 1](../specs/004-resilient-remodeler/contracts/guard-allowlist.md#denials-added-after-stage-1) |
| 18A | 2026-09-25 | 004 (seat sitting) | Three 004 items join the sitting: the FeatureWorks record (T164), the packages T003 reads, and the probes T033 to T039. | [docs/test-plan-2026-09-27/workstation-test-plan.md: Workstation test plan: the sitting for features 008 to 011](../docs/test-plan-2026-09-27/workstation-test-plan.md#workstation-test-plan-the-sitting-for-features-008-to-011) |
| 20A | 2026-09-25 | 003 | "The system rows of the real dumps are not content": eleven system types move into `tolerated_loose`. | [003 tasks.md: Decision 20A (owner, 2026-09-25): the system rows of the...](../specs/003-resilient-modeling/tasks.md#decision-20a-owner-2026-09-25-the-system-rows-of-the-real-dumps-are-not-content) |
| 21A | 2026-09-25 | 004 | "The creation family is closed in `ReadOnlyGuard`". | [004 research.md: R5.11 Decision 21A: the creation family is closed in Read...](../specs/004-resilient-remodeler/research.md#r511-decision-21a-the-creation-family-is-closed-in-readonlyguard-owner-2026-09-25) |
| 22A | 2026-09-25 | 004 | "A plan does not survive a tool-service re-attach": Start is refused by name (`SessionLost`) rather than carrying the session across. | [004 research.md: R9. The pane: tab 5, Remodel](../specs/004-resilient-remodeler/research.md#r9-the-pane-tab-5-remodel) |
| 23A | 2026-09-25 | 008 (answers 003's question 20A-Q1) | A recorded `rms.*` finding that lost only subjects the type table stopped counting is "narrowed, not lost". | [008 research.md: Amendment 2026-09-25 (owner decision 23A): a recorded RMS...](../specs/008-checks-first-review/research.md#amendment-2026-09-25-owner-decision-23a-a-recorded-rms-finding-the-type-table-narrowed) |
| 24A | 2026-09-25 | 004 | "The page is told when a plan is lost": the host posts `remodel.plan_lost`; `SessionLost` stays the backstop. | [004 contracts/pane-remodel-messages.md: The page is told when a plan is lost (decision 24A)](../specs/004-resilient-remodeler/contracts/pane-remodel-messages.md#the-page-is-told-when-a-plan-is-lost-decision-24a) |
| 25A | 2026-09-25 | 008 | The replay compares drawing locations by "exact references": a swapped subject is lost and the new one added. | [008 contracts/replay.md: 5. The finding comparison](../specs/008-checks-first-review/contracts/replay.md#5-the-finding-comparison) |

## Run 2: 2026-09-28 to 2026-10-17

Decisions 1A to 12A were taken in feature 014's eval interview, 13A to 30A from its spec and plan
reviews, and 31A to 36A in the owner's review of its plan (014 `research.md` §1). Feature 014's
`spec.md` also lists 1A to 56A in one table, "Owner Decisions", with the refinements between them.

| Id | Date | Feature | Decision | Recorded in |
|---|---|---|---|---|
| 1A | 2026-09-28 | 014 | "The eval stays on the product's providers, OpenAI (default) and Gemini. Any future judge is OpenAI or Gemini, never Claude." | [014 research.md: 1A. Providers (2026-09-28)](../specs/014-design-review-eval/research.md#1a-providers-2026-09-28) |
| 2A | 2026-09-28 | 014 | "The flow under evaluation is the agentic design review of a package, graded against answer keys." | [014 research.md: 2A. The flow under evaluation (2026-09-28)](../specs/014-design-review-eval/research.md#2a-the-flow-under-evaluation-2026-09-28) |
| 3A | 2026-09-28 | 014 | "The first study is the Task Pane defaults against all levers off." Headline: recall on defects only the model can find, plus false alarms. | [014 research.md: 3A. The first study and its headline (2026-09-28)](../specs/014-design-review-eval/research.md#3a-the-first-study-and-its-headline-2026-09-28) |
| 4A | 2026-09-28 | 014 | "The benchmark scorer is fixed in place, tests first." | [014 research.md: 4A. The scorer (2026-09-28)](../specs/014-design-review-eval/research.md#4a-the-scorer-2026-09-28) |
| 5A | 2026-09-28 | 014 | Cases are "a committed seeded-case generator plus a private held-out slice of real designs", kept outside the repository. | [014 research.md: 5A. Where the cases come from (2026-09-28)](../specs/014-design-review-eval/research.md#5a-where-the-cases-come-from-2026-09-28) |
| 6A | 2026-09-28 | 014 | "`benchmark run` can run the pane's configuration through the resolver `review` already uses, and records it." | [014 research.md: 6A. Parity with the pane (2026-09-28)](../specs/014-design-review-eval/research.md#6a-parity-with-the-pane-2026-09-28) |
| 7A | 2026-09-28 | 014 | "The anchors are the eight real cases R-1 to R-8", plus the big assembly's three analyst-found defects. | [014 research.md: 7A. The anchors (2026-09-28)](../specs/014-design-review-eval/research.md#7a-the-anchors-2026-09-28) |
| 8A | 2026-09-28 | 014 | The answer key also grades forbidden findings, expected coverage and question rules, "all by code, with no judge". | [014 research.md: 8A. What the key grades beyond matched defects (2026-09-28)](../specs/014-design-review-eval/research.md#8a-what-the-key-grades-beyond-matched-defects-2026-09-28) |
| 9A | 2026-09-28 | 014 | "Cases carry scripted engineer answers, played through the answer path the pane uses." | [014 research.md: 9A. Scripted answers (2026-09-28)](../specs/014-design-review-eval/research.md#9a-scripted-answers-2026-09-28) |
| 10A | 2026-09-28 | 014 | "The set must detect a 10-point drop in model-judgement recall: about 34 held-out model-produced defects at 3 repetitions." | [014 research.md: 10A. Set size (2026-09-28)](../specs/014-design-review-eval/research.md#10a-set-size-2026-09-28) |
| 11A | 2026-09-28 | 014 | "The planning pass's 23 lower-level choices take their recommended defaults (research §4)." | [014 research.md: 11A. The 23 planning choices (2026-09-28)](../specs/014-design-review-eval/research.md#11a-the-23-planning-choices-2026-09-28) |
| 12A | 2026-09-28 | 014 | Delivery order: "the scorer, then parity with the pane, then the key extensions and scripted answers, then the generator, the report and runner robustness". | [014 research.md: 12A. Delivery (2026-09-28)](../specs/014-design-review-eval/research.md#12a-delivery-2026-09-28) |
| 13A | 2026-09-29 | 014 | "Every known defect states its expected status"; an unresolved finding on a defect expected demonstrated or suspected is *flagged below expected* and outside headline recall. | [014 research.md: 13A. An unresolved finding on a defect expected demonstra...](../specs/014-design-review-eval/research.md#13a-an-unresolved-finding-on-a-defect-expected-demonstrated-or-suspected-2026-09-29) |
| 14A | 2026-09-29 | 014 | "34 held-out model-produced defects is the floor, not the plan": a paid pilot of the off arm first, and the owner approves size and cost at the cost gate. | [014 research.md: 14A. Set size and repetitions (2026-09-29)](../specs/014-design-review-eval/research.md#14a-set-size-and-repetitions-2026-09-29) |
| 15A | 2026-09-29 | 014 | "Held out is decided per graded item"; anything the prompt or checklist was written around is *tuned-on*. | [014 research.md: 15A. Held out is decided per graded item (2026-09-29)](../specs/014-design-review-eval/research.md#15a-held-out-is-decided-per-graded-item-2026-09-29) |
| 16A | 2026-09-29 | 014 | "Producer is decided per defect, in its own package." | [014 research.md: 16A. Who produces a defect (2026-09-29)](../specs/014-design-review-eval/research.md#16a-who-produces-a-defect-2026-09-29) |
| 17A | 2026-09-29 | 014 | "Only model-origin false alarms decide the pane study's verdict". | [014 research.md: 17A. False alarms that decide (2026-09-29)](../specs/014-design-review-eval/research.md#17a-false-alarms-that-decide-2026-09-29) |
| 18A | 2026-09-29 | 014 | The fit and axial-stack call-count guard "is shown with a paired interval ... but never decides". | [014 research.md: 18A. The fit and axial-stack call counts (2026-09-29)](../specs/014-design-review-eval/research.md#18a-the-fit-and-axial-stack-call-counts-2026-09-29) |
| 19A | 2026-09-29 | 014 (product change) | "Every fastener-joint and hole-alignment result records its fastener and hole ids (the joint's references) on every path". | [014 research.md: 19A. Joint references on every path (2026-09-29)](../specs/014-design-review-eval/research.md#19a-joint-references-on-every-path-2026-09-29) |
| 20A | 2026-09-29 | 014 | "A call of a tool the pre-run also calls, or of a check with no arguments, is code origin whoever makes it". | [014 research.md: 20A. A code-only call is code origin (2026-09-29)](../specs/014-design-review-eval/research.md#20a-a-code-only-call-is-code-origin-2026-09-29) |
| 21A | 2026-09-29 | 014 | "Identical arms" for the 5% bound: the model behaves the same in both arms while code-produced defects behave as each configuration does. | [014 research.md: 21A. What identical arms means (2026-09-29)](../specs/014-design-review-eval/research.md#21a-what-identical-arms-means-2026-09-29) |
| 22A | 2026-09-29 | 014 | "Repetitions grow first, up to a cap of 10, then cases." | [014 research.md: 22A. The repetition cap (2026-09-29)](../specs/014-design-review-eval/research.md#22a-the-repetition-cap-2026-09-29) |
| 23A | 2026-09-29 | 014 | "The private real-design slice is its own study", reported beside the pane study's verdict "and never deciding it". | [014 research.md: 23A. The private slice (2026-09-29)](../specs/014-design-review-eval/research.md#23a-the-private-slice-2026-09-29) |
| 24A | 2026-09-29 | 014 | "One fully clean twin per core case". | [014 research.md: 24A. Clean twins (2026-09-29)](../specs/014-design-review-eval/research.md#24a-clean-twins-2026-09-29) |
| 25A | 2026-09-29 | 014 | "A held-out item's stamp digests the system prompt, the checklist and every registered tool description the model reads". | [014 research.md: 25A. The held-out stamp covers the tool descriptions (202...](../specs/014-design-review-eval/research.md#25a-the-held-out-stamp-covers-the-tool-descriptions-2026-09-29) |
| 26A | 2026-09-29 | 014 | A context-window overflow "is a behavioural stop", never an infrastructure failure. | [014 research.md: 26A. A context overflow is a behavioural stop (2026-09-29)](../specs/014-design-review-eval/research.md#26a-a-context-overflow-is-a-behavioural-stop-2026-09-29) |
| 27A | 2026-09-29 | 014 | "The paid pilot is 3 off-arm repetitions over the whole committed pane set." | [014 research.md: 27A. The paid pilot's size (2026-09-29)](../specs/014-design-review-eval/research.md#27a-the-paid-pilots-size-2026-09-29) |
| 28A | 2026-09-29 | 014 | Committed study and pilot folders carry their event streams gzip-compressed (`events.jsonl.gz`), each digest recorded. | [014 research.md: 28A. The committed event streams, compressed (2026-09-29)](../specs/014-design-review-eval/research.md#28a-the-committed-event-streams-compressed-2026-09-29) |
| 29A | 2026-09-29 | 014 | "The tasks are generated now; the owner reviews the plan and the tasks together before implementation." | [014 research.md: 29A. Tasks before the owner's plan review (2026-09-29)](../specs/014-design-review-eval/research.md#29a-tasks-before-the-owners-plan-review-2026-09-29) |
| 30A | 2026-09-30 | 014 | "Held-out core cases take no answer turn"; every verdict names dropped reasoning as a setting it does not test. | [014 research.md: 30A. Held-out cases take no answer turn (2026-09-30)](../specs/014-design-review-eval/research.md#30a-held-out-cases-take-no-answer-turn-2026-09-30) |
| 31A | 2026-10-06 | 014 | The form of the plan review: "review the plan and tasks with CLAUDE.md's procedure, then commit the documents and start Phase 3" (over 31B, skip the review, and 31C, trim the scope). | [014 research.md: §1 Owner decisions log](../specs/014-design-review-eval/research.md#1-owner-decisions-log) |
| 32A | 2026-10-06 | 014 | "SMALL CHANGE, one question per section" (over 32B, BIG CHANGE, up to four per section). | [014 research.md: §1 Owner decisions log](../specs/014-design-review-eval/research.md#1-owner-decisions-log) |
| 33A | 2026-10-06 | 014 | Slices 1, 2 and 6 re-run the add-in's tests and replay the recorded pane sessions; one smoke review on the pilot workstation (T221) before any paid run. | [014 research.md: 33A. The pane's behaviour, checked at the gates and once...](../specs/014-design-review-eval/research.md#33a-the-panes-behaviour-checked-at-the-gates-and-once-on-the-seat-2026-10-06) |
| 34A | 2026-10-06 | 014 | "One atomic writer": the product's three older atomic writes move onto the eval's writer. | [014 research.md: 34A. One atomic writer (2026-10-06)](../specs/014-design-review-eval/research.md#34a-one-atomic-writer-2026-10-06) |
| 35A | 2026-10-06 | 014 | "A paid smoke run before the pilot (quickstart P0)". | [014 research.md: 35A. A paid smoke run before the pilot (2026-10-06)](../specs/014-design-review-eval/research.md#35a-a-paid-smoke-run-before-the-pilot-2026-10-06) |
| 36A | 2026-10-06 | 014 | The cost gate prints a projected wall clock; `benchmark run --jobs N` reviews up to N packages at once. | [014 research.md: 36A. A projected wall clock and bounded concurrency (2026...](../specs/014-design-review-eval/research.md#36a-a-projected-wall-clock-and-bounded-concurrency-2026-10-06) |
| 37A | 2026-10-07 | 014 | The matcher's family rows that T022 tests read on `fastener.head.*`. | [014 research.md: 37A. T022's family rows on a family a key can hold (2026-...](../specs/014-design-review-eval/research.md#37a-t022s-family-rows-on-a-family-a-key-can-hold-2026-10-07) |
| 38A | 2026-10-07 | 014 | The event-line reader "ends a line where text mode ends it, a lone carriage return included, exactly as at `be01974`". | [014 research.md: 38A. The event reader's line ends, as at be01974 (2026-10...](../specs/014-design-review-eval/research.md#38a-the-event-readers-line-ends-as-at-be01974-2026-10-07) |
| 39A | 2026-10-07 | 014 | "The `joint-unknown-role` check golden stays at schema 1.3.0". | [014 research.md: 39A. The unknown-role golden stays at schema 1.3.0 (2026-...](../specs/014-design-review-eval/research.md#39a-the-unknown-role-golden-stays-at-schema-130-2026-10-07) |
| 40A | 2026-10-07 | 014 | "`check_interference_group` cites its own step on every finding". | [014 research.md: 40A. check_interference_group cites its own step (2026-10...](../specs/014-design-review-eval/research.md#40a-check_interference_group-cites-its-own-step-2026-10-07) |
| 41A | 2026-10-07 | 014 | T032's end-to-end test of origins takes its code-only-call findings from the same package's off arm. | [014 research.md: 41A. T032's code-only call from the off arm (2026-10-07)](../specs/014-design-review-eval/research.md#41a-t032s-code-only-call-from-the-off-arm-2026-10-07) |
| 44A | 2026-10-07 | 014 | "The too-small-set override is a must-match field of a study". | [014 research.md: 44A. The too-small-set override must match across a study...](../specs/014-design-review-eval/research.md#44a-the-too-small-set-override-must-match-across-a-study-2026-10-07) |
| 47A | 2026-10-08 | 014 | A value a record lacks reads "not recorded" only for fields whose absence can only mean an older build wrote the record. | [014 research.md: 47A. A field a record lacks, quoted not recorded (2026-10...](../specs/014-design-review-eval/research.md#47a-a-field-a-record-lacks-quoted-not-recorded-2026-10-08) |
| 48A | 2026-10-08 | 014 | "A package id equal to `attempts` in any case is refused before any review". | [014 research.md: 48A. The package id attempts, ignoring case (2026-10-08)](../specs/014-design-review-eval/research.md#48a-the-package-id-attempts-ignoring-case-2026-10-08) |
| 50A | 2026-10-08 | 010 | "ISO and UNC table": fine pitch is judged against ISO 261 coarse pitch and ASME B1.1 UNC, in one cited data file. | [010 research.md: R2.26 Fine and non-standard thread pitch is flagged for t...](../specs/010-mechanical-checks/research.md#r226-fine-and-non-standard-thread-pitch-is-flagged-for-the-engineer-to-confirm-amendment-2026-10-08-owner-decisions-50a-to-53a) |
| 51A | 2026-10-08 | 010 | "Flag all, Accept": "Every fine or non-standard thread is flagged on every review; the engineer confirms with the existing Accept disposition." | [010 research.md: R2.26 Fine and non-standard thread pitch is flagged for t...](../specs/010-mechanical-checks/research.md#r226-fine-and-non-standard-thread-pitch-is-flagged-for-the-engineer-to-confirm-amendment-2026-10-08-owner-decisions-50a-to-53a) |
| 52A | 2026-10-08 | 010 | "All model sources and the parser fixes". | [010 research.md: R2.26 Fine and non-standard thread pitch is flagged for t...](../specs/010-mechanical-checks/research.md#r226-fine-and-non-standard-thread-pitch-is-flagged-for-the-engineer-to-confirm-amendment-2026-10-08-owner-decisions-50a-to-53a) |
| 53A | 2026-10-08 | 010 | "A feature 010 amendment on a new branch". | [010 research.md: R2.26 Fine and non-standard thread pitch is flagged for t...](../specs/010-mechanical-checks/research.md#r226-fine-and-non-standard-thread-pitch-is-flagged-for-the-engineer-to-confirm-amendment-2026-10-08-owner-decisions-50a-to-53a) |
| 54A | 2026-10-08 | 014 | The case vocabulary gains the six Resilient Modeling group folders' words. | [014 research.md: 54A. The Resilient Modeling group words in the case vocab...](../specs/014-design-review-eval/research.md#54a-the-resilient-modeling-group-words-in-the-case-vocabulary-2026-10-08) |
| 55A | 2026-10-08 | 014 | "`coaxiality_undrawn` is treated like a drawing kind". | [014 research.md: 55A. coaxiality_undrawn's twin carries no correct call (2...](../specs/014-design-review-eval/research.md#55a-coaxiality_undrawns-twin-carries-no-correct-call-2026-10-08) |
| 56A | 2026-10-08 | 014 | "A generated drawing dimension may carry its nominal as the drawing writes it". | [014 research.md: 56A. A dimension's nominal as the drawing writes it (2026...](../specs/014-design-review-eval/research.md#56a-a-dimensions-nominal-as-the-drawing-writes-it-2026-10-08) |
| 57A | 2026-10-08 | 010 | "One finding per check and part." | [010 research.md: R2.26 Fine and non-standard thread pitch is flagged for t...](../specs/010-mechanical-checks/research.md#r226-fine-and-non-standard-thread-pitch-is-flagged-for-the-engineer-to-confirm-amendment-2026-10-08-owner-decisions-50a-to-53a) |
| 58A | 2026-10-08 | 010 | "A restated finding keeps its disposition." | [010 research.md: R2.26 Fine and non-standard thread pitch is flagged for t...](../specs/010-mechanical-checks/research.md#r226-fine-and-non-standard-thread-pitch-is-flagged-for-the-engineer-to-confirm-amendment-2026-10-08-owner-decisions-50a-to-53a) |
| 59A | 2026-10-08 | 015 | One checkbox, "Send to the model when the checks finish", ticked by default; unticked, Review runs the code checks only and shows a **Send to model** button. | [015 spec.md](../specs/015-review-send-gate/spec.md) |
| 60A | 2026-10-08 | 015 | The checkbox "sits on the Review tab beside the Review button"; it is remembered across sessions. | [015 spec.md](../specs/015-review-send-gate/spec.md) |
| 61A | 2026-10-08 | 015 | "Send resumes the same paused review." | [015 spec.md](../specs/015-review-send-gate/spec.md) |
| 62A | 2026-10-08 | 015 | "Delivered as new speckit feature 015 (spec, plan, tasks) on its own branch." | [015 spec.md](../specs/015-review-send-gate/spec.md) |
| 63A | 2026-10-08 | 010 | "The goal lines stay as they are." | [010 research.md: R2.26 Fine and non-standard thread pitch is flagged for t...](../specs/010-mechanical-checks/research.md#r226-fine-and-non-standard-thread-pitch-is-flagged-for-the-engineer-to-confirm-amendment-2026-10-08-owner-decisions-50a-to-53a) |
| 64A | 2026-10-09 | 014 | "A case and its twin lay the same document ids". | [014 research.md: 64A. A case and its twin lay the same document ids (2026-...](../specs/014-design-review-eval/research.md#64a-a-case-and-its-twin-lay-the-same-document-ids-2026-10-09) |
| 65A | 2026-10-09 | 014 | Test 5's second half keeps every key with no extension list and expects the condition columns not assessed when the key holds no correct condition. | [014 research.md: 65A. Test 5's second half on a key holding no correct con...](../specs/014-design-review-eval/research.md#65a-test-5s-second-half-on-a-key-holding-no-correct-condition-2026-10-09) |
| 66A | 2026-10-09 | 014 | The denylist scan of the generated cases is narrowed to what it should read; matching words are reworded, "never exempted". | [014 research.md: 66A. The denylist scan of the generated cases, and the wo...](../specs/014-design-review-eval/research.md#66a-the-denylist-scan-of-the-generated-cases-and-the-words-it-found-2026-10-09) |
| 67A | 2026-10-09 | 014 | "The committed pilot set is keyed". | [014 research.md: 67A. The committed pilot set is keyed (2026-10-09)](../specs/014-design-review-eval/research.md#67a-the-committed-pilot-set-is-keyed-2026-10-09) |
| 68A | 2026-10-09 | 015 | "Send is the only re-run trigger after a restart". | [015 research.md: 68A. Send is the only re-run trigger after a restart (202...](../specs/015-review-send-gate/research.md#68a-send-is-the-only-re-run-trigger-after-a-restart-2026-10-09) |
| 69A | 2026-10-09 | 015 | "A waiting chat's work queues on its own worker". | [015 research.md: 69A. A waiting chat's work queues on its own worker (2026...](../specs/015-review-send-gate/research.md#69a-a-waiting-chats-work-queues-on-its-own-worker-2026-10-09) |
| 70A | 2026-10-09 | 015 | "The host's wait for a checks-only start and a re-run, measured". | [015 research.md: 70A. The host's wait for a checks-only start and a re-run...](../specs/015-review-send-gate/research.md#70a-the-hosts-wait-for-a-checks-only-start-and-a-re-run-measured-2026-10-09) |
| 71A | 2026-10-09 | 015 | "One shared step per repeated tail". | [015 research.md: 71A. One shared step per repeated tail (2026-10-09)](../specs/015-review-send-gate/research.md#71a-one-shared-step-per-repeated-tail-2026-10-09) |
| 72A | 2026-10-09 | 015 | "Send and the carry reuse the owners of the state they change". | [015 research.md: 72A. Send and the carry reuse the owners of the state the...](../specs/015-review-send-gate/research.md#72a-send-and-the-carry-reuse-the-owners-of-the-state-they-change-2026-10-09) |
| 73A | 2026-10-09 | 015 | "One home for each fact outside the runner". | [015 research.md: 73A. One home for each fact outside the runner (2026-10-09)](../specs/015-review-send-gate/research.md#73a-one-home-for-each-fact-outside-the-runner-2026-10-09) |
| 74A | 2026-10-09 | 015 | "What an unticked start loads, said exactly". | [015 research.md: 74A. What an unticked start loads, said exactly (2026-10-09)](../specs/015-review-send-gate/research.md#74a-what-an-unticked-start-loads-said-exactly-2026-10-09) |
| 75A | 2026-10-09 | 015 | "The characterization of a ticked review covers its failures". | [015 research.md: 75A. The characterization of a ticked review covers its f...](../specs/015-review-send-gate/research.md#75a-the-characterization-of-a-ticked-review-covers-its-failures-2026-10-09) |
| 76A | 2026-10-09 | 015 | "One restart and crash helper for the tests". | [015 research.md: 76A. One restart and crash helper for the tests (2026-10-09)](../specs/015-review-send-gate/research.md#76a-one-restart-and-crash-helper-for-the-tests-2026-10-09) |
| 77A | 2026-10-09 | 015 | "A reload during a Send or an apply". | [015 research.md: 77A. A reload during a Send or an apply (2026-10-09)](../specs/015-review-send-gate/research.md#77a-a-reload-during-a-send-or-an-apply-2026-10-09) |
| 78A | 2026-10-09 | 015 | "The pins that could not fail for what they guard". | [015 research.md: 78A. The pins that could not fail for what they guard (20...](../specs/015-review-send-gate/research.md#78a-the-pins-that-could-not-fail-for-what-they-guard-2026-10-09) |
| 79A | 2026-10-09 | 015 | "A waiting review releases its SOLIDWORKS pipe". | [015 research.md: 79A. A waiting review releases its SOLIDWORKS pipe (2026-...](../specs/015-review-send-gate/research.md#79a-a-waiting-review-releases-its-solidworks-pipe-2026-10-09) |
| 80A | 2026-10-09 | 015 | "The found-review search, pinned by its access pattern". | [015 research.md: 80A. The found-review search, pinned by its access patter...](../specs/015-review-send-gate/research.md#80a-the-found-review-search-pinned-by-its-access-pattern-2026-10-09) |
| 81A | 2026-10-14 | 014 | "A module-level sentence may name the stream files". | [014 research.md: 81A. A module-level sentence may name the stream files (2...](../specs/014-design-review-eval/research.md#81a-a-module-level-sentence-may-name-the-stream-files-2026-10-14) |
| 82A | 2026-10-14 | 014 | "R-18 measures the report's own work". | [014 research.md: 82A. R-18 measures the report's own work (2026-10-14)](../specs/014-design-review-eval/research.md#82a-r-18-measures-the-reports-own-work-2026-10-14) |
| 83A | 2026-10-14 | 014 | "A damaged body, a failed build, and every message sent": read a damaged body as an unreadable line and build into a sibling folder swapped in once complete. | [014 research.md: 83A. A damaged body, a failed build, and every message se...](../specs/014-design-review-eval/research.md#83a-a-damaged-body-a-failed-build-and-every-message-sent-2026-10-14) |
| 84A | 2026-10-14 | 014 | "Three more refusals" in `benchmark report`, each before anything is written. | [014 research.md: 84A. Three more refusals (2026-10-14)](../specs/014-design-review-eval/research.md#84a-three-more-refusals-2026-10-14) |
| 85A | 2026-10-14 | 014 | "Literals, the two-drive refusal, a wider guard, an exact R-9 and shared rules". | [014 research.md: 85A. Literals, the two-drive refusal, a wider guard, an e...](../specs/014-design-review-eval/research.md#85a-literals-the-two-drive-refusal-a-wider-guard-an-exact-r-9-and-shared-rules-2026-10-14) |
| 86A | 2026-10-14 | 014 | "The second prompts write never hides the review's failure; an empty sum deferred". | [014 research.md: 86A. The second prompts write never hides the review's fa...](../specs/014-design-review-eval/research.md#86a-the-second-prompts-write-never-hides-the-reviews-failure-an-empty-sum-deferred-2026-10-14) |
| 87A | 2026-10-14 | 015 | "Every test gap the review found in the carry is closed now". | [015 research.md: 87A. Every test gap the review found in the carry is clos...](../specs/015-review-send-gate/research.md#87a-every-test-gap-the-review-found-in-the-carry-is-closed-now-2026-10-14) |
| 88A | 2026-10-14 | 015 | "A carry settles the waiting opening only when it carried answers or outcome lines". | [015 research.md: 88A. A carry settles the waiting opening only when it car...](../specs/015-review-send-gate/research.md#88a-a-carry-settles-the-waiting-opening-only-when-it-carried-answers-or-outcome-lines-2026-10-14) |
| 89A | 2026-10-14 | 015 | "Two earlier answers that match one question: neither is carried, both are named". | [015 research.md: 89A. Two earlier answers that match one question: neither...](../specs/015-review-send-gate/research.md#89a-two-earlier-answers-that-match-one-question-neither-is-carried-both-are-named-2026-10-14) |
| 90A | 2026-10-14 | 015 | "Four small fixes to the carry and the claim". | [015 research.md: 90A. Four small fixes to the carry and the claim (2026-10...](../specs/015-review-send-gate/research.md#90a-four-small-fixes-to-the-carry-and-the-claim-2026-10-14) |
| 91A | 2026-10-14 | 014 | "Fall back, never fail": when the finished report cannot be moved into place, build beside it and copy it in rather than fail. | [014 research.md: 91A. Fall back, never fail (2026-10-14)](../specs/014-design-review-eval/research.md#91a-fall-back-never-fail-2026-10-14) |
| 92A | 2026-10-14 | 014 | "The cheap notes, and three known limits": four fixes, three limits recorded. | [014 research.md: 92A. The cheap notes, and three known limits (2026-10-14)](../specs/014-design-review-eval/research.md#92a-the-cheap-notes-and-three-known-limits-2026-10-14) |
| 93A | 2026-10-15 | 015 | "The re-run's commit point is the atomic replace of its `session.json`". | [015 research.md: 93A. The re-run's commit point is the atomic replace of i...](../specs/015-review-send-gate/research.md#93a-the-re-runs-commit-point-is-the-atomic-replace-of-its-sessionjson-2026-10-15) |
| 94A | 2026-10-15 | 014 (see [ADR 0005](adr/0005-language-model-providers.md)) | "OpenAI only": build OpenAI's behaviour and the shared pieces, defer Gemini's specific behaviour. The owner: "We are only using openAI api key". | [014 research.md: 94A. OpenAI only (2026-10-15)](../specs/014-design-review-eval/research.md#94a-openai-only-2026-10-15) |
| 95A | 2026-10-14 | 014 | "A Python 3.11 shim", and a 3.11 run in the slice's gate. | [014 research.md: 95A. A Python 3.11 shim (2026-10-14)](../specs/014-design-review-eval/research.md#95a-a-python-311-shim-2026-10-14) |
| 96A | 2026-10-14 | 014 | "Never delete anything that is not ours". | [014 research.md: 96A. Never delete anything that is not ours (2026-10-14)](../specs/014-design-review-eval/research.md#96a-never-delete-anything-that-is-not-ours-2026-10-14) |
| 97A | 2026-10-15 | 014 | "Staging names are refused, never deleted". | [014 research.md: 97A. Staging names are refused, never deleted (2026-10-15)](../specs/014-design-review-eval/research.md#97a-staging-names-are-refused-never-deleted-2026-10-15) |
| 98A | 2026-10-15 | 015 | "Every confirmed T116 finding in 015's own code and tests is fixed now, test-first". | [015 research.md: 98A. Every confirmed T116 finding in 015's own code and t...](../specs/015-review-send-gate/research.md#98a-every-confirmed-t116-finding-in-015s-own-code-and-tests-is-fixed-now-test-first-2026-10-15) |
| 99A | 2026-10-15 | 015, 016 | "015 merges to `main` first, after 014 slice 5; 016 adapts on top of `main`". | [015 research.md: 99A. 015 merges to main first, after 014 slice 5; 016 ada...](../specs/015-review-send-gate/research.md#99a-015-merges-to-main-first-after-014-slice-5-016-adapts-on-top-of-main-2026-10-15) |
| 100A | 2026-10-15 | 015 | "The 014 slice-5 merge regenerates nothing, and one test stops reading a private helper". | [015 research.md: 100A. The 014 slice-5 merge regenerates nothing, and one...](../specs/015-review-send-gate/research.md#100a-the-014-slice-5-merge-regenerates-nothing-and-one-test-stops-reading-a-private-helper-2026-10-15) |
| 101A | 2026-10-15 | 014 | "What was moved aside, exclusive staging, and an OSError's clean-up". | [014 research.md: 101A. What was moved aside, exclusive staging, and an OSE...](../specs/014-design-review-eval/research.md#101a-what-was-moved-aside-exclusive-staging-and-an-oserrors-clean-up-2026-10-15) |
| 102A | 2026-10-15 | 014 | "The default model is priced by the variant that answers". | [014 research.md: 102A. The default model is priced by the variant that ans...](../specs/014-design-review-eval/research.md#102a-the-default-model-is-priced-by-the-variant-that-answers-2026-10-15) |
| 103A | 2026-10-15 | 014 | "A short-context price and where it stops": a round above the threshold is cost unknown. | [014 research.md: 103A. A short-context price and where it stops (2026-10-15)](../specs/014-design-review-eval/research.md#103a-a-short-context-price-and-where-it-stops-2026-10-15) |
| 104A | 2026-10-15 | 014 | "The scanner admits the scrub's placeholders". | [014 research.md: 104A. The scanner admits the scrub's placeholders (2026-1...](../specs/014-design-review-eval/research.md#104a-the-scanner-admits-the-scrubs-placeholders-2026-10-15) |
| 105A | 2026-10-15 | 016 (recorded in 015) | The carried check of a re-run "stays as built" and also requires the saved baseline's package id, root document and configuration. | [015 research.md: 105A-109A. The adversarial check of 016 on 015, and its f...](../specs/015-review-send-gate/research.md#105a-109a-the-adversarial-check-of-016-on-015-and-its-follow-ups-2026-10-15) |
| 106A | 2026-10-15 | 016 (recorded in 015) | "The strict lock stays": the context panel is disabled while any review is shown waiting. | [015 research.md: 105A-109A. The adversarial check of 016 on 015, and its f...](../specs/015-review-send-gate/research.md#105a-109a-the-adversarial-check-of-016-on-015-and-its-follow-ups-2026-10-15) |
| 107A | 2026-10-15 | 016 (recorded in 015) | Binding accepts exactly the live interference check's own rewrite of `package.json`; "any other change is still a mismatch". | [015 research.md: 105A-109A. The adversarial check of 016 on 015, and its f...](../specs/015-review-send-gate/research.md#105a-109a-the-adversarial-check-of-016-on-015-and-its-follow-ups-2026-10-15) |
| 108A | 2026-10-15 | 016 (recorded in 015) | "Retry on a failed context review re-attaches the same saved context in its own run folder". | [015 research.md: 105A-109A. The adversarial check of 016 on 015, and its f...](../specs/015-review-send-gate/research.md#105a-109a-the-adversarial-check-of-016-on-015-and-its-follow-ups-2026-10-15) |
| 109A | 2026-10-15 | 016 (recorded in 015) | "001's review-session schema accepts a finding that names its document scope in a non-empty `inputs`". | [015 research.md: 105A-109A. The adversarial check of 016 on 015, and its f...](../specs/015-review-send-gate/research.md#105a-109a-the-adversarial-check-of-016-on-015-and-its-follow-ups-2026-10-15) |
| 110A | 2026-10-16 | 014 | "The whole-slice review's fixes, without a version bump". | [014 research.md: 110A. The whole-slice review's fixes, without a version b...](../specs/014-design-review-eval/research.md#110a-the-whole-slice-reviews-fixes-without-a-version-bump-2026-10-16) |
| 111A | 2026-10-16 | 014 | "The simulator made fast before it lands", every pinned output byte-identical. | [014 research.md: 111A. The simulator made fast before it lands (2026-10-16)](../specs/014-design-review-eval/research.md#111a-the-simulator-made-fast-before-it-lands-2026-10-16) |
| 112A | 2026-10-16 | 014 | "The verdict slice's review fixes". | [014 research.md: 112A. The verdict slice's review fixes (2026-10-16)](../specs/014-design-review-eval/research.md#112a-the-verdict-slices-review-fixes-2026-10-16) |
| 113A | 2026-10-16 | 014 | "`graded_items`: an optional scorecard field without a rules bump". | [014 research.md: 113A. graded_items: an optional scorecard field without a...](../specs/014-design-review-eval/research.md#113a-graded_items-an-optional-scorecard-field-without-a-rules-bump-2026-10-16) |
| 114A | 2026-10-16 | 014 | "The slow slice 7 tests moved or shared, no check weakened". | [014 research.md: 114A. The slow slice 7 tests moved or shared, no check we...](../specs/014-design-review-eval/research.md#114a-the-slow-slice-7-tests-moved-or-shared-no-check-weakened-2026-10-16) |
| 115A | 2026-10-17 | 014 | "The co-movement estimate reads each package run's detection vector". | [014 research.md: 115A. The co-movement estimate reads each package run's d...](../specs/014-design-review-eval/research.md#115a-the-co-movement-estimate-reads-each-package-runs-detection-vector-2026-10-17) |
| 116A | 2026-10-17 | 014 | "Slice 8's offline review fixed in full". | [014 research.md: 116A. Slice 8's offline review fixed in full (2026-10-17)](../specs/014-design-review-eval/research.md#116a-slice-8s-offline-review-fixed-in-full-2026-10-17) |
| 117A | 2026-10-17 | 014 | "The measurement records whether its size was reached". | [014 research.md: 117A. The measurement records whether its size was reache...](../specs/014-design-review-eval/research.md#117a-the-measurement-records-whether-its-size-was-reached-2026-10-17) |
| 118A | 2026-10-17 | 014 | "The noise floor shares the simulator's data model". | [014 research.md: 118A. The noise floor shares the simulator's data model (...](../specs/014-design-review-eval/research.md#118a-the-noise-floor-shares-the-simulators-data-model-2026-10-17) |
| 119A | 2026-10-17 | 014 | "The private slice's noise floor is not computed". | [014 research.md: 119A. The private slice's noise floor is not computed (20...](../specs/014-design-review-eval/research.md#119a-the-private-slices-noise-floor-is-not-computed-2026-10-17) |
| 120A | 2026-10-17 | 014 | "The noise floor records what was tested". | [014 research.md: 120A. The noise floor records what was tested (2026-10-17)](../specs/014-design-review-eval/research.md#120a-the-noise-floor-records-what-was-tested-2026-10-17) |

## Run 3: 2026-10-18, repository housekeeping

These were first given only in commit messages on `main`. This page is their record from now
on: a later decision of this run is added to the table below.

| Id | Date | Subject | What the commit says | Commit |
|---|---|---|---|---|
| 2A | 2026-10-18 | CI | "main's check becomes the required one once branch protection is on (2A)"; the next commit names "the outside-the-checkout temp folder rule CI fix 2A added". | `174900b`, `dfb4eda` |
| 3A | 2026-10-18 | Documentation | Dated notes archived in `docs/history/` and the architecture proposal moved to ADR 0001, every reference updated "(3A)"; the documentation layout this page belongs to. | `c42d3c2` |
| 4A | 2026-10-18 | Agent guidance | "shared rules in AGENTS.md; personal prompt out of CLAUDE.md (owner decision 4A)". | `e10e2e6` |

The owner's decision of the same day to keep this repository as the public upstream of private
downstream forks is not numbered; it is recorded as
[ADR 0008](adr/0008-public-upstream-private-fork.md).

## The same ids used for other things

Reviews and handoffs number their own questions and options, and a few of those labels look like
decision ids. They are not entries of the runs above:

| Label | Date | Where | What it is |
|---|---|---|---|
| "the review's 5A" to "8A" | 2026-10-14 | 015 `research.md` R8 | The US4 code review's own option labels; the owner's decisions are 87A to 90A. |
| "the T116 review's 16A" to "18A" | 2026-10-15 | 015 `research.md` 98A to 100A | The T116 review's labels; the decisions are 98A to 100A. |
| "the owner's 26A, 27A and 29A-31A" | 2026-10-15 | 015 `research.md` 105A-109A; 016 `tasks.md` and `validation.md` ("the verifier's 26A") | The adversarial check's labels; the decisions are 105A to 109A. |
| "issue N, answered NA" (7A, 8A, 13A, 14A, 15A, 19A, 20A, 21A, 25A, 34A, 35A, 37A, 38A) | 2026-10-14 to 2026-10-16 | 014 `research.md`, 91A to 113A | The number of the question in its review; the decision is the heading's id. 110A also cites "(33C)". |
| "owner decision 23A" | 2026-10-15 | [002 `contracts/handoff-export.md`](../specs/002-task-pane-assistant/contracts/handoff-export.md), commit `10cecf3` ("handoff 015-23A") | A handoff label written as an owner decision: the export leaves out a report or attention record that names another session. It is not run 2's 23A (the private slice, 2026-09-29). |
| "owner decision 4A" | 2026-10-14 | [015 `review-2026-10-12.md`](../specs/015-review-send-gate/review-2026-10-12.md); [`workstation-test-plan.md`](test-plan-2026-09-27/workstation-test-plan.md), "How long it takes" | A handoff label: step 4.10 adds 35 minutes to the sitting. It is not run 2's 4A (the scorer, 2026-09-28). |
| "20A-Q1" | 2026-09-25 | 003 `research.md`, 008 `research.md` R2.58 | Feature 003's question about decision 20A, which 23A of run 1 answers. |

## Unnumbered owner decisions

Some decisions carry a date and no number. The main ones are the decisions of 2026-09-22
([`docs/history/roadmap-2026-09-22.md`](history/roadmap-2026-09-22.md), "Decisions taken
2026-09-22"), the decisions of 2026-09-16 that feature 004's spec is written from, and the
drawing-creation inventory's answers of 2026-10-18
([`docs/drawing-creation-d0-inventory.md`](drawing-creation-d0-inventory.md), "Inputs and the
owner's decisions"). The cross-cutting ones are recorded as ADRs below.

## Architecture decision records

ADRs record decisions that cut across features. They live in [`docs/adr/`](adr/README.md) and are
not edited after acceptance except to mark them superseded. Their index, with each one's title,
status and date, is [`docs/adr/README.md`](adr/README.md); it is kept there only.

**ADR 0001's status.** It was written as a proposal on 2026-09-12. Its layers 1 and 2 are built
as it proposed: the in-process C# extractor and add-in that dump a versioned IR (`extractor/`) and
the Python reviewer that reasons over it (`reviewer/`), and the constitution adopts the split in
Principle II ("Reasoning runs on an intermediate representation (IR) outside SolidWorks"). The
first stage of its layer 3, read-only drawing context, is feature 011, built as its 2026-09-22
amendment set out. Its second stage, drawing creation, is not specified: number 012 is reserved,
the [D0 inventory](drawing-creation-d0-inventory.md) is its first step, and its 2026 Auto-Generate
Drawing route does not apply on the SOLIDWORKS 2024 SP5 seat (the amendment says so). Its status
line therefore reads "Accepted in part"; its body is unchanged.
