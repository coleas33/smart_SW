using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using SwReview.AddIn.Model;
using SwReview.AddIn.Remodel;
using SwReview.AddIn.Review;
using SwReview.AddIn.Standards;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 145A, the hosts' half of "every tab follows a settings restart". The Model
/// check, Standards and Remodel hosts each tell their page `backend.restarted` when the add-in
/// asks them to, and the add-in asks all three each time the review host has restarted the
/// backend - a save's restart made at once, or one made after it waited (that half is in
/// <see cref="DeferredRestartTests"/>). The page then asks `ready` again for the new port and
/// token (<see cref="TabPagesBackendRestartTests"/>).
///
/// The add-in cannot be built without a live SOLIDWORKS, so its wiring is read from its source,
/// as <see cref="DeferredRestartTests"/> and <see cref="RemodelWiringTests"/> read theirs.
///
/// The 150A review adds the way on to the add-in's word that the backend did not start, a failed
/// first start's and a failed restart's, as each tab is told it.
/// </summary>
public sealed class OtherTabsBackendRestartTests
{
    public static IEnumerable<object[]> Tabs => new[]
    {
        new object[] { "model-check" },
        new object[] { "standards" },
        new object[] { "remodel" },
    };

    /// <summary>
    /// One message, unsolicited, and nothing else: `backend.restarted` carrying none of the Review
    /// tab's sentences about a restart that waited, since this page was shown none of them.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void EachOtherTabsHostTellsItsPageTheBackendRestarted(string tab)
    {
        var posted = new List<string>();
        Action told = TellingHost(tab, posted);

        told();

        JsonElement message = JsonDocument.Parse(Assert.Single(posted)).RootElement;
        Assert.Equal("backend.restarted", message.GetProperty("type").GetString());
        Assert.True(
            !message.TryGetProperty("id", out JsonElement id) || id.ValueKind == JsonValueKind.Null,
            "backend.restarted answers nothing the page asked, so it carries no id: " + message.GetRawText());
        JsonElement sentences = message.GetProperty("payload").GetProperty("sentences");
        Assert.Equal(JsonValueKind.Array, sentences.ValueKind);
        Assert.Equal(0, sentences.GetArrayLength());
    }

    /// <summary>
    /// The review host's restarts reach every other tab that holds the backend's port and token:
    /// the add-in hands the review host one call that tells the Model check, Standards and Remodel
    /// hosts, each read through its field - those hosts are built after the review host's options,
    /// and one that has gone tells nothing. The Terminal tab holds no backend, and is not told.
    /// </summary>
    [Fact]
    public void TheAddInTellsTheOtherTabsAfterEveryRestartTheReviewHostMakes()
    {
        string source = AddInSource();
        string options = Between(
            source, "var reviewOptions = new ReviewHostOptions(", "_reviewHost = new ReviewHost(reviewOptions);");
        Assert.Contains("BackendRestarted = TellTheOtherTabsTheBackendRestarted,", options, StringComparison.Ordinal);

        string fanOut = Between(source, "private void TellTheOtherTabsTheBackendRestarted() {", "}");
        Assert.Contains("_modelCheckHost?.BackendRestarted();", fanOut, StringComparison.Ordinal);
        Assert.Contains("_standardsHost?.BackendRestarted();", fanOut, StringComparison.Ordinal);
        Assert.Contains("_remodelHost?.BackendRestarted();", fanOut, StringComparison.Ordinal);
        Assert.DoesNotContain("_terminalHost", fanOut, StringComparison.Ordinal);
    }

