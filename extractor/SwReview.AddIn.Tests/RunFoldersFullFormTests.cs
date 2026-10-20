using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 148A (feature 011 T186, research R12.3): every run folder is made in its full form -
/// <c>Path.GetFullPath</c> of the folder made - whatever spelling of the run root the setting holds, for
/// every kind of run: a review, a Model check, a Standards check, a re-modeler's run and the terminal's.
///
/// The run folder is handed on as it is made: to the extractor, to the backend, whose path rule refuses
/// a <c>..</c> segment in a run folder rather than resolve it, and for a re-modeler's run to the bridge's
/// bind and, as the folder of its copy, to the pane seat, whose one rule for the copy's path refuses
/// one too. Under a run root spelled <c>C:\work\..\runs</c>, a folder made as it was spelled ended every
/// plan before it began (research R11.8 item 5). And a folder made is spelled as the same folder found:
/// the review host compares the folder of a review removed this session with the folder its search finds
/// on disk, so both answer in the full form.
/// </summary>
public sealed class RunFoldersFullFormTests : IDisposable
{
    private static readonly DateTime Stamp = new DateTime(2026, 10, 20, 9, 30, 0);

    private static readonly PageDocument Document = new PageDocument(@"C:\Fictional\FICT-Bracket.SLDPRT", "FICT-Default");

    private readonly string _root;

    public RunFoldersFullFormTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.RunFoldersFullForm.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(_root, "work"));
        Directory.CreateDirectory(RunRoot);
    }

    public void Dispose() => Directory.Delete(_root, recursive: true);

    /// <summary>The run root, as the canonical form every spelling below names.</summary>
    private string RunRoot => Path.Combine(_root, "runs");

    public static IEnumerable<object[]> KindsAndSpellings() =>
        from kind in new[] { "review", "check", "standards", "remodel", "terminal" }
        from spelling in new[] { "a parent segment", "forward slashes", "a current-folder segment", "a trailing separator", "as it is" }
        select new object[] { kind, spelling };

    public static IEnumerable<object[]> Spellings() =>
        new[] { "a parent segment", "forward slashes", "a current-folder segment" }.Select(spelling => new object[] { spelling });

    [Theory]
    [MemberData(nameof(KindsAndSpellings))]
    public void EveryKindOfRunFolderIsMadeInItsFullForm(string kind, string spelling)
    {
        string created = Create(kind, Spell(spelling));

        Assert.Equal(Path.GetFullPath(Path.Combine(RunRoot, Path.GetFileName(created))), created);
        Assert.Equal(Path.GetFullPath(created), created);
        Assert.DoesNotContain('/', created);
        Assert.DoesNotContain(created.Split('\\'), segment => segment == ".." || segment == ".");
        Assert.True(Directory.Exists(created), $"the helper did not create {created}");
    }

    /// <summary>
    /// A folder made and the same folder found are one spelling: the Model check's and the Standards
    /// check's newest folder, and the waiting review the search finds, answer in the full form the folder
    /// was made in, so the review host's comparison of a removed review's folder with a found one holds.
    /// </summary>
    [Theory]
    [MemberData(nameof(Spellings))]
    public void AFolderMadeIsSpeltAsTheSameFolderFound(string spelling)
    {
        string root = Spell(spelling);

        string check = RunFolders.CreateForCheck(root, Document.Path, Stamp);
        Assert.Equal(check, RunFolders.NewestCheckFolder(root, RunFolders.CheckSuffix));

        string standards = RunFolders.CreateForStandards(root, Document.Path, Stamp);
        Assert.Equal(standards, RunFolders.NewestCheckFolder(root, RunFolders.StandardsSuffix));

        string review = RunFolders.CreateForDocument(root, Document.Path, Stamp);
        WriteWaitingSession(review);
        SessionRecord found = Assert.IsType<SessionRecord>(RunFolders.FindNotSentReview(root, Document));
        Assert.Equal(review, found.RunDirectory);
    }

    /// <summary>What the two searches answer is in full form too, whatever spelling of the root they are asked under.</summary>
    [Theory]
    [MemberData(nameof(Spellings))]
    public void TheSearchesAnswerInTheFullFormWhateverTheRootsSpelling(string spelling)
    {
        RunFolders.CreateForCheck(RunRoot, Document.Path, Stamp);
        string review = RunFolders.CreateForDocument(RunRoot, Document.Path, Stamp);
        WriteWaitingSession(review);

        string? check = RunFolders.NewestCheckFolder(Spell(spelling), RunFolders.CheckSuffix);
        SessionRecord? found = RunFolders.FindNotSentReview(Spell(spelling), Document);

        Assert.NotNull(check);
        Assert.Equal(Path.GetFullPath(Path.Combine(RunRoot, Path.GetFileName(check!))), check);
        Assert.Equal(review, found?.RunDirectory);
    }

    /// <summary>
    /// The searches still answer nothing, and throw nothing, for a root that names no folder: a character
    /// no path may hold, a colon after the drive's, and none at all.
    /// </summary>
    [Theory]
    [InlineData(@"C:\Fictional\bad<name>\runs")]
    [InlineData(@"C:\Fictional\runs:stream")]
    [InlineData("   ")]
    public void ARootThatNamesNoFolderIsAnsweredNothingByTheSearches(string root)
    {
        Assert.Null(RunFolders.NewestCheckFolder(root, RunFolders.CheckSuffix));
        Assert.Null(RunFolders.FindNotSentReview(root, Document));
    }

    private string Spell(string spelling)
    {
        switch (spelling)
        {
            case "a parent segment":
                return Path.Combine(_root, "work", "..", "runs");
            case "forward slashes":
                return RunRoot.Replace('\\', '/');
            case "a current-folder segment":
                return Path.Combine(_root, ".", "runs");
            case "a trailing separator":
                return RunRoot + Path.DirectorySeparatorChar;
            case "as it is":
                return RunRoot;
            default:
                throw new ArgumentOutOfRangeException(nameof(spelling), spelling, "not a spelling of the run root");
        }
    }

    private static string Create(string kind, string runRoot)
    {
        switch (kind)
        {
            case "review":
                return RunFolders.CreateForDocument(runRoot, Document.Path, Stamp);
            case "check":
                return RunFolders.CreateForCheck(runRoot, Document.Path, Stamp);
            case "standards":
                return RunFolders.CreateForStandards(runRoot, Document.Path, Stamp);
            case "remodel":
                return RunFolders.CreateForRemodel(runRoot, Document.Path, Stamp);
            case "terminal":
                return RunFolders.CreateForTerminal(runRoot, Stamp);
            default:
                throw new ArgumentOutOfRangeException(nameof(kind), kind, "not a kind of run");
        }
    }

    private static void WriteWaitingSession(string folder) =>
        File.WriteAllText(Path.Combine(folder, "session.json"), JsonSerializer.Serialize(new
        {
            session_id = "FICT-session",
            model_status = new
            {
                state = "not_sent",
                document = new { path = Document.Path, configuration = Document.Configuration },
                checked_at = "2026-10-20T09:30:00+10:30",
            },
        }));
}
