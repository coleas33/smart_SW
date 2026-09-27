using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// 004 build order, lane B: the one reading of <c>IModelDocExtension.GetWhatsWrong</c>'s three
/// out-arrays, shared by the probe host (PROBE-9's question: what is the <c>Features</c> array's
/// element?) and the copy's adapter (<c>remodel.rebuild</c>'s corroborating <c>whats_wrong[]</c>).
///
/// The element type is UNVERIFIED on 2024 (PROBE-9), so both a name and a live feature are read,
/// and anything else is described rather than assumed. The arrays are read from their lower bound,
/// and a short code or warning array leaves that part of the entry out rather than padding it.
/// </summary>
public class RemodelWhatsWrongTests
{
    // ---- PROBE-9's element kind (the probe host's ledger values, pinned) ------------------------

    public static IEnumerable<object?[]> ElementKinds() => new[]
    {
        new object?[] { "null is empty", null, "empty" },
        new object?[] { "an empty array is empty", new object[0], "empty" },
        new object?[] { "a value that is not an array is empty", "Fillet1", "empty" },
        new object?[] { "a name first", new object[] { "Fillet1", 7 }, "feature_names" },
        new object?[] { "a string[]", new[] { "Fillet1" }, "feature_names" },
        new object?[] { "an integer first", new object[] { 7 }, "unknown:Int32" },
        new object?[] { "a null first", new object?[] { null, "Fillet1" }, "unknown:null" },
        new object?[] { "a one-based array is read from its lower bound", OneBased("Fillet1"), "feature_names" },
    };

    [Theory]
    [MemberData(nameof(ElementKinds))]
    public void TheElementKindIsReadFromTheFirstElement(string shape, object? features, string kind)
    {
        Assert.NotNull(shape);
        Assert.Equal(kind, RemodelWhatsWrong.ElementKind(features));
    }

    [Fact]
    public void ALiveFeatureFirstIsAFeatureObject()
    {
        var feature = new InteropRecorder<IFeature>();

        Assert.Equal("feature_objects", RemodelWhatsWrong.ElementKind(new object[] { feature.Instance }));

        // Telling the kind asks the feature nothing: PROBE-9's gated set stays what it was.
        Assert.Empty(feature.Calls);
    }

    // ---- the entries remodel.rebuild corroborates with ------------------------------------------

    [Fact]
    public void EachElementIsOneEntryWithItsCodeAndItsWarningFlag()
    {
        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            new object[] { "Fillet1", "Cut-Extrude1" },
            new object[] { 3, 5 },
            new object[] { false, true });

        Assert.Equal(new[] { "Fillet1: error 3", "Cut-Extrude1: error 5 (warning)" }, entries);
    }

    [Fact]
    public void TypedArraysAreReadLikeObjectArrays()
    {
        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            new[] { "Fillet1" }, new[] { 12 }, new[] { true });

        Assert.Equal(new[] { "Fillet1: error 12 (warning)" }, entries);
    }

    [Fact]
    public void ALiveFeatureIsNamedByItsName()
    {
        var feature = new InteropRecorder<IFeature>().Answer("get_Name", "Shell1");

        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            new object[] { feature.Instance }, new object[] { 2 }, new object[] { false });

        Assert.Equal(new[] { "Shell1: error 2" }, entries);
        Assert.Equal(new[] { "get_Name" }, feature.Members);
    }

    [Fact]
    public void AFeatureWhoseNameIsNullAndANullElementAreUnnamed()
    {
        var feature = new InteropRecorder<IFeature>().Answer("get_Name", null);

        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            new object?[] { feature.Instance, null }, new object[] { 1, 2 }, new object[] { false, false });

        Assert.Equal(new[] { "(unnamed feature): error 1", "(unnamed feature): error 2" }, entries);
    }

    [Fact]
    public void AnElementThatIsNeitherANameNorAFeatureIsDescribedNotGuessed()
    {
        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            new object[] { 7, 2.5 }, new object[] { 1, 1 }, new object[] { false, false });

        Assert.Equal(new[] { "(unrecognised element Int32): error 1", "(unrecognised element Double): error 1" }, entries);
    }

    /// <summary>A short code or warning array leaves that part out; it never pads or shifts.</summary>
    [Fact]
    public void AShortCodeOrWarningArrayLeavesThatPartOut()
    {
        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            new object[] { "Fillet1", "Cut-Extrude1", "Shell1" },
            new object[] { 3 },
            new object[] { true, true });

        Assert.Equal(new[] { "Fillet1: error 3 (warning)", "Cut-Extrude1 (warning)", "Shell1" }, entries);
    }

    [Fact]
    public void MissingCodeAndWarningArraysLeaveOnlyTheNames()
    {
        Assert.Equal(new[] { "Fillet1" }, RemodelWhatsWrong.Entries(new object[] { "Fillet1" }, null, null));
    }

    [Fact]
    public void ANullCodeElementAndANonBooleanWarningAreLeftOut()
    {
        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            new object[] { "Fillet1" }, new object?[] { null }, new object[] { "true" });

        Assert.Equal(new[] { "Fillet1" }, entries);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("Fillet1")]
    [InlineData(7)]
    public void NoFeaturesArrayIsNoEntries(object? features)
    {
        Assert.Empty(RemodelWhatsWrong.Entries(features, new object[] { 1 }, new object[] { true }));
    }

    [Fact]
    public void OneBasedArraysAreReadFromTheirLowerBounds()
    {
        IReadOnlyList<string> entries = RemodelWhatsWrong.Entries(
            OneBased("Fillet1", "Shell1"), OneBased(4, 6), OneBased(false, true));

        Assert.Equal(new[] { "Fillet1: error 4", "Shell1: error 6 (warning)" }, entries);
    }

    /// <summary>The code is written in the invariant culture: a code is a number, not prose.</summary>
    [Fact]
    public void ACodeIsWrittenInTheInvariantCulture()
    {
        System.Globalization.CultureInfo before = System.Globalization.CultureInfo.CurrentCulture;
        try
        {
            System.Globalization.CultureInfo.CurrentCulture = new System.Globalization.CultureInfo("de-DE");

            Assert.Equal(
                new[] { "Fillet1: error 1234567" },
                RemodelWhatsWrong.Entries(new object[] { "Fillet1" }, new object[] { 1234567 }, null));
        }
        finally
        {
            System.Globalization.CultureInfo.CurrentCulture = before;
        }
    }

    // ---- the probe host reads the kind through the shared class ---------------------------------

    /// <summary>
    /// The element reading is written once: the probe host names the shared class and keeps no
    /// reading of its own.
    /// </summary>
    [Fact]
    public void TheProbeHostReadsTheElementKindThroughTheSharedClass()
    {
        string source = ProbeWrapperCases.ProductSource("SwRemodelProbeHost.cs");

        Assert.Contains("RemodelWhatsWrong.ElementKind(", source, StringComparison.Ordinal);
        Assert.DoesNotContain("\"feature_names\"", source, StringComparison.Ordinal);
        Assert.DoesNotContain("\"feature_objects\"", source, StringComparison.Ordinal);
    }

    private static Array OneBased<T>(params T[] values)
    {
        Array array = Array.CreateInstance(typeof(T), new[] { values.Length }, new[] { 1 });
        for (int index = 0; index < values.Length; index++)
        {
            array.SetValue(values[index], index + 1);
        }

        return array;
    }
}
