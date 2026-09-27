# Contract: Readings That Match SOLIDWORKS, and the Probe 1 Watchdog

Normative for FR-049 to FR-052 and User Story 7. Research R2.37, R2.38, R2.41. Amends feature 006's
`contracts/ir-additions.md` section 3 (a sheet's views include its own view; revision tables
deduplicated) and `contracts/rules.md` (`revision_matches`; `standards.part.sketches_fully_defined`
through the shared tree), and feature 003's `contracts/rules.md` ("Content features" and the sketch
rules). Feature 004's documents are not edited: the planner keeps importing the same names from
`remodel/nodes.py`, so its contract's text stays true.

## 1. The sheet's own view

`IDrawingReader` (`Dump/DrawingDumper.cs:89-96`) gains `SheetViews(document)`: the per-sheet arrays of
`IDrawingDoc.GetViews()`, whose first element per sheet is the sheet's own (type 1) view - one reader
shared with `SwOpenDrawingReader` (`:55-80`), which already reads it.

`ReadSheet` (`DrawingDumper.cs:711-742`), for sheet *i*: takes array *i*, confirms element 0 has type
1 and the sheet's name, and reads the sheet view's tables and notes with the other views. On a
mismatch (count, type or name), it records a gap (kind `not_extracted`, entity kind
`drawing_sheet_view`) naming the sheet and what differed, and keeps today's `ISheet.GetViews` reading for that sheet. No sheet is activated.

Revision tables join the table de-duplication (`TableSeen`) the other tables already get, since the
sheet view and a drawing view may return one table. `CrossCheckRevisionTable` (`:1935-1956`) is
unchanged; with the sheet view read it no longer fires on a sheet whose table was found.

The comment at `Program.cs:2961-2966` that says `GetFirstView`/`GetNextView` crosses sheets is
corrected. View ids shift by one per sheet in new packages; goldens that pin them are regenerated.

## 2. The revision check stays honest

`drawing_scope` (`checks/standards/drawing.py:353-357`) counts as unreadable, beside today's
`drawing_sheet_views` gaps, a sheet with a `revision_table_read` gap on its id and a sheet that
recorded no type-1 view (`sheets_without_format_view`, `:292-298`). `revision_matches` (`:656-674`)
then reports "no revision table" as **unresolved**, citing the gap, on such a sheet; the warning "no
revision table was found" is emitted only when every sheet was fully walked, each recorded its own
view, and none flagged a table. The property-to-model comparison still runs and can pass on its own
(a pass row beside an unresolved row).

## 3. One tree reading

```python
# reviewer/src/swreview/checks/feature_nodes.py   (moved from remodel/nodes.py)
def tree_nodes(features: Sequence[FeatureRow]) -> tuple[FeatureNode, ...]: ...
MergedRow, CarriedRow   # unchanged types
```

`remodel/nodes.py` re-exports the three names, so `remodel/plan.py:61`, `:862` and every planner
test are unchanged, and the planner's output is byte-identical.

Readers:

