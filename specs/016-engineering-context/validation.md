# Offline delivery validation — 2026-10-14

Branch: `016-engineering-context`, based on main `7a21605`.
Scope: typed requirements and total applied forces, saved-snapshot binding, immutable
private storage, explicit confirmation, CLI entry and bounded read-only review context.
No C# source, native protocol, capability switch or CAD file is changed.

The full gate also exposed a pre-existing Remodel polling race. A poll could read an
applying plan, then return a terminal job state published during that read. The follow-up
fix snapshots state/error before reading persisted facts, and publishes the failure
reason before the failure state. Four controlled regressions force the interleavings;
all 90 Remodel route tests pass. No timeout or native action is changed.

## Evidence collected

- Focused integration gate: 158 passed, including default registry/schema pins and
  benchmark/pane default parity. Later unit-export and CLI checks also pass.
- Binding lane: 50 passed; repeated instances, configurations, unavailable ancestors,
  exact raw snapshot digests, one package read per batch and private refusal messages.
- Store lane: 44 passed with actual Windows link/junction fencing and no skipped case;
  immutable history, CAS, cross-process locks, interrupted head replacement, identical
  orphan retry, approval invalidation, baseline restoration refusal and withheld-data fencing.
- Brief/tool lane: 72 passed including existing surface regressions; exact states/counts,
  6000-byte bounds, path/ref/actor omission, refresh reassessment and checked root force vectors.
- CLI smoke: the installed entry point lists all five context commands; a fake-provider
  review with explicit `--engineering-context` retains its bounded summary and report.
- Ruff and Windows Git whitespace checks pass.
- Full nonlive Python gate with required tokenizer: 15,592 passed, 4 skipped,
  7 deselected, 2 existing warnings in 525.33 seconds. Command:
  `SWREVIEW_REQUIRE_TOKENIZER=1 python -m pytest -m "not live"`.
  Native integration cases skip without their saved workstation package; live provider
  cases are excluded. No native SOLIDWORKS run or C# validation is claimed for this
  Python-only change.

Meaningful behavioral failures were recorded before fixes for force conversion/admission,
rigid frames, missing ancestor/configuration facts, forged frames, repeated snapshot reads,
stale/baseline-restored approval, failed publication, invalid confirmation numerics,
withheld directories, private diagnostics/path fragments, oversized revision metadata,
context opening-message attachment and stale summaries in reused output directories.
Missing-module scaffolds and corrected test-fixture mistakes are not correctness evidence.

Independent review converged on the implemented offline scope. The full suite initially
flagged the new semantic review argument and force converter in existing closed API
classification tests; their explicit classifications were updated without weakening
parity or changing the default tool schema pins.

## Remaining gates

Native selection/face resolution across extractions, unsaved-state attestation and a
SOLIDWORKS engineer UI remain T010 on the other machine. Offline `matched_snapshot`
is historical evidence, never verification of live CAD state. Automated drawing output,
pressure/moment/support/load-case modeling and structural acceptance are later features.
Existing drawing-open, drawing numerical-binding and Remodel Start switches stay unchanged.

## Adaptation to feature 015's send gate — 2026-10-15

Branch `016-adapt-015`, from `016-engineering-context` (`769432e`), with `main` (`10cecf3`:
015's send gate, 014 slice 5 and 23A) merged as `15c3793`, per owner decision 99A (015
research R8). Each commit group landed test-first and gate-green; the T116 integration
review's findings, as fixed:

| Finding | Fix | Red-first tests |
|---|---|---|
| The context start skips the Send gate (blocker) | `3bef74f`: one `CreateReviewSession`, Send or Wait from the box; page busy takes 015's flags | host theory, wire body, two page tests |
| The rebuilt Send opening drops the context (blocker) | `5bb44b0`: one opening builder input, `runner._review_opening`; summary on `ReviewRun` | answered-wait opening and estimate; reloaded package |
| A restored review's re-run drops its context (should-fix) | `e8c167c`: `model_status.engineering_context`; re-run reloads and validates it; no unlink | record and schema; restart re-run and Send; changed head; cut at the replace |
| Context editable while a review waits (should-fix) | `6e48e3e`: `awaiting_send` busy; one registry, `_pending_run_dirs` | edit while waiting; edit during the record read |

The merge's textual conflicts were resolved as the reviewer listed them, with
`engineering_context` keyword-only on `_start_review` and passed by name. `9bac682`
regenerated the three waiting pane fixtures with 016's labels (snapshot part byte-equal,
labels the union) and moved `review-send-failure-events.json`'s pin of
`review-waiting.json`'s sha256; `review-big-assembly.json` regenerated unchanged.

A re-run validates the recorded head, context id and saved package digest, not the folder's
package against the saved baseline: the first run's live interference check appends to
`package.json`, so requiring the baseline would refuse every re-run of an assembly review
with live checks. The summary marks that change as needing review, as at the start.

Gate on `6e48e3e`:
- Python 3.11.16 (the worktree's environment), `SWREVIEW_REQUIRE_TOKENIZER=1`, not live:
  **16,543 passed, 6 skipped, 7 deselected**; Ruff clean.
- Python 3.11.16 and 3.12.3, each `uv run --isolated` outside the repository with
  `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`: **16,543 passed, 6 skipped,
  7 deselected** each; no 3.12-only API.
- Release build: zero warnings and errors. .NET: **9,138 extractor and 2,448 add-in tests**,
  none skipped.
- Replay regeneration: all three generators unchanged; `git diff --exit-code --
  reviewer/tests/fixtures/replay` empty.
- 015's pins T007 (`test_ticked_review_golden`) and T008
  (`test_request_prefix_characterization`) green and unedited.

Still open: T010 and T015, the SOLIDWORKS workstation gates. No SOLIDWORKS run, live model
call or paid request was made.


## Owner decisions 105A-109A on the adversarial check — 2026-10-15

The adversarial check of `10cecf3..2ab8043` answered MERGE-READY: no path gets saved context
to a provider before Send. The owner's follow-ups, each test-first and gate-green:

| Decision | Commit | What |
|---|---|---|
| 109A (31A) | `51e7b9f` | 001's `Finding` accepts a document scope in a non-empty `inputs`; a whole pane review's `session.json`, ticked or unticked, with or without context, validates. Also the verifier's two probes as tests and Remodel's awaiting rule held once |
| 107A (29A) | `3ab02ee` | the baseline's `without_live_interference_sha256`; the live check's own rewrite keeps saved inputs matched, any other change mismatches |
| 105A (26A), 106A (27A), 108A (30A) | `9bafa80` | the carried check also requires package id, root document and configuration; the strict lock kept; Retry re-attaches the same context in its folder through the gated path; the refusal and the `EngineeringContextConflict` label point to the Engineering context panel |

Gate on `9bafa80`:
- Python 3.11.16 (the worktree's environment), not live: **16,567 passed, 6 skipped,
  7 deselected**; Ruff clean.
- Python 3.11.16 and 3.12.3, each `uv run --isolated` outside the repository with
  `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`: **16,567 passed, 6 skipped,
  7 deselected** each.
- Release build: zero warnings and errors. .NET: **9,138 extractor and 2,456 add-in tests**,
  none skipped.
- Replay regeneration unchanged and its `git diff` empty; T007 and T008 green and unedited.

Still open: T010 and T015, the SOLIDWORKS workstation gates.
