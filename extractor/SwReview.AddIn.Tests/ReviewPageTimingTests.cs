using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 007, cycle 18 (007 T089; research R12; contracts/timing.md section 3): the minutes typed on the Review page.
///
/// At the end of Results a minutes form holds one text field per human timing input the backend's labels name -
/// `labels.timing`, keyed by `TIMING_INPUTS` in their order, each field labelled with its word - and Save, which posts the
/// fields to `POST /sessions/{chat_id}/timing`: a blank field as null, which keeps what is recorded, a number as a number,
/// and any other text as typed, for the route to refuse. It shows on a live review once a turn of it has ended, is off while
/// a turn runs and is absent on a read-only restore, where the console stays the way. After Save one line says the minutes
/// are recorded, in the words file's words (`labels.timing_form`); a refusal says its class's sentence (`labels.errors`) and
/// never the backend's message; either way the typed figures stay in the fields, and nowhere else on the page - neither the
/// reply's nor a refusal's. The form starts blank on every review it shows, and with no labels there is none (009 FR-030).
/// Every figure is fictional, and each one no other text of the page holds, so finding it in the page's text means the page
/// printed it.
/// </summary>
public sealed class ReviewPageTimingTests
{
    private const string Chat = "chat-1";

    private const string TimingPath = "/sessions/" + Chat + "/timing";

    /// <summary>An earlier live review of the same document, kept by the host.</summary>
    private const string OtherChat = "chat-2";

    private const string OtherRun = "20260923-083000-bracket-2";

    /// <summary>A review the host kept whose chat the backend no longer holds: restored read-only from its run folder.</summary>
    private const string RestoredChat = "chat-restored";

    private const string RestoredRun = "20260923-090000-bracket-restored";

    /// <summary>The six figures typed, in `TIMING_INPUTS`' order.</summary>
    private static readonly string[] Typed = { "417", "23.75", "331", "199", "57", "86" };

    /// <summary><see cref="Typed"/> as the page posts them: numbers, under the labels' keys in their order.</summary>
    private const string Posted =
        "{\"baseline\":417,\"supervision\":23.75,\"verification\":331,\"false_alarms\":199,\"setup\":57,\"by_hand\":86}";

    /// <summary>
    /// The route's `200`, the recomputed `Timing`: the figures again and the net the backend derives from them, which the
    /// page prints none of.
    /// </summary>
    private const string Recorded =
        "{\"baseline_minutes\":417.0,\"assisted_supervision_minutes\":23.75,\"assisted_verification_minutes\":331.0,"
        + "\"false_alarm_handling_minutes\":199.0,\"setup_minutes\":57.0,\"review_by_hand_minutes\":86.0,"
        + "\"unattended_runtime_minutes\":12.5,\"net_saved_minutes\":-279.75}";

    /// <summary>The net in <see cref="Recorded"/>, which no text of the page may hold either.</summary>
    private const string Net = "279.75";

    /// <summary>The route's refusal of a negative figure, as it names the key and the value.</summary>
    private const string InvalidTiming =
        "{\"error_class\":\"InvalidTiming\",\"message\":\"baseline must not be negative, got -417.0\",\"retryable\":false}";

    private const string TurnRunning =
        "{\"error_class\":\"TurnRunning\",\"message\":\"chat chat-1 is running a turn; wait for it to end\",\"retryable\":true}";

