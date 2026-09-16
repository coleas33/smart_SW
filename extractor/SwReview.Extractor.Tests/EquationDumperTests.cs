using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T037. The equation dumper over a fake <see cref="IEquationReader"/>, on a machine with
/// no SOLIDWORKS seat - the same split <see cref="FeatureDumperTests"/> pins for the
/// feature tree.
///
/// Four properties matter more than the field-by-field mapping:
///
///   * <b>Once per document.</b> A part used forty times has one equation list, not forty;
///     rows per instance would multiply every finding by the instance count.
///   * <b>`is_global` is SOLIDWORKS' answer, never ours.</b> It comes off
///     <c>GlobalVariable(i)</c>, not from parsing the text (research R5): the two rules the
///     equations carry are decided by that flag, and guessing it from the text is exactly
///     the silent wrong answer the rules exist to avoid.
///   * <b>Nothing is defaulted.</b> A read that failed is null plus an `equations` gap, so
///     the rule layer reports unresolved instead of "this part has no global variables".
///   * <b>Nothing mutates.</b> Every read goes through the gate, under the member names the
///     read-only guard and the SC-004 audit see.
/// </summary>
public class EquationDumperTests
{
    private const string AssemblyPath = @"C:\vault\bracket-assy\bracket-assy.SLDASM";
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
    private const string CoverPath = @"C:\vault\bracket-assy\cover.SLDPRT";

    private readonly FakeEquationReader _reader = new FakeEquationReader();
    private readonly RecordingObserver _observer = new RecordingObserver();
    private readonly SwGate _gate = new SwGate();

    private DumpScope _scope = null!;

    public EquationDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- one list per document ---------------------------------------------------

    [Fact]
    public void Dump_ReadsEachDocumentOnce_NotOncePerInstance()
    {
        _reader.Add(HousingPath).Equations.Add(Eq("\"WallThickness\" = 3", global: true, value: 3));

        IReadOnlyList<Equation> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("housing-2", HousingPath));

