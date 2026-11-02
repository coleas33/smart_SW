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
///
/// Roadmap hole H-g-012 (002 T322): after any refused press the card shows the record again - the
/// recorded triage pressed, or none, in place of the refused pick, and the recorded disposition's
/// sentence above the refusal's - read from the page's one memory of what is recorded, and a second
/// triage is refused with its own class and sentence, `TriageAlreadyRecorded`.
///
/// Roadmap hole H-d-008 (owner decisions 189A and 191A; 002 T328): when a check the model ran again
/// after an answer folds onto a decided finding with another status or severity, the backend clears
/// the disposition, draws the card again through the fold's `finding` event, and then sends
/// `disposition.cleared`, whose line - the backend's, naming the decision and the triage - the card
/// prints on its status line, as sent. A fold that kept the verdict carries the disposition in its
/// `finding` event, and the card shows it as any finding sent decided. A replay leaves Results as the
/// snapshot holds them.
///
/// Owner decision 187A (002 T334): a pass - a `checked_within_scope` finding, in the Checked, no issue fold - takes
/// no triage but `wrong`, the miss. Its fold's row holds that one button, worded as the backend words a pass's miss
/// (`labels.pass_triage`), or the token itself from a backend that sends no labels; picked, it travels with the
/// decision as any outcome does. The rule is the backend's: the page draws the one button and refuses nothing.
///
/// Owner decision 193A (002 T342): the cleared line comes back. Both snapshots name each undecided finding's line under
/// `cleared`, so a reload, a review switch and a read-only restore show it again; the page keeps it in the finding's
/// entry beside the disposition, shows it above any status a press or Show writes, keeps it on a card drawn again while
/// undecided, and drops it when a decision is recorded. A fold's withdrawal of the re-run's own id (`folded_into`) drops
/// its card, so Results hold the cards the session holds.
///
/// The triage tally (002 T348; the owner's request, cycle 7): how the triage stands - `report.md`'s By triage and misses
/// lines - in a section of its own under the summary, as the backend sends it beside the summary, in a decision's reply and
/// in the `disposition` and `disposition.cleared` events. The page shows the last it was sent, none while it was sent none,
/// counts nothing and offers no control; a reply that lands after a review switch writes nothing, and a snapshot's tally is
/// its summary's, never a cleared line's.
///
/// Roadmap hole H-c-008 (002 T354): the card says it has no triage yet. Until a flagged finding's triage is recorded, its
/// card's head says so under the title, read with the fold shut, in the backend's words for where its record stands
/// (`labels.no_triage`, keyed by the decision recorded, `undecided` for none), each naming the repair. `showDisposition` draws
/// it again from each recorded decision, so a pick alone leaves it; a pass takes no triage but the miss and says nothing; a
/// cleared decision brings it back; and with no labels the head is its line and its title, as before (FR-030).
/// </summary>
public sealed class ReviewPageTriageTests
{
    private const string Chat = "chat-1";

    private const string Engineer = "FICT-ENG";

    private const string RecordedAt = "2026-11-01T09:00:00+00:00";

    private const string RestoredChat = "chat-restored";

    private const string RestoredRun = "20261101-090000-bracket-restored";

    /// <summary>An earlier review of the same document, kept by the host and live on the backend.</summary>
    private const string OtherChat = "chat-2";

    private const string OtherRun = "20261101-083000-bracket-2";

    private const string IllegalTransition =
        "{\"error_class\":\"IllegalTransition\",\"message\":\"FICT finding F-001 already has a terminal disposition ('accepted'); it cannot be changed\",\"retryable\":false}";

    private const string TriageAlreadyRecordedMessage =
        "FICT finding F-001 already has a terminal disposition ('accepted') with its triage ('already_known'); a triage is recorded once and cannot be changed";

    /// <summary>The backend's refusal of a second triage (roadmap hole H-g-012), as the route sends it.</summary>
    private static readonly string TriageAlreadyRecorded = Refusal("TriageAlreadyRecorded", TriageAlreadyRecordedMessage, false);

    /// <summary>A decision refused while a turn runs, which says nothing of the record.</summary>
    private static readonly string TurnRunning = Refusal("TurnRunning", "a turn is already running for chat-1", true);

    /// <summary>
    /// The backend's line for an Accept recorded as `already_known` that a re-run after an answer cleared (roadmap hole
    /// H-d-008): the words file's `rerun.cleared_with_triage`, filled as the runner fills it and sent as
    /// `disposition.cleared`'s `reason`. The page prints it as sent, with labels or without.
    /// </summary>
    private const string ClearedLine =
        "The check ran again after your answer and its verdict changed, so your Accept (real but already known) was cleared. Decide again.";

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
    ///
    /// *Changed 2026-11-01 on purpose (002 T322; roadmap hole H-g-012):* the second triage is
    /// scripted as the backend now refuses it, `409 TriageAlreadyRecorded`, where it was
    /// `IllegalTransition`; and after the refusal the late triage, `already known`, is asserted
    /// pressed again, where nothing checked which button was pressed, and the recorded disposition's
    /// sentence shown above the refusal, where the refusal replaced it and the fact asserted no
    /// "Disposition:" on the card.
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

