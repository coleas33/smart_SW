using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SwReview.Extractor.Rms;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>What one scripted PROBE-1 reorder attempt does (<see cref="ParkingReorder"/>).</summary>
public enum ReorderAttempt
{
    /// <summary>Returns true, as a reorder SOLIDWORKS refused without a box would.</summary>
    Returns,

    /// <summary>Throws, with <see cref="ParkingReorder.HostMessage"/> as the host's own words.</summary>
    Throws,

    /// <summary>Never returns until the fake is disposed: a "Cannot reorder" box nobody answers.</summary>
    Parks,
}

/// <summary>
/// PROBE-1's <c>ReorderFeature</c>, scripted by the <c>CommandInProgress</c> flag each attempt sees,
/// with a block the test controls rather than a clock (013 contracts/readings.md section 4, 004 T171).
/// An attempt that parks records "attempt k parked" - a per-attempt task that completes the moment
/// it parks - and then waits on an event only <see cref="Dispose"/> sets. The test's watchdog
/// deadline for attempt k is that task (<see cref="Deadlines"/>): it fires exactly when attempt k
/// has parked, and never for an attempt that returns or throws, so no verdict waits on a timer and
/// none can be decided by the machine's load.
/// </summary>
public sealed class ParkingReorder : IDisposable
{
    /// <summary>The message an attempt that throws carries: the host's own words, which the ledger must keep.</summary>
    public const string HostMessage = "the host's own words: the reorder failed";

    private readonly FakeRemodelProbeHost _host;
    private readonly Func<bool, ReorderAttempt> _byFlag;
    private readonly ManualResetEventSlim _release = new ManualResetEventSlim(false);
    private readonly ConcurrentDictionary<int, TaskCompletionSource<bool>> _parked =
        new ConcurrentDictionary<int, TaskCompletionSource<bool>>();

    private int _attempts;
    private int _parkedNow;

    /// <summary>Scripts <paramref name="host"/>'s <c>ReorderFeature</c>: <paramref name="byFlag"/> is given the flag each attempt sees.</summary>
    public ParkingReorder(FakeRemodelProbeHost host, Func<bool, ReorderAttempt> byFlag)
    {
        _host = host ?? throw new ArgumentNullException(nameof(host));
        _byFlag = byFlag ?? throw new ArgumentNullException(nameof(byFlag));
        host.ReorderFeatureImpl = Reorder;
    }

    /// <summary>The <c>CommandInProgress</c> value each attempt saw, in the order the attempts ran.</summary>
    public ConcurrentQueue<bool> FlagSeenByAttempt { get; } = new ConcurrentQueue<bool>();

    /// <summary>How many attempts are parked at this moment.</summary>
    public int ParkedNow => Volatile.Read(ref _parkedNow);

    /// <summary>"Attempt <paramref name="attempt"/> parked" (0-based): completes once that attempt has parked, never otherwise.</summary>
    public Task Parked(int attempt) => Slot(attempt).Task;

    /// <summary>
    /// The watchdog deadline factory for a run whose attempts all go through this fake: the k-th
    /// deadline the watchdog asks for is <see cref="Parked"/>(k). The watchdog asks for one per
    /// attempt, in order, only once that attempt has begun.
    /// </summary>
    public Func<CancellationToken, Task> Deadlines()
    {
        int next = -1;
        return _ => Parked(Interlocked.Increment(ref next));
    }

    /// <summary>Releases every parked attempt, so no test leaves a thread behind it.</summary>
    public void Dispose() => _release.Set();

    private bool Reorder(RemodelProbePart part, string featureToMove, string targetFeature, int location)
    {
        int attempt = Interlocked.Increment(ref _attempts) - 1;
        bool flag = _host.CommandInProgress;
        FlagSeenByAttempt.Enqueue(flag);

        switch (_byFlag(flag))
        {
            case ReorderAttempt.Throws:
                throw new InvalidOperationException(HostMessage);
            case ReorderAttempt.Parks:
                Interlocked.Increment(ref _parkedNow);
                Slot(attempt).TrySetResult(true);
                _release.Wait();
                Interlocked.Decrement(ref _parkedNow);
                return true;
            default:
                return true;
        }
    }

