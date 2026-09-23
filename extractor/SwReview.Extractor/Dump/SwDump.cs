using System;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// Wires the real dumpers into a <see cref="PackageWriter"/>. The one place that knows
/// both the SldWorks pointer and the full set of phases, so the console host and the
/// add-in each call it with one line.
/// </summary>
public static class SwDump
{
    /// <summary>Builds a writer that dumps <paramref name="session"/>'s document.</summary>
    public static PackageWriter CreateWriter(ISldWorks swApp, ISwSession session)
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

        // One reader for both drawing seams: the drawing phase reads through
        // IDrawingReader, and the component traversal asks the same object which models the
        // drawing's views reference (IDrawingReferenceSource). Two readers would be two sets
        // of interop expressions that could disagree about what a view references.
        var drawings = new SwDrawingReader(session, refs);

        // A face's persistent reference is scoped to its owning PART document, so the face
        // dumper needs to turn a path back into an open document.
        Func<string, IModelDoc2?> openDocument = path =>
            session.Gate.Call("GetOpenDocumentByName", () => swApp.GetOpenDocumentByName(path)) as IModelDoc2;

        return new PackageWriter(
            new ComponentTreeDumper(session, refs, drawings),
            new PropertyDumper(session, swApp),
            new ManifestBuilder(session.Gate),
            new MateDumper(session, refs),
            new FeatureDumper(session.Gate, new SwFeatureReader(session.Gate, refs)),
            new EquationDumper(session.Gate, new SwEquationReader()),

            // The cut-list phase runs under the Standards and Full profiles, and the drawing
            // phase under those two when the root document is a drawing; both are recorded
            // `skipped` otherwise, which PackageWriter decides. A source left null here would
            // record the phase `skipped` in a dump that could have run it, which is the row
            // `swreview check standards` refuses a package on (FR-043).
            cutList: new CutListDumper(session.Gate, new SwCutListReader(session.Gate, refs)),
            drawings: new DrawingDumper(session.Gate, drawings),
            new HoleDumper(session, refs),
            new FastenerDumper(session, refs),
            new FaceDumper(session, refs, openDocument),
            new MeshExporter(session, refs),
            session.SwVersion,

            // The tolerance phase (schema 1.5.0, feature 010) runs under the Full profile; a
            // source left out here would record it `skipped` in a dump that could have run it.
            tolerances: new ToleranceDumper(
                session.Gate,
                new SwDimensionToleranceReader(session.Gate, refs),
                new SwModelAnnotationReader(session.Gate, refs)));
    }

    /// <summary>Attaches to a document and dumps it in one call.</summary>
    public static DumpResult Run(ISldWorks swApp, string? documentPath, DumpOptions options)
    {
        if (options == null)
        {
            throw new ArgumentNullException(nameof(options));
        }

        SwSession session = SwSession.Attach(swApp, documentPath, options.Configuration);
        return CreateWriter(swApp, session).Write(options);
    }
}
