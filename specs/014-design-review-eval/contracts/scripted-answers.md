# Contract: Scripted Answers and the Answer Driver

Normative for FR-022 to FR-026, the answer-turn bound of FR-013, and User Story 4. Research D3,
D14.3, D16, §7 ("The review run, turns and the answer path"), §8.3. How a request is matched to a
scripted answer is `questions.md` section 3; this contract calls that rule and does not restate it.
Line numbers are at `be01974`; paths are under `reviewer/src/swreview/` unless another root is
given. Every example value is fictional.

What this contract fixes: where a case's scripted answers live and when they are refused; how
`benchmark run` holds a review open and answers its questions through the method the pane's Send
reaches; what Skip means; when answering stops; and the per-package record, `answer-log.json`, that
the scorer reads in place of the case file, which only the driver ever opens.

## 1. What is reused

| Piece | Where | Used as |
|---|---|---|
| A review held open | `agent/runner.py:1497` `start_review` returns a `ReviewRun`; `:1113` `start`; `:1138-1202` `answer_evidence_batch` | The driver's only way to play turns. `run_review` (`:1815-1848`) is start-then-close, one turn, and stays the `review` command's |
| The pane's Send | `extractor/SwReview.AddIn/Review/ReviewPage/app.js:2154-2166` (every answered, not-skipped question, trimmed, in the summary's order), `:2289-2293` (Send does nothing with no answer); `chat/server.py:1384-1399` (the batch route calls `run.answer_evidence_batch(answers)`), `:1402-1431` (shape: non-blank strings, no id twice) | The parity reference (FR-023) |
| The pane's Skip | `app.js:2233-2242`: "Skipped stays open and unresolved in the backend: nothing is sent for it" | D3 |
| The questions' order | `report/summary.py:662-694`: open requests in session order | The order of a batch |
| Open requests | `agent/runner.py:549` `open_evidence_requests` | The one enumeration, read after every turn |
| When the pane waits | `chat/server.py:2199`: `waiting_engineer` only while a request is open | The loop's condition |
| The regrade | `agent/runner.py:1180-1193` (`_regrade_roles`, `_restate`, `REGRADED_LINE`), inside `answer_evidence_batch` | US4-7 needs nothing new |
| How a turn ended | `agent/runner.py:1457`, `:1366` (`turn.ended {reason}`); `agent/events.py:234` (a raised turn emits `turn.ended {"reason": "error"}` before it propagates); `agent/events.py:122` `EventSink.add_listener` | `start` and `answer_evidence_batch` return the session, not the `TurnResult`, so the driver listens for `turn.ended` |
| A driver of answer turns | `benchmark/replay.py:436-457` (`_drive`: recorded answers through `answer_evidence_batch`) | Precedent only: it plays recorded tool calls, not a live model |

No product method changes for the driver. `answer_evidence_batch`'s own refusals (`:1152-1157`:
empty, repeated, unknown or answered ids) cannot fire on a driver batch, which names only ids the
live session holds open; they stay the one validator the route also uses (`answerable`, `:879`).

## 2. The case file

### 2.1 Where it lives

- **Committed cases**: `benchmarks/case_files/<package_id>.json`, written by the generator from the
  case spec (FR-027), and named by the set entry's `case_file` field as a repository-relative path.
- **Private cases**: the set entry's `case_file`, an absolute path outside the repository (FR-030).
- Nothing is looked up by convention: a set entry without `case_file` has no scripted answers, and
  every question of its reviews is unscripted.
- A case file that resolves inside any package folder the set names is refused at set load
  (FR-022, "outside the package"). The key-isolation guard's half is section 6.

### 2.2 Format

```json
{
  "case_file_version": 1,
  "package_id": "fict-r3-press-fit-a",
  "answers": [
    {"id": "A-1", "item": "interfaces.fit", "ids": ["cmp:0001", "cmp:0002"],
     "answer": "press fit"},
    {"id": "A-2", "item": "fasteners", "ids": ["doc:0002"],
     "answer": "the screws are in a separate assembly"},
    {"id": "A-3", "part_roles": true, "answer": "All bought"}
  ]
}
```

