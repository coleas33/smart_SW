# Metrics

One row per metric: what it measures, the instrument that measures it, its baseline (or what it
needs before it can be measured) and its latest value. A value enters this file only with its
source: a sitting date and step, a command's output, or a count the private fork keeps (the
designs and scores themselves stay there). The roadmap that uses them is
[`README.md`](README.md#north-star-and-guardrails).

**Kinds.** The **north star** is the one number the plan steers by. **Quality** rows are the
four per-design measures of the constitution's Principle VI. **Guardrails** stop a change that
makes things worse, and never count as benefit on their own. **Process** rows watch the plan
itself. At today's denominator (one engineer; three real assemblies ever reviewed at a seat, none
with its drawings) per-design medians and rates mean nothing yet; per-review counts and process
counts do.

| Metric | Kind | Definition | Instrument | Baseline, or what it needs | Latest |
|---|---|---|---|---|---|
| Net engineering minutes saved per design | north star | Median over real designs of the baseline review minutes minus assisted minutes, assisted counting supervision, verification and false-alarm handling, unattended runtime reported apart (001 SC-001, FR-026; target at least 60) | `swreview timing` (feature 007), into the run's `session.json` and the report's Timing section | Not measurable yet: needs a baseline and the three assisted minutes on a real design (007 T060 (open), test-plan steps 4.1 and 4.5, S3), then five or more designs for a median | none |
| Escape-replay hits, held-out half | quality | Of the owner's late-caught defects tagged held out, how many the tool flags at the pre-fix revision: hit, partial or miss; reported as counts and categories only | `swreview benchmark score` on private keys, with the `held_out` and `tuned_on` tags; keys, designs and scores in the private fork | Not measurable yet: needs the owner's list split before the first replay, and each pre-fix revision reviewed at the seat (about one sitting) | none |
| New and real findings per design | quality | Findings the engineer triages *new and real* at the seat, per design; *real but already known* counted apart | Partly: the disposition route (`accepted`, `rejected`, `deferred`, a note) cannot tell new from known; the four-outcome triage is proposed, not in any tasks.md | Not measurable yet: needs the four-outcome triage on every finding of one real review at a seat | none |
| Missed known defects per design | quality | Known defects of a design the review did not flag | The scorer's missed defects on a keyed design (escape replay; 014 T265 (open)) | Not measurable yet: needs keys for real designs | none |
| False alarms per design | quality | Findings triaged *wrong*, and apart from them *true but not worth flagging*, per design | Partly: disposition `rejected` cannot split the two; the four-outcome triage is proposed | No real-design value; on a fictional fixture, 9 to 12 per run (`docs/history/pane-findings-2026-09-19.md`, "5. Ledger") | none |
| Unresolved coverage per design | quality | What a review recorded as unresolved, failed or not reached | The coverage block of `session.json`; the report's Coverage section and "Not reached" line | From the recorded real reviews: B 48 unresolved and 1 failed (2026-09-20); A 23 and 46 in two recordings (`reviewer/tests/fixtures/replay/`) | as baseline |
| Accepted share | guardrail | Accepted findings over dispositioned findings, per review; never benefit on its own | The disposition route; nothing counts them yet | Not measurable yet: no disposition was ever recorded at a seat | none |
| 014 recall and false alarms, by producer | guardrail | Recall on the fictional held-out set and false alarms, code and model producers apart (feature 014) | `swreview benchmark score`, `swreview benchmark report` | Not measurable yet: needs the paid pilot (014 T244, T245, both open); offline the oracle scores 100% and the null review 0% | none |
| Input tokens per review | guardrail | Input tokens of a review, uncached share and rounds beside them | The session's usage, the report's Tokens section, `swreview benchmark replay` | A: 590,498 on 2026-09-26 (first pass 199,139), first pass 297,812 on 2026-09-28; B: 12.4M billed on 2026-09-20, 660,007 when replayed under today's pane defaults | as baseline |
| Cost per review | guardrail | Money per review at the provider's prices | Prices in `reviewer/src/swreview/benchmark/prices.yaml`, through the replay | Not on record: needs the recorded runs priced by a replay (no seat needed) | none |
| Review wall time | guardrail | Time from Review to the last finding, unattended | The timing block's unattended runtime; `events.jsonl` timestamps | A: 83 s and 93 s (2026-09-19); B never timed | as baseline |
| Reports read by a second person | process | Finished reports read by someone other than the engineer who ran them, with what they would act on | None: a note in the private fork, counted here | 0 (no second reader on record; the owner says one can read a report before M1) | 0 |
| Seat tasks validated per month | process | Seat tasks ticked with a dated note from a sitting, per month | The `tasks.md` ticks, listed by `reviewer/tests/support/seat_tasks.py` | October 2026: 0; none of the four ticked seat tasks was ticked from use at a seat | 0 |
| Engineer asks retested at a seat | process | Rows of the pilot evidence ledger a later sitting retested | [`capabilities.md`](capabilities.md#2-the-pilot-evidence-ledger), section 2 | 2 of 45 retested, 11 partly (run 1) | 2 of 45 |
| Seat hours used per month | process | Hours at the pilot workstation, against about 7 available | None in the repository: sitting times stay in the findings document | Last sitting on record 2026-10-13; S1 not yet held | none on record since 2026-10-13 |
| Review rounds and reviewer runs per merged PR | process | Review rounds and reviewer agent runs per merged PR, with findings by severity and the share behind a switch that ships off | `gh pr view` bodies, counted as run 1 counted them | PRs #34 to #56 (21): median 2 rounds and 3 reviewer runs per PR; 218 findings, 23 high; 7.8% behind an off switch | as baseline |
| Merged PRs on a capability no engineer has used | process | Merged PRs whose changes serve a capability that ships off or was never used at a seat | `gh pr list` against the switches and the capability map | PRs #34 to #56: 14 of 21 change feature 004's package (16 counting two one-line notes) while Remodel's Start ships off | as baseline |
| Engineers and real designs reviewed | process | Distinct engineers, and distinct real designs reviewed at a seat | The dated sitting records | 1 engineer; 3 real assemblies (A, B, and one more on 2026-09-16), none with its drawing package | as baseline |

## The precision floor

Each check family gets a floor from seat triage. Default taken, the owner chooses the
threshold: a family whose findings over three triaged reviews are more than half *wrong* or *true
but not worth flagging* comes to the owner to fold, demote or switch off by default. Today's split
by family, on the one recorded review of B (2026-09-20, before checks first): modelling practice
85, standards 5, interference 6, hole alignment 3, none triaged
([`docs/history/roadmap-2026-09-22.md`](../history/roadmap-2026-09-22.md), "What the evidence
says" and "Decisions taken 2026-09-22").

## Assumptions

A1 and A2, which the plan rests on most, are in the roadmap's value model
([`README.md`](README.md#value-model)). The rest, numbered on from them:

- **A3.** The engineer's estimate of an unaided review is an acceptable baseline until a timed one
  exists.
- **A4.** "One design" is an assembly with its drawing package (001 `spec.md`, Assumptions).
- **A5.** Who signs each job of the release path, how long it takes and what a miss costs: held
  privately by the owner; assumption, owner to confirm.
- **A6.** The second reader judges in the same four outcomes as the engineer.
- **A7.** A model finding has release value only if it would change the released document or the
  build.
- **A8.** The owner tags every escape item held out or tuned-on before the first replay.
- **A9.** A pre-fix revision can be opened and reviewed at the seat without changing it.
- **A10.** A design reviewed in several runs is timed once.
- **A11.** Paid-review cost is not a binding limit at pilot scale.
- **A12.** Commits and PRs stand in for development hours, which nothing records.
