using System;
using System.Globalization;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.AddIn.Remodel.Seat;
using SwReview.AddIn.Review;
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
/// Everything that decides anything is in <see cref="BackendRemodelPipeline"/>, which is tested
/// over a fake of this interface. <see cref="ActivateOpenCopy"/> is also tested over the
/// recording stand-ins of feature 004's build order (`SwRemodelSeatTests`), since what it must
/// never do - open a document - is a property of the calls it makes.
/// </summary>
public sealed class SwRemodelSeat : IRemodelSeat
{
    private readonly ISldWorks _swApp;
    private readonly IApplicationThread _thread;

    public SwRemodelSeat(ISldWorks swApp, IApplicationThread thread)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _thread = thread ?? throw new ArgumentNullException(nameof(thread));
    }

    public void ActivateOrOpen(string copyPath)
    {
        if (copyPath == null)
        {
            throw new ArgumentNullException(nameof(copyPath));
        }

        _thread.Invoke<object?>(() =>
        {
            var open = _swApp.GetOpenDocumentByName(copyPath) as IModelDoc2;
            if (open != null)
            {
                Activate(open);
                return null;
            }

            Open(copyPath);
            return null;
        });
    }

    /// <summary>
    /// 004 T159: the copy made the active document before a dump - found among the documents
    /// SOLIDWORKS already has open and activated by <see cref="ActivateWithoutRebuild"/>, the
    /// same call `remodel.open_copy` makes - and the path of whatever is active afterwards, or
    /// null when SOLIDWORKS does not have the copy open or activated no document.
    ///
    /// <b>Activate only.</b> A copy that is not open is answered null and left alone: no
    /// <c>OpenDoc7</c>, no open request, no fallback (research R13.8, D6). And the error bits
    /// <c>ActivateDoc3</c> reports do not decide on their own - a copy that needs a rebuild is
    /// still activated, without one, as asked - the active document does, and
    /// <see cref="BackendRemodelPipeline"/> compares its path with the copy's.
    /// </summary>
    public string? ActivateOpenCopy(string copyPath)
    {
        if (copyPath == null)
        {
            throw new ArgumentNullException(nameof(copyPath));
        }

        return _thread.Invoke<string?>(() =>
        {
            var open = _swApp.GetOpenDocumentByName(copyPath) as IModelDoc2;
            if (open == null || ActivateWithoutRebuild(open, out _) == null)
            {
                return null;
            }

            return (_swApp.ActiveDoc as IModelDoc2)?.GetPathName();
        });
    }

    private void Activate(IModelDoc2 open)
    {
        object? activated = ActivateWithoutRebuild(open, out int errors);

        if (activated == null || errors != 0)
        {
            throw new InvalidOperationException(
                "SOLIDWORKS would not activate the copy that is already open ("
                + open.GetPathName() + "): ActivateDoc3 reported "
                + errors.ToString(CultureInfo.InvariantCulture) + ".");
        }
    }

    /// <summary>
    /// The one <c>ActivateDoc3</c> both activations make: by the document's title, the user's
    /// preferences not consulted, and <c>swDontRebuildActiveDoc</c> - a rebuild on activation
    /// would dirty a copy the report was written against, or change the tree a dump is about to
    /// read.
    /// </summary>
    private object? ActivateWithoutRebuild(IModelDoc2 open, out int errors)
    {
        errors = 0;
        return _swApp.ActivateDoc3(
            open.GetTitle(),
            UseUserPreferences: false,
            Option: (int)swRebuildOnActivation_e.swDontRebuildActiveDoc,
            Errors: ref errors);
    }

    private void Open(string copyPath)
    {
        // RemodelCopy.OpenOptions (Silent | LoadModel = 17) as the specification's own members,
        // stated once for both opens of a copy (feature 004, build order lane B).
        IDocumentSpecification specification = CopyOpenSpecification.For(_swApp, copyPath);

        IModelDoc2? opened = _swApp.OpenDoc7(specification);
        if (opened == null)
        {
            throw new InvalidOperationException(
                "SOLIDWORKS would not open the copy at '" + copyPath + "': "
                + FileLoadErrors.Describe(specification.Error, specification.Warning)
                + ". The run folder still holds it"
                + (File.Exists(copyPath) ? "." : ", but the file is no longer there."));
        }
    }
}
