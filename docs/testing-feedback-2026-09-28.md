# September 28 testing feedback and development follow-up

The testing packet ran `main` at `beaeb85`, including the newer checks-first,
engineer-first review, drawing context, and Remodel seat work. This follow-up starts
from that build on `codex/testing-feedback-2026-09-28`; it preserves the intervening
features and efficiency defaults. The owner authorized implementation of the reported fixes.

The branch holds two rounds: the first fixes (`63fc360`, `2aed3d5`), then a check of them by
four reviews - drawing, read-only source, crash hunt, and gates - whose findings were fixed
test-first in `f26a6ec` and `b583065` and the commit that carries this document. Each decision
the second round took is a default taken 2026-09-28 that the owner may revise, recorded in
feature 004's research R16 and tasks T185 to T188, and feature 011's research R7 and task T110.

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

- **U25, drawing Review.** Review is unavailable while a drawing is active, with and without an
  earlier review, and switching back restores the model-bound review. Since the second round the
  host decides "drawing" (`kind` on `init` and `document.changed`) and composes one sentence that
  names the model the drawing's views show - "{drawing} is a drawing of {model}. Keep the drawing
  open in SOLIDWORKS, open or switch to {model}, then press Review with it active; Review reads
  open drawings whose views show the model." - with several models it names the first and counts
  the rest, and with none known it names none. The page prints it as sent, Retry with a drawing
  active says why it did nothing, and the host's `DrawingActive` refusal carries the same words.
  The models are read only for a drawing, through a read-only gate; nothing is activated or opened.
- **U26, checked-in source.** A saved, clean read-only source is allowed; only the new copy is made
  writable, and the source's bytes, timestamp and attributes stay unchanged (now tested end to end
  over the real copy code). Since the second round, "clean" is only believed where SOLIDWORKS can
  report it: `GetSaveFlag` does not report a read-only model's unsaved changes while "Don't prompt
  to save read-only referenced documents" is selected (the API help's own remark), so with that
  option on the part is refused before any copy and the message says to turn it off or check the
  part out. Making the copy writable has its own failure (`copy_failed`, the copy deleted), and the
  source attestation is re-checked when the copy is closed, and after a failed open, so a plan-only
  run's record says whether the source is still what was copied.
- **U27, native exit.** Diagnostics first, then hardening where the evidence supported it:
  - the copy is measured as a whole part, the sequence the review dump makes on every part and the
    one proven on this seat the same day, with no `set_AccuracyLevel` and no `set_SelectedItems` -
    the two calls no seat had run, the second handed a plain `object[]` where the SOLIDWORKS
    programming guide requires a `DispatchWrapper` array for input arrays of its objects (PROBE-8,
    the one caller left, now wraps it). The copy's selection is cleared first, a part with other
    than one solid body is counted and not measured, and a volume that is not positive and finite
    is not a reading;
  - `POST /remodel/open` refuses a baseline that is not usable and ends the session;
  - `CommandInProgress` is put back as `remodel.open`'s last step (the API help: set it before a
    sequence of calls, back after it, and it affects only out-of-process applications); the three
    dialog toggles still hold for the session;
  - a pipe thread answers anything that escapes a request with an error line instead of letting it
    reach the SOLIDWORKS process.
  Native crash resolution still needs the seat retest below.

## What the crash evidence establishes

