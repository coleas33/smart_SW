using System;
using System.Collections.Generic;
using System.Linq;

namespace SwReview.Extractor.Rms;

/// <summary>
/// One interop member the re-modeler calls, as the code was written against it: the
/// interface-qualified key, the ordered argument names, and the return type; and, for the frozen
/// manifest's row (004 T181), the commands that call it and the row's note, which reflection cannot
/// answer and so are committed here rather than typed into the fixture.
/// </summary>
public sealed class RemodelInteropCall
{
    private static readonly string[] Nobody = new string[0];

    private readonly string[] _parameterNames;
    private readonly string[] _usedBy;

    public RemodelInteropCall(
        string interfaceName,
        string member,
        string kind,
        string[] parameterNames,
        string returns,
        bool allowlisted)
        : this(interfaceName, member, kind, parameterNames, returns, allowlisted, Nobody, null)
    {
    }

    private RemodelInteropCall(
        string interfaceName,
        string member,
        string kind,
        string[] parameterNames,
        string returns,
        bool allowlisted,
        string[] usedBy,
        string? note)
    {
        Interface = interfaceName;
        Member = member;
        Kind = kind;
        _parameterNames = parameterNames;
        Returns = returns;
        Allowlisted = allowlisted;
        _usedBy = usedBy;
        Note = note;
    }

    public string Interface { get; }

    public string Member { get; }

    /// <summary><c>method</c>, <c>property-get</c> or <c>property-set</c>.</summary>
    public string Kind { get; }

    /// <summary>
    /// <b>Ordered.</b> The order is load-bearing: a reordered signature is exactly the failure a
    /// name-only check misses, and the one that writes a wrong argument to a document.
    /// </summary>
    public IReadOnlyList<string> ParameterNames => _parameterNames;

    public string Returns { get; }

    /// <summary>Mirrors <c>RemodelGuard.AllowedKeys</c>; the manifest test asserts both ways.</summary>
    public bool Allowlisted { get; }

    /// <summary>
    /// The manifest row's <c>used_by</c>: the <c>remodel.*</c> commands (or the probe, or a named
    /// check such as <c>VerifyTarget</c>) that call the member, so a red diff leads to the affected
    /// command in one step. Never empty in <see cref="RemodelInteropSurface.Calls"/>; the manifest
    /// command refuses a row without one.
    /// </summary>
    public IReadOnlyList<string> UsedBy => _usedBy;

    /// <summary>The manifest row's <c>note</c>, or null for a row with none.</summary>
    public string? Note { get; }

    /// <summary>The key a write call site hands the gate, and the manifest's row key.</summary>
    public string Key => Interface + "." + Member;

    /// <summary>This call, with the commands that call it (the manifest row's <c>used_by</c>).</summary>
    public RemodelInteropCall WithUsedBy(params string[] commands) =>
        new RemodelInteropCall(
            Interface, Member, Kind, _parameterNames, Returns, Allowlisted, commands ?? Nobody, Note);

    /// <summary>This call, with the manifest row's <c>note</c>.</summary>
    public RemodelInteropCall WithNote(string note) =>
        new RemodelInteropCall(
            Interface, Member, Kind, _parameterNames, Returns, Allowlisted, _usedBy, note);
}

/// <summary>
/// The constants of one swconst enum the frozen manifest records (004 T181): the enum's name and
/// its members' names, in the order the manifest lists them. Only the constants the code composes
/// are recorded; the integers are read by reflection when the manifest is written, never typed.
/// </summary>
public sealed class RemodelInteropConstants
{
    public RemodelInteropConstants(string enumName, params string[] members)
    {
        Enum = enumName ?? throw new ArgumentNullException(nameof(enumName));
        Members = members ?? throw new ArgumentNullException(nameof(members));
    }

    /// <summary>The enum's name in <c>SolidWorks.Interop.swconst</c>, for instance <c>swOpenDocOptions_e</c>.</summary>
    public string Enum { get; }

    /// <summary>The members' names, in the manifest's order.</summary>
    public IReadOnlyList<string> Members { get; }
}

/// <summary>
/// A member the design depends on <b>not</b> existing (004 T054's absences; T181): an interface and
/// either one member name or a <c>*core*</c> pattern, with the names a pattern matches that are
/// not the member the design means (<see cref="Except"/>), and the consequence the design draws.
/// </summary>
public sealed class RemodelInteropAbsence
{
    private static readonly string[] NoExceptions = new string[0];

    private RemodelInteropAbsence(
        string interfaceName, string? member, string? memberPattern, string[] except, string consequence)
    {
        Interface = interfaceName ?? throw new ArgumentNullException(nameof(interfaceName));
        Member = member;
        MemberPattern = memberPattern;
        Except = except;
        Consequence = consequence ?? throw new ArgumentNullException(nameof(consequence));
    }

    public string Interface { get; }

    /// <summary>The one member name that must stay absent, or null for a pattern.</summary>
    public string? Member { get; }

    /// <summary>A <c>*core*</c> pattern no member name may contain, or null for one member.</summary>
    public string? MemberPattern { get; }

    /// <summary>
    /// Names the pattern matches that are not the member the design depends on being absent, so
    /// the broad pattern is kept: <c>IFeatureManager.GetPlasticsShellType</c> matches <c>*Shell*</c>
    /// and is a Plastics query, not a shell creator.
    /// </summary>
    public IReadOnlyList<string> Except { get; }

