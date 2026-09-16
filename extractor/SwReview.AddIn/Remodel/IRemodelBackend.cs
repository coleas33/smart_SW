using System;
using System.Collections.Generic;
using SwReview.AddIn.Review;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel;

/// <summary>`POST /remodel/probe`: the read-only look at the engineer's open source.</summary>
public sealed class RemodelProbeRequest
{
    public RemodelProbeRequest(string sourcePath, string? configuration, BridgeConfig bridge)
    {
        SourcePath = sourcePath ?? throw new ArgumentNullException(nameof(sourcePath));
        Configuration = configuration;
        Bridge = bridge ?? throw new ArgumentNullException(nameof(bridge));
    }

    public string SourcePath { get; }

    public string? Configuration { get; }

    /// <summary>`{pipe, secret}`, the remodel half. In the body, never in the URL.</summary>
    public BridgeConfig Bridge { get; }
}

/// <summary>What the probe measured and what the pure gate made of it.</summary>
public sealed class RemodelProbeReply
{
    public RemodelProbeReply(string probeId, ScopeSignals signals, IReadOnlyList<string> refusals)
    {
        ProbeId = probeId ?? throw new ArgumentNullException(nameof(probeId));
        Signals = signals ?? throw new ArgumentNullException(nameof(signals));
        Refusals = refusals ?? throw new ArgumentNullException(nameof(refusals));
    }

    /// <summary>
    /// The token `remodel.open` must quote back. The bridge mints it for one source path and
    /// refuses an open that names another (`contracts/bridge-remodel.md`, `scope_not_probed`).
    /// </summary>
    public string ProbeId { get; }

    public ScopeSignals Signals { get; }

    /// <summary>Every failing signal's sentence; empty is the only "ok".</summary>
    public IReadOnlyList<string> Refusals { get; }
}

/// <summary>`POST /remodel/open`: copy, open, tag, roll and rebuild, in the bridge.</summary>
public sealed class RemodelOpenRequest
{
    public RemodelOpenRequest(
        string runDirectory,
        string sourcePath,
        string? configuration,
        string? probeId,
        BridgeConfig bridge)
    {
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        SourcePath = sourcePath ?? throw new ArgumentNullException(nameof(sourcePath));
        Configuration = configuration;
        ProbeId = probeId;
        Bridge = bridge ?? throw new ArgumentNullException(nameof(bridge));
    }

    public string RunDirectory { get; }

    /// <summary>The last request in this feature that names the engineer's file.</summary>
    public string SourcePath { get; }

    public string? Configuration { get; }

    /// <summary>From the probe that preceded this open, or null when there was none.</summary>
    public string? ProbeId { get; }

    public BridgeConfig Bridge { get; }
}

/// <summary>The copy, and the baseline reading the run is attributed against.</summary>
public sealed class RemodelOpenReply
{
    public RemodelOpenReply(string copyPath, int? rebuildErrorCount, bool copyPresent)
    {
        CopyPath = copyPath ?? throw new ArgumentNullException(nameof(copyPath));
        RebuildErrorCount = rebuildErrorCount;
        CopyPresent = copyPresent;
    }

    public string CopyPath { get; }

    /// <summary>Null is unknown, never zero: a baseline that could not be read is not a clean
    /// part, and the host refuses the run on it.</summary>
    public int? RebuildErrorCount { get; }

    /// <summary>
    /// False when the bridge refused with `preexisting_rebuild_errors`: it has already deleted
    /// the copy and closed the document, and the count is what it read before it did.
    /// </summary>
    public bool CopyPresent { get; }
}

/// <summary>`POST /remodel/runs`: phases B to D, on a worker thread in the backend.</summary>
public sealed class RemodelRunRequest
{
    public RemodelRunRequest(string runDirectory, BridgeConfig bridge)
    {
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        Bridge = bridge ?? throw new ArgumentNullException(nameof(bridge));
    }

    public string RunDirectory { get; }

    public BridgeConfig Bridge { get; }
}

/// <summary>The change the executor is inside, as `remodel.progress` reports it.</summary>
public sealed class RemodelRunCurrent
{
    public RemodelRunCurrent(int seq, string kind, string? subjectName)
    {
        Seq = seq;
        Kind = kind ?? throw new ArgumentNullException(nameof(kind));
        SubjectName = subjectName;
    }

    public int Seq { get; }

    public string Kind { get; }

    /// <summary>Recorded for the report; nothing is ever addressed by it.</summary>
    public string? SubjectName { get; }
}

/// <summary>`GET /remodel/runs/{job_id}`: where the run has got to.</summary>
public sealed class RemodelRunStatus
{
    /// <summary>The job is on its worker thread.</summary>
    public const string RunningState = "running";

    /// <summary>The job is blocked on the add-in's `package-after.json` dump.</summary>
    public const string AwaitingState = "awaiting_package_after";

    public const string FinishedState = "finished";

    public const string FailedState = "failed";

