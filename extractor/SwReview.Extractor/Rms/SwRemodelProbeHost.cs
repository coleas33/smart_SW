using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// T032. The SOLIDWORKS side of <see cref="IRemodelProbeHost"/> and
/// <see cref="IRemodelToggleHost"/>: interop calls and nothing else, so every decision
/// <c>probe remodel</c> makes is testable without a seat (the same split as
/// <see cref="SwSuppressTarget"/> and <see cref="SwFeatureReader"/>).
///
/// Building <see cref="RemodelProbePartRecipe.Default"/>'s seven steps is the one part of this
/// class Phase 2's own probes exist to check: whether <c>FeatureFillet3</c>,
/// <c>InsertFeatureChamfer</c>, <c>InsertFeatureShell</c> and
/// <c>InsertFeatureTreeFolder2</c> behave as their signatures promise on SOLIDWORKS 2024 SP5
/// is UNVERIFIED (research.md R10) - that is exactly what PROBE-3, 4, 5, 9, 10, 11 and 20
/// measure once their bodies land (tasks.md T033 to T038). This class is a best-effort,
/// well-documented first construction for those probes to run against, not a claim that the
/// geometry it builds is correct; every dimension is a round, arbitrary number chosen only so
/// the recipe rebuilds cleanly.
///
/// Every mutating call is routed through <see cref="RemodelProbeGate"/>'s gate, exactly as
/// <see cref="SwSuppressTarget"/> routes its two. Nothing here ever addresses a document this
/// class did not itself create with <see cref="ISldWorks.NewDocument"/>.
/// </summary>
public sealed class SwRemodelProbeHost : IRemodelProbeHost, IRemodelToggleHost
{
    /// <summary>
    /// The interop members this class names to the gate. One place, so the guard, the
    /// observer and the tests cannot drift from the call sites - the same reason
    /// <c>SuppressTest.Member</c> exists.
    /// </summary>
    internal static class Member
    {
        public const string FirstDocument = "GetFirstDocument";
        public const string RevisionNumber = "RevisionNumber";
        public const string TemplatePath = "GetUserPreferenceStringValue";
        public const string NewDocument = "NewDocument";
        public const string SelectByID2 = "SelectByID2";
        public const string InsertSketch = "InsertSketch";
        public const string CreateCornerRectangle = "CreateCornerRectangle";
        public const string FeatureExtrusion3 = "FeatureExtrusion3";
        public const string FeatureCut4 = "FeatureCut4";
        public const string FeatureFillet3 = "FeatureFillet3";
        public const string InsertFeatureChamfer = "InsertFeatureChamfer";
        public const string InsertFeatureShell = "InsertFeatureShell";
        public const string InsertFeatureTreeFolder2 = "InsertFeatureTreeFolder2";
        public const string GetEquationMgr = "GetEquationMgr";
        public const string AddEquation = "Add3";
        public const string ForceRebuild3 = "ForceRebuild3";
        public const string SaveAs3 = "SaveAs3";
        public const string CloseDoc = "CloseDoc";
        public const string GetBodies2 = "GetBodies2";
        public const string GetEdges = "GetEdges";
        public const string GetFaces = "GetFaces";
        public const string Select4 = "Select4";
        public const string Select2 = "Select2";
        public const string SetName = "set_Name";
        public const string FirstFeature = "FirstFeature";
        public const string NextFeature = "GetNextFeature";
        public const string ClearSelection2 = "ClearSelection2";
    }

    /// <summary>The box footprint, in metres: 100 mm x 60 mm.</summary>
    private const double BoxWidth = 0.1;
    private const double BoxDepthY = 0.06;

    /// <summary>The extrusion depth, in metres: 40 mm.</summary>
    private const double BoxHeight = 0.04;

    /// <summary>The pocket cut's footprint and depth, in metres.</summary>
    private const double CutWidth = 0.03;
    private const double CutDepthY = 0.02;
    private const double CutDepth = 0.01;

    /// <summary>The fillet radius and chamfer distance, in metres: 3 mm each.</summary>
    private const double FilletRadius = 0.003;
    private const double ChamferDistance = 0.003;

    /// <summary>The shell wall thickness, in metres: 2 mm.</summary>
    private const double ShellThickness = 0.002;

    private readonly ISldWorks _swApp;
    private readonly SwGate _gate;

