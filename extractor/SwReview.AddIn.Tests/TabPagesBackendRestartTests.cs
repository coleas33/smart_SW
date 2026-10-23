using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 145A, the pages' half: every tab that holds the backend's port and token, not
/// only Review (<see cref="ReviewPageBackendRestartTests"/>), follows a settings restart. Each is
/// the real page in an offscreen WebView2, under the real CSP, with this class playing the host.
///
/// The Model check and Standards pages call their check routes themselves with the port and token
/// of their `init`, and the Remodel page keeps them so one `init` field means one thing on every
/// tab. A restart - a save's made at once, or one made after it waited - starts a backend on
/// another port with another token, and nothing told these pages: every call they made with the
/// old token was refused 401 (143A, owner question 3). Now the host posts `backend.restarted`,
/// and each page asks `ready` again - once more after an `init` already on its way, which the host
/// may have read before the new backend was up. On that `init` a page takes the new port and token
/// and leaves what the engineer is looking at as it is: a check page does not read its latest
/// check again, and the Remodel page does not read its latest run again (research 145A).
///
/// Owner decision 150A adds what a failed or stopped backend leaves on these tabs: the strip says
/// the backend is not running from the add-in's word that it did not start until an `init` names
/// one, `backend.stopped` sends the engineer to save the settings on the Review tab, and an Accept
/// whose re-read is dropped for a newer check says its exception is saved.
/// </summary>
public sealed class TabPagesBackendRestartTests
{
    /// <summary>`backend.restarted` as these pages' hosts post it: none of the Review tab's sentences.</summary>
    private static readonly object Restarted = new { sentences = new string[0] };

    private const string RestartedToken = "FICT-token-after-the-restart";

    /// <summary>The three tabs besides Review that hold the backend's port and token.</summary>
    public static IEnumerable<object[]> Tabs =>
        TabPageDriver.Kinds.Select(kind => new object[] { kind });

    /// <summary>The two tabs that call the backend themselves.</summary>
    public static IEnumerable<object[]> CheckTabs => new[]
    {
        new object[] { TabPageDriver.ModelCheck },
        new object[] { TabPageDriver.Standards },
    };

