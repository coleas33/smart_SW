using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Mesh;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T056. One mesh file per solid body under <c>meshes/</c>.
///
/// Tessellation quality is fixed rather than configurable: the meshes exist for raycasting
/// and envelope checks (US5), and a tolerance the caller can turn down would silently
/// change a clearance answer. Positions come back in the BODY's frame in meters; the
/// component transform rides along on the glTF node (and is baked into an STL, which has
/// no nodes).
///
/// Walking a tessellation (research R12): facet to three fins, fin to two vertices,
/// vertex to a point. The face-facet map is built the other way round - face to its facets
/// - because comparing COM face pointers for equality is not reliable.
/// </summary>
public sealed class MeshExporter : IMeshSource
{
    /// <summary>0.1 mm chord and plane tolerance: fine enough for clearance, small enough to write.</summary>
    private const double ChordToleranceM = 0.0001;

    private const double PlaneToleranceM = 0.0001;

    private readonly ISwSession _session;
    private readonly PersistRefService _refs;

    public MeshExporter(ISwSession session, PersistRefService refs)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    public IReadOnlyList<BodyRef> Dump(DumpScope scope, string meshDirectory)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        if (string.IsNullOrWhiteSpace(meshDirectory))
        {
            throw new ArgumentException("A mesh directory is required.", nameof(meshDirectory));
        }

        var bodies = new List<BodyRef>();
        Directory.CreateDirectory(meshDirectory);

        foreach (ScopedComponent component in scope.Components)
        {
            Export(component, scope, meshDirectory, bodies);
        }

