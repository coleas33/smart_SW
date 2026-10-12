# Quickstart: Validating the Design-Review Eval

**Feature**: `014-design-review-eval` | **Plan**: [plan.md](plan.md) | **Tasks**: [tasks.md](tasks.md) | **Contracts**: [contracts/](contracts/README.md)

Runnable scenarios, offline first, then the paid pilot and the cost gate. Each names what it proves
and the outcome to expect. Commands run from `reviewer/` unless they say otherwise. Offline means no
provider key and no SOLIDWORKS licence (FR-047); SOLIDWORKS is never started. Folders written under
`$TMP` stay outside the repository.

## 0. Preconditions

- A checkout made after the `.gitattributes` change of the parity slice. On an older Windows working
  copy, check the digested inputs out again once, or the line-ending test and the pane studies refuse:

  ```bash
  git ls-files --eol config/standards.example.yaml reviewer/src/swreview/agent/checklist_v1.yaml \
      reviewer/src/swreview/agent/prompts/system_v1.md      # expect w/lf on every line
  ```

- After this branch merges into `main`, any other checkout deletes its working copies of
  `config/standards.example.yaml`, the checklist and the system prompt and checks them out again
  (`git checkout -- <them>`; git leaves an unchanged working copy as it is), so they read LF and
  their digests agree (plan RK-5); the check above then reads `w/lf`.

- `uv sync`, then `uv run swreview tokenizer fetch` once per machine: section 1 runs with
  `SWREVIEW_REQUIRE_TOKENIZER=1`, under which a missing vocabulary fails the tests that need it
  rather than skipping them (`reviewer/tests/conftest.py:85-106`). The vocabulary is otherwise
  optional offline: without it token counts read unknown and nothing is refused, which
  `test_benchmark_attempts.py`'s no-vocabulary test pins (`benchmark-run.md` 15; INT-18).

## Offline

### 1. The whole suite

```bash
SWREVIEW_REQUIRE_TOKENIZER=1 uv run pytest -q -p no:warnings -o addopts="" -m "not live"
uv run ruff check src tests
```

Expected: green. `test_line_endings.py` passes (or is skipped, never passed, without git);
`test_committable_paths.py` finds no local path in any committable file.

### 2. Oracle and null reviews, and the version rule (SC-001, SC-002, SC-013)

```bash
uv run pytest -q tests/golden/test_golden_scorecards.py tests/unit/test_committed_answer_keys.py
```

Expected: for every committed case the oracle, written as a package folder with its one-event
`events.jsonl` and its stored request results (RF-58), detects every known defect and scores zero on
every failure column its key grades; a column reads "not assessed" exactly where the key has no entry
of the list it reads, and the two answer-log columns always (no oracle has an answer log), and
nowhere else; the null detects nothing and raises no false alarm; no oracle
finding matches a second defect; each probe moves exactly the columns it declares; the goldens'
digest equals the last row of `tests/golden/scoring_rules_versions.json`. Changing a matching rule
without appending a row fails here, as does appending a row with no golden change.

### 3. Regenerate the committed cases byte for byte (SC-006, SC-011)

```bash
uv run python -m tests.benchmark_cases.generate
git status --porcelain -- ../benchmarks ':(exclude)../benchmarks/packages/bracket-assy'   # expect nothing
```

Expected: every package, key, case file and set file rewritten to identical bytes, no stale file
reported, exit 0. The excluded folder is the test suite's native-package slot, placed per machine and
not ignored by git, which the generator neither writes nor scans (`cases.md` 1; RF-75): on a machine
that holds it, `git status` would otherwise list it untracked however identical the regeneration. `tests/unit/test_benchmark_generator_imports.py` passes: the generator imports only
the allowed data models and fictional builders (the key's format through the data-only
`benchmark/answer_key_model.py`, never the key loader), and each data-only format module, imported
alone, loads no tool, agent or check module.

### 4. Reachability validation (FR-054, SC-014)

```bash
uv run pytest -q tests/unit/test_benchmark_cases_reachable.py tests/unit/test_benchmark_validation_catches.py
```

