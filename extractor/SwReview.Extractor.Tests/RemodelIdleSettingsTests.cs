using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>T180: an open copy can wait without owning the engineer's application settings.</summary>
public sealed class RemodelIdleSettingsTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void OpenRestoresEverySettingBeforePublishingTheHeldSession(bool originalCommand)
    {
        using (var world = World())
        {
            SetOriginals(world, originalCommand);
            byte[] source = File.ReadAllBytes(world.SourcePath);
            world.Open();
            AssertOriginals(world, originalCommand);
            Assert.Equal(source, File.ReadAllBytes(world.SourcePath));
            Assert.Contains(world.CopyPath, world.Seat.OpenDocuments);
            Assert.Equal(RemodelHarness.RunId, world.Copy.SessionTag);
            Assert.Equal(BridgeStatus.Ok, world.Dispatch(RemodelCommands.Snapshot, "{}").Status);
        }
    }

    [Theory]
    [InlineData("rename", "IFeature.set_Name")]
    [InlineData("reorder", "IModelDocExtension.ReorderFeature")]
    [InlineData("folder", "IFeatureManager.InsertFeatureTreeFolder2")]
    [InlineData("describe", "IFeature.set_Description")]
    [InlineData("equation", "IEquationMgr.Add3")]
    [InlineData("rebuild", "IModelDoc2.ForceRebuild3")]
    [InlineData("save", "IModelDoc2.Save3")]
    public void EachOperationSuppressesOnlyItsOwnSequenceAndRestoresTheCurrentIdleValues(
        string operation, string member)
    {
        using (var world = World())
        {
            SetOriginals(world, false);
            world.Open();
            world.GeometryGate();
            // These are the engineer's values now, rather than the values from Plan.
            world.Seat.SetUserPreferenceToggle(RemodelSystemToggles.InputDimValOnCreate, false);
            world.Seat.SetUserPreferenceToggle(RemodelSystemToggles.ShowErrorsEveryRebuild, true);
            world.Seat.SetUserPreferenceToggle(RemodelSystemToggles.WarnSaveUpdateErrors, true);
            world.Seat.ToggleWrites.Clear();
            int observed = 0;
            world.Gate.Observer = new Watch(key =>
            {
                if (key != member) return;
                observed++;
                AssertSuppressed(world);
            });

            byte[] source = File.ReadAllBytes(world.SourcePath);
            Assert.Equal(BridgeStatus.Ok, world.Dispatch("remodel." + operation, Parameters(operation)).Status);
            Assert.True(observed > 0, "the actual operation did not reach its guarded member");
            Assert.False(world.Seat.GetUserPreferenceToggle(RemodelSystemToggles.InputDimValOnCreate));
            Assert.True(world.Seat.GetUserPreferenceToggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
            Assert.True(world.Seat.GetUserPreferenceToggle(RemodelSystemToggles.WarnSaveUpdateErrors));
            Assert.False(world.Seat.CommandInProgress);
            Assert.Contains("CommandInProgress=True", world.Seat.ToggleWrites);
            Assert.Equal("CommandInProgress=False", world.Seat.ToggleWrites.Last());
            Assert.Equal(source, File.ReadAllBytes(world.SourcePath));
        }
    }

    [Fact]
    public void AnOperationThatThrowsStillRestoresAllFourSettings()
    {
        using (var world = World())
        {
            SetOriginals(world, false);
            world.Open();
            world.Gate.Observer = new Watch(key =>
            {
                if (key != "IFeature.set_Name") return;
                AssertSuppressed(world);
                throw new InvalidOperationException("FICT operation refused");
            });
            Assert.Equal(BridgeStatus.Error, world.Dispatch(RemodelCommands.Rename, Parameters("rename")).Status);
            AssertOriginals(world, false);
            Assert.Equal("Fillet1", world.Copy.Features[3].Name);
        }
    }

    [Fact]
    public void ATargetThatNoLongerVerifiesChangesNoApplicationSettingOrFeature()
    {
        using (var world = World())
        {
            SetOriginals(world, false);
            world.Open();
            world.Seat.ToggleWrites.Clear();
            world.Copy.SessionTag = "FICT-another-run";
            Assert.Equal(BridgeStatus.Error, world.Dispatch(RemodelCommands.Rename, Parameters("rename")).Status);
            Assert.Empty(world.Seat.ToggleWrites);
            Assert.Equal("Fillet1", world.Copy.Features[3].Name);
        }
    }

    [Fact]
    public void AFailedRestoreIsRetainedForCloseAndNeverOverwrittenByANewCommand()
    {
        using (var world = World())
        {
            SetOriginals(world, false);
            world.Open();
            world.Seat.FailingWrites.Add("77=True");
            Assert.Equal(BridgeStatus.Error, world.Dispatch(RemodelCommands.Rename, Parameters("rename")).Status);
            int featureWrites = world.Copy.Members.Count(key => key == nameof(FakeRemodelDocument.SetFeatureName));
            Assert.Equal(BridgeStatus.Error, world.Dispatch(RemodelCommands.Describe, Parameters("describe")).Status);
            Assert.Equal(featureWrites, world.Copy.Members.Count(key => key == nameof(FakeRemodelDocument.SetFeatureName)));
            Assert.DoesNotContain(nameof(FakeRemodelDocument.SetFeatureDescription), world.Copy.Members);
            world.Seat.FailingWrites.Clear();
            Assert.Equal(BridgeStatus.Ok, world.Dispatch(RemodelCommands.Close, "{}").Status);
            AssertOriginals(world, false);
            Assert.Empty(world.Seat.OpenDocuments);
        }
    }

    [Fact]
    public void FailedSuppressionReportsItsRetainedSettingsBeforeAnyCopyExists()
    {
        using (var world = World())
        {
            SetOriginals(world, false);
            byte[] source = File.ReadAllBytes(world.SourcePath);
            var endings = new System.Collections.Generic.List<RemodelSessionEnd>();
            world.Services.RemodelSessionEnded = endings.Add;
            world.Seat.FailingWrites.Add("77=False");
            world.Seat.FailingWrites.Add("77=True");

            Assert.ThrowsAny<Exception>(world.Open);

            var ended = Assert.Single(endings);
            Assert.Equal(RemodelSessionEnd.ReasonOpenFailed, ended.Reason);
            Assert.Equal(new[] { "swShowErrorsEveryRebuild" }, ended.SettingsOutstanding);
            Assert.True(ended.CopyClosed);
            Assert.False(File.Exists(world.CopyPath));
            Assert.Empty(world.Seat.Closed);
            Assert.Null(world.Dispatcher.RemodelTargetPath);
            Assert.Equal(source, File.ReadAllBytes(world.SourcePath));
            Assert.True(world.Seat.GetUserPreferenceToggle(RemodelSystemToggles.InputDimValOnCreate));
            Assert.False(world.Seat.CommandInProgress);
        }
    }

    [Fact]
    public void ARefusedGeometryVerdictWritesNoApplicationSettingOrSave()
    {
        using (var world = World())
        {
            world.Open();
            world.Seat.ToggleWrites.Clear();

            Assert.Equal(RemodelErrorCodes.GateNotPassed,
                RemodelHarness.Refusal(world.Dispatch(RemodelCommands.Save, RemodelHarness.SaveParams("fail"))));

            Assert.Empty(world.Seat.ToggleWrites);
            Assert.DoesNotContain("IModelDoc2.Save3", world.Observer.Members);
        }
    }

    private static RemodelHarness World() => new RemodelHarness(
        new FakeFeature("ref:sketch", "Sketch1", "ProfileFeature"),
        new FakeFeature("ref:boss", "Boss-Extrude1"),
        new FakeFeature("ref:chamfer", "Chamfer1"),
        new FakeFeature("ref:fillet", "Fillet1"));

    private static void SetOriginals(RemodelHarness world, bool command)
    {
        world.Seat.SetUserPreferenceToggle(RemodelSystemToggles.InputDimValOnCreate, true);
        world.Seat.SetUserPreferenceToggle(RemodelSystemToggles.ShowErrorsEveryRebuild, true);
        world.Seat.SetUserPreferenceToggle(RemodelSystemToggles.WarnSaveUpdateErrors, false);
        world.Seat.CommandInProgress = command;
    }

    private static void AssertOriginals(RemodelHarness world, bool command)
    {
        Assert.True(world.Seat.GetUserPreferenceToggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.True(world.Seat.GetUserPreferenceToggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.False(world.Seat.GetUserPreferenceToggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.Equal(command, world.Seat.CommandInProgress);
    }

    private static void AssertSuppressed(RemodelHarness world)
    {
        Assert.All(RemodelSystemToggles.SuppressedToggles, key => Assert.False(world.Seat.GetUserPreferenceToggle(key)));
        Assert.True(world.Seat.CommandInProgress);
    }

    private static string Parameters(string operation)
    {
        switch (operation)
        {
            case "rename": return "{\"persist_ref\":\"ref:fillet\",\"new_name\":\"Fillet-Outer\"}";
            case "describe": return "{\"persist_ref\":\"ref:fillet\",\"text\":\"FICT description\"}";
            case "reorder": return "{\"feature_persist_ref\":\"ref:fillet\",\"anchor_persist_ref\":\"ref:boss\",\"location\":\"after\"}";
            case "folder": return "{\"op\":\"create\",\"name\":\"3-Core\",\"member_persist_refs\":[\"ref:boss\",\"ref:chamfer\"]}";
            case "equation": return "{\"op\":\"add\",\"text\":\"\\\"w\\\" = 120\",\"which_configs\":2}";
            case "save": return RemodelHarness.SaveParams("pass");
            default: return "{}";
        }
    }

    private sealed class Watch : ISwGateObserver
    {
        private readonly Action<string> _before;
        public Watch(Action<string> before) => _before = before;
        public void Gated(string member) => _before(member);
        public void Refused(MutatingCallError refusal) { }
    }
}
