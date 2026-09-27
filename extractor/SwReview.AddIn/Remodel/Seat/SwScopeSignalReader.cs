using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Rms;

namespace SwReview.AddIn.Remodel.Seat;

/// <summary>
/// <see cref="IScopeSignalSource"/> over one <c>IModelDoc2</c>: the scope signals of
/// contracts/bridge-remodel.md's <c>scope_signals</c> table and <c>GetType()</c>, read with the
/// interop calls that table names and nothing else (feature 004, T153 and T154; build order lane
/// B). One reader, shared by the engineer's open source (<see cref="SwRemodelProbeSource"/>, at
/// <c>remodel.probe_scope</c>) and the copy (<see cref="SwRemodelCopyDocument"/>, at
/// <c>remodel.open</c> step 12), so the two readings cannot drift apart at the COM level and step
/// 12's comparison compares like with like.
///
/// <b>Every value is a measurement, and unknown stays unknown.</b> A value that cannot be read is
/// null, never a default and never a pass: <c>remodel/scope.py</c> turns a null into
/// <c>signal_unresolved</c>. A document that is not a part answers null for the part-only rows.
///
/// <b>Ungated, and it opens nothing.</b> The bridge gates each member from outside, under the bare
/// read keys of <see cref="RemodelScopeProbe.ProbeSurface"/>; this class is handed a document it
/// did not open and keeps nothing but that handle.
///
/// The readings the table leaves open, each a default taken 2026-09-27 that the owner may revise
/// and a seat item until a sitting checks it (tasks.md, lane B's note): the mesh and graphics rows
/// read every body (<c>swAllBodies = -1</c>); the feature walks read every feature, nested ones
/// included (<c>GetFeatures(false)</c>); and a folder row is an <c>FtrFolder</c> that is not its
/// own end-tag marker, whose members are read only when their count agrees with the folder's.
/// </summary>
public sealed class SwScopeSignalReader : IScopeSignalSource
{
    /// <summary>The type name a feature folder reports on 2024 SP5 (VERIFIED).</summary>
    private const string FolderTypeName = "FtrFolder";

    /// <summary>
    /// The suffix of the marker a flat tree closes a folder with (PROBE-10). It can never carry one
    /// of the six group names, so leaving it out cannot hide a group folder from the scope gate.
    /// </summary>
    private const string EndTagSuffix = "___EndTag___";

    /// <summary><c>swBodyType_e.swAllBodies</c> (VERIFIED value -1): every body, of every type.</summary>
    private const int AllBodies = (int)swBodyType_e.swAllBodies;

    private readonly IModelDoc2 _document;

    public SwScopeSignalReader(IModelDoc2 document)
    {
        _document = document ?? throw new ArgumentNullException(nameof(document));
    }

    /// <inheritdoc />
    public int GetDocumentType()
    {
        // IModelDoc2.GetType(), the interop member answering swDocumentTypes_e, and not
        // object.GetType(): the int it is assigned to is what makes the compiler say so.
        int documentType = _document.GetType();
        return documentType;
    }

    /// <inheritdoc />
    public int? GetBodyCount(int bodyType)
    {
        IPartDoc? part = _document as IPartDoc;
        if (part == null)
        {
            return null;
        }

        // GetBodies2 answers null for a part with no body of that type: a count of zero. A null
        // among the bodies is not a body anyone can count, so the count is unknown.
        object? answer = part.GetBodies2(bodyType, false);
        if (answer == null)
        {
            return 0;
        }

        object?[]? elements = SwRemodelReads.Elements(answer);
        return elements == null || Array.IndexOf(elements, null) >= 0 ? (int?)null : elements.Length;
    }

    /// <inheritdoc />
    public bool? IsWeldment() => (_document as IPartDoc)?.IsWeldment();

    /// <inheritdoc />
    public bool? HasSheetMetalFolder()
    {
        IFeatureManager? manager = _document.FeatureManager;
        return manager == null ? (bool?)null : manager.GetSheetMetalFolder() != null;
    }

    /// <inheritdoc />
    public bool? HasMeshBody() => AnyBody(body => body.IsMeshBody());

    /// <inheritdoc />
    public bool? HasGraphicsBody() => AnyBody(body => body.IsGraphicsBody());

