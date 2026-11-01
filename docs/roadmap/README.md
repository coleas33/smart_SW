# Roadmap

How smart_SW becomes a tool working mechanical engineers choose for real SOLIDWORKS designs,
because it finds real problems sooner and more cheaply than they would alone and they trust what
it says. Benefit is measured, never asserted. The prompt that updates this page run after run is
[`PROMPT.md`](PROMPT.md); the holes are in [`holes.md`](holes.md), the measures in
[`metrics.md`](metrics.md), what is built and seen in [`capabilities.md`](capabilities.md).
Nothing here is a task: proposed work says "proposed, not in any tasks.md" and reaches a
`tasks.md` only after the owner's go.

## Run record

| Run | Date | `main` at start | Last register id read | Last sitting read | Prompt | Agents, by model |
|---|---|---|---|---|---|---|
| 1 (full) | 2026-10-31 | `a1ff6af6` | 178A | 2026-10-13 (`docs/history/testing-feedback-2026-10-13.md`); S1 not yet held | `PROMPT.md`, version 1 | 27 of 30: Opus 17 (one stopped at its output limit), Sonnet 8, Haiku 1, Codex 1 |
| 2 (update) | 2026-11-01 | `65bc3b21` | 185A | 2026-10-13 (`docs/history/testing-feedback-2026-10-13.md`); S1 not yet held | `PROMPT.md`, version 1 | 6 of 8: Opus 6 (three hunters, lenses a, c and d, g; three skeptics) |

## Change log

### Run 2, 2026-11-01 (update run)

