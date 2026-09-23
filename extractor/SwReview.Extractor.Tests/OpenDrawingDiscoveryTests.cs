using System;
using System.Collections.Generic;
using System.Linq;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Feature 011 T018 (contracts/open-drawings.md sections 1, 2, 3 and 5): which open drawings a
/// review extraction reads, in what order, at most ten, and which same-name drawings beside the
/// design it names as candidates - all of it the pure <see cref="OpenDrawingDiscovery.Discover"/>
/// over a fake <see cref="IOpenDrawingSource"/>, so every rule is decided here with no seat.
/// Nothing is ever opened: the source only lists what SOLIDWORKS already has open and asks
/// whether a file exists.
/// </summary>
public class OpenDrawingDiscoveryTests
{
    private const string Folder = @"C:\Fictional\bracket";
    private const string AssemblyPath = Folder + @"\bracket-assy.SLDASM";
    private const string HousingPath = Folder + @"\housing.SLDPRT";
    private const string PinPath = Folder + @"\pin.SLDPRT";
    private const string CoverPath = Folder + @"\cover.SLDPRT";
    private const string OutsidePath = @"C:\Fictional\other\unrelated.SLDPRT";
    private const string SecondOutsidePath = @"C:\Fictional\other\another.SLDPRT";

    private readonly GapCollector _gaps = new GapCollector();

    // ---- section 1: when discovery runs -------------------------------------------------

    [Theory]
    [InlineData(DumpProfile.Full, DocumentKind.Part, true)]
    [InlineData(DumpProfile.Full, DocumentKind.Assembly, true)]
    [InlineData(DumpProfile.Full, DocumentKind.Drawing, false)]
    [InlineData(DumpProfile.Standards, DocumentKind.Part, false)]
    [InlineData(DumpProfile.Standards, DocumentKind.Assembly, false)]
    [InlineData(DumpProfile.Standards, DocumentKind.Drawing, false)]
    [InlineData(DumpProfile.ModelCheck, DocumentKind.Part, false)]
    [InlineData(DumpProfile.ModelCheck, DocumentKind.Assembly, false)]
    [InlineData(DumpProfile.ModelCheck, DocumentKind.Drawing, false)]
    public void RunsFor_OnlyTheFullProfileOfAPartOrAssemblyRootDiscovers(
        DumpProfile profile, DocumentKind rootKind, bool runs)
    {
        ComponentTreeResult tree = Tree(rootKind == DocumentKind.Drawing
            ? Folder + @"\bracket-assy.SLDDRW"
            : AssemblyPath, rootKind);

        Assert.Equal(runs, OpenDrawingDiscovery.RunsFor(tree, Options(profile)));
    }

    [Fact]
    public void RunsFor_AnUnreadRootKindDiscoversNothing()
    {
        var tree = new ComponentTreeResult { RootDocumentPath = AssemblyPath, RootDocumentKind = null };

        Assert.False(OpenDrawingDiscovery.RunsFor(tree, Options(DumpProfile.Full)));
    }

