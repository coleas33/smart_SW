using System;
using System.Diagnostics;
using SwReview.Extractor.Dump;

namespace SwReview.AddIn.Review;

/// <summary>
/// Runs a piece of work on the SOLIDWORKS application thread.
///
/// Every interop call in the process has to happen there (constitution, Technical
/// Constraints), and <see cref="ReviewHost.Receive"/> runs off it so that a backend restart
/// or a dump does not freeze the pane's message pump. The implementation (T043) marshals onto
/// the Task Pane control; the tests never need one, because everything that decides anything
/// is on this side of the seam.
/// </summary>
public interface IApplicationThread
{
    /// <summary>Runs <paramref name="work"/> there and returns what it returned.</summary>
    T Invoke<T>(Func<T> work);
}

/// <summary>What one in-process dump produced, as the pane reports it.</summary>
public sealed class DumpSummary
{
    /// <param name="documents">Documents in the package, or null when the caller did not count
    /// them. Null rather than zero throughout: a zero is a statement about the design - "this
    /// part has no equations" - and the constitution forbids writing a default for engineering
    /// data. The Model check tab renders a count it was not given as absent.</param>
    /// <param name="features">Feature rows in the package, or null; same rule.</param>
    /// <param name="equations">Equation rows in the package, or null; same rule.</param>
    public DumpSummary(
        string packageFilePath,
        int components,
        int gaps,
        int? documents = null,
        int? features = null,
        int? equations = null)
    {
        PackageFilePath = packageFilePath ?? throw new ArgumentNullException(nameof(packageFilePath));
        Components = components;
        Gaps = gaps;
        Documents = documents;
        Features = features;
        Equations = equations;
    }

    /// <summary>Absolute path of the package.json that was written.</summary>
    public string PackageFilePath { get; }

    public int Components { get; }

    /// <summary>Gaps are normal and are reported, never hidden (constitution Principle I).</summary>
    public int Gaps { get; }

    /// <summary>Documents in the package; null when the dump did not report a count.</summary>
    public int? Documents { get; }

    /// <summary>Feature rows in the package; null when the dump did not report a count.</summary>
    public int? Features { get; }

    /// <summary>Equation rows in the package; null when the dump did not report a count.</summary>
    public int? Equations { get; }
}

/// <summary>
/// The extractor, behind one seam.
///
/// It exists so <see cref="ReviewHost"/>'s review flow - refuse without a document, name and
/// create the run folder, dump, post the session, reply - is testable with no SOLIDWORKS. The
/// real implementation is <see cref="SwReviewDump"/>, which runs the same
/// <c>PackageWriter</c> the console does, in this process, against the document already on
/// screen (spec: no second attach).
/// </summary>
public interface IReviewDump
{
    /// <summary>
    /// Dumps the active document into <paramref name="outputDirectory"/>, which already
    /// exists. <paramref name="progress"/> is called with one line per phase; the host turns
    /// each into a `status {stage: "extracting"}` message.
    ///
    /// <paramref name="profile"/> is how much of the design to read. It defaults to
    /// <see cref="DumpProfile.Full"/> so the review path keeps asking for every phase without
    /// restating it; a Model check asks for <see cref="DumpProfile.ModelCheck"/>, which reads
    /// documents, mates, features and equations and skips holes, fasteners, faces and meshes.
    /// The package records which one ran as `extractor.profile`, so a thin package is never
    /// mistaken for a model with no holes in it (FR-022).
    /// </summary>
    DumpSummary Run(
        string outputDirectory, Action<string> progress, DumpProfile profile = DumpProfile.Full);
}

/// <summary>One `entity.show` from the page (pane-host-messages.md).</summary>
public sealed class EntityShowRequest
{
    public EntityShowRequest(string persistRef, string? persistRefScope, string? componentId)
    {
        PersistRef = persistRef ?? throw new ArgumentNullException(nameof(persistRef));
        PersistRefScope = persistRefScope;
        ComponentId = componentId;
    }

    /// <summary>The base64 persistent reference carried by the finding.</summary>
    public string PersistRef { get; }

    /// <summary>The `document_id` whose extension produced the reference; may be null.</summary>
    public string? PersistRefScope { get; }

    /// <summary>The package component id the finding names; may be null.</summary>
    public string? ComponentId { get; }
}

/// <summary>
/// What became of a Show in SOLIDWORKS.
///
/// <see cref="FullPath"/> is the point of the type. A persistent reference that stops
/// resolving after a rebuild is an expected outcome, not a bug, and the engineer's next move
/// is to find the component by hand - so the failure carries the component's full instance
/// path (`sub-2/bracket-3`) alongside the state code rather than just saying no (spec Edge
/// Cases, SC-007).
/// </summary>
public sealed class EntityShowOutcome
{
    private EntityShowOutcome(bool ok, int stateCode, string? message, string? fullPath)
    {
        Ok = ok;
        StateCode = stateCode;
        Message = message;
        FullPath = fullPath;
    }

    public bool Ok { get; }

    /// <summary>`swPersistReferencedObjectStates_e`: 0 ok, 1 invalid, 2 suppressed, 4 deleted.</summary>
    public int StateCode { get; }

    public string? Message { get; }

    /// <summary>`IComponent2.Name2`, the full instance path, when one is known.</summary>
    public string? FullPath { get; }

    /// <summary>
    /// Selected. <paramref name="message"/> says what happened when it is worth saying - a
    /// folder has no geometry to zoom to, so "selected in the feature tree" is the difference
    /// between a working Show and an engineer staring at an unchanged graphics area.
    /// </summary>
    public static EntityShowOutcome Shown(string? fullPath, string? message = null) =>
        new EntityShowOutcome(true, 0, message ?? "ok", fullPath);

    /// <summary>Not selected; <paramref name="stateCode"/> and <paramref name="fullPath"/> say why and where.</summary>
    public static EntityShowOutcome NotShown(int stateCode, string message, string? fullPath) =>
        new EntityShowOutcome(false, stateCode, message, fullPath);
}

/// <summary>
/// Resolving, selecting and zooming, behind one seam.
///
/// One call rather than three, because the real implementation marshals onto the SOLIDWORKS
/// application thread and every hop costs a round trip through the message loop; and because
/// "resolve, then select, then zoom" is one operation whose failure modes only make sense
/// together.
/// </summary>
public interface IEntityResolver
{
    /// <summary>Selects and zooms to what <paramref name="request"/> names.</summary>
    EntityShowOutcome Show(EntityShowRequest request);
}

/// <summary>
/// `ShellExecute`, behind one seam.
///
/// Injected because the alternative is a unit test that opens Explorer windows and a
/// Markdown editor on the machine running it - and because the rule worth testing is which
/// path reaches the shell, not what the shell does with it.
/// </summary>
public interface IPathOpener
{
    /// <summary>Opens <paramref name="path"/> in the default application.</summary>
    void Open(string path);
}

/// <summary>The real opener: the shell's default verb, as the contract's "default app" means.</summary>
public sealed class ShellPathOpener : IPathOpener
{
    public void Open(string path)
    {
        // UseShellExecute is what picks the registered application for a .md file or opens a
        // folder in Explorer; without it this would try to execute the file.
        using (Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }))
        {
        }
    }
}