            await driver.Route("POST", DispositionPath("F-001"), 409, TriageAlreadyRecorded);
            await driver.ClearCalls();
            await Press(driver, "F-001", "wrong");
            await Decide(driver, "F-001", "accept");
            Assert.Equal(
                "decision=accepted, note=FICT second note, triage=wrong",
                Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal("card-status bad", refused.GetProperty("statusClass").GetString());
            Assert.Equal("TriageAlreadyRecorded", refused.GetProperty("refusalClass").GetString());
            Assert.Equal(new[] { "already_known" }, Pressed(refused));
            Assert.Equal(Sentence("accepted", "already_known", "FICT first note"), refused.GetProperty("record").GetString());
            Assert.Equal(LabelsSample.TriageAlreadyRecorded, refused.GetProperty("refusal").GetString());
        });
    }

    /// <summary>
    /// Roadmap hole H-g-012: a finding the stream sends accepted with `already known`; `wrong` is picked and
    /// Accept pressed, and the backend refuses the second triage (a scripted `409 TriageAlreadyRecorded`). The card
    /// shows the record again: `already known` pressed and `wrong` let go, the recorded disposition's sentence above
    /// the refusal's, which is the words' sentence for the class, and the class in the refusal's fold.
    /// </summary>
    [Fact]
    public void ARefusedTriageShowsTheRecordedTriageAgain()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Finding("F-001", Disposition("accepted", "FICT first note", "already_known")));
            await driver.Route("POST", DispositionPath("F-001"), 409, TriageAlreadyRecorded);
            await Press(driver, "F-001", "wrong");
            Assert.Equal(new[] { "wrong" }, Pressed(await driver.Read(ReadCard("F-001"))));
            await driver.ClearCalls();

            await Decide(driver, "F-001", "accept");

            Assert.Equal("decision=accepted, note=, triage=wrong", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "already_known" }, Pressed(refused));
            Assert.Equal(Sentence("accepted", "already_known", "FICT first note"), refused.GetProperty("record").GetString());
            Assert.Equal(LabelsSample.TriageAlreadyRecorded, refused.GetProperty("refusal").GetString());
            Assert.Equal("TriageAlreadyRecorded", refused.GetProperty("refusalClass").GetString());
            Assert.Equal("card-status bad", refused.GetProperty("statusClass").GetString());
            Assert.True(refused.GetProperty("recordFirst").GetBoolean(), "the recorded sentence is not above the refusal.");
        });
    }

    /// <summary>
    /// Roadmap hole H-g-012: any refused decision leaves the card as recorded, the page deciding nothing. F-001's
    /// Accept with `true but not worth flagging` arrives as a `disposition` event; `wrong` picked and Reject pressed
    /// is refused (a scripted `409 IllegalTransition`): the recorded triage is pressed again and its sentence shown
    /// above the refusal. F-002 is undecided; `new and real` picked and Defer pressed is refused (`409 TurnRunning`):
    /// the pick goes back to none, and the refusal is shown alone, with no disposition sentence.
    /// </summary>
    [Fact]
    public void ARefusedDecisionPressesTheRecordedTriageBackToo()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "finding", Finding("F-002"));
            await driver.Push(Chat, 3, "disposition", DispositionEvent("F-001", Disposition("accepted", "FICT intended", "not_worth_flagging")));
            await driver.EndSession(Chat);
            await driver.Route("POST", DispositionPath("F-001"), 409, IllegalTransition);
            await driver.Route("POST", DispositionPath("F-002"), 409, TurnRunning);

            await Press(driver, "F-001", "wrong");
            await Decide(driver, "F-001", "reject");
            await Press(driver, "F-002", "new_and_real");
            await Decide(driver, "F-002", "defer");

            JsonElement decided = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "not_worth_flagging" }, Pressed(decided));
            Assert.Equal(Sentence("accepted", "not_worth_flagging", "FICT intended"), decided.GetProperty("record").GetString());
            Assert.Equal("IllegalTransition", decided.GetProperty("refusalClass").GetString());
            Assert.True(decided.GetProperty("recordFirst").GetBoolean(), "the recorded sentence is not above the refusal.");

            JsonElement undecided = await driver.Read(ReadCard("F-002"));
            Assert.Empty(Pressed(undecided));
            Assert.Equal(JsonValueKind.Null, undecided.GetProperty("record").ValueKind);
            Assert.DoesNotContain("Disposition:", undecided.GetProperty("status").GetString()!);
            Assert.Equal(LabelsSample.TurnRunning, undecided.GetProperty("refusal").GetString());
            Assert.Equal("TurnRunning", undecided.GetProperty("refusalClass").GetString());
        });
    }

    /// <summary>
    /// FR-030 with H-g-012: with no labels a refused press prints the class and the message, as every card's refusal
    /// does with no labels, after the recorded disposition's sentence, which prints the triage's token; and the
    /// recorded triage is pressed again.
    /// </summary>
    [Fact]
    public void WithNoLabelsARefusedPressShowsTheRecordAndTheClassAndMessage()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await Reviewed(driver, Finding("F-001", Disposition("accepted", string.Empty, "already_known")));
            await driver.Route("POST", DispositionPath("F-001"), 409, TriageAlreadyRecorded);
            await Press(driver, "F-001", "wrong");
            await Decide(driver, "F-001", "accept");

            JsonElement refused = await driver.Read(ReadCard("F-001"));
            string recorded = "Disposition: accepted (already_known) by " + Engineer + " at " + RecordedAt;
            Assert.Equal(new[] { "already_known" }, Pressed(refused));
            Assert.Equal(recorded, refused.GetProperty("record").GetString());
            Assert.Equal(recorded + "TriageAlreadyRecorded: " + TriageAlreadyRecordedMessage, refused.GetProperty("status").GetString());
            Assert.Equal("card-status bad", refused.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// H-g-012 at a docked pane's 300 px: after a refused triage the recorded disposition's sentence, the refusal's
    /// sentence, its Details fold and every triage button are whole - inside the window and every box that clips
    /// them, their words inside them - with no sideways page scroll, as
    /// <see cref="EveryTriageButtonIsWhollyVisibleAtThreeHundredPixels"/> holds the triage row.
    /// </summary>
    [Fact]
    public void ARefusedPressIsWhollyVisibleAtThreeHundredPixels()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await Reviewed(driver, Finding("F-001", Disposition("accepted", "FICT first note", "already_known")));
            await driver.Route("POST", DispositionPath("F-001"), 409, TriageAlreadyRecorded);
            await Press(driver, "F-001", "wrong");
            await Decide(driver, "F-001", "accept");

            JsonElement measured = await driver.Read(ReadRefusalWhole("F-001"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.True(measured.GetProperty("foldOpen").GetBoolean(), "the finding's fold did not open.");
            Assert.Equal(7, measured.GetProperty("count").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    /// <summary>
    /// H-g-012, on the Tier 2 review (2026-11-01): a decision's reply that lands after the engineer switched reviews
    /// belongs to the review it was pressed on. Review chat-1's F-001 is accepted with `wrong` and its reply held;
    /// the engineer switches to review chat-2, whose F-001 was accepted with `already known`; the held reply then
    /// lands. A press on chat-2's F-001 that the backend refuses shows chat-2's record again - `already known`
    /// pressed and chat-2's own `Disposition: ...` sentence - and nothing of chat-1's.
    /// </summary>
    [Fact]
    public void AReplyLandingAfterAReviewSwitchKeepsTheShownReviewsRecord()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-001"));
            await driver.HoldRoute("POST", DispositionPath("F-001"), 200,
                Finding("F-001", Disposition("accepted", "FICT note of the first review", "wrong")));
            await Press(driver, "F-001", "wrong");
            await Decide(driver, "F-001", "accept");

            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200,
                Snapshot(OtherRun, false, Finding("F-001", Disposition("accepted", "FICT note of the second review", "already_known"))));
            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            await driver.ReleaseRoute("POST", DispositionPath("F-001"));

            string recorded = Sentence("accepted", "already_known", "FICT note of the second review");
            JsonElement shown = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "already_known" }, Pressed(shown));
            Assert.Equal(recorded, shown.GetProperty("status").GetString());

            string otherPath = "/sessions/" + OtherChat + "/findings/F-001/disposition";
            await driver.Route("POST", otherPath, 409, TriageAlreadyRecorded);
            await driver.ClearCalls();
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "accept");

            Assert.Equal(otherPath, Assert.Single(await DispositionCalls(driver)).GetProperty("path").GetString());
            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "already_known" }, Pressed(refused));
            Assert.Equal(recorded, refused.GetProperty("record").GetString());
            Assert.Equal("TriageAlreadyRecorded", refused.GetProperty("refusalClass").GetString());
        });
    }

    /// <summary>
    /// Roadmap hole H-d-008 (owner decisions 189A and 191A): F-001 is accepted with `already known`; after an answer the
    /// model ran its check again and the verdict changed, so the backend folded the re-run onto F-001 with no disposition
    /// and then sent `disposition.cleared`. The card shows the new verdict undecided - no `Disposition:` sentence, its
    /// triage row released - and the backend's line on its status line, as sent, in a class of its own; and the event is
    /// read, so the Transcript says nothing of an event it could not read.
    /// </summary>
    [Fact]
    public void ACardWhoseDecisionARerunClearedSaysSoAndIsUndecided()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await DecidedThenFolded(driver, true);

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ClearedLine, card.GetProperty("status").GetString());
            Assert.Equal("card-status cleared", card.GetProperty("statusClass").GetString());
            Assert.DoesNotContain("could not read", (await driver.Read(ReadTranscript)).GetProperty("text").GetString()!);
        });
    }

    /// <summary>
    /// H-d-008: a re-run that kept the status and the severity keeps the whole disposition, so the fold's `finding` event
    /// carries it and the card shows it - its sentence and `already known` pressed - with no line.
    /// </summary>
    [Fact]
    public void ARerunThatKeptItsVerdictShowsItsDispositionAndPressedTriage()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await DecidedThenFolded(driver, false);

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "already_known" }, Pressed(card));
            Assert.Equal(Sentence("accepted", "already_known", "FICT intended"), card.GetProperty("status").GetString());
            Assert.Equal("card-status decided", card.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// H-d-008 at a docked pane's 300 px: the cleared decision's line and every triage button are whole - inside the
    /// window and every box that clips them, their words inside them - with no sideways page scroll.
    /// </summary>
    [Fact]
    public void AClearedDecisionsLineIsWhollyVisibleAtThreeHundredPixels()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await DecidedThenFolded(driver, true);

            JsonElement measured = await driver.Read(ReadClearedWhole("F-001"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.True(measured.GetProperty("foldOpen").GetBoolean(), "the finding's fold did not open.");
            Assert.Equal(5, measured.GetProperty("count").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    /// <summary>
    /// FR-030 with H-d-008: with no labels the card prints the backend's line as sent - the backend words it, so it needs
    /// none - with the triage buttons printing their tokens and none pressed.
    /// </summary>
    [Fact]
    public void WithNoLabelsAClearedCardShowsTheBackendsLine()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await DecidedThenFolded(driver, true);

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(card, "words"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ClearedLine, card.GetProperty("status").GetString());
            Assert.Equal("card-status cleared", card.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// H-d-008: a review restored from its live chat shows its snapshot, in which the cleared finding is undecided, and its
    /// Transcript, chosen, replays the stream: the `disposition.cleared` there is read and changes nothing in Results, as
    /// a replayed `disposition` changes nothing - the card stays as its snapshot holds it, with no line - and the
    /// Transcript says nothing of an event it could not read.
    /// </summary>
    [Fact]
    public void AReplayedClearedDecisionLeavesTheRestoredCardAsItsSnapshotHoldsIt()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200,
                Snapshot(OtherRun, false, Finding("F-001", null, "suspected", "low")));
            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();

            await driver.Click("view-transcript");
            await driver.Push(OtherChat, 1, "finding", Finding("F-001"));
            await driver.Push(OtherChat, 2, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
            await driver.Push(OtherChat, 3, "finding", Finding("F-001", null, "suspected", "low"));
            await driver.Push(OtherChat, 4, "disposition.cleared", Cleared("F-001", AcceptedAlreadyKnown()));
            await driver.Settle();

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(string.Empty, card.GetProperty("status").GetString());
            Assert.Equal("card-status", card.GetProperty("statusClass").GetString());
            JsonElement transcript = await driver.Read(ReadTranscript);
            Assert.Equal(2, ReviewPageDriver.Strings(transcript, "markers").Count(marker => marker.StartsWith("F-001 recorded:", StringComparison.Ordinal)));
            Assert.DoesNotContain("could not read", transcript.GetProperty("text").GetString()!);
        });
    }

    /// <summary>
    /// Owner decision 193A (002 T342): a reload brings the line back. F-001's decision was cleared live and the page is
    /// loaded again; the backend still holds the chat, and its snapshot names the line under `cleared`, the
    /// `disposition.cleared` body its stream holds. The restored card shows it on its status line, in its class, with the
    /// triage row released.
    /// </summary>
    [Fact]
    public void AClearedLineComesBackAfterAReload()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await DecidedThenFolded(driver, true);
            driver.InitialRoutes.Add(("GET", "/sessions/" + Chat + "/snapshot", 200,
                Snapshot("20260923-101500-bracket-1", false, new[] { Cleared("F-001", AcceptedAlreadyKnown()) }, Finding("F-001", null, "suspected", "low"))));

            await driver.Reload();
            await driver.Settle();

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ClearedLine, card.GetProperty("status").GetString());
            Assert.Equal("card-status cleared", card.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// 193A: a review switch brings the line back. The engineer leaves for review chat-1 and chooses chat-2's chip; its
    /// live snapshot names F-001's line, and the card shows it, released, while chat-2's undecided F-002 shows none.
    /// </summary>
    [Fact]
    public void AClearedLineComesBackAfterAReviewSwitch()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200,
                Snapshot(OtherRun, false, new[] { Cleared("F-001", AcceptedAlreadyKnown()) }, Finding("F-001", null, "suspected", "low"), Finding("F-002")));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ClearedLine, card.GetProperty("status").GetString());
            Assert.Equal("card-status cleared", card.GetProperty("statusClass").GetString());
            JsonElement other = await driver.Read(ReadCard("F-002"));
            Assert.Equal(string.Empty, other.GetProperty("status").GetString());
            Assert.Equal("card-status", other.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// 193A: a backend restart and a read-only restore bring the line back. The backend no longer holds chat-2
    /// (`404 UnknownChat`), so the page restores it from its run folder (`GET /reviews/{run_id}`), read-only; that
    /// snapshot names F-001's line too, and the card shows it with its decision and triage controls off.
    /// </summary>
    [Fact]
    public void AClearedLineComesBackInAReadOnlyRestore()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 404,
                Refusal("UnknownChat", "no chat " + OtherChat, false));
            await driver.Route("GET", "/reviews/" + OtherRun, 200,
                Snapshot(OtherRun, true, new[] { Cleared("F-001", AcceptedAlreadyKnown()) }, Finding("F-001", null, "suspected", "low")));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ClearedLine, card.GetProperty("status").GetString());
            Assert.Equal("card-status cleared", card.GetProperty("statusClass").GetString());
            Assert.All(Disabled(card), Assert.True);
        });
    }

    /// <summary>
    /// 193A and the backlog's cycle 3 section: a press refused while a turn still runs (`409 TurnRunning`, the explanation
    /// pass) writes the refusal on the card's status line, and the cleared line stays above it - read from the finding's
    /// entry, where the page keeps it beside the disposition - with the picked triage let go, since nothing is recorded.
    /// </summary>
    [Fact]
    public void ARefusedPressShowsTheClearedLineAboveTheRefusal()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await DecidedThenFolded(driver, true);
            await driver.Route("POST", DispositionPath("F-001"), 409, TurnRunning);
            await Press(driver, "F-001", "new_and_real");

            await Decide(driver, "F-001", "reject");

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ClearedLine, card.GetProperty("cleared").GetString());
            Assert.Equal(JsonValueKind.Null, card.GetProperty("record").ValueKind);
            Assert.Equal(LabelsSample.TurnRunning, card.GetProperty("refusal").GetString());
            Assert.Equal("TurnRunning", card.GetProperty("refusalClass").GetString());
            Assert.Equal("card-status bad", card.GetProperty("statusClass").GetString());
            Assert.True(card.GetProperty("clearedFirst").GetBoolean(), "the cleared line is not above the refusal.");
        });
    }

    /// <summary>
    /// 193A and the backlog's cycle 3 section: Show in SOLIDWORKS writes its own status - "Selecting in SOLIDWORKS...",
    /// then the host's answer - and the cleared line stays above each, so the engineer still reads that the decision is to
    /// be made again.
    /// </summary>
    [Fact]
    public void ShowInSolidWorksShowsTheClearedLineAboveItsStatus()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Referenced(Finding("F-001")));
            await driver.Push(Chat, 2, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 3, "finding", Referenced(Finding("F-001", null, "suspected", "low")));
            await driver.Push(Chat, 4, "disposition.cleared", Cleared("F-001", AcceptedAlreadyKnown()));
            await driver.EndSession(Chat);

            await driver.Read(
                "document.querySelector('.card.finding[data-finding-id=\"F-001\"] [data-action=\"show\"]').click();"
                + "return JSON.stringify({ok: true});");
            await driver.Settle();

            JsonElement shown = Assert.Single(driver.Posted("entity.show"));
            Assert.Equal("FICT-REF-0001", shown.GetProperty("persist_ref").GetString());
            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Equal(ClearedLine, card.GetProperty("cleared").GetString());
            Assert.Equal(ClearedLine + "Selected Pin-A-1.", card.GetProperty("status").GetString());
            Assert.Equal("card-status", card.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// 193A: the line stands while the finding is undecided, as a snapshot taken then would show it. A later answer's
    /// re-run draws the card again with no disposition, and the line is still there; then a decision arrives, and the card
    /// shows its sentence alone; and a press refused after it shows the record above the refusal, with no line.
    /// </summary>
    [Fact]
    public void ARedrawnCardKeepsItsClearedLineUntilADecision()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 3, "finding", Finding("F-001", null, "suspected", "low"));
            await driver.Push(Chat, 4, "disposition.cleared", Cleared("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 5, "finding", Finding("F-001", null, "unresolved", "low"));
            await driver.Settle();

            JsonElement redrawn = await driver.Read(ReadCard("F-001"));
            Assert.Equal(ClearedLine, redrawn.GetProperty("status").GetString());
            Assert.Equal("card-status cleared", redrawn.GetProperty("statusClass").GetString());

            Dictionary<string, object?> decided = Disposition("rejected", "FICT decided again", null);
            await driver.Push(Chat, 6, "disposition", DispositionEvent("F-001", decided));
            await driver.EndSession(Chat);
            await driver.Route("POST", DispositionPath("F-001"), 409, IllegalTransition);
            await Decide(driver, "F-001", "accept");

            string sentence = "Disposition: rejected by " + Engineer + " at " + RecordedAt + " - FICT decided again";
            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal(JsonValueKind.Null, refused.GetProperty("cleared").ValueKind);
            Assert.Equal(sentence, refused.GetProperty("record").GetString());
            Assert.Equal("IllegalTransition", refused.GetProperty("refusalClass").GetString());
        });
    }

    /// <summary>
    /// The backlog's cycle 3 section (FR-031, the stream agrees with the fold): the resumed turn's re-run is first
    /// announced under its own id, F-002, and the fold withdraws it, naming F-001 as the id it took, before announcing F-001
    /// again. Results then hold F-001's card alone, with the line; the Transcript says where F-002 went; and the page reads
    /// no ranking for the fold's withdrawal, which moved no verdict out of the review - the session's end reads it once.
    /// </summary>
    [Fact]
    public void AFoldLeavesNoStrayCardAndReadsNoRanking()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 3, "finding", Finding("F-002", null, "suspected", "low"));
            await driver.Settle();
            Assert.Equal(new[] { "F-001", "F-002" }, ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));
            await driver.ClearCalls();

            await driver.Push(Chat, 4, "finding.withdrawn", Folded("F-002", "F-001"));
            await driver.Push(Chat, 5, "finding", Finding("F-001", null, "suspected", "low"));
            await driver.Push(Chat, 6, "disposition.cleared", Cleared("F-001", AcceptedAlreadyKnown()));
            await driver.Settle();

            Assert.Equal(new[] { "F-001" }, ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("path").GetString()!.EndsWith("/attention", StringComparison.Ordinal));
            Assert.Equal(ClearedLine, (await driver.Read(ReadCard("F-001"))).GetProperty("status").GetString());
            Assert.Contains(
                "F-002 withdrawn: a second verdict on what F-001 judges, shown as F-001",
                ReviewPageDriver.Strings(await driver.Read(ReadTranscript), "markers"));
        });
    }

    /// <summary>
    /// 193A at a docked pane's 300 px, the card where a real turn leaves it: the session's end reads the ranking, which puts
    /// F-007's card in its grouped row, shut. After a refused press, with the row and the fold opened, the cleared line,
    /// the refusal's sentence, its Details fold and every triage button are whole - inside the window and every box that
    /// clips them, their words inside them - with no sideways page scroll.
    /// </summary>
    [Fact]
    public void AClearedLineAboveARefusalIsWhollyVisibleAtThreeHundredPixelsInItsRow()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await driver.RouteAttention(Chat, SummarySample.Json());
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-007"));
            await driver.Push(Chat, 2, "disposition", DispositionEvent("F-007", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 3, "finding", Finding("F-007", null, "suspected", "low"));
            await driver.Push(Chat, 4, "disposition.cleared", Cleared("F-007", AcceptedAlreadyKnown()));
            await driver.EndSession(Chat);
            JsonElement placed = await driver.Read(ReadRow("F-007"));
            Assert.True(placed.GetProperty("inRow").GetBoolean(), "F-007's card is not in its grouped row.");
            Assert.False(placed.GetProperty("rowOpen").GetBoolean(), "F-007's row is open before the press.");
            await driver.Route("POST", DispositionPath("F-007"), 409, TurnRunning);

            await Decide(driver, "F-007", "accept");

            JsonElement measured = await driver.Read(ReadClearedRefusalWhole("F-007"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.True(measured.GetProperty("foldOpen").GetBoolean(), "the finding's fold did not open.");
            Assert.Equal(7, measured.GetProperty("count").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    /// <summary>
    /// FR-030 with 193A: with no labels a press refused on a cleared card prints the class and the message, as every card's
    /// refusal does with no labels, after the backend's line, which needs none.
    /// </summary>
    [Fact]
    public void WithNoLabelsARefusedPressShowsTheClearedLineAndTheClassAndMessage()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await DecidedThenFolded(driver, true);
            await driver.Route("POST", DispositionPath("F-001"), 409, TurnRunning);

            await Decide(driver, "F-001", "accept");

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ClearedLine, card.GetProperty("cleared").GetString());
            Assert.Equal(ClearedLine + "TurnRunning: a turn is already running for chat-1", card.GetProperty("status").GetString());
            Assert.Equal("card-status bad", card.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// Owner decision 187A: a pass's fold holds one triage button, `wrong`, worded as the backend words a pass's miss, in
    /// the one row a flagged finding's four stand in - before the tools row and outside the decisions - with none
    /// pressed; and a flagged finding beside it still offers the four.
    /// </summary>
    [Fact]
    public void APassOffersTheMissAloneWordedAsOne()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Pass("F-001"), Finding("F-002"));
            JsonElement pass = await driver.Read(ReadCard("F-001"));
            JsonElement fold = await driver.Read(ReadFold("F-001"));

            Assert.Equal(new[] { "wrong" }, ReviewPageDriver.Strings(pass, "tokens"));
            Assert.Equal(new[] { LabelsSample.Miss }, ReviewPageDriver.Strings(pass, "words"));
            Assert.Equal(new[] { "false" }, ReviewPageDriver.Strings(pass, "ariaPressed"));
            Assert.Equal(1, fold.GetProperty("rows").GetInt32());
            Assert.Equal("group", fold.GetProperty("rowRole").GetString());
            Assert.Equal("Triage", fold.GetProperty("rowLabel").GetString());
            Assert.True(fold.GetProperty("rowInFold").GetBoolean(), "the miss is not in the pass's fold.");
            Assert.True(fold.GetProperty("rowBeforeTools").GetBoolean(), "the miss is not before the tools row.");
            Assert.Equal(0, fold.GetProperty("inSeg").GetInt32());
            Assert.Equal(new[] { "accept", "reject", "defer" }, ReviewPageDriver.Strings(fold, "segActions"));
            Assert.Equal(ContractTriages(), ReviewPageDriver.Strings(await driver.Read(ReadCard("F-002")), "tokens"));
        });
    }

    /// <summary>
    /// 187A: the miss is picked and sent as any outcome is. Pressed on a pass it picks `wrong` and sends nothing; Reject
    /// pressed then posts `triage=wrong` with the note, and the reply - the backend records a pass's miss - is shown with
    /// the miss pressed and the card's sentence naming its triage.
    /// </summary>
    [Fact]
    public void ThePassesMissTravelsWithTheDecision()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Pass("F-001"));
            await driver.Route("POST", DispositionPath("F-001"), 200, Pass("F-001", Disposition("rejected", "FICT the check missed it", "wrong")));
            await driver.ClearCalls();

            await Press(driver, "F-001", "wrong");
            JsonElement picked = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { LabelsSample.Miss }, ReviewPageDriver.Strings(picked, "words"));
            Assert.Equal(new[] { "wrong" }, Pressed(picked));
            Assert.Empty(await driver.Calls());

            await Note(driver, "F-001", "FICT the check missed it");
            await Decide(driver, "F-001", "reject");

            Assert.Equal("decision=rejected, note=FICT the check missed it, triage=wrong", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement decided = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "wrong" }, Pressed(decided));
            Assert.Equal(Sentence("rejected", "wrong", "FICT the check missed it"), decided.GetProperty("status").GetString());
            Assert.Equal("card-status decided", decided.GetProperty("statusClass").GetString());
        });
    }

    /// <summary>
    /// 187A at a docked pane's 300 px: a pass's one triage button is whole - inside the window and every box that clips
    /// it, its words inside it - with no sideways page scroll.
    /// </summary>
    [Fact]
    public void APassesMissIsWhollyVisibleAtThreeHundredPixels()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await Reviewed(driver, Pass("F-001"));

            JsonElement measured = await driver.Read(ReadWhole("F-001"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.Equal(1, measured.GetProperty("count").GetInt32());
            Assert.True(measured.GetProperty("foldOpen").GetBoolean(), "the finding's fold did not open.");
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    /// <summary>FR-030 with 187A: an older backend sends no labels, and a pass's one button prints its token, `wrong`.</summary>
    [Fact]
    public void WithNoLabelsAPassesMissPrintsItsToken()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await Reviewed(driver, Pass("F-001"));

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "wrong" }, ReviewPageDriver.Strings(card, "tokens"));
            Assert.Equal(new[] { "wrong" }, ReviewPageDriver.Strings(card, "words"));
            Assert.Empty(Pressed(card));
        });
    }

    // ---- the triage tally (002 T348; the owner's request, cycle 7) ----------------------------

    /// <summary>
    /// A review a re-run carried F-001's Accept as `already known` into ends, and its summary's tally is shown under the
    /// summary, its two lines as sent. Each press's reply carries the review's tally and the page shows it as sent: a refused
    /// press leaves it as it was, F-002's `wrong` brings "not recorded" to 0, and the pass's miss is counted apart. Nothing in
    /// it is a control.
    /// </summary>
    [Fact]
    public void TheTallyFollowsEachPressUntilNoneIsLeftNotRecorded()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            JsonObject carried = Tally(0, 1, 0, 0, 1, 0);
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 2, "finding", Finding("F-002"));
            await driver.Push(Chat, 3, "finding", Pass("F-003"));
            await driver.RouteAttention(Chat, SummarySample.Json(summary => summary["triage_tally"] = carried.DeepClone()));
            await driver.EndSession(Chat);
            JsonElement ended = await driver.Read(ReadTally);
            Assert.True(ended.GetProperty("shown").GetBoolean(), "the summary's tally is not shown at the session's end.");
            Assert.Equal(Lines(carried), ReviewPageDriver.Strings(ended, "lines"));

            await driver.Route("POST", DispositionPath("F-002"), 409, TurnRunning);
            await Press(driver, "F-002", "wrong");
            await Decide(driver, "F-002", "reject");
            Assert.Equal(Lines(carried), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));

            JsonObject judged = Tally(0, 1, 1, 0, 0, 0);
            await driver.Route("POST", DispositionPath("F-002"), 200,
                WithTally(Finding("F-002", Disposition("rejected", string.Empty, "wrong")), judged));
            await Press(driver, "F-002", "wrong");
            await Decide(driver, "F-002", "reject");
            string[] none = ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines");
            Assert.Equal(Lines(judged), none);
            Assert.EndsWith("not recorded: 0", none[0], StringComparison.Ordinal);

            JsonObject missed = Tally(0, 1, 1, 0, 0, 1);
            await driver.Route("POST", DispositionPath("F-003"), 200,
                WithTally(Pass("F-003", Disposition("rejected", string.Empty, "wrong")), missed));
            await Press(driver, "F-003", "wrong");
            await Decide(driver, "F-003", "reject");
            JsonElement last = await driver.Read(ReadTally);
            Assert.Equal(Lines(missed), ReviewPageDriver.Strings(last, "lines"));
            Assert.Equal(0, last.GetProperty("controls").GetInt32());
        });
    }

    /// <summary>
    /// The stream's decisions and cleared notices carry the review's tally, and the page shows the last it was sent as it
    /// arrives: F-001's Accept, F-002's Reject, then F-001's decision cleared by a re-run, its notice carrying the tally the
    /// clear left; then F-002's cleared too, the last triage, its notice carrying none, and the tally goes - and the
    /// session's end, whose summary carries none, leaves it gone.
    /// </summary>
    [Fact]
    public void TheTallyFollowsTheStreamsDispositionsAndClearedNotices()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            JsonObject accepted = Tally(0, 1, 0, 0, 1, 0);
            JsonObject rejected = Tally(0, 1, 1, 0, 0, 0);
            JsonObject cleared = Tally(0, 0, 1, 0, 1, 0);
            Dictionary<string, object?> missed = Disposition("rejected", "FICT missed", "wrong");
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "finding", Finding("F-002"));
            await driver.Push(Chat, 3, "disposition", WithTally(DispositionEvent("F-001", AcceptedAlreadyKnown()), accepted));
            await driver.Settle();
            Assert.Equal(Lines(accepted), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));

            await driver.Push(Chat, 4, "disposition", WithTally(DispositionEvent("F-002", missed), rejected));
            await driver.Settle();
            Assert.Equal(Lines(rejected), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));

            await driver.Push(Chat, 5, "finding", Finding("F-001", null, "suspected", "low"));
            await driver.Push(Chat, 6, "disposition.cleared", WithTally(Cleared("F-001", AcceptedAlreadyKnown()), cleared));
            await driver.Settle();
            Assert.Equal(Lines(cleared), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));
            Assert.Equal(ClearedLine, (await driver.Read(ReadCard("F-001"))).GetProperty("status").GetString());

            await driver.Push(Chat, 7, "finding", Finding("F-002", null, "suspected", "low"));
            await driver.Push(Chat, 8, "disposition.cleared", Cleared("F-002", missed));
            await driver.Settle();
            JsonElement gone = await driver.Read(ReadTally);
            Assert.False(gone.GetProperty("shown").GetBoolean(), "a tally is shown after the last triage was cleared.");
            Assert.Empty(ReviewPageDriver.Strings(gone, "lines"));

            await driver.RouteAttention(Chat, SummarySample.Json());
            await driver.EndSession(Chat);
            Assert.False((await driver.Read(ReadTally)).GetProperty("shown").GetBoolean(), "a summary with no tally showed one.");
        });
    }

    /// <summary>
    /// A summary that carries no tally hides the one shown (cycle 7's Tier 2 review), with nothing else to hide it first - no
    /// cleared notice, no review switch: F-001's Reject as `wrong` is the review's one triage, and its tally is shown; then an
    /// answer's regrade withdraws F-001, a bought part, and the ranking the page reads again carries none, as the backend
    /// sends none while no finding records a triage.
    /// </summary>
    [Fact]
    public void ARankingReadAgainWithNoTallyHidesTheShownOne()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            JsonObject judged = Tally(0, 0, 1, 0, 1, 0);
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "finding", Finding("F-002"));
            await driver.Push(Chat, 3, "disposition",
                WithTally(DispositionEvent("F-001", Disposition("rejected", "FICT missed", "wrong")), judged));
            await driver.Settle();
            Assert.Equal(Lines(judged), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));

            await driver.RouteAttention(Chat, SummarySample.Json());
            await driver.Push(Chat, 4, "finding.withdrawn",
                JsonSerializer.Serialize(new { finding_id = "F-001", reason = "bought part (your answer to ER-001)" }));
            await driver.Settle();
            JsonElement gone = await driver.Read(ReadTally);
            Assert.False(gone.GetProperty("shown").GetBoolean(), "a tally is shown after a ranking that carries none: " + gone);
            Assert.Empty(ReviewPageDriver.Strings(gone, "lines"));
            Assert.DoesNotContain("F-001", ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));
        });
    }

    /// <summary>
    /// A review switch and a reload bring the tally back from the snapshot's summary. Chat-2's live snapshot shows its
    /// summary's tally. Back on chat-1, whose summary carries none, none is shown - nothing of chat-2's stays - though its
    /// snapshot's cleared lines hold one F-002's clear was written with, before F-001's cleared the last triage: a snapshot's
    /// tally is its summary's, never a cleared line's. After a reload chat-1's snapshot, now carrying one, shows it.
    /// </summary>
    [Fact]
    public void TheTallyComesBackAfterAReloadAndAReviewSwitch()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string ChatRun = "20260923-101500-bracket-1";
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, ChatRun, ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            JsonObject other = Tally(0, 0, 1, 0, 1, 0);
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200, Ranked(
                Snapshot(OtherRun, false, Finding("F-001"), Finding("F-002", Disposition("rejected", "FICT missed", "wrong"))), other));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            JsonElement switched = await driver.Read(ReadTally);
            Assert.True(switched.GetProperty("shown").GetBoolean(), "a switched-to review's tally is not shown.");
            Assert.Equal(Lines(other), ReviewPageDriver.Strings(switched, "lines"));

            string[] clearedLines =
            {
                Cleared("F-001", AcceptedAlreadyKnown()),
                WithTally(Cleared("F-002", Disposition("rejected", "FICT missed", "wrong")), Tally(0, 1, 0, 0, 1, 0)),
            };
            await driver.Route("GET", "/sessions/" + Chat + "/snapshot", 200, Ranked(
                Snapshot(ChatRun, false, clearedLines, Finding("F-001", null, "suspected", "low"), Finding("F-002", null, "suspected", "low")),
                null));
            await driver.Read(ReviewPageSessionsTests.Chip(Chat));
            await driver.Settle();
            JsonElement back = await driver.Read(ReadTally);
            Assert.False(back.GetProperty("shown").GetBoolean(), "a tally is shown from a summary that carries none: " + back);
            Assert.Equal(ClearedLine, (await driver.Read(ReadCard("F-001"))).GetProperty("status").GetString());

            JsonObject reloaded = Tally(1, 0, 0, 0, 1, 0);
            driver.InitialRoutes.Add(("GET", "/sessions/" + Chat + "/snapshot", 200, Ranked(
                Snapshot(ChatRun, false, Finding("F-001", Disposition("accepted", string.Empty, "new_and_real")), Finding("F-002")),
                reloaded)));
            await driver.Reload();
            await driver.Settle();
            Assert.Equal(Lines(reloaded), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));
        });
    }

    /// <summary>
    /// A backend restart and a read-only restore: the backend no longer holds chat-2, so the page restores it from its run
    /// folder, read-only, and shows that snapshot's summary's tally with every decision and triage control off and none in it.
    /// </summary>
    [Fact]
    public void AReadOnlyRestoredReviewShowsItsTally()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            JsonObject restored = Tally(0, 1, 0, 0, 1, 0);
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 404, Refusal("UnknownChat", "no chat " + OtherChat, false));
            await driver.Route("GET", "/reviews/" + OtherRun, 200, Ranked(
                Snapshot(OtherRun, true, Finding("F-100", Disposition("accepted", "FICT intended", "already_known")), Finding("F-101")),
                restored));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();

            JsonElement tally = await driver.Read(ReadTally);
            Assert.True(tally.GetProperty("shown").GetBoolean(), "a read-only review's tally is not shown.");
            Assert.Equal(Lines(restored), ReviewPageDriver.Strings(tally, "lines"));
            Assert.Equal(0, tally.GetProperty("controls").GetInt32());
            Assert.All(Disabled(await driver.Read(ReadCard("F-101"))), Assert.True);
        });
    }

    /// <summary>
    /// A decision's reply that lands after the engineer switched reviews writes nothing: F-001's Accept on chat-1 is held, the
    /// engineer chooses chat-2 - which holds an F-001 of its own - and its summary's tally stays when the reply, carrying
    /// chat-1's, lands (the card it was pressed on is detached; `entryOf`, H-g-012).
    /// </summary>
    [Fact]
    public void AReplyThatLandsAfterAReviewSwitchLeavesTheTallyAlone()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-001"));
            JsonObject other = Tally(0, 0, 1, 0, 0, 0);
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200, Ranked(
                Snapshot(OtherRun, false, Finding("F-001", Disposition("rejected", "FICT missed", "wrong"))), other));
            await driver.HoldRoute("POST", DispositionPath("F-001"), 200,
                WithTally(Finding("F-001", Disposition("accepted", string.Empty, "new_and_real")), Tally(1, 0, 0, 0, 0, 0)));
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "accept");

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            Assert.Equal(Lines(other), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));

            await driver.ReleaseRoute("POST", DispositionPath("F-001"));
            Assert.Equal(Lines(other), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));
        });
    }

    /// <summary>FR-030: the tally is the backend's words, so with no labels its two lines print as sent.</summary>
    [Fact]
    public void WithNoLabelsTheTallyPrintsTheBackendsLines()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await Reviewed(driver, Finding("F-001"), Finding("F-002"));
            JsonObject tally = Tally(0, 0, 0, 1, 1, 0);
            await driver.Route("POST", DispositionPath("F-001"), 200,
                WithTally(Finding("F-001", Disposition("deferred", string.Empty, "not_worth_flagging")), tally));
            await Press(driver, "F-001", "not_worth_flagging");
            await Decide(driver, "F-001", "defer");

            JsonElement shown = await driver.Read(ReadTally);
            Assert.True(shown.GetProperty("shown").GetBoolean(), "the tally is not shown with no labels.");
            Assert.Equal(Lines(tally), ReviewPageDriver.Strings(shown, "lines"));
        });
    }

    /// <summary>
    /// FR-030: a backend that sends no tally - not in the summary, the stream or a reply - leaves the page as it was: the
    /// tally's section is there, hidden, empty and taking no room, and the card shows the reply as before.
    /// </summary>
    [Fact]
    public void ABackendThatSendsNoTallyShowsNone()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "finding", Finding("F-002"));
            await driver.Push(Chat, 3, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
            await driver.RouteAttention(Chat, SummarySample.Json());
            await driver.EndSession(Chat);
            await driver.Route("POST", DispositionPath("F-002"), 200, Finding("F-002", Disposition("rejected", string.Empty, "wrong")));
            await Press(driver, "F-002", "wrong");
            await Decide(driver, "F-002", "reject");

            JsonElement none = await driver.Read(ReadTally);
            Assert.True(none.GetProperty("present").GetBoolean(), "the page has no section for the tally.");
            Assert.True(none.GetProperty("hidden").GetBoolean(), "the tally's section is shown with nothing sent.");
            Assert.Empty(ReviewPageDriver.Strings(none, "lines"));
            Assert.Equal(0, none.GetProperty("height").GetInt32());
            Assert.Equal(new[] { "wrong" }, Pressed(await driver.Read(ReadCard("F-002"))));
        });
    }

    /// <summary>
    /// At a docked pane's 300 px the tally's two lines are whole - inside the window and every box that clips them, their
    /// words wrapping rather than cut off - with no sideways page scroll, at counts of four figures.
    /// </summary>
    [Fact]
    public void TheTallyIsWhollyVisibleAtThreeHundredPixels()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await Reviewed(driver, Finding("F-001"));
            JsonObject tally = Tally(1234, 5678, 9012, 3456, 7890, 1234);
            await driver.Route("POST", DispositionPath("F-001"), 200,
                WithTally(Finding("F-001", Disposition("accepted", string.Empty, "new_and_real")), tally));
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "accept");

            JsonElement measured = await driver.Read(ReadTallyWhole);
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.Equal(2, measured.GetProperty("count").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    // ---- the card says it has no triage yet (002 T354; roadmap hole H-c-008) ------------------

    /// <summary>
    /// A flagged finding not yet decided says on its card's head that it has no triage - one line under its title, read with
    /// the fold shut, in the backend's words for a finding not yet decided. A pick is no record and leaves it; the Accept
    /// whose reply records `new and real` takes it away, and the head is its line and its title again.
    /// </summary>
    [Fact]
    public void ACardSaysItHasNoTriageUntilOneIsRecorded()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Finding("F-001"));
            JsonElement undecided = await driver.Read(ReadNoTriage("F-001"));
            Assert.Equal(1, undecided.GetProperty("count").GetInt32());
            Assert.Equal(LabelsSample.NoTriageUndecided, undecided.GetProperty("text").GetString());
            Assert.True(undecided.GetProperty("inHead").GetBoolean(), "the line is not in the card's head.");
            Assert.True(undecided.GetProperty("afterTitle").GetBoolean(), "the line is not under the title.");
            Assert.True(undecided.GetProperty("foldShut").GetBoolean(), "the finding's fold is open.");
            Assert.True(undecided.GetProperty("shown").GetBoolean(), "the line does not read with the fold shut.");

            await Press(driver, "F-001", "new_and_real");
            Assert.Equal(new[] { "new_and_real" }, Pressed(await driver.Read(ReadCard("F-001"))));
            Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());

            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", string.Empty, "new_and_real")));
            await Decide(driver, "F-001", "accept");
            JsonElement recorded = await driver.Read(ReadNoTriage("F-001"));
            Assert.Equal(0, recorded.GetProperty("count").GetInt32());
            Assert.Equal(new[] { "card-line", "title" }, ReviewPageDriver.Strings(recorded, "headChildren"));
        });
    }

    /// <summary>
    /// 185A's late triage: each decision recorded without a triage has its own words, naming the repair, drawn from the reply.
    /// F-001's Accept says to press Accept again, F-002's Reject to press Reject again, and F-003's Defer, which a Defer cannot
    /// follow, to press Accept or Reject. A press refused while a turn runs leaves F-001's line as recorded, and the late triage
    /// takes it away.
    /// </summary>
    [Fact]
    public void ACardDecidedWithoutATriageSaysToPressTheSameDecisionAgain()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Finding("F-001"), Finding("F-002"), Finding("F-003"));
            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", string.Empty, null)));
            await driver.Route("POST", DispositionPath("F-002"), 200, Finding("F-002", Disposition("rejected", string.Empty, null)));
            await driver.Route("POST", DispositionPath("F-003"), 200, Finding("F-003", Disposition("deferred", string.Empty, null)));
            await Decide(driver, "F-001", "accept");
            await Decide(driver, "F-002", "reject");
            await Decide(driver, "F-003", "defer");

            Assert.Equal(LabelsSample.NoTriageAccepted, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());
            Assert.Equal(LabelsSample.NoTriageRejected, (await driver.Read(ReadNoTriage("F-002"))).GetProperty("text").GetString());
            Assert.Equal(LabelsSample.NoTriageDeferred, (await driver.Read(ReadNoTriage("F-003"))).GetProperty("text").GetString());

            await driver.Route("POST", DispositionPath("F-001"), 409, TurnRunning);
            await Press(driver, "F-001", "already_known");
            await Decide(driver, "F-001", "accept");
            JsonElement refused = await driver.Read(ReadNoTriage("F-001"));
            Assert.Equal(1, refused.GetProperty("count").GetInt32());
            Assert.Equal(LabelsSample.NoTriageAccepted, refused.GetProperty("text").GetString());

            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", string.Empty, "already_known")));
            await Press(driver, "F-001", "already_known");
            await Decide(driver, "F-001", "accept");
            Assert.Equal(0, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("count").GetInt32());
        });
    }

    /// <summary>
    /// 187A: a pass takes no triage but the miss, so its card's head says nothing of a triage - not yet decided, nor rejected
    /// without the miss - while a flagged finding beside it says it has none.
    /// </summary>
    [Fact]
    public void APassSaysNothingOfATriage()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(driver, Pass("F-001"), Finding("F-002"));
            Assert.Equal(0, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("count").GetInt32());
            Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-002"))).GetProperty("text").GetString());

            await driver.Route("POST", DispositionPath("F-001"), 200, Pass("F-001", Disposition("rejected", string.Empty, null)));
            await Decide(driver, "F-001", "reject");
            JsonElement pass = await driver.Read(ReadNoTriage("F-001"));
            Assert.Equal(0, pass.GetProperty("count").GetInt32());
            Assert.Equal(new[] { "card-line", "title" }, ReviewPageDriver.Strings(pass, "headChildren"));
        });
    }

    /// <summary>
    /// H-d-008: the stream's decisions draw the line as a reply does - F-001's Accept with `already known` takes it away, and
    /// F-002's Reject with none says to press Reject again. A re-run after an answer changes F-001's verdict, so the backend
    /// clears its decision and triage: the card the fold draws again says it has no triage, and its status line carries the
    /// backend's cleared line. F-002's re-run keeps its verdict and its Reject, and its words stay.
    /// </summary>
    [Fact]
    public void ACardWhoseDecisionARerunClearedSaysAgainItHasNoTriage()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            Dictionary<string, object?> rejected = Disposition("rejected", "FICT not a clash", null);
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "finding", Finding("F-002"));
            await driver.Push(Chat, 3, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 4, "disposition", DispositionEvent("F-002", rejected));
            await driver.Settle();
            Assert.Equal(0, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("count").GetInt32());
            Assert.Equal(LabelsSample.NoTriageRejected, (await driver.Read(ReadNoTriage("F-002"))).GetProperty("text").GetString());

            await driver.Push(Chat, 5, "finding", Finding("F-001", null, "suspected", "low"));
            await driver.Push(Chat, 6, "disposition.cleared", Cleared("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 7, "finding", Finding("F-002", rejected));
            await driver.EndSession(Chat);

            Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());
            Assert.Equal(ClearedLine, (await driver.Read(ReadCard("F-001"))).GetProperty("status").GetString());
            Assert.Equal(LabelsSample.NoTriageRejected, (await driver.Read(ReadNoTriage("F-002"))).GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// A review restored read-only from its run folder: each card's head says what its record says - F-100's Accept with
    /// `already known` nothing, F-101, not yet decided, and F-102's Accept without a triage their words, and F-103, whose decision
    /// a re-run cleared, the words of a finding not yet decided, its status line the cleared line - with every triage button off.
    /// </summary>
    [Fact]
    public void ARestoredReviewSaysWhichCardsHaveNoTriage()
    {
        ReviewPageDriver.Run(
            driver =>
            {
                Labelled(driver);
                driver.Sessions.Add(ReviewPageSessionsTests.Item(RestoredChat, RestoredRun, ReviewPageDriver.ReviewedPath, 9, 0));
                driver.InitialRoutes.Add(("GET", "/sessions/" + RestoredChat + "/snapshot", 404, ReviewPageRecheckTests.UnknownChat));
                driver.InitialRoutes.Add(("GET", "/reviews/" + RestoredRun, 200, Snapshot(
                    RestoredRun,
                    true,
                    new[] { Cleared("F-103", AcceptedAlreadyKnown()) },
                    Finding("F-100", Disposition("accepted", "FICT intended", "already_known")),
                    Finding("F-101"),
                    Finding("F-102", Disposition("accepted", "FICT intended", null)),
                    Finding("F-103", null, "suspected", "low"))));
            },
            async driver =>
            {
                await driver.Settle();

                Assert.Equal(0, (await driver.Read(ReadNoTriage("F-100"))).GetProperty("count").GetInt32());
                Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-101"))).GetProperty("text").GetString());
                Assert.Equal(LabelsSample.NoTriageAccepted, (await driver.Read(ReadNoTriage("F-102"))).GetProperty("text").GetString());
                Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-103"))).GetProperty("text").GetString());
                Assert.Equal(ClearedLine, (await driver.Read(ReadCard("F-103"))).GetProperty("status").GetString());
                foreach (string id in new[] { "F-100", "F-101", "F-102", "F-103" })
                {
                    Assert.All(Disabled(await driver.Read(ReadCard(id))), off => Assert.True(off, "a triage button is live on a read-only review."));
                }
            });
    }

    /// <summary>
    /// At a docked pane's 300 px, the card where a real turn leaves it: the session's end reads the ranking, which puts F-007's
    /// card in its grouped row, shut. With the row opened and the card's fold shut, the line - a finding not yet decided, the
    /// longest of the words - is whole: inside the window and every box that clips it, its words inside it, with no sideways
    /// page scroll.
    /// </summary>
    [Fact]
    public void ANoTriageLineIsWhollyVisibleAtThreeHundredPixelsInItsRow()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await driver.RouteAttention(Chat, SummarySample.Json());
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-007"));
            await driver.EndSession(Chat);
            JsonElement placed = await driver.Read(ReadRow("F-007"));
            Assert.True(placed.GetProperty("inRow").GetBoolean(), "F-007's card is not in its grouped row.");
            Assert.False(placed.GetProperty("rowOpen").GetBoolean(), "F-007's row is open before it is measured.");

            JsonElement measured = await driver.Read(ReadNoTriageWhole("F-007"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.Equal(LabelsSample.NoTriageUndecided, measured.GetProperty("text").GetString());
            Assert.True(measured.GetProperty("foldShut").GetBoolean(), "the finding's fold is open.");
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    /// <summary>
    /// FR-030: an older backend sends no labels, so there are no words, and a card's head is its line and its title, as before -
    /// not yet decided, and accepted without a triage. A guard: no line is drawn without the backend's words.
    /// </summary>
    [Fact]
    public void WithNoLabelsACardsHeadIsAsBefore()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await Reviewed(driver, Finding("F-001"));
            JsonElement undecided = await driver.Read(ReadNoTriage("F-001"));
            Assert.Equal(0, undecided.GetProperty("count").GetInt32());
            Assert.Equal(new[] { "card-line", "title" }, ReviewPageDriver.Strings(undecided, "headChildren"));

            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", string.Empty, null)));
            await Decide(driver, "F-001", "accept");
            JsonElement accepted = await driver.Read(ReadNoTriage("F-001"));
            Assert.Equal(0, accepted.GetProperty("count").GetInt32());
            Assert.Equal(new[] { "card-line", "title" }, ReviewPageDriver.Strings(accepted, "headChildren"));
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

    /// <summary>
    /// F-001 accepted with `already known` - pressed on the card, as a guard - before an answer resumed the turn, then the
    /// frames of the fold after it in the order the runner writes them (roadmap hole H-d-008): the re-run's `finding`
    /// folded onto F-001, and - when <paramref name="changed"/> - with another status and severity and no disposition,
    /// then `disposition.cleared`; otherwise with the verdict decided and the disposition kept.
    /// </summary>
    private static async Task DecidedThenFolded(ReviewPageDriver driver, bool changed)
    {
        await driver.StartReview();
        await driver.Push(Chat, 1, "finding", Finding("F-001"));
        await driver.Push(Chat, 2, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
        await driver.Settle();
        Assert.Equal(new[] { "already_known" }, Pressed(await driver.Read(ReadCard("F-001"))));

        if (changed)
        {
            await driver.Push(Chat, 3, "finding", Finding("F-001", null, "suspected", "low"));
            await driver.Push(Chat, 4, "disposition.cleared", Cleared("F-001", AcceptedAlreadyKnown()));
        }
        else
        {
            await driver.Push(Chat, 3, "finding", Finding("F-001", AcceptedAlreadyKnown()));
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

    /// <summary>The card's sentence for a disposition recorded with a triage, in `LabelsSample`'s words.</summary>
    private static string Sentence(string decision, string triage, string note) =>
        "Disposition: " + decision + " (" + Word(triage) + ") by " + Engineer + " at " + RecordedAt
        + (note.Length > 0 ? " - " + note : string.Empty);

    // ---- samples ------------------------------------------------------------------------------

    private static string Finding(
        string id, Dictionary<string, object?>? disposition = null, string status = "demonstrated", string severity = "medium") =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "id", id },
            { "check", "interference.static" },
            { "title", "FICT finding " + id },
            { "status", status },
            { "severity", severity },
            { "component_ids", new[] { "cmp:0002" } },
            { "observed", "FICT observed for " + id + "." },
            { "disposition", disposition },
        });

    /// <summary>A pass, 'Checked, no issue' (owner decision 187A): `checked_within_scope`, severity info.</summary>
    private static string Pass(string id, Dictionary<string, object?>? disposition = null) =>
        Finding(id, disposition, "checked_within_scope", "info");

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

    /// <summary>F-001's Accept with `already known`, recorded before an answer resumed the turn (roadmap hole H-d-008).</summary>
    private static Dictionary<string, object?> AcceptedAlreadyKnown() => Disposition("accepted", "FICT intended", "already_known");

    /// <summary>A `disposition.cleared` body as the runner writes it: the finding, the disposition cleared and the line.</summary>
    private static string Cleared(string findingId, Dictionary<string, object?> disposition) =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "finding_id", findingId },
            { "disposition", disposition },
            { "reason", ClearedLine },
        });

    /// <summary>
    /// The review's triage tally as the backend sends it (002 cycle 7): the flagged findings by outcome, those not recorded and
    /// the misses, with `report.md`'s two lines for them - words no page composes, printed as sent.
    /// </summary>
    private static JsonObject Tally(int newAndReal, int alreadyKnown, int wrong, int notWorth, int notRecorded, int misses) =>
        new JsonObject
        {
            ["counts"] = new JsonObject
            {
                ["new_and_real"] = newAndReal,
                ["already_known"] = alreadyKnown,
                ["wrong"] = wrong,
                ["not_worth_flagging"] = notWorth,
            },
            ["not_recorded"] = notRecorded,
            ["misses"] = misses,
            ["text"] = "By triage: new and real: " + newAndReal + ", real but already known: " + alreadyKnown + ", wrong: " + wrong
                + ", true but not worth flagging: " + notWorth + ", not recorded: " + notRecorded,
            ["misses_text"] = "Passes judged wrong (misses): " + misses,
        };

    /// <summary>The two lines a tally carries, in the order the page prints them.</summary>
    private static string[] Lines(JsonObject tally) =>
        new[] { tally["text"]!.GetValue<string>(), tally["misses_text"]!.GetValue<string>() };

    /// <summary><paramref name="body"/> - a reply or an event body - carrying <paramref name="tally"/>, as the backend adds it.</summary>
    private static string WithTally(string body, JsonObject tally)
    {
        JsonObject node = JsonNode.Parse(body)!.AsObject();
        node["triage_tally"] = tally.DeepClone();
        return node.ToJsonString();
    }

    /// <summary>
    /// <paramref name="snapshot"/> with the ranking and summary a backend sends (<see cref="SummarySample"/>), its summary
    /// carrying <paramref name="tally"/>, or no tally when none.
    /// </summary>
    private static string Ranked(string snapshot, JsonObject? tally)
    {
        JsonObject node = JsonNode.Parse(snapshot)!.AsObject();
        node["ranking"] = SummarySample.Ranking(summary =>
        {
            if (tally != null)
            {
                summary["triage_tally"] = tally.DeepClone();
            }
        });
        return node.ToJsonString();
    }

    /// <summary>A refusal's body, as the route sends one.</summary>
    private static string Refusal(string errorClass, string message, bool retryable) =>
        JsonSerializer.Serialize(new { error_class = errorClass, message, retryable });

    /// <summary>A run folder's read-only snapshot: one finding accepted with a triage, one undecided, no ranking.</summary>
    private static string RestoredSnapshot() => Snapshot(
        RestoredRun,
        true,
        Finding("F-100", Disposition("accepted", "FICT intended", "already_known")),
        Finding("F-101"));

    /// <summary>
    /// A review's snapshot with <paramref name="findings"/> and no ranking: read-only from its run folder, or the
    /// backend's live chat, its turn ended, whose findings take decisions.
    /// </summary>
    private static string Snapshot(string runId, bool readOnly, params string[] findings) =>
        Snapshot(runId, readOnly, new string[0], findings);

    /// <summary>
    /// <see cref="Snapshot(string, bool, string[])"/> naming <paramref name="cleared"/> - `disposition.cleared` bodies - under
    /// `cleared`, as the backend adds it when a cleared decision's line still stands (owner decision 193A); none, no key.
    /// </summary>
    private static string Snapshot(string runId, bool readOnly, string[] cleared, params string[] findings)
    {
        var snapshot = new JsonObject
        {
            ["run_id"] = runId,
            ["read_only"] = readOnly,
            ["read_only_reason"] = readOnly ? ReviewPageSessionsTests.ReadOnlyReason : null,
            ["chat_state"] = readOnly ? null : "ended",
            ["last_seq"] = readOnly ? null : JsonValue.Create(9),
            ["document"] = JsonNode.Parse(JsonSerializer.Serialize(new { path = ReviewPageDriver.ReviewedPath, configuration = "Default" })),
            ["findings"] = new JsonArray(findings.Select(finding => JsonNode.Parse(finding)).ToArray()),
            ["evidence_requests"] = new JsonArray(),
            ["coverage"] = new JsonArray(),
            ["ranking"] = null,
            ["not_examined"] = null,
        };
        if (cleared.Length > 0)
        {
            snapshot["cleared"] = new JsonArray(cleared.Select(body => JsonNode.Parse(body)).ToArray());
        }

        return snapshot.ToJsonString();
    }

    /// <summary><paramref name="finding"/> citing a drawing place by its persistent reference, so Show sends it to the host.</summary>
    private static string Referenced(string finding)
    {
        JsonObject body = JsonNode.Parse(finding)!.AsObject();
        body["drawing_locations"] = JsonNode.Parse("[{\"document_id\":\"doc:2\",\"persist_ref\":\"FICT-REF-0001\"}]");
        return body.ToJsonString();
    }

    /// <summary>
    /// The `finding.withdrawn` body of a fold, as the runner writes it (the backlog's cycle 3 section): the id the re-run was
    /// first announced under, why, and `folded_into`, the id it took.
    /// </summary>
    private static string Folded(string spent, string onto) =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "finding_id", spent },
            { "reason", "a second verdict on what " + onto + " judges, shown as " + onto },
            { "folded_into", onto },
        });

    // ---- reading the page ---------------------------------------------------------------------

    /// <summary>
    /// One card's triage buttons - tokens, words, pressed and off - its status line, and after a refusal the
    /// recorded disposition's sentence beside it, the refusal's sentence and class, and which comes first.
    /// </summary>
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
  refusalClass: status ? h.text(status, '.error-fold .error-class') : null,
  record: status ? h.text(status, '.card-record') : null,
  refusal: status ? h.text(status, '.plain-error-text') : null,
  recordFirst: !!status && h.before(status.querySelector('.card-record'), status.querySelector('.plain-error')),
  cleared: status ? h.text(status, '.card-cleared') : null,
  clearedFirst: !!status && h.before(status.querySelector('.card-cleared'), status.querySelector('.plain-error'))
});";

    /// <summary>
    /// One card's no-triage line (roadmap hole H-c-008): how many the card holds, its words, whether it stands in the card's head
    /// under the title, whether the fold is shut and whether the line reads all the same, and the head's children by class.
    /// </summary>
    private static string ReadNoTriage(string findingId) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