    [Theory]
    [MemberData(nameof(Tabs))]
    public void ABackendRestartedIsAskedForAgain(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            driver.Token = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();

            // Once: one `ready` for one restart, not one per message the page then handles.
            Assert.Equal(readies + 1, driver.Readies);
        });
    }

    /// <summary>
    /// An `init` already on its way when `backend.restarted` arrives may have been read before the
    /// new backend was up, so the page asks once more after it - not a second `ready` beside it,
    /// and not one per restart message while it waits.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ARestartAnnouncedWhileAnInitIsOnItsWayIsFollowedByOneMoreAsk(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            driver.HoldReady = true;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init");
            await driver.Post("backend.restarted", Restarted);
            await driver.Settle();
            Assert.Equal(readies + 1, driver.Readies);
            Assert.Equal(1, driver.HeldReady);

            driver.Token = RestartedToken;
            await driver.ReleaseReady();
            await driver.Until(() => driver.Readies == readies + 2, "asked once more");
            await driver.Settle();
            Assert.Equal(readies + 2, driver.Readies);
        });
    }

    /// <summary>Each tab with its first init on reload, or an ordinary restart's init, held back.</summary>
    public static IEnumerable<object[]> TabsAndInitKinds =>
        TabPageDriver.Kinds.SelectMany(kind => new[] { new object[] { kind, false }, new object[] { kind, true } });

    /// <summary>
    /// T300: an init overtaken by a lifecycle failure cannot revive the old backend, clear its failure, or
    /// read a result with the obsolete endpoint. A replacement init retains the first load's latest-result
    /// intent; an ordinary restart still leaves the result on screen without reading it again.
    /// </summary>
    [Theory]
    [MemberData(nameof(TabsAndInitKinds))]
    public void AnInitReadBeforeALifecycleFailureCannotReviveTheFailedBackend(string tab, bool firstInit)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            driver.HoldReady = true;
            if (firstInit)
            {
                await driver.Reload(holdInit: true);
            }
            else
            {
                await driver.Post("backend.restarted", Restarted);
            }

            await driver.Until(() => driver.HeldReady == 1, "held the init read before the failure");
            await driver.ClearCalls();
            int reads = await driver.LatestResultReads();
            await driver.Post("status", new { stage = "error", message = BackendFailure, lifecycle = true });
            await driver.ReleaseOneReady();

            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal(BackendFailure, await driver.Banner());
            Assert.Empty(await driver.Calls());
            Assert.Equal(reads, await driver.LatestResultReads());
            await driver.Until(() => driver.HeldReady == 1, "held the fresh init request");

            driver.Token = RestartedToken;
            await driver.ReleaseReady();
            Assert.Equal(("Backend ready", false), await driver.Strip());
            Assert.Null(await driver.Banner());
            if (firstInit)
            {
                await driver.UntilReads(reads + 1, "read the latest result from the fresh init");
            }

            Assert.Equal(reads + (firstInit ? 1 : 0), await driver.LatestResultReads());
            Assert.True(await driver.RowsShown() > 0);
            Assert.DoesNotContain(await driver.Calls(), call =>
                call.GetProperty("authorization").GetString() == "Bearer " + TabPageDriver.FirstToken);
        });
    }

    /// <summary>A stale init refusal also leaves the newer lifecycle failure visible until fresh state arrives.</summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ARefusedInitOvertakenByALifecycleFailureDoesNotReplaceTheFailure(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            driver.HoldReady = true;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.HeldReady == 1, "held the earlier init request");
            await driver.Post("status", new { stage = "error", message = BackendFailure, lifecycle = true });
            await driver.RefuseOneReady();

            Assert.Equal(BackendFailure, await driver.Banner());
            Assert.Equal((NotRunning, true), await driver.Strip());
            await driver.Until(() => driver.HeldReady == 1, "held the fresh init request");
            driver.Token = RestartedToken;
            await driver.ReleaseReady();
            Assert.Equal(("Backend ready", false), await driver.Strip());
            Assert.Null(await driver.Banner());
        });
    }

    /// <summary>
    /// The page takes the restarted backend's token from that `init`: its next call - the check
    /// pressed again - carries it, and no call carries the old one, which the new backend refuses.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void TheNextCallAfterARestartCarriesTheRestartedBackendsToken(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            driver.Token = RestartedToken;
            await driver.ClearCalls();

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();
            await driver.Click("run-check");
            await driver.UntilCall("POST", "a check called after the restart");

            JsonElement[] calls = await driver.Calls();
            JsonElement check = Assert.Single(calls, call => call.GetProperty("method").GetString() == "POST");
            Assert.Equal("Bearer " + RestartedToken, check.GetProperty("authorization").GetString());
            Assert.DoesNotContain(calls, call =>
                call.GetProperty("authorization").GetString() == "Bearer " + TabPageDriver.FirstToken);
        });
    }

    /// <summary>
    /// A check pressed just as the backend restarts. The host extracts on the check tab's own pump,
    /// so the `ready` the page asks on `backend.restarted` waits there behind the extraction, and
    /// the extraction's reply reaches the page first. The page's call to the check route waits for
    /// the `init` on its way and carries the restarted backend's token: made at once, it carried the
    /// old one, which the new backend refuses, and the extraction was wasted (owner decision 145A,
    /// found on review).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ACheckPressedWhileAnInitIsOnItsWayCallsWithTheRestartedBackendsToken(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            await driver.ClearCalls();
            driver.HoldReady = true;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
            await driver.Click("run-check");
            await driver.Settle();

            // The extraction has answered, and the call waits for the `init` on its way.
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("method").GetString() == "POST");

            driver.Token = RestartedToken;
            await driver.ReleaseReady();
            await driver.UntilCall("POST", "the check's call once the init arrived");

            JsonElement[] calls = await driver.Calls();
            JsonElement check = Assert.Single(calls, call => call.GetProperty("method").GetString() == "POST");
            Assert.Equal("Bearer " + RestartedToken, check.GetProperty("authorization").GetString());
            Assert.DoesNotContain(calls, call =>
                call.GetProperty("authorization").GetString() == "Bearer " + TabPageDriver.FirstToken);
        });
    }

    /// <summary>
    /// The call waits for the last `init` a restart asks for, not the first: a second restart
    /// announced while the first `init` was on its way makes the page ask once more after it, since
    /// the host may have answered the first before the new backend was up - with the old token, as
    /// here - and the call carries the token the last one leaves.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ACallWaitsForTheOneMoreAskARestartAnnouncedMeanwhileMakes(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            await driver.ClearCalls();
            driver.HoldReady = true;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
            await driver.Click("run-check");
            await driver.Post("backend.restarted", Restarted);

            // The first `init` names the old token; the page asks once more after it.
            await driver.ReleaseOneReady();
            await driver.Until(() => driver.Readies == readies + 2, "asked once more");
            await driver.Settle();
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("method").GetString() == "POST");

            driver.Token = RestartedToken;
            await driver.ReleaseReady();
            await driver.UntilCall("POST", "the check's call once the last init arrived");

            JsonElement check = Assert.Single(
                await driver.Calls(), call => call.GetProperty("method").GetString() == "POST");
            Assert.Equal("Bearer " + RestartedToken, check.GetProperty("authorization").GetString());
        });
    }

    /// <summary>
    /// A check tab opened while the backend restarts: the host's `init` names the backend that is
    /// going, so the page's read of its latest check is refused by the one that replaced it, and the
    /// tab has nothing to show. The `init` the restart's message asks for reads it again, with the
    /// new token, so the tab does not stay blank (owner decision 145A, found on review). A latest
    /// check the page did read is not read again (the case below).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ALatestCheckTheOldTokenCouldNotReadIsReadAgainAfterTheRestart(string tab)
    {
        TabPageDriver.Run(
            tab,
            driver =>
            {
                driver.WithLatestResult = true;
                driver.AcceptedToken = RestartedToken;
            },
            async driver =>
            {
                await driver.UntilTheLatestResultIsRead();
                await driver.Settle();
                Assert.Equal(0, await driver.RowsShown());
                int readies = driver.Readies;
                driver.Token = RestartedToken;

                await driver.Post("backend.restarted", Restarted);
                await driver.Until(() => driver.Readies > readies, "asked for init again");
                await driver.UntilReads(2, "read its latest check again");
                await driver.Settle();

                JsonElement[] reads = (await driver.Calls())
                    .Where(call => call.GetProperty("method").GetString() == "GET")
                    .ToArray();
                Assert.Equal(2, reads.Length);
                Assert.Equal("Bearer " + TabPageDriver.FirstToken, reads[0].GetProperty("authorization").GetString());
                Assert.Equal("Bearer " + RestartedToken, reads[1].GetProperty("authorization").GetString());
                await driver.WhatIsShown();
            });
    }

    /// <summary>
    /// A latest check the old token could not read is read again only while it is still what the tab
    /// would show: not under a check the engineer has pressed since, whose result is on its way, nor
    /// over the result that check left - the result on screen is the engineer's, and stays.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ALatestCheckTheOldTokenCouldNotReadIsNotReadOverACheckPressedSince(string tab)
    {
        TabPageDriver.Run(
            tab,
            driver =>
            {
                driver.WithLatestResult = true;
                driver.AcceptedToken = RestartedToken;
            },
            async driver =>
            {
                await driver.UntilTheLatestResultIsRead();
                await driver.Settle();
                int readies = driver.Readies;
                driver.HoldReady = true;
                driver.Token = RestartedToken;

                // The engineer presses Check while the restart's `init` is on its way.
                await driver.Post("backend.restarted", Restarted);
                await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
                await driver.Click("run-check");
                await driver.ReleaseReady();
                await driver.UntilCall("POST", "the check's call");
                await driver.Settle();

                // And the backend restarts once more, the check's result on screen.
                await driver.Post("backend.restarted", Restarted);
                await driver.Until(() => driver.Readies == readies + 2, "asked for init again");
                await driver.Settle();

                Assert.Equal(1, await driver.LatestResultReads());
                await driver.WhatIsShown();
            });
    }

    /// <summary>
    /// A latest check read again once it could be is done with: a check pressed afterwards that
    /// fails before anything is graded - the Standards page clears its verdict then, on purpose -
    /// and a later restart do not bring the old check back (owner decision 145A, found on the
    /// third review: the flag that asked for the re-read was never cleared, and the Standards page
    /// showed the old verdict again under the failure).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ALatestCheckReadOnceItCouldBeIsNotReadAgainAfterACheckThatFailed(string tab)
    {
        TabPageDriver.Run(
            tab,
            driver =>
            {
                driver.WithLatestResult = true;
                driver.AcceptedToken = RestartedToken;
            },
            async driver =>
            {
                await driver.UntilTheLatestResultIsRead();
                await driver.Settle();
                int readies = driver.Readies;
                driver.Token = RestartedToken;

                await driver.Post("backend.restarted", Restarted);
                await driver.UntilReads(2, "read its latest check again");
                await driver.Settle();
                await driver.WhatIsShown();

                driver.StartRefusal = ("ExtractionFailed", "FICT the extraction failed before anything was graded.");
                await driver.Click("run-check");
                await driver.Settle();
                int rowsAfterTheFailure = await driver.RowsShown();

                await driver.Post("backend.restarted", Restarted);
                await driver.Until(() => driver.Readies == readies + 2, "asked for init again");
                await driver.Settle();

                Assert.Equal(2, await driver.LatestResultReads());
                Assert.Equal(rowsAfterTheFailure, await driver.RowsShown());
            });
    }

    /// <summary>
    /// A latest check read again once it could be is not read again by the restart after that:
    /// the read that failed has been answered (third review).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ALatestCheckReadOnceItCouldBeIsNotReadAgainByALaterRestart(string tab)
    {
        TabPageDriver.Run(
            tab,
            driver =>
            {
                driver.WithLatestResult = true;
                driver.AcceptedToken = RestartedToken;
            },
            async driver =>
            {
                await driver.UntilTheLatestResultIsRead();
                await driver.Settle();
                int readies = driver.Readies;
                driver.Token = RestartedToken;

                await driver.Post("backend.restarted", Restarted);
                await driver.UntilReads(2, "read its latest check again");
                await driver.Settle();
                await driver.Post("backend.restarted", Restarted);
                await driver.Until(() => driver.Readies == readies + 2, "asked for init again");
                await driver.Settle();

                Assert.Equal(2, await driver.LatestResultReads());
                await driver.WhatIsShown();
            });
    }

    /// <summary>
    /// A latest-check read made before a check was pressed is done with once the check is pressed:
    /// answered after it, it is not shown - here over a check that failed, whose cleared screen
    /// is the engineer's - and refused after it, it is not read again by a later `init` (third
    /// review).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ALatestCheckReadMadeBeforeACheckWasPressedIsNotShownAfterIt(string tab)
    {
        TabPageDriver.Run(
            tab,
            driver =>
            {
                driver.WithLatestResult = true;
                driver.HoldGetsAtBoot = true;
            },
            async driver =>
            {
                await driver.UntilTheLatestResultIsRead();
                driver.StartRefusal = ("ExtractionFailed", "FICT the extraction failed before anything was graded.");
                await driver.Click("run-check");
                await driver.Settle();

                await driver.ReleaseGets();

                Assert.Equal(0, await driver.RowsShown());
            });
    }

    /// <summary>The same read, refused after the press: it is not remembered as one to read again.</summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ALatestCheckReadRefusedAfterACheckWasPressedIsNotReadAgain(string tab)
    {
        TabPageDriver.Run(
            tab,
            driver =>
            {
                driver.WithLatestResult = true;
                driver.HoldGetsAtBoot = true;
                driver.AcceptedToken = RestartedToken;
            },
            async driver =>
            {
                await driver.UntilTheLatestResultIsRead();
                driver.StartRefusal = ("ExtractionFailed", "FICT the extraction failed before anything was graded.");
                await driver.Click("run-check");
                await driver.Settle();
                await driver.ReleaseGets();
                int readies = driver.Readies;
                driver.Token = RestartedToken;

                await driver.Post("backend.restarted", Restarted);
                await driver.Until(() => driver.Readies > readies, "asked for init again");
                await driver.Settle();

                Assert.Equal(1, await driver.LatestResultReads());
            });
    }

    /// <summary>
    /// An `init` the host refuses still lets the calls waiting for it go: they wait for an `init`
    /// on its way, not for one that succeeds, and a check pressed meanwhile still calls its route
    /// - with the token the page holds, which the backend answers as it answers it (third review:
    /// nothing pinned it, and with the calls let go only after an `init` that was applied, every
    /// later call waited for ever).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ARefusedInitStillLetsTheCallsWaitingForItGo(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            await driver.ClearCalls();
            driver.HoldReady = true;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
            await driver.Click("run-check");
            await driver.Settle();
            Assert.DoesNotContain(await driver.Calls(), call => call.GetProperty("method").GetString() == "POST");

            await driver.RefuseOneReady();

            await driver.UntilCall("POST", "the check's call once its init was refused");
        });
    }

    /// <summary>
    /// An Accept and a check, both waiting for the `init` a restart asked for, are let go together:
    /// the newer check can be shown before the Accept's re-read of the older one lands. That
    /// re-read is stale and is not shown - the newer check stays on screen, and no row of it is
    /// marked as the one just accepted (third review: 145A's waiting calls made the order possible).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void AnAcceptsReReadMadeStaleByANewerCheckIsNotShown(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await AcceptAndANewerCheckAreLetGoTogether(driver);

            Assert.StartsWith("Checked", await driver.TextOf("check-state"), StringComparison.Ordinal);
            Assert.Equal(0, await driver.JustAccepted());
        });
    }

    /// <summary>
    /// ...but the exception that Accept wrote is saved, and the page says so, in its notice, as it
    /// says so of an Accept whose re-read failed - naming the exception, why its check was not
    /// shown again, and the way on - so the engineer is not left to accept the rule a second time
    /// (owner decision 150A; until then the dropped re-read said nothing).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void AnAcceptWhoseReReadIsDroppedSaysItsExceptionIsSaved(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await AcceptAndANewerCheckAreLetGoTogether(driver);

            Assert.Equal(
                "Accepted as " + TabPageDriver.ExceptionId + ", and the exception is saved; a newer check was "
                    + "pressed before this check was re-read. Press the check again to see where it stands.",
                await driver.AcceptNotice());
        });
    }

    /// <summary>
    /// An Accept whose re-read failed says so in the same place and the same way - the exception it
    /// wrote, why its check is not shown again, the way on - since before 150A; the one helper that
    /// now says both is pinned by both.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void AnAcceptWhoseReReadFailsSaysItsExceptionWasWrittenAndWhy(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            await driver.Settle();
            await driver.WhatIsShown();
            await driver.RefuseGets();

            await driver.AcceptTheFirstRule();
            await driver.UntilAcceptNotice("said the Accept's re-read failed");

            Assert.Equal(
                "Accepted as " + TabPageDriver.ExceptionId + ", but the check could not be re-read: "
                    + TabPageDriver.RefusedGet + " Press the check again to see where it stands.",
                await driver.AcceptNotice());
        });
    }

    /// <summary>
    /// Owner decision 160A: a check that fails and an Accept's notice no longer share one banner. The notice -
    /// the one word that the exception is saved - has its own place beside the check's status, and the failure
    /// keeps the banner, whichever lands first. On the Standards page, whose failed check clears the result,
    /// both orders make a notice. The Model check page keeps its result when a check fails (decided on the
    /// decision's review, for the owner): a failure first leaves the result the Accept's re-read is shown on,
    /// so the rule is marked accepted on its row and in the check's line beside the failure, and no notice is
    /// made; a notice first is kept through the press and the failure, as on the Standards page.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabsAndOrders))]
    public void ACheckFailureAndAnAcceptNoticeBothStayVisible(string tab, bool failureFirst)
    {
        const string Failure = "FICT the extraction failed before anything was graded.";
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            await driver.Settle();
            await driver.HoldGets();
            await driver.AcceptTheFirstRule();
            await driver.UntilReads(2, "asked to re-read the accepted check");

            if (failureFirst)
            {
                driver.StartRefusal = ("ExtractionFailed", Failure);
                await driver.Click("run-check");
                await driver.UntilBanner("showed the check's failure");
                await driver.ReleaseGets();
            }
            else
            {
                await driver.RefuseGets();
                await driver.ReleaseGets();
                await driver.UntilAcceptNotice("showed the Accept's notice");
                driver.StartRefusal = ("ExtractionFailed", Failure);
                await driver.Click("run-check");
                await driver.UntilBanner("showed the check's failure");
            }

            Assert.Equal(Failure, await driver.Banner());
            if (failureFirst && tab == TabPageDriver.ModelCheck)
            {
                Assert.Null(await driver.AcceptNotice());
                Assert.Equal(1, await driver.JustAccepted());
                Assert.StartsWith("Accepted as " + TabPageDriver.ExceptionId, await driver.TextOf("check-state"), StringComparison.Ordinal);
                return;
            }

            string notice = Assert.IsType<string>(await driver.AcceptNotice());
            Assert.StartsWith("Accepted as " + TabPageDriver.ExceptionId, notice, StringComparison.Ordinal);
            Assert.Contains("Press the check again to see where it stands.", notice, StringComparison.Ordinal);
        });
    }

    /// <summary>Each check tab, with a failed check landing first and last.</summary>
    public static IEnumerable<object[]> CheckTabsAndOrders =>
        from row in CheckTabs
        from failureFirst in new[] { false, true }
        select new object[] { row[0], failureFirst };

    /// <summary>
    /// A second Accept's notice takes the place of the first, as the banner it replaced did: the one notice says
    /// where the newest Accept stands (the review of owner decision 160A).
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void ASecondAcceptsNoticeTakesThePlaceOfTheFirst(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            await driver.Settle();
            await driver.RefuseGets();
            await driver.AcceptTheFirstRule();
            await driver.UntilAcceptNotice("said the first Accept's re-read failed");
            int reads = await driver.LatestResultReads();

            await driver.AcceptTheFirstRule();
            await driver.UntilReads(reads + 1, "asked to re-read the second Accept's check");
            await driver.Settle();

            Assert.Equal(
                "Accepted as " + TabPageDriver.ExceptionId + ", but the check could not be re-read: "
                    + TabPageDriver.RefusedGet + " Press the check again to see where it stands.",
                await driver.AcceptNotice());
        });
    }

    /// <summary>
    /// ...and the notice comes down once a result is shown again (decided on the review of decision 160A):
    /// it says the exception is saved and to press the check again to see where it stands, which a result
    /// shown - a check pressed again, or another Accept whose re-read is shown - then says. Until 160A the
    /// banner that carried it came down at the next press; its own place has no press to take it down, and
    /// a notice left up over a result that shows the rule accepted would be a false line.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabsAndWaysShown))]
    public void AnAcceptsNoticeComesDownOnceAResultIsShownAgain(string tab, string shown)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            await driver.Settle();
            await driver.RefuseGets();
            await driver.AcceptTheFirstRule();
            await driver.UntilAcceptNotice("said the Accept's re-read failed");
            await driver.AnswerGets();

            if (shown == "a check pressed again")
            {
                await driver.Click("run-check");
                await driver.UntilText(
                    "check-state", text => text.StartsWith("Checked", StringComparison.Ordinal), "showed the check pressed again");
            }
            else
            {
                await driver.AcceptTheFirstRule();
                await driver.UntilText(
                    "check-state", text => text.StartsWith("Accepted as", StringComparison.Ordinal), "showed the Accept's re-read");
            }

            Assert.Null(await driver.AcceptNotice());
        });
    }

    /// <summary>Each check tab, with a check pressed again and with another Accept.</summary>
    public static IEnumerable<object[]> CheckTabsAndWaysShown =>
        from row in CheckTabs
        from shown in new[] { "a check pressed again", "another Accept" }
        select new object[] { row[0], shown };

    /// <summary>
    /// An Accept and a check, both waiting for the `init` a restart asked for, let go together: the
    /// newer check is shown before the Accept's re-read of the older one lands.
    /// </summary>
    private static async Task AcceptAndANewerCheckAreLetGoTogether(TabPageDriver driver)
    {
        await driver.UntilTheLatestResultIsRead();
        await driver.Settle();
        await driver.WhatIsShown();
        int readies = driver.Readies;
        driver.HoldReady = true;
        driver.Token = RestartedToken;

        await driver.Post("backend.restarted", Restarted);
        await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
        await driver.AcceptTheFirstRule();
        await driver.Click("run-check");
        await driver.HoldGets();

        await driver.ReleaseReady();
        await driver.UntilText("check-state", text => text.StartsWith("Checked", StringComparison.Ordinal), "showed the newer check");
        await driver.ReleaseGets();
    }

    /// <summary>The add-in's word that the backend did not start, as a failed start or restart tells every tab.</summary>
    private const string BackendFailure = "FICT the review backend did not start: the handshake timed out.";

    /// <summary>
    /// The banner the page put up for the add-in's word that the backend did not start - a failed
    /// start or restart, `status {stage: "error", lifecycle: true}` - comes down once a later `init`
    /// names a backend: the next restart that works makes it untrue. An `init` that names none
    /// leaves it (owner decision 145A, third review: the banner stayed under "Backend ready" until
    /// the tab's next press).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ALifecycleErrorBannerComesDownOnceALaterInitNamesABackend(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            await driver.Post("status", new { stage = "error", message = BackendFailure, lifecycle = true });
            Assert.Equal(BackendFailure, await driver.Banner());

            driver.NoBackend = true;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
            await driver.Settle();
            Assert.Equal(BackendFailure, await driver.Banner());

            driver.NoBackend = false;
            driver.Token = RestartedToken;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 2, "asked for init again");
            await driver.Settle();
            Assert.Null(await driver.Banner());
        });
    }

    /// <summary>
    /// Only that banner: an error the page was told that is not the backend's own - a check or a run
    /// that stopped - stays through a restart's `init`, and so does any banner that took the place
    /// of the backend's word since.
    /// </summary>
    [Theory]
    [MemberData(nameof(TabsAndBanners))]
    public void ABannerThatIsNotTheBackendsWordStaysThroughARestartsInit(string tab, string banner)
    {
        const string Other = "FICT the check stopped part way through.";
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            if (banner == "not the backend's")
            {
                await driver.Post("status", new { stage = "error", message = Other });
            }
            else
            {
                await driver.Post("status", new { stage = "error", message = BackendFailure, lifecycle = true });
                await driver.Post("error", new { error_class = "HostError", message = Other, retryable = false });
            }

            Assert.Equal(Other, await driver.Banner());
            driver.Token = RestartedToken;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
            await driver.Settle();

            Assert.Equal(Other, await driver.Banner());
        });
    }

    /// <summary>Every tab, with a banner of each kind that is not the backend's word on screen.</summary>
    public static IEnumerable<object[]> TabsAndBanners =>
        TabPageDriver.Kinds.SelectMany(kind => new[]
        {
            new object[] { kind, "not the backend's" },
            new object[] { kind, "in the backend's place" },
        });

    /// <summary>What the strip says from the add-in's word that the backend did not start (owner decision 150A).</summary>
    private const string NotRunning = "Backend not running";

    /// <summary>The way on the Model check, Standards and Remodel pages put on their banner after a failed start (owner decision 160A).</summary>
    private const string OtherTabsWayOn = "The backend is not running. Save Settings on the Review tab to start it again.";

    /// <summary>
    /// Owner decision 160A: a page that loads, or loads again, after a failed start or restart - whose `status` it never
    /// saw - is told so by `init` (`backend_start_failed`) and says the backend is not running, with the way on the add-in
    /// gives the other tabs, where it said "Backend starting"; an `init` that names a backend takes both down.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void APageLoadedOrReloadedAfterAFailedStartSaysTheBackendIsNotRunningAndHowToStartIt(string tab)
    {
        TabPageDriver.Run(tab, driver =>
        {
            driver.NoBackend = true;
            driver.BackendStartFailed = true;
        }, async driver =>
        {
            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal("The backend is not running. Save Settings on the Review tab to start it again.", await driver.Banner());

            await driver.Reload();
            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal("The backend is not running. Save Settings on the Review tab to start it again.", await driver.Banner());

            driver.NoBackend = false;
            driver.BackendStartFailed = false;
            int readies = driver.Readies;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for the running backend");
            await driver.Settle();
            Assert.Equal(("Backend ready", false), await driver.Strip());
            Assert.Null(await driver.Banner());
        });
    }

    /// <summary>
    /// ...but the way on takes the banner only when it says nothing else (the review of owner decision 160A): a
    /// word already there - another error the page was told - stays, and the strip says the backend is not running.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AFailedStartsWayOnLeavesAnotherWordOnTheBanner(string tab)
    {
        const string Other = "FICT another word the page was told.";
        TabPageDriver.Run(tab, null, async driver =>
        {
            await driver.Post("error", new { error_class = "HostError", message = Other, retryable = false });
            await driver.Settle();
            Assert.Equal(Other, await driver.Banner());

            driver.NoBackend = true;
            driver.BackendStartFailed = true;
            int readies = driver.Readies;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for the failed backend");
            await driver.Settle();

            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal(Other, await driver.Banner());
        });
    }

    /// <summary>
    /// The review of owner decision 160A (D2): a `ready` status while an `init` is on its way is asked about once
    /// more after that `init`, as `backend.restarted` is. The `init` on its way can have been read before the
    /// backend was up - naming none, and with the last start's failure - and delivered after the `ready`: dropped,
    /// the ask would leave the page saying the backend is not running while it is up.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AReadyStatusWhileAnInitIsOnItsWayIsAskedAboutOnceMoreAfterIt(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.NoBackend = true, async driver =>
        {
            driver.HoldReady = true;
            await driver.Post("status", new { stage = "ready", message = "Backend ready." });
            await driver.Until(() => driver.HeldReady == 1, "asked for the backend the status named");
            await driver.Post("status", new { stage = "ready", message = "Backend ready." });
            await driver.Settle();
            Assert.Equal(1, driver.HeldReady);

            driver.BackendStartFailed = true;
            await driver.ReleaseOneReady();
            await driver.Settle();
            Assert.Equal(1, driver.HeldReady);

            driver.NoBackend = false;
            driver.BackendStartFailed = false;
            await driver.ReleaseReady();
            Assert.Equal(("Backend ready", false), await driver.Strip());
            Assert.Null(await driver.Banner());
        });
    }

    /// <summary>
    /// The final review of owner decision 160A: the ask once more after an `init` on its way - a `backend.restarted`, or
    /// a `ready` status, met one - reads no check again, as the restart's own ask reads none: the check on screen is the
    /// engineer's.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void TheAskOnceMoreReadsTheLatestCheckNoMore(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            await driver.Settle();
            int reads = await driver.LatestResultReads();
            int readies = driver.Readies;

            driver.HoldReady = true;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.HeldReady == 1, "asked after the restart");
            await driver.Post("backend.restarted", Restarted);
            await driver.Settle();
            await driver.ReleaseOneReady();
            await driver.Until(() => driver.HeldReady == 1, "asked once more after the init on its way");
            await driver.ReleaseReady();
            await driver.Settle();

            Assert.Equal(readies + 2, driver.Readies);
            Assert.Equal(reads, await driver.LatestResultReads());
        });
    }

    /// <summary>...while one that loads before the first start has finished, which has not failed, still says it is starting.</summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void APageLoadedBeforeTheFirstStartFinishesStillSaysBackendStarting(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.NoBackend = true, async driver =>
        {
            Assert.Equal(("Backend starting", true), await driver.Strip());
            Assert.Null(await driver.Banner());
        });
    }

    /// <summary>
    /// The Remodel page with no seat, after a failed start: the seat's own word keeps the banner, with the way on after
    /// it, rather than one covering the other (owner decision 160A).
    /// </summary>
    [Fact]
    public void ARemodelPageWithNoSeatStillNamesTheWayOnAfterAFailedStart()
    {
        TabPageDriver.Run(TabPageDriver.Remodel, driver =>
        {
            driver.NoBackend = true;
            driver.BackendStartFailed = true;
            driver.RemodelAvailable = false;
        }, async driver =>
        {
            Assert.Equal((NotRunning, true), await driver.Strip());
            string banner = Assert.IsType<string>(await driver.Banner());
            Assert.Contains(TabPageDriver.NoRemodelSeat, banner, StringComparison.Ordinal);
            Assert.Contains("Save Settings on the Review tab to start it again.", banner, StringComparison.Ordinal);
        });
    }

    /// <summary>
    /// The final review of owner decision 160A (item 1): every attach or detach of the tool service refreshes the Remodel
    /// page's seat (`document.changed` with `remodel`), which this build has none of. After a failed start the banner
    /// keeps the way on after the seat's word, as an `init` puts them, where the refresh wrote the seat's word alone
    /// while the strip said the backend is not running.
    /// </summary>
    [Fact]
    public void ASeatRefreshAfterAFailedStartKeepsTheWayOnAfterTheSeatsWord()
    {
        TabPageDriver.Run(TabPageDriver.Remodel, driver =>
        {
            driver.NoBackend = true;
            driver.BackendStartFailed = true;
            driver.RemodelAvailable = false;
        }, async driver =>
        {
            Assert.Equal(TabPageDriver.NoRemodelSeat + " " + OtherTabsWayOn, await driver.Banner());

            await driver.Post("document.changed", new
            {
                path = @"C:\Fictional\bracket.sldprt",
                configuration = "Default",
                kind = "part",
                remodel = new { available = false, message = TabPageDriver.NoRemodelSeat },
            });
            await driver.Settle();

            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal(TabPageDriver.NoRemodelSeat + " " + OtherTabsWayOn, await driver.Banner());
        });
    }

    /// <summary>
    /// A deferred restart can stop the backend the Remodel page already held and then fail. Its lifecycle status
    /// makes that endpoint obsolete: a later seat refresh still keeps the way on after the seat's word.
    /// </summary>
    [Fact]
    public void ASeatRefreshAfterADeferredRestartFailedKeepsTheWayOnAfterTheSeatsWord()
    {
        TabPageDriver.Run(TabPageDriver.Remodel, driver => driver.RemodelAvailable = false, async driver =>
        {
            Assert.Equal(("Backend ready", false), await driver.Strip());
            Assert.Equal(TabPageDriver.NoRemodelSeat, await driver.Banner());

            await driver.Post("status", new
            {
                stage = "error",
                message = "FICT the backend did not restart. Save Settings on the Review tab to start it again.",
                lifecycle = true,
            });
            await driver.Settle();
            Assert.Equal((NotRunning, true), await driver.Strip());

            await driver.Post("document.changed", new
            {
                path = @"C:\Fictional\bracket.sldprt",
                configuration = "Default",
                kind = "part",
                remodel = new { available = false, message = TabPageDriver.NoRemodelSeat },
            });
            await driver.Settle();

            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal(TabPageDriver.NoRemodelSeat + " " + OtherTabsWayOn, await driver.Banner());
        });
    }

    /// <summary>
    /// ...and an `init` the host read before a start failed - no backend, and no failed start yet - and delivered after
    /// the add-in's word that it failed keeps the way on after the seat's word: the page's own mark says the backend is
    /// not running, where the stale `init`'s flag put up the seat's word alone.
    /// </summary>
    [Fact]
    public void AnInitReadBeforeAStartFailedKeepsTheWayOnAfterTheSeatsWord()
    {
        TabPageDriver.Run(TabPageDriver.Remodel, driver =>
        {
            driver.NoBackend = true;
            driver.RemodelAvailable = false;
        }, async driver =>
        {
            driver.HoldReady = true;
            await driver.Post("status", new { stage = "ready", message = "Backend ready." });
            await driver.Until(() => driver.HeldReady == 1, "asked for an init");
            await driver.Post("status", new
            {
                stage = "error",
                message = "FICT the backend did not start. Save Settings on the Review tab to start it again.",
                lifecycle = true,
            });
            await driver.Settle();
            Assert.Equal((NotRunning, true), await driver.Strip());

            await driver.ReleaseReady();

            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal(TabPageDriver.NoRemodelSeat + " " + OtherTabsWayOn, await driver.Banner());
        });
    }

    /// <summary>...an `init` that names a backend takes the way on down and leaves the seat's word, if it still holds.</summary>
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void ARemodelPageWithNoSeatDropsTheFailedBackendNoticeOnceAnInitNamesOne(bool seatAvailable)
    {
        TabPageDriver.Run(TabPageDriver.Remodel, driver =>
        {
            driver.NoBackend = true;
            driver.BackendStartFailed = true;
            driver.RemodelAvailable = false;
        }, async driver =>
        {
            driver.NoBackend = false;
            driver.BackendStartFailed = false;
            driver.RemodelAvailable = seatAvailable;
            int readies = driver.Readies;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for the running backend");
            await driver.Settle();

            Assert.Equal(("Backend ready", false), await driver.Strip());
            Assert.Equal(seatAvailable ? null : TabPageDriver.NoRemodelSeat, await driver.Banner());
        });
    }

    /// <summary>...and one that names a seat while the backend is still not running takes the seat's word down and leaves the way on.</summary>
    [Fact]
    public void ARemodelPageDropsTheSeatNoticeOnceItsInitNamesASeatWhileTheBackendIsStillNotRunning()
    {
        TabPageDriver.Run(TabPageDriver.Remodel, driver =>
        {
            driver.NoBackend = true;
            driver.BackendStartFailed = true;
            driver.RemodelAvailable = false;
        }, async driver =>
        {
            driver.RemodelAvailable = true;
            int readies = driver.Readies;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for the available seat");
            await driver.Settle();

            Assert.Equal((NotRunning, true), await driver.Strip());
            Assert.Equal("The backend is not running. Save Settings on the Review tab to start it again.", await driver.Banner());
        });
    }

    /// <summary>
    /// The strip follows the add-in's word that the backend did not start - a failed start or
    /// restart, `status {stage: "error", lifecycle: true}` - and says the backend is not running
    /// until an `init` names a backend again: through an `init` that names none, and back to
    /// "Backend ready" at the one that names one, where the banner comes down too. The word is then
    /// done with: an `init` naming none after it is a backend starting, as during a restart (owner
    /// decision 150A; until then the strip followed `init` alone, and said "Backend ready" under the
    /// banner that said the backend did not start).
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void TheStripSaysTheBackendIsNotRunningFromALifecycleErrorUntilAnInitNamesABackend(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            Assert.Equal(("Backend ready", false), await driver.Strip());

            await driver.Post("status", new { stage = "error", message = BackendFailure, lifecycle = true });
            Assert.Equal((NotRunning, true), await driver.Strip());

            driver.NoBackend = true;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
            await driver.Settle();
            Assert.Equal((NotRunning, true), await driver.Strip());

            driver.NoBackend = false;
            driver.Token = RestartedToken;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 2, "asked for init again");
            await driver.Settle();
            Assert.Equal(("Backend ready", false), await driver.Strip());

            driver.NoBackend = true;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 3, "asked for init once more");
            await driver.Settle();
            Assert.Equal(("Backend starting", true), await driver.Strip());
        });
    }

    /// <summary>
    /// A banner put up since the add-in's word - a check's failure, say, which takes its place - is
    /// not the backend starting: the strip still says it is not running through an `init` that
    /// names none. (The banner's own mark is cleared by any banner put up since, which is why the
    /// strip keeps one of its own.)
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ABannerPutUpSinceTheLifecycleErrorLeavesTheStripSayingTheBackendIsNotRunning(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            await driver.Post("status", new { stage = "error", message = BackendFailure, lifecycle = true });
            await driver.Post("error", new { error_class = "BackendUnavailable", message = "FICT the check could not reach the backend.", retryable = true });

            driver.NoBackend = true;
            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init again");
            await driver.Settle();

            Assert.Equal((NotRunning, true), await driver.Strip());
        });
    }

    /// <summary>
    /// Only the add-in's word: an error that is not the backend's - a check or a run that stopped -
    /// leaves the strip as it was.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void AnErrorThatIsNotTheBackendsWordLeavesTheStripAsItWas(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            await driver.Post("status", new { stage = "error", message = "FICT the check stopped part way through." });

            Assert.Equal(("Backend ready", false), await driver.Strip());
        });
    }

    /// <summary>
    /// `backend.stopped` names the way that starts the backend again (owner decision 150A): the
    /// add-in starts it when it loads and a settings save restarts it, and the settings are saved on
    /// the Review tab - so the sentence sends the engineer there, not to reopen the pane, which
    /// starts nothing.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ABackendStoppedNamesSavingTheSettingsOnTheReviewTabAsTheWayToStartItAgain(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            await driver.Post("backend.stopped", new { exit_code = 1, log_path = @"C:\Fictional\FICT-logs\backend.log" });

            Assert.Equal(
                ("The backend stopped. Save Settings on the Review tab to start it again.", true),
                await driver.Strip());
        });
    }

    /// <summary>
    /// The page keeps what the engineer is looking at. A check page's result - read back from its
    /// latest check when the page loaded - stays on screen as it was, and is not read again: the
    /// restart changed the backend, not the check, and a re-read would race whatever the page
    /// shows. The Remodel page's run stays too, and is not read again: its record is the run
    /// folder, which the host reads and the restart does not touch.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void WhatTheEngineerIsLookingAtStaysAndIsNotReadAgain(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            await driver.Settle();
            string before = await driver.WhatIsShown();
            int reads = await driver.LatestResultReads();
            int readies = driver.Readies;
            driver.Token = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();

            Assert.Equal(reads, await driver.LatestResultReads());
            Assert.Equal(before, await driver.WhatIsShown());
        });
    }

    /// <summary>
    /// A remodel run in progress is not the page's to end: Stop stays pressable and Start stays
    /// off through a restart's `init`, and the run is not read again under it. (The host makes no
    /// restart while a run is in progress; the run's own terminal `status` may still be on its way
    /// when the message for a restart made just after it arrives.)
    /// </summary>
    [Fact]
    public void ARemodelRunInProgressKeepsRunningThroughARestartsInit()
    {
        TabPageDriver.Run(TabPageDriver.Remodel, null, async driver =>
        {
            await driver.Click("plan-run");
            await driver.Click("start-run");
            Assert.False(await driver.Disabled("stop-run"));
            int reads = await driver.LatestResultReads();
            int readies = driver.Readies;
            driver.Token = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();

            Assert.False(await driver.Disabled("stop-run"));
            Assert.True(await driver.Disabled("start-run"));
            Assert.Equal(reads, await driver.LatestResultReads());
        });
    }

    /// <summary>
    /// One of the three pages driven as its host drives it: `ready` answered with the `init` its
    /// host sends, the page's start verbs with the reply its host gives, and - for the two check
    /// pages - `window.fetch` replaced by a stub that answers the check routes with the page's own
    /// sample and records each call with its `Authorization` header. The first `ready` is held
    /// until the stub is in place, since a check page reads its latest check the moment `init`
    /// names one.
    /// </summary>
    private sealed class TabPageDriver
    {
        public const string ModelCheck = "model-check";

        public const string Standards = "standards";

        public const string Remodel = "remodel";

        public static readonly string[] Kinds = { ModelCheck, Standards, Remodel };

        /// <summary>The page's own origin under the backend prefix, as every host's `init` names it.</summary>
        public const string Origin = "https://swreview.invalid/__backend";

        /// <summary>The token the backend started with, before any restart.</summary>
        public const string FirstToken = "FICT-token-before-the-restart";

        /// <summary>The exception the stubbed backend writes for an Accept, as its route answers it.</summary>
        public const string ExceptionId = "EXC-FICT-0001";

        /// <summary>Why the stubbed backend refuses a `GET` once <see cref="RefuseGets"/> is called.</summary>
        public const string RefusedGet = "FICT the check folder is gone.";

        /// <summary>The remodel seat's own word when the Remodel page's `init` says it is not available.</summary>
        public const string NoRemodelSeat = "FICT the remodel seat is unavailable.";

        private const string RemodelRunDir = @"C:\SwReviewRuns\20260916-142201-bracket-remodel";

        private readonly string _kind;
        private readonly object _gate = new object();
        private readonly List<(string Type, string? Id)> _posted = new List<(string, string?)>();
        private readonly Queue<string> _heldReady = new Queue<string>();
        private string? _bootReady;
        private bool _booted;
        private int _remodelResults;

        private TabPageDriver(string kind, CoreWebView2 page)
        {
            _kind = kind;
            Page = page;
        }

        public CoreWebView2 Page { get; }

        /// <summary>The token the next `init` hands out; a restart is a new one.</summary>
        public string Token { get; set; } = FirstToken;

        /// <summary>
        /// Whether `init` names a latest result for the page to read back - a check's folder, or a
        /// remodel run's - as the host does once the page has one.
        /// </summary>
        public bool WithLatestResult { get; set; }

        /// <summary>Holds every `ready` after the boot until <see cref="ReleaseReady"/>: an `init` on its way.</summary>
        public bool HoldReady { get; set; }

        /// <summary>
        /// The one token the stubbed backend accepts, or null for any: a call with another is refused
        /// 401 `Unauthorized`, as the backend refuses a token that is not its own. Set before the
        /// page loads, since the stub is put in place at the boot.
        /// </summary>
        public string? AcceptedToken { get; set; }

        /// <summary>
        /// Whether the stubbed backend holds every `GET` from the boot on, until
        /// <see cref="ReleaseGets"/>: a read in flight. Set before the page loads.
        /// </summary>
        public bool HoldGetsAtBoot { get; set; }

        /// <summary>
        /// When set, the host refuses the check's start - `check.start` or `standards.start` - with this
        /// class and message, as it refuses one that fails before anything is graded.
        /// </summary>
        public (string ErrorClass, string Message)? StartRefusal { get; set; }

        /// <summary>
        /// Whether `init` names no backend, as the host's does while none is up - after a start or a
        /// restart that failed, say.
        /// </summary>
        public bool NoBackend { get; set; }

        /// <summary>
        /// What `init` carries as `backend_start_failed`: whether the last start or restart failed with no
        /// backend up (owner decision 160A).
        /// </summary>
        public bool BackendStartFailed { get; set; }

        /// <summary>Whether the Remodel page's `init` says the remodel seat is available; when not, it says <see cref="NoRemodelSeat"/>.</summary>
        public bool RemodelAvailable { get; set; } = true;

        public int Readies => Count("ready");

        public int HeldReady
        {
            get
            {
                lock (_gate)
                {
                    return _heldReady.Count;
                }
            }
        }

        /// <summary>
        /// How many times the page has read its result back: each `remodel.result` it sent, or
        /// each `GET /checks/{check_id}` a check page made.
        /// </summary>
        public async Task<int> LatestResultReads()
        {
            if (_kind == Remodel)
            {
                lock (_gate)
                {
                    return _remodelResults;
                }
            }

            return (await Calls()).Count(call => call.GetProperty("method").GetString() == "GET");
        }

        /// <summary>Waits, bounded, until the page has read the latest result its `init` named.</summary>
        public Task UntilTheLatestResultIsRead() => UntilReads(1, "read the latest result its init named");

        /// <summary>Waits, bounded, until the page has read its result back <paramref name="reads"/> times.</summary>
        public async Task UntilReads(int reads, string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (await LatestResultReads() < reads)
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never " + what + ".");
                }

                await Task.Delay(5);
            }
        }

        /// <summary>How many rows of a result are on screen: a check's rules, or a run's changes.</summary>
        public async Task<int> RowsShown() =>
            JsonDocument.Parse(await Page.ExecuteScriptAsync(
                "document.querySelectorAll('.rule, #change-list li').length")).RootElement.GetInt32();

        /// <summary>The banner's text, or null while it is hidden.</summary>
        public async Task<string?> Banner()
        {
            string raw = await Page.ExecuteScriptAsync(
                "(function () { var banner = document.getElementById('banner'); "
                + "return banner.hidden ? null : banner.textContent; }())");
            JsonElement banner = JsonDocument.Parse(raw).RootElement;
            return banner.ValueKind == JsonValueKind.Null ? null : banner.GetString();
        }

        /// <summary>
        /// The Accept's notice in its own place, `accept-notice`, or null while it is hidden or the page has none:
        /// the Standards page's since owner decision 160A, and the Model check page's since its review.
        /// </summary>
        public async Task<string?> AcceptNotice()
        {
            string raw = await Page.ExecuteScriptAsync(
                "(function () { var note = document.getElementById('accept-notice'); "
                + "return !note || note.hidden ? null : note.textContent; }())");
            JsonElement note = JsonDocument.Parse(raw).RootElement;
            return note.ValueKind == JsonValueKind.Null ? null : note.GetString();
        }

        /// <summary>Loads the page again, as the engineer's reload does, and answers its first `ready` with `init`.</summary>
        public async Task Reload(bool holdInit = false)
        {
            _booted = false;
            _bootReady = null;
            Page.Reload();
            await BootAsync(holdInit);
        }

        /// <summary>The backend strip: its text, and whether it wears the warning colour.</summary>
        public async Task<(string Text, bool Warn)> Strip()
        {
            string raw = await Page.ExecuteScriptAsync(
                "(function () { var strip = document.getElementById('backend-state'); "
                + "return JSON.stringify({ text: strip.textContent, warn: strip.classList.contains('warn') }); }())");
            JsonElement strip = JsonDocument.Parse(JsonDocument.Parse(raw).RootElement.GetString() ?? "{}").RootElement;
            return (strip.GetProperty("text").GetString() ?? string.Empty, strip.GetProperty("warn").GetBoolean());
        }

        /// <summary>The text of one element of the page.</summary>
        public async Task<string> TextOf(string elementId) =>
            JsonDocument.Parse(await Page.ExecuteScriptAsync(
                "document.getElementById(" + JsonSerializer.Serialize(elementId) + ").textContent"))
                .RootElement.GetString() ?? string.Empty;

        /// <summary>Waits, bounded, until one element's text satisfies <paramref name="condition"/>.</summary>
        public async Task UntilText(string elementId, Func<string, bool> condition, string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (!condition(await TextOf(elementId)))
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never " + what + ".");
                }

                await Task.Delay(5);
            }
        }

        /// <summary>How many rule rows say they were just accepted.</summary>
        public async Task<int> JustAccepted() =>
            JsonDocument.Parse(await Page.ExecuteScriptAsync(
                "document.querySelectorAll('.rule.just-accepted').length")).RootElement.GetInt32();

        /// <summary>
        /// Accepts the first rule on screen that can be accepted, with a note, as the engineer does;
        /// answers its finding id.
        /// </summary>
        public async Task<string> AcceptTheFirstRule()
        {
            string raw = await Page.ExecuteScriptAsync(@"(function () {
  var button = document.querySelector('#rules .rule [data-action=""accept""]');
  if (!button) { return null; }
  var row = button.closest('.rule');
  row.querySelector('.note').value = 'FICT acceptable on this part for the test';
  button.click();
  return row.getAttribute('data-finding-id');
}())");
            JsonElement finding = JsonDocument.Parse(raw).RootElement;
            Assert.True(finding.ValueKind == JsonValueKind.String, "no rule on screen could be accepted.");
            await Settle();
            return finding.GetString()!;
        }

        /// <summary>From now on the stubbed backend holds every `GET`, until <see cref="ReleaseGets"/>.</summary>
        public Task HoldGets() => Page.ExecuteScriptAsync("window.__holdGets = true;0");

        /// <summary>From now on the stubbed backend refuses every `GET`, 404 `UnknownCheck`, saying <see cref="RefusedGet"/>.</summary>
        public Task RefuseGets() => Page.ExecuteScriptAsync("window.__refuseGets = true;0");

        /// <summary>From now on the stubbed backend answers every `GET` again, after <see cref="RefuseGets"/>.</summary>
        public Task AnswerGets() => Page.ExecuteScriptAsync("window.__refuseGets = false;0");

        /// <summary>Waits, bounded, until the banner shows.</summary>
        public async Task UntilBanner(string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (await Banner() == null)
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never " + what + ".");
                }

                await Task.Delay(5);
            }
        }

        /// <summary>Waits, bounded, until the Accept's notice shows (<see cref="AcceptNotice"/>).</summary>
        public async Task UntilAcceptNotice(string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (await AcceptNotice() == null)
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never " + what + ".");
                }

                await Task.Delay(5);
            }
        }

        /// <summary>Answers every `GET` held, and holds no more.</summary>
        public async Task ReleaseGets()
        {
            await Page.ExecuteScriptAsync("window.__releaseGets();0");
            await Settle();
        }

        public static void Run(string kind, Action<TabPageDriver>? configure, Func<TabPageDriver, Task> script)
        {
            TabPageDriver? driver = null;
            OffscreenReviewPage.WithPage(
                UrlOf(kind),
                page =>
                {
                    driver = new TabPageDriver(kind, page);
                    configure?.Invoke(driver);
                    page.WebMessageReceived += (sender, args) => driver.OnMessage(args.WebMessageAsJson);
                },
                async page =>
                {
                    await driver!.BootAsync();
                    await script(driver);
                });
        }

        /// <summary>Posts one unsolicited host message and lets the page handle it.</summary>
        public async Task Post(string type, object payload)
        {
            Page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id = (string?)null, payload }));
            await Settle();
        }

        public Task Settle() => OffscreenReviewPage.Settled(Page);

        /// <summary>Waits, bounded, until <paramref name="condition"/> about what the page posted holds.</summary>
        public async Task Until(Func<bool> condition, string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (!condition())
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never " + what + ".");
                }

                await Page.ExecuteScriptAsync("0");
                await Task.Delay(5);
            }
        }

        /// <summary>Waits, bounded, until the page has made a call with <paramref name="method"/>.</summary>
        public async Task UntilCall(string method, string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (!(await Calls()).Any(call => call.GetProperty("method").GetString() == method))
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never made " + what + ".");
                }

                await Task.Delay(5);
            }
        }

        public async Task ReleaseReady()
        {
            lock (_gate)
            {
                Assert.NotEmpty(_heldReady);
                HoldReady = false;
                while (_heldReady.Count > 0)
                {
                    Reply("init", _heldReady.Dequeue(), Init());
                }
            }

            await Settle();
        }

        /// <summary>Answers the oldest `ready` held, with <see cref="Token"/>, and goes on holding the rest.</summary>
        public async Task ReleaseOneReady()
        {
            lock (_gate)
            {
                Assert.NotEmpty(_heldReady);
                Reply("init", _heldReady.Dequeue(), Init());
            }

            await Settle();
        }

        /// <summary>
        /// Answers the oldest `ready` held with an error, as a host that cannot give its `init`
        /// answers it, and goes on holding the rest.
        /// </summary>
        public async Task RefuseOneReady()
        {
            lock (_gate)
            {
                Assert.NotEmpty(_heldReady);
                Reply("error", _heldReady.Dequeue(), new
                {
                    error_class = "HostError",
                    message = "FICT the host could not give its init",
                    retryable = false,
                });
            }

            await Settle();
        }

        public async Task Click(string elementId)
        {
            await Page.ExecuteScriptAsync("document.getElementById(" + JsonSerializer.Serialize(elementId) + ").click();0");
            await Settle();
        }

        public async Task<bool> Disabled(string elementId) =>
            JsonDocument.Parse(await Page.ExecuteScriptAsync(
                "document.getElementById(" + JsonSerializer.Serialize(elementId) + ").disabled")).RootElement.GetBoolean();

        /// <summary>Every backend call the page made since the last <see cref="ClearCalls"/>; none on the Remodel page.</summary>
        public async Task<JsonElement[]> Calls()
        {
            string raw = await Page.ExecuteScriptAsync("JSON.stringify(window.__calls || [])");
            string json = JsonDocument.Parse(raw).RootElement.GetString() ?? "[]";
            return JsonDocument.Parse(json).RootElement.EnumerateArray().Select(call => call.Clone()).ToArray();
        }

        public Task ClearCalls() => Page.ExecuteScriptAsync("window.__calls = [];0");

        /// <summary>
        /// What the engineer is looking at, read off the live page as one string: the result's
        /// header and rows, the line under the buttons and the folder on a check page; the run's
        /// folder, state, status line, change list and judgement on the Remodel page.
        /// </summary>
        public async Task<string> WhatIsShown()
        {
            string ids = _kind == Remodel
                ? "['run-dir','run-state','run-status','attestation','change-list','rebuild','judgement','banner']"
                : "['" + (_kind == ModelCheck ? "grade" : "verdict") + "','rules','check-state','run-dir','stale-result','banner']";
            string raw = await Page.ExecuteScriptAsync(
                "JSON.stringify({ shown: " + ids + ".map(function (id) { var node = document.getElementById(id); "
                + "return id + '=' + (node.hidden ? '[hidden]' : '') + node.textContent; })"
                + ".concat(['stale=' + document.body.classList.contains('result-stale')]).join(' | '), "
                + "rows: document.querySelectorAll('.rule, #change-list li').length })");
            JsonElement read = JsonDocument.Parse(JsonDocument.Parse(raw).RootElement.GetString() ?? "{}").RootElement;

            // A result is on screen to keep: rows of it, rendered from the latest result.
            Assert.True(read.GetProperty("rows").GetInt32() > 0, "no result is on screen: " + read.GetRawText());
            return read.GetProperty("shown").GetString() ?? string.Empty;
        }

        private static string UrlOf(string kind)
        {
            switch (kind)
            {
                case ModelCheck:
                    return ModelCheckPageFiles.PageUrl;
                case Standards:
                    return StandardsPageFiles.PageUrl;
                case Remodel:
                    return RemodelPageFiles.PageUrl;
                default:
                    throw new ArgumentOutOfRangeException(nameof(kind), kind, "no tab of that name");
            }
        }

        private int Count(string type)
        {
            lock (_gate)
            {
                return _posted.Count(message => message.Type == type);
            }
        }

        private async Task BootAsync(bool holdInit = false)
        {
            for (int attempt = 0; attempt < 400 && _bootReady == null; attempt++)
            {
                await Page.ExecuteScriptAsync("0");
                await Task.Delay(10);
            }

            Assert.True(_bootReady != null, "the " + _kind + " page never sent `ready`.");
            if (_kind != Remodel)
            {
                await Page.ExecuteScriptAsync(FetchStub(SampleJson(), AcceptedToken, HoldGetsAtBoot));
            }

            lock (_gate)
            {
                _booted = true;
                if (holdInit)
                {
                    HoldReady = true;
                    _heldReady.Enqueue(_bootReady!);
                }
                else
                {
                    Reply("init", _bootReady!, Init());
                }
            }

            await Settle();
        }

        private void OnMessage(string json)
        {
            JsonElement message = JsonDocument.Parse(json).RootElement;
            string type = message.GetProperty("type").GetString() ?? string.Empty;
            string? id = message.TryGetProperty("id", out JsonElement value) && value.ValueKind == JsonValueKind.String
                ? value.GetString()
                : null;

            lock (_gate)
            {
                _posted.Add((type, id));
                if ((type == "check.start" || type == "standards.start") && StartRefusal.HasValue)
                {
                    Reply("error", id, new
                    {
                        error_class = StartRefusal.Value.ErrorClass,
                        message = StartRefusal.Value.Message,
                        retryable = true,
                    });
                    return;
                }

                switch (type)
                {
                    case "ready":
                        if (!_booted)
                        {
                            _bootReady = id;
                        }
                        else if (HoldReady)
                        {
                            _heldReady.Enqueue(id!);
                        }
                        else
                        {
                            Reply("init", id, Init());
                        }

                        return;

                    case "check.start":
                        Reply("check.extracted", id, new
                        {
                            run_dir = @"C:\SwReviewRuns\20260916-101532-bracket-check",
                            document = @"C:\vault\bracket.sldprt",
                            configuration = "Default",
                            counts = new { documents = 1, features = 12, equations = 0 },
                            gaps = 0,
                        });
                        return;

                    case "standards.start":
                        Reply("standards.extracted", id, new
                        {
                            run_dir = @"C:\SwReviewRuns\20260917-101532-top-plate-standards",
                            document = @"C:\vault\top-plate.sldasm",
                            configuration = "AsBuilt",
                            counts = new { documents = 1, features = 12, cut_list_items = 0, drawing_sheets = 0 },
                            gaps = 0,
                        });
                        return;

                    case "remodel.plan":
                        Reply("remodel.planned", id, new
                        {
                            run_dir = RemodelRunDir,
                            plan_summary = JsonDocument.Parse(RemodelResultSample.PlanSummaryJson()).RootElement.Clone(),
                        });
                        return;

                    case "remodel.start":
                        Reply("remodel.started", id, new { chat_id = "20260916-142201-bracket-remodel" });
                        return;

                    case "remodel.result":
                        _remodelResults++;
                        Reply("remodel.result", id, JsonDocument.Parse(RemodelResultSample.ResultJson()).RootElement.Clone());
                        return;

                    default:
                        Reply("ok", id, new { });
                        return;
                }
            }
        }

        /// <summary>The `init` each host sends, for the backend that holds <see cref="Token"/>, or for none.</summary>
        private object Init()
        {
            object? backend = NoBackend ? null : new { port = 51234, origin = Origin };
            string? token = NoBackend ? null : Token;
            switch (_kind)
            {
                case ModelCheck:
                    return new
                    {
                        backend,
                        token,
                        backend_start_failed = BackendStartFailed,
                        run_root = @"C:\SwReviewRuns",
                        standards_profile = (string?)null,
                        document = new { path = @"C:\vault\bracket.sldprt", configuration = "Default", kind = "part" },
                        latest_check = WithLatestResult
                            ? new { run_dir = @"C:\SwReviewRuns\20260916-101532-bracket-check", at = "2026-09-16T10:15:32.0000000" }
                            : null,
                    };

                case Standards:
                    return new
                    {
                        backend,
                        token,
                        backend_start_failed = BackendStartFailed,
                        run_root = @"C:\SwReviewRuns",
                        profile_path = @"C:\Fictional\FICT-standards.yaml",
                        document = new { path = @"C:\vault\top-plate.sldasm", configuration = "AsBuilt", kind = "assembly" },
                        latest_check = WithLatestResult
                            ? new { run_dir = @"C:\SwReviewRuns\20260917-101532-top-plate-standards", at = "2026-09-17T10:15:32.0000000" }
                            : null,
                    };

                default:
                    return new
                    {
                        backend,
                        token,
                        backend_start_failed = BackendStartFailed,
                        run_root = @"C:\SwReviewRuns",
                        document = new { path = @"C:\vault\bracket.sldprt", configuration = "Default", kind = "part" },
                        limits = new { max_changes = 250, max_minutes = 20, max_rebuild_seconds = 120 },
                        remodel = new { available = RemodelAvailable, message = RemodelAvailable ? null : NoRemodelSeat },
                        latest_run = WithLatestResult
                            ? new { run_dir = RemodelRunDir, at = "2026-09-16T14:22:01.0000000", state = "saved", plan_lost = (string?)null }
                            : null,
                    };
            }
        }

        private string SampleJson() => _kind == ModelCheck ? CheckResultSample.Json() : StandardsResultSample.Json();

        /// <summary>
        /// Every check route answered with this page's sample, each call recorded with its method,
        /// its path with the origin stripped, and its `Authorization` header. A call that does not
        /// carry <paramref name="accepted"/>, when there is one, is refused as the backend refuses a
        /// token that is not its own (chat/server.py). A check - the `POST` to the family's route -
        /// is answered as a newer check than the sample, under a check id of its own, and an Accept -
        /// the `POST` to a finding's exceptions route - with the exception it wrote,
        /// <see cref="ExceptionId"/>; every `GET` is held while `window.__holdGets` is set - from
        /// the boot when <paramref name="holdGets"/> - and answered by `window.__releaseGets()`, and
        /// refused while `window.__refuseGets` is set.
        /// </summary>
        private static string FetchStub(string sample, string? accepted, bool holdGets) => @"
