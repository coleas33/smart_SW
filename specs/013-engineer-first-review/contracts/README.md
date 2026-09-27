# Contracts: Engineer-First Review

Normative interfaces of feature 013. Each contract names the requirements it serves; `tasks.md`
names the contract every task implements. Every example value is fictional (`FICT-`), and no
contract carries a company value (FR-055).

| Contract | What it fixes | Serves |
|---|---|---|
| [part-roles-profile.md](part-roles-profile.md) | Standards profile version 4: the `part_roles` section, its field rules, the name-pattern vocabulary, the upgrade helper | FR-001 to FR-004 |
| [part-roles.md](part-roles.md) | The classifier: states, the decision table, reasons, the API, the consumers, the one question, answers and the regrade, the bought-parts line | FR-005 to FR-014 |
| [grouped-list.md](grouped-list.md) | The grouped findings view: the groups and their words, the partition and order rules, the summary block, the pane section, the report's index, and `top_n` | FR-015 to FR-023 |
| [re-ask-guard.md](re-ask-guard.md) | Code-owned checklist items and `closed_by_code`; provenance closed at setup; the re-ask guard; the ids `request_evidence` accepts | FR-024 to FR-032, FR-045 (the mechanism) |
| [drawing-capability.md](drawing-capability.md) | The ping capability, drawing states, the instruction line, one read per file, code-answered drawing requests, refusal outcomes | FR-033 to FR-040 |
| [sources.md](sources.md) | Source tokens and labels, the answer basis, the explanation pass | FR-041 to FR-044 |
| [tokens.md](tokens.md) | The close-out closed by code, `open_items`, lever 14, and the replay gate | FR-045 to FR-048 |
| [readings.md](readings.md) | The sheet's own view, the honest revision check, the shared tree reading, the deterministic probe 1 watchdog | FR-049 to FR-052 |

## Contracts of other features this feature amends

Each carries a one-line note dated 2026-09-26 pointing here; the full text of each amendment lands
with the task that changes the code (`tasks.md`, "Amends").

| Feature | Contract |
|---|---|
| 001 | `contracts/README.md` (for `review-session.schema.json`), `contracts/agent-tools.md` |
| 002 | `contracts/README.md` (for `chat-events.schema.json`) |
| 003 | `contracts/rules.md`, `contracts/tools.md` |
| 005 | `contracts/levers.md` |
| 006 | `contracts/profile.md`, `contracts/rules.md`, `contracts/ir-additions.md` |
| 007 | `contracts/attention.md` |
| 008 | `contracts/checks-first.md`, `contracts/answer-batch.md`, `contracts/model-view.md`, `contracts/replay.md` |
| 009 | `contracts/questions.md`, `contracts/review-summary.md`, `contracts/views.md`, `contracts/plain-words.md` |
| 010 | `contracts/hygiene.md`, `contracts/code-first.md` |
| 011 | `contracts/questions.md`, `contracts/confirmed-open.md`, `contracts/brief.md`, `contracts/native-evidence.md` |

Feature 004 is not amended (its remodeler items are out of this package); feature 012 is reserved
for drawing creation.
