using System;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// U8's rule on the two check tabs (docs/pane-findings-2026-09-20-review-gui.md section 1, the
/// analyst's "check pages" recommendation): a result is bound to the document it graded.
///
/// Both tabs restore the newest check folder on init whatever the open document, and both kept
/// the previous result on screen after `document.changed` - with Show in SOLIDWORKS and Accept
/// live against a model that was no longer the one open. `web/shared/check-page.js` now hides
/// the result and says whose it is when the open document is another one, disables Open report
/// and Open check folder, and undoes all of it when the graded document comes back. One rule
/// for both tabs, because it is written once in the shared half; each tab is driven here once so
/// a page that forgot to mark part of its result as the result fails by name.
///
/// The rule is the one the Review tab uses, from `web/shared/document.js`: the path ignoring
/// case, the configuration exactly, and no document at all is never the graded one.
/// </summary>
public sealed class CheckPageDocumentBindingTests
{
    private static readonly Lazy<Phases> ModelCheck = new Lazy<Phases>(() => Drive(
        ModelCheckPageFiles.PageUrl,
        CheckResultSample.Json(),
        new { path = @"C:\vault\bracket.sldprt", configuration = "Default", kind = "part" },
        "20260916-101532-bracket-check",
        "grade"));

    private static readonly Lazy<Phases> Standards = new Lazy<Phases>(() => Drive(
        StandardsPageFiles.PageUrl,
        StandardsResultSample.Json(),
        new { path = @"C:\vault\top-plate.sldasm", configuration = "AsBuilt", kind = "assembly" },
        "20260917-101532-top-plate-standards",
        "verdict"));

    [Fact]
    public void TheModelCheckResultOfTheOpenDocumentIsShownWithNoLineAboutIt()
    {
        AssertBound(ModelCheck.Value.Bound, "grade");
    }

    [Fact]
    public void AnotherDocumentHidesTheModelCheckResultAndSaysWhoseItIs()
    {
        JsonElement state = ModelCheck.Value.Elsewhere;

        Assert.Equal(
            "This result is for bracket.sldprt [Default]. The open document is plate.sldprt [Default].",
            Text(state, "staleText"));
        AssertHidden(state, "grade");
        Assert.False(Flag(state, "runCheckDisabled"), "Model check is refused for the open document.");
    }

    [Fact]
    public void TheGradedDocumentComingBackRestoresTheModelCheckResultWhateverTheCase()
    {
        AssertBound(ModelCheck.Value.Back, "grade");
    }

    [Fact]
    public void NoDocumentOpenHidesTheModelCheckResultAndSaysSo()
    {
        JsonElement state = ModelCheck.Value.NoDocument;

        Assert.Equal(
            "This result is for bracket.sldprt [Default]. No document is open.",
            Text(state, "staleText"));
        AssertHidden(state, "grade");
    }

    /// <summary>
    /// The Standards tab's result is larger - the verdict and the sixteen-check roster as well as
    /// the ranked rows, the chips and the rules - and all of it is the result.
    /// </summary>
    [Fact]
    public void AnotherDocumentHidesTheWholeStandardsResultIncludingTheRoster()
    {
        Phases run = Standards.Value;

        AssertBound(run.Bound, "verdict");
        Assert.True(Flag(run.Bound, "roster"), "the sixteen-check roster is not shown.");

        Assert.Equal(
            "This result is for top-plate.sldasm [AsBuilt]. The open document is plate.sldprt [Default].",
            Text(run.Elsewhere, "staleText"));
        AssertHidden(run.Elsewhere, "verdict");
        Assert.False(Flag(run.Elsewhere, "roster"), "the sixteen-check roster is still shown.");

        AssertBound(run.Back, "verdict");
    }

    /// <summary>
    /// A result rendered before the host has said anything about the open document is not
    /// judged against it: "no answer yet" is not "no document open", and a page that hid its
    /// result on load would hide it on every tab switch before `init` arrived.
    /// </summary>
    [Fact]
    public void AResultRenderedBeforeTheHostNamesADocumentIsNotHidden()
    {
        JsonElement rendered = OffscreenModelCheckPage.Evaluate(
            "check(" + CheckResultSample.Json() + ");"
            + "return JSON.stringify({ok: true, "
            + "staleHidden: !!document.getElementById('stale-result').hidden, "
            + "rules: document.getElementById('rules').getClientRects().length > 0});");

        Assert.True(rendered.GetProperty("staleHidden").GetBoolean(), "the line was shown before init.");
        Assert.True(rendered.GetProperty("rules").GetBoolean(), "the result was hidden before init.");
    }

    // ---- assertions -------------------------------------------------------------------------

    private static void AssertBound(JsonElement state, string headerId)
    {
        Assert.True(state.GetProperty("staleHidden").GetBoolean(), "the line is shown for the graded document.");
        Assert.True(Flag(state, headerId), "#" + headerId + " is not shown.");
        Assert.True(Flag(state, "attention"), "Start here is not shown.");
        Assert.True(Flag(state, "filters"), "the chips are not shown.");
        Assert.True(Flag(state, "rules"), "the rules are not shown.");
        Assert.False(Flag(state, "reportDisabled"), "Open report is disabled.");
        Assert.False(Flag(state, "folderDisabled"), "Open check folder is disabled.");
    }

