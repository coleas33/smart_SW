using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T071: the Standards check's run folder, and the newest-run scan both check tabs read on
/// `init` (`contracts/standards-check.md` section 4).
///
/// Two things are new here and everything else is feature 003's rule applied to a second
/// suffix:
///
/// 1. <b>`CreateForStandards` is `CreateForCheck` with `-standards` on the end.</b> Same
///    cleaning of a path that cannot be a folder name, same truncation budget, same collision
///    suffix - two presses inside one second are a double-click, not an error, and the second
///    must not be written into the first one's folder. The suffix is what lets one enumeration
///    of the run root answer for each check tab without opening anything.
/// 2. <b>`NewestCheckFolder` is a run-root scan that does not exist today.</b>
///    `ModelCheckHost.LatestCheck` is in-process state, so a check cannot be read back after a
///    restart at all right now; FR-034 and SC-009 require it. The scan answers <b>from the
///    folder names alone</b> - a `check.json` read per sibling would run on every tab
///    activation, and a name comparison is free where a file read is not - and one suffix never
///    answers for the other, so neither tab's latest check is ever the other tab's.
///
/// The registration rule is asserted here too, over a `-standards` folder: the folder becomes
/// the pane's latest run, which is what `CurrentSessionRunDirectory` and
/// <see cref="RunPackageIndex"/> read, so `entity.show` resolves `document_id` through the
/// package that was just written. Its <see cref="SessionRecord"/> carries no chat id, because
/// a check has no chat, and the any-turn-running scan skips it rather than asking the backend
/// about an id that does not exist (FR-034).
/// </summary>
public sealed class RunFoldersStandardsTests : IDisposable
{
    private static readonly DateTime Stamp = new DateTime(2026, 9, 16, 10, 15, 32);

    private readonly string _root;

