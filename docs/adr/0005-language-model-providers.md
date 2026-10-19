# ADR 0005: OpenAI is the provider in use; Gemini work is deferred; never Claude in the product

**Status:** Accepted
**Date:** 2026-10-15 (owner decision 94A), building on the provider rule of 2026-09-13
**Deciders:** the project owner

## Context

Feature 001 first planned the review loop on the Anthropic SDK. On 2026-09-13 the build was
retargeted: "This build targets OpenAI and Google Gemini only; no Anthropic path exists in
deployed code" (001 `research.md` R2, amended 2026-09-13). Feature 002 built the provider layer,
OpenAI by default and Gemini beside it, and made "no Claude or Anthropic path" a requirement.
On 2026-10-15, while feature 014's slice 6 was being drafted, the owner said: "We are only using
openAI api key".

## Decision

- The product's review loop runs on OpenAI or Gemini through one provider interface; no other
  model provider is used in product code, and the Anthropic SDK is not a dependency (002 FR-009).
  No Claude or Anthropic path exists in product code, configuration or documentation (002
  FR-026). Any future evaluation judge is OpenAI or Gemini, never Claude (014 decision 1A).
- OpenAI is the provider in use. Decision 94A chose to "build OpenAI's behaviour and the shared
  pieces; give Gemini only the structural changes the shared code needs; defer Gemini's specific
  behaviour". The deferred items are listed in 014 `research.md` 94A (Gemini's served model and
  stop reason mapping, its input-token-limit pattern, its retry mapping and a Gemini price entry).

The Gemini adapter stays in the code (`reviewer/src/swreview/agent/providers/gemini_provider.py`)
and `--provider gemini` still exists; 94A defers further Gemini-specific work, it does not
remove the adapter. `DEFAULT_PROVIDER` is OpenAI (`reviewer/src/swreview/agent/settings.py`).

## Consequences

- Live and paid runs (014's paid tasks, the `-m live` tests) use an OpenAI key.
- Gemini-specific tasks elsewhere stay open or deferred: 002 T055a and T063 (the Gemini terminal),
  005's Gemini probes and lever-3 Gemini tasks, 008 T106; see the [specs index](../../specs/README.md).
- Contributor tooling (`AGENTS.md`, `CLAUDE.md`) may use any assistant; the rule above is about the
  product.

## Sources

- [`specs/014-design-review-eval/research.md`](../../specs/014-design-review-eval/research.md),
  "94A. OpenAI only (2026-10-15)" and "1A. Providers (2026-09-28)".
- [`specs/002-task-pane-assistant/spec.md`](../../specs/002-task-pane-assistant/spec.md),
  FR-009 and FR-026.
- [`specs/001-agentic-design-review/research.md`](../../specs/001-agentic-design-review/research.md),
  R2, "Amended 2026-09-13".
- [`NOTICE.md`](../../NOTICE.md), "Python runtime dependencies"; [`reviewer/README.md`](../../reviewer/README.md),
  "Providers and keys".
