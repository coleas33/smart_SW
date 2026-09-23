using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T081 (contract): the Model check page's half of
/// `specs/003-resilient-modeling/contracts/model-check.md`.
///
/// Two halves, and they answer different questions.
///
/// <b>The scan</b> is the same four-rule scan <see cref="ReviewPageContractTests"/> runs over
/// the Review page, applied to section 2 and section 3 of this feature's contract: nothing the
/// page posts is invented, no row of the table is orphaned, every dotted literal the page names
/// is in one of the two tables, and every element id the script looks up exists in the HTML. A
/// type the host has never heard of is answered `error` at runtime and the feature behind it
/// silently does nothing; an id that is not in the page is a `null` the script reads off.
///
/// <b>The render</b> is the real page, loaded from the real virtual host in an offscreen
/// WebView2 under the real CSP, handed a `CheckResult` and asked what landed in the DOM. That
/// is the only way to assert what an engineer sees: which buckets are visible before anyone
/// touches a chip, that the Accept control exists for a `fail` rule and does not exist for a
/// `warn` one, and that the Show button on a subject with several instances says which one it
/// will show.
///
/// Injection is not in scope here; that is <see cref="ModelCheckPageInjectionTests"/>.
/// </summary>
public sealed class ModelCheckPageTests
{
    private static readonly ModelCheckContract Contract = ModelCheckContract.Load();

    // ---- rule 1: nothing is invented -------------------------------------------------------

