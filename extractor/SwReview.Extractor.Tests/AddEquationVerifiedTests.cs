using System;
using System.IO;
using System.Linq;
using System.Reflection;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T067. <c>AddEquationVerified</c> and <c>SetEquationVerified</c>: the two helpers every
/// equation write in the feature goes through, and the only evidence that a write landed.
///
/// <b>The return code is not the evidence.</b> PROBE-6 observed <c>IEquationMgr.Add3</c>
/// answering <c>-1</c> and adding nothing, silently. So each helper asserts on what it can
/// read back - the count moved (or did not move, for an in-place edit) <b>and</b>
/// <c>get_Equation(i)</c> round-trips to the text that was written - and only then reports
/// success. On a failure it tries the older member once and asserts again; a second failure
/// fails the change with <c>equation_unverified</c>.
///
/// The assertion is never inlined at a call site. That is why these are the only two public
/// members of <see cref="RemodelEquations"/> and why a test below pins that surface: a third
/// path would be a write whose evidence nobody checked.
///
/// <c>set</c> is FR-029's in-place repair and is <b>its own inverse</b>. Delete-and-re-add is
/// not a fallback and is not reachable from it: while a referenced global is missing, every
/// dependent equation enters an error state that does not clear when the global returns
/// (research R3.5).
/// </summary>
public class AddEquationVerifiedTests
{
    private const string RunId = "20260916-142201-bracket-remodel";

    /// <summary><c>swInConfigurationOpts_e.swAllConfiguration</c>; the caller composes it.</summary>
    private const int AllConfigurations = 2;

    private static readonly string RunDirectory =
        Path.Combine(Path.GetTempPath(), "SwReview.RemodelEquations", RunId);

    private static readonly string CopyPath =
        Path.Combine(RunDirectory, "copy", "bracket-RMS.SLDPRT");

    // ---- the add helper --------------------------------------------------------------

    [Fact]
    public void Add_WhenAdd3Lands_AssertsTheCountMovedAndTheTextRoundTrips()
    {
        FakeEquationManager equations = Manager();

        RemodelEquationResult result = Add(equations, 0, "\"w\" = 120");

        Assert.Equal(RemodelEquationHelperPaths.Add3, result.HelperPath);
        Assert.Equal(0, result.CountBefore);
        Assert.Equal(1, result.CountAfter);
        Assert.Equal("\"w\" = 120", result.RoundTripText);
        Assert.Null(result.PreviousText);

        // The count and the text are both read back; neither alone is the evidence.
        Assert.Equal(
            new[]
            {
                nameof(FakeEquationManager.GetCount),
                nameof(FakeEquationManager.Add3),
                nameof(FakeEquationManager.GetCount),
                nameof(FakeEquationManager.GetEquation),
            },
            equations.Members);
    }

    [Fact]
    public void Add_TheReturnCodeIsNotTheEvidence()
    {
        // PROBE-6 saw Add3 answer -1 and add nothing. Here it answers -1 and adds: the helper
        // believes the read-back, so this is a success through add3 and not a fallback.
        FakeEquationManager equations = Manager();
        equations.Add3Answer = -1;

        Assert.Equal(RemodelEquationHelperPaths.Add3, Add(equations, 0, "\"w\" = 120").HelperPath);
        Assert.DoesNotContain(nameof(FakeEquationManager.Add2), equations.Members);
    }

    [Fact]
    public void Add_WhenAdd3AddsNothing_FallsBackToAdd2AndAssertsAgain()
    {
        FakeEquationManager equations = Manager();
        equations.Add3Adds = false;

        RemodelEquationResult result = Add(equations, 0, "\"w\" = 120");

        Assert.Equal(RemodelEquationHelperPaths.Add2, result.HelperPath);
        Assert.Equal(1, result.CountAfter);
        Assert.Equal(new[] { "\"w\" = 120" }, equations.Equations);
    }

