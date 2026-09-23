using System;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Measure;
using SwReview.Extractor.PersistRefs;

namespace SwReview.Extractor.Sw;

/// <summary>
/// Builds the interference, capture and measure services over an attached session, the way
/// <see cref="SwDump"/> builds the dumpers. The one place that knows both the SldWorks
/// pointer and the wiring, so <c>interference</c>, <c>capture</c>, <c>serve</c> and the
/// add-in each ask for a service in one line.
///
/// The component index is built by walking the tree once. That is the same traversal
/// <c>dump</c> does and it allocates ids the same way, which is what makes a
/// <c>cmp:0011</c> read out of package.json mean the same component here (T071).
/// </summary>
public sealed class SwScope
{
    private SwScope(
        ISldWorks swApp,
        ISwSession session,
        ComponentIndex components,
        ComponentTreeResult tree)
    {
        SwApp = swApp;
        Session = session;
        Components = components;
        Tree = tree;
        Refs = new PersistRefService(session.Gate);
    }

    public ISldWorks SwApp { get; }

    public ISwSession Session { get; }

    /// <summary>Package component ids to live components and back.</summary>
    public ComponentIndex Components { get; }

    /// <summary>
    /// The traversal <see cref="Components"/> was built from, kept because
    /// <see cref="TessellateSource"/> needs the nodes themselves - the transform, the key and
    /// the live handle - and not only the id mapping.
    /// </summary>
    public ComponentTreeResult Tree { get; }

    public PersistRefService Refs { get; }

    /// <summary>Attaches, walks the component tree, and wires the services.</summary>
    public static SwScope Open(ISldWorks swApp, ISwSession session)
    {
        if (swApp == null)
        {
            throw new ArgumentNullException(nameof(swApp));
        }

        if (session == null)
        {
            throw new ArgumentNullException(nameof(session));
        }

        var refs = new PersistRefService(session.Gate);
        var gaps = new GapCollector();

        // Traversal only; nothing is written. The gaps it records are about components the
        // dump would also have skipped, and the commands below report them if they matter.
        ComponentTreeResult tree = new ComponentTreeDumper(session, refs)
            .Traverse(gaps, new DumpOptions { OutputDirectory = ".", Configuration = session.ConfigurationName() });

        return new SwScope(swApp, session, new ComponentIndex(tree), tree);
    }

    /// <summary>An already-open document by path, for references scoped to a part.</summary>
    public IModelDoc2? OpenDocument(string path) =>
        Session.Gate.Call("GetOpenDocumentByName", () => SwApp.GetOpenDocumentByName(path)) as IModelDoc2;

    public IInterferenceSource InterferenceSource() => new SwInterferenceSource(Session);

    public ICaptureView CaptureView() =>
        new SwCaptureView(Session, Refs, OpenDocument, handle => Components.IdOf(handle));

    public IMeasureSource MeasureSource() => new SwMeasureSource(Session, Refs, OpenDocument);

    /// <summary>
    /// The mesh fetch <c>tessellate</c> answers with (T097, lever 10a).
    ///
    /// The scope it exports into is built by <see cref="PackageWriter.ScopeFor"/>, the same
    /// call the dump and <c>probe rms</c> make, so a <c>cmp:0011</c> read out of package.json
    /// names the same component here - exactly what <see cref="Components"/> promises for the
    /// other commands, kept true by using one allocation rather than a second one.
    /// </summary>
    public ITessellateSource TessellateSource() => new SwTessellateSource(
        new MeshExporter(Session, Refs),
        PackageWriter.ScopeFor(
            new GapCollector(),
            new DumpOptions
            {
                OutputDirectory = ".",
                Configuration = Session.ConfigurationName(),
                Meshes = MeshFormat.Glb,
            },
            Tree));
}
