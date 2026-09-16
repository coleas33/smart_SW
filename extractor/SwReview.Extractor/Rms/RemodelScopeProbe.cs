using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json.Serialization;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// One feature folder in the tree, with its members, as
/// <c>remodel.probe_scope</c> reads it (data-model.md section 4.1, <c>rms_named_folders</c>).
///
/// This row is what makes <c>rms_named_folder_wrong_members</c> decidable in <c>scope.py</c>
/// from <see cref="ScopeSignals"/> alone, which is what puts FR-007's refusal <b>ahead of the
/// copy</b>: a folder already carrying one of the six RMS names but holding the wrong members
/// is refused, never dissolved, because <c>IModelDoc2.EditDelete</c> is not on the stage-1
/// allowlist and there is therefore no dissolve path.
/// </summary>
public sealed class RmsNamedFolder
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("member_persist_refs")]
    public IReadOnlyList<string> MemberPersistRefs { get; set; } = new string[0];
}

/// <summary>
/// Where an EPDM source lives, recorded and <b>never</b> a refusal reason (owner decision: an
/// EPDM part is copied out, not refused). Null means "not in a vault"; a vault whose revision
/// could not be read is a different answer and the report says which.
/// </summary>
public sealed class VaultReference
{
    [JsonPropertyName("path")]
    public string? Path { get; set; }

    [JsonPropertyName("revision")]
    public string? Revision { get; set; }
}

/// <summary>
/// The scope signals, measured in C# at <c>remodel.probe_scope</c> on the engineer's
/// already-open source, then again on the copy at <c>remodel.open</c> step 12
/// (data-model.md section 4.1).
///
/// <b>Every field is a measurement, and the verdict is made elsewhere.</b> The pure
/// <c>remodel/scope.py</c> decides <c>ok</c>, <c>refused</c> or <c>unresolved</c> from these
/// numbers in Python, so the refusal table is table-testable with no seat and the host can
/// refuse a run without ever calling <c>remodel.open</c>.
///
/// A signal that could not be read is <b>null</b>, never a default. A null is not a pass: it
/// produces an <c>unresolved</c> scope item naming the signal, and a run may not proceed on an
/// unresolved multibody, weldment, sheet-metal, mesh, 3D Interconnect or
/// <see cref="RmsNamedFolders"/> signal.
/// </summary>
public sealed class ScopeSignals
{
    /// <summary><c>swDocumentTypes_e</c>; anything but <c>swDocPART = 1</c> is a refusal.</summary>
    [JsonPropertyName("document_type")]
    public int? DocumentType { get; set; }

    /// <summary><c>IPartDoc.GetBodies2(swSolidBody = 0, false)</c>.</summary>
    [JsonPropertyName("solid_body_count")]
    public int? SolidBodyCount { get; set; }

    /// <summary><c>IPartDoc.GetBodies2(swSheetBody = 1, false)</c>.</summary>
    [JsonPropertyName("sheet_body_count")]
    public int? SheetBodyCount { get; set; }

    /// <summary><c>IPartDoc.IsWeldment()</c>.</summary>
    [JsonPropertyName("is_weldment")]
    public bool? IsWeldment { get; set; }

    /// <summary><c>IFeatureManager.GetSheetMetalFolder()</c> non-null.</summary>
    [JsonPropertyName("sheet_metal_folder_present")]
    public bool? SheetMetalFolderPresent { get; set; }

    /// <summary><c>IBody2.IsMeshBody()</c> on any body.</summary>
    [JsonPropertyName("mesh_body_present")]
    public bool? MeshBodyPresent { get; set; }

    /// <summary><c>IBody2.IsGraphicsBody</c> on any body.</summary>
    [JsonPropertyName("graphics_body_present")]
    public bool? GraphicsBodyPresent { get; set; }

    /// <summary><c>IFeature.Is3DInterconnectFeature</c> on any feature.</summary>
    [JsonPropertyName("is_3d_interconnect")]
    public bool? Is3DInterconnect { get; set; }

