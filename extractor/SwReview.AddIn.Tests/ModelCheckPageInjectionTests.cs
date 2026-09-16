using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T081 (injection): a feature name and an observed string that contain markup reach the screen
/// as characters, not as elements (FR-029, contracts/pane-host-messages.md).
///
/// This page's untrusted text has a different provenance from the Review page's and is no less
/// dangerous for it. Nothing here was written by a language model: a feature name is whatever
/// an engineer typed into the SOLIDWORKS feature tree, and an `observed` string is assembled
/// out of those names by the rule layer. A part that arrived from a supplier - or from anyone
/// who has ever been able to rename a feature - is the injection vector, and the Task Pane runs
/// inside SOLIDWORKS with a backend token in its renderer.
///
/// The test is driven the way <see cref="ReviewPageInjectionTests"/> is driven and for the
/// reasons given there: the page's own renderer is called <i>inside the real page</i>, loaded
/// from the real virtual host under the real CSP, and the result is read back through
/// `ExecuteScriptAsync`. A static scan over the page's scripts - its own and the shared
/// `shared/dom.js` it loads - is the other half.
/// </summary>
public sealed class ModelCheckPageInjectionTests
{
    // ---- the rendered DOM -------------------------------------------------------------------

    [Fact]
    public void AFeatureNameAndAnObservedStringRenderAsLiteralText()
    {
        string result = CheckResultSample.Json(
            featureName: CheckResultSample.HostileFeatureName,
            observed: CheckResultSample.HostileObserved);

        JsonElement rendered = OffscreenModelCheckPage.Evaluate(
            "check(" + result + "); return JSON.stringify(describe(document.getElementById('rules')));");

        Assert.True(
            rendered.GetProperty("ok").GetBoolean(),
            rendered.TryGetProperty("error", out JsonElement error)
                ? error.GetString()
                : "the page did not render");

        string text = rendered.GetProperty("text").GetString()!;
        string html = rendered.GetProperty("html").GetString()!;

        Assert.Contains(CheckResultSample.HostileFeatureName, text);
        Assert.Contains(CheckResultSample.HostileObserved, text);

        Assert.Equal(0, rendered.GetProperty("injected").GetInt32());
        Assert.Equal(0, rendered.GetProperty("handlers").GetInt32());

        // The serialized markup proves the other half: the browser escaped what it was given
        // instead of parsing it, which is what `textContent` does and `innerHTML` does not.
        Assert.Contains("&lt;", html);
        Assert.DoesNotContain("<img", html);
        Assert.DoesNotContain("<script", html);
    }

    // ---- the static half: the page's own rules ------------------------------------------------

    [Fact]
    public void IndexHtmlCarriesTheContractCspMetaTag()
    {
        Match meta = Regex.Match(
            ModelCheckPageFiles.IndexHtml(),
            @"<meta\s+http-equiv=""Content-Security-Policy""\s+content=""([^""]*)""\s*/?>",
            RegexOptions.IgnoreCase);

        Assert.True(meta.Success, "index.html carries no Content-Security-Policy meta tag.");

        // Byte-identical to the one contracts/pane-host-messages.md prints, which is the one
        // the Review and Terminal pages already ship: three pages on one origin with three
        // policies is one policy nobody checked.
        Assert.Equal(Normalize(ContractCsp()), Normalize(meta.Groups[1].Value));
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
        string index = ModelCheckPageFiles.IndexHtml();

        List<string> handlers = Regex.Matches(index, @"<[^>!][^>]*?\s(on[a-z]+)\s*=", RegexOptions.IgnoreCase)
            .Cast<Match>()
            .Select(match => match.Groups[1].Value)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        Assert.True(
            handlers.Count == 0,
            "index.html carries inline event handlers (" + string.Join(", ", handlers)
                + "); every handler is attached with addEventListener in check.js.");
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
        ModelCheckPageFiles.Scripts()
            .Concat(new[] { new KeyValuePair<string, string>("index.html", ModelCheckPageFiles.IndexHtml()) });

    /// <summary>The CSP the contract prints in its fenced `html` block, read as data.</summary>
    private static string ContractCsp()
    {
        Match meta = Regex.Match(
            ReviewPageFiles.ReadContract("pane-host-messages.md"),
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
