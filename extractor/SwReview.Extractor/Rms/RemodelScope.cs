using System;
using System.IO;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The two interop reads <see cref="RemodelScope.AssertFolderSelection"/> makes, and nothing
/// else, so the assertion is testable without a SOLIDWORKS seat (the same split as
/// <c>ISuppressTarget</c> and <c>SwSuppressTarget</c>).
///
/// The implementation reads <c>ISelectionMgr.GetSelectedObjectCount2(-1)</c> (VERIFIED) and
/// <c>((IFeature)selectionMgr.GetSelectedObject6(1, -1))?.GetTypeName2()</c> (VERIFIED). Both
/// are reads, so both take the remodel guard's delegation branch to
/// <see cref="ReadOnlyGuard"/>. There is no COM-backed implementation in v1: the assertion has
/// no write call site (see <see cref="RemodelScope.AssertFolderSelection"/>), and the adapter
/// arrives with the stage-2 dissolve that first needs one.
/// </summary>
public interface IFolderSelection
{
    /// <summary><c>ISelectionMgr.GetSelectedObjectCount2(-1)</c>: every mark, this document.</summary>
    int GetSelectedObjectCount();

    /// <summary>
    /// <c>GetTypeName2()</c> of the single selected feature, or null when the selection holds
    /// no feature at all - which is a different failure from a feature of the wrong type and
    /// is named as one.
    /// </summary>
    string? GetSelectedFeatureTypeName();
}

/// <summary>
/// The copy, as <see cref="RemodelScope.VerifyTarget"/> addresses it: four reads and nothing
/// else, so every decision the scope makes is testable without a SOLIDWORKS seat (the same split
/// as <c>ISuppressTarget</c> and <c>SwSuppressTarget</c>).
///
/// The COM implementation is the only thing in the product that holds the copy's
/// <c>IModelDoc2</c>. Each member is one VERIFIED read:
/// </summary>
public interface IRemodelTarget
{
    /// <summary><c>IModelDoc2.GetPathName()</c>. Check 1.</summary>
    string? GetPathName();

    /// <summary>
    /// <c>Extension.CustomPropertyManager("").Get4(fieldName, false, out value, out resolved)</c>.
    /// Check 2. Null is "the property is not there", which is a different failure from a
    /// property carrying another run's id and is reported as one.
    /// </summary>
    string? GetSessionTag(string fieldName);

    /// <summary>
    /// <c>Marshal.GetIUnknownForObject</c> of the held <c>IModelDoc2</c>, released immediately
    /// so the pointer is an identity to compare and never a reference to keep. Check 3.
    /// </summary>
    IntPtr GetDocumentIdentity();

    /// <summary>
    /// The same for <c>ISldWorks.GetOpenDocumentByName(documentPath)</c>, or
    /// <see cref="IntPtr.Zero"/> when SOLIDWORKS has nothing open at that path. Check 3.
    /// </summary>
    IntPtr GetOpenDocumentIdentity(string documentPath);
}

/// <summary>
/// Which of <see cref="RemodelScope.VerifyTarget"/>'s four checks failed, numbered as
/// contracts/guard-allowlist.md numbers them.
/// </summary>
public enum RemodelTargetCheck
{
    /// <summary>1. <c>GetPathName()</c> is not the copy path this run created.</summary>
    DocumentPath = 1,

    /// <summary>2. The <c>SwReviewRemodelRun</c> property is not this run's id.</summary>
    SessionTag = 2,

    /// <summary>3. <c>GetOpenDocumentByName(copyPath)</c> is not the same COM identity.</summary>
    ComIdentity = 3,

    /// <summary>4. The copy path is not a canonicalized descendant of this run's folder.</summary>
    RunFolderContainment = 4,
}

/// <summary>
/// Raised when <see cref="RemodelScope.VerifyTarget"/> refuses. The run aborts with
/// `changes.jsonl` intact and the copy left on disk for inspection; the bridge reports it as
/// <c>target_mismatch</c>.
/// </summary>
[Serializable]
public class RemodelTargetError : Exception
{
    public RemodelTargetError(RemodelTargetCheck check, string message)
        : base(message)
    {
        Check = check;
    }

    /// <summary>The check that failed, so a caller never parses the sentence.</summary>
    public RemodelTargetCheck Check { get; }
}

