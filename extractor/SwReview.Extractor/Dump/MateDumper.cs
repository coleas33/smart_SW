using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;
using IrMate = SwReview.Extractor.Ir.Mate;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T051. Mates of the root assembly.
///
/// SOLIDWORKS 2024 has no <c>IAssemblyDoc.GetMates</c>; mates live in the feature tree
/// under the MateGroup feature, and each mate feature's <c>GetSpecificFeature2</c> returns
/// the <c>IMate2</c>. Distance and angle mates carry their value on the mate's DIMENSION,
/// not on IMate2, so those stay null with a Gap rather than being guessed from the
/// geometry (constitution Principle I): a wrong mate distance would silently feed a stack
/// calculation.
///
/// Mate entity params (8 doubles, assembly space, meters) are NOT interpreted here - what
/// they mean depends on the entity type (research R12) - but the entity's persistent
/// reference and its component are recorded so a check can navigate to it, and a face
/// entity is registered with the face dumper so its geometry is described.
/// </summary>
public sealed class MateDumper : IMateSource
{
    private const string MateGroupFeatureType = "MateGroup";

    private readonly ISwSession _session;
    private readonly PersistRefService _refs;

    public MateDumper(ISwSession session, PersistRefService refs)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    public IReadOnlyList<IrMate> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var mates = new List<IrMate>();
        SwGate gate = _session.Gate;

        var feature = gate.Call("FirstFeature", () => _session.Document.FirstFeature()) as IFeature;
        while (feature != null)
        {
            IFeature current = feature;
            string typeName = gate.Call("GetTypeName2", () => current.GetTypeName2()) ?? string.Empty;
            if (typeName == MateGroupFeatureType)
            {
                ReadMateGroup(current, scope, mates);
            }

            feature = gate.Call("GetNextFeature", () => current.GetNextFeature()) as IFeature;
        }

        return mates;
    }

    private void ReadMateGroup(IFeature mateGroup, DumpScope scope, List<IrMate> mates)
    {
        SwGate gate = _session.Gate;
        var child = gate.Call("GetFirstSubFeature", () => mateGroup.GetFirstSubFeature()) as IFeature;

        while (child != null)
        {
            IFeature current = child;
            string name = gate.Call("Feature.Name", () => current.Name) ?? string.Empty;

            scope.Gaps.TryStep("mate", null, $"read mate '{name}'", () =>
            {
                var mate = gate.Call("GetSpecificFeature2", () => current.GetSpecificFeature2()) as IMate2;
                if (mate != null)
                {
                    mates.Add(ReadMate(mate, current, name, scope));
                }
            });

            child = gate.Call("GetNextSubFeature", () => current.GetNextSubFeature()) as IFeature;
        }
    }

    private IrMate ReadMate(IMate2 mate, IFeature feature, string featureName, DumpScope scope)
    {
        SwGate gate = _session.Gate;
        int type = gate.Call("Mate.Type", () => mate.Type);

        var record = new IrMate
        {
            Id = scope.MateIds.Next(),
            PersistRef = string.Empty,
            PersistRefScope = scope.DocumentId(
                gate.Call("GetPathName", () => _session.Document.GetPathName())),
            Type = MateTypeName(type),
            Alignment = ReadAlignment(gate.Call("Mate.Alignment", () => mate.Alignment)),

            // IFeature.IsSuppressed is not exposed on IMate2; a suppressed mate sits in the
            // tree with no solved entities, which the entity list below makes visible.
            Suppressed = false,
        };

        ScopedPersistRef? reference = _refs.TryGet(_session.Document, feature);
        if (reference == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "mate",
                record.Id,
                $"Mate '{featureName}' has no persistent reference; it cannot be navigated to.",
                null);
        }
        else
        {
            record.PersistRef = reference.Base64;
            record.PersistRefScope = reference.ScopeDocumentId;
        }

        ReadEntities(mate, record, featureName, scope);

        // Distance and angle live on the mate's display dimension, which this build does
        // not read. Recording the gap keeps a stack check from treating them as absent.
        if (IsDimensioned(type))
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "mate",
                record.Id,
                $"Mate '{featureName}' is a distance or angle mate; its value was not read, "
                + "so any check that needs it is unresolved.",
                null);
        }

        return record;
    }

    private void ReadEntities(IMate2 mate, IrMate record, string featureName, DumpScope scope)
    {
        SwGate gate = _session.Gate;
        int count = gate.Call("GetMateEntityCount", () => mate.GetMateEntityCount());

        for (int i = 0; i < count; i++)
        {
            int index = i;
            scope.Gaps.TryStep("mate", record.Id, $"read entity {index} of mate '{featureName}'", () =>
            {
                var entity = gate.Call("MateEntity", () => mate.MateEntity(index)) as IMateEntity2;
                if (entity == null)
                {
                    return;
                }

                var owner = gate.Call("ReferenceComponent", () => entity.ReferenceComponent) as IComponent2;
                string ownerKey = owner == null
                    ? string.Empty
                    : gate.Call("Name2", () => owner.Name2) ?? string.Empty;

                ScopedComponent? component = scope.Find(ownerKey);
                object? reference = gate.Call("MateEntity.Reference", () => entity.Reference);

                record.Entities.Add(new MateEntityRef
                {
                    ComponentId = component?.Id ?? string.Empty,
                    PersistRef = reference == null
                        ? null
                        : _refs.TryGet(_session.Document, reference)?.Base64,
                    EntityKind = EntityKindName(gate.Call("ReferenceType2", () => entity.ReferenceType2)),
                });

                RequestFaceGeometry(reference, component, owner, scope);
            });
        }
    }

    /// <summary>
    /// A mate on a face is a check input (coaxiality, gaps), so that face is described by
    /// the face dumper. The face belongs to the component's PART document, which is where
    /// its persistent reference must be scoped from.
    /// </summary>
    private void RequestFaceGeometry(
        object? reference, ScopedComponent? component, IComponent2? owner, DumpScope scope)
    {
        if (!(reference is IFace2) || component == null || owner == null)
        {
            return;
        }

        var model = _session.Gate.Call("GetModelDoc2", () => owner.GetModelDoc2()) as IModelDoc2;
        if (model == null)
        {
            return;
        }

        string path = _session.Gate.Call("GetPathName", () => model.GetPathName());
        scope.RequestFace(reference, component.Id, component.Node.Transform, path);
    }

    /// <summary>The swMateType_e member name, e.g. "swMateCONCENTRIC".</summary>
    private static string MateTypeName(int type)
    {
        string? name = Enum.GetName(typeof(swMateType_e), type);
        return name ?? $"swMateUNKNOWN({type})";
    }

    private static MateAlignment ReadAlignment(int alignment)
    {
        switch ((swMateAlign_e)alignment)
        {
            case swMateAlign_e.swMateAlignANTI_ALIGNED:
                return MateAlignment.AntiAligned;
            case swMateAlign_e.swMateAlignCLOSEST:
                return MateAlignment.Closest;
            default:
                return MateAlignment.Aligned;
        }
    }

    private static string EntityKindName(int referenceType)
    {
        string? name = Enum.GetName(typeof(swSelectType_e), referenceType);
        return name ?? $"unknown({referenceType})";
    }

    /// <summary>Mate types whose value lives on a dimension rather than on IMate2.</summary>
    private static bool IsDimensioned(int type) =>
        (swMateType_e)type == swMateType_e.swMateDISTANCE
        || (swMateType_e)type == swMateType_e.swMateANGLE;
}
