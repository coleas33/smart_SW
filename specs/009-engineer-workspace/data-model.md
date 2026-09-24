# Data Model: The Engineer's Workspace

**Feature**: `009-engineer-workspace` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

No IR schema change and no event type. The review-session contract gains three optional properties
on `$defs.EvidenceRequest` (`question`, `options`, `blocks`) and no required one; the event schema
references that definition, so `chat-events.schema.json` does not move. `attention.json`, both check
bodies and `report.md` keep their shapes (research R2.2), and `attention.json` its bytes. *Amended
2026-09-23 (owner, decision 2A, research R2.28):* no golden baseline moves - `Finding.title` stays
the recorded title the model reads - and the `title` a person reads is the display title
(`contracts/plain-words.md` section 2): on the `finding` event, the snapshot's findings, the
Review tab's ranking rows, both check bodies' `attention` rows and in `report.md`, where a recorded
title was cut or named a part by id. Everything else below is a new response shape, a data file,
or page state, each normative in `contracts/`.

---

## 1. The words file (`reviewer/src/swreview/report/review_words_v1.yaml`)

Loaded once per process by `summary.load_words() -> Words` (`functools.cache`, like `load_policy`).
`Words` and every nested model are `extra="forbid"`. No `%` anywhere in the file.

| Key | Type | Content |
|---|---|---|
| `version` | str | `review_words_v1` |
| `headline` | `{none, findings_one, findings_many, issues_one, issues_many}` | "No findings were recorded", "1 finding", "{n} findings", "in 1 issue", "in {n} issues" |
| `groups` | map `decide \| fix \| verify \| decided \| within_scope` → `{label, one, many}` | labels "Decide", "Fix", "Verify" (owner, 2026-09-23), "Decided", "Within limits"; templates such as "{n} needs your decision" / "{n} need your decision" |
| `questions` | `{one, many}` | "1 question for you", "{n} questions for you" |
| `not_loaded` | `{text}` | "{count} of {total} parts not loaded" |
| `drawings` | `{read_one, read_many, candidates_one, candidates_many, more}` | "Drawing read: {names}", "Drawings read: {names}", "Same-name drawing found but not open: {names}", "Same-name drawings found but not open: {names}", "{names} and {n} more" (*added 2026-09-23, decision 10A*) |
| `contacts` | `{one, many}` | "1 size-for-size contact", "{n} size-for-size contacts" |
| `resume` | `{with_tokens, without}` | "Sending resumes the review once. Its last round sent {tokens} input tokens." / "Sending resumes the review once." |
| `read_only` | str | "The backend restarted, so this review is shown from its run folder. Follow-ups, decisions and answers are off." |
| `goal_states` | map `issues \| checked \| not_reached \| not_applicable` → str | "issues found", "checked, no issue", "not reached", "not applicable" |
| `goal_reasons` | map `unresolved \| skipped \| failed \| out_of_scope \| no_check` → str | "evidence missing", "skipped", "a check failed", "out of scope", "no check ran" |
| `goals` | list of `{id, title, items: list[str], prefixes: list[str]}` | the eight goals of research R2.4, in the owner's order |
| `labels` | see section 7 | the card vocabulary served by `GET /labels` |

Rules a test asserts: every template's placeholders are exactly the ones the code fills; every goal
id is unique; every checklist item of `agent/checklist_v1.yaml` except `coverage.closeout` is in
exactly one goal's `items`; every check id in `attention_policy_v1.yaml` `classes` has exactly one
goal by longest prefix; every `FindingStatus`, `Severity` and coverage bucket value has a label;
every `ChatError` subclass's `error_class` has an `errors` entry.

## 2. The summary (`reviewer/src/swreview/report/summary.py`, pure)

`review_summary(ranking, session, package, *, usage=None) -> ReviewSummary`. Reads its arguments and
the words file; imports no provider and no settings; writes nothing.

### `ReviewSummary`

