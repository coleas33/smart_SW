# Task Pane pages cannot reach the loopback backend behind a web filter

Handoff for finishing the same-origin backend proxy. Diagnosed and started on the pilot
workstation (SOLIDWORKS 2024, WebView2 153.0.4234.32, Sophos Endpoint) against `main`
`8b09438`.

**Status (updated 2026-09-16): done.** Root cause proven, the proxy built, and the one thing
that blocked it - WebView2 raises no `WebResourceRequested` for a virtual host mapped to a
folder, so the page's own origin could not be intercepted - resolved by dropping the mapping
and serving every page file from the host through the same handler (option B). The pane is now
one origin: `connect-src 'self'`, no CORS anywhere, and no page request to loopback at all.
Section 4 has the evidence and the file list.

---

## 1. The problem

Every Task Pane page showed `Failed to fetch`. The Review tab never displayed a finding,
the Model check tab never returned a grade, and the telemetry panel read
"No model round trips yet".

**The engine was fine the whole time.** A review ran to completion and wrote a 23 KB
`report.md` with a real finding. Only the UI was blind.

### Root cause

**Sophos Web Protection intercepts HTTP from browser processes** and answers
`http://127.0.0.1:<port>` with a "Warning: Uncategorized" warn interstitial. The Task
Pane's WebView2 is a browser process. A `fetch()` cannot click through an interstitial, so
every page call received Sophos's `403` - carrying no CORS headers - instead of the
backend's `204`.

Requests made by the add-in's **own C# code are not intercepted**, which is exactly why
`POST /sessions`, `GET /models` and `POST /remodel/probe` all worked while the pages got
nothing.

### How to prove it in one command

```powershell
# Non-browser: the real backend answers.
Invoke-WebRequest "http://127.0.0.1:<port>/health" -UseBasicParsing   # 401 from the Guard

# Browser: Sophos answers instead.
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  --headless=new --disable-gpu --no-first-run --user-data-dir="$env:TEMP\probe" `
  --dump-dom "http://127.0.0.1:<port>/health"
```

The second prints:

```
Warning: Uncategorized
Location: http://127.0.0.1/health
Your organization's policy is to warn you about websites in the category Uncategorized.
sophos web protection
```

### Dead ends, so they are not repeated

| Hypothesis | Why it was wrong |
|---|---|
| Chromium Local Network Access (LNA) | Microsoft's [WebView2 announcement #126](https://github.com/MicrosoftEdge/WebView2Announcements/issues/126) states LNA is **disabled by default** for WebView2 apps; the force-allow flag `msWebViewAllowLocalNetworkAccessChecks` is off. |
| Backend missing CORS headers | A raw socket capture shows `access-control-allow-origin`, `vary`, `allow-headers`, `allow-methods`, `max-age` and `allow-private-network` all present on the 204. |
| The `Guard`'s origin-mismatch branch | It would log `refused a request from origin` and return 403; the backend log shows neither - only 204s. |
| A configured proxy | `ProxyEnable=0`, no `AutoConfigURL`. |
| A WebView2 browser flag would fix it | `AdditionalBrowserArguments` **silently ignores** switches WebView2 rejects, so a flag cannot even distinguish "not the cause" from "never applied". |

Two diagnostic notes worth keeping:

- **`OPTIONS` 204 in the backend log with `403` in DevTools is the signature.** The request
  reaches uvicorn; the response is replaced in flight. Do not trust either log alone.
- A preflight re-sent repeatedly **despite `Access-Control-Max-Age: 600`** means the
  browser is rejecting the response rather than caching it.

---

## 2. The fix

Stop the page from crossing the network boundary at all.

The pages are told their backend lives at **their own origin**,
`https://swreview.invalid/__backend`. WebView2 raises `WebResourceRequested` for that
prefix and the host serves it by calling loopback from C#. Same-origin means no CORS, no
preflight, and nothing for a web filter to classify.

> The second sentence did not survive contact as written: WebView2 raises that event for
> everything **except** a host mapped with `SetVirtualHostNameToFolderMapping`, which is how
> these pages used to be served. The mapping is gone and the host serves the page files through
> the same event, which is what makes the paragraph above true as written. See section 4.

### Why not the alternatives

