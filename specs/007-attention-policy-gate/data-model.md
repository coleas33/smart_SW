# Data Model: Attention Policy and Procedural Gate

**Feature**: `007-attention-policy-gate` | **Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)

No IR change and no change to the review-session contract's `Finding` or `ReviewSession`
shapes, both of which are `additionalProperties: false`. Everything this feature records lives
in two places: a new sibling file beside `session.json`, and three response bodies. The one
model change is additive and one-line: `Timing.baseline_minutes` gains the `ge=0` constraint
its committed schema already states, and `EfficiencySettings` gains its eleventh boolean, in
the contract's `properties` and never in its `required`.

---

## 1. The attention policy (a versioned data file)

`reviewer/src/swreview/report/attention_policy_v1.yaml`, loaded once by
`report/attention.py`. `contracts/attention.md` is normative; this is the model.

| Field | Type | Rules |
|---|---|---|
| `version` | str | `attention_policy_v1`. Travels into every record and every report footer |
| `needs_judgement` | list[str] | Check-id prefixes whose findings sort first among the undecided: `interference.`, `fit.`, `fastener.`, `hole.` |
| `classes` | map[str, ConsequenceClass] | Every emittable check id to exactly one class. A missing id sorts as `unclassified` and is printed by name; the catalogue test fails the build |
| `blind_spots` | map[str, str] | One sentence per pre-run family (`fastener_joint`, `hole_alignment`, `fit`, `axial_stack`, `interference`, `standards`) saying what no enumerator can see. Read by the gate's brief only |
| `triage_pass_preconditions` | list[str] | The four written conditions for ever adding an agentic triage pass (spec FR-035) |

`ConsequenceClass = Literal["rebuild_breaker", "interface", "manufacturing", "unclassified",
"discipline", "hygiene"]`, ordered as listed for the sort.

## 2. Python types (all in `report/attention.py`, pure)

### `AttentionKey`

The nine-key tuple, one named lookup per position, in sort order. Every value is an
integer or a string so two rankings compare byte-identically.

| Position | Name | Value |
|---|---|---|
| 1 | `suppressed` | 1 when `status == "checked_within_scope"` or `disposition.decision in {accepted, rejected}`; else 0 |
| 2 | `judgement` | 0 when the check id starts with a `needs_judgement` prefix; else 1 |
| 3 | `consequence` | the class's ordinal, `rebuild_breaker` = 0 … `hygiene` = 5 |
| 4 | `status` | demonstrated 0, suspected 1, unresolved 2, checked_within_scope 3 |
| 5 | `severity` | high 0, medium 1, low 2, info 3, read verbatim from the finding |
| 6 | `reach` | `3 - min(3, len(set(component_ids)))`, so more distinct components sort first |
| 7 | `carried` | 1 when `carried_over_from` is set; else 0 |
| 8 | `check` | the check id |
| 9 | `finding_id` | the surviving finding id of the row |

### `AttentionRow`

| Field | Type | Rules |
|---|---|---|
| `finding_id` | str | The row's surviving finding: the lowest finding id among the members |
| `member_finding_ids` | list[str] | Every finding folded into the row, the survivor first; length 1 when nothing folded |
| `check` | str | |
| `title` | str | The survivor's title |
| `status`, `severity` | as on the finding | |
| `component_ids` | list[str] | The union over members, sorted |
| `consequence_class` | ConsequenceClass | |
| `key` | AttentionKey | The nine values, so a placement is arguable by hand |
| `reason` | str | One sentence naming the key that placed the row: "needs your judgement", "rebuild breaker, demonstrated", "unclassified check `x.y`", … Never contains `%` |

### `Ranking`

| Field | Type | Rules |
|---|---|---|
| `policy_version` | str | |
| `rows` | list[AttentionRow] | Every row, in order, suppressed last; the report and the pane show the first `top_n` |
| `top_n` | int | 5 |
| `not_amplified` | NotAmplified | `total`, `checked_within_scope`, `dispositioned`, `info`, `beyond_top_n` |
| `coverage` | CoverageBlock | The five bucket counts; `not_closed: list[NotClosed]` - the unresolved items whose `check` is a checklist item id other than `coverage.closeout` (the close-out rows `finalize` writes for the items the run did not reach), each `{item, reason}` with the reason verbatim, at most five in the order the session holds them; `open_evidence_requests: int` (the `coverage.evidence_request` rows); `rules: {unresolved, skipped}` for every other unresolved and skipped item. A check folder has no checklist rows, so `not_closed` is empty there |
| `empty_reason` | str \| None | Set when `rows` is empty: "no findings were recorded" or "every finding is informational or already decided" |

