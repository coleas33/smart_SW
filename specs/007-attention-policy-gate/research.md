# Research: Attention Policy and Procedural Gate

**Feature**: `007-attention-policy-gate` | **Date**: 2026-09-18 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the 2026-09-18 workstation record (`docs/pane-findings-2026-09-18.md`);
the planning session recorded in [design-brief.md](design-brief.md) (seven subsystem readers,
two bug diagnoses, three designs, three judges, a synthesis and a critic); and a second
reading pass on 2026-09-18 over the exact code the plan names (six readers: timing, the report
models, the check routes, the pre-run and levers, the pane pages, the CLI and benchmark
conventions), each of which opened the files and quoted the real signatures. Where this
document says VERIFIED, a reader opened the file on 2026-09-18 and, where the claim is
behavioural, ran it. Line numbers are as of commit `ce114a1` and will drift; every task
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
problem `docs/pane-findings-2026-09-16.md` records); `20260916-003612-…` is an earlier
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
scenario is rms-only and the spec says so.

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
