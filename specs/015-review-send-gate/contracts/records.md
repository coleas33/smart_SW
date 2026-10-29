# Contract: Honest Records of Whether a Review Was Sent

Normative for what a review started with the box unticked writes about itself, and for the readers
of those records (FR-009 to FR-011, FR-032, FR-036, FR-040). Amends 001
`contracts/review-session.schema.json` and `contracts/README.md`; 002 `contracts/handoff-export.md`
(added by this plan); 008 `contracts/replay.md` section 2. A review started with the box ticked
writes nothing new: its `session.json`, `events.jsonl`, `report.md` and `attention.json` are what they
are today (FR-032, FR-035). Amended on 2026-10-09 by the owner's plan review (research R7): decisions
72A, 73A, 75A and 76A.

## 1. The session fields

`report/session.py`, three optional `ReviewSession` fields, each dropped by the serializer at its
default (the pattern `_omit_empty_finding_explanations` already follows), and `model_status`
declared directly after `provider_info` so it is in the file's first kilobytes (`recheck.md`
section 9 reads only a bounded head). 001 `review-session.schema.json` gains, never in `required`:

```json
"model_status": { "$ref": "#/$defs/ModelStatus", "description": "Feature 015: written only for a review started with the box unticked. Absent means the review was sent when its checks finished, as every review before the feature." },
"live_detection": { "$ref": "#/$defs/LiveDetection", "description": "Feature 015: the first run's live interference outcome, which a re-run after a restart carries rather than repeats." },
"drawing_outcomes": { "type": "array", "items": { "$ref": "#/$defs/DrawingOutcome" }, "description": "Feature 015: one line per drawing file a confirmed read asked for while the review waited." }
```

```json
"ModelStatus": {
  "type": "object", "additionalProperties": false,
  "required": ["state", "document", "checked_at"],
  "properties": {
    "state": { "enum": ["not_sent", "send_failed", "sent"] },
    "document": { "type": "object", "additionalProperties": false, "required": ["path", "configuration"],
                  "properties": { "path": { "type": "string" }, "configuration": { "type": "string" } } },
    "checked_at": { "type": "string", "format": "date-time" },
    "profile": { "type": "object", "additionalProperties": false, "required": ["path", "sha256"],
                 "properties": { "path": { "type": "string" }, "sha256": { "type": ["string", "null"], "pattern": "^[0-9a-f]{64}$" } } },
    "rechecked_from": { "type": "string", "format": "uuid" },
    "failures": { "type": "array", "items": { "$ref": "#/$defs/SendFailure" } },
    "sent_at": { "type": "string", "format": "date-time" },
    "estimate": { "$ref": "#/$defs/SendEstimate" },
    "opening_finding_ids": { "type": "array", "items": { "type": "string", "pattern": "^F-[0-9]+$" } }
  }
},
"SendFailure": { "type": "object", "additionalProperties": false, "required": ["at", "error_class", "reason"],
  "properties": { "at": { "type": "string", "format": "date-time" }, "error_class": { "type": "string" }, "reason": { "type": "string" } } },
"SendEstimate": { "type": "object", "additionalProperties": false, "required": ["input_tokens", "encoding", "approximate"],
  "properties": { "input_tokens": { "type": ["integer", "null"], "minimum": 0 }, "encoding": { "const": "o200k_base" }, "approximate": { "type": "boolean" } } },
"LiveDetection": { "type": "object", "additionalProperties": false, "required": ["configuration", "settings"],
  "properties": { "configuration": { "type": "string" }, "settings": { "type": "object" },
    "step_index": { "type": ["integer", "null"] }, "not_attempted": { "enum": ["no_bridge", "not_assembly", null] },
    "groups": { "type": "integer", "minimum": 0 }, "rows_detected": { "type": "integer", "minimum": 0 },
    "rows_added": { "type": "integer", "minimum": 0 }, "rows_collided": { "type": "integer", "minimum": 0 },
    "error": { "type": ["string", "null"] }, "persist_error": { "type": ["string", "null"] } } },
"DrawingOutcome": { "type": "object", "additionalProperties": false, "required": ["file", "outcome"],
  "properties": { "file": { "type": "string" }, "outcome": { "type": "string" } } }
```

*Amended 2026-10-15 (feature 016 lands on this feature, owner decision 99A):* `ModelStatus` gains
an optional `engineering_context`, omitted when null, written only by a review started unticked
with saved engineering context:

