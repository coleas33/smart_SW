# Contracts: Task Pane Assistant

*Feature 015 amendment notice, 2026-10-08:* Planned amendments for `settings.schema.json`, `chat-events.schema.json` are specified in [015 pane.md](../../015-review-send-gate/contracts/pane.md), [015 review-flow.md](../../015-review-send-gate/contracts/review-flow.md).

*Feature 015 US1 event amendment, landed 2026-10-12:* `session.started` accepts the optional
`send_when_checked` field only with value `false`, identifying a checks-only start. Ticked
starts omit it and keep the previous body. Other new fields remain refused by the closed schema.
*Amended 2026-11-02 (feature 015 cycle 12, T122; owner decision 193A, extended to Check
again):* a re-run's `session.started` also accepts `carried_withdrawals`, present only when its
earlier record withdrew findings with a decision: each such `finding.withdrawn` body, `disposition`
and `taken` included, in the order they went, which `report.md` names before the session's own.
Their ids are the earlier record's, so no reader drops a finding for them. And a re-run's carry
writes each undecided earlier finding's last `disposition.cleared` again, onto the one finding with
its subject key, before any decision it carries ([015 `recheck.md`](../../015-review-send-gate/contracts/recheck.md)
section 4, step 8).
*Amended 2026-11-02 (feature 015 cycle 12's Tier 1 review, T123; recorded on its read-only
check):* the carry writes that `disposition.cleared` only onto a finding at the status and
severity of the earlier finding it was written on, where its words, that this verdict changed,
still hold; elsewhere it writes none.
*Amended 2026-11-02 (feature 015 cycle 12's Codex review, T123):* each `carried_withdrawals` item
also names `session_id`, required: the session that withdrew it - the earlier record's for its own
withdrawals, kept as it was for one that record carried itself - since finding ids restart in each
session; `report.md` names it on the item's line.

*Amended 2026-09-29 by feature 014 (`specs/014-design-review-eval/`), in benchmark-run.md sections 6 to 8; the amendment text lands with the 014 task that changes the code:* `chat-events.schema.json` gains optional `served_model`, `stop_reason` and `retries` on the `usage` and `error` bodies.

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), landed 2026-09-27 (013 T038, T108):* `chat-events.schema.json`: `text.done`'s body gains optional `basis`, and a `finding.withdrawn` event is added; see 013 `contracts/sources.md` section 3 and `contracts/part-roles.md` section 9.

*Amended 2026-11-01 (roadmap hole H-d-008; owner decisions 189A and 191A; T327):* `chat-events.schema.json` gains a `disposition.cleared` event, `{finding_id, disposition, reason}`: a check the model ran again after an answer folded onto a decided finding with another status or severity, so the disposition was cleared. The runner writes it after the fold's `finding` event for the same id; `disposition` is the one cleared and `reason` the words file's line naming its decision and triage, which the Review page prints on the finding's card. A re-run with the status and severity decided keeps the disposition and writes no such event ([data-model.md](../data-model.md) section 3, rule 3).

*Amended 2026-11-01 (owner decisions 193A and 194A; T341):* `chat-events.schema.json`: `finding.withdrawn` gains an optional `folded_into`, on the withdrawal of the id a re-run or restated finding was first announced under once it folds onto that id; and `disposition.cleared` is also written by the restate and by a re-run's carry, its `reason` naming which ([data-model.md](../data-model.md) section 3, rule 3).

