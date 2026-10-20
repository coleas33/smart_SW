using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004 T159 (build order lane E) and owner decision 144A (feature 011 T163, research R11):
/// <see cref="SwRemodelSeat"/>, the re-modeler's pane seat - <c>remodel.open_copy</c>
/// (<see cref="SwRemodelSeat.ActivateOrOpen"/>) and the activation both dumps make
/// (<see cref="SwRemodelSeat.ActivateOpenCopy"/>) - over the recording stand-ins: no COM object
/// exists and SOLIDWORKS is never started.
///
/// What it must do is small and exact. Find the copy among the documents SOLIDWORKS already has open,
/// confirm the document found is the run's copy, and activate it by its title without a rebuild; for
/// <c>remodel.open_copy</c>, open it again when SOLIDWORKS does not have it - writable, through the
/// one open request (<c>Silent | LoadModel = 17</c>, never <c>ReadOnly</c> or <c>ViewOnly</c>), for
/// the engineer's Save As - and confirm the document opened is the copy; all on the application
/// thread. What it must never do is reach SOLIDWORKS except through its gate, whose guard
/// (<see cref="RemodelSeatGuard"/>) allows <c>ISldWorks.ActivateDoc3</c> and <c>ISldWorks.OpenDoc7</c>
/// by their qualified keys and hands every bare read to the read-only guard; open anything for a dump;
/// or touch a document that is not the run's copy.
///
/// The seat runs only on the pilot workstation, so these list exactly the calls it makes: the gate's
/// journal places every interop call under the gate entry it was made under, and a call made outside
/// the gate, or one more than listed, fails here rather than at the seat.
/// </summary>
public sealed class SwRemodelSeatTests
{
    private const string CopyTitle = "bracket-RMS.SLDPRT";

    private const string SourcePath = "C:\\work\\bracket.SLDPRT";

    private static readonly string RunDirectory =
        Path.Combine(Path.GetTempPath(), "swreview-seat", "20260927-100000-bracket-remodel");

    private static readonly string CopyPath = RemodelCopy.CopyPathFor(RunDirectory, SourcePath);

    private readonly InteropRecorder<ISldWorks> _application = new InteropRecorder<ISldWorks>();
    private readonly StandInDocument _copy = new StandInDocument();
    private readonly StandInDocument _other = new StandInDocument();
    private readonly InteropRecorder<IDocumentSpecification> _request = new InteropRecorder<IDocumentSpecification>();
    private readonly RecordingThread _thread = new RecordingThread();
    private readonly List<(string RunDirectory, string Line, bool OnTheApplicationThread)> _log =
        new List<(string, string, bool)>();

    private readonly GateJournal _journal;

    public SwRemodelSeatTests()
    {
        _copy.Document.Answer("GetTitle", CopyTitle).Answer("GetPathName", CopyPath);
        _other.Document.Answer("GetTitle", "bracket.SLDPRT").Answer("GetPathName", SourcePath);
        _application
            .Answer("GetOpenDocumentByName", _copy.Instance)
            .Answer("ActivateDoc3", _copy.Instance)
            .Answer("get_ActiveDoc", _copy.Instance)
            .Answer("GetOpenDocSpec", _request.Instance)
            .Answer("OpenDoc7", _copy.Instance);

        _journal = new GateJournal(
            ("ISldWorks", _application),
            ("copy", _copy.Document),
            ("other", _other.Document),
            ("request", _request));
    }

    // ---- ActivateOpenCopy: the activation before each dump (004 T159) --------------------------------

