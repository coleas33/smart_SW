using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.AddIn;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T054: a configuration switch inside the reviewed document is a document change
/// (FR-022, contracts/sessions.md section 7).
///
/// The add-in subscribed to one SOLIDWORKS event, `ActiveDocChangeNotify`, so switching the open
/// assembly from Default to Machined told no tab anything and a review of Default stayed painted
/// over Machined. <see cref="ActiveConfigurationWatch"/> follows the active document and holds at
/// most one subscription to its `ActiveConfigChangePostNotify` - the part's or the assembly's; a
/// drawing has no configuration of its own - and runs the add-in's document fan-out when it fires,
/// so every host posts `document.changed` with the new configuration.
///
/// The rule is tested behind its seam - subscribe and unsubscribe delegates over fake documents -
/// because there is no licence on this machine; the real events are confirmed at the next
/// workstation sitting (T081).
/// </summary>
public sealed class ActiveConfigurationWatchTests
{
    [Fact]
    public void FollowingAPartSubscribesItOnce()
    {
        var world = new World();
        var part = new FakeDocument("part");

        world.Watch.Follow(part);

        Assert.Equal(new[] { "subscribe part" }, world.Calls.ToArray());
    }

    [Fact]
    public void FollowingAnAssemblyAfterAPartUnsubscribesThePartAndSubscribesTheAssembly()
    {
        var world = new World();
        var part = new FakeDocument("part");
        var assembly = new FakeDocument("assembly");

        world.Watch.Follow(part);
        world.Watch.Follow(assembly);

        Assert.Equal(new[] { "subscribe part", "unsubscribe part", "subscribe assembly" }, world.Calls.ToArray());
    }

    /// <summary>A drawing has no configuration of its own, and no document has none: either leaves nothing subscribed.</summary>
    [Fact]
    public void FollowingADrawingOrNothingUnsubscribesAndSubscribesNothing()
    {
        var world = new World();
        var part = new FakeDocument("part");

        world.Watch.Follow(part);
        world.Watch.Follow(new FakeDocument("drawing"));
        Assert.Equal(new[] { "subscribe part", "unsubscribe part", "refused drawing" }, world.Calls.ToArray());

        world.Calls.Clear();
        world.Watch.Follow(part);
        world.Watch.Follow(null);
        Assert.Equal(new[] { "subscribe part", "unsubscribe part" }, world.Calls.ToArray());
    }

    /// <summary>Every `ActiveDocChangeNotify` follows the active document; the same one twice is one subscription.</summary>
    [Fact]
    public void FollowingTheSameDocumentTwiceSubscribesOnce()
    {
        var world = new World();
        var assembly = new FakeDocument("assembly");

        world.Watch.Follow(assembly);
        world.Watch.Follow(assembly);

        Assert.Equal(new[] { "subscribe assembly" }, world.Calls.ToArray());
    }

    [Fact]
    public void TheEventRunsTheCallbackAndAnswersZero()
    {
        var world = new World();
        world.Watch.Follow(new FakeDocument("part"));

        int answer = world.Sink!();

        Assert.Equal(1, world.Changes);
        Assert.Equal(0, answer);
    }

    /// <summary>
    /// Nothing may leave a COM event sink: an exception out of it is SOLIDWORKS' problem. A
    /// callback that throws is swallowed, and the sink still answers 0.
    /// </summary>
    [Fact]
    public void AThrowingCallbackIsSwallowedAndTheSinkAnswersZero()
    {
        var world = new World { Throw = true };
        world.Watch.Follow(new FakeDocument("part"));

        int answer = world.Sink!();

        Assert.Equal(1, world.Changes);
        Assert.Equal(0, answer);
    }

    /// <summary>An unsubscribe that throws - the document is already gone - does not stop the watch following the next one.</summary>
    [Fact]
    public void AFailedUnsubscribeDoesNotStopTheWatchFollowingTheNextDocument()
    {
        var world = new World();
        var part = new FakeDocument("part");
        world.Watch.Follow(part);
        world.UnsubscribeFailure = new InvalidOperationException("the document is closed");

        world.Watch.Follow(new FakeDocument("assembly"));

        Assert.Equal(new[] { "subscribe part", "unsubscribe part", "subscribe assembly" }, world.Calls.ToArray());
    }

    [Fact]
    public void DisposeUnsubscribes()
    {
        var world = new World();
        world.Watch.Follow(new FakeDocument("assembly"));

        world.Watch.Dispose();
        world.Watch.Dispose();

        Assert.Equal(new[] { "subscribe assembly", "unsubscribe assembly" }, world.Calls.ToArray());
    }

    /// <summary>The sink it subscribes is one delegate, so unsubscribing names the same handler it subscribed.</summary>
    [Fact]
    public void TheSameSinkIsSubscribedAndUnsubscribed()
    {
        var world = new World();
        world.Watch.Follow(new FakeDocument("part"));
        Func<int>? subscribed = world.Sink;

        world.Watch.Follow(null);

        Assert.Same(subscribed, world.Unsubscribed);
    }

    private sealed class FakeDocument
    {
        public FakeDocument(string kind) => Kind = kind;

        public string Kind { get; }
    }

    private sealed class World
    {
        public World()
        {
            Watch = new ActiveConfigurationWatch(
                (document, sink) =>
                {
                    var fake = (FakeDocument)document;
                    if (fake.Kind != "part" && fake.Kind != "assembly")
                    {
                        Calls.Add("refused " + fake.Kind);
                        return false;
                    }

                    Calls.Add("subscribe " + fake.Kind);
                    Sink = sink;
                    return true;
                },
                (document, sink) =>
                {
                    Calls.Add("unsubscribe " + ((FakeDocument)document).Kind);
                    Unsubscribed = sink;
                    if (UnsubscribeFailure != null)
                    {
                        throw UnsubscribeFailure;
                    }
                },
                () =>
                {
                    Changes++;
                    if (Throw)
                    {
                        throw new InvalidOperationException("the fan-out failed");
                    }
                });
        }

        public ActiveConfigurationWatch Watch { get; }

        public List<string> Calls { get; } = new List<string>();

        public Func<int>? Sink { get; private set; }

        public Func<int>? Unsubscribed { get; private set; }

        public Exception? UnsubscribeFailure { get; set; }

        public int Changes { get; private set; }

        public bool Throw { get; set; }
    }
}
