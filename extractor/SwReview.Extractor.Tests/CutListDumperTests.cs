using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T039. The <c>cutlist</c> phase (schema 1.4.0), over a fake <see cref="ICutListReader"/> on
/// a machine with no SOLIDWORKS seat - the same split <see cref="FeatureDumper"/> makes with
/// <see cref="IFeatureReader"/>.
///
/// Four properties matter more than the field mapping:
///
///   * <b>Items are identified structurally.</b> A feature is a cut-list folder because
///     <c>GetSpecificFeature2</c> hands back an <c>IBodyFolder</c>, never because its name
///     looks like one (difference bb). A renamed item is still the same item, so a rename is
///     not a waiver, and a folder type name this build has never seen is recorded verbatim
///     rather than dropped - which is what makes PROBE-8's answer visible instead of silent.
///   * <b>Nothing is defaulted.</b> A body count or an exclusion flag that could not be read
///     is null plus the gap entity kind <c>data-model.md</c> section 2.4 names, and the item
///     is still recorded: Python then reports it unresolved rather than passing it.
///   * <b>An empty folder is evidence.</b> A folder whose body count is 0 is not displayed by
///     SOLIDWORKS and is no check's subject, but it is recorded, so the coverage reason can
///     say how many folders were seen and how many were displayable.
///   * <b>Nothing mutates.</b> The phase sits beside the whole cut-list write family
///     (<c>SetAutomaticCutList</c>, <c>UpdateCutList</c>, <c>SortCutList</c>,
///     <c>set_ExcludeFromCutList</c>), all of which research R8 put on the denylist, and it
///     calls none of them.
/// </summary>
public class CutListDumperTests
{
    private const string AssemblyPath = @"C:\vault\bracket-assy\bracket-assy.SLDASM";
    private const string HousingPath = @"C:\vault\bracket-assy\housing.SLDPRT";
    private const string RailPath = @"C:\vault\bracket-assy\rail.SLDPRT";

    private readonly FakeCutListReader _reader = new FakeCutListReader();
    private readonly RecordingGateObserver _observer = new RecordingGateObserver();
    private readonly SwGate _gate = new SwGate();

    private DumpScope _scope = null!;

    public CutListDumperTests()
    {
        _gate.Observer = _observer;
    }

    // ---- structural identification -------------------------------------------------

    [Fact]
    public void Dump_FindsItemsFromTheBodyFolderTreeWhateverTheyAreCalled()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat folder = housing.AddFolder("Cut list(2)", "CutListFolder");

        // Renamed by the engineer; the macro's name match would have missed both.
        folder.AddItem("2x2x0.125 rectangular tube, 400", bodyCount: 1);
        folder.AddItem("Gusset A", bodyCount: 1);

        IReadOnlyList<CutListItem> items = Dump(Part("housing-1", HousingPath));

