using System;
using System.Collections.Generic;

namespace SwReview.Extractor.Rms;

/// <summary>
/// One interop member the re-modeler calls, as the code was written against it: the
/// interface-qualified key, the ordered argument names, and the return type.
/// </summary>
public sealed class RemodelInteropCall
{
    public RemodelInteropCall(
        string interfaceName,
        string member,
        string kind,
        string[] parameterNames,
        string returns,
        bool allowlisted)
    {
        Interface = interfaceName;
        Member = member;
        Kind = kind;
        ParameterNames = parameterNames;
        Returns = returns;
        Allowlisted = allowlisted;
    }

    public string Interface { get; }

    public string Member { get; }

    /// <summary><c>method</c>, <c>property-get</c> or <c>property-set</c>.</summary>
    public string Kind { get; }

    /// <summary>
    /// <b>Ordered.</b> The order is load-bearing: a reordered signature is exactly the failure a
    /// name-only check misses, and the one that writes a wrong argument to a document.
    /// </summary>
    public IReadOnlyList<string> ParameterNames { get; }

    public string Returns { get; }

    /// <summary>Mirrors <c>RemodelGuard.AllowedKeys</c>; the manifest test asserts both ways.</summary>
    public bool Allowlisted { get; }

    /// <summary>The key a write call site hands the gate, and the manifest's row key.</summary>
    public string Key => Interface + "." + Member;
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
            "FeatureToMove", "TargetFeature", "MoveLocation"),

        // Wrap the current contiguous selection, Containing = 2. The one exception to
        // "stage 1 creates nothing".
        Call("IFeatureManager", "InsertFeatureTreeFolder2", Method,
            "SolidWorks.Interop.sldworks.Feature", true, "Type"),

        // Roll the bar to the end at open, ToEnd = 1, with an empty feature name.
        Call("IFeatureManager", "EditRollback", Method, "System.Boolean", true,
            "Location", "Feature"),

        // Duplicate-feature-name repair before any reorder, and naming a folder the run just
        // created. Nothing else is renamed; v1 addresses no dimension at all (FR-030).
        Call("IFeature", "set_Name", PropertySet, "System.Void", true, "Retval"),
        Call("IFeature", "set_Description", PropertySet, "System.Void", true, "Description"),

        // Build the contiguous selection a folder wraps.
        Call("IFeature", "Select2", Method, "System.Boolean", true, "Append", "Mark"),

        // The verified equation helpers: Add3 then Add2 for an add, set_Equation then
        // SetEquationAndConfigurationOption for the op: "set" repair of FR-029, and Delete as
        // the inverse of an add this run made.
        Call("IEquationMgr", "Add3", Method, "System.Int32", true,
            "Index", "Equation", "Solve", "WhichConfigurations", "ConfigNames"),
        Call("IEquationMgr", "Add2", Method, "System.Int32", true, "Index", "Equation", "Solve"),
        Call("IEquationMgr", "Delete", Method, "System.Int32", true, "Index"),
        Call("IEquationMgr", "set_Equation", PropertySet, "System.Void", true, "Index", "Equation"),
        Call("IEquationMgr", "SetEquationAndConfigurationOption", Method, "System.Int32", true,
            "Index", "Equation", "WhichConfigurations", "ConfigNames"),

        // One rebuild call, the selection clearing around every selection-based operation, and
        // the single save - which takes no filename and is made behind AssertSaveTarget.
        Call("IModelDoc2", "ForceRebuild3", Method, "System.Boolean", true, "TopOnly"),
        Call("IModelDoc2", "ClearSelection2", Method, "System.Void", true, "All"),
        Call("IModelDoc2", "Save3", Method, "System.Boolean", true, "Options", "Errors", "Warnings"),

        // Selection where Select2 is not enough.
        Call("IModelDocExtension", "SelectByID2", Method, "System.Boolean", true,
            "Name", "Type", "X", "Y", "Z", "Append", "Mark", "Callout", "SelectOption"),

        // The session tag: written at open, removed at close. Delete2 here is the collision the
        // qualified key exists for - the read-only denial of the bare name was written for
        // IEntity.Delete2.
        Call("ICustomPropertyManager", "Add3", Method, "System.Int32", true,
            "FieldName", "FieldType", "FieldValue", "OverwriteExisting"),
        Call("ICustomPropertyManager", "Delete2", Method, "System.Int32", true, "FieldName"),

        // The three user-preference toggles and the run-scoped modal-suppression flag, all
        // restored in a finally. CommandInProgress is a property rather than a
        // swUserPreferenceToggle_e value, so it needs its own key.
        Call("ISldWorks", "SetUserPreferenceToggle", Method, "System.Void", true,
            "UserPreferenceValue", "OnFlag"),
        Call("ISldWorks", "set_CommandInProgress", PropertySet, "System.Void", true, "VbControl"),

        // Close the tagged copy.
        Call("ISldWorks", "CloseDoc", Method, "System.Void", true, "Name"),

        // ---- the read members the bridge uses -----------------------------------------------
        // Allowlisted: false. They take RemodelGuard's delegation branch to ReadOnlyGuard,
        // exactly as the reviewer's reads do, and are recorded here because a read whose
        // signature moved writes a wrong argument just as surely as a write whose did.

        Call("ISldWorks", "GetOpenDocumentByName", Method, "System.Object", false, "DocumentName"),
        Call("ISldWorks", "OpenDoc7", Method, "SolidWorks.Interop.sldworks.ModelDoc2", false,
            "Specification"),
        Call("ISldWorks", "GetUserPreferenceToggle", Method, "System.Boolean", false,
            "UserPreferenceToggle"),
        Call("ISldWorks", "get_CommandInProgress", PropertyGet, "System.Boolean", false),

        Call("IModelDoc2", "GetPathName", Method, "System.String", false),
        Call("IModelDoc2", "GetSaveFlag", Method, "System.Boolean", false),
        Call("IModelDoc2", "ListExternalFileReferencesCount2", Method, "System.Int32", false),
        Call("IModelDoc2", "GetConfigurationNames", Method, "System.Object", false),
        Call("IModelDoc2", "GetType", Method, "System.Int32", false),

        // Recorded so an upgrade cannot quietly change what it is. It is NOT allowlisted: the
        // owner's decision is that a part carrying an RMS-named folder whose members differ from
        // the plan is refused, never dissolved, so v1 has no delete path at all.
        Call("IModelDoc2", "EditDelete", Method, "System.Void", false),

        Call("IModelDocExtension", "GetWhatsWrongCount", Method, "System.Int32", false),
        Call("IModelDocExtension", "GetWhatsWrong", Method, "System.Boolean", false,
            "Features", "ErrorCodes", "Warnings"),
        Call("IModelDocExtension", "GetObjectByPersistReference3", Method, "System.Object", false,
            "PersistId", "ErrorCode"),
        Call("IModelDocExtension", "CreateMassProperty2", Method, "System.Object", false),
        Call("IModelDocExtension", "get_CustomPropertyManager", PropertyGet,
            "SolidWorks.Interop.sldworks.CustomPropertyManager", false, "ConfigName"),

        Call("ICustomPropertyManager", "Get4", Method, "System.Boolean", false,
            "FieldName", "UseCached", "ValOut", "ResolvedValOut"),

        Call("IFeature", "get_Name", PropertyGet, "System.String", false),
        Call("IFeature", "get_Description", PropertyGet, "System.String", false),
        Call("IFeature", "GetTypeName2", Method, "System.String", false),
        Call("IFeature", "GetErrorCode2", Method, "System.Int32", false, "IsWarning"),
        Call("IFeature", "IsRolledBack", Method, "System.Boolean", false),
        Call("IFeature", "get_Is3DInterconnectFeature", PropertyGet, "System.Boolean", false),
        Call("IFeature", "GetImportedFileName", Method, "System.String", false),

        Call("IFeatureManager", "GetSheetMetalFolder", Method, "System.Object", false),
        Call("IFeatureManager", "FeatureFolderLocation", Method,
            "SolidWorks.Interop.sldworks.Feature", false, "Feature"),
        Call("IFeatureManager", "get_ShowFeatureDescription", PropertyGet, "System.Boolean", false),

        Call("IEquationMgr", "GetCount", Method, "System.Int32", false),
        Call("IEquationMgr", "get_Equation", PropertyGet, "System.String", false, "Index"),
        Call("IEquationMgr", "get_Value", PropertyGet, "System.Double", false, "Index"),

        Call("IPartDoc", "GetBodies2", Method, "System.Object", false, "BodyType", "BVisibleOnly"),
        Call("IPartDoc", "IsWeldment", Method, "System.Boolean", false),
        Call("IPartDoc", "GetMaterialPropertyName2", Method, "System.String", false,
            "ConfigName", "Database"),

        Call("IBody2", "IsMeshBody", Method, "System.Boolean", false),
        Call("IBody2", "IsGraphicsBody", Method, "System.Boolean", false),
        Call("IBody2", "GetFaceCount", Method, "System.Int32", false),
        Call("IBody2", "GetEdgeCount", Method, "System.Int32", false),

        Call("IMassProperty2", "Recalculate", Method, "System.Boolean", false),
        Call("IMassProperty2", "set_AccuracyLevel", PropertySet, "System.Void", false, "Retval"),
        Call("IMassProperty2", "set_SelectedItems", PropertySet, "System.Void", false, "Retval"),

        // Set before Recalculate, or the numbers come back in the document's display units
        // and the reading's own field names (volume_m3, mass_kg) are wrong (research R12).
        Call("IMassProperty2", "set_UseSystemUnits", PropertySet, "System.Void", false, "Retval"),
        Call("IMassProperty2", "get_Volume", PropertyGet, "System.Double", false),
        Call("IMassProperty2", "get_SurfaceArea", PropertyGet, "System.Double", false),
        Call("IMassProperty2", "get_CenterOfMass", PropertyGet, "System.Object", false),
        Call("IMassProperty2", "get_PrincipalMomentsOfInertia", PropertyGet, "System.Object", false),
        Call("IMassProperty2", "get_Mass", PropertyGet, "System.Double", false),
        Call("IMassProperty2", "get_Density", PropertyGet, "System.Double", false),

        // The two reads AssertFolderSelection makes, and nothing else.
        Call("ISelectionMgr", "GetSelectedObjectCount2", Method, "System.Int32", false, "Mark"),
        Call("ISelectionMgr", "GetSelectedObject6", Method, "System.Object", false, "Index", "Mark"),
    };

    /// <summary>The whole table, in the order it is declared above.</summary>
    public static readonly IReadOnlyList<RemodelInteropCall> Calls = CallArray;

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
