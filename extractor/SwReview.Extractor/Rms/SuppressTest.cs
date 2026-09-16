using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using IrFeature = SwReview.Extractor.Ir.Feature;

namespace SwReview.Extractor.Rms;

/// <summary>
/// Raised when the suppress-test refuses to start. Every one of these is checked BEFORE the
/// first mutation, so a refused run leaves the document exactly as the engineer left it.
/// </summary>
[Serializable]
public class SuppressTestRefusedError : Exception
{
    public SuppressTestRefusedError(string message)
        : base(message)
    {
    }
}

/// <summary>One feature of the live tree, flattened in walk order, with no interop type.</summary>
public sealed class LiveFeature
{
    public LiveFeature(string name, string typeName, int depth, object handle)
    {
        Name = name ?? string.Empty;
        TypeName = typeName ?? string.Empty;
        Depth = depth;
        Handle = handle ?? throw new ArgumentNullException(nameof(handle));
    }

    /// <summary><c>IFeature.Name</c>.</summary>
    public string Name { get; }

    /// <summary><c>IFeature.GetTypeName2</c>.</summary>
    public string TypeName { get; }

    /// <summary>Sub-feature nesting depth, exactly as the dump records it.</summary>
    public int Depth { get; }

    /// <summary>The live <c>IFeature</c>, opaque here.</summary>
    public object Handle { get; }
}

/// <summary>
/// The live reads and the two writes <see cref="SuppressTest"/> needs, with no interop type
/// in any signature (<see cref="SwSuppressTarget"/> is the SOLIDWORKS one). The seam exists
/// so every decision this command makes - which refusals fire, what a row records, what the
/// restore puts back - is tested on a machine with no seat, exactly as <c>IFeatureReader</c>
/// and <c>IInterferenceSource</c> are.
///
/// Members that map to ONE interop call are gated by <see cref="SuppressTest"/>, which names
/// them, so the guard, the circuit breaker and the SC-003 observer see the production member
/// names even under a fake. <see cref="ActiveConfiguration"/>, <see cref="Walk"/> and
/// <see cref="IsSameFeature"/> span several calls each and gate them inside the
/// implementation.
/// </summary>
public interface ISuppressTarget
{
    /// <summary>The document's active configuration name. Gates its own calls.</summary>
    string ActiveConfiguration();

    /// <summary><c>IModelDoc2.GetSaveFlag</c>: true when the document has unsaved changes.</summary>
    bool HasUnsavedChanges();

    /// <summary>The feature tree, flattened in walk order. Gates its own calls.</summary>
    IReadOnlyList<LiveFeature> Walk();

    /// <summary><c>IFeature.IsRolledBack</c>.</summary>
    bool IsRolledBack(object feature);

    /// <summary><c>IFeature.IsSuppressed2</c> in <paramref name="configuration"/> only.</summary>
    bool IsSuppressed(object feature, string configuration);

    /// <summary>
    /// <c>IFeature.SetSuppression2</c> with <c>swThisConfiguration</c>; returns what
    /// SOLIDWORKS answered, which is never trusted on its own - the caller re-reads the state.
    /// </summary>
    bool Suppress(object feature, bool suppress, string configuration);

    /// <summary><c>IModelDoc2.ForceRebuild3(false)</c>: this document only.</summary>
    void Rebuild();

    /// <summary><c>IModelDocExtension.GetWhatsWrongCount</c>.</summary>
    int WhatsWrongCount();

    /// <summary>At most <paramref name="max"/> <c>GetWhatsWrong</c> messages, in order.</summary>
    IReadOnlyList<string> WhatsWrongMessages(int max);

    /// <summary>
    /// <c>IModelDocExtension.IsSamePersistentID</c> between the plan's reference and the live
    /// feature. Gates its own calls; reference bytes are never compared here (research R12).
    /// </summary>
    bool IsSameFeature(string persistRef, object feature);
}

/// <summary>What <c>suppress-test</c> was asked to do (contracts/cli.md).</summary>
public sealed class SuppressTestSettings
{
    /// <summary><c>--limit</c> when it was not given.</summary>
    public const int DefaultLimit = 50;

    /// <summary><c>--timeout-seconds</c> when it was not given.</summary>
    public const int DefaultTimeoutSeconds = 900;

