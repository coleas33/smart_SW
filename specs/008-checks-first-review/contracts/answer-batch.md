# Contract: The Answer Batch

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

## 3. The replay

A recording whose resumed turn is preceded by several `evidence.answered` events is replayed
through `answer_evidence_batch` with those pairs, in recorded order; one event through
`answer_evidence`.
