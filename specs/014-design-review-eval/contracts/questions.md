# Contract: Questions - Request Calls, the One Matcher, and the Question Columns

Normative for FR-019, FR-020, FR-053 and FR-060, FR-021 for the question columns, User Story 3
scenarios 5 to 8, and the scripted-answer rule FR-022 and `scripted-answers.md` section 3 call.
Research D4, §7 ("Questions"), §8.3, §8.15. Line numbers are at `be01974`; paths are under
`reviewer/src/swreview/` unless another root is given. Every example value is fictional.

What this contract fixes: what counts as a question and how it is read from a run folder; how ids
are compared; the one relation that pairs a request with an earlier question, a scripted answer or a
question-count rule; the key's two question entries; and the scorecard columns they feed. It lives
in one module, `benchmark/questions.py`, which the answer driver and the scorer both import: there is
no second matcher (FR-053).

## 1. Request calls and questions

A **request call** is a step of `session.steps` whose `tool` is `request_evidence`. Every call is
one: `SessionSink.record` appends a step for an ok call, an error and a guard answer alike
(`tools/registry.py:362-375`). The guard records nothing else for a refused call, no request, id or
event (`tools/session.py:110-126`; 013 `contracts/re-ask-guard.md` section 3), so a column counting
recorded requests would read R-2's and R-3's failures as zero (research D4).

Each call is read with its stored full result, `tool-results/step-<index>.json`, which every recorded
step of a review writes (`tools/registry.py:391-432`; the folder is set by `agent/runner.py:1606`):

| From | Field |
|---|---|
| the step | `index`; `arguments.blocks` (the **item**, `null` when absent); `arguments.entity_ids` |
| the stored result | the **outcome**, from `payload.status`, and the **request id** |

| Stored result | Outcome | Request id | A question |
|---|---|---|---|
| envelope `status` `error`: an unknown id or a short-form refusal (`tools/session.py:104-109`) | none | none | **no**: counted in no question column; the model is told what to fix and its next call is the question |
| `open` | `recorded` (seen by the engineer) | `payload.evidence_request.id` | yes |
| `already_answered` | refused | the cited request (`tools/session.py:353-369`) | yes |
| `already_asked` | refused | the cited request | yes |
| `closed_by_code`: a code-owned item (`:112`), a drawing request on a document with no attached drawing (`:113-114`, `:301-340`) | refused | none | yes |

The stored result is read through the one reader beside its one writer,
`tools/registry.read_stored_result(run_dir, session_id, step, *, tool, arguments)` (plan decision
RF-30), passing the step's tool and arguments; the replay's check (`benchmark/replay.py:1012-1036`)
calls the same function, and this contract restates none of its rule. An `Unstored` answer (the file
`missing`, `unreadable`, carrying another `session_id`, written so a stale file is detectable,
`tools/registry.py:407-409`, or naming another call) makes the package's call columns (section 6) read
not assessed, naming the steps and the reason. Nothing is guessed (Principle I). A session recorded
before feature 008 has no stored results at all and reads the same way.

A **question** is a request on the session (`session.evidence_requests`): model-written (`source`
`model`), created by the call whose outcome recorded its id; or code-written (`source` `code`): the
part-roles question and the drawing check's candidate and governing questions, written through
`record_question` (`tools/session.py:173-195`).

**In time.** A question is **answered before** a call when the answer log's point whose `sent`
holds it has `steps_before` at most the call's index (`scripted-answers.md` section 5). It is
**open at** a call when the call that recorded it has a lower index and it was not answered before
the call.

## 2. Ids

One `QuestionIds` per package, built on `tools/context.context_for(package)` (`tools/context.py:575-582`),
whose lookups (`:187-193`) are the ones `request_evidence` validated the call's ids against.

**Instances**, for re-asks, repeats of open questions, scripted answers and question-count rules:

| Id | Resolves to |
|---|---|
| a component instance | itself |
| a hole | the instance that owns it (`Hole.component_id`, `ir/models.py:658`) |
| a fastener | its instance (`Fastener.component_id`, `ir/models.py:709`) |
| a document | every component instance of it (`ComponentInstance.document_id`, `ir/models.py:379`); itself when it has none, as the root assembly |
| any other id (feature, joint, mate, drawing record) | itself |

Two instances of one pin stay two. The product compares ids raw (`report/session.py:190-192`);
reading a hole or a fastener as its instance is research §8.3's widening, and reading a document as
its instances is this contract's (plan decision QA-11): the model names a part by its document or by
its instance interchangeably, and without it a scripted answer keyed to the plate's instance would
miss a question naming the plate's document, and an answered question on a one-instance part would
not be re-asked by a call naming its document.