    /// <summary>The plan file consumed, recorded into the run for the reviewer.</summary>
    public string PlanFile { get; set; } = string.Empty;

    /// <summary><c>--acknowledge-rebuild</c>. False refuses the run.</summary>
    public bool Acknowledged { get; set; }

    /// <summary>Features to attempt; the rest get <c>truncated</c> rows.</summary>
    public int Limit { get; set; } = DefaultLimit;

    /// <summary>Wall-clock budget; the rest get <c>truncated</c> rows.</summary>
    public int TimeoutSeconds { get; set; } = DefaultTimeoutSeconds;
}

/// <summary>The run and whether the command should exit non-zero.</summary>
public sealed class SuppressTestResult
{
    public SuppressTestResult(SuppressTestRun run, string? error)
    {
        Run = run ?? throw new ArgumentNullException(nameof(run));
        Error = error;
    }

    /// <summary>The run to append to the package, complete whatever happened.</summary>
    public SuppressTestRun Run { get; }

    /// <summary>What stopped the run, or null when it finished.</summary>
    public string? Error { get; }

    /// <summary>
    /// False when the run stopped early, when the tree could not be put back, or when no
    /// feature was ever suppressed and rebuilt. The first two are the obvious exit code 1: a
    /// model left modified in a way the command cannot describe is the worst outcome this
    /// feature has, and it must not look like success.
    ///
    /// The third is the quiet one. A document opened read-only answers false to every
    /// <c>SetSuppression2</c>, so every row comes back <c>not_applied</c>, nothing is
    /// rebuilt, the restore has nothing to put back and verifies - and the command would exit
    /// 0 having tested nothing. The exit code is the engineer's only signal, and a run that
    /// proved nothing is not a pass (Principle I). Rows that were skipped as
    /// <c>already_suppressed</c> do not count either: nothing was measured about them.
    /// </summary>
    public bool Succeeded => Error == null && Run.RestoreVerified && Rebuilt > 0;

    /// <summary>Rows whose feature really was suppressed and rebuilt.</summary>
    private int Rebuilt => Run.Rows.Count(
        row => row.Outcome == SuppressTestOutcome.Ok
            || row.Outcome == SuppressTestOutcome.RebuildErrors);
}

/// <summary>
/// T055. The engineer-run suppressibility test (FR-013, research R6): suppress one Detail
/// feature, rebuild, count what is wrong, put the tree back, repeat.
///
/// It is the only code in the product that changes the engineer's model, so it is written
/// around what it must never do:
///
///   * <b>Nothing happens without every precondition.</b> Acknowledgement, a saved document,
///     no rolled-back feature, the plan's configuration, a zero baseline, and a live tree
///     that still matches the package row for row and persistent id for persistent id. All
///     of them are checked before the first <c>SetSuppression2</c>.
///   * <b>The tree goes back after every feature.</b> Suppressing a feature suppresses its
///     dependents, so the restore compares the WHOLE tree with the snapshot rather than
///     unsuppressing the one feature it touched, and a run that cannot verify the restore
///     ends with <c>restore_verified = false</c> and a non-zero exit.
///   * <b>Nothing is assumed.</b> <c>SetSuppression2</c>'s answer is never trusted without
///     re-reading the state; a feature the run never reached is an <c>aborted</c> row, not a
///     missing one; and a feature whose state cannot be read during the restore is NAMED as
///     unrestored rather than hoped about.
///
/// The interop lives behind <see cref="ISuppressTarget"/>, and the single-call members are
/// named to <see cref="SwGate"/> here so the guard, the breaker and the SC-003 observer see
/// the production names under a fake. The gate this is built with decides whether the two
/// mutating members are allowed at all: only the console command's
/// <see cref="SuppressTestGuard"/> permits them.
/// </summary>
public sealed class SuppressTest
{
    /// <summary>Messages kept per row; the rest are counted in <c>messages_truncated</c>.</summary>
    public const int MaxMessages = 20;

    /// <summary>
    /// The refusal for a missing <c>--acknowledge-rebuild</c>, said in one place.
    ///
    /// contracts/cli.md row 20 lists this first among the refusals that happen "before
    /// touching anything", so the console command refuses with it before it connects to
    /// SOLIDWORKS; <see cref="Run"/> refuses with the same sentence as the library invariant
    /// for any other caller.
    /// </summary>
    public const string AcknowledgementRequiredMessage =
        "suppress-test suppresses features and rebuilds the model. Re-run it with "
        + "--acknowledge-rebuild once the document is one you are willing to have modified in "
        + "memory (it is never saved).";

