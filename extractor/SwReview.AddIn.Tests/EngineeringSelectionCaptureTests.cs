using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.EngineeringContext;
using SwReview.AddIn.Review;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Tests;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>Fictional saved evidence and recording interop proxies; no CAD process exists.</summary>
public sealed class EngineeringSelectionCaptureTests
{
    [Fact]
    public void AUniqueComponentIsMatchedUsingScopedNativeIdentityDespiteDifferentBytes()
    {
        using var seat = new SelectionSeat();
        EngineeringSelectionObservation result = seat.Capture();

        Assert.Equal("matched_saved_target", result.Status);
        Assert.Equal("component", result.Kind);
        Assert.Equal("cmp:0002", result.EntityId);
        Assert.Equal("cmp:0002", result.ComponentId);
        Assert.Equal(seat.Package.PackageId, result.PackageId);
        Assert.Equal(seat.RootId, result.RootDocumentId);
        Assert.Equal(seat.OwnerId, result.DocumentId);
        Assert.Equal("Default", result.Configuration);
        Assert.False(result.NativeCalibrated);
        Assert.Equal("selection_observation_only", result.NativeModelState);
        Assert.Equal("cannot_establish", result.Freshness);
        Assert.False(result.RootDirty);
        Assert.True(result.RootDirtyReliable);
        Assert.Empty(result.ReasonCodes);
        Assert.Equal(1, seat.Thread.Invocations);
        Assert.Contains("IsSamePersistentID", seat.Root.Extension.Members);
        seat.AssertReadOnly();
    }

    [Fact]
    public void AnAssemblyFaceMatchesItsOccurrenceAndThenTheMappedPartFaceSeparately()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();

        EngineeringSelectionObservation result = seat.Capture();