    /// <summary><c>IFeature.GetImportedFileName</c>; null when the walk could not be made.</summary>
    [JsonPropertyName("imported_file_names")]
    public IReadOnlyList<string>? ImportedFileNames { get; set; }

    /// <summary><c>IModelDoc2.GetConfigurationNames</c>.</summary>
    [JsonPropertyName("configuration_names")]
    public IReadOnlyList<string>? ConfigurationNames { get; set; }

    /// <summary>
    /// Folders whose <c>GetTypeName2()</c> is <c>"FtrFolder"</c>, with each folder's members.
    /// Null is an unreadable listing, which is <c>signal_unresolved</c> for the same reason
    /// every other unreadable signal is; otherwise this row reopens the FR-007 hole from the
    /// other side.
    /// </summary>
    [JsonPropertyName("rms_named_folders")]
    public IReadOnlyList<RmsNamedFolder>? RmsNamedFolders { get; set; }

    /// <summary><c>ListExternalFileReferencesCount2()</c>.</summary>
    [JsonPropertyName("external_reference_count")]
    public int? ExternalReferenceCount { get; set; }

    /// <summary><c>GetSaveFlag()</c> on the source, when it is open.</summary>
    [JsonPropertyName("save_flag_dirty")]
    public bool? SaveFlagDirty { get; set; }

    [JsonPropertyName("read_only")]
    public bool? ReadOnly { get; set; }

    /// <summary>
    /// <c>GetWhatsWrongCount()</c> after the baseline rollback and rebuild. The one row the
    /// probe cannot fill: reading it needs a rollback and a rebuild, both writes, and neither
    /// may touch the source. Null at probe time, and null is <b>unknown</b>, not zero.
    /// </summary>
    [JsonPropertyName("rebuild_error_count")]
    public int? RebuildErrorCount { get; set; }

    /// <summary>EPDM; recorded, never a refusal reason.</summary>
    [JsonPropertyName("vault")]
    public VaultReference? Vault { get; set; }
}

/// <summary>
/// The scope-signal reads, and nothing else, so the same nine rows can be read on the
/// engineer's open source at <c>remodel.probe_scope</c> and again on the copy at
/// <c>remodel.open</c> step 12 without two readers that could drift apart.
///
/// Every member is one VERIFIED interop call, named in the gate so the SC-004 audit sees the
/// production member names even under a fake. A value that could not be read is null, and null
/// is unknown, never a pass.
/// </summary>
public interface IScopeSignalSource
{
    /// <summary><c>IModelDoc2.GetType()</c>; <c>swDocPART = 1</c> (VERIFIED value).</summary>
    int GetDocumentType();

    /// <summary><c>IPartDoc.GetBodies2(bodyType, false)</c>: solid is 0, sheet is 1.</summary>
    int? GetBodyCount(int bodyType);

    /// <summary><c>IPartDoc.IsWeldment()</c>.</summary>
    bool? IsWeldment();

    /// <summary><c>IFeatureManager.GetSheetMetalFolder()</c> non-null.</summary>
    bool? HasSheetMetalFolder();

    /// <summary><c>IBody2.IsMeshBody()</c> on any body.</summary>
    bool? HasMeshBody();

    /// <summary><c>IBody2.IsGraphicsBody</c> on any body.</summary>
    bool? HasGraphicsBody();

    /// <summary><c>IFeature.Is3DInterconnectFeature</c> on any feature.</summary>
    bool? Is3DInterconnect();

    /// <summary><c>IFeature.GetImportedFileName</c> over the tree.</summary>
    IReadOnlyList<string>? GetImportedFileNames();

    /// <summary><c>IModelDoc2.GetConfigurationNames</c>.</summary>
    IReadOnlyList<string>? GetConfigurationNames();

    /// <summary>Every <c>GetTypeName2() == "FtrFolder"</c> feature, with its members.</summary>
    IReadOnlyList<RmsNamedFolder>? GetFolders();
}