        Assert.Equal(
            new[] { "2x2x0.125 rectangular tube, 400", "Gusset A" },
            items.Select(i => i.Name));
    }

    [Fact]
    public void Dump_IgnoresAFeatureThatIsNoBodyFolder()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        housing.AddFeature("Boss-Extrude1", "Extrusion");
        housing.AddFolder("Cut list(1)", "CutListFolder").AddItem("Cut-List-Item1", bodyCount: 1);

        Assert.Equal("Cut-List-Item1", Assert.Single(Dump(Part("housing-1", HousingPath))).Name);
    }

    [Fact]
    public void Dump_IgnoresAFolderChildThatIsNoBodyFolder()
    {
        // An ordinary part's "Solid Bodies" folder lists bodies, not cut-list items. They are
        // not body folders, so they are not rows - and the part simply has no cut list, which
        // Python reports as a skip with a reason rather than a pass (difference aa).
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat bodies = housing.AddFolder("Solid Bodies(1)", "SolidBodyFolder");
        bodies.AddChild("housing", isBodyFolder: false);

        Assert.Empty(Dump(Part("housing-1", HousingPath)));
    }

    [Fact]
    public void Dump_RecordsEveryFieldVerbatim()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        housing.ActiveConfiguration = "Weldment";

        // A folder type name this build has never seen: recorded as it came, so PROBE-8's
        // answer is visible on the package rather than swallowed by a whitelist.
        FakeFeat folder = housing.AddFolder("Cut list(1)", "SomeNewCutListFolderName");
        FakeFeat item = folder.AddItem("Cut-List-Item1", bodyCount: 4);
        item.Excluded = true;
        item.PersistRef = "Q3V0MQ==";

        CutListItem row = Assert.Single(Dump(Part("housing-1", HousingPath)));

        Assert.Equal("cut:0001", row.Id);
        Assert.Equal(_scope.DocumentId(HousingPath), row.DocumentId);
        Assert.Equal("Weldment", row.Configuration);
        Assert.Equal("Cut list(1)", row.FolderName);
        Assert.Equal("SomeNewCutListFolderName", row.FolderTypeName);
        Assert.Equal("Cut-List-Item1", row.Name);
        Assert.Equal(4, row.BodyCount);
        Assert.True(row.ExcludedFromCutList);
        Assert.Equal("Q3V0MQ==", row.PersistRef);
        Assert.Equal(_scope.DocumentId(HousingPath), row.PersistRefScope);
    }

    [Fact]
    public void Dump_AllocatesIdsInTraversalOrderAcrossThePackage()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat housingFolder = housing.AddFolder("Cut list(2)", "CutListFolder");
        housingFolder.AddItem("Cut-List-Item1", bodyCount: 1);
        housingFolder.AddItem("Cut-List-Item2", bodyCount: 1);

        FakeDoc rail = _reader.Add(RailPath);
        rail.AddFolder("Cut list(1)", "CutListFolder").AddItem("Cut-List-Item1", bodyCount: 1);

        IReadOnlyList<CutListItem> items = Dump(
            Part("housing-1", HousingPath), Part("rail-1", RailPath));

        Assert.Equal(new[] { "cut:0001", "cut:0002", "cut:0003" }, items.Select(i => i.Id));
    }

    [Fact]
    public void Dump_WalksEachDocumentOnce_NotOncePerInstance()
    {
        _reader.Add(HousingPath)
            .AddFolder("Cut list(1)", "CutListFolder")
            .AddItem("Cut-List-Item1", bodyCount: 1);

        IReadOnlyList<CutListItem> items = Dump(
            Part("housing-1", HousingPath), Part("housing-2", HousingPath));

        Assert.Single(items);
        Assert.Equal(new[] { HousingPath }, _reader.DocumentRequests);
    }

    [Fact]
    public void Dump_SkipsAssembliesAndUnloadedComponents()
    {
        _reader.Add(HousingPath)
            .AddFolder("Cut list(1)", "CutListFolder")
            .AddItem("Cut-List-Item1", bodyCount: 1);

        // A suppressed instance has no loaded document, and that loss is already on the
        // package twice: the component tree records the instance's suppression state, and the
        // feature phase records it as a feature_tree_unavailable gap against the component id.
        // Python grades the document unresolved off the component tree alone
        // (results.document_evidence_unresolved), so a document-keyed cut_list_folder gap here
        // would not add a signal - it would claim the DOCUMENT's cut list was unread, which is
        // false whenever another instance of the same part is resolved (the test below).
        IReadOnlyList<CutListItem> items = Dump(
            Part("housing-1", HousingPath, SuppressionState.Suppressed));

        Assert.Empty(items);
        Assert.Empty(_reader.DocumentRequests);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_SuppressedAndResolvedInstances_ReadTheDocumentThroughTheResolvedOne()
    {
        _reader.Add(HousingPath)
            .AddFolder("Cut list(1)", "CutListFolder")
            .AddItem("Cut-List-Item1", bodyCount: 1);

        IReadOnlyList<CutListItem> items = Dump(
            Part("housing-1", HousingPath, SuppressionState.Suppressed),
            Part("housing-2", HousingPath));

        // The cut list WAS read, so nothing about this document is missing and no gap is due.
        Assert.Equal("Cut-List-Item1", Assert.Single(items).Name);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    [Fact]
    public void Dump_ResolvedComponentWithNoLoadedDocument_IsACutListFolderGap()
    {
        // GetModelDoc2 answered null for an instance the tree calls resolved: the document
        // exists in the assembly and its cut list was NOT read. Swallowed, that reads on the
        // Python side as "the part records no cut-list items" - a silent skip, and the reason
        // on the row would be the wrong one. FeatureDumper names the same loss the same way.
        IReadOnlyList<CutListItem> items = Dump(Part("housing-1", HousingPath));

        Assert.Empty(items);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_folder", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Contains("housing-1", gap.Reason, StringComparison.Ordinal);
    }

    // ---- an empty folder is still evidence -----------------------------------------

    [Fact]
    public void Dump_FolderWithNoBodies_IsRecordedAndIsNotAGap()
    {
        _reader.Add(HousingPath)
            .AddFolder("Cut list(1)", "CutListFolder")
            .AddItem("Cut-List-Item1", bodyCount: 0);

        CutListItem row = Assert.Single(Dump(Part("housing-1", HousingPath)));

        Assert.Equal(0, row.BodyCount);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    // ---- gaps ----------------------------------------------------------------------

    [Fact]
    public void Dump_FolderTypeNameThatFailed_IsACutListFolderGapAndTheItemsAreStillRecorded()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat folder = housing.AddFolder("Cut list(1)", "CutListFolder");
        folder.TypeNameThrows = true;
        folder.AddItem("Cut-List-Item1", bodyCount: 1);

        CutListItem row = Assert.Single(Dump(Part("housing-1", HousingPath)));

        Assert.Equal(string.Empty, row.FolderTypeName);
        Assert.Equal("Cut list(1)", row.FolderName);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_folder", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Fact]
    public void Dump_ItemSpecificFeatureThatFailed_IsACutListFolderGapAndTheItemIsStillRecorded()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat folder = housing.AddFolder("Cut list(1)", "CutListFolder");
        FakeFeat item = folder.AddItem("Cut-List-Item1", bodyCount: 3);
        item.BodyFolderThrows = true;

        CutListItem row = Assert.Single(Dump(Part("housing-1", HousingPath)));

        Assert.Equal("Cut-List-Item1", row.Name);
        Assert.Null(row.BodyCount);
        Assert.Equal("cut_list_folder", Assert.Single(_scope.Gaps.Gaps).EntityKind);
    }

    [Fact]
    public void Dump_TopLevelSpecificFeatureThatFailed_IsACutListFolderGap()
    {
        // The feature could not be identified as a folder at all, so nothing about it can be
        // recorded - but the failure is named, because a swallowed one would read as "this
        // part has no cut list", which is a silent pass on the check that matters (RK-5).
        FakeDoc housing = _reader.Add(HousingPath);
        housing.AddFeature("Cut list(1)", "CutListFolder").BodyFolderThrows = true;

        Assert.Empty(Dump(Part("housing-1", HousingPath)));

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_folder", gap.EntityKind);
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Fact]
    public void Dump_ActiveConfigurationThatFailed_IsACutListFolderGapAndNoRows()
    {
        // Which configuration the tree was read in is part of the evidence: rows recorded
        // without it would name a cut list nobody can say belongs to the graded configuration.
        FakeDoc housing = _reader.Add(HousingPath);
        housing.ConfigurationThrows = true;
        housing.AddFolder("Cut list(1)", "CutListFolder").AddItem("Cut-List-Item1", bodyCount: 1);

        Assert.Empty(Dump(Part("housing-1", HousingPath)));

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_folder", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Fact]
    public void Dump_FeatureWalkThatFailed_IsACutListFolderGapAndNoRows()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        housing.FeaturesThrow = true;
        housing.AddFolder("Cut list(1)", "CutListFolder").AddItem("Cut-List-Item1", bodyCount: 1);

        Assert.Empty(Dump(Part("housing-1", HousingPath)));

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_folder", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
    }

    [Fact]
    public void Dump_FolderSubFeaturesThatFailed_IsACutListFolderGapAndNoRows()
    {
        // The folder was identified but its items could not be listed: the part has a cut
        // list and none of it was read, which is not the same as having none.
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat folder = housing.AddFolder("Cut list(1)", "CutListFolder");
        folder.AddItem("Cut-List-Item1", bodyCount: 1);
        folder.SubFeaturesThrow = true;

        Assert.Empty(Dump(Part("housing-1", HousingPath)));

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_folder", gap.EntityKind);
        Assert.Equal(_scope.DocumentId(HousingPath), gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains("Cut list(1)", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_BodyCountThatFailed_IsNullPlusACutListBodyCountGap()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat item = housing.AddFolder("Cut list(1)", "CutListFolder")
            .AddItem("Cut-List-Item1", bodyCount: 2);
        item.BodyCountThrows = true;

        CutListItem row = Assert.Single(Dump(Part("housing-1", HousingPath)));

        Assert.Null(row.BodyCount);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_body_count", gap.EntityKind);
        Assert.Equal("cut:0001", gap.EntityId);
        Assert.Contains("Cut-List-Item1", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Dump_ExclusionThatFailed_IsNullPlusACutListExclusionGap()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat item = housing.AddFolder("Cut list(1)", "CutListFolder")
            .AddItem("Cut-List-Item1", bodyCount: 1);
        item.ExcludedThrows = true;

        CutListItem row = Assert.Single(Dump(Part("housing-1", HousingPath)));

        Assert.Null(row.ExcludedFromCutList);

        Gap gap = Assert.Single(_scope.Gaps.Gaps);
        Assert.Equal("cut_list_exclusion", gap.EntityKind);
        Assert.Equal("cut:0001", gap.EntityId);
    }

    [Fact]
    public void Dump_ItemWithNoPersistentReference_IsANullPairAndNoGap()
    {
        // FR-026: a null persist_ref is a statement - the id is a within-dump identity - not
        // a failure. PROBE-10 says which entity kinds SOLIDWORKS answers for at all.
        FakeDoc housing = _reader.Add(HousingPath);
        FakeFeat item = housing.AddFolder("Cut list(1)", "CutListFolder")
            .AddItem("Cut-List-Item1", bodyCount: 1);
        item.PersistRef = null;

        CutListItem row = Assert.Single(Dump(Part("housing-1", HousingPath)));

        Assert.Null(row.PersistRef);
        Assert.Null(row.PersistRefScope);
        Assert.Empty(_scope.Gaps.Gaps);
    }

    // ---- read-only -----------------------------------------------------------------

    [Fact]
    public void Dump_NoMutatingMemberEverPassesThroughTheGate()
    {
        FakeDoc housing = _reader.Add(HousingPath);
        housing.AddFolder("Cut list(1)", "CutListFolder").AddItem("Cut-List-Item1", bodyCount: 1);

        Dump(Part("housing-1", HousingPath));

        Assert.NotEmpty(_observer.Members);
        foreach (string member in _observer.Members)
        {
            // The shipped denylist, not a copy of it.
            ReadOnlyGuard.Assert(member);
        }

        // The cut-list write family research R8 put on the denylist, beside the reads this
        // phase makes. The read ExcludeFromCutList passes; the write set_ExcludeFromCutList
        // is refused, and neither is called.
        foreach (string mutating in new[]
        {
            "SetAutomaticCutList", "UpdateCutList", "SortCutList", "SetAutomaticUpdate",
            "set_ExcludeFromCutList",
        })
        {
            Assert.DoesNotContain(mutating, _observer.Members);
        }

        Assert.Contains("ExcludeFromCutList", _observer.Members);
        Assert.Contains("GetSpecificFeature2", _observer.Members);
        Assert.Contains("GetBodyCount", _observer.Members);
    }

    [Fact]
    public void Constructor_NullArgument_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new CutListDumper(null!, _reader));
        Assert.Throws<ArgumentNullException>(() => new CutListDumper(_gate, null!));
    }

    [Fact]
    public void Dump_NullScope_Throws()
    {
        Assert.Throws<ArgumentNullException>(() => new CutListDumper(_gate, _reader).Dump(null!));
    }

    // ---- harness -------------------------------------------------------------------

    private IReadOnlyList<CutListItem> Dump(params ComponentNode[] nodes)
    {
        _scope = NewScope(nodes);
        return new CutListDumper(_gate, _reader).Dump(_scope);
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
        var ids = new IdAllocator("cmp");
        foreach (ComponentNode node in nodes)
        {
            scope.AddComponent(ids.Next(), scope.DocumentId(node.DocumentPath), node);
        }

        return scope;
    }

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

    /// <summary>One feature in a scripted tree, with a switch for every read that can fail.</summary>
    private sealed class FakeFeat
    {
        public string Name { get; set; } = string.Empty;

        public string TypeName { get; set; } = string.Empty;

        public bool NameThrows { get; set; }

        public bool TypeNameThrows { get; set; }

        /// <summary>Whether GetSpecificFeature2 hands back an IBodyFolder.</summary>
        public bool IsBodyFolder { get; set; }

        public bool BodyFolderThrows { get; set; }

        public int BodyCount { get; set; }

        public bool BodyCountThrows { get; set; }

        public bool Excluded { get; set; }

        public bool ExcludedThrows { get; set; }

        public bool SubFeaturesThrow { get; set; }

        public string? PersistRef { get; set; } = "Q3V0";

        public List<FakeFeat> SubFeatures { get; } = new List<FakeFeat>();

        public FakeFeat AddItem(string name, int bodyCount)
        {
            var item = new FakeFeat
            {
                Name = name,
                TypeName = "CutListFolder",
                IsBodyFolder = true,
                BodyCount = bodyCount,
            };

            SubFeatures.Add(item);
            return item;
        }

        public FakeFeat AddChild(string name, bool isBodyFolder)
        {
            var child = new FakeFeat { Name = name, TypeName = "SolidBody", IsBodyFolder = isBodyFolder };
            SubFeatures.Add(child);
            return child;
        }
    }

    /// <summary>One open part document.</summary>
    private sealed class FakeDoc
    {
        public FakeDoc(string path)
        {
            Path = path;
        }

        public string Path { get; }

        public string ActiveConfiguration { get; set; } = "Default";

        public bool ConfigurationThrows { get; set; }

        public bool FeaturesThrow { get; set; }

        public List<FakeFeat> Features { get; } = new List<FakeFeat>();

        public FakeFeat AddFeature(string name, string typeName)
        {
            var feature = new FakeFeat { Name = name, TypeName = typeName };
            Features.Add(feature);
            return feature;
        }

        public FakeFeat AddFolder(string name, string typeName)
        {
            FakeFeat folder = AddFeature(name, typeName);
            folder.IsBodyFolder = true;
            return folder;
        }
    }

    /// <summary>The seam: what a live SOLIDWORKS would answer, scripted.</summary>
    private sealed class FakeCutListReader : ICutListReader
    {
        private readonly Dictionary<string, FakeDoc> _documents =
            new Dictionary<string, FakeDoc>(StringComparer.OrdinalIgnoreCase);

        /// <summary>Every document the dumper asked for, in order.</summary>
        public List<string> DocumentRequests { get; } = new List<string>();

        public FakeDoc Add(string path)
        {
            var document = new FakeDoc(path);
            _documents[path] = document;
            return document;
        }

        public object? Document(ScopedComponent component)
        {
            DocumentRequests.Add(component.Node.DocumentPath);
            FakeDoc found;
            return _documents.TryGetValue(component.Node.DocumentPath, out found) ? found : null;
        }

        public string ActiveConfiguration(object document)
        {
            FakeDoc doc = Doc(document);
            if (doc.ConfigurationThrows)
            {
                throw new InvalidOperationException(
                    $"ConfigurationManager.ActiveConfiguration did not answer for '{doc.Path}'.");
            }

            return doc.ActiveConfiguration;
        }

        public IReadOnlyList<object> Features(object document)
        {
            FakeDoc doc = Doc(document);
            if (doc.FeaturesThrow)
            {
                throw new InvalidOperationException($"FirstFeature did not answer for '{doc.Path}'.");
            }

            return doc.Features.Cast<object>().ToList();
        }

        public IReadOnlyList<object> SubFeatures(object feature) =>
            Throwing(feature, f => f.SubFeaturesThrow, "GetFirstSubFeature")
                .SubFeatures.Cast<object>().ToList();

        public string Name(object feature) =>
            Throwing(feature, f => f.NameThrows, "Feature.Name").Name;

        public string TypeName(object feature) =>
            Throwing(feature, f => f.TypeNameThrows, "GetTypeName2").TypeName;

        public object? BodyFolder(object feature)
        {
            FakeFeat f = Throwing(feature, x => x.BodyFolderThrows, "GetSpecificFeature2");
            return f.IsBodyFolder ? feature : null;
        }

        public int BodyCount(object bodyFolder) =>
            Throwing(bodyFolder, f => f.BodyCountThrows, "GetBodyCount").BodyCount;

        public bool ExcludedFromCutList(object feature) =>
            Throwing(feature, f => f.ExcludedThrows, "ExcludeFromCutList").Excluded;

        public ScopedPersistRef? PersistRef(object document, object feature)
        {
            string? reference = F(feature).PersistRef;
            if (reference == null)
            {
                return null;
            }

            string path = Doc(document).Path;
            return new ScopedPersistRef(reference, DocumentIds.For(path), path);
        }

        private static FakeDoc Doc(object document) => (FakeDoc)document;

        private static FakeFeat F(object feature) => (FakeFeat)feature;

        private static FakeFeat Throwing(object feature, Func<FakeFeat, bool> fails, string member)
        {
            FakeFeat f = F(feature);
            if (fails(f))
            {
                throw new InvalidOperationException($"{member} did not answer for '{f.Name}'.");
            }

            return f;
        }
    }
}
