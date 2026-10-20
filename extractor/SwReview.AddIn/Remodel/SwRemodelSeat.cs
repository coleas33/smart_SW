using System;
using System.Globalization;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.AddIn.Remodel.Seat;
using SwReview.AddIn.Review;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// The real <see cref="IRemodelSeat"/>: `remodel.open_copy`, and the activation before each dump
/// (<see cref="ActivateOpenCopy"/>, 004 T159), on the SOLIDWORKS application thread.
///
/// `remodel.open_copy` takes two paths, in this order, because the copy may or may not still be
/// open when the engineer presses the button - the run closes it, and `remodel.discard_copy` may
/// have been pressed on an earlier run:
///
/// 1. <c>GetOpenDocumentByName</c> and, if it is there, <c>ActivateDoc3</c> with
///    <c>swDontRebuildActiveDoc</c>. Not rebuilding is deliberate: the copy was saved after the
///    geometry gate measured it, and a rebuild on activation would dirty a document the report
///    has already been written against.
/// 2. Otherwise <c>OpenDoc7</c> with <c>Silent</c> and <c>LoadModel</c> - the
///    <c>RemodelCopy.OpenOptions</c> integer 17 that `remodel.open` pins, through the same
///    <see cref="CopyOpenSpecification"/> the bridge seat opens the copy with - and never
///    <c>ReadOnly</c> or <c>ViewOnly</c>. A copy the engineer cannot edit is a copy they cannot
///    accept: the whole point of the run is that they Save As it somewhere of their own
///    choosing.
///
/// <b>Every call goes through a gate</b> (owner decision 144A, feature 011 research R11): each action
/// builds one, <see cref="Gate"/>, whose guard is <see cref="RemodelSeatGuard"/> - an allowlist of
/// <c>ISldWorks.ActivateDoc3</c> and <c>ISldWorks.OpenDoc7</c> by their qualified keys, every other
/// qualified key refused, every bare name handed to the read-only guard - and writes what the gate was
/// asked to the run folder's <c>remodel.log</c> (<see cref="RemodelSeatGateLog"/>): a begin line before
/// its first call, and its outcome after its last. The open request's property sets are made inside
/// the gate entry that asks for the request, and read back inside the open's, as the bridge makes them
/// inside its open: they set a throwaway request, not a document.
///
/// <b>Only the run's copy</b> (decision 144A), as the re-modeler's every other exception is scoped to
/// its own documents: a path that is not the run's copy (<see cref="RemodelSeatCopyPath"/>) is refused
/// before SOLIDWORKS is asked anything, and from then on the seat uses the full, canonical form it was
/// checked in; and a document SOLIDWORKS answers - the lookup's, the activation's or the open's - is
/// activated, or taken as the copy, only once its own path is the copy's
/// (<see cref="OpenDrawingDiscovery.SamePath"/>, the rule the pipeline compares the active document by
/// after each activation). A document that is not is never activated, asked its title or closed, and is
/// not named: it may be the engineer's.
///
/// Everything that decides anything else is in <see cref="BackendRemodelPipeline"/>, which is tested
/// over a fake of this interface. This class is tested over the recording stand-ins of feature
/// 004's build order (`SwRemodelSeatTests`), which place every interop call under the gate entry it
/// is made under, since what it must never do - reach SOLIDWORKS outside its gate, open a document for
/// a dump, or touch a document that is not the copy - is a property of the calls it makes.
/// </summary>
public sealed class SwRemodelSeat : IRemodelSeat
{
    /// <summary>The gate log's name for `remodel.open_copy` (<see cref="ActivateOrOpen"/>).</summary>
    public const string OpenCopyAction = "open_copy";

    /// <summary>The gate log's name for the activation before each dump (<see cref="ActivateOpenCopy"/>).</summary>
    public const string ActivateBeforeDumpAction = "activate_before_dump";

    // The outcomes the gate log names: the copy activated, or opened again; and, for the activation
    // before a dump, which answers rather than refuses, why nothing was activated.
    private const string ActivatedOutcome = "activated";
    private const string OpenedOutcome = "opened";
    private const string NotOpenOutcome = "not_open";
    private const string NotTheCopyOutcome = "not_the_copy";
    private const string NotActivatedOutcome = "not_activated";

    // The two calls beyond reading, by the qualified keys RemodelSeatGuard allowlists: the seat's own
    // literals, as BridgeDispatcher spells RemodelGuard's, so the file that makes each call names it.
    private const string ActivateDocKey = "ISldWorks.ActivateDoc3";
    private const string OpenDocKey = "ISldWorks.OpenDoc7";