/// <summary>
/// T045, T047 and T049. Layer 2 of the write guard (contracts/guard-allowlist.md): <b>which
/// document a member may be called on</b>. <see cref="RemodelGuard"/> decides which member may be called
/// at all, and cannot decide more than that - the document is captured inside the lambda at
/// <c>SwGate.Call("GetChildren", () =&gt; component.GetChildren())</c>, so the call guard never
/// sees it.
///
/// The static half carries the two assertions that are pure. The instance half holds the copy -
/// through <see cref="IRemodelTarget"/>, the only handle on it anywhere in the product - and
/// runs <see cref="VerifyTarget"/> before <b>every single write</b>, never once at open: RK-14
/// is the engineer editing or closing the copy mid-run, and a scope that cached the answer would
/// read correctly and miss it.
///
/// <b>The strongest property here is structural, not procedural.</b> No command in the bridge
/// protocol takes a document, so the scope's copy is the only target reachable. That is stronger
/// than validating a path a caller supplied, and it is what the constitution's exception rests
/// on.
/// </summary>
public sealed class RemodelScope
{
    /// <summary>The one extension the re-modeler may save. Parts only, in stage 1 and in v1.</summary>
    private const string PartExtension = ".SLDPRT";

    /// <summary>The member every refusal here is reported against.</summary>
    private const string SaveMember = "Save3";

    /// <summary>The type name a feature folder reports on 2024 SP5 (VERIFIED).</summary>
    private const string FolderTypeName = "FtrFolder";

    /// <summary>
    /// The copy. The one handle on the document this run may change, anywhere in the product.
    /// </summary>
    private readonly IRemodelTarget _target;

    /// <summary>A <see cref="SwGate"/> built with a <see cref="RemodelGuard"/>.</summary>
    private readonly SwGate _gate;

    /// <summary>
    /// Binds the scope to one copy, for one run. <paramref name="gate"/> is a
    /// <see cref="SwGate"/> built with a <see cref="RemodelGuard"/>: the guard answers "which
    /// member", this object answers "which document", and both have to pass.
    /// </summary>
    public RemodelScope(
        IRemodelTarget target, SwGate gate, string runId, string copyPath, string runDirectory)
    {
        _target = target ?? throw new ArgumentNullException(nameof(target));
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        if (string.IsNullOrWhiteSpace(runId))
        {
            throw new ArgumentException("A run id is required.", nameof(runId));
        }

        RunId = runId.Trim();
        CopyPath = CanonicalizeArgument(Required(copyPath, nameof(copyPath)), nameof(copyPath));
        RunDirectory = CanonicalizeArgument(
                Required(runDirectory, nameof(runDirectory)), nameof(runDirectory))
            .TrimEnd(Path.DirectorySeparatorChar);
    }

    /// <summary>The id written into the copy's <c>SwReviewRemodelRun</c> custom property.</summary>
    public string RunId { get; }

    /// <summary>
    /// The copy this run created, canonicalized. Every <c>ChangeRecord.target_path</c> and every
    /// `remodel.log` line records this value, and the report asserts the two agree (FR-041).
    /// </summary>
    public string CopyPath { get; }

    /// <summary>This run's folder, canonicalized; check 4's containment root.</summary>
    public string RunDirectory { get; }

    /// <summary>
    /// The four cheap checks of contracts/guard-allowlist.md, in the order that file numbers
    /// them, re-run before every single write. A target failing several reports the first, so
    /// the error token a run reports comes from the contract rather than from an evaluation
    /// order.
    /// </summary>
    public void VerifyTarget()
    {
        string? reported = _target.GetPathName();
        if (string.IsNullOrWhiteSpace(reported)
            || !string.Equals(Canonicalize(reported!.Trim()), CopyPath, StringComparison.OrdinalIgnoreCase))
        {
            throw new RemodelTargetError(
                RemodelTargetCheck.DocumentPath,
                $"check 1 failed: GetPathName() reports "
                + $"{(string.IsNullOrWhiteSpace(reported) ? "(no path)" : "'" + reported + "'")} "
                + $"and this run's copy is '{CopyPath}'. A different document became the handle.");
        }

        string? tag = _target.GetSessionTag(RemodelCopy.SessionTagName);
        if (tag == null)
        {
            throw new RemodelTargetError(
                RemodelTargetCheck.SessionTag,
                $"check 2 failed: the document carries no {RemodelCopy.SessionTagName} custom "
                + "property, so it cannot be shown to be this run's copy.");
        }

        if (!string.Equals(tag, RunId, StringComparison.Ordinal))
        {
            throw new RemodelTargetError(
                RemodelTargetCheck.SessionTag,
                $"check 2 failed: {RemodelCopy.SessionTagName} reads '{tag}' and this run is "
                + $"'{RunId}'. That is a different copy.");
        }

        IntPtr held = _target.GetDocumentIdentity();
        IntPtr open = _target.GetOpenDocumentIdentity(CopyPath);
        if (held == IntPtr.Zero || open == IntPtr.Zero || held != open)
        {
            throw new RemodelTargetError(
                RemodelTargetCheck.ComIdentity,
                $"check 3 failed: GetOpenDocumentByName('{CopyPath}') is COM identity {open} and "
                + $"the document this scope holds is {held}. The copy was closed and reopened "
                + "underneath the run.");
        }

        if (!IsInside(CopyPath, RunDirectory))
        {
            throw new RemodelTargetError(
                RemodelTargetCheck.RunFolderContainment,
                $"check 4 failed: '{CopyPath}' is not inside this run's folder "
                + $"'{RunDirectory}'.");
        }
    }

