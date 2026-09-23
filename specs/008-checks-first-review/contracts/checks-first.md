# Contract: Checks First

Normative for the pre-run under the pane default, live interference and its persistence, the
opening digest, the re-call guard and the folded modelling-practice group (FR-008 to FR-014,
SC-006), and the tools that leave the array once it ran them (FR-030, section 7).

## 1. When it runs

`checks_first(efficiency)` is true when `prerun_checks` (lever 5) or `procedural_gate` (lever 11)
is on. The pane passes `pane_defaults(provider).efficiency` to `start_review`, so every pane
review runs checks first; `start_review`, `swreview review` and `benchmark run` default off, and
`swreview review --lever prerun_checks` or `--pane-defaults` turns it on (`cli.md`). The
`GATED_ALONE` refusals are unchanged (`procedural_gate` with `prerun_checks`, and either with
`coverage_stop`). The pre-run runs inside `start_review`, before the first provider request and
before `POST /sessions` returns 201, through the same `ToolDispatch` the model uses: every call is
a real `InvestigationStep` with `tool.started`/`tool.finished`, its findings and its coverage.

## 2. What it runs, in order

| # | Call | When |
|---|---|---|
| 1 | `bridge_interference(component_ids=[], configuration=<active>, settings=PRERUN_INTERFERENCE_SETTINGS)` | `context.bridge` is set, the root is an assembly and the package has at least two components |
| 2 | `check_rms_part()`, `check_rms_equations()`, `check_rms_assembly()` | always, unless withheld (lever 4) |
| 3 | `check_interference_group(group_key=K)`, once per distinct group key | for every group `groups_of` enumerates, the live rows included |
| 4 | `check_standards()` | when a standards run is attached (a profile named and usable) |

`PRERUN_INTERFERENCE_SETTINGS`:

```json
{"treat_coincident_as_interference": true, "treat_subassemblies_as_components": true,
 "include_multibody": true, "ignore_hidden": false, "fastener_folder_treatment": "include"}
```

Under checks first the standards family is attached when a profile is named and reported with
its reason when it is not (`coverage.prerun.standards`, the four sentences of 007's
`contracts/gate.md` section 2) - which supersedes 007 FR-030's "nothing about standards" for
lever 5.

## 3. Live interference

1. Before call 1 the package's rows for the reviewed configuration are removed in memory (the
   rule `PackageAppender.Merge` applies on the console); they are restored if the call fails.
