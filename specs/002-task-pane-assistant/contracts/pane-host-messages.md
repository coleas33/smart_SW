# Page ↔ Host Messages

*Feature 015 amendment notice, 2026-10-08:* Planned amendments for the host messages are specified in [015 pane.md](../../015-review-send-gate/contracts/pane.md).

The WebView2 pages talk to the add-in with `window.chrome.webview.postMessage(json)` and
receive `WebMessageReceived` replies as JSON. Every message is `{ "type": string, "id":
string, "payload": object }`; replies echo `id`. Unknown types are answered with
`{type: "error", payload: {message}}`. Pages are loaded from the add-in's content folder
under the fixed virtual host name `swreview.invalid`, never from the run folder. The page
origin is therefore `https://swreview.invalid`, and that exact string is what the backend is
started with as its allowed origin (`chat-api.md`).

`swreview.invalid` is a **name, not a mapping**: nothing calls
`SetVirtualHostNameToFolderMapping`. The host serves every page file itself, out of the web
folder, through `WebResourceRequested` - see the next section for why, and what that costs.

## WebView2 environment (every page)

The add-in creates **one** `CoreWebView2Environment` for the process with an explicit user
data folder `%LOCALAPPDATA%\SwReview\WebView2\<add-in instance>`, and every one of the five
pages - Review, Terminal, Model check, Remodel and Standards - shares it. Six tabs, five
pages: the Extract tab is a WinForms panel and has no WebView2 at all. The default
folder is derived from `SLDWORKS.exe`, which is shared with SOLIDWORKS' own WebView2 usage
and every other add-in in the process, and its directory under `C:\Program Files\...` is
not writable. A second environment created over a user data folder already opened with
different options fails at runtime. The Model check tab's WebView2 is created on its
**first activation** rather than at add-in load, on that same environment: a page loaded
into every SOLIDWORKS session that never presses Model check is a renderer process nobody
asked for. Environment or `EnsureCoreWebView2` failure surfaces as the documented
"WebView2 runtime missing" fallback panel (download link plus the run folder path in plain
text), never as an exception escaping into SOLIDWORKS, and the Extract tab keeps working.
A failure on the Model check tab lands in that tab only; the other pages keep working.

### Every page resource is served by the host

Each page's WebView2 gets **one** `WebResourceRequested` filter - `https://swreview.invalid/*`,
every resource context, every request source kind - and **one** handler, and that handler
answers everything on the origin:

| Request | Answered by |
|---|---|
| `https://swreview.invalid/__backend/...` | The backend proxy: the host calls `http://127.0.0.1:<port>/...` from C# and returns what it gets. `GET /sessions/{chat_id}/events` is refused with 501 - a `WebResourceRequested` response must be complete before it is handed back, so the host reads that route itself and pushes frames over the `events.*` messages instead. *Amended 2026-10-19 (owner decision 143A):* while the backend waits to be restarted with settings saved during a turn (`settings.save`, below), a `POST` to `/sessions/{chat_id}/messages`, `/send`, `/evidence` or `/evidence/{request_id}` is answered by the review host and never sent: while something holds the restart back, with what - `TurnRunning` (409) for a turn, `RemodelRunning` (409) for a remodel run, `BackendUnavailable` (503) for a backend that gives no answer; otherwise the host makes the restart, or waits for it, and answers `UnknownChat` (404) once one has been made, since the restarted backend does not hold the chat, or `BackendUnavailable` (503) with the failure when the restart it made or waited for failed. A refusal carries the status and `retryable` flag the backend gives its class - `TurnRunning` and `UnknownChat` are not retryable, as `chat/server.py` answers them - and the host's own words, which say why. Stop, dispositions and every other call are sent as before. |
| Anything else on the origin | The page file server: the file at that path under the web folder. |

**There is no `SetVirtualHostNameToFolderMapping`, and there must not be one.** WebView2 raises
no `WebResourceRequested` at all for a folder-mapped host - the mapping resolves the request
itself, ahead of the event - so a page served that way cannot have its own origin intercepted,
which is the whole of the same-origin proxy. Every page's `fetch` would reach the loopback
backend as a browser request, and an endpoint web filter that intercepts browser HTTP to
loopback answers it with an interstitial no `fetch` can click through
(`docs/pane-backend-proxy.md`).

