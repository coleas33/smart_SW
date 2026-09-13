using System;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Sw;

/// <summary>
/// The SOLIDWORKS session a dump runs against. An interface so the console host, the
/// add-in and future tests hand the dumpers the same three things: the document, its
/// active configuration, and the gate every call goes through.
/// </summary>
public interface ISwSession
{
    /// <summary>The document being dumped.</summary>
    IModelDoc2 Document { get; }

    /// <summary>The configuration the dump is bound to.</summary>
    IConfiguration Configuration { get; }

    /// <summary>e.g. "2024 SP5.0", or null when the version could not be read.</summary>
    string? SwVersion { get; }

    /// <summary>The read-only guard plus circuit breaker every interop call goes through.</summary>
    SwGate Gate { get; }
}

/// <summary>
/// A session over a running SOLIDWORKS instance.
///
/// The document is never opened for editing and the configuration is never switched: a
/// dump reads whatever configuration is active, because activating another one rebuilds
/// the model (research R12, and the read-only rule in the constitution). Asking for a
/// configuration that is not the active one is refused with a clear message rather than
/// quietly dumping the wrong geometry.
/// </summary>
public sealed class SwSession : ISwSession
{
    private SwSession(IModelDoc2 document, IConfiguration configuration, string? swVersion, SwGate gate)
    {
        Document = document;
        Configuration = configuration;
        SwVersion = swVersion;
        Gate = gate;
    }

    public IModelDoc2 Document { get; }

    public IConfiguration Configuration { get; }

    public string? SwVersion { get; }

    public SwGate Gate { get; }

    /// <summary>Full path of the document being dumped.</summary>
    public string DocumentPath => Document.GetPathName();

    /// <summary>
    /// Opens a session on <paramref name="documentPath"/>, or on the active document when
    /// it is null. A document that is already open is used as it stands; one that is not
    /// is opened READ ONLY, which is the only file-opening call the extractor makes.
    /// </summary>
    public static SwSession Attach(
        ISldWorks swApp, string? documentPath, string? configurationName, SwGate? gate = null)
    {
        if (swApp == null)
        {
            throw new ArgumentNullException(nameof(swApp));
        }

        SwGate g = gate ?? new SwGate();
        IModelDoc2 document = FindDocument(swApp, documentPath, g);

        IConfiguration configuration = ActiveConfiguration(document, g);
        if (!string.IsNullOrWhiteSpace(configurationName)
            && !string.Equals(configuration.Name, configurationName, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"'{configurationName}' is not the active configuration ('{configuration.Name}'). "
                + "Activate it in SOLIDWORKS first: the extractor never switches configurations, "
                + "because that rebuilds the model.");
        }

        string? version = ReadVersion(swApp, g);
        return new SwSession(document, configuration, version, g);
    }

    /// <summary>The document kind, for the IR's <see cref="DocumentKind"/>.</summary>
    public static DocumentKind KindOf(IModelDoc2 document, SwGate gate)
    {
        int type = gate.Call("GetType", () => document.GetType());
        switch ((swDocumentTypes_e)type)
        {
            case swDocumentTypes_e.swDocASSEMBLY:
                return DocumentKind.Assembly;
            case swDocumentTypes_e.swDocDRAWING:
                return DocumentKind.Drawing;
            default:
                return DocumentKind.Part;
        }
    }

    private static IModelDoc2 FindDocument(ISldWorks swApp, string? documentPath, SwGate gate)
    {
        if (string.IsNullOrWhiteSpace(documentPath))
        {
            var active = gate.Call("ActiveDoc", () => swApp.ActiveDoc) as IModelDoc2;
            if (active == null)
            {
                throw new InvalidOperationException(
                    "No document is open in SOLIDWORKS and --doc was not given.");
            }

            return active;
        }

        var open = gate.Call("GetOpenDocumentByName", () => swApp.GetOpenDocumentByName(documentPath))
            as IModelDoc2;
        if (open != null)
        {
            return open;
        }

        return OpenReadOnly(swApp, documentPath!, gate);
    }

    /// <summary>
    /// The one file-opening call in the extractor. Read-only and silent; the document is
    /// left open afterwards so persistent references stay resolvable for a later
    /// <c>resolve</c> or <c>capture</c>.
    ///
    /// The existence check lives HERE, after <c>GetOpenDocumentByName</c> has already said
    /// no, and nowhere earlier. Mapped drives and EPDM vault views are per logon session, so
    /// a path SOLIDWORKS resolves need not resolve for this process; checking before the
    /// lookup would reject a document SOLIDWORKS has open, with a wrong cause, in exactly
    /// the mismatched-session case the attach diagnosis is there to catch.
    /// </summary>
    private static IModelDoc2 OpenReadOnly(ISldWorks swApp, string documentPath, SwGate gate)
    {
        if (!File.Exists(documentPath))
        {
            throw new InvalidOperationException(
                $"'{documentPath}' is not open in SOLIDWORKS and not found on disk from this "
                + "process. A mapped drive or an EPDM vault view belongs to one logon session, "
                + "so check that this process sees the same drives as SOLIDWORKS, or pass the "
                + "UNC path.");
        }

        int documentType = documentPath.EndsWith(".sldasm", StringComparison.OrdinalIgnoreCase)
            ? (int)swDocumentTypes_e.swDocASSEMBLY
            : documentPath.EndsWith(".slddrw", StringComparison.OrdinalIgnoreCase)
                ? (int)swDocumentTypes_e.swDocDRAWING
                : (int)swDocumentTypes_e.swDocPART;

        int options = (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly
            | (int)swOpenDocOptions_e.swOpenDocOptions_Silent;

        int errors = 0;
        int warnings = 0;
        IModelDoc2? document = gate.Call(
            "OpenDoc6",
            () => (IModelDoc2?)swApp.OpenDoc6(documentPath, documentType, options, string.Empty, ref errors, ref warnings));

        if (document == null)
        {
            throw new InvalidOperationException(
                $"SOLIDWORKS could not open '{documentPath}' read-only "
                + $"({FileLoadErrors.Describe(errors, warnings)}).");
        }

        return document;
    }

    private static IConfiguration ActiveConfiguration(IModelDoc2 document, SwGate gate)
    {
        var configuration = gate.Call(
            "ConfigurationManager.ActiveConfiguration",
            () => document.ConfigurationManager?.ActiveConfiguration) as IConfiguration;

        if (configuration == null)
        {
            throw new InvalidOperationException(
                $"'{document.GetPathName()}' reports no active configuration.");
        }

        return configuration;
    }

    private static string? ReadVersion(ISldWorks swApp, SwGate gate)
    {
        // RevisionNumber is "32.5.0" style; the marketing name ("2024 SP5") is not exposed,
        // so the build number is recorded as-is rather than mapped to a guess.
        string? revision = gate.Call("RevisionNumber", () => swApp.RevisionNumber());
        return string.IsNullOrWhiteSpace(revision) ? null : revision;
    }
}