    [Theory]
    [InlineData(DumpProfile.Standards)]
    [InlineData(DumpProfile.ModelCheck)]
    public void Discover_UnderAnotherProfile_AsksTheSourceNothingAndAttachesNothing(DumpProfile profile)
    {
        var source = new FakeSource();
        source.Drawing(Folder + @"\bracket-assy.SLDDRW", AssemblyPath);
        source.Exists(Folder + @"\housing.SLDDRW");

        AttachedDrawings found = OpenDrawingDiscovery.Discover(
            AssemblyTree(), source, Options(profile), _gaps);

        Assert.Empty(found.Drawings);
        Assert.Empty(found.NotRead);
        Assert.Empty(found.Candidates);
        Assert.Equal(0, source.OpenDocumentsCalls);
        Assert.Empty(source.ExistenceChecks);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void Discover_OfADrawingRoot_AsksTheSourceNothing()
    {
        var source = new FakeSource();
        source.Drawing(Folder + @"\other.SLDDRW", HousingPath);

        AttachedDrawings found = OpenDrawingDiscovery.Discover(
            Tree(Folder + @"\bracket-assy.SLDDRW", DocumentKind.Drawing, (HousingPath, DocumentKind.Part)),
            source,
            Options(DumpProfile.Full),
            _gaps);

        Assert.Empty(found.Drawings);
        Assert.Equal(0, source.OpenDocumentsCalls);
        Assert.Empty(source.ExistenceChecks);
    }

    // ---- section 2: what discovery reads, and each failure -------------------------------

    [Fact]
    public void Discover_OpenDocumentsThatCannotBeListed_IsOneDiscoveryGapAndNothingAttached()
    {
        var source = new FakeSource { OpenDocumentsFailure = new InvalidOperationException("no answer") };

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Drawings);
        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_discovery");
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains("open in SOLIDWORKS", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("no answer", gap.Error, StringComparison.Ordinal);
    }

    [Fact]
    public void Discover_ADocumentWhoseKindThrows_IsSkippedWithOneGapNamingItsPositionAndTheRestAreRead()
    {
        var source = new FakeSource();
        source.Add(new FakeDocument { KindFailure = new InvalidOperationException("kind") });
        FakeDocument drawing = source.Drawing(Folder + @"\bracket-assy.SLDDRW", AssemblyPath);

        AttachedDrawings found = Discover(source);

        Assert.Equal(new[] { drawing.Path }, found.Drawings.Select(d => d.Path));
        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_discovery");
        Assert.Contains("open document 1", gap.Reason, StringComparison.Ordinal);
        Assert.Null(gap.EntityId);
    }

    [Fact]
    public void Discover_ADrawingWhosePathThrows_IsSkippedWithOneGapNamingItsPosition()
    {
        var source = new FakeSource();
        source.Drawing(Folder + @"\bracket-assy.SLDDRW", AssemblyPath);
        source.Add(new FakeDocument
        {
            Kind = DocumentKind.Drawing,
            PathFailure = new InvalidOperationException("path"),
            References = { AssemblyPath },
        });

        AttachedDrawings found = Discover(source);

        Assert.Single(found.Drawings);
        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_discovery");
        Assert.Contains("open document 2", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Discover_ADrawingWhoseViewsThrow_IsNotAttachedAndIsOneGapNamingItsPath()
    {
        const string Broken = Folder + @"\broken.SLDDRW";
        var source = new FakeSource();
        source.Add(new FakeDocument
        {
            Kind = DocumentKind.Drawing,
            Path = Broken,
            ViewsFailure = new InvalidOperationException("views"),
        });

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Drawings);
        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_discovery");
        Assert.Contains(Broken, gap.Reason, StringComparison.Ordinal);
        Assert.Equal(DocumentIds.For(Broken), gap.EntityId);
    }

    [Fact]
    public void Discover_APartOrAssemblyThatIsOpen_IsAskedItsKindAndNothingElse()
    {
        // Only a drawing has views to show the design; reading a model's path or views would be
        // calls nobody needs, on documents the traversal already reads.
        var source = new FakeSource();
        FakeDocument part = source.Add(new FakeDocument { Kind = DocumentKind.Part, Path = HousingPath });
        FakeDocument assembly = source.Add(new FakeDocument { Kind = DocumentKind.Assembly, Path = AssemblyPath });

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Drawings);
        Assert.Equal(new[] { "kind" }, part.Reads);
        Assert.Equal(new[] { "kind" }, assembly.Reads);
        Assert.DoesNotContain(_gaps.Gaps, g => g.EntityKind == "drawing_discovery");
    }

    [Fact]
    public void Discover_ReadsADrawingsKindThenItsPathThenItsViews()
    {
        var source = new FakeSource();
        FakeDocument drawing = source.Drawing(Folder + @"\bracket-assy.SLDDRW", AssemblyPath);

        Discover(source);

        Assert.Equal(new[] { "kind", "path", "views" }, drawing.Reads);
    }

    // ---- section 3: matching -------------------------------------------------------------

    [Fact]
    public void Discover_ADrawingThatReferencesTheRoot_IsAttachedWithItsHandle()
    {
        var source = new FakeSource();
        FakeDocument drawing = source.Drawing(Folder + @"\bracket-assy.SLDDRW", AssemblyPath);

        AttachedDrawings found = Discover(source);

        AttachedDrawing attached = Assert.Single(found.Drawings);
        Assert.Equal(drawing.Path, attached.Path);
        Assert.Same(drawing.Handle, attached.Handle);
    }

    [Fact]
    public void Discover_ADrawingThatReferencesASubPart_IsAttached()
    {
        var source = new FakeSource();
        source.Drawing(Folder + @"\housing.SLDDRW", HousingPath);

        Assert.Single(Discover(source).Drawings);
    }

    [Fact]
    public void Discover_ADrawingThatReferencesOnlyAnOutsideDocument_IsNotAttachedAndRaisesNoGap()
    {
        var source = new FakeSource();
        source.Drawing(@"C:\Fictional\other\unrelated.SLDDRW", OutsidePath);

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Drawings);
        Assert.Empty(found.NotRead);
        Assert.DoesNotContain(_gaps.Gaps, g => g.EntityKind == "drawing_referenced_document");
    }