    /// <summary>
    /// Edited deliberately for decision 144A (feature 011 T163): the copy is now asked its path before
    /// it is activated, so its calls read <c>GetPathName</c>, <c>GetTitle</c>, <c>GetPathName</c> where
    /// they read <c>GetTitle</c>, <c>GetPathName</c> - the seat activates only a document it has shown
    /// to be the run's copy. Every other assertion is as it was.
    /// </summary>
    [Fact]
    public void TheOpenCopyIsActivatedByItsTitleWithNoRebuildAndTheActivePathIsAnswered()
    {
        string? active = Seat().ActivateOpenCopy(CopyPath);

        Assert.Equal(CopyPath, active);
        Assert.Equal(new[] { "GetOpenDocumentByName", "ActivateDoc3", "get_ActiveDoc" }, _application.Members);
        Assert.Equal(new object?[] { CopyPath }, _application.Calls[0].Arguments);
        Assert.Equal(
            new object?[] { CopyTitle, false, (int)swRebuildOnActivation_e.swDontRebuildActiveDoc, 0 },
            _application.Calls[1].Arguments);
        Assert.Equal(new[] { "GetPathName", "GetTitle", "GetPathName" }, _copy.Document.Members);
    }

    /// <summary>
    /// Refused rather than opened: SOLIDWORKS does not have the copy open, so nothing is
    /// activated, no open is asked for and nothing else is read.
    /// </summary>
    [Fact]
    public void ACopySolidworksDoesNotHaveOpenIsNeitherActivatedNorOpened()
    {
        _application.Answer("GetOpenDocumentByName", null);

        Assert.Null(Seat().ActivateOpenCopy(CopyPath));

        Assert.Equal(new[] { "GetOpenDocumentByName" }, _application.Members);
        Assert.Empty(_copy.Document.Calls);
    }

    /// <summary>An activation SOLIDWORKS answers with no document activated nothing, and says so.</summary>
    [Fact]
    public void AnActivationThatAnswersNoDocumentAnswersNull()
    {
        _application.Handle("ActivateDoc3", arguments =>
        {
            arguments[3] = (int)swActivateDocError_e.swGenericActivateError;
            return null;
        });

        Assert.Null(Seat().ActivateOpenCopy(CopyPath));

        Assert.Equal(new[] { "GetOpenDocumentByName", "ActivateDoc3" }, _application.Members);
    }

    /// <summary>
    /// `ActivateDoc3`'s error bits do not decide on their own: a document that needs a rebuild
    /// is still activated - without one, as asked - and the active document's path is the answer.
    /// </summary>
    [Fact]
    public void ARebuildWarningDoesNotDecideTheActiveDocumentDoes()
    {
        _application.Handle("ActivateDoc3", arguments =>
        {
            arguments[3] = (int)swActivateDocError_e.swDocNeedsRebuildWarning;
            return _copy.Instance;
        });

        Assert.Equal(CopyPath, Seat().ActivateOpenCopy(CopyPath));
    }

    /// <summary>
    /// Whatever SOLIDWORKS has active afterwards is answered as it is - here the engineer's own
    /// part - for the pipeline to refuse; the seat does not judge it.
    /// </summary>
    [Fact]
    public void WhateverIsActiveAfterwardsIsAnsweredAsItIs()
    {
        _application.Answer("get_ActiveDoc", _other.Instance);

        Assert.Equal(SourcePath, Seat().ActivateOpenCopy(CopyPath));
    }

    [Fact]
    public void NoActiveDocumentAfterwardsAnswersNull()
    {
        _application.Answer("get_ActiveDoc", null);

        Assert.Null(Seat().ActivateOpenCopy(CopyPath));
    }

    /// <summary>Every call is made inside one hop onto the application thread, and none outside it.</summary>
    [Fact]
    public void EveryCallIsMadeOnTheApplicationThread()
    {
        bool outside = false;
        _application.Handle("GetOpenDocumentByName", _ =>
        {
            outside |= !_thread.Inside;
            return _copy.Instance;
        });
        _application.Handle("get_ActiveDoc", _ =>
        {
            outside |= !_thread.Inside;
            return _copy.Instance;
        });

        Seat().ActivateOpenCopy(CopyPath);

        Assert.Equal(1, _thread.Invocations);
        Assert.False(outside);
    }