The file server replaces the sandbox the mapping used to provide, so its rules are part of this
contract: the canonical path must stay under the web folder (traversal, a rooted segment, or
anything resolving outside it is a 404); the content type comes from a closed list of
extensions - `html`, `js`, `css`, `json`, `svg`, `png`, `ico`, `woff2` - and any other
extension is a 404; the query string and the fragment never choose the file; there is no
directory listing and no implicit `index.html`; every response carries `Cache-Control:
no-store`; and every refusal is the same 404, so a page learns only that it did not get what it
asked for.

## Rendering untrusted text (every page)

Assistant text deltas, tool `result_summary`, finding `title` and `recommended_action`,
drawing `text_as_read`, evidence text and error `message` are authored by the model or by
reviewed documents. Every page MUST insert every such string with `textContent` /
`createTextNode`, never `innerHTML`, and never through an inline event handler. If Markdown
is ever rendered, the renderer is vendored with HTML disabled and escaping on. Every page
ships the same strict CSP meta tag:

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'">
```

The host handles `NavigationStarting` and `NewWindowRequested` on every WebView2 control and
cancels any URL outside `https://swreview.invalid/`.

## Review page → host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, settings (no key, including send_when_checked), run_root, document: {path, configuration, kind, drawing_guidance?} \| null, review_preparation: boolean, engineering_context: boolean, engineering_selection: boolean}`. Feature 016's optional context/selection flags expose available preparation/prefill seams, without native calibration. *Amended 2026-09-28 (U25; default taken 2026-09-28, the owner may revise; feature 011 `contracts/attach.md` section 5):* `document` is the check tabs' shape, `kind` included, and a drawing's carries `drawing_guidance`, the one sentence the host composes for it (below). |
| `review.prepare` | `{}` | Read the active component tree without writing a run folder, resolving components, or contacting a model. Reply `review.prepared {preparation_id, document, component_count, unread_count, gap_count, instances, omitted_instances, requires_attention, standards_configured}`. At most 30 unread instances, strings capped at 200 characters. |
| `review.start` | `{preparation_id?, retry_of?}` | Refuse if no document is open (`error`). A host advertising `review_preparation: true` in `init` requires the single-use id from its latest preparation and the same active document/configuration; otherwise `PreparationExpired`. Create the run folder, run the in-process dump, then `POST /sessions` using the stored `send_when_checked` value when this message is handled; reply `review.started {chat_id, run_dir, not_examined, document, send_when_checked}` where `not_examined` is the backend's `{sentence, instances}` warning or `null`, and `document` is `{path, configuration}` of the document the dump extracted (captured before the dump, in the shape `init` and `document.changed` carry). The page binds the results on screen to `document`: when `document.changed` names another path (ignoring case) or configuration, or no document, it hides the previous results and disables what acts on them until that document is open again. Unticked, the record and its `sessions.list` item carry `model_status: "not_sent"`; the ready status says "Checked {n} components by code; nothing was sent to the model.". Progress via `status` messages. |
| `context.prepare` | `{}` | Feature 016: extract a host-owned evidence run without creating a provider session; reply `context.prepared {run_id, package_sha256, document}`. The prepared run is bound to the current document/configuration and expires on replacement or document/configuration change. |
| `context.selection` | `{run_id, package_sha256}` | Read exactly one current component/face on the application thread against that prepared package. Reply `context.selected` with a unique saved target ID or explicit unresolved reason codes, `native_calibrated: false`, `native_model_state: selection_observation_only`, and `freshness: cannot_establish`. No selection, activation, native write, confirmation or cross-extraction rebinding is performed. Native refs and filesystem paths are not returned. |
| `context.review` | `{run_id, context_id, head_digest, package_sha256}` | Explicitly review the prepared saved package with the exact private context revision, without another dump. Host-owned run/document/config and package SHA must still match. `POST /sessions` validates context ID/head/package before provider setup. Reply through the existing `review.started` message; no automatic context attachment occurs in ordinary Review. *Amended 2026-10-15 (feature 016 on feature 015, owner decision 99A):* the review starts through the one `CreateReviewSession` `review.start` uses, so `POST /sessions` carries the stored `send_when_checked` beside the attachment, the reply is `review.started {chat_id, run_dir, not_examined, document, send_when_checked}`, and an unticked start's record is `not_sent` with the ready status "Checked {n} components by code; nothing was sent to the model.". *Amended 2026-10-15 (owner decision 108A):* `review.start {retry_of}` naming a chat the host started with saved context extracts nothing: it requires the same active document and configuration (`ReviewNotActive` otherwise) and posts `POST /sessions` with that chat's run folder, `retry_of` and the same attachment, Send or Wait from the box, through the same `CreateReviewSession`. |
| `review.recheck` | `{chat_id}` | *Feature 015 T108, 2026-10-15.* Re-run a restored waiting review's checks from its own run folder, as the first step of its Send ([015 recheck.md](../../015-review-send-gate/contracts/recheck.md) section 1). Refuse `InvalidRequest` (no `chat_id`), `UnknownChat` (no tracked review), `DrawingActive`, `ReviewNotActive` (another document or configuration is active) and `BackendUnavailable`, in that order, changing nothing. Otherwise post `status` `checking`, call `POST /sessions` with the record's folder, `send_when_checked: false` and `recheck: true` (no dump), replace the record (same folder and document, the new chat id, its `ModelStatus` kept), post `status` `ready` and reply `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document}`. A backend refusal is rethrown with its class. |
| `settings.save` | `{provider, model, effort, api_key \| null, base_url, gemini_enterprise}` | Refuse with `error {error_class: "TurnRunning"}` while any chat has a running turn. While a review waits at `awaiting_send`, saving is accepted. Otherwise encrypt the key with DPAPI, persist settings (a failed write is `SettingNotSaved`, leaving stored settings unchanged), restart the backend with the new environment; reply `settings.saved {settings (no key, including send_when_checked), key_source}`. A release build refuses `provider: "fake"` (FR-027). *Amended 2026-10-19 (owner decision 143A):* a turn can start after that check and before the restart - a follow-up, the answers or a Send reach the backend directly - and the restart is then refused, with the settings already written: the add-in's `BackendSupervisor` asks again before it stops the old backend. The save is kept: the reply is still `settings.saved`, and `status {stage: "error", message}` follows it with "the settings are saved; the backend restarts when the running turn ends." The host makes that restart once no remodel run is in progress and no chat has a running turn, however the turn ended, with the settings in force then, so several saves restart it once, with the last; it then posts `backend.restarted {sentences}`, or, when the start fails, `status {stage: "error"}` with the failure, as a failed start is reported, and does not retry. Only a readable state, a 404 `UnknownChat` or a 400 `InvalidRequest` rules a chat's turn out; anything else - no answer at all, a 5xx, a body that is not the backend's - leaves the turn unknown and holds the restart back. After three such looks in a row the host stops looking and posts `status {stage: "error"}`, before anything a later save posts, saying the backend has not been restarted yet, that it will be before the next review or follow-up once it answers, and that saving the settings again restarts it now; the restart still waits, and the next review or page call that would start a turn looks once more. Until the restart is made, a new review (`review.start`, `review.recheck`, `context.review`), and an engineering context request that checks the backend (`context.prepare`, `context.selection`), makes the restart first or waits for the one being made, and is refused before anything is read, saying what holds the restart back - `TurnRunning` for a turn, `RemodelRunning` for a remodel run, `BackendUnavailable` for a backend that gives no answer - or `BackendUnavailable` with the failure when the restart it made or waited for failed, a save's own included; and the host answers a page call that would start a turn itself (the backend prefix, above). A save when no turn runs restarts at once, as before, and is that restart. The `TurnRunning` refusal of the check says the settings were not saved. *Amended 2026-10-19 (owner decision 145A):* a remodel run is treated as a turn. A save made while a remodel run is in progress - a plan or a Start's run (004 `pane-remodel-messages.md`) - is kept as above, and its restart waits for the run, which it would end with its copy half changed: the host reads the run under the restart's own lock, before it asks the backend anything, and the status says "the settings are saved; the backend restarts when the remodel run ends.", or, when a turn also started during the save, "the settings are saved; the backend restarts when the running turn and the remodel run end."; the restart is made once nothing holds it back, and a restart made after waiting reads the run again under its own lock after its look, which can answer without reading it - with no backend process at all - so it never ends one in progress. The status for a backend that does not answer now reads "the review backend is not answering, so it has not been restarted with the saved settings yet. It will be before the next review, follow-up or remodel run, once it answers; to restart it now, save the settings again.". A remodel run begins only once no restart waits: the host makes a waiting restart first, or waits for the one being made, a save's included, or refuses the run while something holds the restart back, or with the failure of the restart it made or waited for (004 `pane-remodel-messages.md`). Every restart the host makes, at once or after waiting, is told to the Model check, Standards and Remodel pages too (`backend.restarted`, in their tables below); a failed one is told to none of them as a restart. *Amended on review the same day:* one that failed once the old backend had stopped is told to them as a failed first start is told to every page - `status {stage: "error"}` with the failure, masked - since no backend answers the token they hold; one that failed before it stopped anything left the old backend up, and is told to the Review page alone. |
| `send_when_checked.save` | `{send_when_checked: boolean}` | Persist the setting without a restart or turn check; reply `send_when_checked.saved {send_when_checked}`. A missing or non-boolean value is `InvalidRequest`; a failed write is `SettingNotSaved`, with the stored value unchanged. |
| `settings.get` | `{}` | Reply `settings {settings (no key, including send_when_checked), key_source}`. |
| `models.list` | `{provider}` | Proxy to backend `/models`; reply `models {models}`. |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id, chat_id?}` | Resolve through the tool service, select and zoom on the application thread; reply `entity.shown {ok, state_code, message, full_path \| null}` — on a reference that no longer resolves, `full_path` carries the component's full path so the engineer can find it by hand (spec Edge Cases). With `chat_id` - the Review page always sends the chat it shows (feature 009 FR-023) - the ids are looked up in that chat's run folder, resolved from the host's own record through the same lookup `report.open` uses, and a `chat_id` the host never recorded is refused as `report.open` refuses one; without it they are looked up in the pane's latest run, as the check tabs' Show always has. The check hosts read their own `run_id` the same way; their pages send none. |
| `report.open` | `{chat_id}` | Open `report.md` in the default app; reply `ok`. |
| `folder.open` | `{chat_id}` | Open that session's run folder; reply `ok`. |
| `sessions.list` | `{}` | Reply `sessions {items: [{chat_id, run_id, run_dir, path, configuration, started_at}]}`: every review this host tracks, in the order it tracked them, and never a check or remodel record (feature 009 FR-020, its `contracts/sessions.md` sections 1-2). `path` and `configuration` are the document `review.started` named, or a found review's `model_status.document`; `run_id` is the run folder's name. `started_at` is ISO 8601 with its offset from when the review was tracked, or a found review's stored `checked_at`; null where the host does not know. The records live for the SOLIDWORKS session, not the backend process: a settings save keeps every one. Feature 015 T074: `model_status` is present only for a waiting record. After the search below and before replying, only marked records get one bounded `session.json` head read each; a head whose `model_status.state` says `sent` clears the mark, and a missing or unreadable head keeps it. The default reader shares the file for reads, writes and replacement. |
| `session.forget` | `{chat_id}` | Remove that review's record and reply `sessions {items}` without it; the pane's latest run is cleared if it was that record. A `chat_id` the host never recorded - a check record has none - is refused exactly as `report.open` refuses one, `error {error_class: "UnknownChat"}`, and nothing is removed; no `chat_id` is `InvalidRequest`. |
| `log.open` | `{}` | Open the log folder; reply `ok`. |
| `events.open` | `{chat_id, last_event_id \| null}` | Read `GET /sessions/{chat_id}/events` in the host and post every frame back as `events.frame`. Stops any stream this host was already reading. No reply: what the page is waiting for is frames. `error {error_class: "InvalidRequest"}` when no `chat_id` is given. |
| `events.close` | `{}` | Stop the host's reader. No reply. |

*Amended by feature 015 T106*: before `sessions.list` answers, an active part or assembly with no
tracked review of its path (ignoring case) and configuration (exactly) triggers a waiting-review
search. Only folder names matching `<yyyyMMdd-HHmmss>-<DocumentName(path)>`, optionally followed
by a numeric `-N` collision suffix, are candidates; `-check`, `-standards` and `-remodel` folders
are skipped. The newest timestamp, then ordinal name, selects one folder. Its `session.json` is
opened once, reading at most 65,536 bytes to the top-level `session_id` and `model_status`; no
other candidate's file is opened. A `not_sent` or `send_failed` state whose document matches the
active path and configuration becomes a tracked review: `chat_id` is `session_id`, `started_at`
is `checked_at` with its stored wall clock and offset, and `model_status` is the state. This
record can be restored and rechecked like any tracked review, and another list adds no duplicate.
A newer sent, missing, unreadable or mismatched head offers nothing, without falling back to an
older folder; an unreadable run root also offers nothing.

`report.open` and `folder.open` resolve the path from the host's own session record keyed by
`chat_id`; the page never supplies a path. `log.open` uses the host's log folder. Every
resolved path is canonicalized and must be a descendant of `run_root` (or the log folder)
before it reaches `ShellExecute`; anything else is answered `error`.

The page talks to the backend directly for messages, evidence answers and dispositions, using
the token and origin from `init`. **The event stream is the exception**: the host reads
`GET /sessions/{chat_id}/events` itself and pushes each frame over this channel. That route
cannot be served any other way — a `WebResourceRequested` response must be complete when its
deferral ends, so server-sent events cannot be proxied — and reading it in C# is also what
keeps it working on a workstation whose web filter intercepts HTTP from browser processes
(`docs/pane-backend-proxy.md`). The frame is passed on **verbatim apart from two
transformations**, and the page's parser is indifferent to both. Every configured secret is
masked out of it first, through the host's own redacting choke point, because a frame carries a
provider's own error message (FR-015). And the host reads the response line by line and rejoins
a frame's lines with `\n`, so a backend that separates them with `\r\n` - `sse-starlette`'s
default, which is what `reviewer/src/swreview/chat/server.py` streams - reaches the page as the
same frame as one that uses `\n`; the page splits on either. Nothing else is done to it, and in
particular nothing is parsed: the page already reads `id:` and `data:` and tracks `seq`, and a
second parser in the host could disagree with it. "Untouched" would be the wrong word for both
of those, and it would invite the next change to remove the redaction as a contract violation.

## Host → review page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "extracting" \| "backend_starting" \| "checking" \| "ready" \| "error", message}`. Checking saved evidence again posts `checking` with "Checking the saved evidence again...", then `ready` with "Checked the saved evidence again; nothing was sent to the model." on success. |
| `document.changed` | `{path, configuration, kind, drawing_guidance?} \| null` when the active document changes - and, since feature 009 (FR-022), when the active document's configuration changes: the add-in follows the active part's or assembly's `ActiveConfigChangePostNotify` and runs the same fan-out, so every host posts this with the new configuration. *`kind` and a drawing's `drawing_guidance` added 2026-09-28 (U25), as `init`'s* |
| `backend.stopped` | `{exit_code, log_path}` |
| `backend.restarted` | `{sentences}` — *added 2026-10-19 (owner decision 143A):* the host restarted the backend with settings saved while a turn was running, once nothing held it back (`settings.save` above); `sentences` are the host's sentences about that wait, word for word - the one posted when the save was kept, and the one posted if it stopped looking at a backend that did not answer. The port and token of the page's last `init` are the old child's, so the page takes whichever of `sentences` is on its banner off it, and nothing else there, and sends `ready` again - once more after an `init` already on its way, which may have been answered before the new child was up, or before the restart began: an `init` naming the token the page held when this arrived is not the new backend. The new backend does not hold the chat on screen, so the page closes that chat's stream and any reconnect. *Amended 2026-10-19 (owner decision 145A):* `sentences` carries all four of the host's sentences about a restart that waits - the three for a save whose restart waits (for a turn, for a remodel run, for both) and the one for a backend that does not answer - and the host posts `backend.restarted` to the Model check, Standards and Remodel pages as well, with `sentences` empty, after every restart it makes, a save's made at once included, which this page learns of from `settings.saved` |
| `events.frame` | `{chat_id, frame}` — one raw SSE frame, the text between blank lines, redacted of every configured secret and with its line endings normalised to `\n`; unparsed otherwise |
| `events.closed` | `{chat_id, reason}` — the backend closed the stream or the read failed; the page decides whether to reopen, and with which `last_event_id` |
| `context.prepared` | Feature 016 reply: `{run_id, package_sha256, document}` naming the host-owned saved package prepared without a provider session. |
| `context.selected` | Feature 016 reply: saved target IDs or unresolved reason codes, package identity/digest, source observations, `native_calibrated: false`, `native_model_state: selection_observation_only`, `freshness: cannot_establish`; no native refs or local paths. |

