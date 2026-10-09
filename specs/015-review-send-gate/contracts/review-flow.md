# Contract: The Review Flow with a Send Gate

Normative for the backend half of the box: starting a checks-only review, the `awaiting_send` state,
Send, the engineer's work while a review waits, the opening the model reads at Send, a failed first
request, the provider a waiting review holds, and the two event changes (FR-003, FR-006 to FR-011,
FR-014 to FR-020, FR-023 to FR-025, FR-035). Amends 002 `chat-api.md`, `data-model.md` section 3 and
`chat-events.schema.json`; 008 `checks-first.md` sections 1 and 4 and `answer-batch.md` section 1;
009 FR-015; 011 `confirmed-open.md` section 1; 013 `part-roles.md` section 9 and
`drawing-capability.md` section 6.

## 1. `POST /sessions`

Two optional body fields; everything else is 002 `chat-api.md`'s row, unchanged.

| Field | Type | Absent means | Rule |
|---|---|---|---|
| `send_when_checked` | boolean | `true` | anything but a boolean is `400 InvalidRequest` naming the field |
| `recheck` | boolean | `false` | `true` re-runs the checks of the folder's waiting review (`recheck.md`); `true` with `send_when_checked: true` is `400 InvalidRequest` ("a re-run always waits for Send") |

**`send_when_checked: true`** (the default, and every host before this feature): today's path, byte
for byte - the adapter is built first (no key: `502` before any check), the checks run, the chat
moves to `running`, `run.start` is submitted, `201`.

**`send_when_checked: false`**, in order:

1. the run folder is claimed and resolved as today;
2. `_start_review` builds a `DeferredProvider` from the request's settings (section 8) - no key is
   read and no SDK client is built - and calls `start_review(..., send_when_checked=False)`;
   the pre-run, the part-roles question and the drawing questions run exactly as they do today
   before a first request (008 `checks-first.md` sections 1 and 2);
3. `start_review` emits `session.started` with `send_when_checked: false` (section 7), records
   `model_status {state: "not_sent", document}` and, when the pre-run ran, `live_detection`
   (`records.md` section 1), and the run keeps its `PrerunResult` and standards gap (section 5);
4. on the thread pool, all **before** the chat is attached and registered: the run builds its Send
   cache (`build_send_cache()`, section 5: the opening and its estimate); the run is finalized (no
   turn, so no `turn.ended`; `session.ended` is written; `model_status.checked_at` is the
   finalization's end, stamped by `local_now`); and the report and the attention record are
   rendered by `ChatServer._render_run(run, chat.report_path, chat.run_dir)` - today's
   `_render_report` body, extracted, which `_render_report(chat)` now calls too, because
   `_render_report` returns at once while `chat.run` is `None`. A cache build or finalization that
   raises moves the unregistered chat `extracting -> failed` and answers the error body any
   unexpected failure of `POST /sessions` answers today: no chat holds the folder, and no shutdown
   can finalize the run while this call does. The render, as `_play`'s, logs a failure and never
   raises, so `report.md` is on disk with the not-sent header when the 201 arrives unless its write
   failed;
5. the chat is attached and registered and moves `extracting -> awaiting_send`;
6. `201 {chat_id, review_session_id, not_examined}`, as today.

**The host's timeout.** The cache build, the finalization and the render make this call longer than
a ticked start's by their own time, so the host makes it with the long timeout every call with
`send_when_checked: false` has, 10 minutes (default; `BackendClient.TimeoutFor`, `recheck.md`
section 1); a ticked start keeps 30 s (FR-035; research RK-10). **If the host gives up anyway**,
the backend still finishes and registers the waiting chat, which holds its folder: the host reports
today's failure (the error card and Retry, which extracts into a new folder) and keeps no record of
the review. The orphan sends nothing on its own; its record says not sent. When the host holds no
review of that document and the orphan's folder is its newest, the found-review search offers it
(`recheck.md` section 9), and its first action's re-run claim adopts the live orphan (`recheck.md`
section 2); otherwise - a Retry made a newer folder - it is never offered, and it is released at the
next backend restart.

