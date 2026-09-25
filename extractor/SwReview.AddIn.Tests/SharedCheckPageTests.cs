using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T029. The family-neutral half of a check page, served from `web/shared/check-page.js` beside
/// `web/shared/dom.js` - the same virtual host, the same CSP, the same escaping point.
///
/// <b>Why it moved.</b> `Model/ModelCheckPage/check.js` was 1117 lines of which only the grade
/// header and the start verb are about the RMS rule family. The Standards check tab needs the
/// rest of it - the host channel, the authenticated `call` wrapper, the bucket chips, the
/// coverage and finding renderers, the Show and Accept flows - and a second copy of them would
/// be a second copy of the rules about what an engineer is allowed not to see (Principle VI)
/// and about which strings reach the DOM as text (FR-040). So there is one copy, both pages
/// load it from the same origin, and both pages' injection tests render through it.
///
/// <b>The gate is that this was a move.</b> `ModelCheckPageTests` and
/// `ModelCheckPageInjectionTests` pass <b>unedited</b> after it (quickstart gate 7b): the page
/// still exports `window.SwReviewCheck.renderResult`, still names its own route, and still
/// renders the same DOM. Those two files are the proof; the tests here say what is now where,
/// so that a regression names the reason rather than just the symptom.
///
/// Rendering assertions go through <see cref="OffscreenModelCheckPage"/> - the real page, the
/// real virtual host, the real CSP, in an offscreen WebView2 - because a static scan cannot
/// tell whether the shared script was served and allowed to run at all.
/// </summary>
public sealed class SharedCheckPageTests
{
    /// <summary>
    /// The family-neutral functions `tasks.md` T029 names, plus the ones they are built out of.
    /// Each must be defined in `web/shared/check-page.js` and in no page's own script.
    /// </summary>
    public static readonly string[] SharedFunctions =
    {
        // the host channel
        "send", "onHostMessage", "asError", "handleUnsolicited",

        // the backend
        "call", "backendError",

        // the check
        "loadLatestCheck", "acceptRule", "refreshResult", "markAccepted",

        // Show in SOLIDWORKS
        "showSubject", "cycleSubject",

        // rendering
        "renderNotExamined", "renderAttention", "renderCarriedForward", "renderFilters",
        "countByBucket", "documentSection", "bucketGroup", "subjectList", "subjectLine",
        "subjectMeta",

        // the chips and the page's chrome
        "toggleBucket", "applyFilter", "renderBackendState", "showStatus", "folderName",
    };

    /// <summary>What stays with the Model check page: its grade header and its own start verb.</summary>
    public static readonly string[] PageFunctions = { "renderGrade", "gradeHeading", "startCheck" };

    public static IEnumerable<object[]> EverySharedFunction() =>
        SharedFunctions.Select(name => new object[] { name });

    public static IEnumerable<object[]> EveryPageFunction() =>
        PageFunctions.Select(name => new object[] { name });

    // ---- where each half lives ---------------------------------------------------------------

    [Theory]
    [MemberData(nameof(EverySharedFunction))]
    public void EveryFamilyNeutralFunctionIsDefinedInTheSharedScript(string name)
    {
        Assert.True(
            Defines(SharedScript(), name),
            $"web/shared/check-page.js does not define `{name}`; T029 lists it as the "
                + "family-neutral half of the check page.");
    }

    /// <summary>
    /// A move, not a copy. A page that kept its own copy of one of these would drift from the
    /// other page the first time either was fixed, and the constitution's DRY rule names exactly
    /// this case.
    /// </summary>
    [Theory]
    [MemberData(nameof(EverySharedFunction))]
    public void NoFamilyNeutralFunctionIsStillDefinedByTheModelCheckPage(string name)
    {
        Assert.False(
            Defines(CheckScript(), name),
            $"Model/ModelCheckPage/check.js still defines `{name}`; it belongs to "
                + "web/shared/check-page.js now, and two copies of it is one copy out of date.");
    }