    public SwRemodelProbeHost(ISldWorks swApp, SwGate gate)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
    }

    /// <inheritdoc />
    public bool AnyDocumentOpen() =>
        _gate.Call(Member.FirstDocument, () => _swApp.GetFirstDocument()) != null;

    /// <inheritdoc />
    public string SwVersion() =>
        _gate.Call(Member.RevisionNumber, () => _swApp.RevisionNumber()) ?? string.Empty;

    /// <inheritdoc />
    public RemodelProbePart BuildPart(RemodelProbePartRecipe recipe, string savePath)
    {
        if (recipe == null)
        {
            throw new ArgumentNullException(nameof(recipe));
        }

        if (string.IsNullOrWhiteSpace(savePath))
        {
            throw new ArgumentException("A save path is required.", nameof(savePath));
        }

        string template = _gate.Call(
            Member.TemplatePath,
            () => _swApp.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart));

        object newDocument = _gate.Call(Member.NewDocument, () => _swApp.NewDocument(template, 0, 0, 0));
        if (!(newDocument is IModelDoc2 document))
        {
            throw new InvalidOperationException(
                "ISldWorks.NewDocument returned no part document; probe remodel has nothing to "
                + "build the throwaway part's recipe onto. Check --out names a template part "
                + "and that swDefaultTemplatePart is configured in this SOLIDWORKS session.");
        }

        var features = new List<object>(recipe.Steps.Count);
        var byName = new Dictionary<string, object>(StringComparer.Ordinal);

        foreach (RemodelProbeFeatureStep step in recipe.Steps)
        {
            object feature = BuildStep(document, step, byName);
            features.Add(feature);

            // The recipe deliberately gives the fillet and the chamfer the same name
            // (RemodelProbePartRecipe.Default), so this dictionary intentionally keeps only
            // the LAST feature seen under a shared name; RemodelProbePart.Features is the
            // ordered list every probe body actually walks.
            byName[step.Name] = feature;
        }

        int saveErrors = 0;
        int saveWarnings = 0;
        bool saved = _gate.Call(Member.SaveAs3, () =>
            document.Extension.SaveAs3(savePath, 0, 0, null, null, ref saveErrors, ref saveWarnings));
        if (!saved)
        {
            throw new InvalidOperationException(
                $"SaveAs3 could not write the throwaway part to '{savePath}'.");
        }

        return new RemodelProbePart(document, savePath, features);
    }

    /// <inheritdoc />
    public void ClosePart(RemodelProbePart part)
    {
        if (part == null)
        {
            throw new ArgumentNullException(nameof(part));
        }

        // ISldWorks.CloseDoc takes the document's saved path, the same way
        // IRemodelSeat.CloseDocument(documentPath) already addresses "the tagged copy only"
        // elsewhere in this product - never a window title. BuildPart already confirmed
        // SaveAs3 wrote part.Path, so that is the name SOLIDWORKS knows this document by.
        _gate.Call(Member.CloseDoc, () => _swApp.CloseDoc(part.Path));
    }

    /// <inheritdoc />
    public bool GetUserPreferenceToggle(int toggle) => _swApp.GetUserPreferenceToggle(toggle);

    /// <inheritdoc />
    public void SetUserPreferenceToggle(int toggle, bool value) =>
        _swApp.SetUserPreferenceToggle(toggle, value);

    /// <inheritdoc />
    public bool GetCommandInProgress() => _swApp.CommandInProgress;

    /// <inheritdoc />
    public void SetCommandInProgress(bool value) => _swApp.CommandInProgress = value;

    private object BuildStep(
        IModelDoc2 document, RemodelProbeFeatureStep step, IReadOnlyDictionary<string, object> byName)
    {
        object feature;
        switch (step.Kind)
        {
            case RemodelProbeFeatureKind.Box:
                feature = BuildBox(document);
                break;
            case RemodelProbeFeatureKind.Cut:
                feature = BuildCut(document);
                break;
            case RemodelProbeFeatureKind.Fillet:
                feature = BuildFillet(document);
                break;
            case RemodelProbeFeatureKind.Chamfer:
                feature = BuildChamfer(document);
                break;
            case RemodelProbeFeatureKind.Shell:
                feature = BuildShell(document);
                break;
            case RemodelProbeFeatureKind.Folder:
                feature = BuildFolder(document, step, byName);
                break;
            case RemodelProbeFeatureKind.Equation:
                feature = BuildEquation(document, step);
                break;
            default:
                throw new ArgumentOutOfRangeException(
                    nameof(step), step.Kind, "Unknown recipe feature kind.");
        }

        if (feature is IFeature named)
        {
            _gate.Call(Member.SetName, () => named.Name = step.Name);
        }

        Rebuild(document);
        return feature;
    }

    private object BuildBox(IModelDoc2 document)
    {
        SelectFrontPlane(document);
        ISketchManager sketchManager = document.SketchManager;
        _gate.Call(Member.InsertSketch, () => sketchManager.InsertSketch(true));
        _gate.Call(
            Member.CreateCornerRectangle,
            () => sketchManager.CreateCornerRectangle(0, 0, 0, BoxWidth, BoxDepthY, 0));
        _gate.Call(Member.InsertSketch, () => sketchManager.InsertSketch(true));

        IFeatureManager featureManager = document.FeatureManager;
        return _gate.Call(Member.FeatureExtrusion3, () => featureManager.FeatureExtrusion3(
            true, false, false,
            (int)swEndConditions_e.swEndCondBlind, 0,
            BoxHeight, 0.0,
            false, false, false, false,
            0.0, 0.0,
            false, false, false, false,
            true, true, false,
            0, 0.0, false));
    }

    private object BuildCut(IModelDoc2 document)
    {
        SelectFrontPlane(document);
        ISketchManager sketchManager = document.SketchManager;
        _gate.Call(Member.InsertSketch, () => sketchManager.InsertSketch(true));
        _gate.Call(
            Member.CreateCornerRectangle,
            () => sketchManager.CreateCornerRectangle(0, 0, 0, CutWidth, CutDepthY, 0));
        _gate.Call(Member.InsertSketch, () => sketchManager.InsertSketch(true));

        IFeatureManager featureManager = document.FeatureManager;
        return _gate.Call(Member.FeatureCut4, () => featureManager.FeatureCut4(
            true, false, false,
            (int)swEndConditions_e.swEndCondBlind, 0,
            CutDepth, 0.0,
            false, false, false, false,
            0.0, 0.0,
            false, false, false, false,
            false, true, false, false, false, false,
            0, 0.0, false, false));
    }

    private object BuildFillet(IModelDoc2 document)
    {
        SelectFirstEdge(document);
        IFeatureManager featureManager = document.FeatureManager;
        return _gate.Call(Member.FeatureFillet3, () => featureManager.FeatureFillet3(
            0, FilletRadius, 0.0, 0.0,
            (int)swFeatureFilletType_e.swFeatureFilletType_Simple,
            0, 0, null, null, null, null, null, null, null));
    }

    private object BuildChamfer(IModelDoc2 document)
    {
        SelectFirstEdge(document);
        IFeatureManager featureManager = document.FeatureManager;
        return _gate.Call(Member.InsertFeatureChamfer, () => featureManager.InsertFeatureChamfer(
            0, (int)swChamferType_e.swChamferEqualDistance,
            ChamferDistance, 0.0, 0.0, 0.0, 0.0, 0.0));
    }

    private object BuildShell(IModelDoc2 document)
    {
        SelectFirstFace(document);
        _gate.Call(Member.InsertFeatureShell, () => document.InsertFeatureShell(ShellThickness, true));

        // InsertFeatureShell (an IModelDoc2 method, not an IFeatureManager one - see
        // contracts/interop-manifest.md's documented absence of a *Shell* creator on
        // IFeatureManager) answers void, so the new feature is read off the tree instead of a
        // return value.
        return LastFeature(document);
    }

    private object BuildFolder(
        IModelDoc2 document, RemodelProbeFeatureStep step, IReadOnlyDictionary<string, object> byName)
    {
        _gate.Call(Member.ClearSelection2, () => document.ClearSelection2(true));

        bool append = false;
        foreach (string memberName in step.FolderMembers)
        {
            if (!byName.TryGetValue(memberName, out object? member) || !(member is IFeature feature))
            {
                throw new InvalidOperationException(
                    $"The recipe's folder step names '{memberName}', which was not built "
                    + "before the folder step ran.");
            }

            bool selected = append
                ? _gate.Call(Member.Select2, () => feature.Select2(true, 0))
                : _gate.Call(Member.Select2, () => feature.Select2(false, 0));

            if (!selected)
            {
                throw new InvalidOperationException(
                    $"'{memberName}' could not be selected for the recipe's folder.");
            }

            append = true;
        }

        IFeatureManager featureManager = document.FeatureManager;
        return _gate.Call(
            Member.InsertFeatureTreeFolder2,
            () => featureManager.InsertFeatureTreeFolder2(
                (int)swFeatureTreeFolderType_e.swFeatureTreeFolder_Containing));
    }

    private object BuildEquation(IModelDoc2 document, RemodelProbeFeatureStep step)
    {
        var manager = _gate.Call(Member.GetEquationMgr, () => document.GetEquationMgr()) as IEquationMgr;

        if (manager == null)
        {
            throw new InvalidOperationException(
                "GetEquationMgr returned nothing; the recipe's equation step could not run.");
        }

        _gate.Call(Member.AddEquation, () => manager.Add3(
            -1, step.EquationText, true, (int)swInConfigurationOpts_e.swAllConfiguration, null));

        // Equations are not IFeature: nothing is added to the feature tree, so the recipe's
        // per-step rename and rebuild both no-op harmlessly for this step (RemodelProbeFeatureStep
        // still names it "w" for the ledger and for a probe body that reads the equation back).
        return manager;
    }

    /// <summary>The most recently added feature: <c>FirstFeature</c> walked to its end.</summary>
    private object LastFeature(IModelDoc2 document)
    {
        object? current = _gate.Call(Member.FirstFeature, () => document.FirstFeature());
        object? last = current;
        while (current is IFeature feature)
        {
            object? next = _gate.Call(Member.NextFeature, () => feature.GetNextFeature());
            if (next == null)
            {
                break;
            }

            last = next;
            current = next;
        }

        return last ?? throw new InvalidOperationException(
            "The feature tree is empty; the shell step ran before anything was built.");
    }

    /// <summary>The part's first solid body, or a named failure - shared by the edge and face pickers below.</summary>
    private IBody2 FirstSolidBody(IModelDoc2 document, string forStep)
    {
        var part = (IPartDoc)document;
        object bodies = _gate.Call(
            Member.GetBodies2, () => part.GetBodies2((int)swBodyType_e.swSolidBody, true));

        if (!(FirstElement(bodies) is IBody2 body))
        {
            throw new InvalidOperationException($"The part has no solid body yet; {forStep}.");
        }

        return body;
    }

    /// <summary>Selects the first edge of the part's first solid body, for a fillet or a chamfer.</summary>
    private void SelectFirstEdge(IModelDoc2 document)
    {
        _gate.Call(Member.ClearSelection2, () => document.ClearSelection2(true));
        IBody2 body = FirstSolidBody(document, "a fillet or a chamfer cannot select an edge");

        object edges = _gate.Call(Member.GetEdges, () => body.GetEdges());
        if (!(FirstElement(edges) is IEdge edge))
        {
            throw new InvalidOperationException("The body reported no edges to fillet or chamfer.");
        }

        bool selected = _gate.Call(Member.Select4, () => ((IEntity)edge).Select4(false, null));
        if (!selected)
        {
            throw new InvalidOperationException("The chosen edge could not be selected.");
        }
    }

    /// <summary>Selects the first face of the part's first solid body, for the shell.</summary>
    private void SelectFirstFace(IModelDoc2 document)
    {
        _gate.Call(Member.ClearSelection2, () => document.ClearSelection2(true));
        IBody2 body = FirstSolidBody(document, "the shell step cannot select a face");

        object faces = _gate.Call(Member.GetFaces, () => body.GetFaces());
        if (!(FirstElement(faces) is IFace2 face))
        {
            throw new InvalidOperationException("The body reported no faces to shell.");
        }

        bool selected = _gate.Call(Member.Select4, () => ((IEntity)face).Select4(false, null));
        if (!selected)
        {
            throw new InvalidOperationException("The chosen face could not be selected.");
        }
    }

    /// <summary>
    /// The first element of a SAFEARRAY interop hands back as <c>object</c>, or null for an
    /// empty or absent one. Interop marshals these as <c>object[]</c>, a concrete element-type
    /// array, or occasionally nothing at all depending on the member and the build, so this
    /// reads through <see cref="Array"/> rather than casting to one shape - the same reasoning
    /// <c>SwSuppressTarget.Items</c> already applies to <c>GetWhatsWrong</c>'s three arrays.
    /// </summary>
    private static object? FirstElement(object? arrayLike) =>
        arrayLike is Array array && array.Length > 0 ? array.GetValue(0) : null;

    /// <summary>Selects "Front Plane" by name - every recipe step sketches on the same plane.</summary>
    private void SelectFrontPlane(IModelDoc2 document)
    {
        IModelDocExtension extension = document.Extension;
        bool selected = _gate.Call(
            Member.SelectByID2,
            () => extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, false, 0, null, 0));

        if (!selected)
        {
            throw new InvalidOperationException(
                "'Front Plane' could not be selected on the throwaway part's template.");
        }
    }

    private void Rebuild(IModelDoc2 document)
    {
        bool rebuilt = _gate.Call(Member.ForceRebuild3, () => document.ForceRebuild3(false));
        if (!rebuilt)
        {
            throw new InvalidOperationException(
                "ForceRebuild3 returned false while building the throwaway part's recipe.");
        }
    }
}
