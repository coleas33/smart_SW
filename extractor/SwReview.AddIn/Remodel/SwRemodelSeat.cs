using System;
using System.Globalization;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.AddIn.Review;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.Remodel;

/// <summary>
/// The real <see cref="IRemodelSeat"/>: `remodel.open_copy`, on the SOLIDWORKS application
/// thread.
///
/// Two paths, in this order, because the copy may or may not still be open when the engineer
/// presses the button - the run closes it, and `remodel.discard_copy` may have been pressed on
/// an earlier run:
///
/// 1. <c>GetOpenDocumentByName</c> and, if it is there, <c>ActivateDoc3</c> with
///    <c>swDontRebuildActiveDoc</c>. Not rebuilding is deliberate: the copy was saved after the
///    geometry gate measured it, and a rebuild on activation would dirty a document the report
///    has already been written against.
/// 2. Otherwise <c>OpenDoc7</c> with <c>Silent</c> and <c>LoadModel</c> - the
///    <c>RemodelCopy.OpenOptions</c> integer 17 that `remodel.open` pins - and never
///    <c>ReadOnly</c> or <c>ViewOnly</c>. A copy the engineer cannot edit is a copy they cannot
///    accept: the whole point of the run is that they Save As it somewhere of their own
///    choosing.
///
/// Compiled but not unit tested, like the add-in's other interop-only classes
/// (<see cref="SwReviewDump"/>): everything that decides anything is in
/// <see cref="BackendRemodelPipeline"/>, which is tested over a fake of this interface.
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

    private void Activate(IModelDoc2 open)
    {
        int errors = 0;
        object? activated = _swApp.ActivateDoc3(
            open.GetTitle(),
            UseUserPreferences: false,
            Option: (int)swRebuildOnActivation_e.swDontRebuildActiveDoc,
            Errors: ref errors);

        if (activated == null || errors != 0)
        {
            throw new InvalidOperationException(
                "SOLIDWORKS would not activate the copy that is already open ("
                + open.GetPathName() + "): ActivateDoc3 reported "
                + errors.ToString(CultureInfo.InvariantCulture) + ".");
        }
    }

    private void Open(string copyPath)
    {
        var specification = _swApp.GetOpenDocSpec(copyPath) as IDocumentSpecification;
        if (specification == null)
        {
            throw new InvalidOperationException(
                "SOLIDWORKS would not describe how to open '" + copyPath + "'.");
        }

        specification.DocumentType = (int)swDocumentTypes_e.swDocPART;

        // The two halves of RemodelCopy.OpenOptions (Silent | LoadModel = 17), stated as the
        // specification's own members, and the two that are never set.
        specification.Silent = true;
        specification.LoadModel = true;
        specification.ReadOnly = false;
        specification.ViewOnly = false;

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