    /// <summary>
    /// The page keeps what is about its own rule family: the grade header, and the verb the
    /// button presses. Neither belongs in a file the Standards tab also loads.
    /// </summary>
    [Theory]
    [MemberData(nameof(EveryPageFunction))]
    public void TheGradeHeaderAndTheStartVerbStayWithTheModelCheckPage(string name)
    {
        Assert.True(
            Defines(CheckScript(), name),
            $"Model/ModelCheckPage/check.js no longer defines `{name}`.");
        Assert.False(
            Defines(SharedScript(), name),
            $"web/shared/check-page.js defines `{name}`, which is about the RMS rule family; "
                + "the shared half renders a header it is given.");
    }

    [Fact]
    public void TheSharedScriptAndStylesheetAreShippedBesideDomJs()
    {
        foreach (string name in new[] { "check-page.js", "check-page.css", "dom.js" })
        {
            Assert.True(
                File.Exists(Path.Combine(ModelCheckPageFiles.SharedFolder, name)),
                $"{name} was not copied to {ModelCheckPageFiles.SharedFolder}; check the Content "
                    + "items in SwReview.AddIn.csproj.");
        }
    }

    [Fact]
    public void TheModelCheckPageLoadsBothSharedFilesFromTheSharedFolder()
    {
        string index = ModelCheckPageFiles.IndexHtml();

        Assert.Contains("../../shared/dom.js", index, StringComparison.Ordinal);
        Assert.Contains("../../shared/check-page.js", index, StringComparison.Ordinal);
        Assert.Contains("../../shared/check-page.css", index, StringComparison.Ordinal);

        // In that order, and the last mention of each is its `<script>` tag: check-page.js reads
        // `window.SwReviewDom` as it loads, and the page's own script reads
        // `window.SwReviewCheckPage` as it loads.
        Assert.True(
            index.LastIndexOf("shared/dom.js", StringComparison.Ordinal)
                < index.LastIndexOf("shared/check-page.js", StringComparison.Ordinal),
            "dom.js must be loaded before check-page.js.");
        Assert.True(
            index.LastIndexOf("shared/check-page.js", StringComparison.Ordinal)
                < index.LastIndexOf("check.js", StringComparison.Ordinal),
            "check-page.js must be loaded before the page's own check.js.");
    }

    /// <summary>
    /// The shared half is served from the add-in's own virtual host under the page's own CSP,
    /// and it ran: `script-src 'self'` would have refused it from anywhere else, and a page that
    /// could not load it would render nothing at all.
    /// </summary>
    [Fact]
    public void TheSharedModuleIsServedUnderThePagesOwnOriginAndCspAndRuns()
    {
        JsonElement loaded = OffscreenModelCheckPage.Evaluate(
            "return JSON.stringify({ok: true, "
            + "factory: typeof (window.SwReviewCheckPage || {}).create, "
            + "dom: typeof (window.SwReviewDom || {}).el, "
            + "render: typeof (window.SwReviewCheck || {}).renderResult, "
            + "src: attrs('script', 'src'), "
            + "css: attrs('link', 'href')});");

        Assert.True(loaded.GetProperty("ok").GetBoolean());
        Assert.Equal("function", loaded.GetProperty("factory").GetString());
        Assert.Equal("function", loaded.GetProperty("dom").GetString());

        // What both existing page tests call: the export did not move.
        Assert.Equal("function", loaded.GetProperty("render").GetString());

        string[] sources = loaded.GetProperty("src").EnumerateArray()
            .Select(value => value.GetString()!).ToArray();
        Assert.Contains("../../shared/check-page.js", sources);
        Assert.Contains("../../shared/dom.js", sources);
        Assert.Contains(
            "../../shared/check-page.css",
            loaded.GetProperty("css").EnumerateArray().Select(value => value.GetString()));
    }

    // ---- the escaping point is still dom.js ---------------------------------------------------

    /// <summary>
    /// `web/shared/dom.js` stays the one place a string becomes a text node (FR-040). The shared
    /// half builds every node through it and reaches no DOM constructor of its own, so there is
    /// still exactly one file to audit for the rule, and it is not this one.
    /// </summary>
    [Theory]
    [InlineData("createTextNode")]
    [InlineData("createElement")]
    [InlineData("innerHTML")]
    [InlineData("outerHTML")]
    [InlineData("insertAdjacentHTML")]
    public void TheSharedScriptReachesNoDomConstructorOfItsOwn(string sink)
    {
        Assert.DoesNotContain(sink, Strip(SharedScript()), StringComparison.Ordinal);
    }

