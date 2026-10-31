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
/// node - so it carries the <c>IModelDoc2</c> as its handle.
///
/// It lives here, once, because <see cref="SwFeatureReader"/> and <see cref="SwEquationReader"/>
/// both need the answer and a copy in each is a second place to forget the part root, which
/// would leave the Model check tab's headline case with no features and no equations.
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
    /// otherwise skip the node in silence (feature 010 T128, owner decision 166A): one
    /// <c>not_extracted</c> gap of <paramref name="entityKind"/>, naming the node as the gaps
    /// beside it do, ending "so <paramref name="notRead"/>.". Any other handle records nothing:
    /// a drawing's forest root carries none and has no holes, faces or fastener identity of its
    /// own. A type test, not an interop call; reading these nodes is T130's, after PROBE-15.
    /// </summary>
    public static void RecordDocumentNode(
        DumpScope scope, ScopedComponent component, string entityKind, string notRead)
    {
        if (component.Node.Handle is IModelDoc2)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                entityKind,
                null,
                $"'{component.Node.Key}' is reviewed as a document of its own, not as a component "
                + $"of an assembly, so {notRead}.",
                null);
        }
    }
}
