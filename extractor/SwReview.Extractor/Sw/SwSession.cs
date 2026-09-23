using System;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Sw;

/// <summary>
/// Who is attaching, which decides whether a drawing may be attached to (feature 011,
/// contracts/attach.md section 1).
/// </summary>
public enum AttachPurpose
{
    /// <summary>
    /// Every caller of <see cref="SwSession.Attach"/> - the tool service, the terminal, the
    /// bridge, interference, capture, the remodel: a session bound to a configuration, so a
    /// drawing is refused with today's sentence.
    /// </summary>
    Model,

    /// <summary>
    /// The extraction only (<see cref="SwSession.AttachForDump"/>): a drawing is attached to,
    /// with no configuration, so the Standards tab and <c>swreview-extract dump</c> can read it.
    /// </summary>
    Dump,
}

/// <summary>
/// The SOLIDWORKS session a dump runs against. An interface so the console host, the
/// add-in and future tests hand the dumpers the same three things: the document, its
/// active configuration, and the gate every call goes through.
/// </summary>
public interface ISwSession
{
    /// <summary>The document being dumped.</summary>
    IModelDoc2 Document { get; }

    /// <summary>
    /// The configuration the dump is bound to, or null for a drawing, which has none (feature
    /// 011). Only <see cref="SwSession.AttachForDump"/> hands out a session with no
    /// configuration, and only the extraction reads one: every caller of
    /// <see cref="SwSession.Attach"/> holds the concrete <see cref="SwSession"/>, whose
    /// configuration is never null.
    /// </summary>
    IConfiguration? Configuration { get; }

    /// <summary>e.g. "2024 SP5.0", or null when the version could not be read.</summary>
    string? SwVersion { get; }

    /// <summary>The read-only guard plus circuit breaker every interop call goes through.</summary>
    SwGate Gate { get; }
}

/// <summary>
/// The name of the configuration a session is bound to (feature 011, contracts/attach.md
/// section 2).
///
/// <i>Landed as</i> an extension method rather than an <see cref="ISwSession"/> member: .NET
/// Framework 4.8 has no default interface members, and a new abstract member would break every
/// implementer of the interface - among them the add-in's wiring-test fake, which the task
/// keeps unedited. One rule in one place either way: the bound configuration's name, read
/// through the session's gate, or null for a drawing session, which has no configuration.
/// </summary>
public static class SwSessionConfiguration
{
    /// <summary>The bound configuration's name, or null when the session has no configuration.</summary>
    public static string? ConfigurationName(this ISwSession session)
    {
        if (session == null)
        {
            throw new ArgumentNullException(nameof(session));
        }

        IConfiguration? configuration = session.Configuration;
        return configuration == null
            ? null
            : session.Gate.Call("Configuration.Name", () => configuration.Name);
    }
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
    /// it is null. A document that is already open is used as it stands; a part or assembly
    /// that is not is opened READ ONLY, which is the only file-opening call the extractor makes.
    /// A drawing is refused (<see cref="AttachPurpose.Model"/>): this is the form every caller
    /// but the extraction uses, and each of them needs a configuration.
    /// </summary>
    public static SwSession Attach(
        ISldWorks swApp, string? documentPath, string? configurationName, SwGate? gate = null)
    {
        if (swApp == null)
        {
            throw new ArgumentNullException(nameof(swApp));
        }

        SwGate g = gate ?? new SwGate();
        IModelDoc2 document = FindDocument(swApp, documentPath, AttachPurpose.Model, g);

        // Before the configuration is asked for, because a drawing has none and the sentence
        // that says so is a symptom rather than an action. Asked of the document rather than of
        // the path: the path is null when the active document is the one being attached to.
        string? refusal = AttachRefusal(KindOf(document, g), document.GetPathName(), AttachPurpose.Model);
        if (refusal != null)
        {
            throw new InvalidOperationException(refusal);
        }

        return Bind(swApp, document, configurationName, g);
    }

