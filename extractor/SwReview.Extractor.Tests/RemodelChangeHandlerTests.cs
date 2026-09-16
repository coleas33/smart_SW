using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T063. The five mutating commands: <c>rename</c>, <c>reorder</c>, <c>folder</c>,
/// <c>describe</c> and <c>equation</c>.
///
/// Every one of them is addressed by <b>persistent reference</b> and never by name and never
/// by index, because names change on a rename and indices change on every reorder. The
/// sequence each handler follows is therefore fixed:
/// <c>GetObjectByPersistReference3</c> with its ByRef error code read on <b>every</b> resolve,
/// then <c>IFeature.get_Name</c>, then the name-based API - in one breath, with nothing
/// between the read of the name and the call that uses it.
///
/// A reference that stops resolving after a reorder is a <b>failed change</b> and never a
/// retry (RK-13): a retry would either find nothing or, worse, find something else. A
/// <c>ReorderFeature</c> that answers a bare <c>false</c> is a <b>contract violation</b>, not a
/// condition: legality was decided from the dependency graph before the call, so <c>false</c>
/// means the model of the tree is wrong, and the run stops rather than searching for a legal
/// position.
///
/// <c>folder</c> supports <c>create</c> and <c>rename</c> only; <c>dissolve</c> answers
/// <c>not_in_v1</c>, because <c>IModelDoc2.EditDelete</c> is not on the stage-1 allowlist and a
/// part that would need one is refused by the scope gate before anything is copied.
/// </summary>
public class RemodelChangeHandlerTests : IDisposable
{
    private readonly RemodelHarness _harness;

    public RemodelChangeHandlerTests()
    {
        _harness = new RemodelHarness(
            new FakeFeature("ref:sketch", "Sketch1", "ProfileFeature"),
            new FakeFeature("ref:boss", "Boss-Extrude1"),
            new FakeFeature("ref:chamfer", "Chamfer1"),
            new FakeFeature("ref:fillet", "Fillet1"));
        _harness.Open();
    }

    public void Dispose() => _harness.Dispose();

    // ---- remodel.rename --------------------------------------------------------------

    [Fact]
    public void Rename_ResolvesTheRefReadsTheNameAndWritesTheNewOneInOneBreath()
    {
        var result = RemodelHarness.Ok<RemodelRenameResult>(_harness.Dispatch(
            RemodelCommands.Rename,
            "{\"persist_ref\":\"ref:fillet\",\"new_name\":\"Fillet-Outer\"}"));

        Assert.Equal("Fillet1", result.PreviousName);
        Assert.Equal("Fillet-Outer", result.NewName);
        Assert.Equal("Fillet-Outer", _harness.Copy.Features[3].Name);
        Assert.Equal(new[] { "ref:fillet" }, _harness.Copy.Resolved);

        AssertOneBreath(
            nameof(FakeRemodelDocument.ResolveByPersistReference),
            nameof(FakeRemodelDocument.GetFeatureName),
            nameof(FakeRemodelDocument.SetFeatureName));
    }

    [Fact]
    public void Rename_VerifiesTheTargetBeforeTheWrite()
    {
        _harness.Dispatch(
            RemodelCommands.Rename, "{\"persist_ref\":\"ref:fillet\",\"new_name\":\"Fillet-Outer\"}");

        List<string> members = _harness.Copy.Members;
        int write = members.IndexOf(nameof(FakeRemodelDocument.SetFeatureName));
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
    public void Rename_ARefThatNoLongerResolves_IsAFailedChangeAndNeverARetry()
    {
        _harness.Copy.ResolveErrors["ref:fillet"] = 4;

        Assert.Equal(
            RemodelErrorCodes.PersistRefUnresolved,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Rename,
                "{\"persist_ref\":\"ref:fillet\",\"new_name\":\"Fillet-Outer\"}")));

