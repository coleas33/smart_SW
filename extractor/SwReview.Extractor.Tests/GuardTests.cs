using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using SwReview.Extractor.Guard;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T022. The guard is the only thing standing between an agent-driven bridge and a
/// modified reviewed model (research R4, constitution Technical Constraints).
/// </summary>
public class ReadOnlyGuardTests
{
    [Theory]
    [InlineData("EditRebuild3")]
    [InlineData("ForceRebuild3")]
    [InlineData("Save3")]
    [InlineData("SaveAs3")]
    [InlineData("Delete2")]
    [InlineData("EditSuppress2")]
    [InlineData("EditUnsuppress2")]
    [InlineData("EditDelete")]
    [InlineData("ModifyDefinition")]
    [InlineData("SetSuppression2")]
    [InlineData("SetSuppression")]
    [InlineData("ForceRebuildAll")]
    [InlineData("AccessSelections")]
    [InlineData("EditRollback")]
    [InlineData("SetSaveFlag")]
    public void Assert_DeniedMember_Throws(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
        Assert.Equal(member, error.MemberName);
        Assert.Contains(member, error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("FeatureCut4")]
    [InlineData("FeatureCutThin")]
    [InlineData("FeatureExtrusion3")]
    [InlineData("FeatureExtrusionThin2")]
    [InlineData("InsertFeature")]
    [InlineData("InsertFeatureChamfer")]
    [InlineData("SetSystemValue")]
    [InlineData("SetSystemValues")]
    public void Assert_DeniedFamilyPrefix_Throws(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
    }

    [Theory]
    [InlineData("GetPersistReference3")]
    [InlineData("GetObjectByPersistReference3")]
    [InlineData("GetChildren")]
    [InlineData("GetSuppression2")]
    [InlineData("GetAll3")]
    [InlineData("InterferenceDetectionManager")]
    [InlineData("ViewZoomToSelection")]
    [InlineData("SelectByID2")]
    [InlineData("SaveBMP")]
    public void Assert_AllowedMember_Passes(string member)
    {
        ReadOnlyGuard.Assert(member);
    }

    [Fact]
    public void Assert_IsCaseInsensitive()
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("save3"));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("FEATURECUT4"));
    }

    /// <summary>
    /// Feature 011 review (2026-09-23): an interface-qualified key is judged by its member half,
    /// so a read-only gate refuses <c>IDrawingDoc.ActivateSheet</c> exactly as it refuses
    /// <c>ActivateSheet</c>. Only the allowlist guards (<see cref="RemodelGuard"/>,
    /// <see cref="DrawingOpenGuard"/> and, since decision 144A, <see cref="RemodelSeatGuard"/>, which
    /// accepts <c>ISldWorks.ActivateDoc3</c> below) accept a qualified writer key, and they judge it
    /// before this guard is asked; a qualified key on a read-only gate had passed whatever it named.
    /// </summary>
    [Theory]
    [InlineData("IDrawingDoc.ActivateSheet")]
    [InlineData("IModelDoc2.Save3")]
    [InlineData("IModelDoc2.ForceRebuild3")]
    [InlineData("IModelDoc2.FeatureCut4")]
    [InlineData("ISldWorks.ActivateDoc3")]
    [InlineData("IView.SetDisplayMode4")]
    public void Assert_QualifiedKeyOfADeniedMember_Throws_NamingTheKey(string key)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(key));
        Assert.Equal(key, error.MemberName);
        Assert.Contains(key, error.Message, StringComparison.Ordinal);
        Assert.Throws<MutatingCallError>(() => ReadOnlyCallGuard.Instance.Assert(key));
        Assert.Throws<MutatingCallError>(() => new SwReview.Extractor.Sw.SwGate(new CircuitBreaker()).Call(key, () => 0));
    }

    [Theory]
    [InlineData("Feature.Name")]
    [InlineData("Component.Select4")]
    [InlineData("IDrawingDoc.GetViews")]
    [InlineData("EquationMgr.Equation")]
    [InlineData("drawing.read")]
    public void Assert_QualifiedKeyOfARead_Passes(string key)
    {
        ReadOnlyGuard.Assert(key);
        ReadOnlyCallGuard.Instance.Assert(key);
    }

    /// <summary>
    /// The deliberate exclusions of contracts/guard.md section 3 stay exclusions whatever their
    /// spelling: <c>OpenDoc6</c> is the extractor's read-only open of a model and <c>CloseDoc</c> the
    /// bare name of feature 004's stage-1 key. What keeps a read path from closing a document is
    /// that no read call site names it; the confirmed drawing's close goes through
    /// <see cref="DrawingOpenGuard"/>'s allowlist.
    /// </summary>
    [Theory]
    [InlineData("ISldWorks.OpenDoc6")]
    [InlineData("ISldWorks.CloseDoc")]
    public void Assert_QualifiedKeyOfAnExcludedMember_PassesAsItsBareNameDoes(string key)
    {
        ReadOnlyGuard.Assert(key);
        ReadOnlyGuard.Assert(CallKey.BareName(key));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void Assert_MissingMemberName_Throws(string? member)
    {
        Assert.Throws<ArgumentException>(() => ReadOnlyGuard.Assert(member!));
    }

    [Theory]
    [InlineData(@"C:\runs\captures\cmp-0012.png")]
    [InlineData(@"C:\runs\captures\cmp-0012.PNG")]
    [InlineData(@"C:\runs\captures\view.bmp")]
    [InlineData(@"C:\runs\captures\view.jpg")]
    public void AssertSaveAs_ImageExtension_Passes(string path)
    {
        ReadOnlyGuard.AssertSaveAs(path);
    }

    [Theory]
    [InlineData(@"C:\vault\bracket.sldprt")]
    [InlineData(@"C:\vault\bracket.SLDASM")]
    [InlineData(@"C:\vault\bracket.slddrw")]
    [InlineData(@"C:\vault\bracket.step")]
    [InlineData(@"C:\vault\bracket")]
    public void AssertSaveAs_ModelExtension_Throws(string path)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.AssertSaveAs(path));
        Assert.Equal("SaveAs3", error.MemberName);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void AssertSaveAs_MissingPath_Throws(string? path)
    {
        Assert.Throws<ArgumentException>(() => ReadOnlyGuard.AssertSaveAs(path!));
    }
}

/// <summary>
/// T048. The instance form of the read-only guard: the seam <see cref="SwReview.Extractor.Sw.SwGate"/>
/// consults, and the default every gate gets. It must answer exactly as the static guard does.
/// </summary>
public class ReadOnlyCallGuardTests
{
    [Theory]
    [InlineData("ForceRebuild3")]
    [InlineData("SetSuppression2")]
    [InlineData("SetSaveFlag")]
    [InlineData("FeatureCut4")]
    public void Assert_DeniedMember_ThrowsLikeTheStaticGuard(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(
            () => ReadOnlyCallGuard.Instance.Assert(member));

        Assert.Equal(member, error.MemberName);
    }

    [Theory]
    [InlineData("GetChildren")]
    [InlineData("GetSuppression2")]
    [InlineData("GetSaveFlag")]
    public void Assert_AllowedMember_Passes(string member)
    {
        ReadOnlyCallGuard.Instance.Assert(member);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void Assert_MissingMemberName_Throws(string? member)
    {
        Assert.Throws<ArgumentException>(() => ReadOnlyCallGuard.Instance.Assert(member!));
    }
}

/// <summary>
/// T022. Three consecutive COM failures stop the bridge; the review then reports failed
/// coverage instead of retrying into a hung SOLIDWORKS session (research R4).
/// </summary>
public class CircuitBreakerTests
{
    private static COMException ComFailure() => new COMException("RPC_E_DISCONNECTED");

    [Fact]
    public void Execute_Success_ReturnsValueAndKeepsCircuitClosed()
    {
        var breaker = new CircuitBreaker();

        int result = breaker.Execute(() => 42);

        Assert.Equal(42, result);
        Assert.False(breaker.IsOpen);
        Assert.Equal(0, breaker.ConsecutiveFailures);
    }

    [Fact]
    public void Execute_TwoFailures_KeepsCircuitClosed()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));
        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));

        Assert.False(breaker.IsOpen);
        Assert.Equal(2, breaker.ConsecutiveFailures);
    }

    [Fact]
    public void Execute_ThirdFailure_OpensCircuitAndStillReportsTheOriginalError()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));
        Assert.Throws<InvalidOperationException>(
            () => breaker.Execute<int>(() => throw new InvalidOperationException("stale pointer")));
        Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));

        Assert.True(breaker.IsOpen);
        Assert.Equal(3, breaker.ConsecutiveFailures);
    }

    [Fact]
    public void Execute_WhenOpen_ThrowsCircuitOpenErrorWithoutCallingTheOperation()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 3);

        bool called = false;
        Assert.Throws<CircuitOpenError>(() => breaker.Execute(() =>
        {
            called = true;
            return 1;
        }));

        Assert.False(called);
    }

    [Fact]
    public void Execute_WhenOpen_StaysOpenForFurtherCalls()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 3);

        Assert.Throws<CircuitOpenError>(() => breaker.Execute(() => 1));
        Assert.Throws<CircuitOpenError>(() => breaker.Execute(() => 2));
        Assert.True(breaker.IsOpen);
    }

    [Fact]
    public void Reset_ClosesTheCircuitAndClearsTheCount()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 3);

        breaker.Reset();

        Assert.False(breaker.IsOpen);
        Assert.Equal(0, breaker.ConsecutiveFailures);
        Assert.Equal(7, breaker.Execute(() => 7));
    }

    [Fact]
    public void Execute_SuccessAfterFailures_ClearsTheCount()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 2);

        Assert.Equal(1, breaker.Execute(() => 1));
        Assert.Equal(0, breaker.ConsecutiveFailures);

        FailTimes(breaker, 2);
        Assert.False(breaker.IsOpen);
    }

    // ---- ExecuteOptional (feature 010) ---------------------------------------------
    //
    // An optional read is one whose failure the caller records as a gap on that one value -
    // a Hole Wizard field, a dimension's tolerance. SOLIDWORKS may refuse such a property for
    // one hole type on every hole of that type, and three of those in a row must not end the
    // dump as a dead session would; a dead session still opens the circuit on the next
    // counted call.

    [Fact]
    public void ExecuteOptional_Failure_IsRethrownAndNotCounted()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 2);

        for (int i = 0; i < 5; i++)
        {
            Assert.Throws<COMException>(() => breaker.ExecuteOptional<int>(() => throw ComFailure()));
            Assert.Throws<InvalidOperationException>(
                () => breaker.ExecuteOptional<int>(() => throw new InvalidOperationException("not for this type")));
        }

        Assert.Equal(2, breaker.ConsecutiveFailures);
        Assert.False(breaker.IsOpen);
    }

    [Fact]
    public void ExecuteOptional_Success_ClearsTheCountBecauseTheSessionAnswered()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 2);

        Assert.Equal(5, breaker.ExecuteOptional(() => 5));
        Assert.Equal(0, breaker.ConsecutiveFailures);
    }

    [Fact]
    public void ExecuteOptional_WhenOpen_ThrowsCircuitOpenErrorWithoutCallingTheOperation()
    {
        var breaker = new CircuitBreaker();
        FailTimes(breaker, 3);

        bool called = false;
        Assert.Throws<CircuitOpenError>(() => breaker.ExecuteOptional(() =>
        {
            called = true;
            return 1;
        }));

        Assert.False(called);
        Assert.True(breaker.IsOpen);
    }

    [Fact]
    public void ExecuteOptional_NullOperation_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new CircuitBreaker().ExecuteOptional<int>(null!));
    }

    [Fact]
    public void Execute_UnexpectedExceptionType_PropagatesWithoutCountingAsAComFailure()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<ArgumentOutOfRangeException>(
            () => breaker.Execute<int>(() => throw new ArgumentOutOfRangeException("id")));

        Assert.Equal(0, breaker.ConsecutiveFailures);
        Assert.False(breaker.IsOpen);
    }

    [Fact]
    public void Execute_NullOperation_Throws()
    {
        var breaker = new CircuitBreaker();

        Assert.Throws<ArgumentNullException>(() => breaker.Execute<int>(null!));
    }

    private static void FailTimes(CircuitBreaker breaker, int times)
    {
        for (int i = 0; i < times; i++)
        {
            Assert.Throws<COMException>(() => breaker.Execute<int>(() => throw ComFailure()));
        }
    }
}

/// <summary>
/// Reads a denylist table out of a spec document the csproj copies next to this assembly, the
/// way <c>ir.schema.json</c> is copied: the spec is read, never transcribed. The members are the
/// backticked names of the first cell, interface qualifier dropped exactly as
/// <c>SwGate.Call</c> drops it; the second cell is kept verbatim. Feature 006's R8 table and
/// feature 010's table in <c>guard-allowlist.md</c> are read by this one parser.
///
/// Every failure is loud and names the document, because a parser that silently returned
/// nothing would make every theory over the table vacuous.
/// </summary>
internal static class DenylistTable
{
    private static readonly Regex BacktickedName = new Regex("`([^`]+)`", RegexOptions.Compiled);

    public static IReadOnlyList<(string Family, string[] Members)> Parse(
        string fileName, string documentName, string tableHeader, int minimumRows, bool keepQualifier = false)
    {
        string path = Path.Combine(AppContext.BaseDirectory, fileName);
        Assert.True(
            File.Exists(path),
            $"{fileName} was not copied next to the test assembly; check the Content "
                + "item in SwReview.Extractor.Tests.csproj.");

        string[] lines = File.ReadAllLines(path);
        int header = Array.FindIndex(
            lines, line => line.Trim().StartsWith(tableHeader, StringComparison.Ordinal));
        Assert.True(
            header >= 0,
            $"{documentName} no longer carries the header '{tableHeader}'; this parser reads "
                + "that table and cannot find it.");
        Assert.True(
            header + 1 < lines.Length && lines[header + 1].Trim().StartsWith("|---", StringComparison.Ordinal),
            $"The table in {documentName} has no separator row under its header: "
                + (header + 1 < lines.Length ? lines[header + 1] : "<end of file>"));

        var rows = new List<(string Family, string[] Members)>();
        for (int index = header + 2; index < lines.Length; index++)
        {
            string line = lines[index].Trim();
            if (!line.StartsWith("|", StringComparison.Ordinal))
            {
                break;
            }

            string[] cells = line.Trim('|').Split('|');
            Assert.True(cells.Length == 2, $"Row '{line}' of {documentName} does not have two cells.");

            string[] members = BacktickedName.Matches(cells[0])
                .Cast<Match>()
                .Select(match => match.Groups[1].Value.Trim())
                .Select(name => keepQualifier ? name : name.Substring(name.LastIndexOf('.') + 1))
                .ToArray();
            Assert.True(
                members.Length > 0,
                $"Row '{line}' of {documentName} names no member in backticks; this parser reads "
                    + "them from there.");

            rows.Add((cells[1].Trim(), members));
        }

        // A floor, not the count: it catches a parse that read the header and then nothing,
        // without putting a number beside the table that would have to be kept in step with it.
        Assert.True(
            rows.Count >= minimumRows,
            $"The table in {documentName} parsed as only {rows.Count} rows; the guard test would "
                + "be nearly vacuous. Check the table's shape.");
        return rows;
    }
}