    /// <summary>
    /// The extraction's attach (feature 011, contracts/attach.md section 1): <see cref="Attach"/>
    /// for a part or an assembly, and for a drawing a session with no configuration, which the
    /// Standards tab and <c>swreview-extract dump</c> read and nothing else is handed (section 3).
    /// A drawing that is not open is refused before anything is opened (section 4), and a
    /// configuration named with a drawing is refused naming both (section 2).
    /// </summary>
    public static ISwSession AttachForDump(
        ISldWorks swApp, string? documentPath, string? configurationName, SwGate? gate = null)
    {
        if (swApp == null)
        {
            throw new ArgumentNullException(nameof(swApp));
        }

        SwGate g = gate ?? new SwGate();
        IModelDoc2 document = FindDocument(swApp, documentPath, AttachPurpose.Dump, g);
        DocumentKind kind = KindOf(document, g);
        string path = document.GetPathName();

        // Null for every kind today (the dump purpose accepts all three); asked all the same, so
        // the purpose table has one reader and a kind added to it later is refused here too.
        string? refusal = AttachRefusal(kind, path, AttachPurpose.Dump)
            ?? ConfigurationRefusal(kind, path, configurationName);
        if (refusal != null)
        {
            throw new InvalidOperationException(refusal);
        }

        if (kind == DocumentKind.Drawing)
        {
            // No configuration is asked for: every drawing answers null to
            // ConfigurationManager.ActiveConfiguration, and nothing the extraction reads of a
            // drawing root needs one (section 2).
            return new DrawingSession(document, ReadVersion(swApp, g), g);
        }

        return Bind(swApp, document, configurationName, g);
    }

    /// <summary>
    /// Why an attach for <paramref name="purpose"/> will not open a session on a document of this
    /// kind, or null when it will (contracts/attach.md section 1).
    ///
    /// The model purpose refuses one kind: a drawing. Every drawing answers null to
    /// <c>ConfigurationManager.ActiveConfiguration</c>, and a model session is bound to a
    /// configuration - the tool service, the terminal and the bridge all read one - so the
    /// attach cannot succeed. It used to fail as "reports no active configuration", which names
    /// what was missing and not what to do about it, and the add-in logs a failed tool-service
    /// start rather than showing it, so the engineer was left with a pane whose features were
    /// all quietly off. The dump purpose refuses nothing: the extraction reads a drawing with no
    /// configuration (feature 011).
    ///
    /// Pure, and separate from the call that discovers the kind, so both the sentence and the
    /// rule are testable on a machine with no SOLIDWORKS.
    /// </summary>
    public static string? AttachRefusal(DocumentKind kind, string documentPath, AttachPurpose purpose) =>
        kind == DocumentKind.Drawing && purpose == AttachPurpose.Model
            ? DrawingHasNoConfiguration(documentPath)
            : null;

    /// <summary>
    /// Why a configuration named with this document cannot be selected, or null (contracts/
    /// attach.md section 2). Only a drawing is refused here, and only when a name was given: a
    /// drawing has no configuration to select. A part's or an assembly's named configuration is
    /// checked against its active one when the session is bound, with that rule's own sentence.
    /// </summary>
    public static string? ConfigurationRefusal(
        DocumentKind kind, string documentPath, string? configurationName) =>
        kind == DocumentKind.Drawing && !string.IsNullOrWhiteSpace(configurationName)
            ? $"'{documentPath}' is a drawing and has no configuration; '{configurationName}' "
                + "cannot be selected"
            : null;