    [Fact]
    public void TheSharedScriptBuildsItsNodesThroughDomJs()
    {
        string shared = Strip(SharedScript());

        Assert.Contains("window.SwReviewDom", shared, StringComparison.Ordinal);
        Assert.Contains("dom.el(", shared, StringComparison.Ordinal);
        Assert.Contains("dom.button(", shared, StringComparison.Ordinal);
        Assert.Contains("dom.write(", shared, StringComparison.Ordinal);
    }

    /// <summary>
    /// dom.js itself is reused unchanged: it is loaded by both pages from the same folder, and
    /// nothing was added to it for this feature.
    /// </summary>
    [Fact]
    public void DomJsIsStillTheSameTenHelpersBothPagesLoad()
    {
        string dom = File.ReadAllText(Path.Combine(ModelCheckPageFiles.SharedFolder, "dom.js"));

        Assert.Equal(
            new[]
            {
                "el", "write", "clear", "append", "button", "field", "list", "scalar",
                "compact", "seconds",
            },
            Regex.Matches(dom, @"^  function ([A-Za-z0-9_]+)\(", RegexOptions.Multiline)
                .Cast<Match>().Select(match => match.Groups[1].Value).ToArray());
    }

    /// <summary>
    /// A feature name and an observed string that carry markup reach the screen as characters
    /// after the move, rendered by the shared half through the same real page and the same real
    /// CSP <see cref="ModelCheckPageInjectionTests"/> uses.
    /// </summary>
    [Fact]
    public void TheSharedRenderersStillRenderHostileTextAsLiteralCharacters()
    {
        string result = CheckResultSample.Json(
            featureName: CheckResultSample.HostileFeatureName,
            observed: CheckResultSample.HostileObserved);

        JsonElement rendered = OffscreenModelCheckPage.Evaluate(
            "check(" + result + "); return JSON.stringify(describe(document.getElementById('rules')));");

        Assert.True(rendered.GetProperty("ok").GetBoolean());
        Assert.Contains(CheckResultSample.HostileFeatureName, rendered.GetProperty("text").GetString()!);
        Assert.Equal(0, rendered.GetProperty("injected").GetInt32());
        Assert.Equal(0, rendered.GetProperty("handlers").GetInt32());
        Assert.DoesNotContain("<img", rendered.GetProperty("html").GetString()!);
    }

    // ---- the token and the origin --------------------------------------------------------------

    /// <summary>
    /// The `call` wrapper moved, and the rule moved with it: the token travels in the
    /// `Authorization` header and nowhere else, because a URL reaches access logs, WebView2's
    /// history and every crash dump (chat-api.md). This is the assertion
    /// `ModelCheckPageTests` makes about the page's own script, made where the code now is.
    /// </summary>
    [Fact]
    public void TheSharedCallWrapperSendsABearerHeaderAndNeverPutsTheTokenInAUrl()
    {
        string shared = Strip(SharedScript());

        Assert.Contains("Authorization", shared, StringComparison.Ordinal);
        Assert.Contains("'Bearer '", shared, StringComparison.Ordinal);

        // The origin is the one the host sent in `init` - the page's own, under `/__backend` -
        // and the page never builds a URL out of the port.
        Assert.Contains("state.backend.origin", shared, StringComparison.Ordinal);
        Assert.DoesNotContain("127.0.0.1", shared, StringComparison.Ordinal);
        Assert.DoesNotContain("http://", shared, StringComparison.Ordinal);

        string[] offences = shared
            .Split('\n')
            .Where(line => line.IndexOf("token", StringComparison.OrdinalIgnoreCase) >= 0)
            .Where(line => TokenInUrl.IsMatch(line))
            .Select(line => line.Trim())
            .ToArray();

        Assert.True(
            offences.Length == 0,
            "The token is being put into a URL:" + Environment.NewLine
                + string.Join(Environment.NewLine, offences));
    }

