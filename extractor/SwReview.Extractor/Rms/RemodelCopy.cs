using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;

namespace SwReview.Extractor.Rms;

/// <summary>Which route <see cref="RemodelCopy.CreateCopy"/> took, for the run log.</summary>
public enum RemodelCopyRoute
{
    /// <summary><c>File.Copy(source, copy, overwrite: false)</c>.</summary>
    FileCopy,

    /// <summary>
    /// RK-9's fallback: <c>FileShare.ReadWrite</c> over a source SOLIDWORKS holds open,
    /// streamed into a destination opened <c>FileMode.CreateNew</c>.
    /// </summary>
    SharedReadStream,
}

/// <summary>
/// A refusal from the copy sequence, carrying the stable token
/// contracts/bridge-remodel.md's error table maps to a Python class.
/// </summary>
[Serializable]
public class RemodelCopyError : RemodelCommandError
{
    public RemodelCopyError(string errorCode, string message)
        : base(errorCode, message)
    {
    }
}

/// <summary>
/// What the copy sequence needs from the opened copy: three reads that
/// <see cref="IRemodelTarget"/> already declares, plus the one write that tags it.
///
/// The tag is written <b>before</b> a <see cref="RemodelScope"/> can exist, because the tag is
/// one of <see cref="RemodelScope.VerifyTarget"/>'s four checks and a scope that verified before
/// it was written would refuse its own first write. That is why this member lives here and not
/// on the scope.
///
/// <c>ICustomPropertyManager.Add3(FieldName, FieldType, FieldValue, OverwriteExisting)</c>
/// (VERIFIED), returning <c>Add3</c>'s answer unchanged.
/// </summary>
public interface IRemodelCopyTarget : IRemodelTarget
{
    /// <summary><c>Extension.CustomPropertyManager("").Add3(...)</c>, answer unchanged.</summary>
    int WriteSessionTag(string fieldName, int fieldType, string fieldValue, int overwriteExisting);

    /// <summary>
    /// <c>Extension.CustomPropertyManager("").Delete2(FieldName)</c> (VERIFIED), answer
    /// unchanged. The other half of the tag: <c>remodel.close</c> removes it once the run has
    /// no more writes to verify.
    /// </summary>
    int RemoveSessionTag(string fieldName);
}

/// <summary>
/// The source attestation, recorded at copy time and re-checked at report time
/// (data-model.md section 5). A difference is a <b>hard failure of the run</b>, however well the
/// copy came out: it means something wrote to the engineer's file during the run, and the run
/// can no longer claim it did not.
///
/// The record is handed back rather than written here: `remodel.open` returns it as
/// <c>source_attestation</c> and the Python runner writes <c>source-attestation.json</c>, so
/// the artifact has one writer and one schema owner.
/// </summary>
public sealed class SourceAttestation
{
    public SourceAttestation(
        string path,
        long lengthBytes,
        DateTime lastWriteUtc,
        string sha256,
        string sourceDesignId,
        DateTime recordedAt,
        string copyPath,
        string? vaultPath,
        string? vaultRevision)
    {
        Path = path;
        LengthBytes = lengthBytes;
        LastWriteUtc = lastWriteUtc;
        Sha256 = sha256;
        SourceDesignId = sourceDesignId;
        RecordedAt = recordedAt;
        CopyPath = copyPath;
        VaultPath = vaultPath;
        VaultRevision = vaultRevision;
    }

    /// <summary>The engineer's file. Never opened for writing, saved, renamed or deleted.</summary>
    public string Path { get; }

    public long LengthBytes { get; }

    public DateTime LastWriteUtc { get; }

    public string Sha256 { get; }

    /// <summary>
    /// <c>DocumentIds.DesignId</c> of the <b>source</b> path. This is what the exceptions
    /// carry-forward matches on: this run's packages are dumps of the copy, whose path is unique
    /// to the run, so matching on those would select no candidate, ever
    /// (contracts/run-artifacts.md, "Exceptions carry-forward").
    /// </summary>
    public string SourceDesignId { get; }

    /// <summary>Before the copy is made.</summary>
    public DateTime RecordedAt { get; }

    public string CopyPath { get; }

