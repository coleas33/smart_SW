using System;
using System.Collections;
using System.Collections.Generic;

namespace SwReview.Extractor.Guard;

/// <summary>
/// A view of a privately held collection that exposes no mutable collection interface (owner decision 160A):
/// a guard's set, or, since the decision's review, the read-only guard's array of denied prefixes, whose
/// members are distinct too. It can be counted and enumerated, and cast to nothing that can be changed - no
/// set, no list and no array, generic or not.
/// </summary>
internal sealed class ReadOnlySet<T> : IReadOnlyCollection<T>
{
    private readonly IReadOnlyCollection<T> _set;

    public ReadOnlySet(IReadOnlyCollection<T> set)
    {
        _set = set ?? throw new ArgumentNullException(nameof(set));
    }

    public int Count => _set.Count;

    public IEnumerator<T> GetEnumerator() => _set.GetEnumerator();

    IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
}
