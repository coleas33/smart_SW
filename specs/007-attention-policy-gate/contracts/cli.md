# Command-Line Additions

## `swreview` (Python)

| Command | Arguments | Effect |
|---------|-----------|--------|
| `swreview timing <run_dir>` | `--baseline M`, `--supervision M`, `--verification M`, `--false-alarms M`, `--json` | Records the four human minute inputs on `<run_dir>/session.json` through `record_timing_at`, the one writer `benchmark time` and the backend route also use, and re-renders `report.md` and `attention.json` through `rerender_run_folder`. Net saved minutes is derived and never an argument. **Exit 1** when the folder holds no session (naming the path, and naming `benchmark time` for a benchmark run root) or an input is below zero (naming the field); nothing is written on refusal. Payload `{run_dir, session_file, report_file, timing}`. |
| `swreview attention <run_dir>` | `--json` | Reads `<run_dir>/session.json`, ranks it with the current policy and prints the policy version, the rows in order with their reasons and key values, the not-amplified line and the coverage block. **Writes nothing** (a hash of the folder before and after is the test), constructs no provider and reads no key. Exit 1 when the folder holds no session. Payload `{run_dir, session_file, attention}` where `attention` is the `Ranking` JSON. |
| `swreview review` | `--standards-profile <yaml>` (new, optional); `--lever procedural_gate` (new value) | With a profile, the standards checks are offered to the review and, with the gate on, run in the pre-run; without one, the gate reports standards as not evaluated. |

`swreview disposition` and `swreview exceptions accept-rms` / `accept-standards` re-render
through `rerender_run_folder` too, so a disposition on a standards folder no longer deletes its
verdict header and a re-render no longer loses the package's component names.

## What a run writes, and where

```
<run_dir>/
├── session.json      unchanged shape; timing inputs recorded here
├── report.md         gains "## Start here" above "## Findings"
├── attention.json    NEW: the ranking record (contracts/attention.md section 4)
└── check.json        (check folders only) unchanged
```

## Two things this command line deliberately does not offer

| Not offered | Why |
|---|---|
| A `--top N` or a `--class` filter on `attention` | The rule amplifies and never filters; a reader that showed a different top five from the report would be a second policy |
| A `--net` input on `timing` | Net saved minutes is derived; an accepted net is the one number the pilot must never type |
