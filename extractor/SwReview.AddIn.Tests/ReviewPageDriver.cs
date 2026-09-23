using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// The Review page driven the way feature 009's page tests drive it: the real page in an
/// offscreen WebView2 (<see cref="OffscreenReviewPage"/>), the host end of the bridge played by
/// this class, and `window.fetch` replaced by a routed stub that answers the backend's routes
/// from what a test put there.
///
/// <b>Why one driver.</b> Every page test before feature 009 wrote its own `Drive` - its own
/// `ready` handler, its own `init`, its own fetch stub - and each stub answered every URL with
/// one body. The summary, the questions, the two views, the chips, the labels and the errors
/// all need the page to talk to several routes in one run (`/attention`, `/labels`,
/// `/snapshot`, `/reviews/{run_id}`, `/evidence`) and the host to answer rows the older
/// drivers ignore (`sessions.list`, `session.forget`, `entity.show`). One driver holds that
/// once, so a test states only what its backend and its host answer.
///
/// <b>The fetch stub is in place before the page's first call.</b> The page asks for
/// `/labels` the moment `init` names a backend, so `init` is held back until the stub has been
/// installed: the page's `ready` is recorded, the stub evaluated, and only then answered. A
/// later `ready` (a re-init after a settings save) is answered at once.
///
/// <b>An unrouted call is a 404 with an `error_class`</b>, which is exactly what an older
/// backend answers for a route it does not have - so a test that routes nothing is a test of
/// the FR-030 fallback, not a test that happens to pass because nothing was asked.
/// </summary>
internal sealed class ReviewPageDriver
{
    /// <summary>The origin the host's `init` names; every backend call starts with it.</summary>
    public const string Origin = "http://127.0.0.1:51999";

    /// <summary>The bearer token the host hands out; it travels in the header and nowhere else.</summary>
    public const string Token = "0FAKEtoken-for-the-page-tests";

    /// <summary>The document every review in these tests is of, unless a test says otherwise.</summary>
    public const string ReviewedPath = @"C:\parts\bracket.sldasm";

    private readonly List<PostedMessage> _posted = new List<PostedMessage>();
    private string? _readyId;
    private bool _booted;
    private int _starts;

    private ReviewPageDriver(CoreWebView2 page)
    {
        Page = page;
    }

    public CoreWebView2 Page { get; }

    /// <summary>The document `init` names and `review.started` names by default.</summary>
    public object? Document { get; set; } = new { path = ReviewedPath, configuration = "Default" };

    /// <summary>The `review.started` payload for the nth press (1-based), or null for the default.</summary>
    public Func<int, object>? ReviewStarted { get; set; }

    /// <summary>The items `sessions.list` and `session.forget` answer with, in the host's order.</summary>
    public List<Dictionary<string, object?>> Sessions { get; } = new List<Dictionary<string, object?>>();

    /// <summary>What `settings.save` answers: null for `settings.saved`, or an `error` payload.</summary>
    public object? SettingsSaveError { get; set; }

    /// <summary>What `review.start` answers instead of `review.started`, when set: an `error` payload.</summary>
    public object? ReviewStartError { get; set; }

    /// <summary>How many `review.start` messages the page sent.</summary>
    public int Starts => _starts;

    /// <summary>
    /// Boots the page, lets <paramref name="configure"/> set the host up before the page loads,
    /// and runs <paramref name="script"/> once `init` has been answered and settled.
    /// </summary>
    public static void Run(Action<ReviewPageDriver>? configure, Func<ReviewPageDriver, Task> script)
    {
        ReviewPageDriver? driver = null;

        OffscreenReviewPage.WithPage(
            page =>
            {
                driver = new ReviewPageDriver(page);
                configure?.Invoke(driver);
                page.WebMessageReceived += (sender, args) => driver.OnMessage(args.WebMessageAsJson);
            },
            async page =>
            {
                await driver!.BootAsync();
                await script(driver);
            });
    }

    // ---- the backend ------------------------------------------------------------------------

    /// <summary>Answers <paramref name="method"/> <paramref name="path"/> with a status and a JSON body.</summary>
    public Task Route(string method, string path, int status, string bodyJson) =>
        Page.ExecuteScriptAsync(
            "window.__fetch.routes[" + JsonSerializer.Serialize(method + " " + path) + "] = {status: "
            + status + ", body: " + bodyJson + "};0");