    public RunFoldersStandardsTests()
    {
        _root = Path.Combine(
            Path.GetTempPath(), "SwReview.RunFoldersStandards.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    private string RunRoot => Path.Combine(_root, "runs");

    // ---- CreateForStandards ---------------------------------------------------------------

    [Fact]
    public void AStandardsFolderIsTheTimestampTheDocumentAndTheStandardsSuffixAndItExists()
    {
        string created = RunFolders.CreateForStandards(RunRoot, @"C:\parts\bracket.SLDASM", Stamp);

        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-standards"), created);
        Assert.True(Directory.Exists(created), $"the helper did not create {created}");
    }

    /// <summary>
    /// The same cases <see cref="RunFoldersCheckTests"/> pins for the check folder, with
    /// `-standards` on the end: one cleaning rule, or the folder kinds would be different
    /// conventions in the one listing the engineer sorts by in Explorer.
    /// </summary>
    [Theory]
    [InlineData(@"C:\parts\bracket.sldasm", "20260916-101532-bracket-standards")]
    [InlineData(@"C:\parts\sub/rev 2.SLDDRW", "20260916-101532-rev 2-standards")]
    [InlineData(@"C:\parts\.sldprt", "20260916-101532-document-standards")]
    [InlineData(@"C:\vault\bad|name*.sldprt", "20260916-101532-bad-name-standards")]
    [InlineData("", "20260916-101532-document-standards")]
    public void TheStandardsFolderIsNamedByTheSameRuleAsTheReviewAndCheckFolders(
        string documentPath, string expectedName)
    {
        string created = RunFolders.CreateForStandards(RunRoot, documentPath, Stamp);

        Assert.Equal(Path.Combine(RunRoot, expectedName), created);
        Assert.True(Directory.Exists(created));
    }

    [Fact]
    public void ALongDocumentNameIsTruncatedByTheSameBudgetTheCheckFolderUses()
    {
        string created = RunFolders.CreateForStandards(
            RunRoot, @"C:\parts\" + new string('a', 120) + ".sldasm", Stamp);

        Assert.Equal(
            Path.Combine(
                RunRoot, "20260916-101532-" + new string('a', RunFolders.MaxNameLength) + "-standards"),
            created);
    }

    [Fact]
    public void TwoStandardsRunsInTheSameSecondGetDistinctFoldersThroughTheSameCollisionSuffix()
    {
        string first = RunFolders.CreateForStandards(RunRoot, @"C:\parts\bracket.sldasm", Stamp);
        string second = RunFolders.CreateForStandards(RunRoot, @"C:\parts\bracket.sldasm", Stamp);
        string third = RunFolders.CreateForStandards(RunRoot, @"C:\parts\bracket.sldasm", Stamp);

        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-standards"), first);
        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-standards-2"), second);
        Assert.Equal(Path.Combine(RunRoot, "20260916-101532-bracket-standards-3"), third);
        Assert.Equal(3, Directory.GetDirectories(RunRoot).Length);
    }

    [Fact]
    public void AStandardsFolderNeverCollidesWithTheReviewOrCheckFolderOfTheSameSecond()
    {
        string review = RunFolders.CreateForDocument(RunRoot, @"C:\parts\bracket.sldprt", Stamp);
        string check = RunFolders.CreateForCheck(RunRoot, @"C:\parts\bracket.sldprt", Stamp);
        string standards = RunFolders.CreateForStandards(RunRoot, @"C:\parts\bracket.sldprt", Stamp);

        Assert.NotEqual(review, standards);
        Assert.NotEqual(check, standards);
        Assert.EndsWith(RunFolders.StandardsSuffix, standards, StringComparison.Ordinal);
        Assert.Equal(
            new[]
            {
                "20260916-101532-bracket",
                "20260916-101532-bracket-check",
                "20260916-101532-bracket-standards",
            },
            Directory.GetDirectories(RunRoot).Select(Path.GetFileName).OrderBy(name => name).ToArray());
    }

    [Fact]
    public void ABlankRunRootIsRefusedWithTheSettingToFixRatherThanAFolderSomewhereElse()
    {
        ArgumentException failure = Assert.Throws<ArgumentException>(
            () => RunFolders.CreateForStandards("  ", @"C:\parts\bracket.sldasm", Stamp));

        Assert.Contains("run_root", failure.Message, StringComparison.Ordinal);
    }

    // ---- the folder is the pane's latest run ----------------------------------------------

    /// <summary>
    /// The same registration a Model check makes, over a `-standards` folder: the pane points
    /// `CurrentSessionRunDirectory` and <see cref="RunPackageIndex"/> at
    /// <see cref="ReviewHost.LatestSession"/>, and `entity.show` resolves `document_id` to a
    /// path through the package in that folder. A standards run that wrote somewhere else would
    /// silently degrade Show to "no full path" for every finding and open the Ask tab in an
    /// unrelated folder.
    /// </summary>
    [Fact]
    public void TrackingAStandardsRunMakesItsFolderTheLatestRunAndTheRecordCarriesNoChatId()
    {
        using (var host = NewReviewHost(out FakeBackend backend))
        {
            string standards = RunFolders.CreateForStandards(
                RunRoot, @"C:\parts\bracket.sldasm", Stamp);
            WritePackage(standards, "doc-standards", @"C:\parts\bracket.sldasm");

            SessionRecord record = host.TrackCheck(standards);

            Assert.True(record.IsCheck);
            Assert.Null(record.ChatId);
            Assert.Equal(standards, record.RunDirectory);
            Assert.Same(record, host.LatestSession);

            // Spelled the way SwReviewAddIn spells it, and read through the index itself.
            var packages = new RunPackageIndex(() => host.LatestSession?.RunDirectory);
            Assert.Equal(@"C:\parts\bracket.sldasm", packages.DocumentPath("doc-standards"));

            // A check has no chat, so the backend is never asked about one.
            Assert.False(host.AnyTurnRunning());
            Assert.Empty(backend.TurnQuestions);
        }
    }

    // ---- NewestCheckFolder ------------------------------------------------------------------

    [Fact]
    public void TheScanAnswersNullForARunRootWithNothingInItAndForOneThatIsNotThere()
    {
        Directory.CreateDirectory(RunRoot);

        Assert.Null(RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix));
        Assert.Null(RunFolders.NewestCheckFolder(
            Path.Combine(_root, "never-created"), RunFolders.StandardsSuffix));
        Assert.Null(RunFolders.NewestCheckFolder("   ", RunFolders.StandardsSuffix));
        Assert.Null(RunFolders.NewestCheckFolder(null, RunFolders.StandardsSuffix));
    }

    /// <summary>
    /// The newest by the timestamp the folder name carries, not by what the file system happens
    /// to report: the run folder's name is the check id, and the id is what the page reads back.
    /// </summary>
    [Fact]
    public void TheScanReturnsTheNewestFolderCarryingTheSuffix()
    {
        MakeFolder("20260914-080000-bracket-standards");
        string newest = MakeFolder("20260916-101532-bracket-standards");
        MakeFolder("20260915-235959-housing-standards");

        Assert.Equal(newest, RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix));
    }

    /// <summary>
    /// A collision-suffixed folder is the newest one, not an unrecognized one: two runs in the
    /// same second leave `...-standards` and `...-standards-2`, and the second is the one the
    /// page asked for.
    /// </summary>
    [Fact]
    public void TheScanSeesTheCollisionSuffixedFolderAndPrefersTheLaterOfTheSameSecond()
    {
        MakeFolder("20260916-101532-bracket-standards");
        string second = MakeFolder("20260916-101532-bracket-standards-2");

        Assert.Equal(second, RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix));
    }

