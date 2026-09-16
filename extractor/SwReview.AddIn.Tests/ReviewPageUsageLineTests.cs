using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 005 T016a: the running usage line on the Review page - tokens so far, the cached
/// share, the round trips and the last round's latency - accumulated in the pane from the
/// `usage` events it is already streaming, and updating while the turn is still running.
///
/// Three rules are asserted here because nowhere else can:
///
/// <b>The numbers come off the stream.</b> `GET /sessions/{chat_id}` is unchanged and the page
/// reads no usage total from a reply: putting these numbers on `ChatSession.public()` would be a
/// third copy of them, and the pane summing the stream is the same arithmetic `SessionUsage`
/// defines rather than a second rule. The invariant that proves it is small and checkable -
/// every `.usage` the page reads is `state.usage`, the array of event bodies it appended itself.
///
/// <b>Unknown stays unknown.</b> Every token field is `int | None` because a field the endpoint
/// omitted is `None`, not zero (`contracts/usage.md` section 1), and a sum over rounds where any
/// round reported `None` is `None` rather than a partial sum. So a null renders as "unknown",
/// and the cached share renders as unknown until the provider reports one (FR-047). A line that
/// showed "0 cached" for "the endpoint did not say" is the Principle I violation that contract
/// exists to prevent.
///
/// <b>It reaches the screen as text.</b> The line is built through `web/shared/dom.js` like
/// every other node on the page, and it is rendered here <i>inside the real page</i>, under the
/// real CSP, through the same offscreen WebView2 route <see cref="ReviewPageInjectionTests"/>
/// uses - so "textContent only" is answered by the browser rather than by a scan.
/// </summary>
public sealed class ReviewPageUsageLineTests
{
    /// <summary>The element the line is written into.</summary>
    private const string UsageElementId = "usage-line";

    // ---- the contract ---------------------------------------------------------------------

    /// <summary>
    /// The page handles the `usage` event. Without this case the adapter's events fall through
    /// the switch's `default` and the line never moves - which is exactly what shipping this
    /// layer without T016a would look like.
    /// </summary>
    [Fact]
    public void ThePageHandlesTheUsageEventTheAdaptersEmit()
    {
        string app = ReviewPageFiles.Read("app.js");

        Assert.Matches(new Regex(@"case\s+'usage'\s*:"), app);
        Assert.Contains("state.usage.push(", app);
    }

    /// <summary>
    /// Every field the line reads is a field of the `usage` event body as
    /// `specs/005-llm-efficiency/contracts/usage.md` section 5 defines it. A misspelled field
    /// name is otherwise invisible: it reads `undefined`, the line says "unknown", and nothing
    /// anywhere reports that the page asked for a field the adapter never sends.
    /// </summary>
    [Fact]
    public void EveryFieldTheLineReadsIsAFieldOfTheUsageEvent()
    {
        IReadOnlyCollection<string> contract = UsageEventFields();
        IReadOnlyCollection<string> read = FieldsReadPerRound();

        Assert.NotEmpty(read);
        string[] invented = read.Where(field => !contract.Contains(field)).ToArray();
        Assert.True(
            invented.Length == 0,
            "render.js reads fields the `usage` event does not carry: " + string.Join(", ", invented)
                + Environment.NewLine + "The event carries: " + string.Join(", ", contract));

        // The four the line is specified to show, so a line that quietly dropped one fails here
        // rather than at the workstation.
        foreach (string needed in new[]
                 { "input_tokens", "cached_input_tokens", "total_tokens", "latency_s" })
        {
            Assert.Contains(needed, read);
        }
    }