    /// <summary>What the design does because the member is absent.</summary>
    public string Consequence { get; }

    public static RemodelInteropAbsence OfMember(string interfaceName, string member, string consequence) =>
        new RemodelInteropAbsence(
            interfaceName, member ?? throw new ArgumentNullException(nameof(member)), null, NoExceptions, consequence);

    public static RemodelInteropAbsence OfPattern(
        string interfaceName, string memberPattern, string consequence, params string[] except) =>
        new RemodelInteropAbsence(
            interfaceName,
            null,
            memberPattern ?? throw new ArgumentNullException(nameof(memberPattern)),
            except ?? NoExceptions,
            consequence);

    /// <summary>Whether <paramref name="memberName"/>, found on the interface, breaks this absence.</summary>
    public bool Matches(string memberName)
    {
        if (Except.Contains(memberName, StringComparer.Ordinal))
        {
            return false;
        }

        if (Member != null)
        {
            return string.Equals(Member, memberName, StringComparison.Ordinal);
        }

        string pattern = MemberPattern ?? string.Empty;
        string core = pattern.Trim('*');
        return pattern.StartsWith("*", StringComparison.Ordinal)
            && pattern.EndsWith("*", StringComparison.Ordinal)
            && core.Length > 0
            && memberName.IndexOf(core, StringComparison.Ordinal) >= 0;
    }
}

/// <summary>
/// T055. The argument-builder table the frozen interop-surface manifest pins
/// (contracts/interop-manifest.md, "Test A").
///
/// Every member on the stage-1 allowlist is VERIFIED: it exists with that signature on
/// SOLIDWORKS 2024 SP5 interop <c>32.5.0.48</c>. Nothing keeps that true. An upgrade can change
/// an arity, reorder parameters, turn a ByRef out-parameter into a return value, or remove a
/// member, and the failure mode is a <c>COMException</c> or, worse, a silently wrong argument at
/// the one moment the code is writing to a document.
///
/// This table is what a call site is written against and what
/// <c>RemodelInteropManifestTests.CodeMatchesManifest</c> compares with the checked-in fixture,
/// so "the code and the frozen surface agree" is a build-time statement rather than a reading.
/// A member reached without a row here has no frozen signature, which is why the test fails a
/// row that no builder reaches and a builder that no row records.
///
/// It is also the manifest's <b>selection</b> (004 T181; research R15.1): which rows the fixture
/// holds, in this order, with each row's <c>used_by</c>, <c>allowlisted</c> and <c>note</c>;
/// <see cref="Constants"/>, the swconst constants it records; and <see cref="Absences"/>.
/// <c>swreview-extract probe interop --emit-manifest</c> (<see cref="RemodelInteropManifest"/>)
/// writes the fixture from these and from reflection over the installed interop, which answers
/// every other field, so a row is added here and regenerated, never typed into the fixture.
///
/// The <b>composed option integers</b> are not here. They live where they are used -
/// <see cref="RemodelCopy.OpenOptions"/>, <see cref="RemodelCopy.SaveOptions"/>,
/// <see cref="RemodelCopy.SessionTagType"/>, <see cref="RemodelCopy.SessionTagOverwrite"/> and
/// <see cref="RemodelSystemToggles"/>' three toggles - and the manifest test asserts each one
/// against the manifest's recorded enum value, so the value and the name it was written as
/// cannot drift apart.
/// </summary>
public static class RemodelInteropSurface
{
    private const string Method = "method";
    private const string PropertyGet = "property-get";
    private const string PropertySet = "property-set";

