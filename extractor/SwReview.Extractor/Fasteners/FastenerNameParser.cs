using System;
using System.Collections.Generic;
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
/// Reads a component's configuration name, description and file name into a fastener
/// identity (T047; the file name and the vendor forms are feature 010's, T051). SOLIDWORKS
/// 2024 has no fastener API (research R12), so this parser and the configuration-specific
/// custom properties are the only identity available.
///
/// The rule that outranks every other: an unreadable name yields nulls. A screw whose
/// length is unknown must stay unknown so the bottoming check reports unresolved rather
/// than clearing on an invented number (constitution Principle I).
///
/// Formats handled. Every form is anchored at the start of the text, so a size token that
/// merely appears somewhere in a name ("BRACKET_M5_TAPPED") is never read as a size:
///   "M6 x 20"              size, then length in mm
///   "M6x1.0 x 20 - 20N"    size and pitch, then length; the "- 20N" thread-length suffix
///                          is ignored
///   "M10x35"               size, then length (an integer after the size is a length)
///   "M6x1.0"               size and pitch only; the 1.0 is a PITCH, not a 1 mm screw
///   "M4-0.7 x 12"          a pitch written with a hyphen is a pitch (feature 010)
///   "1/4-20 x 1-1/2"       unified inch thread, then length in inches
///   "#10-32 x 0.75"        numbered inch thread
///   "0.190-32 x 0.5"       decimal inch thread (feature 010)
///   "SHC_M4-0.7X12_..."    the vendor file-name form: a head code, then size, pitch and
///                          length in mm (feature 010, contracts/fasteners.md section 1)
///   "SCREW, SOC M4-0.7 X 12 MM, ..."   the vendor description form (feature 010)
///   "socket head cap screw_am"   head type and kind only; the "_am" library suffix is
///                          stripped
///
/// The same rows are asserted against the Python parser through
/// <c>specs/010-mechanical-checks/contracts/fastener-name-vectors.json</c>, so the two cannot
/// drift (research R2.11).
/// </summary>
public static class FastenerNameParser
{
    /// <summary>
    /// The SOLIDWORKS extensions a file name may carry. Only these are dropped: a vendor name
    /// has a dot inside its pitch ("M4-0.7X12"), so "everything after the last dot" would cut
    /// the size in half.
    /// </summary>
    private static readonly string[] DocumentExtensions = { ".sldprt", ".sldasm", ".slddrw" };

    /// <summary>
    /// The vendor head codes the recorded assemblies carry (research R2.11), and what each
    /// says. The trailing letter of <c>FHT</c> and <c>BHT</c> is Torx by the owner's answer of
    /// 2026-09-23 (research R5); the drive is the Python side's to record
    /// (<c>checks/fastener_names.yaml</c>), so it is not repeated here. An unlisted code reads
    /// no kind and no head, and the size is still read.
    /// </summary>
    private static readonly Dictionary<string, (FastenerKind Kind, string HeadType)> HeadCodes =
        new Dictionary<string, (FastenerKind Kind, string HeadType)>(StringComparer.Ordinal)
        {
            ["shc"] = (FastenerKind.Screw, "socket head cap"),
            ["bht"] = (FastenerKind.Screw, "button head"),
            ["fht"] = (FastenerKind.Screw, "flat head"),
        };

