using System;
using System.Collections.Generic;
using System.IO;

namespace SwReview.Extractor.Guard;

/// <summary>
/// Raised when a caller tries to invoke a SOLIDWORKS member that would modify the model.
/// </summary>
[Serializable]
public class MutatingCallError : Exception
{
    public MutatingCallError(string memberName, string message)
        : base(message)
    {
        MemberName = memberName;
    }

    /// <summary>The interop member that was refused.</summary>
    public string MemberName { get; }
}

/// <summary>
/// The read-only gate in front of every SOLIDWORKS call the bridge and the console host
/// make (research R4). The review assistant inspects reviewed models; it never edits them.
///
/// The list is a denylist of members known to mutate a document, not an allowlist of
/// readers: the extraction surface is hundreds of getters and grows every phase, and a
/// stale allowlist fails closed on harmless reads while teaching nobody anything. Add a
/// member here the moment a phase touches an API family that can write.
/// </summary>
public static partial class ReadOnlyGuard
{
    /// <summary>Members refused outright, matched case-insensitively.</summary>
    private static readonly HashSet<string> DeniedMemberSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        // Rebuild: changes the model and can resolve lightweight components.
        "EditRebuild3",
        "ForceRebuild3",
        "ForceRebuildAll",

        // Writing files. SaveAs3 has one legitimate use - saving a capture image - which
        // goes through AssertSaveAs so the extension is checked.
        "Save3",
        "SaveAs3",

        // Deleting entities, features and components.
        "Delete2",
        "EditDelete",

        // Suppression state changes the geometry a later check would read. SetSuppression2
        // and ForceRebuild3 are the two the engineer-run suppress-test is exempted from, and
        // it is exempted by building its gate with SuppressTestGuard, never by this list.
        "EditSuppress2",
        "EditUnsuppress2",
        "SetSuppression2",
        "SetSuppression",

        // Rewriting a feature definition. AccessSelections is part of that edit: it rolls
        // the model back to the feature and must be released before anything else runs.
        "ModifyDefinition",
        "AccessSelections",

        // Rolling the tree back, and marking the document dirty so SOLIDWORKS offers to
        // save it - both leave the reviewed document changed for the engineer.
        "EditRollback",
        "SetSaveFlag",

        // ---- feature 006: the families the cut-list and drawing phases read from ----------
        //
        // Every member below sits beside a read one of those phases performs, and none of them
        // is called. They are here because this list grows the moment a phase touches an API
        // family that can write, which is the rule stated above. The table that fixes the
        // membership - and therefore the count - is `006-standards-check/research.md` R8; it is
        // restated in `004-resilient-remodeler/contracts/guard-allowlist.md` and asserted from
        // both ends by StandardsDenylistTests and RemodelGuardTests.
        //
        // The names are bare because SwGate.Call names them bare: `SetText` is one entry and
        // covers IDisplayDimension.SetText and INote.SetText alike.

        // Sheet and view activation - the release-checklist macro's one side effect, and the
        // thing the drawing phase is written not to need.
        "ActivateSheet",
        "ActivateView",

        // Exploded-state writes, beside the exploded read.
        "ShowExploded",
        "ShowExploded2",
        "CreateExplodedView",
        "AutoExplode",

        // Visibility writes, beside the visibility read.
        "SetVisibility",
        "SetVisibilityInAsmDisplayStates",
        "set_Visible",

        // Appearance writes, beside the transparency read.
        "SetMaterialPropertyValues2",
        "RemoveMaterialProperty",
        "RemoveMaterialProperty2",

        // Table-cell and revision writes, beside the revision-table read.
        "set_Text",
        "set_Text2",
        "AddRevision",
        "DeleteRevision",
        "InsertRevisionTable",
        "InsertRevisionTable2",

        // Cut-list writes, beside the cut-list read.
        "SetAutomaticCutList",
        "UpdateCutList",
        "SortCutList",
        "SetAutomaticUpdate",

        // Mass-override writes, beside the mass-override read.
        "set_OverrideMass",
        "SetOverrideMassValue",