    /// <summary>
    /// The EPDM vault path and revision, or null when the source is not in a vault. Null, never
    /// an empty string: "not in a vault" and "in a vault whose revision could not be read" are
    /// different answers and the report says which.
    /// </summary>
    public string? VaultPath { get; }

    /// <inheritdoc cref="VaultPath" />
    public string? VaultRevision { get; }
}

/// <summary>
/// T051. The working copy: where it lives, how it is made, the options the seat is handed, and
/// the attestation of the file it was taken from.
///
/// <b>The copy is made before any SOLIDWORKS document handle to it exists</b>, by a bytewise
/// <c>File.Copy(source, copy, overwrite: false)</c>, and is then opened at its own path.
/// <c>IModelDoc2.Save3</c> takes no filename (VERIFIED), so the only file the seat can write is
/// the one in the run folder: the source is unreachable rather than merely un-targeted. Nothing
/// in stage 1 uses <c>SaveAs*</c> - research R2.2 records why, in one line per route:
/// <c>SaveAs3</c> without <c>Copy</c> retargets the open document in place, and with
/// <c>swSaveAsOptions_Copy</c> it opened a modal Save As dialog <i>after</i> writing the file,
/// and a modal on the add-in's STA thread is a hang rather than an error.
///
/// The copy lives <b>only</b> in the run folder (OQ-10). Writing <c>&lt;name&gt;-RMS.SLDPRT</c>
/// beside the source is friendlier and much riskier: one bad path join writes into the
/// engineer's working directory, possibly into an EPDM vault. An EPDM source is copied
/// <b>out</b> and is never refused for vault reasons (OQ-11); nothing here reads the path
/// looking for a vault, which is what makes that structural rather than a promise.
/// </summary>
public static class RemodelCopy
{
    /// <summary>The subfolder of the run folder the copy lives in, and nowhere else.</summary>
    public const string CopyFolderName = "copy";

    /// <summary>What marks the copy's file name.</summary>
    public const string CopySuffix = "-RMS";

    /// <summary>Parts only, in stage 1 and in v1.</summary>
    public const string PartExtension = ".SLDPRT";

    /// <summary>
    /// The custom property the copy is tagged with, and <see cref="RemodelScope.VerifyTarget"/>'s
    /// check 2. One spelling: the writer is here and the reader is the scope.
    /// </summary>
    public const string SessionTagName = "SwReviewRemodelRun";

    /// <summary><c>swCustomInfoType_e.swCustomInfoText</c> (VERIFIED value 30).</summary>
    public const int SessionTagType = (int)swCustomInfoType_e.swCustomInfoText;

    /// <summary>
    /// <c>swCustomPropertyAddOption_e.swCustomPropertyReplaceValue</c> (VERIFIED value 2): a
    /// re-run over a recovered copy replaces the tag rather than refusing to write it.
    /// </summary>
    public const int SessionTagOverwrite = (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue;

    /// <summary>
    /// <c>swOpenDocOptions_Silent(1) | swOpenDocOptions_LoadModel(16) = 17</c>, and never
    /// <c>ReadOnly(2)</c> or <c>ViewOnly(4)</c>: a copy opened either way cannot be changed and
    /// the run would report a success it never made. The integer, not the name, is what the
    /// tests assert (contracts/guard-allowlist.md, "Option composition").
    /// </summary>
    public const int OpenOptions =
        (int)swOpenDocOptions_e.swOpenDocOptions_Silent
        | (int)swOpenDocOptions_e.swOpenDocOptions_LoadModel;

    /// <summary>
    /// <c>swSaveAsOptions_Silent = 1</c> and nothing else. <c>Copy(2)</c> leaves the document
    /// pointing at the old path, <c>SaveReferenced(4)</c> walks out of the run folder, and
    /// <c>AvoidRebuildOnSave(8)</c> saves a tree the geometry gate never measured.
    /// </summary>
    public const int SaveOptions = (int)swSaveAsOptions_e.swSaveAsOptions_Silent;

    /// <summary>
    /// <c>swFileSaveWarning_e.swFileSaveWarning_RebuildError</c> (VERIFIED value 1). A save
    /// that reports it is a failed run <b>with a saved artifact</b>, and the report says so
    /// rather than reporting success.
    /// </summary>
    public const int SaveWarningRebuildError =
        (int)swFileSaveWarning_e.swFileSaveWarning_RebuildError;

    /// <summary>
    /// <c>&lt;run&gt;/copy/&lt;name&gt;-RMS.SLDPRT</c>. The run folder's own name is
    /// <c>RunFolders</c>'; this decides only what sits inside it, so each convention lives in
    /// exactly one place.
    /// </summary>
    public static string CopyPathFor(string runDirectory, string sourcePath)
    {
        if (string.IsNullOrWhiteSpace(runDirectory))
        {
            throw new ArgumentException("A run folder is required.", nameof(runDirectory));
        }

        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            throw new ArgumentException("A source path is required.", nameof(sourcePath));
        }

        string name = Path.GetFileNameWithoutExtension(sourcePath.Trim());
        if (string.IsNullOrEmpty(name))
        {
            throw new ArgumentException(
                $"'{sourcePath}' has no file name to build a copy name from.", nameof(sourcePath));
        }

        return Path.Combine(runDirectory, CopyFolderName, name + CopySuffix + PartExtension);
    }

