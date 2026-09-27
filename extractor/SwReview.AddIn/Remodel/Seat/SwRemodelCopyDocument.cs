using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel.Seat;

/// <summary>
/// The copy, as the bridge addresses it after <c>remodel.open</c> (feature 004, T153; build order
/// lane B): <see cref="IRemodelDocument"/> with its inherited <see cref="IRemodelCopyTarget"/>,
/// <see cref="IRemodelTarget"/>, <see cref="IScopeSignalSource"/> and
/// <see cref="IGeometrySource"/>, over the copy's <c>IModelDoc2</c>. One interop member per
/// interface member, reached through the accessors that member needs (the document's extension,
/// its feature manager, its custom property manager) and nothing else.
///
/// <b>It calls COM directly and gates nothing itself</b> (T153's amendment, decision 17A). The
/// bridge already gates every call it makes on this object from outside - writes through
/// <c>RemodelScope.Write</c> or the remodel gate under interface-qualified keys, reads under bare
/// keys, the geometry reading under <see cref="RemodelGeometry.Read"/>'s - so a gate in here would
/// gate each call twice and log a bare write key the stage-1 guard passes through its read-only
/// branch. The one path with no gate around it, <see cref="IRemodelTarget"/>'s reads in
/// <c>VerifyTarget</c> and <c>RemodelCopy.AssertOpenedAtCopy</c>, stays ungated as it is over the
/// fakes. The equation manager and the mass property are lane A's shared, ungated
/// <see cref="SwEquationManager"/> and <see cref="SwMassProperty"/>; the scope signals are the
/// shared <see cref="SwScopeSignalReader"/>, the one the probe reads the source with.
///
/// It is built only by <see cref="SwRemodelBridgeSeat.OpenDocument"/>, over the document that
/// call opened at the copy's own path, and takes no path of its own: the one path-taking member,
/// <see cref="GetOpenDocumentIdentity"/>, is <c>VerifyTarget</c>'s check 3 and is handed the copy
/// path the scope holds.
///
/// Compiled here and fake-tested with recording stand-ins; what SOLIDWORKS answers to each call is
/// a seat item (research R13.8, "What only a seat can show").
/// </summary>
public sealed class SwRemodelCopyDocument : IRemodelDocument
{
    /// <summary><c>swMoveRollbackBarTo_e.swMoveRollbackBarToEnd</c> (VERIFIED value 1).</summary>
    private const int RollbackToEnd = (int)swMoveRollbackBarTo_e.swMoveRollbackBarToEnd;

    /// <summary>
    /// <c>swPersistReferencedObjectStates_e.swPersistReferencedObject_Invalid</c> (VERIFIED value
    /// 1): what a persist ref that does not even decode answers, without asking SOLIDWORKS.
    /// </summary>
    private const int InvalidReference = (int)swPersistReferencedObjectStates_e.swPersistReferencedObject_Invalid;

    private readonly ISldWorks _swApp;
    private readonly IModelDoc2 _document;
    private readonly SwScopeSignalReader _signals;

