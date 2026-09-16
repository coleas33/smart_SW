using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Rms;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// One feature of a fake tree. The re-modeler addresses features by persistent reference and
/// never by name or index, so the ref is the identity here too and the name is data.
/// </summary>
public sealed class FakeFeature
{
    public FakeFeature(string persistRef, string name, string typeName = "Extrusion")
    {
        PersistRef = persistRef;
        Name = name;
        TypeName = typeName;
    }

    public string PersistRef { get; }

    public string? Name { get; set; }

    /// <summary>Null is <b>unreadable</b>, which is not the same as <c>""</c> (absent).</summary>
    public string? Description { get; set; } = string.Empty;

    public string TypeName { get; set; }

    public bool RolledBack { get; set; }

    /// <summary><c>swFeatureError_e</c>; <c>swFeatureErrorNone = 0</c>.</summary>
    public int ErrorCode { get; set; }

    public bool IsWarning { get; set; }

    /// <summary>The folder this feature sits in, as <c>FeatureFolderLocation</c> reports it.</summary>
    public FakeFeature? Folder { get; set; }

    public override string ToString() => Name ?? PersistRef;
}

/// <summary>
/// One body of a fake part, as the geometry reading walks it: the faces and edges it reports,
/// either of which may be unreadable and is then null rather than zero.
/// </summary>
public sealed class FakeBody
{
    public FakeBody(int faceCount, int edgeCount)
    {
        FaceCount = faceCount;
        EdgeCount = edgeCount;
    }

    /// <summary><c>IBody2.GetFaceCount()</c>; null is unreadable.</summary>
    public int? FaceCount { get; set; }

    /// <summary><c>IBody2.GetEdgeCount()</c>; null is unreadable.</summary>
    public int? EdgeCount { get; set; }
}

/// <summary>
/// The typed <c>IMassProperty2</c> the reading is taken through. Every read is recorded, so a
/// test can assert that <c>Recalculate()</c>'s Boolean was checked before any of them ran.
/// </summary>
public sealed class FakeMassProperty : IMassPropertyReading
{
    /// <summary>Every seam member called, in order.</summary>
    public List<string> Members { get; } = new List<string>();

    /// <summary>The integer <c>set_AccuracyLevel</c> was handed, asserted exactly.</summary>
    public int AccuracyLevel { get; private set; } = -1;

    /// <summary>What <c>set_SelectedItems</c> was handed: the bodies, and nothing else.</summary>
    public IReadOnlyList<object>? SelectedItems { get; private set; }

    public bool RecalculateAnswer { get; set; } = true;

    public double Volume { get; set; } = 0.00123456789;

    public double SurfaceArea { get; set; } = 0.0456;

    public double Mass { get; set; } = 3.21;

    public double Density { get; set; } = 2700.0;

    public IReadOnlyList<double>? CenterOfMass { get; set; } = new[] { 0.01, 0.02, 0.03 };

    public IReadOnlyList<double>? PrincipalMoments { get; set; } =
        new[] { 1.1e-5, 2.2e-5, 3.3e-5 };

    public void SetAccuracyLevel(int accuracyLevel)
    {
        Members.Add(nameof(SetAccuracyLevel));
        AccuracyLevel = accuracyLevel;
    }

    public void SetSelectedItems(IReadOnlyList<object> bodies)
    {
        Members.Add(nameof(SetSelectedItems));
        SelectedItems = bodies;
    }

    /// <summary>What <c>set_UseSystemUnits</c> was handed; false until it is set.</summary>
    public bool UseSystemUnits { get; private set; }

    public void SetUseSystemUnits(bool useSystemUnits)
    {
        Members.Add(nameof(SetUseSystemUnits));
        UseSystemUnits = useSystemUnits;
    }

    public bool Recalculate()
    {
        Members.Add(nameof(Recalculate));
        return RecalculateAnswer;
    }

    public double GetVolume()
    {
        Members.Add(nameof(GetVolume));
        return Volume;
    }

    public double GetSurfaceArea()
    {
        Members.Add(nameof(GetSurfaceArea));
        return SurfaceArea;
    }

    public IReadOnlyList<double>? GetCenterOfMass()
    {
        Members.Add(nameof(GetCenterOfMass));
        return CenterOfMass;
    }

    public IReadOnlyList<double>? GetPrincipalMomentsOfInertia()
    {
        Members.Add(nameof(GetPrincipalMomentsOfInertia));
        return PrincipalMoments;
    }

