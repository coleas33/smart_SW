# Page ↔ Host Messages

Both WebView2 pages talk to the add-in with `window.chrome.webview.postMessage(json)` and
receive `WebMessageReceived` replies as JSON. Every message is `{ "type": string, "id":
string, "payload": object }`; replies echo `id`. Unknown types are answered with
`{type: "error", payload: {message}}`. Pages are loaded from the add-in's content folder with
a virtual host name, never from the run folder.

## Review page → host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` with `{backend: {port}, token, settings (no key), run_root, document: {path, configuration} \| null}`. |
| `review.start` | `{}` | Refuse if no document is open (`error`). Otherwise create the run folder, run the in-process dump, then `POST /sessions`; reply `review.started {chat_id, run_dir}`. Progress via `status` messages. |
| `settings.save` | `{provider, model, effort, api_key \| null, base_url, gemini_enterprise}` | Encrypt the key with DPAPI, write settings, restart the backend with the new environment; reply `settings.saved {settings (no key), key_source}`. |
| `settings.get` | `{}` | Reply `settings {settings (no key), key_source}`. |
| `models.list` | `{provider}` | Proxy to backend `/models`; reply `models {models}`. |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id}` | Resolve through the tool service, select and zoom on the application thread; reply `entity.shown {ok, state_code, message}`. |
| `report.open` | `{chat_id}` | Open `report.md` in the default app; reply `ok`. |
| `folder.open` | `{run_dir}` | Open the folder; reply `ok`. |
| `log.open` | `{}` | Open the log folder; reply `ok`. |

The page talks to the backend directly for messages, evidence answers, dispositions, and the
event stream, using the token from `init`. The host never proxies the SSE stream.

## Host → review page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}` |
| `document.changed` | `{path, configuration} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}` |

## Terminal page → host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{cols, rows}` | Reply `init {clis: [{name, found, version, path, minimum}], last_choice}`. |
| `terminal.start` | `{cli, cols, rows}` | Locate the CLI, regenerate profiles, start the ConPTY session in the run folder; reply `terminal.started {pid, cwd, profile_paths}` or `error {install_steps}`. |
| `terminal.input` | `{data}` (UTF-8 text) | Write to the pseudo-console. |
| `terminal.resize` | `{cols, rows}` | `ResizePseudoConsole`. |
| `terminal.stop` | `{}` | Send the CLI's exit command, then terminate the process tree; reply `terminal.stopped`. |

## Host → terminal page (unsolicited)

| type | payload |
|------|---------|
| `terminal.output` | `{data_base64}` |
| `terminal.exited` | `{exit_code}` |
| `chatlog.count` | `{count}` after each MCP call is logged |
