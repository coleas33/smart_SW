using System;
using System.Collections.Generic;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Tests;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Recording stand-ins for the SOLIDWORKS objects the seat adapter (feature 004, build order lane
/// B) reaches, wired the way a real part answers: the document is an <c>IModelDoc2</c> and, when it
/// is a part, an <c>IPartDoc</c>; its extension, feature manager and document-level custom property
/// manager are objects of their own. Each is an <see cref="InteropRecorder{TInterface}"/>, so a test
/// states what SOLIDWORKS answers and asserts exactly which members were called with what. No COM
/// object exists and SOLIDWORKS is never started.
/// </summary>
internal sealed class StandInDocument
{
    public StandInDocument(bool isPart = true)
    {
        Document = isPart ? new InteropRecorder<ModelDoc2>(typeof(IPartDoc)) : new InteropRecorder<ModelDoc2>();
        Document
            .Answer("get_Extension", Extension.Instance)
            .Answer("get_FeatureManager", Manager.Instance)
            .Answer("get_ConfigurationManager", Configurations.Instance);
        Extension.Answer("get_CustomPropertyManager", Properties.Instance);
        Configurations.Answer("get_ActiveConfiguration", ActiveConfiguration.Instance);
    }

    public InteropRecorder<ModelDoc2> Document { get; }

    public InteropRecorder<ModelDocExtension> Extension { get; } = new InteropRecorder<ModelDocExtension>();

    public InteropRecorder<FeatureManager> Manager { get; } = new InteropRecorder<FeatureManager>();

    public InteropRecorder<CustomPropertyManager> Properties { get; } = new InteropRecorder<CustomPropertyManager>();

    public InteropRecorder<ConfigurationManager> Configurations { get; } = new InteropRecorder<ConfigurationManager>();

    public InteropRecorder<Configuration> ActiveConfiguration { get; } = new InteropRecorder<Configuration>();

    /// <summary>The document, as the adapter is handed it.</summary>
    public ModelDoc2 Instance => Document.Instance;

    /// <summary>
    /// <c>IFeatureManager.GetFeatures(ToplevelOnly)</c> answering <paramref name="topLevel"/> for
    /// <c>true</c> and <paramref name="all"/> for <c>false</c>, so a test can tell which walk read it.
    /// </summary>
    public StandInDocument WithFeatures(object? topLevel, object? all)
    {
        Manager.Handle("GetFeatures", arguments => (bool)arguments[0]! ? topLevel : all);
        return this;
    }

    /// <summary>The same features for both walks.</summary>
    public StandInDocument WithFeatures(params InteropRecorder<Feature>[] features) =>
        WithFeatures(Features(features), Features(features));

    /// <summary>
    /// <c>IModelDocExtension.GetPersistReference3(entity)</c> answering the bytes
    /// <paramref name="references"/> holds for that entity, and null for any other.
    /// </summary>
    public StandInDocument WithPersistReferences(IDictionary<object, byte[]> references)
    {
        Extension.Handle(
            "GetPersistReference3",
            arguments => arguments[0] != null && references.TryGetValue(arguments[0]!, out byte[]? bytes) ? bytes : null);
        return this;
    }

    /// <summary><c>IPartDoc.GetBodies2(BodyType, BVisibleOnly)</c> answering per body type, and null for any other.</summary>
    public StandInDocument WithBodies(IDictionary<int, object?> byType)
    {
        Document.Handle("GetBodies2", arguments => byType.TryGetValue((int)arguments[0]!, out object? bodies) ? bodies : null);
        return this;
    }

    /// <summary>The members called on every stand-in this document owns, each as <c>Interface.member</c>.</summary>
    public IReadOnlyList<string> AllMembers() =>
        Qualified("IModelDoc2", Document.Members)
            .Concat(Qualified("IModelDocExtension", Extension.Members))
            .Concat(Qualified("IFeatureManager", Manager.Members))
            .Concat(Qualified("ICustomPropertyManager", Properties.Members))
            .Concat(Qualified("IConfigurationManager", Configurations.Members))
            .Concat(Qualified("IConfiguration", ActiveConfiguration.Members))
            .ToList();

    public static object[] Features(params InteropRecorder<Feature>[] features) =>
        features.Select(feature => (object)feature.Instance).ToArray();

    public static InteropRecorder<Feature> Feature(string name, string typeName = "Extrusion") =>
        new InteropRecorder<Feature>().Answer("get_Name", name).Answer("GetTypeName2", typeName);

    private static IEnumerable<string> Qualified(string interfaceName, IEnumerable<string> members) =>
        members.Select(member => interfaceName + "." + member);
}

/// <summary>
/// SOLIDWORKS as the seat adapter meets it over a Plan and a Discard, played by recording stand-ins:
/// an application with the engineer's part open, and the byte copy of it the seat opens, both the
/// same two-feature part read the same way - so <c>remodel.open</c>'s step 12 finds them alike - and
/// the copy answering its tag, rollback, rebuild, units, equations and geometry.
///
/// The copy is whatever path the seat asked to open (<c>GetOpenDocSpec</c>), so the world serves any
/// run folder, the one a Remodel host makes included. Once it is open it can be activated by its
/// title (<c>ActivateDoc3</c>) and then read as the active document (<c>get_ActiveDoc</c>), which is
/// what the pane's activation before a dump asks (004 T159); until then the engineer's part is the
/// active document. No COM object exists and SOLIDWORKS is never started. Shared by
/// <see cref="RemodelSeatBridgeTests"/> and <see cref="RemodelPlanEndToEndTests"/>.
/// </summary>
internal sealed class StandInSolidworks
{
    public static readonly byte[] BossRef = { 1, 1, 1 };

    public static readonly byte[] CutRef = { 2, 2, 2 };

    /// <summary>What the source may be asked: the probe's reads and the accessors that reach them.</summary>
    public static readonly IReadOnlyCollection<string> SourceReads = new HashSet<string>(StringComparer.Ordinal)
    {
        "IModelDoc2.GetType", "IModelDoc2.GetSaveFlag", "IModelDoc2.ListExternalFileReferencesCount2",
        "IModelDoc2.GetBodies2", "IModelDoc2.IsWeldment", "IModelDoc2.get_FeatureManager", "IModelDoc2.GetConfigurationNames",
        "IModelDoc2.get_Extension", "IFeatureManager.GetSheetMetalFolder", "IFeatureManager.GetFeatures",
        "IModelDocExtension.GetPersistReference3",
    };

    private string? _requested;
    private object? _active;

    public StandInSolidworks(string sourcePath)
    {
        SourcePath = sourcePath ?? throw new ArgumentNullException(nameof(sourcePath));
        _active = Source.Instance;
        WireApplication();
        WirePart(Source);
        WirePart(Copy);
        WireCopy();
    }

    public string SourcePath { get; }

    /// <summary>The path the seat opened the copy at; null until it has.</summary>
    public string? CopyPath { get; private set; }

    /// <summary>Whether SOLIDWORKS has the copy open: from its <c>OpenDoc7</c> to its <c>CloseDoc</c>.</summary>
    public bool CopyOpen { get; private set; }

    /// <summary>The session tag on the copy, as <c>Add3</c> wrote it and <c>Delete2</c> took it off.</summary>
    public string? Tag { get; private set; }

    public InteropRecorder<ISldWorks> Application { get; } = new InteropRecorder<ISldWorks>();

    public InteropRecorder<IDocumentSpecification> Specification { get; } = new InteropRecorder<IDocumentSpecification>();

    public StandInDocument Source { get; } = new StandInDocument();

    public StandInDocument Copy { get; } = new StandInDocument();

    public InteropRecorder<Feature> Boss { get; } = StandInDocument.Feature("Boss-Extrude1");

    public InteropRecorder<Feature> Cut { get; } = StandInDocument.Feature("Cut-Extrude1");

    public InteropRecorder<EquationMgr> Equations { get; } = new InteropRecorder<EquationMgr>();

    public InteropRecorder<IMassProperty2> MassProperty { get; } = new InteropRecorder<IMassProperty2>();

    private static bool Same(string? path, string? other) =>
        path != null && other != null && string.Equals(path, other, StringComparison.OrdinalIgnoreCase);

    private void WireApplication()
    {
        Application
            .Handle("GetOpenDocumentByName", arguments =>
            {
                string path = (string)arguments[0]!;
                if (Same(path, SourcePath))
                {
                    return Source.Instance;
                }

                return CopyOpen && Same(path, CopyPath) ? Copy.Instance : null;
            })
            .Handle("GetOpenDocSpec", arguments =>
            {
                _requested = (string)arguments[0]!;
                return Specification.Instance;
            })
            .Handle("OpenDoc7", arguments =>
            {
                CopyPath = _requested;
                CopyOpen = true;
                return Copy.Instance;
            })
            .Handle("CloseDoc", arguments =>
            {
                CopyOpen = false;
                if (ReferenceEquals(_active, Copy.Instance))
                {
                    _active = Source.Instance;
                }

                return null;
            })
            .Handle("ActivateDoc3", arguments =>
            {
                if (!CopyOpen || CopyPath == null
                    || !string.Equals((string)arguments[0]!, System.IO.Path.GetFileName(CopyPath), StringComparison.OrdinalIgnoreCase))
                {
                    return null;
                }

                _active = Copy.Instance;
                return Copy.Instance;
            })
            .Handle("get_ActiveDoc", arguments => _active)
            .Answer("GetUserPreferenceToggle", true)
            .Answer("get_CommandInProgress", false);
    }

    /// <summary>The same part, read the same way, for the source and its byte copy: step 12 compares them.</summary>
    private void WirePart(StandInDocument part)
    {
        var body = new InteropRecorder<IBody2>().Answer("GetFaceCount", 6).Answer("GetEdgeCount", 12);
        part.Document
            .Answer("GetType", 1)
            .Answer("GetSaveFlag", false)
            .Answer("ListExternalFileReferencesCount2", 0)
            .Answer("IsWeldment", false)
            .Answer("GetConfigurationNames", new[] { "Default" });
        part.WithBodies(new Dictionary<int, object?> { [0] = new object[] { body.Instance }, [-1] = new object[] { body.Instance } });
        part.WithFeatures(Boss, Cut);
        part.WithPersistReferences(new Dictionary<object, byte[]> { [Boss.Instance] = BossRef, [Cut.Instance] = CutRef });
    }

    /// <summary>The copy's own answers: its path and title, the tag, the rollback, the rebuild, the units, the geometry.</summary>
    private void WireCopy()
    {
        Copy.Document
            .Handle("GetPathName", arguments => CopyPath)
            .Handle("GetTitle", arguments => CopyPath == null ? null : System.IO.Path.GetFileName(CopyPath))
            .Answer("ForceRebuild3", true)
            .Answer("GetUnits", new[] { 0, 0, 2, 3, 0 })
            .Answer("GetEquationMgr", Equations.Instance)
            .Answer("GetMaterialPropertyName2", "6061-T6");
        Copy.ActiveConfiguration.Answer("get_Name", "Default");
        Copy.Manager.Answer("EditRollback", true);
        Copy.Extension
            .Answer("GetWhatsWrongCount", 0)
            .Answer("CreateMassProperty2", MassProperty.Instance)
            .Handle("GetObjectByPersistReference3", arguments =>
            {
                var bytes = (byte[])arguments[0]!;
                arguments[1] = 0;
                return bytes.SequenceEqual(BossRef) ? Boss.Instance : bytes.SequenceEqual(CutRef) ? Cut.Instance : (object?)null;
            });
        Copy.Properties
            .Handle("Add3", arguments =>
            {
                Tag = (string)arguments[2]!;
                return 1;
            })
            .Handle("Get4", arguments =>
            {
                arguments[2] = Tag ?? string.Empty;
                arguments[3] = Tag ?? string.Empty;
                return Tag != null;
            })
            .Handle("Delete2", arguments =>
            {
                Tag = null;
                return 0;
            });
        Equations.Answer("GetCount", 1).Answer("get_Equation", "\"w\" = 120");
        MassProperty
            .Answer("Recalculate", true)
            .Answer("get_Volume", 0.000125)
            .Answer("get_SurfaceArea", 0.015)
            .Answer("get_CenterOfMass", new[] { 0.0, 0.0, 0.0025 })
            .Answer("get_PrincipalMomentsOfInertia", new[] { 1e-6, 2e-6, 3e-6 })
            .Answer("get_Mass", 0.3375)
            .Answer("get_Density", 2700.0);
    }
}
