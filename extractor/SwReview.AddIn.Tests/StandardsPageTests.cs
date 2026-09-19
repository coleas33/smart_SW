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
/// T078 (contract): the Standards page's half of
/// `specs/006-standards-check/contracts/standards-check.md`.
///
/// Two halves, and they answer different questions.
///
/// <b>The scan</b> is the scan <see cref="ModelCheckPageTests"/> and
/// <see cref="RemodelPageContractTests"/> already run, applied to sections 2 and 3 of this
/// feature's contract, which are read as data: nothing the page posts is invented, no
/// page-to-host row is orphaned, every unsolicited row is handled, every dotted literal the
/// page names is in one of the two tables, and every element id the script looks up exists in
/// the HTML. A type the host has never heard of is answered `error` at runtime and the feature
/// behind it silently does nothing; an id that is not in the page is a `null` the script then
/// reads a property off.
///
/// <b>The render</b> is the real page, loaded from the real virtual host in an offscreen
/// WebView2 under the real CSP, handed a `StandardsResult` and asked what landed in the DOM.
/// That is the only way to assert what an engineer sees before a release: which headline the
/// three verdict states produce, that the unresolved check ids travel with the counts in every
/// one of them, that all sixteen checks are accounted for with the bucket, the documents and
/// the reason, that no letter grade and no single percentage is rendered at all, and that a
/// subject with nothing to select is offered no Show control rather than one that fails every
/// time.
///
/// Injection is not in scope here; that is <see cref="StandardsPageInjectionTests"/>.
/// </summary>
public sealed class StandardsPageTests
{
    private static readonly StandardsContract Contract = StandardsContract.Load();

    // ---- rule 1: nothing is invented -------------------------------------------------------

    [Fact]
    public void EveryTypeThePageSendsIsARowOfTheContract()
    {
        var undocumented = new List<string>();

        foreach (KeyValuePair<string, string> script in StandardsPageFiles.Scripts())
        {
            foreach (string type in SentTypes(Strip(script.Value)))
            {
                if (!Contract.PageToHost.Contains(type))
                {
                    undocumented.Add($"{script.Key} posts `{type}`");
                }
            }
        }

        Assert.True(
            undocumented.Count == 0,
            "The Standards page posts message types contracts/standards-check.md does not "
                + "define:" + Environment.NewLine + string.Join(Environment.NewLine, undocumented)
                + Environment.NewLine + "Documented: " + Join(Contract.PageToHost));
    }

    // ---- rule 2: nothing is orphaned -------------------------------------------------------

