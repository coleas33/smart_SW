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
/// record for a node they read only through an <c>IComponent2</c>.
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
    /// those words. Nothing is recorded for a document a resolved <c>IComponent2</c> node in the
    /// same configuration already reads, nor for any other handle: a drawing's forest root
    /// carries none and has no holes, faces, bodies or fastener identity of its own. A type test
    /// and a pass over the scope, not an interop call; reading these nodes is T130's and T134's.
    /// </summary>
    public static void RecordDocumentNode(
        DumpScope scope, ScopedComponent component, string entityKind, string notRead, string? assemblyNotRead)
    {
        ComponentNode node = component.Node;
        if (!(node.Handle is IModelDoc2) || ReadThroughAnInstance(scope, component))
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
    /// Whether the readers take this document through a resolved component of it in the same
    /// configuration - a part a drawing details that is also in the assembly it draws (T132,
    /// research R2.28). The document id is what says two paths are one file.
    /// </summary>
    private static bool ReadThroughAnInstance(DumpScope scope, ScopedComponent component) =>
        scope.Components.Any(other =>
            other.Node.Handle is IComponent2
            && other.Node.Suppression == SuppressionState.Resolved
            && other.DocumentId == component.DocumentId
            && other.Node.ReferencedConfiguration == component.Node.ReferencedConfiguration);
}
