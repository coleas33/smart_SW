using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 145A, the pages' half: every tab that holds the backend's port and token, not
/// only Review (<see cref="ReviewPageBackendRestartTests"/>), follows a settings restart. Each is
/// the real page in an offscreen WebView2, under the real CSP, with this class playing the host.
///
/// The Model check and Standards pages call their check routes themselves with the port and token
/// of their `init`, and the Remodel page keeps them so one `init` field means one thing on every
/// tab. A restart - a save's made at once, or one made after it waited - starts a backend on
/// another port with another token, and nothing told these pages: every call they made with the
/// old token was refused 401 (143A, owner question 3). Now the host posts `backend.restarted`,
/// and each page asks `ready` again - once more after an `init` already on its way, which the host
/// may have read before the new backend was up. On that `init` a page takes the new port and token
/// and leaves what the engineer is looking at as it is: a check page does not read its latest
/// check again, and the Remodel page does not read its latest run again (research 145A).
/// </summary>
public sealed class TabPagesBackendRestartTests
{
    /// <summary>`backend.restarted` as these pages' hosts post it: none of the Review tab's sentences.</summary>
    private static readonly object Restarted = new { sentences = new string[0] };

    private const string RestartedToken = "FICT-token-after-the-restart";

    /// <summary>The three tabs besides Review that hold the backend's port and token.</summary>
    public static IEnumerable<object[]> Tabs =>
        TabPageDriver.Kinds.Select(kind => new object[] { kind });

    /// <summary>The two tabs that call the backend themselves.</summary>
    public static IEnumerable<object[]> CheckTabs => new[]
    {
        new object[] { TabPageDriver.ModelCheck },
        new object[] { TabPageDriver.Standards },
    };

