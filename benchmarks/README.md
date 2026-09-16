# benchmarks

Benchmark packages and answer keys for the design review pilot.

```text
benchmarks/
├── packages/<name>/        # one review package per design
│   ├── package.json        # EvidencePackage (contracts/ir.schema.json), written by ingest or the extractor
│   ├── manifest.json       # vault path, version, revision, configuration per document
│   ├── bom.csv             # item, part number, description, quantity, configuration
│   ├── drawings/*.pdf      # exported drawing sheets
│   ├── geometry/*.step     # optional exported geometry
│   ├── native/             # optional extractor output (package.json, meshes/, captures/)
│   │   ├── suppress-plan.json  # written by `rms suppress-plan`, read by `suppress-test`
│   │   ├── suppress-test.log   # the gate members the suppress-test run actually called
│   │   └── rms_exceptions.json # the checker's flat waiver file, read by `exceptions accept-rms`
│   ├── exceptions.json     # accepted exceptions bound to geometry or to the feature tree
│   └── notes.md            # what was seeded, baseline time, results
├── native/<name>/          # SOLIDWORKS files used to produce native packages on the workstation
├── answer_keys/<name>.json # known defects and correct conditions
└── sets/pilot.json         # which packages belong to a run and which are held out
```

Rule: `benchmarks/answer_keys/` is never passed to the reviewer. The package loader refuses
any path under it, and only `swreview benchmark score` reads it.

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