    [Theory]
    [InlineData(@"C:\FICTIONAL\BRACKET\HOUSING.sldprt")]
    [InlineData(@"c:\fictional\bracket\housing.SLDPRT")]
    [InlineData(@"C:\Fictional\bracket\sub\..\housing.SLDPRT")]
    [InlineData(@"C:\Fictional\bracket\.\housing.SLDPRT")]
    [InlineData(@"C:\Fictional\other\..\bracket\housing.SLDPRT")]
    public void Discover_MatchesByFullPathIgnoringCaseAndNormalisingDotSegments(string referenced)
    {
        var source = new FakeSource();
        source.Drawing(Folder + @"\housing.SLDDRW", referenced);

        Assert.Single(Discover(source).Drawings);
    }

    [Theory]
    [InlineData("housing.SLDPRT")]
    [InlineData(@"bracket\housing.SLDPRT")]
    [InlineData(@"C:\Fictional\elsewhere\housing.SLDPRT")]
    [InlineData(@"\\fileserver\fictional\bracket\housing.SLDPRT")]
    public void Discover_NeverMatchesByFileNameAloneOrAnotherSpellingOfTheFolder(string referenced)
    {
        // A file name alone, a relative path (whatever the current directory is), a same-named
        // file in another folder, and a UNC spelling of the folder: none is the reached document.
        var source = new FakeSource();
        source.Drawing(Folder + @"\housing.SLDDRW", referenced);

        Assert.Empty(Discover(source).Drawings);
    }

    [Fact]
    public void Discover_AnAttachedDrawingThatAlsoShowsOutsideDocuments_IsAttachedAndTheOutsidePathsAreLeftToTheDrawingPhase()
    {
        // Section 3: a drawing that also shows documents outside the design is attached. The
        // "references '{path}', which is not part of this review" gap belongs to the view that
        // shows the path - its dvw id, which exists only once the drawing phase numbers the view,
        // as the assembly-drawings fixture records it - so discovery writes none of its own
        // (DrawingDumperTests.Dump_AnAttachedDrawingsViewOfAnOutsideDocument_...).
        const string DrawingPath = Folder + @"\housing.SLDDRW";
        var source = new FakeSource();
        source.Drawing(DrawingPath, HousingPath, OutsidePath, OutsidePath.ToUpperInvariant(), SecondOutsidePath);

        AttachedDrawings found = Discover(source);

        Assert.Equal(new[] { DrawingPath }, found.Drawings.Select(d => d.Path));
        Assert.DoesNotContain(_gaps.Gaps, g => g.EntityKind == "drawing_referenced_document");
    }

    [Fact]
    public void Discover_ViewsThatShowNothing_AreIgnoredWhenMatching()
    {
        // A sheet-format view or an empty view answers a blank referenced model name.
        var source = new FakeSource();
        source.Drawing(Folder + @"\housing.SLDDRW", "", "   ", HousingPath);

        Assert.Single(Discover(source).Drawings);
        Assert.DoesNotContain(_gaps.Gaps, g => g.EntityKind == "drawing_referenced_document");
    }

    [Fact]
    public void Discover_TheSameDrawingListedTwice_IsAttachedOnce()
    {
        var source = new FakeSource();
        source.Drawing(Folder + @"\housing.SLDDRW", HousingPath);
        source.Drawing(Folder + @"\HOUSING.slddrw", HousingPath);

        Assert.Single(Discover(source).Drawings);
    }

