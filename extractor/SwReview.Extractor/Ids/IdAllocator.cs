using System;
using System.Globalization;

namespace SwReview.Extractor.Ids;

/// <summary>
/// Hands out <c>prefix:NNNN</c> ids in allocation order. Component ids must match the IR
/// schema pattern <c>^cmp:[0-9]{4,}$</c>, and the reviewer reads them as a traversal order,
/// so the counter is never reset or reused within a package.
/// </summary>
public sealed class IdAllocator
{
    private readonly string _prefix;
    private int _next;

    public IdAllocator(string prefix)
        : this(prefix, 0)
    {
    }

    /// <summary>
    /// Starts counting after <paramref name="issued"/> ids. Used when a command appends to
    /// a package that already holds rows with this prefix (T071): the next id must not
    /// collide with one the reviewer may already have cited.
    /// </summary>
    public IdAllocator(string prefix, int issued)
    {
        if (string.IsNullOrWhiteSpace(prefix))
        {
            throw new ArgumentException("An id prefix is required, e.g. \"cmp\".", nameof(prefix));
        }

        if (issued < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(issued), issued, "An id allocator cannot start below zero.");
        }

        _prefix = prefix;
        _next = issued;
    }

    /// <summary>
    /// The highest number already used for <paramref name="prefix"/> in
    /// <paramref name="existingIds"/>, so a new allocator can continue past it. Ids that do
    /// not match the prefix, or whose number does not parse, are ignored.
    /// </summary>
    public static int HighestIssued(string prefix, System.Collections.Generic.IEnumerable<string> existingIds)
    {
        if (string.IsNullOrWhiteSpace(prefix))
        {
            throw new ArgumentException("An id prefix is required, e.g. \"cap\".", nameof(prefix));
        }

        if (existingIds == null)
        {
            return 0;
        }

        string head = prefix + ":";
        int highest = 0;
        foreach (string id in existingIds)
        {
            if (id == null || !id.StartsWith(head, StringComparison.Ordinal))
            {
                continue;
            }

            int number;
            if (int.TryParse(
                    id.Substring(head.Length), NumberStyles.None, CultureInfo.InvariantCulture, out number)
                && number > highest)
            {
                highest = number;
            }
        }

        return highest;
    }

    /// <summary>How many ids have been issued.</summary>
    public int Count => _next;

    /// <summary>The next id, zero-padded to at least four digits.</summary>
    public string Next()
    {
        _next++;
        return _prefix + ":" + _next.ToString("D4", CultureInfo.InvariantCulture);
    }
}
