using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// 004 build order, lane B (T153): the copy's length unit, read off <c>IModelDoc2.GetUnits()</c>
/// through a pure table, because it is the only stated source for FR-027's metres-to-document-unit
/// conversion and a wrong answer silently builds a part a thousand times off.
///
/// The table names every <c>swLengthUnit_e</c> member, so the planner refuses a unit it does not
/// convert by name rather than being told "could not be read"; the three it converts are the IR's
/// own tokens, pinned here against the Python module that converts them. Anything that is not a
/// recognised integer in the answer's first place is unknown (null), never metres.
/// </summary>
public class RemodelLengthUnitsTests
{
    /// <summary>Every <c>swLengthUnit_e</c> member and the token it is named by, pinned by value.</summary>
    public static IEnumerable<object[]> EveryUnit() => new[]
    {
        new object[] { swLengthUnit_e.swMM, 0, "mm" },
        new object[] { swLengthUnit_e.swCM, 1, "cm" },
        new object[] { swLengthUnit_e.swMETER, 2, "m" },
        new object[] { swLengthUnit_e.swINCHES, 3, "in" },
        new object[] { swLengthUnit_e.swFEET, 4, "ft" },
        new object[] { swLengthUnit_e.swFEETINCHES, 5, "ft-in" },
        new object[] { swLengthUnit_e.swANGSTROM, 6, "angstrom" },
        new object[] { swLengthUnit_e.swNANOMETER, 7, "nm" },
        new object[] { swLengthUnit_e.swMICRON, 8, "um" },
        new object[] { swLengthUnit_e.swMIL, 9, "mil" },
        new object[] { swLengthUnit_e.swUIN, 10, "uin" },
    };

    [Theory]
    [MemberData(nameof(EveryUnit))]
    public void EachUnitIsNamedByItsToken(swLengthUnit_e unit, int value, string token)
    {
        Assert.Equal(value, (int)unit);
        Assert.Equal(token, RemodelLengthUnits.TokenFor((int)unit));
    }

    /// <summary>A member added to the enum by a later interop is a red test until it is named.</summary>
    [Fact]
    public void TheTableIsEveryMemberOfTheEnum()
    {
        Assert.Equal(
            Enum.GetValues(typeof(swLengthUnit_e)).Cast<int>().OrderBy(value => value),
            EveryUnit().Select(row => (int)row[1]).OrderBy(value => value));
    }

    [Fact]
    public void EveryTokenIsDistinct()
    {
        List<string?> tokens = Enum.GetValues(typeof(swLengthUnit_e)).Cast<int>().Select(RemodelLengthUnits.TokenFor).ToList();

        Assert.DoesNotContain(null, tokens);
        Assert.Equal(tokens.Count, tokens.Distinct(StringComparer.Ordinal).Count());
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(11)]
    [InlineData(42)]
    [InlineData(int.MaxValue)]
    [InlineData(int.MinValue)]
    public void AnIntegerOutsideTheEnumIsUnknown(int value)
    {
        Assert.Null(RemodelLengthUnits.TokenFor(value));
    }

    /// <summary>
    /// The three units the planner converts (<c>DOCUMENT_LENGTH_UNITS</c> in
    /// <c>reviewer/src/swreview/remodel/units.py</c>) are exactly the tokens this table writes for
    /// millimetres, inches and metres, read from the Python source rather than restated, so the two
    /// ends of <c>document_length_unit</c> cannot drift apart.
    /// </summary>
    [Fact]
    public void ThePlannersThreeUnitsAreTheTokensForMillimetresInchesAndMetres()
    {
        string units = File.ReadAllText(Path.Combine(RepositoryRoot(), "reviewer", "src", "swreview", "remodel", "units.py"));
        Match declared = Regex.Match(units, @"DOCUMENT_LENGTH_UNITS:[^=]*=\s*\(([^)]*)\)");
        Assert.True(declared.Success, "DOCUMENT_LENGTH_UNITS was not found in units.py.");

        List<string> planner = Regex.Matches(declared.Groups[1].Value, "\"([^\"]*)\"")
            .Cast<Match>()
            .Select(match => match.Groups[1].Value)
            .ToList();

        Assert.Equal(
            new[]
            {
                RemodelLengthUnits.TokenFor((int)swLengthUnit_e.swMM),
                RemodelLengthUnits.TokenFor((int)swLengthUnit_e.swINCHES),
                RemodelLengthUnits.TokenFor((int)swLengthUnit_e.swMETER),
            },
            planner);
    }

