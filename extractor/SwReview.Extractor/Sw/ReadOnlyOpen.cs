using System;
using SwReview.Extractor.Guard;

namespace SwReview.Extractor.Sw;

/// <summary>
/// Decision 136A (feature 011, 2026-10-19): what the extractor's two read-only opens do with the
/// document SOLIDWORKS hands back - feature 011's confirmed drawing (<see cref="DrawingOpenScope"/>)
/// and the console attach's part or assembly (<see cref="SwSession"/>'s <c>OpenReadOnly</c>) -
/// written once, so the two cannot drift apart.
///
/// Both ask <c>OpenDoc6</c> for ReadOnly | Silent, and nothing but the document itself says whether
/// SOLIDWORKS honoured the option. So <see cref="Refusal"/> asks it,
/// <c>IModelDoc2.IsOpenedReadOnly()</c>, before anything reads it, and a document that is not
/// open read-only - or that will not say - is refused and closed again by <see cref="Close"/>: only
/// that document, and only after SOLIDWORKS answers its path with the very COM object the open
/// returned. A document that was open before the open is the caller's to recognise - the lookup
/// before it, or the open's own word that it was already open
/// (<see cref="FileLoadErrors.SayAlreadyOpen"/>, decision 136A's review) - and is never asked and
/// never closed. Neither method throws for SOLIDWORKS's failures: each answers with the sentence
/// to show, so a caller names every failure in one refusal.
/// </summary>
internal static class ReadOnlyOpen
{
    /// <summary><c>IModelDoc2.IsOpenedReadOnly()</c>: a read, so gated under its bare name.</summary>
    public const string ReadOnlyMember = "IsOpenedReadOnly";

    /// <summary><c>ISldWorks.GetOpenDocumentByName(path)</c>, the close's identity check: a read, gated bare.</summary>
    public const string LookupMember = "GetOpenDocumentByName";

    /// <summary>
    /// The refusal of a document an open returned that SOLIDWORKS does not confirm is open
    /// read-only, after <paramref name="close"/> has run; null, with nothing closed, when
    /// <c>IsOpenedReadOnly()</c> answered true. It fails closed: a false answer is a refusal, and so
    /// is any exception from the call - a guard's refusal or an open circuit included, since the
    /// document is open either way and must not be read - which is handed back in
    /// <paramref name="failure"/> for the refusal to carry. The open's load errors and warnings are
    /// named, since they may say why the option was not honoured.
    /// </summary>
    /// <param name="close">Closes what the open opened; answers why it did not, or null when it did.</param>
    /// <param name="name">How the document is named in the sentence: a file name or a path.</param>
    public static string? Refusal(
        SwGate gate,
        Func<bool> isOpenedReadOnly,
        int errors,
        int warnings,
        Func<string?> close,
        string name,
        out Exception? failure)
    {
        failure = null;
        string loaded = FileLoadErrors.Describe(errors, warnings);
        string reason;
        try
        {
            if (gate.Call(ReadOnlyMember, isOpenedReadOnly))
            {
                return null;
            }

            reason = $"but not read-only (IsOpenedReadOnly answered false; {loaded})";
        }
        catch (Exception error)
        {
            failure = error;
            reason = $"but did not confirm it read-only (IsOpenedReadOnly failed: {Described(error)}; {loaded})";
        }

        return $"SOLIDWORKS opened '{name}', {reason}, so it was not read; " + (close() ?? "it was closed again.");
    }

    /// <summary>
    /// Closes what an open opened, after checking SOLIDWORKS still answers its path with the very
    /// document the open returned; returns why it did not close, or null when it closed. A lookup or
    /// close SOLIDWORKS fails is returned as a reason, never thrown: the caller may be unwinding from
    /// another failure, which must not be hidden. A guard's refusal of either key is not
    /// SOLIDWORKS's failure and propagates.
    /// </summary>
    /// <param name="lookup">The open's <c>GetOpenDocumentByName(path)</c>.</param>
    /// <param name="closeKey">The key the caller's gate allows the close under.</param>
    /// <param name="close">The open's <c>CloseDoc(path)</c>.</param>
    /// <param name="opened">What the open returned.</param>
    /// <param name="name">How the document is named in the sentence: a file name or a path.</param>
    /// <param name="opener">Who opened it, as the sentence says: "the review", "the extractor".</param>
    public static string? Close(
        SwGate gate,
        Func<object?> lookup,
        string closeKey,
        Action close,
        object opened,
        string name,
        string opener)
    {
        try
        {
            object? current = gate.Call(LookupMember, lookup);
            if (!ReferenceEquals(current, opened))
            {
                return current == null
                    ? $"'{name}' was not closed: SOLIDWORKS no longer answers its path with the "
                        + $"same document {opener} opened, so nothing was closed."
                    : $"'{name}' was not closed: SOLIDWORKS answers its path with a document "
                        + $"that is not the same document {opener} opened, so nothing was closed.";
            }

            gate.Call(closeKey, close);
            return null;
        }
        catch (Exception error) when (!(error is MutatingCallError))
        {
            return $"'{name}' was not closed: SOLIDWORKS failed while {opener} was closing it ({Described(error)}).";
        }
    }

    /// <summary>An exception as the sentences name it: its type and message.</summary>
    public static string Described(Exception error) => error.GetType().Name + ": " + error.Message;
}
