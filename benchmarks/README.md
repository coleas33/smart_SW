# benchmarks

The design review eval's cases: fictional review packages, their answer keys, the engineer's
scripted answers and the sets that name them (`specs/014-design-review-eval/contracts/cases.md`).
A case's id names its package folder, its key and its case file alike (`cases.md` 2).

```text
benchmarks/
├── packages/<name>/        # one review package per case: package.json and meshes/*.glb
├── answer_keys/<name>.json # known defects and correct conditions, key format 2 (specs/014-design-review-eval/contracts/answer-key.md)
├── case_files/<name>.json  # the engineer's scripted answers, for the four cases whose questions are answered
├── sets/
│   ├── committed.json      # the pane study's set: every generated case but cover-blind-tap
│   ├── pilot.json          # the lever studies' smoke set: cover-blind-tap alone
│   └── pane-smoke.json     # the pane study's smoke set: committed.json's kalo-1 and kalo-fit-1
├── packages/bracket-assy/  # the test suite's native-package slot, placed per machine (below)
│   └── native/             # extractor output (package.json, meshes/, captures/)
│       ├── suppress-plan.json  # written by `rms suppress-plan`, read by `suppress-test`
│       ├── suppress-test.log   # the gate members the suppress-test run actually called
│       └── rms_exceptions.json # the checker's flat waiver file, read by `exceptions accept-rms`
└── native/rms-part/        # RECIPE.md: the SOLIDWORKS part to model for the suppress-test workflow
```

| Files | For | Read by |
|---|---|---|
| `packages/<name>/` | what the reviewer reviews | the reviewer, through the package loader |
| `answer_keys/<name>.json` | what a review is graded against | the scorer's key reader only: `swreview benchmark score` and `benchmark set-summary` |
| `case_files/<name>.json` | the answers a review's questions get | the answer driver only |
| `sets/*.json` | which cases a run reviews, each entry naming its key | `benchmark run`, `score`, `compare`, the report and `set-summary` |

Rule: `benchmarks/answer_keys/` is never passed to the reviewer. The package loader refuses
any path under it, and only the scorer's key reader reads it; a set refuses a key or a case file
inside a package folder, which the reviewer reads whole.

## The generated cases

Every file under `packages/`, `answer_keys/`, `case_files/` and `sets/` is written by the
generator from the case specs in `reviewer/tests/benchmark_cases/`
(`specs/014-design-review-eval/contracts/generator.md`) and is never edited by hand: change the
spec and regenerate. From `reviewer/`:

```bash
uv run python -m tests.benchmark_cases.generate
git status --porcelain -- ../benchmarks ':(exclude)../benchmarks/packages/bracket-assy'   # expect nothing
```

The generator prints each path it wrote, then each stale file, one under those folders that no
spec writes, and exits 1 while one remains; it never deletes. A regeneration rewrites every file
to identical bytes, so the `git status` check lists nothing, and
`reviewer/tests/unit/test_benchmark_case_generator.py` fails when a fresh render and the committed
tree differ by a byte or a file.

Hand-kept, and never written by the generator: this `README.md`, `answer_keys/rms-part.json` (a
key-only key, the expected result of `native/rms-part/`) and `native/rms-part/RECIPE.md`.
`packages/bracket-assy/` is the test suite's native-package slot (`reviewer/tests/conftest.py`),
placed per machine and named by no set: the generator neither writes nor scans it, which is why
the `git status` check above leaves it out.

## The validation and the set summary

`reviewer/tests/unit/test_benchmark_cases_reachable.py`, in the default suite, proves offline
that every case of `committed.json` and `pilot.json` grades what its key says
(`cases.md` 7): code-only calls detect exactly the code-produced defects and nothing unkeyed; a
correct reviewer detects every model-produced defect at its expected status, with every lever off
and with the pane's defaults; and no decoy call credits, flags or clears a keyed defect. A case
that fails it cannot be committed. From `reviewer/`:

```bash
uv run swreview benchmark set-summary ../benchmarks/sets/committed.json
```