**Documents**, for unanswerable-request entries only: the product's drawing guard's rule, a
component names its document and a hole or fastener its component's (`tools/session.py:280-298`).
`_documents_named` becomes the public `documents_named` (its one caller, `:322`, renamed with it) and
the eval calls it on the same context. No second document rule.

## 3. The one relation and its four uses

```python
# reviewer/src/swreview/report/session.py  (extracted from covering_requests, :203-209)
def covers(blocks: str | None, ids: frozenset[str],
           earlier_blocks: str | None, earlier_ids: frozenset[str]) -> bool: ...

# reviewer/src/swreview/benchmark/questions.py
def asks_within(later_item: str | None, later_ids: frozenset[str],
                earlier_item: str | None, earlier_ids: frozenset[str]) -> bool: ...
```

**The product's predicate, extracted once** (plan decision RF-6). `covers` is the covering test
written inline in `covering_requests` today (`report/session.py:201-209`, 013's `re-ask-guard.md`
section 3): true when `blocks == earlier_blocks` (`null` equals `null`) and either `ids` is
non-empty and a subset of `earlier_ids`, or both are empty and `blocks` is not `null`. A question
naming neither an item nor an id is covered by nothing (`:201-202`). `covering_requests` calls it
for each model-written request; nothing else about the guard changes, and its own tests pin that.

`asks_within` wraps it: both id sets are resolved to instances (section 2) and passed to `covers`,
and one branch is added: a later request naming an item and no ids asks within any earlier question
on that item, where the product covers it only when the earlier one named no ids either (`:208`).
So `asks_within` is `covers` widened in exactly two ways, and holds no second copy of it: ids are
compared after resolution, and the item-only branch is R-3's "now give numeric limits" (research
§8.3). A request naming neither an item nor an id asks within nothing, as `covers` never covers
one.

| Use | Later | Earlier | Rule |
|---|---|---|---|
| **Re-ask** (FR-020) | a request call | a model-written question answered before it | the latest answered (by point, then session order) is cited as `of` |
| **Repeat of an open question** (FR-020) | a request call that is no re-ask | a model-written question open at it | the latest open one is cited as `of` |
| **Scripted answer** (FR-022, FR-053) | an open request that is not the part-roles question (section 4), model- or code-written | each case-file entry that is not `part_roles` | exactly one entry: a delivery; several: unscripted `ambiguous`, naming them; none: `no_answer`, or `names_nothing` when the request names no item and no id |
| **Question-count item rule** (FR-060) | a request call | the rule's item and ids | a rule naming no ids: item equality alone |

- **Only model-written questions are earlier questions** (plan decision QA-12). A code question
  covers only itself in the product (`report/session.py:194-199, 206`): the part-roles question has
  no item and names every unclear part, so under the relation any later model question naming one
  of them with no item would read as a re-ask of "All bought".
- **A re-ask outranks a repeat**, as the guard answers `already_answered` before `already_asked`
  (`tools/session.py:117-120`).
- **At most one entry matches a request that names ids**: `scripted-answers.md` row 8 refuses two
  entries on one item whose resolved ids intersect, so only an item-only request can match several
  (research §8.3; RR3-4).
- **Unmatched** (FR-053, US3-7): a call naming no item and no id. It is no re-ask, no repeat and no
  count rule's call, and is listed in its own column, never silently "not a re-ask" (research D4).

## 4. The part-roles question

```python
def is_part_roles_question(request: EvidenceRequest) -> bool: ...
```

True for a request with `source` `code`, `question` equal to `part_roles.QUESTION`
(`checks/part_roles.py:233-235`), `options` equal to `(OPTION_ALL, OPTION_NONE)` (`:236-237`) and no
`blocks`: the fields 013 `contracts/part-roles.md` section 8 fixes. Its entity ids are not compared,
as `answered_roles` compares them against the spec (`:909-914`), because the spec needs the profile
and the scorer has only its digest (FR-013 records no path); at run time the question on the session
is the one `ask_part_roles` has just recorded from the same roles (`agent/runner.py:470-487`). One
function serves the driver and the scorer (plan decision QA-14). A model question with the same
words is not it (`source` `model`), nor is the drawing candidate question.

It is matched only by this identity: the case file's `part_roles` entry answers it, and a
`part_roles` count rule counts it. It is never an earlier question and never matched by ids.

## 5. The key's question entries

The answer-key contract carries both lists; each entry also carries the tag fields every graded item
does (held out with its digests, or tuned-on; FR-031). Neither ever decides the pane study's verdict
(section 6).