    [Fact]
    public void Add_WhenNeitherMemberCanBeProvenToHaveLanded_IsEquationUnverified()
    {
        FakeEquationManager equations = Manager();
        equations.Add3Adds = false;
        equations.Add2Adds = false;

        RemodelCommandError error = Assert.Throws<RemodelCommandError>(
            () => Add(equations, 0, "\"w\" = 120"));

        Assert.Equal(RemodelErrorCodes.EquationUnverified, error.ErrorCode);
        Assert.Contains(nameof(FakeEquationManager.Add2), equations.Members);
    }

    [Fact]
    public void Add_WhenTheCountMovesButTheTextDoesNotRoundTrip_IsNotASuccess()
    {
        // A row appeared and it is not the row that was asked for. That is a different part
        // from the one the plan described, so it is a failure and not a success.
        FakeEquationManager equations = Manager();
        equations.Add3Adds = false;
        equations.Add2Adds = false;
        equations.CountDrift = 1;

        Assert.Equal(
            RemodelErrorCodes.EquationUnverified,
            Assert.Throws<RemodelCommandError>(() => Add(equations, 0, "\"w\" = 120")).ErrorCode);
    }

    [Fact]
    public void Add_WithNoConfigurationOption_IsRefusedRatherThanAssumed()
    {
        // which_configs comes from the configuration count remodel.open recorded. A
        // single-configuration assumption is checked, never assumed.
        FakeEquationManager equations = Manager();

        Assert.Throws<RemodelCommandError>(() => RemodelEquations.AddEquationVerified(
            Scope(equations), Gate(), equations, 0, "\"w\" = 120", null, null));
        Assert.Empty(equations.Members);
    }

    [Fact]
    public void Add_WritesThroughTheScope_SoTheTargetIsVerifiedFirst()
    {
        FakeEquationManager equations = Manager();
        var target = new FakeRemodelDocument(CopyPath) { SessionTag = RunId };

        RemodelEquations.AddEquationVerified(
            new RemodelScope(target, Gate(), RunId, CopyPath, RunDirectory),
            Gate(),
            equations,
            0,
            "\"w\" = 120",
            AllConfigurations,
            null);

        Assert.Equal(
            new[]
            {
                nameof(FakeRemodelDocument.GetPathName),
                nameof(FakeRemodelDocument.GetSessionTag),
                nameof(FakeRemodelDocument.GetDocumentIdentity),
                nameof(FakeRemodelDocument.GetOpenDocumentIdentity),
            },
            target.Members);
    }

    // ---- the set helper --------------------------------------------------------------

    [Fact]
    public void Set_ReadsThePreviousTextBeforeWritingAndEditsInPlace()
    {
        FakeEquationManager equations = Manager("\"w\" = 100");

        RemodelEquationResult result = Set(equations, 0, "\"w\" = 120");

        Assert.Equal(RemodelEquationHelperPaths.SetEquation, result.HelperPath);
        Assert.Equal("\"w\" = 100", result.PreviousText);
        Assert.Equal("\"w\" = 120", result.RoundTripText);

        // The count is UNCHANGED: an in-place edit that changed the count edited something
        // else as well.
        Assert.Equal(1, result.CountBefore);
        Assert.Equal(1, result.CountAfter);

        Assert.Equal(nameof(FakeEquationManager.GetEquation), equations.Members[0]);
        Assert.Contains(nameof(FakeEquationManager.SetEquation), equations.Members);
    }

    [Fact]
    public void Set_IsNeverADeleteAndAnAdd()
    {
        // Deleting a referenced global puts every dependent equation into an error state that
        // does not clear when it returns (research R3.5), so set is its own operation and its
        // own inverse.
        FakeEquationManager equations = Manager("\"w\" = 100");
        Set(equations, 0, "\"w\" = 120");

        Assert.DoesNotContain(nameof(FakeEquationManager.Delete), equations.Members);
        Assert.DoesNotContain(nameof(FakeEquationManager.Add3), equations.Members);
        Assert.DoesNotContain(nameof(FakeEquationManager.Add2), equations.Members);
    }

