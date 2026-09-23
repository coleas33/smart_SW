using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using SwReview.AddIn.Review;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T042a: a finding title, a recommended action and a tool result summary that contain markup
/// reach the screen as characters, not as elements (FR-029, contracts/pane-host-messages.md).
///
/// <b>How this is driven, and why.</b> tasks.md asks for the page's pure rendering functions in
/// a separately loadable script file, evaluated with a minimal JS engine on net48, and allows
/// an offscreen `CoreWebView2` with the vendored files as the fallback. This test takes both
/// halves: the page must ship `render.js` exposing pure rendering functions, and those
/// functions are called <i>inside the real page</i>, loaded from the real virtual host in an
/// offscreen WebView2, with the result read back through `ExecuteScriptAsync`.
///
/// The engine route was rejected on the merits rather than for want of one. The .NET Framework
/// does ship a JavaScript engine (`Microsoft.JScript`), and it is unusable here for two
/// independent reasons. It is an ES3 engine: `Object.create`, `Array.prototype.forEach` and
/// `JSON` - which the page already uses - do not exist in it, so the file under test would have
/// to be written down to the engine rather than the engine chosen to fit the file. And it has
/// no DOM, so the test would have to supply a shim, and a shim cannot answer the only question
/// an injection test asks: would a browser's HTML parser turn this string into an element? A
/// shim can only report which property the code assigned, which is what the static scan below
/// already proves, from the source, for free. The real engine answers the real question:
/// `querySelectorAll('img,script,...')` over the rendered subtree, and the escaped `&lt;img` in
/// its serialized markup.
///
/// <b>What T041 must provide.</b> `Review/ReviewPage/render.js`, loaded by `index.html` before
/// `app.js`, setting `window.SwReviewRender` to an object with two pure functions - pure in the
/// sense that they touch no host bridge, no network and no page state, so they can be called
/// from a test with nothing else set up:
///
/// <code>
///   window.SwReviewRender.findingCard(finding) -> Element   // a Finding, review-session.schema.json
///   window.SwReviewRender.toolCard(tool)       -> Element   // a tool.started body merged with
///                                                           // its tool.finished body
/// </code>
///
/// `app.js` renders its transcript through the same two functions; the static scan is what
/// keeps the rest of the page honest.
/// </summary>
public sealed class ReviewPageInjectionTests
{
    // Each of the three carries both shapes tasks.md asks for: an element that fires on a load
    // failure (no network is needed, so the CSP's `img-src` is not what is being relied on), and
    // a closing script tag, which is what escapes a string that was written into markup.

    /// <summary>A finding title, as a model wrote it.</summary>
    private const string HostileTitle = "<img src=x onerror=\"alert(1)\"></script>";

    /// <summary>A recommended action, which is the field an engineer is most likely to read.</summary>
    private const string HostileAction = "</script><script>alert(2)</script><img src=x onerror=alert(2)>";

    /// <summary>A tool's own words, which come back from the model the same way.</summary>
    private const string HostileSummary = "<img src=x onerror=alert(3)></script><svg/onload=alert(4)>";

    // ---- the rendered DOM -------------------------------------------------------------------

    [Fact]
    public void AFindingTitleAndRecommendedActionRenderAsLiteralText()
    {
        string finding = JsonSerializer.Serialize(HostileFinding());

        JsonElement rendered = OffscreenReviewPage.Evaluate(
            "return JSON.stringify(describe(render('findingCard', " + finding + ")));");

        AssertLiteral(rendered, HostileTitle, HostileAction);
    }

    [Fact]
    public void AToolResultSummaryRendersAsLiteralText()
    {
        string tool = JsonSerializer.Serialize(new
        {
            step_index = 3,
            tool = "check_fastener_grip",
            arguments = new { component_id = "c-17" },
            status = "ok",
            result_summary = HostileSummary,
            elapsed_s = 1.25,
            error = (string?)null,
        });

        JsonElement rendered = OffscreenReviewPage.Evaluate(
            "return JSON.stringify(describe(render('toolCard', " + tool + ")));");

        AssertLiteral(rendered, HostileSummary);
    }

    private static void AssertLiteral(JsonElement rendered, params string[] expected)
    {
        Assert.True(
            rendered.GetProperty("ok").GetBoolean(),
            rendered.TryGetProperty("error", out JsonElement error) ? error.GetString() : "the page did not render");

        string text = rendered.GetProperty("text").GetString()!;
        string html = rendered.GetProperty("html").GetString()!;

        foreach (string value in expected)
        {
            Assert.Contains(value, text);
        }

        Assert.Equal(0, rendered.GetProperty("injected").GetInt32());
        Assert.Equal(0, rendered.GetProperty("handlers").GetInt32());

        // The serialized markup proves the other half: the browser escaped what it was given
        // instead of parsing it, which is what `textContent` does and `innerHTML` does not.
        Assert.Contains("&lt;", html);
        Assert.DoesNotContain("<img", html);
        Assert.DoesNotContain("<script", html);
    }

    /// <summary>
    /// A complete `Finding` (review-session.schema.json), because the card renders more than the
    /// two hostile fields and a half-filled body would exercise a different path.
    /// </summary>
    private static object HostileFinding() => new
    {
        id = "F-001",
        check = "fastener_grip",
        title = HostileTitle,
        status = "suspected",
        severity = "high",
        component_ids = new[] { "c-17", "c-18" },
        drawing_locations = new[] { new { document_id = "d-1", sheet = "Sheet1" } },
        provenance = new[]
        {
            new
            {
                document_id = "d-1",
                vault_path = @"\\vault\bracket.sldasm",
                vault_version = 4,
                revision = "B",
                configuration = "Default",
                local_modified = false,
                export_method = "native",
            },
        },
        configuration = "Default",
        observed = "Grip length 12.0 mm against a 10.0 mm stack.",
        requirement = "Grip length must not exceed the fastened stack.",
        inputs = new[] { "grip=12.0 mm" },
        calculation = (object?)null,
        tool_result_ids = new[] { 7 },
        coverage_limits = new[] { "threads not modelled" },
        recommended_action = HostileAction,
        group = (object?)null,
        capture_ids = Array.Empty<string>(),
        disposition = (object?)null,
        exception_id = (string?)null,
    };

    // ---- the shape of the reworked cards ----------------------------------------------------