        return bodies;
    }

    /// <summary>
    /// T097, lever 10a: the same export for one component, so a mesh fetched over the bridge
    /// is written by the same <see cref="ExportBody"/>, at the same chord tolerance, as a
    /// mesh the dump wrote.
    /// </summary>
    public IReadOnlyList<BodyRef> DumpComponent(
        DumpScope scope, ScopedComponent component, string meshDirectory)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        if (component == null)
        {
            throw new ArgumentNullException(nameof(component));
        }

        if (string.IsNullOrWhiteSpace(meshDirectory))
        {
            throw new ArgumentException("A mesh directory is required.", nameof(meshDirectory));
        }

        var bodies = new List<BodyRef>();
        Directory.CreateDirectory(meshDirectory);
        Export(component, scope, meshDirectory, bodies);
        return bodies;
    }

    private void Export(
        ScopedComponent component,
        DumpScope scope,
        string meshDirectory,
        List<BodyRef> bodies)
    {
        if (component.Node.Suppression != SuppressionState.Resolved
            || !(component.Node.Handle is IComponent2 handle))
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "body",
                null,
                $"'{component.Node.Key}' is not resolved, so no mesh was written for it.",
                null);
            return;
        }

        ExportComponent(handle, component, scope, meshDirectory, bodies);
    }

    private void ExportComponent(
        IComponent2 handle,
        ScopedComponent component,
        DumpScope scope,
        string meshDirectory,
        List<BodyRef> bodies)
    {
        SwGate gate = _session.Gate;

        var model = gate.Call("GetModelDoc2", () => handle.GetModelDoc2()) as IModelDoc2;
        if (model == null)
        {
            return;
        }

        var bodyArray = gate.Call("GetBodies2", () => handle.GetBodies2((int)swBodyType_e.swSolidBody))
            as object[];

        if (bodyArray == null)
        {
            return;
        }

        foreach (object item in bodyArray)
        {
            if (!(item is IBody2 body))
            {
                continue;
            }

            string bodyId = scope.BodyIds.Next();
            scope.Gaps.TryStep("body", bodyId, $"tessellate a body of '{component.Node.Key}'", () =>
            {
                BodyRef? reference = ExportBody(body, model, component, scope, meshDirectory, bodyId);
                if (reference != null)
                {
                    bodies.Add(reference);
                }
            });
        }
    }

    private BodyRef? ExportBody(
        IBody2 body,
        IModelDoc2 model,
        ScopedComponent component,
        DumpScope scope,
        string meshDirectory,
        string bodyId)
    {
        SwGate gate = _session.Gate;

        var tessellation = gate.Call("GetTessellation", () => body.GetTessellation(null)) as ITessellation;
        if (tessellation == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted, "body", bodyId, "GetTessellation returned nothing.", null);
            return null;
        }

        gate.Call("CurveChordTolerance", () => tessellation.CurveChordTolerance = ChordToleranceM);
        gate.Call("SurfacePlaneTolerance", () => tessellation.SurfacePlaneTolerance = PlaneToleranceM);
        gate.Call("NeedFaceFacetMap", () => tessellation.NeedFaceFacetMap = true);
        gate.Call("NeedVertexNormal", () => tessellation.NeedVertexNormal = true);

        if (!gate.Call("Tessellate", () => tessellation.Tessellate()))
        {
            scope.Gaps.Add(GapKind.ToolError, "body", bodyId, "Tessellate() failed for the body.", null);
            return null;
        }

        MeshData mesh = BuildMesh(tessellation, body, component, gate);
        if (mesh.TriangleCount == 0)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted, "body", bodyId, "The tessellation produced no triangles.", null);
            return null;
        }

        ScopedPersistRef? reference = _refs.TryGet(model, body);
        if (reference == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "body",
                bodyId,
                $"SOLIDWORKS gave no persistent reference for a body of '{component.Node.Key}'.",
                null);
            return null;
        }

        mesh.PersistRef = reference.Base64;
        mesh.PersistRefScope = reference.ScopeDocumentId;

        string extension = scope.Options.Meshes == MeshFormat.Stl ? ".stl" : ".glb";
        string fileName = FileName(component.Id, bodyId) + extension;
        string path = Path.Combine(meshDirectory, fileName);

        if (scope.Options.Meshes == MeshFormat.Stl)
        {
            StlWriter.WriteFile(path, mesh);
        }
        else
        {
            GlbWriter.WriteFile(path, mesh);
        }

        return new BodyRef
        {
            Id = bodyId,
            PersistRef = mesh.PersistRef,
            PersistRefScope = mesh.PersistRefScope,
            ComponentId = component.Id,
            MeshFile = PackageWriter.MeshDirectoryName + "/" + fileName,
            TriangleCount = mesh.TriangleCount,
            IsSolid = mesh.IsSolid,
        };
    }

    private static MeshData BuildMesh(
        ITessellation tessellation, IBody2 body, ScopedComponent component, SwGate gate)
    {
        int vertexCount = gate.Call("GetVertexCount", () => tessellation.GetVertexCount());
        int facetCount = gate.Call("GetFacetCount", () => tessellation.GetFacetCount());

        var positions = new float[vertexCount * 3];
        for (int i = 0; i < vertexCount; i++)
        {
            int index = i;
            if (gate.Call("GetVertexPoint", () => tessellation.GetVertexPoint(index)) is double[] point
                && point.Length >= 3)
            {
                positions[(i * 3) + 0] = (float)point[0];
                positions[(i * 3) + 1] = (float)point[1];
                positions[(i * 3) + 2] = (float)point[2];
            }
        }

        var indices = new List<uint>(facetCount * 3);
        for (int facet = 0; facet < facetCount; facet++)
        {
            int index = facet;
            if (!(gate.Call("GetFacetFins", () => tessellation.GetFacetFins(index)) is int[] fins)
                || fins.Length < 3)
            {
                continue;
            }

            // Two fins are enough to name the triangle: the first gives two corners, the
            // second contributes the one that is not already in the pair.
            if (!(gate.Call("GetFinVertices", () => tessellation.GetFinVertices(fins[0])) is int[] first)
                || first.Length < 2
                || !(gate.Call("GetFinVertices", () => tessellation.GetFinVertices(fins[1])) is int[] second)
                || second.Length < 2)
            {
                continue;
            }

            int third = second[0] != first[0] && second[0] != first[1] ? second[0] : second[1];

            indices.Add((uint)first[0]);
            indices.Add((uint)first[1]);
            indices.Add((uint)third);
        }

        return new MeshData
        {
            Name = component.Node.Key + "/" + (gate.Call("Body.Name", () => body.Name) ?? "body"),
            Positions = positions,
            Indices = indices.ToArray(),
            NodeTransform = component.Node.Transform,
            FaceFacetMap = BuildFaceFacetMap(tessellation, body, facetCount, gate),
            IsSolid = gate.Call("Body.GetType", () => body.GetType()) == (int)swBodyType_e.swSolidBody,
        };
    }

    /// <summary>
    /// Facet index to the index of the face it belongs to, within the body's face list.
    /// Built face-first (<c>GetFaceFacets</c>) rather than facet-first, because comparing
    /// the COM face pointers <c>GetFacetFace</c> returns is not reliable.
    /// </summary>
    private static int[]? BuildFaceFacetMap(
        ITessellation tessellation, IBody2 body, int facetCount, SwGate gate)
    {
        if (!(gate.Call("GetFaces", () => body.GetFaces()) is object[] faces))
        {
            return null;
        }

        var map = new int[facetCount];
        for (int i = 0; i < map.Length; i++)
        {
            map[i] = -1;
        }

        for (int faceIndex = 0; faceIndex < faces.Length; faceIndex++)
        {
            object face = faces[faceIndex];
            if (!(gate.Call("GetFaceFacets", () => tessellation.GetFaceFacets(face)) is int[] facets))
            {
                continue;
            }

            foreach (int facet in facets)
            {
                if (facet >= 0 && facet < map.Length)
                {
                    map[facet] = faceIndex;
                }
            }
        }

        return map;
    }

    /// <summary>"cmp-0002-bod-0001": ids only, so no file name depends on a model name.</summary>
    private static string FileName(string componentId, string bodyId) =>
        componentId.Replace(':', '-') + "-" + bodyId.Replace(':', '-');
}
