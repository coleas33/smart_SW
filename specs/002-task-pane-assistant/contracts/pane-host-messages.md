# Page ↔ Host Messages

Both WebView2 pages talk to the add-in with `window.chrome.webview.postMessage(json)` and
receive `WebMessageReceived` replies as JSON. Every message is `{ "type": string, "id":
string, "payload": object }`; replies echo `id`. Unknown types are answered with
`{type: "error", payload: {message}}`. Pages are loaded from the add-in's content folder
with the fixed virtual host name `swreview.invalid`, mapped with
`SetVirtualHostNameToFolderMapping("swreview.invalid", <web folder>,
CoreWebView2HostResourceAccessKind.Allow)`, never from the run folder. The page origin is
therefore `https://swreview.invalid`, and that exact string is what the backend is started
with as its allowed origin (`chat-api.md`).

## WebView2 environment (both tabs)

The add-in creates **one** `CoreWebView2Environment` for the process with an explicit user
data folder `%LOCALAPPDATA%\SwReview\WebView2\<add-in instance>`, and both tabs share it.
The default folder is derived from `SLDWORKS.exe`, which is shared with SOLIDWORKS' own
WebView2 usage and every other add-in in the process, and its directory under
`C:\Program Files\...` is not writable. A second environment created over a user data folder
already opened with different options fails at runtime. Environment or `EnsureCoreWebView2`
failure surfaces as the documented "WebView2 runtime missing" fallback panel (download link
plus the run folder path in plain text), never as an exception escaping into SOLIDWORKS, and
the Actions tab keeps working.

## Rendering untrusted text (both pages)

Assistant text deltas, tool `result_summary`, finding `title` and `recommended_action`,
drawing `text_as_read`, evidence text and error `message` are authored by the model or by
reviewed documents. Both pages MUST insert every such string with `textContent` /
`createTextNode`, never `innerHTML`, and never through an inline event handler. If Markdown
is ever rendered, the renderer is vendored with HTML disabled and escaping on. Both pages
ship a strict CSP meta tag:

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src http://127.0.0.1:*; base-uri 'none'; form-action 'none'">
```

The host handles `NavigationStarting` and `NewWindowRequested` on both WebView2 controls and
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
