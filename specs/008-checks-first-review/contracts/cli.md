# Command-Line Additions

## `swreview` (Python)

| Command | Arguments | Effect |
|---------|-----------|--------|
| `swreview benchmark replay RUN_DIR` | `--pane-defaults/--no-pane-defaults` (default on), `--lever NAME`..., `--payload-slimming`, `--history-pruning`, `--prune-after N`, `--standards-profile PATH`, `--json` | Replays a review run folder through the current code twice - as recorded, and with the requested settings - with a scripted provider, and prints per-round and total input tokens, the finding comparison and, from User Story 4, the regrouped estimate (`replay.md`). No key, no network, no SOLIDWORKS; writes nothing into `RUN_DIR`. **Exit 1** on a refusal (one sentence) or a lost finding (after printing); **exit 2** on a usage error. Payload: the `ReplayReport` |
| `swreview review` | `--pane-defaults` (new), `--payload-slimming` (new), `--history-pruning` (new), `--prune-after N` (new); `--lever prerun_checks`, `--lever parallel_tool_calls` (existing) | Every change is **off** unless asked. `--pane-defaults` applies exactly `pane_defaults(provider)` - checks first, parallel calls for OpenAI, payload slimming, history pruning after two rounds - the settings a pane review runs with; the explicit switches add to it or, without it, turn one change on. The session records what ran (`efficiency`, `model_view`) |
| `swreview benchmark run` | unchanged | Stays all-off for the model view, so its arms compare with every recorded ledger row |

One resolver, `_review_settings(provider, *, pane_defaults, lever, payload_slimming,
history_pruning, prune_after) -> (EfficiencySettings, ModelViewSettings)`, serves `review` and
`benchmark replay`:

1. Start from `pane_defaults(provider)` when asked, else `(EfficiencySettings(), MODEL_VIEW_OFF)`.
2. Add the named levers through `efficiency_from_levers` (the pane's own levers included), so every
   existing refusal applies - `--pane-defaults --lever coverage_stop` is refused by `GATED_ALONE`,
   `--lever parallel_tool_calls --provider gemini` by the Gemini rule.
3. Turn on `--payload-slimming` and `--history-pruning` when given.
4. `--prune-after N` sets the prune age; **exit 2** when N < 1 or when pruning is not on (neither
   `--history-pruning` nor `--pane-defaults`), naming the flags.

## What a review run folder holds

```
<run_dir>/
├── session.json          gains optional model_view and folded_families; steps gain optional sizes
├── events.jsonl          unchanged event types
├── report.md             a folded family renders in one collapsed subsection; "Largest tool results"
├── attention.json        a folded family is one row (family, rule_count)
├── package.json          in the pane: the live interference rows, persisted (checks-first.md section 3);
│                         on the command line: a merged copy, only when live detection ran
└── tool-results/         NEW: step-<index>.json, the full payload of every recorded step
    └── step-0.json …
```

## Two things this command line deliberately does not offer

| Not offered | Why |
|---|---|
| `--no-checks-first` and other `--no-...` switches on `review` | The command line is off by default; the way to compare is to leave a change out (research R2.15) |
| A replay that regroups silently | The regrouped figure is printed separately, with its assumption, beside the strict one (research R2.43) |
