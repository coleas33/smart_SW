using System;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Ids;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.PersistRefs;

/// <summary>A persistent reference and the document it is scoped to.</summary>
public sealed class ScopedPersistRef
{
    public ScopedPersistRef(string base64, string scopeDocumentId, string scopeDocumentPath)
    {
        Base64 = base64;
        ScopeDocumentId = scopeDocumentId;
        ScopeDocumentPath = scopeDocumentPath;
    }

    public string Base64 { get; }

    /// <summary>document_id of the document whose extension produced the reference.</summary>
    public string ScopeDocumentId { get; }

    public string ScopeDocumentPath { get; }
}

/// <summary>What a reference resolved to, and in what state.</summary>
public sealed class ResolvedPersistRef
{
    public ResolvedPersistRef(object? entity, swPersistReferencedObjectStates_e state)
    {
        Entity = entity;
        State = state;
    }

    /// <summary>The SOLIDWORKS entity, or null when it could not be resolved.</summary>
    public object? Entity { get; }

    /// <summary>0 ok, 1 invalid, 2 suppressed, 4 deleted (research R12).</summary>
    public swPersistReferencedObjectStates_e State { get; }

    public bool IsOk => State == swPersistReferencedObjectStates_e.swPersistReferencedObject_Ok
        && Entity != null;

    /// <summary>A sentence an engineer can read in the report.</summary>
    public string Describe()
    {
        switch (State)
        {
            case swPersistReferencedObjectStates_e.swPersistReferencedObject_Ok:
                return Entity == null ? "resolved to nothing" : "ok";
            case swPersistReferencedObjectStates_e.swPersistReferencedObject_Invalid:
                return "invalid: the reference does not belong to this document";
            case swPersistReferencedObjectStates_e.swPersistReferencedObject_Suppressed:
                return "suppressed: the entity exists but is suppressed in this configuration";
            case swPersistReferencedObjectStates_e.swPersistReferencedObject_Deleted:
                return "deleted: the entity no longer exists";
            default:
                return $"unknown state {(int)State}";
        }
    }
}

/// <summary>
/// T049. Persistent references are the only durable link between a finding and a
/// SOLIDWORKS entity (constitution Principle IV), so every entity in the IR gets one on
/// the way out and the bridge resolves it on the way back.
///
/// Scope matters. The reference is produced by ONE document's extension and must be
/// resolved by the same one: the assembly for components and mates, the owning PART for
/// faces, holes, threads and bodies. Which document owns a face inside a component is the
/// one thing research R12 could not verify, which is exactly why the IR records
/// <c>persist_ref_scope</c> and quickstart Scenario 2 round-trips it on the workstation.
///
/// References are never compared byte for byte - the bytes for one entity can differ
/// between calls. <see cref="IsSame"/> asks SOLIDWORKS instead.
/// </summary>
public sealed class PersistRefService
{
    private readonly SwGate _gate;

    public PersistRefService(SwGate gate)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
    }

    /// <summary>
    /// The reference for <paramref name="entity"/> as produced by
    /// <paramref name="scopeDoc"/>'s extension. Throws <see cref="PersistRefError"/> when
    /// SOLIDWORKS gives nothing; the caller records a Gap.
    /// </summary>
    public ScopedPersistRef Get(IModelDoc2 scopeDoc, object entity)
    {
        if (scopeDoc == null)
        {
            throw new ArgumentNullException(nameof(scopeDoc));
        }

        if (entity == null)
        {
            throw new ArgumentNullException(nameof(entity));
        }

        object? raw = _gate.Call(
            "GetPersistReference3",
            () => scopeDoc.Extension.GetPersistReference3(entity));

        string path = _gate.Call("GetPathName", () => scopeDoc.GetPathName());
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new PersistRefError(
                "The scope document has no file path, so its persistent references cannot be scoped.");
        }

        return new ScopedPersistRef(PersistRefCodec.EncodeComValue(raw), DocumentIds.For(path), path);
    }

    /// <summary>
    /// Encodes without throwing. Returns null when SOLIDWORKS gave no reference, which is
    /// the normal answer for a suppressed or lightweight entity.
    /// </summary>
    public ScopedPersistRef? TryGet(IModelDoc2 scopeDoc, object? entity)
    {
        if (scopeDoc == null || entity == null)
        {
            return null;
        }

        try
        {
            return Get(scopeDoc, entity);
        }
        catch (PersistRefError)
        {
            return null;
        }
    }

    /// <summary>
    /// Resolves a base64 reference against the document that produced it. The returned
    /// state is surfaced rather than folded into null, because "suppressed" and "deleted"
    /// mean very different things to a reviewer.
    /// </summary>
    public ResolvedPersistRef Resolve(IModelDoc2 scopeDoc, string base64)
    {
        if (scopeDoc == null)
        {
            throw new ArgumentNullException(nameof(scopeDoc));
        }

        byte[] bytes = PersistRefCodec.Decode(base64);

        int state = 0;
        object? entity = _gate.Call(
            "GetObjectByPersistReference3",
            () => scopeDoc.Extension.GetObjectByPersistReference3(bytes, out state));

        return new ResolvedPersistRef(entity, (swPersistReferencedObjectStates_e)state);
    }

    /// <summary>
    /// Whether two references point at the same entity. Always asks SOLIDWORKS
    /// (<c>IsSamePersistentID</c>); the byte arrays are not comparable (research R12).
    /// </summary>
    public bool IsSame(IModelDoc2 scopeDoc, string firstBase64, string secondBase64)
    {
        if (scopeDoc == null)
        {
            throw new ArgumentNullException(nameof(scopeDoc));
        }

        byte[] first = PersistRefCodec.Decode(firstBase64);
        byte[] second = PersistRefCodec.Decode(secondBase64);

        return _gate.Call(
            "IsSamePersistentID",
            () => scopeDoc.Extension.IsSamePersistentID(first, second)) == 1;
    }
}
