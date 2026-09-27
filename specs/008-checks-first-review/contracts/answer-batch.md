# Contract: The Answer Batch

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), landed by 2026-09-27 (013 T038, T089):* a part-roles answer regrades before the resumed turn and may withdraw findings (`finding.withdrawn`), and a confirmed drawing read's outcomes become lines of the resumed message; see 013 `contracts/part-roles.md` section 9 and `contracts/drawing-capability.md` section 6.

Normative for answering several open evidence requests in one submission (FR-025, SC-005).

## 1. The runner

`ReviewRun.answer_evidence_batch(answers: Sequence[tuple[str, str]]) -> ReviewSession`:

1. **Validate everything first.** An empty sequence, a request id repeated in the submission, an
   unknown id (`UnknownEvidenceRequestError`) or an already-answered id
   (`EvidenceAlreadyAnsweredError`) raises before anything changes - no request is marked, no event
   is written, no turn starts. Both error classes subclass `ValueError` and keep today's message
   text; the first failing id is named.
2. **Record each answer.** In submission order, each request gets its answer and `answered_at`,
   and one `evidence.answered` event.
3. **Resume once.** One `_ask`, one `_reconcile_reruns`, one finalize. The resumed turn's user
   message is `ANSWER_MESSAGE.format(...)` byte for byte for a batch of one, and `ANSWERS_MESSAGE`
   for two or more:

```
The engineer answered your evidence requests:
- ER-001: <answer>
- ER-002: <answer>
- ER-003: <answer>
Continue the review with these answers.
```

`answer_evidence(request_id, answer)` delegates to `answer_evidence_batch([(request_id,
answer)])`. `answerable(session, request_id)` is the one validator: the single route, the batch
route and the runner all call it, removing the two copies of the lookup that exist today.

*Landed as (T083).* The two copies worded the unknown-id refusal differently - the route listed
the requests still open, the runner every request under the word "open" - and `answerable`
keeps the route's sentence, `no evidence request 'ER-404' in this session; open: ['ER-002']`,
so the list is what it says it is. Both error classes carry `request_id`, which the routes copy
onto their bodies. `answers_message(answers)` is the one place the resumed turn's message is
worded (`ANSWER_MESSAGE` for one answer, `ANSWERS_MESSAGE` with one `ANSWER_LINE` each
otherwise); the replay and its test support rebuild a recording's message through it. A repeated
id is refused with `REPEATED_ANSWER` ("evidence request ER-001 is answered twice in one
submission"), found by `repeated_request_id`, in the runner and the route alike. The batch
message does not repeat `ANSWER_MESSAGE`'s instruction to re-run the check each request named;
it is worded as this section gives it.

*Amended by feature 013 (T038, `contracts/part-roles.md` section 9).* A new step sits between 2
and 3: **2a. Read, regrade, restate.** `read_confirmed_candidates` runs first, with the roles its
question was built with; then, when the batch answers the part-roles question (exactly the
question the current roles ask), the parts are classified again with the answer; then one
`ReviewRun._restate` - which replaces `_restate_drawing_check` - restates the union of what
changed, each check once (`check_rms_part`, `check_rms_equations`, `check_rms_assembly`,
`check_hygiene` and `check_drawings` when the roles changed; `check_drawings` when a read reloaded
the package), each a recorded step the pre-run's guard answers repeats from. `_restate` folds
each restated finding onto the earlier one with the same verdict key, which keeps its id, and
withdraws every earlier finding of a restated check that nothing re-produced through
`ToolContext.withdraw_findings`, the one place a finding leaves the session. **This adds an event
type** - "no new event type" no longer holds: `finding.withdrawn {finding_id, reason}`, the reason
"bought part (your answer to ER-001)" (002 `chat-events.schema.json`). The bought-parts rows are
restated naming the withdrawn ids, and step 3's `before` index is taken only after `_restate`
returns. The resumed message gains one line when the answer withdrew findings - "Checks first
graded again after your answer: withdrew F-003, F-004 (bought parts)." - and is
`answers_message(answers)` byte for byte otherwise. A check the session never ran is not
restated: restating supersedes the call it restates.

*Amended by feature 013 (T089, `contracts/drawing-capability.md` section 6).* After a confirmed
read, the resumed message opens with one line per drawing file the read asked for - "Drawing
{file}: {outcome}", the `drawing.confirmed_open` reason, refusals included (the host's refusal,
the bridge error, the ten-drawing bound, no connection) - then a blank line and the answers'
message. Two documents of one file are one line. A batch with no confirmed read sends today's
message byte for byte.

## 2. The route

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/sessions/{chat_id}/evidence` | `{"answers": [{"request_id": "ER-001", "answer": "…"}, …]}` | `202`; every request answered; the review resumes once |

Checked in this order, and a refusal changes nothing:

| Order | Check | Refusal |
|---|---|---|
| 1 | the chat exists (`_chat`, as every session route) | `404 UnknownChat` |
| 2 | shape: `answers` a non-empty list of objects each with a string `request_id` and a string `answer`, no id repeated | `400 InvalidRequest` naming the index or the repeated id |
| 3 | no turn running, the session not failed | `409 TurnRunning` / `409 SessionFailed` |
| 4 | every id known and open | `404 UnknownEvidenceRequest` / `409 AlreadyAnswered`, naming the first failing id |

The single-answer route `POST /sessions/{chat_id}/evidence/{request_id}` stays as it is, through
`answerable()`. No new event type. The add-in's proxy forwards the path with no change; the page
that sends answers together is feature 009's.

*Landed as (T085).* The shape check asks of each item what the single route asks of its one
answer: a `request_id` and an `answer` that are strings **and not blank**, so a whitespace
answer is `400 InvalidRequest` on both routes. A body that is not a JSON object, or has no
`answers` list, is `400 InvalidRequest` too. A batch may name some of the open requests; the
others stay open and the chat settles `waiting_engineer` again.

## 3. The replay

A recording whose resumed turn is preceded by several `evidence.answered` events is replayed
through `answer_evidence_batch` with those pairs, in recorded order; one event through
`answer_evidence`.