    /// <summary>
    /// Whatever SOLIDWORKS answers, no open is ever asked for: not the open request, not
    /// `OpenDoc7`, and not `remodel.open_copy`'s fallback.
    /// </summary>
    [Theory]
    [InlineData("the copy is open")]
    [InlineData("the copy is not open")]
    [InlineData("the activation answers nothing")]
    [InlineData("another document is active")]
    [InlineData("the lookup answers another document")]
    public void NoOpenIsEverAskedFor(string state)
    {
        switch (state)
        {
            case "the copy is not open":
                _application.Answer("GetOpenDocumentByName", null);
                break;
            case "the activation answers nothing":
                _application.Answer("ActivateDoc3", null);
                break;
            case "another document is active":
                _application.Answer("get_ActiveDoc", new StandInDocument().Instance);
                break;
            case "the lookup answers another document":
                _application.Answer("GetOpenDocumentByName", _other.Instance);
                break;
        }

        Seat().ActivateOpenCopy(CopyPath);

        Assert.DoesNotContain("OpenDoc7", _application.Members);
        Assert.DoesNotContain("GetOpenDocSpec", _application.Members);
        Assert.DoesNotContain(_application.Members, member => member.StartsWith("OpenDoc", StringComparison.Ordinal));
    }

    [Fact]
    public void ANullPathIsRefusedBeforeAnyCall()
    {
        Assert.Throws<ArgumentNullException>(() => Seat().ActivateOpenCopy(null!));

        Assert.Empty(_application.Calls);
        Assert.Equal(0, _thread.Invocations);
        Assert.Empty(_log);
    }

    /// <summary>
    /// Decision 144A: every call of the activation goes through the seat's gate, one gate entry per
    /// interop call, in this order - the lookup, the copy's path, its title, the activation by the
    /// qualified key, the active document and its path - and the gate log says so in one line of the
    /// run folder's <c>remodel.log</c>, with nothing refused.
    /// </summary>
    [Fact]
    public void ActivateOpenCopy_EveryCallGoesThroughTheSeatsGateAndTheLogSaysSo()
    {
        Seat().ActivateOpenCopy(CopyPath);

        Assert.Equal(
            new[]
            {
                "gate GetOpenDocumentByName", "ISldWorks.GetOpenDocumentByName",
                "gate GetPathName", "copy.GetPathName",
                "gate GetTitle", "copy.GetTitle",
                "gate ISldWorks.ActivateDoc3", "ISldWorks.ActivateDoc3",
                "gate ActiveDoc", "ISldWorks.get_ActiveDoc",
                "gate GetPathName", "copy.GetPathName",
            },
            _journal.Timeline());
        Assert.Empty(_journal.Refusals);
        Assert.Equal(
            (RunDirectory,
             "seat=activate_before_dump status=ok gated=GetOpenDocumentByName,GetPathName,GetTitle,ISldWorks.ActivateDoc3,ActiveDoc",
             true),
            Assert.Single(_log));
    }

    /// <summary>
    /// Decision 144A, the copy's scope: a document the lookup answers that is not at the copy's path is
    /// not the run's copy, so it is neither asked its title nor activated, and the answer is null, as
    /// for a copy SOLIDWORKS does not have open; the pipeline refuses the dump.
    /// </summary>
    [Fact]
    public void ActivateOpenCopy_ADocumentThatIsNotTheCopyIsNeitherActivatedNorAskedItsTitle()
    {
        _application.Answer("GetOpenDocumentByName", _other.Instance);

        Assert.Null(Seat().ActivateOpenCopy(CopyPath));

        Assert.Equal(
            new[] { "gate GetOpenDocumentByName", "ISldWorks.GetOpenDocumentByName", "gate GetPathName", "other.GetPathName" },
            _journal.Timeline());
        Assert.Equal(new[] { "GetPathName" }, _other.Document.Members);
        Assert.Equal(
            "seat=activate_before_dump status=ok gated=GetOpenDocumentByName,GetPathName",
            Assert.Single(_log).Line);
    }

    // ---- ActivateOrOpen: remodel.open_copy (decision 144A's seat-level tests) ---------------------