No provider request of any kind is made, and none will be until Send (FR-006, FR-007, SC-001). The
explanation pass is not attempted: it follows only a turn that ended `end` (`runner.py:1333`, `1449`).

## 2. The chat state

002 `data-model.md` section 3, amended:

| From | To | When |
|---|---|---|
| `extracting` | `awaiting_send` | the checks of an unticked review (or a re-run) are done and saved |
| `awaiting_send` | `running` | Send (section 3), an answer route on a waiting run, or a decision or timing write on a waiting run, held for the write (section 4) |
| `running` | `awaiting_send` | the applied answers are saved; Send's adapter could not be built (section 3); a Send failed before any request, or its first request failed before a model round completed (section 6); a decision or timing write returned (section 4) |
| `awaiting_send` | `failed` | an unrecoverable error |

`POST /messages` is refused in `awaiting_send` (`409 NotSent`, section 4); `POST /evidence`, the
single answer route, `POST /disposition` and `POST /timing` are accepted there, the last two
holding the chat `running` for their write (section 4). `_play` settles
`awaiting_send` when `run.awaiting_send` is true after the action, else `waiting_engineer` or `ended`
as today. A Settings save is accepted while a chat is `awaiting_send` and refused, as today, while one
is `running` - which covers answers being applied and a Send in flight (FR-027). An apply that fails
moves the chat `running -> failed` (section 4), a move that exists today.

