# Contract: The Attention Policy

Normative for `report/attention.py`, the "Start here" section, `attention.json`, the
`attention` key on the two check result bodies and `GET /sessions/{chat_id}/attention`.

## 1. The rule

A ranking is a total order over a finished session's findings. Two findings compare by the
first key on which they differ; every key is one named lookup; there are no weights.

| # | Key | Order | Read from |
|---|-----|-------|-----------|
| 1 | suppressed | undecided first; `checked_within_scope`, or a disposition of `accepted` or `rejected`, last | `status`, `disposition.decision` |
| 2 | needs judgement | a check whose id starts with `interference.`, `fit.`, `fastener.` or `hole.` first | the policy file's `needs_judgement` |
| 3 | consequence class | `rebuild_breaker` > `interface` > `manufacturing` > `unclassified` > `discipline` > `hygiene` | the policy file's `classes`; an id the table does not name is `unclassified` and is printed by name |
| 4 | status | demonstrated > suspected > unresolved > checked_within_scope | `status` |
| 5 | severity | high > medium > low > info | `severity`, verbatim |
| 6 | reach | more distinct components first, capped at three | `component_ids` |
| 7 | carried over | a finding carried from a previous session after an otherwise equal fresh one | `carried_over_from` |
| 8 | check id | ascending | `check` |
| 9 | finding id | ascending | `id` |

Points the rule exists to enforce:

- **A deferred disposition and a re-review waiver keep competing.** Neither has been decided.
  `exception_id` is not read: it is set for a re-review waiver too, and the finding alone cannot
  tell the two apart (research R2.1).
- **`checked_within_scope` is one bucket.** A waived rule finding and a clean numeric pass both
  carry it and both sort last; the not-amplified line counts them together as "checked within
  scope".
- **Severity is read, never recomputed.** The rule families' high-severity override and the
  interference family's volume threshold stay where they are.
- **The rank is arguable by pointing at a line.** Every row records its nine key values and a
  one-sentence reason naming the key that placed it.

## 2. Folding

Before ranking, findings that share `check`, `status` and `severity`, whose `component_ids`
are pairwise disjoint, and whose check is not in the needs-judgement set, fold into one row.
The survivor is the lowest finding id; the row lists every member id and the union of their
component ids. A single finding is a row of one. Two findings sharing any subject never fold.
Two needs-judgement findings never fold: two press fits may be two intents.

Folding writes nothing: `session.findings`, `Finding.group` and the Findings section are
byte-identical before and after. The fold is recorded in the ranking and in `attention.json`.

## 3. The "Start here" section

Rendered by `render_report(session, package=None, *, ranking=None)` only when a ranking is
supplied, immediately above `## Findings`:

```markdown
## Start here

1. **F-007** `interference.static` - needs your judgement (interference of 0.8 mm³ between …)
2. **F-008** `interference.static` - needs your judgement (…)
3. **F-003** `rms.assembly.mates_to_reference_geometry` - rebuild breaker, demonstrated, 2 components
4. **F-002** `rms.sketches.fully_defined` - rebuild breaker, demonstrated
5. **F-004** `rms.grouping.all_features_in_a_group` - discipline, demonstrated

Not amplified: 3 findings (0 checked within scope, 0 already decided, 0 informational, 3 beyond the top five).

What this run could not reach: 39 unresolved, 11 skipped, 0 failed, 7 out of scope.
- fasteners: list_fasteners returned zero instances, so no screw or bolt joint could be checked.
- holes.alignment: only cmp:0003 holes were extracted; the two lightweight pin components have none.
- interfaces.fit: pin geometry was not extracted, so the 3.0 mm dowel fit could not be computed.
- interfaces.stack: no drawing dimensions, target gap or stack contributors were extracted.
- drawing.manufacturing_inputs: no drawing documents or sheets were included.
- 3 evidence requests are still open; 23 RMS rules unresolved and 11 skipped.

Ranked by attention_policy_v1; the rule is in reviewer/src/swreview/report/attention.py.
```

Points the section exists to enforce:

- **Amplify, never filter.** Every finding still renders in full below, in its severity
  section, in recording order. A folded row's members are all still there.
- **The coverage block is the run's own close-out.** Its lines are the unresolved coverage
  items whose check is a checklist item id - the rows `finalize` writes for the items the
  run did not close - each with the reason the run recorded, at most five, then the count of
  open evidence requests, then the rule counts. Nothing is recomputed or reworded; a check
  folder, which has no checklist rows, prints the bucket counts and the rule counts only.
- **The empty case is words.** A session with no findings prints "Nothing to start with: no
  findings were recorded." and still prints the coverage line; a session whose findings are all
  informational or already decided prints "Nothing to start with: every finding is
  informational or already decided." and the not-amplified line counts them.
- **No percent sign anywhere in the section.** The Standards page's body scan forbids one.
- **The standards report keeps its verdict header first.** "Start here" is the section above
  Findings, on every surface; nothing "opens with" it.
- **Rendering with no ranking is byte-identical to today**, proven by the one golden of this
  renderer; a second golden pins the ranked shape.

## 4. `attention.json`

Written beside `session.json` from the same `Ranking` the report was rendered from, by
`ReviewRun.finalize` (including the failure path), by the RMS check's `write_report`, by the
standards check's `_write_report`, and by `rerender_run_folder` for the offline commands.

