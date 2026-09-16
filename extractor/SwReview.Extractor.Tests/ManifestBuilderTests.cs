using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T089. The two schema 1.3.0 members the package-reuse key cannot do without:
/// <c>file_modified_utc</c> and <c>file_size_bytes</c>, read from
/// <see cref="FileInfo.LastWriteTimeUtc"/> and <see cref="FileInfo.Length"/>.
///
/// Before them the manifest held no modification time, no file size and no content hash:
/// <c>document_id</c> is a SHA-1 of the lowercased normalized path, <c>vault_version</c> and
/// <c>revision</c> are null unless a vault writes them back, and <c>local_modified</c> is
/// hardcoded null with an <c>unsupported</c> gap on every document of every dump. A reuse key
/// over that reduces to "the same files, in the same configurations", which says nothing about
/// whether any of them changed (data-model.md 9.1).
///
/// Both members are <b>nullable with a gap</b>, never 0 and never "now": a path this process
/// cannot stat - deleted under us, on a disconnected share, a name the filesystem rejects - is
/// an unknown, and an unknown refuses reuse rather than matching (constitution Principle I).
/// </summary>
public sealed class ManifestBuilderTests : IDisposable
{
    private readonly string _root;

    public ManifestBuilderTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "SwReview.Manifest.Tests", Guid.NewGuid().ToString("N"));
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

    [Fact]
    public void ASavedFile_RecordsItsModificationTimeAndItsSize()
    {
        string path = WriteFile("cover.sldprt", 2048);
        var scope = NewScope();

        ManifestEntry entry = Build(scope, path);

        Assert.Equal(2048, entry.FileSizeBytes);
        Assert.Equal(
            Truncate(File.GetLastWriteTimeUtc(path)),
            entry.FileModifiedUtc!.Value.UtcDateTime);
        Assert.Equal(TimeSpan.Zero, entry.FileModifiedUtc!.Value.Offset);
    }

    [Fact]
    public void TheModificationTime_IsTruncatedToTheMicrosecondThePackageCanCarry()
    {
        // A .NET tick is 100 ns and an ISO 8601 timestamp in the IR carries microseconds, so
        // a value with tick precision would be written one way and read back another - and
        // the key hashes what was read back. Truncating here keeps the two the same number.
        string path = WriteFile("cover.sldprt", 16);
        File.SetLastWriteTimeUtc(path, new DateTime(2026, 9, 10, 8, 30, 0, DateTimeKind.Utc).AddTicks(1237));

        ManifestEntry entry = Build(NewScope(), path);

        Assert.Equal(0, entry.FileModifiedUtc!.Value.UtcDateTime.Ticks % 10);
        Assert.Equal(
            new DateTime(2026, 9, 10, 8, 30, 0, DateTimeKind.Utc).AddTicks(1230),
            entry.FileModifiedUtc!.Value.UtcDateTime);
    }

    [Fact]
    public void AnEmptyFile_IsASizeAndNotAnUnknown()
    {
        string path = WriteFile("empty.sldprt", 0);

        ManifestEntry entry = Build(NewScope(), path);

        Assert.Equal(0, entry.FileSizeBytes);
        Assert.NotNull(entry.FileModifiedUtc);
    }

    [Fact]
    public void AMissingFile_LeavesBothMembersNullAndRecordsAGap()
    {
        var scope = NewScope();

        ManifestEntry entry = Build(scope, Path.Combine(_root, "never-written.sldprt"));

        Assert.Null(entry.FileModifiedUtc);
        Assert.Null(entry.FileSizeBytes);
        Assert.Contains(
            scope.Gaps.Gaps,
            gap => gap.EntityKind == "manifest"
                && gap.EntityId == "doc:1"
                && gap.Reason.IndexOf("modification time", StringComparison.Ordinal) >= 0);
    }

    [Fact]
    public void APathTheFilesystemRejects_IsAnUnknownAndNotAnException()
    {
        var scope = NewScope();

        ManifestEntry entry = Build(scope, "\0:/not a path");

        Assert.Null(entry.FileModifiedUtc);
        Assert.Null(entry.FileSizeBytes);
        Assert.Contains(scope.Gaps.Gaps, gap => gap.EntityKind == "manifest" && gap.Error != null);
    }

    [Fact]
    public void ADocumentWithNoPath_IsAnUnknownAndNotAnException()
    {
        // A never-saved document has no path at all. PackageWriter refuses the dump before
        // this point, but the builder is not the place to learn that the hard way.
        var scope = NewScope();

        ManifestEntry entry = Build(scope, string.Empty);

        Assert.Null(entry.FileModifiedUtc);
        Assert.Null(entry.FileSizeBytes);
    }

    [Fact]
    public void TheStatGoesThroughTheGate()
    {
        // Every read the dump makes is named at the door, so an audit of what a dump touched
        // is the gate's record and not a second list somebody has to remember to update.
        string path = WriteFile("cover.sldprt", 8);
        var observer = new RecordingGateObserver();
        var gate = new SwGate { Observer = observer };

        Build(NewScope(), path, gate);

        Assert.Contains(ManifestBuilder.FileStatMember, observer.Members);
    }

    [Fact]
    public void AMissingFile_DoesNotCountAgainstTheCircuitBreaker()
    {
        // The breaker exists to stop a dump when SOLIDWORKS has stopped answering. A file
        // that is not there is an answer, so it must not push the breaker towards opening.
        var gate = new SwGate();
        var scope = NewScope();

        for (int i = 0; i < 20; i++)
        {
            Build(scope, Path.Combine(_root, "never-written.sldprt"), gate);
        }

        Assert.False(gate.Breaker.IsOpen);
    }

    private static DateTime Truncate(DateTime value) =>
        new DateTime(value.Ticks - (value.Ticks % 10), value.Kind);

    private string WriteFile(string name, int bytes)
    {
        string path = Path.Combine(_root, name);
        File.WriteAllBytes(path, new byte[bytes]);
        return path;
    }

    private static DumpScope NewScope() =>
        new DumpScope(new GapCollector(), new DumpOptions(), new ComponentTreeResult());

    private static ManifestEntry Build(DumpScope scope, string documentPath, SwGate? gate = null)
    {
        var document = new Document
        {
            DocumentId = "doc:1",
            FileName = "cover.sldprt",
            Path = documentPath,
            ActiveConfiguration = "Default",
        };

        Manifest manifest = new ManifestBuilder(gate).Build(scope, new List<Document> { document });

        return manifest.Entries.Single();
    }
}
