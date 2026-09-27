using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// 004 T167 (default taken 2026-09-26, the owner may revise; research R13.1; lane D's defaults of
/// 2026-09-27): the one end-of-session routine, <see cref="SwBridgeDispatcher.EndRemodelSession"/>,
/// over the fake seat and the fake copy - what a tool-service re-attach or an add-in unload runs
/// before the pipe closes, and what <c>remodel.close</c> runs too
/// (contracts/bridge-remodel.md, "Ending a session").
///
/// In order: <c>VerifyTarget</c>; when it passes, the tag off and the copy closed
/// <b>unsaved</b>, each write judged by the guard and recorded but not counted against the
/// circuit breaker; in a <c>finally</c>, all four settings put back, <c>CommandInProgress</c>
/// last; in an outer <c>finally</c>, the session and the run root cleared. It never saves and
/// never deletes, and it tells the host every ending of a session that existed.
///
/// The seat's originals are set to the opposite of what a run writes - the three toggles on,
/// <c>CommandInProgress</c> off - so a restore that wrote the run's values back would be seen.
/// </summary>
public sealed class RemodelTeardownTests : IDisposable
{
    private const string Reason = RemodelSessionEnd.ReasonToolServiceStopped;

    /// <summary>What a whole restore writes, in order: the originals, CommandInProgress last.</summary>
    private static readonly string[] WholeRestore =
    {
        "10=True", "77=True", "329=True", "CommandInProgress=False",
    };

    private readonly RemodelHarness _harness;
    private readonly List<RemodelSessionEnd> _told = new List<RemodelSessionEnd>();

    public RemodelTeardownTests()
    {
        _harness = new RemodelHarness(
            new FakeFeature("ref:boss", "Boss-Extrude1"),
            new FakeFeature("ref:fillet", "Fillet1"));

        foreach (int toggle in RemodelSystemToggles.SuppressedToggles)
        {
            _harness.Seat.SetUserPreferenceToggle(toggle, true);
        }

        _harness.Services.RemodelSessionEnded = _told.Add;
    }

    public void Dispose() => _harness.Dispose();

    // ---- no session --------------------------------------------------------------------

    [Fact]
    public void ATeardownWithNoSessionCallsNothingAndTellsNobody()
    {
        _harness.Seat.ToggleWrites.Clear();

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.False(outcome.HadSession);
        Assert.True(outcome.Succeeded);
        Assert.Equal(Reason, outcome.Reason);
        Assert.Equal(0, outcome.SettingsRestored);
        Assert.Empty(outcome.SettingsOutstanding);
        Assert.Null(outcome.RunDirectory);
        Assert.Null(outcome.CopyPath);

        // Not a SOLIDWORKS member, not a gate key, not a word to the host.
        Assert.Empty(_harness.Seat.ToggleWrites);
        Assert.Empty(_harness.Seat.Closed);
        Assert.Empty(_harness.Copy.Members);
        Assert.Empty(_harness.Observer.Members);
        Assert.Empty(_told);
    }

