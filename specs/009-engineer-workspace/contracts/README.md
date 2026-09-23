# Contracts: The Engineer's Workspace

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| The summary: groups, goals, words, names, questions, contacts, the resume cost, and the ranking body that carries it | `review-summary.md` | `report/summary.py`, `report/review_words_v1.yaml`, `chat/server.py` → the Review tab's Results |
| Questions for you: the short form on `request_evidence`, the questions panel, one batch through feature 008's route, refusals | `questions.md` | the model → `tools/session.py` → the session → the summary → the page → `POST /sessions/{chat_id}/evidence` (008) |
| Results or Transcript: the two views, what each holds, the status line, pinned answers | `views.md` | the page |
| Sessions: the host's review list, forgetting one, Show by chat, the snapshot and disk routes, choosing and restoring, read-only, the configuration change | `sessions.md` | `ReviewHost`, `PaneActions`, the add-in, `report/snapshot.py`, `chat/server.py` → the page |
| Plain words: `GET /labels`, titles, names, ids into folds, errors, Model check statements, the default-view scan | `plain-words.md` | `report/review_words_v1.yaml`, `tools/recording.py`, `report/unexamined.py`, `chat/server.py` → every tab |

## Versioning

The review-session contract gains `question`, `options` and `blocks` on `$defs.EvidenceRequest`, all
optional, landed in the same change as the model fields; every session written before this feature
validates, loads and renders. The words file carries its own `version` (`review_words_v1`), echoed
on the summary and the labels, so a page or a person can say which words they read. No IR version
moves; no event type is added.

## What this feature does *not* move

- **The ranking.** `report/attention.py`, its keys, its fold and `TOP_N` are untouched; the summary
  reads the ranking and never reorders it. `attention.json` and both check bodies keep their shape
  and bytes (`AttentionRecord.of` copies field by field).
- **A finding's evidence.** `observed`, `component_ids`, inputs, calculations and statuses do not
  change. The title changes (whole first sentence, part names), and only the ten golden baselines
  holding a cut title move, once. *Not landed yet*: T062 is open (`plain-words.md` section 2).
- **`report.md`.** No new section; its goldens hold apart from titles.
- **`chat-events.schema.json`, `ir.schema.json`, `settings.schema.json`, `UserSettings.cs`.**
- **Feature 008's code.** Its batch route is called as specified; this feature adds one field
  (`request_id`) to two error bodies after 008 T085 lands, and never edits `usageLine`'s body
  (008 T094-T095).
- **The check tabs' behaviour** beyond the shared rows: they keep `LatestSession` for Show, their
  subject lists keep ids, the Standards header is unchanged.

## Where these contracts land in other features' packages

Feature 001's `contracts/review-session.schema.json` gains the three `EvidenceRequest` properties;
`contracts/agent-tools.md` records `request_evidence`'s three optional arguments. Feature 002's
`contracts/chat-api.md` gains `GET /sessions/{chat_id}/snapshot`, `GET /reviews/{run_id}`,
`GET /labels`, the `summary` key on the attention row, `not_examined.headline` on the sessions row,
and `request_id` on the two evidence refusals; `contracts/pane-host-messages.md` gains
`sessions.list`, `session.forget`, `entity.show`'s optional `chat_id`, and the configuration case of
`document.changed`. Feature 003's `contracts/model-check.md` records `rule_statements`. Feature 007's
`contracts/attention.md` section 6 records the summary, the modelling-practice group, the shared
row's check id moving to `data-check`, and that the Review tab's panel lives in Results.