    /// <summary>The last thing the command says, on stdout and in its log (FR-013).</summary>
    public const string ModifiedInMemoryMessage =
        "This document is modified in memory. Close it without saving - the file on disk is "
        + "unchanged, and saving it would keep whatever the test left behind.";

    private readonly SwGate _gate;
    private readonly ISuppressTarget _target;
    private readonly Func<DateTimeOffset> _now;

    /// <summary>
    /// <paramref name="clock"/> is the test seam for elapsed times and the timeout; null is
    /// the wall clock. It is read once at the start of the run and twice per attempted row.
    /// </summary>
    public SuppressTest(SwGate gate, ISuppressTarget target, Func<DateTimeOffset>? clock = null)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _target = target ?? throw new ArgumentNullException(nameof(target));
        _now = clock ?? (() => DateTimeOffset.Now);
    }

    /// <summary>
    /// Runs the test for <paramref name="plan"/> against the package rows
    /// <paramref name="packageFeatures"/> (the whole package's <c>features[]</c>; the rows
    /// for the plan's document are selected here).
    /// </summary>
    public SuppressTestResult Run(
        SuppressPlan plan, IReadOnlyList<IrFeature> packageFeatures, SuppressTestSettings settings)
    {
        if (plan == null)
        {
            throw new ArgumentNullException(nameof(plan));
        }

        if (packageFeatures == null)
        {
            throw new ArgumentNullException(nameof(packageFeatures));
        }

        if (settings == null)
        {
            throw new ArgumentNullException(nameof(settings));
        }

        if (settings.Limit < 1)
        {
            throw new ArgumentOutOfRangeException(
                nameof(settings), settings.Limit, "--limit must be at least 1.");
        }

        if (settings.TimeoutSeconds < 1)
        {
            throw new ArgumentOutOfRangeException(
                nameof(settings), settings.TimeoutSeconds, "--timeout-seconds must be at least 1.");
        }

        if (!settings.Acknowledged)
        {
            throw new SuppressTestRefusedError(AcknowledgementRequiredMessage);
        }

        IReadOnlyList<IrFeature> rows = RowsFor(plan.DocumentId, packageFeatures);

        if (_gate.Call(Member.SaveFlag, () => _target.HasUnsavedChanges()))
        {
            throw new SuppressTestRefusedError(
                "The document has unsaved changes. A previous suppress-test run leaves the "
                + "document modified in memory; close it without saving and reopen it before "
                + "running another.");
        }

        string configuration = _target.ActiveConfiguration();
        if (!string.Equals(configuration, plan.Configuration, StringComparison.Ordinal))
        {
            throw new SuppressTestRefusedError(
                $"The document's active configuration is '{configuration}' but the plan was "
                + $"written for '{plan.Configuration}'. Activate that configuration in "
                + "SOLIDWORKS first: this command never switches configurations, because that "
                + "rebuilds the model.");
        }

        IReadOnlyList<LiveFeature> walk = _target.Walk();
        bool[] snapshot = Compare(walk, rows, configuration, plan.DocumentId);

        int baseline = _gate.Call(Member.WhatsWrongCount, () => _target.WhatsWrongCount());
        if (baseline != 0)
        {
            IReadOnlyList<string> wrong = _gate.Call(
                Member.WhatsWrong, () => _target.WhatsWrongMessages(MaxMessages));
            throw new SuppressTestRefusedError(
                $"The document already has {baseline} rebuild error(s), so no feature's "
                + "suppression could be told apart from them: "
                + string.Join("; ", wrong.ToArray()));
        }

        int[] planned = PlannedIndexes(plan, rows, walk);

        var run = NewRun(plan, settings, baseline, _now());
        return Execute(run, rows, walk, snapshot, planned, configuration, settings);
    }

    /// <summary>
    /// The refusal for a document the engineer has not opened, said in one place.
    ///
    /// The extractor's only file-opening call is <c>SwSession.OpenReadOnly</c>, which opens
    /// read-only and silent so a dump can never change a reviewed model. That is the wrong
    /// door for this command: a read-only document answers false to every
    /// <c>SetSuppression2</c>, so the run would record <c>not_applied</c> for every planned
    /// feature, rebuild nothing, restore nothing - and it would have opened the engineer's
    /// part in their session to do it. The command refuses instead, and the engineer opens
    /// the part themselves.
    /// </summary>
    public static string DocumentNotOpenMessage(string documentPath) =>
        $"'{documentPath}' is not open in SOLIDWORKS. Open it with write access first: "
        + "suppress-test never opens a document, because the extractor's only open path is "
        + "read-only and a read-only document cannot be suppressed.";

    /// <summary>
    /// The lines the command writes to <c>suppress-test.log</c> and stderr: what the run
    /// found, the distinct interop members the gate saw (the SC-003 audit), every feature the
    /// restore could not put back, and the closing instruction.
    /// </summary>
    public static IReadOnlyList<string> LogLines(
        SuppressTestResult result, IReadOnlyList<string> gatedMembers)
    {
        if (result == null)
        {
            throw new ArgumentNullException(nameof(result));
        }

        SuppressTestRun run = result.Run;
        int tested = run.Rows.Count(
            row => row.Outcome != SuppressTestOutcome.Truncated
                && row.Outcome != SuppressTestOutcome.Aborted);

        var lines = new List<string>
        {
            $"{run.DocumentId} [{run.Configuration}] group {run.Group}, plan {run.PlanFile}",
            $"rows: {tested}/{run.FeaturesPresent} tested, "
                + $"{Count(run, SuppressTestOutcome.Ok)} ok, "
                + $"{Count(run, SuppressTestOutcome.RebuildErrors)} with rebuild errors, "
                + $"{Count(run, SuppressTestOutcome.AlreadySuppressed)} already suppressed, "
                + $"{Count(run, SuppressTestOutcome.NotApplied)} not applied, "
                + $"{Count(run, SuppressTestOutcome.Truncated)} truncated, "
                + $"{Count(run, SuppressTestOutcome.Aborted)} aborted",
            "interop members: "
                + (gatedMembers == null || gatedMembers.Count == 0
                    ? "(none)"
                    : string.Join(", ", gatedMembers.ToArray())),
            $"restore verified: {(run.RestoreVerified ? "yes" : "no")}",
        };

        if (result.Error != null)
        {
            lines.Add("the run stopped: " + result.Error);
        }

        if (run.UnrestoredFeatureIds.Count > 0)
        {
            lines.Add(
                "not restored: " + string.Join(", ", run.UnrestoredFeatureIds.ToArray())
                + " - these features are NOT in the state the document started in.");
        }

        lines.Add(ModifiedInMemoryMessage);
        return lines;
    }

    private SuppressTestResult Execute(
        SuppressTestRun run,
        IReadOnlyList<IrFeature> rows,
        IReadOnlyList<LiveFeature> walk,
        bool[] snapshot,
        int[] planned,
        string configuration,
        SuppressTestSettings settings)
    {
        DateTimeOffset started = run.RunAt;
        var timeout = TimeSpan.FromSeconds(settings.TimeoutSeconds);
        string? failure = null;
        int attempted = 0;

        for (int i = 0; i < planned.Length; i++)
        {
            SuppressTestRow row = run.Rows[i];
            LiveFeature feature = walk[planned[i]];

            if (attempted >= settings.Limit)
            {
                row.Outcome = SuppressTestOutcome.Truncated;
                continue;
            }

            DateTimeOffset rowStarted = _now();
            if (rowStarted - started >= timeout)
            {
                // Every remaining row is truncated from here, and the clock is not read
                // again: the budget is gone whatever the rest would have cost.
                for (int rest = i; rest < planned.Length; rest++)
                {
                    run.Rows[rest].Outcome = SuppressTestOutcome.Truncated;
                }

                break;
            }

            attempted++;
            try
            {
                TestOne(row, feature, snapshot[planned[i]], run.BaselineWhatsWrongCount, configuration);

                // The tree goes back before the next feature is tried, or every later row
                // would be measured against a model that is quietly missing features.
                IReadOnlyList<string> left = Restore(
                    walk, snapshot, configuration, rows, resetBreaker: false);
                if (left.Count > 0)
                {
                    failure = $"the tree could not be restored after '{feature.Name}': "
                        + string.Join(", ", left.ToArray());
                    row.ElapsedMs = Elapsed(rowStarted);
                    break;
                }
            }
            catch (Exception error)
            {
                row.Outcome = SuppressTestOutcome.Aborted;
                row.Error = error.Message;
                failure = error.Message;
                row.ElapsedMs = Elapsed(rowStarted);
                break;
            }

            row.ElapsedMs = Elapsed(rowStarted);
        }

        // The restore runs whatever happened, with the breaker reset first when something
        // threw: a breaker left open would refuse every call of the restore itself.
        //
        // And it runs inside a try, because a result is this method's promise: without one
        // the caller appends no rms_suppress_test row and writes no "not restored:" line for
        // a document it has already modified. Restore catches per feature, so nothing should
        // reach here; if anything does, every feature is named, because which ones were put
        // back is exactly what is no longer known.
        IReadOnlyList<string> unrestored;
        try
        {
            unrestored = Restore(walk, snapshot, configuration, rows, resetBreaker: failure != null);
        }
        catch (Exception error)
        {
            unrestored = rows.Select(row => row.Id).ToList();
            failure = failure ?? error.Message;
        }

        run.RestoreVerified = unrestored.Count == 0;
        run.UnrestoredFeatureIds.AddRange(unrestored);
        return new SuppressTestResult(run, failure);
    }

    /// <summary>One planned feature: skip, suppress, verify, rebuild, record.</summary>
    private void TestOne(
        SuppressTestRow row,
        LiveFeature feature,
        bool alreadySuppressed,
        int baseline,
        string configuration)
    {
        if (alreadySuppressed)
        {
            // Nothing is proved by suppressing what is already suppressed, and unsuppressing
            // it to find out would change the model the engineer is reviewing.
            row.Outcome = SuppressTestOutcome.AlreadySuppressed;
            return;
        }

        bool answered = _gate.Call(
            Member.SetSuppression, () => _target.Suppress(feature.Handle, true, configuration));
        bool suppressed = _gate.Call(
            Member.Suppressed, () => _target.IsSuppressed(feature.Handle, configuration));

        if (!answered || !suppressed)
        {
            // No rebuild: rebuilding an unchanged model would report a clean pass for a
            // feature that was never suppressed (Principle I).
            row.Outcome = SuppressTestOutcome.NotApplied;
            return;
        }

        _gate.Call(Member.Rebuild, () => _target.Rebuild());

        int count = _gate.Call(Member.WhatsWrongCount, () => _target.WhatsWrongCount());
        row.WhatsWrongCount = count;

        if (count > 0)
        {
            IReadOnlyList<string> messages = _gate.Call(
                Member.WhatsWrong, () => _target.WhatsWrongMessages(MaxMessages));
            row.Messages.AddRange(messages);
            row.MessagesTruncated = Math.Max(0, count - row.Messages.Count);
        }

        row.Outcome = count > baseline ? SuppressTestOutcome.RebuildErrors : SuppressTestOutcome.Ok;
    }

    /// <summary>
    /// Puts the whole tree back the way the snapshot had it and says which features it could
    /// not confirm.
    ///
    /// The comparison is over every feature, not the one under test: SOLIDWORKS suppresses a
    /// feature's dependents along with it, and unsuppressing only the tested feature would
    /// leave them suppressed for every row after it.
    ///
    /// Each feature is read, written back only if it differs, and READ AGAIN to verify: the
    /// answer <c>SetSuppression2</c> gives is not evidence that the state changed. A feature
    /// that matched the snapshot on the first read needs no second one - nothing has touched
    /// it since - which keeps the restore at one read for the tree's untouched majority.
    ///
    /// A read or a write that fails is caught PER FEATURE, so one dead feature does not stop
    /// the rest being restored, and that feature is NAMED as unrestored: "we could not
    /// confirm it" and "it is fine" are not the same answer. <see cref="CircuitOpenError"/>
    /// is the usual one here - the failure that brought the run down has often opened the
    /// breaker, which is why the caller resets it first.
    /// </summary>
    private IReadOnlyList<string> Restore(
        IReadOnlyList<LiveFeature> walk,
        bool[] snapshot,
        string configuration,
        IReadOnlyList<IrFeature> rows,
        bool resetBreaker)
    {
        if (resetBreaker)
        {
            _gate.Breaker.Reset();
        }

        var unrestored = new List<string>();
        for (int i = 0; i < walk.Count; i++)
        {
            int index = i;
            try
            {
                if (Suppression(walk[index], configuration) == snapshot[index])
                {
                    continue;
                }

                _gate.Call(
                    Member.SetSuppression,
                    () => _target.Suppress(walk[index].Handle, snapshot[index], configuration));

                if (Suppression(walk[index], configuration) != snapshot[index])
                {
                    unrestored.Add(rows[index].Id);
                }
            }
            catch (Exception)
            {
                // Every failure, not a list of the ones we thought of. A dead session raises
                // CircuitOpenError and COMException, but also SEHException,
                // InvalidComObjectException and RemotingException, none of which derives from
                // COMException; an escape from here escapes the run, and the caller would
                // then append no run and name no unrestored feature for a model it has
                // already modified. Naming the feature is the right answer to all of them:
                // "we could not confirm it" is what actually happened.
                unrestored.Add(rows[index].Id);
            }
        }

        return unrestored;
    }

    private bool Suppression(LiveFeature feature, string configuration) =>
        _gate.Call(Member.Suppressed, () => _target.IsSuppressed(feature.Handle, configuration));

    /// <summary>
    /// The live walk against the package rows, and the suppression snapshot the restore
    /// returns to. Any difference is a refusal: the rule reads the package's rows, so a run
    /// recorded against a tree that no longer matches them describes a different model.
    /// </summary>
    private bool[] Compare(
        IReadOnlyList<LiveFeature> walk,
        IReadOnlyList<IrFeature> rows,
        string configuration,
        string documentId)
    {
        if (walk.Count != rows.Count)
        {
            throw new SuppressTestRefusedError(
                $"The live feature tree has {walk.Count} feature(s) but the package's rows for "
                + $"{documentId} have {rows.Count}. Dump the package again before testing.");
        }

        var snapshot = new bool[walk.Count];
        for (int i = 0; i < walk.Count; i++)
        {
            LiveFeature feature = walk[i];
            IrFeature row = rows[i];

            if (_gate.Call(Member.RolledBack, () => _target.IsRolledBack(feature.Handle)))
            {
                throw new SuppressTestRefusedError(
                    $"'{feature.Name}' is rolled back. Roll the tree forward before testing: a "
                    + "rolled-back tree rebuilds only part of the model, so a clean rebuild "
                    + "would prove nothing.");
            }

            if (!string.Equals(feature.TypeName, row.TypeName, StringComparison.Ordinal))
            {
                throw new SuppressTestRefusedError(
                    $"Feature {i} is '{feature.Name}' of type '{feature.TypeName}' live but "
                    + $"'{row.Name}' of type '{row.TypeName}' in the package. Dump the package "
                    + "again before testing.");
            }

            if (!string.Equals(feature.Name, row.Name, StringComparison.Ordinal))
            {
                throw new SuppressTestRefusedError(
                    $"Feature {i} is '{feature.Name}' live but '{row.Name}' in the package. "
                    + "Dump the package again before testing.");
            }

            if (feature.Depth != row.Depth)
            {
                throw new SuppressTestRefusedError(
                    $"'{feature.Name}' is at depth {feature.Depth} live but depth {row.Depth} in "
                    + "the package. Dump the package again before testing.");
            }

            bool suppressed = _gate.Call(
                Member.Suppressed, () => _target.IsSuppressed(feature.Handle, configuration));
            snapshot[i] = suppressed;

            if (row.Suppressed == null)
            {
                throw new SuppressTestRefusedError(
                    $"The package does not record whether '{feature.Name}' is suppressed, so the "
                    + "live tree cannot be matched against it. Dump the package again before "
                    + "testing.");
            }

            if (suppressed != row.Suppressed.Value)
            {
                throw new SuppressTestRefusedError(
                    $"'{feature.Name}' is {(suppressed ? "suppressed" : "unsuppressed")} live but "
                    + $"{(row.Suppressed.Value ? "suppressed" : "unsuppressed")} in the package. "
                    + "Dump the package again before testing.");
            }
        }

        return snapshot;
    }

    /// <summary>
    /// Where each planned feature sits in the walk, checked by persistent identity. The
    /// package's row order is the map; <c>IsSamePersistentID</c> is what proves the row and
    /// the live feature are the same entity, because reference bytes are not comparable
    /// (research R12).
    /// </summary>
    private int[] PlannedIndexes(
        SuppressPlan plan, IReadOnlyList<IrFeature> rows, IReadOnlyList<LiveFeature> walk)
    {
        var indexes = new int[plan.Features.Count];
        for (int i = 0; i < plan.Features.Count; i++)
        {
            SuppressPlanFeature planned = plan.Features[i];
            int index = -1;
            for (int r = 0; r < rows.Count; r++)
            {
                if (string.Equals(rows[r].Id, planned.FeatureId, StringComparison.Ordinal))
                {
                    index = r;
                    break;
                }
            }

            if (index < 0)
            {
                throw new SuppressTestRefusedError(
                    $"The plan names {planned.FeatureId} ('{planned.Name}'), which the package's "
                    + $"rows for {plan.DocumentId} do not contain. Write the plan from the "
                    + "package you are testing against.");
            }

            if (!_target.IsSameFeature(planned.PersistRef, walk[index].Handle))
            {
                throw new SuppressTestRefusedError(
                    $"{planned.FeatureId} ('{planned.Name}') is not the same entity as the live "
                    + $"'{walk[index].Name}': the plan's persistent reference resolves to "
                    + "something else. Dump the package again and rewrite the plan.");
            }

            indexes[i] = index;
        }

        return indexes;
    }

    /// <summary>
    /// The package's rows for the plan's document, in index order. A document with no rows is
    /// refused rather than tested: there would be nothing to compare the live tree against.
    /// </summary>
    private static IReadOnlyList<IrFeature> RowsFor(
        string documentId, IReadOnlyList<IrFeature> packageFeatures)
    {
        List<IrFeature> rows = packageFeatures
            .Where(row => string.Equals(row.DocumentId, documentId, StringComparison.Ordinal))
            .OrderBy(row => row.Index)
            .ToList();

        if (rows.Count == 0)
        {
            throw new SuppressTestRefusedError(
                $"The package has no features[] rows for {documentId}. Dump the package with "
                + "--features tree first: the live tree is only testable against rows to "
                + "compare it with.");
        }

        return rows;
    }

    /// <summary>
    /// The run, with one row per planned feature already in place. Rows start as
    /// <c>aborted</c> (the DTO's default), so a run that dies mid-way describes every feature
    /// it never reached as untested rather than leaving it out of the table.
    /// </summary>
    private static SuppressTestRun NewRun(
        SuppressPlan plan, SuppressTestSettings settings, int baseline, DateTimeOffset startedAt)
    {
        var run = new SuppressTestRun
        {
            DocumentId = plan.DocumentId,
            Configuration = plan.Configuration,
            Group = plan.Group,
            PlanFile = settings.PlanFile,
            RunAt = startedAt,
            Acknowledged = true,
            BaselineWhatsWrongCount = baseline,
            Limit = settings.Limit,
            TimeoutSeconds = settings.TimeoutSeconds,
            FeaturesPresent = plan.Features.Count,
        };

        foreach (SuppressPlanFeature feature in plan.Features)
        {
            run.Rows.Add(new SuppressTestRow
            {
                FeatureId = feature.FeatureId,
                PersistRef = feature.PersistRef,
                PersistRefScope = feature.PersistRefScope,
                Name = feature.Name,
            });
        }

        return run;
    }

    private static int Count(SuppressTestRun run, SuppressTestOutcome outcome) =>
        run.Rows.Count(row => row.Outcome == outcome);

    private int Elapsed(DateTimeOffset since)
    {
        double ms = (_now() - since).TotalMilliseconds;
        return ms <= 0 ? 0 : (int)Math.Min(ms, int.MaxValue);
    }

    /// <summary>
    /// The interop members this class names to the gate. One place, so the guard, the
    /// observer and the tests cannot drift from the call sites - and so
    /// <see cref="SwSuppressTarget"/>, which asks the gate about the two mutating members at
    /// the interop call itself, names them from here rather than from a second copy.
    /// </summary>
    internal static class Member
    {
        public const string SaveFlag = "GetSaveFlag";
        public const string RolledBack = "IsRolledBack";
        public const string Suppressed = "IsSuppressed2";
        public const string SetSuppression = "SetSuppression2";
        public const string Rebuild = "ForceRebuild3";
        public const string WhatsWrongCount = "GetWhatsWrongCount";
        public const string WhatsWrong = "GetWhatsWrong";
    }
}