/// <summary>
/// The engineer's <b>already-open</b> source, as <c>remodel.probe_scope</c> reads it.
///
/// There is no member here that opens anything and none that hands back an
/// <c>IModelDoc2</c>: the probe reaches the document through
/// <c>ISldWorks.GetOpenDocumentByName</c> (VERIFIED), reads, and returns measurements. A
/// source SOLIDWORKS does not already have open is <c>source_not_open</c>, because opening it
/// to answer would give away the one property the constitution's exception rests on.
/// </summary>
public interface IRemodelProbeSource : IScopeSignalSource
{
    /// <summary>
    /// <c>ISldWorks.GetOpenDocumentByName(documentPath)</c> returned a document. It also
    /// <b>binds</b> that document for the reads that follow, which is why it is called first
    /// and exactly once per probe.
    /// </summary>
    bool IsOpen(string documentPath);

    /// <summary><c>IModelDoc2.GetSaveFlag()</c>: true is <c>source_dirty</c>.</summary>
    bool GetSaveFlag();

    /// <summary><c>IModelDoc2.ListExternalFileReferencesCount2()</c>: non-zero is a refusal.</summary>
    int GetExternalReferenceCount();
}

/// <summary>One probe this bridge session performed, kept beside its canonicalized source.</summary>
public sealed class ProbeRecord
{
    public ProbeRecord(string probeId, string sourcePath, ScopeSignals signals, DateTime at)
    {
        ProbeId = probeId;
        SourcePath = sourcePath;
        Signals = signals;
        At = at;
    }

    /// <summary>Minted here; <c>remodel.open</c> refuses a <c>probe_id</c> it did not mint.</summary>
    public string ProbeId { get; }

    /// <summary>Canonicalized, and compared canonically: the check is on the file, not the spelling.</summary>
    public string SourcePath { get; }

    /// <summary>The signals the verdict was reached from, kept for <c>plan.scope.signals_probe</c>.</summary>
    public ScopeSignals Signals { get; }

    public DateTime At { get; }
}

/// <summary>
/// T062. <c>remodel.probe_scope</c>'s reading, and the register of probes this bridge session
/// performed.
///
/// <b>The verdict is not made here.</b> The pure <c>remodel/scope.py</c> decides it in Python
/// from these signals, so the refusal table is table-testable with no seat and the host can
/// refuse a run without ever calling <c>remodel.open</c>. What is decided here is only what
/// can be: the four protocol conditions that have to be true before a signal means anything -
/// the path is an existing part, SOLIDWORKS has it open, it is not dirty, and it has no
/// external references.
///
/// The register is what makes FR-001 structural rather than conventional. <c>remodel.open</c>
/// refuses with <c>scope_not_probed</c> unless it is handed the <c>probe_id</c> of a probe
/// this session performed on this exact canonicalized source, <b>before</b> the copy. The
/// bridge cannot check a verdict Python reached and does not try to; it checks that a probe
/// happened, which is the part a caller could otherwise skip.
/// </summary>
public sealed class RemodelScopeProbe
{
    /// <summary>Parts only, in stage 1 and in v1.</summary>
    public const string PartExtension = ".SLDPRT";

    /// <summary><c>swDocumentTypes_e.swDocPART</c> (VERIFIED value 1).</summary>
    public const int PartDocumentType = (int)swDocumentTypes_e.swDocPART;

    /// <summary><c>swBodyType_e.swSolidBody</c> (VERIFIED value 0).</summary>
    public const int SolidBodyType = (int)swBodyType_e.swSolidBody;

    /// <summary><c>swBodyType_e.swSheetBody</c> (VERIFIED value 1).</summary>
    public const int SheetBodyType = (int)swBodyType_e.swSheetBody;

