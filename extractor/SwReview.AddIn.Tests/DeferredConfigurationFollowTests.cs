using System;
using System.Collections.Generic;
using System.IO;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>004 T274: only configuration subscription waits for the actual native copy-open boundary.</summary>
public sealed class DeferredConfigurationFollowTests
{
    [Fact]
    public void AWatchFollowDuringOpenWaitsForItsFinalExit()
    {
        using (var world = new World())
        {
            IDisposable opening = world.Coordinator.BeginRemodelOpen()!;
            world.ActiveDocument = "copy";

            world.Coordinator.Request();

            Assert.Empty(world.Followed);
            Assert.Equal(0, world.Resolutions);
            Assert.Empty(world.Posted);
            opening.Dispose();
            Assert.Single(world.Posted);
            Assert.Empty(world.Followed);
            world.RunNext();
            Assert.Equal(new[] { "copy" }, world.Followed);
        }
    }

    [Fact]
    public void DeferredWatchRequestsCoalesceAndUseTheLatestActiveDocument()
    {
        using (var world = new World())
        {
            IDisposable opening = world.Coordinator.BeginRemodelOpen()!;
            world.ActiveDocument = "first copy";
            world.Coordinator.Request();
            world.ActiveDocument = "second copy";
            world.Coordinator.Request();
            opening.Dispose();
            Assert.Single(world.Posted);

            world.ActiveDocument = "latest document";
            world.RunNext();

            Assert.Equal(1, world.Resolutions);
            Assert.Equal(new[] { "latest document" }, world.Followed);
        }
    }

    [Fact]
    public void APostedFlushPumpedInsideAnotherOpenDoesNotFollowUntilThatOpenEnds()
    {
        using (var world = new World())
        {
            IDisposable first = world.Coordinator.BeginRemodelOpen()!;
            world.Coordinator.Request();
            first.Dispose();
            Assert.Single(world.Posted);
            IDisposable second = world.Coordinator.BeginRemodelOpen()!;

            world.RunNext();

            Assert.Empty(world.Followed);
            Assert.Equal(0, world.Resolutions);
            Assert.Empty(world.Posted); // A nested message pump must not cause a self-posting loop.
            world.ActiveDocument = "after both opens";
            second.Dispose();
            Assert.Single(world.Posted);
            world.RunNext();
            Assert.Equal(new[] { "after both opens" }, world.Followed);
        }
    }

    [Fact]
    public void NestedOrRepeatedOpenLeaseDisposalCannotReleaseAnotherOpen()
    {
        using (var world = new World())
        {
            IDisposable outer = world.Coordinator.BeginRemodelOpen()!;
            IDisposable inner = world.Coordinator.BeginRemodelOpen()!;
            world.Coordinator.Request();

            outer.Dispose();
            outer.Dispose();

            Assert.Empty(world.Posted);
            Assert.Empty(world.Followed);
            inner.Dispose();
            inner.Dispose();
            Assert.Single(world.Posted);
            world.RunNext();
            Assert.Equal(new[] { "source" }, world.Followed);
        }
    }

    [Fact]
    public void DisposingTheCoordinatorInvalidatesQueuedWorkAndOldLeases()
    {
        using (var world = new World())
        {
            IDisposable opening = world.Coordinator.BeginRemodelOpen()!;
            world.Coordinator.Request();
            opening.Dispose();
            Assert.Single(world.Posted);
            IDisposable late = world.Coordinator.BeginRemodelOpen()!;

            world.Coordinator.Dispose();
            late.Dispose();
            world.RunNext();
            world.Coordinator.Request();

            Assert.Empty(world.Followed);
            Assert.Equal(0, world.Resolutions);
            Assert.Empty(world.Posted);
            Assert.Null(world.Coordinator.BeginRemodelOpen());
        }
    }

