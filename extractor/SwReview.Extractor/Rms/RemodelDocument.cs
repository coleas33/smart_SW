using System;
using System.Collections.Generic;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The equation manager, as the two verified helpers address it
/// (<see cref="RemodelEquations"/>). One member per VERIFIED interop call, so the helpers'
/// evidence - the count moved and the text round-tripped - is testable without a seat.
///
/// <c>IEquationMgr.set_GlobalVariable</c> is a VERIFIED ABSENCE and therefore not here: a
/// global variable is created by <b>syntax</b>, a quoted left-hand side with no <c>@</c>, and
/// nothing may treat globalness as a flag it can set.
/// </summary>
public interface IEquationTarget
{
    /// <summary><c>IEquationMgr.GetCount()</c>.</summary>
    int GetCount();

    /// <summary><c>IEquationMgr.get_Equation(index)</c>; null is unreadable.</summary>
    string? GetEquation(int index);

    /// <summary><c>IEquationMgr.Add3(Index, Equation, Solve, WhichConfigurations, ConfigNames)</c>.</summary>
    int Add3(int index, string equation, bool solve, int whichConfigurations, string[]? configNames);

    /// <summary><c>IEquationMgr.Add2(Index, Equation, Solve)</c>, the fallback.</summary>
    int Add2(int index, string equation, bool solve);

    /// <summary><c>IEquationMgr.set_Equation(Index, Equation)</c>: FR-029's in-place edit.</summary>
    void SetEquation(int index, string equation);

    /// <summary>
    /// <c>IEquationMgr.SetEquationAndConfigurationOption(Index, Equation, WhichConfigurations,
    /// ConfigNames)</c>, the in-place edit's fallback.
    /// </summary>
    int SetEquationAndConfigurationOption(
        int index, string equation, int whichConfigurations, string[]? configNames);

    /// <summary><c>IEquationMgr.Delete(Index)</c>, only ever the inverse of an add this run made.</summary>
    int Delete(int index);
}

/// <summary>
/// The copy, as every command after <c>remodel.open</c> addresses it. One interface, because
/// in the product one <c>IModelDoc2</c> answers all of it, and one seam, because a decision
/// that cannot be exercised without a SOLIDWORKS seat is a decision nobody tests.
///
/// It carries <see cref="IRemodelCopyTarget"/>'s four <c>VerifyTarget</c> reads and the tag
/// write, <see cref="IScopeSignalSource"/>'s nine signal reads, so <c>remodel.open</c>
/// step 12 re-reads the probe's rows on the copy through the same reader that read them on the
/// source, and <see cref="IGeometrySource"/>'s mass-property reads, because the copy is the
/// only document <c>remodel.geometry</c> can measure.
///
/// Features cross this seam as <c>object</c>, exactly as they do in
/// <c>IEquationReader</c> and <c>IFeatureReader</c>: an interop type in the signature would put
/// SOLIDWORKS in the test project.
/// </summary>
public interface IRemodelDocument : IRemodelCopyTarget, IScopeSignalSource, IGeometrySource
{
    /// <summary>
    /// <c>IModelDocExtension.GetObjectByPersistReference3(PersistId, out ErrorCode)</c>
    /// (VERIFIED, ByRef error code). The error code is read on <b>every</b> resolve; a ref
    /// that stops resolving is a failed change, never a retry and never a search by name.
    /// </summary>
    object? ResolveByPersistReference(string persistRef, out int errorCode);

    /// <summary><c>IModelDocExtension.GetPersistReference3(object)</c>.</summary>
    string? GetPersistReference(object feature);

    /// <summary>The feature tree in tree order.</summary>
    IReadOnlyList<object> GetFeaturesInOrder();

    /// <summary><c>IFeature.get_Name()</c>.</summary>
    string? GetFeatureName(object feature);

    /// <summary><c>IFeature.get_Description()</c>; null is unreadable, <c>""</c> is absent.</summary>
    string? GetFeatureDescription(object feature);

    /// <summary><c>IFeature.GetTypeName2()</c>.</summary>
    string? GetFeatureTypeName(object feature);

    /// <summary><c>IFeature.IsRolledBack()</c>.</summary>
    bool IsRolledBack(object feature);

    /// <summary><c>IFeature.GetErrorCode2(out IsWarning)</c>; <c>swFeatureErrorNone = 0</c>.</summary>
    int GetFeatureErrorCode(object feature, out bool isWarning);

    /// <summary><c>IFeature.set_Name</c>.</summary>
    void SetFeatureName(object feature, string name);

    /// <summary><c>IFeature.set_Description</c>.</summary>
    void SetFeatureDescription(object feature, string text);