| Field | Rule |
|---|---|
| `case_file_version` | `1`; any other value is refused |
| `package_id` | equals the set entry's `package_id` |
| `answers[].id` | `A-<n>`, unique in the file; the only thing about an entry any run folder ever records |
| `answers[].part_roles` | `true` for the answer to the part-roles question (`questions.md` section 4); `item` and `ids` are then absent |
| `answers[].item` | otherwise required: a checklist item id, or `null` for a question naming no item |
| `answers[].ids` | otherwise required and non-empty: component instance ids or document ids of the package ("parts or documents", FR-022); a hole or fastener a request names resolves to its instance (`questions.md` section 2), so an entry never needs one |
| `answers[].answer` | the engineer's words: non-blank, sent trimmed, as the page trims (`app.js:2162`) |

The model is strict: an unknown field is refused, never ignored.

### 2.3 Refusals at run start

`benchmark/runner.preflight_set`, which `run_benchmark` requires (`benchmark-run.md` section 3 row
4; plan decision INT-14), loads and checks every case file the set names, in set order, **before
the first review** and after the profile preflight (FR-050), so a library caller gets the same
guarantee as the command line. The first failing row of the first failing file ends the run: `benchmark run`
exits 1 with one line naming the case file (its set-relative path, or its file name for a private
entry) and the entry. No package folder is created.

| # | Condition | Message gist |
|---|---|---|
| 1 | unreadable, not JSON, an unknown field, another version | "case file {name}: {reason}" |
| 2 | `package_id` differs from the set entry's | names both ids |
| 3 | an entry id repeated; an entry with both `part_roles` and `item`/`ids`, or neither | names the entry |
| 4 | a blank answer | the pane route's rule (`chat/server.py:1417-1426`) |
| 5 | `item` not a checklist item (`agent/checklist.py:64-66`) | names the entry and the item |
| 6 | `item` is code-owned (`ChecklistItem.owner`, `agent/checklist.py:60`): `request_evidence` answers such an item `closed_by_code` and records nothing (`tools/session.py:112`), so the question can never be open | "can never be asked" |
| 7 | an id that is not a component instance or a document of the package | names the entry and the id |
| 8 | two entries on one item, or two with no item, whose resolved ids intersect (`questions.md` section 2): a request naming a shared id would match both (research §8.3; RR3-4) | names both entries |
| 9 | two `part_roles` entries | names both |
| 10 | a `part_roles` entry when the run's profile would not ask the part-roles question of this package: `part_roles.roles_question(classify_parts(package, profile, None, profile_refusal=None), package)` is `None` (`checks/part_roles.py:659, 881-899`), because there is no profile, the classifier's state is absent (`:725-738`), its zero-match guard fires, or no part is unclear | names the entry and the classifier's reason |

Row 10 is US4-8's "a part-roles answer whose question the run's profile would never ask": the
scripted answer can never be delivered. It uses the product's own classifier over the same package
and profile the review will load, so it cannot disagree with the review (plan decision QA-5).
Testing for the profile's section instead (`profile.part_roles is None`) would refuse a
convention-only profile whose question is asked (`:735-736`) and pass a section whose question
never is.

## 3. The driver

```python
# reviewer/src/swreview/benchmark/case_file.py  (data only: CaseFile, ScriptedAnswer)
# reviewer/src/swreview/benchmark/answers.py
def load_case_file(path: Path, *, entry: BenchmarkPackageRef, package: EvidencePackage,
                   checklist: Checklist, profile: StandardsProfile | None) -> CaseFile: ...
def drive_review(run: ReviewRun, case_file: CaseFile | None, *, max_answer_turns: int,
                 stop_requested: Callable[[], bool]) -> AnswerLog: ...
```

The case file's models live in the data-only `benchmark/case_file.py`, so the generator can write
case files through them without importing this module, which imports the agent's runner
(`generator.md` sections 7 and 9; plan decision INT-6). `load_case_file`, section 2.3's refusals,
the driver and the answer log live here. `stop_requested` is added with the robustness slice
(`benchmark-run.md` section 5.1), which supplies the attempt's stop; until then the driver takes no
such argument (plan decision INT-7).

