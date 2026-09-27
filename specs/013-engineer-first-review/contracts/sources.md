# Contract: Sources, the Answer Basis, and the Explanation Pass

Normative for FR-041 to FR-044 and User Story 5. Research R2.29 to R2.31, R2.39. Amends feature 001's
`review-session.schema.json` (`source` on `Finding`, `EvidenceRequest`, `CoverageItem`); feature
002's `chat-events.schema.json` (`text.done.basis`); feature 007's `contracts/attention.md` section 4
(`NotClosed.source`) and section 6 (the explanation fallback); feature 009's `contracts/questions.md`
sections 2 to 4 and 7, `contracts/plain-words.md` sections 1 and 7, `contracts/views.md` section 4;
feature 011's `contracts/questions.md` (drawing questions carry `source: code`).

## 1. The token

`source: Literal["code", "model"]`, optional on three records, omitted from `session.json` at each
kind's usual author, and never echoed in a tool result, so no byte the model reads moves:

| Record | Default (omitted) | Written as the other value by |
|---|---|---|
| `Finding` | `code` | `record_drawing_finding` (`tools/session.py:214-288`) writes `model` |
| `EvidenceRequest` | `model` | the drawing check (`tools/drawings.py:96-107`) and the part-roles question write `code` |
| `CoverageItem` | `code` | `mark_coverage` (`tools/session.py:209`) writes `model` |

Why the defaults differ: a request's tool result (`request_evidence`) keeps its bytes, and an older
session's code question reads as AI guidance, never the reverse; an older model-written coverage row
shows no label rather than a false "Checked by code" (surfaces label coverage only when `model`). On
load, a finding with no `source` whose check is `drawing.manufacturing_inputs` reads as `model` (the
one pre-013 non-numeric writer).

**Tool results echo a record without `source`.** Two tools return the whole record they wrote:
`mark_coverage` returns `{coverage_item: as_json(item)}` (`tools/session.py:210`) and
`record_drawing_finding` returns `{finding: as_json(finding)}` (`:288`). Both write `model`, the
value the serializer keeps, so both echo the record through one helper, `as_json(record,
exclude={"source"})` (`tools/query.py:69` gains the optional `exclude`), and their results stay
byte-identical to today's; `session.json` still stores the field. Every other tool result that
carries a record carries one written at its kind's default, so the field is already absent there.
*Added on review, 2026-09-26.* *Landed as (T097, 2026-09-27):* `get_finding` (`tools/session.py`)
returns any finding "exactly as the session records it", so a drawing finding the model wrote
would carry `source: model` there; it echoes through the same `as_json(record, exclude=ECHO)`
(`ECHO = {"source"}`), the third such tool. The load rule is a `Finding` validator
(`findings.MODEL_FINDING_CHECK`); a stated source is never overridden.

Bodies sent to the pane always state the source explicitly: `pane_finding` (`report/titles.py`), the
evidence and coverage event bodies (`tools/context.py:268-273`, `:355-358`), the snapshot
(`report/snapshot.py:67-73`), `QuestionView.source`, `GroupRow.source` (with its `chip`,
`grouped-list.md` section 3), `GoalLine.detail_source`, and `NotClosed.source` (the last two omitted
when `code`, so `attention.json` keeps its bytes and the page prints a coverage label only when the
field is present, never comparing its value). *Landed as (T101, T102, 2026-09-27):* a finding
(`pane_finding`) and a request (`EvidenceRequest.pane_body`, shared by the `evidence.requested`
event and the snapshot) always state it; a coverage body - the `coverage` event's item and the
snapshot's - states it only when `model`, as `NotClosed.source` does, since the dump already omits
`code`: an older model-written row loaded from disk reads as `code` and must show no label rather
than a false "Checked by code" (the reason section 1 gives for the defaults).

## 2. The words and where they show

`report/review_words_v1.yaml` `labels.source: {code: "Checked by code", model: "AI guidance"}`, placed
before `errors` (which stays last, `ErrorLabelsCoverTheHostTests`), served by `GET /labels`. The page
prints `labelOf(labels, "source", token, "")` - a lookup, no comparison:

- a chip on the finding card's line (`render.js:297-304`); on the grouped list's rows the page
  prints `GroupRow.chip` verbatim, which the backend sets for model rows and leaves null for code
  rows (`grouped-list.md` section 3);
- the question pager line (`render.js:561-565`) and the evidence card head (`render.js:513-515`),
  replacing the one title "The review needs an input" for both kinds;
- goal detail and coverage rows, only when the body carries a source (`detail_source` and
  `NotClosed.source` are sent only for `model`);
- the pinned answer and the transcript's assistant block ("AI guidance", section 3).

`report.md`: a model finding gets "- Source: AI guidance"; the evidence requests table gains a Source
column; a model-written close-out sentence is marked "(AI guidance)".

## 3. The answer basis

```python
# reviewer/src/swreview/report/sources.py
READ_EXCLUDED = frozenset({"request_evidence", "mark_coverage", "record_drawing_finding",
                           "get_review_checklist"})
def answer_basis(steps: Sequence[InvestigationStep], package: EvidencePackage | None,
                 words: Words) -> str: ...
```