    /// <summary>
    /// A restart that failed once the old backend had stopped reaches every other tab that holds the
    /// backend's port and token as a failed first start reaches every page: the add-in hands the
    /// review host one call that posts `status {stage: "error"}`, with the failure, through each of
    /// the Model check, Standards and Remodel hosts - the add-in's own fan-out of a backend status,
    /// less the Review page, which the review host tells itself (owner decision 145A, found on
    /// review). One case per tab. Since the 150A review the failure ends with the way on, which is
    /// on the Review tab, and the call, which a failed first start makes too, is named for what it
    /// says: the backend did not start.
    /// </summary>
    [Theory]
    [InlineData("_modelCheckHost?.PostStatus(stage, message, lifecycle: true);")]
    [InlineData("_standardsHost?.PostStatus(stage, message, lifecycle: true);")]
    [InlineData("_remodelHost?.PostStatus(stage, message, lifecycle: true);")]
    public void TheAddInTellsEachOtherTabARestartFailedAsAFailedStartIsTold(string post)
    {
        string source = AddInSource();
        string options = Between(
            source, "var reviewOptions = new ReviewHostOptions(", "_reviewHost = new ReviewHost(reviewOptions);");
        Assert.Contains("BackendRestartFailed = TellTheOtherTabsTheBackendDidNotStart,", options, StringComparison.Ordinal);
        Assert.Contains(
            "private void TellTheOtherTabsTheBackendDidNotStart(string message) => PostStatusToTheOtherPages("
                + "\"error\", ReviewHost.WithTheWayOn(message, ReviewHost.StartItAgainOnTheReviewTab));",
            source,
            StringComparison.Ordinal);

        string others = Between(source, "private void PostStatusToTheOtherPages(string stage, string message) {", "/// <summary>");
        Assert.Contains(post, others, StringComparison.Ordinal);
        Assert.DoesNotContain("_reviewHost", others, StringComparison.Ordinal);

        // The first start's fan-out is the same one, with the Review page in front of it.
        string every = Between(source, "private void PostStatusToPages(string stage, string message) {", "}");
        Assert.Contains("_reviewHost?.PostStatus(stage, message); PostStatusToTheOtherPages(stage, message);", every, StringComparison.Ordinal);
    }

    /// <summary>
    /// A first start that failed is told to every page with the way on (150A review, O2: until then
    /// each banner carried the bare failure): the Review page is sent to its own Save, and every
    /// other tab, through the call a restart that failed is told to them with, to the Review tab's.
    /// <i>Changed deliberately on the review of owner decision 160A (S3):</i> the Review page's word is
    /// marked as the backend's own (`lifecycle`), as every other page's is, since only that word, and a
    /// save's `BackendNotRestarted`, now tells its strip the backend is not running.
    /// </summary>
    [Fact]
    public void AFailedFirstStartTellsEveryPageTheWayOn()
    {
        string source = AddInSource();
        // The first start takes nothing since owner decision 153A's review (C1): the review host reads
        // the settings when the start is made.
        string start = Between(
            source,
            "private void StartBackend() {",
            "Report(\"The SwReview backend did not start.\", failure);");
        int caught = start.IndexOf("catch (Exception failure)", StringComparison.Ordinal);
        Assert.True(caught >= 0, "StartBackend no longer catches the start's failure where this test reads it.");
        string failed = start.Substring(caught);

        Assert.Contains(
            "_reviewHost?.PostStatus(\"error\", ReviewHost.WithTheWayOn(failure.Message, ReviewHost.StartItAgain), lifecycle: true);",
            failed,
            StringComparison.Ordinal);
        Assert.Contains("TellTheOtherTabsTheBackendDidNotStart(failure.Message);", failed, StringComparison.Ordinal);
        Assert.DoesNotContain("PostStatusToPages(\"error\"", failed, StringComparison.Ordinal);
    }

    /// <summary>
    /// The way on is a sentence of its own after the failure: a failure that does not end in a full
    /// stop - "... (log: &lt;path&gt;)" - is given one, trailing blanks go, and with no failure there is
    /// only the way on (150A review, O2).
    /// </summary>
    [Theory]
    [InlineData(
        "FICT the backend did not answer /health within 30 seconds. See the log at C:\\Fictional\\FICT-logs\\backend.log.",
        "FICT the backend did not answer /health within 30 seconds. See the log at C:\\Fictional\\FICT-logs\\backend.log. "
            + "Save Settings on the Review tab to start it again.")]
    [InlineData(
        "FICT the backend could not be started: the job refused it (log: C:\\Fictional\\FICT-logs\\backend.log)",
        "FICT the backend could not be started: the job refused it (log: C:\\Fictional\\FICT-logs\\backend.log). "
            + "Save Settings on the Review tab to start it again.")]
    [InlineData("FICT the backend did not start?  ", "FICT the backend did not start? Save Settings on the Review tab to start it again.")]
    [InlineData("", "Save Settings on the Review tab to start it again.")]
    public void TheWayOnIsASentenceOfItsOwnAfterTheFailure(string failure, string said)
    {
        Assert.Equal(said, ReviewHost.WithTheWayOn(failure, ReviewHost.StartItAgainOnTheReviewTab));
    }

