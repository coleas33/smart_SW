using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using SwReview.AddIn.Terminal;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T054: finding the terminal CLIs, resolving how to start them, and reading their versions.
///
/// Nothing here requires Codex or Gemini to be installed, and that is deliberate: the CLIs are
/// the engineer's, not the build's, and a test that skipped itself on a machine without them
/// would be green on exactly the machine where the "not installed" message matters most. The
/// search path and the `--version` probe are therefore both injected, and fake CLIs are written
/// into a temporary folder that stands in for a PATH directory.
///
/// The one test that does start a real process (<see cref="TheProbeRunsTheResolvedCommand"/>)
/// runs a `.cmd` written seconds earlier, because the fact worth pinning down is that the probe
/// and <c>TerminalSession</c> start a CLI the same way. A `.cmd` cannot be handed to
/// `CreateProcess` (see <see cref="CliLaunch"/>), so a probe that shelled out on its own would
/// report "not installed" for the npm shim that the terminal then starts perfectly well - or,
/// worse, the other way round: a version that probed fine and a terminal that will not open.
///
/// Gemini is detected and never started. The terminal for it is deferred (decision
/// 2026-09-13), so the dropdown has two things to say about it - "not installed" with the
/// install steps and the Node requirement, or "installed, but the terminal is not in this
/// version" - and both of them are asserted here.
/// </summary>
public sealed class CliLocatorTests
{
    private static string Cmd => Path.Combine(Environment.SystemDirectory, "cmd.exe");

