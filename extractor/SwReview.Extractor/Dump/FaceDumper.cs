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
/// T055. Face geometry, in assembly space.
///
/// By default only the faces another dumper asked for are described (a hole's cylinder, a
/// fastener's shank, a mated face); <c>--faces all</c> sweeps every face of every body,
/// which is large and only useful for debugging.
///
/// Surface parameters (research R12):
///   <c>CylinderParams</c> is 7 doubles - origin x y z, axis x y z, radius - in meters.
///   <c>PlaneParams</c> is 6 doubles - NORMAL first, then a root point. The order is the
///   opposite of what most people assume, which is why it is spelled out here.
///
/// <c>GetBox</c> fills the bbox and NOTHING else: SOLIDWORKS documents it as approximate
/// and says it may change after a rebuild, so no axis, distance or radius ever comes from
/// it.
/// </summary>
public sealed class FaceDumper : IFaceSource
{
    private readonly ISwSession _session;
    private readonly PersistRefService _refs;
    private readonly Func<string, IModelDoc2?> _openDocument;

    /// <param name="openDocument">
    /// Turns a document path back into the open document whose extension scopes a face's
    /// persistent reference. Supplied by the caller that owns the SldWorks pointer, so this
    /// class stays about faces.
    /// </param>
    public FaceDumper(ISwSession session, PersistRefService refs, Func<string, IModelDoc2?> openDocument)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
        _openDocument = openDocument ?? throw new ArgumentNullException(nameof(openDocument));
    }

    public IReadOnlyList<FaceGeometry> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var faces = new List<FaceGeometry>();

        foreach (FaceRequest request in scope.FaceRequests)
        {
            scope.Gaps.TryStep("face", request.FaceId, "describe a referenced face", () =>
            {
                FaceGeometry? face = Describe(request, request.FaceId!, scope);
                if (face != null)
                {
                    faces.Add(face);
                }
            });
        }

        if (scope.Options.Faces == FaceScope.All)
        {
            SweepEveryFace(scope, faces);
        }

        return faces;
    }

    private FaceGeometry? Describe(FaceRequest request, string faceId, DumpScope scope)
    {
        if (!(request.Entity is IFace2 face))
        {
            return null;
        }

        SwGate gate = _session.Gate;
        var surface = gate.Call("GetSurface", () => face.GetSurface()) as ISurface;

        var geometry = new FaceGeometry
        {
            Id = faceId,
            PersistRef = string.Empty,
            PersistRefScope = scope.DocumentId(request.ScopeDocumentPath),
            ComponentId = request.ComponentId,
            BodyId = string.Empty,
            Kind = FaceKind.Other,
            AreaM2 = gate.Call("GetArea", () => face.GetArea()),
            Bbox = ReadBoundingBox(face, request.ComponentTransform, gate),
        };

        if (surface == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "face",
                faceId,
                "The face reported no surface, so its kind and parameters are unknown.",
                null);
        }
        else
        {
            ReadSurface(surface, request.ComponentTransform, geometry, scope, gate);
        }

        AttachReference(face, request, geometry, scope);
        return geometry;
    }

    private void ReadSurface(
        ISurface surface, double[][] transform, FaceGeometry geometry, DumpScope scope, SwGate gate)
    {
        if (gate.Call("IsCylinder", () => surface.IsCylinder()))
        {
            geometry.Kind = FaceKind.Cylinder;

            if (gate.Call("CylinderParams", () => surface.CylinderParams) is double[] p && p.Length >= 7)
            {
                geometry.Cylinder = new CylinderSurface
                {
                    AxisOrigin = SwTransform.ApplyToPoint(transform, new Vec3(p[0], p[1], p[2])),
                    AxisDir = SwTransform.ApplyToDirection(transform, new Vec3(p[3], p[4], p[5])),
                    RadiusM = p[6],
                };
            }
            else
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted, "face", geometry.Id, "CylinderParams could not be read.", null);
            }

            return;
        }

        if (gate.Call("IsPlane", () => surface.IsPlane()))
        {
            geometry.Kind = FaceKind.Plane;

            if (gate.Call("PlaneParams", () => surface.PlaneParams) is double[] p && p.Length >= 6)
            {
                // PlaneParams is NORMAL first (0..2), then the root point (3..5).
                geometry.Plane = new PlaneSurface
                {
                    Normal = SwTransform.ApplyToDirection(transform, new Vec3(p[0], p[1], p[2])),
                    Origin = SwTransform.ApplyToPoint(transform, new Vec3(p[3], p[4], p[5])),
                };
            }
            else
            {
                scope.Gaps.Add(
                    GapKind.NotExtracted, "face", geometry.Id, "PlaneParams could not be read.", null);
            }

            return;
        }

        if (gate.Call("IsCone", () => surface.IsCone()))
        {
            geometry.Kind = FaceKind.Cone;
        }
        else if (gate.Call("IsTorus", () => surface.IsTorus()))
        {
            geometry.Kind = FaceKind.Torus;
        }

        scope.Gaps.Add(
            GapKind.Unsupported,
            "face",
            geometry.Id,
            $"The face is a {PackageSerializer.EnumToJsonName(geometry.Kind)} surface; "
            + "only cylinders and planes carry parameters in this build.",
            null);
    }

    /// <summary>
    /// The bbox, and only the bbox, from <c>GetBox</c>. The eight corners are transformed
    /// and re-boxed, because rotating an axis-aligned box and keeping two corners would
    /// shrink it.
    /// </summary>
    private static BoundingBox ReadBoundingBox(IFace2 face, double[][] transform, SwGate gate)
    {
        var box = gate.Call("GetBox", () => face.GetBox()) as double[];
        if (box == null || box.Length < 6)
        {
            return new BoundingBox();
        }

        double minX = double.MaxValue, minY = double.MaxValue, minZ = double.MaxValue;
        double maxX = double.MinValue, maxY = double.MinValue, maxZ = double.MinValue;

        for (int corner = 0; corner < 8; corner++)
        {
            var local = new Vec3(
                (corner & 1) == 0 ? box[0] : box[3],
                (corner & 2) == 0 ? box[1] : box[4],
                (corner & 4) == 0 ? box[2] : box[5]);

            Vec3 world = SwTransform.ApplyToPoint(transform, local);
            minX = Math.Min(minX, world.X);
            minY = Math.Min(minY, world.Y);
            minZ = Math.Min(minZ, world.Z);
            maxX = Math.Max(maxX, world.X);
            maxY = Math.Max(maxY, world.Y);
            maxZ = Math.Max(maxZ, world.Z);
        }

        return new BoundingBox
        {
            Min = new Vec3(minX, minY, minZ),
            Max = new Vec3(maxX, maxY, maxZ),
        };
    }

    /// <summary>
    /// A face's persistent reference is produced by the OWNING PART's extension, not the
    /// assembly's. Which of the two actually resolves it is the open question from research
    /// R12, so the scope is recorded and quickstart Scenario 2 round-trips it.
    /// </summary>
    private void AttachReference(IFace2 face, FaceRequest request, FaceGeometry geometry, DumpScope scope)
    {
        var body = _session.Gate.Call("Face.GetBody", () => face.GetBody()) as IBody2;
        if (body != null)
        {
            geometry.BodyId = _session.Gate.Call("Body.Name", () => body.Name) ?? string.Empty;
        }

        IModelDoc2? scopeDocument = _openDocument(request.ScopeDocumentPath);
        if (scopeDocument == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "face",
                geometry.Id,
                $"The owning document '{request.ScopeDocumentPath}' is not open, so the face has no "
                + "persistent reference and cannot be navigated to.",
                null);
            return;
        }

        ScopedPersistRef? reference = _refs.TryGet(scopeDocument, face);
        if (reference == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "face",
                geometry.Id,
                "SOLIDWORKS gave no persistent reference for the face.",
                null);
            return;
        }

        geometry.PersistRef = reference.Base64;
        geometry.PersistRefScope = reference.ScopeDocumentId;
    }

    /// <summary><c>--faces all</c>: every face of every solid body of every resolved component.</summary>
    private void SweepEveryFace(DumpScope scope, List<FaceGeometry> faces)
    {
        SwGate gate = _session.Gate;

        foreach (ScopedComponent component in scope.Components)
        {
            if (component.Node.Suppression != SuppressionState.Resolved
                || !(component.Node.Handle is IComponent2 handle))
            {
                continue;
            }

            var model = gate.Call("GetModelDoc2", () => handle.GetModelDoc2()) as IModelDoc2;
            if (model == null)
            {
                continue;
            }

            string path = gate.Call("GetPathName", () => model.GetPathName());
            var bodies = gate.Call("GetBodies2", () => handle.GetBodies2((int)swBodyType_e.swSolidBody))
                as object[];

            if (bodies == null)
            {
                continue;
            }

            foreach (object bodyItem in bodies)
            {
                if (!(bodyItem is IBody2 body)
                    || !(gate.Call("GetFaces", () => body.GetFaces()) is object[] bodyFaces))
                {
                    continue;
                }

                foreach (object faceItem in bodyFaces)
                {
                    if (!(faceItem is IFace2 face))
                    {
                        continue;
                    }

                    var request = new FaceRequest(face, component.Id, component.Node.Transform, path)
                    {
                        FaceId = scope.FaceIds.Next(),
                    };

                    scope.Gaps.TryStep("face", request.FaceId, "describe a face (--faces all)", () =>
                    {
                        FaceGeometry? geometry = Describe(request, request.FaceId!, scope);
                        if (geometry != null)
                        {
                            faces.Add(geometry);
                        }
                    });
                }
            }
        }
    }
}