    /// <summary>
    /// The copy SOLIDWORKS has open is confirmed to be the copy, then activated by its title, the user's
    /// preferences not consulted and with no rebuild; nothing is opened and nothing else is read.
    /// </summary>
    [Fact]
    public void ActivateOrOpen_AnOpenCopyIsActivatedByItsTitleWithNoRebuildAndNothingIsOpened()
    {
        Seat().ActivateOrOpen(CopyPath);

        Assert.Equal(
            new[]
            {
                "gate GetOpenDocumentByName", "ISldWorks.GetOpenDocumentByName",
                "gate GetPathName", "copy.GetPathName",
                "gate GetTitle", "copy.GetTitle",
                "gate ISldWorks.ActivateDoc3", "ISldWorks.ActivateDoc3",
            },
            _journal.Timeline());
        Assert.Equal(new object?[] { CopyPath }, _application.Calls[0].Arguments);
        Assert.Equal(
            new object?[] { CopyTitle, false, (int)swRebuildOnActivation_e.swDontRebuildActiveDoc, 0 },
            _application.Calls[1].Arguments);
        Assert.Empty(_request.Calls);
        Assert.Empty(_journal.Refusals);
        Assert.Equal(
            (RunDirectory, "seat=open_copy status=ok gated=GetOpenDocumentByName,GetPathName,GetTitle,ISldWorks.ActivateDoc3", true),
            Assert.Single(_log));
    }

    /// <summary>
    /// The writable open: a copy SOLIDWORKS does not have open is opened again through the one open
    /// request, built inside the gate entry that asks for it, handed to <c>OpenDoc7</c> under its
    /// qualified key, and the document opened is confirmed to be the copy. Nothing is activated.
    /// </summary>
    [Fact]
    public void ActivateOrOpen_AClosedCopyIsOpenedAgainThroughTheOneOpenRequest()
    {
        _application.Answer("GetOpenDocumentByName", null);

        Seat().ActivateOrOpen(CopyPath);

        Assert.Equal(
            new[]
            {
                "gate GetOpenDocumentByName", "ISldWorks.GetOpenDocumentByName",
                "gate GetOpenDocSpec", "ISldWorks.GetOpenDocSpec",
                "request.set_DocumentType", "request.set_Silent", "request.set_ReadOnly", "request.set_ViewOnly",
                "request.set_LoadModel",
                "gate ISldWorks.OpenDoc7", "ISldWorks.OpenDoc7",
                "gate GetPathName", "copy.GetPathName",
            },
            _journal.Timeline());
        Assert.Equal(new object?[] { CopyPath }, _application.Calls[1].Arguments);
        Assert.Same(_request.Instance, Assert.Single(_application.Calls[2].Arguments));
        Assert.DoesNotContain("ActivateDoc3", _application.Members);
        Assert.Empty(_journal.Refusals);
        Assert.Equal(
            (RunDirectory, "seat=open_copy status=ok gated=GetOpenDocumentByName,GetOpenDocSpec,ISldWorks.OpenDoc7,GetPathName", true),
            Assert.Single(_log));
    }

    /// <summary>
    /// The open options, asserted as the values set and as the integer they compose: a part,
    /// <c>Silent</c> and <c>LoadModel</c> - <c>RemodelCopy.OpenOptions</c>, 17 - and never
    /// <c>ReadOnly</c> (2) or <c>ViewOnly</c> (4), because the copy opens writable for the engineer's
    /// Save As.
    /// </summary>
    [Fact]
    public void ActivateOrOpen_TheCopyOpensSilentAndLoadModelAndNeverReadOnlyOrViewOnly()
    {
        _application.Answer("GetOpenDocumentByName", null);

        Seat().ActivateOrOpen(CopyPath);

        var set = _request.Calls.ToDictionary(call => call.Member, call => Assert.Single(call.Arguments));
        Assert.Equal((int)swDocumentTypes_e.swDocPART, set["set_DocumentType"]);
        Assert.Equal(true, set["set_Silent"]);
        Assert.Equal(true, set["set_LoadModel"]);
        Assert.Equal(false, set["set_ReadOnly"]);
        Assert.Equal(false, set["set_ViewOnly"]);

        int composed = ((bool)set["set_Silent"]! ? (int)swOpenDocOptions_e.swOpenDocOptions_Silent : 0)
            | ((bool)set["set_ReadOnly"]! ? (int)swOpenDocOptions_e.swOpenDocOptions_ReadOnly : 0)
            | ((bool)set["set_ViewOnly"]! ? (int)swOpenDocOptions_e.swOpenDocOptions_ViewOnly : 0)
            | ((bool)set["set_LoadModel"]! ? (int)swOpenDocOptions_e.swOpenDocOptions_LoadModel : 0);
        Assert.Equal(17, composed);
        Assert.Equal(RemodelCopy.OpenOptions, composed);
    }