## 3. `POST /sessions/{chat_id}/send`

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/sessions/{chat_id}/send` | `{}` (any keys ignored) | `202` with the chat's public view; the model's first request follows on the chat's worker |

Checked in this order; a refusal changes nothing and the review keeps waiting:

| Order | Check | Refusal |
|---|---|---|
| 1 | the chat exists | `404 UnknownChat` |
| 2 | not failed | `409 SessionFailed` |
| 3 | no turn running (answers being applied, or a Send already in flight) | `409 TurnRunning` |
| 4 | the run waits for Send | `409 NotWaiting` |
| 5 | the settings in effect hold a usable credential: `ProviderSettings.has_credential` - a key from the settings or the environment, or the scripted provider, or Gemini with an enterprise project | `409 NoCredential` |
| 6 | the adapter builds (`await run_in_threadpool(self.provider_factory, settings)`, off the event loop, as `_start_review` builds it inside the thread pool today; the factory constructs the SDK client, whose first import can be cold) | `502` with the provider's own error class, as `POST /sessions` answers it today |

Checks 1 to 5 and the move `awaiting_send -> running` run on the event loop with no `await`
between them, so a second Send, an answer, a decision or a Settings save that arrives while the
adapter is being built meets `running` and is refused (`409 TurnRunning`): the build at order 6 is
the route's only `await`, and it comes after the move (*second review, 2026-10-09*). When the build
fails, the chat moves back `running -> awaiting_send` before the `502`, so the refusal changes
nothing; when it succeeds, the worker runs `run.send(adapter)` (section 6).

The settings are `ChatServer._settings({provider, model, effort})` of the chat - the one resolver,
with the backend's environment. They are the settings in effect: changing the provider, model,
effort or key is a Settings save, and a save restarts the backend (the review is then restored and
re-run first, `recheck.md`).

## 4. While a review waits

| Action | Route | What happens |
|---|---|---|
| Answer one or several questions | `POST /sessions/{id}/evidence` and `/evidence/{request_id}` | validated exactly as 008 `answer-batch.md` section 2; the chat moves to `running`; `answer_evidence_batch` sees `awaiting_send` and applies the answers with **no turn** (below); the chat settles `awaiting_send` |
| Accept, Reject, Defer | `POST /sessions/{id}/findings/{fid}/disposition` | saved at once on the live session; kept at Send and treated from then on as a decision made between turns (FR-024). On a waiting chat the route moves it `awaiting_send -> running` on the event loop right after `_require_idle`, with no `await` between, and back in a `finally` once `record_disposition` returns or raises, so a Send, an answer or a Settings save that arrives meanwhile is `409 TurnRunning` and no two threads write the session (research R2.12). Any other chat: today's path |
| Timing | `POST /sessions/{id}/timing` | as the decision route: held `running` for `record_timing_live` on a waiting chat; today's path otherwise |
| Follow-up | `POST /sessions/{id}/messages` | `409 NotSent` while `run.awaiting_send` (a follow-up would reach the model with no opening; FR-019) |
| Stop | `POST /sessions/{id}/stop` | unchanged code: the session has an `ended_at`, so nothing is written, no event, no model call (FR-025); during an apply the stop flag is set and never read, then cleared |
| Shutdown | lifespan | unchanged code: a finalized session is skipped; nothing is written (FR-010) |

**Applying answers with no turn** (amends 008 `answer-batch.md` section 1 step 3, 009 FR-015, 011
`confirmed-open.md` section 1, 013 `part-roles.md` section 9). `ReviewRun._apply_answers(answers)`
holds steps 1, 2 and 2a of the batch, shared by both paths: validate, mark each answer with its
`evidence.answered` event, `read_confirmed_candidates`, the part-roles regrade, one `_restate`, the
bought-parts rows and the unmatched-piece rows. Then:

- **a run that was sent** (today): the resumed message as today, `_ask`, the reconcile, finalize;
- **a waiting run**: each `ConfirmedRead` is appended to `session.drawing_outcomes` as `{file,
  outcome}`; the restated tools' calls replace theirs in the run's `PrerunResult` (section 5);
  `_opening_changed` is set; the Send cache is rebuilt (`build_send_cache()`, section 5); the run
  is finalized. No `_ask`, no `REGRADED_LINE`, no turn event.

A crash or a shutdown during the apply loses only the apply: `session.json` holds the record as it
was before, the questions show open again, and no turn event is written - unless the crash came
after the finalization wrote `session.json`, when the record is the applied one.

**An apply that fails.** Validation still refuses before anything changes, as today (`400`). Anything
the waiting branch raises after it - `read_confirmed_candidates`, the part-roles regrade, `_restate`,
the Send cache's build, or the finalization's writes - is caught there, and the branch:

1. puts the record on disk back into the run: `context.session = load_session(session_path)` (when
   the failure came after the finalization's write, that record is the applied one; either way it is
   a whole record), so the `report.md` and `attention.json` `_play` renders next are that record's;
2. emits one `error` event (`error_body`, the class and the redacted message, `retryable: true`) and
   no `turn.ended` or `session.ended` (FR-010);
3. re-raises.

`_play` moves the chat `running -> failed`, and `_close_out` writes nothing because the record's
`ended_at` is set (`_already_ended`). The failed chat no longer holds the folder, so the review's
next answer, decision or Send re-runs it from the folder (`recheck.md`). The page's side is
`pane.md` section 5. Which record the folder holds depends on where the failure came - the
finalization writes `session.json`, then `attention.json`, then the `session.ended` event
(`runner.py:1367-1383`):

| The failure came | `session.json` holds | The restored review shows |
|---|---|---|
| before the finalization's `save_session` (the read, the regrade, `_restate`, the cache, the save itself) | the record before the apply | the answers being applied open again |
| after it (`write_attention_record`, the `session.ended` event) | the applied record | the answers answered; the re-run carries them (`recheck.md` section 4) |

**A drawing merged before the failure.** A confirmed read merges its drawing into the folder's
`package.json` before the regrade; its outcome line reaches `session.json` only with the
finalization. A failure (or a crash) between the two leaves the drawing in the package and the
record without its answer or its outcome line. The re-run checks that drawing in its place and does
not ask its question again, so the outcome line FR-021 sends to the model is lost; the re-run names
the loss in its `coverage.recheck` row (`recheck.md` section 5), a recorded limitation of FR-021
(research R2.13).

## 5. The opening at Send, and the Send cache

What Send would send is built once, on a worker, and kept: `ReviewRun.build_send_cache()` sets
`_send_cache = SendCache(opening=opening_at_send(), estimate=first_request_estimate(),
named_ids=...)` in one assignment (`estimate.md` section 2). It is called at three points, each
inside a path whose failure is already defined: the unticked start and a re-run (after
`start_review`, and the carry, and before the finalization: a failure is the start's error body,
section 1); and the waiting apply (after the regrade, before its finalization: a failure is an
apply failure, section 4). Nothing the opening reads moves in a finalization (research R2.8), and a
test pins that the cache's opening equals the opening built again after it. The attention and
snapshot routes, which compute on the event loop and never write, and `send` only read the cache;
no route builds an opening or counts a token.

`ReviewRun.opening_at_send()`, called only by `build_send_cache()`:

- **nothing applied while waiting** (`_opening_changed` false): `self.opening_message`, the opening
  frozen at setup, byte for byte (SC-004; for a re-run, SC-008);
- **answers applied**: `_opening_message(self._prerun, session, package, standards_gap=...,
  roles=review_roles(context))` - the one builder `start_review` uses - followed by the wait's lines
  inserted between the digest and `OPENING_MESSAGE`:

```
<package brief, with the part roles as they stand>

