# Backend Routes: the Remodel tab

The nine loopback routes `AddIn/Remodel/BackendRemodelPipeline.cs` calls, served by
`reviewer/src/swreview/chat/remodel.py` and registered in `chat/server.py::create_app` beside the
Model check routes. Feature 002 `contracts/chat-api.md` applies unchanged and is not restated: the
same `Guard` middleware (origin, preflight, bearer token), the same error body
`{error_class, message, retryable}`, and the same path rule for `run_dir` (`resolve_run_dir`).

**Why these routes exist at all.** Every `remodel.*` bridge call is made from Python, through the
one `bridge/remodel_client.py::RemodelClient` there is, using the `RemodelSecret` the pane holds:
one bridge caller, one error mapping, one place the client's refusals become sentences. What the
add-in does in process - the two `SwReviewDump` ModelCheck dumps and activating the copy in the
seat - it does because the extractor needs the STA thread and the `ISldWorks` the add-in holds.
The division is `wiring-brief.md`'s and nothing here re-decides it.

`create_app` takes `remodel_bridge_factory: Callable[[str, str | None], RemodelClient] | None`,
mirroring `bridge_factory`. Every `bridge` body field is `{pipe, secret}`, exactly as
`POST /sessions` takes it, and **no route ever echoes the secret**: it reaches the client and
nothing else.

## Routes

| Route | Body | Does | Reply |
|---|---|---|---|
| `POST /remodel/probe` | `{source_path, configuration, bridge}` | `client.probe_scope(source_path)`, then the pure gate of `remodel/scope.py` over the signals it read. The verdict is never the bridge's | `200 {probe_id, signals, refusals}`, `refusals` a list of sentences. **An empty `refusals` is the only ok** |
| `POST /remodel/open` | `{run_dir, source_path, configuration, probe_id, bridge}` | `client.open(source_path, copy_path, run_id, probe_id)` with the copy path derived from the run folder; on ok writes `source-attestation.json` and `open.json` | `200 {copy_path, rebuild_error_count, copy_present}` |
| `POST /remodel/plan` | `{run_dir}` | Carries forward `exceptions.json`, then `remodel/runner.py::plan_run` over `package-before.json`, and records the copy's identity on the plan | `200 {plan_summary}`, the per-part row `swreview remodel plan --json` prints |
| `POST /remodel/runs` | `{run_dir, bridge, provider, model, effort}` | Creates a `RemodelJob` and submits `run_remodel` to its worker thread: phases B, C and D, to completion | `201 {job_id, chat_id}` |
| `GET /remodel/runs/{job_id}` | | Reads the job and its run folder; nothing is evaluated | `200 {state, plan_state, changes_total, changes_applied, current, awaiting, error}` |
| `GET /remodel/runs/{job_id}/events` | | `replay_events(<run_dir>/events.jsonl, after)`, with `after` a query parameter | `200 {events, next}` |
| `POST /remodel/runs/{job_id}/package-after` | `{path}` | Hands the run the dump the add-in just wrote, ending the `dump_after` rendezvous | `200 {ok}` |
| `POST /remodel/runs/{job_id}/stop` | `{}` | Sets the run's stop flag. Idempotent | `200 {stopping}` |
| `POST /remodel/close` | `{run_dir, bridge, discard_copy}` | `client.close_document(discard_copy)`. A copy that is not open is a no-op | `200 {closed}` |

Before phase B starts, the worker performs a deterministic run-entry preflight. The plan must
still be `planned`, its scope verdict must be `ok`, and it must carry the attested copy tuple
(`run_id`, `copy_path`, `source`); stage 1 must use the calibrated `IDENTITY` profile. A failed
preflight is reported on the job and leaves the plan, provider, bridge, change log, and
package-after rendezvous untouched. This check remains in `run_remodel` so a caller cannot
bypass it by skipping the pane's start-state checks.

`provider`, `model` and `effort` on `POST /remodel/runs` are optional and are resolved exactly as
`POST /sessions` resolves them (`ProviderSettings.from_env`), so a remodel run and a review run
cannot disagree about what "the default provider" means. **No route constructs a provider.** The
judgement phase is the one construction site (`remodel/runner.py::build_provider`), it is reached
only from `POST /remodel/runs`, and a run whose adapter cannot be built records the absence and
applies the plan anyway (FR-045).

