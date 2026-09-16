using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T134: every untrusted string this tab shows reaches the screen as characters, not as
/// elements (FR-029, contracts/pane-remodel-messages.md).
///
/// This page has more untrusted provenance than any other tab, and two kinds of it. A feature
/// name is whatever an engineer typed into the SOLIDWORKS feature tree - on a supplied model,
/// whoever last renamed a feature is not anyone this workstation knows - and a rebuild reason's
/// detail is assembled out of those names. A description and a rationale are written by a
/// language model, which is a string generator being handed a part someone else authored. The
/// run folder path is the add-in's own, and it still carries whatever the document was called.
/// The Task Pane runs inside SOLIDWORKS with a backend token in its renderer, so any of these
/// becoming an element is a script running there.
///
/// The test is driven the way <see cref="ModelCheckPageInjectionTests"/> is driven and for the
/// reasons given there: the page's own renderers are called <i>inside the real page</i>, loaded
/// from the real virtual host under the real CSP, and the result is read back through
/// `ExecuteScriptAsync`. What it asserts is the <b>node type</b> that landed - a text node
/// whose value is the hostile string, character for character - rather than the absence of an
/// alert, because a page that dropped the string entirely would also raise no alert.
///
/// A static scan over the page's scripts - its own and the shared `shared/dom.js` it loads - is
/// the other half: a sink that turns a string into markup is a defect whether or not a test
/// happens to reach it.
/// </summary>
public sealed class RemodelPageInjectionTests
{
    /// <summary>A DOM `Node.TEXT_NODE`. Anything else here is an element that got parsed.</summary>
    private const int TextNode = 3;

    // ---- the rendered DOM -------------------------------------------------------------------

    [Fact]
    public void AFeatureNameCarryingMarkupIsATextNodeInTheChangeList()
    {
        JsonElement rendered = OffscreenRemodelPage.Evaluate(
            "remodel(" + RemodelResultSample.ResultJson(RemodelResultSample.HostileFeatureName) + ");"
            + "return JSON.stringify({ok: true, "
            + "subjects: nodes('#changes .change .subject-name'), "
            + "region: describe(document.getElementById('changes'))});");

        JsonElement first = Ok(rendered).GetProperty("subjects").EnumerateArray().First();

        // The assertion is the node type and the exact characters, not the absence of an alert:
        // a page that swallowed the name would raise no alert either.
        Assert.Equal(TextNode, first.GetProperty("node_type").GetInt32());
        Assert.Equal(RemodelResultSample.HostileFeatureName, first.GetProperty("value").GetString());
        Assert.Equal(0, first.GetProperty("children").GetInt32());

        AssertNothingWasParsed(rendered.GetProperty("region"), RemodelResultSample.HostileFeatureName);
    }

    [Fact]
    public void ADescriptionContainingAScriptEndTagIsATextNodeInTheJudgement()
    {
        JsonElement rendered = OffscreenRemodelPage.Evaluate(
            "plan(" + RemodelResultSample.PlanSummaryJson(RemodelResultSample.HostileDescription) + ");"
            + "return JSON.stringify({ok: true, "
            + "proposals: nodes('#judgement .proposal .proposal-text'), "
            + "region: describe(document.getElementById('judgement'))});");

        JsonElement first = Ok(rendered).GetProperty("proposals").EnumerateArray().First();

        Assert.Equal(TextNode, first.GetProperty("node_type").GetInt32());
        Assert.Equal(RemodelResultSample.HostileDescription, first.GetProperty("value").GetString());

        AssertNothingWasParsed(rendered.GetProperty("region"), RemodelResultSample.HostileDescription);
    }

    [Fact]
    public void ARebuildReasonCarryingMarkupIsATextNodeInTheRebuildList()
    {
        JsonElement rendered = OffscreenRemodelPage.Evaluate(
            "remodel(" + RemodelResultSample.ResultJson(
                "Cut-Extrude1", RemodelResultSample.HostileRebuildDetail) + ");"
            + "return JSON.stringify({ok: true, "
            + "details: nodes('#rebuild .entry .detail'), "
            + "region: describe(document.getElementById('rebuild'))});");

        JsonElement first = Ok(rendered).GetProperty("details").EnumerateArray().First();

        Assert.Equal(TextNode, first.GetProperty("node_type").GetInt32());
        Assert.Equal(RemodelResultSample.HostileRebuildDetail, first.GetProperty("value").GetString());

        AssertNothingWasParsed(rendered.GetProperty("region"), RemodelResultSample.HostileRebuildDetail);
    }

    /// <summary>
    /// The run folder path, which carries the quotes that break a hand-built attribute. It is
    /// the one untrusted string on this page that the host produced rather than the model or
    /// the feature tree, and it is held to the same rule.
    /// </summary>
    [Fact]
    public void ARunPathContainingQuotesIsATextNodeInTheRunHeader()
    {
        JsonElement rendered = OffscreenRemodelPage.Evaluate(
            "run(" + JsonSerializer.Serialize(RemodelResultSample.HostileRunPath) + ");"
            + "return JSON.stringify({ok: true, "
            + "paths: nodes('#run-dir'), "
            + "region: describe(document.getElementById('run-header'))});");

        JsonElement first = Ok(rendered).GetProperty("paths").EnumerateArray().First();

        Assert.Equal(TextNode, first.GetProperty("node_type").GetInt32());
        Assert.Equal(RemodelResultSample.HostileRunPath, first.GetProperty("value").GetString());

        AssertNothingWasParsed(rendered.GetProperty("region"), RemodelResultSample.HostileRunPath);
    }

    /// <summary>
    /// The region that held the hostile string shows it as characters and holds nothing that
    /// was parsed out of it.
    /// </summary>
    private static void AssertNothingWasParsed(JsonElement region, string hostile)
    {
        Assert.Contains(hostile, region.GetProperty("text").GetString()!);
        Assert.Equal(0, region.GetProperty("injected").GetInt32());
        Assert.Equal(0, region.GetProperty("handlers").GetInt32());

        // The serialized markup proves the other half: the browser escaped what it was given
        // instead of parsing it, which is what `textContent` does and `innerHTML` does not.
        string html = region.GetProperty("html").GetString()!;
        Assert.Contains("&lt;", html);
        Assert.DoesNotContain("<img", html);
        Assert.DoesNotContain("<script", html);
        Assert.DoesNotContain("<iframe", html);
    }

    private static JsonElement Ok(JsonElement rendered)
    {
        Assert.True(
            rendered.GetProperty("ok").GetBoolean(),
            rendered.TryGetProperty("error", out JsonElement error)
                ? error.GetString()
                : "the page did not render");
        return rendered;
    }

    // ---- the static half: the page's own rules ------------------------------------------------

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
        string index = RemodelPageFiles.IndexHtml();

        List<string> handlers = Regex.Matches(index, @"<[^>!][^>]*?\s(on[a-z]+)\s*=", RegexOptions.IgnoreCase)
            .Cast<Match>()
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        Assert.True(
            handlers.Count == 0,
            "index.html carries inline event handlers (" + string.Join(", ", handlers)
                + "); every handler is attached with addEventListener in remodel.js.");
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
        RemodelPageFiles.Scripts()
            .Concat(new[]
            {
                new KeyValuePair<string, string>("index.html", RemodelPageFiles.IndexHtml()),
            });
}
