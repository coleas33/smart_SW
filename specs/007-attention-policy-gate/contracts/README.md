# Contracts: Attention Policy and Procedural Gate

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| The attention policy: the nine keys, the consequence classes, the fold rule, the "Start here" section, `attention.json`, the `attention` key on the two check bodies, and `GET /sessions/{chat_id}/attention` | `attention.md` | `report/attention.py` → `report/markdown.py`, the run folder, `chat/server.py`, the three pages |
| Timing: `record_timing_at`, `swreview timing`, `POST /sessions/{chat_id}/timing`, the ledger column | `timing.md` | Engineer → `benchmark/timing.py` → `session.json`, `report.md`, the ledger |
| The procedural gate: lever 11, the brief, the standards half, the checklist item, the number guard, the adoption rule | `gate.md` | `prerun.py`, `agent/settings.py`, `tools/session.py` → the first user message, the ledger |
| Command lines | `cli.md` | Engineer → `swreview timing`, `swreview attention`, `swreview review --standards-profile`, `--lever procedural_gate` |

## Versioning

The policy is versioned by its file (`attention_policy_v1`) and the version travels in every
record and every report footer. A change to a class, to the needs-judgement set or to a key is
a new policy version and a new golden; an old report still says which version ordered it.
The review-session contract gains one optional lever name and no other change; the IR is
untouched.

## What this feature does *not* move

- **`Finding` and `ReviewSession`.** No rank, score, confidence or group is written to either;
  the fold lives in the ranking and the record.
- **`FindingGroup`.** Stays declared and unconstructed; the reason is research R2.2.
- **The report's Findings section and severity order.** Every finding still renders in full
  under its severity; `_SEVERITY_ORDER` does not move.
- **The claim rule and `SESSION_FILES`.** `attention.json` is rotated explicitly, not through
  the tuple that decides whether a folder already holds a review.
- **The MCP function list and the terminal profile.** No tool is registered; the standards
  check tool is offered to a review context exactly as it is offered to a standards run today.
- **`chat-events.schema.json`.** No event type; the gate's calls ride the four events the
  pre-run already emits.
- **Every C# production file and every IR model.**

## Where these contracts land in other features' packages

Feature 002's `contracts/chat-api.md` gains two route rows (`POST /sessions/{chat_id}/timing`,
`GET /sessions/{chat_id}/attention`). Feature 003's `contracts/model-check.md` and feature 006's
`contracts/standards-check.md` each gain the `attention` key in their result block, a bullet
in their "points the shape exists to enforce" list, and `attention.json` in their run-folder
listing; the two blocks are identical, which is stated so no difference row is added to 006's
section-6 table. Feature 001's `contracts/cli.md` gains three rows cross-referencing `cli.md`
here as normative, and its `review-session.schema.json` gains the lever name in `properties`.
Feature 005's `contracts/levers.md` gains a row and `contracts/ab-harness.md` records the
ledger column in sections 5 and 10.8.
