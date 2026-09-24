using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using IrMeasure = SwReview.Extractor.Ir.Measure;

namespace SwReview.Extractor.Probes;

/// <summary>
/// How <c>probe drawings</c> writes what it read (contracts/probes.md section 1): ids, counts,
/// member answers, enum numbers and millimetres - never a file name, path, property value, note
/// text or cell text - so its report can be pasted into the research of a public repository. Every
/// line the probes print goes through these, so the rule is kept in one place.
/// </summary>
public static class ProbeText
{
    /// <summary>What an answer the read did not give is printed as.</summary>
    public const string Unread = "unread";

    /// <summary>What a path, file name or stem is replaced with in a sentence the probe must repeat.</summary>
    public const string DrawingPlaceholder = "<drawing>";

    private const double InchInMillimetres = 25.4;

    private const double DegreesPerRadian = 180.0 / Math.PI;

    public static string Bool(bool? value) => value == null ? Unread : Bool(value.Value);

    public static string Bool(bool value) => value ? "true" : "false";

    public static string Int(int? value) => value == null ? Unread : Int(value.Value);

    public static string Int(int value) => value.ToString(CultureInfo.InvariantCulture);

    public static string Number(double? value) =>
        value == null ? Unread : value.Value.ToString("G6", CultureInfo.InvariantCulture);

    /// <summary>
    /// An exception as its type and HRESULT, <b>never its message</b>: a SOLIDWORKS or file-system
    /// message may carry the path or name of the very document the report must not name.
    /// </summary>
    public static string Failure(Exception error) =>
        error == null
            ? Unread
            : string.Format(CultureInfo.InvariantCulture, "{0} 0x{1:X8}", error.GetType().Name, error.HResult);

    /// <summary>
    /// A sentence of the product's own (a refusal of the confirmed open's seam) with every spelling
    /// of <paramref name="paths"/> - the full path, the file name and the stem, in any case -
    /// replaced by <see cref="DrawingPlaceholder"/>, longest first so a path is not left half
    /// replaced by its own file name.
    /// </summary>
    public static string Redact(string text, params string?[] paths)
    {
        if (string.IsNullOrEmpty(text))
        {
            return text ?? string.Empty;
        }

        var spellings = new List<string>();
        foreach (string? path in paths ?? Array.Empty<string?>())
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                continue;
            }

            string full = path!.Trim();
            string name = FileName(full);
            spellings.Add(full);
            spellings.Add(name);
            spellings.Add(name.Substring(0, name.Length - Extension(name).Length));
        }

        string result = text;
        foreach (string spelling in spellings.Where(s => s.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase)
                     .OrderByDescending(s => s.Length))
        {
            result = ReplaceIgnoringCase(result, spelling, DrawingPlaceholder);
        }

        return result;
    }

    /// <summary>
    /// A tolerance limit or any measured value, signed: a length in millimetres (from metres,
    /// millimetres or inches), an angle in degrees, to four decimals.
    /// </summary>
    public static string Limit(IrMeasure? measure)
    {
        if (measure == null)
        {
            return Unread;
        }

        (double value, string unit) = Normalised(measure);
        return (value >= 0 ? "+" : "-") + Math.Abs(value).ToString("F4", CultureInfo.InvariantCulture) + " " + unit;
    }

    /// <summary>A length in metres, in millimetres to four decimals, unsigned.</summary>
    public static string Millimetres(double metres) =>
        (metres * 1000.0).ToString("F4", CultureInfo.InvariantCulture) + " mm";

    /// <summary>Two measures agree when both are unread, or both read to the same value in the same kind of unit.</summary>
    public static bool SameMeasure(IrMeasure? first, IrMeasure? second)
    {
        if (first == null || second == null)
        {
            return first == null && second == null;
        }

        (double a, string unitA) = Normalised(first);
        (double b, string unitB) = Normalised(second);
        return string.Equals(unitA, unitB, StringComparison.Ordinal) && Math.Abs(a - b) < 1e-9;
    }

    /// <summary>"1 view" or "3 views".</summary>
    public static string Count(int count, string noun) =>
        count.ToString(CultureInfo.InvariantCulture) + " " + (count == 1 ? noun : noun + "s");

    /// <summary>"a", "a and b", "a, b and c".</summary>
    public static string And(IReadOnlyList<string> items)
    {
        if (items.Count <= 1)
        {
            return items.Count == 0 ? string.Empty : items[0];
        }

        return string.Join(", ", items.Take(items.Count - 1)) + " and " + items[items.Count - 1];
    }

    /// <summary>A document's kind from its extension, which names no file: part, assembly, drawing or other.</summary>
    public static string KindByExtension(string? path)
    {
        string extension = Extension(path ?? string.Empty).ToLowerInvariant();
        switch (extension)
        {
            case ".sldprt":
                return "part";
            case ".sldasm":
                return "assembly";
            case ".slddrw":
                return "drawing";
            default:
                return "other";
        }
    }

    /// <summary>
    /// The part of <paramref name="path"/> after its last separator. Written out rather than
    /// <see cref="Path.GetFileName(string)"/>, which on .NET Framework throws on a character the file
    /// system refuses - and a dimension's full name, which this is also asked of, may hold one.
    /// </summary>
    public static string FileName(string path)
    {
        int separator = Math.Max(path.LastIndexOf('\\'), path.LastIndexOf('/'));
        return separator < 0 ? path : path.Substring(separator + 1);
    }

    /// <summary>The file name's extension with its dot (<c>.SLDPRT</c>), or empty; never throws (see <see cref="FileName"/>).</summary>
    public static string Extension(string path)
    {
        string name = FileName(path);
        int dot = name.LastIndexOf('.');
        return dot <= 0 ? string.Empty : name.Substring(dot);
    }

    private static (double Value, string Unit) Normalised(IrMeasure measure)
    {
        switch ((measure.Unit ?? string.Empty).ToLowerInvariant())
        {
            case "m":
                return (measure.Value * 1000.0, "mm");
            case "in":
                return (measure.Value * InchInMillimetres, "mm");
            case "rad":
                return (measure.Value * DegreesPerRadian, "deg");
            case "deg":
                return (measure.Value, "deg");
            default:
                return (measure.Value, "mm");
        }
    }

    private static string ReplaceIgnoringCase(string text, string value, string replacement)
    {
        int index = text.IndexOf(value, StringComparison.OrdinalIgnoreCase);
        if (index < 0)
        {
            return text;
        }

        var builder = new System.Text.StringBuilder();
        int start = 0;
        while (index >= 0)
        {
            builder.Append(text, start, index - start).Append(replacement);
            start = index + value.Length;
            index = text.IndexOf(value, start, StringComparison.OrdinalIgnoreCase);
        }

        return builder.Append(text, start, text.Length - start).ToString();
    }
}