if (!card) { return JSON.stringify({ ok: false, error: 'no card " + findingId + @"' }); }
var head = card.querySelector('.card-head');
var lines = card.querySelectorAll('.card-no-triage');
var line = lines.length ? lines[0] : null;
return JSON.stringify({
  ok: true,
  count: lines.length,
  text: line ? line.textContent : null,
  inHead: !!line && line.parentElement === head,
  afterTitle: h.before(head.querySelector('.title'), line),
  foldShut: card.querySelector('.details').hidden,
  shown: h.rendered(line),
  headChildren: h.children(head)
});";

    /// <summary>
    /// Opens the grouped row one card stands in, leaves the card's fold shut, and measures its no-triage line brought into view
    /// by <see cref="Whole"/>; a line that is missing counts as cut off.
    /// </summary>
    private static string ReadNoTriageWhole(string findingId) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
var row = card.closest('details.type-row');
if (row) { row.open = true; }
" + Whole + @"
var line = card.querySelector('.card-no-triage');
var clipped = [];
if (!line) { clipped.push('line missing'); }
else if (!whole(line)) { clipped.push(JSON.stringify(line.getBoundingClientRect())); }
return JSON.stringify({
  ok: true,
  width: window.innerWidth,
  text: line ? line.textContent : null,
  foldShut: card.querySelector('.details').hidden,
  clipped: clipped,
  noHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth
});";

    /// <summary>
    /// The triage tally's section (002 cycle 7): whether the page has one, whether it is hidden or shown, its lines in order,
    /// how many controls it holds and how tall it stands.
    /// </summary>
    private const string ReadTally = @"