/// <summary>
/// T019. The members feature 006's two new phases put beside the reads they perform: sheet and
/// view activation, exploded-state writes, visibility and appearance writes, table-cell and
/// revision writes, cut-list writes, mass overrides, dimension and note writes, annotation
/// renaming and the cut-list exclusion flag.
///
/// <b>research.md R8's table is the count, and this class reads it.</b> No test here states how
/// many members there are and none transcribes them: <see cref="Table"/> is parsed out of
/// `specs/006-standards-check/research.md`, which the csproj copies next to this assembly the
/// way `ir.schema.json` is copied, so a row added to R8 and not to
/// <see cref="ReadOnlyGuard"/> is a red test rather than a member nobody gated. <c>SetText</c> -
/// which R8 lists twice, for <c>IDisplayDimension</c> and for <c>INote</c> - is one entry,
/// because <see cref="ReadOnlyGuard"/> matches bare names.
///
/// None of these is called by this feature. Adding them is a <b>narrowing</b> of the call
/// surface, so no constitution exception arises, and the one side effect the release-checklist
/// macro had - activating a sheet in order to read it - is refused rather than avoided by
/// convention (FR-044, quickstart gate 8).
/// </summary>
public class StandardsDenylistTests
{
    /// <summary>One row of research.md R8's table: the members it guards, and what it guards them for.</summary>
    public sealed class R8Row
    {
        public R8Row(string family, string[] members)
        {
            Family = family;
            Members = members;
        }

        /// <summary>The "family it guards" column, verbatim.</summary>
        public string Family { get; }

        /// <summary>
        /// The bare member names of the "Member" column. R8 writes them interface-qualified for
        /// the reader ("IDrawingDoc.ActivateSheet"); the guard entry is the bare name, so the
        /// qualifier is dropped here exactly as `ReadOnlyGuard.Assert` judges a qualified key by
        /// its member half.
        /// </summary>
        public string[] Members { get; }
    }

    /// <summary>
    /// The file the csproj copies next to this assembly, as it copies the IR schema: the spec
    /// is read, never transcribed.
    /// </summary>
    private const string ResearchFileName = "standards-research.md";

    /// <summary>The header row of R8's table, which is where the parse starts.</summary>
    private const string TableHeader = "| Member | The family it guards |";

    /// <summary>research.md R8's table, parsed. Adding a row there is what grows the set below.</summary>
    public static readonly R8Row[] Table = DenylistTable
        .Parse(ResearchFileName, "specs/006-standards-check/research.md R8", TableHeader, minimumRows: 10)
        .Select(row => new R8Row(row.Family, row.Members))
        .ToArray();

    /// <summary>
    /// The distinct bare names <see cref="Table"/> holds - the expected set, derived rather
    /// than typed out a second time.
    /// </summary>
    public static IReadOnlyCollection<string> ExpectedMembers =>
        new HashSet<string>(
            Table.SelectMany(row => row.Members), StringComparer.OrdinalIgnoreCase);

    public static IEnumerable<object[]> EveryMember() =>
        ExpectedMembers.OrderBy(member => member, StringComparer.Ordinal)
            .Select(member => new object[] { member });

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheR8TableIsRefused(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
        Assert.Equal(member, error.MemberName);
    }

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheR8TableIsRefusedByTheInstanceGuardToo(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyCallGuard.Instance.Assert(member));
    }

    /// <summary>
    /// <c>SwGate.Call</c> names members however the call site spelled them, so a refusal cannot
    /// depend on case.
    /// </summary>
    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheR8TableIsRefusedWhateverItsCase(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToUpperInvariant()));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToLowerInvariant()));
    }

    /// <summary>
    /// The expected set is the table's membership, never a count typed beside it:
    /// <c>SetText</c> is on two rows and is one entry, and a row added to R8 without being
    /// copied here would otherwise be invisible.
    /// </summary>
    [Fact]
    public void TheExpectedSetIsTheTablesDistinctMembershipWithSetTextCountedOnce()
    {
        Assert.Equal(
            Table.SelectMany(row => row.Members).Distinct(StringComparer.OrdinalIgnoreCase).Count(),
            ExpectedMembers.Count);

        Assert.Equal(
            2,
            Table.Count(row => row.Members.Contains("SetText", StringComparer.OrdinalIgnoreCase)));
        Assert.Single(
            ExpectedMembers,
            member => string.Equals(member, "SetText", StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>
    /// The reads the two new phases actually perform stay allowed. A denylist that swallowed
    /// the getter beside the setter would fail closed on the evidence the checks are graded on.
    /// </summary>
    [Theory]
    [InlineData("GetOverride")]
    [InlineData("GetOverrideValue")]
    [InlineData("GetSystemValue3")]
    [InlineData("GetText")]
    [InlineData("GetName")]
    [InlineData("GetName2")]
    [InlineData("ExcludeFromCutList")]
    [InlineData("GetVisibility")]
    [InlineData("GetViews")]
    [InlineData("GetCutListItems")]
    [InlineData("OverrideMass")]
    public void TheReadsBesideThemAreStillAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
    }

    /// <summary>
    /// The suppress-test gate is exempted from exactly two members, and this feature adds no
    /// third: every member R8 adds is refused there as well.
    /// </summary>
    [Theory]
    [MemberData(nameof(EveryMember))]
    public void TheSuppressTestGateIsExemptedFromNoneOfThem(string member)
    {
        Assert.Throws<MutatingCallError>(() => new SuppressTestGuard().Assert(member));
    }

    /// <summary>
    /// <c>ForceRebuild3</c> and <c>ForceRebuildAll</c> were denied before this feature and stay
    /// denied, with the one pre-existing exemption unchanged (FR-044).
    /// </summary>
    [Fact]
    public void ForceRebuildStaysDeniedAndItsOnlyExemptionIsTheSuppressTestGate()
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("ForceRebuild3"));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert("ForceRebuildAll"));

        var gate = new SuppressTestGuard();
        gate.Assert("ForceRebuild3");
        Assert.Throws<MutatingCallError>(() => gate.Assert("ForceRebuildAll"));
    }
}

/// <summary>
/// Feature 010 T086. The setters beside every value the Hole Wizard and <c>tolerance</c> reads
/// take: the dimension tolerance, the GTol frames, the datum label, the annotation's attachment
/// and the Hole Wizard data (<c>010-mechanical-checks/contracts/tolerances.md</c> section 2).
///
/// <b>The table in <c>004-resilient-remodeler/contracts/guard-allowlist.md</c> is the
/// membership, and this class reads it</b>, exactly as <see cref="StandardsDenylistTests"/>
/// reads R8: a row added there and not to <see cref="ReadOnlyGuard"/> is a red test. None of
/// these is called; adding them is a narrowing, so no constitution exception arises.
/// </summary>
public class MechanicalChecksDenylistTests
{
    private const string AllowlistFileName = "guard-allowlist.md";

    private const string TableHeader = "| Member (feature 010) | The read it sits beside |";

    /// <summary>The feature 010 table of guard-allowlist.md, parsed.</summary>
    public static readonly IReadOnlyList<(string Family, string[] Members)> Table = DenylistTable.Parse(
        AllowlistFileName,
        "specs/004-resilient-remodeler/contracts/guard-allowlist.md (feature 010)",
        TableHeader,
        minimumRows: 15);

    /// <summary>The distinct bare names the table holds: the expected set, derived.</summary>
    public static IReadOnlyCollection<string> ExpectedMembers =>
        new HashSet<string>(Table.SelectMany(row => row.Members), StringComparer.OrdinalIgnoreCase);

    public static IEnumerable<object[]> EveryMember() =>
        ExpectedMembers.OrderBy(member => member, StringComparer.Ordinal)
            .Select(member => new object[] { member });

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheTableIsRefused(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
        Assert.Equal(member, error.MemberName);
        Assert.Throws<MutatingCallError>(() => ReadOnlyCallGuard.Instance.Assert(member));
    }

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheTableIsRefusedWhateverItsCase(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToUpperInvariant()));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToLowerInvariant()));
    }

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void TheSuppressTestGateIsExemptedFromNoneOfThem(string member)
    {
        Assert.Throws<MutatingCallError>(() => new SuppressTestGuard().Assert(member));
    }

    /// <summary>
    /// Every setter the contract names is on the table, <c>set_*Diameter</c>, <c>set_*Depth</c>
    /// and <c>set_*Angle</c> included through the members beside the reads this feature makes.
    /// </summary>
    [Theory]
    [InlineData("SetToleranceValues")]
    [InlineData("SetToleranceType")]
    [InlineData("SetToleranceFitValues")]
    [InlineData("SetFitValues")]
    [InlineData("SetValues2")]
    [InlineData("set_Type")]
    [InlineData("SetFrameValues")]
    [InlineData("SetFrameSymbols")]
    [InlineData("SetDatumIdentifier")]
    [InlineData("SetLabel")]
    [InlineData("set_HoleFit")]
    [InlineData("set_ThreadClass")]
    [InlineData("set_ThruHoleDiameter")]
    [InlineData("set_TapDrillDiameter")]
    [InlineData("set_CounterBoreDiameter")]
    [InlineData("set_CounterBoreDepth")]
    [InlineData("set_CounterSinkDiameter")]
    [InlineData("set_CounterSinkAngle")]
    [InlineData("set_HeadClearance")]
    [InlineData("SetSymbolXml")]
    [InlineData("SetAttachedEntities")]
    public void EverySetterTheContractNamesIsOnTheTable(string member)
    {
        Assert.Contains(member, ExpectedMembers, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>
    /// The reads the Hole Wizard, <c>tolerance</c> and mass-override paths make stay allowed,
    /// spelled as their call sites name them to the gate. A denylist that swallowed the getter
    /// beside the setter would fail closed on the evidence the checks are graded on.
    /// </summary>
    [Theory]
    [InlineData("WizardHole.Type")]
    [InlineData("WizardHole.EndCondition")]
    [InlineData("WizardHole.Diameter")]
    [InlineData("FastenerSize")]
    [InlineData("HoleDepth")]
    [InlineData("ThreadDepth")]
    [InlineData("ThreadEndCondition")]
    [InlineData("HoleFit")]
    [InlineData("ThreadClass")]
    [InlineData("ThruHoleDiameter")]
    [InlineData("TapDrillDiameter")]
    [InlineData("CounterBoreDiameter")]
    [InlineData("CounterBoreDepth")]
    [InlineData("CounterSinkDiameter")]
    [InlineData("CounterSinkAngle")]
    [InlineData("HeadClearance")]
    [InlineData("GetFirstDisplayDimension")]
    [InlineData("GetNextDisplayDimension")]
    [InlineData("GetDimension2")]
    [InlineData("Type2")]
    [InlineData("FullName")]
    [InlineData("GetSystemValue3")]
    [InlineData("Tolerance")]
    [InlineData("DimensionTolerance.Type")]
    [InlineData("GetMinValue2")]
    [InlineData("GetMaxValue2")]
    [InlineData("GetHoleFitValue")]
    [InlineData("GetShaftFitValue")]
    [InlineData("GetAnnotations")]
    [InlineData("Annotation.GetType")]
    [InlineData("GetSpecificAnnotation")]
    [InlineData("IsDimXpert")]
    [InlineData("GetFrameCount")]
    [InlineData("GetFrameValues")]
    [InlineData("GetFrameSymbols3")]
    [InlineData("GetFrame")]
    [InlineData("GetSymbolXml")]
    [InlineData("GetDatumIdentifier")]
    [InlineData("GetLabel")]
    [InlineData("GetAttachedEntities3")]
    [InlineData("GetPersistReference3")]
    [InlineData("CreateMassProperty")]
    [InlineData("GetOverrideOptions")]
    [InlineData("OverrideMass")]
    public void TheReadsBesideThemAreStillAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
    }

    [Fact]
    public void TheTableAddsNothingFeature006AlreadyDenied()
    {
        // Two tables, two memberships: a name on both would be counted twice by the reader of
        // guard-allowlist.md and would hide which feature a denial belongs to.
        Assert.Empty(ExpectedMembers.Intersect(
            StandardsDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase));
    }

    [Fact]
    public void NoMemberOfTheTableIsTheBareNameOfAStage1AllowlistKey()
    {
        // The re-modeler's allowlist is asserted against the read-only denied surface; a
        // feature 010 denial that shared a stage-1 key's bare name would change the set of
        // keys that override a denial.
        var bareKeys = new HashSet<string>(
            RemodelGuard.AllowedKeys.Select(CallKey.BareName), StringComparer.OrdinalIgnoreCase);

        Assert.DoesNotContain(ExpectedMembers, bareKeys.Contains);
    }
}

/// <summary>
/// Feature 011 T003. Every writer of the 28 drawing families and the named members of the two
/// shared families (<c>011-drawing-context/contracts/guard.md</c>), refused before any new drawing
/// read lands (FR-005, SC-009).
///
/// <b>The "Feature 011" table of <c>004-resilient-remodeler/contracts/guard-allowlist.md</c> is the
/// membership, and this class reads it</b>, as <see cref="MechanicalChecksDenylistTests"/> reads
/// feature 010's. That table is generated by <c>extractor/tools/list-writer-members.ps1</c> from the
/// interop and never typed; <see cref="DrawingFamilyCompletenessTests"/> reflects the same interop
/// at test time to prove the table complete. None of these members is called.
/// </summary>
public class DrawingFamilyDenylistTests
{
    private const string AllowlistFileName = "guard-allowlist.md";

    /// <summary>The header of the generated denial table.</summary>
    internal const string TableHeader = "| Members refused (feature 011) | Interface; already denied |";

    /// <summary>The header of the generated table of names the section deliberately does not deny.</summary>
    internal const string ExclusionHeader = "| Not denied (feature 011) | Why |";

    /// <summary>The feature 011 table, parsed: one row per interface with a new denial.</summary>
    public static readonly IReadOnlyList<(string Family, string[] Members)> Table = DenylistTable.Parse(
        AllowlistFileName,
        "specs/004-resilient-remodeler/contracts/guard-allowlist.md (feature 011)",
        TableHeader,
        minimumRows: 15);

    /// <summary>The names a writer grammar or a shared row matched and the section leaves allowed.</summary>
    public static readonly IReadOnlyList<(string Family, string[] Members)> Exclusions = DenylistTable.Parse(
        AllowlistFileName,
        "specs/004-resilient-remodeler/contracts/guard-allowlist.md (feature 011 exclusions)",
        ExclusionHeader,
        minimumRows: 2);

    /// <summary>The distinct bare names the table denies: the expected set, derived.</summary>
    public static IReadOnlyCollection<string> ExpectedMembers =>
        new HashSet<string>(Table.SelectMany(row => row.Members), StringComparer.OrdinalIgnoreCase);