    /// <summary>
    /// And the rule holds over everything the page loads, not only over the file that builds the
    /// request. `ModelCheckPageTests.TheBackendIsCalledWithABearerHeaderAndNeverWithATokenInAUrl`
    /// makes the feature-003 version of this assertion against `check.js` alone; since the
    /// extraction that file builds no URL at all, so the scan is made here over every script the
    /// page serves. `check.js` stays unedited (T030's gate), and the one file that names the
    /// header is the shared call wrapper.
    ///
    /// Comments are stripped harder here than <see cref="Strip"/> strips them - trailing `//`
    /// as well as whole-line - because the point of the assertion is what the code does. The
    /// feature-003 test's `Strip` keeps a trailing comment, which is how `check.js` still
    /// satisfies its "Authorization" and "'Bearer '" literals after the move: a cross-reference
    /// rather than a call. That is named in the T030 report as a deviation to decide on, not
    /// worked around here.
    /// </summary>
    [Fact]
    public void NoScriptTheModelCheckPageLoadsPutsTheTokenInAUrl()
    {
        var offences = new List<string>();
        var namesTheHeader = new List<string>();

        foreach (KeyValuePair<string, string> script in ModelCheckPageFiles.Scripts())
        {
            string text = StripEveryComment(script.Value);

            if (text.IndexOf("'Bearer '", StringComparison.Ordinal) >= 0)
            {
                namesTheHeader.Add(script.Key);
            }

            offences.AddRange(text
                .Split('\n')
                .Where(line => line.IndexOf("token", StringComparison.OrdinalIgnoreCase) >= 0)
                .Where(line => TokenInUrl.IsMatch(line))
                .Select(line => script.Key + ": " + line.Trim()));
        }

        Assert.True(
            offences.Count == 0,
            "A script this page loads puts the token into a URL:" + Environment.NewLine
                + string.Join(Environment.NewLine, offences));

        string header = Assert.Single(namesTheHeader);
        Assert.EndsWith("check-page.js", header, StringComparison.Ordinal);
    }

    /// <summary>
    /// The shared half names no family's route. `POST /checks/rms` is the Model check page's,
    /// and the route the Standards page will call is its own; what is shared is the read-back
    /// and the exception routes, which are addressed by `check_id` and are the same for both.
    /// </summary>
    [Fact]
    public void TheSharedScriptNamesNoFamilysOwnCheckRoute()
    {
        string shared = Strip(SharedScript());

        Assert.DoesNotContain("/checks/rms", shared, StringComparison.Ordinal);
        Assert.Contains("/checks/rms", Strip(CheckScript()), StringComparison.Ordinal);
    }

    // ---- which shared scripts belong to which page ----------------------------------------------

    /// <summary>
    /// `web/shared` stopped being "one file every page loads" when `check-page.js` arrived, so
    /// "which shared scripts does this page run" has one answer (<see cref="PageScripts"/>) and
    /// it is the page's own `index.html`. A page scanned against a script it never loads fails
    /// for message types its own contract has no reason to define - which is what the Remodel
    /// page's contract tests would do if they still swept the folder whole.
    /// </summary>
    [Fact]
    public void EachPageIsScannedAgainstTheSharedScriptsItsOwnIndexHtmlLoads()
    {
        string[] check = ModelCheckPageFiles.Scripts().Select(script => script.Key).ToArray();
        string[] remodel = RemodelPageFiles.Scripts().Select(script => script.Key).ToArray();

        Assert.Contains(check, name => name.EndsWith("dom.js", StringComparison.Ordinal));
        Assert.Contains(check, name => name.EndsWith("check-page.js", StringComparison.Ordinal));

        Assert.Contains(remodel, name => name.EndsWith("dom.js", StringComparison.Ordinal));
        Assert.DoesNotContain(
            remodel, name => name.EndsWith("check-page.js", StringComparison.Ordinal));
    }

    // ---- nothing family-shaped stayed behind in the shared half ---------------------------------

