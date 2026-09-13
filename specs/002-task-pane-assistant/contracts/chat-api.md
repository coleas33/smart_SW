# Chat Backend API

`swreview chat serve --port 0 [--run-root <dir>]` starts a loopback HTTP server. The first
stdout line is `{"port": 51234, "token": "<32 bytes base64url>"}`; nothing else is printed
to stdout. Every request carries `Authorization: Bearer <token>`; a missing or wrong token
returns 401 and is logged without the token. The server binds `127.0.0.1` only.

Provider credentials arrive in the child's environment (`OPENAI_API_KEY`, `GEMINI_API_KEY`,
`OPENAI_BASE_URL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`); the server never reads
the settings file.

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/health` | | `{status: "ok", version, providers: ["openai", "gemini"]}` |
| GET | `/models?provider=openai\|gemini` | | `{models: [{id, label}]}` from the provider; 502 with the provider error class on failure |
| POST | `/sessions` | `{run_dir, provider, model, effort, bridge: {pipe, secret} \| null, engineer}` | `201 {chat_id, review_session_id}`; starts the review turn immediately. 400 if `run_dir/package.json` is missing or invalid. |
| GET | `/sessions/{chat_id}` | | `ChatSession` state without `token` |
| GET | `/sessions/{chat_id}/events` | `Last-Event-ID` header optional | `text/event-stream`; replays from `events.jsonl` after the given id, then live. Event `id` = `seq`, `event` = `type`, `data` = JSON body. |
| POST | `/sessions/{chat_id}/messages` | `{text}` | 202; appends a user turn and runs. 409 if a turn is running. |
| POST | `/sessions/{chat_id}/evidence/{request_id}` | `{answer}` | 202; marks answered, resumes. 404 unknown request; 409 already answered. |
| POST | `/sessions/{chat_id}/findings/{finding_id}/disposition` | `{decision, note, by}` | 200 with the `Finding`; 409 on an illegal transition. Re-renders `report.md`. |
| POST | `/sessions/{chat_id}/stop` | | 202; ends the turn at the next tool boundary and writes `session.ended`. |
| GET | `/sessions/{chat_id}/report` | | `text/markdown` of `report.md` |

Errors: JSON `{error_class, message, retryable}` with the message redacted of any
configured key. 5xx only for server faults; provider failures surface as 502 with the
provider's error class name.

Concurrency: one running turn per chat; the server serializes messages and evidence
answers per chat and refuses with 409 rather than queueing silently.