    public double GetMass()
    {
        Members.Add(nameof(GetMass));
        return Mass;
    }

    public double GetDensity()
    {
        Members.Add(nameof(GetDensity));
        return Density;
    }
}

/// <summary>The equation manager as the two verified helpers address it.</summary>
public sealed class FakeEquationManager : IEquationTarget
{
    /// <summary>Every seam member called, in order.</summary>
    public List<string> Members { get; } = new List<string>();

    public List<string> Equations { get; } = new List<string>();

    /// <summary>What <c>Add3</c> answers, and whether it actually adds (PROBE-6).</summary>
    public int Add3Answer { get; set; }

    public bool Add3Adds { get; set; } = true;

    public int Add2Answer { get; set; }

    public bool Add2Adds { get; set; } = true;

    /// <summary>Whether <c>set_Equation</c> actually writes (PROBE-7).</summary>
    public bool SetEquationWrites { get; set; } = true;

    public bool SetEquationAndConfigurationOptionWrites { get; set; } = true;

    /// <summary>Makes the read of an existing equation fail, so there is no inverse.</summary>
    public bool EquationUnreadable { get; set; }

    /// <summary>
    /// The rows whose text reads back null while the rest read normally, which is what a
    /// snapshot of a part with one unreadable equation has to survive.
    /// </summary>
    public HashSet<int> UnreadableIndexes { get; } = new HashSet<int>();

    /// <summary>What a write does to the count beyond adding or removing a row.</summary>
    public int CountDrift { get; set; }

    public int GetCount()
    {
        Members.Add(nameof(GetCount));
        return Equations.Count + CountDrift;
    }

    public string? GetEquation(int index)
    {
        Members.Add(nameof(GetEquation));
        if (EquationUnreadable || UnreadableIndexes.Contains(index))
        {
            return null;
        }

        return index >= 0 && index < Equations.Count ? Equations[index] : null;
    }

    public int Add3(int index, string equation, bool solve, int whichConfigurations, string[]? configNames)
    {
        Members.Add(nameof(Add3));
        if (Add3Adds)
        {
            Insert(index, equation);
        }

        return Add3Answer;
    }

    public int Add2(int index, string equation, bool solve)
    {
        Members.Add(nameof(Add2));
        if (Add2Adds)
        {
            Insert(index, equation);
        }

        return Add2Answer;
    }

    public void SetEquation(int index, string equation)
    {
        Members.Add(nameof(SetEquation));
        if (SetEquationWrites && index >= 0 && index < Equations.Count)
        {
            Equations[index] = equation;
        }
    }

    public int SetEquationAndConfigurationOption(
        int index, string equation, int whichConfigurations, string[]? configNames)
    {
        Members.Add(nameof(SetEquationAndConfigurationOption));
        if (SetEquationAndConfigurationOptionWrites && index >= 0 && index < Equations.Count)
        {
            Equations[index] = equation;
        }

        return 0;
    }

    public int Delete(int index)
    {
        Members.Add(nameof(Delete));
        if (index >= 0 && index < Equations.Count)
        {
            Equations.RemoveAt(index);
        }

        return 0;
    }

    private void Insert(int index, string equation)
    {
        if (index < 0 || index > Equations.Count)
        {
            Equations.Add(equation);
            return;
        }

        Equations.Insert(index, equation);
    }
}

/// <summary>
/// The engineer's already-open source as <c>remodel.probe_scope</c> reads it: reads only, no
/// handle handed back, and nothing opened to answer a question.
/// </summary>
public sealed class FakeProbeSource : IRemodelProbeSource
{
    /// <summary>Every seam member called, in order.</summary>
    public List<string> Members { get; } = new List<string>();

    /// <summary>The paths <see cref="IsOpen"/> was asked about.</summary>
    public List<string> OpenQueries { get; } = new List<string>();

    public bool Open { get; set; } = true;

    public int DocumentType { get; set; } = 1;

    public bool SaveFlag { get; set; }

    public int ExternalReferenceCount { get; set; }

    public ScopeSignalValues Signals { get; } = new ScopeSignalValues();

    public bool IsOpen(string documentPath)
    {
        Members.Add(nameof(IsOpen));
        OpenQueries.Add(documentPath);
        return Open;
    }

    public int GetDocumentType()
    {
        Members.Add(nameof(GetDocumentType));
        return DocumentType;
    }

    public bool GetSaveFlag()
    {
        Members.Add(nameof(GetSaveFlag));
        return SaveFlag;
    }