        Assert.Equal(new[] { "\"WallThickness\" = 3" }, rows.Select(r => r.Text));
        Assert.Equal(new[] { HousingPath }, _reader.DocumentRequests);
        Assert.Equal(new[] { HousingPath }, _reader.ManagerRequests);
    }

    [Fact]
    public void Dump_AssemblyDocuments_AreNotRead()
    {
        // The one assembly-equation rule is unresolved coverage by construction
        // ("assembly equations not extracted", contracts/rules.md), so the assembly's own
        // manager is never opened and no row claims to describe it.
        _reader.Add(AssemblyPath).Equations.Add(Eq("\"Pitch\" = 10", global: true, value: 10));

        Assert.Empty(Dump(Root()));
        Assert.Empty(_reader.DocumentRequests);
    }

    [Fact]
    public void Dump_NumbersRowsByThePositionInTheEquationManager()
    {
        FakeEquationDocument housing = _reader.Add(HousingPath);
        housing.Equations.Add(Eq("\"WallThickness\" = 3", global: true, value: 3));
        housing.Equations.Add(Eq("\"D1@Sketch1\" = \"WallThickness\" * 2", global: false, value: 6));

        IReadOnlyList<Equation> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.Equal(new[] { 0, 1 }, rows.Select(r => r.Index));
        Assert.Equal(
            new[] { _scope.DocumentId(HousingPath), _scope.DocumentId(HousingPath) },
            rows.Select(r => r.DocumentId));
    }

    [Fact]
    public void Dump_EachDocumentsRowsCarryItsOwnDocumentId()
    {
        _reader.Add(HousingPath).Equations.Add(Eq("\"A\" = 1", global: true, value: 1));
        _reader.Add(CoverPath).Equations.Add(Eq("\"B\" = 2", global: true, value: 2));

        IReadOnlyList<Equation> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Equal(
            new[] { _scope.DocumentId(HousingPath), _scope.DocumentId(CoverPath) },
            rows.Select(r => r.DocumentId));
        Assert.Equal(new[] { 0, 0 }, rows.Select(r => r.Index));
    }

    // ---- text and lhs ------------------------------------------------------------

    [Theory]
    [InlineData("\"WallThickness\" = 3", "WallThickness")]
    [InlineData("\"D1@Sketch1\" = \"WallThickness\" * 2", "D1@Sketch1")]
    [InlineData("\"Ratio\" = \"A\" / \"B\" = 2", "Ratio")]
    [InlineData("  \"Spaced\"   =  1 ", "Spaced")]
    [InlineData("Unquoted = 1", "Unquoted")]
    public void Dump_LhsIsLeftOfTheFirstEqualsWithQuotesStripped(string text, string expected)
    {
        _reader.Add(HousingPath).Equations.Add(Eq(text, global: true, value: 1));

        Equation row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Equal(text, row.Text);
        Assert.Equal(expected, row.Lhs);
    }

    [Fact]
    public void Dump_TextWithNoEquals_IsItsOwnLhs()
    {
        // The equation manager also hands back rows that are not assignments. Splitting on
        // a '=' that is not there must not silently drop the text the engineer will read as
        // evidence, so the whole row becomes the lhs and nothing is invented.
        _reader.Add(HousingPath).Equations.Add(Eq("\"just a comment\"", global: false, value: 0));

        Equation row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Equal("just a comment", row.Lhs);
    }

    // ---- is_global and value -----------------------------------------------------

    [Fact]
    public void Dump_IsGlobalComesFromTheSourceFlag_NotFromTheText()
    {
        // The text of a global and of a driven dimension look alike enough that parsing
        // them is a coin flip; GlobalVariable(i) is the only honest source (research R5).
        FakeEquationDocument housing = _reader.Add(HousingPath);
        housing.Equations.Add(Eq("\"D1@Sketch1\" = 3", global: true, value: 3));
        housing.Equations.Add(Eq("\"WallThickness\" = 4", global: false, value: 4));

        IReadOnlyList<Equation> rows = Dump(Root(), Part("housing-1", HousingPath));

        Assert.Equal(new bool?[] { true, false }, rows.Select(r => r.IsGlobal));
    }

    [Fact]
    public void Dump_GlobalVariableThatThrows_IsNullPlusAnEquationsGap()
    {
        // Both equation rules are unresolved when any is_global is null (contracts/rules.md),
        // so false here would report "this part has no global variables" about a flag
        // SOLIDWORKS never gave.
        FakeEquation broken = Eq("\"WallThickness\" = 3", global: true, value: 3);
        broken.GlobalThrows = true;
        _reader.Add(HousingPath).Equations.Add(broken);

        Equation row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.IsGlobal);
        Assert.Equal(3.0, row.Value);
        AssertGap("GlobalVariable");
    }

    [Fact]
    public void Dump_ValueThatThrows_IsNullPlusAnEquationsGap()
    {
        FakeEquation broken = Eq("\"WallThickness\" = 3", global: true, value: 3);
        broken.ValueThrows = true;
        _reader.Add(HousingPath).Equations.Add(broken);

        Equation row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Null(row.Value);
        Assert.True(row.IsGlobal);
        AssertGap("Value");
    }

    [Fact]
    public void Dump_ValueOfZero_IsZeroAndNotNull()
    {
        // A zero value and an unreadable one are different answers; recording zero as null
        // would make an evidence line say the value is unknown when it is 0.
        _reader.Add(HousingPath).Equations.Add(Eq("\"Offset\" = 0", global: true, value: 0));

        Equation row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Equal(0.0, row.Value);
    }

    // ---- the manager -------------------------------------------------------------

    [Fact]
    public void Dump_ManagerThatCouldNotBeRead_IsAGapAndNoRowsForThatDocument()
    {
        _reader.Add(HousingPath).ManagerFailure = new InvalidOperationException("the manager went away");
        _reader.Add(CoverPath).Equations.Add(Eq("\"B\" = 2", global: true, value: 2));

        IReadOnlyList<Equation> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Equal(new[] { _scope.DocumentId(CoverPath) }, rows.Select(r => r.DocumentId));
        Gap gap = AssertGap("the manager went away");
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
    }

    [Fact]
    public void Dump_DocumentWithNoEquationManager_IsAGapAndNoRows()
    {
        // T037: "manager unavailable -> empty list plus gap". A manager SOLIDWORKS never
        // handed over is a different answer from a manager that was read and holds nothing:
        // with no gap here, rms.params.global_variables_present reports "the equation
        // manager holds no equations" about a manager nobody opened (Principle I), and
        // `probe rms` already prints that state separately.
        _reader.Add(HousingPath).HasManager = false;

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));

        Gap gap = AssertGap("no equation manager");
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
    }

    [Fact]
    public void Dump_DocumentWithNoEquations_IsNoRowsAndNoGap()
    {
        // A part with no equations is exactly what rms.params.global_variables_present is
        // there to find. A gap here would turn every such finding into unresolved coverage.
        _reader.Add(HousingPath);

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_CountThatThrows_IsAGapAndNoRowsForThatDocument()
    {
        _reader.Add(HousingPath).CountFailure = new InvalidOperationException("GetCount failed");
        _reader.Add(CoverPath).Equations.Add(Eq("\"B\" = 2", global: true, value: 2));

        IReadOnlyList<Equation> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("cover-1", CoverPath));

        Assert.Equal(new[] { _scope.DocumentId(CoverPath) }, rows.Select(r => r.DocumentId));
        AssertGap("GetCount failed");
    }

    [Fact]
    public void Dump_EquationTextThatThrows_IsAGapAndTheOtherRowsAreStillRead()
    {
        // One unreadable row does not hide the rest: the gap says an equation is missing,
        // and the remaining rows keep the index the manager gave them.
        FakeEquationDocument housing = _reader.Add(HousingPath);
        FakeEquation broken = Eq("\"WallThickness\" = 3", global: true, value: 3);
        broken.TextThrows = true;
        housing.Equations.Add(broken);
        housing.Equations.Add(Eq("\"D1@Sketch1\" = 6", global: false, value: 6));

        Equation row = Assert.Single(Dump(Root(), Part("housing-1", HousingPath)));

        Assert.Equal(1, row.Index);
        AssertGap("Equation");
    }

    [Fact]
    public void Dump_EquationWithNoText_IsAGapAndNoRow()
    {
        FakeEquation blank = Eq(null!, global: true, value: 1);
        _reader.Add(HousingPath).Equations.Add(blank);

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));
        AssertGap("no text");
    }

    // ---- component state ---------------------------------------------------------

    [Theory]
    [InlineData(SuppressionState.Lightweight)]
    [InlineData(SuppressionState.Suppressed)]
    [InlineData(SuppressionState.Unloaded)]
    public void Dump_ComponentThatIsNotResolved_IsAGapAndIsNeverResolved(SuppressionState state)
    {
        _reader.Add(HousingPath).Equations.Add(Eq("\"A\" = 1", global: true, value: 1));

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath, state)));

        Gap gap = AssertGap(PackageSerializer.EnumToJsonName(state));
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal("cmp:0002", gap.EntityId);
        Assert.Empty(_reader.DocumentRequests);
    }

    [Fact]
    public void Dump_OneUnresolvedInstance_DoesNotStopAResolvedOneOfTheSameDocument()
    {
        _reader.Add(HousingPath).Equations.Add(Eq("\"A\" = 1", global: true, value: 1));

        IReadOnlyList<Equation> rows = Dump(
            Root(),
            Part("housing-1", HousingPath, SuppressionState.Lightweight),
            Part("housing-2", HousingPath));

        Assert.Single(rows);
        Assert.Single(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_ComponentWithNoLoadedDocument_IsAGapAndNoRows()
    {
        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));

        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityId == "cmp:0002");
        Assert.Equal("equations", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains("no loaded model document", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_DocumentNoInstanceCouldOpen_IsAlsoAGapUnderTheDocumentId()
    {
        // The per-instance gap above names a component (cmp:NNNN), and the rules look a
        // document's gap up by its DOCUMENT id (checks/rms/part.py, document_gap), so a
        // component-scoped gap alone is invisible to them: both equation rules would grade
        // an empty list and report "this part has no global variables" about a document
        // nobody opened (Principle I).
        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));

        string documentId = _scope.DocumentId(HousingPath);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityId == documentId);
        Assert.Equal("equations", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains("housing.SLDPRT", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_DocumentWhoseOpenThrew_IsAlsoAGapUnderTheDocumentId()
    {
        _reader.Add(HousingPath).DocumentFailure =
            new InvalidOperationException("GetModelDoc2 failed");

        Assert.Empty(Dump(Root(), Part("housing-1", HousingPath)));

        string documentId = _scope.DocumentId(HousingPath);
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityId == documentId);
        Assert.Equal("equations", gap.EntityKind);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);

        // The exception itself is still the per-instance gap, with the error text on it.
        Gap thrown = Assert.Single(_scope.Gaps.Gaps, g => g.EntityId == "cmp:0002");
        Assert.Contains("GetModelDoc2 failed", thrown.Error ?? string.Empty, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_OneInstanceWithNoLoadedDocument_IsNoDocumentGapWhenAnotherInstanceOpens()
    {
        // The same reason the unresolved instance above does not mark the document read:
        // the document's equations WERE read, and a document-scoped gap would turn a whole
        // answer into unresolved coverage for every rule that reads it.
        _reader.Add(HousingPath).Equations.Add(Eq("\"A\" = 1", global: true, value: 1));
        _reader.Unloaded.Add("housing-1");

        IReadOnlyList<Equation> rows = Dump(
            Root(), Part("housing-1", HousingPath), Part("housing-2", HousingPath));

        Assert.Single(rows);
        string documentId = _scope.DocumentId(HousingPath);
        Assert.DoesNotContain(_scope.Gaps.Gaps, g => g.EntityId == documentId);
        Assert.Single(_scope.Gaps.Gaps, g => g.EntityId == "cmp:0002");
    }

    // ---- the guard and the census ------------------------------------------------

    [Fact]
    public void Dump_PutsEveryReadThroughTheGateUnderItsInteropName()
    {
        _reader.Add(HousingPath).Equations.Add(Eq("\"A\" = 1", global: true, value: 1));

        Dump(Root(), Part("housing-1", HousingPath));

        Assert.Contains("GetModelDoc2", _observer.Members);
        Assert.Contains("GetEquationMgr", _observer.Members);
        Assert.Contains("GetCount", _observer.Members);
        Assert.Contains("EquationMgr.Equation", _observer.Members);
        Assert.Contains("GlobalVariable", _observer.Members);
        Assert.Contains("EquationMgr.Value", _observer.Members);
    }

    [Fact]
    public void Dump_NoMutatingMemberEverPassesThroughTheGate()
    {
        _reader.Add(HousingPath).Equations.Add(Eq("\"A\" = 1", global: true, value: 1));

        Dump(Root(), Part("housing-1", HousingPath));

        Assert.NotEmpty(_observer.Members);
        foreach (string member in _observer.Members)
        {
            // The shipped denylist, not a copy of it.
            ReadOnlyGuard.Assert(member);
        }

        // The members an equation EDIT would use. Naming them here is what keeps this
        // dumper out of that API family even if the seam grows.
        foreach (string mutating in new[]
        {
            "Add3", "Delete", "SetEquation", "SetEquationAndConfigurationOption",
            "EditSuppress2", "ForceRebuild3",
        })
        {
            Assert.DoesNotContain(mutating, _observer.Members);
        }
    }

    [Fact]
    public void Dump_FeedsTheTypeNameCensusNothing()
    {
        // The census answers "this feature type was walked past and nobody read it". The
        // equation manager is not the feature tree and classifies nothing, so a pass from
        // here would report type names as gaps on every part.
        _reader.Add(HousingPath).Equations.Add(Eq("\"A\" = 1", global: true, value: 1));

        Dump(Root(), Part("housing-1", HousingPath));

        Assert.Empty(_scope.Gaps.TypeNames.Unconsumed());
    }

    [Fact]
    public void Constructor_NullArgument_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new EquationDumper(null!, _reader));
        Assert.Throws<ArgumentNullException>(() => new EquationDumper(_gate, null!));
    }

    [Fact]
    public void Dump_NullScope_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new EquationDumper(_gate, _reader).Dump(null!));
    }

    // ---- harness -----------------------------------------------------------------

    /// <summary>
    /// The one `equations` gap recorded, and a phrase its reason or error carries. The kind
    /// is not asserted here: a read that threw is a <see cref="GapKind.ToolError"/> through
    /// <c>GapCollector.Record</c>, and an absence the dumper decided is
    /// <see cref="GapKind.NotExtracted"/>; the tests that care say which they expect.
    /// </summary>
    private Gap AssertGap(string phrase)
    {
        Gap gap = Assert.Single(_scope.Gaps.Gaps, g => g.EntityKind == "equations");
        Assert.Contains(
            phrase,
            gap.Reason + " " + (gap.Error ?? string.Empty),
            StringComparison.Ordinal);
        return gap;
    }

    private IReadOnlyList<Equation> Dump(params ComponentNode[] nodes)
    {
        _scope = NewScope(nodes);
        return new EquationDumper(_gate, _reader).Dump(_scope);
    }

    private static DumpScope NewScope(ComponentNode[] nodes)
    {
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = AssemblyPath,
            RootDocumentKind = DocumentKind.Assembly,
            DesignName = "bracket-assy",
            ActiveConfiguration = "Default",
        };

        tree.Nodes.AddRange(nodes);

        var scope = new DumpScope(new GapCollector(), new DumpOptions { OutputDirectory = "out" }, tree);

        // Ids exactly as PackageWriter allocates them, so cmp:0001 is the root here too.
        var ids = new IdAllocator("cmp");
        foreach (ComponentNode node in nodes)
        {
            scope.AddComponent(ids.Next(), scope.DocumentId(node.DocumentPath), node);
        }

        return scope;
    }

    private static ComponentNode Root() => new ComponentNode
    {
        Key = "bracket-assy-1",
        ParentKey = null,
        Name = "bracket-assy-1",
        DocumentPath = AssemblyPath,
        DocumentKind = DocumentKind.Assembly,
        ReferencedConfiguration = "Default",
        Transform = Transform.Identity(),
        Suppression = SuppressionState.Resolved,
        PersistRef = "Q29tcA==",
        PersistRefScopePath = AssemblyPath,
        Handle = new object(),
    };

    private static ComponentNode Part(
        string key,
        string path,
        SuppressionState state = SuppressionState.Resolved) => new ComponentNode
        {
            Key = key,
            ParentKey = "bracket-assy-1",
            Name = key,
            DocumentPath = path,
            DocumentKind = DocumentKind.Part,
            ReferencedConfiguration = "Default",
            Transform = Transform.Identity(),
            Suppression = state,
            PersistRef = "Q29tcA==",
            PersistRefScopePath = AssemblyPath,
            Handle = new object(),
        };

    private static FakeEquation Eq(string text, bool global, double value) =>
        new FakeEquation { Text = text, Global = global, Value = value };

    /// <summary>Every member the gate was asked about, in order, duplicates and all.</summary>
    private sealed class RecordingObserver : ISwGateObserver
    {
        public List<string> Members { get; } = new List<string>();

        public void Gated(string interopMember) => Members.Add(interopMember);

        public void Refused(MutatingCallError refusal)
        {
        }
    }

    /// <summary>One row of the equation manager, with a switch for every read that can fail.</summary>
    private sealed class FakeEquation
    {
        public string? Text { get; set; }

        public bool TextThrows { get; set; }

        public bool Global { get; set; }

        public bool GlobalThrows { get; set; }

        public double Value { get; set; }

        public bool ValueThrows { get; set; }
    }

    /// <summary>One open part document and the manager it does or does not have.</summary>
    private sealed class FakeEquationDocument
    {
        public FakeEquationDocument(string path)
        {
            Path = path;
        }

        public string Path { get; }

        public List<FakeEquation> Equations { get; } = new List<FakeEquation>();

        /// <summary>False means GetEquationMgr answers with nothing.</summary>
        public bool HasManager { get; set; } = true;

        public Exception? ManagerFailure { get; set; }

        /// <summary>Set to make GetModelDoc2 throw for every instance of this document.</summary>
        public Exception? DocumentFailure { get; set; }

        public Exception? CountFailure { get; set; }
    }

    /// <summary>The seam: what a live SOLIDWORKS would answer, scripted.</summary>
    private sealed class FakeEquationReader : IEquationReader
    {
        private readonly Dictionary<string, FakeEquationDocument> _documents =
            new Dictionary<string, FakeEquationDocument>(StringComparer.OrdinalIgnoreCase);

        /// <summary>Every document the dumper asked for, in order.</summary>
        public List<string> DocumentRequests { get; } = new List<string>();

        /// <summary>Every document whose equation manager was opened, in order.</summary>
        public List<string> ManagerRequests { get; } = new List<string>();

        /// <summary>
        /// Component keys whose GetModelDoc2 answers with nothing however loaded the
        /// document is - one instance of a part that is not in memory while another is.
        /// </summary>
        public HashSet<string> Unloaded { get; } = new HashSet<string>(StringComparer.Ordinal);

        public FakeEquationDocument Add(string path)
        {
            var document = new FakeEquationDocument(path);
            _documents[path] = document;
            return document;
        }

        public object? Document(ScopedComponent component)
        {
            DocumentRequests.Add(component.Node.DocumentPath);
            FakeEquationDocument found;
            if (!_documents.TryGetValue(component.Node.DocumentPath, out found))
            {
                return null;
            }

            if (found.DocumentFailure != null)
            {
                throw found.DocumentFailure;
            }

            return Unloaded.Contains(component.Node.Key) ? null : found;
        }

        public object? Manager(object document)
        {
            FakeEquationDocument doc = Doc(document);
            ManagerRequests.Add(doc.Path);
            if (doc.ManagerFailure != null)
            {
                throw doc.ManagerFailure;
            }

            return doc.HasManager ? doc : null;
        }

        public int Count(object manager)
        {
            FakeEquationDocument doc = Doc(manager);
            if (doc.CountFailure != null)
            {
                throw doc.CountFailure;
            }

            return doc.Equations.Count;
        }

        public string? Text(object manager, int index) =>
            Throwing(manager, index, e => e.TextThrows, "Equation").Text;

        public bool GlobalVariable(object manager, int index) =>
            Throwing(manager, index, e => e.GlobalThrows, "GlobalVariable").Global;

        public double Value(object manager, int index) =>
            Throwing(manager, index, e => e.ValueThrows, "Value").Value;

        private static FakeEquationDocument Doc(object document) => (FakeEquationDocument)document;

        private static FakeEquation Throwing(
            object manager, int index, Func<FakeEquation, bool> fails, string member)
        {
            FakeEquation equation = Doc(manager).Equations[index];
            if (fails(equation))
            {
                throw new InvalidOperationException($"{member}({index}) failed.");
            }

            return equation;
        }
    }
}
