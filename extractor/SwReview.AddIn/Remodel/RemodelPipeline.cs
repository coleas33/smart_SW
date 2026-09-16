using System;
using System.Collections.Generic;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// The scope signals read off the engineer's open source, and the pure gate's verdict on them
/// (`data-model.md` section 4.2, `ScopeReport`).
///
/// Two halves because they are decided in two places and neither may be moved: the
/// <see cref="Signals"/> are C# measurements taken by `remodel.probe_scope` with read members
/// only, and the <see cref="Refusals"/> are the verdict, made by the pure `remodel/scope.py`.
/// A host that decided multibody or weldment itself would be a second rule table that could
/// drift from the one the report is written against.
///
/// A signal that could not be read is <b>null</b>, and null is not a pass: the host refuses
/// the run naming that signal rather than proceeding on an unknown.
/// </summary>
public sealed class RemodelScopeReading
{
    /// <param name="signals">What was measured on the source; a null field is unknown.</param>
    /// <param name="refusals">One sentence per failing signal, from the pure gate. Empty is
    /// the only thing that means "ok": <b>every</b> failing signal is carried, because a
    /// refusal that named one of two reasons sends the engineer back twice.</param>
    public RemodelScopeReading(ScopeSignals signals, IReadOnlyList<string> refusals)
    {
        Signals = signals ?? throw new ArgumentNullException(nameof(signals));
        Refusals = refusals ?? throw new ArgumentNullException(nameof(refusals));
    }

    public ScopeSignals Signals { get; }

    public IReadOnlyList<string> Refusals { get; }
}

/// <summary>What the copy step is given. The source appears here as a <b>path</b>, and nowhere else.</summary>
public sealed class RemodelCopyRequest
{
    public RemodelCopyRequest(string runDirectory, string sourcePath, string? configuration)
    {
        RunDirectory = runDirectory ?? throw new ArgumentNullException(nameof(runDirectory));
        SourcePath = sourcePath ?? throw new ArgumentNullException(nameof(sourcePath));
        Configuration = configuration;
    }

    /// <summary>The run folder, already created. The copy goes under it and nowhere else.</summary>
    public string RunDirectory { get; }

    /// <summary>
    /// The engineer's file, as the source of a filesystem copy.
    ///
    /// It is a path and never a document handle, which is the property the constitution's
    /// re-modeler exception rests on: the source is unreachable from the run rather than
    /// merely un-targeted (plan.md key point 2).
    /// </summary>
    public string SourcePath { get; }

    public string? Configuration { get; }
}

/// <summary>What came back from copying, opening, tagging, rolling and rebuilding the copy.</summary>
public sealed class RemodelCopyReading
{
    /// <param name="copyPath">The copy, under `&lt;run_dir&gt;/copy/`.</param>
    /// <param name="rebuildErrorCount">`GetWhatsWrongCount()` after the baseline rollback and
    /// rebuild, or <b>null</b> when it could not be read. Null is unknown, never zero: a part
    /// that is already broken is refused, and reading "no errors" into an unanswered call is
    /// how a run would be started on one.</param>
    /// <param name="copyPresent">Whether the copy is still on disk and open.</param>
    public RemodelCopyReading(string copyPath, int? rebuildErrorCount, bool copyPresent)
    {
        CopyPath = copyPath ?? throw new ArgumentNullException(nameof(copyPath));
        RebuildErrorCount = rebuildErrorCount;
        CopyPresent = copyPresent;
    }

    public string CopyPath { get; }

    public int? RebuildErrorCount { get; }

    /// <summary>
    /// False when the bridge refused with `preexisting_rebuild_errors`: it deleted the copy and
    /// closed the document before it answered (`contracts/bridge-remodel.md`).
    ///
    /// It is carried rather than inferred from <see cref="RebuildErrorCount"/>, because the
    /// count is only what the refusal's detail happened to say - a refusal carrying no number
    /// arrives as null and one carrying 0 arrives as 0 - and a copy that is gone must be
    /// refused on either. Every step after this one addresses "the copy"; with no copy there,
    /// the document they would address is the engineer's source.
    /// </summary>
    public bool CopyPresent { get; }
}

