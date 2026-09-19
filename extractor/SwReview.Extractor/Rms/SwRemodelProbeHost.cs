using System;
using System.Collections.Generic;
using System.Linq;
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

        // ---- T033 to T039: the fifteen probe bodies' own interop members ----------------

        public const string GetName = "get_Name";
        public const string GetTypeName2 = "GetTypeName2";
        public const string GetDescription = "get_Description";
        public const string SetDescription = "set_Description";
        public const string ReorderFeature = "ReorderFeature";
        public const string MoveToFolder = "MoveToFolder";
        public const string MakeSubFeature = "MakeSubFeature";
        public const string EquationGetCount = "GetCount";
        public const string EquationGetEquationText = "get_Equation";
        public const string EquationAdd2 = "Add2";
        public const string EquationSetEquation = "set_Equation";
        public const string EquationSetEquationAndConfigurationOption = "SetEquationAndConfigurationOption";
        public const string EquationDelete = "Delete";
        public const string EquationGetValue = "get_Value";
        public const string SetSuppression2 = "SetSuppression2";
        public const string GetWhatsWrongCount = "GetWhatsWrongCount";
        public const string GetWhatsWrong = "GetWhatsWrong";
        public const string GetCustomPropertyManager = "get_CustomPropertyManager";
        public const string CustomPropertyAdd3 = "Add3";
        public const string CustomPropertyGet4 = "Get4";
        public const string GetOpenDocSpec = "GetOpenDocSpec";
        public const string OpenDoc7 = "OpenDoc7";
        public const string GetTitle = "GetTitle";
        public const string CreateCenterRectangle = "CreateCenterRectangle";
        public const string CreateCircleByRadius = "CreateCircleByRadius";
        public const string CreateMassProperty2 = "CreateMassProperty2";
        public const string MassPropertySetAccuracyLevel = "set_AccuracyLevel";
        public const string MassPropertySetSelectedItems = "set_SelectedItems";
        public const string MassPropertySetUseSystemUnits = "set_UseSystemUnits";
        public const string MassPropertyRecalculate = "Recalculate";
        public const string MassPropertyGetVolume = "get_Volume";
        public const string MassPropertyGetSurfaceArea = "get_SurfaceArea";
        public const string MassPropertyGetCenterOfMass = "get_CenterOfMass";
        public const string MassPropertyGetPrincipalMoments = "get_PrincipalMomentsOfInertia";
        public const string MassPropertyGetMass = "get_Mass";
        public const string MassPropertyGetDensity = "get_Density";
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
    public bool ReorderFeature(RemodelProbePart part, string featureToMove, string targetFeature, int location) =>
        _gate.Call(Member.ReorderFeature, () => Document(part).Extension.ReorderFeature(featureToMove, targetFeature, location));

    /// <inheritdoc />
    public IReadOnlyList<string> GetFeatureNames(RemodelProbePart part)
    {
        var names = new List<string>();
        object? current = _gate.Call(Member.FirstFeature, () => Document(part).FirstFeature());
        while (current is IFeature feature)
        {
            names.Add(_gate.Call(Member.GetName, () => feature.Name));
            current = _gate.Call(Member.NextFeature, () => feature.GetNextFeature());
        }

        return names;
    }

    /// <inheritdoc />
    public string? GetFeatureTypeName(RemodelProbePart part, string featureName)
    {
        IFeature? feature = FindFeatureByName(Document(part), featureName);
        return feature == null ? null : _gate.Call(Member.GetTypeName2, () => feature.GetTypeName2());
    }

    /// <inheritdoc />
    public string? GetFeatureDescription(RemodelProbePart part, string featureName)
    {
        IFeature? feature = FindFeatureByName(Document(part), featureName);
        return feature == null ? null : _gate.Call(Member.GetDescription, () => feature.Description);
    }

    /// <inheritdoc />
    public void SetFeatureDescription(RemodelProbePart part, string featureName, string text)
    {
        IFeature feature = RequireFeature(Document(part), featureName);
        _gate.Call(Member.SetDescription, () => feature.Description = text);
    }

    /// <inheritdoc />
    public void SetFeatureName(RemodelProbePart part, string currentName, string newName)
    {
        IFeature feature = RequireFeature(Document(part), currentName);
        _gate.Call(Member.SetName, () => feature.Name = newName);
    }

    /// <inheritdoc />
    public object? TryInsertFeatureTreeFolder(RemodelProbePart part, IReadOnlyList<string> memberNames)
    {
        if (memberNames == null || memberNames.Count == 0)
        {
            throw new ArgumentException("At least one member name is required.", nameof(memberNames));
        }

        IModelDoc2 document = Document(part);
        _gate.Call(Member.ClearSelection2, () => document.ClearSelection2(true));

        bool append = false;
        foreach (string name in memberNames)
        {
            IFeature? feature = FindFeatureByName(document, name);
            if (feature == null)
            {
                return null;
            }

            bool selected = _gate.Call(Member.Select2, () => feature.Select2(append, 0));
            if (!selected)
            {
                return null;
            }

            append = true;
        }

        return _gate.Call(
            Member.InsertFeatureTreeFolder2,
            () => document.FeatureManager.InsertFeatureTreeFolder2(
                (int)swFeatureTreeFolderType_e.swFeatureTreeFolder_Containing));
    }

    /// <inheritdoc />
    public bool MoveToFolder(RemodelProbePart part, string moveToFeatureOrFolder, string moveFromFeature, bool isFolder) =>
        _gate.Call(
            Member.MoveToFolder,
            () => Document(part).FeatureManager.MoveToFolder(moveToFeatureOrFolder, moveFromFeature, isFolder));

    /// <inheritdoc />
    public bool MakeSubFeature(RemodelProbePart part, string parentFeatureName, string subFeatureName)
    {
        IModelDoc2 document = Document(part);
        IFeature parent = RequireFeature(document, parentFeatureName);
        IFeature sub = RequireFeature(document, subFeatureName);

        // IFeature.MakeSubFeature's own parameter is typed Feature (the interop coclass
        // interface), not IFeature; the cast is safe because every IFeature this class ever
        // hands back is the same underlying COM object, which implements both.
        return _gate.Call(Member.MakeSubFeature, () => parent.MakeSubFeature((Feature)sub));
    }

    /// <inheritdoc />
    public IEquationTarget GetEquationManager(RemodelProbePart part)
    {
        var manager = _gate.Call(Member.GetEquationMgr, () => Document(part).GetEquationMgr());
        if (manager == null)
        {
            throw new InvalidOperationException("GetEquationMgr returned nothing for the throwaway part.");
        }

        return new SwEquationTarget(_gate, manager);
    }

    /// <inheritdoc />
    public double GetEquationValue(RemodelProbePart part, int index)
    {
        var manager = _gate.Call(Member.GetEquationMgr, () => Document(part).GetEquationMgr());
        if (manager == null)
        {
            throw new InvalidOperationException("GetEquationMgr returned nothing for the throwaway part.");
        }

        return _gate.Call(Member.EquationGetValue, () => manager.get_Value(index));
    }

    /// <inheritdoc />
    public bool SetFeatureSuppression(RemodelProbePart part, string featureName, bool suppress)
    {
        IFeature feature = RequireFeature(Document(part), featureName);
        return _gate.Call(Member.SetSuppression2, () => feature.SetSuppression2(
            (int)(suppress ? swFeatureSuppressionAction_e.swSuppressFeature : swFeatureSuppressionAction_e.swUnSuppressFeature),
            (int)swInConfigurationOpts_e.swThisConfiguration,
            null));
    }

    /// <inheritdoc />
    public bool ForceRebuild(RemodelProbePart part) =>
        _gate.Call(Member.ForceRebuild3, () => Document(part).ForceRebuild3(false));

    /// <inheritdoc />
    public RemodelWhatsWrongReading ReadWhatsWrong(RemodelProbePart part)
    {
        IModelDoc2 document = Document(part);
        int count = _gate.Call(Member.GetWhatsWrongCount, () => document.Extension.GetWhatsWrongCount());

        object? features = null;
        object? errorCodes = null;
        object? warnings = null;
        bool callSucceeded = _gate.Call(
            Member.GetWhatsWrong,
            () => document.Extension.GetWhatsWrong(out features, out errorCodes, out warnings));

        return new RemodelWhatsWrongReading(count, callSucceeded, DescribeWhatsWrongElementKind(features));
    }

    /// <inheritdoc />
    public int AddCustomProperty(RemodelProbePart part, string key, string value)
    {
        ICustomPropertyManager manager = CustomPropertyManager(part);
        return _gate.Call(Member.CustomPropertyAdd3, () => manager.Add3(
            key,
            (int)swCustomInfoType_e.swCustomInfoText,
            value,
            (int)swCustomPropertyAddOption_e.swCustomPropertyReplaceValue));
    }

    /// <inheritdoc />
    public bool GetCustomProperty(RemodelProbePart part, string key, out string? value, out string? resolvedValue)
    {
        ICustomPropertyManager manager = CustomPropertyManager(part);
        string readValue = string.Empty;
        string readResolvedValue = string.Empty;
        bool found = _gate.Call(
            Member.CustomPropertyGet4, () => manager.Get4(key, false, out readValue, out readResolvedValue));

        value = found ? readValue : null;
        resolvedValue = found ? readResolvedValue : null;
        return found;
    }

    /// <inheritdoc />
    public bool SaveExistingPart(RemodelProbePart part)
    {
        IModelDoc2 document = Document(part);
        int saveErrors = 0;
        int saveWarnings = 0;
        return _gate.Call(Member.SaveAs3, () =>
            document.Extension.SaveAs3(part.Path, 0, 0, null, null, ref saveErrors, ref saveWarnings));
    }

    /// <inheritdoc />
    public RemodelProbePart ReopenPart(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("A path is required.", nameof(path));
        }

        object specObject = _gate.Call(Member.GetOpenDocSpec, () => _swApp.GetOpenDocSpec(path));
        if (!(specObject is IDocumentSpecification spec))
        {
            throw new InvalidOperationException($"GetOpenDocSpec returned nothing for '{path}'.");
        }

        // Silent | LoadModel = 17 (research R2.4), and never ReadOnly or ViewOnly - the same
        // composition stage 1's own open sequence requires. These are plain property sets on a
        // throwaway request object, not a call against the engineer's SOLIDWORKS session, so
        // they are not routed through the gate; OpenDoc7 itself is.
        spec.Silent = true;
        spec.LoadModel = true;
        spec.ReadOnly = false;
        spec.ViewOnly = false;

        object opened = _gate.Call(Member.OpenDoc7, () => _swApp.OpenDoc7(spec));
        if (!(opened is IModelDoc2 document))
        {
            throw new InvalidOperationException($"OpenDoc7 could not reopen '{path}'.");
        }

        return new RemodelProbePart(document, path, Array.Empty<object>());
    }

    /// <inheritdoc />
    public object BuildBlankDocument()
    {
        string template = _gate.Call(
            Member.TemplatePath,
            () => _swApp.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart));

        object newDocument = _gate.Call(Member.NewDocument, () => _swApp.NewDocument(template, 0, 0, 0));
        if (!(newDocument is IModelDoc2 document))
        {
            throw new InvalidOperationException(
                "ISldWorks.NewDocument returned no part document for PROBE-21's blank part.");
        }

        return document;
    }

    /// <inheritdoc />
    public int GetEquationCount(object blankDocument)
    {
        IModelDoc2 document = RequireBlankDocument(blankDocument);
        var manager = _gate.Call(Member.GetEquationMgr, () => document.GetEquationMgr());
        if (manager == null)
        {
            throw new InvalidOperationException("GetEquationMgr returned nothing for PROBE-21's blank part.");
        }

        return _gate.Call(Member.EquationGetCount, () => manager.GetCount());
    }

    /// <inheritdoc />
    public void DiscardBlankDocument(object blankDocument)
    {
        IModelDoc2 document = RequireBlankDocument(blankDocument);
        string title = _gate.Call(Member.GetTitle, () => document.GetTitle());
        _gate.Call(Member.CloseDoc, () => _swApp.CloseDoc(title));
    }

    /// <inheritdoc />
    public RemodelProbePart BuildAnalyticSolid(AnalyticSolidSpec spec, string savePath)
    {
        if (spec == null)
        {
            throw new ArgumentNullException(nameof(spec));
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
                "ISldWorks.NewDocument returned no part document for PROBE-8's analytic solid.");
        }

        SelectFrontPlane(document);
        ISketchManager sketchManager = document.SketchManager;
        _gate.Call(Member.InsertSketch, () => sketchManager.InsertSketch(true));

        if (spec.IsBox)
        {
            // A rectangle centred on the origin, half-width and half-depth from it, so the
            // extruded box's centroid lands at (0, 0, 0) regardless of Front Plane's axis
            // mapping (AnalyticSolidSpec's own remarks).
            double halfWidth = spec.Dimension1 / 2.0;
            double halfDepth = spec.Dimension2 / 2.0;
            _gate.Call(
                Member.CreateCenterRectangle,
                () => sketchManager.CreateCenterRectangle(0, 0, 0, halfWidth, halfDepth, 0));
        }
        else
        {
            _gate.Call(Member.CreateCircleByRadius, () => sketchManager.CreateCircleByRadius(0, 0, 0, spec.Dimension1));
        }

        _gate.Call(Member.InsertSketch, () => sketchManager.InsertSketch(true));

        IFeatureManager featureManager = document.FeatureManager;

        // T1 = swEndCondMidPlane, D1 = the full height: SOLIDWORKS splits a mid-plane extrude
        // symmetrically about the sketch plane, which is what centres the solid on the origin
        // along the extrude direction too. If the workstation run's attained volume error comes
        // back near 100% rather than near zero, that is the signature of D1 meaning "half the
        // depth" instead on this build, and Height should be halved here to compensate.
        object feature = _gate.Call(Member.FeatureExtrusion3, () => featureManager.FeatureExtrusion3(
            true, false, false,
            (int)swEndConditions_e.swEndCondMidPlane, 0,
            spec.Height, 0.0,
            false, false, false, false,
            0.0, 0.0,
            false, false, false, false,
            true, true, false,
            0, 0.0, false));

        bool rebuilt = _gate.Call(Member.ForceRebuild3, () => document.ForceRebuild3(false));
        if (!rebuilt)
        {
            throw new InvalidOperationException("ForceRebuild3 returned false while building PROBE-8's analytic solid.");
        }

        int saveErrors = 0;
        int saveWarnings = 0;
        bool saved = _gate.Call(Member.SaveAs3, () =>
            document.Extension.SaveAs3(savePath, 0, 0, null, null, ref saveErrors, ref saveWarnings));
        if (!saved)
        {
            throw new InvalidOperationException($"SaveAs3 could not write PROBE-8's analytic solid to '{savePath}'.");
        }

        return new RemodelProbePart(document, savePath, new[] { feature });
    }

    /// <inheritdoc />
    public IMassPropertyReading? MeasureMassProperties(RemodelProbePart part)
    {
        IModelDoc2 document = Document(part);
        IBody2 body = FirstSolidBody(document, "PROBE-8 needs a solid body to measure");

        object created = _gate.Call(Member.CreateMassProperty2, () => document.Extension.CreateMassProperty2());
        if (!(created is IMassProperty2 massProperty))
        {
            return null;
        }

        var reading = new SwMassPropertyReading(_gate, massProperty);
        reading.SetSelectedItems(new object[] { body });
        return reading;
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

    // ---- T033 to T039: shared plumbing every probe body's host member uses ------------

    /// <summary><paramref name="part"/>'s document, cast back from the opaque handle it crossed the seam as.</summary>
    private static IModelDoc2 Document(RemodelProbePart part)
    {
        if (part == null)
        {
            throw new ArgumentNullException(nameof(part));
        }

        return part.Document as IModelDoc2
            ?? throw new InvalidOperationException("RemodelProbePart.Document is not an IModelDoc2.");
    }

    /// <summary>
    /// <paramref name="blankDocument"/>, cast back from the opaque handle
    /// <see cref="BuildBlankDocument"/> returned. A wrong-typed argument here is a caller
    /// mistake (PROBE-21 is the one caller), not a SOLIDWORKS answer, so it throws
    /// <see cref="ArgumentException"/> rather than joining the gate's own failure modes.
    /// </summary>
    private static IModelDoc2 RequireBlankDocument(object blankDocument) =>
        blankDocument as IModelDoc2
            ?? throw new ArgumentException(
                "blankDocument was not returned by BuildBlankDocument.", nameof(blankDocument));

    /// <summary>
    /// The first feature named <paramref name="name"/>, walked fresh from
    /// <c>IModelDoc2.FirstFeature()</c>. Two recipe features share a name by construction
    /// (<see cref="RemodelProbePartRecipe.Default"/>); this resolves to whichever one the tree
    /// walk reaches first, exactly as SOLIDWORKS's own name-addressed APIs would, rather than
    /// disambiguating on this class's behalf.
    /// </summary>
    private IFeature? FindFeatureByName(IModelDoc2 document, string name)
    {
        object? current = _gate.Call(Member.FirstFeature, () => document.FirstFeature());
        while (current is IFeature feature)
        {
            string? featureName = _gate.Call(Member.GetName, () => feature.Name);
            if (string.Equals(featureName, name, StringComparison.Ordinal))
            {
                return feature;
            }

            current = _gate.Call(Member.NextFeature, () => feature.GetNextFeature());
        }

        return null;
    }

    /// <summary><see cref="FindFeatureByName"/>, or a named failure instead of a null a caller would have to check for.</summary>
    private IFeature RequireFeature(IModelDoc2 document, string name) =>
        FindFeatureByName(document, name)
            ?? throw new InvalidOperationException($"'{name}' was not found in the throwaway part's tree.");

    /// <summary>
    /// <c>IModelDocExtension.get_CustomPropertyManager("")</c> (VERIFIED): the document-level
    /// property set, never a configuration-specific one. PROBE-12.
    /// </summary>
    private ICustomPropertyManager CustomPropertyManager(RemodelProbePart part)
    {
        IModelDoc2 document = Document(part);
        var manager = _gate.Call(
            Member.GetCustomPropertyManager, () => document.Extension.get_CustomPropertyManager(string.Empty));

        if (manager == null)
        {
            throw new InvalidOperationException("get_CustomPropertyManager returned nothing.");
        }

        return manager;
    }

    /// <summary>
    /// PROBE-9's own question, decided from the runtime type of <c>GetWhatsWrong</c>'s
    /// <c>Features</c> array first element: a name, a live <c>IFeature</c>, or - "unrecognised
    /// gives unresolved rather than a guess" - anything else, described rather than assumed.
    /// </summary>
    private static string DescribeWhatsWrongElementKind(object? featuresArrayLike)
    {
        if (!(featuresArrayLike is Array array) || array.Length == 0)
        {
            return "empty";
        }

        object? first = array.GetValue(0);
        if (first is string)
        {
            return "feature_names";
        }

        if (first is IFeature)
        {
            return "feature_objects";
        }

        return "unknown:" + (first?.GetType().Name ?? "null");
    }
}

