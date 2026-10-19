# ADR-007: The send-to-model gate, ticked by default

**Status:** Accepted
**Date:** 2026-10-08 (owner decisions 59A to 62A)
**Deciders:** the project owner

## Context

Before feature 015, pressing Review ran extraction, part roles and the checks-first pre-run, then
submitted the model's first request before the pane heard that the review had started; Stop could
not prevent that request, and with no key stored the review failed before any check ran (015
`spec.md`, "Input"). The owner's request of 2026-10-08: "I want the option to not send the review
to llm after clicking review."

## Decision

- **59A**: one checkbox, "Send to the model when the checks finish", ticked by default, "so
  today's behaviour is unchanged". Unticked, Review runs the code checks only and stops, and the
  Review tab shows a **Send to model** button with the estimated size of the first request in
  tokens. "Never pressing Send means nothing about this review reaches the model." A checks-only
  review works with no API key stored.
- **60A**: the checkbox sits on the Review tab beside the Review button, not in Settings, and is
  remembered across sessions.
- **61A**: Send resumes the same paused review; answers and decisions made while it waited are
  kept.
- **62A**: delivered as feature 015, test-first, with one licensed-seat check (a `[W]` task).

## Consequences

- The default keeps the earlier behaviour; nothing reaches a provider from an unticked review
  until Send (015 FR-006).
- The plan review added decisions 68A to 80A (restart, re-run and carry rules), and later reviews
  87A to 90A, 93A and 98A to 100A; see the [decision log](../decisions.md).
- Feature 016's engineering context goes through the same gate (owner decision 99A).
- The seat check, 015 T119, is still open.

## Sources

- [`specs/015-review-send-gate/spec.md`](../../specs/015-review-send-gate/spec.md), "Owner
  decisions (2026-10-08)", FR-001 and FR-006.
- [`specs/015-review-send-gate/research.md`](../../specs/015-review-send-gate/research.md), R7
  and R8.
- [`specs/016-engineering-context/contracts/pane-context.md`](../../specs/016-engineering-context/contracts/pane-context.md),
  "On feature 015's send gate (owner decision 99A, 2026-10-15)".
