# Page ↔ Host Messages

The WebView2 pages talk to the add-in with `window.chrome.webview.postMessage(json)` and
receive `WebMessageReceived` replies as JSON. Every message is `{ "type": string, "id":
string, "payload": object }`; replies echo `id`. Unknown types are answered with
`{type: "error", payload: {message}}`. Pages are loaded from the add-in's content folder
with the fixed virtual host name `swreview.invalid`, mapped with
`SetVirtualHostNameToFolderMapping("swreview.invalid", <web folder>,
CoreWebView2HostResourceAccessKind.Allow)`, never from the run folder. The page origin is
therefore `https://swreview.invalid`, and that exact string is what the backend is started
with as its allowed origin (`chat-api.md`).

## WebView2 environment (every page)

The add-in creates **one** `CoreWebView2Environment` for the process with an explicit user
data folder `%LOCALAPPDATA%\SwReview\WebView2\<add-in instance>`, and all three pages -
Review, Terminal and Model check - share it. The default folder is derived from
`SLDWORKS.exe`, which is shared with SOLIDWORKS' own WebView2 usage and every other add-in in
the process, and its directory under `C:\Program Files\...` is not writable. A second
environment created over a user data folder already opened with different options fails at
runtime. The Model check tab's WebView2 is created on its **first activation** rather than at
add-in load, on that same environment: a page loaded into every SOLIDWORKS session that never
presses Model check is a renderer process nobody asked for. Environment or `EnsureCoreWebView2`
failure surfaces as the documented "WebView2 runtime missing" fallback panel (download link
plus the run folder path in plain text), never as an exception escaping into SOLIDWORKS, and
the Extract tab keeps working. A failure on the Model check tab lands in that tab only; the
other pages keep working.

## Rendering untrusted text (every page)

Assistant text deltas, tool `result_summary`, finding `title` and `recommended_action`,
drawing `text_as_read`, evidence text and error `message` are authored by the model or by
reviewed documents. Every page MUST insert every such string with `textContent` /
`createTextNode`, never `innerHTML`, and never through an inline event handler. If Markdown
is ever rendered, the renderer is vendored with HTML disabled and escaping on. Every page
ships the same strict CSP meta tag:

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src http://127.0.0.1:*; base-uri 'none'; form-action 'none'">
```

The host handles `NavigationStarting` and `NewWindowRequested` on every WebView2 control and
cancels any URL outside `https://swreview.invalid/`.

## Review page → host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, settings (no key), run_root, document: {path, configuration} \| null}`. |
| `review.start` | `{}` | Refuse if no document is open (`error`). Otherwise create the run folder, run the in-process dump, then `POST /sessions`; reply `review.started {chat_id, run_dir}`. Progress via `status` messages. |
| `settings.save` | `{provider, model, effort, api_key \| null, base_url, gemini_enterprise}` | Refuse with `error {error_class: "TurnRunning"}` while any chat has a running turn. Otherwise encrypt the key with DPAPI, write settings, restart the backend with the new environment; reply `settings.saved {settings (no key), key_source}`. A release build refuses `provider: "fake"` (FR-027). |
| `settings.get` | `{}` | Reply `settings {settings (no key), key_source}`. |
| `models.list` | `{provider}` | Proxy to backend `/models`; reply `models {models}`. |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id}` | Resolve through the tool service, select and zoom on the application thread; reply `entity.shown {ok, state_code, message, full_path \| null}` — on a reference that no longer resolves, `full_path` carries the component's full path so the engineer can find it by hand (spec Edge Cases). |
| `report.open` | `{chat_id}` | Open `report.md` in the default app; reply `ok`. |
| `folder.open` | `{chat_id}` | Open that session's run folder; reply `ok`. |
| `log.open` | `{}` | Open the log folder; reply `ok`. |

`report.open` and `folder.open` resolve the path from the host's own session record keyed by
`chat_id`; the page never supplies a path. `log.open` uses the host's log folder. Every
resolved path is canonicalized and must be a descendant of `run_root` (or the log folder)
before it reaches `ShellExecute`; anything else is answered `error`.

The page talks to the backend directly for messages, evidence answers, dispositions, and the
event stream, using the token and origin from `init`. The host never proxies the SSE stream.

## Host → review page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}` |
| `document.changed` | `{path, configuration} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}` |

