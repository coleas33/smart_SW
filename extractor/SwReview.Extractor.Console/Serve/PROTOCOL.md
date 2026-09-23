# Bridge protocol (`swreview-extract serve`)

Protocol version **1.3**. This file is the contract the Python client in
`reviewer/src/swreview/bridge/client.py` (T073) is written against; the agent-facing tool
names and arguments are in
`specs/001-agentic-design-review/contracts/agent-tools.md`.

**1.1 is additive to 1.0** (feature 004, T073). The transport, the request and response
envelopes, the `secret` rules, and the four commands `ping`, `capture`, `measure` and
`interference` are unchanged in shape and in meaning, so a client written against 1.0 works
against a 1.1 host without an edit. 1.1 adds one command family, `remodel.*`, one carve-out
in the `result` field of an error response, and a third secret scope; all three are
described under "The `remodel.*` family" below and specified in
`specs/004-resilient-remodeler/contracts/bridge-remodel.md`.

**1.2 is additive to 1.1** (feature 005, T096). Everything 1.1 speaks is untouched, and 1.2
adds exactly one command, `tessellate`, described under "`tessellate`" below. A client
written against 1.0 or 1.1 works against a 1.2 host without an edit. Feature 005's task list
names this bump "1.1" because it was written before feature 004 landed and took that number;
the rule it states - one additive minor per added command - is what 1.2 obeys.

**1.3 is additive to 1.2** (feature 011, T072). Everything 1.2 speaks is untouched, and 1.3
adds exactly one command, `drawing.read`, described under "`drawing.read`" below. A client
written against 1.0, 1.1 or 1.2 works against a 1.3 host without an edit.

`ping` reports the host's own `SwBridgeDispatcher.ProtocolVersion`, which is what a client
compares against.

**Two hosts speak it** (T045). The command handling — `SwBridgeDispatcher`,
`BridgeProtocol`, `BridgeServices` and the command result types — lives in
`extractor/SwReview.Extractor/Bridge/`, so both share one implementation:

| Host | Transport | Secret |
|------|-----------|--------|
| `swreview-extract serve --pipe <name>` | `PipeServer` (this folder): a named pipe and one STA worker thread | None. `NoSecretPolicy` ignores the `secret` field. |
| The SOLIDWORKS add-in's in-process tool service | a named pipe read on a background thread, marshalled onto the application thread | Required on every line. `ScopedSecretPolicy` with two per-launch secrets. |

## Transport

- A **named pipe**: `\\.\pipe\<name>`, where `<name>` comes from `serve --pipe <name>`.
- **One JSON object per line**, UTF-8, no BOM, `\n` as the line terminator. A response is a
  single line, never pretty-printed.
- Requests are answered **in arrival order, one at a time**. A single STA worker thread owns
  the `SldWorks` pointer (research R3), so a capture can never change the selection
  underneath a measure.
- One client at a time. The server keeps serving after a client disconnects, so the reviewer
  can be restarted without restarting SOLIDWORKS.
- Blank lines are ignored.

## Request

```json
{"id": "<string>", "command": "ping|capture|measure|interference|tessellate|drawing.read", "params": {}, "secret": null}
```

| Field | Type | Rules |
|-------|------|-------|
| `id` | string | Required, non-empty. Echoed on the response so a client can match them up. |
| `command` | string | Required. One of the five below, or one of the twelve `remodel.*` commands of `specs/004-resilient-remodeler/contracts/bridge-remodel.md`. |
| `params` | object | Command arguments. May be omitted for `ping`. |
| `secret` | string or null | Optional on the wire. Ignored by the console host; **required** by the in-process host, where it also selects the command scope (below). |

Unknown **top-level** fields are rejected (the same `additionalProperties: false` stance as
the IR schema). Unknown fields inside `params` are ignored.

Every request passes the read-only guard by command name before anything runs, and every
SOLIDWORKS call underneath goes through `SwGate`, which asks the guard again. A command
named after a mutating API (`Save3`, `FeatureCut4`, …) is refused with `status: "error"`.

### `secret` and the two scopes

The protocol version stays **1.0** because the field is additive: a client that omits it
still works against the console host, and one that sends it is accepted by both.

