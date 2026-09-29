using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T065. <c>remodel.rebuild</c>, <c>remodel.save</c> and <c>remodel.close</c>: the three
/// commands that end a change, end a run, and end a session.
///
/// <c>rebuild</c>'s <b>primary</b> reading is the per-feature <c>IFeature.GetErrorCode2</c>
/// walk in <c>feature_errors[]</c>, which is what the verify phase reads.
/// <c>GetWhatsWrong</c> is corroborating only: its out-array element type is UNVERIFIED
/// (PROBE-9) and re-joining by name is fragile where two features inside different folders
/// share a name. <c>IModelDoc2.EditRebuild3</c> is not allowlisted, so there is one rebuild
/// call and it has one meaning.
///
/// <c>save</c> calls <c>IModelDoc2.Save3</c> - which takes <b>no filename</b> (VERIFIED), the
/// structural reason it cannot reach the source - with <c>Silent = 1</c> and nothing else,
/// behind <c>AssertSaveTarget</c>. A non-zero <c>errors</c> is a failed run; a
/// <c>swFileSaveWarning_RebuildError</c> warning is a failed run <b>with a saved artifact</b>,
/// and the answer says exactly that rather than reporting success.
///
/// <c>close</c> closes the tagged copy only. With <c>discard_copy</c> it deletes the copy and
/// nothing else: <b>discard keeps every other artifact</b>, because deleting the run folder
/// would lose the evidence Principle VI asks for, and "what did it propose?" has to stay
/// answerable after the engineer says no.
/// </summary>
public class RemodelFinishHandlerTests : IDisposable
{
    private readonly RemodelHarness _harness;

    public RemodelFinishHandlerTests()
    {
        _harness = new RemodelHarness(
            new FakeFeature("ref:boss", "Boss-Extrude1"),
            new FakeFeature("ref:fillet", "Fillet1"));
        _harness.Open();
    }

    public void Dispose() => _harness.Dispose();

    // ---- remodel.rebuild -------------------------------------------------------------

    [Fact]
    public void Rebuild_CarriesThePerFeatureErrorWalkAsThePrimaryReading()
    {
        _harness.Copy.Features[1].ErrorCode = 12;
        _harness.Copy.Features[1].IsWarning = true;
        _harness.Copy.WhatsWrongCount = 1;
        _harness.Copy.WhatsWrongRows.Add("Fillet1: the face no longer exists");

        var result = RemodelHarness.Ok<RemodelRebuildResult>(
            _harness.Dispatch(RemodelCommands.Rebuild, "{\"force\":false}"));

        Assert.Equal(1, result.RebuildErrors);
        Assert.Equal(2, result.FeatureErrors.Count);

        RemodelFeatureError boss = result.FeatureErrors[0];
        Assert.Equal("ref:boss", boss.PersistRef);
        Assert.Equal("Boss-Extrude1", boss.Name);
        Assert.Equal(0, boss.ErrorCode);
        Assert.False(boss.IsWarning);

        RemodelFeatureError fillet = result.FeatureErrors[1];
        Assert.Equal("ref:fillet", fillet.PersistRef);
        Assert.Equal(12, fillet.ErrorCode);
        Assert.True(fillet.IsWarning);

        // Corroborating only, and carried rather than interpreted.
        Assert.Equal(
            new[] { "Fillet1: the face no longer exists" }, result.WhatsWrong);
    }

    [Fact]
    public void Rebuild_UsesForceRebuild3AndNeverEditRebuild3()
    {
        _harness.Dispatch(RemodelCommands.Rebuild, "{\"force\":true}");

        Assert.Contains("IModelDoc2.ForceRebuild3", _harness.Observer.Members);
        Assert.DoesNotContain("EditRebuild3", _harness.Observer.Members);
        Assert.Empty(_harness.Observer.Refusals);
        Assert.True(_harness.Copy.LastRebuildTopOnly);
    }

    [Fact]
    public void Rebuild_ForceDefaultsToFalseRatherThanBeingRequired()
    {
        _harness.Dispatch(RemodelCommands.Rebuild, "{}");

        Assert.False(_harness.Copy.LastRebuildTopOnly);
    }

