# Research: Attention Policy and Procedural Gate

**Feature**: `007-attention-policy-gate` | **Date**: 2026-09-18 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the 2026-09-18 workstation record (`docs/history/pane-findings-2026-09-18.md`);
the planning session recorded in [design-brief.md](design-brief.md) (seven subsystem readers,
two bug diagnoses, three designs, three judges, a synthesis and a critic); and a second
reading pass on 2026-09-18 over the exact code the plan names (six readers: timing, the report
models, the check routes, the pre-run and levers, the pane pages, the CLI and benchmark
conventions), each of which opened the files and quoted the real signatures. Where this
document says VERIFIED, a reader opened the file on 2026-09-18 and, where the claim is
behavioural, ran it. Line numbers are as of commit `826c57d` and will drift; every task
re-verifies before editing.

---

## R1. What the sources are, and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | The four user stories and thirty-five requirements the owner reviewed | Normative for what is built; amended in the places R4 names, each with its reason |
| `design-brief.md` | The planning session's decisions, the ordered steps and the critic's corrections | The design intent; superseded by R2 wherever this pass found the code disagrees |
| The six reader reports (this pass) | Signatures, shapes, conventions, the tests to model on, the tests that go red | Normative for how each change is made; folded into R3 |
| The constitution | Principles I to VI and the technical constraints | The gate every decision below is checked against in `plan.md` |

## R2. Decisions, alternatives and rationale

### R2.1 What "suppressed" means, and why `exception_id` is not part of it

**Decision**: a finding is suppressed when `status == "checked_within_scope"` or
`disposition.decision in {"accepted", "rejected"}`. Nothing else. `exception_id` is not read.

**Why**: VERIFIED that `exception_id` is set on a finding for both an active waiver and a waiver
whose fingerprint moved (`checks/rules/report.py:315-329` sets it in both branches), and that the
re-review branch changes only `observed` and `recommended_action`, never status or severity
(`:486-505`). The active/needs_review/retired state lives on the exception store
(`exceptions.py:82`), which the pure policy module may not read (FR-015). So `exception_id`
cannot tell a live waiver from a re-review one, and reading it would suppress exactly the
finding FR-008 says must keep competing. The only pure signal of a live waiver is the status
rewrite `_waived` performs (`checks/rules/report.py:463`, to `checked_within_scope` and
`info`); the interference family's `_excepted` does the same (`checks/interference.py:314`).

**Consequence stated plainly**: `checked_within_scope` is also the clean-pass status of the
numeric families (`fit.py:112`, `hole_alignment.py:124`, `fastener.py:362`, `stack.py:151`).
Both meanings sort last, which is right: neither needs the engineer's minutes. The
not-amplified line therefore counts "checked within scope", not "waived", because from the
finding alone the two are one bucket. FR-008 and FR-013's wording are amended accordingly (R4).

**Alternatives**: reading the exception store from the policy (rejected: violates FR-015 and
makes the rank depend on a file beside the session); adding a `waived` flag to `Finding`
(rejected: the schema is `additionalProperties: false`, and the flag would restate the status
rewrite).

### R2.2 The fold is a row in the ranking, not a mutation of the session

**Decision**: repeated conditions fold into one `AttentionRow` carrying the member finding ids
and the union of their component ids. `Finding.group` is not set. `session.findings` and the
Findings section are byte-identical before and after ranking.

**Why**: VERIFIED that `FindingGroup.member_component_ids` holds component ids, not finding
ids (`findings.py:68-72`), so the vehicle cannot record which findings were folded; that no
production path constructs one (`tools/recording.py:72-91` never passes `group`); and that
`report/markdown.py`'s own docstring states "session.json is the only source of truth; this
module never reads or writes it". Stamping `group` during ranking would make rendering write
to the session, and make the fold reproducible only by re-running the mutation. A row in the
ranking is pure, reproducible from `session.json` alone (FR-014), and is what `attention.json`
records (FR-020, "the groups").

**Alternative rejected**: filling `FindingGroup` as the brief proposed. It stays declared and
unconstructed; the spec's FR-012 is amended (R4).

### R2.3 "Start here" sits immediately above "## Findings"; nothing "opens with" it

**Decision**: the section is rendered between Summary and Findings. The standards report's
verdict header, prepended outside the renderer (`checks/standards/run.py:418`), stays first on
that surface.

**Why**: VERIFIED that the section order is a straight-line list in `render_report`
(`report/markdown.py:55-79`) and that the standards path writes `header + render_report(...)`.
"Opens with" and "immediately above Findings" were two placements; the second is the one every
surface can honour. FR-013 is amended (R4).

### R2.4 Severity is read as recorded, and the fixture must prove the consequence key on its own

**Decision**: key 5 reads `Finding.severity` verbatim. The committed fixture that pins the top
five uses rule findings that are **not** in a family's `high_severity` set.

**Why**: VERIFIED that `_status_and_severity` (`checks/rules/results.py:85-99`) overrides a
`demonstrated` rule finding to `high` when its rule is in `family.high_severity`, which for RMS
is every `rms.refs.*` rule plus `rms.sketches.not_over_defined` (`checks/rms/registry.py:101-113`)
and for standards is `HIGH_SEVERITY_CHECKS` (`checks/standards/registry.py:247`). The brief's
"severity is nearly constant for the rule families" omitted this. On the 2026-09-18 run none of
the eight findings was an `rms.refs.*` rule, so the worked order stands; a fixture built on
`rms.refs.*` rules would let the severity key do the consequence key's work and prove nothing.

### R2.5 Reach and the coverage block, defined

**Decision**: reach is `len(set(component_ids))` capped at 3, descending; a drawing finding has
reach 0 and competes on its other keys. The coverage block prints the five bucket counts read
from `session.coverage`, then the **close-out rows**: the unresolved items whose `check` is a
checklist item id, each with the reason the run recorded, at most five; then the count of
`coverage.evidence_request` rows; then the counts of every other unresolved and skipped item
as "rules".

