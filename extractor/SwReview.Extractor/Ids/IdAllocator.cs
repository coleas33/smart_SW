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
    {
        if (string.IsNullOrWhiteSpace(prefix))
        {
            throw new ArgumentException("An id prefix is required, e.g. \"cmp\".", nameof(prefix));
        }

        _prefix = prefix;
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