    /// <summary>
    /// An open SOLIDWORKS answers with no document is refused naming the copy and the load error and
    /// warning bits, read off the request inside the open's own gate entry; the log says it failed.
    /// </summary>
    [Fact]
    public void ActivateOrOpen_AnOpenThatAnswersNoDocumentIsRefusedNamingTheLoadErrors()
    {
        _application.Answer("GetOpenDocumentByName", null).Answer("OpenDoc7", null);
        _request
            .Answer("get_Error", (int)swFileLoadError_e.swFileNotFoundError)
            .Answer("get_Warning", (int)swFileLoadWarning_e.swFileLoadWarning_ReadOnly);

        var refusal = Assert.Throws<InvalidOperationException>(() => Seat().ActivateOrOpen(CopyPath));

        Assert.Contains(CopyPath, refusal.Message, StringComparison.Ordinal);
        Assert.Contains(
            FileLoadErrors.Describe(
                (int)swFileLoadError_e.swFileNotFoundError, (int)swFileLoadWarning_e.swFileLoadWarning_ReadOnly),
            refusal.Message,
            StringComparison.Ordinal);
        Assert.Equal(
            new[] { "gate ISldWorks.OpenDoc7", "ISldWorks.OpenDoc7", "request.get_Error", "request.get_Warning" },
            _journal.Timeline().SkipWhile(entry => entry != "gate ISldWorks.OpenDoc7"));
        Assert.Equal(
            "seat=open_copy status=error gated=GetOpenDocumentByName,GetOpenDocSpec,ISldWorks.OpenDoc7 error=InvalidOperationException",
            Assert.Single(_log).Line);
    }

