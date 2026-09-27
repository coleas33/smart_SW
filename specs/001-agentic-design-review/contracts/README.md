# Contracts: SOLIDWORKS Agentic Design Review Pilot

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), pending implementation:* `review-session.schema.json` gains optional `allow_text` and `source` on `EvidenceRequest`, `source` on `Finding` and `CoverageItem`, and `drawing_read` on the session, each omitted at its default; see 013 `contracts/sources.md` and `data-model.md` section 3.

These are the interfaces the feature exposes between its own layers and to the engineer.
Field-level rules live in [data-model.md](../data-model.md); this directory pins the wire
shapes.

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| Evidence package (IR) | `ir.schema.json` | C# extractor, PDF parser → Python checks, agent tools |
| Review session and findings | `review-session.schema.json` | Python reviewer → report renderer, disposition CLI, scorecard |
| Scorecard | `scorecard.schema.json` | Benchmark runner → engineer |
| Curated agent tools | `agent-tools.md` | Python tool layer → the provider adapters (one canonical schema per tool from `agent/providers/schema.py`, in the OpenAI strict and Gemini forms) |
| Command lines | `cli.md` | Engineer → `swreview` (Python) and `SwReview.Extractor.Console` (C#) |

Versioning: `ir.schema.json` carries `schema_version` semver. Minor bumps add optional
fields only. A major bump requires a migration note in `research.md` and updated golden
fixtures. Review-session and scorecard schemas are versioned with the Python package.

*Amended 2026-09-26 by feature 013 (T071; 013 research R2.21):* the manifest gaps. The native
extractor no longer writes, per document, a `manifest` gap for a vault version no custom property
carries, nor the `unsupported` `manifest` gap for the local-modification state: this build reads no
vault, so `ManifestEntry.vault_version` (with no vault property) and `local_modified` are null for
every document by construction, and the review states that once, in the `provenance` row code writes
at setup (013 `contracts/re-ask-guard.md` section 2), instead of two gaps per document. A missing
revision is still a `manifest` gap, and so is a file stat that could not be read. `ir.schema.json`
is unchanged; packages dumped from now on carry two fewer gaps per document, which moves the
carry-over key's gap digest once (carried findings do not carry for one run) and lowers the pane's
gap count.