    // Completed inline on the parked thread, so the watchdog waiting on it never waits for a pool thread.
    private TaskCompletionSource<bool> Slot(int attempt) =>
        _parked.GetOrAdd(attempt, _ => new TaskCompletionSource<bool>());
}

/// <summary>
/// A minimal, always-successful <see cref="IMassPropertyReading"/>. PROBE-8's tests use
/// <see cref="FakeMassProperty"/> (Fakes/RemodelFakes.cs) directly when they need to script
/// specific readings; this is only <see cref="FakeRemodelProbeHost"/>'s own out-of-the-box
/// default for tests that never call <c>MeasureMassProperties</c> at all.
/// </summary>
public delegate bool FakeGetCustomProperty(RemodelProbePart part, string key, out string? value, out string? resolvedValue);

/// <summary>
/// Every decision <c>probe remodel</c>'s bodies (tasks.md T033 to T039) can ask a host for,
/// scripted through public delegate properties with benign defaults - a test overrides only the
/// members its scenario actually cares about. Every call is recorded in <see cref="Calls"/> in
/// order, so a test can assert what a probe body did and did not touch.
/// </summary>
public sealed class FakeRemodelProbeHost : IRemodelProbeHost
{
    public List<string> Calls { get; } = new List<string>();

    private readonly Dictionary<int, bool> _toggles = new Dictionary<int, bool>();

    // ---- T031/T032's original four ------------------------------------------------------

    public Func<bool> AnyDocumentOpenImpl { get; set; } = () => false;

    public Func<string> SwVersionImpl { get; set; } = () => "32.5.0.48";

    public Func<RemodelProbePartRecipe, string, RemodelProbePart> BuildPartImpl { get; set; } =
        (recipe, savePath) => new RemodelProbePart(new object(), savePath, Array.Empty<object>());

    public Action<RemodelProbePart> ClosePartImpl { get; set; } = _ => { };

    public bool AnyDocumentOpen()
    {
        Calls.Add(nameof(AnyDocumentOpen));
        return AnyDocumentOpenImpl();
    }

    public string SwVersion()
    {
        Calls.Add(nameof(SwVersion));
        return SwVersionImpl();
    }

    public RemodelProbePart BuildPart(RemodelProbePartRecipe recipe, string savePath)
    {
        Calls.Add(nameof(BuildPart));
        return BuildPartImpl(recipe, savePath);
    }

    public void ClosePart(RemodelProbePart part)
    {
        Calls.Add(nameof(ClosePart));
        ClosePartImpl(part);
    }

    // ---- IRemodelToggleHost --------------------------------------------------------------

    public bool GetUserPreferenceToggle(int toggle)
    {
        Calls.Add(nameof(GetUserPreferenceToggle));
        return _toggles.TryGetValue(toggle, out bool value) && value;
    }

    public void SetUserPreferenceToggle(int toggle, bool value)
    {
        Calls.Add(nameof(SetUserPreferenceToggle));
        _toggles[toggle] = value;
    }

    /// <summary>
    /// Every value <see cref="SetCommandInProgress"/> was called with, in order - PROBE-1's own
    /// evidence that it flipped the flag clear, then set, around its two attempts.
    /// </summary>
    public List<bool> CommandInProgressHistory { get; } = new List<bool>();

    public bool CommandInProgress { get; set; }

    public bool GetCommandInProgress()
    {
        Calls.Add(nameof(GetCommandInProgress));
        return CommandInProgress;
    }

    public void SetCommandInProgress(bool value)
    {
        Calls.Add(nameof(SetCommandInProgress));
        CommandInProgress = value;
        CommandInProgressHistory.Add(value);
    }

    // ---- T033 to T039's additions ---------------------------------------------------------

    public Func<RemodelProbePart, string, string, int, bool> ReorderFeatureImpl { get; set; } = (part, move, target, location) => true;