The in-process host issues **two** secrets per launch and the secret on the line decides
what that line may ask for:

| Secret | Held by | Authorizes |
|--------|---------|------------|
| review | the add-in's own review session | `ping`, `capture`, `measure`, `interference`, `tessellate`, `drawing.read` |
| general-chat | the CLI, through its generated restriction profile | `ping`, `capture`, `measure` |

`interference`, `tessellate` or `drawing.read` with the general-chat secret is answered:

```json
{"id":"4","status":"error","result":null,"error":"unauthorized","elapsed_ms":0}
```

That is the **same** answer a wrong secret, a missing secret, and a command outside the
vocabulary get, so a caller learns nothing from the difference. The check runs before the
command is looked up and before the read-only guard, so a refused request never reaches
SOLIDWORKS. The refusal is logged by the host with the command name and never with the
secret, and no response ever carries a `secret` field.

Why the scope is enforced here and not only by the MCP allowlist: the CLI can read the
profile that lists its own tools, so leaving `interference` out of that list withholds
nothing on its own. A single shared secret would authenticate without bounding what it
authorizes. The dispatcher is where the read-only subset promised by FR-022 becomes a
boundary (`specs/002-task-pane-assistant/contracts/README.md`).

## Response

```json
{"id": "<string>", "status": "ok|error|circuit_open", "result": {} , "error": null, "elapsed_ms": 0}
```

| Field | Type | Rules |
|-------|------|-------|
| `id` | string | The request's `id`. Empty when the line could not be parsed at all. |
| `status` | string | `ok`, `error`, or `circuit_open`. |
| `result` | object or null | The command's answer. Null on `circuit_open`; on `error` it is null except where noted (`capture` returns its `Gap`; every `remodel.*` command returns `{"error_code": "<stable token>", "detail": {}}`). |
| `error` | string or null | A sentence an engineer can read. Null when `status` is `ok`. |
| `elapsed_ms` | integer | Wall-clock milliseconds the worker spent on the command. |

`circuit_open` means SOLIDWORKS failed three times in a row and the circuit breaker
(research R4) has stopped further calls. The client must **not** retry, and must record
failed coverage rather than a passing check.

Enum values and property names inside `result` are exactly the ones `package.json` uses:
an `Interference` that travels over the bridge is byte-identical to one written by `dump`.

## `ping`

```json
{"id": "1", "command": "ping"}
```

```json
{"id":"1","status":"ok","result":{"pong":true,"protocol":"1.3","sw_version":"32.5.0","document":"C:\\work\\bracket-assy.SLDASM","configuration":"Default","component_count":17},"error":null,"elapsed_ms":1}
```

`document` and `component_count` are how a client checks that the component ids in its
`package.json` mean the same thing here: they only do while this is the assembly that was
dumped, in the same configuration.

## `capture` — `bridge_capture(persist_ref, view)`

```json
{"id": "2", "command": "capture", "params": {"persist_ref": "<base64>", "view": "iso", "scope_document": null, "note": ""}}
```

| Param | Type | Rules |
|-------|------|-------|
| `persist_ref` | string | Required. Base64 persistent reference of the entity to frame. |
| `view` | string | `iso`, `front`, `top`, `right`, `fit`. Default `fit`. |
| `scope_document` | string or null | Full path of the document whose extension produced the reference. Null means the attached document. |
| `note` | string | Free text recorded on the `Capture` row. |

```json
{"id":"2","status":"ok","result":{"capture":{"id":"cap:0001","persist_ref":"<base64>","component_ids":["cmp:0007"],"file":"captures/cap-0001.png","view":"iso","note":""},"path":"C:\\work\\pkg\\captures\\cap-0001.png","gap":null},"error":null,"elapsed_ms":812}
```

- `capture` is the IR `Capture` row to append to `package.json`'s `captures`.
- `file` is package-relative and forward-slashed; `path` is absolute, so the client can copy
  the PNG into its own package directory.
- The directory is chosen by the host (`serve --out <dir>`, else a temp directory under
  `%TEMP%\swreview-bridge\<pipe>`). A client never names a path: a filesystem path in a
  request would be a write the agent controls (research R4).

On failure the response is `status: "error"`, and `result` still carries the `Gap` so the
client can record unresolved coverage rather than silently losing the request:

```json
{"id":"2","status":"error","result":{"capture":null,"path":null,"gap":{"kind":"not_extracted","entity_kind":"capture","entity_id":null,"reason":"select the entity to capture (iso view)","error":"The reference did not resolve: deleted: the entity no longer exists."}},"error":"select the entity to capture (iso view) - The reference did not resolve: deleted: the entity no longer exists.","elapsed_ms":40}
```

## `measure` — `bridge_measure(persist_ref_a, persist_ref_b)`

```json
{"id": "3", "command": "measure", "params": {"persist_ref_a": "<base64>", "persist_ref_b": "<base64>", "scope_document_a": null, "scope_document_b": null}}
```

| Param | Type | Rules |
|-------|------|-------|
| `persist_ref_a`, `persist_ref_b` | string | Required. The two entities to measure between. |
| `scope_document_a`, `scope_document_b` | string or null | The document each reference is scoped to. Null means the attached document. |

```json
{"id":"3","status":"ok","result":{"distance":{"value":0.0123,"unit":"m"},"delta_x":{"value":0.0123,"unit":"m"},"delta_y":{"value":0.0,"unit":"m"},"delta_z":{"value":0.0,"unit":"m"}},"error":null,"elapsed_ms":220}
```

Lengths are **meters** — `IMeasure` answers in system units and nothing here rounds or
reformats them. A pairing the Measure tool has no answer for is an error with a sentence,
never a number:

```json
{"id":"3","status":"error","result":null,"error":"SOLIDWORKS could not measure between these two entities. The Measure tool has no answer for this pairing; pick faces, edges or vertices.","elapsed_ms":95}
```

## `interference` — `bridge_interference(component_ids, configuration, settings)`

```json
{"id": "4", "command": "interference", "params": {"component_ids": ["cmp:0001", "cmp:0011"], "configuration": "Default", "settings": {"treat_coincident_as_interference": false, "treat_subassemblies_as_components": true, "include_multibody": false, "ignore_hidden": true, "fastener_folder_treatment": "include"}, "truncate_after": null}}
```

| Param | Type | Rules |
|-------|------|-------|
| `component_ids` | array of string | Empty or absent: the whole assembly. Exactly two: that pair. More than two: every unordered pair among them. One id alone is an error. An id this document does not have is refused by name, never dropped. |
| `configuration` | string or null | Echoed into every row. Null means the attached document's active configuration. |
| `settings` | object or null | Any subset of the five fields below; the rest keep their defaults. |
| `truncate_after` | integer or null | Test hook: stop computing after this many rows and mark the rest `truncated`. |

`settings` mirrors `Interference.settings` in the IR:

| Field | Type | Default | Maps to |
|-------|------|---------|---------|
| `treat_coincident_as_interference` | boolean | `false` | `IInterferenceDetectionMgr.TreatCoincidenceAsInterference` |
| `treat_subassemblies_as_components` | boolean | `false` | `TreatSubAssembliesAsComponents` |
| `include_multibody` | boolean | `false` | `IncludeMultibodyPartInterferences` |
| `ignore_hidden` | boolean | `false` | `IgnoreHiddenBodies` |
| `fastener_folder_treatment` | `include` \| `exclude` \| `only` | `include` | Not a manager property: `CreateFastenersFolder` is always on, and results are filtered by `IInterference.IsFastener`. |

```json
{"id":"4","status":"ok","result":{"interferences":[{"id":"int:0001","configuration":"Default","component_ids":["cmp:0001","cmp:0011"],"volume":{"value":3.2e-9,"unit":"m3"},"settings":{"treat_coincident_as_interference":false,"treat_subassemblies_as_components":true,"include_multibody":false,"ignore_hidden":true,"fastener_folder_treatment":"include"},"is_fastener":true,"is_possible":false,"status":"computed","error":null,"group_key":"cmp:0001|pat:screws"}],"gaps":[{"kind":"unsupported","entity_kind":"interference_volume_unit","entity_id":null,"reason":"IInterference.Volume unit assumed m3; verify on workstation","error":null}]},"error":null,"elapsed_ms":3100}
```