### 5.1 Unanswerable requests (FR-019)

```json
"unanswerable_requests": [
  {"id": "U-1", "documents": ["doc:0003"], "item": null, "tag": "tuned_on",
   "description": "The bought pin's drawing: a vendor part has none to supply."}
]
```

A request call matches an entry when `documents_named` of its ids intersects the entry's
`documents`, and the entry's `item` is `null` or equals the call's item. **Every** matching call is
counted, whatever its outcome: recorded, refused as asked or answered, or closed by code. R-2's
entry names the pin's document and no item, so a request naming the pin, its document or its holes
matches (research §8.3).

### 5.2 Question-count rules (FR-060)

```json
"question_counts": [
  {"id": "Q-1", "part_roles": true, "min": 1, "max": 1, "tag": "tuned_on",
   "description": "Exactly one part-roles question."},
  {"id": "Q-2", "item": "interfaces.fit", "ids": ["cmp:0001", "cmp:0002"], "max": 1,
   "tag": "tuned_on", "description": "At most one question on the pin's fit."},
  {"id": "Q-3", "item": "fasteners", "max": 1, "tag": "tuned_on",
   "description": "At most one question on which fasteners go in the holes."}
]
```

- **Count.** A `part_roles` rule counts the code-written requests on the session that are the
  part-roles question. An item rule counts the request calls section 3's fourth use matches,
  refused ones included (research §8.3): a model that asks again did ask again.
- **Miss.** A count below `min` or above `max` is one question-count miss for the rule.
- `min` is 0 or 1, default 0; `max` is optional, at least `min`, unbounded when absent. A minimum
  of one is all an anchor needs (R-1), code asks the part-roles question at most once, and the oracle
  review asks each rule's minimum as one question (section 8), which a second identical call would
  turn into a repeat of an open question.

### 5.3 Refusals at key load (FR-009)

Ids are resolved against the package only when it exists (D7); each refusal names the entry.

| Entry | Refused when |
|---|---|
| unanswerable | `documents` empty; an id that is not a document of the package; `item` not a checklist item; an id repeated among entries; two entries whose documents intersect and whose items are equal or either `null` (one call would count twice) |
| count rule | neither `part_roles` nor `item`, or both; `ids` beside `part_roles`; neither `min` nor `max`; `min` other than 0 or 1; `max` below `min`; `item` not a checklist item; an id that is not a component instance or a document; two `part_roles` rules; two rules on one item whose resolved ids intersect or either of which names none; a rule with `min` 1 whose one oracle question (section 8) would match an unanswerable entry, the key demanding a question it calls unanswerable (names both) |

## 6. The columns

`PackageScore` gains these fields; the scorecard contract embeds them. Lists only, counts derived
where rendered (SP-14). `null` is **not assessed**, with the reason in the scorecard's one
`not_assessed` map (`scoring.md` section 7; plan decision INT-2: one map over every column, not a
second one for these), and renders "not assessed", never 0 (FR-021, US3-8).

```json
"re_asks": [{"step": 31, "outcome": "recorded", "request_id": "ER-006", "of": "ER-002"}],
"open_repeats": [{"step": 18, "outcome": "already_asked", "request_id": "ER-003", "of": "ER-003"}],
"unanswerable_requests": [
  {"step": 17, "entry": "U-1", "outcome": "recorded", "request_id": "ER-003"},
  {"step": 18, "entry": "U-1", "outcome": "already_asked", "request_id": "ER-003"}],
"unmatched_requests": [],
"question_counts": [{"entry": "Q-1", "count": 1, "min": 1, "max": 1}],
"unscripted_questions": [{"request_id": "ER-004", "reason": "no_answer"}],
"bound_reached": false,
"not_assessed": {}
```

`outcome` is `recorded`, `already_answered`, `already_asked` or `closed_by_code`.

| Column | Lists | Assessed when |
|---|---|---|
| `re_asks` | each call section 3 calls a re-ask; rendered split into **seen** (`recorded`: the engineer was asked again) and **refused** (the rest) (FR-020) | every request call is readable (section 1), and every answered request is placed by an answer log |
| `open_repeats` | each call that is a repeat of an open question, unscripted or not yet answered (FR-020, D3) | as `re_asks` |
| `unmatched_requests` | each unmatched call (FR-053) | every request call is readable |
| `unanswerable_requests` | each (call, entry) match (FR-019) | the key has entries, and every call is readable |
| `question_counts` | every rule's count; **misses** rendered from those outside their bounds (FR-060) | the key has rules; item rules also need every call readable |
| `unscripted_questions` | each request an answer point gave nothing, once, with its first reason (FR-024) | the package has an answer log |
| `bound_reached` | the log's `ended` is `bound_reached` (FR-025, D16) | the package has an answer log |

