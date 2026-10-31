using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The model document behind a traversed component.
///
/// Two shapes reach the readers and they are not interchangeable. An assembly's component is
/// an <c>IComponent2</c> and its document comes from <c>GetModelDoc2</c>, which answers null
/// for a suppressed or lightweight instance. The part root a part opened alone produces
/// (<see cref="ComponentTreeDumper"/>, T064) has no component at all - the document IS the
/// node - so it carries the <c>IModelDoc2</c> as its handle, as every model a drawing's views
/// reference does.
///
/// It lives here, once, because <see cref="SwFeatureReader"/> and <see cref="SwEquationReader"/>
/// both need the answer and a copy in each is a second place to forget the part root, which
/// would leave the Model check tab's headline case with no features and no equations. For the
/// same reason <see cref="RecordDocumentNode"/> is here: the gap <see cref="HoleDumper"/>,
/// <see cref="FastenerDumper"/>, <see cref="FaceDumper"/> and <see cref="MeshExporter"/>
/// record, through a <see cref="DocumentNodePass"/>, for a node they read only through an
/// <c>IComponent2</c>.
/// </summary>
internal static class ComponentDocuments
{
    /// <summary>
    /// The document for <paramref name="node"/>, or null when it is not loaded. One interop
    /// call at most (<c>GetModelDoc2</c>), which the callers name to the gate.
    /// </summary>
    public static IModelDoc2? Of(ComponentNode node)
    {
        switch (node.Handle)
        {
            case IComponent2 component:
                return component.GetModelDoc2() as IModelDoc2;
            case IModelDoc2 document:
                return document;
            default:
                return null;
        }
    }

    /// <summary>
    /// The gap a reader that goes through an <c>IComponent2</c> records for a node whose handle
    /// is its document - a part root, or a model a drawing references - where it would
    /// otherwise skip the node in silence (feature 010 T128 and T132, owner decision 166A): one
    /// <c>not_extracted</c> gap of <paramref name="entityKind"/>, naming the node as the gaps
    /// beside it do and saying how it is reviewed - a part root, the one such node with no
    /// parent, on its own; any other, referenced by a drawing - ending "so
    /// <paramref name="notRead"/>.".
    ///
    /// An assembly a drawing references is read through its components, so it records the gap
    /// only when <paramref name="assemblyNotRead"/> says what of its own the reader loses, and in
    /// those words. Nothing is recorded for a document the reader reached through a resolved
    /// <c>IComponent2</c> node in the same configuration, one of <paramref name="reached"/> (T137),
    /// nor for any other handle: a drawing's forest root carries none and has no holes, faces,
    /// bodies or fastener identity of its own. A type test and a pass over
    /// <paramref name="reached"/>, not an interop call; reading these nodes is T130's and T134's.
    /// </summary>
    public static void RecordDocumentNode(
        DumpScope scope,
        ScopedComponent component,
        string entityKind,
        string notRead,
        string? assemblyNotRead,
        IEnumerable<ScopedComponent> reached)
    {
        ComponentNode node = component.Node;
        if (!(node.Handle is IModelDoc2) || ReadThroughAnInstance(reached, component))
        {
            return;
        }

        bool assembly = node.DocumentKind == DocumentKind.Assembly;
        if (assembly && assemblyNotRead == null)
        {
            return;
        }

        string how = node.ParentKey == null
            ? "is reviewed as a document of its own, not as a component of an assembly"
            : "is referenced by a drawing, not reviewed as a component of an assembly";
        scope.Gaps.Add(
            GapKind.NotExtracted,
            entityKind,
            null,
            $"'{node.Key}' {how}, so {(assembly ? assemblyNotRead : notRead)}.",
            null);
    }

    /// <summary>
    /// Whether the reader took this document through a resolved component of it in the same
    /// configuration - a part a drawing details that is also in the assembly it draws (T132,
    /// research R2.28) - that it reached (T137, R2.29). The document id is what says two paths
    /// are one file.
    /// </summary>
    private static bool ReadThroughAnInstance(IEnumerable<ScopedComponent> reached, ScopedComponent component) =>
        reached.Any(other =>
            other.Node.Handle is IComponent2
            && other.Node.Suppression == SuppressionState.Resolved
            && other.DocumentId == component.DocumentId
            && other.Node.ReferencedConfiguration == component.Node.ReferencedConfiguration);
}

/// <summary>
/// One read's pass over the scope (feature 010 T137, research R2.29): the document nodes it
/// skips and the components whose document it reached, so that a node's gap is left out only
/// for a document the read really took through an instance, wherever the drawing lists the two;
/// the gaps are recorded after the pass. An instance that answered no model, or no bodies, did
/// not reach it, and the node keeps its gap.
/// </summary>
internal sealed class DocumentNodePass
{
    private readonly DumpScope _scope;
    private readonly List<ScopedComponent> _skipped = new List<ScopedComponent>();
    private readonly List<ScopedComponent> _reached;

    /// <param name="scope">The scope the read passes over, which takes the gaps.</param>
    /// <param name="reached">
    /// Components taken as reached before the pass begins: over the bridge, every component of
    /// the scope, because each is fetched by a call of its own that answers for itself (T133).
    /// </param>
    public DocumentNodePass(DumpScope scope, IEnumerable<ScopedComponent>? reached = null)
    {
        _scope = scope ?? throw new ArgumentNullException(nameof(scope));
        _reached = new List<ScopedComponent>(reached ?? Enumerable.Empty<ScopedComponent>());
    }

    /// <summary>A node the read skips, having no <c>IComponent2</c> to read it through.</summary>
    public void Skip(ScopedComponent component) => _skipped.Add(component);

    /// <summary>A component whose document the read reached: its model, or its bodies.</summary>
    public void Reached(ScopedComponent component) => _reached.Add(component);

    /// <summary>Each skipped node's gap, as <see cref="ComponentDocuments.RecordDocumentNode"/> words it.</summary>
    public void Record(string entityKind, string notRead, string? assemblyNotRead)
    {
        foreach (ScopedComponent component in _skipped)
        {
            ComponentDocuments.RecordDocumentNode(_scope, component, entityKind, notRead, assemblyNotRead, _reached);
        }
    }
}