- `status: "ok"` at the envelope level means the run happened. **Each row carries its own
  `status`**: `computed`, `truncated`, or `failed`. A `truncated` or `failed` row is
  unresolved coverage, never a pass.
- `gaps` are IR `Gap` objects to append to `package.json`'s `gaps`. Until the workstation
  check in T069 confirms the unit of `IInterference.Volume`, every run that recorded a
  volume carries the `interference_volume_unit` gap shown above, and the volumes are
  labelled `m3` on that assumption.
- `group_key` is each member's pattern id where it has one and its component id otherwise,
  sorted ordinally and joined with `|`. Rows that share a key collapse into one finding
  (FR-011).

## `tessellate` — lever 10a's mesh fetch (1.2)

```json
{"id": "5", "command": "tessellate", "params": {"component_id": "cmp:0007"}}
```

| Param | Type | Rules |
|-------|------|-------|
| `component_id` | string | Required. The package id of the component to tessellate. An id this document does not have is refused by name, never answered with no bodies. |

```json
{"id":"5","status":"ok","result":{"bodies":[{"id":"bod:0001","persist_ref":"<base64>","persist_ref_scope":"doc:2","component_id":"cmp:0007","mesh_file":"meshes/cmp-0007-bod-0001.glb","triangle_count":8412,"is_solid":true}],"paths":["C:\work\pkg\meshes\cmp-0007-bod-0001.glb"],"gaps":[]},"error":null,"elapsed_ms":2400}
```

- `bodies` are IR `BodyRef` rows to append to `package.json`'s `bodies`, and `paths` holds
  each row's absolute path in the same order. As with `capture`, `mesh_file` is
  package-relative and forward-slashed while `path` is absolute.
- **The directory is chosen by the host**, the same `serve --out <dir>` captures go under,
  with the meshes written to `meshes/` inside it. A client never names a path: a filesystem
  path in a request would be a write the agent controls (research R4), so a `params` field
  naming one is ignored like any other unknown field.
- **The same tessellation the dump uses.** The host exports through `MeshExporter.ExportBody`
  rather than a second tessellator, at the same chord tolerance, so a clearance answer never
  depends on how the mesh arrived (FR-090).
- **A component that produced no body is `gaps`, not an empty answer.** `gaps` are IR `Gap`
  objects to append to `package.json`'s `gaps`, and the reviewer turns "no body came back"
  into unresolved coverage naming the component. An empty `bodies` with nothing said would
  read as a component with nothing in the way, which is a clear nothing established.
- **Review scope only.** A mesh fetch writes a file and can take seconds, so the general-chat
  secret is refused with the same indistinguishable `unauthorized` as anything else out of
  scope.
- **One STA worker answers in arrival order**, so a tessellation blocks every other bridge
  call behind it. `elapsed_ms` is how long it did.
- The read-only guard passes it unchanged: `ReadOnlyGuard` is a denylist, and
  `GetTessellation`, `Tessellate`, `CurveChordTolerance` and `GetBodies2` are not on it.

## `drawing.read` — the confirmed candidate's read-only open (1.3)

Feature 011, the owner's answer of 2026-09-23 (`specs/011-drawing-context/contracts/confirmed-open.md`
section 2). When the engineer confirms the candidate question of a review, the backend asks, once
per candidate, for one document's same-name drawing to be read into that review's package.

```json
{"id": "7", "command": "drawing.read", "params": {"run_id": "<run folder name>", "document_id": "doc:0007"}}
```

| Param | Type | Rules |
|-------|------|-------|
| `run_id` | string | Required. The review's run folder's own name; the host resolves it through its own session records and never reads it as a path. |
| `document_id` | string | Required. A part or assembly of that review's package with a `drawing_candidates[]` row. |

**Any other parameter is refused before anything runs** - a path above all: the host resolves
the run folder, the package and the drawing's file from its own records, so a caller can never
name what SOLIDWORKS opens. (Unlike every other command, an unknown `params` member here is an
error, not ignored.)

```json
{"id":"7","status":"ok","result":{"document_id":"doc:0007","drawing_document_id":"doc:0012","opened":true,"closed":true,"sheets":2,"gaps":1},"error":null,"elapsed_ms":3100}
```

