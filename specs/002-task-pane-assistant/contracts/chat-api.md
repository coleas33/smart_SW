# Reviewer Backend API

One loopback service, not one per tab: `swreview chat serve` is the **reviewer backend**,
and it serves **checks as well as chats**. The `/sessions/*` routes run a review turn
through a provider; the `/checks/*` routes grade a design without one - against the
Resilient Modeling rules (feature 003, User Story 6) or against a standards profile
(feature 006, User Story 3) - and construct no provider, read no key and make no
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
| POST | `/sessions/{chat_id}/timing` | `{baseline?, supervision?, verification?, false_alarms?}` - numbers or null; every key optional | 200 with the recomputed `Timing`, net included. Writes the **live** session the run holds and re-renders `report.md` with that run's package, so the values survive the next turn; **emits no event**, because timing is the engineer's bookkeeping and not something the review did. `400 InvalidTiming` naming the key for a key that is not one of the four (including `net_saved_minutes`, which is derived and never accepted), a value that is not a number, or a negative one; `404 UnknownChat`; `409 TurnRunning` / `SessionFailed` as `disposition`. Check runs register no chat, so they are timed from the command line. `specs/007-attention-policy-gate/contracts/timing.md` is normative. |
| POST | `/sessions/{chat_id}/stop` | | 202; ends the turn at the next tool boundary, emits `turn.ended {reason: "stopped"}`, then writes `session.ended`. Idempotent: on a session that already has an `ended_at` it is 202 with the current state and no second terminal event pair. |
| GET | `/sessions/{chat_id}/report` | | `text/markdown` of `report.md` |
| POST | `/checks/rms` | `{run_dir, scope: "part" \| "equations" \| "all", document_id: str \| null}` | `201 CheckResult` (feature 003 `contracts/model-check.md`). Runs synchronously: no provider, no network call, no turn, and no chat is registered for the folder. 400 when `run_dir` fails the path rule, when `run_dir/package.json` is missing or invalid (`InvalidPackage`), when the package carries no feature rows (`EmptyFeatureTree`), when the carry-forward candidate cannot be parsed (`UnreadableExceptions`), or when `scope` is `"assembly"` (`ScopeNotAvailable`) |
| POST | `/checks/standards` | `{run_dir, profile_path: str}` | `201 StandardsResult` (feature 006 `contracts/standards-check.md`, the normative source for this row and the two below). Runs synchronously for the same reasons as `/checks/rms`: no provider, no key, no network call, no turn, and no chat is registered for the folder. **There is no `scope`**: every standards check runs on every run, the document kinds decide which apply, and a body carrying one is refused rather than quietly answered. 400 when `run_dir` fails the path rule, when `run_dir/package.json` is missing or invalid (`InvalidPackage`), when the package does not record the phases the standards checks read (`MissingStandardsPhases`), when the root document has no recorded kind or no path (`UngradableRoot`), when `profile_path` is absent, unreadable or not configured (`ProfileUnreadable`), when the profile parses and fails its schema (`ProfileInvalid`), or when the carry-forward candidate cannot be parsed (`UnreadableExceptions`) |
| GET | `/checks/{check_id}` | | `200` re-read from that check run folder - the recorded `session.json` and `check.json`, with nothing evaluated and nothing written, so a refresh cannot overwrite a recorded disposition; `404 UnknownCheck` when the run root holds no such folder, no check ran in it, or its session is no longer the one its record names. The answer is **the record's own family shape**: a `CheckResult` for a folder whose `check.json` carries `family: "rms"` or no `family` at all, a `StandardsResult` for `family: "standards"`. Neither family ever answers for the other: the route answers in the record's own family shape, and a page reads back only the ids its own evaluation route produced - handed the other family's shape it renders nothing it cannot read |
| POST | `/checks/{check_id}/exceptions/{finding_id}` | `{note, by}` | `200 {finding, exception_id}` with the finding re-rendered as checked within scope; `400 EmptyNote` on a blank note; `404 UnknownCheck` / `UnknownFinding`; `409 RuleNotAcceptable` for a rule its family does not let an engineer waive (a `warn` rms rule, FR-016; a `warning` standards check, feature 006 FR-041); `409 AlreadyAccepted` when an active exception already covers the condition. Re-renders `report.md`. **One route, both families**: the folder's `check.json` `family` decides which catalogue answers "may this be waived" and which entry point re-renders the folder |
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

The add-in also installs a **same-origin proxy** on every Task Pane page: a call to
`https://swreview.invalid/__backend/<path>` is answered by the add-in's own C# code, which
re-issues it to `http://127.0.0.1:<port>/<path>` (`docs/pane-backend-proxy.md`). A call that
arrives that way carries **no `Origin`** - `BackendProxyHandler` drops the header, because the
page's origin is the virtual host and the origin guard above would refuse the very call the
proxy exists to deliver - and it gets **no `Access-Control-*` header back**, because same
origin has nothing to allow and a stray `Access-Control-Allow-Origin` would re-open the
question the proxy closes.

None of this section is therefore removed. The origin guard, the `OPTIONS` 204 and every
`Access-Control-*` header stay exactly as they are: the `swreview` CLI and any other direct
caller still use them, the pages still reach the backend cross-origin on a workstation whose
web filter leaves loopback alone, and a request with no `Origin` is not a cross-origin request
for the guard to refuse in the first place.

## Reading the event stream

**The host reads this route, not the page.** The add-in reads
`GET /sessions/{chat_id}/events` with `HttpWebRequest` (`Proxy = null`, `Authorization`,
`Accept: text/event-stream`, and `Last-Event-ID` when the page supplied one), splits the
response on blank lines, and posts each raw frame to the page as `events.frame`
(`pane-host-messages.md`). The page asks for the stream with `events.open` and gives it up
with `events.close`; the frame it receives is the one the server wrote, and the page's own
parser reads it.

Two reasons, and either alone would be enough. A Task Pane page is a browser process, and an
endpoint web filter that intercepts browser HTTP to `127.0.0.1` answers the page's `fetch`
with its own interstitial while the backend logs a clean 200 (`docs/pane-backend-proxy.md`);
a request made by the add-in's own code is not intercepted. And this route is the one that
cannot be handed to WebView2's `WebResourceRequested` either — a response there must have all
of its content available when the deferral completes — so there is no proxy that could serve
it.

`EventSource` is still not an option anywhere: it can set neither `Authorization` nor
`Last-Event-ID`. Putting the token in the URL remains forbidden (it would land in access
logs, WebView2 history and crash dumps), which is why it travels as a header - on the
host's own request for this route, and in the page's `Authorization` header for the routes
the page still calls itself. `init` carries the token to the page for those
(`pane-host-messages.md`); what moving the stream into the host bought is that the stream's
token is no longer one of them.

## Shutdown and settings changes

A running turn owns process state that is not on disk, so:

- `settings.save` in the pane MUST NOT restart the backend while a turn is running; the host
  refuses with `error {error_class: "TurnRunning"}` and the page offers Save again when the
  turn ends (`pane-host-messages.md`).
- On any shutdown signal the server finalizes every live chat before exiting: it writes
  `turn.ended {reason: "error"}` when a turn was mid-flight, then `session.ended` with an
  `ended_at`, and saves `session.json`. A session is never left without an ended time
  (FR-008), including the provider-failure path that raises out of the runner.
