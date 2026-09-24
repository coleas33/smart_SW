# Research: The Engineer's Workspace

**Feature**: `009-engineer-workspace` | **Date**: 2026-09-23 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the spec (User Stories 1 and 2 landed on main as `2c48e2b`, `cf3c66e` and
`b5cfcb4`; Stories 3 to 7 are the work); the owner's decisions of 2026-09-22 and 2026-09-23
recorded in the spec's Input line; the pilot workstation's evening packet
(`docs/pane-findings-2026-09-20-review-gui.md`, asks U8 to U16) and `docs/roadmap-2026-09-22.md`
section "009"; the UI analyst's pass of 2026-09-23 (24 facts, 7 increment recommendations, 9 open
questions), which opened the page, the host and the backend and wrote each fact with `path:line`;
feature 008's finished plan package (`specs/008-checks-first-review/`, being implemented now),
whose answer batch, folded modelling-practice group and committed replay fixtures this feature
consumes; and feature 010's spec, data model and task list as they stood while this pass ran (010
is being planned in the same working tree; its `contracts/contacts.md`, `data-model.md` sections 9
and 14 and `tasks.md` were read, never edited).

Where this document says **VERIFIED**, this pass opened the file on main at `e8b40b5` (after the
three landed increments) and read the lines cited; where the claim is behavioural and was run, it
says so. The analyst's facts were re-opened for every decision that turns on them and their line
numbers corrected where the three landed increments moved them (R3). Numbers read off the recorded
run folders are the analyst's, computed on 2026-09-23 from the dumps that stay on the development
machine; they are restated against feature 008's committed fixtures in the task that asserts them.
Line numbers drift; every task re-verifies before editing.

---

## R1. What the sources are, and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | Seven stories, FR-001 to FR-030, SC-001 to SC-007; US1 and US2 landed | Normative for what is built; amended in the places R4 names, each with its reason |
| Owner decisions | Modelling practice as one folded group (2026-09-22); size-for-size contacts as a separate list; summary wording "Decide / Fix / Verify" with labels supplied by the backend; a follow-up answer pinned in Results (all 2026-09-23) | Normative; each is a data value or a rule below, never a page literal |
| The design rules | Every colour, face and size from `web/shared/tokens.css`; no page script sorts or compares severity or status; every string through `web/shared/dom.js`; three tiers of ink; pane 260 to 420 px; no webfont | Normative; enforced by `PageRuleScanTests`, `ReviewPageInjectionTests.ThePageStylesheetNamesNoLiteralColour` and the injection fence |
| The UI analyst's pass | Facts about the page, host sessions, backend routes, event replay, pinned tests, developer vocabulary | Evidence and starting design (its Increments 4 to 7 and the plain-language pass), reconciled below |
| Feature 008 | The answer batch route (`contracts/answer-batch.md`), the family fold (`contracts/checks-first.md` section 6), the committed fixtures (`contracts/replay.md` section 8) | A dependency: every 009 task that needs one names the 008 task id |
| Feature 010 | The contact list (`ReviewSession.contacts`, its US1) and the new check ids (its data model section 14) | A dependency for FR-011 and for the goal table's completeness |
| The constitution | Principles I to VI and the technical constraints | The gate in `plan.md` |

---

## R2. Decisions, alternatives and rationale

### Landed work

#### R2.1 User Stories 1 and 2 are recorded as done, not redone

**Decision**: `tasks.md` Phase 1 lists the three landed increments as completed tasks pointing at
their commits and the tests each added. No landed behaviour is re-implemented. Where a later story
changes what a landed test pins, that test is named red by design in the task that lands the change.

**Why**: VERIFIED with `git show --stat`: `2c48e2b` added `ReviewPageDocumentBindingTests` (13
tests), `CheckPageDocumentBindingTests` (6), two `ReviewHostTests`, contract-row, no-command and
one-constant tests, `web/shared/document.js`; `cf3c66e` inverted
`WhatWasObservedIsPrintedBeforeTheFold` and `ClickingARankedRowOpensAndFlashesItsFindingCard`,
added the title clamp and Collapse all; `b5cfcb4` moved the Start-here row into
`web/shared/attention.js` (`SharedAttentionScriptTests`, 7 test methods), drew every ranking row
behind "Show all" and amended `specs/007-attention-policy-gate/contracts/attention.md` section 6.
The AddIn suite went 1288 → 1322 → 1324 → 1353, all green, the Extractor suite unchanged at 1843
(the three commit messages).

### The summary (User Story 3)

#### R2.2 The summary is a pure module beside the ranking, carried on the Review tab's ranking body

**Decision**: a new pure module `reviewer/src/swreview/report/summary.py` computes
`review_summary(ranking, session, package, *, usage=None) -> ReviewSummary`. The Review tab's
ranking body is a subclass, `ReviewRanking(Ranking)` with `summary: ReviewSummary`, defined in
`summary.py`. `GET /sessions/{chat_id}/attention` answers a `ReviewRanking`; the snapshot and the
disk route (US6) answer the same object. `report/attention.py`, `attention.json`, both check bodies
and `report.md` do not move.

