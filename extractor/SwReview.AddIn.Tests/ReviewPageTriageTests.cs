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
/// *Changed 2026-11-02 (002 T356; cycle 9's Tier 2 review):* the words are shorter - a finding not yet decided says only that
/// it has none - and while the review is read-only every such card says `read_only`'s words, whatever its decision, and
/// names no press its locked buttons cannot make. A reply that lands after a review switch draws no line on the shown
/// review's card of the same id, and a reload and a switch bring the line back from the live snapshot.
/// *Added 2026-11-02 (002 T356; a read-only check of those fixes):* a switch between a live review and a read-only restore
/// draws every card's line again for the review shown - the read-only words, or, once it is live again, the repair.
///
/// Roadmap hole H-g-010 (002 T360): a withdrawal says what it took. When an answer's restate withdraws a finding that held a
/// decision, the `finding.withdrawn` body names the disposition and the backend's clause for it (`taken`), and the Transcript's
/// line ends with that clause after the reason, printed as sent, live and in a replay; a fold's withdrawal carries none, the
/// cleared line on the card saying what the fold took.
///
/// Owner decision 198A (002 T366; roadmap hole H-c-009): a Defer recorded without a triage takes one when Defer is pressed again
/// with one picked, and its card says so in the backend's words; and a card's note box shows the recorded note when the card is
/// drawn and after each reply, a refusal's too, so it never shows a note the backend did not keep and a later press posts the
/// recorded note - after a reload or a review switch too - rather than an empty box over it.
/// *Changed 2026-11-02 (002 T368; cycle 11's Tier 2 review):* not a refusal's: a refused press leaves the box as typed, since the
/// backend never read its note, so the retry posts it. And when a reply keeps the note recorded first in place of another,
/// non-blank one the press sent - a late triage keeps it - the card says so after the reply's sentence, in the backend's words
/// (`labels.note`), until its status is next written.
/// *Added 2026-11-02 (002 T368; a read-only check of those fixes):* with no labels the card says nothing of the note, and the
/// line is wholly visible at a docked pane's 300 px, in its grouped row.
///
/// Four Review page fixes, the owner's pick (002 T372; cycle 13): a `finding` event carries the tally, as the disposition events
/// do, and the page shows it as it arrives; after a reload the cards carry the backend's words whichever of the labels and the
/// snapshot answers first; a read-only restore's cleared line is the backend's read-only form, which asks for no decision; and
/// a read-only restore's Transcript names each withdrawal that took a decision, as the live line does.
/// *Changed 2026-11-02 (002 T374; cycle 13's Tier 2 review):* a `finding` event names the tally, null while no finding records
/// a triage, and the page changes the tally only when the event names it, so an older backend's finding, which never does,
/// leaves it as it was (009 FR-030). And a restore read that fails before the labels answer draws its error card once they
/// have, so the card says its next step.
/// *Added 2026-11-03 (002 T374; a read-only check of those fixes):* a restore read for a review the engineer left before the
/// labels answered draws nothing once they have, neither its snapshot nor its error card.
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

    /// <summary>
    /// <see cref="ClearedLine"/> as a read-only restore names it (002 cycle 13): the backend's line without the call to decide
    /// again (`RerunWords.read_only`), since the restore's decision buttons are off. The page prints it as sent.
    /// </summary>
    private const string ReadOnlyClearedLine =
        "The check ran again after your answer and its verdict changed, so your Accept (real but already known) was cleared.";

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
    ///
    /// *Changed 2026-11-02 on purpose (002 T366; owner decision 198A, roadmap hole H-c-009):* the deferred
    /// finding's Accept posts the Defer's note, `FICT check the bore`, which its note box now shows, where
    /// the body pinned an empty note - the empty box that would have replaced the Defer's note, unannounced.
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
            Assert.Equal("decision=accepted, note=FICT check the bore", Body(Assert.Single(await DispositionCalls(driver))));
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
    ///
    /// *Changed 2026-11-02 on purpose (002 T368; cycle 11's Tier 2 review, a guard):* and the event
    /// fills F-001's note box with the note recorded (owner decision 198A), which no fact read.
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
            Assert.Equal("FICT intended", await NoteBox(driver, "F-001"));

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
    ///
    /// *Changed 2026-11-02 on purpose (002 T368; cycle 11's Tier 2 review, a guard):* and F-100's
    /// note box holds the note recorded (owner decision 198A), which no fact read on a restore.
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
                Assert.Equal("FICT intended", await NoteBox(driver, "F-100"));
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
    ///
    /// *Changed 2026-11-02 on purpose (002 T366; owner decision 198A, roadmap hole H-c-009):* the
    /// note box shows the recorded note after each reply. After the late triage, whose reply keeps
    /// the first note, the box shows `FICT first note`, where it went on showing `FICT second note`,
    /// which the backend did not keep; the refused press posts what the box then holds, `FICT third
    /// note` typed over it, where it posted `FICT second note` still in the box; and after the
    /// refusal the box shows the recorded note again, as the row shows the recorded triage.
    ///
    /// *Changed 2026-11-02 on purpose (002 T368; cycle 11's Tier 2 review):* after the refusal the
    /// box holds `FICT third note` as typed, where it showed the recorded note again: the backend
    /// never read the refused press's note, so the box keeps it for the retry
    /// (<see cref="ARefusedPressLeavesTheTypedNoteForTheRetry"/>). And the late triage's status
    /// line is the reply's sentence followed by the words file's line that the note recorded first
    /// stays, where it was the sentence alone: `FICT second note` was sent and not kept
    /// (<see cref="ALateTriageThatKeepsTheNoteRecordedFirstSaysSo"/>).
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
                "Disposition: accepted (" + Word("already_known") + ") by " + Engineer + " at " + RecordedAt + " - FICT first note"
                    + LabelsSample.NoteNotKept,
                late.GetProperty("status").GetString());
            Assert.Equal("card-status decided", late.GetProperty("statusClass").GetString());
            Assert.Equal("FICT first note", await NoteBox(driver, "F-001"));

            await driver.Route("POST", DispositionPath("F-001"), 409, TriageAlreadyRecorded);
            await Note(driver, "F-001", "FICT third note");
            await driver.ClearCalls();
            await Press(driver, "F-001", "wrong");
            await Decide(driver, "F-001", "accept");
            Assert.Equal(
                "decision=accepted, note=FICT third note, triage=wrong",
                Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal("card-status bad", refused.GetProperty("statusClass").GetString());
            Assert.Equal("TriageAlreadyRecorded", refused.GetProperty("refusalClass").GetString());
            Assert.Equal(new[] { "already_known" }, Pressed(refused));
            Assert.Equal(Sentence("accepted", "already_known", "FICT first note"), refused.GetProperty("record").GetString());
            Assert.Equal(LabelsSample.TriageAlreadyRecorded, refused.GetProperty("refusal").GetString());
            Assert.Equal("FICT third note", await NoteBox(driver, "F-001"));
        });
    }

    /// <summary>
    /// Owner decision 198A (002 T366; roadmap hole H-c-009): a finding deferred without a triage takes one when Defer is pressed
    /// again with one picked, and stays deferred. F-001 arrives deferred with a note and no triage: its head says to press Defer
    /// again, in the backend's words, and its note box shows the Defer's note. `new and real` picked and Defer pressed posts the
    /// deferral with the triage and that note; the reply - deferred, the triage recorded, the note, engineer and time kept - takes
    /// the line away, presses `new and real`, is the card's sentence and is the box's note. Which press the backend records is
    /// its rule alone: the page sends the press and shows the reply.
    /// </summary>
    [Fact]
    public void ADeferredFindingTakesAnOutcomeWhenDeferIsPressedAgain()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string Kept = "FICT first shown at an earlier sitting";
            await Reviewed(driver, Finding("F-001", Disposition("deferred", Kept, null)));
            Assert.Equal(LabelsSample.NoTriageDeferred, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());
            Assert.Equal(Kept, await NoteBox(driver, "F-001"));

            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("deferred", Kept, "new_and_real")));
            await driver.ClearCalls();
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "defer");

            Assert.Equal("decision=deferred, note=" + Kept + ", triage=new_and_real", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Equal(new[] { "new_and_real" }, Pressed(card));
            Assert.Equal(Sentence("deferred", "new_and_real", Kept), card.GetProperty("status").GetString());
            Assert.Equal("card-status decided", card.GetProperty("statusClass").GetString());
            Assert.Equal(0, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("count").GetInt32());
            Assert.Equal(Kept, await NoteBox(driver, "F-001"));
        });
    }

    /// <summary>
    /// Roadmap hole H-g-012: a finding the stream sends accepted with `already known`; `wrong` is picked and
    /// Accept pressed, and the backend refuses the second triage (a scripted `409 TriageAlreadyRecorded`). The card
    /// shows the record again: `already known` pressed and `wrong` let go, the recorded disposition's sentence above
    /// the refusal's, which is the words' sentence for the class, and the class in the refusal's fold.
    ///
    /// *Changed 2026-11-02 on purpose (002 T366; owner decision 198A, roadmap hole H-c-009):* the press posts the recorded
    /// note, `FICT first note`, which the card's note box now shows when the card is drawn, where the body pinned the empty
    /// box the card was drawn with.
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

            Assert.Equal("decision=accepted, note=FICT first note, triage=wrong", Body(Assert.Single(await DispositionCalls(driver))));
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
    /// *Changed 2026-11-02 on purpose (002 T372; cycle 13):* the read-only snapshot named the live line, "... Decide again.", on
    /// a card whose buttons are off; the backend now names its read-only form, without that call (002 T371), and the card shows
    /// it as sent, asking for no decision. A guard of the page's half: the page prints the line as sent.
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
            await driver.Route("GET", "/reviews/" + OtherRun, 200, Snapshot(
                OtherRun,
                true,
                new[] { Cleared("F-001", AcceptedAlreadyKnown(), ReadOnlyClearedLine) },
                Finding("F-001", null, "suspected", "low")));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();

            JsonElement card = await driver.Read(ReadCard("F-001"));
            Assert.Empty(Pressed(card));
            Assert.Equal(ReadOnlyClearedLine, card.GetProperty("status").GetString());
            Assert.DoesNotContain("Decide again", card.GetProperty("status").GetString()!, StringComparison.Ordinal);
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
    /// *Changed 2026-11-02 (002 T366; owner decision 198A):* F-003's Defer says to press Defer again, which records the outcome
    /// and keeps the deferral (<see cref="ADeferredFindingTakesAnOutcomeWhenDeferIsPressedAgain"/>), so every decision's words
    /// name the same decision again; the fact reads them from <see cref="LabelsSample"/>, and its code is as it was.
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
    /// *Changed 2026-11-02 on purpose (002 T356; cycle 9's Tier 2 review):* it asserted F-102's sentence to press Accept again,
    /// on a card whose buttons are off. A read-only review takes no press, so every flagged card with no triage says the
    /// backend's read-only words, whatever its decision, and asks for none: F-101 not yet decided, F-102's Accept, F-104's
    /// Reject and F-105's Defer without one, and the cleared F-103; F-100, with its triage, and the pass F-106 say nothing.
    /// *Changed 2026-11-02 on purpose (002 T372; cycle 13):* F-103's status line was the live cleared line, "... Decide again.";
    /// a read-only snapshot now names its read-only form (002 T371), which the card shows as sent.
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
                    new[] { Cleared("F-103", AcceptedAlreadyKnown(), ReadOnlyClearedLine) },
                    Finding("F-100", Disposition("accepted", "FICT intended", "already_known")),
                    Finding("F-101"),
                    Finding("F-102", Disposition("accepted", "FICT intended", null)),
                    Finding("F-103", null, "suspected", "low"),
                    Finding("F-104", Disposition("rejected", "FICT not a clash", null)),
                    Finding("F-105", Disposition("deferred", string.Empty, null)),
                    Pass("F-106"))));
            },
            async driver =>
            {
                await driver.Settle();

                Assert.Equal(0, (await driver.Read(ReadNoTriage("F-100"))).GetProperty("count").GetInt32());
                foreach (string id in new[] { "F-101", "F-102", "F-103", "F-104", "F-105" })
                {
                    JsonElement line = await driver.Read(ReadNoTriage(id));
                    Assert.Equal(1, line.GetProperty("count").GetInt32());
                    Assert.Equal(LabelsSample.NoTriageReadOnly, line.GetProperty("text").GetString());
                }

                Assert.Equal(0, (await driver.Read(ReadNoTriage("F-106"))).GetProperty("count").GetInt32());
                Assert.Equal(ReadOnlyClearedLine, (await driver.Read(ReadCard("F-103"))).GetProperty("status").GetString());
                foreach (string id in new[] { "F-100", "F-101", "F-102", "F-103", "F-104", "F-105", "F-106" })
                {
                    Assert.All(Disabled(await driver.Read(ReadCard(id))), off => Assert.True(off, "a triage button is live on a read-only review."));
                }
            });
    }

    /// <summary>
    /// At a docked pane's 300 px, the card where a real turn leaves it: the session's end reads the ranking, which puts F-007's
    /// card in its grouped row, shut. With the row opened and the card's fold shut, the line - a finding not yet decided, the
    /// longest of the words - is whole: inside the window and every box that clips it, its words inside it, with no sideways
    /// page scroll. *Changed 2026-11-02 on purpose (002 T356; cycle 9's Tier 2 review):* the words for a finding not yet
    /// decided are now the shortest, so F-007 is sent deferred without a triage, whose words are now the longest.
    /// *Changed 2026-11-02 on purpose (002 T366; owner decision 198A):* a Defer's words now name Defer again and are no longer
    /// the longest, so F-007 is sent accepted without a triage, whose words, "... press Accept again", now are.
    /// </summary>
    [Fact]
    public void ANoTriageLineIsWhollyVisibleAtThreeHundredPixelsInItsRow()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await driver.RouteAttention(Chat, SummarySample.Json());
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-007", Disposition("accepted", string.Empty, null)));
            await driver.EndSession(Chat);
            JsonElement placed = await driver.Read(ReadRow("F-007"));
            Assert.True(placed.GetProperty("inRow").GetBoolean(), "F-007's card is not in its grouped row.");
            Assert.False(placed.GetProperty("rowOpen").GetBoolean(), "F-007's row is open before it is measured.");

            JsonElement measured = await driver.Read(ReadNoTriageWhole("F-007"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.Equal(LabelsSample.NoTriageAccepted, measured.GetProperty("text").GetString());
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

    /// <summary>
    /// Cycle 9's Tier 2 review, a guard: a decision's reply that lands after the engineer switched reviews draws no line on
    /// the shown review's card of the same id (`showDisposition` draws only through the card its own entry holds,
    /// `entryOf`). Chat-1's F-001 is accepted with no outcome picked and its reply held; the engineer chooses chat-2, whose
    /// F-001 is rejected as `wrong` and says nothing of a triage; the held reply then lands, an Accept with no triage - and
    /// chat-2's F-001 still says nothing, its head its line and its title.
    /// </summary>
    [Fact]
    public void AReplyWithNoTriageThatLandsAfterAReviewSwitchDrawsNoLineOnTheShownCard()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-001"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200,
                Snapshot(OtherRun, false, Finding("F-001", Disposition("rejected", "FICT missed", "wrong"))));
            await driver.HoldRoute("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", string.Empty, null)));
            await Decide(driver, "F-001", "accept");

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            Assert.Equal(0, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("count").GetInt32());

            await driver.ReleaseRoute("POST", DispositionPath("F-001"));
            JsonElement shown = await driver.Read(ReadNoTriage("F-001"));
            Assert.Equal(0, shown.GetProperty("count").GetInt32());
            Assert.Equal(new[] { "card-line", "title" }, ReviewPageDriver.Strings(shown, "headChildren"));
        });
    }

    /// <summary>
    /// Cycle 9's Tier 2 review, a guard: a review switch and a reload bring the line back through
    /// `GET /sessions/{chat}/snapshot`, as they bring the cleared line and the tally back. Chat-2's live snapshot holds F-001
    /// not yet decided, F-002's Accept without a triage and F-003's Reject as `wrong`: their cards say they have none, to
    /// press Accept again, and nothing. After a reload the page shows chat-1, the newest review of the document, from its live
    /// snapshot: F-001's Defer and F-002's Reject without a triage, whose cards say to press Accept or Reject, and Reject again.
    /// *Changed 2026-11-02 (002 T366; owner decision 198A):* F-001's Defer now says to press Defer again; the fact reads the
    /// words from <see cref="LabelsSample"/>, and its code is as it was.
    /// </summary>
    [Fact]
    public void ANoTriageLineComesBackAfterAReloadAndAReviewSwitch()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string ChatRun = "20260923-101500-bracket-1";
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, ChatRun, ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200, Snapshot(
                OtherRun,
                false,
                Finding("F-001"),
                Finding("F-002", Disposition("accepted", string.Empty, null)),
                Finding("F-003", Disposition("rejected", "FICT missed", "wrong"))));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());
            Assert.Equal(LabelsSample.NoTriageAccepted, (await driver.Read(ReadNoTriage("F-002"))).GetProperty("text").GetString());
            Assert.Equal(0, (await driver.Read(ReadNoTriage("F-003"))).GetProperty("count").GetInt32());

            driver.InitialRoutes.Add(("GET", "/sessions/" + Chat + "/snapshot", 200, Snapshot(
                ChatRun,
                false,
                Finding("F-001", Disposition("deferred", string.Empty, null)),
                Finding("F-002", Disposition("rejected", string.Empty, null)))));
            await driver.Reload();
            await driver.Settle();
            Assert.Equal(LabelsSample.NoTriageDeferred, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());
            Assert.Equal(LabelsSample.NoTriageRejected, (await driver.Read(ReadNoTriage("F-002"))).GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// Owner decision 198A (002 T366; roadmap hole H-c-009): a card's note box shows the recorded note whenever the card is drawn,
    /// so a press after a review switch or a reload posts the note recorded, not an empty box over it - the Defer's note, such as
    /// 188A's date, survives the Defer's later Accept. The engineer chooses chat-2, whose live snapshot holds F-001 deferred with
    /// a note and no triage, and F-002 not yet decided: F-001's box shows the Defer's note and F-002's is empty, and `new and real`
    /// picked and Accept pressed on F-001 posts the note to chat-2. After a reload the page shows chat-1, the newest review of the
    /// document, from its live snapshot, F-003 rejected with a note and no triage: its box shows the note, and the late triage
    /// posts it.
    /// </summary>
    [Fact]
    public void ANoteBoxShowsTheRecordedNoteAfterAReviewSwitchAndAReload()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string ChatRun = "20260923-101500-bracket-1";
            const string Deferred = "FICT first shown at an earlier sitting";
            string otherPath = "/sessions/" + OtherChat + "/findings/F-001/disposition";
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, ChatRun, ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200, Snapshot(
                OtherRun,
                false,
                Finding("F-001", Disposition("deferred", Deferred, null)),
                Finding("F-002")));
            await driver.Route("POST", otherPath, 200, Finding("F-001", Disposition("accepted", Deferred, "new_and_real")));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            Assert.Equal(Deferred, await NoteBox(driver, "F-001"));
            Assert.Equal(string.Empty, await NoteBox(driver, "F-002"));
            await driver.ClearCalls();
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "accept");
            JsonElement accepted = Assert.Single(await DispositionCalls(driver));
            Assert.Equal(otherPath, accepted.GetProperty("path").GetString());
            Assert.Equal("decision=accepted, note=" + Deferred + ", triage=new_and_real", Body(accepted));

            driver.InitialRoutes.Add(("GET", "/sessions/" + Chat + "/snapshot", 200, Snapshot(
                ChatRun,
                false,
                Finding("F-003", Disposition("rejected", "FICT not a clash", null)))));
            await driver.Reload();
            await driver.Settle();
            Assert.Equal("FICT not a clash", await NoteBox(driver, "F-003"));
            await driver.Route("POST", DispositionPath("F-003"), 200, Finding("F-003", Disposition("rejected", "FICT not a clash", "wrong")));
            await driver.ClearCalls();
            await Press(driver, "F-003", "wrong");
            await Decide(driver, "F-003", "reject");
            Assert.Equal("decision=rejected, note=FICT not a clash, triage=wrong", Body(Assert.Single(await DispositionCalls(driver))));
        });
    }

    /// <summary>
    /// Cycle 11's Tier 2 review (002 T368; owner decision 198A): a refused press leaves the note box as typed, since the backend
    /// never read its note. F-001 is not yet decided; the engineer types the earlier sitting 188A asks for, picks `new and real`
    /// and presses Accept while a turn still runs - the explanation pass, inside the turn's end - and the backend refuses it
    /// (`409 TurnRunning`). The pick goes back to the record's, none, and the box keeps what was typed; once the turn is over,
    /// the outcome picked again and Accept pressed again posts it.
    /// </summary>
    [Fact]
    public void ARefusedPressLeavesTheTypedNoteForTheRetry()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string Typed = "FICT first shown at an earlier sitting";
            await Reviewed(driver, Finding("F-001"));
            await driver.Route("POST", DispositionPath("F-001"), 409, TurnRunning);
            await Note(driver, "F-001", Typed);
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "accept");

            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal("TurnRunning", refused.GetProperty("refusalClass").GetString());
            Assert.Empty(Pressed(refused));
            Assert.Equal(Typed, await NoteBox(driver, "F-001"));

            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", Typed, "new_and_real")));
            await driver.ClearCalls();
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "accept");
            Assert.Equal("decision=accepted, note=" + Typed + ", triage=new_and_real", Body(Assert.Single(await DispositionCalls(driver))));
        });
    }

    /// <summary>
    /// Cycle 11's Tier 2 review (002 T368; owner decision 198A): a late triage keeps the note recorded first, so a different note
    /// sent with it is not kept, and the card says so in one line of the backend's words after the reply's sentence - where the
    /// box, which shows the recorded note and so invites the edit, goes back to it. F-001 is deferred with a note and no triage;
    /// the engineer edits the note, picks `new and real` and presses Defer again, and the reply keeps the Defer's note. The line
    /// lasts as the record's sentence above a refusal does: the next status written on the card, a refused press's, replaces it.
    /// </summary>
    [Fact]
    public void ALateTriageThatKeepsTheNoteRecordedFirstSaysSo()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string Kept = "FICT first shown at an earlier sitting";
            const string Edited = "FICT first shown at the sitting before this one";
            await Reviewed(driver, Finding("F-001", Disposition("deferred", Kept, null)));
            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("deferred", Kept, "new_and_real")));
            await Note(driver, "F-001", Edited);
            await driver.ClearCalls();
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "defer");

            Assert.Equal("decision=deferred, note=" + Edited + ", triage=new_and_real", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement late = await driver.Read(ReadCard("F-001"));
            Assert.Equal(LabelsSample.NoteNotKept, late.GetProperty("noteKept").GetString());
            Assert.Equal(Sentence("deferred", "new_and_real", Kept) + LabelsSample.NoteNotKept, late.GetProperty("status").GetString());
            Assert.Equal("card-status decided", late.GetProperty("statusClass").GetString());
            Assert.Equal(Kept, await NoteBox(driver, "F-001"));

            await driver.Route("POST", DispositionPath("F-001"), 409, TurnRunning);
            await Decide(driver, "F-001", "defer");
            JsonElement refused = await driver.Read(ReadCard("F-001"));
            Assert.Equal("TurnRunning", refused.GetProperty("refusalClass").GetString());
            Assert.Equal(Sentence("deferred", "new_and_real", Kept), refused.GetProperty("record").GetString());
            Assert.Equal(JsonValueKind.Null, refused.GetProperty("noteKept").ValueKind);
        });
    }

    /// <summary>
    /// Cycle 11's Tier 2 review (002 T368), a guard: a reply that keeps the note the press sent says nothing of the note. F-001
    /// is accepted with no note and no triage; the engineer types the earlier sitting 188A asks for, picks `new and real` and
    /// presses Accept again, and the reply keeps that note (198A: none was recorded). F-002 is accepted with a note and no
    /// triage; its box shows the note, which goes back with a space typed after it, and the reply keeps the note recorded - the
    /// same note, the two compared trimmed. Each card shows the reply's sentence alone.
    /// </summary>
    [Fact]
    public void ALateTriageThatKeepsTheNoteSentSaysNothingOfIt()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string Dated = "FICT first shown at an earlier sitting";
            await Reviewed(
                driver,
                Finding("F-001", Disposition("accepted", string.Empty, null)),
                Finding("F-002", Disposition("accepted", "FICT first note", null)));
            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("accepted", Dated, "new_and_real")));
            await driver.Route("POST", DispositionPath("F-002"), 200,
                Finding("F-002", Disposition("accepted", "FICT first note", "already_known")));
            await driver.ClearCalls();

            await Note(driver, "F-001", Dated);
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "accept");
            await Note(driver, "F-002", "FICT first note ");
            await Press(driver, "F-002", "already_known");
            await Decide(driver, "F-002", "accept");

            Assert.Equal(
                new[]
                {
                    "decision=accepted, note=" + Dated + ", triage=new_and_real",
                    "decision=accepted, note=FICT first note , triage=already_known",
                },
                (await DispositionCalls(driver)).Select(Body).ToArray());
            JsonElement dated = await driver.Read(ReadCard("F-001"));
            Assert.Equal(Sentence("accepted", "new_and_real", Dated), dated.GetProperty("status").GetString());
            Assert.Equal(JsonValueKind.Null, dated.GetProperty("noteKept").ValueKind);
            JsonElement same = await driver.Read(ReadCard("F-002"));
            Assert.Equal(Sentence("accepted", "already_known", "FICT first note"), same.GetProperty("status").GetString());
            Assert.Equal(JsonValueKind.Null, same.GetProperty("noteKept").ValueKind);
        });
    }

    /// <summary>
    /// Cycle 11's Tier 2 review (002 T368), a guard: a press that sends no note says nothing of the note the reply keeps. F-001
    /// and F-002 are accepted with a note and no triage; the engineer empties F-001's box and leaves two spaces in F-002's - a
    /// blank note is none (198A) - picks `already known` on each and presses Accept again, and each reply keeps the note
    /// recorded. Each card shows the reply's sentence alone, and its box the recorded note.
    /// </summary>
    [Fact]
    public void ALateTriageSentWithNoNoteSaysNothingOfTheNote()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await Reviewed(
                driver,
                Finding("F-001", Disposition("accepted", "FICT first note", null)),
                Finding("F-002", Disposition("accepted", "FICT second note", null)));
            await driver.Route("POST", DispositionPath("F-001"), 200,
                Finding("F-001", Disposition("accepted", "FICT first note", "already_known")));
            await driver.Route("POST", DispositionPath("F-002"), 200,
                Finding("F-002", Disposition("accepted", "FICT second note", "already_known")));
            await driver.ClearCalls();

            await Note(driver, "F-001", string.Empty);
            await Press(driver, "F-001", "already_known");
            await Decide(driver, "F-001", "accept");
            await Note(driver, "F-002", "  ");
            await Press(driver, "F-002", "already_known");
            await Decide(driver, "F-002", "accept");

            Assert.Equal(
                new[] { "decision=accepted, note=, triage=already_known", "decision=accepted, note=  , triage=already_known" },
                (await DispositionCalls(driver)).Select(Body).ToArray());
            JsonElement emptied = await driver.Read(ReadCard("F-001"));
            Assert.Equal(Sentence("accepted", "already_known", "FICT first note"), emptied.GetProperty("status").GetString());
            Assert.Equal(JsonValueKind.Null, emptied.GetProperty("noteKept").ValueKind);
            Assert.Equal("FICT first note", await NoteBox(driver, "F-001"));
            JsonElement blank = await driver.Read(ReadCard("F-002"));
            Assert.Equal(Sentence("accepted", "already_known", "FICT second note"), blank.GetProperty("status").GetString());
            Assert.Equal(JsonValueKind.Null, blank.GetProperty("noteKept").ValueKind);
            Assert.Equal("FICT second note", await NoteBox(driver, "F-002"));
        });
    }

    /// <summary>
    /// A read-only check of cycle 11's Tier 2 fixes (002 T368), a guard, FR-030: with no labels there are no words for a note
    /// not kept, so the card says nothing of it - no line, not even an empty one - and its status line is the reply's sentence
    /// alone, the triage's token in it. F-001 is deferred with a note and no triage; the engineer edits the note, picks
    /// `new_and_real` and presses Defer again, and the reply keeps the Defer's note, as in
    /// <see cref="ALateTriageThatKeepsTheNoteRecordedFirstSaysSo"/>.
    /// </summary>
    [Fact]
    public void WithNoLabelsALateTriageThatKeepsTheNoteRecordedFirstSaysNothingOfIt()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            const string Kept = "FICT first shown at an earlier sitting";
            const string Edited = "FICT first shown at the sitting before this one";
            await Reviewed(driver, Finding("F-001", Disposition("deferred", Kept, null)));
            await driver.Route("POST", DispositionPath("F-001"), 200, Finding("F-001", Disposition("deferred", Kept, "new_and_real")));
            await Note(driver, "F-001", Edited);
            await driver.ClearCalls();
            await Press(driver, "F-001", "new_and_real");
            await Decide(driver, "F-001", "defer");

            Assert.Equal("decision=deferred, note=" + Edited + ", triage=new_and_real", Body(Assert.Single(await DispositionCalls(driver))));
            JsonElement late = await driver.Read(ReadCard("F-001"));
            Assert.Equal(JsonValueKind.Null, late.GetProperty("noteKept").ValueKind);
            Assert.Equal(
                "Disposition: deferred (new_and_real) by " + Engineer + " at " + RecordedAt + " - " + Kept,
                late.GetProperty("status").GetString());
            Assert.Equal(Kept, await NoteBox(driver, "F-001"));
        });
    }

    /// <summary>
    /// A read-only check of cycle 11's Tier 2 fixes (002 T368), at a docked pane's 300 px, the card where a real turn leaves it:
    /// the session's end reads the ranking, which puts F-007's card in its grouped row, shut. F-007 is deferred with a note and
    /// no triage, and a late triage sent with the note edited keeps the Defer's. With the row and the fold opened, the card's
    /// status line - the reply's sentence and the line saying the first note stays - the line itself and every triage button
    /// are whole - inside the window and every box that clips them, their words inside them - with no sideways page scroll, as
    /// every other line FR-031 puts on a card is.
    /// </summary>
    [Fact]
    public void ANoteNotKeptLineIsWhollyVisibleAtThreeHundredPixelsInItsRow()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string Kept = "FICT first shown at an earlier sitting";
            await ReviewPageSummaryAcceptanceTests.NarrowPane(driver);
            await driver.RouteAttention(Chat, SummarySample.Json());
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-007", Disposition("deferred", Kept, null)));
            await driver.EndSession(Chat);
            JsonElement placed = await driver.Read(ReadRow("F-007"));
            Assert.True(placed.GetProperty("inRow").GetBoolean(), "F-007's card is not in its grouped row.");
            Assert.False(placed.GetProperty("rowOpen").GetBoolean(), "F-007's row is open before the press.");
            await driver.Route("POST", DispositionPath("F-007"), 200, Finding("F-007", Disposition("deferred", Kept, "new_and_real")));
            await Note(driver, "F-007", "FICT first shown at the sitting before this one");
            await Press(driver, "F-007", "new_and_real");
            await Decide(driver, "F-007", "defer");

            JsonElement measured = await driver.Read(ReadNoteKeptWhole("F-007"));
            Assert.Equal(300, measured.GetProperty("width").GetInt32());
            Assert.True(measured.GetProperty("foldOpen").GetBoolean(), "the finding's fold did not open.");
            Assert.Equal(6, measured.GetProperty("count").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(measured, "clipped"));
            Assert.True(measured.GetProperty("noHorizontalOverflow").GetBoolean(), measured.ToString());
        });
    }

    /// <summary>
    /// A read-only check of cycle 9's Tier 2 fixes, a guard: a switch from a live review to a read-only restore draws every
    /// card's line again in the read-only words, since the page reads `state.readOnly` when it draws a card and sets it before
    /// a restore draws them. Chat-1 is live: its F-001 Accept, F-002 Reject and F-003 Defer, each recorded without a triage,
    /// say to press, and F-004, not yet decided, that it has none, every triage button on. The engineer chooses chat-2, which
    /// the backend no longer holds (`404 UnknownChat`), so the page restores it read-only from its run folder, holding the
    /// same four records: each card says the read-only words, naming no press, its buttons off.
    /// </summary>
    [Fact]
    public void ASwitchFromALiveReviewToAReadOnlyRestoreNamesNoPress()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Untriaged());
            await AssertNoTriageLines(driver, false);
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 404,
                Refusal("UnknownChat", "no chat " + OtherChat, false));
            await driver.Route("GET", "/reviews/" + OtherRun, 200, Snapshot(OtherRun, true, Untriaged()));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();

            await AssertNoTriageLines(driver, true);
        });
    }

    /// <summary>
    /// The same check, a guard: a switch from a read-only restore to a live review draws every card's line again in the words
    /// for where its record stands, since the switch resets `state.readOnly` before the live snapshot's cards are drawn. The
    /// engineer chooses chat-2, restored read-only as above, whose four cards say the read-only words; then chat-1 again,
    /// which the backend holds, and whose live snapshot holds the same four records: F-001, F-002 and F-003 say to press again,
    /// and F-004 that it has none, every triage button on.
    /// </summary>
    [Fact]
    public void ASwitchFromAReadOnlyRestoreToALiveReviewNamesTheRepairAgain()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            const string ChatRun = "20260923-101500-bracket-1";
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, ChatRun, ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 404,
                Refusal("UnknownChat", "no chat " + OtherChat, false));
            await driver.Route("GET", "/reviews/" + OtherRun, 200, Snapshot(OtherRun, true, Untriaged()));
            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            await AssertNoTriageLines(driver, true);

            await driver.Route("GET", "/sessions/" + Chat + "/snapshot", 200, Snapshot(ChatRun, false, Untriaged()));
            await driver.Read(ReviewPageSessionsTests.Chip(Chat));
            await driver.Settle();

            await AssertNoTriageLines(driver, false);
        });
    }

    /// <summary>
    /// Roadmap hole H-g-010 (002 T360): a withdrawal that takes a decided finding says what it took. F-001 is rejected as `wrong`
    /// and F-002 accepted as `already_known`; an answer's restate no longer produces either, and the backend withdraws each,
    /// naming the disposition and its clause. Each Transcript line ends with the clause after the reason, printed as sent -
    /// backend text, characters and never markup - and both cards leave Results, as any withdrawn one does.
    /// </summary>
    [Fact]
    public void AWithdrawalSaysWhatItTookAsSent()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "finding", Finding("F-002"));
            await driver.Push(Chat, 3, "disposition", DispositionEvent("F-001", RejectedWrong()));
            await driver.Push(Chat, 4, "disposition", DispositionEvent("F-002", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 5, "finding.withdrawn", Took("F-001", RejectedWrong(), TookRejectedWrong));
            await driver.Push(Chat, 6, "finding.withdrawn", Took("F-002", AcceptedAlreadyKnown(), HostileClause));
            await driver.Settle();

            string[] markers = ReviewPageDriver.Strings(await driver.Read(ReadTranscript), "markers");
            Assert.Contains("F-001 withdrawn: " + BoughtReason + "; " + TookRejectedWrong, markers);
            Assert.Contains("F-002 withdrawn: " + BoughtReason + "; " + HostileClause, markers);
            Assert.Equal(0, (await driver.Read(ReadInjected)).GetProperty("injected").GetInt32());
            Assert.Empty(ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));
        });
    }

    /// <summary>
    /// The line comes back with the Transcript (002 T360): a review switch restores chat-2 from its snapshot, the session after
    /// the withdrawal, and replays its stream from the start into the Transcript, where the withdrawal's line ends with the
    /// backend's clause, as it did live.
    /// </summary>
    [Fact]
    public void AReplayedWithdrawalSaysWhatItTook()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 200, Snapshot(OtherRun, false, Finding("F-002")));
            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();

            await driver.Click("view-transcript");
            await driver.Push(OtherChat, 1, "finding", Finding("F-001"));
            await driver.Push(OtherChat, 2, "finding", Finding("F-002"));
            await driver.Push(OtherChat, 3, "disposition", DispositionEvent("F-001", RejectedWrong()));
            await driver.Push(OtherChat, 4, "finding.withdrawn", Took("F-001", RejectedWrong(), TookRejectedWrong));
            await driver.Settle();

            Assert.Contains(
                "F-001 withdrawn: " + BoughtReason + "; " + TookRejectedWrong,
                ReviewPageDriver.Strings(await driver.Read(ReadTranscript), "markers"));
        });
    }

    /// <summary>
    /// A fold's withdrawal is not this case (002 T360; a guard): the re-run's own id leaves, naming the id it took, and its line
    /// says why and nothing of a decision, while the cleared line on F-001's card says what the fold took.
    /// </summary>
    [Fact]
    public void AFoldsWithdrawalSaysNothingOfADecision()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "disposition", DispositionEvent("F-001", AcceptedAlreadyKnown()));
            await driver.Push(Chat, 3, "finding", Finding("F-002", null, "suspected", "low"));
            await driver.Push(Chat, 4, "finding.withdrawn", Folded("F-002", "F-001"));
            await driver.Push(Chat, 5, "finding", Finding("F-001", null, "suspected", "low"));
            await driver.Push(Chat, 6, "disposition.cleared", Cleared("F-001", AcceptedAlreadyKnown()));
            await driver.Settle();

            string[] markers = ReviewPageDriver.Strings(await driver.Read(ReadTranscript), "markers");
            Assert.Contains("F-002 withdrawn: a second verdict on what F-001 judges, shown as F-001", markers);
            Assert.DoesNotContain(markers, marker => marker.IndexOf("went with it", StringComparison.Ordinal) >= 0);
            Assert.Equal(ClearedLine, (await driver.Read(ReadCard("F-001"))).GetProperty("status").GetString());
        });
    }

    // ---- four Review page fixes, the owner's pick (002 T372; cycle 13) ---------------------------

    /// <summary>
    /// The tally counts a finding a resumed turn adds as it arrives (the backlog's cycle 7 section): a `finding` event carries
    /// the review's tally, as the disposition events do, and the page shows it as sent. F-001's Accept as `already known` is the
    /// review's one triage; the resumed turn announces F-002, flagged and undecided, its tally counting it not recorded, and the
    /// page shows that count at once, not when the turn ends. Then the fold announces F-001 again with another verdict, its
    /// Accept cleared, so its event's tally is null - the review records no triage any more - and the tally goes, as a
    /// disposition event that carries none takes it.
    /// *Changed 2026-11-02 (cycle 13's Tier 2 review):* the fold's event named no tally. The backend now names one on every
    /// `finding` event, null while no finding records a triage, so the page tells it from an older backend's, which names none
    /// and leaves the tally as it was (<see cref="AnOlderBackendsFindingLeavesTheTallyAsItWas"/>).
    /// </summary>
    [Fact]
    public void AFindingAnnouncedWithTheTallyShowsItAsItArrives()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            JsonObject accepted = Tally(0, 1, 0, 0, 0, 0);
            JsonObject added = Tally(0, 1, 0, 0, 1, 0);
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "disposition", WithTally(DispositionEvent("F-001", AcceptedAlreadyKnown()), accepted));
            await driver.Settle();
            Assert.Equal(Lines(accepted), ReviewPageDriver.Strings(await driver.Read(ReadTally), "lines"));

            await driver.Push(Chat, 3, "finding", WithTally(Finding("F-002"), added));
            await driver.Settle();
            JsonElement counted = await driver.Read(ReadTally);
            Assert.True(counted.GetProperty("shown").GetBoolean(), "the finding's tally is not shown.");
            Assert.Equal(Lines(added), ReviewPageDriver.Strings(counted, "lines"));
            Assert.Equal(new[] { "F-001", "F-002" }, ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));

            await driver.Push(Chat, 4, "finding", WithTally(Finding("F-001", null, "suspected", "low"), null));
            await driver.Settle();
            JsonElement gone = await driver.Read(ReadTally);
            Assert.False(gone.GetProperty("shown").GetBoolean(), "a tally is shown after a finding whose tally is null: " + gone);
            Assert.Empty(ReviewPageDriver.Strings(gone, "lines"));
        });
    }

    /// <summary>
    /// A backend of cycles 7 to 12 sends the tally on the disposition events and never on a `finding` event (009 FR-030), so a
    /// finding it announces - a resumed turn's, or a fold's - leaves the tally as it was, as before cycle 13, until a
    /// disposition event or the turn's end sends another (cycle 13's Tier 2 review). F-001's Accept as `already known` is the
    /// review's one triage; F-002, announced after it with no tally named, leaves that tally shown.
    /// </summary>
    [Fact]
    public void AnOlderBackendsFindingLeavesTheTallyAsItWas()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            JsonObject accepted = Tally(0, 1, 0, 0, 0, 0);
            await driver.StartReview();
            await driver.Push(Chat, 1, "finding", Finding("F-001"));
            await driver.Push(Chat, 2, "disposition", WithTally(DispositionEvent("F-001", AcceptedAlreadyKnown()), accepted));
            await driver.Push(Chat, 3, "finding", Finding("F-002"));
            await driver.Settle();

            JsonElement kept = await driver.Read(ReadTally);
            Assert.True(kept.GetProperty("shown").GetBoolean(), "an older backend's finding took the tally away: " + kept);
            Assert.Equal(Lines(accepted), ReviewPageDriver.Strings(kept, "lines"));
            Assert.Equal(new[] { "F-001", "F-002" }, ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));
        });
    }

    /// <summary>
    /// After a reload the page reads `/labels` and the snapshot at once (the backlog's cycle 9 section). Here the snapshot answers
    /// first and the labels are held: once they answer, every card carries the backend's words - its no-triage line and its
    /// triage buttons' words - as when the labels answer first. Chat-1's live snapshot holds F-001 not yet decided and F-002's
    /// Accept without a triage. Reloaded again with chat-1 gone from the backend, the page restores it read-only from its run
    /// folder, the labels held once more, and both cards say the read-only words.
    /// </summary>
    [Fact]
    public void CardsGetTheirWordsWhenTheSnapshotAnswersBeforeTheLabels()
    {
        const string ChatRun = "20260923-101500-bracket-1";
        string livePath = "/sessions/" + Chat + "/snapshot";
        string[] findings = { Finding("F-001"), Finding("F-002", Disposition("accepted", string.Empty, null)) };
        ReviewPageDriver.Run(
            driver =>
            {
                driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, ChatRun, ReviewPageDriver.ReviewedPath, 10, 15));
                driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
                driver.HeldInitialRoutes.Add(("GET", "/labels"));
                driver.InitialRoutes.Add(("GET", livePath, 200, Snapshot(ChatRun, false, findings)));
            },
            async driver =>
            {
                await LabelsAnswerAfter(driver, livePath);
                Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());
                Assert.Equal(LabelsSample.NoTriageAccepted, (await driver.Read(ReadNoTriage("F-002"))).GetProperty("text").GetString());
                Assert.Equal(ContractTriages().Select(Word).ToArray(), ReviewPageDriver.Strings(await driver.Read(ReadCard("F-001")), "words"));

                driver.InitialRoutes.RemoveAll(route => route.Path == livePath);
                driver.InitialRoutes.Add(("GET", livePath, 404, ReviewPageRecheckTests.UnknownChat));
                driver.InitialRoutes.Add(("GET", "/reviews/" + ChatRun, 200, Snapshot(ChatRun, true, findings)));
                await driver.Reload();
                await LabelsAnswerAfter(driver, "/reviews/" + ChatRun);
                foreach (string id in new[] { "F-001", "F-002" })
                {
                    Assert.Equal(LabelsSample.NoTriageReadOnly, (await driver.Read(ReadNoTriage(id))).GetProperty("text").GetString());
                }
            });
    }

    /// <summary>
    /// A restore read that fails before the labels answer draws its error card once they have, as a snapshot is drawn (cycle
    /// 13's Tier 2 review): drawn first, the card would say no next step, and nothing would draw it again. After a reload
    /// chat-1's live snapshot read answers 500 with no error body, which the page names `HttpError`, while the labels are
    /// held; reloaded again with chat-1 gone from the backend, its run folder's read answers so too. Each time, once the labels
    /// answer, the one error card says the backend's sentence for that class.
    /// </summary>
    [Fact]
    public void ARestoreReadThatFailsBeforeTheLabelsSaysWhatToDoNext()
    {
        const string ChatRun = "20260923-101500-bracket-1";
        string livePath = "/sessions/" + Chat + "/snapshot";
        ReviewPageDriver.Run(
            driver =>
            {
                driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, ChatRun, ReviewPageDriver.ReviewedPath, 10, 15));
                driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
                driver.HeldInitialRoutes.Add(("GET", "/labels"));
                driver.InitialRoutes.Add(("GET", livePath, 500, "null"));
            },
            async driver =>
            {
                await LabelsAnswerAfter(driver, livePath);
                JsonElement live = await driver.Read(ReadErrorCards);
                Assert.Equal(1, live.GetProperty("cards").GetInt32());
                Assert.Equal(LabelsSample.HttpError, live.GetProperty("sentence").GetString());

                driver.InitialRoutes.RemoveAll(route => route.Path == livePath);
                driver.InitialRoutes.Add(("GET", livePath, 404, ReviewPageRecheckTests.UnknownChat));
                driver.InitialRoutes.Add(("GET", "/reviews/" + ChatRun, 500, "null"));
                await driver.Reload();
                await LabelsAnswerAfter(driver, "/reviews/" + ChatRun);
                JsonElement folder = await driver.Read(ReadErrorCards);
                Assert.Equal(1, folder.GetProperty("cards").GetInt32());
                Assert.Equal(LabelsSample.HttpError, folder.GetProperty("sentence").GetString());
            });
    }

    /// <summary>
    /// A restore read for a review the engineer left before the labels answered draws nothing once they have (cycle 13's
    /// read-only check of its Tier 2 review's fixes): after the wait each restore read checks again that its review is the one
    /// shown, for a failure's error card (`restoreFailed`) as for the live snapshot and the run folder's. After a reload with
    /// the labels held the page restores chat-1, the newest review of the document, and the engineer chooses chat-2, whose live
    /// snapshot holds F-001 and F-002, before the labels answer. Chat-1's live snapshot read answers 500; reloaded, 200 with
    /// F-007; reloaded again, `UnknownChat`, its run folder's read answering 200 with F-007 read-only. Each time, once the
    /// labels answer, Results hold chat-2's two cards alone, in the backend's words, and no error card.
    /// </summary>
    [Fact]
    public void AReviewLeftBeforeTheLabelsAnswerDrawsNothingIntoTheNext()
    {
        const string ChatRun = "20260923-101500-bracket-1";
        string livePath = "/sessions/" + Chat + "/snapshot";
        string folderPath = "/reviews/" + ChatRun;
        ReviewPageDriver.Run(
            driver =>
            {
                driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
                driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, ChatRun, ReviewPageDriver.ReviewedPath, 10, 15));
                driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json()));
                driver.HeldInitialRoutes.Add(("GET", "/labels"));
                driver.InitialRoutes.Add(("GET", "/sessions/" + OtherChat + "/snapshot", 200,
                    Snapshot(OtherRun, false, Finding("F-001"), Finding("F-002"))));
                driver.InitialRoutes.Add(("GET", livePath, 500, "null"));
            },
            async driver =>
            {
                await LeftBeforeTheLabels(driver, livePath);

                driver.InitialRoutes.RemoveAll(route => route.Path == livePath);
                driver.InitialRoutes.Add(("GET", livePath, 200, Snapshot(ChatRun, false, Finding("F-007"))));
                await driver.Reload();
                await LeftBeforeTheLabels(driver, livePath);

                driver.InitialRoutes.RemoveAll(route => route.Path == livePath);
                driver.InitialRoutes.Add(("GET", livePath, 404, ReviewPageRecheckTests.UnknownChat));
                driver.InitialRoutes.Add(("GET", folderPath, 200, Snapshot(ChatRun, true, Finding("F-007"))));
                await driver.Reload();
                await LeftBeforeTheLabels(driver, folderPath);
            });
    }

    /// <summary>
    /// A read-only restore after a backend restart replays no Transcript (H-g-010's *Left open*), so its snapshot names, under
    /// `withdrawn`, each withdrawal that took a decision, from the record's own stream, and the Transcript prints each after its
    /// note that the transcript is in the run folder, worded as the live line: the reason, then the backend's clause, as sent -
    /// characters, never markup. Results hold the snapshot's cards alone.
    /// </summary>
    [Fact]
    public void AReadOnlyRestoresTranscriptShowsEachWithdrawalWithADecision()
    {
        ReviewPageDriver.Run(Labelled, async driver =>
        {
            driver.Sessions.Add(ReviewPageSessionsTests.Item(OtherChat, OtherRun, ReviewPageDriver.ReviewedPath, 8, 30));
            driver.Sessions.Add(ReviewPageSessionsTests.Item(Chat, "20260923-101500-bracket-1", ReviewPageDriver.ReviewedPath, 10, 15));
            await Reviewed(driver, Finding("F-009"));
            await driver.Route("GET", "/sessions/" + OtherChat + "/snapshot", 404,
                Refusal("UnknownChat", "no chat " + OtherChat, false));
            await driver.Route("GET", "/reviews/" + OtherRun, 200, WithWithdrawn(
                Snapshot(OtherRun, true, Finding("F-002")),
                Took("F-001", RejectedWrong(), TookRejectedWrong),
                Took("F-003", AcceptedAlreadyKnown(), HostileClause)));

            await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
            await driver.Settle();
            await driver.Click("view-transcript");

            JsonElement transcript = await driver.Read(ReadRestoredTranscript);
            Assert.Equal(
                new[]
                {
                    "F-001 withdrawn: " + BoughtReason + "; " + TookRejectedWrong,
                    "F-003 withdrawn: " + BoughtReason + "; " + HostileClause,
                },
                ReviewPageDriver.Strings(transcript, "markers"));
            Assert.True(transcript.GetProperty("noteFirst").GetBoolean(), "a withdrawal is not after the restored Transcript's note.");
            Assert.Equal(0, (await driver.Read(ReadInjected)).GetProperty("injected").GetInt32());
            Assert.Equal(new[] { "F-002" }, ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));
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

    /// <summary>
    /// After a boot or a reload whose labels are held (002 cycle 13): the page has read and been answered
    /// <paramref name="snapshotPath"/> and asked for the labels, which then answer.
    /// </summary>
    private static async Task LabelsAnswerAfter(ReviewPageDriver driver, string snapshotPath)
    {
        await driver.Settle();
        string[] asked = (await driver.Calls())
            .Select(call => call.GetProperty("method").GetString() + " " + call.GetProperty("path").GetString())
            .ToArray();
        Assert.Contains("GET " + snapshotPath, asked);
        Assert.Contains("GET /labels", asked);
        await driver.ReleaseRoute("GET", "/labels");
    }

    /// <summary>
    /// After a boot or a reload whose labels are held, with chat-1 being restored (002 cycle 13's read-only check): once the page
    /// has read <paramref name="readPath"/> for it, the engineer chooses chat-2, and then the labels answer. Results hold chat-2's
    /// two cards alone, the first saying in the backend's words that it has no triage, and no error card.
    /// </summary>
    private static async Task LeftBeforeTheLabels(ReviewPageDriver driver, string readPath)
    {
        await driver.Settle();
        Assert.Contains(
            "GET " + readPath,
            (await driver.Calls()).Select(call => call.GetProperty("method").GetString() + " " + call.GetProperty("path").GetString()));
        await driver.Read(ReviewPageSessionsTests.Chip(OtherChat));
        await LabelsAnswerAfter(driver, "/sessions/" + OtherChat + "/snapshot");
        Assert.Equal(0, (await driver.Read(ReadErrorCards)).GetProperty("cards").GetInt32());
        Assert.Equal(new[] { "F-001", "F-002" }, ReviewPageDriver.Strings(await driver.Read(ReadCards), "ids"));
        Assert.Equal(LabelsSample.NoTriageUndecided, (await driver.Read(ReadNoTriage("F-001"))).GetProperty("text").GetString());
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

    /// <summary>What one card's note box holds, as the next press would post it (owner decision 198A).</summary>
    private static async Task<string> NoteBox(ReviewPageDriver driver, string findingId) =>
        (await driver.Read(
            "var box = document.querySelector('.card.finding[data-finding-id=\"" + findingId + "\"] input.note');"
            + "if (!box) { return JSON.stringify({ok: false, error: 'no note box on " + findingId + "'}); }"
            + "return JSON.stringify({ok: true, note: box.value});"))
        .GetProperty("note").GetString()!;

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

    /// <summary>
    /// Each of <see cref="UntriagedCards"/>' cards holds one no-triage line: on a live review its own words, with its triage
    /// buttons on; on a read-only review the read-only words, whatever its decision, with its buttons off.
    /// </summary>
    private static async Task AssertNoTriageLines(ReviewPageDriver driver, bool readOnly)
    {
        foreach (var card in UntriagedCards)
        {
            JsonElement line = await driver.Read(ReadNoTriage(card.Id));
            Assert.Equal(1, line.GetProperty("count").GetInt32());
            Assert.Equal(readOnly ? LabelsSample.NoTriageReadOnly : card.Words, line.GetProperty("text").GetString());
            Assert.All(Disabled(await driver.Read(ReadCard(card.Id))), off => Assert.Equal(readOnly, off));
        }
    }

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

    /// <summary>
    /// One flagged finding in each state `labels.no_triage` words, none with a triage - an Accept, a Reject and a Defer
    /// recorded without one, and a finding not yet decided - with its card's words on a live review (roadmap hole H-c-008).
    /// </summary>
    private static readonly (string Id, string? Decision, string Words)[] UntriagedCards =
    {
        ("F-001", "accepted", LabelsSample.NoTriageAccepted),
        ("F-002", "rejected", LabelsSample.NoTriageRejected),
        ("F-003", "deferred", LabelsSample.NoTriageDeferred),
        ("F-004", null, LabelsSample.NoTriageUndecided),
    };

    /// <summary><see cref="UntriagedCards"/> as findings, each disposition recorded without a triage.</summary>
    private static string[] Untriaged() =>
        UntriagedCards
            .Select(card => Finding(card.Id, card.Decision == null ? null : Disposition(card.Decision, string.Empty, null)))
            .ToArray();

    /// <summary>
    /// A `disposition.cleared` body as the runner writes it: the finding, the disposition cleared and the line - or, with
    /// <paramref name="reason"/>, as a read-only snapshot names it (002 cycle 13).
    /// </summary>
    private static string Cleared(string findingId, Dictionary<string, object?> disposition, string reason = ClearedLine) =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "finding_id", findingId },
            { "disposition", disposition },
            { "reason", reason },
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

    /// <summary>
    /// <paramref name="body"/> - a reply or an event body - carrying <paramref name="tally"/>, as the backend adds it, or null,
    /// as it names it on a `finding` event while no finding records a triage (cycle 13's Tier 2 review).
    /// </summary>
    private static string WithTally(string body, JsonObject? tally)
    {
        JsonObject node = JsonNode.Parse(body)!.AsObject();
        node["triage_tally"] = tally?.DeepClone();
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

    /// <summary>Why an answer's restate withdrew a finding, as the runner words it (`BOUGHT_WITHDRAWAL`).</summary>
    private const string BoughtReason = "bought part (your answer to ER-001)";

    /// <summary>
    /// The backend's clause for a Reject recorded as `wrong` that a withdrawal took (roadmap hole H-g-010): the words file's
    /// `withdrawn.took_with_triage`, filled as `withdraw_findings` fills it and sent as the body's `taken`.
    /// </summary>
    private const string TookRejectedWrong = "your Reject (wrong) went with it";

    /// <summary>A clause no page could compose, markup that must reach the Transcript as characters (FR-029).</summary>
    private const string HostileClause = "<img src=x onerror=alert(8)></p><script>alert(9)</script> went with it";

    /// <summary>F-001's Reject with `wrong`, recorded before an answer withdrew it (roadmap hole H-g-010).</summary>
    private static Dictionary<string, object?> RejectedWrong() => Disposition("rejected", "FICT not a problem", "wrong");

    /// <summary>
    /// The `finding.withdrawn` body of a finding that held a decision, as `withdraw_findings` writes it (roadmap hole H-g-010):
    /// the reason, the disposition that went with it and <paramref name="clause"/>, the backend's words naming it.
    /// </summary>
    private static string Took(string findingId, Dictionary<string, object?> disposition, string clause) =>
        JsonSerializer.Serialize(new Dictionary<string, object?>
        {
            { "finding_id", findingId },
            { "reason", BoughtReason },
            { "disposition", disposition },
            { "taken", clause },
        });

    /// <summary>
    /// <paramref name="snapshot"/> naming <paramref name="withdrawals"/> - `finding.withdrawn` bodies that took a decision -
    /// under `withdrawn`, as a read-only restore names them from the record's own stream (002 cycle 13).
    /// </summary>
    private static string WithWithdrawn(string snapshot, params string[] withdrawals)
    {
        JsonObject node = JsonNode.Parse(snapshot)!.AsObject();
        node["withdrawn"] = new JsonArray(withdrawals.Select(body => JsonNode.Parse(body)).ToArray());
        return node.ToJsonString();
    }

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
  clearedFirst: !!status && h.before(status.querySelector('.card-cleared'), status.querySelector('.plain-error')),
  noteKept: status ? h.text(status, '.card-note-kept') : null
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
    /// A restored review's Transcript (002 cycle 13): its finding markers, and whether its note that the transcript is in the
    /// run folder comes before the first of them.
    /// </summary>
    private const string ReadRestoredTranscript = @"
var transcript = document.getElementById('transcript');
return JSON.stringify({
  ok: true,
  markers: h.texts(transcript, '.marker'),
  noteFirst: h.before(transcript.querySelector('.restored'), transcript.querySelector('.marker'))
});";

    /// <summary>Results' error cards: how many, and the last one's sentence in the backend's words (null with no labels).</summary>
    private const string ReadErrorCards = @"
var cards = document.querySelectorAll('#errors .card.error');
var card = cards[cards.length - 1];
return JSON.stringify({ ok: true, cards: cards.length, sentence: card ? h.text(card, '.plain-error-text') : null });";

    /// <summary>How many elements backend text injected into the Transcript.</summary>
    private const string ReadInjected = @"
return JSON.stringify({ ok: true, injected: h.injected(document.getElementById('transcript')) });";

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
    /// After a late triage that kept the note recorded first (cycle 11's Tier 2 review): opens the grouped row one card stands
    /// in, then measures the card's status line, the line saying the first note stays and every triage button, as
    /// <see cref="ReadRefusalWhole"/> measures; a line that is missing counts as cut off.
    /// </summary>
    private static string ReadNoteKeptWhole(string findingId) => ReadPartsWhole(findingId, @"
var row = card.closest('details.type-row');
if (row) { row.open = true; }
var status = card.querySelector('.card-status');
var parts = [
  ['status', status],
  ['line', status.querySelector('.card-note-kept')]
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