    /// <summary>
    /// Every card the rework reshapes, rendered once, in one page.
    ///
    /// One boot rather than one per assertion: <see cref="OffscreenReviewPage.Evaluate"/> starts
    /// a WebView2, serves the real page through the real <see cref="PageFileServer"/> and tears
    /// it down again on every call, which is seconds each time. The script below renders a
    /// finding this run carried over, a finding it computed, a tool call, the ranked rows and
    /// the coverage fold, and reports the shape of each; the facts under it read that one
    /// report. It is the same arrangement <see cref="ReviewPageAttentionPanelTests"/> uses for
    /// the page it drives.
    /// </summary>
    private static readonly Lazy<JsonElement> Shapes = new Lazy<JsonElement>(RenderShapes);

    /// <summary>
    /// The finding's line states the three things that decide whether to read further: which
    /// finding it is, what the backend concluded and how hard, and which check said so. The
    /// status reaches a class name by interpolation - `status-&lt;status&gt;` - so the stylesheet
    /// can colour it without any script comparing a status to anything (PageRuleScanTests).
    /// </summary>
    [Fact]
    public void TheFindingsFirstLineNamesTheFindingItsStateAndItsCheck()
    {
        JsonElement card = Shapes.Value.GetProperty("carried");

        Assert.Equal(
            new[] { "finding-id mono", "chip status-unresolved", "chip sev-low", "finding-check mono" },
            Strings(card, "lineChildren"));
        Assert.Equal("F-011", card.GetProperty("findingId").GetString());
        Assert.Equal(new[] { "unresolved", "low" }, Strings(card, "chipTexts"));
        Assert.Equal("provenance.vault_version", card.GetProperty("check").GetString());
        Assert.Equal("The vault version of the housing is unknown", card.GetProperty("title").GetString());
    }

    /// <summary>
    /// U10 (docs/pane-findings-2026-09-20-review-gui.md section 3), inverting what this test
    /// used to pin. `observed` was the one fact printed before the fold, and it is the long
    /// "mates to faces..." paragraph whose first sentence already <i>is</i> the title (a prefix
    /// of `observed` in 99 of 99, 13 of 13 and 7 of 7 findings on the evening's reviews). On a
    /// narrow pane that paragraph under every title hid the next finding, so nobody could read
    /// the review as a list. It is now the first row inside the fold: the card's head is the
    /// finding's line and its title and nothing else, and the evidence is one press away.
    /// </summary>
    [Fact]
    public void WhatWasObservedIsTheFirstRowInsideTheFold()
    {
        JsonElement card = Shapes.Value.GetProperty("carried");

        Assert.Equal(
            "The extract carries no vault version for housing.SLDPRT.",
            card.GetProperty("factsInFold").GetString());
        Assert.Equal("facts", card.GetProperty("firstInFold").GetString());
        Assert.Equal(0, card.GetProperty("factsOutsideFold").GetInt32());
        Assert.Equal(new[] { "card-line", "title" }, Strings(card, "headChildren"));
    }

    /// <summary>
    /// A title is a headline, so it is clamped to two lines while the fold is shut and read in
    /// full once it is open - by the stylesheet alone, so the page computes nothing about it.
    /// </summary>
    [Fact]
    public void TheTitleIsClampedToTwoLinesUntilTheFoldIsOpened()
    {
        JsonElement card = Shapes.Value.GetProperty("carried");

        Assert.Equal("2", card.GetProperty("titleClamp").GetString());
        Assert.Equal("none", card.GetProperty("openTitleClamp").GetString());
    }

    /// <summary>
    /// The two carry-over fields reach the screen. The Finding schema has defined
    /// `carried_over_from` and `carried_over_at` since feature 005 lever 11a and this card
    /// dropped both: a verdict this run did not compute but carried over from an earlier
    /// session is a different claim from one it computed, and an engineer reading the fold is
    /// owed that beside the provenance.
    /// </summary>
    [Fact]
    public void TheFoldCarriesTheCarryOverFieldsTheCardUsedToDrop()
    {
        JsonElement card = Shapes.Value.GetProperty("carried");
        string[] labels = Strings(card, "labels");

        Assert.Equal("Affects", labels[0]);
        Assert.Contains("Carried over from", labels);
        Assert.Contains("Carried over at", labels);
        Assert.Contains("2026-09-17T08:00:00Z", Strings(card, "values"));
    }

    /// <summary>
    /// A finding with no calculation prints no calculation block, and a finding with one prints
    /// only the rows that calculation filled. The block used to emit all six rows whatever it
    /// held, so a model that excluded nothing showed "Excluded effects" against a blank - which
    /// reads as a question asked and answered with nothing rather than as a field never filled.
    /// </summary>
    [Fact]
    public void TheCalculationBlockAppearsOnlyWithACalculationAndPrintsOnlyItsFilledRows()
    {
        Assert.Equal(0, Shapes.Value.GetProperty("carried").GetProperty("calculations").GetInt32());

        JsonElement computed = Shapes.Value.GetProperty("computed");
        Assert.Equal(1, computed.GetProperty("calculations").GetInt32());
        Assert.Equal(
            new[] { "Model", "Function", "Inputs", "Result" },
            Strings(computed, "calculationLabels"));
    }

    /// <summary>
    /// The three dispositions are one choice, so they are one bordered group, and the note
    /// travels with them: the box comes first and the buttons follow it, inside the fold, beside
    /// Show in SOLIDWORKS. A finding with no persistent reference draws that button as the
    /// refusal it would be rather than waiting to fail on press.
    /// </summary>
    [Fact]
    public void TheThreeDispositionsAreOneGroupWithTheNoteBoxBeforeThem()
    {
        JsonElement card = Shapes.Value.GetProperty("carried");

        Assert.True(card.GetProperty("toolsInsideDetails").GetBoolean(), "the tools row is not in the fold.");
        Assert.Equal(new[] { "accept", "reject", "defer" }, Strings(card, "segActions"));
        Assert.True(card.GetProperty("noteBeforeGroup").GetBoolean(), "input.note is not before the group.");
        Assert.Equal("none", card.GetProperty("showReference").GetString());

        Assert.Equal(
            JsonValueKind.Null,
            Shapes.Value.GetProperty("computed").GetProperty("showReference").ValueKind);
    }