    /// <summary>The distinct bare names the exclusion table leaves allowed.</summary>
    public static IReadOnlyCollection<string> ExcludedMembers =>
        new HashSet<string>(Exclusions.SelectMany(row => row.Members), StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// The interface a row is for: the first backticked name of its second cell, which the
    /// generator writes as "`IDrawingDoc`; already denied: ...".
    /// </summary>
    internal static string InterfaceOf((string Family, string[] Members) row)
    {
        Match match = Regex.Match(row.Family, "^`([^`]+)`");
        Assert.True(match.Success, $"Row for '{row.Family}' does not start with its interface in backticks.");
        return match.Groups[1].Value;
    }

    public static IEnumerable<object[]> EveryMember() =>
        ExpectedMembers.OrderBy(member => member, StringComparer.Ordinal)
            .Select(member => new object[] { member });

    public static IEnumerable<object[]> EveryQualifiedMember() =>
        Table.SelectMany(row => row.Members.Select(member => InterfaceOf(row) + "." + member))
            .Distinct(StringComparer.Ordinal)
            .OrderBy(key => key, StringComparer.Ordinal)
            .Select(key => new object[] { key });

    /// <summary>FR-005 and SC-009 in every spelling a call site could use: bare, or qualified with
    /// the interface the table names (feature 011 review, 2026-09-23).</summary>
    [Theory]
    [MemberData(nameof(EveryQualifiedMember))]
    public void EveryMemberOfTheTableIsRefusedQualifiedWithItsInterface(string key)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(key));
        Assert.Equal(key, error.MemberName);
        Assert.Throws<MutatingCallError>(() => ReadOnlyCallGuard.Instance.Assert(key));
    }

    public static IEnumerable<object[]> EveryExcludedMember() =>
        ExcludedMembers.OrderBy(member => member, StringComparer.Ordinal)
            .Select(member => new object[] { member });

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheTableIsRefused(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
        Assert.Equal(member, error.MemberName);
        Assert.Throws<MutatingCallError>(() => ReadOnlyCallGuard.Instance.Assert(member));
    }

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheTableIsRefusedWhateverItsCase(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToUpperInvariant()));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToLowerInvariant()));
    }

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void TheSuppressTestGateIsExemptedFromNoneOfThem(string member)
    {
        Assert.Throws<MutatingCallError>(() => new SuppressTestGuard().Assert(member));
    }

    /// <summary>
    /// The table lists only what is new; what an earlier feature (or a denied prefix) refuses sits
    /// in its "already denied" column, so no feature's denial is counted twice.
    /// </summary>
    [Fact]
    public void TheTableAddsNothingAnEarlierFeatureAlreadyDenied()
    {
        Assert.Empty(ExpectedMembers.Intersect(StandardsDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase));
        Assert.Empty(ExpectedMembers.Intersect(MechanicalChecksDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase));
        Assert.DoesNotContain(
            ExpectedMembers,
            member => ReadOnlyGuard.DeniedPrefixes.Any(
                prefix => member.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)));
    }

    /// <summary>
    /// Feature 004's allowlist is asserted against the read-only denied surface; a feature 011
    /// denial that shared a stage-1 key's bare name would change the keys that override a denial
    /// (<c>Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive</c>).
    /// </summary>
    [Fact]
    public void NoMemberOfTheTableIsTheBareNameOfAStage1AllowlistKey()
    {
        var bareKeys = new HashSet<string>(
            RemodelGuard.AllowedKeys.Select(CallKey.BareName), StringComparer.OrdinalIgnoreCase);

        Assert.DoesNotContain(ExpectedMembers, bareKeys.Contains);
    }

    /// <summary>
    /// <see cref="RemodelGuard.ExcludedMembers"/> are the members the re-modeler refuses itself
    /// because <see cref="ReadOnlyGuard"/> does not; a feature 011 denial of one would make that
    /// list redundant, which its own test forbids.
    /// </summary>
    [Fact]
    public void NoMemberOfTheTableIsOneTheRemodelGuardRefusesItself()
    {
        Assert.Empty(ExpectedMembers.Intersect(RemodelGuard.ExcludedMembers, StringComparer.OrdinalIgnoreCase));
    }

    /// <summary>A name the section leaves allowed is really allowed, and is not also on the table.</summary>
    [Theory]
    [MemberData(nameof(EveryExcludedMember))]
    public void EveryExcludedNameStaysAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
        Assert.DoesNotContain(member, ExpectedMembers, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Every exclusion has one of contracts/guard.md section 3's reasons: the bare name of a
    /// stage-1 allowlist key, a member <see cref="RemodelGuard"/> refuses itself, or a member a
    /// sanctioned path already calls by its bare name - the extractor's read-only model open and
    /// feature 004's opens of the copy and of the throwaway part (found by the read audit, T003),
    /// and, since decision 140A refused the save family, the capture's image, <c>SaveBMP</c>. Edited
    /// deliberately for decision 136A (2026-10-19), which accepted one exclusion more, <c>Close</c>,
    /// the member half of the bridge command <c>remodel.close</c> while the dispatcher handed command
    /// names to the read-only guard; and narrowed back for decision 140A the same day, when the
    /// dispatcher stopped doing so: a bridge command's member half is no reason at all now. Narrowed
    /// again for decision 144A the same day: <c>NewDocument</c> and <c>MoveToFolder</c>, which only
    /// <c>probe remodel</c> calls, are no exclusions now - the read-only guard refuses them and only the
    /// probe's own guard lets them through (<see cref="TheProbesTwoWritersAreRefusedByEveryGateButTheProbesOwnBare"/>).
    /// </summary>
    [Fact]
    public void EveryExclusionHasOneOfTheContractsReasons()
    {
        var sanctionedCalls = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "OpenDoc6",
            "OpenDoc7",
            "SaveBMP",
        };
        var bareKeys = new HashSet<string>(
            RemodelGuard.AllowedKeys.Select(CallKey.BareName), StringComparer.OrdinalIgnoreCase);

        foreach (string member in ExcludedMembers)
        {
            Assert.True(
                bareKeys.Contains(member)
                    || RemodelGuard.ExcludedMembers.Contains(member, StringComparer.OrdinalIgnoreCase)
                    || sanctionedCalls.Contains(member),
                $"{member} is excluded from the feature 011 denials without a reason contracts/guard.md "
                    + "section 3 gives.");
        }
    }

    /// <summary>
    /// The sanctioned calls stay allowed whether or not a grammar reached them: the extractor's
    /// read-only model open, feature 004's opens of the copy and of the throwaway part, the shared
    /// names feature 004's allowlist keys carry, and (decision 140A) the capture's image. Edited
    /// deliberately for decision 144A (2026-10-19): <c>NewDocument</c> and <c>MoveToFolder</c> left
    /// this list for <see cref="TheProbesTwoWritersAreRefusedByEveryGateButTheProbesOwnBare"/>, which
    /// asserts they are refused, and let through only where the decision says.
    /// </summary>
    [Theory]
    [InlineData("OpenDoc6")]
    [InlineData("OpenDoc7")]
    [InlineData("SaveBMP")]
    [InlineData("CloseDoc")]
    [InlineData("SetUserPreferenceToggle")]
    [InlineData("set_Name")]
    [InlineData("Select2")]
    public void TheSanctionedCallsStayAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
    }

    /// <summary>
    /// Decision 144A (2026-10-19; research R10.4 item 5): <c>probe remodel</c>'s two writers that the
    /// read-only guard left allowed - <c>ISldWorks.NewDocument</c>, which creates the throwaway part,
    /// and <c>IFeatureManager.MoveToFolder</c>, PROBE-5's move into a folder - are refused by it in both
    /// spellings, and so by every gate the product builds, but for <see cref="RemodelProbeGuard"/>, which
    /// lets the bare name its host gates through and nothing else: its run-scoped members, as
    /// <c>ForceRebuild3</c> and <c>SaveAs3</c> are.
    /// </summary>
    [Theory]
    [InlineData("ISldWorks.NewDocument")]
    [InlineData("IFeatureManager.MoveToFolder")]
    public void TheProbesTwoWritersAreRefusedByEveryGateButTheProbesOwnBare(string key)
    {
        string member = CallKey.BareName(key);
        Assert.Contains(member, ExpectedMembers, StringComparer.OrdinalIgnoreCase);
        Assert.DoesNotContain(member, ExcludedMembers, StringComparer.OrdinalIgnoreCase);

        foreach (ICallGuard gate in GuardSweep.ProductGates())
        {
            Assert.Throws<MutatingCallError>(() => gate.Assert(key));
            if (gate is RemodelProbeGuard)
            {
                gate.Assert(member);
            }
            else
            {
                Assert.Throws<MutatingCallError>(() => gate.Assert(member));
            }
        }
    }

    /// <summary>
    /// The reads feature 011 performs stay allowed, spelled as their call sites name them to the
    /// gate. A denylist that swallowed the getter beside the setter would fail closed on the
    /// evidence the drawing checks read.
    /// </summary>
    [Theory]
    [InlineData("GetDocuments")]
    [InlineData("GetDocumentCount")]
    [InlineData("GetType")]
    [InlineData("GetPathName")]
    [InlineData("GetOpenDocumentByName")]
    [InlineData("GetViews")]
    [InlineData("GetReferencedModelName")]
    [InlineData("IsDetailingMode")]
    [InlineData("GetUserPreferenceInteger")]
    [InlineData("GetUserPreferenceString")]
    [InlineData("GetTemplateName")]
    [InlineData("GetProperties2")]
    [InlineData("GetSheetFormatName")]
    [InlineData("ReferencedConfiguration")]
    [InlineData("IsModelOutOfDate")]
    [InlineData("IsModelLoaded")]
    [InlineData("ScaleDecimal")]
    [InlineData("GetOrientationName")]
    [InlineData("GetCorrespondingEntity")]
    [InlineData("GetCorrespondingEntity2")]
    [InlineData("GetDisplayDimensions")]
    [InlineData("GetTableAnnotations")]
    [InlineData("GetText")]
    [InlineData("GetPrimaryPrecision2")]
    [InlineData("GetPrimaryTolPrecision2")]
    [InlineData("GetUseDocPrecision")]
    [InlineData("GetUnits")]
    [InlineData("GetUseDocUnits")]
    [InlineData("IsReferenceDim")]
    [InlineData("DrivenState")]
    [InlineData("IsHoleCallout")]
    [InlineData("GetHoleCalloutVariables")]
    [InlineData("GetAttachedEntities3")]
    [InlineData("GetTwoAdjacentFaces2")]
    [InlineData("GetSymbol")]
    [InlineData("GetTextCount")]
    [InlineData("GetTextAtIndex")]
    [InlineData("Title")]
    [InlineData("RowCount")]
    [InlineData("ColumnCount")]
    [InlineData("Text")]
    [InlineData("GetModelPathNames")]
    public void TheReadsFeature011PerformsStayAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
    }
}

/// <summary>
/// Feature 011 T003. The table is complete: the 28 drawing families of contracts/guard.md section
/// 1 are reflected on the interop the extractor is built against, the writer grammar of section 2
/// is applied, and every match is refused or is a name the exclusion table states. The shared
/// rows are each declared on their interface and refused.
///
/// The grammar is written here a second time, beside the generator's copy, on purpose: this is the
/// independent check of the generator's output, and a verifier that reused the generator would
/// agree with any mistake the generator made. Both copies cite contracts/guard.md section 2.
/// Only metadata is read; SOLIDWORKS is never started.
/// </summary>
public class DrawingFamilyCompletenessTests
{
    /// <summary>
    /// contracts/guard.md section 1: the 28 drawing families. The last four, the hole callout's
    /// variables, joined on review (2026-09-23): <c>SwDrawingReader.HoleCalloutVariables</c> reads
    /// them (T026), and a family a drawing read touches is a family whose every writer is refused.
    /// </summary>
    internal static readonly string[] DrawingFamilies =
    {
        "IDrawingDoc", "ISheet", "IView", "IDisplayDimension", "IDimension", "IDimensionTolerance",
        "IAnnotation", "INote", "IGtol", "IGtolFrame", "IDatumTag", "ISFSymbol", "ITableAnnotation",
        "IBomTableAnnotation", "IBomFeature", "IRevisionTableAnnotation", "IGeneralTableFeature",
        "ITitleBlockTableFeature", "ITitleBlock", "IDatumTargetSym", "ICenterMark", "IWeldSymbol",
        "IDowelSymbol", "IMultiJogLeader",
        "ICalloutVariable", "ICalloutLengthVariable", "ICalloutAngleVariable", "ICalloutStringVariable",
    };

    /// <summary>
    /// contracts/guard.md section 1: the shared families, named members only. Edited deliberately for
    /// decision 136A (2026-10-19): <c>IModelDoc2</c> joined, for its close, quit, reload and activate
    /// members (<see cref="DocumentLifecycleFamilyTests"/>). Edited deliberately for decision 140A the
    /// same day: <c>IPartDoc</c> and <c>IAssemblyDoc</c> joined, for their save, copy, replace and
    /// rebuild members, and on its review <c>IFeatureManager</c>, for its move members
    /// (<see cref="DocumentWriteFamilyTests"/>).
    /// </summary>
    internal static readonly string[] SharedFamilies =
        { "ISldWorks", "IModelDoc2", "IModelDocExtension", "IPartDoc", "IAssemblyDoc", "IFeatureManager" };

    /// <summary>
    /// contracts/guard.md section 2: a name starting with one of the reader prefixes - <c>get_</c>,
    /// <c>Get</c>, <c>IGet</c>, <c>Is</c> - as a whole word is a reader: the prefix followed by the end
    /// of the name or by anything but a lowercase letter (<c>get_</c> ends a word itself). Edited
    /// deliberately for decision 144A (2026-10-19; research R10.4 item 2): the prefixes were read by
    /// their letters, so <c>Is</c> took in two writers, <c>IDrawingDoc.IsolateChangedDimensions</c> and
    /// <c>IAssemblyDoc.Isolate</c> (<see cref="ReaderLetters"/>, which
    /// <see cref="EveryNameTheReaderPrefixesTookOnlyByTheirLettersIsRefusedByEveryGate"/> reads).
    /// </summary>
    private static readonly Regex ReaderRule = new Regex("^(get_|(Get|IGet|Is)(?![a-z]))", RegexOptions.CultureInvariant);

    /// <summary>The reader prefixes read by their letters alone, as section 2 read them until decision 144A.</summary>
    private static readonly Regex ReaderLetters = new Regex("^(get_|Get|IGet|Is)", RegexOptions.CultureInvariant);

    /// <summary>
    /// contracts/guard.md section 2: the writer grammar. Edited deliberately for decision 144A
    /// (2026-10-19; research R10.4 item 2): the COM twin's <c>I</c> may come before every verb, where it
    /// came before four (<c>ISet</c>, <c>IAdd</c>, <c>IInsert</c>, <c>ICreate</c>) and the twins of
    /// other verbs passed - <c>IDrawingDoc.IEditSelectedGtol</c>, <c>IMakeCustomSymbol2</c>,
    /// <c>INewGtol</c> and <c>IReorderSheets</c>, and <c>IView.ISelectEntity</c>; and <c>Isolate</c>,
    /// the display writer beside <c>Hide</c> and <c>Show</c>, is a verb, which the reader prefix
    /// <c>Is</c> had hidden.
    /// </summary>
    private static readonly Regex WriterGrammar = new Regex(
        "^(set_|I?(Set|Add|Insert|Delete|Remove|Edit|Modify|Change|Reset|Activate|"
            + "Attach|Detach|Update|Replace|Break|Hide|Show|Isolate|Move|Align|Suppress|Unsuppress|Rebuild|"
            + "Convert|Create|Make|Lock|Unlock|Sort|Split|Merge|Rotate|Scale|Flip|Link|Unlink|"
            + "Import|Explode|Clear|Apply|Restore|Save|Dissolve|Expand|Collapse|Reload|Rename|New|Paste|"
            + "Copy|Cut|Drag|Close|Quit|Open|Load|Unload|Regenerate|Reorder|Auto|Dimension|Reverse|Swap|"
            + "Toggle|Enable|Disable|Select|Purge|Relink|Resolve|Crop|Unbreak|Force|Hatch|Offset|"
            + "Position|Freeze|Unfreeze))",
        RegexOptions.CultureInvariant);

    /// <summary>
    /// The installed interop the build references (<c>$(SwRedist)</c>, or <c>SWREVIEW_SW_REDIST</c>),
    /// found and loaded for its metadata by the locator the interop-manifest tests use.
    /// </summary>
    internal static Assembly Interop => RemodelInteropManifestTests.InstalledInterop.Load(
        RemodelInteropManifestTests.InstalledInterop.RedistDirectory()!, "SolidWorks.Interop.sldworks");

    internal static Type InterfaceType(string name)
    {
        Type? type = Interop.GetType("SolidWorks.Interop.sldworks." + name);
        Assert.True(type != null, $"{name} is not on {Interop.GetName().Name} {Interop.GetName().Version}.");
        return type!;
    }

    internal static IEnumerable<string> MethodNames(string interfaceName) =>
        InterfaceType(interfaceName)
            .GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Select(method => method.Name)
            .Distinct(StringComparer.Ordinal);

    /// <summary>contracts/guard.md section 2's reader rule, which decision 21A's creation grammar
    /// applies first as well (<see cref="CreationFamilyCompletenessTests.IsCreation"/>).</summary>
    internal static bool IsReader(string name) => ReaderRule.IsMatch(name);

    internal static bool IsWriter(string name) => !IsReader(name) && WriterGrammar.IsMatch(name);