    [Fact]
    public void Rebuild_BeforeOpen_IsRefused()
    {
        using (var fresh = new RemodelHarness(new FakeFeature("ref:boss", "Boss-Extrude1")))
        {
            Assert.Equal(
                RemodelErrorCodes.TargetMismatch,
                RemodelHarness.Refusal(fresh.Dispatch(RemodelCommands.Rebuild, "{}")));
        }
    }

    // ---- remodel.save ----------------------------------------------------------------

    [Fact]
    public void Save_CallsSave3WithSilentAndNothingElseAndChecksTheSaveFlag()
    {
        _harness.Copy.SaveFlag = true;
        _harness.GeometryGate();

        var result = RemodelHarness.Ok<RemodelSaveResult>(
            _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("pass")));

        // Silent = 1 exactly, and never Copy(2), SaveReferenced(4) or AvoidRebuildOnSave(8).
        Assert.Equal(1, _harness.Copy.SaveOptions);
        Assert.Equal(_harness.CopyPath, result.Path);
        Assert.Equal(0, result.Errors);
        Assert.False(result.SaveFlagAfter);
    }

    [Fact]
    public void Save_VerifiesTheTargetBeforeItWrites()
    {
        _harness.GeometryGate();
        _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("pass"));

        var members = _harness.Copy.Members;
        int write = members.IndexOf(nameof(FakeRemodelDocument.Save));
        Assert.Equal(
            new[]
            {
                nameof(FakeRemodelDocument.GetPathName),
                nameof(FakeRemodelDocument.GetSessionTag),
                nameof(FakeRemodelDocument.GetDocumentIdentity),
                nameof(FakeRemodelDocument.GetOpenDocumentIdentity),
            },
            members.GetRange(write - 4, 4));
    }

    [Fact]
    public void Save_NonZeroErrors_IsAFailedRun()
    {
        _harness.Copy.SaveErrors = 3;
        _harness.GeometryGate();

        Assert.Equal(
            RemodelErrorCodes.SaveFailed,
            RemodelHarness.Refusal(
                _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("pass"))));
    }

    [Fact]
    public void Save_ARebuildErrorWarning_IsAFailedRunWithASavedArtifactAndSaysSo()
    {
        // swFileSaveWarning_RebuildError (1). The file is on disk and the run failed; a report
        // that said "success" here would be describing a part nobody checked.
        _harness.Copy.SaveWarnings = 1;
        _harness.GeometryGate();

        BridgeResponse response =
            _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("pass"));

        Assert.Equal(RemodelErrorCodes.SaveFailed, RemodelHarness.Refusal(response));
        var error = Assert.IsType<RemodelErrorResult>(response.Result);
        Assert.Equal("true", error.Detail!["saved"]);
        Assert.Equal("1", error.Detail["warnings"]);
        Assert.Contains("rebuild error", response.Error!, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Save_ASaveFlagStillSetAfterwards_IsAFailedRun()
    {
        // GetSaveFlag() is asserted false afterwards: a document SOLIDWORKS still considers
        // dirty was not saved, whatever Save3 answered.
        _harness.Copy.SaveFlag = true;
        _harness.Copy.SaveClearsFlag = false;
        _harness.GeometryGate();

        Assert.Equal(
            RemodelErrorCodes.SaveFailed,
            RemodelHarness.Refusal(
                _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("pass"))));
    }

    // ---- remodel.save: the geometry gate ---------------------------------------------

    /// <summary>
    /// The constitution's mutation exception permits <c>Save3</c> "only after the geometry
    /// comparison has passed", and contracts/bridge-remodel.md spells that as a host-side
    /// <c>gate_not_passed</c>. It is refused here, beside the call it guards, rather than
    /// only in the caller that reports the verdict: a clause enforced solely by the caller is
    /// a clause the caller can skip.
    /// </summary>
    [Theory]
    [InlineData("fail")]
    [InlineData("unresolved")]
    public void Save_WithoutAPassVerdict_IsGateNotPassedAndWritesNothing(string verdict)
    {
        _harness.GeometryGate();

        BridgeResponse response =
            _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams(verdict));

        Assert.Equal(RemodelErrorCodes.GateNotPassed, RemodelHarness.Refusal(response));
        Assert.Equal(verdict, Assert.IsType<RemodelErrorResult>(response.Result).Detail!["verdict"]);
        Assert.DoesNotContain(nameof(FakeRemodelDocument.Save), _harness.Copy.Members);
    }

    /// <summary>
    /// A verdict needs a before and an after, and this host is the only thing that can say
    /// whether it produced them. A reported <c>pass</c> from a run that took no reading is a
    /// gate that never ran, and the refusal names that as well as the verdict.
    /// </summary>
    [Fact]
    public void Save_WithAPassVerdictButNoReadingToReachItFrom_IsGateNotPassed()
    {
        BridgeResponse response =
            _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("pass"));

        Assert.Equal(RemodelErrorCodes.GateNotPassed, RemodelHarness.Refusal(response));
        Assert.Equal("0", Assert.IsType<RemodelErrorResult>(response.Result).Detail!["geometry_readings"]);
        Assert.DoesNotContain(nameof(FakeRemodelDocument.Save), _harness.Copy.Members);
    }

    [Fact]
    public void Save_WithOnlyTheBaselineReading_IsGateNotPassed()
    {
        RemodelHarness.Ok<GeometryReading>(_harness.Dispatch(RemodelCommands.Geometry, "{}"));

        Assert.Equal(
            RemodelErrorCodes.GateNotPassed,
            RemodelHarness.Refusal(
                _harness.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("pass"))));
        Assert.DoesNotContain(nameof(FakeRemodelDocument.Save), _harness.Copy.Members);
    }

    /// <summary>
    /// No verdict at all is not a passing one. It is a malformed request rather than a gate
    /// refusal, because the client composes the whole params object for every command.
    /// </summary>
    [Fact]
    public void Save_WithNoVerdictAtAll_IsARefusalAndNotASave()
    {
        _harness.GeometryGate();

        Assert.Equal(
            RemodelErrorCodes.BadRequest,
            RemodelHarness.Refusal(_harness.Dispatch(RemodelCommands.Save, "{}")));
        Assert.DoesNotContain(nameof(FakeRemodelDocument.Save), _harness.Copy.Members);
    }

    // ---- remodel.close ---------------------------------------------------------------

    [Fact]
    public void Close_ClosesTheTaggedCopyAndKeepsItOnDisk()
    {
        var result = RemodelHarness.Ok<RemodelCloseResult>(
            _harness.Dispatch(RemodelCommands.Close, "{}"));

        Assert.True(result.Closed);
        Assert.False(result.CopyDeleted);
        Assert.Equal(_harness.CopyPath, Assert.Single(_harness.Seat.Closed));
        Assert.True(File.Exists(_harness.CopyPath));
    }

    /// <summary>
    /// The session tag is written at open and removed at close
    /// (contracts/guard-allowlist.md's row for <c>ICustomPropertyManager.Delete2</c>). Without
    /// this the allowlist would carry a key with no call path, which
    /// <see cref="RemodelGuard"/>'s own rule calls the accidental widening the allowlist
    /// exists to prevent.
    /// </summary>
    [Fact]
    public void Close_RemovesTheSessionTagThroughTheGateBeforeItClosesTheDocument()
    {
        RemodelHarness.Ok<RemodelCloseResult>(_harness.Dispatch(RemodelCommands.Close, "{}"));

        Assert.Null(_harness.Copy.SessionTag);
        Assert.Contains("ICustomPropertyManager.Delete2", _harness.Observer.Members);
        Assert.Empty(_harness.Observer.Refusals);

        // The order is load-bearing: the tag is VerifyTarget's check 2, so it is removed after
        // the last verification and before the close, never after the document is gone.
        List<string> members = _harness.Copy.Members;
        int removed = members.IndexOf(nameof(FakeRemodelDocument.RemoveSessionTag));
        int verified = members.LastIndexOf(nameof(FakeRemodelDocument.GetOpenDocumentIdentity));
        Assert.True(removed > verified, "the tag was removed before the target was verified");
    }

    [Fact]
    public void Close_WithDiscard_DeletesTheCopyAndKeepsEveryOtherArtifact()
    {
        string plan = Path.Combine(_harness.RunDirectory, "plan.json");
        File.WriteAllText(plan, "{}");

        var result = RemodelHarness.Ok<RemodelCloseResult>(
            _harness.Dispatch(RemodelCommands.Close, "{\"discard_copy\":true}"));

        Assert.True(result.CopyDeleted);
        Assert.False(File.Exists(_harness.CopyPath));

        // Discard keeps every artifact but the .SLDPRT: "what did it propose?" stays
        // answerable after the engineer says no.
        Assert.True(File.Exists(plan));
        Assert.True(Directory.Exists(_harness.RunDirectory));
    }

    [Fact]
    public void Close_RestoresTheSystemTogglesItSet()
    {
        _harness.Seat.ToggleWrites.Clear();

        _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(
            new[] { "10=False", "77=False", "329=False" },
            _harness.Seat.ToggleWrites);
    }

    [Fact]
    public void Close_EndsTheRun_SoTheNextCommandHasNoScopeToActOn()
    {
        _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(
            RemodelErrorCodes.TargetMismatch,
            RemodelHarness.Refusal(_harness.Dispatch(RemodelCommands.Snapshot, "{}")));
    }

    [Fact]
    public void Close_BeforeOpen_IsRefused()
    {
        using (var fresh = new RemodelHarness(new FakeFeature("ref:boss", "Boss-Extrude1")))
        {
            Assert.Equal(
                RemodelErrorCodes.TargetMismatch,
                RemodelHarness.Refusal(fresh.Dispatch(RemodelCommands.Close, "{}")));
        }
    }

    // ---- remodel.close through the end-of-session routine (004 T167) ------------------
    //
    // The verification, the untag and the close used to run outside any `try`, so one throw
    // left the four settings flipped and every later `remodel.open` on that attachment answered
    // `run_in_progress`. Now the close is the routine a teardown runs too
    // (contracts/bridge-remodel.md, "Ending a session"): whatever fails, all four settings are
    // put back, the session is cleared, and the answer names what was left.

    [Fact]
    public void Close_WhoseVerificationFails_IsTargetMismatch_ClosesNothing_AndRestoresAllFour()
    {
        _harness.Copy.SessionTag = "20260101-000000-another-run";
        _harness.Seat.ToggleWrites.Clear();

        BridgeResponse response = _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(RemodelErrorCodes.TargetMismatch, RemodelHarness.Refusal(response));
        IReadOnlyDictionary<string, string> detail = Detail(response);
        Assert.Equal("false", detail["verified"]);
        Assert.Equal("2", detail["failed_check"]);
        Assert.Equal("false", detail["copy_closed"]);
        Assert.Equal("4", detail["settings_restored"]);
        Assert.Equal(string.Empty, detail["settings_outstanding"]);
        Assert.Equal("false", detail["copy_deleted"]);
        Assert.Equal(RemodelSessionEnd.ReasonClose, detail["reason"]);
        Assert.Contains("check 2", response.Error!, StringComparison.Ordinal);

        Assert.Empty(_harness.Seat.Closed);
        Assert.Equal(
            new[] { "10=False", "77=False", "329=False" },
            _harness.Seat.ToggleWrites);
        AssertTheSessionIsOverAndTheNextOpenGoesThrough();
    }

    [Fact]
    public void Close_WhoseUntagThrows_IsCloseIncomplete_ButStillClosesAndRestores()
    {
        _harness.Copy.UntagFailure = new System.Runtime.InteropServices.COMException("Delete2 refused");

        BridgeResponse response = _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(RemodelErrorCodes.CloseIncomplete, RemodelHarness.Refusal(response));
        IReadOnlyDictionary<string, string> detail = Detail(response);
        Assert.Equal("true", detail["verified"]);
        Assert.False(detail.ContainsKey("failed_check"));
        Assert.Equal("false", detail["tag_removed"]);
        Assert.Equal("true", detail["copy_closed"]);
        Assert.Equal("4", detail["settings_restored"]);
        Assert.Contains("Delete2 refused", response.Error!, StringComparison.Ordinal);
        Assert.Equal(_harness.CopyPath, Assert.Single(_harness.Seat.Closed));
        AssertTheSessionIsOverAndTheNextOpenGoesThrough();
    }

    [Fact]
    public void Close_WhoseCloseThrows_IsCloseIncomplete_AndSaysTheCopyWasNotClosed()
    {
        _harness.Seat.CloseFailure = new System.Runtime.InteropServices.COMException("CloseDoc refused");

        BridgeResponse response = _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(RemodelErrorCodes.CloseIncomplete, RemodelHarness.Refusal(response));
        Assert.Equal("false", Detail(response)["copy_closed"]);
        Assert.Equal("4", Detail(response)["settings_restored"]);
        Assert.Contains("The copy may still be open and 4 of 4 settings are back.", response.Error!, StringComparison.Ordinal);
        _harness.Seat.CloseFailure = null;
        AssertTheSessionIsOverAndTheNextOpenGoesThrough();
    }

    /// <summary>
    /// 004 T179 (default taken 2026-09-27, the owner may revise; research R15.3): <c>Delete2</c>'s
    /// answer decides <c>tag_removed</c>. One that is not <c>swCustomInfoDeleteResult_OK</c> is named,
    /// and the copy is still closed.
    /// </summary>
    [Fact]
    public void Close_WhoseUntagSolidworksDeclined_IsCloseIncomplete_NamingTheAnswer()
    {
        _harness.Copy.UntagAnswer = 1;

        BridgeResponse response = _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(RemodelErrorCodes.CloseIncomplete, RemodelHarness.Refusal(response));
        Assert.Equal("false", Detail(response)["tag_removed"]);
        Assert.Equal("true", Detail(response)["copy_closed"]);
        Assert.Contains("Delete2 answered swCustomInfoDeleteResult_NotPresent (1)", response.Error!, StringComparison.Ordinal);
        Assert.Contains("The copy was closed unsaved", response.Error!, StringComparison.Ordinal);
        _harness.Copy.UntagAnswer = 0;
        AssertTheSessionIsOverAndTheNextOpenGoesThrough();
    }

    /// <summary>
    /// 004 T179: a <c>CloseDoc</c> that returned and left the copy open is no close - the answer says
    /// SOLIDWORKS still has it, and that the copy may still be open rather than that it was closed.
    /// </summary>
    [Fact]
    public void Close_ThatSolidworksDidNotCarryOut_IsCloseIncomplete_AndSaysTheCopyMayStillBeOpen()
    {
        _harness.Seat.CloseLeavesItOpen = true;

        BridgeResponse response = _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(RemodelErrorCodes.CloseIncomplete, RemodelHarness.Refusal(response));
        Assert.Equal("true", Detail(response)["tag_removed"]);
        Assert.Equal("false", Detail(response)["copy_closed"]);
        Assert.Equal("4", Detail(response)["settings_restored"]);
        Assert.Contains("SOLIDWORKS still has the copy open", response.Error!, StringComparison.Ordinal);
        Assert.Contains("The copy may still be open", response.Error!, StringComparison.Ordinal);
        Assert.DoesNotContain("closed unsaved", response.Error!, StringComparison.Ordinal);
        _harness.Seat.CloseLeavesItOpen = false;
        _harness.Seat.OpenDocuments.Clear();
        AssertTheSessionIsOverAndTheNextOpenGoesThrough();
    }

    [Fact]
    public void Close_WhoseRestoreFailsPartWay_IsCloseIncomplete_NamingTheSettingStillSet()
    {
        // A toggle, since CommandInProgress went back at the open (U27).
        _harness.Seat.FailingWrites.Add("77=False");

        BridgeResponse response = _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Equal(RemodelErrorCodes.CloseIncomplete, RemodelHarness.Refusal(response));
        Assert.Equal("3", Detail(response)["settings_restored"]);
        Assert.Equal("swShowErrorsEveryRebuild", Detail(response)["settings_outstanding"]);
        Assert.Equal("true", Detail(response)["copy_closed"]);
        _harness.Seat.FailingWrites.Clear();
        AssertTheSessionIsOverAndTheNextOpenGoesThrough();
    }

    [Fact]
    public void Close_WhoseCircuitIsOpen_StillClosesTheCopyAndRestoresAllFour()
    {
        while (!_harness.Gate.Breaker.IsOpen)
        {
            try
            {
                _harness.Gate.Breaker.Execute<int>(
                    () => throw new System.Runtime.InteropServices.COMException("the session died"));
            }
            catch (System.Runtime.InteropServices.COMException)
            {
            }
        }

        _harness.Seat.ToggleWrites.Clear();

        var result = RemodelHarness.Ok<RemodelCloseResult>(_harness.Dispatch(RemodelCommands.Close, "{}"));

        Assert.True(result.Closed);
        Assert.Equal(_harness.CopyPath, Assert.Single(_harness.Seat.Closed));
        Assert.Equal(
            new[] { "10=False", "77=False", "329=False" },
            _harness.Seat.ToggleWrites);
    }

    [Fact]
    public void Close_WithDiscard_WhoseRoutineFailed_StillDeletesTheCopyAndSaysSo()
    {
        string plan = Path.Combine(_harness.RunDirectory, "plan.json");
        File.WriteAllText(plan, "{}");
        _harness.Copy.PathName = Path.Combine(_harness.Root, "work", "somebody-else.SLDPRT");

        BridgeResponse response = _harness.Dispatch(RemodelCommands.Close, "{\"discard_copy\":true}");

        Assert.Equal(RemodelErrorCodes.TargetMismatch, RemodelHarness.Refusal(response));
        Assert.Equal("true", Detail(response)["copy_deleted"]);
        Assert.False(File.Exists(_harness.CopyPath));
        Assert.True(File.Exists(plan));
    }

    [Fact]
    public void Close_TellsTheHostItEndedTheSession()
    {
        var told = new List<RemodelSessionEnd>();
        _harness.Services.RemodelSessionEnded = told.Add;

        RemodelHarness.Ok<RemodelCloseResult>(_harness.Dispatch(RemodelCommands.Close, "{}"));

        RemodelSessionEnd outcome = Assert.Single(told);
        Assert.Equal(RemodelSessionEnd.ReasonClose, outcome.Reason);
        Assert.True(outcome.Succeeded);
    }

    [Fact]
    public void Close_ThatFailed_TellsTheHostWhatWasLeft()
    {
        var told = new List<RemodelSessionEnd>();
        _harness.Services.RemodelSessionEnded = told.Add;
        _harness.Seat.CloseFailure = new System.Runtime.InteropServices.COMException("CloseDoc refused");

        _harness.Dispatch(RemodelCommands.Close, "{}");

        RemodelSessionEnd outcome = Assert.Single(told);
        Assert.False(outcome.Succeeded);
        Assert.False(outcome.CopyClosed);
    }

    [Fact]
    public void Close_ClearsTheRunRootWithTheSession()
    {
        _harness.Dispatcher.BindRemodelRun(_harness.RunDirectory);

        _harness.Dispatch(RemodelCommands.Close, "{}");

        Assert.Null(_harness.Services.RemodelRunRoot);
    }

    private static IReadOnlyDictionary<string, string> Detail(BridgeResponse response) =>
        Assert.IsType<RemodelErrorResult>(response.Result).Detail!;

    /// <summary>
    /// The session is over whatever the close answered: the next command has no scope, and a
    /// fresh open on the same bridge is not answered <c>run_in_progress</c>.
    /// </summary>
    private void AssertTheSessionIsOverAndTheNextOpenGoesThrough()
    {
        Assert.Equal(
            RemodelErrorCodes.TargetMismatch,
            RemodelHarness.Refusal(_harness.Dispatch(RemodelCommands.Snapshot, "{}")));

        if (File.Exists(_harness.CopyPath))
        {
            File.Delete(_harness.CopyPath);
        }

        _harness.Copy.PathName = _harness.CopyPath;
        _harness.Copy.SessionTag = null;
        _harness.Copy.UntagFailure = null;
        _harness.Open();
    }
}