    [Theory]
    [MemberData(nameof(Tabs))]
    public void ABackendRestartedIsAskedForAgain(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            driver.Token = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();

            // Once: one `ready` for one restart, not one per message the page then handles.
            Assert.Equal(readies + 1, driver.Readies);
        });
    }

    /// <summary>
    /// An `init` already on its way when `backend.restarted` arrives may have been read before the
    /// new backend was up, so the page asks once more after it - not a second `ready` beside it,
    /// and not one per restart message while it waits.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void ARestartAnnouncedWhileAnInitIsOnItsWayIsFollowedByOneMoreAsk(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            driver.HoldReady = true;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies == readies + 1, "asked for init");
            await driver.Post("backend.restarted", Restarted);
            await driver.Settle();
            Assert.Equal(readies + 1, driver.Readies);
            Assert.Equal(1, driver.HeldReady);

            driver.Token = RestartedToken;
            await driver.ReleaseReady();
            await driver.Until(() => driver.Readies == readies + 2, "asked once more");
            await driver.Settle();
            Assert.Equal(readies + 2, driver.Readies);
        });
    }

    /// <summary>
    /// The page takes the restarted backend's token from that `init`: its next call - the check
    /// pressed again - carries it, and no call carries the old one, which the new backend refuses.
    /// </summary>
    [Theory]
    [MemberData(nameof(CheckTabs))]
    public void TheNextCallAfterARestartCarriesTheRestartedBackendsToken(string tab)
    {
        TabPageDriver.Run(tab, null, async driver =>
        {
            int readies = driver.Readies;
            driver.Token = RestartedToken;
            await driver.ClearCalls();

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();
            await driver.Click("run-check");
            await driver.UntilCall("POST", "a check called after the restart");

            JsonElement[] calls = await driver.Calls();
            JsonElement check = Assert.Single(calls, call => call.GetProperty("method").GetString() == "POST");
            Assert.Equal("Bearer " + RestartedToken, check.GetProperty("authorization").GetString());
            Assert.DoesNotContain(calls, call =>
                call.GetProperty("authorization").GetString() == "Bearer " + TabPageDriver.FirstToken);
        });
    }

    /// <summary>
    /// The page keeps what the engineer is looking at. A check page's result - read back from its
    /// latest check when the page loaded - stays on screen as it was, and is not read again: the
    /// restart changed the backend, not the check, and a re-read would race whatever the page
    /// shows. The Remodel page's run stays too, and is not read again: its record is the run
    /// folder, which the host reads and the restart does not touch.
    /// </summary>
    [Theory]
    [MemberData(nameof(Tabs))]
    public void WhatTheEngineerIsLookingAtStaysAndIsNotReadAgain(string tab)
    {
        TabPageDriver.Run(tab, driver => driver.WithLatestResult = true, async driver =>
        {
            await driver.UntilTheLatestResultIsRead();
            await driver.Settle();
            string before = await driver.WhatIsShown();
            int reads = await driver.LatestResultReads();
            int readies = driver.Readies;
            driver.Token = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();

            Assert.Equal(reads, await driver.LatestResultReads());
            Assert.Equal(before, await driver.WhatIsShown());
        });
    }

    /// <summary>
    /// A remodel run in progress is not the page's to end: Stop stays pressable and Start stays
    /// off through a restart's `init`, and the run is not read again under it. (The host makes no
    /// restart while a run is in progress; the run's own terminal `status` may still be on its way
    /// when the message for a restart made just after it arrives.)
    /// </summary>
    [Fact]
    public void ARemodelRunInProgressKeepsRunningThroughARestartsInit()
    {
        TabPageDriver.Run(TabPageDriver.Remodel, null, async driver =>
        {
            await driver.Click("plan-run");
            await driver.Click("start-run");
            Assert.False(await driver.Disabled("stop-run"));
            int reads = await driver.LatestResultReads();
            int readies = driver.Readies;
            driver.Token = RestartedToken;

            await driver.Post("backend.restarted", Restarted);
            await driver.Until(() => driver.Readies > readies, "asked for init again");
            await driver.Settle();

            Assert.False(await driver.Disabled("stop-run"));
            Assert.True(await driver.Disabled("start-run"));
            Assert.Equal(reads, await driver.LatestResultReads());
        });
    }

    /// <summary>
    /// One of the three pages driven as its host drives it: `ready` answered with the `init` its
    /// host sends, the page's start verbs with the reply its host gives, and - for the two check
    /// pages - `window.fetch` replaced by a stub that answers the check routes with the page's own
    /// sample and records each call with its `Authorization` header. The first `ready` is held
    /// until the stub is in place, since a check page reads its latest check the moment `init`
    /// names one.
    /// </summary>
    private sealed class TabPageDriver
    {
        public const string ModelCheck = "model-check";

        public const string Standards = "standards";

        public const string Remodel = "remodel";

        public static readonly string[] Kinds = { ModelCheck, Standards, Remodel };

        /// <summary>The page's own origin under the backend prefix, as every host's `init` names it.</summary>
        public const string Origin = "https://swreview.invalid/__backend";

        /// <summary>The token the backend started with, before any restart.</summary>
        public const string FirstToken = "FICT-token-before-the-restart";

        private const string RemodelRunDir = @"C:\SwReviewRuns\20260916-142201-bracket-remodel";

        private readonly string _kind;
        private readonly object _gate = new object();
        private readonly List<(string Type, string? Id)> _posted = new List<(string, string?)>();
        private readonly Queue<string> _heldReady = new Queue<string>();
        private string? _bootReady;
        private bool _booted;
        private int _remodelResults;

        private TabPageDriver(string kind, CoreWebView2 page)
        {
            _kind = kind;
            Page = page;
        }

        public CoreWebView2 Page { get; }

        /// <summary>The token the next `init` hands out; a restart is a new one.</summary>
        public string Token { get; set; } = FirstToken;

        /// <summary>
        /// Whether `init` names a latest result for the page to read back - a check's folder, or a
        /// remodel run's - as the host does once the page has one.
        /// </summary>
        public bool WithLatestResult { get; set; }

        /// <summary>Holds every `ready` after the boot until <see cref="ReleaseReady"/>: an `init` on its way.</summary>
        public bool HoldReady { get; set; }

        public int Readies => Count("ready");

        public int HeldReady
        {
            get
            {
                lock (_gate)
                {
                    return _heldReady.Count;
                }
            }
        }

        /// <summary>
        /// How many times the page has read its result back: each `remodel.result` it sent, or
        /// each `GET /checks/{check_id}` a check page made.
        /// </summary>
        public async Task<int> LatestResultReads()
        {
            if (_kind == Remodel)
            {
                lock (_gate)
                {
                    return _remodelResults;
                }
            }

            return (await Calls()).Count(call => call.GetProperty("method").GetString() == "GET");
        }

        /// <summary>Waits, bounded, until the page has read the latest result its `init` named.</summary>
        public async Task UntilTheLatestResultIsRead()
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (await LatestResultReads() == 0)
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never read the latest result its init named.");
                }

                await Task.Delay(5);
            }
        }

        public static void Run(string kind, Action<TabPageDriver>? configure, Func<TabPageDriver, Task> script)
        {
            TabPageDriver? driver = null;
            OffscreenReviewPage.WithPage(
                UrlOf(kind),
                page =>
                {
                    driver = new TabPageDriver(kind, page);
                    configure?.Invoke(driver);
                    page.WebMessageReceived += (sender, args) => driver.OnMessage(args.WebMessageAsJson);
                },
                async page =>
                {
                    await driver!.BootAsync();
                    await script(driver);
                });
        }

        /// <summary>Posts one unsolicited host message and lets the page handle it.</summary>
        public async Task Post(string type, object payload)
        {
            Page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id = (string?)null, payload }));
            await Settle();
        }

        public Task Settle() => OffscreenReviewPage.Settled(Page);

        /// <summary>Waits, bounded, until <paramref name="condition"/> about what the page posted holds.</summary>
        public async Task Until(Func<bool> condition, string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (!condition())
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never " + what + ".");
                }

                await Page.ExecuteScriptAsync("0");
                await Task.Delay(5);
            }
        }

        /// <summary>Waits, bounded, until the page has made a call with <paramref name="method"/>.</summary>
        public async Task UntilCall(string method, string what)
        {
            var bound = System.Diagnostics.Stopwatch.StartNew();
            while (!(await Calls()).Any(call => call.GetProperty("method").GetString() == method))
            {
                if (bound.Elapsed > TimeSpan.FromSeconds(30))
                {
                    throw new TimeoutException("the page never made " + what + ".");
                }

                await Task.Delay(5);
            }
        }

        public async Task ReleaseReady()
        {
            lock (_gate)
            {
                Assert.NotEmpty(_heldReady);
                HoldReady = false;
                while (_heldReady.Count > 0)
                {
                    Reply("init", _heldReady.Dequeue(), Init());
                }
            }

            await Settle();
        }

        public async Task Click(string elementId)
        {
            await Page.ExecuteScriptAsync("document.getElementById(" + JsonSerializer.Serialize(elementId) + ").click();0");
            await Settle();
        }

        public async Task<bool> Disabled(string elementId) =>
            JsonDocument.Parse(await Page.ExecuteScriptAsync(
                "document.getElementById(" + JsonSerializer.Serialize(elementId) + ").disabled")).RootElement.GetBoolean();

        /// <summary>Every backend call the page made since the last <see cref="ClearCalls"/>; none on the Remodel page.</summary>
        public async Task<JsonElement[]> Calls()
        {
            string raw = await Page.ExecuteScriptAsync("JSON.stringify(window.__calls || [])");
            string json = JsonDocument.Parse(raw).RootElement.GetString() ?? "[]";
            return JsonDocument.Parse(json).RootElement.EnumerateArray().Select(call => call.Clone()).ToArray();
        }

        public Task ClearCalls() => Page.ExecuteScriptAsync("window.__calls = [];0");

        /// <summary>
        /// What the engineer is looking at, read off the live page as one string: the result's
        /// header and rows, the line under the buttons and the folder on a check page; the run's
        /// folder, state, status line, change list and judgement on the Remodel page.
        /// </summary>
        public async Task<string> WhatIsShown()
        {
            string ids = _kind == Remodel
                ? "['run-dir','run-state','run-status','attestation','change-list','rebuild','judgement','banner']"
                : "['" + (_kind == ModelCheck ? "grade" : "verdict") + "','rules','check-state','run-dir','stale-result','banner']";
            string raw = await Page.ExecuteScriptAsync(
                "JSON.stringify({ shown: " + ids + ".map(function (id) { var node = document.getElementById(id); "
                + "return id + '=' + (node.hidden ? '[hidden]' : '') + node.textContent; })"
                + ".concat(['stale=' + document.body.classList.contains('result-stale')]).join(' | '), "
                + "rows: document.querySelectorAll('.rule, #change-list li').length })");
            JsonElement read = JsonDocument.Parse(JsonDocument.Parse(raw).RootElement.GetString() ?? "{}").RootElement;

            // A result is on screen to keep: rows of it, rendered from the latest result.
            Assert.True(read.GetProperty("rows").GetInt32() > 0, "no result is on screen: " + read.GetRawText());
            return read.GetProperty("shown").GetString() ?? string.Empty;
        }

        private static string UrlOf(string kind)
        {
            switch (kind)
            {
                case ModelCheck:
                    return ModelCheckPageFiles.PageUrl;
                case Standards:
                    return StandardsPageFiles.PageUrl;
                case Remodel:
                    return RemodelPageFiles.PageUrl;
                default:
                    throw new ArgumentOutOfRangeException(nameof(kind), kind, "no tab of that name");
            }
        }

        private int Count(string type)
        {
            lock (_gate)
            {
                return _posted.Count(message => message.Type == type);
            }
        }

        private async Task BootAsync()
        {
            for (int attempt = 0; attempt < 400 && _bootReady == null; attempt++)
            {
                await Page.ExecuteScriptAsync("0");
                await Task.Delay(10);
            }

            Assert.True(_bootReady != null, "the " + _kind + " page never sent `ready`.");
            if (_kind != Remodel)
            {
                await Page.ExecuteScriptAsync(FetchStub(SampleJson()));
            }

            lock (_gate)
            {
                _booted = true;
                Reply("init", _bootReady!, Init());
            }

            await Settle();
        }

        private void OnMessage(string json)
        {
            JsonElement message = JsonDocument.Parse(json).RootElement;
            string type = message.GetProperty("type").GetString() ?? string.Empty;
            string? id = message.TryGetProperty("id", out JsonElement value) && value.ValueKind == JsonValueKind.String
                ? value.GetString()
                : null;

            lock (_gate)
            {
                _posted.Add((type, id));
                switch (type)
                {
                    case "ready":
                        if (!_booted)
                        {
                            _bootReady = id;
                        }
                        else if (HoldReady)
                        {
                            _heldReady.Enqueue(id!);
                        }
                        else
                        {
                            Reply("init", id, Init());
                        }

                        return;

                    case "check.start":
                        Reply("check.extracted", id, new
                        {
                            run_dir = @"C:\SwReviewRuns\20260916-101532-bracket-check",
                            document = @"C:\vault\bracket.sldprt",
                            configuration = "Default",
                            counts = new { documents = 1, features = 12, equations = 0 },
                            gaps = 0,
                        });
                        return;

                    case "standards.start":
                        Reply("standards.extracted", id, new
                        {
                            run_dir = @"C:\SwReviewRuns\20260917-101532-top-plate-standards",
                            document = @"C:\vault\top-plate.sldasm",
                            configuration = "AsBuilt",
                            counts = new { documents = 1, features = 12, cut_list_items = 0, drawing_sheets = 0 },
                            gaps = 0,
                        });
                        return;

                    case "remodel.plan":
                        Reply("remodel.planned", id, new
                        {
                            run_dir = RemodelRunDir,
                            plan_summary = JsonDocument.Parse(RemodelResultSample.PlanSummaryJson()).RootElement.Clone(),
                        });
                        return;

                    case "remodel.start":
                        Reply("remodel.started", id, new { chat_id = "20260916-142201-bracket-remodel" });
                        return;

                    case "remodel.result":
                        _remodelResults++;
                        Reply("remodel.result", id, JsonDocument.Parse(RemodelResultSample.ResultJson()).RootElement.Clone());
                        return;

                    default:
                        Reply("ok", id, new { });
                        return;
                }
            }
        }

        /// <summary>The `init` each host sends, for the backend that holds <see cref="Token"/>.</summary>
        private object Init()
        {
            object backend = new { port = 51234, origin = Origin };
            switch (_kind)
            {
                case ModelCheck:
                    return new
                    {
                        backend,
                        token = Token,
                        run_root = @"C:\SwReviewRuns",
                        standards_profile = (string?)null,
                        document = new { path = @"C:\vault\bracket.sldprt", configuration = "Default", kind = "part" },
                        latest_check = WithLatestResult
                            ? new { run_dir = @"C:\SwReviewRuns\20260916-101532-bracket-check", at = "2026-09-16T10:15:32.0000000" }
                            : null,
                    };

                case Standards:
                    return new
                    {
                        backend,
                        token = Token,
                        run_root = @"C:\SwReviewRuns",
                        profile_path = @"C:\Fictional\FICT-standards.yaml",
                        document = new { path = @"C:\vault\top-plate.sldasm", configuration = "AsBuilt", kind = "assembly" },
                        latest_check = WithLatestResult
                            ? new { run_dir = @"C:\SwReviewRuns\20260917-101532-top-plate-standards", at = "2026-09-17T10:15:32.0000000" }
                            : null,
                    };

                default:
                    return new
                    {
                        backend,
                        token = Token,
                        run_root = @"C:\SwReviewRuns",
                        document = new { path = @"C:\vault\bracket.sldprt", configuration = "Default", kind = "part" },
                        limits = new { max_changes = 250, max_minutes = 20, max_rebuild_seconds = 120 },
                        remodel = new { available = true, message = (string?)null },
                        latest_run = WithLatestResult
                            ? new { run_dir = RemodelRunDir, at = "2026-09-16T14:22:01.0000000", state = "saved", plan_lost = (string?)null }
                            : null,
                    };
            }
        }

        private string SampleJson() => _kind == ModelCheck ? CheckResultSample.Json() : StandardsResultSample.Json();

        /// <summary>
        /// Every check route answered with this page's sample, each call recorded with its method,
        /// its path with the origin stripped, and its `Authorization` header.
        /// </summary>
        private static string FetchStub(string sample) => @"
(function () {
  var origin = '" + Origin + @"';
  var sample = " + sample + @";
  window.__calls = [];
  window.fetch = function (url, request) {
    var path = String(url);
    if (path.indexOf(origin) === 0) { path = path.substring(origin.length); }
    var headers = (request && request.headers) || {};
    window.__calls.push({
      method: (request && request.method) || 'GET',
      path: path,
      authorization: headers.Authorization || ''
    });
    return Promise.resolve({
      ok: true,
      status: 200,
      text: function () { return Promise.resolve(JSON.stringify(sample)); }
    });
  };
}());0";

        private void Reply(string type, string? id, object payload) =>
            Page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id, payload }));
    }
}