Expected: under three minutes; for every committed case (a) code-only calls detect exactly the
code-produced defects and nothing unkeyed, (b) the correct reviewer detects every model-produced
defect at its expected status under both the off and the pane configuration, and no decoy credits,
flags or clears a planted entry. The second file proves each leg fails, with its message, on a
deliberately broken in-memory case.

### 5. The committed set's summary (FR-033, SC-004)

```bash
uv run swreview benchmark set-summary ../benchmarks/sets/committed.json
```

Expected: one row per judgement family and one for the others; 36 held-out model-produced defects
against the floor of 34 ("met"); every one with a clean twin; the largest design share at or below
a fifth; every anchor R-1 to R-8 and analyst-found AF-1 to AF-3 covered; no stale held-out item;
exit 0.

### 6. A scripted multi-turn case (US4, US3-6)

```bash
uv run pytest -q tests/integration/test_scripted_answers_flow.py tests/integration/test_questions_on_real_tools.py
```

Expected: the scripted model asks the fit question naming the pin and the plate's hole, "press fit"
arrives through `answer_evidence_batch` as one answer turn, and the follow-up naming only the plate's
hole is refused by the product's guard as already answered and counted as one refused re-ask on the
scorecard; `answer-log.json` records one point with one delivery of `A-1`, `ended`
`no_open_questions`, and no answer text. In the real-tools test, R-3's item-only follow-up is
recorded and is one seen re-ask, and the driver answers it again at the next point (an entry answers
every time it is asked); R-2's second request is one repeat of an open question and a second
unanswerable request.

### 7. An offline run, score and compare over the committed set (US2, US1-11)

```bash
uv run swreview benchmark run --set ../benchmarks/sets/committed.json --out $TMP/off-1 \
    --provider fake --study pane_defaults --arm off --rep 1 --no-explain-findings \
    --standards-profile ../config/standards.example.yaml --max-answer-turns 0
uv run swreview benchmark score $TMP/off-1
uv run swreview benchmark compare $TMP/off-1 --out $TMP/ledger
```

Expected: the run refuses nothing (the fake provider is synthetic: the pane studies' clean-tree and
known-commit rules still apply, so commit or stash first). `--max-answer-turns 0` is needed here:
the fake's one-turn script cannot play `mir-sitting`'s scripted part-roles answer, which would end
that package `internal_error` and the run with exit 1; at 0 the delivery is held and its log reads
`bound_reached`, a completed review (research §9.9, RF-25). `run-provenance.json` and
`benchmark-set.json` exist before the first package folder; the saved set names every package
repository-relative; `run-status.json` records each package `completed`; the score prints the
three-line summary with its scoring-rules version; compare writes a ledger with the model view,
profile and live-tools columns, and a raw row per package (one arm alone gives no verdict, refused as
"an arm of the pane study has no run", the raw rows still written, exit 1). `score` reads the keys
the committed set names, so it needs no `--answer-keys`. Comparing a folder whose scorecard was
written by an older build is refused with "Re-score it: swreview benchmark score ...", before any
validation error; `score` itself overwrites such a scorecard and re-scores it.

### 8. A forced-failure run and resume (SC-007, US7)

```bash
uv run pytest -q tests/integration/test_benchmark_failures.py tests/unit/test_benchmark_resume.py
```

Expected: over one set the scripted provider fails on the first package, hangs silently on the
second (a short injected wall clock) and safety-stops the third; the set completes; the first two
are infrastructure failures in `unscored_packages`, in no score, with exact retry counts; the third is
a behavioural `provider_stop` with its reason, scored from its state at the stop, its re-asks and
forbidden hits counted; `benchmark resume` re-runs exactly the two failures from the start in new
attempt folders and never appends to the third.

### 9. The report (US6, SC-009)

```bash
uv run swreview benchmark report $TMP/off-1 --out $TMP/report
uv run pytest -q -m perf tests/perf/test_benchmark_report_perf.py
```