One reader per host. A new `events.open`, an `events.close`, a `ready` from a page that
reloaded, and disposing the host all stop it, and a frame that arrives from a stream that has
already been replaced is dropped rather than posted: it belongs to a transcript that is gone.
Reconnect and its backoff live in the page, because the page is what knows what it has shown.

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
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, run_root, standards_profile: str \| null, document: {path, configuration, kind} \| null, latest_check: {run_dir, at} \| null}`. `standards_profile` (feature 013 T150) is the configured path, or null when the setting is blank; the page relays it on `POST /checks/rms` (feature 003 `contracts/model-check.md`). |
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
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}`. *Amended 2026-10-19 (feature 002, owner decision 145A, found on review):* `error` also when a settings restart failed once the old backend had stopped, with the failure, masked, as a failed first start is told: no backend answers the token of the page's last `init` |
| `document.changed` | `{path, configuration, kind} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}` |
| `backend.restarted` | `{sentences}` - *added 2026-10-19 (owner decision 145A):* the host restarted the backend with saved settings, a save's restart made at once or one made after it waited (`settings.save`); `sentences` is empty, since the Review tab's sentences about a restart that waited are shown there alone. The page sends `ready` again - once more after an `init` already on its way - takes the new port and token, and keeps the check on screen without reading its latest check again. *Amended 2026-10-19 (owner decision 145A, found on review):* a call the page makes while that `init` is on its way waits for it, since the host answers it behind an extraction already running on the tab's pump; and a latest check the old token could not read is read again by the next `init` while no result has been shown since (003 `contracts/model-check.md`) |