/// <summary>
/// <see cref="IEquationTarget"/> over a real <c>IEquationMgr</c> (PROBE-2, 6, 7 and 21). Every
/// member routes through the same gate every other interop call on this host does.
/// </summary>
internal sealed class SwEquationTarget : IEquationTarget
{
    private readonly SwGate _gate;
    private readonly IEquationMgr _manager;

    public SwEquationTarget(SwGate gate, IEquationMgr manager)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _manager = manager ?? throw new ArgumentNullException(nameof(manager));
    }

    public int GetCount() => _gate.Call(SwRemodelProbeHost.Member.EquationGetCount, () => _manager.GetCount());

    public string? GetEquation(int index) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationGetEquationText, () => _manager.get_Equation(index));

    public int Add3(int index, string equation, bool solve, int whichConfigurations, string[]? configNames) =>
        _gate.Call(
            SwRemodelProbeHost.Member.AddEquation,
            () => _manager.Add3(index, equation, solve, whichConfigurations, configNames));

    public int Add2(int index, string equation, bool solve) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationAdd2, () => _manager.Add2(index, equation, solve));

    public void SetEquation(int index, string equation) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationSetEquation, () => _manager.set_Equation(index, equation));

    public int SetEquationAndConfigurationOption(
        int index, string equation, int whichConfigurations, string[]? configNames) =>
        _gate.Call(
            SwRemodelProbeHost.Member.EquationSetEquationAndConfigurationOption,
            () => _manager.SetEquationAndConfigurationOption(index, equation, whichConfigurations, configNames));

    public int Delete(int index) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationDelete, () => _manager.Delete(index));
}

