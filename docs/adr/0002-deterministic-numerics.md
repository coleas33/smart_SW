# ADR 0002: Numbers come from tested code; the model never computes a verdict

**Status:** Accepted
**Date:** 2026-09-12
**Deciders:** the project owner (constitution, ratified 2026-09-12)

## Context

The reviewer asks a language model to investigate a design. Model output is not
reproducible, and a fit, a stack or an interference volume that is slightly wrong looks the
same as one that is right. The findings report is the product, and an engineer must be able to
reproduce every finding in it.

## Decision

Every numerical result - geometry measurement, unit conversion, interference, fit and stack
calculations - comes from checked, tested software functions. The language model may decide what
to investigate, request evidence, interpret results and explain them; it must not perform the
arithmetic that produces a verdict. Every calculation exposes its inputs, units, sign conventions,
assumptions and calculation model. Reasoning runs on an intermediate representation (IR) outside
SOLIDWORKS, so it can be replayed and tested without a CAD seat.

This is Principle II of the constitution, "Deterministic Numerics, Agentic Investigation", and it
is recorded here only so the decision log has one entry for it. The constitution is the
authoritative text.

## Consequences

- Checks live in `reviewer/src/swreview/checks/` and are tested first (constitution Principle
  III); the model reaches them only as curated tools.
- A missing input stays unknown and the check reports `unresolved` rather than a guessed pass
  (Principle I).
- The same rule later moved the argument-free checks out of the model's turns altogether
  ([ADR 0006](0006-checks-first-and-token-budget.md)).
- Generic code-execution tools are not exposed to the model (constitution, Technical
  Constraints).

## Sources

- [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md), Principle II
  "Deterministic Numerics, Agentic Investigation", Principle I, Principle III and "Technical
  Constraints".
- [ADR 0001](0001-agentic-review-architecture.md), "Layer 2: Reasoning and agent".
- [`AGENTS.md`](../../AGENTS.md), "What the project is": "Numbers come from tested code; the model
  never computes a verdict."
