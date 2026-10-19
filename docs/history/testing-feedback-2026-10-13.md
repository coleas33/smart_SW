# October 13 workstation feedback: Review and Remodel fixes

The supplied private pilot handoff tested main at `017ba0a`. It reports recurring
Review crashes while an assembly was active, related drawings remained open, and
library components had been resolved. The empty run folders place those failures
before mesh creation. One preserved journal contains a CLR exception stack;
the raw evidence does not establish the exact failing phase or native member.
The private packet, its real designs and company profile remain outside this repo.

## Changes

Drawing attachment mapping now uses the owning part's
`IModelDocExtension.GetCorrespondingEntity2`. `IView.GetCorrespondingEntity` maps
in the opposite direction. The original drawing attachment supplies component
ownership before mapping loses that context. Adjacent faces and persistent
references retain that same part scope. Missing, unloaded or non-part owners
remain gaps. No document is opened, activated, resolved or changed by these reads.
This fixes a demonstrated API error; it does not establish native crash causation.

Queued pane refresh and page-post callbacks now contain exceptions from their
entire bodies, including session reads, view selection and WebView access. A
callback that runs after pane disposal returns without reading document/session
state. These asynchronous callbacks cannot rely on the caller's catch after
`BeginInvoke` has returned. The synchronous application-thread dispatcher is
unchanged.

Every written extraction now creates `extraction-progress.jsonl` before
traversal. Flushed rows identify attachment, traversal, drawing discovery, scope,
each phase, postprocessing, serialization and package writing. Rows also identify
the last guarded member and guard refusal. A `gated` row is an attempted guard
check, not proof that a native call ran or returned. The file contains symbolic
names and exception types, never model paths, values or exception messages.
An existing gate observer and its refusal audit are preserved and restored.
The handoff exporter includes this optional trace for both review and Remodel
runs, using its existing redaction, size and path rules. A missing trace is not a
missing required artifact. Pure `Build` and package-reuse probes do not create
diagnostics. Ordinary phase
failures still become gaps and an open circuit still stops later phases.

Remodel copy selection ignores SOLIDWORKS `~$` lock files. It still refuses zero
or multiple real parts and, when `open.json` exists, requires its exact recorded
copy. Older run folders without that record retain the singleton check. A plan
or later dump must name the exact activated copy rather than another document in
its folder. This fixes the repeatable "holds 2 parts" stop while the one copy is
open. Existing same-title open refusals remain: no unrelated document is closed.

## Validation

The test-first regressions reproduced the defects before the runtime changes:
15 copy-selection failures, four queued-callback failures, and ten drawing
attachment failures with one existing passing refusal. Four missing-diagnostics
cases failed with one passing no-write control before diagnostics were added.
The optional-export regression baseline was six failures with two passing
controls; the corrected handoff/CLI modules pass 28 cases with one existing skip.
The root integrated focused run passes 76 add-in cases and ten diagnostics cases
with a forced Release solution rebuild and zero warnings/errors. Independent
runtime and privacy reviews are clear. Complete branch-specific gate results are recorded below.

These fixes do not enable drawing opening or Remodel Start and do not publish
calibration. A scoped main update contains these handoff fixes; the complete
`015-review-send-gate` build also contains the earlier T180 lifetime/settings and
T187 calibration prerequisites from `5590266`. Use the intended branch when
collecting enablement evidence. Native SOLIDWORKS testing belongs on the separate
workstation; the development machine has no SOLIDWORKS.

## Focused workstation retest

1. Update and run the normal workstation gates with SOLIDWORKS closed. Use `main`
   for these handoff fixes, or select `015-review-send-gate` and use `-NoPull` for
   the complete enablement candidate. Confirm the actual revision before testing.
2. Reproduce the reported Review sequence with a suitable assembly: keep its
   related drawing open, activate the assembly, manually resolve the relevant
   components, then Review. Require a finished package and report with drawing
   evidence or explicit gaps, preserved active document and unchanged design
   files/save flags. Compare a drawing-closed run. If it fails or crashes, keep
   `extraction-progress.jsonl`, add-in/backend logs and the native journal outside
   the checkout. Preserve the last complete rows; do not infer a native return
   from `gated`. Also retest drawing-to-model-to-drawing pane transitions.
3. Remodel a saved writable test part with no older copy of the same title open.
   Require one real copy plus its ordinary SOLIDWORKS lock, completed Plan and
   source attestation, and unchanged source bytes/size/timestamps/attributes.
   Verify Discard closes only that owned copy. Start still refuses while its
   production validation switch is off. For the full 015 candidate, require all
   four application settings restored while the Plan is idle.
4. Keep the read-only source / External References-option refusal as the expected
   safety result while that option is selected. Do not weaken it to make Plan run.
   If SOLIDWORKS reports a prior same-title copy already open, deliberately close
   that prior copy before retrying and keep its run evidence; never automatically
   close an unrelated document. Then continue the separate drawing D14 and
   Remodel native calibration/enablement procedure when testing the 015 build.

## Complete gates on the frozen candidates

| Check | main | 015-review-send-gate |
|---|---|---|
| Tokenizer-enforced Python (`-m "not live"`) | 15,431 passed; 4 skipped; 7 deselected; 430.26 s | 16,022 passed; 5 skipped; 7 deselected; 443.42 s |
| Ruff over src/tests | Clean | Clean |
| Forced Release solution rebuild | Zero warnings/errors | Zero warnings/errors |
| Extractor .NET suite | 9,086 passed; zero skipped; 20 s | 9,138 passed; zero skipped; 18 s |
| Add-in .NET suite | 2,148 passed; zero skipped; 1 min 24 s | 2,277 passed; zero skipped; 2 min 36 s |

The 2,340 main files and 2,399 active-branch files, including each staged tree,
remained frozen through the complete runs. All four gate pipelines and their
native test children finished before this result-only update. The 24 C39 and 13
C45 controls on the active branch are unchanged. Independent staged, drawing,
copy, callback, diagnostics and exporter audits found no blocking issues.
Native application tests and both production enablement gates remain pending.
