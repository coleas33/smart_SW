using System;
using System.IO;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Dump;
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

    public DumpSummary Run(string outputDirectory, Action<string> progress)
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
            };

            DumpResult result = SwDump.CreateWriter(_swApp, session).Write(options);

            return new DumpSummary(
                result.PackageFilePath,
                result.Package.Components.Count,
                result.Gaps.Count);
        });
    }
}
