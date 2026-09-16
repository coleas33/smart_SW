using System;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The Ask tab's evidence line and its Extract evidence button, driven through the real page.
///
/// <b>Why this is driven rather than scanned.</b> `TerminalPageContractTests` proves the page
/// and the host share one vocabulary and that every element the script looks up exists; neither
/// says what the engineer sees. This half is the whole point of the button: a CLI started over a
/// folder with no package can answer nothing about the model, and before this line the only clue
/// was one failed tool call per question.
///
/// Three states, and each of them is a sentence an engineer acts on: no evidence yet (so press
/// the button), extraction in flight (so do not press it again), and a package in the folder (so
/// the CLI can be asked). The fourth is a refusal - no document open, or a dump that failed -
/// where the button has to come back, because the engineer's next move is to open the model and
/// press it again.
///
/// The host end is played by the test, answering `ready` and `evidence.extract` exactly as
/// <see cref="Terminal.TerminalHost"/> answers them.
/// </summary>
public sealed class TerminalPageEvidenceTests
{
    private const string RunDir = @"C:\SwReviewRuns\20260913-140506-terminal";

    private const string NoEvidence =
        "No evidence for this session yet, so the CLI has nothing to read about the model.";

    private const string HasEvidence = "This session folder holds an evidence package.";

    private const string Refusal =
        "this pane cannot extract evidence: it is not attached to a SOLIDWORKS document yet. "
        + "Open a document, then try again.";

    /// <summary>
    /// Before anything is pressed. This also proves `start()` ran to its end: the page renders
    /// the evidence line *before* it posts `ready`, so an element it could not find would throw
    /// inside `start`, `ready` would never be sent, and the CLI dropdown would stay empty and
    /// Start disabled with no banner to say why.
    /// </summary>
    [Fact]
    public void AnEmptyRunFolderSaysSoAndOffersTheButton()
    {
        PageState state = Drive(press: false);

        Assert.True(state.ReadyPosted, "The page never posted `ready`.");
        Assert.Equal(NoEvidence, state.EvidenceText);
        Assert.False(state.ExtractHidden, "The Extract evidence button is hidden with no evidence.");
        Assert.False(state.ExtractDisabled, "The Extract evidence button is disabled with no evidence.");
        Assert.Equal(1, state.CliOptions);
    }

    [Fact]
    public void AFinishedExtractionFlipsTheSentenceAndPutsTheButtonAway()
    {
        PageState state = Drive(press: true);

        Assert.Equal(1, state.Extractions);
        Assert.Equal(HasEvidence, state.EvidenceText);
        Assert.True(
            state.ExtractHidden,
            "The Extract evidence button is still offered although the package is written.");
        Assert.True(state.BannerHidden, "A successful extraction showed an error banner.");
    }

    /// <summary>
    /// The state in between, which is the one an engineer can do damage in: a dump of an open
    /// assembly takes seconds, and a second press during it would start a second extraction on
    /// the SOLIDWORKS application thread on top of the first.
    /// </summary>
    [Fact]
    public void AnExtractionInFlightSaysSoAndCannotBeStartedAgain()
    {
        PageState state = Drive(press: true, answer: false, pressAgain: true);

        Assert.Equal(1, state.Extractions);
        Assert.Equal("Extracting evidence from the open document...", state.EvidenceText);
        Assert.False(state.ExtractHidden, "The button vanished mid-extraction, so nothing says why.");
        Assert.True(state.ExtractDisabled, "The Extract evidence button is still pressable.");
    }

    /// <summary>
    /// A refusal - the pane has no document, or the dump failed part way - has to leave the
    /// engineer able to try again: the button comes back enabled, and the host's own sentence is
    /// on screen rather than a generic one.
    /// </summary>
    [Fact]
    public void ARefusedExtractionBringsTheButtonBackWithTheHostsReason()
    {
        PageState state = Drive(press: true, refusal: Refusal);

        Assert.Equal(1, state.Extractions);
        Assert.Equal(NoEvidence, state.EvidenceText);
        Assert.False(state.ExtractHidden, "The Extract evidence button vanished on a refusal.");
        Assert.False(state.ExtractDisabled, "The Extract evidence button stayed disabled on a refusal.");
        Assert.False(state.BannerHidden, "A refused extraction showed no banner.");
        Assert.Equal(Refusal, state.BannerText);
    }

