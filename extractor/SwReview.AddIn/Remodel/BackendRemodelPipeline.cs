using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.ExceptionServices;
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
    /// Owner decision 159A, on Codex's review (C1): the longest wait between two polls the backend did not answer. The
    /// waits start at the poll delay and double up to this, so a backend busy for a moment is asked again at once and
    /// one that stays silent is not asked twice a second for as long as it does.
    /// </summary>
    private static readonly TimeSpan LongestUnansweredWait = TimeSpan.FromSeconds(8);

    /// <summary>
    /// Owner decision 159A, on Codex's review (C1): what the page is told, once, when a run's status poll goes unanswered
    /// while the backend that runs it is still running - in plain words, naming no path. The run is not over until its
    /// job is, so nothing else starts meanwhile; Stop still reaches the job once the backend answers; and closing
    /// SOLIDWORKS ends the backend, which the add-in started, and the run's worker with it.
    /// </summary>
    public const string BackendNotAnsweringMidRunMessage =
        "The review backend is not answering, so this run cannot be confirmed over yet, and nothing else starts until "
        + "it is. Stop is passed on as soon as the backend answers. If it does not come back, close SOLIDWORKS: that ends "
        + "the backend and the run with it.";

    /// <summary>
    /// Owner decision 159A, on Codex's review (C1): what the page is told, once, when the after-dump could not be confirmed
    /// handed to the backend - it could not be written, the backend refused it, or its answer was lost - in plain words,
    /// naming no path. The job waits for that dump, so the run is not over until the backend has finished with it or
    /// stopped waiting for it, and nothing else starts meanwhile.
    /// </summary>
    public const string AfterDumpNotConfirmedMessage =
        "The copy's feature tree after the changes was not confirmed handed to the review backend. The run ends when the "
        + "backend has finished with it or stops waiting for it, and nothing else starts until then; Stop ends the wait.";

    /// <summary>
    /// What the page is told as the after-dump is made, and what its line holds while the job waits for that dump unless
    /// it could not be confirmed handed over (owner decision 159A, on the final review: S1).
    /// </summary>
    private const string AfterDumpReadingMessage = "Reading the copy's feature tree after the changes...";

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

    /// <summary>
    /// The class of 004 T159's refusal: the copy could not be made the active document before a
    /// dump (`contracts/pane-remodel-messages.md`, refusal classes).
    /// </summary>
    private const string CopyNotActiveClass = "CopyNotActive";

    private readonly Func<BackendEndpoint?> _endpoint;
    private readonly Func<BridgeConfig?> _remodelBridge;
    private readonly Func<string, bool> _bindRun;
    private readonly Func<PageDocument?> _currentDocument;
    private readonly IReviewDump _dump;
    private readonly IRemodelSeat _seat;
    private readonly IRemodelBackend _backend;
    private readonly TimeSpan _pollDelay;
    private readonly Action<TimeSpan> _pause;

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
    /// <param name="bindRun">Hands a run folder to the tool service for the next
    /// `remodel.open`, and answers whether it took it (004 T158): the bridge's run root is used
    /// up by the open, so every open is bound first, with the folder the host made. The add-in
    /// answers it through its gate's tool service.</param>
    /// <param name="currentDocument">The active document, asked for fresh; SOLIDWORKS owns the
    /// answer. Read by <see cref="ProbeScope"/> and by nothing after it.</param>
    /// <param name="dump">The in-process extractor, for the two ModelCheck dumps.</param>
    /// <param name="seat">The copy put in front: `remodel.open_copy`, and the activation both
    /// dumps make, on the application thread.</param>
    /// <param name="backend">The loopback routes.</param>
    /// <param name="pollDelay">How long between two `GET`s of the run. Injected so the tests
    /// are not slow; defaults to half a second.</param>
    /// <param name="pause">Makes each wait of the poll loop: the clock's sleep by default. Injected so the tests can read
    /// the waits - the backoff after a poll not answered included - without making them (owner decision 159A, on the
    /// final review: A8, A9).</param>
    public BackendRemodelPipeline(
        Func<BackendEndpoint?> endpoint,
        Func<BridgeConfig?> remodelBridge,
        Func<string, bool> bindRun,
        Func<PageDocument?> currentDocument,
        IReviewDump dump,
        IRemodelSeat seat,
        IRemodelBackend backend,
        TimeSpan? pollDelay = null,
        Action<TimeSpan>? pause = null)
    {
        _endpoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
        _remodelBridge = remodelBridge ?? throw new ArgumentNullException(nameof(remodelBridge));
        _bindRun = bindRun ?? throw new ArgumentNullException(nameof(bindRun));
        _currentDocument = currentDocument ?? throw new ArgumentNullException(nameof(currentDocument));
        _dump = dump ?? throw new ArgumentNullException(nameof(dump));
        _seat = seat ?? throw new ArgumentNullException(nameof(seat));
        _backend = backend ?? throw new ArgumentNullException(nameof(backend));
        _pollDelay = pollDelay ?? DefaultPollDelay;
        _pause = pause ?? Pause;
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

        // 004 T158: the folder the host made, and no other, becomes the bridge's run root for
        // this one open. Before the copying status, because a copy that cannot happen is not one
        // to announce, and before the open, which would otherwise be refused for want of a root.
        BindRunFolder(request.RunDirectory);

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
        // Called on the host's way to deleting `copy/`, including on paths where the tool service
        // never attached, and the folder is what the engineer asked to be rid of: the host deletes
        // it whatever the close answers. With no tool service listening there is no bridge to hold
        // a session - its teardown ended any - so there is nothing to close.
        BridgeConfig? bridge = _remodelBridge();
        if (bridge == null)
        {
            return;
        }

        // Owner decision 159A, on review (the mutation review's M6): a backend that is not running
        // cannot carry the close, and the bridge may still hold the session - one that stopped after
        // the open leaves it so - so the close is refused as not sent, which the host reads as a close
        // that was not answered. It was a quiet no-op, which the host took for done.
        if (_endpoint() == null)
        {
            throw new RemodelRefusal(
                "BackendUnavailable",
                "the review backend is not running, so the close was not sent.",
                retryable: true);
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
        BackendEndpoint? runningOn = _endpoint();
        string jobId = Start(
            new RemodelRunRequest(runDirectory, bridge, Guid.NewGuid().ToString("N")), runningOn, reporter);
        return Poll(runDirectory, jobId, runningOn, reporter);
    }

    /// <summary>
    /// The run's Start, answered. Owner decision 159A, on the final review (S3; older than 159A): a Start whose answer did
    /// not come back - the client's 30 seconds ran out, or the answer failed as it was read - may have made its job, and
    /// was read as a refusal: the host closed the run's session and was free while that job could run on the bridge, and
    /// a Start pressed again was refused, the run folder already that job's. The Start names the job it makes, so one not
    /// answered is asked again - the backend answers the same Start with the job it made, or makes it then - waiting
    /// longer each time, as a poll not answered does, the page told once. Only a refusal the backend answered, or a
    /// backend gone - and the job, if it made one, with it - ends it unstarted. An answer of success the client could not
    /// read is the Start taken, and the run waits for the job it named.
    /// </summary>
    private string Start(RemodelRunRequest request, BackendEndpoint? runningOn, IRemodelRunReporter reporter)
    {
        bool told = false;
        TimeSpan wait = _pollDelay;
        while (true)
        {
            try
            {
                return _backend.StartRun(request);
            }
            catch (BackendRequestException failure)
                when (string.Equals(failure.ErrorClass, "BadResponse", StringComparison.Ordinal))
            {
                // Owner decision 159A, on the final review (found while recording S3): an answer of success the client
                // could not read - the backend answers a Start it refuses with an error class of its own - so the backend
                // took the Start, and its job is the one named here. Its polls say how it stands; a backend gone with it
                // ends the run as any poll's does.
                return request.JobId;
            }
            catch (BackendRequestException failure) when (Answered(failure) || TheBackendIsGone(runningOn))
            {
                // `RunNotPlanned`, `ResumeRefused` and `RunInProgress` are refusals the page has a
                // name for, not a failed run: nothing was started, so nothing ended.
                throw Refusal(failure);
            }
            catch (Exception failure) when (!(failure is BackendRequestException) && TheBackendIsGone(runningOn))
            {
                throw new RemodelRefusal("BackendUnavailable", failure.Message, retryable: true, failure);
            }
            catch (Exception)
            {
                if (!told)
                {
                    told = true;
                    reporter.Status("judging", BackendNotAnsweringMidRunMessage);
                }

                _pause(wait);
                wait = Longer(wait);
            }
        }
    }

    public void ActivateCopy(string runDirectory)
    {
        _seat.ActivateOrOpen(CopyIn(runDirectory));
    }

    // ---- the poll loop -----------------------------------------------------------------------

    /// <summary>
    /// The run, polled to its end. Owner decision 159A, on Codex's review (C1, older than 159A): the run is over only when
    /// its job is - the backend says the job finished or failed, or no longer knows it, or the backend that runs it is
    /// gone, its worker with it. A poll the backend did not answer while it still runs is not the run's end: the run's
    /// worker may still be applying changes, and a host freed then lets a plan open its copy on the same bridge, where
    /// the next change of this run would land. So the page is told once that the backend is not answering; the poll is
    /// asked again, waiting longer each time up to <see cref="LongestUnansweredWait"/>; a Stop asked for is tried on every
    /// poll until it lands; and the page is told where the run stands once the backend answers again. A backend that stays
    /// silent while it runs holds the run, and the host, until it answers or stops: closing SOLIDWORKS ends it. Nothing
    /// that fails on this side ends the run either: an after-dump that failed is told on the page, the line kept while the
    /// job waits for the dump, and answered once the job, which waits for that dump and then goes on to its end, has ended:
    /// with that failure when the job failed without a dump this side knows never reached it, and otherwise as the job
    /// ended - a dump whose answer was lost may have reached its job, and the job's own words say how it ended (owner
    /// decision 159A, on the final review: S1, S4).
    /// </summary>
    private RemodelRunOutcome Poll(
        string runDirectory, string jobId, BackendEndpoint? runningOn, IRemodelRunReporter reporter)
    {
        int relayed = 0;
        int applied = 0;
        int postedApplied = -1;
        int postedSeq = -1;
        string? stage = null;
        bool stopped = false;
        string stopId = Guid.NewGuid().ToString("N");
        bool dumped = false;
        bool unanswered = false;
        TimeSpan wait = _pollDelay;
        Exception? dumpFailure = null;
        bool dumpMayHaveArrived = false;
        string dumpWords = AfterDumpReadingMessage;

        while (true)
        {
            RemodelRunStatus status;
            try
            {
                status = _backend.Status(jobId);
            }
            catch (Exception failure)
            {
                if (TheJobIsOver(failure, runningOn))
                {
                    if (dumpFailure != null)
                    {
                        Rethrow(dumpFailure);
                    }

                    // The backend is the only thing that knows how the run ended. With the job gone the run is over
                    // and unattributable, which is `failed`; the change log on disk is what is left, and it is intact.
                    reporter.Status("error", failure.Message);
                    return new RemodelRunOutcome("failed", applied);
                }

                if (!unanswered)
                {
                    unanswered = true;
                    reporter.Status(stage ?? "judging", BackendNotAnsweringMidRunMessage);
                }

                if (!stopped && reporter.StopRequested)
                {
                    stopped = TryStop(jobId, stopId);
                }

                _pause(wait);
                wait = Longer(wait);
                continue;
            }

            if (unanswered)
            {
                // The backend answers again: the page is told where the run stands, below, and the polls go back to
                // their pace.
                unanswered = false;
                stage = null;
                wait = _pollDelay;
            }

            applied = status.ChangesApplied;
            relayed += Relay(runDirectory, relayed, reporter);

            if (status.State == RemodelRunStatus.FinishedState
                || status.State == RemodelRunStatus.FailedState)
            {
                // Owner decision 159A, on the final review (S4): the job's own end decides. But for a job that failed
                // without the dump this side knows never reached it - not written, or refused by the backend - that
                // failure is why; a dump whose answer was lost may have reached it, and the job's words say how it ended.
                if (dumpFailure != null && !dumpMayHaveArrived && status.State == RemodelRunStatus.FailedState)
                {
                    Rethrow(dumpFailure);
                }

                return Ended(status, applied, reporter);
            }

            // Owner decision 159A, on the final review (S1): while the job waits for the dump this run made, or could not,
            // the backend's plan still reads `applying` - it records `verifying` once the dump has arrived - so the line
            // keeps what it said of that dump rather than going back to the plan being applied, and says it again once the
            // backend answers after it did not.
            if (dumped && status.Awaiting == RemodelRunStatus.PackageAfterAwaiting)
            {
                if (stage != "verifying")
                {
                    stage = "verifying";
                    reporter.Status(stage, dumpWords);
                }
            }
            else
            {
                string? next = Stage(status.PlanState);
                if (next != null && next != stage)
                {
                    stage = next;
                    reporter.Status(next, StageMessages[next]);
                }
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
                stopped = TryStop(jobId, stopId);
            }

            if (!dumped && status.Awaiting == RemodelRunStatus.PackageAfterAwaiting)
            {
                // The rendezvous: the backend is blocked until this dump lands, so it is made
                // now and the run is asked again immediately rather than after a poll delay.
                // Once, whatever it answers.
                dumped = true;
                stage = "verifying";
                reporter.Status("verifying", AfterDumpReadingMessage);
                string? package = null;
                try
                {
                    package = DumpInto(runDirectory, PackageAfterName, "verifying", reporter);
                }
                catch (Exception failure)
                {
                    // Owner decision 159A, on Codex's review (C1): answered once the job has ended, as above. This side
                    // could not write the dump, so it never reached the job.
                    dumpFailure = failure;
                }

                if (package != null)
                {
                    try
                    {
                        _backend.PackageAfter(jobId, package);
                    }
                    catch (BackendRequestException failure)
                    {
                        // `PackageAfterRefused` is a class of its own in the route's error table.
                        // Unwrapped it would leave this loop as a raw request failure, reach the
                        // host's generic catch and be shown as `HostError` - the one thing
                        // `RemodelRefusal` exists to prevent. A refusal the backend answered says the
                        // dump did not reach the job; an answer that did not come back, or could not be
                        // read, says nothing of it (owner decision 159A, on the final review: S4).
                        dumpFailure = Refusal(failure);
                        dumpMayHaveArrived = !Answered(failure) || UnreadAnswerClasses.Contains(failure.ErrorClass);
                    }
                    catch (Exception failure)
                    {
                        dumpFailure = failure;
                        dumpMayHaveArrived = true;
                    }
                }

                if (dumpFailure != null)
                {
                    dumpWords = AfterDumpNotConfirmedMessage;
                    reporter.Status("verifying", dumpWords);

                    // Owner decision 159A, on the final review (S1): the job's wait for its dump ends on a new Stop
                    // asked for while it waits. The earlier Stop belongs to apply, and its transport retries must keep
                    // its identity; this cancellation, after the dump failed, therefore gets an identity of its own.
                    stopped = false;
                    stopId = Guid.NewGuid().ToString("N");
                }

                continue;
            }

            _pause(_pollDelay);
        }
    }

    /// <summary>
    /// Owner decision 159A, on Codex's review (C1): whether a poll that failed with <paramref name="failure"/> says the
    /// job is over - the backend no longer knows it, and its runs live in its memory - or the backend that ran it, the one
    /// listening at <paramref name="runningOn"/> when the run began, is gone: none is running, or another runs in its place.
    /// A backend is stopped only by the add-in, which stops one before it starts the next and holds a settings restart back
    /// while a run is in flight, or by its own exit; either way its worker is not acting.
    /// </summary>
    private bool TheJobIsOver(Exception failure, BackendEndpoint? runningOn) =>
        (failure is BackendRequestException refused
            && string.Equals(refused.ErrorClass, "UnknownJob", StringComparison.Ordinal))
        || TheBackendIsGone(runningOn);

    /// <summary>
    /// Whether the backend asked at <paramref name="runningOn"/> is gone: none is running, or another runs in its place,
    /// told by its port or its token. A backend is stopped only by the add-in, which stops one before it starts the next
    /// and holds a settings restart back while a run is in flight, or by its own exit; either way its worker is not acting.
    /// </summary>
    private bool TheBackendIsGone(BackendEndpoint? runningOn)
    {
        BackendEndpoint? now = _endpoint();
        return runningOn == null
            || now == null
            || now.Port != runningOn.Port
            || !string.Equals(now.Token, runningOn.Token, StringComparison.Ordinal);
    }

    /// <summary>
    /// Whether <paramref name="failure"/> is an answer the backend gave (owner decision 159A, on the final review: S3, S4):
    /// any but the client's <c>BackendUnavailable</c>, which says none came - the backend not running, the connection
    /// refused, or the client's 30 seconds spent.
    /// </summary>
    private static bool Answered(BackendRequestException failure) =>
        !string.Equals(failure.ErrorClass, "BackendUnavailable", StringComparison.Ordinal);

    /// <summary>
    /// The client's classes for an answer that came and could not be read: what the backend did is not in it (owner
    /// decision 159A, on the final review: S4).
    /// </summary>
    private static readonly HashSet<string> UnreadAnswerClasses = new HashSet<string>(StringComparer.Ordinal)
    {
        "HttpError",
        "BadResponse",
    };

    /// <summary>
    /// Posts the Stop the engineer asked for, and answers whether its reply arrived. A lost reply does not say whether
    /// the backend accepted the Stop, and the run may still be applying changes to the copy. Ending the run here would
    /// report "failed, 0 changes" while the backend still applies them and leave the folder blocked as `RunInProgress`.
    /// So it is posted again at the next poll with the same intent, even if the job now waits for its after-dump: that
    /// retry must not become a new cancellation of the wait (owner decision 159A; 004 T263).
    /// </summary>
    private bool TryStop(string jobId, string stopId)
    {
        try
        {
            _backend.Stop(jobId, stopId);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>The next wait after a poll the backend did not answer: twice this one, up to <see cref="LongestUnansweredWait"/>.</summary>
    internal static TimeSpan Longer(TimeSpan wait) =>
        wait <= TimeSpan.Zero
            ? wait
            : TimeSpan.FromTicks(Math.Min(wait.Ticks * 2, LongestUnansweredWait.Ticks));

    private static void Pause(TimeSpan wait)
    {
        if (wait > TimeSpan.Zero)
        {
            Thread.Sleep(wait);
        }
    }

    /// <summary>Throws <paramref name="failure"/> again, as it was first thrown.</summary>
    private static void Rethrow(Exception failure) => ExceptionDispatchInfo.Capture(failure).Throw();

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
        catch (UnauthorizedAccessException)
        {
            // Owner decision 159A, on Codex's review (C1): nor does a log this side cannot read end the run, which is
            // over only when its job is. The lines are still there on the next poll.
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
    /// SOLIDWORKS has active, and the engineer's own source is still open in another tab
    /// throughout - including minutes later, at the after-dump. So the copy is made the active
    /// document first, activate only (<see cref="MakeTheCopyActive"/>, 004 T159); but the
    /// engineer can still click away between that and the dump, and which document was read is
    /// knowable only from the file that was written, so it is read out of it and refused unless
    /// it is the copy this run made. The activation is the pre-check, this the post-check.
    /// </summary>
    private string DumpInto(
        string runDirectory, string fileName, string stage, IRemodelRunReporter reporter)
    {
        string copy = MakeTheCopyActive(runDirectory, fileName);

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

        RequireItReadTheCopy(written, runDirectory, copy, fileName);

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
    /// Makes this run's copy the active document before a dump (004 T159; research R13.8, D6):
    /// the one real part in the run folder's `copy/`, matching `open.json` when recorded,
    /// handed to <see cref="IRemodelSeat.ActivateOpenCopy"/>, which only ever activates - a dump
    /// that could open a document would be a second way to open one.
    ///
    /// The seat answers what SOLIDWORKS has active afterwards and decides nothing; this does. An
    /// answer that is not the copy by path - none, because SOLIDWORKS does not have the copy open
    /// or would not activate it; the engineer's part; another run's copy; a bare name - a seat
    /// whose call threw, and a run folder with no copy left in it to activate (each kept as the
    /// cause) are all `CopyNotActive`, in the host's words for the dump that was about to be
    /// taken, and nothing is dumped. `remodel.open_copy`'s own words for a missing copy speak of
    /// a plan and a report that a plan-time dump does not have yet, so they are not used here.
    /// </summary>
    private string MakeTheCopyActive(string runDirectory, string fileName)
    {
        string copy;
        try
        {
            copy = CopyIn(runDirectory);
        }
        catch (RemodelRefusal gone)
        {
            throw CopyNotActive(fileName, gone);
        }

        string? active;
        try
        {
            active = _seat.ActivateOpenCopy(copy);
        }
        catch (Exception failure)
        {
            throw CopyNotActive(fileName, failure);
        }

        // One rule for "the same document" in the product: full paths, ordinal ignoring case, and
        // a path that is not rooted names nothing.
        if (!OpenDrawingDiscovery.SamePath(active, copy))
        {
            throw CopyNotActive(fileName, null);
        }

        return copy;
    }

    /// <summary>
    /// `CopyNotActive` in the words for the dump it stopped: before the plan it is retryable,
    /// since planning again makes a new copy; after the changes it is not, since that run can no
    /// longer be checked and its copy is never saved.
    /// </summary>
    private static RemodelRefusal CopyNotActive(string fileName, Exception? cause) =>
        string.Equals(fileName, PackageAfterName, StringComparison.Ordinal)
            ? new RemodelRefusal(
                CopyNotActiveClass, RemodelHost.CopyNotActiveAfterChangesMessage, retryable: false, cause)
            : new RemodelRefusal(
                CopyNotActiveClass, RemodelHost.CopyNotActiveBeforePlanMessage, retryable: true, cause);

    /// <summary>
    /// Refuses a dump that is not a reading of this run's copy, before it can be renamed into a
    /// run artifact.
    ///
    /// The check is the exact copy path selected before activation, not merely its folder:
    /// a lock file or a different document beside the copy is not the document this run opened.
    /// The copy's name remains the bridge's to choose.
    ///
    /// A package that names no document is refused too. It says nothing about what it read, and
    /// unknown is not the copy (constitution Principle I).
    ///
    /// <b>The path that was read is not in the message.</b> It may be the source, and nothing
    /// after the copy may name the source - not even in prose on the page. The package stays in
    /// the run folder unrenamed, which is where the evidence for this refusal belongs.
    /// </summary>
    private static void RequireItReadTheCopy(
        string written, string runDirectory, string copy, string fileName)
    {
        string? read = DocumentIn(written);

        if (!OpenDrawingDiscovery.SamePath(read, copy))
        {
            throw new InvalidOperationException(
                $"the dump written for '{fileName}' "
                + (read == null
                    ? "names no document, so which document it read cannot be established"
                    : "names a document that is not this run's exact copy")
                + $", so it is not a reading of this run's copy. '{runDirectory}' keeps the "
                + "package it wrote as the evidence; the path it named is not repeated here, "
                + "because nothing after the copy may name the source.");
        }
    }

    /// <summary>
    /// `documents[0].path` of a written package, or null when the file says
    /// nothing readable about what it read.
    ///
    /// Null for every unreadable shape rather than a throw per shape: every one of them means
    /// the same thing to the one caller - the document is unknown - and unknown is refused
    /// there, by name, once.
    /// </summary>
    private static string? DocumentIn(string packagePath)
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
            return Path.IsPathRooted(documentPath) ? Path.GetFullPath(documentPath) : null;
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
    /// The one real `.SLDPRT` under the run folder's `copy/`, excluding SOLIDWORKS's `~$`
    /// lock files. The lock lives beside an open part and has the same extension, but it is not
    /// another part and must never be activated or dumped.
    ///
    /// `open.json` records the exact copy path before HTTP Open answers. When that record exists,
    /// the real part must match it; a different file in the folder cannot stand in for the copy.
    /// Older run folders without an open record retain the singleton check. Two real parts are
    /// always refused, even if the record names one of them.
    /// </summary>
    private static string CopyIn(string runDirectory)
    {
        string folder = Path.Combine(
            runDirectory ?? throw new ArgumentNullException(nameof(runDirectory)),
            SwReview.Extractor.Rms.RemodelCopy.CopyFolderName);

        var parts = new List<string>();
        if (Directory.Exists(folder))
        {
            foreach (string file in Directory.GetFiles(folder, "*", SearchOption.TopDirectoryOnly))
            {
                if (!Path.GetFileName(file).StartsWith("~$", StringComparison.Ordinal)
                    && string.Equals(Path.GetExtension(file),
                        SwReview.Extractor.Rms.RemodelCopy.PartExtension, StringComparison.OrdinalIgnoreCase))
                {
                    parts.Add(file);
                }
            }
        }

        if (parts.Count == 0)
        {
            throw new RemodelRefusal(
                "CopyDiscarded",
                "this run's copy is no longer in its run folder, so there is nothing to open. "
                + "The plan, the change list and the report are still there.",
                retryable: false);
        }

        if (parts.Count > 1)
        {
            throw new InvalidOperationException(
                $"'{folder}' holds {parts.Count.ToString(CultureInfo.InvariantCulture)} parts "
                + "and a run folder holds exactly one copy. Nothing is opened until it is clear "
                + "which file the run wrote.");
        }

        string record = Path.Combine(runDirectory, "open.json");
        if (File.Exists(record) && !OpenDrawingDiscovery.SamePath(OpenedCopyIn(record), parts[0]))
        {
            throw new InvalidOperationException(
                "this run's open record does not identify the exact part in its copy folder. "
                + "Nothing is activated or opened until the copy can be established.");
        }

        return parts[0];
    }

    private static string? OpenedCopyIn(string record)
    {
        try
        {
            using (var file = new FileStream(record, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (JsonDocument document = JsonDocument.Parse(file))
            {
                return document.RootElement.ValueKind == JsonValueKind.Object
                    && document.RootElement.TryGetProperty("copy_path", out JsonElement path)
                    && path.ValueKind == JsonValueKind.String
                        ? path.GetString()
                        : null;
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
    /// 004 T158's host half: the run folder handed to the tool service before the open. A bind
    /// that answers false, or that throws (kept as the cause), is `BridgeUnavailable` in the
    /// host's words - nothing is copied and no open is sent, and pressing the button again can
    /// work, since the tool service may simply have been re-attaching.
    /// </summary>
    private void BindRunFolder(string runDirectory)
    {
        bool bound;
        try
        {
            bound = _bindRun(runDirectory);
        }
        catch (Exception failure)
        {
            throw RunNotBound(failure);
        }

        if (!bound)
        {
            throw RunNotBound(null);
        }
    }

    private static RemodelRefusal RunNotBound(Exception? cause) =>
        new RemodelRefusal("BridgeUnavailable", RemodelHost.RunNotBoundMessage, retryable: true, cause);

    /// <summary>
    /// The backend's named refusal, as the page's named refusal. The class and the sentence are
    /// carried through unchanged: `contracts/pane-remodel-messages.md`'s refusal table and the
    /// backend's `error_class` are one vocabulary, and translating between them here would be a
    /// second table that can drift.
    /// </summary>
    private static RemodelRefusal Refusal(BackendRequestException failure) =>
        new RemodelRefusal(failure.ErrorClass, failure.Message, failure.Retryable, failure);
}
