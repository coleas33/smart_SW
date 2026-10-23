using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.AddIn.Terminal;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The final review of owner decision 160A, found on the way, the same shape as the decision's item 2 (feature 011
/// research R14): the Terminal tab's published lists - the read-only toolset its CLI profiles allow, and each CLI's
/// built-ins the first-launch check sanctions - were arrays typed as read-only lists, which a cast turns back into the
/// array and writes through. Each is held to being a read-only view, which no cast can write through: no array, no
/// list and no collection, generic or not; and to counting, indexing and enumerating as before.
/// </summary>
public class TerminalListReadOnlyTests
{
    public static IEnumerable<object[]> PublishedLists()
    {
        yield return new object[] { nameof(CliProfileWriter) + ".EnabledTools", CliProfileWriter.EnabledTools };
        yield return new object[] { nameof(ToolListingCheck) + ".CodexBuiltIns", ToolListingCheck.CodexBuiltIns };
        yield return new object[] { nameof(ToolListingCheck) + ".GeminiBuiltIns", ToolListingCheck.GeminiBuiltIns };
    }

    [Theory]
    [MemberData(nameof(PublishedLists))]
    public void APublishedListCanBeReadWithoutExposingAWritableOne(string name, IReadOnlyList<string> list)
    {
        Assert.False(list is string[], name + " is an array.");
        Assert.False(list is ICollection<string>, name + " exposes ICollection<string>.");
        Assert.False(list is System.Collections.IList, name + " exposes IList.");
        Assert.False(list is System.Collections.ICollection, name + " exposes ICollection.");
        Assert.NotEmpty(list);
        Assert.Equal(list.Count, list.ToArray().Length);
        Assert.Equal(list.ToArray(), Enumerable.Range(0, list.Count).Select(index => list[index]).ToArray());
        Assert.Equal(list.Count, list.Distinct(StringComparer.Ordinal).Count());
        Assert.All(list, member => Assert.False(string.IsNullOrWhiteSpace(member)));
    }
}
