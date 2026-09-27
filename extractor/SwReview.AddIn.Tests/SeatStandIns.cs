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
