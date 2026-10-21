using System;
using System.Collections;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>A view of a privately held set that exposes no mutable collection interface.</summary>
internal sealed class ReadOnlySet<T> : IReadOnlyCollection<T>
{
    private readonly HashSet<T> _set;

    public ReadOnlySet(HashSet<T> set)
    {
        _set = set ?? throw new ArgumentNullException(nameof(set));
    }

    public int Count => _set.Count;

    public IEnumerator<T> GetEnumerator() => _set.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}
