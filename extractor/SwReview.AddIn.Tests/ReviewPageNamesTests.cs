using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 009 T030: names instead of ids where a part has one (FR-012, contracts/plain-words.md
/// section 3).
///
/// A component id is how the package names a part - `cmp:0003` - and it is how the Start-here
/// rows and the not-loaded warning named parts until feature 009: correct, and unreadable to
/// anyone who did not write the extractor. The backend sends the names beside the ids
/// (`not_examined.headline`); the Review tab prints the name where there is one and the id where
/// there is not, and keeps every id one fold away. The check tabs are handed no names and keep
/// printing ids - their subject lists are about ids (research R4) - so the shared row prints names
/// only when the caller passes them.
///
/// Feature 013 T053 removed the two tests of the Review tab's Start-here meta line: the tab has no
/// Start here, and a grouped row prints the backend's display title - which names the parts - and
/// its `reach_text`, never a list of components (contracts/grouped-list.md section 3).
/// </summary>
public sealed class ReviewPageNamesTests
{
    private const string Headline =
        "3 of 89 parts were not loaded: Pin-A-1 and Pin-B-1 (lightweight), Plate-1 (suppressed). "
        + "Interference, fit and the feature-tree rules cannot see them.";

    private const string Sentence =
        "3 of 89 component instances were not read: Pin-A-1 cmp:0002 (lightweight), Pin-B-1 cmp:0004 "
        + "(lightweight), Plate-1 cmp:0003 (suppressed). Interference, fit and the feature-tree rules cannot see them.";

    private static readonly Lazy<Run> Scripted = new Lazy<Run>(Drive);

    /// <summary>
    /// The not-loaded warning leads with the backend's names-only headline, and the instances'
    /// ids and states are in a shut fold beneath it - one press away, and off the default view.
    /// </summary>
    [Fact]
    public void TheNotLoadedWarningPrintsTheHeadlineWithEachInstancesIdAndStateInAShutFold()
    {
        JsonElement named = Scripted.Value.Named;

        Assert.Equal(Headline, named.GetProperty("headline").GetString());
        Assert.Equal("shut", named.GetProperty("fold").GetString());
        Assert.Equal(
            new[] { "cmp:0002 (lightweight)", "cmp:0004 (lightweight)", "cmp:0003 (suppressed)" },
            ReviewPageDriver.Strings(named, "instances"));
        Assert.DoesNotContain("cmp:", named.GetProperty("visible").GetString()!);
    }

    /// <summary>
    /// FR-030: a warning with no headline - every backend before this feature - prints its
    /// sentence exactly as before, and adds no fold (the sentence already names the ids).
    /// </summary>
    [Fact]
    public void AWarningWithNoHeadlinePrintsItsSentenceExactlyAsBefore()
    {
        JsonElement plain = Scripted.Value.Plain;

        Assert.Equal(Sentence, plain.GetProperty("text").GetString());
        Assert.Equal("none", plain.GetProperty("fold").GetString());
    }

    /// <summary>
    /// The Model check tab is handed no names, and prints ids even when the ranking on its body
    /// carries a summary: the check tabs do not read one (research R4).
    /// </summary>
    [Fact]
    public void TheModelCheckTabPrintsIdsEvenWhenItsRankingCarriesASummary()
    {
        JsonElement rendered = OffscreenModelCheckPage.Evaluate(
            "var result = " + CheckResultSample.Json() + ";"
            + "result.attention = " + SummarySample.Json() + ";"
            + "check(result);"
            + "var metas = document.querySelectorAll('#attention .attention-meta');"
            + "var out = []; for (var i = 0; i < metas.length; i++) { out.push(metas[i].textContent); }"
            + "return JSON.stringify({ok: true, metas: out});");

        Assert.True(rendered.GetProperty("ok").GetBoolean(), rendered.ToString());
        Assert.Equal("demonstrated · medium · cmp:0002, cmp:0003", ReviewPageDriver.Strings(rendered, "metas")[0]);
    }

    private static Run Drive()
    {
        var run = new Run();

        ReviewPageDriver.Run(
            driver =>
            {
                driver.ReviewStarted = press => new Dictionary<string, object?>
                {
                    { "chat_id", "chat-" + press },
                    { "run_dir", @"C:\SwReviewRuns\20260923-101500-bracket-" + press },
                    { "document", new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" } },
                    { "not_examined", press == 1 ? NamedWarning() : PlainWarning() },
                };
            },
            async driver =>
            {
                await driver.RouteAttention("chat-1", SummarySample.Json());
                await driver.StartReview();
                await driver.EndSession("chat-1");
                run.Named = await driver.Read(ReadNames);

                await driver.StartReview();
                run.Plain = await driver.Read(ReadNames);
            });

        return run;
    }

    private static object NamedWarning() => new
    {
        sentence = Sentence,
        headline = Headline,
        instances = new[]
        {
            new { id = "cmp:0002", name = "Pin-A-1", state = "lightweight" },
            new { id = "cmp:0004", name = "Pin-B-1", state = "lightweight" },
            new { id = "cmp:0003", name = "Plate-1", state = "suppressed" },
        },
    };

    private static object PlainWarning() => new
    {
        sentence = Sentence,
        instances = new[] { new { id = "cmp:0002", name = "Pin-A-1", state = "lightweight" } },
    };

    private const string ReadNames = @"
var warning = document.getElementById('not-examined');
var fold = warning.querySelector('details');
return JSON.stringify({
  ok: true,
  headline: h.text(warning, '.not-examined-headline'),
  fold: fold ? (fold.open ? 'open' : 'shut') : 'none',
  instances: fold ? h.texts(fold, 'li') : [],
  visible: h.visibleText(warning),
  text: warning.textContent
});";

    private sealed class Run
    {
        public JsonElement Named { get; set; }

        public JsonElement Plain { get; set; }
    }
}