    /// <summary>
    /// Why a document that is <b>not open</b> will not be opened for this attach, or null when it
    /// may be opened read-only (contracts/attach.md section 4). A drawing is never opened by an
    /// attach: opening one loads every model its views show. The dump purpose names that; the
    /// model purpose would refuse the drawing open or not, so it gets today's sentence - before
    /// anything is opened, where it used to open the drawing first and refuse it after.
    /// </summary>
    public static string? NotOpenRefusal(string documentPath, AttachPurpose purpose)
    {
        if (documentPath == null)
        {
            throw new ArgumentNullException(nameof(documentPath));
        }

        if (!documentPath.EndsWith(DrawingExtension, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        return purpose == AttachPurpose.Model
            ? DrawingHasNoConfiguration(documentPath)
            : $"'{documentPath}' is a drawing that is not open in SOLIDWORKS. Open it first: the "
                + "extractor does not open drawings, because opening one loads every model its views show.";
    }

    /// <summary>The drawing file extension, matched case-insensitively.</summary>
    private const string DrawingExtension = ".slddrw";

    /// <summary>Today's refusal of a drawing by the model purpose, word for word (attach.md section 1).</summary>
    private static string DrawingHasNoConfiguration(string documentPath) =>
        $"'{documentPath}' is a drawing, which has no configuration to bind a session to; "
        + "open the part or assembly it documents.";

    /// <summary>
    /// The configuration half of an attach, shared by both purposes for a part or an assembly:
    /// the active configuration, the named one checked against it, and the version.
    /// </summary>
    private static SwSession Bind(
        ISldWorks swApp, IModelDoc2 document, string? configurationName, SwGate gate)
    {
        IConfiguration configuration = ActiveConfiguration(document, gate);
        if (!string.IsNullOrWhiteSpace(configurationName)
            && !string.Equals(configuration.Name, configurationName, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"'{configurationName}' is not the active configuration ('{configuration.Name}'). "
                + "Activate it in SOLIDWORKS first: the extractor never switches configurations, "
                + "because that rebuilds the model.");
        }

        string? version = ReadVersion(swApp, gate);
        return new SwSession(document, configuration, version, gate);
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

    /// <summary>
    /// The open document as an <c>IDrawingDoc</c>, or null when it is not a drawing (schema
    /// 1.4.0, feature 006). The drawing handle the <c>drawing</c> phase reads through, beside
    /// <see cref="KindOf"/>, which is the kind question the same document answers.
    ///
    /// A COM cast, not a call: nothing is opened, and no sheet or view is activated to get it
    /// (FR-044). It is <c>as</c> rather than a hard cast because "this document is not a
    /// drawing" is an answer the caller records, not an exception - the phase runs only for a
    /// drawing root, so a null here is the dump disagreeing with itself and
    /// <see cref="Dump.DrawingDumper"/> writes a gap saying so.
    /// </summary>
    public static IDrawingDoc? DrawingOf(IModelDoc2 document)
    {
        if (document == null)
        {
            throw new ArgumentNullException(nameof(document));
        }

        return document as IDrawingDoc;
    }

    private static IModelDoc2 FindDocument(
        ISldWorks swApp, string? documentPath, AttachPurpose purpose, SwGate gate)
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

        return OpenReadOnly(swApp, documentPath!, purpose, gate);
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
    ///
    /// Parts and assemblies only (feature 011, contracts/attach.md section 4): a drawing that is
    /// not open is refused here, before the existence check and before any open, by
    /// <see cref="NotOpenRefusal"/>.
    /// </summary>
    private static IModelDoc2 OpenReadOnly(
        ISldWorks swApp, string documentPath, AttachPurpose purpose, SwGate gate)
    {
        string? refusal = NotOpenRefusal(documentPath, purpose);
        if (refusal != null)
        {
            throw new InvalidOperationException(refusal);
        }

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

/// <summary>
/// A session over an open drawing (feature 011, contracts/attach.md section 2): the document,
/// no configuration, the version and the gate. Handed out by
/// <see cref="SwSession.AttachForDump"/> only, so no caller of <see cref="SwSession.Attach"/> -
/// the tool service, the terminal, the reuse probe, interference, remodel, the bridge - ever
/// meets a null configuration.
/// </summary>
internal sealed class DrawingSession : ISwSession
{
    public DrawingSession(IModelDoc2 document, string? swVersion, SwGate gate)
    {
        Document = document ?? throw new ArgumentNullException(nameof(document));
        SwVersion = swVersion;
        Gate = gate ?? throw new ArgumentNullException(nameof(gate));
    }

    public IModelDoc2 Document { get; }

    /// <summary>Always null: a drawing has no configuration.</summary>
    public IConfiguration? Configuration => null;

    public string? SwVersion { get; }

    public SwGate Gate { get; }
}