Reads are the steps with status ok whose tool is not in `READ_EXCLUDED` (the writers and bookkeeping
tools of `session_tools()`, `tools/registry.py:136-144`). Words (`answer_basis` in the words file):

| Case | Line |
|---|---|
| no read | "No evidence was read for this answer: this is general guidance." |
| one read | "Based on 1 result read for this answer." |
| n reads | "Based on {n} results read for this answer." |
| appended when `drawings_of(package).read` is empty | " No drawing was read in this review." |

The runner keeps a step marker that advances when a turn ends; it wraps the provider's `on_event`
(`agent/runner.py:1036-1043`) so every `text.done` body becomes `{text, basis}`, with `basis` computed
from `session.steps` since the marker. The pre-run's checks count in turn 1 (recorded before it,
`agent/runner.py:1270-1300`); a restated check counts in its answer turn; a stopped turn's steps roll
into the next answer. The model's text is never parsed. The provider adapters are unchanged; the
explanation pass never reaches the sink, so it gets no basis.

`chat-events.schema.json`: `text.done`'s body gains optional `basis` (string); `text.delta`
unchanged. Page: `pinnedAnswer` (`render.js:217-225`) prints the "AI guidance" chip, then `basis` as
its first line, then the answer; the transcript's assistant block (`app.js:699-726`) gets the chip at
the first delta and the basis at `text.done`. A turn that ends without `text.done` keeps "No answer:
the turn ended (…)" with no chip. An older `text.done` with no `basis` renders as before.

For the sitting's follow-up turn this gives: "No evidence was read for this answer: this is general
guidance. No drawing was read in this review."

## 4. Explanations

- `fill_fallbacks` becomes `keep_explained(session, rows)`, which only prunes
  `finding_explanations` to the explained rows (`report/explanations.py:276-281`,
  `agent/runner.py:967`); nothing stands in for a missing explanation.
- `EXPLANATION_UNAVAILABLE` is kept as a legacy constant; `rank()` skips it when attaching
  (`report/attention.py:463-467`), so older run folders and the replay fixtures stop rendering it; the
  fixtures stay unedited as evidence of the legacy line. *Amended 2026-09-27 (T158; default taken
  2026-09-27, the owner may revise):* until the checklist moved (T157): decision 3A then had the three
  replay fixtures regenerated by the current code (008 `replay.md` section 8), which writes no
  fallback, so they hold the line no more - never edited by hand either way. The filter's evidence is
  the legacy session of `test_a_legacy_fallback_reaches_no_row_no_record_and_no_report`, and
  `test_the_regenerated_replay_fixtures_hold_no_legacy_line` holds that no regeneration brings it
  back.
- Real text is labelled "AI guidance" in the card fold (`app.js:1528-1529`) and in `report.md`
  ("   - AI guidance: …" instead of "Explanation:", `report/markdown.py:405-407`).
- `parse_explanations` keeps each valid item and returns the rejections - `(finding id or position,
  rule)`, the rule one of `unknown_id`, `repeated_id`, `too_long`, `not_json`, `not_a_list` -
  instead of rejecting the batch (`report/explanations.py:84-120`). `generate_explanations` logs the
  rejections and any provider error to the backend log (`logging.getLogger("swreview.explanations")`),
  never the model's text (`:252-257`), and records nothing else in the session.
- The request asks for 300 characters or fewer per explanation, so `MAX_EXPLANATION_CHARS` (480) has
  margin; the cap itself is unchanged.
- The explanation pass sends only rows that are not suppressed (`grouped-list.md` section 1).

## 5. Tests

`test_tools_session.py`: a drawing finding carries `model`; a `request_evidence` request is `model` and
omitted from the dump; a `mark_coverage` row is `model`; the results of `mark_coverage` and
`record_drawing_finding` are byte-identical to today's (no `source` in the echoed record) while
`session.json` stores `model`. Drawing check and part-roles tests: their
requests carry `code`. `test_session.py`, `test_schema_sync.py`: old sessions keep their bytes on a
round trip; an old drawing finding reads as `model`. `test_events_schema.py`: `basis` optional.
`test_tool_payload.py`: code findings' bytes unchanged. `test_review_words.py` and a labels-route
test. `test_answer_basis.py`: no steps; only writers; failed steps not counted; n reads; a drawing read
versus none. A runner test with the scripted provider: `text.done` carries the basis; turn 1 counts
the pre-run; the answer turn counts the restated check; a stopped turn rolls into the next.
`test_finding_explanations.py`: no fallback persisted; a legacy fallback reaches no row,
`attention.json` or `report.md`; partial acceptance; each rejection logged with its rule and no model
text (`caplog`); invalid JSON stores nothing. C#: `ReviewPageLabelsTests` (source words; no labels, no
chip); `ReviewPageQuestionsTests`, `ReviewPageDrawingQuestionsTests` (a code and a model question each
show their chip); `ReviewPageInjectionTests` (the chip and the basis are text; a hostile label renders
literally); `ReviewPageEventStreamTests`, `ReviewPageTurnStateTests` (the basis first; an old
`text.done` as before); `ReviewPageDefaultViewScanTests` (no raw `code` or `model` token visible;
"No model explanation" rendered nowhere).
