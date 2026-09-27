# Contract: Code-Owned Items, Provenance, and the Re-Ask Guard

Normative for FR-024 to FR-032 and the mechanism FR-039 and FR-045 use. Research R2.20 to R2.23,
R2.40, R3 C9, C14. Amends feature 001's `contracts/agent-tools.md` (the `request_evidence` and
`mark_coverage` rows), feature 008's `contracts/checks-first.md` (provenance at setup), feature 009's
`contracts/questions.md` section 1 (rows after the four refusals) and feature 011's
`contracts/questions.md` section 4 (the drawing check's duplicate test is the shared exact test of
`checks/questions.py`).

## 1. Code-owned checklist items and `closed_by_code`

`ChecklistItem` (`agent/checklist.py`) gains `owner: Literal["model", "code"] = "model"`. Two items
are code-owned: `provenance` (section 2) and `coverage.closeout` (`tokens.md` section 1). The
drawing item `drawing.manufacturing_inputs` is closed by code only in the state
`drawing-capability.md` section 5 defines, through the same answer.

`Checklist.render()` prints, for a code-owned item, "Closed by code before your first turn; never ask
about it or mark it." in place of the `mark_coverage` line. The checklist version stays 1 (features
008 and 010 added items at version 1; the version is in the carry-over key, so a bump would drop every
carried finding once).

`mark_coverage(check=<code-owned item>)` and `request_evidence(blocks=<code-owned item>)` answer,
with no error:

```json
{"status": "closed_by_code", "check": "provenance", "reason": "<the reason code recorded>"}
```

and record nothing: no coverage row, no failed row (any `error` payload becomes failed coverage,
`tools/registry.py:366-377`), no event, no request id.

## 2. Provenance closed at setup

```python
# reviewer/src/swreview/checks/provenance.py
def close_provenance(package: EvidencePackage) -> ProvenanceOutcome: ...
```

Pure. With no manifest discrepancy (always, on the native path; only `ingest/manifest.py` writes
them): one coverage row, check `provenance`, bucket `checked`, scope every part and assembly document
and the root's configuration, reason:

> Reviewed as open in SOLIDWORKS: {n} documents, each at its own path in its active configuration;
> revision read on {k} of {n}. The open files are taken as the latest: vault version and local
> modification are not read and never asked. A missing revision is reported by the hygiene checks.

With discrepancies: one finding per discrepancy, check `provenance.<kind>`, status demonstrated,
severity in `DISCREPANCY_SEVERITY` order; the prefix closes the item. It never writes a question.

`record_provenance(context, package)` runs in `start_review` right after `record_partial_evidence`
(`agent/runner.py:1241`), the lever-independent setup write, through `context.record_coverage` and
`record_result`, so the pane receives the events: the command line and the pane, checks first on or
off, and Retry, exactly once.

The checklist item's description becomes: "Closed by code from the package before your first turn:
each reviewed document's path, configuration and revision. The open files are reviewed as the latest;
never ask for a vault version or whether a file is modified locally. A missing revision on a custom
part is a hygiene finding."

`package_brief._document_line` (`agent/package_brief.py:69-85`) prints `vault_version=` and
`local_modified=` only when the manifest has a value. System prompt step 1 gains: "The manifest's
vault-version and local-modification gaps are answered by the provenance item, which code has
closed."

## 3. The re-ask guard

```python
# reviewer/src/swreview/report/session.py
def covering_requests(session: ReviewSession, blocks: str | None,
                      entity_ids: Sequence[str]) -> CoveringRequests: ...
```

The guard answers the model's questions. An earlier **model-written** request R (`source` `model`)
**covers** a new question when `R.blocks == blocks` (null equals null) and either `set(entity_ids)`
is non-empty and a subset of `set(R.entity_ids)`, or both are empty and `blocks` is not null. Ids are
compared raw: a component instance is never turned into its document (that would merge two instances
of one screw).

Two exclusions (revised on review, 2026-09-26; default taken 2026-09-26, the owner may revise,
research R2.22):

- **A question with no checklist item and no ids is never covered**: without an item or a part,
  nothing says two questions are the same one (a question about load after an answered one about
  temperature is new).
- **A code-written request covers only itself**: it never covers a model question, because the
  part-roles question has no checklist item and names the unclear parts, and would otherwise answer
  any later model question about one of those parts "All bought"; the drawing check's candidate and
  governing questions likewise. A code question is recorded unless an identical one is already on
  the session - today's exact test (`_already_asked`, `tools/drawings.py:68-74`), moved to
  `checks/questions.already_asked` (T005) and shared by the drawing check and the part-roles
  question - because a code question can trigger an action (`_is_confirmed_candidate`).