2. The call's new rows join the in-memory package, and `planned_calls` then judges every group.
3. The detected rows and the host's gaps are written by `ir/loader.append_interference_run(
   source_dir=package_dir, target_dir=out, configuration, rows, gaps)`: the raw
   `source_dir/package.json` is parsed, that configuration's rows replaced, the new rows and any
   new gaps appended, the text re-validated as an `EvidencePackage` that must equal the in-memory
   package, written to a temporary file in `target_dir` and `os.replace`d onto
   `target_dir/package.json`. In the pane `source_dir == target_dir`; on the command line the
   input folder is never written and the merged copy lands in `--out`.
4. Outcomes, each a digest line and a coverage item, none stopping the review:

| Outcome | Coverage | Digest line |
|---|---|---|
| no bridge, and the package holds rows | skipped `coverage.prerun.interference` | "interference: SOLIDWORKS is not attached, so live detection did not run; the <n> groups the package already holds were judged" |
| no bridge, and the package holds no rows | skipped `coverage.prerun.interference` | today's sentence, unchanged: "the package reports no interference, so no group was checked. That is what SOLIDWORKS detected, not a claim that detection was run over every configuration." |
| part root, or fewer than two components | skipped `coverage.prerun.interference` | "interference: live detection needs an assembly with two components or more; the root is <kind> with <n> components" |
| the call failed (any `BridgeError`, the open circuit, a host error, a bridge without `interference`) | failed `tool.bridge_interference` (the dispatch's own) and skipped `coverage.prerun.interference` naming the error | "interference: live detection failed: <error>; it was not evaluated" |
| rows dropped because their ids collide with another configuration's | unresolved `coverage.prerun.interference` with the count | "interference: <n> detected rows were dropped because their ids collide with rows of another configuration" |
| the rows could not be written | unresolved `coverage.prerun.interference_rows` naming the error; every file untouched; findings still recorded | "interference: the detected rows could not be written to package.json: <error>" |
| detected nothing | **checked** item for checklist id `interference`, scoped to the configuration, reason stating `STATIC_SCOPE_LIMIT` and the settings | "interference: live detection over <configuration> found no interference (<settings>)" |
| detected groups | none beyond the calls' own | "bridge_interference(<configuration>) -> <rows> rows in <groups> groups (<settings>)" |

A hang is not detectable: the pipe transport has no read timeout (research R2.23).

*Landed as (T042).* The sentences count in English: "the 1 group the package already holds was
judged", "1 detected row was dropped because ..." / "<n> detected rows were dropped because
...", "the root is a part with 4 components". The live line counts the rows the call **added**
(`rows_added`) and the distinct groups among them, so "rows in groups" are the rows the pre-run
then judged; rows dropped for colliding ids are the unresolved line's count. The collision and
the failed write are `unresolved` items (`NotEvaluated.bucket`), the rest `skipped`, and every
one renders its line under "NOT evaluated, and why". A clean detection's line replaces the
call's own `Evaluated:` line. The host's gaps are kept once in memory too, so the in-memory
package equals the written one and a Retry grows neither.

## 4. The opening digest

`DIGEST_HEADER`, `Evaluated:` and `NOT evaluated, and why:` stay. Within `Evaluated:`:

- a tool called once renders exactly `PrerunCall.line()`;
- a tool called several times renders one line: `check_interference_group x113 -> 113 ok, 113
  findings` (errors counted and the first three named);
- the live call has its own line (section 3).

`Findings recorded: <n>` stays. Then, in the order the findings were recorded:

- a **folded family** renders one line and no id: `modelling practice: 85 findings across 7 rules
  (51 demonstrated, 34 suspected); counts only - the findings are in the session and the report`,
  its counts from `tools/model_view.count_findings`;
- every other `(check, status)` renders `  <check> - <n> <status>: <ids>` with at most
  `DIGEST_ID_CAP = 20` ids and `and <m> more`.

No payload key (`subjects`, `inputs`, `drawing_locations`) ever appears in the opening message.
The opening message is never pruned (`model-view.md` section 7).

## 5. The re-call guard

`PrerunGuard(tools, prerun)` wraps the dispatch innermost when a pre-run ran. Its ledger holds the
**successful** pre-run calls, keyed by `repeat_key(tool, arguments)`:

| Tool | Key |
|---|---|
| `check_rms_part`, `check_rms_equations` | `(tool,)`, whatever `document_id` |
| `check_rms_assembly`, `check_standards` | `(tool,)` |
| `check_interference_group` | `(tool, group_key)` |
| `bridge_interference` | `(tool, configuration, sorted-JSON settings)`, only when `component_ids` is empty |
| `check_joints`, `check_mass_material`, `check_hygiene`: every name in feature 010's `CODE_FIRST_CHECKS`, read when the key is asked for (*landed as*, T044, research R2.52; 010 T092-T093) | `(tool,)`, whatever arguments: they take none |

A hit records one real step through `registry.record_call` (status `ok`, no coverage, no finding
event) and answers:

```json
{"status": "already_run", "ran_at_step": 4,
 "note": "Checks first ran this call before your first turn; its findings are in the session. It was not run again.",
 "outcome": {}}