## Terminal page → host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{cols, rows}` | Reply `init {clis: [{name, found, version, path, minimum}], last_choice, evidence: {present, run_dir}}`. The evidence block describes the current session folder without creating one, so the page can say whether there is anything to ask about before Start. |
| `evidence.extract` | `{}` | Run the same in-process dump the Review tab runs, into the terminal run folder (rule below, created when there is none yet); reply `evidence.extracted {run_dir, counts}` or `error`. The MCP server re-reads the evidence package lazily, so a CLI that is already running picks it up without being restarted. |
| `terminal.start` | `{cli, cols, rows}` | Locate the CLI, regenerate profiles, start the ConPTY session in the terminal run folder (rule below); reply `terminal.started {pid, cwd, profile_paths}` or `error {install_steps}`. |
| `terminal.input` | `{data}` (UTF-8 text) | Write to the pseudo-console. |
| `terminal.resize` | `{cols, rows}` | `ResizePseudoConsole`. |
| `terminal.stop` | `{}` | Send the CLI's exit command, then terminate the process tree; reply `terminal.stopped`. |

Terminal run folder: on `terminal.start` the host uses the current chat session's run folder
when one exists; otherwise it creates `<run_root>/<yyyyMMdd-HHmmss>-terminal` through the
**same** run-folder helper `ReviewHost` uses, and reports it as `terminal.started.cwd`. The
Terminal tab is reachable with no review and no document open, so a run folder is always
created rather than assumed.

## Host → terminal page (unsolicited)

| type | payload |
|------|---------|
| `terminal.output` | `{data_base64}` |
| `terminal.exited` | `{exit_code}` |
| `chatlog.count` | `{count}` after each MCP call is logged |

`terminal.output` is coalesced: the read loop appends into a buffer and posts at most one
message per ~16 ms, or immediately when the buffer exceeds 32 KB, whichever comes first, and
drops nothing. `PostWebMessageAsJson` has UI-thread affinity, so the background read loop
marshals the post onto the pane control like every other UI call.

## Model check page → host

Tab 4, the Model check page (`specs/003-resilient-modeling/contracts/model-check.md`, which
is the full contract; these are the rows as this pane serves them). The tab runs the rules
with no provider, no key and no network call beyond the loopback backend.

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, run_root, document: {path, configuration, kind} \| null, latest_check: {run_dir, at} \| null}`. |
| `check.start` | `{scope: "part"}` | Refuse with `error {error_class: "NoDocument"}`, `"NotAttached"` or `"NotAPart"` as applicable. Otherwise create the check run folder, run the `ModelCheck` profile dump in process, register that folder as the pane's latest run, and reply `check.extracted {run_dir, document, configuration, counts, gaps}`. Progress via `status`. The host stops there: the page calls `POST /checks/rms` itself, with the token and origin from `init`. |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id}` | **The Review page's row, unchanged**: both hosts delegate it to the one `PaneActions`; reply `entity.shown {ok, state_code, message, full_path \| null}`. |
| `report.open` | `{run_id}` | Delegated to `PaneActions`; the path comes from the host's own record, never from the page. |
| `folder.open` | `{run_id}` | Delegated to `PaneActions`. |
| `log.open` | `{}` | Delegated to `PaneActions`. |

The last four rows are the same code as the Review page's, under the same rule: the resolved
path is canonicalized and must be a descendant of `run_root` (or the log folder) before it
reaches `ShellExecute`, and the page never supplies a path.

The check run folder is `<run_root>/<yyyyMMdd-HHmmss>-<doc>-check`, named through the same
`RunFolders` helper as a review's, and it is the pane's current session folder afterwards.

## Host → Model check page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}` |
| `document.changed` | `{path, configuration, kind} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}` |

`kind` is on this page's row and not on the Review page's because this page decides with it:
the Model check reads a part's feature tree, so the tab says whether a check can run at all
rather than letting the engineer press a button the host will refuse. The Review page's
`document.changed` carries the path and the configuration only, which is what `ReviewHost`
sends.

The backend's lifecycle reaches this page as well as the Review page, because this page calls
the check routes itself with the endpoint and token its `init` carried: a tab opened while the
backend was still starting holds a null endpoint, and `status {stage: "ready"}` is what tells
it to re-send `ready` and take the endpoint from the fresh `init`.

## The step strip (all four tabs)

Above the tabs, the strip renders three steps - open a document, extract evidence, review or
ask - each done or pending with the reason it is pending, from two facts the add-in answers:
whether a document is open, and whether the session's run folder holds `package.json`.

It also reads `extractor.profile` out of that `package.json`. A package written by the
`model_check` profile carries features and equations and none of the geometry phases, so the
strip adds one line, **"Evidence: model check only (features and equations)"**, and an
**Extract full evidence** action that opens the Extract tab; the three steps read exactly as
they do for a full package, because partial evidence is still evidence. A `model_check`
folder is never suggested as the Extract tab's output folder: a full dump into it would
overwrite the package that check's own `session.json` and `report.md` describe. A `full`
package adds nothing to the strip.

Only the head of `package.json` is read - `extractor` is the fourth property of the file -
because the strip repaints on the SOLIDWORKS application thread every time a tab is selected
and a full review package is tens of megabytes. A file that cannot be read is not a check.
