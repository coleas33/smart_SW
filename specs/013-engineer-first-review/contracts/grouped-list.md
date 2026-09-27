# Contract: The Grouped List, Findings by Type

Normative for FR-015 to FR-023 and User Story 2. Research R2.12 to R2.19, R3 C7, C8. Amends feature
007's `contracts/attention.md` sections 3, 4 and 6 (and spec FR-013, FR-023, FR-031, SC-009's parity
wording) and feature 009's `contracts/review-summary.md` sections 2 to 7, `contracts/views.md`
sections 2, 5, 6 and 7, and `contracts/plain-words.md` sections 2 and 7.

## 1. No surface amplifies a pass

`rank()` (`report/attention.py`) sets

```
top_n = min(TOP_N, number of rows whose key.suppressed == 0)
```

`TOP_N` stays 5 and `top_n` keeps its meaning, "how many rows the section amplifies". The amplified
set is the members of `rows[:top_n]`; `not_amplified` counts every other finding, passes as checked
within scope. Every slice of `rows[0:top_n]` - the check tabs through `web/shared/attention.js`, the
gate brief (`prerun.py:641`), `swreview attention` (`cli.py:943`), the explanation pass
(`agent/runner.py:940`) - therefore carries no pass, with no page change. The fold, row and sort
steps of `rank()` (`report/attention.py:450-457`) move into a public
`ranked_rows(findings, policy, families)`; `rank()` calls it, so `attention.json` is byte-identical
except where `top_n` changes.

## 2. The groups and their words

`report/review_words_v1.yaml` gains, before `labels` (whose `errors` block stays last):

```yaml
finding_groups:
  - {id: interference_fit,   title: "Interference and fit", open: true}
  - {id: fasteners,          title: "Fasteners",            open: true}
  - {id: drawings,           title: "Drawings",             open: true}
  - {id: standards,          title: "Standards",            open: true}
  - {id: modelling_practice, title: "Modelling practice",   open: false}
  - {id: hygiene,            title: "Hygiene",              open: true}
  - {id: mass_material,      title: "Mass and material",    open: true}
finding_group_other: {id: other, title: "Other checks", open: true}
finding_group_checked: {title: "Checked, no issue", open: false,
                        exception_tail: "within an accepted exception"}
finding_group_text:
  one: "1 finding"
  many: "{n} findings"
  decided: " · {d} decided"
  fold_tail: "×{n}"
  reach_one: "reaches 1 component"
  reach_many: "reaches {n} components"
```

Each goal gains `group:`; a new `standards` goal is split out of `hygiene`; ten goals:

| Goal | Items | Prefixes | Group |
|---|---|---|---|
| interference | `interference`, `coverage.prerun.interference` | `interference.` | interference_fit |
| fasteners | `fasteners` | `fastener.` | fasteners |
| hole_alignment | `holes.alignment` | `hole.`, `joint.` | interference_fit |
| fits_and_stacks | `interfaces.fit`, `interfaces.stack` | `fit.`, `stack.` | interference_fit |
| tool_access | - | `fastener.head_clearance`, `fastener.head_fit` | fasteners |
| mass_and_material | `mass.material` | `mass.`, `standards.part.material_assigned` | mass_material |
| hygiene | `provenance`, `hygiene` | `provenance.`, `hygiene.` | hygiene |
| standards | `standards.release`, `coverage.prerun.standards` | `standards.` | standards |
| drawings | `drawing.manufacturing_inputs` | `drawing.`, `drawing_profile.`, `standards.drawing.`, `rms.drawing.` | drawings |
| modelling_practice | `modeling.resilience` | `rms.` | modelling_practice |

A finding's group is the group of `summary.goal_of(check, goals)` (the goal whose items name it, else
the longest prefix). A check no goal names goes to `other`. Folding Mass and material into Hygiene is
one edit: that goal's `group: hygiene`; the `mass_material` group then has no goal and no row, and
is left out (section 3), so six groups render.

## 3. The view

```python
# reviewer/src/swreview/report/finding_groups.py
def findings_by_type(session: ReviewSession, package: EvidencePackage | None,
                     words: Words, policy: AttentionPolicy) -> FindingsByType: ...
```