    /// <summary>
    /// The fold starts shut and its button says so; a settled finding says so in the class the
    /// stylesheet colours, so `app.js` and `render.js` agree about what decided looks like.
    /// </summary>
    [Fact]
    public void TheFoldStartsShutAndASettledFindingSaysSo()
    {
        JsonElement carried = Shapes.Value.GetProperty("carried");
        Assert.True(carried.GetProperty("detailsHidden").GetBoolean(), "the fold started open.");
        Assert.Equal("Details", carried.GetProperty("expandLabel").GetString());
        Assert.Equal("card-status", carried.GetProperty("statusClass").GetString());

        JsonElement computed = Shapes.Value.GetProperty("computed");
        Assert.Equal("card-status decided", computed.GetProperty("statusClass").GetString());
        Assert.Contains("Disposition: accepted", computed.GetProperty("statusText").GetString()!);
    }

    /// <summary>
    /// A tool call is one line - a glyph the stylesheet draws, the name, what came back and how
    /// long it took - and its arguments are behind a fold, indented. A review makes a dozen of
    /// these and none of them is a finding.
    /// </summary>
    [Fact]
    public void AToolCallIsOneLineWithItsArgumentsInAFold()
    {
        JsonElement tool = Shapes.Value.GetProperty("tool");

        Assert.Equal("card tool status-ok", tool.GetProperty("cardClass").GetString());
        Assert.Equal("3", tool.GetProperty("stepIndex").GetString());
        Assert.Equal(
            new[] { "tool-status", "tool-name mono", "tool-summary", "elapsed" },
            Strings(tool, "headChildren"));
        Assert.Equal("check_fastener_grip", tool.GetProperty("toolName").GetString());
        Assert.Equal("1.25 s", tool.GetProperty("elapsed").GetString());

        // The status is a glyph from a CSS ::before, so the element itself carries no word: an
        // inline <svg> is what the injection assertion below refuses, and the CSP loads no
        // image file either.
        Assert.Equal(string.Empty, tool.GetProperty("statusText").GetString());

        Assert.True(tool.GetProperty("argumentsInFold").GetBoolean(), "the arguments are not in a fold.");
        Assert.Equal(0, tool.GetProperty("argumentsOutsideFold").GetInt32());
        Assert.Contains("\n  \"component_id\"", tool.GetProperty("argumentsText").GetString()!);
    }

    /// <summary>
    /// A ranked row says what the finding is, not only that it exists. The backend sends ten
    /// fields per row (contracts/attention.md section 4) and the panel that is meant to be read
    /// first used to print three of them, so it said less about a finding than the finding's own
    /// card did.
    /// </summary>
    [Fact]
    public void ARankedRowCarriesTheTitleAndTheStateTheRankingSent()
    {
        JsonElement start = Shapes.Value.GetProperty("start");

        Assert.Equal("eyebrow attention-heading", start.GetProperty("headingClass").GetString());
        Assert.Equal(AttentionSample.Heading, start.GetProperty("headingText").GetString());

        string[] titles = Strings(start, "titles");
        Assert.Equal(AttentionSample.ShownFindingIds.Length, titles.Length);
        Assert.Equal("The pin interferes with the bore it is pressed into", titles[0]);
        Assert.All(titles, title => Assert.False(string.IsNullOrWhiteSpace(title)));

        // Status and severity as the words the ranking sent, and the components it reaches in
        // the face an id is read in.
        Assert.Equal(
            "demonstrated · medium · cmp:0002, cmp:0003",
            Strings(start, "metas")[0]);
        Assert.Equal("cmp:0002, cmp:0003", Strings(start, "monos")[0]);

        // The three the panel always showed are untouched.
        Assert.Equal(AttentionSample.ShownChecks, Strings(start, "checks"));
        Assert.Equal(AttentionSample.ShownReasons, Strings(start, "reasons"));
    }

    /// <summary>
    /// The stripe restates a field the backend already sent and invents nothing: the judgement
    /// key when the policy said only an engineer can settle the row (F-007 and F-008 carry
    /// `key.judgement` 0), otherwise the consequence class through a map. The rows this fixture
    /// carries run interface, interface, rebuild_breaker, rebuild_breaker, discipline - so a map
    /// keyed off the consequence class alone would colour the first two red rather than purple.
    /// </summary>
    [Fact]
    public void TheStripeOnARankedRowComesFromTheJudgementKeyThenTheConsequenceClass()
    {
        Assert.Equal(
            new[]
            {
                "attention-row stripe-judge",
                "attention-row stripe-judge",
                "attention-row stripe-critical",
                "attention-row stripe-critical",
                "attention-row stripe-warn",
            },
            Strings(Shapes.Value.GetProperty("start"), "rowClasses"));
    }

    // ---- every row, behind Show all (U12) ------------------------------------------------------

    /// <summary>
    /// The panel with every row of <see cref="AttentionSample"/> - the sixth row's title made
    /// hostile - and four variations on the numbers the backend sends, rendered once in one page.
    /// </summary>
    private static readonly Lazy<JsonElement> Index = new Lazy<JsonElement>(() => OffscreenReviewPage.Evaluate(
        ShapeHelpers
        + IndexHelpers
        + "var sample = " + AttentionSample.Json().Replace(
            "\"title\":\"" + AttentionSample.BeyondTopNTitle + "\"",
            "\"title\":" + JsonSerializer.Serialize(HostileTitle)) + ";"
        + "return JSON.stringify({ok: true,"
        + "full: indexShape(mutate(sample, function (r) {})),"
        + "fits: indexShape(mutate(sample, function (r) { r.rows = r.rows.slice(0, 3); r.not_amplified.beyond_top_n = 0; })),"
        + "one: indexShape(mutate(sample, function (r) { r.rows = r.rows.slice(0, 1); r.not_amplified.beyond_top_n = 1; })),"
        + "noCounts: indexShape(mutate(sample, function (r) { delete r.not_amplified; })),"
        + "noTopN: indexShape(mutate(sample, function (r) { delete r.top_n; }))"
        + "});"));

