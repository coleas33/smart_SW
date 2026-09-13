using System;
using System.Globalization;
using System.Text.RegularExpressions;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Fasteners;

/// <summary>
/// What a fastener's name and description could be read to say. Every field is nullable
/// and stays null when the text does not say it.
/// </summary>
public sealed class FastenerIdentity
{
    /// <summary>e.g. "M6", "M6x1.0", "1/4-20". Null when the text carries no size.</summary>
    public string? ThreadDesignation { get; set; }

    /// <summary>Under-head length. Null when absent or when the unit cannot be known.</summary>
    public Quantity? Length { get; set; }

    /// <summary>e.g. "socket head cap". Null when the description names no head.</summary>
    public string? HeadType { get; set; }

    /// <summary><see cref="FastenerKind.Other"/> unless the text names a kind.</summary>
    public FastenerKind Kind { get; set; } = FastenerKind.Other;

    /// <summary>Always <see cref="IdentitySource.NameParse"/> for this parser's output.</summary>
    public IdentitySource IdentitySource { get; set; } = IdentitySource.NameParse;
}

/// <summary>
/// Reads a Toolbox-style configuration name and description into a fastener identity
/// (T047). SOLIDWORKS 2024 has no fastener API (research R12), so this parser and the
/// configuration-specific custom properties are the only identity available.
///
/// The rule that outranks every other: an unreadable name yields nulls. A screw whose
/// length is unknown must stay unknown so the bottoming check reports unresolved rather
/// than clearing on an invented number (constitution Principle I).
///
/// Formats handled, all taken from real Toolbox configuration names:
///   "M6 x 20"              size, then length in mm
///   "M6x1.0 x 20 - 20N"    size and pitch, then length; the "- 20N" thread-length suffix
///                          is ignored
///   "M10x35"               size, then length (an integer after the size is a length)
///   "M6x1.0"               size and pitch only; the 1.0 is a PITCH, not a 1 mm screw
///   "1/4-20 x 1-1/2"       unified inch thread, then length in inches
///   "#10-32 x 0.75"        numbered inch thread
///   "socket head cap screw_am"   head type and kind only; the "_am" library suffix is
///                          stripped
/// </summary>
public static class FastenerNameParser
{
    /// <summary>
    /// Head vocabulary, longest first so "socket head cap" wins over "cap". Matching is
    /// literal: an unlisted head type is reported as null, never approximated.
    /// </summary>
    private static readonly string[] HeadTypes =
    {
        "socket countersunk head",
        "socket button head",
        "socket head cap",
        "button head cap",
        "hex socket head",
        "cheese head",
        "hex flange",
        "flat head",
        "hex head",
        "pan head",
        "round head",
        "countersunk",
    };

    private static readonly (string Word, FastenerKind Kind)[] Kinds =
    {
        ("screw", FastenerKind.Screw),
        ("bolt", FastenerKind.Bolt),
        ("nut", FastenerKind.Nut),
        ("washer", FastenerKind.Washer),
        ("pin", FastenerKind.Pin),
    };