    [Fact]
    public void Set_WhenThePreviousTextIsUnreadable_FailsWithoutWriting()
    {
        // An unreadable previous text is a change with no inverse; writing over it would be a
        // silent edit.
        FakeEquationManager equations = Manager("\"w\" = 100");
        equations.EquationUnreadable = true;

        Assert.Equal(
            RemodelErrorCodes.EquationUnverified,
            Assert.Throws<RemodelCommandError>(() => Set(equations, 0, "\"w\" = 120")).ErrorCode);
        Assert.DoesNotContain(nameof(FakeEquationManager.SetEquation), equations.Members);
        Assert.Equal(new[] { "\"w\" = 100" }, equations.Equations);
    }

    [Fact]
    public void Set_WhenSetEquationDoesNotWrite_FallsBackToSetEquationAndConfigurationOption()
    {
        FakeEquationManager equations = Manager("\"w\" = 100");
        equations.SetEquationWrites = false;

        RemodelEquationResult result = Set(equations, 0, "\"w\" = 120");

        Assert.Equal(
            RemodelEquationHelperPaths.SetEquationAndConfigurationOption, result.HelperPath);
        Assert.Equal(new[] { "\"w\" = 120" }, equations.Equations);
    }

    [Fact]
    public void Set_WhenNeitherMemberWrites_IsEquationUnverified()
    {
        FakeEquationManager equations = Manager("\"w\" = 100");
        equations.SetEquationWrites = false;
        equations.SetEquationAndConfigurationOptionWrites = false;

        Assert.Equal(
            RemodelErrorCodes.EquationUnverified,
            Assert.Throws<RemodelCommandError>(() => Set(equations, 0, "\"w\" = 120")).ErrorCode);
        Assert.Equal(new[] { "\"w\" = 100" }, equations.Equations);
    }

    [Fact]
    public void Set_AnIndexOutsideTheEquationList_IsRefusedBeforeAnyWrite()
    {
        FakeEquationManager equations = Manager("\"w\" = 100");

        Assert.Throws<RemodelCommandError>(() => Set(equations, 4, "\"w\" = 120"));
        Assert.DoesNotContain(nameof(FakeEquationManager.SetEquation), equations.Members);
    }

    // ---- the surface -----------------------------------------------------------------

    [Fact]
    public void TheHelpersAreTheOnlyPublicWayToWriteAnEquation()
    {
        // The assertion is never inlined at a call site: it is the only evidence the write
        // happened, and a second copy of it is a second thing to get wrong.
        Assert.Equal(
            new[] { "AddEquationVerified", "SetEquationVerified" },
            typeof(RemodelEquations)
                .GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly)
                .Select(method => method.Name)
                .OrderBy(name => name, StringComparer.Ordinal)
                .ToArray());
    }

    // ---- helpers ---------------------------------------------------------------------

    private static FakeEquationManager Manager(params string[] equations)
    {
        var manager = new FakeEquationManager();
        manager.Equations.AddRange(equations);
        manager.Members.Clear();
        return manager;
    }

    private static SwGate Gate() => new SwGate(new CircuitBreaker(), new RemodelGuard());

    private static RemodelScope Scope(FakeEquationManager equations) =>
        new RemodelScope(
            new FakeRemodelDocument(CopyPath) { SessionTag = RunId },
            Gate(),
            RunId,
            CopyPath,
            RunDirectory);

    private static RemodelEquationResult Add(FakeEquationManager equations, int index, string text) =>
        RemodelEquations.AddEquationVerified(
            Scope(equations), Gate(), equations, index, text, AllConfigurations, null);

    private static RemodelEquationResult Set(FakeEquationManager equations, int index, string text) =>
        RemodelEquations.SetEquationVerified(
            Scope(equations), Gate(), equations, index, text, AllConfigurations, null);
}