    /// <summary>
    /// The rows beyond `top_n` are one line each: which finding, its title, how many findings
    /// the row folds when it folds more than one, and how many components it reaches - with
    /// the stripe of its consequence class, from the same shared map as Start here. Under
    /// Start here, in the order supplied, behind one control that names both units.
    /// </summary>
    [Fact]
    public void ARowBeyondTopNIsOneLineBehindAControlAfterTheFive()
    {
        JsonElement full = Index.Value.GetProperty("full");

        Assert.Equal(AttentionSample.ShownFindingIds, Strings(full, "startIds"));
        Assert.Equal(new[] { AttentionSample.BeyondTopN }, Strings(full, "indexIds"));
        Assert.Equal("Show all 6 issues (8 findings)", full.GetProperty("more").GetString());
        Assert.Equal("attention-line stripe-quiet", full.GetProperty("lineClass").GetString());
        Assert.Equal(
            new[] { "line-id", "line-title", "line-members", "line-reach" },
            Strings(full, "lineChildren"));
        Assert.Equal(
            new[] { AttentionSample.BeyondTopN, HostileTitle, "×3", "1 component" },
            Strings(full, "lineTexts"));
        Assert.False(full.GetProperty("moreOpen").GetBoolean(), "Show all arrived open.");
    }

    /// <summary>A title that carries markup is characters on a one-line row too (FR-029).</summary>
    [Fact]
    public void AHostileTitleOnARowBeyondTopNRendersAsLiteralText()
    {
        JsonElement full = Index.Value.GetProperty("full");

        Assert.Contains(HostileTitle, full.GetProperty("text").GetString()!);
        Assert.Equal(0, full.GetProperty("injected").GetInt32());
        Assert.Equal(0, full.GetProperty("handlers").GetInt32());
    }

    /// <summary>
    /// The count line prints the backend's numbers and says what each counts, in the singular
    /// when it is one, and a ranking whose rows all fit under Start here offers no control.
    /// </summary>
    [Fact]
    public void TheCountLinePrintsTheBackendsNumbersAndAFittingRankingOffersNoControl()
    {
        JsonElement full = Index.Value.GetProperty("full");
        JsonElement fits = Index.Value.GetProperty("fits");
        JsonElement one = Index.Value.GetProperty("one");

        Assert.Equal("Start here: 5 of 6 issues · 3 findings not in Start here", full.GetProperty("count").GetString());
        Assert.Equal("Start here: 3 of 3 issues · 0 findings not in Start here", fits.GetProperty("count").GetString());
        Assert.Equal("Start here: 1 of 1 issue · 1 finding not in Start here", one.GetProperty("count").GetString());

        Assert.Equal(JsonValueKind.Null, fits.GetProperty("more").ValueKind);
        Assert.Empty(Strings(fits, "indexIds"));
        Assert.Equal(JsonValueKind.Null, one.GetProperty("more").ValueKind);
    }

    /// <summary>
    /// A ranking without `not_amplified` prints the issues and no findings figure rather than a
    /// made-up one; a ranking without a usable `top_n` shows every row under Start here, as
    /// `amplified` always has, and so has nothing to put behind a control.
    /// </summary>
    [Fact]
    public void AMissingCountIsLeftOutAndAMissingTopNShowsEveryRowUnderStartHere()
    {
        JsonElement noCounts = Index.Value.GetProperty("noCounts");
        JsonElement noTopN = Index.Value.GetProperty("noTopN");

        Assert.Equal("Start here: 5 of 6 issues", noCounts.GetProperty("count").GetString());
        Assert.Equal("Show all 6 issues (8 findings)", noCounts.GetProperty("more").GetString());

        Assert.Equal("Start here: 6 of 6 issues · 3 findings not in Start here", noTopN.GetProperty("count").GetString());
        Assert.Equal(6, Strings(noTopN, "startIds").Length);
        Assert.Equal(JsonValueKind.Null, noTopN.GetProperty("more").ValueKind);
    }

    private const string IndexHelpers = @"
var attrsOf = function (root, selector, name) {
  var found = root.querySelectorAll(selector);
  var out = [];
  for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute(name)); }
  return out;
};

var mutate = function (ranking, change) {
  var copy = JSON.parse(JSON.stringify(ranking));
  change(copy);
  return copy;
};