var section = document.getElementById('triage-tally');
if (!section) { return JSON.stringify({ ok: true, present: false, hidden: true, shown: false, lines: [], controls: 0, height: 0 }); }
var lines = [];
var paragraphs = section.querySelectorAll('p');
for (var i = 0; i < paragraphs.length; i++) { lines.push(paragraphs[i].textContent); }
var box = section.getBoundingClientRect();
return JSON.stringify({
  ok: true,
  present: true,
  hidden: section.hidden,
  shown: !section.hidden && box.height > 0,
  lines: lines,
  controls: section.querySelectorAll('button, input, select, textarea, a, [tabindex], [data-action]').length,
  height: Math.round(box.height)
});";

    /// <summary>
    /// Measures each of the tally's lines brought into view, as <see cref="ReadWhole"/> measures the triage buttons; a section
    /// that is missing or hidden counts as cut off.
    /// </summary>
    private const string ReadTallyWhole = @"
var section = document.getElementById('triage-tally');
var lines = section ? section.querySelectorAll('p') : [];
" + Whole + @"
var clipped = [];
if (!section || section.hidden) { clipped.push('the section is missing or hidden'); }
for (var i = 0; i < lines.length; i++) {
  if (!whole(lines[i])) { clipped.push(lines[i].textContent + ' ' + JSON.stringify(lines[i].getBoundingClientRect())); }
}
return JSON.stringify({
  ok: true,
  width: window.innerWidth,
  count: lines.length,
  clipped: clipped,
  noHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth
});";

    /// <summary>The finding cards Results hold, by id, wherever they stand.</summary>
    private const string ReadCards = @"