    /// <summary>
    /// Section 2's grammar, case by case: every verb's COM twin is a writer, and so is
    /// <c>Isolate</c>; a reader prefix is a whole word, so <c>Is</c> starts a reader only where a word
    /// begins after it. The rows marked "(144A)" were wrong before decision 144A: the twins and
    /// <c>Isolate</c> were no writers, and every name a reader prefix starts by its letters only was a
    /// reader.
    /// </summary>
    [Theory]
    [InlineData("IEditSelectedGtol", false, true)] // (144A)
    [InlineData("IMakeCustomSymbol2", false, true)] // (144A)
    [InlineData("INewGtol", false, true)] // (144A)
    [InlineData("IReorderSheets", false, true)] // (144A)
    [InlineData("ISelectEntity", false, true)] // (144A)
    [InlineData("IsolateChangedDimensions", false, true)] // (144A)
    [InlineData("Isolate", false, true)] // (144A)
    [InlineData("ISetXform", false, true)]
    [InlineData("IAddDisplayText", false, true)]
    [InlineData("IInsertBomTable", false, true)]
    [InlineData("ICreateText2", false, true)]
    [InlineData("InsertNewNote2", false, true)]
    [InlineData("ImportDiagnosis", false, true)]
    [InlineData("set_Text", false, true)]
    [InlineData("IsDetailingMode", true, false)]
    [InlineData("IsOpenedReadOnly", true, false)]
    [InlineData("Is3DView", true, false)]
    [InlineData("Is", true, false)]
    [InlineData("GetViews", true, false)]
    [InlineData("get_ReadOnly", true, false)]
    [InlineData("IGetDisplayDimensions", true, false)]
    [InlineData("Issue", false, false)] // (144A)
    [InlineData("Getaway", false, false)] // (144A)
    [InlineData("Title", false, false)]
    public void TheGrammarReadsEveryVerbsTwinAndTheReaderPrefixesAsWholeWords(string name, bool reader, bool writer)
    {
        Assert.Equal(reader, IsReader(name));
        Assert.Equal(writer, IsWriter(name));
    }

    /// <summary>
    /// Decision 144A (2026-10-19; research R10.4 item 2): every member of the 34 interfaces the generated
    /// tables are written against whose name a reader prefix starts by its letters but not as a word -
    /// on 32.5.0.48, <c>IDrawingDoc.IsolateChangedDimensions</c>, which the writer grammar now reaches, and
    /// <c>IAssemblyDoc.Isolate</c>, which no grammar of these interfaces reads and the <c>IAssemblyDoc</c>
    /// row names - is refused bare and qualified by every gate the product builds. A later interop's member
    /// of the kind fails here until someone decides what it is.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryNameTheReaderPrefixesTookOnlyByTheirLettersIsRefusedByEveryGate()
    {
        var taken = DocumentWriteFamilyTests.Interfaces
            .SelectMany(face => MethodNames(face)
                .Where(name => ReaderLetters.IsMatch(name) && !IsReader(name))
                .Select(name => face + "." + name))
            .OrderBy(key => key, StringComparer.Ordinal)
            .ToList();

        Assert.Equal(new[] { "IAssemblyDoc.Isolate", "IDrawingDoc.IsolateChangedDimensions" }, taken);

        IReadOnlyList<string> letThrough = GuardSweep.LetThrough(GuardSweep.ProductGates(), GuardSweep.Spellings(taken));
        Assert.True(letThrough.Count == 0, "Spellings a gate the product builds lets through: " + string.Join(", ", letThrough));
    }

    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryFamilyOfTheContractIsOnTheInterop()
    {
        foreach (string family in DrawingFamilies.Concat(SharedFamilies))
        {
            InterfaceType(family);
        }
    }

    /// <summary>The heart of SC-009: no writer of the 28 families is left callable by accident.</summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryWriterOfTheDrawingFamiliesIsRefusedOrANamedExclusion()
    {
        var excluded = new HashSet<string>(DrawingFamilyDenylistTests.ExcludedMembers, StringComparer.OrdinalIgnoreCase);
        var callable = new List<string>();

        foreach (string family in DrawingFamilies)
        {
            foreach (string name in MethodNames(family).Where(IsWriter))
            {
                if (excluded.Contains(name))
                {
                    continue;
                }

                try
                {
                    ReadOnlyGuard.Assert(name);
                    callable.Add(family + "." + name);
                }
                catch (MutatingCallError)
                {
                }
            }
        }

        Assert.True(
            callable.Count == 0,
            "Writers of the drawing families the guard does not refuse (regenerate the feature 011 "
                + "table with extractor/tools/list-writer-members.ps1): " + string.Join(", ", callable));
    }

    /// <summary>
    /// The other direction: every name a family row denies is a grammar match declared on that
    /// interface, so nothing was typed into the generated table by hand.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryFamilyRowNamesOnlyGrammarMatchesOfItsInterface()
    {
        foreach (var row in DrawingFamilyDenylistTests.Table)
        {
            string family = DrawingFamilyDenylistTests.InterfaceOf(row);
            if (SharedFamilies.Contains(family, StringComparer.Ordinal))
            {
                continue;
            }

            Assert.Contains(family, DrawingFamilies);
            var declared = new HashSet<string>(MethodNames(family), StringComparer.Ordinal);
            foreach (string member in row.Members)
            {
                Assert.True(declared.Contains(member), $"{family}.{member} is not declared on the interop.");
                Assert.True(IsWriter(member), $"{family}.{member} is not a writer by contracts/guard.md section 2.");
            }
        }
    }

    /// <summary>The shared rows name real members of their interfaces, and each is refused.</summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void TheSharedRowsAreDeclaredOnTheirInterfacesAndRefused()
    {
        var rows = DrawingFamilyDenylistTests.Table
            .Where(row => SharedFamilies.Contains(DrawingFamilyDenylistTests.InterfaceOf(row), StringComparer.Ordinal))
            .ToList();
        Assert.Equal(
            SharedFamilies.OrderBy(name => name, StringComparer.Ordinal),
            rows.Select(DrawingFamilyDenylistTests.InterfaceOf).OrderBy(name => name, StringComparer.Ordinal));

        foreach (var row in rows)
        {
            string family = DrawingFamilyDenylistTests.InterfaceOf(row);
            var declared = new HashSet<string>(MethodNames(family), StringComparer.Ordinal);
            foreach (string member in row.Members)
            {
                Assert.True(declared.Contains(member), $"{family}.{member} is not declared on the interop.");
                Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
            }
        }

        // The activation, closing, creation, opening and macro members section 1 names are the
        // point of the shared row; spot-check that each kind is there.
        foreach (string member in new[] { "ActivateDoc3", "CloseAllDocuments", "QuitDoc", "NewDrawing2", "OpenDoc", "LoadFile4", "RunMacro2", "DocumentVisible", "SetUserPreferenceInteger" })
        {
            Assert.Contains(member, DrawingFamilyDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase);
        }
    }
}

/// <summary>
/// Feature 011 T003. The hardening refuses nothing the product reads (FR-006, research RK-4).
///
/// Every string literal in the product's own source - the extractor, the add-in and the console,
/// including the constants a call site names a member through and the literals passed to the
/// dumpers' read helpers - is scanned, and every one the feature 011 table refuses must be one of
/// the named literals below, each of which is not a member the product calls through a gate.
/// That is a superset of "every literal passed to <c>SwGate.Call</c>" (contracts/guard.md section
/// 5): a gated name reached through a constant or a helper cannot slip past it. The scan found, the
/// day it was written, feature 004's <c>OpenDoc7</c> and <c>NewDocument</c>, which the section
/// therefore leaves allowed (see <see cref="DrawingFamilyDenylistTests.EveryExclusionHasOneOfTheContractsReasons"/>).
/// </summary>
public class DrawingFamilyReadAuditTests
{
    /// <summary>
    /// The literals the table refuses that are not member names the product gates, each keyed by the
    /// literal and the file it stands in, as <see cref="Literals"/> reports them, with what it is
    /// there. Keyed exactly, since decision 140A (2026-10-19): a word the product uses for something
    /// else in lower case - a clean-up step's label, a plan's JSON member - must not exempt the
    /// member's own spelling, which the guard refuses in every case. Keyed by file as well, since the
    /// decision's review (2026-10-19): an entry exempts its literal in the file named with it, never
    /// anywhere in the product, so a gate asked about the same spelling in another file - the capture's
    /// <c>Gate.Call("close", ...)</c> - fails the audit. The file is its path under the extractor
    /// folder since the decision's second pass, the same day, so a file of the same name in another
    /// folder is another file. Every key was already a literal spelled exactly
    /// (<see cref="EveryNamedLiteralIsStillInTheSourceAndStillRefused"/>), so each step exempts less.
    /// </summary>
    private static readonly IReadOnlyDictionary<(string Literal, string Where), string> NamedLiterals =
        new Dictionary<(string Literal, string Where), string>
        {
            [("ActivateDoc3", "SwReview.Extractor.Console/Program.cs")] =
                "a member probe standards asserts is absent from its gate log",
            [("ActivateDoc3", "SwReview.Extractor/Rms/RemodelInteropSurface.cs")] =
                "the frozen interop manifest's row for ISldWorks.ActivateDoc3 (feature 004 T181), which the pane seat "
                + "calls on the copy outside the bridge; a row records a member and permits none. Named on decision "
                + "140A's review, whose keying by file found it: the literal's earlier entry named Program.cs only. "
                + "Since decision 144A (research R11, settling R10.4 item 6) the seat calls it through a gate of its "
                + "own, by the qualified key its own guard, RemodelSeatGuard, allowlists",
            [("LoadFile4", "SwReview.Extractor.Console/Program.cs")] =
                "a member probe standards asserts is absent from its gate log",
            [("dimensions", "SwReview.Extractor/Ir/DrawingSheet.cs")] =
                "a JSON property name, matching IDrawingDoc.Dimensions only by case",
            [("dissolve", "SwReview.Extractor/Bridge/BridgeProtocol.cs")] =
                "a remodel.folder operation name in the protocol",
            [("LoadModel", "SwReview.Extractor/Rms/RemodelInteropSurface.cs")] =
                "the parameter name of IDocumentSpecification.set_LoadModel in the frozen interop manifest's builder "
                + "table (feature 004 T156), matching IView.LoadModel only by name",
            [("set_ReadOnly", "SwReview.Extractor/Rms/RemodelInteropSurface.cs")] =
                "IDocumentSpecification.set_ReadOnly in the frozen interop manifest's builder table (feature 004 T156), "
                + "a property of the throwaway open request that is set false and never gated, matching IDimension's "
                + "and INote's only by name",

            // Decision 140A (2026-10-19): what refusing Close, Save and Rebuild found. Three bridge
            // command names, which the dispatcher judges against its own fixed set and hands to no
            // guard, and a session-end reason spelled as one of them; judged as a qualified key, each
            // matches the member by the part after the dot only.
            [("remodel.close", "SwReview.Extractor/Bridge/BridgeProtocol.cs")] =
                "the bridge command remodel.close, matching IModelDoc2.Close only by the part after the dot",
            [("remodel.close", "SwReview.Extractor/Rms/RemodelSessionEnd.cs")] =
                "the session-end reason named after the bridge command remodel.close, matching IModelDoc2.Close only "
                + "by the part after the dot",
            [("remodel.close", "SwReview.Extractor/Rms/RemodelInteropSurface.cs")] =
                "the frozen interop manifest's used_by column naming the bridge command remodel.close, matching "
                + "IModelDoc2.Close only by the part after the dot",
            [("remodel.save", "SwReview.Extractor/Bridge/BridgeProtocol.cs")] =
                "the bridge command remodel.save, matching IModelDoc2.Save only by the part after the dot",
            [("remodel.save", "SwReview.Extractor/Rms/RemodelInteropSurface.cs")] =
                "the frozen interop manifest's used_by column naming the bridge command remodel.save, matching "
                + "IModelDoc2.Save only by the part after the dot",
            [("remodel.rebuild", "SwReview.Extractor/Bridge/BridgeProtocol.cs")] =
                "the bridge command remodel.rebuild, matching IModelDoc2.Rebuild and IModelDocExtension.Rebuild only "
                + "by the part after the dot",
            [("remodel.rebuild", "SwReview.Extractor/Rms/RemodelInteropSurface.cs")] =
                "the frozen interop manifest's used_by column naming the bridge command remodel.rebuild, matching "
                + "IModelDoc2.Rebuild and IModelDocExtension.Rebuild only by the part after the dot",

            // The same decision: lower-case words the product uses for something else.
            [("close", "SwReview.Extractor/Bridge/BridgeDispatcher.cs")] =
                "the label CloseCopyUnsaved gives its clean-up step in a failure sentence; the call is gated as "
                + "ISldWorks.CloseDoc, matching IModelDoc2.Close only by case",
            [("rebuild", "SwReview.AddIn/Remodel/RemodelHost.cs")] =
                "the plan's JSON member whose value the Remodel page receives as rebuild_list, matching "
                + "IModelDoc2.Rebuild only by case",
            [("events.close", "SwReview.AddIn/Review/ReviewHost.cs")] =
                "a message type the Review page sends its host, matching IModelDoc2.Close only by the part after the dot",
            [("send_when_checked.save", "SwReview.AddIn/Review/ReviewHost.cs")] =
                "a message type the Review page sends its host, matching IModelDoc2.Save only by the part after the dot",
            [("settings.save", "SwReview.AddIn/Review/ReviewHost.cs")] =
                "a message type the Review page sends its host, matching IModelDoc2.Save only by the part after the dot",
        };

    private static readonly Regex StringLiteral = new Regex("\"((?:[^\"\\\\\\r\\n]|\\\\.)*)\"", RegexOptions.Compiled);

    private static readonly string[] ProductSourceRoots =
    {
        "SwReview.Extractor",
        "SwReview.AddIn",
        "SwReview.Extractor.Console",
    };

    /// <summary>The extractor folder: the one holding SwReview.sln, found upward from the test assembly.</summary>
    internal static string ExtractorRoot()
    {
        DirectoryInfo? directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory != null && !File.Exists(Path.Combine(directory.FullName, "SwReview.sln")))
        {
            directory = directory.Parent;
        }

