using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// U8 (docs/pane-findings-2026-09-20-review-gui.md section 1): the review on the Review tab is
/// bound to the document it is of.
///
/// <b>What was wrong.</b> Opening another model only repainted the header, so the header could
/// name 810-11281 while the body still showed the previous assembly's Start here, findings and
/// evidence requests - with Accept, Reject, Show in SOLIDWORKS and a follow-up box all live
/// against a model that was no longer on screen. The page now keeps `state.reviewed` from
/// `review.started`, and when `document.changed` names anything else it hides the previous
/// results, disables what would act on them and says, in one line, whose review it is. Going
/// back to the reviewed document undoes it; Clear review forgets the review outright.
///
/// <b>How it is driven.</b> The real page in a real WebView2, the host end of the bridge played
/// by this test as <see cref="ReviewPageAttentionPanelTests"/> plays it, `window.fetch` stubbed
/// for the attention read. One boot and one scripted conversation, read by every test below.
/// Visibility is read with `getClientRects()`, which is what the engineer sees: a card that is
/// still in the DOM but not rendered is hidden, and one that comes back is the same card.
/// </summary>
public sealed class ReviewPageDocumentBindingTests
{
    private static readonly Lazy<Conversation> Scripted = new Lazy<Conversation>(Drive);

    private const string ReviewedPath = @"C:\parts\bracket.sldasm";

    private const string OtherPath = @"C:\parts\other.SLDPRT";

    // ---- the header -------------------------------------------------------------------------

    /// <summary>
    /// The header names the file, not the path: a full path clipped at the end of a 300 px
    /// strip loses exactly the part that says which model it is. The path is still one hover
    /// away, in the title.
    /// </summary>
    [Fact]
    public void TheHeaderShowsTheFileNameWithTheFullPathInItsTitle()
    {
        Conversation run = Scripted.Value;

        Assert.Equal("bracket.sldasm [Default]", Text(run.Bound, "header"));
        Assert.Equal(ReviewedPath, Text(run.Bound, "headerTitle"));

        Assert.Equal("other.SLDPRT [Machined]", Text(run.Elsewhere, "header"));
        Assert.Equal(OtherPath, Text(run.Elsewhere, "headerTitle"));

        Assert.Equal("No document open", Text(run.NoDocument, "header"));
        Assert.Equal(JsonValueKind.Null, run.NoDocument.GetProperty("headerTitle").ValueKind);
    }

    // ---- the document on screen is the reviewed one ------------------------------------------

    [Fact]
    public void AReviewOfTheOpenDocumentShowsEverythingAndNoLineAboutIt()
    {
        AssertBound(Scripted.Value.Bound);
    }

    // ---- another document ---------------------------------------------------------------------

    /// <summary>
    /// Another document hides Start here, the not-examined warning, the coverage fold and every
    /// finding and evidence card, and disables Open report, Open run folder and the follow-up.
    /// Review stays pressable - reviewing the document on screen is exactly what the line says
    /// to do - and nothing about the previous review is thrown away.
    /// </summary>
    [Fact]
    public void AnotherDocumentHidesThePreviousResultsAndSaysWhoseReviewItIs()
    {
        JsonElement state = Scripted.Value.Elsewhere;

        Assert.False(state.GetProperty("staleHidden").GetBoolean(), "the line was not shown.");
        Assert.Equal(
            "This review is of bracket.sldasm [Default]. Press Review to review other.SLDPRT [Machined].",
            Text(state, "staleText"));

        AssertResultsHidden(state);
        Assert.Equal(1, state.GetProperty("findingCards").GetInt32());

        Assert.False(Flag(state, "reviewDisabled"), "Review was disabled for the open document.");
        Assert.True(Flag(state, "stopDisabled"), "Stop is enabled with no turn running.");
        Assert.False(Flag(state, "clearDisabled"), "Clear review is refused with no turn running.");
    }

    /// <summary>
    /// Going back undoes it, and "back" is decided the way Windows decides it: a path that
    /// differs only in case is the same file.
    /// </summary>
    [Fact]
    public void ReturningToTheReviewedDocumentRestoresItWhateverTheCaseOfItsPath()
    {
        AssertBound(Scripted.Value.Back);
    }