| Field | Type | Rules |
|---|---|---|
| `version` | str | the words file's `version` |
| `headline` | str | from `headline` templates; "No findings were recorded" when there are none |
| `findings` | int | `len(session.findings)` |
| `issues` | int | `len(ranking.rows)` |
| `groups` | list[`SummaryGroup`] | `decide`, `fix`, `verify` always, in that order; then `decided` and `within_scope` only when non-zero |
| `modelling_practice` | `ModellingPractice \| None` | from the ranking row with `family` set (feature 008); `None` without one |
| `questions` | `QuestionList` | the open evidence requests in session order |
| `not_loaded` | `NotLoaded \| None` | from `unexamined.not_examined(package)`; `None` when every instance was read or there is no package |
| `drawings` | `DrawingsLine \| None` | from `drawings_of(package)` (*added 2026-09-23, decision 10A*): the drawings read and the same-name drawings found but not open; `None` when neither exists or there is no package |
| `goals` | list[`GoalLine`] | one per goal, in the words file's order |
| `contacts` | `ContactList \| None` | from `contacts_of(session)` (feature 010's list); `None` when absent or empty |
| `component_names` | dict[str, str] | every component with a non-blank name, `{cmp id: name}` |
| `resume_input_tokens` | int \| None | `usage.last_conversation_input()` when a ledger is passed; else `None` |
| `resume_text` | str | from `resume`, with the number formatted with thousands separators when known |

Partition, asserted: `sum(group.count) + (modelling_practice.findings if present else 0) ==
findings`.

### `SummaryGroup`

| Field | Type | Rules |
|---|---|---|
| `kind` | Literal["decide", "fix", "verify", "decided", "within_scope"] | research R2.3's first-match rule (within scope, decided, decide, fix, verify); listed in the display order decide, fix, verify, decided, within scope |
| `label` | str | from `groups.<kind>.label` |
| `count` | int | findings in the group, a folded family's excluded |
| `text` | str | `one` or `many` template with `{n}` |
| `by_goal` | list[`GoalCount`] | goals with a non-zero count in this group, in goal order |

`GoalCount`: `{goal: str, title: str, count: int}`.

### `ModellingPractice`

`{title: str (the family row's title), findings: int, rules: int (the row's rule_count),
finding_ids: list[str] (the row's member_finding_ids, in the row's order)}`.

### `QuestionList` and `QuestionView`

`QuestionList`: `{count: int, text: str | None (None when count is 0), items: list[QuestionView]}`.

| `QuestionView` field | Type | Rules |
|---|---|---|
| `id` | str | `ER-001` |
| `question` | str | the request's `question`, or its `what` when it has no short form |
| `options` | list[str] | the request's `options`, in order; empty for a free-text answer |
| `blocks` | str \| None | the checklist item id |
| `blocks_title` | str \| None | the title of the goal whose `items` hold `blocks` |
| `what`, `why` | str | verbatim |
| `about` | list[`{id, name}`] | each entity id with the component's name or the document's file name; `name` is `None` for any other id |

### `NotLoaded`

`{count: int, total: int, text: str}`.

### `DrawingsLine`

*Added 2026-09-23 (owner decision 10A).* `{read: list[str], candidates: list[str], text: str}`:
`read` the file names of the drawings the review read (a native record or a PDF-ingested sheet), in
document-id order; `candidates` the file names of the same-name drawings found beside a reviewed file
but not open, in document-id order, once per file and never one the review read (a confirmed and read
candidate is read); `text` the one line the page prints (`contracts/review-summary.md` section 4).

### `GoalLine`

| Field | Type | Rules |
|---|---|---|
| `goal`, `title` | str | from the table |
| `state` | Literal["issues", "checked", "not_reached", "not_applicable"] | research R2.4's precedence |
| `state_label` | str | from `goal_states` |
| `findings` | int | non-within-scope findings mapped to the goal, a folded family's included (the goal says whether a family was reached, the groups say what to do) |
| `reason` | str \| None | from `goal_reasons` for `not_reached` and `not_applicable`; `None` otherwise |
| `detail` | str \| None | the recorded sentence behind the reason, verbatim (a close-out row's or a pre-run row's `reason`); `None` when there is none |

### `ContactList` and `ContactView`

`ContactList`: `{count: int, text: str, items: list[ContactView]}` in the session's order.
`ContactView`: `{id, component_ids, names: list[str | None], configuration, kind, kind_label,
volume_mm3: float | None, text}` where `text` joins the names (the id where a name is blank) with
"and".

### `ReviewRanking(Ranking)`

`report/attention.Ranking` plus `summary: ReviewSummary`. What `GET /sessions/{chat_id}/attention`,
the snapshot and the disk route answer. `Ranking` itself, `AttentionRecord` and the check bodies are
unchanged.

## 3. The names helper (`reviewer/src/swreview/report/names.py`, pure)

| Function | Rules |
|---|---|
| `component_names(package) -> dict[str, str]` | `{component.id: component.name}` for every component, blank names included, exactly the map `report/explanations.py:155-156` builds (which then calls this) |
| `with_component_names(text, names) -> str` | every `cmp:` id token (the IR's `^cmp:[0-9]{4,}$` pattern) whose name is non-blank is replaced by the name; any other text, and an id with no or a blank name, is kept |

## 4. `EvidenceRequest` (`reviewer/src/swreview/report/session.py`)

| Field | Type | Rules |
|---|---|---|
| `question` | str \| None, default None | at most 140 characters, not blank |
| `options` | list[str], default [] | at most 5; each at most 60 characters, not blank; distinct |
| `blocks` | str \| None, default None | one of `attention.CHECKLIST_ITEM_IDS` |

Omitted from the dump when `None` or empty, so a session written before this feature keeps its
bytes. `$defs.EvidenceRequest` in `specs/001-agentic-design-review/contracts/review-session.schema.json`
gains the three as optional properties (`question`: string, `maxLength` 140; `options`: array of
string, `maxItems` 5, items `maxLength` 60; `blocks`: string), none in `required`. The tool
validates the same limits before constructing the model and refuses with an `error_result`.

## 5. `NotExamined.headline` (`reviewer/src/swreview/report/unexamined.py`)

`headline: str` added beside `sentence`: "{count} of {total} parts were not loaded: {names by
state}. {CANNOT_SEE}", names only, grouped by state in package order, each group followed by its
state word. `sentence` and `instances` are unchanged.

## 6. The usage ledger (`reviewer/src/swreview/agent/events.py`)

`UsageLedger` gains `_rounds_at_text_done: int | None`, set to `len(self._rounds)` on each
`text.done`, and `last_conversation_input() -> int | None`: the `input_tokens` of round
`_rounds_at_text_done - 1`, or `None` when there has been no `text.done`, no round before it, or
that round reported no input.

## 7. The labels payload (`GET /labels`)

The words file's `labels` block, verbatim:

| Key | Type | Content |
|---|---|---|
| `version` | str | the words file's version |
| `status` | map `FindingStatus` → str | `checked_within_scope` → "checked within scope"; the other three as themselves |
| `severity` | map `Severity` → str | the four words as themselves |
| `bucket` | map bucket → str | `out_of_scope` → "out of scope"; the other four as themselves |
| `evidence_status` | map `open \| answered` → str | "open", "answered" |
| `contact_kind` | map `zero_volume \| possible_only \| thread_model` → str | "touching", "possible only", "thread model" |
| `errors` | map error class → str | one sentence per class saying what to do next |

## 8. The snapshot (`reviewer/src/swreview/report/snapshot.py`)

`review_snapshot(session, package, *, run_id, usage=None, chat_state=None, last_seq=None,
read_only_reason=None) -> dict`, the body of `GET /sessions/{chat_id}/snapshot` and
`GET /reviews/{run_id}`:

| Key | Type | Rules |
|---|---|---|
| `run_id` | str | the run folder's name |
| `read_only` | bool | `read_only_reason is not None` |
| `read_only_reason` | str \| None | the words file's `read_only` for the disk route |
| `chat_state` | str \| None | the live chat's state (`running`, `waiting_engineer`, `ended`, `failed`); `None` from disk |
| `last_seq` | int \| None | the live sink's `seq`; `None` from disk |
| `document` | `{path, configuration}` \| None | the package's root document path and its active configuration |
| `findings` | list[Finding JSON] | `session.findings` in session order, dispositions included |
| `evidence_requests` | list[EvidenceRequest JSON] | in session order |
| `coverage` | list[`{bucket, item}`] | every coverage item, bucket by bucket in the order `checked, skipped, unresolved, failed, out_of_scope`, the shape the `coverage` event carries |
| `ranking` | `ReviewRanking` JSON | `rank(session)` plus its summary |
| `not_examined` | NotExamined JSON \| None | `unexamined.not_examined(package)` |

The pane fixture `extractor/SwReview.AddIn.Tests/Fixtures/review-big-assembly.json` is this object
for feature 008's `big-assembly` fixture, plus `labels` (section 7) so the page tests need no route.

## 9. Error bodies

`UnknownEvidenceRequest` and `AlreadyAnswered` carry `request_id: str`; `ChatError.body()` adds
`request_id` to the JSON when set: `{error_class, message, retryable, request_id}`. Every other
error body is unchanged. `UnknownReview` (404) is new, for the disk route.

## 10. `CheckResult.rule_statements`

`rule_statements: dict[str, str]` on the Model check body: every rule id the grade names (findings
and coverage rows) with its `RULES` statement; an id the catalogue lacks is absent. Additive; the
Standards body is unchanged.

## 11. The host (`extractor/SwReview.AddIn/Review/`)

### `SessionRecord`

| Member | Type | Rules |
|---|---|---|
| `Document` | `PageDocument?` | the document `review.started` names; null for a check or remodel record |
| `StartedAt` | `DateTimeOffset?` | from `ReviewHostOptions.Now` when the review was tracked; null for a check |
| `RunId` | string | `Path.GetFileName(RunDirectory)` |

`TrackSession(chatId, runDirectory, document, startedAt)`; `TrackCheck` unchanged.

### Page-to-host rows

| Row | Payload | Reply |
|---|---|---|
| `sessions.list` | `{}` | `sessions {items: [{chat_id, run_id, run_dir, path, configuration, started_at}]}`, reviews only, in the order tracked |
| `session.forget` | `{chat_id}` | `sessions {items}` after removing that review; `LatestSession` set to null if it was that record; an unknown id refused as `report.open` refuses one |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id, chat_id?}` | unchanged reply; `chat_id` resolves the run folder through the host's record |

### `EntityShowRequest.RunDirectory`

`string?`, set by `PaneActions` from the host's record when the page named a `chat_id`, never from
the page. `SwEntityResolver`'s lookups become `(id, runDirectory)`; `RunPackageIndex.DocumentPath`
and `ComponentFullPath` take an optional folder that wins over the `Func<string?>` it was built with.

### `ActiveConfigurationWatch` (`extractor/SwReview.AddIn/ActiveConfigurationWatch.cs`)

Holds at most one subscription: `Follow(object? activeDocument)` unsubscribes the previous document
and subscribes the new one's `ActiveConfigChangePostNotify` when it is a part or an assembly;
`Dispose` unsubscribes. The event calls the `Action` it was built with (the add-in's document fan-out)
and swallows every exception. Subscribe and unsubscribe are delegates so a test drives it with a fake
document.

## 12. Page state (`extractor/SwReview.AddIn/Review/ReviewPage/app.js`)

| State | Type | Rules |
|---|---|---|
| `labels` | object \| null | `GET /labels`, refreshed after each `init` naming a backend; null keeps raw tokens |
| `view` | `'results' \| 'transcript'` | starts `results`; one class on `body` |
| `reviews` | array | the host's `sessions` items, as last received |
| `summary` | object \| null | the last `ranking.summary` for the shown chat |
| `questionIndex` | int | the question on screen |
| `drafts` | map chat id → `{answers: {request id: text}, skipped: {request id: true}}` | page memory only |
| `pinned` | map chat id → array of `{question, answer}` | page memory only |
| `readOnly` | string \| null | the snapshot's `read_only_reason` |
| `replayUntil` | int | 0, or the snapshot's `last_seq` while a transcript replay runs |
| `transcriptLoaded` | bool | whether the shown chat's transcript has been built or replayed |

## 13. Relationships

```
session.json + package.json ──rank()──▶ Ranking ──review_summary()──▶ ReviewRanking.summary
      │  (live run or run folder)               ▲             ▲             ▲
      │                                          │             │             └─ UsageLedger.last_conversation_input (live only)
      │                                          │             └─ review_words_v1.yaml (groups, goals, words, labels)
      │                                          └─ feature 008: AttentionRow.family / rule_count (the modelling-practice line)
      └──review_snapshot()──▶ /sessions/{chat}/snapshot, /reviews/{run_id} ──▶ the page's Results
                                                                                   ▲
host SessionRecord{Document, StartedAt} ──sessions.list──▶ chips ─────────────────┘
feature 010: ReviewSession.contacts ──contacts_of()──▶ summary.contacts ──▶ the contacts fold
feature 011: package drawing_records, drawings, drawing_candidates ──drawings_of()──▶ summary.drawings ──▶ the drawings line
GET /labels ──▶ status, severity, bucket, evidence and error words on every card
```