```json
"engineering_context": { "type": "object", "additionalProperties": false,
  "required": ["context_id", "head_digest", "package_sha256"],
  "properties": { "context_id": { "type": "string", "format": "uuid" },
                  "head_digest": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
                  "package_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" } } }
```

It names the attachment the review was started with - no path - so a re-run carries and validates
it again (`recheck.md` section 2). A re-run sets its own from what it validated, and the carry
leaves it as is. A review without saved context writes nothing new, byte for byte. 001
`review-session.schema.json` is amended to match.

`checked_at` is required even before the first save: setup constructs the in-memory model status
with `local_now()` after the checks, and the first finalization replaces that provisional value
with its end before writing `session.json`. A waiting apply keeps the first finalization's value;
a re-run has its own first finalization (2026-10-12 re-check).

`model_status.state` moves `not_sent -> send_failed` (a Send's first request is about to be made,
`review-flow.md` section 6) `-> sent` (its first round completed) or back to `send_failed` with the
provider's reason; `sent` is final. A Send that fails before any request leaves `model_status` as it
was before that Send, because no request was made: `session.sent` is emitted before the pre-write, so
a failure up to the pre-write leaves no write behind, and a pre-write that fails leaves the file
`write_atomic` was replacing whole; the guard restores the run's memory and never writes (owner
decision 72A). The failure is the stream's `error` event and the Send block's line, held by the live
run only (`review-flow.md` section 6). `profile` is the identity of the Standards profile the
checks graded with: the path the review was given and the sha256 of its bytes when it loaded
(`ProfileIdentity`, `checks/standards/profile.py`), `sha256` null when the profile was refused, the
field omitted when the review had none; a re-run records its own and names a change
(`recheck.md` section 4). It is a local path in the run folder's own record, which is never
committed (FR-039). A re-run after a restart **carries** the earlier record's
`state`, `document` and `failures` whole and adds `rechecked_from` (`recheck.md` section 4 step 5): a
re-run never turns a `send_failed` record into `not_sent`, because `not_sent` means no request was
ever made. `checked_at`, `sent_at` and each failure's `at` are stamped by `agent/events.local_now()`
and keep their UTC offset; everything that prints one prints the stored wall clock as it is, never
converted to the zone of the machine rendering it, so a record renders the same everywhere and a
fixture generator pins the one clock. `document` is the reviewed root document's `{path,
configuration}`, the shape `report/snapshot._root_document` already gives the snapshot (made public
and shared, not copied). A session saved before this feature has no `model_status` and reads as sent.

## 2. Finalization of a review not sent

`finalize_session` reads `model_status`. While its `state` is not `sent`, each open checklist item
whose `owner` is `model` is unresolved with `NOT_SENT_ITEM`, "{title}: not reviewed, because the
review was not sent to the model"; an item left open after its blocking question was answered keeps
`ANSWERED_BUT_OPEN` and adds `NOT_SENT_SUFFIX`, "; the review was not sent to the model". Nothing is
marked checked because the model did not look (FR-009). A code-owned item is closed by code, as today.
Once `sent`, finalization is today's.

## 3. Running time

For a session with `model_status`, `timing.unattended_runtime_minutes` is `(checked_at - started_at)`
plus, once `sent`, `(ended_at - sent_at)`; the wait, and any minutes spent answering or deciding
while it waits, are not running time (FR-011). `checked_at` is set by the first finalization of the
checks (`review-flow.md` section 1 step 4); a re-run sets its own.

## 4. The report

`report/markdown.py`, `_render_title`:

| `model_status` | Lines (in place of `- Model:` and `- Provider:`) |
|---|---|
| absent, on a review (sent at once, or before this feature) | today's, unchanged |
| absent, on a check's own session (*amended 2026-10-19, owner decision 132A*) | `- Model: not sent to the model (checked by code only)`, as `not_sent` |
| `not_sent` | `- Model: not sent to the model (checked by code only)` |
| `send_failed` | `- Model: not sent to the model; the last attempt failed at {at}: {reason}` |
| `sent` | today's `- Model:` and `- Provider:` lines, then `- Sent to the model: {sent_at} (checks finished {checked_at})` and, when there were failed attempts, `- Earlier attempts that failed: {n}` |

A re-run adds `- Checked again from session: {rechecked_from}`, beside today's `- Retry of session:`.
Because a re-run carries the earlier state and failures, a re-run of a failed send keeps the
`send_failed` line, and `{n}` counts every failed attempt before the Send that got an answer, those
made before a restart included. No not-sent report names a model or a provider as having run
(SC-009).

*Amended 2026-10-19 (owner decision 132A):* a check's own session (a Model check's, a Standards
check's, the re-modeler's grade) constructs no provider, yet records the model `new_session` stamps
on every session, and its report printed that model as if it had run. Rendered with
`check_run=True`, it prints the `not_sent` line and no `- Provider:` line, where the check writes
its report and wherever `report/rerender.py` re-renders its folder. A session is the check's own
while the folder's `check.json` names it, so a review that claimed the folder keeps its own lines.

## 5. The transcript's events

`session.started` carries `send_when_checked: false` for an unticked review; each Send attempt emits
`session.sent` (`review-flow.md` section 7), before the attempt's record is written, so the page words
it "Sending to {provider} {model} ..." and never as sent (owner decision 72A; `pane.md` section 10). A not-sent
review writes no `turn.ended` of any kind, a shutdown and a stop included (FR-010).

## 6. The replay and the recording reader

`benchmark/recording.read_recording` refuses, after it finds the session and **before** it reads the
events, a session that carries `model_status`, in one sentence each (`RecordingRefused`):

| `model_status.state` | Sentence |
|---|---|
| `not_sent`, `send_failed` | "{RUN_DIR} was never sent to the model, so it has no model turn to replay" |
| `sent` | "{RUN_DIR} was sent to the model after waiting for Send; the replay reads only reviews sent when their checks finished" |

008 `replay.md` section 2's table gains both rows above its first. A review sent at once is read as
today (FR-040).

## 7. The handoff export (added by this plan; owner decision 73A)

`handoff.py`'s session summary gains `"model_status": session["model_status"]["state"]` when the
session carries one, beside `provider_info`; nothing else in the bundle moves. 002
`contracts/handoff-export.md` gains the key. The owner kept this (plan question 2, answered by 73A):
otherwise the export would be the last record that names a provider for a review never sent.

*Landed as* (T111-T112, T115, 2026-10-15): this section named no rule for a value that cannot be
read, so the code chose one.
- A non-mapping `model_status`, or a missing, non-string or unknown `state`, exports as
  `"model_status": null` and does not fail the export, as an unreadable `provider_info` does.
- A missing or null `model_status` adds no key.
- The known states are read from `ModelStatus`'s own field (`get_args`), not restated.
- 002 `contracts/handoff-export.md` states this.

## 8. The atomic write

`save_session` writes through `atomic.write_atomic(path, bytes)`: the encoded JSON to a temporary in
the session's own folder, then `os.replace`. The bytes are unchanged; a crash mid-write leaves the
previous file whole. The helper is feature 014's (`reviewer/src/swreview/atomic.py`): imported when
014 is on `main`, otherwise added with 014's exact name, signature and body (research R3).

*Landed as* (owner decision 93A, T115, 2026-10-15): for a re-run, this replace of `session.json`
is the commit point. Before it the earlier record stays canonical. After it the re-run is complete,
even if writing `attention.json` or emitting `session.ended` then fails or is cut off
(`recheck.md` section 2).

## 9. Tests

`test_session_fields_015.py`, `test_report_model_status.py`, `test_runner_send.py` (finalization,
timing, the mid-turn save at the first round, the record a crash before and after the first round
leaves - each the folder `tests/support/restart.py`'s `disk_at` copied at that point, read by a
backend started afresh (owner decision 76A) - and the times rendered as stored), `test_recheck.py`
(a re-run of a failed send keeps its failure line, and a later Send counts it; a changed profile is
named), `test_send_gate_server.py` (a Send that fails before any request leaves `session.json` as it
was, at each of its five failure points), `test_replay_recording.py` and `test_cli_benchmark_replay.py` (the
refusals), `test_handoff.py` (research R4.1). The characterization of a ticked review
(`test_ticked_review_golden.py`: five scenarios, its failures included (owner decision 75A), each
with its `session.json`, `events.jsonl`, `report.md` and `attention.json`, captured on the
pre-feature code; research R2.28) and every replay fixture stay byte-identical.