        Assert.True(directory != null, "SwReview.sln was not found above " + AppContext.BaseDirectory);
        return directory!.FullName;
    }

    internal static IEnumerable<string> ProductSourceFiles()
    {
        string root = ExtractorRoot();
        foreach (string project in ProductSourceRoots)
        {
            foreach (string file in Directory.EnumerateFiles(Path.Combine(root, project), "*.cs", SearchOption.AllDirectories))
            {
                string[] parts = file.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                if (parts.Contains("obj", StringComparer.OrdinalIgnoreCase) || parts.Contains("bin", StringComparer.OrdinalIgnoreCase))
                {
                    continue;
                }

                // The guards' own tables name members in order to refuse or allow them; they call
                // nothing, so the audit of what the product calls does not read them.
                if (parts.Contains("Guard", StringComparer.Ordinal))
                {
                    continue;
                }

                yield return file;
            }
        }
    }

    /// <summary>
    /// Every string literal of the product source, with the file it is in, by its path under the
    /// extractor folder (<see cref="PathUnder"/>). A literal never spans a line (the pattern stops at
    /// one), so the source is read a line at a time.
    ///
    /// Edited deliberately for decision 140A (2026-10-19): a line that is a comment and nothing else
    /// (<see cref="IsWholeLineComment"/>) is skipped. A word quoted in a comment - <c>"rebuild"</c> in
    /// a sentence, <c>&lt;see cref="Close"/&gt;</c> naming a C# method, <c>&lt;paramref name="close"/&gt;</c>
    /// - is not a string the program holds, so it can name no member a gate is asked about; until
    /// <c>Close</c>, <c>Save</c> and <c>Rebuild</c> were refused, none stood in one. A comment after
    /// code on the same line is still read, which errs toward reading too much.
    /// </summary>
    internal static IReadOnlyList<(string Literal, string Where)> Literals()
    {
        string root = ExtractorRoot();
        var found = new List<(string, string)>();
        foreach (string file in ProductSourceFiles())
        {
            string where = PathUnder(root, file);
            foreach (string line in File.ReadAllLines(file))
            {
                if (IsWholeLineComment(line))
                {
                    continue;
                }

                foreach (Match match in StringLiteral.Matches(line))
                {
                    found.Add((match.Groups[1].Value, where));
                }
            }
        }

        return found;
    }

    /// <summary>
    /// <paramref name="file"/>'s path under <paramref name="root"/>, the extractor folder, with forward
    /// slashes - <c>SwReview.Extractor/Capture/SwCaptureView.cs</c> - which names one file however
    /// many others share its name. Since decision 140A's second pass (2026-10-19): the scan named a
    /// file by its name alone, and a key by file needed a check that no two files shared one, which
    /// failed for any two that did, whether or not a key named either.
    /// </summary>
    private static string PathUnder(string root, string file)
    {
        Assert.StartsWith(root, file, StringComparison.OrdinalIgnoreCase);
        return file.Substring(root.Length).TrimStart('\\', '/').Replace('\\', '/');
    }

    /// <summary>A line whose first characters, after its indentation, open a line comment.</summary>
    internal static bool IsWholeLineComment(string line) =>
        line.TrimStart().StartsWith("//", StringComparison.Ordinal);

    /// <summary>A floor, so a scan that read nothing cannot pass vacuously.</summary>
    [Fact]
    public void TheScanReadsTheProductSource()
    {
        IReadOnlyList<(string Literal, string Where)> literals = Literals();

        Assert.True(ProductSourceFiles().Count() > 100, "The product source scan found almost no files.");
        foreach (string read in new[] { "GetViews", "GetReferencedModelName", "GetOpenDocumentByName", "OpenDoc6", "OpenDoc7", "NewDocument" })
        {
            Assert.Contains(literals, literal => literal.Literal == read);
        }
    }

    /// <summary>
    /// Decision 140A: the scan skips a line that is a comment and nothing else - a documentation
    /// comment, a line comment, at any indentation - and reads every other line whole, so a
    /// literal in code is read even with a comment after it, and so is one in a block comment or
    /// after a URL's two slashes, erring toward reading too much.
    /// </summary>
    [Theory]
    [InlineData("    /// <see cref=\"Close\"/> waits for a reader", true)]
    [InlineData("/// <paramref name=\"close\"/>", true)]
    [InlineData("        // A command outside the vocabulary - \"rebuild\", \"Save3\" - is in no scope", true)]
    [InlineData("\t//\"Close\"", true)]
    [InlineData("_gate.Call(\"Close\", () => document.Close()); // \"Close\"", false)]
    [InlineData("string url = \"http://example.invalid/Close\";", false)]
    [InlineData("/* \"Close\" */", false)]
    [InlineData("\"Close\"", false)]
    [InlineData("", false)]
    public void OnlyAWholeLineCommentIsSkipped(string line, bool skipped)
    {
        Assert.Equal(skipped, IsWholeLineComment(line));
    }

    /// <summary>
    /// A literal as the read-only guard judges it: its member half when it is an
    /// interface-qualified key (feature 011 review, 2026-09-23), unless it is a key of one of the
    /// two allowlist guards, which judge their own keys before the read-only guard is asked. The pane
    /// seat's guard (decision 144A) is not among them: its keys are judged whole only in the seat's own
    /// file (<see cref="IsTheSeatsOwnKey"/>), so a key carried to another file is judged by its member
    /// half here as before.
    /// </summary>
    internal static string Judged(string literal) =>
        CallKey.IsQualified(literal)
            && !RemodelGuard.AllowedKeys.Contains(literal)
            && !DrawingOpenGuard.AllowedKeys.Contains(literal)
            ? CallKey.BareName(literal)
            : literal;

    /// <summary>The pane seat's file, by its path under the extractor folder (decision 144A).</summary>
    internal const string PaneSeatFile = "SwReview.AddIn/Remodel/SwRemodelSeat.cs";

    /// <summary>
    /// Decision 144A's review (T173): a literal of the pane seat's own file that is one of its guard's
    /// two keys is the seat's own call, which its own guard judges first - in that file and nowhere else,
    /// as <see cref="IsTheProbesOwnCall"/> keys the probe's calls by its file.
    /// </summary>
    private static bool IsTheSeatsOwnKey((string Literal, string Where) literal) =>
        literal.Where == PaneSeatFile && RemodelSeatGuard.AllowedKeys.Contains(literal.Literal);

    /// <summary>
    /// Decision 144A's review (T173): the pane seat's two keys are literals of its own file and of no
    /// other product file, so its guard's exemption is exercised and stays its own; a key carried to
    /// another file fails here and in the audit.
    /// </summary>
    [Fact]
    public void TheSeatsOwnKeysAreLiteralsOfItsOwnFileAlone()
    {
        var named = Literals()
            .Where(literal => RemodelSeatGuard.AllowedKeys.Contains(literal.Literal))
            .Select(literal => literal.Literal + " in " + literal.Where)
            .Distinct(StringComparer.Ordinal)
            .OrderBy(entry => entry, StringComparer.Ordinal)
            .ToList();

        Assert.Equal(
            new[] { "ISldWorks.ActivateDoc3 in " + PaneSeatFile, "ISldWorks.OpenDoc7 in " + PaneSeatFile },
            named);
    }

    /// <summary>
    /// Edited deliberately for decision 144A (2026-10-19): a literal of <c>probe remodel</c>'s host that
    /// the probe's own guard lets through is not a read but the probe's own call
    /// (<see cref="IsTheProbesOwnCall"/>), as decision 21A's audit judges the probe's creation calls;
    /// <see cref="TheProbesOwnCallsAreExactlyItsTwoWritersAndOnlyItsGuardLetsThemThrough"/> pins which.
    /// And on the decision's review (T173), a literal of the pane seat's file that is one of its guard's
    /// two keys is the seat's own call (<see cref="IsTheSeatsOwnKey"/>), in that file only.
    /// </summary>
    [Fact]
    public void NoLiteralOfTheProductSourceIsRefusedByTheTableExceptTheNamedOnes()
    {
        var table = new HashSet<string>(DrawingFamilyDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase);
        var refused = Literals()
            .Where(literal => table.Contains(Judged(literal.Literal))
                && !NamedLiterals.ContainsKey(literal)
                && !IsTheProbesOwnCall(literal)
                && !IsTheSeatsOwnKey(literal))
            .Select(literal => $"\"{literal.Literal}\" in {literal.Where}")
            .Distinct(StringComparer.Ordinal)
            .ToList();

        Assert.True(
            refused.Count == 0,
            "The feature 011 denials refuse a name the product source uses; a read that needs a refused "
                + "member is a read that writes and is redesigned, never exempted: " + string.Join(", ", refused));
    }

    /// <summary>
    /// Decision 144A (2026-10-19): a literal of <c>probe remodel</c>'s host
    /// (<see cref="CreationFamilyReadAuditTests.ProbeHostFile"/>) that <see cref="RemodelProbeGuard"/>
    /// lets through is one of the probe's own calls on its throwaway part, made through the one gate
    /// built with that guard - never a read the table would refuse.
    /// </summary>
    private static bool IsTheProbesOwnCall((string Literal, string Where) literal) =>
        literal.Where == CreationFamilyReadAuditTests.ProbeHostFile
        && !GuardSweep.Refuses(new RemodelProbeGuard().Assert, literal.Literal);

    /// <summary>
    /// Decision 144A: the probe's own calls the table refuses are exactly its two writers the read-only
    /// guard left allowed until then - <c>NewDocument</c> and <c>MoveToFolder</c> - and its guard lets
    /// each through, so the exception is exercised and no wider: a later literal of the probe host the
    /// table refuses fails here until someone decides what it is.
    /// </summary>
    [Fact]
    public void TheProbesOwnCallsAreExactlyItsTwoWritersAndOnlyItsGuardLetsThemThrough()
    {
        var table = new HashSet<string>(DrawingFamilyDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase);
        var named = Literals()
            .Where(literal => literal.Where == CreationFamilyReadAuditTests.ProbeHostFile && table.Contains(Judged(literal.Literal)))
            .Select(literal => literal.Literal)
            .Distinct(StringComparer.Ordinal)
            .OrderBy(literal => literal, StringComparer.Ordinal)
            .ToList();

        Assert.Equal(new[] { "MoveToFolder", "NewDocument" }, named);
        Assert.All(named, member => new RemodelProbeGuard().Assert(member));

        // Only its guard (the decision's review, T176): every other gate the product builds refuses each.
        Assert.Equal(
            new[] { "RemodelProbeGuard MoveToFolder", "RemodelProbeGuard NewDocument" },
            GuardSweep.LetThrough(GuardSweep.ProductGates(), named));
    }

    /// <summary>
    /// Each named literal is still in the source and still refused, so the list cannot go stale
    /// and hide a later collision behind an entry nobody needs.
    /// </summary>
    [Fact]
    public void EveryNamedLiteralIsStillInTheSourceAndStillRefused() =>
        AssertEveryNamedLiteralIsStillInTheSourceAndRefused(NamedLiterals, DrawingFamilyDenylistTests.ExpectedMembers);

    /// <summary>
    /// The staleness check every read audit's named literals share (feature 011, decision 21A's T169):
    /// each is still a literal of the product source, spelled exactly, and still refused by the table
    /// its audit reads - judged as the audits judge a literal (<see cref="Judged"/>), which is the
    /// literal itself for a bare name. Edited deliberately for decision 140A, whose three named
    /// literals are qualified: a qualified literal is refused when its member half is. Edited again on
    /// the decision's review, which keyed each by its file: each is still a literal of the file named
    /// with it.
    /// </summary>
    internal static void AssertEveryNamedLiteralIsStillInTheSourceAndRefused(
        IReadOnlyDictionary<(string Literal, string Where), string> named, IReadOnlyCollection<string> table)
    {
        IReadOnlyList<(string Literal, string Where)> literals = Literals();
        foreach (KeyValuePair<(string Literal, string Where), string> entry in named)
        {
            Assert.True(
                literals.Contains(entry.Key),
                $"\"{entry.Key.Literal}\" is no longer a literal of {entry.Key.Where}; drop it, or say what it is now.");
            Assert.Contains(Judged(entry.Key.Literal), table, StringComparer.OrdinalIgnoreCase);
        }
    }
}

/// <summary>
/// What the family tests of decisions 136A and 140A share (<see cref="DocumentLifecycleFamilyTests"/>,
/// <see cref="DocumentWriteFamilyTests"/>): the guards the product builds its gates with, a family
/// grammar read over interfaces, and what a guard lets through of a set of keys. Each decision's class
/// keeps its own grammar, interfaces, members left allowed and exceptions.
/// </summary>
internal static class GuardSweep
{
    /// <summary>
    /// Every guard a gate the product builds is built with: the read-only guard every gate gets by
    /// default, and the five the exceptions, the confirmed drawing's open and, since decision 144A, the
    /// re-modeler's pane seat build their gates with. <see cref="GuardSweepTests"/> holds it to every
    /// guard the product defines, so a guard added later cannot be left out of the sweeps.
    /// </summary>
    internal static ICallGuard[] ProductGates() => new ICallGuard[]
    {
        ReadOnlyCallGuard.Instance,
        new SuppressTestGuard(),
        new RemodelProbeGuard(),
        new RemodelGuard(),
        new DrawingOpenGuard(),
        new RemodelSeatGuard(),
    };

    /// <summary>
    /// Every member of <paramref name="interfaces"/> whose name <paramref name="family"/> matches,
    /// interface-qualified, readers included, in ordinal order.
    /// </summary>
    internal static IReadOnlyList<string> Members(IEnumerable<string> interfaces, Regex family) =>
        interfaces
            .SelectMany(face => DrawingFamilyCompletenessTests.MethodNames(face)
                .Where(name => family.IsMatch(name))
                .Select(name => face + "." + name))
            .OrderBy(key => key, StringComparer.Ordinal)
            .ToList();

    /// <summary>The members to refuse: neither a reader by contracts/guard.md section 2's prefixes nor left allowed.</summary>
    internal static IEnumerable<string> ToRefuse(IEnumerable<string> members, IEnumerable<string> allowed)
    {
        var left = new HashSet<string>(allowed, StringComparer.Ordinal);
        return members.Where(key => !DrawingFamilyCompletenessTests.IsReader(CallKey.BareName(key)) && !left.Contains(key));
    }

    /// <summary>Both spellings a call site can hand a gate for each key: the key, and its member half.</summary>
    internal static IReadOnlyCollection<string> Spellings(IEnumerable<string> keys)
    {
        var spellings = new SortedSet<string>(StringComparer.Ordinal);
        foreach (string key in keys)
        {
            spellings.Add(key);
            spellings.Add(CallKey.BareName(key));
        }

        return spellings;
    }

    /// <summary>"<c>Guard spelling</c>" for every spelling each guard lets through, guard by guard.</summary>
    internal static IReadOnlyList<string> LetThrough(IEnumerable<ICallGuard> guards, IReadOnlyCollection<string> spellings) =>
        guards
            .SelectMany(guard => spellings
                .Where(key => !Refuses(guard.Assert, key))
                .Select(key => guard.GetType().Name + " " + key))
            .ToList();

    internal static bool Refuses(Action<string> assert, string key)
    {
        try
        {
            assert(key);
            return false;
        }
        catch (MutatingCallError)
        {
            return true;
        }
    }

    /// <summary>
    /// Every gate the product builds lets through exactly <paramref name="exceptions"/> of
    /// <paramref name="spellings"/> - keyed "<c>Guard spelling</c>", as <see cref="LetThrough"/> reports
    /// them - each with a reason: a guard that comes to let another member through, or no longer lets
    /// one of these through, fails, so an exception cannot widen, or outlive its guard, unnoticed.
    /// Shared by the family sweeps of decisions 136A and 140A since decision 144A gave the first its own.
    /// </summary>
    internal static void AssertLetThroughExactly(
        IReadOnlyCollection<string> spellings, IReadOnlyDictionary<string, (string Where, string Reason)> exceptions)
    {
        IReadOnlyList<string> letThrough = LetThrough(ProductGates(), spellings);

        Assert.True(
            new HashSet<string>(letThrough, StringComparer.Ordinal).SetEquals(exceptions.Keys),
            "Family members a gate the product builds lets through: " + string.Join(", ", letThrough)
                + "; expected exactly: " + string.Join(", ", exceptions.Keys));
        Assert.All(exceptions, entry => Assert.False(string.IsNullOrWhiteSpace(entry.Value.Reason), entry.Key + " has no reason."));
    }

    /// <summary>
    /// Each exception's key is still a literal of the product file named with it - its path under the
    /// extractor folder, as the read audit's scan reports it - so one guard's exception cannot be kept
    /// alive by another's call of the same member.
    /// </summary>
    internal static void AssertEveryExceptionIsStillNamed(IReadOnlyDictionary<string, (string Where, string Reason)> exceptions)
    {
        IReadOnlyList<(string Literal, string Where)> literals = DrawingFamilyReadAuditTests.Literals();

        foreach (KeyValuePair<string, (string Where, string Reason)> exception in exceptions)
        {
            string key = exception.Key.Substring(exception.Key.IndexOf(' ') + 1);
            Assert.True(
                literals.Any(literal => literal.Literal == key && literal.Where == exception.Value.Where),
                $"{exception.Key} is no longer named in {exception.Value.Where}; drop it, or say what calls it now.");
        }
    }
}

/// <summary>
/// Decision 144A (feature 011 T163): "every gate the product builds" is every guard the product
/// defines. The family sweeps, the creation and import-repair sweeps and the confirmed open's read
/// check all read <see cref="GuardSweep.ProductGates"/>, so a guard added and left out of it would be
/// swept by none of them - the pane seat's guard, which lets <c>ISldWorks.ActivateDoc3</c> through,
/// above all.
/// </summary>
public class GuardSweepTests
{
    /// <summary>
    /// A type declared to implement <see cref="ICallGuard"/>: a class, a struct or a record, generic or
    /// not, with a primary constructor or not. Widened on the decision's review (T173), which found the
    /// first form read classes alone.
    /// </summary>
    private static readonly Regex GuardDeclaration = new Regex(
        @"\b(?:class|struct|record(?:\s+(?:class|struct))?)\s+(\w+)\s*(?:<[^>{]*>)?\s*(?:\([^)]*\))?\s*:[^{;]*\bICallGuard\b",
        RegexOptions.CultureInvariant);