    /// <summary>
    /// Neither tab's latest check is ever the other tab's. This is the whole reason the suffix
    /// differs: one enumeration answers for each host from the names alone.
    /// </summary>
    [Fact]
    public void TheScanNeverAnswersOneSuffixWithTheOthersFolder()
    {
        string check = MakeFolder("20260916-101532-bracket-check");
        string standards = MakeFolder("20260914-080000-bracket-standards");
        MakeFolder("20260917-090000-bracket");
        MakeFolder("20260917-091000-bracket-remodel");
        MakeFolder("20260917-092000-terminal");

        Assert.Equal(standards, RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix));
        Assert.Equal(check, RunFolders.NewestCheckFolder(RunRoot, RunFolders.CheckSuffix));
    }

    /// <summary>
    /// A folder whose name does not start with a run timestamp is not a run folder this helper
    /// named, and is not answered with: the name is the check id and the page hands it straight
    /// to `GET /checks/{check_id}`.
    /// </summary>
    [Fact]
    public void TheScanIgnoresAFolderWhoseNameDoesNotCarryARunTimestamp()
    {
        MakeFolder("scratch-standards");
        string real = MakeFolder("20260914-080000-bracket-standards");

        Assert.Equal(real, RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix));

        Directory.Delete(real, recursive: true);
        Assert.Null(RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix));
    }

    /// <summary>
    /// <b>From the folder names alone.</b> `init` runs on every tab activation, so the scan
    /// opens nothing: not one of the folders below holds a `check.json`, and the one the scan
    /// must answer with holds a directory of that name, which every read of it would fail on.
    /// </summary>
    [Fact]
    public void TheScanReadsNoFileInsideTheFoldersItRanks()
    {
        MakeFolder("20260914-080000-bracket-standards");
        string newest = MakeFolder("20260916-101532-bracket-standards");
        Directory.CreateDirectory(Path.Combine(newest, "check.json"));

        Assert.Equal(newest, RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix));
    }

    [Fact]
    public void TheScanAnswersWithTheFullPathTheFolderNameIsTheCheckId()
    {
        string created = MakeFolder("20260916-101532-bracket-standards");

        string? found = RunFolders.NewestCheckFolder(RunRoot, RunFolders.StandardsSuffix);

        Assert.Equal(created, found);
        Assert.Equal("20260916-101532-bracket-standards", Path.GetFileName(found));
    }

    // ---- both check hosts read the scan on init ---------------------------------------------

    /// <summary>
    /// T072: the scan is called from <b>both</b> check tabs, each with its own suffix. The
    /// Standards side is pinned in <see cref="StandardsHostTests"/>; this is the Model check
    /// side, and it is here rather than in `ModelCheckHostTests` because that file is feature
    /// 003's regression proof and is not edited by this feature.
    /// </summary>
    [Fact]
    public void TheModelCheckHostReadsItsOwnNewestRunBackOnInitAndNeverAStandardsOne()
    {
        var posted = new List<string>();
        using (var host = new SwReview.AddIn.Model.ModelCheckHost(
            new SwReview.AddIn.Model.ModelCheckHostOptions(
                new CollectingChannel(posted), () => RunRoot)
            {
                LogFolder = () => Path.Combine(_root, "logs"),
            }))
        {
            string standards = MakeFolder("20260917-090000-bracket-standards");
            string check = MakeFolder("20260916-101532-bracket-check");

            host.Receive(
                System.Text.Json.JsonSerializer.Serialize(
                    new { type = "ready", id = "r1", payload = new { } }));

            System.Text.Json.JsonElement latest = Payload(posted, "init")
                .GetProperty("latest_check");
            Assert.Equal(check, latest.GetProperty("run_dir").GetString());
            Assert.NotEqual(standards, latest.GetProperty("run_dir").GetString());
        }
    }

    private static System.Text.Json.JsonElement Payload(List<string> posted, string type)
    {
        foreach (string message in posted)
        {
            System.Text.Json.JsonElement root =
                System.Text.Json.JsonDocument.Parse(message).RootElement;
            if (root.GetProperty("type").GetString() == type)
            {
                return root.GetProperty("payload");
            }
        }

        throw new InvalidOperationException($"no '{type}' message was posted");
    }

    // ---- the world --------------------------------------------------------------------------

    private string MakeFolder(string name)
    {
        string directory = Path.Combine(RunRoot, name);
        Directory.CreateDirectory(directory);
        return directory;
    }

    private ReviewHost NewReviewHost(out FakeBackend backend)
    {
        var settings = UserSettings.Defaults();
        settings.RunRoot = RunRoot;
        string settingsPath = Path.Combine(_root, "settings.json");
        settings.Save(settingsPath);

        backend = new FakeBackend();
        return new ReviewHost(new ReviewHostOptions(
            new NullChannel(), backend, settingsPath)
        {
            BuildMode = BuildMode.Development,
            LogFolder = Path.Combine(_root, "logs"),
            CurrentDocument = () => null,
            Environment = _ => null,
        });
    }

    private static void WritePackage(string runDirectory, string documentId, string documentPath)
    {
        var package = new SwReview.Extractor.Ir.EvidencePackage();
        package.Documents.Add(new SwReview.Extractor.Ir.Document
        {
            DocumentId = documentId,
            Kind = SwReview.Extractor.Ir.DocumentKind.Assembly,
            FileName = Path.GetFileName(documentPath),
            Path = documentPath,
            ActiveConfiguration = "Default",
        });

        File.WriteAllText(
            Path.Combine(runDirectory, "package.json"),
            SwReview.Extractor.Ir.PackageSerializer.Serialize(package));
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

    private sealed class NullChannel : IPageChannel
    {
        public void PostMessage(string json)
        {
        }
    }

    private sealed class CollectingChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public CollectingChannel(List<string> posted) => _posted = posted;

        public void PostMessage(string json) => _posted.Add(json);
    }

    /// <summary>A backend that records every chat it was asked about; it should never be asked.</summary>
    private sealed class FakeBackend : IBackendClient
    {
        public List<string> TurnQuestions { get; } = new List<string>();

        public BackendEndpoint? Endpoint => null;

        public IReadOnlyList<ModelChoice> ListModels(string provider) => new ModelChoice[0];

        public bool IsTurnRunning(string chatId)
        {
            TurnQuestions.Add(chatId);
            return false;
        }

        public void Restart(UserSettings settings, ResolvedApiKey key)
        {
        }

        public ChatSessionHandle CreateSession(NewSessionRequest request) =>
            throw new InvalidOperationException("a standards run never creates a chat session");
    }
}
