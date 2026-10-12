# Data Model: Send the Review to the Model Only When the Engineer Wants It

**Feature**: `015-review-send-gate` | **Date**: 2026-10-08 | **Plan**: [plan.md](plan.md)

Every new field is optional and additive (FR-036): a settings file, a session, a snapshot or an event
written before this feature loads, and round-trips to its own bytes, and means "send at once, and
sent". Nothing new is written for a review started with the box ticked (FR-032, FR-035). Values below
are fictional. Amended on 2026-10-09 by the owner's plan review (decisions 68A to 80A; research R7):
sections 1 to 3, 6, 8, 9 and 10.

## 1. The send setting (C#, per Windows user)

`%APPDATA%\SwReview\settings.json` (`Settings/UserSettings.cs`), schema
`specs/002-task-pane-assistant/contracts/settings.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `send_when_checked` | `boolean`, optional | Absent, `null` or not a boolean: ticked (`true`). A non-boolean is one load problem, "send_when_checked '{value}' is not true or false; ticked is in use.", and every other field loads as today. Written only once the engineer has changed the box (omitted while no token is held; a bad token is cleared by `Normalize`, below). Never a lever name (`test_no_lever_in_pane_settings.py`). |

The file's token is kept raw, because a `System.Text.Json` converter has no access to the
`problems` list `Normalize(mode, problems)` fills (`UserSettings.cs:400`; `Load` creates the list
after the deserializer returns, `:253-255`), so a converter that read a bad token as `null` would
lose it before it could be reported (*second review, 2026-10-09*):

- `[JsonPropertyName("send_when_checked")] public JsonElement? SendWhenCheckedValue` - the token as
  the file holds it (absent and JSON `null` both read as no value); written back as it is held;
- `[JsonIgnore] public bool SendsWhenChecked` - the one reading every caller uses: `false` exactly
  when the held token is JSON `false`, otherwise `true`; its setter stores the boolean as a token.
  Two members, not three (owner decision 73A): no caller needs a `bool?` beside it;
- `Normalize` adds the one load problem, "send_when_checked '{token}' is not true or false; ticked
  is in use.", when the held token is present and not a boolean, and then clears it, as it replaces
  every other bad field with its default - so the next save drops the bad token.

`settings.save` keeps it (the existing `Clone`, which copies the held token). Both writers of the
file - `settings.save` and `send_when_checked.save` - go through one `ReviewHost.PersistSettings(next)`
(73A): it writes the file (`UserSettings.Save`, atomic), replaces `_settings` and clears
`_settingsError`, and a failed write is `SettingNotSaved` from either handler, the stored settings
standing (`contracts/pane.md` section 1). `settings.save` then restarts the backend, as today; the
box's save does not.

The host's settings view (`ReviewHost.View`, an allow-list) gains `send_when_checked: boolean`,
always stated (`true` when unset), so the page never has to know the default.

## 2. The chat state (Python, `chat/sessions.py`)

`ChatState.AWAITING_SEND = "awaiting_send"`: the checks are done and saved, the box was unticked, and
no model round of this review has completed. No turn is running.

| From | To | When |
|---|---|---|
| `extracting` | `awaiting_send` | `POST /sessions` with `send_when_checked: false` (or `recheck: true`) finished its checks |
| `awaiting_send` | `running` | `POST /sessions/{id}/send` (the route, on the event loop, before it submits Send to the chat's worker), or an answer route on a waiting run (answers being applied) |
| `running` | `awaiting_send` | the applied answers are saved; a Send failed before any request (its adapter's build included, 69A) or its first request failed before a model round completed |
| `awaiting_send` | `failed` | an unrecoverable error (every state can fail) |

Every other move from `awaiting_send` is refused (`InvalidTransitionError`). `finished` stays `ended` or
`failed` only, so a waiting chat still holds its run folder (`_claim_run_dir`). `_require_idle` accepts
`awaiting_send`; `_play` settles `awaiting_send` while `run.awaiting_send`, else as today, and when it
settles `awaiting_send` it releases the run's SOLIDWORKS pipe (`ReviewRun.release_bridge()`, section 3;
owner decision 79A). On a waiting chat the disposition and timing routes run their write on the
chat's one worker thread (`ChatServer._on_worker(chat, call)`, awaited) and leave the chat
`awaiting_send`: a Send or an answer accepted meanwhile queues behind the write on the same worker,
so no two threads write one session, and nothing moves the chat or touches its stop flag outside
`_play` (owner decision 69A; research R2.12). A chat in any other state takes today's path.
`ChatSession.public()` reports the state; nothing else in it changes.

An unticked start and a re-run end in one helper, `ChatServer._open_waiting(chat, run)` (owner
decision 71A): on the thread pool `run.close_waiting()` (section 3) and `_render_run`, then
`run.release_bridge()`; then, on the loop, attach, register and `extracting -> awaiting_send`.

Two paths use moves that exist today. An unticked start (or a re-run) whose finalization raises moves
its chat `extracting -> failed` before the chat is ever registered, so it holds no folder, and its run
is closed (`run.close()`), so it holds no pipe either (79A). An apply
that fails while waiting moves the chat `running -> failed` through `_play`, the folder's record as
it was before the apply (`contracts/review-flow.md` section 4). A re-run's claim **adopts** a live
chat on its folder that is `awaiting_send` instead of refusing it, and refuses a folder whose re-run
is still running: `ChatServer._rechecking: set[Path]` holds each re-run's folder from its claim to its
answer, because its chat is registered only after its finalization (`contracts/recheck.md` section 2).

Which the page shows - "waiting" or "running" - is read from the summary's `send` block (section 6),
present exactly while `run.awaiting_send`, which is true from the checks' end until step 7 of a Send's
commit half (`contracts/review-flow.md` section 6), and again after a Send that failed before any request or whose first request failed;
and, after a reload, from the snapshot's `send_in_flight` (section 6; owner decision 77A).

## 3. The run (Python, `agent/runner.py`)

`ReviewRun` gains:

| Member | Type | Meaning |
|---|---|---|
| `awaiting_send` | `bool` | the review waits for Send (section 2) |
| `_send_in_flight` | `bool` | a Send was accepted and has neither completed a model round nor returned the run to waiting: set by the send route on the event loop as it moves the chat to `running`; cleared at the first `usage`, and by the guard and by the failure branch, each before its `error` (`contracts/review-flow.md` section 6). The snapshot carries `send_in_flight: true` exactly while it is set (section 6; 77A) |
| `_prerun` | `PrerunResult \| None` | the pre-run's result, kept (and replaced after a restate) so the opening can be rebuilt |
| `_standards_gap` | `NotEvaluated \| None` | what `attach_standards` returned, kept for the same reason |
| `_opening_changed` | `bool` | answers were applied while waiting, so the frozen opening no longer stands |
| `_send_cache` | `SendCache \| None` | `{opening: str, estimate: SendEstimate, named_ids: list[str]}`: what Send would send next, its counted size and the ids its digest names; built on a worker by `build_send_cache()` (below) and replaced by one assignment; `None` before the first build |
| `_send_error` | `SendFailure \| None` | a Send that failed before any request (research R2.10): held in memory only, shown as the Send block's failure line until the next Send; never written to `model_status`, because no request was made |
| `attach_provider(adapter)` | method | configures the adapter as setup would have: `configure_provider`, then steps numbered from the session's count; called by `send`'s prepare half, which does not yet make the adapter the run's provider (its commit half does, replacing the `DeferredProvider`) |
| `send(build_adapter)` | method | `contracts/review-flow.md` section 6, on the chat's worker: a prepare half that changes nothing (build the adapter by calling `build_adapter`, the route's `provider_factory` call - owner decision 69A; configure it; read the cache; build the `session.sent` body); a commit half (`session.sent`, then the pre-write, then `withdraw_finalization` with `_finalized` cleared and the adapter made the run's provider - owner decision 72A); the opening turn; and a guard over both halves that restores the model status in memory, writes nothing, and returns the run to waiting |
| `close_waiting()` | method | `build_send_cache()`, then `finalize()`: the end of every path that leaves a run waiting - the unticked start and a re-run (through `ChatServer._open_waiting`) and the waiting apply - and the only caller of `build_send_cache` on them (owner decision 71A) |
| `_settle_waiting(applied)` | method | what applied answers change on a waiting run before `close_waiting`: each `ConfirmedRead` appended to `drawing_outcomes`, the restated tools' calls replaced in `_prerun` (`prerun.restated`), `_opening_changed` set; called by the waiting apply and by `carry_from`, so a carried part-roles answer restates the pre-run too (71A) |
| `release_bridge()` | method | closes the context's bridge transport and keeps the client (`BridgeClient.close()` closes only the transport, `bridge/client.py:569-571`; the named-pipe transport opens again on its next request), so the circuit breaker and the cached drawing-read answer survive; called by `_open_waiting` before the chat is registered and by `_play` when it settles `awaiting_send` (owner decision 79A) |
| `build_send_cache()` | method | builds `_send_cache` from `opening_at_send()` and `first_request_estimate()`; called only by `close_waiting()`, on a worker, never by a route |
| `opening_at_send()` | method | the frozen opening, or the rebuilt one when `_opening_changed` (`contracts/review-flow.md` section 5); called only by `build_send_cache` |
| `first_request_estimate()` | method | section 7; called only by `build_send_cache` |
| `carry_from(earlier)` | method | the re-run's carry (`contracts/recheck.md` section 4); in memory only, it writes nothing; it ends with `_settle_waiting(applied)` |

`withdraw_finalization(review, written)` (`agent/runner.py`, new module function): the withdrawal
`finalize_session` makes at its start of the rows a previous finalization appended (`runner.py:619-627`),
extracted so `finalize_session` and Send's commit half call the one body (owner decision 72A).

`start_review(..., send_when_checked: bool = True, earlier: ReviewSession | None = None)`: two new
arguments (`earlier` only with `send_when_checked=False`, else `ValueError`). Both default to today.

`agent/events.local_now() -> datetime` (new, beside `utc_now`): `datetime.now(UTC).astimezone()`, the
backend's wall clock with its UTC offset. It stamps the three model-status times (section 4), and is
the one clock a fixture generator patches for them (research R2.15, R2.25).

`DeferredProvider` (`agent/providers/deferred.py`): `name: ProviderName`, `model: str`,
`effort_mapping(effort)` (the adapter's own rule), `start_steps_at(index)` (kept), `run` and
`for_presentation` raise `ProviderNotSent`. Not `ModelViewAware`, `PromptCacheAware` or
`PriorReasoningAware`, so `configure_provider` does nothing to it. It reads no key and builds no SDK
client. Its effort rule is the adapter module's `effort_mapping_for`, and `start_review` calls
`effort_mapping` at setup (`runner.py:1581`), so an unticked start does import the provider's SDK
module, which those modules import at their top (owner decision 74A; research R2.5).

## 4. The session record (Python, `report/session.py`; 001 `review-session.schema.json`)

| Record | New field | Type | Omitted when |
|---|---|---|---|
| `ReviewSession` | `model_status` | `ModelStatus \| None`, declared after `provider_info` | `None` (every ticked review) |
| `ReviewSession` | `live_detection` | `LiveDetectionRecord \| None` | `None` |
| `ReviewSession` | `drawing_outcomes` | `list[DrawingOutcome]` | empty |

**`ModelStatus`** (`extra="forbid"`)

| Field | Type | Rule |
|---|---|---|
| `state` | `"not_sent" \| "send_failed" \| "sent"` | not sent: no request was made; send failed: a request was made and no model round completed; sent: a round completed |
| `document` | `{path: str, configuration: str}` | the reviewed root document, as the snapshot names it (`report/snapshot._root_document`), so the host can find the review after SOLIDWORKS reopens |
| `checked_at` | `datetime` | required when the in-memory model status is constructed: initially `local_now()` after setup's checks; replaced by the first finalization's end before any record is saved (its offset kept). A later waiting apply keeps that first end; a re-run stamps its own |
| `profile` | `{path: str, sha256: str \| None} \| None` | the Standards profile the checks graded with: the path the review was given and the sha256 of its bytes when it loaded (`ProfileIdentity`, `checks/standards/profile.py`), `sha256` null when it was refused; omitted when the review had none. A re-run compares it with the profile in effect and names a change (`contracts/recheck.md` section 4); a re-run records its own |
| `rechecked_from` | `UUID \| None` | a re-run: the earlier record's `session_id`; omitted when `None` |
| `failures` | `list[SendFailure]` | every failed attempt, oldest first; omitted when empty. A re-run carries the earlier record's list whole, and its `state` with it (`send_failed` stays `send_failed`) |
| `sent_at` | `datetime \| None` | sent: when Send was pressed for the attempt that got an answer |
| `estimate` | `SendEstimate \| None` | sent: the estimate shown at Send |
| `opening_finding_ids` | `list[str]` | sent: the finding ids the opening named, in its order; omitted when empty |

`SendFailure {at: datetime, error_class: str, reason: str}` (the reason redacted). Before a Send's
first request an entry `{at, error_class: "Interrupted", reason: "the backend stopped before the model
answered"}` is written and the state set `send_failed`; the first completed round drops it and sets
`sent`; a failed first request replaces it with the provider's class and redacted message.

**Times.** `checked_at`, `sent_at` and each failure's `at` are stamped by `local_now` and keep their
UTC offset. Every sentence, header line and chip that prints one prints the stored wall clock as it
is, never converted to the zone of the machine rendering it (research R2.15).

`SendEstimate {input_tokens: int | None, encoding: "o200k_base", approximate: bool}`.

**`LiveDetectionRecord`**: exactly `prerun.LiveOutcome`'s fields - `configuration: str`,
`settings: dict[str, Any]`, `step_index: int | None`, `not_attempted: "no_bridge" | "not_assembly" |
None`, `groups: int`, `rows_detected: int`, `rows_added: int`, `rows_collided: int`, `error: str | None`,
`persist_error: str | None`. `LiveOutcome.as_record()` and `LiveOutcome.from_record()` convert; a test
fails when a dataclass field is not carried. Written by `start_review` for an unticked review whose
pre-run ran.

**`DrawingOutcome`** `{file: str, outcome: str}`: one per drawing file a confirmed read asked for while
the review waited (or carried by a re-run), rendered "Drawing {file}: {outcome}".

**Timing.** For a session with a `model_status`, `unattended_runtime_minutes` is
`checked_at - started_at`, plus `ended_at - sent_at` once sent: the wait, and the minutes spent
answering while waiting, are not running time (FR-011). Otherwise as today.

**Finalization reasons.** For a session whose `model_status.state` is not `sent`, an open model-owned
checklist item reads "{title}: not reviewed, because the review was not sent to the model"; one whose
blocking question was answered keeps feature 013's "{title}: still open after {id} was answered:
'{answer}'" and adds "; the review was not sent to the model".

**Write.** `save_session` writes through `atomic.write_atomic` (a temporary in the folder, then
`os.replace`).

## 5. Events (002 `chat-events.schema.json`)

| Event | Change |
|---|---|
| `session.started` | optional `send_when_checked: false`, present only for a review started with the box unticked |
| `session.sent` | **new**: `{provider, model, effort_mapping, estimate?: SendEstimate}`, emitted once per Send attempt, before its first request |

`EventType` (`agent/providers/__init__.py`) gains `"session.sent"`. No other event changes; a checks-only
review writes no `turn.ended`.

## 6. The summary's Send block (`report/summary.py`)

`ReviewSummary.send: SendBlock | None`, omitted when `None` (so the pane fixture keeps its bytes).

| Field | Type | Meaning |
|---|---|---|
| `state` | `"waiting" \| "restored"` | waiting: a live run waits; restored: shown read-only from its run folder, and Send re-runs it first (owner decision 68A) |
| `input_tokens` | `int \| None` | the first request's counted size; `None` when not counted or restored |
| `approximate` | `bool` | the provider is Gemini |
| `text` | `str` | the size sentence (`contracts/words.md` section 1); `{tokens}` is written by the one formatter `ResumeWords.of` uses (`summary.tokens_text`, 73A) |
| `failure` | `str \| None` | the last failure's line: a Send that failed before any request (`_send_error`, words `send.not_started`), else the last recorded failed request when the state is `send_failed` (`send.failed`) |
| `rerun_failed_text` | `str \| None` | the line a failed re-run prints, state `restored` only |

The block carries no `session_id` and no restored line (68A, 73A). A restored not-sent review is
read-only, so its line under the status line is the snapshot's `read_only_reason`: for a record that
says `not_sent` or `send_failed`, the words file's `read_only_lead`, a space, and `send.restored_line`
with `{when}` (`contracts/words.md` section 1), composed by the backend. `read_only_lead`, the first
sentence of feature 009's read-only line, is a key of its own, which `Words.read_only` composes with
`read_only_off` into 009's sentence, so the two lines never drift (73A).

**The snapshot's `send_in_flight`** (owner decision 77A): `review_snapshot(..., send_in_flight=False)`
writes `"send_in_flight": true` only while the run's `_send_in_flight` is set, and omits the key
otherwise, so a ticked review's snapshot, a waiting one's and the pane fixture keep their bytes. The
page's restore reads it (section 10).

`review_ranking(session, package, *, usage=None, send=None)`: the attention and snapshot routes pass
`run.send_input()` (`{state, input_tokens, provider, send_error}`, read from `_send_cache` and
`_send_error` and computing nothing) while the run waits; the disk route passes `restored` for a
not-sent record, with the composed `read_only_reason`. `ReviewSummary.resume_text` is the words file's `send.apply_answers`
while a `send` block is present, else today's.

## 7. The first-request estimate

`request_prefix(system, tools, opening) -> str` (`agent/runner.py`): `system + json.dumps([{name,
description, parameters} for tool in tools]) + opening`, the replay's `_prefix` moved, byte for byte.
`ReviewRun.first_request_estimate()` is `count_tokens(request_prefix(self.system, self.tools,
self.opening_at_send()))`, `None` on `TokenizerUnavailable`; counted by `build_send_cache()` on a
worker whenever the opening can change (the unticked start, a re-run, an apply while waiting), and
read from the cache everywhere else. `approximate` is `provider == "gemini"`.

## 8. The re-run's carry (`contracts/recheck.md`)

| Item | Matched by | Not carried when |
|---|---|---|
| an answered code question | `checks/questions.asks_same(earlier, new)`: the same `question`, `options` and `entity_ids` in order | no re-run question asks the same thing (except a drawing question whose drawing the earlier read put in the package: only its outcome line is carried, and nothing is named), or more than one does |
| an Accept, Reject or Defer | `findings.finding_subject_key`: the same check, sorted component ids, drawing places with their persistent references, entity ids among the inputs, and configuration (the replay's key for renumbered findings; it tells two `hole.coaxiality` findings on one pair of components apart, which `_verdict_key` does not). Applied through `report/dispositions.set_disposition(..., at=earlier.at)` and announced with the event `record_disposition` emits, one function both call (owner decision 72A) | no re-run finding has the key, or more than one has it, or another earlier decision matches the same re-run finding (none of them is carried, 72A) |
| a drawing read's outcome | the earlier record's `drawing_outcomes` | never: carried verbatim |
| the live detection | the earlier record's `live_detection`, recorded as one carried step at its `step_index` | never: carried, not repeated |
| the drawing-read capability | the earlier record's `drawing_read`, set on the context's cache **and** on the re-run's session (`ToolContext.carry_drawing_read`), so the re-run's record keeps it for the next re-run | `None` there: asked lazily, as today |
| the Standards profile | not carried: the re-run grades with the profile in effect; its identity is compared with the earlier record's `model_status.profile` | a different path or sha256: named in `coverage.recheck` (default; research R6 question 3) |
| the interference rows the first run could not write | not carried: with `persist_error`, the reviewed configuration's rows are removed from the in-memory package as the first run removed them, so the dump's stale rows are not judged | always, when `persist_error` is set: `INTERFERENCE_ROWS_NOT_CARRIED` |
| a drawing outcome an unfinished read lost | nothing to carry: an earlier **open** drawing question whose drawing is now in the package and whose file no `drawing_outcomes` entry names | always: named in `coverage.recheck` (research R2.13) |
| the four human timing inputs | the earlier record's `timing` (baseline, supervision, verification, false alarms) | never: carried whole |
| the model status | the earlier record's `model_status`: `state`, `document` and `failures` whole; `rechecked_from` set; `checked_at` the re-run's | never |

All of it is carried in memory; the carry writes nothing to disk, and the re-run's finalization is its
one write of `session.json`. Items not carried are named in one unresolved coverage row, check
`coverage.recheck`. No id map leaves the backend: Send is the only re-run trigger, so nothing on the
page refers to an earlier id once the re-run answers (owner decision 68A).

## 9. The host's records (C#, `Review/ReviewHost.cs`)

`SessionRecord` gains `ModelStatus: string?` - `not_sent` or `send_failed` while the review waits for
Send, `null` otherwise - and the `sessions.list` item gains `model_status` when it is set. The host
record is the one source of a chip's "not sent" mark (owner decision 73A): `ModelStatus` is set to
`not_sent` by an unticked `review.start`, kept by a re-run (the earlier record's state), and set by the
search for a review found after SOLIDWORKS reopened (`contracts/recheck.md` section 9). On every
`sessions.list` the host refreshes only the records whose `ModelStatus` is set, each with one bounded
head read of its `session.json` (`RunFolders.ReadModelStatus`, the reader the search uses): a record
whose file now says `sent` loses the mark, and a read that finds nothing (no `session.json`, an
unreadable file, or no `model_status` within 64 KiB) keeps it, so only a head that says `sent` clears a
mark; the mark is exact after a page reload, at one bounded read per waiting record. A found review's `ChatId` is its record's `session_id` (stable, so a second search
tracks the same record), its `StartedAt` its `checked_at`. A re-run replaces the record of the review
it re-ran: same folder and document, the new chat id, `StartedAt` now.

`ReviewHost.CreateReviewSession(document, runDirectory, retryOf, mode)` (owner decision 71A) is the
one body `review.start` and `review.recheck` share: the drawing refusal, the backend check, the request
built from the settings, the catch and its status, the record kept and the ready status. For
`ReviewMode.Recheck` only, it checks the document binding (the active document is `document`: path
ignoring case, configuration exactly; `ReviewNotActive`) between the drawing refusal and the backend
check, so `contracts/recheck.md` section 1's refusal order holds; for `Send` and `Wait` the document
is the active one, and no binding check runs. `mode` is
`ReviewMode { Send, Wait, Recheck }`, so the host cannot build the one pair the backend refuses (a
re-run that sends at once). `NewSessionRequest` gains `Mode` (default `Send`), optional, so no
`IBackendClient` fake changes; `BackendClient.CreateSession` writes the wire's two booleans from it -
`send_when_checked: true, recheck: false` for `Send`, `false, false` for `Wait`, `false, true` for
`Recheck`. `ChatSessionHandle` does not change. `BackendClient.TimeoutFor(request)` is the call's
timeout: `ChecksOnlyTimeout` for `Wait` and `Recheck`, and the client's 30 s `CallTimeout` for `Send`
and every other call. `ChecksOnlyTimeout` is set from a measurement, not chosen (owner decision 70A;
research R2.17, RK-10): when the larger re-run timed by `tests/perf/test_send_gate_perf.py` fits inside
30 s, there is one 30 s rule and `TimeoutFor` and `ChecksOnlyTimeout` go; otherwise `ChecksOnlyTimeout`
is that re-run with its stated margin (three times it, rounded up to the next 30 s: a default the
owner may revise, research R2.17).

`RunFolders.ReadModelStatus(runDirectory, openHead)` reads the top-level `model_status` of a folder's
`session.json` within its first 64 KiB with `Utf8JsonReader` and stops there. `openHead` is injectable;
its default opens a `FileStream` with `FileShare.ReadWrite | FileShare.Delete`, so the backend's
`os.replace` of that file never fails while the host reads it (owner decision 80A). It fills its
buffer through `PackageIndex.FillHead(stream, maxBytes)`, the bounded fill loop extracted from
`PackageIndex.HeadOf` (`extractor/SwReview.Extractor/Dump/PackageIndex.cs:266-291`), which both readers
call. `RunFolders.FindNotSentReview` (the search) takes the same `openHead`.

## 10. Page state (`Review/ReviewPage/app.js`)

| Field | Meaning |
|---|---|
| `state.sentSeen` | chat ids whose first `usage` after Send this page has seen since the host's last `sessions` answer: their chips drop the " · not sent" mark at once, before the next list's refreshed record agrees; cleared at each `sessions` answer (owner decision 73A). The mark itself is the `sessions` item's `model_status`, never page memory, so it is exact after a reload |
| `state.sending` | a Send was pressed, or a restore read the snapshot's `send_in_flight` (owner decision 77A), and neither a `usage` nor an `error` event of it has arrived |
| `state.rechecking` | a `review.recheck` is in flight |

Between `review.started {send_when_checked: false}` and the first summary, the status line reads the
waiting state from that reply.

The status line, Stop, the follow-up box, the questions panel's button and the Send block are drawn from
these and from `state.summary.send` (`contracts/pane.md`).
