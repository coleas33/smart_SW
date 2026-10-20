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
    /// review). One case per tab.
    /// </summary>
    [Theory]
    [InlineData("_modelCheckHost?.PostStatus(stage, message);")]
    [InlineData("_standardsHost?.PostStatus(stage, message);")]
    [InlineData("_remodelHost?.PostStatus(stage, message);")]
    public void TheAddInTellsEachOtherTabARestartFailedAsAFailedStartIsTold(string post)
    {
        string source = AddInSource();
        string options = Between(
            source, "var reviewOptions = new ReviewHostOptions(", "_reviewHost = new ReviewHost(reviewOptions);");
        Assert.Contains("BackendRestartFailed = TellTheOtherTabsTheRestartFailed,", options, StringComparison.Ordinal);
        Assert.Contains(
            "private void TellTheOtherTabsTheRestartFailed(string message) => PostStatusToTheOtherPages(\"error\", message);",
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
