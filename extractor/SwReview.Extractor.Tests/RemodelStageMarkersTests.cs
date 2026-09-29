using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// U27 (2026-09-28). The one helper that writes the before, after and failed markers around a
/// native call in <c>remodel.open</c> and <c>remodel.geometry</c>, so both commands mark their
/// calls the same way and a writer that fails never changes the call.
/// </summary>
public class RemodelStageMarkersTests
{
    [Fact]
    public void TheBeforeMarkerIsWrittenBeforeTheCallAndTheAfterMarkerOnceItAnswers()
    {
        var markers = new List<string>();

        int answer = RemodelStageMarkers.Around(markers.Add, "OpenDoc7", () =>
        {
            Assert.Equal(new[] { "before OpenDoc7" }, markers);
            return 17;
        });

        Assert.Equal(17, answer);
        Assert.Equal(new[] { "before OpenDoc7", "after OpenDoc7" }, markers);
    }

    [Fact]
    public void ACallThatThrowsLeavesAFailedMarkerAndTheExceptionGoesOnUnchanged()
    {
        var markers = new List<string>();
        var failure = new InvalidOperationException("the seat said no");

        InvalidOperationException thrown = Assert.Throws<InvalidOperationException>(
            () => RemodelStageMarkers.Around(markers.Add, "GetBodies2", (Action)(() => throw failure)));

        Assert.Same(failure, thrown);
        Assert.Equal(new[] { "before GetBodies2", "failed GetBodies2" }, markers);
    }

    [Fact]
    public void AWriterThatThrowsChangesNeitherTheAnswerNorTheCall()
    {
        int calls = 0;

        int answer = RemodelStageMarkers.Around(
            _ => throw new IOException("log unavailable"),
            "Recalculate",
            () =>
            {
                calls++;
                return 5;
            });

        Assert.Equal(5, answer);
        Assert.Equal(1, calls);
    }

    [Fact]
    public void NoWriterIsNoMarkers()
    {
        Assert.Equal(3, RemodelStageMarkers.Around(null, "get_Volume", () => 3));
    }
}
