using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// The real <see cref="IRemodelPipeline"/>: what the Remodel tab does with a live backend and a
/// live seat.
///
/// It is thin, and the division of labour behind that is the wiring brief's:
///
/// <b>Every `remodel.*` bridge call is Python's.</b> The copy, the tag, the rollback, every
/// write to the feature tree and the close all happen on the other side of the loopback, through
/// the one client that already exists and the one holder of the remodel secret. This class makes
/// HTTP calls; it holds no bridge connection and no secret of its own.
///
/// <b>The two `package.json` dumps are the add-in's.</b> `package-before.json` and
/// `package-after.json` are written by the in-process extractor, on the application thread,
/// against the document SOLIDWORKS already has open (`contracts/run-artifacts.md`): the
/// extractor needs the STA thread and the <c>ISldWorks</c> this process holds, and a second
/// attach could bind a different session.
///
/// <b>Planning, judgement, apply, verify and grading are Python's.</b> They are pure functions
/// over the package and the plan, and none of them is in this process.
///
/// <b>The order of the messages is the host's.</b> This class reports; it never decides a
/// refusal's precedence, never deletes the copy folder and never replies to the page.
///
/// So what is left here is the run's shape: probe, copy, dump, plan, start, poll, hand the
/// change lines over as they are written, dump again when the backend asks for the after
/// reading, and stop when the engineer says so. Each of those is asserted in
/// `BackendRemodelPipelineTests`, which is why they are here and not spread across the host.
///
/// <b>The source is named once.</b> <see cref="OpenCopy"/> passes the path on as the source of a
/// filesystem copy and nothing after it names the source again - not the plan, not the run, not
/// the close, not the seat. There is no call to make, so there is no call to get wrong
/// (constitution, Technical Constraints: the re-modeler exception).
/// </summary>
public sealed class BackendRemodelPipeline : IRemodelPipeline
{
    /// <summary>The copy's tree at open, which is the source's tree (run-artifacts.md).</summary>
    public const string PackageBeforeName = RunFolders.PackageBeforeName;

    /// <summary>The copy's tree after the last change.</summary>
    public const string PackageAfterName = "package-after.json";

    /// <summary>The change log, tailed so the page's list grows as the file does.</summary>
    private const string ChangesFileName = "changes.jsonl";

    /// <summary>
    /// Long enough that a twenty-minute run does not cost thousands of requests, short enough
    /// that the change list looks live and a stop is acted on while the engineer is still
    /// looking at the button.
    /// </summary>
    private static readonly TimeSpan DefaultPollDelay = TimeSpan.FromMilliseconds(500);

