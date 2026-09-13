using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using SwReview.AddIn.Native;
using SwReview.AddIn.Review;
using SwReview.AddIn.Settings;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// T033: the child process the pane launches for `swreview chat serve --port 0`.
///
/// Everything here runs against <see cref="StubBackend"/>, a real child process that behaves
/// like the backend's handshake without needing Python or a key. The real entry point is
/// exercised on the Python side (T037a); what has to be proved here is the *host's* half of
/// the contract, and every clause of it is a way the pane can fail a user badly:
///
/// - the first stdout line is the only handshake there is, so a malformed or missing one has
///   to become a message an engineer can act on rather than a pane that waits forever;
/// - the API key reaches the backend through the environment block and nowhere else - a key
///   on a command line is readable by every process on the workstation (FR-015);
/// - the child is in a kill-on-close job object *before its first thread runs*, so a
///   SOLIDWORKS crash cannot leave a server holding a loopback port (the ordering itself is
///   proved in <see cref="ProcessLifetimeTests"/>; here we only assert membership);
/// - a settings change restarts the backend, but never while a turn is running, because a
///   running turn owns process state that is not on disk (chat-api.md, "Shutdown and
///   settings changes");
/// - stopping asks before it terminates, because `TerminateProcess` delivers no signal and
///   the backend's shutdown is what gives every live chat an `ended_at` (FR-008) - and it
///   stops the whole tree, because the pilot launcher puts the server a generation below the
///   process we hold a handle to;
/// - the credential and endpoint variables that reach the child are the pane's answers and
///   not the workstation's, asserted against a real child's own view of its environment,
///   because that block is the parent's environment with the pane's values merged over it.
/// </summary>
public sealed class BackendProcessTests
{
    private const string Key = "sk-proj-EXAMPLE-not-a-real-key-0123456789";
    private const string Origin = "https://swreview.invalid";

    // ---- the handshake ------------------------------------------------------------------

    [Fact]
    public void ParsesPortAndTokenFromTheFirstStdoutLine()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake(port: 51234);