`request_evidence`, in this order (the first four unchanged):

| # | Check | Answer |
|---|---|---|
| 1 | every entity id known (`entity_kind`, section 4) | error, as today |
| 2-4 | the short form | error, as today |
| 5 | `blocks` is a code-owned item | `closed_by_code` (section 1) |
| 6 | `blocks == "drawing.manufacturing_inputs"` and a named document has no attached drawing | `closed_by_code` with drawing states (`drawing-capability.md` section 5) |
| 7 | covered by an **answered** model-written request | `already_answered` (below); the most recent answered wins |
| 8 | covered by an **open** model-written request | `already_asked` (below) |
| 9 | otherwise | recorded, as today, `{"status": "open", "evidence_request": …, "open_items": […]}` |

```json
{"status": "already_answered",
 "evidence_request": {"id": "ER-002", "question": "…", "answer": "latest version",
                      "answered_at": "…", "blocks": "provenance", "entity_ids": ["doc:0001"]},
 "note": "ER-002 answered this. Use that answer and record the check with it; if it is not enough, mark the check unresolved quoting it. To ask something different, name the specific hole, fastener or face."}
```

`already_asked` has the same shape with the open request and the note "ER-003 already asks this;
wait for the engineer's answer." Nothing is recorded for either: no id, no event, no failed row
(the 008 re-call guard's `already_run` precedent, `prerun.py:1297-1305`). The tool's docstring does
not change; the model meets the rule as a status.

`_already_asked` (`tools/drawings.py:68-74`) keeps its exact match, moved to `checks/questions.py`
(above); `covering_requests` and its subset rule are for model questions only.
`_is_confirmed_candidate` stays exact, being the trigger for an action.

**At finalization**, a checklist item still open whose blocking request (`blocks == item.id`) is
answered is written unresolved with the reason "{title}: still open after {ER id} was answered:
'{answer}'" instead of the generic "ended without a finding or a coverage entry".

System prompt step 6 gains: "An answered request is final: never ask it again in other words; record
the check with the answer as given."

The answer messages (`agent/runner.py:209-224`) stay byte-identical: replays rebuild them.

## 4. The ids `request_evidence` accepts

`ToolContext.entity_kind` (`tools/context.py:387-412`) gains, after today's kinds:

| Kind | Ids | From |
|---|---|---|
| `joint` | `jnt:` | the session's joint map (`check_joints`' record) |
| `feature` | `feat:` | `package.features` |
| `drawing_sheet`, `drawing_view`, `drawing_dimension`, `drawing_annotation`, `drawing_note` | `dsh:`, `dvw:`, `ddm:`, `dan:`, `dnt:` | the package's drawing records |

An id of a known prefix that names nothing is still refused. `mark_coverage`'s scope check is
unchanged (components and documents only).

## 5. Tests

`test_provenance_closure.py`: a native package gives one checked row, no finding, no question, the
counts in the reason; an ingest package with each discrepancy kind gives one finding each, in
severity order; the lever matrix (checks first on and off, the gate on and off, the command line,
Retry) writes the row exactly once; a document with no manifest entry; a custom part missing its
revision gives a hygiene finding while provenance stays checked. `test_checklist.py`: the code-owned
render line; the provenance description pinned; every model-owned item still renders the
`mark_coverage` line. `test_tools_session.py`: `mark_coverage(provenance)` and
`request_evidence(blocks="provenance")` answer `closed_by_code`, add no row, no failed row, no event,
and allocate no id (the next real request is still ER-001); covered by an answered request; by an open
one; partial overlap allowed; a superset allowed; different blocks allowed; null blocks; the empty
set; two questions with no checklist item and no ids both recorded; the part-roles question answered,
then a model question with no checklist item naming one of its parts recorded (a code request covers
only itself); a model question with no checklist item naming a subset of an answered model
question's parts, also with no item, answered `already_answered` (pinned, research R2.22); the drawing
check's duplicate test still exact; the most recent answer wins; payload shapes; `jnt:`, `feat:` and drawing ids accepted after the
tools that hand them out, an unknown `jnt:` refused. A regression test replays the sitting's eight
question calls with fictional ids: ER-006, ER-007 and ER-008 come back `already_answered` citing
ER-002, ER-003 and ER-005. `test_package_brief.py`: null fields omitted, supplied fields printed. The
opening-message pin and the golden fixtures regenerated; `test_docstring_split.py` and
`test_tool_payload.py` pass unedited.