    /// <summary>
    /// The run folder a copy path sits in: <c>&lt;run&gt;/copy/&lt;name&gt;-RMS.SLDPRT</c> has
    /// the run folder two levels up. It is derived rather than passed so that the convention
    /// <see cref="CopyPathFor"/> writes and the one <c>remodel.open</c> reads are the same
    /// statement, in one place.
    ///
    /// A path that is not inside a <c>copy</c> folder is refused as a save target would be,
    /// with the same <see cref="MutatingCallError"/>, because it is the same decision: this
    /// path is not somewhere the re-modeler may write.
    /// </summary>
    public static string RunDirectoryOf(string copyPath)
    {
        string copy = Canonical(Required(copyPath, nameof(copyPath)), "copy_failed");
        string? folder = Path.GetDirectoryName(copy);

        if (folder == null
            || !string.Equals(
                Path.GetFileName(folder), CopyFolderName, StringComparison.OrdinalIgnoreCase))
        {
            throw new MutatingCallError(
                "Save3",
                $"'{copyPath}' is not inside a run folder's '{CopyFolderName}' subfolder. The "
                + "copy lives only in the run folder, never beside the engineer's file.");
        }

        string? run = Path.GetDirectoryName(folder);
        if (string.IsNullOrEmpty(run))
        {
            throw new MutatingCallError(
                "Save3", $"'{copyPath}' has no run folder above its '{CopyFolderName}' folder.");
        }

        return run!;
    }

    /// <summary>
    /// The bytewise copy, refusing to overwrite, with RK-9's fallback for a source SOLIDWORKS
    /// holds open.
    ///
    /// <c>File.Copy</c> asks for read access with a share mode that excludes writers, so it
    /// fails beside the handle SOLIDWORKS keeps on the engineer's open part. The fallback opens
    /// the source <c>FileShare.ReadWrite</c> and streams it into a destination opened
    /// <c>FileMode.CreateNew</c> - <b>never</b> <c>Create</c> - so refuse-to-overwrite survives
    /// the fallback (PROBE-13).
    /// </summary>
    public static RemodelCopyRoute CreateCopy(string sourcePath, string copyPath)
    {
        string source = Required(sourcePath, nameof(sourcePath));
        string copy = Required(copyPath, nameof(copyPath));

        if (File.Exists(copy))
        {
            throw new RemodelCopyError(
                "copy_exists",
                $"'{copy}' already exists. The re-modeler never overwrites a file that was "
                + "already there, its own earlier copy included.");
        }

        string? folder = Path.GetDirectoryName(copy);
        if (!string.IsNullOrEmpty(folder))
        {
            Directory.CreateDirectory(folder);
        }

        try
        {
            File.Copy(source, copy, overwrite: false);
            ClearReadOnly(copy);
            return RemodelCopyRoute.FileCopy;
        }
        catch (IOException primary)
        {
            if (File.Exists(copy))
            {
                throw new RemodelCopyError(
                    "copy_exists",
                    $"'{copy}' appeared while the copy was being made: {primary.Message}");
            }

            if (!File.Exists(source))
            {
                throw new RemodelCopyError(
                    "copy_failed", $"'{source}' could not be read: {primary.Message}");
            }

            StreamCopy(source, copy, primary);
            return RemodelCopyRoute.SharedReadStream;
        }
        catch (UnauthorizedAccessException primary)
        {
            throw new RemodelCopyError(
                "copy_failed", $"'{source}' could not be copied to '{copy}': {primary.Message}");
        }
    }