```jsonc
{
  "policy_version": "attention_policy_v1",
  "session_id": "6f1c…",
  "rows": [
    {
      "finding_id": "F-007",
      "member_finding_ids": ["F-007"],
      "check": "interference.static",
      "title": "…",
      "status": "demonstrated",
      "severity": "medium",
      "component_ids": ["cmp:0002", "cmp:0003"],
      "consequence_class": "interface",
      "key": {"suppressed": 0, "judgement": 0, "consequence": 1, "status": 0, "severity": 1, "reach": 1, "carried": 0, "check": "interference.static", "finding_id": "F-007"},
      "reason": "needs your judgement"
    }
  ],
  "top_n": 5,
  "not_amplified": {"total": 3, "checked_within_scope": 0, "dispositioned": 0, "info": 0, "beyond_top_n": 3},
  "coverage": {
    "checked": 5, "skipped": 11, "unresolved": 39, "failed": 0, "out_of_scope": 7,
    "not_closed": [{"item": "fasteners", "reason": "list_fasteners returned zero instances, so no screw or bolt joint could be checked."}, {"item": "holes.alignment", "reason": "…"}],
    "open_evidence_requests": 3,
    "rules": {"unresolved": 23, "skipped": 11}
  },
  "empty_reason": null
}
```

Points the record exists to enforce:

- **Reproducible from the session alone.** `rank(load_session(...), policy)` reproduces the
  record exactly; a record whose `session_id` is not the session beside it is stale, the same
  rule `check.json` already follows.
- **Not a session file.** It is not in `SESSION_FILES`; a folder holding only `attention.json`
  is not "a folder that already holds a review". When a review claims an RMS check folder, the
  record is rotated to `attention.1.json` beside `session.1.json`.
- **Never written by a read.** `GET /checks/{check_id}` and `GET /sessions/{chat_id}/attention`
  recompute in memory.

## 5. The `attention` key on the check bodies, and the review route

Both `CheckResult` and `StandardsResult` gain one top-level key, `attention`, whose value is
the `Ranking` JSON above minus `session_id` (the body already names the session). The two
blocks are identical, which is why no difference row is added to feature 006's table. The
key is present on the POST, on the `GET /checks/{check_id}` re-read (recomputed, byte-equal to
the POST's), and after an Accept.

`GET /sessions/{chat_id}/attention` answers the same shape for a review the pane started,
computed from the live session on each call: `200 Ranking`; `404 UnknownChat`; for a run that
has produced no findings, `200` with `rows: []` and `empty_reason` set. It never writes. It is
authenticated like every other session route and joins the door test's route census.

## 6. What the pages may do with it

### Review finding explanations (U5, 2026-09-20)

The Review pane enables `start_review(explain_findings=True)`. After a successful
engineering turn, the runner may make one isolated, tool-free presentation request for
the amplified rows (at most five). It receives only the member findings' evidence and
component names, with a 16,000-byte UTF-8 prompt cap; it uses low effort and a 2,048-token
output ceiling. Each returned explanation is at most 480 characters. Unknown/duplicate
finding IDs, malformed JSON, or oversized output are rejected. No new evidence, ranking,
severity, or status is produced by this request.

`ReviewSession` optionally persists `explanations_enabled`, `finding_explanations`
(representative finding ID to plain text), and `finding_explanation_fingerprint`.
An unchanged evidence fingerprint reuses the batch, including across ordinary follow-ups;
failure or Stop never starts a presentation request. Cancellation is checked before and
during streaming. The request's reported usage belongs to the engineering turn and its
elapsed time is included in session timing. Missing or invalid model text uses an explicit
"No model explanation was generated" fallback rather than an invented paraphrase.

`AttentionRow.explanation` is optional. Ranking keys and row order are unchanged. The
Review pane renders the same persisted text under Start here and as the first line inside
the fold of the corresponding finding cards (including members of a folded row; since U10,
2026-09-22, a finding card's head is its line and title only); the Markdown report renders it as
escaped plain text on both surfaces. Offline re-rendering and deterministic Model check /
Standards runs make no presentation calls. Omitted optional fields preserve older session
and attention-record shapes. Model-authored text is distinct from deterministic labels;
the no-percent-label rule above still applies to the deterministic attention wording.

- **Pages may show all rows, in the supplied order, behind a control** (amended 2026-09-22,
  feature 009 increment 3, U12). `rows[0..top_n)` is what goes under "Start here", on every
  surface; the rows after it may be shown too, but only after them, only in the order the
  ranking supplied, and only behind a control the engineer opens. A page never reorders,
  filters or re-ranks the rows, and `TOP_N` stays 5. Any count a page prints is the backend's
  number and names its unit: `rows.length` counts issues (a row can fold several findings) and
  `not_amplified.*` counts findings.
- The two check pages render `result.attention.rows[0..top_n)` in the order supplied, each as
  its reason line, into `<section id="attention">` above the bucket chips (above the sixteen-
  check roster on the Standards tab), through `web/shared/check-page.js`, the shared row
  renderer `web/shared/attention.js` and `dom.js` only. They do not show the rows beyond
  `top_n` yet.
- The Review page fetches the route in `endSession`, drops the response if `state.chatId` has
  moved on, renders through `render.attentionPanel(ranking)` into `<section
  id="attention-panel">` above the transcript, shows `empty_reason` in words when there are no
  rows, and clears the panel in `resetTranscript`. Under the heading it prints one count line,
  `Start here: <shown> of <rows.length> issues · <not_amplified.beyond_top_n> findings not in
  Start here`, then the `top_n` rows as the check pages render them (the same
  `web/shared/attention.js` row), then - when there are more - every remaining row, one line
  each, behind a shut `Show all <rows.length> issues (<findings> findings)` control, where
  `<findings>` is the sum of the rows' `member_finding_ids`. Clicking any row scrolls to that
  finding's card.
- No page script sorts, compares severities, or contains a band rule; a test scans every page
  script, comments stripped, for `.sort(`, `localeCompare`, a severity literal list, or a
  numeric comparison on `severity`/`status`, with an allowlist of the existing bucket display
  orders.
