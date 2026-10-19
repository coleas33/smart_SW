# Architecture decision records

Architecture decision records, numbered, never edited after acceptance except to mark them
superseded. Owner decisions are numbered entries such as `112A`, indexed with where each is recorded in
[`docs/decisions.md`](../decisions.md).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-agentic-review-architecture.md) | Where the SolidWorks reviewer and drawing automation should live (ADR-001) | Accepted in part (layers 1 and 2, and layer 3's read-only stage; drawing creation open) |
| [0002](0002-deterministic-numerics.md) | Numbers come from tested code; the model never computes a verdict | Accepted, 2026-09-12 |
| [0003](0003-documents-read-not-written.md) | SOLIDWORKS documents are read, never written, behind a guard | Accepted, 2026-09-16 |
| [0004](0004-remodeler-works-on-a-copy.md) | The re-modeler works on a copy it created, and on nothing else | Accepted, 2026-09-16 |
| [0005](0005-language-model-providers.md) | OpenAI is the provider in use; Gemini work is deferred; never Claude in the product | Accepted, 2026-10-15 |
| [0006](0006-checks-first-and-token-budget.md) | Checks first, and the token budget | Accepted, 2026-09-22 |
| [0007](0007-send-gate-default-on.md) | The send-to-model gate, ticked by default | Accepted, 2026-10-08 |
| [0008](0008-public-upstream-private-fork.md) | Public upstream, private downstream fork | Accepted, 2026-10-18 |