var indexShape = function (value) {
  var got = one('attentionPanel', value, 'section.attention');
  var panel = got.node;
  var seen = describe(got.host);
  var line = panel.querySelector('.attention-index .attention-line');
  var more = panel.querySelector('.attention-more');
  return {
    count: textOf(panel, '.attention-count'),
    more: more ? textOf(more, 'summary') : null,
    moreOpen: more ? !!more.open : false,
    startIds: attrsOf(panel, '.attention-rows .attention-row', 'data-finding-id'),
    indexIds: attrsOf(panel, '.attention-index [data-finding-id]', 'data-finding-id'),
    lineClass: line ? line.className : '',
    lineChildren: childClasses(line),
    lineTexts: line ? textsOf(line, 'span') : [],
    text: seen.text,
    injected: seen.injected,
    handlers: seen.handlers
  };
};
";

    /// <summary>
    /// The coverage panel is a fold that is shut when it arrives, and its one line says how much
    /// is inside. A real run produced 62 of these rows, listed flat and uncollapsed, under a
    /// transcript - which is 62 lines of "the run did not reach this" between the engineer and
    /// everything else on the tab.
    /// </summary>
    [Fact]
    public void TheCoveragePanelIsAShutFoldWhoseOneLineCountsTheBuckets()
    {
        JsonElement coverage = Shapes.Value.GetProperty("coverage");

        Assert.True(coverage.GetProperty("hasFold").GetBoolean(), "the coverage panel is not a fold.");
        Assert.False(coverage.GetProperty("open").GetBoolean(), "the coverage fold arrived open.");
        Assert.Equal("eyebrow coverage-heading", coverage.GetProperty("headingClass").GetString());
        Assert.Equal("Not reached", coverage.GetProperty("headingText").GetString());

        // The buckets in `coverageSummary`'s own order array, which PageRuleScanTests pins by
        // its words: checked, skipped, unresolved, failed, out_of_scope. `failed` is empty here
        // and is therefore named nowhere.
        Assert.Equal(
            "5 checked · 11 skipped · 39 unresolved · 7 out of scope",
            coverage.GetProperty("counts").GetString());
        Assert.Equal(
            new[]
            {
                "coverage-bucket bucket-checked",
                "coverage-bucket bucket-skipped",
                "coverage-bucket bucket-unresolved",
                "coverage-bucket bucket-out_of_scope",
            },
            Strings(coverage, "bucketClasses"));
        Assert.Equal(62, coverage.GetProperty("items").GetInt32());
    }

    /// <summary>
    /// The fence the rework must not have moved: nothing any of these five renderers builds is
    /// an image, a script, an inline &lt;svg&gt; or a scoped &lt;style&gt;, and nothing carries
    /// an `on*` attribute. `&lt;details&gt;` and `&lt;summary&gt;` are neither - they are what
    /// the folds are made of.
    /// </summary>
    [Fact]
    public void NothingTheReworkedCardsBuildIsAnElementTheInjectionFenceRefuses()
    {
        foreach (string card in new[] { "carried", "computed", "tool", "start", "coverage" })
        {
            JsonElement shape = Shapes.Value.GetProperty(card);
            Assert.Equal(0, shape.GetProperty("injected").GetInt32());
            Assert.Equal(0, shape.GetProperty("handlers").GetInt32());
        }
    }

    // ---- the stylesheet the rework draws from --------------------------------------------------

    /// <summary>
    /// The shared palette is linked, and it is linked first. Linked after `app.css` the page
    /// would win its own tokens back and the four tabs would drift apart again.
    /// </summary>
    [Fact]
    public void IndexHtmlLinksTheSharedTokensBeforeThePageStylesheet()
    {
        string index = ReviewPageFiles.IndexHtml();

        int tokens = index.IndexOf("../../shared/tokens.css", StringComparison.Ordinal);
        int page = index.IndexOf("\"app.css\"", StringComparison.Ordinal);

        Assert.True(tokens >= 0, "index.html does not link web/shared/tokens.css.");
        Assert.True(page >= 0, "index.html does not link app.css.");
        Assert.True(tokens < page, "tokens.css must be linked before app.css.");
    }

    /// <summary>
    /// Not one literal colour in the page's own stylesheet. Every hue is a custom property of
    /// `web/shared/tokens.css`, which is what keeps the four tabs one palette: a colour written
    /// here is a colour the other three do not have, and the next person to touch one of them
    /// has no way to know it exists.
    /// </summary>
    [Fact]
    public void ThePageStylesheetNamesNoLiteralColour()
    {
        string css = ReviewPageFiles.Read("app.css");

        string[] literals = HexColour.Matches(css).Cast<Match>()
            .Select(match => match.Value)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

        Assert.True(
            literals.Length == 0,
            "Review/ReviewPage/app.css names colours of its own: " + string.Join(", ", literals)
                + Environment.NewLine
                + "Use a custom property from web/shared/tokens.css instead.");

        foreach (string notation in new[] { "rgb(", "rgba(", "hsl(", "hsla(", "color(" })
        {
            Assert.DoesNotContain(notation, css, StringComparison.OrdinalIgnoreCase);
        }
    }

    /// <summary>
    /// A hex colour, and not an id selector that happens to start with hex digits: `#effort`
    /// and `#accept` are ids this pane uses and `#eff`/`#acce` are not colours in them.
    /// </summary>
    private static readonly Regex HexColour = new Regex(
        @"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9A-Za-z_-])",
        RegexOptions.Compiled);

    // ---- rendering the shapes -------------------------------------------------------------------

    private static JsonElement RenderShapes() => OffscreenReviewPage.Evaluate(
        ShapeHelpers
        + "return JSON.stringify({"
        + "ok: true,"
        + "carried: findingShape(" + Json(CarriedFinding()) + "),"
        + "computed: findingShape(" + Json(ComputedFinding()) + "),"
        + "tool: toolShape(" + Json(SampleTool()) + "),"
        + "start: startShape(" + AttentionSample.Json() + "),"
        + "coverage: coverageShape(" + Json(CoverageEntries()) + ")"
        + "});");

    private static string Json(object value) => JsonSerializer.Serialize(value);

    private static string[] Strings(JsonElement shape, string name) =>
        shape.GetProperty(name).EnumerateArray().Select(value => value.GetString()!).ToArray();

    /// <summary>
    /// A finding whose verdict this run carried over rather than computed, with no persistent
    /// reference and no calculation: the two absences the fold has to handle without printing
    /// an empty row for either.
    /// </summary>
    private static object CarriedFinding() => new
    {
        id = "F-011",
        check = "provenance.vault_version",
        title = "The vault version of the housing is unknown",
        status = "unresolved",
        severity = "low",
        component_ids = new[] { "cmp:0003" },
        drawing_locations = Array.Empty<object>(),
        provenance = Array.Empty<object>(),
        configuration = "Default",
        observed = "The extract carries no vault version for housing.SLDPRT.",
        requirement = "Every document names the vault version it was read at.",
        inputs = Array.Empty<string>(),
        calculation = (object?)null,
        tool_result_ids = Array.Empty<int>(),
        coverage_limits = Array.Empty<string>(),
        recommended_action = "Open the document from the vault so the version travels with it.",
        group = (object?)null,
        capture_ids = Array.Empty<string>(),
        disposition = (object?)null,
        exception_id = (string?)null,
        carried_over_from = "0b0f6f2e-0f1d-4f3a-9b6c-2f2c7d4a1e55",
        carried_over_at = "2026-09-17T08:00:00Z",
    };

    /// <summary>
    /// A finding this run computed: a calculation that filled four of its six fields, a
    /// persistent reference, and a disposition an engineer has already recorded.
    /// </summary>
    private static object ComputedFinding() => new
    {
        id = "F-007",
        check = "interference.static",
        title = "Static interference between the housing and the second pin",
        status = "demonstrated",
        severity = "medium",
        component_ids = new[] { "cmp:0003", "cmp:0004" },
        drawing_locations = new[]
        {
            new { document_id = "d-1", sheet = "Sheet1", persist_ref = "AAECAwQ=" },
        },
        observed = "Largest overlap 0.012 mm in configuration Default.",
        requirement = "No two solid bodies share volume in the graded configuration.",
        calculation = new
        {
            model = "static interference, rigid bodies",
            function = "interference.static",
            function_version = "1.2",
            inputs = new { component_id = "cmp:0004" },
            assumptions = Array.Empty<string>(),
            excluded_effects = Array.Empty<string>(),
            result = 0.012,
            units_out = "mm",
        },
        disposition = new
        {
            decision = "accepted",
            by = "C. Sorkness",
            at = "2026-09-18T22:04:00Z",
            note = "intended press fit per drawing note 4",
        },
    };

    /// <summary>One finished tool call, both bodies merged the way `app.js` merges them.</summary>
    private static object SampleTool() => new
    {
        step_index = 3,
        tool = "check_fastener_grip",
        arguments = new { component_id = "c-17" },
        status = "ok",
        result_summary = "1 finding",
        elapsed_s = 1.25,
        error = (string?)null,
    };

    /// <summary>
    /// The coverage a real workstation run produced - 5 checked, 11 skipped, 39 unresolved, 0
    /// failed, 7 out of scope (docs/pane-findings-2026-09-18.md) - fed in an order no bucket
    /// order could be read off, so the groups and the counts prove the page walks its own order
    /// array rather than the order the events arrived in.
    /// </summary>
    private static object[] CoverageEntries()
    {
        var entries = new List<object>();
        AddCoverage(entries, "out_of_scope", 7, "drawing.rule");
        AddCoverage(entries, "unresolved", 39, "rms.open");
        AddCoverage(entries, "checked", 5, "rms.done");
        AddCoverage(entries, "skipped", 11, "rms.skip");
        return entries.ToArray();
    }

    private static void AddCoverage(List<object> entries, string bucket, int count, string prefix)
    {
        for (int index = 1; index <= count; index++)
        {
            entries.Add(new
            {
                bucket,
                item = new { check = prefix + index, reason = "the extract carries nothing for it" },
            });
        }
    }

    /// <summary>
    /// What each card looks like once the browser has built it. Read through the DOM rather than
    /// through the serialized markup, because the questions here - which element is a child of
    /// which, whether a fold is shut - are questions only a parsed document answers.
    /// </summary>
    private const string ShapeHelpers = @"