    public int GetExternalReferenceCount()
    {
        Members.Add(nameof(GetExternalReferenceCount));
        return ExternalReferenceCount;
    }

    public int? GetBodyCount(int bodyType)
    {
        Members.Add(nameof(GetBodyCount));
        return Signals.BodyCount(bodyType);
    }

    public bool? IsWeldment()
    {
        Members.Add(nameof(IsWeldment));
        return Signals.IsWeldment;
    }

    public bool? HasSheetMetalFolder()
    {
        Members.Add(nameof(HasSheetMetalFolder));
        return Signals.SheetMetalFolderPresent;
    }

    public bool? HasMeshBody()
    {
        Members.Add(nameof(HasMeshBody));
        return Signals.MeshBodyPresent;
    }

    public bool? HasGraphicsBody()
    {
        Members.Add(nameof(HasGraphicsBody));
        return Signals.GraphicsBodyPresent;
    }

    public bool? Is3DInterconnect()
    {
        Members.Add(nameof(Is3DInterconnect));
        return Signals.Is3DInterconnect;
    }

    public IReadOnlyList<string>? GetImportedFileNames()
    {
        Members.Add(nameof(GetImportedFileNames));
        return Signals.ImportedFileNames;
    }

    public IReadOnlyList<string>? GetConfigurationNames()
    {
        Members.Add(nameof(GetConfigurationNames));
        return Signals.ConfigurationNames;
    }

    public IReadOnlyList<RmsNamedFolder>? GetFolders()
    {
        Members.Add(nameof(GetFolders));
        return Signals.Folders;
    }
}

/// <summary>
/// The measurements a fake source hands back, shared by the probe fake and the document fake
/// so a test can make the copy's signals differ from the source's in exactly one field.
/// </summary>
public sealed class ScopeSignalValues
{
    public int? SolidBodyCount { get; set; } = 1;

    public int? SheetBodyCount { get; set; }

    public bool? IsWeldment { get; set; }

    public bool? SheetMetalFolderPresent { get; set; }

    public bool? MeshBodyPresent { get; set; }

    public bool? GraphicsBodyPresent { get; set; }

    public bool? Is3DInterconnect { get; set; }

    public IReadOnlyList<string>? ImportedFileNames { get; set; } = new string[0];

    public IReadOnlyList<string>? ConfigurationNames { get; set; } = new[] { "Default" };

    public IReadOnlyList<RmsNamedFolder>? Folders { get; set; } = new RmsNamedFolder[0];

    public int? BodyCount(int bodyType) => bodyType == 0 ? SolidBodyCount : SheetBodyCount;
}

/// <summary>
/// The copy, as every handler after <c>remodel.open</c> addresses it. One object holds the
/// whole surface - the four <c>VerifyTarget</c> reads, the signal reads, the tree, the
/// equations, the rebuild and the save - because in the product one <c>IModelDoc2</c> does.
/// </summary>
public sealed class FakeRemodelDocument : IRemodelDocument
{
    private readonly IntPtr _identity = new IntPtr(0x4001);

    public FakeRemodelDocument(string path, params FakeFeature[] features)
    {
        PathName = path;
        Features = new List<FakeFeature>(features);
    }

    /// <summary>Every seam member called, in order, across every call.</summary>
    public List<string> Members { get; } = new List<string>();

    /// <summary>The persist refs <see cref="ResolveByPersistReference"/> was asked about.</summary>
    public List<string> Resolved { get; } = new List<string>();

    public List<FakeFeature> Features { get; }

    public List<FakeFeature> Selected { get; } = new List<FakeFeature>();

    public ScopeSignalValues Signals { get; } = new ScopeSignalValues();

    public FakeEquationManager EquationManager { get; } = new FakeEquationManager();

    public string? PathName { get; set; }

    public string? SessionTag { get; set; }

    public int DocumentType { get; set; } = 1;

    public string? LengthUnit { get; set; } = "mm";

    /// <summary>Persist refs that answer with a non-zero <c>GetObjectByPersistReference3</c> code.</summary>
    public Dictionary<string, int> ResolveErrors { get; } =
        new Dictionary<string, int>(StringComparer.Ordinal);

    /// <summary>What <c>ReorderFeature</c> answers. A bare false is a contract violation.</summary>
    public bool ReorderAnswer { get; set; } = true;

    public bool RollbackAnswer { get; set; } = true;

    public bool RebuildAnswer { get; set; } = true;

    public int WhatsWrongCount { get; set; }

