using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The test classes that start real stub children (<see cref="StubBackend"/>), run one at a time.
///
/// The test runner's console is one per process, and these classes change it or depend on it.
/// <c>BackendProcessTests</c> gives its console up for a test, to stand in for SOLIDWORKS, which
/// has none; a child started meanwhile anywhere in the runner gets a console of its own, and is
/// later asked to stop by attaching to that console and freeing it again (ChildProcess
/// .TryRequestStop) - process-wide, from whichever thread stops it. Two of those from classes
/// running side by side can leave the runner on the wrong console, or on none: a stop that then
/// cannot signal its child fails fast and terminates it without waiting out the grace period.
/// That is the reading of the code that explains
/// <c>ABackendThatIgnoresTheShutdownRequestIsTerminatedAfterTheGracePeriod</c> failing once under
/// a loaded run; the failure was not seen again. The add-in has no such overlap - every stop
/// there is made under the backend client's one gate - so it is the tests that are kept apart
/// (owner decision 143A).
/// </summary>
[CollectionDefinition(Name)]
public sealed class StubChildrenCollection
{
    /// <summary>The collection's name, for <c>[Collection(StubChildrenCollection.Name)]</c>.</summary>
    public const string Name = "Stub children";
}
