using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T066: the card vocabulary comes from the backend's labels (FR-024, FR-030,
/// contracts/plain-words.md section 1).
///
/// A finding card said `checked_within_scope`, the coverage fold said `out_of_scope` spelled with
/// spaces by a page-side regex, and every one of those words was a token of the code rather than a
/// word of the engineer's. The words are the backend's now - `GET /labels`, the words file's
/// `labels` block, fetched after every `init` that names a backend - and the page looks each token
/// up and prints what it finds. A token the labels do not name, an older backend that answers 404,
/// and a token that happens to name something on `Object.prototype` all print exactly what the
/// page printed before this feature.
/// </summary>
public sealed class ReviewPageLabelsTests
{
    private static readonly Lazy<Run> Labelled = new Lazy<Run>(() => Drive(withLabels: true));

    private static readonly Lazy<Run> Unlabelled = new Lazy<Run>(() => Drive(withLabels: false));

    /// <summary>The labels are read after `init` names a backend, and again after the re-init a settings save causes.</summary>
    [Fact]
    public void ThePageReadsTheLabelsAfterInitAndAgainAfterASettingsSave()
    {
        Assert.Equal(1, Labelled.Value.LabelReadsAfterInit);
        Assert.Equal(2, Labelled.Value.LabelReadsAfterSave);
    }

    [Fact]
    public void AFindingsChipsPrintTheStatusAndSeverityLabels()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal(new[] { "checked within scope", "medium severity" }, ReviewPageDriver.Strings(read, "withinChips"));

        // The class names still carry the token: the hue is the stylesheet's, and it reads the class.
        Assert.Equal(new[] { "chip status-checked_within_scope", "chip sev-medium" }, ReviewPageDriver.Strings(read, "withinClasses"));
    }

    [Fact]
    public void TheCoverageFoldNamesItsBucketsInTheBackendsWords()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal("1 evidence missing · 1 out of scope", read.GetProperty("coverageCounts").GetString());
        Assert.Equal(new[] { "evidence missing · 1", "out of scope · 1" }, ReviewPageDriver.Strings(read, "bucketNames"));
    }

    [Fact]
    public void TheEvidenceRecordsChipPrintsItsLabelAsLiteralText()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal(LabelsSample.HostileOpen, read.GetProperty("evidenceChip").GetString());
        Assert.Equal(0, read.GetProperty("injected").GetInt32());
    }

    /// <summary>
    /// Feature 013 T103 (contracts/sources.md section 2): a finding's line carries the backend's word
    /// for who wrote it - `labels.source` looked up by the body's `source`, never compared - after
    /// its status and severity; a body that states no source gets no chip.
    /// </summary>
    [Fact]
    public void AFindingsLineCarriesItsSourceWordWhenItsBodyStatesOne()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal(new[] { "demonstrated", "medium severity", LabelsSample.SourceModel }, ReviewPageDriver.Strings(read, "modelChips"));
        Assert.Equal("chip source-chip source-model", ReviewPageDriver.Strings(read, "modelClasses")[2]);
        Assert.Equal(new[] { "demonstrated", "medium severity", LabelsSample.SourceCode }, ReviewPageDriver.Strings(read, "codeChips"));
        Assert.Equal(2, ReviewPageDriver.Strings(read, "withinChips").Length);
    }

    /// <summary>
    /// The evidence record's head is its lifecycle chip and its source word: the one fixed title
    /// "The review needs an input" is gone, because a code question and a model question are not
    /// the same claim.
    /// </summary>
    [Fact]
    public void TheEvidenceRecordsHeadCarriesItsSourceWordAndNoFixedTitle()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal(new[] { LabelsSample.HostileOpen, LabelsSample.SourceCode }, ReviewPageDriver.Strings(read, "evidenceHead"));
        Assert.DoesNotContain("The review needs an input", read.GetProperty("evidenceText").GetString()!);
    }

    /// <summary>
    /// A coverage row and a goal's recorded sentence say who wrote them only when the body carries
    /// a source - the backend sends it only for the model's (sources.md section 1) - and say
    /// nothing otherwise.
    /// </summary>
    [Fact]
    public void ACoverageRowAndAGoalsSentenceStateTheirSourceOnlyWhenTheBodyCarriesOne()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal(new[] { LabelsSample.SourceModel }, ReviewPageDriver.Strings(read, "coverageChips"));
        Assert.Contains("interfaces.fit - no limits" + LabelsSample.SourceModel, ReviewPageDriver.Strings(read, "coverageLines"));
        Assert.Equal(new[] { LabelsSample.SourceModel }, ReviewPageDriver.Strings(read, "modelDetailChips"));
        Assert.Empty(ReviewPageDriver.Strings(read, "codeDetailChips"));
    }

    /// <summary>A token that names something on `Object.prototype` is printed as itself, not as whatever the prototype holds.</summary>
    [Fact]
    public void ATokenNamingSomethingOnTheObjectPrototypePrintsAsItself()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal(new[] { "toString", "__proto__" }, ReviewPageDriver.Strings(read, "oddChips"));
    }

    /// <summary>
    /// FR-030: an older backend answers `/labels` with 404, and every surface prints exactly what
    /// it printed before this feature - the raw tokens, and the coverage fold's own spacing.
    /// </summary>
    [Fact]
    public void WithNoLabelsEverySurfacePrintsWhatItPrintedBefore()
    {
        JsonElement read = Unlabelled.Value.Read;

        Assert.Equal(new[] { "checked_within_scope", "medium" }, ReviewPageDriver.Strings(read, "withinChips"));
        Assert.Equal("1 unresolved · 1 out of scope", read.GetProperty("coverageCounts").GetString());
        Assert.Equal("open", read.GetProperty("evidenceChip").GetString());

        // Feature 013 T103: no labels, no source word anywhere - the page has none of its own.
        Assert.Equal(new[] { "demonstrated", "medium" }, ReviewPageDriver.Strings(read, "modelChips"));
        Assert.Equal(new[] { "open" }, ReviewPageDriver.Strings(read, "evidenceHead"));
        Assert.Empty(ReviewPageDriver.Strings(read, "coverageChips"));
        Assert.Empty(ReviewPageDriver.Strings(read, "modelDetailChips"));
        Assert.Equal(new[] { "toString", "__proto__" }, ReviewPageDriver.Strings(read, "oddChips"));
    }

    private static Run Drive(bool withLabels)
    {
        var run = new Run();

        ReviewPageDriver.Run(
            driver =>
            {
                if (withLabels)
                {
                    driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
                }
            },
            async driver =>
            {
                run.LabelReadsAfterInit = LabelReads(await driver.Calls());

                await driver.RouteAttention("chat-1", SummarySample.Json());
                await driver.StartReview();
                await driver.Push("chat-1", 1, "finding", Finding("F-001", "checked_within_scope", "medium"));
                await driver.Push("chat-1", 2, "finding", Finding("F-002", "toString", "__proto__"));
                await driver.Push("chat-1", 3, "evidence.requested",
                    @"{""id"":""ER-001"",""what"":""Which fit?"",""why"":""The limits decide it."",""entity_ids"":[""cmp:0002""],""status"":""open"",""source"":""code""}");
                await driver.Push("chat-1", 4, "coverage", @"{""bucket"":""out_of_scope"",""item"":{""check"":""drawing.rule"",""reason"":""no drawing""}}");
                await driver.Push("chat-1", 5, "coverage", @"{""bucket"":""unresolved"",""item"":{""check"":""interfaces.fit"",""reason"":""no limits"",""source"":""model""}}");
                await driver.Push("chat-1", 6, "finding", Finding("F-003", "demonstrated", "medium", "model"));
                await driver.Push("chat-1", 7, "finding", Finding("F-004", "demonstrated", "medium", "code"));
                await driver.EndSession("chat-1");
                run.Read = await driver.Read(ReadCards);

                await driver.Click("save-settings");
                await driver.Settle();
                run.LabelReadsAfterSave = LabelReads(await driver.Calls());
            });

        return run;
    }

    private static int LabelReads(JsonElement[] calls) =>
        calls.Count(call => call.GetProperty("method").GetString() == "GET" && call.GetProperty("path").GetString() == "/labels");

    /// <summary>A finding body; `source` is stated only when given, as a body from before feature 013 states none.</summary>
    private static string Finding(string id, string status, string severity, string? source = null)
    {
        var body = new Dictionary<string, object>
        {
            { "id", id },
            { "check", "interference.static" },
            { "title", "Finding " + id },
            { "status", status },
            { "severity", severity },
            { "component_ids", new[] { "cmp:0002" } },
            { "observed", "Observed for " + id + "." },
        };
        if (source != null)
        {
            body["source"] = source;
        }

        return JsonSerializer.Serialize(body);
    }

    private const string ReadCards = @"