    /// <summary>
    /// `plan.json`'s `RunState` (data-model.md section 11) as one of the `status` stages the
    /// page knows (`contracts/pane-remodel-messages.md`). A state that is not here posts no
    /// stage at all: `failed` and `discarded` are terminal, and announcing "error" from inside
    /// the poll loop would race the host's own closing status.
    /// </summary>
    private static readonly Dictionary<string, string> StageForPlanState =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "planned", "judging" },
            { "judging", "judging" },
            { "applying", "applying" },
            { "verifying", "verifying" },
            { "saved", "saving" },
            { "truncated", "saving" },
        };

    /// <summary>What the engineer reads while each stage runs.</summary>
    private static readonly Dictionary<string, string> StageMessages =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "judging", "Asking the model to name and describe the features..." },
            { "applying", "Applying the plan to the copy..." },
            { "verifying", "Verifying the copy against the baseline..." },
            { "saving", "Saving the copy..." },
        };

    private readonly Func<BackendEndpoint?> _endpoint;
    private readonly Func<BridgeConfig?> _remodelBridge;
    private readonly Func<PageDocument?> _currentDocument;
    private readonly IReviewDump _dump;
    private readonly IRemodelSeat _seat;
    private readonly IRemodelBackend _backend;
    private readonly TimeSpan _pollDelay;

    /// <summary>
    /// The probe the bridge last minted, quoted back by <see cref="OpenCopy"/>. The bridge
    /// refuses an open whose probe it did not mint for that exact source
    /// (`contracts/bridge-remodel.md`, `scope_not_probed`), which is what makes "the scope was
    /// checked" a fact rather than a claim by the caller.
    /// </summary>
    private string? _probeId;

    /// <param name="endpoint">The backend's endpoint, read fresh: `settings.save` restarts the
    /// child on a new port.</param>
    /// <param name="remodelBridge">`{pipe, secret}` for the remodel half of the tool service, or
    /// null before it is listening.</param>
    /// <param name="currentDocument">The active document, asked for fresh; SOLIDWORKS owns the
    /// answer. Read by <see cref="ProbeScope"/> and by nothing after it.</param>
    /// <param name="dump">The in-process extractor, for the two ModelCheck dumps.</param>
    /// <param name="seat">`remodel.open_copy`, on the application thread.</param>
    /// <param name="backend">The loopback routes.</param>
    /// <param name="pollDelay">How long between two `GET`s of the run. Injected so the tests
    /// are not slow; defaults to half a second.</param>
    public BackendRemodelPipeline(
        Func<BackendEndpoint?> endpoint,
        Func<BridgeConfig?> remodelBridge,
        Func<PageDocument?> currentDocument,
        IReviewDump dump,
        IRemodelSeat seat,
        IRemodelBackend backend,
        TimeSpan? pollDelay = null)
    {
        _endpoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
        _remodelBridge = remodelBridge ?? throw new ArgumentNullException(nameof(remodelBridge));
        _currentDocument = currentDocument ?? throw new ArgumentNullException(nameof(currentDocument));
        _dump = dump ?? throw new ArgumentNullException(nameof(dump));
        _seat = seat ?? throw new ArgumentNullException(nameof(seat));
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        _pollDelay = pollDelay ?? DefaultPollDelay;
    }

    public RemodelScopeReading ProbeScope()
    {
        RequireBackend();
        BridgeConfig bridge = RequireBridge();
        PageDocument document = _currentDocument() ?? throw new RemodelRefusal(
            "NoDocument",
            "open the part you want reorganized in SOLIDWORKS first: the re-modeler copies the "
            + "active document.",
            retryable: true);

        try
        {
            RemodelProbeReply reply = _backend.Probe(
                new RemodelProbeRequest(document.Path, document.Configuration, bridge));
            _probeId = reply.ProbeId;
            return new RemodelScopeReading(reply.Signals, reply.Refusals);
        }
        catch (BackendRequestException failure)
        {
            throw Refusal(failure);
        }
    }

    public RemodelCopyReading OpenCopy(RemodelCopyRequest request, IRemodelRunReporter reporter)
    {
        if (request == null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        if (reporter == null)
        {
            throw new ArgumentNullException(nameof(reporter));
        }

        RequireBackend();
        BridgeConfig bridge = RequireBridge();
        reporter.Status(
            "copying",
            $"Copying {Path.GetFileName(request.SourcePath)} into the run folder...");

        try
        {
            RemodelOpenReply reply = _backend.Open(new RemodelOpenRequest(
                request.RunDirectory, request.SourcePath, request.Configuration, _probeId, bridge));

            // `copy_present: false` is the bridge's `preexisting_rebuild_errors`: it has already
            // deleted the copy and closed the document, and the count it read comes back with
            // it. Both travel, so the host takes its existing refusal path on either: the count
            // alone cannot carry "the copy is gone", because 0 is a count the refusal's detail
            // may well have said.
            return new RemodelCopyReading(
                reply.CopyPath, reply.RebuildErrorCount, reply.CopyPresent);
        }
        catch (BackendRequestException failure)
        {
            throw Refusal(failure);
        }
    }

    public void CloseCopy(string runDirectory)
    {
        // Called on the host's way to deleting `copy/`, including on paths where the backend
        // never started or the tool service never attached. There is nothing open to close in
        // either case, and the folder is what the engineer asked to be rid of: a close that
        // cannot be made must not stop the delete.
        BridgeConfig? bridge = _remodelBridge();
        if (_endpoint() == null || bridge == null)
        {
            return;
        }

        try
        {
            _backend.Close(new RemodelCloseRequest(runDirectory, bridge, discardCopy: false));
        }
        catch (BackendRequestException failure)
        {
            throw Refusal(failure);
        }
    }

    public string Plan(string runDirectory, IRemodelRunReporter reporter)
    {
        if (reporter == null)
        {
            throw new ArgumentNullException(nameof(reporter));
        }

        // Before the dump, not after it: a dump occupies the application thread for as long as
        // the part takes, and a backend that is not listening is knowable now.
        RequireBackend();

        reporter.Status("dumping", "Reading the copy's feature tree...");
        DumpInto(runDirectory, PackageBeforeName, "dumping", reporter);

        reporter.Status("planning", "Planning the reorganization...");
        try
        {
            return _backend.Plan(runDirectory);
        }
        catch (BackendRequestException failure)
        {
            throw Refusal(failure);
        }
    }

    public RemodelRunOutcome Run(string runDirectory, IRemodelRunReporter reporter)
    {
        if (reporter == null)
        {
            throw new ArgumentNullException(nameof(reporter));
        }

        RequireBackend();
        BridgeConfig bridge = RequireBridge();

        string jobId;
        try
        {
            jobId = _backend.StartRun(new RemodelRunRequest(runDirectory, bridge));
        }
        catch (BackendRequestException failure)
        {
            // `RunNotPlanned`, `ResumeRefused` and `RunInProgress` are refusals the page has a
            // name for, not a failed run: nothing was started, so nothing ended.
            throw Refusal(failure);
        }

        return Poll(runDirectory, jobId, reporter);
    }

    public void ActivateCopy(string runDirectory)
    {
        _seat.ActivateOrOpen(CopyIn(runDirectory));
    }

    // ---- the poll loop -----------------------------------------------------------------------

    private RemodelRunOutcome Poll(
        string runDirectory, string jobId, IRemodelRunReporter reporter)
    {
        int relayed = 0;
        int applied = 0;
        int postedApplied = -1;
        int postedSeq = -1;
        string? stage = null;
        bool stopped = false;
        bool dumped = false;

        while (true)
        {
            RemodelRunStatus status;
            try
            {
                status = _backend.Status(jobId);
            }
            catch (BackendRequestException failure)
            {
                // The backend is the only thing that knows how the run ended. With it gone the
                // run is over and unattributable, which is `failed`; the change log on disk is
                // what is left, and it is intact.
                reporter.Status("error", failure.Message);
                return new RemodelRunOutcome("failed", applied);
            }

            applied = status.ChangesApplied;
            relayed += Relay(runDirectory, relayed, reporter);

            if (status.State == RemodelRunStatus.FinishedState
                || status.State == RemodelRunStatus.FailedState)
            {
                return Ended(status, applied, reporter);
            }

            string? next = Stage(status.PlanState);
            if (next != null && next != stage)
            {
                stage = next;
                reporter.Status(next, StageMessages[next]);
            }

            if (status.Current != null
                && (status.ChangesApplied != postedApplied || status.Current.Seq != postedSeq))
            {
                postedApplied = status.ChangesApplied;
                postedSeq = status.Current.Seq;
                reporter.Progress(
                    status.ChangesApplied,
                    status.ChangesTotal,
                    status.Current.Seq,
                    status.Current.Kind,
                    status.Current.SubjectName);
            }

            // Once. The backend's stop is idempotent, but a stop posted on every poll would be
            // a request per half second for as long as the change in flight takes to finalize.
            if (!stopped && reporter.StopRequested)
            {
                try
                {
                    _backend.Stop(jobId);
                    stopped = true;
                }
                catch (BackendRequestException)
                {
                    // A stop that could not be posted has not happened, and the run it belongs
                    // to is still healthy: the executor is applying changes to the copy either
                    // way. Ending the run here would report "failed, 0 changes" while the
                    // backend is still applying them, and leave the folder blocked as
                    // `RunInProgress` when the engineer pressed Start again. So `stopped` stays
                    // false and the next poll posts it again, which the route's idempotence
                    // makes free.
                }
            }

            if (!dumped && status.Awaiting == RemodelRunStatus.PackageAfterAwaiting)
            {
                // The rendezvous: the backend is blocked until this dump lands, so it is made
                // now and the run is asked again immediately rather than after a poll delay.
                stage = "verifying";
                reporter.Status("verifying", "Reading the copy's feature tree after the changes...");
                string package = DumpInto(runDirectory, PackageAfterName, "verifying", reporter);
                try
                {
                    _backend.PackageAfter(jobId, package);
                }
                catch (BackendRequestException failure)
                {
                    // `PackageAfterRefused` is a class of its own in the route's error table.
                    // Unwrapped it would leave this loop as a raw request failure, reach the
                    // host's generic catch and be shown as `HostError` - the one thing
                    // `RemodelRefusal` exists to prevent.
                    throw Refusal(failure);
                }

                dumped = true;
                continue;
            }

            if (_pollDelay > TimeSpan.Zero)
            {
                Thread.Sleep(_pollDelay);
            }
        }
    }

    /// <summary>
    /// What the host is told the run ended as.
    ///
    /// The state comes from `plan.json` through the backend, because `plan.json` is what
    /// `remodel.result` will read afterwards; a state this class decided for itself could
    /// disagree with the file the engineer opens. A job that ended without one is reported
    /// <c>failed</c> and says so: a run that did not record what it finished in is not a run
    /// that saved (constitution Principle I - a missing input stays unknown and is never read
    /// favourably).
    /// </summary>
    private static RemodelRunOutcome Ended(
        RemodelRunStatus status, int applied, IRemodelRunReporter reporter)
    {
        if (status.State == RemodelRunStatus.FailedState && !string.IsNullOrEmpty(status.Error))
        {
            reporter.Status("error", status.Error!);
        }

        if (string.IsNullOrEmpty(status.PlanState))
        {
            reporter.Status(
                "error",
                "the run ended without writing a state to plan.json, so what it did to the copy "
                + "cannot be stated. The change log in the run folder is what it left.");
            return new RemodelRunOutcome("failed", applied);
        }

        return new RemodelRunOutcome(status.PlanState!, applied);
    }

    private static string? Stage(string? planState) =>
        planState != null && StageForPlanState.TryGetValue(planState, out string? stage)
            ? stage
            : null;

    /// <summary>
    /// Hands every `changes.jsonl` line written since the last poll to the reporter, in order,
    /// and returns how many were handed over.
    ///
    /// Verbatim and once each: the page reads each line as a `ChangeRecord`, so a line reshaped
    /// here is a record it cannot read and a line relayed twice is a duplicate row in the change
    /// list. A trailing fragment with no newline is <b>not</b> relayed - the writer appends the
    /// record and its newline in one call, but a reader can still arrive mid-write, and half a
    /// record is not a record.
    /// </summary>
    private static int Relay(string runDirectory, int relayed, IRemodelRunReporter reporter)
    {
        string path = Path.Combine(runDirectory, ChangesFileName);
        string text;
        try
        {
            if (!File.Exists(path))
            {
                return 0;
            }

            using (var file = new FileStream(
                path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(file, Encoding.UTF8))
            {
                text = reader.ReadToEnd();
            }
        }
        catch (IOException)
        {
            // The writer has it for a moment. The lines are still there on the next poll.
            return 0;
        }

        int relayedNow = 0;
        int seen = 0;
        int start = 0;
        for (int index = 0; index < text.Length; index++)
        {
            if (text[index] != '\n')
            {
                continue;
            }

            string line = text.Substring(start, index - start).Trim();
            start = index + 1;
            if (line.Length == 0)
            {
                continue;
            }

            seen++;
            if (seen > relayed)
            {
                reporter.Change(line);
                relayedNow++;
            }
        }

        return relayedNow;
    }

    // ---- the dumps ---------------------------------------------------------------------------

    /// <summary>
    /// One in-process ModelCheck dump of the copy, renamed to the name the run artifacts use.
    ///
    /// The rename is a plain move because a ModelCheck package is one file - the profile skips
    /// meshes and captures (`Dump/DumpContracts.cs`) - so there is nothing beside it to leave
    /// behind. The profile is read back <b>out of the file that was written</b> rather than
    /// assumed from the argument that was passed: a full package renamed to
    /// `package-before.json` would be a different reading of the part, and the plan built from
    /// it would be a plan for that other reading.
    ///
    /// <b>And so is the document it read.</b> The dump attaches to whatever document
    /// SOLIDWORKS has active; nothing here selects one, and the engineer's own source is still
    /// open in another tab throughout - including minutes later, at the after-dump. Which
    /// document was read is knowable only from the file that was written, so it is read out of
    /// it and refused unless it is the copy this run made.
    /// </summary>
    private string DumpInto(
        string runDirectory, string fileName, string stage, IRemodelRunReporter reporter)
    {
        DumpSummary summary = _dump.Run(
            runDirectory, line => reporter.Status(stage, line), DumpProfile.ModelCheck);

        string written = summary.PackageFilePath;
        DumpProfile? profile = PackageIndex.HeadOf(
            Path.GetDirectoryName(written) ?? runDirectory).Profile;
        if (profile != DumpProfile.ModelCheck)
        {
            throw new InvalidOperationException(
                $"'{written}' records "
                + (profile == null
                    ? "no readable extractor profile"
                    : "the '" + PackageSerializer.EnumToJsonName(profile.Value) + "' profile")
                + $", so it cannot be used as '{fileName}': the remodel run reads a "
                + "'model_check' package and a package written by another profile is a "
                + "different reading of the part.");
        }

        RequireItReadTheCopy(written, runDirectory, fileName);

        string target = Path.Combine(runDirectory, fileName);
        if (File.Exists(target))
        {
            // A re-run in the same folder. The file being replaced is this run's own earlier
            // attempt; the plan and the change log beside it are untouched.
            File.Delete(target);
        }

        File.Move(written, target);
        return target;
    }

    /// <summary>
    /// Refuses a dump that is not a reading of this run's copy, before it can be renamed into a
    /// run artifact.
    ///
    /// The check is the copy folder rather than one exact file name, because the copy's name is
    /// the bridge's to choose and `&lt;run_dir&gt;/copy/` is the one folder this run created:
    /// the engineer's source is never inside it, and it is the whole of what the host deletes.
    ///
    /// A package that names no document is refused too. It says nothing about what it read, and
    /// unknown is not the copy (constitution Principle I).
    ///
    /// <b>The path that was read is not in the message.</b> It may be the source, and nothing
    /// after the copy may name the source - not even in prose on the page. The package stays in
    /// the run folder unrenamed, which is where the evidence for this refusal belongs.
    /// </summary>
    private static void RequireItReadTheCopy(
        string written, string runDirectory, string fileName)
    {
        string copyFolder = Path.GetFullPath(Path.Combine(
            runDirectory, SwReview.Extractor.Rms.RemodelCopy.CopyFolderName));
        string? read = FolderOfDocumentIn(written);

        if (read == null || !string.Equals(read, copyFolder, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"the dump written for '{fileName}' "
                + (read == null
                    ? "names no document, so which document it read cannot be established"
                    : $"names a document that is not in '{copyFolder}'")
                + $", so it is not a reading of this run's copy. '{runDirectory}' keeps the "
                + "package it wrote as the evidence; the path it named is not repeated here, "
                + "because nothing after the copy may name the source.");
        }
    }

    /// <summary>
    /// The folder holding `documents[0].path` of a written package, or null when the file says
    /// nothing readable about what it read.
    ///
    /// Null for every unreadable shape rather than a throw per shape: every one of them means
    /// the same thing to the one caller - the document is unknown - and unknown is refused
    /// there, by name, once.
    /// </summary>
    private static string? FolderOfDocumentIn(string packagePath)
    {
        string? documentPath;
        try
        {
            using (var file = new FileStream(
                packagePath, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (JsonDocument package = JsonDocument.Parse(file))
            {
                if (package.RootElement.ValueKind != JsonValueKind.Object
                    || !package.RootElement.TryGetProperty("documents", out JsonElement documents)
                    || documents.ValueKind != JsonValueKind.Array
                    || documents.GetArrayLength() == 0)
                {
                    return null;
                }

                JsonElement first = documents[0];
                if (first.ValueKind != JsonValueKind.Object
                    || !first.TryGetProperty("path", out JsonElement path)
                    || path.ValueKind != JsonValueKind.String)
                {
                    return null;
                }

                documentPath = path.GetString();
            }
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
        catch (JsonException)
        {
            return null;
        }

        if (string.IsNullOrWhiteSpace(documentPath))
        {
            return null;
        }

        try
        {
            string? folder = Path.GetDirectoryName(documentPath);
            return string.IsNullOrEmpty(folder) ? null : Path.GetFullPath(folder!);
        }
        catch (ArgumentException)
        {
            return null;
        }
        catch (NotSupportedException)
        {
            return null;
        }
        catch (PathTooLongException)
        {
            return null;
        }
    }

    // ---- the copy ------------------------------------------------------------------------------

    /// <summary>
    /// The one `.SLDPRT` under the run folder's `copy/`.
    ///
    /// Found rather than composed, because the copy's name is the bridge's to choose
    /// (`RemodelCopy`), and refused by name when it is not there: a discarded copy is an
    /// ordinary state of a run whose artifacts are still readable.
    /// </summary>
    private static string CopyIn(string runDirectory)
    {
        string folder = Path.Combine(
            runDirectory ?? throw new ArgumentNullException(nameof(runDirectory)),
            SwReview.Extractor.Rms.RemodelCopy.CopyFolderName);

        string[] parts = Directory.Exists(folder)
            ? Directory.GetFiles(folder, "*.SLDPRT", SearchOption.TopDirectoryOnly)
            : new string[0];

        if (parts.Length == 0)
        {
            throw new RemodelRefusal(
                "CopyDiscarded",
                "this run's copy is no longer in its run folder, so there is nothing to open. "
                + "The plan, the change list and the report are still there.",
                retryable: false);
        }

        if (parts.Length > 1)
        {
            throw new InvalidOperationException(
                $"'{folder}' holds {parts.Length.ToString(CultureInfo.InvariantCulture)} parts "
                + "and a run folder holds exactly one copy. Nothing is opened until it is clear "
                + "which file the run wrote.");
        }

        return parts[0];
    }

    // ---- what has to be there before a call is made ---------------------------------------------

    private void RequireBackend()
    {
        if (_endpoint() == null)
        {
            throw new RemodelRefusal(
                "BackendUnavailable",
                "the review backend is not running, so the re-modeler has nothing to plan with. "
                + "Wait for it to start and press Remodel again.",
                retryable: true);
        }
    }

    private BridgeConfig RequireBridge() =>
        _remodelBridge() ?? throw new RemodelRefusal(
            "BridgeUnavailable",
            "the add-in's tool service is not listening yet, so the re-modeler cannot reach "
            + "SOLIDWORKS. Open the part, wait a moment and press Remodel again.",
            retryable: true);

    /// <summary>
    /// The backend's named refusal, as the page's named refusal. The class and the sentence are
    /// carried through unchanged: `contracts/pane-remodel-messages.md`'s refusal table and the
    /// backend's `error_class` are one vocabulary, and translating between them here would be a
    /// second table that can drift.
    /// </summary>
    private static RemodelRefusal Refusal(BackendRequestException failure) =>
        new RemodelRefusal(failure.ErrorClass, failure.Message, failure.Retryable, failure);
}
