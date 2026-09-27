using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 013 T053: the grouped findings the Review tab shows when a session ends (FR-015 to
/// FR-022, contracts/grouped-list.md section 5) - one section, `#findings-by-type`, in place of
/// feature 007's Start here, feature 009's "Show all" and the flat list. Until feature 013 this
/// class pinned the Start-here panel (T039); the panel is gone, and what it tested about the
/// ranking's lifecycle - the one authenticated read at the session's end, the answer for a chat
/// the page moved on from, a failed read - is tested here of the section that replaced it.
///
/// <b>The page moves cards, it never orders them</b> (research R2.19). Every group, row, count,
/// plural and chip is the backend's (<see cref="GroupsSample"/>, whose order no page could have
/// produced and whose Hygiene row's words disagree with its members on purpose); the page prints
/// each word verbatim or honours each flag, and <see cref="PageRuleScanTests"/> keeps the source
/// free of ranking rules. How the finding cards move into the rows is
/// <see cref="ReviewPageFindingGroupTests"/>'.
///
/// <b>Driven rather than scanned</b>, for the reason the panel's tests were: the section has to
/// notice that the session ended, ask `GET /sessions/{chat_id}/attention` with its bearer token,
/// and decide whether the answer still belongs to the chat on screen - a race a scan cannot name.
/// The session end is played from `contracts/event-stream.sample.sse` through
/// <see cref="SseFrames"/>, whose bytes the Python producer test pins.
///
/// <b>One boot, one scripted conversation</b>, read by every test below.
/// </summary>
public sealed class ReviewPageAttentionPanelTests
{
    /// <summary>The scripted run, driven once and read by every test in this class.</summary>
    private static readonly Lazy<Conversation> Scripted = new Lazy<Conversation>(Drive);

    /// <summary>The token the host sends in `init`, which must travel in the header and nowhere else.</summary>
    private const string Token = "0FAKEtoken-for-the-page-tests";

    private const string Origin = "http://127.0.0.1:51999";

    // ---- the fetch ---------------------------------------------------------------------------

    /// <summary>
    /// One authenticated read of the chat that just ended. The path names the chat, the token
    /// is in the `Authorization` header and nowhere in the URL (chat-api.md), and the method is
    /// a `GET` because the route computes the ranking in memory and writes nothing.
    /// </summary>
    [Fact]
    public void TheEndOfASessionReadsTheRankingForThatChatWithTheBearerHeader()
    {
        JsonElement call = Assert.Single(Scripted.Value.FirstEnd.GetProperty("calls").EnumerateArray());

        Assert.Equal("GET", call.GetProperty("method").GetString());
        Assert.Equal(Origin + "/sessions/chat-1/attention", call.GetProperty("url").GetString());
        Assert.Equal("Bearer " + Token, call.GetProperty("authorization").GetString());
    }

    // ---- the groups -----------------------------------------------------------------------------

    /// <summary>
    /// Every group in the order the backend supplied it, the checked fold last, each with its
    /// title and its `text` as sent - the page counts and pluralises nothing.
    /// </summary>
    [Fact]
    public void TheGroupsRenderInTheSuppliedOrderWithTheBackendsTitlesAndWords()
    {
        JsonElement first = Scripted.Value.FirstEnd;

        Assert.False(first.GetProperty("hidden").GetBoolean(), "#findings-by-type stayed hidden.");
        Assert.Equal(GroupsSample.GroupIds.Concat(new[] { "checked" }).ToArray(), ReviewPageDriver.Strings(first, "groupIds"));
        Assert.Equal(
            GroupsSample.GroupTitles.Concat(new[] { GroupsSample.CheckedTitle }).ToArray(),
            ReviewPageDriver.Strings(first, "groupTitles"));
        Assert.Equal(
            GroupsSample.GroupTexts.Concat(new[] { GroupsSample.CheckedText }).ToArray(),
            ReviewPageDriver.Strings(first, "groupTexts"));
        Assert.Equal("function", first.GetProperty("exported").GetString());
    }

    /// <summary>
    /// Each group is a `&lt;details&gt;` open as the backend's `open` says: Modelling practice
    /// arrives collapsed (research R2.15) and the checked fold collapsed, the rest open.
    /// </summary>
    [Fact]
    public void EachGroupIsOpenAsTheBackendSaysAndTheCheckedFoldArrivesCollapsed()
    {
        JsonElement first = Scripted.Value.FirstEnd;

        Assert.Equal(
            GroupsSample.GroupOpen.Concat(new[] { false }).ToArray(),
            first.GetProperty("groupOpen").EnumerateArray().Select(value => value.GetBoolean()).ToArray());
        Assert.All(ReviewPageDriver.Strings(first, "groupTags"), tag => Assert.Equal("DETAILS", tag));
    }

    /// <summary>
    /// Within each group, the rows in the order supplied - by survivor - with the checked fold's
    /// rows after every group's. A page that sorted by id would put F-007 before F-008.
    /// </summary>
    [Fact]
    public void EachGroupsRowsRenderInTheSuppliedOrder()
    {
        JsonElement first = Scripted.Value.FirstEnd;

        Assert.Equal(
            GroupsSample.GroupRowIds.Select(rows => string.Join("|", rows)).Concat(new[] { string.Join("|", GroupsSample.CheckedRowIds) }).ToArray(),
            ReviewPageDriver.Strings(first, "groupRows"));
    }

    /// <summary>
    /// A row is one line: its display title, then `tail_text`, `reach_text` and `chip`, each printed
    /// verbatim and only when the backend sent it; the stripe is the shared map's
    /// (`attention.stripeOf`), and a single-member row says it hides its card's title.
    /// </summary>
    [Fact]
    public void ARowIsOneLineOfTheBackendsWordsEachPrintedOnlyWhenSent()
    {
        JsonElement rows = Scripted.Value.FirstEnd.GetProperty("rows");

        JsonElement folded = rows.GetProperty(GroupsSample.FoldedRow);
        Assert.Equal(new[] { "type-row-title", "type-row-tail", "type-row-reach" }, ReviewPageDriver.Strings(folded, "parts"));
        Assert.Equal(
            new[] { GroupsSample.TitleOf(GroupsSample.FoldedRow), GroupsSample.FoldedTail, "reaches 1 component" },
            ReviewPageDriver.Strings(folded, "texts"));
        Assert.Equal("type-row stripe-quiet", folded.GetProperty("className").GetString());
        Assert.Equal("type-row stripe-critical hide-card-title", rows.GetProperty("F-003").GetProperty("className").GetString());
        Assert.Equal("type-row stripe-warn hide-card-title", rows.GetProperty("F-004").GetProperty("className").GetString());

        JsonElement single = rows.GetProperty("F-008");
        Assert.Equal(new[] { "type-row-title", "type-row-reach" }, ReviewPageDriver.Strings(single, "parts"));
        Assert.Equal("type-row stripe-judge hide-card-title", single.GetProperty("className").GetString());

        JsonElement model = rows.GetProperty(GroupsSample.ModelRow);
        Assert.Equal(new[] { "type-row-title", "chip type-row-chip" }, ReviewPageDriver.Strings(model, "parts"));
        Assert.Equal(new[] { GroupsSample.TitleOf(GroupsSample.ModelRow), GroupsSample.ModelChip }, ReviewPageDriver.Strings(model, "texts"));

        JsonElement bare = rows.GetProperty(GroupsSample.HostileRow);
        Assert.Equal(new[] { "type-row-title" }, ReviewPageDriver.Strings(bare, "parts"));
        Assert.Equal("type-row stripe-quiet hide-card-title", bare.GetProperty("className").GetString());
    }

    /// <summary>
    /// The page counts nothing: a row whose words disagree with its two members and its one
    /// component prints the words (FR-022; the page once counted them, research R2.19).
    /// </summary>
    [Fact]
    public void ARowWhoseWordsDisagreeWithItsMembersPrintsTheWords()
    {
        JsonElement row = Scripted.Value.FirstEnd.GetProperty("rows").GetProperty(GroupsSample.DisagreeingRow);

        Assert.Equal(
            new[] { GroupsSample.TitleOf(GroupsSample.DisagreeingRow), GroupsSample.DisagreeingTail, GroupsSample.DisagreeingReach },
            ReviewPageDriver.Strings(row, "texts"));
        Assert.Equal("type-row stripe-quiet", row.GetProperty("className").GetString());
    }

    /// <summary>The title is clamped to one line by the stylesheet alone; the page cuts nothing.</summary>
    [Fact]
    public void ARowsTitleIsClampedToOneLineByTheStylesheet()
    {
        JsonElement row = Scripted.Value.FirstEnd.GetProperty("rows").GetProperty("F-008");

        Assert.Equal("nowrap", row.GetProperty("titleWhiteSpace").GetString());
        Assert.Equal("ellipsis", row.GetProperty("titleOverflow").GetString());
        Assert.Equal(GroupsSample.TitleOf("F-008"), ReviewPageDriver.Strings(row, "texts")[0]);
    }

    /// <summary>A row title that carries markup reaches the screen as characters (FR-029).</summary>
    [Fact]
    public void AHostileRowTitleRendersAsLiteralText()
    {
        JsonElement first = Scripted.Value.FirstEnd;

        Assert.Equal(GroupsSample.HostileTitle, ReviewPageDriver.Strings(first.GetProperty("rows").GetProperty(GroupsSample.HostileRow), "texts")[0]);
        Assert.Equal(0, first.GetProperty("injected").GetInt32());
        Assert.Equal(0, first.GetProperty("handlers").GetInt32());
        Assert.DoesNotContain("<img", first.GetProperty("html").GetString()!);
    }

    /// <summary>
    /// A group with no row prints its goals' state - the backend's `text` - and its goal lines,
    /// and nothing else (grouped-list.md section 3).
    /// </summary>
    [Fact]
    public void AGroupWithNoRowPrintsItsStateAndItsGoalLines()
    {
        JsonElement first = Scripted.Value.FirstEnd;
        int fasteners = Array.IndexOf(GroupsSample.GroupIds, "fasteners");

        Assert.Equal(GroupsSample.GroupTexts[fasteners], ReviewPageDriver.Strings(first, "groupTexts")[fasteners]);
        Assert.Equal(string.Empty, ReviewPageDriver.Strings(first, "groupRows")[fasteners]);
        Assert.Equal(GroupsSample.FastenersGoalTitles, ReviewPageDriver.Strings(first, "fastenersGoalTitles"));
    }

    /// <summary>
    /// The goal lines sit under their group, after its rows, in goal order: title, state in words
    /// and reason, with the recorded sentence behind a shut fold - and none where none was sent.
    /// Until feature 013 these were the summary's own list (feature 009 T024).
    /// </summary>
    [Fact]
    public void AGroupsGoalLinesFollowItsRowsWithTheRecordedSentenceInAShutFold()
    {
        JsonElement goals = Scripted.Value.FirstEnd.GetProperty("interferenceGoals");

        Assert.Equal(GroupsSample.InterferenceGoalTitles, ReviewPageDriver.Strings(goals, "titles"));
        Assert.Equal(GroupsSample.InterferenceGoalStates, ReviewPageDriver.Strings(goals, "states"));
        Assert.Equal(GroupsSample.InterferenceGoalClasses, ReviewPageDriver.Strings(goals, "classes"));
        Assert.Equal(new[] { string.Empty, string.Empty, "a check failed" }, ReviewPageDriver.Strings(goals, "reasons"));
        Assert.Equal(new[] { "none", "none", "shut" }, ReviewPageDriver.Strings(goals, "folds"));
        Assert.Equal(SummarySample.HostileDetail, ReviewPageDriver.Strings(goals, "details")[2]);
        Assert.True(goals.GetProperty("afterRows").GetBoolean(), "the goal lines are not after the group's rows.");
    }

    /// <summary>The checked fold: its title and text, collapsed, and a waived pass's exception tail printed as sent.</summary>
    [Fact]
    public void TheCheckedFoldPrintsItsRowsAndTheExceptionTailAsSent()
    {
        JsonElement row = Scripted.Value.FirstEnd.GetProperty("rows").GetProperty(GroupsSample.CheckedRowIds[0]);

        Assert.Equal(
            new[] { GroupsSample.TitleOf(GroupsSample.CheckedRowIds[0]), GroupsSample.ExceptionTail, "reaches 1 component" },
            ReviewPageDriver.Strings(row, "texts"));
    }

    // ---- where it stands ---------------------------------------------------------------------------

    /// <summary>
    /// In Results, after the summary, the questions and the parts not loaded, and before the
    /// holding list the cards arrive in (grouped-list.md section 5); never in the Transcript.
    /// </summary>
    [Fact]
    public void TheSectionIsInResultsAfterTheSummaryTheQuestionsAndThePartsNotLoaded()
    {
        JsonElement first = Scripted.Value.FirstEnd;

        Assert.True(first.GetProperty("inResults").GetBoolean(), "#findings-by-type is not in #results.");
        Assert.True(first.GetProperty("afterSummary").GetBoolean(), "#findings-by-type must come after #summary.");
        Assert.True(first.GetProperty("afterQuestions").GetBoolean(), "#findings-by-type must come after #questions.");
        Assert.True(first.GetProperty("afterNotExamined").GetBoolean(), "#findings-by-type must come after #not-examined.");
        Assert.True(first.GetProperty("beforeHolding").GetBoolean(), "#findings-by-type must come before #findings.");
        Assert.False(first.GetProperty("inTranscript").GetBoolean(), "#findings-by-type is in the Transcript view.");
    }

    /// <summary>
    /// A review that recorded nothing still shows its groups with their goals' state and no row,
    /// and no checked fold - the sentence and the words are the backend's.
    /// </summary>
    [Fact]
    public void ARankingOfAReviewThatRecordedNothingShowsItsGroupsWithNoRow()
    {
        JsonElement empty = Scripted.Value.EmptyEnd;

        Assert.False(empty.GetProperty("hidden").GetBoolean(), "the section stayed hidden.");
        Assert.Equal(new[] { "interference_fit", "fasteners" }, ReviewPageDriver.Strings(empty, "groupIds"));
        Assert.Equal(new[] { "not reached · evidence missing", "not reached · evidence missing" }, ReviewPageDriver.Strings(empty, "groupTexts"));
        Assert.Equal(new[] { string.Empty, string.Empty }, ReviewPageDriver.Strings(empty, "groupRows"));
    }

    /// <summary>
    /// A ranking with no `groups` - a body shaped like `attention.json`, which never carries them
    /// (grouped-list.md section 3) - shows no section and leaves every card where it arrived.
    /// </summary>
    [Fact]
    public void ARankingWithNoGroupsShowsNoSectionAndMovesNoCard()
    {
        JsonElement none = Scripted.Value.NoGroups;

        Assert.True(none.GetProperty("hidden").GetBoolean(), "#findings-by-type is shown with no groups.");
        Assert.Equal(0, none.GetProperty("children").GetInt32());
        Assert.Equal(new[] { "F-007", "F-008" }, ReviewPageDriver.Strings(none, "holdingIds"));
    }

    // ---- the chat it belongs to -----------------------------------------------------------------

    /// <summary>
    /// A second Review press throws the first chat away, and the section with it: left standing it
    /// would be the previous review's groups over a review that has just started.
    /// </summary>
    [Fact]
    public void ASecondReviewPressClearsAndHidesTheSection()
    {
        JsonElement section = Scripted.Value.AfterSecondPress;

        Assert.True(section.GetProperty("hidden").GetBoolean(), "the section was left showing.");
        Assert.Equal(string.Empty, section.GetProperty("text").GetString());
        Assert.Equal(0, section.GetProperty("children").GetInt32());
    }

    /// <summary>
    /// The answer to a request made for a chat the page has moved on from is dropped: the reply
    /// can land after a second press has cleared the section for the new chat.
    /// </summary>
    [Fact]
    public void AnAnswerThatArrivesAfterTheChatMovedOnIsDiscarded()
    {
        JsonElement section = Scripted.Value.AfterStaleAnswer;

        Assert.True(section.GetProperty("hidden").GetBoolean(), "a stale ranking was shown.");
        Assert.Equal(string.Empty, section.GetProperty("text").GetString());
    }

    // ---- when the read fails ----------------------------------------------------------------

    /// <summary>
    /// A read that fails shows nothing new and breaks nothing else: the cards are in the holding
    /// list already, and the rest of `endSession` - the session-ended line - still runs.
    /// </summary>
    [Fact]
    public void AFailedReadLeavesTheSectionHiddenAndTheRestOfTheEndIntact()
    {
        JsonElement section = Scripted.Value.AfterFailedRead;

        Assert.True(section.GetProperty("hidden").GetBoolean(), "the section was shown after a failed read.");
        Assert.Equal(string.Empty, section.GetProperty("text").GetString());
        Assert.Contains("The session ended", section.GetProperty("transcript").GetString()!);
        Assert.Equal("The session ended.", section.GetProperty("streamState").GetString());
    }

    // ---- driving the real page ------------------------------------------------------------------

    /// <summary>
    /// Loads the page, answers `ready`, `models.list` and `review.start` the way the add-in does -
    /// a fresh chat id on each press - stubs `window.fetch`, and plays the reviews: one that ends
    /// normally with every card of <see cref="GroupsSample"/> delivered, one replaced by a second
    /// press, one whose answer is held until the page has moved on, one that recorded nothing, one
    /// whose ranking carries no groups, and one whose read fails.
    /// </summary>
    private static Conversation Drive()
    {
        var run = new Conversation();
        int chats = 0;

        OffscreenReviewPage.WithPage(
            page =>
            {
                page.WebMessageReceived += (sender, args) =>
                {
                    JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                    string type = message.GetProperty("type").GetString() ?? string.Empty;
                    string id = message.TryGetProperty("id", out JsonElement value)
                        && value.ValueKind == JsonValueKind.String
                            ? value.GetString() ?? string.Empty
                            : string.Empty;

                    switch (type)
                    {
                        case "ready":
                            page.PostWebMessageAsJson(Reply("init", id, Init()));
                            return;
                        case "models.list":
                            page.PostWebMessageAsJson(Reply(
                                "models", id, new { provider = "openai", models = new object[0] }));
                            return;
                        case "review.start":
                            chats++;
                            page.PostWebMessageAsJson(Reply(
                                "review.started",
                                id,
                                new Dictionary<string, object?>
                                {
                                    { "chat_id", "chat-" + chats },
                                    { "run_dir", @"C:\SwReviewRuns\20260916-101500-bracket-" + chats },
                                    { "document", new { path = @"C:\parts\bracket.sldasm", configuration = "Default" } },
                                }));
                            return;
                        default:
                            return;
                    }
                };
            },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);
                await page.ExecuteScriptAsync(FetchStub);
                await Body(page, SummarySample.Json());

                // 1. A review that ends normally, every card of the sample delivered first.
                await StartReview(page);
                int seq = 0;
                foreach (string findingId in GroupsSample.ArrivalOrder)
                {
                    await SseFrames.Push(page, "chat-1", SseFrames.Frame(++seq, "finding", GroupsSample.Finding(findingId)));
                }

                await OffscreenReviewPage.Settled(page);
                await page.ExecuteScriptAsync("window.__attention.calls = [];0");
                await EndSession(page, "chat-1");
                run.FirstEnd = await Read(page);

                // 2. A second press throws that chat away, and the section with it.
                await StartReview(page);
                run.AfterSecondPress = await Read(page);

                // 3. The answer for chat-2 is held until a third press has moved the page on,
                //    then released: it belongs to a Results that is gone.
                await Hold(page, true);
                await EndSession(page, "chat-2");
                await StartReview(page);
                await Hold(page, false);
                await page.ExecuteScriptAsync("window.__attention.release();0");
                await OffscreenReviewPage.Settled(page);
                run.AfterStaleAnswer = await Read(page);

                // 4. A run that recorded nothing: groups with their goals' state, no row.
                await Body(page, SummarySample.EmptyJson());
                await EndSession(page, "chat-3");
                run.EmptyEnd = await Read(page);

                // 5. A ranking with no groups: the cards stay where they arrived.
                await Body(page, AttentionSample.Json());
                await StartReview(page);
                await SseFrames.Push(page, "chat-4", SseFrames.Frame(1, "finding", GroupsSample.Finding("F-007")));
                await SseFrames.Push(page, "chat-4", SseFrames.Frame(2, "finding", GroupsSample.Finding("F-008")));
                await EndSession(page, "chat-4");
                run.NoGroups = await Read(page);

                // 6. A read that fails.
                await StartReview(page);
                await page.ExecuteScriptAsync("window.__attention.fail = true;0");
                await EndSession(page, "chat-5");
                run.AfterFailedRead = await Read(page);
            });

        return run;
    }

    private static async Task StartReview(CoreWebView2 page)
    {
        await page.ExecuteScriptAsync("window.__attention.calls = [];0");
        await page.ExecuteScriptAsync("document.getElementById('start-review').click()");
        await OffscreenReviewPage.Settled(page);
    }

    /// <summary>Plays the contract sample's closing pair at the page, for one chat.</summary>
    private static async Task EndSession(CoreWebView2 page, string chatId)
    {
        foreach (string frame in SseFrames.ContractSampleFrames())
        {
            await SseFrames.Push(page, chatId, frame);
        }

        await OffscreenReviewPage.Settled(page);
    }

    private static Task<string> Body(CoreWebView2 page, string json) =>
        page.ExecuteScriptAsync("window.__attention.body = " + json + ";0");

    private static Task<string> Hold(CoreWebView2 page, bool held) =>
        page.ExecuteScriptAsync("window.__attention.hold = " + (held ? "true" : "false") + ";0");

    /// <summary>
    /// Runs the reporting script in the page and parses what it said: `{ok: true, ...}` or
    /// `{ok: false, error}`, so a page that threw says so here.
    /// </summary>
    private static async Task<JsonElement> Read(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync(SectionState);

        Assert.False(
            string.IsNullOrEmpty(raw) || raw == "null",
            "The page script threw before it could report: " + (raw ?? "<nothing>"));

        string json = JsonDocument.Parse(raw!).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing: " + raw);
        JsonElement state = JsonDocument.Parse(json).RootElement.Clone();

        Assert.True(
            state.GetProperty("ok").GetBoolean(),
            state.TryGetProperty("error", out JsonElement error)
                ? error.GetString()
                : "the page did not report");
        return state;
    }

    /// <summary>
    /// The backend, stubbed. It records every call the page makes - the URL, the method and the
    /// `Authorization` header - and answers with whatever the test last put in `body`. `hold`
    /// makes it keep the promise until `release` is called, which is how the stale answer is
    /// driven without a race; `fail` rejects the way an unreachable backend does.
    /// </summary>
    private const string FetchStub = @"
