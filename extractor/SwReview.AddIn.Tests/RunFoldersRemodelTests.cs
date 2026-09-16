using System;
using System.IO;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T051. The re-modeler's run folder, created by the same helper the review, the terminal and
/// the Model check use, so the run-folder naming convention stays in one place
/// (contracts/run-artifacts.md).
///
/// `&lt;run_root&gt;/&lt;yyyyMMdd-HHmmss&gt;-&lt;doc&gt;-remodel`. The suffix sorts beside feature
/// 003's `-check` and feature 001's review folders in the one listing the engineer reads in
/// Explorer, and makes the folder obviously disposable. What goes <b>inside</b> it - `copy/`
/// and the `-RMS.SLDPRT` name - is <c>RemodelCopy</c>'s, so neither convention is written
/// twice.
/// </summary>
public sealed class RunFoldersRemodelTests : IDisposable
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 16, 14, 22, 1);

    private readonly string _root;

    public RunFoldersRemodelTests()
    {
        _root = Path.Combine(
            Path.GetTempPath(), "SwReview.RunFoldersRemodel.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    private string RunRoot => Path.Combine(_root, "runs");

    [Fact]
    public void ARemodelFolderIsTheTimestampTheDocumentAndTheRemodelSuffixAndItExists()
    {
        string created = RunFolders.CreateForRemodel(RunRoot, @"C:\parts\bracket.SLDPRT", Stamp);

        Assert.Equal(Path.Combine(RunRoot, "20260916-142201-bracket-remodel"), created);
        Assert.True(Directory.Exists(created), $"the helper did not create {created}");
    }

    /// <summary>
    /// The same cleaning, truncation and collision rules as every other run folder: two runs of
    /// the same document inside one second is a double-click, not an error, and the second must
    /// not be written into the first one's folder.
    /// </summary>
    [Fact]
    public void ASecondRemodelOfTheSameDocumentInTheSameSecondGetsItsOwnFolder()
    {
        string first = RunFolders.CreateForRemodel(RunRoot, @"C:\parts\bracket.SLDPRT", Stamp);
        string second = RunFolders.CreateForRemodel(RunRoot, @"C:\parts\bracket.SLDPRT", Stamp);

        Assert.NotEqual(first, second);
        Assert.Equal(Path.Combine(RunRoot, "20260916-142201-bracket-remodel-2"), second);
        Assert.True(Directory.Exists(second));
    }

    /// <summary>
    /// The suffix is part of the name, not a separate folder, and it is spelled in exactly one
    /// place: the run id in `plan.json` and the `SwReviewRemodelRun` tag are this folder's name.
    /// </summary>
    [Fact]
    public void TheSuffixIsTheOneTheContractNames()
    {
        Assert.Equal("-remodel", RunFolders.RemodelSuffix);
    }

    [Fact]
    public void ADocumentPathThatCannotBeAFolderNameIsCleanedTheSameWayEveryOtherRunFolderIs()
    {
        string created = RunFolders.CreateForRemodel(RunRoot, @"C:\parts\a:b*c.SLDPRT", Stamp);

        Assert.Equal(Path.Combine(RunRoot, "20260916-142201-a-b-c-remodel"), created);
    }

    [Fact]
    public void ABlankRunRootIsRefusedRatherThanResolvedAgainstTheWorkingDirectory()
    {
        Assert.Throws<ArgumentException>(() =>
            RunFolders.CreateForRemodel(string.Empty, @"C:\parts\bracket.SLDPRT", Stamp));
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
        }
    }
}