    [Fact]
    public void EveryTypeThePageSendsIsARowOfTheContract()
    {
        var undocumented = new List<string>();

        foreach (KeyValuePair<string, string> script in ModelCheckPageFiles.Scripts())
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
            "The Model check page posts message types contracts/model-check.md does not define:"
                + Environment.NewLine + string.Join(Environment.NewLine, undocumented)
                + Environment.NewLine + "Documented: " + Join(Contract.PageToHost));
    }

    // ---- rule 2: nothing is orphaned -------------------------------------------------------

    [Fact]
    public void EveryPageToHostRowIsExercisedByThePage()
    {
        string all = string.Join(
            Environment.NewLine,
            ModelCheckPageFiles.Scripts().Select(script => Strip(script.Value)));

        List<string> missing = Contract.PageToHost
            .Where(type => !Mentions(all, type))
            .OrderBy(type => type, StringComparer.Ordinal)
            .ToList();

        Assert.True(
            missing.Count == 0,
            "contracts/model-check.md defines host handlers the page never asks for: "
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

        foreach (KeyValuePair<string, string> script in ModelCheckPageFiles.Scripts())
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
            "The page names types that are in neither table of contracts/model-check.md (a typo "
                + "in one of these is invisible at runtime):" + Environment.NewLine
                + string.Join(Environment.NewLine, unknown)
                + Environment.NewLine + "model-check.md: "
                + Join(Contract.PageToHost.Concat(Contract.HostToPage)));
    }

    // ---- rule 4: the page and its script agree about the document ---------------------------

    [Fact]
    public void EveryElementIdTheScriptLooksUpExistsInTheHtml()
    {
        string html = ModelCheckPageFiles.IndexHtml();

        var present = new HashSet<string>(
            Regex.Matches(html, "\\bid=\"([^\"]+)\"").Cast<Match>().Select(match => match.Groups[1].Value),
            StringComparer.Ordinal);

        var missing = new List<string>();
        foreach (KeyValuePair<string, string> script in ModelCheckPageFiles.Scripts())
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
    /// token goes in the `Authorization` header and nowhere else, and the routes the page calls
    /// are the three of `contracts/model-check.md` section 1.
    /// </summary>
    [Fact]
    public void TheBackendIsCalledWithABearerHeaderAndNeverWithATokenInAUrl()
    {
        string script = Strip(ModelCheckPageFiles.Read("check.js"));

        Assert.Contains("Authorization", script, StringComparison.Ordinal);
        Assert.Contains("'Bearer '", script, StringComparison.Ordinal);
        Assert.Contains("/checks/rms", script, StringComparison.Ordinal);

        string[] offences = script
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

    // ---- what an engineer sees ---------------------------------------------------------------

    /// <summary>
    /// The grade header states every count and then says, in words, which rules reached no
    /// verdict: "Not graded, evidence missing:" and each rule's statement (feature 009 FR-028,
    /// research R2.23).
    ///
    /// Until feature 009 this pinned the verdict fraction ("0.50") and the unresolved rules by id.
    /// A fraction of the rules that reached a verdict is a number only its author reads, and a
    /// rule id is developer vocabulary: the header now names each unresolved rule by its
    /// statement (`rule_statements`, the backend's `RULES` catalogue) and keeps the ids behind a
    /// fold. The fraction stays in the body and in the report.
    /// </summary>
    [Fact]
    public void TheGradeHeaderShowsEveryCountAndNamesEveryUnresolvedRule()
    {
        JsonElement rendered = Render("return JSON.stringify(describe(document.getElementById('grade')));");

        string text = Text(rendered);

        Assert.Contains("2 failed", text);
        Assert.Contains("1 warned", text);
        Assert.Contains("3 checked", text);

        Assert.Contains("Not graded, evidence missing:", text);
        Assert.Contains(CheckResultSample.RefsDirectionStatement, text);
        Assert.Contains(CheckResultSample.SketchFullyDefinedStatement, text);
        Assert.DoesNotContain("0.50", text);
    }

    /// <summary>A grade whose every rule reached a verdict says so, and lists nothing.</summary>
    [Fact]
    public void AGradeWithNoUnresolvedRuleSaysEveryRuleReachedAVerdict()
    {
        JsonElement rendered = RenderMutated(
            "result.grade.unresolved_rule_ids = [];",
            "return JSON.stringify({ok: true, text: document.getElementById('grade').textContent, "
            + "folds: document.querySelectorAll('#grade details').length});");

        Assert.Contains("Every rule reached a verdict.", rendered.GetProperty("text").GetString()!);
        Assert.DoesNotContain("Not graded", rendered.GetProperty("text").GetString()!);
        Assert.Equal(0, rendered.GetProperty("folds").GetInt32());
    }

    /// <summary>
    /// An unresolved rule the catalogue has no statement for is named by its id - never dropped -
    /// and a body with no `rule_statements` at all (a backend before feature 009) names every
    /// unresolved rule by id (FR-030).
    /// </summary>
    [Fact]
    public void AnUnresolvedRuleTheCatalogueLacksIsNamedByItsId()
    {
        JsonElement lacking = RenderMutated(
            "delete result.rule_statements['rms.sketch.fully_defined'];",
            "return JSON.stringify({ok: true, statements: texts('#grade .unresolved-statements li')});");
        JsonElement older = RenderMutated(
            "delete result.rule_statements;",
            "return JSON.stringify({ok: true, statements: texts('#grade .unresolved-statements li')});");

        Assert.Equal(
            new[] { CheckResultSample.RefsDirectionStatement, "rms.sketch.fully_defined" },
            Strings(lacking, "statements"));
        Assert.Equal(new[] { "rms.refs.direction", "rms.sketch.fully_defined" }, Strings(older, "statements"));
    }

    /// <summary>A statement is the backend's text, and reaches the screen as characters (FR-029).</summary>
    [Fact]
    public void AHostileStatementIsLiteralText()
    {
        JsonElement rendered = RenderMutated(
            "result.rule_statements['rms.refs.direction'] = " + JsonSerializer.Serialize(CheckResultSample.HostileFeatureName) + ";",
            "return JSON.stringify(describe(document.getElementById('grade')));");

        Assert.Contains(CheckResultSample.HostileFeatureName, Text(rendered));
        Assert.Equal(0, rendered.GetProperty("injected").GetInt32());
    }

    [Fact]
    public void TheRuleListIsGroupedByDocumentAndThenByBucket()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "documents: attrs('#rules .document-group', 'data-document-id'), "
            + "buckets: attrs('#rules .document-group .bucket-group', 'data-bucket'), "
            + "rules: attrs('#rules .rule', 'data-rule-id')});");

        Assert.Equal(
            new[] { "doc:ab12" },
            rendered.GetProperty("documents").EnumerateArray().Select(value => value.GetString()).ToArray());

        string[] buckets = rendered.GetProperty("buckets").EnumerateArray()
            .Select(value => value.GetString()!).ToArray();

        // The order is the grade's order, so the thing to act on is at the top.
        Assert.Equal(new[] { "failed", "warned", "checked", "unresolved" }, buckets);

        Assert.Contains(
            "rms.detail.holes_last",
            rendered.GetProperty("rules").EnumerateArray().Select(value => value.GetString()));
    }

    // ---- the ranked rows ---------------------------------------------------------------------

    /// <summary>
    /// The first `top_n` rows of `result.attention`, in the order the backend supplied them,
    /// each naming the finding, the check and the reason it was placed (FR-023).
    ///
    /// The order is the assertion that matters. <see cref="AttentionSample"/>'s ids run
    /// F-007, F-008, F-003, F-002, F-004 and its checks are not alphabetical, so a page that
    /// sorted anything - by id, by check, by severity - renders a different list and fails
    /// here. The ranking is computed once, in `report/attention.py`, and rendered everywhere;
    /// a page that could reorder it would be a second policy nobody could point at.
    /// </summary>
    [Fact]
    public void TheRankedRowsRenderInTheOrderTheRankingSuppliedThem()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "ids: attrs('#attention .attention-row', 'data-finding-id'), "
            + "checks: attrs('#attention .attention-row', 'data-check'), "
            + "visibleChecks: document.querySelectorAll('#attention .attention-check').length, "
            + "reasons: texts('#attention .attention-reason'), "
            + "heading: texts('#attention .attention-heading')[0], "
            + "text: document.getElementById('attention').textContent});");

        Assert.Equal(AttentionSample.ShownFindingIds, Strings(rendered, "ids"));

        // The check travels on the row as `data-check` and is shown nowhere since feature 009
        // moved check ids out of the default view on every tab (FR-025, research R2.21); the rule
        // list below still names every rule, inside each row's fold.
        Assert.Equal(AttentionSample.ShownChecks, Strings(rendered, "checks"));
        Assert.Equal(0, rendered.GetProperty("visibleChecks").GetInt32());
        Assert.All(AttentionSample.ShownChecks, check => Assert.DoesNotContain(check, rendered.GetProperty("text").GetString()!));
        Assert.Equal(AttentionSample.ShownReasons, Strings(rendered, "reasons"));
        Assert.Equal(AttentionSample.Heading, rendered.GetProperty("heading").GetString());

        // The sixth row is beyond `top_n`: the page shows what the policy chose to amplify and
        // no more, and the rest is still in the rule list below in full.
        Assert.DoesNotContain(AttentionSample.BeyondTopN, rendered.GetProperty("text").GetString()!);
    }

    /// <summary>
    /// Feature 009 T068: a rule row's title is its statement, and its rule id is inside the row's
    /// own fold - every row has one now, a coverage row included, so the id is always one press
    /// away and never on the line (FR-025).
    /// </summary>
    [Fact]
    public void ARuleRowShowsItsStatementAsItsTitleAndItsRuleIdOnlyInsideItsFold()
    {
        JsonElement rendered = Render(SharedCheckPageTests.RuleRowsScript);

        JsonElement[] rules = rendered.GetProperty("rules").EnumerateArray().ToArray();
        Assert.True(rules.Length >= 8, "too few rule rows to prove every row.");
        foreach (JsonElement rule in rules)
        {
            string id = rule.GetProperty("id").GetString()!;
            Assert.True(rule.GetProperty("hasFold").GetBoolean(), id + " has no fold.");
            Assert.True(rule.GetProperty("idInFold").GetBoolean(), id + "'s rule id is not inside its fold.");
            Assert.Equal(id, rule.GetProperty("idText").GetString());
            Assert.False(rule.GetProperty("idOutside").GetBoolean(), id + "'s rule id is on the line.");
        }

        JsonElement holes = rules.Single(rule => rule.GetProperty("id").GetString() == "rms.detail.holes_last");
        Assert.Equal("statement", holes.GetProperty("afterHead").GetString());
    }

    /// <summary>
    /// The block sits above the bucket chips, which is where "start here" has to be for anyone
    /// to read it first (contracts/attention.md section 6, research R2.14).
    /// </summary>
    [Fact]
    public void TheRankedRowsSitAboveTheBucketChips()
    {
        JsonElement rendered = Render(
            "var attention = document.getElementById('attention');"
            + "var filters = document.getElementById('filters');"
            + "return JSON.stringify({ok: true, before: !!(attention.compareDocumentPosition(filters) "
            + "& Node.DOCUMENT_POSITION_FOLLOWING)});");

        Assert.True(
            rendered.GetProperty("before").GetBoolean(),
            "#attention must come before #filters in the document.");
    }

    /// <summary>
    /// A run that produced nothing to amplify says so in words rather than showing an empty
    /// list, and the sentence is the backend's - the page neither composes it nor decides when
    /// it applies (FR-024).
    /// </summary>
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

    /// <summary>
    /// A body from before this feature carries no `attention` at all, and a page that read one
    /// off it would print an empty heading over nothing on every re-read of an older check
    /// folder. Nothing is rendered, and the rest of the page is untouched.
    /// </summary>
    [Fact]
    public void ABodyWithNoRankingRendersNothingInTheSection()
    {
        JsonElement rendered = RenderMutated(
            "delete result.attention;",
            "return JSON.stringify({ok: true, "
            + "text: document.getElementById('attention').textContent, "
            + "children: document.getElementById('attention').childNodes.length, "
            + "rules: document.querySelectorAll('#rules .rule').length});");

        Assert.Equal(string.Empty, rendered.GetProperty("text").GetString());
        Assert.Equal(0, rendered.GetProperty("children").GetInt32());
        Assert.True(rendered.GetProperty("rules").GetInt32() > 0, "the rest of the page stopped rendering.");
    }

    /// <summary>
    /// Rendering is a function of the result: a second render replaces the rows rather than
    /// appending to them, which is what every other block on this page does and what an Accept
    /// re-read depends on.
    /// </summary>
    [Fact]
    public void ASecondRenderReplacesTheRowsRatherThanAppendingThem()
    {
        JsonElement rendered = Render(
            "check(" + CheckResultSample.Json() + ");"
            + "return JSON.stringify({ok: true, "
            + "ids: attrs('#attention .attention-row', 'data-finding-id'), "
            + "headings: texts('#attention .attention-heading')});");

        Assert.Equal(AttentionSample.ShownFindingIds, Strings(rendered, "ids"));
        Assert.Single(Strings(rendered, "headings"));
    }

    /// <summary>
    /// A ranked row prints what the ranking actually sent it.
    ///
    /// The row carries `title`, `status`, `severity`, `component_ids` and `consequence_class`
    /// and the pages rendered three fields of it, so the block that is supposed to be the first
    /// thing an engineer reads told them a finding id and made them go and look the rest up.
    /// Every one of those fields is on the row now, and the stripe restates - in the pane's own
    /// palette - the consequence class the policy already recorded. It is not a second ranking:
    /// nothing here reorders anything, and a class is a class whatever position it is in.
    /// </summary>
    [Fact]
    public void AStartHereRowCarriesItsTitleItsMetaAndTheStripeOfItsConsequenceClass()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "titles: texts('#attention .attention-title'), "
            + "metas: texts('#attention .attention-meta'), "
            + "components: texts('#attention .attention-components'), "
            + "classes: attrs('#attention .attention-row', 'class')});");

        Assert.Equal(AttentionSample.ShownTitles, Strings(rendered, "titles"));

        // Status and severity as plain words, in the order the contract states them. They are
        // read and printed; nothing on this page compares either of them. The components close
        // the same line since the renderer became one shared script (feature 009 increment 3):
        // the Review tab always put them there, and one row shape is the point of sharing it.
        foreach (string meta in Strings(rendered, "metas"))
        {
            Assert.StartsWith("demonstrated · medium", meta, StringComparison.Ordinal);
        }

        Assert.Equal("cmp:0002, cmp:0003", Strings(rendered, "components")[0]);
        Assert.EndsWith("cmp:0002, cmp:0003", Strings(rendered, "metas")[0], StringComparison.Ordinal);

        string[] classes = Strings(rendered, "classes");
        Assert.Equal(5, classes.Length);
        Assert.Contains("stripe-judge", classes[0]);
        Assert.Contains("stripe-judge", classes[1]);
        Assert.Contains("stripe-critical", classes[2]);
        Assert.Contains("stripe-critical", classes[3]);
        Assert.Contains("stripe-warn", classes[4]);
    }

    /// <summary>
    /// The judgement lever wins the stripe, and a consequence class the pane has never heard of
    /// gets the quiet one rather than none.
    ///
    /// `key.judgement` is the policy's own eleventh lever for "only an engineer can settle
    /// this", published on the row beside the eight it ranks by. A row it placed there wears the
    /// judgement stripe whatever its consequence class - which is what the mutation below
    /// proves, because `rebuild_breaker` maps to the critical stripe on its own.
    /// </summary>
    [Fact]
    public void TheJudgementKeyWinsTheStripeAndAnUnknownConsequenceClassFallsBackToQuiet()
    {
        JsonElement rendered = RenderMutated(
            "result.attention.rows[2].key.judgement = 0;"
            + "result.attention.rows[4].consequence_class = 'a-class-from-next-year';",
            "return JSON.stringify({ok: true, "
            + "classes: attrs('#attention .attention-row', 'class')});");

        string[] classes = Strings(rendered, "classes");
        Assert.Contains("stripe-judge", classes[2]);
        Assert.DoesNotContain("stripe-critical", classes[2]);
        Assert.Contains("stripe-quiet", classes[4]);
    }

    /// <summary>
    /// A ranked row points at its rule: the press that used to do nothing now scrolls the
    /// matching row into view and lights it.
    ///
    /// Both blocks already carried the same finding id and the engineer was already reading the
    /// top one. It amplifies and it still does not filter - except that a bucket which was
    /// hiding the row is turned back on, chip and all, because a press that scrolled to
    /// something invisible would read as a broken page. Exactly one row is lit at a time: two
    /// rows both claiming to be the one that was pointed at is worse than none.
    /// </summary>
    [Fact]
    public void PressingARankedRowLightsTheMatchingRuleAndOpensTheBucketThatWasHidingIt()
    {
        JsonElement rendered = Render(
            "var rows = document.querySelectorAll('#attention .attention-row');"
            + "var before = document.querySelectorAll('#rules .rule.flash').length;"
            + "rows[0].click();"
            + "var unranked = document.querySelectorAll('#rules .rule.flash').length;"
            + "rows[3].click();"
            + "var warned = attrs('#rules .rule.flash', 'data-finding-id');"
            + "rows[2].click();"
            + "return JSON.stringify({ok: true, before: before, unranked: unranked, "
            + "warned: warned, lit: attrs('#rules .rule.flash', 'data-finding-id'), "
            + "visible: attrs('#rules .bucket-group:not([hidden])', 'data-bucket'), "
            + "pressed: attrs('#filters .chip[aria-pressed=\"true\"]', 'data-bucket')});");

        Assert.Equal(0, rendered.GetProperty("before").GetInt32());

        // F-007 is ranked but produced no rule row in this result; the press does nothing rather
        // than lighting something that is not the row it names.
        Assert.Equal(0, rendered.GetProperty("unranked").GetInt32());

        // F-002 is in `warned`, which a page opens on.
        Assert.Equal(new[] { "F-002" }, Strings(rendered, "warned"));

        // F-003 is an accepted rule, so it is in `checked`, which a page opens with closed.
        Assert.Equal(new[] { "F-003" }, Strings(rendered, "lit"));
        Assert.Equal(new[] { "failed", "warned", "checked" }, Strings(rendered, "visible"));
        Assert.Equal(new[] { "failed", "warned", "checked" }, Strings(rendered, "pressed"));
    }

    /// <summary>
    /// A chip is a count first and a filter second: the number is what an engineer reads off the
    /// tab before deciding what to open, so it leads and it is in its own element - which is
    /// also what lets a pressed chip be filled in its bucket's own colour from the stylesheet,
    /// with no script setting one (the `.style.` ban).
    /// </summary>
    [Fact]
    public void EveryChipCarriesItsCountInALeadingElementAndItsBucketAsAClass()
    {
        JsonElement rendered = Render(
            "return JSON.stringify({ok: true, "
            + "buckets: attrs('#filters .chip', 'data-bucket'), "
            + "classes: attrs('#filters .chip', 'class'), "
            + "counts: texts('#filters .chip > b.chip-count'), "
            + "labels: texts('#filters .chip > .chip-label'), "
            + "pressed: attrs('#filters .chip[aria-pressed=\"true\"]', 'class')});");

        string[] buckets = Strings(rendered, "buckets");
        Assert.Equal(new[] { "failed", "warned", "checked", "unresolved" }, buckets);

        // The rows in each bucket, not the grade's counts: the chip says how much it will show.
        Assert.Equal(new[] { "1", "1", "4", "2" }, Strings(rendered, "counts"));
        Assert.Equal(buckets, Strings(rendered, "labels"));

        string[] classes = Strings(rendered, "classes");
        for (int index = 0; index < buckets.Length; index++)
        {
            Assert.Contains("bucket-" + buckets[index], classes[index]);
        }

        // Pressed needs both halves: the state the filter reads, and the class the fill comes
        // from. A chip with one and not the other would be a filter nobody can see the state of.
        string[] pressed = Strings(rendered, "pressed");
        Assert.Equal(2, pressed.Length);
        Assert.Contains("bucket-failed", pressed[0]);
        Assert.Contains("bucket-warned", pressed[1]);
    }

    /// <summary>
    /// The grade is a summary, not a headline: every count still reads exactly as it did, and the
    /// number of each is in its own element so the stylesheet can set it apart from its label.
    ///
    /// Feature 009 (FR-028) changed the rest of what this pinned: there is no `.fraction` element
    /// any more, and the ids of the rules that reached no verdict are inside a shut fold, in the
    /// mono face, while their statements are on the header.
    /// </summary>
    [Fact]
    public void EveryGradeCountKeepsItsTextAndLeadsWithItsNumberInItsOwnElement()
    {
        JsonElement rendered = Render(
            "var fold = document.querySelector('#grade .unresolved-rules details');"
            + "return JSON.stringify({ok: true, "
            + "counts: texts('#grade .counts .count'), "
            + "numbers: texts('#grade .counts .count > :first-child'), "
            + "leads: attrs('#grade .counts .count > :first-child', 'class'), "
            + "fractions: document.querySelectorAll('#grade .fraction').length, "
            + "foldOpen: fold ? fold.open : null, "
            + "ids: fold ? texts('#grade .unresolved-rules details .mono') : []});");

        Assert.Equal(
            new[]
            {
                "2 failed", "1 warned", "3 checked", "0 skipped", "2 unresolved", "0 out of scope",
            },
            Strings(rendered, "counts"));
        Assert.Equal(new[] { "2", "1", "3", "0", "2", "0" }, Strings(rendered, "numbers"));
        Assert.All(Strings(rendered, "leads"), value => Assert.Equal("count-n", value));

        Assert.Equal(0, rendered.GetProperty("fractions").GetInt32());
        Assert.False(rendered.GetProperty("foldOpen").GetBoolean(), "the rule ids' fold arrived open.");
        Assert.Equal(
            new[] { "rms.refs.direction, rms.sketch.fully_defined" },
            Strings(rendered, "ids"));
    }

    /// <summary>
    /// What an engineer does about a rule is one press away, and what the rule is stays on the
    /// line. The Accept control's DOM contract is unchanged by the move - it is still a
    /// `[data-action="accept"]` with a sibling required `input.note` - and a coverage row, which
    /// has no statement and no observed, keeps its reason on the line, because folded away it
    /// would leave a check id and nothing else.
    /// </summary>
    [Fact]
    public void ARulesRecommendedActionAndAcceptControlSitBehindOneClosedFold()
    {
        JsonElement rendered = Render(
            "var fail = document.querySelector('.rule[data-rule-id=\"rms.detail.holes_last\"]');"
            + "var fold = fail.querySelector('details.rule-fold');"
            + "var note = fold.querySelector('input.note');"
            + "var coverage = document.querySelector('.rule[data-rule-id=\"rms.refs.direction\"]');"
            + "return JSON.stringify({ok: true, "
            + "open: !!fold.open, "
            + "summary: fold.querySelector('summary').textContent, "
            + "reasonsInFold: fold.querySelectorAll('p.reason').length, "
            + "reasonsOnRow: fail.querySelectorAll('p.reason').length, "
            + "acceptsInFold: fold.querySelectorAll('[data-action=\"accept\"]').length, "
            + "acceptsOnRow: fail.querySelectorAll('[data-action=\"accept\"]').length, "
            + "noteRequired: !!note.required, "
            + "notePlaceholder: note.getAttribute('placeholder'), "
            + "statement: fail.querySelector('p.statement').textContent, "
            + "coverageFolds: coverage.querySelectorAll('details').length, "
            + "coverageReason: coverage.querySelector('p.reason').textContent});");

        Assert.False(
            rendered.GetProperty("open").GetBoolean(),
            "The fold opens by default, so every row states its remedy in full again.");
        Assert.Equal("Recommended, and accept", rendered.GetProperty("summary").GetString());

        // In the fold and nowhere else: one recommended action and one Accept control per row.
        Assert.Equal(1, rendered.GetProperty("reasonsInFold").GetInt32());
        Assert.Equal(1, rendered.GetProperty("reasonsOnRow").GetInt32());
        Assert.Equal(1, rendered.GetProperty("acceptsInFold").GetInt32());
        Assert.Equal(1, rendered.GetProperty("acceptsOnRow").GetInt32());

        Assert.True(rendered.GetProperty("noteRequired").GetBoolean(), "The note is not required.");
        Assert.Contains("required", rendered.GetProperty("notePlaceholder").GetString()!);

        // What the rule is stays on the line.
        Assert.Equal(
            "Holes are the last features in the Detail group.",
            rendered.GetProperty("statement").GetString());

        // Until feature 009 a coverage row had no fold. Every rule row has one now, holding its
        // rule id (FR-025, T068) - and the reason still stays on the line, because folded away a
        // coverage row would say nothing at all.
        Assert.Equal(1, rendered.GetProperty("coverageFolds").GetInt32());
        Assert.Equal(
            "reference directions are not in the evidence package",
            rendered.GetProperty("coverageReason").GetString());
    }

    /// <summary>
    /// How much of a document is on screen, beside its name - and it moves with the chips.
    ///
    /// A chip hides rows rather than re-rendering them, so a count taken only at render time
    /// would be wrong the moment one was pressed, and a wrong count beside a document heading
    /// reads as the document having fewer rules than it has.
    /// </summary>
    [Fact]
    public void EachDocumentHeadingSaysHowManyOfItsRulesAreOnScreenAndTheCountMovesWithTheChips()
    {
        JsonElement rendered = Render(
            "var before = texts('#rules .document-group .document-name .document-count');"
            + "document.querySelector('#filters .chip[data-bucket=\"checked\"]').click();"
            + "var after = texts('#rules .document-group .document-name .document-count');"
            + "document.querySelector('#filters .chip[data-bucket=\"failed\"]').click();"
            + "return JSON.stringify({ok: true, before: before, after: after, "
            + "closed: texts('#rules .document-group .document-name .document-count')});");

        // Eight rows in the one document; `failed` and `warned` are the two a page opens on.
        Assert.Equal(new[] { "2 of 8 shown" }, Strings(rendered, "before"));
        Assert.Equal(new[] { "6 of 8 shown" }, Strings(rendered, "after"));
        Assert.Equal(new[] { "5 of 8 shown" }, Strings(rendered, "closed"));
    }

    [Fact]
    public void TheBucketChipsStartOnFailAndWarnAndTurnAnotherBucketOn()
    {
        JsonElement rendered = Render(
            "var before = attrs('#filters .chip[aria-pressed=\"true\"]', 'data-bucket');"
            + "var visibleBefore = attrs('#rules .bucket-group:not([hidden])', 'data-bucket');"
            + "document.querySelector('#filters .chip[data-bucket=\"checked\"]').click();"
            + "var visibleAfter = attrs('#rules .bucket-group:not([hidden])', 'data-bucket');"
            + "return JSON.stringify({ok: true, before: before, visibleBefore: visibleBefore, "
            + "visibleAfter: visibleAfter, chips: attrs('#filters .chip', 'data-bucket')});");

        Assert.Equal(
            new[] { "failed", "warned" },
            rendered.GetProperty("before").EnumerateArray().Select(value => value.GetString()).ToArray());
        Assert.Equal(
            new[] { "failed", "warned" },
            rendered.GetProperty("visibleBefore").EnumerateArray().Select(value => value.GetString()).ToArray());
        Assert.Equal(
            new[] { "failed", "warned", "checked" },
            rendered.GetProperty("visibleAfter").EnumerateArray().Select(value => value.GetString()).ToArray());

        // Every bucket the result carries has a chip, including the ones that start off - the
        // engineer cannot turn on a bucket that was never offered.
        Assert.Equal(
            new[] { "failed", "warned", "checked", "unresolved" },
            rendered.GetProperty("chips").EnumerateArray().Select(value => value.GetString()).ToArray());
    }

    [Fact]
    public void ASubjectWithSeveralInstancesSaysWhichOneShowWillShowAndCyclesOnTheLabel()
    {
        JsonElement rendered = Render(
            "var row = document.querySelector('.rule[data-rule-id=\"rms.detail.holes_last\"]');"
            + "var subject = row.querySelector('.subject');"
            + "var first = subject.querySelector('[data-action=\"show\"]').textContent;"
            + "subject.querySelector('[data-action=\"cycle\"]').click();"
            + "var second = subject.querySelector('[data-action=\"show\"]').textContent;"
            + "var single = document.querySelector('.rule[data-rule-id=\"rms.folders.ordered\"] "
            + "[data-action=\"show\"]').textContent;"
            + "return JSON.stringify({ok: true, first: first, second: second, single: single});");

        Assert.Equal("Show (instance 1 of 2)", rendered.GetProperty("first").GetString());
        Assert.Equal("Show (instance 2 of 2)", rendered.GetProperty("second").GetString());

        // One instance is the ordinary case and says nothing extra.
        Assert.Equal("Show", rendered.GetProperty("single").GetString());
    }

    /// <summary>
    /// A subject whose persistent reference could not be read offers no Show - the host would
    /// refuse it - and says why instead, which is the reason the subject entry carries one.
    /// </summary>
    [Fact]
    public void ASubjectWithNoPersistentReferenceSaysSoInsteadOfOfferingShow()
    {
        JsonElement rendered = Render(
            "var subjects = document.querySelectorAll("
            + "'.rule[data-rule-id=\"rms.detail.holes_last\"] .subject');"
            + "var without = subjects[1];"
            + "return JSON.stringify({ok: true, shows: without.querySelectorAll("
            + "'[data-action=\"show\"]').length, text: without.textContent});");

        Assert.Equal(0, rendered.GetProperty("shows").GetInt32());
        Assert.Contains(
            "the persistent reference could not be read",
            rendered.GetProperty("text").GetString()!);
    }

    [Fact]
    public void AFailRuleCarriesTheAcceptControlWithARequiredNoteAndAWarnRuleCarriesNone()
    {
        JsonElement rendered = Render(
            "var fail = document.querySelector('.rule[data-rule-id=\"rms.detail.holes_last\"]');"
            + "var warn = document.querySelector('.rule[data-rule-id=\"rms.folders.ordered\"]');"
            + "var accept = fail.querySelector('[data-action=\"accept\"]');"
            + "var note = fail.querySelector('input.note');"
            + "return JSON.stringify({ok: true, label: accept.textContent, "
            + "noteRequired: note.required, notePlaceholder: note.getAttribute('placeholder'), "
            + "warnAccepts: warn.querySelectorAll('[data-action=\"accept\"]').length, "
            + "warnNotes: warn.querySelectorAll('input.note').length});");

        // model-check.md section 5: the binding is the rule and the part, and the label says so.
        Assert.Equal("Accept this rule for this part", rendered.GetProperty("label").GetString());
        Assert.True(rendered.GetProperty("noteRequired").GetBoolean(), "The note is not required.");
        Assert.Contains("required", rendered.GetProperty("notePlaceholder").GetString()!);

        // Absent, not disabled: FR-016 makes `warn` rules unacceptable, and a disabled control
        // invites a request to enable it.
        Assert.Equal(0, rendered.GetProperty("warnAccepts").GetInt32());
        Assert.Equal(0, rendered.GetProperty("warnNotes").GetInt32());
    }

    [Fact]
    public void AnAcceptedRuleKeepsItsRowAndNamesTheExceptionAndItsNote()
    {
        JsonElement rendered = Render(
            "return JSON.stringify(describe(document.querySelector("
            + "'.rule[data-rule-id=\"rms.sketch.one_per_feature\"]')));");

        string text = Text(rendered);

        Assert.Contains("EX-001", text);
        Assert.Contains("legacy hole pattern", text);

        // And it is reachable: an exception carried forward from an earlier run renders in the
        // `checked` bucket, which starts closed, so the chip that opens it has to be offered.
        // Filtered behind a chip that names its count is not the same as dropped; a bucket with
        // no chip would be.
        JsonElement chips = Render(
            "return JSON.stringify({ok: true, "
            + "bucket: document.querySelector('.rule[data-rule-id=\"rms.sketch.one_per_feature\"]')"
            + ".getAttribute('data-bucket'), "
            + "chips: attrs('#filters .chip', 'data-bucket')});");

        Assert.Equal("checked", chips.GetProperty("bucket").GetString());
        Assert.Contains("checked", Strings(chips, "chips"));
    }

    /// <summary>
    /// A check that graded more than one document names no single document
    /// (`_checked_document` in `chat/server.py` answers null), and a coverage row's document
    /// ids live in its `scope`. Both together are the case that used to empty the rule list:
    /// the page read `item.document_ids`, which is never there, and fell back to a document
    /// that is null - so every skipped, unresolved and out-of-scope rule vanished while the
    /// grade header went on counting them. Silence is not coverage.
    /// </summary>
    [Fact]
    public void EveryCoverageRowStillReachesTheDomWhenTheCheckNamesNoSingleDocument()
    {
        JsonElement rendered = RenderMutated(
            "result.document = null;",
            "return JSON.stringify({ok: true, rules: attrs('#rules .rule', 'data-rule-id'), "
            + "documents: attrs('#rules .document-group', 'data-document-id')});");

        string[] rules = Strings(rendered, "rules");

        foreach (string rule in new[]
        {
            "rms.folders.present", "rms.grouping", "modeling.resilience",
            "rms.refs.direction", "rms.sketch.fully_defined",
        })
        {
            Assert.Contains(rule, rules);
        }

        // Grouped by the document the coverage item itself names, which is what makes a
        // multi-document check readable rather than one undifferentiated list.
        Assert.Equal(new[] { "doc:ab12" }, Strings(rendered, "documents"));
    }

    /// <summary>
    /// A row that ends up naming no document is rendered under a section that says so. The
    /// alternative - dropping it - is the silence the constitution forbids, and it is
    /// indistinguishable to the engineer from a rule that was never run.
    /// </summary>
    [Fact]
    public void ARowThatNamesNoDocumentIsRenderedUnderAnUngroupedSectionRatherThanDropped()
    {
        JsonElement rendered = RenderMutated(
            "result.document = null; result.coverage[0].scope.document_ids = [];",
            "return JSON.stringify({ok: true, "
            + "ungrouped: texts('#rules .document-group.ungrouped .rule .rule-id'), "
            + "heading: texts('#rules .document-group.ungrouped .document-name'), "
            + "grouped: attrs('#rules .document-group:not(.ungrouped) .rule', 'data-rule-id')});");

        Assert.Equal(new[] { "rms.folders.present" }, Strings(rendered, "ungrouped"));
        Assert.DoesNotContain("rms.folders.present", Strings(rendered, "grouped"));
        Assert.Single(Strings(rendered, "heading"));
    }

    // ---- what was never read (feature: resolve-lightweight) --------------------------------------

    /// <summary>
    /// A body carrying `not_examined` prints its sentence, unhidden, above the ranked rows -
    /// the first thing under the header block, so an engineer reads it before the buckets
    /// (docs/feature-request-resolve-lightweight.md).
    /// </summary>
    [Fact]
    public void ANotExaminedResultPrintsItsSentenceUnhiddenAboveTheRankedRows()
    {
        JsonElement rendered = RenderMutated(
            "result.not_examined = " + NotExaminedSample.Json() + ";",
            "var node = document.getElementById('not-examined');"
            + "var attention = document.getElementById('attention');"
            + "return JSON.stringify({ok: true, "
            + "text: node.textContent, "
            + "hidden: !!node.hidden, "
            + "before: !!(node.compareDocumentPosition(attention) "
            + "& Node.DOCUMENT_POSITION_FOLLOWING)});");

        Assert.Equal(NotExaminedSample.Sentence, rendered.GetProperty("text").GetString());
        Assert.False(rendered.GetProperty("hidden").GetBoolean(), "#not-examined stayed hidden.");
        Assert.True(
            rendered.GetProperty("before").GetBoolean(),
            "#not-examined must come before #attention in the document.");
    }

    /// <summary>`null` means every instance was read, so the block says nothing and stays hidden.</summary>
    [Fact]
    public void ANotExaminedKeyOfNullLeavesTheBlockHiddenAndEmpty()
    {
        JsonElement rendered = RenderMutated(
            "result.not_examined = null;",
            "var node = document.getElementById('not-examined');"
            + "return JSON.stringify({ok: true, text: node.textContent, hidden: !!node.hidden});");

        Assert.Equal(string.Empty, rendered.GetProperty("text").GetString());
        Assert.True(rendered.GetProperty("hidden").GetBoolean());
    }

    /// <summary>
    /// A body from before this feature carries no `not_examined` key at all, which reads the
    /// same as `null`: nothing is said and the block stays hidden.
    /// </summary>
    [Fact]
    public void ABodyWithNoNotExaminedKeyLeavesTheBlockHiddenAndEmpty()
    {
        JsonElement rendered = RenderMutated(
            "delete result.not_examined;",
            "var node = document.getElementById('not-examined');"
            + "return JSON.stringify({ok: true, text: node.textContent, hidden: !!node.hidden});");

        Assert.Equal(string.Empty, rendered.GetProperty("text").GetString());
        Assert.True(rendered.GetProperty("hidden").GetBoolean());
    }

    /// <summary>
    /// The sentence is untrusted the same way an `observed` string is - it is assembled out of
    /// component names, and a component in a supplied model may have been renamed by anyone who
    /// has ever been able to open it - so it reaches the screen as characters, never as markup.
    /// </summary>
    [Fact]
    public void AHostileNotExaminedSentenceRendersAsLiteralTextWithNothingInjected()
    {
        JsonElement rendered = RenderMutated(
            "result.not_examined = "
                + NotExaminedSample.Json(CheckResultSample.HostileNotExaminedSentence) + ";",
            "return JSON.stringify(describe(document.getElementById('not-examined')));");

        string text = Text(rendered);
        Assert.Contains(CheckResultSample.HostileNotExaminedSentence, text);
        Assert.Equal(0, rendered.GetProperty("injected").GetInt32());
        Assert.Equal(0, rendered.GetProperty("handlers").GetInt32());
        Assert.DoesNotContain("<img", rendered.GetProperty("html").GetString()!);
    }

    // ---- what happens when the engineer accepts a rule -----------------------------------------

    /// <summary>
    /// Accept, driven end to end against a stubbed backend: the rule the engineer just accepted
    /// stays on screen as `checked`, the grade moves with it, and the exception id is named.
    ///
    /// Each of those was broken in a different way. The page re-rendered from the result it
    /// already had, so the grade header kept the pre-accept counts while the row read as
    /// checked; and `checked` is a bucket that starts off, so the row was re-rendered into a
    /// group with `hidden` set - the rule disappeared as it was accepted, which
    /// `contracts/model-check.md` section 5 forbids outright ("Never hidden, per Principle VI").
    ///
    /// `window.fetch` is the stub rather than a listening server: the route's behaviour is
    /// tested in Python, and what is under test here is what the page does with the answer.
    /// </summary>
    [Fact]
    public void AcceptingARuleKeepsItVisibleAsCheckedAndMovesTheGradeAndNamesTheException()
    {
        JsonElement state = DriveAccept();

        Assert.Equal("checked", state.GetProperty("bucket").GetString());
        Assert.False(
            state.GetProperty("hidden").GetBoolean(),
            "The rule the engineer just accepted was re-rendered into a hidden bucket group, so "
                + "it disappeared as they accepted it (contracts/model-check.md section 5).");

        // The route re-ran the rules before it answered; the page shows that run's grade rather
        // than the one it was holding, so the headline number and the list agree.
        string grade = state.GetProperty("grade").GetString()!;
        Assert.Contains("1 failed", grade);
        Assert.Contains("4 checked", grade);

        Assert.Contains("EX-009", state.GetProperty("said").GetString()!);
        Assert.Contains("EX-009", state.GetProperty("exception").GetString()!);

        // The accept, then the re-read: the page asks the backend what the result is now rather
        // than deciding it (there is one evaluation entry point, FR-024).
        Assert.Equal(
            new[]
            {
                "POST /checks/20260916-101532-bracket-check/exceptions/F-001",
                "GET /checks/20260916-101532-bracket-check",
            },
            state.GetProperty("calls").EnumerateArray().Select(value => value.GetString()).ToArray());
    }

    /// <summary>
    /// The tab can be opened while the backend is still starting, in which case its `init`
    /// carries no endpoint and every `POST /checks/rms` would be refused for the life of the
    /// page. The Review page already re-asks on `status {stage: "ready"}` (`app.js`); this is
    /// the same guard on this page, and the guard on `state.backend` is what keeps the host's
    /// own end-of-extraction `ready` from re-initialising the page in the middle of a check.
    /// </summary>
    [Fact]
    public void ABackendThatStartsAfterThePageDidIsPickedUpFromTheNextReadyStatus()
    {
        HostStub? stub = null;
        string backendState = string.Empty;

        OffscreenReviewPage.WithPage(
            ModelCheckPageFiles.PageUrl,
            page => { stub = new HostStub(page, backendAtFirstReady: false); },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);

                // The backend finished starting after this page was given its `init`.
                stub!.Post("status", new { stage = "ready", message = "Backend ready." });
                await OffscreenReviewPage.Settled(page);

                // And again with the endpoint already in hand: this is the host's own
                // end-of-extraction `ready`, and it must not re-initialise the page mid-check.
                stub!.Post(
                    "status", new { stage = "ready", message = "Extracted. Checking the model..." });
                await OffscreenReviewPage.Settled(page);

                backendState = await ReadText(page, "backend-state");
            });

        // Two `ready` messages: the one the page posts on load, and the one the guard posts
        // when the host says the backend is up. A third would mean the guard re-fires on every
        // status, which is what the `state.backend` guard is there to prevent.
        Assert.Equal(2, stub!.Readies);
        Assert.Equal("Backend ready", backendState);
    }

    // ---- rendering ---------------------------------------------------------------------------

    private static JsonElement Render(string body) =>
        OffscreenModelCheckPage.Evaluate("check(" + CheckResultSample.Json() + ");" + body);

    /// <summary>Renders the sample after <paramref name="mutate"/> has changed it.</summary>
    private static JsonElement RenderMutated(string mutate, string body) =>
        OffscreenModelCheckPage.Evaluate(
            "var result = " + CheckResultSample.Json() + ";" + mutate + "check(result);" + body);

    private static string[] Strings(JsonElement rendered, string name) =>
        rendered.GetProperty(name).EnumerateArray().Select(value => value.GetString()!).ToArray();

    // ---- driving the real page ------------------------------------------------------------------

    /// <summary>
    /// Loads the page with a host that answers `ready`, renders the sample against a stubbed
    /// `window.fetch`, presses Accept, and reports what the page looks like afterwards.
    /// </summary>
    private static JsonElement DriveAccept()
    {
        string? raw = null;

        OffscreenReviewPage.WithPage(
            ModelCheckPageFiles.PageUrl,
            page => { _ = new HostStub(page, backendAtFirstReady: true); },
            async page =>
            {
                await OffscreenReviewPage.Settled(page);
                await page.ExecuteScriptAsync(AcceptStub);
                await OffscreenReviewPage.Settled(page);
                await page.ExecuteScriptAsync(AcceptPress);
                await OffscreenReviewPage.Settled(page);
                raw = await page.ExecuteScriptAsync(AcceptRead);
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
                : "the page did not render");
        return state;
    }

    private static async Task<string> ReadText(CoreWebView2 page, string elementId)
    {
        string raw = await page.ExecuteScriptAsync(
            "document.getElementById('" + elementId + "').textContent");
        return JsonDocument.Parse(raw).RootElement.GetString() ?? string.Empty;
    }

    /// <summary>
    /// Stubs the backend and renders the sample.
    ///
    /// `accepted` is what `GET /checks/{check_id}` answers once the exception is written: the
    /// route re-ran the rules before it replied to the `POST`, so the finding is
    /// `checked_within_scope` carrying its exception and the grade has moved with it. That is
    /// the whole reason the page re-reads rather than patching the result it holds.
    /// </summary>
    private static readonly string AcceptStub = @"
(function () {
  var sample = " + CheckResultSample.Json() + @";
  var accepted = JSON.parse(JSON.stringify(sample));
  var row = accepted.findings[0];
  row.finding.status = 'checked_within_scope';
  row.exception = {id: 'EX-009', state: 'active', note: 'legacy hole pattern, drawing 4471 rev B'};
  accepted.grade.failed = 1;
  accepted.grade.checked = 4;

  window.__calls = [];
  window.fetch = function (url, request) {
    window.__calls.push(request.method + ' ' + String(url).replace('https://swreview.invalid/__backend', ''));
    var body = (request.method === 'POST') ? {finding: row, exception_id: 'EX-009'} : accepted;
    return Promise.resolve({
      ok: true,
      status: 200,
      text: function () { return Promise.resolve(JSON.stringify(body)); }
    });
  };

  window.SwReviewCheck.renderResult(sample);
}());
";

    private const string AcceptPress = @"
(function () {
  var row = document.querySelector('.rule[data-rule-id=""rms.detail.holes_last""]');
  row.querySelector('input.note').value = 'legacy hole pattern, drawing 4471 rev B';
  row.querySelector('[data-action=""accept""]').click();
}());
";

    private const string AcceptRead = @"
(function () {
  function acceptedRow() {
    return document.querySelector('.rule[data-rule-id=""rms.detail.holes_last""]');
  }

  function acceptedGroup() {
    var node = acceptedRow();
    while (node && !(node.classList && node.classList.contains('bucket-group'))) {
      node = node.parentNode;
    }
    return node;
  }

  try {
    return JSON.stringify({
      ok: true,
      bucket: acceptedRow() ? acceptedRow().getAttribute('data-bucket') : null,
      hidden: !!(acceptedGroup() && acceptedGroup().hidden),
      grade: document.getElementById('grade').textContent,
      said: document.getElementById('check-state').textContent,
      exception: acceptedRow() ? acceptedRow().textContent : '',
      calls: window.__calls
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}());
";

    /// <summary>
    /// The host end of the bridge for the driven tests: it answers `ready` with the `init`
    /// <c>ModelCheckHost.SendInit</c> sends, and counts how many times it was asked.
    ///
    /// <paramref name="backendAtFirstReady"/> false is the state the pane is really in while
    /// the backend is starting: the first `init` carries no endpoint and no token, and every
    /// later one does.
    /// </summary>
    private sealed class HostStub
    {
        private readonly CoreWebView2 _page;
        private readonly bool _backendAtFirstReady;

        public HostStub(CoreWebView2 page, bool backendAtFirstReady)
        {
            _page = page;
            _backendAtFirstReady = backendAtFirstReady;
            page.WebMessageReceived += OnMessage;
        }

        /// <summary>How many `ready` messages the page has posted.</summary>
        public int Readies { get; private set; }

        /// <summary>Posts an unsolicited message, which carries no `id`.</summary>
        public void Post(string type, object payload) =>
            _page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, payload }));

        private void OnMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
        {
            JsonElement message = JsonDocument.Parse(args.WebMessageAsJson).RootElement;
            if (message.GetProperty("type").GetString() != "ready")
            {
                return;
            }

            Readies++;
            bool withBackend = _backendAtFirstReady || Readies > 1;
            _page.PostWebMessageAsJson(JsonSerializer.Serialize(new
            {
                type = "init",
                id = message.GetProperty("id").GetString(),
                payload = new
                {
                    backend = withBackend
                        ? (object?)new { port = 51234, origin = "https://swreview.invalid/__backend" }
                        : null,
                    token = withBackend ? "0FAKEtoken" : null,
                    run_root = @"C:\SwReviewRuns",
                    document = new
                    {
                        path = @"C:\vault\bracket.sldprt",
                        configuration = "Default",
                        kind = "part",
                    },
                    latest_check = (object?)null,
                },
            }));
        }
    }

    private static string Text(JsonElement rendered)
    {
        Assert.True(
            rendered.GetProperty("ok").GetBoolean(),
            rendered.TryGetProperty("error", out JsonElement error)
                ? error.GetString()
                : "the page did not render");
        return rendered.GetProperty("text").GetString()!;
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

    /// <summary>A token spliced into a path or a query string, in the shapes that hide it.</summary>
    private static readonly Regex TokenInUrl = new Regex(
        @"[?&]\s*(access_)?token\s*=|['""][^'""]*/[^'""]*['""]\s*\+\s*[A-Za-z_.]*token",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex BlockComment = new Regex(
        @"/\*.*?\*/", RegexOptions.Singleline | RegexOptions.Compiled);

    private static readonly Regex WholeLineComment = new Regex(
        @"^[ \t]*//.*$", RegexOptions.Multiline | RegexOptions.Compiled);

    /// <summary>
    /// Extensions a dotted literal is allowed to end in: `'check.js'` and `'report.md'` are
    /// file names, not message types.
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

    // ---- the contract itself --------------------------------------------------------------------

    /// <summary>
    /// Sections 2 and 3 of `contracts/model-check.md`, read as data so a contract change lands
    /// here rather than in a hand-kept list that drifts.
    /// </summary>
    private sealed class ModelCheckContract
    {
        private ModelCheckContract(ISet<string> pageToHost, ISet<string> hostToPage)
        {
            PageToHost = pageToHost;
            HostToPage = hostToPage;
        }

        /// <summary>The `type` column of "Model check page to host".</summary>
        public ISet<string> PageToHost { get; }

        /// <summary>
        /// The unsolicited table, plus every type named as a reply in the host-action column
        /// (`init`, `check.extracted`, `entity.shown`, `status`, `error`). Replies are matched
        /// by `id` rather than by type, so they are read out of the prose that defines them.
        /// </summary>
        public ISet<string> HostToPage { get; }

        public static ModelCheckContract Load()
        {
            var pageToHost = new HashSet<string>(StringComparer.Ordinal);
            var hostToPage = new HashSet<string>(StringComparer.Ordinal);

            string? section = null;
            foreach (string raw in ReviewPageFiles.ReadContract("model-check.md").Split('\n'))
            {
                string line = raw.TrimEnd('\r');
                if (line.StartsWith("## ", StringComparison.Ordinal))
                {
                    section = line.Substring(3).Trim();
                    continue;
                }

                Match row = TableRow.Match(line);
                if (!row.Success || section == null)
                {
                    continue;
                }

                string type = row.Groups[1].Value;
                if (section.IndexOf("page to host", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    pageToHost.Add(type);
                    foreach (string reply in BacktickedTypes(row.Groups[2].Value))
                    {
                        hostToPage.Add(reply);
                    }
                }
                else if (section.IndexOf("Host to Model check page", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    hostToPage.Add(type);
                }
            }

            // A parser that quietly matched nothing would make every test above vacuous.
            Assert.True(
                pageToHost.Count == 6 && hostToPage.Count >= 6,
                $"contracts/model-check.md did not parse: {pageToHost.Count} page-to-host rows, "
                    + $"{hostToPage.Count} host-to-page types. Did the table or heading shape change?");

            return new ModelCheckContract(pageToHost, hostToPage);
        }

        private static readonly Regex TableRow = new Regex(
            @"^\|\s*`([a-z][a-z0-9_.]*)`\s*\|(.*)$", RegexOptions.Compiled);

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
/// One `CheckResult` (`contracts/model-check.md` section 1) for the page tests to render.
///
/// It is written out as a literal rather than produced by running the Python rule layer: these
/// tests are about what the page does with the shape, the contract is what both sides agree on,
/// and a fixture generated by one side would only prove that side consistent with itself. The
/// values are chosen so every branch the page has is reachable - four buckets, a `fail` rule
/// and a `warn` rule, a subject with two instances and one with one, an accepted rule, and a
/// subject whose persistent reference could not be read.
/// </summary>
internal static class CheckResultSample
{
    /// <summary>A feature name as SOLIDWORKS hands it over when someone types it in.</summary>
    public const string HostileFeatureName = "<img src=x onerror=\"alert(1)\"></script>";

    /// <summary>An observed string, which is assembled out of the model's own names.</summary>
    public const string HostileObserved =
        "</script><script>alert(2)</script><img src=x onerror=alert(3)>";

    /// <summary>A `not_examined.sentence`, hostile the same way a feature name can be.</summary>
    public const string HostileNotExaminedSentence = "<img src=x onerror=alert(1)>";

    /// <summary>The two unresolved rules' statements, from `rule_statements` (feature 009 FR-028).</summary>
    public const string RefsDirectionStatement = "Reference geometry follows the method's axes and planes.";

    public const string SketchFullyDefinedStatement = "Every sketch is fully defined.";

    public static string Json(string featureName = "Cut-Extrude1", string? observed = null) =>
        JsonSerializer.Serialize(
            Build(featureName, observed ?? "2 holes are not the last features in 4-Detail"));

    private static object Build(string featureName, string observed) => new
    {
        check_id = "20260916-101532-bracket-check",
        run_dir = @"C:\SwReviewRuns\20260916-101532-bracket-check",
        document = new
        {
            id = "doc:ab12",
            path = @"C:\vault\bracket.sldprt",
            configuration = "Default",
            kind = "part",
        },
        extracted_at = "2026-09-16T10:15:32Z",
        profile = "model_check",
        grade = new
        {
            failed = 2,
            warned = 1,

            // `checked` is a C# keyword and the contract's field name; the escape is the
            // identifier, and the serialized property is still `checked`.
            @checked = 3,
            skipped = 0,
            unresolved = 2,
            out_of_scope = 0,
            fraction = 0.5,
            unresolved_rule_ids = new[] { "rms.refs.direction", "rms.sketch.fully_defined" },
        },
        findings = new object[]
        {
            new
            {
                finding = Finding(
                    "F-001", "rms.detail.holes_last", observed, new[] { "cmp:0003", "cmp:0009" }, null),
                rule_id = "rms.detail.holes_last",
                severity = "fail",
                statement = "Holes are the last features in the Detail group.",
                observed,
                acceptable = true,
            },
            new
            {
                finding = Finding(
                    "F-002", "rms.folders.ordered", "3-Core follows 4-Detail", new[] { "cmp:0003" }, null),
                rule_id = "rms.folders.ordered",
                severity = "warn",
                statement = "The group folders are in the method's order.",
                observed = "3-Core follows 4-Detail",
                acceptable = false,
            },
            new
            {
                finding = Finding(
                    "F-003",
                    "rms.sketch.one_per_feature",
                    "Sketch3 feeds two features",
                    new[] { "cmp:0003" },
                    "EX-001"),
                rule_id = "rms.sketch.one_per_feature",
                severity = "fail",
                statement = "Each sketch is consumed by one feature.",
                observed = "Sketch3 feeds two features",
                acceptable = true,
                exception = new
                {
                    id = "EX-001",
                    state = "active",
                    note = "legacy hole pattern, drawing 4471 rev B",
                },
            },
        },
        coverage = new object[]
        {
            Coverage("checked", "rms.folders.present", "all six group folders are present"),
            Coverage("checked", "rms.grouping", "every content feature is in a group"),
            Coverage("checked", "modeling.resilience", "3 of 6 rules checked"),
            Coverage(
                "unresolved",
                "rms.refs.direction",
                "reference directions are not in the evidence package"),
            Coverage("unresolved", "rms.sketch.fully_defined", "sketch status is unavailable"),
        },
        subjects = new Dictionary<string, object[]>
        {
            {
                "F-001",
                new object[]
                {
                    new
                    {
                        feature_id = "feat:0007",
                        name = featureName,
                        type_name = "ICE",
                        group = "4-Detail",
                        persist_ref = "YmFzZTY0",
                        persist_ref_scope = "doc:ab12",
                        component_ids = new[] { "cmp:0003", "cmp:0009" },
                    },
                    new
                    {
                        feature_id = "feat:0011",
                        name = "Sketch4",
                        type_name = "ProfileFeature",
                        group = "4-Detail",
                        persist_ref = (string?)null,
                        persist_ref_scope = "doc:ab12",
                        component_ids = new[] { "cmp:0003" },
                        reason = "the persistent reference could not be read",
                    },
                }
            },
            {
                "F-002",
                new object[]
                {
                    new
                    {
                        feature_id = "feat:0002",
                        name = "3-Core",
                        type_name = "FtrFolder",
                        group = "3-Core",
                        persist_ref = "Zm9sZGVy",
                        persist_ref_scope = "doc:ab12",
                        component_ids = new[] { "cmp:0003" },
                    },
                }
            },
            {
                "F-003",
                new object[]
                {
                    new
                    {
                        feature_id = "feat:0005",
                        name = "Sketch3",
                        type_name = "ProfileFeature",
                        group = "4-Detail",
                        persist_ref = "c2tldGNo",
                        persist_ref_scope = "doc:ab12",
                        component_ids = new[] { "cmp:0003" },
                    },
                }
            },
        },
        exceptions_carried_forward = new
        {
            from_run = "20260915-173001-bracket-check",
            count = 1,
            reason = (string?)null,
        },

        // Feature 009 T064: the `RULES` statement of every rule the grade names, findings and
        // coverage rows alike; `modeling.resilience` is a checklist item, not a rule, so the
        // catalogue has no statement for it and the map leaves it out.
        rule_statements = new Dictionary<string, string>
        {
            { "rms.detail.holes_last", "Holes are the last features in the Detail group." },
            { "rms.folders.ordered", "The group folders are in the method's order." },
            { "rms.sketch.one_per_feature", "Each sketch is consumed by one feature." },
            { "rms.folders.present", "All six group folders are present." },
            { "rms.grouping", "Every content feature is in a group." },
            { "rms.refs.direction", RefsDirectionStatement },
            { "rms.sketch.fully_defined", SketchFullyDefinedStatement },
        },

        // The ranking the backend computed for this run, carried on the body so the tab renders
        // it without a second call (contracts/attention.md section 5). It is one shape on every
        // surface, so it is one fixture: <see cref="AttentionSample"/>.
        attention = AttentionSample.Ranking(),
    };

    /// <summary>
    /// One coverage item as `coverage_rows` in `checks/rms/run.py` emits it: the bucket, and
    /// then the `CoverageItem` itself, whose scope is where the document ids live.
    ///
    /// The nesting is the point. A row that carried `document_ids` at the top level - which is
    /// what this fixture asserted before - would let the page read a field the backend has
    /// never sent and group every coverage row under nothing.
    /// </summary>
    private static object Coverage(
        string bucket, string check, string reason, string? documentId = "doc:ab12") => new
    {
        bucket,
        check,
        scope = new
        {
            component_ids = new[] { "cmp:0003" },
            pairs = new object[0],
            configuration = "Default",
            positions = new string[0],
            document_ids = documentId == null ? new string[0] : new[] { documentId },
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
        configuration = "Default",
        observed,
        requirement = "Resilient Modeling Strategy",
        inputs = new[] { "feat:0007 ICE 4-Detail" },
        calculation = (object?)null,
        tool_result_ids = new[] { 1 },
        coverage_limits = new string[0],
        recommended_action = "Move the holes to the end of 4-Detail.",
        group = (object?)null,
        capture_ids = new string[0],
        disposition = (object?)null,
        exception_id = exceptionId,
    };
}