**Why**: VERIFIED that `rank(session)` reads the session alone and is pure (`attention.py:380-413`;
FR-015 of 007 forbids I/O and provider imports, asserted in `tests/unit/test_attention.py`), while
the summary needs the package (component names, the not-loaded count through
`report/unexamined.py:64-89`) and, for the cost line, the live usage ledger - so it cannot be
computed inside `rank()`. VERIFIED that `AttentionRecord.of` copies `Ranking` field by field
(`attention_record.py:84-102`, "so that a field added to `Ranking` for a surface that is not the
record ... is a decision taken here"), so a subclass leaks nothing into `attention.json`. A
`summary` field on `Ranking` itself would need `attention.py` to import the summary types while
`summary.py` imports `Ranking` - a cycle - and would put a new field on the object both check
bodies serialize (`server.py:733`, `:891`). Feature 008 is editing `attention.py` now (its T032, the family
fold); keeping 009 out of that file removes a merge.

**Alternatives**: a field on `Ranking` (rejected: the import cycle, the check bodies, 008's
concurrent edit); a separate `GET /sessions/{chat_id}/summary` route (rejected: two requests at the
end of every turn that must agree, and a second place the chat id is checked); computing in the page
(rejected: FR-009 and the no-comparison rule).

#### R2.3 Decide, Fix, Verify are counted by the policy's own keys, over findings

**Decision**: every finding outside a folded family falls in exactly one group, first match
winning, by the keys `report/attention.py` already uses:

| Group | Rule | Owner's label |
|---|---|---|
| `within_scope` | status `checked_within_scope` (`SUPPRESSED_STATUS`) | "Within limits" |
| `decided` | disposition `accepted` or `rejected` (`DECIDED_DECISIONS`) | "Decided" |
| `decide` | `policy.needs_judgement_of(check)` (key 2 is 0) | **"Decide"** |
| `fix` | status `demonstrated` | **"Fix"** |
| `verify` | status `suspected` or `unresolved` | **"Verify"** |

The order of the tests is key 1 (suppressed: within scope first, then decided - the order
`attention._not_amplified` counts them in, `attention.py:492-510`, and `_reason` names them in,
`:461-467`, so a waived finding that also carries a decision is "within limits" on every surface)
then key 2 then key 4; severity is not read. The three
owner groups are always present, even at zero, in the order Decide, Fix, Verify; `decided` and
`within_scope` follow only when non-zero. Each group carries its count, a sentence from the words
file ("9 need your decision"), and a per-goal breakdown (R2.4) in goal-table order. The headline
states findings and issues: `len(session.findings)` and `len(ranking.rows)`.

Findings of a folded family (008's `session.folded_families`, "rms" in the pane) are counted in no
group: they are the one "Modelling practice: N findings across M rules" line, taken from the family
row 008 builds (`AttentionRow.family`, `rule_count`, `member_finding_ids`). A test asserts the
partition: the five groups plus the family findings equal `len(session.findings)`.

**Why**: FR-007 "by the ranking's own keys" and the owner's labels. VERIFIED the keys:
`_is_suppressed` (`attention.py:446-450`), `needs_judgement_of` (`:192-194`), the judgement key
(`:423`), the status order (`:112-118`). Counting findings rather than rows avoids the ambiguity a
folded row brings (a row folds several findings that share a status, but 008's family row mixes
statuses, `contracts/checks-first.md` section 6). Excluding the family from the three groups keeps
"Fix" from reading 56 on the big assembly when 51 of them are modelling practice the owner decided to fold
away. On the recorded session (no family) the analyst counted 9 decide (6 interference, 3 hole
coaxiality), 56 fix, 34 verify (fact 19 re-read as findings rather than rows), which the US3
acceptance re-asserts on 008's `big-assembly` fixture.

**Alternatives**: groups by rows (rejected: a family row has no single status); including the
family (rejected above); a severity threshold (rejected: severity is key 5 and FR-007 names the
keys).

#### R2.4 The check goals are a data table; state by a fixed precedence; a few words and the full reason

**Decision**: the owner's eight goals live in `report/review_words_v1.yaml` under `goals`, each
with an id, a title, the checklist `items` it closes (exact coverage check ids) and the check-id
`prefixes` it owns. A finding's check belongs to the goal with the **longest matching prefix**
(so `fastener.head_clearance` is tool access, not fasteners; `standards.drawing.*` is drawings, not
hygiene). The initial table:

| Goal | Items | Prefixes |
|---|---|---|
| Interference | `interference`, `coverage.prerun.interference` | `interference.` |
| Fasteners | `fasteners` | `fastener.` |
| Hole alignment | `holes.alignment` | `hole.` |
| Fits and stacks | `interfaces.fit`, `interfaces.stack` | `fit.`, `stack.` |
| Tool access | - | `fastener.head_clearance`, `fastener.head_fit` |
| Mass and material | - | `mass.`, `standards.part.material_assigned` |
| Hygiene | `provenance`, `modeling.resilience`, `standards.release`, `coverage.prerun.standards` | `provenance.`, `rms.`, `standards.`, `hygiene.` |
| Drawings | `drawing.manufacturing_inputs` | `drawing.`, `standards.drawing.`, `rms.drawing.` |

Each goal gets one state, first match winning:

1. **issues found** - at least one finding mapped to it whose status is not `checked_within_scope`;
2. **not reached** - a close-out row for one of its items is `unresolved`, `skipped` or `failed`,
   or nothing at all speaks for the goal (no checked row, no within-scope finding, no
   out-of-scope row);
3. **checked, no issue** - a `checked` coverage row or a within-scope finding matches it;
4. **not applicable** - only `out_of_scope` rows match it.

The short reason is a fixed word from the file (`evidence missing`, `skipped`, `a check failed`,
`out of scope`, `no check ran`); the recorded sentence (a close-out row's `reason`, a pre-run row's
reason) travels as `detail` for the fold, verbatim.

**Why**: FR-007 and the spec's assumption that "a goal added later is a data change". VERIFIED the
checklist (`agent/checklist_v1.yaml:5-68`: ten items with `check_prefix`) and the close-out rule
(`attention.py:140-170`, `_coverage_block` `:513-539`). The analyst found close-out reasons of 84 to
419 characters written by the model (fact 30), too long for a ten-second line and never to be cut
(FR-027's own principle), so the line carries a category and the fold the sentence. "Not reached"
precedes "checked" so a run whose own close-out says an item was not closed never reads "checked"
because one rule row was (Principle I). Tool access and mass and material have no checklist item
today, so they read "not reached - no check ran" until feature 010's checks write coverage under
their ids (010 data model section 14: `fastener.head_fit`, `mass.*`, `hygiene.*`, read while 010
was being planned). Modelling practice is a **ninth goal line** of its own, matched by the `rms.` prefix and the
`modeling.resilience` checklist item (settled 2026-09-23 in the owner's session: the owner made it
one folded group of its own on 2026-09-22, and filing 85 modelling findings under hygiene would
bury the house-rule findings the hygiene goal is for).

A test asserts the table is complete: every checklist item except `coverage.closeout` is in exactly
one goal, and every check id in `attention_policy_v1.yaml` `classes` maps to exactly one goal. Feature
010's new ids - `hole.nominal_alignment`, `hole.position_stack` (its T037), `fastener.identity`
(T047), `fastener.head_fit` (T061), `mass.*` (T067), `hygiene.*` (T075), read from 010's
`tasks.md` and data model section 14 while they were being written - all fall under the table's
prefixes; any later id without a goal is named by that test, and the mapping is then a data row in
whichever feature lands second.

**Alternatives**: a `blocks`-style structured reason from `mark_coverage` (rejected: changes a tool
schema for a display need, and the model's reason is still the evidence); truncating the reason
(rejected: FR-027); a partition by first prefix in table order (rejected: order-dependent and hard
to argue; longest prefix is a rule a reader can check by hand).

#### R2.5 One words file for every word the backend supplies

**Decision**: `reviewer/src/swreview/report/review_words_v1.yaml`, loaded once by
`summary.load_words()` (a pydantic `Words` model, `extra="forbid"`, cached like `load_policy`),
holds: the five group labels with one/many sentence templates; the headline, questions,
parts-not-loaded, contacts and resume templates; the four goal states; the five goal reasons; the
goal table; the read-only sentence (US6); and the `labels` block served by `GET /labels` (US7:
status, severity, coverage bucket, evidence status, contact kind, and one next-step sentence per
error class). A test asserts no `%` anywhere (the rule `attention_policy_v1.yaml` states for every
word that can reach a tab), every `FindingStatus`, `Severity` and bucket value has a label, and every
template's placeholders are the ones the code fills.

**Why**: the owner's decision that the labels are supplied by the backend "so a later wording change
is a data change" (spec edge cases), and DRY: one file, one loader, one test of the vocabulary. The
policy file stays what it says it is - what "read this first" means (`attention_policy_v1.yaml:1-8`)
- rather than growing a second purpose.

**Alternatives**: extending `attention_policy_v1.yaml` (rejected: widens the `Policy` model and its
version for presentation words, and the gate brief reads that file); page constants (rejected:
FR-008, FR-024).

#### R2.6 Component names come from one helper; titles carry names at the one title funnel

**Decision**: `reviewer/src/swreview/report/names.py` holds `component_names(package) -> dict[str,
str]` (`{component.id: component.name}` for every component, exactly the map
`report/explanations.py:155-156` builds today, which then calls it) and `with_component_names(text,
names)`, which replaces each `cmp:NNNN` token whose name is not blank with the name. The summary
carries `component_names` (non-blank names only) for the page's lookups (Start-here meta, question
"about" lines, contacts); `tools/recording.title_from` gains a `names` argument and
`result_to_finding` passes `component_names(context.ir)`, so a finding's title names parts where
the observed string names ids (US7's task, landed with the truncation change so the goldens move
once, R2.20). `observed`, `component_ids` and every input keep their ids.

**Why**: FR-012 and SC-003. VERIFIED the observed strings name bare ids
(`checks/interference.py`: "Static interference between {pair} ...", `pair` built from
`group.component_ids`; the analyst counted 6 of 99 and 2 of 13 titles with `cmp:` ids, fact 11).
VERIFIED `title_from` is the one funnel (`tools/recording.py:39-44`, called at `:75` and
`tools/session.py:180`). A page-side regex replacing ids inside titles would be the page deriving
display text - cleverness in the file the owner reads least - and would need the same map anyway.
The helper is extracted because it is now used three times (explanations, summary, titles);
VERIFIED `report/markdown.py:251` keeps its own `_components_by_id` returning instances, a different
need, left alone.

**Alternatives**: rewording every check's observed string (rejected: changes findings' evidence and
10 check modules, two of which feature 010 is rewriting); names only in the page (rejected: titles
are backend text).

Hole ids (`hole:0012`) in hole-alignment titles are not component ids and stay; plain words for them
are an open item (R5).

*Amended 2026-09-23 (owner, decision 2A, R2.28):* `title_from` gains no `names` argument; the
third caller is `report/titles.display_title`, which names the parts in the title a person reads
while `Finding.title`, the one the model reads, keeps its ids.

#### R2.7 Size-for-size contacts are read from feature 010's list, through one accessor

**Decision**: the summary carries `contacts: {count, text, items: [{id, component_ids, names,
configuration, kind, kind_label, text}]} | None`, built by `summary.contacts_of(session)` from
`ReviewSession.contacts` in the order 010 recorded them; `None` when the session has none or
predates 010. The page renders it as one shut fold after the findings, apart from them. Until
010's US1 lands the field does not exist and the accessor answers `None`.

**Why**: FR-011 and the owner's decision of 2026-09-23. Feature 010 owns the rule and the record
(its spec FR-002; its contract `contacts.md` section 4 and data model section 9, read on
2026-09-23: `Contact{id, kind, group_key, configuration, interference_ids, component_ids,
volume_mm3, joint_id, reason, tool_result_ids}`, `ReviewSession.contacts` omitted when empty, and
"`report/attention.py` never reads `contacts`"). One accessor means one line adapts if 010's name
differs when it lands. 010's `tasks.md` (read while it was being written) lands the model and the
field in its T020 and the contact path in `check_interference_group` in its T022; this feature's
backend half waits for T020.

#### R2.8 "Parts not loaded" gets a names-only headline beside the sentence

**Decision**: `NotExamined` gains `headline` (for example "3 of 89 parts were not loaded: Pin-A-1
and Pin-B-1 (lightweight), Plate-1 (suppressed). Interference, fit and the feature-tree rules cannot
see them."), composed in `not_examined()` from the same instances with names and state labels and no
ids. `sentence` is unchanged and is still what `report.md` and both check bodies print. The page
shows `headline` when present, `sentence` otherwise, and the instance ids in a fold. The summary's
`not_loaded` is `{count, total, text}`.

**Why**: VERIFIED the sentence names ids (`report/unexamined.py:79-82`, `f"{instance.name}
{instance.id} ({instance.suppression})"`) and that the module is "the one place the sentence is
composed" (`:12`). VERIFIED the host forwards `not_examined` as raw JSON (`IBackendClient.cs:96-108`
`JsonElement? NotExamined`; `ReviewHost.cs:1041`), so an added key reaches the page with no C#
change. The report keeps the ids (spec: "every id ... is still in ... the report").

### Questions (User Story 4)

#### R2.9 The short form is three optional arguments on `request_evidence`

**Decision**: `request_evidence(what, why, entity_ids, question=None, options=None, blocks=None)`.
`question` is at most 140 characters; `options` at most five strings of at most 60 characters,
distinct, non-blank; `blocks` a checklist item id from `CHECKLIST_ITEM_IDS`. Each refusal is an
`error_result` naming the argument and the limit, and records nothing. `EvidenceRequest` gains
`question: str | None = None`, `options: list[str] = []`, `blocks: str | None = None`, omitted from
the dump when empty so every earlier `session.json` keeps its bytes; the three optional properties
join `$defs.EvidenceRequest` in `review-session.schema.json` in the same change (the event schema
`$ref`s it, so `chat-events.schema.json` does not move). The docstring's Notes gain two sentences:
one decision per request, and never guess a fit class, tolerance or thread depth - ask.

**Why**: FR-013. VERIFIED today's tool (`tools/session.py:50-78`: `what`, `why`, `entity_ids`) and
model (`report/session.py:65-74`); VERIFIED `$defs.EvidenceRequest` is
`additionalProperties: false` (`review-session.schema.json:118-127`) and the event schema refs it
(`chat-events.schema.json:32-33`). The analyst found every evening request stayed open with `what`
at 132 to 299 characters (fact 14). `blocks` names a checklist item because that is the vocabulary
the model already works in (the checklist is in its prompt); the summary maps the item to its goal
title for the engineer (R2.4). **Red by design** in the landing task: the curated array pins of
`tests/unit/test_tool_payload.py` (`OPENAI_ARRAY_BYTES`, `GEMINI_ARRAY_BYTES`, the trimmed pins, the
bridge pin, and 008's slimmed pin from its T062), regenerated with `python -m
tests.unit.test_tool_payload --write`; the tool count stays 32. Feature 008's replay is unaffected:
pass A's prefix delta is zero by construction and pass B's differs from pass A by settings only
(`specs/008-checks-first-review/contracts/replay.md` section 4, `dP`). The dated baseline table in
`docs/llm-efficiency-options.md` is a measurement of commit `a0be95f` and is not edited.

**Alternatives**: a second tool `ask_engineer` (rejected: a 33rd tool in every request and two ways
to ask); required short fields (rejected: every recorded session would stop validating).

#### R2.10 The questions panel sends one batch through 008's route; the transcript card becomes a record

**Decision**: the summary carries `questions: {count, text, items: [...]}`, the open requests in
session order, each `{id, question, options, blocks, blocks_title, what, why, about: [{id, name}]}`
where `question` is the short form or, when absent, `what`. The page shows one at a time above
Start here ("Question 1 of 4"), the offered answers as buttons that select or a text box, "Skip for
now" (moves on, sends nothing, keeps the question open), and "Send answers" enabled once one answer
is non-blank. It posts `POST /sessions/{chat_id}/evidence {answers: [{request_id, answer}, ...]}`
(feature 008 T085) with the answered questions in the order supplied, and nothing for a skipped one.
The transcript's evidence card keeps the question, its status and the answer, and loses its own
answer box: one way to answer. Answers typed and not sent are kept per chat in page memory while the
page lives. A refusal carries the failing `request_id` (a field this feature adds to the two
evidence error bodies, after 008 T085); the page names that question by its number and short text,
reloads the summary, and keeps the other drafts.

**Why**: FR-014, FR-015, US4 scenario 4 and the edge cases. The page must not filter requests by
status (`PageRuleScanTests` rule 3 scans `status` comparisons; VERIFIED the one evidence exemption
is `body.status === 'answered'` in `render.js`), so the open list comes from the backend. VERIFIED
008's contract: validate everything first, one `evidence.answered` per answer in submission order,
one resumed turn, refusals naming "the first failing id" in the message
(`contracts/answer-batch.md` sections 1 and 2); a message is not a field, so the page would have to
parse English to say which question - hence the structured `request_id`. VERIFIED `ChatError.body`
is one place (`server.py:197-198`).

**Alternatives**: parsing the id out of the message (rejected: fragile); comparing the old and new
open lists to find it (rejected: the refusal already knows); keeping the single-answer box on the
transcript card (rejected: two ways to answer, one of which costs a turn per answer).

#### R2.11 The resume cost is the last conversation round's measured input

**Decision**: `UsageLedger` records the round count at each `text.done`; `last_conversation_input()`
answers the `input_tokens` of the last round before the most recent `text.done`, or `None` (no
`text.done` yet, or that round did not report input). The summary carries `resume_input_tokens` and
`resume_text` ("Sending resumes the review once. Its last round sent 405,861 input tokens.", or
the sentence without the number when unknown); only the live routes pass the ledger, so the disk
route answers `None`. The page prints `resume_text` beside Send.

**Why**: FR-016 says "from the last round's measured input size". VERIFIED that the explanation
pass's usage is emitted after the turn's text (`agent/runner.py:745-760`, before `turn.ended` at
`:770-775`), so "the last round" read naively would be the small presentation request; 008 reads the
same boundary the same way (its T015: "the presentation usage after `text.done` is
`kind="presentation"`"). VERIFIED the ledger is the one accumulator and a listener on the sink
(`agent/events.py:134-174`, `runner.py:654-661`). With 008's pruning the resumed request is roughly
the last round's input; the sentence says what was measured and does not predict.

### Results or Transcript (User Story 5)

#### R2.12 Two containers, one switch; each view owns the pane

**Decision**: `index.html` gains a two-button switch (Results, Transcript; `aria-pressed`) under
the header and two containers, `#results` and `#transcript`, one hidden by a class on `body`
(`view-results` default, `view-transcript`). Results holds, in order: the summary, the questions,
the not-loaded warning, Start here and "Show all", the findings list (headline cards in arrival
order, with the modelling-practice group and the contacts fold), the "Not reached" coverage fold,
the error cards, and the pinned follow-up answers, with one status line of page words ("The review
is running." / "Reconnecting to the review." / "The review has finished." / "Waiting for your
answers."). Transcript holds its own head (calls, rounds, the running tool, the usage line, the
stream state, the run folder path) and the chronological record: prose blocks, tool cards, evidence
cards, system lines, one-line finding markers, and error lines with their class. The stale line,
the preparation panel and the follow-up form sit outside both. The transcript fold toggle and the
`.transcript.folded` rules are removed.

**Why**: FR-017, FR-018 and the owner's U11 ask. VERIFIED today's single container interleaves
findings with tool cards and prose and hides the latter with a class (`app.css:666-669`,
`app.js:701-708`), which is why a 300 px strip shows one or the other badly. A finding card cannot
sit in two containers, so the Transcript carries a one-line marker for each finding in its place in
the chronology. VERIFIED `appendCard` scrolls the transcript to the end on every card, forcing a
layout (`app.js:516-524`); with findings in Results, streaming 99 findings no longer forces 99
layouts of the transcript. The usage line, token counts and the run folder path move out of the
engineer's default view (FR-018); feature 008's `usageLine` body (its T094-T095) is not touched.

**Alternatives**: keeping one container with more classes (rejected: the modelling-practice group
and chronology cannot both hold in one DOM order); an automatic switch to Transcript for a
follow-up (rejected by the owner's decision: the answer is pinned in Results).

#### R2.13 A follow-up answer is pinned from the stream; pins live in page memory per chat

**Decision**: sending a follow-up adds a pinned block to Results holding the question; the turn's
`text.done` fills its answer (the same text also lands in the Transcript as a prose block) and
brings it into view. Pins are kept per chat in page memory, so choosing that review's chip again
(US6) shows them; after a page reload or a backend restart they are gone, and the answers remain in
the transcript and `events.jsonl`.

**Why**: FR-019. VERIFIED that the follow-up's own text is not on the event stream
(`runner.continue_session` `:693-699` emits no event for it) and the page appends it itself
(`app.js:1048`), so no backend record could restore the question after a restart without a new
event type. Page memory covers the owner's normal session (assembly, pin, plate in one pane life).

**Alternatives**: a new event type carrying the engineer's text (rejected: an event-schema change
for a display convenience); an in-memory list on `ReviewRun` served by the snapshot (rejected for
now: it survives a page reload but not the backend restart the read-only case is about, so it
covers the rarest case only; recorded in R5).

### Sessions (User Story 6)

#### R2.14 The host lists reviews and forgets one; every action names its chat

**Decision**: `SessionRecord` gains `Document` (`PageDocument`, the one `review.started` names) and
`StartedAt`, set by `TrackSession` for reviews only. Two page-to-host rows: `sessions.list {}` →
`sessions {items: [{chat_id, run_id, run_dir, path, configuration, started_at}]}`, reviews only, in
the order they were started; `session.forget {chat_id}` → the same reply, the record removed (and
`LatestSession` cleared if it was that record). `entity.show` accepts an optional `chat_id`: when
present, `PaneActions` resolves the run folder through the same `PaneRunLookup` `report.open` uses
and passes it on `EntityShowRequest.RunDirectory`, and the resolver's two package lookups read that
folder instead of `LatestSession`'s. The Review page always sends its shown chat's id. No
host-side "shown session" pointer is added.

**Why**: FR-020, FR-023. VERIFIED `SessionRecord` holds only `ChatId`, `RunDirectory`, `IsCheck`
(`ReviewHost.cs:84-116`) and that Show resolves ids through `RunPackageIndex` over `LatestSession`
(`SwReviewAddIn.cs:440`, `:461-462`), which a Model check or a Remodel run replaces
(`ReviewHost.TrackCheck`, `:356-366`) - the analyst's inferred cross-tab risk (fact 5), confirmed on
the next sitting (Phase 9). VERIFIED `report.open` and `folder.open` already carry `chat_id` and
resolve through the host's record (`PaneActions.cs:360-383`, `PaneRunLookup` `:39-65`), so
`entity.show` follows the same rule: the page names an id, never a path. A host "shown" pointer
would be a second mutable fact crossing threads (the resolver runs on the SOLIDWORKS thread,
`ReviewHost.cs:316-326` explains why `LatestSession` is a single reference) that goes stale on a
page reload; an id on each request cannot. The check tabs send no `chat_id` and keep today's
behaviour. The Ask tab keeps following `LatestSession` (`SwReviewAddIn.cs:388`).

**Alternatives**: `session.select` setting a host pointer (rejected above); the page keeping the list
(rejected: lost on every page reload while the host lives for the SOLIDWORKS session).

#### R2.15 One snapshot builder serves the live chat and the run folder

**Decision**: `reviewer/src/swreview/report/snapshot.py` builds `review_snapshot(session, package,
*, run_id, usage=None, chat_state=None, last_seq=None, read_only_reason=None) -> dict`: `{run_id,
read_only, read_only_reason, chat_state, last_seq, document, findings, evidence_requests, coverage:
[{bucket, item}], ranking (a ReviewRanking with its summary), not_examined}`. Two routes answer it:
`GET /sessions/{chat_id}/snapshot` from the run the backend holds (writes nothing), and
`GET /reviews/{run_id}` from the folder under the run root (`session.json` and `package.json`
through `load_session` and `load_package`, the ranking recomputed by `rank()`, read-only, the reason
from the words file, **writes nothing**). `run_id` goes through `resolve_run_dir` as `check_id` does;
anything refused, a folder with no `session.json`, a check folder (`check.json`), or an unreadable
file is `404 UnknownReview`, so the route cannot probe the workstation.

**Why**: FR-020, FR-021 and the spec's assumption that restoring writes nothing. VERIFIED no route
reads a finished review back (fact 9) and that `GET /checks/{check_id}` is the precedent: a name, not
a path, through `resolve_run_dir`, refused as unknown (`server.py:1345-1359`, `_check_dir`
`:1407-1422`), recomputing the ranking in memory and writing nothing (`attention_record.py:11-16`).
VERIFIED the pieces: `load_session` (`report/session.py:420`), `_package_of` (`rerender.py:146-154`),
`not_examined`, `rank`. VERIFIED an unknown chat is `404 UnknownChat` (`server.py:1696-1701`) and
that a settings save restarts the backend and drops every chat (fact 7), which is when the disk
route is needed. VERIFIED session order is the page's arrival order: a re-run replaces its finding in
place in `session.findings` and on the stream (`runner._reconcile_reruns`, `:555-586`), so rendering
`findings` in session order reproduces the page. `EventSink.seq` gives `last_seq`
(`agent/events.py:102-104`).

**Alternatives**: replaying `events.jsonl` from seq 0 to rebuild Results (rejected: 793,183 bytes
and 2,256 events on the big assembly, each card forcing a layout, and today's `endSession` closes the
stream on every turn's `session.ended`, fact 8); reading `attention.json` for the rows (rejected:
the check route's precedent recomputes, and `rank(load_session(...))` equals the record by
construction, `attention_record.py:11-16`).

#### R2.16 Choosing a chip restores; returning to a document shows its newest review

**Decision**: chips under the header name the file, configuration and time of each review in the
host's order. Choosing one (refused while a turn or a start is in flight, like Clear review) closes
the stream, clears Results and Transcript, sets the chat, fetches `/snapshot` - falling back to
`/reviews/{run_id}` on `404 UnknownChat` - and renders it. The same function runs when the active
document changes and no turn or start is in flight: if the shown review is not of the new document
and the host's list holds a review of it, the newest such review is shown; otherwise the landed U8
binding hides the shown review as today. It also runs after `init` (a page reload). A chip whose
disk route answers `404 UnknownReview` says the review can no longer be restored and offers Remove
(`session.forget`). A read-only review disables the follow-up, the dispositions and the questions,
and shows the backend's reason; Open report and Open run folder still work (the host's record). A
chip of a document that is not active renders hidden behind the stale line, as FR-001 requires.

**Why**: US6, SC-005, US1 scenario 2 ("returning to the assembly brings it back") extended to
several reviews, and FR-001 kept strict so nothing acts on the wrong model. "Newest" is the last
match in the host's supplied order: a scan, not a sort. VERIFIED the landed binding re-judges on
every `document.changed` (`app.js:974-986`) and the running-turn rule keeps Stop live
(`ReviewPageDocumentBindingTests.WhileATurnRunsStopStaysEnabledAndClearReviewIsRefused`).

**Alternatives**: chips only, no automatic show (rejected: the engineer returns to the assembly and
reads "Press Review to review it" while its review is one chip away); showing another document's
review with actions disabled (rejected: FR-001 says hidden).

#### R2.17 A restored live chat's transcript is replayed only when Transcript is opened

**Decision**: Transcript of a chip restored from `/snapshot` is empty until Transcript is chosen;
then the page opens the stream from seq 0 in replay mode (`state.replayUntil = snapshot.last_seq`):
events with `seq <= replayUntil` build only the Transcript (a `finding` event adds its marker, never
a second card), `session.ended` does not close the stream or reload the ranking until the replay
reaches `replayUntil`, and the transcript scrolls once at the end rather than per card. A chat the
snapshot reports `running` (a page reload mid-turn) resumes the live stream from `last_seq`. A
review restored from its folder shows one sentence in Transcript - the transcript is in the run
folder's `events.jsonl` - with Open run folder.

**Why**: the replay facts of R2.15; FR-021 asks for results, not the transcript; a disk events route
would be a new read surface for a file that can be 800 KB.

#### R2.18 A configuration switch is a document change

**Decision**: a new `extractor/SwReview.AddIn/ActiveConfigurationWatch.cs` subscribes to the active
document's `ActiveConfigChangePostNotify` (the part's or the assembly's event interface), moves the
subscription when the active document changes, and calls the same fan-out
`OnActiveDocumentChanged` calls, so every host posts `document.changed` with the new configuration.
The subscription is behind a seam (subscribe and unsubscribe delegates) so the rule is unit-tested
without SOLIDWORKS; the real events are confirmed at the sitting.

**Why**: FR-022. VERIFIED the add-in subscribes only to `ActiveDocChangeNotify`
(`SwReviewAddIn.cs:494-499`, unsubscribed `:268`) and that the page already treats another
configuration as another document (`ReviewPageDocumentBindingTests.AnotherConfigurationOfTheSameDocumentIsAnotherDocument`).
VERIFIED statically that `DPartDocEvents_ActiveConfigChangePostNotifyEventHandler` and
`DAssemblyDocEvents_ActiveConfigChangePostNotifyEventHandler` exist in the SOLIDWORKS 2024 SP5
`SolidWorks.Interop.sldworks.dll` redist on this machine (a string search of the assembly; not run,
there is no licence here). A drawing has no configuration of its own, so no drawing subscription.

### Plain words (User Story 7)

#### R2.19 The card vocabulary is served once by `GET /labels`

**Decision**: `GET /labels` (token required, like every route) answers the `labels` block of the
words file: `{version, status, severity, bucket, evidence_status, contact_kind, errors}`. The page
fetches it after every `init` that names a backend and passes it into the renderers as an argument;
a missing label, a 404 from an older backend, or a key that names something on `Object.prototype`
prints the raw token as today.

**Why**: FR-024 and FR-030. Finding cards stream in during the turn, long before the ranking, so the
words cannot ride on the summary without every card first showing a raw token. VERIFIED the page
reaches any backend path through the proxy with no host change (`app.js:254-301`; the proxy row,
`pane-host-messages.md:40`). VERIFIED `render.js` is pure by design ("nothing here talks to anything:
no ... page state", `:4-8`), so labels are an argument, not module state. A map read keyed by a
status is not a comparison (`PageRuleScanTests.ValueComparison`, `:427-435`, matches only an
operator).

**Alternatives**: labels on `review.started` (rejected: a host change and a contract row for static
data); on every `finding` event (rejected: an event-schema change); a page map (rejected: FR-024).

#### R2.20 Titles are the whole first sentence, with part names

**Decision**: `title_from(observed, names=None)` returns the first sentence of `observed`, trimmed,
with component ids replaced by names (R2.6), and never cut; `TITLE_LENGTH` is removed. The page's
two-line clamp (landed, `app.css:735-744`) is the only limit. **Red by design** in the landing task:
the ten `tests/golden/test_golden/*.yml` baselines that hold a cut title (`cover-blind-tap`,
`rms-assembly`, `rms-part`, and seven `standards-*`), regenerated with `--force-regen`; the task
asserts the regenerated diff touches `title:` lines only.

**Why**: FR-027 and FR-012. VERIFIED the cut (`tools/recording.py:36-44`, 80 characters and an
ellipsis) and the ten baselines (a search for the ellipsis under `tests/golden/test_golden/`); the
analyst counted 71 of 99 titles cut on the big assembly (fact 11). No `.md` golden holds a cut title (the
same search), and feature 008's replay compares findings by subject key, which ignores the title
(`specs/008-checks-first-review/contracts/replay.md` section 5).

*Superseded 2026-09-23 (owner, decision 2A, R2.28):* `title_from` and `TITLE_LENGTH` stay as they
are; the whole, named title is `report/titles.display_title`, built only where a person reads it.
No baseline is regenerated. The replay's finding comparison ignores the title, but its round
sizes do not: the recorded title is in every check tool's result.

#### R2.21 Check ids and component ids move into folds, on every tab that shows them

**Decision**: the finding card's line drops the check id; the fold's first labelled row is "Rule"
with it. The shared Start-here row (`web/shared/attention.js`) drops the visible check id on all
three tabs and keeps it as `data-check`; its meta line prints status and severity through the labels
and component names through the summary's map when the caller passes them (the Review tab), ids
otherwise (the check tabs). The shared rule row (`web/shared/check-page.js ruleRow`) moves the rule
id into the row's fold, so every rule row has one. The question panel, the not-loaded warning and
the contacts list show names, with ids in their folds.

**Why**: FR-025 and SC-003. VERIFIED the visible ids: `render.js:263` (`finding-check`),
`attention.js:103` (`attention-check`) and `:127-133` (components, mono), `check-page.js:954`
(`rule-id`), `render.js:471-473` ("About"). VERIFIED the shared row is pinned equal on both kinds of
tab (`SharedAttentionScriptTests.TheReviewTabAndTheCheckTabsRenderTheSameStartHereRows`), so the
change is made once and on every tab rather than forking the row. **Red by design**:
`ReviewPageInjectionTests.TheFindingsFirstLineNamesTheFindingItsStateAndItsCheck` (`:187`),
`ModelCheckPageTests.TheRankedRowsRenderInTheOrderTheRankingSuppliedThem` (`:231`, reads
`.attention-check`), `StandardsPageTests.TheRankedRowsRenderInTheOrderTheRankingSuppliedThem`
(`:507`), `ReviewPageAttentionPanelTests` (`:629` harness), `ReviewPageInjectionTests` (`:880`
harness), `SharedCheckPageTests.TheSharedRulesAreInTheSharedStylesheetAndNotInThePages`
(`.attention-check`, `:464`), and `AttentionSample.ShownChecks`.

#### R2.22 Errors say what to do next; the class goes into the fold

**Decision**: the words file's `labels.errors` maps each error class to one next-step sentence (for
example `TurnRunning`: "A review turn is still running. Wait for it to finish, or press Stop.").
The page's error card, card status lines and the settings save line print that sentence (the
message when no label exists), with the class and the backend's message behind a fold. A Python test
asserts every `ChatError` subclass's `error_class` has a label; a C# test reads the words file and
asserts every error class the Review host and `PaneActions` can send, and every class `app.js`
names, has one.

**Why**: FR-026. VERIFIED the class is printed today (`render.js:502`; `app.js:1300`, `:1327`,
`:1532-1534`) and the classes are defined in one place per side (`server.py:185-...`; the
`SendError(id, "<class>"` literals in `ReviewHost.cs` and `PaneActions.cs`).

#### R2.23 Model check states rule statements, not the fraction and the id list

**Decision**: `check_result` adds `rule_statements: {rule_id: statement}` for every rule the grade
names (from `RULES`); the Model check header drops the fraction line and prints "Not graded,
evidence missing:" followed by the unresolved rules' statements, with the ids behind a fold. The
grade's `fraction` stays in the body and the report. The Standards tab is unchanged.

**Why**: FR-028. VERIFIED the fraction and the id list (`check.js:160-183`) and that statements
reach the tab only on finding rows (`server.py:815-831`, `_finding_row` `statement`), while the
unresolved rules are coverage rows with none. **Red by design**:
`ModelCheckPageTests.TheGradeHeaderShowsEveryCountAndNamesEveryUnresolvedRule` (`:177`) and
`EveryGradeCountKeepsItsTextAndLeadsWithItsNumberInItsOwnElement` (`:479`),
`SharedCheckPageTests.TheGradeRulesStayWithTheModelCheckPage` (`.fraction`, `:477`).

### Cross-cutting

#### R2.24 The fixtures: 008's big assembly for the backend, one generated file for the page

**Decision**: the US3 acceptance summarizes feature 008's committed `big-assembly` fixture
(`reviewer/tests/fixtures/replay/big-assembly/`, 008 T018): the three groups, the questions, the
parts not loaded and the eight goals, the numbers asserted against the fixture. A generator,
`reviewer/tests/fixtures/pane/generate_pane_fixture.py`, writes the snapshot of that fixture to
`extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json`; a Python test fails when the
committed file differs from a fresh generation (`--write` regenerates it, as
`test_tool_payload.py` does). The WebView2 acceptance tests of US3 to US7 load that file.

**Why**: the spec's "fixture shaped like the big assembly's run" exists already, fictional and
hygiene-checked (008 `contracts/replay.md` section 8, its T017). One fixture for both sides means
the page is tested against exactly what the backend produces; the drift test keeps them together.
The recorded dumps never enter the repository.

#### R2.25 Hundreds of findings: measured first, paged only if needed

**Decision**: a WebView2 performance test renders a snapshot of 1,000 findings and a 1,000-row
ranking into Results offscreen and requires the render within 3 s and the first card in view. If
it fails, the findings list pages by 100 in the supplied order behind "Show 100 more", decided and
recorded here before the task closes.

**Why**: the spec's edge case. VERIFIED each card builds its whole fold up front (`render.js:345-376`)
and today's per-card scroll forced a layout (R2.12), which US5 removes; whether 1,000 cards then fit
the budget is a measurement, not a guess.

**Measured (T049, 2026-09-23, development machine, offscreen WebView2 at 420 by 800)**: 1,000
`finding` events and a 1,000-row ranking, posted as one burst through the live stream and the
ranking route, were rendered into Results - 1,000 cards in `#findings`, 995 lines behind "Show
all" - in 162 to 417 ms over nine runs (`ReviewPageScaleTests`), an order of magnitude inside the
3 s bound. **No paging**: `#findings` renders every card in the supplied order and "Show 100
more" is not built. "The first card in view" is read as the first card of Results - Start
here's first row - on screen with Results at its top, and the first finding's card rendered (not
paged away) below it: at a docked pane's size Start here's five cards fill the first screen, so
no finding card can be above the fold and a test that demanded one would be a test of the pane's
height. The bound is driven through the live stream rather than a snapshot because the snapshot
render is US6's (T057), which reuses the same renderers.

#### R2.26 The tests that go red by design, by story

| Story | Tests | Why |
|---|---|---|
| US3 | none pinned; `ReviewPageAttentionPanelTests.ThePanelIsAboveTheTranscript` (`:142`) stays green until US5 | the summary is additive |
| US4 | `test_tool_payload.py` array pins (R2.9) | the tool schema grows |
| US5 | `ReviewPageEventStreamTests.TheTranscriptArrivesFoldedAndItsHeaderUnfoldsIt` (`:131`), `TheTranscriptHeaderCountsTheRoundsTheCallsAndWhatIsRunning` (`:150`), `AFollowUpUnfoldsTheTranscriptSoItsAssistantAnswerIsVisible` (`:231`); `ReviewPageAttentionPanelTests.ThePanelIsAboveTheTranscript` (`:142`); `ReviewPageNarrowLayoutTests.TheFirstFindingDetailsHaveAReadableViewportAtTheNarrowPaneSize` (`:29`, re-measured in Results) | the fold becomes a switch |
| US6 | `ReviewHostTests.TrackingACheckMakesItsFolderTheLatestRunAndTheRecordCarriesNoChatId` (`:504`) keeps its assertions and gains the Review-page Show case | `LatestSession` stays for the Ask tab and the check tabs |
| US7 | R2.28 (was R2.20), R2.21, R2.23 lists | titles, ids, Model check |

Any other test a landing change turns red is named in that task's commit message and edited
deliberately, never loosened.

#### R2.27 File ownership against 008's and 010's implementation agents

Page-only tasks (`extractor/SwReview.AddIn/Review/ReviewPage/*`, `web/shared/*`,
`Model/ModelCheckPage/*`, and their C# page tests) can run beside any Python task of 008 or 010.
Host tasks touch `ReviewHost.cs`, `PaneActions.cs`, `ReviewServices.cs`, `SwEntityResolver.cs`,
`RunPackageIndex.cs`, `SwReviewAddIn.cs` and a new file; no 008 or 010 task edits those. Python
tasks share files with 008 and 010 and run serially with them where they meet:

| File | 008 tasks | 010 | 009 tasks |
|---|---|---|---|
| `report/session.py`, `review-session.schema.json` | T030, T053, T088-T090 | T020 (`contacts`) | US4 `EvidenceRequest` fields |
| `chat/server.py`, `tests/unit/test_chat_server.py` | T047-T048, T059, T067, T076-T077, T080-T081, T084-T085 | - | US3 route, US4 refusal field, US6 routes, US7 labels route |
| `tests/unit/test_tool_payload.py` | T057, T062 | - | US4 pins |
| `tools/recording.py` | - | new checks call `result_to_finding` | US7 `title_from` |
| `tests/golden/test_golden/*.yml` | - | T016 (`standards-*`, profile hash), T043 (three engagement baselines) | US7 titles |
| `attention_policy_v1.yaml` | T032 (none planned) | T037, T047, T061, T067, T075 (classes) | read only, by the goal-table test |
| `specs/007-attention-policy-gate/contracts/attention.md` | T032 (sections 2-4) | - | section 6 |
| `render.js` | T094-T095 (`usageLine` only) | - | US3-US7, never `usageLine`'s body |

*Amended 2026-09-23 (R2.28):* the `tools/recording.py` and golden-baseline rows no longer hold a
009 task: `title_from` moves unchanged into `report/titles.py` and no baseline moves.

#### R2.28 Whole, named titles where a person reads them; the model's title stays (owner decision 2A)

**Decision** (owner, 2026-09-23; FR-027, `contracts/plain-words.md` section 2). R2.20's change -
one title, whole and named, recorded by `title_from` into `Finding.title` - is not made.
`Finding.title` stays the recorded title, byte for byte what it was: the first sentence of
`observed`, cut at 80 characters with an ellipsis, ids as written. The whole, named title is
built only where a person reads it, by one function, `report/titles.display_title(finding,
names)`, which every such surface calls: the `finding` event and the snapshot's findings (through
`pane_finding`), the Review tab's ranking and both check bodies' `attention` rows (through
`with_display_titles`), and `report.md`'s finding headings and Start here. `title_from` and
`TITLE_LENGTH` move unchanged from `tools/recording.py` into `report/titles.py`, beside the
function that undoes their cut; `tools/recording.py` re-exports both, so no caller changes.

**Why.** T062 was parked because R2.20's change moves every check tool's result - the recorded
finding is in it, and in its slim view's rows (`tools/model_view.ROW_FIELDS`) - which feature
008's replay acceptance pins to the recorded rounds; landing it meant re-recording or re-pinning,
and every future result naming a finding would carry the longer title on every round. The owner
chose the option with no model-side cost: the model reads what it read, and only the pages and the
report change. VERIFIED on the committed replay fixtures: every recorded title is
`title_from(observed)` (99 of 99 on `big-assembly`, 13 of 13 and 7 of 7 on the small ones); 71
of 99 are cut and 6 name a named part by id on `big-assembly` (10 and 2 of 13 on
`small-assembly-a`, 5 and 0 of 7 on `small-assembly-b`).

**Which title is "whole".** A title this product recorded from `observed` (`finding.title ==
title_from(finding.observed)`, cut or not) is shown as the whole first sentence; any other title
is shown as written, named. Always showing the first sentence of `observed` was rejected: a title
written by hand says something else - VERIFIED, the ranked-report golden
(`tests/unit/test_report_start_here/test_the_ranked_report_matches_the_golden.md`) holds eight
titles none of which is its finding's first sentence - and a title an older build wrote would be
replaced by a sentence it never showed. Undoing only the cut this product made is the one reading
under which "the whole title" means the title.

**Why the pages keep reading `title`.** Each body a page receives carries the display title under
the key it already prints, so `render.js` and `web/shared/attention.js` are unchanged, FR-030
holds by construction (an older backend's `title` prints as before), and
`chat-events.schema.json` - whose `finding` body is `review-session.schema.json#/$defs/Finding`,
`additionalProperties: false` - does not move. `events.jsonl` records the `finding` events as the
pane received them; the replay reads only their ids (`benchmark/recording.py _finding`).

**What moves, and what does not.** The `title` value, only where the recorded title was cut or
named a named part, on: the `finding` event, the snapshot, the attention route, both check bodies'
`attention` rows, and `report.md`. Nothing else: no tool result, no slim view, no gate brief, no
explanation prompt, no `session.json`, no `attention.json`, no golden baseline, no tool payload
pin, no replay round. A new test pins the bytes the model reads of representative check tools
(`tests/unit/test_model_reads_the_recorded_title.py`). Deliberately edited: the two check-route
tests that pinned a check body's `attention` equal to `rank(session)`
(`test_chat_checks_routes.py`, `test_chat_standards_routes.py`), which now pin it equal to
`with_display_titles(rank(session), ...)` - the order, keys and reasons still the record's. The
pane fixture is regenerated once with `--write`.

**Alternatives**: B, the whole, named title in `Finding.title` (R2.20 as planned; an earlier
attempt implemented it) - rejected by the owner: a token cost on every result that names a finding
and a re-recording of 008's replay fixtures; a `display_title` key beside `title` - rejected: a
change to every `Finding` of 001's session contract and a fallback in the page; the page naming
parts from `summary.component_names` - rejected: the page builds no text (FR-029).

---

## R3. Verified facts the plan relies on

Re-opened on 2026-09-23 at `e8b40b5`:

- **Page**: `index.html` session row `:101-126` (meta line `:121-125`), stale line `:133`,
  not-examined `:143`, preparation `:145-155`, attention panel `:157`, transcript head `:170-174`,
  transcript `:176`, coverage `:178`, follow-up `:184-189`, scripts `:191-195` (dom, document,
  attention, render, app). `app.js`: `document.changed` `:201-206`; `onChatEvent` `:437-489`;
  `appendCard`/`scrollToEnd` `:516-524`; `showFinding` `:593-603`; evidence `:605-625`;
  transcript head `:681-694`; `foldTranscript` `:701-708`; `endSession` `:720-730` (closes the
  stream and loads the ranking on every `session.ended`); `loadAttention` `:755-777` (chat and epoch
  guard); `syncFindingExplanations` `:792-817`; `review.started` `:892-902`; `canClearReview`
  `:937-939`; `renderBinding` `:974-986`; `resetTranscript` `:996-1017`; `sendFollowUp`
  `:1035-1065`; `revealFinding` `:1173-1182`; `entity.show` without a chat id `:1265`; `decide`
  `:1282-1302`; single-route `answer` `:1304-1329`; `requestInit` `:1554-1579`. `render.js`:
  `findingCard` `:248-274`; `details` `:345-376`; `evidenceCard` `:457-490`; `errorCard`
  `:497-516`; `coverageSummary` `:524-572`; `attentionPanel` `:595-613`; `usageLine` `:731-751`.
  `web/shared/attention.js` `attentionRow` `:96-110`, `attentionMeta` `:117-135`. `app.css` stale
  `:289-295`, panel height `:324-328`, fold `:666-669`, clamp `:735-744`.
- **Page rules**: `PageRuleScanTests` vocabulary `:47-61`, allowed orders and comparisons (including
  `body.status === 'answered'`), the comparison regex `:427-435`, every script of the three pages
  scanned once (`PageScripts.Collect`).
- **Host**: `ReviewHost.cs` `SessionRecord` `:84-116`, `Sessions` `:304-313`, `LatestSession`
  `:326`, `TrackSession` `:329-344`, `TrackCheck` `:356-366`, `FindSession` `:369-375`, `Dispatch`
  `:480-535`, `StartReview` `:922-1047` (`TrackSession` `:1031`, `review.started` `:1036-1042`).
  `PaneActions.cs` `PaneRunLookup` `:39-65`, `TryHandle` `:152-176`, `ShowEntity` `:185-213`,
  `TryRunDirectory` `:360-383`. `ReviewServices.cs` `EntityShowRequest` `:133-151`.
  `SwEntityResolver.cs` lookups `:50-72`. `RunPackageIndex.cs` constructor `:64-68`.
  `SwReviewAddIn.cs` `:388`, `:440`, `:461-462`, `:494-499`, `:268`, `:1014`.
  `IBackendClient.cs:96-108`.
- **Backend**: `report/attention.py` as cited in R2.2-R2.4; `report/attention_record.py:84-102`;
  `report/unexamined.py:64-89`; `report/rerender.py:69-154`; `report/session.py:65-74`, `:348`,
  `:420`; `report/explanations.py:155-156`; `tools/session.py:50-78`, `:180`;
  `tools/recording.py:36-44`, `:75`; `agent/events.py:102-104`, `:134-174`; `agent/runner.py`
  `:555-586`, `:654-661`, `:693-726`, `:745-775`; `chat/server.py` `ChatError` `:185-198`,
  `resolve_run_dir` `:454-477`, `check_result` `:697-735`, `_finding_row` `:802-831`,
  `create_session` `:1108-1140`, `attention` `:1145-1168`, `answer_evidence` `:1208-1228`,
  `read_check` `:1345-1359`, `_check_dir` `:1407-1422`, `_chat` `:1696-1701`, `_render_report`
  `:1972-1994`, routes `:2141-2170`; `chat/sessions.py` `ChatSession.public` `:306-322`.
- **Contracts**: `review-session.schema.json:118-127`; `chat-events.schema.json:32-33`;
  `chat-api.md` route table; `pane-host-messages.md:78-91`, `:117-123`;
  `attention.md` section 6.
- **Tests**: `test_chat_server.py` `ROUTES` `:272-285`; `test_usage_contracts.py:217-221`;
  `test_tool_payload.py:299-309`; the ten golden baselines of R2.20; the page tests named in R2.21,
  R2.23 and R2.26.
- **Interop**: the two `ActiveConfigChangePostNotify` handler types of R2.18.
- **Feature 008**, as planned: `contracts/answer-batch.md` sections 1-2; `contracts/checks-first.md`
  section 6; `contracts/replay.md` sections 4, 5, 8; `contracts/cost.md` section 4.
- **Feature 010**, read while it was being planned (uncommitted): `contracts/contacts.md` sections
  3-4; `data-model.md` sections 9 and 14; `tasks.md` T016, T020, T022, T037, T043, T047, T061,
  T067, T075.

---

## R4. Amendments to the spec made by this pass

| Where | Was | Now | Why |
|---|---|---|---|
| FR-007, Key Entities | groups "by the ranking's own keys" | counted over findings; a folded family's findings are its own line and in no group; decided and within-limits are two further groups shown when non-zero | R2.3 |
| FR-007 | one state per goal "with a short reason" | the short reason is a fixed category word; the recorded sentence is in the fold | R2.4 |
| FR-013 | "the check goal it blocks" | the checklist item it blocks; the summary shows that item's goal | R2.9 |
| FR-016 | "the last round's measured input size" | the last conversation round, before the most recent `text.done`, so the explanation pass is not taken for it | R2.11 |
| US5 | Results shows "the follow-up box" | the follow-up form sits outside both views and is visible in both | R2.12 |
| FR-019 | pinned under its question | pins live in page memory per chat; gone after a page reload or a backend restart, the answer still in the transcript | R2.13 |
| US6, FR-020 | "choosing a chip" | choosing a chip, and also returning to a document shows its newest kept review when no turn runs | R2.16 |
| FR-021 | "restorable read-only from its run folder" | results restored; the transcript of a review restored from its folder is not, and the pane says where it is | R2.17 |
| FR-024, FR-025 | "the default view" | the Review tab's default view for labels; ids move into folds on the Review tab and in the shared Start-here and rule rows of the check tabs | R2.19, R2.21 |
| FR-012 | wherever a component has a name | the Review tab; the check tabs keep ids in their subject lists | R2.21 |
| FR-028 | statements rather than the fraction | needs the backend to send the unresolved rules' statements (`rule_statements`) | R2.23 |
| FR-027 (owner, 2026-09-23) | titles not truncated; the page clamps them | the titles an engineer reads - Review tab, the check tabs' Start here, `report.md` - are whole and named; the title the model reads stays as recorded | R2.28 |

---

## R5. Open items that stay open

| Item | Owner | Blocks |
|---|---|---|
| Whether modelling practice belongs under the hygiene goal (the table's first opinion) or is a ninth goal line | owner | nothing; a data row |
| The goal state words ("issues found", "checked, no issue", "not reached", "not applicable") and reason words are first opinions beside the owner's "Decide / Fix / Verify" | owner | nothing; data |
| Hole ids (`hole:0012`) stay in hole-alignment titles; plain words would need the hole-to-part map | owner, later | nothing |
| SOLIDWORKS API tokens (`swMateCONCENTRIC`, `swSelFACES`) in RMS titles come from the checks' observed strings; rewording them changes findings' evidence | owner, later | nothing |
| `swreview attention` prints Start here with the recorded titles (cut, ids): it is a command-line reader of `attention.json`, and a CLI in the pane's terminal is often a model reading it, so it was left with the model's title (R2.28) | owner | nothing |
| `report.md` could lead with the same summary block (one source); not done so the report goldens hold | owner | nothing |
| The backend never evicts chats, so a night of kept reviews holds every run's package in memory (fact 25: 1.48 MB on disk for the big assembly); evicting ended chats after their snapshot is a follow-up | backlog | nothing |
| Follow-up questions are not on the event stream, so pinned answers do not survive a page reload; an in-memory list on `ReviewRun` would cover the reload case | backlog | nothing |
| A contact list delivered before 010 lands is `None`; the page's contacts fold is proven on `SummarySample`'s hand-added contacts until then | feature 010 (T020, T022) | FR-011's backend half |
| 010's task ids were read from its `tasks.md` while it was being written; they are re-verified before T018, T034 and T062 start | this feature | nothing |
| Collapsing the modelling-practice cards happens when the ranking arrives at the end of the turn; during checks first's pre-run they stream in one by one | owner | nothing |
| The cross-tab Show risk was inferred from code (fact 5); Phase 9 confirms it on a seat | next sitting | nothing in code |
| SC-002 and SC-007 are judged by an engineer at the next sitting | owner | Phase 9 |