    /// <summary>
    /// The attestation, recorded <b>before</b> the copy is made and before any document handle
    /// to the source could exist. Reading it never opens the source for writing.
    ///
    /// <paramref name="vaultPath"/> and <paramref name="vaultRevision"/> come from the caller
    /// that can read the vault, and are null for a source that is not in one. Nothing here
    /// inspects the path for a vault, because nothing here may refuse a source for being in one.
    /// </summary>
    public static SourceAttestation RecordSource(
        string sourcePath,
        string copyPath,
        DateTime recordedAt,
        string? vaultPath,
        string? vaultRevision)
    {
        string source = Required(sourcePath, nameof(sourcePath));
        string copy = Required(copyPath, nameof(copyPath));

        var file = new FileInfo(source);
        if (!file.Exists)
        {
            throw new RemodelCopyError(
                "not_a_part", $"'{source}' does not exist, so there is nothing to attest to.");
        }

        return new SourceAttestation(
            source,
            file.Length,
            File.GetLastWriteTimeUtc(source),
            HashOf(source),
            DocumentIds.DesignId(source),
            recordedAt,
            copy,
            vaultPath,
            vaultRevision);
    }

    /// <summary>
    /// Tags the copy with this run's id and reads it back.
    ///
    /// <b>The read-back is the proof, not the return code.</b> PROBE-6 observed
    /// <c>Add3</c> answering -1 and adding nothing, silently; a tag judged by its answer would
    /// pass here and fail <see cref="RemodelScope.VerifyTarget"/>'s check 2 on the first write,
    /// where the message no longer points at the tag. The answer is handed back for
    /// `remodel.log`, so the run report can say what the seat actually did.
    /// </summary>
    public static int Tag(IRemodelCopyTarget target, string runId)
    {
        if (target == null)
        {
            throw new ArgumentNullException(nameof(target));
        }

        string id = Required(runId, nameof(runId));

        int answer = target.WriteSessionTag(SessionTagName, SessionTagType, id, SessionTagOverwrite);
        string? readBack = target.GetSessionTag(SessionTagName);

        if (!string.Equals(readBack, id, StringComparison.Ordinal))
        {
            throw new RemodelCopyError(
                "tag_failed",
                $"the copy's {SessionTagName} property read back as "
                + $"{(readBack == null ? "(absent)" : "'" + readBack + "'")} rather than '{id}'. "
                + $"Add3 answered {answer}. The tag is one of VerifyTarget's four checks, so a "
                + "run cannot start without it.");
        }

        return answer;
    }

    /// <summary>
    /// Removes the session tag, which is what <c>remodel.close</c> does after the last write
    /// the run will verify.
    ///
    /// The read-back is <b>not</b> asserted here, and that is the difference from
    /// <see cref="Tag"/>: the tag exists to prove the document is this run's copy before a
    /// write, and by the time this runs there is no write left to protect - the next call
    /// closes the document. A refusal here would leave the copy open with the run over. The
    /// answer is handed back for `remodel.log` instead, so the run report can still say what
    /// the seat did.
    /// </summary>
    public static int Untag(IRemodelCopyTarget target)
    {
        if (target == null)
        {
            throw new ArgumentNullException(nameof(target));
        }

        return target.RemoveSessionTag(SessionTagName);
    }