    /// <summary>The only value `awaiting` takes when it is not null.</summary>
    public const string PackageAfterAwaiting = "package_after";

    public RemodelRunStatus(
        string state,
        string? planState,
        int changesTotal,
        int changesApplied,
        RemodelRunCurrent? current,
        string? awaiting,
        string? error)
    {
        State = state ?? throw new ArgumentNullException(nameof(state));
        PlanState = planState;
        ChangesTotal = changesTotal;
        ChangesApplied = changesApplied;
        Current = current;
        Awaiting = awaiting;
        Error = error;
    }

    /// <summary>The job's state: running, awaiting_package_after, finished or failed.</summary>
    public string State { get; }

    /// <summary>
    /// `plan.json`'s `RunState` (data-model.md section 11), or null when the file does not say.
    /// Null stays null: a run that finished without recording what it finished in is not a run
    /// that saved.
    /// </summary>
    public string? PlanState { get; }

    public int ChangesTotal { get; }

    public int ChangesApplied { get; }

    public RemodelRunCurrent? Current { get; }

    /// <summary>`package_after` while the backend waits for the dump, else null.</summary>
    public string? Awaiting { get; }

    /// <summary>Why the job failed, or null.</summary>
    public string? Error { get; }
}

/// <summary>One page of `events.jsonl`, as the chat event stream holds it.</summary>
public sealed class RemodelEventPage
{
    public RemodelEventPage(IReadOnlyList<string> events, int next)
    {
        Events = events ?? throw new ArgumentNullException(nameof(events));
        Next = next;
    }

    /// <summary>One JSON object per event, exactly as the file holds it.</summary>
    public IReadOnlyList<string> Events { get; }

    /// <summary>The cursor for the next call.</summary>
    public int Next { get; }
}

/// <summary>`POST /remodel/close`: `CloseDoc` on the copy, through the bridge.</summary>
public sealed class RemodelCloseRequest
{
    public RemodelCloseRequest(string runDirectory, BridgeConfig bridge, bool discardCopy)
    {
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        Bridge = bridge ?? throw new ArgumentNullException(nameof(bridge));
        DiscardCopy = discardCopy;
    }

    public string RunDirectory { get; }

    public BridgeConfig Bridge { get; }

    /// <summary>
    /// Always false from this add-in: <see cref="RemodelHost"/> is the one deleter of `copy/`,
    /// so a second deleter on the Python side would be a second chance to delete the wrong
    /// folder.
    /// </summary>
    public bool DiscardCopy { get; }
}

/// <summary>
/// The loopback backend's remodel routes, behind one seam
/// (`specs/004-resilient-remodeler/contracts/backend-remodel.md`).
///
/// One member per route, and the split is the wiring brief's: every `remodel.*` bridge call is
/// made by Python, through the one client that already exists and the one holder of the remodel
/// secret, and the add-in makes two in-process dumps, one seat action and these HTTP calls. The
/// seam exists so <see cref="BackendRemodelPipeline"/> - which is where the order of the run
/// lives - is testable with no Python, no socket and no SOLIDWORKS.
///
/// Every failure arrives as <see cref="BackendRequestException"/> carrying the backend's own
/// `{error_class, message, retryable}`, the way <see cref="IBackendClient"/>'s failures do.
/// </summary>
public interface IRemodelBackend
{
    /// <summary>`POST /remodel/probe`. Reads the source; copies nothing.</summary>
    RemodelProbeReply Probe(RemodelProbeRequest request);

    /// <summary>`POST /remodel/open`. The copy, and the attestation written beside it.</summary>
    RemodelOpenReply Open(RemodelOpenRequest request);

    /// <summary>
    /// `POST /remodel/plan`. Reads `package-before.json` out of the run folder - which the
    /// add-in wrote - and returns `plan_summary` as JSON, passed to the page untouched.
    /// </summary>
    string Plan(string runDirectory);

    /// <summary>`POST /remodel/runs`. Returns the job id, which is also the chat id.</summary>
    string StartRun(RemodelRunRequest request);

    /// <summary>`GET /remodel/runs/{job_id}`.</summary>
    RemodelRunStatus Status(string jobId);

    /// <summary>
    /// `GET /remodel/runs/{job_id}/events?after=N`. The agent's event stream, the same shape a
    /// review's is; the Remodel page reads it with the token and origin its `init` carries, and
    /// this member is how anything on the add-in's side of the process reaches it.
    /// </summary>
    RemodelEventPage Events(string jobId, int after);

    /// <summary>
    /// `POST /remodel/runs/{job_id}/package-after`. The rendezvous: the backend is blocked
    /// until the add-in has dumped the copy and named the file.
    /// </summary>
    void PackageAfter(string jobId, string packagePath);

    /// <summary>`POST /remodel/runs/{job_id}/stop`. Idempotent.</summary>
    void Stop(string jobId);

    /// <summary>`POST /remodel/close`. A copy that is not open is a no-op.</summary>
    void Close(RemodelCloseRequest request);
}