    // ---- GetUnits()'s answer --------------------------------------------------------------------

    /// <summary>
    /// What <c>GetUnits()</c> may answer, and the token read from it. The documented answer is an
    /// array of five integers whose first is the <c>swLengthUnit_e</c>; only that first place is
    /// read, from the array's lower bound, and only when it holds an integer.
    /// </summary>
    private static readonly IReadOnlyDictionary<string, (object? Answer, string? Token)> Answers =
        new Dictionary<string, (object?, string?)>(StringComparer.Ordinal)
        {
            ["an int[] in millimetres"] = (new[] { 0, 0, 2, 3, 0 }, "mm"),
            ["an int[] in inches"] = (new[] { 3, 1, 16, 4, 1 }, "in"),
            ["an int[] in metres"] = (new[] { 2, 0, 2, 3, 0 }, "m"),
            ["an int[] in centimetres is named, for the planner to refuse by name"] = (new[] { 1, 0, 2, 3, 0 }, "cm"),
            ["an object[] of boxed integers"] = (new object[] { 3, 1, 16, 4, true }, "in"),
            ["a short in the first place"] = (new object[] { (short)2 }, "m"),
            ["a long in the first place"] = (new object[] { 0L }, "mm"),
            ["a byte in the first place"] = (new object[] { (byte)3 }, "in"),
            ["a lone element is enough"] = (new[] { 0 }, "mm"),
            ["an array whose lower bound is one is read from its lower bound"] = (OneBased(3, 0, 2), "in"),
            ["null is unknown"] = (null, null),
            ["an empty array is unknown"] = (new int[0], null),
            ["a lone integer that is not an array is unknown"] = (3, null),
            ["a string is unknown"] = ("mm", null),
            ["a double in the first place is unknown, never rounded"] = (new object[] { 3.0 }, null),
            ["a string in the first place is unknown, never parsed"] = (new object[] { "3" }, null),
            ["a null in the first place is unknown, never millimetres"] = (new object?[] { null, 0 }, null),
            ["a Boolean in the first place is unknown"] = (new object[] { true }, null),
            ["an integer outside the enum is unknown"] = (new[] { 42, 0 }, null),
            ["a negative integer is unknown"] = (new[] { -1, 0 }, null),
            ["a long too big for an int is unknown"] = (new object[] { long.MaxValue }, null),
            ["a two-dimensional array is unknown"] = (new int[,] { { 0, 0 } }, null),
        };

    public static IEnumerable<object[]> AnswerCases() => Answers.Keys.Select(shape => new object[] { shape });

    [Theory]
    [MemberData(nameof(AnswerCases))]
    public void TheUnitIsReadFromTheFirstPlaceOfGetUnitsAnswer(string shape)
    {
        (object? answer, string? token) = Answers[shape];

        Assert.Equal(token, RemodelLengthUnits.FromUnits(answer));
    }

    // ---- helpers --------------------------------------------------------------------------------

    private static Array OneBased(params int[] values)
    {
        Array array = Array.CreateInstance(typeof(int), new[] { values.Length }, new[] { 1 });
        for (int index = 0; index < values.Length; index++)
        {
            array.SetValue(values[index], index + 1);
        }

        return array;
    }

    /// <summary>The repository root: the folder above the test assembly that holds <c>reviewer/</c> and <c>extractor/</c>.</summary>
    private static string RepositoryRoot()
    {
        DirectoryInfo? directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory != null
            && !(Directory.Exists(Path.Combine(directory.FullName, "reviewer"))
                && Directory.Exists(Path.Combine(directory.FullName, "extractor"))))
        {
            directory = directory.Parent;
        }

        Assert.True(directory != null, "The repository root was not found above " + AppContext.BaseDirectory);
        return directory!.FullName;
    }
}