### `POST /remodel/open` and `open.json`

The reply's `rebuild_error_count` is `0` on the ok path by construction: step 11 of
`remodel.open` (`bridge-remodel.md`) rolls to the end, rebuilds, and refuses with
`preexisting_rebuild_errors` on any non-zero count, so an open that answered ok is an open whose
copy rebuilt clean. That refusal is **not** an error body, because the host already has a path for
it and the count is what the engineer needs to read:

| Condition | Reply |
|---|---|
| ok | `200 {copy_path, rebuild_error_count: 0, copy_present: true}` |
| `preexisting_rebuild_errors` | `200 {copy_path, rebuild_error_count: <from the refusal's detail, null when it carries none>, copy_present: false}` - the bridge has already deleted the copy and closed the document |
| any other `error_code` | the error body of the class named in the table below |

On the ok path the route writes two files before it answers, so that `POST /remodel/plan` and
`POST /remodel/runs` can rebuild the runner's inputs **from the folder alone** - which is what
lets the pane answer after a restart and what keeps the pipeline stateless:

- `source-attestation.json`, through `attestation_from_open` and `write_attestation`;
- `open.json`: `{copy_path, rebuild_error_count, document_length_unit, which_configs,
  scope_signals, probe_id, geometry_before, configuration}`. `geometry_before` is the
  `client.geometry()` reply taken at open - the `copy_at_open` reading the geometry gate compares
  against, because the source is never opened for the comparison in any mode (FR-037).
  `scope_signals` are the **copy's**, measured at step 12, which is what the plan records.

### `GET /remodel/runs/{job_id}`

| Field | Value |
|---|---|
| `state` | `running`, `awaiting_package_after`, `finished` or `failed`. The job's, not the plan's |
| `plan_state` | The `RunState` in `plan.json` (data-model.md section 11), or `null` when there is no plan yet. This is what the pipeline maps to the pane's `status` stage |
| `changes_total` | The number of changes in `plan.json` |
| `changes_applied` | How many of the planned changes **landed**: the `applied` records in `changes.jsonl` that are not the `save`. A change that failed or was rolled back did not land and is not counted, and the `save` is not a planned change - its `seq` is the next free one in the log rather than a plan index, so counting it as "all of them" would report a run the engineer stopped after one change as a completed one. `0` when there is no log yet |
| `current` | `{seq, kind, subject_name}` from the last line of `changes.jsonl`, or `null` when there is none **and once that line is the `save`**: the save is the run's own record and names no planned change, so reporting it would name a change nothing attempted |
| `awaiting` | `"package_after"` while the run is blocked on the after-dump, else `null` |
| `error` | The message a failed job died with, else `null`. Redacted like every other body |

A job whose worker thread died is `state: "failed"` carrying that message; the change log and the
plan on disk are untouched, which is what makes a failed run still readable (Principle VI).

### The package-after rendezvous

`run_remodel` takes `dump_after` as a **callable**, because the after-dump is a reading of the
document as the apply phase leaves it and cannot be taken before that phase runs. The dumper is
the add-in, in process, so the job blocks: `RemodelJob.wait_for_package_after()` moves the job to
`awaiting_package_after`, waits on a `threading.Event` with a timeout (600 s, injectable), and
raises `PackageAfterTimeout` on expiry. `run_remodel` reports that exception on the event stream,
records it on the plan as a `PlanCoverage` row and finalizes the run as `failed` **with the change
log intact**: the changes were applied and it is the reading after them that is missing.

`POST /remodel/runs/{job_id}/package-after` refuses any `path` but `<run_dir>/package-after.json`,
compared as resolved paths, and refuses a file that does not load as a ModelCheck package. The
page never supplies a path and neither does the model: the pipeline sends back the exact path the
route already knows, and the check is what keeps a body from naming a dump of something else.

### The engineer stop

