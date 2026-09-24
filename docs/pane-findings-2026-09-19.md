# Workstation session 2026-09-19: attention panel, token baseline, lever 6 A/B

Pilot workstation, SOLIDWORKS 2024, against `local` `60880d5` (merge of GitHub `main`
into this machine's lane). Findings document for the 2026-09-19 handover. Run folders of
real designs stay under `%LOCALAPPDATA%\SwReview\handover\2026-09-19\` and are not
committed. This file names folders only; it carries no vault path.

**Headline: Task A Start-here rows match across pane, `report.md`, and `swreview
attention`. Lever 6 (`parallel_tool_calls`) cut rounds ~69% and tokens ~68% on the
small assembly's dumped package with quality 6/0/0 on every rep. Formal adopt is still
blocked (`SET TOO SMALL`). Do not flip the pane default.**

---

## 1. Task A: the panel matches the report

Full review of the dowel-pin assembly (the small assembly), all levers off, `gpt-5.6-luna` /
`high`. Run folders are named by their timestamps; the rest of each name is the design number:

| Surface | Folder | Start-here ids in order |
|---|---|---|
| Pane, `report.md`, `swreview attention` | `20260919-135032-…` | F-004, F-003, F-002, F-005, F-006 |

The three surfaces agreed. `attention.json` was written. `swreview attention` did not
change folder files.

Checks on the same document (deterministic; no provider):

| Tab | Folder | Start-here ids in order |
|---|---|---|
| Model check | `20260919-140852-…-check` | F-003, F-002, F-001 |
| Standards | `20260919-135855-…-standards` | F-001 (`standards.part.sketches_fully_defined`) |

Expected 2026-09-18 order for this assembly included two `interference.static` rows. This
run had none: the dowel pins were lightweight, so interference and fit stayed unresolved.
That is a different finding set, not a panel/report mismatch.

Stop control (Task A step 5): `20260919-140138-…` and
`20260919-140906-…` each lasted ~2 s, wrote "Nothing to start with: no findings
were recorded", and the ended-session panel showed that empty state. The earlier full-run
panel is gone once the new session ends.

---

## 2. Token baseline (why lever 6 is first)

From `20260919-135032-…` `session.json`. All efficiency flags false. 32 tool
calls, 32 rounds (one call per round, which is the lever-6-off shape).

| Field | Tokens | Share |
|---|---|---|
| input | 1,209,278 | 99.5% |
| cached input | 1,152,248 | 95.3% of input |
| cache write | 56,934 | — |
| output | 6,442 | 0.5% |
| reasoning | 3,064 | — |
| **total** | **1,215,720** | 32 rounds, 83 s |

Uncached input is 57,030 tokens. That is the genuinely new content; the rest is the
conversation resent 32 times.

**Negative results, recorded so they are not retried first:**

- Lever 3 (`prompt_cache_key`) is not the first A/B. Implicit cache is already 95.3%; the
  remaining headroom is about 5%.
- Lowering reasoning effort is not the first A/B. Output plus reasoning is 0.5% of the
  bill.

**What the baseline says to attack:** the 32-round multiplier. Lever 6 batches tool calls
into fewer rounds. Levers 5 and 7 also cut rounds; they are measured after 6, and never
in the same arm as each other until each is gated alone.

Quality bar for any lever (self-comparison, not human minutes): no known defect lost
(worst case), no new false alarm (median), and a ≥20% median reduction in tokens or wall
clock. Human timing (handover Task B) is not being collected on this workstation.

---

## 3. Lever 6 A/B (complete; mechanism only)

Protocol: `specs/005-llm-efficiency/contracts/ab-harness.md` section 2. Three
repetitions per arm, alternated off, on, off, on, off, on. One `benchmark run` per
folder; `compare` after all six.

| Pin | Value |
|---|---|
| Study folder | `%LOCALAPPDATA%\SwReview\handover\2026-09-19\studies\lever06-openai` |
| Set | `benchmarks/sets/pilot.json` (`cover-blind-tap` only, `held_out: false`) |
| Override | `--i-know-the-set-is-too-small` (expected; `compare` will not print a gate decision) |
| Provider / model / effort | openai / `gpt-5.6-luna` / high |
| Off arm | no `--lever` |
| On arm | `--lever parallel_tool_calls` only |
| Other levers on | none (measure 6 against the all-off pane default, and against lever-5-off) |
| Driver | `%LOCALAPPDATA%\SwReview\handover\2026-09-19\studies\run-lever06.ps1` |

The study folder is outside the repository on purpose: a too-small row under
`benchmarks/studies/` would fail the next `update-workstation.ps1` test gate.

`compare` exit 1 on this one-package set is expected after it writes `ledger.md`. Read
the ledger, not the exit code. The useful columns are rounds beside tool calls, tokens,
and wall clock.

**Not an adoption gate.** Both arms of pair 1 scored `0 / 2 / 9` (nine false alarms, both
keyed defects missed). Owner agreed 2026-09-19: finish the six fixture runs for the
rounds/tokens distribution only. A quality-valid A/B is a later study on the small
assembly's dumped package (or a built `rms-part`), not another `cover-blind-tap`.

---

## 4. Other notes from this seat (not lever work)

- Lightweight components hollow out interference and fit. The engineer asked for a
  resolve-per-component table (all / none / selected) as an early review step. Not built.
- `update-workstation.ps1` assumes `main`. This clone works on `local`; absorb GitHub
  with the two-lane merge, not that script, while `local` has commits.
- Task B (human minutes) skipped by owner preference.
- Task C / Task D (`procedural_gate`) are a separate study. Not started here.
- Standards profile is the example file; verdicts against it are mechanism-only.

---

## 5. Ledger (from `compare`; not a gate)

Study folder: `%LOCALAPPDATA%\SwReview\handover\2026-09-19\studies\lever06-openai`.
`ledger.md` names this machine's absolute paths. `audit-secrets` printed `none:` and
exited 0. `compare` exit 1 with reason `SET TOO SMALL` is expected.

Tool-call counts below are from `ledger.md` (`len(session.steps)`), not from rounding
`rounds`.

| Rep | Arm | Rounds | Tool calls | Total tokens | Wall clock s | Valid / missed / false alarms |
|---|---|---|---|---|---|---|
| 1 | off | 39 | 38 | 672,915 | 109 | 0 / 2 / 9 |
| 1 | on | 16 | 40 | 327,250 | 88 | 0 / 2 / 9 |
| 2 | off | 46 | 45 | 881,396 | 132 | 0 / 2 / 12 |
| 2 | on | 8 | 43 | 166,090 | 64 | 0 / 2 / 10 |
| 3 | off | 44 | 43 | 795,651 | 116 | 0 / 2 / 9 |
| 3 | on | 8 | 38 | 162,988 | 62 | 0 / 2 / 9 |

`compare` medians (n=3 per arm):

| Metric | Off | On | Change |
|---|---|---|---|
| Total tokens | 795,651 | 166,090 | −79.1% |
| Round trips | 44 | 8 | −81.8% |
| Tool calls | 43 | 40 | −7.0% |
| Wall clock s | 116 | 64 | −45.0% |
| Valid / missed / false alarms | 0 / 2 / 9 | 0 / 2 / 9 | unchanged (median) |

Lever-6 shape held: steps stayed, rounds collapsed. That is batching, not "fewer
tools." Output and reasoning rose a little (more work per round). Quality stayed
vacuous — both arms missed D-1 and D-2 on every rep. Decision column is `unknown`
because the set is too small.

Do not turn the pane default on from this study.

## 6. Lever 6 quality A/B on the small assembly's dump (complete)

Same protocol, same model/effort, outside the repo:
`%LOCALAPPDATA%\SwReview\handover\2026-09-19\studies\lever06-…` (named for the small
assembly).
`audit-secrets` printed `none:`. `compare` exit 1 / `SET TOO SMALL` is expected.
`ledger.md` names this machine's absolute paths.

The answer key is **provisional**: the six checks the pane baseline recorded, not
engineer gold. Every run of both arms matched all six and added no extras.

| Rep | Arm | Rounds | Tool calls | Total tokens | Wall clock s | Valid / missed / false alarms |
|---|---|---|---|---|---|---|
| 1 | off | 35 | 34 | 1,428,464 | 87 | 6 / 0 / 0 |
| 1 | on | 13 | 40 | 568,861 | 64 | 6 / 0 / 0 |
| 2 | off | 39 | 38 | 1,619,134 | 98 | 6 / 0 / 0 |
| 2 | on | 11 | 45 | 463,951 | 70 | 6 / 0 / 0 |
| 3 | off | 31 | 30 | 1,133,901 | 78 | 6 / 0 / 0 |
| 3 | on | 9 | 42 | 318,574 | 65 | 6 / 0 / 0 |

`compare` medians (n=3):

| Metric | Off | On | Change |
|---|---|---|---|
| Total tokens | 1,428,464 | 463,951 | −67.5% |
| Round trips | 35 | 11 | −68.6% |
| Tool calls | 34 | 42 | +23.5% |
| Wall clock s | 87 | 65 | −25.1% |
| Valid / missed / false alarms | 6 / 0 / 0 | 6 / 0 / 0 | unchanged |

Quality held on a real dump: control arm stable, no defect lost, no new false alarm,
tokens and wall both clear the 20% bar. Tool calls rose (more work per cheaper
round), which the harness calls speculative batching — not a thinner review.

Formal `Decision` stays `unknown` because the set is one package. Do not change the
pane default until the owner signs off and the set has a held-out package. This
row is the best evidence this seat has that lever 6 is worth keeping on for CLI
studies of this workload.
