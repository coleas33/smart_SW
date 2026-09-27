using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Remodel.Seat;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Feature 004, T153 (build order lane B): the copy's adapter, one interop member per interface
/// member, over recording stand-ins. Each case pins the member called, its arguments, and that the
/// answer comes back unchanged - or, where the interface says so, that an answer that cannot be
/// read is unknown rather than a default. What SOLIDWORKS itself answers is a seat item.
/// </summary>
public class SwRemodelCopyDocumentTests
{
    private const string CopyPath = "C:\\runs\\20260927-100000-bracket-remodel\\copy\\bracket-RMS.SLDPRT";

    private readonly InteropRecorder<ISldWorks> _application = new InteropRecorder<ISldWorks>();
    private readonly StandInDocument _copy = new StandInDocument();

    // ---- IRemodelTarget --------------------------------------------------------------------------------

    [Fact]
    public void ThePathIsGetPathNamesAnswer()
    {
        _copy.Document.Answer("GetPathName", CopyPath);

        Assert.Equal(CopyPath, Adapter().GetPathName());
        Assert.Equal(new[] { "IModelDoc2.GetPathName" }, _copy.AllMembers());
    }

    [Fact]
    public void TheSessionTagIsGet4sRawValueOnTheDocumentLevelSet()
    {
        _copy.Properties.Handle("Get4", arguments =>
        {
            arguments[2] = "20260927-100000-bracket-remodel";
            arguments[3] = "resolved, and not what is read";
            return true;
        });

        Assert.Equal("20260927-100000-bracket-remodel", Adapter().GetSessionTag(RemodelCopy.SessionTagName));

        Assert.Equal(new object?[] { string.Empty }, Assert.Single(_copy.Extension.Calls).Arguments);
        (string member, object?[] arguments) = Assert.Single(_copy.Properties.Calls);
        Assert.Equal("Get4", member);
        Assert.Equal(RemodelCopy.SessionTagName, arguments[0]);
        Assert.Equal(false, arguments[1]);
    }

    [Fact]
    public void ATagGet4DoesNotFindIsNotThere()
    {
        _copy.Properties.Handle("Get4", arguments =>
        {
            arguments[2] = "left over";
            return false;
        });

        Assert.Null(Adapter().GetSessionTag(RemodelCopy.SessionTagName));
    }

    [Fact]
    public void NoCustomPropertyManagerRaisesForEveryTagMemberRatherThanReadingAsNoTag()
    {
        _copy.Extension.Answer("get_CustomPropertyManager", null);
        SwRemodelCopyDocument adapter = Adapter();

        Assert.Throws<InvalidOperationException>(() => adapter.GetSessionTag(RemodelCopy.SessionTagName));
        Assert.Throws<InvalidOperationException>(() => adapter.WriteSessionTag(RemodelCopy.SessionTagName, 30, "run", 2));
        Assert.Throws<InvalidOperationException>(() => adapter.RemoveSessionTag(RemodelCopy.SessionTagName));
    }

    [Fact]
    public void TheHeldDocumentAndTheOneOpenAtThePathAreTheSameIdentity()
    {
        _application.Answer("GetOpenDocumentByName", _copy.Instance);
        SwRemodelCopyDocument adapter = Adapter();

        IntPtr held = adapter.GetDocumentIdentity();

        Assert.NotEqual(IntPtr.Zero, held);
        Assert.Equal(held, adapter.GetOpenDocumentIdentity(CopyPath));
        Assert.Equal(new object?[] { CopyPath }, Assert.Single(_application.Calls).Arguments);
    }

    [Fact]
    public void AnotherDocumentOpenAtThePathIsAnotherIdentity()
    {
        _application.Answer("GetOpenDocumentByName", new StandInDocument().Instance);
        SwRemodelCopyDocument adapter = Adapter();

        Assert.NotEqual(adapter.GetDocumentIdentity(), adapter.GetOpenDocumentIdentity(CopyPath));
    }