    /// <summary>Makes a route reject the way an unreachable backend does.</summary>
    public Task Fail(string method, string path) =>
        Page.ExecuteScriptAsync(
            "window.__fetch.routes[" + JsonSerializer.Serialize(method + " " + path) + "] = {fail: true};0");

    /// <summary>Removes a route, so it answers the older backend's 404 again.</summary>
    public Task Unroute(string method, string path) =>
        Page.ExecuteScriptAsync(
            "delete window.__fetch.routes[" + JsonSerializer.Serialize(method + " " + path) + "];0");

    /// <summary>The ranking route of one chat, answered with <paramref name="rankingJson"/>.</summary>
    public Task RouteAttention(string chatId, string rankingJson) =>
        Route("GET", "/sessions/" + chatId + "/attention", 200, rankingJson);

    /// <summary>Every backend call the page made so far: `{method, path, body, authorization}`.</summary>
    public async Task<JsonElement[]> Calls()
    {
        string raw = await Page.ExecuteScriptAsync("JSON.stringify(window.__fetch.calls)");
        string json = JsonDocument.Parse(raw).RootElement.GetString() ?? "[]";
        return JsonDocument.Parse(json).RootElement.EnumerateArray().Select(call => call.Clone()).ToArray();
    }

    /// <summary>Forgets the calls recorded so far, so a phase reads only its own.</summary>
    public Task ClearCalls() => Page.ExecuteScriptAsync("window.__fetch.calls = [];0");

    // ---- the host -----------------------------------------------------------------------------

    /// <summary>The payloads of every message of <paramref name="type"/> the page posted, in order.</summary>
    public JsonElement[] Posted(string type)
    {
        lock (_posted)
        {
            return _posted.Where(message => message.Type == type).Select(message => message.Payload).ToArray();
        }
    }

    /// <summary>The types of every message the page posted, in order.</summary>
    public string[] PostedTypes()
    {
        lock (_posted)
        {
            return _posted.Select(message => message.Type).ToArray();
        }
    }

    /// <summary>Posts one unsolicited host message.</summary>
    public async Task Post(string type, object? payload)
    {
        Page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id = (string?)null, payload }));
        await OffscreenReviewPage.Settled(Page);
    }

    /// <summary>The host says the active document changed.</summary>
    public Task DocumentChanged(object? document) => Post("document.changed", document);

    // ---- the page -----------------------------------------------------------------------------

    /// <summary>Presses Review and lets the reply settle.</summary>
    public async Task StartReview()
    {
        await Page.ExecuteScriptAsync("document.getElementById('start-review').click();0");
        await OffscreenReviewPage.Settled(Page);
    }

    /// <summary>Clicks the element with this id and lets the page react.</summary>
    public async Task Click(string elementId)
    {
        await Page.ExecuteScriptAsync("document.getElementById(" + JsonSerializer.Serialize(elementId) + ").click();0");
        await OffscreenReviewPage.Settled(Page);
    }

    /// <summary>Pushes one frame for one chat, without waiting for the page to settle.</summary>
    public Task Push(string chatId, int seq, string type, string body) =>
        SseFrames.Push(Page, chatId, SseFrames.Frame(seq, type, body));

    /// <summary>Plays the contract sample's closing pair for one chat and lets the page react.</summary>
    public async Task EndSession(string chatId)
    {
        foreach (string frame in SseFrames.ContractSampleFrames())
        {
            await SseFrames.Push(Page, chatId, frame);
        }

        await OffscreenReviewPage.Settled(Page);
    }

    public Task Settle() => OffscreenReviewPage.Settled(Page);

    /// <summary>
    /// Runs a reporting script body in the page and parses what it returned. The body returns
    /// `JSON.stringify({...})`; <see cref="Helpers"/> are in scope as `h`; a throw is reported.
    /// </summary>
    public async Task<JsonElement> Read(string body)
    {
        string raw = await Page.ExecuteScriptAsync(
            "(function () { " + Helpers + " try { " + body + " } catch (error) { "
            + "return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) }); } }())");

        Assert.False(
            string.IsNullOrEmpty(raw) || raw == "null",
            "The page script threw before it could report: " + (raw ?? "<nothing>"));

        string json = JsonDocument.Parse(raw!).RootElement.GetString()
            ?? throw new InvalidOperationException("the page reported nothing: " + raw);
        JsonElement state = JsonDocument.Parse(json).RootElement.Clone();

        if (state.TryGetProperty("ok", out JsonElement ok) && ok.ValueKind == JsonValueKind.False)
        {
            Assert.Fail(state.TryGetProperty("error", out JsonElement error) ? error.GetString() : "the page did not report");
        }

        return state;
    }

    /// <summary>The string values of one array property of a report.</summary>
    public static string[] Strings(JsonElement state, string name) =>
        state.GetProperty(name).EnumerateArray().Select(value => value.GetString() ?? string.Empty).ToArray();

    /// <summary>
    /// The helpers every read script has as `h`: text and class readers, whether a node is on
    /// screen (inside every scrolling ancestor and the window), the visible text of a subtree
    /// (skipping what a shut fold or a hidden element keeps off screen), and a reset of every
    /// scroll position so "it scrolled there" is something a click has to do.
    /// </summary>
    public const string Helpers = @"
