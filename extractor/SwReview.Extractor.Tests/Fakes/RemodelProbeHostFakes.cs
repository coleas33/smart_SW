using System;
using System.Collections.Generic;
using SwReview.Extractor.Rms;

namespace SwReview.Extractor.Tests.Fakes;

/// <summary>
/// A minimal, always-successful <see cref="IMassPropertyReading"/>. PROBE-8's tests use
/// <see cref="FakeMassProperty"/> (Fakes/RemodelFakes.cs) directly when they need to script
/// specific readings; this is only <see cref="FakeRemodelProbeHost"/>'s own out-of-the-box
/// default for tests that never call <c>MeasureMassProperties</c> at all.
/// </summary>
public delegate bool FakeGetCustomProperty(RemodelProbePart part, string key, out string? value, out string? resolvedValue);

/// <summary>
/// Every decision <c>probe remodel</c>'s bodies (tasks.md T033 to T039) can ask a host for,
/// scripted through public delegate properties with benign defaults - a test overrides only the
/// members its scenario actually cares about. Every call is recorded in <see cref="Calls"/> in
/// order, so a test can assert what a probe body did and did not touch.
/// </summary>
public sealed class FakeRemodelProbeHost : IRemodelProbeHost
{
    public List<string> Calls { get; } = new List<string>();

    private readonly Dictionary<int, bool> _toggles = new Dictionary<int, bool>();

    // ---- T031/T032's original four ------------------------------------------------------

    public Func<bool> AnyDocumentOpenImpl { get; set; } = () => false;

    public Func<string> SwVersionImpl { get; set; } = () => "32.5.0.48";

    public Func<RemodelProbePartRecipe, string, RemodelProbePart> BuildPartImpl { get; set; } =
        (recipe, savePath) => new RemodelProbePart(new object(), savePath, Array.Empty<object>());

    public Action<RemodelProbePart> ClosePartImpl { get; set; } = _ => { };

    public bool AnyDocumentOpen()
    {
        Calls.Add(nameof(AnyDocumentOpen));
        return AnyDocumentOpenImpl();
    }

    public string SwVersion()
    {
        Calls.Add(nameof(SwVersion));
        return SwVersionImpl();
    }

    public RemodelProbePart BuildPart(RemodelProbePartRecipe recipe, string savePath)
    {
        Calls.Add(nameof(BuildPart));
        return BuildPartImpl(recipe, savePath);
    }

    public void ClosePart(RemodelProbePart part)
    {
        Calls.Add(nameof(ClosePart));
        ClosePartImpl(part);
    }

    // ---- IRemodelToggleHost --------------------------------------------------------------

    public bool GetUserPreferenceToggle(int toggle)
    {
        Calls.Add(nameof(GetUserPreferenceToggle));
        return _toggles.TryGetValue(toggle, out bool value) && value;
    }

    public void SetUserPreferenceToggle(int toggle, bool value)
    {
        Calls.Add(nameof(SetUserPreferenceToggle));
        _toggles[toggle] = value;
    }

    /// <summary>
    /// Every value <see cref="SetCommandInProgress"/> was called with, in order - PROBE-1's own
    /// evidence that it flipped the flag clear, then set, around its two attempts.
    /// </summary>
    public List<bool> CommandInProgressHistory { get; } = new List<bool>();

    public bool CommandInProgress { get; set; }

    public bool GetCommandInProgress()
    {
        Calls.Add(nameof(GetCommandInProgress));
        return CommandInProgress;
    }

    public void SetCommandInProgress(bool value)
    {
        Calls.Add(nameof(SetCommandInProgress));
        CommandInProgress = value;
        CommandInProgressHistory.Add(value);
    }

    // ---- T033 to T039's additions ---------------------------------------------------------

    public Func<RemodelProbePart, string, string, int, bool> ReorderFeatureImpl { get; set; } = (part, move, target, location) => true;

