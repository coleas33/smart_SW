using System;
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

    /// <summary>The Review tab's Start-here meta prints the labels; the check tabs are handed none and print the raw words.</summary>
    [Fact]
    public void TheReviewTabsStartHereMetaPrintsTheLabels()
    {
        JsonElement read = Labelled.Value.Read;

        Assert.Equal("demonstrated · medium severity · Pin-A-1, Plate-1", ReviewPageDriver.Strings(read, "metas")[0]);
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
        Assert.Equal("demonstrated · medium · Pin-A-1, Plate-1", ReviewPageDriver.Strings(read, "metas")[0]);
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
                    @"{""id"":""ER-001"",""what"":""Which fit?"",""why"":""The limits decide it."",""entity_ids"":[""cmp:0002""],""status"":""open""}");
                await driver.Push("chat-1", 4, "coverage", @"{""bucket"":""out_of_scope"",""item"":{""check"":""drawing.rule"",""reason"":""no drawing""}}");
                await driver.Push("chat-1", 5, "coverage", @"{""bucket"":""unresolved"",""item"":{""check"":""interfaces.fit"",""reason"":""no limits""}}");
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

    private static string Finding(string id, string status, string severity) => JsonSerializer.Serialize(new
    {
        id,
        check = "interference.static",
        title = "Finding " + id,
        status,
        severity,
        component_ids = new[] { "cmp:0002" },
        observed = "Observed for " + id + ".",
    });

    private const string ReadCards = @"
var within = document.querySelector('.card.finding[data-finding-id=""F-001""] .card-line');
var odd = document.querySelector('.card.finding[data-finding-id=""F-002""] .card-line');
var evidence = document.querySelector('.card.evidence .evidence-status');
return JSON.stringify({
  ok: true,
  withinChips: h.texts(within, '.chip'),
  withinClasses: h.attrs(within, '.chip', 'class'),
  oddChips: h.texts(odd, '.chip'),
  coverageCounts: h.text(document.getElementById('coverage-panel'), 'summary .fold-count'),
  bucketNames: h.texts(document.getElementById('coverage-panel'), '.bucket-name'),
  evidenceChip: evidence ? evidence.textContent : null,
  injected: h.injected(document.querySelector('.card.evidence')),
  metas: h.texts(document, '#attention-panel .attention-row .attention-meta')
});";

    private sealed class Run
    {
        public int LabelReadsAfterInit { get; set; }

        public int LabelReadsAfterSave { get; set; }

        public JsonElement Read { get; set; }
    }
}
