using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 154A (feature 002 T189, research 154A): a run root is acceptable only when it is a local
/// folder reached by its own path. The backend writes only into a local folder and refuses a UNC or device
/// path for every route, and it resolves the run folder it is sent, following a junction, a symbolic link, a
/// substituted drive or a mapped network drive, where the add-in binds its own spelling - so under a run root
/// on a share nothing can run, and under one reached through a link the re-modeler's copy is refused at its
/// open (feature 011 research R12.9, items 1 and 2). The rule names such a root before any run is begun.
///
/// What it refuses, and in what order, so that nothing is ever opened over the network or through a link:
/// a root written as a UNC or device path, on its text, before even its full path is made; then its full path,
/// made from the text alone, which reads nothing; a mapped network drive and a substituted drive, by what
/// Windows says of the drive letter; a junction or symbolic link among the folders that exist, by what each is,
/// never by opening through it; a part there that cannot be read as itself, which could hide a link, as
/// unverified; and any root whose final path - the nearest existing folder's, which is what the backend's own
/// resolution reads - differs from its spelling other than by letter case and from its long-name form too,
/// read only then (the reviews of decision 154A, findings F1 to F3). A root that does not exist yet is judged
/// by its nearest existing folder. Decision 160A refuses invalid folder names on their text, at the save
/// and at every run start. A blank root or one on a drive that is not there stays left to the run folder.
///
/// Most cases run over <see cref="FakeRunRootProbe"/>, which fakes what this machine cannot make without
/// rights or side effects (a share, a mapped drive, a substituted drive); the cases a test can make for real
/// under the temp folder - a junction (<c>mklink /J</c>), a long path, another letter case, an 8.3 short name -
/// run over <see cref="WindowsRunRootProbe"/>. Every path in a faked case is fictional and nothing is touched.
/// </summary>
public sealed class RunRootRuleTests : IDisposable
{
    private const string Fictional = @"C:\Fictional";

    private readonly string _root;

    private readonly List<string> _junctions = new List<string>();

    private readonly List<(string Folder, uint Tag)> _tagged = new List<(string Folder, uint Tag)>();

    private readonly List<(string Folder, FileSystemAccessRule Rule)> _denied = new List<(string Folder, FileSystemAccessRule Rule)>();

    public RunRootRuleTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.RunRootRule.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        // The denials first, so every folder can be read and removed again.
        foreach ((string folder, FileSystemAccessRule rule) in _denied)
        {
            DirectorySecurity security = Directory.GetAccessControl(folder);
            security.RemoveAccessRule(rule);
            Directory.SetAccessControl(folder, security);
        }

        // A tagged folder's reparse point next, which no filter answers, so the folder can be removed.
        foreach ((string folder, uint tag) in _tagged)
        {
            SetReparsePoint(folder, tag, FsctlDeleteReparsePoint, data: null);
        }

        // The junctions first, by their own names, so nothing below is reached through them; then the rest.
        foreach (string junction in _junctions)
        {
            try
            {
                Directory.Delete(Device(junction));
            }
            catch (IOException)
            {
            }
        }