    private static void AssertHidden(JsonElement state, string headerId)
    {
        Assert.False(state.GetProperty("staleHidden").GetBoolean(), "the line was not shown.");
        Assert.False(Flag(state, headerId), "#" + headerId + " is still shown.");
        Assert.False(Flag(state, "attention"), "Start here is still shown.");
        Assert.False(Flag(state, "filters"), "the chips are still shown.");
        Assert.False(Flag(state, "rules"), "the rules are still shown.");
        Assert.False(Flag(state, "carried"), "the carried-forward line is still shown.");
        Assert.True(Flag(state, "reportDisabled"), "Open report is still enabled.");
        Assert.True(Flag(state, "folderDisabled"), "Open check folder is still enabled.");
    }

    private static bool Flag(JsonElement state, string name) => state.GetProperty(name).GetBoolean();

    private static string Text(JsonElement state, string name) => state.GetProperty(name).GetString()!;

    // ---- driving the real pages ------------------------------------------------------------------

    /// <summary>
    /// Loads a check page whose `init` names the graded document and the check folder this
    /// session left behind, answers the re-read with <paramref name="result"/>, and then moves
    /// the open document away, back (in another case) and to nothing.
    /// </summary>
    private static Phases Drive(string pageUrl, string result, object document, string checkId, string headerId)
    {
        var run = new Phases();
        string? readyId = null;

        OffscreenReviewPage.WithPage(
            pageUrl,
            page =>
            {
                page.WebMessageReceived += (sender, args) =>
                {
                    JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                    if (message.GetProperty("type").GetString() == "ready" && readyId == null)
                    {
                        readyId = message.GetProperty("id").GetString();
                    }
                };
            },
            async page =>
            {
                // The first `ready` is held until `fetch` is stubbed, so the re-read of the
                // check folder `init` names is answered by the sample and by nothing else.
                await OffscreenReviewPage.Settled(page);
                Assert.NotNull(readyId);
                await page.ExecuteScriptAsync(
                    "window.fetch = function () { return Promise.resolve({ok: true, status: 200, "
                    + "text: function () { return Promise.resolve(" + JsonSerializer.Serialize(result)
                    + "); }}); };0");
                page.PostWebMessageAsJson(JsonSerializer.Serialize(new
                {
                    type = "init",
                    id = readyId,
                    payload = new
                    {
                        backend = new { port = 51234, origin = "https://swreview.invalid/__backend" },
                        token = "0FAKEtoken",
                        run_root = @"C:\SwReviewRuns",
                        profile_path = @"C:\Users\pilot\AppData\Local\SwReview\standards.yaml",
                        document,
                        latest_check = new { run_dir = @"C:\SwReviewRuns\" + checkId },
                    },
                }));
                await OffscreenReviewPage.Settled(page);
                run.Bound = await Read(page, headerId);

                await DocumentChanged(page, new { path = @"C:\vault\plate.sldprt", configuration = "Default", kind = "part" });
                run.Elsewhere = await Read(page, headerId);

                await DocumentChanged(page, Upper(document));
                run.Back = await Read(page, headerId);

                await DocumentChanged(page, null);
                run.NoDocument = await Read(page, headerId);
            });

        return run;
    }

    /// <summary>The same document with its path in capitals, which is the same file on Windows.</summary>
    private static object Upper(object document)
    {
        JsonElement parsed = JsonDocument.Parse(JsonSerializer.Serialize(document)).RootElement;
        return new
        {
            path = parsed.GetProperty("path").GetString()!.ToUpperInvariant(),
            configuration = parsed.GetProperty("configuration").GetString(),
            kind = parsed.GetProperty("kind").GetString(),
        };
    }

    private static async Task DocumentChanged(CoreWebView2 page, object? document)
    {
        page.PostWebMessageAsJson(JsonSerializer.Serialize(
            new { type = "document.changed", id = (string?)null, payload = document }));
        await OffscreenReviewPage.Settled(page);
    }

    private static async Task<JsonElement> Read(CoreWebView2 page, string headerId)
    {
        string raw = await page.ExecuteScriptAsync(ReadState.Replace("@@HEADER@@", headerId));
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

    private const string ReadState = @"
(function () {
  function byId(id) { return document.getElementById(id); }
  function rendered(id) { var node = byId(id); return !!node && node.getClientRects().length > 0; }

  try {
    var line = byId('stale-result');
    var state = {
      ok: true,
      staleHidden: !!line.hidden,
      staleText: line.textContent,
      attention: rendered('attention'),
      filters: rendered('filters'),
      rules: rendered('rules'),
      carried: rendered('carried-forward'),
      roster: rendered('checks'),
      reportDisabled: !!byId('open-report').disabled,
      folderDisabled: !!byId('open-folder').disabled,
      runCheckDisabled: !!byId('run-check').disabled
    };
    state['@@HEADER@@'] = rendered('@@HEADER@@');
    return JSON.stringify(state);
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}())
";

    private sealed class Phases
    {
        public JsonElement Bound { get; set; }

        public JsonElement Elsewhere { get; set; }

        public JsonElement Back { get; set; }

        public JsonElement NoDocument { get; set; }
    }
}