    public bool ReorderFeature(RemodelProbePart part, string featureToMove, string targetFeature, int location)
    {
        Calls.Add(nameof(ReorderFeature));
        return ReorderFeatureImpl(part, featureToMove, targetFeature, location);
    }

    public Func<RemodelProbePart, IReadOnlyList<string>> GetFeatureNamesImpl { get; set; } =
        _ => new[] { "Boss-Extrude1", "Cut-Extrude1", "Fillet1", "Fillet1", "Shell1" };

    public IReadOnlyList<string> GetFeatureNames(RemodelProbePart part)
    {
        Calls.Add(nameof(GetFeatureNames));
        return GetFeatureNamesImpl(part);
    }

    public Func<RemodelProbePart, string, string?> GetFeatureTypeNameImpl { get; set; } = (part, name) => "Extrusion";

    public string? GetFeatureTypeName(RemodelProbePart part, string featureName)
    {
        Calls.Add(nameof(GetFeatureTypeName));
        return GetFeatureTypeNameImpl(part, featureName);
    }

    public Func<RemodelProbePart, string, string?> GetFeatureDescriptionImpl { get; set; } = (part, name) => string.Empty;

    public string? GetFeatureDescription(RemodelProbePart part, string featureName)
    {
        Calls.Add(nameof(GetFeatureDescription));
        return GetFeatureDescriptionImpl(part, featureName);
    }

    public Action<RemodelProbePart, string, string> SetFeatureDescriptionImpl { get; set; } = (part, name, text) => { };

    public void SetFeatureDescription(RemodelProbePart part, string featureName, string text)
    {
        Calls.Add(nameof(SetFeatureDescription));
        SetFeatureDescriptionImpl(part, featureName, text);
    }

    public Action<RemodelProbePart, string, string> SetFeatureNameImpl { get; set; } = (part, current, replacement) => { };

    public void SetFeatureName(RemodelProbePart part, string currentName, string newName)
    {
        Calls.Add(nameof(SetFeatureName));
        SetFeatureNameImpl(part, currentName, newName);
    }

    public Func<RemodelProbePart, IReadOnlyList<string>, object?> TryInsertFeatureTreeFolderImpl { get; set; } = (part, names) => new object();

    public object? TryInsertFeatureTreeFolder(RemodelProbePart part, IReadOnlyList<string> memberNames)
    {
        Calls.Add(nameof(TryInsertFeatureTreeFolder));
        return TryInsertFeatureTreeFolderImpl(part, memberNames);
    }

    public Func<RemodelProbePart, string, string, bool, bool> MoveToFolderImpl { get; set; } = (part, to, from, isFolder) => true;

    public bool MoveToFolder(RemodelProbePart part, string moveToFeatureOrFolder, string moveFromFeature, bool isFolder)
    {
        Calls.Add(nameof(MoveToFolder));
        return MoveToFolderImpl(part, moveToFeatureOrFolder, moveFromFeature, isFolder);
    }

    public Func<RemodelProbePart, string, string, bool> MakeSubFeatureImpl { get; set; } = (part, parent, sub) => true;

    public bool MakeSubFeature(RemodelProbePart part, string parentFeatureName, string subFeatureName)
    {
        Calls.Add(nameof(MakeSubFeature));
        return MakeSubFeatureImpl(part, parentFeatureName, subFeatureName);
    }

    public Func<RemodelProbePart, IEquationTarget> GetEquationManagerImpl { get; set; } = _ => new FakeEquationManager();

    public IEquationTarget GetEquationManager(RemodelProbePart part)
    {
        Calls.Add(nameof(GetEquationManager));
        return GetEquationManagerImpl(part);
    }

    public Func<RemodelProbePart, int, double> GetEquationValueImpl { get; set; } = (part, index) => 120.0;

    public double GetEquationValue(RemodelProbePart part, int index)
    {
        Calls.Add(nameof(GetEquationValue));
        return GetEquationValueImpl(part, index);
    }

    public Func<RemodelProbePart, string, bool, bool> SetFeatureSuppressionImpl { get; set; } = (part, name, suppress) => true;

