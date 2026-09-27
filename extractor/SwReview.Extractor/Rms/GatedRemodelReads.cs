using System;
using System.Collections.Generic;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Rms;

/// <summary>
/// The probe host's <see cref="IEquationTarget"/> (PROBE-2, 6, 7 and 21): another
/// <see cref="IEquationTarget"/> - in the product, the shared <see cref="SwEquationManager"/> - with
/// each call gated <b>once</b>, under the bare key the probe host has always gated it under
/// (<see cref="SwRemodelProbeHost.Member"/>), so every probe's gated set and ledger are what they
/// were before the split (feature 004, T153's amendment; build order lane A).
///
/// The probe executors call the equation manager with no gate around them, which is why this
/// wrapper exists; the bridge gates the copy's adapter from outside and never uses it. It adds the
/// gate and nothing else: arguments and answers pass through unchanged.
/// </summary>
public sealed class GatedEquationTarget : IEquationTarget
{
    private readonly SwGate _gate;
    private readonly IEquationTarget _equations;

    public GatedEquationTarget(SwGate gate, IEquationTarget equations)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _equations = equations ?? throw new ArgumentNullException(nameof(equations));
    }

    /// <inheritdoc />
    public int GetCount() => _gate.Call(SwRemodelProbeHost.Member.EquationGetCount, () => _equations.GetCount());

    /// <inheritdoc />
    public string? GetEquation(int index) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationGetEquationText, () => _equations.GetEquation(index));

    /// <inheritdoc />
    public int Add3(int index, string equation, bool solve, int whichConfigurations, string[]? configNames) =>
        _gate.Call(
            SwRemodelProbeHost.Member.AddEquation,
            () => _equations.Add3(index, equation, solve, whichConfigurations, configNames));

    /// <inheritdoc />
    public int Add2(int index, string equation, bool solve) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationAdd2, () => _equations.Add2(index, equation, solve));

    /// <inheritdoc />
    public void SetEquation(int index, string equation) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationSetEquation, () => _equations.SetEquation(index, equation));

    /// <inheritdoc />
    public int SetEquationAndConfigurationOption(
        int index, string equation, int whichConfigurations, string[]? configNames) =>
        _gate.Call(
            SwRemodelProbeHost.Member.EquationSetEquationAndConfigurationOption,
            () => _equations.SetEquationAndConfigurationOption(index, equation, whichConfigurations, configNames));

    /// <inheritdoc />
    public int Delete(int index) =>
        _gate.Call(SwRemodelProbeHost.Member.EquationDelete, () => _equations.Delete(index));
}

/// <summary>
/// The probe host's <see cref="IMassPropertyReading"/> (PROBE-8): another
/// <see cref="IMassPropertyReading"/> - in the product, the shared <see cref="SwMassProperty"/> -
/// with each call gated <b>once</b>, under the bare key the probe host has always gated it under
/// (<see cref="SwRemodelProbeHost.Member"/>), so PROBE-8's gated set and ledger are what they were
/// before the split (feature 004, T153's amendment; build order lane A). The keys are the ones
/// <see cref="RemodelGeometry.Read"/> gates the same members under on the copy.
///
/// It adds the gate and nothing else: arguments and answers pass through unchanged, and the
/// principal moments are not sorted here (that is <see cref="RemodelGeometry"/>'s rule).
/// </summary>
public sealed class GatedMassPropertyReading : IMassPropertyReading
{
    private readonly SwGate _gate;
    private readonly IMassPropertyReading _massProperty;

    public GatedMassPropertyReading(SwGate gate, IMassPropertyReading massProperty)
    {
        _gate = gate ?? throw new ArgumentNullException(nameof(gate));
        _massProperty = massProperty ?? throw new ArgumentNullException(nameof(massProperty));
    }

    /// <inheritdoc />
    public void SetAccuracyLevel(int accuracyLevel) =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertySetAccuracyLevel, () => _massProperty.SetAccuracyLevel(accuracyLevel));

    /// <inheritdoc />
    public void SetSelectedItems(IReadOnlyList<object> bodies) =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertySetSelectedItems, () => _massProperty.SetSelectedItems(bodies));

    /// <inheritdoc />
    public void SetUseSystemUnits(bool useSystemUnits) =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertySetUseSystemUnits, () => _massProperty.SetUseSystemUnits(useSystemUnits));

    /// <inheritdoc />
    public bool Recalculate() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyRecalculate, () => _massProperty.Recalculate());

    /// <inheritdoc />
    public double GetVolume() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetVolume, () => _massProperty.GetVolume());

    /// <inheritdoc />
    public double GetSurfaceArea() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetSurfaceArea, () => _massProperty.GetSurfaceArea());

    /// <inheritdoc />
    public IReadOnlyList<double>? GetCenterOfMass() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetCenterOfMass, () => _massProperty.GetCenterOfMass());

    /// <inheritdoc />
    public IReadOnlyList<double>? GetPrincipalMomentsOfInertia() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetPrincipalMoments, () => _massProperty.GetPrincipalMomentsOfInertia());

    /// <inheritdoc />
    public double GetMass() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetMass, () => _massProperty.GetMass());

    /// <inheritdoc />
    public double GetDensity() =>
        _gate.Call(SwRemodelProbeHost.Member.MassPropertyGetDensity, () => _massProperty.GetDensity());
}