<the pre-run digest, rebuilt>

Drawing FICT-1001-drw.SLDDRW: opened read-only, read and closed (2 sheets)
ER-001 (Which of these parts are bought?) was answered before this review was sent: All bought. The checks above were graded again by code with this answer.

Review the evidence package described in the system prompt. ...
```

First one `DRAWING_OUTCOME_LINE` per `session.drawing_outcomes` entry, in order (013's words, refusals
included); then one `WAIT_ANSWER_LINE` per answered code question, in the order the answers were
given (`answered_at`, then id). Neither block has a header; a block with no line is absent, and
with no line at all the separator is absent too. No line names a withdrawn finding, and no line asks
the model to re-run, replace or continue (FR-023). None of these lines is sent again after Send.

**The rebuilt digest** (`prerun.restated(prerun, context, calls, standards)`, new): the pre-run
result with (a) each restated tool's calls replaced, in place, by its restated `PrerunCall`, whose
`findings` are the session's standing findings that cite that call's step (a finding `_restate`
folded keeps its id), and (b) `not_evaluated` recomputed by `not_evaluated_families` with the current
roles and the run's live outcome and withheld tools. `withheld`, `live` and `families` are kept. With
nothing restated, `restated` returns its input, so the builder reproduces the frozen opening byte for
byte (pinned by a test). Every finding the digest names stands; every standing pre-run finding is
named under the digest's own caps (`DIGEST_ID_CAP`; a folded family is counts only).

`PrerunResult.named_finding_ids()` (new) returns the ids the digest lines name, in order, from the
same loop `_finding_lines` renders: the cache's `named_ids`, recorded as the Send's
`opening_finding_ids` (SC-010).

## 6. Send, and a failed first request

`ReviewRun.send(adapter)`, on the chat's worker, in two halves and a guard (research R2.10):

**Prepare** - nothing written, nothing emitted, nothing in the session changed:

1. `before = session.model_status.model_copy(deep=True)`; `_send_error = None`;
   `attach_provider(adapter)`: `configure_provider(adapter, session)`, then
   `adapter.start_steps_at(len(session.steps))` when the session has steps. The adapter is not yet
   the run's provider;
2. `opening`, `estimate` and `named_ids` read from `_send_cache` (section 5);
3. the `session.sent` body built: `{provider: adapter.name, model, effort_mapping:
   adapter.effort_mapping(effort), estimate}`;
4. the withdrawn coverage computed, pure: `coverage.checked` and `coverage.unresolved` without any
   item of the run's `_finalized` list (the close-out row, one unresolved row per open question,
   one per open checklist item - the "not reviewed, because the review was not sent to the model"
   rows), by identity, exactly as `finalize_session` filters them at its start
   (`runner.py:619-627`). Rows anything else wrote stay.

**Commit**:

5. the pre-write: the model status gets `failures += [{at: local_now(), error_class:
   "Interrupted", reason: "the backend stopped before the model answered"}]` and `state:
   "send_failed"`, and the session is saved as it stands - still the finalized record of the
   checks, so a crash from here on leaves a whole record that says a request was made and no round
   completed;
6. `session.sent {provider, model, effort_mapping, estimate}` is emitted;
7. the withdrawn lists are assigned and `_finalized` cleared - so the model's first turn reads the
   coverage a ticked review's first turn reads: no item placed by a close-out, `open_items` and
   `get_review_checklist` as a review sent at once sees them (US2, FR-015; research R2.27), on
   every Send: the first, one after a failed Send, one after answers applied while waiting, and one
   after a re-run; then `self.provider = adapter`, `awaiting_send = False`, `_send_in_flight =
   True`, `sent_at = local_now()` (held, not yet recorded). Assignments only: nothing here can
   raise;
8. `_say(opening)`.

**The guard** over steps 1 to 7. Anything they raise:

- puts the model status back from `before`, in memory;
- when step 5's save had completed, saves the session again (the undo), so `session.json` says what
  it said before Send; when the undo save itself raises, the failure is logged and the run goes on
  waiting: the file then says what a crash right after step 5 leaves, and the next write (the next
  Send's pre-write, an apply's finalization) replaces it;
- leaves the `DeferredProvider` as the run's provider (step 7 never ran);
- keeps `awaiting_send = True` and sets `_send_error = {at: local_now(), error_class, reason:
  redacted message}` - in memory only, shown as the Send block's failure line (`words.md`
  `send.not_started`) until the next Send, and never written to `model_status`, because no request
  was made;
- emits one `error` (`error_body`, `retryable: true`) and no `turn.ended` or `session.ended`;
- returns normally, so `_play` settles `awaiting_send` and re-renders the unchanged session.

The run's state and its failure are set **before** the `error` is emitted, so a page that re-reads
the summary on that event reads the Send block with its failure line (`pane.md` section 3). A
crash between step 5 and the request leaves `send_failed` although no request left the machine:
the record errs on the side of the model having been asked (research R2.10, RK-7).

**The first completed round.** In `_emit_turn_event`, the first `usage` event while
`_send_in_flight` sets `model_status {state: "sent", sent_at, estimate, opening_finding_ids}`, drops
the `Interrupted` entry, clears `_send_in_flight` and saves the session as it stands: the checks'
finalization rows were withdrawn at step 7 and `_run_turn` cleared `ended_at`, so the file is a sent
review whose turn has not ended, never a finalized checks-only record whose state says `sent`
(research R2.11). A crash after it leaves that record, which `GET /reviews` reads read-only as a sent
review. From then on the review is a review sent at once in every respect but its record (FR-015):
turns, Stop, the model's questions, answers that resume it, the explanation pass after a turn that
ends `end`, follow-ups and the ranking.

**A failure before any round.** `_run_turn`'s `except` branch reads, **before** `emit_turn_failed`,
whether a Send is in flight with `usage_ledger.current_round_count == 0`. When it is: the
`Interrupted` entry is replaced by `{at, error_class: type(exc).__name__, reason: redacted message}`,
`self.messages = []`, `awaiting_send = True`, `_send_in_flight = False`, and the run's provider
goes back to a `DeferredProvider` of the same settings, so nothing can reach the model until the
next Send attaches an adapter again; then `emit_turn_failed` and `finalize` run as today (the
`error` and `turn.ended {error}` events are the failed attempt's record; streamed text stays in the
stream), and the exception travels to `send`, which catches it and returns, so `_play` settles
`awaiting_send`. The finalization appends a new set of finalization rows, which the next Send's
steps 4 and 7 withdraw. A second Send sends the opening once (FR-017). **A failure after a round** is
today's: the review ends, `failed`, with the error card.

## 7. Events

002 `chat-events.schema.json`, amended (additive). The `session.started` branch's `body` already
has `"additionalProperties": false` and a fixed property list, and a sibling `allOf` entry cannot widen
it, so the new key goes **inside that branch's `body.properties`**, beside `effort_mapping`, and not
in `required`:

```json
"send_when_checked": { "const": false, "description": "Feature 015: present only for a review started with the box unticked, whose checks run and which then waits for Send. Absent means sent when the checks finish, as every review before the feature." }
```

`test_events_schema.py` gains the rows: an unticked `session.started` with `send_when_checked: false`
validates; one with `send_when_checked: true` is refused (`const`); a ticked one without the key
validates as today; any other new key on `session.started` is still refused. `session.sent` is a new
branch of its own:

```json
{ "if": { "properties": { "type": { "const": "session.sent" } } },
  "then": { "properties": { "body": { "type": "object", "additionalProperties": false,
    "required": ["provider", "model", "effort_mapping"],
    "properties": {
      "provider": { "enum": ["openai", "gemini", "fake"] },
      "model": { "type": "string" },
      "effort_mapping": { "type": "object", "additionalProperties": false, "required": ["requested", "provider_param", "provider_value"], "properties": { "requested": { "type": "string" }, "provider_param": { "type": "string" }, "provider_value": { "type": ["string", "integer"] } } },
      "estimate": { "$ref": "https://smart-sw.local/contracts/review-session.schema.json#/$defs/SendEstimate" } } } } } }