Expected: `$TMP/report/index.html` opens from disk with no script; its counts equal the scorecard's;
each row links to a transcript that starts with `prompts.json`'s system prompt, then the opening
message, then each answer turn as the engineer's turn; a failed repetition reads
`failed: <kind>, <class>`, never 0; a scripted run's cost reads "synthetic, not priced". Building
twice gives identical bytes. The perf test builds 940 pilot-size transcripts, the committed set at
the cap in both arms (47 × 10 × 2), in under 60 seconds (RF-46).

### 10. The simulator (SC-005's mechanics, SC-010)

```bash
uv run swreview benchmark simulate --scenario uniform-sd1.0-fa1-nb0.5-clear
uv run pytest -q -m simulation tests/simulation/test_reference_scenarios.py     # about 4 to 6 minutes
```

Expected: every input printed with its value or source; each size tried with its `alpha`, both powers
and both 5% rates with their upper bounds; the clearance scenario prints the cleared guard "named
only" with its null rate near 0.729, 0.885 and 0.936 at 3, 6 and 10 repetitions; every
`half-sd1.0-*` scenario reaches the cap of 10 and then adds at least one growth unit (S-10 asserts
it); the sweep holds both 5% bounds and 80% power in all 39 scenarios. Keep the sweep's printout with
the simulator slice.

## Paid (a machine with a provider key)

Run only after the robustness slice's gate and once the seat's Task Pane smoke review of the small
assembly has passed on the pilot workstation (tasks.md T221; owner decision 33A), and start with P0.
The tree must be clean and at a known commit; the
committed set, the example profile and the price table's entry for the model must be present: a
pane-study run whose model the table cannot price refuses to start, naming it (`benchmark-run.md` 3
row 6, RF-79), and `uv run pytest -q tests/unit/test_prices.py` checks the default models' entries.
Committable folders are written only for the committed pane study: the smoke run's and the paid pilot's under
`benchmarks/pilots/<study folder>/`, which `recorded_runs()` never scans, so a pilot run never enters
the study (RF-36), and the study's under `benchmarks/studies/<study folder>/`. Each is committed
whole, its event streams packed first (owner decision 28A): once a folder's run is final, `swreview
benchmark pack` replaces each `events.jsonl` with `events.jsonl.gz` and records each stream's sha256
in the folder's `event-streams.json` (`provenance.md` 6.7). A run writes plain streams, and `score`
and `report` read either form. `.gitignore` ignores a plain stream in both trees and admits a packed
one only there, so `git status` lists every packed stream before the commit and no
plain one (RF-84). The private slice's go outside the repository.

### P0. Smoke: two packages, one repetition per arm (owner decision 35A)

```bash
uv run swreview benchmark run --set ../benchmarks/sets/pane-smoke.json \
    --out ../benchmarks/pilots/pane-openai/smoke-off --provider openai --model <model> \
    --effort <effort> --study pane_defaults --arm off --rep 1 --no-explain-findings \
    --standards-profile ../config/standards.example.yaml --jobs <N>
uv run swreview benchmark run --set ../benchmarks/sets/pane-smoke.json \
    --out ../benchmarks/pilots/pane-openai/smoke-on --provider openai --model <model> \
    --effort <effort> --study pane_defaults --arm on --pane-defaults --rep 1 --no-explain-findings \
    --standards-profile ../config/standards.example.yaml --jobs <N>
# exit 1 names infrastructure failures: run `uv run swreview benchmark resume <that folder>`
uv run swreview benchmark score ../benchmarks/pilots/pane-openai/smoke-off
uv run swreview benchmark score ../benchmarks/pilots/pane-openai/smoke-on
uv run swreview benchmark report ../benchmarks/pilots/pane-openai/smoke-off \
    ../benchmarks/pilots/pane-openai/smoke-on --out $TMP/smoke-report
