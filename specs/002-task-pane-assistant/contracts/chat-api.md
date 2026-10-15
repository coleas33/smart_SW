# Reviewer Backend API

*Feature 015 amendment, 2026-10-12 (T041):* `POST /sessions` accepts the optional boolean
`send_when_checked` (default true); false saves a checks-only review in `awaiting_send`.
Follow-ups before Send are refused with `409 NotSent`. The flow is specified in
[015 review-flow.md](../../015-review-send-gate/contracts/review-flow.md).
The later Send and restoration changes remain specified in
[015 recheck.md](../../015-review-send-gate/contracts/recheck.md).

*Feature 015 amendment, 2026-10-14 (T095):* `POST /sessions` also accepts the optional boolean
`recheck` (default false): the re-run of a waiting review's checks in its own `run_dir`,
which needs `send_when_checked: false` (`400 InvalidRequest` otherwise, as for a non-boolean
value or a `retry_of`). A live chat on the folder in `awaiting_send` is adopted: `201` with
that chat's `{chat_id, review_session_id, not_examined}` and nothing run. A folder being set
up (a re-run still running) or a running chat is `409 RunDirInUse`; with no live chat, a
folder with no readable `session.json` is `404 UnknownReview` and a record with no
`model_status`, or one already sent, is `409 NotWaiting`. The earlier `session.json` and
`attention.json` are copied, not moved, so they stay canonical until the re-run's
finalization replaces them; the answer is an unticked start's `201`. See
[015 recheck.md](../../015-review-send-gate/contracts/recheck.md) sections 2, 6 and 7.

*Feature 015 amendment, 2026-10-14 (T100):* `GET /reviews/{run_id}` restores a record whose
`model_status.state` is `not_sent` or `send_failed` read-only as every record, with its own
`read_only_reason`: the words file's `read_only_lead`, a space, and `send.restored_line` with
`{when}` the stored `checked_at` wall clock (`YYYY-MM-DD HH:MM`, never converted), never
`read_only_off`. Its summary carries the `send` block `{state: "restored", input_tokens: null,
approximate, text: send.restored, failure, rerun_failed_text}`, with no `session_id`. Every other
record keeps the words file's `read_only` sentence and no block. Still writes nothing. See
[015 recheck.md](../../015-review-send-gate/contracts/recheck.md) section 8.

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), landed by 2026-09-27 (013 T054):* the Review tab's Start here is replaced by the grouped findings list (`<section id="findings-by-type">`), so `not_examined`'s headline sits above that list; see 013 `contracts/grouped-list.md` section 5 (lands with 013 T054).