        // Once. A reference is never retried and never replaced by a search by name.
        Assert.Equal(new[] { "ref:fillet" }, _harness.Copy.Resolved);
        Assert.DoesNotContain(nameof(FakeRemodelDocument.SetFeatureName), _harness.Copy.Members);
    }

    // ---- remodel.reorder -------------------------------------------------------------

    [Fact]
    public void Reorder_ResolvesBothRefsAndCallsTheNameBasedApi()
    {
        var result = RemodelHarness.Ok<RemodelReorderResult>(_harness.Dispatch(
            RemodelCommands.Reorder,
            "{\"feature_persist_ref\":\"ref:fillet\",\"anchor_persist_ref\":\"ref:boss\","
            + "\"location\":\"before\"}"));

        Assert.Equal(new[] { "ref:fillet", "ref:boss" }, _harness.Copy.Resolved);
        Assert.Equal(
            new[] { "Sketch1", "Fillet1", "Boss-Extrude1", "Chamfer1" },
            _harness.Copy.Features.Select(feature => feature.Name));

        // Everything derive_undo needs, read rather than assumed.
        Assert.Equal("ref:chamfer", result.PreviousAnchorPersistRef);
        Assert.Equal("after", result.PreviousLocation);
        Assert.Equal(3, result.PreviousIndex);
        Assert.Equal(1, result.NewIndex);

        // Reorder is the one command where a stale name silently moves the wrong feature
        // (T012), so the tree walk that derives the inverse is taken before the refs are
        // resolved and the whole of what stands between the two name reads and the name-based
        // call is VerifyTarget, which reads no name at all.
        List<string> members = _harness.Copy.Members;
        int first = members.IndexOf(nameof(FakeRemodelDocument.ResolveByPersistReference));
        int call = members.IndexOf(nameof(FakeRemodelDocument.ReorderFeature));
        Assert.True(first >= 0 && call > first, "the resolve or the reorder never happened");
        Assert.Equal(
            new[]
            {
                nameof(FakeRemodelDocument.ResolveByPersistReference),
                nameof(FakeRemodelDocument.GetFeatureName),
                nameof(FakeRemodelDocument.ResolveByPersistReference),
                nameof(FakeRemodelDocument.GetFeatureName),
                nameof(FakeRemodelDocument.GetPathName),
                nameof(FakeRemodelDocument.GetSessionTag),
                nameof(FakeRemodelDocument.GetDocumentIdentity),
                nameof(FakeRemodelDocument.GetOpenDocumentIdentity),
                nameof(FakeRemodelDocument.ReorderFeature),
            },
            members.GetRange(first, call - first + 1));

        // And the walk that reads the previous position is on the other side of the resolve,
        // so no GetPersistReference3 sits between a name read and the move.
        Assert.True(
            members.IndexOf(nameof(FakeRemodelDocument.GetFeaturesInOrder)) < first,
            "the tree was walked after the refs were resolved");
    }

    [Fact]
    public void Reorder_MapsTheClosedLocationSetToTheVerifiedEnumValues()
    {
        // swMoveLocation_e.Before = 2, After = 3 (VERIFIED values), asserted as integers.
        _harness.Dispatch(
            RemodelCommands.Reorder,
            "{\"feature_persist_ref\":\"ref:fillet\",\"anchor_persist_ref\":\"ref:sketch\","
            + "\"location\":\"after\"}");

        Assert.Equal(
            new[] { "Sketch1", "Fillet1", "Boss-Extrude1", "Chamfer1" },
            _harness.Copy.Features.Select(feature => feature.Name));
    }

    [Fact]
    public void Reorder_ABareFalse_IsAContractViolationThatStopsTheRun()
    {
        // Legality was decided from the dependency graph before the call, so false means the
        // model of the tree is wrong. Never retry, never search for a legal position.
        _harness.Copy.ReorderAnswer = false;

        Assert.Equal(
            RemodelErrorCodes.ReorderRefused,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Reorder,
                "{\"feature_persist_ref\":\"ref:fillet\",\"anchor_persist_ref\":\"ref:boss\","
                + "\"location\":\"before\"}")));

        Assert.Single(
            _harness.Copy.Members, member => member == nameof(FakeRemodelDocument.ReorderFeature));
    }

    [Fact]
    public void Reorder_AnUnresolvableAnchor_FailsBeforeAnythingMoves()
    {
        _harness.Copy.ResolveErrors["ref:boss"] = 7;

        Assert.Equal(
            RemodelErrorCodes.PersistRefUnresolved,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Reorder,
                "{\"feature_persist_ref\":\"ref:fillet\",\"anchor_persist_ref\":\"ref:boss\","
                + "\"location\":\"before\"}")));

        Assert.DoesNotContain(nameof(FakeRemodelDocument.ReorderFeature), _harness.Copy.Members);
    }

    [Fact]
    public void Reorder_AnUnknownLocation_IsRefusedBeforeAnyResolve()
    {
        Assert.Equal(
            RemodelErrorCodes.BadRequest,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Reorder,
                "{\"feature_persist_ref\":\"ref:fillet\",\"anchor_persist_ref\":\"ref:boss\","
                + "\"location\":\"somewhere\"}")));

        Assert.Empty(_harness.Copy.Resolved);
    }

    // ---- remodel.folder --------------------------------------------------------------

    [Fact]
    public void Folder_Create_WrapsTheContiguousRunNamesItAndReportsVerifiedMembership()
    {
        var result = RemodelHarness.Ok<RemodelFolderResult>(_harness.Dispatch(
            RemodelCommands.Folder,
            "{\"op\":\"create\",\"name\":\"3-Core\","
            + "\"member_persist_refs\":[\"ref:boss\",\"ref:chamfer\"]}"));

        Assert.Equal("3-Core", result.Name);
        Assert.NotNull(result.FolderPersistRef);

        // The MEMBERSHIP IS VERIFIED with FeatureFolderLocation rather than assumed from the
        // selection, and it is the verified membership the result carries: a caller that asked
        // for two members and is answered with one has a failed change to record.
        Assert.Equal(new[] { "ref:boss", "ref:chamfer" }, result.MemberPersistRefs);

        List<string> members = _harness.Copy.Members;
        Assert.True(
            members.IndexOf(nameof(FakeRemodelDocument.ClearSelection))
            < members.IndexOf(nameof(FakeRemodelDocument.SelectFeature)),
            "the selection is cleared before the run is selected");
        Assert.True(
            members.IndexOf(nameof(FakeRemodelDocument.SelectFeature))
            < members.IndexOf(nameof(FakeRemodelDocument.InsertFeatureTreeFolder)),
            "the folder wraps the selection that was just made");
        Assert.True(
            members.IndexOf(nameof(FakeRemodelDocument.InsertFeatureTreeFolder))
            < members.IndexOf(nameof(FakeRemodelDocument.SetFeatureName)),
            "the folder is named after it exists");
        Assert.Contains(nameof(FakeRemodelDocument.GetFeatureFolder), members);
    }

    [Fact]
    public void Folder_Create_NonContiguousMembers_IsRefusedRatherThanAttempted()
    {
        Assert.Equal(
            RemodelErrorCodes.FolderMembersNotContiguous,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Folder,
                "{\"op\":\"create\",\"name\":\"3-Core\","
                + "\"member_persist_refs\":[\"ref:sketch\",\"ref:chamfer\"]}")));

        Assert.DoesNotContain(nameof(FakeRemodelDocument.SelectFeature), _harness.Copy.Members);
        Assert.DoesNotContain(
            nameof(FakeRemodelDocument.InsertFeatureTreeFolder), _harness.Copy.Members);
    }

    [Fact]
    public void Folder_Create_WithNoMembers_IsRefused()
    {
        Assert.Equal(
            RemodelErrorCodes.FolderMembersNotContiguous,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Folder,
                "{\"op\":\"create\",\"name\":\"3-Core\",\"member_persist_refs\":[]}")));
    }

    [Fact]
    public void Folder_Rename_SetsTheNameOnTheResolvedFolder()
    {
        var created = RemodelHarness.Ok<RemodelFolderResult>(_harness.Dispatch(
            RemodelCommands.Folder,
            "{\"op\":\"create\",\"name\":\"3-Core\","
            + "\"member_persist_refs\":[\"ref:boss\",\"ref:chamfer\"]}"));

        var renamed = RemodelHarness.Ok<RemodelFolderResult>(_harness.Dispatch(
            RemodelCommands.Folder,
            "{\"op\":\"rename\",\"name\":\"4-Detail\",\"folder_persist_ref\":\""
            + created.FolderPersistRef + "\"}"));

        Assert.Equal("4-Detail", renamed.Name);
        Assert.Equal(created.FolderPersistRef, renamed.FolderPersistRef);
        Assert.Contains(_harness.Copy.Features, feature => feature.Name == "4-Detail");
    }

    [Fact]
    public void Folder_Dissolve_IsNotInV1AndNothingIsTouched()
    {
        // Reserved for stage 2, so the value stays in the protocol and stage 2 adds a handler
        // branch and an allowlist entry rather than a new command.
        Assert.Equal(
            RemodelErrorCodes.NotInV1,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Folder,
                "{\"op\":\"dissolve\",\"folder_persist_ref\":\"ref:boss\"}")));

        Assert.Empty(_harness.Copy.Resolved);
        Assert.Empty(_harness.Copy.Members);
    }

    // ---- remodel.describe ------------------------------------------------------------

    [Fact]
    public void Describe_ReadsThePreviousTextForTheInverseThenWrites()
    {
        _harness.Copy.Features[1].Description = "the main boss";

        var result = RemodelHarness.Ok<RemodelDescribeResult>(_harness.Dispatch(
            RemodelCommands.Describe,
            "{\"persist_ref\":\"ref:boss\",\"text\":\"3-Core: the main boss\"}"));

        Assert.Equal("the main boss", result.PreviousText);
        Assert.Equal("3-Core: the main boss", _harness.Copy.Features[1].Description);

        List<string> members = _harness.Copy.Members;
        Assert.True(
            members.IndexOf(nameof(FakeRemodelDocument.GetFeatureDescription))
            < members.IndexOf(nameof(FakeRemodelDocument.SetFeatureDescription)),
            "the inverse is read before the change is made");
    }

    [Fact]
    public void Describe_AnAbsentDescription_IsAnEmptyStringAndNotNull()
    {
        var result = RemodelHarness.Ok<RemodelDescribeResult>(_harness.Dispatch(
            RemodelCommands.Describe, "{\"persist_ref\":\"ref:boss\",\"text\":\"3-Core\"}"));

        Assert.Equal(string.Empty, result.PreviousText);
    }

    [Fact]
    public void Describe_AnUnreadableDescription_IsRefusedBeforeTheWrite()
    {
        // An inverse that writes "" over something unreadable is a silent edit, and the
        // constitution's re-modeler exception requires an inverse for every applied change.
        // The planner refuses such a feature up front, so a request for one is a caller bug.
        _harness.Copy.Features[1].Description = null;

        Assert.Equal(
            RemodelErrorCodes.BadRequest,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Describe, "{\"persist_ref\":\"ref:boss\",\"text\":\"3-Core\"}")));

        Assert.DoesNotContain(
            nameof(FakeRemodelDocument.SetFeatureDescription), _harness.Copy.Members);
    }

    // ---- remodel.equation ------------------------------------------------------------

    [Fact]
    public void Equation_Add_GoesThroughTheVerifiedHelper()
    {
        var result = RemodelHarness.Ok<RemodelEquationResult>(_harness.Dispatch(
            RemodelCommands.Equation,
            "{\"op\":\"add\",\"text\":\"\\\"w\\\" = 120\",\"which_configs\":2}"));

        Assert.Equal(RemodelEquationHelperPaths.Add3, result.HelperPath);
        Assert.Equal(0, result.CountBefore);
        Assert.Equal(1, result.CountAfter);
        Assert.Equal("\"w\" = 120", result.RoundTripText);
        Assert.Equal(new[] { "\"w\" = 120" }, _harness.Copy.EquationManager.Equations);
    }

    [Fact]
    public void Equation_Set_EditsInPlaceAndIsTheFr029Repair()
    {
        _harness.Copy.EquationManager.Equations.Add("\"w\" = 100");

        var result = RemodelHarness.Ok<RemodelEquationResult>(_harness.Dispatch(
            RemodelCommands.Equation,
            "{\"op\":\"set\",\"index\":0,\"text\":\"\\\"w\\\" = 120\",\"which_configs\":2}"));

        Assert.Equal(RemodelEquationHelperPaths.SetEquation, result.HelperPath);
        Assert.Equal("\"w\" = 100", result.PreviousText);
        Assert.Equal(1, result.CountBefore);
        Assert.Equal(1, result.CountAfter);
        Assert.DoesNotContain(
            nameof(FakeEquationManager.Delete), _harness.Copy.EquationManager.Members);
    }

    [Fact]
    public void Equation_Delete_IsTheInverseOfAnAddAndRemovesTheRow()
    {
        _harness.Copy.EquationManager.Equations.Add("\"w\" = 120");

        var result = RemodelHarness.Ok<RemodelEquationResult>(_harness.Dispatch(
            RemodelCommands.Equation, "{\"op\":\"delete\",\"index\":0}"));

        Assert.Equal(RemodelEquationHelperPaths.Delete, result.HelperPath);
        Assert.Equal("\"w\" = 120", result.PreviousText);
        Assert.Equal(1, result.CountBefore);
        Assert.Equal(0, result.CountAfter);
        Assert.Empty(_harness.Copy.EquationManager.Equations);
    }

    [Fact]
    public void Equation_AddThatCannotBeProvenToHaveLanded_IsEquationUnverified()
    {
        _harness.Copy.EquationManager.Add3Adds = false;
        _harness.Copy.EquationManager.Add2Adds = false;

        Assert.Equal(
            RemodelErrorCodes.EquationUnverified,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Equation,
                "{\"op\":\"add\",\"text\":\"\\\"w\\\" = 120\",\"which_configs\":2}")));
    }

    [Fact]
    public void Equation_SetAndDelete_NeedAnIndex()
    {
        Assert.Equal(
            RemodelErrorCodes.BadRequest,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Equation,
                "{\"op\":\"set\",\"text\":\"\\\"w\\\" = 120\",\"which_configs\":2}")));

        Assert.Equal(
            RemodelErrorCodes.BadRequest,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Equation, "{\"op\":\"delete\"}")));
    }

    [Fact]
    public void Equation_AddWithoutText_IsRefused()
    {
        Assert.Equal(
            RemodelErrorCodes.BadRequest,
            RemodelHarness.Refusal(_harness.Dispatch(
                RemodelCommands.Equation, "{\"op\":\"add\",\"which_configs\":2}")));
    }

    // ---- the family ------------------------------------------------------------------

    [Fact]
    public void EveryMutatingCommand_IgnoresAParameterThatNamesADocument()
    {
        // The target is unreachable, not validated: a member the command table does not
        // declare is simply never read, so there is nothing to validate and nothing to get
        // wrong.
        var result = RemodelHarness.Ok<RemodelRenameResult>(_harness.Dispatch(
            RemodelCommands.Rename,
            "{\"persist_ref\":\"ref:fillet\",\"new_name\":\"Fillet-Outer\","
            + "\"document\":\"C:\\\\work\\\\somebody-elses.SLDPRT\"}"));

        Assert.Equal("Fillet-Outer", result.NewName);
        Assert.Equal("Fillet-Outer", _harness.Copy.Features[3].Name);
    }

    /// <summary>
    /// The resolve, the name read and the name-based call, with nothing between them: a name
    /// read at any other moment is a name that may no longer address this feature.
    /// </summary>
    private void AssertOneBreath(string resolve, string readName, string call)
    {
        List<string> members = _harness.Copy.Members;
        int at = members.IndexOf(resolve);
        Assert.True(at >= 0, resolve + " was never called");
        Assert.Equal(readName, members[at + 1]);

        int used = members.IndexOf(call);
        Assert.True(used > at + 1, call + " was not called after the name was read");
        Assert.DoesNotContain(resolve, members.GetRange(at + 1, used - at - 1));
        Assert.DoesNotContain(readName, members.GetRange(at + 2, used - at - 2));
    }
}
