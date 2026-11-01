using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 002 T316 (owner decision 185A; FR-031): a finding's triage on the Review page - one of four
/// outcomes beside Accept, Reject and Defer, optional and independent of the decision.
///
/// The fold holds a row of four toggle buttons of its own, before the tools row and outside the `.seg`
/// of the three decisions, and the row wraps at a docked pane's 300 px. A press only picks;
/// the decision pressed next carries the pick in its body, and no `triage` key when none is picked.
/// What the backend recorded - the reply to a decision, a `disposition` event, a finding's own body or
/// a restore - is what the row shows pressed and what the card's sentence names, in the backend's
/// words (`labels.triage`), or the token itself from a backend that sends none (FR-030). The page holds
/// no rule of its own: an Accept or Reject recorded without a triage takes one when the same decision
/// is pressed again with one picked (185A's late triage), and whatever the backend refuses is shown on
/// the card as any refused decision is.
/// </summary>
public sealed class ReviewPageTriageTests
{
    private const string Chat = "chat-1";

    private const string Engineer = "FICT-ENG";

    private const string RecordedAt = "2026-11-01T09:00:00+00:00";

    private const string RestoredChat = "chat-restored";

    private const string RestoredRun = "20261101-090000-bracket-restored";

    private const string IllegalTransition =
        "{\"error_class\":\"IllegalTransition\",\"message\":\"FICT finding F-001 already has a terminal disposition ('accepted'); it cannot be changed\",\"retryable\":false}";