            using (BackendProcess backend = BackendProcess.Start(Options(stub, job)))
            {
                Assert.Equal(51234, backend.Port);
                Assert.Equal(StubBackend.DefaultToken, backend.Token);
                Assert.Equal("http://127.0.0.1:51234", backend.Origin);
                Assert.True(backend.ProcessId > 0);
                Assert.True(backend.Healthy);
                Assert.Equal(stub.LogPath, backend.LogPath);
            }
        }
    }

    [Fact]
    public void LaterStdoutLinesDoNotDisturbThePortOrToken()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            // The contract forbids a second stdout line. A backend that writes one anyway
            // must not move the pane's port, and must not be able to fill the pipe and block:
            // the reader keeps draining into the log after the handshake.
            stub.PrintsHandshake(port: 40001).AlsoPrints("{\"port\": 9, \"token\": \"later\"}");

            using (BackendProcess backend = BackendProcess.Start(Options(stub, job)))
            {
                Assert.Equal(40001, backend.Port);
                Assert.Equal(StubBackend.DefaultToken, backend.Token);
            }
        }
    }

    [Fact]
    public void ASilentBackendTimesOutWithAMessageNamingTheCommandAndTheLog()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsNothing();
            BackendStartOptions options = Options(stub, job);
            options.HandshakeTimeout = TimeSpan.FromSeconds(3);

            var failure = Assert.Throws<BackendStartException>(() => BackendProcess.Start(options));

            Assert.Contains("3", failure.Message);
            Assert.Contains(stub.LogPath, failure.Message);
            Assert.Contains("powershell.exe", failure.Message, StringComparison.OrdinalIgnoreCase);
            // The child that never answered is not left behind.
            Assert.NotNull(failure.ProcessId);
            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(failure.ProcessId!.Value)));
        }
    }

    [Fact]
    public void ABackendThatExitsBeforeTheHandshakeReportsItsExitCodeAndStderr()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.WritesToStandardError("ModuleNotFoundError: No module named 'swreview'").ExitsWith(3);
            BackendStartOptions options = Options(stub, job);
            options.HandshakeTimeout = TimeSpan.FromSeconds(30);

            var failure = Assert.Throws<BackendStartException>(() => BackendProcess.Start(options));

            Assert.Contains("3", failure.Message);
            Assert.Contains(stub.LogPath, failure.Message);
            Assert.Contains("No module named", stub.ReadLog());
        }
    }

    [Fact]
    public void AnUnparseableFirstLineIsReportedWithoutEchoingIt()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            // Echoing the line back would defeat the point the moment a misconfigured backend
            // prints something containing the key it was given.
            stub.PrintsRawLine("Traceback (most recent call last): " + Key);
            BackendStartOptions options = Options(stub, job);
            options.HandshakeTimeout = TimeSpan.FromSeconds(10);

            var failure = Assert.Throws<BackendStartException>(() => BackendProcess.Start(options));

            Assert.DoesNotContain(Key, failure.Message);
            Assert.Contains(stub.LogPath, failure.Message);
        }
    }

    [Fact]
    public void AnUnhealthyBackendIsStoppedAndReported()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake();
            BackendStartOptions options = Options(stub, job);
            options.HealthProbe = (origin, token) => false;
            options.HealthTimeout = TimeSpan.FromSeconds(2);

            var failure = Assert.Throws<BackendStartException>(() => BackendProcess.Start(options));

            Assert.Contains("health", failure.Message, StringComparison.OrdinalIgnoreCase);
            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(failure.ProcessId!.Value)));
        }
    }

    [Fact]
    public void TheHealthProbeIsCalledWithTheBackendOriginAndToken()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake(port: 45678);
            var seen = new List<string>();
            BackendStartOptions options = Options(stub, job);
            options.HealthProbe = (origin, token) =>
            {
                seen.Add(origin + " " + token);
                return true;
            };

            using (BackendProcess.Start(options))
            {
                Assert.Equal(new[] { "http://127.0.0.1:45678 " + StubBackend.DefaultToken }, seen);
            }
        }
    }

    // ---- the key ------------------------------------------------------------------------

    [Fact]
    public void TheKeyTravelsInTheEnvironmentAndNeverOnTheCommandLine()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake().RecordsItsCommandLine().RecordsItsEnvironment();
            BackendStartOptions options = Options(stub, job);
            options.Environment["OPENAI_API_KEY"] = Key;
            options.Environment["OPENAI_BASE_URL"] = "https://gateway.example.invalid/v1";
            options.Secrets.Add(Key);

            using (BackendProcess.Start(options))
            {
                string commandLine = stub.ReadCommandLine();
                string environment = stub.ReadEnvironmentDump();

                Assert.DoesNotContain(Key, commandLine);
                Assert.Contains("chat serve", commandLine);
                Assert.Contains("--port 0", commandLine);
                Assert.Contains("OPENAI_API_KEY=" + Key, environment);
                Assert.Contains("OPENAI_BASE_URL=https://gateway.example.invalid/v1", environment);
            }
        }
    }

    [Fact]
    public void TheAllowedOriginAndRunRootAreOnTheCommandLine()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake().RecordsItsCommandLine();

            using (BackendProcess.Start(Options(stub, job)))
            {
                string commandLine = stub.ReadCommandLine();

                Assert.Contains("--allow-origin " + Origin, commandLine);
                Assert.Contains("--run-root", commandLine);
                Assert.Contains(stub.RunRoot, commandLine);
            }
        }
    }

    [Fact]
    public void StderrIsWrittenToTheLogWithSecretsRedacted()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake().WritesToStandardError("openai error for key " + Key);
            BackendStartOptions options = Options(stub, job);
            options.Environment["OPENAI_API_KEY"] = Key;
            options.Secrets.Add(Key);

            using (BackendProcess.Start(options))
            {
                Assert.True(StubBackend.Waits(() => stub.ReadLog().Contains("openai error")));
                string log = stub.ReadLog();

                Assert.DoesNotContain(Key, log);
                Assert.Contains(Redaction.Mask, log);
            }
        }
    }

    // ---- the credential and endpoint environment BackendClient builds ---------------------

    [Fact]
    public void TheGeminiKeyIsWrittenToEveryVariableTheProviderReadsSoAnInheritedOneCannotWin()
    {
        // The child inherits SLDWORKS.exe's whole environment, and the Python side resolves
        // GOOGLE_API_KEY *ahead of* GEMINI_API_KEY - the precedence google.genai applies
        // itself (agent/settings.py `_env_key`). Writing only GEMINI_API_KEY therefore lets a
        // workstation's personal GOOGLE_API_KEY silently win while the pane reports
        // key_source "settings": a run that cannot say which credential it used (FR-015).
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (Seeded("GOOGLE_API_KEY", "workstation-key-that-must-not-be-used"))
        {
            UserSettings settings = Gemini();
            settings.SetApiKey(Key);

            string environment = EnvironmentOf(stub, job, settings);

            Assert.Contains("GOOGLE_API_KEY=" + Key, environment);
            Assert.Contains("GEMINI_API_KEY=" + Key, environment);
            Assert.DoesNotContain("workstation-key-that-must-not-be-used", environment);
        }
    }

    [Fact]
    public void GeminiEnterpriseSettingsTurnTheEnterpriseSwitchOnBesideTheProjectAndLocation()
    {
        // A project alone deliberately does not route a review at Vertex: agent/settings.py
        // `_env_enterprise` ignores GOOGLE_CLOUD_PROJECT unless the switch is present and on,
        // because plenty of corporate workstations export a project for unrelated tools. So
        // the pane, which *has* been told to use Enterprise, has to say so.
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            UserSettings settings = Gemini();
            settings.SetApiKey(Key);
            settings.GeminiEnterprise = new GeminiEnterpriseSettings
            {
                Project = "acme-cad-review",
                Location = "us-central1",
            };

            string environment = EnvironmentOf(stub, job, settings);

            Assert.Contains("GOOGLE_GENAI_USE_ENTERPRISE=true", environment);
            Assert.Contains("GOOGLE_CLOUD_PROJECT=acme-cad-review", environment);
            Assert.Contains("GOOGLE_CLOUD_LOCATION=us-central1", environment);
        }
    }

    [Fact]
    public void NoEnterpriseSettingsTurnTheSwitchOffEvenWhenTheWorkstationHasItOn()
    {
        // The mirror image: the pane says "public endpoint" and an inherited switch says
        // Vertex. The pane's answer has to be the one that reaches the child, or the echo in
        // `settings.saved` is a lie about where the review ran.
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (Seeded("GOOGLE_GENAI_USE_ENTERPRISE", "true"))
        {
            UserSettings settings = Gemini();
            settings.SetApiKey(Key);

            string environment = EnvironmentOf(stub, job, settings);

            Assert.Contains("GOOGLE_GENAI_USE_ENTERPRISE=false", environment);
        }
    }

    [Fact]
    public void TheBaseUrlIsWrittenOnlyForTheProviderThatReadsIt()
    {
        const string Gateway = "https://gateway.example.invalid/v1";

        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            UserSettings openai = UserSettings.Defaults();
            openai.Provider = "openai";
            openai.Model = UserSettings.DefaultModelFor("openai");
            openai.BaseUrl = Gateway;
            openai.SetApiKey(Key);

            Assert.Contains("OPENAI_BASE_URL=" + Gateway, EnvironmentOf(stub, job, openai));
        }

        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            // OPENAI_BASE_URL is read for the openai provider only (agent/settings.py
            // `_env_base_url`), so writing it for gemini would be an endpoint override the
            // engineer was told was saved and that nothing ever reads. ReviewHost refuses the
            // save; nothing that reaches here may write it either.
            UserSettings gemini = Gemini();
            gemini.BaseUrl = Gateway;
            gemini.SetApiKey(Key);

            Assert.DoesNotContain(Gateway, EnvironmentOf(stub, job, gemini));
        }
    }

    // ---- lifetime -----------------------------------------------------------------------

    [Fact]
    public void TheChildIsInsideTheJobObject()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake();

            using (BackendProcess backend = BackendProcess.Start(Options(stub, job)))
            {
                Assert.True(job.Contains(backend.ProcessId));
            }
        }
    }

    [Fact]
    public void DisposeStopsTheProcess()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake();
            int pid;

            using (BackendProcess backend = BackendProcess.Start(Options(stub, job)))
            {
                pid = backend.ProcessId;
                Assert.True(ProcessLifetimeTests.IsRunning(pid));
            }

            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(pid)));
        }
    }

    [Fact]
    public void DisposeAsksTheBackendToShutDownBeforeItTerminatesIt()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            // TerminateProcess delivers no signal, so a backend that is only ever terminated
            // never runs its uvicorn lifespan - and the lifespan is what finalizes every live
            // chat: `turn.ended {reason: "error"}`, `session.ended`, `session.json` with an
            // `ended_at` (chat-api.md, "Shutdown and settings changes"). Closing SOLIDWORKS
            // mid-turn would otherwise leave `ended_at` null for ever, which is FR-008.
            stub.PrintsHandshake().SignalsOnBreak();
            int pid;

            using (BackendProcess backend = BackendProcess.Start(Options(stub, job)))
            {
                pid = backend.ProcessId;
                Assert.True(ProcessLifetimeTests.IsRunning(pid));
            }

            Assert.True(
                File.Exists(stub.BreakPath),
                "the backend was never asked to shut down. Backend log: " + stub.ReadLog());
            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(pid)));
        }
    }

    [Fact]
    public void TheShutdownRequestReachesABackendWithAConsoleOfItsOwn()
    {
        // The branch above is the one a console-hosted test runner takes: the child shares our
        // console and the signal needs no arranging. The branch that actually *ships* is the
        // other one - SLDWORKS.exe is a GUI process with no console, so the backend is given a
        // hidden console of its own and the host attaches to it for the length of one call.
        // Leaving that untested would mean testing everything except the path SOLIDWORKS runs,
        // so the runner puts itself in SOLIDWORKS' position and gives up its console.
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (Detached())
        {
            stub.PrintsHandshake().SignalsOnBreak();
            int pid;

            using (BackendProcess backend = BackendProcess.Start(Options(stub, job)))
            {
                pid = backend.ProcessId;
            }

            Assert.True(
                File.Exists(stub.BreakPath),
                "the backend was never asked to shut down. Backend log: " + stub.ReadLog());
            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(pid)));
        }
    }

    [Fact]
    public void ABackendThatIgnoresTheShutdownRequestIsTerminatedAfterTheGracePeriod()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            // The stub never handles the break, so it is still there when the grace period
            // ends. A graceful stop that could hang is worse than no graceful stop at all:
            // this one runs on the add-in's unload path, with SOLIDWORKS waiting for it.
            stub.PrintsHandshake();
            BackendStartOptions options = Options(stub, job);
            options.StopGrace = TimeSpan.FromMilliseconds(500);
            int pid;

            var clock = System.Diagnostics.Stopwatch.StartNew();
            using (BackendProcess backend = BackendProcess.Start(options))
            {
                pid = backend.ProcessId;
                clock.Restart();
            }

            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(pid)));
            Assert.True(
                clock.Elapsed >= TimeSpan.FromMilliseconds(500),
                $"Dispose returned in {clock.Elapsed}, so it never waited out the grace period");
            Assert.True(
                clock.Elapsed < TimeSpan.FromSeconds(15),
                $"Dispose took {clock.Elapsed} for a 0.5s grace period");
        }
    }

    [Fact]
    public void RestartEndsTheWholeProcessTreeAndNotOnlyTheLauncher()
    {
        using (var first = new StubBackend())
        using (var second = new StubBackend())
        using (var job = new JobObject())
        {
            // The pilot launcher is `uv run --project <reviewer> swreview chat serve`, so the
            // HTTP server is a *grandchild* of uv.exe. Killing only the direct child would
            // leave the old Python server holding its loopback port and its copy of the key,
            // which is exactly the "two backends alive at once" BackendSupervisor exists to
            // prevent (FR-019).
            first.PrintsHandshake(port: 40301).SpawnsAGrandchild();
            second.PrintsHandshake(port: 40302);

            using (var supervisor = new BackendSupervisor(() => false))
            {
                int launcherPid = supervisor.Start(Options(first, job)).ProcessId;
                int grandchildPid = first.ReadGrandchildProcessId();
                Assert.NotEqual(launcherPid, grandchildPid);
                Assert.True(ProcessLifetimeTests.IsRunning(grandchildPid));

                supervisor.Restart(Options(second, job));

                Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(launcherPid)));
                Assert.True(
                    StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(grandchildPid)),
                    "the old backend's grandchild outlived the restart");
            }
        }
    }

    [Fact]
    public void DisposeIsIdempotent()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake();
            BackendProcess backend = BackendProcess.Start(Options(stub, job));

            backend.Dispose();
            backend.Dispose();
        }
    }

    // ---- restart on a settings change ---------------------------------------------------

    [Fact]
    public void RestartReplacesTheProcessWhenNoTurnIsRunning()
    {
        using (var first = new StubBackend())
        using (var second = new StubBackend())
        using (var job = new JobObject())
        {
            first.PrintsHandshake(port: 40101);
            second.PrintsHandshake(port: 40102);
            bool turnRunning = false;

            using (var supervisor = new BackendSupervisor(() => turnRunning))
            {
                BackendProcess before = supervisor.Start(Options(first, job));
                int beforePid = before.ProcessId;

                BackendProcess after = supervisor.Restart(Options(second, job));

                Assert.NotSame(before, after);
                Assert.Same(after, supervisor.Current);
                Assert.Equal(40102, after.Port);
                Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(beforePid)));
            }
        }
    }

    [Fact]
    public void RestartIsRefusedWhileATurnIsRunningAndLeavesTheProcessAlone()
    {
        using (var first = new StubBackend())
        using (var second = new StubBackend())
        using (var job = new JobObject())
        {
            first.PrintsHandshake(port: 40201);
            second.PrintsHandshake(port: 40202);
            bool turnRunning = true;

            using (var supervisor = new BackendSupervisor(() => turnRunning))
            {
                BackendProcess before = supervisor.Start(Options(first, job));

                var refused = Assert.Throws<TurnRunningException>(() => supervisor.Restart(Options(second, job)));

                Assert.Equal("TurnRunning", refused.ErrorClass);
                Assert.Same(before, supervisor.Current);
                Assert.Equal(40201, supervisor.Current!.Port);
                Assert.True(ProcessLifetimeTests.IsRunning(before.ProcessId));

                // and once the turn ends the same save succeeds
                turnRunning = false;
                BackendProcess after = supervisor.Restart(Options(second, job));

                Assert.Equal(40202, after.Port);
            }
        }
    }

    [Fact]
    public void DisposingTheSupervisorStopsTheCurrentProcess()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake();
            int pid;

            using (var supervisor = new BackendSupervisor(() => false))
            {
                pid = supervisor.Start(Options(stub, job)).ProcessId;
            }

            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(pid)));
        }
    }

    // ---- locating the launcher ----------------------------------------------------------

    [Fact]
    public void TheLocatorPrefersAnExplicitUvOverride()
    {
        using (var stub = new StubBackend())
        {
            string uv = Path.Combine(Path.GetDirectoryName(stub.ScriptPath)!, "uv.exe");
            File.WriteAllText(uv, string.Empty);
            string project = Path.GetDirectoryName(stub.ScriptPath)!;

            BackendCommand command = BackendLocator.Resolve(uv, project, name => null);

            Assert.Equal(uv, command.Executable);
            Assert.Equal(new[] { "run", "--project", project, "swreview" }, command.Arguments.ToArray());
        }
    }

    [Fact]
    public void TheLocatorUsesAnExplicitSwreviewExecutableDirectly()
    {
        using (var stub = new StubBackend())
        {
            string exe = Path.Combine(Path.GetDirectoryName(stub.ScriptPath)!, "swreview.exe");
            File.WriteAllText(exe, string.Empty);

            BackendCommand command = BackendLocator.Resolve(exe, projectDirectory: null, onPath: name => null);

            Assert.Equal(exe, command.Executable);
            Assert.Empty(command.Arguments);
        }
    }

    [Fact]
    public void AnInterpreterOverrideResolvesToTheSwreviewExecutableBesideIt()
    {
        using (var stub = new StubBackend())
        {
            string root = Path.GetDirectoryName(stub.ScriptPath)!;
            string scripts = Path.Combine(root, "Scripts");
            Directory.CreateDirectory(scripts);
            string python = Path.Combine(root, "python.exe");
            File.WriteAllText(python, string.Empty);
            string exe = Path.Combine(scripts, "swreview.exe");
            File.WriteAllText(exe, string.Empty);

            BackendCommand command = BackendLocator.Resolve(python, projectDirectory: null, onPath: name => null);

            Assert.Equal(exe, command.Executable);
        }
    }

    [Fact]
    public void TheLocatorFallsBackToPathAndThenSaysExactlyWhatItLookedFor()
    {
        using (var stub = new StubBackend())
        {
            string root = Path.GetDirectoryName(stub.ScriptPath)!;
            string onPath = Path.Combine(root, "swreview.exe");
            File.WriteAllText(onPath, string.Empty);

            BackendCommand found = BackendLocator.Resolve(
                null, projectDirectory: null, onPath: name => name == "swreview" ? onPath : null);
            Assert.Equal(onPath, found.Executable);

            var failure = Assert.Throws<BackendStartException>(
                () => BackendLocator.Resolve(null, projectDirectory: null, onPath: name => null));
            Assert.Contains("swreview", failure.Message);
            Assert.Contains("uv", failure.Message);
            Assert.Contains("python", failure.Message, StringComparison.OrdinalIgnoreCase);
        }
    }

    [Fact]
    public void AnOverrideThatDoesNotExistIsReportedAgainstTheSettingsField()
    {
        var failure = Assert.Throws<BackendStartException>(
            () => BackendLocator.Resolve(
                @"C:\nowhere\at\all\uv.exe", projectDirectory: null, onPath: name => null));

        Assert.Contains("python", failure.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Contains(@"C:\nowhere\at\all\uv.exe", failure.Message);
    }

    /// <summary>Settings for the gemini provider, with this test's run root filled in later.</summary>
    private static UserSettings Gemini()
    {
        UserSettings settings = UserSettings.Defaults();
        settings.Provider = "gemini";
        settings.Model = UserSettings.DefaultModelFor("gemini");
        return settings;
    }

    /// <summary>
    /// The credential and endpoint block <see cref="BackendClient.StartOptions"/> builds for
    /// <paramref name="settings"/>, read back out of a real child process.
    ///
    /// Asserted against the child's own view rather than against the dictionary, because the
    /// bug these tests exist for is precisely that the dictionary is *merged into the parent's
    /// environment* (<see cref="ChildProcess"/>): a variable the pane does not write is not a
    /// variable the child does not have.
    /// </summary>
    private static string EnvironmentOf(StubBackend stub, JobObject job, UserSettings settings)
    {
        // `python` names the launcher BackendLocator resolves; a file called swreview.exe is
        // taken as the console script and run directly, which is all StartOptions needs.
        string launcher = Path.Combine(Path.GetDirectoryName(stub.ScriptPath)!, "swreview.exe");
        File.WriteAllText(launcher, string.Empty);
        settings.Python = launcher;
        settings.RunRoot = stub.RunRoot;

        BackendStartOptions built;
        using (var supervisor = new BackendSupervisor(() => false))
        using (var client = new BackendClient(supervisor, Path.GetDirectoryName(stub.LogPath)!, job))
        {
            built = client.StartOptions(settings, settings.ResolveApiKey(name => null));
        }

        stub.PrintsHandshake().RecordsItsEnvironment();
        BackendStartOptions options = Options(stub, job);
        foreach (KeyValuePair<string, string> variable in built.Environment)
        {
            options.Environment[variable.Key] = variable.Value;
        }

        using (BackendProcess.Start(options))
        {
            return stub.ReadEnvironmentDump();
        }
    }

    /// <summary>
    /// Sets one process environment variable for the duration of a test, then puts it back.
    ///
    /// The parent's environment is the thing under test - `ChildProcess` merges it into every
    /// child block - so there is no seam to inject here; the variable has to really be set.
    /// </summary>
    private static IDisposable Seeded(string name, string value) => new SeededVariable(name, value);

    /// <summary>
    /// Detaches this process from its console for the duration, then re-attaches it.
    ///
    /// Nothing in the add-in ever does this - it is how the test runner impersonates the
    /// console-less GUI process the add-in really lives in, because
    /// <see cref="ChildProcess.StartSuspended"/> decides how the child gets a console from
    /// whether this process has one. Every test in this class runs in the same xUnit
    /// collection, so none of them can be starting a child while the console is gone.
    /// </summary>
    private static IDisposable Detached() => new DetachedConsole();

    private sealed class DetachedConsole : IDisposable
    {
        private const uint AttachParentProcess = 0xFFFFFFFF;

        private readonly uint[] _owners;

        public DetachedConsole()
        {
            // The other processes on our console, kept so the console can be rejoined
            // afterwards: ATTACH_PARENT_PROCESS alone assumes the parent is the console's, and
            // a test runner is several processes deep.
            var attached = new uint[64];
            uint count = GetConsoleProcessList(attached, (uint)attached.Length);
            uint self = (uint)System.Diagnostics.Process.GetCurrentProcess().Id;
            _owners = count == 0 || count > attached.Length
                ? new uint[0]
                : attached.Take((int)count).Where(pid => pid != self).ToArray();

            if (count != 0)
            {
                FreeConsole();
            }
        }

        public void Dispose()
        {
            foreach (uint owner in _owners)
            {
                if (AttachConsole(owner))
                {
                    return;
                }
            }

            AttachConsole(AttachParentProcess);
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint GetConsoleProcessList(uint[] processList, uint count);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool FreeConsole();

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AttachConsole(uint processId);
    }

    private sealed class SeededVariable : IDisposable
    {
        private readonly string _name;
        private readonly string? _previous;

        public SeededVariable(string name, string value)
        {
            _name = name;
            _previous = Environment.GetEnvironmentVariable(name);
            Environment.SetEnvironmentVariable(name, value);
        }

        public void Dispose() => Environment.SetEnvironmentVariable(_name, _previous);
    }

    private static BackendStartOptions Options(StubBackend stub, JobObject job)
    {
        var options = new BackendStartOptions(stub.Command, stub.LogPath)
        {
            RunRoot = stub.RunRoot,
            AllowOrigin = Origin,
            Job = job,
            HandshakeTimeout = TimeSpan.FromSeconds(30),
            HealthTimeout = TimeSpan.FromSeconds(10),
            // The stub only handles the shutdown request when a test asks it to, so every
            // other test would otherwise sit out the production five seconds on the way to the
            // terminate. The grace period is what is under test in exactly two cases below,
            // and both state their own.
            StopGrace = TimeSpan.FromMilliseconds(500),
            HealthProbe = (origin, token) => true,
        };

        foreach (KeyValuePair<string, string> knob in stub.Knobs)
        {
            options.Environment[knob.Key] = knob.Value;
        }

        return options;
    }
}