(function () {
  var origin = '" + Origin + @"';
  var sample = " + sample + @";
  var accepted = " + JsonSerializer.Serialize(accepted) + @";
  var checkRoutes = ['/checks/rms', '/checks/standards'];
  window.__calls = [];
  window.__holdGets = " + (holdGets ? "true" : "false") + @";
  window.__heldGets = [];
  window.__releaseGets = function () {
    var held = window.__heldGets;
    window.__heldGets = [];
    window.__holdGets = false;
    for (var index = 0; index < held.length; index++) { held[index](); }
  };
  function answer(method, path, headers) {
    if (method === 'GET' && window.__refuseGets) {
      return Promise.resolve({
        ok: false,
        status: 404,
        text: function () {
          return Promise.resolve(JSON.stringify({
            error_class: 'UnknownCheck',
            message: '" + RefusedGet + @"',
            retryable: false
          }));
        }
      });
    }
    if (accepted !== null && headers.Authorization !== 'Bearer ' + accepted) {
      return Promise.resolve({
        ok: false,
        status: 401,
        text: function () {
          return Promise.resolve(JSON.stringify({
            error_class: 'Unauthorized',
            message: 'this request carried no valid bearer token',
            retryable: false
          }));
        }
      });
    }
    var body = sample;
    if (method === 'POST' && checkRoutes.indexOf(path) >= 0) {
      body = JSON.parse(JSON.stringify(sample));
      body.check_id = String(sample.check_id) + '-newer';
    } else if (method === 'POST' && path.indexOf('/exceptions/') >= 0) {
      body = { exception_id: '" + ExceptionId + @"' };
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      text: function () { return Promise.resolve(JSON.stringify(body)); }
    });
  }
  window.fetch = function (url, request) {
    var path = String(url);
    if (path.indexOf(origin) === 0) { path = path.substring(origin.length); }
    var headers = (request && request.headers) || {};
    var method = (request && request.method) || 'GET';
    window.__calls.push({
      method: method,
      path: path,
      authorization: headers.Authorization || ''
    });
    if (method === 'GET' && window.__holdGets) {
      return new Promise(function (resolve) {
        window.__heldGets.push(function () { resolve(answer(method, path, headers)); });
      });
    }
    return answer(method, path, headers);
  };
}());0";

        private void Reply(string type, string? id, object payload) =>
            Page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id, payload }));
    }
}
