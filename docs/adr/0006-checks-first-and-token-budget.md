# ADR 0006: Checks first, and the token budget

**Status:** Accepted
**Date:** 2026-09-22
**Deciders:** the project owner

## Context

The pilot workstation's recorded reviews showed where the tokens went. On the big assembly, 90 of
the 99 findings came from checks that take no arguments, and the model drove each of them one
call at a time, reading payloads of up to 205k tokens (008 `spec.md`, User Story 2). The
recorded review sent 12.4M input tokens (008 SC-002). The owner's direction of 2026-09-22:
"Token usage is way too high, we gotta get more efficient."

Until then the rule (feature 005) was that no pane default changes before a held-out design and a
signed-off ledger row.

## Decision

Code runs every check it can enumerate before the model's first turn; the model explains, asks the
engineer and investigates what code cannot scope. Decided on 2026-09-22 and recorded in
`docs/history/roadmap-2026-09-22.md`, "Decisions taken 2026-09-22":

- model-facing payload slimming, checks first, history pruning and parallel tool calls all become
  pane defaults;
- they are gated by an offline replay of the recorded runs (`swreview benchmark replay`), which
  must show the same findings and a token cut on every recorded run, rather than by feature 005's
  A/B ledger. This supersedes, for levers 5 and 6, the rule that the pane default waits for a
  held-out package (`docs/llm-efficiency-options.md`);
- modelling-practice findings appear in Review as one folded group.

The token budget is stated as feature 008's success criteria: under 1.0M input tokens for the
replay of the big assembly with the pane defaults on (SC-002), under 0.3M for the small assembly
(SC-003), and a paid review at most 1.5 times the replay's estimate at the next sitting (SC-010).

## Consequences

- The pane's levers are decided in one place, `pane_efficiency` in
  `reviewer/src/swreview/agent/settings.py`; the command line and `benchmark run` stay all off.
- Later levers became pane defaults on the same replay terms: lever 13 on 2026-09-23 and lever 14
  on 2026-09-27 (`docs/llm-efficiency-options.md`).
- ADR 0001 records the same change to its layer 2 ("Amendment 2026-09-22").
- Feature 014 measures the pane defaults against all levers off with answer keys (014 decision 3A);
  its paid runs are still open.
- SC-010 needs a paid seat sitting; 008's tasks T102 to T104 are still open.

## Sources

- [`specs/008-checks-first-review/spec.md`](../../specs/008-checks-first-review/spec.md),
  "Input", User Story 2, SC-002, SC-003 and SC-010.
- [`docs/history/roadmap-2026-09-22.md`](../history/roadmap-2026-09-22.md), "Decisions taken
  2026-09-22" and "008 Checks-first review and the token budget".
- [`docs/llm-efficiency-options.md`](../llm-efficiency-options.md), "Decision taken 2026-09-22,
  outside the ledger (feature 008)".
- [ADR 0001](0001-agentic-review-architecture.md), "Amendment 2026-09-22: checks first, and drawings
  in two stages".
