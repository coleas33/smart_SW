using System;
using System.Globalization;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.Remodel.Seat;

/// <summary>
/// The extractor-side seat (feature 004, T155; build order lane B): the SOLIDWORKS application as
/// the bridge's <c>remodel.*</c> commands reach it - <see cref="SwReview.Extractor.Rms.IRemodelSeat"/>
/// with its <see cref="IRemodelToggleHost"/> - over the add-in's <c>ISldWorks</c>. Three things and
/// no more: the read-only view of the engineer's open source, the one open of the copy, and the
/// close; plus the three system toggles and <c>CommandInProgress</c> the run sets and restores.
///
/// Named apart from the add-in's <see cref="SwRemodelSeat"/>, which implements the add-in's own
/// <see cref="IRemodelSeat"/> for <c>remodel.open_copy</c>. The two seats share how a copy is opened
/// (<see cref="CopyOpenSpecification"/>) and nothing else.
///
/// <b>It calls COM directly and gates nothing itself</b> (T153's amendment): the bridge gates every
/// call on it - the open and the close under <c>OpenDoc7</c> and <c>ISldWorks.CloseDoc</c>, the
/// toggles through <see cref="RemodelSystemToggles"/>. What it does check, before any call, is that
/// a path it is asked to open or close is inside a run folder's <c>copy/</c> subfolder
/// (<see cref="RemodelCopy.RunDirectoryOf"/>'s rule) - the bridge has already checked the path is
/// this run's copy, so reaching the refusal is a bug in the caller - and that the options are
/// exactly <see cref="RemodelCopy.OpenOptions"/> (defaults taken 2026-09-27, the owner may revise).
///
/// <see cref="GetVault"/> answers null, which means "not read by this build", until T139 adds a vault
/// read (T155's amendment, research R13.5): no PDM API is referenced anywhere in the product.
/// </summary>
public sealed class SwRemodelBridgeSeat : SwReview.Extractor.Rms.IRemodelSeat
{
    private readonly ISldWorks _swApp;
    private readonly SwRemodelToggleHost _toggles;

    public SwRemodelBridgeSeat(ISldWorks swApp)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _toggles = new SwRemodelToggleHost(swApp);
    }

    /// <summary>
    /// A fresh <see cref="SwRemodelProbeSource"/> on every read, so each probe binds its own
    /// document and no <c>IModelDoc2</c> outlives the probe that read it.
    /// </summary>
    public IRemodelProbeSource ProbeSource => new SwRemodelProbeSource(_swApp);

    /// <summary>
    /// <c>ISldWorks.OpenDoc7</c> with the specification <see cref="CopyOpenSpecification"/> builds -
    /// <c>Silent | LoadModel = 17</c> exactly - and the opened document as the copy's adapter. An
    /// <c>OpenDoc7</c> that answers no document raises <c>open_failed</c> naming the load error and
    /// warning bits, so the run log says why rather than only that it failed; the bridge's cleanup
    /// is the same either way.
    /// </summary>
    public IRemodelDocument? OpenDocument(string documentPath, int options)
    {
        if (options != RemodelCopy.OpenOptions)
        {
            throw new ArgumentOutOfRangeException(
                nameof(options),
                options,
                "the copy is opened with RemodelCopy.OpenOptions ("
                + RemodelCopy.OpenOptions.ToString(CultureInfo.InvariantCulture)
                + ", Silent | LoadModel) and nothing else: never read-only and never view-only.");
        }

        RequireCopyPath(documentPath, nameof(documentPath));
        IDocumentSpecification specification = CopyOpenSpecification.For(_swApp, documentPath);

        IModelDoc2? opened = _swApp.OpenDoc7(specification);
        if (opened == null)
        {
            throw new RemodelCopyError(
                RemodelErrorCodes.OpenFailed,
                "SOLIDWORKS would not open the copy at '" + documentPath + "': "
                + FileLoadErrors.Describe(specification.Error, specification.Warning) + ".");
        }

        return new SwRemodelCopyDocument(_swApp, opened);
    }

    /// <summary><c>ISldWorks.CloseDoc(documentPath)</c>, on a path inside a run folder's <c>copy/</c> only.</summary>
    public void CloseDocument(string documentPath)
    {
        RequireCopyPath(documentPath, nameof(documentPath));
        _swApp.CloseDoc(documentPath);
    }

    /// <summary>Null, "not read by this build", until T139 adds a vault read (research R13.5).</summary>
    public VaultReference? GetVault(string sourcePath) => null;

    /// <inheritdoc />
    public bool GetUserPreferenceToggle(int toggle) => _toggles.GetUserPreferenceToggle(toggle);

    /// <inheritdoc />
    public void SetUserPreferenceToggle(int toggle, bool value) => _toggles.SetUserPreferenceToggle(toggle, value);

    /// <inheritdoc />
    public bool GetCommandInProgress() => _toggles.GetCommandInProgress();

    /// <inheritdoc />
    public void SetCommandInProgress(bool value) => _toggles.SetCommandInProgress(value);

    /// <summary>
    /// The seat opens and closes nothing but a copy: a path whose folder is not a run folder's
    /// <c>copy/</c> is refused before SOLIDWORKS is asked anything, by the rule
    /// <see cref="RemodelCopy.RunDirectoryOf"/> states once.
    /// </summary>
    private static void RequireCopyPath(string documentPath, string parameterName)
    {
        try
        {
            RemodelCopy.RunDirectoryOf(documentPath);
        }
        catch (MutatingCallError refusal)
        {
            throw new ArgumentException(refusal.Message, parameterName, refusal);
        }
    }
}
