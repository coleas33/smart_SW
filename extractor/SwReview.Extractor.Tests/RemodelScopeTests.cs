using System;
using System.Collections.Generic;
using System.IO;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T048. Layer 2 of the write guard: <b>which document a member may be called on</b>.
///
/// <see cref="RemodelGuard"/> decides which member may be called at all and cannot decide more
/// than that, because the document is captured inside the lambda at
/// <c>SwGate.Call("GetChildren", () =&gt; component.GetChildren())</c> and the call guard never
/// sees it. <see cref="RemodelScope"/> is the only object that holds the copy's
/// <c>IModelDoc2</c>, and every write it makes is <c>VerifyTarget()</c> and then
/// <c>gate.Call(qualifiedKey, ...)</c>.
///
/// <see cref="RemodelScope.VerifyTarget"/> is contracts/guard-allowlist.md's four cheap checks,
/// re-run <b>before every single write</b> rather than once at open:
///
///   1. <c>GetPathName()</c> equals the copy path this run created - a different document
///      became the handle;
///   2. the <c>SwReviewRemodelRun</c> custom property equals this run's id - a different copy,
///      or the tag stripped;
///   3. <c>ISldWorks.GetOpenDocumentByName(copyPath)</c> returns the <b>same</b> COM identity
///      (<c>Marshal.GetIUnknownForObject</c>) - a close-and-reopen underneath the run;
///   4. the copy path is a canonicalized descendant of this run's folder, with <c>..</c>
///      resolved - a path that escapes the run folder.
///
/// "Before every write" is asserted here <b>by call count</b> rather than by reading the
/// implementation: a scope that verified once and cached the answer would pass an inspection
/// and fail RK-14, where the engineer edits or closes the copy mid-run.
///
/// Each failure throws <see cref="RemodelTargetError"/> naming the check that failed. What the
/// run does next - abort with `changes.jsonl` intact and the copy left on disk for inspection -
/// is the executor's, not the scope's, and is pinned by the Phase 5 artifact tests.
/// </summary>
public class RemodelScopeTests
{
    private const string RunId = "20260916-142201-bracket-remodel";

    private static readonly string RunDirectory =
        Path.Combine(Path.GetTempPath(), "SwReview.RemodelScope", RunId);

    private static readonly string CopyPath =
        Path.Combine(RunDirectory, "copy", "bracket-RMS.SLDPRT");

    /// <summary>A write key that is on the stage-1 allowlist, so the gate is not the subject.</summary>
    private const string AllowedKey = "IFeature.set_Name";

    /// <summary>
    /// The four reads <see cref="RemodelScope.VerifyTarget"/> makes, in the order
    /// contracts/guard-allowlist.md numbers them. Check 4 is pure and makes no read, which is
    /// why the sequence has four names and not five.
    /// </summary>
    private static readonly string[] VerifySequence =
    {
        nameof(IRemodelTarget.GetPathName),
        nameof(IRemodelTarget.GetSessionTag),
        nameof(IRemodelTarget.GetDocumentIdentity),
        nameof(IRemodelTarget.GetOpenDocumentIdentity),
    };

    /// <summary>
    /// The copy as the scope addresses it: four reads and nothing else, so every decision
    /// <see cref="RemodelScope"/> makes is testable without a SOLIDWORKS seat (the same split
    /// as <c>ISuppressTarget</c> and <c>SwSuppressTarget</c>).
    /// </summary>
    private sealed class TargetFake : IRemodelTarget
    {
        private readonly IntPtr _identity = new IntPtr(0x4001);

        /// <summary>Every seam member called, in order, across every call.</summary>
        public List<string> Members { get; } = new List<string>();

        /// <summary>The paths <see cref="GetOpenDocumentIdentity"/> was asked about.</summary>
        public List<string> OpenDocumentQueries { get; } = new List<string>();

        /// <summary>The custom-property names <see cref="GetSessionTag"/> was asked for.</summary>
        public List<string> TagQueries { get; } = new List<string>();

        public string? PathName { get; set; } = CopyPath;

        public string? SessionTag { get; set; } = RunId;

        /// <summary>What the held document's identity reads as.</summary>
        public IntPtr DocumentIdentity { get; set; }

        /// <summary>
        /// What <c>GetOpenDocumentByName(copyPath)</c>'s identity reads as.
        /// <see cref="IntPtr.Zero"/> is "SOLIDWORKS no longer has that path open".
        /// </summary>
        public IntPtr OpenIdentity { get; set; }