Pure. Rows come from `ranked_rows(session.findings, policy, families=())`: the modelling-practice
family is unfolded (the group is the fold now); the same-check fold of disjoint subjects is kept, shown
by its `tail_text` ("×N"). Rows carry display titles (`with_display_titles`) and their `source` (`sources.md`); persisted
explanations attach by `finding_id`.

One pass over the ranked rows places each row in its survivor's group, so every group keeps the
policy's order. Then, within each group, accepted and rejected rows move to the end, keeping their
order. A row whose status is `checked_within_scope` goes to `checked`, never to a type group; a row
with an `exception_id` in `checked` carries the exception tail.

```
FindingsByType {version: 1, groups: [TypeGroup] (in the fixed order, every group that has a row or
               a goal: the seven while each has a goal; `other` last only when it holds a row),
               checked: CheckedFold | None}
TypeGroup {id, title, open, findings: int, decided: int, text: str,
           rows: [GroupRow], goals: [GoalLine]}
GroupRow = AttentionRow + {source, tail_text: str | None, reach_text: str | None,
                           hide_card_title: bool, chip: str | None}
CheckedFold {title, open, findings: int, text, rows: [GroupRow]}
```

`text` is `finding_group_text` ("{n} findings", plus " · {d} decided" when any are decided). A group
with no row shows its goals' state instead: its `text` is the first goal line's state label and
reason in 009's precedence (not reached, then checked, then not applicable). `goals` are the
`GoalLine`s of the goals mapped to the group, in goal order. A group with neither a row nor a goal
is left out, so folding a goal into another group (section 2) needs no second edit.

Each row's words are the backend's, so the page counts and compares nothing (FR-022; added on
review, 2026-09-26, where the page had counted them):

| Field | Value |
|---|---|
| `tail_text` | `fold_tail` ("×3") when the row folds more than one member, else null |
| `reach_text` | `reach_one` or `reach_many` ("reaches 2 components") when the row names components, else null |
| `hide_card_title` | true for a single-member row, whose card would repeat the row's title |
| `chip` | `labels.source`'s word for the row's source when it is `model` ("AI guidance"), null for `code` (lands with User Story 5, `sources.md` section 2) |

**Partition** (asserted): every finding is a member of exactly one row of one group or of `checked`,
and the union is `session.findings`.

`ReviewRanking` (`report/summary.py:359-372`) gains `groups: FindingsByType`. `attention.json` and
the two check bodies do not carry it. The disk route recomputes it from `session.json`, so there is no
compatibility branch in the page for a ranking without it (009 FR-030 amended for this field).

## 4. The summary block

`review_summary` keeps: the headline, now "{n} findings in {m} issues · {k} checked, no issue"
(passes counted as checked, not as issues; "No findings were recorded" at zero); one tally line
"Decide {a} · Fix {b} · Verify {c}" plus " · Decided {d}" when any; the questions line; the parts not
loaded; the drawings line; the bought-parts line (`part-roles.md` section 7); and one line
`not_reached: {titles, text}` - "Not reached: {goal titles}" in goal order, `None` when every goal was
reached - so the first screen still names the coverage gaps. Removed: `SummaryGroup.by_goal`,
`modelling_practice` and the top-level goal list (the goal lines live in the groups). The groups'
`within_scope` label becomes "Checked, no issue". Decide, Fix and Verify stay: the kind of action is
independent of the type.

## 5. The pane

`render.typeGroups(byType, labels, names)` builds `<section id="findings-by-type">` in place of
`#attention-panel`, after the questions panel and the parts-not-loaded headline:

- each group a `<details class="type-group" data-group="{id}">`, open as the backend's `open` says;
  its summary line the title and `text`;
- each row a `<details class="type-row stripe-{…}" data-finding-id="{survivor}">` whose summary is one
  line: the display title under a one-line clamp, then `tail_text`, `reach_text` and `chip`, each
  printed verbatim when it is not null; its body the finding cards of the row's members;
- after the rows, the group's goal lines (the existing `goalLine`); the `checked` fold last,
  collapsed;
- the stripe from `attention.stripeOf`, one shared copy.

