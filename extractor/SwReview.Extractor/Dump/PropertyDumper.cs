using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T054. Custom properties, configurations, material and mass, per document.
///
/// Mass is read with <c>CreateMassProperty2</c> and <c>UseSystemUnits = true</c>, so it
/// arrives in kg and m3 with no conversion (research R12). A surface-only model returns
/// nothing, which becomes a null mass plus a Gap rather than a zero.
///
/// <c>GetOverrideOptions</c> is recorded as a Gap when an override is in force: an
/// overridden mass is a number an engineer typed, not one the geometry produced, and a
/// weight check must know the difference.
/// </summary>
public sealed class PropertyDumper : IDocumentSource
{
    private readonly ISwSession _session;
    private readonly ISldWorks _swApp;

    public PropertyDumper(ISwSession session, ISldWorks swApp)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
    }

    public IReadOnlyList<Document> Dump(DumpScope scope, IReadOnlyList<string> documentPaths)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        if (documentPaths == null)
        {
            throw new ArgumentNullException(nameof(documentPaths));
        }

        var documents = new List<Document>();

        foreach (string path in documentPaths)
        {
            string documentId = scope.DocumentId(path);

            Document? document = scope.Gaps.TryStep<Document>(
                "document", documentId, $"read '{Path.GetFileName(path)}'", () => Read(path, documentId, scope));

            if (document == null)
            {
                // A document that could not be read still has to exist in the package,
                // because every component points at one.
                documents.Add(Placeholder(path, documentId));
                continue;
            }

            documents.Add(document);
        }

        return documents;
    }

    private Document? Read(string path, string documentId, DumpScope scope)
    {
        SwGate gate = _session.Gate;

        var model = gate.Call("GetOpenDocumentByName", () => _swApp.GetOpenDocumentByName(path)) as IModelDoc2;
        if (model == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "document",
                documentId,
                $"'{Path.GetFileName(path)}' is not open in SOLIDWORKS, so its properties, material "
                + "and mass were not read.",
                null);
            return Placeholder(path, documentId);
        }

        string activeConfiguration =
            gate.Call("ActiveConfiguration.Name", () => model.ConfigurationManager?.ActiveConfiguration?.Name)
            ?? string.Empty;

        var document = new Document
        {
            DocumentId = documentId,
            Kind = SwSession.KindOf(model, gate),
            FileName = Path.GetFileName(path),
            Path = path,
            ActiveConfiguration = activeConfiguration,
            CustomProperties = ReadProperties(model, string.Empty, gate),
            Material = ReadMaterial(model, activeConfiguration, gate),
        };

        if (gate.Call("GetConfigurationNames", () => model.GetConfigurationNames()) is object[] names)
        {
            foreach (object name in names)
            {
                string? configuration = name as string;
                if (string.IsNullOrEmpty(configuration))
                {
                    continue;
                }

                document.Configurations.Add(configuration!);
                document.ConfigProperties[configuration!] = ReadProperties(model, configuration!, gate);
            }
        }

        document.Mass = ReadMass(model, activeConfiguration, documentId, scope, gate);
        return document;
    }

    /// <summary>
    /// <c>GetAll3</c> for one configuration, or the document level when
    /// <paramref name="configuration"/> is empty. Resolved values are preferred over the
    /// raw expression, because that is what a drawing or a BOM would show.
    /// </summary>
    public static Dictionary<string, string> ReadProperties(
        IModelDoc2 model, string configuration, SwGate gate)
    {
        var properties = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        var manager = gate.Call(
            "CustomPropertyManager",
            () => model.Extension.CustomPropertyManager[configuration ?? string.Empty]) as ICustomPropertyManager;

        if (manager == null)
        {
            return properties;
        }

        object? names = null;
        object? types = null;
        object? values = null;
        object? resolved = null;
        object? linked = null;

        gate.Call(
            "GetAll3",
            () => manager.GetAll3(ref names, ref types, ref values, ref resolved, ref linked));

        if (!(names is object[] nameArray))
        {
            return properties;
        }

        var valueArray = values as object[];
        var resolvedArray = resolved as object[];

        for (int i = 0; i < nameArray.Length; i++)
        {
            string? name = nameArray[i] as string;
            if (string.IsNullOrWhiteSpace(name))
            {
                continue;
            }

            string? value = At(resolvedArray, i) ?? At(valueArray, i);
            properties[name!] = value ?? string.Empty;
        }

        return properties;
    }

    /// <summary>The material of a part, or null for an assembly or an unassigned part.</summary>
    public static string? ReadMaterial(IModelDoc2 model, string configuration, SwGate gate)
    {
        if (!(model is IPartDoc part))
        {
            return null;
        }

        string database = string.Empty;
        string? material = gate.Call(
            "GetMaterialPropertyName2",
            () => part.GetMaterialPropertyName2(configuration ?? string.Empty, out database));

        return string.IsNullOrWhiteSpace(material) ? null : material!.Trim();
    }

    /// <summary>
    /// Mass in kg and volume in m3 through <c>CreateMassProperty2</c> with
    /// <c>UseSystemUnits</c>. Null plus a Gap for a surface-only model, and a Gap whenever
    /// the mass has been overridden.
    /// </summary>
    private static MassProperties? ReadMass(
        IModelDoc2 model, string configuration, string documentId, DumpScope scope, SwGate gate)
    {
        var mass = gate.Call("CreateMassProperty2", () => model.Extension.CreateMassProperty2())
            as IMassProperty2;

        if (mass == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "document",
                documentId,
                "CreateMassProperty2 returned nothing; mass and volume are unknown.",
                null);
            return null;
        }

        // UseSystemUnits must be set BEFORE Recalculate, or the numbers come back in the
        // document's display units (research R12).
        gate.Call("UseSystemUnits", () => mass.UseSystemUnits = true);

        if (!gate.Call("Recalculate", () => mass.Recalculate()))
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "document",
                documentId,
                "Mass properties could not be recalculated (a surface-only model has none); "
                + "mass and volume are unknown.",
                null);
            return null;
        }

        double volume = gate.Call("Volume", () => mass.Volume);
        if (volume <= 0)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "document",
                documentId,
                "The model has no solid volume (surface bodies only); mass and volume are unknown.",
                null);
            return null;
        }

        if (gate.Call("GetOverrideOptions", () => mass.GetOverrideOptions()) is int[] overrides)
        {
            foreach (int option in overrides)
            {
                if (option != 0)
                {
                    scope.Gaps.Add(
                        GapKind.Unsupported,
                        "document",
                        documentId,
                        "The mass properties are OVERRIDDEN in SOLIDWORKS; the values recorded were "
                        + "typed by a user, not computed from the geometry.",
                        null);
                    break;
                }
            }
        }

        var centre = gate.Call("CenterOfMass", () => mass.CenterOfMass) as double[];

        return new MassProperties
        {
            MassKg = gate.Call("Mass", () => mass.Mass),
            VolumeM3 = volume,
            CenterOfMass = centre != null && centre.Length >= 3
                ? new Vec3(centre[0], centre[1], centre[2])
                : new Vec3(0, 0, 0),
            Configuration = configuration,
        };
    }

    private static string? At(object[]? array, int index) =>
        array != null && index < array.Length ? array[index] as string : null;

    /// <summary>A document the extractor knows exists but could not open.</summary>
    private static Document Placeholder(string path, string documentId) => new Document
    {
        DocumentId = documentId,
        Kind = path.EndsWith(".sldasm", StringComparison.OrdinalIgnoreCase)
            ? DocumentKind.Assembly
            : path.EndsWith(".slddrw", StringComparison.OrdinalIgnoreCase)
                ? DocumentKind.Drawing
                : DocumentKind.Part,
        FileName = Path.GetFileName(path),
        Path = path,
        ActiveConfiguration = string.Empty,
        Material = null,
        Mass = null,
    };
}
