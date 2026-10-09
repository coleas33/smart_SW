# Research: Send the Review to the Model Only When the Engineer Wants It

**Feature**: `015-review-send-gate` | **Date**: 2026-10-08 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the owner's request and decisions 59A to 62A of 2026-10-08 (spec, top); four
read-only maps of the same day (plans and history, the reviewer pipeline, the add-in flow and
settings, what is sent and the approval patterns), held outside the repository; and a second pass
on 2026-10-08 that opened every file this package cites on branch `015-review-send-gate` at
`7554445` (the spec commit on `838b66b`, whose product code it equals). Where this document says
**VERIFIED**, the file was opened on 2026-10-08 at that commit. A third pass on 2026-10-09, after
the plan's adversarial review, opened every file its fixes cite at the same product code (marked
*revised 2026-10-09* where an entry changed, and R2.27 added). A fourth pass the same day, after
the plan's second adversarial review, opened every file its fixes cite at the same product code,
re-read branch 014 at `45b5076`, and measured the pane's 300 by 600 budget on the committed build
(R2.21); entries it changed are marked *second review, 2026-10-09*, and R2.28 is added. Line
numbers drift; every task re-verifies before editing.

The owner asked for no interactive questions. Every question the spec left open is settled here by a
default, marked **default taken 2026-10-08, the owner may revise**; the three the spec already put
to the owner (its questions 2 to 4) keep the spec's defaults. The questions this plan adds are
listed in R6 and returned with the plan; none blocks the tasks.

Every example value in this package is fictional (`FICT-`); no design name, number, company value
or local path is written here.

---

## R1. Sources and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | Four user stories, FR-001 to FR-042, SC-001 to SC-010, owner decisions 59A to 62A | Normative for what is built |
| The four read-only maps (2026-10-08, outside the repository) | Path:line facts on the pipeline, the add-in, the approval precedents and the tests | Starting facts; every one used here was re-read (VERIFIED) |
| The 014 worktree (`smart_SW-014`, branch `014-design-review-eval` at `907a621`, not merged) | Changes to files this feature also changes | Read only, for the merge note (R3) |
| The constitution 1.1.0 | Principles I to VI, the read-only rule | The gate (plan.md); this feature adds no exception |

---

## R2. Decisions

Each entry: the decision, the default tag where it is not the owner's words, why (VERIFIED facts),
and the alternatives weighed.

### R2.1 One setting, `send_when_checked`, everywhere

**Decision**: one boolean named `send_when_checked` - in `settings.json`, in the host's settings
view, in the `POST /sessions` body, and in `session.started`'s body when false. `true` (ticked) is
the default and means today's behaviour. The settings file stores it as an optional value: absent,
`null` or anything but a JSON boolean reads as `true`; it is written only once the engineer has
changed the box, so a file written before this feature loads and saves to its own bytes (FR-036).
A non-boolean value is reported as one load problem ("send_when_checked '...' is not true or
false; ticked is in use.") and every other field loads as today (FR-002). (`contracts/pane.md`
section 1.)

**Default taken 2026-10-08, the owner may revise** (the name; 59A decides the behaviour).

**Why**: VERIFIED that the settings schema refuses unknown keys (`specs/002-task-pane-assistant/
contracts/settings.schema.json:7`, `"additionalProperties": false`), that `UserSettings` writes with
`DefaultIgnoreCondition = WhenWritingNull` (`extractor/SwReview.AddIn/Settings/
UserSettings.cs:123-131`), and that `Load` deserializes the whole file in one call, so a value of
the wrong JSON type throws `JsonException` and the whole file falls back to the defaults
(`UserSettings.cs:227-238`): a plain `bool` property would lose the provider, model and stored key
over one bad box value, which FR-002 forbids. A property that accepts any token keeps the rest: the
file's token is held raw (`JsonElement? SendWhenCheckedValue`), the `bool?` is derived from it, and
`Normalize` reports and clears a non-boolean (data-model section 1). A converter that read a bad
token as `null` cannot report it: VERIFIED (second review, 2026-10-09) that the `problems` list is
created by `Load` only after the deserializer returns and filled by `Normalize(mode, problems)`
(`UserSettings.cs:253-255`, `:400-445`), which a converter cannot reach. VERIFIED that the lever
guard scans both files as text for each of the fourteen lever names
(`reviewer/tests/unit/test_no_lever_in_pane_settings.py`, `LEVER_NAMES`): `send_when_checked`
contains none of them, so the guard passes unchanged (FR-004); the schema's description must not
mention `prerun_checks` either.

**Alternatives**: a name per surface (`auto_send` in the file, `send` in the body) - two words for
one fact; reusing a lever (`prerun_checks`) - refused by the guard and by 59A, which makes this a
review-flow setting; a plain `bool` written always - a pre-feature file would gain a line on its
first save.

### R2.2 The box writes without a restart, and is never refused

**Decision**: a new page-to-host message, `send_when_checked.save {send_when_checked}`, answered
`send_when_checked.saved {send_when_checked}`. The host clones its settings, sets the value, saves
the file (the existing atomic `UserSettings.Save`) and replaces its settings; it does not restart
the backend and does not ask whether a turn runs. A failed write answers `error {error_class:
"SettingNotSaved"}`; the page puts the box back to the stored value and prints the label for that
class under the box. `settings.save` keeps the value (it already clones every field the page does
not send). (`contracts/pane.md` sections 1 and 12.)

**Default taken 2026-10-08, the owner may revise** (the message; 60A decides "no restart").

**Why**: VERIFIED that `settings.save` always restarts the backend (`ReviewHost.cs:916`) and is
refused while a turn runs (`ReviewHost.cs:798-803`), which 60A rules out for the box; that the
host clones the settings before applying a save, so fields the page does not send survive
(`ReviewHost.cs:879`, `Clone` at `1406-1413`); that `UserSettings.Save` writes a temporary file and
`File.Replace`s it (`UserSettings.cs:263-286`). VERIFIED that page messages are handled one at a
time on one pump thread, which is blocked for the whole of a `review.start` (`SwReviewAddIn.cs:
1257-1289`; `ReviewHost.Receive` is not re-entrant, `ReviewHost.cs:257-264`): a box change made
during extraction is therefore written when the pump is next free, in order, exactly as FR-002
says, with no extra mechanism.

**Alternatives**: the box inside the Settings section and saved with it (refused by 60A: hidden and
restarting); page `localStorage` (no page uses it, and it would not reach the host that reads the
value at `review.start`); a value sent with each `review.start` (a second source of truth beside
the stored one; R2.3).

### R2.3 The host reads the stored value when a review starts

**Decision**: `review.start` carries nothing new. The host reads `send_when_checked` from its
settings when it handles `review.start` (Review, "Review available evidence", Retry) and passes it
to `POST /sessions`; `review.started` gains `send_when_checked`, the value the review started with.
`NewSessionRequest` gains `SendWhenChecked` (default `true`) and `Recheck` (R2.17), and
`BackendClient.CreateSession` always writes both. (`contracts/pane.md` section 2,
`contracts/review-flow.md` section 1.)

**Why**: VERIFIED that the host builds the session request from its own settings
(`ReviewHost.cs:1295-1305`) and that the body is exactly eight fields today
(`BackendClient.cs:131-150`). Because the pump handles messages in order, a review started after a
box change uses the new value and a running review keeps the one it started with (FR-002, FR-003).
`review.started` carries the value so the page knows at once that this review will wait, before
any event arrives, and never marks a turn running for it (FR-025).

**Alternatives**: the page sends its box value in `review.start` (two sources; and a box whose
write failed would still govern the review); the backend reads the settings file (it never does:
`chat/server.py:1999-2002`).

### R2.4 One new chat state, `awaiting_send`; work on a waiting review runs as `running`

**Decision**: `ChatState` gains `awaiting_send`. Transitions added: `extracting -> awaiting_send`
(checks done, box unticked), `awaiting_send -> running` (Send, answers being applied, or a
decision's or the timing's write), `running -> awaiting_send` (answers applied; Send's adapter not
built, Send failed before any request, or its first request failed before a model round
completed; the write returned), `awaiting_send -> failed` (any state can fail). Everything in
flight on a waiting review - applying answers, building Send's adapter and its first turn, and the
write of a decision or of the timing inputs (R2.7, R2.12, *second review, 2026-10-09*) - is the
existing `running` state, so the existing
`_require_idle` refuses a second action with `TurnRunning` and the host's `AnyTurnRunning` refuses
a Settings save, unchanged. `_play` settles `awaiting_send` when the run still waits, else as
today. Which of "running" and "waiting" the page shows is read from the summary: its `send` block
is present exactly while the run waits for Send, answers being applied included (R2.13), and
absent once Send is pressed. An apply that fails moves the chat `running -> failed` through
`_play`'s existing path, with the folder's record left as it was (R2.13, *revised 2026-10-09*).
(`contracts/review-flow.md` section 2, data-model section 2.)

**Default taken 2026-10-08, the owner may revise.**

**Why**: VERIFIED `TRANSITIONS` (`chat/sessions.py:79-90`): `extracting` goes only to `running` or
`failed`, and there is no paused state. VERIFIED `_play` settles `waiting_engineer` or `ended`
(`chat/server.py:2186-2208`, line 2199), `_require_idle` refuses only `failed` and `running`
(`chat/server.py:2167-2172`), and the host counts a turn as running only on `state == "running"`
(`BackendClient.cs:118-122`). So with one state: a waiting review is idle (decisions, timing and
Settings saves are accepted, FR-024, FR-027), and the three kinds of in-flight work FR-027 lists
(answers applied, a Send in flight, a re-run) are refused as a turn is - the first two by state,
the third because the re-run runs inside `POST /sessions` while the host's pump waits for it
(R2.17). A page reloaded while answers are applied reads `chat_state: "running"` with a `send`
block and shows the review waiting, never running (FR-033); a page reloaded during Send's first
turn reads no `send` block and shows it running, which it is.

**Alternatives**: a second new state for "applying" (the task asks for one; and every existing
refusal would need it added by hand); keeping the chat in `awaiting_send` with a separate busy flag
(the host would have to read a second field to refuse a save, and `_require_idle` a third case);
`ended` with a flag (the page and the host already treat `ended` as "may take a follow-up", which
FR-019 forbids).

### R2.5 No provider is set up until Send: `DeferredProvider`

**Decision**: a review started with the box unticked is set up with `DeferredProvider`
(`agent/providers/deferred.py`, new): it carries `name`, `model` and the adapter's own effort rule,
accepts `start_steps_at`, and raises `ProviderNotSent` from `run` and `for_presentation`. It needs
no key and constructs no SDK client. The three setup hooks of `start_review` (model view, lever 3's
cache key, lever 14) move into one `configure_provider(provider, session)` that `start_review`
calls where it calls them today and `ReviewRun.attach_provider` calls at Send, with
`start_steps_at(len(session.steps))`. Each adapter's effort rule becomes a module function
(`effort_mapping_for(model, effort)`) that its method and `DeferredProvider` both call, so an effort
the model does not offer still fails at setup exactly as today. (`contracts/review-flow.md`
section 8.)

**Default taken 2026-10-08, the owner may revise.**

**Why**: VERIFIED that `_start_review` builds the adapter before anything else, and any failure -
no key included - is `ProviderFailed` 502 before a check runs (`chat/server.py:2111-2114`); that
the OpenAI adapter raises without a key (`agent/providers/openai_provider.py:282-283`). VERIFIED
that `start_review` needs the provider at setup only for `model` (`runner.py:1580`), the effort
mapping (`:1581`), `name` (`:1614`, `:1660`), the three opt-in hooks (`:1622-1646`) and
`start_steps_at` (`:1723`); `_restate` calls `start_steps_at` too (`:1262`), and `finalize` calls the
provider only when an explanation is allowed (`:1333-1349`), which no checks-only review reaches
(R2.15). VERIFIED the effort rules are pure over the model id and module tables
(`openai_provider.py:389-407`, `gemini_provider.py:382-406`, `fake.py:254-256`). With the box
ticked, nothing changes: the server still calls `provider_factory` first, so a review with no key
fails before any check as today (FR-035, the spec's question 3).

**Alternatives**: building the real adapter whenever a key exists (FR-007: no client until Send);
making the adapters tolerate a missing key until `run` (changes the ticked failure, which FR-035
keeps); splitting `start_review` into a checks half and a model half (moves every line of setup for
a seam two hooks give).

### R2.6 A checks-only review ends with a finalization and no turn

**Decision**: with the box unticked, `create_session` does what it does today up to
`_start_review`, then - instead of moving the chat to `running` and submitting `run.start` -
builds the run's Send cache (the opening and its estimate, R2.9), finalizes the run, and renders
the report and the attention record, all on the thread pool **before the chat is attached and
registered** (*revised 2026-10-09*), and only then attaches and registers it, moves it `extracting
-> awaiting_send`, and answers 201. The render is today's `_render_report` body extracted as
`ChatServer._render_run(run, report_path, run_dir)`, which `_render_report(chat)` now calls and the
unticked start calls with the chat's own paths before the chat is attached (*second review,
2026-10-09*): `_render_report` returns at once while `chat.run` is `None`, so calling it there would
write no `report.md` before the 201. A cache build or finalization that raises moves the
unregistered chat `extracting -> failed` and answers the error body any unexpected failure of
`POST /sessions` answers today, so no chat is left holding the folder and a shutdown can never
finalize the same run while this call does; the render, as `_play`'s, logs a failure and never
raises. The finalization writes no `turn.ended`; `session.ended` is written, as by every
finalization. The host makes this call with the long timeout a re-run's call has (R2.17,
*second review, 2026-10-09*).
Finalization of a session whose model status is not `sent` words each open model-owned checklist
item "{title}: not reviewed, because the review was not sent to the model" (FR-009); an item left
open after its blocking question was answered keeps feature 013's sentence and adds "; the review
was not sent to the model". Running time is the checks' time, plus the time from Send to the end
once sent; the wait is not counted (FR-011). (`contracts/review-flow.md` section 1,
`contracts/records.md` sections 2 and 3.)

**Default taken 2026-10-08, the owner may revise** (the wording and the running-time rule).