    /// <summary>"M6" or "M6.3": the metric size token.</summary>
    private static readonly Regex MetricSize = new Regex(
        @"^m(\d+(?:\.\d+)?)$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>"1/4-20", "#10-32", "3/8-16": a unified inch thread designation.</summary>
    private static readonly Regex InchSize = new Regex(
        @"^#?\d+(?:/\d+)?-\d+$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>
    /// The "x" that separates size from pitch from length. It only counts when it sits
    /// between numbers, so the "x" inside "hex" never splits a description.
    /// </summary>
    private static readonly Regex SizeSeparator = new Regex(
        @"(?<=[\d./])\s*x\s*(?=[#\d.\-])", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>"1-1/2" and "3/4" and "20" and "0.75" and "-5".</summary>
    private static readonly Regex MixedFraction = new Regex(
        @"^(\d+)-(\d+)/(\d+)$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    private static readonly Regex Fraction = new Regex(
        @"^(\d+)/(\d+)$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    private static readonly Regex DecimalNumber = new Regex(
        @"^-?\d+(?:\.\d+)?$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>
    /// Reads whatever the configuration name and description say. Size and length are
    /// taken from the configuration name first (that is where Toolbox writes them), head
    /// type and kind from the description first.
    /// </summary>
    public static FastenerIdentity Parse(string? configurationName, string? description = null)
    {
        var identity = new FastenerIdentity();

        string name = Normalize(configurationName);
        string desc = Normalize(description);

        ReadSizeAndLength(name, identity);
        if (identity.ThreadDesignation == null)
        {
            ReadSizeAndLength(desc, identity);
        }

        identity.HeadType = FindHeadType(desc) ?? FindHeadType(name);
        identity.Kind = FindKind(desc) ?? FindKind(name) ?? FastenerKind.Other;

        return identity;
    }

    /// <summary>
    /// Reads a length from a custom property value such as "20", "20mm" or "1/2\"". An
    /// explicit unit in the text wins; otherwise <paramref name="defaultUnit"/> (the
    /// document's own unit) is used. Anything unreadable returns null.
    /// </summary>
    public static Quantity? ParseLength(string? text, LengthUnit defaultUnit)
    {
        string value = Normalize(text);
        if (value.Length == 0)
        {
            return null;
        }

        LengthUnit unit = defaultUnit;
        if (value.EndsWith("mm", StringComparison.Ordinal))
        {
            unit = LengthUnit.Mm;
            value = value.Substring(0, value.Length - 2).Trim();
        }
        else if (value.EndsWith("in", StringComparison.Ordinal))
        {
            unit = LengthUnit.In;
            value = value.Substring(0, value.Length - 2).Trim();
        }
        else if (value.EndsWith("\"", StringComparison.Ordinal))
        {
            unit = LengthUnit.In;
            value = value.Substring(0, value.Length - 1).Trim();
        }

        double? number = ParseNumber(value);
        if (number == null || number.Value <= 0.0)
        {
            return null;
        }

        return new Quantity(number.Value, unit);
    }

    /// <summary>
    /// Lowercases, collapses whitespace, and turns the Toolbox library suffix separator
    /// ("screw_am") into a space so word matching still works.
    /// </summary>
    private static string Normalize(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return string.Empty;
        }

        string lowered = text!.ToLowerInvariant().Replace('_', ' ').Replace('×', 'x');
        return Regex.Replace(lowered, @"\s+", " ").Trim();
    }

    private static void ReadSizeAndLength(string text, FastenerIdentity identity)
    {
        if (text.Length == 0)
        {
            return;
        }

        // "M6x1.0 x 20 - 20N": everything after a spaced hyphen is a thread-length or
        // grade suffix this parser does not claim to understand.
        int suffix = text.IndexOf(" - ", StringComparison.Ordinal);
        string core = suffix >= 0 ? text.Substring(0, suffix).Trim() : text;

        string[] tokens = SizeSeparator.Split(core);

        Match metric = MetricSize.Match(tokens[0]);
        if (metric.Success)
        {
            identity.ThreadDesignation = "M" + metric.Groups[1].Value;
            ReadMetricPitchAndLength(tokens, identity);
            return;
        }

        if (InchSize.IsMatch(tokens[0]))
        {
            identity.ThreadDesignation = tokens[0];
            if (tokens.Length >= 2)
            {
                identity.Length = MakeLength(tokens[1], LengthUnit.In);
            }
        }
    }

    private static void ReadMetricPitchAndLength(string[] tokens, FastenerIdentity identity)
    {
        if (tokens.Length == 1)
        {
            return;
        }

        if (tokens.Length >= 3)
        {
            // "M6 x 1.0 x 20": pitch then length.
            identity.ThreadDesignation += "x" + tokens[1];
            identity.Length = MakeLength(tokens[2], LengthUnit.Mm);
            return;
        }

        // One value after the size. A pitch is written with a decimal point ("M6x1.0");
        // a length is a whole number of millimetres ("M10x35"). Toolbox writes both this
        // way, and guessing the other way round would turn a 35 mm screw into a pitch.
        if (tokens[1].IndexOf('.') >= 0)
        {
            identity.ThreadDesignation += "x" + tokens[1];
        }
        else
        {
            identity.Length = MakeLength(tokens[1], LengthUnit.Mm);
        }
    }

    private static Quantity? MakeLength(string token, LengthUnit unit)
    {
        double? value = ParseNumber(token);
        if (value == null || value.Value <= 0.0)
        {
            return null;
        }

        return new Quantity(value.Value, unit);
    }

    private static double? ParseNumber(string token)
    {
        Match mixed = MixedFraction.Match(token);
        if (mixed.Success)
        {
            double denominator = ToDouble(mixed.Groups[3].Value);
            return denominator == 0
                ? (double?)null
                : ToDouble(mixed.Groups[1].Value) + (ToDouble(mixed.Groups[2].Value) / denominator);
        }

        Match fraction = Fraction.Match(token);
        if (fraction.Success)
        {
            double denominator = ToDouble(fraction.Groups[2].Value);
            return denominator == 0 ? (double?)null : ToDouble(fraction.Groups[1].Value) / denominator;
        }

        if (DecimalNumber.IsMatch(token))
        {
            return ToDouble(token);
        }

        return null;
    }

    private static double ToDouble(string text) =>
        double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture);

    private static string? FindHeadType(string text)
    {
        if (text.Length == 0)
        {
            return null;
        }

        foreach (string head in HeadTypes)
        {
            if (text.IndexOf(head, StringComparison.Ordinal) >= 0)
            {
                return head;
            }
        }

        return null;
    }

    private static FastenerKind? FindKind(string text)
    {
        if (text.Length == 0)
        {
            return null;
        }

        foreach ((string word, FastenerKind kind) in Kinds)
        {
            if (Regex.IsMatch(text, @"\b" + word + @"s?\b", RegexOptions.CultureInvariant))
            {
                return kind;
            }
        }

        return null;
    }
}
