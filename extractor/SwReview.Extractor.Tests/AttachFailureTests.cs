using System.Collections.Generic;
using SwReview.Extractor.Console;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The sentence printed when the running object table has no SOLIDWORKS in it.
///
/// The failure this targets: SOLIDWORKS was started elevated (or in another Windows
/// session) and the terminal was not, so COM cannot see it. Before, that was
/// indistinguishable from "nothing is running" and the host quietly started a SECOND seat.
/// The diagnosis is built from facts the caller measured - our session and integrity level
/// against each SLDWORKS.exe - so it names what actually differs instead of listing
/// guesses; gathering those facts is SwAttach's job and is not testable here, but choosing
/// the sentence is pure and is.
/// </summary>
public class AttachFailureTests
{
    private const string ProgId = "SldWorks.Application.32";

    private static readonly IReadOnlyList<SwProcessFacts> NoProcesses = new SwProcessFacts[0];

    private static string Describe(params SwProcessFacts[] processes) =>
        AttachFailure.Describe(ProgId, ourSessionId: 1, ourIntegrityLevel: "medium", processes);

    // ---- every message ------------------------------------------------------------

    [Fact]
    public void Describe_AlwaysNamesTheProgIdItLookedFor()
    {
        Assert.Contains(ProgId, AttachFailure.Describe(ProgId, 1, "medium", NoProcesses));
    }

    [Fact]
    public void Describe_AlwaysOffersAllowStart()
    {
        // Attach-only is the default, so the message must say how to opt in - otherwise an
        // unattended script has no way forward from the error.
        Assert.Contains("--allow-start", AttachFailure.Describe(ProgId, 1, "medium", NoProcesses));
    }

    // ---- nothing running ----------------------------------------------------------

    [Fact]
    public void Describe_NoSolidWorksProcess_SaysSoWithoutGuessing()
    {
        string message = AttachFailure.Describe(ProgId, 1, "medium", NoProcesses);

        Assert.Contains("No SLDWORKS.exe process is running", message);
        Assert.DoesNotContain("integrity", message);
        Assert.DoesNotContain("session", message);
    }

    // ---- running, and something differs -------------------------------------------

    [Fact]
    public void Describe_HigherIntegrity_NamesElevationAndNotTheSession()
    {
        string message = Describe(new SwProcessFacts(4242, sessionId: 1, integrityLevel: "high"));

        Assert.Contains("4242", message);
        Assert.Contains("integrity", message);
        Assert.Contains("high", message);
        Assert.Contains("medium", message);
        Assert.DoesNotContain("Windows session", message);
    }

    [Fact]
    public void Describe_DifferentSession_NamesTheSessionAndNotElevation()
    {
        string message = Describe(new SwProcessFacts(4242, sessionId: 2, integrityLevel: "medium"));

        Assert.Contains("Windows session 2", message);
        Assert.Contains("session 1", message);
        Assert.DoesNotContain("integrity", message);
    }

    [Fact]
    public void Describe_BothDiffer_NamesBoth()
    {
        string message = Describe(new SwProcessFacts(4242, sessionId: 2, integrityLevel: "high"));

        Assert.Contains("Windows session 2", message);
        Assert.Contains("high", message);
        Assert.Contains("integrity", message);
    }

    [Fact]
    public void Describe_IntegrityUnreadable_SaysThatIsItselfTheAnswer()
    {
        // Reading another process's token fails with access denied exactly when it runs at a
        // higher integrity level or as another user, so the failure IS the diagnosis. This is
        // the DOMINANT real case - Process.SessionId reads fine across integrity levels and
        // only the token fails - so the message must report the session it actually read
        // rather than claiming both were unreadable, and must carry a remedy like every
        // other branch (constitution, Principle I).
        string message = Describe(new SwProcessFacts(4242, sessionId: 1, integrityLevel: null));

        Assert.Contains("4242", message);
        Assert.Contains("Windows session 1", message);
        Assert.Contains("cannot read its token", message);
        Assert.DoesNotContain("cannot read its Windows session", message);
        Assert.Contains("either both elevated or neither", message);
        Assert.DoesNotContain("same integrity level", message);
    }