    [Fact]
    public void ReplacingTheWatchCannotLetOldQueuedWorkFollowTheReplacement()
    {
        using (var world = new World())
        {
            ConfigurationFollowCoordinator old = world.Coordinator;
            IDisposable opening = old.BeginRemodelOpen()!;
            old.Request();
            opening.Dispose();
            Assert.Single(world.Posted);

            world.ReplaceWatch();
            world.ActiveDocument = "replacement";
            world.RunNext();
            opening.Dispose();
            old.Request();

            Assert.Empty(world.Followed);
            Assert.Equal(0, world.Resolutions);
            world.Coordinator.Request();
            Assert.Equal(new[] { "replacement" }, world.Followed);
        }
    }

    [Fact]
    public void AWatchRequestOutsideOpenRunsImmediatelyEvenWhileARemodelRunIsBusy()
    {
        using (var world = new World())
        {
            SwReviewAddIn.TraceFanOutDuringARemodelRun(true, _ => { }, () =>
            {
                world.Coordinator.Request();
                world.Calls.Add("tabs and copy-loss and tool-service follow");
            });

            Assert.Equal(new[] { "follow source", "tabs and copy-loss and tool-service follow" }, world.Calls);
            Assert.Empty(world.Posted);
        }
    }

    [Fact]
    public void ADocumentChangeDuringHeldOpenStillNotifiesTabsAndCopyLossImmediately()
    {
        using (var world = new World())
        {
            IDisposable opening = world.Coordinator.BeginRemodelOpen()!;

            SwReviewAddIn.TraceFanOutDuringARemodelRun(true, _ => { }, () =>
            {
                world.Coordinator.Request();
                world.Calls.Add("tabs and copy-loss and tool-service follow");
            });

            Assert.Equal(new[] { "tabs and copy-loss and tool-service follow" }, world.Calls);
            Assert.Empty(world.Followed);
            Assert.Equal(0, world.Resolutions);
            opening.Dispose();
            world.RunNext();
            Assert.Equal(new[] { "tabs and copy-loss and tool-service follow", "follow source" }, world.Calls);
        }
    }