```

`outcome` is `check_digest(recorded payload, counts_only=<the tool's family is folded>)`
(`model-view.md` section 3) for a check tool, and `{groups, rows, configuration, settings}` for
`bridge_interference`. A miss - another configuration, other settings, a component subset, or a
call whose pre-run attempt failed - runs normally. With checks first off there is no guard.

## 6. The folded group

`start_review` sets `session.folded_families = ["rms"]` when checks first ran. For such a session:

- **ranking**: every `rms.*` finding - suppressed and decided ones included - forms one
  `AttentionRow` with `family = "rms"`, `rule_count` = distinct check ids, `check = "rms"`, `title =
  "Modelling practice: N findings across M rules"`, `member_finding_ids` = every family id sorted,
  the representative the member whose own key sorts first, `component_ids` the union. The row takes
  at most one Start-here slot, and `start_here_lines` prints its title. Non-family rows keep their
  relative order. `family` and `rule_count` are omitted when absent, so an unfolded session's
  `attention.json` keeps its bytes.
- **report**: the family's findings render once, after the severity sections, under `###
  Modelling practice: N findings across M rules` and inside `<details><summary>` (a count per
  rule) `…</details>`, each finding rendered as the severity sections render it; they are left out
  of the severity sections. Every finding id still appears under `## Findings`.
- **the model**: sees only the counts - the digest line, the guard's counts-only outcome - and
  the explanation pass never receives a family row.

Check folders never fold. A session without the field renders and ranks byte-identically to
today; the existing goldens do not move (FR-029).

## 7. Already-run tools leave the array (lever 13, amendment 2026-09-23)

FR-030, research R2.53. `EfficiencySettings.withhold_prerun_tools` is read once, in
`start_review`, after the pre-run; `pane_efficiency(provider)` turns it on for both providers,
and on the command line it is `--lever withhold_prerun_tools` (refused without `prerun_checks`
or `procedural_gate`) or `--pane-defaults`. With checks first off, or the flag off, nothing
below happens.

`prerun.withheld_tools(context, tools, calls)` returns the tools that leave, in pre-run order,
and `PrerunResult.withheld` holds them. A call *completed* when `PrerunCall.error is None` and
`repeat_key(tool, arguments)` is not `None`, so the guard can answer any repeat.

| Tool | Leaves the array when |
|---|---|
| `check_rms_part`, `check_rms_equations`, `check_rms_assembly` | all three were called, every call completed and none named a `document_id`; otherwise all three stay |
| `check_interference_group` | it was called; every call completed; every group `groups_of` enumerates after the pre-run has a completed call for its key; no key is shared by two groups; `bridge_interference` is not offered to the model |
| each name in feature 010's `CODE_FIRST_CHECKS` | it was called and every call completed |
| `check_standards` | a standards run is attached, it was called and the call completed |
| `bridge_interference`, `get_finding` and every other tool | never |

A tool that is not in the dispatch's offered tools (withheld by tier) is never listed.

**Mechanism.** `PrerunGuard.__iter__` and `__len__` leave out `prerun.withheld`; `call` is
unchanged, so a withheld tool called anyway reaches the guard's ledger and is answered
`already_run` (section 5), and anything the ledger misses reaches the dispatch, which still
holds the tool. The system prompt's tool notes (lever 2) are built from the offered tools only.

**Wording.** Only when the named tools are withheld (`agent/withheld_wording.py`):

| Where | Withheld | Was | Now |
|---|---|---|---|
| `system_v1.md` step 3 | `check_interference_group` | `` `check_hole_alignment`, `check_interference_group`) `` | `` `check_hole_alignment`) `` |
| `system_v1.md` step 4 | the three RMS tools | the whole step ("4. Grade the modelling method ... answer it.") | "4. The modelling method was graded before your first turn: checks first ran the three RMS checks over every document, and the opening message gives their counts. Together they close out `modeling.resilience`; do not mark that item covered by hand." (wrapped as the file wraps) |
| checklist item `modeling.resilience`, in the prompt and in `get_review_checklist` | the three RMS tools | "Run check_rms_part, check_rms_assembly and check_rms_equations." | "Checks first ran the three RMS checks before the first turn." |

The digest's `Evaluated:` block is followed by one line, `WITHHELD_LINE`:
`Not offered to you this session, because checks first ran them to completion: <names>.`
A stub (`model-view.md` section 7) of a tool the adapter does not offer says
`<name> is not offered this session, so it cannot be called again`, with
`; get_finding(<id>) reads one finding` when its content carries finding ids and `get_finding`
is offered, instead of "call <name> again". Both adapters pass `prune_history` the names on
the turn's array (`offered`); the replay passes each pass's array, counting a call it could not
run (`estimated` or `stored`) as offered, since it ran where the recording was made
(*landed as*, T114).

Unchanged: `DIGEST_HEADER`, the `Evaluated:` lines, the tier sentence, FR-037's reduced-profile
sentence, `ANSWER_MESSAGE`, and every tool description.