One loopback service, not one per tab: `swreview chat serve` is the **reviewer backend**,
and it serves **checks as well as chats**. A ticked `/sessions` start runs a review turn
through a provider; an unticked start runs the code checks and waits for Send without
building a provider client or requiring a key. The `/checks/*` routes grade a design - against the
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
| GET | `/labels` | | `200` with the `labels` block of `reviewer/src/swreview/report/review_words_v1.yaml`, verbatim (feature 009, `specs/009-engineer-workspace/contracts/plain-words.md` section 1, data-model section 7): `{version, status, severity, bucket, evidence_status, contact_kind, errors}` - the words the Review tab prints for each token, and one next-step sentence per error class. Token required like every route. Reads no session and writes nothing. |
| GET | `/engineering-context/{run_id}` | | 200 saved-evidence operator snapshot, including before initialization; bounded targets, typed inputs, frame/force values, decisions and exact digests. Writes nothing. Feature 016 `contracts/pane-context.md` is normative. |
| POST | `/engineering-context/{run_id}/init` | `{}` | 201 fixed private-store publication; 409 existing/busy context. Constructs no provider. |
| POST | `/engineering-context/{run_id}/requirement` | typed target/text/source/assumptions plus `expected_head` | 200 publication; 400 malformed or unavailable target; 409 stale/busy context. |
| POST | `/engineering-context/{run_id}/force` | typed target/force/unit/direction/frame/point/source/assumptions plus `expected_head` | 200 publication; unknown stays unknown; 400 malformed or unavailable target; 409 stale/busy context. |
| POST | `/engineering-context/{run_id}/confirm` | `{expected_head, record_id, actor, expected_record_digest, expected_dependency_digest}` | 200 publication of exact explicit saved-input receipt; 400 unconfirmable inputs; 409 stale/busy context. |
| POST | `/sessions` | `{run_dir, provider, model, effort, bridge: {pipe, secret} \| null, engineer, retry_of: chat_id \| null, standards_profile: str \| null, send_when_checked?: boolean}` | `201 {chat_id, review_session_id, not_examined}`; starts the review turn immediately when `send_when_checked` is true or absent. False runs the code checks, builds the Send cache, finalizes and renders the record, then registers the chat in `awaiting_send`, without a provider request. A non-boolean value is `400 InvalidRequest` naming `send_when_checked`. `standards_profile` is the configured profile path, passed to the reasoning side to attach `check_standards`; blank or null means no profile. An unreadable or invalid configured profile leaves the review possible and makes the standards family not evaluated, rather than refusing the review. `not_examined` is the shared `{sentence, headline, instances}` block from `report/unexamined.py`, or null when every instance was read; Review displays its `headline` (names, no ids; feature 009 T013) above the grouped findings (`<section id="findings-by-type">`, feature 013 T054; above Start here until then) as soon as the session starts, with the instances' ids in a fold, and falls back to `sentence` from a backend that sends no `headline`. `sentence` keeps the ids and is what `report.md` and both check bodies print. 400 if `run_dir` fails the path rule below or `run_dir/package.json` is missing or invalid. |
| GET | `/sessions/{chat_id}` | | `ChatSession` state without `token` and without `bridge` (neither the HTTP token nor the bridge secret is ever echoed) |
| GET | `/sessions/{chat_id}/events` | `Last-Event-ID` header optional | `text/event-stream`; replays from `events.jsonl` after the given id, then live. Event `id` = `seq`, `event` = `type`, `data` = JSON body. |
| POST | `/sessions/{chat_id}/messages` | `{text}` | 202; appends a user turn and runs, including on a session whose previous turn already ended (`ended → running`, see data-model section 3). 409 if a turn is running; `409 NotSent` while the run waits for Send, without changing the review. |
| POST | `/sessions/{chat_id}/evidence/{request_id}` | `{answer}` | 202; marks answered, resumes. 404 unknown request; 409 already answered. Both refusal bodies carry `request_id` naming the request beside `error_class`, `message` and `retryable` (feature 009 T042), as the batch route's will; no other error body has the key. |
| POST | `/sessions/{chat_id}/evidence` | `{answers: [{request_id, answer}, ...]}` | 202; every named request answered, one `evidence.answered` each in submission order, and the review resumes **once** (feature 008, `specs/008-checks-first-review/contracts/answer-batch.md`, normative). Checked in this order, and a refusal changes nothing: `404 UnknownChat`; `400 InvalidRequest` naming the index or the repeated id when `answers` is not a non-empty list of objects each with a non-empty string `request_id` and a non-empty string `answer`, or names one id twice; `409 TurnRunning` / `SessionFailed`; then every id, `404 UnknownEvidenceRequest` / `409 AlreadyAnswered` naming the first failing id. Some of the open requests may be answered; the rest stay open. The single-answer route above stays and uses the same validator (`runner.answerable`). No new event type. |
| POST | `/sessions/{chat_id}/findings/{finding_id}/disposition` | `{decision, note, by}` | 200 with the `Finding`; 409 on an illegal transition. Re-renders `report.md`. |
| POST | `/sessions/{chat_id}/timing` | `{baseline?, supervision?, verification?, false_alarms?}` - numbers or null; every key optional | 200 with the recomputed `Timing`, net included. Writes the **live** session the run holds and re-renders `report.md` with that run's package, so the values survive the next turn; **emits no event**, because timing is the engineer's bookkeeping and not something the review did. `400 InvalidTiming` naming the key for a key that is not one of the four (including `net_saved_minutes`, which is derived and never accepted), a value that is not a number, or a negative one; `404 UnknownChat`; `409 TurnRunning` / `SessionFailed` as `disposition`. Check runs register no chat, so they are timed from the command line. `specs/007-attention-policy-gate/contracts/timing.md` is normative. |
| POST | `/sessions/{chat_id}/stop` | | 202; ends the turn at the next tool boundary, emits `turn.ended {reason: "stopped"}`, then writes `session.ended`. Idempotent: on a session that already has an `ended_at` it is 202 with the current state and no second terminal event pair. |
| GET | `/sessions/{chat_id}/report` | | `text/markdown` of `report.md` |
| GET | `/sessions/{chat_id}/attention` | | `200` with the `Ranking` of `specs/007-attention-policy-gate/contracts/attention.md` section 4 **minus `session_id`** - the same block the two check results carry in their `attention` key. Computed from the **live** session the run is holding on every call, so a disposition recorded a moment ago is in it; it **writes nothing**, not `report.md` and not `attention.json`, because a page refresh must not refresh the record of the order the engineer was shown. A review that produced no findings answers `200` with `rows: []` and `empty_reason` set rather than an empty list alone, so the Review tab's pinned panel can say there is nothing to start with and why (feature 007 FR-023, FR-024). Since feature 009 (T015) the body is a `ReviewRanking`: that `Ranking` unchanged plus one `summary` key, the Review tab's summary computed from the same live session and the run's package (`specs/009-engineer-workspace/contracts/review-summary.md`); neither check body nor `attention.json` carries it. `404 UnknownChat`. |
| GET | `/sessions/{chat_id}/snapshot` | | `200` with `report/snapshot.review_snapshot` of the run this backend holds (feature 009, `specs/009-engineer-workspace/contracts/sessions.md` section 3, data-model section 8): `{run_id, read_only: false, read_only_reason: null, chat_state, last_seq, document, findings, evidence_requests, coverage, ranking, not_examined}` - the live session's findings and requests in session order as their stream bodies, the coverage flattened bucket by bucket as `coverage` event bodies, the `ReviewRanking` with its summary (resume cost from the run's ledger), the chat's state and the sink's last `seq`. Computes and **writes nothing**. `404 UnknownChat`. |
| GET | `/reviews/{run_id}` | | `200` with the same snapshot read-only from the run folder `run_id` names under the run root (sessions.md section 4): `session.json` and `package.json` loaded, the ranking and summary recomputed in memory with no ledger (`resume_input_tokens: null`), `read_only: true` with the words file's `read_only` sentence (a record that waits for Send: its dated line and `restored` Send block, feature 015 T100), `chat_state` and `last_seq` null. `run_id` goes through the `run_dir` path rule as `check_id` does. `404 UnknownReview`, naming only the id, for a name the rule refuses, a missing folder, a folder with no `session.json`, a check folder (`check.json`), or a file that cannot be read or does not validate. **Writes nothing**: every file under the folder keeps its bytes and modification time. |
| POST | `/checks/rms` | `{run_dir, scope: "part" \| "equations" \| "all", document_id: str \| null, standards_profile?: str \| null}` | `201 CheckResult` (feature 003 `contracts/model-check.md`; with a `standards_profile`, since feature 013 T148, the body also carries `bought_parts`). Runs synchronously: no provider, no network call, no turn, and no chat is registered for the folder. 400 when `run_dir` fails the path rule, when `run_dir/package.json` is missing or invalid (`InvalidPackage`), when the package carries no feature rows (`EmptyFeatureTree`), when the carry-forward candidate cannot be parsed (`UnreadableExceptions`), or when `scope` is `"assembly"` (`ScopeNotAvailable`) |
| POST | `/checks/standards` | `{run_dir, profile_path: str}` | `201 StandardsResult` (feature 006 `contracts/standards-check.md`, the normative source for this row and the two below). Runs synchronously for the same reasons as `/checks/rms`: no provider, no key, no network call, no turn, and no chat is registered for the folder. **There is no `scope`**: every standards check runs on every run, the document kinds decide which apply, and a body carrying one is refused rather than quietly answered. 400 when `run_dir` fails the path rule, when `run_dir/package.json` is missing or invalid (`InvalidPackage`), when the package does not record the phases the standards checks read (`MissingStandardsPhases`), when the root document has no recorded kind or no path (`UngradableRoot`), when `profile_path` is absent, unreadable or not configured (`ProfileUnreadable`), when the profile parses and fails its schema (`ProfileInvalid`), or when the carry-forward candidate cannot be parsed (`UnreadableExceptions`) |
| GET | `/checks/{check_id}` | | `200` re-read from that check run folder - the recorded `session.json` and `check.json`, with nothing evaluated and nothing written, so a refresh cannot overwrite a recorded disposition; `404 UnknownCheck` when the run root holds no such folder, no check ran in it, or its session is no longer the one its record names. The answer is **the record's own family shape**: a `CheckResult` for a folder whose `check.json` carries `family: "rms"` or no `family` at all, a `StandardsResult` for `family: "standards"`. Neither family ever answers for the other: the route answers in the record's own family shape, and a page reads back only the ids its own evaluation route produced - handed the other family's shape it renders nothing it cannot read |
| POST | `/checks/{check_id}/exceptions/{finding_id}` | `{note, by}` | `200 {finding, exception_id}` with the finding re-rendered as checked within scope; `400 EmptyNote` on a blank note; `404 UnknownCheck` / `UnknownFinding`; `409 RuleNotAcceptable` for a rule its family does not let an engineer waive (a `warn` rms rule, FR-016; a `warning` standards check, feature 006 FR-041); `409 AlreadyAccepted` when an active exception already covers the condition. Re-renders `report.md`. **One route, both families**: the folder's `check.json` `family` decides which catalogue answers "may this be waived" and which entry point re-renders the folder |
| OPTIONS | any path | | 204 preflight, **answered without a token** (see Origin and CORS) |