    /// <summary>
    /// A review of one configuration is not a review of another: the suppression states, the
    /// mates and the interference groups are all per configuration.
    /// </summary>
    [Fact]
    public void AnotherConfigurationOfTheSameDocumentIsAnotherDocument()
    {
        JsonElement state = Scripted.Value.OtherConfiguration;

        Assert.Equal(
            "This review is of bracket.sldasm [Default]. Press Review to review bracket.sldasm [Machined].",
            Text(state, "staleText"));
        AssertResultsHidden(state);
    }

    /// <summary>No document at all is not the reviewed document either (null is a mismatch).</summary>
    [Fact]
    public void ClosingEveryDocumentHidesTheReviewAndSaysNoDocumentIsOpen()
    {
        JsonElement state = Scripted.Value.NoDocument;

        Assert.Equal(
            "This review is of bracket.sldasm [Default]. No document is open.",
            Text(state, "staleText"));
        AssertResultsHidden(state);
        Assert.True(Flag(state, "reviewDisabled"), "Review is pressable with no document open.");
    }

    /// <summary>
    /// A `review.started` that names no document is never taken to be the document on screen.
    /// The host always names one; a page that guessed would bind a review to whatever happened
    /// to be open when the reply arrived.
    /// </summary>
    [Fact]
    public void AReviewThatNamesNoDocumentIsNeverTakenForTheOpenOne()
    {
        JsonElement state = Scripted.Value.UnnamedReview;

        Assert.False(state.GetProperty("staleHidden").GetBoolean(), "the line was not shown.");
        Assert.Equal(
            "This review is of another document. Press Review to review bracket.sldasm [Default].",
            Text(state, "staleText"));
        Assert.True(Flag(state, "reportDisabled"), "Open report acts on an unnamed review.");
    }

    // ---- Clear review -------------------------------------------------------------------------

    /// <summary>
    /// Clear review empties the pane without opening another document and without spending a
    /// token: the transcript, Start here, the warning and the coverage go, the chat and its run
    /// folder are forgotten, and every control that acted on them is disabled. Since feature 009
    /// the findings are in Results' own list, so "the transcript" is both of them.
    /// </summary>
    [Fact]
    public void ClearReviewEmptiesThePaneAndForgetsTheChat()
    {
        JsonElement state = Scripted.Value.Cleared;

        Assert.Equal(0, state.GetProperty("transcriptChildren").GetInt32());
        Assert.Equal(0, state.GetProperty("attentionChildren").GetInt32());
        Assert.False(Flag(state, "attention"), "Start here survived Clear review.");
        Assert.False(Flag(state, "notExamined"), "the warning survived Clear review.");
        Assert.False(Flag(state, "coverage"), "the coverage fold survived Clear review.");
        Assert.Equal(string.Empty, Text(state, "runDir"));
        Assert.True(state.GetProperty("staleHidden").GetBoolean(), "the line survived Clear review.");

        Assert.True(Flag(state, "reportDisabled"), "Open report is enabled with no review.");
        Assert.True(Flag(state, "folderDisabled"), "Open run folder is enabled with no review.");
        Assert.True(Flag(state, "followupDisabled"), "the follow-up is enabled with no review.");
        Assert.True(Flag(state, "clearDisabled"), "Clear review is offered with nothing to clear.");
        Assert.False(Flag(state, "reviewDisabled"), "Review is disabled after Clear review.");
    }

    // ---- a turn that is still running ---------------------------------------------------------

    /// <summary>
    /// While a turn runs, another document still hides the results - but Stop stays enabled,
    /// because a running turn is spending tokens whatever document is on screen (FR-030).
    /// Clear review is disabled and, pressed anyway, refused: clearing would orphan a turn the
    /// backend is still running, with no Stop left pointing at it.
    /// </summary>
    [Fact]
    public void WhileATurnRunsStopStaysEnabledAndClearReviewIsRefused()
    {
        Conversation run = Scripted.Value;
        JsonElement state = run.RunningElsewhere;

        Assert.False(Flag(state, "stopDisabled"), "Stop was disabled while a turn runs.");
        Assert.True(Flag(state, "clearDisabled"), "Clear review is offered while a turn runs.");
        Assert.True(Flag(state, "followupDisabled"), "the follow-up is enabled while a turn runs.");
        Assert.True(Flag(state, "reportDisabled"), "Open report acts on another document's review.");
        Assert.False(state.GetProperty("staleHidden").GetBoolean(), "the line was not shown.");

        JsonElement refused = run.AfterRefusedClear;
        Assert.EndsWith("bracket-2", Text(refused, "runDir"));
        Assert.Equal(2, refused.GetProperty("findingCards").GetInt32());
        Assert.False(Flag(refused, "stopDisabled"), "the refused Clear review disabled Stop.");
    }