    public List<string> WhatsWrongRows { get; } = new List<string>();

    public int SaveErrors { get; set; }

    public int SaveWarnings { get; set; }

    public bool SaveFlag { get; set; }

    /// <summary>Whether the save actually cleared the dirty flag.</summary>
    public bool SaveClearsFlag { get; set; } = true;

    public int TagWriteAnswer { get; set; }

    public bool TagWrites { get; set; } = true;

    public List<string> FolderNames { get; } = new List<string>();

    /// <summary>The solid bodies <c>GetBodies2(swSolidBody = 0, false)</c> answers with.</summary>
    public List<FakeBody> SolidBodies { get; } = new List<FakeBody>
    {
        new FakeBody(faceCount: 6, edgeCount: 12),
    };

    /// <summary>The sheet bodies <c>GetBodies2(swSheetBody = 1, false)</c> answers with.</summary>
    public List<FakeBody> SheetBodies { get; } = new List<FakeBody>();

    /// <summary>What <c>CreateMassProperty2</c> hands back; null is a failed create.</summary>
    public FakeMassProperty? MassProperty { get; set; } = new FakeMassProperty();

    /// <summary><c>IPartDoc.GetMaterialPropertyName2</c>; null is unknown, never "".</summary>
    public string? MaterialName { get; set; } = "1060 Alloy";

    public IEquationTarget Equations => EquationManager;

    // ---- IRemodelCopyTarget ----------------------------------------------------------

    public string? GetPathName()
    {
        Members.Add(nameof(GetPathName));
        return PathName;
    }

    public string? GetSessionTag(string fieldName)
    {
        Members.Add(nameof(GetSessionTag));
        return SessionTag;
    }

    public IntPtr GetDocumentIdentity()
    {
        Members.Add(nameof(GetDocumentIdentity));
        return _identity;
    }

    public IntPtr GetOpenDocumentIdentity(string documentPath)
    {
        Members.Add(nameof(GetOpenDocumentIdentity));
        return string.Equals(documentPath, PathName, StringComparison.OrdinalIgnoreCase)
            ? _identity
            : IntPtr.Zero;
    }

    public int WriteSessionTag(string fieldName, int fieldType, string fieldValue, int overwriteExisting)
    {
        Members.Add(nameof(WriteSessionTag));
        if (TagWrites)
        {
            SessionTag = fieldValue;
        }

        return TagWriteAnswer;
    }

    public int RemoveSessionTag(string fieldName)
    {
        Members.Add(nameof(RemoveSessionTag));
        SessionTag = null;
        return 0;
    }

    // ---- IScopeSignalSource ----------------------------------------------------------

    public int GetDocumentType()
    {
        Members.Add(nameof(GetDocumentType));
        return DocumentType;
    }

    public int? GetBodyCount(int bodyType)
    {
        Members.Add(nameof(GetBodyCount));
        return Signals.BodyCount(bodyType);
    }

    public bool? IsWeldment()
    {
        Members.Add(nameof(IsWeldment));
        return Signals.IsWeldment;
    }

    public bool? HasSheetMetalFolder()
    {
        Members.Add(nameof(HasSheetMetalFolder));
        return Signals.SheetMetalFolderPresent;
    }

    public bool? HasMeshBody()
    {
        Members.Add(nameof(HasMeshBody));
        return Signals.MeshBodyPresent;
    }

    public bool? HasGraphicsBody()
    {
        Members.Add(nameof(HasGraphicsBody));
        return Signals.GraphicsBodyPresent;
    }

    public bool? Is3DInterconnect()
    {
        Members.Add(nameof(Is3DInterconnect));
        return Signals.Is3DInterconnect;
    }

    public IReadOnlyList<string>? GetImportedFileNames()
    {
        Members.Add(nameof(GetImportedFileNames));
        return Signals.ImportedFileNames;
    }

    public IReadOnlyList<string>? GetConfigurationNames()
    {
        Members.Add(nameof(GetConfigurationNames));
        return Signals.ConfigurationNames;
    }

    public IReadOnlyList<RmsNamedFolder>? GetFolders()
    {
        Members.Add(nameof(GetFolders));
        return Signals.Folders;
    }

    // ---- the tree --------------------------------------------------------------------

    public object? ResolveByPersistReference(string persistRef, out int errorCode)
    {
        Members.Add(nameof(ResolveByPersistReference));
        Resolved.Add(persistRef);