Errors: JSON `{error_class, message, retryable}` with the message redacted of any
configured key. 5xx only for server faults; provider failures surface as 502 with the
provider's error class name.

Concurrency: one running turn per chat; the server serializes messages and evidence
answers per chat and refuses with 409 rather than queueing silently.

One chat owns each run folder. Before setup's first await, both ticked and unticked starts
reserve its resolved path: an overlapping start on the same folder is `409 RunDirInUse`
before another setup or provider build, while another folder may start independently.
The pending reservation is released on failure and after registration; an unfinished
registered chat, including `awaiting_send`, continues to hold the folder. A failed start
registers no chat, and existing on-disk Retry rules still apply to any files it left.
An unticked start is registered only after its cache, finalization and render finish, so
shutdown cannot finalize that unregistered run concurrently. Stop and graceful shutdown
write nothing for a finalized waiting review; its state remains `awaiting_send`.

Since Feature 016, `POST /sessions` optionally accepts
`engineering_context: {context_id, head_digest, package_sha256}`. Omission preserves
the existing session/tool behavior; null, partial or stale attachments are refused
before provider construction. Context is loaded only from the run's fixed private
store after the exact baseline matches. A startup reservation prevents concurrent
context edits and clears on setup failure.
*Amended 2026-10-15 (feature 016 on feature 015, owner decision 99A):* the attachment works with
`send_when_checked` either way; unticked, no provider is built and Send's first request carries the
context. A review started unticked with it records it in `model_status.engineering_context`, and its
`recheck: true` re-run reloads and validates that attachment (a changed head is `409
EngineeringContextConflict`, nothing moved); `recheck: true` with an `engineering_context` member is
`400 InvalidRequest`. The startup reservation is the one "folder being set up" registry
above, `_pending_run_dirs`, held from the claim in every mode (ticked, unticked and re-run, the
record read included); the attachment is read again on the thread pool, and saved context cannot
be edited while a chat on the folder is set up, extracting, running, waiting for the engineer or
`awaiting_send`. The [pane context contract](../../016-engineering-context/contracts/pane-context.md)
defines the entry bodies, projections, privacy limits and saved-snapshot scope.

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
  turn ends (`pane-host-messages.md`). A review at `awaiting_send` has no running turn, so
  Save is accepted there. A failed settings write is `SettingNotSaved`, with the stored
  settings unchanged. The Review box saves its setting without a restart or turn check.
