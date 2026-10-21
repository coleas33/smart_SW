using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 154A (feature 002 T166, research 154A): a run root is acceptable only when it is a local
/// folder reached by its own path. The backend writes only into a local folder and refuses a UNC or device
/// path for every route, and it resolves the run folder it is sent, following a junction, a symbolic link, a
/// substituted drive or a mapped network drive, where the add-in binds its own spelling - so under a run root
/// on a share nothing can run, and under one reached through a link the re-modeler's copy is refused at its
/// open (feature 011 research R12.9, items 1 and 2). The rule names such a root before any run is begun.
///
/// What it refuses, and in what order, so that nothing is ever opened over the network or through a link:
/// a root written as a UNC or device path, on sight; a mapped network drive and a substituted drive, by what
/// Windows says of the drive letter; a junction or symbolic link among the folders that exist, by what each is,
/// never by opening through it; and any root whose final path - the nearest existing folder's, which is what
/// the backend's own resolution reads - differs from its full path other than by letter case. A root that does
/// not exist yet is judged by its nearest existing folder. A root the rule cannot read at all - blank, with no
/// full form, on a drive that is not there - is left to the run folder, which reports it as before.
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

    public RunRootRuleTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.RunRootRule.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        // A tagged folder's reparse point first, which no filter answers, so the folder can be removed.
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

    /// <summary>A final path that cannot be read is no reason to refuse: the rule refuses what it can name.</summary>
    [Fact]
    public void AFinalPathThatCannotBeReadIsNoReasonToRefuse()
    {
        var probe = new FakeRunRootProbe();
        probe.FinalPaths[Fictional + @"\work\runs"] = null;

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Fictional + @"\work\runs", probe));
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
    [InlineData(@"C:\Fictional\a:b")]
    [InlineData(@"C:\Fictional\x<y")]
    public void ARootTheRuleCannotReadIsLeftToTheRunFolder(string? runRoot)
    {
        FakeRunRootProbe probe = FakeRunRootProbe.Local();

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(runRoot, probe));
        Assert.Empty(probe.Asked);
    }

    [Fact]
    public void ARootOnADriveThatIsNotThereIsLeftToTheRunFolder()
    {
        var probe = new FakeRunRootProbe();
        probe.Drives[@"Q:\"] = RunRootDrive.Missing;

        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(@"Q:\Fictional\runs", probe));
        Assert.Equal(new[] { @"DriveOf Q:\" }, probe.Asked);
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
    /// words named the settings file and a restart of SOLIDWORKS. Changed deliberately for that.
    /// </summary>
    [Theory]
    [InlineData(
        RunRootVerdict.Share,
        "The run root is on a network share or a mapped network drive, and runs are made only in a local folder "
        + "reached by its own path, so nothing was checked. Choose a local folder for runs in Settings, then "
        + "press Model check again.")]
    [InlineData(
        RunRootVerdict.Link,
        "The run root is reached through a link, such as a junction, a symbolic link or a substituted drive, and "
        + "runs are made only in a local folder reached by its own path, so nothing was checked. Choose a local "
        + "folder for runs in Settings, then press Model check again.")]
    [InlineData(
        RunRootVerdict.DevicePath,
        "The run root is written as a Windows device path, and runs are made only in a local folder reached by "
        + "its own path, so nothing was checked. Choose a local folder for runs in Settings, then press Model "
        + "check again.")]
    public void TheRefusalSaysWhatIsTrueOfTheRootTheRuleAndTheWayOn(RunRootVerdict verdict, string words)
    {
        Assert.Equal(words, RunRootRule.Refusal(verdict, "nothing was checked", "press Model check again"));
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
    public void ASaveSaysTheRunRootItLeavesInForceIsRefused(RunRootVerdict verdict, string words)
    {
        Assert.Equal(words, RunRootRule.KeptRefusal(verdict));
    }

    [Fact]
    public void ThereAreNoWordsForARootTheRuleAccepts()
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => RunRootRule.Refusal(RunRootVerdict.Accepted, "nothing was checked", "press Model check again"));
        Assert.Throws<ArgumentOutOfRangeException>(() => RunRootRule.ChosenRefusal(RunRootVerdict.Accepted));
        Assert.Throws<ArgumentOutOfRangeException>(() => RunRootRule.KeptRefusal(RunRootVerdict.Accepted));
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
    /// Another letter case is the same folder, and so is an 8.3 short name, which the full form expands: neither
    /// is a link. The short name is the one Windows gave the folder, so the case is not vacuous.
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
    /// A reparse point is a link only when it names another path - a name surrogate: a junction, a symbolic
    /// link, a mount point. A cloud file's folder - a OneDrive folder, which Known Folder Move makes of
    /// Documents and with it of the default run root - carries one that names no other path, and is not
    /// refused for it. Made for real with a third-party tag, which needs no rights: one without the surrogate
    /// bit, as a cloud file's, and the same tag with it. No filter answers either tag, so nothing below them
    /// opens: the first is judged by itself, the folder whose final path cannot be read, and accepted.
    /// </summary>
    [Fact]
    public void AReparsePointIsALinkOnlyWhenItNamesAnotherPath()
    {
        string plain = MakeReparsePoint(Path.Combine(_root, "cloud"), 0x00001234);
        string surrogate = MakeReparsePoint(Path.Combine(_root, "elsewhere"), 0x20001234);

        Assert.Equal(RunRootEntry.Folder, WindowsRunRootProbe.Instance.EntryOf(plain));
        Assert.Equal(RunRootEntry.Link, WindowsRunRootProbe.Instance.EntryOf(surrogate));
        Assert.Equal(RunRootVerdict.Accepted, RunRootRule.Judge(Path.Combine(plain, "runs"), WindowsRunRootProbe.Instance));
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
