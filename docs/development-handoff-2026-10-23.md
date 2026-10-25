# Development handoff, 2026-10-23

Updated 2026-10-24 with T188 source-attestation delivery and configuration-watch continuation.

The T188 metadata item was delivered in PR #41. The configuration-watch continuation below
defers subscription only during actual copy opening; verify its PR/gates before resuming.
Changed-root cleanup remains the known offline defect before Start; keep Remodel Start disabled.
The interrupted 160A and 157A work has been recovered, reviewed and combined; the earlier
159A recovery fixes have merged in PR #36. Delivery and final validation are recorded below. Verify
the table against the remote before starting new work. Original Claude branches and their worktrees were preserved.

## Delivery and validation

| Work | Delivery | Evidence |
|---|---|---|
| 160A pane, run-root and guard-list cleanup | [PR #34](https://github.com/coleas33/smart_SW/pull/34), head `0bbef37`, merged at `6b0508c` after all four CI checks passed | 002 T296-T302, 011 T221-T223. Final Windows build: zero warnings/errors; 10,125 extractor and 3,695 add-in tests passed. Python 3.12 and 3.11: 18,112 passed and 5 skipped each; Ruff passed. All fourteen late-init regressions failed before the fix. Independent review approved. |
| 157A check/restart holds and integration | [PR #35](https://github.com/coleas33/smart_SW/pull/35), head `320375c`, merged at `931e4b0` after all four CI checks passed | 002 T293-T295 and T303-T306. Windows build: zero warnings/errors; 10,125 extractor and 3,948 add-in tests passed. Python 3.12/3.11 each: 18,112 passed and 5 skipped, tokenizer required; sync, tokenizer fetch and Ruff passed. The unload regression was strengthened deliberately; five cases failed before the integration fix. Independent final review approved; actual-main integration preserved the tested code. |
| 159A failed-Plan cleanup and stopping-word reload | [PR #36](https://github.com/coleas33/smart_SW/pull/36), head `455a90e`, merged at `607f2c8` after all four CI checks passed | 004 T257-T261, research R19.27-R19.30. Nineteen focused cases passed after fourteen failed first and five guards already passed. Windows build: zero warnings/errors; 10,169 extractor and 4,114 add-in tests passed. Python 3.12/3.11 each: 18,166 passed and 5 skipped, tokenizer required; sync, tokenizer fetch and Ruff passed. Actual-main refresh preserved all gated product/test bytes; record checks run before commit. Independent review approved the two fixes. |
| 159A Stop retry identities | [PR #38](https://github.com/coleas33/smart_SW/pull/38), head `ca1329c`, merged at `a376c03` after all four CI checks passed | 004 T262-T264, research R19.31. Six C# and 23 Python cases failed first. All 143 focused C# and 164 Python route/integration cases pass. Windows Release build: zero warnings/errors; 10,169 extractor + 4,120 add-in tests pass. Full required-tokenizer Python 3.12/3.11 each: 18,193 passed and 5 skipped; sync, tokenizer and Ruff pass. Independent source/document audit approved unchanged code. Final record/identifier/link/task/LF checks precede commit. |
| 159A atomic after-dump handover | [PR #40](https://github.com/coleas33/smart_SW/pull/40), head `0c2473c`, merged at `6c50858` after all four required CI checks passed | 004 T265-T268, research R19.32. All 16 new Python cases failed first; 180 route/integration cases and 146 focused C# cases pass. Windows Release rebuild: zero warnings/errors; 10,169 extractor + 4,123 add-in tests pass. Full required-tokenizer Python 3.12/3.11 each: 18,209 passed and 5 skipped; sync, tokenizer and Ruff pass. Independent full source/document audit approved unchanged code; 298 final record/identifier cases pass, none skipped; link/task/named-test checks pass and final whitespace/index-LF checks precede commit. |
| T188 source filesystem attestation metadata | [PR #41](https://github.com/coleas33/smart_SW/pull/41), head `1c0bf03`, merged at `62d22bb` after all four required CI checks passed | 004 T269-T272, research R20. All 64 new Python cases ran before implementation: 23 actual failures and 41 already-passing guards. C# stages produced four actual failures each; all 320 focused Python and 74 C# copy-family cases pass. Windows Release rebuild: zero warnings/errors; 10,178 extractor + 4,123 add-in tests pass. Full required-tokenizer Python 3.12/3.11 each: 18,273 passed and 5 skipped; sync, tokenizer and Ruff pass. Independent full source/document audit approved unchanged code; 298 final record/identifier cases pass, none skipped; link/task/named-test checks pass and final whitespace/index-LF checks precede commit. This completes only the attestation part of T188. |
| T188 configuration-watch deferral | `codex/t188-watch-deferral`, based on `62d22bb`; verify its delivery PR and all four required CI checks | 004 T273-T276, research R21. Compiled red/green: 17 bridge + 6 host failures (4 guards), 17 add-in failures (1 guard), then 6 lifecycle failures (194 guards); focused 316 boundary and 200 add-in cases pass. Both complete Python suites pass 18,273 with 5 skipped. Windows Release rebuild/test both exit 0, zero warnings/errors, 10,199 extractor + 4,153 add-in tests passed. Independent source/document audits approved unchanged code; 298 final record/identifier cases pass, none skipped, with named-test/link/task/LF and whitespace checks passing. Native open/failed-unwind timing remains pilot acceptance; Start stays disabled. |

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
this introduces no new pane cancellation mode. The following continuation addresses the separate ordering defects.

## After-dump ordering continuation (004 T265 to T268)

[Issue #39](https://github.com/coleas33/smart_SW/issues/39) records the arrival-before-Stop-check
race and a late package handover that returned success after its wait had ended. Delivered in
[PR #40](https://github.com/coleas33/smart_SW/pull/40), head `0c2473c`, merged at `6c50858` after
all four required CI checks passed. A per-job rendezvous lock orders acceptance, cancellation, expiry,
shutdown and terminal closure. The first accepted package wins and cannot be replaced. Late or
duplicate handovers are refused as `PackageAfterRefused` (400), even while a failed worker is
still finalizing and has not yet published terminal status. Parsing stays outside the lock and
eligibility is rechecked before acceptance. Wrong-path/invalid-package refusals still permit a
corrected valid request while the wait is open.

The established policy is retained: a distinct Stop can cancel before acceptance, while an
accepted package outranks Stop. C# guards cover cancellation before dumping and a Stop flag
pressed during a held dump; neither reorders production pipeline calls. Stop identities and
write/run/session guards are unchanged. Full validation and independent review are recorded in
R19.32. The delivered source tree exactly matched the locally gated/reviewed tree.
This work does not approve Start or the remaining root-cleanup case.


## T188 source-attestation continuation (004 T269 to T272)

The source's filesystem ReadOnly bit is now recorded before the copy as nullable `read_only`
metadata beside its hash, in both `plan.json`'s `source` and `source-attestation.json`. It is not
an ACL, vault permission or SOLIDWORKS document-open mode; false grants no write permission.
Expected failures of this extra metadata read remain unknown. Mandatory source evidence failures
and unexpected errors still fail recording. Python retains the value without remeasuring it;
the size/time/hash recheck and its verdict are unchanged.

The nine existing recorded fields remain required. Old replies, plans and artifacts which omit
`read_only` load as unknown without read-time rewriting. Only exact Boolean/null values are
accepted for the extension; arbitrary extra fields stay refused. Two fictional fixtures pin
old/current artifact compatibility. Tests, gate evidence and the independent review are in R20.
PR #41 delivered this metadata at `62d22bb`; its tested tree exactly matches the merged tree.
The configuration-watch continuation follows below. The documented `InvokeTimeout` alternative
is retained. Neither item settles root-change cleanup or approves Start.

## Next offline work: decision 159A remains in progress

1. **Settle cleanup after a run-root change.** The old run's close is refused as outside the new
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


   Read-only follow-up found that exposing pending cleanup as `BackendBusy` alone would deadlock:
   Plan applies the pending restart before its existing cleanup. A coherent direction is a
   dedicated cleanup prerequisite before stopping backend A, with a retriable/deferred outcome
   that keeps B saved and A in force until the exact old session answers. Check active turn,
   check and run holds first; do not put HTTP in the quick `DeferredRestart.Begin` callback or
   label pending cleanup as a running turn. Ordinary restart failure clears pending work and
   is not the right result for this prerequisite.

   If A has exited, its HTTP close cannot recover the session. Investigate a narrowly bound
   internal native hook around the existing guarded session-ending routine, checking the full
   canonical run directory and captured attachment/service on the application thread. Run IDs
   alone are insufficient for equal basenames under different roots; delayed cleanup must not
   close a replacement session. `Dispose`, terminal gate disposal and `FollowDocument` are not
   targeted cleanup receipts. Preserve the existing answered-with-what-it-left outcomes rather
   than requiring every cleanup action to succeed. Add no outside-root HTTP exception or write
   allowance. Acceptance also needs dead-A recovery, waiting/failed/finished leftovers, stale
   attachments and delayed equal-basename cleanup, with Save, unload and other holds unchanged.

Changed-root cleanup remains a known defect before Start readiness. Earlier R19.26 statements that no known defect
remained are corrected by R19.29. The small fixes above do not approve the unresolved cases.


## T188 configuration-watch continuation (004 T273 to T276)

This continuation uses `codex/t188-watch-deferral` from `62d22bb`. R21 and the new tasks record
the exact callback contract, compiled test-first failures and gate evidence. Verify delivery
and all four required CI checks before treating this branch as delivered.

An optional scope around `SwBridgeDispatcher.Open`'s existing `OpenIn` try/finally tells the
add-in when actual copy opening is in progress. Only `ActiveConfigurationWatch.Follow` waits;
tab notifications, copy-loss handling and ToolServiceGate holds remain immediate. Changes
coalesce and queued work resolves the latest active document after the final scope exits.
The explicit scope still protects against UI work pumped during native `OpenDoc7`; neither
`RunInProgress` nor posting alone establishes that boundary. Old queued work and
scopes are invalidated before watch replacement or unload. Watch disposal is terminal, including
when native unsubscribe or subscribe reenters unload; late sinks remain inactive. Keep this event subscription separate from decision
158A's bridge attachment-follow policy.

T188's implementation is complete with the source metadata, watch lifecycle and documented
`InvokeTimeout` alternative. The fake scheduling/lifecycle tests and local/CI gates do
not validate native SOLIDWORKS timing: the next licensed Plan/probe sitting must check that
configuration subscription stays outside actual OpenDoc7 and failed-open unwind, and that
normal configuration switching still follows the active part/assembly (009 T081). Native
acceptance and the Start switch stay held. Changed-root cleanup above is the next known
offline defect; 014 T254-T259 still wait on paid slice gate T253.

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

Follow 004 tasks after T276 and record the new failing tests before implementation. Run the
full reviewer gates with the tokenizer required on Python 3.12, and 3.11 at the slice gate;
run the zero-warning Windows C# build and tests. Keep pytest temporary folders outside the
checkout, paid/seat tasks gated, and all changes to main behind a PR with green CI.