var within = document.querySelector('.card.finding[data-finding-id=""F-001""] .card-line');
var odd = document.querySelector('.card.finding[data-finding-id=""F-002""] .card-line');
var evidence = document.querySelector('.card.evidence .evidence-status');
var model = document.querySelector('.card.finding[data-finding-id=""F-003""] .card-line');
var code = document.querySelector('.card.finding[data-finding-id=""F-004""] .card-line');
var goalOf = function (title) {
  var goals = document.querySelectorAll('#findings-by-type .summary-goal');
  for (var i = 0; i < goals.length; i++) { if (h.text(goals[i], '.goal-title') === title) { return goals[i]; } }
  return null;
};
return JSON.stringify({
  ok: true,
  modelChips: h.texts(model, '.chip'),
  modelClasses: h.attrs(model, '.chip', 'class'),
  codeChips: h.texts(code, '.chip'),
  evidenceHead: h.texts(document.querySelector('.card.evidence .card-head'), '.chip'),
  evidenceText: document.querySelector('.card.evidence').textContent,
  coverageChips: h.texts(document.getElementById('coverage-panel'), '.bucket-item .source-chip'),
  coverageLines: h.texts(document.getElementById('coverage-panel'), '.bucket-item'),
  modelDetailChips: h.texts(goalOf('" + GroupsSample.ModelDetailGoal + @"'), '.goal-detail .source-chip'),
  codeDetailChips: h.texts(goalOf('" + GroupsSample.CodeDetailGoal + @"'), '.goal-detail .source-chip'),
  withinChips: h.texts(within, '.chip'),
  withinClasses: h.attrs(within, '.chip', 'class'),
  oddChips: h.texts(odd, '.chip'),
  coverageCounts: h.text(document.getElementById('coverage-panel'), 'summary .fold-count'),
  bucketNames: h.texts(document.getElementById('coverage-panel'), '.bucket-name'),
  evidenceChip: evidence ? evidence.textContent : null,
  injected: h.injected(document.querySelector('.card.evidence'))
});";

    private sealed class Run
    {
        public int LabelReadsAfterInit { get; set; }

        public int LabelReadsAfterSave { get; set; }

        public JsonElement Read { get; set; }
    }
}