    private static readonly RemodelInteropCall[] CallArray =
    {
        // ---- the stage-1 write surface (contracts/guard-allowlist.md), twenty keys ----------

        // The only move operation; MoveLocation is Before = 2 or After = 3.
        Call("IModelDocExtension", "ReorderFeature", Method, "System.Boolean", true,
            "FeatureToMove", "TargetFeature", "MoveLocation")
            .WithUsedBy("remodel.reorder")
            .WithNote("the only move operation; MoveLocation is Before = 2 or After = 3"),

        // Wrap the current contiguous selection, Containing = 2. The one exception to
        // "stage 1 creates nothing".
        Call("IFeatureManager", "InsertFeatureTreeFolder2", Method,
            "SolidWorks.Interop.sldworks.Feature", true, "Type")
            .WithUsedBy("remodel.folder")
            .WithNote("Containing = 2; the one exception to 'stage 1 creates nothing'"),

        // Roll the bar to the end at open, ToEnd = 1, with an empty feature name.
        Call("IFeatureManager", "EditRollback", Method, "System.Boolean", true,
            "Location", "Feature")
            .WithUsedBy("remodel.open")
            .WithNote("swMoveRollbackBarToEnd = 1, then no feature may report IsRolledBack"),

        // Duplicate-feature-name repair before any reorder, and naming a folder the run just
        // created. Nothing else is renamed; v1 addresses no dimension at all (FR-030).
        Call("IFeature", "set_Name", PropertySet, "System.Void", true, "Retval")
            .WithUsedBy("remodel.rename", "remodel.folder")
            .WithNote("duplicate-name repair before any reorder, and naming a folder the run just created"),
        Call("IFeature", "set_Description", PropertySet, "System.Void", true, "Description")
            .WithUsedBy("remodel.describe"),

        // Build the contiguous selection a folder wraps.
        Call("IFeature", "Select2", Method, "System.Boolean", true, "Append", "Mark")
            .WithUsedBy("remodel.folder")
            .WithNote("builds the contiguous member run a folder wraps"),

        // The verified equation helpers: Add3 then Add2 for an add, set_Equation then
        // SetEquationAndConfigurationOption for the op: "set" repair of FR-029, and Delete as
        // the inverse of an add this run made.
        Call("IEquationMgr", "Add3", Method, "System.Int32", true,
            "Index", "Equation", "Solve", "WhichConfigurations", "ConfigNames")
            .WithUsedBy("remodel.equation")
            .WithNote("AddEquationVerified step 1"),
        Call("IEquationMgr", "Add2", Method, "System.Int32", true, "Index", "Equation", "Solve")
            .WithUsedBy("remodel.equation")
            .WithNote("AddEquationVerified step 3, the fallback"),
        Call("IEquationMgr", "Delete", Method, "System.Int32", true, "Index")
            .WithUsedBy("remodel.equation")
            .WithNote("the inverse of an add this run made, never of a global the part already had"),
        Call("IEquationMgr", "set_Equation", PropertySet, "System.Void", true, "Index", "Equation")
            .WithUsedBy("remodel.equation")
            .WithNote("SetEquationVerified step 2, the op: set repair path of FR-029"),
        Call("IEquationMgr", "SetEquationAndConfigurationOption", Method, "System.Int32", true,
            "Index", "Equation", "WhichConfigurations", "ConfigNames")
            .WithUsedBy("remodel.equation")
            .WithNote("SetEquationVerified step 4, the fallback"),

        // One rebuild call, the selection clearing around every selection-based operation, and
        // the single save - which takes no filename and is made behind AssertSaveTarget.
        Call("IModelDoc2", "ForceRebuild3", Method, "System.Boolean", true, "TopOnly")
            .WithUsedBy("remodel.open", "remodel.rebuild")
            .WithNote("one rebuild call, one meaning; EditRebuild3 is excluded"),
        Call("IModelDoc2", "ClearSelection2", Method, "System.Void", true, "All")
            .WithUsedBy("remodel.folder")
            .WithNote("around every selection-based operation"),
        Call("IModelDoc2", "Save3", Method, "System.Boolean", true, "Options", "Errors", "Warnings")
            .WithUsedBy("remodel.save")
            .WithNote("takes no filename; this is the structural reason it cannot reach the source"),

        // Selection where Select2 is not enough.
        Call("IModelDocExtension", "SelectByID2", Method, "System.Boolean", true,
            "Name", "Type", "X", "Y", "Z", "Append", "Mark", "Callout", "SelectOption")
            .WithUsedBy("remodel.folder")
            .WithNote("selection where Select2 is not enough"),

        // The session tag: written at open, removed at close. Delete2 here is the collision the
        // qualified key exists for - the read-only denial of the bare name was written for
        // IEntity.Delete2.
        Call("ICustomPropertyManager", "Add3", Method, "System.Int32", true,
            "FieldName", "FieldType", "FieldValue", "OverwriteExisting")
            .WithUsedBy("remodel.open")
            .WithNote("the SwReviewRemodelRun session tag, written at open"),
        Call("ICustomPropertyManager", "Delete2", Method, "System.Int32", true, "FieldName")
            .WithUsedBy("remodel.close")
            .WithNote("the session tag removed at close; the bare name Delete2 means IEntity.Delete2, "
                + "which is the collision the qualified key exists for; T179: its answer is judged "
                + "against swCustomInfoDeleteResult_e, and only OK = 0 removed the tag"),

        // The three user-preference toggles and the run-scoped modal-suppression flag, all
        // restored in a finally. CommandInProgress is a property rather than a
        // swUserPreferenceToggle_e value, so it needs its own key.
        Call("ISldWorks", "SetUserPreferenceToggle", Method, "System.Void", true,
            "UserPreferenceValue", "OnFlag")
            .WithUsedBy("remodel.open", "remodel.close")
            .WithNote("the three toggles 10, 77 and 329 only, restored in a finally"),
        Call("ISldWorks", "set_CommandInProgress", PropertySet, "System.Void", true, "VbControl")
            .WithUsedBy("remodel.open", "remodel.close")
            .WithNote("a property, not a swUserPreferenceToggle_e value; it is deliberately absent from "
                + "the enums block"),

        // Close the tagged copy.
        Call("ISldWorks", "CloseDoc", Method, "System.Void", true, "Name")
            .WithUsedBy("remodel.close")
            .WithNote("closes the tagged copy only; T179: it answers nothing, so a GetOpenDocumentByName "
                + "read of the copy's path confirms it"),

        // ---- the read members the bridge uses -----------------------------------------------
        // Allowlisted: false. They take RemodelGuard's delegation branch to ReadOnlyGuard,
        // exactly as the reviewer's reads do, and are recorded here because a read whose
        // signature moved writes a wrong argument just as surely as a write whose did.

        Call("ISldWorks", "GetOpenDocumentByName", Method, "System.Object", false, "DocumentName")
            .WithUsedBy(
                "remodel.probe_scope", "remodel.open", "VerifyTarget", "remodel.open_copy", "remodel.plan",
                "remodel.start", "remodel.close")
            .WithNote("reaches the engineer's already-open source, and is VerifyTarget check 3 on the "
                + "copy; T181: the pane seat finds the copy with it before it activates it; T179: "
                + "IRemodelSeat.IsDocumentOpen, the read that confirms the copy's close"),
        Call("ISldWorks", "OpenDoc7", Method, "SolidWorks.Interop.sldworks.ModelDoc2", false,
            "Specification")
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("opens the copy at its own path with Silent | LoadModel = 17, never ReadOnly or "
                + "ViewOnly; T181: the pane seat's remodel.open_copy reopens a copy the engineer "
                + "closed through the same open request"),
        Call("ISldWorks", "GetUserPreferenceToggle", Method, "System.Boolean", false,
            "UserPreferenceToggle")
            .WithUsedBy("remodel.open")
            .WithNote("records each toggle's original value; a value that cannot be read refuses the "
                + "start"),
        Call("ISldWorks", "get_CommandInProgress", PropertyGet, "System.Boolean", false)
            .WithUsedBy("remodel.open")
            .WithNote("records the flag's original value for the finally restore"),

        Call("IModelDoc2", "GetPathName", Method, "System.String", false)
            .WithUsedBy("remodel.open", "VerifyTarget", "remodel.open_copy", "remodel.plan", "remodel.start")
            .WithNote("VerifyTarget check 1, and the post-open assertion that the handle is the copy and "
                + "not the source; T181: the pane seat reads the active document's path after it "
                + "activates the copy (T159)"),
        Call("IModelDoc2", "GetSaveFlag", Method, "System.Boolean", false)
            .WithUsedBy("remodel.probe_scope", "remodel.open", "remodel.save")
            .WithNote("the source must not be dirty; after the save it must read false"),
        Call("IModelDoc2", "ListExternalFileReferencesCount2", Method, "System.Int32", false)
            .WithUsedBy("remodel.probe_scope", "remodel.open")
            .WithNote("zero, or the run is refused with external_refs"),
        Call("IModelDoc2", "GetConfigurationNames", Method, "System.Object", false)
            .WithUsedBy("remodel.probe_scope", "remodel.open")
            .WithNote("the configuration count is checked, never assumed"),
        Call("IModelDoc2", "GetType", Method, "System.Int32", false)
            .WithUsedBy("remodel.probe_scope")
            .WithNote("swDocPART = 1; parts only"),

        // Recorded so an upgrade cannot quietly change what it is. It is NOT allowlisted: the
        // owner's decision is that a part carrying an RMS-named folder whose members differ from
        // the plan is refused, never dissolved, so v1 has no delete path at all.
        Call("IModelDoc2", "EditDelete", Method, "System.Void", false)
            .WithUsedBy("(no call path in v1)")
            .WithNote("recorded so an upgrade cannot quietly change what it is: it is NOT allowlisted, "
                + "because v1 refuses a mis-membered RMS-named folder instead of dissolving it"),

        Call("IModelDocExtension", "GetWhatsWrongCount", Method, "System.Int32", false)
            .WithUsedBy("remodel.open", "remodel.rebuild")
            .WithNote("non-zero at baseline stops the run and deletes the copy"),
        Call("IModelDocExtension", "GetWhatsWrong", Method, "System.Boolean", false,
            "Features", "ErrorCodes", "Warnings")
            .WithUsedBy("remodel.rebuild")
            .WithNote("corroborating only; its out-array element type is UNVERIFIED (PROBE-9)"),
        Call("IModelDocExtension", "GetObjectByPersistReference3", Method, "System.Object", false,
            "PersistId", "ErrorCode")
            .WithUsedBy("remodel.rename", "remodel.reorder", "remodel.folder", "remodel.describe")
            .WithNote("the ByRef error code is read on every resolve"),
        Call("IModelDocExtension", "CreateMassProperty2", Method, "System.Object", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("the typed interface, not the raw Object from GetMassProperties2"),
        Call("IModelDocExtension", "get_CustomPropertyManager", PropertyGet,
            "SolidWorks.Interop.sldworks.CustomPropertyManager", false, "ConfigName")
            .WithUsedBy("remodel.open", "remodel.close", "VerifyTarget")
            .WithNote("the document-scoped property manager, asked for with the empty configuration name"),

        Call("ICustomPropertyManager", "Get4", Method, "System.Boolean", false,
            "FieldName", "UseCached", "ValOut", "ResolvedValOut")
            .WithUsedBy("remodel.open", "VerifyTarget")
            .WithNote("the session tag read back; VerifyTarget check 2"),

        Call("IFeature", "get_Name", PropertyGet, "System.String", false)
            .WithUsedBy("remodel.rename", "remodel.reorder", "remodel.snapshot")
            .WithNote("read in the same breath as the name-addressed call"),
        Call("IFeature", "get_Description", PropertyGet, "System.String", false)
            .WithUsedBy("remodel.snapshot", "remodel.describe")
            .WithNote("null means unreadable, which is not the same as the empty string"),
        Call("IFeature", "GetTypeName2", Method, "System.String", false)
            .WithUsedBy("remodel.probe_scope", "remodel.snapshot")
            .WithNote("FtrFolder is how a feature folder is recognised"),
        Call("IFeature", "GetErrorCode2", Method, "System.Int32", false, "IsWarning")
            .WithUsedBy("remodel.rebuild")
            .WithNote("the primary per-feature error reading; swFeatureErrorNone = 0 is the only "
                + "acceptable value at verify time"),
        Call("IFeature", "IsRolledBack", Method, "System.Boolean", false)
            .WithUsedBy("remodel.open")
            .WithNote("asserted false for every feature after EditRollback"),
        Call("IFeature", "get_Is3DInterconnectFeature", PropertyGet, "System.Boolean", false)
            .WithUsedBy("remodel.probe_scope")
            .WithNote("scope signal"),
        Call("IFeature", "GetImportedFileName", Method, "System.String", false)
            .WithUsedBy("remodel.probe_scope")
            .WithNote("scope signal: an imported dumb solid"),

        Call("IFeatureManager", "GetSheetMetalFolder", Method, "System.Object", false)
            .WithUsedBy("remodel.probe_scope")
            .WithNote("scope signal: non-null means sheet metal"),
        Call("IFeatureManager", "FeatureFolderLocation", Method,
            "SolidWorks.Interop.sldworks.Feature", false, "Feature")
            .WithUsedBy("remodel.folder")
            .WithNote("membership is verified for every member after a folder is created"),
        Call("IFeatureManager", "get_ShowFeatureDescription", PropertyGet, "System.Boolean", false)
            .WithUsedBy("remodel.snapshot")
            .WithNote("a description hidden in the tree can be detected here and, per the absence below, "
                + "not turned on"),

        Call("IEquationMgr", "GetCount", Method, "System.Int32", false)
            .WithUsedBy("remodel.equation")
            .WithNote("the count is asserted to have incremented, or to be unchanged, around every "
                + "equation write"),
        Call("IEquationMgr", "get_Equation", PropertyGet, "System.String", false, "Index")
            .WithUsedBy("remodel.equation", "remodel.snapshot")
            .WithNote("the round-trip read that proves an equation write landed"),
        Call("IEquationMgr", "get_Value", PropertyGet, "System.Double", false, "Index")
            .WithUsedBy("remodel.snapshot")
            .WithNote("whether it answers in document units or metres is UNVERIFIED and blocking "
                + "(PROBE-2)"),

        Call("IPartDoc", "GetBodies2", Method, "System.Object", false, "BodyType", "BVisibleOnly")
            .WithUsedBy("remodel.probe_scope", "remodel.geometry")
            .WithNote("swSolidBody = 0 and swSheetBody = 1"),
        Call("IPartDoc", "IsWeldment", Method, "System.Boolean", false)
            .WithUsedBy("remodel.probe_scope")
            .WithNote("scope signal"),
        Call("IPartDoc", "GetMaterialPropertyName2", Method, "System.String", false,
            "ConfigName", "Database")
            .WithUsedBy("remodel.geometry")
            .WithNote("material_name, compared separately from geometry"),

        Call("IBody2", "IsMeshBody", Method, "System.Boolean", false)
            .WithUsedBy("remodel.probe_scope")
            .WithNote("scope signal"),
        Call("IBody2", "IsGraphicsBody", Method, "System.Boolean", false)
            .WithUsedBy("remodel.probe_scope")
            .WithNote("scope signal"),
        Call("IBody2", "GetFaceCount", Method, "System.Int32", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("face_count, compared exactly"),
        Call("IBody2", "GetEdgeCount", Method, "System.Int32", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("edge_count, compared exactly"),

        Call("IMassProperty2", "Recalculate", Method, "System.Boolean", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("its Boolean is checked before anything is read"),
        Call("IMassProperty2", "set_AccuracyLevel", PropertySet, "System.Void", false, "Retval")
            .WithUsedBy("remodel.geometry")
            .WithNote("swMassPropertyAccuracyLevel_Higher = 2"),
        Call("IMassProperty2", "set_SelectedItems", PropertySet, "System.Void", false, "Retval")
            .WithUsedBy("remodel.geometry")
            .WithNote("the body the reading is taken over"),

        // Set before Recalculate, or the numbers come back in the document's display units
        // and the reading's own field names (volume_m3, mass_kg) are wrong (research R12).
        Call("IMassProperty2", "set_UseSystemUnits", PropertySet, "System.Void", false, "Retval")
            .WithUsedBy("remodel.geometry")
            .WithNote("set true BEFORE Recalculate, or the numbers come back in the document's display "
                + "units (research R12)"),
        Call("IMassProperty2", "get_Volume", PropertyGet, "System.Double", false)
            .WithUsedBy("remodel.geometry"),
        Call("IMassProperty2", "get_SurfaceArea", PropertyGet, "System.Double", false)
            .WithUsedBy("remodel.geometry"),
        Call("IMassProperty2", "get_CenterOfMass", PropertyGet, "System.Object", false)
            .WithUsedBy("remodel.geometry"),
        Call("IMassProperty2", "get_PrincipalMomentsOfInertia", PropertyGet, "System.Object", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("sorted ascending by the C# side before comparison"),
        Call("IMassProperty2", "get_Mass", PropertyGet, "System.Double", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("recorded and compared separately, never as geometry"),
        Call("IMassProperty2", "get_Density", PropertyGet, "System.Double", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("comes from the material, which is not geometry"),

        // The two reads AssertFolderSelection makes, and nothing else.
        Call("ISelectionMgr", "GetSelectedObjectCount2", Method, "System.Int32", false, "Mark")
            .WithUsedBy("AssertFolderSelection")
            .WithNote("the first half of the one selected object and it is a FtrFolder reading"),
        Call("ISelectionMgr", "GetSelectedObject6", Method, "System.Object", false, "Index", "Mark")
            .WithUsedBy("AssertFolderSelection")
            .WithNote("the second half of that reading"),

        // ---- the seat adapter's plumbing (T153 to T155; T156, 2026-09-27) -----------------
        // Reads, and property sets on a throwaway open request, so none is allowlisted. The
        // adapter calls them directly and gates nothing itself; the bridge gates the calls on
        // the seam from outside, GetFeatures, GetPersistReference3 and GetUnits under those
        // bare keys.

        // The routes to every IModelDocExtension and IFeatureManager member above.
        Call("IModelDoc2", "get_Extension", PropertyGet,
            "SolidWorks.Interop.sldworks.ModelDocExtension", false)
            .WithUsedBy(
                "remodel.probe_scope", "remodel.open", "remodel.snapshot", "remodel.rename",
                "remodel.reorder", "remodel.folder", "remodel.describe", "remodel.rebuild",
                "remodel.geometry", "remodel.close", "VerifyTarget")
            .WithNote("T156: every IModelDocExtension member the seat adapter calls is reached through it"
                + " - the persist refs, the session tag's property manager, ReorderFeature, What's "
                + "Wrong and CreateMassProperty2"),
        Call("IModelDoc2", "get_FeatureManager", PropertyGet,
            "SolidWorks.Interop.sldworks.FeatureManager", false)
            .WithUsedBy(
                "remodel.probe_scope", "remodel.open", "remodel.snapshot", "remodel.reorder",
                "remodel.folder", "remodel.rebuild")
            .WithNote("T156: GetFeatures, GetSheetMetalFolder, EditRollback, InsertFeatureTreeFolder2 and"
                + " FeatureFolderLocation are all reached through it"),

        // IRemodelDocument.Equations, handed to the shared SwEquationManager.
        Call("IModelDoc2", "GetEquationMgr", Method, "SolidWorks.Interop.sldworks.EquationMgr", false)
            .WithUsedBy("remodel.snapshot", "remodel.equation")
            .WithNote("T156: IRemodelDocument.Equations; the manager is handed to the shared, ungated "
                + "SwEquationManager and to nothing else"),

        // IRemodelDocument.GetLengthUnit: element 0 is a swLengthUnit_e value. An answer that
        // cannot be read is null, never metres (research R3.6).
        Call("IModelDoc2", "GetUnits", Method, "System.Object", false)
            .WithUsedBy("remodel.open")
            .WithNote("T156: IRemodelDocument.GetLengthUnit; element 0 is a swLengthUnit_e value, named "
                + "by the pure RemodelLengthUnits table, and an answer that cannot be read is null, "
                + "never metres (research R3.6); the bridge gates it under the bare key GetUnits"),

        // IRemodelDocument.GetPersistReference and a folder's member refs, as PersistRefCodec
        // encodes them; and the top-level tree in tree order, GetFeatures(true).
        Call("IModelDocExtension", "GetPersistReference3", Method, "System.Object", false, "DispObj")
            .WithUsedBy(
                "remodel.probe_scope", "remodel.open", "remodel.snapshot", "remodel.reorder",
                "remodel.folder", "remodel.rebuild")
            .WithNote("T156: IRemodelDocument.GetPersistReference and a folder's member refs; the byte "
                + "array is encoded by the existing PersistRefCodec; the bridge gates it under the "
                + "bare key GetPersistReference3"),
        Call("IFeatureManager", "GetFeatures", Method, "System.Object", false, "ToplevelOnly")
            .WithUsedBy(
                "remodel.probe_scope", "remodel.open", "remodel.snapshot", "remodel.reorder",
                "remodel.folder", "remodel.rebuild")
            .WithNote("T156: GetFeatures(true), the top-level tree in tree order, for "
                + "IRemodelDocument.GetFeaturesInOrder and the scope-signal reader's walk; the bridge"
                + " gates it under the bare key GetFeatures; its order against the dump's is a seat "
                + "check (research R13.8)"),

        // The active configuration IGeometrySource.GetMaterialName reads the material for, by
        // the path Dump/PropertyDumper.cs already reads it.
        Call("IModelDoc2", "get_ConfigurationManager", PropertyGet,
            "SolidWorks.Interop.sldworks.ConfigurationManager", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("T156: with IConfigurationManager.get_ActiveConfiguration and "
                + "IConfiguration.get_Name, the active configuration IGeometrySource.GetMaterialName "
                + "reads the material for, by the path Dump/PropertyDumper.cs already reads it"),
        Call("IConfigurationManager", "get_ActiveConfiguration", PropertyGet,
            "SolidWorks.Interop.sldworks.Configuration", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("T156: the second step of that path"),
        Call("IConfiguration", "get_Name", PropertyGet, "System.String", false)
            .WithUsedBy("remodel.geometry")
            .WithNote("T156: the ConfigName GetMaterialPropertyName2 is asked for"),

        // An FtrFolder's members, for the rms_named_folders signal (research R3.1), read only when
        // their number agrees with the folder's count.
        Call("IFeature", "GetSpecificFeature2", Method, "System.Object", false)
            .WithUsedBy("remodel.probe_scope", "remodel.open")
            .WithNote("T156: an FtrFolder feature's IFeatureFolder, for the rms_named_folders row; the "
                + "reader is shared by the probe source and the copy, so remodel.open step 12 reads "
                + "the copy the same way"),
        Call("IFeatureFolder", "GetFeatures", Method, "System.Object", false)
            .WithUsedBy("remodel.probe_scope", "remodel.open")
            .WithNote("T156: the folder's members, whose persist refs fill member_persist_refs (research "
                + "R3.1 lists it VERIFIED)"),

        // The copy's open request, built by the one open-options helper the add-in's
        // remodel.open_copy shares. OpenDoc7 takes the request, so RemodelCopy.OpenOptions
        // (Silent | LoadModel = 17) is written as its members, and ReadOnly and ViewOnly are
        // always set false.
        Call("ISldWorks", "GetOpenDocSpec", Method, "System.Object", false, "FileName")
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: the one open-options helper builds the copy's open request from it, shared "
                + "with the add-in's remodel.open_copy; OpenDoc7 takes the request, so Silent | "
                + "LoadModel = 17 is written as its members"),
        Call("IDocumentSpecification", "set_DocumentType", PropertySet, "System.Void", false,
            "DocumentType")
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: swDocPART = 1; a property set on the throwaway open request, not a document "
                + "write, so it is neither gated nor allowlisted"),
        Call("IDocumentSpecification", "set_Silent", PropertySet, "System.Void", false, "OpenSilent")
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: true, the Silent half of RemodelCopy.OpenOptions (17); a property set on the"
                + " throwaway open request, not a document write, so it is neither gated nor "
                + "allowlisted"),
        Call("IDocumentSpecification", "set_LoadModel", PropertySet, "System.Void", false, "LoadModel")
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: true, the LoadModel half of RemodelCopy.OpenOptions (17); a property set on "
                + "the throwaway open request, not a document write, so it is neither gated nor "
                + "allowlisted"),
        Call("IDocumentSpecification", "set_ReadOnly", PropertySet, "System.Void", false, "OpenReadOnly")
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: always false, never ReadOnly (2); a property set on the throwaway open "
                + "request, not a document write, so it is neither gated nor allowlisted"),
        Call("IDocumentSpecification", "set_ViewOnly", PropertySet, "System.Void", false, "OpenViewOnly")
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: always false, never ViewOnly (4); a property set on the throwaway open "
                + "request, not a document write, so it is neither gated nor allowlisted"),
        Call("IDocumentSpecification", "get_Error", PropertyGet, "System.Int32", false)
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: the swFileLoadError_e bits of an open that returned no document, named by "
                + "FileLoadErrors.Describe"),
        Call("IDocumentSpecification", "get_Warning", PropertyGet, "System.Int32", false)
            .WithUsedBy("remodel.open", "remodel.open_copy")
            .WithNote("T156: the swFileLoadWarning_e bits of the same open"),

        // The count a folder's members are read against (the FtrFolder rows above), found by the
        // cross-check when lane B merged and so last in the manifest, where this table keeps it.
        Call("IFeatureFolder", "GetFeatureCount", Method, "System.Int32", false)
            .WithUsedBy("remodel.probe_scope", "remodel.open")
            .WithNote("T156: the count a folder's GetFeatures is read against; a length that disagrees "
                + "makes the whole rms_named_folders listing null rather than a shorter one (a null "
                + "answer with a count of zero is an empty folder)"),

        // ---- the pane's own seat (T181, 2026-09-27) ----------------------------------------
        // SwRemodelSeat: remodel.open_copy, and T159's activation before each dump, calling COM
        // directly outside the bridge by design (research R14.6, R15.2). None is allowlisted: the
        // pane seat is outside the bridge and its guard, a row records a member and never permits
        // one, and ActivateDoc3 stays on the read-only guard's denylist. OpenDoc7,
        // GetOpenDocumentByName and GetPathName, which the bridge calls too, name its commands above.

        // Activate the copy by its title, the user's preferences not consulted, without a rebuild.
        Call("ISldWorks", "ActivateDoc3", Method, "System.Object", false,
            "Name", "UseUserPreferences", "Option", "Errors")
            .WithUsedBy("remodel.open_copy", "remodel.plan", "remodel.start")
            .WithNote("T181: the pane seat activates the copy by its title with swDontRebuildActiveDoc = "
                + "1, so a copy the report was written against is not rebuilt; outside the bridge by "
                + "design and on the read-only guard's denylist, so recorded and never allowlisted"),

        // What SOLIDWORKS has active afterwards, whose path the pipeline compares with the copy's.
        Call("ISldWorks", "get_ActiveDoc", PropertyGet, "System.Object", false)
            .WithUsedBy("remodel.plan", "remodel.start")
            .WithNote("T181: after the activation before each dump, the active document, whose path "
                + "must be the copy's or the dump is refused CopyNotActive (T159)"),

        // The title ActivateDoc3 is asked for: SOLIDWORKS activates a document by title, not path.
        Call("IModelDoc2", "GetTitle", Method, "System.String", false)
            .WithUsedBy("remodel.open_copy", "remodel.plan", "remodel.start")
            .WithNote("T181: the title ActivateDoc3 is asked for, since SOLIDWORKS activates an open "
                + "document by its title and not its path"),
    };

    /// <summary>The whole table, in the order it is declared above.</summary>
    public static readonly IReadOnlyList<RemodelInteropCall> Calls = CallArray;

    /// <summary>
    /// The swconst constants the frozen manifest records, in its order (004 T181): only the constants
    /// the code composes. The integers are not here: the manifest command reads each one from the
    /// installed swconst, and <c>RemodelInteropManifestTests</c> asserts the code's composed values
    /// against them.
    /// </summary>
    public static readonly IReadOnlyList<RemodelInteropConstants> Constants = new[]
    {
        new RemodelInteropConstants(
            "swMoveLocation_e", "swMoveToEnd", "swMoveBefore", "swMoveAfter", "swMoveToTop",
            "swMoveToFolder"),
        new RemodelInteropConstants(
            "swFeatureTreeFolderType_e", "swFeatureTreeFolder_EmptyBefore", "swFeatureTreeFolder_Containing",
            "swFeatureTreeFolder_Mold"),
        new RemodelInteropConstants(
            "swOpenDocOptions_e", "swOpenDocOptions_Silent", "swOpenDocOptions_ReadOnly",
            "swOpenDocOptions_ViewOnly", "swOpenDocOptions_LoadModel"),
        new RemodelInteropConstants(
            "swSaveAsOptions_e", "swSaveAsOptions_Silent", "swSaveAsOptions_Copy",
            "swSaveAsOptions_SaveReferenced", "swSaveAsOptions_AvoidRebuildOnSave"),
        new RemodelInteropConstants(
            "swUserPreferenceToggle_e", "swInputDimValOnCreate", "swShowErrorsEveryRebuild",
            "swWarnSaveUpdateErrors"),
        new RemodelInteropConstants("swCustomInfoType_e", "swCustomInfoText"),
        new RemodelInteropConstants(
            "swCustomPropertyAddOption_e", "swCustomPropertyOnlyIfNew", "swCustomPropertyDeleteAndAdd",
            "swCustomPropertyReplaceValue"),
        new RemodelInteropConstants(
            "swMassPropertyAccuracyLevel_e", "swMassPropertyAccuracyLevel_Lower",
            "swMassPropertyAccuracyLevel_Medium", "swMassPropertyAccuracyLevel_Higher"),
        new RemodelInteropConstants(
            "swMassPropertiesStatus_e", "swMassPropertiesStatus_OK", "swMassPropertiesStatus_UnknownError",
            "swMassPropertiesStatus_NoBody"),
        new RemodelInteropConstants("swFeatureError_e", "swFeatureErrorNone"),
        new RemodelInteropConstants(
            "swMoveRollbackBarTo_e", "swMoveRollbackBarToEnd", "swMoveRollbackBarToPreviousPosition",
            "swMoveRollbackBarToBeforeFeature", "swMoveRollbackBarToAfterFeature"),
        new RemodelInteropConstants(
            "swFileSaveWarning_e", "swFileSaveWarning_RebuildError", "swFileSaveWarning_NeedsRebuild"),
        new RemodelInteropConstants(
            "swBodyType_e", "swSolidBody", "swSheetBody", "swMeshBody", "swGraphicsBody", "swAllBodies"),
        new RemodelInteropConstants("swDocumentTypes_e", "swDocPART"),
        new RemodelInteropConstants(
            "swInConfigurationOpts_e", "swThisConfiguration", "swAllConfiguration", "swSpecifyConfiguration"),
        new RemodelInteropConstants("swPersistReferencedObjectStates_e", "swPersistReferencedObject_Invalid"),
        new RemodelInteropConstants(
            "swLengthUnit_e", "swMM", "swCM", "swMETER", "swINCHES", "swFEET", "swFEETINCHES", "swANGSTROM",
            "swNANOMETER", "swMICRON", "swMIL", "swUIN"),

        // T181 (default taken 2026-09-27, the owner may revise; research R15.2): the constant the
        // pane seat composes, and Delete2's answers, all three, which the teardown names (T179).
        new RemodelInteropConstants("swRebuildOnActivation_e", "swDontRebuildActiveDoc"),
        new RemodelInteropConstants(
            "swCustomInfoDeleteResult_e", "swCustomInfoDeleteResult_OK", "swCustomInfoDeleteResult_NotPresent",
            "swCustomInfoDeleteResult_LinkedProp"),
    };

    /// <summary>
    /// The members the design depends on <b>not</b> existing, each with its consequence (004 T054,
    /// T181). The manifest command refuses to write while any of them is present, and test B fails.
    /// </summary>
    public static readonly IReadOnlyList<RemodelInteropAbsence> Absences = new[]
    {
        RemodelInteropAbsence.OfMember(
            "IEquationMgr",
            "set_GlobalVariable",
            "a global is created by equation syntax, \"name\" = expr, not by a flag"),
        RemodelInteropAbsence.OfPattern(
            "IFeatureManager",
            "*Shell*",
            "shell is IModelDoc2.InsertFeatureShell(Double, Boolean) returning Void, from the current "
            + "face selection; GetPlasticsShellType is a Plastics query and not a creator, so it is "
            + "excepted rather than narrowing the pattern",
            "GetPlasticsShellType"),
        RemodelInteropAbsence.OfMember(
            "ISketchRelation",
            "Name",
            "sketch relations cannot be named; intent is recorded in the parent feature's Description"),
        RemodelInteropAbsence.OfMember(
            "IFeature",
            "set_ShowFeatureDescription",
            "descriptions hidden in the tree can be DETECTED via "
            + "IFeatureManager.get_ShowFeatureDescription but not turned on"),
    };

    private static RemodelInteropCall Call(
        string interfaceName,
        string member,
        string kind,
        string returns,
        bool allowlisted,
        params string[] parameterNames) =>
        new RemodelInteropCall(
            interfaceName, member, kind, parameterNames ?? Array.Empty<string>(), returns, allowlisted);
}