*Amended 2026-11-01 (the owner's request; cycle 7, T347):* `chat-events.schema.json` gains `$defs/TriageTally` - the flagged findings by outcome and with none, the passes judged wrong, and `report.md`'s By triage and misses lines for them, counted by `report/summary.triage_tally` - and an optional `triage_tally` of that shape on the `disposition` and `disposition.cleared` bodies, present only while some finding records a triage. The review summary and the disposition route's reply carry the same ([chat-api.md](chat-api.md); [data-model.md](../data-model.md) section 2). Each event's tally is the count when it is sent (settled 2026-11-02), so a Check again's carry counts decision by decision.

*Amended 2026-11-02 (roadmap hole H-g-010; cycle 10, T359):* `chat-events.schema.json`: `finding.withdrawn` gains optional `disposition` and `taken`, both or neither, on the withdrawal of a finding that held a decision: the disposition that went with it, and the words file's clause naming the decision and its triage (`withdrawn`), which the Review page's Transcript ends the withdrawal's line with, as sent. A fold's withdrawal and an undecided finding's carry neither. `report.md` names each such withdrawal, and prints an undecided finding's last cleared line, from the stream the session wrote ([spec.md](../spec.md), FR-031). *Amended 2026-11-02 (cycle 10's Tier 2 review):* a withdrawal of a finding the record still holds is not named, because the stream can run ahead of the record.

*Amended 2026-11-02 (the owner's pick of four Review page fixes; cycle 13, T371):* `chat-events.schema.json`: the `finding` body gains an optional `triage_tally` of `$defs/TriageTally`'s shape beside the finding, present only while some finding records a triage - the count once the finding is in the session, or once the fold that announces it is done - so the Review page counts a finding a resumed turn adds as it arrives. The body is closed in the event's branch (`unevaluatedProperties: false` beside its `$ref`), and 001 [review-session.schema.json](../../001-agentic-design-review/contracts/review-session.schema.json)'s `Finding` is closed where it is used rather than where it is defined, so a session's finding still takes no other key ([spec.md](../spec.md), FR-031). *Amended 2026-11-02 (cycle 13's Tier 2 review):* the key is on every `finding` body, null while no finding records a triage, and the Review page changes the tally on a `finding` event only when its body names the key, so an older backend's finding, which names none, leaves the tally as it was (009 FR-030).

*Amended 2026-11-03 (a withdrawal names its finding's title; cycle 16, T383):* `chat-events.schema.json`: `finding.withdrawn` gains an optional `title`, the finding's display title as its `finding` event names it, which the backend names on every withdrawal it writes - an answer's, a decision taken or not, and a fold's, the title of the `finding` event it announces next - and each `carried_withdrawals` item of a re-run's `session.started` keeps it with the body it carries. `report.md`'s withdrawn lines, a read-only restore's lines and the Review page's Transcript name it in parentheses right after the id; an older body, without one, stays valid and is printed as before ([spec.md](../spec.md), FR-031).

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| Chat backend HTTP + SSE | `chat-api.md` | Python `swreview chat serve` → add-in Review page |
| Chat event stream | `chat-events.schema.json` | Runner and tools → `events.jsonl`, SSE, CLI |
| Page ↔ host messages | `pane-host-messages.md` | WebView2 pages ↔ add-in host |
| CLI restriction profiles | `cli-profiles.md` | Add-in `CliProfileWriter` → Codex / Gemini |
| MCP toolset | `mcp-toolset.md` | Python `swreview mcp` → CLI |
| Settings file | `settings.schema.json` | Add-in ↔ per-user settings |
| Tool service protocol | feature 001 `extractor/.../Serve/PROTOCOL.md` v1.0 plus the `secret` field below | Add-in in-process server ↔ Python bridge client and MCP server |

Tool service addition: every request line carries `"secret": "<per-launch>"`; a wrong or
missing secret returns `status: "error"` with `error: "unauthorized"` and is logged (never
with the secret in the log line). The protocol version stays 1.0 because clients that omit
the field simply fail on the in-process host and still work against the console host.

The host issues **two** secrets per launch. The review-session secret accepts
`ping | capture | measure | interference`. The general-chat secret handed to the CLI profile
accepts `ping | capture | measure` only; `interference` with that secret returns
`status: "error"`, `error: "unauthorized"`. A single shared secret would authenticate without bounding what it authorizes, and the CLI
can read its own generated profile, so scoping is what makes the read-only subset promised by
FR-022 an enforced boundary at the dispatcher rather than an MCP-allowlist convention.

Transport access control: the in-process pipe is created with an explicit `PipeSecurity`
granting `ReadWrite` to the current user's SID and nothing to anyone else. .NET Framework
4.8 has no `PipeOptions.CurrentUserOnly`, and a named pipe created with the default security
descriptor is readable by any local process, so the GUID in the pipe name is not an access
control.

Path arguments: every path a caller supplies (`run_dir` in `chat-api.md`, any path reaching
a host-side `ShellExecute`) is canonicalized and must resolve to a descendant of the
configured `run_root` (or the log folder); UNC and device paths are refused.

*Feature 015 T064 landed 2026-10-12:* `chat-events.schema.json` includes the additive
`session.sent` event body `{provider, model, effort_mapping, estimate}`. It precedes the
attempt's interrupted pre-write; its live words say Sending, not that a round completed.
The first usage writes the sent model-status record. Ticked reviews emit no new event.