        public TargetFake()
        {
            DocumentIdentity = _identity;
            OpenIdentity = _identity;
        }

        public string? GetPathName()
        {
            Members.Add(nameof(GetPathName));
            return PathName;
        }

        public string? GetSessionTag(string fieldName)
        {
            Members.Add(nameof(GetSessionTag));
            TagQueries.Add(fieldName);
            return SessionTag;
        }

        public IntPtr GetDocumentIdentity()
        {
            Members.Add(nameof(GetDocumentIdentity));
            return DocumentIdentity;
        }

        public IntPtr GetOpenDocumentIdentity(string documentPath)
        {
            Members.Add(nameof(GetOpenDocumentIdentity));
            OpenDocumentQueries.Add(documentPath);
            return OpenIdentity;
        }
    }

    private static SwGate Gate() => new SwGate(new CircuitBreaker(), new RemodelGuard());

    private static RemodelScope ScopeOver(TargetFake target, string? copyPath = null) =>
        new RemodelScope(target, Gate(), RunId, copyPath ?? CopyPath, RunDirectory);

    // ---------------------------------------------------------------- the happy path

    [Fact]
    public void VerifyTargetReadsTheFourChecksInTheOrderTheContractNumbersThem()
    {
        var target = new TargetFake();

        ScopeOver(target).VerifyTarget();

        Assert.Equal(VerifySequence, target.Members);
    }

    /// <summary>
    /// Check 2 asks for the one property name the copy was tagged with. A scope that asked for
    /// a different name would read null and refuse every write, which is a failure mode worth
    /// one assertion rather than a comment.
    /// </summary>
    [Fact]
    public void VerifyTargetAsksForTheSessionTagTheCopyWasTaggedWith()
    {
        var target = new TargetFake();

        ScopeOver(target).VerifyTarget();

        Assert.Equal(new[] { RemodelCopy.SessionTagName }, target.TagQueries);
    }

    /// <summary>
    /// Check 3 asks SOLIDWORKS about <b>the copy path</b>, not about whatever the document
    /// currently reports: asking the document for its own path and then asking SOLIDWORKS about
    /// that path would agree with itself after a close-and-reopen, which is the case the check
    /// exists for.
    /// </summary>
    [Fact]
    public void VerifyTargetAsksSolidworksAboutTheCopyPathAndNotAboutWhatTheDocumentReports()
    {
        var target = new TargetFake { PathName = CopyPath };

        ScopeOver(target).VerifyTarget();

        Assert.Equal(new[] { CopyPath }, target.OpenDocumentQueries);
    }

    /// <summary>
    /// The path is compared canonically: the same file spelled with a redundant separator is
    /// the same document, and a scope that refused it would abort a healthy run.
    /// </summary>
    [Fact]
    public void VerifyTargetAcceptsTheCopyPathSpelledWithARedundantSeparator()
    {
        string spelled = Path.Combine(RunDirectory, "copy", ".", "bracket-RMS.SLDPRT");
        var target = new TargetFake { PathName = spelled };

        ScopeOver(target).VerifyTarget();

        Assert.Equal(VerifySequence, target.Members);
    }

    // ------------------------------------------------- each check fails independently