    /// <summary>
    /// One of every concrete <see cref="ICallGuard"/> the extractor's and the console's assemblies
    /// define - where every guard lives is the extractor's <c>Guard</c> folder - and none declared in any
    /// other source file of the three projects (the add-in's own assembly, which this suite does not
    /// load, is read by the add-in suite's <c>TheAddInDefinesNoGuardOfItsOwn</c>). Widened on the
    /// decision's review (T173): it read the extractor's assembly alone and the read audit's files, which
    /// skip every folder named <c>Guard</c>.
    /// </summary>
    [Fact]
    public void TheProductsGatesHoldOneOfEveryGuardTheProductDefines()
    {
        var defined = new[] { typeof(ICallGuard).Assembly, typeof(SwReview.Extractor.Console.Program).Assembly }
            .SelectMany(assembly => assembly.GetTypes())
            .Where(type => typeof(ICallGuard).IsAssignableFrom(type) && !type.IsInterface && !type.IsAbstract)
            .Select(type => type.FullName!)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToList();
        var swept = GuardSweep.ProductGates()
            .Select(gate => gate.GetType().FullName!)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToList();

        Assert.Contains(typeof(RemodelSeatGuard).FullName, defined);
        Assert.Equal(defined, swept);

        string root = DrawingFamilyReadAuditTests.ExtractorRoot();
        string guardFolder = Path.Combine(root, "SwReview.Extractor", "Guard") + Path.DirectorySeparatorChar;
        var elsewhere = new[] { "SwReview.Extractor", "SwReview.AddIn", "SwReview.Extractor.Console" }
            .SelectMany(project => Directory.EnumerateFiles(Path.Combine(root, project), "*.cs", SearchOption.AllDirectories))
            .Where(file => !file.Split(Path.DirectorySeparatorChar).Any(part => part == "obj" || part == "bin"))
            .Where(file => !file.StartsWith(guardFolder, StringComparison.OrdinalIgnoreCase))
            .SelectMany(file => GuardDeclaration.Matches(File.ReadAllText(file)).Cast<Match>()
                .Select(match => match.Groups[1].Value + " in " + file.Substring(root.Length).TrimStart('\\', '/')))
            .ToList();
        Assert.True(elsewhere.Count == 0, "Guards declared outside the extractor's Guard folder: " + string.Join(", ", elsewhere));
    }

    /// <summary>The declaration pattern reads every form a guard could be declared in, and nothing else.</summary>
    [Theory]
    [InlineData("public sealed class RemodelSeatGuard : ICallGuard", true)]
    [InlineData("internal class Guard<T> : Base, ICallGuard", true)]
    [InlineData("public struct StructGuard : ICallGuard", true)]
    [InlineData("public record RecordGuard(string Name) : ICallGuard", true)]
    [InlineData("public record struct RecordStructGuard : ICallGuard", true)]
    [InlineData("public sealed class SwRemodelSeat : IRemodelSeat", false)]
    [InlineData("private readonly ICallGuard _guard;", false)]
    public void TheDeclarationPatternReadsEveryFormOfAGuard(string declaration, bool isGuard)
    {
        Assert.Equal(isGuard, GuardDeclaration.IsMatch(declaration));
    }
}

/// <summary>
/// Decision 136A (feature 011, 2026-10-19). FR-005 asks the guard to refuse the application's
/// document activation, closing, creation and macro members, and contracts/guard.md section 1's shared
/// rows named them by hand, so other spellings on the same interop went unrefused: the COM twins
/// <c>IOpenDoc</c> to <c>IOpenDoc5</c>, <c>IOpenDocSilent</c>, <c>IActivateDoc*</c> and the
/// <c>INew*</c> creators, and bare <c>LoadFile</c>, <c>LoadAddIn</c> and <c>LoadAdminSettingsFile</c>.
///
/// This class reflects the interop the extractor is built against and holds every member of
/// <c>ISldWorks</c>, <c>IModelDoc2</c> and <c>IModelDocExtension</c> - and, since decision 144A,
/// <c>IAssemblyDoc</c> - whose name belongs to the open,
/// activate, new, load, close or quit families (<see cref="BelongsToAFamily"/>) to one of three answers:
/// a reader by section 2's prefixes, which stays allowed (FR-006); one of the <see cref="Allowed"/>
/// members, each with its reason; or refused by <see cref="ReadOnlyGuard"/> in both spellings a call
/// site can hand it - bare, and qualified with its interface - and by every gate the product builds
/// but for the exceptions a guard was written for, each named with its reason
/// (<see cref="Exceptions"/>, since decision 144A). A member a later interop adds fails here until
/// someone decides which it is. Only metadata is read; SOLIDWORKS is never started.
/// </summary>
public class DocumentLifecycleFamilyTests
{
    /// <summary>
    /// The interfaces the families are read from. Edited deliberately for decision 144A (2026-10-19;
    /// research R10.4 item 1): <c>IAssemblyDoc</c> joined as a fourth, the document type whose
    /// component opens, reloads and new parts are these families' members too (<c>OpenCompFile</c>,
    /// <c>ComponentReload2</c>, <c>InsertNewPart2</c>, ...).
    /// </summary>
    internal static readonly string[] Interfaces = { "ISldWorks", "IModelDoc2", "IModelDocExtension", "IAssemblyDoc" };

    /// <summary>
    /// What the grammar finds on <c>IAssemblyDoc</c> on 32.5.0.48 (research R10.4 item 1, decision 144A):
    /// component documents opened, reloaded or created, a reference loaded, the ground plane activated,
    /// and the isolate and temporary-fix-group modes left - none a reader, and none called by the product.
    /// </summary>
    private static readonly string[] AssemblyFamilyMembers =
    {
        "OpenCompFile", "SelectiveOpen", "ComponentReload", "ComponentReload2", "IComponentReload2",
        "IComponentReload3", "InsertNewPart", "InsertNewPart2", "InsertNewAssembly", "InsertNewVirtualPart",
        "InsertNewVirtualAssembly", "InsertLoadReference", "ActivateGroundPlane", "ExitIsolate",
        "TemporaryFixGroupExit",
    };

    /// <summary>
    /// The families, as a word of a member's name: the verb, or a compound of it, beginning with its
    /// capital - at the start of the name, after a COM twin's <c>I</c>, or where a word starts - and
    /// ending where the name does or the next word begins. So <c>IOpenDoc5</c>, <c>CloseAndReopen</c>,
    /// <c>ExitApp</c> (the quit family), <c>FileReload</c> (load) and <c>DeActivateFeatureMgrView</c>
    /// (activate) belong; <c>ClosestDistance</c>, a measurement, and <c>IsOpenedReadOnly</c> do not.
    /// </summary>
    private static readonly Regex Family = new Regex(
        "(Open|Reopen|Activate|Deactivate|New|Load|Reload|Unload|Close|Quit|Exit)(?![a-z])",
        RegexOptions.CultureInvariant);

    /// <summary>
    /// The family members deliberately left allowed, each with its reason: the exclusions of
    /// contracts/guard.md section 3 these families reach. Keyed interface-qualified, though the guard
    /// matches bare names, so the bare name is what stays allowed.
    /// </summary>
    internal static readonly IReadOnlyDictionary<string, string> Allowed = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["ISldWorks.OpenDoc6"] = "the console attach's read-only open of a part or assembly (SwSession.OpenReadOnly, "
            + "under the bare key), checked with IsOpenedReadOnly since decision 136A; the confirmed drawing's open "
            + "calls the qualified key through DrawingOpenGuard's allowlist",
        ["ISldWorks.OpenDoc7"] = "feature 004's open of the re-modeler's own copy (remodel.open, under RemodelGuard) and "
            + "probe remodel's reopen of its throwaway part",
        ["ISldWorks.CloseDoc"] = "the bare name of feature 004's stage-1 allowlist key ISldWorks.CloseDoc: denying it "
            + "would make that key override a read-only denial; the confirmed drawing's close and the console "
            + "attach's close of a document it opened that is not read-only both go through the identity check",

        // Decision 140A (2026-10-19) removed IModelDoc2.Close from this list: it was left allowed only
        // because the bridge handed the command name remodel.close to the read-only guard, which
        // judged it by its member half. The dispatcher no longer does, and nothing calls the member.
        //
        // Decision 144A (the same day) removed ISldWorks.NewDocument: probe remodel's throwaway part is
        // created with it under the probe's own guard, so the read-only guard refuses it now and only
        // RemodelProbeGuard lets it through, one of the Exceptions below.
    };

    /// <summary>
    /// What a guard written for an exception lets through of these families, as the guard's type and
    /// the key, each with the product file whose call needs it - its path under the extractor folder,
    /// as the read audit's scan reports it - and the exception it is: exactly these (decision 144A,
    /// 2026-10-19, which gave this class the exceptions <see cref="DocumentWriteFamilyTests"/> has). The
    /// read-only guard, the suppress-test's, the re-modeler's and the confirmed drawing's let none
    /// through.
    /// </summary>
    internal static readonly IReadOnlyDictionary<string, (string Where, string Reason)> Exceptions =
        new Dictionary<string, (string Where, string Reason)>(StringComparer.Ordinal)
        {
            ["RemodelSeatGuard ISldWorks.ActivateDoc3"] = ("SwReview.AddIn/Remodel/SwRemodelSeat.cs",
                "the re-modeler's pane seat makes the run's copy the active document, by its title and without a "
                + "rebuild, for remodel.open_copy and before each dump (feature 004 T159); its own guard allowlists "
                + "the qualified key and nothing else of the families but ISldWorks.OpenDoc7, which the read-only "
                + "guard leaves allowed (decision 144A)"),
            ["RemodelProbeGuard NewDocument"] = ("SwReview.Extractor/Rms/SwRemodelProbeHost.cs",
                "probe remodel creates its throwaway part, and PROBE-8's and PROBE-21's, with it (feature 004 T032): one "
                + "of RemodelProbeGuard's run-scoped members since decision 144A, under the bare name its host gates, "
                + "in the one gate built with that guard, which refuses to run while any document is open"),
        };

    internal static bool BelongsToAFamily(string name) => Family.IsMatch(name);

    /// <summary>Every family member of the four interfaces, interface-qualified, readers included.</summary>
    internal static IReadOnlyList<string> FamilyMembers() => GuardSweep.Members(Interfaces, Family);

    private static IEnumerable<string> RefusedFamilyMembers() => GuardSweep.ToRefuse(FamilyMembers(), Allowed.Keys);

    [Theory]
    [InlineData("IOpenDoc5", true)]
    [InlineData("IOpenDocSilent", true)]
    [InlineData("CloseAndReopen2", true)]
    [InlineData("ExitApp", true)]
    [InlineData("FileReload", true)]
    [InlineData("UnloadAddIn", true)]
    [InlineData("DeActivateFeatureMgrView", true)]
    [InlineData("CreateNewWindow", true)]
    [InlineData("Quit", true)]
    [InlineData("OpenCompFile", true)]
    [InlineData("SelectiveOpen", true)]
    [InlineData("IComponentReload3", true)]
    [InlineData("InsertNewVirtualAssembly", true)]
    [InlineData("InsertLoadReference", true)]
    [InlineData("ActivateGroundPlane", true)]
    [InlineData("ExitIsolate", true)]
    [InlineData("TemporaryFixGroupExit", true)]
    [InlineData("ClosestDistance", false)]
    [InlineData("IClosestDistance", false)]
    [InlineData("IsOpenedReadOnly", false)]
    [InlineData("DownloadFromMySolidWorksSettings", false)]
    [InlineData("InsertSheetMetalClosedCorner", false)]
    [InlineData("Isolate", false)]
    [InlineData("GetOpenDocumentByName", true)]
    public void TheFamilyGrammarReadsWholeWords(string name, bool belongs)
    {
        Assert.Equal(belongs, BelongsToAFamily(name));
    }

    /// <summary>
    /// A floor, so a grammar or a reflection that found almost nothing cannot pass vacuously, and the
    /// spellings decision 136A names are among what it finds.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void TheFamiliesAreFoundOnEachInterface()
    {
        IReadOnlyList<string> members = FamilyMembers();

        Assert.True(
            members.Count(key => key.StartsWith("ISldWorks.", StringComparison.Ordinal)) >= 40,
            "The family grammar found almost nothing on ISldWorks: " + string.Join(", ", members));
        foreach (string face in Interfaces)
        {
            Assert.Contains(members, key => key.StartsWith(face + ".", StringComparison.Ordinal));
        }

        foreach (string named in new[]
                 {
                     "ISldWorks.IOpenDoc", "ISldWorks.IOpenDoc2", "ISldWorks.IOpenDoc3", "ISldWorks.IOpenDoc4",
                     "ISldWorks.IOpenDoc5", "ISldWorks.IOpenDocSilent", "ISldWorks.IActivateDoc",
                     "ISldWorks.IActivateDoc2", "ISldWorks.IActivateDoc3", "ISldWorks.INewDocument",
                     "ISldWorks.INewDocument2", "ISldWorks.INewDrawing", "ISldWorks.INewDrawing2",
                     "ISldWorks.INewPart", "ISldWorks.INewAssembly", "ISldWorks.LoadFile", "ISldWorks.LoadAddIn",
                     "ISldWorks.LoadAdminSettingsFile",
                 })
        {
            Assert.Contains(named, members);
        }

        // Decision 144A: the members research R10.4 item 1 names on IAssemblyDoc, and no other.
        Assert.Equal(
            AssemblyFamilyMembers.Select(name => "IAssemblyDoc." + name).OrderBy(key => key, StringComparer.Ordinal),
            members.Where(key => key.StartsWith("IAssemblyDoc.", StringComparison.Ordinal)));
    }

    /// <summary>The heart of decision 136A: no member of the families is left callable by accident.</summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryFamilyMemberIsAReader_ANamedExclusion_OrRefusedBareAndQualified()
    {
        var callable = RefusedFamilyMembers()
            .Where(key => !GuardSweep.Refuses(ReadOnlyGuard.Assert, CallKey.BareName(key))
                || !GuardSweep.Refuses(ReadOnlyGuard.Assert, key))
            .ToList();

        Assert.True(
            callable.Count == 0,
            "Members of the open, activate, new, load, close and quit families the read-only guard does not "
                + "refuse in both spellings: refuse each (the shared rows of extractor/tools/list-writer-members.ps1, "
                + "contracts/guard.md section 1) or name it in Allowed with its reason: " + string.Join(", ", callable));
    }

    /// <summary>
    /// Every gate the product builds refuses them in both spellings, except exactly
    /// <see cref="Exceptions"/>. Edited deliberately for decision 144A (2026-10-19): this was
    /// <c>EveryGateTheProductBuildsRefusesThem</c>, which asserted that no gate let any member through;
    /// the pane seat's own guard lets <c>ISldWorks.ActivateDoc3</c> through, the one call the seat makes
    /// that the read-only guard refuses, so the test names it as an exception, with the file whose call
    /// needs it, as <see cref="DocumentWriteFamilyTests"/> names its own - and any other member a gate
    /// lets through, or an exception no guard lets through any longer, fails it as before.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions() =>
        GuardSweep.AssertLetThroughExactly(GuardSweep.Spellings(RefusedFamilyMembers()), Exceptions);

    /// <summary>
    /// Each exception's key is still a literal of the product file whose call needs it (decision 144A),
    /// so one guard's exception cannot be kept alive by another's call of the same member.
    /// </summary>
    [Fact]
    public void EveryExceptionIsStillNamedByTheProduct() => GuardSweep.AssertEveryExceptionIsStillNamed(Exceptions);

    /// <summary>The reads among the families stay allowed in both spellings (FR-006): the lookups the product calls above all.</summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void TheReadersAmongThemStayAllowed()
    {
        var readers = FamilyMembers().Where(key => DrawingFamilyCompletenessTests.IsReader(CallKey.BareName(key))).ToList();

        Assert.Contains("ISldWorks.GetOpenDocumentByName", readers);
        foreach (string key in readers)
        {
            ReadOnlyGuard.Assert(CallKey.BareName(key));
            ReadOnlyGuard.Assert(key);
        }
    }

    /// <summary>
    /// Each exclusion is a family member of the interop, not a reader, allowed in both spellings, with
    /// a reason - so the list cannot go stale and hide a later member behind an entry nobody needs -
    /// and is one the generated "Not denied (feature 011)" table names with its reason, so the
    /// contract and this list agree.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryAllowedMemberIsAFamilyMemberLeftAllowedWithTheContractsReason()
    {
        IReadOnlyList<string> members = FamilyMembers();

        foreach (KeyValuePair<string, string> entry in Allowed)
        {
            string bare = CallKey.BareName(entry.Key);
            Assert.Contains(entry.Key, members);
            Assert.False(DrawingFamilyCompletenessTests.IsReader(bare), $"{entry.Key} is a reader; readers need no entry.");
            Assert.False(string.IsNullOrWhiteSpace(entry.Value), $"{entry.Key} has no reason.");
            ReadOnlyGuard.Assert(bare);
            ReadOnlyGuard.Assert(entry.Key);
            Assert.Contains(bare, DrawingFamilyDenylistTests.ExcludedMembers, StringComparer.OrdinalIgnoreCase);
        }
    }

    /// <summary>
    /// Decision 140A (2026-10-19). This replaces <c>NoCommandTheBridgeAnswersIsRefusedByTheReadOnlyGuard</c>,
    /// which pinned a dispatcher that handed every command name to the read-only guard, so the member
    /// halves of <c>remodel.close</c>, <c>remodel.save</c> and <c>remodel.rebuild</c> had to stay allowed.
    /// The dispatcher now judges its commands against its own fixed set and hands no name to a guard
    /// (<c>BridgeDispatcherTests</c>, "the bridge's own commands"), so the three members are refused:
    /// bare, and qualified with every interface of the three that declares them, by every gate the
    /// product builds.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void CloseSaveAndRebuildAreRefusedInEverySpellingByEveryGate()
    {
        var spellings = new List<string>();
        foreach (string member in new[] { "Close", "Save", "Rebuild" })
        {
            string[] declaring = Interfaces
                .Where(face => DrawingFamilyCompletenessTests.MethodNames(face).Contains(member, StringComparer.Ordinal))
                .ToArray();
            Assert.NotEmpty(declaring);
            spellings.Add(member);
            spellings.AddRange(declaring.Select(face => face + "." + member));
        }

        Assert.Contains("IModelDoc2.Close", spellings);
        Assert.Contains("IModelDoc2.Save", spellings);
        Assert.Contains("IModelDoc2.Rebuild", spellings);
        Assert.Contains("IModelDocExtension.Rebuild", spellings);

        IReadOnlyList<string> letThrough = GuardSweep.LetThrough(GuardSweep.ProductGates(), spellings);
        Assert.True(letThrough.Count == 0, "Spellings a gate the product builds lets through: " + string.Join(", ", letThrough));
    }
}