/// <summary>
/// <see cref="IMassPropertyReading"/> over a real <c>IMassProperty2</c> (PROBE-8). The same
/// typed interface <c>RemodelGeometry.Read</c> addresses the stage-1 gate's mass property
/// through - PROBE-8 measures with the identical member sequence, not a probe-only shortcut.
/// </summary>
internal sealed class SwMassPropertyReading : IMassPropertyReading
{
    private readonly SwGate _gate;
    private readonly IMassProperty2 _massProperty;

    public SwMassPropertyReading(SwGate gate, IMassProperty2 massProperty)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _massProperty = massProperty ?? throw new ArgumentNullException(nameof(massProperty));
    }

    public void SetAccuracyLevel(int accuracyLevel) =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertySetAccuracyLevel, () => _massProperty.AccuracyLevel = accuracyLevel);

    public void SetSelectedItems(IReadOnlyList<object> bodies) =>
        _gate.Call(
            SwRemodelProbeHost.Member.MassPropertySetSelectedItems,
            () => _massProperty.SelectedItems = bodies.ToArray());

    public void SetUseSystemUnits(bool useSystemUnits) =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertySetUseSystemUnits, () => _massProperty.UseSystemUnits = useSystemUnits);

    public bool Recalculate() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyRecalculate, () => _massProperty.Recalculate());

    public double GetVolume() => _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetVolume, () => _massProperty.Volume);

    public double GetSurfaceArea() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetSurfaceArea, () => _massProperty.SurfaceArea);

    public IReadOnlyList<double>? GetCenterOfMass() =>
        ToDoubleArray(_gate.Call(SwRemodelProbeHost.Member.MassPropertyGetCenterOfMass, () => _massProperty.CenterOfMass));

    public IReadOnlyList<double>? GetPrincipalMomentsOfInertia() =>
        ToDoubleArray(_gate.Call(
            SwRemodelProbeHost.Member.MassPropertyGetPrincipalMoments, () => _massProperty.PrincipalMomentsOfInertia));

    public double GetMass() => _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetMass, () => _massProperty.Mass);

    public double GetDensity() => _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetDensity, () => _massProperty.Density);

    /// <summary>
    /// The raw <c>object</c> a mass property getter answers with, marshalled as a SAFEARRAY of
    /// doubles - or, depending on the interop build, a plain <c>double[]</c> already. Anything
    /// else, or the wrong length, is unreadable rather than guessed (the same reasoning
    /// <c>SwRemodelProbeHost.FirstElement</c> already applies to <c>GetWhatsWrong</c>'s arrays).
    /// </summary>
    private static IReadOnlyList<double>? ToDoubleArray(object? value)
    {
        if (value is double[] doubles)
        {
            return doubles;
        }

        if (value is Array array)
        {
            var converted = new double[array.Length];
            for (int i = 0; i < array.Length; i++)
            {
                converted[i] = Convert.ToDouble(array.GetValue(i));
            }

            return converted;
        }

        return null;
    }
}
