# Development handoff, 2026-10-23

Resume with decision 159A's three remaining offline defects below. Keep Remodel Start disabled.
The interrupted 160A and 157A work has been recovered, reviewed and combined; the two small
159A recovery fixes are implemented. Delivery and final validation are recorded below. Verify
the table against the remote before starting new work. Original Claude branches and their worktrees were preserved.

## Delivery and validation

| Work | Delivery | Evidence |
|---|---|---|
| 160A pane, run-root and guard-list cleanup | [PR #34](https://github.com/coleas33/smart_SW/pull/34), head `0bbef37`, merged at `6b0508c` after all four CI checks passed | 002 T296-T302, 011 T221-T223. Final Windows build: zero warnings/errors; 10,125 extractor and 3,695 add-in tests passed. Python 3.12 and 3.11: 18,112 passed and 5 skipped each; Ruff passed. All fourteen late-init regressions failed before the fix. Independent review approved. |
| 157A check/restart holds and integration | [PR #35](https://github.com/coleas33/smart_SW/pull/35), head `320375c`, merged at `931e4b0` after all four CI checks passed | 002 T293-T295 and T303-T306. Windows build: zero warnings/errors; 10,125 extractor and 3,948 add-in tests passed. Python 3.12/3.11 each: 18,112 passed and 5 skipped, tokenizer required; sync, tokenizer fetch and Ruff passed. The unload regression was strengthened deliberately; five cases failed before the integration fix. Independent final review approved; actual-main integration preserved the tested code. |
| 159A failed-Plan cleanup and stopping-word reload | This continuation on `codex/159a-cleanup-recovery`, preserving original `86a7c9c` history; check its PR for remote delivery status | 004 T257-T261, research R19.27-R19.30. Nineteen focused cases passed after fourteen failed first and five guards already passed. Windows build: zero warnings/errors; 10,169 extractor and 4,114 add-in tests passed. Python 3.12/3.11 each: 18,166 passed and 5 skipped, tokenizer required; sync, tokenizer fetch and Ruff passed. Actual-main refresh preserved all gated product/test bytes; record checks run before commit. Independent review approved the two fixes. |

Every PR requires green CI on Windows/Linux and Python 3.11/3.12. No live/paid API test
ran, and SOLIDWORKS was not started. Local validation used fake providers and the installed
interop assemblies. Historical counts for earlier preservation commits remain in the feature
research; the table above records the gated code trees. The actual-main provenance refresh retained
all product/test blobs; final record updates are checked separately before commit.

## What changed

160A recovered the interrupted tests, protects the published Terminal tool lists, and makes
failed backend startup visible across the pane. An init reply or refusal captured before a
lifecycle failure cannot reinstate the failed backend or replace its banner; each tab obtains
fresh state. Initial result/model loading and Review chat replacement remain intact.

157A holds a settings restart through a Model or Standards check's extraction, delivery and
evaluation while the backend is up. A check started with a restart pending makes that restart
first. The shared check gate forwards one owner run-root probe through folder
validation and creation. Unload marks the host as stopping before waiting for worker threads,
so late saves and deferred completions report the correct state and cannot notify disposed
tabs. The documented minute-expiry limitation remains in the 157A research.

159A's earlier work binds commands after open to their run, keeps the host held until the
job ends, retries lost Start replies with the original job identity, and uses masked pane
messages and shared logging. This continuation retains an unsuccessful Plan's unanswered
cleanup identity separately from successful
runs and retries that exact run on the same tool-service attachment before another probe or
copy. A replaced attachment receives no old cleanup. An unanswered close refuses a new Plan
retryably; original Plan failures and evidence remain intact. Stop and copy-gone events also
retain their latest status for reload. Neither fix changes the write guard or enables Start.

## Next offline work: decision 159A remains in progress

1. **Make a retried Stop idempotent.** The pipeline retries a Stop whose answer was lost, while
   the backend counts every receipt. A retry during the after-dump can cancel a valid truncated
   run. Give an intent an identity or otherwise distinguish a retry from a genuine later
   cancellation. Begin with deterministic failing tests; preserve a real second cancellation.

   Start in [`BackendRemodelPipeline.Poll` / `TryStop`](../extractor/SwReview.AddIn/Remodel/BackendRemodelPipeline.cs)
   and [`RemodelJob.request_stop` / `wait_for_package_after`](../reviewer/src/swreview/chat/remodel.py).
   Existing `TestStop.test_stop_is_idempotent_and_sets_the_runs_flag` checks the reply and flag;
   it does not cover a lost reply followed by a retry during the dump wait. Add that interleaving
   in [`test_chat_remodel_routes.py`](../reviewer/tests/unit/test_chat_remodel_routes.py) and
   [`BackendRemodelPipelineTests.cs`](../extractor/SwReview.AddIn.Tests/BackendRemodelPipelineTests.cs).
   If Stop gains an intent identity, update the empty-body client test and its API contract.
2. **Settle late Stop and after-dump ordering.** A first Stop while the backend awaits its dump
   can fail the job before a healthy package arrives. Arrival can also race with the stop check
   after a timed wait. Define the cancellation rule and test both orderings before changing it.

   Use barriers around `RemodelJob.wait_for_package_after` and `RemodelServer._deliver` to test
   arrival after the timed wait returns but before the Stop check. The documented arrival-first
   rule needs that deterministic regression. In the C# pipeline tests, hold dump creation,
   deliver the first late Stop, then release a healthy package. The policy question is whether
   that first late Stop preserves verification or cancels it; cancellation must still work
   when no dump can arrive.
3. **Settle cleanup after a run-root change.** The old run's close is refused as outside the new
   root before reaching the bridge; the next Plan retries the same cleanup. Resolve the
   cleanup/root policy without weakening run/session identity checks or permitting arbitrary
   paths. T258 intentionally retains the pending identity on this refusal.

   Follow [`RemodelHost.EndTheFailedPlan` / `EndTheSessionARunLeft`](../extractor/SwReview.AddIn/Remodel/RemodelHost.cs)
   through `BackendRemodelPipeline.CloseCopy` to
   [`resolve_run_dir`](../reviewer/src/swreview/chat/server.py). Decide whether a root change
   waits for cleanup or the specifically bound old session can be closed under its old root.
   Add a recovering A-to-B-root case in
   [`RemodelHostTests.cs`](../extractor/SwReview.AddIn.Tests/RemodelHostTests.cs), preserving
   `AFailedPlansCleanupKeepsTheOldRunWhenTheRunRootMovesAndTheBackendRefusesIt`, outside-root
   refusal tests, and `ACommandOfAnotherRunIsRefusedBeforeAnythingIsReadOrWritten`.

These are known defects before Start readiness. Earlier R19.26 statements that no known defect
remained are corrected by R19.29. The small fixes above do not approve the unresolved cases.

## Owner and pilot-workstation prerequisites

- Keep 004 T172 off. It also waits on T180's owner decision, blocking PROBE-1, PROBE-2, PROBE-3,
  PROBE-4 and PROBE-12 verdicts, and a real Plan whose source hash stays unchanged.
- Draft PR #4 (134A/148A constitution amendment) still needs the owner's explicit go.
- 004 T003, calibration and native acceptance remain pilot-workstation work. Never launch
  SOLIDWORKS on an unlicensed development machine.
- 014 T221 is the next smoke review at the pilot workstation. Paid T244 runs additionally need
  the smoke review, served-model decision and explicit live-test authorization.
- The next unallocated owner-decision id is 161A. Continue existing decisions where applicable;
  take a new id only for an actual new owner decision.

Use the [workstation test plan](test-plan-2026-09-27/README.md) for the other seat-only tasks.

## Restart procedure

Fetch the remote, inspect the clean main and local worktrees, then create an owned `codex/`
branch for the next slice. Preserve `checkhold-157a`'s five original document edits and
`cleanups-160a`'s six interrupted test files in their original worktrees; their content was
recovered into the owned continuation branches. `remodel2-159a` at `86a7c9c` is the original clean
159A preservation point. The owned continuation branches retain the recovery and integration records. Fetch the remote
and inspect each branch's PR before changing it. The earlier [October 21 handoff](development-handoff-2026-10-21.md)
records the preservation work before these integrations.

Follow 004 tasks after T261 and record the new failing tests before implementation. Run the
full reviewer gates with the tokenizer required on Python 3.12, and 3.11 at the slice gate;
run the zero-warning Windows C# build and tests. Keep pytest temporary folders outside the
checkout, paid/seat tasks gated, and all changes to main behind a PR with green CI.