| Option | Verdict |
|---|---|
| Same-origin proxy through the host | **Chosen.** Immune to web filters and to browser policy changes, needs no admin and no IT ticket, and travels with the product. |
| Sophos exclusion for `127.0.0.1` | Fixes one workstation, needs an IT change request, and leaves every other locked-down seat broken. Worth doing anyway as an interim unblock. |
| Browser flag to relax the check | Rejected: WebView2 silently ignores flags it blocks, and the cause is not a browser policy. |
| `SLDWORKS.exe.config` | Irrelevant to this cause, and modifies a vendor installation. |

### The one hard constraint

**`WebResourceRequested` cannot stream.** WebView2 documents that the response stream
"must have all the content data available by the time the ... deferral ... is completed",
and [WebView2Feedback #3519](https://github.com/MicrosoftEdge/WebView2Feedback/issues/3519)
confirms server-sent events are unsupported - plus WebView2 reads every response stream on
a **single background thread**, so one blocking read stalls every other request in the
control.

So `GET /sessions/{chat_id}/events` cannot be proxied. The host reads that route itself
and pushes each SSE frame to the page over the existing message channel.

### Scope: only two pages fetch

```
Review/ReviewPage/app.js      call() + the event stream   -> needs the proxy
Model/ModelCheckPage/check.js call()                      -> needs the proxy
Remodel page                  no fetch at all             -> unaffected
Terminal ("Ask") page         no fetch at all             -> unaffected
```

Remodel's backend work is all host-side (`Remodel/RemodelBackendClient.cs`), so it already
works through a web filter. All three hosts that send `backend.origin` send the same value,
`BackendProxy.PageOrigin`, so a fetch added to the Remodel page later is same-origin by
default rather than refused by that page's own CSP.

---

## 3. What is already built

Both are now wired, and section 4's Done table says where. `TaskPaneControl.AttachPageAsync`
installs `AddWebResourceRequestedFilter(TaskPaneControl.PageResourceFilter, All, All)` and the
`WebResourceRequested` handler on **every** page, one `BackendProxyHandler` per control, and
`SwReviewAddIn` passes `Backend = () => _backend?.Endpoint`.

Every line of that machinery survived section 4 unchanged - the prefix, the mapping function,
the `ProxySend` seam, the 501 for `/events`. What changed is only which URLs reach the handler:
all of them now, because the folder mapping that used to answer the page's own files is gone
and the host answers those too.

| File | What it does |
|---|---|
| `extractor/SwReview.AddIn/Review/BackendProxy.cs` | Maps `https://swreview.invalid/__backend/<path>` to `http://127.0.0.1:<port>/<path>`. Pure function. Exposes `PathPrefix`, `PageOrigin`, `TryMapToBackend`. |
| `extractor/SwReview.AddIn/Review/BackendProxyHandler.cs` | Serves those calls from C#. `TryServe` returns null when the URL is not ours, which is what hands the request to the page file server. Real transport is `HttpWebRequest` with `Proxy = null`. |
| `extractor/SwReview.AddIn.Tests/BackendProxyTests.cs` | 13 cases: mapping, query strings, prefix boundary, traversal, malformed URLs. |
| `extractor/SwReview.AddIn.Tests/BackendProxyHandlerTests.cs` | 9 cases: forwarding, dropped headers, refusals, failure shapes. |

Suite with all of section 4 in place: **1286** extractor + **887** add-in tests pass.

Decisions baked into the handler, each with a test:

- **`Origin` is not forwarded.** The page's origin is the virtual host; sending it on would
  make the backend's own origin guard refuse the call the proxy exists to deliver.
- **No CORS header is copied back.** Same-origin has nothing to allow, and a stray
  `Access-Control-Allow-Origin` would re-open the question the proxy closes.
- **`Host`, `Content-Length`, `Connection` and `Sec-*` are dropped** - they describe a
  request that is not the one being made.
- **`/events` is refused with 501 `StreamNotProxyable`** rather than half-served.
- **No backend yet, and transport failures, answer in the pages' own
  `{error_class, message, retryable}` shape**, so no page needs a new branch.
- **`HttpWebRequest`, not `HttpClient`** - matching `Review/BackendClient.cs`, whose comment
  gives the reason that matters here: it "can be told not to consult the corporate proxy
  for 127.0.0.1". `System.Net.Http` is also not referenced by this project.

---

## 4. Done: the pages are served by the host, and so is the backend prefix

The design in section 2 could not be delivered while the pages were served by a folder
mapping, and that was the one thing this handoff did not know. It is delivered now, by
dropping the mapping.

### The limitation, and why the tests for it stay

**WebView2 raises no `WebResourceRequested` at all for a host mapped with
`SetVirtualHostNameToFolderMapping`.** The mapping resolves the request itself, ahead of the
event. So a `fetch('/__backend/health')` from a folder-mapped page is answered "no such file",
which reaches the page as `Failed to fetch` - the same three words the web filter produced,
from an entirely different cause - and the handler never sees the call.

Proven in `BackendProxyPageTests`, in three tests rather than one, because a negative result
with no control is not evidence. All three use the same harness: a filter of `*`,
`CoreWebView2WebResourceContext.All` and `CoreWebView2WebResourceRequestSourceKinds.All`,
registered **before** the mapping and before the navigation.

| Test | Result |
|---|---|
| `TheFolderMappedVirtualHostRaisesNoWebResourceRequestedForThePagesOwnFiles` | **Zero** events across a page load that really did fetch `index.html`, `app.js`, `render.js` and a stylesheet - asserted by running the page's scripts, so zero events means the event is not raised rather than that nothing was asked for. |
| `TheFolderMappedVirtualHostRaisesNoWebResourceRequestedForAFetchTheCspAllows` | **Zero** events, and `Failed to fetch`, for `fetch('/__backend/health')` from a page whose CSP is `connect-src 'self'`. |
| `TheSameWiringIsRaisedForAHostThatIsNotFolderMapped` | The positive control: identical filter, identical harness, host not folder-mapped - the `OPTIONS` **and** the `GET` are both raised and both served from C#. So `seen.Count == 0` above says the mapping swallows the event, not that this harness never fires. |

The second row is the one that had to be redone during diagnosis. The original test fetched
from the **shipped** Review page, whose CSP was then `connect-src http://127.0.0.1:*` with no
`'self'` - so a same-origin `fetch` was refused inside the renderer before any request existed,
which produces the same `TypeError: Failed to fetch` and guarantees the same zero events
whatever the mapping does. Re-run from a scratch page carrying `connect-src 'self'`, the result
is unchanged, so the conclusion stands on the platform rather than on the policy.

These three tests are why `SetVirtualHostNameToFolderMapping` must not come back. They fail the
day a WebView2 update starts raising the event, at which point the mapping becomes a choice
again rather than a trap.

### What shipped: option B

Every resource under `https://swreview.invalid/` is served by the host, from the web folder,
through the **one** `WebResourceRequested` handler that already served `/__backend/*`. One
filter (`TaskPaneControl.PageResourceFilter`, every context, every source kind), one handler:
`BackendProxyHandler.TryServe` answers the backend prefix and returns null for everything else,
and `PageFileServer` answers the rest. Same origin holds, so the CSP is `connect-src 'self'`
and there is no CORS anywhere in the pane - exactly the design section 2 chose.

Option A - a second virtual host that is not folder-mapped - was rejected. It is a smaller
diff, but it buys that by re-opening the question section 3 closed on purpose: a cross-origin
call needs a preflight, so `BackendProxyHandler`, a class whose rule is that it strips every
`Access-Control-` header, would grow `OPTIONS` handling and start emitting the headers it
strips. `TheSameWiringIsRaisedForAHostThatIsNotFolderMapped` is what prices that: the `GET`
does not happen until the `OPTIONS` is answered with `Access-Control-Allow-*`.

| What | Where |
|---|---|
| The page file server: canonical path under the web folder or 404, a closed extension list, no directory listing, no query-string influence, `Cache-Control: no-store`, one identical 404 for every refusal | `extractor/SwReview.AddIn/Review/PageFileServer.cs` |
| 48 cases over it: traversal in both forms, rooted and UNC segments, unknown extensions, directories, off-origin and malformed URLs, content types including case, byte-for-byte content, and every file the four shipped pages load - that last one read out of the four `index.html` files rather than listed here, with the whole shipped folder checked against the closed extension list | `extractor/SwReview.AddIn.Tests/PageFileServerTests.cs` |
| The mapping dropped; one filter over `PageOrigin + "/*"` with every context and every source kind; `TryServe` then the file server, with the deferral discipline unchanged - request and body read on the UI thread, the work off it, the response and `Complete()` back on it, nothing thrown | `extractor/SwReview.AddIn/TaskPaneControl.cs` (`AttachPageAsync`, `ServePageResource`) |
| `BackendProxy.ResourceFilter` removed: the filter is no longer the prefix, and a property documented as "the filter WebView2 is given" that is not the filter WebView2 is given is a lie the next reader would act on | `extractor/SwReview.AddIn/Review/BackendProxy.cs`, `BackendProxyTests.cs` |
| `init.backend.origin` is now `BackendProxy.PageOrigin` - the page's own origin under `/__backend` - from **all three** hosts that send it, so one field means one thing in every contract. The port is still sent: the pane shows it and a diagnostic needs it, but no page builds a URL from it | `Review/ReviewHost.cs`, `Model/ModelCheckHost.cs`, `Remodel/RemodelHost.cs`, `ModelCheckHostTests.cs`, `PageMessageTests.cs`, `ModelCheckPageTests.cs`, `RemodelHostTests.cs`, `RemodelPageContractTests.cs` |
| `connect-src 'self'` in the contract and in all four `index.html` files, byte-identical (the page contract tests assert that) | `specs/002-task-pane-assistant/contracts/pane-host-messages.md`, the four pages |
| The offscreen page-test helper serves pages with the same `PageFileServer` through the same filter instead of mapping the host, so every existing page test now exercises the real serving path | `extractor/SwReview.AddIn.Tests/ReviewPageInjectionTests.cs` (`OffscreenReviewPage`) |
| The shipped configuration, end to end on a real WebView2: the Review page loads whole - scripts ran and `app.css` applied - with nothing of its own reaching the transport, and a same-origin `GET` and `POST` under `/__backend` both reach the host's transport with `Authorization` present and `Origin` stripped | `BackendProxyPageTests.TheShippedPaneServesItsOwnPagesAndItsBackendCallsThroughOneHandler` |
| The other half of the CSP decision: a `fetch` to `http://127.0.0.1:1/` raises a `securitypolicyviolation` on `connect-src` - refused by the renderer before a socket is opened, so no web filter can answer it | `BackendProxyPageTests.ThePagesCspRefusesLoopbackBeforeAnyNetworkCallIsMade` |

`WithNoFolderMappingThePageAndItsBackendCallsAreBothServedFromCSharp`, which measured option B
against a scratch page before it was chosen, is gone: the shipped test above asserts the same
thing against the real `TaskPaneControl`, and keeping both would be one claim in two places.

### What the file server had to pay for

The mapping was also a sandbox - one folder, and no way out of it - and `File.ReadAllBytes` is
not. Every rule it used to enforce is now stated in `PageFileServer` and pinned in its tests:
the request must be on the page origin; the path comes from `AbsolutePath`, so a query string
or a fragment can never choose the file; each segment is decoded **first** and then refused if
it is empty, `.`, `..`, or carries a separator or any character Windows forbids in a file name
(which is what stops `%2e%2e`, `%5c` and a bare drive letter); and the canonical path is checked
**again** to be under the web folder, because one of those two rules holding is not a reason to
trust the other. The extension list is closed, so `vendor/LICENSES.md` and anything else that
ever lands under `web/` is a 404 rather than a download. Every refusal is the same 404, so a
page learns only that it did not get what it asked for.

### Still true, and still not proxied

`GET /sessions/{chat_id}/events` is refused with 501 and read by the host instead, for the
reason in section 2: a `WebResourceRequested` response must have all its content available when
the deferral completes. That is unchanged by any of this.

### Traps

- **SOLIDWORKS locks `SwReview.AddIn.dll`.** A build fails with
  `The file is locked by: "SolidWorks (<pid>)"`. Close SOLIDWORKS to compile. That lock is
  also proof the assembly loaded.
- **Do not diagnose COM or CORS through PowerShell against the page.** PowerShell wraps
  arguments in `PSObject`, which produces a fake `InvalidCastException`, and PowerShell is
  not subject to the web filter, so it cannot reproduce the page's failure.
- Registration survives rebuilds: same GUID, same codebase path, no `regasm` needed.

---

## 5. The interim workaround, no longer needed

Before the proxy landed, a **Sophos Web Control exclusion for `127.0.0.1` / `localhost`** was
what made the pane work, and it needed a Sophos Central administrator. It is recorded here
because it is the fallback if the proxy ever has to be backed out, and because it is the one
thing that distinguishes "this workstation's filter" from "this pane's bug" when the next
report arrives. It is not required now: no page makes a browser request to loopback at all,
and the CSP would refuse one if a page tried.

Unaffected today, with no change at all: the **Extract** tab (native WinForms) and the
entire `swreview` CLI, including `swreview check rms`, which is the same grading the Model
check tab cannot display.
