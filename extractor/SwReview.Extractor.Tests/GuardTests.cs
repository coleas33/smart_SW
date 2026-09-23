using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
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
        string fileName, string documentName, string tableHeader, int minimumRows)
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
                .Select(name => name.Substring(name.LastIndexOf('.') + 1))
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
        /// qualifier is dropped here exactly as `SwGate.Call` drops it.
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