        // Dimension, display-dimension and note writes, beside the GetOverride,
        // GetOverrideValue, GetSystemValue3 and GetText reads. SetSystemValue3 is already
        // refused by the SetSystemValue prefix below and is named here as well, because R8's
        // table is the membership and a reader checking the two against each other should not
        // have to know which rule catches it.
        "SetOverride",
        "SetText",
        "SetSystemValue3",
        "set_SystemValue",
        "set_Value",

        // Annotation-identity writes, beside the GetName read.
        "SetName",

        // Cut-list exclusion writes, beside the ExcludeFromCutList read.
        "set_ExcludeFromCutList",

        // ---- feature 010: the families the Hole Wizard and tolerance reads read from --------
        //
        // The setters beside every value those reads take, each reflected on the 2024 SP5
        // interop. The table that fixes the membership is the "Feature 010" table of
        // `004-resilient-remodeler/contracts/guard-allowlist.md`; MechanicalChecksDenylistTests
        // parses it and RemodelGuardTests lists the same names. None of them is called.

        // Dimension tolerance writes, beside IDimension.Tolerance and the IDimensionTolerance
        // reads (Type, GetMinValue2, GetMaxValue2, GetHoleFitValue, GetShaftFitValue). The three
        // IDimension members are the obsolete writers of the same tolerance.
        "SetToleranceType",
        "SetToleranceValues",
        "SetToleranceFitValues",
        "set_Type",
        "set_FitType",
        "SetValues",
        "SetValues2",
        "SetFitValues",

        // GTol frame and datum-identifier writes, beside GetFrameValues, GetFrameSymbols3,
        // GetFrameCount, GetFrame, GetDatumIdentifier and IGtolFrame.GetSymbolXml.
        "SetFrameValues",
        "SetFrameValues2",
        "SetFrameSymbols",
        "SetFrameSymbols2",
        "AddFrame",
        "DeleteFrame",
        "SetDatumIdentifier",
        "SetSymbolXml",
        "SetIndicator",
        "AddIndicator",
        "DeleteIndicator",
        "SetFrameToleranceType",

        // Datum-label and attachment writes, beside IDatumTag.GetLabel and
        // IAnnotation.GetAttachedEntities3.
        "SetLabel",
        "SetAttachedEntities",
        "ISetAttachedEntities",

        // Hole Wizard data writes, beside the HoleFit, ThreadClass, HeadClearance, diameter,
        // depth and angle reads. Every set_*Diameter, set_*Depth and set_*Angle
        // IWizardHoleFeatureData2 declares: ModifyDefinition, denied above, is the only way a
        // wizard edit takes effect, and these close the family by name as well.
        "set_HoleFit",
        "set_ThreadClass",
        "set_HeadClearance",
        "set_Diameter",
        "set_CounterBoreDiameter",
        "set_CounterDrillDiameter",
        "set_CounterSinkDiameter",
        "set_MinorDiameter",
        "set_MajorDiameter",
        "set_HoleDiameter",
        "set_ThruHoleDiameter",
        "set_TapDrillDiameter",
        "set_ThruTapDrillDiameter",
        "set_NearCounterSinkDiameter",
        "set_MidCounterSinkDiameter",
        "set_FarCounterSinkDiameter",
        "set_ThreadDiameter",
        "set_Depth",
        "set_CounterBoreDepth",
        "set_CounterDrillDepth",
        "set_HoleDepth",
        "set_ThruHoleDepth",
        "set_TapDrillDepth",
        "set_ThruTapDrillDepth",
        "set_ThreadDepth",
        "set_CounterDrillAngle",
        "set_CounterSinkAngle",
        "set_DrillAngle",
        "set_NearCounterSinkAngle",
        "set_MidCounterSinkAngle",
        "set_FarCounterSinkAngle",
        "set_ThreadAngle",