| Reader | Change |
|---|---|
| `checks/rms/part.py` `part_tree` (`:175-206`) | content and rows from `tree_nodes`: an absorbed sketch listed at depth 0 and again at depth 1 with one persist ref is one node; a carried sub-feature (the Hole Wizard's profile sketch) is its hole's, not a row of its own |
| grouping (`:358-375`), `rms.grouping.all_features_in_a_group` | an absorbed sketch is not its own loose row: it moves with the feature consuming it and is reported as part of it |
| `_sketch_status_rule` (`:884-927`), `one_sketch_per_feature` (`:933` onward) | each sketch named once; a second listing is not a consumer |
| `checks/standards/part.py` `part_scope` (`:211-235`), `sketches_fully_defined` (`:269-339`) | each sketch named once, at one location |

What was merged or carried is counted in one coverage note per part ("{m} second listings merged, {c}
carried sub-features read with their feature"), as the planner already records, so counts never drop
without a word. Finding counts and observed text change (the custom plate's loose features from 48 to
the 22 an engineer moves); feature 008's carried-finding comparisons (T128, T129) are re-read against
the regenerated fixtures.

## 4. The probe 1 watchdog

```csharp
// extractor/SwReview.Extractor/Rms/RemodelProbeWatchdog.cs
public static RemodelProbeWatchdogOutcome Run(
    Func<bool> call, Func<CancellationToken, Task> deadline, TimeSpan startBound);
public static RemodelProbeWatchdogOutcome RunWithTimeout(Func<bool> call, TimeSpan timeout)
    => Run(call, ct => Task.Delay(timeout, ct), StartBound);   // production, unchanged signature
```

- The call runs on its own thread (`Task.Factory.StartNew(..., TaskCreationOptions.LongRunning)`),
  never the pool, and sets a "started" signal on its first line.
- The watchdog waits up to `startBound` (30 s) for the signal and fails with an explicit error if it
  never comes; only then does it invoke `deadline`.
- `Task.WaitAny(call, deadline)`: the call first returns its result, rethrowing the host's own
  exception through `GetAwaiter().GetResult()` (never an `AggregateException`), and cancels the
  deadline; the deadline first returns `Blocked`.
- `RemodelProbeContext` gains an optional deadline factory, defaulting to
  `Task.Delay(WatchdogTimeout)`; probe 1 uses it.

*Added 2026-09-26, after this package:* feature 004 records the same change as 004 T171 (004
research R13.7); it is built once, with the signature above, under whichever list reaches it first.

*Landed 2026-09-26 (013 T137, 004 T171):* `Run` takes a fourth, optional argument,
`Func<Func<bool>, Task<bool>>? startCall = null` - how the call's thread is started, null for a
thread of its own - so a test can hold the call before its first line and show that no deadline
starts meanwhile; `StartBound` is `RemodelProbeWatchdog.StartBound`, and
`RemodelProbeWatchdog.Deadline(timeout)` is the one production deadline, used by `RunWithTimeout`
and by `RemodelProbeContext.WatchdogDeadline`'s default.

Probe 1 (`Rms/RemodelProbeExecutors.cs:344-372`) runs the **flag-set** attempt first, then the
flag-clear attempt, so a message box left open by one cannot spoil the other's reading;
`RemodelProbe1Logic.Decide` and the ledger's raw keys are unchanged. `RemodelProbeRunner` records the
host's own message (`RemodelProbe.cs:833-837`).

Tests: a parking fake records "attempt k parked" (a per-attempt `TaskCompletionSource`) and waits on a
`ManualResetEventSlim` that `Dispose` sets; the test's deadline is "attempt k parked" for blocking
scripts and "never" for scripts that return or throw. Every `Thread.Sleep(Timeout.Infinite)` and every
500 ms timeout leaves the tests.

## 5. Tests

C#: `DrawingDumperTests` (a fake whose `ISheet.GetViews` lacks the type-1 view while the document's
per-sheet arrays carry it, with a revision table and a BOM: one revision table, one table, no
cross-check gap, the sheet view recorded as type 1; a name or type mismatch records the gap and falls
back; a revision table returned by two views recorded once; a multi-sheet drawing takes each sheet's
array and calls no activation member); `DrawingTraversalTests` (fakes no longer put the sheet view
inside `ISheet.GetViews`). First a reproduction in a non-parallel collection: hold `ProcessorCount x 2`
pool items, run probe 1 with a host that throws through today's `RunWithTimeout(500 ms)` and see
`Refuted`; with the fix the same test reads `Unresolved`. `RemodelProbeExecutorsTests` over the parking
fake: toggles give `Unresolved`; a host throw gives `Unresolved` with the recorded message; blocked only
with the flag clear gives `Verified`; both blocked give `Refuted`; blocked only with the flag set gives
`Unresolved`; the flag-set attempt runs first; after `Dispose` no thread is parked.
`RemodelProbeWatchdogTests`: returns true and false with a deadline that never fires; a throw comes out
as the host's exception (`Assert.Throws`, not `ThrowsAny`); parked with a firing deadline gives
`Blocked`; the deadline factory is invoked only after the call signalled; one production-timer test in
the blocking direction only. Python: `test_standards_drawing_revision.py` (the cross-check gap and no
tables give unresolved citing it; a sheet with no type-1 view and no tables gives unresolved; a
complete walk with no table gives the warning; the comparison passing beside an unresolved table);
`test_feature_nodes.py` and, on the `remodel-absorbed-sketches` fixture, `test_rms_part_rules.py`,
`test_rms_groups.py`, `test_standards_part_rules.py` (each sketch once; the vendor pin shape's "4 features"
becomes 3; a carried profile sketch not a loose row); the planner's output byte-identical
(`test_tools_remodel_plan.py` unedited).