`POST /remodel/runs/{job_id}/stop` sets the job's stop event, which `run_remodel` reads through
`stop_requested` and `apply_changes` reads **between** changes. The change in flight finishes, is
inverted if it failed, and the run finalizes as `truncated` (`pane-remodel-messages.md`,
`remodel.stop`). Stop is idempotent: a second press answers `{stopping: true}` and changes
nothing, for the same reason `POST /sessions/{chat_id}/stop` does.

`truncated` is one state reached two ways - the three bounds of `Limits`, and this - so the
state alone does not say which, and `report.md`'s headline names the stop rather than a
limit nobody reached (Principle I; `data-model.md` section 11's "a distinct report
headline"). The reason travels from the apply phase that reached it to the headline that
names it, and `GET /remodel/runs/{job_id}` reports `changes_applied` as what landed, so the
page shows "1 of 3" for a run stopped after one change and never "3 of 3".

## Error classes

Every class below is a `ChatError` subclass, so the door's one exception handler renders it and
its message goes through the same redactor. The first six are the bridge's `error_code` table
(`bridge-remodel.md`) mapped onto the pane's refusal classes of `pane-remodel-messages.md`; a
token with no row maps to `RunFolderFailed` carrying the host's own sentence, because an unknown
refusal is still a refusal and is never guessed into a nearer class.

| `error_class` | Status | Raised when |
|---|---|---|
| `NotAPart` | 400 | `not_a_part`: the source is not an existing `.SLDPRT` |
| `DocumentDirty` | 400 | `source_dirty`: the open source has unsaved changes. This feature never saves the source |
| `ExternalReferences` | 400 | `external_refs`: `ListExternalFileReferencesCount2() != 0` |
| `ScopeRefused` | 400 | `scope_not_probed` or `scope_changed`, with the host's sentence. Also the pure gate's own refusal, which names **every** failing signal |
| `RunFolderFailed` | 400 | `copy_failed`, `copy_exists`, `tag_failed`, every `error_code` this build has no row for, an `ok` reply this build cannot read, and a run folder that could not be prepared - including a carry-forward candidate that exists and will not parse (FR-029) |
| `BridgeUnavailable` | 502 | The circuit is open or the transport failed, so the call was never sent. Retryable |
| `PackageMissing` | 400 | `<run_dir>/package-before.json` is absent: the add-in's ModelCheck dump has not landed |
| `NotModelCheck` | 400 | `package-before.json` is not a ModelCheck dump of exactly one part |
| `RunNotPlanned` | 409 | `POST /remodel/runs` on a folder with no `plan.json`, or whose plan is past `planned` |
| `ResumeRefused` | 409 | The folder already holds a `changes.jsonl`. **A run never auto-resumes** (FR-031) |
| `RunInProgress` | 409 | A live job already holds that run folder. One run per folder. **Checked before `RunNotPlanned` and `ResumeRefused`**, which a live run makes true of its own folder within milliseconds of the `201` - it records `judging` on the plan and opens a change log - so the most specific fact wins and the pane is never told to plan a part a run is writing to |
| `UnknownJob` | 404 | No job of that id on this backend |
| `PackageAfterRefused` | 400 | The posted `path` is not `<run_dir>/package-after.json`, or does not load as a ModelCheck package |

`NoDocument`, `NotAttached`, `DocumentReadOnly`, `RunNotFound` and `CopyDiscarded` are the host's
own refusals (`AddIn/Remodel/RemodelHost.cs`) and are raised before any of these routes is called;
`PreexistingRebuildErrors` is the host's too and is reached from the ok reply above rather than
from an error body. `InvalidRunDir` is `chat-api.md`'s and is unchanged here.

## Tests

- `reviewer/tests/unit/test_chat_remodel_routes.py` drives all nine through Starlette's
  in-process client over `tests/support/remodel_bridge.py::FakeRemodelBridge`, and parses the two
  tables on this page the way `RemodelPageContractTests` parses the pane contract: a route
  documented here and not registered, a route registered and not documented, and an error class on
  either side alone are all failures.
- No provider is constructed on any route but `POST /remodel/runs`, and there only through
  `remodel/runner.py`; the source path is named in no bridge call after `remodel.open`.