    [Fact]
    public void EveryPageToHostRowIsExercisedByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            StandardsPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> missing = Contract.PageToHost
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            missing.Count == 0,
            "contracts/standards-check.md defines host handlers the page never asks for: "
                + Join(missing)
                + Environment.NewLine
                + "The page is the only sender these handlers have, so a row nothing sends is "
                + "dead host code or a feature that was specified and never built.");
    }

    // ---- rule 3: every type the page names is documented ------------------------------------

    [Fact]
    public void EveryMessageTypeThePageNamesIsDocumented()
    {
        var unknown = new List<string>();

        foreach (KeyValuePair<string, string> script in StandardsPageFiles.Scripts())
        {
            foreach (string literal in DottedLiterals(Strip(script.Value)))
            {
                if (!Contract.PageToHost.Contains(literal) && !Contract.HostToPage.Contains(literal))
                {
                    unknown.Add($"{script.Key}: '{literal}'");
                }
            }
        }

        Assert.True(
            unknown.Count == 0,
            "The page names types that are in neither table of contracts/standards-check.md (a "
                + "typo in one of these is invisible at runtime):" + Environment.NewLine
                + string.Join(Environment.NewLine, unknown)
                + Environment.NewLine + "standards-check.md: "
                + Join(Contract.PageToHost.Concat(Contract.HostToPage)));
    }

    // ---- rule 4: every unsolicited row is handled --------------------------------------------

    [Fact]
    public void EveryUnsolicitedHostRowIsHandledByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            StandardsPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> ignored = Contract.Unsolicited
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            ignored.Count == 0,
            "contracts/standards-check.md section 3 defines unsolicited messages the page never "
                + "handles: " + Join(ignored)
                + Environment.NewLine
                + "Each of these is a message the host posts into a page that drops it.");
    }

    // ---- rule 5: the page and its script agree about the document ---------------------------

    [Fact]
    public void EveryElementIdTheScriptLooksUpExistsInTheHtml()
    {
        string html = StandardsPageFiles.IndexHtml();

        var present = new HashSet<string>(
            Regex.Matches(html, "\\bid=\"([^\"]+)\"").Cast<Match>().Select(match => match.Groups[1].Value),
            StringComparer.Ordinal);

        var missing = new List<string>();
        foreach (KeyValuePair<string, string> script in StandardsPageFiles.Scripts())
        {
            foreach (Match match in ElementLookup.Matches(Strip(script.Value)))
            {
                string id = match.Groups[2].Value;
                if (!present.Contains(id))
                {
                    missing.Add($"{script.Key} looks up '{id}'");
                }
            }
        }

        Assert.True(
            missing.Count == 0,
            "The script reads elements index.html does not have (each of these is a null the "
                + "page then reads a property off):" + Environment.NewLine
                + string.Join(Environment.NewLine, missing)
                + Environment.NewLine + "index.html has: " + Join(present));
    }

    // ---- the token never travels in a URL ---------------------------------------------------

    /// <summary>
    /// A URL reaches access logs, WebView2's history and every crash dump (chat-api.md). The
    /// token goes in the `Authorization` header and nowhere else, and the route the page calls
    /// is `POST /checks/standards` - the page calls it itself, because the host stops at
    /// `standards.extracted` (contracts/standards-check.md section 1).
    /// </summary>
    [Fact]
    public void TheBackendIsCalledWithABearerHeaderAndNeverWithATokenInAUrl()
    {
        string page = Strip(StandardsPageFiles.Read("standards.js"));
        string shared = Strip(StandardsPageFiles.Read(
            Path.Combine(StandardsPageFiles.SharedFolder, "check-page.js")));

        Assert.Contains("/checks/standards", page, StringComparison.Ordinal);
        Assert.Contains("Authorization", shared, StringComparison.Ordinal);
        Assert.Contains("'Bearer '", shared, StringComparison.Ordinal);

        string[] offences = StandardsPageFiles.Scripts()
            .SelectMany(script => Strip(script.Value)
                .Split('\n')
                .Where(line => line.IndexOf("token", StringComparison.OrdinalIgnoreCase) >= 0)
                .Where(line => TokenInUrl.IsMatch(line))
                .Select(line => script.Key + ": " + line.Trim()))
            .ToArray();

        Assert.True(
            offences.Length == 0,
            "The token is being put into a URL:" + Environment.NewLine
                + string.Join(Environment.NewLine, offences));
    }

    /// <summary>
    /// The page relays the `profile_path` it was given in `init` and sends no `scope`.
    ///
    /// Both halves are the contract's (section 1, differences D1 and D9): the reasoning side
    /// owns the schema, so the path travels on the request and no profile <i>value</i> ever
    /// does; and there is no scope, because every standards check runs on every run.
    /// </summary>
    [Fact]
    public void ThePageCallsTheStandardsRouteItselfWithTheRunDirAndTheProfilePathFromInit()
    {
        JsonElement state = Drive(CallStub, PressCheck, ReadCalls);

        Assert.Equal(
            new[] { "POST /checks/standards" },
            state.GetProperty("calls").EnumerateArray().Select(value => value.GetString()).ToArray());

        JsonElement body = state.GetProperty("body");
        Assert.Equal(
            @"C:\SwReviewRuns\20260917-101532-top-plate-standards",
            body.GetProperty("run_dir").GetString());
        Assert.Equal(
            @"C:\Users\pilot\AppData\Local\SwReview\standards.yaml",
            body.GetProperty("profile_path").GetString());

        // D1: no scope field at all, not a null one. A run whose coverage depended on a control
        // nobody recorded is what the absence is for.
        Assert.False(
            body.TryGetProperty("scope", out JsonElement _),
            "The page sent a `scope`; contracts/standards-check.md D1 says there is none.");

        // The host's half stops at `standards.extracted`, and the page sent it no payload (D7).
        Assert.Equal(
            new[] { "standards.start" },
            state.GetProperty("sent").EnumerateArray().Select(value => value.GetString()).ToArray());
        Assert.Equal("{}", state.GetProperty("startPayload").GetString());
    }

    // ---- the verdict header --------------------------------------------------------------------

    /// <summary>
    /// "Ready to release" only at zero errors <b>and</b> zero unresolved checks (FR-032). The
    /// three states are the only three, and the unresolved ids are named beside the counts in
    /// every one of them - a headline that could be read as a score without them is the thing
    /// this shape exists to prevent.
    /// </summary>
    [Fact]
    public void TheHeadlineReadsReadyToReleaseOnlyAtZeroErrorsAndZeroUnresolved()
    {
        JsonElement ready = RenderMutated(
            "result.verdict.state = 'ready';"
            + "result.verdict.counts.error = 0; result.verdict.counts.unresolved = 0;"
            + "result.verdict.unresolved_check_ids = [];",
            Headline);

        Assert.Equal("Ready to release", ready.GetProperty("headline").GetString());
        Assert.Contains("Every check reached a verdict", ready.GetProperty("text").GetString()!);
    }

    [Fact]
    public void TheHeadlineReadsNotReadyWheneverTheErrorCountIsAboveZeroHoweverManyChecksPassed()
    {
        JsonElement rendered = RenderMutated(
            "result.verdict.state = 'not_ready';"
            + "result.verdict.counts.error = 1; result.verdict.counts.checked = 40;",
            Headline);

        string text = rendered.GetProperty("text").GetString()!;

        Assert.Equal("Not ready to release", rendered.GetProperty("headline").GetString());
        Assert.Contains("1 error", text);
        Assert.Contains("40 checked", text);

        // The unresolved ids travel with the counts here too: "not ready" plus a hidden gap is
        // still a headline claiming more than the run checked.
        Assert.Contains("standards.assembly.not_transparent", text);
        Assert.Contains("standards.assembly.mate_references", text);
    }

    [Fact]
    public void ZeroErrorsWithAnUnresolvedCheckIsNeitherReadyNorNotReady()
    {
        JsonElement rendered = Render(Headline);

        string headline = rendered.GetProperty("headline").GetString()!;

        Assert.Equal(
            "Not proven ready: the run left checks without a verdict", headline);
        Assert.DoesNotContain("Ready to release", headline, StringComparison.OrdinalIgnoreCase);

        string text = rendered.GetProperty("text").GetString()!;
        Assert.Contains("standards.assembly.not_transparent", text);
        Assert.Contains("standards.assembly.mate_references", text);
    }

    /// <summary>
    /// The three notes (`verdict.notes`) are on the headline, not folded away: a `ready`
    /// verdict reached with waivers, with checks skipped for an empty profile list, or over a
    /// package with no drawing has to say so (FR-032).
    /// </summary>
    [Fact]
    public void AReadyVerdictSaysOnTheHeadlineWhatItWasReachedWith()
    {
        JsonElement rendered = RenderMutated(
            "result.verdict.state = 'ready';"
            + "result.verdict.counts.error = 0; result.verdict.counts.unresolved = 0;"
            + "result.verdict.unresolved_check_ids = [];",
            "return JSON.stringify({ok: true, "
            + "headline: texts('#verdict .verdict-headline')[0], "
            + "notes: texts('#verdict .verdict-note')});");

        Assert.Equal("Ready to release", rendered.GetProperty("headline").GetString());
        Assert.Equal(
            new[]
            {
                "1 finding waived by an accepted exception",
                "2 checks skipped because a profile list is empty",
                "no drawing graded",
            },
            Strings(rendered, "notes"));
    }

    /// <summary>
    /// The unit of every count is stated, because the six do not share one: `error`, `warning`
    /// and `waived` count findings and the four coverage counts count (check, document) pairs,
    /// so they do not sum to sixteen and a reader who added them up would be wrong.
    /// </summary>
    [Fact]
    public void EveryCountIsRenderedWithTheUnitItCounts()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, counts: texts('#verdict .count')});");

        string[] counts = Strings(rendered, "counts");

        Assert.Equal(
            new[]
            {
                "0 error findings",
                "0 warning findings",
                "1 waived findings",
                "9 checked (check, document) pairs",
                "4 skipped (check, document) pairs",
                "2 unresolved (check, document) pairs",
                "4 out of scope (check, document) pairs",
            },
            counts);
    }

    /// <summary>
    /// No letter grade and no single percentage, anywhere on the page (FR-032). The RMS tab
    /// prints a fraction beside its counts and says why it can; a release verdict is not a
    /// score, and one that could be read as 83% would be read as 83%.
    /// </summary>
    [Fact]
    public void NoLetterGradeAndNoSinglePercentageIsRenderedAnywhere()
    {
        JsonElement rendered = Render("return JSON.stringify(describe(document.body));");

        string text = Text(rendered);

        // No percentage anywhere on the page, and none of the Model check header's own
        // vocabulary: a grade heading, a letter, or the fraction it prints beside its counts.
        Assert.DoesNotContain("%", text);
        Assert.DoesNotContain("Grade:", text, StringComparison.Ordinal);
        Assert.DoesNotContain("of the rules that reached a verdict were checked", text);

        JsonElement header = Render(
            "return JSON.stringify({ok: true, fractions: texts('#verdict .fraction'), "
            + "headings: texts('#verdict .grade-heading')});");

        Assert.Empty(Strings(header, "fractions"));
        Assert.Empty(Strings(header, "headings"));
    }

    // ---- the ranked rows ---------------------------------------------------------------------

    /// <summary>
    /// The first `top_n` rows of `result.attention`, in the order the backend supplied them,
    /// each naming the finding, the check and the reason it was placed (FR-023).
    ///
    /// The same block the Model check tab renders, from the same key, through the same shared
    /// function - which is the point: the ranking is computed once and rendered everywhere.
    /// The order is the assertion that bites, because <see cref="AttentionSample"/>'s ids and
    /// checks are in no order a page could have produced for itself.
    /// </summary>
    [Fact]
    public void TheRankedRowsRenderInTheOrderTheRankingSuppliedThem()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "ids: attrs('#attention .attention-row', 'data-finding-id'), "
            + "checks: texts('#attention .attention-check'), "
            + "reasons: texts('#attention .attention-reason'), "
            + "heading: texts('#attention .attention-heading')[0], "
            + "text: document.getElementById('attention').textContent});");

        Assert.Equal(AttentionSample.ShownFindingIds, Strings(rendered, "ids"));
        Assert.Equal(AttentionSample.ShownChecks, Strings(rendered, "checks"));
        Assert.Equal(AttentionSample.ShownReasons, Strings(rendered, "reasons"));
        Assert.Equal(AttentionSample.Heading, rendered.GetProperty("heading").GetString());

        Assert.DoesNotContain(AttentionSample.BeyondTopN, rendered.GetProperty("text").GetString()!);
    }

    /// <summary>
    /// On this tab the block goes above the sixteen-check roster, so it is above the bucket
    /// chips on both tabs and the roster does not sit between the release headline and the
    /// rows an engineer is being asked to start with (research R2.14).
    /// </summary>
    [Fact]
    public void TheRankedRowsSitAboveTheCheckRosterAndAboveTheBucketChips()
    {
        JsonElement rendered = Render(
            "var attention = document.getElementById('attention');"
            + "function after(id) {"
            + "  return !!(attention.compareDocumentPosition(document.getElementById(id))"
            + "    & Node.DOCUMENT_POSITION_FOLLOWING);"
            + "}"
            + "return JSON.stringify({ok: true, checks: after('checks'), filters: after('filters')});");

        Assert.True(
            rendered.GetProperty("checks").GetBoolean(),
            "#attention must come before #checks in the document.");
        Assert.True(
            rendered.GetProperty("filters").GetBoolean(),
            "#attention must come before #filters in the document.");
    }

    [Fact]
    public void ARankingWithNoRowsPrintsItsOwnSentenceAndNoList()
    {
        JsonElement rendered = RenderMutated(
            "result.attention = " + AttentionSample.EmptyJson() + ";",
            "return JSON.stringify({ok: true, "
            + "text: document.getElementById('attention').textContent, "
            + "rows: attrs('#attention .attention-row', 'data-finding-id'), "
            + "lists: document.querySelectorAll('#attention ol').length});");

        Assert.Contains(AttentionSample.EmptyReason, rendered.GetProperty("text").GetString()!);
        Assert.Empty(Strings(rendered, "rows"));
        Assert.Equal(0, rendered.GetProperty("lists").GetInt32());
    }

    [Fact]
    public void ABodyWithNoRankingRendersNothingInTheSection()
    {
        JsonElement rendered = RenderMutated(
            "delete result.attention;",
            "return JSON.stringify({ok: true, "
            + "text: document.getElementById('attention').textContent, "
            + "children: document.getElementById('attention').childNodes.length, "
            + "checks: document.querySelectorAll('#checks .check').length});");

        Assert.Equal(string.Empty, rendered.GetProperty("text").GetString());
        Assert.Equal(0, rendered.GetProperty("children").GetInt32());
        Assert.Equal(16, rendered.GetProperty("checks").GetInt32());
    }

    // ---- all sixteen checks ------------------------------------------------------------------

    /// <summary>
    /// `checks` is a required array of all sixteen (D4), and the page renders every one of them
    /// with every bucket it landed in, the documents in that bucket and the reason - including
    /// the checks that did not apply, which are present with an `out_of_scope` bucket rather
    /// than absent. A release gate reads "all sixteen were accounted for" off this list.
    /// </summary>
    [Fact]
    public void AllSixteenChecksRenderWithEveryBucketTheyLandedInAndTheDocumentsInIt()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "checks: attrs('#checks .check', 'data-check'), "
            + "worst: attrs('#checks .check', 'data-worst-bucket'), "
            + "buckets: attrs('#checks .check[data-check=\"standards.assembly.mate_references\"] "
            + ".check-bucket', 'data-bucket'), "
            + "rows: texts('#checks .check[data-check=\"standards.assembly.mate_references\"] "
            + ".check-bucket')});");

        string[] checks = Strings(rendered, "checks");

        Assert.Equal(16, checks.Length);
        Assert.Equal(StandardsResultSample.CheckIds, checks);

        // A check that did not apply is present, not missing.
        Assert.Contains("out_of_scope", Strings(rendered, "worst"));

        // One check in two buckets renders both, each naming its documents and its reason.
        Assert.Equal(new[] { "unresolved", "checked" }, Strings(rendered, "buckets"));

        string[] rows = Strings(rendered, "rows");
        Assert.Contains("doc:ab12", rows[0]);
        Assert.Contains("one mate entity did not resolve", rows[0]);
        Assert.Contains("doc:ef56", rows[1]);
    }

    // ---- the subjects ------------------------------------------------------------------------

    /// <summary>
    /// `showable: false` renders <b>no</b> Show control at all (D5, FR-031). A revision-table
    /// row and a drawing entity carry a reference the shared resolver cannot select, so a
    /// control built from the reference alone would report `ok: false` every single time, which
    /// is worse than not offering it.
    /// </summary>
    [Fact]
    public void ASubjectThatIsNotShowableIsOfferedNoShowControlAtAll()
    {
        JsonElement rendered = Render(
            "var rows = document.querySelectorAll("
            + "'.rule[data-rule-id=\"standards.drawing.revision_matches\"] .subject');"
            + "return JSON.stringify({ok: true, "
            + "shows: rows[0].querySelectorAll('[data-action=\"show\"]').length, "
            + "text: rows[0].textContent});");

        Assert.Equal(0, rendered.GetProperty("shows").GetInt32());
        Assert.Contains(
            "there is nothing in SOLIDWORKS to select",
            rendered.GetProperty("text").GetString()!);
    }

    [Fact]
    public void ASubjectReachedThroughSeveralInstancesSaysWhichOneItWillActOnAndCycles()
    {
        JsonElement rendered = Render(
            "var row = document.querySelector("
            + "'.rule[data-rule-id=\"standards.assembly.not_hidden\"]');"
            + "var subject = row.querySelector('.subject');"
            + "var first = subject.querySelector('[data-action=\"show\"]').textContent;"
            + "subject.querySelector('[data-action=\"cycle\"]').click();"
            + "var second = subject.querySelector('[data-action=\"show\"]').textContent;"
            + "return JSON.stringify({ok: true, first: first, second: second});");

        Assert.Equal("Show (instance 1 of 2)", rendered.GetProperty("first").GetString());
        Assert.Equal("Show (instance 2 of 2)", rendered.GetProperty("second").GetString());
    }

    /// <summary>
    /// The Accept control binds to the check and the <b>document</b> (D12): a standards run
    /// grades parts, assemblies and drawings, and an engineer waiving a drawing check must see
    /// that every dimension on that drawing is covered. A `warning` check has no control at
    /// all rather than a disabled one (FR-041).
    /// </summary>
    [Fact]
    public void AnErrorCheckCarriesTheAcceptControlForTheDocumentAndAWarningCheckCarriesNone()
    {
        JsonElement rendered = Render(
            "var error = document.querySelector("
            + "'.rule[data-rule-id=\"standards.part.material_assigned\"]');"
            + "var warning = document.querySelector("
            + "'.rule[data-rule-id=\"standards.drawing.revision_matches\"]');"
            + "var accept = error.querySelector('[data-action=\"accept\"]');"
            + "return JSON.stringify({ok: true, label: accept.textContent, "
            + "hint: error.querySelector('input.note').getAttribute('placeholder'), "
            + "warningAccepts: warning.querySelectorAll('[data-action=\"accept\"]').length});");

        Assert.Equal(
            "Accept this check for this document", rendered.GetProperty("label").GetString());
        Assert.Contains("required", rendered.GetProperty("hint").GetString()!);
        Assert.Equal(0, rendered.GetProperty("warningAccepts").GetInt32());
    }

    // ---- the run folder controls ----------------------------------------------------------------

    /// <summary>
    /// Report, folder and log are delegated to the host with the run id off the host's own
    /// record. The page supplies no path: `PaneActions` resolves one from the record and
    /// canonicalizes it, and a page that sent a path would be the one place that guard could be
    /// skipped (contracts/standards-check.md section 2).
    /// </summary>
    [Fact]
    public void TheReportFolderAndLogControlsDelegateToTheHostAndNamePath()
    {
        JsonElement state = Drive(
            withBackend: true,
            stub: CallStub,
            presses: new[]
            {
                PressCheck,
                @"(function () {
  document.getElementById('open-report').click();
  document.getElementById('open-folder').click();
  document.getElementById('open-log').click();
}());",
            },
            read: "return JSON.stringify({ok: true, sent: window.__sent, payloads: window.__payloads});");

        string[] sent = Strings(state, "sent");

        Assert.Equal(
            new[] { "standards.start", "report.open", "folder.open", "log.open" }, sent);

        string[] payloads = Strings(state, "payloads");
        foreach (string payload in payloads)
        {
            Assert.DoesNotContain("SwReviewRuns", payload);
            Assert.DoesNotContain("path", payload);
        }

        // The run id is the check folder's name, which is what `GET /checks/{check_id}`
        // resolves under the run root.
        Assert.Contains("20260917-101532-top-plate-standards", payloads[1]);
        Assert.Contains("20260917-101532-top-plate-standards", payloads[2]);
    }

    // ---- what the page can grade ------------------------------------------------------------------

    /// <summary>
    /// All three kinds are gradable (D11), so `kind` tells the page <b>what</b> will be graded
    /// rather than whether anything can be. A drawing-rooted run fans out to every model its
    /// views reference, and an engineer who presses Standards on a drawing should not be
    /// surprised by that; the page never offers a button the host will refuse.
    /// </summary>
    [Theory]
    [InlineData("drawing", "this drawing and the models its views reference")]
    [InlineData("assembly", "this assembly and everything under it")]
    [InlineData("part", "this part")]
    public void ThePageSaysWhatWillBeGradedFromTheKindOnDocumentChanged(string kind, string said)
    {
        StandardsHostStub? stub = null;
        string note = string.Empty;
        bool enabled = false;

        OffscreenReviewPage.WithPage(
            StandardsPageFiles.PageUrl,
            page => { stub = new StandardsHostStub(page, withBackend: true); },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);

                stub!.Post(
                    "document.changed",
                    new { path = @"C:\vault\top-plate.slddrw", configuration = "AsBuilt", kind });
                await OffscreenReviewPage.Settled(page);

                note = await ReadText(page, "grading");
                enabled = await ReadEnabled(page, "run-check");
            });

        Assert.Contains(said, note);
        Assert.True(enabled, "The Standards button is disabled for a document the host grades.");
    }

    /// <summary>
    /// A kind the host refuses (`UnsupportedKind`) is refused on the page too: the tab says what
    /// it can grade rather than offering a button whose only answer is a refusal.
    /// </summary>
    [Fact]
    public void ADocumentKindTheHostRefusesIsNotOfferedAButton()
    {
        StandardsHostStub? stub = null;
        string note = string.Empty;
        bool enabled = true;

        OffscreenReviewPage.WithPage(
            StandardsPageFiles.PageUrl,
            page => { stub = new StandardsHostStub(page, withBackend: true); },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);

                stub!.Post(
                    "document.changed",
                    new { path = @"C:\vault\notes.sldlfp", configuration = (string?)null, kind = "other" });
                await OffscreenReviewPage.Settled(page);

                note = await ReadText(page, "grading");
                enabled = await ReadEnabled(page, "run-check");
            });

        Assert.Contains("part, an assembly or a drawing", note);
        Assert.False(enabled, "The Standards button is offered for a kind the host refuses.");
    }

    // ---- the two states that are not a result -----------------------------------------------------

    /// <summary>
    /// The backend not running is a state, not a silence: the page says so and offers the log,
    /// which is the one control that works without a backend.
    /// </summary>
    [Fact]
    public void TheBackendNotRunningIsReportedWithTheLogOffered()
    {
        JsonElement state = Drive(
            withBackend: false,
            stub: "window.__calls = []; window.fetch = function () { window.__calls.push('called'); };",
            press: PressCheck,
            read: "return JSON.stringify({ok: true, banner: document.getElementById('banner').textContent, "
                + "hidden: !!document.getElementById('banner').hidden, "
                + "log: !document.getElementById('open-log').disabled, "
                + "calls: window.__calls});");

        Assert.False(state.GetProperty("hidden").GetBoolean(), "The banner is hidden.");
        Assert.Contains("backend is not running", state.GetProperty("banner").GetString()!);
        Assert.True(state.GetProperty("log").GetBoolean(), "View log is disabled with no backend.");
        Assert.Empty(state.GetProperty("calls").EnumerateArray());
    }

    /// <summary>
    /// A run folder created before a `ProfileInvalid` refusal renders as an <b>empty run</b>,
    /// never as a result (spec US3 acceptance scenario 12, `contracts/profile.md`). The host
    /// refuses before it creates anything, so the folder only exists when the dump succeeded and
    /// the backend then refused the profile - and the page must not leave the last result on
    /// screen beside the new run folder, where it reads as this run's answer.
    ///
    /// Two presses, because the case only exists after a result: the first is graded, the second
    /// is refused, and what is on screen afterwards is the new run folder and the refusal.
    /// </summary>
    [Fact]
    public void ARunRefusedForAnInvalidProfileRendersAsAnEmptyRunRatherThanAsAResult()
    {
        JsonElement state = Drive(
            withBackend: true,
            stub: RefusingSecondCallStub,
            presses: new[] { PressCheck, PressCheck },
            read: "return JSON.stringify({ok: true, banner: document.getElementById('banner').textContent, "
                + "runDir: document.getElementById('run-dir').textContent, "
                + "verdict: document.getElementById('verdict').textContent, "
                + "checks: document.getElementById('checks').textContent, "
                + "rules: document.querySelectorAll('#rules .rule').length});");

        Assert.Contains("revision.cell.column", state.GetProperty("banner").GetString()!);
        Assert.Contains(
            "20260917-101532-top-plate-standards", state.GetProperty("runDir").GetString()!);

        Assert.Equal(string.Empty, state.GetProperty("verdict").GetString());
        Assert.Equal(string.Empty, state.GetProperty("checks").GetString());
        Assert.Equal(0, state.GetProperty("rules").GetInt32());
    }

    // ---- rendering ---------------------------------------------------------------------------

    private static JsonElement Render(string body) =>
        OffscreenStandardsPage.Evaluate("check(" + StandardsResultSample.Json() + ");" + body);

    private static JsonElement RenderMutated(string mutate, string body) =>
        OffscreenStandardsPage.Evaluate(
            "var result = " + StandardsResultSample.Json() + ";" + mutate + "check(result);" + body);

    private const string Headline =
        "return JSON.stringify({ok: true, text: document.getElementById('verdict').textContent, "
        + "headline: texts('#verdict .verdict-headline')[0]});";

    private static string[] Strings(JsonElement rendered, string name) =>
        rendered.GetProperty(name).EnumerateArray().Select(value => value.GetString()!).ToArray();

    private static string Text(JsonElement rendered)
    {
        Assert.True(
            rendered.GetProperty("ok").GetBoolean(),
            rendered.TryGetProperty("error", out JsonElement error)
                ? error.GetString()
                : "the page did not render");
        return rendered.GetProperty("text").GetString()!;
    }

    // ---- driving the real page ------------------------------------------------------------------

    private static JsonElement Drive(string stub, string press, string read) =>
        Drive(withBackend: true, stub: stub, presses: new[] { press }, read: read);

    private static JsonElement Drive(bool withBackend, string stub, string press, string read) =>
        Drive(withBackend, stub, new[] { press }, read);

    /// <summary>
    /// Loads the page with a host that answers `ready` the way <c>StandardsHost</c> does, runs
    /// <paramref name="stub"/> (which replaces `window.fetch`), presses things in order, and
    /// reports. The message recorder is installed after the page's own `ready` has been answered,
    /// so what it holds is what the engineer's presses sent.
    /// </summary>
    private static JsonElement Drive(bool withBackend, string stub, string[] presses, string read)
    {
        string? raw = null;

        OffscreenReviewPage.WithPage(
            StandardsPageFiles.PageUrl,
            page => { _ = new StandardsHostStub(page, withBackend); },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);
                await page.ExecuteScriptAsync(Recorder);
                await page.ExecuteScriptAsync(stub);
                await OffscreenReviewPage.Settled(page);
                foreach (string press in presses)
                {
                    await page.ExecuteScriptAsync(press);
                    await OffscreenReviewPage.Settled(page);
                }

                raw = await page.ExecuteScriptAsync(Wrap(read));
            });

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
                : "the page did not answer");
        return state;
    }

    private static string Wrap(string body) => @"
