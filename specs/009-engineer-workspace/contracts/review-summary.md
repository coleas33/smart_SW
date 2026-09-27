# Contract: The Review Summary

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), pending implementation:* ten goals, each naming a finding group (Standards split from Hygiene); the summary block keeps the headline, a tally, the questions, the parts not loaded, the drawings and bought-parts lines and a not-reached line, while the goal lines move under their groups; `ReviewRanking` gains `groups`; see 013 `contracts/grouped-list.md`.

Normative for FR-007 to FR-012, SC-001 and SC-002's backend half.

## 1. Where it is computed, and what carries it

`report/summary.review_summary(ranking, session, package, *, usage=None)` is pure: it reads its
arguments and `report/review_words_v1.yaml`, imports no provider and no settings, and writes
nothing. *Amended 2026-09-26 (feature 013 T050):* its first argument is the session's findings by
type (`report/finding_groups.findings_by_type`, 013 `contracts/grouped-list.md` section 3) in place
of the ranking - `review_summary(groups, session, package, *, usage=None)` - whose rows are the
issues and whose fold the passes; `ReviewRanking` carries the same `groups`. Three routes answer a `ReviewRanking` (the `Ranking` of feature 007's
`contracts/attention.md` section 4, minus `session_id`, plus `summary`):

| Route | Session and package | Ledger |
|---|---|---|
| `GET /sessions/{chat_id}/attention` | the live run's | the run's `usage_ledger` |
| `GET /sessions/{chat_id}/snapshot` | the live run's | the run's `usage_ledger` |
| `GET /reviews/{run_id}` | the run folder's `session.json` and `package.json` | none |

`attention.json`, the Model check and Standards bodies, and `report.md` do not carry it.

## 2. The groups

Every finding outside a folded family is in exactly one group, first match winning:

| # | Group | Test |
|---|---|---|
| 1 | `within_scope` | `status == "checked_within_scope"` (as `attention._not_amplified` counts first) |
| 2 | `decided` | `disposition.decision` in `{accepted, rejected}` |
| 3 | `decide` | `policy.needs_judgement_of(check)` |
| 4 | `fix` | `status == "demonstrated"` |
| 5 | `verify` | `status` in `{suspected, unresolved}` |

`groups` lists `decide`, `fix`, `verify` always, in that order, with their labels "Decide", "Fix",
"Verify"; then `decided` and `within_scope` when their count is non-zero. Severity is never read.

*Amended 2026-09-26 (feature 013 T050, its `contracts/grouped-list.md` section 4):* the groups keep
their tests and order, `within_scope`'s label becomes "Checked, no issue" ("{n} checked, no issue"),
and `by_goal` and the `modelling_practice` line are removed - every finding, a folded family's
included, is in exactly one group, and the goal lines live under their finding groups. The one
`tally` line `{text}` reads "Decide {a} · Fix {b} · Verify {c}", then " · Decided {d}" when that
group holds a finding (words: `tally.item` "{label} {n}", joined by `separator`). The rest of this
section, from "Each group's `by_goal`", describes the summary before feature 013.
Each group's `by_goal` lists the goals (section 3) with a non-zero count in that group, in goal
order. A folded family (`session.folded_families`, feature 008) is the `modelling_practice` line,
built from the ranking row whose `family` is set: `{title, findings: len(member_finding_ids), rules:
rule_count, finding_ids}`. The partition holds: the group counts plus the family's findings equal
`len(session.findings)`. *Landed as* (T017): the row is the first with `family` set, in rank
order; a second folded family, which no build writes, is not refused - its findings stay in the
groups as if unfolded, so the partition still holds.

## 3. The goals

The table is `goals` in the words file: `{id, title, items, prefixes}`. Nine goals, in this order: interference, fasteners, hole alignment, fits and stacks, tool access, mass and material, hygiene, drawings, and modelling practice (`items: [modeling.resilience]`, `prefixes: [rms.]`, a goal of its own since 2026-09-23 so modelling findings never fill the hygiene line). A finding's check belongs to
the goal with the longest prefix it starts with; a coverage item matches a goal when its `check` is
one of the goal's `items` or starts with one of its `prefixes`. *Landed as* (T011): one goal per
check, finding and coverage row alike - `summary.goal_of(check, goals)` answers the goal whose
`items` name it, else the goal of its longest prefix - so a `standards.drawing.*` row speaks for
drawings and never also for hygiene (`standards.`). One `GoalLine` per goal, in table order, the
state first match winning:

| # | State | When |
|---|---|---|
| 1 | `issues` | a finding mapped to the goal has a status other than `checked_within_scope` |
| 2 | `not_reached` | a coverage item whose `check` is one of the goal's `items` sits in `unresolved`, `skipped` or `failed`; or no coverage item and no finding matches the goal at all |
| 3 | `checked` | a `checked` coverage item matches, or a `checked_within_scope` finding is mapped to it |
| 4 | `not_applicable` | only `out_of_scope` items match |
| 5 | `not_reached` | otherwise: rule rows only (no `items` row), none checked, at least one `unresolved`, `skipped` or `failed` (*landed as*, T011: the four rows above left this case with no state; the big-assembly fixture's mass-and-material goal is one, an unresolved `standards.part.material_assigned` row beside an out-of-scope one) |

`reason` (for `not_reached` and `not_applicable`): the bucket of the first matching close-out row in
`unresolved, skipped, failed` order mapped through `goal_reasons` (`evidence missing`, `skipped`, `a
check failed`), `out of scope` for `not_applicable`, `no check ran` when nothing matched; for row 5,
the first matching rule row in that order. `detail`: that row's `reason`, verbatim, or `None` - for
`not_applicable`, the first out-of-scope row's `reason`.

*Amended 2026-09-26 (feature 013 T046, its `contracts/grouped-list.md` section 2):* ten goals.
A `standards` goal (`items: [standards.release, coverage.prerun.standards]`, `prefixes:
[standards.]`) is split out of `hygiene`, which keeps `items: [provenance, hygiene]` and
`prefixes: [provenance., hygiene.]`; it sits after `hygiene` in the table. Every goal gains
`group`, the id of the finding group (013 `finding_groups` in the words file) its findings are
listed under - one taxonomy for goals and groups. The words file refuses a goal naming a group it
does not list. `standards.drawing.*` stays drawings and `standards.part.material_assigned` mass and
material, each by its longer prefix. The goals, `goal_of` and the goal lines are computed in
`report/finding_groups.py` (`goal_lines(session, words)`), which the summary imports.

*Note (2026-09-23, feature 010 T108 as amended):* the mass and hygiene families' summary rows,
`mass.material` and `hygiene`, are `items` rows of their goals, so their bucket decides between
rows 2 and 3. Each is `checked` only when its call wrote a `checked` per-check row or recorded a
finding, `skipped` otherwise and `failed` on a refused finding, so a family run that checked
nothing (no standards profile, every part lightweight) reads `not_reached` by row 2 - reason
`skipped`, the row's counts as the detail - never `checked` by row 3.

## 4. The other lines

| Key | Rule |
|---|---|
| `headline` | "{n} findings in {m} issues" from `findings_*` and `issues_*`; "No findings were recorded" at zero. *Amended 2026-09-26 (feature 013 T050):* "{n} findings in {m} issues · {k} checked, no issue" - `n` the findings outside the checked fold, `m` the rows of the type groups (the grouped view's rows, a folded family unfolded), `k` the passes (`headline.checked`, joined by `separator`); each part only when it counts something, so a review of passes only reads "{k} checked, no issue"; "No findings were recorded" at zero. `findings` stays every finding and `issues` is `m` |
| `tally` | *Added 2026-09-26 (feature 013 T050):* section 2's one line |
| `not_reached` | *Added 2026-09-26 (feature 013 T050):* `{titles, text}` - the titles of the goals whose line reads `not_reached`, in goal order, and "Not reached: {titles}" naming them as a sentence does; `None` when every goal was reached. It replaces the top-level goal list on the first screen: the goal lines themselves are under their finding groups (`ReviewRanking.groups`) |
| `questions` | open evidence requests in session order (`questions.md` section 3); `text` `None` at zero. *Amended 2026-09-26 (feature 013 T034):* each item gains `allow_text` (the request's, false when absent) and the list gains `text_placeholder`, the words file's `questions.text_placeholder`, which the page prints in the text box of a question that allows text |
| `not_loaded` | `not_examined(package)`: `{count, total, text}`; `None` when every instance was read or no package |
| `drawings` | *Added 2026-09-23 (owner decision 10A; feature 011 T086, T087).* `drawings_of(package)`: one line naming the drawings the review read and the same-name drawings it found but did not open, `{read, candidates, text}`; `None` when neither exists, or no package. `read`: the file name (`documents[].file_name`, the document id where the package has no row) of every drawing document with a native record (`drawing_records[]`) or a PDF-ingested sheet (`drawings[]`), once each, in document-id order - a drawing root's own drawing included. `candidates`: the file name of every `drawing_candidates[]` path, in its reviewed document's id order, once per file (a part and an assembly of one stem share one), and never a file the review read: a candidate the engineer confirmed and the product opened and read (feature 011 `contracts/confirmed-open.md`) is read, not a candidate, whether or not the package still holds its candidate row (paths compared ignoring case and the separator). `text`: "Drawing read: {names}" or "Drawings read: {names}", then ". ", then "Same-name drawing found but not open: {names}" or "Same-name drawings found but not open: {names}", each part only when its list is non-empty; `{names}` joins the file names with commas and a final "and", and past ten names the first ten with commas and "and {n} more" (the candidate question's bound). The words are `drawings` in the words file. Counted in no group, goal or headline |
| `bought_parts` | *Added 2026-09-26 (feature 013 T034, its `contracts/part-roles.md` section 7):* `bought_parts_of(session, package)`: `{count, names, maybe_count, maybe_names, text}` read from the persisted `coverage.prerun.bought_parts` and `coverage.prerun.maybe_bought` rows (from any bucket; the last row of each check, since a regrade restates it) and never classified again - `names` and `maybe_names` the file names of each row's `scope.document_ids` (the id where the package has no row, or there is no package), `text` the rows' sentences joined by ". "; `None` when neither row exists. `report.md` renders the rows' sentences once, under the words file's `bought_parts.heading`, after the Summary. Counted in no group, goal or headline |
| `contacts` | `contacts_of(session, names)`: feature 010's `ReviewSession.contacts` in its order, each part named from the summary's `component_names` (its id in `text` and `None` in `names` where it has none), `kind_label` from `labels.contact_kind`, ids `C-001` as 010 allocates them; `None` when absent or empty. Counted in no group, goal or headline |
| `component_names` | non-blank names of every package component |
| `resume_input_tokens`, `resume_text` | `questions.md` section 5 |

## 5. What the page does with it

*Amended 2026-09-26 (feature 013 T050; the page's half is 013 T054):* the summary block prints the
headline, the tally line, the questions, the parts not loaded, the drawings line, the bought-parts
line and the not-reached line, each verbatim; no group line carries goal counts and no goal line is
printed here - they are under their groups in `<section id="findings-by-type">` (013
`contracts/grouped-list.md` section 5) - and the modelling-practice group below is retired with its
line. The text that follows describes the page before feature 013.

`render.summaryBlock(summary)` builds `<section id="summary">` at the top of Results: the headline;
one line per group (`label` in the lead face, `text`, then each `by_goal` as "title count"); the
questions `text`; the `not_loaded` `text`; the `drawings` `text`, verbatim, when `drawings` is not
`None` (*added 2026-09-23, decision 10A*); one line per goal (`title`, `state_label`, `reason`) with
`detail` behind a shut `<details>`. *Amended 2026-09-23 (the owner's decision 10A; the page's half,
009 T086 and T087)*: the one line about drawings is printed verbatim from `drawings.text`, in the
second tier of ink (`--ink-2`), and nothing is printed when `drawings` is null or its `text` is
empty; the field itself is section 4's, the backend's. Class names interpolate `kind` and `state` (`group-decide`,
`goal-not_reached`) and the stylesheet colours them from `tokens.css`: decide `--judge`, fix
`--critical`, verify `--warn`, issues `--critical`, checked `--good`, not reached `--warn`, not
applicable `--quiet`. The page prints and never counts, groups or orders: every number and word is
the summary's.

The modelling-practice group: once the ranking arrives, the finding cards whose ids are in
`modelling_practice.finding_ids` move, in arrival order, into one shut `<details
class="finding-group">` whose summary is `modelling_practice.title`, placed where the first of them
was. A Start-here row or a "Show all" line that names a member opens the group before scrolling.

The contacts fold: `<details class="contacts">` after the findings, its summary `contacts.text`, one
line per item (`text`, then `kind_label` and `configuration`), component ids and the volume in each
line's own fold. Never among the findings; never in Start here.

Names: the Review tab's Start-here meta, the question panel's "about" line and the contacts list
print `component_names[id]` where present and the id where not; the id itself is in a fold.

## 6. An older backend, and no findings

*Amended 2026-09-26 (feature 013 T050):* a summary with zero findings shows "No findings were
recorded", the tally at zero and the not-reached line naming every goal; every route builds its
ranking with `groups`, so the page keeps no branch for a ranking without it.

A ranking with no `summary` renders exactly as before this feature: no summary block, no empty
section, the Start-here panel where it was. A summary with no `drawings` key (a backend before
decision 10A), or with `drawings: null`, has no drawings line and renders every other line as
before it. A summary with zero findings shows the headline "No
findings were recorded", the three groups at zero, and every goal line.

## 7. SC-001

*Amended 2026-09-26 (feature 013 T050):* the headline, the tally line and the not-reached line are
inside the viewport, in place of the three groups and every not-reached goal line.

On the big-assembly pane fixture in a 300 by 600 pane, the summary's headline, its three groups and
every goal line whose state is `not_reached` are inside the viewport with Results scrolled to the
top.