    /// <summary><c>IFeature.Select2(Append, Mark)</c>.</summary>
    bool SelectFeature(object feature, bool append, int mark);

    /// <summary><c>IModelDoc2.ClearSelection2(true)</c>.</summary>
    void ClearSelection();

    /// <summary>
    /// <c>IModelDocExtension.ReorderFeature(FeatureToMove, TargetFeature, Location)</c>: the
    /// name-based call the resolve-and-read-name pair exists to feed. A bare <c>false</c> is a
    /// contract violation, not a retry.
    /// </summary>
    bool ReorderFeature(string featureName, string targetName, int location);

    /// <summary><c>IFeatureManager.InsertFeatureTreeFolder2(Type)</c>, Containing = 2.</summary>
    object? InsertFeatureTreeFolder(int type);

    /// <summary><c>IFeatureManager.FeatureFolderLocation(Feature)</c>: membership, verified.</summary>
    object? GetFeatureFolder(object feature);

    /// <summary><c>IFeatureManager.EditRollback(swMoveRollbackBarToEnd = 1, "")</c>.</summary>
    bool EditRollbackToEnd();

    /// <summary><c>IModelDoc2.ForceRebuild3(TopOnly)</c>. The one rebuild call, one meaning.</summary>
    bool ForceRebuild(bool topOnly);

    /// <summary><c>IModelDocExtension.GetWhatsWrongCount()</c>.</summary>
    int GetWhatsWrongCount();

    /// <summary><c>IModelDocExtension.GetWhatsWrong</c>, corroborating only (PROBE-9).</summary>
    IReadOnlyList<string> GetWhatsWrong();

    /// <summary><c>IModelDoc2.GetEquationMgr</c>.</summary>
    IEquationTarget Equations { get; }

    /// <summary>
    /// <c>IModelDoc2.Save3(Options, out Errors, out Warnings)</c> (VERIFIED, and it takes
    /// <b>no filename</b>, which is the structural reason it cannot reach the source).
    /// </summary>
    bool Save(int options, out int errors, out int warnings);

    /// <summary><c>IModelDoc2.GetSaveFlag()</c>: asserted false after a save.</summary>
    bool GetSaveFlag();

    /// <summary>
    /// The document's length unit, the only stated source for FR-027's metres-to-document-unit
    /// conversion. Null is unknown, and a change that needs it refuses rather than assuming
    /// metres: a wrong answer here silently builds a 120 metre part that rebuilds cleanly.
    /// </summary>
    string? GetLengthUnit();
}

/// <summary>
/// The SOLIDWORKS application, as the remodel commands reach it. Three things and no more:
/// the read-only view of the engineer's open source, the one open of the copy, and the close.
///
/// There is deliberately no member that opens the source and none that hands back a document
/// for a path the run did not create.
/// </summary>
public interface IRemodelSeat : IRemodelToggleHost
{
    /// <summary>The reads <c>remodel.probe_scope</c> makes, and nothing else.</summary>
    IRemodelProbeSource ProbeSource { get; }

    /// <summary>
    /// <c>ISldWorks.OpenDoc7</c> with <c>Silent | LoadModel = 17</c> exactly, and never
    /// <c>ReadOnly(2)</c> or <c>ViewOnly(4)</c>. Null is a failed open.
    /// </summary>
    IRemodelDocument? OpenDocument(string documentPath, int options);

    /// <summary><c>ISldWorks.CloseDoc</c>, on the tagged copy only.</summary>
    void CloseDocument(string documentPath);

    /// <summary>
    /// The EPDM vault path and revision of a source that is in one, or null. Recorded, never a
    /// refusal reason: an EPDM part is copied out (owner decision).
    /// </summary>
    VaultReference? GetVault(string sourcePath);
}

/// <summary>
/// One feature, resolved by persistent reference and named in the same breath - which is the
/// whole point: <c>ReorderFeature</c> and <c>set_Name</c> are name-based, names change on every
/// rename, and a name read at any other moment is a name that may no longer address this
/// feature.
/// </summary>
public readonly struct ResolvedFeature
{
    public ResolvedFeature(object feature, string name)
    {
        Feature = feature;
        Name = name;
    }

    public object Feature { get; }

    public string Name { get; }
}

/// <summary>
/// T062. One remodel run, as the bridge session holds it: the copy, the guard layers around
/// it, and the measurements <c>remodel.open</c> took.
///
/// It exists so that the handlers have exactly one place to reach the document from. There is
/// no second path: no command takes a document, <see cref="Scope"/> holds the only
/// <c>IModelDoc2</c> the run can reach, and every write goes through
/// <c>RemodelScope.Write</c>, which re-verifies the target before each one.
/// </summary>
public sealed class RemodelSession
{
    /// <summary>
    /// <c>IModelDocExtension.GetObjectByPersistReference3</c>, as the gate is told about it.
    /// A read: it takes <see cref="RemodelGuard"/>'s delegation branch.
    /// </summary>
    public const string ResolveMember = "GetObjectByPersistReference3";