    [Fact]
    public void Check1RefusesWhenTheDocumentReportsADifferentPath()
    {
        var target = new TargetFake { PathName = @"C:\work\bracket.SLDPRT" };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.DocumentPath, error.Check);
        Assert.Contains("GetPathName", error.Message, StringComparison.Ordinal);
        Assert.Contains(@"C:\work\bracket.SLDPRT", error.Message, StringComparison.Ordinal);
    }

    /// <summary>A document with no path at all is check 1's failure, named as one.</summary>
    [Fact]
    public void Check1RefusesWhenTheDocumentReportsNoPath()
    {
        var target = new TargetFake { PathName = null };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.DocumentPath, error.Check);
    }

    [Fact]
    public void Check2RefusesWhenTheSessionTagIsAnotherRunsId()
    {
        var target = new TargetFake { SessionTag = "20260916-090000-bracket-remodel" };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.SessionTag, error.Check);
        Assert.Contains(RemodelCopy.SessionTagName, error.Message, StringComparison.Ordinal);
    }

    /// <summary>The tag stripped is not the tag changed, and the message says which it was.</summary>
    [Fact]
    public void Check2RefusesWhenTheSessionTagHasBeenStripped()
    {
        var target = new TargetFake { SessionTag = null };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.SessionTag, error.Check);
        Assert.Contains("carries no", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Check3RefusesWhenSolidworksHandsBackADifferentComIdentity()
    {
        var target = new TargetFake { OpenIdentity = new IntPtr(0x9999) };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.ComIdentity, error.Check);
        Assert.Contains("GetOpenDocumentByName", error.Message, StringComparison.Ordinal);
    }

    /// <summary>
    /// The copy closed underneath the run: SOLIDWORKS has nothing open at that path, so there
    /// is no identity to compare. That is check 3's failure and not a silent pass.
    /// </summary>
    [Fact]
    public void Check3RefusesWhenSolidworksNoLongerHasTheCopyOpen()
    {
        var target = new TargetFake { OpenIdentity = IntPtr.Zero };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.ComIdentity, error.Check);
    }

    /// <summary>
    /// A held document that has released its own identity is check 3 as well: comparing
    /// <see cref="IntPtr.Zero"/> with <see cref="IntPtr.Zero"/> would make two dead handles
    /// "the same document".
    /// </summary>
    [Fact]
    public void Check3RefusesWhenTheHeldDocumentHasNoIdentityEitherRatherThanMatchingZeroToZero()
    {
        var target = new TargetFake { DocumentIdentity = IntPtr.Zero, OpenIdentity = IntPtr.Zero };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.ComIdentity, error.Check);
    }

    [Theory]
    [InlineData(@"copy\..\..\escape\bracket-RMS.SLDPRT")]
    [InlineData(@"..\bracket-RMS.SLDPRT")]
    public void Check4RefusesACopyPathThatEscapesTheRunFolder(string relative)
    {
        string escaping = Path.Combine(RunDirectory, relative);
        var target = new TargetFake { PathName = escaping };

        var error = Assert.Throws<RemodelTargetError>(() =>
            ScopeOver(target, escaping).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.RunFolderContainment, error.Check);
        Assert.Contains(RunDirectory, error.Message, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Another run's copy is outside this run's folder, so it is check 4 and not check 1: the
    /// two checks answer different questions and a test that let one stand in for the other
    /// would not notice if the other were deleted.
    /// </summary>
    [Fact]
    public void Check4RefusesAnotherRunsCopy()
    {
        string other = Path.Combine(
            Path.GetTempPath(), "SwReview.RemodelScope", "20260916-090000-bracket-remodel",
            "copy", "bracket-RMS.SLDPRT");
        var target = new TargetFake { PathName = other };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target, other).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.RunFolderContainment, error.Check);
    }

    /// <summary>
    /// The checks run in the contract's order, so a target failing two of them reports the
    /// first. Without this the error token a run reports would depend on the implementation's
    /// evaluation order rather than on the contract.
    /// </summary>
    [Fact]
    public void ATargetFailingSeveralChecksReportsTheFirstOne()
    {
        var target = new TargetFake
        {
            PathName = @"C:\work\bracket.SLDPRT",
            SessionTag = null,
            OpenIdentity = IntPtr.Zero,
        };

        var error = Assert.Throws<RemodelTargetError>(() => ScopeOver(target).VerifyTarget());

        Assert.Equal(RemodelTargetCheck.DocumentPath, error.Check);
    }

    // ------------------------------------------------ VerifyTarget before EVERY write

    /// <summary>
    /// Asserted by call count, not by inspection. A scope that verified once at open and cached
    /// the answer would read correctly and fail RK-14.
    /// </summary>
    [Fact]
    public void EveryWriteVerifiesTheTargetFirstAssertedByCallCount()
    {
        var target = new TargetFake();
        RemodelScope scope = ScopeOver(target);
        int calls = 0;

        for (int i = 0; i < 3; i++)
        {
            scope.Write(AllowedKey, () => calls++);
        }

        Assert.Equal(3, calls);
        Assert.Equal(
            new[]
            {
                VerifySequence[0], VerifySequence[1], VerifySequence[2], VerifySequence[3],
                VerifySequence[0], VerifySequence[1], VerifySequence[2], VerifySequence[3],
                VerifySequence[0], VerifySequence[1], VerifySequence[2], VerifySequence[3],
            },
            target.Members);
    }

    /// <summary>A write that returns a value verifies too, and hands the value back.</summary>
    [Fact]
    public void AWriteThatReturnsAValueVerifiesFirstAndHandsTheValueBack()
    {
        var target = new TargetFake();

        bool returned = ScopeOver(target).Write(AllowedKey, () => true);

        Assert.True(returned);
        Assert.Equal(VerifySequence, target.Members);
    }

    /// <summary>
    /// The refusal happens <b>before</b> the interop call, not after it. A scope that called
    /// first and checked afterwards would have already written to the wrong document.
    /// </summary>
    [Fact]
    public void AWriteWhoseTargetFailsNeverReachesTheInteropCall()
    {
        var target = new TargetFake { SessionTag = null };
        bool called = false;

        Assert.Throws<RemodelTargetError>(() =>
            ScopeOver(target).Write(AllowedKey, () => called = true));

        Assert.False(called, "the interop call ran although VerifyTarget refused");
    }

    /// <summary>
    /// The change log stays readable across a refusal: the scope throws and changes nothing
    /// about itself, so the next write verifies from the same recorded copy path and run id.
    /// </summary>
    [Fact]
    public void AScopeThatRefusedOnceVerifiesAgainstTheSameRunWhenTheTargetRecovers()
    {
        var target = new TargetFake { SessionTag = null };
        RemodelScope scope = ScopeOver(target);

        Assert.Throws<RemodelTargetError>(() => scope.Write(AllowedKey, () => { }));

        target.SessionTag = RunId;
        int calls = 0;
        scope.Write(AllowedKey, () => calls++);

        Assert.Equal(1, calls);
    }

    // -------------------------------------------------------------- the gate, and keys

    /// <summary>
    /// A member that is not on the stage-1 allowlist is refused by the gate. The scope answers
    /// "which document", the guard answers "which member", and both have to pass.
    /// </summary>
    [Fact]
    public void AWriteOfAMemberThatIsNotOnTheStage1AllowlistIsRefusedByTheGate()
    {
        var target = new TargetFake();
        bool called = false;

        Assert.Throws<MutatingCallError>(() =>
            ScopeOver(target).Write("IModelDoc2.EditDelete", () => called = true));

        Assert.False(called);
    }

    /// <summary>
    /// A bare key at a remodel write call site is a programming error: it could never have
    /// matched the interface-qualified allowlist, so the call would silently take
    /// <see cref="ReadOnlyGuard"/>'s path instead of being judged as a write.
    /// </summary>
    [Fact]
    public void AWriteWithABareMemberNameIsAProgrammingErrorAndVerifiesNothing()
    {
        var target = new TargetFake();
        bool called = false;

        Assert.Throws<ArgumentException>(() => ScopeOver(target).Write("set_Name", () => called = true));

        Assert.False(called);
        Assert.Empty(target.Members);
    }

    // ------------------------------------------------------------------ construction

    [Fact]
    public void AScopeRefusesToBeBuiltWithoutATarget()
    {
        Assert.Throws<ArgumentNullException>(() =>
            new RemodelScope(null!, Gate(), RunId, CopyPath, RunDirectory));
    }

    [Fact]
    public void AScopeRefusesToBeBuiltWithoutAGate()
    {
        Assert.Throws<ArgumentNullException>(() =>
            new RemodelScope(new TargetFake(), null!, RunId, CopyPath, RunDirectory));
    }

    [Theory]
    [InlineData("", "copy", "run")]
    [InlineData("run-id", "", "run")]
    [InlineData("run-id", "copy", "")]
    public void AScopeRefusesToBeBuiltWithABlankRunIdCopyPathOrRunFolder(
        string runId, string copyPath, string runDirectory)
    {
        Assert.Throws<ArgumentException>(() =>
            new RemodelScope(new TargetFake(), Gate(), runId, copyPath, runDirectory));
    }

    /// <summary>
    /// The scope reports the copy path canonically, because that is what every
    /// <c>ChangeRecord.target_path</c> and every `remodel.log` line records, and the report
    /// asserts the two agree (FR-041).
    /// </summary>
    [Fact]
    public void AScopeReportsTheCanonicalizedCopyPathAndRunFolder()
    {
        var scope = new RemodelScope(
            new TargetFake(),
            Gate(),
            RunId,
            Path.Combine(RunDirectory, "copy", ".", "bracket-RMS.SLDPRT"),
            RunDirectory + Path.DirectorySeparatorChar);

        Assert.Equal(Path.GetFullPath(CopyPath), scope.CopyPath);
        Assert.Equal(Path.GetFullPath(RunDirectory), scope.RunDirectory);
        Assert.Equal(RunId, scope.RunId);
    }
}