(function () {
  window.__attention = { calls: [], body: null, hold: false, release: null, fail: false };

  window.fetch = function (url, request) {
    var headers = (request && request.headers) || {};
    window.__attention.calls.push({
      url: String(url),
      method: (request && request.method) || 'GET',
      authorization: headers.Authorization || ''
    });

    if (window.__attention.fail) {
      return Promise.reject(new Error('the review backend is not running.'));
    }

    var body = window.__attention.body;
    var answer = {
      ok: true,
      status: 200,
      text: function () { return Promise.resolve(JSON.stringify(body)); }
    };

    if (window.__attention.hold) {
      return new Promise(function (resolve) {
        window.__attention.release = function () { resolve(answer); };
      });
    }

    return Promise.resolve(answer);
  };
}())
";

    /// <summary>What the section looks like, and what the page asked for to get there.</summary>
    private const string SectionState = @"
(function () {
  function attrs(root, selector, name) {
    var found = root ? root.querySelectorAll(selector) : [];
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute(name)); }
    return out;
  }

  function texts(root, selector) {
    var found = root ? root.querySelectorAll(selector) : [];
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
    return out;
  }

  function before(a, b) {
    return !!a && !!b && !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  }

  try {
    var section = document.getElementById('findings-by-type');
    var groups = section.querySelectorAll('details.type-group');
    var groupRows = [], groupOpen = [], groupTags = [], groupTitles = [], groupTexts = [];
    for (var g = 0; g < groups.length; g++) {
      groupRows.push(attrs(groups[g], 'details.type-row', 'data-finding-id').join('|'));
      groupOpen.push(!!groups[g].open);
      groupTags.push(groups[g].tagName);
      groupTitles.push(groups[g].querySelector(':scope > summary .type-group-title').textContent);
      groupTexts.push(groups[g].querySelector(':scope > summary .type-group-text').textContent);
    }

    var rows = {};
    var rowNodes = section.querySelectorAll('details.type-row');
    for (var r = 0; r < rowNodes.length; r++) {
      var head = rowNodes[r].querySelector(':scope > summary');
      var parts = [], words = [];
      for (var c = 0; c < head.children.length; c++) {
        parts.push(head.children[c].className);
        words.push(head.children[c].textContent);
      }
      var title = head.querySelector('.type-row-title');
      rows[rowNodes[r].getAttribute('data-finding-id')] = {
        className: rowNodes[r].className,
        parts: parts,
        texts: words,
        titleWhiteSpace: getComputedStyle(title).whiteSpace,
        titleOverflow: getComputedStyle(title).textOverflow
      };
    }

    var interference = section.querySelector('details.type-group[data-group=""interference_fit""]');
    var goalNodes = interference ? interference.querySelectorAll('.summary-goal') : [];
    var goals = { titles: [], states: [], classes: [], reasons: [], details: [], folds: [] };
    for (var j = 0; j < goalNodes.length; j++) {
      goals.titles.push(goalNodes[j].querySelector('.goal-title').textContent);
      goals.states.push(goalNodes[j].querySelector('.goal-state').textContent);
      goals.classes.push(goalNodes[j].className);
      var reason = goalNodes[j].querySelector('.goal-reason');
      goals.reasons.push(reason ? reason.textContent : '');
      var fold = goalNodes[j].querySelector('details');
      var detail = fold ? fold.querySelector('.goal-detail') : null;
      goals.details.push(detail ? detail.textContent : '');
      goals.folds.push(fold ? (fold.open ? 'open' : 'shut') : 'none');
    }
    var lastRow = interference ? interference.querySelectorAll('details.type-row') : [];
    goals.afterRows = goalNodes.length > 0 && lastRow.length > 0 && before(lastRow[lastRow.length - 1], goalNodes[0]);

    var fasteners = section.querySelector('details.type-group[data-group=""fasteners""]');

    var handlers = 0;
    var all = section.getElementsByTagName('*');
    for (var k = 0; k < all.length; k++) {
      for (var a = 0; a < all[k].attributes.length; a++) { if (/^on/i.test(all[k].attributes[a].name)) { handlers++; } }
    }

    return JSON.stringify({
      ok: true,
      hidden: !!section.hidden,
      text: section.textContent,
      html: section.innerHTML,
      children: section.childNodes.length,
      groupIds: attrs(section, 'details.type-group', 'data-group'),
      groupTitles: groupTitles,
      groupTexts: groupTexts,
      groupOpen: groupOpen,
      groupTags: groupTags,
      groupRows: groupRows,
      rows: rows,
      interferenceGoals: goals,
      fastenersGoalTitles: texts(fasteners, '.summary-goal .goal-title'),
      holdingIds: attrs(document.getElementById('findings'), ':scope > .card.finding', 'data-finding-id'),
      injected: section.querySelectorAll('img,script,iframe,svg,object,embed,link,style').length,
      handlers: handlers,
      inResults: document.getElementById('results').contains(section),
      inTranscript: document.getElementById('transcript-view').contains(section),
      afterSummary: before(document.getElementById('summary'), section),
      afterQuestions: before(document.getElementById('questions'), section),
      afterNotExamined: before(document.getElementById('not-examined'), section),
      beforeHolding: before(section, document.getElementById('findings')),
      transcript: document.getElementById('transcript').textContent,
      streamState: document.getElementById('stream-state').textContent,
      calls: window.__attention.calls,
      exported: typeof (window.SwReviewRender || {}).typeGroups
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}())
";

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    /// <summary>
    /// The `init` the host sends once the backend is up. A backend and a token are named
    /// because `call` refuses without them, which is the whole point of the header assertion.
    /// </summary>
    private static object Init() => new
    {
        backend = new { port = 51999, origin = Origin },
        token = Token,
        settings = new
        {
            version = 1,
            provider = "openai",
            model = "gpt-5.1",
            effort = "high",
            base_url = (string?)null,
            gemini_enterprise = (object?)null,
            terminal_cli = "codex",
            python = "uv",
            run_root = @"C:\SwReviewRuns",
        },
        key_source = "settings",
        run_root = @"C:\SwReviewRuns",
        providers = new[] { "openai", "gemini" },
        document = new { path = @"C:\parts\bracket.sldasm", configuration = "Default" },
    };

    /// <summary>What the scripted run saw, one snapshot per phase.</summary>
    private sealed class Conversation
    {
        public JsonElement FirstEnd { get; set; }

        public JsonElement AfterSecondPress { get; set; }

        public JsonElement AfterStaleAnswer { get; set; }

        public JsonElement EmptyEnd { get; set; }

        public JsonElement NoGroups { get; set; }

        public JsonElement AfterFailedRead { get; set; }
    }
}