var h = {
  texts: function (root, selector) {
    var found = root ? root.querySelectorAll(selector) : [];
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
    return out;
  },
  attrs: function (root, selector, name) {
    var found = root ? root.querySelectorAll(selector) : [];
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute(name)); }
    return out;
  },
  text: function (root, selector) {
    var node = root ? root.querySelector(selector) : null;
    return node ? node.textContent : null;
  },
  children: function (node) {
    var out = [];
    if (!node) { return out; }
    for (var i = 0; i < node.children.length; i++) { out.push(node.children[i].className); }
    return out;
  },
  rendered: function (node) {
    return !!node && node.getClientRects().length > 0 && node.checkVisibility();
  },
  before: function (a, b) {
    return !!a && !!b && !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
  },
  injected: function (node) {
    return node ? node.querySelectorAll('img,script,iframe,svg,object,embed,link,style').length : 0;
  },
  inView: function (node) {
    if (!node) { return false; }
    var rect = node.getBoundingClientRect();
    if (rect.height === 0 && rect.width === 0) { return false; }
    for (var p = node.parentElement; p; p = p.parentElement) {
      var overflow = getComputedStyle(p).overflowY;
      if (overflow === 'auto' || overflow === 'scroll') {
        var view = p.getBoundingClientRect();
        if (rect.top < view.top - 1 || rect.bottom > view.bottom + 1) { return false; }
      }
    }
    return rect.top >= -1 && rect.bottom <= window.innerHeight + 1;
  },
  resetScroll: function () {
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) { if (all[i].scrollTop) { all[i].scrollTop = 0; } }
    if (document.scrollingElement) { document.scrollingElement.scrollTop = 0; }
  },
  visibleText: function (root) {
    var out = [];
    var walk = function (node) {
      if (node.nodeType === 3) { out.push(node.nodeValue); return; }
      if (node.nodeType !== 1) { return; }
      if (node.hidden || getComputedStyle(node).display === 'none') { return; }
      if (node.tagName === 'DETAILS' && !node.open) {
        var head = node.querySelector(':scope > summary');
        if (head) { walk(head); }
        return;
      }
      for (var c = node.firstChild; c; c = c.nextSibling) { walk(c); }
      if (getComputedStyle(node).display !== 'inline') { out.push('\n'); }
    };
    if (root) { walk(root); }
    return out.join('');
  }
};
";

    // ---- plumbing -----------------------------------------------------------------------------

    private async Task BootAsync()
    {
        for (int attempt = 0; attempt < 400 && _readyId == null; attempt++)
        {
            await Page.ExecuteScriptAsync("0");
            await Task.Delay(10);
        }

        Assert.True(_readyId != null, "the Review page never sent `ready`.");

        await Page.ExecuteScriptAsync(FetchStub);
        _booted = true;
        Reply("init", _readyId!, Init());
        await OffscreenReviewPage.Settled(Page);
    }

    private void OnMessage(string json)
    {
        JsonElement message = JsonDocument.Parse(json).RootElement;
        string type = message.GetProperty("type").GetString() ?? string.Empty;
        string id = message.TryGetProperty("id", out JsonElement value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
        JsonElement payload = message.TryGetProperty("payload", out JsonElement body)
            ? body.Clone()
            : default;

        lock (_posted)
        {
            _posted.Add(new PostedMessage(type, payload));
        }

        switch (type)
        {
            case "ready":
                if (_booted)
                {
                    Reply("init", id, Init());
                }
                else
                {
                    _readyId = id;
                }

                return;

            case "models.list":
                Reply("models", id, new { provider = "openai", models = new object[0] });
                return;

            case "review.start":
                _starts++;
                if (ReviewStartError != null)
                {
                    Reply("error", id, ReviewStartError);
                    return;
                }

                Reply("review.started", id, ReviewStarted?.Invoke(_starts) ?? DefaultStarted(_starts));
                return;

            case "sessions.list":
                Reply("sessions", id, new { items = Sessions.ToArray() });
                return;

            case "session.forget":
                string chatId = payload.ValueKind == JsonValueKind.Object
                    && payload.TryGetProperty("chat_id", out JsonElement chat)
                        ? chat.GetString() ?? string.Empty
                        : string.Empty;
                Sessions.RemoveAll(item => Equals(item["chat_id"], chatId));
                Reply("sessions", id, new { items = Sessions.ToArray() });
                return;

            case "entity.show":
                Reply("entity.shown", id, new { ok = true, state_code = 0, message = "ok", full_path = "Pin-A-1" });
                return;

            case "settings.save":
                if (SettingsSaveError != null)
                {
                    Reply("error", id, SettingsSaveError);
                    return;
                }

                Reply("settings.saved", id, new { settings = Settings(), key_source = "settings" });
                return;

            default:
                return;
        }
    }

    private object DefaultStarted(int press) => new Dictionary<string, object?>
    {
        { "chat_id", "chat-" + press },
        { "run_dir", @"C:\SwReviewRuns\20260923-101500-bracket-" + press },
        { "document", Document },
    };

    private void Reply(string type, string id, object payload) =>
        Page.PostWebMessageAsJson(JsonSerializer.Serialize(new { type, id, payload }));

    private object Init() => new
    {
        backend = new { port = 51999, origin = Origin },
        token = Token,
        settings = Settings(),
        key_source = "settings",
        run_root = @"C:\SwReviewRuns",
        providers = new[] { "openai", "gemini" },
        document = Document,
    };

    private static object Settings() => new
    {
        version = 1,
        provider = "openai",
        model = "gpt-5.6",
        effort = "high",
        base_url = (string?)null,
        gemini_enterprise = (object?)null,
        terminal_cli = "codex",
        python = "uv",
        run_root = @"C:\SwReviewRuns",
    };

    /// <summary>
    /// The backend, stubbed by route. Every call is recorded with its method, its path (the
    /// origin stripped), its body and its `Authorization` header. A route answers `{status,
    /// body}` or rejects (`fail`); an unrouted call is the 404 an older backend answers.
    /// </summary>
    private const string FetchStub = @"
(function () {
  var origin = '" + Origin + @"';
  window.__fetch = { calls: [], routes: {} };
  window.fetch = function (url, request) {
    var method = (request && request.method) || 'GET';
    var path = String(url);
    if (path.indexOf(origin) === 0) { path = path.substring(origin.length); }
    var headers = (request && request.headers) || {};
    window.__fetch.calls.push({
      method: method,
      path: path,
      body: (request && request.body) ? String(request.body) : null,
      authorization: headers.Authorization || ''
    });

    var route = window.__fetch.routes[method + ' ' + path];
    if (route && route.fail) {
      return Promise.reject(new Error('the review backend is not running.'));
    }
    if (!route) {
      route = { status: 404, body: { error_class: 'NotFound', message: 'no route ' + path, retryable: false } };
    }
    var text = route.body === undefined || route.body === null ? '' : JSON.stringify(route.body);
    return Promise.resolve({
      ok: route.status >= 200 && route.status < 300,
      status: route.status,
      text: function () { return Promise.resolve(text); }
    });
  };
}());0";

    private sealed class PostedMessage
    {
        public PostedMessage(string type, JsonElement payload)
        {
            Type = type;
            Payload = payload;
        }

        public string Type { get; }

        public JsonElement Payload { get; }
    }
}