(function () {
  function texts(selector) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
    return out;
  }
  try {
" + body + @"
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}());
";

    /// <summary>Records every `{type, payload}` the page posts, without answering any of it.</summary>
    private const string Recorder = @"
(function () {
  window.__sent = [];
  window.__payloads = [];
  var post = window.chrome.webview.postMessage;
  window.chrome.webview.postMessage = function (message) {
    window.__sent.push(message.type);
    window.__payloads.push(JSON.stringify(message.payload));
    return post.call(window.chrome.webview, message);
  };
}());
";

    /// <summary>`POST /checks/standards` answered with the sample result.</summary>
    private static readonly string CallStub = @"
(function () {
  window.__calls = [];
  window.__body = null;
  window.fetch = function (url, request) {
    window.__calls.push(
      request.method + ' ' + String(url).replace('https://swreview.invalid/__backend', ''));
    window.__body = request.body;
    return Promise.resolve({
      ok: true,
      status: 201,
      text: function () { return Promise.resolve(JSON.stringify(" + StandardsResultSample.Json() + @")); }
    });
  };
}());
";

    /// <summary>
    /// The first `POST /checks/standards` is graded; the second is refused with the route's
    /// `ProfileInvalid`, which is what an engineer who edited the profile between two presses
    /// gets.
    /// </summary>
    private static readonly string RefusingSecondCallStub = @"
