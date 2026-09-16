using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Rms;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T050. The working copy, and the attestation of the file it was taken from.
///
/// The re-modeler works on a copy it creates in the run folder and never saves over a file that
/// already existed. That is structural rather than conventional: the copy is a bytewise
/// <c>File.Copy(source, copy, overwrite: false)</c> made <b>before any SOLIDWORKS document
/// handle to the copy exists</b>, the copy is opened at its own path, and
/// <c>IModelDoc2.Save3</c> takes no filename (VERIFIED), so the only file the seat can write is
/// the one in the run folder. Nothing in stage 1 uses <c>SaveAs*</c> (research R2.1, R2.2).
///
/// The copy lives <b>only</b> in the run folder. Writing <c>&lt;name&gt;-RMS.SLDPRT</c> beside
/// the source is friendlier and much riskier: one bad path join writes into the engineer's
/// working directory, possibly into an EPDM vault (research R2.5).
///
/// The option integers are asserted as <b>integers</b>, not as the names the code writes, which
/// is the failure a name-only check misses when an enum value drifts under an upgrade.
/// </summary>
public class RemodelCopyTests : IDisposable
{
    private const string RunId = "20260916-142201-bracket-remodel";

    private readonly string _root;

    public RemodelCopyTests()
    {
        _root = Path.Combine(
            Path.GetTempPath(), "SwReview.RemodelCopy.Tests", Guid.NewGuid().ToString("N"));
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
            // A test that deliberately holds a handle open can lose the race with the
            // filesystem; the folder is under the OS temp directory either way.
        }
    }

    private string RunDirectory
    {
        get
        {
            string path = Path.Combine(_root, "runs", RunId);
            Directory.CreateDirectory(path);
            return path;
        }
    }

    /// <summary>A source part with recognisable bytes, in its own directory.</summary>
    private string WriteSource(string directoryName = "work", string fileName = "bracket.SLDPRT")
    {
        string directory = Path.Combine(_root, directoryName);
        Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, fileName);
        File.WriteAllText(path, "SLDPRT bytes for " + fileName, Encoding.UTF8);
        return path;
    }

    private static string Sha256Of(string path)
    {
        using (var sha = SHA256.Create())
        using (var stream = File.OpenRead(path))
        {
            byte[] digest = sha.ComputeHash(stream);
            var hex = new StringBuilder(digest.Length * 2);
            foreach (byte value in digest)
            {
                hex.Append(value.ToString("x2"));
            }

            return hex.ToString();
        }
    }

    // ------------------------------------------------------------ where the copy lives

    /// <summary>
    /// <c>&lt;run&gt;/copy/&lt;name&gt;-RMS.SLDPRT</c>, and nowhere else. The run folder's own
    /// name is <c>RunFolders</c>'; this helper owns only what sits inside it, so the two
    /// conventions each live in exactly one place.
    /// </summary>
    [Fact]
    public void TheCopyPathIsTheRunFoldersCopySubfolderAndTheRmsSuffixedPartName()
    {
        string source = WriteSource();

        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        Assert.Equal(Path.Combine(RunDirectory, "copy", "bracket-RMS.SLDPRT"), copy);
    }

    [Fact]
    public void TheCopyIsBytewiseAndLivesOnlyInTheRunFolderAndNeverBesideTheSource()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        RemodelCopy.CreateCopy(source, copy);

        Assert.True(File.Exists(copy), $"the copy was not created at {copy}");
        Assert.Equal(Sha256Of(source), Sha256Of(copy));
        Assert.Empty(Directory.GetFiles(Path.GetDirectoryName(source)!, "*-RMS.SLDPRT"));
        Assert.Single(Directory.GetFiles(Path.GetDirectoryName(source)!));
    }

    /// <summary>The <c>copy/</c> subfolder is created; the caller does not have to.</summary>
    [Fact]
    public void TheCopySubfolderIsCreatedWhenItIsNotThereYet()
    {
        string source = WriteSource();
        string run = RunDirectory;

        RemodelCopy.CreateCopy(source, RemodelCopy.CopyPathFor(run, source));

        Assert.True(Directory.Exists(Path.Combine(run, "copy")));
    }

    // -------------------------------------------------------- refusing to overwrite

    [Fact]
    public void AnExistingDestinationIsRefusedAndIsLeftExactlyAsItWas()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        Directory.CreateDirectory(Path.GetDirectoryName(copy)!);
        File.WriteAllText(copy, "an earlier artifact", Encoding.UTF8);

        var error = Assert.Throws<RemodelCopyError>(() => RemodelCopy.CreateCopy(source, copy));

        Assert.Equal("copy_exists", error.ErrorCode);
        Assert.Equal("an earlier artifact", File.ReadAllText(copy));
    }

    [Fact]
    public void AMissingSourceIsRefusedAndNothingIsWritten()
    {
        string source = Path.Combine(_root, "work", "absent.SLDPRT");
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        var error = Assert.Throws<RemodelCopyError>(() => RemodelCopy.CreateCopy(source, copy));

        Assert.Equal("copy_failed", error.ErrorCode);
        Assert.False(File.Exists(copy));
    }

    // ---------------------------------------------------- RK-9: the source is held open

    /// <summary>
    /// RK-9. SOLIDWORKS holds the engineer's open <c>.SLDPRT</c> with write access while sharing
    /// reads. The fallback is <c>new FileStream(source, Open, Read, FileShare.ReadWrite)</c>
    /// streamed into a destination opened <c>FileMode.CreateNew</c>, and this is it running
    /// against exactly that handle.
    ///
    /// It is exercised <b>directly</b> rather than by forcing <c>CreateCopy</c> down the
    /// fallback branch, because on Windows 11 <c>CopyFile</c> shares read <i>and</i> write, so
    /// no in-process share mode makes the primary route fail while leaving this one able to
    /// succeed: a handle that defeats <c>File.Copy</c> defeats the fallback's read too. Whether
    /// a real SOLIDWORKS handle defeats <c>File.Copy</c> at all is PROBE-13's question; this is
    /// the answer that is ready either way, and the test that proves the answer works.
    /// </summary>
    [Fact]
    public void TheSharedReadStreamFallbackCopiesASourceHeldOpenForWriting()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        using (new FileStream(source, FileMode.Open, FileAccess.ReadWrite, FileShare.Read))
        {
            RemodelCopy.CopyThroughSharedStream(source, copy);
        }

        Assert.Equal(Sha256Of(source), Sha256Of(copy));
    }

    /// <summary>
    /// RK-9's outcome, through the entry point the run actually calls: a source SOLIDWORKS holds
    /// open is copied byte-identically, by whichever of the two routes answers.
    /// </summary>
    [Fact]
    public void ASourceHeldOpenForWritingIsStillCopiedByteIdentically()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        using (new FileStream(source, FileMode.Open, FileAccess.ReadWrite, FileShare.Read))
        {
            RemodelCopy.CreateCopy(source, copy);
        }

        Assert.Equal(Sha256Of(source), Sha256Of(copy));
    }

    /// <summary>An unheld source takes the plain bytewise copy, not the fallback.</summary>
    [Fact]
    public void AnUnheldSourceTakesThePlainFileCopyRoute()
    {
        string source = WriteSource();

        RemodelCopyRoute route = RemodelCopy.CreateCopy(
            source, RemodelCopy.CopyPathFor(RunDirectory, source));

        Assert.Equal(RemodelCopyRoute.FileCopy, route);
    }

    /// <summary>
    /// The fallback refuses an existing destination for the same reason the primary route does:
    /// <c>FileMode.CreateNew</c>, never <c>Create</c>. Without this, the one route that is
    /// reached only in a failure is also the one that could silently overwrite.
    /// </summary>
    [Fact]
    public void TheFallbackAlsoRefusesToOverwriteAnExistingDestination()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        Directory.CreateDirectory(Path.GetDirectoryName(copy)!);
        File.WriteAllText(copy, "an earlier artifact", Encoding.UTF8);

        var error = Assert.Throws<RemodelCopyError>(() =>
            RemodelCopy.CopyThroughSharedStream(source, copy));

        Assert.Equal("copy_exists", error.ErrorCode);
        Assert.Equal("an earlier artifact", File.ReadAllText(copy));
    }

    /// <summary>
    /// The fallback creates <c>copy/</c> and leaves a writable file too, so it is not a
    /// half-built route: it writes bytes into a file it created rather than copying the
    /// source's attributes across, which is why a read-only source needs no extra step here.
    /// </summary>
    [Fact]
    public void TheFallbackCreatesTheCopySubfolderAndLeavesAWritableFile()
    {
        string source = WriteSource();
        File.SetAttributes(source, FileAttributes.ReadOnly);
        string run = RunDirectory;
        string copy = RemodelCopy.CopyPathFor(run, source);

        try
        {
            RemodelCopy.CopyThroughSharedStream(source, copy);
        }
        finally
        {
            File.SetAttributes(source, FileAttributes.Normal);
        }

        Assert.True(Directory.Exists(Path.Combine(run, "copy")));
        Assert.False(File.GetAttributes(copy).HasFlag(FileAttributes.ReadOnly));
    }

    // ------------------------------------------------------------- the attestation

    [Fact]
    public void TheAttestationRecordsThePathLengthLastWriteTimeAndHashOfTheSource()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        var recordedAt = new DateTime(2026, 9, 16, 14, 22, 1, DateTimeKind.Utc);

        SourceAttestation attestation = RemodelCopy.RecordSource(source, copy, recordedAt, null, null);

        Assert.Equal(source, attestation.Path);
        Assert.Equal(new FileInfo(source).Length, attestation.LengthBytes);
        Assert.Equal(File.GetLastWriteTimeUtc(source), attestation.LastWriteUtc);
        Assert.Equal(Sha256Of(source), attestation.Sha256);
        Assert.Equal(recordedAt, attestation.RecordedAt);
        Assert.Equal(copy, attestation.CopyPath);
    }

    /// <summary>
    /// The attestation's <c>source_design_id</c> is the <b>source</b> path's id, which is what
    /// the exceptions carry-forward matches on. This run's packages are dumps of the copy,
    /// whose path is unique to the run, so matching on those would select no candidate, ever
    /// (contracts/run-artifacts.md, "Exceptions carry-forward").
    /// </summary>
    [Fact]
    public void TheAttestationCarriesTheSourceDesignIdAndNotTheCopys()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        SourceAttestation attestation = RemodelCopy.RecordSource(
            source, copy, DateTime.UtcNow, null, null);

        Assert.Equal(DocumentIds.DesignId(source), attestation.SourceDesignId);
        Assert.NotEqual(DocumentIds.DesignId(copy), attestation.SourceDesignId);
    }

    /// <summary>
    /// Reading the attestation never opens the source for writing: its last-write time is the
    /// value that is re-checked at report time, and a difference there is a hard failure of the
    /// run, so recording it must not be what changes it.
    /// </summary>
    [Fact]
    public void RecordingTheAttestationAndTakingTheCopyLeaveTheSourceUntouched()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        DateTime before = File.GetLastWriteTimeUtc(source);
        long length = new FileInfo(source).Length;
        string hash = Sha256Of(source);

        RemodelCopy.RecordSource(source, copy, DateTime.UtcNow, null, null);
        RemodelCopy.CreateCopy(source, copy);

        Assert.Equal(before, File.GetLastWriteTimeUtc(source));
        Assert.Equal(length, new FileInfo(source).Length);
        Assert.Equal(hash, Sha256Of(source));
    }

    /// <summary>
    /// OQ-11. An EPDM vault part is <b>copied out</b> into the run folder and is never refused
    /// for vault reasons; the vault path and the revision are recorded beside the rest of the
    /// attestation. A checked-in, read-only vault file is a legitimate source because nothing
    /// in the run opens it for writing.
    /// </summary>
    [Fact]
    public void AVaultSourceIsCopiedOutAndItsVaultPathAndRevisionAreRecorded()
    {
        string source = WriteSource(Path.Combine("Vault", "Designs"), "vaulted.SLDPRT");
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        SourceAttestation attestation = RemodelCopy.RecordSource(
            source, copy, DateTime.UtcNow, @"\\vault\Designs\vaulted.SLDPRT", "B");
        RemodelCopy.CreateCopy(source, copy);

        Assert.Equal(@"\\vault\Designs\vaulted.SLDPRT", attestation.VaultPath);
        Assert.Equal("B", attestation.VaultRevision);
        Assert.True(File.Exists(copy), "a vault source was not copied out into the run folder");
        Assert.Equal(Sha256Of(source), Sha256Of(copy));
    }

    /// <summary>
    /// A read-only source is a legitimate source, and the copy is writable: the engineer's file
    /// keeps its attributes and the run's copy is the one the seat writes.
    /// </summary>
    [Fact]
    public void AReadOnlySourceIsCopiedAndTheCopyIsWritable()
    {
        string source = WriteSource();
        File.SetAttributes(source, FileAttributes.ReadOnly);
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);

        try
        {
            RemodelCopy.CreateCopy(source, copy);
        }
        finally
        {
            File.SetAttributes(source, FileAttributes.Normal);
        }

        Assert.False(File.GetAttributes(copy).HasFlag(FileAttributes.ReadOnly),
            "the copy inherited the source's read-only attribute and the seat could not save it");
    }

    /// <summary>
    /// Unknown stays unknown. A source that is not in a vault records <c>null</c> for both
    /// vault fields and never an empty string, because the report distinguishes "not in a
    /// vault" from "in a vault whose revision could not be read".
    /// </summary>
    [Fact]
    public void ASourceThatIsNotInAVaultRecordsNullForBothVaultFields()
    {
        string source = WriteSource();

        SourceAttestation attestation = RemodelCopy.RecordSource(
            source, RemodelCopy.CopyPathFor(RunDirectory, source), DateTime.UtcNow, null, null);

        Assert.Null(attestation.VaultPath);
        Assert.Null(attestation.VaultRevision);
    }

    /// <summary>
    /// The attestation crosses the bridge as JSON, and the names on the wire are the whole
    /// agreement: <c>remodel/attestation.py</c>'s <c>RECORDED_FIELDS</c> is exhaustive in
    /// both directions - it refuses a <c>source_attestation</c> block missing one of these
    /// nine keys, and refuses one that carries a key it does not know - so a PascalCase
    /// block is nine missing fields and nine unexpected ones at once, on every run.
    ///
    /// Nothing renames these properties for us: <see cref="PackageSerializer"/> sets
    /// <c>PropertyNamingPolicy = null</c> on purpose, so every name in the contract is
    /// spelled by a <c>JsonPropertyName</c> attribute or it is not spelled at all, and
    /// <see cref="BridgeCodec"/> inherits those options unchanged.
    ///
    /// The order is asserted too, because it is free: data-model.md section 5 lists the
    /// recorded half in this order and <c>RECORDED_FIELDS</c> repeats it, so a property
    /// inserted in the middle of the C# type shows up here rather than in a review.
    /// </summary>
    [Fact]
    public void TheAttestationSerializesTheSnakeCaseNamesThePythonReaderRequires()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        SourceAttestation attestation = RemodelCopy.RecordSource(
            source, copy, new DateTime(2026, 9, 16, 14, 22, 1, DateTimeKind.Utc), null, null);

        using (JsonDocument written = JsonDocument.Parse(
            JsonSerializer.Serialize(attestation, BridgeCodec.Options)))
        {
            Assert.Equal(
                new[]
                {
                    "path",
                    "length_bytes",
                    "last_write_utc",
                    "sha256",
                    "source_design_id",
                    "recorded_at",
                    "copy_path",
                    "vault_path",
                    "vault_revision",
                },
                written.RootElement.EnumerateObject().Select(member => member.Name).ToArray());

            // Unknown stays unknown across the wire: a source that is not in a vault sends
            // null for both, and the reader distinguishes that from an empty string.
            Assert.Equal(JsonValueKind.Null, written.RootElement.GetProperty("vault_path").ValueKind);
            Assert.Equal(
                JsonValueKind.Null, written.RootElement.GetProperty("vault_revision").ValueKind);

            // Both timestamps name a time zone. The reader refuses one that does not - the
            // attestation records UTC - and DateTimeKind.Utc is what puts the Z there.
            Assert.EndsWith(
                "Z",
                written.RootElement.GetProperty("recorded_at").GetString(),
                StringComparison.Ordinal);
            Assert.EndsWith(
                "Z",
                written.RootElement.GetProperty("last_write_utc").GetString(),
                StringComparison.Ordinal);
        }
    }

    // --------------------------------------------------- option composition, as integers

    /// <summary>
    /// <c>swOpenDocOptions_Silent(1) | swOpenDocOptions_LoadModel(16) = 17</c>, and never
    /// <c>ReadOnly(2)</c> or <c>ViewOnly(4)</c>: a copy opened read-only or view-only cannot be
    /// changed, and the run would report a success it never made.
    /// </summary>
    [Fact]
    public void TheOpenOptionsComposeToSeventeenAndNeverCarryReadOnlyOrViewOnly()
    {
        Assert.Equal(17, RemodelCopy.OpenOptions);
        Assert.Equal(0, RemodelCopy.OpenOptions & 2);
        Assert.Equal(0, RemodelCopy.OpenOptions & 4);
    }

    /// <summary>
    /// <c>swSaveAsOptions_Silent = 1</c> and nothing else. <c>Copy(2)</c> would leave the
    /// document pointing at the old path, <c>SaveReferenced(4)</c> would walk out of the run
    /// folder, and <c>AvoidRebuildOnSave(8)</c> would save a tree the gate never measured.
    /// </summary>
    [Fact]
    public void TheSaveOptionsComposeToOneAndNeverCarryCopySaveReferencedOrAvoidRebuild()
    {
        Assert.Equal(1, RemodelCopy.SaveOptions);
        Assert.Equal(0, RemodelCopy.SaveOptions & 2);
        Assert.Equal(0, RemodelCopy.SaveOptions & 4);
        Assert.Equal(0, RemodelCopy.SaveOptions & 8);
    }

    /// <summary>
    /// <c>Add3(name, swCustomInfoText = 30, value, swCustomPropertyReplaceValue = 2)</c>, both
    /// asserted as the integers the code composes.
    /// </summary>
    [Fact]
    public void TheSessionTagIsWrittenAsTextWithTheReplaceValueOption()
    {
        Assert.Equal(30, RemodelCopy.SessionTagType);
        Assert.Equal(2, RemodelCopy.SessionTagOverwrite);
        Assert.Equal("SwReviewRemodelRun", RemodelCopy.SessionTagName);
    }

    // -------------------------------------------------- the tag, written and read back

    /// <summary>
    /// The two writes and the one read the tag needs, and nothing else, so the round trip is
    /// testable without a SOLIDWORKS seat.
    /// </summary>
    private sealed class CopyTargetFake : IRemodelCopyTarget
    {
        public string? PathName { get; set; }

        public string? StoredTag { get; set; }

        /// <summary>What <c>Add3</c> answered. PROBE-6 saw it answer -1 and add nothing.</summary>
        public int AddResult { get; set; }

        public string? WrittenName { get; private set; }

        public int WrittenType { get; private set; }

        public string? WrittenValue { get; private set; }

        public int WrittenOverwrite { get; private set; }

        /// <summary>When false, <c>Add3</c> answers but the property does not change.</summary>
        public bool WritesLand { get; set; } = true;

        public int WriteSessionTag(string fieldName, int fieldType, string fieldValue, int overwriteExisting)
        {
            WrittenName = fieldName;
            WrittenType = fieldType;
            WrittenValue = fieldValue;
            WrittenOverwrite = overwriteExisting;
            if (WritesLand)
            {
                StoredTag = fieldValue;
            }

            return AddResult;
        }

        /// <summary>The field name <c>Delete2</c> was handed, null until it is called.</summary>
        public string? RemovedName { get; private set; }

        public int RemoveSessionTag(string fieldName)
        {
            RemovedName = fieldName;
            StoredTag = null;
            return 0;
        }

        public string? GetPathName() => PathName;

        public string? GetSessionTag(string fieldName) =>
            fieldName == RemodelCopy.SessionTagName ? StoredTag : null;

        public IntPtr GetDocumentIdentity() => new IntPtr(0x4001);

        public IntPtr GetOpenDocumentIdentity(string documentPath) => new IntPtr(0x4001);
    }

    [Fact]
    public void TheSessionTagIsWrittenWithTheRunIdAndReadBack()
    {
        var target = new CopyTargetFake();

        int result = RemodelCopy.Tag(target, RunId);

        Assert.Equal(RemodelCopy.SessionTagName, target.WrittenName);
        Assert.Equal(RemodelCopy.SessionTagType, target.WrittenType);
        Assert.Equal(RunId, target.WrittenValue);
        Assert.Equal(RemodelCopy.SessionTagOverwrite, target.WrittenOverwrite);
        Assert.Equal(0, result);
        Assert.Equal(RunId, target.StoredTag);
    }

    /// <summary>
    /// The other half of the tag, so the allowlist's <c>ICustomPropertyManager.Delete2</c>
    /// entry has a call path rather than being the accidental widening the allowlist exists to
    /// prevent. It names the same property <see cref="RemodelCopy.Tag"/> wrote, spelled once.
    /// </summary>
    [Fact]
    public void TheSessionTagIsRemovedByName()
    {
        var target = new CopyTargetFake { StoredTag = RunId };

        Assert.Equal(0, RemodelCopy.Untag(target));
        Assert.Equal(RemodelCopy.SessionTagName, target.RemovedName);
        Assert.Null(target.StoredTag);
    }

    /// <summary>
    /// The read-back is the proof, not the return code. PROBE-6 observed <c>Add3</c> returning
    /// -1 and adding nothing, silently, so a tag judged by its return value would pass while
    /// <c>VerifyTarget</c>'s check 2 failed on the first write.
    /// </summary>
    [Fact]
    public void ATagThatDidNotLandIsRefusedEvenWhenAdd3AnsweredSuccessfully()
    {
        var target = new CopyTargetFake { WritesLand = false, AddResult = 0 };

        var error = Assert.Throws<RemodelCopyError>(() => RemodelCopy.Tag(target, RunId));

        Assert.Equal("tag_failed", error.ErrorCode);
    }

    /// <summary>A tag that read back as another run's id is refused, not overwritten.</summary>
    [Fact]
    public void ATagThatReadBackAsAnotherRunsIdIsRefused()
    {
        var target = new CopyTargetFake { WritesLand = false, StoredTag = "20260101-000000-other-remodel" };

        var error = Assert.Throws<RemodelCopyError>(() => RemodelCopy.Tag(target, RunId));

        Assert.Equal("tag_failed", error.ErrorCode);
    }

    /// <summary>
    /// A non-zero <c>Add3</c> answer is handed back rather than swallowed, because
    /// `remodel.log` records what the seat actually did; it is not what the tag is judged on.
    /// </summary>
    [Fact]
    public void TheAdd3AnswerIsHandedBackForTheLogWhenTheTagDidLand()
    {
        var target = new CopyTargetFake { AddResult = -1 };

        int result = RemodelCopy.Tag(target, RunId);

        Assert.Equal(-1, result);
    }

    // ------------------------------------------- the document is open at the copy's path

    [Fact]
    public void AfterOpenTheDocumentReportsTheCopyPathAndNotTheSourcePath()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        var target = new CopyTargetFake { PathName = copy };

        RemodelCopy.AssertOpenedAtCopy(target, copy, source);

        Assert.NotEqual(source, target.PathName);
    }

    [Fact]
    public void ADocumentThatOpenedAtTheSourcePathIsRefused()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        var target = new CopyTargetFake { PathName = source };

        var error = Assert.Throws<RemodelCopyError>(() =>
            RemodelCopy.AssertOpenedAtCopy(target, copy, source));

        Assert.Equal("open_failed", error.ErrorCode);
        Assert.Contains(source, error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ADocumentThatReportsNoPathAtAllIsRefused()
    {
        string source = WriteSource();
        string copy = RemodelCopy.CopyPathFor(RunDirectory, source);
        var target = new CopyTargetFake { PathName = null };

        var error = Assert.Throws<RemodelCopyError>(() =>
            RemodelCopy.AssertOpenedAtCopy(target, copy, source));

        Assert.Equal("open_failed", error.ErrorCode);
    }
}
