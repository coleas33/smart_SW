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
    private static readonly HashSet<string> DeniedMembers = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        // Rebuild: changes the model and can resolve lightweight components.
        "EditRebuild3",
        "ForceRebuild3",

        // Writing files. SaveAs3 has one legitimate use - saving a capture image - which
        // goes through AssertSaveAs so the extension is checked.
        "Save3",
        "SaveAs3",

        // Deleting entities, features and components.
        "Delete2",
        "EditDelete",

        // Suppression state changes the geometry a later check would read.
        "EditSuppress2",
        "EditUnsuppress2",

        // Rewriting a feature definition.
        "ModifyDefinition",
    };

    /// <summary>
    /// Member families refused by prefix, matched case-insensitively. These are the
    /// feature-creation and system-setting calls; each has many numbered and Thin variants.
    /// </summary>
    private static readonly string[] DeniedPrefixes =
    {
        "FeatureCut",
        "FeatureExtrusion",
        "InsertFeature",
        "SetSystemValue",
    };

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

        if (DeniedMembers.Contains(member))
        {
            throw new MutatingCallError(
                member,
                $"{member} modifies the model. The review assistant is read-only (research R4).");
        }

        foreach (string prefix in DeniedPrefixes)
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