uv run pytest -q -m live -rs tests/live/test_benchmark_live_attempt.py
```

Two packages, `kalo-1` (a held-out core case) and `kalo-fit-1` (the anchor with a case file, so the
answer driver runs), one repetition per arm: about four real reviews, with the model, effort,
explanation setting and profile the pilot and the study will use, and `<N>` the concurrency planned
for them (1 unless chosen; P3). Then read every row of both scorecards and of the report:

- the served model, within the requested model's aliases (`served_models`);
- non-zero usage, input and output tokens;
- a priced cost, never "cost unknown", and the price table's source and date in the report's head;
- the run status: completed, bound-reached, or a behavioural stop with its class;
- `kalo-fit-1`'s answer log (`answer-log.json`): what the model asked and what was sent;
- the finding origins, none `unknown`;
- each package's transcript in the report, opening with the recorded system prompt.

The live test drives one more real attempt end to end and checks the same fields; it counts only as
`1 passed, 0 skipped`. Expected: every row as listed (SC-008 confirmed here first). A wiring fault (a
field missing, unknown or trivial; a refusal the pilot would meet; the live test red) is fixed before
P1 by a change with its own failing test; then delete both smoke folders, uncommitted, and run P0
again from the fix's commit. P1 runs from the commit of the P0 that passed. Keep the two folders: P2
reads their review times (`--smoke`), and P3 packs and commits them with the pilot's.

### P1. The pilot: three repetitions of the off arm (FR-055; owner decision 27A)

```bash
for n in 1 2 3; do
  uv run swreview benchmark run --set ../benchmarks/sets/committed.json \
      --out ../benchmarks/pilots/pane-openai/pilot-off-$n --provider openai --model <model> \
      --effort <effort> --study pane_defaults --arm off --rep $n --no-explain-findings \
      --standards-profile ../config/standards.example.yaml --jobs <N>
  # exit 1 names infrastructure failures: run `uv run swreview benchmark resume <that folder>`
  uv run swreview benchmark score ../benchmarks/pilots/pane-openai/pilot-off-$n
done
```

Three repetitions over the whole committed set, into `benchmarks/pilots/`, never counted as study
repetitions (research §9.7, question 6), from the commit of the P0 that passed and at P0's `<N>`. Expected: every package kept (completed, bound-reached or a
behavioural stop, a context overflow included, 26A); each completed
package carries the responding model, non-zero usage and a priced cost, and none reads "cost
unknown" (SC-008).

### P2. Measure and size (US5-13, US5-14)

```bash
uv run swreview benchmark pilot ../benchmarks/pilots/pane-openai/pilot-off-{1,2,3} \
    --smoke ../benchmarks/pilots/pane-openai/smoke-off \
    --smoke ../benchmarks/pilots/pane-openai/smoke-on --jobs <N> \
    --out ../benchmarks/pilots/pane-openai/pilot-measurement.json
```

Expected: the cost gate printed: the size (repetitions, packages, held-out defects, and the growth
units to add, each a core case and its fully clean twin, 24A, `cases.md` 6.5), the deciding rules and `alpha`, whether
the cleared guard decides, both powers, both 5% rates with their Monte Carlo upper bounds, the code
guard's stress case, the estimated cost, and the study's projected wall clock at `--jobs <N>` (owner
decision 36A: per run and for the study, from the pilot's off-arm times and the on arm's ratio from
P0, beside the mean tokens per minute of one review); the never-detected held-out defects each listed
with the findings on their parts or documents. The file holds `"approval": {"approved": false,
"approved_at": null}` and, in `sizing`, `pilot_packages`, the packages the paid pilot ran, and the `growth_units` the
size needs, and `jobs` with the projection. The size was searched over the grown layout already, so nothing is re-measured and no
second pilot is paid for (RF-40). `benchmark pilot` refuses an existing `--out`: one study has one
measurement.

### P3. The owner's approval (the cost gate)

The owner reads the printout and edits only the `approval` block: `"approved": true` and the date, on
or before the first study run. The approval covers the printed size, growth units included. To size
at another cap instead, the owner deletes the unapproved file and runs `benchmark pilot ... --cap
<n>` again over the same folders; an approved file is never rewritten.

**Choosing N** (owner decision 36A). The projection is at the `--jobs` given; to project at another,
the owner deletes the unapproved file and runs `benchmark pilot ... --jobs <n>` again, as for another
cap. Choose N so that N times one review's mean tokens per minute (printed with the projection) stays
under the account's tokens-per-minute limit with room, and lower it if P0 or the pilot counted many
rate-limit retries (plan RK-18). N is recorded in every run and changes no measurement
(`provenance.md` 4), but the approved projection assumes it, so P4 runs at the approved `jobs`.

When `growth_units` is above 0, write that many core cases (each with its twin) as case specs, in
the designs `cases.md` 6.5 names, then regenerate and validate (offline scenarios 3 to 5).

Whatever the growth, pack the pilot's run folders once every resume is done (owner decision 28A):

```bash
uv run swreview benchmark pack ../benchmarks/pilots/pane-openai/pilot-off-{1,2,3} \
    ../benchmarks/pilots/pane-openai/smoke-off ../benchmarks/pilots/pane-openai/smoke-on
