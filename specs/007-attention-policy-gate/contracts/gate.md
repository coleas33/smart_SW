# Contract: The Procedural Gate

Normative for lever 11, the brief, the standards half of the pre-run, the checklist item, the
number guard, and the adoption rule.

## 1. Lever 11

`EfficiencySettings.procedural_gate: bool = False`, appended after `carry_over_rms`;
`--lever procedural_gate` on `swreview review` and `swreview benchmark run`. Recorded whole on
the session like every lever. The pane exposes no control for it; when adopted it becomes a
code default at `ChatServer._start_review`.

| Combination | Answer |
|---|---|
| `procedural_gate` alone | the pre-run runs (lever 5's calls plus the standards call when a profile is attached), the brief replaces the digest |
| `prerun_checks` alone | unchanged: the digest, byte-identical to today |
| `procedural_gate` + `prerun_checks` | refused: "levers 5 and 11 never share an arm until each has been gated alone" |
| `procedural_gate` + `coverage_stop` | refused, for the reason `prerun_checks` + `coverage_stop` is |

## 2. What the pre-run runs with the gate on

`planned_calls` is lever 5's list - `check_rms_part`, `check_rms_equations`,
`check_rms_assembly`, one `check_interference_group` per group, filtered by `tools.withheld` -
plus `check_standards` when the context carries a standards run. Every call goes through the
production dispatch and produces a real step, real events and findings that cite it.

The standards run is attached inside `start_review`, between `build_context` and the dispatch,
when `standards_profile` is given. Three things stop it, each a `NotEvaluated` line and a
skipped coverage item `coverage.prerun.standards`, never a refusal of the review:

| Reason | Line |
|---|---|
| no profile configured | "standards: no profile was configured for this review" |
| profile unreadable or invalid | "standards: the profile at <path> could not be loaded: <error>" |
| the package lacks the `cutlist` (or `drawing`) phase rows | "standards: the package was not dumped with the standards profile (missing phases: cutlist)" |

The pre-run's `error` read is guarded against an envelope without an `error` key.

## 3. The brief

`gate_brief(prerun, ranking) -> str`, the first user message (never the system prompt):

1. the lever-5 digest, byte-identical;
2. `Start here:` - the same lines `render_report` renders for the top rows, from the same
   `Ranking` object, then the same not-amplified line;
3. `Needs your judgement:` - the rows whose judgement key is 0, or `none`;
4. `Not reached in this run:` - the close-out rows with their recorded reasons (at most five), the open evidence requests, and the rule counts, as the report's coverage block prints them;
5. `Not visible to any rule:` - one sentence per `NotEvaluated` family from the policy file's
   `blind_spots`, backed one-to-one by the family's skipped coverage item;
6. the instruction: "These verdicts are computed from checked code. Do not re-derive them; spend
   your rounds on what was not reached."

Caps: five rows, five close-out items. Rows and items beyond the caps are counted, never
silently dropped. The anti-drift test asserts the brief's finding ids
equal the report's "Start here" ids in order for one fixture session, and it is structural:
both come from `ranking.rows`.

## 4. The checklist item

```yaml
- id: standards.release
  title: Release standards
  check_prefix: standards.
  description: >
    The company's release checklist as the standards profile configures it. Closed by a
    standards finding, or by the family's summary coverage item.
```

`standards.release` is `STANDARDS_FAMILY.summary_check`, so the family's summary item closes it
by id and any `standards.*` finding by prefix, exactly as `modeling.resilience` works. It moves
the system prompt for every review; the prompt-prefix stability fixtures and the byte counts in
feature 005's `contracts/levers.md` are updated in the same change.

## 5. The number guard

`record_drawing_finding` refuses, as an `error_result` the model may answer once, an `observed`
or `requirement` containing a number-like token that appears in none of the drawing evidence the
`source_refs` reach: the cited sheets' `dimensions[].text_as_read`, `general_notes`, and native
`DrawingNote` / annotation text.

| Token | Number-like? |
|---|---|
| `0.05`, `12`, `12.5 mm`, `1/4-20`, `±0.1` | yes |
| `F-003`, `cmp:0002`, `dnt:0007`, `Sheet 2`, `2026-09-18` | no |

The refusal names the token and the sheets it searched. The model's free transcript prose is
not guarded; it never enters the report.

## 6. Adoption

Six alternated runs off and on over the benchmark set with `--study procedural_gate`, each
scored, then one `benchmark compare`. The row's lever counter is the per-run sum of `check_fit`
and `check_axial_stack` calls: the arm medians, and `fell_in_runs` naming every on-arm run whose
count fell below the off arm's minimum. A non-empty `fell_in_runs` is a failed gate whatever the
token saving. Nothing becomes a default until the set holds held-out packages and the ledger row
carries a decision.
