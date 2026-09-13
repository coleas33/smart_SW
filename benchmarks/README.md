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
│   ├── exceptions.json     # accepted interference exceptions bound to geometry
│   └── notes.md            # what was seeded, baseline time, results
├── native/<name>/          # SOLIDWORKS files used to produce native packages on the workstation
├── answer_keys/<name>.json # known defects and correct conditions
└── sets/pilot.json         # which packages belong to a run and which are held out
```

Rule: `benchmarks/answer_keys/` is never passed to the reviewer. The package loader refuses
any path under it, and only `swreview benchmark score` reads it.