        int code;
        if (ResolveErrors.TryGetValue(persistRef, out code) && code != 0)
        {
            errorCode = code;
            return null;
        }

        FakeFeature? feature = Features.FirstOrDefault(
            candidate => string.Equals(candidate.PersistRef, persistRef, StringComparison.Ordinal));
        errorCode = feature == null ? 1 : 0;
        return feature;
    }

    public string? GetPersistReference(object feature)
    {
        Members.Add(nameof(GetPersistReference));
        return ((FakeFeature)feature).PersistRef;
    }

    public IReadOnlyList<object> GetFeaturesInOrder()
    {
        Members.Add(nameof(GetFeaturesInOrder));
        return Features.Cast<object>().ToList();
    }

    public string? GetFeatureName(object feature)
    {
        Members.Add(nameof(GetFeatureName));
        return ((FakeFeature)feature).Name;
    }

    public string? GetFeatureDescription(object feature)
    {
        Members.Add(nameof(GetFeatureDescription));
        return ((FakeFeature)feature).Description;
    }

    public string? GetFeatureTypeName(object feature)
    {
        Members.Add(nameof(GetFeatureTypeName));
        return ((FakeFeature)feature).TypeName;
    }

    public bool IsRolledBack(object feature)
    {
        Members.Add(nameof(IsRolledBack));
        return ((FakeFeature)feature).RolledBack;
    }

    public int GetFeatureErrorCode(object feature, out bool isWarning)
    {
        Members.Add(nameof(GetFeatureErrorCode));
        var target = (FakeFeature)feature;
        isWarning = target.IsWarning;
        return target.ErrorCode;
    }

    public void SetFeatureName(object feature, string name)
    {
        Members.Add(nameof(SetFeatureName));
        ((FakeFeature)feature).Name = name;
    }

    public void SetFeatureDescription(object feature, string text)
    {
        Members.Add(nameof(SetFeatureDescription));
        ((FakeFeature)feature).Description = text;
    }

    public bool SelectFeature(object feature, bool append, int mark)
    {
        Members.Add(nameof(SelectFeature));
        if (!append)
        {
            Selected.Clear();
        }

        Selected.Add((FakeFeature)feature);
        return true;
    }

    public void ClearSelection()
    {
        Members.Add(nameof(ClearSelection));
        Selected.Clear();
    }

    public bool ReorderFeature(string featureName, string targetName, int location)
    {
        Members.Add(nameof(ReorderFeature));
        if (!ReorderAnswer)
        {
            return false;
        }

        FakeFeature? moving = Features.FirstOrDefault(
            candidate => string.Equals(candidate.Name, featureName, StringComparison.Ordinal));
        FakeFeature? anchor = Features.FirstOrDefault(
            candidate => string.Equals(candidate.Name, targetName, StringComparison.Ordinal));
        if (moving == null || anchor == null)
        {
            return false;
        }

        Features.Remove(moving);
        int at = Features.IndexOf(anchor);
        Features.Insert(location == 2 ? at : at + 1, moving);
        return true;
    }

    public object? InsertFeatureTreeFolder(int type)
    {
        Members.Add(nameof(InsertFeatureTreeFolder));
        if (Selected.Count == 0)
        {
            return null;
        }

        var folder = new FakeFeature(
            "folder:" + Selected[0].PersistRef, "Folder" + (FolderNames.Count + 1), "FtrFolder");
        FolderNames.Add(folder.Name!);

        foreach (FakeFeature member in Selected)
        {
            member.Folder = folder;
        }

        Features.Insert(Features.IndexOf(Selected[0]), folder);
        return folder;
    }

    public object? GetFeatureFolder(object feature)
    {
        Members.Add(nameof(GetFeatureFolder));
        return ((FakeFeature)feature).Folder;
    }

    // ---- the geometry reading ----------------------------------------------------------

    public IMassPropertyReading? CreateMassProperty()
    {
        Members.Add(nameof(CreateMassProperty));
        return MassProperty;
    }

    public IReadOnlyList<object>? GetBodies(int bodyType)
    {
        Members.Add(nameof(GetBodies));
        List<FakeBody> bodies = bodyType == 0 ? SolidBodies : SheetBodies;
        return bodies.Count == 0 ? null : bodies.Cast<object>().ToList();
    }

    public int? GetFaceCount(object body)
    {
        Members.Add(nameof(GetFaceCount));
        return ((FakeBody)body).FaceCount;
    }

    public int? GetEdgeCount(object body)
    {
        Members.Add(nameof(GetEdgeCount));
        return ((FakeBody)body).EdgeCount;
    }

