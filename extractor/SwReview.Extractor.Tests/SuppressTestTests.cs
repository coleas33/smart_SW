using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.Extractor.Console;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using Xunit;
using IrFeature = SwReview.Extractor.Ir.Feature;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T054. The engineer-run suppress-test, over a fake <see cref="ISuppressTarget"/> and a
/// real plan file, on a machine with no seat.
///
/// This is the one command in the product that changes the engineer's model, so the tests
/// that matter most are about what it does NOT do: every refusal, no rebuild after a
/// suppression that did not take, no save member ever named to the gate, and a restore that
/// runs - and names what it could not put back - even when the rebuild throws.
///
/// The fake sits at the seam <c>SwSuppressTarget</c> implements, and the single-call interop
/// members are named to the gate by <see cref="SuppressTest"/> itself (the
/// <c>FeatureDumper</c> pattern), so the guard, the circuit breaker and the SC-003 observer
/// see the production member names under the fake.
/// </summary>
public class SuppressTestTests : IDisposable
{
    private const string Document = "doc:0002";
    private const string Configuration = "Default";
    private const string Group = "01_Detail";

    private readonly string _directory;

    public SuppressTestTests()
    {
        _directory = Path.Combine(Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_directory);
    }

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }

    // ---- the plan file -----------------------------------------------------------

    [Fact]
    public void Plan_Load_ReadsTheShapeTheReviewerWrites()
    {
        string path = WritePlan();

        SuppressPlan plan = SuppressPlan.Load(path);

        Assert.Equal(Document, plan.DocumentId);
        Assert.Equal(Configuration, plan.Configuration);
        Assert.Equal(Group, plan.Group);
        Assert.Equal(
            new[] { "feat:0002", "feat:0004", "feat:0005" },
            plan.Features.Select(feature => feature.FeatureId).ToArray());
        Assert.Equal("Fillet1", plan.Features[0].Name);
        Assert.Equal("Fillet", plan.Features[0].TypeName);
        Assert.Equal("ref:Fillet1", plan.Features[0].PersistRef);
        Assert.Equal(Document, plan.Features[0].PersistRefScope);
    }

    [Fact]
    public void Plan_Load_MissingFile_SaysHowToWriteOne()
    {
        string path = Path.Combine(_directory, "nope.json");

        FileNotFoundException error = Assert.Throws<FileNotFoundException>(() => SuppressPlan.Load(path));

        Assert.Contains("suppress-plan", error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("\"document_id\": \"doc:0002\"", "\"document_id\": \"\"", "document_id")]
    [InlineData("\"configuration\": \"Default\"", "\"configuration\": \"\"", "configuration")]
    [InlineData("\"group\": \"01_Detail\"", "\"group\": \"\"", "group")]
    [InlineData("\"persist_ref\": \"ref:Fillet1\"", "\"persist_ref\": \"\"", "persist_ref")]
    [InlineData("\"type_name\": \"Fillet\"", "\"type_name\": \"\"", "type_name")]
    public void Plan_Load_MissingField_IsRefusedRatherThanDefaulted(
        string original, string replacement, string named)
    {
        // Nothing in a plan is guessable: an empty configuration would suppress features in
        // whatever the document happens to be showing (constitution Principle I).
        string json = File.ReadAllText(WritePlan()).Replace(original, replacement);
        string path = Path.Combine(_directory, "broken-plan.json");
        File.WriteAllText(path, json);

        SuppressPlanError error = Assert.Throws<SuppressPlanError>(() => SuppressPlan.Load(path));

        Assert.Contains(named, error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Plan_Load_NoFeatures_IsRefused()
    {
        string path = Path.Combine(_directory, "empty-plan.json");
        File.WriteAllText(
            path,
            "{\"document_id\": \"doc:0002\", \"configuration\": \"Default\", "
            + "\"group\": \"01_Detail\", \"features\": []}");

        SuppressPlanError error = Assert.Throws<SuppressPlanError>(() => SuppressPlan.Load(path));

        Assert.Contains("features", error.Message, StringComparison.Ordinal);
    }

    // ---- refusals, before anything is touched -------------------------------------

    [Fact]
    public void Run_WithoutAcknowledgement_RefusesAndTouchesNothing()
    {
        Case test = NewCase();
        test.Options.Acknowledged = false;

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        // The library invariant and the command's own refusal say the same sentence, because
        // they are the same constant: the command refuses before it attaches to SOLIDWORKS
        // (contracts/cli.md, "refuses, before touching anything"), and this is the backstop
        // for any other caller.
        Assert.Equal(SuppressTest.AcknowledgementRequiredMessage, error.Message);
        Assert.Contains("--acknowledge-rebuild", error.Message, StringComparison.Ordinal);
        Assert.Empty(test.Target.Calls);
        Assert.Empty(test.Observer.Members);
    }

    [Fact]
    public void DocumentNotOpenMessage_NamesThePartAndWhyTheCommandWillNotOpenIt()
    {
        // The extractor's one open path is read-only and silent (SwSession.OpenReadOnly), and
        // a read-only document answers false to every SetSuppression2: opening the part here
        // would produce a run of not_applied rows that tested nothing.
        string message = SuppressTest.DocumentNotOpenMessage(@"C:\vault\housing.SLDPRT");

        Assert.Contains(@"C:\vault\housing.SLDPRT", message, StringComparison.Ordinal);
        Assert.Contains("write access", message, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("read-only", message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Run_UnsavedChanges_RefusesWithTheReopenMessage()
    {
        Case test = NewCase();
        test.Target.UnsavedChanges = true;

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("without saving", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("reopen", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("GetSaveFlag", test.Observer.Members);
        Assert.DoesNotContain("SetSuppression2", test.Observer.Members);
    }

    [Fact]
    public void Run_ActiveConfigurationDiffersFromThePlan_Refuses()
    {
        Case test = NewCase();
        test.Target.Configuration = "Machined";

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Machined", error.Message, StringComparison.Ordinal);
        Assert.Contains(Configuration, error.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("SetSuppression2", test.Observer.Members);
    }

    [Fact]
    public void Run_RolledBackFeature_RefusesNamingIt()
    {
        Case test = NewCase();
        test.Target.Features[2].RolledBack = true;

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Shell1", error.Message, StringComparison.Ordinal);
        Assert.Contains("IsRolledBack", test.Observer.Members);
        Assert.DoesNotContain("SetSuppression2", test.Observer.Members);
    }

    [Fact]
    public void Run_BaselineErrorsAlreadyPresent_RefusesNamingThem()
    {
        Case test = NewCase();
        test.Target.PreExistingErrors.Add("Fillet2 could not be rebuilt");

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Fillet2 could not be rebuilt", error.Message, StringComparison.Ordinal);
        Assert.Contains("GetWhatsWrongCount", test.Observer.Members);
        Assert.Contains("GetWhatsWrong", test.Observer.Members);
        Assert.DoesNotContain("SetSuppression2", test.Observer.Members);
        Assert.DoesNotContain("ForceRebuild3", test.Observer.Members);
    }

    [Fact]
    public void Run_NoPackageRowsForTheDocument_Refuses()
    {
        Case test = NewCase();
        test.Rows.RemoveAll(row => string.Equals(row.DocumentId, Document, StringComparison.Ordinal));

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains(Document, error.Message, StringComparison.Ordinal);
        Assert.Contains("dump", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Run_LiveWalkHasADifferentCount_RefusesAndSaysToDumpAgain()
    {
        Case test = NewCase();
        test.Target.Features.RemoveAt(4);

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("4", error.Message, StringComparison.Ordinal);
        Assert.Contains("5", error.Message, StringComparison.Ordinal);
        Assert.Contains("dump", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("SetSuppression2", test.Observer.Members);
    }

    [Fact]
    public void Run_LiveWalkIsInADifferentOrder_Refuses()
    {
        Case test = NewCase();
        FakeFeature moved = test.Target.Features[1];
        test.Target.Features.RemoveAt(1);
        test.Target.Features.Insert(3, moved);

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Fillet1", error.Message, StringComparison.Ordinal);
        Assert.Contains("dump", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Run_LiveTypeNameDiffers_Refuses()
    {
        Case test = NewCase();
        test.Target.Features[1].TypeName = "VarFillet";

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("VarFillet", error.Message, StringComparison.Ordinal);
        Assert.Contains("type", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Run_LiveNameDiffers_Refuses()
    {
        Case test = NewCase();
        test.Target.Features[1].Name = "Fillet1 renamed";

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Fillet1 renamed", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Run_LiveDepthDiffers_Refuses()
    {
        Case test = NewCase();
        test.Target.Features[3].Depth = 0;

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Chamfer1", error.Message, StringComparison.Ordinal);
        Assert.Contains("depth", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Run_LiveSuppressionDiffers_Refuses()
    {
        // The package says unsuppressed and the model says suppressed: the rows the rule
        // will read describe a different model, so a run built on them would be a quiet lie.
        Case test = NewCase();
        test.Target.Features[2].Suppressed = true;

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Shell1", error.Message, StringComparison.Ordinal);
        Assert.Contains("suppress", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Run_PackageDoesNotRecordSuppression_Refuses()
    {
        Case test = NewCase();
        test.Rows[2].Suppressed = null;

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Shell1", error.Message, StringComparison.Ordinal);
        Assert.Contains("dump", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Run_PlannedFeatureFailsIsSamePersistentID_Refuses()
    {
        Case test = NewCase();
        test.Target.Features[3].PersistRef = "ref:something-else";

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("Chamfer1", error.Message, StringComparison.Ordinal);
        Assert.Contains("dump", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("SetSuppression2", test.Observer.Members);
    }

    [Fact]
    public void Run_PlannedFeatureIsNotInThePackageRows_Refuses()
    {
        Case test = NewCase();
        test.Plan.Features[1].FeatureId = "feat:9999";

        SuppressTestRefusedError error = Assert.Throws<SuppressTestRefusedError>(() => test.Run());

        Assert.Contains("feat:9999", error.Message, StringComparison.Ordinal);
    }

    // ---- the run -------------------------------------------------------------------

    [Fact]
    public void Run_RecordsTheRunHeaderAndTheBaseline()
    {
        Case test = NewCase();

        SuppressTestRun run = test.Run().Run;

        Assert.Equal(Document, run.DocumentId);
        Assert.Equal(Configuration, run.Configuration);
        Assert.Equal(Group, run.Group);
        Assert.Equal(test.Options.PlanFile, run.PlanFile);
        Assert.True(run.Acknowledged);
        Assert.Equal(0, run.BaselineWhatsWrongCount);
        Assert.Equal(test.Options.Limit, run.Limit);
        Assert.Equal(test.Options.TimeoutSeconds, run.TimeoutSeconds);
        Assert.Equal(test.Clock.First, run.RunAt);

        // The invariant the reviewer reads the table under: a feature nobody reached is a
        // row, never a missing one (data-model section 2).
        Assert.Equal(3, run.FeaturesPresent);
        Assert.Equal(run.FeaturesPresent, run.Rows.Count);
        Assert.Equal(
            new[] { "feat:0002", "feat:0004", "feat:0005" },
            run.Rows.Select(row => row.FeatureId).ToArray());
        Assert.Equal(new[] { "Fillet1", "Chamfer1", "Fillet2" }, run.Rows.Select(row => row.Name).ToArray());
        Assert.Equal("ref:Fillet1", run.Rows[0].PersistRef);
        Assert.Equal(Document, run.Rows[0].PersistRefScope);
    }

    [Fact]
    public void Run_CleanSuppressions_AreOkAndTheTreeIsRestored()
    {
        Case test = NewCase();

        SuppressTestResult result = test.Run();

        Assert.True(result.Succeeded);
        Assert.Null(result.Error);
        Assert.All(result.Run.Rows, row => Assert.Equal(SuppressTestOutcome.Ok, row.Outcome));
        Assert.All(result.Run.Rows, row => Assert.Equal(0, row.WhatsWrongCount));
        Assert.All(result.Run.Rows, row => Assert.Empty(row.Messages));
        Assert.All(result.Run.Rows, row => Assert.Equal(0, row.MessagesTruncated));
        Assert.All(result.Run.Rows, row => Assert.Null(row.Error));
        Assert.True(result.Run.RestoreVerified);
        Assert.Empty(result.Run.UnrestoredFeatureIds);
        Assert.All(test.Target.Features, feature => Assert.False(feature.Suppressed));

        // One suppression and one rebuild per planned feature, and the restore put each one
        // back before the next was tried.
        Assert.Equal(3, test.Target.Calls.Count(call => call == "ForceRebuild3"));
        Assert.Equal(6, test.Target.Calls.Count(call => call == "SetSuppression2"));
    }

    [Fact]
    public void Run_FeatureAlreadySuppressed_IsSkippedAndNeverTouched()
    {
        Case test = NewCase();
        test.Target.Features[1].Suppressed = true;
        test.Rows[1].Suppressed = true;

        SuppressTestResult result = test.Run();

        Assert.Equal(SuppressTestOutcome.AlreadySuppressed, result.Run.Rows[0].Outcome);
        Assert.Null(result.Run.Rows[0].WhatsWrongCount);
        Assert.NotNull(result.Run.Rows[0].ElapsedMs);
        Assert.Equal(SuppressTestOutcome.Ok, result.Run.Rows[1].Outcome);
        Assert.Equal(SuppressTestOutcome.Ok, result.Run.Rows[2].Outcome);

        // It stays suppressed: the snapshot is the state the restore returns to.
        Assert.True(test.Target.Features[1].Suppressed);
        Assert.True(result.Run.RestoreVerified);
        Assert.Equal(2, test.Target.Calls.Count(call => call == "ForceRebuild3"));
    }

    [Fact]
    public void Run_SuppressionReturnsFalse_IsNotAppliedAndNothingIsRebuilt()
    {
        Case test = NewCase();
        test.Target.SuppressReturns = false;

        SuppressTestResult result = test.Run();

        Assert.All(result.Run.Rows, row => Assert.Equal(SuppressTestOutcome.NotApplied, row.Outcome));
        Assert.All(result.Run.Rows, row => Assert.Null(row.WhatsWrongCount));
        Assert.DoesNotContain("ForceRebuild3", test.Target.Calls);
        Assert.True(result.Run.RestoreVerified);

        // Nothing was suppressed and nothing was rebuilt, so the run proved nothing about any
        // feature. The exit code is the engineer's only signal, and a document opened
        // read-only answers false to every SetSuppression2 exactly like this: exit 0 here
        // would report a clean pass for a test that never ran (Principle I).
        Assert.False(result.Succeeded);
    }

    [Fact]
    public void Run_EveryPlannedFeatureAlreadySuppressed_ProvedNothingAndDoesNotSucceed()
    {
        Case test = NewCase();
        foreach (int index in new[] { 1, 3, 4 })
        {
            test.Target.Features[index].Suppressed = true;
            test.Rows[index].Suppressed = true;
        }

        SuppressTestResult result = test.Run();

        Assert.All(
            result.Run.Rows,
            row => Assert.Equal(SuppressTestOutcome.AlreadySuppressed, row.Outcome));
        Assert.DoesNotContain("ForceRebuild3", test.Target.Calls);
        Assert.True(result.Run.RestoreVerified);
        Assert.Null(result.Error);
        Assert.False(result.Succeeded);
    }

    [Fact]
    public void Run_SuppressionSaidYesButTheStateDidNotChange_IsNotApplied()
    {
        // SetSuppression2 answering true while IsSuppressed2 still says false is the case
        // that would otherwise be recorded as a clean pass for a feature never suppressed.
        Case test = NewCase();
        test.Target.SuppressApplies = false;

        SuppressTestResult result = test.Run();

        Assert.All(result.Run.Rows, row => Assert.Equal(SuppressTestOutcome.NotApplied, row.Outcome));
        Assert.DoesNotContain("ForceRebuild3", test.Target.Calls);
    }

    [Fact]
    public void Run_RebuildErrors_AreRecordedWithTheirCountAndMessages()
    {
        Case test = NewCase();
        test.Target.RebuildMessages["Chamfer1"] = new[] { "Chamfer1 failed", "Fillet2 failed" };

        SuppressTestResult result = test.Run();

        Assert.Equal(SuppressTestOutcome.Ok, result.Run.Rows[0].Outcome);
        Assert.Equal(SuppressTestOutcome.RebuildErrors, result.Run.Rows[1].Outcome);
        Assert.Equal(2, result.Run.Rows[1].WhatsWrongCount);
        Assert.Equal(new[] { "Chamfer1 failed", "Fillet2 failed" }, result.Run.Rows[1].Messages.ToArray());
        Assert.Equal(0, result.Run.Rows[1].MessagesTruncated);

        // A row fails only ABOVE the baseline, and the command refuses to start with a
        // non-zero one: a count equal to the baseline is the clean case and stays ok.
        Assert.Equal(SuppressTestOutcome.Ok, result.Run.Rows[2].Outcome);
        Assert.Equal(0, result.Run.Rows[2].WhatsWrongCount);
        Assert.True(result.Succeeded);
        Assert.True(result.Run.RestoreVerified);
    }

    [Fact]
    public void Run_MoreThanTwentyMessages_KeepsTwentyAndCountsTheRest()
    {
        Case test = NewCase();
        test.Target.RebuildMessages["Fillet1"] = Enumerable.Range(1, 23)
            .Select(i => "error " + i.ToString(CultureInfo.InvariantCulture))
            .ToArray();

        SuppressTestRow row = test.Run().Run.Rows[0];

        Assert.Equal(SuppressTestOutcome.RebuildErrors, row.Outcome);
        Assert.Equal(23, row.WhatsWrongCount);
        Assert.Equal(20, row.Messages.Count);
        Assert.Equal("error 1", row.Messages[0]);
        Assert.Equal("error 20", row.Messages[19]);
        Assert.Equal(3, row.MessagesTruncated);
    }

    [Fact]
    public void Run_SuppressionAlsoSuppressedDependents_RestoresThemFromTheSnapshot()
    {
        // Suppressing a parent suppresses its dependents. Unsuppressing only the feature
        // under test would leave them suppressed, and every later row would be measured
        // against a model that is quietly missing features.
        Case test = NewCase();
        test.Target.Features[1].Dependents.Add(test.Target.Features[2]);
        test.Target.Features[1].Dependents.Add(test.Target.Features[4]);

        SuppressTestResult result = test.Run();

        Assert.All(result.Run.Rows, row => Assert.Equal(SuppressTestOutcome.Ok, row.Outcome));
        Assert.All(test.Target.Features, feature => Assert.False(feature.Suppressed));
        Assert.True(result.Run.RestoreVerified);
        Assert.Empty(result.Run.UnrestoredFeatureIds);
        Assert.True(result.Succeeded);
    }

    [Fact]
    public void Run_ThrowingRebuild_AbortsRestoresWithTheBreakerResetAndNamesWhatItCouldNotPutBack()
    {
        // The breaker is open by the time the restore starts (threshold 1 here), so the
        // restore resets it first or it would put nothing back at all. The feature that
        // cannot be read re-opens it, and everything after that is named rather than assumed
        // good.
        Case test = NewCase(new CircuitBreaker(1));
        test.Target.Features[1].Dependents.Add(test.Target.Features[2]);
        test.Target.RebuildError = new COMException("SOLIDWORKS stopped answering");
        test.Target.UnreadableFeature = "Shell1";

        SuppressTestResult result = test.Run();

        Assert.False(result.Succeeded);
        Assert.Contains("SOLIDWORKS stopped answering", result.Error!, StringComparison.Ordinal);

        Assert.Equal(SuppressTestOutcome.Aborted, result.Run.Rows[0].Outcome);
        Assert.Contains("SOLIDWORKS stopped answering", result.Run.Rows[0].Error!, StringComparison.Ordinal);

        // A feature the run never reached is aborted, never truncated: truncated is a
        // deliberate skip and the rule reads it as one.
        Assert.Equal(SuppressTestOutcome.Aborted, result.Run.Rows[1].Outcome);
        Assert.Equal(SuppressTestOutcome.Aborted, result.Run.Rows[2].Outcome);
        Assert.Equal(result.Run.FeaturesPresent, result.Run.Rows.Count);

        Assert.False(result.Run.RestoreVerified);
        Assert.Contains("feat:0003", result.Run.UnrestoredFeatureIds);

        // The reset happened: Fillet1, restored before the unreadable feature was reached,
        // is back the way the snapshot had it.
        Assert.False(test.Target.Features[1].Suppressed);
    }

    [Fact]
    public void Run_RestoreFailsWithANonComException_StillReturnsTheRunAndNamesTheFeature()
    {
        // A dead session does not only raise COMException: SEHException,
        // InvalidComObjectException and RemotingException all come out of a stale RCW and
        // none of them derives from it. If one of those escapes the restore it escapes the
        // run, and the command writes no rms_suppress_test row and no "not restored" line for
        // a model it has already modified - the worst outcome this feature has.
        Case test = NewCase();
        test.Target.UnreadableFeature = "Shell1";
        test.Target.UnreadableError = new InvalidComObjectException("the RCW is gone");

        SuppressTestResult result = test.Run();

        Assert.False(result.Succeeded);
        Assert.False(result.Run.RestoreVerified);
        Assert.Contains("feat:0003", result.Run.UnrestoredFeatureIds);

        // The run stops on the first feature whose restore could not be confirmed, and says
        // which one it was: the failure is that the tree is no longer the tree the snapshot
        // describes, whatever the COM layer called it.
        Assert.Contains("could not be restored", result.Error!, StringComparison.Ordinal);
        Assert.Contains("feat:0003", result.Error!, StringComparison.Ordinal);

        // The row that was tested successfully keeps its own outcome: the restore failed
        // after it, and calling it aborted would describe a feature that was measured as one
        // that never was.
        Assert.Equal(SuppressTestOutcome.Ok, result.Run.Rows[0].Outcome);
        Assert.Equal(result.Run.FeaturesPresent, result.Run.Rows.Count);

        // And the run is still writable and still names the feature for the engineer.
        string written = string.Join(
            Environment.NewLine, SuppressTest.LogLines(result, test.Observer.Members));
        Assert.Contains("not restored", written, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("feat:0003", written, StringComparison.Ordinal);
    }

    [Fact]
    public void Run_MutationRefusedByTheGate_IsAbortedAndNothingIsSuppressed()
    {
        // The exemption lives in the gate the command builds and nowhere else: a
        // suppress-test wired to an ordinary gate must change nothing.
        Case test = NewCase();
        var readOnly = new SwGate(new CircuitBreaker()) { Observer = test.Observer };

        SuppressTestResult result = new SuppressTest(readOnly, test.Target, test.Clock.Read)
            .Run(test.Plan, test.Rows, test.Options);

        Assert.False(result.Succeeded);
        Assert.All(result.Run.Rows, row => Assert.Equal(SuppressTestOutcome.Aborted, row.Outcome));
        Assert.All(test.Target.Features, feature => Assert.False(feature.Suppressed));
        Assert.Equal("SetSuppression2", Assert.Single(test.Observer.Refusals).MemberName);
    }

    [Fact]
    public void Run_Limit_TruncatesTheRestAndStillWritesARowForEveryPlannedFeature()
    {
        Case test = NewCase();
        test.Options.Limit = 2;

        SuppressTestResult result = test.Run();
        SuppressTestRun run = result.Run;

        // A deliberate stop after two tested features is still a run that proved something.
        Assert.True(result.Succeeded);
        Assert.Equal(SuppressTestOutcome.Ok, run.Rows[0].Outcome);
        Assert.Equal(SuppressTestOutcome.Ok, run.Rows[1].Outcome);
        Assert.Equal(SuppressTestOutcome.Truncated, run.Rows[2].Outcome);
        Assert.Null(run.Rows[2].ElapsedMs);
        Assert.Null(run.Rows[2].WhatsWrongCount);
        Assert.Equal(3, run.FeaturesPresent);
        Assert.Equal(run.FeaturesPresent, run.Rows.Count);
        Assert.Equal(2, test.Target.Calls.Count(call => call == "ForceRebuild3"));
    }

    [Fact]
    public void Run_Timeout_TruncatesTheRest()
    {
        // The clock advances one second per reading and a row costs two readings, so the
        // third row starts after the five-second budget is gone.
        Case test = NewCase();
        test.Clock.Step = TimeSpan.FromSeconds(1);
        test.Options.TimeoutSeconds = 5;

        SuppressTestRun run = test.Run().Run;

        Assert.Equal(SuppressTestOutcome.Ok, run.Rows[0].Outcome);
        Assert.Equal(SuppressTestOutcome.Ok, run.Rows[1].Outcome);
        Assert.Equal(SuppressTestOutcome.Truncated, run.Rows[2].Outcome);
        Assert.Equal(run.FeaturesPresent, run.Rows.Count);
    }

    [Fact]
    public void Run_RecordsElapsedMsPerRow()
    {
        Case test = NewCase();
        test.Clock.Step = TimeSpan.FromMilliseconds(250);

        SuppressTestRun run = test.Run().Run;

        Assert.All(run.Rows, row => Assert.Equal(250, row.ElapsedMs));
    }

    // ---- what the gate saw ----------------------------------------------------------

    [Fact]
    public void Run_NamesEveryInteropMemberToTheGateAndNeverASaveMember()
    {
        Case test = NewCase();
        test.Target.RebuildMessages["Fillet1"] = new[] { "Fillet1 failed" };

        test.Run();

        Assert.Equal(
            new[]
            {
                "GetSaveFlag",
                "IsRolledBack",
                "IsSuppressed2",
                "GetWhatsWrongCount",
                "SetSuppression2",
                "ForceRebuild3",
                "GetWhatsWrong",
            },
            test.Observer.Members.ToArray());

        foreach (string save in new[] { "Save3", "SaveAs3", "SetSaveFlag", "ForceRebuildAll", "EditRollback" })
        {
            Assert.DoesNotContain(save, test.Observer.Members);
        }

        Assert.Empty(test.Observer.Refusals);
    }

    // ---- what the command writes ------------------------------------------------------

    [Fact]
    public void LogLines_CarryTheDistinctMemberNamesAndLandInSuppressTestLog()
    {
        Case test = NewCase();
        SuppressTestResult result = test.Run();

        using (var log = new ExtractLog(_directory, Program.SuppressTestLogFileName))
        {
            foreach (string line in SuppressTest.LogLines(result, test.Observer.Members))
            {
                log.Write(line);
            }
        }

        string written = File.ReadAllText(Path.Combine(_directory, "suppress-test.log"));

        Assert.Contains("SetSuppression2", written, StringComparison.Ordinal);
        Assert.Contains("ForceRebuild3", written, StringComparison.Ordinal);
        Assert.Contains("GetWhatsWrongCount", written, StringComparison.Ordinal);
        Assert.Contains(SuppressTest.ModifiedInMemoryMessage, written, StringComparison.Ordinal);
        Assert.Contains("3/3", written, StringComparison.Ordinal);
    }

    [Fact]
    public void LogLines_NameEveryUnrestoredFeature()
    {
        Case test = NewCase(new CircuitBreaker(1));
        test.Target.RebuildError = new COMException("SOLIDWORKS stopped answering");
        test.Target.UnreadableFeature = "Shell1";

        SuppressTestResult result = test.Run();
        string written = string.Join(Environment.NewLine, SuppressTest.LogLines(result, test.Observer.Members));

        Assert.Contains("feat:0003", written, StringComparison.Ordinal);
        Assert.Contains("not restored", written, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void ModifiedInMemoryMessage_TellsTheEngineerNotToSave()
    {
        Assert.Contains("modified in memory", SuppressTest.ModifiedInMemoryMessage, StringComparison.Ordinal);
        Assert.Contains("without saving", SuppressTest.ModifiedInMemoryMessage, StringComparison.Ordinal);
    }

    [Fact]
    public void AppendSuppressTest_PutsTheRunInThePackage()
    {
        PackageAppender.Save(
            _directory,
            new EvidencePackage { PackageId = Guid.NewGuid(), CreatedAt = DateTimeOffset.Now });

        SuppressTestResult result = NewCase().Run();
        string path = PackageAppender.AppendSuppressTest(_directory, result.Run);

        Assert.Equal(PackageAppender.PathIn(_directory), path);
        SuppressTestRun stored = PackageAppender.Load(_directory).RmsSuppressTest!;
        Assert.Equal(Document, stored.DocumentId);
        Assert.Equal(3, stored.Rows.Count);
        Assert.True(stored.RestoreVerified);
    }

    // ---- fixtures ----------------------------------------------------------------------

    private string WritePlan()
    {
        string path = Path.Combine(_directory, "suppress-plan.json");
        File.WriteAllText(
            path,
            @"{
  ""document_id"": ""doc:0002"",
  ""configuration"": ""Default"",
  ""group"": ""01_Detail"",
  ""features"": [
    {""feature_id"": ""feat:0002"", ""persist_ref"": ""ref:Fillet1"", ""persist_ref_scope"": ""doc:0002"", ""name"": ""Fillet1"", ""type_name"": ""Fillet""},
    {""feature_id"": ""feat:0004"", ""persist_ref"": ""ref:Chamfer1"", ""persist_ref_scope"": ""doc:0002"", ""name"": ""Chamfer1"", ""type_name"": ""Chamfer""},
    {""feature_id"": ""feat:0005"", ""persist_ref"": ""ref:Fillet2"", ""persist_ref_scope"": ""doc:0002"", ""name"": ""Fillet2"", ""type_name"": ""Fillet""}
  ]
}");
        return path;
    }

    /// <summary>
    /// The happy fixture every test starts from: five live features that match five package
    /// rows exactly, three of them planned, nothing suppressed and nothing wrong.
    /// </summary>
    private Case NewCase(CircuitBreaker? breaker = null)
    {
        var target = new FakeSuppressTarget(
            new FakeFeature("Extrude1", "Extrusion", 0),
            new FakeFeature("Fillet1", "Fillet", 0),
            new FakeFeature("Shell1", "Shell", 0),
            new FakeFeature("Chamfer1", "Chamfer", 1),
            new FakeFeature("Fillet2", "Fillet", 0));

        var rows = new List<IrFeature>();
        for (int i = 0; i < target.Features.Count; i++)
        {
            FakeFeature feature = target.Features[i];
            rows.Add(new IrFeature
            {
                Id = "feat:000" + (i + 1).ToString(CultureInfo.InvariantCulture),
                DocumentId = Document,
                Configuration = Configuration,
                Index = i,
                Depth = feature.Depth,
                Name = feature.Name,
                TypeName = feature.TypeName,
                Suppressed = feature.Suppressed,
                PersistRef = feature.PersistRef,
                PersistRefScope = Document,
            });
        }

        // A row from another document: the walk is compared against THIS document's rows.
        rows.Add(new IrFeature
        {
            Id = "feat:0099",
            DocumentId = "doc:0003",
            Configuration = Configuration,
            Index = 0,
            Name = "Extrude1",
            TypeName = "Extrusion",
            Suppressed = false,
            PersistRef = "ref:other",
            PersistRefScope = "doc:0003",
        });

        var observer = new RecordingGateObserver();

        return new Case
        {
            Target = target,
            Rows = rows,
            Plan = SuppressPlan.Load(WritePlan()),
            Gate = new SwGate(breaker ?? new CircuitBreaker(), new SuppressTestGuard()) { Observer = observer },
            Observer = observer,
            Clock = new TestClock(),
            Options = new SuppressTestSettings
            {
                PlanFile = Path.Combine(_directory, "suppress-plan.json"),
                Acknowledged = true,
            },
        };
    }

    private sealed class Case
    {
        public FakeSuppressTarget Target { get; set; } = null!;

        public List<IrFeature> Rows { get; set; } = null!;

        public SuppressPlan Plan { get; set; } = null!;

        public SuppressTestSettings Options { get; set; } = null!;

        public SwGate Gate { get; set; } = null!;

        public RecordingGateObserver Observer { get; set; } = null!;

        public TestClock Clock { get; set; } = null!;

        public SuppressTestResult Run() =>
            new SuppressTest(Gate, Target, Clock.Read).Run(Plan, Rows, Options);
    }

    /// <summary>
    /// A clock that advances by <see cref="Step"/> on every reading, so elapsed times and the
    /// timeout are exact rather than flaky: the run reads it once at the start and twice per
    /// row it attempts.
    /// </summary>
    private sealed class TestClock
    {
        private DateTimeOffset _now = new DateTimeOffset(2026, 1, 2, 3, 4, 5, TimeSpan.Zero);

        public TestClock()
        {
            First = _now;
        }

        /// <summary>What the first reading returns; the run records it as run_at.</summary>
        public DateTimeOffset First { get; }

        public TimeSpan Step { get; set; } = TimeSpan.Zero;

        public DateTimeOffset Read()
        {
            DateTimeOffset now = _now;
            _now = _now.Add(Step);
            return now;
        }
    }

    /// <summary>One live feature, with the switches the failure paths need.</summary>
    private sealed class FakeFeature
    {
        public FakeFeature(string name, string typeName, int depth)
        {
            Name = name;
            TypeName = typeName;
            Depth = depth;
            PersistRef = "ref:" + name;
        }

        public string Name { get; set; }

        public string TypeName { get; set; }

        public int Depth { get; set; }

        public string PersistRef { get; set; }

        public bool Suppressed { get; set; }

        public bool RolledBack { get; set; }

        /// <summary>Features SOLIDWORKS would suppress along with this one.</summary>
        public List<FakeFeature> Dependents { get; } = new List<FakeFeature>();

        public override string ToString() => Name;
    }

    /// <summary>
    /// The document with no SOLIDWORKS behind it. Every switch here is a failure a seat can
    /// produce: a suppression that answers no, one that answers yes and does nothing, a
    /// rebuild that throws, and a feature whose state cannot be read back.
    /// </summary>
    private sealed class FakeSuppressTarget : ISuppressTarget
    {
        private readonly List<string> _messages = new List<string>();

        public FakeSuppressTarget(params FakeFeature[] features)
        {
            Features = new List<FakeFeature>(features);
        }

        public List<FakeFeature> Features { get; }

        public List<string> PreExistingErrors { get; } = new List<string>();

        /// <summary>Messages the rebuild reports while the named feature is suppressed.</summary>
        public Dictionary<string, string[]> RebuildMessages { get; } =
            new Dictionary<string, string[]>(StringComparer.Ordinal);

        public string Configuration { get; set; } = "Default";

        public bool UnsavedChanges { get; set; }

        public bool SuppressReturns { get; set; } = true;

        /// <summary>False models SetSuppression2 answering yes without changing anything.</summary>
        public bool SuppressApplies { get; set; } = true;

        public Exception? RebuildError { get; set; }

        /// <summary>
        /// Once a rebuild has been attempted, reading or writing this feature's suppression
        /// throws, the way a stale RCW does after a rebuild died part-way.
        /// </summary>
        public string? UnreadableFeature { get; set; }

        /// <summary>
        /// What <see cref="UnreadableFeature"/> throws; null is the COMException a dead
        /// session usually raises. A stale RCW also raises types that do not derive from it.
        /// </summary>
        public Exception? UnreadableError { get; set; }

        /// <summary>Every call, in order, named by the interop member it stands for.</summary>
        public List<string> Calls { get; } = new List<string>();

        public string ActiveConfiguration()
        {
            Calls.Add("ActiveConfiguration");
            return Configuration;
        }

        public bool HasUnsavedChanges()
        {
            Calls.Add("GetSaveFlag");
            return UnsavedChanges;
        }

        public IReadOnlyList<LiveFeature> Walk()
        {
            Calls.Add("Walk");
            return Features
                .Select(feature => new LiveFeature(feature.Name, feature.TypeName, feature.Depth, feature))
                .ToList();
        }

        public bool IsRolledBack(object feature)
        {
            Calls.Add("IsRolledBack");
            return Feature(feature).RolledBack;
        }

        public bool IsSuppressed(object feature, string configuration)
        {
            Calls.Add("IsSuppressed2");
            FakeFeature target = Feature(feature);
            Fail(target);
            return target.Suppressed;
        }

        public bool Suppress(object feature, bool suppress, string configuration)
        {
            Calls.Add("SetSuppression2");
            FakeFeature target = Feature(feature);
            Fail(target);

            if (!SuppressReturns)
            {
                return false;
            }

            if (SuppressApplies)
            {
                target.Suppressed = suppress;
                if (suppress)
                {
                    foreach (FakeFeature dependent in target.Dependents)
                    {
                        dependent.Suppressed = true;
                    }
                }
            }

            return true;
        }

        public void Rebuild()
        {
            Calls.Add("ForceRebuild3");
            if (RebuildError != null)
            {
                throw RebuildError;
            }

            _messages.Clear();
            _messages.AddRange(PreExistingErrors);
            foreach (FakeFeature feature in Features)
            {
                if (feature.Suppressed && RebuildMessages.TryGetValue(feature.Name, out string[] messages))
                {
                    _messages.AddRange(messages);
                }
            }

            Rebuilt = true;
        }

        public int WhatsWrongCount()
        {
            Calls.Add("GetWhatsWrongCount");
            return Current().Count;
        }

        public IReadOnlyList<string> WhatsWrongMessages(int max)
        {
            Calls.Add("GetWhatsWrong");
            return Current().Take(max).ToList();
        }

        public bool IsSameFeature(string persistRef, object feature)
        {
            Calls.Add("IsSamePersistentID");
            return string.Equals(Feature(feature).PersistRef, persistRef, StringComparison.Ordinal);
        }

        /// <summary>True once a rebuild has run; before that the errors are the baseline's.</summary>
        private bool Rebuilt { get; set; }

        private List<string> Current() => Rebuilt ? _messages : PreExistingErrors;

        private void Fail(FakeFeature feature)
        {
            if (string.Equals(feature.Name, UnreadableFeature, StringComparison.Ordinal)
                && Calls.Contains("ForceRebuild3"))
            {
                throw UnreadableError ?? new COMException($"{feature.Name} is no longer answering.");
            }
        }

        private static FakeFeature Feature(object feature) => (FakeFeature)feature;
    }
}
