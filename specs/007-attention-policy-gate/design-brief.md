# Design brief: attention policy and procedural gate

Input to the plan phase. Recorded from the 2026-09-18 planning session: seven subsystem
readers, two bug diagnoses, three independent designs (procedural gate then targeted agent;
an agentic triage layer; a deterministic policy with no new agent stage), three judges
(engineer value, engineering quality, feasibility now), one synthesis and one completeness
critic. Line numbers below were verified in the tree on 2026-09-18 and will drift; the plan
re-verifies each before naming it.

## Decisions taken by the owner

| # | Decision | Chosen |
|---|----------|--------|
| 1 | Do findings that need engineering judgement rank above rebuild-breaker RMS findings? | Judgement first, then consequence class |
| 2 | Scope to the 2026-10-03 checkpoint | Bugs, timing, the policy on report.md and the two keyless tabs; the gate and the brief built behind a flag and not claimed |
| 3 | How the gate is switched on | An eleventh efficiency lever, `procedural_gate`, paying the three pinned lever-count edits in one change |
| 4 | Next artifact | This spec package; the two pane bugs fixed first as their own commits (`b3cb948`, `7e700e4`) |

## What the readers established (facts the plan relies on)

- The review loop is one provider turn per engineer message (`agent/runner.py`); the model
  alone chooses what to investigate, steered by `agent/prompts/system_v1.md` and the nine-item
  `agent/checklist_v1.yaml`. Findings are built by the check tools, not authored by the model,
  except `record_drawing_finding` (`tools/session.py:118`), which cannot claim `demonstrated`.
- There is no priority, rank or confidence anywhere. Report order is fixed sections, findings
  grouped high > medium > low > info in recording order (`report/markdown.py:35`
  `_SEVERITY_ORDER`). `Severity` is a `Literal` at `findings.py:36` and must stay.
- Severity is nearly constant for the rule families (`checks/rms/registry.py:368-370` maps
  fail to demonstrated/medium and warn to suspected/low), but not for interference
  (`checks/interference.py:60`, `SEVERITY_VOLUME_MM3 = 1.0`, high above it).
- `FindingGroup` (`findings.py:68`) exists for FR-011, renders at `report/markdown.py:358-362`,
  and is constructed nowhere under `src`; the only construction is `tests/unit/test_report.py:79`.
- `render_report` (`report/markdown.py:55`) has **eight** production call sites: `cli.py:563`,
  `cli.py:607`, `cli.py:1303`, `chat/server.py:1860` (after every turn at `:1803` and after a
  stop at `:1883`), `chat/sessions.py:348`, `checks/rules/run.py:231`,
  `checks/standards/run.py:418`, `report/dispositions.py:111`. The re-modeler has its own
  separate renderer (`remodel/report.py:221`), which the `test_remodel_report` golden covers.
- Lever 5 (`prerun.py:338 prerun_checks`) already runs `check_rms_part`, `check_rms_equations`,
  `check_rms_assembly` and one `check_interference_group` per group through the production
  `ToolDispatch`, so it produces real steps, findings, coverage and stream events; its digest
  (`prerun.py:209`) and `NotEvaluated` (`prerun.py:151`, `coverage_item` `:167`, `line` `:172`)
  render the report line and the model line from one object. It has never been A/B'd (005
  T078/T079 open).