    [Fact]
    public void Describe_SessionUnreadable_IsTreatedAsUnreadableNotAsAMatch()
    {
        // The token was read here, so the message must not say it was not.
        string message = Describe(new SwProcessFacts(4242, sessionId: null, integrityLevel: "medium"));

        Assert.Contains("cannot read its Windows session", message);
        Assert.DoesNotContain("cannot read its token", message);
        Assert.Contains("run this tool as that user", message);
    }

    [Fact]
    public void Describe_NeitherSessionNorIntegrityReadable_BlamesTheSessionNotElevation()
    {
        // Nothing at all could be read, so the honest answer is the narrower one: the process
        // belongs to somewhere this one cannot look.
        string message = Describe(new SwProcessFacts(4242, sessionId: null, integrityLevel: null));

        Assert.Contains("4242", message);
        Assert.Contains("cannot read its Windows session", message);
        Assert.DoesNotContain("cannot read its token", message);
        Assert.DoesNotContain("Windows session 1", message);
    }

    // ---- running, and nothing differs ---------------------------------------------

    [Fact]
    public void Describe_SameSessionAndIntegrity_DoesNotBlameElevation()
    {
        // A false "you are elevated" would send the engineer chasing the wrong thing; the
        // honest answer is that the ROT entry is missing for some other reason.
        string message = Describe(new SwProcessFacts(4242, sessionId: 1, integrityLevel: "medium"));

        Assert.Contains("same Windows session", message);
        Assert.Contains("same integrity level", message);
        Assert.Contains("still be starting up", message);
    }

    // ---- several seats -------------------------------------------------------------

    [Fact]
    public void Describe_SeveralProcesses_ReportsTheOneThatDiffers()
    {
        // A matching SLDWORKS.exe that is merely slow to register must not mask the
        // elevated one that is the actual cause.
        string message = Describe(
            new SwProcessFacts(1111, sessionId: 1, integrityLevel: "medium"),
            new SwProcessFacts(2222, sessionId: 1, integrityLevel: "high"));

        Assert.Contains("2222", message);
        Assert.DoesNotContain("1111", message);
    }

    [Fact]
    public void Describe_SeveralProcessesAllMatching_ReportsTheFirst()
    {
        string message = Describe(
            new SwProcessFacts(1111, sessionId: 1, integrityLevel: "medium"),
            new SwProcessFacts(2222, sessionId: 1, integrityLevel: "medium"));

        Assert.Contains("1111", message);
        Assert.DoesNotContain("2222", message);
    }

    // ---- the diagnosis on its own ----------------------------------------------------

    [Fact]
    public void Diagnose_RunningButInvisibleSeat_StandsAloneWithoutTheAllowStartAdvice()
    {
        // --allow-start does not make the diagnosis irrelevant - it makes it MORE relevant:
        // a seat was running that COM could not see, and the session about to be started is
        // not it. The start path in SwAttach logs this sentence too, so it must be produced
        // independently of the message that offers --allow-start (that offer would be absurd
        // on a run that already passed the flag).
        var invisibleSeat = new[] { new SwProcessFacts(4242, sessionId: 1, integrityLevel: "high") };

        string diagnosis = AttachFailure.Diagnose(
            ourSessionId: 1, ourIntegrityLevel: "medium", processes: invisibleSeat);

        Assert.Contains("4242", diagnosis);
        Assert.Contains("high", diagnosis);
        Assert.DoesNotContain("--allow-start", diagnosis);

        // And it is the same sentence the attach-only error wraps, not a second wording.
        Assert.Contains(diagnosis, AttachFailure.Describe(ProgId, 1, "medium", invisibleSeat));
    }

    [Fact]
    public void Diagnose_NoSolidWorksProcess_StillSaysSo()
    {
        // The start path only logs when a process was found, but the sentence must be safe
        // to ask for either way rather than throwing on an empty list.
        Assert.Contains(
            "No SLDWORKS.exe process is running",
            AttachFailure.Diagnose(1, "medium", NoProcesses));
    }

    // ---- the facts themselves -------------------------------------------------------

    [Fact]
    public void SwProcessFacts_KeepsWhatItWasGiven()
    {
        var facts = new SwProcessFacts(7, sessionId: 3, integrityLevel: "high");

        Assert.Equal(7, facts.ProcessId);
        Assert.Equal(3, facts.SessionId);
        Assert.Equal("high", facts.IntegrityLevel);
    }
}
