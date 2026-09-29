# September 28 testing feedback and development follow-up

The testing packet ran `main` at `beaeb85`, including the newer checks-first,
engineer-first review, drawing context, and Remodel seat work. This follow-up starts
from that build on `codex/testing-feedback-2026-09-28`; it preserves the intervening
features and efficiency defaults. The owner authorized implementation of the reported fixes.

## Evidence and scope

All 110 packet files are preserved byte-for-byte outside the public checkout under
`%LOCALAPPDATA%\SwReview\handoffs\handoff-2026-09-28\`. This includes the original findings, reports, event streams,
logs, native Remodel copy, and company standards profile. They are evidence, not
implementation instructions, and are not published with this change. This document
uses generic design descriptions; original identifiers and values stay local. The
repository's profile census also scans ignored directories, so the complete packet
is kept outside the checkout rather than weakening that check.

The engineer reported the remainder of the tool seemed to work. The small assembly
review completed with a first pass of 297,812 input tokens. Batched answers reclassified
bought parts and withdrew their inapplicable findings. Model check and Standards also
completed. These observations do not establish that every feature was tested.

## Changes and acceptance

- **U25, drawing Review:** drawing-specific guidance in the banner and error card;
  Review is unavailable until its part or assembly is active. Keep the drawing open so
  existing discovery can include it. With or without an earlier review, a drawing must
  never get the misleading Review invitation. Switching back must restore the correct
  model-bound review. The host must also refuse direct drawing Review requests clearly.
- **U26, checked-in source:** allow a saved, clean read-only source through the Remodel
  host. Existing filesystem copy and attestation rules still apply; only the newly
  created copy becomes writable. Source bytes, timestamp, and read-only attribute must
  remain unchanged. Dirty, unreadable, externally referenced, and unsupported sources
  must still refuse.
- **U27, native exit:** persist backend Open phases and geometry API operation markers,
  and harden the geometry-reading counter so unsuccessful measurements cannot count
  toward the save prerequisite. Diagnostics must precede the native call, avoid request
  data, and preserve cleanup on exceptions. Native crash resolution needs a seat retest.

## What the crash evidence establishes

The packet contains a successful **bridge** `remodel.open` line and a source attestation,
but no `open.json`, baseline package, or plan. The HTTP `POST /remodel/open` route opens
the copy, writes the attestation, calls `remodel.geometry`, validates its reply, and
writes `open.json` before returning to the add-in. Therefore the successful bridge line
does not establish that HTTP Open completed or that the add-in reached activation or
extraction. The packet is consistent with an interruption during baseline measurement.

No native crash dump or stack was included. The expected refusal to reattach while a
Remodel turn is running is not evidence of a crash cause. This development change does
not claim that the SOLIDWORKS crash has been reproduced or eliminated.

Two diagnostics make the next attempt attributable:

- `remodel-open.jsonl`: timestamped backend phase boundaries, flushed before the baseline
  call. It contains fixed phase names, not request data or failure details. A diagnostic
  write failure cannot prevent cleanup. `cleanup.returned` means the cleanup helper
  returned; the existing close outcome determines whether the copy actually closed.
- `remodel.log`: flushed before/after/failed markers around geometry API operations,
  alongside completed-command records. A before marker without a matching after marker
  identifies an interrupted operation, not its underlying cause. An adapter operation
  can include accessor calls: the material read also reads the active configuration.

These are diagnostics only, not recovery records or geometry acceptance. They do not
authorize resuming an interrupted run or enable Start. Seat-validation flags remain
unchanged. The typed mass-property API is retained: SOLIDWORKS documents part-body
selection in [SelectedItems](https://help.solidworks.com/2022/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IMassProperty2~SelectedItems.html).
There is no evidence here that replacing that API would fix the crash.

## Focused workstation retest

Use the current [workstation setup and test plan](test-plan-2026-09-27/README.md), with
this branch as the build under test. Close SOLIDWORKS before rebuilding; fetch and merge
the branch into the workstation's intended lane, then use
`extractor/tools/update-workstation.ps1 -NoPull`. Record the installed commit.

1. After an assembly review, activate its drawing. Confirm model guidance and no drawing
   Review invitation. Repeat with no prior review. Keep the drawing open, activate its
   model, and run Review; inspect drawing coverage rather than assuming every open
   drawing belongs to that model.
2. Request Remodel a copy from a saved, clean checked-in part. Confirm it is accepted
   without Save As or checkout and the source stays unchanged. Dirty or unreadable
   source state must still stop before copying.
3. Collect the new run folder even if planning fails. Check both diagnostic files.
   Complete Open writes `open.json`; complete Plan writes the baseline package and plan.
   Start remains disabled pending the existing blocking seat probes.
4. If SOLIDWORKS exits again, preserve the last markers and available Windows crash
   event/dump evidence before another attempt. An unrechecked attestation is not proof
   of post-crash source integrity; verify the source against its recorded hash.

`swreview handoff <run-dir> --out <new-handoff.zip>` now includes `remodel-open.jsonl`,
`remodel.log`, `open.json`, and `source-attestation.json` when present, including partial
runs. Missing review artifacts stay explicit. The native copy and company profile are
not included by that exporter. Keep real-design packets local and inspect before sharing.

## Development validation

- Release solution: 9,008 extractor tests and 2,103 add-in tests passed.
- After regenerating the pane fixture for `DrawingActive`, all 250 pane tests passed.
- Offline reviewer suite: 11,837 passed, 4 skipped, 7 live tests deselected. The required
  tokenizer setting was enabled. Ruff and whitespace checks passed.
- The secret audit found no occurrence of the configured CI dummy key in 28,475
  test-output files.
- The complete testing packet was rechecked against the ZIP after moving it outside
  the checkout; all 110 files match. The company-profile census passed unchanged.

No live provider calls or native SOLIDWORKS retest were made during this validation.
The native crash remains unverified until the focused workstation retest above.

## Constitution check

Evidence and missing coverage stay explicit (I, VI); numerics still come from the existing
geometry reader (II). Regressions use fictional inputs and fake seats (III). Model binding
and source attestation stay authoritative (IV). Existing copy, redaction, logging, and
export paths are reused (V). No source-write permission, new geometry algorithm, or
unvalidated execution capability is added.
