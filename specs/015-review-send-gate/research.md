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
(R2.21); entries it changed are marked *second review, 2026-10-09*, and R2.28 is added. A fifth
pass the same day, after the tasks' adversarial review, opened the files its fixes cite at the same
product code (`chat/server.py`'s stop flag, the page's `sessions.list` calls, the add-in test
project's fixture glob, the command-line review's output); entries it changed are marked *tasks
review, 2026-10-09*. A sixth pass the same day applied the owner's review of the plan (CLAUDE.md's
review in its BIG CHANGE form, decisions 68A to 80A, each recorded in R7 with the options it
rejected), reading the files each decision cites at the same product code; entries it changed are
marked with the decision's id. A fresh review of the amended head `8347827` on 2026-10-12 is
recorded in [review-2026-10-12.md](review-2026-10-12.md); it corrected the Send rollback snapshot
order and the Setup note's timing, and records an open FR-041 finalization finding. The earlier
VERIFIED dates and line numbers remain historical evidence. The accepted 010 integration is
required before 015's baseline pins; its exact baseline commit is recorded there once available.
Line numbers drift; every task re-verifies before editing.

The owner asked for no interactive questions. Every question the spec left open is settled here by a
default, marked **default taken 2026-10-08, the owner may revise**. The three the spec put to the
owner (its questions 2 to 4) and the three this plan added (R6) were answered by the owner's plan
review of 2026-10-09 (R7): the spec's questions 2 and 3 and the plan's question 3 kept their
defaults, the spec's question 4 took its alternative (68A), and the plan's questions 1 and 2 were
settled by 73A.

Every example value in this package is fictional (`FICT-`); no design name, number, company value
or local path is written here.

---

## R1. Sources and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | Four user stories, FR-001 to FR-042, SC-001 to SC-010, owner decisions 59A to 62A and the plan review's 68A to 80A (R7) | Normative for what is built |
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
file's token is held raw (`JsonElement? SendWhenCheckedValue`), the settable `bool SendsWhenChecked`
reads it (two members, owner decision 73A), and `Normalize` reports and clears a non-boolean
(data-model section 1). A converter that read a bad
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
`send_when_checked.saved {send_when_checked}`. The host clones its settings, sets the value and hands
the clone to `PersistSettings(next)`, the one persist step `settings.save` uses too (owner decision
73A): it saves the file (the existing atomic `UserSettings.Save`), replaces `_settings` and clears
`_settingsError`. The box's save does not restart the backend and does not ask whether a turn runs.
A failed write answers `error {error_class: "SettingNotSaved"}` from either handler; for the box the
page puts it back to the stored value and prints the label for that class under the box.
`settings.save` keeps the value (it already clones every field the page does not send).
(`contracts/pane.md` sections 1 and 12.)

**One persist step** (73A). VERIFIED (2026-10-09) that `settings.save`'s persist step
(`ReviewHost.cs:879-910`) clears `_settingsError` (`:910`) and lets a failed write reach `Receive`'s
catch-all as `HostError` (`:596-599`), while the box was planned to answer `SettingNotSaved` and clear
nothing; and that the box writes `Clone(_settings)` (`:1406-1413`), whose values `Normalize` has
already replaced in memory (`UserSettings.cs:400-451`), so a box click on a hand-edited file with a
load problem writes the replacements - as a Settings save does - and, with no clear, leaves
`ReportSettingsProblems` (`:937-956`) re-posting a problem the file no longer has. One persist step
keeps the two writers one rule. `settings.save`'s failed-write class moves from `HostError` to
`SettingNotSaved`, which no test pins (checked during the review); the label is worded for both.

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
`review.start` and `review.recheck` share one body, `ReviewHost.CreateReviewSession(document,
runDirectory, retryOf, mode)`, whose `mode` is `ReviewMode { Send, Wait, Recheck }` (owner decision
71A): the host can build no re-run that sends at once, the one pair the backend refuses.
`NewSessionRequest` gains `Mode` (default `Send`), and `BackendClient.CreateSession` always writes
the wire's two booleans from it (`send_when_checked`, `recheck`). (`contracts/pane.md` section 2,
`contracts/review-flow.md` section 1, data-model section 9.)

**Why**: VERIFIED that the host builds the session request from its own settings
(`ReviewHost.cs:1295-1305`) and that the body is exactly eight fields today
(`BackendClient.cs:131-150`). Because the pump handles messages in order, a review started after a
box change uses the new value and a running review keeps the one it started with (FR-002, FR-003).
`review.started` carries the value so the page knows at once that this review will wait, before
any event arrives, and never marks a turn running for it (FR-025).

**Alternatives**: the page sends its box value in `review.start` (two sources; and a box whose
write failed would still govern the review); the backend reads the settings file (it never does:
`chat/server.py:1999-2002`); two booleans on `NewSessionRequest` and `review.recheck` written beside
`StartReview` (the plan before 71A: about forty lines of `StartReview` - the drawing refusal, the
backend check, the request, the rethrow, `ReviewHost.cs:1198-1331` - kept in step by hand, and a
request type that can express the refused pair).

### R2.4 One new chat state, `awaiting_send`; answers and Send on a waiting review run as `running`

**Decision**: `ChatState` gains `awaiting_send`. Transitions added: `extracting -> awaiting_send`
(checks done, box unticked), `awaiting_send -> running` (Send, or answers being applied),
`running -> awaiting_send` (answers applied; Send failed before any request, its adapter's build
included, or its first request failed before a model round completed), `awaiting_send -> failed`
(any state can fail). Applying answers, and a Send from its route's acceptance (its adapter's build
included) to its first round, are the existing `running` state, so the existing `_require_idle`
refuses a second action with `TurnRunning` and the host's `AnyTurnRunning` refuses a Settings save,
unchanged. The write of a decision or of the timing inputs is not: it runs on the chat's one worker
and leaves the chat `awaiting_send` (R2.12, owner decision 69A). `_play` settles `awaiting_send` when the run still waits, else as
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
Settings saves are accepted, FR-024, FR-027; a decision's write is queued on the chat's worker, R2.12),
and the three kinds of in-flight work FR-027 lists
(answers applied, a Send in flight, a re-run) are refused as a turn is - the first two by state,
the third because the re-run runs inside `POST /sessions` while the host's pump waits for it
(R2.17). A page reloaded while answers are applied reads `chat_state: "running"` with a `send`
block and shows the review waiting, never running (FR-033); a page reloaded during a Send reads the
snapshot's `send_in_flight` and shows it sending (owner decision 77A, R2.30).

**Alternatives**: a second new state for "applying" (the task asks for one; and every existing
refusal would need it added by hand); keeping the chat in `awaiting_send` with a separate busy flag
(the host would have to read a second field to refuse a save, and `_require_idle` a third case);
`ended` with a flag (the page and the host already treat `ended` as "may take a follow-up", which
FR-019 forbids).

### R2.5 No provider is set up until Send: `DeferredProvider`

**Decision**: a review started with the box unticked is set up with `DeferredProvider`
(`agent/providers/deferred.py`, new): it carries `name`, `model` and the adapter's own effort rule,
accepts `start_steps_at`, and raises `ProviderNotSent` from `run` and `for_presentation`. It reads
no key and constructs no SDK client. It does import the provider's SDK module: its effort rule is
the adapter module's `effort_mapping_for`, `start_review` calls `effort_mapping` at setup
(`runner.py:1581`), and those modules import their SDK at their top (`openai_provider.py:50-52`,
`gemini_provider.py:50`). So an unticked start loads the SDK module, builds no client and reads no
key; `test_deferred_provider.py` asserts exactly that, and not "no SDK imported" (owner decision 74A,
correcting this entry and its test as the plan first wrote them). The three setup hooks of `start_review` (model view, lever 3's
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
(`openai_provider.py:389-407`, `gemini_provider.py:382-406`, `fake.py:254-256`), and (74A) that the
tables and their error classes live in the modules that import the SDKs (`openai_provider.py:88-91`,
`:153`; `gemini_provider.py:95-108`, `:148`), so the rule cannot be reached without the import. With the box
ticked, nothing changes: the server still calls `provider_factory` first, so a review with no key
fails before any check as today (FR-035, the spec's question 3).

**Alternatives**: building the real adapter whenever a key exists (FR-007: no client until Send);
making the adapters tolerate a missing key until `run` (changes the ticked failure, which FR-035
keeps); splitting `start_review` into a checks half and a model half (moves every line of setup for
a seam two hooks give); moving the effort rules into one module that imports no SDK, with one table
read by the three adapters and `DeferredProvider` (weighed in the plan review and not taken, 74A:
the promise FR-007 makes is no client and no key, which holds either way, and the move would touch
every provider module for an import nothing depends on).

### R2.6 A checks-only review ends with a finalization and no turn

**Decision**: with the box unticked, `create_session` does what it does today up to
`_start_review`, then - instead of moving the chat to `running` and submitting `run.start` - ends in
`ChatServer._open_waiting(chat, run)`, the one tail it shares with a re-run (owner decision 71A):
on the thread pool, `run.close_waiting()` builds the run's Send cache (the opening and its estimate,
R2.9) and finalizes the run - `close_waiting` is the only caller of `build_send_cache` on these
paths - then the report and the attention record are rendered and `run.release_bridge()` closes the
run's SOLIDWORKS pipe (owner decision 79A, R2.29), all **before the chat is attached and
registered** (*revised 2026-10-09*); and only then does `_open_waiting` attach and register it and
move it `extracting -> awaiting_send`, and the route answers 201. The render is today's `_render_report` body extracted as
`ChatServer._render_run(run, report_path, run_dir)`, which `_render_report(chat)` now calls and the
unticked start calls with the chat's own paths before the chat is attached (*second review,
2026-10-09*): `_render_report` returns at once while `chat.run` is `None`, so calling it there would
write no `report.md` before the 201. A cache build or finalization that raises closes the run
(`run.close()`, which closes its bridge, as `start_review`'s setup does when setup raises), moves the
unregistered chat `extracting -> failed` and answers the error body any unexpected failure of
`POST /sessions` answers today, so no chat is left holding the folder and a shutdown can never
finalize the same run while this call does; the render, as `_play`'s, logs a failure and never
raises. The finalization writes no `turn.ended`; `session.ended` is written, as by every
finalization. The host makes this call with the timeout a re-run's call has, which is measured
(R2.17, owner decision 70A): `ChecksOnlyTimeout`, or the one 30 s rule when the measured re-run fits
inside 30 s.
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
scripted provider). Then, on the event loop with no `await` between them and the checks, the route
moves the chat `awaiting_send -> running`, sets the run's `_send_in_flight`, submits
`run.send(build_adapter)` to the chat's one worker (`_submit`, so it runs inside `_play`) and
answers `202` (owner decision 69A). `build_adapter` is the `provider_factory` call with the chat's
settings; it runs on the worker, inside Send's guarded prepare half, never on the event loop - the
factory constructs the SDK client, whose first import can be cold (*second review, 2026-10-09*). A
factory that raises is one of the ways a Send fails before any request (R2.10): one `error`, the
`send.not_started` line, the review back to waiting; never a refusal of its own. The settings used
are the chat's
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
page would choose a provider the backend was not started with); building the adapter in the route,
`await`ed on the thread pool after the move, with a `502` and a hand-cleared stop flag when it
fails (the plan before 69A: one failure class with two surfaces, a `502` that writes no event beside
the guard's `error` and `send.not_started`, against the spec's edge case "Send failing before its
first request", which keeps such a failure in the event stream).

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
as one `SendCache` value, replaced by one assignment. Its one caller is `ReviewRun.close_waiting()`
(owner decision 71A), which builds the cache and then finalizes, at three points, each on a worker
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

**Decision** (*revised 2026-10-09*; the order and the guard *second review, 2026-10-09*; the
adapter's build in the prepare half, owner decision 69A; `session.sent` before the pre-write and a
guard that only restores memory, owner decision 72A): `ReviewRun.send(build_adapter)` runs on the
chat's worker, inside `_play`, in two halves and a guard.

- **Prepare** - nothing written, nothing emitted, nothing in the session changed: first keep a
  deep copy of the model status and clear the prior in-memory `_send_error`, before any guarded
  operation can raise (2026-10-12 re-check). Then (1) build the adapter by calling `build_adapter`,
  the route's `provider_factory` call with the chat's settings (69A); (2) configure the adapter
  (`configure_provider`, `start_steps_at`) without yet making it the run's provider; (3) read the
  opening, its estimate and its named ids from the Send cache (R2.8), built earlier on the worker;
  (4) build the `session.sent` body (`adapter.name`, the model, `adapter.effort_mapping(effort)`,
  the estimate).
- **Commit**: (5) emit `session.sent` - first, so the guard never has a write to undo (72A); its
  Transcript line reads "Sending to {provider} {model} ...", because it can now come before a save
  that fails; (6) the pre-write - the attempt goes into the model status as failed with the reason
  "the backend stopped before the model answered", and the session is saved as it stands, still the
  checks' finalized record, through `write_atomic`, so a crash from here on leaves a whole record and
  a save that fails leaves the file it was replacing whole (`contracts/records.md` section 8); (7)
  `withdraw_finalization(session, _finalized)` - the body `finalize_session` runs at its start
  (`runner.py:619-627`), extracted and called in place (72A; R2.27) - with `_finalized` cleared, the
  adapter made the run's provider and `awaiting_send` cleared: a filter of lists in memory and
  assignments, which cannot fail; (8) run the opening turn.
- **The guard** over steps 1 to 7, whose five failure points are the factory, `configure_provider`,
  the effort mapping, the `session.sent` emit and the pre-write's save: anything they raise puts the
  model status back from the copy, in memory only - the guard never writes, because nothing before
  step 6 wrote and a failed step 6 left the file whole; leaves the `DeferredProvider` in place; keeps
  `awaiting_send` and clears `_send_in_flight`; holds the failure in memory (`_send_error`: its time,
  class and redacted message), which the Send block shows until the next Send; emits one `error`
  (`retryable: true`) and no `turn.ended` or `session.ended`; and returns normally, so `_play` settles
  `awaiting_send`, re-renders the unchanged session and releases the pipe (R2.29). When the guard's
  own `error` emit raises - an unwritable `events.jsonl` fails it for the reason the step failed -
  the failure is logged and not raised, so `_play` still settles `awaiting_send` rather than failing
  the chat with no event while the page waits on its Send (72A). No request was made, so nothing is
  recorded in the model status: "send failed" means a request was made (spec, Key Entities).

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

**The windows the commit half leaves.** A crash between `session.sent` and the pre-write leaves the
record as it was before Send and a stream whose last line is `session.sent`, which the Transcript
reads "Sending to ...", still true (72A). A crash between the pre-write and the request leaves
`send_failed` although no request left the machine; the record cannot tell the two apart and errs on
the side of the model having been asked, the trade RK-7 takes. A raised exception in either window is
not a crash: the guard restores memory, and the file is the last whole write. The crash cases are
tested as the folder a crash leaves, copied at that point with nothing raised, and read by a backend
started afresh (`tests/support/restart.py`, owner decision 76A; R4.1).

**Default taken 2026-10-08, the owner may revise** (the guard's in-memory failure: second review,
2026-10-09; the build inside Send, owner decision 69A; the commit order and a guard that never writes,
owner decision 72A).

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
which has marked a Send in flight, waits for one - and a record pre-written at step 6 would say a
request was made when none was. VERIFIED (72A) that the guard's own `error` emit can fail for the
reason the step failed (an unwritable `events.jsonl`), and that an exception out of the guard would
reach `_play`'s `except`, whose `_close_out` returns at once for a session with an `ended_at`
(`chat/server.py:2235`): the chat would fail with no event while the page held `state.sending`.

**Alternatives**: catching in `send` after `_run_turn`'s finalization (two `session.ended` events
and a summary that reads "finished" for a moment); a new event for a failed send (the page already
reads the summary at `session.ended`); reloading the record from disk in the guard, as an apply
failure does (R2.13) - unneeded, because the prepare half changes nothing in the session and the
commit half changes only the model status before its last, infallible step; recording a failure
before any request in `model_status.failures` (it would say a request was made); the pre-write before
`session.sent`, with an undo save in the guard (the plan before 72A: a fifth failure point and its
test, and an undo that fails left `session.json` saying `send_failed` while the run held the earlier
state); a step-4 precompute of the withdrawn coverage beside `finalize_session`'s own filter (the plan
before 72A: two copies of one rule); building the adapter in the route with a `502` refusal (the plan
before 69A, R2.7).

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
on a waiting chat now run on the chat's one worker, where they are queued ahead of any Send and never
run beside one - R2.12, owner decision 69A): so this save is the one write in the middle of a turn,
and saving the last finalized record with only
its state changed - the other way to keep it whole - would put "not reviewed, because the review
was not sent to the model" beside "Sent to the model" in the file `GET /reviews` restores.

