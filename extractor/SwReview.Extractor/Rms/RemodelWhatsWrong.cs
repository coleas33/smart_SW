using System;
using System.Collections.Generic;
using System.Globalization;
using SolidWorks.Interop.sldworks;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The one reading of <c>IModelDocExtension.GetWhatsWrong(out Features, out ErrorCodes, out
/// Warnings)</c>'s three parallel out-arrays (feature 004, build order lane B), shared by the probe
/// host - PROBE-9 asks what the <c>Features</c> array's element is - and the copy's adapter, whose
/// <c>remodel.rebuild</c> carries the entries as <c>whats_wrong[]</c>, corroborating only
/// (contracts/bridge-remodel.md): <c>GetErrorCode2</c> per feature is the primary reading.
///
/// The element type is UNVERIFIED on 2024 (PROBE-9), so a name and a live feature are both read
/// and anything else is described rather than assumed. Each array is read from its lower bound,
/// and a short code or warning array leaves that part of an entry out rather than padding or
/// shifting it: a rebuild message is evidence (default taken 2026-09-27, the owner may revise).
///
/// Nothing here is gated: the callers gate <c>GetWhatsWrong</c> itself, and telling the element
/// kind makes no interop call at all, so the probe's gated set is what it was.
/// </summary>
public static class RemodelWhatsWrong
{
    /// <summary>No element to read: no array, or an empty one.</summary>
    public const string Empty = "empty";

    /// <summary>The first element is a feature's name.</summary>
    public const string FeatureNames = "feature_names";

    /// <summary>The first element is a live <c>IFeature</c>.</summary>
    public const string FeatureObjects = "feature_objects";

    /// <summary>Anything else: this prefix and the runtime type's name, or <c>null</c>.</summary>
    public const string UnknownPrefix = "unknown:";

    /// <summary>An element that names no feature: a null, or a feature whose name reads null.</summary>
    public const string UnnamedFeature = "(unnamed feature)";

    /// <summary>
    /// PROBE-9's answer, from the runtime type of the <c>Features</c> array's first element:
    /// <see cref="FeatureNames"/>, <see cref="FeatureObjects"/>, <see cref="Empty"/>, or
    /// <see cref="UnknownPrefix"/> and the type's name. Unrecognised gives unknown rather than a
    /// guess. It asks the element nothing.
    /// </summary>
    public static string ElementKind(object? features)
    {
        object?[] elements = Items(features);
        if (elements.Length == 0)
        {
            return Empty;
        }

        object? first = elements[0];
        if (first is string)
        {
            return FeatureNames;
        }

        if (first is IFeature)
        {
            return FeatureObjects;
        }

        return UnknownPrefix + (first?.GetType().Name ?? "null");
    }

    /// <summary>
    /// One entry per <c>Features</c> element: <c>&lt;feature&gt;: error &lt;code&gt;</c>, with
    /// <c> (warning)</c> when its warning flag is true. The feature is a string element as it is,
    /// a live feature's name, <see cref="UnnamedFeature"/> for a null, and
    /// <c>(unrecognised element &lt;type&gt;)</c> otherwise. A code that is missing or null leaves
    /// <c>: error</c> out; a flag that is missing or not a Boolean leaves <c> (warning)</c> out.
    /// </summary>
    public static IReadOnlyList<string> Entries(object? features, object? errorCodes, object? warnings)
    {
        object?[] named = Items(features);
        object?[] codes = Items(errorCodes);
        object?[] flags = Items(warnings);

        var entries = new List<string>(named.Length);
        for (int index = 0; index < named.Length; index++)
        {
            string entry = Name(named[index]);

            object? code = At(codes, index);
            if (code != null)
            {
                entry += ": error " + Convert.ToString(code, CultureInfo.InvariantCulture);
            }

            if (At(flags, index) is bool warning && warning)
            {
                entry += " (warning)";
            }

            entries.Add(entry);
        }

        return entries;
    }

    private static string Name(object? element)
    {
        switch (element)
        {
            case null:
                return UnnamedFeature;
            case string name:
                return name;
            case IFeature feature:
                return feature.Name ?? UnnamedFeature;
            default:
                return "(unrecognised element " + element.GetType().Name + ")";
        }
    }

    /// <summary>
    /// One out-array as objects, read from its lower bound. Interop hands these back as
    /// <c>object[]</c>, <c>string[]</c> or <c>int[]</c> depending on the member and the build, so
    /// the array is read through <see cref="Array"/> rather than cast to one shape; anything that is
    /// not a one-dimensional array is no elements.
    /// </summary>
    private static object?[] Items(object? answer)
    {
        if (!(answer is Array array) || array.Rank != 1)
        {
            return new object?[0];
        }

        int lowerBound = array.GetLowerBound(0);
        var items = new object?[array.Length];
        for (int index = 0; index < array.Length; index++)
        {
            items[index] = array.GetValue(lowerBound + index);
        }

        return items;
    }

    private static object? At(object?[] items, int index) => index < items.Length ? items[index] : null;
}