        // ---- decision 17A (feature 004, 2026-09-25): FeatureWorks and import repair --------
        //
        // The members that recognize features on an imported body and build them into the part
        // (IFeatureWorksApp, SolidWorks.Interop.fworks), FeatureWorks' option setters, and the
        // writers that repair an imported body in place. None of them is called. The table that
        // fixes the membership is the "Decision 17A" table of
        // `004-resilient-remodeler/contracts/guard-allowlist.md`; ImportRepairDenylistTests parses
        // it, and the members deliberately left open are tabulated beside it with their reasons.
        "RecognizeFeatureAutomatic",
        "RecognizeFeatureInteractive",
        "CreateFeatures",
        "SetAdvancedOptions",
        "SetPerformanceOptions",
        "ImportDiagnosis",
        "ImportDiagnosisGapCloser",
        "HealEdges",
        "InsertImportedFeature",
        "SetImportedFeatureParameters",
        "SetImportedFileName",
    };

    /// <summary>
    /// Member families refused by prefix, matched case-insensitively. These are the
    /// feature-creation and system-setting calls; each has many numbered and Thin variants.
    /// </summary>
    private static readonly string[] DeniedPrefixArray =
    {
        "FeatureCut",
        "FeatureExtrusion",
        "InsertFeature",
        "SetSystemValue",
    };

    /// <summary>
    /// The denied surface, for reading only (feature 004, contracts/guard-allowlist.md): the
    /// re-modeler's allowlist is asserted as a set against it, so a denial added here cannot
    /// silently widen that allowlist. The lookups below stay on the concrete collections, so
    /// exposing these changes neither the comparer nor the cost of a call.
    /// </summary>
    public static readonly IReadOnlyCollection<string> DeniedMembers = DeniedMemberSet;

    /// <inheritdoc cref="DeniedMembers" />
    public static readonly IReadOnlyCollection<string> DeniedPrefixes = DeniedPrefixArray;

    /// <summary>
    /// Feature 011 (T004): the generated drawing-family denials (<c>ReadOnlyGuard.Drawing.cs</c>,
    /// the "Feature 011" table of <c>004-resilient-remodeler/contracts/guard-allowlist.md</c>) join
    /// the set here. A static constructor runs after every static field initializer of both
    /// partial files, so the order the compiler takes the two files in cannot matter, and
    /// <see cref="DeniedMembers"/>, being the same set, reads them too.
    /// </summary>
    static ReadOnlyGuard()
    {
        DeniedMemberSet.UnionWith(DrawingFamilyDeniedMembers);
    }

    /// <summary>Image extensions SaveAs3 may write. Anything else is a model write.</summary>
    private static readonly HashSet<string> AllowedSaveAsExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        ".png",
        ".bmp",
        ".jpg",
    };

    /// <summary>
    /// Throws <see cref="MutatingCallError"/> if the named interop member is known to
    /// modify a model. Everything else is allowed.
    ///
    /// An interface-qualified key (<c>IDrawingDoc.ActivateSheet</c>) is judged by its member half
    /// as well as by the whole key, so no spelling of a denied member passes a read-only gate
    /// (feature 011 review, 2026-09-23: a qualified key had passed whatever it named). The two
    /// allowlist guards, <see cref="RemodelGuard"/> and <see cref="DrawingOpenGuard"/>, accept
    /// their own qualified keys before this guard is asked, and are unchanged by this. The error
    /// names the key as the caller wrote it.
    /// </summary>
    public static void Assert(string interopMemberName)
    {
        if (string.IsNullOrWhiteSpace(interopMemberName))
        {
            throw new ArgumentException(
                "An interop member name is required.", nameof(interopMemberName));
        }

        string member = interopMemberName.Trim();
        string bare = CallKey.BareName(member);

        if (DeniedMemberSet.Contains(member) || DeniedMemberSet.Contains(bare))
        {
            throw new MutatingCallError(
                member,
                $"{member} modifies the model. The review assistant is read-only (research R4).");
        }

        foreach (string prefix in DeniedPrefixArray)
        {
            if (member.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)
                || bare.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                throw new MutatingCallError(
                    member,
                    $"{member} is part of the {prefix}* family, which modifies the model. "
                    + "The review assistant is read-only (research R4).");
            }
        }
    }

    /// <summary>
    /// The one sanctioned use of SaveAs3: writing a capture image. Throws
    /// <see cref="MutatingCallError"/> for any other target, including a model file.
    /// </summary>
    public static void AssertSaveAs(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("A save path is required.", nameof(path));
        }

        string extension = Path.GetExtension(path.Trim());
        if (!AllowedSaveAsExtensions.Contains(extension))
        {
            string described = string.IsNullOrEmpty(extension) ? "(no extension)" : extension;
            throw new MutatingCallError(
                "SaveAs3",
                $"SaveAs3 may only write a capture image (.png, .bmp, .jpg); refused {described}.");
        }
    }
}