var textOf = function (root, selector) {
  var node = root.querySelector(selector);
  return node ? node.textContent : '';
};

var textsOf = function (root, selector) {
  var found = root.querySelectorAll(selector);
  var out = [];
  for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
  return out;
};

var classesOf = function (root, selector) {
  var found = root.querySelectorAll(selector);
  var out = [];
  for (var i = 0; i < found.length; i++) { out.push(found[i].className); }
  return out;
};

var actionsOf = function (root) {
  var found = root ? root.querySelectorAll('[data-action]') : [];
  var out = [];
  for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute('data-action')); }
  return out;
};

var childClasses = function (node) {
  var out = [];
  if (!node) { return out; }
  for (var i = 0; i < node.children.length; i++) { out.push(node.children[i].className); }
  return out;
};

var one = function (name, value, selector) {
  var host = render(name, value);
  var node = host.querySelector(selector);
  if (!node) { throw new Error(name + ' rendered nothing matching ' + selector); }
  return { host: host, node: node };
};

var findingShape = function (value) {
  var got = one('findingCard', value, '.card.finding');
  var card = got.node;
  var seen = describe(got.host);
  var tools = card.querySelector('.details .card-tools');
  var group = tools ? tools.querySelector('.seg') : null;
  var note = tools ? tools.querySelector('input.note') : null;
  var show = card.querySelector('[data-action=""show""]');
  var status = card.querySelector('.card-status');
  var fold = card.querySelector('.details');
  var title = card.querySelector('.card-head .title');
  var titleClamp = getComputedStyle(title).webkitLineClamp;
  fold.hidden = false;
  var openTitleClamp = getComputedStyle(title).webkitLineClamp;
  fold.hidden = true;
  return {
    cardClass: card.className,
    headChildren: childClasses(card.querySelector('.card-head')),
    lineChildren: childClasses(card.querySelector('.card-head .card-line')),
    findingId: textOf(card, '.card-line .finding-id'),
    chipTexts: textsOf(card, '.card-line .chip'),
    check: textOf(card, '.card-line .finding-check'),
    title: textOf(card, '.card-head .title'),
    factsInFold: textOf(card, '.details > .facts'),
    firstInFold: fold.firstElementChild ? fold.firstElementChild.className : '',
    factsOutsideFold: card.querySelectorAll('.facts').length - fold.querySelectorAll('.facts').length,
    titleClamp: titleClamp,
    openTitleClamp: openTitleClamp,
    labels: textsOf(card, '.details > dl.kv > dt'),
    values: textsOf(card, '.details > dl.kv > dd'),
    calculations: card.querySelectorAll('.details .calculation').length,
    calculationLabels: textsOf(card, '.details .calculation dt'),
    detailsHidden: card.querySelector('.details').hidden,
    expandLabel: textOf(card, '[data-action=""expand""]'),
    toolsInsideDetails: !!tools,
    segActions: actionsOf(group),
    noteBeforeGroup: !!(note && group
      && (note.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING)),
    showReference: show ? show.getAttribute('data-reference') : null,
    statusClass: status ? status.className : '',
    statusText: status ? status.textContent : '',
    injected: seen.injected,
    handlers: seen.handlers
  };
};

var toolShape = function (value) {
  var got = one('toolCard', value, '.card.tool');
  var card = got.node;
  var seen = describe(got.host);
  var fold = card.querySelector('details.tool-fold');
  return {
    cardClass: card.className,
    stepIndex: card.getAttribute('data-step-index'),
    headChildren: childClasses(card.querySelector('.card-head')),
    toolName: textOf(card, '.tool-name'),
    summary: textOf(card, '.tool-summary'),
    elapsed: textOf(card, '.elapsed'),
    statusText: textOf(card, '.tool-status'),
    argumentsInFold: !!(fold && fold.querySelector('.tool-arguments')),
    argumentsOutsideFold: card.querySelectorAll(':scope > .tool-arguments').length,
    argumentsText: fold ? textOf(fold, '.tool-arguments') : '',
    injected: seen.injected,
    handlers: seen.handlers
  };
};

var startShape = function (value) {
  var got = one('attentionPanel', value, 'section.attention');
  var panel = got.node;
  var seen = describe(got.host);
  var heading = panel.querySelector('.attention-heading');
  return {
    headingClass: heading ? heading.className : '',
    headingText: heading ? heading.textContent : '',
    rowClasses: classesOf(panel, '.attention-row'),
    ids: textsOf(panel, '.attention-id'),
    titles: textsOf(panel, '.attention-title'),
    metas: textsOf(panel, '.attention-meta'),
    monos: textsOf(panel, '.attention-meta .mono'),
    checks: textsOf(panel, '.attention-check'),
    reasons: textsOf(panel, '.attention-reason'),
    injected: seen.injected,
    handlers: seen.handlers
  };
};

