using System;
using System.Collections.Generic;
using System.Globalization;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// The reads <see cref="HoleDumper"/> makes of one Hole Wizard definition
/// (<c>IWizardHoleFeatureData2</c>), with no interop type in the signature
/// (<see cref="SwHoleWizardReader"/> is the SOLIDWORKS one). The seam exists so what becomes a
/// field, a null and a gap is unit tested with no seat (feature 010 T088, research R2.24).
///
/// Every member is one interop read the dumper gates under the member's own name, so the guard
/// and the gate log see the production names even under a fake. Two exceptions, both because
/// the answer needs <c>swconst</c> enumeration names the test assembly cannot load:
/// <see cref="HoleType"/> classifies <c>Type</c> by its <c>swWzdHoleTypes_e</c> member name
/// (the dumper gates it as <c>WizardHole.Type</c>), and <see cref="Standard"/> spans
/// <c>Standard2</c> and the free-text <c>Standard</c> and gates both itself. Lengths are metres
/// and the angle radians, exactly as SOLIDWORKS reports them.
/// </summary>
public interface IHoleWizardReader
{
    /// <summary><c>Type</c>, classified by its <c>swWzdHoleTypes_e</c> member name.</summary>
    HoleType HoleType { get; }

    /// <summary><c>EndCondition</c> verbatim (<c>swEndConditions_e</c>).</summary>
    int EndCondition { get; }

    /// <summary><c>Standard2</c>'s name, or the free-text <c>Standard</c> for -1; gated inside.</summary>
    string? Standard { get; }

    string? FastenerSize { get; }

    double HoleDepth { get; }

    double Diameter { get; }

    double ThreadDepth { get; }

    /// <summary><c>ThreadEndCondition</c> verbatim (<c>swEndConditions_e</c>).</summary>
    int ThreadEndCondition { get; }

    /// <summary><c>HoleFit</c> verbatim (<c>swWzdHoleScrewClearanceTypes_e</c>).</summary>
    int HoleFit { get; }

    string? ThreadClass { get; }

    double ThruHoleDiameter { get; }

    double TapDrillDiameter { get; }

    double CounterBoreDiameter { get; }

    double CounterBoreDepth { get; }

    double CounterSinkDiameter { get; }

    double CounterSinkAngle { get; }

    double HeadClearance { get; }
}

/// <summary>
/// T052. Hole Wizard features and cosmetic threads, per component.
///
/// The rule that shapes this file: <c>thread_depth</c> is the usable thread depth a
/// bottoming check divides by, and it is NEVER derived from the drill depth
/// (constitution Principle I, FR-008). It is written only when the feature is tapped and
/// SOLIDWORKS reports a positive ThreadDepth; in every other case it is null and the gap
/// says so.
///
/// Interop notes (research R12):
///   - Features are filtered by <c>GetTypeName2</c> first; <c>GetDefinition</c> returns
///     null for anything else.
///   - The scalars below are readable WITHOUT <c>AccessSelections</c>. AccessSelections
///     rolls the model back, so it is not called at all here; if a future field needs it,
///     it must be paired with <c>ReleaseSelectionAccess</c> in a finally.
///   - <c>Standard2</c> returns -1 for a copied or custom standard; the string
///     <c>Standard</c> is the fallback.
///   - The hole axis comes from the cylindrical face's <c>CylinderParams</c>, never from
///     <c>GetBox</c>, which is documented as approximate.
///
/// Lengths are written in meters exactly as SOLIDWORKS reports them; the Python side
/// converts explicitly.
///
/// Feature 010 (T089) reads the definition through <see cref="IHoleWizardReader"/> and adds the
/// wizard data of schema 1.5.0 (<see cref="HoleWizardData"/>): the fit and thread classes and
/// the drill, counterbore and countersink sizes, each null plus a <c>hole_wizard</c> gap when
/// its read fails.
/// </summary>
public sealed class HoleDumper : IHoleSource
{
    private const string WizardHoleFeatureType = "HoleWzd";
    private const string CosmeticThreadFeatureType = "CosmeticThread";

    private readonly ISwSession _session;
    private readonly PersistRefService _refs;

    public HoleDumper(ISwSession session, PersistRefService refs)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    public HoleDumpResult Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var result = new HoleDumpResult();