The packet contains a successful **bridge** `remodel.open` line (about 1.3 s) and a source
attestation, but no `open.json`, baseline package, or plan. The HTTP `POST /remodel/open` route
opens the copy, writes the attestation, calls `remodel.geometry`, validates its reply, and writes
`open.json` before returning to the add-in. The backend wrote the attestation and then sent
`remodel.geometry`; after that nothing was written: no geometry request line, no 120-second
timeout line, no HTTP answer, no `remodel.close`, and none of the teardown or stopped lines every
earlier tool-service log ends with. The copy was never saved (its hash is the attested source's)
and its lock file was left behind. So SOLIDWORKS ended while the geometry request was running on
the application thread or waiting for it. The logs of that build cannot tell those two apart, and
whether SOLIDWORKS froze first or exited at once is not known.

No native crash dump or stack was included. The expected refusal to reattach while a Remodel turn
is running is not evidence of a crash cause. This development change does not claim that the
SOLIDWORKS crash has been reproduced or eliminated: removing the two unproven calls from the path
under investigation is what the evidence supports, and the retest is what decides.

## The diagnostics the next attempt leaves

- `remodel-open.jsonl`: timestamped backend phase boundaries, flushed and synced before each native
  call (`copy_open.begin` to `open_record.written`, and `cleanup.*` after a failed open). Fixed phase
  names only; a diagnostic write failure cannot prevent cleanup.
- `remodel.log`: a `command=<command> begin` line for every request before it runs, then
  `command=remodel.open stage=before <step>` / `stage=after <step>` (or `failed`) around each step of
  the open that calls SOLIDWORKS or does file work, the unwind's steps included, and the same around
  every call of `remodel.geometry`, starting with the selection clear. Each is one file append,
  written before the call it names starts (the tests read the file from inside the fake call).
- `addin.log`: while a Remodel plan or run is in flight, `active document changed during a remodel
  run: fan-out begin` and `... fan-out end` around the add-in's document-change fan-out, which the
  copy's open raises.
- `source-attestation.json`: re-checked (`rechecked_at`, `matches`) when the copy closes or after a
  failed open, not only in phase D.

A before line without its after line identifies the call in progress, not its cause. These are
diagnostics only, not recovery records: they do not authorize resuming a run or enable Start.
Seat-validation flags remain unchanged.

## Focused workstation retest

Use the current [workstation setup and test plan](test-plan-2026-09-27/README.md), with this branch
as the build under test. Close SOLIDWORKS before rebuilding; fetch and merge the branch into the
workstation's intended lane, then use `extractor/tools/update-workstation.ps1 -NoPull`. Record the
installed commit. The plan's section "First: the retest of 2026-09-28's findings U25 to U27" runs it
right after step 1 and before step 2.4:

1. **U25** (the plan's step 4.9): J's drawing opened on its own - the line names J and Review is
   greyed out; J reviewed, then the drawing active again - whose review it is and the drawing's
   sentence, no Review invitation, and Retry starts nothing; back on J, the review returns; C, a
   multi-sheet drawing, names its model or counts several; the add-in log has no line saying a
   drawing's views could not be read.
2. **U27** (step 5.3, items A to C), before any real part, with every other document saved and
   closed: crash capture set where the seat has administrator rights (Windows LocalDumps for
   `SLDWORKS.exe`, a full dump into the handover folder); Remodel a copy on a throwaway box saved
   into the handover folder, whose phases must end `open_record.written` and whose `remodel.log`
   must end with the `get_Density` markers.
3. **U26** (step 5.3, items 1 to 6, on part J checked in), only once the box planned: J's
   `IsReadOnly` and the External References option noted first; with the option off, J plans on a
   copy; with it on, the refusal names the option. J's hash, size, time and read-only attribute are
   unchanged at the end, and so are the three dialog settings.

**If SOLIDWORKS closes again** (step 5.3's item C), before restarting it:

1. the time on the clock, and whether it froze, vanished, or showed its own error report (a photo);
2. the last phase in `remodel-open.jsonl` and the last `stage=before` line with no matching
   `stage=after`; no geometry marker with the phases at `baseline_geometry.begin` means the close was
   outside the measurement;
3. the whole run folder (`copy/` and its lock file included), the tool-service, backend and add-in
   logs, the SOLIDWORKS journal (`swxJRNL.swj` and `.bak`), the Application and System event logs,
   any SOLIDWORKS error report, and the dump;
4. after the restart, the three Tools > Options values the open sets (input dimension value, show
   errors every rebuild, warn before saving with update errors), because a close before the session
   ended can leave them as the run set them;
5. whether anything was selected or clicked in the copy's window;
6. the part rehashed against the attestation's `sha256` (an unrechecked attestation is not proof of
   post-crash source integrity).

`swreview handoff <run-dir> --out <new-handoff.zip>` now exports a Remodel run folder with a Remodel
run's records - required `remodel-open.jsonl`, `remodel.log`, `source-attestation.json`,
`open.json`, `package-before.json` and `plan.json`, and the later records when present - so its
missing list says what the run did not reach, and the manifest's `run_kind` says which list applied.
The native copy and company profile are not included by that exporter. Those records carry the
source's and the copy's paths: keep real-design packets local and inspect before sharing.

## What the second round did not change

- **Overrides and accuracy** (004 T187): a whole-part reading honours a mass, centre-of-mass or
  moment override; detecting one adds calls never run in this path, so it waits for PROBE-8 on a
  throwaway part with and without one. Then the reading either sets higher accuracy again or
  PROBE-8 calibrates at the default.
- **Smaller follow-ups** (004 T188): the source's read-only attribute in the attestation (the plan
  reads it before and after instead); the fan-out deferring its configuration watch onto a Remodel
  copy while a plan opens it (it finished cleanly in the packet, and is logged now); a read deadline
  in the Python pipe transport, which records its 60 s and does not enforce it (the add-in's 120 s
  is the bound a stuck call meets, as the code now says).

## Development validation

Second round, from the primary checkout on this branch:

- `dotnet build extractor/SwReview.sln -c Release`: 0 warnings, 0 errors.
- `dotnet test --no-build`: 9,036 extractor and 2,129 add-in tests passed, run twice with the Python
  suite alongside.
- Offline reviewer suite (`SWREVIEW_REQUIRE_TOKENIZER=1`, `-m "not live"`): 11,860 passed, 4 skipped,
  7 deselected; `ruff check src tests` passed.
- The interop manifest was regenerated from the installed interop metadata with
  `swreview-extract probe interop --emit-manifest` (SOLIDWORKS not started).

No live provider calls or native SOLIDWORKS retest were made during this validation. The native
crash remains unverified until the focused workstation retest above.

## Constitution check

Evidence and missing coverage stay explicit (I, VI): a reading that cannot be used is reported
and refused as a baseline, and a save flag that cannot be believed refuses the run. Numerics still
come from the existing geometry reader, on its proven whole-part sequence (II). Regressions use
fictional inputs and fake seats (III). Model binding and source attestation stay authoritative, and
the attestation is now re-checked for plan-only runs (IV). Existing copy, redaction, logging, and
export paths are reused (V). No source-write permission, new geometry algorithm, or unvalidated
execution capability is added; the one new call on the copy is the allowlisted selection clear.
