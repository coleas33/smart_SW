using System;
using System.Collections.Generic;
using System.Globalization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// T055. The SOLIDWORKS side of <see cref="ISuppressTarget"/>: interop calls and nothing
/// else, so every decision <see cref="SuppressTest"/> makes is testable without a seat (the
/// same split as <c>FeatureDumper</c> and <see cref="SwFeatureReader"/>).
///
/// Interop notes, all against the 2024 SP5 interop (research R5):
///   - the walk is <see cref="SwFeatureReader"/>'s, flattened by
///     <see cref="FeatureTreeIndexer"/>, so "the live tree" here is the same order and the
///     same depth a <c>dump</c> would record - which is what makes comparing the walk with
///     the package's rows meaningful at all.
///   - <c>SetSuppression2(SuppressionState, Config_opt, Config_names)</c> takes
///     <c>swSuppressFeature</c>/<c>swUnSuppressFeature</c> and
///     <c>swThisConfiguration</c>, so no configuration name is passed and no other
///     configuration is touched.
///   - <c>GetWhatsWrong(out Features, out ErrorCodes, out Warnings)</c> answers with three
///     parallel VARIANT arrays; a short or missing array is reported as what it is rather
///     than padded, because a rebuild message is evidence.
///   - <c>IsSamePersistentID</c> is asked through <see cref="PersistRefService"/>: reference
///     bytes for one entity differ between calls and are never compared here (research R12).
///   - The two mutating members ask <see cref="SwGate.Assert"/> themselves, before the call.
///     Every other member here is a reader whose gating is the caller's, as in
///     <see cref="SwFeatureReader"/>; these two are the product's entire mutation surface, so
///     they are refused under any gate that was not built with a
///     <see cref="SuppressTestGuard"/> even if a caller never asked.
///   - No save member is reachable from this class. <c>GetSaveFlag</c> READS the dirty flag;
///     <c>SetSaveFlag</c>, <c>Save3</c> and <c>SaveAs3</c> appear nowhere, and the gate the
///     command builds refuses them anyway.
/// </summary>
public sealed class SwSuppressTarget : ISuppressTarget
{
    private readonly SwGate _gate;
    private readonly IModelDoc2 _document;
    private readonly SwFeatureReader _reader;
    private readonly PersistRefService _refs;

    public SwSuppressTarget(SwGate gate, IModelDoc2 document, PersistRefService refs)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _document = document ?? throw new ArgumentNullException(nameof(document));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
        _reader = new SwFeatureReader(gate, refs);
    }

    /// <inheritdoc />
    public string ActiveConfiguration() => _reader.ActiveConfiguration(_document);

    /// <inheritdoc />
    public bool HasUnsavedChanges() => _document.GetSaveFlag();

    /// <inheritdoc />
    public IReadOnlyList<LiveFeature> Walk()
    {
        IReadOnlyList<FeatureTreeNode> walk = _reader.Walk(_document);

        // The allocator's ids are thrown away: the package's ids are the ones the run
        // records, and this call only wants the index and depth the same walk would produce.
        IReadOnlyList<FeatureTreeRow> rows = FeatureTreeIndexer.Index(walk, new IdAllocator("feat"));

        var features = new List<LiveFeature>(rows.Count);
        foreach (FeatureTreeRow row in rows)
        {
            object? handle = row.Node.Handle;
            if (handle == null)
            {
                throw new InvalidOperationException(
                    $"The walk produced no live feature for '{row.Node.Name}', so its suppression "
                    + "could neither be read nor put back.");
            }

            features.Add(new LiveFeature(row.Node.Name, row.Node.TypeName, row.Depth, handle));
        }

        return features;
    }

    /// <inheritdoc />
    public bool IsRolledBack(object feature) => Feature(feature).IsRolledBack();

    /// <inheritdoc />
    public bool IsSuppressed(object feature, string configuration) =>
        _reader.Suppressed(feature, configuration);

    /// <inheritdoc />
    public bool Suppress(object feature, bool suppress, string configuration)
    {
        // The guard is asked HERE, at the interop call, not only by the SuppressTest that
        // wraps it: these two members are the product's whole mutation surface, and they must
        // be unreachable under a gate nobody asked. Asking twice costs one hash lookup and
        // nothing else - the observer keeps distinct names, and Assert does not touch the
        // breaker.
        _gate.Assert(SuppressTest.Member.SetSuppression);

        return Feature(feature).SetSuppression2(
            (int)(suppress
                ? swFeatureSuppressionAction_e.swSuppressFeature
                : swFeatureSuppressionAction_e.swUnSuppressFeature),
            (int)swInConfigurationOpts_e.swThisConfiguration,
            null);
    }

    /// <inheritdoc />
    public void Rebuild()
    {
        _gate.Assert(SuppressTest.Member.Rebuild);
        _document.ForceRebuild3(false);
    }

    /// <inheritdoc />
    public int WhatsWrongCount() => _document.Extension.GetWhatsWrongCount();

    /// <inheritdoc />
    public IReadOnlyList<string> WhatsWrongMessages(int max)
    {
        var messages = new List<string>();
        if (max <= 0)
        {
            return messages;
        }

        object features;
        object errorCodes;
        object warnings;
        if (!_document.Extension.GetWhatsWrong(out features, out errorCodes, out warnings))
        {
            return messages;
        }

        object?[] named = Items(features);
        object?[] codes = Items(errorCodes);
        object?[] flags = Items(warnings);

        for (int i = 0; i < named.Length && messages.Count < max; i++)
        {
            messages.Add(Describe(named[i], At(codes, i), At(flags, i)));
        }

        return messages;
    }

    /// <inheritdoc />
    public bool IsSameFeature(string persistRef, object feature)
    {
        ScopedPersistRef live = _refs.Get(_document, feature);
        return _refs.IsSame(_document, persistRef, live.Base64);
    }

    /// <summary>
    /// One rebuild message. The feature comes back as a name or as an <c>IFeature</c>
    /// depending on the release, so both are handled and neither is invented: an entry with
    /// no readable feature says so rather than being dropped.
    /// </summary>
    private string Describe(object? named, object? code, object? warning)
    {
        string feature;
        switch (named)
        {
            case null:
                feature = "(unnamed feature)";
                break;
            case string text:
                feature = text;
                break;
            case IFeature live:
                feature = _gate.Call("Feature.Name", () => live.Name) ?? "(unnamed feature)";
                break;
            default:
                feature = named.ToString() ?? "(unnamed feature)";
                break;
        }

        string described = code == null
            ? feature
            : feature + ": error " + Convert.ToString(code, CultureInfo.InvariantCulture);

        return warning is bool flag && flag ? described + " (warning)" : described;
    }

    /// <summary>
    /// One VARIANT array as objects. Interop hands these back as <c>object[]</c>,
    /// <c>string[]</c> or <c>int[]</c> depending on the member and the build, so the array is
    /// read through <see cref="Array"/> rather than cast to one shape.
    /// </summary>
    private static object?[] Items(object? answer)
    {
        if (!(answer is Array array))
        {
            return new object?[0];
        }

        var items = new object?[array.Length];
        for (int i = 0; i < array.Length; i++)
        {
            items[i] = array.GetValue(i);
        }

        return items;
    }

    private static object? At(object?[] items, int index) =>
        index < items.Length ? items[index] : null;

    private static IFeature Feature(object feature) => (IFeature)feature;
}