```

and `"session.sent"` joins the `type` enum and `EventType`. The page handles it live and in a
transcript replay (`pane.md` section 10); `PageRuleScanTests` reads the enum.

## 8. The provider a waiting review holds

A run holds a `DeferredProvider` whenever it waits: from its setup, after a Send that failed before
any request (the guard never replaced it), and after a first request that failed before any round
(the failure branch puts one back) - section 6. `agent/providers/deferred.py`:

```python
class ProviderNotSent(RuntimeError):
    """A waiting review asked its provider for a turn: nothing may reach a model before Send."""

class DeferredProvider:
    name: ProviderName
    model: str
    def __init__(self, name: ProviderName, model: str) -> None: ...
    @classmethod
    def for_settings(cls, settings: ProviderSettings) -> DeferredProvider: ...
    def effort_mapping(self, effort: EffortLevel) -> EffortMapping:   # the adapter's own rule
    def start_steps_at(self, index: int) -> None:                      # kept, read by nothing
    def run(self, **_: Any) -> TurnResult:                             # raises ProviderNotSent
    def for_presentation(self, max_output_tokens: int) -> AgentProvider:  # raises ProviderNotSent
```

`effort_mapping` calls the module function each adapter's method now calls:
`openai_provider.effort_mapping_for(model, effort)`, `gemini_provider.effort_mapping_for(model,
effort)`, `fake.effort_mapping_for(model, effort)` (the methods become one-line delegations; no
behaviour change). An effort the model refuses raises the adapter's own error at setup, as today.

`configure_provider(provider, session)` (`agent/runner.py`, new) holds `start_review`'s three
opt-in hooks, unchanged and in their order: `use_model_view(session.model_view)` when
`ModelViewAware`; `use_prompt_cache(str(session.session_id))` when lever 3 is on and
`PromptCacheAware`; `drop_prior_reasoning()` when lever 14 is on and `PriorReasoningAware`.
`start_review` calls it where the three hooks are today; `attach_provider` calls it at Send.

## 9. Error classes

New `ChatError` subclasses; each has a sentence in the words file's `labels.errors`
(`words.md` section 2), which the existing every-class-has-a-label test enforces.

| Class | Status | Raised by |
|---|---|---|
| `NotWaiting` | 409 | Send on a review that does not wait; a re-run of a folder whose record is not a waiting review's |
| `NotSent` | 409 | a follow-up on a review that waits |
| `NoCredential` | 409 | Send with no usable credential |

## 10. Tests

Research R4.1: `test_send_gate_server.py`, `test_runner_send.py`, `test_deferred_provider.py`,
`test_waiting_answers.py`; the moved `test_chat_sessions.py`, `test_chat_server.py` `ROUTES` and
`test_events_schema.py`; and, first of all, the characterization of a ticked review on the
pre-feature code (`test_ticked_review_golden.py`, research R2.28), which section 1's ticked path
must keep byte for byte. Every test that drives an unticked review asserts the provider factory was
never called (`ProviderControl.built == []`) up to the Send under test. Section 6's guard is pinned
at five failure points (`configure_provider`, the effort mapping, the pre-write's save, the
`session.sent` emit, and the undo save after a failed emit): no provider request, the chat waiting
again, one `error`, and a record that does not say a request was made. Section 4's hold is pinned by
a decision held in flight while `POST /send` and `POST /evidence` are refused. Section 6's
withdrawal (steps 4 and 7) is pinned by comparing **every** request of a scripted first turn that
calls `mark_coverage`, `request_evidence` and `get_review_checklist` - tool results included -
between a ticked review and an unticked review sent, on the same package, and again after a failed
Send and after a re-run.