**Why**: VERIFIED `create_session` (`chat/server.py:1230-1262`): the 201 is returned after
`_start_review` and after `_submit(chat, run.start)` (lines 1253-1254), so the checks already run
before the reply and only the submit has to go. VERIFIED that `finalize()` with no turn writes no
`turn.ended` because `_pending_turn_end` is `None` (`runner.py:1363-1366`), makes no explanation
call because `_explanation_allowed` is false until a turn ends `end` (`:1333`, `:1449`), and writes
the close-out row, one unresolved row per open request and one per open checklist item
(`finalize_session`, `runner.py:597-678`, the items at `647-665`). VERIFIED that the running time is
`ended - started` (`runner.py:673-677`), which would count the wait. VERIFIED that a graceful
shutdown skips a session with an `ended_at` (`_finalize_on_exit`, `chat/server.py:2327-2334`;
`_already_ended`, `2337-2345`) and that `POST /stop` on a chat that is not running finalizes only
when it has no `ended_at` (`chat/server.py:1494-1501`): a waiting review is finalized, so a stop or
a shutdown writes nothing for it (FR-010, FR-025) with no change to either path - only tests.
VERIFIED (2026-10-09) that today's `create_session` attaches and registers the chat before it
submits (`chat/server.py:1251-1252`), that a chat holds its folder until it is `ended` or `failed`
(`_claim_run_dir`, `2048-2055`; `ChatSession.finished`, `chat/sessions.py:239-241`), and that a
shutdown finalizes every registered chat with no `ended_at` (`_finalize_on_exit`, `2327-2334`): a
chat registered while still `extracting` whose finalization then raised would hold its folder with
no way to `failed`, and a shutdown in that window would finalize the run on a second thread.
VERIFIED (second review, 2026-10-09) that `_render_report` begins `run = chat.run; if run is None:
return` and catches every exception of the ranking and the two writes (`chat/server.py:2259-2281`).
The unticked path also puts a cache build, a finalization and a render inside the `POST /sessions`
call, before its 201, which the host makes today with a 30 s timeout (RK-10).

**Alternatives**: a new "checks only" finalization (a second close-out rule); leaving the session
unfinalized until Send (a crash would lose the checks, which FR-008 forbids).

### R2.7 Send is one route, refused in a fixed order

**Decision**: `POST /sessions/{chat_id}/send`, empty body, `202` with the chat's public view.
Checked in this order, and a refusal changes nothing: `404 UnknownChat`; `409 SessionFailed`;
`409 TurnRunning` (answers being applied, or a Send already in flight - FR-018); `409 NotWaiting`
(the review is not waiting: it was sent, or it started ticked); `409 NoCredential` (the settings in
effect hold no usable credential: no key, and for Gemini no enterprise project; never for the
scripted provider); `502` with the provider's class when building the adapter fails. The adapter is
built with `await run_in_threadpool(self.provider_factory, settings)`, off the event loop, as
`_start_review` builds it today inside the thread pool (`chat/server.py:2111-2114`): the factory
constructs the SDK client, whose first import can be cold (*second review, 2026-10-09*). Because
that build is an `await`, the chat moves `awaiting_send -> running` first, on the loop right after
the checks, so nothing can pass the checks beside it - a second Send included - while the adapter
is built; a build that fails moves it back before the `502`. Then the worker runs
`ReviewRun.send(adapter)`. The settings used are the chat's
provider, model and effort with the backend's environment - which are the settings in effect,
because changing any of them is a Settings save and a save restarts the backend (FR-016).
(`contracts/review-flow.md` section 3.)

**Default taken 2026-10-08, the owner may revise** (`NoCredential` and its wording).

**Why**: VERIFIED that the chat keeps `provider`, `model` and `effort` (`chat/sessions.py:200-205`),
that `_settings(body)` resolves them with the environment (`chat/server.py:1996-2010`) and is the
one resolver to reuse, and that a Settings save always restarts (`ReviewHost.cs:916`), so a live
waiting chat's settings are the ones in effect. VERIFIED `ProviderSettings` already knows the
three facts the credential rule needs - `api_key`, `provider`, `enterprise`
(`agent/settings.py:194-215`); a `has_credential` property on it is the one place the rule lives.
A new route rather than `POST /messages`: VERIFIED `continue_session` sends only the engineer's text
(`runner.py:1123-1129`), so the brief and the digest would never reach the model; and the answer
routes end in `_ask` (`runner.py:1199`).

**Alternatives**: Send as a host message (the host's pump can be held for minutes by another
review's extraction; the page reaches every live route through the proxy already,
`BackendProxyHandler.cs` forwards any path but `/events`); Send carrying provider settings (the
page would choose a provider the backend was not started with).

### R2.8 The model's opening at Send

**Decision**: when nothing was applied while the review waited, Send sends the opening frozen at
setup, byte for byte (SC-004). When answers were applied, the opening is rebuilt by the one builder
(`_opening_message`) from the run's current state: the brief with the current part roles, the
digest from the pre-run result with each restated tool's calls replaced by its restated calls (each
call's findings re-read from the standing findings that cite it) and the "NOT evaluated" families
recomputed with the current roles (`prerun.restated(...)`, new), then - after the digest and before
the opening instruction - the wait's lines: one `Drawing {file}: {outcome}` line per drawing file
read (feature 013's words, `runner.py:933`), then one line per answered question, "{ER id}
({question}) was answered before this review was sent: {answer}. The checks above were graded
again by code with this answer." No line names withdrawn findings and no line tells the model to
re-run or continue (FR-023). The ids the opening names are recorded (`opening_finding_ids`, from the
digest's own lines). (`contracts/review-flow.md` section 5, `contracts/words.md` section 3.)

**Built once, on the worker** (*second review, 2026-10-09*): the opening Send would send, its
estimate (R2.9) and its named ids are built by `ReviewRun.build_send_cache()` and kept on the run
as one `SendCache` value, replaced by one assignment. It is built at three points, each on a worker
thread and each inside a path whose failure is already defined: the unticked start and a re-run,
after `start_review` (and the carry) and before the finalization (a failure is the start's error
body, R2.6); and the waiting apply, after the regrade and before the apply's finalization (a failure
is an apply failure, R2.13). The attention and snapshot routes, which compute on the event loop and
never write, and `send` only read it. VERIFIED that both routes run inline on the loop
(`chat/server.py:1267-1318`, "inline rather than through the thread pool"); a rebuild there could
raise into every summary of the waiting review, and could read the session while the worker is
changing it. Before the finalization, because nothing the opening reads moves in it: VERIFIED that
the pane's opening is the package brief, `prerun.digest()` and `OPENING_MESSAGE`
(`_opening_message`, `runner.py:1784-1810`; lever 11's gate brief, which ranks, is off in the pane:
`pane_efficiency`, `agent/settings.py:502-521`), and that `finalize_session` changes coverage,
carry-over keys, timing and `ended_at`, never a finding (`runner.py:597-678`). A test pins that the
cache's opening equals the opening built again after the finalization, so the order cannot hide a
dependency.

**Default taken 2026-10-08, the owner may revise** (the answer line's words).

**Why**: VERIFIED that the opening is built once in `start_review` and kept as a string
(`runner.py:1768-1774`, `ReviewRun.opening_message`, `1032-1041`), and that `ReviewRun` keeps
neither the `PrerunResult` nor the standards gap (`runner.py:1008-1027`). VERIFIED the digest is
rendered from the pre-run's own calls (`PrerunResult.digest`, `prerun.py:541-559`, and
`findings` at `537-539`), so a finding a regrade withdrew would still be named, and a restated
check's new counts missed; and that the "NOT evaluated" block is the families computed at pre-run
time (`prerun.py:1106-1114`), whose bought-parts lines name the parts an answer has since decided.
VERIFIED the resumed message today adds "Checks first graded again after your answer: withdrew
..." (`REGRADED_LINE`, `runner.py:928`, used at `1192-1193`), which FR-023 forbids here because the
model never saw those findings. Keeping the frozen string when nothing changed makes SC-004 hold by
construction; a test pins that the builder reproduces it, so the two cannot drift.

**Alternatives**: always rebuilding (SC-004 would rest on a second rendering never drifting);
patching the frozen string (text surgery on a digest); sending today's resumed-turn message after
the opening (two user messages, and the "withdrew" line).

### R2.9 The size of the first request

**Decision**: the estimate is `count_tokens` over exactly the request's fixed text - the system
prompt, the tool list and the opening as Send would send them - rendered by one function,
`request_prefix(system, tools, opening)` in `agent/runner.py`, which the replay's `_prefix` becomes
a call of. It is counted on this machine with feature 008's one encoding, with no network, and again
whenever the opening changes - in the Send cache (R2.8), on the worker, never in a route. It is
`None` when the vocabulary is not on the machine (`TokenizerUnavailable`) and for a review restored
from its folder before its re-run; the sentence then says what Send does with no number. With a
Gemini provider the number is shown and called approximate. The pane sentence names no encoding; the
Send record and the `session.sent` event name it. (`contracts/estimate.md`.)

**Default taken 2026-10-08, the owner may revise** (literal count, not calibrated - the spec's
default; and the sentence words).

**Why**: VERIFIED `_prefix(run)` is `run.system + json.dumps(tools) + run.opening_message`
(`benchmark/replay.py:350-361`), the text feature 008 counted when it measured one recording at
19.5% above its billed first round (008 research R2.5); `count_tokens` (`tokens.py:156`) raises
`TokenizerUnavailable` without the cached vocabulary, and `result_size` is the precedent for turning
that into `None` (`tools/registry.py:646-657`). VERIFIED the 009 resume sentence's two forms
(`review_words_v1.yaml:93-95`, `ResumeWords.of`, `report/summary.py:279-284`). Moving `_prefix`
rather than copying it keeps the replay's prefix and the estimate one rendering (DRY).

**What proves the move** (*second review, 2026-10-09*): a characterization, not the replay's
totals. VERIFIED that no committed replay count depends on the prefix's own bytes:
`BIG_RECORDED_TOTAL` and `BIG_FOLLOW_UP_RECORDED` are sums of the fixtures' recorded usage
(`recorded_input = recorded_round.usage.input_tokens`, `benchmark/replay.py:1320`; `_totals`,
`:1595-1597`; the test's own docstring, `tests/unit/test_replay_fixtures.py:236-238`: "nothing but a
regeneration moves it"); the as-recorded input is `fixed + _results_tokens(...)` and never reads the
prefix (`:1352-1356`); and the requested pass reads only `count_tokens(second.prefix) -
count_tokens(first.prefix)` (`:922`), a difference any change both passes share cancels. So before
the move, a test commits the sha256 and the length of the first pass's `PlayedReview.prefix`
(`benchmark/replay.py:244`, filled from `_prefix(run)` at `:368`) for each of the three committed
replay fixtures under the pane defaults, and the commit that moves the function must reproduce all
three (R2.28, `contracts/estimate.md` section 7).

**Alternatives**: the provider's own count endpoint (network, and 59A's "counted on this machine");
calibrating by the measured 19.5% (a fitted number from one recording, which SC-006 checks
instead); the whole review's cost (unknowable before the model asks for anything).

### R2.10 A failed first request leaves the review waiting

**Decision** (*revised 2026-10-09*; the order and the guard *second review, 2026-10-09*):
`ReviewRun.send` runs in two halves and a guard.

- **Prepare** - nothing written, nothing emitted, nothing in the session changed: (1) keep a deep
  copy of the model status as it stands; configure the adapter (`configure_provider`,
  `start_steps_at`) without yet making it the run's provider; (2) read the opening, its estimate
  and its named ids from the Send cache (R2.8), built earlier on the worker; (3) build the
  `session.sent` body (`adapter.name`, the model, `adapter.effort_mapping(effort)`, the estimate);
  (4) compute the coverage lists without the previous finalization's rows (R2.27), pure.
- **Commit**: (5) the pre-write - the attempt goes into the model status as failed with the reason
  "the backend stopped before the model answered", and the session is saved as it stands, still
  the checks' finalized record, so a crash from here on leaves a whole record; (6) emit
  `session.sent`; (7) assign the withdrawn coverage lists and clear `_finalized`, make the adapter
  the run's provider, and mark the attempt in flight - assignments that cannot fail; (8) run the
  opening turn.
- **The guard** over steps 1 to 7: anything they raise puts the model status back from the copy
  and, only when step 5's save had completed, saves the session again, so the file says what it
  said before Send; leaves the `DeferredProvider` in place; keeps `awaiting_send`; holds the failure in
  memory (`_send_error`: its time, class and redacted message), which the Send block shows until the
  next Send; emits one `error` (`retryable: true`) and no `turn.ended` or `session.ended`; and
  returns normally, so `_play` settles `awaiting_send` and re-renders the unchanged session. No
  request was made, so nothing is recorded in the model status: "send failed" means a request was
  made (spec, Key Entities). When the undo save itself fails, the failure is logged and the chat
  still waits; the file then says what a crash right after step 5 leaves, and the next write (the
  next Send's pre-write, an apply's finalization) replaces it.

When the turn raises and no model round of this attempt completed, `_run_turn`'s failure branch -
before its own `turn.ended {error}` and finalization - returns the run to waiting: the history back
to empty (a second Send carries the opening once), the attempt's reason replaced by the provider's
redacted message, `awaiting_send` set again, and the run's provider a `DeferredProvider` of the same
settings again (*second review, 2026-10-09*), so a waiting run always holds the deferred provider,
whatever path led back to waiting, and the guard above has one provider to leave in place. The
exception still reaches `send`, which returns normally, so `_play` settles `awaiting_send`. Text
that streamed stays in the stream, and the `error` and `turn.ended {error}` events stay as the
failed attempt's record. When a round had completed, the failure is today's: the review ends with
the error card. In both failure paths the run sets `awaiting_send` and its failure **before** the
`error` event is written, so the page, which draws no error card for an `error` that arrives during
a Send before any `usage` event, ends the Send on that event and re-reads the summary, whose `send`
block already carries the failure line (`contracts/pane.md` section 3). (`contracts/review-flow.md`
section 6.)

**The window step 5 leaves.** A crash between the pre-write and the request leaves `send_failed`
although no request left the machine; the record cannot tell the two apart and errs on the side of
the model having been asked, the trade RK-7 takes. A raised exception in that window is not a crash,
and the guard undoes the pre-write.

**Default taken 2026-10-08, the owner may revise** (the guard's in-memory failure: second review,
2026-10-09).

**Why**: VERIFIED `_run_turn` reports, closes the turn and finalizes before re-raising
(`runner.py:1434-1442`), and that the history keeps the opening after a failure because
`self.messages` is replaced only on success (`:1401`, `:1447`). VERIFIED the ledger counts rounds
since the last turn boundary (`UsageLedger.current_round_count`, `agent/events.py:167-169`) and that
`emit_turn_failed` writes the `turn.ended` that adds a boundary, so the round count must be read
before it. VERIFIED the page draws an error card for every `error` event today
(`ReviewPage/app.js:551-555`). "A model round completed" is "a `usage` event arrived", the spec's
definition (FR-017) and the ledger's.

VERIFIED (second review, 2026-10-09) why the guard is needed: an exception from steps 1 to 7 leaves
`send` with no turn begun, so the session's `ended_at` is still set; `_play` calls `_close_out`,
which returns at once for a session with an `ended_at` (`chat/server.py:2186-2208`, `2219-2235`,
`_already_ended` at `2337`), so with no guard the chat would go `failed` with no event while the page,
which has marked a Send in flight, waits for one - and a record pre-written at step 5 would say a
request was made when none was.

**Alternatives**: catching in `send` after `_run_turn`'s finalization (two `session.ended` events
and a summary that reads "finished" for a moment); a new event for a failed send (the page already
reads the summary at `session.ended`); reloading the record from disk in the guard, as an apply
failure does (R2.13) - unneeded, because the prepare half changes nothing in the session and the
commit half changes only the model status before its last, infallible step; recording a failure
before any request in `model_status.failures` (it would say a request was made).

