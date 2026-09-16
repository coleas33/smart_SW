using System;
using System.Globalization;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// T068. The two helpers every equation write in the feature goes through, and the only
/// evidence that a write landed.
///
/// <b>The member's return code is not the evidence.</b> PROBE-6 observed
/// <c>IEquationMgr.Add3</c> answering <c>-1</c> and adding nothing, silently, so each helper
/// reads back what it can - the count moved (or, for an in-place edit, did <i>not</i> move)
/// <b>and</b> <c>get_Equation(i)</c> round-trips to the text that was written - and only then
/// reports success. On a failure it tries the older member once and asserts again; a second
/// failure fails the change with <c>equation_unverified</c>.
///
/// <b>The assertion is never inlined at a call site.</b> These two methods are the whole
/// public surface of this class for exactly that reason: a third path would be an equation
/// write whose evidence nobody checked, and there would then be two places to get the
/// assertion wrong.
///
/// <c>set</c> is FR-029's in-place repair and is <b>its own inverse</b>. Delete-and-re-add is
/// not a third fallback and is not reachable from it: while a referenced global is missing,
/// every dependent equation enters an error state that does not clear when the global returns
/// (research R3.5). Trading a failed edit for a missing global is exactly that upstream
/// failure.
///
/// A global variable is created by <b>syntax</b> - <c>"name" = expr</c>, a quoted left-hand
/// side with no <c>@</c> - because <c>IEquationMgr.set_GlobalVariable</c> is a VERIFIED
/// ABSENCE and nothing may treat globalness as a flag.
/// </summary>
public static class RemodelEquations
{
    /// <summary>The allowlist key for <c>IEquationMgr.Add3</c>; spelled here and nowhere else.</summary>
    private const string Add3Key = "IEquationMgr.Add3";

    private const string Add2Key = "IEquationMgr.Add2";
    private const string SetEquationKey = "IEquationMgr.set_Equation";
    private const string SetEquationAndConfigurationOptionKey =
        "IEquationMgr.SetEquationAndConfigurationOption";

    /// <summary><c>IEquationMgr.GetCount</c>, as the gate is told about it. A read.</summary>
    private const string CountMember = "GetCount";

    /// <summary><c>IEquationMgr.get_Equation</c>, as the gate is told about it. A read.</summary>
    private const string EquationMember = "get_Equation";

    /// <summary>
    /// <c>Add3</c>'s <c>Solve</c> argument. The equation is solved as it is added, because an
    /// unsolved equation cannot be read back with a value and the run would have added
    /// something it could not describe.
    /// </summary>
    private const bool Solve = true;

    /// <summary>
    /// Adds one equation and proves it landed.
    ///
    /// <paramref name="whichConfigs"/> is <c>swInConfigurationOpts_e</c> and is <b>required</b>:
    /// it comes from the configuration count <c>remodel.open</c> recorded, and a
    /// single-configuration assumption is checked, never assumed.
    /// </summary>
    public static RemodelEquationResult AddEquationVerified(
        RemodelScope scope,
        SwGate gate,
        IEquationTarget equations,
        int index,
        string text,
        int? whichConfigs,
        string[]? configNames)
    {
        Required(scope, gate, equations, text);
        int configurations = RequiredConfigurations(whichConfigs);

        int before = gate.Call(CountMember, equations.GetCount);
        int at = index < 0 || index > before ? before : index;

        scope.Write(
            Add3Key, () => equations.Add3(at, text, Solve, configurations, configNames));

        int after = gate.Call(CountMember, equations.GetCount);
        string? roundTrip = gate.Call(EquationMember, () => equations.GetEquation(at));

        if (Landed(before, after, roundTrip, text))
        {
            return Result(at, before, after, null, roundTrip, RemodelEquationHelperPaths.Add3);
        }

        // One fallback, one more assertion. Never a loop and never a third member.
        scope.Write(Add2Key, () => equations.Add2(at, text, Solve));

        after = gate.Call(CountMember, equations.GetCount);
        roundTrip = gate.Call(EquationMember, () => equations.GetEquation(at));

        if (Landed(before, after, roundTrip, text))
        {
            return Result(at, before, after, null, roundTrip, RemodelEquationHelperPaths.Add2);
        }

        throw Unverified(
            $"neither Add3 nor Add2 could be proven to have added '{text}' at index "
            + $"{at.ToString(CultureInfo.InvariantCulture)}: the count went from "
            + $"{before.ToString(CultureInfo.InvariantCulture)} to "
            + $"{after.ToString(CultureInfo.InvariantCulture)} and the row reads back as "
            + Describe(roundTrip) + ".");
    }