`rank(session, policy) -> Ranking` is total: it never raises on any `ReviewSession`, which the
cross-product test proves. `fold(findings) -> list[list[Finding]]` groups by (check, status,
severity) with pairwise-disjoint `component_ids`, never a needs-judgement check, and never two
findings sharing a subject; single findings are singleton groups.

### `AttentionRecord` (`attention.json`)

| Field | Type | Rules |
|---|---|---|
| `policy_version` | str | |
| `session_id` | UUID | The session the record was computed from; a record naming another session is stale |
| `rows` | list[AttentionRow] | As rendered |
| `not_amplified`, `coverage`, `empty_reason` | as on `Ranking` | |

Written with `indent=2` and a trailing newline, like `session.json`. Re-running `rank` over
the finished `session.json` reproduces it exactly. Not added to `SESSION_FILES`; rotated
explicitly beside the session when a review claims an RMS check folder.

## 3. Response bodies (additive keys)

| Body | Key | Value | Contract |
|---|---|---|---|
| `CheckResult` (`POST /checks/rms`, `GET /checks/{id}`) | `attention` | `Ranking` JSON | `specs/003-…/contracts/model-check.md` |
| `StandardsResult` (`POST /checks/standards`, `GET /checks/{id}`) | `attention` | `Ranking` JSON | `specs/006-…/contracts/standards-check.md` |
| `GET /sessions/{chat_id}/attention` | the body | `Ranking` JSON | `contracts/attention.md`; the row lands in `chat-api.md` |

`GET` recomputes and writes nothing, so the JSON carries no timestamp, path or fresh id.

## 4. Timing (`Timing`, existing)

| Field | Change |
|---|---|
| `baseline_minutes: float \| None` | gains `Field(ge=0)`, matching the committed schema's `minimum: 0` |
| the other five | unchanged |

`record_timing_at(session_path, *, baseline, supervision, verification, false_alarms) ->
Timing` is the one writer; `record_timing(run_dir, package_id, ...)` wraps it. The route body
is `{baseline?, supervision?, verification?, false_alarms?}`; any other key is refused.

## 5. The ledger (existing models, one column)

| Model | Change |
|---|---|
| `adoption.METRICS` | `"median_net_saved_minutes": lambda run: run.scorecard.aggregate.median_net_saved_minutes` |
| `LeverDecision` | `median_net_saved_minutes: OffOn` |
| `LEVER_COLUMNS` | "Median net saved minutes off -> on" |
| `LeverCounter` | `fell_in_runs: list[str] = []` beside `dropped_tools`: the runs on the on arm whose per-run fit + axial-stack count fell below the off arm's minimum |
| `LEVER_COUNTERS` | `procedural_gate`: "check_fit and check_axial_stack calls per run (must not fall)"; `prerun_checks`'s placeholder string replaced by the same |

## 6. The lever and the checklist

| Model | Change |
|---|---|
| `EfficiencySettings` | `procedural_gate: bool = False`, appended last; docstring "Lever 11: …" |
| `review-session.schema.json` `EfficiencySettings` | the name in `properties`; not in `required` |
| `efficiency_from_levers` | refuses `procedural_gate` with `prerun_checks`, and with `coverage_stop` |
| `checklist_v1.yaml` | one item: `id: standards.release`, `check_prefix: standards.` |
| `start_review` | `standards_profile: Path \| None = None` |

## 7. The gate brief (a rendered string, one object)

`gate_brief(prerun: PrerunResult, ranking: Ranking) -> str`:

```
<lever-5 digest, byte-identical>

Start here:
  1. <the same line the report renders for row 1>
  …up to 5
  Not amplified: <the same line the report renders>

Needs your judgement:
  <one line per row whose judgement key is 0, or "none">

Not reached in this run:
  <checklist item>: <the reason the run recorded>   (the close-out rows, up to 5)
  <n> evidence requests open; <n> RMS rules unresolved, <n> skipped

Not visible to any rule:
  <blind-spot sentence per NotEvaluated family, from the policy file>

These verdicts are computed from checked code. Do not re-derive them; spend your rounds on
what was not reached.

<OPENING_MESSAGE>
```

## 8. Relationships

```
ReviewSession ──rank(policy)──▶ Ranking ──▶ report.md "## Start here"   (render_report ranking=)
                                   ├──▶ attention.json                   (finalize / write_report / _write_report / rerender_run_folder)
                                   ├──▶ CheckResult.attention, StandardsResult.attention, GET /sessions/{id}/attention
                                   └──▶ gate_brief(prerun, ranking) ──▶ the first user message (gate on)
Timing ◀── record_timing_at ◀── swreview timing | POST /sessions/{id}/timing | benchmark time
```