    /// <summary>
    /// One write: <see cref="VerifyTarget"/>, then <c>gate.Call(qualifiedKey, ...)</c>. Every
    /// write the re-modeler makes goes through here, so "the target is verified first" is one
    /// statement rather than one per call site.
    ///
    /// <paramref name="qualifiedKey"/> is interface-qualified. A bare key is a programming
    /// error, not a refusal: it could never have matched the interface-qualified allowlist, so
    /// the call would silently take <see cref="ReadOnlyGuard"/>'s path instead of being judged
    /// as a write. It is checked before the target is, because a mis-written call site is not a
    /// reason to touch the seat at all.
    /// </summary>
    public void Write(string qualifiedKey, Action call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        string key = CallKey.AssertQualified(qualifiedKey);
        VerifyTarget();
        _gate.Call(key, call);
    }

    /// <inheritdoc cref="Write(string, Action)" />
    public T Write<T>(string qualifiedKey, Func<T> call)
    {
        if (call == null)
        {
            throw new ArgumentNullException(nameof(call));
        }

        string key = CallKey.AssertQualified(qualifiedKey);
        VerifyTarget();
        return _gate.Call(key, call);
    }

    /// <summary>
    /// Called before <c>IModelDoc2.Save3</c> even though <c>Save3</c> takes no filename
    /// (VERIFIED). The source is already unreachable structurally - the copy is opened at its
    /// own path, <c>Save3</c> saves the document it is called on, and nothing in stage 1 uses
    /// <c>SaveAs*</c> - but this assertion is what the test suite pins and what the run report
    /// cites, so the property is checked rather than merely argued.
    ///
    /// Only <paramref name="copyPath"/>, spelled exactly as this run created it, passes.
    /// Everything else is refused with the reason named: a path carrying <c>..</c> (refused
    /// before canonicalization, so a path that would canonicalize onto the copy is refused
    /// too), a path that is not a part file, the source, a path outside this run's folder -
    /// another run's copy among them - and the copy path spelled in another case or as an 8.3
    /// short name, because the final comparison is exact.
    /// </summary>
    public static void AssertSaveTarget(string path, string copyPath, string runDirectory, string sourcePath)
    {
        string candidate = Required(path, nameof(path));
        string copy = Required(copyPath, nameof(copyPath));
        string runRoot = Required(runDirectory, nameof(runDirectory));
        string source = Required(sourcePath, nameof(sourcePath));

        if (HasRelativeSegment(candidate))
        {
            throw Refusal($"'{candidate}' contains a '..' segment; a save target is refused before "
                + "it is canonicalized, so a path that would resolve onto the copy is refused too.");
        }

        string extension = Path.GetExtension(candidate);
        if (!string.Equals(extension, PartExtension, StringComparison.OrdinalIgnoreCase))
        {
            string described = string.IsNullOrEmpty(extension) ? "(no extension)" : extension;
            throw Refusal($"'{candidate}' is not a part file: the re-modeler writes {PartExtension} "
                + $"and nothing else; got {described}.");
        }

        string fullCandidate = Canonicalize(candidate);
        string fullCopy = Canonicalize(copy);
        string fullSource = Canonicalize(source);
        string fullRunRoot = Canonicalize(runRoot).TrimEnd(Path.DirectorySeparatorChar);

        if (string.Equals(fullCandidate, fullSource, StringComparison.OrdinalIgnoreCase))
        {
            throw Refusal($"'{candidate}' is the source file. The re-modeler works on a copy it "
                + "created in the run folder and never saves over an existing file.");
        }

        if (!IsInside(fullCandidate, fullRunRoot))
        {
            throw Refusal($"'{candidate}' is outside this run's folder '{fullRunRoot}'.");
        }

        if (!string.Equals(fullCandidate, fullCopy, StringComparison.Ordinal))
        {
            throw Refusal($"'{candidate}' is not this run's copy '{fullCopy}'. The comparison is "
                + "exact, so another case or an 8.3 short name of the same file is refused.");
        }
    }