    /// <summary>
    /// Each other tab's host marks the add-in's own word on the backend - its start, or a restart
    /// that failed - as such, `lifecycle: true`, when the add-in says so, and nothing else it posts:
    /// the page takes down a banner it put up for that word once a later `init` names a backend,
    /// and only that banner (owner decision 145A, third review).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void EachOtherTabsHostMarksTheBackendsOwnWordAndNothingElse(string tab)
    {
        var posted = new List<string>();
        Action<string, string, bool> post = PostingHost(tab, posted);

        post("error", "FICT the review backend did not start.", true);
        post("error", "FICT the check stopped part way through.", false);

        Assert.Equal(2, posted.Count);
        JsonElement backends = JsonDocument.Parse(posted[0]).RootElement.GetProperty("payload");
        Assert.Equal("error", backends.GetProperty("stage").GetString());
        Assert.Equal("FICT the review backend did not start.", backends.GetProperty("message").GetString());
        Assert.True(backends.GetProperty("lifecycle").GetBoolean());
        JsonElement other = JsonDocument.Parse(posted[1]).RootElement.GetProperty("payload");
        Assert.False(other.TryGetProperty("lifecycle", out _), "only the backend's own word is marked: " + other.GetRawText());
    }

    /// <summary>
    /// Owner decision 160A, found on review by mutation: each other tab's `init` says whether the last start or restart of
    /// the backend failed with none up - the review host's word, which the add-in hands each host - so its page, loaded or
    /// loaded again after the failure's `status`, says the backend is not running and how to start it, not "Backend
    /// starting". Only while no backend is up: an `init` that names one never calls it failed, whatever the word says.
    /// </summary>
    [Theory]
    [MemberData(nameof(TabsAndStarts))]
    public void EachOtherTabsInitSaysWhetherTheLastStartFailedWithNoBackendUp(string tab, bool failed, bool backendUp, bool said)
    {
        var posted = new List<string>();
        BackendEndpoint? endpoint = backendUp ? new BackendEndpoint(51234, "FICT-token") : null;
        using (IDisposable host = InitHost(tab, posted, () => endpoint, () => failed, out Action<string> receive))
        {
            receive(JsonSerializer.Serialize(new { type = "ready", id = "r1", payload = new { } }));
        }

        JsonElement init = posted
            .Select(message => JsonDocument.Parse(message).RootElement)
            .Single(root => root.GetProperty("type").GetString() == "init")
            .GetProperty("payload");
        Assert.Equal(backendUp ? JsonValueKind.Object : JsonValueKind.Null, init.GetProperty("backend").ValueKind);
        Assert.Equal(said, init.GetProperty("backend_start_failed").GetBoolean());
    }

    /// <summary>
    /// Each other tab, with what the review host's word can meet: no failure; a failure with no backend up; and a failure
    /// while one is up, which the word itself never says (<c>ReviewHost.BackendStartFailed</c>), held here by the host too.
    /// </summary>
    public static IEnumerable<object[]> TabsAndStarts =>
        from tab in new[] { "model-check", "standards", "remodel" }
        from start in new[]
        {
            new[] { false, false, false },
            new[] { true, false, true },
            new[] { true, true, false },
        }
        select new object[] { tab, start[0], start[1], start[2] };

    /// <summary>
    /// ...and the add-in hands each of the three the review host's word, read at each `init`, as it hands them the review
    /// host's run roots (found on review by mutation). The add-in cannot be built here, so its source is read.
    /// </summary>
    [Theory]
    [InlineData("_modelCheckHost = new ModelCheckHost(new ModelCheckHostOptions(")]
    [InlineData("_standardsHost = new StandardsHost(new StandardsHostOptions(")]
    [InlineData("_remodelHost = new RemodelHost(new RemodelHostOptions(")]
    public void TheAddInHandsEachOtherTabTheReviewHostsWordOnAFailedStart(string built)
    {
        string options = Between(AddInSource(), built, "});");
        Assert.Contains("BackendStartFailed = () => _reviewHost?.BackendStartFailed == true,", options, StringComparison.Ordinal);
    }

