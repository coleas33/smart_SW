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
/// What one <c>IMateEntity2.Reference</c> read gave, and how the package says so: the entity
/// itself when there was one, and the <see cref="MateEntityResolution"/> that distinguishes a
/// null reference from a read that threw (schema 1.4.0).
/// </summary>
public sealed class MateEntityReferenceRead
{
    public MateEntityReferenceRead(MateEntityResolution status, object? reference)
    {
        Status = status;
        Reference = reference;
    }

    public MateEntityResolution Status { get; }

    /// <summary>The live entity, or null when it was null or unreadable.</summary>
    public object? Reference { get; }
}

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
        var sightings = new List<TypeNameSighting>();
        SwGate gate = _session.Gate;

        var feature = gate.Call("FirstFeature", () => _session.Document.FirstFeature()) as IFeature;
        while (feature != null)
        {
            IFeature current = feature;
            string typeName = gate.Call("GetTypeName2", () => current.GetTypeName2()) ?? string.Empty;
            bool consumed = typeName == MateGroupFeatureType;
            sightings.Add(new TypeNameSighting(typeName, consumed));

            if (consumed)
            {
                ReadMateGroup(current, scope, mates);
            }

            feature = gate.Call("GetNextFeature", () => current.GetNextFeature()) as IFeature;
        }

        // This walk is over the root assembly's own feature tree, so that is the document
        // the names belong to. MateGroup is the only name it claims; the component-pattern
        // walk over the same tree claims the pattern names, and the census unions the two.
        scope.Gaps.TypeNames.AddPass(scope.Tree.RootDocumentPath, sightings);

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
        string id = scope.MateIds.Next();

        var record = new IrMate
        {
            Id = id,
            PersistRef = string.Empty,
            PersistRefScope = scope.DocumentId(
                gate.Call("GetPathName", () => _session.Document.GetPathName())),
            Type = MateTypeName(type),
            Alignment = ReadAlignment(gate.Call("Mate.Alignment", () => mate.Alignment)),

            // Suppression is not exposed on IMate2, but the mate FEATURE answers for it.
            Suppressed = ReadSuppressed(feature, featureName, id, scope),
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

    /// <summary>
    /// The mate feature's <c>IsSuppressed2</c> for the configuration being dumped. The chain
    /// depth rule must not walk a suppressed mate as an edge.
    ///
    /// It answers with a VARIANT - one flag per configuration asked about - so the shape is
    /// unwrapped by <see cref="SuppressionAnswer.FirstFlag"/> rather than cast blindly. A read that failed or answered with something
    /// else is <c>false</c> plus a Gap with entity kind <c>mate_suppression</c>, and the rule
    /// reports that mate unresolved instead of trusting the false (Principle I).
    /// </summary>
    private bool ReadSuppressed(IFeature feature, string featureName, string mateId, DumpScope scope)
    {
        bool? suppressed = null;

        bool read = scope.Gaps.TryStep(
            "mate_suppression", mateId, $"read IsSuppressed2 for mate '{featureName}'", () =>
            {
                object? answer = _session.Gate.Call(
                    "IsSuppressed2",
                    () => feature.IsSuppressed2((int)swInConfigurationOpts_e.swThisConfiguration, null));
                suppressed = SuppressionAnswer.FirstFlag(answer);
            });

        if (!read)
        {
            // TryStep already recorded the failure under the same entity kind.
            return false;
        }

        if (suppressed == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "mate_suppression",
                mateId,
                $"Mate '{featureName}' gave no suppression state, so it is recorded as "
                + "unsuppressed and any check that walks it is unresolved.",
                null);
            return false;
        }

        return suppressed.Value;
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

                // Schema 1.4.0, and no new interop call: the Reference read already happened
                // here, and all that changes is that a reference that came back null is now
                // told from a read that threw. Both produced a null persist_ref before, which
                // is the conflation standards.assembly.mate_references exists to end.
                MateEntityReferenceRead resolution = ReadEntityReference(
                    record.Id, featureName, index, scope.Gaps, gate, () => entity.Reference);

                object? reference = resolution.Reference;

                record.Entities.Add(new MateEntityRef
                {
                    ComponentId = component?.Id ?? string.Empty,
                    PersistRef = reference == null
                        ? null
                        : _refs.TryGet(_session.Document, reference)?.Base64,
                    EntityKind = EntityKindName(gate.Call("ReferenceType2", () => entity.ReferenceType2)),
                    ResolutionStatus = resolution.Status,
                });

                RequestFaceGeometry(reference, component, owner, scope);
            });
        }
    }

    /// <summary>
    /// One <c>IMateEntity2.Reference</c> read, and what it means (schema 1.4.0): non-null is
    /// <c>resolved</c>, null is <c>unresolved</c> - the mate points at an entity that is gone,
    /// which is a finding - and a read that threw is <c>unknown</c> plus a
    /// <c>mate_entity_reference</c> gap, which is unresolved coverage. Before 1.4.0 all three
    /// produced a null <c>persist_ref</c> and were indistinguishable.
    ///
    /// The interop expression stays at the call site and the policy lives here, because the
    /// dumper holds a live <c>IMate2</c> that no machine without a seat can produce - the same
    /// split <see cref="FeatureDumper"/> makes with <see cref="IFeatureReader"/>, one delegate
    /// wide instead of one interface wide.
    /// </summary>
    public static MateEntityReferenceRead ReadEntityReference(
        string mateId,
        string featureName,
        int index,
        GapCollector gaps,
        SwGate gate,
        Func<object?> read)
    {
        object? reference = null;
        bool answered = gaps.TryStep(
            "mate_entity_reference",
            mateId,
            $"read Reference for entity {index} of mate '{featureName}'",
            () => { reference = gate.Call("MateEntity.Reference", read); });

        if (!answered)
        {
            return new MateEntityReferenceRead(MateEntityResolution.Unknown, null);
        }

        return new MateEntityReferenceRead(
            reference == null ? MateEntityResolution.Unresolved : MateEntityResolution.Resolved,
            reference);
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
