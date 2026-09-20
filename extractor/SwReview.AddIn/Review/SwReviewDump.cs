using System;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.Review;

/// <summary>
/// The real <see cref="IReviewDump"/>: the same <see cref="PackageWriter"/> the console runs,
/// in this process, against the document already on screen.
///
/// In-process is the whole point of the pane (spec US4): a second SOLIDWORKS attach could bind
/// a different session than the one the engineer is looking at, and the console host would
/// need the model saved first. The cost is that the dump occupies the application thread for
/// as long as it takes, which is why the progress lines below exist - they are the only thing
/// the engineer sees while SOLIDWORKS is busy.
///
/// Compiled but not unit tested, like the other interop-only classes in the extractor: the
/// decisions live in <see cref="PackageWriter"/> and in <see cref="ReviewHost"/>, both of
/// which are tested with fakes.
/// </summary>
public sealed class SwReviewDump : IReviewDump
{
    private readonly ISldWorks _swApp;
    private readonly IApplicationThread _thread;

    public SwReviewDump(ISldWorks swApp, IApplicationThread thread)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _thread = thread ?? throw new ArgumentNullException(nameof(thread));
    }

    /// <summary>Reuse guarded tree traversal without running geometry phases or writing files.</summary>
    public ReviewPreparation Prepare() => _thread.Invoke(() =>
    {
        SwSession session = SwSession.Attach(_swApp, documentPath: null, configurationName: null);
        var gaps = new GapCollector();
        var tree = new ComponentTreeDumper(session, new PersistRefService(session.Gate)).Traverse(
            gaps, new DumpOptions { Configuration = session.Configuration.Name });
        return new ReviewPreparation(tree, gaps);
    });

    public DumpSummary Run(
        string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full)
    {
        if (outputDirectory == null)
        {
            throw new ArgumentNullException(nameof(outputDirectory));
        }

        if (progress == null)
        {
            throw new ArgumentNullException(nameof(progress));
        }

        return _thread.Invoke(() =>
        {
            progress("Attaching to the active document...");

            // documentPath and configurationName are null on purpose: whatever is active is
            // what is reviewed, and activating another configuration would rebuild the model
            // (constitution, read-only rule).
            SwSession session = SwSession.Attach(_swApp, documentPath: null, configurationName: null);

            progress(
                $"Extracting {Path.GetFileName(session.DocumentPath)} "
                + $"[{session.Configuration.Name}]...");

            var options = new DumpOptions
            {
                OutputDirectory = outputDirectory,
                Configuration = session.Configuration.Name,
                Meshes = MeshFormat.Glb,
                Faces = FaceScope.Needed,

                // The caller's profile, not this class's opinion: the Review tab asks for
                // Full and a Model check asks for ModelCheck, and PackageWriter records
                // which one ran on the package it writes.
                Profile = profile,
            };

            DumpResult result = SwDump.CreateWriter(_swApp, session).Write(options);

            return new DumpSummary(
                result.PackageFilePath,
                result.Package.Components.Count,
                result.Gaps.Count,

                // Lightweight or suppressed: SOLIDWORKS itself never resolved them, so the
                // extractor read nothing off them and nothing downstream can see them either
                // (docs/feature-request-resolve-lightweight.md).
                result.Package.Components.Count(
                    component => component.Suppression != SuppressionState.Resolved),
                result.Package.Documents.Count,
                result.Package.Features.Count,
                result.Package.Equations.Count,

                // Null when the phase did not run, which is what the two arrays being null
                // means: a zero would say "this weldment has no cut list" or "this drawing has
                // no sheets", which is a statement about the design rather than about the dump.
                result.Package.CutListItems?.Count,
                result.Package.DrawingRecords?.Sum(drawing => drawing.Sheets.Count));
        });
    }
}