    /// <summary>
    /// A finding that streams in while another document is open is hidden like the rest, and
    /// is there when the reviewed document comes back: hiding is a class on the page, not a
    /// filter on the stream.
    /// </summary>
    [Fact]
    public void AFindingThatArrivesWhileAnotherDocumentIsOpenIsShownWhenTheReviewedOneReturns()
    {
        Conversation run = Scripted.Value;

        Assert.Equal(0, run.AfterRefusedClear.GetProperty("renderedFindings").GetInt32());
        Assert.Equal(2, run.RunningBack.GetProperty("renderedFindings").GetInt32());
        Assert.True(run.RunningBack.GetProperty("staleHidden").GetBoolean(), "the line stayed.");
        Assert.False(Flag(run.RunningBack, "stopDisabled"), "Stop was disabled on the way back.");
    }

    // ---- the shared rule --------------------------------------------------------------------

    /// <summary>
    /// "Is this the same document" is one rule, written once in `web/shared/document.js` and
    /// read by the Review page and both check pages: the path ignoring case, the configuration
    /// exactly, and nothing on either side is never a match.
    /// </summary>
    [Theory]
    [InlineData(@"C:\parts\a.sldprt", "Default", @"C:\parts\a.sldprt", "Default", true)]
    [InlineData(@"C:\parts\a.sldprt", "Default", @"c:\PARTS\A.SLDPRT", "Default", true)]
    [InlineData(@"C:\parts\a.sldprt", "Default", @"C:\parts\a.sldprt", "Machined", false)]
    [InlineData(@"C:\parts\a.sldprt", "Default", @"C:\parts\a.sldprt", "default", false)]
    [InlineData(@"C:\parts\a.sldprt", null, @"C:\parts\a.sldprt", null, true)]
    [InlineData(@"C:\parts\a.sldprt", null, @"C:\parts\a.sldprt", "Default", false)]
    [InlineData(@"C:\parts\a.sldprt", "Default", @"C:\parts\b.sldprt", "Default", false)]
    [InlineData(null, null, @"C:\parts\a.sldprt", "Default", false)]
    [InlineData(@"C:\parts\a.sldprt", "Default", null, null, false)]
    [InlineData("", "Default", "", "Default", false)]
    public void TheSameDocumentRuleComparesThePathIgnoringCaseAndTheConfigurationExactly(
        string? leftPath, string? leftConfiguration, string? rightPath, string? rightConfiguration, bool same)
    {
        string left = Info(leftPath, leftConfiguration);
        string right = Info(rightPath, rightConfiguration);

        JsonElement answer = OffscreenReviewPage.Evaluate(
            "return JSON.stringify({ok: true, same: window.SwReviewDocument.same("
            + left + ", " + right + "), reverse: window.SwReviewDocument.same(" + right + ", " + left + ")});");

        Assert.Equal(same, answer.GetProperty("same").GetBoolean());
        Assert.Equal(same, answer.GetProperty("reverse").GetBoolean());
    }

    /// <summary>
    /// A document is named by its file and its configuration, the way the header and the line
    /// both print it: Windows and POSIX separators, no configuration, and nothing at all.
    /// </summary>
    [Fact]
    public void ADocumentIsLabelledByItsFileNameAndConfiguration()
    {
        JsonElement answer = OffscreenReviewPage.Evaluate(
            "var d = window.SwReviewDocument;"
            + "return JSON.stringify({ok: true, "
            + "windows: d.label({path: 'C:\\\\parts\\\\bracket.sldasm', configuration: 'Default'}), "
            + "posix: d.label({path: '/mnt/parts/plate.sldprt', configuration: null}), "
            + "bare: d.label({path: 'pin.sldprt'}), "
            + "none: d.label(null), "
            + "file: d.fileName('C:\\\\a\\\\b/c.slddrw')});");

        Assert.Equal("bracket.sldasm [Default]", Text(answer, "windows"));
        Assert.Equal("plate.sldprt", Text(answer, "posix"));
        Assert.Equal("pin.sldprt", Text(answer, "bare"));
        Assert.Equal(string.Empty, Text(answer, "none"));
        Assert.Equal("c.slddrw", Text(answer, "file"));
    }

