using SolidWorks.Interop.sldworks;

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
}