**Alternatives**: patching only `model_status` onto the saved checks-only record (the contradiction
above); saving nothing until the turn ends (a crash after a completed round would leave "the
backend stopped before the model answered", which is false once the model has answered).

### R2.12 Decisions, timing, Stop and shutdown on a waiting review

**Decision** (*owner decision 69A, 2026-10-09*, replacing the second review's hold): Accept,
Reject and Defer, and the timing route, work on a waiting review through the existing routes
(`_require_idle` accepts `awaiting_send`), with one change: on a chat in `awaiting_send`, each route
submits its write (`record_disposition`, `record_timing_live`) to the chat's one-thread worker and
awaits it, through one helper, `ChatServer._on_worker(chat, call)`, and the chat stays
`awaiting_send`. A Send or an answer accepted while the write runs is queued behind it on the same
worker, so no two threads write one session, and nothing moves the chat or touches its stop flag
outside `_play`. A Settings save that arrives during the write is not refused: FR-027 does not list
that case, it is what a decision on an ended review meets today, and `save_session` is atomic through
`write_atomic`. A chat in any other state takes today's path unchanged, so a ticked review's routes do
not move (FR-035). Stop on a waiting review changes nothing; a graceful shutdown writes nothing for it
(R2.6). Each is pinned by a test: one holds a decision's write on the worker and sends `POST /send`,
which is accepted and whose Send runs only after the write returns; another sends `POST /evidence` in
its place, applied after the write.

**The stop flag** (owner decision 69A, replacing the tasks review's hand-cleared flag). `_play`'s
`finally` stays the only place the flag is cleared. A stop during a decision's or the timing's write
meets `awaiting_send` and writes nothing, as on any waiting review. A stop during Send's adapter build
meets `running`, because the route moved the chat before it submitted the Send, and sets the flag;
the build runs inside `_play`, so a build that fails is a guard failure (R2.10) and `_play`'s
`finally` clears the flag before the chat waits again, while a build that succeeds keeps it, and Stop
is today's from then on (the first turn ends `stopped` at its first tool boundary). Only a race or an
older page can send that stop, since the page offers Stop only after the `202`. Tests send a stop
during a held write and during a held build that fails, then Send, whose first turn makes a tool call
and runs to `end`.

**Default taken 2026-10-09, the owner may revise** (a stop during a build that succeeds is kept); the
queue on the worker is owner decision 69A.

**Why**: VERIFIED `disposition` and `timing` refuse only through `_require_idle`
(`chat/server.py:1444-1468`, `1470-1483`) and write the live session (`record_disposition`,
`chat/sessions.py:328-371`, its save at `:357`; `record_timing_live`, its save at `:408`), through
`await run_in_threadpool(...)` without moving the chat out of its state. A `POST /send` accepted
during that await passes `_require_idle` and starts `send` on the chat's worker, so two threads
would save and change one session: Send's pre-write and withdrawal beside the decision's
`save_session`. The race exists today between a decision and an answer on an ended review, but
deciding and then pressing Send is this feature's expected flow. VERIFIED that the chat's worker is
already one thread per chat (`_submit`, `chat/server.py:2176-2184`, a `ThreadPoolExecutor` with
`max_workers=1`), so a write submitted there runs in order with Send and the apply, with no new
mechanism. The plan before 69A rejected this because "a decision queued behind a Send would wait for
the whole turn"; that cannot happen: a decision passes `_require_idle` only before Send has moved the
chat to `running` (`chat/server.py:2167-2172`), so it is always queued ahead of a Send, never behind
it. During an apply the chat is `running`, and a stop
request only sets a flag the apply never reads (`StoppableTools` wraps `run.tools`,
`chat/server.py:2145`; the apply restates through the registry's own dispatch,
`runner.py:1242-1263`), cleared in `_play`'s `finally` (`chat/server.py:2201`). VERIFIED
(2026-10-09, tasks review) that `stop` sets the flag whenever the chat is `running`
(`chat/server.py:1497-1498`), that `StoppableTools` (`:2145`) and `check_presentation_cancelled`
(`:2147-2149`) read it, and that `_play`'s `finally` is the only place that clears it, so a flag set
outside `_play` survives into the next turn. VERIFIED
(2026-10-09) that nothing in the pane calls the timing route (no `/timing` in `Review/ReviewPage/`
or the host): the four human inputs reach a waiting review through the API or the offline
`record_timing_at` (`benchmark/timing.py:90`), so the page gains no timing control, and a re-run
carries the four inputs whole (R2.17 step 4).

**Alternatives**: holding the waiting chat `running` for the write and clearing the stop flag by hand
in a `finally` (the plan before 69A: the turn state borrowed as a lock, three hand-written copies of a
no-await rule, and a flag a future path could leak into the next Send's first turn); a distinct
`busy` state for such work (every reader of `running` revisited in two languages: `_require_idle`,
the stop route, shutdown, `BackendClient.IsTurnRunning`, the transition table and the page); a
run-level lock held by `record_disposition`, `record_timing_live` and Send's commit half (a second
mechanism beside the worker every chat already has); holding `running` for every chat (moves a
ticked review's routes, which FR-035 keeps). For the stop flag: the stop route treating a run whose
`awaiting_send` is set as idle (it reads the run's state from the event loop while the worker changes
it, and a stop during a build that succeeds would then be dropped although the Send is in flight);
clearing the flag when Send is submitted (it would drop that stop too).

### R2.13 Answers while waiting: the same routes, no model call

**Decision**: `answer_evidence_batch` (both answer routes reach it) checks `awaiting_send` first. A
waiting run applies the answers exactly as today up to the resumed turn - validate, mark, the
confirmed drawing read, the part-roles regrade, `_restate`, the bought-parts rows - and then, in
place of `_ask`, ends in two helpers it shares with the re-run's carry (owner decision 71A):
`_settle_waiting(applied)` records each drawing file's outcome on the session (`drawing_outcomes`),
replaces the restated tools' calls in its pre-run result (`prerun.restated`) and marks the opening
as changed; then `close_waiting()` builds the Send cache (R2.8, *second review, 2026-10-09*) and
finalizes. One private `_apply_answers` holds the shared steps, so the resumed path and the waiting
path cannot drift (DRY). When `_play` then settles `awaiting_send`, it releases the SOLIDWORKS pipe a
confirmed read opened (R2.29). The summary's `resume_text` is "Applying your answers regrades the review by code.
Nothing is sent to the model." while the run waits, and the panel's button reads "Apply answers".
`POST /messages` on a waiting run is refused `409 NotSent`. (`contracts/review-flow.md` section 4.)

**An apply that fails** (*added 2026-10-09*): anything after validation that raises in the waiting
branch - the confirmed read, the regrade, `_restate`, the Send cache's build, the finalization's
writes - is caught by the branch, which (1) puts the record on disk back into the run
(`context.session = load_session(session_path)`), so the report and attention record `_play`
renders next are that record's; (2) emits one `error` event and no `turn.ended` or `session.ended`
(FR-010); (3) re-raises. `_play` moves the chat `running -> failed`, and `_close_out` writes nothing
because the record's `ended_at` is set. The page draws no error card for it: it restores the review
from its folder, as after a restart (FR-042) - read-only, with Send offered (owner decision 68A) -
with the error's line in the Send block, and its Send re-runs it (R2.17), the failed chat no longer
holding the folder. The page tells an apply's `error` from a Send's by the summary's `send` block and
`state.sending`, never by page memory alone, so a reload during the apply changes nothing (owner
decision 77A, R2.30).

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

**Decision** (*revised 2026-10-09*; Send the only trigger, *owner decision 68A*): a review restored
from its folder whose record says not sent (or send failed) is read-only with the Send block (R2.18;
the spec's question 4 answered with its alternative). Its Send - nothing else on it - sends the host
message `review.recheck {chat_id}`; the host, through `CreateReviewSession(..., ReviewMode.Recheck)`,
the body `review.start` uses too (owner decision 71A, R2.3) - refusing a drawing, another active
document (`ReviewNotActive`) and a stopped backend as `review.start` does - posts `POST /sessions` for
the review's own folder with `recheck: true` and `send_when_checked: false`, with the live bridge as
for any review, no dump, and the measured bound its mode has (owner decision 70A; "The host's
timeout" below). The backend:

1. claims the folder. A live chat on it that waits for Send (`awaiting_send`) is **adopted**: the
   call answers 201 with that chat's id and runs nothing - so a host that gave up on a re-run the
   backend then finished, and asks again, gets the finished one rather than `RunDirInUse` until a
   restart. Any other live chat is `409 RunDirInUse`, and so is a folder whose re-run is still
   running: since the chat is registered only after its finalization, the claim holds the folder
   itself until the call answers, so a host that gave up and asked again while the first re-run
   still ran never starts a second re-run in the same folder. With no live chat it reads
   `session.json` - the earlier record; none, unreadable, or not a waiting review's is
   `404 UnknownReview` or `409 NotWaiting`;
2. rotates by what the canonical stream is. When `events.jsonl` is the earlier record's own (its
   `session.started` names `session.json`'s `session_id`), as a retry does, except that
   `session.json` and `attention.json` are **copied** to index N, not moved, while `events.jsonl`
   and `tool-results/` are moved. When it is a failed attempt's stream, or absent (what a failed or
   killed re-run leaves), the stray stream and results move to their own index with no session file
   beside them, and the earlier record is not copied again (the attempt that left them copied it).
   Until the re-run's own finalization replaces it atomically, the canonical `session.json` stays
   the earlier record, so a failed, refused or killed re-run leaves the earlier record restorable
   with no recovery step, and every index holds a session with the stream it wrote or a failed
   attempt's stream alone. A `.session.json.<random>.tmp` a kill inside `write_atomic` left behind is
   passed over by the rotation, `GET /reviews` and the next re-run (76A's cut-off, R4.1);
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
   its identity differs from the earlier record's `model_status.profile` - another path, the same
   path edited, a profile added where the earlier record had none, or one removed - the change is
   named (step 4; *second review, 2026-10-09*, R6 question 3, kept by 68A);
4. carries, in memory only, the earlier answers, decisions, timing inputs and model status: each
   answered code question onto the re-run's question that asks the same thing (same question,
   options and entity ids - the rule the part-roles answer and the confirmed read already match
   by, extracted once as `checks/questions.asks_same`); the part-roles answer regraded by code; a
   drawing answer marked with no read and its outcome line carried, or - when its drawing is now in
   the package and its question not asked again - only its outcome line; each Accept, Reject or
   Defer onto the finding with the same `findings.finding_subject_key`, through
   `report/dispositions.set_disposition(..., at=earlier.at)` and the `disposition` event
   `record_disposition` emits, one function both call (owner decision 72A); two or more earlier
   decisions that match one re-run finding carried none of them, each named (72A); the four human
   timing inputs whole; the model status's state and failures whole, with `rechecked_from`; anything
   that matches nothing or more than one item named in one unresolved row, `coverage.recheck`, which
   also names a changed Standards profile and a drawing outcome an unfinished read lost (R2.13). The
   carry ends with `_settle_waiting(applied)`, the waiting apply's own tail (owner decision 71A), so
   `prerun.restated` replaces the restated tools' calls in `_prerun` and the opening a carried
   part-roles answer is sent with names no finding it withdrew (FR-023 and SC-005 on the restart
   path). The carry writes nothing to disk: it never calls `record_disposition`,
   `record_timing_live` or `save_session`;
5. ends through `_open_waiting` (71A, R2.6): `close_waiting()` builds the Send cache (R2.8) and
   finalizes - the re-run's one write of `session.json`, through `write_atomic` - then the render and
   `release_bridge()` (79A), then the chat is registered (R2.6's order), answers
   `201 {chat_id, review_session_id, not_examined}`, and is held in `awaiting_send`.

The host replaces its record of the review with the new chat, keeping its `ModelStatus` (owner
decision 73A), and replies `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined,
document}`; the page shows the new chat's snapshot and posts `POST /sessions/{chat_id}/send`
(`contracts/recheck.md`; `contracts/pane.md` section 7). Nothing is re-keyed: a read-only review held
no draft and no pending action, and Send names no finding or question (68A). If that Send is refused
(`NoCredential`), the review is a live waiting review, its questions and decisions usable.

**The host's timeout** (owner decision 70A, replacing "10 minutes, default"). The bound is measured,
not chosen. `reviewer/tests/perf/test_send_gate_perf.py`, under the repository's opt-in `perf` marker
(`tests/conftest.py`: collected only when `-m` names it), times on `test_prerun_perf.py`'s
thousand-group package a ticked start, an unticked start and a re-run with a carry, prints the
seconds, and asserts that the unticked start's added work (the cache, the finalization, the render)
stays a small fraction of the pre-run both starts share. When the larger measured re-run fits inside
30 s, this entry says so and one 30 s rule covers every call: `TimeoutFor` and `ChecksOnlyTimeout`
go. Otherwise `ChecksOnlyTimeout` is that re-run times three, rounded up to the next 30 s: the stated
margin, three because the seat's machine and a real assembly are not the development machine and
the fixture. The measuring task records the seconds and which of the two holds, here and in RK-10.
Until it lands, `ChecksOnlyTimeout` is the client's 30 s, so no unmeasured number is ever in force.
**Default taken 2026-10-09, the owner may revise**: the margin's value (three times the re-run,
rounded up to the next 30 s) and the interim 30 s until the measurement lands; 70A asks for a
measured bound with a stated margin and names neither. The [W] task times the unticked start and the
re-run on the small assembly and on the big one; a seat re-run longer than 30 s where the one 30 s
rule applies, or longer than a third of `ChecksOnlyTimeout` where it does not, sets the bound again
from that timing by the same rule, recorded here and in RK-10. The seat's unticked-start timing is
recorded for information only: 70A sets the bound from the re-run, and an unticked start runs the
checks a ticked start's call already runs inside today's 30 s, its live detection included, plus
the added work the perf test bounds.
*Measured value* (T098, 2026-10-14, the development machine, `uv run pytest -m perf -s
tests/perf/test_send_gate_perf.py`, six runs and one with the two starts swapped; each start timed as the host waits for it,
`POST /sessions` to its 201, on the thousand-group package with no seat): a ticked start
5.3 to 5.5 s (its pre-run 5.2 to 5.4 s); an unticked start 7.4 to 7.9 s (its pre-run 6.9 to
7.4 s, and the cache, finalization and render 0.39 to 0.61 s, at most 9% of that pre-run;
the test bounds it at 25%); a re-run with a carry, from a restarted backend, carrying a
Reject made while the first run waited, 7.4 to 8.8 s. The two starts' pre-runs differ by
order, not by kind: the second start in one process is about 1.4 s slower, and with the
unticked start first it was 5.3 s against the ticked start's 6.6 s. **The larger measured
re-run, 8.8 s, fits inside 30 s, so one 30 s rule covers every call**: `TimeoutFor` and
`ChecksOnlyTimeout` go, and every mode keeps `CallTimeout` (T103-T104). The [W] task's
seat timings set the bound again by the rule above if a seat re-run exceeds 30 s.

**Default taken 2026-10-08, the owner may revise** (the mechanism; 61A and FR-028 to FR-031 decide
the behaviour; the adoption, the carried step, the stray-stream rule and the decision key:
2026-10-09; the stale rows, the carried capability on the record and the profile in effect: second
review, 2026-10-09). Owner decisions of 2026-10-09: Send the only trigger (68A), the measured timeout
(70A), the shared tails (71A), the decision writer and the many-to-one rule (72A).

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
  `chat/server.py:2048-2055`), and without adoption every later Send on that review would be
  `RunDirInUse` until something restarted the backend. Adoption stays whatever the bound (70A).
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
  extraction, no live detection). One rule for both: the `Wait` and `Recheck` modes share
  `ChecksOnlyTimeout`, or the one 30 s rule when the measured re-run fits inside it. A ticked start
  keeps 30 s (FR-035).

VERIFIED (owner decision 70A, 2026-10-09): the host handles every page message on one pump thread and
`ReviewHost.Receive` is not re-entrant (`SwReviewAddIn.cs:1257-1289`; `ReviewHost.cs:257-264`), so the
box's save, Settings, the chips, `sessions.list` and Review on another document all queue behind a
`CreateSession` in flight; the bridge read has no enforced timeout (`bridge/client.py:240`;
`docs/review-backlog.md:2085`), and an unticked start makes the live call, so a hang holds the pump
for the whole bound. The review measured the added work on the fictional big-assembly fixture
(outside the repository): `save_session` 5 ms, `rank` up to 10 ms, the render 3 to 13 ms, the
attention record 1 ms, the tokenizer's first load 0.134 s once per process, 120k characters counted in
5 ms. The time that matters is the pre-run both starts share, whose own budget is 30 s at 1,000
groups (`tests/perf/test_prerun_perf.py:30-31`). A 10-minute bound would have held every page message
for up to ten minutes on a hang, with no measurement behind it.

Feature 014 stamps every step code makes with an `origin_mark` and counts a step without one as the
model's (014 `report/session.py`, `StepMark`): after the merge, the carried step carries
`origin_mark: "prerun"`, the code that first made the call (R3).

**Alternatives**: rebuilding a `ReviewRun` from disk with no re-run (the digest's live outcome and
not-evaluated families are not persisted, and the guard needs every pre-run payload in memory -
map 2, section 5); re-extracting (61A: no re-extraction); a restored review usable through a re-run,
whose first answer, decision or Send each re-runs it (the spec's question 4 default, which 68A set
aside: three triggers, and an id re-keying protocol across three layers - `carried` maps in the 201,
on the run and on the host's handle, the page's drafts and pending action re-keyed, a "no longer
applies" card, a `send.session_id` comparison for a re-run adopted after a reload); splitting the
restart into a feature of its own (it breaks 61A's restart clause on the hot no-key path, since saving
the key restarts the backend, and leaves a failed apply with no way back); 10 minutes for every call
with `send_when_checked` false (unmeasured, 70A); making the long work asynchronous, a `202` once the
folder is claimed (a feature of its own: it changes the start contract FR-035 keeps for ticked
reviews); a carried call with no step,
whose repeat is answered "ran in the earlier check run" with no step index (simpler, but the
re-run's session and report would show no live-detection step and every later index would move);
keeping `_verdict_key` and naming the coaxiality limitation (it leaves a decision the engineer made
uncarried for a reason the key, not the design, creates); grading a re-run against the first
run's profile (the record holds its identity, not its content, and the file may have changed);
refusing a re-run whose profile changed (the engineer's next action on the review would fail for a
setting they meant to change, and a fresh Review would lose the answers and decisions 61A keeps).

### R2.18 A restored not-sent review is shown read-only, with Send and its age

**Decision** (*owner decision 68A*, replacing "shown usable"; the composed line, *owner decision
73A*): `GET /reviews/{run_id}` answers a not-sent (or send-failed) record read-only, as it answers
every record today, with two differences. Its `read_only_reason` is the words file's
`read_only_lead` ("The backend restarted, so this review is shown from its run folder."), a space,
and `send.restored_line` ("Its checks ran {when}; Send checks the saved evidence again first."),
composed by the backend. `read_only_lead` is a key of its own: feature 009's `read_only` key is held
as its two sentences, `read_only_lead` and `read_only_off` ("Follow-ups, decisions and answers are
off."), and `Words.read_only` composes them, so every other restored review shows 009's sentence word
for word (`contracts/words.md` section 1). And its summary carries the
`send` block in state `restored`: the size sentence without a number, the re-run failure sentence
the page prints if a re-run fails, and the failure line of a `send_failed` record. The page prints
the line in `#read-only` as it prints every read-only reason, keeps the questions panel, the decision
buttons and the follow-up box off as on any read-only restore, and enables Send alone, which goes
through `review.recheck` first. A sent record restores read-only as today, with today's sentence.
(`contracts/recheck.md` section 8, `contracts/pane.md` section 7.)

**Why**: VERIFIED `_read_review` passes the words file's read-only sentence for every folder
(`chat/server.py:1677-1682`) and the snapshot carries it (`report/snapshot.py:57-75`); the page
prints it under the status line (`app.js:1466-1470`, `index.html:162`). One line, one element. 73A
composes the restored line from a `read_only` lead key, so the lead sentence lives once and the two
lines cannot drift; splitting the key keeps `Words.read_only`'s value, so `_read_review`'s sentence
for every other record (`chat/server.py:1681`) and the tests that read it
(`test_chat_review_routes.py:179-182`, `test_review_snapshot.py:84-87`) are unedited. 009's second
sentence is left out of the restored line, as 73A words it: the questions panel, the decisions and
the follow-up box are off as on any read-only restore, and the Send block says what Send does. The
`send` block carries no `session_id` (it served only the re-keying 68A drops) and no restored line
(the line is the snapshot's `read_only_reason`).

**Alternatives**: a restored review usable through a re-run, its line saying "its next answer,
decision or Send checks the saved evidence again first" and 009's sentence not shown (the spec's
question 4 default before 68A); a `send.restored_line` that repeats 009's first sentence word for
word (two copies of one sentence, the plan before 73A); the restored line as 009's whole `read_only`
sentence followed by the dated sentence, no key split (a reading of 73A the amendment first took,
withdrawn on its review because 73A names a lead key: it would have put the owner's decision aside on
an unconfirmed reading).

### R2.19 A restart while a waiting review is on screen

**Decision**: after an `init` that names a different backend (a Settings save, or a restart after
`backend.stopped`), the page restores the review on screen from its folder at once when it was
waiting - read-only, with Send offered (owner decision 68A) - through the same path a chip uses when
the chat is gone (FR-042). A draft answer typed before the restart goes with the live chat. Reviews that were not
waiting keep feature 009's rule (restored when chosen).

**Why**: VERIFIED the page re-asks `init` after a save (`app.js:2554-2561`) and holds the old chat
id; its next live call would be refused `UnknownChat`. `showReview`'s fallback to
`GET /reviews/{run_id}` is the restore path (`app.js:1378-1404`).

### R2.20 Finding a not-sent review after SOLIDWORKS reopens

**Decision**: `sessions.list` first looks, when the active document is a part or assembly this
host holds no review of, for that document's newest review in the run root: the folders whose
names carry the document's name (`RunFolders.DocumentName`, with the collision suffix, check,
standards and remodel folders skipped), newest by the name's timestamp; only the newest is read,
and only the head of its `session.json` (64 KiB, `Utf8JsonReader`, stopping at `model_status`),
through `RunFolders.ReadModelStatus` and its injectable head opener, whose default is a `FileStream`
with `FileShare.ReadWrite | FileShare.Delete`, the buffer filled by `PackageIndex.FillHead`, the
bounded fill loop extracted from `PackageIndex.HeadOf` so both readers call one (owner decision 80A).
It is tracked as a kept review - its chat id the record's `session_id`, its time `checked_at`, its
item carrying `model_status` - when that record says not sent or send failed **and** names this
document's full path and configuration. A newer folder with the same name that is not such a record
(a review sent at once, a failed check run, another document with the same file name) offers
nothing. The page asks `sessions.list` again on `document.changed`, after following with the list it
has, and follows again with the answer by the same rule (*tasks review, 2026-10-09*), as it already
does after `init` (`requestSessions(true)`, `app.js:2611`; the function at `:1248-1258`). A found review of the active
document is therefore shown, restored from its folder, whether the pane loaded before or after the
document was opened. A chip of a review found this way names the date when it is not today.
(`contracts/recheck.md` section 9.)

**Default taken 2026-10-08, the owner may revise** (the spec's question 2 default, kept by owner
decision 68A, and "the newest same-name folder decides"). **Default taken 2026-10-09, the owner may revise** (the second follow).
Without it, the review would be shown at once when the pane loaded after the document opened, and
only as a chip when it loaded before. FR-030 says "the Review tab then shows that review".

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

VERIFIED (owner decision 80A, 2026-10-09): `HeadOf` opens with `FileShare.ReadWrite` only
(`extractor/SwReview.Extractor/Dump/PackageIndex.cs:269-273`), and on Windows a reader without
`FileShare.Delete` makes a concurrent `os.replace` of that file fail - and 015 sends every
`save_session` through `write_atomic` (`contracts/records.md` section 8), while an orphan of an
unticked start the host gave up on is a folder the backend still writes and the host has no record
of; the add-in already opens backend-written files with `ReadWrite | Delete`
(`Remodel/BackendRemodelPipeline.cs:461`, `Terminal/TerminalHost.cs:1068`). A 2 s timer cannot prove
"names first, one head read": a naive scan of 500 heads fits inside it (`load_session` of the 656 KB
fictional big record takes about 10 ms), so the access pattern is pinned by a counting opener - one
file opened, the newest - and a stream that throws past 65,536 bytes proves the cap; the 2 s bound
stays a plain `[Fact]` (precedent `ReviewPageScaleTests.cs:85`). The same reader refreshes every
marked record on `sessions.list` (owner decision 73A, R2.21): one bounded read per waiting record,
none for a ticked one.

**Alternatives**: the backend searches (it may not be running yet, and it does not own the folder
names); reading every same-name folder's package (the cost FR-030 forbids); a sidecar file per run
folder (a second record of one fact).

### R2.21 The page


**T077 acceptance measured 2026-10-13.** After the corrected T075/T076 candidate passed
all 38 Send cases and its required full gates, the real backend's
`failed_send` snapshot in `review-waiting-big-assembly.json` was restored at 300 by 600.
The headline, tally, not-reached line and Send to model button all satisfy SC-007. The Send
button's bottom is 153.4375 px above the window edge; the not-reached line's is 199.828125 px.
The session buttons occupy two rows and the box remains directly below them. The exact backend
failure sentence renders without an error card. Its bottom is 41.09375 px above the window edge,
but the scrolling Results viewport initially clips 7.296875 px of the note (`h.inView` is
false). Ordinary scrolling of `#results` by 8 px makes the exact whole note visible
(`h.inView` is true), so this is accessible scroll content. SC-007 requires the summary's
three lines and the Send button, which remain in view at the initial scroll position. No page or shared asset
changed after the acceptance test was authored, and no layout fallback was made. The new case
and the four unchanged T056 cases pass. The raw fixture SHA256 is
`b3d5c881cdfae89aade0e2234c080e5ac3e5e0fbb926431f70abc5505351946f`.

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
  (R2.10, *second review, 2026-10-09*), and the same after a reload, through the snapshot's
  `send_in_flight` (owner decision 77A, R2.30);
- a restored waiting review is read-only, as feature 009 restores any review, with the Send block's
  Send its one control (owner decision 68A, R2.18);
- the status line gains "Checked by code. Not sent to the model." and "Checking the saved evidence
  again.", page words read from page state, ahead of "Waiting for your answers." (FR-033);
- the questions panel's button reads "Apply answers" while the review waits; its sentence is the
  summary's `resume_text`;
- the follow-up box is disabled while the review waits, its placeholder saying it has not been sent;
  Stop is disabled while the review waits or is being checked again;
- the transcript's first line for an unticked review says it ran the code checks only; each
  `session.sent` adds "Sending to {provider} {model} ...": the event comes before the attempt's
  record, which can still fail (owner decision 72A);
- the Settings section shows one line while a review waits; the no-key note becomes a sentence true
  for both box states;
- a chip carries " · not sent" while its `sessions` item carries `model_status`: the host's record
  is the one source of the mark (owner decision 73A, R6 question 1), set at an unticked start, kept
  by a re-run, set for a found review and refreshed on every `sessions.list` by one bounded head read
  per marked record (R2.20), so it is exact after a page reload; the page drops it at once at the
  review's first `usage` after Send, until the next list agrees.

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

**T056 waiting measurement, 2026-10-12.** The real backend-generated
`review-waiting-big-assembly.json` preview from T053, with 13,388 first-request tokens and
no code questions, was played into the implemented page in offscreen WebView2. Its raw SHA-256
was `e59826c40117bf139eeb04126453327d8cd3359b1b6f35dec8d65bcf9a9f0eee`.
T054 passed all 14 cases on the real waiting fixtures before the unchanged T056 assertions
ran; T056 passed all four cases. No layout rule was changed to obtain this result. The
headline, tally, not-reached line and Send to model button were all in the 300 by 600 viewport.

| Viewport | Session button rows | Not-reached slack to fold | Send button slack to fold | Horizontal overflow |
|---|---|---|---|---|
| 260 by 600 | 3 | 164.4375 px | 118.046875 px | none |
| 300 by 600 | 2 | 199.828125 px | 153.4375 px | none |
| 420 by 600 | 2 | 236.71875 px | 190.328125 px | none |

At 300 px the button row ended at 182.046875 px and the box began at 186.046875 px,
directly below it. This measures the US1 waiting state; the later failed-Send and restored
states remain their own acceptance work. Parent integration regenerates the accepted T053
fixtures and requires raw equality with this preview before its final pane/full gate.

### R2.22 Where the words live

**Decision**: every sentence the Send block, the summary and the questions panel print comes from
the words file (`review_words_v1.yaml`, a new `send:` block and five `labels.errors` keys, and
feature 009's `read_only` key held as its two sentences, `read_only_lead` and `read_only_off`, owner
decision 73A); the
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

**How it is pinned** (*tasks review, 2026-10-09*). VERIFIED that no test asserts the command's
printed lines (`cli.py:774-780`): `test_cli.py`'s review tests (`:409-810`) assert exit codes,
the files written and `--json` values, and no test in `reviewer/tests` reads a "reviewed ... with"
line; the characterization (R2.28) drives `POST /sessions`, never the command. One case in
`test_runner_send.py`, written with the first unticked start's tests, runs `swreview review` through
`test_cli.py`'s own helpers and asserts the four lines as literals, the ten `--json` keys
(`cli.py:758-772`), and no option for the box. It is green on the code before the first unticked
start, and `test_cli.py` is not edited.

### R2.24 The handoff export says whether the review was sent (added by this plan)

**Decision**: the handoff bundle's session summary gains `model_status` (the state only) when the
session carries one; nothing else in the export moves. 002 `contracts/handoff-export.md` is amended.

**Owner decision 73A** (R6 question 2, its default kept on 2026-10-09).

**Why**: VERIFIED the export copies `provider_info` (provider, model, effort, key source) into its
summary (`handoff.py:391-401`); for a never-sent review that names a provider as if it had run,
which FR-032 forbids of the saved review. FR-038 lets the plan add a contract it finds.

### R2.25 Fixtures

**Decision** (*revised 2026-10-09*): the pane fixture (`review-big-assembly.json`) keeps its
snapshot part byte for byte; its labels block gains the five error keys only (FR-035). The snapshot
gains one optional key, `send_in_flight`, written only while a Send is in flight and omitted
otherwise (owner decision 77A), so no committed snapshot moves. Every fixture
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
  `waiting` (the live snapshot, its size sentence counted), `sending` (the live snapshot while a
  Send is held, taken inside the scripted provider's first request, so it carries
  `send_in_flight: true`; owner decision 77A) and `failed_send` (the live snapshot after a Send
  whose scripted first request failed, with its failure line);
- `review-waiting-restored.json`, from the same package: `restored` (the run-folder snapshot of
  the record with nothing answered: read-only, its composed line and the `restored` Send block) and
  `rechecked` (the re-run's `POST /sessions` answer and the re-run's live snapshot), which the page
  shows before it posts Send. No snapshot of an answered record and no id maps (owner decision 68A:
  the page re-keys nothing);
- `review-waiting-big-assembly.json`, from the fictional big-assembly package, for the layout tests
  only (the worst case for height): `waiting`, `failed_send` and `restored`.

Every clock the generator's reviews read is pinned to a fixed fictional time - the runner's
`datetime` and `utc_now` the way `tests/unit/test_finding_explanations.py:366` pins them, and the
one new `local_now` (R2.15) - so a fresh generation is byte-identical on any machine, in any zone,
on any day. `tests/unit/test_pane_waiting_fixtures.py` fails when a committed file differs from a
fresh generation (the precedent `test_pane_drawing_fixture.py`), and the three files, with the
generator's fourth, `review-not-sent-session.json` (the earlier record's `session.json` for the
host's cross-language head read, R4.2), join `test_replay_fixture_hygiene.py`'s list of committed
fixtures, as `review-big-assembly.json` is (FR-039). Every replay fixture is untouched: no change here moves what a review sent at once tells
the model, which R2.28's characterization and its regeneration step hold the code to.

**Why**: VERIFIED the pane fixture is `review_snapshot` of the big-assembly replay fixture plus the
words file's labels (`tests/fixtures/pane/generate_pane_fixture.py`), and that the summary block and
snapshot keys are serialized whole: so `send` must be omitted when absent, and a snapshot key may be
added only when it is omitted at its default (`send_in_flight`, owner decision 77A, R2.30). Page tests read backend-made fixtures, never hand-built shapes (feature 009 research
R2.24). VERIFIED (2026-10-09) that the big-assembly package raises no code question: the four
questions in `review-big-assembly.json` are all `source: "model"`, and a checks-only review of the
package raises none (the plan's review ran `start_review` with the pane defaults: 104 findings,
`evidence_requests == []`), so a waiting fixture built from it alone would leave "Apply answers"
and the status line's precedence over "Waiting for your answers." (FR-033) with nothing to test. VERIFIED that the restored line's `{when}` is `checked_at`,
the first finalization's end - "now" at generation - so it must come from a pinned clock and
render with no reference to the generating machine's zone (R2.15).

### R2.26 Other tabs and paths are untouched

**Decision**: Model check, Standards, Remodel, the Ask tab and the Settings model list are not
governed by the box and do not change (spec, Edge Cases, last item). Nothing in this feature adds a
tool, a bridge command, or a write to any document.

### R2.27 The Send turn starts from the coverage a ticked review starts from (added 2026-10-09)

**Decision**: `ReviewRun.send`, after it emits `session.sent` and saves the attempt and before
`_say`, withdraws - through `withdraw_finalization(session, _finalized)`, the body `finalize_session`
runs at its start, extracted and called in place in the commit half (R2.10, owner decision 72A) - the
rows the run's previous finalization appended - the close-out row, one
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
   and committed on the recorded pre-015 baseline, including accepted 010 before the pins
   (2026-10-12 re-check; `review-2026-10-12.md`), before any 015 refactor, in one commit. It drives ticked reviews through the chat server's
   `TestClient` app (`test_chat_server.py`'s fixtures), with the recording provider below scripted,
   on the fictional questions package (R2.25), in **five scenarios, each with its own golden** (owner
   decision 75A), so the failures of a ticked review are pinned to the old code as its success is:
   1. **success**: the opening turn; one answer to the part-roles question that resumes the model
      (the path `_apply_answers` will hold, with `REGRADED_LINE`); one follow-up; and the explanation
      pass after each turn that ends `end`. It is posted twice, once with no new key in the body and
      once with the body the host now sends, `{send_when_checked: true, recheck: false}` (what
      `BackendClient` writes for `ReviewMode.Send`, R2.3), and both runs must equal one golden;
   2. **a ticked start whose factory raises** (no key): the status, the body and the run folder's
      listing;
   3. **a first request that raises before any round**;
   4. **a failure after one completed round**, through a small raising wrapper over the recording
      provider;
   5. **Stop at the first tool boundary**.

   Each golden holds every provider `run()` input (the system prompt, the encoded tools, the encoded
   messages) and every presentation request's input, in order; `events.jsonl`; and `session.json`,
   `report.md` and `attention.json` where the scenario writes them - with times, durations and UUIDs
   replaced by placeholders in order of first appearance. Timestamp/UUID identities are kept;
   each duration occurrence gets its own number because equality of measured float values is
   volatile. One fictional monotonic clock is injected through the existing event, runner and
   tool-context clock seams, keeping equal stored timestamp values equal without accidental
   wall-clock collisions. The real provider requests, tool dispatch and raw output bytes are
   still captured. The harness also replaces only its
   explicitly supplied scratch run directory and profile file, including their JSON-escaped
   forms, with `<RUN_DIR>` and `<PROFILE_PATH>`. Matching requires complete quoted values or
   complete lines: unknown sibling prefixes, names containing spaces or commas, descendants
   and profile backup names remain visible, as do `C:\Fictional\` evidence
   paths and every stable count and word. Duration normalization covers the named JSON fields,
   the unattended-runtime line and, only in the captured `report.md`'s `Investigation Trace`
   section with its exact `Elapsed (s)` header, the elapsed-seconds column. It leaves the
   table's index, tool and status columns and all lookalike tables elsewhere unchanged.
   Raw UTF-8 file strings retain
   their actual CRLF/LF bytes: `read_bytes`, never newline-translating `read_text`. The separate
   normalizer test pins these rules before capture (2026-10-12 baseline preparation).
   Every later commit keeps all five
   byte-equal; they run in the gate. The shape checks that would have duplicated scenarios 2 and 3 on
   code that had already changed (a ticked no-key `502` in the unticked start's test, a ticked failed
   first request in the failed Send's test) are not written.
2. **The prefix characterization**, `tests/unit/test_request_prefix_characterization.py` (a
   `data_regression`): for each of the three committed replay fixtures, under the pane defaults, the
   sha256 and the length of the first pass's `PlayedReview.prefix`. Committed before `_prefix`
   moves; the commit that moves it into `request_prefix` must reproduce all three (R2.9).
3. **The replay regeneration step**, on a machine that holds the owner's recordings mapping
   (`%LOCALAPPDATA%\SwReview\recordings.json`, read by `tests/support/recordings.py`): 008
   `contracts/replay.md` section 8's unchanged-fixture recipe: `uv run python
   tests/fixtures/replay/verify_regeneration.py` from `reviewer/`, which seeds only the committed
   runtime inputs while calling the unchanged generators and self-checks; then from the root the
   literal `git diff --exit-code -- reviewer/tests/fixtures/replay`, comparing raw bytes against
   the baseline. Every pass consumes its exact runtime-input budget; no output is normalized or
   rewritten, and stable payload changes remain visible. An unseeded generator run is not claimed
   byte-clean. Where the mapping is absent the step is skipped, naming why. It
   runs at the gate of every phase that changes the runner, the pre-run, a provider or the records,
   and at the final gate.

**One recording provider.** `RecordingProvider` moves from `tests/unit/test_prefix_stability.py`
(`:113-156`; it records before the turn runs, so a turn that raises still contributed its input,
and it encodes the tools and the history as the OpenAI adapter does) to
`tests/support/recording_provider.py`, gaining `for_presentation`, which records the presentation
request the same way, and keeping beside each `run()`'s encoded bytes its raw inputs - the system
prompt, the tool specs and the first message - so a test can count `request_prefix(...)` of what the
provider received and hold the estimate shown before Send to it (owner decision 78A, R4.1);
`test_prefix_stability.py` imports it, its assertions unchanged. The characterization, SC-004's and SC-008's every-request comparisons, R2.14's three pins and the
waiting-fixture generator all use it, and 015 adds no other.

**Why**: before this entry every comparison the plan made ran new code against new code - an
unticked review that was sent against a ticked one, both on the 015 code (SC-004, R2.14) - while the
plan refactors the ticked path itself, its failure paths included (`_start_review`'s factory call,
`chat/server.py:2110-2114`; `_run_turn`'s `except` branch, `runner.py:1434-1442`; `_play`,
`chat/server.py:2186-2208`), which only shape tests pinned before 75A (`test_chat_server.py:1905`,
`:2027-2045`). The pre-feature server reads the body with `.get` and ignores keys it does not know
(`chat/server.py:1230-1236`), so the host's real body can be captured on the pre-feature code (75A).
The paths refactored: `configure_provider`, the `effort_mapping_for` delegations,
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
characterization's five goldens on the first-merged side alone - `main` after the first merge, without the
second branch's code - commits that in the merge, and the merged code must pass it unchanged; and,
on the machine with the recordings, runs the regeneration step against the other branch's
fixtures (R3).

**Alternatives**: comparing an unticked review that was sent with a ticked one on the new code only
(both can drift together); pinning the first request alone (the resumed answer, the follow-up and
the explanation pass run through code this plan refactors); a characterization on the
big-assembly replay fixture (it raises no code question, so the answer path would go unpinned); the
success path alone, posted with no new key (the plan before 75A: the four ticked failure paths this
plan rewrites, and the body the host actually sends, would never meet the old code); adding only the
host's body to the success path (75A's option B: the failure half of "today's behaviour, byte for
byte" left to shape checks written on changed code).

### R2.29 A waiting review holds no SOLIDWORKS pipe (owner decision 79A, 2026-10-09)

**Decision**: `ReviewRun.release_bridge()` closes the context's bridge transport and keeps the
client. It is called at the end of an unticked start and of a re-run, before the chat is registered
(`_open_waiting`, R2.6), and by `_play` whenever it settles `awaiting_send` - after an apply, or
after a Send that failed before any round. The named-pipe transport opens again on its next request,
so a confirmed drawing read while waiting, or the first live tool after Send, reconnects, and the
client's circuit breaker and cached drawing-read answer survive. A ticked review's pipe is today's.
Tests run a real `BridgeClient` over a fake transport that counts the pipes it opens: five unticked
assembly reviews waiting in one backend hold zero pipes; Send's first live tool opens one; T007's goldens stay byte-equal.
(`contracts/review-flow.md` section 8.)

**Why**: VERIFIED (2026-10-09) that each review builds its own `BridgeClient`
(`agent/runner.py:1583-1586`), whose `NamedPipeTransport` opens the pipe on its first call and keeps
it open (`bridge/client.py:237-238`, `:256-261`); that the only close is `ReviewRun.close()`
(`runner.py:1386-1390`), reached only at shutdown (`chat/server.py:2327-2334`), and chats are never
removed from `ChatServer.chats` (`:1189`); that an assembly review with SOLIDWORKS attached opens
the pipe in its pre-run's live detection (`prerun.py:1239-1251`); and that the add-in serves at most
four pipe instances (`ToolService/InProcPipeServer.cs:394-398`), its accept loop returning for good
when the next listener cannot be made (`:739-747`). So without the release, a few checks-only reviews
waiting at once - which 015 makes cheap, and which the spec names as an edge case - could stop the
tool service for the rest of the SOLIDWORKS session. `BridgeClient.close()` closes only the
transport (`bridge/client.py:569-571`).

**Out of scope**: the older ceiling on every chat (`docs/review-backlog.md:336-337`, `:436-437`): a
sent review still holds its pipe once its first live tool opens it, and the accept loop still
returns for good. That limit predates 015 and touches the ticked path and the add-in's tool service,
so it is left to a separate change.

**Alternatives**: releasing the pipe on every settle and making the accept loop back off and retry
(the real fix of the older ceiling, out of scope above); doing nothing (after the third or fourth
waiting review, every later live tool and drawing read would read as "SOLIDWORKS not attached").

### R2.30 A reload during a Send or an apply (owner decision 77A, 2026-10-09)

**Decision**: the snapshot carries one optional key, `send_in_flight: true`, exactly while the run's
`_send_in_flight` is set - from the send route's acceptance to the Send's first round, or to the
guard's or the failure branch's return to waiting, each clearing it before its `error` - and omits it
otherwise, so a ticked review's snapshot, a waiting one's and the pane fixture keep their bytes. The
page's restore sets `state.sending` from it. The apply-failure rule is keyed on the summary's `send`
block with no Send in flight. Four page cases pin it: a reload while a Send is held, then a failed
send; the same with one `error` and nothing after it; a reload during an apply that then fails; and
the chip's mark after a reload (R2.21). (`contracts/pane.md` sections 3 and 5.)

**Why**: VERIFIED (2026-10-09) that a reload of a running chat restores from the snapshot, marks the
turn running and reopens the stream after the snapshot's last `seq`, reading every later event as
live (`app.js:1412-1434`); that a live `error` draws the error card (`app.js:551-555`), which always
offers Retry (`render.js:749`); and that during a Send the summary carries no `send` block once the
commit half runs (R2.11). So with `state.sending` in page memory alone, a reload during a Send - the
longest window, since a reasoning model's first round can take a minute - would draw the error card
with Retry for a key the provider rejects, and for a Send that failed before any request would leave
no Send block at all, against the spec's edge case.

**Alternatives**: testing only the apply reload and the chip, recording the Send reload as a known
limitation (Retry after a rejected key would extract again into a new folder); doing nothing.


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
contracts/cli.md` - is neither changed nor relied on by 015.

**Re-checked 2026-10-12.** At `ee6571c`, the only shared file changed since `45b5076` is
`tests/support/mechanical.py`, adding the M6 socket-head dimensions. This does not replace the
intersection required at the actual integration head. The earlier claim that `smart_SW-fp` touched
only feature 010 documents was stale: `010-fine-pitch` at `7fcbf66` changes 68 files against
`838b66b`, including `agent/runner.py`, the mechanical tools and their registry, the words and
attention policy, the shared mechanical and pre-run builders, replay assertions, and contracts
015 amends. Integrate the accepted 010 change before T007-T008 and re-verify the causes; otherwise
the characterizations would freeze superseded ticked behavior. No 015 product change is allowed
before those pins. The exact integrated baseline and verification are recorded in
`review-2026-10-12.md`; the accepted baseline is now `c93c86a`, integrating `main`
`017ba0ac` (010 `a5b4ed8`, combined integration `7ebd4ae`, 014 goldens `48049bf`, T158
receipt `017ba0ac`). The historical table remains the file map for the original review.
At this actual head the additional shared changes since `45b5076` include 010's
`agent/runner.py` pre-run/thread-tool wiring, `report/review_words_v1.yaml`, the mechanical
registry/tools and the `tests/support/mechanical.py` and `tests/support/prerun.py` builders,
plus the owning 008 answer-batch/checks-first/replay contract updates. None is replaced by
015: new steps/offsets derive from actual dispatch, words are extended, and the existing
helpers are imported. The other later changes are 014 probe helpers/goldens that 015 does
not edit. The four merge conflicts were amendment-note placement only; both 014 amendments
and 015 notices were preserved. Reuse 014's atomic writer and eleven tests, skipping
T009-T010. Each later implementation re-verifies its historical cause at this baseline.

---

## R4. Tests

Test-first (62A, Principle III): every implementation task follows a failing test task. The new
tests, by layer, with the edge cases each covers; then every existing test that moves and why.

### R4.1 New reviewer tests (`reviewer/tests/unit/`)

| File | Covers (spec edge cases and requirements) |
|---|---|
| `test_send_gate_server.py` (route level, `TestClient`, `ProviderControl.built` must stay empty; every recorded request read from `tests/support/recording_provider.py`, R2.28; every crash and restart case through `tests/support/restart.py`, owner decision 76A) | checks-only start with no key: 201, `awaiting_send`, no provider built, no `turn.ended`, `session.started.send_when_checked` false, `session.ended`, `session.json` model status, and `report.md` already on disk with the not-sent header when the 201 arrives (`_render_run`, R2.6) (FR-006 to FR-010, US1-1, US1-2); the unticked start ends through `_open_waiting` and `close_waiting`, the only caller of `build_send_cache` there (one build per start; owner decision 71A), and finalizes before it registers: a cache build or finalization that raises (`write_atomic` raising) answers the error body, registers no chat, and leaves the folder claimable (R2.6); an unticked start on an unreadable package answers `InvalidPackage` as today, with no provider built and no chat registered (the spec's "checks of an unticked review fail"); **no pipe held while waiting** (owner decision 79A, R2.29): with a real `BridgeClient` over a fake transport that counts the pipes it opens, five unticked assembly reviews in one backend hold zero once each 201 arrives, the client kept; a ticked review's no-key `502` and its failures are pinned by the characterization (R2.28 item 1, owner decision 75A), never by a shape check here; `send_when_checked` not a boolean, and `recheck` with `send_when_checked: true`, are 400; Send's refusal order (UnknownChat, SessionFailed, TurnRunning while answers apply, a second Send in flight, NotWaiting for a ticked or sent review, NoCredential with no key, none for an environment key, a Gemini enterprise project or the scripted provider - each leaving the chat waiting, FR-016, FR-018); **the adapter built inside Send** (owner decision 69A): the route answers `202` before the factory runs, and a factory that records its thread sees the chat's worker, never the loop; **a Send that fails before any request** (R2.10), at each of its five points - the factory raising, `configure_provider` raising, the effort mapping raising, the `session.sent` emit raising, the pre-write's `save_session` raising - each: no provider `run()` recorded, one `error` event and no `turn.ended` or `session.ended`, the chat back to `awaiting_send` (the page is not left waiting), `session.json` byte-equal to the record before Send with no `Interrupted` entry, the Send block's failure line from `send.not_started`, the pipe released again, and a second Send that succeeds; and with the guard's own `error` emit raising too, the failure logged and the chat still `awaiting_send` (owner decision 72A); **a decision queued on the worker** (`record_disposition` held on the chat's worker, owner decision 69A): the chat reads `awaiting_send` throughout, `POST /send` is accepted and its Send runs only after the write returns (the decision's save before `session.sent` in the recorded order), and in another case `POST /evidence` is accepted and applied after it; the same with the timing route and `record_timing_live`; a held write that raises answers its error and the Send queued behind it still runs (R2.12); **a stop during a held write** answers `202`, writes no event and sets no flag; **a stop during a held adapter build** answers `202` and writes no event: when the build then fails (the guard's case), `_play`'s `finally` clears the flag and the next Send's first turn, which makes a tool call, runs to `end` with no `stopped` turn and one presentation request; when it succeeds, the stop is today's (R2.12); **the snapshot's `send_in_flight`** (owner decision 77A, R2.30): `true` from the route's `202` to the first `usage`, and from the `202` to the guard's or the failure branch's return to waiting, each clearing it before its `error`; omitted otherwise, a ticked chat's and an idle waiting chat's snapshots carrying no such key; **every request of Send's first turn byte-identical to a ticked review's**, tool results included, with a scripted first turn that calls `mark_coverage`, `request_evidence` and `get_review_checklist` (SC-004, US2, R2.27), and the same comparison after a failed Send and after a re-run with nothing answered; **the size shown is the size sent** (owner decision 78A): `count_tokens(request_prefix(<the recorded raw system prompt, tool specs and first message>))` equals `summary.send.input_tokens` read before Send, `session.sent.estimate.input_tokens` and `model_status.estimate.input_tokens`; Send's first live tool opens the pipe again (79A); after an apply while waiting, the session at the first request holds no row of any earlier finalization (no close-out, no unresolved row of an open question or item), so `get_review_checklist` and every `open_items` show each model-owned item with no finding as open (R2.27); a failed first request returns to `awaiting_send`, records the failure, and a second Send resends the opening once (FR-017); a failed Send, then an apply, then Send sends the rebuilt opening once (FR-017); a failure after a round is today's (FR-017 last sentence); after Send with a turn ending `end`, exactly one presentation request (R2.14); `POST /messages` is `409 NotSent` while waiting and `202` after the first `usage` (FR-019); an answer to a question the model asked after Send resumes the model with today's `ANSWER_MESSAGE` and `REGRADED_LINE`, byte for byte against the same answer in a ticked review (FR-015, R2.14); Stop while waiting writes no event and sets no flag (FR-025); shutdown while waiting writes no event, shutdown during an apply writes none (FR-010); a decision and timing while waiting are saved and kept at Send (FR-024); several reviews waiting at once each send alone; the `send` route is in `ROUTES` and refuses no token |
| `test_runner_send.py` (runner level) | `configure_provider` sets the three hooks as `start_review` did; `attach_provider` numbers steps from the session's count; the frozen opening is sent when nothing applied, the builder reproduces it byte for byte (SC-004); the Send cache (R2.8): built by `close_waiting` alone (71A) at the unticked start, after an apply and after a re-run's carry, each on the worker; its opening equal to the opening built again after the finalization; the attention and snapshot routes and `send` never build it (a builder patched to raise once the cache exists leaves both routes `200` and Send working); Send's order (R2.10, owner decision 72A): nothing in the session or on disk changed by the prepare half (the adapter's build included), `session.sent` before the pre-write, the pre-write before the withdrawal, the run's `_finalized` list empty after it; `withdraw_finalization` is the body `finalize_session` runs at its start (`finalize_session` calls it, T007's goldens byte-equal) and Send's commit half calls it in place; **crashes, as the folder a crash leaves** (owner decision 76A): `disk_at` copies the run folder inside the scripted provider before its first `usage` - the copy says `send_failed` with "the backend stopped before the model answered" (RK-7), its read-only restore with the restored Send block pinned in `test_chat_review_routes.py` once that block lands - and again after the first `usage`'s save - the copy says `sent`, `ended_at` null, with no row of the checks' finalization, which `GET /reviews` of a restarted app reads read-only as a sent review (R2.11); the wait is not running time (FR-011); not-sent checklist reasons, answered-but-open reason (FR-009); `opening_finding_ids`; the model-status times stamped by `local_now` and rendered as stored: a record whose `checked_at` carries `+05:30` renders that wall clock in `{when}`, whatever the zone running the test (R2.15) |
| `test_deferred_provider.py` | name, model and the effort mapping equal each adapter's for every effort and for a model with no table row; an effort the model refuses raises the adapter's own error at setup; `run` and `for_presentation` raise `ProviderNotSent`; **no key read and no SDK client constructed** (owner decision 74A): with `openai.OpenAI` and `google.genai.Client` patched to raise and settings whose key raises when read, `for_settings(...)` and its `effort_mapping(...)` succeed; the SDK module itself may be imported, because the effort rule lives in the adapter module, and the test asserts nothing about module imports |
| `test_send_estimate.py` | `request_prefix` moved byte for byte, proven by the prefix characterization committed before the move (`test_request_prefix_characterization.py`, R2.28), which the moving commit keeps green - never the function compared with itself, and never `test_replay_fixtures.py`'s totals, which read no prefix (R2.9); the estimate is the count of the cached opening and is recounted, in the cache, after an apply (FR-013); `None` with the vocabulary absent, by `monkeypatch.setattr(tokens, "encoding", <raises TokenizerUnavailable>)` (the precedent `test_step_sizes.py:166-171`; `tokens.encoding` is cached per process, `tokens.py:150-153`, so pointing `SWREVIEW_TOKENIZER_DIR` at an empty folder would meet the warm cache), and `None` for a restored review; Gemini is approximate (FR-012); SC-006 over the owner's recordings, skipped through `tests/support/recordings.recording_folder` and the vocabulary fixture as the replay's real-recording tests are (no new marker: `pyproject.toml` registers none for it) |
| `test_waiting_answers.py` (013's part-roles shape, `tests/support/roles_review.py`) | "All bought" while waiting withdraws the unclear part's findings with no provider request and recounts the size (US3 independent test). The fixture is built so the answer withdraws at least one **named** finding - a hygiene finding of the unclear part, the helper extended if it raises none - besides folded RMS findings, which the digest counts and never names (`PrerunResult._finding_lines`, `prerun.py:582-598`): the opening names no withdrawn named id and every standing one, the folded family's counts line in the rebuilt opening equals the regraded session's counts, the answer line is there, and there is no "withdrew" line and no instruction (SC-005, FR-023); the waiting branch ends in `_settle_waiting` and `close_waiting` (71A); after the apply, the size sentence's number, `session.sent`'s and `model_status`'s estimates and the count of the recorded request prefix are one number (owner decision 78A); after Send, the message an answer to the model's own question adds, and a follow-up's, carry none of the wait's lines, and no later request holds them more than once, inside the opening (FR-023's last sentence, *tasks review, 2026-10-09*); "Apply answers" sentence; a Reject kept; a confirmed drawing read while waiting with the fake bridge writes the outcome line, a refusal's too (FR-021), and once the apply settles `awaiting_send` the pipe the read opened is closed again (owner decision 79A); an answered question cannot be answered again; Send refused while answers apply; **an apply that fails** - `classify_part_roles` raising, the confirmed read raising, the Send cache's build raising, the finalization's `save_session` (`write_atomic`) raising - each: one `error` event and no `turn.ended` or `session.ended`, the chat `failed`, `session.json` and `report.md` the record before the apply (its answers open), the provider factory never called, and the failed chat no longer holding the folder (R2.13; the re-run that then claims it is `test_recheck.py`'s); the failure **after** the write (`write_attention_record` raising): `session.json` the applied record, its answers answered (`test_recheck.py` carries them); **a crash during an apply** (owner decision 76A): the folder `disk_at` copies inside the apply before the finalization's save holds the record before the apply, its answers open and no turn event (its read-only restore with Send offered is pinned in `test_chat_review_routes.py`); **a drawing merged before the failure** (a confirmed read that merges its drawing into the folder's `package.json`, then the regrade raising) is re-run in `test_recheck.py`, which does not ask that drawing question again, carries no outcome line for it, and names the loss once in `coverage.recheck` (R2.13) |
| `test_recheck.py` (every case that stands for a restart starts from `tests/support/restart.py`'s `restarted_app`, a backend started afresh over the same run root with no live chat, and every cut-off is the folder `disk_at` copied at the point a kill cuts, with nothing raised: owner decision 76A) | the earlier record with a part-roles answer, a drawing answer whose read moved the numbers, and a Reject (US4 independent test), sent from a restarted app: no extraction, zero bridge calls before the first request (a counting fake bridge), the digest's interference line and coverage rows equal the first run's, answers and the decision on their own items, the outcome line carried, unmatched and ambiguous items named once (FR-028, FR-029, SC-008); **the opening after a carried part-roles answer** names no finding the answer withdrew and every standing one, because the carry ends with `_settle_waiting` and `prerun.restated` (owner decision 71A; FR-023, SC-005 on the restart path); with nothing answered, the first request byte-identical to the live waiting review's; after a re-run, the size sentence's number, `session.sent`'s and `model_status`'s estimates and the count of the recorded request prefix are one number (owner decision 78A); every live outcome carried (clean, rows, collided, rows not written - the unresolved line and the decisions named - failed and not retried, no bridge, not an assembly); the carried live step at the first run's `live_detection.step_index`, every later step index and finding citation equal to the first run's, the guard's `ran_at_step` for a repeated live call naming the carried step, `tool-results/step-N.json` holding the carried payload, a failed first call carried as a failed step with the first run's `failed` row, and no step for a call never attempted (R2.17); decisions matched on `finding_subject_key` and applied through `set_disposition(..., at=earlier.at)`, keeping their first time, with one `disposition` event each (owner decision 72A): two `hole.coaxiality` findings on one pair of components, one Rejected, the Reject carried onto its own finding and nothing named; **two earlier decisions that meet one re-run finding** (a profile change merges them): neither carried, each named once with "another decision matches the same finding" (72A); the four timing inputs carried; a `send_failed` record re-run stays `send_failed` with its failures and its report keeps the failure line, and a Send that then succeeds reports "Earlier attempts that failed: 1" (FR-032); `drawing_read` carried with no ping and written on the re-run's session, and a second restart's re-run of that record again makes zero bridge calls (SC-008); a first run whose rows were not written (`persist_error`), with the dump's stale rows for the reviewed configuration still in `package.json`: the re-run judges none of them (no finding cites one) and its family row is `INTERFERENCE_ROWS_NOT_CARRIED`; the Standards profile changed between the first run and the re-run - another file, the same file edited, a profile added where the earlier record had none, and one removed (owner decision 78A): the re-run grades with the profile in effect, records its identity in `model_status.profile` (absent when it has none), names the change once in `coverage.recheck`, and names any decision whose finding the new profile no longer raises; an unchanged profile names nothing; **adoption** (the same app, which is what a host that gave up meets): a re-run whose answer the caller discards, then a second `recheck: true`, answers the same chat id, runs nothing again and never calls the provider factory, while a live chat on the folder that is `running` is still `409 RunDirInUse`, and a second `recheck: true` sent while the first is still running (held in the backend) is `409 RunDirInUse` and starts nothing, the third, after the first answers, adopting it; the carry writes nothing - `session.json`, `report.md` and `attention.json` unchanged on disk from the claim until the finalization; a re-run that fails (an unreadable package, raised: FR-041's other half) or is cut off at each of three points - after the rotation, after `start_review` and the carry and before the finalization, and inside `write_atomic` once its temporary is written and before `os.replace` - leaves `session.json` byte-equal to the earlier record, which a restarted app reads (its restored Send block pinned in `test_chat_review_routes.py`), the leftover `.session.json.<random>.tmp` passed over by `GET /reviews`, the rotation and the next re-run, the provider factory never called, and a second re-run succeeding at the next index (FR-041); two failed re-runs then one that succeeds leave every index a session with the stream it wrote or a failed attempt's stream with no session, the earlier record copied once (R2.17 step 2); a folder deleted is `404 UnknownReview`; a sent record is `409 NotWaiting` |
| `test_session_fields_015.py` | the three fields optional, omitted at their defaults, and `model_status.profile` omitted for a review with no profile; a pre-feature session round-trips to its own bytes (FR-036), and so does the `session.json` the characterization's scenario writes, read before normalization (never its golden, whose placeholders do not validate); each validates against the amended `review-session.schema.json`; `LiveOutcome` to record and back keeps every dataclass field (a field added later fails the test) |
| `test_send_block.py` | the summary's `send` block absent for a ticked review (the pane fixture's bytes), present waiting with and without a number, Gemini approximate, the failure line of a recorded failed request (`send.failed`) and of a Send that failed before any request (`send.not_started`, held by the run, absent after a restart), `restored`; the block carries no `session_id` and no restored line (owner decision 68A); `{tokens}` written by `summary.tokens_text`, the formatter `ResumeWords.of` calls too (patching it moves both; owner decision 73A); `resume_text` while waiting; every sentence a words-file key |
| `test_questions_identity.py` | `asks_same` is the rule `answered_roles` and `_is_confirmed_candidate` used (their tests unchanged) |
| `test_report_model_status.py` | the three header variants, and a re-run's "Checked again from session" line; a ticked review's report unchanged (the characterization golden of R2.28) |
| `test_pane_waiting_fixtures.py` | the three waiting fixtures, and `review-not-sent-session.json` (the earlier record's `session.json`, for the host's cross-language head read, R4.2), equal a fresh generation (the precedent `test_pane_drawing_fixture.py`); every clock value in them is the pinned fictional time; `review-waiting.json`'s `waiting` holds the part-roles question and a drawing-candidate question, both written by code, and its `sending` carries `send_in_flight: true` (owner decision 77A); `review-waiting-restored.json`'s `restored` is read-only with the composed line and the `restored` block, and its `rechecked` is the re-run's answer and live snapshot (R2.25) |
| `test_ticked_review_golden.py` (**first**, on the pre-feature code; R2.28) | five scenarios on the fictional questions package through the `TestClient`, with the recording provider, each against its own golden (owner decision 75A): the success scenario (the opening turn, a part-roles answer that resumes the model, a follow-up and the explanation pass), posted with no new key and with the host's `{send_when_checked: true, recheck: false}`, both equal to one golden; a ticked start whose factory raises (the status, the body and the run folder's listing); a first request that raises before any round; a failure after one completed round; Stop at the first tool boundary - each with every `run()` and presentation input, `events.jsonl`, `session.json`, `report.md` and `attention.json` where written, times, durations and UUIDs normalized (FR-035, SC-003) |
| `test_request_prefix_characterization.py` (before `_prefix` moves; R2.28) | for each committed replay fixture under the pane defaults, the first pass's prefix sha256 and length equal to the committed values (R2.9) |
| `test_restart_support.py` (owner decision 76A) | `tests/support/restart.py`: `restarted_app(run_root, settings)` is a fresh `create_app` over the same run root, holding no chat of the first app (the precedent `test_chat_review_routes.py:205-225`); `disk_at(folder, hook)` copies the run folder when the named point is reached, raises nothing, and lets the code carry on (the precedent `test_remodel_apply_log.py:307-324`); its one named point, `BEFORE_REPLACE`, inside `write_atomic` after the temporary is written and before `os.replace`, leaves the copy holding the old file and the temporary beside it; the copy is a folder a restarted app reads |
| `tests/perf/test_send_gate_perf.py` (opt-in, the `perf` marker; owner decision 70A) | on `test_prerun_perf.py`'s thousand-group package: a ticked start, an unticked start and a re-run with a carry, timed and printed; the unticked start's added work a small fraction of the pre-run's; the figures, and the bound they set (one 30 s rule when the larger re-run fits inside 30 s, else `ChecksOnlyTimeout`), recorded in R2.17 and RK-10 |

Support modules: `tests/support/recording_provider.py` (moved from `test_prefix_stability.py`, with
`for_presentation` added and each run's raw inputs kept, owner decision 78A),
`tests/support/questions_package.py` (new: the fictional questions package the characterization, the
waiting fixtures and `test_waiting_answers.py` share) (R2.28, R2.25), and `tests/support/restart.py`
(new: `restarted_app` and `disk_at`, the one way every crash, kill and restart case is simulated,
owner decision 76A).

Existing modules extended rather than duplicated: `test_chat_sessions.py` (the table),
`test_chat_review_routes.py` (`GET /reviews` of a not-sent record is read-only, its
`read_only_reason` the composed restored line, and carries the restored block; a sent one is as today:
owner decisions 68A and 73A), `test_review_snapshot.py` (`send_in_flight` written only when passed
true, omitted otherwise: owner decision 77A), `test_events_schema.py` (an
unticked `session.started` with `send_when_checked: false` validates; `true`, or any other new key,
is refused; `session.sent` validates; `contracts/review-flow.md` section 7),
`test_recording.py` and `test_cli_benchmark_replay.py` (the two refusals), `test_handoff.py`,
`test_review_words.py`, `test_pane_fixture.py`, `test_replay_fixture_hygiene.py` (the three waiting
fixtures and `review-not-sent-session.json` join its committed files, FR-039), and `test_atomic.py` if 015 lands `atomic.py` first
(R3).

### R4.2 New add-in tests (`extractor/SwReview.AddIn.Tests/`)

| File | Covers |
|---|---|
| `UserSettingsTests.cs` (extended) | absent, `null`, a string, a number each read ticked with one problem for the non-booleans and every other field loaded (FR-002); `false` round-trips; a file written before the feature saves to its own bytes; the schema validates both; the setting is two members, the held token and a settable `SendsWhenChecked` (owner decision 73A) |
| `PageMessageTests.cs` (extended) | `init` and `settings` views carry `send_when_checked`; `send_when_checked.save` writes, does not restart (`Backend.Restarts` unchanged), is not refused while a turn runs, keeps every other field; a failed write is `SettingNotSaved` and the stored value stands; `settings.save` keeps the value; **one persist step** (owner decision 73A): a box save on a file with a load problem writes what a Settings save writes and clears the load problem, so `ReportSettingsProblems` posts none after it; a `settings.save` whose write fails answers `SettingNotSaved` (it answered `HostError` before) and the stored settings stand; `settings.save` is accepted when the fake backend reports the review's chat `awaiting_send` and refused when it reports `running` (FR-027; the host's `IsTurnRunning` counts only `running`, `BackendClient.cs:118-122`) |
| `ReviewHostTests.cs` (extended) | `review.start` passes the stored value as the request's `Mode` (`Send` or `Wait`, through `CreateReviewSession`, owner decision 71A); `review.started` carries it; an unticked start's record has `ModelStatus` `not_sent` and its `sessions` item `model_status`, a ticked start's neither (owner decision 73A); `review.recheck` refusals (no record, a drawing, another document, no backend), the request (`Mode` `Recheck`, the record's folder, the bridge, no dump), the record replaced with its `ModelStatus` kept, `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document}`; the call's timeout the one `TimeoutFor` gives its mode; a backend refusal rethrown with its class; messages handled in order - a `review.start` then a box change: the start passes the old value and the change is written after it (FR-002, FR-003); a Retry (`review.start` after a failed start) passes the value stored when it is handled, after a box change (the spec's Retry edge case); a `CreateSession` that times out on an unticked start is today's failure, with no record kept (the orphan waiting chat of `review-flow.md` section 1); the `checking` and `ready` statuses around a re-run carry `words.md` section 5's sentences, asserted as literals; a review found by `sessions.list`'s search is re-run by its `session_id` - accepted, not `UnknownChat`, with `POST /sessions` on its folder, `recheck: true`, `send_when_checked: false` and no dump (FR-030, *tasks review, 2026-10-09*); **the marks** (73A): `sessions.list` refreshes only the records whose `ModelStatus` is set, one head read each through a counting opener and none for a ticked record; a record whose `session.json` now says `sent` loses its mark, and a `null` head read (no `session.json`, as the fake backend writes none; an unreadable file; no `model_status` within 64 KiB) keeps it; after a second `ready` (a page reload), the list still carries every waiting record's mark |
| `RunFoldersNotSentTests.cs` (new) | the search over fictional folders: offered when the newest same-name folder's record is not sent or send failed and names this path and configuration; not offered behind a newer sent review, a failed check run, another path, another configuration, or when the session holds a review of the document; never offered from a newest folder of another document name whose record names this document (owner decision 78A: names first); check, standards and remodel folders skipped; the collision suffix; a `session.json` written by the Python fixture generator read by the head reader (the cross-language contract; `Fixtures/review-not-sent-session.json`, a name the project's `Fixtures\review-*.json` copy glob already covers, `SwReview.AddIn.Tests.csproj:180`); a head with no `model_status` within 64 KiB is nothing; the found chip's date is the stored `checked_at` wall clock (R2.15); **the access pattern** (owner decision 80A): over a 500-folder root of the same document, each with a `session.json`, the injectable opener is called exactly once, for the newest folder's file; the 2 s bound on that root a plain `[Fact]` (FR-030) |
| `RunFoldersModelStatusTests.cs` (new; owner decisions 73A and 80A) | `RunFolders.ReadModelStatus(runDirectory, openHead)`: the top-level `model_status` within the first 64 KiB, read with `Utf8JsonReader` and no further; none within the cap, or no file, is `null`, and nothing throws; a stream that throws past 65,536 bytes proves the cap; the default opener uses `FileShare.ReadWrite \| FileShare.Delete`, so a `File.Replace` of the file while the reader holds it succeeds; `PackageIndex.FillHead` is the one bounded fill loop `HeadOf` and `ReadModelStatus` call, `HeadOf`'s tests unchanged |
| `BackendClientSessionBodyTests.cs` (new, an in-process `HttpListener` on 127.0.0.1 as `RemodelBackendClientTests.cs` uses, 004 T134d - `StubBackend` is a process-lifetime stub that serves no `POST /sessions`) | the body carries `send_when_checked` and `recheck` written from the request's `Mode`: `true, false` for `Send`, `false, false` for `Wait`, `false, true` for `Recheck`, so no request can ask for a re-run that sends at once (owner decision 71A); `TimeoutFor` gives `ChecksOnlyTimeout` for `Wait` and `Recheck` and the 30 s `CallTimeout` for `Send` and every other call, checked directly, with no waiting; `ChecksOnlyTimeout` is the 30 s `CallTimeout` until the measuring task, and then the literal research R2.17 records - or, where R2.17 says the re-run fits inside 30 s, `TimeoutFor` is gone and every call has the 30 s `CallTimeout` (owner decision 70A) |
| `ReviewPageSendGateTests.cs` (new, offscreen WebView2, `review-waiting.json`) | the box: under the buttons, from `init`, a change posts the message, a refused write puts it back with the label, never disabled; an unticked start: no turn running, Stop off, the status line, the Send block with its sentence, the follow-up off with its placeholder; the status line "Checked by code. Not sent to the model." ahead of "Waiting for your answers." with code questions open (FR-033); Send: posts `/send`, running at the first `usage`, the follow-up box enabled after it; a failed first round (`failed_send`): no error card, the failure line, Send again, and the text the failed round streamed still in the Transcript (FR-017); `NoCredential` beside Send; **a reload while a Send is held** (owner decision 77A): the snapshot's `send_in_flight` sets `state.sending`, and `failed_send`'s events played after it draw no error card and no Retry, the failure line and Send coming back; the same with one `error` and nothing after it; "Apply answers"; an apply leaves the status and Stop as waiting; a reload while waiting and during an apply shows waiting; Send disabled while another document or a drawing is active and offered again on return (FR-018); the Settings section's waiting line (FR-027); transcript lines, `session.sent`'s reading "Sending to ..." (owner decision 72A); a chip's "not sent" from its `sessions` item, and **after a reload** the waiting chip marked before it is chosen while a ticked review's chip never is (73A); Review pressed while waiting (FR-026); zero proxy calls to `/send`, `/messages` and `/evidence` across Clear review, a document switch and Review again (SC-001); "Before this review" still says no tokens were used with the box unticked; the Send block under the summary and above the questions panel; a Send that fails before any request (an `error` with no `usage` and no `session.ended` after it): no error card, the turn unmarked, the failure line, Send offered again (R2.10); with `HoldReviewStart`, a box change shows at once and its `send_when_checked.save` is posted after the `review.start`, and on release the waiting state follows `review.started`'s value, not the box (FR-002, FR-003); a `review.start` error with the box unticked (`InvalidPackage`) shows today's error card and Retry and no Send block |
| `ReviewPageRecheckTests.cs` (new, `review-waiting-restored.json`) | a restored waiting review (owner decision 68A): read-only, its `#read-only` line the snapshot's composed `read_only_reason` (the first sentence of feature 009's read-only line, then the dated Send sentence, and never 009's second sentence: 73A), the sentence without a number, the questions panel, decisions and follow-up off, Send alone enabled; Send posts `review.recheck`, then `/send` with the `rechecked` chat id, re-keying nothing; a Send refused after the re-run (`NoCredential`) leaves the review live and waiting, its questions and decisions usable, the refusal beside Send; a re-run in flight: the status line, Save, Review, chips and Send off, no Stop; a failed re-run: its line, the review still read-only with Send offered, no Retry; a folder gone: feature 009's sentence; a backend restart with a waiting review on screen restores it at once, read-only with Send (FR-042); a found chip names its date when not today; a page reload while a re-run is held shows nothing of the review until the release, then shows it - never running and never being checked again (FR-033, the restoring edge case); a restored review's Settings line, switching to the re-run's line while one is held and back on release (FR-027); a `document.changed` that asks `sessions.list` again, the found review's dated chip marked not sent, the page following with it restored, and its Send going through `review.recheck` with the found chat id (FR-030, *tasks review, 2026-10-09*); an apply that fails: no error card, the review restored read-only from its folder with Send offered and the error's line; **a reload during an apply that then fails** (77A): the same, the rule keyed on the summary's `send` block |
| `ReviewPageSendLayoutTests.cs` (new, `review-waiting-big-assembly.json`) | at 300 by 600, the headline, tally and not-reached line inside the viewport in each worst case a waiting review shows (SC-007): `waiting`; `failed_send`, with its failure line; `restored`, with its restored line and sentence; and `restored` after a failed re-run, with the `rerun_failed` line; in the same four, the Send to model button inside the viewport too (R2.21); the measured slack recorded in R2.21; at 260, 300 and 420 px the session buttons wrap as today (two rows at 300 px) with the box directly under them |
| `ReviewPageDriver.cs` (extended; the page tests' host) | answers `send_when_checked.save` and `review.recheck` (the second with a fixture's `rechecked` body), an error mode for each, `sessions.list` items that carry `model_status` (73A), and `HoldReviewRecheck` / `ReleaseReviewRecheck` beside `HoldReviewStart` / `ReleaseReviewStart`, so a re-run can be held in flight. Unlike `HoldReviewStart`, which holds only its own reply, `HoldReviewRecheck` also queues every message the page posts after it and answers them in order on release, as the host's one pump does (R2.2), so a reload during a re-run is answered only after it |
| `ReviewPageDefaultViewScanTests.cs` (extended) | the raw tokens `awaiting_send`, `not_sent` and `send_failed` never visible, scanned on `review-waiting.json` and `review-waiting-restored.json` as well as the pane fixture |

The six `IBackendClient` fakes (`EventStreamPumpTests`, `PageMessageTests`, `PaneActionsTests`,
`ReviewHostTests`, `RunFoldersStandardsTests`, `ToolServiceWiringTests`) need no change: 015 adds no
interface member (`NewSessionRequest` is a class, and its `Mode` is optional with `Send` its default),
and `ChatSessionHandle` does not change (owner decision 68A drops the `carried` maps).

### R4.3 Existing tests that move, and why

| Test | Moves because |
|---|---|
| `reviewer/tests/unit/test_chat_sessions.py`: `test_every_state_can_fail`, `test_a_transition_the_table_does_not_name_raises` | the transition table gains `awaiting_send`; new paths and refused moves are added (`test_failed_is_terminal` iterates `ChatState` and passes unchanged) |
| `reviewer/tests/unit/test_chat_server.py`: `ROUTES` (`:279-296`) | the census gains `POST /sessions/{chat}/send`, so the door test covers it |
| `reviewer/tests/unit/test_events_schema.py`: `test_a_full_run_emits_every_event_type_the_runner_and_tools_can_emit` | the full run must include an unticked review sent after waiting, so `session.sent` and the `send_when_checked` field are emitted |
| `reviewer/tests/unit/test_gate_same_session.py`: `test_a_gated_run_emits_no_event_type_outside_the_sixteen` (`:201-214`) | it asserts `len(SCHEMA_EVENT_TYPES) == 16`, read from the schema's `type` enum, which `session.sent` makes 17: renamed `..._outside_the_seventeen`, the count 17, and a dated docstring line, as 011 T092 and 013 T038 each renamed it (added 2026-10-09, tasks review) |
| `reviewer/tests/unit/test_provider_protocol.py`: `valid_bodies()` (`:112`), read by `test_every_schema_event_type_has_a_case` (`:184-186`) | that test needs one valid body per enum type, so `valid_bodies()` gains a `session.sent` body `{provider, model, effort_mapping, estimate}` (`contracts/review-flow.md` section 7); the test itself is unedited (added 2026-10-09, tasks review) |
| `reviewer/tests/unit/test_review_words.py` | the words file gains the `send` block and five error labels |
| `reviewer/tests/unit/test_pane_fixture.py` | the labels block gains keys (snapshot part unchanged) |
| `reviewer/tests/unit/test_replay_fixture_hygiene.py` | the three waiting fixtures and `review-not-sent-session.json` join the committed files its string checks read |
| `reviewer/tests/unit/test_recording.py`, `test_cli_benchmark_replay.py` | two new refusal rows ahead of the event read |
| `extractor/SwReview.AddIn.Tests/ReviewPageViewsTests.cs`: `TheStatusLineReadsEachOfItsFourSentencesInItsState` (`:107-118`) | six sentences; renamed accordingly |
| `extractor/SwReview.AddIn.Tests/ErrorLabelsCoverTheHostTests.cs`: `TheScanFindsTheClassesTheHostAndThePageMake` | the expected list gains `ReviewNotActive` and `SettingNotSaved` |
| `extractor/SwReview.AddIn.Tests/PageMessageTests.cs`: `ReadyIsAnsweredWithInitCarryingTheBackendOriginAndNoKey` | asserts the view's new key (additive) |
| `extractor/SwReview.AddIn.Tests/UserSettingsTests.cs`: `RoundTripsEveryFieldThroughATempFileAndSatisfiesTheContract` | the new field round-trips |
| `extractor/SwReview.AddIn.Tests/ReviewHostTests.cs`: the `review.start` test that asserts every `NewSessionRequest` field (`:322-370`) and `FakeBackend.CreateSession` (`:2123`) | the request gains `Mode` (owner decision 71A) |
| `extractor/SwReview.AddIn.Tests/ReviewPageContractTests.cs`: `TheReviewStartRowsReplyNamesTheDocumentItReviewed` (`:178-186`) | it asserts the exact substring "review.started {chat_id, run_dir, not_examined, document}" of 002's `review.start` row (`:184`), and the amendment adds `send_when_checked` to that reply: the asserted substring becomes "review.started {chat_id, run_dir, not_examined, document, send_when_checked}", in the commit that amends the row |
| `extractor/SwReview.AddIn.Tests/ReviewPageDefaultViewScanTests.cs`: `NoRawStatusOrBucketTokenIsVisible` (`:55-65`) | its token list (`:60`) gains `awaiting_send`, `not_sent` and `send_failed`, and it runs on the two waiting fixtures too (R4.2) |
| `reviewer/tests/unit/test_prefix_stability.py` | `RecordingProvider` moves to `tests/support/recording_provider.py` (R2.28); the module imports it, every assertion unchanged |
| `extractor/SwReview.AddIn.Tests/ReviewPageSummaryAcceptanceTests.cs` (`:91-109`) and `ReviewPageNarrowLayoutTests.cs` (`:37-53`) - not edited | the box is a line in `#session` in every review, ticked included; measured (R2.21) at about 21 px of 226 px of slack, so both pass with it unedited. The first page task runs both with the real box in place |
| 014's `test_benchmark_pane_parity.py` | at merge only (R3) |

Unchanged and expected to pass untouched (each a check that the default path did not move):
`test_no_lever_in_pane_settings.py`, every replay test and fixture, every check golden (`tests/golden`),
`test_session.py`, `test_runner_provider.py`, `test_part_roles.py`, `test_confirmed_drawing_read.py`,
`test_answer_batch_roles.py`, `ReviewPageContractTests.cs` but the row above (its rules 1 and 2,
`:55-99`, hold each new Review page row to the page's sends, so each row lands in the commit where the
page first posts it: `send_when_checked.save` with the page's box, `review.recheck` with its re-run;
tasks T055 and T108),
`PageRuleScanTests.cs`, `ReviewPageSessionsTests.cs`, `ReviewPageQuestionsTests.cs`,
`ReviewPagePreparationTests.cs`.

---

## R5. Risks

| # | Risk | Mitigation |
|---|---|---|
| RK-1 | Something sends before Send (a hook missed) | `ProviderControl.built` empty and a provider stand-in that fails on any call, across every path SC-001 lists; the page tests count proxy calls to `/send`, `/messages` and `/evidence` |
| RK-2 | The opening rebuilt after a regrade differs from what a fresh review would say, or SC-004 drifts | frozen opening when nothing applied; the builder pinned to it; the regrade fixture checks named and withdrawn ids and the folded counts line |
| RK-3 | The 300 by 600 budget breaks with the box and the Send block | measured on the committed build (R2.21): about 226 px of slack above the fold on the finished big assembly; the box takes about 21 px; a Send block above the summary failed its worst case (a restored review after a failed re-run) on a proxy, so the block sits under the summary, where it moves nothing SC-007 reads, and only the box and the restored line (about 91 px together) stand above it. `ReviewPageSendLayoutTests` measures the four worst cases on the big-assembly waiting fixture once it exists and records the figure; if SC-007 still fails, the page work stops and the owner is asked which gives way (R2.21) |
| RK-4 | A re-run leaves the folder unrestorable | the record is copied, not moved, and replaced atomically at the re-run's end; the carry writes nothing before it; a failed attempt's stream rotates alone; fail tests (raised) and kill tests at three points, each kill the folder `disk_at` copied where it cuts - the last inside `write_atomic` before `os.replace`, leaving a temporary the rotation and `GET /reviews` pass over - read by a backend started afresh with `restarted_app` (owner decision 76A) |
| RK-5 | A carried answer or decision lands on the wrong item | identity, never number (`asks_same`, `finding_subject_key`); ambiguous is not carried and is named, and so are two earlier decisions that meet one re-run finding (owner decision 72A); decisions applied through `set_disposition`, the validated writer every decision takes; the moved-numbers fixture and the two-coaxiality-findings case |
| RK-6 | The found-review search slows document opening, or makes a backend write fail | runs on the pump thread, names first, one bounded head read opened with `FileShare.ReadWrite \| FileShare.Delete`; the access pattern pinned by a counting opener over 500 folders of the same document (one file opened) and a stream that throws past 64 KiB; the 2 s bound a plain `[Fact]` (owner decision 80A) |
| RK-7 | A crash mid-Send leaves a record that says "not sent" though the model received the request, or "sent" beside "not sent" rows | the attempt is written as failed ("the backend stopped before the model answered") before the request; at the first round the session is saved as a sent review mid-turn, the checks' finalization rows already withdrawn (R2.11) |
| RK-8 | Merge conflicts with 014 | R3's table; whichever merges second reconciles, classifies the two `start_review` arguments, marks the carried live step `prerun`, regenerates the pane fixture and the characterization's five goldens in the merge commit (on the first-merged side alone), and runs the replay regeneration step against the other branch's fixtures (R2.28) |
| RK-9 | The seat has no tokenizer vocabulary, so the size sentence never shows a number there | the sentence without a number is the spec's; the [W] task records whether `swreview tokenizer fetch` (or `--from`) was run |
| RK-10 | `POST /sessions` does more before its 201: an unticked start adds a cache build, a finalization and a render, and a re-run runs the checks; the host waits 30 s for any call (`BackendClient.cs:39`) on its one message pump | a measured bound (owner decision 70A, R2.17): `tests/perf/test_send_gate_perf.py` (opt-in) times a ticked start, an unticked start and a re-run with a carry on the thousand-group package; when the larger measured re-run fits inside 30 s, R2.17 says so and one 30 s rule covers every call (`TimeoutFor` and `ChecksOnlyTimeout` go), and otherwise `ChecksOnlyTimeout` - `TimeoutFor`'s value for the `Wait` and `Recheck` modes - is that re-run times three, rounded up to the next 30 s, the measuring task recording which holds, here and in R2.17; until it lands, every call keeps 30 s (the margin's value and the interim 30 s: defaults taken 2026-10-09, the owner may revise, R2.17); a ticked start keeps 30 s (FR-035); a re-run the host gave up on is adopted by the next one (R2.17); an unticked start the host gave up on leaves an orphan waiting chat that is never sent and is released at the next restart (`review-flow.md` section 1); the [W] task times the unticked start and the re-run on the small and the big assembly, and a seat re-run longer than 30 s under the one rule, or than a third of `ChecksOnlyTimeout`, sets the bound again by the same rule; the seat's unticked-start timing is recorded for information only (R2.17). *Measured* (T098, 2026-10-14, development machine, thousand-group package): ticked start 5.3 to 5.5 s, unticked start 7.4 to 7.9 s (its added work at most 0.61 s), re-run with a carry 7.4 to 8.8 s; the larger re-run fits inside 30 s, so one 30 s rule covers every call and `TimeoutFor` and `ChecksOnlyTimeout` go (T104) |
| RK-11 | The Send turn reads a coverage the checks' finalization left, and stops early | the rows are withdrawn by identity before the first request (R2.27); every request of the turn compared with a ticked review's, tool results included |
| RK-12 | An apply that fails leaves the page locked, or a report that matches neither record | the run puts the record on disk back before `_play` re-renders, one `error` event is written, the chat fails, and the page restores the review from its folder (R2.13); the failure points before and after the finalization's write tested, and a drawing merged before the failure named by the re-run |
| RK-13 | Send fails before any request (the adapter's build or setup, the `session.sent` event, the pre-write) and leaves the page waiting or a record that says a request was made | the prepare half changes nothing, the adapter's build included (owner decision 69A); `session.sent` comes before the pre-write, so the guard only restores memory and never writes (owner decision 72A); one `error` written, the chat back to waiting (R2.10); five failure points tested, and a guard whose own `error` emit fails still settles waiting |
| RK-14 | Two threads write one waiting session (a decision's write beside Send's pre-write) | on a waiting chat the decision and timing routes run their write on the chat's one worker, where a Send or an answer accepted meanwhile is queued behind it (owner decision 69A, R2.12); a held-write test |
| RK-15 | A refactor of the ticked path drifts and every planned comparison, new code against new code, still passes | the characterization golden and the prefix characterization are committed on the pre-feature code before any refactor, and the replay regeneration step runs where the recordings are (R2.28) |
| RK-16 | Several waiting reviews hold their SOLIDWORKS pipes and use up the add-in's four pipe instances, stopping the tool service for the rest of the session | `ReviewRun.release_bridge()` at the end of an unticked start or a re-run and whenever `_play` settles `awaiting_send`, the client kept (owner decision 79A, R2.29); a counting transport: five waiting assembly reviews hold zero pipes, and Send reopens one. The older ceiling on sent reviews is out of scope, for a separate change (`docs/review-backlog.md:336-337`, `:436-437`) |
| RK-17 | A reload during a Send or an apply turns its failure into the error card with Retry | the snapshot's optional `send_in_flight` sets `state.sending` on restore, and the apply rule is keyed on the summary's `send` block (owner decision 77A, R2.30); four page reload cases |

---

## R6. Questions this plan adds for the owner

**Answered by the owner on 2026-10-09** (R7): question 1 by 73A (the host's record, option B's
exact mark, refreshing only the records that wait); question 2 by 73A (A, the default kept);
question 3 by 68A (A, the default kept). The text below is the question as it was put.

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
   call each). A is the least machinery and a reload is rare; B is the exact one. **Answered (73A)**:
   the host's record is the one source of the mark, set at an unticked start, kept by a re-run, set
   by the search, and refreshed on every `sessions.list` for the records that wait only (one bounded
   head read each), so it is exact after a reload (R2.20, R2.21).
2. **The handoff export (R2.24).** Default (A): it gains the model status. (B) leave the export as
   it is (it then names a provider for a review never sent). A is one field and keeps FR-032's
   honesty in every record a review leaves. **Answered (73A)**: A.
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
   **Answered (68A)**: A.

---

## R7. Owner decisions of the plan review (2026-10-09)

The owner ran CLAUDE.md's plan review in its BIG CHANGE form on 2026-10-09: four sections
(Architecture, Code quality, Tests, Performance), each with its numbered issues and lettered options,
the recommended option first, and took the recommended option on every issue. Decisions 68A to 80A
are the result; each binds this package. The options recorded are the review's own for each issue,
the chosen one first; the review's notes are held outside the repository. Two of its issues merge in
one decision (70A); one part of an issue is superseded by another decision (71A's hold, by 69A); for
74A the option taken is the correction the decision names, and the module the review's notes
proposed is recorded as B. The reviewers also refuted one performance issue as overstated - loading
the earlier record on the event loop during a re-run's claim, about 10 ms on the fictional big record
- and nothing changes for it. Where a decision leaves a detail open, the amendment fills it with a
default marked **Default taken 2026-10-09, the owner may revise** in that decision's entry (70A's
margin and interim 30 s; 72A's rule that neither of two decisions meeting one finding is carried).

### 68A. Send is the only re-run trigger after a restart (2026-10-09)

- **Question** (Architecture, issue 1; the spec's questions 1, 2 and 4 and this plan's question 3;
  FR-028 to FR-031, FR-041, FR-042): User Story 4 built three re-run triggers - a restored review's
  answer, decision and Send (the spec's question 4 default) - and with them an id re-keying protocol
  across the backend, the host and the page; 61A names one trigger, Send. What does a restored
  not-sent review offer, and what starts its re-run?
- **Options**: A: Send is the only re-run trigger. A restored not-sent review is feature 009's
  read-only restore plus the Send block; Send runs `review.recheck`, then the re-run from the same
  folder - which carries the answers and decisions made before the restart by identity, keeps its
  full matching matrix, names anything that no longer matches in its one line, copies and never
  moves the record, handles failed and killed re-runs, and grades with the Standards profile in
  effect, named when it changed - and then `POST /send`. Dropped: the re-run before an answer or a
  decision (`recheckThen` for them), the `carried` maps end to end (the 201, `ReviewRun.carried`,
  `ChatSessionHandle.Carried`, `review.rechecked.carried`), the page's re-keying, the "no longer
  applies" card and `send.session_id`. After a restart, a new answer or decision waits until after
  Send, through today's resumed path. A failed apply restores read-only with Send offered. B: as
  planned: questions, decisions and Send each trigger the re-run, with ids re-keyed through the
  `carried` maps in three layers. C: split User Story 4 into a later feature and ship User Stories 1
  to 3 (breaks 61A's restart clause on the hot no-key path: saving the key restarts the backend).
- **Chosen**: A, with the spec's question 1 (carry answers and decisions) yes, question 2 (bring a
  never-sent review back when its document is reopened) its default, question 3 (a ticked review
  keeps today's failures) its default, and this plan's question 3 (grade with the profile in
  effect, named) its default. Applied in: spec User Story 4, its scenarios and edge cases, FR-020,
  FR-027 to FR-031, FR-041, FR-042 and the Assumptions; R2.13, R2.17, R2.18, R2.19, R2.21, R2.25;
  data-model sections 6, 8 and 9; `contracts/recheck.md` sections 1, 4, 6 to 8 and 10;
  `contracts/pane.md` sections 5, 7 and 9; `contracts/words.md`; tasks of User Story 4.

### 69A. A waiting chat's work queues on its own worker (2026-10-09)

- **Question** (Architecture, issue 2; the spec's edge case "Send failing before its first
  request"): the plan moved a waiting chat `running` for a decision's or the timing's write and for
  Send's adapter build outside `_play`, so each path cleared the stop flag by hand, and the factory
  failure had a `502` with no event of its own, against the spec's edge case.
- **Options**: A: on a waiting chat the decision and timing routes submit their write to the chat's
  one-thread worker and await it (no state move, no `finally`, no flag); Send's route runs its checks,
  moves the chat to `running`, submits `run.send` and answers `202`, and the adapter is built inside
  Send's guarded prepare half, one more failure point (one `error`, the `send.not_started` line, back
  to waiting); `_play`'s `finally` stays the only place the stop flag is cleared. B: as planned (hold
  `running`, build on the loop with a `502`). C: a distinct `busy` state for such work.
- **Chosen**: A. The plan's reason for rejecting the worker - a decision would wait behind a whole
  Send turn - cannot happen, because a decision passes `_require_idle` only before Send moves the
  chat. Applied in: R2.4, R2.7, R2.10, R2.11, R2.12; data-model sections 2 and 3;
  `contracts/review-flow.md` sections 2 to 4 and 6; `contracts/pane.md` section 3; tasks of User
  Story 2.

### 70A. The host's wait for a checks-only start and a re-run, measured (2026-10-09)

- **Question** (Architecture, issue 3, and Performance, issue 3, one decision): every
  `CreateSession` with `send_when_checked` false had an unmeasured 10-minute timeout, on the host's
  one message pump, where a hang (the bridge read has no enforced timeout) would hold every page
  message for ten minutes.
- **Options**: A: measure, then set: an opt-in perf test (`reviewer/tests/perf`, the repository's
  `perf` marker) times a ticked start, an unticked start and a re-run with a carry on
  `test_prerun_perf.py`'s thousand-group package, and the [W] task times the big assembly as well as
  the small one; the long value is the larger measured re-run with a stated margin, recorded in R2.17
  and RK-10, and if the re-run fits inside 30 s, one 30 s rule applies; ticked starts keep 30 s. B:
  as planned (10 minutes whenever `send_when_checked` is false). C: one 30 s rule now, with no
  measurement (Performance issue 3's B). D: make the long work asynchronous, a `202` once the folder
  is claimed (a feature of its own).
- **Chosen**: A: when the larger measured re-run fits inside 30 s, research says so and one 30 s
  rule covers every call (`TimeoutFor` and `ChecksOnlyTimeout` go); otherwise the long value is that
  re-run with the stated margin. **Default taken 2026-10-09, the owner may revise**: two details 70A
  leaves open are filled by this amendment - the margin's value, three times the re-run, rounded up
  to the next 30 s, and the interim rule that every call keeps 30 s until the measurement lands. The
  seat's unticked-start timing is recorded for information only, since 70A sets the bound from the
  re-run (R2.17). Applied in: R2.6, R2.17, RK-10; data-model section 9;
  `contracts/review-flow.md` section 1; `contracts/recheck.md` section 1; `contracts/pane.md`
  section 12; quickstart Scenarios 4 and 8; the measuring task and the host's timeout tasks.

### 71A. One shared step per repeated tail (2026-10-09)

- **Question** (Code quality, issue 1): the unticked start and the re-run, the waiting apply and the
  re-run's carry, and `review.start` and `review.recheck` were each specified two or three times; the
  carry's copy dropped `prerun.restated`, so after a restart the opening could name findings a
  carried part-roles answer withdrew (FR-023, SC-005), and no test looked.
- **Options**: A: one helper per layer: in the server, `_open_waiting(chat, run)` for both starts,
  over the runner's `close_waiting()` (the Send cache, then the finalization), the only caller of
  `build_send_cache` on these paths; in the runner, `_settle_waiting(applied)` (`drawing_outcomes`,
  `prerun.restated` into `_prerun`, `_opening_changed`), used by the waiting apply and by
  `carry_from`; in the host, `CreateReviewSession(document, runDirectory, retryOf, mode)`, whose mode
  cannot express a re-run that sends at once; and the missing test that the opening after a carried
  part-roles answer names no withdrawn finding. B: the Python helpers only. C: do nothing.
- **Chosen**: A. The issue's third tail - the waiting chat's hold - is superseded by 69A, which
  removes the hold. Applied in: R2.3, R2.6, R2.8, R2.13, R2.17; data-model sections 2, 3 and 9;
  `contracts/review-flow.md` sections 1, 4 and 5; `contracts/recheck.md` sections 1 and 4; the tasks
  of the unticked start, the waiting apply, the re-run and the host.

### 72A. Send and the carry reuse the owners of the state they change (2026-10-09)

- **Question** (Code quality, issue 2): Send's withdrawal of the finalization rows was a second copy
  of `finalize_session`'s; the carry wrote dispositions with a third writer that skipped the
  transition check, and two earlier decisions meeting one finding overwrote each other silently;
  Send's pre-write came before `session.sent`, so the guard had to save again to undo it; and the
  guard's own `error` emit could fail with no rule.
- **Options**: A: extract `withdraw_finalization` from `finalize_session` and call it at Send (no
  step-4 precompute); carry decisions through `set_disposition(..., at=earlier.at)`, sharing
  `record_disposition`'s emit; name the many-to-one carried decision in the not-carried line; emit
  `session.sent` before the pre-write, so the guard only restores memory (four failure points; the
  undo save and its test go); if the guard's own `error` emit fails, log it and let `_play` settle
  `awaiting_send`; the transcript line becomes "Sending to {provider} {model} ...". B: the DRY half
  only. C: do nothing.
- **Chosen**: A. With 69A's adapter build, the guard has five failure points: the factory,
  `configure_provider`, the effort mapping, the `session.sent` emit and the pre-write's save. Two
  earlier decisions that meet one finding are both named and neither is carried. **Default taken
  2026-10-09, the owner may revise**: 72A says only that the many-to-one carried decision is named;
  that neither decision is carried, and that each is named, fills that rule, so no decision silently
  replaces another and `set_disposition` never meets a finding the carry already decided. The
  alternative recorded for the owner: carry the first, by the earlier record's order, and name the
  rest. Applied in: R2.10, R2.11, R2.17, R2.27; data-model sections 3 and 8;
  `contracts/review-flow.md` section 6; `contracts/recheck.md` sections 4 and 5;
  `contracts/records.md` sections 1 and 5; `contracts/words.md` sections 2 and 4; spec FR-029, the
  edge case on moving numbers and the transcript edge case.

### 73A. One home for each fact outside the runner (2026-10-09)

- **Question** (Code quality, issue 4; this plan's questions 1 and 2): the settings file had two
  persist paths with different failure classes, and a box click on a file with a load problem left a
  stale problem on screen; the setting had three members; the chip's "not sent" mark had two
  sources, one lost on a reload; the handoff named a provider for a review never sent; the restored
  line repeated 009's sentence, and the Send sentence repeated the resume sentence's number format.
- **Options**: A: one `PersistSettings(next)` for `settings.save` and the box (it writes, replaces
  `_settings`, clears `_settingsError`; a failed write answers `SettingNotSaved` from either, the label
  reworded); the setting is the held `JsonElement?` plus a settable `bool SendsWhenChecked`; the host
  record is the one source of the chip's mark (`ModelStatus` set at an unticked `review.start`, a
  re-run and the search; `sessions.list` refreshes only those records with the bounded head reader),
  exact after a reload; the handoff gains the model status; the restored line composed from a
  `read_only` lead key, and the Send size sentence reusing `ResumeWords`' formatting. B: the C# settings
  fixes only, the chip mark and the sentences as planned. C: do nothing.
- **Chosen**: A, as worded. The restored line is composed from a `read_only` lead key: feature
  009's `read_only` key is held as its two sentences, `read_only_lead` and `read_only_off`, which
  `Words.read_only` composes into 009's sentence word for word, and a restored not-sent review's
  line is `read_only_lead` followed by the dated Send sentence (`send.restored_line`), composed by
  the backend. 009's second sentence ("Follow-ups, decisions and answers are off.") is not in that
  line; the restored review's questions panel, decisions and follow-up box are off as on 009's
  restore. The amendment first read 73A as composing the line from 009's whole sentence with no key
  split; that reading was withdrawn on the amendment's review, because 73A names a lead key, and is
  recorded among R2.18's alternatives. The line is a few words shorter than the proxy R2.21
  measured, and its words, as every word this feature adds, are defaults the owner may change in the
  words file. Applied in: R2.1, R2.2, R2.18, R2.20, R2.21, R2.22, R2.24, R6; data-model sections 1,
  6, 9 and 10; `contracts/pane.md` sections 1, 2, 7, 8, 11 and 12; `contracts/recheck.md` sections 8
  and 9; `contracts/words.md` sections 1 and 2; `contracts/records.md` section 7; spec User Story 4
  scenario 2, the restoring edge case, FR-026, FR-031 and FR-038.

### 74A. What an unticked start loads, said exactly (2026-10-09)

- **Question** (Code quality, issue 3): R2.5 and the deferred provider's test said an unticked start
  imports no SDK, but `start_review` calls the effort mapping at setup and the rule lives in the
  adapter module, which imports its SDK at its top: the test proved the claim only for a bare import.
- **Options**: A: correct R2.5 and the test: an unticked start imports the provider's SDK module but
  builds no client and reads no key, and the test asserts exactly that (no client constructed, no
  key read), not "no SDK imported". B: move the three effort rules, their tables and error classes
  into one SDK-free module with one table read by the adapters and `DeferredProvider`, re-exported so
  no provider test moves. C: reach the rules through the existing registry, the claim narrowed to the
  bare import. D: leave the claim and the test as written.
- **Chosen**: A. FR-007's promise is no client and no key until Send, which holds; the import is
  said, not avoided. Applied in: R2.5; data-model section 3; `contracts/review-flow.md` section 8;
  the deferred provider's test task.

### 75A. The characterization of a ticked review covers its failures (2026-10-09)

- **Question** (Tests, issue 1; FR-035, the spec's question 3): the characterization played only the
  success path, posted with no new key - a body the host never sends once it writes both fields -
  while four ticked paths this plan rewrites (the factory failure, a first request that fails, a
  failure after a round, Stop) were pinned only by shape checks written on changed code.
- **Options**: A: one pre-feature characterization with five scenarios, each its own golden,
  captured on the pre-feature code in the first commit group: success posted twice (no new keys,
  and the host's real body `{send_when_checked: true, recheck: false}`) against one golden; a ticked
  start whose factory raises; a first request that raises before any round; a failure after one
  completed round; and Stop at the first tool boundary; the shape checks that duplicate it go. B: add
  only the explicit body to the success path. C: do nothing.
- **Chosen**: A. Applied in: R2.28, R4.1; spec FR-035; `contracts/review-flow.md` section 10;
  `contracts/records.md` section 9; the characterization task, and the unticked start's and the
  failed Send's tasks, whose ticked shape checks go.

### 76A. One restart and crash helper for the tests (2026-10-09)

- **Question** (Tests, issue 2; FR-041, RK-4): many cases depend on what a restart, a crash or a kill
  leaves on disk, and none said how each is simulated; a raise inside the same app runs code a kill
  skips (`_run_turn`'s `except`, `write_atomic`'s clean-up) and keeps the earlier chat, which a
  restarted backend does not have.
- **Options**: A: `tests/support/restart.py` with `restarted_app(run_root, settings)` - a fresh
  `create_app` over the same run root (the precedent `test_chat_review_routes.py:205-225`) - and
  `disk_at(folder, hook)` - the folder copied at a named point, nothing raised (the precedent
  `test_remodel_apply_log.py:307-324`); the crash cases of Send, the re-run's cut-offs (including
  inside `write_atomic` after the temporary is written, before `os.replace`) and every restart case
  use them. B: cut by raising a `BaseException` and restore in a fresh app (`finally` blocks still
  run). C: leave it to each test.
- **Chosen**: A. The raise-based failures stay, as FR-041's "a re-run that fails". The cut-off
  inside `write_atomic` is `disk_at`'s one named point, `BEFORE_REPLACE`, not a third helper. Applied
  in: R2.10, R2.17, R4.1, RK-4; spec FR-041; `contracts/recheck.md` sections 2 and 11;
  `contracts/review-flow.md` section 10; `contracts/records.md` section 9; the helper's tasks and
  every crash and restart case.

### 77A. A reload during a Send or an apply (2026-10-09)

- **Question** (Tests, issue 3; FR-017, FR-033, this plan's question 1): the page treated an `error`
  as a Send's end only while `state.sending` was set in page memory; after a reload, a failed Send
  would draw the error card with Retry, or leave no Send block, and no page test reloaded during a
  Send or an apply that then failed.
- **Options**: A: the four page reload cases (a reload while a Send is held, then a failed send; the
  same with one `error` and nothing after it; a reload during an apply that then fails; the chip
  mark after a reload), made to pass with one optional snapshot key, `send_in_flight`, present only
  while `ReviewRun._send_in_flight` is true and omitted otherwise so ticked snapshots and the pane
  fixture do not move, read by the page's restore. B: test only the apply reload and the chip, and
  record the Send reload as a known limitation. C: do nothing.
- **Chosen**: A. `_send_in_flight` is set by the send route as it accepts the Send, so a reload during
  the adapter's build is covered too. Applied in: R2.4, R2.13, R2.21, R2.25, R2.30, RK-17; spec
  FR-033 and the edge cases; data-model sections 2, 3, 6 and 10; `contracts/pane.md` sections 3
  and 5; the snapshot's tasks and the page's Send and restore tasks.

### 78A. The pins that could not fail for what they guard (2026-10-09)

- **Question** (Tests, issue 4): the size the engineer approves was tested only against the code's
  own formula; the found-review search had no case showing names are read first and no seat step
  that reopens SOLIDWORKS while a review waits; and two of the four profile changes were untested.
- **Options**: A: the recording provider keeps each run's raw system prompt, tool specs and first
  message, and the plain Send, the Send after an apply and the Send after a re-run each assert
  `count_tokens(request_prefix(<recorded>))` == `summary.send.input_tokens` (read before Send) ==
  the `session.sent` estimate == `model_status.estimate`; the search's tests add a newest folder of
  another name whose record names this document (never offered); the [W] task closes SOLIDWORKS
  while a review waits, reopens it and records that the review comes back with Send; the re-run's
  tests add the two missing profile cases (the earlier record had no profile; the new settings have
  none). B: the estimate tie and the seat step only. C: do nothing.
- **Chosen**: A. (Issue 4's third point, the deferred provider's import claim, is 74A.) Applied in:
  R2.28, R4.1, R4.2; `contracts/estimate.md` section 7; `contracts/recheck.md` section 11; quickstart
  Scenario 8; the recording provider's, the Send's, the waiting answers', the re-run's, the search's
  and the seat's tasks.

### 79A. A waiting review releases its SOLIDWORKS pipe (2026-10-09)

- **Question** (Performance, issue 1; the spec's edge case "Several reviews waiting at once"): a
  waiting review kept the pipe its live detection opened, and the add-in serves four pipe instances,
  its accept loop ending for good when a listener cannot be made: a few waiting reviews could stop the
  tool service for the rest of the SOLIDWORKS session.
- **Options**: A: `ReviewRun.release_bridge()` closes the bridge transport and keeps the client, at
  the end of an unticked start or a re-run before the chat is registered, and in `_play` when it
  settles `awaiting_send`; tests with a counting fake transport (five waiting assembly reviews hold
  zero pipes; Send reopens). B: fix the ceiling for every chat as well (release on every settle, and
  an accept loop that backs off and retries). C: do nothing.
- **Chosen**: A. The older ceiling on every chat (`docs/review-backlog.md:336-337`, `:436-437`) is
  out of scope, for a separate change. Applied in: R2.6, R2.13, R2.29, RK-16; spec edge case;
  data-model sections 2 and 3; `contracts/review-flow.md` sections 1, 2, 4 and 8; the unticked
  start's and the failed Send's tasks.

### 80A. The found-review search, pinned by its access pattern (2026-10-09)

- **Question** (Performance, issue 2; FR-030): the search's only proof was a 2 s timer a naive scan
  passes, the plan called it a marked perf test where the tasks made it a plain `[Fact]`, and the
  planned head read, opened as `PackageIndex.HeadOf` opens (`FileShare.ReadWrite` only), could make
  the backend's `os.replace` of that file fail, while a second copy of `HeadOf`'s fill loop was
  planned.
- **Options**: A: `FindNotSentReview` takes an injectable head opener (default a `FileStream` with
  `FileShare.ReadWrite | FileShare.Delete`); a test over a 500-folder same-document root asserts
  exactly one file opened, the newest; a stream that throws past 65,536 bytes proves the cap;
  `HeadOf`'s bounded fill loop is extracted into one helper both readers call; the 2 s bound stays a
  plain `[Fact]` and plan.md is corrected. B: tighten the timing test only. C: do nothing.
- **Chosen**: A. The same reader serves 73A's refresh of the marked records. Applied in: R2.20, R4.2,
  RK-6; plan.md's performance goals; spec FR-030; data-model section 9; `contracts/recheck.md`
  section 9; the search's tasks and the head reader's.
