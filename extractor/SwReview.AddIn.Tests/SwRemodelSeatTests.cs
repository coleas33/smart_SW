using System;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004 T159 (build order lane E): <see cref="SwRemodelSeat.ActivateOpenCopy"/>, the
/// activation both dumps make, over the recording stand-ins - no COM object exists and
/// SOLIDWORKS is never started.
///
/// What it must do is small and exact: find the copy among the documents SOLIDWORKS already has
/// open, activate it by its title without a rebuild - the call <c>remodel.open_copy</c> already
/// makes - and answer the path of whatever is active afterwards, all on the application thread.
/// What it must never do is open anything: a copy SOLIDWORKS does not have open is answered null
/// and left alone, because a dump that could open a document would be a second way to open one
/// (research R13.8, D6). It decides nothing; the pipeline compares the answer with the copy.
/// </summary>
public sealed class SwRemodelSeatTests
{
    private const string CopyTitle = "bracket-RMS.SLDPRT";

    private static readonly string CopyPath = RemodelCopy.CopyPathFor(
        Path.Combine(Path.GetTempPath(), "swreview-seat", "20260927-100000-bracket-remodel"),
        "C:\\work\\bracket.SLDPRT");

    private readonly InteropRecorder<ISldWorks> _application = new InteropRecorder<ISldWorks>();
    private readonly StandInDocument _copy = new StandInDocument();
    private readonly RecordingThread _thread = new RecordingThread();

    public SwRemodelSeatTests()
    {
        _copy.Document.Answer("GetTitle", CopyTitle).Answer("GetPathName", CopyPath);
        _application
            .Answer("GetOpenDocumentByName", _copy.Instance)
            .Answer("ActivateDoc3", _copy.Instance)
            .Answer("get_ActiveDoc", _copy.Instance);
    }

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
        Assert.Equal(new[] { "GetTitle", "GetPathName" }, _copy.Document.Members);
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
        var source = new StandInDocument();
        source.Document.Answer("GetPathName", "C:\\work\\bracket.SLDPRT");
        _application.Answer("get_ActiveDoc", source.Instance);

        Assert.Equal("C:\\work\\bracket.SLDPRT", Seat().ActivateOpenCopy(CopyPath));
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
    }

    private SwRemodelSeat Seat() => new SwRemodelSeat(_application.Instance, _thread);

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
}
