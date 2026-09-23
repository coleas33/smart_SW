# Contract: The Review Summary

Normative for FR-007 to FR-012, SC-001 and SC-002's backend half.

## 1. Where it is computed, and what carries it

`report/summary.review_summary(ranking, session, package, *, usage=None)` is pure: it reads its
arguments and `report/review_words_v1.yaml`, imports no provider and no settings, and writes
nothing. Three routes answer a `ReviewRanking` (the `Ranking` of feature 007's
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
Each group's `by_goal` lists the goals (section 3) with a non-zero count in that group, in goal
order. A folded family (`session.folded_families`, feature 008) is the `modelling_practice` line,
built from the ranking row whose `family` is set: `{title, findings: len(member_finding_ids), rules:
rule_count, finding_ids}`. The partition holds: the group counts plus the family's findings equal
`len(session.findings)`.

## 3. The goals

The table is `goals` in the words file: `{id, title, items, prefixes}`. A finding's check belongs to
the goal with the longest prefix it starts with; a coverage item matches a goal when its `check` is
one of the goal's `items` or starts with one of its `prefixes`. One `GoalLine` per goal, in table
order, the state first match winning:

| # | State | When |
|---|---|---|
| 1 | `issues` | a finding mapped to the goal has a status other than `checked_within_scope` |
| 2 | `not_reached` | a coverage item whose `check` is one of the goal's `items` sits in `unresolved`, `skipped` or `failed`; or no coverage item and no finding matches the goal at all |
| 3 | `checked` | a `checked` coverage item matches, or a `checked_within_scope` finding is mapped to it |
| 4 | `not_applicable` | only `out_of_scope` items match |

`reason` (for `not_reached` and `not_applicable`): the bucket of the first matching close-out row in
`unresolved, skipped, failed` order mapped through `goal_reasons` (`evidence missing`, `skipped`, `a
check failed`), `out of scope` for `not_applicable`, `no check ran` when nothing matched. `detail`:
that row's `reason`, verbatim, or `None`.

## 4. The other lines

| Key | Rule |
|---|---|
| `headline` | "{n} findings in {m} issues" from `findings_*` and `issues_*`; "No findings were recorded" at zero |
| `questions` | open evidence requests in session order (`questions.md` section 3); `text` `None` at zero |
| `not_loaded` | `not_examined(package)`: `{count, total, text}`; `None` when every instance was read or no package |
| `contacts` | `contacts_of(session)`: feature 010's `ReviewSession.contacts` in its order; `None` when absent or empty |
| `component_names` | non-blank names of every package component |
| `resume_input_tokens`, `resume_text` | `questions.md` section 5 |

## 5. What the page does with it

`render.summaryBlock(summary)` builds `<section id="summary">` at the top of Results: the headline;
one line per group (`label` in the lead face, `text`, then each `by_goal` as "title count"); the
questions `text`; the `not_loaded` `text`; one line per goal (`title`, `state_label`, `reason`) with
`detail` behind a shut `<details>`. Class names interpolate `kind` and `state` (`group-decide`,
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

A ranking with no `summary` renders exactly as before this feature: no summary block, no empty
section, the Start-here panel where it was. A summary with zero findings shows the headline "No
findings were recorded", the three groups at zero, and every goal line.

## 7. SC-001

On the big-assembly pane fixture in a 300 by 600 pane, the summary's headline, its three groups and
every goal line whose state is `not_reached` are inside the viewport with Results scrolled to the
top.
