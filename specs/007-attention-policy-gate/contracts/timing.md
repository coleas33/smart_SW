# Contract: Timing

Normative for `benchmark/timing.py`, `swreview timing`, `POST /sessions/{chat_id}/timing` and
the ledger's median column. The four human inputs and the derived net are the feature 001
`Timing` shape; nothing here changes it except the `ge=0` on `baseline_minutes` its schema
already states.

## 1. One writer

```python
def record_timing_at(
    session_path: Path | str,
    *,
    baseline: float | None = None,
    supervision: float | None = None,
    verification: float | None = None,
    false_alarms: float | None = None,
) -> Timing
```

Loads the session at `session_path`, applies the inputs that are not `None` through
`Timing.replace`, saves, returns the recomputed `Timing`. Nothing is written when validation
refuses. `record_timing(run_dir, package_id, ...)` is `record_timing_at(run_dir / package_id /
"session.json", ...)` and keeps its six tests unchanged. Net saved minutes is derived by the
model and is not a parameter on any path.

## 2. `swreview timing <run_dir>`

| Argument | Meaning |
|---|---|
| `<run_dir>` | A folder holding `session.json` directly: a pane review, a CLI review, an RMS check or a standards check folder |
| `--baseline M`, `--supervision M`, `--verification M`, `--false-alarms M` | Minutes; each optional; an omitted one keeps its value |
| `--json` | The payload instead of the lines |

Writes `session.json`, then re-renders `report.md` and `attention.json` through
`rerender_run_folder`, which loads `package.json` when the folder holds one and re-prepends the
standards verdict header when `check.json` names that family. Payload: `{run_dir, session_file,
report_file, timing}`; lines: the four values and `net saved: <value>`.

Exit-1 conditions, each naming what was wrong:

| Condition | Message names |
|---|---|
| `<run_dir>/session.json` absent or unreadable | the path; a benchmark run root (no session at the top) additionally names `swreview benchmark time` as the command for it |
| any input below zero | the field, through the model's own validation |
| `--json` payload asked to carry a net | not possible: there is no such option |

## 3. `POST /sessions/{chat_id}/timing`

| | |
|---|---|
| Body | `{baseline?, supervision?, verification?, false_alarms?}` - numbers or null; every key optional |
| Response | `200 {timing}` - the recomputed `Timing`, net included |
| 400 `InvalidTiming` | a key that is not one of the four (including `net_saved_minutes`), a non-number, or a negative value; the message names the key |
| 404 `UnknownChat` | |
| 409 `TurnRunning` / `SessionFailed` | as `disposition` |

Writes the **live** session the run holds and saves it, re-renders `report.md` and
`attention.json` with the package the run holds, and emits no event (timing is not a review
event). A review may be timed after `session.ended`; check runs register no chat and are timed
from the command line.

## 4. The ledger column

`adoption.METRICS["median_net_saved_minutes"]` reads `scorecard.aggregate.median_net_saved_minutes`
per run. The decision row gains `median_net_saved_minutes: OffOn`, rendered as "Median net
saved minutes off -> on" with `n=` the runs that carried timing. It is reported, never gated:
`decide()` names its metrics and this is not one. The per-design median keeps printing in
`scorecard.md`. `docs/llm-efficiency-options.md`'s ledger block and `ab-harness.md` sections 5
and 10.8 are regenerated and amended in the same change.