    // The gate is asked about the production member name, never about the seam member, so the
    // recorded gated set is auditable against contracts/bridge-remodel.md's table.
    private const string GetOpenDocumentByName = "GetOpenDocumentByName";
    private const string GetTypeMember = "GetType";
    private const string GetSaveFlagMember = "GetSaveFlag";
    private const string ListExternalFileReferencesCount2 = "ListExternalFileReferencesCount2";
    private const string GetBodies2 = "GetBodies2";
    private const string IsWeldmentMember = "IsWeldment";
    private const string GetSheetMetalFolder = "GetSheetMetalFolder";
    private const string IsMeshBody = "IsMeshBody";
    private const string IsGraphicsBody = "IsGraphicsBody";
    private const string Is3DInterconnectFeature = "Is3DInterconnectFeature";
    private const string GetImportedFileName = "GetImportedFileName";
    private const string GetConfigurationNames = "GetConfigurationNames";
    private const string GetTypeName2 = "GetTypeName2";

    private static readonly string[] ProbeSurfaceArray =
    {
        GetOpenDocumentByName,
        GetTypeMember,
        GetSaveFlagMember,
        ListExternalFileReferencesCount2,
        GetBodies2,
        IsWeldmentMember,
        GetSheetMetalFolder,
        IsMeshBody,
        IsGraphicsBody,
        Is3DInterconnectFeature,
        GetImportedFileName,
        GetConfigurationNames,
        GetTypeName2,
    };

    /// <summary>
    /// Every member <c>remodel.probe_scope</c> can gate: the <c>scope_signals</c> table plus
    /// the four protocol reads. All thirteen are reads, so they take
    /// <see cref="RemodelGuard"/>'s delegation branch to <see cref="ReadOnlyGuard"/> and touch
    /// no allowlist entry. A member added to the probe has to be added here and to the
    /// contract's table, which is the point.
    /// </summary>
    public static readonly IReadOnlyList<string> ProbeSurface = ProbeSurfaceArray;

    private readonly SwGate _gate;
    private readonly Dictionary<string, ProbeRecord> _probes =
        new Dictionary<string, ProbeRecord>(StringComparer.Ordinal);