    /// <summary><c>IFeature.get_Name</c>, as the gate is told about it.</summary>
    public const string NameMember = "get_Name";

    public RemodelSession(
        RemodelScope scope,
        IRemodelDocument document,
        SwGate gate,
        string sourcePath,
        SourceAttestation attestation,
        RemodelSystemToggles toggles)
    {
        Scope = scope ?? throw new ArgumentNullException(nameof(scope));
        Document = document ?? throw new ArgumentNullException(nameof(document));
        Gate = gate ?? throw new ArgumentNullException(nameof(gate));
        SourcePath = sourcePath ?? throw new ArgumentNullException(nameof(sourcePath));
        Attestation = attestation ?? throw new ArgumentNullException(nameof(attestation));
        Toggles = toggles ?? throw new ArgumentNullException(nameof(toggles));
    }

    /// <summary>Layer 2 of the write guard: which document a member may be called on.</summary>
    public RemodelScope Scope { get; }

    /// <summary>The copy. The only document this run can reach.</summary>
    public IRemodelDocument Document { get; }

    /// <summary>The gate the reads go through; the writes go through <see cref="Scope"/>.</summary>
    public SwGate Gate { get; }

    /// <summary>The engineer's file. Read once, at the probe, and never opened.</summary>
    public string SourcePath { get; }

    public SourceAttestation Attestation { get; }

    /// <summary>Restored in the <c>finally</c> that wraps the run, and at <c>remodel.close</c>.</summary>
    public RemodelSystemToggles Toggles { get; }

    /// <summary>The copy's signals, measured at <c>remodel.open</c> step 12.</summary>
    public ScopeSignals? Signals { get; set; }

    /// <summary>
    /// <c>GetWhatsWrongCount()</c> at the baseline, which is zero by construction: a non-zero
    /// count refuses the run at <c>remodel.open</c> step 11. It is recorded rather than assumed
    /// because a change that raises the count above <b>this</b> number is what gets inverted.
    /// </summary>
    public int BaselineRebuildErrors { get; set; }

    public string? LengthUnit { get; set; }

    /// <summary>
    /// How many geometry readings this run has taken. It stamps
    /// <c>GeometryReading.subject</c> - the first reading of a run is <c>copy_at_open</c> and
    /// every later one is <c>copy_at_end</c>, so the phase is the run's own and the caller
    /// cannot ask for a reading of anything else - and it is what <c>remodel.save</c> checks
    /// a reported <c>pass</c> against, because a verdict needs a before and an after and this
    /// host is the only thing that can say whether it produced them.
    /// </summary>
    public int GeometryReadings { get; set; }

    /// <summary>True once this run's baseline geometry reading has been taken.</summary>
    public bool BaselineGeometryTaken => GeometryReadings > 0;

    public IReadOnlyList<string> Configurations { get; set; } = new string[0];

    /// <summary>
    /// The refusal a command gets when it addresses a persistent reference the copy will not
    /// resolve: the change fails and the run stops. Never a retry, and never a search by name -
    /// a name that resolves to the wrong feature writes to the wrong feature.
    /// </summary>
    public ResolvedFeature Resolve(string persistRef)
    {
        if (string.IsNullOrWhiteSpace(persistRef))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.PersistRefUnresolved, "a persistent reference is required.");
        }

        int errorCode = 0;
        object? feature = Gate.Call(
            ResolveMember, () => Document.ResolveByPersistReference(persistRef, out errorCode));

        if (feature == null || errorCode != 0)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.PersistRefUnresolved,
                $"'{persistRef}' could not be addressed in the copy: "
                + $"GetObjectByPersistReference3 answered error code {errorCode}. The change "
                + "fails and the run stops; a reference is never retried and never replaced by "
                + "a search.",
                new Dictionary<string, string>(StringComparer.Ordinal)
                {
                    { "persist_ref", persistRef },
                    { "error_code", errorCode.ToString(System.Globalization.CultureInfo.InvariantCulture) },
                });
        }

        string? name = Gate.Call(NameMember, () => Document.GetFeatureName(feature!));
        if (string.IsNullOrEmpty(name))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.PersistRefUnresolved,
                $"'{persistRef}' resolved to a feature whose name could not be read, and every "
                + "call that follows a resolve is name-based.");
        }

        return new ResolvedFeature(feature!, name!);
    }
}