    [Fact]
    public void TheReviewPageOffersTheFourOutcomesBesideAcceptRejectAndDefer()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Finding("F-001"));
            JsonElement fold = await driver.Read(ReadFold("F-001"));
            JsonElement card = await driver.Read(ReadCard("F-001"));
            string[] tokens = ContractTriages();

            Assert.Equal(4, tokens.Length);
            Assert.Equal(tokens, ReviewPageDriver.Strings(card, "tokens"));
            Assert.Equal(4, fold.GetProperty("inCard").GetInt32());
            Assert.Equal(1, fold.GetProperty("rows").GetInt32());
            Assert.Equal("group", fold.GetProperty("rowRole").GetString());
            Assert.Equal("Triage", fold.GetProperty("rowLabel").GetString());
            Assert.True(fold.GetProperty("rowInFold").GetBoolean(), "the triage row is not in the finding's fold.");
            Assert.True(fold.GetProperty("rowBeforeTools").GetBoolean(), "the triage row is not before the tools row.");
            Assert.Equal(0, fold.GetProperty("inSeg").GetInt32());
            Assert.Equal(new[] { "accept", "reject", "defer" }, ReviewPageDriver.Strings(fold, "segActions"));

            Assert.Equal(tokens.Select(Word).ToArray(), ReviewPageDriver.Strings(card, "words"));
            Assert.Equal(new[] { "false", "false", "false", "false" }, ReviewPageDriver.Strings(card, "ariaPressed"));
            Assert.Equal(string.Empty, card.GetProperty("status").GetString());
        });
    }

    /// <summary>
    /// A press picks one outcome at a time, a second press on the picked one lets it go, and nothing
    /// is sent until a decision is pressed. Rejected with `wrong` picked, the body carries it and the
    /// reply is shown; a deferred finding whose recorded triage is let go posts no `triage` key, and
    /// the reply - the backend keeps a Defer's triage when the later decision names none - is what the
    /// row shows pressed again.
    /// </summary>
    [Fact]
    public void APickedTriageTravelsWithTheDecisionAndIsShownOnTheCard()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(
                driver,
                Finding("F-001"),
                Finding("F-002", Disposition("deferred", "FICT check the bore", "not_worth_flagging")));
            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("rejected", string.Empty, "wrong")));
            await driver.Route("POST", DispositionPath("F-002"), 200,
                Finding("F-002", Disposition("accepted", "FICT check the bore", "not_worth_flagging")));
            Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(await driver.Read(ReadCard("F-001")), "tokens"));
            await driver.ClearCalls();

            await Press(driver, "F-001", "wrong");
            Assert.Equal(new[] { "wrong" }, Pressed(await driver.Read(ReadCard("F-001"))));
            await Press(driver, "F-001", "already_known");
            Assert.Equal(new[] { "already_known" }, Pressed(await driver.Read(ReadCard("F-001"))));
            await Press(driver, "F-001", "already_known");
            Assert.Empty(Pressed(await driver.Read(ReadCard("F-001"))));
            await Press(driver, "F-001", "wrong");
            Assert.Empty(await driver.Calls());

            await Decide(driver, "F-001", "reject");
            Assert.Equal("decision=rejected, note=, triage=wrong", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement rejected = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "wrong" }, Pressed(rejected));
            Assert.Equal("Disposition: rejected (" + Word("wrong") + ") by " + Engineer + " at " + RecordedAt, rejected.GetProperty("status").GetString());
            Assert.Equal("card-status decided", rejected.GetProperty("statusClass").GetString());

            Assert.Equal(new[] { "not_worth_flagging" }, Pressed(await driver.Read(ReadCard("F-002"))));
            await Press(driver, "F-002", "not_worth_flagging");
            Assert.Empty(Pressed(await driver.Read(ReadCard("F-002"))));
            await driver.ClearCalls();
            await Decide(driver, "F-002", "accept");
            Assert.Equal("decision=accepted, note=", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement accepted = await driver.Read(ReadCard("F-002"));
            Assert.Equal(new[] { "not_worth_flagging" }, Pressed(accepted));
            Assert.Equal(
                "Disposition: accepted (" + Word("not_worth_flagging") + ") by " + Engineer + " at " + RecordedAt + " - FICT check the bore",
                accepted.GetProperty("status").GetString());
        });
    }

    /// <summary>
    /// A finding the stream sends already decided - a re-run's restate (58A) - is drawn with its
    /// triage pressed; and a `disposition` event replaces whatever was picked on the card with what
    /// the backend recorded, whoever recorded it.
    /// </summary>
    [Fact]
    public void ATriageFromTheStreamIsShownPressed()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "finding", Finding("F-002", Disposition("deferred", "FICT check it", "new_and_real")));
            await driver.Settle();
            Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(await driver.Read(ReadCard("F-001")), "tokens"));

            await Press(driver, "F-001", "wrong");
            await driver.Push(Chat, 3, "disposition", DispositionEvent("F-001", Disposition("accepted", "FICT intended", "not_worth_flagging")));
            await driver.Settle();

            JsonElement first = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "not_worth_flagging" }, Pressed(first));
            Assert.Equal(
                "Disposition: accepted (" + Word("not_worth_flagging") + ") by " + Engineer + " at " + RecordedAt + " - FICT intended",
                first.GetProperty("status").GetString());

            JsonElement second = await driver.Read(ReadCard("F-002"));
            Assert.Equal(new[] { "new_and_real" }, Pressed(second));
            Assert.Equal(
                "Disposition: deferred (" + Word("new_and_real") + ") by " + Engineer + " at " + RecordedAt + " - FICT check it",
                second.GetProperty("status").GetString());
        });
    }

    /// <summary>FR-030: an older backend sends no labels, and the buttons and the sentence print the token.</summary>
    [Fact]
    public void WithNoLabelsTheTriageButtonsPrintTheirTokens()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "disposition", DispositionEvent("F-001", Disposition("accepted", string.Empty, "already_known")));
            await driver.Settle();

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(card, "words"));
            Assert.Equal(new[] { "already_known" }, Pressed(card));
            Assert.Equal("Disposition: accepted (already_known) by " + Engineer + " at " + RecordedAt, card.GetProperty("status").GetString());
        });
    }

    /// <summary>
    /// A review restored read-only from its run folder shows each recorded triage pressed, and every
    /// triage button is off with the decisions and the note boxes (contracts/sessions.md section 5).
    /// </summary>
    [Fact]
    public void ARestoredReviewLocksItsTriageButtons()
    {
        ReviewPageDriver.Run(
            driver =>
            {
                Labelled(driver);
                driver.Sessions.Add(ReviewPageSessionsTests.Item(RestoredChat, RestoredRun, ReviewPageDriver.ReviewedPath, 9, 0));
                driver.InitialRoutes.Add(("GET", "/sessions/" + RestoredChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat));
                driver.InitialRoutes.Add(("GET", "/reviews/" + RestoredRun, 200, RestoredSnapshot()));
            },
            async driver =>
            {
                await driver.Settle();
                JsonElement decided = await driver.Read(ReadCard("F-100"));
                JsonElement open = await driver.Read(ReadCard("F-101"));

                Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(decided, "tokens"));
                Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(open, "tokens"));
                Assert.All(Disabled(decided), off => Assert.True(off, "a triage button is live on a read-only review."));
                Assert.All(Disabled(open), off => Assert.True(off, "a triage button is live on a read-only review."));
                Assert.Equal(new[] { "already_known" }, Pressed(decided));
                Assert.Empty(Pressed(open));
                Assert.Equal(
                    "Disposition: accepted (" + Word("already_known") + ") by " + Engineer + " at " + RecordedAt + " - FICT intended",
                    decided.GetProperty("status").GetString());
            });
    }

    /// <summary>
    /// At a docked pane's 300 px every triage button is whole: inside the window and every box that
    /// clips it, and its words inside the button - the row wraps rather than cutting a word off.
    /// </summary>
    [Fact]
    public void EveryTriageButtonIsWhollyVisibleAtThreeHundredPixels()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await Reviewed(driver, Finding("F-001"));

            JsonElement measured = await driver.Read(ReadWhole("F-001"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.Equal(4, measured.GetProperty("count").GetInt32());
            Assert.True(measured.GetProperty("foldOpen").GetBoolean(), "the finding's fold did not open.");
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    /// <summary>
    /// 185A: an Accept recorded with none picked leaves the row live; picking `already known` and
    /// pressing Accept again posts the same decision with the triage and the note box as it stands,
    /// and the reply - the triage recorded, the first note, engineer and time kept - is what the card
    /// shows. A second triage, which the backend refuses, is shown on the card as any refused
    /// decision is.
    /// </summary>
    [Fact]
    public void ADecidedFindingWithoutATriageTakesOneWithTheSameDecision()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Finding("F-001"));
            Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(await driver.Read(ReadCard("F-001")), "tokens"));

            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", "FICT first note", null)));
            await Note(driver, "F-001", "FICT first note");
            await driver.ClearCalls();
            await Decide(driver, "F-001", "accept");
            Assert.Equal("decision=accepted, note=FICT first note", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement first = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(first));
            Assert.All(Disabled(first), off => Assert.False(off, "a decision without a triage locked the triage row."));
            Assert.Equal("Disposition: accepted by " + Engineer + " at " + RecordedAt + " - FICT first note", first.GetProperty("status").GetString());

            await driver.Route("POST", DispositionPath("F-001"), 200,
                Finding("F-001", Disposition("accepted", "FICT first note", "already_known")));
            await Note(driver, "F-001", "FICT second note");
            await driver.ClearCalls();
            await Press(driver, "F-001", "already_known");
            await Decide(driver, "F-001", "accept");
            Assert.Equal(
                "decision=accepted, note=FICT second note, triage=already_known",
                Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement late = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "already_known" }, Pressed(late));
            Assert.Equal(
                "Disposition: accepted (" + Word("already_known") + ") by " + Engineer + " at " + RecordedAt + " - FICT first note",
                late.GetProperty("status").GetString());
            Assert.Equal("card-status decided", late.GetProperty("statusClass").GetString());

            await driver.Route("POST", DispositionPath("F-001"), 409, IllegalTransition);
            await driver.ClearCalls();
            await Press(driver, "F-001", "wrong");
            await Decide(driver, "F-001", "accept");
            Assert.Equal(
                "decision=accepted, note=FICT second note, triage=wrong",
                Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal("card-status bad", refused.GetProperty("statusClass").GetString());
            Assert.Equal("IllegalTransition", refused.GetProperty("refusalClass").GetString());
            Assert.DoesNotContain("Disposition:", refused.GetProperty("status").GetString()!);
        });
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static void Labelled(ReviewPageDriver driver) =>
        driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));

    /// <summary>A review of <paramref name="findings"/>, ended; no ranking is routed, so the cards stay in the list.</summary>
    private static async Task Reviewed(ReviewPageDriver driver, params string[] findings)
    {
        await driver.StartReview();
        int seq = 0;
        foreach (string finding in findings)
        {
            await driver.Push(Chat, ++seq, "finding", finding);
        }

        await driver.EndSession(Chat);
    }

    /// <summary>Presses one triage button of one card, as the engineer does.</summary>
    private static async Task Press(ReviewPageDriver driver, string findingId, string token)
    {
        await driver.Read(
            "var node = document.querySelector('.card.finding[data-finding-id=\"" + findingId + "\"] [data-action=\"triage\"][data-triage=\"" + token + "\"]');"
            + "if (!node) { return JSON.stringify({ok: false, error: 'no triage button " + token + " on " + findingId + "'}); }"
            + "node.click(); return JSON.stringify({ok: true});");
        await driver.Settle();
    }

    /// <summary>Presses Accept, Reject or Defer on one card.</summary>
    private static async Task Decide(ReviewPageDriver driver, string findingId, string action)
    {
        await driver.Read(
            "document.querySelector('.card.finding[data-finding-id=\"" + findingId + "\"] [data-action=\"" + action + "\"]').click();"
            + "return JSON.stringify({ok: true});");
        await driver.Settle();
    }

    /// <summary>Types into one card's note box.</summary>
    private static Task Note(ReviewPageDriver driver, string findingId, string text) =>
        driver.Read(
            "document.querySelector('.card.finding[data-finding-id=\"" + findingId + "\"] input.note').value = "
            + JsonSerializer.Serialize(text) + "; return JSON.stringify({ok: true});");

    private static string DispositionPath(string findingId) => "/sessions/" + Chat + "/findings/" + findingId + "/disposition";

    private static async Task<JsonElement[]> DispositionCalls(ReviewPageDriver driver) =>
        (await driver.Calls())
            .Where(call => call.GetProperty("method").GetString() == "POST"
                && call.GetProperty("path").GetString()!.EndsWith("/disposition", StringComparison.Ordinal))
            .ToArray();

    /// <summary>A posted body as its keys and values in key order, so a key left out reads as absent.</summary>
    private static string Body(JsonElement call)
    {
        using (JsonDocument body = JsonDocument.Parse(call.GetProperty("body").GetString()!))
        {
            return string.Join(", ", body.RootElement.EnumerateObject()
                .OrderBy(field => field.Name, StringComparer.Ordinal)
                .Select(field => field.Name + "=" + field.Value.GetString()));
        }
    }

    private static string[] Pressed(JsonElement card) => ReviewPageDriver.Strings(card, "pressed");

    private static bool[] Disabled(JsonElement card) =>
        card.GetProperty("disabled").EnumerateArray().Select(value => value.GetBoolean()).ToArray();

    // ---- the contract and the words -------------------------------------------------------------

    /// <summary>review-session.schema.json's `Disposition.triage` enum: the four tokens, in their order.</summary>
    private static string[] ContractTriages()
    {
        using (JsonDocument schema = JsonDocument.Parse(ReviewPageFiles.ReadContract("review-session.schema.json")))
        {
            return schema.RootElement.GetProperty("$defs").GetProperty("Disposition").GetProperty("properties")
                .GetProperty("triage").GetProperty("enum").EnumerateArray()
                .Select(value => value.GetString()!)
                .ToArray();
        }
    }

    /// <summary>`LabelsSample`'s word for one triage token.</summary>
    private static string Word(string token)
    {
        using (JsonDocument labels = JsonDocument.Parse(LabelsSample.Json()))
        {
            return labels.RootElement.GetProperty("triage").GetProperty(token).GetString()!;
        }
    }

    // ---- samples ------------------------------------------------------------------------------

    private static string Finding(string id, Dictionary<string, object?>? disposition = null) =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "id", id },
            { "check", "interference.static" },
            { "title", "FICT finding " + id },
            { "status", "demonstrated" },
            { "severity", "medium" },
            { "component_ids", new[] { "cmp:0002" } },
            { "observed", "FICT observed for " + id + "." },
            { "disposition", disposition },
        });

    /// <summary>A recorded disposition; the triage is left out when none, as the backend leaves it out.</summary>
    private static Dictionary<string, object?> Disposition(string decision, string note, string? triage)
    {
        var disposition = new Dictionary<string, object?>
        {
            { "decision", decision },
            { "note", note },
            { "by", Engineer },
            { "at", RecordedAt },
        };
        if (triage != null)
        {
            disposition["triage"] = triage;
        }

        return disposition;
    }

    private static string DispositionEvent(string findingId, Dictionary<string, object?> disposition) =>
        JsonSerializer.Serialize(new Dictionary<string, object?> { { "finding_id", findingId }, { "disposition", disposition } });

    /// <summary>A run folder's read-only snapshot: one finding accepted with a triage, one undecided, no ranking.</summary>
    private static string RestoredSnapshot() => new JsonObject
    {
        ["run_id"] = RestoredRun,
        ["read_only"] = true,
        ["read_only_reason"] = ReviewPageSessionsTests.ReadOnlyReason,
        ["chat_state"] = null,
        ["last_seq"] = null,
        ["document"] = JsonNode.Parse(JsonSerializer.Serialize(new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" })),
        ["findings"] = new JsonArray(
            JsonNode.Parse(Finding("F-100", Disposition("accepted", "FICT intended", "already_known"))),
            JsonNode.Parse(Finding("F-101"))),
        ["evidence_requests"] = new JsonArray(),
        ["coverage"] = new JsonArray(),
        ["ranking"] = null,
        ["not_examined"] = null,
    }.ToJsonString();

    // ---- reading the page ---------------------------------------------------------------------

    /// <summary>One card's triage buttons - tokens, words, pressed and off - its sentence, and a refusal's class.</summary>
    private static string ReadCard(string findingId) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
if (!card) { return JSON.stringify({ ok: false, error: 'no card " + findingId + @"' }); }
var buttons = card.querySelectorAll('[data-action=""triage""]');
var pressed = [];
var disabled = [];
for (var i = 0; i < buttons.length; i++) {
  if (buttons[i].getAttribute('aria-pressed') === 'true') { pressed.push(buttons[i].getAttribute('data-triage')); }
  disabled.push(buttons[i].disabled);
}
var status = card.querySelector('.card-status');
return JSON.stringify({
  ok: true,
  tokens: h.attrs(card, '[data-action=""triage""]', 'data-triage'),
  words: h.texts(card, '[data-action=""triage""]'),
  ariaPressed: h.attrs(card, '[data-action=""triage""]', 'aria-pressed'),
  pressed: pressed,
  disabled: disabled,
  status: status ? status.textContent : null,
  statusClass: status ? status.className : null,
  refusalClass: status ? h.text(status, '.error-fold .error-class') : null
});";

    /// <summary>Where the triage buttons stand in one card: one row in the fold, before the tools row, outside the decisions.</summary>
    private static string ReadFold(string findingId) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
var fold = card.querySelector('.details');
var tools = fold.querySelector('.card-tools');
var buttons = card.querySelectorAll('[data-action=""triage""]');
var rows = [];
for (var i = 0; i < buttons.length; i++) {
  if (rows.indexOf(buttons[i].parentElement) < 0) { rows.push(buttons[i].parentElement); }
}
var row = rows.length ? rows[0] : null;
return JSON.stringify({
  ok: true,
  inCard: buttons.length,
  rows: rows.length,
  rowRole: row ? row.getAttribute('role') : null,
  rowLabel: row ? row.getAttribute('aria-label') : null,
  rowInFold: !!row && fold.contains(row),
  rowBeforeTools: h.before(row, tools),
  inSeg: card.querySelectorAll('.seg [data-action=""triage""]').length,
  segActions: h.attrs(fold.querySelector('.seg'), '[data-action]', 'data-action')
});";

    /// <summary>
    /// Opens one card's fold and measures each triage button brought into view: no box scrolled
    /// sideways to show it, inside the window and every ancestor that clips, on both axes, with its
    /// words inside it; and no sideways page scroll.
    /// </summary>
    private static string ReadWhole(string findingId) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
card.querySelector('[data-action=""expand""]').click();
var whole = function (node) {
  node.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  var rect = node.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) { return false; }
  if (node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1) { return false; }
  for (var p = node.parentElement; p; p = p.parentElement) {
    // The pane scrolls up and down only: a box scrolled sideways to show the button cuts it off at rest.
    if (p.scrollLeft !== 0) { return false; }
    var style = getComputedStyle(p);
    if (style.overflowX !== 'visible' || style.overflowY !== 'visible') {
      var box = p.getBoundingClientRect();
      if (rect.left < box.left - 1 || rect.right > box.right + 1 || rect.top < box.top - 1 || rect.bottom > box.bottom + 1) { return false; }
    }
  }
  return rect.left >= -1 && rect.right <= window.innerWidth + 1 && rect.top >= -1 && rect.bottom <= window.innerHeight + 1;
};
var buttons = card.querySelectorAll('[data-action=""triage""]');
var clipped = [];
for (var i = 0; i < buttons.length; i++) {
  if (!whole(buttons[i])) { clipped.push(buttons[i].getAttribute('data-triage') + ' ' + JSON.stringify(buttons[i].getBoundingClientRect())); }
}
return JSON.stringify({
  ok: true,
  width: window.innerWidth,
  count: buttons.length,
  foldOpen: !card.querySelector('.details').hidden,
  clipped: clipped,
  noHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth
});";
}