        Assert.Equal("matched_saved_target", result.Status);
        Assert.Equal("face", result.Kind);
        Assert.Equal("face:0001", result.EntityId);
        Assert.Equal("cmp:0002", result.ComponentId);
        Assert.Contains("GetComponent", seat.AssemblyFace.Members);
        Assert.Contains("IsSamePersistentID", seat.Root.Extension.Members);
        Assert.Contains("IsSamePersistentID", seat.Owner.Extension.Members);
        Assert.Contains(seat.Owner.Extension.Calls, call =>
            call.Member == "GetCorrespondingEntity2"
            && ReferenceEquals(call.Arguments[0], seat.AssemblyFace.Instance));
        Assert.Contains(seat.Owner.Extension.Calls, call =>
            call.Member == "GetPersistReference3"
            && ReferenceEquals(call.Arguments[0], seat.PartFace.Instance));
        seat.AssertReadOnly();
    }

    [Fact]
    public void AStandalonePartFaceUsesTheSavedRootOccurrenceAndPartScope()
    {
        using var seat = new SelectionSeat();
        seat.SelectPartFace();

        EngineeringSelectionObservation result = seat.Capture();

        Assert.Equal("matched_saved_target", result.Status);
        Assert.Equal("face:0001", result.EntityId);
        Assert.Equal("cmp:0001", result.ComponentId);
        Assert.Equal(seat.OwnerId, result.RootDocumentId);
        seat.AssertReadOnly();
    }

    [Theory]
    [InlineData(0, "selection_empty")]
    [InlineData(2, "selection_multiple")]
    public void ExactlyOneSelectionAcrossAllMarksIsRequired(int count, string reason)
    {
        using var seat = new SelectionSeat();
        seat.Selection.Answer("GetSelectedObjectCount2", count);

        AssertUnresolved(seat.Capture(), reason);
        Assert.Contains(seat.Selection.Calls, call =>
            call.Member == "GetSelectedObjectCount2" && Equals(call.Arguments[0], -1));
        Assert.DoesNotContain("GetPersistReference3", seat.Root.Extension.Members);
        seat.AssertReadOnly();
    }

    [Fact]
    public void AnUnsupportedEdgeDoesNotBecomeAComponentPrefill()
    {
        using var seat = new SelectionSeat();
        seat.Selection.Answer("GetSelectedObject6", new InteropRecorder<IEdge>().Instance);

        AssertUnresolved(seat.Capture(), "selection_unsupported");
        seat.AssertReadOnly();
    }

    [Theory]
    [InlineData(true, "root_dirty")]
    [InlineData(false, "owner_dirty")]
    public void DirtyRootOrOwnerIsObservedAndRefused(bool root, string reason)
    {
        using var seat = new SelectionSeat();
        (root ? seat.Root : seat.Owner).Document.Answer("GetSaveFlag", true);

        EngineeringSelectionObservation result = seat.Capture();

        AssertUnresolved(result, reason);
        Assert.True(root ? result.RootDirty : result.OwnerDirty);
        seat.AssertReadOnly();
    }

    [Theory]
    [InlineData(true, "root_dirty_unreliable")]
    [InlineData(false, "owner_dirty_unreliable")]
    public void ReadOnlyDiscardPreferenceMakesAFalseSaveFlagUnreliable(bool root, string reason)
    {
        using var seat = new SelectionSeat();
        (root ? seat.Root : seat.Owner).Document.Answer("IsOpenedReadOnly", true);
        seat.Application.Answer("GetUserPreferenceToggle", true);

        EngineeringSelectionObservation result = seat.Capture();

        AssertUnresolved(result, reason);
        Assert.False(root ? result.RootDirtyReliable : result.OwnerDirtyReliable);
        Assert.Contains(seat.Application.Calls, call =>
            call.Member == "GetUserPreferenceToggle" && Equals(call.Arguments[0], 15));
        seat.AssertReadOnly();
    }

    [Fact]
    public void AnUnreadableDirtyFlagRemainsUnknown()
    {
        using var seat = new SelectionSeat();
        seat.Root.Document.Fail("GetSaveFlag", new InvalidOperationException("private path"));

        EngineeringSelectionObservation result = seat.Capture();

        AssertUnresolved(result, "native_read_failed");
        Assert.Null(result.RootDirty);
        Assert.False(result.RootDirtyReliable);
        Assert.DoesNotContain("private path", JsonSerializer.Serialize(result));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(4)]
    [InlineData(5)]
    public void SuppressedLightweightOrUnknownOccurrencesAreNeverResolved(int state)
    {
        using var seat = new SelectionSeat();
        seat.Component.Answer("GetSuppression2", state);

        AssertUnresolved(seat.Capture(), "occurrence_unavailable");
        Assert.DoesNotContain("GetModelDoc2", seat.Component.Members);
        seat.AssertReadOnly();
    }

    [Fact]
    public void AnUnloadedOwnerIsNotOpened()
    {
        using var seat = new SelectionSeat();
        seat.Component.Answer("GetModelDoc2", null);

        AssertUnresolved(seat.Capture(), "owner_unavailable");
        seat.AssertReadOnly();
    }

    [Fact]
    public void AChangedOccurrenceConfigurationDoesNotMatchTheSavedComponent()
    {
        using var seat = new SelectionSeat();
        seat.Component.Answer("get_ReferencedConfiguration", "Other");

        AssertUnresolved(seat.Capture(), "occurrence_not_in_package");
    }

    [Fact]
    public void AFaceReadInTheWrongActiveOwnerConfigurationIsUnresolved()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        seat.Owner.ActiveConfiguration.Answer("get_Name", "Other");

        AssertUnresolved(seat.Capture(), "owner_configuration_mismatch");
    }

    [Fact]
    public void ARepeatedPartCannotBeMatchedToAnotherOccurrenceWithTheSamePartReference()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        seat.Package.Components[1].FullPath = "bracket-2";
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "occurrence_not_in_package");
    }

    [Fact]
    public void NativeComponentIdentityMismatchCannotFallBackToItsName()
    {
        using var seat = new SelectionSeat();
        seat.Root.Extension.Answer("IsSamePersistentID", 0);

        AssertUnresolved(seat.Capture(), "occurrence_not_in_package");
    }

    [Fact]
    public void DuplicateSavedNativeMatchesRemainAmbiguous()
    {
        using var seat = new SelectionSeat();
        seat.Package.Components.Add(new ComponentInstance
        {
            Id = "cmp:0003", Name = "duplicate", FullPath = "bracket-1", DocumentId = seat.OwnerId,
            ReferencedConfiguration = "Default", PersistRefScope = seat.RootId,
            PersistRef = SelectionSeat.ComponentSaved, ParentId = "cmp:0001",
        });
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "occurrence_ambiguous");
    }

    [Fact]
    public void APositiveMatchWithAnUncertainNativeCompetitorCannotEstablishUniqueness()
    {
        using var seat = new SelectionSeat();
        seat.Package.Components.Add(new ComponentInstance
        {
            Id = "cmp:0003", Name = "duplicate", FullPath = "bracket-1", DocumentId = seat.OwnerId,
            ReferencedConfiguration = "Default", PersistRefScope = seat.RootId,
            PersistRef = Convert.ToBase64String(new byte[] { 11 }), ParentId = "cmp:0001",
        });
        seat.Root.Extension.Handle("IsSamePersistentID", arguments => ((byte[])arguments[0]!)[0] == 10 ? 1 : -1);
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "identity_comparison_unresolved");
    }

    [Fact]
    public void APositiveMatchWithAMissingReferenceCompetitorCannotEstablishUniqueness()
    {
        using var seat = new SelectionSeat();
        seat.Package.Components.Add(new ComponentInstance
        {
            Id = "cmp:0003", Name = "duplicate", FullPath = "bracket-1", DocumentId = seat.OwnerId,
            ReferencedConfiguration = "Default", PersistRefScope = seat.RootId,
            PersistRef = string.Empty, ParentId = "cmp:0001",
        });
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "identity_reference_missing");
    }

    [Fact]
    public void APositiveFaceWithAnUncertainNativeCompetitorCannotEstablishUniqueness()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        seat.Package.Faces.Add(new FaceGeometry
        {
            Id = "face:0002", ComponentId = "cmp:0002", PersistRefScope = seat.OwnerId,
            PersistRef = Convert.ToBase64String(new byte[] { 21 }),
        });
        seat.Owner.Extension.Handle("IsSamePersistentID", arguments => ((byte[])arguments[0]!)[0] == 20 ? 1 : -1);
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "identity_comparison_unresolved");
    }

    [Fact]
    public void AResolvedLeafInsideALightweightParentIsNotResolvedToAnswer()
    {
        using var seat = new SelectionSeat();
        var parent = new InteropRecorder<Component2>().Answer("GetSuppression2", 1);
        seat.Component.Answer("GetParent", parent.Instance);

        AssertUnresolved(seat.Capture(), "ancestor_unavailable");
        seat.AssertReadOnly();
    }

    [Fact]
    public void AnAncestorCycleDoesNotHangOrCreateAnOccurrence()
    {
        using var seat = new SelectionSeat();
        var parent = new InteropRecorder<Component2>().Answer("GetSuppression2", 2)
            .Answer("get_Name2", "sub-1").Answer("GetPathName", SelectionSeat.RootPath)
            .Answer("get_ReferencedConfiguration", "Default");
        parent.Answer("GetParent", parent.Instance);
        seat.Component.Answer("GetParent", parent.Instance);

        AssertUnresolved(seat.Capture(), "ancestor_cycle");
    }

    [Fact]
    public void ASelectedFaceMissingFromSavedEvidenceDoesNotInventAnId()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        seat.Package.Faces.Clear();
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "face_not_in_package");
    }

    [Fact]
    public void MappedFaceReferenceMismatchIsNotMatchedBySurfaceGeometry()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        seat.Owner.Extension.Answer("IsSamePersistentID", 0);

        AssertUnresolved(seat.Capture(), "face_not_in_package");
    }

    [Fact]
    public void AChangedRootConfigurationDuringCaptureInvalidatesThePrefill()
    {
        using var seat = new SelectionSeat();
        int reads = 0;
        seat.Root.ActiveConfiguration.Handle("get_Name", _ => ++reads == 1 ? "Default" : "Other");

        AssertUnresolved(seat.Capture(), "root_state_changed");
    }

    [Fact]
    public void AnActiveDocumentSwitchDuringCaptureInvalidatesThePrefill()
    {
        using var seat = new SelectionSeat();
        int reads = 0;
        seat.Application.Handle("get_ActiveDoc", _ => ++reads == 1 ? seat.Root.Instance : seat.Owner.Instance);

        AssertUnresolved(seat.Capture(), "active_document_changed");
    }

    [Fact]
    public void AChangedSelectionDuringCaptureInvalidatesThePrefill()
    {
        using var seat = new SelectionSeat();
        int reads = 0;
        seat.Selection.Handle("GetSelectedObject6", _ => ++reads == 1 ? seat.Component.Instance : seat.AssemblyFace.Instance);

        AssertUnresolved(seat.Capture(), "selection_changed");
    }

    [Fact]
    public void AChangedRootTransformDoesNotPrefillASavedForceFrame()
    {
        using var seat = new SelectionSeat();
        var transform = SwTransform.FromArrayData(SelectionSeat.IdentityArray);
        transform[0][3] = 5.0;
        seat.Package.Components[1].Transform = transform;
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "occurrence_transform_mismatch");
    }

    [Fact]
    public void ADirtyRootAfterTheReadIsReportedRatherThanItsEarlierCleanValue()
    {
        using var seat = new SelectionSeat();
        int reads = 0;
        seat.Root.Document.Handle("GetSaveFlag", _ => ++reads > 1);

        EngineeringSelectionObservation result = seat.Capture();

        AssertUnresolved(result, "root_state_changed");
        Assert.True(result.RootDirty);
    }

    [Fact]
    public void ADirtyOwnerAfterTheReadIsReportedRatherThanItsEarlierCleanValue()
    {
        using var seat = new SelectionSeat();
        int reads = 0;
        seat.Owner.Document.Handle("GetSaveFlag", _ => ++reads > 1);

        EngineeringSelectionObservation result = seat.Capture();

        AssertUnresolved(result, "owner_state_changed");
        Assert.True(result.OwnerDirty);
    }

    [Fact]
    public void AnAssemblyFaceWhoseOccurrenceChangesCannotKeepItsOriginalPrefill()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        int reads = 0;
        var other = new InteropRecorder<IComponent2>();
        seat.AssemblyFace.Handle("GetComponent", _ => ++reads == 1 ? seat.Component.Instance : other.Instance);

        AssertUnresolved(seat.Capture(), "occurrence_state_changed");
    }

    [Fact]
    public void ACurrentSelectionManagerIsUsedForTheFinalSelectionCheck()
    {
        using var seat = new SelectionSeat();
        var other = new InteropRecorder<ISelectionMgr>().Answer("GetSelectedObjectCount2", 0);
        int reads = 0;
        seat.Root.Document.Handle("get_SelectionManager", _ => ++reads == 1 ? seat.Selection.Instance : other.Instance);

        AssertUnresolved(seat.Capture(), "selection_changed");
    }

    [Fact]
    public void APackageThatChangesDuringNativeObservationInvalidatesItsPrefill()
    {
        using var seat = new SelectionSeat();
        seat.Root.Extension.Handle("IsSamePersistentID", _ =>
        {
            File.AppendAllText(Path.Combine(seat.Folder, "package.json"), "\n");
            return 1;
        });

        AssertUnresolved(seat.Capture(), "package_changed");
    }

    [Fact]
    public void DuplicateSavedFaceIdentityIsUnresolved()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        seat.Package.Faces.Add(new FaceGeometry
        {
            Id = "face:0002", ComponentId = "cmp:0002", PersistRefScope = seat.OwnerId,
            PersistRef = SelectionSeat.FaceSaved,
        });
        seat.SavePackage();

        AssertUnresolved(seat.Capture(), "face_ambiguous");
    }

    [Fact]
    public void AFaceThatCannotMapToItsPartIsNotReinterpretedInAssemblyScope()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        seat.Owner.Extension.Answer("GetCorrespondingEntity2", null);

        AssertUnresolved(seat.Capture(), "face_mapping_unavailable");
    }

    [Fact]
    public void CandidateBoundsRefuseTheWholeIdentitySearchInsteadOfReturningAnEarlyMatch()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();
        for (int id = 2; id <= 257; id++)
        {
            seat.Package.Faces.Add(new FaceGeometry
            {
                Id = "face:" + id.ToString("D4"), ComponentId = "cmp:0002",
                PersistRefScope = seat.OwnerId, PersistRef = SelectionSeat.FaceSaved,
            });
        }

        seat.SavePackage();
        AssertUnresolved(seat.Capture(), "identity_candidates_truncated");
        Assert.DoesNotContain("IsSamePersistentID", seat.Owner.Extension.Members);
    }

    [Fact]
    public void AStaleExpectedPackageDigestIsRefusedBeforeAnyNativeRead()
    {
        using var seat = new SelectionSeat();

        AssertUnresolved(seat.Capture(new string('0', 64)), "package_digest_mismatch");
        Assert.Empty(seat.Application.Calls);
    }

    [Fact]
    public void NativeReferenceBytesAndSourcePathsNeverLeaveTheAdapter()
    {
        using var seat = new SelectionSeat();
        seat.SelectFace();

        string json = JsonSerializer.Serialize(seat.Capture());

        Assert.DoesNotContain("persist_ref", json);
        Assert.DoesNotContain("C:\\", json);
        Assert.DoesNotContain("GetCorresponding", json);
        Assert.Contains("\"native_calibrated\":false", json);
        Assert.Contains("\"freshness\":\"cannot_establish\"", json);
    }

    [Fact]
    public void ANestedSelectionLabelShowsTheSavedOccurrenceChainDocumentAndConfiguration()
    {
        using var seat = new SelectionSeat();
        const string parentPath = "C:\\fictional\\subassembly.SLDASM";
        var parent = new InteropRecorder<Component2>().Answer("GetSuppression2", 2)
            .Answer("get_Name2", "subassembly-2").Answer("GetPathName", parentPath)
            .Answer("get_ReferencedConfiguration", "Default");
        seat.Component.Answer("GetParent", parent.Instance).Answer("get_Name2", "subassembly-2/bracket-1");
        seat.Package.Components[1].FullPath = "subassembly-2/bracket-1";
        seat.Package.Components[1].ParentId = "cmp:0003";
        seat.Package.Components.Add(new ComponentInstance
        {
            Id = "cmp:0003", Name = "subassembly-2", FullPath = "subassembly-2",
            DocumentId = DocumentIds.For(parentPath), ParentId = "cmp:0001",
            ReferencedConfiguration = "Default", PersistRefScope = seat.RootId,
            PersistRef = SelectionSeat.ComponentSaved,
        });
        seat.Package.Documents.Add(new Document
        {
            DocumentId = DocumentIds.For(parentPath), Path = parentPath, Kind = DocumentKind.Assembly,
            FileName = "subassembly.SLDASM", Configurations = new List<string> { "Default" },
            ActiveConfiguration = "Default",
        });
        seat.SavePackage();

        EngineeringSelectionObservation result = seat.Capture();

        Assert.Equal("matched_saved_target", result.Status);
        Assert.Contains("subassembly-2/bracket-1", result.DisplayName);
        Assert.Contains("bracket.SLDPRT", result.DisplayName);
        Assert.Contains("[Default]", result.DisplayName);
        Assert.DoesNotContain("fictional", result.DisplayName);
    }

    [Theory]
    [InlineData("C:\\private\\secret.SLDPRT")]
    [InlineData("\\\\private\\share\\secret.SLDPRT")]
    [InlineData("/private/secret.SLDPRT")]
    [InlineData("persist_ref:YWJj")]
    [InlineData("subassembly-1/native_reference=YWJj")]
    public void SourceLookingOrNativeReferenceLikeOccurrenceLabelsAreOmitted(string untrusted)
    {
        using var seat = new SelectionSeat();
        seat.Component.Answer("get_Name2", untrusted);
        seat.Package.Components[1].FullPath = untrusted;
        seat.SavePackage();

        EngineeringSelectionObservation result = seat.Capture();

        Assert.Equal("matched_saved_target", result.Status);
        Assert.DoesNotContain("private", result.DisplayName);
        Assert.DoesNotContain("YWJj", result.DisplayName);
        Assert.Contains("bracket.SLDPRT", result.DisplayName);
    }

    private static void AssertUnresolved(EngineeringSelectionObservation result, string reason)
    {
        Assert.Equal("unresolved", result.Status);
        Assert.Contains(reason, result.ReasonCodes);
        Assert.Null(result.EntityId);
        Assert.Null(result.ComponentId);
        Assert.False(result.NativeCalibrated);
        Assert.Equal("cannot_establish", result.Freshness);
    }

    private sealed class ApplicationThread : IApplicationThread
    {
        public int Invocations { get; private set; }

        public T Invoke<T>(Func<T> work)
        {
            Invocations++;
            return work();
        }
    }

    private sealed class SelectionSeat : IDisposable
    {
        internal const string RootPath = "C:\\fictional\\assembly.SLDASM";
        internal const string OwnerPath = "C:\\fictional\\bracket.SLDPRT";
        internal static readonly string ComponentSaved = Convert.ToBase64String(new byte[] { 10 });
        internal static readonly string FaceSaved = Convert.ToBase64String(new byte[] { 20 });
        internal static readonly double[] IdentityArray = { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 };

        internal SelectionSeat()
        {
            Directory.CreateDirectory(Folder);
            Root.Document.Answer("GetType", 2).Answer("GetPathName", RootPath)
                .Answer("GetSaveFlag", false).Answer("IsOpenedReadOnly", false)
                .Answer("get_SelectionManager", Selection.Instance);
            Owner.Document.Answer("GetType", 1).Answer("GetPathName", OwnerPath)
                .Answer("GetSaveFlag", false).Answer("IsOpenedReadOnly", false);
            Root.ActiveConfiguration.Answer("get_Name", "Default");
            Owner.ActiveConfiguration.Answer("get_Name", "Default");
            Application.Answer("get_ActiveDoc", Root.Instance).Answer("GetUserPreferenceToggle", false);
            Component.Answer("GetSuppression2", 2).Answer("get_Name2", "bracket-1")
                .Answer("GetPathName", OwnerPath).Answer("get_ReferencedConfiguration", "Default")
                .Answer("GetModelDoc2", Owner.Instance).Answer("get_Transform2", Transform.Instance);
            Transform.Answer("get_ArrayData", IdentityArray);
            Selection.Answer("GetSelectedObjectCount2", 1).Answer("GetSelectedObject6", Component.Instance);
            Root.Extension.Answer("GetPersistReference3", new byte[] { 90 }).Answer("IsSamePersistentID", 1);
            Owner.Extension.Answer("GetCorrespondingEntity2", PartFace.Instance)
                .Answer("GetPersistReference3", new byte[] { 91 }).Answer("IsSamePersistentID", 1);
            AssemblyFace.Answer("GetComponent", Component.Instance);
            Package.PackageId = Guid.NewGuid();
            Package.Design.RootAssemblyDocumentId = RootId;
            Package.Design.ActiveConfiguration = "Default";
            Package.Documents.Add(Document(RootPath, DocumentKind.Assembly));
            Package.Documents.Add(Document(OwnerPath, DocumentKind.Part));
            Package.Components.Add(new ComponentInstance
            {
                Id = "cmp:0001", Name = "assembly", DocumentId = RootId, PersistRefScope = RootId,
                PersistRef = ComponentSaved, ReferencedConfiguration = "Default",
            });
            Package.Components.Add(new ComponentInstance
            {
                Id = "cmp:0002", Name = "bracket-1", FullPath = "bracket-1", DocumentId = OwnerId,
                PersistRefScope = RootId, PersistRef = ComponentSaved, ParentId = "cmp:0001",
                ReferencedConfiguration = "Default",
            });
            Package.Faces.Add(new FaceGeometry
            {
                Id = "face:0001", ComponentId = "cmp:0002", PersistRefScope = OwnerId,
                PersistRef = FaceSaved,
            });
            SavePackage();
        }

        internal string Folder { get; } = Path.Combine(Path.GetTempPath(), "engineering-selection-" + Guid.NewGuid().ToString("N"));
        internal string RootId => DocumentIds.For(RootPath);
        internal string OwnerId => DocumentIds.For(OwnerPath);
        internal string Digest { get; private set; } = string.Empty;
        internal EvidencePackage Package { get; } = new EvidencePackage();
        internal InteropRecorder<ISldWorks> Application { get; } = new InteropRecorder<ISldWorks>();
        internal StandInDocument Root { get; } = new StandInDocument(false);
        internal StandInDocument Owner { get; } = new StandInDocument();
        internal InteropRecorder<IComponent2> Component { get; } = new InteropRecorder<IComponent2>();
        internal InteropRecorder<ISelectionMgr> Selection { get; } = new InteropRecorder<ISelectionMgr>();
        internal InteropRecorder<MathTransform> Transform { get; } = new InteropRecorder<MathTransform>();
        internal InteropRecorder<IFace2> AssemblyFace { get; } = new InteropRecorder<IFace2>(typeof(IEntity));
        internal InteropRecorder<IFace2> PartFace { get; } = new InteropRecorder<IFace2>(typeof(IEntity));
        internal ApplicationThread Thread { get; } = new ApplicationThread();

        internal EngineeringSelectionObservation Capture(string? digest = null) =>
            new SwEngineeringSelectionCapture(Application.Instance, Thread).Capture(Folder, digest ?? Digest);

        internal void SavePackage()
        {
            byte[] bytes = Encoding.UTF8.GetBytes(PackageSerializer.Serialize(Package));
            File.WriteAllBytes(Path.Combine(Folder, "package.json"), bytes);
            using var sha = SHA256.Create();
            Digest = string.Concat(sha.ComputeHash(bytes).Select(value => value.ToString("x2")));
        }

        internal void SelectFace() => Selection.Answer("GetSelectedObject6", AssemblyFace.Instance);

        internal void SelectPartFace()
        {
            Application.Answer("get_ActiveDoc", Owner.Instance);
            Owner.Document.Answer("get_SelectionManager", Selection.Instance);
            Selection.Answer("GetSelectedObject6", PartFace.Instance);
            Package.Design.RootAssemblyDocumentId = OwnerId;
            Package.Documents.RemoveAt(0);
            Package.Components.RemoveAt(1);
            Package.Components[0].DocumentId = OwnerId;
            Package.Components[0].PersistRefScope = OwnerId;
            Package.Faces[0].ComponentId = "cmp:0001";
            SavePackage();
        }

        internal void AssertReadOnly()
        {
            IEnumerable<string> calls = Application.Members.Concat(Root.AllMembers())
                .Concat(Owner.AllMembers()).Concat(Selection.Members).Concat(Component.Members)
                .Concat(AssemblyFace.Members).Concat(PartFace.Members).Concat(Transform.Members);
            Assert.DoesNotContain(calls, member => member.Contains("Select4") || member.Contains("Select2")
                || member.Contains("ClearSelection") || member.Contains("SelectByID")
                || member.Contains("OpenDoc") || member.Contains("ActivateDoc")
                || member.Contains("Rebuild") || member.Contains("Save3") || member.StartsWith("set_"));
        }

        private static Document Document(string path, DocumentKind kind) => new Document
        {
            DocumentId = DocumentIds.For(path), Path = path, FileName = Path.GetFileName(path),
            Kind = kind, Configurations = new List<string> { "Default" }, ActiveConfiguration = "Default",
        };

        public void Dispose() => Directory.Delete(Folder, true);
    }
}