```

Expected: in each folder every `events.jsonl`, kept packages' and attempts' alike, replaced by its
`events.jsonl.gz`, and one `event-streams.json` naming each with its digest; a folder holding an
attempt with no outcome or an unfinished promotion is refused, naming `benchmark resume`, and nothing
is packed; packing a folder again prints "already packed". Then commit, in one commit, the smoke
and pilot run folders, the approved `pilot-measurement.json` and any grown cases. Every study run below starts
from that commit: the runs of one study must share one commit and a clean tracked tree (`provenance.md` 3.2 and 4). The pilot's own runs may sit at an earlier commit;
they live under `benchmarks/pilots/` and never enter the study's checks (`verdict.md` 7). Compare
refuses a study whose saved sets lack a package the paid pilot ran or hold fewer than the approved growth units
(`verdict.md` 7, refusal 9).

### P4. The study runs and the verdict (US8)

Alternate the arms (ab-harness section 2) for the approved repetitions: `--arm off` with no
change, `--arm on --pane-defaults`, both with the same typed explanation setting, profile, set,
model and effort and the approved `--jobs <N>` (`sizing.jobs`), every one from the approval's commit, each into
`../benchmarks/studies/pane-openai/{off,on}-<n>`; resume any infrastructure failure; score every run.
Commit nothing between repetitions: the study's folders stay untracked, which leaves `tree_dirty`
false, and are committed only after the last repetition is run and scored, since a commit in between
gives the later runs another `commit` and compare refuses the paid study (plan RK-15). After the last
repetition, simulate the noise floor once (RF-53), then compare:

```bash
uv run swreview benchmark noise-floor ../benchmarks/studies/pane-openai/{off,on}-* \
    --pilot ../benchmarks/pilots/pane-openai/pilot-measurement.json \
    --out ../benchmarks/studies/pane-openai/noise-floor.json
uv run swreview benchmark compare ../benchmarks/studies/pane-openai/{off,on}-* \
    --pilot ../benchmarks/pilots/pane-openai/pilot-measurement.json \
    --noise-floor ../benchmarks/studies/pane-openai/noise-floor.json \
    --into ../docs/llm-efficiency-options.md
```

Expected: the pilot runs render as raw rows, read from the measurement's `pilot_runs`, whose arm cell
reads `off (pilot)`, and are in no count; the pane block names the verdict (`quality loss`,
`no 10-point loss` or `inconclusive`) with its reasons, both paired rules on both figures with their
intervals and `alpha`, both guards, the drops, the approval line, the noise floor with its seed and
numpy version (read from the record, never simulated by compare), the settings the arms differed in
(and dropped reasoning as a setting the verdict does not test, while no held-out case takes an answer
turn), and the shown table. Compared twice, the ledger's bytes are identical. Then pack the study's
folders (`uv run swreview benchmark pack ../benchmarks/studies/pane-openai/{off,on}-*`, as in P3), and
commit them, the noise-floor record and the regenerated document together;
`test_committable_paths.py` passes over the committed study and pilot folders, every packed stream
decompressing to the bytes its recorded digest names (RF-84), and a re-score or a report built from
another checkout reads the packed streams as the plain ones.

### P5. The private slice (23A)

With the real profile and the private set, outside the repository:
`--study pane_defaults_private --arm off|on`, then `compare` with `--out` outside the repository.
Expected: its own row, `slice: private`, every interval shown, `verdict: null` with the reason "private
slice (23A)"; compare refuses writing it into the committed document.