- The lever count is pinned in three places: `tests/unit/test_no_lever_in_pane_settings.py:46`
  (`len(LEVER_NAMES) == 10`), `tests/unit/test_efficiency_settings.py:55/:89/:90`
  (`EXPECTED_LEVERS`, `[False] * 10`), and `_levers_sentence` in `agent/settings.py` ("the ten
  levers are"). `EfficiencySettings` is at `agent/settings.py:400`.
- `ChatServer._start_review` (`chat/server.py:1721`) passes no `efficiency` and no
  `previous_session`, so every feature-005 lever is structurally unreachable from the pane.
- The check routes: `OFFERED_SCOPES` (`chat/server.py:605`) excludes `RmsScope.assembly`, so
  the Model check tab cannot produce a needs-judgement finding. `check_result` (`:655`) and
  `standards_result` (`:785`) are the bodies that gain an `attention` key; their contracts are
  `specs/003-resilient-modeling/contracts/model-check.md` and
  `specs/006-standards-check/contracts/standards-check.md`.
- A review that claims a check folder rotates the check's `session.json` to `session.1.json`
  (`chat/server.py:1656-1717`); `is_check_folder` is at `checks/rms/run.py:533`.
- Timing: `benchmark/timing.py:19 record_timing` is the sole writer of the four human inputs
  and resolves `<run_dir>/<package_id>/session.json` at `:15-17`, a shape no pane or CLI run
  folder has. `median_net_saved_minutes` is absent from `benchmark/adoption.py:155-170`.
  `swreview benchmark time` already writes the same four inputs, so the new command must
  share one writer with it rather than add a second surface.
- `benchmarks/sets/pilot.json` holds one package, `cover-blind-tap`, `held_out: false`, so
  recall is None and `adoption.decide` refuses every decision.
- The checklist has no `standards.` prefix (`agent/checklist_v1.yaml` lines 6-60), so standards
  findings inside a review close nothing until an item is added.
- `Disposition` (`findings.py:59`) has three decisions; `deferred` is neither accepted nor
  rejected. A waiver whose fingerprint moved is left standing with a re-review marker
  (`checks/rules/report.py:486 _needs_review`); the waive rewrite is `_waived` at `:463`.
- The fastener family exports five constants (`checks/fastener.py:59-63`), not one
  module-level `CHECK`; the catalogue test must enumerate them.

## The policy, as the synthesis stated it

One pure module, `reviewer/src/swreview/report/attention.py`, plus a versioned
`attention_policy_v1.yaml` (consequence classes, the needs-judgement set, the blind-spot
sentence per family, the four triage-pass preconditions). Nine keys, each one named lookup:

1. suppressed last (`exception_id` active, disposition accepted or rejected, or
   `checked_within_scope`; still rendered);
2. needs judgement first (`interference.*`, `fit.*`, `fastener.*`, `hole.*`);
3. consequence class: rebuild_breaker > interface > manufacturing > unclassified >
   discipline > hygiene;
4. status: demonstrated > suspected > unresolved;
5. severity: high > medium > low > info, read from the existing literal;
6. reach: distinct `component_ids`, capped at 3, descending;
7. carried over (`carried_over_from` set) last within its group;
8. check id; 9. finding id.

Folding before ranking: same check, status and severity, disjoint subjects, never a
needs-judgement check; stamped on the surviving finding's `group`; nothing removed.
Top five are "Start here"; a "Not amplified: N findings (n waived, n dispositioned, n info)"
line; a "Ranked by attention_policy_v1; the rule is in report/attention.py" line; a separate
coverage block ("What this run could not reach: 39 unresolved, 11 skipped" plus top five
prefixes) sourced from `agent/checklist.py:45 bucket_of` and `prerun.py:261
not_evaluated_families`, never recomputed. The model contributes nothing to the rank.

On the 2026-09-18 review this yields: interference pin A, interference pin B,
`rms.assembly.mates_to_reference_geometry`, `rms.sketches.fully_defined`,
`rms.grouping.all_features_in_a_group`; `rms.folders.present` last of eight. On the model
check: `rms.sketches.fully_defined`, grouping, folders. Folding does nothing on that data
(the rule layer emits one finding per rule per document).

## Implementation order (each step carries its verification)

| Step | What | Size | Verify |
|------|------|------|--------|
| 0 | Timing: extract `record_timing_at(session_path, ...)`; `record_timing` becomes a two-line wrapper; `swreview timing <run_dir>` beside `disposition` (`cli.py:626`) sharing the writer with `benchmark time`; `POST /sessions/{chat_id}/timing`; `median_net_saved_minutes` as a reported column | half a day | real net figure on a fixture folder; negative refused; net never accepted; benchmark path unchanged |
| 0a | A human-baseline collection step: who records the four inputs after each pilot run (the owner, from the CLI) | owner time | a run folder from the workstation carries timing |
| 1 | `report/attention.py` + policy file + catalogue test; nothing calls it yet. Land the catalogue test after step 2's read-through, or it pins an unagreed table | 1 day | shuffled-input byte-identical; no provider/settings import; full suite unchanged |
| 2 | `swreview attention <run_dir>` keyless reader; copy the 2026-09-18 folders (three reviews, one check) off the workstation and read the output with the owner | hours | top five as stated above; provider factories patched to raise |
| 3 | `render_report(*, ranking=None)` and the `## Start here` section; wire **all eight** call sites; golden fixture for a ranked report | half a day | both existing goldens byte-identical with `None`; section present after turn, stop, disposition, waiver |
| 4 | `attention.json` beside `session.json`: written by `ReviewRun.finalize` (`runner.py:719`, including the failure path) and by both check paths; rotation with the check session; explicit folder-kind test | hours | re-running `rank` over the finished session reproduces the record |
| 5 | `attention` key on `check_result` and `standards_result`; amend both contracts | hours | route tests assert the key equals `rank` over the same session and no provider is constructed |
| 6 | Folding into `FindingGroup` | half a day | `member_component_ids` min 2; interference rows never fold; session length unchanged |
| 7 | Number guard on `record_drawing_finding` | hours | "0.05 mm" refused without a cited source, accepted with one; ids accepted; error result, never a raise |
| 8 | The gate: lever 11 (three pinned edits in one change), `planned_calls`/`not_evaluated_families` widened, brief composed from the digest + ranked rows + three lists + the instruction, wired at the pre-run call site and the opening-message site (`runner.py:988`); anti-drift test; `test_prerun_digest.py` byte-identical with the gate off; state whether `procedural_gate` implies `prerun_checks` | 1.5 days | brief ids == Start here ids; lever 5 arm untouched |
| 9 | Pane rendering: ranking above the bucket chips (`web/shared/check-page.js`) and a pinned Review panel on `session.ended` (`app.js` `showFinding` region, `:498`); computed nowhere in JS | 1 day | add-in tests assert no severity list or band rule in any page script; one workstation run matches report.md |
| 10 | Standards inside the gate: `check_standards` in `planned_calls` with a profile, a `standards.` checklist item, `--standards-profile` on the CLI review | half a day + a workstation session | two families in one session without contaminating each other's summary items (untested anywhere today); NotEvaluated line and skipped item without a profile |
| 11 | Measure: six alternated runs off/on, the ledger row, the named regression (per-run `check_fit` and `check_axial_stack` counts must not fall) | calendar-bound | the row computes rather than being typed |
| 12 | Gate on in the pane as a code default behind a ledger row; pass the standards profile path (`chat/server.py:1721`) | half a day | `test_no_lever_in_pane_settings.py` still green; pane review shows gate cards before the first model text |

Steps 0 to 8 are pure Python and were planned to run in parallel with the two C# bugs, which
are now landed. Step 9 needed the event-stream fix (`b3cb948`); step 10 needs the
drawing-attach fix (`7e700e4`) and 006 T100.

## Corrections the critic made to the synthesis (honoured in the spec)

- Eight render call sites, not three; a section wired into three is erased by the next turn.
- `attention.json` needs a writer on the review path (`finalize`), not only on check folders.
- The 2026-09-18 run folders are not in the repository; copying them is a named prerequisite.
- The Model check tab cannot exercise the judgement key (no assembly scope); the first
  shipped surface validates the consequence class only.
- The drawing-attach fix skips drawings; it does not unblock 006's drawing-rooted standards
  scenarios, which need a nullable configuration through the dumpers.
- `deferred` and re-review waivers need a stated rule (the spec: they keep competing).
- The reach key is inert on a four-component assembly.
- A golden fixture for a ranked report is required by Principle III, not optional.
- A `standards.` checklist item is required or standards findings close nothing.
- `swreview timing` must share `record_timing_at` with `benchmark time` (DRY).
- Line citations corrected: `SwReviewAddIn.cs` delegate at `:880` and follow call at `:1026`
  (pre-fix), `standards.js` has 357 lines, `app.js` `showFinding` at `:498`, no module-level
  `CHECK` in `fastener.py`, `EfficiencySettings` at `settings.py:400`, `_reconcile_reruns` at
  `runner.py:552`, `bucket_of` at `checklist.py:45`.

## Rejected, and why

- A separate triage turn (a second provider round trip whose only output is prose): the worst
  cost/benefit against a pilot judged on minutes with no recorded baseline; the same value
  comes free by reshaping the opening message.
- A weighted sum with hand-set points: arguable only by re-doing arithmetic; a tuple key is
  arguable by pointing at a line.
- Ranking unresolved coverage above demonstrated findings: on the real run 39 unresolved rows
  bury the press fit; coverage gets its own block instead.
- A recurrence-driven order: right on this run by accident; three `rms.refs` findings would
  invert it.
- A rank, score or confidence field on `Finding`: the schema is `additionalProperties: false`
  and a rank is a property of this policy at this version, so it travels in `attention.json`.
- Rewriting lever 5's digest in place: redefines an experiment never performed.
- Moving `_SEVERITY_ORDER` out of `report/markdown.py`: churns the goldens for no gain.
- A new event type or a synthetic `text.done` for the brief: new weight on the stream.
- A number guard over the model's free prose: that prose never enters the report.
- Redirecting a drawing attach to its referenced model: chicken-and-egg through the gate, and
  it reviews a document the engineer did not select.
- A `GET /sessions/{id}/attention` route: redundant beside the `attention` key and the report.

## Written preconditions for an agentic triage pass

Build one only when all four hold: the deterministic top five misses the finding that got
the first accepted disposition in 30% or more of reviews over five designs; the miss cannot
be expressed as a new consequence class or rule (005 T110's standing practice); assisted
verification minutes exceed about ten per design; and net saved minutes is already positive.
