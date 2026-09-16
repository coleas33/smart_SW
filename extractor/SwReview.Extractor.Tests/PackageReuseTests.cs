using System;
using System.IO;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T091. The reuse path: copy an earlier run's <c>package.json</c> and <c>meshes/</c> into this
/// run's folder instead of dumping.
///
/// <b>The reused package still gets its own run folder</b> (VERIFIED: <c>chat/server.py</c>
/// claims a run folder per chat and refuses a second, and <c>session.json</c>,
/// <c>events.jsonl</c> and <c>report.md</c> are written into it), so what is asserted here is a
/// copy into a new directory and never a pointer at the old one.
///
/// The three guards of data-model.md 9.5, one group of tests each: reuse is <b>stated</b>, with
/// the provenance on the package and a sentence naming the folder and its age; reuse <b>never
/// crosses a refusal</b>, asked of the live document and of the candidate on disk; and the
/// <b>key is recomputed</b> from what is on screen now rather than trusted from the file.
/// </summary>
public sealed class PackageReuseTests : IDisposable
{
    private static readonly DateTimeOffset Now = new DateTimeOffset(2026, 9, 12, 15, 0, 0, TimeSpan.Zero);

    private readonly string _root;
    private readonly string _out;

    public PackageReuseTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.PackageReuse.Tests", Guid.NewGuid().ToString("N"));
        _out = Path.Combine(_root, "20260912-150000-cover-assy");
        Directory.CreateDirectory(_out);
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

    // --- the copy ----------------------------------------------------------------------

    [Fact]
    public void AMatchingRun_IsCopiedIntoThisRunsOwnFolder()
    {
        WriteSource("20260912-120000-cover-assy");

        ReuseOutcome outcome = Reuse();

        Assert.NotNull(outcome.Result);
        Assert.Equal(Path.Combine(_out, PackageWriter.PackageFileName), outcome.Result!.PackageFilePath);
        Assert.True(File.Exists(Path.Combine(_out, PackageWriter.PackageFileName)));
        Assert.True(File.Exists(Path.Combine(_out, PackageWriter.MeshDirectoryName, "bod0001.glb")));
    }

    [Fact]
    public void TheCopiedPackage_SaysWhereItCameFromAndWhen()
    {
        WriteSource("20260912-120000-cover-assy");

        ReuseOutcome outcome = Reuse();

        EvidencePackage written = PackageSerializer.Deserialize(
            File.ReadAllText(Path.Combine(_out, PackageWriter.PackageFileName)));

        Assert.Equal("20260912-120000-cover-assy", written.ReusedFrom);
        Assert.Equal(Now, written.ReusedAt);
        Assert.Equal(outcome.Result!.Package.ReuseKey, written.ReuseKey);
    }

    [Fact]
    public void TheCopiedPackage_IsTheSourcePackageApartFromItsProvenance()
    {
        // The gate lever 9 is adopted on is byte-identity with a fresh dump modulo the
        // identifiers and the reuse members. Nothing else may be rewritten on the way through.
        string source = WriteSource("20260912-120000-cover-assy");
        string before = File.ReadAllText(Path.Combine(source, PackageWriter.PackageFileName));

        Reuse();

        string after = File.ReadAllText(Path.Combine(_out, PackageWriter.PackageFileName));
        Assert.Equal(
            Strip(before),
            Strip(after));
        Assert.DoesNotContain("\"reused_from\": \"20260912-120000-cover-assy\"", before, StringComparison.Ordinal);
    }

    [Fact]
    public void TheCopiedPackage_SaysNoDumpPhaseRanInThisRun()
    {
        // Nothing was dumped here, so the timing rows say so. Carrying the original dump's
        // wall clock forward would have this package claim milliseconds nobody spent in it
        // (Principle I), and `extractor.phases` is the one member lever 9's own A/B harness
        // reads (T085a/T093).
        EvidencePackage timed = ReuseFixture.Dumped(Options());
        timed.Extractor.Phases.Add(
            new DumpPhase { Name = "document", ElapsedMs = 41, Status = DumpPhaseStatus.Ok });
        timed.Extractor.Phases.Add(
            new DumpPhase { Name = "body", ElapsedMs = 900, Status = DumpPhaseStatus.Ok });
        WriteSource("20260912-120000-cover-assy", timed);

        Reuse();

        EvidencePackage written = PackageSerializer.Deserialize(
            File.ReadAllText(Path.Combine(_out, PackageWriter.PackageFileName)));

        Assert.Equal(
            new[]
            {
                "document", "manifest", "mate", "feature", "equation", "hole", "fastener",
                "face", "body",
            },
            written.Extractor.Phases.Select(phase => phase.Name));
        Assert.All(written.Extractor.Phases, phase =>
        {
            Assert.Null(phase.ElapsedMs);
            Assert.Equal(DumpPhaseStatus.Skipped, phase.Status);
        });
    }