Read `git log a1ff6af6..65bc3b21` (PRs #57 to #59), the register rows 179A to 185A and no sitting
record (none since 2026-10-13); hunted the lenses #58 and #59 touch: a, c and d, g. **Closed
offline:** H-g-007 (PR #59) and H-f-004 (PR #58), their tests in [`holes.md`](holes.md).
**Opened** 13: nine stand (H-a-009, H-a-010, H-a-013, H-d-008, H-g-009 to H-g-013), four merged
(H-a-011, H-a-012, H-c-007, H-d-007); the skeptics verified seven and refuted none. **Restated,
scores unchanged:** H-a-002 (now the by-hand reading), H-a-003, H-a-004 (181A placed M0-a's
review), H-g-004. No Codex re-check ran: H-a-009 and H-g-009 enter the top ten at 17 and wait for
the next full run. **Run 1's next cycle:** cycle 1 done (PR #59); cycle 2, H-g-003's escape keys,
slipped behind the owner's fixes and M0's records. **Measured:** nothing; the review-rounds row of
[`metrics.md`](metrics.md) has its first values under 180A. **Decided:** 186A to 190A. One
security item was reported to the owner privately, 2026-11-01. Run 1's entry and its Run 0 table
are in [`archive/2026-11-01.md`](archive/2026-11-01.md) (Run 0 one by one:
[`capabilities.md`](capabilities.md#5-run-0-the-earlier-roadmaps-near-term-items-one-by-one)).

## Value model

**The release path, and where the tool lands today.** Who signs each job, how long it takes and
what a miss costs are held privately by the owner, or "assumption, owner to confirm" (A5).

| Job | Document checked | Where the output must land to save time | What the tool can put there today |
|---|---|---|---|
| Self-check | model and drawing | fixes in the files before submitting | partly, on the model: Model check and Standards ran at the seat 2026-09-19 to 09-28, never triaged |
| Checker's red-line | the drawing | a red-line on the drawing, item by item | nowhere yet: no mark-up output, and drawing reading is off |
| Design review | model and drawing | the action list, each finding with its disposition | the nearest fit: `report.md` lists each finding with evidence and disposition; none was ever recorded at a seat |
| Release gate and sign-off | the released document (held privately) | the signed release record | nowhere yet: Standards' verdict stays in the pane, unvalidated (006 T100, T110 open) |
| ECO/ECN | model and drawing | the change form: parts, drawings, interfaces | nowhere yet: change impact is deferred (001 `spec.md`); a re-review starts from scratch |
| Shop or supplier RFI/NCR | the drawing | the NCR and the fix behind it | nowhere as output; as input, these are the escape-replay set |

**Model versus drawing.** Both drawing switches ship off: `DrawingOpenScope.SeatValidated`
(no closed drawing is opened; D14 at S1) and `DRAWING_BINDING_VALIDATED` (no callout binds to a
hole; D4 to D8 at S4). A review reads only drawings already open, which crashed Review on
2026-10-13 (ledger C1). So the tool serves the self-check and the design review, on the model
only, and no engineer has yet used either at a seat. On the owner's answer about the released
document (held privately) the drawing gap is a ranked hole (H-b-004).

**Instruments, and seat triage.** Dispositions (`accepted`, `rejected`, `deferred`, a note),
carried off the seat by `swreview handoff`, were never pressed at a seat. Since PR #59 each can
hold one of the four triage outcomes (185A): *new and real*, *real but already known*, *wrong*,
*true but not worth flagging*, counted in `report.md`. 007's `swreview timing` was never used;
since PR #59 it counts setup and the review left by hand (183A, 184A; H-a-002). `swreview
benchmark score` grades 014's fictional set; `swreview benchmark replay` prices recordings, not
usefulness. Nothing records a review timed without the tool. The north star counts *new and
real* findings and escape-replay hits; "accepted" alone is a guardrail.

**Escape replay and the defect census.** The owner names 10 to 20 defects caught late whose
pre-fix revision exists; list, designs and scores stay in the private fork, and this repository
records counts and categories only. Default taken, the owner may revise: a held-out evaluation
set, split before the first replay into a half that may steer checks (tagged `tuned_on` once
used, as `reviewer/src/swreview/benchmark/answer_key_model.py` allows) and a half only scored.
Each pre-fix revision is reviewed read-only at the seat, code checks first, scored hit, partial
or miss. Tallied by category, it is the **defect census** that ranks the checks. 014's recall
stays a regression guardrail: fictional held-out items, tuned-on real anchors (15A, 014, 2026-09-29).

**The denominator.** One engineer; three real assemblies ever reviewed at a seat (A, the small
assembly, the only one on the checks-first build; B, the big assembly, once on 2026-09-20; one
more on 2026-09-16), none with its drawings. Per-design medians and rates mean nothing at that
number; per-review and process counts do.

**Assumptions.** The plan rests most on two: **A1**, most of the owner's late defects are visible
in what the tool reads at the pre-fix revision (if most are drawing-only, the replay measures the
drawing gap); **A2**, about 7 seat hours a month time and triage at least one design per review
sitting. A3 to A12 sit beside the measures they qualify, in [`metrics.md`](metrics.md#assumptions).

## North star and guardrails

- **The north star exists: net engineering minutes saved per real design** (001 SC-001, FR-026),
  the median of baseline minus assisted minutes, assisted counting setup, supervision,
  verification, false alarms and the review left by hand (183A); at least 60. Beside it,
  Principle VI's per-design measures: valid findings (*new and real*), missed known defects (the
  escape replay), false alarms and unresolved coverage.
- **How far the evidence is:** no real design timed, triaged or keyed; only unresolved coverage
  has values. M0 gives the first numbers: one design, a value; five, a median, months away.
- **Another north star?** The value model asks whether the escape-replay count should lead, net
  minutes second; that amends 001 SC-001 and Principle VI's rationale. Default taken, the owner
  may revise: keep SC-001 and decide at M0's exit.
- **Guardrails, never benefit on their own:** the accepted share; 014's recall and false alarms
  on its fictional set; tokens, money and wall time per review; review rounds per merged PR.
- **Every kill or pivot** uses the pilot proposal's continue, narrow, revise or stop
  ([`pilot-proposal-2026-09-13.md`](../history/pilot-proposal-2026-09-13.md), "Success criteria
  and ROI"). Its checkpoint, 2026-10-03 in 001 `spec.md`, passed undecided, and today's evidence
  cannot choose: no benefit is measured either way, while the cost is (809 commits, 60 merged PRs
  and 143 decisions in October; no seat task validated by use).

## Milestones

Ordering, the earlier rule winning: validate before you build; measure before you optimise;
finish, park or delete before anything new; every cycle ends with something an engineer sees. No
new check enters without a real instance and the owner's estimate of its frequency and cost.

### M0. Does it find real problems in our designs?

- **Goal:** "Run it on a design I know and on old designs whose problems were caught late, judge
  each finding, and let someone else read one report."
- **Exit criteria:**
  1. A, a design the engineer knows, reviewed with the send box unticked (step 4.10, items 1, 2),
     every flagged finding given one of the four outcomes and a wrong pass marked a miss (187A,
     188A), the minutes kept with `swreview timing` in the private fork (186A).
  2. The same design reviewed with the model (step 4.1) and triaged the same way, so the model's
     gain over the free checks is a number on a real design, not only on 014's generated cases.
  3. The escape replay on at least 10 of the owner's defects, each pre-fix revision opened
     read-only at the seat, code checks first, scored with `swreview benchmark score` on private
     keys (a proposed step of M0-a).
  4. The big assembly's three real defects against the current build: step 4.2 shows RD1 to RD3
     or not, and the engineer judges each (H-g-002); on B, only these (190A).
  5. One report, carried off the seat by `swreview handoff`, read by the second reader, who gives
     each finding the four outcomes.
- **Holes it closes:** H-a-001 to H-a-004, H-a-009, H-a-010, H-a-013, H-c-006, H-d-008, H-e-003,
  H-g-002, H-g-003, H-g-009 to H-g-013.
- **Seat time:** two sittings after S1: M0-a, no key (step 1, the triaged review, the replay's
  extractions, step 6); M0-b, S3's first sitting (steps 2.5, 4.1, 4.2, 4.5 and 4.11).
- **Owner decisions:** taken, the sitting order (181A), the freeze (179A), the timing kept private
  (186A), passes and 'already known' (187A, 188A), the re-run (189A) and B's scope (190A); open,
  the escape list; one model for the seat, the pane and the study (H-e-003); the second reader; at
  the exit, continue, narrow, revise or stop on these numbers, and the north-star question (H-a-001).
- **Does not do:** no new feature package, check or lever study; Start stays off; no drawing
  switch beyond S1's D14 report. **Risks:** A1 fails and the replay measures the drawing gap
  (itself a finding); one design is an anecdote; Review crashing with drawings open recurs; M0-a
  overruns (H-a-010).
- **Kill or pivot:** stop if neither the triage nor the replay shows a *new and real* finding;
  revise, drawings first, if most escapes are drawing-borne; narrow to the families that gave
  *new and real* findings.

### M1. Finish or park what no engineer asked for

- **Goal:** "My seat time goes to what I asked for; nothing half-built waits on me." Its decisions
  can be taken during M0; its exit needs ten minutes of S1.
- **Exit criteria:**
  1. Step 5.1's parts P give 004 T003 its numbers and the owner signs 004 T004 (open) on them;
     Start then goes on at S2, or 004 is parked with a dated note under 173A (H-f-004, closed
     offline: PR #58 placed the parts in S1 or M0-a).
  2. The count script (`uv run python count_tasks.py`, capabilities.md's appendix) shows 005's
     lever tasks without an engineer's ask, and 014 T245 to T264, closed under 173A with dated
     notes; 014 keeps 014 T221 and its paid pilot 014 T244 as the guardrail, and the escape
     replay is a study of its own (23A, 014, 2026-09-29) (H-f-007, H-f-008).
  3. `uv run python count_tasks.py` shows the open seat backlog under the owner's size (H-f-001).
- **Holes it closes:** H-c-003, H-f-001, H-f-005, H-f-006, H-f-007, H-f-008, H-g-008.
- **Seat time:** ten minutes. **Owner decisions:** each park; the intake cap; a growth budget;
  taken, the review tiers (180A). **Does not do:** delete code without a decision. **Risks:**
  parking what an engineer later wants (a dated note is cheap to undo). **Kill or pivot:** a kept
  track names its engineer demand before its next seat step.

### M2. Act on what M0 measured

- **Goal:** "The checks that found real problems come first, the wrong or trivial ones go quiet,
  and the drawing the checker red-lines is read."
- **Exit criteria:**
  1. Each family's four-outcome split over three reviews triaged as steps 4.1 and 4.2 triage them,
     and every family over the owner's threshold folded, demoted or off by default (H-g-004).
  2. The census's top category served: if drawing-borne, probes D4 to D8 at S4 (steps 3.2 to
     3.8; 011 T064, T066) and the binding switch set; otherwise its check fixed, demand cited.
  3. The press-fit pass fixed, failing test first (proposed:
     `test_a_pin_the_engineer_calls_press_fit_is_not_passed_as_floating`, H-d-002), and no read
     unchecked against known values labelled "Checked by code" (proposed:
     `test_an_unvalidated_read_is_not_labelled_checked_by_code`, H-d-003, H-d-004).
  4. A second real design, never reviewed before, triaged and timed (step 4.1's protocol).
  5. The escape replay's held-out half scored again with `swreview benchmark score` on the new
     build: hits not below M0's.
- **Holes it closes:** H-a-008, H-b-004, H-b-005, H-c-001, H-c-002, H-d-002, H-d-003, H-d-004,
  H-d-005, H-d-006, H-g-004.
- **Seat time:** S4 and one review sitting. **Owner decisions:** the precision threshold
  ([`metrics.md`](metrics.md)); 14A for the 2026-10-13 retest (H-c-001); the label rule.
  **Does not do:** drawing creation (012 stays reserved). **Risks:** steering on the held-out
  half; S4's probes failing. **Kill or pivot:** if held-out hits fall, revert what steered them.

### M3. The first median: five real designs

- **Goal:** "On five of my designs, the time it saves me is counted."
- **Exit criteria:** five real designs timed with `swreview timing` and triaged (step 4.1's
  protocol); their median net minutes in [`metrics.md`](metrics.md); the owner's continue,
  narrow, revise or stop recorded at a full roadmap run.
- **Holes it closes:** what M0 to M2 leave; H-e-002 if a design is larger than B; H-e-004.
  **Seat time:**
  about three sittings. **Owner decisions:** the five designs; the checkpoint. **Does not do:**
  start a new track. **Risks:** designs the engineer knows bias the baseline. **Kill or pivot:**
  a median below zero is a stop or a narrowing.

## Operating cadence

- **Cycles and sittings are separate.** A cycle ends at a merged PR; a sitting runs what is merged
  and waiting. Each cycle's end and each sitting's return is an update run ([`PROMPT.md`](PROMPT.md),
  section 5), each milestone's exit a full run. "Shipped" means it reached the seat at the next
  sitting, or a new measured value appeared in [`metrics.md`](metrics.md).
- **Seat time is the scarce resource:** about 7 hours a month, two sittings of at most 3.5 h, of
  which step 1's update takes 55 minutes and the handoff 25 to 45: about 2 hours of purpose each.
- **The seat backlog:** the test plan's steps 2 to 5 are 12 h 15 min, about six sittings; outside
  that sum, unestimated, are 004 T135 to T141, the fixtures, 005's lever runs, 006 T104, T106,
  T108 to T110, 007 T061 to T063, 016 T010 and T015. At least nine sittings, about five months.
- **Budget:** M0 two sittings after S1; M1 ten minutes; M2 S4 and one review sitting; M3 about
  three. The gates that stop a measurement:
  [`capabilities.md`](capabilities.md#7-the-gates-that-stop-a-measurement).

## The next cycles' brief

**Cycle 1, make M0 countable: done** (PR #59; 183A to 185A; 002 T307 to T318, 007 T064 to T069).
The next cycles, in the owner's order of 2026-11-01, each on its own branch, failing tests first
(proposed, not in any tasks.md), reviewed at its 180A tier and merged on the owner's word:
- **Cycle 2, a refused correction shows the record** (H-g-012), before M0-a: 002 tasks; in C#,
  `ARefusedTriageShowsTheRecordedTriageAgain` and a refused triage's own sentence. Tier 2.
- **Cycle 3, a re-run keeps a decision whose verdict holds** (H-d-008, 189A), before M0-b: tasks
  appended to 002; `test_a_check_rerun_after_an_answer_keeps_the_decision_and_its_triage` and
  `test_a_check_rerun_with_another_verdict_clears_the_decision_and_says_so`. Tier 1.
- **Cycle 4, timing stays private** (186A), before M0-a: step 4.1 writes its figures in the private
  fork's copy, and the public-repository rule gains them, their pins first. Tier 3.
- **Cycle 5, what each outcome means** (H-g-009, 187A; H-a-009, 188A), before M0-a: 002 tasks,
  `test_the_report_counts_passes_apart_from_findings_by_triage`; step 4.1 defines the four. Tier 2.
- **Then M0's tables** (H-a-003, H-a-004, H-a-010 with 190A, H-a-013, H-g-010, H-g-011, H-g-013),
  when M0-a is planned. H-g-003's escape keys follow; until then M0-a scores the replay by hand.

## Questions for the owner, and defaults taken

**Answered:** round 2 (2026-10-31), 179A to 182A; after cycle 1's review (2026-11-01), the order of
work, with 183A kept, not numbered; in this run, 186A to 190A. Each is in
[`docs/decisions.md`](../decisions.md).

**Defaults taken, the owner may revise:** the escape set is a held-out evaluation set, split
before the first replay; the precision floor's threshold ([`metrics.md`](metrics.md#the-precision-floor));
the north-star question waits for M0's exit; the 2026-10-14 roadmap stays where it is, since
moving it into `docs/history/` breaks six links in files this run may not change; M0-b reviews A
fresh, the send box ticked first (H-g-013); how the vault returns an old revision with its
references, assumption, owner to confirm (H-a-013).

**Owner questions the holes route to a decision, each asked with its milestone:** one model for
the seat, the pane default and the study (H-e-003, M0); a lighter seat update (H-c-003), a growth
budget (H-f-005), an ask register (H-g-008), and parking 004 if 004 T003's numbers are poor
(H-f-004), all M1; 14A and the 2026-10-13 retest (H-c-001), the press-fit rule (H-d-002), labels
for reads never checked against known values (H-d-003, H-d-004), and carrying answers into a
re-review (H-c-002), all M2; and, on M0-a's records, which by-hand reading the net counts
(H-a-002).
