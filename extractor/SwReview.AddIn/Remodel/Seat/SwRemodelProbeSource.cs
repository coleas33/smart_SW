using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel.Seat;

/// <summary>
/// The engineer's <b>already-open</b> source, read-only, as <c>remodel.probe_scope</c> and
/// <c>remodel.open</c>'s re-check read it (feature 004, T154; build order lane B):
/// <see cref="IRemodelProbeSource"/> over <c>ISldWorks.GetOpenDocumentByName</c>.
///
/// It reads only the members of contracts/bridge-remodel.md's <c>scope_signals</c> table (through
/// the shared <see cref="SwScopeSignalReader"/>) plus <c>GetType</c>, <c>GetSaveFlag</c> and
/// <c>ListExternalFileReferencesCount2</c>, and since U26 (2026-09-28) <c>IsOpenedReadOnly</c> and
/// the one system option that decides whether a read-only source's save flag can be believed
/// (<c>GetUserPreferenceToggle(swExtRefNoPromptOrSave)</c>). <b>It opens nothing</b>: a source SOLIDWORKS does not
/// already have open answers false, which the bridge reports as <c>source_not_open</c>, because
/// opening it to answer would give away the one property the constitution's exception rests on.
/// And it keeps no <c>IModelDoc2</c> past the probe: the seat hands out a fresh one for each probe
/// (<see cref="SwRemodelBridgeSeat.ProbeSource"/>), and nothing holds it after.
///
/// <see cref="IsOpen"/> binds the document the reads that follow are made on, which is why the
/// bridge calls it first; a read asked for before a document is bound raises rather than reading
/// something else (default taken 2026-09-27, the owner may revise). Ungated, like every class in
/// this folder: the bridge gates each member from outside.
/// </summary>
public sealed class SwRemodelProbeSource : IRemodelProbeSource
{
    private readonly ISldWorks _swApp;
    private IModelDoc2? _document;
    private SwScopeSignalReader? _signals;

    public SwRemodelProbeSource(ISldWorks swApp)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
    }

    /// <summary>
    /// <c>ISldWorks.GetOpenDocumentByName(documentPath)</c>: true, and that document bound for the
    /// reads that follow, when SOLIDWORKS has it open; false, and nothing bound, when it has not.
    /// An answer that is not a document raises: "not open" would be a claim nobody measured.
    /// </summary>
    public bool IsOpen(string documentPath)
    {
        if (string.IsNullOrWhiteSpace(documentPath))
        {
            throw new ArgumentException("A source path is required.", nameof(documentPath));
        }

        _document = null;
        _signals = null;

        object? open = _swApp.GetOpenDocumentByName(documentPath);
        if (open == null)
        {
            return false;
        }

        if (!(open is IModelDoc2 document))
        {
            throw new InvalidOperationException(
                $"GetOpenDocumentByName answered a {open.GetType().Name} for the source, which is not a "
                + "document, so whether the source is open is unknown.");
        }

        _document = document;
        _signals = new SwScopeSignalReader(document);
        return true;
    }

    /// <inheritdoc />
    public bool GetSaveFlag() => Bound().GetSaveFlag();

    /// <inheritdoc />
    public bool IsOpenedReadOnly() => Bound().IsOpenedReadOnly();

    /// <inheritdoc />
    /// <remarks>
    /// An application-wide option, asked about only once a source is bound - the question is
    /// always about that source's save flag - so a read before <see cref="IsOpen"/> raises like
    /// every other read here.
    /// </remarks>
    public bool GetDiscardsReadOnlyChanges()
    {
        Bound();
        return _swApp.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swExtRefNoPromptOrSave);
    }

    /// <inheritdoc />
    public int GetExternalReferenceCount() => Bound().ListExternalFileReferencesCount2();

    /// <inheritdoc />
    public int GetDocumentType() => Signals().GetDocumentType();

    /// <inheritdoc />
    public int? GetBodyCount(int bodyType) => Signals().GetBodyCount(bodyType);

    /// <inheritdoc />
    public bool? IsWeldment() => Signals().IsWeldment();

    /// <inheritdoc />
    public bool? HasSheetMetalFolder() => Signals().HasSheetMetalFolder();

    /// <inheritdoc />
    public bool? HasMeshBody() => Signals().HasMeshBody();

    /// <inheritdoc />
    public bool? HasGraphicsBody() => Signals().HasGraphicsBody();

    /// <inheritdoc />
    public bool? Is3DInterconnect() => Signals().Is3DInterconnect();

    /// <inheritdoc />
    public IReadOnlyList<string>? GetImportedFileNames() => Signals().GetImportedFileNames();

    /// <inheritdoc />
    public IReadOnlyList<string>? GetConfigurationNames() => Signals().GetConfigurationNames();

    /// <inheritdoc />
    public IReadOnlyList<RmsNamedFolder>? GetFolders() => Signals().GetFolders();

    /// <inheritdoc />
    public IReadOnlyList<string>? GetFeatureTypeNames() => Signals().GetFeatureTypeNames();

    private IModelDoc2 Bound() => _document ?? throw NotBound();

    private SwScopeSignalReader Signals() => _signals ?? throw NotBound();

    private static InvalidOperationException NotBound() =>
        new InvalidOperationException(
            "no source is bound: IsOpen binds the engineer's open document, and it has not answered "
            + "true for this probe.");
}