    [Theory]
    [InlineData("follow")]
    [InlineData("post")]
    [InlineData("resolve")]
    [InlineData("report")]
    public void AThrowingFollowOrPostDoesNotStrandLaterRequests(string failureAt)
    {
        using (var world = new World())
        {
            if (failureAt == "follow" || failureAt == "report")
            {
                world.FollowFailure = new IOException("FICT the old document no longer answers.");
                world.ReportFailure = failureAt == "report";
                Assert.Null(Record.Exception(world.Coordinator.Request));
                world.FollowFailure = null;
                world.ReportFailure = false;
            }
            else if (failureAt == "resolve")
            {
                world.ResolveFailure = new IOException("FICT the active document no longer answers.");
                Assert.Null(Record.Exception(world.Coordinator.Request));
                world.ResolveFailure = null;
            }
            else
            {
                world.PostFailure = new InvalidOperationException("FICT the posting handle went away.");
                IDisposable opening = world.Coordinator.BeginRemodelOpen()!;
                world.Coordinator.Request();
                Assert.Null(Record.Exception(opening.Dispose));
                world.PostFailure = null;
            }

            Assert.Single(world.Failures);
            world.ActiveDocument = "later document";
            world.Coordinator.Request();

            Assert.Equal(new[] { "later document" }, world.Followed);
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void AReentrantActiveDocumentReadCannotFollowAfterCoordinatorReplacementOrDisposal(bool replace)
    {
        using (var world = new World())
        {
            world.DuringResolve = () =>
            {
                world.DuringResolve = null;
                if (replace) world.ReplaceWatch();
                else world.Coordinator.Dispose();
            };

            world.Coordinator.Request();

            Assert.Empty(world.Followed);
            Assert.Empty(world.Posted);
            if (replace)
            {
                world.ActiveDocument = "replacement";
                world.Coordinator.Request();
                Assert.Equal(new[] { "replacement" }, world.Followed);
            }
        }
    }

    [Fact]
    public void AnOpenEnteredDuringActiveDocumentResolutionDefersTheFollowAgain()
    {
        using (var world = new World())
        {
            IDisposable? opening = null;
            world.DuringResolve = () =>
            {
                world.DuringResolve = null;
                opening = world.Coordinator.BeginRemodelOpen();
            };

            world.Coordinator.Request();

            Assert.Empty(world.Followed);
            Assert.Empty(world.Posted);
            world.ActiveDocument = "after open";
            opening!.Dispose();
            Assert.Single(world.Posted);
            world.RunNext();
            Assert.Equal(new[] { "after open" }, world.Followed);
        }
    }

    [Fact]
    public void ADocumentChangeDuringResolutionDoesNotSubscribeAStaleReturnedDocument()
    {
        using (var world = new World())
        {
            world.DuringResolve = () =>
            {
                world.DuringResolve = null;
                world.ActiveDocument = "replacement";
                world.Coordinator.Request();
            };

            world.Coordinator.Request();

            Assert.Empty(world.Followed);
            Assert.Single(world.Posted);
            world.RunNext();
            Assert.Equal(new[] { "replacement" }, world.Followed);
        }
    }

    [Fact]
    public void AnOpenThatEntersAndExitsDuringResolutionStillRequiresAFreshDocumentRead()
    {
        using (var world = new World())
        {
            world.DuringResolve = () =>
            {
                world.DuringResolve = null;
                IDisposable opening = world.Coordinator.BeginRemodelOpen()!;
                world.ActiveDocument = "after completed open";
                opening.Dispose();
            };

            world.Coordinator.Request();

            Assert.Empty(world.Followed);
            Assert.Single(world.Posted);
            world.RunNext();
            Assert.Equal(new[] { "after completed open" }, world.Followed);
        }
    }

    private sealed class World : IDisposable
    {
        public World() => ReplaceWatch();

        public object? ActiveDocument { get; set; } = "source";
        public Action? DuringResolve { get; set; }
        public Exception? FollowFailure { get; set; }
        public Exception? PostFailure { get; set; }
        public Exception? ResolveFailure { get; set; }
        public bool ReportFailure { get; set; }
        public int Resolutions { get; private set; }
        public List<string> Calls { get; } = new List<string>();
        public List<string> Followed { get; } = new List<string>();
        public List<Exception> Failures { get; } = new List<Exception>();
        public Queue<Action> Posted { get; } = new Queue<Action>();
        public ActiveConfigurationWatch Watch { get; private set; } = null!;
        public ConfigurationFollowCoordinator Coordinator { get; private set; } = null!;

        public void ReplaceWatch()
        {
            Coordinator?.Dispose();
            Watch?.Dispose();
            Watch = new ActiveConfigurationWatch(
                (document, _) =>
                {
                    if (FollowFailure != null) throw FollowFailure;
                    Calls.Add("follow " + document);
                    Followed.Add((string)document);
                    return true;
                },
                (_, __) => { },
                () => { });
            Coordinator = new ConfigurationFollowCoordinator(
                work =>
                {
                    if (PostFailure != null) throw PostFailure;
                    Posted.Enqueue(work);
                },
                () =>
                {
                    Resolutions++;
                    if (ResolveFailure != null) throw ResolveFailure;
                    object? result = ActiveDocument;
                    DuringResolve?.Invoke();
                    return result;
                },
                document => Watch.Follow(document),
                failure =>
                {
                    Failures.Add(failure);
                    if (ReportFailure) throw new IOException("FICT the error log is unavailable.");
                });
        }

        public void RunNext()
        {
            Assert.NotEmpty(Posted);
            Posted.Dequeue()();
        }

        public void Dispose()
        {
            Coordinator.Dispose();
            Watch.Dispose();
        }
    }
}
