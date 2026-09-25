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
using SwReview.AddIn.Remodel;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T132: the Remodel page's half of
/// `specs/004-resilient-remodeler/contracts/pane-remodel-messages.md`.
///
/// Three halves, and they answer different questions.
///
/// <b>The scan</b> is the scan <see cref="ModelCheckPageTests"/> already runs over tab 4,
/// applied to tab 5's tables and in <i>both</i> directions: nothing the page posts is invented,
/// no page-to-host row is orphaned, every dotted literal the page names is in one of the two
/// tables, every unsolicited host-to-page row is handled, and every element id the script looks
/// up exists in the HTML. A type the host has never heard of is answered `error` at runtime and
/// the feature behind it silently does nothing; an unsolicited type the page does not handle is
/// a progress stream nobody sees; an id that is not in the page is a `null` the script then
/// reads a property off.
///
/// <b>The boundary</b> is the page's origin. The CSP meta tag is byte-identical to feature
/// 002's, the page loads `web/shared/dom.js` from the shared virtual host instead of copying
/// its helpers - a second copy of the `textContent` rule is a security rule with a stale copy -
/// and the real Remodel tab, loaded through the add-in's own `TaskPaneControl`, cancels a
/// navigation off `https://swreview.invalid/` and opens no new window.
///
/// <b>The render</b> is the real page, loaded from the real virtual host in an offscreen
/// WebView2 under the real CSP, handed a `remodel.result` payload and asked what landed in the
/// DOM: the eight `RunState` values and no others, the attestation verdict, one change row per
/// `ChangeRecord` with its outcome and a Show button, the two grades as counts with the
/// unresolved rule ids named, the geometry verdict with its coverage statement, the rebuild
/// list with a reason per entry, and every rejected proposal with the rule that refused it.
///
/// Injection is not in scope here; that is <see cref="RemodelPageInjectionTests"/>.
/// </summary>
public sealed class RemodelPageContractTests
{
    private static readonly RemodelContract Contract = RemodelContract.Load();

    // ---- rule 1: nothing is invented -------------------------------------------------------

