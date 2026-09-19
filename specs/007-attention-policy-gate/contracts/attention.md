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

What this run could not reach: 39 unresolved, 11 skipped, 0 failed, 7 out of scope; most in fastener (12), hole (9), fit (8), rms (6), standards (4).

Ranked by attention_policy_v1; the rule is in reviewer/src/swreview/report/attention.py.
```

Points the section exists to enforce:

- **Amplify, never filter.** Every finding still renders in full below, in its severity
  section, in recording order. A folded row's members are all still there.
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
  "coverage": {"checked": 5, "skipped": 11, "unresolved": 39, "failed": 0, "out_of_scope": 7, "families": [["fastener", 12], ["hole", 9], ["fit", 8], ["rms", 6], ["standards", 4]]},
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

- The two check pages render `result.attention.rows[0..top_n)` in the order supplied, each as
  its reason line, into `<section id="attention">` above the bucket chips (above the sixteen-
  check roster on the Standards tab), through `web/shared/check-page.js` and `dom.js` only.
- The Review page fetches the route in `endSession`, drops the response if `state.chatId` has
  moved on, renders through `render.attentionPanel(ranking)` into `<section
  id="attention-panel">` above the transcript, shows `empty_reason` in words when there are no
  rows, and clears the panel in `resetTranscript`.
- No page script sorts, compares severities, or contains a band rule; a test scans every page
  script, comments stripped, for `.sort(`, `localeCompare`, a severity literal list, or a
  numeric comparison on `severity`/`status`, with an allowlist of the existing bucket display
  orders.
