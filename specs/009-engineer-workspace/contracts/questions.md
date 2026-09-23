# Contract: Questions for You

Normative for FR-013 to FR-016, SC-004 and the question edge cases.

## 1. The tool

```python
def request_evidence(
    what: str,
    why: str,
    entity_ids: list[str],
    question: str | None = None,
    options: list[str] | None = None,
    blocks: str | None = None,
) -> ToolResult:
```

Checked in this order; each refusal is one `error_result` naming the argument and records nothing:

| # | Check | Refusal |
|---|---|---|
| 1 | every `entity_ids` entry is in the package (today's check) | "entity_ids not in this package: [...]" |
| 2 | `question`, when given, is not blank and at most 140 characters | "question must be one short question of at most 140 characters (got N)" |
| 3 | `options`, when given: at most 5, each not blank, at most 60 characters, no two equal | names the index or the repeated option |
| 4 | `blocks`, when given, is a checklist item id | names the id and lists the valid ones |

The docstring's `Args` describe the three; its `Notes` add: ask one decision per request; offer
`options` only when the answers are a closed set; never guess a fit class, a tolerance or a thread
depth - ask for it. Every description stays under `MAX_DESCRIPTION_LENGTH` and
`MAX_PARAMETER_DESCRIPTION_LENGTH` (`test_docstring_split.py` unedited).

## 2. The session and its contract

`EvidenceRequest` gains `question`, `options` and `blocks` (data-model section 4), omitted from the
dump when empty. `review-session.schema.json` `$defs.EvidenceRequest` gains them as optional
properties in the same change. The `evidence.requested` event carries them through its `$ref`.

## 3. The summary's questions

`summary.questions = {count, text, items}`; `items` are the requests whose status is `open`, in
session order, each a `QuestionView` (data-model section 2): the short `question` or `what`, the
`options`, `blocks` and the title of its goal, `what` and `why` verbatim, and `about` with names.

## 4. The panel

`<section id="questions">` in Results, after the summary and before Start here, shown when
`summary.questions.count > 0`:

- a pager line "Question {i} of {count}" (`i` is the position on screen, `count` the summary's) with
  Previous and Next;
- the question in the lead face; `blocks_title` as "Blocks: {title}"; `about` names; `what`, `why`
  and the ids behind a shut fold;
- the options as buttons, one selectable at a time (`aria-pressed`), the answer being the option's
  text verbatim; or, with no options, one text box;
- "Skip for now": marks the question skipped in page memory and moves on; sends nothing;
- "Send answers": enabled when at least one question has a non-blank answer; beside it
  `summary.resume_text`;
- disabled while a turn runs, while a start is in flight, and for a read-only review.

Sending posts `POST /sessions/{chat_id}/evidence` (feature 008 T085) with `{answers: [{request_id,
answer}]}`: every answered question, in the order the summary supplied them, answers trimmed;
skipped and unanswered ones are absent. On `202` the turn runs and the stream reopens as a follow-up
does; the drafts of the sent questions are dropped. Drafts are kept per chat id in page memory while
the page lives, so choosing another review and coming back keeps them.

## 5. The resume cost

`summary.resume_input_tokens` is `UsageLedger.last_conversation_input()`: the input tokens of the
last round before the most recent `text.done` (the explanation pass's round, after `text.done`, is
never taken). `resume_text` is "Sending resumes the review once. Its last round sent {tokens} input
tokens." with the number formatted `405,861`, or "Sending resumes the review once." when unknown.
The disk route answers `None` and the panel is disabled there.

## 6. Refusals

`UnknownEvidenceRequest` (404) and `AlreadyAnswered` (409) carry `request_id` in their body beside
`error_class`, `message` and `retryable`, on the batch route and the single route alike. The page:

| Refusal | What the pane says | Then |
|---|---|---|
| `AlreadyAnswered` / `UnknownEvidenceRequest` with `request_id` | "Question {i} ({question}) was answered elsewhere, so nothing was sent." | reloads the summary; keeps the other drafts |
| `TurnRunning` | the label for `TurnRunning` | nothing else |
| any other | the label for its class, the class and message in a fold | nothing else |

Nothing is recorded on any refusal (008 `contracts/answer-batch.md` section 2).

## 7. The transcript card

`render.evidenceCard` keeps the question, `why`, "about" and, once answered, the answer; it no longer
carries an answer box or a Send button. The single-answer route stays in the backend; the page no
longer calls it.