- A run folder recorded before this feature has no answer log; a session scored on its own (a
  pane session) may hold answered requests and no log: whatever needs the log reads not assessed,
  never zero.
- **The log against the session.** Before these columns are scored, every `sent` id must name a
  request the session holds answered, and every answered request must have been sent at exactly one
  point. A disagreement refuses the package with one line naming the request: the folder was
  altered, or written by something other than the driver.
- **Behavioural stops**: the calls up to the stop are counted (FR-041); the log reads
  `turn_did_not_end`.
- **One call, several columns, by definition** (research §8.15): R-2's second request is a repeat of
  an open question and a second unanswerable request (US3-6); a re-ask on an item a count rule
  bounds is also counted by the rule. A call is never both a re-ask and a repeat, and an unmatched
  call is in no other column.
- **None decides.** Every column is shown per arm with a paired interval, named when it excludes
  zero (FR-059). A change to any rule of this contract bumps the scoring-rules version (FR-008), and
  section 8's probes are what make that bump visible (SC-013).

## 7. The anchors of US3-6 under this design

Ids fictional: plate `doc:0002` with instance `cmp:0001` and hole `hol:0001`; bought pin `doc:0003`
with instances `cmp:0002` and `cmp:0003`; the part-roles question is `ER-001` when asked.