- The host refuses, with a sentence and **nothing opened**, when the run is not one it started,
  its run folder holds no package, the package's root is not the document the bridge is attached
  to, the document is unknown or is a drawing or has no candidate row, the row's path is not the
  drawing beside the document by discovery's rule, the file no longer exists, the drawing is
  already in the package, or the package already holds ten drawings.
- The drawing is opened **read-only and hidden** only when it is not already open - through its
  own allowlisted seam (`ISldWorks.DocumentVisible`, `ISldWorks.OpenDoc6` with type 3 and options
  3, `ISldWorks.CloseDoc`; `specs/004-resilient-remodeler/contracts/guard-allowlist.md`) - read
  with every drawing id continuing the package's, merged into `package.json` in the run folder,
  and closed again only when the host opened it and SOLIDWORKS still answers its path with the
  same document. A drawing the engineer had open is read as it stands and left open
  (`opened: false`, `closed: false`).
- **Shipped off** until probe D14 passes at a seat: a closed candidate is answered "the read-only
  open of a confirmed drawing is not yet validated on a seat (feature 011 probe D14)", and an
  already-open one is still read.
- **Review scope only.** The general-chat and remodel secrets are answered `unauthorized`.
- **The console host has no source** and answers that this bridge cannot read a drawing: only
  the add-in's review host keeps the review records the command resolves against.

## The `remodel.*` family (1.1)

Twelve commands — `remodel.probe_scope`, `open`, `snapshot`, `rename`, `reorder`, `folder`,
`describe`, `equation`, `rebuild`, `geometry`, `save`, `close` — whose request and response
shapes, sequences and error codes are **`specs/004-resilient-remodeler/contracts/bridge-remodel.md`**
and are not restated here. What belongs to this file is what they change about the protocol,
and it is three things:

1. **`result` on an error carries a token.** A `remodel.*` failure answers
   `result: {"error_code": "<stable token>", "detail": {}}` so a client maps a refusal to a
   class without matching on prose; `error` still carries the sentence an engineer reads.
   `detail` is always an object, `{}` when there is nothing to add, never null. This is the
   same "except where noted" allowance 1.0 already grants `capture`, and it applies to no
   other command.
2. **A third secret scope.** `ScopedSecretPolicy` gains `remodel`, minted per launch by
   `ToolServiceHost` and handed only to the remodel backend session:

   | Secret | Authorizes | Refused |
   |--------|------------|---------|
   | review | `ping`, `capture`, `measure`, `interference`, `tessellate`, `drawing.read` | every `remodel.*` |
   | general-chat | `ping`, `capture`, `measure` | every `remodel.*`, `tessellate` and `drawing.read` |
   | remodel | `ping`, `remodel.*` | everything else, `interference` and `drawing.read` included |

   The refusal is the same `error: "unauthorized"` line as every other scope failure, so a
   caller still learns nothing from the difference.
3. **No `remodel.*` command that writes names a document.** Exactly two name a path at all,
   `remodel.probe_scope` and `remodel.open`, and both run before a document handle to the
   copy exists; every command after `remodel.open` addresses the tree by persistent
   reference and reaches the one document the run's scope holds. The Python end of this
   family is `reviewer/src/swreview/bridge/remodel_client.py`, whose own command allowlist
   is `ping` plus these twelve — `COMMANDS` in `client.py` is unchanged.

These commands are refused by the read-only guard, as a mutating command must be: they run
under the document-scoped allowlist guard of
`specs/004-resilient-remodeler/contracts/guard-allowlist.md`, on a copy the run created, and
on no other document.

## Errors that are not command failures

| Situation | Response |
|-----------|----------|
| Line is not JSON, or has no `id`/`command` | `{"id":"","status":"error","error":"<what was wrong>","result":null,"elapsed_ms":0}` |
| Unknown `command` | `status: "error"`, listing the commands the host speaks — but `error: "unauthorized"` on a host that requires a secret, which refuses an out-of-vocabulary command before looking it up. |
| Wrong, missing, or out-of-scope `secret` | `status: "error"`, `error: "unauthorized"`, `result: null`. Only on a host that requires a secret. |
| Missing or wrong-typed `params` field | `status: "error"` naming the field. |
| Three consecutive SOLIDWORKS failures | `status: "circuit_open"` on this and every later request until the server is restarted. |