    /// <summary>
    /// Loads the Terminal page, answers `ready` with a run folder that holds no package, presses
    /// Extract evidence when asked to, and reports what the page looks like afterwards.
    /// </summary>
    /// <param name="press">Whether to click the button.</param>
    /// <param name="refusal">When set, `evidence.extract` is answered with an `error` carrying
    /// this message instead of `evidence.extracted`.</param>
    /// <param name="answer">False leaves `evidence.extract` unanswered, which is the state the
    /// page is in while the dump runs.</param>
    /// <param name="pressAgain">Presses the button a second time before the state is read; with
    /// <paramref name="answer"/> false this is the double press.</param>
    private static PageState Drive(
        bool press, string? refusal = null, bool answer = true, bool pressAgain = false)
    {
        var extractions = 0;
        var ready = false;
        PageState? observed = null;

        OffscreenReviewPage.WithPage(
            TaskPaneControl.TerminalPageUrl,
            page =>
            {
                page.WebMessageReceived += (sender, args) =>
                {
                    JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
                    string type = message.GetProperty("type").GetString() ?? string.Empty;
                    string id = message.GetProperty("id").GetString() ?? string.Empty;

                    if (type == "ready")
                    {
                        ready = true;
                        page.PostWebMessageAsJson(Reply("init", id, Init()));
                        return;
                    }

                    if (type == "evidence.extract")
                    {
                        extractions++;
                        if (!answer)
                        {
                            // The dump is still running: the page gets nothing back yet.
                            return;
                        }

                        page.PostWebMessageAsJson(
                            refusal == null
                                ? Reply("evidence.extracted", id, Extracted())
                                : Reply("error", id, Error(refusal)));
                    }
                };
            },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);

                if (press)
                {
                    await page.ExecuteScriptAsync("document.getElementById('extract').click()");
                    await OffscreenReviewPage.Settled(page);
                }

                if (pressAgain)
                {
                    // `click()` rather than a synthesized mouse event: a disabled button ignores
                    // it exactly as it ignores a real press, which is the behaviour under test.
                    await page.ExecuteScriptAsync("document.getElementById('extract').click()");
                    await OffscreenReviewPage.Settled(page);
                }

                observed = await ReadState(page);
            });

        PageState state = observed ?? throw new InvalidOperationException("the page was never read");
        state.Extractions = extractions;
        state.ReadyPosted = ready;
        return state;
    }

    private static async Task<PageState> ReadState(CoreWebView2 page)
    {
        string raw = await page.ExecuteScriptAsync(ReadStateScript);
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing about its controls");

        JsonElement fields = JsonDocument.Parse(json).RootElement;
        return new PageState
        {
            EvidenceText = fields.GetProperty("evidenceText").GetString(),
            ExtractHidden = fields.GetProperty("extractHidden").GetBoolean(),
            ExtractDisabled = fields.GetProperty("extractDisabled").GetBoolean(),
            BannerHidden = fields.GetProperty("bannerHidden").GetBoolean(),
            BannerText = fields.GetProperty("bannerText").GetString(),
            CliOptions = fields.GetProperty("cliOptions").GetInt32(),
        };
    }

    /// <summary>What the engineer sees, read from the DOM only: `term.js` is an IIFE and its
    /// `state` object is deliberately not reachable from outside.</summary>
    private const string ReadStateScript = @"JSON.stringify({
  evidenceText: document.getElementById('evidence-text').textContent,
  extractHidden: document.getElementById('extract').hidden,
  extractDisabled: document.getElementById('extract').disabled,
  bannerHidden: document.getElementById('banner').hidden,
  bannerText: document.getElementById('banner').textContent,
  cliOptions: document.getElementById('cli').options.length
})";

    private static string Reply(string type, string id, object payload) =>
        JsonSerializer.Serialize(new { type, id, payload });

    /// <summary>`init`, as the host builds it: one CLI that can be started, and a run folder
    /// with no package in it (contracts/pane-host-messages.md).</summary>
    private static object Init() => new
    {
        clis = new[]
        {
            new
            {
                name = "codex",
                display_name = "Codex CLI",
                found = true,
                status = (string?)null,
                version = "0.115.0",
                path = @"C:\tools\codex.cmd",
                minimum = "0.100.0",
                message = (string?)null,
                install_steps = (string?)null,
            },
        },
        last_choice = "codex",
        evidence = new { present = false, run_dir = RunDir },
    };

    private static object Extracted() => new
    {
        run_dir = RunDir,
        counts = new { components = 42, gaps = 3 },
    };

    private static object Error(string message) => new
    {
        error_class = "ExtractionUnavailable",
        message,
        retryable = false,
        install_steps = (string?)null,
    };

    private sealed class PageState
    {
        public string? EvidenceText { get; set; }

        public bool ExtractHidden { get; set; }

        public bool ExtractDisabled { get; set; }

        public bool BannerHidden { get; set; }

        public string? BannerText { get; set; }

        public int CliOptions { get; set; }

        public int Extractions { get; set; }

        public bool ReadyPosted { get; set; }
    }
}