    /// <summary>
    /// Edits one equation in place and proves it landed, reading the previous text
    /// <b>before</b> writing, because that text is the inverse and the command never guesses
    /// it. An unreadable previous text fails the change rather than writing over something
    /// that could not be put back.
    /// </summary>
    public static RemodelEquationResult SetEquationVerified(
        RemodelScope scope,
        SwGate gate,
        IEquationTarget equations,
        int index,
        string text,
        int? whichConfigs,
        string[]? configNames)
    {
        Required(scope, gate, equations, text);
        int configurations = RequiredConfigurations(whichConfigs);

        string? previous = gate.Call(EquationMember, () => equations.GetEquation(index));
        if (previous == null)
        {
            throw Unverified(
                $"equation {index.ToString(CultureInfo.InvariantCulture)} could not be read "
                + "before the edit, so the edit would have no inverse. Writing over something "
                + "that cannot be put back is a silent edit.");
        }

        int before = gate.Call(CountMember, equations.GetCount);

        scope.Write(SetEquationKey, () => equations.SetEquation(index, text));

        int after = gate.Call(CountMember, equations.GetCount);
        string? roundTrip = gate.Call(EquationMember, () => equations.GetEquation(index));

        if (Edited(before, after, roundTrip, text))
        {
            return Result(
                index, before, after, previous, roundTrip, RemodelEquationHelperPaths.SetEquation);
        }

        scope.Write(
            SetEquationAndConfigurationOptionKey,
            () => equations.SetEquationAndConfigurationOption(
                index, text, configurations, configNames));

        after = gate.Call(CountMember, equations.GetCount);
        roundTrip = gate.Call(EquationMember, () => equations.GetEquation(index));

        if (Edited(before, after, roundTrip, text))
        {
            return Result(
                index,
                before,
                after,
                previous,
                roundTrip,
                RemodelEquationHelperPaths.SetEquationAndConfigurationOption);
        }

        throw Unverified(
            $"neither set_Equation nor SetEquationAndConfigurationOption could be proven to "
            + $"have written '{text}' at index {index.ToString(CultureInfo.InvariantCulture)}: "
            + "the row reads back as " + Describe(roundTrip) + ". Delete-and-re-add is not a "
            + "fallback, because a missing global puts every equation that references it into "
            + "an error state that does not clear when it returns.");
    }

    /// <summary>An add landed when the count rose by one and the row reads back as the text.</summary>
    private static bool Landed(int before, int after, string? roundTrip, string text) =>
        after == before + 1 && string.Equals(roundTrip, text, StringComparison.Ordinal);

    /// <summary>
    /// An in-place edit landed when the count is <b>unchanged</b> and the row reads back as the
    /// text. A count that moved means something was added or removed as well.
    /// </summary>
    private static bool Edited(int before, int after, string? roundTrip, string text) =>
        after == before && string.Equals(roundTrip, text, StringComparison.Ordinal);

    private static RemodelEquationResult Result(
        int index, int before, int after, string? previous, string? roundTrip, string helperPath) =>
        new RemodelEquationResult
        {
            Index = index,
            CountBefore = before,
            CountAfter = after,
            PreviousText = previous,
            RoundTripText = roundTrip,
            HelperPath = helperPath,
        };

    private static RemodelCommandError Unverified(string message) =>
        new RemodelCommandError(RemodelErrorCodes.EquationUnverified, message);

    private static string Describe(string? roundTrip) =>
        roundTrip == null ? "(unreadable)" : "'" + roundTrip + "'";

    private static int RequiredConfigurations(int? whichConfigs)
    {
        if (whichConfigs == null)
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest,
                "\"which_configs\" is required: it is composed from the configuration count "
                + "remodel.open recorded, and a single-configuration assumption is checked, "
                + "never assumed.");
        }

        return whichConfigs.Value;
    }

    private static void Required(
        RemodelScope scope, SwGate gate, IEquationTarget equations, string text)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        if (equations == null)
        {
            throw new ArgumentNullException(nameof(equations));
        }

        if (string.IsNullOrWhiteSpace(text))
        {
            throw new RemodelCommandError(
                RemodelErrorCodes.BadRequest, "an equation needs a non-empty text.");
        }
    }
}