    /// <inheritdoc />
    public bool? Is3DInterconnect()
    {
        IReadOnlyList<IFeature>? features = SwRemodelReads.Features(_document, topLevelOnly: false);
        if (features == null)
        {
            return null;
        }

        foreach (IFeature feature in features)
        {
            if (feature.Is3DInterconnectFeature)
            {
                return true;
            }
        }

        return false;
    }

    /// <inheritdoc />
    public IReadOnlyList<string>? GetImportedFileNames()
    {
        IReadOnlyList<IFeature>? features = SwRemodelReads.Features(_document, topLevelOnly: false);
        if (features == null)
        {
            return null;
        }

        var names = new List<string>();
        foreach (IFeature feature in features)
        {
            string? name = feature.GetImportedFileName();
            if (!string.IsNullOrEmpty(name))
            {
                names.Add(name!);
            }
        }

        return names;
    }

    /// <inheritdoc />
    public IReadOnlyList<string>? GetConfigurationNames()
    {
        object?[]? elements = SwRemodelReads.Elements(_document.GetConfigurationNames());
        if (elements == null)
        {
            return null;
        }

        var names = new List<string>(elements.Length);
        foreach (object? element in elements)
        {
            if (!(element is string name))
            {
                return null;
            }

            names.Add(name);
        }

        return names;
    }

    /// <inheritdoc />
    public IReadOnlyList<RmsNamedFolder>? GetFolders()
    {
        IReadOnlyList<IFeature>? features = SwRemodelReads.Features(_document, topLevelOnly: false);
        if (features == null)
        {
            return null;
        }

        var folders = new List<RmsNamedFolder>();
        foreach (IFeature feature in features)
        {
            if (!string.Equals(feature.GetTypeName2(), FolderTypeName, StringComparison.Ordinal))
            {
                continue;
            }

            string? name = feature.Name;
            if (name == null)
            {
                return null;
            }

            if (name.EndsWith(EndTagSuffix, StringComparison.Ordinal))
            {
                continue;
            }

            IReadOnlyList<string>? members = FolderMembers(feature);
            if (members == null)
            {
                return null;
            }

            folders.Add(new RmsNamedFolder { Name = name, MemberPersistRefs = members });
        }

        return folders;
    }

    /// <summary>
    /// The persist refs of one folder's members, or null when they cannot all be read: the feature
    /// is not an <c>IFeatureFolder</c>, <c>GetFeatures()</c>'s length disagrees with
    /// <c>GetFeatureCount()</c> (a null answer with a count of zero is an empty folder), a member is
    /// not a feature, or a member has no persist ref. Never a shorter list.
    /// </summary>
    private IReadOnlyList<string>? FolderMembers(IFeature folder)
    {
        if (!(folder.GetSpecificFeature2() is IFeatureFolder contents))
        {
            return null;
        }

        int count = contents.GetFeatureCount();
        object? answer = contents.GetFeatures();
        object?[]? elements = answer == null && count == 0 ? new object?[0] : SwRemodelReads.Elements(answer);
        if (elements == null || elements.Length != count)
        {
            return null;
        }

        var members = new List<string>(elements.Length);
        foreach (object? element in elements)
        {
            string? persistRef = element is IFeature member ? SwRemodelReads.PersistReference(_document, member) : null;
            if (persistRef == null)
            {
                return null;
            }

            members.Add(persistRef);
        }

        return members;
    }

    /// <summary>
    /// True when any body of any type answers <paramref name="test"/> true; otherwise null when a
    /// body could not be asked (not a part, an unreadable answer, an element that is not a body),
    /// and false only when every body answered false. A body that answers true is present whatever
    /// another body could not say.
    /// </summary>
    private bool? AnyBody(Func<IBody2, bool> test)
    {
        IPartDoc? part = _document as IPartDoc;
        if (part == null)
        {
            return null;
        }

        object? answer = part.GetBodies2(AllBodies, false);
        object?[]? elements = answer == null ? new object?[0] : SwRemodelReads.Elements(answer);
        if (elements == null)
        {
            return null;
        }

        bool unreadable = false;
        foreach (object? element in elements)
        {
            if (!(element is IBody2 body))
            {
                unreadable = true;
                continue;
            }

            if (test(body))
            {
                return true;
            }
        }

        return unreadable ? (bool?)null : false;
    }
}