    /// <summary>
    /// The rule is loaded by every page that binds a result to a document, before the scripts
    /// that read it, and no page script keeps a copy of it.
    /// </summary>
    [Fact]
    public void EveryPageThatBindsAResultLoadsTheSharedDocumentScriptFirst()
    {
        foreach (KeyValuePair<string, string> page in new[]
                 {
                     new KeyValuePair<string, string>("render.js", ReviewPageFiles.IndexHtml()),
                     new KeyValuePair<string, string>("shared/check-page.js", ModelCheckPageFiles.IndexHtml()),
                     new KeyValuePair<string, string>("shared/check-page.js", StandardsPageFiles.IndexHtml()),
                 })
        {
            int shared = page.Value.IndexOf("src=\"../../shared/document.js\"", StringComparison.Ordinal);
            int reader = page.Value.IndexOf("src=\"" + (page.Key.StartsWith("shared/", StringComparison.Ordinal)
                ? "../../" + page.Key
                : page.Key) + "\"", StringComparison.Ordinal);

            Assert.True(shared >= 0, "a page does not load ../../shared/document.js.");
            Assert.True(reader > shared, "shared/document.js must load before " + page.Key + ".");
        }

        string check = File.ReadAllText(Path.Combine(PageScripts.SharedFolder, "check-page.js"));
        string app = ReviewPageFiles.Read("app.js");
        foreach (string name in new[] { "fileName", "label", "same" })
        {
            Assert.False(Defines(check, name), "shared/check-page.js still defines " + name + ".");
            Assert.False(Defines(app, name), "app.js defines its own " + name + ".");
        }
    }

    // ---- assertions -------------------------------------------------------------------------

    private static void AssertBound(JsonElement state)
    {
        Assert.True(state.GetProperty("staleHidden").GetBoolean(), "the line is shown for the reviewed document.");
        Assert.True(Flag(state, "attention"), "Start here is not shown.");
        Assert.True(Flag(state, "notExamined"), "the not-examined warning is not shown.");
        Assert.True(Flag(state, "coverage"), "the coverage fold is not shown.");
        Assert.True(Flag(state, "evidence"), "the evidence request is not shown.");
        Assert.Equal(1, state.GetProperty("renderedFindings").GetInt32());

        Assert.False(Flag(state, "reportDisabled"), "Open report is disabled.");
        Assert.False(Flag(state, "folderDisabled"), "Open run folder is disabled.");
        Assert.False(Flag(state, "followupDisabled"), "the follow-up is disabled.");
        Assert.False(Flag(state, "clearDisabled"), "Clear review is disabled.");
    }

    private static void AssertResultsHidden(JsonElement state)
    {
        Assert.False(Flag(state, "attention"), "Start here is still shown.");
        Assert.False(Flag(state, "notExamined"), "the not-examined warning is still shown.");
        Assert.False(Flag(state, "coverage"), "the coverage fold is still shown.");
        Assert.False(Flag(state, "evidence"), "an evidence request is still shown.");
        Assert.Equal(0, state.GetProperty("renderedFindings").GetInt32());

        Assert.True(Flag(state, "reportDisabled"), "Open report is still enabled.");
        Assert.True(Flag(state, "folderDisabled"), "Open run folder is still enabled.");
        Assert.True(Flag(state, "followupDisabled"), "the follow-up is still enabled.");
    }

    private static bool Flag(JsonElement state, string name) => state.GetProperty(name).GetBoolean();

    private static string Text(JsonElement state, string name) => state.GetProperty(name).GetString()!;

    private static string Info(string? path, string? configuration) =>
        path == null ? "null" : JsonSerializer.Serialize(new { path, configuration });