    /// <summary>
    /// The host of <paramref name="tab"/> over a channel that collects what it posts, with its backend and the review
    /// host's word on a failed start, and its <c>Receive</c>, which takes a page's message.
    /// </summary>
    private static IDisposable InitHost(
        string tab, List<string> posted, Func<BackendEndpoint?> backend, Func<bool> failed, out Action<string> receive)
    {
        var channel = new CollectingChannel(posted);
        Func<string> runRoot = () => Path.Combine(Path.GetTempPath(), "SwReview.OtherTabs.Tests");
        switch (tab)
        {
            case "model-check":
                var check = new ModelCheckHost(new ModelCheckHostOptions(channel, runRoot) { Backend = backend, BackendStartFailed = failed });
                receive = check.Receive;
                return check;

            case "standards":
                var standards = new StandardsHost(new StandardsHostOptions(channel, runRoot) { Backend = backend, BackendStartFailed = failed });
                receive = standards.Receive;
                return standards;

            case "remodel":
                var remodel = new RemodelHost(new RemodelHostOptions(channel, runRoot) { Backend = backend, BackendStartFailed = failed });
                receive = remodel.Receive;
                return remodel;

            default:
                throw new ArgumentOutOfRangeException(nameof(tab), tab, "no tab of that name");
        }
    }

    /// <summary>The host of <paramref name="tab"/> over a channel that collects what it posts, and its <c>PostStatus</c>.</summary>
    private static Action<string, string, bool> PostingHost(string tab, List<string> posted)
    {
        var channel = new CollectingChannel(posted);
        Func<string> runRoot = () => Path.Combine(Path.GetTempPath(), "SwReview.OtherTabs.Tests");
        switch (tab)
        {
            case "model-check":
                ModelCheckHost check = new ModelCheckHost(new ModelCheckHostOptions(channel, runRoot));
                return (stage, message, lifecycle) => check.PostStatus(stage, message, lifecycle);

            case "standards":
                StandardsHost standards = new StandardsHost(new StandardsHostOptions(channel, runRoot));
                return (stage, message, lifecycle) => standards.PostStatus(stage, message, lifecycle);

            case "remodel":
                RemodelHost remodel = new RemodelHost(new RemodelHostOptions(channel, runRoot));
                return (stage, message, lifecycle) => remodel.PostStatus(stage, message, lifecycle);

            default:
                throw new ArgumentOutOfRangeException(nameof(tab), tab, "no tab of that name");
        }
    }

    /// <summary>
    /// The host of <paramref name="tab"/> over a channel that collects what it posts, and its
    /// <c>BackendRestarted</c>: the call the add-in makes on it after a restart.
    /// </summary>
    private static Action TellingHost(string tab, List<string> posted)
    {
        var channel = new CollectingChannel(posted);
        Func<string> runRoot = () => Path.Combine(Path.GetTempPath(), "SwReview.OtherTabs.Tests");
        switch (tab)
        {
            case "model-check":
                return new ModelCheckHost(new ModelCheckHostOptions(channel, runRoot)).BackendRestarted;

            case "standards":
                return new StandardsHost(new StandardsHostOptions(channel, runRoot)).BackendRestarted;

            case "remodel":
                return new RemodelHost(new RemodelHostOptions(channel, runRoot)).BackendRestarted;

            default:
                throw new ArgumentOutOfRangeException(nameof(tab), tab, "no tab of that name");
        }
    }

    /// <summary>The add-in's source with every run of whitespace made one space, as the wiring tests read it.</summary>
    internal static string AddInSource() => Regex.Replace(
        File.ReadAllText(Path.Combine(
            ErrorLabelsCoverTheHostTests.RepositoryRoot(), "extractor", "SwReview.AddIn", "SwReviewAddIn.cs")),
        @"\s+",
        " ");

    /// <summary>The text from <paramref name="start"/> to the first <paramref name="end"/> after it.</summary>
    internal static string Between(string source, string start, string end)
    {
        int from = source.IndexOf(start, StringComparison.Ordinal);
        int to = from < 0 ? -1 : source.IndexOf(end, from + start.Length, StringComparison.Ordinal);
        Assert.True(to > from, "SwReviewAddIn.cs no longer has `" + start + "` where this test reads it.");
        return source.Substring(from, to - from);
    }

    private sealed class CollectingChannel : IPageChannel
    {
        private readonly List<string> _posted;

        public CollectingChannel(List<string> posted)
        {
            _posted = posted;
        }

        public void PostMessage(string json) => _posted.Add(json);
    }
}