var coverageShape = function (value) {
  var got = one('coverageSummary', value, 'section.coverage');
  var panel = got.node;
  var seen = describe(got.host);
  var fold = panel.querySelector('details.coverage-fold');
  var heading = panel.querySelector('.coverage-heading');
  return {
    hasFold: !!fold,
    open: fold ? !!fold.open : true,
    headingClass: heading ? heading.className : '',
    headingText: heading ? heading.textContent : '',
    counts: textOf(panel, 'summary .fold-count'),
    bucketClasses: classesOf(panel, '.coverage-bucket'),
    bucketNames: textsOf(panel, '.bucket-name'),
    items: panel.querySelectorAll('.bucket-items .bucket-item').length,
    injected: seen.injected,
    handlers: seen.handlers
  };
};
";

    // ---- the static half: the page's own rules --------------------------------------------

    [Fact]
    public void IndexHtmlCarriesTheContractCspMetaTag()
    {
        string expected = ContractCsp();
        string index = ReviewPageFiles.IndexHtml();

        Match meta = Regex.Match(
            index,
            @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""([^""]*)""\s*/?>",
            RegexOptions.IgnoreCase);

        Assert.True(meta.Success, "index.html carries no Content-Security-Policy meta tag.");
        Assert.Equal(Normalize(expected), Normalize(meta.Groups[1].Value));
    }

    [Fact]
    public void NeitherThePageNorItsScriptsAssignMarkup()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> file in PageFiles())
        {
            foreach (Match match in MarkupSink.Matches(file.Value))
            {
                offences.Add($"{file.Key}: {match.Value.Trim()}");
            }
        }

        Assert.True(
            offences.Count == 0,
            "The page must build every node with textContent/createTextNode; these turn a string "
                + "into markup:" + Environment.NewLine + string.Join(Environment.NewLine, offences));
    }

    [Fact]
    public void IndexHtmlNamesNoInlineHandlerAndNoInnerHtml()
    {
        string index = ReviewPageFiles.IndexHtml();

        List<string> handlers = Regex.Matches(index, @"<[^>!][^>]*?\s(on[a-z]+)\s*=", RegexOptions.IgnoreCase)
            .Cast<Match>()
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        Assert.True(
            handlers.Count == 0,
            "index.html carries inline event handlers (" + string.Join(", ", handlers)
                + "); every handler is attached with addEventListener in app.js.");
        Assert.DoesNotContain("innerHTML", index, StringComparison.Ordinal);
    }

    /// <summary>
    /// The sinks that turn a string into markup. `eval` and `new Function` are here because the
    /// page's CSP (`script-src 'self'`, no `unsafe-eval`) already blocks them at runtime, and a
    /// page that needs them is a page whose CSP is about to be loosened.
    /// </summary>
    private static readonly Regex MarkupSink = new Regex(
        @"\.\s*(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\s*\.\s*write|\bnew\s+Function\s*\(|\beval\s*\(",
        RegexOptions.Compiled);

    private static IEnumerable<KeyValuePair<string, string>> PageFiles() =>
        ReviewPageFiles.Scripts()
            .Concat(new[] { new KeyValuePair<string, string>("index.html", ReviewPageFiles.IndexHtml()) });

    /// <summary>The CSP the contract prints in its fenced `html` block, read as data.</summary>
    private static string ContractCsp()
    {
        string contract = ReviewPageFiles.ReadContract("pane-host-messages.md");
        Match meta = Regex.Match(
            contract,
            @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""([^""]*)""\s*>",
            RegexOptions.IgnoreCase);

        Assert.True(meta.Success, "contracts/pane-host-messages.md no longer prints a CSP meta tag.");
        return meta.Groups[1].Value;
    }

    private static string Normalize(string policy) =>
        string.Join(
            "; ",
            policy.Split(';')
                .Select(directive => Regex.Replace(directive.Trim(), @"\s+", " "))
                .Where(directive => directive.Length > 0));
}

/// <summary>
/// The Review page, loaded from the add-in's own virtual host in an offscreen WebView2, with a
/// script evaluated inside it.
///
/// The page is navigated to `https://swreview.invalid/Review/ReviewPage/index.html` and served
/// by the same <see cref="PageFileServer"/>, through the same `WebResourceRequested` filter,
/// that the add-in serves it with, so the CSP meta tag, the relative
/// `src` of every script and the page's origin are the real ones rather than a `file://`
/// approximation of them. `window.chrome.webview` exists in this host as it does in the add-in,
/// so `app.js` starts normally; nothing answers its `ready`, which is exactly the state the page
/// is in before the host replies, and the rendering functions do not depend on it.
///
/// The environment gets its own throwaway user data folder per call. The add-in's single
/// process-wide environment (T042b) is a different concern and a different folder; two
/// environments over the same folder with different options is the failure
/// contracts/pane-host-messages.md warns about.
/// </summary>
internal static class OffscreenReviewPage
{
    /// <summary>
    /// Evaluates a JS function body in the loaded page and parses what it returned. The body
    /// runs with two helpers in scope: `render(name, value)` calls one `window.SwReviewRender`
    /// function and appends the element it returns to the document, and `describe(node)`
    /// reports what actually landed in the DOM.
    /// </summary>
    public static JsonElement Evaluate(string body)
    {
        string raw = Run(Prelude + body + Epilogue);
        string json = JsonDocument.Parse(raw).RootElement.GetString()
            ?? throw new InvalidOperationException("The page script returned no value: " + raw);
        return JsonDocument.Parse(json).RootElement.Clone();
    }

