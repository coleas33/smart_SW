using System;
using System.IO;
using System.Linq;
using System.Text;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Decision 160A: fake the short-name lookup because a drive need not create 8.3 names.
/// The fake maps a synthetic short spelling to a real long root and requires the root to
/// exist before its long name is read. No SOLIDWORKS session or machine setting is needed.
/// </summary>
public sealed class RunFoldersLongNamesTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "SwReview.RunFoldersLongNames.Tests", Guid.NewGuid().ToString("N"));
    private static readonly DateTime Stamp = new DateTime(2026, 10, 21, 12, 34, 56);

    public RunFoldersLongNamesTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, recursive: true);
    }

    [Theory]
    [InlineData("review", "bracket")]
    [InlineData("check", "bracket-check")]
    [InlineData("standards", "bracket-standards")]
    [InlineData("remodel", "bracket-remodel")]
    [InlineData("terminal", "terminal")]
    public void EveryCreatedRunIsNamedUnderTheRootsLongNameReadOnceAfterTheRootExists(string kind, string label)
    {
        string shortRoot = Path.Combine(_root, "SHORT~1", "new", "runs");
        string longRoot = Path.Combine(_root, "Long Folder Name", "new", "runs");
        Directory.CreateDirectory(longRoot);
        var probe = new ExistingRootProbe(shortRoot, longRoot);

        string made;
        switch (kind)
        {
            case "review": made = RunFolders.CreateForDocument(shortRoot, @"C:\Fictional\bracket.sldprt", Stamp, probe); break;
            case "check": made = RunFolders.CreateForCheck(shortRoot, @"C:\Fictional\bracket.sldprt", Stamp, probe); break;
            case "standards": made = RunFolders.CreateForStandards(shortRoot, @"C:\Fictional\bracket.sldprt", Stamp, probe); break;
            case "remodel": made = RunFolders.CreateForRemodel(shortRoot, @"C:\Fictional\bracket.sldprt", Stamp, probe); break;
            case "terminal": made = RunFolders.CreateForTerminal(shortRoot, Stamp, probe); break;
            default: throw new ArgumentOutOfRangeException(nameof(kind));
        }

        Assert.Equal(Path.Combine(longRoot, "20261021-123456-" + label), made);
        Assert.True(Directory.Exists(made));
        Assert.Equal(1, probe.LongNameReads);
        Assert.Empty(Directory.GetDirectories(shortRoot));
    }

    [Fact]
    public void TheNewestCheckIsFoundUnderTheRootsLongName()
    {
        string shortRoot = Path.Combine(_root, "SHORT~1");
        string longRoot = Path.Combine(_root, "Long Folder Name");
        Directory.CreateDirectory(shortRoot);
        string expected = Path.Combine(longRoot, "20261021-123456-bracket-check");
        Directory.CreateDirectory(expected);
        var probe = new ExistingRootProbe(shortRoot, longRoot);

        Assert.Equal(expected, RunFolders.NewestCheckFolder(shortRoot, RunFolders.CheckSuffix, probe));
        Assert.Equal(1, probe.LongNameReads);
    }

    [Fact]
    public void AWaitingReviewIsFoundUnderTheRootsLongName()
    {
        string shortRoot = Path.Combine(_root, "SHORT~1");
        string longRoot = Path.Combine(_root, "Long Folder Name");
        Directory.CreateDirectory(shortRoot);
        string expected = Path.Combine(longRoot, "20261021-123456-bracket");
        Directory.CreateDirectory(expected);
        var probe = new ExistingRootProbe(shortRoot, longRoot);
        var document = new PageDocument(@"C:\Fictional\bracket.sldprt", "Default");
        const string head = "{\"session_id\":\"fictional-waiting\",\"model_status\":{\"state\":\"not_sent\","
            + "\"document\":{\"path\":\"C:\\\\Fictional\\\\bracket.sldprt\",\"configuration\":\"Default\"},"
            + "\"checked_at\":\"2026-10-21T12:34:56+00:00\"}}";

        SessionRecord? found = RunFolders.FindNotSentReview(
            shortRoot, document, _ => new MemoryStream(Encoding.UTF8.GetBytes(head)), probe);

        Assert.NotNull(found);
        Assert.Equal(expected, found!.RunDirectory);
        Assert.Equal(1, probe.LongNameReads);
    }

    [Fact]
    public void ALongNamedRunStillBelongsToTheSameShortSpelledRoot()
    {
        string shortRoot = Path.Combine(_root, "SHORT~1");
        string longRoot = Path.Combine(_root, "Long Folder Name");
        Directory.CreateDirectory(shortRoot);
        string folder = Path.Combine(longRoot, "20261021-123456-bracket-remodel");
        Directory.CreateDirectory(folder);
        var probe = new ExistingRootProbe(shortRoot, longRoot);

        Assert.True(RunFolders.IsUnder(folder, shortRoot, probe));
        Assert.Equal(1, probe.LongNameReads);
    }

    [Fact]
    public void AFolderAlreadyUnderTheWrittenRootNeedsNoLongNameRead()
    {
        string runRoot = Path.Combine(_root, "runs");
        var probe = FakeRunRootProbe.Local();

        Assert.True(RunFolders.IsUnder(Path.Combine(runRoot, "20261021-123456-bracket"), runRoot, probe));
        Assert.Empty(probe.Asked);
        Assert.Empty(probe.Normalized);
    }

    [Theory]
    [InlineData("on a share")]
    [InlineData("through a link")]
    public void ASearchRefusesTheRootBeforeAnyLongNameOrFolderIsRead(string kind)
    {
        var refused = FakeRunRootProbe.Refusing(kind, Path.Combine(_root, "runs"));

        Assert.Null(RunFolders.NewestCheckFolder(refused.RunRoot, RunFolders.CheckSuffix, refused.Probe));
        Assert.Null(RunFolders.FindNotSentReview(
            refused.RunRoot, new PageDocument(@"C:\Fictional\bracket.sldprt", "Default"), probe: refused.Probe));

        Assert.DoesNotContain(refused.Probe.Asked, call => call.StartsWith("LongPathOf", StringComparison.Ordinal));
        Assert.DoesNotContain(refused.Probe.Asked, call => call.StartsWith("EntryOf", StringComparison.Ordinal));
        Assert.Equal(2, refused.Probe.Asked.Count(call => call.StartsWith("DriveOf", StringComparison.Ordinal)));
    }

    private sealed class ExistingRootProbe : IRunRootProbe
    {
        private readonly string _shortRoot;
        private readonly string _longRoot;
        private readonly FakeRunRootProbe _probe = FakeRunRootProbe.Local();

        public ExistingRootProbe(string shortRoot, string longRoot)
        {
            _shortRoot = shortRoot;
            _longRoot = longRoot;
        }

        public int LongNameReads { get; private set; }
        public RunRootDrive DriveOf(string driveRoot) => _probe.DriveOf(driveRoot);
        public string? SubstituteOf(string drive) => _probe.SubstituteOf(drive);
        public RunRootEntry EntryOf(string path) => _probe.EntryOf(path);
        public string? FinalPathOf(string folder) => folder == _shortRoot ? _longRoot : _probe.FinalPathOf(folder);
        public string? FullPathOf(string root) => _probe.FullPathOf(root);
        public string? LongPathOf(string folder)
        {
            Assert.Equal(_shortRoot, folder);
            Assert.True(Directory.Exists(folder), "the root must exist before its long name is read");
            LongNameReads++;
            return _longRoot;
        }
    }
}
