using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Remodel.Seat;
using SwReview.Extractor.Guard;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004, T153 and T154 (build order lane B): the one scope-signal reader, over recording
/// stand-ins. Each row of contracts/bridge-remodel.md's <c>scope_signals</c> table is read with the
/// interop call the table names, and every value that cannot be read is null - unknown, never a
/// default and never a pass. The readings the table leaves open are tasks.md lane B's defaults of
/// 2026-09-27, pinned here.
/// </summary>
public class SwScopeSignalReaderTests
{
    // ---- GetType --------------------------------------------------------------------------------------

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    public void TheDocumentTypeIsGetTypesAnswer(int documentType)
    {
        var part = new StandInDocument();
        part.Document.Answer("GetType", documentType);

        Assert.Equal(documentType, new SwScopeSignalReader(part.Instance).GetDocumentType());
        Assert.Equal(new[] { "IModelDoc2.GetType" }, part.AllMembers());
    }

    // ---- body counts ----------------------------------------------------------------------------------

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    public void ABodyCountIsGetBodies2OfThatTypeVisibleOrNot(int bodyType)
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [bodyType] = new object[] { new object(), new object() } });

        Assert.Equal(2, new SwScopeSignalReader(part.Instance).GetBodyCount(bodyType));

        (string member, object?[] arguments) = Assert.Single(part.Document.Calls);
        Assert.Equal("GetBodies2", member);
        Assert.Equal(new object?[] { bodyType, false }, arguments);
    }

    [Fact]
    public void NoBodyOfATypeIsACountOfZero()
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?>());

        Assert.Equal(0, new SwScopeSignalReader(part.Instance).GetBodyCount(0));
    }

    [Fact]
    public void AnUnreadableBodyListIsAnUnknownCountNeverZero()
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [0] = "two bodies" });

        Assert.Null(new SwScopeSignalReader(part.Instance).GetBodyCount(0));
    }

    [Fact]
    public void ANullAmongTheBodiesIsAnUnknownCountNeverOneLess()
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [0] = new object?[] { new object(), null } });

        Assert.Null(new SwScopeSignalReader(part.Instance).GetBodyCount(0));
    }

    [Fact]
    public void ABodyCountReadsAOneBasedArrayWhole()
    {
        Array bodies = Array.CreateInstance(typeof(object), new[] { 3 }, new[] { 1 });
        for (int index = 1; index <= 3; index++)
        {
            bodies.SetValue(new object(), index);
        }

        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [0] = bodies });

        Assert.Equal(3, new SwScopeSignalReader(part.Instance).GetBodyCount(0));
    }

    // ---- a document that is not a part ----------------------------------------------------------------

    /// <summary>The part-only rows are unknown on a document that is not a part, and nothing is asked of it.</summary>
    [Fact]
    public void ThePartOnlyRowsAreUnknownOnADocumentThatIsNotAPart()
    {
        var assembly = new StandInDocument(isPart: false);
        var reader = new SwScopeSignalReader(assembly.Instance);

        Assert.Null(reader.GetBodyCount(0));
        Assert.Null(reader.IsWeldment());
        Assert.Null(reader.HasMeshBody());
        Assert.Null(reader.HasGraphicsBody());
        Assert.Empty(assembly.AllMembers());
    }

    // ---- weldment and sheet metal ---------------------------------------------------------------------

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void WeldmentIsIsWeldmentsAnswer(bool weldment)
    {
        var part = new StandInDocument();
        part.Document.Answer("IsWeldment", weldment);

        Assert.Equal(weldment, new SwScopeSignalReader(part.Instance).IsWeldment());
        Assert.Equal(new[] { "IModelDoc2.IsWeldment" }, part.AllMembers());
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void SheetMetalIsASheetMetalFolderBeingThere(bool present)
    {
        var part = new StandInDocument();
        part.Manager.Answer("GetSheetMetalFolder", present ? new object() : null);

        Assert.Equal(present, new SwScopeSignalReader(part.Instance).HasSheetMetalFolder());
        Assert.Equal(new[] { "IModelDoc2.get_FeatureManager", "IFeatureManager.GetSheetMetalFolder" }, part.AllMembers());
    }

    [Fact]
    public void NoFeatureManagerMakesEveryTreeRowUnknown()
    {
        var part = new StandInDocument();
        part.Document.Answer("get_FeatureManager", null);
        var reader = new SwScopeSignalReader(part.Instance);

        Assert.Null(reader.HasSheetMetalFolder());
        Assert.Null(reader.Is3DInterconnect());
        Assert.Null(reader.GetImportedFileNames());
        Assert.Null(reader.GetFolders());
    }

    // ---- mesh and graphics bodies: every body (default 1) ---------------------------------------------

    [Fact]
    public void TheMeshAndGraphicsRowsReadEveryBodyVisibleOrNot()
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [-1] = new object[] { Body().Instance } });

        new SwScopeSignalReader(part.Instance).HasMeshBody();

        (string member, object?[] arguments) = Assert.Single(part.Document.Calls);
        Assert.Equal("GetBodies2", member);
        Assert.Equal(new object?[] { -1, false }, arguments);
    }

    [Fact]
    public void AMeshBodyAnywhereIsPresent()
    {
        InteropRecorder<IBody2> plain = Body();
        InteropRecorder<IBody2> mesh = Body(mesh: true);
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [-1] = new object[] { plain.Instance, mesh.Instance } });
        var reader = new SwScopeSignalReader(part.Instance);

        Assert.True(reader.HasMeshBody());
        Assert.False(reader.HasGraphicsBody());
        Assert.Equal(new[] { "IsMeshBody", "IsGraphicsBody" }, plain.Members);
        Assert.Equal(new[] { "IsMeshBody", "IsGraphicsBody" }, mesh.Members);
    }

    [Fact]
    public void AGraphicsBodyAnywhereIsPresent()
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [-1] = new object[] { Body().Instance, Body(graphics: true).Instance } });
        var reader = new SwScopeSignalReader(part.Instance);

        Assert.True(reader.HasGraphicsBody());
        Assert.False(reader.HasMeshBody());
    }

    [Fact]
    public void APartWithNoBodyHasNoMeshAndNoGraphicsBody()
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?>());
        var reader = new SwScopeSignalReader(part.Instance);

        Assert.False(reader.HasMeshBody());
        Assert.False(reader.HasGraphicsBody());
    }

    [Fact]
    public void AnUnreadableBodyListIsUnknownNeverAbsent()
    {
        var part = new StandInDocument().WithBodies(new Dictionary<int, object?> { [-1] = 7 });
        var reader = new SwScopeSignalReader(part.Instance);

        Assert.Null(reader.HasMeshBody());
        Assert.Null(reader.HasGraphicsBody());
    }

    /// <summary>A body that cannot be asked makes "none" unknown, but a body that answers true is present whatever.</summary>
    [Fact]
    public void AnElementThatIsNotABodyIsUnknownUnlessAnotherBodyIsOne()
    {
        var unknown = new StandInDocument().WithBodies(new Dictionary<int, object?> { [-1] = new object?[] { Body().Instance, "not a body", null } });
        Assert.Null(new SwScopeSignalReader(unknown.Instance).HasMeshBody());

        var present = new StandInDocument().WithBodies(new Dictionary<int, object?> { [-1] = new object?[] { "not a body", Body(mesh: true).Instance } });
        Assert.True(new SwScopeSignalReader(present.Instance).HasMeshBody());
    }

    // ---- the feature walks: every feature (default 2) ---------------------------------------------------

    [Fact]
    public void TheFeatureWalksReadEveryFeatureNestedOnesIncluded()
    {
        InteropRecorder<Feature> nested = StandInDocument.Feature("Import1", "BaseBody");
        nested.Answer("GetImportedFileName", "C:\\imports\\bracket.step");
        var part = new StandInDocument().WithFeatures(topLevel: StandInDocument.Features(), all: StandInDocument.Features(nested));

        Assert.Equal(new[] { "C:\\imports\\bracket.step" }, new SwScopeSignalReader(part.Instance).GetImportedFileNames());
        Assert.Equal(new object?[] { false }, Assert.Single(part.Manager.Calls, call => call.Member == "GetFeatures").Arguments);
    }

    [Fact]
    public void A3DInterconnectFeatureAnywhereIsPresent()
    {
        InteropRecorder<Feature> linked = StandInDocument.Feature("Imported1").Answer("get_Is3DInterconnectFeature", true);
        var part = new StandInDocument().WithFeatures(StandInDocument.Feature("Boss-Extrude1"), linked);

        Assert.True(new SwScopeSignalReader(part.Instance).Is3DInterconnect());
        Assert.Contains("get_Is3DInterconnectFeature", linked.Members);
    }

    [Fact]
    public void NoLinkedFeatureIsNoInterconnect()
    {
        var part = new StandInDocument().WithFeatures(StandInDocument.Feature("Boss-Extrude1"), StandInDocument.Feature("Fillet1"));

        Assert.False(new SwScopeSignalReader(part.Instance).Is3DInterconnect());
    }

    [Theory]
    [InlineData(null)]
    [InlineData("a tree")]
    public void AnUnreadableTreeMakesEveryTreeRowUnknown(object? answer)
    {
        var part = new StandInDocument().WithFeatures(answer, answer);
        var reader = new SwScopeSignalReader(part.Instance);

        Assert.Null(reader.Is3DInterconnect());
        Assert.Null(reader.GetImportedFileNames());
        Assert.Null(reader.GetFolders());
    }

    [Fact]
    public void AnElementOfTheTreeThatIsNotAFeatureMakesTheTreeUnknown()
    {
        object?[] tree = { StandInDocument.Feature("Boss-Extrude1").Instance, "not a feature" };
        var part = new StandInDocument().WithFeatures(tree, tree);
        var reader = new SwScopeSignalReader(part.Instance);

        Assert.Null(reader.Is3DInterconnect());
        Assert.Null(reader.GetImportedFileNames());
        Assert.Null(reader.GetFolders());
    }

    // ---- imported file names and configurations (default 4) ---------------------------------------------

    [Fact]
    public void ImportedFileNamesAreEveryNonEmptyAnswerInWalkOrder()
    {
        InteropRecorder<Feature> first = StandInDocument.Feature("Imported1").Answer("GetImportedFileName", "C:\\imports\\a.step");
        InteropRecorder<Feature> plain = StandInDocument.Feature("Fillet1").Answer("GetImportedFileName", string.Empty);
        InteropRecorder<Feature> unnamed = StandInDocument.Feature("Cut1").Answer("GetImportedFileName", null);
        InteropRecorder<Feature> second = StandInDocument.Feature("Imported2").Answer("GetImportedFileName", "C:\\imports\\b.x_t");
        var part = new StandInDocument().WithFeatures(first, plain, unnamed, second);

        Assert.Equal(new[] { "C:\\imports\\a.step", "C:\\imports\\b.x_t" }, new SwScopeSignalReader(part.Instance).GetImportedFileNames());
    }

    [Fact]
    public void APartWithNothingImportedHasAnEmptyListNotAnUnknownOne()
    {
        var part = new StandInDocument().WithFeatures(StandInDocument.Feature("Boss-Extrude1"));

        Assert.Equal(new string[0], new SwScopeSignalReader(part.Instance).GetImportedFileNames());
    }

    public static IEnumerable<object?[]> ConfigurationAnswers() => new[]
    {
        new object?[] { "a string[]", new[] { "Default", "Long" }, new[] { "Default", "Long" } },
        new object?[] { "an object[] of strings", new object[] { "Default" }, new[] { "Default" } },
        new object?[] { "an empty array", new string[0], new string[0] },
        new object?[] { "null", null, null },
        new object?[] { "a lone string", "Default", null },
        new object?[] { "a null element", new object?[] { "Default", null }, null },
        new object?[] { "an element that is not a string", new object[] { "Default", 2 }, null },
    };

    [Theory]
    [MemberData(nameof(ConfigurationAnswers))]
    public void ConfigurationNamesAreReadOnlyFromAnArrayOfStrings(string shape, object? answer, string[]? names)
    {
        Assert.NotNull(shape);
        var part = new StandInDocument();
        part.Document.Answer("GetConfigurationNames", answer);

        IReadOnlyList<string>? read = new SwScopeSignalReader(part.Instance).GetConfigurationNames();

        if (names == null)
        {
            Assert.Null(read);
        }
        else
        {
            Assert.Equal(names, read);
        }

        Assert.Equal(new[] { "IModelDoc2.GetConfigurationNames" }, part.AllMembers());
    }

    // ---- folders (default 3) --------------------------------------------------------------------------

    [Fact]
    public void AFolderIsNamedAndCarriesItsMembersPersistRefsInOrder()
    {
        InteropRecorder<Feature> boss = StandInDocument.Feature("Boss-Extrude1");
        InteropRecorder<Feature> cut = StandInDocument.Feature("Cut-Extrude1");
        InteropRecorder<Feature> folder = Folder("3-Base", boss, cut);
        var part = new StandInDocument()
            .WithFeatures(folder, boss, cut)
            .WithPersistReferences(References((boss, new byte[] { 1, 2 }), (cut, new byte[] { 3 })));

        RmsNamedFolder read = Assert.Single(new SwScopeSignalReader(part.Instance).GetFolders()!);

        Assert.Equal("3-Base", read.Name);
        Assert.Equal(new[] { PersistRefCodec.Encode(new byte[] { 1, 2 }), PersistRefCodec.Encode(new byte[] { 3 }) }, read.MemberPersistRefs);
    }

    [Fact]
    public void OnlyFtrFolderFeaturesAreFoldersAndTheirTypeIsAskedOnce()
    {
        InteropRecorder<Feature> boss = StandInDocument.Feature("Boss-Extrude1");
        var part = new StandInDocument().WithFeatures(boss, StandInDocument.Feature("3-Base", "Extrusion"));

        Assert.Empty(new SwScopeSignalReader(part.Instance).GetFolders()!);
        Assert.Equal(new[] { "GetTypeName2" }, boss.Members);
    }

    /// <summary>The end-tag marker a flat tree closes a folder with is not a folder of its own.</summary>
    [Fact]
    public void TheEndTagMarkerIsNotAFolder()
    {
        InteropRecorder<Feature> boss = StandInDocument.Feature("Boss-Extrude1");
        InteropRecorder<Feature> endTag = StandInDocument.Feature("3-Base___EndTag___", "FtrFolder");
        var part = new StandInDocument()
            .WithFeatures(Folder("3-Base", boss), boss, endTag)
            .WithPersistReferences(References((boss, new byte[] { 9 })));

        RmsNamedFolder read = Assert.Single(new SwScopeSignalReader(part.Instance).GetFolders()!);

        Assert.Equal("3-Base", read.Name);
        Assert.DoesNotContain("GetSpecificFeature2", endTag.Members);
    }

    /// <summary>A folder with no members answers a null list and a count of zero, and is an empty folder.</summary>
    [Fact]
    public void AnEmptyFolderIsAFolderWithNoMembers()
    {
        InteropRecorder<IFeatureFolder> contents = new InteropRecorder<IFeatureFolder>().Answer("GetFeatureCount", 0).Answer("GetFeatures", null);
        InteropRecorder<Feature> folder = StandInDocument.Feature("6-Quarantine", "FtrFolder").Answer("GetSpecificFeature2", contents.Instance);
        var part = new StandInDocument().WithFeatures(folder);

        RmsNamedFolder read = Assert.Single(new SwScopeSignalReader(part.Instance).GetFolders()!);

        Assert.Equal("6-Quarantine", read.Name);
        Assert.Empty(read.MemberPersistRefs);
    }

    public static IEnumerable<object[]> UnreadableFolders() => new[]
    {
        new object[] { "the specific feature is not a folder" },
        new object[] { "the members disagree with the count" },
        new object[] { "a null member list with members counted" },
        new object[] { "the member list is not an array" },
        new object[] { "a member is not a feature" },
        new object[] { "a member has no persist ref" },
        new object[] { "the folder's name cannot be read" },
    };

    /// <summary>
    /// A folder whose members cannot all be read makes the whole listing unknown - never a
    /// shorter list, which would hide a folder from the scope gate - so the run is refused as
    /// <c>signal_unresolved</c>.
    /// </summary>
    [Theory]
    [MemberData(nameof(UnreadableFolders))]
    public void AFolderThatCannotBeReadMakesTheWholeListingUnknown(string how)
    {
        InteropRecorder<Feature> boss = StandInDocument.Feature("Boss-Extrude1");
        InteropRecorder<Feature> cut = StandInDocument.Feature("Cut-Extrude1");
        var references = References((boss, new byte[] { 1 }), (cut, new byte[] { 2 }));
        InteropRecorder<Feature> folder = Folder("3-Base", boss, cut);

        switch (how)
        {
            case "the specific feature is not a folder":
                folder.Answer("GetSpecificFeature2", new object());
                break;
            case "the members disagree with the count":
                folder.Answer("GetSpecificFeature2", Contents(3, StandInDocument.Features(boss, cut)).Instance);
                break;
            case "a null member list with members counted":
                folder.Answer("GetSpecificFeature2", Contents(2, null).Instance);
                break;
            case "the member list is not an array":
                folder.Answer("GetSpecificFeature2", Contents(1, boss.Instance).Instance);
                break;
            case "a member is not a feature":
                folder.Answer("GetSpecificFeature2", Contents(2, new object[] { boss.Instance, "cut" }).Instance);
                break;
            case "a member has no persist ref":
                references.Remove(cut.Instance);
                break;
            case "the folder's name cannot be read":
                folder.Answer("get_Name", null);
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(how), how, "Not a case.");
        }

        var part = new StandInDocument().WithFeatures(folder, boss, cut).WithPersistReferences(references);

        Assert.Null(new SwScopeSignalReader(part.Instance).GetFolders());
    }

    /// <summary>The folder's member refs are made by the same encoding the copy's adapter answers GetPersistReference with.</summary>
    [Fact]
    public void AFolderMembersRefIsTheCopysPersistReferenceOfThatMember()
    {
        InteropRecorder<Feature> boss = StandInDocument.Feature("Boss-Extrude1");
        var part = new StandInDocument()
            .WithFeatures(Folder("1-Reference", boss), boss)
            .WithPersistReferences(References((boss, new byte[] { 7, 7, 7 })));

        RmsNamedFolder read = Assert.Single(new SwScopeSignalReader(part.Instance).GetFolders()!);
        string? copyRef = new SwRemodelCopyDocument(new InteropRecorder<ISldWorks>().Instance, part.Instance).GetPersistReference(boss.Instance);

        Assert.Equal(copyRef, Assert.Single(read.MemberPersistRefs));
    }

    // ---- what the reader asks, across a whole reading ---------------------------------------------------

    /// <summary>
    /// A full reading of every row asks the document only the members contracts/bridge-remodel.md's
    /// table names, the accessors that reach them, and <c>GetType</c> - and never anything that
    /// writes, opens or saves.
    /// </summary>
    [Fact]
    public void AFullReadingAsksOnlyTheTablesMembers()
    {
        InteropRecorder<Feature> boss = StandInDocument.Feature("Boss-Extrude1");
        InteropRecorder<IFeatureFolder> contents = Contents(1, StandInDocument.Features(boss));
        InteropRecorder<Feature> folder = StandInDocument.Feature("3-Base", "FtrFolder").Answer("GetSpecificFeature2", contents.Instance);
        InteropRecorder<IBody2> body = Body();
        var part = new StandInDocument()
            .WithFeatures(folder, boss)
            .WithBodies(new Dictionary<int, object?> { [-1] = new object[] { body.Instance }, [0] = new object[] { body.Instance } })
            .WithPersistReferences(References((boss, new byte[] { 1 })));
        part.Document.Answer("GetConfigurationNames", new[] { "Default" });

        RemodelScopeProbe.ReadSignals(new SwGate(new CircuitBreaker(), new RemodelGuard()), new SwScopeSignalReader(part.Instance));

        var expected = new HashSet<string>(StringComparer.Ordinal)
        {
            "IModelDoc2.GetType", "IModelDoc2.GetBodies2", "IModelDoc2.IsWeldment", "IModelDoc2.get_FeatureManager",
            "IModelDoc2.GetConfigurationNames", "IModelDoc2.get_Extension",
            "IFeatureManager.GetSheetMetalFolder", "IFeatureManager.GetFeatures",
            "IModelDocExtension.GetPersistReference3",
        };
        Assert.Subset(expected, new HashSet<string>(part.AllMembers(), StringComparer.Ordinal));
        Assert.Equal(new[] { "IsMeshBody", "IsGraphicsBody" }, body.Members);
        Assert.Equal(new[] { "GetFeatureCount", "GetFeatures" }, contents.Members);
        Assert.Subset(
            new HashSet<string>(StringComparer.Ordinal) { "GetTypeName2", "get_Is3DInterconnectFeature", "GetImportedFileName" },
            new HashSet<string>(boss.Members, StringComparer.Ordinal));
        Assert.Subset(
            new HashSet<string>(StringComparer.Ordinal) { "GetTypeName2", "get_Name", "GetSpecificFeature2", "get_Is3DInterconnectFeature", "GetImportedFileName" },
            new HashSet<string>(folder.Members, StringComparer.Ordinal));
    }

    // ---- helpers --------------------------------------------------------------------------------------

    private static InteropRecorder<IBody2> Body(bool mesh = false, bool graphics = false) =>
        new InteropRecorder<IBody2>().Answer("IsMeshBody", mesh).Answer("IsGraphicsBody", graphics);

    private static InteropRecorder<IFeatureFolder> Contents(int count, object? members) =>
        new InteropRecorder<IFeatureFolder>().Answer("GetFeatureCount", count).Answer("GetFeatures", members);

    private static InteropRecorder<Feature> Folder(string name, params InteropRecorder<Feature>[] members) =>
        StandInDocument.Feature(name, "FtrFolder")
            .Answer("GetSpecificFeature2", Contents(members.Length, StandInDocument.Features(members)).Instance);

    private static Dictionary<object, byte[]> References(params (InteropRecorder<Feature> Feature, byte[] Bytes)[] references) =>
        references.ToDictionary(reference => (object)reference.Feature.Instance, reference => reference.Bytes);
}
