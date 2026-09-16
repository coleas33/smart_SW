using System;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T089/T091. The package-reuse key, and the one thing this side of it has to get right:
/// <b>the same package must hash to the same digest in C# and in Python</b>.
///
/// The invalidation table - one row per change the key must catch - is tested once, in
/// `reviewer/tests/unit/test_reuse_key.py`, over `swreview/benchmark/reuse.py`. Restating
/// those twenty rows here would be the same table maintained twice, and two tables drift.
/// What cannot be tested there is that this implementation agrees with that one, so that is
/// what is tested here: the canonical form is pinned character for character against the
/// text `benchmark/reuse.py` produces for the same package, and the digest against the
/// SHA-256 of it.
///
/// If this test fails after a change to either side, the two languages have stopped agreeing
/// on what a package is, and every reuse decision made from a stored key is a guess.
/// </summary>
public sealed class ReuseKeyTests
{
    /// <summary>
    /// `canonical_form(key_parts(reuse_package(), DumpOptions()))` from
    /// `reviewer/tests/support/reuse.py`, verbatim.
    /// </summary>
    private const string PythonCanonicalForm =
        "{\"extractor_name\":\"SwReview.Extractor\",\"extractor_version\":\"0.1.0\","
        + "\"schema_version\":\"1.3.0\",\"profile\":\"full\",\"meshes\":\"glb\","
        + "\"faces\":\"needed\",\"features\":\"tree\",\"equations\":\"on\","
        + "\"root_assembly_document_id\":\"doc:1\",\"active_configuration\":\"Default\","
        + "\"documents\":[{\"document_id\":\"doc:1\",\"configuration\":\"Default\","
        + "\"referenced_configurations\":[],\"file_modified_utc\":\"2026-09-10T08:30:00+00:00\","
        + "\"file_size_bytes\":262144},{\"document_id\":\"doc:2\",\"configuration\":\"Default\","
        + "\"referenced_configurations\":[\"Default\"],"
        + "\"file_modified_utc\":\"2026-09-09T17:05:00+00:00\",\"file_size_bytes\":98304}],"
        + "\"components\":[{\"component_id\":\"cmp:0001\",\"suppression\":\"resolved\"},"
        + "{\"component_id\":\"cmp:0002\",\"suppression\":\"resolved\"}]}";

    /// <summary>`package_reuse_key(reuse_package(), DumpOptions())`, verbatim.</summary>
    private const string PythonDigest =
        "35753b68428470782750128ffbfa09db185497d00cc320ddb297752b18d2a845";

    [Fact]
    public void TheCanonicalForm_IsTheTextPythonHashes()
    {
        Assert.Equal(PythonCanonicalForm, ReuseKey.CanonicalForm(Fixture(), Options()));
    }

    [Fact]
    public void TheDigest_IsTheDigestPythonComputes()
    {
        Assert.Equal(PythonDigest, ReuseKey.Of(Fixture(), Options()));
    }

    [Fact]
    public void PackageIdAndCreatedAt_AreNotInTheKey()
    {
        // PackageWriter assigns a fresh Guid and timestamp on every dump, so a key that
        // included either would never match anything and the lever could not work at all.
        EvidencePackage other = Fixture();
        other.PackageId = Guid.NewGuid();
        other.CreatedAt = DateTimeOffset.UtcNow;

        Assert.Equal(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void ReuseProvenance_IsNotInTheKey()
    {
        // A reused package is the package a dump would have written; that it was copied is
        // recorded on it, and recording it must not make it a different design.
        EvidencePackage other = Fixture();
        other.ReuseKey = "stale";
        other.ReusedFrom = "20260910-083000-cover-assy";
        other.ReusedAt = DateTimeOffset.UtcNow;

        Assert.Equal(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void TraversalOrder_IsNotAChange()
    {
        EvidencePackage other = Fixture();
        other.Manifest.Entries.Reverse();
        other.Components.Reverse();

        Assert.Equal(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void ASavedFile_ChangesTheKey()
    {
        EvidencePackage other = Fixture();
        other.Manifest.Entries[0].FileSizeBytes += 512;

        Assert.NotEqual(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void AnUnknownStat_IsNotTheSameKeyAsAKnownOne()
    {
        // Unknown is a value in the key, never a wildcard that matches everything. Whether
        // an unknown may be reused on at all is a refusal, not a key part.
        EvidencePackage other = Fixture();
        other.Manifest.Entries[0].FileModifiedUtc = null;

        Assert.NotEqual(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void ADumpOptionChangesTheKey()
    {
        Assert.NotEqual(
            ReuseKey.Of(Fixture(), Options()),
            ReuseKey.Of(Fixture(), Options(o => o.Meshes = MeshFormat.None)));
    }

    [Fact]
    public void TheProfileChangesTheKey()
    {
        // A model_check package has empty holes[], fasteners[], faces[] and bodies[] by
        // design; handing one to a review that asked for full silently narrows the review.
        EvidencePackage other = Fixture();
        other.Extractor.Profile = DumpProfile.ModelCheck;

        Assert.NotEqual(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void AComponentResolvedFromSuppressed_ChangesTheKey()
    {
        EvidencePackage other = Fixture();
        other.Components[0].Suppression = SuppressionState.Suppressed;

        Assert.NotEqual(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void AMicrosecondInTheModificationTime_SurvivesIntoTheKey()
    {
        // Python datetimes carry microseconds and nothing finer, which is why the dump
        // truncates the .NET tick. A digest that dropped them would call two different
        // saves the same design.
        EvidencePackage other = Fixture();
        other.Manifest.Entries[0].FileModifiedUtc =
            other.Manifest.Entries[0].FileModifiedUtc!.Value.AddTicks(10);

        Assert.Contains("08:30:00.000001+00:00", ReuseKey.CanonicalForm(other, Options()));
        Assert.NotEqual(PythonDigest, ReuseKey.Of(other, Options()));
    }

    [Fact]
    public void AValueThatLooksLikeASeparator_IsStillOneValue()
    {
        // The canonical form is JSON rather than a delimiter-joined string precisely so a
        // configuration named with a quote or a brace cannot impersonate the structure.
        EvidencePackage quoted = Fixture();
        quoted.Design.ActiveConfiguration = "De\"fault";
        EvidencePackage plain = Fixture();
        plain.Design.ActiveConfiguration = "De\\\"fault";

        Assert.Contains("\"active_configuration\":\"De\\\"fault\"", ReuseKey.CanonicalForm(quoted, Options()));
        Assert.NotEqual(ReuseKey.Of(quoted, Options()), ReuseKey.Of(plain, Options()));
    }

    private static DumpOptions Options(Action<DumpOptions>? change = null) =>
        ReuseFixture.Options(change);

    /// <summary>The package `reviewer/tests/support/reuse.py::reuse_package()` builds.</summary>
    private static EvidencePackage Fixture() => ReuseFixture.Package();
}
