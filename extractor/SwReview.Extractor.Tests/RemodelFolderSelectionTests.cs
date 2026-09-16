using System;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T046. <c>AssertFolderSelection</c> reads one selection exactly as contracts/guard-allowlist.md
/// defines it: <c>ISelectionMgr.GetSelectedObjectCount2(-1) == 1</c> (VERIFIED) <b>and</b>
/// <c>((IFeature)GetSelectedObject6(1, -1)).GetTypeName2() == "FtrFolder"</c> (VERIFIED).
///
/// In v1 it has exactly two consumers, <b>neither of which is a write</b>:
///   1. the planner's <c>rms_named_folder_wrong_members</c> refusal, which is written against
///      this same reading of "one selected object and it is a folder"; and
///   2. the precondition any future dissolve must pass, so stage 2 inherits a tested
///      assertion rather than writing one under time pressure beside a delete.
/// It is not a precondition to folder creation: creation selects a contiguous run of N content
/// features, which this predicate refuses by construction, so calling it before the
/// <c>set_Name</c> that follows <c>InsertFeatureTreeFolder2(Containing = 2)</c> would fail
/// every folder creation. The companion assertion below pins that <c>IModelDoc2.EditDelete</c>
/// is absent from the stage-1 allowlist, so no v1 path can need this helper before a delete.
///
/// The assertion exists once, as a named helper, and is never inlined at a call site: one
/// wrong selection under a delete removes real features.
/// </summary>
public class RemodelFolderSelectionTests
{
    /// <summary>
    /// The two interop reads, and nothing else. The COM-backed implementation arrives with
    /// stage 2's call site; in v1 the helper's only job is to be tested and to be the reading
    /// everything else is written against.
    /// </summary>
    private sealed class FakeSelection : IFolderSelection
    {
        public FakeSelection(int count, string? typeName)
        {
            Count = count;
            TypeName = typeName;
        }

        public int Count { get; }

        public string? TypeName { get; }

        public int GetSelectedObjectCount() => Count;

        public string? GetSelectedFeatureTypeName() => TypeName;
    }

    [Fact]
    public void AssertFolderSelection_OneSelectedFolder_Passes()
    {
        RemodelScope.AssertFolderSelection(new FakeSelection(1, "FtrFolder"));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(2)]
    [InlineData(7)]
    [InlineData(-1)]
    public void AssertFolderSelection_WrongSelectedCount_ThrowsNamingTheCondition(int count)
    {
        InvalidOperationException error = Assert.Throws<InvalidOperationException>(
            () => RemodelScope.AssertFolderSelection(new FakeSelection(count, "FtrFolder")));

        Assert.Contains("GetSelectedObjectCount2(-1)", error.Message, StringComparison.Ordinal);
        Assert.Contains(count.ToString(), error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void AssertFolderSelection_NullSelection_ThrowsNamingTheCondition()
    {
        InvalidOperationException error = Assert.Throws<InvalidOperationException>(
            () => RemodelScope.AssertFolderSelection(new FakeSelection(1, null)));

        Assert.Contains("GetSelectedObject6(1, -1)", error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("ProfileFeature")]
    [InlineData("Fillet")]
    [InlineData("Extrusion")]
    [InlineData("ftrfolder")]
    [InlineData("")]
    public void AssertFolderSelection_SelectedObjectIsNotAFolder_ThrowsNamingTheCondition(string typeName)
    {
        InvalidOperationException error = Assert.Throws<InvalidOperationException>(
            () => RemodelScope.AssertFolderSelection(new FakeSelection(1, typeName)));

        Assert.Contains("FtrFolder", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void AssertFolderSelection_NoSelectionReader_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => RemodelScope.AssertFolderSelection(null!));
    }

    /// <summary>
    /// The companion assertion T046 asks for. v1 refuses a mis-membered RMS-named folder
    /// instead of dissolving it, so the one call that deletes real features on a mis-selection
    /// is not on the stage-1 allowlist and no v1 path can reach a delete at all.
    /// </summary>
    [Fact]
    public void EditDelete_IsAbsentFromTheStage1Allowlist_SoThisHelperHasNoWriteCallSite()
    {
        Assert.DoesNotContain("IModelDoc2.EditDelete", RemodelGuard.AllowedKeys);
        Assert.Throws<MutatingCallError>(() => new RemodelGuard().Assert("IModelDoc2.EditDelete"));
    }
}