### R2.11 "Sent" is the first completed round

**Decision**: on the first `usage` event of a Send attempt (`_emit_turn_event`), the model status
becomes `sent` with `sent_at` (when Send was pressed), the estimate shown at Send, the opening's
named finding ids, and the pre-written failure entry dropped; the session is saved there and then,
so a crash later in the turn leaves a record that says it was sent. What is saved is the session as
it stands (*revised 2026-10-09*): the checks' finalization rows were withdrawn at Send (R2.10 step
7) and `_run_turn` cleared `ended_at`, so the file is a sent review whose turn has not ended - no
"not sent to the model" row beside a `sent` state, and no close-out row of a finalization that
the sent review has not had. `awaiting_send` turns false at Send, not at the first round, so the
summary's `send` block disappears while the model runs.

**Why**: VERIFIED `_emit_turn_event` sees every event of a turn (`runner.py:1460-1473`). The spec's
three states (Key Entities) need a moment at which "send failed" becomes "sent"; the first usage is
that moment by definition. VERIFIED (2026-10-09) that `_run_turn` clears `ended_at` when a turn
begins (`runner.py:1416`) and that `finalize` is the runner's only write of `session.json`
(`runner.py:1372`; every other `save_session` call is outside the runner or in
`record_disposition`/`record_timing_live`, which `_require_idle` refuses while a turn runs, and which
on a waiting chat now hold it `running` for their write, so no Send can begin beside one - R2.12,
*second review, 2026-10-09*): so this save is the one write in the middle of a turn, and saving the
last finalized record with only
its state changed - the other way to keep it whole - would put "not reviewed, because the review
was not sent to the model" beside "Sent to the model" in the file `GET /reviews` restores.