    /// <summary>
    /// The named reading of "one selected object and it is a feature folder":
    /// <c>GetSelectedObjectCount2(-1) == 1</c> <b>and</b>
    /// <c>((IFeature)GetSelectedObject6(1, -1)).GetTypeName2() == "FtrFolder"</c> (all VERIFIED).
    /// One wrong selection under a delete removes real features, so this exists once, as a
    /// helper, and is never inlined at a call site.
    ///
    /// In v1 it is a <b>refusal predicate with no write call site</b>.
    /// <c>IModelDoc2.EditDelete</c> is not on the stage-1 allowlist - the owner's decision is
    /// that a part carrying an RMS-named folder whose members differ from the plan is refused
    /// with <c>rms_named_folder_wrong_members</c> rather than dissolved - so v1 has no dissolve
    /// path and nothing calls this before a delete. Its two v1 uses are the reading the
    /// planner's refusal is written against, and the stated precondition any future dissolve
    /// must pass. It is <b>not</b> a precondition to folder creation: creation selects a
    /// contiguous run of N content features, which this predicate refuses by construction, so
    /// calling it before the <c>set_Name</c> that follows
    /// <c>InsertFeatureTreeFolder2(Containing = 2)</c> would fail every folder creation.
    /// </summary>
    public static void AssertFolderSelection(IFolderSelection selection)
    {
        if (selection == null)
        {
            throw new ArgumentNullException(nameof(selection));
        }

        int count = selection.GetSelectedObjectCount();
        if (count != 1)
        {
            throw new InvalidOperationException(
                $"GetSelectedObjectCount2(-1) == 1 failed: {count} objects are selected. A folder "
                + "assertion reads exactly one selected object.");
        }

        string? typeName = selection.GetSelectedFeatureTypeName();
        if (typeName == null)
        {
            throw new InvalidOperationException(
                "GetSelectedObject6(1, -1) returned no feature, so there is nothing to read "
                + $"GetTypeName2() == \"{FolderTypeName}\" from.");
        }

        if (!string.Equals(typeName, FolderTypeName, StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"GetTypeName2() == \"{FolderTypeName}\" failed: the selected feature is "
                + $"'{typeName}'.");
        }
    }

    private static MutatingCallError Refusal(string message) => new MutatingCallError(SaveMember, message);

    private static string Required(string value, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("A path is required.", parameterName);
        }

        return value.Trim();
    }

    /// <summary>True when any segment of the raw path is <c>..</c> or <c>.</c>.</summary>
    private static bool HasRelativeSegment(string path)
    {
        foreach (string segment in path.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar))
        {
            if (segment == ".." || segment == ".")
            {
                return true;
            }
        }

        return false;
    }

    private static string Canonicalize(string path)
    {
        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception error) when (IsPathError(error))
        {
            throw Refusal($"'{path}' could not be canonicalized: {error.Message}");
        }
    }

    /// <summary>
    /// The constructor's canonicalization. A path this object was <b>built</b> with that cannot
    /// be canonicalized is a bad argument, not a refused save, so it does not answer with
    /// <see cref="Refusal"/>'s <c>Save3</c> <see cref="MutatingCallError"/>.
    /// </summary>
    private static string CanonicalizeArgument(string path, string parameterName)
    {
        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception error) when (IsPathError(error))
        {
            throw new ArgumentException(
                $"'{path}' could not be canonicalized: {error.Message}", parameterName, error);
        }
    }

    /// <summary>The four ways <c>Path.GetFullPath</c> answers "that is not a path".</summary>
    private static bool IsPathError(Exception error) =>
        error is ArgumentException
        || error is NotSupportedException
        || error is PathTooLongException
        || error is System.Security.SecurityException;

    private static bool IsInside(string fullPath, string fullRoot)
    {
        return fullPath.Length > fullRoot.Length + 1
            && fullPath.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase)
            && (fullPath[fullRoot.Length] == Path.DirectorySeparatorChar
                || fullPath[fullRoot.Length] == Path.AltDirectorySeparatorChar);
    }
}