    /// <summary>
    /// The numbers are summed in the pane from the stream. `GET /sessions/{chat_id}` is
    /// untouched, and the page reads no `usage` off any reply - not off a session, and not off
    /// `session.ended`, which would only update the line once the whole review was over.
    /// </summary>
    [Fact]
    public void TheNumbersComeOffTheStreamAndNotOffTheSessionRoute()
    {
        var offences = new List<string>();

        foreach (KeyValuePair<string, string> script in ReviewPageFiles.Scripts())
        {
            foreach (Match match in UsageRead.Matches(script.Value))
            {
                // `state.usage` is the pane's own accumulator and `ui.usage` is the element the
                // line is written into; anything else with a `usage` on it came from the
                // backend.
                if (!match.Value.Contains("state.usage") && !match.Value.Contains("ui.usage"))
                {
                    offences.Add($"{script.Key}: {match.Value}");
                }
            }
        }

        Assert.True(
            offences.Count == 0,
            "The page reads a usage total from something other than the events it accumulated "
                + "itself, which would be a second copy of SessionUsage's arithmetic:"
                + Environment.NewLine + string.Join(Environment.NewLine, offences));
    }

    [Fact]
    public void TheLineHasItsOwnElementOnThePage()
    {
        Assert.Contains(UsageElementId, ReviewPageFiles.IndexHtml());
        Assert.Contains("'" + UsageElementId + "'", ReviewPageFiles.Read("app.js"));
    }

    // ---- the rendered line ------------------------------------------------------------------

    /// <summary>
    /// Two rounds, every field reported: the line states the total, the cached share, the round
    /// trips and the latency of the <b>last</b> round, which is the one an engineer watching a
    /// running turn is waiting on.
    /// </summary>
    [Fact]
    public void TheLineStatesTheTotalTheCachedShareTheRoundTripsAndTheLastLatency()
    {
        JsonElement rendered = Render(new object[]
        {
            Round(inputTokens: 10000, cachedInputTokens: 9000, totalTokens: 12000, latency: 4.31),
            Round(inputTokens: 2000, cachedInputTokens: 1200, totalTokens: 555, latency: 1.5),
        });

        string text = TextOf(rendered);
        Assert.Contains("12555", text);
        Assert.Contains("85%", text);
        Assert.Contains("2 round trips", text);
        Assert.Contains("1.50 s", text);
        Assert.DoesNotContain("unknown", text);
    }

    /// <summary>
    /// A null in any round makes that total null, never a partial sum: a partial sum silently
    /// understates and no reader can tell it happened (`contracts/usage.md` section 1, rule 3).
    /// </summary>
    [Fact]
    public void ANullInAnyRoundRendersAsUnknownAndNeverAsZero()
    {
        JsonElement rendered = Render(new object[]
        {
            Round(inputTokens: 10000, cachedInputTokens: 9000, totalTokens: 12000, latency: 4.31),
            Round(inputTokens: 2000, cachedInputTokens: 1200, totalTokens: null, latency: 1.5),
        });

        string text = TextOf(rendered);
        Assert.Contains("tokens unknown", text);
        Assert.DoesNotContain("12000", text);

        // The other three are still known, and are still shown: one unreported field does not
        // blank the line.
        Assert.Contains("2 round trips", text);
        Assert.Contains("1.50 s", text);
    }

    /// <summary>
    /// The cached share is unknown until the provider reports one (FR-047), which is the state
    /// every round is in before probe L1 is recorded. Zero cached tokens and "the endpoint did
    /// not say" are different answers and the line says which.
    /// </summary>
    [Fact]
    public void TheCachedShareIsUnknownUntilTheProviderReportsIt()
    {
        JsonElement rendered = Render(new object[]
        {
            Round(inputTokens: 10000, cachedInputTokens: null, totalTokens: 12000, latency: 4.31),
        });

        string text = TextOf(rendered);
        Assert.Contains("cached unknown", text);
        Assert.DoesNotContain("0%", text);
        Assert.Contains("12000", text);
    }

    [Fact]
    public void BeforeTheFirstRoundTheLineSaysSoRatherThanShowingZeros()
    {
        string text = TextOf(Render(new object[0]));

        Assert.DoesNotContain("0 tokens", text);
        Assert.Contains("No model round trips yet", text);
    }