    [Fact]
    public void ATeardownWithNoSessionStillClearsABoundRunRoot()
    {
        _harness.Dispatcher.BindRemodelRun(_harness.RunDirectory);

        _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.Null(_harness.Services.RemodelRunRoot);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void ASessionEndsForANamedReason(string reason)
    {
        Assert.Throws<ArgumentException>(() => _harness.Dispatcher.EndRemodelSession(reason));
    }

    // ---- a session, cleanly ended --------------------------------------------------------

    [Fact]
    public void ATeardownVerifiesThenUntagsThenClosesTheCopyUnsavedAndRestoresAllFour()
    {
        _harness.Open();
        _harness.Seat.ToggleWrites.Clear();

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.True(outcome.HadSession);
        Assert.True(outcome.Succeeded);
        Assert.True(outcome.Verified);
        Assert.Null(outcome.FailedCheck);
        Assert.True(outcome.TagRemoved);
        Assert.True(outcome.CopyClosed);
        Assert.Equal(4, outcome.SettingsRestored);
        Assert.Empty(outcome.SettingsOutstanding);
        Assert.Empty(outcome.Failures);
        Assert.Equal(_harness.CopyPath, outcome.CopyPath);
        Assert.Equal(Path.GetFullPath(_harness.RunDirectory), outcome.RunDirectory);

        // The verification's four reads, then the untag, on the copy; then the close, on the seat.
        Assert.Equal(
            new[]
            {
                nameof(FakeRemodelDocument.GetPathName),
                nameof(FakeRemodelDocument.GetSessionTag),
                nameof(FakeRemodelDocument.GetDocumentIdentity),
                nameof(FakeRemodelDocument.GetOpenDocumentIdentity),
                nameof(FakeRemodelDocument.RemoveSessionTag),
            },
            _harness.Copy.Members);
        Assert.Equal(_harness.CopyPath, Assert.Single(_harness.Seat.Closed));
        Assert.Null(_harness.Copy.SessionTag);
        Assert.Equal(WholeRestore, _harness.Seat.ToggleWrites);
        Assert.False(_harness.Seat.CommandInProgress);
    }

    [Fact]
    public void ATeardownNeverSavesNeverDeletesAndLeavesTheRunFolderWhole()
    {
        _harness.Open();
        string plan = Path.Combine(_harness.RunDirectory, "plan.json");
        string changes = Path.Combine(_harness.RunDirectory, "changes.jsonl");
        File.WriteAllText(plan, "{\"state\":\"planned\"}");
        File.WriteAllText(changes, "{\"seq\":1}\n");
        byte[] copyBefore = File.ReadAllBytes(_harness.CopyPath);

        _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.DoesNotContain(nameof(FakeRemodelDocument.Save), _harness.Copy.Members);
        Assert.DoesNotContain("IModelDoc2.Save3", _harness.Observer.Members);
        Assert.True(File.Exists(_harness.CopyPath));
        Assert.Equal(copyBefore, File.ReadAllBytes(_harness.CopyPath));
        Assert.Equal("{\"state\":\"planned\"}", File.ReadAllText(plan));
        Assert.Equal("{\"seq\":1}\n", File.ReadAllText(changes));
    }

    /// <summary>
    /// A run in progress when the add-in unloads ends the same way: the change it made goes with
    /// the unsaved close, and nothing is saved on its behalf.
    /// </summary>
    [Fact]
    public void AMidRunTeardownClosesTheChangedCopyUnsaved()
    {
        _harness.Open();
        RemodelHarness.Ok<RemodelRenameResult>(_harness.Dispatch(
            RemodelCommands.Rename, "{\"persist_ref\":\"ref:fillet\",\"new_name\":\"Fillet-Edge1\"}"));

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.True(outcome.Succeeded);
        Assert.True(outcome.CopyClosed);
        Assert.DoesNotContain(nameof(FakeRemodelDocument.Save), _harness.Copy.Members);
    }

    [Fact]
    public void ASecondTeardownChangesNothingMore()
    {
        _harness.Open();
        _harness.Dispatcher.EndRemodelSession(Reason);
        _harness.Seat.ToggleWrites.Clear();
        _harness.Copy.Members.Clear();
        int closes = _harness.Seat.Closed.Count;
        int gated = _harness.Observer.Members.Count;

        RemodelSessionEnd second = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.False(second.HadSession);
        Assert.Empty(_harness.Seat.ToggleWrites);
        Assert.Empty(_harness.Copy.Members);
        Assert.Equal(closes, _harness.Seat.Closed.Count);
        Assert.Equal(gated, _harness.Observer.Members.Count);
    }

    [Fact]
    public void TheSessionAndTheRunRootAreClearedSoTheNextOpenGoesThrough()
    {
        _harness.Open();
        _harness.Dispatcher.BindRemodelRun(_harness.RunDirectory);

        _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.Null(_harness.Dispatcher.RemodelTargetPath);
        Assert.Null(_harness.Dispatcher.RemodelRunDirectory);
        Assert.Null(_harness.Services.RemodelRunRoot);
        Assert.Equal(
            RemodelErrorCodes.TargetMismatch,
            RemodelHarness.Refusal(_harness.Dispatch(RemodelCommands.Snapshot, "{}")));

        OpenAgain();
    }

    // ---- the verification fails -----------------------------------------------------------

    [Theory]
    [InlineData(RemodelTargetCheck.DocumentPath)]
    [InlineData(RemodelTargetCheck.SessionTag)]
    public void ATeardownWhoseVerificationFailsClosesNothingAndStillRestoresAllFour(
        RemodelTargetCheck check)
    {
        _harness.Open();
        Break(check);
        _harness.Seat.ToggleWrites.Clear();

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.False(outcome.Succeeded);
        Assert.False(outcome.Verified);
        Assert.Equal(check, outcome.FailedCheck);
        Assert.False(outcome.TagRemoved);
        Assert.False(outcome.CopyClosed);
        Assert.Equal(4, outcome.SettingsRestored);
        Assert.Contains("check " + (int)check, Assert.Single(outcome.Failures), StringComparison.Ordinal);

        Assert.Empty(_harness.Seat.Closed);
        Assert.DoesNotContain(nameof(FakeRemodelDocument.RemoveSessionTag), _harness.Copy.Members);
        Assert.Equal(WholeRestore, _harness.Seat.ToggleWrites);
        Assert.Null(_harness.Dispatcher.RemodelTargetPath);
    }

    [Fact]
    public void AVerificationThatCannotRunClosesNothingAndNamesNoCheck()
    {
        _harness.Open();
        _harness.Copy.PathNameFailure = new COMException("the RPC server is unavailable");

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.False(outcome.Verified);
        Assert.Null(outcome.FailedCheck);
        Assert.False(outcome.CopyClosed);
        Assert.Empty(_harness.Seat.Closed);
        Assert.Equal(4, outcome.SettingsRestored);
        Assert.Contains("the RPC server is unavailable", Assert.Single(outcome.Failures), StringComparison.Ordinal);
    }

    [Fact]
    public void AfterAFailedVerificationTheNextOpenGoesThrough()
    {
        _harness.Open();
        Break(RemodelTargetCheck.DocumentPath);

        _harness.Dispatcher.EndRemodelSession(Reason);

        OpenAgain();
    }

    // ---- a write fails --------------------------------------------------------------------

    [Fact]
    public void AnUntagThatThrowsStillClosesTheCopyAndRestoresAllFour()
    {
        _harness.Open();
        _harness.Copy.UntagFailure = new COMException("Delete2 refused");
        _harness.Seat.ToggleWrites.Clear();

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.False(outcome.Succeeded);
        Assert.True(outcome.Verified);
        Assert.False(outcome.TagRemoved);
        Assert.True(outcome.CopyClosed);
        Assert.Equal(4, outcome.SettingsRestored);
        Assert.Contains("Delete2 refused", Assert.Single(outcome.Failures), StringComparison.Ordinal);
        Assert.Equal(_harness.CopyPath, Assert.Single(_harness.Seat.Closed));
        Assert.Equal(WholeRestore, _harness.Seat.ToggleWrites);
        Assert.Null(_harness.Dispatcher.RemodelTargetPath);
    }

    [Fact]
    public void ACloseThatThrowsStillRestoresAllFourAndSaysTheCopyWasNotClosed()
    {
        _harness.Open();
        _harness.Seat.CloseFailure = new COMException("CloseDoc refused");
        _harness.Seat.ToggleWrites.Clear();

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.False(outcome.Succeeded);
        Assert.True(outcome.TagRemoved);
        Assert.False(outcome.CopyClosed);
        Assert.Equal(4, outcome.SettingsRestored);
        Assert.Contains("CloseDoc refused", Assert.Single(outcome.Failures), StringComparison.Ordinal);
        Assert.Equal(WholeRestore, _harness.Seat.ToggleWrites);
        Assert.Null(_harness.Dispatcher.RemodelTargetPath);
    }

    [Fact]
    public void ARestoreThatFailsPartWayPutsBackTheRestAndNamesWhatIsLeft()
    {
        _harness.Open();
        _harness.Seat.FailingWrites.Add("77=True");
        _harness.Seat.ToggleWrites.Clear();

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.False(outcome.Succeeded);
        Assert.True(outcome.CopyClosed);
        Assert.Equal(3, outcome.SettingsRestored);
        Assert.Equal(new[] { "swShowErrorsEveryRebuild" }, outcome.SettingsOutstanding);

        // Every one was attempted, CommandInProgress last, and the session is over anyway.
        Assert.Equal(WholeRestore, _harness.Seat.ToggleWrites);
        Assert.False(_harness.Seat.CommandInProgress);
        Assert.Null(_harness.Dispatcher.RemodelTargetPath);
        OpenAgain();
    }

    [Fact]
    public void ACommandInProgressThatWillNotGoBackIsNamed()
    {
        _harness.Open();
        _harness.Seat.FailingWrites.Add("CommandInProgress=False");

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.Equal(new[] { RemodelSystemToggles.CommandInProgressSetting }, outcome.SettingsOutstanding);
        Assert.True(_harness.Seat.CommandInProgress);
    }

    [Fact]
    public void EverythingFailingStillEndsTheSessionAndNamesEachFailureInOrder()
    {
        _harness.Open();
        _harness.Copy.UntagFailure = new COMException("untag");
        _harness.Seat.CloseFailure = new COMException("close");
        _harness.Seat.FailingWrites.Add("10=True");
        _harness.Seat.FailingWrites.Add("CommandInProgress=False");

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.Equal(3, outcome.Failures.Count);
        Assert.Contains("untag", outcome.Failures[0], StringComparison.Ordinal);
        Assert.Contains("close", outcome.Failures[1], StringComparison.Ordinal);
        Assert.Contains("settings", outcome.Failures[2], StringComparison.Ordinal);
        Assert.Equal(2, outcome.SettingsRestored);
        Assert.Equal(
            new[] { "swInputDimValOnCreate", RemodelSystemToggles.CommandInProgressSetting },
            outcome.SettingsOutstanding);
        Assert.Null(_harness.Dispatcher.RemodelTargetPath);
    }

    // ---- the gate ------------------------------------------------------------------------

    /// <summary>
    /// The run that most needs its clean-up is the one that killed the session, so the untag,
    /// the close and the restore are asserted by the guard and recorded, and made outside the
    /// breaker's count: an open circuit cannot stop them.
    /// </summary>
    [Fact]
    public void AnOpenCircuitDoesNotStopTheCleanUp()
    {
        _harness.Open();
        Trip(_harness.Gate.Breaker);
        _harness.Seat.ToggleWrites.Clear();

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.True(outcome.Succeeded);
        Assert.True(outcome.CopyClosed);
        Assert.Equal(WholeRestore, _harness.Seat.ToggleWrites);
    }

    [Fact]
    public void TheCleanUpsWritesAreJudgedAndRecordedAndNoneIsRefused()
    {
        _harness.Open();
        var observer = new SwReview.Extractor.Sw.RecordingGateObserver();
        _harness.Gate.Observer = observer;

        _harness.Dispatcher.EndRemodelSession(Reason);

        // Exactly the keys this job has on the allowlist, and nothing read through the gate: the
        // verification's reads are ungated, as they are before every write.
        Assert.Equal(
            new[]
            {
                "ICustomPropertyManager.Delete2",
                "ISldWorks.CloseDoc",
                RemodelSystemToggles.ToggleMember,
                RemodelSystemToggles.CommandInProgressMember,
            },
            observer.Members);
        Assert.Empty(observer.Refusals);
    }

    [Fact]
    public void AFailedCleanUpWriteIsNotCountedAgainstTheBreaker()
    {
        _harness.Open();
        _harness.Seat.CloseFailure = new COMException("CloseDoc refused");
        _harness.Copy.UntagFailure = new COMException("Delete2 refused");
        int before = _harness.Gate.Breaker.ConsecutiveFailures;

        _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.Equal(before, _harness.Gate.Breaker.ConsecutiveFailures);
        Assert.False(_harness.Gate.Breaker.IsOpen);
    }

    // ---- who is told ---------------------------------------------------------------------

    [Fact]
    public void TheHostIsToldOnceAfterTheSessionIsCleared()
    {
        _harness.Open();
        string? targetWhenTold = "not told";
        _harness.Services.RemodelSessionEnded = outcome =>
        {
            _told.Add(outcome);
            targetWhenTold = _harness.Dispatcher.RemodelTargetPath;
        };

        RemodelSessionEnd returned = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.Same(returned, Assert.Single(_told));
        Assert.Null(targetWhenTold);
    }

    [Fact]
    public void AHostWhoseCallbackThrowsDoesNotStopTheRoutineOrReachItsCaller()
    {
        _harness.Open();
        _harness.Services.RemodelSessionEnded = _ => throw new InvalidOperationException("the pane is gone");

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.True(outcome.Succeeded);
        Assert.Null(_harness.Dispatcher.RemodelTargetPath);
    }

    [Fact]
    public void ANullCallbackIsNoOnesBusiness()
    {
        _harness.Open();
        _harness.Services.RemodelSessionEnded = null;

        Assert.True(_harness.Dispatcher.EndRemodelSession(Reason).Succeeded);
    }

    // ---- the outcome's fields ------------------------------------------------------------

    [Fact]
    public void TheFieldsNameEveryFactAsAPlainTokenInOrder()
    {
        _harness.Open();
        _harness.Seat.FailingWrites.Add("329=True");
        Break(RemodelTargetCheck.SessionTag);

        RemodelSessionEnd outcome = _harness.Dispatcher.EndRemodelSession(Reason);

        Assert.Equal(
            new[]
            {
                new KeyValuePair<string, string>("reason", Reason),
                new KeyValuePair<string, string>("verified", "false"),
                new KeyValuePair<string, string>("failed_check", "2"),
                new KeyValuePair<string, string>("tag_removed", "false"),
                new KeyValuePair<string, string>("copy_closed", "false"),
                new KeyValuePair<string, string>("settings_restored", "3"),
                new KeyValuePair<string, string>("settings_outstanding", "swWarnSaveUpdateErrors"),
            },
            outcome.Fields());
    }

    [Fact]
    public void ACleanOutcomeCarriesNoFailedCheckAndAnEmptyOutstandingList()
    {
        _harness.Open();

        IReadOnlyList<KeyValuePair<string, string>> fields =
            _harness.Dispatcher.EndRemodelSession(Reason).Fields();

        Assert.DoesNotContain(fields, field => field.Key == "failed_check");
        Assert.Equal(string.Empty, fields.Single(field => field.Key == "settings_outstanding").Value);
        Assert.Equal("4", fields.Single(field => field.Key == "settings_restored").Value);
    }

    [Fact]
    public void TheFourSettingsAreTheThreeTogglesAndCommandInProgress()
    {
        Assert.Equal(RemodelSystemToggles.SettingCount, RemodelSystemToggles.SuppressedToggles.Count + 1);
        Assert.Equal(
            new[] { "swInputDimValOnCreate", "swShowErrorsEveryRebuild", "swWarnSaveUpdateErrors" },
            RemodelSystemToggles.SuppressedToggles.Select(RemodelSystemToggles.SettingName));
    }

    // ---- helpers -------------------------------------------------------------------------

    /// <summary>Makes <paramref name="check"/> fail on the copy, the way the engineer or SOLIDWORKS would.</summary>
    private void Break(RemodelTargetCheck check)
    {
        switch (check)
        {
            case RemodelTargetCheck.DocumentPath:
                _harness.Copy.PathName = Path.Combine(_harness.Root, "work", "somebody-else.SLDPRT");
                break;
            case RemodelTargetCheck.SessionTag:
                _harness.Copy.SessionTag = "20260101-000000-another-run";
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(check), check, "not a check this suite breaks");
        }
    }

    /// <summary>
    /// A fresh run on the same bridge: the copy <c>remodel.close {discard_copy}</c> would have
    /// deleted is deleted, the copy is put back as SOLIDWORKS would open it, and the open is not
    /// answered <c>run_in_progress</c> by a session that is already over.
    /// </summary>
    private void OpenAgain()
    {
        File.Delete(_harness.CopyPath);
        _harness.Copy.PathName = _harness.CopyPath;
        _harness.Copy.PathNameFailure = null;
        _harness.Copy.SessionTag = null;
        _harness.Seat.FailingWrites.Clear();
        _harness.Open();
        Assert.Equal(_harness.CopyPath, _harness.Dispatcher.RemodelTargetPath);
    }

    private static void Trip(CircuitBreaker breaker)
    {
        while (!breaker.IsOpen)
        {
            try
            {
                breaker.Execute<int>(() => throw new COMException("the session died"));
            }
            catch (COMException)
            {
            }
        }
    }
}
