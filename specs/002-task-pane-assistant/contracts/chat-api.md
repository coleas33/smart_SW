# Reviewer Backend API

One loopback service, not one per tab: `swreview chat serve` is the **reviewer backend**,
and it serves **checks as well as chats**. The `/sessions/*` routes run a review turn
through a provider; the `/checks/*` routes (feature 003, User Story 6) grade a model
against the Resilient Modeling rules and construct no provider, read no key and make no
network call at all. Everything below - the handshake, the token, the origin rules, the
error body and the `run_dir` path rule - holds for both families, which is why they share
one process and one door rather than a second server with a second copy of all of it.

`swreview chat serve --port 0 [--run-root <dir>]` starts a loopback HTTP server. The first
stdout line is `{"port": 51234, "token": "<32 bytes base64url>"}`; nothing else is ever
printed to stdout. The server MUST run with a logging configuration whose `default` **and**
`access` handlers write to `stderr` (uvicorn's default sends the access log to stdout, which
would corrupt the handshake and can block the child once the parent stops draining the
pipe). Diagnostics go to stderr and to the log folder. Every request carries
`Authorization: Bearer <token>`; a missing or wrong token returns 401 and is logged without
the token. The token MUST NOT appear in a URL, a query string, or a log line. The server
binds `127.0.0.1` only.

Provider credentials arrive in the child's environment (`OPENAI_API_KEY`, `GEMINI_API_KEY`,
`OPENAI_BASE_URL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`); the server never reads
the settings file.

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/health` | | `{status: "ok", version, providers: ["openai", "gemini"]}`; a development build also lists `"fake"` |
| GET | `/models?provider=openai\|gemini\|fake` | | `{models: [{id, label}]}` from the provider; `fake` returns one scripted id; 502 with the provider error class on failure |
| POST | `/sessions` | `{run_dir, provider, model, effort, bridge: {pipe, secret} \| null, engineer, retry_of: chat_id \| null}` | `201 {chat_id, review_session_id}`; starts the review turn immediately. 400 if `run_dir` fails the path rule below or `run_dir/package.json` is missing or invalid. |
| GET | `/sessions/{chat_id}` | | `ChatSession` state without `token` and without `bridge` (neither the HTTP token nor the bridge secret is ever echoed) |
| GET | `/sessions/{chat_id}/events` | `Last-Event-ID` header optional | `text/event-stream`; replays from `events.jsonl` after the given id, then live. Event `id` = `seq`, `event` = `type`, `data` = JSON body. |
| POST | `/sessions/{chat_id}/messages` | `{text}` | 202; appends a user turn and runs, including on a session whose previous turn already ended (`ended → running`, see data-model section 3). 409 if a turn is running. |
| POST | `/sessions/{chat_id}/evidence/{request_id}` | `{answer}` | 202; marks answered, resumes. 404 unknown request; 409 already answered. |
| POST | `/sessions/{chat_id}/findings/{finding_id}/disposition` | `{decision, note, by}` | 200 with the `Finding`; 409 on an illegal transition. Re-renders `report.md`. |
| POST | `/sessions/{chat_id}/stop` | | 202; ends the turn at the next tool boundary, emits `turn.ended {reason: "stopped"}`, then writes `session.ended`. Idempotent: on a session that already has an `ended_at` it is 202 with the current state and no second terminal event pair. |
| GET | `/sessions/{chat_id}/report` | | `text/markdown` of `report.md` |
| POST | `/checks/rms` | `{run_dir, scope: "part" \| "equations" \| "all", document_id: str \| null}` | `201 CheckResult` (feature 003 `contracts/model-check.md`). Runs synchronously: no provider, no network call, no turn, and no chat is registered for the folder. 400 when `run_dir` fails the path rule, when `run_dir/package.json` is missing or invalid (`InvalidPackage`), when the package carries no feature rows (`EmptyFeatureTree`), when the carry-forward candidate cannot be parsed (`UnreadableExceptions`), or when `scope` is `"assembly"` (`ScopeNotAvailable`) |
| GET | `/checks/{check_id}` | | `200 CheckResult` re-read from that check run folder - the recorded `session.json` and `check.json`, with nothing evaluated and nothing written, so a refresh cannot overwrite a recorded disposition; `404 UnknownCheck` when the run root holds no such folder, no check ran in it, or its session is no longer the one its record names |
| POST | `/checks/{check_id}/exceptions/{finding_id}` | `{note, by}` | `200 {finding, exception_id}` with the finding re-rendered as checked within scope; `400 EmptyNote` on a blank note; `404 UnknownCheck` / `UnknownFinding`; `409 RuleNotAcceptable` for a `warn` rule (FR-016); `409 AlreadyAccepted` when an active exception already covers the condition. Re-renders `report.md` |
| OPTIONS | any path | | 204 preflight, **answered without a token** (see Origin and CORS) |

Errors: JSON `{error_class, message, retryable}` with the message redacted of any
configured key. 5xx only for server faults; provider failures surface as 502 with the
provider's error class name.

Concurrency: one running turn per chat; the server serializes messages and evidence
answers per chat and refuses with 409 rather than queueing silently.

## Path rule for `run_dir`

`run_dir` is caller-supplied. The server canonicalizes it (`Path.resolve()`), rejects UNC
and Win32 device paths, and requires the result to be a descendant of the configured
`--run-root` (the pane passes the settings `run_root`). Anything else is 400 with
`error_class: "InvalidRunDir"`. The same rule applies to every host-side path action in
`pane-host-messages.md`.

`check_id` is the check run folder's *name*, so a check is addressable after a restart
without any server-side registry. It is caller-supplied too and goes through the same
rule, resolved under the run root; a path the rule refuses is answered `404 UnknownCheck`
rather than `400`, so the route cannot be used to probe the workstation.

## Origin and CORS

The pages are served from the add-in's virtual host (`https://swreview.invalid/`, fixed in
`pane-host-messages.md`), so every call from a page to `http://127.0.0.1:<port>` is
cross-origin and carries `Authorization`, which makes it non-simple and triggers a
preflight. The server therefore:

- answers `OPTIONS` on every route **without requiring a token** (a preflight never carries
  author headers) with 204;
- echoes `Access-Control-Allow-Origin: <the exact configured virtual-host origin>` — never
  `*`, because the loopback port is reachable from any browser on the workstation — plus
  `Vary: Origin`, `Access-Control-Allow-Headers: authorization, content-type, last-event-id`,
  `Access-Control-Allow-Methods: GET, POST, OPTIONS`, `Access-Control-Max-Age: 600`, and
  `Access-Control-Allow-Private-Network: true` for Chromium's private-network preflight;
- refuses any request whose `Origin` header is present and is not the configured origin,
  with 403, before authentication.

The virtual-host origin is passed to the backend at start (`--allow-origin <origin>`).
`http://127.0.0.1` is a potentially-trustworthy origin, so an `https://` virtual host
reaching it is not mixed content; the virtual host keeps `https://`.

## Reading the event stream

The page MUST read `GET /sessions/{chat_id}/events` with `fetch` plus a `ReadableStream`
reader, not `EventSource`: only `fetch` can set `Authorization` and `Last-Event-ID`.
Putting the token in the URL is forbidden (it would land in access logs, WebView2 history
and crash dumps).

## Shutdown and settings changes

A running turn owns process state that is not on disk, so:

- `settings.save` in the pane MUST NOT restart the backend while a turn is running; the host
  refuses with `error {error_class: "TurnRunning"}` and the page offers Save again when the
  turn ends (`pane-host-messages.md`).
- On any shutdown signal the server finalizes every live chat before exiting: it writes
  `turn.ended {reason: "error"}` when a turn was mid-flight, then `session.ended` with an
  `ended_at`, and saves `session.json`. A session is never left without an ended time
  (FR-008), including the provider-failure path that raises out of the runner.
