using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

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

        int typeCode = gate.Call("WizardHole.Type", () => data.Type);
        HoleType holeType = MapHoleType(typeCode);
        int endConditionCode = gate.Call("WizardHole.EndCondition", () => data.EndCondition);

        var hole = new Hole
        {
            Id = id,
            PersistRef = string.Empty,
            PersistRefScope = scope.DocumentId(modelPath),
            ComponentId = component.Id,
            FeatureName = featureName,
            HoleType = holeType,
            Standard = ReadStandard(data, gate),
            Size = Blank(gate.Call("FastenerSize", () => data.FastenerSize)),

            // Only a tapped hole has a thread. A clearance hole carries the size of the
            // screw it is drilled FOR, and calling that a thread designation would let a
            // thread-match check pass on a hole with no threads in it.
            ThreadDesignation = holeType == HoleType.Tapped
                ? Blank(gate.Call("FastenerSize", () => data.FastenerSize))
                : null,
            HoleDepth = Positive(gate.Call("HoleDepth", () => data.HoleDepth)),
            EndCondition = MapEndCondition(endConditionCode),
            Diameter = Positive(gate.Call("WizardHole.Diameter", () => data.Diameter)),
        };

        hole.ThreadDepth = ReadUsableThreadDepth(data, gate, holeType, hole, scope);

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
    /// Usable thread depth, or null. Written only for a tapped hole whose ThreadDepth is
    /// positive. A through-tapped hole reports no usable depth here on purpose: the depth
    /// would be the material thickness, which this feature does not know, and inventing it
    /// would clear a bottoming check that should stay unresolved.
    /// </summary>
    private static Quantity? ReadUsableThreadDepth(
        IWizardHoleFeatureData2 data, SwGate gate, HoleType holeType, Hole hole, DumpScope scope)
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

        scope.Gaps.Add(
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
    /// <c>Standard2</c> is an enum; -1 means a copied or custom standard, and then the
    /// free-text <c>Standard</c> is the only answer (research R12).
    /// </summary>
    private static string? ReadStandard(IWizardHoleFeatureData2 data, SwGate gate)
    {
        int standard2 = gate.Call("Standard2", () => data.Standard2);
        if (standard2 != -1)
        {
            string? name = Enum.GetName(typeof(swWzdHoleStandards_e), standard2);
            if (!string.IsNullOrEmpty(name))
            {
                return name;
            }
        }

        return Blank(gate.Call("WizardHole.Standard", () => data.Standard));
    }

    /// <summary>
    /// <c>swWzdHoleTypes_e</c> has more than eighty members (every counterbore, countersink
    /// and slot combination). They are classified by the enum member name rather than
    /// listed one by one: the name carries the primary feature, and a member added in a
    /// later service pack still lands in the right bucket instead of silently becoming a
    /// simple hole.
    /// </summary>
    private static HoleType MapHoleType(int typeCode)
    {
        string? name = Enum.GetName(typeof(swWzdHoleTypes_e), typeCode);
        if (string.IsNullOrEmpty(name))
        {
            return HoleType.Unknown;
        }

        if (name!.IndexOf("Tap", StringComparison.Ordinal) >= 0)
        {
            return HoleType.Tapped;
        }

        if (name.StartsWith("swCounterBore", StringComparison.Ordinal)
            || name.StartsWith("swCounterDrilled", StringComparison.Ordinal))
        {
            return HoleType.Counterbore;
        }

        if (name.StartsWith("swCounterSink", StringComparison.Ordinal)
            || name.StartsWith("swCounterSunk", StringComparison.Ordinal))
        {
            return HoleType.Countersink;
        }

        if (name.StartsWith("swHole", StringComparison.Ordinal)
            || name.StartsWith("swSlot", StringComparison.Ordinal))
        {
            // The wizard's "Hole" type is a clearance hole sized for a named fastener.
            return HoleType.Clearance;
        }

        if (name.StartsWith("swSimple", StringComparison.Ordinal))
        {
            return HoleType.Simple;
        }

        return HoleType.Unknown;
    }

    /// <summary>swEndConditions_e to the IR's three-value end condition.</summary>
    private static EndCondition MapEndCondition(int endCondition)
    {
        switch ((swEndConditions_e)endCondition)
        {
            case swEndConditions_e.swEndCondBlind:
                return EndCondition.Blind;

            case swEndConditions_e.swEndCondThroughAll:
            case swEndConditions_e.swEndCondThroughNext:
            case swEndConditions_e.swEndCondThroughAllBoth:
            case swEndConditions_e.swEndCondUpToNext:
                return EndCondition.Through;

            default:
                // Up to vertex, up to surface, offset from surface, midplane, up to body:
                // the depth depends on geometry this feature does not carry.
                return EndCondition.Unknown;
        }
    }

    private static string? Blank(string? text) =>
        string.IsNullOrWhiteSpace(text) ? null : text!.Trim();

    /// <summary>A length in meters, or null when SOLIDWORKS reported zero or less.</summary>
    private static Quantity? Positive(double meters) =>
        meters > 0 ? new Quantity(meters, LengthUnit.M) : null;
}