    /// <summary>
    /// The counts sentence under the start button belongs to the family, not to the check page.
    /// The RMS result carries `grade`; a standards result carries `verdict` with a state, a
    /// waived count and the buckets error/warning/checked/skipped/unresolved/out_of_scope
    /// (`contracts/standards-check.md` D3, "`verdict` replaces `grade`"). A shared
    /// `describeCounts` reading `result.grade` would therefore print "0 failed, 0 warned, 0
    /// checked." after every standards run, and US3 would have to edit this file to fix it -
    /// which would mean the extraction was not clean.
    /// </summary>
    [Fact]
    public void TheSharedScriptNamesNeitherFamilysHeadlineObject()
    {
        string shared = Strip(SharedScript());

        Assert.DoesNotContain("grade", shared, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("verdict", shared, StringComparison.OrdinalIgnoreCase);

        // The shared half still prints the sentence after an accept, so it asks the page for it
        // rather than computing it: `markAccepted` is family-neutral, the counts are not.
        Assert.False(
            Defines(shared, "describeCounts"),
            "web/shared/check-page.js must not compute the counts sentence; it reads a family's "
                + "headline object to do it.");
        Assert.Contains("page.describeCounts(", shared, StringComparison.Ordinal);

        Assert.True(
            Defines(CheckScript(), "describeCounts"),
            "Model/ModelCheckPage/check.js must define `describeCounts`: it reads `result.grade`, "
                + "which is the RMS family's headline object.");
    }

    /// <summary>
    /// The Accept control's wording is the page's too. The Model check label says "for this
    /// part" because the RMS family grades parts; a standards run grades parts, assemblies and
    /// drawings, so its label is "for this document" (`contracts/standards-check.md` section 5
    /// and difference D12). A hard-coded label here would offer a drawing a button saying "for
    /// this part", and the only fix would again be an edit to this file.
    /// </summary>
    [Fact]
    public void TheAcceptControlsWordingIsSuppliedByThePage()
    {
        string shared = Strip(SharedScript());

        Assert.DoesNotContain("this part", shared, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("page.acceptLabel", shared, StringComparison.Ordinal);
        Assert.Contains("page.acceptNoteHint", shared, StringComparison.Ordinal);

        string check = Strip(CheckScript());
        Assert.Contains("Accept this rule for this part", check, StringComparison.Ordinal);
        Assert.Contains("Why this is acceptable on this part (required)", check, StringComparison.Ordinal);
    }

    /// <summary>
    /// The shared half posts only message types the check-page contract defines, and it decides
    /// none of them from a family: the start type is the owner's, passed in.
    /// </summary>
    [Fact]
    public void TheSharedScriptDoesNotNameAnyPagesStartType()
    {
        string shared = Strip(SharedScript());

        Assert.DoesNotContain("'check.start'", shared, StringComparison.Ordinal);
        Assert.Contains("'check.start'", Strip(CheckScript()), StringComparison.Ordinal);
    }

    // ---- the stylesheet ------------------------------------------------------------------------

    /// <summary>
    /// The same split in CSS: the shared rules are the bar, the banner, the session row, the
    /// chips and the rule list; what stays with the page is the grade block its header renders.
    /// </summary>
    [Theory]
    [InlineData(".chip")]
    [InlineData(".bucket-name")]
    [InlineData(".rule")]
    [InlineData(".subject")]
    [InlineData(".banner")]
    [InlineData(".filters")]
    [InlineData(".document-name")]

    // What was never read (feature: resolve-lightweight). Both tabs render the same block from
    // the same `not_examined` key through the same shared function, so its rule is shared too.
    [InlineData(".not-examined")]

    // The ranked rows (T038). Both tabs render the same block from the same `attention` key
    // through the same shared function, so its rules are shared too - a copy in one page's own
    // stylesheet would be the copy that stops matching the other the first time either is
    // touched.
    [InlineData(".attention")]
    [InlineData(".attention-heading")]
    [InlineData(".attention-rows")]
    [InlineData(".attention-row")]
    [InlineData(".attention-id")]

    // `.attention-check` left this list with feature 009: the shared row carries its check as
    // `data-check` and shows no check id on any tab (FR-025, research R2.21), so neither
    // stylesheet has a rule for it.
    [InlineData(".attention-reason")]
    [InlineData(".attention-empty")]
    public void TheSharedRulesAreInTheSharedStylesheetAndNotInThePages(string selector)
    {
        Assert.Contains(selector, SharedStyles(), StringComparison.Ordinal);
        Assert.DoesNotContain(selector, ModelCheckPageFiles.Read("check.css"), StringComparison.Ordinal);
    }

    /// <summary>
    /// Every rule row of a check tab, as feature 009 T068 reads it: its id, whether it has a fold,
    /// whether its `.rule-id` is inside that fold and what it says, whether the id appears on the
    /// line outside the fold, and what follows the row's head. One script for both tabs, because
    /// the row is the shared script's.
    /// </summary>
    internal const string RuleRowsScript = @"
var rules = document.querySelectorAll('#rules .rule');
var out = [];
for (var i = 0; i < rules.length; i++) {
  var rule = rules[i];
  var id = rule.getAttribute('data-rule-id');
  var fold = rule.querySelector(':scope > details.rule-fold');
  var idNode = rule.querySelector('.rule-id');
  var outside = '';
  for (var c = rule.firstChild; c; c = c.nextSibling) { if (c !== fold) { outside += c.textContent; } }
  var head = rule.querySelector(':scope > .rule-head');
  var next = head ? head.nextElementSibling : null;
  out.push({
    id: id,
    hasFold: !!fold,
    idInFold: !!(fold && idNode && fold.contains(idNode)),
    idText: idNode ? idNode.textContent : null,
    idOutside: outside.indexOf(id) >= 0,
    afterHead: next ? next.className : null
  });
}
return JSON.stringify({ok: true, rules: out});";

    [Theory]
    [InlineData(".grade")]
    [InlineData(".grade-heading")]
    [InlineData(".counts")]

    // `.fraction` left this list with feature 009 (FR-028): the grade header states the
    // unresolved rules by their statements and prints no fraction, so no stylesheet has its rule.
    [InlineData(".unresolved-rules")]
    [InlineData(".nothing-evaluated")]
    public void TheGradeRulesStayWithTheModelCheckPage(string selector)
    {
        Assert.Contains(selector, ModelCheckPageFiles.Read("check.css"), StringComparison.Ordinal);
        Assert.DoesNotContain(selector, SharedStyles(), StringComparison.Ordinal);
    }

    /// <summary>
    /// `web/shared/tokens.css` is the one palette and type scale every tab in the pane draws
    /// from, and both check pages link it <b>before</b> the stylesheets that name it.
    ///
    /// The order is the assertion. A page that loaded its own rules first would resolve every
    /// `var()` against nothing - which is not an error, it is a page with no colours at all -
    /// and the CSP allows no inline `<style>` to patch it up afterwards.
    /// </summary>
    [Fact]
    public void BothCheckPagesLinkTheSharedTokensBeforeTheStylesheetsThatNameThem()
    {
        Assert.True(
            File.Exists(Path.Combine(ModelCheckPageFiles.SharedFolder, "tokens.css")),
            "tokens.css was not copied to " + ModelCheckPageFiles.SharedFolder
                + "; check the Content items in SwReview.AddIn.csproj.");

        foreach (KeyValuePair<string, string> page in new[]
                 {
                     new KeyValuePair<string, string>("Model check", ModelCheckPageFiles.IndexHtml()),
                     new KeyValuePair<string, string>("Standards", StandardsPageFiles.IndexHtml()),
                 })
        {
            int tokens = page.Value.IndexOf("shared/tokens.css", StringComparison.Ordinal);
            int shared = page.Value.IndexOf("shared/check-page.css", StringComparison.Ordinal);

            Assert.True(tokens >= 0, $"The {page.Key} page does not link shared/tokens.css.");
            Assert.True(shared >= 0, $"The {page.Key} page does not link shared/check-page.css.");
            Assert.True(
                tokens < shared,
                $"The {page.Key} page links shared/tokens.css after shared/check-page.css; every "
                    + "rule in that file names a token defined in this one.");
        }
    }

    /// <summary>
    /// No stylesheet either check tab loads spells out a colour of its own.
    ///
    /// There is one palette, it is in `web/shared/tokens.css`, and it is defined three times
    /// there on purpose - once for light, once for `prefers-color-scheme: dark` and once for an
    /// explicit `data-theme`. A literal anywhere else is a colour that cannot follow the theme
    /// the workstation is in, and a second definition of a colour the rest of the pane already
    /// names. This is the rule the six hard-coded hexes these two tabs used to carry broke.
    /// </summary>
    [Theory]
    [InlineData("check-page.css")]
    [InlineData("check.css")]
    [InlineData("standards.css")]
    public void NoCheckStylesheetSpellsOutAColourOfItsOwn(string name)
    {
        string[] literals = ColourLiteral.Matches(Stylesheet(name)).Cast<Match>()
            .Select(match => match.Value)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

        Assert.True(
            literals.Length == 0,
            $"{name} spells out " + string.Join(", ", literals)
                + ". Every colour on these tabs is a token from web/shared/tokens.css, because a "
                + "literal here cannot follow the theme the workstation is in.");
    }

    /// <summary>
    /// A hex colour, or a function that builds one. Not an id selector. Shared with
    /// <see cref="RemodelPageContractTests"/>, which holds the Remodel tab's plan-lost notice to
    /// the same rule (decision 24A), rather than copied.
    /// </summary>
    internal static readonly Regex ColourLiteral = new Regex(
        @"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b|\b(?:rgba?|hsla?)\s*\(",
        RegexOptions.Compiled);

    private static string Stylesheet(string name)
    {
        if (name == "check.css")
        {
            return ModelCheckPageFiles.Read(name);
        }

        return name == "standards.css" ? StandardsPageFiles.Read(name) : ReadShared(name);
    }

    /// <summary>
    /// Both stylesheets are files rather than `<style>` blocks, because the CSP is
    /// `style-src 'self'` and the page it is served with refuses an inline one. Nothing in
    /// either is generated or set from script, so a hostile feature name cannot reach a
    /// declaration.
    /// </summary>
    [Fact]
    public void NeitherStylesheetIsGeneratedAndTheSharedOneCarriesNoImport()
    {
        Assert.DoesNotContain("@import", SharedStyles(), StringComparison.Ordinal);
        Assert.DoesNotContain("expression(", SharedStyles(), StringComparison.Ordinal);

        foreach (KeyValuePair<string, string> script in ModelCheckPageFiles.Scripts())
        {
            Assert.DoesNotContain(".style.", Strip(script.Value), StringComparison.Ordinal);
        }
    }

    // ---- reading the files -----------------------------------------------------------------------

    private static string SharedScript() => ReadShared("check-page.js");

    private static string SharedStyles() => ReadShared("check-page.css");

    private static string CheckScript() => ModelCheckPageFiles.Read("check.js");

    private static string ReadShared(string name)
    {
        string path = Path.Combine(ModelCheckPageFiles.SharedFolder, name);
        Assert.True(
            File.Exists(path),
            $"{name} is missing from {ModelCheckPageFiles.SharedFolder}.");
        return File.ReadAllText(path);
    }

    private static bool Defines(string source, string name) =>
        Regex.IsMatch(Strip(source), @"\bfunction\s+" + Regex.Escape(name) + @"\s*\(");

    private static readonly Regex TokenInUrl = new Regex(
        @"[?&]\s*(access_)?token\s*=|['""][^'""]*/[^'""]*['""]\s*\+\s*[A-Za-z_.]*token",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex BlockComment = new Regex(
        @"/\*.*?\*/", RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex WholeLineComment = new Regex(
        @"^[ \t]*//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    /// <summary>
    /// <see cref="Strip"/>, and trailing `//` comments as well - a `:` before the slashes is
    /// left alone so a URL in a string survives. Used where the assertion is about what the
    /// code does rather than about what is written near it.
    /// </summary>
    private static string StripEveryComment(string source) =>
        TrailingComment.Replace(Strip(source), string.Empty);

    private static readonly Regex TrailingComment = new Regex(
        @"(?<!:)//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    private static string Strip(string source) =>
        WholeLineComment.Replace(BlockComment.Replace(source, " "), string.Empty);
}
