using System;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.AddIn.Remodel.Seat;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004, T155 (build order lane B): the extractor-side seat and the one way a copy is opened.
/// <c>OpenDoc7</c> with <c>Silent | LoadModel = 17</c> exactly, the flags read off the pinned
/// integer; the open and the close on a copy's path only; the three toggles and
/// <c>CommandInProgress</c> through the shared mapping; a fresh probe source for every probe; and
/// <c>GetVault</c> null, "not read by this build".
/// </summary>
public class SwRemodelBridgeSeatTests
{
    private static readonly string CopyPath = RemodelCopy.CopyPathFor(
        Path.Combine(Path.GetTempPath(), "swreview-seat", "20260927-100000-bracket-remodel"), "C:\\work\\bracket.SLDPRT");

    private readonly InteropRecorder<ISldWorks> _application = new InteropRecorder<ISldWorks>();
    private readonly InteropRecorder<IDocumentSpecification> _specification = new InteropRecorder<IDocumentSpecification>();
    private readonly StandInDocument _copy = new StandInDocument();

    public SwRemodelBridgeSeatTests()
    {
        _application.Answer("GetOpenDocSpec", _specification.Instance).Answer("OpenDoc7", _copy.Instance);
    }

    // ---- the open specification ------------------------------------------------------------------------