    [Fact]
    public void NothingOpenAtThePathIsTheZeroIdentity()
    {
        _application.Answer("GetOpenDocumentByName", null);

        Assert.Equal(IntPtr.Zero, Adapter().GetOpenDocumentIdentity(CopyPath));
    }

    // ---- IRemodelCopyTarget ----------------------------------------------------------------------------

    [Fact]
    public void TheTagIsWrittenWithAdd3sArgumentsAndItsAnswerHandedBack()
    {
        _copy.Properties.Answer("Add3", -1);

        int answer = Adapter().WriteSessionTag(
            RemodelCopy.SessionTagName, RemodelCopy.SessionTagType, "20260927-100000-bracket-remodel", RemodelCopy.SessionTagOverwrite);

        Assert.Equal(-1, answer);
        (string member, object?[] arguments) = Assert.Single(_copy.Properties.Calls);
        Assert.Equal("Add3", member);
        Assert.Equal(new object?[] { RemodelCopy.SessionTagName, 30, "20260927-100000-bracket-remodel", 2 }, arguments);
    }

    [Fact]
    public void TheTagIsRemovedWithDelete2AndItsAnswerHandedBack()
    {
        _copy.Properties.Answer("Delete2", 0);

        Assert.Equal(0, Adapter().RemoveSessionTag(RemodelCopy.SessionTagName));
        (string member, object?[] arguments) = Assert.Single(_copy.Properties.Calls);
        Assert.Equal("Delete2", member);
        Assert.Equal(new object?[] { RemodelCopy.SessionTagName }, arguments);
    }

    // ---- IScopeSignalSource: the shared reader ----------------------------------------------------------

    [Fact]
    public void TheCopysSignalsAreTheSharedReadersReadingOfTheCopy()
    {
        _copy.Document.Answer("GetType", 1).Answer("IsWeldment", true).Answer("GetConfigurationNames", new[] { "Default" });
        _copy.WithBodies(new Dictionary<int, object?> { [0] = new object[] { new object() } });
        _copy.WithFeatures(StandInDocument.Feature("Sketch1", "ProfileFeature"), StandInDocument.Feature("Boss-Extrude1"));
        SwRemodelCopyDocument adapter = Adapter();
        var reader = new SwScopeSignalReader(_copy.Instance);

        Assert.Equal(reader.GetDocumentType(), adapter.GetDocumentType());
        Assert.Equal(reader.GetBodyCount(0), adapter.GetBodyCount(0));
        Assert.Equal(reader.IsWeldment(), adapter.IsWeldment());
        Assert.Equal(reader.GetConfigurationNames(), adapter.GetConfigurationNames());
        Assert.Equal(new[] { "ProfileFeature", "Extrusion" }, adapter.GetFeatureTypeNames());
        Assert.Equal(reader.GetFeatureTypeNames(), adapter.GetFeatureTypeNames());
    }

    // ---- IGeometrySource ---------------------------------------------------------------------------------