`cli._review_fn` (`cli.py:2192-2223`) calls `start_review` with the same arguments it passes
`run_review` today, then `drive_review`, then `run.close()` in a `finally`, as `run_review` does
(`agent/runner.py:1845-1848`). The case file `preflight_set` loaded and the bound reach it through
`run_benchmark`'s one new keyword, `attempt` (`AttemptRequest.case_file` and `.max_answer_turns`,
`benchmark-run.md` 5; plan decision RF-44). Every benchmark package goes through the driver, with or
without a case file, so every run folder carries an answer log.

**Terms.** An **answer point** is the moment after a turn ended with reason `end` and before the
next one. An **answer turn** is one `answer_evidence_batch` call and the turn it resumes. A
**delivery** is one request answered at a point, with the case-file entry that answered it.

In order:

1. Attach a listener to `run.sink` that keeps each `turn.ended` reason.
2. `run.start()`: the opening turn, as the pane plays it.
3. At each answer point:
   1. If the last turn's reason is not `end`, stop: `ended` is `turn_did_not_end`. A turn cut at its
      step or output limit, or stopped by the provider, is the arm's own outcome (D2, US7-7);
      the run-status contract classifies it (plan decision QA-4). If `stop_requested()` is true,
      stop: `ended` is `stopped`, and nothing is sent (the attempt's wall clock, `benchmark-run.md`
      section 5.3).
   2. Read `open_evidence_requests(run.session)`, in session order. None open: stop,
      `no_open_questions`, and record no point.
   3. Match each open request (`questions.md` section 3): a delivery, or unscripted with a reason
      (`no_answer`, `ambiguous` naming the entries, `names_nothing`).
   4. Record the point: `steps_before = len(run.session.steps)`, its deliveries and its
      unscripted requests.
   5. No delivery: stop, `all_unscripted` (D3, US4-3). The open requests stay open, and
      finalization, which has already run, lists them as unresolved coverage.
   6. Answer turns already played equal `max_answer_turns`: move the deliveries to `held`, send
      nothing, stop, `bound_reached` (section 4).
   7. Otherwise `run.answer_evidence_batch([(request.id, text), ...])`, deliveries in session
      order: one batch per point, as Send sends one (US4-4).
4. Write `answer-log.json` (section 5) in a `finally`; an exception a turn raised then propagates
   to the run-status layer, the log recording `turn_did_not_end` and the last reason the listener
   saw.

**An entry answers every time it is asked** (plan decision RF-13). Nothing limits an entry to one
delivery: at each answer point every open request is matched afresh, and an entry is delivered at
every point where it is the one entry an open request asks within. A model that asks again after
its question was answered, with a request the product records (an item-only follow-up is recorded,
`report/session.py:208`), gets the same answer again, as the pane's engineer would answer it, and
the scorer counts that request as a re-ask seen (`questions.md` 3). The bound (section 4) is what
ends a model that keeps asking. A follow-up the product refuses as `already_answered` opens no
request, so no answer point sees it and nothing is sent.

**The answer text.** Sent as the entry's `answer`, trimmed, whatever the question offers. When the
question offers options and no text box (`allow_text` false), the page draws buttons only
(`extractor/SwReview.AddIn/Review/ReviewPage/render.js:640-662`), so an answer that is not exactly
one of them is one the page could not have sent, though the route accepts it
(`chat/server.py:1402-1431`). Such a delivery is sent and marked `outside_options` in the log,
shown and never scored (plan decision QA-8). The part-roles question offers a text box
(013 `contracts/part-roles.md` section 8), so its answer is never outside the options.

**A confirmed drawing read never happens in an attempt** (spec Edge Cases; plan decision INT-8;
research §9.11). The drawing candidate question is asked only when the host opens closed
drawings (`checks/drawing_context.py:492-504`), and an attempt has no bridge, so its read mode is
`none` (`tools/drawings.py:79-90`): the spec's "a confirmed drawing read records no connection" is
unreachable in a benchmark attempt, and section 7 pins that rather than a path no attempt takes.

**What the driver never does.** It sends no text for an unscripted question: sending "skip" would
record an answer no pane session records and hand the re-ask rule an answered question the
engineer never answered (D3). It calls no `continue_session`: case files script answers only
(FR-022; plan decision QA-20). It answers after no turn that ended other than normally. It reads
no answer key (FR-032). It writes no case-file text anywhere.