    [Fact]
    public void TheStatusLine_NamesTheFolderAndItsAge()
    {
        // "Reusing the extraction from <folder> (<age>)" instead of "Extracting evidence
        // from ...": reuse is stated, never silent.
        WriteSource("20260912-120000-cover-assy");

        ReuseOutcome outcome = Reuse();

        Assert.Equal(
            "Reusing the extraction from 20260912-120000-cover-assy (3 hours old).",
            outcome.Message);
    }

    [Theory]
    [InlineData(0, "under a minute old")]
    [InlineData(90, "1 minute old")]
    [InlineData(45 * 60, "45 minutes old")]
    [InlineData(3 * 60 * 60, "3 hours old")]
    [InlineData(50 * 60 * 60, "2 days old")]
    [InlineData(-60, "age unknown")]
    public void TheAge_IsTheCoarsestUnitThatIsStillTrue(int seconds, string expected)
    {
        Assert.Equal(expected, PackageReuse.Age(TimeSpan.FromSeconds(seconds)));
    }

    // --- reuse never crosses a refusal ---------------------------------------------------

    [Fact]
    public void UnsavedChanges_RefuseEvenWhenTheKeyMatches()
    {
        // A modification time does not move until the document is saved, so the key cannot
        // see an in-memory edit at all. Extraction is minutes; a wrong finding is hours.
        WriteSource("20260912-120000-cover-assy");

        ReuseOutcome outcome = Reuse(unsavedChanges: true);

        Assert.Null(outcome.Result);
        Assert.Equal(ReuseRefusals.UnsavedChanges, outcome.Refusals.Single().Code);
        Assert.StartsWith("Not reusing an earlier extraction:", outcome.Message);
    }

    [Fact]
    public void AnUnreadableSaveState_RefusesToo()
    {
        WriteSource("20260912-120000-cover-assy");

        ReuseOutcome outcome = Reuse(unsavedChanges: null);

        Assert.Null(outcome.Result);
        Assert.Equal(ReuseRefusals.SaveStateUnknown, outcome.Refusals.Single().Code);
    }

    [Fact]
    public void ANonResolvedComponentOnScreen_Refuses()
    {
        // MeshExporter skips a non-resolved component with a gap, so resolving one changes
        // what a review can see with no file change at all.
        WriteSource("20260912-120000-cover-assy");
        EvidencePackage probe = ReuseFixture.Package();
        probe.Components[1].Suppression = SuppressionState.Lightweight;

        ReuseOutcome outcome = PackageReuse.Reuse(probe, Options(), _root, false, Now);

        Assert.Null(outcome.Result);
        Assert.Equal(ReuseRefusals.UnresolvedComponent, outcome.Refusals.Single().Code);
    }

    [Fact]
    public void ACandidateThatWasAPartialDump_Refuses()
    {
        // PackageWriter.Build continues past a failed phase and writes the package either way,
        // with a phase-level tool_error gap and nothing saying "this dump aborted". The
        // candidate is read before it is copied precisely so that gap is seen.
        EvidencePackage partial = ReuseFixture.Dumped(Options());
        partial.Gaps.Add(new Gap
        {
            Kind = GapKind.ToolError,
            EntityKind = "hole",
            EntityId = null,
            Reason = "the hole phase failed",
            Error = "COMException",
        });
        WriteSource("20260912-120000-cover-assy", partial);

        ReuseOutcome outcome = Reuse();

        Assert.Null(outcome.Result);
        Assert.Equal(ReuseRefusals.AbortedDump, outcome.Refusals.Single().Code);
    }

    [Fact]
    public void APerEntityToolError_IsNotAPartialDump()
    {
        // A tool_error that names its entity is the ordinary unknown a review is built to
        // carry; only the phase-level one, with a null entity id, means the dump stopped.
        EvidencePackage package = ReuseFixture.Dumped(Options());
        package.Gaps.Add(new Gap
        {
            Kind = GapKind.ToolError,
            EntityKind = "hole",
            EntityId = "hol:0003",
            Reason = "one hole could not be read",
            Error = "COMException",
        });
        WriteSource("20260912-120000-cover-assy", package);

        Assert.NotNull(Reuse().Result);
    }