    public bool ReorderFeature(RemodelProbePart part, string featureToMove, string targetFeature, int location)
    {
        Calls.Add(nameof(ReorderFeature));
        return ReorderFeatureImpl(part, featureToMove, targetFeature, location);
    }

    public Func<RemodelProbePart, IReadOnlyList<string>> GetFeatureNamesImpl { get; set; } =
        _ => new[] { "Boss-Extrude1", "Cut-Extrude1", "Fillet1", "Fillet1", "Shell1" };

    public IReadOnlyList<string> GetFeatureNames(RemodelProbePart part)
    {
        Calls.Add(nameof(GetFeatureNames));
        return GetFeatureNamesImpl(part);
    }

    public Func<RemodelProbePart, string, string?> GetFeatureTypeNameImpl { get; set; } = (part, name) => "Extrusion";

    public string? GetFeatureTypeName(RemodelProbePart part, string featureName)
    {
        Calls.Add(nameof(GetFeatureTypeName));
        return GetFeatureTypeNameImpl(part, featureName);
    }

    public Func<RemodelProbePart, string, string?> GetFeatureDescriptionImpl { get; set; } = (part, name) => string.Empty;

    public string? GetFeatureDescription(RemodelProbePart part, string featureName)
    {
        Calls.Add(nameof(GetFeatureDescription));
        return GetFeatureDescriptionImpl(part, featureName);
    }

    public Action<RemodelProbePart, string, string> SetFeatureDescriptionImpl { get; set; } = (part, name, text) => { };

    public void SetFeatureDescription(RemodelProbePart part, string featureName, string text)
    {
        Calls.Add(nameof(SetFeatureDescription));
        SetFeatureDescriptionImpl(part, featureName, text);
    }

    public Action<RemodelProbePart, string, string> SetFeatureNameImpl { get; set; } = (part, current, replacement) => { };

    public void SetFeatureName(RemodelProbePart part, string currentName, string newName)
    {
        Calls.Add(nameof(SetFeatureName));
        SetFeatureNameImpl(part, currentName, newName);
    }

    public Func<RemodelProbePart, IReadOnlyList<string>, object?> TryInsertFeatureTreeFolderImpl { get; set; } = (part, names) => new object();

    public object? TryInsertFeatureTreeFolder(RemodelProbePart part, IReadOnlyList<string> memberNames)
    {
        Calls.Add(nameof(TryInsertFeatureTreeFolder));
        return TryInsertFeatureTreeFolderImpl(part, memberNames);
    }

    public Func<RemodelProbePart, string, string, bool, bool> MoveToFolderImpl { get; set; } = (part, to, from, isFolder) => true;

    public bool MoveToFolder(RemodelProbePart part, string moveToFeatureOrFolder, string moveFromFeature, bool isFolder)
    {
        Calls.Add(nameof(MoveToFolder));
        return MoveToFolderImpl(part, moveToFeatureOrFolder, moveFromFeature, isFolder);
    }

    public Func<RemodelProbePart, string, string, bool> MakeSubFeatureImpl { get; set; } = (part, parent, sub) => true;

    public bool MakeSubFeature(RemodelProbePart part, string parentFeatureName, string subFeatureName)
    {
        Calls.Add(nameof(MakeSubFeature));
        return MakeSubFeatureImpl(part, parentFeatureName, subFeatureName);
    }

    public Func<RemodelProbePart, IEquationTarget> GetEquationManagerImpl { get; set; } = _ => new FakeEquationManager();

    public IEquationTarget GetEquationManager(RemodelProbePart part)
    {
        Calls.Add(nameof(GetEquationManager));
        return GetEquationManagerImpl(part);
    }

    public Func<RemodelProbePart, int, double> GetEquationValueImpl { get; set; } = (part, index) => 120.0;

    public double GetEquationValue(RemodelProbePart part, int index)
    {
        Calls.Add(nameof(GetEquationValue));
        return GetEquationValueImpl(part, index);
    }

