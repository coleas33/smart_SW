using System;
using SolidWorks.Interop.sldworks;

namespace SwReview.Extractor.Rms;

/// <summary>
/// <see cref="IEquationTarget"/> over a real <c>IEquationMgr</c>: one interop member per interface
/// member, and nothing else (feature 004, T153's amendment; build order lane A).
///
/// <b>Ungated on purpose.</b> Every caller gates it from outside: the bridge, for the copy's
/// adapter (T153), under the interface-qualified write keys and the bare read keys
/// (<see cref="RemodelEquations"/>, <c>BridgeDispatcher</c>); and the probe host
/// (PROBE-2, 6, 7 and 21) through <see cref="GatedEquationTarget"/>, under the bare keys it has
/// always gated them under, because the probe executors call it with no gate around them. A gate
/// in here would gate each call twice and log a bare write key the stage-1 guard passes through
/// its read-only branch, where the gated-versus-denied rule of T057 cannot see it.
///
/// The mapping is written once, here, and shared - never copied into the adapter or the probe.
/// </summary>
public sealed class SwEquationManager : IEquationTarget
{
    private readonly IEquationMgr _manager;

    public SwEquationManager(IEquationMgr manager)
    {
        _manager = manager ?? throw new ArgumentNullException(nameof(manager));
    }

    /// <inheritdoc />
    public int GetCount() => _manager.GetCount();

    /// <inheritdoc />
    public string? GetEquation(int index) => _manager.get_Equation(index);

    /// <inheritdoc />
    public int Add3(int index, string equation, bool solve, int whichConfigurations, string[]? configNames) =>
        _manager.Add3(index, equation, solve, whichConfigurations, configNames);

    /// <inheritdoc />
    public int Add2(int index, string equation, bool solve) => _manager.Add2(index, equation, solve);

    /// <inheritdoc />
    public void SetEquation(int index, string equation) => _manager.set_Equation(index, equation);

    /// <inheritdoc />
    public int SetEquationAndConfigurationOption(
        int index, string equation, int whichConfigurations, string[]? configNames) =>
        _manager.SetEquationAndConfigurationOption(index, equation, whichConfigurations, configNames);

    /// <inheritdoc />
    public int Delete(int index) => _manager.Delete(index);
}