    // The reads, by the bare names every read call site of the product gives them.
    private const string LookupMember = "GetOpenDocumentByName";
    private const string PathMember = "GetPathName";
    private const string TitleMember = "GetTitle";
    private const string ActiveDocumentMember = "ActiveDoc";
    private const string OpenRequestMember = "GetOpenDocSpec";

    private readonly ISldWorks _swApp;
    private readonly IApplicationThread _thread;
    private readonly ISwGateObserver? _observer;
    private readonly Action<string, string> _log;

    /// <summary>The seat as the add-in builds it: each action's gate log goes to the run folder's <c>remodel.log</c>.</summary>
    public SwRemodelSeat(ISldWorks swApp, IApplicationThread thread)
        : this(swApp, thread, null, RemodelSeatGateLog.Write)
    {
    }

    /// <param name="observer">Told every member each action's gate is asked about, and every refusal; null for none.</param>
    /// <param name="log">Writes a gate-log line to the run folder it is handed.</param>
    internal SwRemodelSeat(ISldWorks swApp, IApplicationThread thread, ISwGateObserver? observer, Action<string, string> log)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _thread = thread ?? throw new ArgumentNullException(nameof(thread));
        _observer = observer;
        _log = log ?? throw new ArgumentNullException(nameof(log));
    }

    /// <summary>
    /// The gate one action of the seat calls SOLIDWORKS through: a breaker of its own, so a failure of
    /// one press counts toward no later one, and <see cref="RemodelSeatGuard"/>.
    /// </summary>
    internal static SwGate Gate(ISwGateObserver observer) =>
        new SwGate(new CircuitBreaker(), new RemodelSeatGuard()) { Observer = observer };

    public void ActivateOrOpen(string copyPath)
    {
        if (copyPath == null)
        {
            throw new ArgumentNullException(nameof(copyPath));
        }

        // From here on the path is the canonical one the check was made on: what SOLIDWORKS is handed
        // and what every document is compared with.
        (copyPath, string runDirectory) = RemodelSeatCopyPath.Of(copyPath);

        _thread.Invoke<object?>(() => Gated<object?>(OpenCopyAction, runDirectory, gate =>
        {
            var open = gate.Call(LookupMember, () => _swApp.GetOpenDocumentByName(copyPath)) as IModelDoc2;
            if (open == null)
            {
                Open(gate, copyPath);
                return (null, OpenedOutcome);
            }

            if (!IsTheCopy(gate, open, copyPath))
            {
                throw new InvalidOperationException(
                    "SOLIDWORKS answered the copy's path '" + copyPath + "' with a document that is not "
                    + "this run's copy, so nothing was activated or opened.");
            }

            Activate(gate, open, copyPath);
            return (null, ActivatedOutcome);
        }));
    }

    /// <summary>
    /// 004 T159: the copy made the active document before a dump - found among the documents
    /// SOLIDWORKS already has open, shown to be the copy by its own path (decision 144A), and
    /// activated by <see cref="ActivateWithoutRebuild"/>, the same call `remodel.open_copy` makes - and
    /// the path of whatever is active afterwards, or null when SOLIDWORKS does not have the copy open
    /// or activated no document.
    ///
    /// <b>Activate only.</b> A copy that is not open is answered null and left alone: no
    /// <c>OpenDoc7</c>, no open request, no fallback (research R13.8, D6). So is a document the lookup
    /// answers that is not at the copy's path: it is not the copy, and is neither asked its title nor
    /// activated. And the error bits <c>ActivateDoc3</c> reports do not decide on their own - a copy
    /// that needs a rebuild is still activated, without one, as asked - the active document does, and
    /// <see cref="BackendRemodelPipeline"/> compares its path with the copy's.
    /// </summary>
    public string? ActivateOpenCopy(string copyPath)
    {
        if (copyPath == null)
        {
            throw new ArgumentNullException(nameof(copyPath));
        }

        // As above: the canonical path, from here on.
        (copyPath, string runDirectory) = RemodelSeatCopyPath.Of(copyPath);

        return _thread.Invoke<string?>(() => Gated<string?>(ActivateBeforeDumpAction, runDirectory, gate =>
        {
            var open = gate.Call(LookupMember, () => _swApp.GetOpenDocumentByName(copyPath)) as IModelDoc2;
            if (open == null)
            {
                return (null, NotOpenOutcome);
            }

            if (!IsTheCopy(gate, open, copyPath))
            {
                return (null, NotTheCopyOutcome);
            }

            if (ActivateWithoutRebuild(gate, open, out _) == null)
            {
                return (null, NotActivatedOutcome);
            }

            var active = gate.Call(ActiveDocumentMember, () => _swApp.ActiveDoc) as IModelDoc2;
            return (active == null ? null : gate.Call(PathMember, () => active.GetPathName()), ActivatedOutcome);
        }));
    }

    /// <summary>
    /// One action through a gate of its own, on the application thread: its begin line written before
    /// its first call, so an action SOLIDWORKS never returns from still leaves its line (as every bridge
    /// request's begin line does, U27), and its outcome line once it is done, whatever it did. A log that
    /// cannot be written fails nothing: the action's own answer, or its own error, is what the caller gets.
    /// </summary>
    private T Gated<T>(string action, string runDirectory, Func<SwGate, (T Result, string Outcome)> work)
    {
        Write(runDirectory, RemodelSeatGateLog.BeginLine(action));

        var gateLog = new RemodelSeatGateLog(_observer);
        string? outcome = null;
        Exception? failure = null;
        try
        {
            (T result, string ended) = work(Gate(gateLog));
            outcome = ended;
            return result;
        }
        catch (Exception error)
        {
            failure = error;
            throw;
        }
        finally
        {
            Write(runDirectory, gateLog.Line(action, outcome, failure));
        }
    }

    private void Write(string runDirectory, string line)
    {
        try
        {
            _log(runDirectory, line);
        }
        catch (Exception)
        {
            // A log that cannot be written must not fail the action it describes.
        }
    }

    /// <summary>Whether <paramref name="document"/>'s own path is the copy's, by the rule the pipeline compares the active document with.</summary>
    private static bool IsTheCopy(SwGate gate, IModelDoc2 document, string copyPath) =>
        OpenDrawingDiscovery.SamePath(gate.Call(PathMember, () => document.GetPathName()), copyPath);

    /// <summary>
    /// `remodel.open_copy`'s activation: refused when SOLIDWORKS activates nothing or reports error
    /// bits, and - since <c>ActivateDoc3</c> activates by title - when the document it answers is not the
    /// copy (decision 144A's review), so the engineer's document is never reported activated as the copy.
    /// </summary>
    private void Activate(SwGate gate, IModelDoc2 open, string copyPath)
    {
        object? activated = ActivateWithoutRebuild(gate, open, out int errors);

        if (activated == null || errors != 0)
        {
            throw new InvalidOperationException(
                "SOLIDWORKS would not activate the copy that is already open ("
                + copyPath + "): ActivateDoc3 reported "
                + errors.ToString(CultureInfo.InvariantCulture) + ".");
        }

        if (!(activated is IModelDoc2 document) || !IsTheCopy(gate, document, copyPath))
        {
            throw new InvalidOperationException(
                "SOLIDWORKS answered the activation of the copy (" + copyPath + ") with a document that is "
                + "not this run's copy.");
        }
    }

    /// <summary>
    /// The one <c>ActivateDoc3</c> both activations make: by the document's title, the user's
    /// preferences not consulted, and <c>swDontRebuildActiveDoc</c> - a rebuild on activation
    /// would dirty a copy the report was written against, or change the tree a dump is about to
    /// read.
    /// </summary>
    private object? ActivateWithoutRebuild(SwGate gate, IModelDoc2 open, out int errors)
    {
        string title = gate.Call(TitleMember, () => open.GetTitle());
        int reported = 0;
        object? activated = gate.Call(ActivateDocKey, () => _swApp.ActivateDoc3(
            title,
            UseUserPreferences: false,
            Option: (int)swRebuildOnActivation_e.swDontRebuildActiveDoc,
            Errors: ref reported));
        errors = reported;
        return activated;
    }

    private void Open(SwGate gate, string copyPath)
    {
        // RemodelCopy.OpenOptions (Silent | LoadModel = 17) as the specification's own members,
        // stated once for both opens of a copy (feature 004, build order lane B), set inside the gate
        // entry that asks for the request.
        IDocumentSpecification specification = gate.Call(
            OpenRequestMember, () => CopyOpenSpecification.For(_swApp, copyPath));

        // The request's load bits are read back inside the open's own gate entry, and only when the
        // open answered no document.
        (IModelDoc2? opened, string? why) = gate.Call(OpenDocKey, () =>
        {
            IModelDoc2? document = _swApp.OpenDoc7(specification);
            return (document, document == null
                ? FileLoadErrors.Describe(specification.Error, specification.Warning)
                : null);
        });

        if (opened == null)
        {
            throw new InvalidOperationException(
                "SOLIDWORKS would not open the copy at '" + copyPath + "': " + why
                + ". The run folder still holds it"
                + (File.Exists(copyPath) ? "." : ", but the file is no longer there."));
        }

        if (!IsTheCopy(gate, opened, copyPath))
        {
            throw new InvalidOperationException(
                "SOLIDWORKS answered the open of the copy at '" + copyPath + "' with a document that is "
                + "not this run's copy - one it already had open under the copy's title, perhaps - so that "
                + "document was left as it is.");
        }
    }
}