**Alternatives**: patching only `model_status` onto the saved checks-only record (the contradiction
above); saving nothing until the turn ends (a crash after a completed round would leave "the
backend stopped before the model answered", which is false once the model has answered).

### R2.12 Decisions, timing, Stop and shutdown on a waiting review

**Decision** (*revised on the second review, 2026-10-09*): Accept, Reject and Defer, and the
timing route, work on a waiting review through the existing routes (`_require_idle` accepts
`awaiting_send`), with one change: on a chat in `awaiting_send`, each route moves the chat
`awaiting_send -> running` on the event loop right after `_require_idle`, with no `await` between,
and back to `awaiting_send` in a `finally` once its thread-pool write returns or raises. A Send, an
answer or a Settings save that arrives during the write meets `running` and is refused
(`TurnRunning`), as during any work in flight (R2.4). A chat in any other state takes today's path
unchanged, so a ticked review's routes do not move (FR-035). Stop on a waiting review changes
nothing; a graceful shutdown writes nothing for it (R2.6). Each is pinned by a test, and one test
holds a decision's write in the thread pool, sends `POST /send` (409 `TurnRunning`) and
`POST /evidence` (409), releases it, and then sends successfully.

**Default taken 2026-10-09, the owner may revise** (the hold).

**Why**: VERIFIED `disposition` and `timing` refuse only through `_require_idle`
(`chat/server.py:1444-1468`, `1470-1483`) and write the live session (`record_disposition`,
`chat/sessions.py:328-371`, its save at `:357`; `record_timing_live`, its save at `:408`), through
`await run_in_threadpool(...)` without moving the chat out of its state. A `POST /send` accepted
during that await passes `_require_idle` and starts `send` on the chat's worker, so two threads
would save and change one session: Send's pre-write and withdrawal beside the decision's
`save_session`. The race exists today between a decision and an answer on an ended review, but
deciding and then pressing Send is this feature's expected flow. Holding `running` reuses the one
refusal every route already has; a run-level lock was weighed and not taken (below). The check and
the move run on the loop with no `await` between them, so no other route can interleave
(`_require_idle`, `chat/server.py:2167-2172`). During an apply the chat is `running`, and a stop
request only sets a flag the apply never reads (`StoppableTools` wraps `run.tools`,
`chat/server.py:2145`; the apply restates through the registry's own dispatch,
`runner.py:1242-1263`), cleared in `_play`'s `finally` (`chat/server.py:2201`). VERIFIED
(2026-10-09) that nothing in the pane calls the timing route (no `/timing` in `Review/ReviewPage/`
or the host): the four human inputs reach a waiting review through the API or the offline
`record_timing_at` (`benchmark/timing.py:90`), so the page gains no timing control, and a re-run
carries the four inputs whole (R2.17 step 4).

**Alternatives**: a run-level lock held by `record_disposition`, `record_timing_live` and Send's
commit half (a second mechanism beside the state every route already reads; and a decision that
took the lock after Send's commit would still write in the middle of the Send turn); running the
two writes on the chat's worker (a decision queued behind a Send would wait for the whole turn);
holding `running` for every chat (moves a ticked review's routes, which FR-035 keeps).

### R2.13 Answers while waiting: the same routes, no model call

**Decision**: `answer_evidence_batch` (both answer routes reach it) checks `awaiting_send` first. A
waiting run applies the answers exactly as today up to the resumed turn - validate, mark, the
confirmed drawing read, the part-roles regrade, `_restate`, the bought-parts rows - and then, in
place of `_ask`, records each drawing file's outcome on the session (`drawing_outcomes`), marks the
opening as changed, replaces the restated tools' calls in its pre-run result, builds the Send cache
(R2.8, *second review, 2026-10-09*), and finalizes. One
private `_apply_answers` holds the shared steps, so the resumed path and the waiting path cannot
drift (DRY). The summary's `resume_text` is "Applying your answers regrades the review by code.
Nothing is sent to the model." while the run waits, and the panel's button reads "Apply answers".
`POST /messages` on a waiting run is refused `409 NotSent`. (`contracts/review-flow.md` section 4.)

**An apply that fails** (*added 2026-10-09*): anything after validation that raises in the waiting
branch - the confirmed read, the regrade, `_restate`, the Send cache's build, the finalization's
writes - is caught by the branch, which (1) puts the record on disk back into the run
(`context.session = load_session(session_path)`), so the report and attention record `_play`
renders next are that record's; (2) emits one `error` event and no `turn.ended` or `session.ended`
(FR-010); (3) re-raises. `_play` moves the chat `running -> failed`, and `_close_out` writes nothing
because the record's `ended_at` is set. The page draws no error card for it: it restores the review
from its folder, as after a restart (FR-042), with the error's line in the Send block, and the next
answer, decision or Send re-runs it (R2.17), the failed chat no longer holding the folder.

What the restored review shows depends on where the failure came (*second review, 2026-10-09*):

- **before the finalization wrote `session.json`** (the read, the regrade, `_restate`, the cache):
  the record on disk is the one before the apply, so the answers being applied show open again;
- **after it** (the attention record's write, or the `session.ended` event): the record on disk is
  the applied one, so the answers show answered, and the re-run carries them (R2.17 step 4).

**A drawing merged before the failure.** A confirmed read merges the drawing it read into the run
folder's `package.json` before the regrade, and its outcome line reaches `session.json` only with
the finalization. When the apply fails between the two (or a crash or shutdown cuts it off there),
the folder's package holds the drawing and the record holds neither its answer nor its outcome line.
The re-run then checks that drawing in its place and does not ask its question again, so the outcome
line FR-021 sends to the model is lost. The re-run names the loss in its `coverage.recheck` row
("the outcome of the drawing read for {id}: the read that merged its drawing did not finish"), found
as an earlier **open** drawing-candidate question whose drawing is now in the folder's package,
which the re-run therefore does not ask, and whose file the earlier record's `drawing_outcomes` does
not name (R2.17 step 4). Persisting the outcome line before the regrade was weighed and not taken:
it would save a half-applied record, and when the regrade itself is what fails, every re-run would
carry the answer into the same failure and the review could never be re-run again.

**Default taken 2026-10-08, the owner may revise** (the apply-failure path: 2026-10-09; the two
sub-cases and the named loss: second review, 2026-10-09).

**Why**: VERIFIED the order and steps of `answer_evidence_batch` (`runner.py:1138-1202`): the marks
and events (`1159-1163`), the read (`1172-1176`), the regrade (`1180-1184`), `_restate` (`1185`),
the rows (`1187-1193`) and then `_ask` (`1199`). Feature 013's regrade is pure code and makes no
model call before `_ask` (013 `contracts/part-roles.md` section 9). VERIFIED (2026-10-09) the
failure path the apply would otherwise take: the waiting apply never enters `_run_turn`, so the
session's `ended_at` stays set; `_play` catches the exception and calls `_close_out`
(`chat/server.py:2186-2208`), which returns at once for a session with an `ended_at`
(`_already_ended`, `2219-2235`, `2337-2345`) and so writes no event - the page, which marked a turn
running for the apply, would wait forever; and `_play`'s `finally` re-renders `report.md` and
`attention.json` from the run's in-memory session (`_render_report`, `2259-2281`), which after a
half-done apply is neither the record before it nor after it. Clearing `ended_at` so `_close_out`
writes would add `turn.ended {error}`, which FR-010 forbids for a review not sent. VERIFIED (second
review, 2026-10-09) the finalization's order, which sets the two sub-cases: `finalize_session`,
then `save_session`, then `write_attention_record`, then the `session.ended` event
(`ReviewRun.finalize`, `runner.py:1367-1383`).

**Alternatives**: rolling the apply back and settling `awaiting_send` (the regrade rewrites findings
and coverage in place and a confirmed read has already merged its drawing into `package.json`, so
there is no whole "before" to roll back to short of the record on disk - which is what this path
uses, but on a chat that is then let go rather than trusted); leaving the chat live after a failure
(its in-memory state is the half-done apply).

**Alternatives**: a separate "apply" route (a second validator path beside 008's batch route,
which `contracts/answer-batch.md` section 1 made the one); queueing answers on the page until Send
(61A: answers given while it waits are regraded by code).

### R2.14 The explanation pass needs nothing new

**Decision**: no code change. It runs only after a turn that ended `end`, which only Send or a
ticked review produces. Three tests pin what FR-015 promises after Send (*added 2026-10-09*), since
the waiting branch of `_apply_answers` (R2.13) is where a regression would hide: after Send with a
turn ending `end`, exactly one presentation request follows; a follow-up after the first `usage`
is `202` and the page enables the follow-up box; and an answer to a question the model asked after
Send resumes the model through `_ask` with today's `ANSWER_MESSAGE` and `REGRADED_LINE`, byte for
byte against the same answer in a ticked review. Each comparison is read from the one recording
provider in `tests/support` (R2.28), which records every turn's and every presentation request's
input before it runs.

**Why**: VERIFIED (`runner.py:1333`, `1449`); a finalization with no turn never sets
`_explanation_allowed`.

### R2.15 The records say whether the review was sent

**Decision**: three optional session fields, each omitted at its default, written only for a review
started with the box unticked (a ticked review's `session.json` keeps every byte, FR-032):
`model_status` (state, the reviewed document, `checked_at`, the identity of the Standards profile
the checks graded with - `profile`, *second review, 2026-10-09*, R2.17 - `rechecked_from`,
`failures`, and once sent `sent_at`, `estimate`, `opening_finding_ids`), declared right after
`provider_info` so it sits
in the file's first kilobytes (R2.20); `live_detection`, the first run's live interference outcome
(R2.17); `drawing_outcomes`, the outcome line of each drawing read while the review waited. The
report's header prints "- Model: not sent to the model (checked by code only)" and no Provider
line for a review never sent; the failure for a failed send; and, for a review sent after waiting,
today's lines plus "- Sent to the model: {sent_at} (checks finished {checked_at})".
`session.started` carries `send_when_checked: false` for an unticked review, and a new event
`session.sent` marks each Send; the page's transcript words both. `save_session` writes atomically.
(`contracts/records.md`.)

**The times** (*added 2026-10-09*): `checked_at`, `sent_at` and each failure's `at` are stamped by
one new clock, `agent/events.local_now()` (`datetime.now(UTC).astimezone()`: the backend's wall
clock with its UTC offset), beside the existing `utc_now`. Every sentence that prints one -
`{when}` in the restored line, `{time}` in the failure line, the report header, the found chip's
date - prints the stored wall clock as it is and never converts it to the zone of the machine
rendering it. A record therefore renders the same on any machine, the engineer reads the local
time the checks ran, and a fixture generator pins the one clock (R2.25).

**Default taken 2026-10-08, the owner may revise** (field names, header words; the times:
2026-10-09).

**Why**: VERIFIED `ReviewSession`'s optional fields are dropped by its serializer at their defaults
(`report/session.py:582-608`) - the pattern followed. VERIFIED the header prints the model and the
provider unconditionally when `provider_info` is set (`report/markdown.py:146-180`) and that
`provider_info` is set at setup (`runner.py:1613-1618`): kept as the configured provider (the live
chat sends with it), so the report, not the field, says the review was not sent. VERIFIED the
transcript's first line is built from `session.started` (`app.js:634-641`), which is replayed for a
restored live chat (`app.js:570-602`), so the "checks only" fact must be on the event. VERIFIED
`save_session` writes the file in place (`report/session.py:650-655`); the re-run of R2.17 replaces
the canonical `session.json` once, at its end, and a crash during that write must not lose the
earlier record. VERIFIED the 014 worktree adds `swreview/atomic.py` with `write_atomic(path,
data)` (temporary in the target's folder, `os.replace`); 015 uses exactly that helper (R3).

**Alternatives**: clearing `provider_info` until Send (the session is the live chat's, which sends
with it; and the effort mapping would have nowhere to live); a fourth "sending" state on disk (the
pre-written failure says the same thing truthfully, R2.10).

### R2.16 Replay and the recording reader refuse a review that waited

**Decision**: `read_recording` refuses, before it reads the events, a session that carries
`model_status`: "{run} was never sent to the model, so it has no model turn to replay" when not
sent, and "{run} was sent to the model after waiting for Send; the replay reads only reviews sent
when their checks finished" otherwise (FR-040, the spec's default). A review sent at once is read as
today.

**Why**: VERIFIED `read_recording` already refuses a log with no usage event
(`benchmark/recording.py:163-167`), which a never-sent review would hit with a sentence about
pricing; and that a review sent after answers would otherwise read as an answer turn and a second
session start. The check reads `session.json` first, so an unknown event type is never reached.

### R2.17 The re-run after a restart

**Decision** (*revised 2026-10-09*): a review restored from its folder whose record says not sent
(or send failed) stays usable (the spec's question 4 default). Its first answer, decision or Send
sends the host message `review.recheck {chat_id}`; the host - refusing a drawing, another active
document (`ReviewNotActive`) and a stopped backend as `review.start` does - posts `POST /sessions`
for the review's own folder with `recheck: true` and `send_when_checked: false`, with the live
bridge as for any review, no dump, and an explicit 10-minute timeout (default) in place of the
client's 30 s - the timeout every call that runs the checks inside `POST /sessions` with
`send_when_checked: false` has, an unticked start included (`BackendClient.TimeoutFor`, *second
review, 2026-10-09*). The backend:

1. claims the folder. A live chat on it that waits for Send (`awaiting_send`) is **adopted**: the
   call answers 201 with that chat's id and the `carried` maps stored on it, and runs nothing - so
   a host that gave up on a re-run the backend then finished, and asks again, gets the finished
   one rather than `RunDirInUse` until a restart. Any other live chat is `409 RunDirInUse`, and so
   is a folder whose re-run is still running: since the chat is registered only after its
   finalization, the claim holds the folder itself until the call answers, so a host that gave up
   and asked again while the first re-run still ran never starts a second re-run in the same folder.
   With no live chat it reads `session.json` - the earlier record; none, unreadable, or not a
   waiting review's is `404 UnknownReview` or `409 NotWaiting`;
2. rotates by what the canonical stream is. When `events.jsonl` is the earlier record's own (its
   `session.started` names `session.json`'s `session_id`), as a retry does, except that
   `session.json` and `attention.json` are **copied** to index N, not moved, while `events.jsonl`
   and `tool-results/` are moved. When it is a failed attempt's stream, or absent (what a failed or
   killed re-run leaves), the stray stream and results move to their own index with no session file
   beside them, and the earlier record is not copied again (the attempt that left them copied it).
   Until the re-run's own finalization replaces it atomically, the canonical `session.json` stays
   the earlier record, so a failed, refused or killed re-run leaves the earlier record restorable
   with no recovery step, and every index holds a session with the stream it wrote or a failed
   attempt's stream alone;
3. runs `start_review` with the earlier record: the pre-run carries the first run's live outcome
   (no bridge call; the digest line, the coverage row, the withheld tools and the guard's answer
   are the first run's; rows that were never written are one unresolved line) and records **one
   carried step** where the first run recorded its live call, so every later step index, the
   guard's `ran_at_step` and `tool-results/step-N.json` mean what they meant in the first run;
   when the first run could not write its detected rows (`persist_error`), the re-run removes the
   reviewed configuration's rows from the in-memory package exactly as the first run did before its
   call, so it judges none of the stale rows the dump left in `package.json` for that configuration
   (*second review, 2026-10-09*); the context carries the first run's `drawing_read` and writes it
   on the session as `drawing_read_mode` does, so the host is not pinged and the re-run's record
   keeps the value for the next re-run (*second review, 2026-10-09*); the review is graded with the
   Standards profile the settings name now, as Send uses the provider in effect (FR-016), and when
   its identity differs from the earlier record's `model_status.profile` the change is named (step
   4; default, *second review, 2026-10-09*, R6 question 3);
4. carries, in memory only, the earlier answers, decisions, timing inputs and model status: each
   answered code question onto the re-run's question that asks the same thing (same question,
   options and entity ids - the rule the part-roles answer and the confirmed read already match
   by, extracted once as `checks/questions.asks_same`); the part-roles answer regraded by code; a
   drawing answer marked with no read and its outcome line carried, or - when its drawing is now in
   the package and its question not asked again - only its outcome line; each Accept, Reject or
   Defer onto the finding with the same `findings.finding_subject_key`; the four human timing
   inputs whole; the model status's state and failures whole, with `rechecked_from`; anything that
   matches nothing or more than one item named in one unresolved row, `coverage.recheck`, which also
   names a changed Standards profile and a drawing outcome an unfinished read lost (R2.13). The
   carry writes nothing to disk: it never calls `record_disposition`, `record_timing_live` or
   `save_session`;
5. builds the Send cache (R2.8), finalizes - the re-run's one write of `session.json`, through
   `write_atomic` - and renders, then registers the chat (R2.6's order), stores `carried` on it,
   answers 201 with `carried:
   {requests: {old: new}, findings: {old: new}}`, and holds the chat in `awaiting_send`.

The host replaces its record of the review with the new chat and replies `review.rechecked`; the
page re-keys its drafts and the pending action by `carried` - unless the answer names the record it
already shows (its `send.session_id`), which happens only when it adopted a re-run the page had
already reloaded - and does what was asked through the live route. (`contracts/recheck.md`.)

**Default taken 2026-10-08, the owner may revise** (the mechanism; 61A and FR-028 to FR-031 decide
the behaviour; the adoption, the carried step, the stray-stream rule, the decision key and the
timeout: 2026-10-09; the timeout's one rule, the stale rows, the carried capability on the record
and the profile in effect: second review, 2026-10-09).

**Why**: VERIFIED that a backend restart drops every chat (`chat/server.py:1189-1190`, in memory
only; `ReviewHost.cs:916`) and that no route rebuilds a `ReviewRun` from a folder; `GET /reviews`
is read-only (`chat/server.py:1660-1682`). VERIFIED that `POST /sessions` into a folder holding a
session is refused unless it is a retry (`_claim_run_dir`, `chat/server.py:2025-2060`), and that
the retry's rotation moves `events.jsonl`, `session.json`, `attention.json` and `tool-results/` to
one free index (`_rotate_previous`, `2062-2099`; `_next_free_index`, `542-555`): moving the session
first would leave a folder with no `session.json` if the re-run failed, which `GET /reviews` and
FR-041 cannot read. VERIFIED the pre-run's live call is the only bridge call before the first
request besides the drawing-capability ping (`_live_interference`, `prerun.py:1254-1320`;
`ToolContext.drawing_read_mode`, `tools/context.py:403-419`, cached per context in `_drawing_read`,
`:181`), that `bridge_interference` records no finding (`tools/bridge.py:397-468`), and that the
digest renders a successful live call from `LiveOutcome` alone and a failed one from the call's
label and error (`prerun.py:490-503`): a carried `PrerunCall` (tool, arguments, the first run's
step, no findings, its error) renders the same line. VERIFIED that the first run's merge writes the rows in the
order the first run judged them - the other configurations' rows, then the new ones, and the new gaps
after the old - and refuses to write unless the file equals the same merge done on the models
(`ir/loader.append_interference_run`, `ir/loader.py:136-173`; the in-memory order is
`prerun.py:1280-1305`): so the re-run's groups, calls and finding ids come out in the first run's
order, and its digest is the first run's, byte for byte, which SC-008 rests on. VERIFIED that a re-run numbers findings and
questions afresh, so numbers cannot carry (FR-029), and the two existing identity rules
(`part_roles.answered_roles`, `checks/part_roles.py:902-917`; `_is_confirmed_candidate`,
`tools/drawings.py:248-258`) compare question, options and entity ids - a third use makes the
extraction mandatory under Principle V.

VERIFIED (2026-10-09), for each revision:

- **The decision key.** `_verdict_key` (`runner.py:802-823`), the key restated findings are folded
  by, is the check, the component ids, the drawing places and the configuration, and ignores hole
  ids: two `hole.coaxiality` findings on one pair of components share it, so their decisions would
  always "match more than one" and never carry (`docs/review-backlog.md`, the `_verdict_key`
  entry). `findings.finding_subject_key` (`findings.py:234-263`) is the replay's key for findings
  "independent of how the run that made it was numbered": the check, the sorted component ids, the
  drawing places with their persistent references, the entity ids among the inputs, and the
  configuration. A re-run judges the same package, the one condition its docstring sets, so it is
  the key for carrying decisions; `_verdict_key` and its backlog entry are left as they are.
- **The carried step.** The live call is the pre-run's first call, recorded at the session's step
  count (`_live_interference`, `prerun.py:1254-1290`; `recorded_call`, `1201-1240`), and the guard
  answers a repeat with `ran_at_step: recorded.step_index` (`prerun.py:1505-1508`). A carried call
  that recorded no step would leave every later step one lower than the first run's, so the
  guard's `ran_at_step` and the re-run's `tool-results/step-N.json` would name another tool's step.
  `registry.record_call` (`tools/registry.py:606-641`) is the funnel that records a step without a
  dispatch, the one the guard's own repeat answer uses.
- **The adoption and the timeout.** The host makes every backend call, `CreateSession` included,
  with a 30 s timeout (`BackendClient.cs:39`, `299-300`). If it gives up on a re-run the backend
  finishes, the backend has registered a waiting chat that holds the folder (`_claim_run_dir`,
  `chat/server.py:2048-2055`), and without adoption every later answer, decision or Send on that
  review would be `RunDirInUse` until something restarted the backend.
- **The rotation.** `_next_free_index` documents one index per session pair (`chat/server.py:
  542-555`). After a failed re-run the canonical `events.jsonl` is the failed attempt's while
  `session.json` is still the earlier record, so rotating them as a pair would store a second copy
  of the earlier record beside the failed attempt's stream. `session.started` carries the session
  id (002 `chat-events.schema.json`, the `session.started` branch), so the first line tells which.
- **Nothing written before the finalization.** The live decision path writes `session.json`,
  `report.md` and `attention.json` at once (`record_disposition`, `chat/sessions.py:328-371`, the
  save at `357`; `record_timing_live`, `:408`): the DRY choice for the carry would have overwritten
  the earlier record part way, and a kill after it would restore a half-carried record.
- **The model status.** The usual way out of a failed send is a key saved in Settings, and a save
  restarts the backend (`ReviewHost.cs:916`): a re-run of a `send_failed` record is the common
  case, not a rare one, so writing `not_sent` there would erase the failure FR-032 requires the
  record to keep.

VERIFIED (second review, 2026-10-09):

- **Rows the first run could not write.** `_live_interference` removes the reviewed
  configuration's rows from the in-memory package before its call, because the host numbers rows
  from `int:0001` on every request (`prerun.py:1280-1281`, the docstring at `:1264-1272`), and
  writes the added rows to `package.json` only at the end (`_persist_rows`, `:1319`). With
  `persist_error` set, the folder's package still holds the dump's rows for that configuration,
  which the first run never judged; a carried re-run that left them in memory would judge them.
- **The drawing-read capability.** `drawing_read_mode` caches the answer on the context and also
  sets `session.drawing_read` (`tools/context.py:413-419`). A re-run's context and session are new
  (`build_context`), so a carry that set only the cache would leave the re-run's record without the
  value, and a second restart's re-run would ping the host, which SC-008's zero bridge calls forbid.
- **The Standards profile.** A re-run passes the settings in effect, the profile path included
  (`recheck.md` section 1), and the usual restart is a Settings save, which can change the profile.
  A loaded profile has an identity, `{path, sha256}` of its bytes (`ProfileIdentity`,
  `checks/standards/profile.py:183-188`; `StandardsProfile.identity`, `:606-614`; computed by
  `load_profile`, `:617-626`), and a review's `ReviewProfile` keeps the path it was given and the
  profile or its refusal (`:643-656`). The record keeps no profile content, so a re-run cannot grade
  against the first run's profile once the file changed; it can only tell that it changed.
- **The host's timeout.** Every backend call, `CreateSession` included, is made with
  `CallTimeout`, 30 s (`BackendClient.cs:39`, set at `:299-300`). An unticked start adds a cache
  build, a finalization and a render to the checks the call already runs; a re-run runs less (no
  extraction, no live detection). One rule for both: the long timeout whenever
  `send_when_checked` is false. A ticked start keeps 30 s (FR-035).

Feature 014 stamps every step code makes with an `origin_mark` and counts a step without one as the
model's (014 `report/session.py`, `StepMark`): after the merge, the carried step carries
`origin_mark: "prerun"`, the code that first made the call (R3).

**Alternatives**: rebuilding a `ReviewRun` from disk with no re-run (the digest's live outcome and
not-evaluated families are not persisted, and the guard needs every pre-run payload in memory -
map 2, section 5); re-extracting (61A: no re-extraction); refusing every action on a restored
review until Send (the spec's question 4 alternative, read-only); a carried call with no step,
whose repeat is answered "ran in the earlier check run" with no step index (simpler, but the
re-run's session and report would show no live-detection step and every later index would move);
keeping `_verdict_key` and naming the coaxiality limitation (it leaves a decision the engineer made
uncarried for a reason the key, not the design, creates); grading a re-run against the first
run's profile (the record holds its identity, not its content, and the file may have changed);
refusing a re-run whose profile changed (the engineer's next action on the review would fail for a
setting they meant to change, and a fresh Review would lose the answers and decisions 61A keeps).

### R2.18 A restored not-sent review is shown usable, with its age

**Decision**: `GET /reviews/{run_id}` answers a not-sent (or send-failed) record with
`read_only: false`, no `read_only_reason`, and the summary's `send` block in state `restored`: the
restored-review line ("The backend restarted, so this review is shown from its run folder. Its
checks ran {when}; its next answer, decision or Send checks the saved evidence again first."), the
size sentence without a number, the re-run failure sentence the page prints if a re-run fails, and
the record's `session_id` (every `send` block carries the session it describes, *added
2026-10-09*: the snapshot has no session key and gains none, R2.25, and the page needs it to tell
an adopted re-run of the record it shows from one of an earlier record, R2.17).
The page prints the restored line in the existing line under the status line (`#read-only`), and
routes every action through `review.recheck` first. A sent record restores read-only as today.
(`contracts/recheck.md` section 8, `contracts/pane.md` section 7.)

**Why**: VERIFIED `_read_review` passes the words file's read-only sentence for every folder
(`chat/server.py:1677-1682`) and the snapshot carries it (`report/snapshot.py:57-75`); the page
prints it under the status line (`app.js:1466-1470`, `index.html:162`). One line, one element.

### R2.19 A restart while a waiting review is on screen

**Decision**: after an `init` that names a different backend (a Settings save, or a restart after
`backend.stopped`), the page restores the review on screen from its folder at once when it was
waiting, through the same path a chip uses when the chat is gone (FR-042). Reviews that were not
waiting keep feature 009's rule (restored when chosen).

**Why**: VERIFIED the page re-asks `init` after a save (`app.js:2554-2561`) and holds the old chat
id; its next live call would be refused `UnknownChat`. `showReview`'s fallback to
`GET /reviews/{run_id}` is the restore path (`app.js:1378-1404`).

### R2.20 Finding a not-sent review after SOLIDWORKS reopens

**Decision**: `sessions.list` first looks, when the active document is a part or assembly this
host holds no review of, for that document's newest review in the run root: the folders whose
names carry the document's name (`RunFolders.DocumentName`, with the collision suffix, check,
standards and remodel folders skipped), newest by the name's timestamp; only the newest is read,
and only the head of its `session.json` (64 KiB, `Utf8JsonReader`, stopping at `model_status`).
It is tracked as a kept review - its chat id the record's `session_id`, its time `checked_at`, its
item carrying `model_status` - when that record says not sent or send failed **and** names this
document's full path and configuration. A newer folder with the same name that is not such a record
(a review sent at once, a failed check run, another document with the same file name) offers
nothing. The page asks `sessions.list` again on `document.changed`, after following with the list it
has. A chip of a review found this way names the date when it is not today. (`contracts/recheck.md`
section 9.)

**Default taken 2026-10-08, the owner may revise** (the spec's question 2 default, and "the newest
same-name folder decides").

**Why**: VERIFIED that kept reviews live for one SOLIDWORKS session (`ReviewHost.cs:372-393`),
that folder names are `<yyyyMMdd-HHmmss>-<document name>` with a `-N` collision suffix
(`RunFolders.cs:354-375`), that `NewestCheckFolder` already finds a tab's newest folder from names
alone (`RunFolders.cs:130-183`, `TimestampOf` `191-206`, `CarriesSuffix` `213-235`), and that a
bounded head read is the existing way to read a run folder off a hot path (`PackageIndex.HeadOf`,
`extractor/SwReview.Extractor/Dump/PackageIndex.cs:259-300`). VERIFIED that the design record holds
no root path (`ir/models.py:290-298`) and a package is tens of megabytes, so a review sent at once -
which records nothing new (FR-032) - cannot be told from another document of the same file name
without reading its package; the newest same-name folder therefore decides, which can hide a
waiting review but can never offer one behind a newer review of the same document. VERIFIED that the
host's message pump is off the SOLIDWORKS UI thread (`SwReviewAddIn.cs:1257-1289`), so the search
never delays opening the document. The date rule is limited to found reviews so feature 009's chips,
and their tests, are unchanged (`ReviewPageSessionsTests.cs:65`, fixed 2026-09-23 times).

**Alternatives**: the backend searches (it may not be running yet, and it does not own the folder
names); reading every same-name folder's package (the cost FR-030 forbids); a sidecar file per run
folder (a second record of one fact).

### R2.21 The page

**Decision** (`contracts/pane.md`):

- the box: `<label class="check send-when-checked">` with the owner's words, in `#session` under the
  buttons' `.row` (FR-001); never disabled. It is a line in `#session` in every state, the ticked
  default included, so it takes height from `#results` in every review - about 21 px (`.check`'s
  12 px face at line height 1.45 and its 4 px top margin) of the measured 226 px (below), so it
  fits with no fallback. The first page task still runs the two existing 300 by 600 tests with the
  real box in place, unedited (*second review, 2026-10-09*);
- the Send block: `<section id="send" class="send-panel">` **directly under `#summary` and above
  `#questions`** (*second review, 2026-10-09*, replacing "between `#read-only` and `#summary`"),
  shown only while the summary carries `send`: the "Send to model" button, the size sentence, and
  one failure or refusal line; built by `render.sendBlock` with `textContent` only. Under the
  summary, it reads in the order US2 tells it - the engineer reads what the code found, then
  decides to send - and only the box line and the restored-review line stand above the summary;
- an `error` event while a Send is in flight and before its first `usage` ends the Send on the page:
  no error card, the Transcript line written, and the summary re-read, whose `send` block carries
  the failure line - one rule for a failed first request and a Send that failed before any request
  (R2.10, *second review, 2026-10-09*);
- the status line gains "Checked by code. Not sent to the model." and "Checking the saved evidence
  again.", page words read from page state, ahead of "Waiting for your answers." (FR-033);
- the questions panel's button reads "Apply answers" while the review waits; its sentence is the
  summary's `resume_text`;
- the follow-up box is disabled while the review waits, its placeholder saying it has not been sent;
  Stop is disabled while the review waits or is being checked again;
- the transcript's first line for an unticked review says it ran the code checks only; each
  `session.sent` adds "Sent to {provider} {model} ...";
- the Settings section shows one line while a review waits; the no-key note becomes a sentence true
  for both box states;
- a chip carries " · not sent" while the page knows the review waits, and for a found review.

**Default taken 2026-10-08, the owner may revise** (every page word except the box's label and
"Send to model", which are 59A's; the Send block's place under the summary: second review,
2026-10-09).

**The budget, measured** (*second review, 2026-10-09*). On the committed build of `838b66b` (the
add-in test assembly the main checkout had built, copied to a scratch folder outside the
repository; its page files equal this branch's but for line endings), a rule appended to the copy's
`app.css` added a block of N px at the end of `#session`, and `ReviewPageSummaryAcceptanceTests` and
`ReviewPageNarrowLayoutTests` ran against `review-big-assembly.json` at 300 by 600:

| Added above the summary | Result |
|---|---|
| 0, 8, 16, 24, 32, 48, 100, 200, 210, 220, 222, 224 and 226 px | both classes pass |
| 228, 230, 240, 250 and 300 px | the not-reached line is below the fold |
| 350 px | the tally too |
| 400, 450, 500 and 600 px | the headline too |

So a finished big-assembly review has **about 226 px** of slack between the bottom of the
summary's not-reached line and the fold; the summary's top sits at about 178 px. The narrow-layout
tests passed at every height tried, up to 600 px, so they do not bound what stands above the summary.
The same rule, with the planned words as text in the page's 12 px face, stood in for each worst
case:

| Stacked above the summary (proxy) | Result |
|---|---|
| the box, then a Send block of the waiting state (button row, size sentence) | pass |
| the same with a send failure's line | pass |
| the box, the restored-review line, a Send block of the restored state | pass |
| the same with a failed re-run's line and its fold | **fails** (the summary's top at 440 px) |
| the box and the restored-review line only (the Send block under the summary) | pass |

A Send block above the summary therefore cannot hold SC-007 in its worst case, and the earlier
fallbacks (a tighter margin for the box; the sentence into the button's row) cannot recover the 40
px or so it lacks: a narrower sentence wraps to more lines. Under the summary, the block moves
nothing SC-007 reads, whatever its failure line holds, and its button stays on the first screen: the
not-reached line ends at about 374 px on the finished review, and with the box (21 px) and the
restored line (at most about 70 px) above the summary, at about 465 px, so the button under it sits
well inside the 600 px fold. The app.css comment that a third button row pushed the last
not-reached line below the fold (`app.css:120-125`) dates from feature 009 (its T032); feature 013
has since moved the goal lines under their groups (`index.html`, the summary's comment), and the
measurement supersedes the comment.

**What is left to measure.** The big-assembly waiting fixture (`review-waiting-big-assembly.json`)
exists only once US1's generator lands; its summary is not the finished one's (no model questions;
more goals not reached). The first page task after it lands runs `ReviewPageSendLayoutTests`
(research R4.2) on its `waiting`, `failed_send`, `restored` and failed-re-run states: the
headline, the tally and the not-reached line inside 300 by 600 (SC-007), and the Send to model
button inside the viewport too, and records the measured figure here. **The end state**: if SC-007
fails even with only the box and the restored line above the summary - the waiting summary would
have to be about 135 px taller than the finished one - the page work stops and the owner is asked
which gives way while a review waits: the restored line's length (FR-031's content) or SC-007's
not-reached line.

**Why**: VERIFIED the session section and its two-row budget (`index.html:121-130`,
`app.css:111-130`: at 300 px the six buttons take exactly two rows), the `.check` class
(`app.css:232-241`, the only checkbox, `index.html:77`), the CSP (`index.html:5`), the status line
and its four states (`app.js:1029-1048`; 009 `contracts/views.md` section 3), the questions panel's
button and resume sentence (`render.js:682-685`), the follow-up and Stop enabling
(`app.js:1695-1704`, `1864-1872`), and the key note (`app.js:2484-2492`). The 300 by 600 checks are
`ReviewPageSummaryAcceptanceTests.cs: 91-109` (the headline, the tally and the not-reached line) and
`ReviewPageNarrowLayoutTests.cs` (an 80 px floor for the first finding's details and the follow-up
box inside the viewport, `:37-53`). VERIFIED (2026-10-09) that `.check` has `margin-top: 4px`
(`app.css:232-237`) and `.session .row` a 10 px bottom padding (`app.css:116-119`), and (second
review) that `--text-small` is 12 px and `--line` 1.45 (`web/shared/tokens.css:51`, `:55`): the box
line is about 21 px, which the measured slack holds with room; no rule is trimmed for it.

### R2.22 Where the words live

**Decision**: every sentence the Send block, the summary and the questions panel print comes from
the words file (`review_words_v1.yaml`, a new `send:` block and five `labels.errors` keys); the
status-line states, button labels, placeholder, transcript lines, chip mark and Settings lines are
page words (as today's status line and "Send answers" are); the lines the model reads are runner
constants beside today's; the report's lines are `report/markdown.py` constants. Every one is listed
once in `contracts/words.md`.

**Why**: FR-034; VERIFIED `Words` refuses unknown and missing keys (`report/summary.py:300-348`),
and `GET /labels` serves `labels` verbatim (`chat/server.py:1204-1212`).

### R2.23 The command-line review stays as it is

**Decision**: no flag, no change (FR-037). `start_review` and `run_review` keep `send_when_checked`
defaulting to true.

**Why**: the owner asked for the pane; the backend's own tests drive the checks-only path through
the chat server (`reviewer/tests/unit/test_chat_server.py` already starts sessions with a
`TestClient`).

### R2.24 The handoff export says whether the review was sent (added by this plan)

**Decision**: the handoff bundle's session summary gains `model_status` (the state only) when the
session carries one; nothing else in the export moves. 002 `contracts/handoff-export.md` is amended.

**Default taken 2026-10-08, the owner may revise** (R6, question 2).

**Why**: VERIFIED the export copies `provider_info` (provider, model, effort, key source) into its
summary (`handoff.py:391-401`); for a never-sent review that names a provider as if it had run,
which FR-032 forbids of the saved review. FR-038 lets the plan add a contract it finds.

### R2.25 Fixtures

**Decision** (*revised 2026-10-09*): the pane fixture (`review-big-assembly.json`) keeps its
snapshot part byte for byte; its labels block gains the five error keys only (FR-035). Every fixture
that carries the labels block is regenerated **in the commit that changes the words file** - the
pane fixture, and the waiting fixtures once they exist - because `test_pane_fixture.py` asserts
`fixture["labels"] == load_words().labels` (`:73`) and that the committed file is a fresh generation
(`:49`), so a words commit without its regeneration fails the gate, and every commit passes the gate
(quickstart). That commit's review checks that each fixture's diff is added label keys only
(*second review, 2026-10-09*, replacing "a commit of its own"). Three new page fixtures, each a set
of named snapshots plus the words file's labels block, written by one generator,
`tests/fixtures/pane/generate_waiting_fixtures.py`, with the box unticked and no provider set up
before a Send:

- `review-waiting.json`, from a **fictional questions package** built by code, whose checks raise
  the part-roles question and a drawing-candidate question - the shapes of 013's
  `tests/support/roles_review.py` (a convention-only profile and an unclear part) and 011's
  `tests/fixtures/pane/generate_drawing_questions.py` (a part with a same-name drawing not open),
  built by one helper, `tests/support/questions_package.py`, which the characterization of R2.28
  uses first (DRY):
  `waiting` (the live snapshot, its size sentence counted) and `failed_send` (the live snapshot
  after a Send whose scripted first request failed, with its failure line);
- `review-waiting-restored.json`, from the same package: `restored` (the run-folder snapshot of
  the record with nothing answered); `restored_answered` (the run-folder snapshot of the record
  after the part-roles answer, a confirmed drawing read whose merge into the folder's package the
  generator plays as the host would, and a Reject, all made while it waited, so a re-run numbers
  its findings and questions differently); and `rechecked` (the re-run's `POST /sessions` answer
  with its `carried` maps, and the re-run's live snapshot), so the page's re-keying has real moves
  to re-key;
- `review-waiting-big-assembly.json`, from the fictional big-assembly package, for the layout tests
  only (the worst case for height): `waiting`, `failed_send` and `restored`.

Every clock the generator's reviews read is pinned to a fixed fictional time - the runner's
`datetime` and `utc_now` the way `tests/unit/test_finding_explanations.py:366` pins them, and the
one new `local_now` (R2.15) - so a fresh generation is byte-identical on any machine, in any zone,
on any day. `tests/unit/test_pane_waiting_fixtures.py` fails when a committed file differs from a
fresh generation (the precedent `test_pane_drawing_fixture.py`), and the three files join
`test_replay_fixture_hygiene.py`'s list of committed fixtures, as `review-big-assembly.json` is
(FR-039). Every replay fixture is untouched: no change here moves what a review sent at once tells
the model, which R2.28's characterization and its regeneration step hold the code to.

**Why**: VERIFIED the pane fixture is `review_snapshot` of the big-assembly replay fixture plus the
words file's labels (`tests/fixtures/pane/generate_pane_fixture.py`), and that the summary block and
snapshot keys are serialized whole: so `send` must be omitted when absent, and no snapshot key may
be added. Page tests read backend-made fixtures, never hand-built shapes (feature 009 research
R2.24). VERIFIED (2026-10-09) that the big-assembly package raises no code question: the four
questions in `review-big-assembly.json` are all `source: "model"`, and a checks-only review of the
package raises none (the plan's review ran `start_review` with the pane defaults: 104 findings,
`evidence_requests == []`), so a waiting fixture built from it alone would leave "Apply answers",
the status line's precedence over "Waiting for your answers." (FR-033) and the re-keying of
`review.recheck` with nothing to test. VERIFIED that the restored line's `{when}` is `checked_at`,
the first finalization's end - "now" at generation - so it must come from a pinned clock and
render with no reference to the generating machine's zone (R2.15).

### R2.26 Other tabs and paths are untouched

**Decision**: Model check, Standards, Remodel, the Ask tab and the Settings model list are not
governed by the box and do not change (spec, Edge Cases, last item). Nothing in this feature adds a
tool, a bridge command, or a write to any document.

### R2.27 The Send turn starts from the coverage a ticked review starts from (added 2026-10-09)

**Decision**: `ReviewRun.send`, after it saves the attempt and emits `session.sent` and before
`_say` (the list computed in its prepare half, assigned in its commit half: R2.10, *second review,
2026-10-09*), withdraws the rows the run's previous finalization appended - the close-out row, one
unresolved row per open question, and one per open checklist item (with the box unticked, the "not
reviewed, because the review was not sent to the model" rows) - by identity, from the run's own
`_finalized` list, and clears the list, exactly as `finalize_session` does at its start. In memory
only: the file stays the finalized record until the first `usage` (R2.11). It applies on every Send:
the first, a Send after a failed one (whose failure was finalized again), a Send after answers
applied while waiting, and a Send after a re-run (whose finalization is the re-run's). Rows anything
else wrote - a part-roles row, the re-run's `coverage.recheck` row, a carried `failed` row - stay,
as they would after any code step.

**Why**: VERIFIED `finalize_session` (`runner.py:597-678`) appends those rows and withdraws a
previous finalization's only when it next runs (`written`, `:619-627`); `Checklist.bucket_of`
counts any coverage entry for an item, `unresolved` included, as placing it (`agent/checklist.py:
68-76`), so every model tool answer that carries `open_items` (`with_open_items`,
`tools/session.py:202-211`, used at `:126`, `:433`, `:450`) would tell the model during the whole
Send turn that no model-owned item is open, `get_review_checklist` would show every item
unresolved, and `closed_by_code` would answer from the close-out row. A ticked review's first turn
follows no finalization and sees none of it, so without this the Send turn would not be "what the
model would have been told had the review been sent at once" (US2, FR-015), and SC-004's first
request could match while the second already differed. Today's resumed turn after answers on an
ended review does see the previous finalization's rows; that is today's behaviour and is left as
it is - the comparison here is with a review sent at once.

**Alternatives**: withdrawing the rows inside the first finalization of an unticked review (a crash
during the wait would then leave a record with no close-out, which FR-008 forbids); leaving them
(the model may stop early, reading every item as placed).

### R2.28 A ticked review pinned to today's before anything moves (added on the second review, 2026-10-09)

**Decision**: three pins, each landing before the product change it guards, so FR-035 and SC-003 ("a
ticked review is today's, byte for byte") are measured against the code as it was before this
feature and never only against the feature's own code:

1. **The characterization golden**, `tests/unit/test_ticked_review_golden.py`, its golden files
   under `tests/unit/test_ticked_review_golden/` through `pytest-regressions` (already a development
   dependency, `pyproject.toml:36`). It is the first test task of the Foundational phase, written
   and committed on the pre-feature code - this branch's product code is `838b66b`'s until the first
   refactor - before any refactor. It drives a ticked `POST /sessions` (no `send_when_checked` in the
   body) through the chat server's `TestClient` app (`test_chat_server.py`'s fixtures), with the
   recording provider below scripted, on the fictional questions package (R2.25), and plays: the
   opening turn; one answer to the part-roles question that resumes the model (the path
   `_apply_answers` will hold, with `REGRADED_LINE`); one follow-up; and the explanation pass after
   each turn that ends `end`. The golden holds every provider `run()` input (the system prompt, the
   encoded tools, the encoded messages) and every presentation request's input, in order;
   `events.jsonl`; and `session.json`, `report.md` and `attention.json` - with times, durations and
   UUIDs replaced by placeholders in order of first appearance. Every later commit keeps it
   byte-equal; it runs in the gate.
2. **The prefix characterization**, `tests/unit/test_request_prefix_characterization.py` (a
   `data_regression`): for each of the three committed replay fixtures, under the pane defaults, the
   sha256 and the length of the first pass's `PlayedReview.prefix`. Committed before `_prefix`
   moves; the commit that moves it into `request_prefix` must reproduce all three (R2.9).
3. **The replay regeneration step**, on a machine that holds the owner's recordings mapping
   (`%LOCALAPPDATA%\SwReview\recordings.json`, read by `tests/support/recordings.py`): 008
   `contracts/replay.md` section 8's three generator commands, then `git diff --exit-code --
   reviewer/tests/fixtures/replay`. Where the mapping is absent the step is skipped, naming why. It
   runs at the gate of every phase that changes the runner, the pre-run, a provider or the records,
   and at the final gate.

**One recording provider.** `RecordingProvider` moves from `tests/unit/test_prefix_stability.py`
(`:113-156`; it records before the turn runs, so a turn that raises still contributed its input,
and it encodes the tools and the history as the OpenAI adapter does) to
`tests/support/recording_provider.py`, gaining `for_presentation`, which records the presentation
request the same way; `test_prefix_stability.py` imports it, its assertions unchanged. The
characterization, SC-004's and SC-008's every-request comparisons, R2.14's three pins and the
waiting-fixture generator all use it, and 015 adds no other.

**Why**: before this entry every comparison the plan made ran new code against new code - an
unticked review that was sent against a ticked one, both on the 015 code (SC-004, R2.14) - while the
plan refactors the ticked path itself: `configure_provider`, the `effort_mapping_for` delegations,
`_apply_answers` (which the sent answer resume uses), `asks_same` inside `answered_roles` and
`_is_confirmed_candidate`, `request_prefix`, `save_session` through `write_atomic`,
`finalize_session` reading `model_status`, `_play`'s settle, `create_session`'s branch and
`_render_run`. A drift in any of them would have passed every planned test. VERIFIED: the pane
fixture test re-renders the stored big-assembly session through `review_snapshot` and runs no
review (`tests/fixtures/pane/generate_pane_fixture.py`); the replay fixtures are written only by
`tests/fixtures/replay/generate_fixtures.py` from recordings held outside the repository (its
docstring) and no test compares them with a fresh generation; `test_replay_fixtures.py` holds each
round to within 1% and pins totals that only a regeneration moves (`:230-240`); `tests/golden`
holds check output, and no golden of a review's requests, events, session or report exists. The
house precedent is feature 009's T005, a characterization captured before a refactor
(`specs/009-engineer-workspace/tasks.md:52`). VERIFIED the copies a ninth recorder would join:
`test_cli.RecordingProvider` (`:109`), `test_gate_standards_in_review.RecordingProvider` (`:385`),
`test_tool_tiers.RecordingFake` (`:271`) and three `SpyProvider`s (`test_runner_provider.py:644`,
`test_withheld_prerun_tools.py:93`, `test_withheld_wording.py:170`); they stay as they are (not this
feature's to move).

**With feature 014.** 014 changes what a ticked review writes (an `origin_mark` on every step, and
its regenerated replay fixtures), so whichever branch merges second regenerates the
characterization golden on the first-merged side alone - `main` after the first merge, without the
second branch's code - commits that in the merge, and the merged code must pass it unchanged; and,
on the machine with the recordings, runs the regeneration step against the other branch's
fixtures (R3).

**Alternatives**: comparing an unticked review that was sent with a ticked one on the new code only
(both can drift together); pinning the first request alone (the resumed answer, the follow-up and
the explanation pass run through code this plan refactors); a characterization on the
big-assembly replay fixture (it raises no code question, so the answer path would go unpinned).

---

## R3. Merge note with feature 014

Branch `014-design-review-eval` (worktree `smart_SW-014`, at `907a621` on 2026-10-08, `4345cf1`
and then `45b5076` on 2026-10-09, not merged) changes files this feature also changes. VERIFIED by
`git diff --name-only 838b66b <head>` at each head, intersected with every file this plan changes,
adds or relies on by name (*revised 2026-10-09*: the first pass missed `prerun.py`,
`agent/settings.py`, `ir/loader.py`, `tokens.py` and `test_handoff.py`; *second review,
2026-10-09*: the second missed the 001 contracts README, `test_atomic.py`, the six replay fixture
files, `tools/session.py`, `agent/checklist.py`, `report/attention_record.py` and
`tests/support/mechanical.py`, and the characterization golden is new):

| File | 014 changes | 015 changes | Who reconciles |
|---|---|---|---|
| `reviewer/src/swreview/agent/runner.py` | `SYSTEM_PROMPT_FILE` imported from `agent/checklist.py`; `session.origin_marks` set in `start_review`; `_restate` passes `mark="regrade"` | `start_review(send_when_checked=, earlier=)`, `configure_provider`, `ReviewRun.send`/`attach_provider`/`_apply_answers`/`carry_from`, the `_run_turn` failure hook, finalization's not-sent reasons, `request_prefix` | the branch that merges second; textual, no semantic overlap |
| `reviewer/src/swreview/chat/server.py` | `explain_findings=defaults.explain_findings` at the `start_review` call (`:2138`) | `_start_review` takes the deferred provider and the earlier record; `create_session`'s unticked path; the send route; the recheck claim and rotation | second; keep 014's `defaults.explain_findings` |
| `reviewer/src/swreview/chat/sessions.py` | `replay_events` moved to `agent/events.py` | `ChatState.AWAITING_SEND` and `TRANSITIONS` | second; textual |
| `reviewer/src/swreview/prerun.py` | `recorded_call` gains a required keyword `mark: StepMark` (`"prerun"`, `"regrade"`) and stamps `origin_mark` on every step it appends; `_prerun_call` passes `"prerun"` | `prerun_checks(carried_live=)`; the carried live step (recorded through `registry.record_call`, not `recorded_call`); `restated()`, `named_finding_ids()`, `LiveOutcome.as_record`/`from_record`, `INTERFERENCE_ROWS_NOT_CARRIED` | second. Every 015 call of `recorded_call` passes `mark` (the re-run's pre-run goes through `_prerun_call`, so `"prerun"`; the carry's regrade through `_restate`, so `"regrade"`). The carried live step is a step code made, so it carries `origin_mark: "prerun"` - the code that first made the call - stamped as `recorded_call` stamps (a step with no mark is counted as the model's, 014 `StepMark`); `test_recheck.py` gains that assertion in the merge commit |
| `reviewer/src/swreview/agent/settings.py` | `PaneDefaults.explain_findings`; the study-arm checks (`_typed_changes`, `_check_pane_study_arm`) | `ProviderSettings.has_credential` | second; textual, keeping `PaneDefaults.explain_findings` |
| `reviewer/src/swreview/agent/events.py` | `replay_events`, `event_stream` and `_open_stream` moved in from `chat/sessions.py` | `local_now()` beside `utc_now()` (R2.15) | second; textual |
| `reviewer/tests/unit/test_replay_fixtures.py` | `BIG_RECORDED_TOTAL` and `BIG_FOLLOW_UP_RECORDED` move with 014's result changes, each with its reason | none, and nothing of 015 is proved by it: its totals are sums of recorded usage and read no prefix (R2.9); the move of `_prefix` is proved by the prefix characterization (R2.28) | none in the file; it must pass unchanged on both sides of the merge |
| `reviewer/tests/fixtures/replay/{big-assembly,small-assembly-a,small-assembly-b}/{session.json,events.jsonl}` (six files) | regenerated (origin marks, result changes) | none: they are the baseline FR-035 and SC-003 hold a ticked review to | the branch that merges second runs R2.28's regeneration step on the machine with the recordings against the other branch's regenerated fixtures; a difference is that branch's to explain or fix, never a fixture to regenerate in the merge |
| `reviewer/tests/unit/test_ticked_review_golden/` and `test_request_prefix_characterization` (015's, new) | none, but 014's origin marks change what a ticked review writes | the characterization of R2.28 | second: regenerated on the first-merged side alone (`main` after the first merge, without the second branch's code), committed in the merge, and the merged code must pass it unchanged |
| `specs/001-agentic-design-review/contracts/README.md` | two lines (origin marks) | its amendments note (`records.md`) | second; textual |
| `reviewer/tests/unit/test_atomic.py` | **new** | **new** only if 015 lands first (R4.1), with 014's exact content | an add/add conflict: the second keeps 014's file, one copy, as for `atomic.py` |
| `reviewer/src/swreview/tools/session.py`, `reviewer/src/swreview/agent/checklist.py` | `_documents_named` renamed `documents_named`; `SYSTEM_PROMPT_FILE` added | none; R2.27 relies on `with_open_items` and `Checklist.bucket_of`, which 014 leaves as they are | none |
| `reviewer/src/swreview/report/attention_record.py` | `write_attention_record` writes through `atomic.write_atomic` | none; `_render_run` and the re-run's copy call it as today | none: same file, same bytes |
| `reviewer/tests/support/mechanical.py` | `screw(fastener_row=False)` added, off by default | none; the fictional questions package (R2.25) builds through `roles_review`, which uses `PackageBuilder` with its defaults | none: a package built with the defaults is unchanged |
| `reviewer/src/swreview/ir/loader.py`, `reviewer/src/swreview/tokens.py` (not 015 files) | `append_interference_run` and `fetch_vocabulary` write through `atomic.write_atomic` in place of their inline temporary-and-replace | none; SC-008 rests on the merge order of `append_interference_run` (R2.17) and the estimate on `tokens.count_tokens` | no reconciliation: the merge order, the merged text and the counting are unchanged, so SC-008 and the estimate are unaffected; `test_recheck.py` and `test_send_estimate.py` run on both sides of the merge |
| `reviewer/src/swreview/report/session.py` | `InvestigationStep.origin_mark`, `ReviewSession.origin_marks`, `covers()` | `ModelStatus`, `LiveDetectionRecord`, `DrawingOutcome`, three fields, `save_session` through `write_atomic` | second; both add pops to the one serializer |
| `reviewer/src/swreview/atomic.py` | **new**: `write_atomic(path, data: bytes)` | needs the same helper for `save_session` | if 014 is on `main` first, 015 imports it; if 015 lands first, it adds `atomic.py` with 014's exact name, signature and body (`reviewer/src/swreview/atomic.py` on branch `014-design-review-eval`), and 014's merge keeps one copy |
| `reviewer/src/swreview/benchmark/replay.py` | `read_stored_result` in place of the inline read | `_prefix` becomes a call of `runner.request_prefix` | second; textual |
| `reviewer/src/swreview/benchmark/recording.py` | one docstring line | two refusals before the event read | second; textual |
| `reviewer/src/swreview/handoff.py`, `specs/002-.../contracts/handoff-export.md`, `reviewer/tests/unit/test_handoff.py` | 98 lines; a section added; tests for both | `model_status` in the session summary; its test rows | second; textual |
| `specs/001-.../contracts/review-session.schema.json` | `origin_marks`, `origin_mark` | `ModelStatus`, `LiveDetection`, `DrawingOutcome` and three properties | second; both additive |
| `specs/008-.../contracts/checks-first.md`, `replay.md` | sections added | amendment notes (R2.8, R2.16, R2.17) | second |
| `extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json` | regenerated (origin marks) | labels block gains five keys | second regenerates it in the merge commit, where the file is a conflict, so the merge passes the gate; its review checks the snapshot part is 014's and the labels block 015's |
| `reviewer/tests/unit/test_benchmark_pane_parity.py` (014 only) | fails on any unclassified `start_review` argument | adds `send_when_checked` and `earlier` | second classifies both as `COMPARED` (equal at their defaults on both surfaces, as `previous_session` and `fail_tool` are) |

The table is the intersection at `45b5076` of 014's diff (212 files) with every file 015 changes,
adds or relies on by name; a later 014 head is intersected again by the branch that merges second.
014 also changes `findings.py` and `tools/registry.py`, which 015 only calls: `finding_subject_key`
and `record_call` are unchanged there (014 adds functions beside them). The rest of 014's diff -
its benchmark modules, the CLI, its check goldens, its tests and documents, `specs/008-.../
contracts/cli.md` - is neither changed nor relied on by 015. The `smart_SW-fp` worktree touches
feature 010 documents only.

---

## R4. Tests

Test-first (62A, Principle III): every implementation task follows a failing test task. The new
tests, by layer, with the edge cases each covers; then every existing test that moves and why.

### R4.1 New reviewer tests (`reviewer/tests/unit/`)

| File | Covers (spec edge cases and requirements) |
|---|---|
| `test_send_gate_server.py` (route level, `TestClient`, `ProviderControl.built` must stay empty; every recorded request read from `tests/support/recording_provider.py`, R2.28) | checks-only start with no key: 201, `awaiting_send`, no provider built, no `turn.ended`, `session.started.send_when_checked` false, `session.ended`, `session.json` model status, and `report.md` already on disk with the not-sent header when the 201 arrives (`_render_run`, R2.6) (FR-006 to FR-010, US1-1, US1-2); the unticked start finalizes before it registers: a cache build or finalization that raises (`write_atomic` raising) answers the error body, registers no chat, and leaves the folder claimable (R2.6); an unticked start on an unreadable package answers `InvalidPackage` as today, with no provider built and no chat registered (the spec's "checks of an unticked review fail"); ticked review unchanged, a ticked review with no key still 502 before any check (FR-035); `send_when_checked` not a boolean, and `recheck` with `send_when_checked: true`, are 400; Send's refusal order (UnknownChat, SessionFailed, TurnRunning while answers apply, a second Send in flight, NotWaiting for a ticked or sent review, NoCredential with no key, none for an environment key, a Gemini enterprise project or the scripted provider, 502 on adapter construction - each leaving the chat waiting, FR-016, FR-018); the adapter built off the event loop (a factory that records the thread it runs on, never the loop's), with the chat already `running` while it builds: a second Send and an answer sent while a held factory builds are `409 TurnRunning`, and a factory that raises leaves the chat `awaiting_send` with the `502` (R2.7); **a Send that fails before any request** (R2.10), at each point - `configure_provider` raising, the effort mapping raising, the pre-write's `save_session` raising, the `session.sent` emit raising, and the undo save raising after a failed emit - each: no provider `run()` recorded, one `error` event and no `turn.ended` or `session.ended`, the chat back to `awaiting_send` (the page is not left waiting), `session.json` byte-equal to the record before Send with no `Interrupted` entry (in the undo-save case the file keeps the pre-write, the run the record before it, and the next Send's pre-write replaces the file), the Send block's failure line from `send.not_started`, and a second Send that succeeds; **a decision held in flight** (`record_disposition` held in the thread pool): `POST /send` and `POST /evidence` are `409 TurnRunning` and the chat reads `running`, then after the release the decision is saved, the chat is `awaiting_send` again and Send succeeds; the same with the timing route (R2.12); **every request of Send's first turn byte-identical to a ticked review's**, tool results included, with a scripted first turn that calls `mark_coverage`, `request_evidence` and `get_review_checklist` (SC-004, US2, R2.27), and the same comparison after a failed Send and after a re-run with nothing answered; after an apply while waiting, the session at the first request holds no row of any earlier finalization (no close-out, no unresolved row of an open question or item), so `get_review_checklist` and every `open_items` show each model-owned item with no finding as open (R2.27); a failed first request returns to `awaiting_send`, records the failure, and a second Send resends the opening once (FR-017); a failed Send, then an apply, then Send sends the rebuilt opening once (FR-017); a failure after a round is today's (FR-017 last sentence); after Send with a turn ending `end`, exactly one presentation request (R2.14); `POST /messages` is `409 NotSent` while waiting and `202` after the first `usage` (FR-019); an answer to a question the model asked after Send resumes the model with today's `ANSWER_MESSAGE` and `REGRADED_LINE`, byte for byte against the same answer in a ticked review (FR-015, R2.14); Stop while waiting writes no event (FR-025); shutdown while waiting writes no event, shutdown during an apply writes none (FR-010); a decision and timing while waiting are saved and kept at Send (FR-024); several reviews waiting at once each send alone; the `send` route is in `ROUTES` and refuses no token |
| `test_runner_send.py` (runner level) | `configure_provider` sets the three hooks as `start_review` did; `attach_provider` numbers steps from the session's count; the frozen opening is sent when nothing applied, the builder reproduces it byte for byte (SC-004); the Send cache (R2.8): built at the unticked start, after an apply and after a re-run's carry, each on the worker; its opening equal to the opening built again after the finalization; the attention and snapshot routes and `send` never build it (a builder patched to raise once the cache exists leaves both routes `200` and Send working); Send's order (R2.10): nothing in the session or on disk changed by the prepare half, the pre-write before `session.sent`, `session.sent` before the withdrawal, the run's `_finalized` list empty after it; the pre-written failure is honest after a simulated crash before the first `usage`; the first `usage` marks `sent` and saves the session as it stands - a simulated crash after it leaves `session.json` with state `sent`, `ended_at` null and no row of the checks' finalization, which `GET /reviews` reads read-only as a sent review (R2.11); the wait is not running time (FR-011); not-sent checklist reasons, answered-but-open reason (FR-009); `opening_finding_ids`; the model-status times stamped by `local_now` and rendered as stored: a record whose `checked_at` carries `+05:30` renders that wall clock in `{when}`, whatever the zone running the test (R2.15) |
| `test_deferred_provider.py` | name, model and the effort mapping equal each adapter's for every effort and for a model with no table row; an effort the model refuses raises the adapter's own error at setup; `run` and `for_presentation` raise `ProviderNotSent`; no SDK module imported |
| `test_send_estimate.py` | `request_prefix` moved byte for byte, proven by the prefix characterization committed before the move (`test_request_prefix_characterization.py`, R2.28), which the moving commit keeps green - never the function compared with itself, and never `test_replay_fixtures.py`'s totals, which read no prefix (R2.9); the estimate is the count of the cached opening and is recounted, in the cache, after an apply (FR-013); `None` with the vocabulary absent, by `monkeypatch.setattr(tokens, "encoding", <raises TokenizerUnavailable>)` (the precedent `test_step_sizes.py:166-171`; `tokens.encoding` is cached per process, `tokens.py:150-153`, so pointing `SWREVIEW_TOKENIZER_DIR` at an empty folder would meet the warm cache), and `None` for a restored review; Gemini is approximate (FR-012); SC-006 over the owner's recordings, skipped through `tests/support/recordings.recording_folder` and the vocabulary fixture as the replay's real-recording tests are (no new marker: `pyproject.toml` registers none for it) |
| `test_waiting_answers.py` (013's part-roles shape, `tests/support/roles_review.py`) | "All bought" while waiting withdraws the unclear part's findings with no provider request and recounts the size (US3 independent test). The fixture is built so the answer withdraws at least one **named** finding - a hygiene finding of the unclear part, the helper extended if it raises none - besides folded RMS findings, which the digest counts and never names (`PrerunResult._finding_lines`, `prerun.py:582-598`): the opening names no withdrawn named id and every standing one, the folded family's counts line in the rebuilt opening equals the regraded session's counts, the answer line is there, and there is no "withdrew" line and no instruction (SC-005, FR-023); "Apply answers" sentence; a Reject kept; a confirmed drawing read while waiting with the fake bridge writes the outcome line, a refusal's too (FR-021); an answered question cannot be answered again; Send refused while answers apply; **an apply that fails** - `classify_part_roles` raising, the confirmed read raising, the Send cache's build raising, the finalization's `save_session` (`write_atomic`) raising - each: one `error` event and no `turn.ended` or `session.ended`, the chat `failed`, `session.json` and `report.md` the record before the apply (its answers open), the provider factory never called, and a following `POST /sessions` with `recheck: true` claims the folder and succeeds (R2.13); the failure **after** the write (`write_attention_record` raising): `session.json` the applied record, its answers answered, and the re-run carrying them; **a drawing merged before the failure**: a confirmed read that merges its drawing into the folder's `package.json`, then the regrade raising - the re-run does not ask that drawing question again, carries no outcome line for it, and names the loss once in `coverage.recheck` (R2.13) |
| `test_recheck.py` | the earlier record with a part-roles answer, a drawing answer whose read moved the numbers, and a Reject (US4 independent test): no extraction, zero bridge calls before the first request (a counting fake bridge), the digest's interference line and coverage rows equal the first run's, answers and the decision on their own items, the outcome line carried, unmatched and ambiguous items named once (FR-028, FR-029, SC-008); with nothing answered, the first request byte-identical to the live waiting review's; every live outcome carried (clean, rows, collided, rows not written - the unresolved line and the decisions named - failed and not retried, no bridge, not an assembly); the carried live step at the first run's `live_detection.step_index`, every later step index and finding citation equal to the first run's, the guard's `ran_at_step` for a repeated live call naming the carried step, `tool-results/step-N.json` holding the carried payload, a failed first call carried as a failed step with the first run's `failed` row, and no step for a call never attempted (R2.17); decisions matched on `finding_subject_key`: two `hole.coaxiality` findings on one pair of components, one Rejected, the Reject carried onto its own finding and nothing named; the four timing inputs carried; a `send_failed` record re-run stays `send_failed` with its failures and its report keeps the failure line, and a Send that then succeeds reports "Earlier attempts that failed: 1" (FR-032); `drawing_read` carried with no ping and written on the re-run's session, and a second restart's re-run of that record again makes zero bridge calls (SC-008); a first run whose rows were not written (`persist_error`), with the dump's stale rows for the reviewed configuration still in `package.json`: the re-run judges none of them (no finding cites one) and its family row is `INTERFERENCE_ROWS_NOT_CARRIED`; the Standards profile changed between the first run and the re-run (another file, and the same file edited): the re-run grades with the profile in effect, records its identity in `model_status.profile`, names the change once in `coverage.recheck`, and names any decision whose finding the new profile no longer raises; an unchanged profile names nothing; `carried` id maps in the 201; **adoption**: a re-run whose answer the caller discards, then a second `recheck: true`, answers the same chat id and `carried`, runs nothing again and never calls the provider factory, while a live chat on the folder that is `running` is still `409 RunDirInUse`, and a second `recheck: true` sent while the first is still running (held in the backend) is `409 RunDirInUse` and starts nothing, the third, after the first answers, adopting it; the carry writes nothing - `session.json`, `report.md` and `attention.json` unchanged on disk from the claim until the finalization; a re-run that fails (an unreadable package) or is cut off at each of three points - after the rotation, after `start_review` and the carry and before the finalization, and inside the finalization's write (`write_atomic` raising) - leaves `session.json` byte-equal to the earlier record, `GET /reviews` not read-only with the restored block, the provider factory never called, and a second re-run succeeding at the next index (FR-041); two failed re-runs then one that succeeds leave every index a session with the stream it wrote or a failed attempt's stream with no session, the earlier record copied once (R2.17 step 2); a folder deleted is `404 UnknownReview`; a sent record is `409 NotWaiting` |
| `test_session_fields_015.py` | the three fields optional, omitted at their defaults, and `model_status.profile` omitted for a review with no profile; a pre-feature session round-trips to its own bytes (FR-036); each validates against the amended `review-session.schema.json`; `LiveOutcome` to record and back keeps every dataclass field (a field added later fails the test) |
| `test_send_block.py` | the summary's `send` block absent for a ticked review (the pane fixture's bytes), present waiting with and without a number, Gemini approximate, the failure line of a recorded failed request (`send.failed`) and of a Send that failed before any request (`send.not_started`, held by the run, absent after a restart), `restored`, its `session_id` the record's; `resume_text` while waiting; every sentence a words-file key |
| `test_questions_identity.py` | `asks_same` is the rule `answered_roles` and `_is_confirmed_candidate` used (their tests unchanged) |
| `test_report_model_status.py` | the three header variants, and a re-run's "Checked again from session" line; a ticked review's report unchanged (the characterization golden of R2.28) |
| `test_pane_waiting_fixtures.py` | the three waiting fixtures equal a fresh generation (the precedent `test_pane_drawing_fixture.py`); every clock value in them is the pinned fictional time; `review-waiting.json`'s `waiting` holds the part-roles question and a drawing-candidate question, both written by code; `rechecked.carried` maps at least one id to a different one (R2.25) |
| `test_ticked_review_golden.py` (**first**, on the pre-feature code; R2.28) | a ticked `POST /sessions` on the fictional questions package through the `TestClient`, with the recording provider: the opening turn, a part-roles answer that resumes the model, a follow-up and the explanation pass; every `run()` and presentation input, `events.jsonl`, `session.json`, `report.md` and `attention.json`, with times, durations and UUIDs normalized, equal to the committed golden (FR-035, SC-003) |
| `test_request_prefix_characterization.py` (before `_prefix` moves; R2.28) | for each committed replay fixture under the pane defaults, the first pass's prefix sha256 and length equal to the committed values (R2.9) |

Support modules: `tests/support/recording_provider.py` (moved from `test_prefix_stability.py`, with
`for_presentation` added) and `tests/support/questions_package.py` (new: the fictional questions
package the characterization, the waiting fixtures and `test_waiting_answers.py` share) (R2.28,
R2.25).

Existing modules extended rather than duplicated: `test_chat_sessions.py` (the table),
`test_chat_review_routes.py` (`GET /reviews` of a not-sent record is not read-only and carries the
restored block; a sent one is as today), `test_review_snapshot.py`, `test_events_schema.py` (an
unticked `session.started` with `send_when_checked: false` validates; `true`, or any other new key,
is refused; `session.sent` validates; `contracts/review-flow.md` section 7),
`test_recording.py` and `test_cli_benchmark_replay.py` (the two refusals), `test_handoff.py`,
`test_review_words.py`, `test_pane_fixture.py`, `test_replay_fixture_hygiene.py` (the three waiting
fixtures join its committed files, FR-039), and `test_atomic.py` if 015 lands `atomic.py` first
(R3).

### R4.2 New add-in tests (`extractor/SwReview.AddIn.Tests/`)

| File | Covers |
|---|---|
| `UserSettingsTests.cs` (extended) | absent, `null`, a string, a number each read ticked with one problem for the non-booleans and every other field loaded (FR-002); `false` round-trips; a file written before the feature saves to its own bytes; the schema validates both |
| `PageMessageTests.cs` (extended) | `init` and `settings` views carry `send_when_checked`; `send_when_checked.save` writes, does not restart (`Backend.Restarts` unchanged), is not refused while a turn runs, keeps every other field; a failed write is `SettingNotSaved` and the stored value stands; `settings.save` keeps the value; `settings.save` is accepted when the fake backend reports the review's chat `awaiting_send` and refused when it reports `running` (FR-027; the host's `IsTurnRunning` counts only `running`, `BackendClient.cs:118-122`) |
| `ReviewHostTests.cs` (extended) | `review.start` passes the stored value; `review.started` carries it; `review.recheck` refusals (no record, a drawing, another document, no backend), the request (`recheck`, the record's folder, the bridge, no dump), the record replaced, `review.rechecked` with `carried` and `review_session_id`; the call made with `Recheck` set, so the client chooses the re-run's timeout; a backend refusal rethrown with its class; messages handled in order - a `review.start` then a box change: the start passes the old value and the change is written after it (FR-002, FR-003); a Retry (`review.start` after a failed start) passes the value stored when it is handled, after a box change (the spec's Retry edge case); a `CreateSession` that times out on an unticked start is today's failure, with no record kept (the orphan waiting chat of `review-flow.md` section 1) |
| `RunFoldersNotSentTests.cs` (new) | the search over fictional folders: offered when the newest same-name folder's record is not sent or send failed and names this path and configuration; not offered behind a newer sent review, a failed check run, another path, another configuration, or when the session holds a review of the document; check, standards and remodel folders skipped; the collision suffix; a `session.json` written by the Python fixture generator read by the head reader (the cross-language contract); a head with no `model_status` within 64 KiB is nothing; the found chip's date is the stored `checked_at` wall clock (R2.15); a 500-folder root within 2 s (FR-030; a perf trait) |
| `BackendClientSessionBodyTests.cs` (new, an in-process `HttpListener` on 127.0.0.1 as `RemodelBackendClientTests.cs` uses, 004 T134d - `StubBackend` is a process-lifetime stub that serves no `POST /sessions`) | the body carries `send_when_checked` and `recheck`; the 201's `carried` reaches the handle; the timeout chosen whenever `SendWhenChecked` is false - an unticked start and a re-run - is the long one, and for a ticked start and every other call the 30 s one (`BackendClient.TimeoutFor`, checked directly, with no waiting) |
| `ReviewPageSendGateTests.cs` (new, offscreen WebView2, `review-waiting.json`) | the box: under the buttons, from `init`, a change posts the message, a refused write puts it back with the label, never disabled; an unticked start: no turn running, Stop off, the status line, the Send block with its sentence, the follow-up off with its placeholder; the status line "Checked by code. Not sent to the model." ahead of "Waiting for your answers." with code questions open (FR-033); Send: posts `/send`, running at the first `usage`, the follow-up box enabled after it; a failed first round (`failed_send`): no error card, the failure line, Send again, and the text the failed round streamed still in the Transcript (FR-017); `NoCredential` beside Send; "Apply answers"; an apply leaves the status and Stop as waiting; a reload while waiting and during an apply shows waiting; an apply that fails: no error card, the panel unlocked, the review restored from its folder with the error's line (R2.13); Send disabled while another document or a drawing is active and offered again on return (FR-018); the Settings section's waiting line (FR-027); transcript lines; a chip's "not sent"; Review pressed while waiting (FR-026); zero proxy calls to `/send`, `/messages` and `/evidence` across Clear review, a document switch and Review again (SC-001); "Before this review" still says no tokens were used with the box unticked; the Send block under the summary and above the questions panel; a Send that fails before any request (an `error` with no `usage` and no `session.ended` after it): no error card, the turn unmarked, the failure line, Send offered again (R2.10); with `HoldReviewStart`, a box change shows at once and its `send_when_checked.save` is posted after the `review.start`, and on release the waiting state follows `review.started`'s value, not the box (FR-002, FR-003); a `review.start` error with the box unticked (`InvalidPackage`) shows today's error card and Retry and no Send block |
| `ReviewPageRecheckTests.cs` (new, `review-waiting-restored.json`) | a restored waiting review: the restored line, the sentence without a number, controls on; Send, an answer and a decision each go through `review.recheck` and then the live route with ids re-keyed by the fixture's own `rechecked.carried`; an answer naming the record the page already shows (`send.session_id`, an adopted re-run) re-keys nothing; an unmatched decision says so; a re-run in flight: the status line, Save, Review, chips, answers, decisions and Send off, no Stop; a failed re-run: its line, Send still offered, no Retry; a folder gone: feature 009's sentence; a backend restart with a waiting review on screen restores it at once (FR-042); a found chip names its date when not today; a page reload while a re-run is held shows nothing of the review until the release, then shows it waiting - never running and never being checked again (FR-033, the restoring edge case) |
| `ReviewPageSendLayoutTests.cs` (new, `review-waiting-big-assembly.json`) | at 300 by 600, the headline, tally and not-reached line inside the viewport in each worst case a waiting review shows (SC-007): `waiting`; `failed_send`, with its failure line; `restored`, with its restored line and sentence; and `restored` after a failed re-run, with the `rerun_failed` line; in the same four, the Send to model button inside the viewport too (R2.21); the measured slack recorded in R2.21; at 260, 300 and 420 px the session buttons wrap as today (two rows at 300 px) with the box directly under them |
| `ReviewPageDriver.cs` (extended; the page tests' host) | answers `send_when_checked.save` and `review.recheck` (the second with a fixture's `rechecked` body), an error mode for each, and `HoldReviewRecheck` / `ReleaseReviewRecheck` beside `HoldReviewStart` / `ReleaseReviewStart`, so a re-run can be held in flight. Unlike `HoldReviewStart`, which holds only its own reply, `HoldReviewRecheck` also queues every message the page posts after it and answers them in order on release, as the host's one pump does (R2.2), so a reload during a re-run is answered only after it |
| `ReviewPageDefaultViewScanTests.cs` (extended) | the raw tokens `awaiting_send`, `not_sent` and `send_failed` never visible, scanned on `review-waiting.json` and `review-waiting-restored.json` as well as the pane fixture |

The six `IBackendClient` fakes (`EventStreamPumpTests`, `PageMessageTests`, `PaneActionsTests`,
`ReviewHostTests`, `RunFoldersStandardsTests`, `ToolServiceWiringTests`) need no change: 015 adds no
interface member (`NewSessionRequest` and `ChatSessionHandle` are classes), and `ChatSessionHandle`
gains `carried` as an optional constructor parameter, so the one fake that builds a handle
(`ReviewHostTests.FakeBackend`) compiles unchanged.

### R4.3 Existing tests that move, and why

| Test | Moves because |
|---|---|
| `reviewer/tests/unit/test_chat_sessions.py`: `test_every_state_can_fail`, `test_a_transition_the_table_does_not_name_raises` | the transition table gains `awaiting_send`; new paths and refused moves are added (`test_failed_is_terminal` iterates `ChatState` and passes unchanged) |
| `reviewer/tests/unit/test_chat_server.py`: `ROUTES` (`:279-296`) | the census gains `POST /sessions/{chat}/send`, so the door test covers it |
| `reviewer/tests/unit/test_events_schema.py`: `test_a_full_run_emits_every_event_type_the_runner_and_tools_can_emit` | the full run must include an unticked review sent after waiting, so `session.sent` and the `send_when_checked` field are emitted |
| `reviewer/tests/unit/test_review_words.py` | the words file gains the `send` block and five error labels |
| `reviewer/tests/unit/test_pane_fixture.py` | the labels block gains keys (snapshot part unchanged) |
| `reviewer/tests/unit/test_replay_fixture_hygiene.py` | the three waiting fixtures join the committed files its string checks read |
| `reviewer/tests/unit/test_recording.py`, `test_cli_benchmark_replay.py` | two new refusal rows ahead of the event read |
| `extractor/SwReview.AddIn.Tests/ReviewPageViewsTests.cs`: `TheStatusLineReadsEachOfItsFourSentencesInItsState` (`:107-118`) | six sentences; renamed accordingly |
| `extractor/SwReview.AddIn.Tests/ErrorLabelsCoverTheHostTests.cs`: `TheScanFindsTheClassesTheHostAndThePageMake` | the expected list gains `ReviewNotActive` and `SettingNotSaved` |
| `extractor/SwReview.AddIn.Tests/PageMessageTests.cs`: `ReadyIsAnsweredWithInitCarryingTheBackendOriginAndNoKey` | asserts the view's new key (additive) |
| `extractor/SwReview.AddIn.Tests/UserSettingsTests.cs`: `RoundTripsEveryFieldThroughATempFileAndSatisfiesTheContract` | the new field round-trips |
| `extractor/SwReview.AddIn.Tests/ReviewHostTests.cs`: the `review.start` test that asserts every `NewSessionRequest` field (`:322-370`) and `FakeBackend.CreateSession` (`:2123`) | the request gains `SendWhenChecked` and `Recheck` |
| `extractor/SwReview.AddIn.Tests/ReviewPageContractTests.cs`: `TheReviewStartRowsReplyNamesTheDocumentItReviewed` (`:178-186`) | it asserts the exact substring "review.started {chat_id, run_dir, not_examined, document}" of 002's `review.start` row (`:184`), and the amendment adds `send_when_checked` to that reply: the asserted substring becomes "review.started {chat_id, run_dir, not_examined, document, send_when_checked}", in the commit that amends the row |
| `extractor/SwReview.AddIn.Tests/ReviewPageDefaultViewScanTests.cs`: `NoRawStatusOrBucketTokenIsVisible` (`:55-65`) | its token list (`:60`) gains `awaiting_send`, `not_sent` and `send_failed`, and it runs on the two waiting fixtures too (R4.2) |
| `reviewer/tests/unit/test_prefix_stability.py` | `RecordingProvider` moves to `tests/support/recording_provider.py` (R2.28); the module imports it, every assertion unchanged |
| `extractor/SwReview.AddIn.Tests/ReviewPageSummaryAcceptanceTests.cs` (`:91-109`) and `ReviewPageNarrowLayoutTests.cs` (`:37-53`) - not edited | the box is a line in `#session` in every review, ticked included; measured (R2.21) at about 21 px of 226 px of slack, so both pass with it unedited. The first page task runs both with the real box in place |
| 014's `test_benchmark_pane_parity.py` | at merge only (R3) |

Unchanged and expected to pass untouched (each a check that the default path did not move):
`test_no_lever_in_pane_settings.py`, every replay test and fixture, every check golden (`tests/golden`),
`test_session.py`, `test_runner_provider.py`, `test_part_roles.py`, `test_confirmed_drawing_read.py`,
`test_answer_batch_roles.py`, `ReviewPageContractTests.cs` but the row above,
`PageRuleScanTests.cs`, `ReviewPageSessionsTests.cs`, `ReviewPageQuestionsTests.cs`,
`ReviewPagePreparationTests.cs`.

---

## R5. Risks

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | Something sends before Send (a hook missed) | `ProviderControl.built` empty and a provider stand-in that fails on any call, across every path SC-001 lists; the page tests count proxy calls to `/send`, `/messages` and `/evidence` |
| RK-2 | The opening rebuilt after a regrade differs from what a fresh review would say, or SC-004 drifts | frozen opening when nothing applied; the builder pinned to it; the regrade fixture checks named and withdrawn ids and the folded counts line |
| RK-3 | The 300 by 600 budget breaks with the box and the Send block | measured on the committed build (R2.21): about 226 px of slack above the fold on the finished big assembly; the box takes about 21 px; a Send block above the summary failed its worst case (a restored review after a failed re-run) on a proxy, so the block sits under the summary, where it moves nothing SC-007 reads, and only the box and the restored line (about 91 px together) stand above it. `ReviewPageSendLayoutTests` measures the four worst cases on the big-assembly waiting fixture once it exists and records the figure; if SC-007 still fails, the page work stops and the owner is asked which gives way (R2.21) |
| RK-4 | A re-run leaves the folder unrestorable | the record is copied, not moved, and replaced atomically at the re-run's end; the carry writes nothing before it; a failed attempt's stream rotates alone; fail tests and kill tests at three points |
| RK-5 | A carried answer or decision lands on the wrong item | identity, never number (`asks_same`, `finding_subject_key`); ambiguous is not carried and is named; the moved-numbers fixture and the two-coaxiality-findings case |
| RK-6 | The found-review search slows document opening | runs on the pump thread, names first, one bounded head read; the 500-folder test |
| RK-7 | A crash mid-Send leaves a record that says "not sent" though the model received the request, or "sent" beside "not sent" rows | the attempt is written as failed ("the backend stopped before the model answered") before the request; at the first round the session is saved as a sent review mid-turn, the checks' finalization rows already withdrawn (R2.11) |
| RK-8 | Merge conflicts with 014 | R3's table; whichever merges second reconciles, classifies the two `start_review` arguments, marks the carried live step `prerun`, regenerates the pane fixture and the characterization golden in the merge commit (the golden on the first-merged side alone), and runs the replay regeneration step against the other branch's fixtures (R2.28) |
| RK-9 | The seat has no tokenizer vocabulary, so the size sentence never shows a number there | the sentence without a number is the spec's; the [W] task records whether `swreview tokenizer fetch` (or `--from`) was run |
| RK-10 | `POST /sessions` does more before its 201: an unticked start adds a cache build, a finalization and a render, and a re-run runs the checks; the host waits 30 s for any call (`BackendClient.cs:39`) | one rule: every call with `send_when_checked` false - an unticked start and a re-run - has the long timeout, 10 minutes (default; `TimeoutFor`), and a ticked start keeps 30 s (FR-035); a re-run the host gave up on is adopted by the next one (R2.17); an unticked start the host gave up on leaves an orphan waiting chat that is never sent and is released at the next restart (`review-flow.md` section 1); the [W] task records how long the small assembly's unticked `POST /sessions` and a re-run of it take, so the bound can be set from a measurement |
| RK-11 | The Send turn reads a coverage the checks' finalization left, and stops early | the rows are withdrawn by identity before the first request (R2.27); every request of the turn compared with a ticked review's, tool results included |
| RK-12 | An apply that fails leaves the page locked, or a report that matches neither record | the run puts the record on disk back before `_play` re-renders, one `error` event is written, the chat fails, and the page restores the review from its folder (R2.13); the failure points before and after the finalization's write tested, and a drawing merged before the failure named by the re-run |
| RK-13 | Send fails before any request (the adapter's setup, the pre-write, the `session.sent` event) and leaves the page waiting or a record that says a request was made | the prepare half changes nothing; the commit half is guarded: the model status is put back, the pre-write undone, one `error` written, the chat back to waiting (R2.10); five failure points tested |
| RK-14 | Two threads write one waiting session (a decision's write beside Send's pre-write) | on a waiting chat the decision and timing routes hold it `running` for their write, so Send, an answer and a Settings save are refused meanwhile (R2.12); a held-decision test |
| RK-15 | A refactor of the ticked path drifts and every planned comparison, new code against new code, still passes | the characterization golden and the prefix characterization are committed on the pre-feature code before any refactor, and the replay regeneration step runs where the recordings are (R2.28) |

---

## R6. Questions this plan adds for the owner

Each has a default the tasks build; the owner may change it before or after. The plan's review of
2026-10-09 added none: each of its fixes is either forced by the code or a default recorded above
(R2.13's apply failure, R2.17's adoption, timeout and decision key, R2.15's times). Its second review
the same day added question 3; its other fixes are forced by the code or measured (R2.10's guard,
R2.12's hold, R2.21's placement, R2.28's pins).

1. **The chips' "not sent" mark after a page reload.** Default (A): the page marks a chip from what
   it has seen this page load and from the host's found reviews; after a reload a chip shows its
   mark once it is chosen. (B) the host reads each listed review folder's `session.json` head on
   every `sessions.list` (exact after a reload; one bounded file read per kept review per list).
   (C) the host asks the backend for each live chat's state (exact for live chats only; one loopback
   call each). A is the least machinery and a reload is rare; B is the exact one.
2. **The handoff export (R2.24).** Default (A): it gains the model status. (B) leave the export as
   it is (it then names a provider for a review never sent). A is one field and keeps FR-032's
   honesty in every record a review leaves.
3. **The Standards profile after a restart (R2.17, second review).** A re-run follows the usual
   restart, a Settings save, which may have changed the profile. Default (A): the re-run grades
   with the profile the settings name now, as Send uses the provider in effect, and its one line of
   what was not carried says the profile changed; decisions on findings the new profile no longer
   raises are named there too. (B) refuse the re-run while the profile differs from the one the
   checks graded with, saying so; the engineer either puts the profile back or presses Review for a
   fresh review (losing the answers and decisions 61A keeps). (C) grade with the first run's
   profile - not possible as such: the record keeps the profile's identity, not its content, and
   the file may have changed. A keeps 61A's "same paused review" for everything but the setting the
   engineer chose to change, and says so; B is the strictest reading of "the same paused review".
