# Contracts: LLM efficiency, speed, and token usage

| Contract | File | Producer to consumer |
|----------|------|----------------------|
| `TokenUsage`, the per-round `usage` event, `SessionUsage` on `session.json`, the one summing rule, and the scorecard fields derived from them | `usage.md` | Both adapters to the event stream, the session, the report and the scorecard |
| Every lever flag: name, default, scope, when it is read, what it touches, how it is measured, and the rule under which it may be adopted; the interaction matrix; the levers deliberately out of scope | `levers.md` | `EfficiencySettings` to the runner, the benchmark, the session record and the ledger |
| The A/B study protocol, what `benchmark run --lever` refuses, what `swreview benchmark compare` validates, and the `ledger.json` and `ledger.md` formats | `ab-harness.md` | Run folders and `scorecard.json` files to the computed decision row the owner signs |
| Which tools sit in which tier, which tiers are decidable before the first turn, and how a withheld tool is reported to the model, the session and the report | `tool-tiers.md` | `ToolRegistry.functions_for` and `ToolDispatch` to the model, the coverage record and the engineer |

## What this feature changes in contracts owned by earlier features

All four edits are **additive** and all four are paid once, in Phase 1, before any lever exists.

| Contract | Owner | Edit | Why existing artifacts stay valid |
|----------|-------|------|-----------------------------------|
| `contracts/chat-events.schema.json` | 002 | One new `type` enum member, `usage`, and one new body definition; one new optional property `usage` on the `session.ended` body | The top-level `type` is a closed enum and **every** body sets `additionalProperties: false` (VERIFIED), so both are deliberate edits rather than accidents. Every existing event type validates unchanged, which is an asserted test |
| `contracts/review-session.schema.json` | 001 | Two new optional properties on the top-level object: `usage` and `efficiency`, **added to `properties` and left out of `required`** | The object is `additionalProperties: false` at the top level, and `provider_info` and `retry_of` already establish this exact pattern. Every feature 001 session loads and validates, which is an asserted test |
| `contracts/scorecard.schema.json` | 001 | New properties on `PackageScore` (`usage`, `round_trips`, `cached_input_share`, `wall_clock_s`, `seconds_to_first_finding`, `coverage_bucket_mix`) and on `Aggregate` (the summed counts, `median_seconds_to_first_finding`, `packages_with_usage`) | This schema uses the **opposite** house style from the session schema: every property is also in `required`, and absence is expressed as a nullable type. The additions follow that style, and a scorecard over a session with no usage produces nulls rather than raising |
| `contracts/ir.schema.json` | 001 | **Tier 3 lever 9 only**: `ManifestEntry.file_modified_utc` and `file_size_bytes`, and a top-level `reuse_key`; a minor bump 1.2.0 to 1.3.0 | Every addition is optional with a default, so 1.2.0 packages load in 1.3.0 builds. Both serializers forbid unknown members, so a 1.3.0 package is readable only by 1.3.0 or later builds; the schema-sync test and the C# serializer test move together |

What holds the **session** schema and `ReviewSession` together is the written-session validation in
`reviewer/tests/unit/test_session.py` (`:244`, `:267`, `:277`, through `session_validator()` at
`:42-49`) and `tests/unit/test_runner_provider.py:773`, against a schema that is
`additionalProperties: false` at the top level: add `usage` or `efficiency` to the model without the
schema edit and those tests go red. **That is the desired behaviour**, not an obstacle.
`reviewer/tests/unit/test_schema_sync.py` is a different test: it compares the **IR** models to
`ir.schema.json` (`:103-112`) and is the one the lever 9 and phase-timing bump regenerates; it
touches the session schema only at `:156-159`, checking that both contract files are valid JSON
Schema.

## What this feature deliberately does not change

- **`GET /sessions/{chat_id}`** (feature 002 `contracts/chat-api.md`). The pane gets usage from
  the event stream and `session.json` is the record; putting it on `ChatSession.public()` would be
  a third copy of the same numbers.
- **`settings.schema.json`** (feature 002). No lever flag becomes a pane checkbox while it is
  being measured. An engineer toggling an experiment flag mid-pilot makes the pilot's own numbers
  unreadable. An adopted lever becomes a default in code.
- **`contracts/agent-tools.md`** (feature 001) and **`contracts/mcp-toolset.md`** and
  **`contracts/cli-profiles.md`** (feature 002). No lever adds a model-facing tool. Lever 4 only
  ever **removes** tools from the wire, and a withheld tool is still in the dispatch.
- **`Guard/ReadOnlyGuard.cs`.** The reviewer stays read-only and the denylist gains no entry,
  including for lever 10a's `tessellate` (see `levers.md`, lever 10a).
- **The feature 001 finding contract.** Lever 11a adds provenance fields to a finding
  (`carried_over_from`, `carried_over_at`, `carry_over_key`) and **does not touch
  `Finding.status`**: a carried `demonstrated` finding is still demonstrated, and overloading
  `status` would break the scorecard's matching rules.

## Versioning

The bridge protocol goes from 1.0 to **1.1**, additively and **only for Tier 3 lever 10a**: one
new command, `tessellate`, added to a vocabulary of exactly four (`ping`, `capture`, `measure`,
`interference`, VERIFIED in `Serve/PROTOCOL.md` and mirrored by `bridge/client.py:348-409`), with
`ping` reporting the version. No existing command moves. The IR bump is Tier 3 lever 9's and is
described above. No feature 001, 002, 003 or 004 golden moves except the session and report
goldens that Phase 1 refreshes deliberately, in the same commit as the schema edit.

## Verification notation

Every claim in these contracts about an SDK field, an SDK behavior or this tree is marked
**VERIFIED** or **UNVERIFIED**.

- **VERIFIED**: read on 2026-09-16 in this tree, or in a package installed under
  `reviewer/.venv/Lib/site-packages` (`openai` 3.13.0, `google-genai` 2.23.0), at the file and
  line cited, or produced by a script run against this tree. It **never** means an API was
  observed behaving that way.
- **UNVERIFIED**: needs a live provider call, a SOLIDWORKS seat or a timed run. Every UNVERIFIED
  claim that gates a decision names its probe (L1 to L5, G1 to G5, P1 to P8).

## The rule these four contracts exist to serve

Instrument first. Then one lever at a time, behind a flag, default off, adopted only on measured
evidence with no quality regression. **Nothing in these contracts proposes turning anything on**,
and a lever that fails its gate keeps its ledger row.