    [Fact]
    public void APackageWithNoRecordedFileStat_IsNeverReused()
    {
        // A package written before schema 1.3.0 has a key that cannot see a change at all.
        EvidencePackage probe = ReuseFixture.Package();
        probe.Manifest.Entries[0].FileModifiedUtc = null;
        probe.Manifest.Entries[0].FileSizeBytes = null;
        WriteSource("20260912-120000-cover-assy");

        ReuseOutcome outcome = PackageReuse.Reuse(probe, Options(), _root, false, Now);

        Assert.Null(outcome.Result);
        Assert.Equal(ReuseRefusals.UnknownFileStat, outcome.Refusals.Single().Code);
    }

    // --- the key is recomputed, and a miss is never an error --------------------------------

    [Fact]
    public void ASavedFile_MeansAFreshDump()
    {
        WriteSource("20260912-120000-cover-assy");
        EvidencePackage probe = ReuseFixture.Package();
        probe.Manifest.Entries[0].FileSizeBytes += 512;

        ReuseOutcome outcome = PackageReuse.Reuse(probe, Options(), _root, false, Now);

        Assert.Null(outcome.Result);
        Assert.Empty(outcome.Refusals);
        Assert.Contains("extracting", outcome.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void NothingToReuse_IsAMessageAndNotAFailure()
    {
        ReuseOutcome outcome = Reuse();

        Assert.Null(outcome.Result);
        Assert.NotEqual(string.Empty, outcome.Message);
    }

    [Fact]
    public void ACandidateThatCannotBeRead_IsAMiss()
    {
        string source = WriteSource("20260912-120000-cover-assy");
        File.WriteAllText(Path.Combine(source, PackageWriter.PackageFileName), "{ not json");

        ReuseOutcome outcome = Reuse();

        Assert.Null(outcome.Result);
        Assert.Contains("could not be read", outcome.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void TheStoredKeyIsOnlyEverUsedToFindCandidates_NeverToTrustOne()
    {
        // A file whose stored key says one thing and whose contents say another is exactly the
        // case this lever must not get wrong: the index is a finding aid, and the candidate is
        // judged on what it actually contains.
        EvidencePackage lying = ReuseFixture.Package();
        lying.Manifest.Entries[0].FileSizeBytes += 512;
        lying.ReuseKey = ReuseKey.Of(ReuseFixture.Package(), Options());
        WriteSource("20260912-120000-cover-assy", lying);

        ReuseOutcome outcome = Reuse();

        // Found by the key it claims, then judged on what it actually holds, and refused.
        Assert.Null(outcome.Result);
        Assert.Contains("is not the design on screen", outcome.Message, StringComparison.Ordinal);
    }

    private DumpOptions Options() => ReuseFixture.Options(options => options.OutputDirectory = _out);

    private ReuseOutcome Reuse(bool? unsavedChanges = false) =>
        PackageReuse.Reuse(ReuseFixture.Package(), Options(), _root, unsavedChanges, Now);

    /// <summary>A run folder holding a package and one mesh, plus its index row.</summary>
    private string WriteSource(string folder, EvidencePackage? package = null)
    {
        EvidencePackage source = package ?? ReuseFixture.Dumped(Options());
        string directory = Path.Combine(_root, folder);
        Directory.CreateDirectory(Path.Combine(directory, PackageWriter.MeshDirectoryName));
        File.WriteAllText(
            Path.Combine(directory, PackageWriter.PackageFileName),
            PackageSerializer.Serialize(source));
        File.WriteAllBytes(
            Path.Combine(directory, PackageWriter.MeshDirectoryName, "bod0001.glb"), new byte[64]);

        PackageIndex.Append(_root, new PackageIndexRow
        {
            ReuseKey = source.ReuseKey ?? string.Empty,
            Folder = folder,
            WrittenAt = Now - TimeSpan.FromHours(3),
            Profile = PackageSerializer.EnumToJsonName(DumpProfile.Full),
            PackageBytes = PackageIndex.PackageBytes(directory),
        });

        return directory;
    }

    /// <summary>
    /// The package text without the members a reuse is allowed to change: the provenance it
    /// stamps on, and <c>extractor.phases</c>, which a reused package rewrites to "no phase
    /// ran here" rather than repeating timings from a dump that happened in another run.
    /// Everything else still has to survive the copy byte for byte.
    /// </summary>
    private static string Strip(string json)
    {
        EvidencePackage package = PackageSerializer.Deserialize(json);
        package.ReusedFrom = null;
        package.ReusedAt = null;
        package.Extractor.Phases.Clear();
        return PackageSerializer.Serialize(package);
    }
}