**Why**: the real 2026-09-18 review (read on 2026-09-19 from the handover folders) shows what
the 39 unresolved rows are: seven checklist close-out rows written by `finalize` - `fasteners`
("list_fasteners returned zero instances…"), `holes.alignment` ("only cmp:0003 holes were
extracted; the two lightweight pins have none"), `interfaces.fit`, `interfaces.stack`,
`drawing.manufacturing_inputs`, `provenance`, `modeling.resilience` - each already carrying a
sentence an engineer can act on; three open evidence requests; one `coverage.closeout`; and
twenty-three RMS rules. A count by family would have said "rms 39" and hidden all of that. The
close-out rows need no checklist lookup: their `check` equals an item id, which is exactly the
equality `Checklist.bucket_of` uses for coverage (`agent/checklist.py:45-53`), and the policy
module can carry the item ids as data. One item is excluded by name: `coverage.closeout` is
itself a checklist item id, and its unresolved row is the run's own close-out summary ("the
package has 24 recorded gaps…"), not an unreached family; the fixtures carry it last and the
block never prints it (found by the Phase 1 builder, 2026-09-19). The gate's brief lists the pre-run's
not-evaluated families separately from their own objects (R2.13).

### R2.6 One renderer, one keyword, one golden that proves it

**Decision**: `render_report(session, package=None, *, ranking=None)`. The section renders only
when a ranking is supplied, guarded exactly as `## Tokens` is guarded on `session.usage`
(`report/markdown.py:74-76`). A new golden pins a ranked report; the one existing golden of this
renderer stays byte-identical.

**Why**: VERIFIED that six of the eight call sites pass `package` positionally, so a fully
keyword-only signature breaks them; and that exactly **one** golden covers
`report/markdown.render_report` (`tests/unit/test_report_tokens/…matches_the_golden.md`). The
other `.md` golden (`test_remodel_report/test_the_whole_report.md`) is produced by
`remodel/report.py:221`, a separate renderer that never calls this one, so it proves nothing
about the default. The spec's "two goldens" is amended to one (R4). A test that enumerates the
call sites must match the import `from swreview.report.markdown import render_report`, not
the bare name, or it counts the re-modeler's.

### R2.7 Where the record is written, and one folder re-render for the three offline writers

**Decision**: `attention.json` is written by three sites from the same `Ranking` the report was
rendered from: `ReviewRun.finalize` (`agent/runner.py:719`, including the failure path, since
`_close_out` finalizes too), `checks/rules/run.py:228 write_report` (the RMS path), and
`checks/standards/run.py:392 _write_report`. `GET /checks/{check_id}` recomputes the ranking in
memory and writes nothing. Accept re-runs the whole check, which rewrites the record through
the entry point.

The three **offline** re-renders that touch a run folder from outside a run - `swreview
disposition` (`report/dispositions.py:111`), the new `swreview timing`, and `swreview
exceptions accept-*` through `cli.py:1303` - go through one new `report/rerender.py`
`rerender_run_folder(run_dir)`, which loads `session.json`, loads `package.json` when the
folder holds one, re-prepends the standards verdict header when `check.json` names that
family, ranks, writes `report.md` and `attention.json`, and returns both paths.

*Amended 2026-10-19 (owner decision 139A, R6):* the header is re-prepended only when
`check.json` also names the session being rendered, which is then the check's own; a review that
claimed the folder is re-rendered without it, as it was written.

**Why**: VERIFIED that `apply_disposition` re-renders with no package, which degrades Manifest
Discrepancies to a placeholder and component names to ids (`report/markdown.py:129-134`), and
would delete a standards folder's verdict header - an existing defect a second lossy writer
(`timing`) would double. One folder-aware re-render is the DRY answer; it is not speculative,
because three commands need it on the day it lands. The record is not added to
`SESSION_FILES` (`chat/server.py:434`): that tuple is also the claim rule's truthiness test,
and a folder holding only `attention.json` must not read as "already holds a review".
`_rotate_previous` moves the record explicitly beside the session.

**Alternative rejected**: writing the record in the routes (rejected: Accept's re-run would
leave a record naming a session the folder no longer holds - the same hazard
`recorded_session` guards for `check.json`).

### R2.8 The Review tab reads `GET /sessions/{chat_id}/attention`

**Decision**: one new read-only route returning the `Ranking` JSON, computed from the live
`run.session` on each call, never written; 404 `UnknownChat` for an unknown chat, and an empty
ranking with its own reason for a run that produced no findings. The page fetches it in
`endSession`, discards the response when `state.chatId` has moved on, renders it through a
new `render.attentionPanel` builder into a new `<section id="attention-panel" class="panel"
hidden>`, and clears it in `resetTranscript`.

**Why**: the brief rejected this route as redundant beside the `attention` key and the report.
VERIFIED that neither exists for a review: `GET /sessions/{chat_id}` returns `ChatSession.public()`
(`chat/sessions.py:302-318`) with no findings, and `GET /sessions/{chat_id}/report` returns
markdown, which the page's `call` helper turns into `null` (`app.js:227-261`). Adding the
ranking to the session view would fatten a body three pages read on every init; a dedicated
read route is explicit, one method, one `Route`, one contract row, one entry in the door test's
`ROUTES` tuple. The brief's rejection is reversed.

### R2.9 Timing: one writer, a folder argument, a model constraint, and a chat-scoped route

**Decisions**:

- `record_timing_at(session_path, *, baseline, supervision, verification, false_alarms) ->
  Timing` is extracted from `record_timing`, which becomes `return record_timing_at(_session_path(run_dir, package_id), ...)`. The six tests in `test_timing.py` pass unchanged.
- `swreview timing <run_dir>` takes a run **folder** holding `session.json` directly, for
  parity with `disposition`, and re-renders through `rerender_run_folder`. A benchmark run root
  (no `session.json` at the top) is refused naming `benchmark time` as the command for it.
- `Timing.baseline_minutes` gains `Field(ge=0)`. VERIFIED that it is the one input without the
  constraint, that a negative baseline is accepted today and derives a negative net, and that
  the committed `review-session.schema.json` already says `"minimum": 0` for it - so the model
  is brought into agreement with its own contract. No real run has ever recorded a baseline, so
  no committed session can fail to load.
- The negative-input refusal is the pydantic `ValidationError` naming the field, through
  `_errors_as_exit_1` (exit 1), uniform across the four inputs; the message is the validator's,
  which names the field.
- `POST /sessions/{chat_id}/timing` copies `disposition`'s shape (`chat/server.py:1150`): `_chat`,
  `_json`, validate, `_require_idle`, then `run_in_threadpool` over a writer that mutates the
  **live** `run.session` and saves it (VERIFIED: a disk-only write is overwritten by the next
  turn's finalize, which is why `record_disposition` exists). The body may carry only the four
  input names; `net_saved_minutes` or any other key is 400 `InvalidTiming` naming the key,
  because VERIFIED `Timing.model_validate` silently accepts and overwrites a supplied net.
- The route is chat-scoped, so it reaches pane **reviews**. Check folders register no chat
  (`chat-api.md`, the `/checks/*` rows), so they are recorded from the command line. FR-001 is
  amended to say so (R4).
- The ledger column: one `METRICS` entry, one `OffOn` field on `LeverDecision`, one
  `LEVER_COLUMNS` title, one `_lever_line` cell; `decide()` names its metrics explicitly, so the
  column gates nothing by construction. The cell is the median **across runs** of each run's
  per-package median, with `n=` the number of runs that carried timing; the per-design median
  stays where it already prints, in `scorecard.md`. The committed ledger block in
  `docs/llm-efficiency-options.md` is regenerated in the same change, and
  `specs/005-llm-efficiency/contracts/ab-harness.md` sections 5 and 10.8 record the column.

### R2.10 Lever 11: appended, four pinned places, two refusals, one counter

**Decisions**:

- `procedural_gate: bool = False` is appended after `carry_over_rms` so `EXPECTED_LEVERS` and
  `LEVER_NAMES` change by one trailing name.
- Pinned places paid in the same change: `test_no_lever_in_pane_settings.py:46` (`== 11`),
  `test_efficiency_settings.py:55/:89/:90/:95`, `_levers_sentence()` ("the eleven levers"), and
  `review-session.schema.json`'s `EfficiencySettings` block - in `properties` only, never in
  `required`, or every committed session fixture stops validating. `levers.md`'s flag table
  gains a row.
- `procedural_gate` **implies** the pre-run: `prerun_checks(...)` runs when either lever is on.
  `procedural_gate` with `prerun_checks` is refused ("levers 5 and 11 never share an arm until
  each has been gated alone"), and `procedural_gate` with `coverage_stop` is refused for the
  reason lever 5 already is (`agent/settings.py:557-561`): a pre-run that closes every checklist
  item plus a stop predicate ends the review before the first turn.
- `LEVER_COUNTERS["procedural_gate"]` names the fit and axial-stack counts, and a new `_counter`
  branch computes them per run from `PackageScore.tool_calls_by_name` (VERIFIED already
  recorded by `tool_histogram`), rendering the arm medians and a worst-case list field
  `fell_in_runs` beside `dropped_tools`, because "must not fall per run" is a worst-case
  statement, not a median. The same branch serves lever 5, whose counter is a placeholder
  string today.

### R2.11 The gate's standards half: ordering, three not-evaluated reasons, one checklist item

**Decisions**:

- `start_review` gains `standards_profile: Path | None = None` (and `swreview review` gains
  `--standards-profile`). When set, the profile is loaded and `graded_documents` computed and
  attached with `attach_standards_run` **between** `build_context` (`runner.py:892`) and the
  dispatch (`:946`), because VERIFIED `ToolRegistry._offered` adds `check_standards` only when
  the context carries a run at dispatch-build time and the tool array never changes afterwards.
- Any failure on that path - profile unreadable or invalid, an ungradable root, a package
  without the `cutlist` (or `drawing`) phase rows - becomes a `NotEvaluated` line and a skipped
  coverage item `coverage.prerun.standards`, never a refusal of the review. VERIFIED that
  `run_standards_checks` refuses a package whose phases did not run, so a review dumped with
  the `model_check` profile hits it; the spec's "no profile" case is one of three.
- `planned_calls` reads `standards_run(context)` (the same attribute `_offered` reads) rather
  than growing a parameter.
- The pre-run's unguarded `result.payload["error"]` (`prerun.py:388`) is guarded in the same
  change, because `check_standards` returns an envelope the pre-run has never seen.
- The checklist gains `standards.release` (id = `STANDARDS_FAMILY.summary_check`, prefix
  `standards.`), the exact shape of `modeling.resilience`. VERIFIED that `Checklist.render()` is
  part of the system prompt for every review, so the prompt-prefix stability tests and the byte
  counts quoted in `contracts/levers.md` move with it; both are named tasks.

### R2.12 The brief is rendered from the ranking object the report renders from

**Decision**: `gate_brief(prerun, ranking) -> str` in `prerun.py` composes: the lever-5 digest
unchanged, then the same "Start here" lines `report/markdown.py` renders (one function, two
callers), then the three lists, then the instruction sentence. The anti-drift test is
therefore structural: the ids come from `ranking.rows` on both sides. The branch between
brief and digest is at the composition site (`runner.py:988-989`), so `PrerunResult.digest()`
is byte-identical with the gate off.

### R2.13 The number guard's sources are the drawing evidence the citations name

**Decision**: `record_drawing_finding` refuses an `observed` or `requirement` containing a
number-like token that appears in none of the drawing evidence the `source_refs` reach:
`DrawingSheet.dimensions[].text_as_read`, `general_notes`, `DrawingNote.text` and annotation
text for the cited document and sheets. A number-like token is a standalone decimal, with or
without a trailing unit; finding ids, component ids, sheet names and ISO dates are not
number-like by that definition.

**Why**: VERIFIED that the tool takes no `inputs` and no `tool_result_ids` (`tools/session.py:118-126`),
so "the cited tool results" had nothing to read; `InvestigationStep.result_summary` is a
summary string, not the payload, and would refuse on the summariser's choices. The sheet
lookup already exists in the same module (`_drawing_coverage_limits`, `:186-197`). FR-033 is
amended (R4).

### R2.14 Two things the pane tests force on the wording

- The shared check page may not contain "grade" or "verdict", even in a trailing comment
  (VERIFIED `SharedCheckPageTests.cs:379-399` scans stripped source case-insensitively). The
  ranking renderer's heading and comments avoid both.
- The Standards page body scan forbids `%` anywhere (VERIFIED `StandardsPageTests.cs:358-377`).
  No reason line, not-amplified line or coverage line carries a percent sign; a policy test
  asserts it.
- The new element is `<section id="attention">` in **both** check pages' `index.html`, placed
  above `#checks` on Standards and above `#filters` on Model check, so "above the bucket chips"
  holds on both and the roster does not sit between the verdict and the rows. The element-id
  scans require the literal id in each page's HTML.

### R2.15 The read-through, held 2026-09-19 on the handover folders

The owner handed over the pilot workstation's run folders on 2026-09-19 (fourteen folders,
2026-09-16 and 2026-09-18; kept at `%LOCALAPPDATA%\SwReview\handover\runs` on the development
machine and never in this repository, because their packages carry vault paths and property
names). A throwaway script applied the nine keys of `contracts/attention.md` section 1 to
every session and the owner read the result. Four decisions, all as the policy proposed:

| # | Question | Decision |
|---|---|---|
| 1 | The top five on the small assembly's review `20260918-215755-…` | As previewed: the two `interference.static` rows, `rms.assembly.mates_to_reference_geometry`, `rms.sketches.fully_defined`, `rms.grouping.all_features_in_a_group`; `rms.folders.present` last of eight |
| 2 | The class of `rms.assembly.first_component_fixed`, found on another assembly's three 2026-09-16 reviews | `rebuild_breaker`: an unfixed first component leaves every mate without an anchor |
| 3 | Grouping and the two equation rules | `discipline`, below the reference rules and above hygiene |
| 4 | The shape of the "not reached" block | The run's own close-out sentences (R2.5), then the evidence-request and rule counts |

What the folders also showed, each recorded so nobody rediscovers it: the real
`mates_to_reference_geometry` finding is bound to the root assembly's component id with the
part and the pin in its `inputs`, so its reach is one, and T003's fixture mirrors that; on
that run the two interference findings sat **fifth and sixth** of six mediums in tool-call
order, not third and fourth as the workstation record said; the review of a single part
(`20260918-204543-…`) carries a `failed` coverage row from `get_drawing_sheet` on a document
with no sheets; the other assembly's three `20260916-2050xx-…-check` folders hold only a
`package.json`, the Model check having never reached the backend that evening (the web-filter
problem `docs/history/pane-findings-2026-09-16.md` records); `20260916-003612-…` is an earlier
assembly review, cut off mid-turn with no error event, from the same evening; and every
session carries `efficiency` all-off and no baseline minutes, which is User Story 1's premise
measured rather than assumed.

**The confirmation run (T022), 2026-09-19, with the shipped command.** `swreview attention`
was run over the ten handover folders that hold a `session.json`, each folder hashed before
and after. Every folder was byte-identical afterwards and every order was the one the table
above records:

| Folder(s) | Top of the ranking |
|---|---|
| `20260918-215755-…` (the small assembly's review, eight findings) | `F-007`, `F-008` `interference.static` (needs your judgement); `rms.assembly.mates_to_reference_geometry`; `rms.sketches.fully_defined`; `rms.grouping.all_features_in_a_group`; three not amplified, `rms.folders.present` last |
| `20260918-214702` and `-215624`, the small assembly (reviews, six findings, no interference call) | mates to reference geometry, the under-defined sketch, grouping, the two equation rules; `rms.folders.present` the one not amplified |
| `20260918-214545` and `-220310`, the small assembly (Model check, three findings) | `rms.sketches.fully_defined`, grouping, folders |
| `20260918-204543-…` (the single part) and its check | grouping first (the part has no sketch or mate finding), folders last |
| The other assembly's three reviews, `20260916-204757-…`, `-210303-…` and `-210754-…` (two findings) | `rms.assembly.first_component_fixed`, then `rms.assembly.mates_to_reference_geometry` |

One thing the preview had not made visible: on the other assembly's reviews the two rows tie on all
seven leading keys (both rebuild breakers, demonstrated, medium, reach two, not carried), so
the check-id key decides and the unfixed first component prints first. That is the contract's
eighth key doing its job, not a class question; T022's acceptance sentence, which had guessed
the other order, was corrected rather than the policy. The "not reached" block prints each
run's own close-out sentences on the reviews and only the rule counts on the check folders,
which hold no checklist items - as R2.5 intends.

## R3. Verified facts the plan relies on

The eight production `render_report` call expressions: `cli.py:563`, `cli.py:607`,
`cli.py:1303`, `chat/server.py:1860` (reached after every turn at `:1803` and after a stop at
`:1883`), `chat/sessions.py:348`, `checks/rules/run.py:231`, `checks/standards/run.py:418`,
`report/dispositions.py:111`. The pane's waiver-accept path re-runs the check and lands on
`checks/rules/run.py:231` or `checks/standards/run.py:418`; it is not a ninth. *Since
2026-09-23 (on review of feature 009's decision 2A):* `swreview report` renders with the package
and verdict header its session's folder holds, through `report/rerender.render_folder_report`,
the half of the one folder re-render that reads and renders; the eight paths now reach the
renderer through seven call expressions (`test_report_start_here.py`, `RENDER_SITES` and
`FOLDER_RENDER_SITES`).

The result bodies: `check_result` (`chat/server.py:655`, ten keys, `attention` goes after
`exceptions_carried_forward`) and `standards_result` (`:785`, fifteen keys asserted set-equal at
`test_chat_standards_routes.py:264`, `attention` goes beside `rebuilt`). Both serve POST, GET
and the Accept re-render, so two insertion points cover six route-family pairs.

The check folder holds exactly `package.json`, `session.json`, `report.md`, `check.json`, and
`exceptions.json` when carried forward; never `events.jsonl`. Four strict folder-content
assertions go red when `attention.json` lands and are edited deliberately:
`test_rms_run.py:278`, `test_standards_run.py:274`, `test_cli.py:1905`, `test_cli.py:1995`.

`is_check_folder` reads through `read_rms_check` and returns False for a standards folder
(VERIFIED by running it), so a review cannot claim a standards check folder today; the rotation
scenario is rms-only and the spec says so. *Corrected 2026-10-19 (owner decision 139A, R6):*
that holds for a start without `retry_of`. `_claim_run_dir` consults the folder only when
`retry_of` is absent, so a Retry claims a standards folder and rotates the check's session aside,
and `swreview review --out` writes a review over one. *Superseded 2026-10-19 (owner decision
142A, 002 [research.md](../002-task-pane-assistant/research.md)):* `_claim_run_dir` consults the
folder for a Retry too and refuses one on a check's folder of every family, and `is_check_folder`
reads every family's `check.json`, so a start is refused on a standards folder as a check's, by
its family's name, rather than as a review's. Only `swreview review --out` still writes a review
over one.

The pre-run has one call site (`runner.py:953`) and one consumer (`:988-989`); its lever test
is one line (`prerun.py:365`); `session.started` is emitted before it (`:930-939`), which makes
`docs/review-backlog.md:1164` stale. The four unconditional not-evaluated families and the
conditional interference one are written as skipped items `coverage.prerun.<family>`.

`record_timing` has one production caller (`cli.py:2051`) and six tests; the nested folder
shape is produced at `benchmark/runner.py:229` and read at three places the extraction leaves
alone. `Aggregate.median_net_saved_minutes` and `packages_with_timing` already exist and print
in `scorecard.md`; only the ledger lacks the column.

The CLI has no Rich: every command emits a payload dict and plain lines through `_emit`, and
refuses through `_errors_as_exit_1`. `rms types` is the shape for a keyless reader;
`disposition` for a run-folder writer; `exceptions accept-standards` for one body under two
names. The `--help` surface test (`test_cli.py:2409`) lists top-level commands by name and
gains `timing` and `attention`.

The two check pages render through one `renderResult` (`check-page.js:447-458`): header,
chips, rules, carried-forward. No page script sorts anything today. Every string reaches the
DOM through `dom.js`; the shared script may not name a DOM constructor.

## R4. Amendments to the spec made by this pass

| Where | Was | Now | Why |
|---|---|---|---|
| FR-001 | "from the command line and through the backend" for any run folder | the command line for any run folder; the backend for a review the pane started | check runs register no chat (R2.9) |
| FR-008, FR-013 | "waived" counted in the not-amplified line | "checked within scope" | the finding cannot tell a waiver from a clean pass (R2.1) |
| FR-012, User Story 2 | fold into the existing finding-group vehicle | fold into one attention row; `Finding.group` untouched | purity and reproducibility (R2.2) |
| FR-013 | "the report MUST open with" | "immediately above the Findings section" | the standards header (R2.3) |
| FR-018, SC-004 | "the two existing golden reports" | the one golden of this renderer | only one exists (R2.6) |
| FR-033 | "absent from the cited tool results, inputs and drawing locations" | "absent from the drawing evidence the cited locations name" | the tool cites no results (R2.13) |
| FR-021, Assumptions | a review that claims a check folder | an RMS check folder; a standards folder is not claimable today | `is_check_folder` (R3) |
| FR-023 | "fetched from the backend" | `GET /sessions/{chat_id}/attention` | no field exists (R2.8) |

## R5. Open items that stay open

| Item | Owner | Blocks |
|---|---|---|
| ~~Copy the 2026-09-18 run folders off the pilot workstation~~ done 2026-09-19 (R2.15); T022 is now the confirmation run with the real command | owner | nothing |
| Place the real standards profile on the pilot workstation and confirm `StandardsProfilePath` there (006 T100). The file itself was regenerated from the macro on 2026-09-19 and validated on the development machine; it stays outside this repository | owner | the gate's standards half being measurable |
| Record the four timing inputs after each pilot run | owner | the checkpoint claim "timing recorded on every run" |
| Held-out packages in `benchmarks/sets/pilot.json` | owner | any adoption decision (006 and 005 both record this) |
| The gate's wall clock before the first model token on the pilot assembly | step 6 | step 7 |

## R6. Owner decision 139A (2026-10-19): the verdict header is the check's own session's

**Decision**: `render_folder_report` re-prepends a standards folder's verdict header only for the
session the folder's `check.json` names: the condition 132A gave `check_run`, so one comparison
now decides both whether the report names a model and whether it opens with the verdict. A
review that claimed the folder re-renders as it was first written, with no header; the check's
own session keeps its header byte for byte, in `session.json` or rotated aside to
`session.1.json`; and a verdict that cannot be read refuses only the render that would rebuild
the header from it.

**Why**: a re-render must give back the report the run wrote (R2.7), and the header is written
in one place only, `checks/standards/run.py` `_write_report`, for the session that run records
in `check.json`. Neither writer of a review's report writes one: `ReviewRun.write_views`
(`agent/runner.py`; the pane after every turn) and `swreview review` (`cli.py`, `review`) both
render `render_report(session, package, ranking=...)`, with `check_run` false since 132A. Before
this, `_header_of` was asked for every session in a folder whose `check.json` named the standards
family, so `swreview report`, `timing`, `disposition` and `exceptions accept-*` prepended the
check's verdict to a review's report, and refused the review outright when the check's verdict
could not be read.

**Evidence** (VERIFIED by running it on 2026-10-19, at `304092c`):

- A standards check folder holding its package, claimed as `_rotate_previous` claims a folder
  (`session.json` and `attention.json` moved to index 1) and reviewed with the scripted provider:
  the review's `report.md` opened `# Design Review Report: dsn:1`; its re-render opened
  `# Standards Check: dsn:1` and the check's verdict lines, and was byte-identical after them.
  The same through the backend itself (`POST /sessions` with a `retry_of`, then
  `GET /sessions/{chat_id}/report`, which served the file as written), and through
  `swreview review <folder> --out <folder> --provider fake`, which writes over the check's
  session rather than rotating it.
- How a review reaches such a folder (R3, corrected): `POST /sessions` without `retry_of` refuses
  a standards folder with `400 InvalidRunDir`, because `is_check_folder` reads through
  `read_rms_check`, which fails on a standards record (it has no `scope`). `_claim_run_dir`
  consults the folder only when `retry_of` is absent, so a Retry claims it, and
  `swreview review --out` checks nothing. The pane does neither: every Review extracts into a new
  folder (`RunFolders.CreateForDocument`), and a context review's Retry reuses the review's own.
- No check's own report loses its header: every `check.json` a standards run writes names its
  session, as `_write_check_record` has done since the family landed (`c5b05b7`, 006 round B).

Tests, written first: `tests/unit/test_rerender.py`
`test_a_review_that_claimed_a_standards_folder_re_renders_as_it_was_first_written` and
`test_an_unreadable_verdict_refuses_only_the_session_whose_header_it_rebuilds`, and
`tests/unit/test_cli.py` `test_report_gives_a_review_written_into_a_standards_folder_no_verdict_header`,
failed before the change and pass after it.
`test_the_check_s_session_a_review_rotated_aside_keeps_its_verdict_header_byte_for_byte` guards
the check's own session, and `test_a_standards_folder_keeps_its_verdict_header_byte_for_byte`
passes unchanged. Amended with it: `contracts/timing.md` section 2, and feature 001
`contracts/cli.md`'s `swreview report` row.

## R7. Owner decisions 183A and 184A (2026-11-01): the net counts all of the engineer's effort

**Decision**: 183A: `swreview timing` records two more inputs, the design's setup and the review
the engineer still does by hand, and the assisted minutes are setup, supervision, verification,
false-alarm handling and the review by hand together. Until both new inputs are recorded the net
reads unknown, as it does without a baseline; a recorded 0 is a value. 184A: setup is this
design's own setup only - preparing the package, opening the assembly, attaching drawings,
starting the review and any rerun - and the sitting's software update is reported apart, as a
pilot cost; corrections count inside verification or false-alarm handling; the review by hand is
the checking the engineer still does on what the tool did not reach; no minute is counted twice;
the seat plan's step 4.1 states it before M0-a.

**Why**: the net counted supervision, verification and false-alarm handling against the baseline
and nothing else (`report/session.py`, `Timing._derive_net_saved_minutes`), while the pilot
proposal counts "package preparation, recurring setup, supervision, verification, false-alarm
handling, corrections, and remaining manual review" in assisted effort
(`docs/history/pilot-proposal-2026-09-13.md`, "Success criteria and ROI"). A net recorded with
the four inputs alone could therefore be overstated
([`docs/roadmap/holes.md`](../../docs/roadmap/holes.md), H-a-002, which merged H-c-004), and
H-a-002's skeptic made widening it an owner decision first, because the narrow definition comes
from 001 SC-001 and this feature's contract. The options, as asked in cycle 1's round:

- 183A, what the net reads while an input is not recorded. A, chosen: unknown until both are
  recorded, a recorded 0 a value, so the report never prints a net that leaves effort out; the
  cost is FR-002, FR-005 and `contracts/timing.md` section 1 amended, the existing tests' figures
  rearranged to record the two as 0 with their expected values unchanged, and `benchmark time`
  needing both numbers for a net. No stored value moves: no session or study has ever carried a
  baseline. B: count an unrecorded input as 0 and print "not recorded" on its line - the
  smallest change, but a review timed with the four numbers still prints the overstated net,
  and the three assisted inputs already start at 0.0 (`tools/context.py`), so a baseline alone
  reads as all saved. C: A for review folders and B for `benchmark time` - one number with two
  rules, so the ledger's median and a seat review's net would mean different things.
- 184A, what the two inputs cover. A, chosen: as above; comparable across designs and true of
  the tool in use, though the net leaves out about an hour of update per sitting at today's
  cadence, which is reported apart. B: the sitting's update divided over the designs it
  reviewed - the most conservative net, but at one design a sitting the update alone takes about
  55 of the 60-minute target, so M0 would mostly measure the update cadence. C: the engineer
  defines it each time, in the findings document - nothing to write, and nothing comparable
  across sittings or designs.

**What it changes**: spec FR-036, with dated notes on FR-001, FR-002, FR-005, Key Entities,
SC-001, User Story 1's scenario 1 and the Timing edge cases, and scenario 7; `contracts/timing.md`
sections 1 to 3; the plan's Summary, its touch points and point 1. In the code: two optional
fields on `Timing`, `setup_minutes` and `review_by_hand_minutes`, left out of `session.json`
while not recorded so every earlier session keeps its bytes, but for a net derived from the four
earlier inputs alone, which now reads unknown and is saved as null; one `Timing.assisted_minutes` that
the net and the scorecard both read, so the two cannot disagree; `TIMING_INPUTS` grows to six,
so the route takes both with no logic of its own; `--setup` and `--by-hand` on `swreview timing`
and `swreview benchmark time`, declared once; the report's Timing section prints both always,
`unknown` when not recorded; and feature 015's re-run copies every human input from one tuple
rather than naming four. 001's FR-026 and SC-001, which define the net, take a dated note at the
close (T069). Tasks T064 to T069, Phase 9 of [tasks.md](tasks.md).

**Not changed**: no pane control for minutes (Assumptions keep it a follow-on); no separate
inputs for preparation or corrections, which 184A folds into setup, verification and false
alarms; `SCORING_RULES_VERSION` is not bumped, since timing is not finding matching and the
scoring goldens exclude it (`tests/support/scoring_probes.py`, `GOLDEN_EXCLUDED`), and a scorecard
scored before the change keeps its old assisted and net figures until it is scored again.
`swreview timing` on a review the backend still holds is still lost at its next save
(`docs/review-backlog.md`, the review of 004 T390 and T391, R8), and the two new inputs share
that: step 4.5 times a review after the backend's restart.

**speckit-converge**, run once on 2026-11-01 (T064), bounded to FR-036, its dated notes, scenario
7, the dated edge cases, the contract's amendments and the plan's touch points: nine gaps - six
`missing`, two `partial` (the scorecard's assisted minutes and the re-run carry, which name three
and four inputs) and one `contradicts` (the net, derived from three assisted inputs) - each
already in Phase 9, so its appended Phase 10 was removed and nothing was folded in.

**Built** (2026-11-01, T066 and T068), as *What it changes* says: the two fields left out of the
dump while `None` by a wrap serializer reusing `omit_when_null`; `Timing.assisted_minutes`, read
by `_derive_net_saved_minutes` and by the scorecard's `PackageScore.assisted_minutes`;
`Timing.replace` checking names against the model's fields, since the dump leaves out an input
not recorded; `HUMAN_TIMING_FIELDS`, the six inputs beside `Timing`, which `carry_from` copies;
`TIMING_INPUTS`' six, through which the writers, `record_timing_live` and the route take both;
the six options declared once as `Annotated` aliases, with one `_timing_line` for both
commands; and the report's two lines, `unknown` when not recorded. The seat plan's step 4.5
line names the six options, its pass text reading "the baseline less the other five", and step
4.1 asks for the two in 184A's words and gives every finding one of the four triage outcomes
(002 FR-031, decision 185A), in T066's commit, since the plan's pin reads the command's options.

**Tests changed on purpose**, none loosened, each because the net is unknown under 183A until
setup and the review by hand are recorded:

- The figures that read a net record the two as 0, their expected values unchanged:
  `test_timing.py` (nine cases), `test_session.py` (three), `test_scorecard.py`'s `TIMING` and
  its distribution case, `tests/support/studies.py`'s `PackageSpec.timing` (so
  `test_benchmark_compare.py`'s and `test_adoption_rule.py`'s medians hold with no edit of their
  own), `test_cli_timing.py`'s `four()`, `test_chat_timing_route.py`'s `FOUR` (which
  `test_waiting_answers.py`'s timed Send imports), `test_cli.py`'s `benchmark time` case, and
  `test_report_tokens.py`'s session, whose golden prints a net of 70.0: not in T065's list, but
  without it T066 would have moved that golden's net line.
- `test_timing.py`'s `test_the_four_input_names_are_the_writers_own_signature`, renamed
  `test_the_input_names_are_the_writers_own_signature` and extended to `record_timing` and
  `record_timing_live`; and the negative-input cases of `test_timing.py` and
  `test_cli_timing.py`, extended to the two inputs.
- `test_session_fields_015.py`'s SHA-256 save pin, moved: `build_session` records the four
  earlier inputs alone, so its saved net reads null where it read 70.0, the one byte that
  changed; putting 70.0 back reproduces both captured values. T066 had expected the pin to
  hold, having read only the key set.
- `test_workstation_test_plan.py`'s `test_the_timing_line_passes_the_four_inputs_swreview_timing_takes`,
  renamed `test_the_timing_line_passes_every_input_swreview_timing_takes`, since the pasted line
  names the six.
- The six report goldens, regenerated with `--force-regen` and each diff read: the two lines and
  nothing else, `unknown` in the ranked report and the four ticked-review goldens and `0.0` in the
  tokens golden.

**Tests first**: T065's new and rearranged cases failed before T066 - 287 failed and 9 errored,
each for want of the two fields, keywords, options or body keys, `test_scorecard.py` and
`test_scoring_rules_version.py` failing to collect since `TIMING` is built at import - but for
the renamed signature pin, which pins the writers' agreement and passed as it stood. T067's two
cases failed before T068: the report printed neither line, and `carry_from` named the four
earlier inputs, so setup and the review by hand came back `None`.

**Gates** (T069, 2026-11-01): run once for cycle 1 with 002 T318 and recorded in full in 002
[research.md](../002-task-pane-assistant/research.md), 185A: the 63 test modules the cycle
touched or that pin its files green on Python 3.12 and 3.11 with the tokenizer required, 3,196
passed and 1 skipped on each; `ruff check` clean; the C# build with zero warnings, and its
10,274 extractor and 4,288 add-in tests passed; the link check clean; every changed file LF in
the index. The whole non-live suites were not run in that lane.

**Review** (Tier 1, decision 180A; 2026-11-01): one Opus and one Codex review of the branch, no
must-fix.

- Codex (medium) and Opus (should-fix) found the same gap: "every earlier session keeps its
  bytes" held only for a session with no baseline. A session timed before 183A holds a net
  derived from the four earlier inputs alone; it now loads with that net unknown and, saved
  again for any reason, writes null for it. That is 183A's rule, and every reader of the net
  reads the model's, so the code stays. Codex's alternative, keeping the old figure in the file
  until the timing is edited, would keep the overstated net 183A exists to stop and set the file
  against the model. Fixed in the claims instead - FR-036 and the edge-case note, the plan, this
  record, `contracts/timing.md` and `contracts/README.md`, 001's data model, contracts README and
  schema descriptions, the serializer's docstring, Phase 9's checkpoint and 183A's register row -
  and by `test_session.py::test_an_older_sessions_recorded_net_reads_unknown_and_is_saved_as_null`:
  a session with a baseline of 90 and a net of 70 reads its net unknown, keeps every input, and
  is saved again with the net alone changed. It passed on arrival, the behaviour being T066's,
  and fails with the derivation changed to keep an older net. `test_session_fields_015.py`'s
  moved pin is the same case, and its test is renamed to say so.
- Opus, should-fix: the plan's re-check said nothing reads an unrecorded input as 0, which is
  untrue of supervision, verification and false-alarm handling: they start at 0 when a review
  starts, as before 183A, so once the baseline and both new inputs are recorded the net is a
  number whether or not those three were. The re-check now says so; whether the net should wait
  for all five is left to the owner in [`docs/review-backlog.md`](../../docs/review-backlog.md).
- Opus, should-fix, left in the backlog: `swreview timing` and `benchmark time` print `None` for
  an input or a net not recorded, where the report prints `unknown` (older for the baseline and
  the net); and `SCORING_RULES_VERSION` stays 4 although the assisted minutes and the net changed
  meaning (*Not changed*, above).

## R8. Owner decision 186A (2026-11-01): a real design's timing stays in the private fork

**Decision**: a real design's timing figures are company facts and stay in the private fork: the
engineer's baseline, the five assisted inputs and a sitting's update minutes. The public
repository holds only each design's net minutes saved and, later, their median. It changes the
seat plan's step 4.1, where its figures are written, and the public-repository rule in
`CONTRIBUTING.md`, which gains them. Asked as 4A in roadmap run 2's owner round, and applied
before M0-a, the first sitting that times a real design
([`docs/roadmap/README.md`](../../docs/roadmap/README.md), cycle 4).

**Why**: step 4.1 had the engineer write the six numbers under its heading in the findings
document, the sitting's update minutes beside them as a pilot cost, and step 4.5's Record line
asked for the six again; the owner commits that document to this public repository from the
development machine (the plan's step 6.5). The public-repository rule, which calls itself the
full list, named no timing. `swreview timing` writes the same minutes into the run folder's
`session.json` and `report.md`, but a run folder travels only in the handover folder and is never
committed (the plan's step 6.3), so the findings document was the one place that would carry them
into this repository. The north star needs only the net, per design and as a median
([`docs/roadmap/metrics.md`](../../docs/roadmap/metrics.md)), so the figures behind it can stay
private and the measure loses nothing.

**What it changes**: no code. At the seat the six minutes and the update's go in a private note
in the handover folder, `notes\timing.txt`, beside `notes\documents.txt` and `notes\paths.txt`,
and never in the findings document; the note travels by hand with the folder and is never pushed,
and the owner keeps it in the private fork. Step 4.5's command takes the minutes from it; a number
the command prints wrong is named in the findings document, never quoted; and its Record line
records the net saved, as `swreview timing` prints it, and A's run folder stamp. Every check of
what stays out of the findings document names them: rule 5 and steps 6.4 and 6.5 of the plan, the
results sheet's header and its 007 T060 row, the handover's timed run, its findings document and
the owner's reading after the sitting, and the runbook's section 8, whose seat may push the
document on a branch. `CONTRIBUTING.md`'s rule gains a real design's review timing, its net
minutes saved and their median apart. T060, FR-036 and the Assumptions take dated notes. Tasks
T070 to T073, Phase 10 of [tasks.md](tasks.md).

**Not changed**: `swreview timing`, the route and the report, which record and print the six in
the run folder as 183A built them. Fictional figures stay where they are: the quickstart's
Scenario 1 and the tests time fixture folders, and the ledger's median column reads benchmark
studies. The roadmap's own pages are brought up to date by its update runs, not here.

**Built** (2026-11-01, T072), as *What it changes* says. The note is `notes\timing.txt`, in the
folder the setup block already makes: a line `A`, then each number on a line of its own with its
name, and the update's minutes apart in the same note. Section 0.2 says every file in `notes\`,
the note among them, is never pushed, as it says of `notes\documents.txt` and `notes\paths.txt`;
step 6.5 says the note travels in the folder, is never committed and stays in the private fork.
The fail of step 4.5's item 4 that shows a number other than the one typed names the input in the
findings document and copies the printed line into the note, since the general rule for a fail,
quoting the line in Observed, would carry the six minutes. T060's dated note keeps its Done note,
which the development machine commits, to the net saved and the stamp.

**Tests changed on purpose**: none. Two pins were added to `test_workstation_test_plan.py`, and
every existing case of the three modules that read the changed files passed before and after with
no edit, among them the pins that read steps 4.1 and 4.5:
`test_the_timing_is_recorded_once_the_backend_no_longer_holds_the_review`,
`test_the_timing_line_passes_every_input_swreview_timing_takes` and
`test_every_sentence_the_plan_quotes_is_the_products`.

**Tests first**: T071's two pins failed before T072, each for want of the words it pins:
`test_a_real_designs_timing_figures_stay_out_of_the_findings_document` at step 4.1's note, and
`test_every_check_before_the_findings_document_is_committed_names_the_timing_figures` at rule 5.
Read one by one on the documents as they stood, 41 of their 42 checks were red; the one that held
is the guard that section 0.2's notes are never pushed. In a first draft the check that step 4.1's
old sentence is gone read the plan unflattened, and so held against the old text, which breaks
that sentence across lines; both checks that an old sentence is gone read the flattened plan
before the pins were committed, and were red with the rest.

**Gates** (T073; 2026-11-01), on T073's tree:

- Python 3.12.3, in the worktree's own environment (`uv sync --python 3.12 --all-extras`), and
  3.11.16 (`uv run --python 3.11 --isolated --all-extras`), the tokenizer required, over the three
  modules that read the changed files - `test_workstation_test_plan.py`,
  `test_workstation_handover.py` and `test_update_workstation_script.py`: 296 passed on each.
- `ruff check src tests` clean.
- The link check over the cycle's changed Markdown: 302 relative links, anchors included, none
  broken. Every changed file LF in the index.
- No C# file changed, so no C# gate. Not run in this lane: the whole non-live suites, which run
  before the pull request and in its CI, among them
  `test_tracked_files_carry_no_recorded_number.py`, which reads the owner's lists outside the
  repository. No SOLIDWORKS process, seat task, or paid or live test ran.

**Review** (Tier 2, decision 180A; 2026-11-01): one Codex review of the branch, two findings,
both fixed test first under T072.

- High: step 4.5 still had the engineer copy an exit-code-1 message of `swreview timing`, paths
  replaced, into the findings document, and the command's messages carry figures: a refused
  input's `input_value=` (`error: ValidationError: 1 validation error for Timing ...`), and, when
  the session's stored timing is malformed, the stored baseline's. Fixed: a timing failure goes
  whole into `notes\timing.txt`, and the findings document records only its exit code, its
  error's name and the field it names, an exception that step 4.5 states and that step 1.4's rule
  to quote a failing line, step 6.4's check and the results sheet's rule each name. Every line
  steps 4.1 and 4.5 print or record was read for a figure: of step 4.5's printed lines only the
  net saved may be recorded, the first, the six minutes, being compared with the note and never
  copied; `report.md`'s Timing section holds the same minutes and the runtime; and the stored
  baseline is now checked, not printed (`session.json carries a baseline: True`).
- Medium: when the engineer watched the whole review, supervision is its start-to-end span, and
  step 4.1's Record line put both times in the findings document, the point this record had left
  open. The owner answered on 2026-11-01 (13A), to be registered as decision 192A: the review's
  start and end times go in `notes\timing.txt` with the six minutes; the findings document keeps
  only the net saved and A's run folder stamp, so no private figure can be worked out from it;
  the runtime stays in the run folder, which is never committed. Fixed: step 4.1 notes the times
  in the note and its Record line keeps them out; rule 5, steps 6.4 and 6.5, the results sheet's
  header, the handover's timed run, its findings document and the owner's reading after the
  sitting, the runbook's section 8, T060, `CONTRIBUTING.md`'s rule and the Assumptions' note name
  them, as decision 192A (the owner's answer of 2026-11-01, 13A).
- Tests changed on purpose, none loosened: T071's two pins, each with a dated note - the first
  gains the exception, the printed lines and the times, the second the times and decision 192A in
  each of its nine places - and a guard,
  `test_no_line_sends_a_real_designs_timing_figure_to_the_findings_document`: no Record
  instruction of the plan asks for a timing figure before its first `never`; no clause of the
  plan, the results sheet, the handover or the runbook that names the findings document or
  Observed names one unless it sends it to the note or says never; and no clause of steps 4.1 and
  4.5 copies or quotes a message or a line outside the note.
- Tests first: the three pins failed on cycle 4's documents as T073 left them, before the fix and
  not only before cycle 4 - the first at step 4.5's exception, the second at rule 5, the third at
  step 4.1's Record line. Read one by one, 27 of the 28 new checks were red; the one that held is
  the guard's clause scan, which has nothing to find since T072 and flags the plan as it stood
  before cycle 4, as its Record and copy scans flag that plan's two Record lines and its copy
  instruction. After the fix the guard caught one of the fix's own sentences, in the handover,
  which sent the times to "the note" without naming it; it names `notes\timing.txt` now.
- Gates, on the fixed tree: the three modules, 297 passed on each of Python 3.12.3 and 3.11.16
  with the tokenizer required; `ruff check` clean; the link check over the cycle's changed
  Markdown clean (302 relative links); every changed file LF in the index.
- Not changed: step 4.2 still notes B's start and end times, since B is not timed at this
  sitting and they bound no one's supervision; a sitting that times B routes them as step 4.1
  does. [`docs/roadmap/metrics.md`](../../docs/roadmap/metrics.md) keeps "Review wall time" as a
  guardrail, and its pages are its update runs' to change: under decision 192A a timed review's
  runtime stays in its run folder, so that row cannot take one.

*Changed 2026-11-02 (owner decision 195A; R9):* where this section has the findings document
record A's run folder stamp, it records the folder's date and letter (`20261101-A`), and the full
stamp goes in `notes\timing.txt` with the review's start and end times.

*Changed 2026-11-02 (owner decision 196A; R10):* where this section leaves a timed review's
runtime in its run folder, the runtime goes in `notes\timing.txt` too, with every other duration
of that review and its start and end times, and never in the findings document.

## R9. Owner decision 195A (2026-11-02): a timed review's run folder by its date and letter

**Decision**: a timed real design's run folder is written in the findings document by its date
and letter only (for example `20261101-A`). Its full stamp, `yyyyMMdd-HHmmss`
(`extractor/SwReview.AddIn/Review/RunFolders.cs`), is the moment Review was pressed; it goes in
the private note `notes\timing.txt` with the review's start and end times (192A), so that no
private figure can be worked out from the findings document. It changes 192A's "the run folder's
stamp"; a review not timed, B's at a sitting (190A), keeps its full stamp. Asked as 21A in
roadmap update run 3's owner round; applied before M0-a, as cycle 8
([`docs/roadmap/README.md`](../../docs/roadmap/README.md)).

**Why**: R8 had the findings document record A's run folder stamp beside the net saved, and that
stamp is the timed review's start, to the second, which 192A keeps in the note.

**What it changes**: no code. The seat plan's rule 5 states it and step 4.1 notes the full stamp
in `notes\timing.txt`; every line that records the timed review's folder - step 4.5's and step
4.11's Record lines, step 4.10's for a review timed there (M0-a times one, the roadmap's M0),
step 6.2's, and the rule for Observed of step 1.4 and the results sheet - writes it by its date
and letter, and a clock time noted when SOLIDWORKS stops answering in a timed review goes in the
note; every check of what stays out of the findings document, the handover, the runbook's
section 8, `CONTRIBUTING.md`'s rule and T060's note name the full stamp. Tasks T074 to T077,
Phase 11 of [tasks.md](tasks.md).

**Not changed**: `RunFolders.cs` and the folders' names; the zips of step 6.3 and the exports of
step 6.2, which carry whole names and travel only in the handover folder; an untimed review's
stamp (steps 4.2, 4.8, 4.9 and 5.1).

**Built** (2026-11-02, T076), as *What it changes* says. Rule 5's example of a full stamp, and
the results sheet's, carry B's letter now (`20261001-101112-B`), A's review being the one timed;
step 4.1's note takes the date and time the folder's name begins with (`20261101-101112`); step
4.5's Record line reads `<date>-A` where it read `<stamp>-A`. The runbook's section 8 listed "run
folder names" among a findings document's evidence, and a name begins with its stamp: it lists
run folders by stamp and letter, as rule 5 does.

**Tests changed on purpose**, each with a dated note, none loosened:
`test_a_real_designs_timing_figures_stay_out_of_the_findings_document` (step 4.5's Record
literal), `test_every_check_before_the_findings_document_is_committed_names_the_timing_figures`
(each of its nine places also names the full stamp, the date and letter and 195A; section 0.2 the
full stamp), `test_no_line_sends_a_real_designs_timing_figure_to_the_findings_document` (the
full stamp is a timing figure, and no line shows a full stamp or `<stamp>` with A's letter) and
`test_the_specs_readme_counts_a_task_173a_closed_as_done` (007's row, pinned since T074). New:
`test_a_timed_reviews_run_folder_is_written_by_its_date_and_letter`.

**Tests first**: T075's four pins failed before T076, each for want of the words it pins - the
first at step 4.5's Record line, the places pin at rule 5, the guard at rule 5's example and step
4.5's `<stamp>-A`, the new pin at rule 5. Read one by one, 45 of their 47 new or changed checks
were red; the two that held are the guard's checks of its own patterns, which read no document.
After T076 all 115 checks of the four pins hold. The README pin was red against 68 / 5 / 0 at
T074 and against 69 / 8 / 0 at T077 before each recount.

**Gates** (T077; 2026-11-02), on T077's tree:

- Python 3.12.3, in the worktree's own environment, and 3.11.16 (`uv run --python 3.11
  --isolated --all-extras`), the tokenizer required, over the seven modules that read the changed
  files - `test_workstation_test_plan.py`, `test_workstation_handover.py`,
  `test_update_workstation_script.py`, the three that read the task lists through
  `tests/support/seat_tasks.py` (`test_seat_assumptions.py`, `test_seat_switch_evidence.py`,
  `test_remodel_ledger.py`) and the identifier scan, `test_tracked_files_carry_no_recorded_number.py`,
  which ran against the owner's lists: 488 passed on each, none skipped.
- `ruff check src tests` clean.
- The link check over the cycle's changed Markdown: 309 relative links, anchors included, none
  broken. Every changed file LF in the index.
- No C# or page file changed, so no C# gate. Not run in this lane: the whole non-live suites,
  which run before the pull request and in its CI. No SOLIDWORKS process, seat task, or paid or
  live test ran.

## R10. Owner decision 196A (2026-11-02): a timed review's runtime and durations in the private note

**Decision**: a timed real design's review runtime, its start-to-end span, and every other
duration of that review go in the private note `notes\timing.txt` with its start and end times,
never in the findings document, so that no private figure can be worked out from it: when the
engineer watched the whole review, its runtime is its supervision minutes, which decision 186A
keeps private. A review not timed, B's at a sitting (190A), keeps its durations. It widens 192A
(R8) and 195A (R9). Asked as 24A during cycle 8, and applied in that cycle, before M0-a
([`docs/roadmap/README.md`](../../docs/roadmap/README.md)).

**Why**: rule 5 kept the timed review's start and end times, its full stamp and every clock time
of it out of the findings document, but no line of the seat plan, the results sheet, the handover
or the runbook kept its runtime, or another duration of it, out. Step 4.1's Record line asks for
the facts `Show-ReviewFacts` prints, which hold the drawing phase's milliseconds and the seconds
from `session.started` to the first `text.delta`, and for the usage line, which ends with the last
round's seconds; step 4.11 records the same facts lines on A's folder; step 4.10 records four
timings, one of them a timed review's when a sitting times a review there (M0-a, the roadmap's
M0); and the runbook's section 8 lists durations among the evidence a findings document carries.
R8 left the runtime in the run folder, which is never committed, without saying that it stays out
of the findings document.

**What it changes**: no code. Rule 5 states it. Step 4.1 notes the runtime in `notes\timing.txt`,
and its Record line sends the facts' and the usage line's durations there; step 4.11's Record line
does the same for the facts lines, step 4.5's item 1 for A's usage line, and step 4.10's item 7
and Record line, with the results sheet's 4.10 row, for a timed review's timings; what the plan
says of `Show-ReviewFacts` and `Show-SetupTime` run on a timed review's folder, and of a duration
noted when SOLIDWORKS stops answering in a timed review, says the same. Every check of what stays
out of the findings document names the runtime and its other durations: rule 5, section 0.2,
steps 6.4 and 6.5, the results sheet's header, the handover's timed run, its findings document
and the owner's reading after the sitting, the runbook's section 8, whose durations leave a timed
review's out, `CONTRIBUTING.md`'s rule and T060's note. Tasks T078 to T081, Phase 12 of
[tasks.md](tasks.md).

**Not changed**: every review not timed keeps its durations in the findings document - D's drawing
phase at step 3.4, B's times at steps 4.2 and 4.3 and the handover's step 12, and the untimed
reviews' timings at step 4.10; `report.md`'s Timing section and the rest of the run folder, which
hold the runtime and travel only in the handover folder (step 6.3); `swreview timing`, the route,
the report and the plan's commands, whose printed lines are routed, not changed.

**Built** (2026-11-02, T080), as *What it changes* says. Rule 5 sends the runtime, from start to
end, and every other duration of a timed review to `notes\timing.txt`, never the findings
document, and a review not timed, B's among them, keeps its full stamp and its durations. Step
4.1's Record line names what the facts and the usage line show that is a duration - the `drawing
phase` line's milliseconds, the `seconds from session.started to the first text.delta` line and
the usage line's `last round <n> s` - and sends them to the note. Step 4.10's item 7 and Record
line, the results sheet's 4.10 row and the handover's step 22 name a timed review's timings in
the words step 4.10's Record line already used for its run folders ("a timed review's ... only").
What the plan says of `Show-SetupTime` holds for a sitting that runs it on a timed review's
folder: this sitting runs it on B's alone (step 4.3). T060's note was written with the records,
at T078.

**Tests changed on purpose**, each with a dated note, none loosened:
`test_a_real_designs_timing_figures_stay_out_of_the_findings_document` (step 4.1's opening and
Record line; `CONTRIBUTING.md`'s rule),
`test_every_check_before_the_findings_document_is_committed_names_the_timing_figures` (each of
its nine places also names the runtime, a duration and 196A; section 0.2 the runtime and every
other duration; the runbook's section 8 durations other than a timed review's),
`test_no_line_sends_a_real_designs_timing_figure_to_the_findings_document` (the runtime is a
timing figure; a new scan reads the Record lines of steps 4.1, 4.5, 4.10 and 4.11 and the
results sheet's rows of those steps, and none asks for a duration, the facts or the usage line
without sending it to `notes\timing.txt`; B's steps and every untimed review's are not read for
one), `test_a_timed_reviews_run_folder_is_written_by_its_date_and_letter` (rule 5, the hang, the
two commands, steps 4.5, 4.10 and 4.11, the results sheet's header and 4.10 row, the handover's
steps 22 and 23) and `test_the_specs_readme_counts_a_task_173a_closed_as_done` (007's row). No
new test: the pins and the guard that read these places were extended, not copied.

**Tests first**: T079's four pins failed before T080, each for want of the words it pins - the
first at step 4.1's opening, the places pin at rule 5, the guard at the Record lines of steps
4.1, 4.10 and 4.11 and the results sheet's 4.10 row, cycle 8's pin at rule 5. Read one by one, 35
of their 42 new or changed checks were red; the seven that held are T060's two, whose note T078
wrote, the guard's Record and clause scans with the runtime added, which had nothing to find, and
its three checks of its own patterns, which read no document. After T080 all 42 hold. The README
pin was red against 72 / 5 / 0 at T078 and against 73 / 8 / 0 at T081 before each recount.

**Gates** (T081; 2026-11-02), on T081's tree:

- Python 3.12.3, in the worktree's own environment, and 3.11.16 (`uv run --python 3.11
  --isolated --all-extras`), the tokenizer required, over the seven modules that read the changed
  files - `test_workstation_test_plan.py`, `test_workstation_handover.py`,
  `test_update_workstation_script.py`, the three that read the task lists through
  `tests/support/seat_tasks.py` (`test_seat_assumptions.py`, `test_seat_switch_evidence.py`,
  `test_remodel_ledger.py`) and the identifier scan, `test_tracked_files_carry_no_recorded_number.py`,
  which ran against the owner's lists: 488 passed on each, none skipped.
- `ruff check src tests` clean.
- The link check over the Markdown changed for 196A: 314 relative links, anchors included, none
  broken. Every changed file LF in the index.
- No C# or page file changed, so no C# gate. Not run in this lane: the whole non-live suites,
  which run before the pull request and in its CI. No SOLIDWORKS process, seat task, or paid or
  live test ran.

## R11. The timing note's seat command (cycle 14, 2026-11-02)

**What**: one function in the seat plan's setup block, `Save-TimingNote '<run folder>'
'<letter>'`, appends a timed review's figures to `notes\timing.txt` in one block headed by the
run folder's date and letter (`20261101-A`). The owner picked it on 2026-11-02 (roadmap update
run 4's round, 29; cycle 14, review Tier 3). It carries no decision of its own: it serves 186A,
192A, 195A, 196A and 197A.

**Why**: at a timed review the engineer copied into the note by hand the run folder's full
stamp, the start and end times, and every duration the plan's commands print for that review:
`Show-ReviewFacts`' drawing-phase milliseconds and its seconds to the first `text.delta`, the
usage line's round times and `Show-SetupTime`'s time. Each copy is a chance to get a figure wrong,
or to carry one off the console into the findings document.

**What stays where**: the block goes in `notes\timing.txt`, beside the six minutes and the
update's minutes, which the engineer still types; the findings document keeps the net saved and
the folder's date and letter, as before; the run folder is only read; the console shows the
note's path and nothing else.

**Defaults taken**:

1. The start is the run folder's full stamp, the moment Review was pressed (195A); the end is
   `session.json`'s `ended_at`, the end of the review's last turn, in the seat's local time; the
   runtime is the end less the start, in minutes to one decimal.
2. The durations are the `drawing phase` and `text.delta` lines `Show-ReviewFacts` prints and the
   line `Show-SetupTime` prints, word for word, and each `usage` event's `latency_s` as
   `round <n>: <s> s`, to two decimals as the usage line shows its last round.
3. The letter is given, never guessed: the folder's name holds the document's real name, not its
   letter.
4. It writes nothing, and says so, for a folder whose name does not begin with a stamp, that
   holds no `session.json` and `events.jsonl`, or whose review has not ended.
5. Step 4.1 runs it once the review has ended, after the answers' turn if it asked questions, and
   before step 4.4 can send it anything; after a Retry, on the stopped run's folder too, so the
   note holds both runs of the timed review.

**Built** (2026-11-02, T084), in the seat plan: the function, after `Show-SetupTime`, takes the
durations from what the two commands print, kept in the block and never printed, and reads the
rounds from `events.jsonl`; what the commands do gives it a bullet, and `Show-ReviewFacts`' and
`Show-SetupTime`'s bullets say it writes their timings; rule 5 names it; step 4.1's opening says
it writes the start and end, the full stamp and the runtime, and a timing bullet runs it, with a
warning that a Notepad left open on the note would save over the block; step 4.1's and step
4.11's Record lines say it wrote the durations. It appends a blank line first, so a last line
Notepad left unended stays whole.

**Not changed**: step 4.5's item 1 still has the engineer note A's `last round <n> s` in the
note: it is 009 T083's reading before and after a restore, taken after step 4.4 may have sent
A's review a turn, which the block written at step 4.1 does not hold. Step 4.10's four timings
are read by hand from the backend log or the host's statuses, as that step says, so a timed
review's stay typed, as does a time noted when SOLIDWORKS stops answering. At M0-a rule 5
names the command for the review its table times; that table is 197A's, written when M0-a is
planned. The handover, the results sheet, the runbook and `CONTRIBUTING.md` say what stays where,
not how it is copied, and are unchanged.

**Tests changed on purpose**, with a dated note, none loosened:
`test_a_real_designs_timing_figures_stay_out_of_the_findings_document` (step 4.1's opening: the
command writes the start and end the engineer noted) and
`test_the_specs_readme_counts_a_task_173a_closed_as_done` (007's row). New:
`test_save_timing_note_appends_a_timed_reviews_figures_and_prints_only_where_it_wrote`,
`test_save_timing_note_writes_nothing_for_a_folder_it_cannot_time`,
`test_save_timing_note_reads_the_run_folder_and_the_backend_log_and_writes_only_the_note` and
`test_step_4_1_writes_the_timed_reviews_figures_with_save_timing_note`. The two that run the
function in Windows PowerShell point `%LOCALAPPDATA%` at a fictional backend log, so the
machine's own logs are never read, and stand this interpreter in for `uv`.

**Tests first**: T083's eight cases failed before T084, each for want of the function or its
words. After T084 they pass, and four mutations of the function - an overwrite for the append, a
printed figure, a misnumbered round, a write in the run folder - each turned them red. The README
pin was red against 76 / 5 / 0 at T082 and against 77 / 8 / 0 at T085 before each recount.

**Gates** (T085; 2026-11-02), on T085's tree:

- Python 3.12.3, in the worktree's own environment, and 3.11.16 (`uv run --python 3.11
  --isolated --all-extras`), the tokenizer required, over the seven modules that read the changed
  files - `test_workstation_test_plan.py`, `test_workstation_handover.py`,
  `test_update_workstation_script.py`, `test_seat_assumptions.py`, `test_seat_switch_evidence.py`,
  `test_remodel_ledger.py` and the identifier scan, `test_tracked_files_carry_no_recorded_number.py`:
  495 passed on each, none skipped.
- `ruff check src tests` clean.
- The link check over the cycle's five changed Markdown files: 114 relative links, anchors
  included, none broken. Every changed file LF in the index.
- No C# or page file changed, so no C# gate. No SOLIDWORKS process, seat task, or paid or live
  test ran.

*Changed 2026-11-02:* that tree came before cycle 14's own findings; the fixed tree's gates are
the last part of this section.

**Cycle 14's own findings** (review Tier 3, decision 180A: the gates and CI only, no review;
2026-11-02, under T085).

**Settled**, test first: a run folder whose name holds brackets got a wrong or missing setup
line. A run folder's name holds its document's name, and Windows PowerShell reads a path given by
`-Path`, or by position, as a wildcard, `[2]` being the one character `2`. `Show-SetupTime` read
`"$run\events.jsonl"` so: for `fictional plate [2]` it read no file, printing an error and no
setup line, or, beside a folder `fictional plate 2`, it read that folder's `events.jsonl` and
timed another review's setup; and `Save-TimingNote` wrote the line it printed. Every path the
setup block's helpers read or write now takes `-LiteralPath`, each helper checked:

- `Show-SetupTime`'s `events.jsonl`;
- the logs folder `Show-SetupTime` and `Show-DrawingReadLog` read: `Get-ChildItem -LiteralPath`
  takes the folder and `-Filter` the logs' name pattern, and pipes the files to `Select-String`,
  the same files in the same order as the `-Path` pattern read;
- `Push-Location` into `$R\reviewer`, in the six helpers that run `uv`;
- `Save-Fingerprint`'s `notes\paths.txt`, dumps folder and CSV, and `Compare-Fingerprint`'s two
  CSVs.

`Save-TimingNote`, `Show-FindingsByType` and `Get-SeatHash` already read literally.
`Split-Path $run -Leaf` stays: it only cuts the string, and Windows PowerShell 5.1 takes no
`-Leaf` with `-LiteralPath`.

- Tests changed on purpose, this cycle's own, with a dated note, not loosened:
  `test_save_timing_note_appends_a_timed_reviews_figures_and_prints_only_where_it_wrote` runs on
  four folders, through the `plan_function` harness: the plain name; a name with brackets, alone
  and beside a folder the brackets match, whose review started 30 s later; and the plain name
  with the backend logs in a folder whose name holds brackets. `timed_run` takes the folder's
  name.
- New: `test_every_path_the_setup_blocks_helpers_read_or_write_is_literal`, read on every
  platform - every call in the helpers that reads or writes a path names it by `-LiteralPath`,
  but a `Select-String` fed by a pipe and `Split-Path $run -Leaf` - and
  `test_show_drawing_read_log_reads_the_tool_service_logs_in_a_folder_with_brackets`.
- Tests first: red, each for the finding's reason, while the plain case passed. Alone, no
  `events.jsonl` and an error; beside the match, a setup of 30.0 s, the other folder's; under the
  bracketed logs folder, `no POST /sessions 201 line after session.started`; the static pin
  listing 14 calls - `Push-Location` in six helpers, `Show-SetupTime`'s two reads,
  `Show-DrawingReadLog`'s, and `Save-Fingerprint`'s and `Compare-Fingerprint`'s five;
  `Show-DrawingReadLog` printing nothing. Green after the fix, with no other test changed.

**Settled**, the second item left open below, test first (2026-11-02): outside the setup block's
helpers, the plan still gave a check folder and the run root by `-Path`. Step 5.2's
`Select-String` read `"$run\report.md"` so: for a `-standards` folder whose name holds brackets
it read no file and printed `False`, the step's pass. The run root is the folder the engineer
types in the pane, whose name the run root's rule (`RunRootRule`, decisions 154A and 160A) lets
hold brackets, and a bracket there left each listing of it empty, with no error: step 5.3 printed
`no remodel folder` beside the tab's copy, step 6.2 would export no review and step 6.3 zip no
run folder. A wildcard can bite there, so:

- step 5.2 reads `report.md` by `-LiteralPath`;
- the run root's five listings take it by `-LiteralPath`: step 5.3's two, T303a's wait for the
  copy, with `"$H\runs-t303a"`, step 6.2's exports and step 6.3's folders.

Not changed, each exempt by name in the new pin: the setup block's `%APPDATA%` read (line 458),
which holds no document's name and lies in the account's profile, named after the Windows
account, whose name cannot hold `[` or `]`, as do `%LOCALAPPDATA%`, `%TEMP%` and the handover
folder, named by its date; and the checkout, `$R`, read at lines 610 and 611 and by the steps'
`cd`. The checkout holds no document's name, and a bracket in its path fails the block's own
check at once, a red `Cannot find path` and then `checkout found: False`; making it literal would
touch some twenty commands, a line of the handover and five pins, so it stays in the backlog as a
note.

- Tests, new: `test_every_path_the_plans_powershell_builds_from_a_run_or_check_folder_is_literal`,
  read on every platform - the helpers' pin carried to every command of the plan's PowerShell,
  its blocks and the commands in its text: a command gives a path by `-Path` only when every name
  it gives is in `NO_DOCUMENT_NAME`, the explicit exemptions, each in use, or when it only cuts
  the string, so `$run`, `$check` or a name not yet written is read by `-LiteralPath`;
  `test_step_5_2_reads_the_report_of_a_check_folder_whose_name_holds_brackets`, step 5.2's line
  on a `-standards` folder, plain and with brackets, whose report says no revision table was
  found, or does not; and
  `test_step_5_3_finds_the_remodel_folder_under_a_run_root_whose_name_holds_brackets`.
- Changed on purpose, this cycle's own, with a dated note: `PATH_CMDLET` matches
  `Compress-Archive` and `cd` too, which the steps use; the helpers use neither.
- Tests first: red, each for the finding's reason, while the plain cases passed. The whole-plan
  pin listed six calls, step 5.2's and the five listings; step 5.2's line printed `False` for the
  bracketed folder whose report says it; step 5.3's check printed `no remodel folder` under
  `runs [pilot]`. Green after the fix, with no other test changed. Five mutants of plan lines
  already literal - the copy of the run folders written in step 6.3's text, step 6.3's
  `Compress-Archive`, step 4.5's `report.md` read and its kept copy, a `cd` into a run folder -
  each turned the whole-plan pin red, listing that call alone; the plan was restored byte for
  byte, its sha256 checked.

**Left open**, in [`docs/review-backlog.md`](../../docs/review-backlog.md) under cycle 14:

- `Show-SetupTime` takes the first `POST /sessions` 201 in the backend logs at or after the run's
  `session.started`. If the timed review's own post was refused, that 201 is another review's
  answer, and `Save-TimingNote` writes the line it gives.
- The commands outside the setup block's helpers still pass a run folder, the run root or the
  checkout by `-Path`. Step 5.2's `Select-String` on a check folder's `report.md` prints `False`,
  its pass, for a folder whose name holds brackets, without reading the report; the run-root
  listings of steps 5.3, 6.2 and 6.3 and the block's own `Set-Location $R` read a bracket as a
  wildcard too. *Changed 2026-11-02:* settled above, all but the checkout, `$R`, which stays in
  the backlog as a note.

**Gates** (2026-11-02), on the fixed tree:

- Python 3.12.3, the tokenizer required, over the seven modules above: 500 passed, none skipped.
- `ruff check src tests` clean.
- The link check over the cycle's six changed Markdown files, `docs/review-backlog.md` among
  them: 116 relative links, anchors included, none broken. Every changed file LF in the index.
- No C# or page file changed, so no C# gate. No SOLIDWORKS process, seat task, or paid or live
  test ran.

*Changed 2026-11-02:* that tree came before the second item's fix; the final tree's gates follow.

**Gates** (2026-11-02), on the final tree:

- Python 3.12.3, the tokenizer required, over the seven modules above: 507 passed, none skipped.
- `ruff check src tests` clean.
- The link check over the cycle's six changed Markdown files: 117 relative links, anchors
  included, none broken. Every changed file LF in the index.
- No C# or page file changed, so no C# gate. No SOLIDWORKS process, seat task, or paid or live
  test ran.
- *Changed 2026-11-03:* the whole suites ran on the final tree, cycle 14 stacked on cycles 12, 13
  and 11 (`13611b22`): 18,914 passed and 5 skipped on Python 3.12.3 and the same on 3.11; ruff
  clean; the identifier scan, 58 passed (T085's last sub-item).

## R12. Minutes typed on the Review page (cycle 18, 2026-11-03)

**What**: a minutes form at the end of the Review page's Results: one field per human timing
input, each labelled from the words file, and Save, which posts the six to
`POST /sessions/{chat_id}/timing` ([contracts/timing.md](contracts/timing.md) section 3), the
route that records them on the review the backend holds. Roadmap run 5 proposes it as hole
H-g-010's feature route, second in its brief; it is built before the owner's pick (review Tier
2). No decision id: it serves 183A and 186A as they stand.

**Why**: the seat plan records a timed review's minutes with `swreview timing` after a backend
restart (step 4.5, item 4), because the backend saves the review it holds over any write to its
folder (`reviewer/src/swreview/chat/sessions.py`, `record_disposition`). The restart ends the
pane's live session, so from then on the pane's triage is locked and a console triage can be saved
over unannounced (H-g-010). The route writes the session the backend holds, so nothing saves over
it, but no page called it; the spec's Assumptions called a pane control a follow-on.

**Settled**, the defaults taken:

1. The words are two groups of the words file's `labels`, after `note`, so `source` stays just
   before `errors`: `timing`, one word per input keyed by `TIMING_INPUTS` in their order, and
   `timing_form`, the form's heading, its button and the line a save leaves. The page draws one
   field per key of `timing`, in its order, and posts each under its key, so it holds no list of
   the inputs of its own; the words test ties the group to `TIMING_INPUTS`. With no labels, or a
   backend that names neither group, there is no form (009 FR-030: the page as it was).
2. Where: the last panel of Results, after the pinned answers: the minutes are the last thing done
   before leaving a review, and Results' top is the review in ten seconds. Hidden, as Results' other
   parts are, while another document is active.
3. When: shown on a live review once a turn of it has ended - its stream's `turn.ended` or
   `session.ended`, which a waiting review's checks end with too, or a live snapshot not mid-turn;
   off while a turn runs, a review starts, a Send is on its way or a save is; absent on a
   read-only restore. *Changed 2026-11-03 (the Tier 2 review, below):* and gone once the backend
   takes the review's minutes no more - another backend replaced the one that held it, or its turn
   failed.
4. The body: all six keys, a blank field as null, which keeps what is recorded; the number
   typed, as a number; and text that is not a number as typed, which the route refuses by name
   (`InvalidTiming`), so the page holds no rule about minutes. The fields are text boxes, so what
   was typed is what is sent and what stays. Save is off while every field is blank: it would
   record nothing.
5. After a save, the words file's line and nothing of the reply, which carries the figures and the
   net. After a refusal, its class's sentence from `labels.errors` and the class in the Details
   fold, never the backend's message, which names a refused figure. Either way the fields keep
   what was typed, and the line goes once a field is typed in again.
6. The form starts blank on every review it shows. The snapshot carries no timing, and carrying it
   would show supervision, verification and false alarms as 0 on every fresh review - their
   starting value, which the record cannot tell from a recorded 0 (the backlog's cycle 1 item) - as
   if the engineer had typed them. So the snapshot is unchanged, and a review switched to never
   shows another review's figures. *Changed 2026-11-03 (the Tier 2 review, below):* but for what
   was typed on it and not saved, kept in page memory per review, as the questions' drafts are.
7. The figures: in the fields, and where the route writes them, as `swreview timing` writes them -
   the run folder's `session.json`, and `report.md` and `attention.json` rendered again (186A);
   never in the Transcript or the page's other text, the findings document or a repository file.
8. The seat plan: step 4.1 has the six typed on the page before the engineer leaves A's review,
   once every finding is judged; step 4.5's item 4 checks what the page wrote and is the console
   fallback when the backend restarted before they were saved. Item 2's restart stays: it is 009
   T083's restore, not the timing's alone. M0-a's row types the minutes on the page.

**Not changed**: the route's rules (contracts/timing.md section 3); the pane's proxy, which already
forwards the call as one that starts no turn (`BackendProxyHandler.StartsATurn`); `swreview
timing`; the snapshot.

**Built** (2026-11-03). T088, the words: `labels.timing` and `labels.timing_form` in
`reviewer/src/swreview/report/review_words_v1.yaml`, after `note`, and `Labels` naming them in
`reviewer/src/swreview/report/summary.py`, whose `TimingInput` copies the six; the pane fixtures
regenerated by their generators, `review-send-failure-events.json`'s pin moved with its source,
and `LabelsSample.cs` mirroring the words. T090, the page: `#timing`, the last panel of Results in
`index.html`; `render.js`'s `timingForm`, which draws it from the labels; and in `app.js` its
state (`turnEnded`, `timingPending`), `renderTiming` beside the question controls, `saveTiming`
through Results' one click listener, `timingLine`, and `clearTiming`, which `resetTranscript`
calls; `app.css` hides it with the rest of a review shown for another document. And the seat plan:
M0-a's row; step 4.1's minutes bullet, and a bullet of its own for the page; step 4.5's item 4,
the check of what the page wrote, the command a block of its own for the fallback, and its Record
line; and the handover's timed run. Dated notes in 009 `contracts/plain-words.md` section 1 and
`contracts/views.md` section 2, 002 `contracts/chat-api.md` and `contracts/timing.md` section 3.

**Tests changed on purpose**, each with a dated note, none loosened:
`reviewer/tests/unit/test_chat_server.py::test_labels_answer_the_words_files_card_vocabulary` (the
two groups); in `reviewer/tests/unit/test_workstation_test_plan.py`,
`test_the_timing_is_recorded_once_the_backend_no_longer_holds_the_review`, renamed
`test_the_minutes_are_typed_on_the_review_page_and_the_console_is_the_fallback`,
`test_after_s1_come_m0s_two_sittings_then_s2` (M0-a's row),
`test_a_real_designs_timing_figures_stay_out_of_the_findings_document` (step 4.5's Record line)
and `test_the_specs_readme_counts_a_task_173a_closed_as_done` (007's row, at T086 and T091); and
`ReviewPageTriageTests.Whole`, made internal for the new class, nothing it checks changed. New:
three tests in `reviewer/tests/unit/test_review_words.py` (four cases) and the ten facts of
`extractor/SwReview.AddIn.Tests/ReviewPageTimingTests.cs`.

**Tests first**: T087's five failed for want of the words while the two modules' 357 other cases
passed. T089's nine facts failed for want of the form - eight found no box to type in, one no
form shown - and its three pins for want of the plan's words, while the plan module's 303 other
cases passed; `WithNoLabelsThereIsNoForm` passed at once, a guard. Five mutants of the page, each
file restored byte for byte, its sha256 checked: a form drawn with no labels failed the guard and
the nine other facts; a refusal printing the backend's message failed
`ARefusalSaysItsSentenceAndKeepsTheFigures` alone; a reply written on the review shown when it
lands failed `AReplyLandingAfterAReviewSwitchWritesNothing` alone; boxes kept across a review
switch failed it and `AnotherReviewShowsTheFormBlank`; the form shown before a turn has ended
failed `TheFormIsOffWhileATurnRuns` alone. The README pin was red against 80 / 5 / 0 at T086 and
against 81 / 10 / 0 at T091, before each recount.

**Left open**:

- A review whose minutes were saved shows the form blank again after a switch or a reload
  (default 6): the snapshot sends the page no timing until the record can tell a recorded 0 from
  the starting 0 of supervision, verification and false alarms (the backlog's cycle 1 item).
- A blank box keeps what is recorded, as the route and the console do: neither clears a figure.
- After a backend restart, a review still on screen until it is shown again from its folder keeps
  its form, and Save is refused with `UnknownChat`'s sentence, which says to press Review; the seat
  plan's step 4.1 sends the engineer to the console then. *Resolved 2026-11-03 (the Tier 2 review,
  below):* the form goes, as it does once the review's turn failed.
- The route renders the run folder's `report.md` again, whose Timing section prints the six, as
  `swreview timing` does: the route is unchanged, so the figures are in the run folder's report as
  before, and nowhere new.
- The backlog's R8, M0-a's console timing lost to a later decision on a waiting review, is
  resolved by M0-a's row typing the minutes on the page (marked in
  [`docs/review-backlog.md`](../../docs/review-backlog.md)).
- *Added 2026-11-03:* a save's retry can land after a newer save of the same review. A save refused
  as running a turn is tried once more a second later (the Tier 2 review's item 5, below). In that
  second the engineer can switch away from the review and back, edit the minutes and press Save. If
  the retry lands last, the backend holds the earlier figures while the page says the later ones are
  recorded. Found while the Tier 2 review's items were fixed. Left, since it needs all four steps
  within about one second.

**Gates** (T091; 2026-11-03), on the final tree:

- Python 3.12.3, in the worktree's own environment, the tokenizer required: the whole non-live
  suite, 18,947 passed and 5 skipped. Python 3.11 (`uv run --python 3.11 --isolated
  --all-extras`), the tokenizer required, over the 101 modules the change touches and those that
  read the changed files - the words, the labels, the pane fixtures, the snapshot, the timing route
  and command, the plan, the handover, the task lists and the tracked files: 5,462 passed.
- `ruff check src tests` clean; the identifier scan
  (`test_tracked_files_carry_no_recorded_number.py`), 58 passed.
- The C# Release build of the solution with zero warnings (`--no-incremental`), then every test:
  10,274 extractor and 4,361 add-in tests passed, the ten new facts among them.
- The link check over the cycle's 11 changed Markdown files: 137 relative links, anchors
  included, none broken. Every changed file LF in the index.
- No SOLIDWORKS process, seat task, or paid or live test ran.
- *Changed 2026-11-03:* that tree came before the Tier 2 review's fixes; their checks are in the
  next paragraph, and the whole suites ran on the stacked tree after them (below).
- *Done 2026-11-03, cycle 18 stacked on cycle 17:* the gates above, and the checks of the Tier 2
  review and of its read-only check below, ran on cycle 18 before it was stacked on cycle 17 (002
  Phase 35, T387 to T392). The two met in the words file, the tests that name its groups,
  `LabelsSample.cs`, the pane fixtures and the records. Each kept both cycles' text, cycle 17's
  first: `first_shown` stays right after `note`, and `timing` and `timing_form` follow it. 007 stays
  86 / 5 / 0. On the stacked tree the pane fixtures' three generators wrote every fixture
  byte-identical, and the goldens did not move. T091's sub-item of the stacking in
  [tasks.md](tasks.md) names each meeting. The whole suites on the stacked tree ran, and T091's
  last sub-item records them.
- *Done 2026-11-03:* the whole suites on the stacked tree (`d710d876`): 18,993 passed and 5
  skipped on Python 3.12.3 and the same on 3.11; ruff clean; the identifier scan, 58 passed;
  C# with zero warnings, then 10,274 extractor and 4,378 add-in tests passed (T091's last
  sub-item).

**The Tier 2 review** (T091; 2026-11-03; decision 180A: one Opus review). No must-fix; five
should-fix, each fixed test first, two things they left in
[`docs/review-backlog.md`](../../docs/review-backlog.md), cycle 18's entry:

1. After a restart, or a turn that failed, the form stayed, and every save was refused with a
   sentence that sends the engineer to Review, a paid one with the send box ticked. Now the form
   goes once the backend takes the review's minutes no more (`state.chatGone`): an `init` naming
   another backend while a review not waiting for Send is on screen (one waiting is shown from its
   folder, as before), an `error` on the review's stream, or a live snapshot's `failed`; it is
   cleared for every review shown next. Default taken: the form goes, rather than every finished
   review being shown read-only from its folder after a restart, which would change the rest of
   the page (backlog). The seat plan's step 4.1 says the console records the minutes once the form
   is gone.
2. Five facts pin what no test held: a review waiting for Send shows the form on its checks'
   `session.ended` alone and its save posts (M0-a's path); another active document hides it; it is
   off while a review starts, a Send is on its way or a save is; and `turn.ended` alone shows it.
3. Minutes typed and not saved are kept per review in page memory (`state.timingDrafts`), as the
   questions' drafts are, and come back when their review is shown again, the automatic switch to
   another document's review among the ways; a save recorded drops them, and a reload loses them,
   as it does the drafts.
4. `InvalidTiming`'s sentence is "Enter each as a number of minutes, 0 or more, then save again.",
   the review's wording: the route refuses a negative figure with the same class, and "Enter the
   minutes as numbers" was untrue of it. The seat plan explains it as a field holding no number, or
   a number below 0.
5. For a moment after a turn's `session.ended` the backend holds the chat `running` while it writes
   the report, and answers a save `409 TurnRunning`. The page tries that save once more a second
   later (`TIMING_RETRY`), the form off meanwhile, and a second refusal is the answer shown.
   Default taken: one retry after one second. Decisions keep the race (backlog).

Tests: ten new facts in `ReviewPageTimingTests.cs` and
`test_review_words.py::test_a_refused_save_of_the_minutes_says_what_each_field_takes`; changed on
purpose, each with a dated note, none loosened, `ARefusalSaysItsSentenceAndKeepsTheFigures` (its
`TurnRunning` save read after the page's held timers run) and
`test_the_minutes_are_typed_on_the_review_page_and_the_console_is_the_fallback` (step 4.1's two
sentences). Red first: the five facts of items 1, 3 and 5 and the two Python cases, each for want
of its change, while the class's 15 others and the two modules' 431 others passed. Item 2's five
guards passed at once and were proved by six mutants, each file restored byte for byte, its
sha256 checked: `app.css` without its `#timing` stale rule, the lock without `startPending`,
without `sendPending` or without `timingPending`, and `endTurn` or `endSession` without its
`turnEnded`, each failing its own fact. The pane fixtures' three generators moved the four that
embed the labels by the one sentence, `review-send-failure-events.json`'s pin with them, and
`LabelsSample.cs` mirrors it. Checks on this tree: every Review page class,
`ErrorLabelsCoverTheHostTests` and `EngineeringContextPaneTests`, 497 passed, after the C# Release
build with zero warnings; the 48 Python modules that read the words, the labels, the pane
fixtures, the plan, the handover and the tracked files, the identifier scan among them, 3,399
passed on Python 3.12.3 with the tokenizer required, and the two changed modules 433 on 3.11.16
(`--isolated`); `ruff check src tests` clean. No task was added, so 007 stays 86 / 5 / 0.

*Added 2026-11-03:* a read-only check of these fixes, no must-fix and five should-fix, all five
taken, as T091's second dated sub-item records. Item 3's drafts: a recorded save's reply deleted
whatever draft its review held when it landed, so minutes typed on the review, shown again before
a slow reply, were lost unsaved; the reply now deletes only the draft its save posted. The second
post that window allows, of the figures shown again, records them again and is left. Item 5's
fact now reads the retry's second; the seat plan's step 4.5, item 4, names a failed review beside
a restart, as step 4.1 does; and two test summaries and 009 `contracts/plain-words.md` section 1
were put right.

## R13. The checkout read literally at the seat (cycle 19, 2026-11-03)

**Settled** (T092, 2026-11-03): every read of the checkout, `$R`, in the seat plan's PowerShell
names it literally. Roadmap run 5's brief proposed it from the third item of cycle 14's findings
in [`docs/review-backlog.md`](../../docs/review-backlog.md), and it was built before the owner's
pick, at review Tier 3 (the gates and CI, no review). It carries no decision of its own.

Why: Windows PowerShell reads a path given by `-Path`, or by position, as a wildcard, `[1]` being
the one character `1`. Cycle 14 left the checkout by `-Path` because a bracket there fails the
setup block's own check at once (R11). Tried in Windows PowerShell 5.1 on a fictional checkout in
a folder `repos [1]`, that holds alone: `Set-Location $R` prints a red `Cannot find path` and the
check `checkout found: False`. Beside a folder the brackets match, `repos 1`, holding a checkout
of its own, it does not: `Set-Location $R` goes into `repos 1` with no red line, the check finds
the update script there and prints `checkout found: True`, and the `swreview-extract` alias runs
that folder's console. The check passes in another checkout.

Defaults taken:

1. Every cmdlet that reads the checkout takes it by `-LiteralPath`: the setup block's
   `Set-Location` and its check's `Test-Path`, step 1.4's `Copy-Item` of the results sheet, step
   1.5's `cd` into the folder the engineer types, and the steps' `cd "$R\reviewer"` and `cd $R`,
   `cd` being `Set-Location`'s alias.
2. The alias takes the console's path escaped, by
   `[Management.Automation.WildcardPattern]::Escape`: `Set-Alias` has no path parameter, and
   PowerShell finds an alias's command by its path read as a wildcard. Escaped, the path names the
   checkout's own console; a path with no bracket is unchanged.
3. A path relative to the checkout stays as it was: step 1.4's `Test-Path docs\...`, by `-Path`,
   and the scripts run as `.\extractor\tools\...`. Windows PowerShell 5.1 resolves a relative
   `-LiteralPath` against the current folder escaped, so in a folder whose path holds brackets it
   finds nothing, while a relative `-Path` reads the right file there, beside a matching folder
   too, and a script run by its relative path is the checkout's own.
4. `git -C $R` stays: git, not PowerShell, reads the path, and reads it literally.
5. The setup block's own check stays, now by `-LiteralPath`: `checkout found: False` still means
   `$R` is not the smart_SW folder itself, and a `CHANGE` line left unchanged or a folder that
   does not exist prints the same red line as before.
6. The handover's step 1.6 line is the plan's, and changes with it. The runbook's alias line,
   which names `<repo>`, and the update and registration scripts, which find the checkout from
   their own folder, are not the plan's PowerShell and are not changed here.

**Built** (T094, 2026-11-03), as *Settled* says. In the seat plan, the setup block's alias,
`Set-Alias swreview-extract ([Management.Automation.WildcardPattern]::Escape("$R\..."))`,
its `Set-Location -LiteralPath $R` and its check's `Test-Path -LiteralPath`; step 1.4's
`Copy-Item -LiteralPath` of the results sheet; step 1.5's `cd -LiteralPath`; and the steps' nine
pairs of `cd -LiteralPath "$R\reviewer"` and `cd -LiteralPath $R`. In the handover, the step 1.6
line, which is the plan's. One more behaviour of Windows PowerShell 5.1, found on the way and not
changed: `Copy-Item` given a missing file under a path that holds brackets prints no red line and
copies nothing, by `-LiteralPath` as by `-Path`, so for such a checkout without the results sheet
step 1.4's copy is silent; the block before it has printed `False` for the sheet by then, which
stops the sitting.

- Tests, new: `test_the_setup_block_finds_a_checkout_whose_path_holds_brackets`, in Windows
  PowerShell, runs the block's alias, `Set-Location` and check on a fictional checkout - plain, in
  `repos [1]` alone, and there beside `repos 1`, a checkout of its own - whose console and update
  script are empty files, so nothing runs: the check ends `checkout found: True`, the window is in
  the checkout, and the alias resolves to the checkout's own console.
- Changed on purpose, each with a dated note, none loosened: `NO_DOCUMENT_NAME`, without `$R` and
  step 1.5's placeholder, with the docstring of
  `test_every_path_the_plans_powershell_builds_from_a_run_or_check_folder_is_literal`; the
  literal lines of `test_the_plan_starts_the_findings_document_once_the_update_has_brought_the_sheet`,
  `test_show_remodel_ledger_hands_each_answers_file_to_swreview_remodel_ledger`,
  `test_show_findings_by_type_prints_each_groups_rows_in_the_reports_order`,
  `test_s1s_steps_hold_what_s1_asks_of_them` and
  `test_save_timing_note_reads_the_run_folder_and_the_backend_log_and_writes_only_the_note`; and
  007's row in `test_the_specs_readme_counts_a_task_173a_closed_as_done`.
- Tests first: nine cases failed before T094, each for want of the literal reads. The whole-plan
  pin listed 22 calls: the block's `Set-Location $R` and `Test-Path`, step 1.4's `Copy-Item`, step
  1.5's `cd` and the steps' nine pairs. The new pin failed in `repos [1]` alone on
  `Set-Location`'s red `Cannot find path`, and beside `repos 1` on the window and the alias in
  `repos 1`, while the check printed `checkout found: True`. The five pins that quote a read of
  the checkout, six cases, failed on their literal lines. All passed after T094 with no other test
  changed. Two mutants of the plan, each restored byte for byte with its sha256 checked: the
  alias's path unescaped turned the new pin's case beside `repos 1` red on the alias alone, which
  the whole-plan pin does not read; the check's `Test-Path` by `-Path` turned the whole-plan pin
  red on that call, and the new pin's bracketed case on `checkout found: False`. The README pin
  was red against 86 / 5 / 0 at T092 and against 87 / 8 / 0 at T095 before each recount.

**Left open**, in [`docs/review-backlog.md`](../../docs/review-backlog.md) under cycle 19: the
update and registration scripts find the checkout, or the add-in's build in it, from their own
folder by `-Path`, and the runbook's alias line names the console by its `<repo>` path. Tried on
the update script's first lines, a checkout under `chk [1]` alone stops at once, and beside
`chk 1` they name that folder's checkout. None is the plan's PowerShell, and the plan clones the
checkout into `C:\smart_SW` or the account's profile, whose paths hold no bracket.

**Gates** (T095; 2026-11-03), on the final tree:

- Python 3.12.3, the tokenizer required: the whole non-live suite, 18,946 passed and 5
  skipped.
- Python 3.11.16 (`uv run --python 3.11 --isolated --all-extras`), the tokenizer required, over the
  seven seat modules, which hold every module that reads the changed files -
  `test_workstation_test_plan.py`, `test_workstation_handover.py`,
  `test_update_workstation_script.py`, `test_seat_assumptions.py`, `test_seat_switch_evidence.py`,
  `test_remodel_ledger.py` and the identifier scan, `test_tracked_files_carry_no_recorded_number.py`:
  510 passed, none skipped, as on 3.12.
- `ruff check src tests` clean; the identifier scan, 58 passed.
- The link check over the cycle's seven changed Markdown files: 124 relative links, anchors
  included, none broken. Every changed file LF in the index.
- No C# or page file changed, so no C# gate, and no words changed. No SOLIDWORKS process, seat
  task, or paid or live test ran.