prints, per judgement family, the held-out model-produced defects, those with a clean twin, the
code-produced guards, the tuned-on items and the anchors and analyst-found defects covered; then
the total against the floor of 34, the largest design's share and every stale held-out item
(`cases.md` 8).

## Held out, tuned-on and the stamp

A held-out item's key records the digests of the system prompt, the checklist and the tool
descriptions it was held out against (`held_out_against`), written from
`reviewer/tests/benchmark_cases/stamps.py` `CURRENT`. When any of the three changes,
`reviewer/tests/unit/test_held_out_stamps.py` fails listing every held-out item: in that commit,
move every held-out item the change cites to tuned-on in its case spec, set `stamps.CURRENT` to
the new digests and regenerate (`cases.md` 5).

## Private sets

A private set, its keys and its case files live outside the repository and name their paths
absolutely; none is ever committed (`cases.md` 4.6).

## The suppress-test workflow

Every Resilient Modeling rule but one is answered from the dumped package. The exception is
`rms.detail.individually_suppressible`: whether each Detail feature can be suppressed on its
own without breaking the rebuild is a question only the live document can answer, so it stays
*unresolved* coverage - not a pass - until a `suppress-test` run has been appended to the
package. That run is the only mutation this product performs, which is why it is split in
two: the reviewer decides **what** may be touched, the extractor does only **that**.

The three files this workflow adds live in `native/`, not beside it: the plan is written
next to the package it planned from, and `suppress-test` writes its log into `--out`, which
is that same package directory.

On the workstation, with the document open in SOLIDWORKS 2024. Run the whole block from
`reviewer/` - `uv run swreview` needs the project that defines it as the working directory,
there is no `pyproject.toml` at the checkout root, and `swreview-extract` is on PATH and
does not care - so every benchmarks path below is written `../benchmarks/...`:

```powershell
cd reviewer

# 1. Dump. The feature tree and the equations are on by default.
swreview-extract dump --out ../benchmarks/packages/<name>/native

# 2. Plan. Reads features[], writes the review configuration, the Detail group and the
#    Detail content features in tree order. Refuses when the document has no features[]
#    rows or no Detail group: an empty plan reads as "nothing to suppress", not "we never
#    looked".
uv run swreview rms suppress-plan --package ../benchmarks/packages/<name>/native --document <doc id>

# 3. Test. Suppresses one planned feature at a time, rebuilds, records what broke, restores
#    the tree. Refuses before touching anything without the acknowledgement, on unsaved
#    changes, on a rolled-back feature, on a different active configuration, on a non-zero
#    starting error count, or when the live walk no longer matches the package (dump again).
swreview-extract suppress-test --doc <part> --plan ../benchmarks/packages/<name>/native/suppress-plan.json --acknowledge-rebuild --out ../benchmarks/packages/<name>/native

# 4. Close the document WITHOUT saving. It is modified in memory; the next run refuses
#    while it has unsaved changes.

# 5. Grade. The rule now reads the appended rms_suppress_test rows.
uv run swreview check rms --package ../benchmarks/packages/<name>/native --scope part

# 6. Optional: import the checker's flat waiver file `{ "<rule_id>": "<reason>" }` against
#    the run. Only demonstrated `fail` rules are acceptable; one invalid id writes nothing.
uv run swreview exceptions accept-rms <run_dir> --package ../benchmarks/packages/<name>/native --file ../benchmarks/packages/<name>/native/rms_exceptions.json --by <name>
```

`suppress-test.log` in the package directory holds the distinct guard members the run
called - the evidence that the exemption set stayed at its two members and that nothing
saved.

`benchmarks/native/rms-part/RECIPE.md` is the hand-built fixture for this workflow: what to
model, which rule each seeded defect trips, and the exact commands for quickstart Scenarios 3
and 4. Its expected result is `benchmarks/answer_keys/rms-part.json`, which is subject to the
same rule as every other answer key above.

## Timing the checks without a seat

`reviewer/tests/perf/test_rms_perf.py` times `swreview check rms` over a builder-generated
100-part package, so the "seconds, not minutes" claim has a number behind it on any machine.
It is not collected by the default run; `uv run pytest -m perf -s` from `reviewer/` runs it
and prints the measured seconds.
