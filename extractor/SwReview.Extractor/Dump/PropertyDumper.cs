using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Guard;
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

        DocumentKind kind = SwSession.KindOf(model, gate);
        string fileName = Path.GetFileName(path);

        var document = new Document
        {
            DocumentId = documentId,
            Kind = kind,
            FileName = fileName,
            Path = path,
            ActiveConfiguration = activeConfiguration,
            CustomProperties = ReadProperties(model, string.Empty, gate),
            Material = ReadMaterial(model, activeConfiguration, gate),

            // Schema 1.4.0 (contracts/ir-additions.md section 1). The configuration costs no
            // interop call: ReadMaterial above already passed it to GetMaterialPropertyName2
            // and discarded it, and recording it is what tells "no material in configuration
            // X" from "no material, configuration unknown".
            MaterialConfiguration = MaterialConfiguration(kind, activeConfiguration),
            IsExploded = ReadIsExploded(
                kind, documentId, fileName, scope.Gaps, gate, () => model.IsExploded()),
            RebuildErrorCount = ReadRebuildErrorCount(
                documentId, fileName, scope.Gaps, gate, () => model.Extension.GetWhatsWrongCount()),
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

        // One CreateMassProperty2 call feeds the mass read and the override's fallback path, and
        // the override is answered FIRST, before ReadMass's volume gates: a surface-only part
        // returns no mass properties, and standards.part.material_assigned would otherwise be
        // unresolved for every one of them (contracts/ir-additions.md section 1). The override
        // is read through the interface that has it (feature 010 T069): CreateMassProperty()'s
        // MassProperty first, then GetOverrideOptions() on the IMassProperty2 below.
        object? massProperty = gate.Call("CreateMassProperty2", () => model.Extension.CreateMassProperty2());

        document.MassOverridden = ReadMassOverridden(
            () => model.Extension.CreateMassProperty(),
            property => ((IMassProperty)property).OverrideMass,
            massProperty,
            property => ((IMassPropertyOverrideOptions)((IMassProperty2)property).GetOverrideOptions()).OverrideMass,
            documentId,
            fileName,
            scope.Gaps,
            gate);

        document.Mass = ReadMass(massProperty, activeConfiguration, documentId, scope, gate);
        return document;
    }

    /// <summary>
    /// <c>IModelDoc2.IsExploded()</c> for an ASSEMBLY document (schema 1.4.0). A part and a
    /// drawing have no exploded state, so their null is silent rather than a gap: the question
    /// does not apply, and naming it would put a coverage row on every part in the package.
    /// Null plus an <c>assembly_exploded</c> gap when the read threw.
    ///
    /// The interop expression stays at the call site and the policy lives here, because this
    /// dumper holds an <c>ISldWorks</c> and an <c>IModelDoc2</c> that no machine without a
    /// seat can produce - the same split <see cref="FeatureDumper"/> makes with
    /// <see cref="IFeatureReader"/>, one delegate wide instead of one interface wide.
    /// </summary>
    public static bool? ReadIsExploded(
        DocumentKind kind,
        string documentId,
        string fileName,
        GapCollector gaps,
        SwGate gate,
        Func<bool> read)
    {
        if (kind != DocumentKind.Assembly)
        {
            return null;
        }

        return Read("assembly_exploded", "IsExploded", documentId, fileName, gaps, gate, read);
    }

    /// <summary>
    /// <c>IModelDocExtension.GetWhatsWrongCount</c> <b>as the document stands</b>: nothing is
    /// rebuilt to refresh it, which is difference g. Null plus a <c>rebuild_error_count</c>
    /// gap when the read threw, never a zero - a zero is "this document rebuilds clean".
    /// </summary>
    public static int? ReadRebuildErrorCount(
        string documentId, string fileName, GapCollector gaps, SwGate gate, Func<int> read) =>
        Read("rebuild_error_count", "GetWhatsWrongCount", documentId, fileName, gaps, gate, read);

    /// <summary>
    /// The one-object form of the override read: <paramref name="read"/> over an object already
    /// in hand, null plus a <c>mass_override</c> gap when the object is missing or the read
    /// fails, so a failure is unknown rather than false (schema 1.4.0).
    ///
    /// <c>Read</c> no longer calls it: its 1.4.0 caller cast <c>CreateMassProperty2</c>'s
    /// object to <c>IMassProperty</c>, which raised on every recorded document, and the
    /// two-path overload below replaced that call site (feature 010 T069). It keeps its
    /// signature and its tests, which pin the one-path policy the two-path read extends.
    /// </summary>
    public static bool? ReadMassOverridden(
        object? massProperty,
        string documentId,
        string fileName,
        GapCollector gaps,
        SwGate gate,
        Func<object, bool> read)
    {
        if (massProperty == null)
        {
            gaps.Add(
                GapKind.NotExtracted,
                "mass_override",
                documentId,
                $"CreateMassProperty2 returned nothing for '{fileName}', so whether its mass "
                + "was overridden is unknown.",
                null);
            return null;
        }

        object property = massProperty;
        return Read(
            "mass_override", "OverrideMass", documentId, fileName, gaps, gate, () => read(property));
    }

    /// <summary>
    /// The override, read through the interface that has it (feature 010 T069,
    /// contracts/mass-material.md section 4). The one-object read above cast
    /// <c>CreateMassProperty2</c>'s object to <c>IMassProperty</c>, which raised on every
    /// document of both recorded assemblies: in the 2024 SP5 interop
    /// <c>IMassProperty2</c> declares no <c>OverrideMass</c> and no base interface.
    ///
    /// Two paths, in this order:
    ///   1. <c>IModelDocExtension.CreateMassProperty()</c>, which returns <c>MassProperty</c>
    ///      (it implements <c>IMassProperty</c>), and its <c>OverrideMass</c>;
    ///   2. when that fails, <c>IMassProperty2.GetOverrideOptions()</c> on the object
    ///      <c>CreateMassProperty2</c> already returned for the mass read, whose
    ///      <c>IMassPropertyOverrideOptions</c> has an <c>OverrideMass</c> of its own. Gated as
    ///      the one member <c>GetOverrideOptions</c>: the options object is read in the same
    ///      breath and has no other use.
    ///
    /// The first answer is kept, <c>false</c> included. When neither path answers, the result
    /// is null plus ONE <c>mass_override</c> gap naming both paths and both errors, so the
    /// seat run (T103) can tell which path failed how; which path answered on a seat shows in
    /// the gate log's member set. A guard refusal or an open circuit is never taken for a
    /// failed path: both propagate, as they do from <see cref="GapCollector.TryStep"/>.
    /// </summary>
    public static bool? ReadMassOverridden(
        Func<object?> createMassProperty,
        Func<object, bool> readOverrideMass,
        object? massProperty2,
        Func<object, bool> readOverrideOptions,
        string documentId,
        string fileName,
        GapCollector gaps,
        SwGate gate)
    {
        if (createMassProperty == null)
        {
            throw new ArgumentNullException(nameof(createMassProperty));
        }

        if (readOverrideMass == null)
        {
            throw new ArgumentNullException(nameof(readOverrideMass));
        }

        if (readOverrideOptions == null)
        {
            throw new ArgumentNullException(nameof(readOverrideOptions));
        }

        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        OverridePath first = TryOverridePath(() =>
        {
            object? property = gate.Call("CreateMassProperty", createMassProperty);
            return property == null
                ? OverridePath.Nothing("CreateMassProperty returned nothing")
                : OverridePath.Answer(gate.Call("OverrideMass", () => readOverrideMass(property)));
        });

        if (first.Value != null)
        {
            return first.Value;
        }

        OverridePath second = massProperty2 == null
            ? OverridePath.Nothing("CreateMassProperty2 returned nothing")
            : TryOverridePath(() =>
                OverridePath.Answer(gate.Call("GetOverrideOptions", () => readOverrideOptions(massProperty2))));

        if (second.Value != null)
        {
            return second.Value;
        }

        bool threw = first.Error != null || second.Error != null;
        gaps.Add(
            threw ? GapKind.ToolError : GapKind.NotExtracted,
            "mass_override",
            documentId,
            $"Whether the mass of '{fileName}' is overridden is unknown: "
            + $"CreateMassProperty().OverrideMass (IMassProperty) - {first.Describe()}; "
            + $"CreateMassProperty2().GetOverrideOptions().OverrideMass "
            + $"(IMassPropertyOverrideOptions) - {second.Describe()}.",
            threw ? $"CreateMassProperty: {first.Error ?? "no error"}; "
                + $"GetOverrideOptions: {second.Error ?? "no error"}" : null);
        return null;
    }

    /// <summary>What one override path came back with: an answer, nothing, or an error.</summary>
    private sealed class OverridePath
    {
        private OverridePath(bool? value, string? nothing, string? error)
        {
            Value = value;
            NothingReason = nothing;
            Error = error;
        }

        public bool? Value { get; }

        public string? NothingReason { get; }

        /// <summary>The exception as <see cref="GapCollector"/> describes one, or null.</summary>
        public string? Error { get; }

        public static OverridePath Answer(bool value) => new OverridePath(value, null, null);

        public static OverridePath Nothing(string reason) => new OverridePath(null, reason, null);

        public static OverridePath Failed(Exception error) =>
            new OverridePath(null, null, GapCollector.Describe(error));

        public string Describe() => NothingReason ?? "failed with " + Error;
    }

    /// <summary>
    /// Runs one override path. Every failure is the path's, except the two that are not a
    /// property of the model: a guard refusal and an open circuit.
    /// </summary>
    private static OverridePath TryOverridePath(Func<OverridePath> path)
    {
        try
        {
            return path();
        }
        catch (CircuitOpenError)
        {
            throw;
        }
        catch (MutatingCallError)
        {
            throw;
        }
        catch (Exception ex)
        {
            return OverridePath.Failed(ex);
        }
    }

    /// <summary>
    /// The configuration the material read was attempted in, or null for a document that has
    /// no material to read (schema 1.4.0). It is recorded even when the material itself came
    /// back null, because "no material in configuration X" and "no material, configuration
    /// unknown" are different facts - which is why this helper is not told what
    /// <see cref="ReadMaterial"/> gave.
    /// </summary>
    public static string? MaterialConfiguration(DocumentKind kind, string configuration) =>
        kind == DocumentKind.Part ? configuration : null;

    /// <summary>One gated read of one document, null plus a gap when it threw.</summary>
    private static T? Read<T>(
        string entityKind,
        string member,
        string documentId,
        string fileName,
        GapCollector gaps,
        SwGate gate,
        Func<T> read)
        where T : struct
    {
        T? value = null;
        gaps.TryStep(
            entityKind,
            documentId,
            $"read {member} for '{fileName}'",
            () => { value = gate.Call(member, read); });

        return value;
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
        object? massProperty, string configuration, string documentId, DumpScope scope, SwGate gate)
    {
        // CreateMassProperty2 is called once, by Read, and its object feeds both the override
        // read and this one; the gap below is unchanged, so the gap set of an existing dump
        // does not move on this account (contracts/ir-additions.md, additivity rule point 5).
        var mass = massProperty as IMassProperty2;

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