    [Fact]
    public void Discover_AnUnsavedDrawingThatShowsTheDesign_IsNotAttachedAndSaysWhy()
    {
        var source = new FakeSource();
        source.Add(new FakeDocument { Kind = DocumentKind.Drawing, Path = "", References = { HousingPath } });

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Drawings);
        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_discovery");
        Assert.Contains("never been saved", gap.Reason, StringComparison.Ordinal);
        Assert.Contains("open document 1", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Discover_AnUnsavedDrawingThatShowsNoneOfTheDesign_IsSilentlyIgnored()
    {
        var source = new FakeSource();
        source.Add(new FakeDocument { Kind = DocumentKind.Drawing, Path = null, References = { OutsidePath } });

        Assert.Empty(Discover(source).Drawings);
        Assert.Empty(_gaps.Gaps);
    }

    // ---- section 3: order and the ten-drawing bound --------------------------------------

    [Fact]
    public void Discover_OrdersRootDrawingsFirstThenByLowestTraversalIndexThenByPath()
    {
        // Traversal order: assembly (0), housing (1), pin (2), cover (3).
        string[] expected =
        {
            Folder + @"\a-root-too.SLDDRW",      // references the root (and cover)
            Folder + @"\z-root.SLDDRW",          // references the root
            Folder + @"\m-housing.SLDDRW",       // lowest index 1
            Folder + @"\b-pin.SLDDRW",           // lowest index 2 (pin and cover)
            Folder + @"\c-pin.SLDDRW",           // lowest index 2, path after b-
            Folder + @"\a-cover.SLDDRW",         // lowest index 3
        };

        var references = new Dictionary<string, string[]>
        {
            [expected[0]] = new[] { CoverPath, AssemblyPath },
            [expected[1]] = new[] { AssemblyPath },
            [expected[2]] = new[] { HousingPath, CoverPath },
            [expected[3]] = new[] { CoverPath, PinPath },
            [expected[4]] = new[] { PinPath },
            [expected[5]] = new[] { CoverPath },
        };

        foreach (int seed in new[] { 1, 7, 42 })
        {
            var gaps = new GapCollector();
            var source = new FakeSource();
            foreach (string path in expected.OrderBy(_ => Guid.NewGuid()).OrderBy(p => (p.GetHashCode() ^ seed) & 0xff))
            {
                source.Drawing(path, references[path]);
            }

            AttachedDrawings found = OpenDrawingDiscovery.Discover(
                FourDocumentTree(), source, Options(DumpProfile.Full), gaps);

            Assert.Equal(expected, found.Drawings.Select(d => d.Path));
        }
    }

    [Fact]
    public void Discover_AtTenDrawings_AttachesAllTenAndRaisesNoLimitGap()
    {
        var source = new FakeSource();
        foreach (string path in NumberedDrawings(10))
        {
            source.Drawing(path, HousingPath);
        }

        AttachedDrawings found = Discover(source);

        Assert.Equal(OpenDrawingDiscovery.MaxAttachedDrawings, found.Drawings.Count);
        Assert.Empty(found.NotRead);
        Assert.DoesNotContain(_gaps.Gaps, g => g.EntityKind == "drawing_attachment_limit");
    }

    [Fact]
    public void Discover_AtElevenDrawings_AttachesExactlyTenAndNamesTheEleventhInOneLimitGap()
    {
        string[] paths = NumberedDrawings(11).ToArray();
        var source = new FakeSource();
        foreach (string path in paths.Reverse())
        {
            source.Drawing(path, HousingPath);
        }

        AttachedDrawings found = Discover(source);

        Assert.Equal(paths.Take(10), found.Drawings.Select(d => d.Path));
        Assert.Equal(new[] { paths[10] }, found.NotRead);

        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_attachment_limit");
        Assert.Equal(
            "1 more open drawings show documents of this design and were not read: " + paths[10]
            + ". Close some and extract again to read them.",
            gap.Reason);
    }

    [Fact]
    public void Discover_TheLimitGapNamesEveryDrawingBeyondTheTenInOrder()
    {
        string[] paths = NumberedDrawings(13).ToArray();
        var source = new FakeSource();
        foreach (string path in paths)
        {
            source.Drawing(path, HousingPath);
        }

        AttachedDrawings found = Discover(source);

        Assert.Equal(paths.Skip(10), found.NotRead);
        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_attachment_limit");
        Assert.StartsWith("3 more open drawings", gap.Reason, StringComparison.Ordinal);
        Assert.Contains(string.Join(", ", paths.Skip(10)), gap.Reason, StringComparison.Ordinal);
    }

    // ---- section 5: candidates -----------------------------------------------------------

    [Theory]
    [InlineData(@"C:\Fictional\bracket\housing.SLDPRT", @"C:\Fictional\bracket\housing.SLDDRW")]
    [InlineData(@"C:\Fictional\bracket\bracket-assy.SLDASM", @"C:\Fictional\bracket\bracket-assy.SLDDRW")]
    [InlineData(@"C:\Fictional\bracket\housing.sldprt", @"C:\Fictional\bracket\housing.SLDDRW")]
    [InlineData(@"C:\Fictional\bracket\housing.v2.SLDPRT", @"C:\Fictional\bracket\housing.v2.SLDDRW")]
    [InlineData(@"C:\housing.SLDPRT", @"C:\housing.SLDDRW")]
    [InlineData(@"\\fileserver\fictional\housing.SLDPRT", @"\\fileserver\fictional\housing.SLDDRW")]
    public void CandidatePath_IsTheSameStemInTheSameFolderWithTheDrawingExtension(string model, string expected)
    {
        Assert.Equal(expected, OpenDrawingDiscovery.CandidatePath(model));
    }

    [Fact]
    public void Discover_ADocumentWithNoAttachedDrawingAndASameNameFileBesideIt_IsACandidate()
    {
        var source = new FakeSource();
        source.Exists(Folder + @"\housing.SLDDRW");

        AttachedDrawings found = Discover(source);

        DrawingCandidate candidate = Assert.Single(found.Candidates);
        Assert.Equal(DocumentIds.For(HousingPath), candidate.DocumentId);
        Assert.Equal(Folder + @"\housing.SLDDRW", candidate.Path);
        Assert.Equal(DrawingCandidateReason.SameNameBesideModel, candidate.Reason);
    }

    [Fact]
    public void Discover_AsksOnlyTheSameNameDrawingPathOncePerDocumentInTraversalOrder()
    {
        var source = new FakeSource();

        Discover(source, FourDocumentTree(extraInstanceOf: HousingPath));

        Assert.Equal(
            new[]
            {
                Folder + @"\bracket-assy.SLDDRW",
                Folder + @"\housing.SLDDRW",
                Folder + @"\pin.SLDDRW",
                Folder + @"\cover.SLDDRW",
            },
            source.ExistenceChecks);
    }

    [Fact]
    public void Discover_WritesCandidatesInTraversalOrder()
    {
        var source = new FakeSource();
        source.Exists(Folder + @"\cover.SLDDRW");
        source.Exists(Folder + @"\bracket-assy.SLDDRW");
        source.Exists(Folder + @"\pin.SLDDRW");

        AttachedDrawings found = Discover(source, FourDocumentTree());

        Assert.Equal(
            new[] { AssemblyPath, PinPath, CoverPath }.Select(DocumentIds.For),
            found.Candidates.Select(c => c.DocumentId));
    }

    [Fact]
    public void Discover_ADocumentAnAttachedDrawingShows_IsNeverAskedAbout()
    {
        var source = new FakeSource();
        source.Drawing(Folder + @"\some-housing-drawing.SLDDRW", HousingPath);
        source.Exists(Folder + @"\housing.SLDDRW");

        AttachedDrawings found = Discover(source);

        Assert.DoesNotContain(found.Candidates, c => c.DocumentId == DocumentIds.For(HousingPath));
        Assert.DoesNotContain(Folder + @"\housing.SLDDRW", source.ExistenceChecks, StringComparer.OrdinalIgnoreCase);
    }

    [Fact]
    public void Discover_ASameNameFileThatDoesNotExist_IsNoCandidateAndNoGap()
    {
        var source = new FakeSource();

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Candidates);
        Assert.Empty(_gaps.Gaps);
    }

