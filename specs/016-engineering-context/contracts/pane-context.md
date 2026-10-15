# Pane context entry contract

Feature 016 extends the existing Review page, host protocol and authenticated backend.
The shared token, origin, error and run-root rules in Feature 002 apply unchanged.

## Preparation and selection

`context.prepare {}` asks the host to extract evidence without starting a review or
constructing a provider. The reply is `context.prepared {run_id, package_sha256,
document}`. The host retains the directory, exact package digest and root document /
configuration. Another preparation, ordinary review or active-document notification
invalidates it. The host rechecks the document after extraction.

`context.selection {run_id, package_sha256}` asks for exactly one selected component
or face against that prepared package. `context.selected` returns an observation ID,
package ID/digest, root identity/configuration, nullable target IDs/label, dirty-state
observations and reason codes. Its status is `matched_saved_target` or `unresolved`.
Every response has `native_calibrated: false`, `native_model_state:
selection_observation_only` and `freshness: cannot_establish`. It carries no source
paths or native reference bytes. A unique native comparison can prefill a saved target;
it never confirms an input or certifies current geometry.

Relevant native identity candidates are bounded at 256. Exhausting the budget, missing
references or an indeterminate native comparison refuses the selection rather than
accepting a partial search. Native saved-package reads are capped at 64 MiB, and
ancestry walks are bounded at 64; exceeding either bound remains unresolved.
Dirty/unreliable/changed sources, missing package faces,
unsupported/multiple selections and ambiguous occurrences remain unresolved.

## Backend routes

The route accepts a single run-folder name under the configured run root. Paths, links,
device names and answer-key locations are refused. The private store is fixed at
`run_root/.engineering-context/<run_id>`, outside extracted evidence and CAD sources.
No request may choose a store directory or CAD path.

| Method | Path | Body | Success |
|---|---|---|---|
| GET | `/engineering-context/{run_id}` | none | 200 operator snapshot, even before initialization; writes nothing |
| POST | `/engineering-context/{run_id}/init` | `{}` | 201 publication; refuses an existing head |
| POST | `/engineering-context/{run_id}/requirement` | record input plus `text` | 200 publication |
| POST | `/engineering-context/{run_id}/force` | record input plus force fields | 200 publication |
| POST | `/engineering-context/{run_id}/confirm` | `expected_head, record_id, actor, expected_record_digest, expected_dependency_digest` | 200 publication |

Record input is `expected_head, record_id, kind, entity_id, component_id?`, with
`provenance_kind: engineer | ai_proposal` (default engineer) and `assumptions: []`.
Requirements accept document, component or face targets. Total forces accept component
or face targets only, with `magnitude: number | null`, `unit: N | kN | lbf`,
`direction: [x,y,z] | null`, `unknown_reason: text | null`,
`frame_component_id: id | null` and `point_m: [x,y,z] | null`. A null frame component
selects the saved root coordinate frame. Blank/unknown magnitude requires a reason;
it does not become zero. Directions normalize separately from magnitude. Translations
apply only to the optional point, once, in metres. Extra/malformed fields are refused.

Publication is `{context_id, revision, head_digest, run_id, package_sha256}`.
The snapshot also carries `initialized`, `scope: saved_snapshot`,
`native_model_state: not_observed`, bounded `targets` (500) and `targets_omitted`.
Each record includes its typed engineering values, target/occurrence/configuration,
frame transform and source kind; exact record/dependency digests; decision; binding;
saved-snapshot freshness; and resolved force where available. Private paths, native
references, provenance source strings and actor history are omitted. Human inspection
is distinct from the existing smaller model-tool projection.

Stale heads, source-package changes, existing initialization, store contention and
entry during a pending/running review return 409. Invalid inputs return 400; unknown
run names return 404. Error text excludes rejected private input. Context edits use
the existing immutable history, lock, CAS and receipt validators. Changing a record
invalidates its previous confirmation; an exact explicit receipt confirms saved inputs.

## Explicit review attachment

`context.review {run_id, context_id, head_digest, package_sha256}` uses the host's
same prepared package, without another extraction. Success consumes the prepared
state and returns the existing `review.started` reply. The backend receives:

```json
{"engineering_context":{"context_id":"<uuid>","head_digest":"<sha256>","package_sha256":"<sha256>"}}
```

This optional member is added to `POST /sessions`. When absent, the existing session
wire format and model tool surface remain unchanged. When supplied, all three values,
the fixed private store and the complete saved baseline must match before provider
construction. Null or incomplete attachments are refused. A startup reservation blocks
context mutations until the review is registered, and is cleared on setup failure.

The review receives an immutable typed artifact and the existing bounded read-only
context tools. Draft/unknown inputs retain their recorded states. This flow does not
require or manufacture confirmations, perform structural analysis or authorize CAD
changes. Native freshness and approval carry-forward remain workstation gates.

Existing checks-first live reads can append interference evidence to the package.
The opening summary and its saved artifact must therefore be reassessed after pre-run
checks. A changed baseline retains the historical confirmation and marks its binding /
applicability as needing review; it never silently carries approval to the new evidence.

## On feature 015's send gate (owner decision 99A, 2026-10-15)

016 was written before 015's send gate and started reviews on its own path. The T116
integration review of 015 found three blockers and a should-fix for whichever landed
second; 016 lands second and adapts here.

**The start goes through the gate.** `context.review` starts through the host's one
`CreateReviewSession`, the path `review.start` takes, with `ReviewMode.Send` when "Send to
the model when the checks finish" is ticked and `ReviewMode.Wait` when it is not; the
attachment is threaded into `NewSessionRequest` by name. An unticked context review runs
the checks with nothing sent, and its record, chip, ready status and `review.started`
reply (`send_when_checked: false`) are those of any unticked review. The page refuses
every context control - prepare, selection, save, new input, confirm and review - while
a review starts, runs a turn, waits for Send, has its Send accepted or is checked again
(`startPending`, `turnRunning`, `awaitingSend`, `sendPending`, `rechecking`), and the
context start meets the same guard ordinary Review has.

