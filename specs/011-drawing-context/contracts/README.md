# Contracts: Drawing Context, Read Only

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| The attach: `AttachForDump`, the purpose-aware refusal, a drawing session with no configuration, the console's refusal to open a drawing | `attach.md` | `Sw/SwSession.cs` → every extraction path; the tool service, terminal and bridge unchanged |
| The guard: the 28 drawing families, the writer grammar, the named shared members, the exclusions, the generated table and its two tests | `guard.md` | `Guard/ReadOnlyGuard.cs`, `extractor/tools/list-writer-members.ps1` → every drawing read, feature 012's future allowlist |
| Open drawings and candidates: discovery, matching, order, the ten-drawing bound, candidates, the gaps, profiles, the reuse key | `open-drawings.md` | `Dump/OpenDrawingDiscovery.cs`, `Dump/PackageWriter.cs` → `drawing_records[]`, `documents[]`, the manifest, `drawing_candidates[]` |
| Native evidence at IR 1.6.0: every new read, its interop member, its field and the gap it writes when it fails | `native-evidence.md` | `Dump/DrawingDumper.cs`, `Dump/SwDrawingReader.cs` → `package.json` |
| The drawing source: the native conversion, the binding rule, the resolver's drawing answer, the precision to the general tolerance, the existing tools on native sheets | `drawing-source.md` | `drawings/native.py`, `drawings/binding.py`, `checks/tolerances.py`, `tools/refs.py`, `tools/query.py` → feature 010's stack-up, `check_fit`, `check_axial_stack`, the model |
| The drawing check and its questions: the drawing family, when it is offered and planned, the coverage, the two questions, the payload, the digest line, the re-call guard | `questions.md` | `checks/drawing_context.py`, `tools/drawings.py`, `prerun.py` → the pre-run, `session.json`, feature 009's panel, feature 008's answer batch |
| The brief: sections, sources, bounds, refusals, the tool and the command | `brief.md` | `drawings/brief.py`, `tools/drawings.py`, `cli.py` → the model, the engineer, feature 012 |
| Profile version 3 and conformance: the `drawing` section, the loader, the comparison, `drawing_profile.conformance` | `profile.md` | `checks/standards/profile.py`, `checks/drawing_context.py` → the review's findings, the brief |
| Fixtures: the three synthetic packages, their case table, the generator, the denylist test | `fixtures.md` | `tests/support/drawings.py`, `tests/fixtures/drawings/` → every acceptance test here |
| The read-only open of a confirmed candidate (owner, 2026-09-23): the backend's trigger, the `drawing.read` bridge command, the guarded seam and its allowlist, the close rule, the switch | `confirmed-open.md` | `agent/runner.py`, `tools/drawings.py`, `Bridge/BridgeDispatcher.cs`, `Guard/DrawingOpenGuard.cs`, `Sw/DrawingOpenScope.cs`, the add-in's tool service → the run's `package.json`, `drawing.confirmed_open` coverage |
| Seat probes: `swreview-extract probe drawings`, D1 to D14, what each prints and records | `probes.md` | `SwReview.Extractor.Console/Program.cs` → `research.md` R4, the seat tasks |

## Versioning

The evidence schema goes to **1.6.0** with optional members only, each omitted when null or empty,
so a 1.5.0 package loads and serializes to its own bytes. The standards profile gains **version 3**
and the loader still reads 1 and 2. The attention policy stays `attention_policy_v1`: one row is
added and none is changed. The brief carries `brief_version: 1`. The review-session contract does
not change.

## What this feature does *not* move

- **Every tool's signature and docstring**, `TOOL_FUNCTIONS`, every existing pin of
  `test_tool_payload.py`, feature 005's `levers.md` figures, the MCP function list and the terminal
  profile. The drawing family is offered only with drawing evidence, and its arm is pinned
  separately (`questions.md` section 7).
- **`Finding`, `CoverageItem`, `EvidenceRequest`, `InvestigationStep`, `chat-events.schema.json`.**
- **Feature 006's sixteen checks, its traversal and its verdict**, and the Standards and model
  check extractions' contents for a part or assembly root.
- **Feature 010's joint map, its checks, its goldens and its fixtures.**
- **A replay of every recorded review**: no recorded package carries drawing evidence.
- **Every golden of `report/markdown.render_report`.**

## Where these contracts land in other features' packages

Feature 001's `contracts/agent-tools.md` gains the drawing family's two rows and `contracts/cli.md`
the `swreview drawing brief` row; its `ir.schema.json` is regenerated at 1.6.0; the bridge's
`PROTOCOL.md` (both ends) goes to 1.3 with `drawing.read`. Feature 002's secret scopes gain
`drawing.read` in the review scope only. Feature 004's `contracts/guard-allowlist.md` gains the
generated "Feature 011" table and the confirmed drawing's allowlist entry. Feature 006's `spec.md`
FR-025 and `contracts/ir-additions.md` section 7 record the review extraction's amendment (T001);
its `contracts/profile.md` carries the version 3 block and `research.md` R5 one row per new field.
Feature 007's `contracts/attention.md` notes the one new class. Feature 008's
`contracts/checks-first.md` section 5 gains the `(tool,)` key for `check_drawings`. Feature 010's
`contracts/tolerances.md` section 6 records the slot's new return (T002).
