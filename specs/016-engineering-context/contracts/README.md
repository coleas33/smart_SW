# Engineering-context contract 1.0.0

The [pane entry contract](pane-context.md) adds selection observations, private entry
routes and exact explicit session attachments without changing the sidecar schema.

`engineering-context.schema.json` is generated from the strict immutable models in
`swreview.engineering_context.models`. The synchronization test compares it exactly;
the fictional fixture covers requirements and a force in a translated/rotated frame.
JSON Schema describes shape. Python validators additionally enforce timezone awareness,
nonblank text, coherent unknown values, force application/target kind, rigid transforms,
unique IDs and receipt revision references. Store validation enforces the revision chain,
immutable baseline and historical receipts, and confirms representable forces only.

Digests use canonical UTF-8 JSON: sorted keys, compact separators, no NaN, original typed
values/units retained. Record digests cover the input revision, target, frame, provenance
and assumptions. Dependency digests cover the saved baseline, target and force frame.
Context digests include the full artifact and audit metadata; predecessor digests make
the immutable revision chain inspectable. They provide integrity checks within a trusted
local store, not signatures or proof of actor identity.

*Amended 2026-10-15 (owner decision 107A):* `EvidenceBaseline` gains the optional
`without_live_interference_sha256` (see the [pane contract](pane-context.md)), omitted when
absent so earlier contexts keep their bytes and digests; the schema is regenerated with it.
Binding reports `matched_snapshot` for the exact saved package, or for that package as the
review's live interference check rewrote it and nothing else.

State dimensions stay separate: the latest matching input receipt determines
`draft`, `confirmed`, `rejected` or `needs_review`; saved evidence binding determines
`matched_snapshot`, `not_verified`, `unresolved` or `mismatch`. No offline result is
`native_verified`. The CLI separately exposes saved-snapshot freshness and unobserved
native state. Rejected decisions are supported by the library; the initial CLI exposes
confirmation only. Baseline relinking and record deletion are intentionally unsupported.

LLM read projections are version 1, each capped at 6000 UTF-8 bytes with omission counts.
Summary rows are sorted by ID; detailed history is latest recorded first. Unknown force
and unavailable frame values remain null. Canonical force vectors are provided only when
checked resolution succeeds against matching saved evidence. Model tools accept context
and record IDs, never paths, and cannot add, revise or confirm records.