    /// <summary>
    /// The post-open assertion: the handle is the copy, at its own path, and is not the source.
    /// Both halves are stated, because "equals the copy" and "is not the source" fail
    /// differently and the report says which.
    /// </summary>
    public static void AssertOpenedAtCopy(IRemodelTarget target, string copyPath, string sourcePath)
    {
        if (target == null)
        {
            throw new ArgumentNullException(nameof(target));
        }

        string copy = Canonical(Required(copyPath, nameof(copyPath)), "open_failed");
        string source = Canonical(Required(sourcePath, nameof(sourcePath)), "open_failed");
        string? opened = target.GetPathName();

        if (string.IsNullOrWhiteSpace(opened))
        {
            throw new RemodelCopyError(
                "open_failed",
                $"the opened document reports no path, so it cannot be shown to be '{copy}'.");
        }

        string canonical = Canonical(opened!.Trim(), "open_failed");

        if (string.Equals(canonical, source, StringComparison.OrdinalIgnoreCase))
        {
            throw new RemodelCopyError(
                "open_failed",
                $"the opened document is the source '{sourcePath}'. The re-modeler works on a "
                + "copy it created in the run folder and never on the engineer's file.");
        }

        if (!string.Equals(canonical, copy, StringComparison.OrdinalIgnoreCase))
        {
            throw new RemodelCopyError(
                "open_failed",
                $"the opened document reports '{opened}' and not the copy '{copy}'.");
        }
    }

    /// <summary>
    /// <c>File.Copy</c> carries the source's attributes across, so a checked-in, read-only vault
    /// part would produce a read-only copy the seat could not save at the end of the run. The
    /// engineer's file keeps its attributes; the run's copy is the one that gets written.
    /// </summary>
    private static void ClearReadOnly(string copy)
    {
        FileAttributes attributes = File.GetAttributes(copy);
        if ((attributes & FileAttributes.ReadOnly) == FileAttributes.ReadOnly)
        {
            File.SetAttributes(copy, attributes & ~FileAttributes.ReadOnly);
        }
    }

    /// <summary>
    /// RK-9's fallback, on its own: the source read <c>FileShare.ReadWrite</c> - so a handle
    /// SOLIDWORKS holds on the engineer's open part does not block it - streamed into a
    /// destination opened <c>FileMode.CreateNew</c>, <b>never</b> <c>Create</c>, so
    /// refuse-to-overwrite survives the fallback (PROBE-13).
    ///
    /// Public because it is the operation RK-9 names, and because it is what a test can exercise
    /// against a genuinely held-open source: <c>CopyFile</c> shares read <i>and</i> write on
    /// Windows 11, so no in-process share mode makes the primary route fail while leaving this
    /// one able to succeed. Whether a real SOLIDWORKS handle ever defeats <c>File.Copy</c> is
    /// PROBE-13's question, and this is the answer that is ready either way.
    /// </summary>
    public static void CopyThroughSharedStream(string sourcePath, string copyPath) =>
        StreamCopy(Required(sourcePath, nameof(sourcePath)), Required(copyPath, nameof(copyPath)), null);

    private static void StreamCopy(string source, string copy, IOException? primary)
    {
        if (File.Exists(copy))
        {
            throw new RemodelCopyError(
                "copy_exists",
                $"'{copy}' already exists. The re-modeler never overwrites a file that was "
                + "already there, its own earlier copy included.");
        }

        string? folder = Path.GetDirectoryName(copy);
        if (!string.IsNullOrEmpty(folder))
        {
            Directory.CreateDirectory(folder);
        }

        try
        {
            using (var reader = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var writer = new FileStream(copy, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                reader.CopyTo(writer);
            }
        }
        catch (Exception fallback) when (fallback is IOException || fallback is UnauthorizedAccessException)
        {
            if (File.Exists(copy) && primary == null)
            {
                throw new RemodelCopyError(
                    "copy_exists", $"'{copy}' appeared while the copy was being made: {fallback.Message}");
            }

            throw new RemodelCopyError(
                "copy_failed",
                $"'{source}' could not be copied to '{copy}'. "
                + (primary == null ? string.Empty : $"File.Copy said: {primary.Message} ")
                + $"The FileShare.ReadWrite read said: {fallback.Message}");
        }

        // No ClearReadOnly here: this route creates a new file and writes bytes into it, so it
        // never carries the source's attributes across the way File.Copy does.
    }

    private static string HashOf(string path)
    {
        using (var sha = SHA256.Create())
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
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

    private static string Canonical(string path, string errorCode)
    {
        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception error) when (error is ArgumentException
            || error is NotSupportedException
            || error is PathTooLongException
            || error is System.Security.SecurityException)
        {
            throw new RemodelCopyError(
                errorCode, $"'{path}' could not be canonicalized: {error.Message}");
        }
    }

    private static string Required(string value, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("A value is required.", parameterName);
        }

        return value.Trim();
    }
}