*Amended 2026-09-28 (U25; default taken 2026-09-28, the owner may revise):* the Review page decides with `kind` too, since it disables Review for a drawing rather than letting the engineer press a button the host will refuse, so its rows carry `kind` - from the same `CheckPaneHost.DocumentPayload`, so the pages cannot disagree - and it never reads a drawing from the path's extension. A drawing's payload also carries `drawing_guidance`: the sentence `ReviewHost.DrawingSentence` composes, naming the model the drawing's views show when they say which (the first, in sheet-then-view order, by file name; the rest counted), which the page prints as sent in its banner and on a Retry it will not send, and which the host's `DrawingActive` refusal carries too. The paragraph below is kept for the record.

`kind` is on this page's row and not on the Review page's because this page decides with it:
the Model check reads a part's feature tree, so the tab says whether a check can run at all
rather than letting the engineer press a button the host will refuse. The Review page's
`document.changed` carries the path and the configuration only, which is what `ReviewHost`
sends.

The backend's lifecycle reaches this page as well as the Review page, because this page calls
the check routes itself with the endpoint and token its `init` carried: a tab opened while the
backend was still starting holds a null endpoint, and `status {stage: "ready"}` is what tells
it to re-send `ready` and take the endpoint from the fresh `init`.

## Standards page → host