return JSON.stringify({ ok: true, ids: h.attrs(document.getElementById('results'), '.card.finding', 'data-finding-id') });";

    /// <summary>Whether one card stands in a grouped row, and whether that row is open.</summary>
    private static string ReadRow(string findingId) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
var row = card ? card.closest('details.type-row') : null;
return JSON.stringify({ ok: !!card, inRow: !!row, rowOpen: !!row && row.open });";

    /// <summary>
    /// After a press refused on a cleared card in its grouped row (193A): opens the row, then measures the cleared line,
    /// the refusal's sentence, its Details summary and every triage button, as <see cref="ReadRefusalWhole"/> measures.
    /// </summary>
    private static string ReadClearedRefusalWhole(string findingId) => ReadPartsWhole(findingId, @"
var row = card.closest('details.type-row');
if (row) { row.open = true; }
var status = card.querySelector('.card-status');
var parts = [
  ['cleared', status.querySelector('.card-cleared')],
  ['refusal', status.querySelector('.plain-error-text')],
  ['details', status.querySelector('.error-fold > summary')]
];");

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

    /// <summary>The Transcript's text and its finding markers.</summary>
    private const string ReadTranscript = @"
var transcript = document.getElementById('transcript');
return JSON.stringify({ ok: true, text: transcript.textContent, markers: h.texts(transcript, '.marker') });";

    /// <summary>
    /// Opens one card's fold and measures each triage button brought into view: no box scrolled
    /// sideways to show it, inside the window and every ancestor that clips, on both axes, with its
    /// words inside it; and no sideways page scroll.
    /// </summary>
    private static string ReadWhole(string findingId) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
card.querySelector('[data-action=""expand""]').click();
" + Whole + @"
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

    /// <summary>
    /// After a refused press (H-g-012): opens one card's fold and measures, each brought into view as
    /// <see cref="ReadWhole"/> measures the triage buttons, the recorded disposition's sentence, the refusal's
    /// sentence, its Details summary and every triage button; a part that is missing counts as cut off.
    /// </summary>
    private static string ReadRefusalWhole(string findingId) => ReadPartsWhole(findingId, @"
var status = card.querySelector('.card-status');
var parts = [
  ['record', status.querySelector('.card-record')],
  ['refusal', status.querySelector('.plain-error-text')],
  ['details', status.querySelector('.error-fold > summary')]
];");

    /// <summary>
    /// After a re-run cleared a decision (H-d-008): opens one card's fold and measures the cleared decision's line and every
    /// triage button, as <see cref="ReadRefusalWhole"/> measures; a line that is missing counts as cut off.
    /// </summary>
    private static string ReadClearedWhole(string findingId) => ReadPartsWhole(findingId, @"
var parts = [['line', card.querySelector('.card-status.cleared')]];");

    /// <summary>
    /// Opens one card's fold and measures each of the named `parts` that <paramref name="parts"/> declares, then every
    /// triage button, each brought into view by <see cref="Whole"/>; a part that is missing counts as cut off. The
    /// refused press and the cleared decision share it rather than copy it.
    /// </summary>
    private static string ReadPartsWhole(string findingId, string parts) => @"
var card = document.querySelector('.card.finding[data-finding-id=""" + findingId + @"""]');
card.querySelector('[data-action=""expand""]').click();
" + Whole + parts + @"
var buttons = card.querySelectorAll('[data-action=""triage""]');
for (var b = 0; b < buttons.length; b++) { parts.push(['triage ' + buttons[b].getAttribute('data-triage'), buttons[b]]); }
var clipped = [];
for (var i = 0; i < parts.length; i++) {
  var node = parts[i][1];
  if (!node) { clipped.push(parts[i][0] + ' missing'); }
  else if (!whole(node)) { clipped.push(parts[i][0] + ' ' + JSON.stringify(node.getBoundingClientRect())); }
}
return JSON.stringify({
  ok: true,
  width: window.innerWidth,
  count: parts.length,
  foldOpen: !card.querySelector('.details').hidden,
  clipped: clipped,
  noHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth
});";

    /// <summary>
    /// `whole(node)`: the node, brought into view, is whole - no box scrolled sideways to show it, inside the window
    /// and every ancestor that clips, on both axes, with its words inside it.
    /// </summary>
    private const string Whole = @"
var whole = function (node) {
  node.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  var rect = node.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) { return false; }
  if (node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1) { return false; }
  for (var p = node.parentElement; p; p = p.parentElement) {
    // The pane scrolls up and down only: a box scrolled sideways to show the node cuts it off at rest.
    if (p.scrollLeft !== 0) { return false; }
    var style = getComputedStyle(p);
    if (style.overflowX !== 'visible' || style.overflowY !== 'visible') {
      var box = p.getBoundingClientRect();
      if (rect.left < box.left - 1 || rect.right > box.right + 1 || rect.top < box.top - 1 || rect.bottom > box.bottom + 1) { return false; }
    }
  }
  return rect.left >= -1 && rect.right <= window.innerWidth + 1 && rect.top >= -1 && rect.bottom <= window.innerHeight + 1;
};";
}
