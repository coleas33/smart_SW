using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Remodel.Seat;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004, T154 (build order lane B): the source's read-only adapter. It reaches the engineer's
/// already-open part through <c>GetOpenDocumentByName</c> and nothing else, opens nothing, reads
/// only the probe's members, and answers nothing before <c>IsOpen</c> has bound a document.
/// </summary>
public class SwRemodelProbeSourceTests
{
    private const string SourcePath = "C:\\work\\bracket.SLDPRT";

    private readonly InteropRecorder<ISldWorks> _application = new InteropRecorder<ISldWorks>();
    private readonly StandInDocument _source = new StandInDocument();

    [Fact]
    public void AnOpenSourceIsBoundByGetOpenDocumentByNameAndNothingIsOpened()
    {
        _application.Answer("GetOpenDocumentByName", _source.Instance);

        Assert.True(new SwRemodelProbeSource(_application.Instance).IsOpen(SourcePath));

        (string member, object?[] arguments) = Assert.Single(_application.Calls);
        Assert.Equal("GetOpenDocumentByName", member);
        Assert.Equal(new object?[] { SourcePath }, arguments);
        Assert.Empty(_source.AllMembers());
    }

    [Fact]
    public void ASourceSolidWorksDoesNotHaveOpenIsNotOpenedToAnswer()
    {
        _application.Answer("GetOpenDocumentByName", null);

        Assert.False(new SwRemodelProbeSource(_application.Instance).IsOpen(SourcePath));
        Assert.Equal(new[] { "GetOpenDocumentByName" }, _application.Members);
    }