    [Fact]
    public void AMassPropertyIsLaneAsSharedClassOverWhatCreateMassProperty2Made()
    {
        var massProperty = new InteropRecorder<IMassProperty2>().Answer("Recalculate", true).Answer("get_Volume", 0.25);
        _copy.Extension.Answer("CreateMassProperty2", massProperty.Instance);

        IMassPropertyReading? reading = Adapter().CreateMassProperty();

        Assert.IsType<SwMassProperty>(reading);
        Assert.True(reading!.Recalculate());
        Assert.Equal(0.25, reading.GetVolume());
        Assert.Equal(new[] { "Recalculate", "get_Volume" }, massProperty.Members);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void NoMassPropertyIsAFailedCreate(bool answerSomethingElse)
    {
        _copy.Extension.Answer("CreateMassProperty2", answerSomethingElse ? new object() : null);

        Assert.Null(Adapter().CreateMassProperty());
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    public void TheBodiesAreGetBodies2OfThatTypeVisibleOrNotInOrder(int bodyType)
    {
        object first = new object();
        object second = new object();
        _copy.WithBodies(new Dictionary<int, object?> { [bodyType] = new[] { first, second } });

        IReadOnlyList<object>? bodies = Adapter().GetBodies(bodyType);

        Assert.Equal(new[] { first, second }, bodies);
        Assert.Equal(new object?[] { bodyType, false }, Assert.Single(_copy.Document.Calls).Arguments);
    }

    [Fact]
    public void NoBodyOfATypeIsNone()
    {
        _copy.WithBodies(new Dictionary<int, object?>());

        Assert.Null(Adapter().GetBodies(0));
    }

    [Theory]
    [InlineData("a string")]
    [InlineData("a null body")]
    public void AnUnreadableBodyListRaisesRatherThanReadingAsNone(string how)
    {
        object answer = how == "a string" ? "bodies" : new object?[] { new object(), null };
        _copy.WithBodies(new Dictionary<int, object?> { [0] = answer });

        Assert.Throws<InvalidOperationException>(() => Adapter().GetBodies(0));
    }

    [Fact]
    public void ACopyThatIsNotAPartHasNoBodiesToReadAndSaysSo()
    {
        var assembly = new StandInDocument(isPart: false);

        Assert.Throws<InvalidOperationException>(() => new SwRemodelCopyDocument(_application.Instance, assembly.Instance).GetBodies(0));
        Assert.Null(new SwRemodelCopyDocument(_application.Instance, assembly.Instance).GetMaterialName());
    }

    [Fact]
    public void FaceAndEdgeCountsAreEachBodysAnswer()
    {
        var body = new InteropRecorder<IBody2>().Answer("GetFaceCount", 6).Answer("GetEdgeCount", 12);

        Assert.Equal(6, Adapter().GetFaceCount(body.Instance));
        Assert.Equal(12, Adapter().GetEdgeCount(body.Instance));
        Assert.Equal(new[] { "GetFaceCount", "GetEdgeCount" }, body.Members);
    }

    [Fact]
    public void ABodyThatIsNotABodyHasUnreadableCountsNeverZero()
    {
        Assert.Null(Adapter().GetFaceCount(new object()));
        Assert.Null(Adapter().GetEdgeCount("body"));
    }

    [Theory]
    [InlineData("6061-T6")]
    [InlineData("")]
    [InlineData(null)]
    public void TheMaterialIsReadForTheActiveConfigurationByNameAndHandedBackUnchanged(string? material)
    {
        _copy.ActiveConfiguration.Answer("get_Name", "Default");
        _copy.Document.Answer("GetMaterialPropertyName2", material);

        Assert.Equal(material, Adapter().GetMaterialName());
        (string member, object?[] arguments) = Assert.Single(_copy.Document.Calls, call => call.Member == "GetMaterialPropertyName2");
        Assert.Equal("Default", arguments[0]);
    }

    [Theory]
    [InlineData("no active configuration")]
    [InlineData("no configuration manager")]
    [InlineData("a configuration with no name")]
    public void AnUnreadableActiveConfigurationIsAnUnknownMaterial(string how)
    {
        switch (how)
        {
            case "no active configuration":
                _copy.Configurations.Answer("get_ActiveConfiguration", null);
                break;
            case "no configuration manager":
                _copy.Document.Answer("get_ConfigurationManager", null);
                break;
            default:
                _copy.ActiveConfiguration.Answer("get_Name", null);
                break;
        }

        Assert.Null(Adapter().GetMaterialName());
        Assert.DoesNotContain("GetMaterialPropertyName2", _copy.Document.Members);
    }

    // ---- persist refs ------------------------------------------------------------------------------------

    [Fact]
    public void AReferenceIsDecodedAndResolvedWithItsErrorCodeRead()
    {
        byte[] bytes = { 4, 8, 15, 16 };
        object feature = StandInDocument.Feature("Fillet1").Instance;
        _copy.Extension.Handle("GetObjectByPersistReference3", arguments =>
        {
            arguments[1] = 0;
            return feature;
        });

        object? resolved = Adapter().ResolveByPersistReference(PersistRefCodec.Encode(bytes), out int errorCode);

        Assert.Same(feature, resolved);
        Assert.Equal(0, errorCode);
        (string member, object?[] arguments) = Assert.Single(_copy.Extension.Calls, call => call.Member == "GetObjectByPersistReference3");
        Assert.Equal(bytes, Assert.IsType<byte[]>(arguments[0]));
    }

    [Theory]
    [InlineData(2)]
    [InlineData(4)]
    public void AReferenceThatDoesNotResolveHandsBackSolidWorksErrorCode(int state)
    {
        _copy.Extension.Handle("GetObjectByPersistReference3", arguments =>
        {
            arguments[1] = state;
            return null;
        });

        Assert.Null(Adapter().ResolveByPersistReference(PersistRefCodec.Encode(new byte[] { 1 }), out int errorCode));
        Assert.Equal(state, errorCode);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("not base64 at all!")]
    public void AReferenceThatDoesNotDecodeIsInvalidAndSolidWorksIsNotAsked(string persistRef)
    {
        Assert.Null(Adapter().ResolveByPersistReference(persistRef, out int errorCode));

        Assert.Equal(1, errorCode);
        Assert.Empty(_copy.AllMembers());
    }

    [Fact]
    public void AFeaturesReferenceIsTheCodecsBase64OfGetPersistReference3sBytes()
    {
        InteropRecorder<Feature> feature = StandInDocument.Feature("Fillet1");
        _copy.WithPersistReferences(new Dictionary<object, byte[]> { [feature.Instance] = new byte[] { 9, 9 } });

        Assert.Equal(PersistRefCodec.Encode(new byte[] { 9, 9 }), Adapter().GetPersistReference(feature.Instance));
        Assert.Same(feature.Instance, Assert.Single(_copy.Extension.Calls).Arguments[0]);
    }

    [Theory]
    [InlineData("null")]
    [InlineData("empty")]
    [InlineData("a string")]
    public void AFeatureWithNoReferenceHasNone(string how)
    {
        object? answer = how == "null" ? null : how == "empty" ? new byte[0] : (object)"ref";
        _copy.Extension.Answer("GetPersistReference3", answer);

        Assert.Null(Adapter().GetPersistReference(StandInDocument.Feature("Fillet1").Instance));
    }

    // ---- the tree ----------------------------------------------------------------------------------------

    [Fact]
    public void TheTreeIsTheTopLevelWalkInItsOrder()
    {
        InteropRecorder<Feature> boss = StandInDocument.Feature("Boss-Extrude1");
        InteropRecorder<Feature> cut = StandInDocument.Feature("Cut-Extrude1");
        _copy.WithFeatures(topLevel: StandInDocument.Features(boss, cut), all: StandInDocument.Features(cut, boss, cut));

        Assert.Equal(new object[] { boss.Instance, cut.Instance }, Adapter().GetFeaturesInOrder());
        Assert.Equal(new object?[] { true }, Assert.Single(_copy.Manager.Calls).Arguments);
    }

    [Theory]
    [InlineData("null")]
    [InlineData("a string")]
    [InlineData("an element that is not a feature")]
    public void AnUnreadableTreeRaisesRatherThanReadingAsEmpty(string how)
    {
        object? answer = how == "null" ? null : how == "a string" ? "tree" : new object[] { StandInDocument.Feature("Boss-Extrude1").Instance, 7 };
        _copy.WithFeatures(answer, answer);

        Assert.Throws<InvalidOperationException>(() => Adapter().GetFeaturesInOrder());
    }

    // ---- one feature member, one interop call -------------------------------------------------------------

    public static IEnumerable<object[]> FeatureMembers() => new[]
    {
        new object[] { "GetFeatureName", "get_Name" },
        new object[] { "GetFeatureDescription", "get_Description" },
        new object[] { "GetFeatureTypeName", "GetTypeName2" },
        new object[] { "IsRolledBack", "IsRolledBack" },
        new object[] { "GetFeatureErrorCode", "GetErrorCode2" },
        new object[] { "SetFeatureName", "set_Name" },
        new object[] { "SetFeatureDescription", "set_Description" },
        new object[] { "SelectFeature", "Select2" },
    };

    [Theory]
    [MemberData(nameof(FeatureMembers))]
    public void EachFeatureMemberCallsExactlyItsOneInteropMemberOnThatFeature(string member, string interop)
    {
        var feature = new InteropRecorder<Feature>();

        CallFeatureMember(Adapter(), member, feature.Instance);

        (string called, object?[] arguments) = Assert.Single(feature.Calls);
        Assert.Equal(interop, called);
        Assert.Equal(FeatureArguments(member), arguments.Take(FeatureArguments(member).Length));
        Assert.Empty(_copy.AllMembers());
    }

    [Theory]
    [MemberData(nameof(FeatureMembers))]
    public void AFeatureMemberHandedSomethingThatIsNotAFeatureRefusesItAndAsksNothing(string member, string interop)
    {
        Assert.NotNull(interop);

        Assert.Throws<ArgumentException>(() => CallFeatureMember(Adapter(), member, new object()));
        Assert.Empty(_copy.AllMembers());
    }

    [Fact]
    public void TheFeatureAnswersComeBackUnchanged()
    {
        var feature = new InteropRecorder<Feature>()
            .Answer("get_Name", "Fillet1")
            .Answer("get_Description", "edge break")
            .Answer("GetTypeName2", "Fillet")
            .Answer("IsRolledBack", true)
            .Answer("Select2", true)
            .Handle("GetErrorCode2", arguments =>
            {
                arguments[0] = true;
                return 41;
            });
        SwRemodelCopyDocument adapter = Adapter();

        Assert.Equal("Fillet1", adapter.GetFeatureName(feature.Instance));
        Assert.Equal("edge break", adapter.GetFeatureDescription(feature.Instance));
        Assert.Equal("Fillet", adapter.GetFeatureTypeName(feature.Instance));
        Assert.True(adapter.IsRolledBack(feature.Instance));
        Assert.True(adapter.SelectFeature(feature.Instance, true, 0));
        Assert.Equal(41, adapter.GetFeatureErrorCode(feature.Instance, out bool isWarning));
        Assert.True(isWarning);
    }

    /// <summary>A description read as null is unreadable and stays null; it never becomes "" (absent).</summary>
    [Fact]
    public void AnUnreadableDescriptionStaysNull()
    {
        var feature = new InteropRecorder<Feature>().Answer("get_Description", null);

        Assert.Null(Adapter().GetFeatureDescription(feature.Instance));
    }

    // ---- the document's writes and reads --------------------------------------------------------------------

    [Fact]
    public void ClearingTheSelectionClearsAllOfIt()
    {
        Adapter().ClearSelection();

        (string member, object?[] arguments) = Assert.Single(_copy.Document.Calls);
        Assert.Equal("ClearSelection2", member);
        Assert.Equal(new object?[] { true }, arguments);
    }

    [Theory]
    [InlineData(2, true)]
    [InlineData(3, false)]
    public void AReorderIsReorderFeatureByNameWithItsAnswer(int location, bool answer)
    {
        _copy.Extension.Answer("ReorderFeature", answer);

        Assert.Equal(answer, Adapter().ReorderFeature("Fillet1", "Cut-Extrude1", location));

        (string member, object?[] arguments) = Assert.Single(_copy.Extension.Calls);
        Assert.Equal("ReorderFeature", member);
        Assert.Equal(new object?[] { "Fillet1", "Cut-Extrude1", location }, arguments);
    }

    [Fact]
    public void AFolderIsInsertedWithTheTypeAsked()
    {
        InteropRecorder<Feature> folder = StandInDocument.Feature("Folder1", "FtrFolder");
        _copy.Manager.Answer("InsertFeatureTreeFolder2", folder.Instance);

        Assert.Same(folder.Instance, Adapter().InsertFeatureTreeFolder(2));

        (string member, object?[] arguments) = Assert.Single(_copy.Manager.Calls);
        Assert.Equal("InsertFeatureTreeFolder2", member);
        Assert.Equal(new object?[] { 2 }, arguments);
    }

    [Fact]
    public void AFeaturesFolderIsFeatureFolderLocationOfThatFeature()
    {
        InteropRecorder<Feature> feature = StandInDocument.Feature("Fillet1");
        InteropRecorder<Feature> folder = StandInDocument.Feature("4-Detail", "FtrFolder");
        _copy.Manager.Answer("FeatureFolderLocation", folder.Instance);

        Assert.Same(folder.Instance, Adapter().GetFeatureFolder(feature.Instance));
        Assert.Same(feature.Instance, Assert.Single(_copy.Manager.Calls).Arguments[0]);
    }

    [Fact]
    public void TheRollbackMovesTheBarToTheEndWithNoFeatureNamed()
    {
        _copy.Manager.Answer("EditRollback", true);

        Assert.True(Adapter().EditRollbackToEnd());

        (string member, object?[] arguments) = Assert.Single(_copy.Manager.Calls);
        Assert.Equal("EditRollback", member);
        Assert.Equal(new object?[] { 1, string.Empty }, arguments);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void TheRebuildIsForceRebuild3WithTopOnlyAsAsked(bool topOnly)
    {
        _copy.Document.Answer("ForceRebuild3", true);

        Assert.True(Adapter().ForceRebuild(topOnly));
        Assert.Equal(new object?[] { topOnly }, Assert.Single(_copy.Document.Calls).Arguments);
    }

    [Fact]
    public void TheRebuildErrorCountIsGetWhatsWrongCountsAnswer()
    {
        _copy.Extension.Answer("GetWhatsWrongCount", 3);

        Assert.Equal(3, Adapter().GetWhatsWrongCount());
    }

    [Fact]
    public void WhatsWrongIsOneEntryPerElementAsTheSharedReadingReadsThem()
    {
        _copy.Extension.Handle("GetWhatsWrong", arguments =>
        {
            arguments[0] = new object[] { "Fillet1", "Shell1" };
            arguments[1] = new object[] { 3, 7 };
            arguments[2] = new object[] { false, true };
            return true;
        });

        Assert.Equal(new[] { "Fillet1: error 3", "Shell1: error 7 (warning)" }, Adapter().GetWhatsWrong());
    }

    [Fact]
    public void WhatsWrongAnsweringFalseIsNoEntries()
    {
        _copy.Extension.Handle("GetWhatsWrong", arguments =>
        {
            arguments[0] = new object[] { "Fillet1" };
            return false;
        });

        Assert.Empty(Adapter().GetWhatsWrong());
    }

    [Fact]
    public void TheEquationsAreLaneAsSharedClassOverTheCopysManager()
    {
        var manager = new InteropRecorder<EquationMgr>().Answer("GetCount", 2);
        _copy.Document.Answer("GetEquationMgr", manager.Instance);

        IEquationTarget equations = Adapter().Equations;

        Assert.IsType<SwEquationManager>(equations);
        Assert.Equal(2, equations.GetCount());
        Assert.Equal(new[] { "GetCount" }, manager.Members);
    }

    [Fact]
    public void NoEquationManagerRaises()
    {
        _copy.Document.Answer("GetEquationMgr", null);

        Assert.Throws<InvalidOperationException>(() => Adapter().Equations);
    }

    [Fact]
    public void TheSaveIsSave3WithItsOptionsAndBothOutParametersRead()
    {
        _copy.Document.Handle("Save3", arguments =>
        {
            arguments[1] = 0;
            arguments[2] = RemodelCopy.SaveWarningRebuildError;
            return true;
        });

        Assert.True(Adapter().Save(RemodelCopy.SaveOptions, out int errors, out int warnings));

        Assert.Equal(0, errors);
        Assert.Equal(1, warnings);
        (string member, object?[] arguments) = Assert.Single(_copy.Document.Calls);
        Assert.Equal("Save3", member);
        Assert.Equal(1, arguments[0]);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void TheSaveFlagIsGetSaveFlagsAnswer(bool dirty)
    {
        _copy.Document.Answer("GetSaveFlag", dirty);

        Assert.Equal(dirty, Adapter().GetSaveFlag());
    }

    [Theory]
    [InlineData(0, "mm")]
    [InlineData(3, "in")]
    [InlineData(2, "m")]
    [InlineData(1, "cm")]
    [InlineData(99, null)]
    public void TheLengthUnitIsGetUnitsFirstPlaceNamed(int lengthUnit, string? token)
    {
        _copy.Document.Answer("GetUnits", new[] { lengthUnit, 0, 2, 3, 0 });

        Assert.Equal(token, Adapter().GetLengthUnit());
        Assert.Equal(new[] { "IModelDoc2.GetUnits" }, _copy.AllMembers());
    }

    [Fact]
    public void AnUnreadableUnitsAnswerIsAnUnknownUnitNeverMetres()
    {
        _copy.Document.Answer("GetUnits", null);

        Assert.Null(Adapter().GetLengthUnit());
    }

    // ---- construction --------------------------------------------------------------------------------------

    [Fact]
    public void TheAdapterRefusesAMissingApplicationOrDocument()
    {
        Assert.Equal("swApp", Assert.Throws<ArgumentNullException>(() => new SwRemodelCopyDocument(null!, _copy.Instance)).ParamName);
        Assert.Equal("document", Assert.Throws<ArgumentNullException>(() => new SwRemodelCopyDocument(_application.Instance, null!)).ParamName);
    }

    /// <summary>Building the adapter asks SOLIDWORKS nothing: every call is made when a member is asked for.</summary>
    [Fact]
    public void BuildingTheAdapterAsksNothing()
    {
        Adapter();

        Assert.Empty(_copy.AllMembers());
        Assert.Empty(_application.Calls);
    }

    // ---- helpers ---------------------------------------------------------------------------------------------

    private SwRemodelCopyDocument Adapter() => new SwRemodelCopyDocument(_application.Instance, _copy.Instance);

    private static void CallFeatureMember(SwRemodelCopyDocument adapter, string member, object feature)
    {
        switch (member)
        {
            case "GetFeatureName":
                adapter.GetFeatureName(feature);
                break;
            case "GetFeatureDescription":
                adapter.GetFeatureDescription(feature);
                break;
            case "GetFeatureTypeName":
                adapter.GetFeatureTypeName(feature);
                break;
            case "IsRolledBack":
                adapter.IsRolledBack(feature);
                break;
            case "GetFeatureErrorCode":
                adapter.GetFeatureErrorCode(feature, out _);
                break;
            case "SetFeatureName":
                adapter.SetFeatureName(feature, "Fillet-Edge1");
                break;
            case "SetFeatureDescription":
                adapter.SetFeatureDescription(feature, "why it is here");
                break;
            case "SelectFeature":
                adapter.SelectFeature(feature, true, 4);
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(member), member, "Not a feature member.");
        }
    }

    private static object?[] FeatureArguments(string member)
    {
        switch (member)
        {
            case "SetFeatureName":
                return new object?[] { "Fillet-Edge1" };
            case "SetFeatureDescription":
                return new object?[] { "why it is here" };
            case "SelectFeature":
                return new object?[] { true, 4 };
            default:
                return new object?[0];
        }
    }
}
