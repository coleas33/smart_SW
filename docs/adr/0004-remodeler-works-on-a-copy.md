# ADR 0004: The re-modeler works on a copy it created, and on nothing else

**Status:** Accepted
**Date:** 2026-09-16
**Deciders:** the project owner (decisions of 2026-09-16; constitution amendment 1.1.0)

## Context

Feature 004 proposes a part that is more resilient under the Resilient Modeling Strategy. That
needs writes to a SOLIDWORKS document, which [ADR 0003](0003-documents-read-not-written.md)
otherwise forbids. The owner's description of 2026-09-16: "The reviewer and the Model check stay
read-only; the re-modeler works on a copy it creates in the run folder and never saves over an
existing file."

## Decision

The re-modeler may create and modify exactly one document, a copy it created during the session,
and no other:

- the copy is made by a filesystem copy that refuses to overwrite, into the run folder, before any
  SOLIDWORKS document handle exists; the engineer's file is never opened for writing, saved,
  renamed or deleted, and its size, last-write time and hash are checked before and after the run;
- only `IModelDoc2.Save3` is permitted, after the geometry comparison passes; `SaveAs3` and any
  write to another document are refused by the guard;
- writes go through a document-scoped guard that allowlists the members the run needs and
  re-verifies the target before each write;
- the model proposes intent into a plan and a deterministic executor applies it;
- the result is a proposal the engineer accepts or discards, never an engineering result.

The constitution's exception 2, "The re-modeler (feature 004)", is the authoritative text.

## Consequences

- `RemodelGuard` (`extractor/SwReview.Extractor/Guard/RemodelGuard.cs`) is the document-scoped
  guard; `ReadOnlyGuard` stays unchanged for everything else.
- Start is switched off in the shipped build until the blocking seat probes pass (004 task T172),
  and the Phase 0 go / no-go is still unsigned (`specs/004-resilient-remodeler/phase0-decision.md`);
  see the [specs index](../../specs/README.md).
- STEP and other imported solids are on the back burner (004 `spec.md`, "Back burner (owner
  decision 2026-09-19)").

## Sources

- [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md), Technical
  Constraints, "Documents are read, not written", exception 2.
- [`specs/004-resilient-remodeler/spec.md`](../../specs/004-resilient-remodeler/spec.md),
  "Input" (the owner decisions of 2026-09-16).
- [`specs/004-resilient-remodeler/tasks.md`](../../specs/004-resilient-remodeler/tasks.md), T172.