    [Fact]
    public void AnAnswerThatIsNotADocumentRaisesRatherThanReadingAsNotOpen()
    {
        _application.Answer("GetOpenDocumentByName", "a document");

        Assert.Throws<InvalidOperationException>(() => new SwRemodelProbeSource(_application.Instance).IsOpen(SourcePath));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void ABlankPathIsRefusedBeforeSolidWorksIsAsked(string? path)
    {
        Assert.Throws<ArgumentException>(() => new SwRemodelProbeSource(_application.Instance).IsOpen(path!));
        Assert.Empty(_application.Calls);
    }

    [Fact]
    public void TheProtocolReadsAreTheBoundDocumentsSaveFlagAndExternalReferenceCount()
    {
        _application.Answer("GetOpenDocumentByName", _source.Instance);
        _source.Document.Answer("GetSaveFlag", true).Answer("ListExternalFileReferencesCount2", 2);
        var probe = new SwRemodelProbeSource(_application.Instance);
        probe.IsOpen(SourcePath);

        Assert.True(probe.GetSaveFlag());
        Assert.Equal(2, probe.GetExternalReferenceCount());
        Assert.Equal(new[] { "IModelDoc2.GetSaveFlag", "IModelDoc2.ListExternalFileReferencesCount2" }, _source.AllMembers());
    }

    /// <summary>
    /// U26 (2026-09-28): the two reads that decide whether the save flag can be believed - the
    /// bound document's <c>IsOpenedReadOnly</c>, and the application's
    /// <c>GetUserPreferenceToggle(swExtRefNoPromptOrSave = 15)</c> - each exactly once, asking
    /// nothing else. The option is asked about only once a source is bound, like every read here.
    /// </summary>
    [Fact]
    public void TheReadOnlyStateIsTheBoundDocumentsAndTheOptionIsTheApplicationsToggle15()
    {
        _application.Answer("GetOpenDocumentByName", _source.Instance).Answer("GetUserPreferenceToggle", true);
        _source.Document.Answer("IsOpenedReadOnly", true);
        var probe = new SwRemodelProbeSource(_application.Instance);
        probe.IsOpen(SourcePath);

        Assert.True(probe.IsOpenedReadOnly());
        Assert.True(probe.GetDiscardsReadOnlyChanges());

        Assert.Equal(new[] { "IModelDoc2.IsOpenedReadOnly" }, _source.AllMembers());
        (string member, object?[] arguments) = _application.Calls.Last();
        Assert.Equal("GetUserPreferenceToggle", member);
        Assert.Equal(new object?[] { 15 }, arguments);
        Assert.Equal(RemodelScopeProbe.DiscardReadOnlyChangesToggle, 15);
    }

    [Fact]
    public void TheSignalsAreTheSharedReadersReadingOfTheBoundSource()
    {
        _application.Answer("GetOpenDocumentByName", _source.Instance);
        _source.Document.Answer("GetType", 1).Answer("IsWeldment", false).Answer("GetConfigurationNames", new[] { "Default", "Long" });
        _source.WithBodies(new Dictionary<int, object?> { [0] = new object[] { new object() } });
        _source.WithFeatures(StandInDocument.Feature("Sketch1", "ProfileFeature"), StandInDocument.Feature("Mirror-Part1", "MirrorStock"));
        var probe = new SwRemodelProbeSource(_application.Instance);
        probe.IsOpen(SourcePath);
        var reader = new SwScopeSignalReader(_source.Instance);

        Assert.Equal(reader.GetDocumentType(), probe.GetDocumentType());
        Assert.Equal(reader.GetBodyCount(0), probe.GetBodyCount(0));
        Assert.Equal(reader.IsWeldment(), probe.IsWeldment());
        Assert.Equal(reader.GetConfigurationNames(), probe.GetConfigurationNames());
        Assert.Equal(new[] { "ProfileFeature", "MirrorStock" }, probe.GetFeatureTypeNames());
        Assert.Equal(reader.GetFeatureTypeNames(), probe.GetFeatureTypeNames());
    }

    public static IEnumerable<object[]> BoundReads() => new[]
    {
        new object[] { "GetSaveFlag" },
        new object[] { "IsOpenedReadOnly" },
        new object[] { "GetDiscardsReadOnlyChanges" },
        new object[] { "GetExternalReferenceCount" },
        new object[] { "GetDocumentType" },
        new object[] { "GetBodyCount" },
        new object[] { "IsWeldment" },
        new object[] { "HasSheetMetalFolder" },
        new object[] { "HasMeshBody" },
        new object[] { "HasGraphicsBody" },
        new object[] { "Is3DInterconnect" },
        new object[] { "GetImportedFileNames" },
        new object[] { "GetConfigurationNames" },
        new object[] { "GetFolders" },
        new object[] { "GetFeatureTypeNames" },
    };

    /// <summary>The table above is every read of the interface, so a member added to it is a red test until it is here.</summary>
    [Fact]
    public void TheBoundReadsAreEveryMemberButIsOpen()
    {
        IEnumerable<string> members = typeof(IRemodelProbeSource).GetMethods()
            .Concat(typeof(IScopeSignalSource).GetMethods())
            .Select(method => method.Name)
            .Where(name => name != nameof(IRemodelProbeSource.IsOpen));

        Assert.Equal(
            members.OrderBy(name => name, StringComparer.Ordinal),
            BoundReads().Select(row => (string)row[0]).OrderBy(name => name, StringComparer.Ordinal));
    }

    /// <summary>Nothing is read before a document is bound: a read of nothing would be a reading of something else.</summary>
    [Theory]
    [MemberData(nameof(BoundReads))]
    public void NothingIsReadBeforeIsOpenHasBoundADocument(string read)
    {
        var probe = new SwRemodelProbeSource(_application.Instance);

        Assert.Throws<InvalidOperationException>(() => Read(probe, read));
        Assert.Empty(_application.Calls);
    }

    /// <summary>An IsOpen that answers false unbinds whatever an earlier one bound, so a later read cannot reach it.</summary>
    [Theory]
    [MemberData(nameof(BoundReads))]
    public void ASourceNoLongerOpenUnbindsTheEarlierDocument(string read)
    {
        var probe = new SwRemodelProbeSource(_application.Instance);
        _application.Answer("GetOpenDocumentByName", _source.Instance);
        Assert.True(probe.IsOpen(SourcePath));

        _application.Answer("GetOpenDocumentByName", null);
        Assert.False(probe.IsOpen(SourcePath));

        Assert.Throws<InvalidOperationException>(() => Read(probe, read));
        Assert.Empty(_source.AllMembers());
    }

    [Fact]
    public void ASecondIsOpenBindsTheDocumentItFinds()
    {
        var later = new StandInDocument();
        later.Document.Answer("GetSaveFlag", true);
        var probe = new SwRemodelProbeSource(_application.Instance);

        _application.Answer("GetOpenDocumentByName", _source.Instance);
        probe.IsOpen(SourcePath);
        _application.Answer("GetOpenDocumentByName", later.Instance);
        probe.IsOpen(SourcePath);

        Assert.True(probe.GetSaveFlag());
        Assert.Empty(_source.AllMembers());
    }

    [Fact]
    public void TheSourceRefusesAMissingApplication()
    {
        Assert.Equal("swApp", Assert.Throws<ArgumentNullException>(() => new SwRemodelProbeSource(null!)).ParamName);
    }

    private static void Read(SwRemodelProbeSource probe, string read)
    {
        switch (read)
        {
            case "GetSaveFlag":
                probe.GetSaveFlag();
                break;
            case "IsOpenedReadOnly":
                probe.IsOpenedReadOnly();
                break;
            case "GetDiscardsReadOnlyChanges":
                probe.GetDiscardsReadOnlyChanges();
                break;
            case "GetExternalReferenceCount":
                probe.GetExternalReferenceCount();
                break;
            case "GetDocumentType":
                probe.GetDocumentType();
                break;
            case "GetBodyCount":
                probe.GetBodyCount(0);
                break;
            case "IsWeldment":
                probe.IsWeldment();
                break;
            case "HasSheetMetalFolder":
                probe.HasSheetMetalFolder();
                break;
            case "HasMeshBody":
                probe.HasMeshBody();
                break;
            case "HasGraphicsBody":
                probe.HasGraphicsBody();
                break;
            case "Is3DInterconnect":
                probe.Is3DInterconnect();
                break;
            case "GetImportedFileNames":
                probe.GetImportedFileNames();
                break;
            case "GetConfigurationNames":
                probe.GetConfigurationNames();
                break;
            case "GetFolders":
                probe.GetFolders();
                break;
            case "GetFeatureTypeNames":
                probe.GetFeatureTypeNames();
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(read), read, "Not a read.");
        }
    }
}