/// <summary>What the executor reports when phases B to D are over.</summary>
public sealed class RemodelRunOutcome
{
    /// <param name="state">The `RunState` the run ended in (data-model.md section 11). The
    /// authoritative copy of it is in `plan.json`; this is what the host says in its closing
    /// `status` without re-reading the file.</param>
    /// <param name="changesApplied">What `remodel.stopped` reports.</param>
    public RemodelRunOutcome(string state, int changesApplied)
    {
        State = state ?? throw new ArgumentNullException(nameof(state));
        ChangesApplied = changesApplied;
    }

    public string State { get; }

    public int ChangesApplied { get; }
}

/// <summary>
/// How the executor tells the pane what it is doing, and how it asks whether to stop.
///
/// The host owns the message pump - every `status`, `remodel.progress` and `remodel.change`
/// goes out through one redacting choke point - so the executor is handed this rather than the
/// channel. It cannot post a message type the contract does not define, and it cannot post a
/// secret the host would have masked.
/// </summary>
public interface IRemodelRunReporter
{
    /// <summary>
    /// Whether a stop has been asked for. Read between changes; the change in flight is always
    /// finished and, if it failed, inverted, before the run finalizes.
    /// </summary>
    bool StopRequested { get; }

    /// <summary>One `status {stage, message}`; the stages are the contract's closed list.</summary>
    void Status(string stage, string message);

    /// <summary>One `remodel.progress {applied, total, current: {seq, kind, subject_name}}`.</summary>
    void Progress(int applied, int total, int seq, string kind, string? subjectName);

    /// <summary>
    /// One `remodel.change`, carrying one `ChangeRecord` <b>exactly as `changes.jsonl` holds
    /// it</b>, so the list on the page grows as the file does. The host passes the line
    /// through and neither reshapes nor summarizes it; a line that is not JSON is dropped
    /// rather than sent as text, because the page reads it as a record.
    /// </summary>
    void Change(string changeRecordJson);
}

/// <summary>
/// Everything the Remodel tab needs from SOLIDWORKS and from the executor, behind one seam.
///
/// It exists for the reason <see cref="Review.IReviewDump"/> exists: the host's real work -
/// which refusals come before the copy, what is created when, what the page is told and in
/// what order - is decided here and has to be testable with no seat. Nothing in this interface
/// decides anything. Each member is one step of `contracts/pane-remodel-messages.md`'s
/// `remodel.plan` row, in the order that row states them, and the host is what orders them.
///
/// <b>There is no member that opens the source.</b> The source's path travels in
/// <see cref="RemodelCopyRequest"/>, as the source of a filesystem copy with
/// `overwrite: false`, and every other member addresses the run folder. That absence is the
/// guarantee, not a convention: there is no call to make, so there is no call to get wrong.
/// </summary>
public interface IRemodelPipeline
{
    /// <summary>
    /// `remodel.probe_scope`: the scope signals off the already-open source, read members
    /// only, before anything is copied (FR-001).
    /// </summary>
    RemodelScopeReading ProbeScope();

    /// <summary>
    /// Copies the source into the run folder, opens and tags the copy, rolls it to the end and
    /// rebuilds it, and reports the rebuild-error count that reading needs.
    /// </summary>
    RemodelCopyReading OpenCopy(RemodelCopyRequest request, IRemodelRunReporter reporter);

    /// <summary>
    /// `CloseDoc` on the copy without saving. Called before the copy folder is deleted - by a
    /// `PreexistingRebuildErrors` refusal and by `remodel.discard_copy` - and a no-op when the
    /// copy is not open.
    /// </summary>
    void CloseCopy(string runDirectory);

    /// <summary>
    /// Dumps the copy with feature 003's `DumpProfile.ModelCheck`, carries `exceptions.json`
    /// forward, and runs the pure planner. Returns `plan_summary` as JSON, which the host
    /// passes through to the page untouched.
    /// </summary>
    string Plan(string runDirectory, IRemodelRunReporter reporter);

    /// <summary>
    /// Phases B (judge), C (apply) and D (verify), <b>to completion</b>. There is no
    /// approve-each-change mode; the only thing that ends a run early is
    /// <see cref="IRemodelRunReporter.StopRequested"/> or a limit.
    /// </summary>
    RemodelRunOutcome Run(string runDirectory, IRemodelRunReporter reporter);

    /// <summary>Activates the copy in SOLIDWORKS, re-opening it if it was closed.</summary>
    void ActivateCopy(string runDirectory);
}
