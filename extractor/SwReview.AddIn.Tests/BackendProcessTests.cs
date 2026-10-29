using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;
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
///   because that block is the parent's environment with the pane's values merged over it;
/// - when the key copied there is the one saved in the pane, the command line names its
///   provider (`--settings-key-provider`, owner decision 138A), because the backend cannot
///   tell that from its environment and the session has to name the credential to revoke.
/// </summary>
[Collection(StubChildrenCollection.Name)]
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

    // ---- a start no longer wanted (owner decision 143A) ------------------------------------

    /// <summary>
    /// A start the add-in no longer wants - SOLIDWORKS unloading while a restart for settings
    /// saved during a turn is under way on the host's own thread - stops waiting for the
    /// handshake at once, not at its timeout, and stops the child it started.
    /// </summary>
    [Fact]
    public void AStartNoLongerWantedStopsWaitingForTheHandshakeAndStopsItsChild()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (var unloading = new CancellationTokenSource())
        {
            stub.PrintsNothing().RecordsThatItRan();
            BackendStartOptions options = Options(stub, job);
            options.HandshakeTimeout = TimeSpan.FromSeconds(60);
            options.Cancellation = unloading.Token;

            BackendStartException failure = StoppedWhenAsked(options, () => File.Exists(stub.MarkerPath), unloading);

            Assert.StartsWith("the backend start was stopped before the backend was ready", failure.Message, StringComparison.Ordinal);
            Assert.NotNull(failure.ProcessId);
            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(failure.ProcessId!.Value)));
        }
    }

    /// <summary>...and stops waiting for `/health` too, between probes.</summary>
    [Fact]
    public void AStartNoLongerWantedStopsWaitingForHealthAndStopsItsChild()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (var unloading = new CancellationTokenSource())
        using (var probed = new ManualResetEventSlim(false))
        {
            stub.PrintsHandshake();
            BackendStartOptions options = Options(stub, job);
            options.HealthTimeout = TimeSpan.FromSeconds(60);
            options.HealthProbe = (origin, token) =>
            {
                probed.Set();
                return false;
            };
            options.Cancellation = unloading.Token;

            BackendStartException failure = StoppedWhenAsked(options, () => probed.IsSet, unloading);

            Assert.StartsWith("the backend start was stopped before the backend was ready", failure.Message, StringComparison.Ordinal);
            Assert.NotNull(failure.ProcessId);
            Assert.True(StubBackend.Waits(() => !ProcessLifetimeTests.IsRunning(failure.ProcessId!.Value)));
        }
    }

    /// <summary>A start asked for once it is no longer wanted starts nothing: no log, no child.</summary>
    [Fact]
    public void AStartAskedForOnceNoLongerWantedStartsNothing()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (var unloading = new CancellationTokenSource())
        {
            stub.PrintsHandshake().RecordsThatItRan();
            BackendStartOptions options = Options(stub, job);
            unloading.Cancel();
            options.Cancellation = unloading.Token;

            var failure = Assert.Throws<BackendStartException>(() => BackendProcess.Start(options));

            Assert.StartsWith("the backend start was stopped before the backend was ready", failure.Message, StringComparison.Ordinal);
            Assert.Null(failure.ProcessId);
            Thread.Sleep(500);
            Assert.False(File.Exists(stub.MarkerPath), "a child was started");
            Assert.False(File.Exists(stub.LogPath), "a log was opened");
        }
    }

    /// <summary>
    /// Disposing the client - the add-in unloading, on the SOLIDWORKS thread - tells a start in
    /// flight to stop before it waits for the gate that start holds, so the unload waits for the
    /// start to stop its child, not for the new backend's handshake and health; and a restart
    /// asked for after that starts nothing. The supervisor's own check stands in for the start in
    /// flight: it runs on the restart's thread, inside the gate.
    /// </summary>
    [Fact]
    public void DisposingTheClientStopsARestartInFlightRatherThanWaitingForIt()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (var inside = new ManualResetEventSlim(false))
        using (var release = new ManualResetEventSlim(false))
        {
            UserSettings settings = UserSettings.Defaults();
            string launcher = Path.Combine(Path.GetDirectoryName(stub.ScriptPath)!, "swreview.exe");
            File.WriteAllText(launcher, string.Empty);
            settings.Python = launcher;
            settings.RunRoot = stub.RunRoot;
            ResolvedApiKey key = settings.ResolveApiKey(_ => null);

            var supervisor = new BackendSupervisor(() =>
            {
                inside.Set();
                release.Wait(TimeSpan.FromSeconds(30));
                return false;
            });
            var client = new BackendClient(supervisor, Path.GetDirectoryName(stub.LogPath)!, job);
            CancellationToken handedOut = client.StartOptions(settings, key).Cancellation;

            Exception? restarted = null;
            var restarting = new Thread(() =>
            {
                try
                {
                    client.Restart(settings, key);
                }
                catch (Exception caught)
                {
                    restarted = caught;
                }
            })
            {
                IsBackground = true,
                Name = "fict-restart-in-flight",
            };
            restarting.Start();
            Assert.True(inside.Wait(TimeSpan.FromSeconds(10)), "the restart never got inside the gate");

            var disposing = new Thread(client.Dispose) { IsBackground = true, Name = "fict-unload" };
            disposing.Start();

            // Told to stop while the restart still holds the gate.
            Assert.True(
                StubBackend.Waits(() => handedOut.IsCancellationRequested, 5000),
                "the client waited for the start in flight before telling it to stop");
            Assert.True(restarting.IsAlive);

            release.Set();
            Assert.True(restarting.Join(TimeSpan.FromSeconds(15)), "the restart in flight did not stop");
            Assert.True(disposing.Join(TimeSpan.FromSeconds(15)), "the client's dispose did not finish");
            var stopped = Assert.IsType<BackendStartException>(restarted);
            Assert.StartsWith("the backend start was stopped before the backend was ready", stopped.Message, StringComparison.Ordinal);

            var late = Assert.Throws<BackendStartException>(() => client.Restart(settings, key));
            Assert.Equal("the add-in is unloading, so the backend was not started.", late.Message);
        }
    }

    /// <summary>
    /// Starts <paramref name="options"/> on a thread of its own, cancels once <paramref name="reached"/>
    /// holds, and answers the start's failure - having asserted the start ended within seconds of
    /// the cancel, far inside the minute its own timeout would have taken.
    /// </summary>
    private static BackendStartException StoppedWhenAsked(
        BackendStartOptions options, Func<bool> reached, CancellationTokenSource unloading)
    {
        Exception? outcome = null;
        var starting = new Thread(() =>
        {
            try
            {
                BackendProcess.Start(options).Dispose();
            }
            catch (Exception caught)
            {
                outcome = caught;
            }
        })
        {
            IsBackground = true,
            Name = "fict-backend-start",
        };
        starting.Start();
        Assert.True(StubBackend.Waits(reached), "the start never got as far as the wait it is stopped in");

        unloading.Cancel();
        Assert.True(starting.Join(TimeSpan.FromSeconds(15)), "the start kept waiting after it was no longer wanted");
        return Assert.IsType<BackendStartException>(outcome);
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

    // ---- where the key came from (owner decision 138A) --------------------------------------

    /// <summary>The key saved in the pane. Built from fragments and not provider-shaped.</summary>
    private const string SavedKey = "fict" + "-pane-saved-" + "0138a";

    /// <summary>A key the workstation exports for itself, inherited from SLDWORKS.exe.</summary>
    private const string WorkstationKey = "fict" + "-workstation-" + "0138a";

    [Theory]
    [InlineData("openai")]
    [InlineData(null)]
    public void TheSettingsKeyProviderIsOnTheCommandLineAndTheKeyIsNot(string? provider)
    {
        // The backend finds the key in its environment either way and cannot tell by itself
        // that it is the one saved in the pane; the session records `settings` only when the
        // add-in says so. A statement, not a credential, so it travels as a start argument
        // beside --run-root and --allow-origin, and the key itself still never does (FR-015).
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake().RecordsItsCommandLine();
            BackendStartOptions options = Options(stub, job);
            options.Environment["OPENAI_API_KEY"] = SavedKey;
            options.Secrets.Add(SavedKey);
            options.SettingsKeyProvider = provider;

            using (BackendProcess.Start(options))
            {
                string commandLine = stub.ReadCommandLine();

                Assert.DoesNotContain(SavedKey, commandLine);
                if (provider == null)
                {
                    Assert.DoesNotContain("--settings-key-provider", commandLine);
                }
                else
                {
                    Assert.Contains("--settings-key-provider " + provider, commandLine);
                }
            }
        }
    }

    [Theory]
    // Both present: the saved key wins (ResolveApiKey) and its provider is named.
    [InlineData("openai", "saved", WorkstationKey, "openai")]
    [InlineData("openai", "saved", null, "openai")]
    [InlineData("gemini", "saved", WorkstationKey, "gemini")]
    // No saved key: the environment's key is copied through and nothing is named.
    [InlineData("openai", null, WorkstationKey, null)]
    [InlineData("openai", null, null, null)]
    // A stored key this Windows account cannot decrypt falls back to the environment's.
    [InlineData("openai", "undecryptable", WorkstationKey, null)]
    // The scripted provider reads no key, so none is copied into the environment or named.
    [InlineData("fake", "saved", null, null)]
    public void StartOptionsNamesTheProviderOnlyWhenItCopiedTheSavedKey(
        string provider, string? stored, string? environmentKey, string? named)
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            UserSettings settings = UserSettings.Defaults();
            settings.Provider = provider;
            settings.Model = UserSettings.DefaultModelFor(provider);
            if (stored == "saved")
            {
                settings.SetApiKey(SavedKey);
            }
            else if (stored == "undecryptable")
            {
                settings.ApiKeyProtected = "this is not base64 !!!";
            }

            BackendStartOptions built = StartOptionsFor(stub, job, settings, name => environmentKey);

            Assert.Equal(named, built.SettingsKeyProvider);
            if (named != null)
            {
                // The statement is true of what was copied: every variable the provider
                // reads holds the saved key, so no inherited one can be what the backend finds.
                foreach (string variable in provider == "gemini"
                    ? new[] { "GOOGLE_API_KEY", "GEMINI_API_KEY" }
                    : new[] { "OPENAI_API_KEY" })
                {
                    Assert.Equal(SavedKey, built.Environment[variable]);
                }
            }
        }
    }

    [Fact]
    public void ASavedKeyAndAWorkstationKeyStartTheBackendWithTheSavedOneAndItsProviderNamed()
    {
        // The case 138A is about, read back out of a real child: the workstation exports a
        // personal key, the engineer saved another in the pane. The child's environment holds
        // the saved one, its command line names the provider - and holds neither key.
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (Seeded("OPENAI_API_KEY", WorkstationKey))
        {
            UserSettings settings = UserSettings.Defaults();
            settings.SetApiKey(SavedKey);

            (string commandLine, string environment) =
                Launched(stub, job, settings, Environment.GetEnvironmentVariable);

            Assert.Contains("--settings-key-provider openai", commandLine);
            Assert.DoesNotContain(SavedKey, commandLine);
            Assert.DoesNotContain(WorkstationKey, commandLine);
            Assert.Contains("OPENAI_API_KEY=" + SavedKey, environment);
            Assert.DoesNotContain(WorkstationKey, environment);
        }
    }

    [Fact]
    public void AWorkstationKeyAloneStartsTheBackendWithNothingNamed()
    {
        // No key saved in the pane: the workstation's key is the one used, the backend records
        // `env`, and the command line says nothing about the settings.
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        using (Seeded("OPENAI_API_KEY", WorkstationKey))
        {
            (string commandLine, string environment) =
                Launched(stub, job, UserSettings.Defaults(), Environment.GetEnvironmentVariable);

            Assert.DoesNotContain("--settings-key-provider", commandLine);
            Assert.DoesNotContain(WorkstationKey, commandLine);
            Assert.Contains("OPENAI_API_KEY=" + WorkstationKey, environment);
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

    /// <summary>
    /// Owner decision 163A, test first (004 T307; research R25, item 1): a restart that closes the old backend's leftover in
    /// process must know that backend can send the bridge nothing more, so its stop returns only once every process of the
    /// tree has exited - the launcher and the server below it - and says so. <see cref="BackendProcess.Dispose"/> does not
    /// wait for the grandchild: closing the job ends it, but later, which is why the cases above wait for it.
    /// </summary>
    [Fact]
    public void AStopForARestartReturnsOnlyOnceTheWholeTreeHasExited()
    {
        using (var first = new StubBackend())
        using (var job = new JobObject())
        {
            first.PrintsHandshake(port: 40311).SpawnsAGrandchild();

            using (var supervisor = new BackendSupervisor(() => false))
            {
                int launcherPid = supervisor.Start(Options(first, job)).ProcessId;
                int grandchildPid = first.ReadGrandchildProcessId();
                Assert.True(ProcessLifetimeTests.IsRunning(grandchildPid));

                Assert.True(supervisor.StopForRestart());

                Assert.False(ProcessLifetimeTests.IsRunning(launcherPid), "the launcher outlived the stop");
                Assert.False(ProcessLifetimeTests.IsRunning(grandchildPid), "the server below the launcher outlived the stop");
                Assert.Null(supervisor.Current);
            }
        }
    }

    /// <summary>
    /// Owner decision 163A, test first (004 T307; research R25): the stop for a restart keeps the supervisor's one rule - never
    /// while a turn is running - as <see cref="BackendSupervisor.Restart"/> keeps it, refusing before it stops anything.
    /// </summary>
    [Fact]
    public void AStopForARestartIsRefusedWhileATurnIsRunningAndLeavesTheProcessAlone()
    {
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake(port: 40321);

            using (var supervisor = new BackendSupervisor(() => true))
            {
                BackendProcess before = supervisor.Start(Options(stub, job));

                Assert.Throws<TurnRunningException>(() => supervisor.StopForRestart());

                Assert.Same(before, supervisor.Current);
                Assert.True(ProcessLifetimeTests.IsRunning(before.ProcessId));
            }
        }
    }

    /// <summary>
    /// The review round of owner decision 163A, test first (Codex, high; 004 T310, research R25.10): the client's stop for a
    /// restart, and its restart, hold the start gate while the supervisor asks whether a turn runs - one call per chat, each
    /// waiting up to 30 seconds on a backend that accepts and never answers. Unloading the add-in disposes the client on the
    /// SOLIDWORKS thread, which waits for that gate: it waited for every one of those calls. The unload now ends them - the
    /// call in flight is aborted, and no further one is made - so the client's dispose ends promptly.
    /// </summary>
    [Theory]
    [InlineData("a stop for a restart")]
    [InlineData("a restart")]
    public void DisposingTheClientWhileItsTurnScanWaitsOnABackendThatDoesNotAnswerEndsPromptly(string what)
    {
        using (var silent = new SilentLoopback())
        using (var stub = new StubBackend())
        using (var job = new JobObject())
        {
            stub.PrintsHandshake(port: silent.Port);
            UserSettings settings = UserSettings.Defaults();
            string launcher = Path.Combine(Path.GetDirectoryName(stub.ScriptPath)!, "swreview.exe");
            File.WriteAllText(launcher, string.Empty);
            settings.Python = launcher;
            settings.RunRoot = stub.RunRoot;
            ResolvedApiKey key = settings.ResolveApiKey(_ => null);

            BackendClient? client = null;
            var supervisor = new BackendSupervisor(() =>
            {
                // As the review host asks it: each tracked chat in turn, no answer read as no turn.
                foreach (string chat in new[] { "fict-chat-1", "fict-chat-2", "fict-chat-3" })
                {
                    try
                    {
                        client!.IsTurnRunning(chat);
                    }
                    catch (BackendRequestException)
                    {
                    }
                }

                return false;
            });
            supervisor.Start(Options(stub, job));
            client = new BackendClient(supervisor, Path.GetDirectoryName(stub.LogPath)!, job);

            var making = new Thread(() =>
            {
                try
                {
                    if (what == "a restart")
                    {
                        client.Restart(settings, key);
                    }
                    else
                    {
                        client.StopForRestart();
                    }
                }
                catch (Exception)
                {
                    // Refused once unloading, or stopped: either way it has ended.
                }
            })
            {
                IsBackground = true,
                Name = "fict-restart-scanning",
            };
            making.Start();
            Assert.True(silent.Asked.Wait(TimeSpan.FromSeconds(10)), "the turn scan never asked the backend");

            var clock = System.Diagnostics.Stopwatch.StartNew();
            var disposing = new Thread(client.Dispose) { IsBackground = true, Name = "fict-unload" };
            disposing.Start();

            Assert.True(
                disposing.Join(TimeSpan.FromSeconds(15)),
                "the client's dispose waited for the turn scan's calls to a backend that does not answer");
            Assert.True(making.Join(TimeSpan.FromSeconds(15)), "the scan did not end");
            Assert.True(clock.Elapsed < TimeSpan.FromSeconds(15), $"the dispose took {clock.Elapsed}");
            Assert.Equal(1, silent.Connections);
            supervisor.Dispose();
        }
    }

    /// <summary>
    /// The review round of owner decision 163A, test first (mutation X8; 004 T310, research R25.10): a stop for a restart
    /// with no backend running - none started, or the last one stopped - has nothing that could still reach the bridge, and
    /// says so: the close in process may go ahead.
    /// </summary>
    [Fact]
    public void AStopForARestartWithNoBackendRunningAnswersThatNothingIsLeft()
    {
        using (var supervisor = new BackendSupervisor(() => false))
        {
            Assert.Null(supervisor.Current);
            Assert.True(supervisor.StopForRestart());
            Assert.True(supervisor.StopForRestart());
        }
    }

    /// <summary>
    /// The review round of owner decision 163A (mutations M86 and X4; 004 T310, research R25.10): the job's end-and-wait
    /// answers from the job's process count - the kernel's, read through a seam here - and not from the time it took. It
    /// waits while the count is not zero, and answers that a process is left when the bound runs out first; a closed job
    /// answers the same, never throwing.
    /// </summary>
    [Fact]
    public void EndingTheJobWaitsForItsProcessCountAndSaysWhenTheBoundRunsOutFirst()
    {
        using (var job = new JobObject())
        {
            int reads = 0;
            Assert.True(job.EndAll(TimeSpan.FromSeconds(10), () => ++reads < 4 ? 1u : 0u));
            Assert.Equal(4, reads);

            var clock = System.Diagnostics.Stopwatch.StartNew();
            Assert.False(job.EndAll(TimeSpan.FromMilliseconds(200), () => 1u));
            Assert.True(clock.Elapsed >= TimeSpan.FromMilliseconds(200), $"it answered after {clock.Elapsed}");

            Assert.False(job.EndAll(TimeSpan.FromSeconds(1), () => throw new InvalidOperationException("FICT the job cannot be read.")));
        }

        var closed = new JobObject();
        closed.Dispose();
        Assert.False(closed.EndAll(TimeSpan.FromSeconds(1)));
    }

    /// <summary>
    /// A loopback port that accepts connections and never answers on them - a backend alive but stuck - counting what it
    /// accepted. Disposing it closes every connection, so whatever still waits on one ends.
    /// </summary>
    private sealed class SilentLoopback : IDisposable
    {
        private readonly System.Net.Sockets.TcpListener _listener =
            new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);

        private readonly List<System.Net.Sockets.TcpClient> _accepted = new List<System.Net.Sockets.TcpClient>();

        public SilentLoopback()
        {
            _listener.Start();
            Port = ((System.Net.IPEndPoint)_listener.LocalEndpoint).Port;
            new Thread(Accept) { IsBackground = true, Name = "fict-silent-backend" }.Start();
        }

        public int Port { get; }

        public ManualResetEventSlim Asked { get; } = new ManualResetEventSlim(false);

        public int Connections
        {
            get
            {
                lock (_accepted)
                {
                    return _accepted.Count;
                }
            }
        }

        public void Dispose()
        {
            _listener.Stop();
            lock (_accepted)
            {
                foreach (System.Net.Sockets.TcpClient client in _accepted)
                {
                    client.Close();
                }
            }
        }

        private void Accept()
        {
            try
            {
                while (true)
                {
                    System.Net.Sockets.TcpClient client = _listener.AcceptTcpClient();
                    lock (_accepted)
                    {
                        _accepted.Add(client);
                    }

                    Asked.Set();
                }
            }
            catch (Exception)
            {
                // Stopped.
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
    /// <paramref name="settings"/>, with no key in the environment, read back out of a real
    /// child process.
    /// </summary>
    private static string EnvironmentOf(StubBackend stub, JobObject job, UserSettings settings) =>
        Launched(stub, job, settings, name => null).Environment;

    /// <summary>
    /// What <see cref="BackendClient.StartOptions"/> builds for <paramref name="settings"/>, the
    /// key resolved against <paramref name="environment"/>, launched as a real child: its
    /// command line and its own view of its environment.
    ///
    /// Asserted against the child's own view rather than against the dictionary, because the
    /// bug these tests exist for is precisely that the dictionary is *merged into the parent's
    /// environment* (<see cref="ChildProcess"/>): a variable the pane does not write is not a
    /// variable the child does not have.
    /// </summary>
    private static (string CommandLine, string Environment) Launched(
        StubBackend stub, JobObject job, UserSettings settings, Func<string, string?> environment)
    {
        BackendStartOptions built = StartOptionsFor(stub, job, settings, environment);

        stub.PrintsHandshake().RecordsItsCommandLine().RecordsItsEnvironment();
        BackendStartOptions options = Options(stub, job);
        foreach (KeyValuePair<string, string> variable in built.Environment)
        {
            options.Environment[variable.Key] = variable.Value;
        }

        options.SettingsKeyProvider = built.SettingsKeyProvider;

        using (BackendProcess.Start(options))
        {
            return (stub.ReadCommandLine(), stub.ReadEnvironmentDump());
        }
    }

    /// <summary>
    /// <see cref="BackendClient.StartOptions"/> for <paramref name="settings"/>, the key resolved
    /// against <paramref name="environment"/>, with this stub's folder as the launcher's home.
    /// </summary>
    private static BackendStartOptions StartOptionsFor(
        StubBackend stub, JobObject job, UserSettings settings, Func<string, string?> environment)
    {
        // `python` names the launcher BackendLocator resolves; a file called swreview.exe is
        // taken as the console script and run directly, which is all StartOptions needs.
        string launcher = Path.Combine(Path.GetDirectoryName(stub.ScriptPath)!, "swreview.exe");
        File.WriteAllText(launcher, string.Empty);
        settings.Python = launcher;
        settings.RunRoot = stub.RunRoot;

        using (var supervisor = new BackendSupervisor(() => false))
        using (var client = new BackendClient(supervisor, Path.GetDirectoryName(stub.LogPath)!, job))
        {
            return client.StartOptions(settings, settings.ResolveApiKey(environment));
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
    /// whether this process has one. Every class that starts a stub child runs in one xUnit
    /// collection (<see cref="StubChildrenCollection"/>), so none of them can be starting or
    /// stopping a child while the console is gone.
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
