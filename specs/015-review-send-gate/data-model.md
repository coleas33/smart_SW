# Data Model: Send the Review to the Model Only When the Engineer Wants It

**Feature**: `015-review-send-gate` | **Date**: 2026-10-08 | **Plan**: [plan.md](plan.md)

Every new field is optional and additive (FR-036): a settings file, a session, a snapshot or an event
written before this feature loads, and round-trips to its own bytes, and means "send at once, and
sent". Nothing new is written for a review started with the box ticked (FR-032, FR-035). Values below
are fictional.

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
- `[JsonIgnore] public bool? SendWhenChecked` - derived: `true` or `false` when the held token is
  a JSON boolean, otherwise `null`; its setter stores the boolean as a token (`null` clears it);
- `Normalize` adds the one load problem, "send_when_checked '{token}' is not true or false; ticked
  is in use.", when the held token is present and not a boolean, and then clears it, as it replaces
  every other bad field with its default - so the next save drops the bad token;
- `SendsWhenChecked => SendWhenChecked != false`, the one reading every caller uses.

`settings.save` keeps it (the existing `Clone`, which copies the held token). Written by
`send_when_checked.save` only (`contracts/pane.md` section 1).

The host's settings view (`ReviewHost.View`, an allow-list) gains `send_when_checked: boolean`,
always stated (`true` when unset), so the page never has to know the default.

## 2. The chat state (Python, `chat/sessions.py`)

`ChatState.AWAITING_SEND = "awaiting_send"`: the checks are done and saved, the box was unticked, and
no model round of this review has completed. No turn is running.

| From | To | When |
|---|---|---|
| `extracting` | `awaiting_send` | `POST /sessions` with `send_when_checked: false` (or `recheck: true`) finished its checks |
| `awaiting_send` | `running` | `POST /sessions/{id}/send`, an answer route on a waiting run (answers being applied), or a decision or timing write on a waiting run (held for the write) |
| `running` | `awaiting_send` | the applied answers are saved; Send's adapter could not be built, Send failed before any request, or its first request failed before a model round completed; a decision or timing write returned |
| `awaiting_send` | `failed` | an unrecoverable error (every state can fail) |

Every other move from `awaiting_send` is refused (`InvalidTransitionError`). `finished` stays `ended` or
`failed` only, so a waiting chat still holds its run folder (`_claim_run_dir`). `_require_idle` accepts
`awaiting_send`; `_play` settles `awaiting_send` while `run.awaiting_send`, else as today. The
disposition and timing routes move a waiting chat to `running` on the event loop, with no `await`
after `_require_idle`, and back in a `finally` once their write returns, so no Send, answer or
Settings save runs beside the write (research R2.12); a chat in any other state takes today's
path.
`ChatSession.public()` reports the state; nothing else in it changes.

Two paths use moves that exist today. An unticked start (or a re-run) whose finalization raises moves
its chat `extracting -> failed` before the chat is ever registered, so it holds no folder. An apply
that fails while waiting moves the chat `running -> failed` through `_play`, the folder's record as
it was before the apply (`contracts/review-flow.md` section 4). A re-run's claim **adopts** a live
chat on its folder that is `awaiting_send` instead of refusing it, and refuses a folder whose re-run
is still running: `ChatServer._rechecking: set[Path]` holds each re-run's folder from its claim to its
answer, because its chat is registered only after its finalization (`contracts/recheck.md` section 2).

Which the page shows - "waiting" or "running" - is read from the summary's `send` block (section 6),
present exactly while `run.awaiting_send`, which is true from the checks' end to the start of a Send,
and again after a Send that failed before any request or whose first request failed.

## 3. The run (Python, `agent/runner.py`)

`ReviewRun` gains:

| Member | Type | Meaning |
|---|---|---|
| `awaiting_send` | `bool` | the review waits for Send (section 2) |
| `_send_in_flight` | `bool` | a Send's opening turn is running and no round of it has completed |
| `_prerun` | `PrerunResult \| None` | the pre-run's result, kept (and replaced after a restate) so the opening can be rebuilt |
| `_standards_gap` | `NotEvaluated \| None` | what `attach_standards` returned, kept for the same reason |
| `_opening_changed` | `bool` | answers were applied while waiting, so the frozen opening no longer stands |
| `_send_cache` | `SendCache \| None` | `{opening: str, estimate: SendEstimate, named_ids: list[str]}`: what Send would send next, its counted size and the ids its digest names; built on a worker by `build_send_cache()` (below) and replaced by one assignment; `None` before the first build |
| `_send_error` | `SendFailure \| None` | a Send that failed before any request (research R2.10): held in memory only, shown as the Send block's failure line until the next Send; never written to `model_status`, because no request was made |
| `carried` | `Carried \| None` | a re-run's id maps (section 8), kept so a second claim of the folder can adopt this chat and answer them again; `None` for a run that is not a re-run |
| `attach_provider(adapter)` | method | configures the adapter as setup would have: `configure_provider`, then steps numbered from the session's count; called by `send`'s prepare half, which does not yet make the adapter the run's provider (its commit half does, replacing the `DeferredProvider`) |
| `send(adapter)` | method | `contracts/review-flow.md` section 6: a prepare half that changes nothing (configure the adapter, read the cache, build the `session.sent` body, compute the withdrawn coverage); a commit half (the pre-write, `session.sent`, the withdrawal of the previous finalization's rows by identity with `_finalized` cleared, the adapter made the run's provider); the opening turn; and a guard over both halves that undoes the pre-write and returns the run to waiting |
| `build_send_cache()` | method | builds `_send_cache` from `opening_at_send()` and `first_request_estimate()`; called on a worker at the unticked start and a re-run (before the finalization) and by the waiting apply (before its finalization), never by a route |
| `opening_at_send()` | method | the frozen opening, or the rebuilt one when `_opening_changed` (`contracts/review-flow.md` section 5); called only by `build_send_cache` |
| `first_request_estimate()` | method | section 7; called only by `build_send_cache` |
| `carry_from(earlier)` | method | the re-run's carry (`contracts/recheck.md` section 4); in memory only, it writes nothing |

`start_review(..., send_when_checked: bool = True, earlier: ReviewSession | None = None)`: two new
arguments (`earlier` only with `send_when_checked=False`, else `ValueError`). Both default to today.

`agent/events.local_now() -> datetime` (new, beside `utc_now`): `datetime.now(UTC).astimezone()`, the
backend's wall clock with its UTC offset. It stamps the three model-status times (section 4), and is
the one clock a fixture generator patches for them (research R2.15, R2.25).

