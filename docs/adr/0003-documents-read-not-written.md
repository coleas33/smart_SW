# ADR-003: SOLIDWORKS documents are read, never written, behind a guard

**Status:** Accepted
**Date:** 2026-09-16
**Deciders:** the project owner (constitution amendment 1.1.0)

## Context

The reviewer, its checks, the tools exposed to the model and the add-in's commands all run
against documents an engineer has open in SOLIDWORKS. A write - a save, a rebuild, a suppression,
a new feature - could change an engineer's design without their knowledge. Until 2026-09-16 the
read-only rule was implicit in Principle II and enforced only in each plan's Constitution Check.

## Decision

Every document SOLIDWORKS has open is treated as read-only by the reviewer, every check, every
tool exposed to a model and every add-in command. `ReadOnlyGuard` is the enforcement point, and
its denylist grows the moment a phase touches an API family that can write. There are exactly two
bounded exceptions, the suppressibility test (feature 003) and the re-modeler's own copy (feature
004, [ADR-004](0004-remodeler-works-on-a-copy.md)); a third requires an amendment to the
constitution.

The constitution's section "Documents are read, not written" is the authoritative text.

## Consequences

- The guard lives in `extractor/SwReview.Extractor/Guard/` (`ReadOnlyGuard.cs` and its partial
  files); later features only narrow it. For example, owner decisions 17A and 21A of 2026-09-25
  added the FeatureWorks, import-repair and feature-creation families to its denials
  ([decision log](../decisions.md)).
- Drawings are read only: feature 011 reads drawings already open, and its one confirmed open is
  read-only and switched off until seat probes pass (`specs/011-drawing-context/`).
- Drawing creation (reserved feature 012) needs a constitution amendment before it is specified
  ([ADR-001](0001-agentic-review-architecture.md), "Amendment 2026-09-22").

## Sources

- [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md), Technical
  Constraints, "Documents are read, not written", and the Sync Impact Report (1.0.0 to 1.1.0).
- [`AGENTS.md`](../../AGENTS.md), "Rules that are never bent", rule 1.
- [`specs/004-resilient-remodeler/contracts/guard-allowlist.md`](../../specs/004-resilient-remodeler/contracts/guard-allowlist.md),
  "Denials added after stage 1".