    /// <summary>
    /// Decision 144A, the copy's scope: an open that answers a document that is not at the copy's path -
    /// one SOLIDWORKS already had open under the copy's title, say - is refused, and that document,
    /// perhaps the engineer's, is left exactly as it is: not activated, not closed, not named.
    /// </summary>
    [Fact]
    public void ActivateOrOpen_AnOpenThatAnswersAnotherDocumentIsRefusedAndThatDocumentIsLeftAlone()
    {
        _application.Answer("GetOpenDocumentByName", null).Answer("OpenDoc7", _other.Instance);

        var refusal = Assert.Throws<InvalidOperationException>(() => Seat().ActivateOrOpen(CopyPath));

        Assert.Contains(CopyPath, refusal.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(SourcePath, refusal.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(new[] { "GetOpenDocumentByName", "GetOpenDocSpec", "OpenDoc7" }, _application.Members);
        Assert.Equal(new[] { "GetPathName" }, _other.Document.Members);
        Assert.Equal(
            "seat=open_copy status=error gated=GetOpenDocumentByName,GetOpenDocSpec,ISldWorks.OpenDoc7,GetPathName error=InvalidOperationException",
            Assert.Single(_log).Line);
    }

    /// <summary>
    /// Decision 144A, the copy's scope: a document the lookup answers that is not at the copy's path is
    /// not the run's copy. It is neither asked its title nor activated, and nothing is opened in its
    /// place - SOLIDWORKS answered the copy's path with it - and the refusal does not name it.
    /// </summary>
    [Fact]
    public void ActivateOrOpen_ALookupThatAnswersAnotherDocumentIsRefusedAndNothingIsActivatedOrOpened()
    {
        _application.Answer("GetOpenDocumentByName", _other.Instance);

        var refusal = Assert.Throws<InvalidOperationException>(() => Seat().ActivateOrOpen(CopyPath));

        Assert.Contains(CopyPath, refusal.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(SourcePath, refusal.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(new[] { "GetOpenDocumentByName" }, _application.Members);
        Assert.Equal(new[] { "GetPathName" }, _other.Document.Members);
        Assert.Empty(_request.Calls);
        Assert.Equal(
            "seat=open_copy status=error gated=GetOpenDocumentByName,GetPathName error=InvalidOperationException",
            Assert.Single(_log).Line);
    }

    /// <summary>An activation SOLIDWORKS refuses, or answers with error bits, is an error naming what it reported.</summary>
    [Theory]
    [InlineData(false, (int)swActivateDocError_e.swGenericActivateError)]
    [InlineData(true, (int)swActivateDocError_e.swDocNeedsRebuildWarning)]
    public void ActivateOrOpen_AnActivationThatFailsIsAnErrorNamingWhatSolidworksReported(bool answersTheCopy, int errors)
    {
        _application.Handle("ActivateDoc3", arguments =>
        {
            arguments[3] = errors;
            return answersTheCopy ? _copy.Instance : null;
        });

        var refusal = Assert.Throws<InvalidOperationException>(() => Seat().ActivateOrOpen(CopyPath));

        Assert.Contains(CopyPath, refusal.Message, StringComparison.Ordinal);
        Assert.Contains("ActivateDoc3 reported " + errors, refusal.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("OpenDoc7", _application.Members);
        Assert.Equal(
            "seat=open_copy status=error gated=GetOpenDocumentByName,GetPathName,GetTitle,ISldWorks.ActivateDoc3 error=InvalidOperationException",
            Assert.Single(_log).Line);
    }

    /// <summary>Both ways, every call and the log line are made inside one hop onto the application thread.</summary>
    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ActivateOrOpen_EveryCallAndTheLogAreMadeInOneHopOntoTheApplicationThread(bool copyIsOpen)
    {
        bool outside = false;
        _application.Handle("GetOpenDocumentByName", _ =>
        {
            outside |= !_thread.Inside;
            return copyIsOpen ? _copy.Instance : null;
        });
        _application.Handle("ActivateDoc3", _ =>
        {
            outside |= !_thread.Inside;
            return _copy.Instance;
        });
        _application.Handle("OpenDoc7", _ =>
        {
            outside |= !_thread.Inside;
            return _copy.Instance;
        });

        Seat().ActivateOrOpen(CopyPath);

        Assert.Equal(1, _thread.Invocations);
        Assert.False(outside);
        Assert.True(Assert.Single(_log).OnTheApplicationThread);
    }

    [Fact]
    public void ActivateOrOpen_ANullPathIsRefusedBeforeAnyCall()
    {
        Assert.Throws<ArgumentNullException>(() => Seat().ActivateOrOpen(null!));

        Assert.Empty(_application.Calls);
        Assert.Equal(0, _thread.Invocations);
        Assert.Empty(_log);
    }

    /// <summary>
    /// Decision 144A, the copy's scope: both actions take only the run's copy - a rooted part inside a
    /// run folder's <c>copy/</c> (<c>RemodelCopy.RunDirectoryOf</c>'s rule) - and refuse any other path
    /// before SOLIDWORKS is asked anything, with no hop and no log line: the engineer's part, an assembly
    /// or a drawing in a <c>copy/</c> folder, a part in any other folder, a path that is not rooted, and
    /// an empty one.
    /// </summary>
    [Theory]
    [MemberData(nameof(PathsThatAreNotARunsCopy))]
    public void APathThatIsNotARunsCopyIsRefusedBeforeAnyCall(string path, bool open)
    {
        SwRemodelSeat seat = Seat();
        Action act = open ? () => seat.ActivateOrOpen(path) : () => seat.ActivateOpenCopy(path);

        Assert.ThrowsAny<ArgumentException>(act);

        Assert.Empty(_application.Calls);
        Assert.Equal(0, _thread.Invocations);
        Assert.Empty(_log);
    }

    public static IEnumerable<object[]> PathsThatAreNotARunsCopy()
    {
        string copyFolder = Path.Combine(RunDirectory, RemodelCopy.CopyFolderName);
        string[] paths =
        {
            SourcePath,
            Path.Combine(copyFolder, "bracket-RMS.SLDASM"),
            Path.Combine(copyFolder, "bracket-RMS.SLDDRW"),
            Path.Combine(RunDirectory, "elsewhere", "bracket-RMS.SLDPRT"),
            Path.Combine(RunDirectory, "bracket-RMS.SLDPRT"),
            Path.Combine(RemodelCopy.CopyFolderName, "bracket-RMS.SLDPRT"),
            string.Empty,
            "   ",
        };

        return paths.SelectMany(path => new[] { new object[] { path, true }, new object[] { path, false } });
    }

    // ---- the seat's gate and its log -------------------------------------------------------------

    /// <summary>
    /// The gate each action builds is the seat's own: its two keys and the bare reads pass, and any
    /// other qualified key, or a bare name the read-only guard refuses, is refused and told to the
    /// observer - so a call outside the allowlist cannot reach SOLIDWORKS from the seat.
    /// </summary>
    [Fact]
    public void TheSeatsGateAllowsItsTwoKeysAndTheReadsAndRefusesAnyOtherCall()
    {
        var observer = new RecordingGateObserver();
        SwGate gate = SwRemodelSeat.Gate(observer);

        foreach (string allowed in new[]
                 {
                     "ISldWorks.ActivateDoc3", "ISldWorks.OpenDoc7", "GetOpenDocumentByName", "GetPathName", "GetTitle",
                     "ActiveDoc", "GetOpenDocSpec",
                 })
        {
            Assert.True(gate.Call(allowed, () => true), allowed);
        }

        string[] refused =
        {
            "ISldWorks.CloseDoc", "ISldWorks.OpenDoc6", "ISldWorks.CloseAllDocuments", "ISldWorks.IActivateDoc3",
            "ISldWorks.ActivateDoc2", "IModelDoc2.Save3", "IModelDoc2.ForceRebuild3", "IModelDoc2.GetPathName",
            "isldworks.activatedoc3", "ActivateDoc3", "Save3", "SaveAs", "ForceRebuild3", "CloseAllDocuments",
        };
        foreach (string key in refused)
        {
            bool reached = false;
            Assert.Throws<MutatingCallError>(() => gate.Call(key, () => reached = true));
            Assert.False(reached, key);
        }

        Assert.Equal(refused, observer.Refusals.Select(refusal => refusal.MemberName));
    }

    /// <summary>A log that cannot be written fails nothing: the action answers as it would, and a failed one throws its own error.</summary>
    [Fact]
    public void ALogThatCannotBeWrittenFailsNothing()
    {
        var seat = new SwRemodelSeat(
            _application.Instance, _thread, _journal, (_, _) => throw new IOException("the run folder is gone"));

        Assert.Equal(CopyPath, seat.ActivateOpenCopy(CopyPath));
        seat.ActivateOrOpen(CopyPath);

        _application.Answer("GetOpenDocumentByName", null).Answer("OpenDoc7", null);
        Assert.Throws<InvalidOperationException>(() => seat.ActivateOrOpen(CopyPath));
    }

    /// <summary>The line names the action, the status and the distinct members gated, in the order first seen.</summary>
    [Fact]
    public void TheGateLogLineNamesTheActionTheStatusAndEachMemberOnceInTheOrderFirstSeen()
    {
        var log = new RemodelSeatGateLog(null);
        foreach (string member in new[] { "GetOpenDocumentByName", "GetPathName", "GetTitle", "getpathname", "ISldWorks.ActivateDoc3" })
        {
            log.Gated(member);
        }

        Assert.Equal(
            "seat=open_copy status=ok gated=GetOpenDocumentByName,GetPathName,GetTitle,ISldWorks.ActivateDoc3",
            log.Line(SwRemodelSeat.OpenCopyAction, null));
        Assert.Equal("seat=open_copy status=ok gated=", log.Line(SwRemodelSeat.OpenCopyAction, null));
    }

    /// <summary>
    /// A refusal is named in <c>refused=</c>, and a failure by its exception's type alone: a message can
    /// quote a path, and the run folder's log names no document.
    /// </summary>
    [Fact]
    public void TheGateLogLineNamesARefusalAndAFailureByItsTypeOnly()
    {
        var also = new RecordingGateObserver();
        var log = new RemodelSeatGateLog(also);
        var refusal = new MutatingCallError("ISldWorks.CloseDoc", "ISldWorks.CloseDoc is not on the allowlist.");
        log.Gated("GetOpenDocumentByName");
        log.Gated("ISldWorks.CloseDoc");
        log.Refused(refusal);

        string line = log.Line(
            SwRemodelSeat.ActivateBeforeDumpAction,
            new InvalidOperationException("SOLIDWORKS would not open 'C:\\work\\bracket.SLDPRT'."));

        Assert.Equal(
            "seat=activate_before_dump status=error gated=GetOpenDocumentByName,ISldWorks.CloseDoc "
            + "refused=ISldWorks.CloseDoc error=InvalidOperationException",
            line);
        Assert.Equal(new[] { "GetOpenDocumentByName", "ISldWorks.CloseDoc" }, also.Members);
        Assert.Same(refusal, Assert.Single(also.Refusals));
    }

    private SwRemodelSeat Seat() =>
        new SwRemodelSeat(
            _application.Instance,
            _thread,
            _journal,
            (runDirectory, line) => _log.Add((runDirectory, line, _thread.Inside)));

    /// <summary>The application thread, inline: counts its hops and knows when it is inside one.</summary>
    private sealed class RecordingThread : IApplicationThread
    {
        public int Invocations { get; private set; }

        public bool Inside { get; private set; }

        public T Invoke<T>(Func<T> work)
        {
            Invocations++;
            Inside = true;
            try
            {
                return work();
            }
            finally
            {
                Inside = false;
            }
        }
    }

    /// <summary>
    /// The seat's gate as a journal: each member the gate was asked about, with how many calls each
    /// stand-in had recorded at that moment, so every interop call can be placed under the gate entry it
    /// was made under. A gate entry is told before its call is made (<see cref="SwGate"/>), so a call
    /// recorded before the first entry was made outside the gate.
    /// </summary>
    private sealed class GateJournal : ISwGateObserver
    {
        private readonly (string Label, Func<IReadOnlyList<string>> Members)[] _standIns;
        private readonly List<(string Member, int[] Counts)> _entries = new List<(string, int[])>();

        public GateJournal(params (string Label, object Recorder)[] standIns)
        {
            _standIns = standIns.Select(standIn => (standIn.Label, MembersOf(standIn.Recorder))).ToArray();
        }

        public List<MutatingCallError> Refusals { get; } = new List<MutatingCallError>();

        public void Gated(string interopMember) =>
            _entries.Add((interopMember, _standIns.Select(standIn => standIn.Members().Count).ToArray()));

        public void Refused(MutatingCallError refusal) => Refusals.Add(refusal);

        /// <summary>
        /// "gate &lt;member&gt;" for each entry, followed by the calls made under it, stand-in by stand-in;
        /// any call made before the first entry is listed first as "outside the gate &lt;call&gt;".
        /// </summary>
        public IReadOnlyList<string> Timeline()
        {
            var timeline = new List<string>();
            int[] start = new int[_standIns.Length];
            for (int entry = 0; entry <= _entries.Count; entry++)
            {
                int[] end = entry < _entries.Count
                    ? _entries[entry].Counts
                    : _standIns.Select(standIn => standIn.Members().Count).ToArray();
                for (int index = 0; index < _standIns.Length; index++)
                {
                    IReadOnlyList<string> members = _standIns[index].Members();
                    for (int call = start[index]; call < end[index]; call++)
                    {
                        string named = _standIns[index].Label + "." + members[call];
                        timeline.Add(entry == 0 ? "outside the gate " + named : named);
                    }
                }

                if (entry < _entries.Count)
                {
                    timeline.Add("gate " + _entries[entry].Member);
                }

                start = end;
            }

            return timeline;
        }

        private static Func<IReadOnlyList<string>> MembersOf(object recorder) =>
            recorder switch
            {
                InteropRecorder<ISldWorks> application => () => application.Members,
                InteropRecorder<ModelDoc2> document => () => document.Members,
                InteropRecorder<IDocumentSpecification> request => () => request.Members,
                _ => throw new ArgumentException("not a stand-in this journal reads", nameof(recorder)),
            };
    }
}
