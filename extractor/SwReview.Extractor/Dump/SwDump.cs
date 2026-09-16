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

        // A face's persistent reference is scoped to its owning PART document, so the face
        // dumper needs to turn a path back into an open document.
        Func<string, IModelDoc2?> openDocument = path =>
            session.Gate.Call("GetOpenDocumentByName", () => swApp.GetOpenDocumentByName(path)) as IModelDoc2;

        return new PackageWriter(
            new ComponentTreeDumper(session, refs),
            new PropertyDumper(session, swApp),
            new ManifestBuilder(session.Gate),
            new MateDumper(session, refs),
            new FeatureDumper(session.Gate, new SwFeatureReader(session.Gate, refs)),
            new EquationDumper(session.Gate, new SwEquationReader()),
            new HoleDumper(session, refs),
            new FastenerDumper(session, refs),
            new FaceDumper(session, refs, openDocument),
            new MeshExporter(session, refs),
            session.SwVersion);
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
