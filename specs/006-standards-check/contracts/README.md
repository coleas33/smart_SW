# Contracts: Standards Check

| Contract | File | Producer → Consumer |
|----------|------|---------------------|
| IR 1.4.0 additions (`cut_list_items`, `drawings`, the new fields on existing models, `DrawingSheet.source`, the new gap kinds, the `cutlist` and `drawing` phases, the widened `extractor.profile` enum) - **`ir-additions.md` section 1 states the field count; nothing else repeats it** | `ir-additions.md`, and feature 001's `contracts/ir.schema.json` (minor bump; nine `$defs` added: `CutListItem`, `DrawingRecord`, `DrawingSheetRecord`, `DrawingView`, `DisplayDimensionRecord`, `DrawingAnnotation`, `DrawingNote`, `RevisionTable`, `RevisionTableRow` - eight drawing models and one cut-list model) | C# extractor → Python checks, tools and the tab |
| Check catalogue, conditions, severities, skips and unresolved conditions | `rules.md` | Python `checks/standards/` → findings, coverage, the verdict, docs |
| The standards profile: YAML schema, placeholder example, validation rules | `profile.md`, and `config/standards.example.yaml` (placeholders only) | Owner → `checks/standards/profile.py` → the checks |
| Standards routes, page and host messages, check run folder, verdict rendering, Accept semantics | `standards-check.md` | Standards page and `StandardsHost` → `chat/server.py` and `checks/standards/run.py` |
| Command lines | `cli.md` | Engineer → `swreview check standards`, `swreview exceptions accept-standards`, `swreview-extract dump --profile standards`, `probe standards` |
| Exceptions (waivers) | feature 001's `exceptions.json` via `ReviewException.document_id` (additive) and `fingerprint_kind: "standards"`; the flat waiver file is an import input described in `cli.md` | Engineer → `ExceptionStore` → Python checks |

## Versioning

The IR bump is **minor, 1.3.0 → 1.4.0**, because every addition is optional, carries a
default and is omitted when null (arrays: when empty), so a 1.3.0 package loads in a 1.4.0
build. Both serializers forbid unknown members (`extra="forbid"`,
`JsonUnmappedMemberHandling.Disallow`), so a 1.4.0 package is readable only by 1.4.0 or later
builds of the reviewer and the extractor; mixed-version use is refused with the serializer's
own message. The schema-sync test and the C# serializer test are updated together. The
review-session schema (`Finding`, `CoverageItem`) is **unchanged**.

The one visible change to an existing package shape is `extractor.phases`, which gains two
rows (`cutlist`, `drawing`), `skipped` for any profile that does not run them. Golden fixture
files on disk are static and stay byte-identical; the tests that pin the **full phase list**
are edited in the task that adds the phases, and that edit is named there rather than
discovered.

## What this feature does *not* move

- **The feature 001 finding contract.** Subjects ride in `Finding.inputs` and, structured,
  **beside** the finding in the route's response - never inside it.
- **The MCP function list and the terminal profile's `enabled_tools`.** The standards family
  registers exactly one review-only check tool so the shared run skeleton can dispatch through
  the tool registry with a session sink (FR-035); it is not exposed by MCP, and the existing
  tests that pin those lists pass **unedited**.
- **Any existing tab.** Standards is the sixth, beside Review, Ask, Extract, Model check and
  Remodel, and none of them is removed, hidden or reordered.
- **`PaneActions`, `web/shared/dom.js`, `SwEntityResolver`, `FeatureSelection`,
  `report/session.py`, `tools/context.py`.** Reused unchanged; the `PaneActions` tests are
  extended to parameterize over the third host rather than copied.
- **`tools/registry.py` is not in that list.** It is the only place a tool group is registered,
  so it gains one registration function, `standards_tools()`, **outside** `REGISTRATIONS` and
  offered by `ToolRegistry._offered` only when the context carries a standards run - exactly as
  `remodel_tools()` is offered only when the context carries a remodel plan. That is what keeps
  the separate, and correct, claim above true: `MCP_TOOL_FUNCTIONS` and the terminal profile's
  `enabled_tools` do not move, and their pinning tests pass unedited.
- **The review-session coverage schema.** `report/session.py`'s five buckets (`checked`,
  `skipped`, `unresolved`, `failed`, `out_of_scope`) are unchanged; `warned` is a **rendered**
  bucket derived from findings by `checks/standards/report.py`, never a session bucket.

## Where these contracts land in other features' packages

Feature 002's `contracts/chat-api.md` gains the three route rows and
`contracts/pane-host-messages.md` the tab-6 message rows, each in the task that adds them;
`standards-check.md` is **normative** for both. Feature 003's `contracts/model-check.md`
gains one sentence recording that `check.json` now carries a `family` field defaulting to
`"rms"`. Feature 001's `contracts/agent-tools.md` gains **nothing**: its curated tables are
asserted set-equal to `registry.TOOL_FUNCTIONS`, which is built from `REGISTRATIONS` alone, and
the standards check tool is registered outside `REGISTRATIONS` (above), so a row there would
break `test_provider_schema.py::test_registered_tools_are_exactly_the_contract_tables`. The
single review-only check tool is documented **here, in `standards-check.md`**, exactly as
feature 004 documents its five out-of-`REGISTRATIONS` tools in its own `contracts/tools.md`.
