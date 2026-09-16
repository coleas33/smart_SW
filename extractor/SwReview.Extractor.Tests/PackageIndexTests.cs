using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T090. The C# half of the run-folder index (the Python half is
/// `reviewer/tests/unit/test_package_index.py`, over the same file format).
///
/// There is no index of run folders in the shipped build (all VERIFIED):
/// <c>RunFolders.Create</c> always makes a fresh timestamped folder, "the pane's latest run"
/// is an in-memory field cleared on detach, and <c>RunFolders.ProfileOf</c> reads only the
/// first 8 KiB of one <c>package.json</c> <b>because</b> a full package is tens of megabytes
/// and the read happens on the SOLIDWORKS application thread. So the dump appends one line
/// per run folder to <c>run_root/package-index.json</c> and the lookup reads that.
///
/// Three rules, each a way this can go wrong: a missing or unparseable index is a <b>miss,
/// never an error</b>; the lookup <b>verifies the folder and its package.json still exist</b>,
/// because the index cannot know an engineer deleted a folder in Explorer; and the fallback
/// scan is <b>bounded</b> to the most recent folders and reads only the head of each package.
/// </summary>
public sealed class PackageIndexTests : IDisposable
{
    private const string Key = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private const string OtherKey = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    private readonly string _root;

    public PackageIndexTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.PackageIndex.Tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
            // A temp directory that will not delete is not a test failure.
        }
    }

    // --- appending -------------------------------------------------------------------

    [Fact]
    public void TheIndexHoldsOneLinePerRunFolder()
    {
        PackageIndex.Append(_root, Row("20260912-120000-cover"));
        PackageIndex.Append(_root, Row("20260912-130000-cover", key: OtherKey));

        string[] lines = File.ReadAllLines(Path.Combine(_root, PackageIndex.IndexFileName));

        Assert.Equal(2, lines.Length);
        Assert.Equal(
            new[] { "20260912-120000-cover", "20260912-130000-cover" },
            PackageIndex.Read(_root).Select(row => row.Folder));
    }

    [Fact]
    public void ARowCarriesWhatTheLookupNeedsBeforeOpeningAnything()
    {
        PackageIndex.Append(_root, Row("20260912-120000-cover"));

        PackageIndexRow row = Assert.Single(PackageIndex.Read(_root));

        Assert.Equal(Key, row.ReuseKey);
        Assert.Equal("full", row.Profile);
        Assert.Equal(262144, row.PackageBytes);
        Assert.Equal(new DateTimeOffset(2026, 9, 12, 12, 0, 0, TimeSpan.Zero), row.WrittenAt);
    }

    [Fact]
    public void AnIndexThatCannotBeWritten_IsNotAFailedDump()
    {
        // The index is a cache of what is already on disk. A dump that succeeded must not be
        // reported as failed because a line could not be appended to it.
        Assert.False(PackageIndex.Append("\0bad", Row("20260912-120000-cover")));
    }

    // --- a miss is never an error ------------------------------------------------------

    [Fact]
    public void NoIndexAtAll_IsAMiss()
    {
        Assert.Empty(PackageIndex.Read(_root));
        Assert.Null(Find());
    }

    [Fact]
    public void AnUnparseableIndex_IsAMissAndNotAnError()
    {
        File.WriteAllText(Path.Combine(_root, PackageIndex.IndexFileName), "this is not json\n{\n");

        Assert.Empty(PackageIndex.Read(_root));
        Assert.Null(Find());
    }

    [Fact]
    public void AHalfWrittenLastLine_DoesNotCostTheEarlierRows()
    {
        WriteRun("20260912-120000-cover");
        PackageIndex.Append(_root, Row("20260912-120000-cover"));
        File.AppendAllText(Path.Combine(_root, PackageIndex.IndexFileName), "{\"reuse_key\": \"aaa");

        Assert.Single(PackageIndex.Read(_root));
        Assert.NotNull(Find());
    }

    [Fact]
    public void AMissingRunRoot_IsAMiss()
    {
        Assert.Empty(PackageIndex.Read(Path.Combine(_root, "no-such-root")));
        Assert.Null(PackageIndex.FindReusable(Path.Combine(_root, "no-such-root"), Key, DumpProfile.Full));
        Assert.Null(PackageIndex.FindReusable(null, Key, DumpProfile.Full));
    }

    // --- what the lookup verifies ------------------------------------------------------

    [Fact]
    public void AMatchingRowWhoseFolderStillExists_IsAHit()
    {
        WriteRun("20260912-120000-cover");
        PackageIndex.Append(_root, Row("20260912-120000-cover"));

        Assert.Equal("20260912-120000-cover", Find()!.Folder);
    }

    [Fact]
    public void ARowWhoseFolderWasDeletedByHand_IsAMiss()
    {
        PackageIndex.Append(_root, Row("20260912-120000-cover"));

        Assert.Null(Find());
    }

    [Fact]
    public void AFolderWithoutAPackage_IsAMiss()
    {
        Directory.CreateDirectory(Path.Combine(_root, "20260912-120000-cover"));
        PackageIndex.Append(_root, Row("20260912-120000-cover"));

        Assert.Null(Find());
    }

    [Fact]
    public void ADifferentKey_IsAMiss()
    {
        WriteRun("20260912-120000-cover", key: OtherKey);
        PackageIndex.Append(_root, Row("20260912-120000-cover", key: OtherKey));

        Assert.Null(Find());
    }

    [Fact]
    public void ADifferentProfile_IsAMiss()
    {
        // A model_check package has empty holes[], fasteners[], faces[] and bodies[] by
        // design; the row carries the profile so that is rejected before a file is opened.
        WriteRun("20260912-120000-cover", profile: "model_check");
        PackageIndex.Append(_root, Row("20260912-120000-cover", profile: "model_check"));

        Assert.Null(Find());
        Assert.NotNull(PackageIndex.FindReusable(_root, Key, DumpProfile.ModelCheck));
    }

    [Fact]
    public void AFolderThatLeavesTheRunRoot_IsRefused()
    {
        PackageIndex.Append(_root, Row("../elsewhere"));

        Assert.Null(Find());
    }

    [Fact]
    public void TheMostRecentMatchingRowWins()
    {
        WriteRun("20260912-120000-cover");
        WriteRun("20260912-130000-cover");
        PackageIndex.Append(_root, Row("20260912-120000-cover"));
        PackageIndex.Append(
            _root,
            Row("20260912-130000-cover", writtenAt: new DateTimeOffset(2026, 9, 12, 13, 0, 0, TimeSpan.Zero)));

        Assert.Equal("20260912-130000-cover", Find()!.Folder);
    }

    // --- the bounded fallback ----------------------------------------------------------

    [Fact]
    public void WithNoIndexTheMostRecentFoldersAreScanned()
    {
        WriteRun("20260912-120000-cover");

        PackageIndexRow? found = Find();

        Assert.NotNull(found);
        Assert.Equal("20260912-120000-cover", found!.Folder);
        Assert.True(found.PackageBytes > 0);
    }

    [Fact]
    public void TheScanIsCappedAtTheMostRecentFolders()
    {
        WriteRun("20260101-000000-cover");
        for (int i = 0; i < PackageIndex.ScanFolderLimit; i++)
        {
            WriteRun("20260912-1200" + i.ToString("D2", CultureInfo.InvariantCulture) + "-cover", key: OtherKey);
        }

        Assert.Null(Find());
        Assert.NotNull(PackageIndex.FindReusable(
            _root, Key, DumpProfile.Full, PackageIndex.ScanFolderLimit + 1));
    }

    [Fact]
    public void TheScanReadsOnlyTheHeadOfAPackage()
    {
        // reuse_key is written near the top of a package for exactly this reason.
        WriteRun("20260912-120000-cover", padding: 16 * 1024);

        Assert.Null(Find());
    }

    [Fact]
    public void TheIndexIsPreferredToTheScan()
    {
        WriteRun("20260912-120000-cover", padding: 16 * 1024);
        PackageIndex.Append(_root, Row("20260912-120000-cover"));

        Assert.Equal("20260912-120000-cover", Find()!.Folder);
    }

    [Fact]
    public void AFileInTheRunRoot_IsNotARunFolder()
    {
        File.WriteAllText(Path.Combine(_root, "notes.txt"), "nothing here");

        Assert.Null(Find());
    }

    [Fact]
    public void PackageBytes_CountsThePackageAndItsMeshes()
    {
        // What a reuse would copy, so the cost is known before it is paid.
        string run = WriteRun("20260912-120000-cover");
        Directory.CreateDirectory(Path.Combine(run, "meshes"));
        File.WriteAllBytes(Path.Combine(run, "meshes", "bod0001.glb"), new byte[1024]);

        long bytes = PackageIndex.PackageBytes(run);

        Assert.True(bytes > 1024);
        Assert.Equal(0, PackageIndex.PackageBytes(Path.Combine(_root, "no-such-folder")));
    }

    private PackageIndexRow? Find() => PackageIndex.FindReusable(_root, Key, DumpProfile.Full);

    private static PackageIndexRow Row(
        string folder,
        string key = Key,
        string profile = "full",
        DateTimeOffset? writtenAt = null) =>
        new PackageIndexRow
        {
            ReuseKey = key,
            Folder = folder,
            WrittenAt = writtenAt ?? new DateTimeOffset(2026, 9, 12, 12, 0, 0, TimeSpan.Zero),
            Profile = profile,
            PackageBytes = 262144,
        };

    /// <summary>A run folder whose package head carries the key and the profile.</summary>
    private string WriteRun(string folder, string key = Key, string profile = "full", int padding = 0)
    {
        string directory = Path.Combine(_root, folder);
        Directory.CreateDirectory(directory);

        var head = new List<string>
        {
            "{",
            "  \"schema_version\": \"1.3.0\",",
            "  \"package_id\": \"11111111-2222-4333-8444-555555555555\",",
            "  \"created_at\": \"2026-09-12T12:00:00+00:00\",",
        };
        if (padding > 0)
        {
            head.Add("  \"design_name\": \"" + new string('x', padding) + "\",");
        }

        head.Add("  \"reuse_key\": \"" + key + "\",");
        head.Add("  \"extractor\": { \"name\": \"SwReview.Extractor\", \"profile\": \"" + profile + "\" },");
        head.Add("  \"gaps\": []");
        head.Add("}");

        File.WriteAllLines(Path.Combine(directory, PackageWriter.PackageFileName), head);
        return directory;
    }
}
