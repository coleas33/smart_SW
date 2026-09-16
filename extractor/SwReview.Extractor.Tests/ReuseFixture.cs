using System;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;

namespace SwReview.Extractor.Tests;

/// <summary>
/// The one package the lever 9 tests reuse, and the package
/// `reviewer/tests/support/reuse.py::reuse_package()` builds: two documents, both stat'ed,
/// two resolved components of the second, dumped `full` with the shipped options.
///
/// Shared rather than rebuilt per test class so the cross-language digest in
/// <see cref="ReuseKeyTests"/> is pinned against the same package
/// <see cref="PackageReuseTests"/> copies around - two fixtures claiming to be the same
/// package are two chances to pin the wrong digest.
/// </summary>
internal static class ReuseFixture
{
    /// <summary>The shipped `dump` defaults, with an output directory the caller sets.</summary>
    public static DumpOptions Options(Action<DumpOptions>? change = null)
    {
        var options = new DumpOptions { OutputDirectory = "out" };
        change?.Invoke(options);
        return options;
    }

    /// <summary>The package, without its `reuse_key`: what a dump would have built.</summary>
    public static EvidencePackage Package()
    {
        return new EvidencePackage
        {
            SchemaVersion = "1.3.0",
            PackageId = new Guid("11111111-2222-4333-8444-555555555555"),
            CreatedAt = new DateTimeOffset(2026, 9, 12, 12, 0, 0, TimeSpan.Zero),
            Extractor = new ExtractorInfo
            {
                Name = "SwReview.Extractor",
                Version = "0.1.0",
                SwVersion = null,
                Machine = "test",
                Profile = DumpProfile.Full,
            },
            Manifest = new Manifest
            {
                Entries =
                {
                    new ManifestEntry
                    {
                        DocumentId = "doc:1",
                        VaultPath = "/Designs/cover-assy.SLDASM",
                        Configuration = "Default",
                        ExportMethod = ExportMethod.Native,
                        FileModifiedUtc = new DateTimeOffset(2026, 9, 10, 8, 30, 0, TimeSpan.Zero),
                        FileSizeBytes = 262144,
                    },
                    new ManifestEntry
                    {
                        DocumentId = "doc:2",
                        VaultPath = "/Designs/housing.SLDPRT",
                        Configuration = "Default",
                        ExportMethod = ExportMethod.Native,
                        FileModifiedUtc = new DateTimeOffset(2026, 9, 9, 17, 5, 0, TimeSpan.Zero),
                        FileSizeBytes = 98304,
                    },
                },
            },
            Design = new Design
            {
                DesignId = "design:1",
                Name = "cover-assy",
                RootAssemblyDocumentId = "doc:1",
                ActiveConfiguration = "Default",
            },
            Components =
            {
                Component("cmp:0001"),
                Component("cmp:0002"),
            },
        };
    }

    /// <summary>The package as a dump would have written it: with its key on it.</summary>
    public static EvidencePackage Dumped(DumpOptions options)
    {
        EvidencePackage package = Package();
        package.ReuseKey = ReuseKey.Of(package, options);
        return package;
    }

    private static ComponentInstance Component(string id) =>
        new ComponentInstance
        {
            Id = id,
            DocumentId = "doc:2",
            ReferencedConfiguration = "Default",
            Suppression = SuppressionState.Resolved,
        };
}
