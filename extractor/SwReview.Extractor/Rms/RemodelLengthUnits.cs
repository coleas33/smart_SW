using System;
using System.Collections.Generic;
using SolidWorks.Interop.swconst;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The copy's length unit, as <see cref="IRemodelDocument.GetLengthUnit"/> reports it (feature
/// 004, T153; build order lane B): the first place of <c>IModelDoc2.GetUnits()</c>'s answer, a
/// <c>swLengthUnit_e</c>, named by a token. It is the only stated source for FR-027's
/// metres-to-document-unit conversion, and a wrong answer silently builds a part a thousand times
/// off, so this is pure, total over the enum and tested without a seat.
///
/// Every member of the enum is named - not only the three the planner converts - so a document
/// kept in centimetres is refused by the planner <b>by name</b> (<c>reviewer/src/swreview/remodel/units.py</c>
/// refuses any token outside the IR's <c>mm</c>, <c>in</c> and <c>m</c>) rather than being
/// reported as unreadable. Unknown stays unknown: an integer outside the enum, or an answer that is
/// not an array whose first element is an integer, is null, never a guessed unit and never metres
/// (default taken 2026-09-27, the owner may revise).
/// </summary>
public static class RemodelLengthUnits
{
    private static readonly IReadOnlyDictionary<int, string> Tokens = new Dictionary<int, string>
    {
        // The three the planner converts: the IR's own LengthUnit tokens.
        [(int)swLengthUnit_e.swMM] = "mm",
        [(int)swLengthUnit_e.swINCHES] = "in",
        [(int)swLengthUnit_e.swMETER] = "m",

        // Named so the planner refuses them by name.
        [(int)swLengthUnit_e.swCM] = "cm",
        [(int)swLengthUnit_e.swFEET] = "ft",
        [(int)swLengthUnit_e.swFEETINCHES] = "ft-in",
        [(int)swLengthUnit_e.swANGSTROM] = "angstrom",
        [(int)swLengthUnit_e.swNANOMETER] = "nm",
        [(int)swLengthUnit_e.swMICRON] = "um",
        [(int)swLengthUnit_e.swMIL] = "mil",
        [(int)swLengthUnit_e.swUIN] = "uin",
    };

    /// <summary>The token for one <c>swLengthUnit_e</c> value, or null for a value outside the enum.</summary>
    public static string? TokenFor(int lengthUnit) =>
        Tokens.TryGetValue(lengthUnit, out string? token) ? token : null;

    /// <summary>
    /// The token for <c>IModelDoc2.GetUnits()</c>'s answer: its first element, read from the
    /// array's lower bound, when that element is a boxed integer of any width. Anything else is
    /// unknown (null): a null, a string, a Boolean or a floating-point number in that place is not
    /// read as a unit, because a guess here is exactly the error FR-027 exists to prevent.
    /// </summary>
    public static string? FromUnits(object? answer)
    {
        if (!(answer is Array array) || array.Rank != 1 || array.Length == 0)
        {
            return null;
        }

        return TryReadInteger(array.GetValue(array.GetLowerBound(0)), out int lengthUnit)
            ? TokenFor(lengthUnit)
            : null;
    }

    /// <summary>A boxed integer of any width that fits an <c>int</c>, and nothing else.</summary>
    private static bool TryReadInteger(object? element, out int value)
    {
        switch (element)
        {
            case int number:
                value = number;
                return true;
            case short number:
                value = number;
                return true;
            case byte number:
                value = number;
                return true;
            case sbyte number:
                value = number;
                return true;
            case ushort number:
                value = number;
                return true;
            case long number when number >= int.MinValue && number <= int.MaxValue:
                value = (int)number;
                return true;
            case uint number when number <= int.MaxValue:
                value = (int)number;
                return true;
            case ulong number when number <= int.MaxValue:
                value = (int)number;
                return true;
            default:
                value = 0;
                return false;
        }
    }
}
