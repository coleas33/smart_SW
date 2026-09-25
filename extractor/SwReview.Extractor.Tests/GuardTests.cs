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
    /// <see cref="DrawingOpenGuard"/>) accept a qualified writer key, and they judge it before this
    /// guard is asked; a qualified key on a read-only gate had passed whatever it named.
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
    /// feature 004's two opens of documents it created (found by the read audit, T003).
    /// </summary>
    [Fact]
    public void EveryExclusionHasOneOfTheContractsReasons()
    {
        var sanctionedCalls = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "OpenDoc6",
            "OpenDoc7",
            "NewDocument",
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
    /// read-only model open, feature 004's copy open and throwaway part, and the two shared names
    /// feature 004's allowlist keys carry.
    /// </summary>
    [Theory]
    [InlineData("OpenDoc6")]
    [InlineData("OpenDoc7")]
    [InlineData("NewDocument")]
    [InlineData("CloseDoc")]
    [InlineData("SetUserPreferenceToggle")]
    [InlineData("set_Name")]
    [InlineData("Select2")]
    public void TheSanctionedCallsStayAllowed(string member)
    {
        ReadOnlyGuard.Assert(member);
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

    /// <summary>contracts/guard.md section 1: the two shared families, named members only.</summary>
    internal static readonly string[] SharedFamilies = { "ISldWorks", "IModelDocExtension" };

    /// <summary>contracts/guard.md section 2: a name starting with one of these is a reader.</summary>
    private static readonly string[] ReaderPrefixes = { "get_", "Get", "IGet", "Is" };

    /// <summary>contracts/guard.md section 2: the writer grammar.</summary>
    private static readonly Regex WriterGrammar = new Regex(
        "^(set_|Set|ISet|Add|IAdd|Insert|IInsert|Delete|Remove|Edit|Modify|Change|Reset|Activate|"
            + "Attach|Detach|Update|Replace|Break|Hide|Show|Move|Align|Suppress|Unsuppress|Rebuild|"
            + "Convert|Create|ICreate|Make|Lock|Unlock|Sort|Split|Merge|Rotate|Scale|Flip|Link|Unlink|"
            + "Import|Explode|Clear|Apply|Restore|Save|Dissolve|Expand|Collapse|Reload|Rename|New|Paste|"
            + "Copy|Cut|Drag|Close|Quit|Open|Load|Unload|Regenerate|Reorder|Auto|Dimension|Reverse|Swap|"
            + "Toggle|Enable|Disable|Select|Purge|Relink|Resolve|Crop|Unbreak|Force|Hatch|Offset|"
            + "Position|Freeze|Unfreeze)",
        RegexOptions.CultureInvariant);

    /// <summary>
    /// The installed interop the build references (<c>$(SwRedist)</c>, or <c>SWREVIEW_SW_REDIST</c>),
    /// found and loaded for its metadata by the locator the interop-manifest tests use.
    /// </summary>
    private static Assembly Interop => RemodelInteropManifestTests.InstalledInterop.Load(
        RemodelInteropManifestTests.InstalledInterop.RedistDirectory()!, "SolidWorks.Interop.sldworks");

    private static Type InterfaceType(string name)
    {
        Type? type = Interop.GetType("SolidWorks.Interop.sldworks." + name);
        Assert.True(type != null, $"{name} is not on {Interop.GetName().Name} {Interop.GetName().Version}.");
        return type!;
    }

    private static IEnumerable<string> MethodNames(string interfaceName) =>
        InterfaceType(interfaceName)
            .GetMethods(BindingFlags.Public | BindingFlags.Instance)
            .Select(method => method.Name)
            .Distinct(StringComparer.Ordinal);

    internal static bool IsWriter(string name) =>
        !ReaderPrefixes.Any(prefix => name.StartsWith(prefix, StringComparison.Ordinal))
        && WriterGrammar.IsMatch(name);

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
    /// <summary>The literals the table refuses that are not member names the product gates.</summary>
    private static readonly IReadOnlyDictionary<string, string> NamedLiterals =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["ActivateDoc3"] = "Program.cs: a member probe standards asserts is absent from its gate log",
            ["LoadFile4"] = "Program.cs: a member probe standards asserts is absent from its gate log",
            ["dimensions"] = "Ir/DrawingSheet.cs: a JSON property name, matching IDrawingDoc.Dimensions only by case",
            ["dissolve"] = "Bridge/BridgeProtocol.cs: a remodel.folder operation name in the protocol",
        };

    private static readonly Regex StringLiteral = new Regex("\"((?:[^\"\\\\\\r\\n]|\\\\.)*)\"", RegexOptions.Compiled);

    private static readonly string[] ProductSourceRoots =
    {
        "SwReview.Extractor",
        "SwReview.AddIn",
        "SwReview.Extractor.Console",
    };

    /// <summary>The extractor folder: the one holding SwReview.sln, found upward from the test assembly.</summary>
    private static string ExtractorRoot()
    {
        DirectoryInfo? directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory != null && !File.Exists(Path.Combine(directory.FullName, "SwReview.sln")))
        {
            directory = directory.Parent;
        }

        Assert.True(directory != null, "SwReview.sln was not found above " + AppContext.BaseDirectory);
        return directory!.FullName;
    }

    private static IEnumerable<string> ProductSourceFiles()
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

    internal static IReadOnlyList<(string Literal, string Where)> Literals()
    {
        var found = new List<(string, string)>();
        foreach (string file in ProductSourceFiles())
        {
            string text = File.ReadAllText(file);
            foreach (Match match in StringLiteral.Matches(text))
            {
                found.Add((match.Groups[1].Value, Path.GetFileName(file)));
            }
        }

        return found;
    }

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
    /// A literal as the read-only guard judges it: its member half when it is an
    /// interface-qualified key (feature 011 review, 2026-09-23), unless it is a key of one of the
    /// two allowlist guards, which judge their own keys before the read-only guard is asked.
    /// </summary>
    internal static string Judged(string literal) =>
        CallKey.IsQualified(literal)
            && !RemodelGuard.AllowedKeys.Contains(literal)
            && !DrawingOpenGuard.AllowedKeys.Contains(literal)
            ? CallKey.BareName(literal)
            : literal;

    [Fact]
    public void NoLiteralOfTheProductSourceIsRefusedByTheTableExceptTheNamedOnes()
    {
        var table = new HashSet<string>(DrawingFamilyDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase);
        var refused = Literals()
            .Where(literal => table.Contains(Judged(literal.Literal)) && !NamedLiterals.ContainsKey(literal.Literal))
            .Select(literal => $"\"{literal.Literal}\" in {literal.Where}")
            .Distinct(StringComparer.Ordinal)
            .ToList();

        Assert.True(
            refused.Count == 0,
            "The feature 011 denials refuse a name the product source uses; a read that needs a refused "
                + "member is a read that writes and is redesigned, never exempted: " + string.Join(", ", refused));
    }

    /// <summary>
    /// Each named literal is still in the source and still refused, so the list cannot go stale
    /// and hide a later collision behind an entry nobody needs.
    /// </summary>
    [Fact]
    public void EveryNamedLiteralIsStillInTheSourceAndStillRefused()
    {
        IReadOnlyList<(string Literal, string Where)> literals = Literals();
        foreach (KeyValuePair<string, string> named in NamedLiterals)
        {
            Assert.Contains(literals, literal => string.Equals(literal.Literal, named.Key, StringComparison.Ordinal));
            Assert.Contains(named.Key, DrawingFamilyDenylistTests.ExpectedMembers, StringComparer.OrdinalIgnoreCase);
        }
    }
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
    /// allowlist and the confirmed drawing's open all refuse every member, bare or qualified.
    /// </summary>
    [Theory]
    [MemberData(nameof(EveryQualifiedMember))]
    public void EveryGateTheProductBuildsRefusesThem(string key)
    {
        string member = CallKey.BareName(key);
        foreach (ICallGuard gate in new ICallGuard[]
                 {
                     new SuppressTestGuard(),
                     new RemodelProbeGuard(),
                     new RemodelGuard(),
                     new DrawingOpenGuard(),
                 })
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