Tab 6, the Standards page (`specs/006-standards-check/contracts/standards-check.md`, which
is the full contract; these are the rows as this pane serves them). The tab grades the
active document against the profile this workstation is configured with. It needs no
language model and no API key: nothing on this path constructs a provider, and the only
host it reaches is the loopback backend.

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, run_root, profile_path: str \| null, document: {path, configuration, kind} \| null, latest_check: {run_dir, at} \| null}`. `profile_path` is the configured path, or null when the setting is blank; `latest_check` names only the newest **`-standards`** folder, never a model check's. |
| `standards.start` | `{}` | Refuse with `error {error_class: "NoDocument"}`, `"NotAttached"`, `"NeverSaved"` (the document has never been saved, so it has no name or folder for the library and part-number checks to read), `"UnsupportedKind"` (it is not a part, an assembly or a drawing) or `"NoProfile"` (none is configured, or the file at the configured path cannot be opened) - **every refusal comes first, the profile check among them, so a refused run leaves no run folder behind**. Otherwise create the check run folder, run the `Standards` profile dump in process, register that folder as the pane's latest run, and reply `standards.extracted {run_dir, document, configuration, counts: {documents, features, cut_list_items, drawing_sheets}, gaps}`. Progress via `status`. The host stops there: the page calls `POST /checks/standards` itself, with the token, the origin and the `profile_path` from `init`. |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id}` | **The Review page's row, unchanged**: all three hosts delegate it to the one `PaneActions`; reply `entity.shown {ok, state_code, message, full_path \| null}`. |
| `report.open` | `{run_id}` | Delegated to `PaneActions`; the path comes from the host's own record, never from the page. |
| `folder.open` | `{run_id}` | Delegated to `PaneActions`. |
| `log.open` | `{}` | Delegated to `PaneActions`. |