(function () {
  var calls = 0;
  window.fetch = function () {
    calls++;
    if (calls === 1) {
      return Promise.resolve({
        ok: true,
        status: 201,
        text: function () { return Promise.resolve(JSON.stringify(" + StandardsResultSample.Json() + @")); }
      });
    }
    return Promise.resolve({
      ok: false,
      status: 400,
      text: function () {
        return Promise.resolve(JSON.stringify({
          error_class: 'ProfileInvalid',
          message: 'revision.cell.column must be an integer of zero or more',
          retryable: false
        }));
      }
    });
  };
}());
";

    private const string PressCheck = @"
(function () { document.getElementById('run-check').click(); }());
";

    private const string ReadCalls =
        "return JSON.stringify({ok: true, calls: window.__calls, "
        + "body: JSON.parse(window.__body), sent: window.__sent, "
        + "startPayload: window.__payloads[0]});";

    private static async Task<string> ReadText(CoreWebView2 page, string elementId)
    {
        string raw = await page.ExecuteScriptAsync(
            "document.getElementById('" + elementId + "').textContent");
        return JsonDocument.Parse(raw).RootElement.GetString() ?? string.Empty;
    }

    private static async Task<bool> ReadEnabled(CoreWebView2 page, string elementId)
    {
        string raw = await page.ExecuteScriptAsync(
            "!document.getElementById('" + elementId + "').disabled");
        return JsonDocument.Parse(raw).RootElement.GetBoolean();
    }

    /// <summary>
    /// The host end of the bridge: it answers `ready` with the `init` <c>StandardsHost</c>
    /// sends - the endpoint, the token, the run root, the configured <b>profile path</b> and the
    /// open document - and it answers `standards.start` with `standards.extracted`, which is
    /// where the host stops.
    /// </summary>
    private sealed class StandardsHostStub
    {
        private readonly CoreWebView2 _page;
        private readonly bool _withBackend;

        public StandardsHostStub(CoreWebView2 page, bool withBackend)
        {
            _page = page;
            _withBackend = withBackend;
            page.WebMessageReceived += OnMessage;
        }

        public void Post(string type, object payload) =>
            _page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, payload }));

        private void OnMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
        {
            JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
            string type = message.GetProperty("type").GetString() ?? string.Empty;
            string id = message.GetProperty("id").GetString() ?? string.Empty;

            if (type == "ready")
            {
                Reply(id, "init", new
                {
                    backend = _withBackend
                        ? (object?)new { port = 51234, origin = "https://swreview.invalid/__backend" }
                        : null,
                    token = _withBackend ? "0FAKEtoken" : null,
                    run_root = @"C:\SwReviewRuns",
                    profile_path = @"C:\Users\pilot\AppData\Local\SwReview\standards.yaml",
                    document = new
                    {
                        path = @"C:\vault\top-plate.sldasm",
                        configuration = "AsBuilt",
                        kind = "assembly",
                    },
                    latest_check = (object?)null,
                });
                return;
            }

            if (type == "standards.start")
            {
                Reply(id, "standards.extracted", new
                {
                    run_dir = @"C:\SwReviewRuns\20260917-101532-top-plate-standards",
                    document = @"C:\vault\top-plate.sldasm",
                    configuration = "AsBuilt",
                    counts = new
                    {
                        documents = 3,
                        features = 44,
                        cut_list_items = 2,
                        drawing_sheets = (int?)null,
                    },
                    gaps = new object[0],
                });
            }
        }

        private void Reply(string id, string type, object payload) =>
            _page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id, payload }));
    }

    // ---- scanning -----------------------------------------------------------------------------

    private static readonly Regex SendCall = new Regex(
        @"\bsend\s*\(\s*['""]([a-z][a-z0-9_.]*)['""]", RegexOptions.Compiled);

    private static readonly Regex TypeProperty = new Regex(
        @"\btype\s*:\s*['""]([a-z][a-z0-9_.]*)['""]", RegexOptions.Compiled);

    private static readonly Regex StringLiteral = new Regex(
        @"'([^'\\\r\n]*)'|""([^""\\\r\n]*)""", RegexOptions.Compiled);

    private static readonly Regex DottedType = new Regex(
        @"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", RegexOptions.Compiled);

    private static readonly Regex ElementLookup = new Regex(
        @"\b(getElementById|byId)\s*\(\s*['""]([A-Za-z][A-Za-z0-9_-]*)['""]\s*\)",
        RegexOptions.Compiled);

    private static readonly Regex TokenInUrl = new Regex(
        @"[?&]\s*(access_)?token\s*=|['""][^'""]*/[^'""]*['""]\s*\+\s*[A-Za-z_.]*token",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex BlockComment = new Regex(
        @"/\*.*?\*/", RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex WholeLineComment = new Regex(
        @"^[ \t]*//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    private static readonly string[] FileExtensions =
        { "js", "css", "html", "htm", "md", "json", "jsonl", "txt", "svg", "png", "map", "yaml" };

    private static string Strip(string source) =>
        WholeLineComment.Replace(BlockComment.Replace(source, " "), string.Empty);

    private static IEnumerable<string> SentTypes(string source) =>
        SendCall.Matches(source).Cast<Match>()
            .Concat(TypeProperty.Matches(source).Cast<Match>())
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.Ordinal);

    private static IEnumerable<string> DottedLiterals(string source) =>
        StringLiteral.Matches(source).Cast<Match>()
            .Select(match => match.Groups[1].Success ? match.Groups[1].Value : match.Groups[2].Value)
            .Where(value => DottedType.IsMatch(value))
            .Where(value => !FileExtensions.Contains(value.Substring(value.LastIndexOf('.') + 1)))
            .Distinct(StringComparer.Ordinal);

    private static bool Mentions(string source, string type) =>
        source.Contains("'" + type + "'") || source.Contains("\"" + type + "\"");

    private static string Join(IEnumerable<string> values) =>
        string.Join(", ", values.OrderBy(value => value, StringComparer.Ordinal));

    // ---- the contract itself --------------------------------------------------------------------

    /// <summary>
    /// Sections 2 and 3 of `contracts/standards-check.md`, read as data the way
    /// <see cref="RemodelPageContractTests"/> reads its own contract, so a contract change lands
    /// here rather than in a hand-kept list that drifts.
    /// </summary>
    private sealed class StandardsContract
    {
        private StandardsContract(
            ISet<string> pageToHost, ISet<string> hostToPage, ISet<string> unsolicited)
        {
            PageToHost = pageToHost;
            HostToPage = hostToPage;
            Unsolicited = unsolicited;
        }

        /// <summary>The `type` column of "Standards page to host".</summary>
        public ISet<string> PageToHost { get; }

        /// <summary>
        /// The unsolicited table, plus every type named as a reply in the host-action column
        /// (`init`, `standards.extracted`, `entity.shown`, `status`, `error`). Replies are
        /// matched by `id` rather than by type, so they are read out of the prose defining them.
        /// </summary>
        public ISet<string> HostToPage { get; }

        /// <summary>Section 3 alone: what the page must handle without having asked.</summary>
        public ISet<string> Unsolicited { get; }

        public static StandardsContract Load()
        {
            var pageToHost = new HashSet<string>(StringComparer.Ordinal);
            var hostToPage = new HashSet<string>(StringComparer.Ordinal);
            var unsolicited = new HashSet<string>(StringComparer.Ordinal);

            string? section = null;
            foreach (string raw in ReviewPageFiles.ReadContract("standards-check.md").Split('\n'))
            {
                string line = raw.TrimEnd('\r');
                if (line.StartsWith("#", StringComparison.Ordinal))
                {
                    // Only a `##` heading opens a table this parser reads; the `###` block under
                    // section 1 is the result shape, not a message table.
                    section = line.StartsWith("## ", StringComparison.Ordinal)
                        ? line.Substring(3).Trim()
                        : null;
                    continue;
                }

                if (section == null || !line.StartsWith("|", StringComparison.Ordinal))
                {
                    continue;
                }

                string[] cells = line.Split('|');
                if (cells.Length < 3)
                {
                    continue;
                }

                List<string> types = BacktickedTypes(cells[1]).ToList();
                if (types.Count == 0)
                {
                    continue;
                }

                if (section.IndexOf("page to host", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    foreach (string type in types)
                    {
                        pageToHost.Add(type);
                    }

                    foreach (string reply in BacktickedTypes(cells[cells.Length - 2]))
                    {
                        hostToPage.Add(reply);
                    }
                }
                else if (section.IndexOf("Host to Standards page", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    foreach (string type in types)
                    {
                        unsolicited.Add(type);
                        hostToPage.Add(type);
                    }
                }
            }

            // A parser that quietly matched nothing would make every test above vacuous.
            Assert.True(
                pageToHost.Count == 6 && unsolicited.Count == 3 && hostToPage.Count >= 6,
                $"contracts/standards-check.md did not parse: {pageToHost.Count} page-to-host "
                    + $"rows ({Join(pageToHost)}), {unsolicited.Count} unsolicited rows "
                    + $"({Join(unsolicited)}). Did the table or heading shape change?");

            return new StandardsContract(pageToHost, hostToPage, unsolicited);
        }

        private static readonly Regex Backticked = new Regex(@"`([^`]+)`", RegexOptions.Compiled);

        private static readonly Regex TypeToken = new Regex(
            @"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$", RegexOptions.Compiled);

        private static IEnumerable<string> BacktickedTypes(string cell) =>
            Backticked.Matches(cell).Cast<Match>()
                .Select(match => match.Groups[1].Value
                    .Split(new[] { ' ', '{', '}', ',' }, StringSplitOptions.RemoveEmptyEntries)
                    .FirstOrDefault() ?? string.Empty)
                .Where(token => TypeToken.IsMatch(token));
    }
}

/// <summary>
/// Where the Standards page's shipped files live, and how a test renders inside one.
///
/// The same convention <see cref="ModelCheckPageFiles"/> uses, for the same reason: the files
/// are read from the build output, which is the copy the add-in actually serves, so a page file
/// that never reaches `web/` fails the scan instead of passing it from source.
/// </summary>
internal static class StandardsPageFiles
{
    /// <summary>The Standards page's folder inside the mapped web folder.</summary>
    public static string Folder =>
        Path.Combine(ReviewPageFiles.WebFolder, "Standards", "StandardsPage");

    /// <summary>The shared helpers this page loads (T030, T080).</summary>
    public static string SharedFolder => PageScripts.SharedFolder;

    /// <summary>The URL the add-in navigates the Standards tab to.</summary>
    public const string PageUrl = "https://swreview.invalid/Standards/StandardsPage/index.html";

    /// <summary>`index.html` as shipped.</summary>
    public static string IndexHtml() => Read("index.html");

    /// <summary>One page file, by name relative to <see cref="Folder"/> or by full path.</summary>
    public static string Read(string name)
    {
        AssertPresent();
        string path = Path.IsPathRooted(name) ? name : Path.Combine(Folder, name);
        Assert.True(File.Exists(path), $"{name} is missing from {Folder}.");
        return File.ReadAllText(path);
    }

    /// <summary>
    /// Every script the page runs: its own, and the shared helpers its own `index.html` loads -
    /// `shared/dom.js`, where this page's text reaches the DOM, and `shared/check-page.js`,
    /// which is the larger half of this page.
    /// </summary>
    public static IReadOnlyList<KeyValuePair<string, string>> Scripts()
    {
        AssertPresent();

        IReadOnlyList<KeyValuePair<string, string>> scripts =
            PageScripts.Collect(Folder, IndexHtml());

        Assert.True(
            scripts.Count >= 3,
            $"The Standards page ships fewer scripts than it loads from {SharedFolder}; "
                + "check the Content items in SwReview.AddIn.csproj.");
        return scripts;
    }

    private static void AssertPresent() =>
        Assert.True(
            Directory.Exists(Folder),
            $"The Standards page was not copied to {Folder}; check the Content items in "
                + "SwReview.AddIn.csproj.");
}

/// <summary>
/// The Standards page, loaded from the add-in's own virtual host in an offscreen WebView2, with
/// a script evaluated inside it. The boot is <see cref="OffscreenReviewPage"/>'s - the same page
/// file server, the same real page URL, the same real CSP - because every page in this pane
/// shares an origin and must not be tested under two different approximations of it.
/// </summary>
internal static class OffscreenStandardsPage
{
    /// <summary>
    /// Evaluates a JS function body in the loaded page and parses what it returned. The body
    /// runs with three helpers in scope: `check(result)` hands a `StandardsResult` to the page's
    /// own renderer, and `describe(node)`/`texts(selector)`/`attrs(selector, name)` report what
    /// actually landed in the DOM.
    /// </summary>
    public static JsonElement Evaluate(string body)
    {
        string? raw = null;

        OffscreenReviewPage.WithPage(
            StandardsPageFiles.PageUrl,
            null,
            async page =>
            {
                raw = await page.ExecuteScriptAsync(Prelude + body + Epilogue);
            });

        Assert.False(
            string.IsNullOrEmpty(raw) || raw == "null",
            "The page script threw before it could report: " + (raw ?? "<nothing>")
                + Environment.NewLine + body);

        string json = JsonDocument.Parse(raw!).RootElement.GetString()
            ?? throw new InvalidOperationException("The page script returned no value: " + raw);
        return JsonDocument.Parse(json).RootElement.Clone();
    }

    private const string Prelude = @"
(function () {
  function check(result) {
    var api = window.SwReviewStandards;
    if (!api || typeof api.renderResult !== 'function') {
      throw new Error('Standards/StandardsPage/standards.js must set ' +
        'window.SwReviewStandards.renderResult (T079): the tests render through the same ' +
        'function the tab renders through.');
    }
    api.renderResult(result);
    return document.body;
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

  function texts(selector) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
    return out;
  }

  function attrs(selector, name) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute(name)); }
    return out;
  }

  try {
";

    private const string Epilogue = @"
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}());
";
}

/// <summary>
/// One `StandardsResult` (`contracts/standards-check.md` section 1) for the page tests to
/// render.
///
/// Written out as a literal rather than produced by running the Python check layer, for the
/// reason <see cref="CheckResultSample"/> gives: these tests are about what the page does with
/// the shape, the contract is what both sides agree on, and a fixture generated by one side
/// would only prove that side consistent with itself. The values are chosen so every branch the
/// page has is reachable - the three verdict states through one mutation each, a check in two
/// buckets, a check that did not apply, an `error` finding, a `warning` finding, a waived one, a
/// subject with two instances and a subject that cannot be shown at all.
/// </summary>
internal static class StandardsResultSample
{
    /// <summary>A component name as SOLIDWORKS hands it over when someone types it in.</summary>
    public const string HostileComponentName = "<img src=x onerror=\"alert(1)\">";

    /// <summary>An observed string, which is assembled out of the model's own names.</summary>
    public const string HostileObserved =
        "</script><script>alert(2)</script><img src=x onerror=alert(3)>";

    /// <summary>A revision-table cell, which is whatever a draughtsman typed into it.</summary>
    public const string HostileCell = "<iframe src=javascript:alert(4)></iframe>";

    /// <summary>The sixteen checks, in `contracts/rules.md` order.</summary>
    public static readonly string[] CheckIds =
    {
        "standards.assembly.not_exploded",
        "standards.assembly.rebuild_errors",
        "standards.assembly.mate_references",
        "standards.assembly.one_fixed",
        "standards.assembly.fully_mated",
        "standards.assembly.not_transparent",
        "standards.assembly.not_hidden",
        "standards.part.sketches_fully_defined",
        "standards.part.rebuild_errors",
        "standards.part.material_assigned",
        "standards.part.cut_list_excluded",
        "standards.drawing.dimensions_not_overridden",
        "standards.drawing.annotations_not_dangling",
        "standards.drawing.revision_matches",
        "standards.drawing.no_itar_statement",
        "standards.document.data_card_complete",
    };

    public static string Json(
        string componentName = "bracket-3", string? observed = null, string? cell = null) =>
        JsonSerializer.Serialize(Build(
            componentName,
            observed ?? "1 mate entity did not resolve",
            cell ?? "B"));

    private static object Build(string componentName, string observed, string cell) => new
    {
        check_id = "20260917-101532-top-plate-standards",
        run_dir = @"C:\SwReviewRuns\20260917-101532-top-plate-standards",
        family = "standards",
        document = new
        {
            id = "doc:ab12",
            path = @"C:\vault\top-plate.sldasm",
            configuration = "AsBuilt",
            kind = "assembly",
        },
        extracted_at = "2026-09-17T10:15:32Z",
        profile = new
        {
            path = @"C:\Users\pilot\AppData\Local\SwReview\standards.yaml",
            sha256 = "9f2c4d1e",
        },
        extractor_profile = "standards",
        documents_graded = new object[]
        {
            new { id = "doc:ab12", kind = "assembly" },
            new { id = "doc:cd34", kind = "part" },
            new { id = "doc:ef56", kind = "assembly" },
        },
        verdict = new
        {
            state = "ready_coverage_incomplete",
            counts = new
            {
                error = 0,
                warning = 0,

                // `checked` is a C# keyword and the contract's field name; the escape is the
                // identifier and the serialized property is still `checked`.
                @checked = 9,
                skipped = 4,
                unresolved = 2,
                out_of_scope = 4,
            },
            waived = 1,
            unresolved_check_ids = new[]
            {
                "standards.assembly.not_transparent",
                "standards.assembly.mate_references",
            },
            notes = new[]
            {
                "1 finding waived by an accepted exception",
                "2 checks skipped because a profile list is empty",
                "no drawing graded",
            },
        },
        checks = CheckRows(),
        findings = new object[]
        {
            new
            {
                finding = Finding(
                    "F-001",
                    "standards.part.material_assigned",
                    "no material and no overridden mass",
                    new[] { "cmp:0003" },
                    null),
                check = "standards.part.material_assigned",
                severity = "error",
                statement =
                    "A part has a material assigned, or a deliberately overridden mass - and "
                    + "not both.",
                observed = "no material and no overridden mass",
                acceptable = true,
            },
            new
            {
                finding = Finding(
                    "F-002",
                    "standards.drawing.revision_matches",
                    "the revision table says " + cell + " and the property says C",
                    new string[0],
                    null),
                check = "standards.drawing.revision_matches",
                severity = "warning",
                statement =
                    "The revision table, the drawing's revision property and every referenced "
                    + "model's revision property agree.",
                observed = "the revision table says " + cell + " and the property says C",
                acceptable = false,
            },
            new
            {
                finding = Finding(
                    "F-003",
                    "standards.assembly.not_hidden",
                    observed,
                    new[] { "cmp:0009", "cmp:0011" },
                    "EX-004"),
                check = "standards.assembly.not_hidden",
                severity = "error",
                statement = "No component is left hidden.",
                observed,
                acceptable = true,
                exception = new
                {
                    id = "EX-004",
                    state = "active",
                    note = "hidden deliberately for the shipping configuration",
                },
            },
        },
        coverage = new object[]
        {
            Coverage("checked", "standards.assembly.not_exploded", "1 document(s)"),
            Coverage("checked", "standards.assembly.one_fixed", "1 document(s)"),
            Coverage(
                "skipped",
                "standards.part.cut_list_excluded",
                "no cut list on this part",
                "doc:cd34"),
            Coverage(
                "unresolved",
                "standards.assembly.not_transparent",
                "doc:ab12: the transparency polarity is unsettled (PROBE-2)"),
            Coverage(
                "unresolved",
                "standards.assembly.mate_references",
                "doc:ab12: one mate entity did not resolve"),
            Coverage(
                "out_of_scope",
                "standards.drawing.dimensions_not_overridden",
                "no drawing graded"),
        },
        subjects = new Dictionary<string, object[]>
        {
            {
                "F-001",
                new object[]
                {
                    new
                    {
                        kind = "component",
                        id = "cmp:0003",
                        feature_id = "cmp:0003",
                        name = "housing",
                        persist_ref = "YmFzZTY0",
                        persist_ref_scope = "doc:cd34",
                        parent_chain = new string[0],
                        component_ids = new[] { "cmp:0003" },
                        showable = true,
                    },
                }
            },
            {
                "F-002",
                new object[]
                {
                    new
                    {
                        kind = "revision_row",
                        id = "drv:0001",
                        feature_id = "drv:0001",
                        name = "revision row " + cell,
                        persist_ref = "cmV2aXNpb24=",
                        persist_ref_scope = "doc:ef56",
                        parent_chain = new string[0],
                        component_ids = new string[0],

                        // A reference the resolver cannot select: every drawing entity is
                        // `showable: false` while the shared resolver reads model entities only.
                        showable = false,
                    },
                }
            },
            {
                "F-003",
                new object[]
                {
                    new
                    {
                        kind = "component",
                        id = "cmp:0009",
                        feature_id = "cmp:0009",
                        name = componentName,
                        persist_ref = "Y29tcG9uZW50",
                        persist_ref_scope = "doc:ab12",
                        parent_chain = new string[0],
                        component_ids = new[] { "cmp:0009", "cmp:0011" },
                        showable = true,
                    },
                }
            },
        },
        exceptions_carried_forward = new
        {
            from_run = "20260916-173001-top-plate-standards",
            count = 2,
            reason = (string?)null,
        },
        rebuilt = false,

        // The ranking the backend computed for this run, carried on the body so the tab renders
        // it without a second call (contracts/attention.md section 5). The two check bodies
        // carry the identical block, which is why there is one fixture for both.
        attention = AttentionSample.Ranking(),
    };

    /// <summary>
    /// All sixteen, each with the buckets it landed in (D4). `mate_references` lands in two,
    /// which is the case a page that read one bucket per check would render wrongly, and four
    /// drawing-scope checks are `out_of_scope` because this run graded no drawing.
    /// </summary>
    private static object[] CheckRows()
    {
        var rows = new List<object>();
        foreach (string id in CheckIds)
        {
            rows.Add(new
            {
                check = id,
                severity = id.StartsWith("standards.drawing.revision", StringComparison.Ordinal)
                    || id.EndsWith("no_itar_statement", StringComparison.Ordinal)
                    ? "warning"
                    : "error",
                statement = id + " statement",
                worst_bucket = WorstBucket(id),
                buckets = Buckets(id),
            });
        }

        return rows.ToArray();
    }

    private static string WorstBucket(string id) =>
        id == "standards.assembly.mate_references" ? "unresolved"
        : id.StartsWith("standards.drawing.", StringComparison.Ordinal) ? "out_of_scope"
        : id == "standards.part.cut_list_excluded" ? "skipped"
        : "checked";

    private static object[] Buckets(string id)
    {
        if (id == "standards.assembly.mate_references")
        {
            // Two buckets over two documents: unresolved on one, checked on the other.
            return new object[]
            {
                new
                {
                    bucket = "unresolved",
                    document_ids = new[] { "doc:ab12" },
                    reason = "doc:ab12: one mate entity did not resolve",
                },
                new
                {
                    bucket = "checked",
                    document_ids = new[] { "doc:ef56" },
                    reason = "1 document(s)",
                },
            };
        }

        return new object[]
        {
            new
            {
                bucket = WorstBucket(id),
                document_ids = new[] { "doc:ab12" },
                reason = "1 document(s)",
            },
        };
    }

    private static object Coverage(
        string bucket, string check, string reason, string documentId = "doc:ab12") => new
    {
        bucket,
        check,
        scope = new
        {
            component_ids = new string[0],
            pairs = new object[0],
            configuration = "AsBuilt",
            positions = new string[0],
            document_ids = new[] { documentId },
        },
        reason,
        error = (string?)null,
    };

    private static object Finding(
        string id, string check, string observed, string[] componentIds, string? exceptionId) => new
    {
        id,
        check,
        title = check,
        status = exceptionId == null ? "suspected" : "checked_within_scope",
        severity = "high",
        component_ids = componentIds,
        drawing_locations = new object[0],
        provenance = new object[0],
        configuration = "AsBuilt",
        observed,
        requirement = "the release checklist",
        inputs = new[] { "component cmp:0003 housing persist_ref=none scope=doc:cd34" },
        calculation = (object?)null,
        tool_result_ids = new[] { 1 },
        coverage_limits = new string[0],
        recommended_action = "assign a material, or override the mass deliberately.",
        group = (object?)null,
        capture_ids = new string[0],
        disposition = (object?)null,
        exception_id = exceptionId,
    };
}