    [Fact]
    public void EveryTypeThePageSendsIsARowOfTheContract()
    {
        var undocumented = new List<string>();

        foreach (KeyValuePair<string, string> script in RemodelPageFiles.Scripts())
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
            "The Remodel page posts message types contracts/pane-remodel-messages.md does not "
                + "define:" + Environment.NewLine + string.Join(Environment.NewLine, undocumented)
                + Environment.NewLine + "Documented: " + Join(Contract.PageToHost));
    }

    // ---- rule 2: nothing is orphaned -------------------------------------------------------

    [Fact]
    public void EveryPageToHostRowIsExercisedByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            RemodelPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> missing = Contract.PageToHost
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            missing.Count == 0,
            "contracts/pane-remodel-messages.md defines host handlers the page never asks for: "
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

        foreach (KeyValuePair<string, string> script in RemodelPageFiles.Scripts())
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
            "The page names types that are in neither table of pane-remodel-messages.md (a typo "
                + "in one of these is invisible at runtime):" + Environment.NewLine
                + string.Join(Environment.NewLine, unknown)
                + Environment.NewLine + "pane-remodel-messages.md: "
                + Join(Contract.PageToHost.Concat(Contract.HostToPage)));
    }

    // ---- rule 4: the other direction --------------------------------------------------------

    /// <summary>
    /// Every unsolicited host-to-page row is handled by the page.
    ///
    /// This is the direction a scan of what the page *sends* cannot see. `remodel.progress` and
    /// `remodel.change` are the whole of "the change list grows live"; `document.changed` is
    /// how the tab learns the copy went away mid-run; `backend.stopped` is why a run stops
    /// answering. A host that posts one of these into a page that ignores it is a silence the
    /// engineer reads as "nothing is happening".
    /// </summary>
    [Fact]
    public void EveryUnsolicitedHostToPageRowIsHandledByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            RemodelPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> missing = Contract.Unsolicited
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            missing.Count == 0,
            "The host posts these unsolicited messages and the page names none of them: "
                + Join(missing)
                + Environment.NewLine
                + "An unhandled `remodel.change` is a change list that never grows, and an "
                + "unhandled `document.changed` is a run whose copy went away with nobody told.");
    }

    // ---- rule 5: the page and its script agree about the document ---------------------------

    [Fact]
    public void EveryElementIdTheScriptLooksUpExistsInTheHtml()
    {
        string html = RemodelPageFiles.IndexHtml();

        var present = new HashSet<string>(
            Regex.Matches(html, "\\bid=\"([^\"]+)\"").Cast<Match>().Select(match => match.Groups[1].Value),
            StringComparer.Ordinal);

        var missing = new List<string>();
        foreach (KeyValuePair<string, string> script in RemodelPageFiles.Scripts())
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

    // ---- the boundary -----------------------------------------------------------------------

    [Fact]
    public void IndexHtmlCarriesTheContractCspMetaTag()
    {
        Match meta = Regex.Match(
            RemodelPageFiles.IndexHtml(),
            @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""([^""]*)""\s*/?>",
            RegexOptions.IgnoreCase);

        Assert.True(meta.Success, "index.html carries no Content-Security-Policy meta tag.");

        // Byte-identical to the one feature 002's contracts/pane-host-messages.md prints, which
        // pane-remodel-messages.md adopts unchanged: five pages on one origin with five
        // policies is one policy nobody checked.
        Assert.Equal(Normalize(ContractCsp()), Normalize(meta.Groups[1].Value));
    }

    /// <summary>
    /// The page loads the shared helpers rather than shipping its own.
    ///
    /// `shared/dom.js` is where "every untrusted string reaches the DOM through
    /// `createTextNode`" is written down once. A page that copied those ten functions would be
    /// a second copy of a **security** rule, and a rule with two copies has one that is out of
    /// date - so the assertion is both halves: the page loads the shared file from the shared
    /// virtual host, and its own script neither reaches the DOM directly nor redefines the
    /// helpers.
    /// </summary>
    [Fact]
    public void ThePageLoadsTheSharedDomHelpersInsteadOfCopyingThem()
    {
        string html = RemodelPageFiles.IndexHtml();

        Assert.True(
            Regex.IsMatch(html, @"<script\s+src=""(\.\./)+shared/dom\.js""", RegexOptions.IgnoreCase),
            "index.html does not load ../../shared/dom.js from the shared virtual host; it has: "
                + string.Join(
                    ", ",
                    Regex.Matches(html, @"<script[^>]*>").Cast<Match>().Select(match => match.Value)));

        string script = Strip(RemodelPageFiles.Read("remodel.js"));

        Assert.Contains("SwReviewDom", script, StringComparison.Ordinal);
        Assert.DoesNotContain("createTextNode", script, StringComparison.Ordinal);
        Assert.False(
            Regex.IsMatch(script, @"\.\s*(textContent|innerText)\s*=[^=]"),
            "remodel.js writes text into the DOM itself. Every string goes through "
                + "shared/dom.js, which is the one copy of that rule.");
    }

    /// <summary>
    /// U13: when the host sends no refusal sentence of its own the page falls back to one, and
    /// it is one constant in the same plain words the host sends - not three copies of a
    /// sentence about a "remodel seat", which is a word from the build and not from the
    /// engineer's screen.
    /// </summary>
    [Fact]
    public void TheNoSeatFallbackIsOneConstantInTheHostsOwnPlainWords()
    {
        string script = Strip(RemodelPageFiles.Read("remodel.js"));

        Assert.Single(Regex.Matches(script, Regex.Escape("'" + RemodelHost.NoSeatMessage + "'")).Cast<Match>());
        Assert.DoesNotContain("remodel seat", script, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("swreview-extract", script, StringComparison.Ordinal);
    }

    /// <summary>
    /// The real tab, loaded by the add-in's own control: a navigation off
    /// `https://swreview.invalid/` is cancelled and no new window is ever opened.
    ///
    /// Asserted on the Remodel view rather than argued from the fact that every tab goes
    /// through one `AttachPageAsync`: tab 5 is created lazily, on a path of its own, and "the
    /// lazy path forgot a guard" is exactly the defect this test exists to catch. The Task Pane
    /// runs inside SOLIDWORKS with a backend token in its renderer, and a model's text can
    /// carry a link.
    ///
    /// The second handler reads what the add-in's handler already decided: handlers run in
    /// subscription order and the add-in subscribed first, so `Cancel` and `Handled` are
    /// observed as the page's own guards left them.
    /// </summary>
    [Fact]
    public void TheRemodelTabCancelsNavigationOffItsOriginAndOpensNoNewWindow()
    {
        bool? cancelledOffOrigin = null;
        bool ownPageAllowed = true;
        bool? newWindowHandled = null;
        string landedOn = string.Empty;

        WithRemodelTab(async page =>
        {
            page.NavigationStarting += (sender, args) =>
            {
                if (args.Uri.StartsWith(TaskPaneControl.PageOrigin, StringComparison.OrdinalIgnoreCase))
                {
                    ownPageAllowed &= !args.Cancel;
                }
                else
                {
                    cancelledOffOrigin = args.Cancel;
                }
            };
            page.NewWindowRequested += (sender, args) => newWindowHandled = args.Handled;

            page.Navigate("https://example.invalid/whatever");
            await Settled(page);

            await page.ExecuteScriptAsync("window.open('https://example.invalid/popup');");
            await Settled(page);

            landedOn = page.Source ?? string.Empty;
        });

        Assert.True(
            cancelledOffOrigin == true,
            "The Remodel tab did not cancel a navigation to https://example.invalid/ ("
                + (cancelledOffOrigin == null ? "NavigationStarting never fired" : "Cancel was false")
                + "). It ended on: " + landedOn);
        Assert.True(ownPageAllowed, "The Remodel tab cancelled its own page's navigation.");
        Assert.True(
            newWindowHandled == true,
            "The Remodel tab did not handle NewWindowRequested ("
                + (newWindowHandled == null ? "it never fired" : "Handled was false")
                + "), so a window.open would take the page's URL out of the pane's control.");

        Assert.StartsWith(TaskPaneControl.PageOrigin, landedOn, StringComparison.OrdinalIgnoreCase);
    }

    // ---- what an engineer sees: the run header ------------------------------------------------

    /// <summary>
    /// The eight `RunState` values of data-model.md section 11 and no others, each said in its
    /// own words, and a state this page has never heard of said as unknown rather than dressed
    /// up as one of the eight.
    /// </summary>
    [Fact]
    public void TheRunHeaderNamesEachOfTheEightRunStatesInItsOwnWords()
    {
        var said = new Dictionary<string, string>(StringComparer.Ordinal);

        foreach (string state in RemodelResultSample.RunStates)
        {
            JsonElement rendered = RenderMutated(
                "result.state = '" + state + "';",
                "return JSON.stringify(describe(document.getElementById('run-state')));");

            said[state] = Text(rendered);
            Assert.Contains(state, said[state]);
        }

        Assert.Equal(8, said.Count);
        Assert.Equal(
            8,
            said.Values.Select(text => text.Trim()).Distinct(StringComparer.Ordinal).Count());

        // Unknown stays unknown: a ninth state is not quietly rendered as one of the eight.
        string ninth = Text(RenderMutated(
            "result.state = 'resuming';",
            "return JSON.stringify(describe(document.getElementById('run-state')));"));
        Assert.Contains("resuming", ninth);
        Assert.Contains("not a state this tab knows", ninth);
    }

    /// <summary>
    /// The source attestation, which is the whole of "your file was never touched": `unchanged`,
    /// `changed` as a hard failure of the run, and - before the re-check has run - not yet
    /// known, which is neither of the other two.
    /// </summary>
    [Fact]
    public void TheRunHeaderShowsTheAttestationResultAndCallsAMismatchAHardFailure()
    {
        Assert.Contains(
            "unchanged",
            Text(Render("return JSON.stringify(describe(document.getElementById('attestation')));")));

        string changed = Text(RenderMutated(
            "result.attestation.matches = false;",
            "return JSON.stringify(describe(document.getElementById('attestation')));"));
        Assert.Contains("changed", changed);
        Assert.Contains("hard failure", changed);

        string pending = Text(RenderMutated(
            "result.attestation.matches = null;",
            "return JSON.stringify(describe(document.getElementById('attestation')));"));
        Assert.Contains("not been re-checked", pending);
        Assert.DoesNotContain("unchanged", pending);
    }

    // ---- what an engineer sees: the change list -------------------------------------------------

    [Fact]
    public void EveryChangeIsARowWithItsOutcomeAndAShowButton()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "seqs: attrs('#changes .change', 'data-seq'), "
            + "statuses: attrs('#changes .change', 'data-status'), "
            + "shows: attrs('#changes .change [data-action=\"show\"]', 'data-action'), "
            + "text: document.getElementById('changes').textContent});");

        Assert.Equal(new[] { "1", "2", "3", "4" }, Strings(rendered, "seqs"));

        // Every terminal status the contract defines, plus the `attempting` line a crash leaves
        // behind: a page that showed only `applied` rows would report a failed change as absent.
        Assert.Equal(
            new[] { "applied", "failed", "rolled_back", "attempting" },
            Strings(rendered, "statuses"));

        // One Show per row, including the failed ones: "which feature was that?" is the first
        // question a failed change raises.
        Assert.Equal(4, Strings(rendered, "shows").Length);

        string text = rendered.GetProperty("text").GetString()!;
        Assert.Contains("reorder", text);
        Assert.Contains("Fillet3", text);

        // The failed change names its bridge error code and the sentence beside it, rather than
        // being a row that simply says "failed".
        Assert.Contains("ReorderRefused", text);
        Assert.Contains("the anchor moved", text);
    }

    /// <summary>
    /// `remodel.change` arrives one line at a time while the run is applying, so the list grows
    /// rather than appearing at the end (contracts/pane-remodel-messages.md, host to page).
    /// </summary>
    [Fact]
    public void AChangePushedByTheHostIsAppendedToTheListAsItArrives()
    {
        JsonElement rendered = OffscreenRemodelPage.Evaluate(
            "remodel(" + RemodelResultSample.ResultJson() + ");"
            + "var before = document.querySelectorAll('#changes .change').length;"
            + "append(" + RemodelResultSample.LiveChangeJson() + ");"
            + "return JSON.stringify({ok: true, before: before, "
            + "seqs: attrs('#changes .change', 'data-seq'), "
            + "text: document.getElementById('changes').textContent});");

        Assert.Equal(4, rendered.GetProperty("before").GetInt32());
        Assert.Equal(new[] { "1", "2", "3", "4", "5" }, Strings(rendered, "seqs"));
        Assert.Contains("Shell1", rendered.GetProperty("text").GetString()!);
    }

    // ---- what an engineer sees: the grade and the geometry ---------------------------------------

    [Fact]
    public void TheGradeShowsBothSidesAsCountsWithTheFractionSecondaryAndTheUnresolvedRulesNamed()
    {
        string text = Text(Render(
            "return JSON.stringify(describe(document.getElementById('grade')));"));

        Assert.Contains("7 failed", text);
        Assert.Contains("1 failed", text);
        Assert.Contains("24 checked", text);
        Assert.Contains("30 checked", text);

        // The fraction is there and is not the headline, and the unresolved rules travel with
        // the counts by name: there is no letter grade and no single percentage.
        Assert.Contains("0.71", text);
        Assert.Contains("0.88", text);
        Assert.Contains("rms.params.units", text);

        // A grade that has not been measured yet is said so, never rendered as zeros - a
        // `grade_after` of no failures reads as a part that passed.
        string after = Text(RenderMutated(
            "result.grade_after = null;",
            "return JSON.stringify(describe(document.getElementById('grade')));"));
        Assert.Contains("not been measured", after);
        Assert.DoesNotContain("0 failed", after);
    }

    [Fact]
    public void TheGeometrySectionShowsTheVerdictTheComparedQuantitiesAndTheCoverageStatement()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "verdict: attrs('#geometry .verdict', 'data-verdict'), "
            + "quantities: texts('#geometry .delta .quantity'), "
            + "limits: texts('#geometry .coverage-limit'), "
            + "text: document.getElementById('geometry').textContent});");

        Assert.Equal(new[] { "pass" }, Strings(rendered, "verdict"));
        Assert.Contains("volume_m3", Strings(rendered, "quantities"));
        Assert.Contains("IDENTITY", rendered.GetProperty("text").GetString()!);

        // Printed on every run, including a passing one: the report says what was not checked
        // (Principle VI), so the verdict cannot be read as "nothing about this part changed".
        Assert.Equal(
            RemodelResultSample.CoverageLimits.Length, Strings(rendered, "limits").Length);
        Assert.Contains("a reflection", Strings(rendered, "limits"));

        // `unresolved` is its own verdict, never rounded to a pass.
        JsonElement unresolved = RenderMutated(
            "result.geometry.gate.verdict = 'unresolved';",
            "return JSON.stringify({ok: true, "
            + "verdict: attrs('#geometry .verdict', 'data-verdict'), "
            + "text: document.getElementById('geometry').textContent});");
        Assert.Equal(new[] { "unresolved" }, Strings(unresolved, "verdict"));

        // And a geometry reading that is not there yet is absent rather than a pass.
        string missing = Text(RenderMutated(
            "result.geometry = null;",
            "return JSON.stringify(describe(document.getElementById('geometry')));"));
        Assert.Contains("not been compared", missing);
        Assert.DoesNotContain("pass", missing);
    }

    // ---- what an engineer sees: the rebuild list and the judgement --------------------------------

    [Fact]
    public void TheRebuildListNamesAReasonPerEntryAndTheBlockingEdge()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "reasons: attrs('#rebuild .entry', 'data-reason'), "
            + "text: document.getElementById('rebuild').textContent});");

        Assert.Equal(
            new[] { "backward_reference", "shared_sketch", "unclassified" },
            Strings(rendered, "reasons"));

        string text = rendered.GetProperty("text").GetString()!;
        Assert.Contains("Fillet7", text);
        Assert.Contains("parent feat:0061 is in 6-Quarantine", text);
        Assert.Contains("feat:0044", text);
    }

    /// <summary>
    /// The judgement section: what the model proposed and what the rules did with it. A
    /// rejected proposal is **listed with the rule that refused it**, never omitted (FR-016,
    /// US4 scenario 7) - a page that showed only the accepted proposals would report the model
    /// as always right.
    /// </summary>
    [Fact]
    public void EveryRejectedProposalIsListedWithTheRuleThatRefusedItAndEveryAcceptedOneNamesItsModel()
    {
        JsonElement rendered = RenderPlan(
            "return JSON.stringify({ok: true, "
            + "rejected: attrs('#judgement .rejected', 'data-rule'), "
            + "text: document.getElementById('judgement').textContent});");

        Assert.Equal(new[] { "global.name_pattern" }, Strings(rendered, "rejected"));

        string text = rendered.GetProperty("text").GetString()!;
        Assert.Contains("propose_global", text);
        Assert.Contains("global name must be lower_snake_case", text);

        // Each accepted proposal carries the provider and the model that produced it, so "who
        // said this" is answerable on the screen the engineer is already looking at.
        Assert.Contains("Mounting slot", text);
        Assert.Contains("openai", text);
        Assert.Contains("a-model-id", text);

        // The deviations the planner made on its own are in the same place, in the words the
        // report uses for them.
        Assert.Contains("reviewed as structural; move to Quarantine if cosmetic", text);
    }

    // ---- the two buttons and the closing sentences -------------------------------------------------

    /// <summary>
    /// Discard deletes the `.SLDPRT` and nothing else, and the page says so before the engineer
    /// presses it - in the contract's own words, read out of the contract rather than restated
    /// here.
    /// </summary>
    [Fact]
    public void DiscardSaysExactlyWhatItDeletesAndOpenCopyIsOffered()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "open: texts('#open-copy'), discard: texts('#discard-copy'), "
            + "note: texts('#discard-note')});");

        Assert.Equal(new[] { "Open copy" }, Strings(rendered, "open"));
        Assert.Equal(new[] { "Discard copy" }, Strings(rendered, "discard"));
        Assert.Equal(new[] { ContractDiscardSentence() }, Strings(rendered, "note"));
    }

    /// <summary>
    /// FR-056: the page closes with the credit and with the sentence that keeps a clean rebuild
    /// from reading as an approval. It is not a footer that may be dropped when the page is
    /// long, which is why it is asserted beside the result rather than assumed.
    /// </summary>
    [Fact]
    public void ThePageClosesWithTheRmsCreditAndWithTheProposalSentence()
    {
        string text = Text(Render(
            "return JSON.stringify(describe(document.getElementById('credit')));"));

        Assert.Contains("Resilient Modeling Strategy", text);
        Assert.Contains("proposal the engineer accepts or discards", text);
        Assert.Contains("not an engineering acceptance result", text);
    }

    // ---- driving the page over the real transport -----------------------------------------------

    /// <summary>
    /// Stop stays pressable for as long as the run is running.
    ///
    /// The host answers `remodel.started` <b>before</b> it schedules phases B to D
    /// (`RemodelHost` hands `Execute` to `RemodelHostOptions.Schedule`, whose whole reason for
    /// existing is that "a run that occupied that thread would be a run that cannot be
    /// stopped"). So the reply to `remodel.start` is an acknowledgement that the run has begun,
    /// not a report that it has ended: a page that cleared its running state when that promise
    /// resolved would disable `#stop-run` one microtask after the run began and leave it
    /// disabled for every change the executor writes, which makes `remodel.stop` unsendable
    /// from the tab and the contract's Stop row dead.
    ///
    /// This is the one page test that drives the real message transport rather than calling
    /// `window.SwReviewRemodel` directly, because the defect it guards lives in the transport
    /// and is invisible to a renderer call.
    /// </summary>
    [Fact]
    public void StopStaysPressableFromRemodelStartedUntilTheRunReachesATerminalStatus()
    {
        var stopDisabled = new List<bool>();
        HostStub? stub = null;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page); },
            async page =>
            {
                await Settled(page);
                await page.ExecuteScriptAsync("document.getElementById('plan-run').click()");
                await Settled(page);
                await page.ExecuteScriptAsync("document.getElementById('start-run').click()");
                await Settled(page);

                // `remodel.started` has been answered and the executor is on its background
                // thread. This is the entire window in which Stop can be pressed.
                stopDisabled.Add(await Disabled(page, "stop-run"));

                stub!.Post(
                    "status", new { stage = "applying", message = "Applying change 3 of 12." });
                await Settled(page);
                stopDisabled.Add(await Disabled(page, "stop-run"));

                // The terminal status: the run is over, and only now is there nothing to stop.
                stub!.Post("status", new { stage = "ready", message = "The run ended 'saved'." });
                await Settled(page);
                stopDisabled.Add(await Disabled(page, "stop-run"));
            });

        Assert.Equal(new[] { false, false, true }, stopDisabled.ToArray());

        // One `remodel.start`: the page does not re-send it while the run is in flight.
        Assert.Equal(1, stub!.Starts);
    }

    /// <summary>
    /// Decision 22A over the real transport: a Start the host refuses because the tool service
    /// re-attached after the plan. The page prints the host's sentence verbatim - it has no
    /// words file and invents none - and, since no run began and no terminal `status` is
    /// coming, it leaves the running state at once: Stop is off, and Remodel a copy, the way
    /// back the sentence names, is pressable.
    /// </summary>
    [Fact]
    public void ARefusedStartPrintsTheHostsSentenceVerbatimAndLeavesTheWayBackToPlanOpen()
    {
        HostStub? stub = null;
        string? banner = null;
        bool? bannerHidden = null;
        var disabled = new Dictionary<string, bool>(StringComparer.Ordinal);

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page =>
            {
                stub = new HostStub(
                    page, startRefusal: ("SessionLost", RemodelHost.SessionLostMessage));
            },
            async page =>
            {
                await Settled(page);
                await page.ExecuteScriptAsync("document.getElementById('plan-run').click()");
                await Settled(page);
                await page.ExecuteScriptAsync("document.getElementById('start-run').click()");
                await Settled(page);

                banner = JsonDocument.Parse(await page.ExecuteScriptAsync(
                    "document.getElementById('banner').textContent")).RootElement.GetString();
                bannerHidden = JsonDocument.Parse(await page.ExecuteScriptAsync(
                    "document.getElementById('banner').hidden")).RootElement.GetBoolean();
                foreach (string id in new[] { "plan-run", "start-run", "stop-run" })
                {
                    disabled[id] = await Disabled(page, id);
                }
            });

        Assert.Equal(RemodelHost.SessionLostMessage, banner);
        Assert.False(bannerHidden);
        Assert.False(disabled["plan-run"]);
        Assert.True(disabled["stop-run"]);

        // Start stays pressable - the page keeps no list of classes to disable it on - and the
        // host answers the same refusal again, which the host's own tests pin.
        Assert.False(disabled["start-run"]);
        Assert.Equal(1, stub!.Starts);
    }

    /// <summary>
    /// The refusal sends the engineer back to plan, and it says so with the label they will see
    /// on the button, read from the page itself rather than restated, so the two cannot drift.
    /// </summary>
    [Fact]
    public void TheSessionLostMessageNamesThePlanButtonByItsLabel()
    {
        Match button = Regex.Match(
            RemodelPageFiles.Read("index.html"),
            @"<button[^>]*\bid=""plan-run""[^>]*>([^<]+)</button>");
        Assert.True(button.Success, "index.html has no plan-run button");

        string label = button.Groups[1].Value.Trim();
        Assert.Contains("press " + label + " to plan again", RemodelHost.SessionLostMessage, StringComparison.Ordinal);
    }

    [Fact]
    public void ABridgeWithoutARemodelSeatDisablesActionsAndShowsGuidanceBeforePosting()
    {
        HostStub? stub = null;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page, remodelAvailable: false); },
            async page =>
            {
                await Settled(page);

                Assert.True(await Disabled(page, "plan-run"));
                Assert.True(await Disabled(page, "start-run"));

                await page.ExecuteScriptAsync("document.getElementById('plan-run').click()");
                await page.ExecuteScriptAsync("document.getElementById('start-run').click()");
                await Settled(page);
            });

        Assert.Equal(0, stub!.Plans);
        Assert.Equal(0, stub.Starts);
    }

    [Fact]
    public void CapabilityBannerClearsWhenUnknownAvailabilityBecomesAvailable()
    {
        HostStub? stub = null;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page, emitUnknownCapability: true); },
            async page =>
            {
                await Settled(page);
                Assert.True(await Disabled(page, "plan-run"));
                Assert.Contains(
                    RemodelHost.SeatCheckingMessage,
                    await page.ExecuteScriptAsync("document.getElementById('banner').textContent"));

                stub!.Post(
                    "document.changed",
                    new
                    {
                        path = @"C:\\vault\\bracket.sldprt",
                        configuration = "Default",
                        kind = "part",
                        remodel = new { available = true, message = (string?)null },
                    });
                await Settled(page);

                Assert.False(await Disabled(page, "plan-run"));
                Assert.Equal(
                    "",
                    JsonDocument.Parse(await page.ExecuteScriptAsync(
                        "document.getElementById('banner').textContent")).RootElement.GetString());
            });
    }

    /// <summary>
    /// Decision 22A as the engineer sees it (the review of 2026-09-25). A re-attach after the plan
    /// reaches the page first as the host's availability refresh - `ToolServiceGate.Stop` publishes
    /// no service, so `RemodelHost.RefreshAvailability` posts `available` unknown with
    /// <see cref="RemodelHost.SeatCheckingMessage"/> - and the page itself disables Start, shows the
    /// wait and sends nothing. Once the new service is attached, Start is pressable again and the
    /// host answers it `SessionLost`, which the page prints verbatim. The host's order, `SessionLost`
    /// before the seat check, does not show here: it decides only a Start that reaches the host
    /// while the service is still restarting, which `RemodelHostTests` pins.
    ///
    /// *Amended 2026-09-25 (decision 24A):* the host now tells the page at the re-attach itself
    /// (`remodel.plan_lost`, the tests below), so this is the backstop - what a page sees when
    /// that notice has not reached it - and it stays pinned as such: this stub sends no notice.
    /// </summary>
    [Fact]
    public void AReattachAfterThePlanShowsTheWaitFirstAndTheNextStartIsRefusedAsSessionLost()
    {
        HostStub? stub = null;
        bool? startDisabledWhileAttaching = null;
        string? bannerWhileAttaching = null;
        int? startsWhileAttaching = null;
        bool? startDisabledOnceAttached = null;
        string? bannerAfterStart = null;

        object Document(bool? available, string? message) => new
        {
            path = @"C:\\vault\\bracket.sldprt",
            configuration = "Default",
            kind = "part",
            remodel = new { available, message },
        };

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page =>
            {
                stub = new HostStub(
                    page, remodelAvailable: true, startRefusal: ("SessionLost", RemodelHost.SessionLostMessage));
            },
            async page =>
            {
                await Settled(page);
                await page.ExecuteScriptAsync("document.getElementById('plan-run').click()");
                await Settled(page);

                stub!.Post("document.changed", Document(null, RemodelHost.SeatCheckingMessage));
                await Settled(page);
                startDisabledWhileAttaching = await Disabled(page, "start-run");
                bannerWhileAttaching = await Banner(page);
                await page.ExecuteScriptAsync("document.getElementById('start-run').click()");
                await Settled(page);
                startsWhileAttaching = stub.Starts;

                stub.Post("document.changed", Document(true, null));
                await Settled(page);
                startDisabledOnceAttached = await Disabled(page, "start-run");
                await page.ExecuteScriptAsync("document.getElementById('start-run').click()");
                await Settled(page);
                bannerAfterStart = await Banner(page);
            });

        Assert.True(startDisabledWhileAttaching);
        Assert.Equal(RemodelHost.SeatCheckingMessage, bannerWhileAttaching);
        Assert.Equal(0, startsWhileAttaching);
        Assert.False(startDisabledOnceAttached);
        Assert.Equal(RemodelHost.SessionLostMessage, bannerAfterStart);
        Assert.Equal(1, stub!.Starts);
    }

    // ---- a lost plan is told at once (decision 24A, T170) -------------------------------------

    /// <summary>
    /// The decision as the engineer sees it. After the plan, the host says it is lost
    /// (`remodel.plan_lost`): the notice shows the host's sentence verbatim - the page has no
    /// words of its own for it - Start is disabled and pressing it sends nothing, Plan again is
    /// offered and pressable, and the run status line no longer tells the engineer to press
    /// Start.
    /// </summary>
    [Fact]
    public void APlanLostNoticeShowsTheHostsSentenceVerbatimDisablesStartAndOffersPlanAgain()
    {
        HostStub? stub = null;
        LostPlanView? before = null;
        LostPlanView? after = null;
        int? startsAfterPressing = null;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page); },
            async page =>
            {
                await Settled(page);
                await Click(page, "plan-run");
                before = await ReadLostPlanView(page);

                stub!.Post(
                    "remodel.plan_lost",
                    new { run_dir = HostStub.RunDir, message = RemodelHost.PlanLostMessage });
                await Settled(page);
                after = await ReadLostPlanView(page);

                await Click(page, "start-run");
                startsAfterPressing = stub.Starts;
            });

        Assert.True(before!.NoticeHidden);
        Assert.False(before.StartDisabled);
        Assert.Equal("Planned. Press Start to apply the plan to the copy.", before.RunStatus);

        Assert.False(after!.NoticeHidden);
        Assert.Equal(RemodelHost.PlanLostMessage, after.NoticeText);
        Assert.True(after.StartDisabled);
        Assert.False(after.PlanAgainDisabled);
        Assert.False(after.PlanDisabled);
        Assert.Equal(string.Empty, after.RunStatus);
        Assert.Equal(0, startsAfterPressing);
    }

    /// <summary>
    /// Plan again is the way back. A refused Plan again - the part has unsaved changes - leaves
    /// the lost plan on screen and the notice standing, with the refusal in the banner. An
    /// accepted one plans a folder of its own, and that plan is not lost: the notice goes and
    /// Start is pressable again, and sent.
    /// </summary>
    [Fact]
    public void PlanAgainPlansAFolderOfItsOwnThatIsStartableAndARefusedOneLeavesTheNotice()
    {
        HostStub? stub = null;
        LostPlanView? refused = null;
        LostPlanView? planned = null;
        int plansAfterTheRefusal = 0;
        string? runDirShown = null;
        int startsAtTheEnd = 0;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page); },
            async page =>
            {
                await Settled(page);
                await Click(page, "plan-run");
                stub!.Post(
                    "remodel.plan_lost",
                    new { run_dir = HostStub.RunDir, message = RemodelHost.PlanLostMessage });
                await Settled(page);

                stub.PlanRefusal = ("DocumentDirty", "the part has unsaved changes.");
                await Click(page, "plan-again");
                refused = await ReadLostPlanView(page);
                plansAfterTheRefusal = stub.Plans;

                stub.PlanRefusal = null;
                await Click(page, "plan-again");
                planned = await ReadLostPlanView(page);
                runDirShown = await TextOf(page, "run-dir");

                await Click(page, "start-run");
                startsAtTheEnd = stub.Starts;
            });

        Assert.Equal(2, plansAfterTheRefusal);
        Assert.False(refused!.NoticeHidden);
        Assert.Equal(RemodelHost.PlanLostMessage, refused.NoticeText);
        Assert.True(refused.StartDisabled);
        Assert.Equal("the part has unsaved changes.", refused.Banner);

        Assert.True(planned!.NoticeHidden);
        Assert.False(planned.StartDisabled);
        Assert.Equal(HostStub.RunDirFor(2), runDirShown);
        Assert.Equal(1, startsAtTheEnd);
    }

    /// <summary>
    /// A notice is about one folder. One that arrives before the page has a plan is not kept
    /// for a plan that comes later, one naming another folder leaves the plan on screen
    /// startable, and one naming no folder at all is nobody's.
    /// </summary>
    [Fact]
    public void ANoticeForAFolderThePageIsNotShowingChangesNothing()
    {
        HostStub? stub = null;
        LostPlanView? afterThePlan = null;
        LostPlanView? afterTheOthers = null;
        int startsAtTheEnd = 0;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page); },
            async page =>
            {
                await Settled(page);
                stub!.Post(
                    "remodel.plan_lost",
                    new { run_dir = HostStub.RunDir, message = RemodelHost.PlanLostMessage });
                await Settled(page);
                await Click(page, "plan-run");
                afterThePlan = await ReadLostPlanView(page);

                stub.Post(
                    "remodel.plan_lost",
                    new { run_dir = HostStub.RunDirFor(2), message = RemodelHost.PlanLostMessage });
                stub.Post("remodel.plan_lost", new { message = RemodelHost.PlanLostMessage });
                await Settled(page);
                afterTheOthers = await ReadLostPlanView(page);

                await Click(page, "start-run");
                startsAtTheEnd = stub.Starts;
            });

        foreach (LostPlanView view in new[] { afterThePlan!, afterTheOthers! })
        {
            Assert.True(view.NoticeHidden);
            Assert.False(view.StartDisabled);
        }

        Assert.Equal(1, startsAtTheEnd);
    }

    /// <summary>
    /// A re-attach as the host tells it: the withdrawal's capability refresh (the wait, in the
    /// banner), the notice, then the new service's refresh. The wait clears from the banner as
    /// it always has, and takes nothing else with it: the notice stands, Start stays disabled
    /// once the seat is back, and Plan again - held while the seat was being checked, like the
    /// plan button - is pressable.
    /// </summary>
    [Fact]
    public void AReattachAsTheHostTellsItLeavesTheNoticeStandingOnceTheServiceIsBack()
    {
        HostStub? stub = null;
        LostPlanView? whileAttaching = null;
        LostPlanView? onceAttached = null;
        int startsAtTheEnd = -1;

        object Document(bool? available, string? message) => new
        {
            path = @"C:\\vault\\bracket.sldprt",
            configuration = "Default",
            kind = "part",
            remodel = new { available, message },
        };

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page, remodelAvailable: true); },
            async page =>
            {
                await Settled(page);
                await Click(page, "plan-run");

                stub!.Post("document.changed", Document(null, RemodelHost.SeatCheckingMessage));
                stub.Post(
                    "remodel.plan_lost",
                    new { run_dir = HostStub.RunDir, message = RemodelHost.PlanLostMessage });
                await Settled(page);
                whileAttaching = await ReadLostPlanView(page);

                stub.Post("document.changed", Document(true, null));
                await Settled(page);
                onceAttached = await ReadLostPlanView(page);

                await Click(page, "start-run");
                startsAtTheEnd = stub.Starts;
            });

        Assert.Equal(RemodelHost.SeatCheckingMessage, whileAttaching!.Banner);
        Assert.False(whileAttaching.NoticeHidden);
        Assert.True(whileAttaching.StartDisabled);
        Assert.True(whileAttaching.PlanAgainDisabled);

        Assert.Equal(string.Empty, onceAttached!.Banner);
        Assert.False(onceAttached.NoticeHidden);
        Assert.Equal(RemodelHost.PlanLostMessage, onceAttached.NoticeText);
        Assert.True(onceAttached.StartDisabled);
        Assert.False(onceAttached.PlanAgainDisabled);
        Assert.Equal(0, startsAtTheEnd);
    }

    /// <summary>
    /// A page that loads again after the notice starts from `init` alone (decision 24A, amended on
    /// review): the notice is told once per plan, so `init.latest_run.plan_lost` carries it. The
    /// page shows the plan's folder with the host's sentence verbatim in the notice, Start
    /// disabled and pressing it sending nothing, and Plan again pressable - the notice exactly as
    /// the unsolicited row gave it before the reload.
    /// </summary>
    [Fact]
    public void APageLoadedAgainAfterTheNoticeIsToldAgainByInit()
    {
        HostStub? stub = null;
        LostPlanView? beforeTheReload = null;
        LostPlanView? afterTheReload = null;
        string? runDirShown = null;
        int startsAtTheEnd = -1;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page, remodelAvailable: true); },
            async page =>
            {
                await Settled(page);
                await Click(page, "plan-run");
                stub!.Post(
                    "remodel.plan_lost",
                    new { run_dir = HostStub.RunDir, message = RemodelHost.PlanLostMessage });
                await Settled(page);
                beforeTheReload = await ReadLostPlanView(page);

                stub.LatestRun = LatestPlan(RemodelHost.PlanLostMessage);
                await Reload(page);
                afterTheReload = await ReadLostPlanView(page);
                runDirShown = await TextOf(page, "run-dir");

                await Click(page, "start-run");
                startsAtTheEnd = stub.Starts;
            });

        Assert.False(beforeTheReload!.NoticeHidden);

        Assert.Equal(HostStub.RunDir, runDirShown);
        Assert.False(afterTheReload!.NoticeHidden);
        Assert.Equal(RemodelHost.PlanLostMessage, afterTheReload.NoticeText);
        Assert.True(afterTheReload.StartDisabled);
        Assert.False(afterTheReload.PlanAgainDisabled);
        Assert.False(afterTheReload.PlanDisabled);
        Assert.Equal(0, startsAtTheEnd);
    }

    /// <summary>
    /// The other side: a page that loads again while its plan is still startable - `plan_lost`
    /// null - shows no notice and starts the plan.
    /// </summary>
    [Fact]
    public void APageLoadedAgainWithItsPlanStillStartableStartsIt()
    {
        HostStub? stub = null;
        LostPlanView? afterTheReload = null;
        string? runDirShown = null;
        int startsAtTheEnd = -1;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page, remodelAvailable: true); },
            async page =>
            {
                await Settled(page);
                await Click(page, "plan-run");

                stub!.LatestRun = LatestPlan(null);
                await Reload(page);
                afterTheReload = await ReadLostPlanView(page);
                runDirShown = await TextOf(page, "run-dir");

                await Click(page, "start-run");
                startsAtTheEnd = stub.Starts;
            });

        Assert.Equal(HostStub.RunDir, runDirShown);
        Assert.True(afterTheReload!.NoticeHidden);
        Assert.False(afterTheReload.StartDisabled);
        Assert.Equal(1, startsAtTheEnd);
    }

    /// <summary>
    /// The notice's line reaches the DOM as text, like every other string on this page: markup
    /// in it builds no element and runs nothing. The host's sentence carries none, and the page
    /// does not take that on trust.
    /// </summary>
    [Fact]
    public void ANoticeCarryingMarkupIsWrittenAsText()
    {
        const string hostile = "<img src=x onerror=\"document.title='owned'\">Plan again.";
        HostStub? stub = null;
        string? text = null;
        string? elements = null;
        string? title = null;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            page => { stub = new HostStub(page); },
            async page =>
            {
                await Settled(page);
                await Click(page, "plan-run");
                stub!.Post("remodel.plan_lost", new { run_dir = HostStub.RunDir, message = hostile });
                await Settled(page);

                text = await TextOf(page, "plan-lost-text");
                elements = await page.ExecuteScriptAsync(
                    "String(document.getElementById('plan-lost-text').children.length)");
                title = await page.ExecuteScriptAsync("document.title");
            });

        Assert.Equal(hostile, text);
        Assert.Equal("\"0\"", elements);
        Assert.DoesNotContain("owned", title, StringComparison.Ordinal);
    }

    /// <summary>
    /// The notice sends the engineer to Plan again, and says so with the label they will see on
    /// the button beside it, read from the page itself rather than restated, so the two cannot
    /// drift. Plan again is the owner's word for it.
    /// </summary>
    [Fact]
    public void ThePlanLostMessageNamesThePlanAgainButtonByItsLabel()
    {
        Match button = Regex.Match(
            RemodelPageFiles.Read("index.html"),
            @"<button[^>]*\bid=""plan-again""[^>]*>([^<]+)</button>");
        Assert.True(button.Success, "index.html has no plan-again button");

        string label = button.Groups[1].Value.Trim();
        Assert.Equal("Plan again", label);
        Assert.EndsWith("press " + label + ".", RemodelHost.PlanLostMessage, StringComparison.Ordinal);
    }

    /// <summary>
    /// The pane's palette is `web/shared/tokens.css` (the other tabs' rule, pinned there by
    /// <see cref="SharedCheckPageTests"/> and <see cref="ReviewPageInjectionTests"/>). The Remodel
    /// page links it before its own stylesheet, so a `var()` in that stylesheet resolves, and
    /// the notice's rules spell out no colour of their own: every colour they set is a token,
    /// which follows the theme the workstation is in.
    /// </summary>
    [Fact]
    public void TheNoticeIsDrawnWithTheSharedTokensLinkedBeforeThePagesOwnStylesheet()
    {
        Assert.True(
            File.Exists(Path.Combine(RemodelPageFiles.SharedFolder, "tokens.css")),
            "tokens.css was not copied to " + RemodelPageFiles.SharedFolder);

        string html = RemodelPageFiles.IndexHtml();
        int tokens = html.IndexOf("href=\"../../shared/tokens.css\"", StringComparison.Ordinal);
        int own = html.IndexOf("href=\"remodel.css\"", StringComparison.Ordinal);
        Assert.True(tokens >= 0, "the Remodel page does not link ../../shared/tokens.css");
        Assert.True(own > tokens, "the Remodel page must link shared/tokens.css before remodel.css");

        List<Match> rules = Regex.Matches(
                RemodelPageFiles.Read("remodel.css"),
                @"(?<selector>[^{}]*\.plan-lost[^{}]*)\{(?<body>[^{}]*)\}")
            .Cast<Match>()
            .ToList();
        Assert.NotEmpty(rules);

        foreach (Match rule in rules)
        {
            string body = rule.Groups["body"].Value;
            Assert.False(
                SharedCheckPageTests.ColourLiteral.IsMatch(body),
                "a plan-lost rule spells out a colour of its own: " + body.Trim());

            // Every declaration that sets a colour - not `border-left-width`, which sets none.
            foreach (Match declaration in Regex.Matches(
                         body,
                         @"(?<![a-z-])(?<property>color|(?:background|outline|border(?:-(?:top|right|bottom|left))?)(?:-color)?)\s*:\s*(?<value>[^;]+);"))
            {
                Assert.True(
                    declaration.Groups["value"].Value.Contains("var(--"),
                    "a plan-lost rule sets " + declaration.Groups["property"].Value + " without a token: "
                        + declaration.Value.Trim());
            }
        }

        Assert.Contains(rules, rule => rule.Groups["body"].Value.Contains("var(--"));
    }

    /// <summary>What the page shows of a lost plan, read off the live page in one go.</summary>
    private sealed class LostPlanView
    {
        public bool NoticeHidden { get; set; }

        public string? NoticeText { get; set; }

        public bool StartDisabled { get; set; }

        public bool PlanDisabled { get; set; }

        public bool PlanAgainDisabled { get; set; }

        public string? RunStatus { get; set; }

        public string? Banner { get; set; }
    }

    private static async Task<LostPlanView> ReadLostPlanView(CoreWebView2 page) => new LostPlanView
    {
        NoticeHidden = await Hidden(page, "plan-lost"),
        NoticeText = await TextOf(page, "plan-lost-text"),
        StartDisabled = await Disabled(page, "start-run"),
        PlanDisabled = await Disabled(page, "plan-run"),
        PlanAgainDisabled = await Disabled(page, "plan-again"),
        RunStatus = await TextOf(page, "run-status"),
        Banner = await Banner(page),
    };

    /// <summary>
    /// Loads the page again, as F5 or the pane building its view anew does, and lets it ask
    /// `ready` and apply the `init` it is answered with.
    /// </summary>
    private static async Task Reload(CoreWebView2 page)
    {
        var loaded = new TaskCompletionSource<bool>();
        void OnLoaded(object? sender, CoreWebView2NavigationCompletedEventArgs args) =>
            loaded.TrySetResult(args.IsSuccess);

        page.NavigationCompleted += OnLoaded;
        try
        {
            page.Reload();
            Assert.True(await loaded.Task, "the Remodel page did not load again");
        }
        finally
        {
            page.NavigationCompleted -= OnLoaded;
        }

        await Settled(page);
    }

    /// <summary>`init.latest_run` for the first plan's folder, as `RemodelHost.SendInit` writes it.</summary>
    private static object LatestPlan(string? planLost) => new
    {
        run_dir = HostStub.RunDir,
        at = "2026-09-16T14:22:01.0000000",
        state = "planned",
        plan_lost = planLost,
    };

    /// <summary>Presses a button the way the engineer does, and lets the page act on it.</summary>
    private static async Task Click(CoreWebView2 page, string elementId)
    {
        await page.ExecuteScriptAsync("document.getElementById('" + elementId + "').click()");
        await Settled(page);
    }

    /// <summary>An element's text, read off the live page.</summary>
    private static async Task<string?> TextOf(CoreWebView2 page, string elementId) =>
        JsonDocument.Parse(await page.ExecuteScriptAsync(
            "document.getElementById('" + elementId + "').textContent")).RootElement.GetString();

    /// <summary>Whether an element is hidden, read off the live page.</summary>
    private static async Task<bool> Hidden(CoreWebView2 page, string elementId) =>
        JsonDocument.Parse(await page.ExecuteScriptAsync(
            "document.getElementById('" + elementId + "').hidden")).RootElement.GetBoolean();

    /// <summary>The banner's text, read off the live page.</summary>
    private static async Task<string?> Banner(CoreWebView2 page) =>
        JsonDocument.Parse(await page.ExecuteScriptAsync(
            "document.getElementById('banner').textContent")).RootElement.GetString();

    /// <summary>Whether a button is disabled, read off the live page.</summary>
    private static async Task<bool> Disabled(CoreWebView2 page, string elementId)
    {
        string raw = await page.ExecuteScriptAsync(
            "document.getElementById('" + elementId + "').disabled");
        return JsonDocument.Parse(raw).RootElement.GetBoolean();
    }

    /// <summary>
    /// The host end of the bridge, answering the rows this test needs in the order
    /// `RemodelHost` answers them.
    /// </summary>
    private sealed class HostStub
    {
        /// <summary>The folder the first `remodel.plan` is answered with.</summary>
        public const string RunDir = @"C:\SwReviewRuns\20260916-142201-bracket-remodel";

        private readonly CoreWebView2 _page;

        /// <summary>How many plans have been answered `remodel.planned`.</summary>
        private int _planned;

        /// <param name="startRefusal">When set, `remodel.start` is answered with this
        /// `error {error_class, message}`, not retryable, as `RemodelHost` refuses one.</param>
        public HostStub(
            CoreWebView2 page,
            bool? remodelAvailable = null,
            bool emitUnknownCapability = false,
            (string ErrorClass, string Message)? startRefusal = null)
        {
            _page = page;
            RemodelAvailable = remodelAvailable;
            EmitRemodelCapability = remodelAvailable.HasValue || emitUnknownCapability;
            StartRefusal = startRefusal;
            page.WebMessageReceived += OnMessage;
        }

        private bool? RemodelAvailable { get; }

        private bool EmitRemodelCapability { get; }

        private (string ErrorClass, string Message)? StartRefusal { get; }

        /// <summary>How many `remodel.start` messages the page has posted.</summary>
        public int Starts { get; private set; }

        public int Plans { get; private set; }

        /// <summary>
        /// What `init.latest_run` carries - null, as for a host with no run yet, until a test
        /// sets it, as the real host answers a page that loads again after a plan.
        /// </summary>
        public object? LatestRun { get; set; }

        /// <summary>
        /// When set, `remodel.plan` is answered with this `error {error_class, message}`, as
        /// `RemodelHost` refuses a plan; when clear, each plan is answered with a folder of its
        /// own, as `RunFolders.CreateForRemodel` makes one per plan.
        /// </summary>
        public (string ErrorClass, string Message)? PlanRefusal { get; set; }

        /// <summary>The folder the <paramref name="plan"/>th accepted `remodel.plan` is answered with.</summary>
        public static string RunDirFor(int plan) => plan == 1 ? RunDir : RunDir + "-" + plan;

        /// <summary>Posts an unsolicited message, which carries no `id`.</summary>
        public void Post(string type, object payload) =>
            _page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, payload }));

        private void OnMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
        {
            JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
            string type = message.GetProperty("type").GetString() ?? string.Empty;
            string? id = message.TryGetProperty("id", out JsonElement value)
                ? value.GetString()
                : null;

            switch (type)
            {
                case "ready":
                    Reply("init", id, new
                    {
                        backend = new { port = 51234, origin = "https://swreview.invalid/__backend" },
                        token = "0FAKEtoken",
                        run_root = @"C:\SwReviewRuns",
                        document = new
                        {
                            path = @"C:\vault\bracket.sldprt",
                            configuration = "Default",
                            kind = "part",
                        },
                        limits = new { max_changes = 200, max_minutes = 30, max_rebuild_seconds = 60 },
                        remodel = EmitRemodelCapability
                            ? (object)new
                            {
                                available = RemodelAvailable,
                                message = RemodelAvailable == false
                                    ? RemodelHost.NoSeatMessage
                                    : RemodelAvailable == null
                                        ? RemodelHost.SeatCheckingMessage
                                        : null,
                            }
                            : null,
                        latest_run = LatestRun,
                    });
                    return;
                case "remodel.plan":
                    Plans++;
                    if (PlanRefusal.HasValue)
                    {
                        Reply("error", id, new
                        {
                            error_class = PlanRefusal.Value.ErrorClass,
                            message = PlanRefusal.Value.Message,
                            retryable = true,
                        });
                        return;
                    }

                    _planned++;
                    Reply("remodel.planned", id, new
                    {
                        run_dir = RunDirFor(_planned),
                        plan_summary = Parse(RemodelResultSample.PlanSummaryJson()),
                    });
                    return;
                case "remodel.start":
                    Starts++;
                    if (StartRefusal.HasValue)
                    {
                        Reply("error", id, new
                        {
                            error_class = StartRefusal.Value.ErrorClass,
                            message = StartRefusal.Value.Message,
                            retryable = false,
                        });
                        return;
                    }

                    Reply("remodel.started", id, new { chat_id = "20260916-142201-bracket-remodel" });
                    return;
                case "remodel.result":
                    Reply("remodel.result", id, Parse(RemodelResultSample.ResultJson()));
                    return;
                default:
                    Reply("ok", id, new { });
                    return;
            }
        }

        private static JsonElement Parse(string json) =>
            JsonDocument.Parse(json).RootElement.Clone();

        private void Reply(string type, string? id, object payload) =>
            _page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id, payload }));
    }

    // ---- rendering ---------------------------------------------------------------------------

    private static JsonElement Render(string body) =>
        OffscreenRemodelPage.Evaluate("remodel(" + RemodelResultSample.ResultJson() + ");" + body);

    /// <summary>Renders the sample result after <paramref name="mutate"/> has changed it.</summary>
    private static JsonElement RenderMutated(string mutate, string body) =>
        OffscreenRemodelPage.Evaluate(
            "var result = " + RemodelResultSample.ResultJson() + ";" + mutate
            + "remodel(result);" + body);

    /// <summary>Renders the plan summary the judgement section is drawn from.</summary>
    private static JsonElement RenderPlan(string body) =>
        OffscreenRemodelPage.Evaluate("plan(" + RemodelResultSample.PlanSummaryJson() + ");" + body);

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

    // ---- the real tab ---------------------------------------------------------------------------

    /// <summary>
    /// Builds the add-in's own <see cref="TaskPaneControl"/> over a real WebView2 environment,
    /// activates the Remodel tab the way a tab click does, and hands the loaded page to
    /// <paramref name="body"/>.
    ///
    /// The control is the product's, not a stand-in: what is under test is whether the tab that
    /// is created lazily gets the same guards as the two created at load.
    /// </summary>
    private static void WithRemodelTab(Func<CoreWebView2, Task> body)
    {
        string userDataFolder = Path.Combine(
            Path.GetTempPath(), "swreview-remodel-tab-" + Guid.NewGuid().ToString("N"));
        var options = new TaskPaneOptions(
            new RealEnvironmentFactory(userDataFolder), Path.GetTempPath())
        {
            WebFolder = ReviewPageFiles.WebFolder,
        };

        try
        {
            StaHost.Run(async form =>
            {
                using (var control = new TaskPaneControl(options))
                {
                    control.Dock = DockStyle.Fill;
                    form.Controls.Add(control);

                    await control.InitializeAsync();
                    await control.ActivateRemodelAsync();

                    Assert.True(
                        control.RemodelPageReady,
                        "The Remodel tab has no WebView2 after activation, so its guards cannot "
                            + "be observed. Is the Evergreen WebView2 runtime installed?");

                    CoreWebView2 page = await RemodelView(control);
                    await body(page);
                }
            });
        }
        finally
        {
            try
            {
                if (Directory.Exists(userDataFolder))
                {
                    Directory.Delete(userDataFolder, recursive: true);
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

    /// <summary>
    /// The Remodel tab's own WebView2, once it has finished loading the page.
    ///
    /// `ActivateRemodelAsync` returns when the control has been created and told to navigate;
    /// the navigation itself finishes a few message-loop turns later, so the wait is for the
    /// page URL rather than for the control.
    /// </summary>
    private static async Task<CoreWebView2> RemodelView(TaskPaneControl control)
    {
        for (int turn = 0; turn < 200; turn++)
        {
            CoreWebView2? loaded = Descendants(control)
                .OfType<WebView2>()
                .Select(view => view.CoreWebView2)
                .FirstOrDefault(core => core != null
                    && (core.Source ?? string.Empty).StartsWith(
                        TaskPaneControl.RemodelPageUrl, StringComparison.OrdinalIgnoreCase));

            if (loaded != null)
            {
                await Settled(loaded);
                return loaded;
            }

            await Task.Delay(50);
        }

        throw new InvalidOperationException(
            "The Remodel tab never navigated to " + TaskPaneControl.RemodelPageUrl
                + "; the views are on: "
                + string.Join(
                    ", ",
                    Descendants(control).OfType<WebView2>()
                        .Select(view => view.CoreWebView2?.Source ?? "<no core>")));
    }

    /// <summary>Lets the renderer act on what it was just told, bounded rather than raced.</summary>
    private static async Task Settled(CoreWebView2 page)
    {
        for (int turn = 0; turn < 12; turn++)
        {
            await page.ExecuteScriptAsync("0");
            await Task.Delay(15);
        }
    }

    private static IEnumerable<Control> Descendants(Control root)
    {
        foreach (Control child in root.Controls)
        {
            yield return child;
            foreach (Control descendant in Descendants(child))
            {
                yield return descendant;
            }
        }
    }

    /// <summary>The environment the add-in would create, over a folder this test owns.</summary>
    private sealed class RealEnvironmentFactory : IWebViewEnvironmentFactory
    {
        private readonly string _userDataFolder;

        public RealEnvironmentFactory(string userDataFolder) => _userDataFolder = userDataFolder;

        public Task<CoreWebView2Environment> CreateAsync() =>
            CoreWebView2Environment.CreateAsync(null, _userDataFolder, null);
    }

    // ---- scanning -------------------------------------------------------------------------------

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

    private static readonly Regex BlockComment = new Regex(
        @"/\*.*?\*/", RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex WholeLineComment = new Regex(
        @"^[ \t]*//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    /// <summary>
    /// Extensions a dotted literal is allowed to end in: `plan.json` and `report.md` are file
    /// names, not message types.
    /// </summary>
    private static readonly string[] FileExtensions =
        { "js", "css", "html", "htm", "md", "json", "jsonl", "txt", "svg", "png", "map" };

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

    /// <summary>The CSP feature 002's contract prints, read as data.</summary>
    private static string ContractCsp()
    {
        Match meta = Regex.Match(
            ReviewPageFiles.ReadContract("pane-host-messages.md"),
            @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""([^""]*)""\s*>",
            RegexOptions.IgnoreCase);

        Assert.True(meta.Success, "contracts/pane-host-messages.md no longer prints a CSP meta tag.");
        return meta.Groups[1].Value;
    }

    /// <summary>What Discard must say, quoted out of pane-remodel-messages.md.</summary>
    private static string ContractDiscardSentence()
    {
        Match sentence = Regex.Match(
            ReviewPageFiles.ReadContract("pane-remodel-messages.md"),
            @"""(Delete the copy\.[^""]*)""");

        Assert.True(
            sentence.Success,
            "contracts/pane-remodel-messages.md no longer quotes what Discard says.");
        return sentence.Groups[1].Value;
    }

    private static string Normalize(string policy) =>
        string.Join(
            "; ",
            policy.Split(';')
                .Select(directive => Regex.Replace(directive.Trim(), @"\s+", " "))
                .Where(directive => directive.Length > 0));

    // ---- the contract itself ----------------------------------------------------------------------

    /// <summary>
    /// The two message tables of `contracts/pane-remodel-messages.md`, read as data so a
    /// contract change lands here rather than in a hand-kept list that drifts.
    /// </summary>
    private sealed class RemodelContract
    {
        private RemodelContract(
            ISet<string> pageToHost, ISet<string> hostToPage, ISet<string> unsolicited)
        {
            PageToHost = pageToHost;
            HostToPage = hostToPage;
            Unsolicited = unsolicited;
        }

        /// <summary>The `type` column of "Page to host". One of its rows names three types.</summary>
        public ISet<string> PageToHost { get; }

        /// <summary>
        /// The unsolicited table, plus every type named as a reply in the host-action column
        /// (`init`, `remodel.planned`, `entity.shown`, `ok`, `error`). Replies are matched by
        /// `id` rather than by type, so they are read out of the prose that defines them.
        /// </summary>
        public ISet<string> HostToPage { get; }

        /// <summary>The "Host to page (unsolicited)" table alone: what the page must handle.</summary>
        public ISet<string> Unsolicited { get; }

        public static RemodelContract Load()
        {
            var pageToHost = new HashSet<string>(StringComparer.Ordinal);
            var hostToPage = new HashSet<string>(StringComparer.Ordinal);
            var unsolicited = new HashSet<string>(StringComparer.Ordinal);

            string? section = null;
            foreach (string raw in ReviewPageFiles.ReadContract("pane-remodel-messages.md").Split('\n'))
            {
                string line = raw.TrimEnd('\r');
                if (line.StartsWith("#", StringComparison.Ordinal))
                {
                    // Only a `##` heading opens a table this parser reads. The refusal classes
                    // are a `###` table under "Page to host" and are not message types.
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
                    // The header and the separator row carry no backticked type.
                    continue;
                }

                if (section.IndexOf("Page to host", StringComparison.OrdinalIgnoreCase) >= 0)
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
                else if (section.IndexOf("Host to page", StringComparison.OrdinalIgnoreCase) >= 0)
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
                pageToHost.Count == 11 && unsolicited.Count == 6 && hostToPage.Count >= 8,
                $"contracts/pane-remodel-messages.md did not parse: {pageToHost.Count} "
                    + $"page-to-host rows ({Join(pageToHost)}), {unsolicited.Count} unsolicited "
                    + $"rows ({Join(unsolicited)}). Did the table or heading shape change?");

            return new RemodelContract(pageToHost, hostToPage, unsolicited);
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
