using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.PersistRefs;

namespace SwReview.AddIn.Remodel.Seat;

/// <summary>
/// The three readings the scope-signal reader and the copy's adapter both make, written once so
/// the two cannot drift apart at the COM level (feature 004, build order lane B): a SAFEARRAY
/// answer's elements, the feature walk, and a persistent reference's encoding. The copy's snapshot
/// and the probe's folder rows carry persist refs made by the one <see cref="PersistReference"/>,
/// which is what lets <c>remodel.open</c> step 12 compare them at all.
///
/// Ungated, like every class in this folder: the bridge gates each seam member from outside.
/// </summary>
internal static class SwRemodelReads
{
    /// <summary>
    /// A SAFEARRAY answer's elements, read from its lower bound, or null when the answer is not a
    /// one-dimensional array - a null answer included, because what a null means (none, or
    /// unreadable) differs between members and is the caller's to say.
    /// </summary>
    public static object?[]? Elements(object? answer)
    {
        if (!(answer is Array array) || array.Rank != 1)
        {
            return null;
        }

        int lowerBound = array.GetLowerBound(0);
        var elements = new object?[array.Length];
        for (int index = 0; index < array.Length; index++)
        {
            elements[index] = array.GetValue(lowerBound + index);
        }

        return elements;
    }

    /// <summary>
    /// <c>IFeatureManager.GetFeatures(ToplevelOnly)</c>, every element a feature, or null when the
    /// tree cannot be read: no feature manager, an answer that is not an array (a part always has
    /// its origin and planes, so a null answer is not an empty tree), or an element that is not a
    /// feature.
    /// </summary>
    public static IReadOnlyList<IFeature>? Features(IModelDoc2 document, bool topLevelOnly)
    {
        IFeatureManager? manager = document.FeatureManager;
        object?[]? elements = manager == null ? null : Elements(manager.GetFeatures(topLevelOnly));
        if (elements == null)
        {
            return null;
        }

        var features = new List<IFeature>(elements.Length);
        foreach (object? element in elements)
        {
            if (!(element is IFeature feature))
            {
                return null;
            }

            features.Add(feature);
        }

        return features;
    }

    /// <summary>
    /// <c>IModelDocExtension.GetPersistReference3(entity)</c>, encoded by the product's one
    /// <see cref="PersistRefCodec"/>; null when SOLIDWORKS answers anything but a non-empty byte
    /// array, because an entity with no reference cannot be addressed and a placeholder would
    /// address the wrong one.
    /// </summary>
    public static string? PersistReference(IModelDoc2 document, object entity)
    {
        IModelDocExtension? extension = document.Extension;
        if (extension == null)
        {
            return null;
        }

        return PersistRefCodec.TryEncode(extension.GetPersistReference3(entity) as byte[], out string? encoded)
            ? encoded
            : null;
    }
}