    /// <summary>The integer the flags are read off: Silent | LoadModel, and no bit a specification cannot state.</summary>
    [Fact]
    public void TheOpenOptionsAreSilentAndLoadModelAndNothingElse()
    {
        const int Statable =
            (int)swOpenDocOptions_e.swOpenDocOptions_Silent
            | (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly
            | (int)swOpenDocOptions_e.swOpenDocOptions_ViewOnly
            | (int)swOpenDocOptions_e.swOpenDocOptions_LoadModel;

        Assert.Equal(17, RemodelCopy.OpenOptions);
        Assert.Equal(0, RemodelCopy.OpenOptions & ~Statable);
    }

    [Fact]
    public void TheSpecificationIsAPartOpenedSilentlyWithItsModelLoadedAndNeverReadOnlyOrViewOnly()
    {
        IDocumentSpecification specification = CopyOpenSpecification.For(_application.Instance, CopyPath);

        Assert.Same(_specification.Instance, specification);
        Assert.Equal(new object?[] { CopyPath }, Assert.Single(_application.Calls).Arguments);
        Assert.Equal(
            new[]
            {
                ("set_DocumentType", (object?)(int)swDocumentTypes_e.swDocPART),
                ("set_Silent", (object?)true),
                ("set_ReadOnly", (object?)false),
                ("set_ViewOnly", (object?)false),
                ("set_LoadModel", (object?)true),
            },
            _specification.Calls.Select(call => (call.Member, Assert.Single(call.Arguments))));
    }

    [Fact]
    public void ASeatThatWillNotDescribeTheOpenRaisesNamingThePath()
    {
        _application.Answer("GetOpenDocSpec", null);

        InvalidOperationException refusal = Assert.Throws<InvalidOperationException>(() => CopyOpenSpecification.For(_application.Instance, CopyPath));
        Assert.Contains(CopyPath, refusal.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void TheSpecificationHelperRefusesMissingArguments()
    {
        Assert.Throws<ArgumentNullException>(() => CopyOpenSpecification.For(null!, CopyPath));
        Assert.Throws<ArgumentException>(() => CopyOpenSpecification.For(_application.Instance, " "));
        Assert.Throws<ArgumentNullException>(() => CopyOpenSpecification.Apply(null!));
        Assert.Empty(_application.Calls);
    }

    // ---- OpenDocument ------------------------------------------------------------------------------------

    [Fact]
    public void TheCopyIsOpenedWithOpenDoc7OverThatSpecificationAndAnsweredAsTheCopysAdapter()
    {
        IRemodelDocument? document = Seat().OpenDocument(CopyPath, RemodelCopy.OpenOptions);

        Assert.IsType<SwRemodelCopyDocument>(document);
        Assert.Equal(new[] { "GetOpenDocSpec", "OpenDoc7" }, _application.Members);
        Assert.Same(_specification.Instance, _application.Calls[1].Arguments[0]);

        // The adapter holds the document OpenDoc7 answered.
        _copy.Document.Answer("GetPathName", CopyPath);
        Assert.Equal(CopyPath, document!.GetPathName());
    }

    [Theory]
    [InlineData(1)]
    [InlineData(16)]
    [InlineData(17 | 2)]
    [InlineData(17 | 4)]
    [InlineData(0)]
    public void AnyOptionsButSilentAndLoadModelAreRefusedBeforeAnyCall(int options)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => Seat().OpenDocument(CopyPath, options));
        Assert.Empty(_application.Calls);
    }

    [Theory]
    [InlineData("C:\\work\\bracket.SLDPRT")]
    [InlineData("C:\\runs\\20260927-100000-bracket-remodel\\bracket-RMS.SLDPRT")]
    [InlineData("C:\\runs\\20260927-100000-bracket-remodel\\copy\\..\\..\\..\\work\\bracket.SLDPRT")]
    public void APathThatIsNotACopyIsNeitherOpenedNorClosed(string path)
    {
        Assert.Throws<ArgumentException>(() => Seat().OpenDocument(path, RemodelCopy.OpenOptions));
        Assert.Throws<ArgumentException>(() => Seat().CloseDocument(path));
        Assert.Empty(_application.Calls);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("  ")]
    public void ABlankPathIsNeitherOpenedNorClosed(string? path)
    {
        Assert.Throws<ArgumentException>(() => Seat().OpenDocument(path!, RemodelCopy.OpenOptions));
        Assert.Throws<ArgumentException>(() => Seat().CloseDocument(path!));
        Assert.Empty(_application.Calls);
    }

    /// <summary>A failed open says why, in the load errors' own names, and is the bridge's open_failed.</summary>
    [Fact]
    public void AnOpenThatAnswersNoDocumentRaisesOpenFailedNamingTheLoadErrors()
    {
        _application.Answer("OpenDoc7", null);
        _specification.Answer("get_Error", 2).Answer("get_Warning", 0);

        RemodelCopyError refusal = Assert.Throws<RemodelCopyError>(() => Seat().OpenDocument(CopyPath, RemodelCopy.OpenOptions));

        Assert.Equal(RemodelErrorCodes.OpenFailed, refusal.ErrorCode);
        Assert.Contains("swFileNotFoundError", refusal.Message, StringComparison.Ordinal);
        Assert.Contains(CopyPath, refusal.Message, StringComparison.Ordinal);
    }

    // ---- CloseDocument ------------------------------------------------------------------------------------

    [Fact]
    public void TheCopyIsClosedByItsPath()
    {
        Seat().CloseDocument(CopyPath);

        (string member, object?[] arguments) = Assert.Single(_application.Calls);
        Assert.Equal("CloseDoc", member);
        Assert.Equal(new object?[] { CopyPath }, arguments);
    }

    // ---- the probe source and the vault -----------------------------------------------------------------

    [Fact]
    public void EveryProbeGetsAFreshSourceAndBuildingOneAsksNothing()
    {
        SwRemodelBridgeSeat seat = Seat();

        IRemodelProbeSource first = seat.ProbeSource;
        IRemodelProbeSource second = seat.ProbeSource;

        Assert.IsType<SwRemodelProbeSource>(first);
        Assert.NotSame(first, second);
        Assert.Empty(_application.Calls);
    }

    [Theory]
    [InlineData("C:\\work\\bracket.SLDPRT")]
    [InlineData("C:\\vault\\Designs\\bracket.SLDPRT")]
    public void TheVaultIsNotReadByThisBuild(string sourcePath)
    {
        Assert.Null(Seat().GetVault(sourcePath));
        Assert.Empty(_application.Calls);
    }

    // ---- the toggles ---------------------------------------------------------------------------------------

    [Fact]
    public void TheTogglesAndCommandInProgressGoToTheApplication()
    {
        _application.Answer("GetUserPreferenceToggle", true).Answer("get_CommandInProgress", false);
        SwRemodelBridgeSeat seat = Seat();

        Assert.True(seat.GetUserPreferenceToggle(10));
        seat.SetUserPreferenceToggle(77, false);
        Assert.False(seat.GetCommandInProgress());
        seat.SetCommandInProgress(true);

        Assert.Equal(
            new[]
            {
                ("GetUserPreferenceToggle", new object?[] { 10 }),
                ("SetUserPreferenceToggle", new object?[] { 77, false }),
                ("get_CommandInProgress", new object?[0]),
                ("set_CommandInProgress", new object?[] { true }),
            },
            _application.Calls.Select(call => (call.Member, call.Arguments)));
    }

    /// <summary>
    /// The run's own set-and-restore, over the real seat: the four originals read, the four set, and
    /// the four put back, CommandInProgress last each time.
    /// </summary>
    [Fact]
    public void TheRunsSetAndRestoreReachesTheApplicationInOrder()
    {
        _application.Answer("GetUserPreferenceToggle", true).Answer("get_CommandInProgress", false);
        var gate = new SwReview.Extractor.Sw.SwGate(new SwReview.Extractor.Guard.CircuitBreaker(), new SwReview.Extractor.Guard.RemodelGuard());

        RemodelSystemToggles toggles = RemodelSystemToggles.Apply(Seat(), gate);
        toggles.Restore();

        Assert.Equal(
            new[]
            {
                "GetUserPreferenceToggle", "GetUserPreferenceToggle", "GetUserPreferenceToggle", "get_CommandInProgress",
                "SetUserPreferenceToggle", "SetUserPreferenceToggle", "SetUserPreferenceToggle", "set_CommandInProgress",
                "SetUserPreferenceToggle", "SetUserPreferenceToggle", "SetUserPreferenceToggle", "set_CommandInProgress",
            },
            _application.Members);
        Assert.Equal(new object?[] { true }, _application.Calls[7].Arguments);
        Assert.Equal(new object?[] { false }, _application.Calls[11].Arguments);
    }

    [Fact]
    public void TheSeatRefusesAMissingApplication()
    {
        Assert.Equal("swApp", Assert.Throws<ArgumentNullException>(() => new SwRemodelBridgeSeat(null!)).ParamName);
    }

    private SwRemodelBridgeSeat Seat() => new SwRemodelBridgeSeat(_application.Instance);
}
