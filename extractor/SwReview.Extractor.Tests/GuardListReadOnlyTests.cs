using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Guard;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>Decision 160A: no published allowlist or exemption list exposes its mutable set.</summary>
public class GuardListReadOnlyTests
{
    public static IEnumerable<object[]> PublishedLists()
    {
        yield return new object[] { nameof(DrawingOpenGuard) + ".AllowedKeys", DrawingOpenGuard.AllowedKeys };
        yield return new object[] { nameof(RemodelSeatGuard) + ".AllowedKeys", RemodelSeatGuard.AllowedKeys };
        yield return new object[] { nameof(RemodelSeatGuard) + ".AllowedReads", RemodelSeatGuard.AllowedReads };
        yield return new object[] { nameof(RemodelGuard) + ".AllowedKeys", RemodelGuard.AllowedKeys };
        yield return new object[] { nameof(RemodelGuard) + ".ExcludedMembers", RemodelGuard.ExcludedMembers };
        yield return new object[] { nameof(RemodelProbeGuard) + ".ThrowawayPartCreationMembers", RemodelProbeGuard.ThrowawayPartCreationMembers };
        foreach (AllowlistGuard guard in new AllowlistGuard[] { new DrawingOpenGuard(), new RemodelSeatGuard(), new RemodelGuard() })
        {
            yield return new object[] { guard.GetType().Name + ".Keys", guard.Keys };
            yield return new object[] { guard.GetType().Name + ".Reads", guard.Reads };
        }
    }

    [Theory]
    [MemberData(nameof(PublishedLists))]
    public void APublishedListCanBeReadWithoutExposingAMutableCollection(string name, IReadOnlyCollection<string> list)
    {
        Assert.False(list is ICollection<string>, name + " exposes ICollection<string>.");
        Assert.False(list is ISet<string>, name + " exposes ISet<string>.");
        Assert.Equal(list.Count, list.Distinct(StringComparer.Ordinal).Count());
        Assert.Equal(list.Count, list.ToArray().Length);
        Assert.All(list, member => Assert.False(string.IsNullOrWhiteSpace(member)));
    }
}