**One run's answers are the pane's.** The resumed message is `answers_message` byte for byte
(`agent/runner.py:248-262`), with the drawing outcome lines above it and the regrade line below it
exactly as the pane's batch gets them (`:1186-1195`); the answers reach the session and the event
stream as `evidence.answered` events (`:1159-1163`), which the recording reader already reads as an
answer turn (`benchmark/recording.py:13-16`). A scripted "All bought" is regraded before the next
turn by `_regrade_roles` and `_restate` inside the same call (`:1180-1193`), so the pin's
modelling-practice and hygiene findings are withdrawn with `finding.withdrawn` before the resumed
turn starts (US4-7). The only differences from the pane are the HTTP layer and the page (section
7's parity test).

## 4. The bound

- `benchmark run --max-answer-turns N`, an integer of 0 or more, default 3 (D14.3). 0 plays the
  opening turn only, which is what every benchmark run did before this feature.
- Provenance records it as `max_answer_turns` (FR-013). A record written before this feature has
  none and reads `None`, rendered "not recorded", never 3. Compare adds the field to the must-match
  fields of a study (`benchmark/compare.py:499-501`; D5, D14.3): the compare contract enforces it,
  this contract names it.
- **Bound-reached**: at the answer point after the `N`-th answer turn (after the opening turn when
  `N` is 0), at least one open request has a delivery. A review whose scripted questions are all
  answered by then, or whose open questions are all unscripted, is not bound-reached (plan
  decision QA-3).
- A bound-reached review ended every turn normally: it is completed, graded from its final state,
  and counted as bound-reached, a shown-only column (D16, FR-025, FR-059). The run-status and
  scorecard contracts read `ended` from the log.

## 5. The answer log

`<run>/<package_id>/answer-log.json`, written by the driver only, through `write_atomic` (plan
decision RF-31):

```json
{
  "answer_log_version": 1,
  "points": [
    {"after_turn": 0, "steps_before": 14,
     "sent": [{"request_id": "ER-002", "entry": "A-1"},
              {"request_id": "ER-001", "entry": "A-3"}],
     "unscripted": [{"request_id": "ER-003", "reason": "no_answer"}],
     "held": []},
    {"after_turn": 1, "steps_before": 27,
     "sent": [],
     "unscripted": [{"request_id": "ER-003", "reason": "no_answer"},
                    {"request_id": "ER-005", "reason": "ambiguous", "entries": ["A-4", "A-5"]}],
     "held": []}
  ],
  "ended": "all_unscripted",
  "last_turn_end": "end",
  "unused_entries": ["A-2"]
}
```

| Field | Meaning |
|---|---|
| `points[].after_turn` | the turn the point follows: 0 for the opening turn, `k` for the `k`-th answer turn |
| `points[].steps_before` | `len(session.steps)` at the point. Every step with this index or later comes after this point's answers, the restated regrade steps included; `questions.md` section 1 places answers in time with it |
| `points[].sent` | the deliveries, in session order: request id, entry id, and `outside_options: true` only when section 3 marks it (omitted when false, as the session omits its false fields, `report/session.py:70-71`) |
| `points[].unscripted` | the open requests given nothing at this point, with the reason; an ambiguous one names the entries it matched |
| `points[].held` | the request ids a delivery was ready for when the bound stopped the review |
| `ended` | `no_open_questions`, `all_unscripted`, `bound_reached`, `turn_did_not_end` or `stopped` (the attempt's stop was set at an answer point) |
| `last_turn_end` | the last `turn.ended` reason: one of `TurnEndReason` (`agent/providers/__init__.py:121`) |
| `unused_entries` | entry ids of the case file no point delivered |

Answer turns played are the points with a non-empty `sent`; the count is derived where rendered,
never stored (SP-14). The log holds ids only: no answer text, which the session already holds for
every delivered answer, no unused answer's text, and no path (FR-051). It is the driver's record of
its own decisions, which nothing else records: which questions were unscripted and why, and what
the bound held back. The scorer reads it and never reads the case file (`questions.md` section 6).

## 6. Isolation and the saved set

- **The key-isolation guard.** The protected segments of `ir/loader.py:23` gain
  `("benchmarks", "case_files")`, so `reject_answer_key_path` (`:46-62`), and through it
  `load_package`, `load_set` (`benchmark/sets.py:52`) and the runner (`benchmark/runner.py:237-239`),
  refuse a committed case file's path to the reviewer. A private case file is refused through the
  paths the set names, by the one guard the answer-key and benchmark-set contracts extend for private
  keys (D7): a package path that is, or lies under, the folder of any case file the set names is
  refused at set load. This contract requires the case-file half and pins it (US4-9).
- **Who reads a case file.** Only `benchmark/answers.load_case_file` (the generator writes them
  through `benchmark/case_file.py`'s models and its tests load them through `load_case_file`). A
  structural test holds that no module under `tools/`, `agent/` or `checks/` imports
  `benchmark/answers.py` or `benchmark/case_file.py`, and that neither imports an answer-key module
  (runs never read keys, FR-032).
- **Both arms get the same answers** (US4-6). The loaded set carries, per package, `case_file` (as
  the set names it) and `case_file_sha256`, the digest of its bytes. They reach the saved set
  (`cli.py:2313-2314`) and so `set_digest` (`:2327`), which compare already requires equal within a
  study (`benchmark/compare.py:499-501`) and checks against the saved copy (`:398-413`). A study
  whose arms read different case-file bytes is refused by the existing set-digest rule, with no
  second must-match field (plan decision QA-7). A committed set names its case files relatively,
  so the digest is the same from any checkout (FR-051; the saved-set design is the benchmark-set
  contract's).

## 7. Tests

Every test here fails before its behaviour exists (constitution III). The scripted provider is
`agent/providers/fake.py`'s `FakeProvider`; each test scripts exactly the turns it expects, since the
fake refuses a turn beyond its script (`:372-382`), which is itself the assertion that no answer turn
was played.

`reviewer/tests/unit/test_benchmark_case_file.py`:
- a case file with an item answer, a no-item answer and a part-roles answer loads (FR-022);
- each of section 2.3's rows 1 to 9 is refused, the message naming the case file and the entry
  (US4-8), row 8 with a document and one of its instances as the intersecting pair (plan decision
  QA-11) and with two disjoint entries on one item loading (RR3-4);
- row 10: refused with no profile, with a profile in the absent state, and on a package whose parts
  are all decided; loaded under a convention-only profile that asks (plan decision QA-5);
- every refusal happens before any review: a spy `review_fn` is never called and no package folder
  exists (US4-8);
- a case file inside a package folder the set names is refused at set load (FR-022).

`reviewer/tests/unit/test_benchmark_answers.py`:
- `test_an_attempt_never_asks_the_drawing_candidate_question`: a package with drawing candidates
  reviewed with `bridge=False` reads `drawing_read` `none`, and `candidate_question` returns `None`
  under it, so no confirmed read can be answered (section 3);
- the fit question (`blocks` `interfaces.fit`, the pin and the plate's hole) answered by `A-1`: one
  `answer_evidence_batch` call, one `evidence.answered` event with the entry's text, the second
  turn's user message equal to `answers_message([(<the request's id>, "press fit")])` as the fake
  received it, and the review continuing into that turn (US4-1, FR-023);
- an unscripted question: no `evidence.answered` for it, the session's evidence coverage unresolved,
  the log listing it `no_answer` (US4-2, FR-024, D3);
- a turn whose open questions are all unscripted: the fake is asked for no second turn, `ended`
  `all_unscripted` (US4-3);
- two scripted and one unscripted in one turn: one batch of two, in session order, one resumed turn
  (US4-4);
- re-delivery (RF-13): after `A-1` answers the fit question at point 0, a follow-up on
  `interfaces.fit` naming no ids is recorded and gets `A-1` again at point 1: two points each
  sending `A-1`, two answer turns, the fake scripting three turns; a follow-up naming only the pin's
  hole is refused `already_answered`, opens nothing, and the next point is `no_open_questions`;
- the bound: a model that asks again in every turn gets three answer turns, the fourth point's
  delivery is `held`, `ended` `bound_reached`, and the session is finalized (US4-5, FR-025, D16);
  the bound at 0 plays the opening turn only; a review whose last scripted question is answered on
  its third answer turn and asks nothing more is `no_open_questions`, not bound-reached (plan
  decision QA-3);
- no answer after a turn ending `max_steps`, `truncated` or `error`, with a scripted question open:
  `turn_did_not_end` and that reason (plan decision QA-4, D2);
- a turn that raises: the log is written with `turn_did_not_end`, then the exception propagates;
- an item-only request on an item with two entries: unscripted, `ambiguous`, both entries named
  (spec Edge Cases);
- an answer outside a closed set of options: sent verbatim, marked `outside_options`; an answer equal
  to an option: unmarked (plan decision QA-8);
- the log holds no answer text and no path, and lists never-delivered entries by id (FR-051);
- with no case file, every open question is unscripted `no_answer` and no answer turn is played (D3);
- each point's `steps_before` equals the step count at its batch's first `evidence.answered` event in
  `events.jsonl`, on a run with two answer turns and a regrade (the two records cannot drift);
- structural: `benchmark/answers.py` imports no answer-key module, and nothing under `tools/`,
  `agent/` or `checks/` imports it (FR-032).

`reviewer/tests/unit/test_benchmark_answers_parity.py`: one package and one scripted model, played
once through the chat server's `POST /sessions` and `POST /sessions/{id}/evidence` and once through
`start_review` and `drive_review` with the same settings: the requests (ids, status, answer), the
`evidence.answered` events, the resumed user message the fake received, and the findings are equal
(FR-023; the US4 Independent Test's "as the pane would").

`reviewer/tests/unit/test_benchmark_answers_roles.py`, on `tests/support/roles_review.py`'s package
and profile: a scripted "All bought" withdraws the unclear parts' modelling and hygiene findings with
`finding.withdrawn` before the resumed turn's first `usage` event, the resumed message ends with the
regrade line, and the final session holds none of them (US4-7); the part-roles answer and a model
question's answer go in one batch (US4-4).

`reviewer/tests/unit/test_answer_key_isolation.py`: a committed case file's path, and a private
case file's path a set names, are refused to `load_package`; a set whose package path lies under a
case file's folder is refused at load (US4-9, FR-030). The pins go in the unit file only: the
integration file of that name is module-marked `integration`, which `reviewer/tests/conftest.py:72-82`
skips wherever the native package is absent, this development machine included (plan decision
RF-26).

`reviewer/tests/unit/test_benchmark_runner.py`: `run_benchmark` checks every case file before the
first review (US4-8), and its existing call passes the `PreflightedSet` it now requires, as the other
five existing calls do (`benchmark-run.md` 15 names them); the saved set carries each `case_file_sha256`, and one changed byte in a case
file changes `set_digest` (US4-6, plan decision QA-7); provenance records `max_answer_turns`, and a
record without it reads `None` (FR-013).

`reviewer/tests/unit/test_cli.py`: `benchmark run` takes `--max-answer-turns`, default 3, refuses a
negative value, and turns a case-file refusal into exit 1 with one line (FR-025, US4-8).

`reviewer/tests/unit/test_benchmark_compare.py` (the compare contract's code; named here because
this contract relies on it): a study whose arms' saved sets differ only in a case file's digest is
refused naming `set_digest`, and one whose runs differ in `max_answer_turns` is refused naming that
field (US4-6, D14.3).

`reviewer/tests/integration/test_scripted_answers_flow.py`, not marked `integration` (it needs no
native package; RF-26): `benchmark run` over a fictional package and its case file, with
`provider_factory` patched to a scripted model that asks the fit question naming the pin and the
plate's hole, receives "press fit", and then asks for numeric limits naming only the plate's hole,
which the product's guard refuses `already_answered`, then ends; scored against a key with no other
entries: one point with one delivery of `A-1` and one answer turn in the log, `ended`
`no_open_questions`, one re-ask (refused, of the answered request) on the scorecard, and the
session's request answered with the entry's text beside its `evidence.answered` event (the US4
Independent Test: "records one answer turn, a scripted re-ask is counted, and the session shows the
answer as the pane would"). The seen re-ask and its re-delivery are
`test_benchmark_answers.py`'s and `test_questions_on_real_tools.py`'s (RF-13).