    private const string Prelude = @"
(function () {
  function render(name, value) {
    var api = window.SwReviewRender;
    if (!api || typeof api[name] !== 'function') {
      throw new Error('Review/ReviewPage/render.js must set window.SwReviewRender.' + name +
        ' (T041): this test renders through the same functions the transcript renders through.');
    }
    var host = document.createElement('div');
    document.body.appendChild(host);
    host.appendChild(api[name](value));
    return host;
  }

  function describe(node) {
    var handlers = 0;
    var all = node.getElementsByTagName('*');
    for (var i = 0; i < all.length; i++) {
      var attributes = all[i].attributes;
      for (var j = 0; j < attributes.length; j++) {
        if (/^on/i.test(attributes[j].name)) { handlers++; }
      }
    }
    return {
      ok: true,
      text: node.textContent,
      html: node.innerHTML,
      injected: node.querySelectorAll('img,script,iframe,svg,object,embed,link,style').length,
      handlers: handlers
    };
  }

  try {
";

    private const string Epilogue = @"
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}());
";

    /// <summary>
    /// Loads the real page in an offscreen WebView2 and hands the live
    /// <see cref="CoreWebView2"/> to <paramref name="body"/>.
    ///
    /// Shared with the tests that <i>drive</i> the page rather than call one of its rendering
    /// functions (T041's turn state). Those need the host end of the bridge - a
    /// `WebMessageReceived` handler answering `ready` and `review.start` the way the add-in does
    /// - and it has to be subscribed before the page loads, because the page posts `ready` from
    /// `DOMContentLoaded`. Everything above it is the same boot: the add-in's own page file
    /// server behind the add-in's own filter, the real page URL, the real CSP.
    /// </summary>
    /// <param name="beforeNavigate">Runs on the UI thread with the page not yet navigated;
    /// this is where event handlers are attached. May be null.</param>
    /// <param name="body">Runs once the page has loaded.</param>
    public static void WithPage(Action<CoreWebView2>? beforeNavigate, Func<CoreWebView2, Task> body) =>
        WithPage(ReviewPageFiles.PageUrl, beforeNavigate, body);

    /// <summary>
    /// The same boot for either page. Every page is served out of the `web` folder the way the
    /// add-in serves it, so the Terminal page loads from its own URL under the same origin and
    /// the same CSP as the Review page.
    /// </summary>
    /// <param name="pageUrl">Which page to navigate to, on the virtual host.</param>
    public static void WithPage(
        string pageUrl, Action<CoreWebView2>? beforeNavigate, Func<CoreWebView2, Task> body)
    {
        if (body == null)
        {
            throw new ArgumentNullException(nameof(body));
        }

        string userDataFolder = Path.Combine(
            Path.GetTempPath(), "swreview-page-tests-" + Guid.NewGuid().ToString("N"));

        try
        {
            StaHost.Run(async form =>
            {
                using (var view = new WebView2 { Dock = DockStyle.Fill })
                {
                    form.Controls.Add(view);

                    CoreWebView2Environment environment;
                    try
                    {
                        environment = await CoreWebView2Environment.CreateAsync(null, userDataFolder, null);
                    }
                    catch (WebView2RuntimeNotFoundException error)
                    {
                        throw new InvalidOperationException(
                            "The Evergreen WebView2 runtime is not installed on this machine, so the "
                                + "Review page cannot be rendered and this security test cannot run. "
                                + "The add-in cannot run here either; install the runtime.",
                            error);
                    }

                    await view.EnsureCoreWebView2Async(environment);
                    ServeThePagesTheWayTheAddInDoes(view.CoreWebView2, environment);

                    var loaded = new TaskCompletionSource<CoreWebView2NavigationCompletedEventArgs>();
                    view.CoreWebView2.NavigationCompleted += (sender, args) => loaded.TrySetResult(args);

                    beforeNavigate?.Invoke(view.CoreWebView2);

                    view.CoreWebView2.Navigate(pageUrl);

                    CoreWebView2NavigationCompletedEventArgs navigation = await loaded.Task;
                    if (!navigation.IsSuccess)
                    {
                        throw new InvalidOperationException(
                            $"{pageUrl} did not load: {navigation.WebErrorStatus}.");
                    }

                    await body(view.CoreWebView2);
                }
            });
        }
        finally
        {
            TryDelete(userDataFolder);
        }
    }

    /// <summary>
    /// Serves the page and everything it loads exactly as <c>TaskPaneControl.AttachPageAsync</c>
    /// does: one filter over the whole origin, one `WebResourceRequested` handler, and the same
    /// <see cref="PageFileServer"/> class, over the same `web` folder.
    ///
    /// This used to be `SetVirtualHostNameToFolderMapping`, and it is not any more for the same
    /// reason the add-in dropped it (docs/pane-backend-proxy.md section 4): a folder-mapped host
    /// raises no `WebResourceRequested`, so a page booted that way would be a page booted the
    /// one way the add-in no longer boots it. Every page test in this assembly goes through
    /// <see cref="WithPage(string, Action{CoreWebView2}, Func{CoreWebView2, Task})"/>, so this
    /// line is what makes all of them exercise the real serving path rather than an
    /// approximation of it.
    ///
    /// Synchronous: a file read off the disk, so there is nothing to defer and no UI thread to
    /// keep off. The add-in takes a deferral because its other half is a blocking HTTP round
    /// trip on the SOLIDWORKS application thread; these tests have no backend at all.
    /// </summary>
    private static void ServeThePagesTheWayTheAddInDoes(
        CoreWebView2 core, CoreWebView2Environment environment)
    {
        var files = new PageFileServer(ReviewPageFiles.WebFolder);

        core.AddWebResourceRequestedFilter(
            TaskPaneControl.PageResourceFilter,
            CoreWebView2WebResourceContext.All,
            CoreWebView2WebResourceRequestSourceKinds.All);

        core.WebResourceRequested += (sender, args) =>
        {
            ProxiedResponse answer = files.Serve(args.Request.Uri);
            args.Response = environment.CreateWebResourceResponse(
                new MemoryStream(answer.Content), answer.Status, answer.Reason, answer.Headers);
        };
    }

    /// <summary>
    /// Lets the page's promise chain drain.
    ///
    /// `bridge.postMessage` and the host's reply cross a process boundary and everything the
    /// page does with a reply is a microtask behind it, so "the page has finished reacting" is
    /// a few round trips through the renderer rather than a single one. Each `ExecuteScriptAsync`
    /// is ordered behind everything the previous one queued, which is what makes this bounded
    /// rather than a race.
    /// </summary>
    public static async Task Settled(CoreWebView2 page)
    {
        for (int turn = 0; turn < 12; turn++)
        {
            await page.ExecuteScriptAsync("0");
            await Task.Delay(15);
        }
    }

    private static string Run(string script)
    {
        string? result = null;

        WithPage(
            null,
            async page =>
            {
                // Script evaluated through the DevTools protocol rather than injected into
                // the document, so the page's own CSP neither blocks it nor is weakened by it.
                result = await page.ExecuteScriptAsync(script);
            });

        Assert.False(
            string.IsNullOrEmpty(result) || result == "null",
            "The page script threw before it could report: " + (result ?? "<nothing>")
                + Environment.NewLine + script);

        return result!;
    }

    /// <summary>Best effort: the browser process may still be letting go of the folder.</summary>
    private static void TryDelete(string folder)
    {
        try
        {
            if (Directory.Exists(folder))
            {
                Directory.Delete(folder, recursive: true);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