- On any shutdown signal the server finalizes every live chat before exiting: it writes
  `turn.ended {reason: "error"}` when a turn was mid-flight, then `session.ended` with an
  `ended_at`, and saves `session.json`. A session is never left without an ended time
  (FR-008), including the provider-failure path that raises out of the runner.


## Feature 015 Send route (T061/T064, 2026-10-12)

`POST /sessions/{chat_id}/send` accepts an empty body (other keys ignored) and returns 202
with the running chat view. It refuses, in order: UnknownChat (404), SessionFailed,
TurnRunning, NotWaiting, NoCredential (each 409). The last checks the existing settings
resolver's usable credential, including scripted and Gemini enterprise configurations.
Refusals change nothing. Validation, awaiting_send -> running, the in-flight flag and worker
submission have no intervening await on the event loop. The adapter factory and Send execute
on that chat's single worker, so another Send or answer encounters running. The first usage
marks the persisted review sent; a Stop during a successful held build reaches the ordinary
tool-boundary stop. Preparation guards and first-request rollback are specified by feature015
`contracts/review-flow.md` section 6 and implemented by T066; they are not a new refusal after 202.


Feature 015 T066 completes the Send guard: the rollback model-status snapshot is taken before
the factory; pre-request failure restores it in memory without saving, clears the in-flight
marker before its error, and returns to awaiting_send. A first request failure before any usage
replaces this attempt's Interrupted entry with its redacted failure, empties history and restores
the DeferredProvider before the error/turn-ended/finalization sequence. Existing earlier failure
history remains. A completed round retains today's fatal-error behavior. Settling awaiting_send
releases the retained bridge transport; the worker finally clears Stop after success or failure.


Feature 015 T068 serializes a waiting review's disposition/timing write on the same one-thread
executor its Send and answers use. The route awaits the write while leaving awaiting_send and
Stop untouched; a subsequently accepted Send or answer queues behind it. A failed write answers
its existing error and does not cancel queued work. Other chat states retain run_in_threadpool.
