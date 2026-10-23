using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using SwReview.AddIn.Native;
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

    /// <summary>The document the waiting review below is of.</summary>
    private static readonly PageDocument Bracket = new PageDocument(@"C:\Fictional\bracket.sldprt", "Default");

    /// <summary>A waiting review's session head, of <see cref="Bracket"/>, not sent.</summary>
    private const string WaitingHead = "{\"session_id\":\"fictional-waiting\",\"model_status\":{\"state\":\"not_sent\","
        + "\"document\":{\"path\":\"C:\\\\Fictional\\\\bracket.sldprt\",\"configuration\":\"Default\"},"
        + "\"checked_at\":\"2026-10-21T12:34:56+00:00\"}}";

    private static Stream OpenWaitingHead(string path) => new MemoryStream(Encoding.UTF8.GetBytes(WaitingHead));

    public RunFoldersLongNamesTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, recursive: true);
    }

    /// <summary>
    /// <i>Changed deliberately on the review of owner decision 160A (the letter case):</i> the run is named under the
    /// root's final path, read once after the root exists - its long-name form in the disk's own letter case, as the rule
    /// hands a search the root - where it was named under the root's long-name form, which keeps the case a long name
    /// is written in.
    /// </summary>
    [Theory]
    [InlineData("review", "bracket")]
    [InlineData("check", "bracket-check")]
    [InlineData("standards", "bracket-standards")]
    [InlineData("remodel", "bracket-remodel")]
    [InlineData("terminal", "terminal")]
    public void EveryCreatedRunIsNamedUnderTheRootsFinalPathReadOnceAfterTheRootExists(string kind, string label)
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
        Assert.Equal(1, probe.FinalPathReads);
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

        SessionRecord? found = RunFolders.FindNotSentReview(shortRoot, Bracket, OpenWaitingHead, probe);

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

    /// <summary>
    /// A search refuses a root the rule refuses before anything of it is read. <i>Strengthened deliberately on the review of
    /// owner decision 160A (S4):</i> the root is there, with a check and a waiting review in it, so a search that read it
    /// anyway would find them; it was not made, and a search that read it found nothing either way.
    /// </summary>
    [Theory]
    [InlineData("on a share")]
    [InlineData("through a link")]
    public void ASearchRefusesTheRootBeforeAnyLongNameOrFolderIsRead(string kind)
    {
        string runRoot = Path.Combine(_root, "runs");
        Directory.CreateDirectory(Path.Combine(runRoot, "20261021-123456-bracket-check"));
        Directory.CreateDirectory(Path.Combine(runRoot, "20261021-123456-bracket"));
        var refused = FakeRunRootProbe.Refusing(kind, runRoot);

        Assert.Null(RunFolders.NewestCheckFolder(refused.RunRoot, RunFolders.CheckSuffix, refused.Probe));
        Assert.Null(RunFolders.FindNotSentReview(refused.RunRoot, Bracket, OpenWaitingHead, refused.Probe));

        Assert.All(refused.Probe.Asked, call => Assert.True(AboutTheDrive(call), "read of a refused root: " + call));
        Assert.Equal(2, refused.Probe.Asked.Count(call => call.StartsWith("DriveOf", StringComparison.Ordinal)));
    }

    /// <summary>
    /// The final review of owner decision 160A: a folder held to a root the rule refuses - the containment rule's second
    /// look, made when the folder is not under the root as written - reads nothing of that root but its drive, no final
    /// path, long name or part of it, as a search reads none.
    /// </summary>
    [Theory]
    [InlineData("on a share")]
    [InlineData("through a link")]
    public void AContainmentCheckRefusesTheRootBeforeAnythingOfItIsRead(string kind)
    {
        var refused = FakeRunRootProbe.Refusing(kind, Path.Combine(_root, "runs"));

        Assert.False(RunFolders.IsUnder(Path.Combine(_root, "elsewhere", "20261021-123456-bracket"), refused.RunRoot, refused.Probe));
        Assert.NotEmpty(refused.Probe.Asked);
        Assert.All(refused.Probe.Asked, call => Assert.True(AboutTheDrive(call), "read of a refused root: " + call));
    }

    /// <summary>Whether a question the probe was asked is about the drive alone: what it is, and what it stands for.</summary>
    private static bool AboutTheDrive(string call) =>
        call.StartsWith("DriveOf ", StringComparison.Ordinal) || call.StartsWith("SubstituteOf ", StringComparison.Ordinal);

    /// <summary>
    /// The review of owner decision 160A (S5): a root not made yet, below an existing folder spelled with 8.3 names, hands a
    /// search nothing - not the long form of the folder the rule's walk stopped at, which a search would read as the root,
    /// finding that folder's runs.
    /// </summary>
    [Fact]
    public void ARootNotYetMadeBelowAShortSpelledFolderHandsASearchNothingOfThatFolder()
    {
        string shortParent = Path.Combine(_root, "SHORT~1");
        string longParent = Path.Combine(_root, "Long Folder Name");
        Directory.CreateDirectory(Path.Combine(longParent, "20261021-123456-bracket-check"));
        Directory.CreateDirectory(Path.Combine(longParent, "20261021-123456-bracket"));
        string runRoot = Path.Combine(shortParent, "new", "runs");
        FakeRunRootProbe probe = FakeRunRootProbe.ExistingDownTo(shortParent);
        probe.FinalPaths[shortParent] = longParent;
        probe.LongPaths[shortParent] = longParent;

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runRoot, probe, out string? existing));
        Assert.Null(existing);
        Assert.Null(RunFolders.NewestCheckFolder(runRoot, RunFolders.CheckSuffix, probe));
        Assert.Null(RunFolders.FindNotSentReview(runRoot, Bracket, OpenWaitingHead, probe));
    }

    /// <summary>
    /// The review of owner decision 160A (the letter case): a run folder made and the same folder found are spelled alike,
    /// letter for letter - in the disk's own case, the run root's final path, which the rule hands a search and the
    /// backend's own resolution reads - whatever case the setting spells the run root in. Read of the real disk.
    /// </summary>
    [Fact]
    public void AFolderMadeAndTheSameFolderFoundAreSpelledAlikeInTheDisksOwnCase()
    {
        string onDisk = Path.Combine(_root, "Runs Folder");
        Directory.CreateDirectory(onDisk);
        string setting = Path.Combine(_root, "rUNS fOLDER");

        string made = RunFolders.CreateForCheck(setting, @"C:\Fictional\bracket.sldprt", Stamp);
        string? found = RunFolders.NewestCheckFolder(setting, RunFolders.CheckSuffix);

        Assert.Equal(made, found);
        Assert.Equal(Path.Combine(WindowsRunRootProbe.Instance.FinalPathOf(onDisk)!, "20261021-123456-bracket-check"), made);
    }

    /// <summary>
    /// ...and below a root spelled with 8.3 names: a search's root is the root's final path, in the disk's own case, which
    /// the rule checks against its long-name form - whose long names keep the case they are written in
    /// (<c>GetLongPathNameW</c>) - as the folder a run is made in is named.
    /// </summary>
    [Fact]
    public void AShortSpelledRootIsSearchedUnderItsFinalPathInTheDisksOwnCase()
    {
        string shortRoot = Path.Combine(_root, "SHORT~1");
        string longRoot = Path.Combine(_root, "Long Folder Name");
        string expected = Path.Combine(longRoot, "20261021-123456-bracket-check");
        Directory.CreateDirectory(expected);
        FakeRunRootProbe probe = FakeRunRootProbe.Local();
        probe.FinalPaths[shortRoot] = longRoot;
        probe.LongPaths[shortRoot] = Path.Combine(_root, "LONG FOLDER NAME");

        Assert.Equal(expected, RunFolders.NewestCheckFolder(shortRoot, RunFolders.CheckSuffix, probe));
    }

    /// <summary>
    /// The review of owner decision 160A (S7): a run root whose final path cannot be read once it is made fails the run
    /// folder - the hosts answer `RunFolderFailed` - rather than naming the run under the root as the setting spells it.
    /// </summary>
    [Fact]
    public void ARootWhoseFinalPathCannotBeReadOnceMadeFailsTheRunFolder()
    {
        string runRoot = Path.Combine(_root, "runs");
        FakeRunRootProbe probe = FakeRunRootProbe.Local();
        probe.FinalPaths[runRoot] = null;

        Assert.Throws<IOException>(() => RunFolders.CreateForCheck(runRoot, @"C:\Fictional\bracket.sldprt", Stamp, probe));
        Assert.Empty(Directory.GetDirectories(runRoot));
    }

    /// <summary>
    /// The review of owner decision 160A: every host hands the run folders the probe its run root rule reads, so a test's
    /// fake answers both and neither reads the real disk behind the other's back - each call that makes or finds a run
    /// folder, or holds one to the run root, and each host's pane actions and check pane, which make such calls of their
    /// own. All but the hidden Terminal tab's, which judges no run root and holds no probe. Read from the source, as the
    /// add-in's other wiring cases are; a call added later is added here, with its probe.
    /// </summary>
    [Fact]
    public void EveryHostHandsTheRunFoldersItsRunRootProbe()
    {
        var calls = new List<string>();
        var options = new List<string>();
        foreach ((string name, string source) in AddInSources().Where(file => file.Name != "RunFolders.cs"))
        {
            foreach (Match call in Regex.Matches(source, @"RunFolders\.(CreateFor\w+|NewestCheckFolder|FindNotSentReview|IsUnder)\("))
            {
                calls.Add(name + " " + call.Groups[1].Value + Enclosed(source, call.Index + call.Length - 1, '(', ')'));
            }

            foreach (Match made in Regex.Matches(source, @"new (PaneActionsOptions|CheckPaneHostOptions)\("))
            {
                int after = Enclosed(source, made.Index + made.Length - 1, '(', ')').Length + made.Index + made.Length - 1;
                string rest = source.Substring(after).TrimStart();
                options.Add(name + " " + made.Groups[1].Value + " "
                    + (rest.StartsWith("{", StringComparison.Ordinal) ? Enclosed(rest, 0, '{', '}') : string.Empty));
            }
        }

        Assert.Equal(
            new[]
            {
                "CheckPaneHost.cs NewestCheckFolder",
                "ModelCheckHost.cs CreateForCheck",
                "PaneActions.cs IsUnder",
                "PaneActions.cs IsUnder",
                "RemodelHost.cs CreateForRemodel",
                "RemodelHost.cs IsUnder",
                "ReviewHost.cs CreateForDocument",
                "ReviewHost.cs CreateForDocument",
                "ReviewHost.cs FindNotSentReview",
                "ReviewHost.cs IsUnder",
                "StandardsHost.cs CreateForStandards",
                "TaskPaneControl.cs CreateForTerminal",
            },
            calls.Select(call => call.Substring(0, call.IndexOf('('))).OrderBy(call => call, StringComparer.Ordinal));
        Assert.All(
            calls.Where(call => !call.StartsWith("TaskPaneControl.cs CreateForTerminal(", StringComparison.Ordinal)),
            call => Assert.Contains(LastArgument(call), new[] { "_options.RunRootProbe", "_options.RunRootProbe()" }));
        Assert.Equal(5, options.Count);
        Assert.All(options, made => Assert.Matches(@"RunRootProbe = \(\) => _?options\.RunRootProbe(\(\))?,", made));
    }

    /// <summary>
    /// The last argument of a call as the scan above writes it - "File.cs Name(arguments)" - by the commas outside any
    /// bracket: the host's probe, exactly, and not another that names a probe too (the decision's final review).
    /// </summary>
    private static string LastArgument(string call)
    {
        string arguments = call.Substring(call.IndexOf('(') + 1, call.LastIndexOf(')') - call.IndexOf('(') - 1);
        int depth = 0;
        int last = 0;
        for (int index = 0; index < arguments.Length; index++)
        {
            char character = arguments[index];
            if (character == '(' || character == '{' || character == '[') depth++;
            if (character == ')' || character == '}' || character == ']') depth--;
            if (character == ',' && depth == 0) last = index + 1;
        }

        return arguments.Substring(last).Trim();
    }

    /// <summary>
    /// ...and the run root rule a run start is refused by reads the same probe, through the pane actions' own option: the
    /// one way in since the coordinator's follow-up to the review of owner decision 160A, where each host also handed
    /// <c>RefusedRunRoot</c> its probe as an argument. No call passes one, the refusal takes none, and it judges the root
    /// with the option - which each host sets, above, and which each host's refusal cases, a refusing probe each, read.
    /// </summary>
    [Fact]
    public void ARunStartIsRefusedThroughThePaneActionsOwnProbe()
    {
        var calls = new List<string>();
        string? refusal = null;
        foreach ((string name, string source) in AddInSources())
        {
            foreach (Match call in Regex.Matches(source, @"\.RefusedRunRoot\("))
            {
                calls.Add(name + " " + Enclosed(source, call.Index + call.Length - 1, '(', ')'));
            }

            Match defined = Regex.Match(source, @"public bool RefusedRunRoot\(");
            if (defined.Success)
            {
                string parameters = Enclosed(source, defined.Index + defined.Length - 1, '(', ')');
                int body = source.IndexOf('{', defined.Index + defined.Length - 1 + parameters.Length);
                refusal = parameters + " " + Enclosed(source, body, '{', '}');
            }
        }

        Assert.Equal(
            new[] { "ModelCheckHost.cs", "RemodelHost.cs", "ReviewHost.cs", "StandardsHost.cs" },
            calls.Select(call => call.Substring(0, call.IndexOf(' '))).OrderBy(name => name, StringComparer.Ordinal));
        Assert.All(calls, call => Assert.DoesNotContain("RunRootProbe", call, StringComparison.Ordinal));
        Assert.NotNull(refusal);
        Assert.DoesNotContain("IRunRootProbe", refusal!, StringComparison.Ordinal);
        Assert.Contains("RunRootRule.Judge(runRoot, _options.RunRootProbe())", refusal!, StringComparison.Ordinal);
    }

    /// <summary>The add-in's own C# files, by name and text, outside its build output.</summary>
    private static IEnumerable<(string Name, string Text)> AddInSources()
    {
        string addIn = Path.Combine(ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn");
        foreach (string file in Directory.GetFiles(addIn, "*.cs", SearchOption.AllDirectories))
        {
            string relative = file.Substring(addIn.Length + 1);
            if (relative.StartsWith(@"bin\", StringComparison.OrdinalIgnoreCase)
                || relative.StartsWith(@"obj\", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            yield return (Path.GetFileName(file), File.ReadAllText(file));
        }
    }

    /// <summary>The text from the <paramref name="open"/> at <paramref name="at"/> to the <paramref name="close"/> that closes it.</summary>
    private static string Enclosed(string source, int at, char open, char close)
    {
        Assert.Equal(open, source[at]);
        int depth = 0;
        for (int index = at; index < source.Length; index++)
        {
            if (source[index] == open) depth++;
            if (source[index] == close && --depth == 0) return source.Substring(at, index - at + 1);
        }

        throw new InvalidOperationException("unbalanced " + open + " at " + at);
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
        public int FinalPathReads { get; private set; }
        public RunRootDrive DriveOf(string driveRoot) => _probe.DriveOf(driveRoot);
        public string? SubstituteOf(string drive) => _probe.SubstituteOf(drive);
        public RunRootEntry EntryOf(string path) => _probe.EntryOf(path);
        public string? FinalPathOf(string folder)
        {
            if (folder != _shortRoot)
            {
                return _probe.FinalPathOf(folder);
            }

            Assert.True(Directory.Exists(folder), "the root must exist before its final path is read");
            FinalPathReads++;
            return _longRoot;
        }

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
