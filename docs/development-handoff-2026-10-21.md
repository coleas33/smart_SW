# Development handoff, 2026-10-21

Delivery update, 2026-10-23: decision 160A merged through [PR #34](https://github.com/coleas33/smart_SW/pull/34),
with main at `6b0508c`. Decision 157A on `codex/resume-157a` now includes that actual main;
its final independent review and all local gates passed, and its PR delivery is next.
The separate 159A recovery candidate is still being gated. The original worktrees and their
uncommitted edits were preserved. The earlier sections below retain the recovery history.

## Completed in this continuation

- Recovered the six interrupted test files before implementing their fixes. The four page
  regressions and three Terminal-list cases all failed first.
- Kept the backend retry sentence on Remodel after capability updates and an older init reply.
- Made Review show a failed backend as not running, discard its stale endpoint, retain chat
  replacement identity, and remove an obsolete lifecycle banner once a backend is available.
- Published the Terminal tool lists without exposing writable arrays or collection interfaces.
- Strengthened the existing shutdown, latest-check and run-root regression coverage.
- Recorded the work as feature 002 T296 to T299 and feature 011 T221 to T223. Feature 002
  T293 to T295 already belong to the separate decision 157A branch.

Validation passed on the cleanup continuation: Python 3.12.3 and 3.11.16 each had
18,112 passed and 5 skipped with the tokenizer required; Ruff passed. The Windows C# build
had zero warnings, with 10,125 extractor tests and 3,681 add-in tests passing. The four
recovered page cases, three list cases and three additional review regressions each failed
before their respective fixes. Changed document links and task ids are clean; staged text
uses LF. No paid/live test ran, and SOLIDWORKS was not started.

## Branches to resume

Update on 2026-10-22: the continuation is published as draft PR #34. Its final adversarial
review found a late init reply could restore a failed backend's old endpoint and hide its
failure. Feature 002 T300 to T302 correct that order across Review, Model check, Standards and Remodel:
fourteen new page regressions failed first. Every page discards init requests overtaken by a
lifecycle failure and asks for fresh state, preserving the initial model/result loading and
Review chat replacement. Ordinary restarts do not reread the displayed check. All fourteen
focused cases pass; the Windows Release rebuild has zero warnings, and the complete C# gate
passes with 10,125 extractor and 3,695 add-in tests. Independent final review approved the
change with no material findings. Refreshed Python 3.12/3.11 tokenizer-required gates each
passed 18,112 tests with 5 skipped; sync, tokenizer fetch and Ruff passed. T302 was closed
on 2026-10-23 after recovering the completed gate results. All four required checks then passed;
PR #34 merged at `6b0508c` on 2026-10-23.

| Decision | Branch and last earlier commit | State and next step |
|---|---|---|
| 160A | `codex/resume-160a`, parent `cleanups-160a` at `8849e52` | Merged through PR #34 at `6b0508c`, with all four CI checks green and local gates complete through T302. |
| 157A | `codex/resume-157a`, `1652bcc`, based on `checkhold-157a` at `a4cc6f0` | The interrupted records and final actual-main integration are complete through T306. Independent review and all local gates passed; PR delivery is next. The five original documentation edits remain preserved. |
| 159A | `remodel2-159a`, `86a7c9c` | Original code through 004 T256 is preserved. The separate `codex/159a-cleanup-recovery` candidate implements the failed-Plan and stopping-word fixes and the readiness correction; its C# gate passed, Python gates/delivery remain pending. Three Start blockers remain below. |
| 134A / 148A | `constitution-134a`, draft PR #4 | Still awaits the owner's explicit go. This continuation does not approve the amendment. |

The separate 157A records commit passed the full Windows C# gate with zero warnings:
10,086 extractor tests and 3,813 add-in tests. Python 3.12 and 3.11 each had 18,111 passed and
5 skipped with the tokenizer required; Ruff, the changed links, task ids and final tracked-file
scan passed. Its earlier scale failure did not recur, and the three-second assertion is unchanged.

The final actual-main 157A integration passed the Windows build with zero warnings/errors:
10,125 extractor and 3,948 add-in tests. Python 3.12 and 3.11 each passed 18,112 tests with
5 skipped and the tokenizer required; sync, tokenizer fetch and Ruff passed. The refreshed
tree matched the tested candidate exactly before recording those results.

The branch tips above are preservation points; use their delivery state and check the remote. Check the remote before pushing. Keep changes reaching main behind a PR and green CI.
The next unallocated owner-decision id in the register is 161A.

## Decision 159A: findings from the original review

Update on 2026-10-23: items 1 and 4 are implemented and independently reviewed in the
separate recovery candidate, with full validation/delivery still pending. Items 2, 3 and 5
remain known defects before Start is enabled.

1. **Failed Plan cleanup can strand a session even with Start disabled.** If the bridge opened
   copy A, a later plan step failed, and the cleanup close was not answered, the host forgets A.
   A later plan B cannot close it: open B is refused as a run in progress and close B names the
   wrong session. Retain the pending cleanup's run identity and attachment, and settle it before
   another probe/copy. Preserve the bridge's session-mismatch checks.
2. **A retried Stop can become a second Stop.** The pipeline retries a Stop whose answer was
   lost, while the backend counts every receipt. A retry during the after-dump can cancel an
   otherwise valid truncated run. Give an intent an identity or otherwise make retries
   idempotent without hiding a real later cancellation.
3. **A first late Stop can cancel a healthy after-dump too.** Polling sees the backend awaiting
   its dump, sends Stop, then makes the dump; the backend can fail before the healthy package
   arrives. Arrival can also race with the stop check after a timed wait. Add deterministic
   tests before deciding the ordering/cancellation rule.
4. **Reload forgets the most recent Stopping status.** The host posts that sentence without
   retaining it for init. This is a small candidate fix once the run lifecycle work resumes.
5. **Cleanup of a finished session can loop after the run root changes.** The old run's close
   is refused as outside the new root before the bridge receives it; the next Plan retries the
   same refused cleanup. Resolve the cleanup/root policy before enabling Start.

That earlier second review was interrupted at the usage limit: its seven characterization probes
reproduced the reported behaviours, but it supplied no final approval. Do not treat the
previous reviews as approval of those unresolved cases. Local review artifacts are temporary;
the findings above are the durable restart record.

## Dependencies that remain

Keep Remodel Start disabled. Feature 004 T172 still depends on T180's owner decision,
PROBE-1, PROBE-2, PROBE-3, PROBE-4 and PROBE-12 verdicts, and a real Plan with the source
unchanged. The new review findings also need resolution or explicit prerequisites before
claiming readiness. T003, the calibration and native acceptance work remain pilot-workstation
work; do not start SOLIDWORKS on the unlicensed development machine.

Feature 014's next smoke review is T221 at the pilot workstation. Paid runs from T244 still
need that smoke review, the served-model decision, and explicit authorization for live tests.
Use the [workstation test plan](test-plan-2026-09-27/README.md) for the other seat-only tasks.

## Integration order

The cleanup PR is merged, and 157A is integrated and gated. Land its PR next, then refresh
159A against that actual main rather than
rebasing history referenced by the records. Preserve both branches' changes in the Review and
Remodel hosts and the numbered research/task sections. Regenerate word/event fixtures through
their existing generators if a merge changes the vocabulary; keep the byte-level fixture pins
consistent. Run the complete gates on each final merged tree, update the decision register
only to the status actually reached, then open its PR.