`DeferredProvider` (`agent/providers/deferred.py`): `name: ProviderName`, `model: str`,
`effort_mapping(effort)` (the adapter's own rule), `start_steps_at(index)` (kept), `run` and
`for_presentation` raise `ProviderNotSent`. Not `ModelViewAware`, `PromptCacheAware` or
`PriorReasoningAware`, so `configure_provider` does nothing to it.

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
| `checked_at` | `datetime` | when the checks finished: the first finalization's end, stamped by `local_now` (its offset kept); a re-run stamps its own |
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
| `state` | `"waiting" \| "restored"` | waiting: a live run waits; restored: shown from its run folder, the next action re-runs it |
| `session_id` | `str` | the review session the block describes (the snapshot has no session key and gains none); the page compares it with a re-run's answer (`contracts/recheck.md` section 7) |
| `input_tokens` | `int \| None` | the first request's counted size; `None` when not counted or restored |
| `approximate` | `bool` | the provider is Gemini |
| `text` | `str` | the size sentence (`contracts/words.md` section 1) |
| `failure` | `str \| None` | the last failure's line: a Send that failed before any request (`_send_error`, words `send.not_started`), else the last recorded failed request when the state is `send_failed` (`send.failed`) |
| `restored_text` | `str \| None` | the restored-review line, state `restored` only |
| `rerun_failed_text` | `str \| None` | the line a failed re-run prints, state `restored` only |

`review_ranking(session, package, *, usage=None, send=None)`: the attention and snapshot routes pass
`run.send_input()` (`{state, input_tokens, provider, send_error}`, read from `_send_cache` and
`_send_error` and computing nothing) while the run waits; the disk route passes `restored` for a
not-sent record. `ReviewSummary.resume_text` is the words file's `send.apply_answers`
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
| an Accept, Reject or Defer | `findings.finding_subject_key`: the same check, sorted component ids, drawing places with their persistent references, entity ids among the inputs, and configuration (the replay's key for renumbered findings; it tells two `hole.coaxiality` findings on one pair of components apart, which `_verdict_key` does not) | no re-run finding has the key, or more than one has it |
| a drawing read's outcome | the earlier record's `drawing_outcomes` | never: carried verbatim |
| the live detection | the earlier record's `live_detection`, recorded as one carried step at its `step_index` | never: carried, not repeated |
| the drawing-read capability | the earlier record's `drawing_read`, set on the context's cache **and** on the re-run's session (`ToolContext.carry_drawing_read`), so the re-run's record keeps it for the next re-run | `None` there: asked lazily, as today |
| the Standards profile | not carried: the re-run grades with the profile in effect; its identity is compared with the earlier record's `model_status.profile` | a different path or sha256: named in `coverage.recheck` (default; research R6 question 3) |
| the interference rows the first run could not write | not carried: with `persist_error`, the reviewed configuration's rows are removed from the in-memory package as the first run removed them, so the dump's stale rows are not judged | always, when `persist_error` is set: `INTERFERENCE_ROWS_NOT_CARRIED` |
| a drawing outcome an unfinished read lost | nothing to carry: an earlier **open** drawing question whose drawing is now in the package and whose file no `drawing_outcomes` entry names | always: named in `coverage.recheck` (research R2.13) |
| the four human timing inputs | the earlier record's `timing` (baseline, supervision, verification, false alarms) | never: carried whole |
| the model status | the earlier record's `model_status`: `state`, `document` and `failures` whole; `rechecked_from` set; `checked_at` the re-run's | never |

All of it is carried in memory; the carry writes nothing to disk, and the re-run's finalization is its
one write of `session.json`. The `POST /sessions` 201 body of a re-run carries `carried: {requests:
{old id: new id}, findings: {old id: new id}}` for every earlier request and finding that matched one
item, answered and decided or not; the run keeps it (`ReviewRun.carried`) for an adoption. Items not
carried are named in one unresolved coverage row, check `coverage.recheck`.

## 9. The host's records (C#, `Review/ReviewHost.cs`)

`SessionRecord` gains `ModelStatus: string?` - `not_sent` or `send_failed` for a review the host
found in the run root after SOLIDWORKS reopened (`contracts/recheck.md` section 9), `null` otherwise -
and the `sessions.list` item gains `model_status` when it is set. A found review's `ChatId` is its
record's `session_id` (stable, so a second search tracks the same record), its `StartedAt` its
`checked_at`. A re-run replaces the record of the review it re-ran: same folder and document, the new
chat id, `StartedAt` now.

`NewSessionRequest` gains `SendWhenChecked: bool` (default `true`) and `Recheck: bool` (default
`false`); `ChatSessionHandle` gains `Carried: JsonElement?` through an optional constructor parameter,
so no `IBackendClient` fake changes. `BackendClient.TimeoutFor(request)` is the call's timeout: 10
minutes (default) whenever `SendWhenChecked` is false - an unticked start and a re-run, each of which
runs the checks and a finalization inside the call - and the client's 30 s for a ticked start and
every other call.

## 10. Page state (`Review/ReviewPage/app.js`)

| Field | Meaning |
|---|---|
| `state.notSent` | chat id to `true` for every review this page load has seen wait (from `review.started`, a snapshot's `send` block, a found item's `model_status`); cleared at that review's first `usage` after Send |
| `state.sending` | a Send was pressed and neither a `usage` nor an `error` event of it has arrived |
| `state.rechecking` | a `review.recheck` is in flight |

The status line, Stop, the follow-up box, the questions panel's button and the Send block are drawn from
these and from `state.summary.send` (`contracts/pane.md`).
