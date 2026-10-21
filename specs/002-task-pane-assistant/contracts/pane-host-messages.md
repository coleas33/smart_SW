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
| `ready` | `{}` | Reply `init` with `{backend: {port, origin}, token, settings (no key, including send_when_checked), run_root, document: {path, configuration, kind, drawing_guidance?} \| null, review_preparation: boolean, engineering_context: boolean, engineering_selection: boolean}`. Feature 016's optional context/selection flags expose available preparation/prefill seams, without native calibration. *Amended 2026-09-28 (U25; default taken 2026-09-28, the owner may revise; feature 011 `contracts/attach.md` section 5):* `document` is the check tabs' shape, `kind` included, and a drawing's carries `drawing_guidance`, the one sentence the host composes for it (below). *Amended 2026-10-20 (owner decision 153A):* `init` also carries `settings_not_in_force: string \| null`. It is null while the saved settings are in force - the backend that is up was started with the same provider, model, effort, key (by its value and where it came from), base URL and Gemini Enterprise - and null while no backend is up, when nothing is in force and the add-in's word that the backend did not start or restart says how to go on (owner decision 150A), and while a restart waits or is being made, when the host's promise is what is true and nothing new runs on the old backend (`settings.save`). Otherwise - a restart failed before it stopped the old backend, which runs on with the settings it was started with - it is the host's sentence "The saved settings are not in force yet: the review backend did not restart with them, so reviews run with the settings it was started with. Save the settings again to retry the restart." Every `init` carries it, so a page that loads or loads again is told; the page shows it on its banner whenever the banner says nothing else, until an `init` carries null, and takes it off at `backend.stopped`. *Amended on the 153A review, 2026-10-20:* each setting is compared as the backend's start reads it for the provider - the base URL for openai alone, trimmed, a blank one none, and Gemini Enterprise for gemini alone - so one a settings file carries for another provider makes no difference; and the page holds the sentence from the `status` of a restart that waited and failed as well (`status`, below). *Amended on the second 153A review, 2026-10-20:* `init` also carries `settings_not_in_force_revision`, the number of the host's reading of whether the saved settings are in force - one past the last reading's, a reading and its number taken together, in the order the host took them - and the page takes a reading only when its number is above the last it took, so an `init` read while a restart waited and delivered after that restart's failure word changes nothing. *Amended on the third 153A review, 2026-10-20:* it is null while a start of the backend is under way too - the add-in's first or a restart - which publishes the backend's endpoint before it records the settings it was made with: an `init` read between the two weighed the backend up against the settings recorded before it, and the page held the sentence, since the add-in's `ready` asks for no `init` on a page that has the backend. *Amended 2026-10-20 (owner decision 154A, the owner's follow-up):* `run_root` is the run root in force - the one the backend was last started with, under which every tab makes its run folders and finds its newest run - and `settings.run_root` the one the settings name, which the Settings panel's field for runs shows and the next restart brings into force; the two differ only while a save's restart waits, or after one failed (**The run root rule**, below). *Amended 2026-10-21 (owner decision 154A, with 153A's record of the settings in force):* `run_root` is the run root of 153A's record - the one the backend that is up was started with - moved by every start of the backend that succeeds, the add-in's first among them, and by nothing else; and `settings_not_in_force` weighs the run root too, as Windows names a folder, ignoring letter case: while the run root saved is not the one in force, alone or with other settings, it is the host's sentence "The saved settings are not in force yet: the review backend did not restart with them, so reviews run with the settings it was started with, and every tab makes its runs in the folder for runs it was started with, not the one saved. Save the settings again to retry the restart." - 153A's, with where runs are made meanwhile, since the Settings panel's field shows the folder saved; 153A's own while the run root saved is the one in force. *Amended on the reviews of owner decision 154A's merge (N4), 2026-10-21:* while the run root saved is not the one in force and the one in force is itself one the rule refuses - every start refused - `settings_not_in_force` is "The saved settings are not in force yet: the review backend did not restart with them, and no run can start until it does, since the folder for runs it was started with is refused. Save the settings again to retry the restart." rather than where runs are made, since none is. |
| `review.prepare` | `{}` | Read the active component tree without writing a run folder, resolving components, or contacting a model. Reply `review.prepared {preparation_id, document, component_count, unread_count, gap_count, instances, omitted_instances, requires_attention, standards_configured}`. At most 30 unread instances, strings capped at 200 characters. *Amended 2026-10-20 (owner decision 154A):* refused first, before the document is read, `RunRootRefused` when the run root is on a network share, reached through a link or written as a device path, or could not be checked (**The run root rule**, under the Terminal run folder below). |
| `review.start` | `{preparation_id?, retry_of?}` | Refuse if no document is open (`error`). A host advertising `review_preparation: true` in `init` requires the single-use id from its latest preparation and the same active document/configuration; otherwise `PreparationExpired`. Create the run folder, run the in-process dump, then `POST /sessions` using the stored `send_when_checked` value when this message is handled; reply `review.started {chat_id, run_dir, not_examined, document, send_when_checked}` where `not_examined` is the backend's `{sentence, instances}` warning or `null`, and `document` is `{path, configuration}` of the document the dump extracted (captured before the dump, in the shape `init` and `document.changed` carry). The page binds the results on screen to `document`: when `document.changed` names another path (ignoring case) or configuration, or no document, it hides the previous results and disables what acts on them until that document is open again. Unticked, the record and its `sessions.list` item carry `model_status: "not_sent"`; the ready status says "Checked {n} components by code; nothing was sent to the model.". Progress via `status` messages. *Amended 2026-10-20 (owner decision 149A):* once the backend is ready - after any settings restart the start made or waited for (`settings.save`, below) - the host reads the active document again, and when it is not the one read when the start began (the path compared ignoring case, the configuration exactly), or there is none, refuses `DocumentChanged`, retryable, before the run folder is made: nothing is extracted and no session is created, and the message names no path. It reads again whether or not a restart was made. `review.recheck` extracts nothing and asks SOLIDWORKS nothing, and is not read again. A `retry_of` naming a chat started with saved context extracts nothing either, but its checks run over the live bridge, which follows the active document, so it is read again too, and refused as one pressed on another document is (`context.review`, below). *Amended 2026-10-20 (owner decision 154A):* before anything else - the document, the preparation, the backend and a waiting settings restart - a start, a Retry and a context review's Retry are refused `RunRootRefused` when the run root is on a network share, reached through a link or written as a device path, or could not be checked, and nothing is read, made, extracted or asked of the backend (**The run root rule**, under the Terminal run folder below). |
| `context.prepare` | `{}` | Feature 016: extract a host-owned evidence run without creating a provider session; reply `context.prepared {run_id, package_sha256, document}`. The prepared run is bound to the current document/configuration and expires on replacement or document/configuration change. *Amended 2026-10-20 (owner decision 154A):* refused first, `RunRootRefused`, with nothing extracted, when the run root is on a network share, reached through a link or written as a device path, or could not be checked (**The run root rule**, under the Terminal run folder below). |
| `context.selection` | `{run_id, package_sha256}` | Read exactly one current component/face on the application thread against that prepared package. Reply `context.selected` with a unique saved target ID or explicit unresolved reason codes, `native_calibrated: false`, `native_model_state: selection_observation_only`, and `freshness: cannot_establish`. No selection, activation, native write, confirmation or cross-extraction rebinding is performed. Native refs and filesystem paths are not returned. |
| `context.review` | `{run_id, context_id, head_digest, package_sha256}` | Explicitly review the prepared saved package with the exact private context revision, without another dump. Host-owned run/document/config and package SHA must still match. `POST /sessions` validates context ID/head/package before provider setup. Reply through the existing `review.started` message; no automatic context attachment occurs in ordinary Review. *Amended 2026-10-15 (feature 016 on feature 015, owner decision 99A):* the review starts through the one `CreateReviewSession` `review.start` uses, so `POST /sessions` carries the stored `send_when_checked` beside the attachment, the reply is `review.started {chat_id, run_dir, not_examined, document, send_when_checked}`, and an unticked start's record is `not_sent` with the ready status "Checked {n} components by code; nothing was sent to the model.". *Amended 2026-10-15 (owner decision 108A):* `review.start {retry_of}` naming a chat the host started with saved context extracts nothing: it requires the same active document and configuration (`ReviewNotActive` otherwise) and posts `POST /sessions` with that chat's run folder, `retry_of` and the same attachment, Send or Wait from the box, through the same `CreateReviewSession`. *Amended 2026-10-20 (owner decision 149A, found on review):* it requires them again once the backend is ready - after any settings restart it made or waited for - and refuses a change with the same `ReviewNotActive`, retryable, in the same words, before `POST /sessions`: its checks run first, over the live bridge, which follows the active document, and would write another document's interference rows into this review's package. *Amended 2026-10-20 (owner decision 154A):* refused first, `RunRootRefused`, with no session asked for, when the run root is on a network share, reached through a link or written as a device path, or could not be checked (**The run root rule**, under the Terminal run folder below). |
| `review.recheck` | `{chat_id}` | *Feature 015 T108, 2026-10-15.* Re-run a restored waiting review's checks from its own run folder, as the first step of its Send ([015 recheck.md](../../015-review-send-gate/contracts/recheck.md) section 1). Refuse `InvalidRequest` (no `chat_id`), `UnknownChat` (no tracked review), `DrawingActive`, `ReviewNotActive` (another document or configuration is active) and `BackendUnavailable`, in that order, changing nothing. Otherwise post `status` `checking`, call `POST /sessions` with the record's folder, `send_when_checked: false` and `recheck: true` (no dump), replace the record (same folder and document, the new chat id, its `ModelStatus` kept), post `status` `ready` and reply `review.rechecked {chat_id, previous_chat_id, run_dir, not_examined, document}`. A backend refusal is rethrown with its class. *Amended 2026-10-20 (owner decision 154A):* before them all, `RunRootRefused` when the run root is on a network share, reached through a link or written as a device path, or could not be checked, the record kept (**The run root rule**, under the Terminal run folder below). |
| `settings.save` | `{provider, model, effort, api_key \| null, base_url, gemini_enterprise, run_root?}` | Refuse with `error {error_class: "TurnRunning"}` while any chat has a running turn. While a review waits at `awaiting_send`, saving is accepted. Otherwise encrypt the key with DPAPI, persist settings (a failed write is `SettingNotSaved`, leaving stored settings unchanged), restart the backend with the new environment; reply `settings.saved {settings (no key, including send_when_checked), key_source}`. A release build refuses `provider: "fake"` (FR-027). *Amended 2026-10-19 (owner decision 143A):* a turn can start after that check and before the restart - a follow-up, the answers or a Send reach the backend directly - and the restart is then refused, with the settings already written: the add-in's `BackendSupervisor` asks again before it stops the old backend. The save is kept: the reply is still `settings.saved`, and `status {stage: "error", message}` follows it with "the settings are saved; the backend restarts when the running turn ends." The host makes that restart once no remodel run is in progress and no chat has a running turn, however the turn ended, with the settings saved by then, so several saves restart it once, with the last; it then posts `backend.restarted {sentences}`, or, when the start fails, `status {stage: "error"}` with the failure, as a failed start is reported, and does not retry. Only a readable state, a 404 `UnknownChat` or a 400 `InvalidRequest` rules a chat's turn out; anything else - no answer at all, a 5xx, a body that is not the backend's - leaves the turn unknown and holds the restart back. After three such looks in a row the host stops looking and posts `status {stage: "error"}`, before anything a later save posts, saying the backend has not been restarted yet, that it will be before the next review or follow-up once it answers, and that saving the settings again restarts it now; the restart still waits, and the next review or page call that would start a turn looks once more. Until the restart is made, a new review (`review.start`, `review.recheck`, `context.review`), and an engineering context request that checks the backend (`context.prepare`, `context.selection`), makes the restart first or waits for the one being made, and is refused before anything is read, saying what holds the restart back - `TurnRunning` for a turn, `RemodelRunning` for a remodel run, `BackendUnavailable` for a backend that gives no answer - or `BackendUnavailable` with the failure when the restart it made or waited for failed, a save's own included; and the host answers a page call that would start a turn itself (the backend prefix, above). A save when no turn runs restarts at once, as before, and is that restart. The `TurnRunning` refusal of the check says the settings were not saved. *Amended 2026-10-19 (owner decision 145A):* a remodel run is treated as a turn. A save made while a remodel run is in progress - a plan or a Start's run (004 `pane-remodel-messages.md`) - is kept as above, and its restart waits for the run, which it would end with its copy half changed: the host reads the run under the restart's own lock, before it asks the backend anything, and the status says "the settings are saved; the backend restarts when the remodel run ends.", or, when a turn also started during the save, "the settings are saved; the backend restarts when the running turn and the remodel run end."; the restart is made once nothing holds it back, and a restart made after waiting reads the run again under its own lock after its look, which can answer without reading it - with no backend process at all - so it never ends one in progress. The status for a backend that does not answer now reads "the review backend is not answering, so it has not been restarted with the saved settings yet. It will be before the next review, follow-up or remodel run, once it answers; to restart it now, save the settings again.". A remodel run begins only once no restart waits: the host makes a waiting restart first, or waits for the one being made, a save's included, or refuses the run while something holds the restart back, or with the failure of the restart it made or waited for (004 `pane-remodel-messages.md`). Every restart the host makes, at once or after waiting, is told to the Model check, Standards and Remodel pages too (`backend.restarted`, in their tables below); a failed one is told to none of them as a restart. *Amended on review the same day:* one that failed once the old backend had stopped is told to them as a failed first start is told to every page - `status {stage: "error"}` with the failure, masked - since no backend answers the token they hold; one that failed before it stopped anything left the old backend up, and is told to the Review page alone. *Amended 2026-10-20 (owner decision 150A):* a save whose own restart fails is answered `error {error_class: "BackendNotRestarted", message, retryable: true}`, whatever the restart threw - a start that failed, or anything outside that wrapper, such as the new backend's log not opened - where a start that failed was answered `settings.saved` with the failure alone in a `status`, and anything else `HostError`, not retryable, as if nothing had been saved. The settings are written and saved in the host before the backend is restarted, so the message says "the settings are saved, but the review backend did not restart with them. Save the settings again to retry the restart. The restart failed: " and the failure, masked; nothing else is posted for it, and the other pages are told as above. The page shows the class's sentence on its Save line, with the message whole when it has no labels, and sends `ready` again, as after a save that restarted the backend, so it shows the settings saved and holds the backend there is now - the old one, or none; while that `init` names no backend its strip says "Backend not running", until one names a backend. *Amended on the 150A review, 2026-10-20:* the `status {stage: "error"}` a restart that waited posts when it fails ends with the way on, "Save the settings again to retry the restart.", true whether it stopped the old backend or failed before it did; and the other pages' `status` for one that failed once the old backend had stopped ends "Save Settings on the Review tab to start it again.". On a `BackendNotRestarted` answer the page marks its backend replaced, as `backend.restarted` does, so the first `init` that names a token other than the one it held is a new backend - its old chat's stream closed, a live waiting review restored - even after an `init` that named none *Amended 2026-10-20 (owner decision 153A):* the saved settings are in force once the backend has restarted with them, and not before - this row's earlier words, which called the saved settings "in force", say "saved" now. A restart that fails before it stops the old backend - the configured launcher cannot be resolved, say - leaves that backend up with the environment it was started with, the key, `OPENAI_BASE_URL` and Gemini Enterprise among it, and nothing waits any more. Until a restart succeeds every session - `review.start`, a Retry, `review.recheck` and `context.review` - is created with the provider, model and effort that backend was started with, never the saved ones, so no session pairs one provider's settings with another's credentials; and `init` carries the sentence that the saved settings are not in force (`ready`, above). A restart that succeeds, a save's at once or one that waited, puts the settings it was made with in force; one that fails leaves the settings in force as they were, and with no backend up nothing is in force. The `status {stage: "error"}` a restart that waited posts when it failed before it stopped the old backend ends, while the saved settings are not the ones in force, with that sentence, which ends with the same way on, rather than with the way on alone. The answer to a save whose restart failed is unchanged: the page asks for its `init` after it *Amended on the 153A review, 2026-10-20:* while the saved settings are not in force the backend holds the key it was started with, so the host masks that key in everything it posts as well as the saved key, and hands both to the Model check, Standards and Remodel pages' hosts to mask (FR-015) *Amended on the second 153A review, 2026-10-20:* the add-in's first start of the backend is the host's too, made under the lock every settings restart holds, with the settings saved when it is made, which it records in force as a restart does; one made once a save's restart has started the backend starts nothing, and one made after a save whose restart failed starts the backend with the saved settings. What the first start tells the pages - `backend_starting`, then `ready`, or the failure with the way on - is unchanged *Amended on the third 153A review, 2026-10-20, and worded on the fourth, 2026-10-21:* while a start of the backend is under way, no session is made: one asked for then is refused with `error {error_class: "BackendUnavailable", retryable: true}`, in the words a review asked for before the backend is up is given; and the key the start was made with is masked as well, by this host and the hosts it hands the keys to *Amended on the fourth 153A review, 2026-10-21:* every key a start of the backend has been made with - the first start's and every restart's, made or failed - is masked from just before that start for as long as the host lives, since a start's failure is told once the start is over, when a save made meanwhile can have replaced the saved key; and a `review.recheck` refused while a start is under way posts no `checking` `status` first. *Amended 2026-10-20 (owner decision 154A, with the owner's follow-up the same day, "A Field + don't block"):* the payload carries `run_root`, the Settings panel's folder for runs: absent, null or not text, the run root stays as the settings name it; trimmed, and empty, it chooses the default, `Documents\SwReview\runs`. A save is never refused for the run root. A folder that differs from the run root the settings name, compared as written, is judged by the run root rule after the `TurnRunning` gate and the payload's own refusals: accepted, it is written with the rest and comes into force with the save's restart - the backend is started with the run root and makes and finds runs under it alone - so a restart that waits, or fails, leaves the run root in force as it was until one is made (`init.run_root`); refused - on a network share, reached through a link or written as a device path, or could not be checked - it is the one field not written, and the answer carries `run_root_refusal {error_class: "RunRootRefused", message, retryable: false}`, whose message says what the folder chosen is, that the run root was not changed and the other settings were saved, and the way on, a local folder chosen and saved again, with no path. A save that chooses no other folder keeps the run root the settings name - the file's, or the default when it names none - and when the rule refuses that one its answer carries `run_root_refusal` saying every run is refused until the run root is changed and the settings were saved, with the way on. `run_root_refusal` rides on `settings.saved`, and on the `BackendNotRestarted` error of a save whose restart failed, which was written all the same. The page shows it under the field, the class's sentence first with the class and the message in a fold, or with no labels the message; the next save written takes it down when its answer carries none, and a save refused before anything was written leaves it. This replaced, before it landed, the first answer to 154A, which refused such a save whole ([research.md](../research.md), 154A; **The run root rule**, under the Terminal run folder below). *Amended the same day (154A's reviews, finding F7):* a folder chosen that is not written as a full path - a drive letter and a separator, or two separators - is the one field not written, before the rule is asked, and the answer carries `run_root_refusal {error_class: "RunRootNotFullPath", message, retryable: false}`, whose message says the folder chosen is not written as a full path, starting with its drive letter, that the run root was not changed and the other settings were saved, and to type the folder's full path, with no path; a relative run root the settings file names keeps working. *Amended on the reviews of owner decision 154A's merge, 2026-10-21:* `run_root` loses one pair of double quotes around the whole, after it is trimmed, and what they held is trimmed again - Explorer's "Copy as path" puts them there (F2); a quote on one side alone stays, and is no full path. A folder chosen with a folder name ending in a space or a period is refused by the rule (F1, **The run root rule**), so it is the one field not saved, with `run_root_refusal` `RunRootRefused`. |
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

*Amended 2026-10-20 (owner decision 152A):* every start that makes a review session - `review.start`
(a new review, or a Retry, with saved context or without), `context.review` and `review.recheck` -
asks which document and configuration the bridge it would hand to `POST /sessions` serves - the
tool service's record of its attach, which the bridge's `ping` answers - and hands over only one on
the review's document, by the rule above (the path ignoring case, the configuration exactly). One on
another document, or one no tool service listening now has, is refused
`error {error_class: "BridgeOnAnotherDocument", retryable: true}`, in words that name no path: no
session is created and no status of an extraction or a check is posted - a Recheck posts `checking`
only once its bridge is asked - and the host asks the tool service to follow the active document,
which it does once no review turn or remodel holds the bridge, so that pressing again goes ahead. A
new review is asked before its run folder is made, so nothing is extracted; every start is asked
again at its session, which is given the very bridge asked about. With no bridge published - no
tool service listening - the session is given none, as before. How the tool service follows is 004
[`pane-remodel-messages.md`](../../004-resilient-remodeler/contracts/pane-remodel-messages.md),
decision 22A's section.

*Amended 2026-10-20 (owner decision 152A, on the Codex review):* a new review's `review.start` reads
the active document again once its evidence is extracted - the extraction runs in one call on the
application thread, so a switch made during it lands as it ends, and a configuration switch
re-attaches no bridge, whose record still names the review's configuration - and refuses one that is
not the review's, by the rule above, `error {error_class: "DocumentChanged", retryable: true}`, in
words true there that name no path: no review session was started and no check ran; make the part or
assembly and the configuration active again, then press Review. The run folder keeps what was
extracted, and the tool service is asked nothing. A new review refused after its extraction - so, or
`BridgeOnAnotherDocument` at its session - then posts
`status {stage: "ready", message: "Evidence extracted, but no review was started; no review tokens used."}`,
which ends the extraction's statuses. The bridge a session is given refuses its live commands while
its document's active configuration is not the one it attached in ([`chat-api.md`](chat-api.md)).
And every start that makes a session holds the tool service's attachment from before it reads the
bridge until its session is tracked, and every page call the proxy passes on that would start a turn
holds it while the call is out, so the tool service does not take that bridge down under them to
follow the active document; with no service listening to hold, both go on as before.

*Amended 2026-10-21 (owner decision 152A merged with 153A and 154A; [research.md](../research.md),
152A, the merge of `main`):* where these refusals meet 153A's and 154A's, they come in the order
those decisions leave - 153A reads a start under way before anything of the settings in force, the
run root among them, and 154A judges the run root, and the folder under it, before anything is asked
or made under it (corrected on the final reviews, N1). At a review session: a start of the backend
under way (`BackendUnavailable`), then the run root judged again (`RunRootRefused`,
`RunRootChosenNotInForce`) and the run folder under the run root in force (`RunRootChanged`), and
only then the bridge (`BridgeOnAnotherDocument`), so a start refused for any of the first takes no
hold and asks the tool service to follow nothing; a Recheck posts `checking` only after all of them.
Before a new review's extraction: the run root judged again, then the bridge. After it: the document
read again (`DocumentChanged`), then the session; and a new review refused at its session, whatever
refused it, posts the `ready` status above.

*Amended 2026-10-21 (owner decision 152A, on its final reviews: C1; [research.md](../research.md),
152A, the final reviews):* a start that finds no service to hold while a bridge is published - a
re-attach that ended since the hold was asked for, or one taking its service down - asks for the
hold once more and reads the bridge again under it; with still none to be had, it is refused
`BridgeOnAnotherDocument`, retryable, rather than given a bridge nothing holds. With nothing
published, the session is given none, as before.

`report.open` and `folder.open` resolve the path from the host's own session record keyed by
`chat_id`; the page never supplies a path. `log.open` uses the host's log folder. Every
resolved path is canonicalized and must be a descendant of `run_root` (or the log folder)
before it reaches `ShellExecute`; anything else is answered `error`. *Amended 2026-10-20 (owner
decision 154A's reviews, finding F6):* of any run root in force in this SOLIDWORKS session - the one in
force, or one a settings save has since moved from - on every tab that opens a run, so a run made
before the move still opens.

*Amended 2026-10-21 (feature 004, owner decision 159A; 004 `research.md` R19.3):* a failure these
shared rows catch - Windows that would not open a file or a folder, SOLIDWORKS that would not show an
entity - is answered with its own message on every tab but the Remodel tab, whose host answers in its own
plain words (`PaneActionsOptions.FailureWords`), since the message can name a path, and writes the message
to the add-in's log. The Remodel tab tells the add-in's word that the backend did not start in its own words
as well, `RemodelHost.BackendDidNotStartMessage`, with this section's way on; the Review tab shows the
failure whole.

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
| `status` | `{stage: "extracting" \| "backend_starting" \| "checking" \| "ready" \| "error", message}`. Checking saved evidence again posts `checking` with "Checking the saved evidence again...", then `ready` with "Checked the saved evidence again; nothing was sent to the model." on success. *Amended on the 150A review, 2026-10-20:* the add-in's `error` for a first start that failed ends with the way on, "Save Settings to start it again.", and the `error` for a restart that waited and failed with "Save the settings again to retry the restart." (`settings.save`); the failure is followed by a full stop when it does not end in one *Amended 2026-10-20 (owner decision 153A):* when that restart failed before it stopped the old backend, and the saved settings are not the ones that backend was started with, the `error` ends instead with "The saved settings are not in force yet: the review backend did not restart with them, so reviews run with the settings it was started with. Save the settings again to retry the restart.", which ends with the same way on (`ready` and `settings.save`, above) *Amended on the 153A review, 2026-10-20:* that `error` carries `settings_not_in_force` as well - the sentence, or null - as `init` does, since no `init` follows it, and the page holds it from there as from `init`; no other `status` carries it, and one that does not leaves what the page holds as it is *Amended on the second 153A review, 2026-10-20:* with `settings_not_in_force_revision`, the number of that reading (`ready`, above) |
| `document.changed` | `{path, configuration, kind, drawing_guidance?} \| null` when the active document changes - and, since feature 009 (FR-022), when the active document's configuration changes: the add-in follows the active part's or assembly's `ActiveConfigChangePostNotify` and runs the same fan-out, so every host posts this with the new configuration. *`kind` and a drawing's `drawing_guidance` added 2026-09-28 (U25), as `init`'s* |
| `backend.stopped` | `{exit_code, log_path}`. *Amended 2026-10-20 (owner decision 150A):* the page says "The backend stopped. Save Settings to start it again.": the add-in starts the backend when it loads and a settings save restarts it, so reopening the pane, which the sentence named before, starts nothing. No host posts it *Amended 2026-10-20 (owner decision 153A):* a backend that stopped holds no settings, so the page takes the sentence that the saved settings are not in force (`ready`) off its banner, and holds it no more |
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

*Amended 2026-10-20 (feature 011, owner decision 148A; its research R12.3):* the helper,
`RunFolders`, makes every run folder - a review's, a Model check's, a Standards check's, a
re-modeler's run's and the terminal's - in its full form, named under `Path.GetFullPath` of
`run_root`, whatever spelling the setting holds, and its two searches, the check tabs' newest folder
and the waiting review, answer in the same form. A folder spelled with a `..` segment, which the
backend's rule for a run folder refuses, is never handed on, and a folder made is spelled as the
same folder found.

**The run root rule** (*added 2026-10-20, owner decision 154A, with the owner's follow-up the
same day and its reviews*; [research.md](../research.md), 154A). A run root is acceptable only when it
is a local folder reached by its own path, and one the add-in can check. Every run start judges the
run root in force - the one the backend was last started with, which every tab's `init` names as
`run_root` and makes its run folders under - and refuses it - first, with nothing read, made,
extracted, restarted or asked of the backend - when it is on a network share (written as a UNC path,
on a mapped network drive, or with its final path on a share), reached through a link (on a
substituted drive, with a junction, a symbolic link or a volume's mount point among its existing
folders, or with any final path that differs from its spelling, and from its long-name form, other
than by letter case), written as a Windows device path, or could not be checked (a part of its path
there but unreadable as itself, or a final path or a needed long-name form that cannot be read). The
rule reads nothing before it can refuse: the root's text first, a share or a device path refused on
sight; then its full path, made from the text alone, which expands no 8.3 short name and reads
nothing; then the drive by its letter; then each part as itself; and only then, when the final path
is not the spelling, the long-name form. A root not made yet is judged by its nearest existing
folder; one no folder can be made under - blank, written with a character no folder can have, on a
drive letter that names no drive - is left to the run folder, as before. The refusal is
`error {error_class: "RunRootRefused", message, retryable: false}`. The words file's sentence, which
the Review page shows, states the rule and the way on, a local folder chosen for runs in Settings;
the message says which of the four the root is, what was not done there, and the way on, and names no
path - on the Review tab "Choose a local folder for runs in Settings, then try again.", and on the
Model check, Standards and Remodel pages, which print it whole and have no Settings of their own,
"Choose a local folder for runs in Settings on the Review tab, then" what to press there (003
`model-check.md`, 004 `pane-remodel-messages.md`, 006 `standards-check.md`). A start that can meet a
settings restart - a review and context evidence once the backend is ready, every review session
before it is asked for, a plan and a Start once their gate is passed - judges again a run root the
restart moved before it makes or hands on anything under it. And a run that would go on in a folder
not under the run root in force - a `review.recheck`, a `context.review`, a context review's Retry, a
review whose run root moved while its evidence was extracted, a `remodel.start` - is refused before the
backend is asked, `error {error_class: "RunRootChanged", message, retryable: false}`, whose message
says the folder is under a run root no longer in force, what was not done, and the way on, with no
path; the backend would refuse the folder inside the run. Every run root in force this session still
holds the pane's runs: `report.open` and `folder.open` on every tab, and the Remodel tab's knowledge of
its own copies. The starts: `review.prepare`,
`review.start` (a review, a Retry, a context review's Retry), `review.recheck`, `context.prepare`,
`context.review`, `check.start`, `standards.start`, and the Remodel page's `remodel.plan` and
`remodel.start` (004 `pane-remodel-messages.md`). The settings are never refused for the run root:
the Settings panel's field for runs is judged by the same rule, and a save writes the folder chosen
only when the rule accepts it, and says when that folder, or the run root it keeps, is refused
(`settings.save`, above); `send_when_checked.save` writes the run root back as the settings name it.
Not refused either: `context.selection`, the actions on a run already made, the searches of the run
root, the Extract tab, which makes no run folder, and the Terminal tab, which is hidden. The
backend's rule for a run folder (`chat-api.md`, "Path rule for `run_dir`") is unchanged: the backend
is started with the run root, and refuses a run folder outside it, so a run root saved comes into
force with the restart that starts the backend with it, and every tab makes its run folders, and
looks for its newest run, under the run root in force until then.

*Amended 2026-10-21 (owner decision 154A, with 153A's record of the settings in force; [research.md](../research.md), 154A, the merge of `main`):*
the run root in force is the run root of the settings in force (`init`, above), so it moves with every start
of the backend that succeeds - the add-in's first among them - and with nothing else. A start publishes the
backend's endpoint before it records the settings it was made with, and can still fail and leave the backend
it would replace, so while one that would bring another run root into force is under way, `check.start`,
`standards.start`, and `remodel.plan` and `remodel.start` once their gate is passed, are refused before
anything is made, `error {error_class: "BackendUnavailable", message, retryable: true}`, whose message says
the review backend is being started with another folder for runs, what was not done, and the same press in a
moment; each reads the run root once, so the one judged is the one its folder is made under. The Review tab's
starts need no refusal of their own: they take the run root once the backend is ready, when the only start
that can be under way is the add-in's first, and a review session is refused while a start is under way
(153A) and when its folder is not under the run root in force (`RunRootChanged`, above).

*Amended on the reviews of owner decision 154A's merge, 2026-10-21 ([research.md](../research.md), 154A, the reviews of the merge):* the rule
refuses a fifth kind of run root, on its text before anything is read: one with a folder name - any, the last
too, but `.` and `..` - that ends in a space or a period, which Windows reads both with and without it, so
the add-in's run folders and the backend's run root would be two folders (F1); and it leaves a folder name
longer than 255 characters to the run folder, as a character no folder can have, rather than calling it a
part that cannot be read (N8). While another folder chosen for runs is saved than the run root in force - a
save's restart failed - a start refused for the run root in force is
`error {error_class: "RunRootChosenNotInForce", message, retryable: false}`, whose message says what the run
root in force is, what was not done, and that the folder chosen is not in force until the review backend
restarts with it, with the way on, to save the settings again to retry the restart - not to choose a local
folder, which the engineer has just done (N4). And a `check.start` or a `standards.start` reads the run root
once to judge it and make its folder, and again once its extraction is over: a run whose folder the run root
in force no longer holds - a settings save's restart brought another in meanwhile - is answered
`RunRootChanged`, and one while a start that would bring another in is under way `BackendUnavailable`, so the
page's first call can still meet a restart only in its own round trip (N6).

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
| `check.start` | `{scope: "part"}` | Refuse with `error {error_class: "NoDocument"}`, `"NotAttached"` or `"NotAPart"` as applicable. Otherwise create the check run folder, run the `ModelCheck` profile dump in process, register that folder as the pane's latest run, and reply `check.extracted {run_dir, document, configuration, counts, gaps}`. Progress via `status`. The host stops there: the page calls `POST /checks/rms` itself, with the token and origin from `init`. *Amended 2026-10-20 (owner decision 154A):* refused first, before every other refusal, `RunRootRefused` when the run root is on a network share, reached through a link or written as a device path, or could not be checked, in words the page prints whole; no check folder is made and nothing is extracted (**The run root rule**, under the Terminal run folder above). *Amended 2026-10-21 (owner decision 154A, with 153A's record of the settings in force):* refused first, `BackendUnavailable`, retryable, while a start of the backend under way would bring another run root into force, in words the page prints whole; the run root is read once, so the one judged is the one the check folder is made under (**The run root rule**). *Amended on the reviews of owner decision 154A's merge, 2026-10-21:* the run root is read again once the extraction is over, and a check whose folder it no longer holds is answered `RunRootChanged`, not retryable, or, while a start that would bring another in is under way, `BackendUnavailable`, retryable, rather than `check.extracted` (N6); and a start refused for the run root in force while another folder chosen for runs is not in force is `RunRootChosenNotInForce` (N4; **The run root rule**). |
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
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}`. *Amended 2026-10-19 (feature 002, owner decision 145A, found on review):* `error` also when a settings restart failed once the old backend had stopped, with the failure, masked, as a failed first start is told: no backend answers the token of the page's last `init`. *Amended on the third review the same day:* the add-in marks its own word on the backend - `backend_starting`, `ready`, and `error` for a failed start or restart - `lifecycle: true`, and the page takes down a banner it put up for such an `error` once a later `init` names a backend; no other banner *Amended 2026-10-20 (owner decision 150A):* from such an `error` the page's backend strip says "Backend not running" until an `init` names a backend - through an `init` that names none, and whatever banner is put up meanwhile - where it followed `init` alone and said "Backend ready" under that banner; any other `error` leaves the strip as it was *Amended on the 150A review, 2026-10-20 (owner decision 150A):* the add-in's `error` - a first start that failed, or a settings restart that failed once the old backend had stopped - ends with the way on, "Save Settings on the Review tab to start it again.": the failure is followed by a full stop when it does not end in one, then that sentence |
| `document.changed` | `{path, configuration, kind} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}`. *Amended 2026-10-20 (owner decision 150A):* the page says "The backend stopped. Save Settings on the Review tab to start it again.": the add-in starts the backend when it loads and a settings save, made on the Review tab, restarts it, so reopening the pane, which the sentence named before, starts nothing. No host posts it |
| `backend.restarted` | `{sentences}` - *added 2026-10-19 (owner decision 145A):* the host restarted the backend with saved settings, a save's restart made at once or one made after it waited (`settings.save`); `sentences` is empty, since the Review tab's sentences about a restart that waited are shown there alone. The page sends `ready` again - once more after an `init` already on its way - takes the new port and token, and keeps the check on screen without reading its latest check again. *Amended 2026-10-19 (owner decision 145A, found on review):* a call the page makes while that `init` is on its way waits for it, since the host answers it behind an extraction already running on the tab's pump; and a latest check the old token could not read is read again by the next `init` until it is read or a check is pressed; a call waits for an `init` on its way whether it is applied or refused, and an Accept's re-read is shown only while its check is the one on screen (003 `contracts/model-check.md`, amended on the third review) *Amended 2026-10-20 (owner decision 150A):* one not shown is said in the banner, as a re-read that failed is, with the exception the Accept wrote: "Accepted as {exception_id}, and the exception is saved; a newer check was pressed before this check was re-read. Press the check again to see where it stands." |

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
| `standards.start` | `{}` | Refuse with `error {error_class: "NoDocument"}`, `"NotAttached"`, `"NeverSaved"` (the document has never been saved, so it has no name or folder for the library and part-number checks to read), `"UnsupportedKind"` (it is not a part, an assembly or a drawing) or `"NoProfile"` (none is configured, or the file at the configured path cannot be opened) - **every refusal comes first, the profile check among them, so a refused run leaves no run folder behind**. Otherwise create the check run folder, run the `Standards` profile dump in process, register that folder as the pane's latest run, and reply `standards.extracted {run_dir, document, configuration, counts: {documents, features, cut_list_items, drawing_sheets}, gaps}`. Progress via `status`. The host stops there: the page calls `POST /checks/standards` itself, with the token, the origin and the `profile_path` from `init`. *Amended 2026-10-20 (owner decision 154A):* refused first, before every other refusal, `RunRootRefused` when the run root is on a network share, reached through a link or written as a device path, or could not be checked, in words the page prints whole; no run folder is made and nothing is extracted (**The run root rule**, under the Terminal run folder above). *Amended 2026-10-21 (owner decision 154A, with 153A's record of the settings in force):* refused first, `BackendUnavailable`, retryable, while a start of the backend under way would bring another run root into force, in words the page prints whole; the run root is read once, so the one judged is the one the run folder is made under (**The run root rule**). *Amended on the reviews of owner decision 154A's merge, 2026-10-21:* the run root is read again once the extraction is over, and a run whose folder it no longer holds is answered `RunRootChanged`, not retryable, or, while a start that would bring another in is under way, `BackendUnavailable`, retryable, rather than `standards.extracted` (N6); and a start refused for the run root in force while another folder chosen for runs is not in force is `RunRootChosenNotInForce` (N4; **The run root rule**). |
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
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}`. *Amended 2026-10-19 (feature 002, owner decision 145A, found on review):* `error` also when a settings restart failed once the old backend had stopped, with the failure, masked, as a failed first start is told: no backend answers the token of the page's last `init`. *Amended on the third review the same day:* the add-in marks its own word on the backend - `backend_starting`, `ready`, and `error` for a failed start or restart - `lifecycle: true`, and the page takes down a banner it put up for such an `error` once a later `init` names a backend; no other banner *Amended 2026-10-20 (owner decision 150A):* from such an `error` the page's backend strip says "Backend not running" until an `init` names a backend - through an `init` that names none, and whatever banner is put up meanwhile - where it followed `init` alone and said "Backend ready" under that banner; any other `error` leaves the strip as it was *Amended on the 150A review, 2026-10-20 (owner decision 150A):* the add-in's `error` - a first start that failed, or a settings restart that failed once the old backend had stopped - ends with the way on, "Save Settings on the Review tab to start it again.": the failure is followed by a full stop when it does not end in one, then that sentence |
| `document.changed` | `{path, configuration, kind} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}`. *Amended 2026-10-20 (owner decision 150A):* the page says "The backend stopped. Save Settings on the Review tab to start it again.": the add-in starts the backend when it loads and a settings save, made on the Review tab, restarts it, so reopening the pane, which the sentence named before, starts nothing. No host posts it |
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