        foreach (ScopedComponent component in scope.Components)
        {
            if (component.Node.Suppression != SuppressionState.Resolved)
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "hole",
                    null,
                    $"'{component.Node.Key}' is {PackageSerializer.EnumToJsonName(component.Node.Suppression)}, "
                    + "so its holes and threads were not read.",
                    null);
                continue;
            }

            if (!(component.Node.Handle is IComponent2 handle))
            {
                continue;
            }

            var model = _session.Gate.Call("GetModelDoc2", () => handle.GetModelDoc2()) as IModelDoc2;
            if (model == null)
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted,
                    "hole",
                    null,
                    $"'{component.Node.Key}' has no loaded model document; its holes were not read.",
                    null);
                continue;
            }

            ReadFeatures(handle, model, component, scope, result);
        }

        return result;
    }

    private void ReadFeatures(
        IComponent2 handle, IModelDoc2 model, ScopedComponent component, DumpScope scope, HoleDumpResult result)
    {
        SwGate gate = _session.Gate;
        string modelPath = gate.Call("GetPathName", () => model.GetPathName());
        var sightings = new List<TypeNameSighting>();

        var feature = gate.Call("Component.FirstFeature", () => handle.FirstFeature()) as IFeature;
        while (feature != null)
        {
            IFeature current = feature;
            string typeName = gate.Call("GetTypeName2", () => current.GetTypeName2()) ?? string.Empty;
            string name = gate.Call("Feature.Name", () => current.Name) ?? string.Empty;
            bool consumed = false;

            if (typeName == WizardHoleFeatureType)
            {
                consumed = true;
                scope.Gaps.TryStep("hole", null, $"read Hole Wizard feature '{name}'", () =>
                    ReadHole(current, model, modelPath, name, component, scope, result));
            }
            else if (typeName == CosmeticThreadFeatureType)
            {
                consumed = true;
                scope.Gaps.TryStep("thread", null, $"read cosmetic thread '{name}'", () =>
                    ReadCosmeticThread(current, model, modelPath, name, component, scope, result));
            }

            sightings.Add(new TypeNameSighting(typeName, consumed));
            feature = gate.Call("GetNextFeature", () => current.GetNextFeature()) as IFeature;
        }

        // The component's document, not the instance: a part used forty times is walked
        // forty times and the census must not report its feature types forty times. The
        // node's path is the one PackageWriter already proved non-blank when it allocated
        // this component's id.
        scope.Gaps.TypeNames.AddPass(component.Node.DocumentPath, sightings);
    }

    private void ReadHole(
        IFeature feature,
        IModelDoc2 model,
        string modelPath,
        string featureName,
        ScopedComponent component,
        DumpScope scope,
        HoleDumpResult result)
    {
        SwGate gate = _session.Gate;
        var data = gate.Call("GetDefinition", () => feature.GetDefinition()) as IWizardHoleFeatureData2;

        string id = scope.HoleIds.Next();
        if (data == null)
        {
            scope.Gaps.Add(
                GapKind.Unsupported,
                "hole",
                id,
                $"GetDefinition returned nothing for '{featureName}'; the hole was not read.",
                null);
            return;
        }

        var hole = new Hole
        {
            Id = id,
            PersistRef = string.Empty,
            PersistRefScope = scope.DocumentId(modelPath),
            ComponentId = component.Id,
            FeatureName = featureName,
        };

        ReadDefinition(new SwHoleWizardReader(data, gate), hole, gate, scope.Gaps);

        // The face reference is scoped to the PART, not the assembly (data-model.md).
        ScopedPersistRef? reference = _refs.TryGet(model, feature);
        if (reference == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "hole",
                id,
                $"'{featureName}' has no persistent reference; it cannot be navigated to.",
                null);
        }
        else
        {
            hole.PersistRef = reference.Base64;
            hole.PersistRefScope = reference.ScopeDocumentId;
        }

        AddAxisAndFaces(feature, model, modelPath, component, scope, hole);
        result.Holes.Add(hole);
    }

    /// <summary>
    /// Everything a hole takes from its Hole Wizard definition: the feature 001 fields, the
    /// usable thread depth and the schema 1.5.0 wizard data. Pure but for the reads, which go
    /// through <paramref name="data"/> and <paramref name="gate"/>, so it is tested with a fake
    /// (T088).
    ///
    /// A feature 001 read that throws fails the whole hole, as it always has: the exception
    /// reaches <see cref="ReadHole"/>'s <c>hole</c> step. A wizard read that throws is that field
    /// only (<see cref="ReadWizardData"/>).
    /// </summary>
    public static void ReadDefinition(IHoleWizardReader data, Hole hole, SwGate gate, GapCollector gaps)
    {
        if (data == null)
        {
            throw new ArgumentNullException(nameof(data));
        }

        if (hole == null)
        {
            throw new ArgumentNullException(nameof(hole));
        }

        if (gate == null)
        {
            throw new ArgumentNullException(nameof(gate));
        }

        if (gaps == null)
        {
            throw new ArgumentNullException(nameof(gaps));
        }

        HoleType holeType = gate.Call("WizardHole.Type", () => data.HoleType);
        int endConditionCode = gate.Call("WizardHole.EndCondition", () => data.EndCondition);

        hole.HoleType = holeType;
        hole.Standard = data.Standard;
        hole.Size = Blank(gate.Call("FastenerSize", () => data.FastenerSize));

        // Only a tapped hole has a thread. A clearance hole carries the size of the screw it
        // is drilled FOR, and calling that a thread designation would let a thread-match check
        // pass on a hole with no threads in it.
        hole.ThreadDesignation = holeType == HoleType.Tapped ? hole.Size : null;
        hole.HoleDepth = Positive(gate.Call("HoleDepth", () => data.HoleDepth));
        hole.EndCondition = MapEndCondition(endConditionCode);
        hole.Diameter = Positive(gate.Call("WizardHole.Diameter", () => data.Diameter));
        hole.ThreadDepth = ReadUsableThreadDepth(data, gate, holeType, hole, gaps);
        hole.Wizard = ReadWizardData(data, gate, hole, gaps);
    }

    /// <summary>
    /// The schema 1.5.0 wizard data (feature 010 T089, contracts/tolerances.md section 2). Each
    /// field is its own step: a read that throws is null plus one <c>hole_wizard</c> gap naming
    /// the field, and the rest are still read. A zero, a negative or a blank is "does not apply
    /// to this hole type" and is null with no gap. Nothing is derived.
    ///
    /// <c>HoleFit</c> is read for counterbore and countersink holes only - the API documents it
    /// for those two, and on any other type its 0 would read as "close" - and
    /// <c>ThreadClass</c> for a tapped hole only, the one kind with a thread.
    ///
    /// Every read goes through <see cref="SwGate.CallOptional{T}"/>: SOLIDWORKS may refuse a
    /// property on every hole of one type, and those refusals are gaps, never an open circuit.
    /// </summary>
    private static HoleWizardData ReadWizardData(
        IHoleWizardReader data, SwGate gate, Hole hole, GapCollector gaps)
    {
        var wizard = new HoleWizardData();

        if (hole.HoleType == HoleType.Counterbore || hole.HoleType == HoleType.Countersink)
        {
            wizard.FitClassRaw = ReadWizardField(
                gaps, hole, "HoleFit", () => HoleFitName(gate.CallOptional("HoleFit", () => data.HoleFit)));
        }

        if (hole.HoleType == HoleType.Tapped)
        {
            wizard.ThreadClassRaw = ReadWizardField(
                gaps, hole, "ThreadClass", () => Blank(gate.CallOptional("ThreadClass", () => data.ThreadClass)));
        }

        wizard.ThruHoleDiameter = ReadWizardLength(gaps, hole, gate, "ThruHoleDiameter", () => data.ThruHoleDiameter);
        wizard.TapDrillDiameter = ReadWizardLength(gaps, hole, gate, "TapDrillDiameter", () => data.TapDrillDiameter);
        wizard.CounterboreDiameter = ReadWizardLength(gaps, hole, gate, "CounterBoreDiameter", () => data.CounterBoreDiameter);
        wizard.CounterboreDepth = ReadWizardLength(gaps, hole, gate, "CounterBoreDepth", () => data.CounterBoreDepth);
        wizard.CountersinkDiameter = ReadWizardLength(gaps, hole, gate, "CounterSinkDiameter", () => data.CounterSinkDiameter);
        wizard.CountersinkAngle = ReadWizardField(gaps, hole, "CounterSinkAngle", () =>
        {
            double radians = gate.CallOptional("CounterSinkAngle", () => data.CounterSinkAngle);
            return radians > 0 ? new Angle(radians, AngleUnit.Rad) : null;
        });
        wizard.HeadClearance = ReadWizardLength(gaps, hole, gate, "HeadClearance", () => data.HeadClearance);

        return wizard;
    }

    /// <summary>One wizard length, gated under <paramref name="member"/>; metres, null when not positive.</summary>
    private static Quantity? ReadWizardLength(
        GapCollector gaps, Hole hole, SwGate gate, string member, Func<double> read) =>
        ReadWizardField(gaps, hole, member, () => Positive(gate.CallOptional(member, read)));

    /// <summary>One wizard read as its own step: null plus a <c>hole_wizard</c> gap naming it when it throws.</summary>
    private static T? ReadWizardField<T>(GapCollector gaps, Hole hole, string member, Func<T?> read)
        where T : class =>
        gaps.TryStep(
            "hole_wizard",
            hole.Id,
            $"read {member} of Hole Wizard feature '{hole.FeatureName}'",
            read);

    /// <summary>
    /// <c>HoleFit</c> as its <c>swWzdHoleScrewClearanceTypes_e</c> member name - close 0,
    /// normal 1, loose 2, reflected on the 2024 SP5 interop - or the number's text for a value
    /// the enumeration does not name. Spelled here rather than looked up with
    /// <c>Enum.GetName</c>, so the mapping is tested without the interop assembly.
    /// </summary>
    public static string HoleFitName(int code) => code switch
    {
        0 => "swScrewClearanceClose",
        1 => "swScrewClearanceNormal",
        2 => "swScrewClearanceLoose",
        _ => code.ToString(CultureInfo.InvariantCulture),
    };

    /// <summary>
    /// Usable thread depth, or null. Written only for a tapped hole whose ThreadDepth is
    /// positive. A through-tapped hole reports no usable depth here on purpose: the depth
    /// would be the material thickness, which this feature does not know, and inventing it
    /// would clear a bottoming check that should stay unresolved.
    /// </summary>
    private static Quantity? ReadUsableThreadDepth(
        IHoleWizardReader data, SwGate gate, HoleType holeType, Hole hole, GapCollector gaps)
    {
        if (holeType != HoleType.Tapped)
        {
            return null;
        }

        double depth = gate.Call("ThreadDepth", () => data.ThreadDepth);
        int threadEnd = gate.Call("ThreadEndCondition", () => data.ThreadEndCondition);

        if (depth > 0 && MapEndCondition(threadEnd) == EndCondition.Blind)
        {
            return new Quantity(depth, LengthUnit.M);
        }

        gaps.Add(
            GapKind.NotExtracted,
            "hole",
            hole.Id,
            $"'{hole.FeatureName}' is tapped but SOLIDWORKS reports no usable blind thread depth "
            + $"(ThreadDepth {depth} m, thread end condition {threadEnd}); it is left unknown and "
            + "is never derived from the drill depth.",
            null);
        return null;
    }

    private void ReadCosmeticThread(
        IFeature feature,
        IModelDoc2 model,
        string modelPath,
        string featureName,
        ScopedComponent component,
        DumpScope scope,
        HoleDumpResult result)
    {
        SwGate gate = _session.Gate;
        var data = gate.Call("GetDefinition", () => feature.GetDefinition()) as ICosmeticThreadFeatureData;

        string id = scope.ThreadIds.Next();
        if (data == null)
        {
            scope.Gaps.Add(
                GapKind.Unsupported,
                "thread",
                id,
                $"GetDefinition returned nothing for cosmetic thread '{featureName}'.",
                null);
            return;
        }

        // ThreadCallout is what the drawing would read; Size is the library size. Neither
        // is invented when both are blank.
        string callout = Blank(gate.Call("ThreadCallout", () => data.ThreadCallout))
            ?? Blank(gate.Call("CosmeticThread.Size", () => data.Size))
            ?? string.Empty;

        int endCondition = gate.Call("CosmeticThread.EndCondition", () => data.EndCondition);
        double blindDepth = gate.Call("BlindDepth", () => data.BlindDepth);

        var thread = new CosmeticThread
        {
            Id = id,
            PersistRef = string.Empty,
            PersistRefScope = scope.DocumentId(modelPath),
            ComponentId = component.Id,
            FaceId = string.Empty,
            Designation = callout,
            Depth = MapEndCondition(endCondition) == EndCondition.Blind ? Positive(blindDepth) : null,

            // A cosmetic thread on an outside diameter is external; this build cannot tell
            // the two apart without reading the edge's face, so it records the common case
            // and a gap. An external thread mis-labelled internal must not silently satisfy
            // a thread-match check.
            IsExternal = false,
        };

        if (callout.Length == 0)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "thread",
                id,
                $"Cosmetic thread '{featureName}' carries no callout or size.",
                null);
        }

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "thread",
            id,
            $"Cosmetic thread '{featureName}' is recorded as internal; "
            + "internal versus external was not determined from the geometry.",
            null);

        ScopedPersistRef? reference = _refs.TryGet(model, feature);
        if (reference == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted, "thread", id, $"'{featureName}' has no persistent reference.", null);
        }
        else
        {
            thread.PersistRef = reference.Base64;
            thread.PersistRefScope = reference.ScopeDocumentId;
        }

        result.Threads.Add(thread);
    }

    /// <summary>
    /// The hole's axis from the cylindrical face SOLIDWORKS generated for it, transformed
    /// into assembly space. GetBox is never used for this: it is approximate and changes
    /// after a rebuild (research R12).
    /// </summary>
    private void AddAxisAndFaces(
        IFeature feature,
        IModelDoc2 model,
        string modelPath,
        ScopedComponent component,
        DumpScope scope,
        Hole hole)
    {
        SwGate gate = _session.Gate;
        var faces = gate.Call("Feature.GetFaces", () => feature.GetFaces()) as object[];

        if (faces == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "hole",
                hole.Id,
                $"'{hole.FeatureName}' reported no faces, so its axis is unknown.",
                null);
            return;
        }

        bool axisFound = false;
        foreach (object item in faces)
        {
            if (!(item is IFace2 face))
            {
                continue;
            }

            var surface = gate.Call("GetSurface", () => face.GetSurface()) as ISurface;
            if (surface == null || !gate.Call("IsCylinder", () => surface.IsCylinder()))
            {
                continue;
            }

            hole.FaceIds.Add(scope.RequestFace(face, component.Id, component.Node.Transform, modelPath));

            if (!axisFound
                && gate.Call("CylinderParams", () => surface.CylinderParams) is double[] cylinder
                && cylinder.Length >= 7)
            {
                // CylinderParams: origin x y z, axis x y z, radius - 7 doubles in meters.
                hole.Axis = new Axis(
                    SwTransform.ApplyToPoint(
                        component.Node.Transform, new Vec3(cylinder[0], cylinder[1], cylinder[2])),
                    SwTransform.ApplyToDirection(
                        component.Node.Transform, new Vec3(cylinder[3], cylinder[4], cylinder[5])));
                axisFound = true;
            }
        }

        if (!axisFound)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "hole",
                hole.Id,
                $"'{hole.FeatureName}' has no cylindrical face with readable CylinderParams, "
                + "so its axis is unknown and alignment checks are unresolved.",
                null);
        }
    }

    /// <summary>
    /// <c>swEndConditions_e</c> to the IR's three-value end condition, by the enumeration's
    /// values as reflected on the 2024 SP5 interop - spelled as numbers so the mapping is tested
    /// without the interop assembly (feature 010 T088).
    /// </summary>
    public static EndCondition MapEndCondition(int endCondition)
    {
        switch (endCondition)
        {
            case 0: // swEndCondBlind
                return EndCondition.Blind;

            case 1: // swEndCondThroughAll
            case 2: // swEndCondThroughNext
            case 9: // swEndCondThroughAllBoth
            case 11: // swEndCondUpToNext
                return EndCondition.Through;

            default:
                // Up to vertex (3), up to surface (4), offset from surface (5), midplane (6),
                // up to body (7), up to selection (10): the depth depends on geometry this
                // feature does not carry.
                return EndCondition.Unknown;
        }
    }

    internal static string? Blank(string? text) =>
        string.IsNullOrWhiteSpace(text) ? null : text!.Trim();

    /// <summary>A length in meters, or null when SOLIDWORKS reported zero or less.</summary>
    private static Quantity? Positive(double meters) =>
        meters > 0 ? new Quantity(meters, LengthUnit.M) : null;
}