The last four rows are the same code as the Review and Model check pages', under the same
rule: the resolved path is canonicalized and must be a descendant of `run_root` (or the log
folder) before it reaches `ShellExecute`, and the page never supplies a path.

The check run folder is `<run_root>/<yyyyMMdd-HHmmss>-<doc>-standards`, named through the
same `RunFolders` helper as a review's and a model check's, and it is the pane's current
session folder afterwards. The suffix is what keeps the two check tabs apart: each host
reads back only the newest folder carrying its own.

**`profile_path` is a path and nothing else.** It is configured as
`standards_profile_path` in the settings file (`settings.schema.json`), whose default is
`%LOCALAPPDATA%\SwReview\standards.yaml`; the host checks that a path is set and that the
file at it can be opened, and reads no byte of it. It is **not** one of the fields
`settings.get`, `settings.save` and `settings.saved` carry - those rows are exactly as the
Review page defines them, and this build offers no pane control that writes it - and no
value read out of the profile ever travels on any message to any page.

## Host → Standards page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}`. *Amended 2026-10-19 (feature 002, owner decision 145A, found on review):* `error` also when a settings restart failed once the old backend had stopped, with the failure, masked, as a failed first start is told: no backend answers the token of the page's last `init` |
| `document.changed` | `{path, configuration, kind} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}` |
| `backend.restarted` | `{sentences}` - *added 2026-10-19 (owner decision 145A):* as on the Model check page |

The Model check page's table exactly, including the two backend stages and why they are
here. What differs is what the page does with `kind`: all three kinds can be graded, so
this page uses it to say *what* will be graded - this drawing and the models its views
reference, this assembly and everything under it - rather than whether anything can be.

## The step strip (all six tabs)

Above the tabs, the strip renders three steps - open a document, extract evidence, review or
ask - each done or pending with the reason it is pending, from two facts the add-in answers:
whether a document is open, and whether the session's run folder holds `package.json`.

*Amended 2026-10-19 (owner decision 139A):* step 3 names the tabs it is done on as the pane
shows them: `3 Review` while the Ask tab is hidden (`TaskPaneControl.AskTabShown`, false since
2026-09-19) and `3 Review or Ask` when it is shown. The pane hands the strip those captions from
its own tab list, so the step cannot name a tab the pane does not show.

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