| Anchor | Calls | Columns |
|---|---|---|
| R-2 | `request_evidence(entity_ids=["cmp:0002"])`, no item, recorded `ER-002`; the same call again, `already_asked` | unanswerable 2 (U-1 on `doc:0003`); repeats of open questions 1, of `ER-002`; re-asks 0 |
| R-2, US3-5 | among other calls, one on `drawing.manufacturing_inputs` naming `doc:0003`, answered `closed_by_code` on a package carrying drawing evidence (`tools/drawings.py:73-76`, `tools/session.py:320-331`) | unanswerable 1 |
| R-3 | `interfaces.fit` naming `cmp:0002` and `hol:0001`, recorded `ER-002`; scripted "press fit" sent at point 0; in answer turn 1, `interfaces.fit` naming no ids, recorded `ER-003` by the product (`report/session.py:208`); at point 1 the driver sends "press fit" again for `ER-003`, the one entry it asks within (`scripted-answers.md` 3's re-delivery) | re-asks 1, seen, of `ER-002` |
| R-3, refused | the same, the follow-up naming `hol:0001` alone: the product answers `already_answered` | re-asks 1, refused |
| R-6 | `fasteners` naming `cmp:0001`, recorded, answered "the screws are in a separate assembly", nothing asked after | Q-3 count 1, no miss; re-asks 0 |
| another item | after R-6's answer, `interfaces.fit` naming `cmp:0001` | re-asks 0 |
| R-1 | the part-roles question on the session once | Q-1 count 1, no miss; none on the session, or two, is one miss |

## 8. The oracle's question half and the probes

**The oracle review** (built by the validation contract, SC-001) holds, per question-count rule with
`min` 1, one question of its kind: the part-roles question as `ask_part_roles` records it, or one
recorded call naming the rule's item and ids (the item alone when it names none), made through the
real `request_evidence` tool so its step and stored result are written as a review writes them
(`scoring.md` 9.2; plan decision RF-58); no other request call; and no answer log. Every call is
then readable, so it scores zero re-asks, repeats and unmatched requests, zero unanswerable requests
and question-count misses wherever the key has those entries (`null` where it has none), and not
assessed for unscripted questions and bound-reached, which read an answer log no key grades
(FR-021). Section 5.3's last count-rule refusal keeps that zero reachable.

**The probes** this contract requires of the validation (FR-049, research §8.15), each a case's
null or oracle review plus one behaviour, moving only its columns:

- columns: a seen re-ask; a refused re-ask; a repeat of an open question; an unanswerable request
  recorded, one refused and one closed by code; an unmatched request; a question-count miss of each
  kind, below and above; an unscripted question of each reason; a bound-reached review. An
  answer-log probe adds the log its base lacks, so it also declares the other log column (`null` to
  assessed) and `not_assessed`, whose two log reasons it removes (`scoring.md` 9.3; RF-70);
- matching rules: a hole and a fastener resolved to their instances; a document resolved to its
  instances; ids to documents for an unanswerable entry; the item-only re-ask; the part-roles
  question by identity, and a model question in its words that is not it; a re-ask outranking a
  repeat; a code question that is no earlier question; an error answer that is no question; a call
  before an answer point (a repeat) and the same call after it (a re-ask).

## 9. Tests

Every test fails before its behaviour exists (constitution III). Sessions are built as data unless
a test says it runs the tool.

`reviewer/tests/unit/test_benchmark_questions.py`:
- request calls are read from the steps and their stored results, with each outcome of section 1's
  table, a recorded call carrying its request id and a refused one the cited id (FR-019);
- an error answer is no question: in no column (plan decision QA-10);
- a stored result that is missing, unreadable, another session's or another call's makes the call
  columns not assessed, naming the step and the reason, read through `read_stored_result` (a spy
  shows the reader calls it for every request call; RF-30; FR-021);
- instances: a hole, a fastener and a document resolve as section 2's table; two instances of one pin
  stay two; `documents_named` answers as the drawing guard does (the guard's own tests pass
  unchanged after the rename);
- `covers` is the predicate `covering_requests` uses: the guard's existing tests
  (`tests/unit/test_tools_session.py`, `test_questions.py`) pass unchanged after the extraction, and
  `covers` is tested directly on its four cases (item and ids, item alone, no item and no ids, a
  `null` item with ids); `asks_within` is tested on its two widenings only: a hole and a document
  resolved to instances, and the item-only branch; everything else is `covers`' (RF-6);
- each row of section 7 (US3-6, US3-5);
- R-3 against a key with Q-2: the follow-up is also one question-count miss (section 6, two columns
  by definition);
- a repeat of an unscripted question after an answer turn is a repeat of an open question (FR-020,
  D3);
- a call before an answer point is a repeat and the same call after it a re-ask;
- a re-ask outranks a repeat when both an answered and an open question match;
- a code question is no earlier question: a model question naming a part the answered part-roles
  question named is not a re-ask (plan decision QA-12);
- a call naming no item and no id is unmatched, twice over when asked twice, and never a re-ask
  (US3-7);
- the part-roles identity: true for the question `ask_part_roles` records, false for a model
  question in its words and for the drawing candidate question (plan decision QA-14);
- a key without question entries reads not assessed in its columns, never 0; a session with answered
  requests and no answer log reads not assessed in `re_asks` and `open_repeats` (US3-8, FR-021);
- an answer log that disagrees with the session refuses the package naming the request;
- `unscripted_questions` lists each request once with its first reason; `bound_reached` reads the
  log (FR-024, FR-025);
- a session cut short at its step limit keeps the counts of the calls before the stop (FR-041).

`reviewer/tests/unit/test_stored_result.py` (the one stored-result reader, RF-30):
- `read_stored_result` returns the payload, the status and the file's raw text for a file `_store`
  wrote; `Unstored` with `missing`, `unreadable` (not JSON; not an object; a payload that is not an
  object), `other_session`, and `other_call` (another step; another tool or other arguments when
  given), one test each;
- the replay's classification is unchanged: every call the replay tests classify as `stored` or
  `estimated` at `be01974` reads the same through the extracted reader
  (`tests/unit/test_cli_benchmark_replay.py` and the replay tests pass unchanged);
- a spy sees the replay, the questions reader and (from the report slice) the report call it, and no
  other reader of `tool-results/` exists under `benchmark/`.

`reviewer/tests/unit/test_answer_key.py` (the answer-key contract's file; these rows are this
contract's): each refusal of section 5.3, naming the entry; an entry naming parts on a key-only key
loads unresolved (D7).

`reviewer/tests/unit/test_benchmark_questions_driver.py`: the driver's delivery decisions use
section 3's scripted-answer row and section 4's identity: an entry keyed to the plate's instance
answers a request naming the plate's document and one naming its hole; an item-only request with two
entries on its item is `ambiguous`; a request naming no item and no id is `names_nothing`; the
part-roles question is answered only by the `part_roles` entry.

`reviewer/tests/integration/test_questions_on_real_tools.py`, not marked `integration`: it needs no
native package, and the marker is skipped wherever one is absent (`reviewer/tests/conftest.py:72-82`;
plan decision RF-26). A scripted review that calls the real
`request_evidence` for R-2's two requests and R-3's two, with the driver's answer between them (R-3's
item-only follow-up is recorded, so the driver answers it again at the next point and the script
plays that second answer turn, `scripted-answers.md` 3's re-delivery), and the scorer reading the
run folder: the guard's outcomes are the ones section 7 expects, and the
columns equal section 7's, so the counting is pinned on what the product actually records, not only
on sessions built as data (research §2's lesson, `no-oracle-null-tests`).