    /// <summary>
    /// The vendor file-name form after normalization: <c>shc m4-0.7x12 fict-0001</c>. The
    /// head code, then the metric size with a hyphen pitch, an "x" and the length in mm.
    /// </summary>
    private static readonly Regex VendorFileName = new Regex(
        @"^(?<code>[a-z]+) m(?<size>\d+(?:\.\d+)?)-(?<pitch>\d+(?:\.\d+)?)x(?<length>\d+(?:\.\d+)?)(?: .*)?$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>
    /// The vendor description form after normalization:
    /// <c>screw, soc m4-0.7 x 12 mm, fictional</c>. A leading word and a comma, then the size
    /// with a hyphen pitch and the length with its unit. The kind is the vocabulary's to read.
    /// </summary>
    private static readonly Regex VendorDescription = new Regex(
        @"^[a-z]+, .*?\bm(?<size>\d+(?:\.\d+)?)-(?<pitch>\d+(?:\.\d+)?) x (?<length>\d+(?:\.\d+)?) mm\b",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

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

    /// <summary>
    /// "M6", "M6.3" or "M4-0.7": the metric size token, with the pitch when it is written
    /// with a hyphen.
    /// </summary>
    private static readonly Regex MetricSize = new Regex(
        @"^m(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>
    /// "1/4-20", "#10-32", "3/8-16", "0.190-32": a unified inch thread designation.
    /// </summary>
    private static readonly Regex InchSize = new Regex(
        @"^(?:#?\d+(?:/\d+)?|\d*\.\d+)-\d+$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

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
    /// Reads whatever the configuration name, description and file name say. Every source is
    /// read with the same grammar. Size and length come from the first source that names a
    /// size, in the order configuration name (that is where Toolbox writes them), description,
    /// file name; head type and kind from the description first, then the configuration
    /// name, then the file name. The file name is last on both counts because it is the one
    /// source feature 010 added (contracts/fasteners.md section 7): a Toolbox part keeps
    /// exactly the identity it had.
    /// </summary>
    public static FastenerIdentity Parse(
        string? configurationName, string? description = null, string? fileName = null)
    {
        SourceReading configuration = ReadSource(Normalize(configurationName));
        SourceReading text = ReadSource(Normalize(description));
        SourceReading file = ReadSource(Normalize(WithoutDocumentExtension(fileName)));

        SourceReading? sized = configuration.ThreadDesignation != null ? configuration
            : text.ThreadDesignation != null ? text
            : file.ThreadDesignation != null ? file
            : null;

        return new FastenerIdentity
        {
            ThreadDesignation = sized?.ThreadDesignation,
            Length = sized?.Length,
            HeadType = text.HeadType ?? configuration.HeadType ?? file.HeadType,
            Kind = text.Kind ?? configuration.Kind ?? file.Kind ?? FastenerKind.Other,
        };
    }

    /// <summary>
    /// Whether a component's names make it a fastener candidate (feature 010 T051): a kind
    /// <b>and</b> a size, from any source. A size alone is a bracket with tapped holes and a
    /// kind alone is a description with no screw in it, so neither is enough (RK-10). The
    /// dumper asks <c>FastenerDumper.IsFastenerCandidate</c>, which lets a Toolbox part
    /// through whatever its names say.
    /// </summary>
    public static bool IsCandidate(string? fileName, string? description, string? configuration)
    {
        FastenerIdentity identity = Parse(configuration, description, fileName);
        return identity.ThreadDesignation != null && identity.Kind != FastenerKind.Other;
    }

    /// <summary>What one source said. Every field stays null when the text does not say it.</summary>
    private sealed class SourceReading
    {
        public string? ThreadDesignation { get; set; }

        public Quantity? Length { get; set; }

        public string? HeadType { get; set; }

        public FastenerKind? Kind { get; set; }
    }

    /// <summary>
    /// One normalized text, read with the whole grammar: the two vendor forms first, whose
    /// shapes cannot be mistaken for a Toolbox name, then the Toolbox forms; the head and the
    /// kind from the vocabulary first, then from a vendor head code.
    /// </summary>
    private static SourceReading ReadSource(string text)
    {
        var reading = new SourceReading();
        if (text.Length == 0)
        {
            return reading;
        }

        (FastenerKind Kind, string HeadType)? code = null;

        Match vendorFile = VendorFileName.Match(text);
        Match vendorText = VendorDescription.Match(text);
        if (vendorFile.Success)
        {
            ReadVendorSize(vendorFile, reading);
            if (HeadCodes.TryGetValue(vendorFile.Groups["code"].Value, out var known))
            {
                code = known;
            }
        }
        else if (vendorText.Success)
        {
            ReadVendorSize(vendorText, reading);
        }
        else
        {
            ReadSizeAndLength(text, reading);
        }

        reading.HeadType = FindHeadType(text) ?? code?.HeadType;
        reading.Kind = FindKind(text) ?? code?.Kind;
        return reading;
    }

    /// <summary>
    /// The size, hyphen pitch and length of a vendor form. The length is in millimetres: the
    /// description states the unit, and the file-name form is only ever metric.
    /// </summary>
    private static void ReadVendorSize(Match match, SourceReading reading)
    {
        reading.ThreadDesignation =
            "M" + match.Groups["size"].Value + "x" + match.Groups["pitch"].Value;
        reading.Length = MakeLength(match.Groups["length"].Value, LengthUnit.Mm);
    }

    /// <summary>The file name without a SOLIDWORKS extension, or unchanged when it has none.</summary>
    private static string? WithoutDocumentExtension(string? fileName)
    {
        if (fileName == null)
        {
            return null;
        }

        string trimmed = fileName.Trim();
        foreach (string extension in DocumentExtensions)
        {
            if (trimmed.EndsWith(extension, StringComparison.OrdinalIgnoreCase))
            {
                return trimmed.Substring(0, trimmed.Length - extension.Length);
            }
        }

        return trimmed;
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

    private static void ReadSizeAndLength(string text, SourceReading reading)
    {
        // "M6x1.0 x 20 - 20N": everything after a spaced hyphen is a thread-length or
        // grade suffix this parser does not claim to understand.
        int suffix = text.IndexOf(" - ", StringComparison.Ordinal);
        string core = suffix >= 0 ? text.Substring(0, suffix).Trim() : text;

        string[] tokens = SizeSeparator.Split(core);

        Match metric = MetricSize.Match(tokens[0]);
        if (metric.Success)
        {
            reading.ThreadDesignation = "M" + metric.Groups[1].Value;
            if (metric.Groups[2].Success)
            {
                // "M4-0.7 x 12": the hyphen already gave the pitch, so the next value can
                // only be the length, whether or not it carries a decimal point.
                reading.ThreadDesignation += "x" + metric.Groups[2].Value;
                if (tokens.Length >= 2)
                {
                    reading.Length = MakeLength(tokens[1], LengthUnit.Mm);
                }

                return;
            }

            ReadMetricPitchAndLength(tokens, reading);
            return;
        }

        if (InchSize.IsMatch(tokens[0]))
        {
            reading.ThreadDesignation = tokens[0];
            if (tokens.Length >= 2)
            {
                reading.Length = MakeLength(tokens[1], LengthUnit.In);
            }
        }
    }

    private static void ReadMetricPitchAndLength(string[] tokens, SourceReading reading)
    {
        if (tokens.Length == 1)
        {
            return;
        }

        if (tokens.Length >= 3)
        {
            // "M6 x 1.0 x 20": pitch then length.
            reading.ThreadDesignation += "x" + tokens[1];
            reading.Length = MakeLength(tokens[2], LengthUnit.Mm);
            return;
        }

        // One value after the size. A pitch is written with a decimal point ("M6x1.0");
        // a length is a whole number of millimetres ("M10x35"). Toolbox writes both this
        // way, and guessing the other way round would turn a 35 mm screw into a pitch.
        if (tokens[1].IndexOf('.') >= 0)
        {
            reading.ThreadDesignation += "x" + tokens[1];
        }
        else
        {
            reading.Length = MakeLength(tokens[1], LengthUnit.Mm);
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
