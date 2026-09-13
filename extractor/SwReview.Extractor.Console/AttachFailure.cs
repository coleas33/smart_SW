using System.Collections.Generic;
using System.Globalization;

namespace SwReview.Extractor.Console;

/// <summary>
/// What this process could learn about one running SLDWORKS.exe. A property is null when
/// the value could not be read, which is itself a diagnosis rather than a missing fact:
/// opening another process's token with PROCESS_QUERY_LIMITED_INFORMATION fails with access
/// denied when it belongs to another user.
/// </summary>
public sealed class SwProcessFacts
{
    public SwProcessFacts(int processId, int? sessionId, string? integrityLevel)
    {
        ProcessId = processId;
        SessionId = sessionId;
        IntegrityLevel = integrityLevel;
    }

    /// <summary>The process id, so the engineer can find it in Task Manager.</summary>
    public int ProcessId { get; }

    /// <summary>Its Windows terminal-services session, or null when unreadable.</summary>
    public int? SessionId { get; }

    /// <summary>"low", "medium", "high" or "system", or null when unreadable.</summary>
    public string? IntegrityLevel { get; }
}

/// <summary>
/// The message printed when the running object table holds no SOLIDWORKS.
///
/// The old code swallowed the COMException with a comment asserting it meant "nothing is
/// running", which is only one of the reasons: a SOLIDWORKS started elevated, or in another
/// Windows session, is invisible to a COM lookup from here. That mistake used to start a
/// SECOND seat - minutes of startup, a consumed licence, and a dump describing an empty
/// session instead of the assembly on screen.
///
/// So this states which fact actually differs instead of printing a list of guesses. The
/// facts are measured by <see cref="SwAttach"/>; choosing the sentence is pure and lives
/// here so it can be tested without SOLIDWORKS.
/// </summary>
public static class AttachFailure
{
    /// <summary>
    /// One sentence of diagnosis, wrapped in what was attempted and how to proceed.
    /// </summary>
    /// <param name="progId">The ProgID that was looked up, for the reader to recognise.</param>
    /// <param name="ourSessionId">This process's Windows session.</param>
    /// <param name="ourIntegrityLevel">This process's integrity level.</param>
    /// <param name="solidWorksProcesses">Every SLDWORKS.exe this process can see.</param>
    public static string Describe(
        string progId,
        int ourSessionId,
        string ourIntegrityLevel,
        IReadOnlyList<SwProcessFacts> solidWorksProcesses)
    {
        return $"Could not attach to a running SOLIDWORKS instance: '{progId}' is not in the "
            + "running object table. "
            + Diagnose(ourSessionId, ourIntegrityLevel, solidWorksProcesses)
            + " Pass --allow-start to start a new one instead (it will have none of your open "
            + "documents, and none of your add-ins).";
    }

    /// <summary>
    /// The one sentence naming the fact that differs, without the wrapper. The start path
    /// logs this on its own: <c>--allow-start</c> does not make the diagnosis irrelevant - a
    /// seat COM could not see is still running, and the session about to be created is not
    /// it - but that path must not also print the offer of a flag it was already given.
    /// </summary>
    public static string Diagnose(
        int ourSessionId, string ourIntegrityLevel, IReadOnlyList<SwProcessFacts> processes)
    {
        if (processes == null || processes.Count == 0)
        {
            return "No SLDWORKS.exe process is running.";
        }

        // The seat that differs is the one to report: a second, matching SLDWORKS.exe that
        // is merely slow to register must not mask the elevated one that is the cause.
        SwProcessFacts reported = processes[0];
        foreach (SwProcessFacts candidate in processes)
        {
            if (Differs(candidate, ourSessionId, ourIntegrityLevel))
            {
                reported = candidate;
                break;
            }
        }

        bool sessionDiffers = reported.SessionId.HasValue && reported.SessionId.Value != ourSessionId;

        if (sessionDiffers && reported.IntegrityLevel != null
            && reported.IntegrityLevel != ourIntegrityLevel)
        {
            return Text(
                "SLDWORKS.exe (pid {0}) runs in Windows session {1} at {2} integrity and this "
                + "process in session {3} at {4} integrity, so COM cannot see it.",
                reported.ProcessId,
                reported.SessionId!.Value,
                reported.IntegrityLevel,
                ourSessionId,
                ourIntegrityLevel);
        }

        if (sessionDiffers)
        {
            return Text(
                "SLDWORKS.exe (pid {0}) runs in Windows session {1} and this process in "
                + "session {2}, so COM cannot see it: run this tool in the same session as "
                + "SOLIDWORKS.",
                reported.ProcessId,
                reported.SessionId!.Value,
                ourSessionId);
        }

        // Each unreadable fact gets its own sentence: they are not read the same way and do
        // not mean the same thing. Process.SessionId reads across integrity levels while the
        // token does not, so in the dominant case - an elevated seat, a medium-integrity
        // terminal - the session IS known and only the token is denied. Saying "session or
        // token" there would report as unread a fact that was read (Principle I).
        if (!reported.SessionId.HasValue)
        {
            return Text(
                "SLDWORKS.exe (pid {0}) is running but this process cannot read its Windows "
                + "session, which means it belongs to another user: run this tool as that "
                + "user, in their Windows session.",
                reported.ProcessId);
        }

        if (reported.IntegrityLevel == null)
        {
            return Text(
                "SLDWORKS.exe (pid {0}) runs in Windows session {1} but this process cannot "
                + "read its token, which means it runs elevated or as another user: start "
                + "both the same way, either both elevated or neither.",
                reported.ProcessId,
                reported.SessionId!.Value);
        }

        if (reported.IntegrityLevel != ourIntegrityLevel)
        {
            return Text(
                "SLDWORKS.exe (pid {0}) runs at {1} integrity and this process at {2} "
                + "integrity, so COM cannot see it: start both the same way, either both "
                + "elevated or neither.",
                reported.ProcessId,
                reported.IntegrityLevel!,
                ourIntegrityLevel);
        }

        return Text(
            "SLDWORKS.exe (pid {0}) runs in the same Windows session ({1}) at the same "
            + "integrity level ({2}), so the entry is missing for another reason - the seat "
            + "may still be starting up, or still showing a dialog.",
            reported.ProcessId,
            reported.SessionId!.Value,
            reported.IntegrityLevel!);
    }

    private static bool Differs(SwProcessFacts facts, int ourSessionId, string ourIntegrityLevel) =>
        !facts.SessionId.HasValue
        || facts.SessionId.Value != ourSessionId
        || facts.IntegrityLevel == null
        || facts.IntegrityLevel != ourIntegrityLevel;

    private static string Text(string format, params object[] values) =>
        string.Format(CultureInfo.InvariantCulture, format, values);
}
