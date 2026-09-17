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
public static class ReadOnlyGuard
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
    /// </summary>
    public static void Assert(string interopMemberName)
    {
        if (string.IsNullOrWhiteSpace(interopMemberName))
        {
            throw new ArgumentException(
                "An interop member name is required.", nameof(interopMemberName));
        }

        string member = interopMemberName.Trim();

        if (DeniedMemberSet.Contains(member))
        {
            throw new MutatingCallError(
                member,
                $"{member} modifies the model. The review assistant is read-only (research R4).");
        }

        foreach (string prefix in DeniedPrefixArray)
        {
            if (member.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
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