    [Fact]
    public void Discover_AnExistenceCheckThatThrows_IsOneCandidateGapNamingTheDocumentAndNoCandidate()
    {
        var source = new FakeSource();
        source.ExistenceFailures[Folder + @"\housing.SLDDRW"] = new UnauthorizedAccessException("denied");

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Candidates);
        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_candidate");
        Assert.Equal(DocumentIds.For(HousingPath), gap.EntityId);
        Assert.Equal(GapKind.ToolError, gap.Kind);
        Assert.Contains("housing.SLDPRT", gap.Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Discover_APathlessDocumentIsNeverAskedAbout()
    {
        var tree = Tree(AssemblyPath, DocumentKind.Assembly, (HousingPath, DocumentKind.Part), ("", DocumentKind.Part));
        var source = new FakeSource();

        Discover(source, tree);

        Assert.Equal(
            new[] { Folder + @"\bracket-assy.SLDDRW", Folder + @"\housing.SLDDRW" },
            source.ExistenceChecks);
    }

    [Fact]
    public void Discover_SuppressedAndLightweightDocumentsAreAskedAboutToo()
    {
        ComponentTreeResult tree = AssemblyTree();
        tree.Nodes[1].Suppression = SuppressionState.Suppressed;
        tree.Nodes[2].Suppression = SuppressionState.Lightweight;
        var source = new FakeSource();
        source.Exists(Folder + @"\housing.SLDDRW");
        source.Exists(Folder + @"\pin.SLDDRW");

        AttachedDrawings found = Discover(source, tree);

        Assert.Equal(
            new[] { HousingPath, PinPath }.Select(DocumentIds.For),
            found.Candidates.Select(c => c.DocumentId));
    }

    [Fact]
    public void Discover_ASameNamePathThatIsOpenButShowsNoneOfTheDesign_IsNeverACandidateAndIsNamedInAGap()
    {
        const string SameName = Folder + @"\housing.SLDDRW";
        var source = new FakeSource();
        source.Drawing(SameName, OutsidePath);
        source.Exists(SameName);

        AttachedDrawings found = Discover(source);

        Assert.Empty(found.Drawings);
        Assert.Empty(found.Candidates);
        Assert.DoesNotContain(SameName, source.ExistenceChecks, StringComparer.OrdinalIgnoreCase);

        Gap gap = Assert.Single(_gaps.Gaps, g => g.EntityKind == "drawing_candidate");
        Assert.Equal(DocumentIds.For(HousingPath), gap.EntityId);
        Assert.Equal(GapKind.NotExtracted, gap.Kind);
        Assert.Equal(
            "the open drawing '" + SameName + "' has the name of housing.SLDPRT but shows none of "
            + "this design, so it was not read",
            gap.Reason);
    }

    [Fact]
    public void Discover_ASameNamePathThatIsOpenAndAttachedForAnotherDocument_IsNoCandidateAndNoGap()
    {
        // housing.SLDDRW shows the assembly but not the housing: it is read (attached), so the
        // housing gets no candidate - the file is already in the package - and nothing says it
        // was not read.
        const string SameName = Folder + @"\housing.SLDDRW";
        var source = new FakeSource();
        source.Drawing(SameName, AssemblyPath);
        source.Exists(SameName);

        AttachedDrawings found = Discover(source);

        Assert.Single(found.Drawings);
        Assert.DoesNotContain(found.Candidates, c => c.DocumentId == DocumentIds.For(HousingPath));
        Assert.DoesNotContain(_gaps.Gaps, g => g.EntityKind == "drawing_candidate");
    }

    [Fact]
    public void Discover_ASameNamePathThatIsOpenButBeyondTheLimit_IsNoCandidateTheLimitGapNamesIt()
    {
        string[] paths = NumberedDrawings(10).ToArray();
        const string SameName = Folder + @"\pin.SLDDRW";
        var source = new FakeSource();
        foreach (string path in paths)
        {
            source.Drawing(path, HousingPath);
        }

        source.Drawing(SameName, PinPath);
        source.Exists(SameName);

        AttachedDrawings found = Discover(source, Tree(AssemblyPath, DocumentKind.Assembly,
            (Folder + @"\a-first.SLDPRT", DocumentKind.Part), (HousingPath, DocumentKind.Part), (PinPath, DocumentKind.Part)));

        Assert.Equal(new[] { SameName }, found.NotRead);
        Assert.DoesNotContain(found.Candidates, c => c.DocumentId == DocumentIds.For(PinPath));
        Assert.DoesNotContain(_gaps.Gaps, g => g.EntityKind == "drawing_candidate");
    }

    [Fact]
    public void Discover_AFailedListingStillLooksBesideTheDesignForCandidates()
    {
        // The listing failing is one gap; the files beside the design are still facts on disk,
        // and nothing is attached, so every document is asked about as section 5 says.
        var source = new FakeSource { OpenDocumentsFailure = new InvalidOperationException("no answer") };
        source.Exists(Folder + @"\housing.SLDDRW");

        AttachedDrawings found = Discover(source);

        Assert.Single(found.Candidates);
    }

    // ---- the fakes and builders -----------------------------------------------------------

    private AttachedDrawings Discover(FakeSource source, ComponentTreeResult? tree = null) =>
        OpenDrawingDiscovery.Discover(tree ?? AssemblyTree(), source, Options(DumpProfile.Full), _gaps);

    private static DumpOptions Options(DumpProfile profile) => new DumpOptions { Profile = profile };

    private static IEnumerable<string> NumberedDrawings(int count) =>
        Enumerable.Range(1, count).Select(i => Folder + $@"\drawing-{i:00}.SLDDRW");

    private static ComponentTreeResult AssemblyTree() =>
        Tree(AssemblyPath, DocumentKind.Assembly, (HousingPath, DocumentKind.Part), (PinPath, DocumentKind.Part));

    private static ComponentTreeResult FourDocumentTree(string? extraInstanceOf = null)
    {
        var nodes = new List<(string, DocumentKind)>
        {
            (HousingPath, DocumentKind.Part),
            (PinPath, DocumentKind.Part),
        };

        if (extraInstanceOf != null)
        {
            nodes.Add((extraInstanceOf, DocumentKind.Part));
        }

        nodes.Add((CoverPath, DocumentKind.Part));
        return Tree(AssemblyPath, DocumentKind.Assembly, nodes.ToArray());
    }

    private static ComponentTreeResult Tree(
        string rootPath, DocumentKind rootKind, params (string Path, DocumentKind Kind)[] children)
    {
        var tree = new ComponentTreeResult
        {
            RootDocumentPath = rootPath,
            RootDocumentKind = rootKind,
            DesignName = System.IO.Path.GetFileNameWithoutExtension(rootPath),
            ActiveConfiguration = "Default",
        };

        if (rootKind != DocumentKind.Drawing)
        {
            tree.Nodes.Add(new ComponentNode
            {
                Key = "root",
                DocumentPath = rootPath,
                DocumentKind = rootKind,
            });
        }

        int index = 0;
        foreach ((string path, DocumentKind kind) in children)
        {
            index++;
            tree.Nodes.Add(new ComponentNode
            {
                Key = $"child-{index}",
                ParentKey = rootKind == DocumentKind.Drawing ? null : "root",
                DocumentPath = path,
                DocumentKind = kind,
            });
        }

        return tree;
    }

    /// <summary>One open document: each read answers, throws, or records that it was made.</summary>
    private sealed class FakeDocument
    {
        public object Handle { get; } = new object();

        public DocumentKind Kind { get; set; } = DocumentKind.Part;

        public Exception? KindFailure { get; set; }

        public string? Path { get; set; }

        public Exception? PathFailure { get; set; }

        public List<string> References { get; } = new List<string>();

        public Exception? ViewsFailure { get; set; }

        public List<string> Reads { get; } = new List<string>();

        public OpenDocument ToOpenDocument() => new OpenDocument(
            Handle,
            () =>
            {
                Reads.Add("kind");
                return KindFailure == null ? Kind : throw KindFailure;
            },
            () =>
            {
                Reads.Add("path");
                return PathFailure == null ? Path : throw PathFailure;
            },
            () =>
            {
                Reads.Add("views");
                return ViewsFailure == null ? References.ToArray() : throw ViewsFailure;
            });
    }

    private sealed class FakeSource : IOpenDrawingSource
    {
        private readonly List<FakeDocument> _documents = new List<FakeDocument>();
        private readonly HashSet<string> _existing = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        public Exception? OpenDocumentsFailure { get; set; }

        public int OpenDocumentsCalls { get; private set; }

        public List<string> ExistenceChecks { get; } = new List<string>();

        public Dictionary<string, Exception> ExistenceFailures { get; } =
            new Dictionary<string, Exception>(StringComparer.OrdinalIgnoreCase);

        public FakeDocument Add(FakeDocument document)
        {
            _documents.Add(document);
            return document;
        }

        public FakeDocument Drawing(string path, params string[] references)
        {
            var document = new FakeDocument { Kind = DocumentKind.Drawing, Path = path };
            document.References.AddRange(references);
            return Add(document);
        }

        public void Exists(string path) => _existing.Add(path);

        public IReadOnlyList<OpenDocument> OpenDocuments()
        {
            OpenDocumentsCalls++;
            if (OpenDocumentsFailure != null)
            {
                throw OpenDocumentsFailure;
            }

            return _documents.Select(document => document.ToOpenDocument()).ToArray();
        }

        public bool FileExists(string path)
        {
            ExistenceChecks.Add(path);
            if (ExistenceFailures.TryGetValue(path, out Exception? failure))
            {
                throw failure;
            }

            return _existing.Contains(path);
        }
    }
}
