# Development handoff, 2026-10-23

Updated 2026-10-24 with the Stop retry continuation and completed local gates.

Resume with decision 159A's remaining late-Stop/dump and changed-root cleanup defects below.
The Stop retry continuation is recorded here; verify its PR and gates before resuming. Keep Remodel Start disabled.
The interrupted 160A and 157A work has been recovered, reviewed and combined; the earlier
159A recovery fixes have merged in PR #36. Delivery and final validation are recorded below. Verify
the table against the remote before starting new work. Original Claude branches and their worktrees were preserved.

## Delivery and validation

| Work | Delivery | Evidence |
|---|---|---|
| 160A pane, run-root and guard-list cleanup | [PR #34](https://github.com/coleas33/smart_SW/pull/34), head `0bbef37`, merged at `6b0508c` after all four CI checks passed | 002 T296-T302, 011 T221-T223. Final Windows build: zero warnings/errors; 10,125 extractor and 3,695 add-in tests passed. Python 3.12 and 3.11: 18,112 passed and 5 skipped each; Ruff passed. All fourteen late-init regressions failed before the fix. Independent review approved. |
| 157A check/restart holds and integration | [PR #35](https://github.com/coleas33/smart_SW/pull/35), head `320375c`, merged at `931e4b0` after all four CI checks passed | 002 T293-T295 and T303-T306. Windows build: zero warnings/errors; 10,125 extractor and 3,948 add-in tests passed. Python 3.12/3.11 each: 18,112 passed and 5 skipped, tokenizer required; sync, tokenizer fetch and Ruff passed. The unload regression was strengthened deliberately; five cases failed before the integration fix. Independent final review approved; actual-main integration preserved the tested code. |
| 159A failed-Plan cleanup and stopping-word reload | [PR #36](https://github.com/coleas33/smart_SW/pull/36), head `455a90e`, merged at `607f2c8` after all four CI checks passed | 004 T257-T261, research R19.27-R19.30. Nineteen focused cases passed after fourteen failed first and five guards already passed. Windows build: zero warnings/errors; 10,169 extractor and 4,114 add-in tests passed. Python 3.12/3.11 each: 18,166 passed and 5 skipped, tokenizer required; sync, tokenizer fetch and Ruff passed. Actual-main refresh preserved all gated product/test bytes; record checks run before commit. Independent review approved the two fixes. |
| 159A Stop retry identities | `codex/159a-stop-retries`, based on main `607f2c8`; inspect its PR for delivery status | 004 T262-T264, research R19.31. Six C# and 23 Python cases failed first. All 143 focused C# and 164 Python route/integration cases pass. Windows Release build: zero warnings/errors; 10,169 extractor + 4,120 add-in tests pass. Full required-tokenizer Python 3.12/3.11 each: 18,193 passed and 5 skipped; sync, tokenizer and Ruff pass. Independent source/document audit approved unchanged code. Final record/identifier/link/task/LF checks precede commit. |

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

## Stop retry continuation (004 T262 to T264)

[Issue #37](https://github.com/coleas33/smart_SW/issues/37) records the lost-reply defect. The
continuation branch is `codex/159a-stop-retries`, based on main `607f2c8`; check its PR before
changing it. Each backend Stop now carries a `stop_id` identifying the delivery intent, reused
across transport retries. The job counts each identified intent once, even after another intent
has arrived. A Stop accepted during apply cannot become a new cancellation when retried during
the after-dump wait. An intentional cancellation after a failed dump uses a fresh identity and
still ends the wait. Legacy requests without an identity retain distinct-receipt behavior.
The [backend contract](../specs/004-resilient-remodeler/contracts/backend-remodel.md) states the
validation and compatibility details. Repeated pane presses still share the host's stop flag;
this introduces no new pane cancellation mode. The separate ordering defects below remain.

## Next offline work: decision 159A remains in progress

1. **Enforce arrival-first ordering and truthful late delivery.** Decision 159A already says
   that a distinct Stop received during the after-dump wait cancels it, an apply Stop does not,
   and an arrived dump outranks Stop (R19.20). The timed wait can return false, then miss an
   arrival before it checks Stop. Reproduce that exact interval deterministically before fixing
   it; no new owner choice is needed to enforce the existing arrival-first rule.

   Begin with `test_a_dump_arrived_before_the_stop_check_wins_a_timed_wait`: a controlled
   `arrived.wait` requests a new Stop, delivers the package, then returns false; the wait must
   return that package. Use barriers around `RemodelJob.wait_for_package_after` and
   `RemodelServer._deliver` for additional worker/route interleavings, in
   [`test_chat_remodel_routes.py`](../reviewer/tests/unit/test_chat_remodel_routes.py). Also hold
   dump creation in `BackendRemodelPipelineTests`, deliver a distinct late Stop, then release
   the package: cancellation and the package handover must agree about whether the job can
   still consume it. `_deliver` currently returns success for a valid package even after the
   job failed or finished, and the gap between an ended wait and terminal worker status also
   needs coverage. Rejecting a dump after cancellation must preserve the stopped failure,
   evidence and unsaved copy. Preserving a healthy dump still being made despite a new Stop
   would revise the existing cancellation rule and needs an explicit policy choice; do not
   assume that revision is required to fix the race or truthful delivery.

2. **Settle cleanup after a run-root change.** The old run's close is refused as outside the new
   root before reaching the bridge; the next Plan retries the same cleanup. Resolve the
   cleanup/root policy without weakening run/session identity checks or permitting arbitrary
   paths. T258 intentionally retains the pending identity on this refusal.

   Follow [`RemodelHost.EndTheFailedPlan` / `EndTheSessionARunLeft`](../extractor/SwReview.AddIn/Remodel/RemodelHost.cs)
   through `BackendRemodelPipeline.CloseCopy` to
   [`resolve_run_dir`](../reviewer/src/swreview/chat/server.py). Decide whether a root change
   waits for cleanup or the specifically bound old session can be closed under its old root.
   Add a recovering A-to-B-root case in
   [`RemodelHostTests.cs`](../extractor/SwReview.AddIn.Tests/RemodelHostTests.cs) that keeps B
   configured and exercises real backend root validation; clearing a fake close failure alone
   would already pass and would miss this defect. `ReviewHost.RunRootsInForce` retains historical
   roots for pane file access, which does not authorize backend cleanup. `SwReviewAddIn.BackendBusy`
   holds a restart while `RunInProgress`, but a failed Plan's pending cleanup does not hold the
   root-change restart. Preserve the existing
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

Follow 004 tasks after T264 and record the new failing tests before implementation. Run the
full reviewer gates with the tokenizer required on Python 3.12, and 3.11 at the slice gate;
run the zero-warning Windows C# build and tests. Keep pytest temporary folders outside the
checkout, paid/seat tasks gated, and all changes to main behind a PR with green CI.