    public string? GetMaterialName()
    {
        Members.Add(nameof(GetMaterialName));
        return MaterialName;
    }

    // ---- rebuild, save and units ------------------------------------------------------

    public bool EditRollbackToEnd()
    {
        Members.Add(nameof(EditRollbackToEnd));
        return RollbackAnswer;
    }

    /// <summary>The <c>TopOnly</c> argument <c>ForceRebuild3</c> was handed.</summary>
    public bool LastRebuildTopOnly { get; private set; }

    public bool ForceRebuild(bool topOnly)
    {
        Members.Add(nameof(ForceRebuild));
        LastRebuildTopOnly = topOnly;
        return RebuildAnswer;
    }

    public int GetWhatsWrongCount()
    {
        Members.Add(nameof(GetWhatsWrongCount));
        return WhatsWrongCount;
    }

    public IReadOnlyList<string> GetWhatsWrong()
    {
        Members.Add(nameof(GetWhatsWrong));
        return WhatsWrongRows;
    }

    public bool Save(int options, out int errors, out int warnings)
    {
        Members.Add(nameof(Save));
        SaveOptions = options;
        errors = SaveErrors;
        warnings = SaveWarnings;
        if (SaveClearsFlag && SaveErrors == 0)
        {
            SaveFlag = false;
        }

        return SaveErrors == 0;
    }

    /// <summary>The integer <c>Save3</c> was handed, asserted exactly.</summary>
    public int SaveOptions { get; private set; } = -1;

    public bool GetSaveFlag()
    {
        Members.Add(nameof(GetSaveFlag));
        return SaveFlag;
    }

    public string? GetLengthUnit()
    {
        Members.Add(nameof(GetLengthUnit));
        return LengthUnit;
    }
}

/// <summary>
/// The seat: the application-level calls the remodel commands make. It never hands back a
/// handle to the source - <see cref="ProbeSource"/> reads it and returns measurements - and
/// the only document it opens is the copy the run just created.
/// </summary>
public sealed class FakeRemodelSeat : IRemodelSeat
{
    private readonly Dictionary<int, bool> _toggles = new Dictionary<int, bool>();

    public FakeRemodelSeat(FakeProbeSource? probe = null, FakeRemodelDocument? copy = null)
    {
        Probe = probe ?? new FakeProbeSource();
        Copy = copy;
    }

    public FakeProbeSource Probe { get; }

    /// <summary>What <c>OpenDoc7</c> hands back, or null for a failed open.</summary>
    public FakeRemodelDocument? Copy { get; set; }

    /// <summary>Every path <see cref="OpenDocument"/> was asked to open, with its options.</summary>
    public List<string> Opened { get; } = new List<string>();

    public List<int> OpenOptions { get; } = new List<int>();

    public List<string> Closed { get; } = new List<string>();

    /// <summary>
    /// What <see cref="CloseDocument"/> throws, for the rollback of a failed open: a COM call
    /// on a path that is already failing is exactly where a restore gets skipped.
    /// </summary>
    public Exception? CloseFailure { get; set; }

    public VaultReference? Vault { get; set; }

    public bool CommandInProgress { get; set; }

    /// <summary>Every toggle write, in order, as <c>toggle=value</c>.</summary>
    public List<string> ToggleWrites { get; } = new List<string>();

    public IRemodelProbeSource ProbeSource => Probe;

    public IRemodelDocument? OpenDocument(string documentPath, int options)
    {
        Opened.Add(documentPath);
        OpenOptions.Add(options);
        if (Copy != null)
        {
            Copy.PathName = Copy.PathName ?? documentPath;
        }

        return Copy;
    }

    public void CloseDocument(string documentPath)
    {
        Closed.Add(documentPath);
        if (CloseFailure != null)
        {
            throw CloseFailure;
        }
    }

    public VaultReference? GetVault(string sourcePath) => Vault;

    public bool GetUserPreferenceToggle(int toggle)
    {
        bool value;
        return _toggles.TryGetValue(toggle, out value) && value;
    }

    public void SetUserPreferenceToggle(int toggle, bool value)
    {
        _toggles[toggle] = value;
        ToggleWrites.Add(toggle + "=" + value);
    }

    public bool GetCommandInProgress() => CommandInProgress;

    public void SetCommandInProgress(bool value)
    {
        CommandInProgress = value;
        ToggleWrites.Add("CommandInProgress=" + value);
    }
}
