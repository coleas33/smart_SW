# Contracts: Resilient Modeling Checks

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| IR 1.1.0 additions (`features`, `equations`, `rms_suppress_test`, `ComponentInstance.constrained_status_raw`, new gap kinds) | feature 001 `contracts/ir.schema.json` (minor bump; `$defs` added: `Feature`, `SketchInfo`, `FilletInfo`, `Equation`, `SuppressTestRun`, `SuppressTestRow`) | C# extractor and `suppress-test` → Python rules and tools |
| Rule catalogue, outcome mapping, group semantics | `rules.md` | Python `checks/rms/` → findings, coverage, docs |
| Type tables | `rms-types.yaml` is the **draft**; T001 moves it to `reviewer/src/swreview/checks/rms_types.yaml`, which is then the single normative file (this directory keeps no copy) | Data → `RmsTypeTable` |
| Exceptions (waivers) | feature 001 `exceptions.json` via `ReviewException.fingerprint_kind`; the checker's flat waiver file is an import input described in `cli.md` | Engineer → `ExceptionStore` → Python rules |
| Tools | `tools.md` | Python tool layer → model; query tools → MCP and the terminal profile |
| Command lines | `cli.md` | Engineer → `swreview check rms`, `swreview rms types`, `swreview exceptions accept-rms`, `swreview-extract dump --features/--equations`, `probe rms`, `suppress-test` |

Versioning: the IR bump is minor (1.0.0 → 1.1.0) because every addition is optional with a
default, so 1.0.0 packages load in 1.1.0 builds. Both serializers forbid unknown members
(`extra="forbid"`, `JsonUnmappedMemberHandling.Disallow`), so a 1.1.0 package is readable
only by 1.1.0 or later builds of the reviewer and the extractor; mixed-version use is refused
with the serializer's message. The schema-sync test and the C# serializer test are updated
together. The review-session schema is unchanged. Feature 001's `contracts/agent-tools.md`
gains six tool rows, and feature 002's `contracts/mcp-toolset.md` and
`contracts/cli-profiles.md` gain the three query tools, each in the task that registers the
tool.