    public SwRemodelCopyDocument(ISldWorks swApp, IModelDoc2 document)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _document = document ?? throw new ArgumentNullException(nameof(document));
        _signals = new SwScopeSignalReader(document);
    }

    // ---- IRemodelTarget: VerifyTarget's four reads ---------------------------------------------

    /// <inheritdoc />
    public string? GetPathName() => _document.GetPathName();

    /// <summary>
    /// <c>ICustomPropertyManager.Get4(fieldName, false, out value, out resolved)</c> on the
    /// document-level set: the raw value when <c>Get4</c> answers true - read as "found", as
    /// PROBE-12's host reads it - and null ("the property is not there") when it answers false.
    /// </summary>
    public string? GetSessionTag(string fieldName)
    {
        bool found = Properties().Get4(fieldName, false, out string value, out string _);
        return found ? value : null;
    }

    /// <inheritdoc />
    public IntPtr GetDocumentIdentity() => Identity(_document);

    /// <inheritdoc />
    public IntPtr GetOpenDocumentIdentity(string documentPath)
    {
        object? open = _swApp.GetOpenDocumentByName(documentPath);
        return open == null ? IntPtr.Zero : Identity(open);
    }

    // ---- IRemodelCopyTarget: the session tag ---------------------------------------------------

    /// <inheritdoc />
    public int WriteSessionTag(string fieldName, int fieldType, string fieldValue, int overwriteExisting) =>
        Properties().Add3(fieldName, fieldType, fieldValue, overwriteExisting);

    /// <inheritdoc />
    public int RemoveSessionTag(string fieldName) => Properties().Delete2(fieldName);

    // ---- IScopeSignalSource: the reader the probe reads the source with ------------------------

    /// <inheritdoc />
    public int GetDocumentType() => _signals.GetDocumentType();

    /// <inheritdoc />
    public int? GetBodyCount(int bodyType) => _signals.GetBodyCount(bodyType);

    /// <inheritdoc />
    public bool? IsWeldment() => _signals.IsWeldment();

    /// <inheritdoc />
    public bool? HasSheetMetalFolder() => _signals.HasSheetMetalFolder();

    /// <inheritdoc />
    public bool? HasMeshBody() => _signals.HasMeshBody();

    /// <inheritdoc />
    public bool? HasGraphicsBody() => _signals.HasGraphicsBody();

    /// <inheritdoc />
    public bool? Is3DInterconnect() => _signals.Is3DInterconnect();

    /// <inheritdoc />
    public IReadOnlyList<string>? GetImportedFileNames() => _signals.GetImportedFileNames();

    /// <inheritdoc />
    public IReadOnlyList<string>? GetConfigurationNames() => _signals.GetConfigurationNames();

    /// <inheritdoc />
    public IReadOnlyList<RmsNamedFolder>? GetFolders() => _signals.GetFolders();

    // ---- IGeometrySource: what remodel.geometry measures ---------------------------------------

    /// <inheritdoc />
    public IMassPropertyReading? CreateMassProperty() =>
        Extension().CreateMassProperty2() is IMassProperty2 massProperty ? new SwMassProperty(massProperty) : null;

    /// <summary>
    /// <c>IPartDoc.GetBodies2(bodyType, false)</c>: null for "there are none", which is what the
    /// API answers for a part with no body of that type. An answer that cannot be read raises
    /// rather than reading as "none", and so does a document that is not a part, because
    /// <see cref="RemodelGeometry"/> would report "none" as a part with no body.
    /// </summary>
    public IReadOnlyList<object>? GetBodies(int bodyType)
    {
        object? answer = Part().GetBodies2(bodyType, false);
        if (answer == null)
        {
            return null;
        }

        object?[]? elements = SwRemodelReads.Elements(answer);
        if (elements == null || Array.IndexOf(elements, null) >= 0)
        {
            throw new InvalidOperationException(
                "GetBodies2 answered something that is not a list of bodies, so the copy's bodies "
                + "cannot be read; it is not read as a part with none.");
        }

        return elements!;
    }

    /// <summary><c>IBody2.GetFaceCount()</c>; a body that is not an <c>IBody2</c> is unreadable (null), never zero.</summary>
    public int? GetFaceCount(object body) => body is IBody2 readable ? readable.GetFaceCount() : (int?)null;

    /// <summary><c>IBody2.GetEdgeCount()</c>; a body that is not an <c>IBody2</c> is unreadable (null), never zero.</summary>
    public int? GetEdgeCount(object body) => body is IBody2 readable ? readable.GetEdgeCount() : (int?)null;

    /// <summary>
    /// <c>IPartDoc.GetMaterialPropertyName2(ConfigName, out Database)</c> for the active
    /// configuration, by its name, as the dump reads it (<c>PropertyDumper.ReadMaterial</c>). Null
    /// is unknown - the configuration's name could not be read, or the document is not a part - and
    /// SOLIDWORKS's answer is handed back unchanged, so an empty string stays "no material".
    /// </summary>
    public string? GetMaterialName()
    {
        if (!(_document is IPartDoc part))
        {
            return null;
        }

        string? configuration = _document.ConfigurationManager?.ActiveConfiguration?.Name;
        return configuration == null ? null : part.GetMaterialPropertyName2(configuration, out string _);
    }

    // ---- IRemodelDocument ----------------------------------------------------------------------

    /// <summary>
    /// <c>IModelDocExtension.GetObjectByPersistReference3(PersistId, out ErrorCode)</c>, with the
    /// reference decoded by <see cref="PersistRefCodec"/>. A string that does not decode answers
    /// null with <c>swPersistReferencedObject_Invalid</c> and asks SOLIDWORKS nothing, so the bridge
    /// reports it as <c>persist_ref_unresolved</c> like any other ref that will not resolve.
    /// </summary>
    public object? ResolveByPersistReference(string persistRef, out int errorCode)
    {
        byte[] bytes;
        try
        {
            bytes = PersistRefCodec.Decode(persistRef);
        }
        catch (PersistRefError)
        {
            errorCode = InvalidReference;
            return null;
        }

        return Extension().GetObjectByPersistReference3(bytes, out errorCode);
    }

    /// <inheritdoc />
    public string? GetPersistReference(object feature) => SwRemodelReads.PersistReference(_document, AsFeature(feature));

    /// <summary>
    /// <c>IFeatureManager.GetFeatures(true)</c>: the top-level tree, in the order SOLIDWORKS
    /// answers it. A tree that cannot be read raises: a part always has its origin and planes, so
    /// no tree is not an empty tree, and a plan made against one would move nothing it meant to.
    /// </summary>
    public IReadOnlyList<object> GetFeaturesInOrder()
    {
        IReadOnlyList<IFeature>? features = SwRemodelReads.Features(_document, topLevelOnly: true);
        if (features == null)
        {
            throw new InvalidOperationException(
                "GetFeatures(true) could not be read as a list of features, so the copy's tree is "
                + "unknown and no command may be planned against it.");
        }

        return features;
    }

    /// <inheritdoc />
    public string? GetFeatureName(object feature) => AsFeature(feature).Name;

    /// <inheritdoc />
    public string? GetFeatureDescription(object feature) => AsFeature(feature).Description;

    /// <inheritdoc />
    public string? GetFeatureTypeName(object feature) => AsFeature(feature).GetTypeName2();

    /// <inheritdoc />
    public bool IsRolledBack(object feature) => AsFeature(feature).IsRolledBack();

    /// <inheritdoc />
    public int GetFeatureErrorCode(object feature, out bool isWarning) => AsFeature(feature).GetErrorCode2(out isWarning);

    /// <inheritdoc />
    public void SetFeatureName(object feature, string name) => AsFeature(feature).Name = name;

    /// <inheritdoc />
    public void SetFeatureDescription(object feature, string text) => AsFeature(feature).Description = text;

    /// <inheritdoc />
    public bool SelectFeature(object feature, bool append, int mark) => AsFeature(feature).Select2(append, mark);

    /// <inheritdoc />
    public void ClearSelection() => _document.ClearSelection2(true);

    /// <inheritdoc />
    public bool ReorderFeature(string featureName, string targetName, int location) =>
        Extension().ReorderFeature(featureName, targetName, location);

    /// <inheritdoc />
    public object? InsertFeatureTreeFolder(int type) => Manager().InsertFeatureTreeFolder2(type);

    /// <summary>
    /// <c>IFeatureManager.FeatureFolderLocation(Feature)</c>. Its parameter is the interop's
    /// <c>Feature</c> coclass interface, which every feature SOLIDWORKS hands back also is.
    /// </summary>
    public object? GetFeatureFolder(object feature) => Manager().FeatureFolderLocation((Feature)AsFeature(feature));

    /// <inheritdoc />
    public bool EditRollbackToEnd() => Manager().EditRollback(RollbackToEnd, string.Empty);

    /// <inheritdoc />
    public bool ForceRebuild(bool topOnly) => _document.ForceRebuild3(topOnly);

    /// <inheritdoc />
    public int GetWhatsWrongCount() => Extension().GetWhatsWrongCount();

    /// <summary>
    /// <c>IModelDocExtension.GetWhatsWrong</c>, one entry per element as <see cref="RemodelWhatsWrong"/>
    /// reads them; no entries when the call answers false. Corroborating only: the per-feature
    /// <c>GetErrorCode2</c> walk is the primary reading and <c>GetWhatsWrongCount()</c> the count.
    /// </summary>
    public IReadOnlyList<string> GetWhatsWrong() =>
        Extension().GetWhatsWrong(out object features, out object errorCodes, out object warnings)
            ? RemodelWhatsWrong.Entries(features, errorCodes, warnings)
            : new string[0];

    /// <summary><c>IModelDoc2.GetEquationMgr()</c>, as lane A's shared <see cref="SwEquationManager"/>.</summary>
    public IEquationTarget Equations
    {
        get
        {
            IEquationMgr? manager = _document.GetEquationMgr();
            if (manager == null)
            {
                throw new InvalidOperationException("GetEquationMgr answered no equation manager for the copy.");
            }

            return new SwEquationManager(manager);
        }
    }

    /// <inheritdoc />
    public bool Save(int options, out int errors, out int warnings)
    {
        // Save3's two counts are [in, out] (ref), so they start at zero rather than unassigned.
        errors = 0;
        warnings = 0;
        return _document.Save3(options, ref errors, ref warnings);
    }

    /// <inheritdoc />
    public bool GetSaveFlag() => _document.GetSaveFlag();

    /// <summary>
    /// <c>IModelDoc2.GetUnits()</c>'s first element, named by <see cref="RemodelLengthUnits"/>; null
    /// is unknown, and a change that needs the unit refuses rather than assuming metres.
    /// </summary>
    public string? GetLengthUnit() => RemodelLengthUnits.FromUnits(_document.GetUnits());

    // ---- the accessors -------------------------------------------------------------------------

    /// <summary>
    /// <c>Marshal.GetIUnknownForObject</c>, released at once: the pointer is an identity to
    /// compare, never a reference to keep. The object itself is not released, because the runtime
    /// hands back one wrapper per COM identity and releasing it would release the copy's own.
    /// </summary>
    private static IntPtr Identity(object comObject)
    {
        IntPtr unknown = Marshal.GetIUnknownForObject(comObject);
        Marshal.Release(unknown);
        return unknown;
    }

    private static IFeature AsFeature(object feature) =>
        feature as IFeature
            ?? throw new ArgumentException(
                $"a {feature?.GetType().Name ?? "null"} is not a feature of the copy.", nameof(feature));

    private IPartDoc Part() =>
        _document as IPartDoc
            ?? throw new InvalidOperationException("the copy is not a part document, and the re-modeler works on parts only.");

    private IModelDocExtension Extension() =>
        _document.Extension ?? throw new InvalidOperationException("the copy answered no document extension.");

    private IFeatureManager Manager() =>
        _document.FeatureManager ?? throw new InvalidOperationException("the copy answered no feature manager.");

    /// <summary><c>IModelDocExtension.get_CustomPropertyManager("")</c>: the document-level set, never a configuration's.</summary>
    private ICustomPropertyManager Properties() =>
        Extension().get_CustomPropertyManager(string.Empty)
            ?? throw new InvalidOperationException(
                "the copy answered no document-level custom property manager, so its session tag "
                + "can be neither read nor written.");
}