/// <summary>
/// Decision 140A (feature 011, 2026-10-19). The read-only guard let the save family through as bare
/// names - <c>IModelDoc2</c>'s <c>Save2</c>, <c>SaveAs</c>, <c>SaveAs2</c>, <c>SaveAs4</c>,
/// <c>SaveAsSilent</c> and <c>SaveSilent</c>, <c>IModelDocExtension</c>'s <c>SaveAs</c>, <c>SaveAs2</c>
/// and <c>SavePackAndGo</c>, <c>ISldWorks.SaveSettings</c> - and <c>SetReadOnlyState</c>,
/// <c>ForceReleaseLocks</c>, <c>RenameDocument</c>, <c>MoveDocument</c> and
/// <c>ReplaceReferencedDocument</c> with them, none of which the product calls (research R8.5, the
/// third question).
///
/// This class reflects the interop the extractor is built against and holds every member of the 34
/// interfaces the generated tables are written against - <see cref="Interfaces"/> - whose name
/// belongs to the save, rename, move and copy, replace, release and lock, read-only or rebuild families
/// (<see cref="BelongsToAFamily"/>) to one of three answers: a reader by section 2's prefixes, which
/// stays allowed; the member left allowed, with its reason (<see cref="Allowed"/>); or refused by
/// <see cref="ReadOnlyGuard"/> in both spellings a call site can hand it, and by every gate the product
/// builds but for the exceptions a guard was written for, each named with its reason
/// (<see cref="Exceptions"/>). A member a later interop adds fails here until someone decides which it
/// is, and so does a guard that comes to let another member through. Only metadata is read;
/// SOLIDWORKS is never started.
/// </summary>
public class DocumentWriteFamilyTests
{
    /// <summary>
    /// The 34 interfaces the generated tables are written against: the four of
    /// <see cref="DocumentLifecycleFamilyTests"/> (three until decision 144A added <c>IAssemblyDoc</c>,
    /// which this list named already); the document types a model document also is, whose
    /// saves, replaces and rebuilds act on that same document (004's guard-allowlist.md had recorded
    /// <c>IPartDoc.SaveToFile</c> to <c>SaveToFile3</c> as open); and every interface one of the
    /// guard's generated tables reflects - decision 21A's creation interfaces, <c>IFeatureManager</c>
    /// among them, and feature 011's 28 drawing families, <c>IDrawingDoc</c> among them. Widened on
    /// the decision's review: it read the first six only. Not every interface: the guard judges a
    /// name on any of them, and research R10.4 counts what the families hold on the others.
    /// </summary>
    internal static readonly string[] Interfaces =
        DocumentLifecycleFamilyTests.Interfaces
            .Concat(new[] { "IPartDoc", "IAssemblyDoc" })
            .Concat(CreationFamilyCompletenessTests.Families)
            .Concat(DrawingFamilyCompletenessTests.DrawingFamilies)
            .Distinct(StringComparer.Ordinal)
            .ToArray();

    /// <summary>
    /// The interfaces the families were found on with 32.5.0.48: the members must still be there. The
    /// others are read so that a later interop's member fails the tests until someone decides.
    /// </summary>
    private static readonly string[] InterfacesWithMembers =
    {
        "ISldWorks", "IModelDoc2", "IModelDocExtension", "IPartDoc", "IAssemblyDoc", "IFeatureManager",
        "IDrawingDoc", "ISheet", "IView", "IDimension", "IAnnotation", "INote", "ITableAnnotation",
        "IBomTableAnnotation",
    };

    /// <summary>
    /// The families, as a word of a member's name, read the way <see cref="DocumentLifecycleFamilyTests"/>
    /// reads its own: the word beginning with its capital - at the start of the name, after a COM
    /// twin's <c>I</c>, or where a word starts - and ending where the name does or the next word begins.
    /// <list type="bullet">
    /// <item><c>Save</c>: the members named for saving - the document, a file made from it
    /// (<c>SaveToFile</c>, <c>SaveDeFeaturedFile</c>), or what the save dialog offers
    /// (<c>AddFileSaveAsItem</c>). A file written under another word, an export or a publish
    /// (<c>ExportToDWG</c>, <c>PublishSTEP242File</c>), is not read here (research R10.4).</item>
    /// <item><c>Rename</c>, <c>Move</c> and <c>Copy</c>: the document's file renamed, moved or copied,
    /// and the references other documents hold to it updated. <c>Copy</c> is here because
    /// <c>ISldWorks.CopyDocument</c> is <c>MoveDocument</c>'s twin - the same arguments and options -
    /// and the word's other members copy the document's contents (<c>CopyWithMates</c>,
    /// <c>CopyDraftingStandard</c>) or its selection (<c>EditCopy</c>).</item>
    /// <item><c>Replace</c>: a referenced document or a component swapped for another.</item>
    /// <item><c>Release</c>, <c>Lock</c> and <c>Unlock</c>: the locks SOLIDWORKS holds on the file
    /// released (<c>ForceReleaseLocks</c>) and the storage streams it opens in it
    /// (<c>IRelease3rdPartyStorage</c>), and what locks or unlocks the document's references
    /// (<c>LockAllExternalReferences</c>) or the application's commands (<c>Lock</c>).</item>
    /// <item><c>ReadOnly</c>: the document's read-only state, which <c>SetReadOnlyState</c> would undo
    /// behind the check decision 136A added after every read-only open.</item>
    /// <item><c>Rebuild</c>: the rebuilds, which change the model and can resolve lightweight
    /// components.</item>
    /// </list>
    /// So <c>ForceReleaseLocks</c>, <c>UnLock</c> and <c>IRelease3rdPartyStorage</c> belong, and
    /// <c>HasRenamedDocuments</c>, a read whose prefix is none of section 2's, and
    /// <c>IsLightLockedToModel</c> do not.
    /// </summary>
    private static readonly Regex Family = new Regex(
        "(Save|Rename|Move|Copy|Replace|Release|Lock|Unlock|ReadOnly|Rebuild)(?![a-z])",
        RegexOptions.CultureInvariant);

    /// <summary>
    /// The family members left allowed by every guard, each with the product file whose call needs it
    /// and the reason. Keyed interface-qualified, though the guard matches bare names. A file, here
    /// and in <see cref="Exceptions"/>, is its path under the extractor folder, as the read audit's
    /// scan reports it (decision 140A's second pass, 2026-10-19).
    /// </summary>
    internal static readonly IReadOnlyDictionary<string, (string Where, string Reason)> Allowed =
        new Dictionary<string, (string Where, string Reason)>(StringComparer.Ordinal)
        {
            ["IModelDoc2.SaveBMP"] = ("SwReview.Extractor/Capture/SwCaptureView.cs",
                "the capture's image of a view: SwCaptureView gates the bare name on the session's read-only gate and "
                + "has it write a bitmap of the graphics window beside the capture's PNG, at the PNG's name with .bmp. "
                + "SaveBMP writes to whatever path it is handed, a document's included, and a guard judges names, never "
                + "paths: what keeps this path an image is the capture's own code, which names the PNG under the "
                + "captures folder of the directory the host chose and checks its extension with AssertSaveAs first. "
                + "SaveAs3 stays refused"),

            // Decision 144A (2026-10-19) moved IFeatureManager.MoveToFolder from here to the Exceptions
            // below: probe remodel's PROBE-5 needs it, so the read-only guard refuses it now and only
            // RemodelProbeGuard lets it through, as it does ForceRebuild3 and SaveAs3.
        };

    /// <summary>
    /// What a guard written for an exception lets through of these families, as the guard's type and
    /// the key, each with the product file whose call needs it and the exception it is - exactly these.
    /// The read-only guard, the confirmed drawing's guard and the re-modeler's pane seat's guard let none
    /// through.
    /// </summary>
    internal static readonly IReadOnlyDictionary<string, (string Where, string Reason)> Exceptions =
        new Dictionary<string, (string Where, string Reason)>(StringComparer.Ordinal)
        {
            ["SuppressTestGuard ForceRebuild3"] = ("SwReview.Extractor/Rms/SuppressTest.cs",
                "feature 003's engineer-run suppress-test rebuilds after its one suppression"),
            ["RemodelProbeGuard ForceRebuild3"] = ("SwReview.Extractor/Rms/SwRemodelProbeHost.cs",
                "probe remodel rebuilds its throwaway part after each step (feature 004 T032)"),
            ["RemodelProbeGuard SaveAs3"] = ("SwReview.Extractor/Rms/SwRemodelProbeHost.cs",
                "probe remodel saves its throwaway part into the run folder, behind RemodelProbe.AssertPartSavePath"),
            ["RemodelProbeGuard MoveToFolder"] = ("SwReview.Extractor/Rms/SwRemodelProbeHost.cs",
                "probe remodel's PROBE-5 moves a feature of its throwaway part into a folder (feature 004 T038): one of "
                + "RemodelProbeGuard's run-scoped members since decision 144A, under the bare name its host gates; never "
                + "the engineer's document, which probe remodel refuses to run beside"),
            ["RemodelGuard IModelDoc2.ForceRebuild3"] = ("SwReview.Extractor/Bridge/BridgeDispatcher.cs",
                "the re-modeler's one rebuild of its own copy (feature 004's stage-1 allowlist)"),
            ["RemodelGuard IModelDoc2.Save3"] = ("SwReview.Extractor/Bridge/BridgeDispatcher.cs",
                "the re-modeler's one save of its own copy, behind RemodelScope.AssertSaveTarget (feature 004's stage-1 allowlist)"),
        };

    internal static bool BelongsToAFamily(string name) => Family.IsMatch(name);

    /// <summary>Every family member of the interfaces, interface-qualified, readers included.</summary>
    internal static IReadOnlyList<string> FamilyMembers() => GuardSweep.Members(Interfaces, Family);

    private static IEnumerable<string> RefusedFamilyMembers() => GuardSweep.ToRefuse(FamilyMembers(), Allowed.Keys);

    [Theory]
    [InlineData("SaveAs4", true)]
    [InlineData("AddFileSaveAsItem2", true)]
    [InlineData("SaveTo3DExperience", true)]
    [InlineData("RenameDocument", true)]
    [InlineData("IMoveDocument", true)]
    [InlineData("ICopyDocument", true)]
    [InlineData("MoveOrCopy", true)]
    [InlineData("CopyWithMates2", true)]
    [InlineData("ReplaceComponents2", true)]
    [InlineData("ReloadOrReplace", true)]
    [InlineData("ForceReleaseLocks", true)]
    [InlineData("IRelease3rdPartyStorage", true)]
    [InlineData("UnLock", true)]
    [InlineData("UnlockAllExternalReferences", true)]
    [InlineData("SetReadOnlyState", true)]
    [InlineData("IsOpenedReadOnly", true)]
    [InlineData("EditRebuildAll", true)]
    [InlineData("set_EnableAssemblyRebuild", true)]
    [InlineData("HasRenamedDocuments", false)]
    [InlineData("IsLightLockedToModel", false)]
    [InlineData("ApplySavedSortScheme", false)]
    [InlineData("set_FocusLocked", false)]
    [InlineData("IGetReplacementSurfaces", false)]
    [InlineData("SetDatumTargetNotMoveable", false)]
    public void TheFamilyGrammarReadsWholeWords(string name, bool belongs)
    {
        Assert.Equal(belongs, BelongsToAFamily(name));
    }

    /// <summary>
    /// A floor, so a grammar or a reflection that found almost nothing cannot pass vacuously, and the
    /// members research R8.5, 004's guard-allowlist.md and the decision's review named are among what
    /// it finds.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void TheFamiliesAreFoundOnEachInterface()
    {
        IReadOnlyList<string> members = FamilyMembers();

        Assert.True(members.Count >= 100, "The family grammar found almost nothing: " + string.Join(", ", members));
        foreach (string face in InterfacesWithMembers)
        {
            Assert.Contains(face, Interfaces);
            Assert.Contains(members, key => key.StartsWith(face + ".", StringComparison.Ordinal));
        }

        foreach (string named in new[]
                 {
                     "IModelDoc2.Save", "IModelDoc2.Save2", "IModelDoc2.SaveAs", "IModelDoc2.SaveAs2", "IModelDoc2.SaveAs4",
                     "IModelDoc2.SaveAsSilent", "IModelDoc2.SaveSilent", "IModelDocExtension.SaveAs",
                     "IModelDocExtension.SaveAs2", "IModelDocExtension.SaveDeFeaturedFile",
                     "IModelDocExtension.SaveDraftingStandard", "IModelDocExtension.SaveTo3DExperience",
                     "IModelDocExtension.SaveViewToSolidworks", "ISldWorks.SaveSettings", "IModelDoc2.SetReadOnlyState",
                     "IModelDoc2.ForceReleaseLocks", "IModelDocExtension.SavePackAndGo", "IModelDocExtension.RenameDocument",
                     "ISldWorks.MoveDocument", "ISldWorks.ReplaceReferencedDocument", "IModelDoc2.SaveBMP",
                     "IModelDoc2.Rebuild", "IModelDocExtension.Rebuild", "IModelDocExtension.EditRebuildAll",
                     "IPartDoc.SaveToFile", "IPartDoc.SaveToFile2", "IPartDoc.SaveToFile3",
                     "IFeatureManager.MoveToFolder", "IFeatureManager.MoveRotateLiveSectionPlane",
                     "IFeatureManager.set_MoveSizeFeatures",
                 })
        {
            Assert.Contains(named, members);
        }
    }

