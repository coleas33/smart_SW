using System;
using System.IO;
using System.Linq;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T076: the check run folder.
///
/// Every Model check writes `&lt;run_root&gt;/&lt;yyyyMMdd-HHmmss&gt;-&lt;doc&gt;-check` through the
/// same helper the review and the terminal use (`contracts/model-check.md` section 4). Three
/// things are asserted here and nowhere else:
///
/// 1. <b>The `-check` suffix is part of the name, not a separate folder.</b> The folders then
///    sort beside the review they belong to and are obviously disposable.
/// 2. <b>The naming rule is the review's naming rule.</b> Same cleaning of a path that cannot
///    be a folder name, same truncation, same collision suffix when two checks land in the same
///    second - a check is pressed after every edit, so that is a double-click, not an error.
/// 3. <b>The folder is created, not just named.</b> The dump writes `package.json` into it
///    immediately and the carry-forward copies `exceptions.json` into it before the rules run;
///    a name handed back without the directory behind it would fail later, inside the
///    extractor, where the message no longer points here.
///
/// The two rejected alternatives and the reasons they are rejected are in the contract:
/// writing into the existing latest run folder (the check's `package.json` would overwrite a
/// review's full package) and one reusable scratch folder (it destroys the previous check's
/// evidence, which is exactly what an engineer compares against after an edit).
/// </summary>
public sealed class RunFoldersCheckTests : IDisposable
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 16, 10, 15, 32);

    private readonly string _root;

    public RunFoldersCheckTests()
    {
        _root = Path.Combine(
            Path.GetTempPath(), "SwReview.RunFoldersCheck.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    private string RunRoot => Path.Combine(_root, "runs");

    [Fact]
    public void ACheckFolderIsTheTimestampTheDocumentAndTheCheckSuffixAndItExists()
    {
        string created = RunFolders.CreateForCheck(RunRoot, @"C:\parts\bracket.SLDPRT", Stamp);

        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-check"), created);
        Assert.True(Directory.Exists(created), $"the helper did not create {created}");
    }

    /// <summary>
    /// The same cases <c>ReviewHostTests</c> pins for the review folder, with `-check` on the
    /// end: one cleaning rule, or the two folder kinds would be two conventions in the one
    /// listing the engineer sorts by in Explorer.
    /// </summary>
    [Theory]
    [InlineData(@"C:\parts\bracket.sldprt", "20260916-101532-bracket-check")]
    [InlineData(@"C:\parts\sub/rev 2.SLDPRT", "20260916-101532-rev 2-check")]
    [InlineData(@"C:\parts\.sldprt", "20260916-101532-document-check")]
    [InlineData(@"C:\vault\bad|name*.sldprt", "20260916-101532-bad-name-check")]
    [InlineData("", "20260916-101532-document-check")]
    public void TheCheckFolderIsNamedByTheSameRuleAsTheReviewFolder(
        string documentPath, string expectedName)
    {
        string created = RunFolders.CreateForCheck(RunRoot, documentPath, Stamp);

        Assert.Equal(Path.Combine(RunRoot, expectedName), created);
        Assert.True(Directory.Exists(created));
    }

    [Fact]
    public void ALongDocumentNameIsTruncatedByTheSameBudgetTheReviewFolderUses()
    {
        string created = RunFolders.CreateForCheck(
            RunRoot, @"C:\parts\" + new string('a', 120) + ".sldprt", Stamp);

        Assert.Equal(
            Path.Combine(RunRoot, "20260916-101532-" + new string('a', RunFolders.MaxNameLength) + "-check"),
            created);
    }

    [Fact]
    public void TwoChecksInTheSameSecondGetDistinctFoldersThroughTheSameCollisionSuffix()
    {
        string first = RunFolders.CreateForCheck(RunRoot, @"C:\parts\bracket.sldprt", Stamp);
        string second = RunFolders.CreateForCheck(RunRoot, @"C:\parts\bracket.sldprt", Stamp);
        string third = RunFolders.CreateForCheck(RunRoot, @"C:\parts\bracket.sldprt", Stamp);

        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-check"), first);
        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-check-2"), second);
        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-check-3"), third);
        Assert.Equal(3, Directory.GetDirectories(RunRoot).Length);
    }

    [Fact]
    public void ACheckFolderNeverCollidesWithTheReviewFolderOfTheSameDocumentAndSecond()
    {
        string review = RunFolders.CreateForDocument(RunRoot, @"C:\parts\bracket.sldprt", Stamp);
        string check = RunFolders.CreateForCheck(RunRoot, @"C:\parts\bracket.sldprt", Stamp);

        Assert.NotEqual(review, check);
        Assert.EndsWith("-check", check, StringComparison.Ordinal);
        Assert.Equal(
            new[] { "20260916-101532-bracket", "20260916-101532-bracket-check" },
            Directory.GetDirectories(RunRoot).Select(Path.GetFileName).OrderBy(name => name).ToArray());
    }

    [Fact]
    public void ABlankRunRootIsRefusedWithTheSettingToFixRatherThanAFolderSomewhereElse()
    {
        ArgumentException failure = Assert.Throws<ArgumentException>(
            () => RunFolders.CreateForCheck("  ", @"C:\parts\bracket.sldprt", Stamp));

        Assert.Contains("run_root", failure.Message, StringComparison.Ordinal);
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
        catch (UnauthorizedAccessException)
        {
        }
    }
}
