using System;
using System.Collections.Generic;
using System.IO;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Fasteners;
using SwReview.Extractor.Geometry;
using SwReview.Extractor.Ir;
using SwReview.Extractor.PersistRefs;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T053. Fastener identity.
///
/// SOLIDWORKS 2024 has no fastener API (research R12): <c>ToolboxPartType</c> says only
/// "0 not Toolbox, 1 standard, 2 copied", and there is no IToolboxPartInfo. Identity
/// therefore comes from, in order of confidence:
///
///   1. the referenced configuration's own custom properties (Description, Length, Size,
///      Part Number) - <c>identity_source: "custom_property"</c>
///   2. the referenced configuration NAME, the description and the document's file name,
///      parsed by <see cref="FastenerNameParser"/> - <c>identity_source: "name_parse"</c>
///
/// Which components are fasteners at all is <see cref="IsFastenerCandidate"/>'s: every
/// Toolbox part, and since feature 010 any part whose names give a kind and a size (the
/// vendor screws no Toolbox flag marks, research R2.11). Every candidate gets the shank-face
/// request, so the reviewer can cross-check the parsed size against the measured shank.
///
/// A field no source supplies stays null. Head diameter and height are NOT measured
/// from the geometry in this build: a head diameter read off the wrong cylinder would
/// silently clear a counterbore clearance check, so it is left null with a Gap.
/// </summary>
public sealed class FastenerDumper : IFastenerSource
{
    private static readonly string[] DescriptionProperties = { "Description", "Fastener Description" };
    private static readonly string[] LengthProperties = { "Length", "Fastener Length", "NominalLength" };
    private static readonly string[] SizeProperties = { "Size", "Fastener Size", "Thread Size" };

    private readonly ISwSession _session;
    private readonly PersistRefService _refs;