    public bool SetFeatureSuppression(RemodelProbePart part, string featureName, bool suppress)
    {
        Calls.Add(nameof(SetFeatureSuppression));
        return SetFeatureSuppressionImpl(part, featureName, suppress);
    }

    public Func<RemodelProbePart, bool> ForceRebuildImpl { get; set; } = _ => true;

    public bool ForceRebuild(RemodelProbePart part)
    {
        Calls.Add(nameof(ForceRebuild));
        return ForceRebuildImpl(part);
    }

    public Func<RemodelProbePart, RemodelWhatsWrongReading> ReadWhatsWrongImpl { get; set; } =
        _ => new RemodelWhatsWrongReading(0, true, "empty");

    public RemodelWhatsWrongReading ReadWhatsWrong(RemodelProbePart part)
    {
        Calls.Add(nameof(ReadWhatsWrong));
        return ReadWhatsWrongImpl(part);
    }

    public Func<RemodelProbePart, string, string, int> AddCustomPropertyImpl { get; set; } = (part, key, value) => 0;

    public int AddCustomProperty(RemodelProbePart part, string key, string value)
    {
        Calls.Add(nameof(AddCustomProperty));
        return AddCustomPropertyImpl(part, key, value);
    }

    public FakeGetCustomProperty GetCustomPropertyImpl { get; set; } =
        (RemodelProbePart part, string key, out string? value, out string? resolvedValue) =>
        {
            value = null;
            resolvedValue = null;
            return false;
        };

    public bool GetCustomProperty(RemodelProbePart part, string key, out string? value, out string? resolvedValue)
    {
        Calls.Add(nameof(GetCustomProperty));
        return GetCustomPropertyImpl(part, key, out value, out resolvedValue);
    }

    public Func<RemodelProbePart, bool> SaveExistingPartImpl { get; set; } = _ => true;

    public bool SaveExistingPart(RemodelProbePart part)
    {
        Calls.Add(nameof(SaveExistingPart));
        return SaveExistingPartImpl(part);
    }

    public Func<string, RemodelProbePart> ReopenPartImpl { get; set; } =
        path => new RemodelProbePart(new object(), path, Array.Empty<object>());

    public RemodelProbePart ReopenPart(string path)
    {
        Calls.Add(nameof(ReopenPart));
        return ReopenPartImpl(path);
    }

    public Func<object> BuildBlankDocumentImpl { get; set; } = () => new object();

    public object BuildBlankDocument()
    {
        Calls.Add(nameof(BuildBlankDocument));
        return BuildBlankDocumentImpl();
    }

    public Func<object, int> GetEquationCountImpl { get; set; } = _ => 0;

    public int GetEquationCount(object blankDocument)
    {
        Calls.Add(nameof(GetEquationCount));
        return GetEquationCountImpl(blankDocument);
    }

    public Action<object> DiscardBlankDocumentImpl { get; set; } = _ => { };

    public void DiscardBlankDocument(object blankDocument)
    {
        Calls.Add(nameof(DiscardBlankDocument));
        DiscardBlankDocumentImpl(blankDocument);
    }

    public Func<AnalyticSolidSpec, string, RemodelProbePart> BuildAnalyticSolidImpl { get; set; } =
        (spec, savePath) => new RemodelProbePart(new object(), savePath, Array.Empty<object>());

    public RemodelProbePart BuildAnalyticSolid(AnalyticSolidSpec spec, string savePath)
    {
        Calls.Add(nameof(BuildAnalyticSolid));
        return BuildAnalyticSolidImpl(spec, savePath);
    }

    public Func<RemodelProbePart, IMassPropertyReading?> MeasureMassPropertiesImpl { get; set; } = _ => new FakeMassProperty();

    public IMassPropertyReading? MeasureMassProperties(RemodelProbePart part)
    {
        Calls.Add(nameof(MeasureMassProperties));
        return MeasureMassPropertiesImpl(part);
    }
}