    private static bool Defines(string source, string name) =>
        Regex.IsMatch(source, @"\bfunction\s+" + Regex.Escape(name) + @"\s*\(");

    // ---- driving the real page ----------------------------------------------------------------

    private static Conversation Drive()
    {
        var run = new Conversation();
        int chats = 0;
        object? reviewedDocument = new { path = ReviewedPath, configuration = "Default" };

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
                                    { "run_dir", @"C:\SwReviewRuns\20260922-101500-bracket-" + chats },
                                    { "not_examined", new { sentence = NotExaminedSentence, instances = new object[0] } },
                                    { "document", reviewedDocument },
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

                // 1. A review of the open document, ended, with every kind of result on screen.
                await Click(page, "start-review");
                await Push(page, "chat-1", 1, "finding", Finding("F-007"));
                await Push(page, "chat-1", 2, "evidence.requested", Evidence);
                await Push(page, "chat-1", 3, "coverage", Coverage);
                await EndSession(page, "chat-1");
                run.Bound = await Read(page);

                // 2. Another document.
                await DocumentChanged(page, new { path = OtherPath, configuration = "Machined" });
                run.Elsewhere = await Read(page);

                // 3. The reviewed one again, its path in another case.
                await DocumentChanged(page, new { path = @"C:\PARTS\BRACKET.SLDASM", configuration = "Default" });
                run.Back = await Read(page);

                // 4. The same file in another configuration.
                await DocumentChanged(page, new { path = ReviewedPath, configuration = "Machined" });
                run.OtherConfiguration = await Read(page);

                // 5. Nothing open.
                await DocumentChanged(page, null);
                run.NoDocument = await Read(page);

                // 6. Back to the reviewed document, then Clear review.
                await DocumentChanged(page, new { path = ReviewedPath, configuration = "Default" });
                await Click(page, "clear-review");
                run.Cleared = await Read(page);

                // 7. A second review whose turn is still running, then another document, then a
                //    finding while it is open, then a Clear review forced past its disabled
                //    button, then the reviewed document again.
                await Click(page, "start-review");
                await Push(page, "chat-2", 1, "finding", Finding("F-008"));
                await DocumentChanged(page, new { path = OtherPath, configuration = "Machined" });
                run.RunningElsewhere = await Read(page);

                await Push(page, "chat-2", 2, "finding", Finding("F-009"));
                await page.ExecuteScriptAsync(
                    "var clear = document.getElementById('clear-review'); clear.disabled = false; clear.click();0");
                await OffscreenReviewPage.Settled(page);
                run.AfterRefusedClear = await Read(page);

                await DocumentChanged(page, new { path = ReviewedPath, configuration = "Default" });
                run.RunningBack = await Read(page);

                // 8. End that turn, clear it, and start a review whose reply names no document.
                await EndSession(page, "chat-2");
                await Click(page, "clear-review");
                reviewedDocument = null;
                await Click(page, "start-review");
                run.UnnamedReview = await Read(page);
            });

        return run;
    }

    private const string NotExaminedSentence =
        "Not examined: 1 of 4 component instances were not read: DOWEL PIN cmp:0004 (lightweight).";

    private const string Evidence =
        @"{""id"":""ER-001"",""what"":""Which drawing governs the pin fit?"","
        + @"""why"":""The fit cannot be checked without limits."",""entity_ids"":[""cmp:0002""]}";

    private const string Coverage =
        @"{""bucket"":""unresolved"",""item"":{""check"":""interfaces.fit"",""reason"":""no drawing""}}";

    private static string Finding(string id) => JsonSerializer.Serialize(new
    {
        id,
        check = "interference.static",
        title = "The pin interferes with the bore it is pressed into",
        status = "demonstrated",
        severity = "medium",
        component_ids = new[] { "cmp:0002", "cmp:0003" },
        observed = "Largest overlap 0.012 mm in configuration Default.",
    });

    private static async Task Click(CoreWebView2 page, string elementId)
    {
        await page.ExecuteScriptAsync("document.getElementById('" + elementId + "').click()");
        await OffscreenReviewPage.Settled(page);
    }

    private static async Task Push(CoreWebView2 page, string chatId, int seq, string type, string body)
    {
        await SseFrames.Push(page, chatId, SseFrames.Frame(seq, type, body));
        await OffscreenReviewPage.Settled(page);
    }

    private static async Task EndSession(CoreWebView2 page, string chatId)
    {
        foreach (string frame in SseFrames.ContractSampleFrames())
        {
            await SseFrames.Push(page, chatId, frame);
        }

        await OffscreenReviewPage.Settled(page);
    }

    private static async Task DocumentChanged(CoreWebView2 page, object? document)
    {
        page.PostWebMessageAsJson(JsonSerializer.Serialize(
            new { type = "document.changed", id = (string?)null, payload = document }));
        await OffscreenReviewPage.Settled(page);
    }

    private static async Task<JsonElement> Read(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync(ReadState);
        Assert.False(
            string.IsNullOrEmpty(raw) || raw == "null",
            "The page script threw before it could report: " + (raw ?? "<nothing>"));

        string json = JsonDocument.Parse(raw!).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing: " + raw);
        JsonElement state = JsonDocument.Parse(json).RootElement.Clone();
        Assert.True(
            state.GetProperty("ok").GetBoolean(),
            state.TryGetProperty("error", out JsonElement error) ? error.GetString() : "the page did not report");
        return state;
    }

    /// <summary>The attention read, answered with the shared sample.</summary>
    private static readonly string FetchStub = @"
(function () {
  var body = " + AttentionSample.Json() + @";
  window.fetch = function () {
    return Promise.resolve({
      ok: true,
      status: 200,
      text: function () { return Promise.resolve(JSON.stringify(body)); }
    });
  };
}())
";

    /// <summary>What the engineer sees, read from the DOM only.</summary>
    private const string ReadState = @"
(function () {
  function byId(id) { return document.getElementById(id); }
  function rendered(node) { return !!node && node.getClientRects().length > 0; }
  function disabled(id) { return !!byId(id).disabled; }

  try {
    var line = byId('stale-review');
    // The findings live in Results and the evidence record in the Transcript since feature 009
    // (User Story 5): the record is read in the Transcript view, which is where it is seen.
    var cards = document.querySelectorAll('#findings .card.finding');
    var shown = 0;
    for (var i = 0; i < cards.length; i++) { if (rendered(cards[i])) { shown++; } }
    byId('view-transcript').click();
    var evidence = rendered(document.querySelector('#transcript .card.evidence'));
    byId('view-results').click();

    return JSON.stringify({
      ok: true,
      header: byId('document-name').textContent,
      headerTitle: byId('document-name').getAttribute('title'),
      staleHidden: !!line.hidden,
      staleText: line.textContent,
      attention: rendered(byId('attention-panel')),
      notExamined: rendered(byId('not-examined')),
      coverage: rendered(byId('coverage-panel')),
      evidence: evidence,
      findingCards: cards.length,
      renderedFindings: shown,
      reviewDisabled: disabled('start-review'),
      stopDisabled: disabled('stop-turn'),
      reportDisabled: disabled('open-report'),
      folderDisabled: disabled('open-folder'),
      followupDisabled: disabled('followup-text') && disabled('followup-send'),
      clearDisabled: disabled('clear-review'),
      runDir: byId('run-dir').textContent,
      transcriptChildren: byId('transcript').children.length + byId('findings').children.length,
      attentionChildren: byId('attention-panel').children.length
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}())
";

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    private static object Init() => new
    {
        backend = new { port = 51999, origin = "http://127.0.0.1:51999" },
        token = "0FAKEtoken-for-the-page-tests",
        settings = new
        {
            version = 1,
            provider = "openai",
            model = "gpt-5.6",
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
        document = new { path = ReviewedPath, configuration = "Default" },
    };

    /// <summary>What the scripted run saw, one snapshot per phase.</summary>
    private sealed class Conversation
    {
        public JsonElement Bound { get; set; }

        public JsonElement Elsewhere { get; set; }

        public JsonElement Back { get; set; }

        public JsonElement OtherConfiguration { get; set; }

        public JsonElement NoDocument { get; set; }

        public JsonElement Cleared { get; set; }

        public JsonElement RunningElsewhere { get; set; }

        public JsonElement AfterRefusedClear { get; set; }

        public JsonElement RunningBack { get; set; }

        public JsonElement UnnamedReview { get; set; }
    }
}