        try
        {
            Directory.Delete(Device(_root), recursive: true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    // ---- a local folder reached by its own path --------------------------------------------------------

    /// <summary>
    /// A local folder reached by its own path is accepted, and the questions are asked in the rule's order:
    /// the drive, whether it is substituted, each part from the top, then the deepest folder's final path.
    /// </summary>
    [Fact]
    public void ALocalFolderReachedByItsOwnPathIsAcceptedAfterEveryQuestionInItsOrder()
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Fictional + @"\work\runs", probe));
        Assert.Equal(
            new[]
            {
                @"DriveOf C:\",
                "SubstituteOf C:",
                @"EntryOf C:\Fictional",
                @"EntryOf C:\Fictional\work",
                @"EntryOf C:\Fictional\work\runs",
                @"FinalPathOf C:\Fictional\work\runs",
            },
            probe.Asked);
    }

    // ---- on a share, or written as a device path: refused on sight --------------------------------------

    [Theory]
    [InlineData(@"\\fictional-server\share\runs")]
    [InlineData("//fictional-server/share/runs")]
    [InlineData(@"\/fictional-server/share/runs")]
    [InlineData(@"/\fictional-server\share\runs")]
    [InlineData(@"\\?\UNC\fictional-server\share\runs")]
    [InlineData(@"\\.\UNC\fictional-server\share\runs")]
    [InlineData(@"\\fictional-server")]
    public void ARootWrittenAsAShareIsRefusedBeforeAnythingIsAsked(string runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge(runRoot, probe));
        Assert.Empty(probe.Asked);
    }

    [Theory]
    [InlineData(@"\\?\C:\Fictional\runs")]
    [InlineData(@"\\.\C:\Fictional\runs")]
    [InlineData("//?/C:/Fictional/runs")]
    [InlineData(@"\\?\Volume{00000000-0000-0000-0000-000000000000}\runs")]
    public void ARootWrittenAsADevicePathIsRefusedBeforeAnythingIsAsked(string runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.DevicePath, RunRootRule.Judge(runRoot, probe));
        Assert.Empty(probe.Asked);
    }

    // ---- nothing is read before the rule's checks (the reviews' finding F1) ------------------------------

    /// <summary>
    /// A root written as a share with an 8.3 short name in it is refused on its text, before anything is read
    /// or made of it: <c>Path.GetFullPath</c> expands a short name by reading each folder of the path - over the
    /// network for a share, where a server that does not answer stalls every run start and every save - so the
    /// rule asks no full path of such a root at all.
    /// </summary>
    [Theory]
    [InlineData(@"\\fictional-server.invalid\share\RUNS~1")]
    [InlineData("//fictional-server.invalid/share/RUNS~1/runs")]
    [InlineData(@"\\?\UNC\fictional-server.invalid\share\RUNS~1")]
    public void AShareWithAShortNameIsRefusedBeforeAnythingIsReadOrMadeOfIt(string runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge(runRoot, probe));
        Assert.Empty(probe.Asked);
        Assert.Empty(probe.Normalized);
    }

    /// <summary>
    /// A link above a short name is found by what it is before anything below it is read: expanding the short
    /// name would read through the link, so the long-name form is asked for only once the walk has found no
    /// link - and here it never is.
    /// </summary>
    [Fact]
    public void ALinkAboveAShortNameIsRefusedBeforeTheShortNameIsReadThroughIt()
    {
        var probe = new FakeRunRootProbe();
        probe.Links.Add(Fictional + @"\link");

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Fictional + @"\link\RUNS~1\runs", probe));
        Assert.Equal(
            new[] { @"DriveOf C:\", "SubstituteOf C:", @"EntryOf C:\Fictional", @"EntryOf C:\Fictional\link" },
            probe.Asked);
    }

    /// <summary>A mapped network drive is refused by its letter, short name or not, before any of its folders is read.</summary>
    [Fact]
    public void AMappedNetworkDriveWithAShortNameIsRefusedByItsLetterAlone()
    {
        var probe = new FakeRunRootProbe();
        probe.Drives[@"Z:\"] = RunRootDrive.Network;

        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge(@"Z:\RUNS~1\runs", probe));
        Assert.Equal(new[] { @"DriveOf Z:\" }, probe.Asked);
    }

    /// <summary>
    /// A relative root is made full against the current folder, from its text alone: under a current folder on
    /// a share it is on the share, and refused before anything is read.
    /// </summary>
    [Fact]
    public void ARelativeRootUnderACurrentFolderOnAShareIsOnTheShare()
    {
        var probe = new FakeRunRootProbe();
        probe.FullPaths["runs"] = @"\\fictional-server.invalid\share\work\runs";

        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge("runs", probe));
        Assert.Equal(new[] { "runs" }, probe.Normalized);
        Assert.Empty(probe.Asked);
    }

    /// <summary>
    /// The rule reads the disk and the network only through its probe, whose questions each read one thing,
    /// asked in the rule's order: it makes no full path through <c>Path.GetFullPath</c> or
    /// <see cref="RunFolders"/>, expands no short name itself and calls Windows for nothing. Its source is read,
    /// since what a call reads below the probe's questions cannot be seen in the probe's own record.
    /// </summary>
    [Fact]
    public void TheRuleReadsTheDiskAndTheNetworkOnlyThroughItsProbe()
    {
        string source = File.ReadAllText(Path.Combine(
            ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn", "Review", "RunRootRule.cs"));
        string code = string.Join(
            "\n",
            source.Split('\n').Where(line => !line.TrimStart().StartsWith("//", StringComparison.Ordinal)));

        foreach (string reading in new[]
                 {
                     "System.IO", "Path.Get", "Directory.", "File.", "RunFolders.", "GetLongPathName",
                     "GetFullPathName", "DllImport", "CreateFile",
                 })
        {
            Assert.DoesNotContain(reading, code, StringComparison.Ordinal);
        }
    }

    // ---- a mapped network drive and a substituted drive: refused by the letter, nothing touched ---------

    [Theory]
    [InlineData(@"Z:\Fictional\runs")]
    [InlineData(@"Z:\")]
    [InlineData("z:/fictional/runs")]
    public void AMappedNetworkDriveIsRefusedBeforeAnyOfItsFoldersIsTouched(string runRoot)
    {
        var probe = new FakeRunRootProbe();
        probe.Drives[@"Z:\"] = RunRootDrive.Network;

        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge(runRoot, probe));
        Assert.Equal(new[] { @"DriveOf Z:\" }, probe.Asked);
    }

    [Theory]
    [InlineData(@"S:\Fictional\runs")]
    [InlineData(@"S:\")]
    [InlineData("s:/fictional/runs")]
    public void ASubstitutedDriveIsRefusedBeforeAnyOfItsFoldersIsTouched(string runRoot)
    {
        var probe = new FakeRunRootProbe();
        probe.Substitutes["S:"] = Fictional + @"\work";

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(runRoot, probe));
        Assert.Equal(new[] { @"DriveOf S:\", "SubstituteOf S:" }, probe.Asked);
    }

    /// <summary>A drive substituted for a folder on a share is on the share.</summary>
    [Fact]
    public void ADriveSubstitutedForAShareIsOnTheShare()
    {
        var probe = new FakeRunRootProbe();
        probe.Substitutes["S:"] = @"\\fictional-server\share";

        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge(@"S:\runs", probe));
        Assert.DoesNotContain(probe.Asked, question => question.StartsWith("EntryOf", StringComparison.Ordinal));
    }

    // ---- a link among the folders that exist, and a final path elsewhere --------------------------------

    /// <summary>
    /// A junction or symbolic link among the folders that exist is refused by what it is, and nothing is
    /// asked through it: not the parts below it, and no final path, whose reading opens the folder.
    /// </summary>
    [Fact]
    public void ALinkAmongTheExistingFoldersIsRefusedWithoutOpeningAnythingThroughIt()
    {
        var probe = new FakeRunRootProbe();
        probe.Links.Add(Fictional + @"\link");

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Fictional + @"\link\work\runs", probe));
        Assert.Equal(@"EntryOf C:\Fictional\link", probe.Asked.Last());
        Assert.DoesNotContain(probe.Asked, question => question.StartsWith("FinalPathOf", StringComparison.Ordinal));
    }

    /// <summary>A root whose final path is another folder is reached through a link, whatever the link is.</summary>
    [Fact]
    public void ARootWhoseFinalPathIsAnotherFolderIsRefusedAsReachedThroughALink()
    {
        var probe = new FakeRunRootProbe();
        probe.FinalPaths[Fictional + @"\work\runs"] = @"D:\Elsewhere\runs";

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Fictional + @"\work\runs", probe));
    }

    /// <summary>A final path on a share is on the share.</summary>
    [Fact]
    public void ARootWhoseFinalPathIsOnAShareIsOnTheShare()
    {
        var probe = new FakeRunRootProbe();
        probe.FinalPaths[Fictional + @"\work\runs"] = @"\\fictional-server\share\runs";

        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge(Fictional + @"\work\runs", probe));
    }

    [Theory]
    [InlineData(@"c:\FICTIONAL\Work\RUNS")]
    [InlineData(@"C:\Fictional\work\runs\")]
    [InlineData(@"C:\fictional\WORK\runs\")]
    public void AFinalPathThatDiffersOnlyByLetterCaseOrATrailingSeparatorIsAccepted(string runRoot)
    {
        var probe = new FakeRunRootProbe();
        probe.FinalPaths[Fictional + @"\work\runs"] = Fictional + @"\work\runs";

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runRoot, probe));
    }

    /// <summary>
    /// A final path that cannot be read leaves the root unverified: whether it is reached through a link cannot
    /// be told. Changed deliberately (the reviews' finding F2) from the first answer, which read it as no reason
    /// to refuse.
    /// </summary>
    [Fact]
    public void AFinalPathThatCannotBeReadLeavesTheRootUnverified()
    {
        var probe = new FakeRunRootProbe();
        probe.FinalPaths[Fictional + @"\work\runs"] = null;

        Assert.Equal(RunRootVerdict.Unverified, RunRootRule.Judge(Fictional + @"\work\runs", probe));
    }

    // ---- a part that cannot be read (the reviews' finding F2) ---------------------------------------------

    /// <summary>
    /// A part that is there but cannot be read as itself - its attributes denied - cannot be told from a link,
    /// and Windows lets every user pass through such a folder to what lies below it, a link to a share among
    /// them: the root could not be checked, and is refused as unverified with nothing below it read. The first
    /// answer read such a part as the end of the walk, and accepted the folder above it.
    /// </summary>
    [Fact]
    public void APartThatCannotBeReadLeavesTheRootUnverified()
    {
        var probe = new FakeRunRootProbe();
        probe.Unreadable.Add(Fictional + @"\restricted");

        Assert.Equal(RunRootVerdict.Unverified, RunRootRule.Judge(Fictional + @"\restricted\link\runs", probe));
        Assert.Equal(@"EntryOf C:\Fictional\restricted", probe.Asked.Last());
    }

    // ---- 8.3 short names (the reviews' finding F3) ------------------------------------------------------

    /// <summary>
    /// A root spelled with an 8.3 short name has a final path in long names: the final path is compared with
    /// the folder's long-name form, read only once the walk has found no link and only when the final path is
    /// not the spelling - so a short name is not a link.
    /// </summary>
    [Fact]
    public void AFinalPathInLongNamesIsComparedWithTheLongNameOfAShortName()
    {
        var probe = new FakeRunRootProbe { Existing = Set(Fictional, Fictional + @"\LONGFO~1") };
        probe.FinalPaths[Fictional + @"\LONGFO~1"] = Fictional + @"\Long Folder Name";
        probe.LongPaths[Fictional + @"\LONGFO~1"] = Fictional + @"\Long Folder Name";

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Fictional + @"\LONGFO~1\new", probe));
        Assert.Equal(
            new[]
            {
                @"DriveOf C:\",
                "SubstituteOf C:",
                @"EntryOf C:\Fictional",
                @"EntryOf C:\Fictional\LONGFO~1",
                @"EntryOf C:\Fictional\LONGFO~1\new",
                @"FinalPathOf C:\Fictional\LONGFO~1",
                @"LongPathOf C:\Fictional\LONGFO~1",
            },
            probe.Asked);
    }

    /// <summary>A final path that is not the long-name form either is reached through a link.</summary>
    [Fact]
    public void AFinalPathThatIsNotTheLongNameEitherIsReachedThroughALink()
    {
        var probe = new FakeRunRootProbe();
        probe.FinalPaths[Fictional + @"\LONGFO~1"] = @"D:\Elsewhere";
        probe.LongPaths[Fictional + @"\LONGFO~1"] = Fictional + @"\Long Folder Name";

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Fictional + @"\LONGFO~1", probe));
    }

    /// <summary>
    /// A long-name form that cannot be read - a folder above denies its listing, which reading it needs -
    /// leaves the root unverified, when the final path is not its spelling.
    /// </summary>
    [Fact]
    public void ALongNameThatCannotBeReadLeavesTheRootUnverified()
    {
        var probe = new FakeRunRootProbe();
        probe.FinalPaths[Fictional + @"\LONGFO~1"] = Fictional + @"\Long Folder Name";
        probe.LongPaths[Fictional + @"\LONGFO~1"] = null;

        Assert.Equal(RunRootVerdict.Unverified, RunRootRule.Judge(Fictional + @"\LONGFO~1", probe));
    }

    // ---- a root that does not exist yet ------------------------------------------------------------------

    /// <summary>
    /// A root the settings name before it is made - the run folder is made with it - is judged by its nearest
    /// existing folder: the walk stops at the first part that is not there, and that folder's final path is read.
    /// </summary>
    [Fact]
    public void ARootThatDoesNotExistYetIsJudgedByItsNearestExistingFolder()
    {
        var probe = new FakeRunRootProbe { Existing = Set(Fictional, Fictional + @"\work") };

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Fictional + @"\work\new\runs", probe));
        Assert.Equal(
            new[]
            {
                @"DriveOf C:\",
                "SubstituteOf C:",
                @"EntryOf C:\Fictional",
                @"EntryOf C:\Fictional\work",
                @"EntryOf C:\Fictional\work\new",
                @"FinalPathOf C:\Fictional\work",
            },
            probe.Asked);

        probe.FinalPaths[Fictional + @"\work"] = @"D:\Elsewhere";
        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Fictional + @"\work\new\runs", probe));
    }

    [Fact]
    public void ARootThatDoesNotExistYetUnderAJunctionIsRefused()
    {
        var probe = new FakeRunRootProbe { Existing = Set(Fictional, Fictional + @"\link") };
        probe.Links.Add(Fictional + @"\link");

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Fictional + @"\link\runs", probe));
    }

    /// <summary>A part that is a file ends the walk: nothing is below it, and the run folder reports it.</summary>
    [Fact]
    public void APartThatIsAFileEndsTheWalkAtTheFolderAboveIt()
    {
        var probe = new FakeRunRootProbe();
        probe.Files.Add(Fictional + @"\notes.txt");

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Fictional + @"\notes.txt\runs", probe));
        Assert.Equal(@"FinalPathOf C:\Fictional", probe.Asked.Last());
    }

    // ---- spellings ---------------------------------------------------------------------------------------

    /// <summary>
    /// The root is judged in its full form - the form every run folder is made under (owner decision 148A) -
    /// whatever spelling the setting holds: forward slashes, a parent segment, a current-folder segment.
    /// </summary>
    [Theory]
    [InlineData("C:/Fictional/work/runs")]
    [InlineData(@"C:\Fictional\other\..\work\runs")]
    [InlineData(@"C:\Fictional\.\work\runs")]
    [InlineData(@"C:\Fictional/work\runs")]
    public void ARootIsJudgedInItsFullFormWhateverItsSpelling(string runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runRoot, probe));
        Assert.Equal(@"FinalPathOf C:\Fictional\work\runs", probe.Asked.Last());
        Assert.DoesNotContain(probe.Asked, question => question.Contains('/') || question.Contains(".."));
    }

    [Fact]
    public void ADrivesRootIsJudgedAsTheDrive()
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(@"C:\", probe));
        Assert.Equal(new[] { @"DriveOf C:\", "SubstituteOf C:", @"FinalPathOf C:\" }, probe.Asked);
    }

    // ---- what the rule leaves to the run folder ----------------------------------------------------------

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void ARootTheRuleCannotReadIsLeftToTheRunFolder(string? runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runRoot, probe));
        Assert.Empty(probe.Asked);
    }

    /// <summary>
    /// Decision 160A: no folder can ever be made under these roots, so the save and every run
    /// refuse them on their text, with no disk reading and no path in the save's words.
    /// </summary>
    [Theory]
    [InlineData(@"C:\Fictional\a:b")]
    [InlineData(@"C:\Fictional\x<y")]
    [InlineData(@"C:\Fictional\x>y")]
    [InlineData(@"C:\Fictional\x|y")]
    [InlineData(@"C:\Fictional\x*y")]
    [InlineData(@"C:\Fictional\x?y")]
    [InlineData("C:\\Fictional\\runs\"")]
    [InlineData("C:\\Fictional\\x\u0001y")]
    public void AnInvalidFolderNameIsRefusedBeforeAnythingIsAsked(string runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        RunRootVerdict verdict = RunRootRule.Judge(runRoot, probe);
        Assert.Equal(RunRootVerdict.InvalidFolderName, verdict);
        Assert.Empty(probe.Asked);
        Assert.Empty(probe.Normalized);
        Assert.Equal(
            "The folder chosen for runs has a name Windows cannot use for a folder, so the run root was not "
            + "changed; the other settings were saved. Use folder names of at most 255 characters, with none of "
            + "\\ / : * ? \" < > | and no control characters in them, then save again.",
            RunRootRule.ChosenRefusal(verdict));
    }

    [Fact]
    public void AnInvalidFolderNameAlreadyInForceHasPlainWordsForTheRunAndTheSave()
    {
        RunRootVerdict verdict = RunRootRule.Judge(@"C:\Fictional\x<y", FakeRunRootProbe.Local());

        Assert.Equal(
            "The run root has a name Windows cannot use for a folder, so nothing was checked. Choose a local "
            + "folder for runs in Settings on the Review tab, then press Model check again.",
            RunRootRule.Refusal(verdict, "nothing was checked", RunRootRule.InSettingsOnTheReviewTab, "press Model check again"));
        Assert.Equal(
            "The run root has a name Windows cannot use for a folder, so every run is refused until it is "
            + "changed; the settings were saved. Choose a local folder for runs, then save again.",
            RunRootRule.KeptRefusal(verdict));
    }

    [Fact]
    public void ARootOnADriveThatIsNotThereIsLeftToTheRunFolder()
    {
        var probe = new FakeRunRootProbe();
        probe.Drives[@"Q:\"] = RunRootDrive.Missing;

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(@"Q:\Fictional\runs", probe));
        Assert.Equal(new[] { @"DriveOf Q:\" }, probe.Asked);
    }

    /// <summary>
    /// Decision 160A deliberately changes 154A's N8: an impossible name is refused before any
    /// disk reading, both at the save and at a run start. The boundary of 255 stays accepted.
    /// </summary>
    [Fact]
    public void AFolderNameLongerThanWindowsAllowsIsRefusedBeforeAnythingIsAsked()
    {
        FakeRunRootProbe tooLong = FakeRunRootProbe.Local();
        Assert.Equal(RunRootVerdict.InvalidFolderName, RunRootRule.Judge(Fictional + @"\" + new string('a', 256) + @"\runs", tooLong));
        Assert.Empty(tooLong.Asked);
        Assert.Empty(tooLong.Normalized);

        FakeRunRootProbe longest = FakeRunRootProbe.Local();
        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Fictional + @"\" + new string('a', 255) + @"\runs", longest));
        Assert.Contains(@"EntryOf C:\Fictional\" + new string('a', 255), longest.Asked);
    }

    // ---- a folder name that ends in a space or a period (the reviews of the merge, F1) ---------------------

    /// <summary>
    /// The reviews of 154A's merge, finding F1 (feature 002 T204): a folder name that ends in a space or a period
    /// is read two ways. <c>GetFullPathNameW</c>, which the rule's full path is made with, and the backend's own
    /// resolution, which the backend is started with, keep <c>Work </c> and <c>Work..</c> as written, while .NET's
    /// legacy path handling - SOLIDWORKS' most likely - trims them when the add-in makes its run folders, so every
    /// run's folder would be made under another folder than the backend's run root and refused deep in the run. So
    /// any folder of the path, the last too, ending in a space or a period, one or more, is refused on its text,
    /// before anything is read or made of it - a relative root the settings file names as well.
    /// </summary>
    [Theory]
    [InlineData(@"C:\Fictional\Work \runs")]
    [InlineData(@"C:\Fictional\Work..\runs")]
    [InlineData(@"C:\Fictional\Work.\runs")]
    [InlineData(@"C:\Fictional\Work...\runs")]
    [InlineData(@"C:\Fictional\Work .\runs")]
    [InlineData(@"C:\Fictional\runs.")]
    [InlineData(@"C:\Fictional\Work \")]
    [InlineData("C:/Fictional/Work /runs")]
    [InlineData(@"Work \runs")]
    public void AFolderNameEndingInASpaceOrAPeriodIsRefusedBeforeAnythingIsAsked(string runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.NameEndsInSpaceOrPeriod, RunRootRule.Judge(runRoot, probe));
        Assert.Empty(probe.Asked);
        Assert.Empty(probe.Normalized);
    }

    /// <summary>
    /// ...while <c>.</c> and <c>..</c>, the folder itself and the one above it, are no names, and a name with a
    /// space or a period inside it, or at its start, is a name like any other.
    /// </summary>
    [Theory]
    [InlineData(@"C:\Fictional\.\runs")]
    [InlineData(@"C:\Fictional\work\..\runs")]
    [InlineData(@"C:\Fictional\my work\runs.v2")]
    [InlineData(@"C:\Fictional\.hidden\runs")]
    [InlineData(@"C:\Fictional\ leading\runs")]
    public void DotSegmentsAndNamesWithASpaceOrAPeriodInsideAreJudgedAsAnyOther(string runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runRoot, probe));
        Assert.NotEmpty(probe.Asked);
    }

    // ---- the default run root ----------------------------------------------------------------------------

    /// <summary>
    /// The default run root, Documents\SwReview\runs, is judged as any other: on a mapped home drive it is on
    /// a share, and when Documents is redirected to a share it is written as one. Nothing is touched: the probe
    /// is faked, and the redirected Documents is fictional.
    /// </summary>
    [Fact]
    public void TheDefaultRunRootIsJudgedAsAnyOther()
    {
        string defaultRoot = UserSettings.Defaults().RunRoot;

        FakeRunRootProbe network = FakeRunRootProbe.OnANetworkDrive();
        Assert.Equal(RunRootVerdict.Share, RunRootRule.Judge(defaultRoot, network));
        Assert.DoesNotContain(network.Asked, question => !question.StartsWith("DriveOf", StringComparison.Ordinal));

        FakeRunRootProbe redirected = FakeRunRootProbe.Local();
        Assert.Equal(
            RunRootVerdict.Share,
            RunRootRule.Judge(Path.Combine(@"\\fictional-server\home\Documents", "SwReview", "runs"), redirected));
        Assert.Empty(redirected.Asked);
    }

    // ---- the words ---------------------------------------------------------------------------------------

    /// <summary>
    /// A run start's words: what the root is, the rule, what was not done, and the way on - since the owner's
    /// follow-up to decision 154A, a local folder chosen in the Settings panel's field, where the first
    /// words named the settings file and a restart of SOLIDWORKS. Changed deliberately for that, and again for
    /// the reviews' findings: the Model check, Standards and Remodel pages have no Settings of their own, so
    /// their words say the Settings are on the Review tab (F5), and a root that could not be checked says so
    /// (F2).
    /// </summary>
    [Theory]
    [InlineData(
        RunRootVerdict.Share,
        "The run root is on a network share or a mapped network drive, and runs are made only in a local folder "
        + "reached by its own path, so nothing was checked. Choose a local folder for runs in Settings on the "
        + "Review tab, then press Model check again.")]
    [InlineData(
        RunRootVerdict.Link,
        "The run root is reached through a link, such as a junction, a symbolic link or a substituted drive, and "
        + "runs are made only in a local folder reached by its own path, so nothing was checked. Choose a local "
        + "folder for runs in Settings on the Review tab, then press Model check again.")]
    [InlineData(
        RunRootVerdict.DevicePath,
        "The run root is written as a Windows device path, and runs are made only in a local folder reached by "
        + "its own path, so nothing was checked. Choose a local folder for runs in Settings on the Review tab, "
        + "then press Model check again.")]
    [InlineData(
        RunRootVerdict.Unverified,
        "The run root could not be checked, since a part of its path cannot be read, and runs are made only in a "
        + "local folder reached by its own path, so nothing was checked. Choose a local folder for runs in "
        + "Settings on the Review tab, then press Model check again.")]
    [InlineData(
        RunRootVerdict.NameEndsInSpaceOrPeriod,
        "The run root has a folder whose name ends in a space or a period, which Windows reads both with and "
        + "without it, and runs are made only in a local folder reached by its own path, so nothing was checked. "
        + "Choose a local folder for runs in Settings on the Review tab, then press Model check again.")]
    public void TheRefusalSaysWhatIsTrueOfTheRootTheRuleAndTheWayOn(RunRootVerdict verdict, string words)
    {
        Assert.Equal(
            words,
            RunRootRule.Refusal(verdict, "nothing was checked", RunRootRule.InSettingsOnTheReviewTab, "press Model check again"));
    }

    /// <summary>The Review tab's own refusals send the engineer to the Settings on that tab.</summary>
    [Fact]
    public void TheReviewTabsRefusalSendsTheEngineerToItsOwnSettings()
    {
        Assert.Equal(
            "The run root is on a network share or a mapped network drive, and runs are made only in a local folder "
            + "reached by its own path, so nothing was started. Choose a local folder for runs in Settings, then "
            + "try again.",
            RunRootRule.Refusal(RunRootVerdict.Share, "nothing was started", RunRootRule.InSettings, "try again"));
    }

    /// <summary>
    /// The owner's follow-up: a save never fails for the run root. A folder chosen in the Settings field that
    /// the rule refuses is the one field not saved, and the save's answer says so - of the folder chosen, not
    /// of the run root in force, which is unchanged - and that the other settings were saved.
    /// </summary>
    [Theory]
    [InlineData(
        RunRootVerdict.Share,
        "The folder chosen for runs is on a network share or a mapped network drive, and runs are made only in a "
        + "local folder reached by its own path, so the run root was not changed; the other settings were saved. "
        + "Choose a local folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.Link,
        "The folder chosen for runs is reached through a link, such as a junction, a symbolic link or a "
        + "substituted drive, and runs are made only in a local folder reached by its own path, so the run root "
        + "was not changed; the other settings were saved. Choose a local folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.DevicePath,
        "The folder chosen for runs is written as a Windows device path, and runs are made only in a local folder "
        + "reached by its own path, so the run root was not changed; the other settings were saved. Choose a "
        + "local folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.Unverified,
        "The folder chosen for runs could not be checked, since a part of its path cannot be read, and runs are "
        + "made only in a local folder reached by its own path, so the run root was not changed; the other "
        + "settings were saved. Choose a local folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.NameEndsInSpaceOrPeriod,
        "The folder chosen for runs has a folder whose name ends in a space or a period, which Windows reads both "
        + "with and without it, and runs are made only in a local folder reached by its own path, so the run root "
        + "was not changed; the other settings were saved. Choose a local folder for runs, then save again.")]
    public void ASaveSaysAFolderChosenForRunsWasRefusedAndTheOtherSettingsWereSaved(RunRootVerdict verdict, string words)
    {
        Assert.Equal(words, RunRootRule.ChosenRefusal(verdict));
    }

    /// <summary>
    /// ...and a save that leaves a refused run root in force - the one the settings file names, or the
    /// default under a Documents on a share - goes through, and its answer says the run root is refused, that
    /// every run is refused until it is changed, and the way on.
    /// </summary>
    [Theory]
    [InlineData(
        RunRootVerdict.Share,
        "The run root is on a network share or a mapped network drive, and runs are made only in a local folder "
        + "reached by its own path, so every run is refused until it is changed; the settings were saved. Choose "
        + "a local folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.Link,
        "The run root is reached through a link, such as a junction, a symbolic link or a substituted drive, and "
        + "runs are made only in a local folder reached by its own path, so every run is refused until it is "
        + "changed; the settings were saved. Choose a local folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.DevicePath,
        "The run root is written as a Windows device path, and runs are made only in a local folder reached by "
        + "its own path, so every run is refused until it is changed; the settings were saved. Choose a local "
        + "folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.Unverified,
        "The run root could not be checked, since a part of its path cannot be read, and runs are made only in a "
        + "local folder reached by its own path, so every run is refused until it is changed; the settings were "
        + "saved. Choose a local folder for runs, then save again.")]
    [InlineData(
        RunRootVerdict.NameEndsInSpaceOrPeriod,
        "The run root has a folder whose name ends in a space or a period, which Windows reads both with and "
        + "without it, and runs are made only in a local folder reached by its own path, so every run is refused "
        + "until it is changed; the settings were saved. Choose a local folder for runs, then save again.")]
    public void ASaveSaysTheRunRootItLeavesInForceIsRefused(RunRootVerdict verdict, string words)
    {
        Assert.Equal(words, RunRootRule.KeptRefusal(verdict));
    }

    /// <summary>
    /// The reviews' finding F7: a folder chosen for runs that is not written as a full path is the one field a
    /// save does not write - resolved against the current folder, it names one place to the add-in and maybe
    /// another to the backend, and SOLIDWORKS can move its current folder - and the words say so, and the way
    /// on, with no path.
    /// </summary>
    [Fact]
    public void ASaveSaysAFolderChosenForRunsThatIsNotAFullPathWasNotSaved()
    {
        Assert.Equal(
            "The folder chosen for runs is not written as a full path, starting with its drive letter, so the run "
            + "root was not changed; the other settings were saved. Type the folder's full path, then save again.",
            RunRootRule.NotFullPathRefusal);
    }

    /// <summary>
    /// Owner decision 154A, with 153A's record of the settings in force (feature 002 T201): what a run start on
    /// the Model check, Standards or Remodel tab is refused with while a start of the backend under way would bring
    /// another run root into force - why, what was not done, and the way on, the same press in a moment - with no
    /// path. Its pages print it whole.
    /// </summary>
    [Theory]
    [InlineData(
        "nothing was checked",
        "press Model check again",
        "The review backend is being started with another folder for runs, so nothing was checked. Press Model check "
        + "again in a moment.")]
    [InlineData(
        "the plan was not applied",
        "press Remodel a copy again",
        "The review backend is being started with another folder for runs, so the plan was not applied. Press Remodel "
        + "a copy again in a moment.")]
    public void ARunStartWhileAnotherRunRootComesIntoForceIsRefusedInWordsThatSaySo(string notDone, string wayOn, string words)
    {
        Assert.Equal(words, RunRootRule.MovingRefusal(notDone, wayOn));
    }

    /// <summary>
    /// The reviews of 154A's merge, N4 (feature 002 T204): while a folder chosen for runs in Settings is not in
    /// force - its save's restart failed - a start refused for the run root in force is told so, and the way on
    /// is the restart the folder chosen comes into force with, not a local folder chosen again, which the engineer
    /// has just done: what the run root in force is, the rule, what was not done, and that way on, with no path.
    /// </summary>
    [Theory]
    [InlineData(
        RunRootVerdict.Share,
        "nothing was started",
        RunRootRule.InSettings,
        "try again",
        "The run root in force is on a network share or a mapped network drive, and runs are made only in a local "
        + "folder reached by its own path, so nothing was started. The folder chosen for runs in Settings is not in "
        + "force until the review backend restarts with it: save the settings again to retry the restart, then try "
        + "again.")]
    [InlineData(
        RunRootVerdict.Link,
        "nothing was checked",
        RunRootRule.InSettingsOnTheReviewTab,
        "press Model check again",
        "The run root in force is reached through a link, such as a junction, a symbolic link or a substituted "
        + "drive, and runs are made only in a local folder reached by its own path, so nothing was checked. The "
        + "folder chosen for runs in Settings on the Review tab is not in force until the review backend restarts "
        + "with it: save the settings again to retry the restart, then press Model check again.")]
    [InlineData(
        RunRootVerdict.InvalidFolderName,
        "nothing was checked",
        RunRootRule.InSettingsOnTheReviewTab,
        "press Model check again",
        "The run root in force has a name Windows cannot use for a folder, so nothing was checked. The folder chosen "
        + "for runs in Settings on the Review tab is not in force until the review backend restarts with it: save the "
        + "settings again to retry the restart, then press Model check again.")]
    public void ARunStartUnderARefusedRunRootWhileAnotherIsChosenSaysToRetryTheRestart(
        RunRootVerdict verdict, string notDone, string where, string wayOn, string words)
    {
        Assert.Equal(words, RunRootRule.ChosenNotInForceRefusal(verdict, notDone, where, wayOn));
    }

    /// <summary>
    /// The reviews of 154A's merge, N6 (feature 002 T204): what a Model check or a Standards run is answered with
    /// when, read again once its extraction is over, the run root in force no longer holds its folder - a
    /// settings save's restart brought another in meanwhile: what changed and when, why it matters, what was not
    /// done and the way on, with no path. Its pages print it whole.
    /// </summary>
    [Fact]
    public void ARunWhoseRunRootChangedWhileTheModelWasReadIsAnsweredInWordsThatSaySo()
    {
        Assert.Equal(
            "The run root changed while the feature tree was read, and the backend makes runs only under the one in "
            + "force, so nothing was checked. Press Model check again.",
            RunRootRule.ChangedRefusal("the feature tree was read", "nothing was checked", "press Model check again"));
    }

    /// <summary>
    /// A full path starts with its drive letter and a separator, or with two separators - a share or a device
    /// path, which the rule itself refuses. A relative path, one rooted on the current drive, and one on a drive
    /// with no separator after its letter, which is relative to that drive's current folder, are not.
    /// </summary>
    [Theory]
    [InlineData(@"C:\runs", true)]
    [InlineData("c:/runs", true)]
    [InlineData(@"C:\", true)]
    [InlineData(@"\\fictional-server\share\runs", true)]
    [InlineData("//fictional-server/share/runs", true)]
    [InlineData(@"\\?\C:\runs", true)]
    [InlineData("runs", false)]
    [InlineData(@".\runs", false)]
    [InlineData(@"..\runs", false)]
    [InlineData(@"\runs", false)]
    [InlineData("/runs", false)]
    [InlineData("C:runs", false)]
    [InlineData("C:", false)]
    [InlineData(@"~\runs", false)]
    public void AFullPathStartsWithItsDriveLetterOrTwoSeparators(string root, bool full)
    {
        Assert.Equal(full, RunRootRule.IsFullPath(root));
    }

    [Fact]
    public void ThereAreNoWordsForARootTheRuleAccepts()
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => RunRootRule.Refusal(
                RunRootVerdict.Accepted, "nothing was checked", RunRootRule.InSettings, "press Model check again"));
        Assert.Throws<ArgumentOutOfRangeException>(() => RunRootRule.ChosenRefusal(RunRootVerdict.Accepted));
        Assert.Throws<ArgumentOutOfRangeException>(() => RunRootRule.KeptRefusal(RunRootVerdict.Accepted));
        Assert.Throws<ArgumentOutOfRangeException>(
            () => RunRootRule.ChosenNotInForceRefusal(
                RunRootVerdict.Accepted, "nothing was checked", RunRootRule.InSettings, "press Model check again"));
    }

    // ---- the real thing, under the temp folder -----------------------------------------------------------

    [Fact]
    public void AFolderUnderTheTempFolderIsAcceptedAndSoIsOneNotMadeYet()
    {
        string runs = Path.Combine(_root, "runs");
        Directory.CreateDirectory(runs);

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runs, WindowsRunRootProbe.Instance));
        Assert.Equal(
            RunRootVerdict.Accepted,
            RunRootRule.Judge(Path.Combine(_root, "new", "runs"), WindowsRunRootProbe.Instance));
    }

    /// <summary>
    /// A real junction under the temp folder, made with <c>mklink /J</c>, which needs no rights: a root that is
    /// the junction, one below it that exists, and one below it not made yet, are each reached through a link.
    /// </summary>
    [Fact]
    public void ARunRootThroughARealJunctionIsRefusedWhetherOrNotItExistsBelowIt()
    {
        string target = Path.Combine(_root, "target");
        Directory.CreateDirectory(Path.Combine(target, "inner"));
        string link = MakeJunction(Path.Combine(_root, "link"), target);

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(link, WindowsRunRootProbe.Instance));
        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Path.Combine(link, "inner"), WindowsRunRootProbe.Instance));
        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Path.Combine(link, "runs"), WindowsRunRootProbe.Instance));
        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Path.Combine(target, "inner"), WindowsRunRootProbe.Instance));
    }

    /// <summary>
    /// Another letter case is the same folder, and so is an 8.3 short name, whose long-name form is the final
    /// path: neither is a link. The short name is the one Windows gave the folder, so the case is not vacuous.
    /// </summary>
    [Fact]
    public void ARealRootSpeltInOtherLetterCaseOrWithAnEightDotThreeShortNameIsAccepted()
    {
        string runs = Path.Combine(_root, "Long Folder Name For The Rule", "runs");
        Directory.CreateDirectory(runs);
        string shortName = ShortPathOf(runs);
        Assert.NotEqual(runs, shortName, StringComparer.OrdinalIgnoreCase);
        Assert.Contains("~", shortName);

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runs.ToUpperInvariant(), WindowsRunRootProbe.Instance));
        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runs.ToLowerInvariant(), WindowsRunRootProbe.Instance));
        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(shortName, WindowsRunRootProbe.Instance));
        Assert.Equal(
            RunRootVerdict.Accepted,
            RunRootRule.Judge(Path.Combine(shortName, "new"), WindowsRunRootProbe.Instance));
    }

    /// <summary>
    /// The reviews' finding F3, its exact shape: an 8.3 short name of an existing folder followed by one folder
    /// not made yet - <c>C:\PROGRA~1\new</c> - was refused as a link, since <c>Path.GetFullPath</c> under the
    /// newer path handling leaves such a short name as written, and not the same way each time. The rule now
    /// makes no full path through it: each part is read as written and the final path is compared with the
    /// long-name form, so the verdict does not depend on the path handling SOLIDWORKS runs the add-in with.
    /// </summary>
    [Fact]
    public void AShortNameFollowedByOneFolderNotMadeYetIsAccepted()
    {
        string folder = Path.Combine(_root, "Long Folder Name For The Rule");
        Directory.CreateDirectory(folder);
        string shortName = ShortPathOf(folder);
        Assert.Contains("~", Path.GetFileName(shortName));

        for (int reading = 0; reading < 3; reading++)
        {
            Assert.Equal(
                RunRootVerdict.Accepted,
                RunRootRule.Judge(Path.Combine(shortName, "new"), WindowsRunRootProbe.Instance));
        }

        Assert.Equal(
            RunRootVerdict.Accepted,
            RunRootRule.Judge(Path.Combine(shortName, "new", "deeper"), WindowsRunRootProbe.Instance));
    }

    /// <summary>
    /// The reviews' finding F2, for real: a folder whose attributes are denied - and whose own folder denies its
    /// listing, so nothing grants them back - which every user may still pass through, with a junction below
    /// it. A user with no rights beyond their own temp folder makes it, and the rule cannot see the junction
    /// past the folder it cannot read: the root is unverified, where the first answer accepted it. The denials
    /// are taken off again before anything is removed.
    /// </summary>
    [Fact]
    public void ARootBelowAFolderThatCannotBeReadIsUnverifiedThoughALinkLiesBelowIt()
    {
        string outer = Path.Combine(_root, "outer");
        string restricted = Path.Combine(outer, "restricted");
        string target = Path.Combine(_root, "target");
        Directory.CreateDirectory(restricted);
        Directory.CreateDirectory(target);
        string link = MakeJunction(Path.Combine(restricted, "link"), target);
        Deny(outer, FileSystemRights.ListDirectory);
        Deny(restricted, FileSystemRights.ReadAttributes | FileSystemRights.ListDirectory);

        Assert.Equal(RunRootEntry.Unreadable, WindowsRunRootProbe.Instance.EntryOf(restricted));
        Assert.Equal(RunRootEntry.Link, WindowsRunRootProbe.Instance.EntryOf(link));
        Assert.Equal(RunRootVerdict.Unverified, RunRootRule.Judge(Path.Combine(link, "runs"), WindowsRunRootProbe.Instance));
    }

    /// <summary>
    /// A root longer than MAX_PATH is judged past it: a long local folder is accepted, and a junction that lies
    /// past MAX_PATH - read only through the <c>\\?\</c> form - is found.
    /// </summary>
    [Fact]
    public void ARealRootLongerThanMaxPathIsJudgedPastIt()
    {
        string deep = Path.Combine(_root, new string('a', 100), new string('b', 100), new string('c', 100));
        Directory.CreateDirectory(Device(deep));
        Assert.True(deep.Length > 260, "the root is not past MAX_PATH: " + deep.Length);

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(deep, WindowsRunRootProbe.Instance));

        string target = Path.Combine(_root, "target");
        Directory.CreateDirectory(target);
        string link = MakeJunction(Path.Combine(deep, "link"), target);

        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Path.Combine(link, "runs"), WindowsRunRootProbe.Instance));
    }

    /// <summary>
    /// Decision 160A changes only the rule's answer: the probe still reports an unreadable
    /// invalid name, and the rule refuses it from the text before asking the probe.
    /// </summary>
    [Fact]
    public void ARealRootWithAFolderNameLongerThanWindowsAllowsIsRefused()
    {
        string tooLong = Path.Combine(_root, new string('a', 256));

        Assert.Equal(RunRootEntry.Unreadable, WindowsRunRootProbe.Instance.EntryOf(tooLong));
        Assert.Equal(RunRootEntry.Missing, WindowsRunRootProbe.Instance.EntryOf(Path.Combine(_root, new string('a', 255))));
        Assert.Equal(RunRootVerdict.InvalidFolderName, RunRootRule.Judge(Path.Combine(tooLong, "runs"), WindowsRunRootProbe.Instance));
    }

    /// <summary>
    /// A reparse point is a link only when it names another path - a name surrogate: a junction, a symbolic
    /// link, a mount point. A cloud file's folder - a OneDrive folder, which Known Folder Move makes of
    /// Documents and with it of the default run root - carries one that names no other path, and is read as a
    /// folder, not a link. Made for real with a third-party tag, which needs no rights: one without the
    /// surrogate bit, as a cloud file's, and the same tag with it. No filter answers either tag, so nothing
    /// below or through them opens: a root under the first could not be checked, and is unverified - changed
    /// deliberately from the first answer, which accepted it (the reviews' finding F2) - while a OneDrive
    /// folder, whose filter answers, has its own final path and is accepted.
    /// </summary>
    [Fact]
    public void AReparsePointIsALinkOnlyWhenItNamesAnotherPath()
    {
        string plain = MakeReparsePoint(Path.Combine(_root, "cloud"), 0x00001234);
        string surrogate = MakeReparsePoint(Path.Combine(_root, "elsewhere"), 0x20001234);

        Assert.Equal(RunRootEntry.Folder, WindowsRunRootProbe.Instance.EntryOf(plain));
        Assert.Equal(RunRootEntry.Link, WindowsRunRootProbe.Instance.EntryOf(surrogate));
        Assert.Equal(RunRootVerdict.Unverified, RunRootRule.Judge(Path.Combine(plain, "runs"), WindowsRunRootProbe.Instance));
        Assert.Equal(RunRootVerdict.Link, RunRootRule.Judge(Path.Combine(surrogate, "runs"), WindowsRunRootProbe.Instance));
    }

    // ---- the Windows probe itself ------------------------------------------------------------------------

    [Fact]
    public void TheWindowsProbeReadsTheSystemDriveAsLocalAndAnUnusedLetterAsMissing()
    {
        string systemRoot = Path.GetPathRoot(Environment.SystemDirectory)!;
        string unused = UnusedDriveRoot();

        Assert.Equal(RunRootDrive.Local, WindowsRunRootProbe.Instance.DriveOf(systemRoot));
        Assert.Null(WindowsRunRootProbe.Instance.SubstituteOf(systemRoot.Substring(0, 2)));
        Assert.Equal(RunRootDrive.Missing, WindowsRunRootProbe.Instance.DriveOf(unused));
        Assert.Null(WindowsRunRootProbe.Instance.SubstituteOf(unused.Substring(0, 2)));
    }

    [Fact]
    public void TheWindowsProbeReadsAJunctionAsALinkAndItsTargetAsItsFinalPath()
    {
        string target = Path.Combine(_root, "target");
        Directory.CreateDirectory(target);
        string file = Path.Combine(_root, "notes.txt");
        File.WriteAllText(file, "fictional");
        string link = MakeJunction(Path.Combine(_root, "link"), target);

        Assert.Equal(RunRootEntry.Link, WindowsRunRootProbe.Instance.EntryOf(link));
        Assert.Equal(RunRootEntry.Folder, WindowsRunRootProbe.Instance.EntryOf(target));
        Assert.Equal(RunRootEntry.Other, WindowsRunRootProbe.Instance.EntryOf(file));
        Assert.Equal(RunRootEntry.Missing, WindowsRunRootProbe.Instance.EntryOf(Path.Combine(_root, "absent")));
        Assert.Equal(RunRootEntry.Missing, WindowsRunRootProbe.Instance.EntryOf(Path.Combine(_root, "absent", "deeper")));

        Assert.Equal(target, WindowsRunRootProbe.Instance.FinalPathOf(link), StringComparer.OrdinalIgnoreCase);
        Assert.Equal(target, WindowsRunRootProbe.Instance.FinalPathOf(target), StringComparer.OrdinalIgnoreCase);
        Assert.Null(WindowsRunRootProbe.Instance.FinalPathOf(Path.Combine(_root, "absent")));
    }

    /// <summary>
    /// The probe's full path is made from the text alone (the reviews' finding F1): an existing folder's 8.3
    /// short name stays as written - <c>Path.GetFullPath</c> reads the folder to expand it, which over a share
    /// goes over the network - while the separators and the dot segments are made canonical.
    /// </summary>
    [Fact]
    public void TheWindowsProbesFullPathReadsNothing()
    {
        string folder = Path.Combine(_root, "Long Folder Name For The Probe");
        Directory.CreateDirectory(Path.Combine(folder, "runs"));
        string shortName = ShortPathOf(folder);
        Assert.Contains("~", Path.GetFileName(shortName));

        Assert.Equal(shortName + @"\runs", WindowsRunRootProbe.Instance.FullPathOf(shortName + @"\runs"));
        Assert.Equal(@"C:\Fictional\work\runs", WindowsRunRootProbe.Instance.FullPathOf(@"C:/Fictional/other/../work/./runs"));
    }

    /// <summary>The probe's long-name form expands each short name of a folder's path, and is null for a folder not there.</summary>
    [Fact]
    public void TheWindowsProbeReadsAFoldersLongName()
    {
        string folder = Path.Combine(_root, "Long Folder Name For The Probe");
        Directory.CreateDirectory(folder);

        Assert.Equal(
            WindowsRunRootProbe.Instance.FinalPathOf(folder),
            WindowsRunRootProbe.Instance.LongPathOf(ShortPathOf(folder)),
            StringComparer.OrdinalIgnoreCase);
        Assert.Null(WindowsRunRootProbe.Instance.LongPathOf(Path.Combine(folder, "absent")));
    }

    /// <summary>
    /// What each <c>GetDriveType</c> answer is to the rule (the reviews' finding F4): only a remote drive is a
    /// mapped network drive, and only a root that is not there is no drive. This reading alone refuses the most
    /// common share, a mapped home drive, which no test here can make, so it is pinned answer by answer.
    /// </summary>
    [Theory]
    [InlineData(0u, RunRootDrive.Local)]
    [InlineData(1u, RunRootDrive.Missing)]
    [InlineData(2u, RunRootDrive.Local)]
    [InlineData(3u, RunRootDrive.Local)]
    [InlineData(4u, RunRootDrive.Network)]
    [InlineData(5u, RunRootDrive.Local)]
    [InlineData(6u, RunRootDrive.Local)]
    public void TheDriveKindIsReadFromWhatGetDriveTypeAnswers(uint driveType, RunRootDrive kind)
    {
        Assert.Equal(kind, WindowsRunRootProbe.DriveKindOf(driveType));
    }

    /// <summary>
    /// What a part is to the rule, from what its open and its attributes answer (the reviews' findings F2 and
    /// F4): not there is missing; an open that fails for any other reason - its attributes denied, a drive not
    /// ready, a reparse point no filter answers - or attributes that cannot be read leave it unreadable; a name
    /// surrogate is a link, a cloud file's folder is not; a folder is a folder, and anything else there is not
    /// one. Pinned answer by answer: the attributes failing to read on a handle opened to read them is one no
    /// test can make happen.
    /// </summary>
    [Theory]
    [InlineData(2, false, 0u, 0u, RunRootEntry.Missing)]
    [InlineData(3, false, 0u, 0u, RunRootEntry.Missing)]
    [InlineData(5, false, 0u, 0u, RunRootEntry.Unreadable)]
    [InlineData(21, false, 0u, 0u, RunRootEntry.Unreadable)]
    [InlineData(1920, false, 0u, 0u, RunRootEntry.Unreadable)]
    [InlineData(0, false, 0u, 0u, RunRootEntry.Unreadable)]
    [InlineData(0, true, 0x10u, 0u, RunRootEntry.Folder)]
    [InlineData(0, true, 0x410u, 0xA0000003u, RunRootEntry.Link)]
    [InlineData(0, true, 0x410u, 0xA000000Cu, RunRootEntry.Link)]
    [InlineData(0, true, 0x410u, 0x9000001Au, RunRootEntry.Folder)]
    [InlineData(0, true, 0x20u, 0u, RunRootEntry.Other)]
    [InlineData(0, true, 0x420u, 0xA000000Cu, RunRootEntry.Link)]
    public void ThePartIsReadFromWhatItsOpenAndItsAttributesAnswer(
        int openError, bool attributesRead, uint attributes, uint reparseTag, RunRootEntry entry)
    {
        Assert.Equal(
            entry,
            WindowsRunRootProbe.EntryKindOf(openError, attributesRead ? (attributes, reparseTag) : ((uint, uint)?)null));
    }

    /// <summary>
    /// What `QueryDosDevice` answers for a drive: <c>subst</c> defines the letter as <c>\??\</c> and the folder,
    /// a share's folder as <c>\??\UNC\</c>; a volume or a mapped network drive is a device, never a folder. The
    /// answer is a list - the mapping in force first - each item ending in a NUL.
    /// </summary>
    [Theory]
    [InlineData("\\??\\C:\\Fictional\\work\0\0", @"C:\Fictional\work")]
    [InlineData("\\??\\UNC\\fictional-server\\share\0\0", @"\\fictional-server\share")]
    [InlineData("\\??\\C:\\Fictional\\work\0\\??\\D:\\Older\0\0", @"C:\Fictional\work")]
    [InlineData("\\Device\\HarddiskVolume4\0\0", null)]
    [InlineData("\\Device\\LanmanRedirector\\;Z:000000000001a2b3\\fictional-server\\share\0\0", null)]
    [InlineData("\\Device\\Mup\\;Z:000000000001a2b3\\fictional-server\\share\0\0", null)]
    [InlineData("", null)]
    public void TheSubstitutedFolderIsReadFromWhatQueryDosDeviceAnswers(string answer, string? folder)
    {
        Assert.Equal(folder, WindowsRunRootProbe.SubstitutedFolder(answer));
    }

    // ---- helpers -----------------------------------------------------------------------------------------

    private static HashSet<string> Set(params string[] folders) =>
        new HashSet<string>(folders, StringComparer.OrdinalIgnoreCase);

    /// <summary>The <c>\\?\</c> form, which reaches a path past MAX_PATH.</summary>
    private static string Device(string path) => @"\\?\" + path;

    /// <summary>A junction made with <c>mklink /J</c>, which needs no rights; removed before the folder is.</summary>
    private string MakeJunction(string link, string target)
    {
        var start = new ProcessStartInfo("cmd.exe", $"/c mklink /J \"{Device(link)}\" \"{target}\"")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        using (Process process = Process.Start(start)!)
        {
            string output = process.StandardOutput.ReadToEnd() + process.StandardError.ReadToEnd();
            process.WaitForExit();
            Assert.True(process.ExitCode == 0, "mklink /J failed: " + output);
        }

        _junctions.Insert(0, link);
        Assert.True(
            (File.GetAttributes(Device(link)) & FileAttributes.ReparsePoint) != 0,
            "mklink /J did not make a junction at " + link);
        return link;
    }

    /// <summary>
    /// Denies the user running the tests <paramref name="rights"/> on <paramref name="folder"/>, on the folder
    /// alone; taken off again first thing on dispose, which an owner may always do.
    /// </summary>
    private void Deny(string folder, FileSystemRights rights)
    {
        var rule = new FileSystemAccessRule(
            WindowsIdentity.GetCurrent().User!, rights, InheritanceFlags.None, PropagationFlags.None, AccessControlType.Deny);
        DirectorySecurity security = Directory.GetAccessControl(folder);
        security.AddAccessRule(rule);
        Directory.SetAccessControl(folder, security);
        _denied.Insert(0, (folder, rule));
    }

    private const uint FsctlSetReparsePoint = 0x000900A4;

    private const uint FsctlDeleteReparsePoint = 0x000900AC;

    /// <summary>A fictional third-party reparse point's owner, as the tag's GUID.</summary>
    private static readonly Guid ReparseOwner = new Guid("5a1d0c4e-7f3b-4e2a-9c61-0d8e2b7f4a15");

    /// <summary>
    /// A folder carrying a third-party reparse point with <paramref name="tag"/> - a GUID buffer, which any
    /// user may set on a folder they can write - removed again before the folder is.
    /// </summary>
    private string MakeReparsePoint(string folder, uint tag)
    {
        Directory.CreateDirectory(folder);
        Assert.True(SetReparsePoint(folder, tag, FsctlSetReparsePoint, new byte[] { 1, 2, 3, 4 }),
            "the reparse point was not set: " + Marshal.GetLastWin32Error());
        _tagged.Insert(0, (folder, tag));
        return folder;
    }

    /// <summary>Sets or removes a third-party reparse point: <c>REPARSE_GUID_DATA_BUFFER</c>.</summary>
    private static bool SetReparsePoint(string folder, uint tag, uint control, byte[]? data)
    {
        byte[] payload = data ?? new byte[0];
        byte[] buffer = new byte[24 + payload.Length];
        BitConverter.GetBytes(tag).CopyTo(buffer, 0);
        BitConverter.GetBytes((ushort)payload.Length).CopyTo(buffer, 4);
        ReparseOwner.ToByteArray().CopyTo(buffer, 8);
        payload.CopyTo(buffer, 24);
        using (SafeFileHandle handle = CreateFile(
            Device(folder), GenericWrite, 0x7, IntPtr.Zero, 3, 0x02000000 | 0x00200000, IntPtr.Zero))
        {
            return !handle.IsInvalid
                && DeviceIoControl(handle, control, buffer, (uint)buffer.Length, IntPtr.Zero, 0, out _, IntPtr.Zero);
        }
    }

    private const uint GenericWrite = 0x40000000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "CreateFileW", SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName, uint desiredAccess, uint shareMode, IntPtr securityAttributes,
        uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DeviceIoControl(
        SafeFileHandle device, uint control, byte[] input, uint inputSize, IntPtr output, uint outputSize,
        out uint returned, IntPtr overlapped);

    private static string ShortPathOf(string path)
    {
        var buffer = new StringBuilder(1024);
        uint length = GetShortPathName(path, buffer, (uint)buffer.Capacity);
        Assert.True(length > 0 && length < buffer.Capacity, "GetShortPathName failed: " + Marshal.GetLastWin32Error());
        return buffer.ToString();
    }

    private static string UnusedDriveRoot()
    {
        string[] used = Directory.GetLogicalDrives();
        for (char letter = 'Q'; letter <= 'Y'; letter++)
        {
            string root = letter + @":\";
            if (!used.Contains(root, StringComparer.OrdinalIgnoreCase))
            {
                return root;
            }
        }

        throw new InvalidOperationException("no unused drive letter between Q and Y");
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetShortPathName(string longPath, StringBuilder shortPath, uint size);
}