`app.js`: while a turn runs, cards arrive in a holding list as today (`placeFinding`);
`applyRanking` returns every card to the holding list in arrival order, then moves each into its
row's body in the row's `member_finding_ids` order (generalising and replacing
`groupModellingPractice`, `app.js:1118-1147`). A card no row names stays in the holding list, never
dropped. A row whose `hide_card_title` is true hides its card's repeated title. `revealFinding` opens the group and the
row before scrolling. "Collapse all" closes rows and card folds, not groups. A `finding.withdrawn`
event removes the card and reloads the summary. Removed: `attentionPanel`, `countLine`,
`attentionIndex`, `attentionLine`, `findingCount`, `findingGroup`, `groupModellingPractice`,
`ungroupFindings`, the Show-all styles and `#attention-panel`.

The page never sorts, compares or counts: group order, row order and member order are the backend's
lists, and every count, plural and chip is a backend word the page prints or a flag it honours;
`PageRuleScanTests` passes with no new allowlist entry, and it catches ranking rules only, so the
page tests assert these fields are printed verbatim (`tasks.md` T053). All text goes through `dom.js`. SC-006
of feature 009 still holds: at most two clicks (a collapsed group, then the row).

## 6. The report

`report/markdown.py`'s `_render_start_here` becomes `## Findings by type`, built by
`findings_by_type`:

```markdown
## Findings by type

### Interference and fit: 2 findings
- **F-007** needs your judgement - Interference of 0.8 mm³ between …
- **F-008** needs your judgement - …
Goals: Interference - issues found; Hole alignment - checked; Fits and stacks - not reached (evidence missing)

### Modelling practice: 7 findings
- **F-003** rebuild breaker, demonstrated - Sketch2 is under defined
   - AI guidance: …
…

### Checked, no issue: 3 findings
- **F-011** checked within scope - …
```

then the coverage line and the policy footer, unchanged. The not-amplified line leaves the report
(every row is listed). `## Findings` is unchanged. The gate brief and `swreview attention` keep the
five-row Start here; feature 007's parity rule becomes: each of the gate's ids appears in the
report's index, in the same order within its group.

## 7. Tests

`test_finding_groups.py`: the partition; no pass in a type group; within each group the order of
`ranked_rows`, also on shuffled copies of the session; decided rows last; every class key of
`attention_policy_v1.yaml` maps to one of the seven groups and an unknown id lands in `other`, last;
each row's `tail_text`, `reach_text` and `hide_card_title`; with Mass and material's goal moved to
Hygiene, six groups and no empty one;
the family unfolded and the same-check fold kept; explanations on the same finding id; display titles;
an empty and an all-pass session; a sitting-shaped fixture (after part roles) with its expected rows.
`test_attention.py`: three undecided rows and two passes give `top_n` 3 and `checked_within_scope` 3
not amplified; all passes still give the empty reason; `attention.json` otherwise byte-identical.
`test_review_words.py`, `test_review_summary.py`, `test_review_summary_fixture.py`,
`test_review_snapshot.py`, `test_chat_attention_route.py`, `test_report_start_here.py` (the golden
rewritten), a new parity test, `test_finding_explanations.py` (a pass is never sent). Page tests in
`SwReview.AddIn.Tests`: `ReviewPageAttentionPanelTests` becomes group tests (supplied order, open
flags, a row opens its cards, a hostile title literal, an empty group prints its state, a row's
`tail_text`, `reach_text` and `chip` printed verbatim and `hide_card_title` honoured, the checked
fold collapsed, a second ranking regroups without duplicating a card, a card with no row stays
visible, `finding.withdrawn` drops the card); `ReviewPageInjectionTests`,
`ReviewPageDefaultViewScanTests`, `ReviewPageViewsTests`, `ReviewPageScaleTests` (1,000 findings),
`ReviewPageNarrowLayoutTests`, `ReviewPageSummaryTests`, `ReviewPageSummaryAcceptanceTests` (SC-001
amended: headline, tally and not-reached line in the 300 by 600 viewport), `SharedAttentionScriptTests`,
`ModelCheckPageTests` and `StandardsPageTests` (no pass in the preview); `PageRuleScanTests`
unchanged.