    /// <summary>
    /// The line is built with `createTextNode` like every other node on this page. The hostile
    /// value here is a `latency_s` that is a string rather than a number - a malformed event
    /// body, which is the only way markup can reach this line at all - and it must arrive as
    /// characters, not as elements.
    /// </summary>
    [Fact]
    public void AMalformedRoundRendersAsTextAndExecutesNothing()
    {
        JsonElement rendered = Render(new object[]
        {
            new Dictionary<string, object?>
            {
                { "round_index", 0 },
                { "provider", "openai" },
                { "model", "gpt-5.6" },
                { "input_tokens", 10 },
                { "cached_input_tokens", 5 },
                { "total_tokens", 20 },
                { "latency_s", "</span><img src=x onerror=alert(1)>" },
            },
        });

        Assert.Equal(0, rendered.GetProperty("injected").GetInt32());
        Assert.Equal(0, rendered.GetProperty("handlers").GetInt32());
        Assert.DoesNotContain("<img", rendered.GetProperty("html").GetString());
    }

    // ---- reading the contract and the page --------------------------------------------------

    /// <summary>`round.<field>` in render.js: what the line actually asks each round for.</summary>
    private static readonly Regex RoundField = new Regex(
        @"\bround\.([a-z_]+)", RegexOptions.Compiled);

    /// <summary>
    /// Anything that reads a `usage` off an object. `state.usage` is the pane's own
    /// accumulator; everything else would be a number the page did not add up itself.
    /// </summary>
    private static readonly Regex UsageRead = new Regex(
        @"\b[A-Za-z_][A-Za-z0-9_]*\s*\.\s*usage\b", RegexOptions.Compiled);

    private static IReadOnlyCollection<string> FieldsReadPerRound()
    {
        var fields = new SortedSet<string>(StringComparer.Ordinal);
        foreach (Match match in RoundField.Matches(ReviewPageFiles.Read("render.js")))
        {
            fields.Add(match.Groups[1].Value);
        }

        return fields;
    }

    /// <summary>
    /// The field names of the `usage` event body, read out of the contract's own example rather
    /// than restated here, so the two cannot drift.
    /// </summary>
    private static IReadOnlyCollection<string> UsageEventFields()
    {
        string contract = ReviewPageFiles.ReadContract("usage.md");
        int section = contract.IndexOf("## 5. The `usage` event", StringComparison.Ordinal);
        Assert.True(section >= 0, "usage.md has no `usage` event section.");

        Match block = new Regex(@"```json\s*(\{.*?\})\s*```", RegexOptions.Singleline)
            .Match(contract, section);
        Assert.True(block.Success, "usage.md section 5 carries no JSON example of the event.");

        using (JsonDocument document = JsonDocument.Parse(block.Groups[1].Value))
        {
            return document.RootElement.EnumerateObject()
                .Select(property => property.Name)
                .ToList();
        }
    }

    private static Dictionary<string, object?> Round(
        int? inputTokens, int? cachedInputTokens, int? totalTokens, double latency) =>
        new Dictionary<string, object?>
        {
            { "round_index", 0 },
            { "provider", "openai" },
            { "model", "gpt-5.6" },
            { "input_tokens", inputTokens },
            { "cached_input_tokens", cachedInputTokens },
            { "cache_write_tokens", null },
            { "output_tokens", 512 },
            { "reasoning_tokens", 448 },
            { "tool_result_input_tokens", null },
            { "total_tokens", totalTokens },
            { "latency_s", latency },
            { "cache_diagnostic", null },
        };

    /// <summary>Renders the line inside the real page and reports what landed in the DOM.</summary>
    private static JsonElement Render(object rounds) =>
        OffscreenReviewPage.Evaluate(
            "return JSON.stringify(describe(render('usageLine', "
            + JsonSerializer.Serialize(rounds) + ")));");

    private static string TextOf(JsonElement rendered)
    {
        Assert.True(
            rendered.GetProperty("ok").GetBoolean(),
            rendered.TryGetProperty("error", out JsonElement error)
                ? error.GetString()
                : "the page did not render");
        return rendered.GetProperty("text").GetString()!;
    }
}