    public RemodelScopeProbe(SwGate gate)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
    }

    /// <summary>
    /// contracts/bridge-remodel.md's five-step sequence. Steps 1 to 4 are the protocol
    /// conditions; step 5 reads the signals and mints the id.
    ///
    /// <paramref name="vault"/> comes from the caller that can read the vault and is recorded,
    /// never a refusal reason: an EPDM part is copied out (owner decision).
    /// </summary>
    public ProbeRecord Probe(string sourcePath, IRemodelProbeSource source, VaultReference? vault)
    {
        if (source == null)
        {
            throw new ArgumentNullException(nameof(source));
        }

        string path = Canonical(sourcePath);

        if (!string.Equals(Path.GetExtension(path), PartExtension, StringComparison.OrdinalIgnoreCase)
            || !File.Exists(path))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.NotAPart,
                $"'{sourcePath}' is not an existing {PartExtension} file. The re-modeler works "
                + "on parts, and only on parts, in stage 1.");
        }

        if (!_gate.Call(GetOpenDocumentByName, () => source.IsOpen(path)))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.SourceNotOpen,
                $"SOLIDWORKS does not have '{path}' open. The probe reads the document the "
                + "engineer already has open and never opens one itself, because opening the "
                + "source is exactly what this feature promises not to do.");
        }

        int documentType = _gate.Call(GetTypeMember, source.GetDocumentType);
        if (documentType != PartDocumentType)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.NotAPart,
                $"'{path}' is open as document type {documentType}, and the re-modeler works on "
                + $"swDocPART ({PartDocumentType}) only.");
        }

        bool dirty = _gate.Call(GetSaveFlagMember, source.GetSaveFlag);
        if (dirty)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.SourceDirty,
                $"'{path}' has unsaved changes. The copy would be taken from the file on disk "
                + "and would not be the part the engineer is looking at.");
        }

        int externalReferences = _gate.Call(
            ListExternalFileReferencesCount2, source.GetExternalReferenceCount);
        if (externalReferences != 0)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.ExternalRefs,
                $"'{path}' has {externalReferences} external file reference(s). Reorganizing a "
                + "part whose geometry is driven from another document is out of scope in v1.");
        }

        ScopeSignals signals = ReadSignals(_gate, source);
        signals.SaveFlagDirty = dirty;
        signals.ExternalReferenceCount = externalReferences;
        signals.ReadOnly = IsReadOnly(path);
        signals.Vault = vault;

        var record = new ProbeRecord(
            "probe:" + Guid.NewGuid().ToString("N"), path, signals, DateTime.UtcNow);
        _probes[record.ProbeId] = record;
        return record;
    }

    /// <summary>
    /// <c>remodel.open</c> step 1: the id names a probe this session performed, and that
    /// probe's canonicalized source equals this request's. Anything else is
    /// <c>scope_not_probed</c>, and it is raised <b>before</b> the copy.
    /// </summary>
    public ProbeRecord Require(string probeId, string sourcePath)
    {
        ProbeRecord? record;
        if (probeId == null || !_probes.TryGetValue(probeId, out record))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.ScopeNotProbed,
                $"'{probeId}' is not a probe this bridge session performed. Every run is probed "
                + "first, so that every scope refusal happens before any copy is made (FR-001).",
                new Dictionary<string, string>(StringComparer.Ordinal) { { "probe_id", probeId ?? string.Empty } });
        }

        string path = Canonical(sourcePath);
        if (!string.Equals(record!.SourcePath, path, StringComparison.OrdinalIgnoreCase))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.ScopeNotProbed,
                $"probe '{probeId}' was minted for '{record.SourcePath}' and this request names "
                + $"'{path}'. The verdict was reached on a different file.");
        }

        return record;
    }

    /// <summary>
    /// The nine signal rows, one VERIFIED call each, in the order contracts/bridge-remodel.md
    /// tabulates them. Used on the source at the probe and on the copy at
    /// <c>remodel.open</c> step 12, so the two readings are comparable by construction.
    /// </summary>
    public static ScopeSignals ReadSignals(SwGate gate, IScopeSignalSource source)
    {
        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        if (source == null)
        {
            throw new ArgumentNullException(nameof(source));
        }

        return new ScopeSignals
        {
            DocumentType = gate.Call(GetTypeMember, source.GetDocumentType),
            SolidBodyCount = gate.Call(GetBodies2, () => source.GetBodyCount(SolidBodyType)),
            SheetBodyCount = gate.Call(GetBodies2, () => source.GetBodyCount(SheetBodyType)),
            IsWeldment = gate.Call(IsWeldmentMember, source.IsWeldment),
            SheetMetalFolderPresent = gate.Call(GetSheetMetalFolder, source.HasSheetMetalFolder),
            MeshBodyPresent = gate.Call(IsMeshBody, source.HasMeshBody),
            GraphicsBodyPresent = gate.Call(IsGraphicsBody, source.HasGraphicsBody),
            Is3DInterconnect = gate.Call(Is3DInterconnectFeature, source.Is3DInterconnect),
            ImportedFileNames = gate.Call(GetImportedFileName, source.GetImportedFileNames),
            ConfigurationNames = gate.Call(GetConfigurationNames, source.GetConfigurationNames),
            RmsNamedFolders = gate.Call(GetTypeName2, source.GetFolders),
        };
    }

    /// <summary>
    /// <c>remodel.open</c> step 12's comparison: the rows that describe the <b>model</b>,
    /// field for field, naming every one that differs.
    ///
    /// The four file-scoped rows are deliberately not compared, because they describe the file
    /// rather than the part and differ between a source and its copy by design:
    /// <c>save_flag_dirty</c> (the copy was just opened), <c>read_only</c> (the copy's
    /// read-only attribute is cleared so the run can save it), <c>vault</c> (the copy is not in
    /// one) and <c>rebuild_error_count</c> (the probe cannot read it at all). Comparing them
    /// would make <c>scope_changed</c> fire on every run of a checked-in vault part, which is
    /// a false refusal, and false refusals are how a gate stops being believed.
    /// <c>external_reference_count</c> is not compared either: it is checked on the source at
    /// the probe and re-checked on the source at step 3, and it is not read on the copy.
    /// </summary>
    public static IReadOnlyList<string> ModelSignalDifferences(ScopeSignals probe, ScopeSignals copy)
    {
        if (probe == null)
        {
            throw new ArgumentNullException(nameof(probe));
        }

        if (copy == null)
        {
            throw new ArgumentNullException(nameof(copy));
        }

        var differences = new List<string>();
        Compare(differences, "document_type", probe.DocumentType, copy.DocumentType);
        Compare(differences, "solid_body_count", probe.SolidBodyCount, copy.SolidBodyCount);
        Compare(differences, "sheet_body_count", probe.SheetBodyCount, copy.SheetBodyCount);
        Compare(differences, "is_weldment", probe.IsWeldment, copy.IsWeldment);
        Compare(
            differences,
            "sheet_metal_folder_present",
            probe.SheetMetalFolderPresent,
            copy.SheetMetalFolderPresent);
        Compare(differences, "mesh_body_present", probe.MeshBodyPresent, copy.MeshBodyPresent);
        Compare(
            differences, "graphics_body_present", probe.GraphicsBodyPresent, copy.GraphicsBodyPresent);
        Compare(differences, "is_3d_interconnect", probe.Is3DInterconnect, copy.Is3DInterconnect);
        CompareList(
            differences, "imported_file_names", probe.ImportedFileNames, copy.ImportedFileNames);
        CompareList(
            differences, "configuration_names", probe.ConfigurationNames, copy.ConfigurationNames);
        CompareFolders(differences, probe.RmsNamedFolders, copy.RmsNamedFolders);
        return differences;
    }

    private static void Compare<T>(List<string> differences, string field, T? left, T? right)
        where T : struct
    {
        if (!Nullable.Equals(left, right))
        {
            differences.Add(field);
        }
    }

    private static void CompareList(
        List<string> differences,
        string field,
        IReadOnlyList<string>? left,
        IReadOnlyList<string>? right)
    {
        if (left == null || right == null)
        {
            if (!ReferenceEquals(left, right))
            {
                differences.Add(field);
            }

            return;
        }

        if (left.Count != right.Count)
        {
            differences.Add(field);
            return;
        }

        for (int i = 0; i < left.Count; i++)
        {
            if (!string.Equals(left[i], right[i], StringComparison.Ordinal))
            {
                differences.Add(field);
                return;
            }
        }
    }

    private static void CompareFolders(
        List<string> differences,
        IReadOnlyList<RmsNamedFolder>? left,
        IReadOnlyList<RmsNamedFolder>? right)
    {
        const string Field = "rms_named_folders";

        if (left == null || right == null)
        {
            if (!ReferenceEquals(left, right))
            {
                differences.Add(Field);
            }

            return;
        }

        if (left.Count != right.Count)
        {
            differences.Add(Field);
            return;
        }

        for (int i = 0; i < left.Count; i++)
        {
            if (!string.Equals(left[i].Name, right[i].Name, StringComparison.Ordinal))
            {
                differences.Add(Field);
                return;
            }

            var members = new List<string>();
            CompareList(members, Field, left[i].MemberPersistRefs, right[i].MemberPersistRefs);
            if (members.Count > 0)
            {
                differences.Add(Field);
                return;
            }
        }
    }

    /// <summary>
    /// The read-only attribute of the file, read from the filesystem rather than from the seat:
    /// it is a property of the file and gating a call for it would put a member in the probe's
    /// recorded surface that the contract's table does not name.
    /// </summary>
    private static bool? IsReadOnly(string path)
    {
        try
        {
            return (File.GetAttributes(path) & FileAttributes.ReadOnly) == FileAttributes.ReadOnly;
        }
        catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
        {
            // Unknown stays unknown: scope.py turns a null into signal_unresolved.
            return null;
        }
    }

    private static string Canonical(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.NotAPart, "a source path is required.");
        }

        try
        {
            return Path.GetFullPath(path.Trim());
        }
        catch (Exception error) when (error is ArgumentException
            || error is NotSupportedException
            || error is PathTooLongException
            || error is System.Security.SecurityException)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.NotAPart,
                $"'{path}' could not be canonicalized: {error.Message}");
        }
    }
}