    /// <summary>The heart of decision 140A: no member of the families is left callable by accident.</summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryFamilyMemberIsAReader_ANamedExclusion_OrRefusedBareAndQualified()
    {
        var callable = RefusedFamilyMembers()
            .Where(key => !GuardSweep.Refuses(ReadOnlyGuard.Assert, CallKey.BareName(key))
                || !GuardSweep.Refuses(ReadOnlyGuard.Assert, key))
            .ToList();

        Assert.True(
            callable.Count == 0,
            "Members of the save, rename, move, copy, replace, release, lock, read-only and rebuild families the "
                + "read-only guard does not refuse in both spellings: refuse each (the shared rows of "
                + "extractor/tools/list-writer-members.ps1, contracts/guard.md section 1) or name it in Allowed with "
                + "its reason: " + string.Join(", ", callable));
    }

    /// <summary>
    /// Every gate the product builds refuses them in both spellings, except exactly
    /// <see cref="Exceptions"/>: a guard that comes to let another member through, or that no longer
    /// lets one of these through, fails here, so an exception cannot widen, or outlive its guard,
    /// unnoticed.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryGateTheProductBuildsLetsThroughOnlyTheNamedExceptions() =>
        GuardSweep.AssertLetThroughExactly(GuardSweep.Spellings(RefusedFamilyMembers()), Exceptions);

    /// <summary>The reads among the families stay allowed in both spellings (FR-006): the two the product calls above all.</summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void TheReadersAmongThemStayAllowed()
    {
        var readers = FamilyMembers().Where(key => DrawingFamilyCompletenessTests.IsReader(CallKey.BareName(key))).ToList();

        Assert.Contains("IModelDoc2.GetSaveFlag", readers);
        Assert.Contains("IModelDoc2.IsOpenedReadOnly", readers);
        foreach (string key in readers)
        {
            ReadOnlyGuard.Assert(CallKey.BareName(key));
            ReadOnlyGuard.Assert(key);
        }
    }

    /// <summary>
    /// Each member left allowed is a family member of the interop, not a reader, allowed in both
    /// spellings, with a reason, named by the generated "Not denied (feature 011)" table, and still a
    /// literal of the product file whose call needs it - so the list cannot go stale and hide a later
    /// member behind an entry nobody needs.
    /// </summary>
    [RemodelInteropManifestTests.InteropAssembliesPresentFact]
    public void EveryAllowedMemberIsAFamilyMemberLeftAllowedWithTheContractsReason()
    {
        IReadOnlyList<string> members = FamilyMembers();
        IReadOnlyList<(string Literal, string Where)> literals = DrawingFamilyReadAuditTests.Literals();

        foreach (KeyValuePair<string, (string Where, string Reason)> entry in Allowed)
        {
            string bare = CallKey.BareName(entry.Key);
            Assert.Contains(entry.Key, members);
            Assert.False(DrawingFamilyCompletenessTests.IsReader(bare), $"{entry.Key} is a reader; readers need no entry.");
            Assert.False(string.IsNullOrWhiteSpace(entry.Value.Reason), $"{entry.Key} has no reason.");
            ReadOnlyGuard.Assert(bare);
            ReadOnlyGuard.Assert(entry.Key);
            Assert.Contains(bare, DrawingFamilyDenylistTests.ExcludedMembers, StringComparer.OrdinalIgnoreCase);
            Assert.True(
                literals.Any(literal => literal.Literal == bare && literal.Where == entry.Value.Where),
                $"{entry.Key} is no longer named in {entry.Value.Where}; drop it, or say what calls it now.");
        }
    }

    /// <summary>
    /// Each exception's key is still a literal of the product file whose call needs it, so one guard's
    /// exception cannot be kept alive by another's call of the same member.
    /// </summary>
    [Fact]
    public void EveryExceptionIsStillNamedByTheProduct() => GuardSweep.AssertEveryExceptionIsStillNamed(Exceptions);
}

/// <summary>
/// Decision 17A (2026-09-25), feature 004 T150. <see cref="ReadOnlyGuard"/>'s denylist let the
/// FeatureWorks members - which recognize features on an imported body and build them into the
/// part - and the import-repair writers through as bare names: <c>RecognizeFeatureAutomatic</c>,
/// <c>CreateFeatures</c> and <c>ImportDiagnosis</c> passed a read-only gate.
///
/// <b>The "Decision 17A" table of <c>004-resilient-remodeler/contracts/guard-allowlist.md</c> is
/// the membership, and this class reads it</b>, as <see cref="MechanicalChecksDenylistTests"/>
/// reads feature 010's. The members deliberately left open are the "Left open" table beside it,
/// each with its reason, and on a machine with the interop every method of FeatureWorks'
/// <c>IFeatureWorksApp</c> is on one table or the other. None of these members is called; adding
/// them is a narrowing, so no constitution exception arises, and a product literal the table
/// would refuse fails here rather than on a seat.
/// </summary>
public class ImportRepairDenylistTests
{
    private const string AllowlistFileName = "guard-allowlist.md";

    private const string Document = "specs/004-resilient-remodeler/contracts/guard-allowlist.md (decision 17A)";

    internal const string TableHeader = "| Member (decision 17A) | What it writes |";

    internal const string LeftOpenHeader = "| Left open (decision 17A) | Why |";

    /// <summary>The table's rows, members interface-qualified as the table writes them.</summary>
    public static readonly IReadOnlyList<(string Family, string[] Members)> QualifiedTable = DenylistTable.Parse(
        AllowlistFileName, Document, TableHeader, minimumRows: 8, keepQualifier: true);

    /// <summary>The names the section leaves callable, each with its reason.</summary>
    public static readonly IReadOnlyList<(string Family, string[] Members)> LeftOpen = DenylistTable.Parse(
        AllowlistFileName, Document + " left open", LeftOpenHeader, minimumRows: 4, keepQualifier: true);

    /// <summary>The distinct bare names the table denies: the expected set, derived.</summary>
    public static IReadOnlyCollection<string> ExpectedMembers =>
        new HashSet<string>(QualifiedKeys.Select(CallKey.BareName), StringComparer.OrdinalIgnoreCase);

    internal static IReadOnlyList<string> QualifiedKeys =>
        QualifiedTable.SelectMany(row => row.Members).Distinct(StringComparer.Ordinal).ToList();

    internal static IReadOnlyCollection<string> LeftOpenNames =>
        new HashSet<string>(LeftOpen.SelectMany(row => row.Members), StringComparer.Ordinal);

    public static IEnumerable<object[]> EveryMember() =>
        ExpectedMembers.OrderBy(member => member, StringComparer.Ordinal)
            .Select(member => new object[] { member });

    public static IEnumerable<object[]> EveryQualifiedMember() =>
        QualifiedKeys.OrderBy(key => key, StringComparer.Ordinal).Select(key => new object[] { key });

    [Fact]
    public void EveryRowNamesItsMembersWithTheirInterface()
    {
        foreach (string key in QualifiedKeys)
        {
            Assert.True(CallKey.IsQualified(key), $"'{key}' in the decision 17A table names no interface.");
        }
    }

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheTableIsRefused(string member)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member));
        Assert.Equal(member, error.MemberName);
        Assert.Throws<MutatingCallError>(() => ReadOnlyCallGuard.Instance.Assert(member));
    }

    [Theory]
    [MemberData(nameof(EveryQualifiedMember))]
    public void EveryMemberOfTheTableIsRefusedQualifiedWithItsInterface(string key)
    {
        MutatingCallError error = Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(key));
        Assert.Equal(key, error.MemberName);
        Assert.Throws<MutatingCallError>(() => ReadOnlyCallGuard.Instance.Assert(key));
    }

    [Theory]
    [MemberData(nameof(EveryMember))]
    public void EveryMemberOfTheTableIsRefusedWhateverItsCase(string member)
    {
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToUpperInvariant()));
        Assert.Throws<MutatingCallError>(() => ReadOnlyGuard.Assert(member.ToLowerInvariant()));
    }

    /// <summary>
    /// No gate the product builds is exempted from any of them: the suppress-test gate's two
    /// exemptions, <c>probe remodel</c>'s throwaway-part recipe, the re-modeler's stage-1
    /// allowlist, the confirmed drawing's open and the re-modeler's pane seat all refuse every
    /// member, bare or qualified. Edited deliberately for decision 144A (2026-10-19): the gates are
    /// <see cref="GuardSweep.ProductGates"/>, which holds every guard the product defines - the read-only
    /// guard and the pane seat's as well as the four this listed by hand.
    /// </summary>
    [Theory]
    [MemberData(nameof(EveryQualifiedMember))]
    public void EveryGateTheProductBuildsRefusesThem(string key)
    {
        string member = CallKey.BareName(key);
        foreach (ICallGuard gate in GuardSweep.ProductGates())
        {
            Assert.Throws<MutatingCallError>(() => gate.Assert(member));
            Assert.Throws<MutatingCallError>(() => gate.Assert(key));
        }
    }

    /// <summary>
    /// Feature 004's allowlist is asserted against the read-only denied surface; a denial that
    /// shared a stage-1 key's bare name would change the keys that override a denial, and one of
    /// <see cref="RemodelGuard.ExcludedMembers"/> would make that list redundant.
    /// </summary>
    [Fact]
    public void NoMemberOfTheTableIsAStage1KeyOrARemodelExclusion()
    {
        var bareKeys = new HashSet<string>(
            RemodelGuard.AllowedKeys.Select(CallKey.BareName), StringComparer.OrdinalIgnoreCase);

        Assert.DoesNotContain(ExpectedMembers, bareKeys.Contains);
        Assert.Empty(ExpectedMembers.Intersect(RemodelGuard.ExcludedMembers, StringComparer.OrdinalIgnoreCase));
    }

    [Fact]
    public void TheTableAddsNothingAnEarlierTableOrPrefixAlreadyDenied()
    {
        Assert.Empty(ExpectedMembers.Intersect(StandardsDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase));
        Assert.Empty(ExpectedMembers.Intersect(MechanicalChecksDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase));
        Assert.Empty(ExpectedMembers.Intersect(DrawingFamilyDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase));
        Assert.DoesNotContain(
            ExpectedMembers,
            member => ReadOnlyGuard.DeniedPrefixes.Any(
                prefix => member.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)));
    }

    /// <summary>
    /// "Without breaking anything the product legitimately calls": no string literal of the
    /// product source - every gated call site names its member in one - is refused by the table,
    /// read by the same scan <see cref="DrawingFamilyReadAuditTests"/> runs.
    /// </summary>
    [Fact]
    public void NoLiteralOfTheProductSourceIsRefusedByTheTable()
    {
        var table = new HashSet<string>(ExpectedMembers, StringComparer.OrdinalIgnoreCase);
        var refused = DrawingFamilyReadAuditTests.Literals()
            .Where(literal => table.Contains(DrawingFamilyReadAuditTests.Judged(literal.Literal)))
            .Select(literal => $"\"{literal.Literal}\" in {literal.Where}")
            .Distinct(StringComparer.Ordinal)
            .ToList();

        Assert.True(
            refused.Count == 0,
            "The decision 17A denials refuse a name the product source uses: " + string.Join(", ", refused));
    }

    /// <summary>The reads beside them stay allowed, and so does what the section leaves open.</summary>
    [Theory]
    [InlineData("GetImportedFileName")]
    [InlineData("GetImportedFeatureParameters")]
    [InlineData("GetImportFileData")]
    [InlineData("Diagnose")]
    [InlineData("GetGapsCount")]
    [InlineData("GetEdgeInformation")]
    [InlineData("GetTypeName2")]
    public void TheReadsBesideThemStayAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
    }

    public static IEnumerable<object[]> EveryLeftOpenMember() =>
        LeftOpenNames.Where(name => !name.Contains("*"))
            .OrderBy(name => name, StringComparer.Ordinal)
            .Select(name => new object[] { name });

    [Theory]
    [MemberData(nameof(EveryLeftOpenMember))]
    public void WhatTheSectionLeavesOpenIsOpenAndNotAlsoOnTheTable(string key)
    {
        ReadOnlyGuard.Assert(CallKey.BareName(key));
        Assert.DoesNotContain(CallKey.BareName(key), ExpectedMembers, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Every member the table names is declared on the interface it names, on the interop the
    /// extractor is built against: a mis-spelled denial would refuse nothing.
    /// </summary>
    [FeatureWorksInteropPresentFact]
    public void EveryMemberOfTheTableIsOnTheInstalledInterop()
    {
        foreach (string key in QualifiedKeys)
        {
            Type type = InterfaceType(CallKey.InterfaceName(key));
            Assert.True(
                type.GetMethods(BindingFlags.Public | BindingFlags.Instance)
                    .Any(method => method.Name == CallKey.BareName(key)),
                $"{key} is not declared on {type.Assembly.GetName().Name} {type.Assembly.GetName().Version}.");
        }
    }

    /// <summary>
    /// FeatureWorks' whole API surface is accounted for: every method of <c>IFeatureWorksApp</c>
    /// is denied or named as left open with its reason, so a writer it gains in a later release
    /// is a red test, not a member nobody gated.
    /// </summary>
    [FeatureWorksInteropPresentFact]
    public void EveryFeatureWorksMethodIsDeniedOrLeftOpenWithAReason()
    {
        Type featureWorks = InterfaceType("IFeatureWorksApp");
        var accounted = new HashSet<string>(QualifiedKeys.Concat(LeftOpenNames), StringComparer.Ordinal);

        var unaccounted = featureWorks.GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Select(method => "IFeatureWorksApp." + method.Name)
            .Distinct(StringComparer.Ordinal)
            .Where(key => !accounted.Contains(key))
            .ToList();

        Assert.True(
            unaccounted.Count == 0,
            "IFeatureWorksApp methods on neither decision 17A table: " + string.Join(", ", unaccounted));
    }

    private static Type InterfaceType(string name)
    {
        string redist = RemodelInteropManifestTests.InstalledInterop.RedistDirectory()!;
        string assembly = name == "IFeatureWorksApp" ? FeatureWorksInterop : "SolidWorks.Interop.sldworks";
        string space = name == "IFeatureWorksApp" ? "SolidWorks.Interop.fworks." : "SolidWorks.Interop.sldworks.";
        Type? type = RemodelInteropManifestTests.InstalledInterop.Load(redist, assembly).GetType(space + name);
        Assert.True(type != null, $"{name} is not on {assembly}.");
        return type!;
    }

    internal const string FeatureWorksInterop = "SolidWorks.Interop.fworks";

    /// <summary>
    /// A <c>[Fact]</c> that reports itself skipped, with the reason, where the SOLIDWORKS interop
    /// or its FeatureWorks assembly is not installed; xUnit 2 decides <c>Skip</c> at discovery.
    /// </summary>
    internal sealed class FeatureWorksInteropPresentFactAttribute : FactAttribute
    {
        public FeatureWorksInteropPresentFactAttribute()
        {
            string? redist = RemodelInteropManifestTests.InstalledInterop.RedistDirectory();
            if (redist == null || !File.Exists(Path.Combine(redist, FeatureWorksInterop + ".dll")))
            {
                Skip = "SolidWorks.Interop.sldworks.dll or SolidWorks.Interop.fworks.dll is not installed "
                    + "(looked in %SWREVIEW_SW_REDIST% and the default SOLIDWORKS api\\redist folder).";
            }
        }
    }
}
