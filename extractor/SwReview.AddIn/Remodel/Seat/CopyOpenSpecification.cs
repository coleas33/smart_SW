using System;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel.Seat;

/// <summary>
/// How the copy is opened, written once (feature 004, T155; build order lane B): the
/// <c>IDocumentSpecification</c> <c>ISldWorks.OpenDoc7</c> is handed, with its four flags derived
/// from the one pinned integer, <see cref="RemodelCopy.OpenOptions"/> -
/// <c>Silent | LoadModel = 17</c>, and never <c>ReadOnly(2)</c> or <c>ViewOnly(4)</c>, because a
/// copy opened either way cannot be changed and the run would report a success it never made.
///
/// Both opens of a copy use it: the bridge seat's <c>remodel.open</c>
/// (<see cref="SwRemodelBridgeSeat.OpenDocument"/>) and the pane's <c>remodel.open_copy</c>
/// (<see cref="SwRemodelSeat"/>), so the flags cannot drift apart between them, nor from the
/// integer the tests and the manifest pin.
/// </summary>
public static class CopyOpenSpecification
{
    /// <summary>
    /// <c>ISldWorks.GetOpenDocSpec(copyPath)</c>, then <see cref="Apply"/>. A seat that will not
    /// describe how to open the path raises, naming it.
    /// </summary>
    public static IDocumentSpecification For(ISldWorks swApp, string copyPath)
    {
        if (swApp == null)
        {
            throw new ArgumentNullException(nameof(swApp));
        }

        if (string.IsNullOrWhiteSpace(copyPath))
        {
            throw new ArgumentException("A copy path is required.", nameof(copyPath));
        }

        var specification = swApp.GetOpenDocSpec(copyPath) as IDocumentSpecification;
        if (specification == null)
        {
            throw new InvalidOperationException("SOLIDWORKS would not describe how to open '" + copyPath + "'.");
        }

        Apply(specification);
        return specification;
    }

    /// <summary>
    /// A part, and the four flags <see cref="RemodelCopy.OpenOptions"/> composes, each read off the
    /// integer rather than restated, in the order the integer's bits run. The integer holds no other
    /// bit (a test pins it), so nothing it says is dropped here.
    /// </summary>
    public static void Apply(IDocumentSpecification specification)
    {
        if (specification == null)
        {
            throw new ArgumentNullException(nameof(specification));
        }

        specification.DocumentType = (int)swDocumentTypes_e.swDocPART;
        specification.Silent = Has(swOpenDocOptions_e.swOpenDocOptions_Silent);
        specification.ReadOnly = Has(swOpenDocOptions_e.swOpenDocOptions_ReadOnly);
        specification.ViewOnly = Has(swOpenDocOptions_e.swOpenDocOptions_ViewOnly);
        specification.LoadModel = Has(swOpenDocOptions_e.swOpenDocOptions_LoadModel);
    }

    private static bool Has(swOpenDocOptions_e option) => (RemodelCopy.OpenOptions & (int)option) != 0;
}