    /// <summary>
    /// The form's fields post every figure under its key, in the labels' order, as numbers, to the live route - one call,
    /// with the token - and Save is off while every field is blank, since it would record nothing. A blank field posts
    /// null, which keeps what is recorded, and text that is no number is posted as typed, for the route to refuse by name:
    /// the page holds no rule about minutes.
    /// </summary>
    [Fact]
    public void TheFormPostsEachFigureToTheTimingRoute()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver);
            await driver.Route("POST", TimingPath, 200, Recorded);
            JsonElement blank = await driver.Read(ReadForm);
            Assert.True(blank.GetProperty("shown").GetBoolean(), "the minutes form is not shown on a finished live review.");
            Assert.Equal(6, Values(blank).Length);
            Assert.All(Values(blank), value => Assert.Equal(string.Empty, value));
            Assert.True(blank.GetProperty("saveDisabled").GetBoolean(), "Save is on while every field is blank.");

            await driver.ClearCalls();
            await Type(driver, Typed);
            Assert.False((await driver.Read(ReadForm)).GetProperty("saveDisabled").GetBoolean(), "Save is off with figures typed.");
            await Save(driver);

            JsonElement call = Assert.Single(await TimingCalls(driver));
            Assert.Equal("POST", call.GetProperty("method").GetString());
            Assert.Equal(Posted, call.GetProperty("body").GetString());
            Assert.Equal("Bearer " + ReviewPageDriver.Token, call.GetProperty("authorization").GetString());

            await driver.ClearCalls();
            await Type(driver, string.Empty, "about 30", "331", "  ", "57", "8.5");
            await Save(driver);
            Assert.Equal(
                "{\"baseline\":null,\"supervision\":\"about 30\",\"verification\":331,\"false_alarms\":null,\"setup\":57,\"by_hand\":8.5}",
                Assert.Single(await TimingCalls(driver)).GetProperty("body").GetString());
        });
    }

    /// <summary>
    /// After Save the form says, in one line, that the minutes are recorded, in the words file's words; the typed figures
    /// stay in their fields; and neither they nor the reply's figures and net are in any text of the page - the Transcript
    /// and Results included. A field typed in again takes the line away, since it no longer says what is recorded.
    /// </summary>
    [Fact]
    public void ASaveSaysTheMinutesAreRecordedAndPrintsNoFigure()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver);
            await driver.Route("POST", TimingPath, 200, Recorded);
            await Type(driver, Typed);
            await Save(driver);

            JsonElement saved = await driver.Read(ReadForm);
            Assert.True(saved.GetProperty("savedShown").GetBoolean(), "the line after Save is not shown.");
            Assert.Equal(LabelsSample.TimingSaved, saved.GetProperty("savedText").GetString());
            Assert.False(saved.GetProperty("refusalShown").GetBoolean(), "a refusal shows after a save that was recorded.");
            Assert.Equal(Typed, Values(saved));
            AssertNoFigureInThePagesText(saved);

            await Type(driver, "418", "23.75", "331", "199", "57", "86");
            JsonElement edited = await driver.Read(ReadForm);
            Assert.False(edited.GetProperty("savedShown").GetBoolean(), "the line still says the minutes are recorded after an edit.");
        });
    }

    /// <summary>
    /// A refused save says its class's sentence from the words file's `errors`, its class behind the Details fold, and
    /// never the backend's message, which names the refused figure; the line that the minutes are recorded is not shown;
    /// and the typed figures stay in their fields for the retry. Each class says its own sentence.
    /// </summary>
    [Fact]
    public void ARefusalSaysItsSentenceAndKeepsTheFigures()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver);
            string[] negative = { "-417", "23.75", "331", "199", "57", "86" };
            await driver.Route("POST", TimingPath, 400, InvalidTiming);
            await Type(driver, negative);
            await Save(driver);

            JsonElement refused = await driver.Read(ReadForm);
            Assert.True(refused.GetProperty("refusalShown").GetBoolean(), "the refusal is not shown.");
            Assert.Equal(LabelsSample.InvalidTiming, refused.GetProperty("refusalText").GetString());
            Assert.Equal("InvalidTiming", refused.GetProperty("refusalClass").GetString());
            Assert.True(refused.GetProperty("refusalBad").GetBoolean(), "the refusal is not in the hue of a refusal.");
            Assert.False(refused.GetProperty("savedShown").GetBoolean(), "a refused save says the minutes are recorded.");
            Assert.Equal(negative, Values(refused));
            Assert.DoesNotContain("must not be negative", refused.GetProperty("bodyText").GetString());
            AssertNoFigureInThePagesText(refused);

            await driver.Route("POST", TimingPath, 409, TurnRunning);
            await Save(driver);
            JsonElement busy = await driver.Read(ReadForm);
            Assert.Equal(LabelsSample.TurnRunning, busy.GetProperty("refusalText").GetString());
            Assert.Equal("TurnRunning", busy.GetProperty("refusalClass").GetString());
            Assert.Equal(negative, Values(busy));
        });
    }

    /// <summary>
    /// The form shows once the review's turn has ended, not before; a follow-up's turn turns every field and Save off,
    /// keeping what was typed, so a press then posts nothing; and the turn's end turns them on again.
    /// </summary>
    [Fact]
    public void TheFormIsOffWhileATurnRuns()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.Route("POST", "/sessions/" + Chat + "/messages", 200, "{}");
            await driver.Route("POST", TimingPath, 200, Recorded);
            await driver.StartReview();
            Assert.False((await driver.Read(ReadForm)).GetProperty("shown").GetBoolean(), "the form shows while the review's first turn runs.");

            await driver.EndSession(Chat);
            await Type(driver, Typed);
            JsonElement ended = await driver.Read(ReadForm);
            Assert.True(ended.GetProperty("shown").GetBoolean(), "the form is not shown once the turn has ended.");
            Assert.All(Disabled(ended), off => Assert.False(off, "a field is off once the turn has ended."));
            Assert.False(ended.GetProperty("saveDisabled").GetBoolean(), "Save is off once the turn has ended.");

            await driver.Read(
                "var input = document.getElementById('followup-text'); input.value = 'Why F-007?';"
                + "document.getElementById('followup').dispatchEvent(new Event('submit', {cancelable: true}));"
                + "return JSON.stringify({ok: true});");
            await driver.Settle();
            await driver.ClearCalls();
            JsonElement running = await driver.Read(ReadForm);
            Assert.True(running.GetProperty("shown").GetBoolean(), "the form went away while the follow-up's turn runs.");
            Assert.All(Disabled(running), off => Assert.True(off, "a field is on while a turn runs."));
            Assert.True(running.GetProperty("saveDisabled").GetBoolean(), "Save is on while a turn runs.");
            Assert.Equal(Typed, Values(running));
            await Save(driver);
            Assert.Empty(await TimingCalls(driver));

            await driver.Push(Chat, 21, "turn.ended", "{\"reason\":\"end\"}");
            await driver.Settle();
            JsonElement again = await driver.Read(ReadForm);
            Assert.All(Disabled(again), off => Assert.False(off, "a field stayed off after the turn ended."));
            Assert.False(again.GetProperty("saveDisabled").GetBoolean(), "Save stayed off after the turn ended.");
        });
    }

    /// <summary>
    /// A review restored read-only from its run folder - the backend restarted - has no minutes form, where the console
    /// stays the way: after a live review's form was shown with figures typed, its chip brings the restored review back
    /// read-only with no form, and nothing was posted.
    /// </summary>
    [Fact]
    public void TheFormIsAbsentOnAReadOnlyRestore()
    {
        ReviewPageDriver.Run(
            driver =>
            {
                Labelled(driver);
                driver.Sessions.Add(ReviewPageSessionsTests.Item(RestoredChat, RestoredRun, ReviewPageDriver.ReviewedPath, 9, 0));
                driver.InitialRoutes.Add(("GET", "/sessions/" + RestoredChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat));
                driver.InitialRoutes.Add(("GET", "/reviews/" + RestoredRun, 200, Snapshot(RestoredRun, true)));
            },
            async driver =>
            {
                await driver.Settle();
                JsonElement restored = await driver.Read(ReadForm);
                Assert.Equal(ReviewPageSessionsTests.ReadOnlyReason, restored.GetProperty("readOnly").GetString());
                Assert.False(restored.GetProperty("shown").GetBoolean(), "a read-only restore shows the minutes form.");

                await Reviewed(driver);
                await Type(driver, Typed);
                Assert.True((await driver.Read(ReadForm)).GetProperty("shown").GetBoolean(), "the live review shows no form.");

                await driver.ClearCalls();
                await driver.Read(ReviewPageSessionsTests.Chip(RestoredChat));
                await driver.Settle();
                JsonElement again = await driver.Read(ReadForm);
                Assert.Equal(ReviewPageSessionsTests.ReadOnlyReason, again.GetProperty("readOnly").GetString());
                Assert.False(again.GetProperty("shown").GetBoolean(), "a read-only restore shows the minutes form.");
                Assert.Empty(await TimingCalls(driver));
            });
    }

    /// <summary>
    /// The form starts blank on every review it shows: switched to another live review of the same document, it shows
    /// blank, with no line, and never another review's figures; Save then posts that review's own figures to its own
    /// route; and back on the first review, the form is blank again.
    /// </summary>
    [Fact]
    public void AnotherReviewShowsTheFormBlank()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver);
            await driver.Route("POST", TimingPath, 200, Recorded);
            await Type(driver, Typed);
            await Save(driver);

            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200, Snapshot(OtherRun, false));
            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            JsonElement other = await driver.Read(ReadForm);
            Assert.True(other.GetProperty("shown").GetBoolean(), "the other live review shows no form.");
            Assert.All(Values(other), value => Assert.Equal(string.Empty, value));
            Assert.False(other.GetProperty("savedShown").GetBoolean(), "the other review says its minutes are recorded.");
            Assert.True(other.GetProperty("saveDisabled").GetBoolean(), "Save is on with every field blank.");

            string otherPath = "/sessions/" + OtherChat + "/timing";
            await driver.Route("POST", otherPath, 200, Recorded);
            await driver.ClearCalls();
            await Type(driver, "60", string.Empty, string.Empty, string.Empty, string.Empty, string.Empty);
            await Save(driver);
            JsonElement call = Assert.Single(await TimingCalls(driver));
            Assert.Equal(otherPath, call.GetProperty("path").GetString());
            Assert.Equal(
                "{\"baseline\":60,\"supervision\":null,\"verification\":null,\"false_alarms\":null,\"setup\":null,\"by_hand\":null}",
                call.GetProperty("body").GetString());

            await driver.Route("GET", "/sessions/" + Chat + "/snapshot", 200, Snapshot("20260923-101500-bracket-1", false));
            await driver.Read(ReviewPageSessionsTests.Chip(Chat));
            await driver.Settle();
            JsonElement back = await driver.Read(ReadForm);
            Assert.True(back.GetProperty("shown").GetBoolean(), "the first review shows no form after the switch back.");
            Assert.All(Values(back), value => Assert.Equal(string.Empty, value));
        });
    }

    /// <summary>
    /// A save's reply that lands after the engineer switched to another review belongs to the review it was pressed on: it
    /// writes no line on the review shown, whose form stays blank.
    /// </summary>
    [Fact]
    public void AReplyLandingAfterAReviewSwitchWritesNothing()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver);
            await driver.HoldRoute("POST", TimingPath, 200, Recorded);
            await Type(driver, Typed);
            await Save(driver);

            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200, Snapshot(OtherRun, false));
            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            await driver.ReleaseRoute("POST", TimingPath);

            JsonElement other = await driver.Read(ReadForm);
            Assert.True(other.GetProperty("shown").GetBoolean(), "the other live review shows no form.");
            Assert.False(other.GetProperty("savedShown").GetBoolean(), "another review's reply says this review's minutes are recorded.");
            Assert.False(other.GetProperty("refusalShown").GetBoolean(), "another review's reply wrote a refusal here.");
            Assert.All(Values(other), value => Assert.Equal(string.Empty, value));
        });
    }

    /// <summary>
    /// Every word of the form is the backend's: the heading, one field per key of `labels.timing` in the labels' own order,
    /// each labelled with its word and posted under its key, the button and the line after a save, from
    /// `labels.timing_form` - here words no page could hold, in an order the words file does not use, one of them markup,
    /// which stays characters.
    /// </summary>
    [Fact]
    public void TheFormIsLabelledFromTheWordsFile()
    {
        var words = new[]
        {
            ("by_hand", "FICT by hand <img src=x onerror=alert(1)>"),
            ("setup", "FICT setup"),
            ("false_alarms", "FICT false alarms"),
            ("verification", "FICT verification"),
            ("supervision", "FICT supervision"),
            ("baseline", "FICT baseline"),
        };

        ReviewPageDriver.Run(
            driver => driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsWith(words))),
            async driver =>
            {
                await Reviewed(driver);
                await driver.Route("POST", TimingPath, 200, Recorded);
                JsonElement form = await driver.Read(ReadForm);

                Assert.Equal("FICT minutes heading", form.GetProperty("heading").GetString());
                Assert.Equal(words.Select(word => word.Item2).ToArray(), ReviewPageDriver.Strings(form, "labels"));
                Assert.Equal(words.Select(word => word.Item1).ToArray(), ReviewPageDriver.Strings(form, "keys"));
                Assert.Equal("FICT save the minutes", form.GetProperty("save").GetString());
                Assert.Equal(0, form.GetProperty("injected").GetInt32());

                await Type(driver, "1", "2", "3", "4", "5", "6");
                await Save(driver);
                Assert.Equal(
                    "{\"by_hand\":1,\"setup\":2,\"false_alarms\":3,\"verification\":4,\"supervision\":5,\"baseline\":6}",
                    Assert.Single(await TimingCalls(driver)).GetProperty("body").GetString());
                Assert.Equal("FICT the minutes are in", (await driver.Read(ReadForm)).GetProperty("savedText").GetString());
            });
    }

    /// <summary>009 FR-030: a backend that sends no labels names no words for the form, so there is no form.</summary>
    [Fact]
    public void WithNoLabelsThereIsNoForm()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await Reviewed(driver);
            JsonElement form = await driver.Read(ReadForm);

            Assert.False(form.GetProperty("shown").GetBoolean(), "a form shows with no words to label it.");
            Assert.Empty(ReviewPageDriver.Strings(form, "keys"));
        });
    }

    /// <summary>
    /// At a docked pane's 300 px every part of the form is whole - inside the window and every box that clips it, its words
    /// wrapping rather than cut off - with no sideways page scroll: the heading, each field's label and box, Save, the line
    /// after a save, and a refusal's sentence and its Details.
    /// </summary>
    [Fact]
    public void TheFormIsWhollyVisibleAtThreeHundredPixels()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await Reviewed(driver);
            await driver.Route("POST", TimingPath, 200, Recorded);
            await Type(driver, Typed);
            await Save(driver);

            JsonElement saved = await driver.Read(ReadFormWhole);
            Assert.Equal(300, saved.GetProperty("width").GetInt32());
            Assert.Equal(15, saved.GetProperty("count").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(saved, "clipped"));
            Assert.True(saved.GetProperty("noHorizontalOverflow").GetBoolean(), saved.ToString());

            await driver.Route("POST", TimingPath, 400, InvalidTiming);
            await Save(driver);
            JsonElement refused = await driver.Read(ReadFormWhole);
            Assert.Equal(16, refused.GetProperty("count").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(refused, "clipped"));
            Assert.True(refused.GetProperty("noHorizontalOverflow").GetBoolean(), refused.ToString());
        });
    }

    // ---- driving the page ---------------------------------------------------------------------

    private static void Labelled(ReviewPageDriver driver) =>
        driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));

    /// <summary>A review started and ended with nothing found: its turn has ended, so the form shows.</summary>
    private static async Task Reviewed(ReviewPageDriver driver)
    {
        await driver.StartReview();
        await driver.EndSession(Chat);
    }

    /// <summary>Types <paramref name="figures"/> into the form's fields, in order, as the engineer would, an input event each.</summary>
    private static Task<JsonElement> Type(ReviewPageDriver driver, params string[] figures) => driver.Read(
        "var fields = document.querySelectorAll('#timing input[data-input]');"
        + "var typed = " + JsonSerializer.Serialize(figures) + ";"
        + "if (fields.length !== typed.length) { return JSON.stringify({ ok: false, error: 'the minutes form holds ' + fields.length + ' fields' }); }"
        + "for (var i = 0; i < fields.length; i++) {"
        + "  fields[i].value = typed[i]; fields[i].dispatchEvent(new Event('input', { bubbles: true }));"
        + "}"
        + "return JSON.stringify({ ok: true });");

    /// <summary>Presses Save on the minutes form and lets the page react.</summary>
    private static async Task Save(ReviewPageDriver driver)
    {
        await driver.Read(
            "var save = document.querySelector('#timing [data-action=\"save-timing\"]');"
            + "if (!save) { return JSON.stringify({ ok: false, error: 'the minutes form has no Save' }); }"
            + "save.click(); return JSON.stringify({ ok: true });");
        await driver.Settle();
    }

    /// <summary>The timing calls the page made since the calls were last cleared.</summary>
    private static async Task<JsonElement[]> TimingCalls(ReviewPageDriver driver) =>
        (await driver.Calls()).Where(call => (call.GetProperty("path").GetString() ?? string.Empty).EndsWith("/timing", StringComparison.Ordinal)).ToArray();

    private static string[] Values(JsonElement form) => ReviewPageDriver.Strings(form, "values");

    private static bool[] Disabled(JsonElement form) =>
        form.GetProperty("disabled").EnumerateArray().Select(value => value.GetBoolean()).ToArray();

    /// <summary>No text of the page - Results, the Transcript, hidden parts included - holds a typed figure or the net.</summary>
    private static void AssertNoFigureInThePagesText(JsonElement form)
    {
        string text = form.GetProperty("bodyText").GetString() ?? string.Empty;
        foreach (string figure in Typed.Where(figure => figure.Length > 1).Concat(new[] { Net }))
        {
            Assert.DoesNotContain(figure, text);
        }
    }

    /// <summary>The sample's labels with <paramref name="words"/> as `timing`, in their order, and the form's own FICT words.</summary>
    private static string LabelsWith((string Key, string Word)[] words)
    {
        JsonObject labels = JsonNode.Parse(LabelsSample.Json())!.AsObject();
        var timing = new JsonObject();
        foreach ((string key, string word) in words)
        {
            timing[key] = word;
        }

        labels["timing"] = timing;
        labels["timing_form"] = new JsonObject
        {
            ["heading"] = "FICT minutes heading",
            ["save"] = "FICT save the minutes",
            ["saved"] = "FICT the minutes are in",
        };
        return labels.ToJsonString();
    }

    /// <summary>
    /// A review's snapshot with no finding and no ranking: read-only from its run folder, or the backend's live chat, its
    /// turn ended.
    /// </summary>
    private static string Snapshot(string runId, bool readOnly) => new JsonObject
    {
        ["run_id"] = runId,
        ["read_only"] = readOnly,
        ["read_only_reason"] = readOnly ? ReviewPageSessionsTests.ReadOnlyReason : null,
        ["chat_state"] = readOnly ? null : "ended",
        ["last_seq"] = readOnly ? null : JsonValue.Create(9),
        ["document"] = JsonNode.Parse(JsonSerializer.Serialize(new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" })),
        ["findings"] = new JsonArray(),
        ["evidence_requests"] = new JsonArray(),
        ["coverage"] = new JsonArray(),
        ["ranking"] = null,
        ["not_examined"] = null,
    }.ToJsonString();

    /// <summary>
    /// The minutes form as it stands: whether it is shown, its heading, each field's label (read through its `for`), key,
    /// value and state, Save, the line after a save and a refusal, the read-only line, and every text of the page.
    /// </summary>
    private const string ReadForm = @"
var form = document.getElementById('timing');
var fields = form ? form.querySelectorAll('input[data-input]') : [];
var labels = [], keys = [], values = [], disabled = [];
for (var i = 0; i < fields.length; i++) {
  var label = fields[i].id ? form.querySelector('label[for=""' + fields[i].id + '""]') : null;
  labels.push(label ? label.textContent : null);
  keys.push(fields[i].getAttribute('data-input'));
  values.push(fields[i].value);
  disabled.push(fields[i].disabled);
}
var save = form ? form.querySelector('[data-action=""save-timing""]') : null;
var saved = form ? form.querySelector('.timing-saved') : null;
var refused = form ? form.querySelector('.timing-refused') : null;
var readOnly = document.getElementById('read-only');
return JSON.stringify({
  ok: true,
  shown: !!form && h.rendered(form),
  heading: form ? h.text(form, 'h2') : null,
  labels: labels,
  keys: keys,
  values: values,
  disabled: disabled,
  save: save ? save.textContent : null,
  saveDisabled: save ? save.disabled : null,
  savedShown: !!saved && h.rendered(saved),
  savedText: saved ? saved.textContent : null,
  refusalShown: !!refused && h.rendered(refused),
  refusalText: refused ? h.text(refused, '.plain-error-text') : null,
  refusalClass: refused ? h.text(refused, '.error-class') : null,
  refusalBad: !!refused && refused.classList.contains('bad'),
  readOnly: readOnly && !readOnly.hidden ? readOnly.textContent : null,
  bodyText: document.body.textContent,
  injected: h.injected(form)
});";

    /// <summary>
    /// Every part of the shown form at the pane's width, measured by <see cref="ReviewPageTriageTests.Whole"/>: the heading,
    /// each label and its box, Save, the line after a save when shown, and a refusal's sentence and its Details when shown.
    /// </summary>
    private const string ReadFormWhole = @"
var form = document.getElementById('timing');
var parts = [];
if (form) {
  parts.push(form.querySelector('h2'));
  var fields = form.querySelectorAll('.field');
  for (var i = 0; i < fields.length; i++) {
    parts.push(fields[i].querySelector('label'));
    parts.push(fields[i].querySelector('input'));
  }
  parts.push(form.querySelector('[data-action=""save-timing""]'));
  var saved = form.querySelector('.timing-saved');
  if (saved && !saved.hidden) { parts.push(saved); }
  var refused = form.querySelector('.timing-refused');
  if (refused && !refused.hidden) {
    parts.push(refused.querySelector('.plain-error-text'));
    parts.push(refused.querySelector('.error-fold > summary'));
  }
}
" + ReviewPageTriageTests.Whole + @"
var clipped = [];
if (!form || form.hidden) { clipped.push('the form is missing or hidden'); }
for (var j = 0; j < parts.length; j++) {
  if (!parts[j] || !whole(parts[j])) { clipped.push(parts[j] ? parts[j].textContent + ' ' + JSON.stringify(parts[j].getBoundingClientRect()) : 'a missing part'); }
}
return JSON.stringify({
  ok: true,
  width: window.innerWidth,
  count: parts.length,
  clipped: clipped,
  noHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth
});";
}
