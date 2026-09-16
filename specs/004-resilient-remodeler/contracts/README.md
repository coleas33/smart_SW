# Contracts: Resilient Re-modeler

| Contract | File | Producer to consumer |
|----------|------|----------------------|
| The `remodel.*` bridge commands, their request and response shapes, and their error classes | `bridge-remodel.md` | Python `bridge/remodel_client.py` to C# `BridgeDispatcher` and `RemodelScope` |
| The model-facing tools (`propose_description`, `propose_global`, `decide_fillet`, `classify_unknown`, `get_remodel_plan`), their validation rules, and the condition under which they are registered at all | `tools.md` | Python tool layer to the model; never to MCP and never to the terminal profile |
| Page to host and host to page messages for tab 5 | `pane-remodel-messages.md` | `RemodelPage` to `RemodelHost`; mirrors feature 002 `contracts/pane-host-messages.md` |
| Every file in the run folder, its schema reference, and the `changes.jsonl` line format | `run-artifacts.md` | The run to the engineer, the pane, the CLI and a later replay |
| The stage-1 interface-qualified allowlist, the explicit not-allowlisted list, `AssertSaveTarget`, `AssertFolderSelection`, and `VerifyTarget` | `guard-allowlist.md` | `RemodelGuard` and `RemodelScope` to every write call site |
| The frozen interop-surface manifest and its two tests | `interop-manifest.md` | The installed SOLIDWORKS interop assembly to the build |

Consumed unchanged from feature 003 and not restated here: `DumpProfile.ModelCheck` and the
part-root node in `ComponentTreeDumper`; `checks/rms/run.py::run_rms_check`;
`checks/rms/grade.py::RmsGrade`; `AddIn/Review/PaneActions.cs`;
`AddIn/Review/FeatureSelection.cs`; `AddIn/web/shared/dom.js`; `checks/rms_types.yaml` (this
feature adds exactly one key, `default_group_by_class`, to the same file, so the checker and the
planner cannot disagree about what "should" means).

Consumed unchanged from features 001 and 002: `contracts/ir.schema.json` at 1.2.0 (read only;
004 adds no IR field, and **dimensions are not in the IR in v1**), the bridge envelope in
`extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md`, `ExceptionStore` and `exceptions.json`,
`RunFolders`, `contracts/chat-events.schema.json` for `events.jsonl`, and the CSP meta tag and
untrusted-text rules in `pane-host-messages.md`.

Versioning: the bridge protocol goes from 1.0 to **1.1**, additively. Existing clients are
unaffected: the four existing commands are untouched, the envelope keeps its shape, and the one
extension (a machine-readable `error_code` inside `result` on an error response) uses the
"except where noted" allowance the 1.0 protocol already grants `capture`. `plan.json` and
`changes.jsonl` carry `plan_schema: "1.0"` and are owned by this feature alone. No feature 001,
002 or 003 golden moves.

**API notation.** Every interop member named in these contracts is marked VERIFIED or
UNVERIFIED. VERIFIED means the member exists with that signature, or the enum constant has that
integer value, on SOLIDWORKS 2024 SP5 interop `32.5.0.48`. It never means the call behaves.
UNVERIFIED means behavior that needs the workstation, and each one names its probe.

**Stage 2 is out of scope for v1.** Where a contract reserves a shape for it (the tri-state
`GateResult`, the `EQUIVALENCE` tolerance profile, the second additive allowlist, the
`remodel.folder` `dissolve` operation), the reservation is named as such and the v1 behavior is
a refusal with a stated error code, never a silent no-op.