    public Func<RemodelProbePart, string, bool, bool> SetFeatureSuppressionImpl { get; set; } = (part, name, suppress) => true;

    public bool SetFeatureSuppression(RemodelProbePart part, string featureName, bool suppress)
    {
        Calls.Add(nameof(SetFeatureSuppression));
        return SetFeatureSuppressionImpl(part, featureName, suppress);
    }

    public Func<RemodelProbePart, bool> ForceRebuildImpl { get; set; } = _ => true;

    public bool ForceRebuild(RemodelProbePart part)
    {
        Calls.Add(nameof(ForceRebuild));
        return ForceRebuildImpl(part);
    }

    public Func<RemodelProbePart, RemodelWhatsWrongReading> ReadWhatsWrongImpl { get; set; } =
        _ => new RemodelWhatsWrongReading(0, true, "empty");

    public RemodelWhatsWrongReading ReadWhatsWrong(RemodelProbePart part)
    {
        Calls.Add(nameof(ReadWhatsWrong));
        return ReadWhatsWrongImpl(part);
    }

    public Func<RemodelProbePart, string, string, int> AddCustomPropertyImpl { get; set; } = (part, key, value) => 0;

    public int AddCustomProperty(RemodelProbePart part, string key, string value)
    {
        Calls.Add(nameof(AddCustomProperty));
        return AddCustomPropertyImpl(part, key, value);
    }

    public FakeGetCustomProperty GetCustomPropertyImpl { get; set; } =
        (RemodelProbePart part, string key, out string? value, out string? resolvedValue) =>
        {
            value = null;
            resolvedValue = null;
            return false;
        };

    public bool GetCustomProperty(RemodelProbePart part, string key, out string? value, out string? resolvedValue)
    {
        Calls.Add(nameof(GetCustomProperty));
        return GetCustomPropertyImpl(part, key, out value, out resolvedValue);
    }

    public Func<RemodelProbePart, bool> SaveExistingPartImpl { get; set; } = _ => true;

    public bool SaveExistingPart(RemodelProbePart part)
    {
        Calls.Add(nameof(SaveExistingPart));
        return SaveExistingPartImpl(part);
    }

    public Func<string, RemodelProbePart> ReopenPartImpl { get; set; } =
        path => new RemodelProbePart(new object(), path, Array.Empty<object>());

    public RemodelProbePart ReopenPart(string path)
    {
        Calls.Add(nameof(ReopenPart));
        return ReopenPartImpl(path);
    }

    public Func<object> BuildBlankDocumentImpl { get; set; } = () => new object();

    public object BuildBlankDocument()
    {
        Calls.Add(nameof(BuildBlankDocument));
        return BuildBlankDocumentImpl();
    }

    public Func<object, int> GetEquationCountImpl { get; set; } = _ => 0;

    public int GetEquationCount(object blankDocument)
    {
        Calls.Add(nameof(GetEquationCount));
        return GetEquationCountImpl(blankDocument);
    }

    public Action<object> DiscardBlankDocumentImpl { get; set; } = _ => { };

    public void DiscardBlankDocument(object blankDocument)
    {
        Calls.Add(nameof(DiscardBlankDocument));
        DiscardBlankDocumentImpl(blankDocument);
    }

    public Func<AnalyticSolidSpec, string, RemodelProbePart> BuildAnalyticSolidImpl { get; set; } =
        (spec, savePath) => new RemodelProbePart(new object(), savePath, Array.Empty<object>());

    public RemodelProbePart BuildAnalyticSolid(AnalyticSolidSpec spec, string savePath)
    {
        Calls.Add(nameof(BuildAnalyticSolid));
        return BuildAnalyticSolidImpl(spec, savePath);
    }

    public Func<RemodelProbePart, IMassPropertyReading?> MeasureMassPropertiesImpl { get; set; } = _ => new FakeMassProperty();

    public IMassPropertyReading? MeasureMassProperties(RemodelProbePart part)
    {
        Calls.Add(nameof(MeasureMassProperties));
        return MeasureMassPropertiesImpl(part);
    }
}