    public FastenerDumper(ISwSession session, PersistRefService refs)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        _refs = refs ?? throw new ArgumentNullException(nameof(refs));
    }

    /// <summary>
    /// Whether the fastener phase treats a component as a fastener (feature 010 T053): a
    /// Toolbox part always, as before; any other part when its names give a kind and a size
    /// (<see cref="FastenerNameParser.IsCandidate"/>). Pure, so the gate is tested with no
    /// seat; the dumper hands it the file name, the description and the configuration name it
    /// read.
    /// </summary>
    public static bool IsFastenerCandidate(
        bool isToolbox, string? fileName, string? description, string? configuration) =>
        isToolbox || FastenerNameParser.IsCandidate(fileName, description, configuration);

    public IReadOnlyList<Fastener> Dump(DumpScope scope)
    {
        if (scope == null)
        {
            throw new ArgumentNullException(nameof(scope));
        }

        var fasteners = new List<Fastener>();

        foreach (ScopedComponent component in scope.Components)
        {
            scope.Gaps.TryStep("fastener", null, $"identify fastener '{component.Node.Key}'", () =>
            {
                Fastener? fastener = ReadFastener(component, scope);
                if (fastener != null)
                {
                    fasteners.Add(fastener);
                }
            });
        }

        return fasteners;
    }

    private Fastener? ReadFastener(ScopedComponent component, DumpScope scope)
    {
        if (!(component.Node.Handle is IComponent2 handle))
        {
            return null;
        }

        SwGate gate = _session.Gate;
        string configuration = component.Node.ReferencedConfiguration;
        string fileName = Path.GetFileName(component.Node.DocumentPath);

        var model = gate.Call("GetModelDoc2", () => handle.GetModelDoc2()) as IModelDoc2;
        Dictionary<string, string> properties = model == null
            ? new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            : PropertyDumper.ReadProperties(model, configuration, gate);

        // A vendor part keeps its Description at the document level, not per configuration,
        // so the document's own properties are asked when the configuration names none: the
        // gate's "a description that parses" would otherwise never see the vendor form.
        string? description = Lookup(properties, DescriptionProperties)
            ?? (model == null
                ? null
                : Lookup(PropertyDumper.ReadProperties(model, string.Empty, gate), DescriptionProperties));

        // The gate (T053). The id is allocated only for a candidate, so fas:NNNN still counts
        // fasteners and not components.
        if (!IsFastenerCandidate(component.Node.IsToolbox, fileName, description, configuration))
        {
            return null;
        }

        string id = scope.FastenerIds.Next();

        if (model == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "fastener",
                id,
                $"'{component.Node.Key}' has no loaded model document, so only its configuration "
                + "name could be read.",
                null);
        }

        FastenerIdentity parsed = FastenerNameParser.Parse(configuration, description, fileName);

        var fastener = new Fastener
        {
            Id = id,
            PersistRef = component.Node.PersistRef ?? string.Empty,
            PersistRefScope = scope.DocumentId(component.Node.PersistRefScopePath),
            ComponentId = component.Id,
            Kind = parsed.Kind,
            HeadType = parsed.HeadType,
            Drive = null,
            HeadDiameter = null,
            HeadHeight = null,
            Material = model == null ? null : PropertyDumper.ReadMaterial(model, configuration, gate),
        };

        // Custom properties outrank the name. Whichever one supplied the designation and
        // the length decides identity_source, so the reviewer can weigh the finding.
        string? propertySize = Lookup(properties, SizeProperties);
        Quantity? propertyLength = FastenerNameParser.ParseLength(
            Lookup(properties, LengthProperties), LengthUnit.Mm);

        fastener.ThreadDesignation = propertySize ?? parsed.ThreadDesignation;
        fastener.Length = propertyLength ?? parsed.Length;
        fastener.IdentitySource = propertySize != null || propertyLength != null
            ? IdentitySource.CustomProperty
            : IdentitySource.NameParse;

        RecordUnknowns(fastener, component, scope);
        ReadShankAxis(handle, model, component, scope, fastener);

        return fastener;
    }

    private static void RecordUnknowns(Fastener fastener, ScopedComponent component, DumpScope scope)
    {
        if (fastener.ThreadDesignation == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "fastener",
                fastener.Id,
                $"Neither the configuration name '{component.Node.ReferencedConfiguration}', the "
                + "description, the file name nor the configuration's custom properties gave a "
                + "thread designation.",
                null);
        }

        if (fastener.Length == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "fastener",
                fastener.Id,
                $"No under-head length could be read for '{component.Node.Key}'; "
                + "bottoming and engagement checks stay unresolved.",
                null);
        }

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "fastener",
            fastener.Id,
            "Head diameter and head height were not measured from the geometry in this build; "
            + "head and washer clearance checks need them supplied or stay unresolved.",
            null);
    }

    /// <summary>
    /// The screw axis from the largest cylindrical face on the part - the shank - using
    /// <c>CylinderParams</c> in assembly space. The direction sign is NOT forced to point
    /// from head to tip here; the surface's own axis is recorded and a Gap says so, because
    /// guessing the sign would invert an engagement calculation.
    /// </summary>
    private void ReadShankAxis(
        IComponent2 handle, IModelDoc2? model, ScopedComponent component, DumpScope scope, Fastener fastener)
    {
        if (model == null)
        {
            return;
        }

        SwGate gate = _session.Gate;
        string modelPath = gate.Call("GetPathName", () => model.GetPathName());

        var bodies = gate.Call("GetBodies2", () => handle.GetBodies2((int)swBodyType_e.swSolidBody)) as object[];
        if (bodies == null)
        {
            return;
        }

        // The shank is the largest cylindrical face on the part. Only that one face is
        // described; registering every candidate along the way would fill the IR with
        // chamfers and thread reliefs.
        IFace2? shank = null;
        double[]? shankCylinder = null;
        double bestArea = 0;

        foreach (object bodyItem in bodies)
        {
            if (!(bodyItem is IBody2 body)
                || !(gate.Call("GetFaces", () => body.GetFaces()) is object[] faces))
            {
                continue;
            }

            foreach (object faceItem in faces)
            {
                if (!(faceItem is IFace2 face))
                {
                    continue;
                }

                var surface = gate.Call("GetSurface", () => face.GetSurface()) as ISurface;
                if (surface == null || !gate.Call("IsCylinder", () => surface.IsCylinder()))
                {
                    continue;
                }

                double area = gate.Call("GetArea", () => face.GetArea());
                if (area <= bestArea
                    || !(gate.Call("CylinderParams", () => surface.CylinderParams) is double[] cylinder)
                    || cylinder.Length < 7)
                {
                    continue;
                }

                bestArea = area;
                shank = face;
                shankCylinder = cylinder;
            }
        }

        if (shank == null || shankCylinder == null)
        {
            scope.Gaps.Add(
                GapKind.NotExtracted,
                "fastener",
                fastener.Id,
                $"No cylindrical shank face was found on '{component.Node.Key}', so its axis is unknown.",
                null);
            return;
        }

        fastener.Axis = new Axis(
            SwTransform.ApplyToPoint(
                component.Node.Transform, new Vec3(shankCylinder[0], shankCylinder[1], shankCylinder[2])),
            SwTransform.ApplyToDirection(
                component.Node.Transform, new Vec3(shankCylinder[3], shankCylinder[4], shankCylinder[5])));

        scope.RequestFace(shank, component.Id, component.Node.Transform, modelPath);

        scope.Gaps.Add(
            GapKind.NotExtracted,
            "fastener",
            fastener.Id,
            "The fastener axis direction is the shank surface's own axis; "
            + "head-to-tip orientation was not determined.",
            null);
    }

    private static string? Lookup(IReadOnlyDictionary<string, string> properties, string[] names)
    {
        foreach (string name in names)
        {
            if (properties.TryGetValue(name, out string value) && !string.IsNullOrWhiteSpace(value))
            {
                return value.Trim();
            }
        }

        return null;
    }
}
