using System;
using SolidWorks.Interop.sldworks;

namespace SwReview.Extractor.Rms;

/// <summary>
/// <see cref="IRemodelToggleHost"/> over a real <c>ISldWorks</c>: one interop member per interface
/// member, and nothing else (feature 004, build order lane B; default taken 2026-09-27, the owner
/// may revise). The probe host (<see cref="SwRemodelProbeHost"/>) and the add-in's bridge seat both
/// delegate their four toggle members here, so the mapping is written once.
///
/// <b>Ungated on purpose</b>, as <see cref="SwEquationManager"/> is: every caller is
/// <see cref="RemodelSystemToggles"/>, which gates each read under its bare key and each write under
/// its interface-qualified allowlist key (<c>ISldWorks.SetUserPreferenceToggle</c>,
/// <c>ISldWorks.set_CommandInProgress</c>), and puts the settings back through the guard alone. A
/// gate in here would gate each call twice and log a bare write key the stage-1 guard passes
/// through its read-only branch.
/// </summary>
public sealed class SwRemodelToggleHost : IRemodelToggleHost
{
    private readonly ISldWorks _swApp;

    public SwRemodelToggleHost(ISldWorks swApp)
    {
        _swApp = swApp ?? throw new ArgumentNullException(nameof(swApp));
    }

    /// <inheritdoc />
    public bool GetUserPreferenceToggle(int toggle) => _swApp.GetUserPreferenceToggle(toggle);

    /// <inheritdoc />
    public void SetUserPreferenceToggle(int toggle, bool value) => _swApp.SetUserPreferenceToggle(toggle, value);

    /// <inheritdoc />
    public bool GetCommandInProgress() => _swApp.CommandInProgress;

    /// <inheritdoc />
    public void SetCommandInProgress(bool value) => _swApp.CommandInProgress = value;
}