    private static string PowerShell => Path.Combine(
        Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe");

    // ---------------------------------------------------------------- finding it on PATH

    [Fact]
    public void FindsACmdShimOnPathAndResolvesItThroughCmd()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write("codex.cmd", "@echo off\r\n");
            CliDiscovery found = Locator(temp).Locate("codex");

            Assert.Equal(CliStatus.Ready, found.Status);
            Assert.True(found.CanStart);
            Assert.NotNull(found.Launch);
            Assert.Equal(Cmd, found.Launch!.Executable);
            Assert.Equal(new[] { "/c", shim }, found.Launch.Arguments);
            Assert.Equal(shim, found.Launch.ToolPath);
        }
    }

    [Fact]
    public void FindsAPowerShellShimOnPathAndResolvesItThroughPowerShell()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write("codex.ps1", "exit 0\r\n");
            CliDiscovery found = Locator(temp).Locate("codex");

            Assert.Equal(CliStatus.Ready, found.Status);
            Assert.Equal(PowerShell, found.Launch!.Executable);
            Assert.Equal(
                new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", shim },
                found.Launch.Arguments);
            Assert.Equal(shim, found.Launch.ToolPath);
        }
    }

    [Fact]
    public void FindsAnExeDirectly()
    {
        using (var temp = new TempFolder())
        {
            string exe = temp.Write("gemini.exe", "MZ");
            CliDiscovery found = Locator(temp, Version("gemini 0.4.1")).Locate("gemini");

            Assert.Equal(exe, found.Launch!.Executable);
            Assert.Empty(found.Launch.Arguments);
        }
    }

    /// <summary>
    /// npm writes `codex`, `codex.cmd` and `codex.ps1` side by side, and a hand-built install
    /// can add `codex.exe`. Preferring the image means one process instead of three and no
    /// interpreter between the pane and the CLI; the order is fixed rather than taken from
    /// PATHEXT because `.ps1` is not in the default PATHEXT at all.
    /// </summary>
    [Fact]
    public void PrefersAnExeToAShimInTheSameDirectory()
    {
        using (var temp = new TempFolder())
        {
            string exe = temp.Write("codex.exe", "MZ");
            temp.Write("codex.cmd", "@echo off\r\n");
            temp.Write("codex.ps1", "exit 0\r\n");
            temp.Write("codex", "#!/bin/sh\n");

            Assert.Equal(exe, Locator(temp).Locate("codex").Launch!.ToolPath);
        }
    }

    [Fact]
    public void TakesTheFirstDirectoryOnThePath()
    {
        using (var first = new TempFolder())
        using (var second = new TempFolder())
        {
            string wanted = first.Write("codex.cmd", "@echo off\r\n");
            second.Write("codex.cmd", "@echo off\r\n");

            var locator = new CliLocator(
                new[] { first.Path, second.Path }, Version("codex-cli 0.115.0"));

            Assert.Equal(wanted, locator.Locate("codex").Launch!.ToolPath);
        }
    }

    /// <summary>
    /// A PATH directory that has been deleted, or a quoted entry, or an empty one between two
    /// semicolons: all three are ordinary on a real machine, and none of them may throw on the
    /// way to the Terminal tab.
    /// </summary>
    [Fact]
    public void SurvivesUnusableDirectoriesOnThePath()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write("codex.cmd", "@echo off\r\n");
            var locator = new CliLocator(
                new[]
                {
                    string.Empty,
                    "   ",
                    Path.Combine(temp.Path, "gone"),
                    "C:\\<not a path>",
                    "\"" + temp.Path + "\"",
                },
                Version("codex-cli 0.115.0"));

            Assert.Equal(shim, locator.Locate("codex").Launch!.ToolPath);
        }
    }

    // ------------------------------------------------------------- the probe uses the launch

    /// <summary>
    /// The point of T054's "that both the `--version` probe and `TerminalSession` use": the
    /// probe is handed the resolved launch with `--version` appended, not a bare name and not a
    /// shell line of its own.
    /// </summary>
    [Fact]
    public void TheProbeIsGivenTheResolvedLaunchCommand()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write("codex.cmd", "@echo off\r\n");
            var probed = new List<CliLaunch>();
            var locator = new CliLocator(
                new[] { temp.Path },
                launch =>
                {
                    probed.Add(launch);
                    return CliVersionOutput.FromText("codex-cli 0.115.0");
                });

            CliDiscovery found = locator.Locate("codex");

            CliLaunch call = Assert.Single(probed);
            Assert.Equal(Cmd, call.Executable);
            Assert.Equal(new[] { "/c", shim, "--version" }, call.Arguments);
            Assert.Equal(shim, call.ToolPath);

            // The launch handed on to TerminalSession is the same command without `--version`.
            Assert.Equal(found.Launch!.Executable, call.Executable);
            Assert.Equal(new[] { "/c", shim }, found.Launch.Arguments);
        }
    }

    /// <summary>
    /// The real probe, against a real shim. `cmd.exe` is what actually runs it, which is the
    /// whole reason <see cref="CliLaunch"/> exists.
    /// </summary>
    [Fact]
    public void TheProbeRunsTheResolvedCommand()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write("codex.cmd", "@echo off\r\necho codex-cli 9.9.9\r\n");
            Assert.True(CliLaunch.TryResolve(shim, out CliLaunch? launch, out _));

            CliVersionOutput output = CliLocator.Probe(
                launch!.With("--version"), TimeSpan.FromSeconds(30));

            Assert.Null(output.Failure);
            Assert.Contains("codex-cli 9.9.9", output.Text);
            Assert.Equal(new System.Version(9, 9, 9, 0), CliLocator.ParseVersion(output.Text));
        }
    }

    /// <summary>
    /// A CLI that hangs instead of printing its version must not hang the pane, and must not
    /// leave a process behind when it is given up on.
    /// </summary>
    [Fact]
    public void TheProbeGivesUpOnACliThatDoesNotAnswer()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write(
                "slow.cmd", "@echo off\r\nping -n 30 127.0.0.1 > nul\r\necho too late\r\n");
            Assert.True(CliLaunch.TryResolve(shim, out CliLaunch? launch, out _));

            CliVersionOutput output = CliLocator.Probe(
                launch!.With("--version"), TimeSpan.FromMilliseconds(750));

            Assert.NotNull(output.Failure);
            Assert.DoesNotContain("too late", output.Text ?? string.Empty);
        }
    }

    [Fact]
    public void AProbeThatCouldNotRunTheCliIsNotAVersion()
    {
        using (var temp = new TempFolder())
        {
            temp.Write("codex.cmd", "@echo off\r\n");
            var locator = new CliLocator(
                new[] { temp.Path },
                _ => CliVersionOutput.FromFailure("CreateProcess failed for 'cmd.exe'"));

            CliDiscovery found = locator.Locate("codex");

            Assert.Equal(CliStatus.VersionUnreadable, found.Status);
            Assert.False(found.CanStart);
            Assert.Contains("CreateProcess failed", found.Message);
        }
    }

    // --------------------------------------------------------------------- version parsing

    [Theory]
    [InlineData("codex-cli 0.115.0", 0, 115, 0)]
    [InlineData("codex-cli 0.115.0\r\n", 0, 115, 0)]
    [InlineData("gemini 0.4.1", 0, 4, 1)]
    [InlineData("v1.2.3", 1, 2, 3)]
    [InlineData("1.2.3-preview.4", 1, 2, 3)]
    [InlineData("  0.115  ", 0, 115, 0)]
    [InlineData("loading config\ncodex-cli 0.115.0\n", 0, 115, 0)]
    public void ParsesTheVersionOutput(string text, int major, int minor, int build)
    {
        Assert.Equal(new System.Version(major, minor, build, 0), CliLocator.ParseVersion(text));
    }

    [Theory]
    [InlineData("")]
    [InlineData(null)]
    [InlineData("codex-cli")]
    [InlineData("build 2024")]
    [InlineData("Error: the term 'codex' is not recognized")]
    public void RefusesToInventAVersion(string? text)
    {
        Assert.Null(CliLocator.ParseVersion(text));
    }

    [Fact]
    public void AnUnreadableVersionStopsTheStart()
    {
        using (var temp = new TempFolder())
        {
            temp.Write("codex.cmd", "@echo off\r\n");
            CliDiscovery found = Locator(temp, Version("not a version at all")).Locate("codex");

            Assert.Equal(CliStatus.VersionUnreadable, found.Status);
            Assert.False(found.CanStart);
            Assert.Contains("not a version at all", found.Message);
        }
    }

    // ------------------------------------------------------------------ minimum versions

    [Fact]
    public void AcceptsTheMinimumVersionItself()
    {
        System.Version minimum = CliLocator.Definition("codex").MinimumVersion!;

        using (var temp = new TempFolder())
        {
            temp.Write("codex.cmd", "@echo off\r\n");
            CliDiscovery found = Locator(temp, Version("codex-cli " + minimum.ToString(3)))
                .Locate("codex");

            Assert.Equal(CliStatus.Ready, found.Status);
        }
    }

    /// <summary>A CLI that prints `0.115` rather than `0.115.0` is the same version, and a
    /// comparison that treated the missing component as "less than zero" would refuse it.</summary>
    [Fact]
    public void AShortVersionIsNotOlderThanTheSameLongOne()
    {
        System.Version minimum = CliLocator.Definition("codex").MinimumVersion!;
        string shortened = minimum.Major + "." + minimum.Minor;

        using (var temp = new TempFolder())
        {
            temp.Write("codex.cmd", "@echo off\r\n");
            CliDiscovery found = Locator(temp, Version("codex-cli " + shortened)).Locate("codex");

            Assert.Equal(
                minimum.Build == 0 && minimum.Revision <= 0 ? CliStatus.Ready : CliStatus.TooOld,
                found.Status);
        }
    }

    [Fact]
    public void ReportsATooOldCliWithBothVersions()
    {
        System.Version minimum = CliLocator.Definition("codex").MinimumVersion!;
        var old = new System.Version(minimum.Major, Math.Max(0, minimum.Minor - 1), 0);

        using (var temp = new TempFolder())
        {
            temp.Write("codex.cmd", "@echo off\r\n");
            CliDiscovery found = Locator(temp, Version("codex-cli " + old.ToString(3)))
                .Locate("codex");

            Assert.Equal(CliStatus.TooOld, found.Status);
            Assert.False(found.CanStart);
            Assert.Contains(old.ToString(3), found.Message);
            Assert.Contains(minimum.ToString(3), found.Message);
            Assert.Contains(CliLocator.Definition("codex").InstallSteps, found.Message);
        }
    }

    // ---------------------------------------------------------------------- not installed

    [Fact]
    public void ReportsCodexNotInstalledWithTheInstallSteps()
    {
        using (var temp = new TempFolder())
        {
            CliDiscovery found = Locator(temp).Locate("codex");

            Assert.Equal(CliStatus.NotInstalled, found.Status);
            Assert.False(found.CanStart);
            Assert.Null(found.Launch);
            Assert.Null(found.Version);
            Assert.Contains("npm install -g @openai/codex", found.Message);
            Assert.Contains(
                CliLocator.Definition("codex").MinimumVersion!.ToString(3), found.Message);
        }
    }

    [Fact]
    public void ReportsGeminiNotInstalledWithTheNodeRequirement()
    {
        using (var temp = new TempFolder())
        {
            CliDiscovery found = Locator(temp).Locate("gemini");

            Assert.Equal(CliStatus.NotInstalled, found.Status);
            Assert.Contains("npm install -g @google/gemini-cli", found.Message);
            Assert.Contains("Node 20", found.Message);
        }
    }

    [Fact]
    public void AnEmptySearchPathIsNotInstalledRatherThanAnError()
    {
        var locator = new CliLocator(
            Array.Empty<string>(), _ => CliVersionOutput.FromText("codex-cli 0.115.0"));

        Assert.Equal(CliStatus.NotInstalled, locator.Locate("codex").Status);
    }

    /// <summary>
    /// The npm bash shim - `codex` with no extension - sitting alone in a directory. Saying
    /// "not installed" there would send the engineer to reinstall something that is already
    /// installed, so the file that was found is named and the reason is given instead.
    /// </summary>
    [Fact]
    public void ReportsAFileItCannotStartRatherThanNothingAtAll()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write("codex", "#!/bin/sh\n");
            var probed = new List<CliLaunch>();
            var locator = new CliLocator(
                new[] { temp.Path },
                launch =>
                {
                    probed.Add(launch);
                    return CliVersionOutput.FromText("codex-cli 0.115.0");
                });

            CliDiscovery found = locator.Locate("codex");

            Assert.Equal(CliStatus.Unsupported, found.Status);
            Assert.False(found.CanStart);
            Assert.Null(found.Launch);
            Assert.Contains(shim, found.Message);
            Assert.Empty(probed);
        }
    }

    // --------------------------------------------------------------------- Gemini deferred

    /// <summary>
    /// Decision 2026-09-13: the Gemini terminal is not in v1. Detection stays so the dropdown
    /// can tell the two cases apart, but an installed Gemini is still never startable, and the
    /// message says why rather than leaving the engineer pressing a dead Start button.
    /// </summary>
    [Fact]
    public void AnInstalledGeminiIsReportedAsDeferredRatherThanReady()
    {
        using (var temp = new TempFolder())
        {
            string shim = temp.Write("gemini.cmd", "@echo off\r\n");
            CliDiscovery found = Locator(temp, Version("gemini 0.4.1")).Locate("gemini");

            Assert.Equal(CliStatus.Deferred, found.Status);
            Assert.False(found.CanStart);
            Assert.Equal(shim, found.Launch!.ToolPath);
            Assert.Equal(new System.Version(0, 4, 1, 0), found.Version);
            Assert.Contains("deferred", found.Message, StringComparison.OrdinalIgnoreCase);
        }
    }

    /// <summary>No minimum has been verified for Gemini (contracts/cli-profiles.md leaves that
    /// to spike T055a), so no version is refused for being too old - inventing a number would
    /// refuse a CLI we have never tested against.</summary>
    [Fact]
    public void GeminiHasNoMinimumVersionYet()
    {
        Assert.Null(CliLocator.Definition("gemini").MinimumVersion);

        using (var temp = new TempFolder())
        {
            temp.Write("gemini.cmd", "@echo off\r\n");
            Assert.Equal(
                CliStatus.Deferred,
                Locator(temp, Version("gemini 0.0.1")).Locate("gemini").Status);
        }
    }

    // ------------------------------------------------------------------------- the roster

    [Fact]
    public void KnowsExactlyTheTwoClisTheSettingsFileAllows()
    {
        Assert.Equal(
            new[] { "codex", "gemini" },
            CliLocator.Definitions.Select(definition => definition.Name).ToArray());
    }

    [Fact]
    public void LocateAllAnswersForEveryCliInOrder()
    {
        using (var temp = new TempFolder())
        {
            temp.Write("codex.cmd", "@echo off\r\n");
            IReadOnlyList<CliDiscovery> all = Locator(temp).LocateAll();

            Assert.Equal(new[] { "codex", "gemini" }, all.Select(one => one.Cli.Name).ToArray());
            Assert.Equal(CliStatus.Ready, all[0].Status);
            Assert.Equal(CliStatus.NotInstalled, all[1].Status);
        }
    }

    [Fact]
    public void RefusesACliNameItDoesNotKnow()
    {
        using (var temp = new TempFolder())
        {
            Assert.Throws<ArgumentException>(() => Locator(temp).Locate("bash"));
        }
    }

    [Fact]
    public void EveryDiscoveryCarriesAMessageWorthShowing()
    {
        using (var temp = new TempFolder())
        {
            temp.Write("codex.cmd", "@echo off\r\n");
            foreach (CliDiscovery found in Locator(temp).LocateAll())
            {
                Assert.False(string.IsNullOrWhiteSpace(found.Message));
                Assert.Contains(found.Cli.DisplayName, found.Message);
            }
        }
    }

    // ------------------------------------------------------------------------------ helpers

    private static CliLocator Locator(
        TempFolder temp, Func<CliLaunch, CliVersionOutput>? probe = null) =>
        new CliLocator(new[] { temp.Path }, probe ?? Version("codex-cli 0.115.0"));

    private static Func<CliLaunch, CliVersionOutput> Version(string text) =>
        _ => CliVersionOutput.FromText(text);

    private sealed class TempFolder : IDisposable
    {
        public TempFolder()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(), "SwReview.CliLocator.Tests", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public string Write(string name, string content)
        {
            string full = System.IO.Path.Combine(Path, name);
            File.WriteAllText(full, content, new UTF8Encoding(false));
            return full;
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(Path, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
}
