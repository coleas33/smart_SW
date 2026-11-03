# Contract: Timing

Normative for `benchmark/timing.py`, `swreview timing`, `POST /sessions/{chat_id}/timing` and
the ledger's median column. The four human inputs and the derived net are the feature 001
`Timing` shape; nothing here changes it except the `ge=0` on `baseline_minutes` its schema
already states.

*Amended 2026-11-01 (owner decisions 183A and 184A; spec FR-036; tasks T065 to T068):* the human
inputs are six. `Timing` gains `setup_minutes` and `review_by_hand_minutes`, each a number of at
least 0 or not recorded, both left out of `session.json` while not recorded, so a session written
before them loads and keeps its bytes, but for a net derived from the four earlier inputs alone,
which now reads unknown and is saved as null; the review-session contract names them in `properties`
only. What each counts is 184A's: setup is this design's own setup only - preparing the package,
opening the assembly, attaching drawings, starting the review and any rerun - and a sitting's
software update is reported apart, as a pilot cost; corrections count inside verification or
false-alarm handling; the review by hand is the checking the engineer still does on what the
tool did not reach; no minute is counted twice. The public names are `setup` and `by_hand`
(`--setup` and `--by-hand` on the command line), beside the four in `TIMING_INPUTS`.

## 1. One writer

```python
def record_timing_at(
    session_path: Path | str,
    *,
    baseline: float | None = None,
    supervision: float | None = None,
    verification: float | None = None,
    false_alarms: float | None = None,
    setup: float | None = None,        # amended 2026-11-01, 183A
    by_hand: float | None = None,      # amended 2026-11-01, 183A
) -> Timing
```

Loads the session at `session_path`, applies the inputs that are not `None` through
`Timing.replace`, saves, returns the recomputed `Timing`. Nothing is written when validation
refuses. `record_timing(run_dir, package_id, ...)` is `record_timing_at(run_dir / package_id /
"session.json", ...)` and keeps its six tests unchanged. Net saved minutes is derived by the
model and is not a parameter on any path.

*Amended 2026-11-01 (owner decision 183A):* the assisted minutes are setup, supervision,
verification, false-alarm handling and the review by hand together (`Timing.assisted_minutes`,
which the scorecard reads too), and the net is the baseline less them: unknown while the
baseline, setup or the review by hand is not recorded, as it was without a baseline, and a
recorded 0 is a value. `record_timing`'s six tests keep their figures by recording setup and
the review by hand as 0, deliberately, with 183A named as the reason; they are no longer
unchanged. `Timing.replace` takes the names from the model's fields, since a dump that leaves out
an input not recorded would refuse it.

## 2. `swreview timing <run_dir>`

| Argument | Meaning |
|---|---|
| `<run_dir>` | A folder holding `session.json` directly: a pane review, a CLI review, an RMS check or a standards check folder |
| `--baseline M`, `--supervision M`, `--verification M`, `--false-alarms M`, `--setup M`, `--by-hand M` (the last two *amended 2026-11-01, owner decision 183A*) | Minutes; each optional; an omitted one keeps its value |
| `--json` | The payload instead of the lines |

Writes `session.json`, then re-renders `report.md` and `attention.json` through
`rerender_run_folder`, which loads `package.json` when the folder holds one and re-prepends the
standards verdict header when `check.json` names that family and names the folder's session
(*amended 2026-10-19, owner decision 139A*). Payload: `{run_dir, session_file,
report_file, timing}`; lines: the four values and `net saved: <value>`. *Amended 2026-11-01
(owner decision 183A):* the six values, then `net saved: <value>`, built by one helper that
`benchmark time` shares; the report's Timing section prints setup and the review by hand always,
`unknown` when not recorded as the baseline's line does, so a reader sees why a net is unknown.

*Amended 2026-10-19 (owner decision 139A):* the header belongs to the standards check's own
session, the one its `check.json` names, which is the rule that already decides whether the
report names a model (132A). A review that claimed the folder - the check's session rotated aside
by `POST /sessions`, or written over by `swreview review --out` - wrote its report with no header,
and its re-render has none (research R6).

Exit-1 conditions, each naming what was wrong:

| Condition | Message names |
|---|---|
| `<run_dir>/session.json` absent or unreadable | the path; a benchmark run root (no session at the top) additionally names `swreview benchmark time` as the command for it |
| any input below zero | the field, through the model's own validation |
| `--json` payload asked to carry a net | not possible: there is no such option |

## 3. `POST /sessions/{chat_id}/timing`

| | |
|---|---|
| Body | `{baseline?, supervision?, verification?, false_alarms?, setup?, by_hand?}` - numbers or null; every key optional (`setup` and `by_hand` *amended 2026-11-01, owner decision 183A*) |
| Response | `200 {timing}` - the recomputed `Timing`, net included |
| 400 `InvalidTiming` | a key that is not one of the six (including `net_saved_minutes`), a non-number, or a negative value; the message names the key |
| 404 `UnknownChat` | |
| 409 `TurnRunning` / `SessionFailed` | as `disposition` |

Writes the **live** session the run holds and saves it, re-renders `report.md` and
`attention.json` with the package the run holds, and emits no event (timing is not a review
event). A review may be timed after `session.ended`; check runs register no chat and are timed
from the command line.

*Amended 2026-11-03 (cycle 18; research R12):* the Review page's minutes form is this route's page
caller, every rule above unchanged. It shows on a live review once a turn of it has ended, is off
while a turn runs and is absent on a read-only restore. Save posts all six keys, through the
pane's proxy, which counts the call as starting no turn: `null` for a blank field, which keeps
what is recorded; the number typed; and text that is not a number as typed, which this route
refuses as `InvalidTiming`. The page prints nothing of the `200`'s `Timing`: after it, one line,
the words file's `labels.timing_form.saved`; after a refusal, its class's sentence from
`labels.errors`, never its message, which names a refused figure. The typed figures stay in the
fields, and reach no other text of the page. Since cycle 18's Tier 2 review (research R12): the
form goes once the backend takes the review's minutes no more - another backend replaced the one
that held it, or its turn failed - where `swreview timing` is the way; a `409 TurnRunning`, which
this route answers for a moment after the turn's `session.ended` while the backend writes the
report, is tried once more a second later; and what was typed on a review and not saved stays in
page memory, as the questions' drafts do, and comes back when that review is shown again.

*Amended 2026-11-03 (cycle 20; research R14):* Save is off while any field is blank, empty or
spaces only, so the page posts all six, 0 typed for none, and never `null`; a line from the words
file under the form's heading, `labels.timing_form.all_six`, says to type all six. This route's
rules are unchanged: `null` still keeps what is recorded.

## 4. The ledger column

`adoption.METRICS["median_net_saved_minutes"]` reads `scorecard.aggregate.median_net_saved_minutes`
per run. The decision row gains `median_net_saved_minutes: OffOn`, rendered as "Median net
saved minutes off -> on" with `n=` the runs that carried timing. It is reported, never gated:
`decide()` names its metrics and this is not one. The per-design median keeps printing in
`scorecard.md`. `docs/llm-efficiency-options.md`'s ledger block and `ab-harness.md` sections 5
and 10.8 are regenerated and amended in the same change.
