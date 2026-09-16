"""`swreview benchmark compare`: N run folders in, the results ledger out (T041).

**The ledger is a rendering of N `scorecard.json` files, never a hand-kept table.** Typed
numbers go stale and cannot be audited, which is what the results table at the end of
`docs/llm-efficiency-options.md` was before this module existed.

Three things this module is, in order of weight:

1. **A validator (RK-20), which is the point of the command.** Two independent writers
   describe every run: `session.efficiency`, written by the runner from the resolved
   `EfficiencySettings`, and the **run provenance record**, written by `cli.py` from the
   `--lever`, `--study`, `--arm` and `--rep` options actually typed. A run whose two
   records disagree is **refused**, and the message names the field. One writer could
   only ever agree with itself.
2. **A renderer with one source per column.** No number is computed twice: the token
   counts are `session.usage.totals` verbatim, `uncached in` and the cached share are the
   scorecard's own derivation read through, `tool calls` is `len(session.steps)` and is
   never conflated with `rounds`, and the four provenance columns are the provenance
   record's.
3. **The reader that asks `adoption.decide` for the `Decision` column** and never types
   one. The owner's approval is `owner_signed_off`, a separate field this module never
   *computes*: `carry_sign_offs` copies it, and `owner_signed_off_at`, off the committed
   ledger onto the matching row before rendering, so the hand-written sign-off the owner
   put there survives the next regeneration instead of being reset to `no`.

**`compare` never contacts a provider, never starts a run and reads no answer key.** It
reads the provenance record, `session.json`, `events.jsonl` and `scorecard.json`, so
Principle VI and FR-025 are untouched.

What is refused, and what is merely null:

- No `efficiency` on a session at all: **refused** - the run predates the flag carrier
  and cannot be attributed to an arm.
- The two records disagreeing, on the settings, the provider, the model, the effort, the
  saved set copy, or the arm against the studied lever's flag: **refused**, naming it.
- Two runs of one study differing in commit, effort, set file or checklist: **refused**,
  naming the field. There is no declared exception; lever 2's off arm is its flag off,
  not an earlier commit.
- No provenance record at all: **not** refused. The row renders with `lever`, `arm`,
  `rep` and `commit` null, because a run made before the convention existed is still a
  real run.
- A study that can produce no recall number, or one carrying the too-small-set override:
  the **decision row** is refused (`decision: null` with the reason beside it) and the
  **raw rows still render**. `adoption.decide` owns that rule; the command exits non-zero.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from swreview.agent.providers import CACHED_SHARE_PUBLISHABLE
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.agent.settings import LEVER_NAMES
from swreview.benchmark.adoption import (
    BASELINE,
    METRICS,
    ArmRun,
    Decision,
    OffOn,
    Verdict,
    decide,
    metric,
    off_on,
)
from swreview.benchmark.runner import REPO_ROOT, RunProvenance, load_provenance, sha256_of
from swreview.benchmark.scorecard import UNKNOWN, PackageScore, Scorecard
from swreview.findings import ReviewModel
from swreview.report.session import ReviewSession, load_session

LEDGER_SCHEMA = "1.0"
LEDGER_JSON = "ledger.json"
LEDGER_MD = "ledger.md"
SCORECARD_FILE = "scorecard.json"
SAVED_SET_FILE = "benchmark-set.json"

LEDGER_BEGIN = "<!-- ledger:begin -->"
LEDGER_END = "<!-- ledger:end -->"
"""The markers `--into` writes between, so a committed document cannot drift from the
runs it claims to summarize (T045)."""

BASELINE_ARM = "baseline"
NO_LEVER = "none"

STUDIES_DIR = REPO_ROOT / "benchmarks" / "studies"
"""Where the run directories the committed ledger is rendered from live.

The `## Results` table in `docs/llm-efficiency-options.md` is a rendering of exactly these
folders, and `--check` is what stops the document drifting from them (T045). The directory
does not exist until the first study is run, and an empty ledger is the honest rendering of
a feature that has measured nothing yet."""

LEVER_COUNTERS: dict[str, str] = {
    "trim_tool_descriptions": "tool-name histogram (arrives with lever 2)",
    "tool_tiers": "unresolved because withheld (arrives with lever 4)",
    "prompt_cache_key": "cache miss reasons and cache_missed_tokens (arrives with lever 3)",
    "gemini_explicit_cache": "cached-content hit rate (arrives with lever 3, Gemini)",
    "prerun_checks": "check_fit and check_axial_stack call counts (arrives with lever 5)",
    "parallel_tool_calls": "tool calls beside round trips",
    "coverage_stop": "stop fire rate (arrives with lever 7)",
    "package_reuse": "dump wall clock, cold against reused (workstation harness)",
    "lazy_meshes": "bodies_swept per arm (workstation harness)",
    "carry_over_rms": "carried against re-run counts (workstation harness)",
    NO_LEVER: "none: a baseline study has no lever to counter",
}
"""The number **this** lever's gate needs and no other's (ab-harness section 6).

Every lever is named here even when the counter itself lands with that lever's own task,
so the column says *which* number is missing rather than going blank. Only lever 6's is
computable from what the scorecard and the session already carry."""

COUNTER_METRIC: dict[str, str] = {"parallel_tool_calls": "tool_calls"}
"""The counters that are already a metric in `adoption.METRICS`; the rest render unknown
until their lever lands."""


class CompareError(ValueError):
    """A run, or a pair of runs, that may not be placed in a comparison."""


class RunRow(ReviewModel):
    """One row per run **per package**: the raw ledger, with one source per column."""

    run: str
    run_dir: str
    commit: str | None
    lever: str | None
    arm: str | None
    rep: int | None
    provider: str | None
    model: str | None
    effort: str | None
    package_id: str
    held_out: bool
    other_levers_on: list[str]
    input_tokens: int | None
    cached_input_tokens: int | None
    uncached_input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    tool_result_input_tokens: int | None
    total_tokens: int | None
    rounds: int | None
    tool_calls: int
    cached_input_share: float | None
    wall_clock_s: float | None
    seconds_to_first_finding: float | None
    valid_findings: int
    missed_known_defects: int
    false_alarms: int
    unresolved_count: int
    coverage_bucket_mix: dict[str, int]
    set_too_small_override: bool


class LeverCounter(ReviewModel):
    """The lever-specific counter column: the name is always there, the numbers may not
    be."""

    name: str
    off: float | None
    on: float | None


class LeverDecision(ReviewModel):
    """One row per lever per provider and model: the summary the owner reads."""

    lever: str
    provider: str | None
    model: str | None
    commit_off: str | None
    commit_on: str | None
    reps: int
    other_levers_on: list[str]
    input_tokens: OffOn
    cached_input_tokens: OffOn
    output_tokens: OffOn
    reasoning_or_thoughts: OffOn
    total_tokens: OffOn
    round_trips: OffOn
    tool_calls: OffOn
    wall_clock_s: OffOn
    dump_wall_clock_s: OffOn
    valid_findings: OffOn
    missed_known_defects: OffOn
    false_alarms: OffOn
    unresolved_count: OffOn
    recall_held_out: OffOn
    worst_case_defects_lost: int | None
    """`adoption.Verdict.worst_case_defects_lost`: `0` where the comparison ran and found
    nothing, `None` where it never ran. Rendered through `_count`, so an absent number
    reads `unknown` and never `0` (RK-1)."""

    lost_defect_ids: list[str]
    lever_counter: LeverCounter
    decision: Decision | None
    decision_reason: str
    owner_signed_off: bool = False
    """**Never computed by `compare`** (FR-027). The owner writes it by hand into the
    committed `ledger.md` once the row has been read, and no flag default changes until
    they do. `carry_sign_offs` copies what is already committed onto the freshly computed
    row, which is what makes the hand edit survive a regeneration."""

    owner_signed_off_at: date | None = None
    """The date beside the sign-off, written and carried by the same hand and the same
    rule. Rendered in its own column so FR-027's "with a date" has somewhere to live."""
    run_dirs: list[str]


class Ledger(ReviewModel):
    ledger_schema: str = LEDGER_SCHEMA
    runs: list[RunRow]
    levers: list[LeverDecision]


@dataclass(frozen=True)
class _LoadedRun:
    """One validated run directory, held once so nothing is read twice."""

    run: str
    run_dir: Path
    provenance: RunProvenance | None
    scorecard: Scorecard
    sessions: dict[str, ReviewSession]

    @property
    def tool_calls(self) -> int:
        return sum(len(session.steps) for session in self.sessions.values())


# --- reading and validating one run directory ------------------------------------


def _load_run(run_dir: Path) -> _LoadedRun:
    scorecard_path = run_dir / SCORECARD_FILE
    if not scorecard_path.is_file():
        raise CompareError(
            f"{run_dir}: no {SCORECARD_FILE}; run `swreview benchmark score` on this run "
            f"before comparing it"
        )
    scorecard = Scorecard.model_validate_json(scorecard_path.read_bytes())
    provenance = load_provenance(run_dir)

    sessions: dict[str, ReviewSession] = {}
    for score in scorecard.per_package:
        session_path = run_dir / score.package_id / SESSION_FILE_NAME
        if not session_path.is_file():
            raise CompareError(f"{run_dir}: {score.package_id} has no {SESSION_FILE_NAME}")
        session = load_session(session_path)
        _check_session(run_dir, score.package_id, session, provenance)
        sessions[score.package_id] = session

    _check_saved_set(run_dir, provenance)
    return _LoadedRun(
        run=run_dir.name,
        run_dir=run_dir,
        provenance=provenance,
        scorecard=scorecard,
        sessions=sessions,
    )


def _check_session(
    run_dir: Path, package_id: str, session: ReviewSession, provenance: RunProvenance | None
) -> None:
    """The RK-20 cross-check, per package, between the two independent writers."""
    if session.efficiency is None:
        raise CompareError(
            f"{run_dir} / {package_id}: session.json carries no efficiency; this run "
            f"predates the flag carrier and cannot be attributed to an arm"
        )
    if provenance is None:
        return

    recorded = provenance.efficiency.model_dump()
    written = session.efficiency.model_dump()
    differing = sorted(name for name in recorded if recorded[name] != written[name])
    if differing:
        raise CompareError(
            f"{run_dir} / {package_id}: session.efficiency and the provenance record "
            f"disagree on {', '.join(differing)}"
        )

    info = session.provider_info
    if info is not None:
        for field, recorded_value, written_value in (
            ("provider", provenance.provider, info.provider),
            ("model", provenance.model, info.model),
            ("effort", provenance.effort, info.effort_mapping.requested),
        ):
            if recorded_value != written_value:
                raise CompareError(
                    f"{run_dir} / {package_id}: session.json and the provenance record "
                    f"disagree on {field}: {written_value!r} against {recorded_value!r}"
                )

    _check_arm(run_dir, package_id, session.efficiency.model_dump(), provenance)


def _check_arm(
    run_dir: Path, package_id: str, flags: dict[str, bool], provenance: RunProvenance
) -> None:
    """The arm against the studied lever's own flag - a second clause, not a narrowing.

    A baseline run has no lever under test and is exempt; it is checked instead as every
    flag false (contracts/ab-harness.md section 3).
    """
    if provenance.arm == BASELINE_ARM or provenance.lever == NO_LEVER:
        on = sorted(name for name in LEVER_NAMES if flags[name])
        if on:
            raise CompareError(
                f"{run_dir} / {package_id}: a baseline run has every flag off, but "
                f"{', '.join(on)} is on"
            )
        return
    if provenance.arm is None:
        return
    if provenance.lever not in flags:
        raise CompareError(f"{run_dir}: provenance names an unknown lever {provenance.lever!r}")
    if flags[provenance.lever] != (provenance.arm == "on"):
        raise CompareError(
            f"{run_dir} / {package_id}: the provenance record says arm "
            f"{provenance.arm!r} while session.efficiency has {provenance.lever} "
            f"{flags[provenance.lever]}"
        )


def _check_saved_set(run_dir: Path, provenance: RunProvenance | None) -> None:
    """The saved `benchmark-set.json` against the digest the record carries.

    Only when the copy is there: the workstation harness writes a run directory of the
    same shape but has no benchmark set to copy (FR-030a), and a check cannot be run on
    a file that does not exist.
    """
    saved = run_dir / SAVED_SET_FILE
    if provenance is None or not saved.is_file():
        return
    digest = sha256_of(saved)
    if digest != provenance.set_digest:
        raise CompareError(
            f"{run_dir}: the saved {SAVED_SET_FILE} does not match the provenance "
            f"record's set_digest"
        )


# --- the raw rows ------------------------------------------------------------------


def _row(run: _LoadedRun, score: PackageScore) -> RunRow:
    session = run.sessions[score.package_id]
    usage = session.usage
    totals = usage.totals if usage is not None else None
    provenance = run.provenance
    flags = session.efficiency.model_dump() if session.efficiency is not None else {}
    studied = provenance.lever if provenance is not None else None
    info = session.provider_info
    coverage = session.coverage
    return RunRow(
        run=run.run,
        run_dir=str(run.run_dir),
        commit=provenance.commit if provenance is not None else None,
        lever=studied,
        arm=provenance.arm if provenance is not None else None,
        rep=provenance.rep if provenance is not None else None,
        provider=info.provider if info is not None else None,
        model=info.model if info is not None else session.model,
        effort=info.effort_mapping.requested if info is not None else None,
        package_id=score.package_id,
        held_out=score.held_out,
        other_levers_on=sorted(name for name in LEVER_NAMES if flags.get(name) and name != studied),
        input_tokens=totals.input_tokens if totals is not None else None,
        cached_input_tokens=totals.cached_input_tokens if totals is not None else None,
        uncached_input_tokens=totals.uncached_input_tokens if totals is not None else None,
        output_tokens=totals.output_tokens if totals is not None else None,
        reasoning_tokens=totals.reasoning_tokens if totals is not None else None,
        tool_result_input_tokens=totals.tool_result_input_tokens if totals is not None else None,
        total_tokens=totals.total_tokens if totals is not None else None,
        rounds=usage.rounds if usage is not None else None,
        tool_calls=len(session.steps),
        cached_input_share=score.cached_input_share,
        wall_clock_s=score.wall_clock_s,
        seconds_to_first_finding=score.seconds_to_first_finding,
        valid_findings=score.valid_findings,
        missed_known_defects=score.missed_known_defects,
        false_alarms=score.false_alarms,
        unresolved_count=score.unresolved_count,
        coverage_bucket_mix={
            bucket: len(getattr(coverage, bucket))
            for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        },
        set_too_small_override=(
            provenance.set_too_small_override if provenance is not None else False
        ),
    )


# --- the decision rows -------------------------------------------------------------


def _study_key(run: _LoadedRun) -> tuple[str, str | None, str | None] | None:
    """One study is one lever, one provider and one model. A run with no provenance
    belongs to none: it renders as a raw row and gates nothing."""
    if run.provenance is None or run.provenance.arm is None:
        return None
    return (run.provenance.lever, run.provenance.provider, run.provenance.model)


def _check_one_study(runs: Sequence[_LoadedRun]) -> None:
    """Refuse to place two runs in one comparison when what was fixed was not.

    The provider and the model are part of the study key, so two models are two studies
    rather than one refusal; commit, effort, set file and checklist are the four that
    must be equal *within* a study, with no declared exception.

    Then the repetitions, which is what stops a six-run set being one run counted six
    times: within an arm every `rep` is distinct, and a gated arm (`off` or `on`) has one
    at all. `adoption.MIN_REPS` counts runs, and without this it is satisfied by copies.
    A baseline arm is exempt from the second clause only: it gates nothing.
    """
    first = runs[0].provenance
    assert first is not None
    for run in runs[1:]:
        other = run.provenance
        assert other is not None
        for field in ("commit", "effort", "set_digest", "checklist_digest"):
            if getattr(first, field) != getattr(other, field):
                raise CompareError(
                    f"{runs[0].run_dir} and {run.run_dir} cannot be placed in one "
                    f"comparison: {field} differs "
                    f"({getattr(first, field)!r} against {getattr(other, field)!r})"
                )
    _check_repetitions(runs)


def _check_repetitions(runs: Sequence[_LoadedRun]) -> None:
    """One `rep` per run per arm, and a gated arm has one at all."""
    seen: dict[tuple[str, int], Path] = {}
    for run in runs:
        provenance = run.provenance
        assert provenance is not None and provenance.arm is not None
        arm = provenance.arm
        if provenance.rep is None:
            if arm == BASELINE_ARM:
                continue
            raise CompareError(
                f"{run.run_dir}: a run of arm {arm!r} carries no repetition index; "
                f"re-run it with --rep <n>, because a median and a worst case are taken "
                f"over distinct repetitions"
            )
        earlier = seen.get((arm, provenance.rep))
        if earlier is not None:
            raise CompareError(
                f"{earlier} and {run.run_dir} are both arm {arm!r} rep {provenance.rep}; "
                f"a study needs distinct repetitions, not one measurement counted twice"
            )
        seen[(arm, provenance.rep)] = run.run_dir


def _arm_run(run: _LoadedRun) -> ArmRun:
    return ArmRun(
        run=run.run,
        scorecard=run.scorecard,
        tool_calls=run.tool_calls,
        set_too_small_override=(
            run.provenance.set_too_small_override if run.provenance is not None else False
        ),
    )


def _counter(lever: str, off: Sequence[ArmRun], on: Sequence[ArmRun]) -> LeverCounter:
    name = LEVER_COUNTERS.get(lever, lever)
    metric_name = COUNTER_METRIC.get(lever)
    if metric_name is None:
        return LeverCounter(name=name, off=None, on=None)
    stat = off_on(metric(off, metric_name), metric(on, metric_name))
    return LeverCounter(name=name, off=stat.off_median, on=stat.on_median)


def _decision_row(
    key: tuple[str, str | None, str | None], runs: Sequence[_LoadedRun]
) -> LeverDecision:
    lever, provider, model = key
    _check_one_study(runs)
    arms = [(run, run.provenance.arm) for run in runs if run.provenance is not None]
    off = [_arm_run(run) for run, arm in arms if arm != "on"]
    on = [_arm_run(run) for run, arm in arms if arm == "on"]
    baseline = lever == NO_LEVER

    verdict = (
        Verdict(
            decision=None,
            reason=(
                f"{BASELINE}: a baseline study is the distribution, with nothing to "
                f"compare against and therefore no decision"
            ),
            worst_case_defects_lost=None,
            lost_defect_ids=[],
        )
        if baseline
        else decide(off, on)
    )

    stats = {name: off_on(metric(off, name), metric(on, name)) for name in METRICS}
    other_levers: set[str] = set()
    for run in runs:
        session = next(iter(run.sessions.values()), None)
        if session is None or session.efficiency is None:
            continue
        flags = session.efficiency.model_dump()
        other_levers |= {name for name in LEVER_NAMES if flags[name] and name != lever}

    return LeverDecision(
        lever=lever,
        provider=provider,
        model=model,
        commit_off=_commit_of(runs, on_arm=False),
        commit_on=_commit_of(runs, on_arm=True),
        reps=max(len(off), len(on)),
        other_levers_on=sorted(other_levers),
        input_tokens=stats["input_tokens"],
        cached_input_tokens=stats["cached_input_tokens"],
        output_tokens=stats["output_tokens"],
        reasoning_or_thoughts=stats["reasoning_tokens"],
        total_tokens=stats["total_tokens"],
        round_trips=stats["round_trips"],
        tool_calls=stats["tool_calls"],
        wall_clock_s=stats["wall_clock_s"],
        dump_wall_clock_s=stats["dump_wall_clock_s"],
        valid_findings=stats["valid_findings"],
        missed_known_defects=stats["missed_known_defects"],
        false_alarms=stats["false_alarms"],
        unresolved_count=stats["unresolved_count"],
        recall_held_out=stats["recall_held_out"],
        worst_case_defects_lost=verdict.worst_case_defects_lost,
        lost_defect_ids=verdict.lost_defect_ids,
        lever_counter=_counter(lever, off, on),
        decision=verdict.decision,
        decision_reason=verdict.reason,
        run_dirs=[str(run.run_dir) for run in runs],
    )


def _commit_of(runs: Sequence[_LoadedRun], *, on_arm: bool) -> str | None:
    """The commit of one arm. Equal to the other for every lever in this feature, lever
    2 included; the pair exists for FR-032, which currently has no instance."""
    for run in runs:
        if run.provenance is None:
            continue
        if (run.provenance.arm == "on") is on_arm:
            return run.provenance.commit
    return None


# --- the ledger --------------------------------------------------------------------


def compare_runs(run_dirs: Sequence[Path | str]) -> Ledger:
    """Read N run directories and build the ledger. Contacts nothing and starts nothing."""
    loaded = [_load_run(path) for path in _distinct(run_dirs)]
    rows = [_row(run, score) for run in loaded for score in run.scorecard.per_package]

    studies: dict[tuple[str, str | None, str | None], list[_LoadedRun]] = {}
    for run in loaded:
        key = _study_key(run)
        if key is not None:
            studies.setdefault(key, []).append(run)

    return Ledger(
        runs=rows,
        levers=[_decision_row(key, runs) for key, runs in studies.items()],
    )


def _distinct(run_dirs: Sequence[Path | str]) -> list[Path]:
    """The resolved run directories, refusing a folder named more than once.

    One folder passed three times is **one** measurement, and the adoption rule's
    six-run precondition may not be met by copies of it (RK-20). Resolved rather than
    compared as typed, so `off-1` and `./off-1` are caught as the same folder.
    """
    seen: dict[Path, Path] = {}
    for run_dir in run_dirs:
        path = Path(run_dir)
        resolved = path.resolve()
        if resolved in seen:
            raise CompareError(
                f"{path} is named more than once; one run directory is one measurement "
                f"and may not stand in for several"
            )
        seen[resolved] = path
    return list(seen.values())


def recorded_runs(studies_dir: Path | str = STUDIES_DIR) -> list[Path]:
    """Every scored run directory under `studies_dir`, sorted, or none at all.

    A run directory is one holding a `scorecard.json`, at whatever depth the study laid it
    out, so the workstation harness's folders are found by the same rule as the benchmark
    runner's.
    """
    root = Path(studies_dir)
    if not root.is_dir():
        return []
    return sorted({path.parent for path in root.rglob(SCORECARD_FILE)})


def refused_decisions(ledger: Ledger) -> list[LeverDecision]:
    """The studies whose decision row was refused (FR-029). A baseline is not one: it
    renders no `Decision` by design and is never blocked."""
    return [
        row
        for row in ledger.levers
        if row.decision is None and not row.decision_reason.startswith(BASELINE)
    ]


def write_ledger(ledger: Ledger, out_dir: Path | str) -> tuple[Path, Path]:
    """Write `ledger.json` and `ledger.md` into `out_dir`."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / LEDGER_JSON
    md_path = target / LEDGER_MD
    json_path.write_text(ledger.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_ledger_md(ledger), encoding="utf-8")
    return json_path, md_path


# --- rendering ---------------------------------------------------------------------


def _count(value: float | None) -> str:
    """A reported number, or `unknown`. Never `0`, never a blank cell (RK-1)."""
    if value is None:
        return UNKNOWN
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _share(share: float | None) -> str:
    """The cached share, or `unknown` while probe L1 is unrecorded (FR-047)."""
    if not CACHED_SHARE_PUBLISHABLE or share is None:
        return UNKNOWN
    return f"{share:.0%}"


def _text(value: str | int | None) -> str:
    return UNKNOWN if value is None else str(value)


def _off_on(stat: OffOn) -> str:
    """`median (min-max) -> median (min-max), delta`, with `unknown` where a number is
    absent and the contributing row count stated where nulls were skipped."""
    delta = UNKNOWN if stat.delta_pct is None else f"{stat.delta_pct:+.1%}"
    return (
        f"{_count(stat.off_median)} ({_count(stat.off_min)}-{_count(stat.off_max)}, "
        f"n={stat.off_rows}) -> {_count(stat.on_median)} ({_count(stat.on_min)}-"
        f"{_count(stat.on_max)}, n={stat.on_rows}), {delta}"
    )


RUN_COLUMNS: tuple[str, ...] = (
    "run",
    "commit",
    "lever",
    "arm",
    "rep",
    "provider",
    "model",
    "effort",
    "package",
    "input",
    "cached in",
    "uncached in",
    "output",
    "reasoning/thoughts",
    "tool-result in",
    "total",
    "rounds",
    "tool calls",
    "cached share",
    "wall clock s",
    "s to 1st finding",
    "valid",
    "missed",
    "false alarms",
    "unresolved",
    "coverage bucket mix",
)

LEVER_COLUMNS: tuple[str, ...] = (
    "Lever",
    "Provider and model",
    "Commit",
    "Reps",
    "Other levers on",
    "Input tokens off -> on (median, min-max)",
    "Cached input off -> on",
    "Output off -> on",
    "Reasoning or thoughts off -> on",
    "Total tokens off -> on",
    "Round trips off -> on",
    "Tool calls off -> on",
    "Wall clock off -> on",
    "Dump wall clock off -> on",
    "Valid / missed / false alarms / unresolved off -> on",
    "Recall (held out) off -> on",
    "Worst-case defects lost",
    "Lever-specific counter",
    "Decision",
    "Owner signed off",
    "Owner signed off at",
    "Decision reason",
    "Link to run dirs",
)


def _header(columns: Sequence[str]) -> list[str]:
    return ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]


def _run_line(row: RunRow) -> str:
    mix = " / ".join(f"{bucket} {count}" for bucket, count in row.coverage_bucket_mix.items())
    cells = (
        row.run,
        _text(row.commit),
        _text(row.lever),
        _text(row.arm),
        _text(row.rep),
        _text(row.provider),
        _text(row.model),
        _text(row.effort),
        row.package_id,
        _count(row.input_tokens),
        _count(row.cached_input_tokens),
        _count(row.uncached_input_tokens),
        _count(row.output_tokens),
        _count(row.reasoning_tokens),
        _count(row.tool_result_input_tokens),
        _count(row.total_tokens),
        _count(row.rounds),
        _count(row.tool_calls),
        _share(row.cached_input_share),
        _count(row.wall_clock_s),
        _count(row.seconds_to_first_finding),
        _count(row.valid_findings),
        _count(row.missed_known_defects),
        _count(row.false_alarms),
        _count(row.unresolved_count),
        mix,
    )
    return "| " + " | ".join(cells) + " |"


def _quality(row: LeverDecision) -> str:
    return " ; ".join(
        _off_on(stat)
        for stat in (
            row.valid_findings,
            row.missed_known_defects,
            row.false_alarms,
            row.unresolved_count,
        )
    )


def _lever_line(row: LeverDecision) -> str:
    counter = row.lever_counter
    cells = (
        row.lever,
        f"{_text(row.provider)} {_text(row.model)}",
        _text(row.commit_off) if row.commit_off == row.commit_on else
        f"{_text(row.commit_off)} -> {_text(row.commit_on)}",
        str(row.reps),
        ", ".join(row.other_levers_on) or "-",
        _off_on(row.input_tokens),
        _off_on(row.cached_input_tokens),
        _off_on(row.output_tokens),
        _off_on(row.reasoning_or_thoughts),
        _off_on(row.total_tokens),
        _off_on(row.round_trips),
        _off_on(row.tool_calls),
        _off_on(row.wall_clock_s),
        _off_on(row.dump_wall_clock_s),
        _quality(row),
        _off_on(row.recall_held_out),
        _count(row.worst_case_defects_lost),
        f"{counter.name}: {_count(counter.off)} -> {_count(counter.on)}",
        row.decision if row.decision is not None else UNKNOWN,
        SIGNED if row.owner_signed_off else UNSIGNED,
        _text(row.owner_signed_off_at.isoformat() if row.owner_signed_off_at else None),
        row.decision_reason,
        ", ".join(row.run_dirs),
    )
    return "| " + " | ".join(cells) + " |"


def render_ledger_md(ledger: Ledger) -> str:
    """Both tables: the raw per-run rows, then the per-lever decision rows.

    Rendered from the ledger and nothing else, so re-running `compare` over the same
    folders regenerates this byte for byte.
    """
    lines = ["## Results ledger", "", "### Runs", "", *_header(RUN_COLUMNS)]
    lines += [_run_line(row) for row in ledger.runs]
    if not ledger.runs:
        lines += ["", "No runs: no run directories were compared."]

    lines += ["", "### Decisions", "", *_header(LEVER_COLUMNS)]
    lines += [_lever_line(row) for row in ledger.levers]
    if not ledger.levers:
        lines += ["", "No decisions: no run directories were compared."]

    lines += [
        "",
        "`Decision` is computed by the adoption rule and is never typed; "
        "`Owner signed off` and `Owner signed off at` are the owner's separate act, "
        "written by hand into the committed table once the row has been read and carried "
        "forward verbatim by every later regeneration. No flag default changes until "
        "they are written.",
        "",
        "`wall clock s` is the session's own `started_at` to `ended_at`, **not** "
        "`unattended_runtime_minutes`, which the benchmark runner overwrites with a span "
        "that also covers package load and adapter construction.",
    ]
    return "\n".join(lines) + "\n"


def splice_ledger(document: str, ledger_md: str) -> str:
    """Replace what sits between the two markers in `document` with `ledger_md`."""
    start = document.find(LEDGER_BEGIN)
    end = document.find(LEDGER_END)
    if start < 0 or end < 0 or end < start:
        raise CompareError(
            f"the document carries no {LEDGER_BEGIN} / {LEDGER_END} pair to write between"
        )
    head = document[: start + len(LEDGER_BEGIN)]
    tail = document[end:]
    return f"{head}\n\n{ledger_md}\n{tail}"


# --- the owner's sign-off, read back and carried forward (FR-027, T043) --------------

SIGNED = "yes"
UNSIGNED = "no"
"""The two values the `Owner signed off` cell may hold. Anything else is a typo in a
column the whole adoption gate rests on, and is refused rather than read as `no`."""

LEVER_COLUMN = "Lever"
PROVIDER_MODEL_COLUMN = "Provider and model"
SIGNED_OFF_COLUMN = "Owner signed off"
SIGNED_OFF_AT_COLUMN = "Owner signed off at"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _absent(cell: str) -> str | None:
    return None if cell == UNKNOWN else cell


class SignOff(ReviewModel):
    """One row's owner sign-off as the committed ledger holds it."""

    signed_off: bool
    signed_off_at: date | None


def read_sign_offs(document: str) -> dict[tuple[str, str | None, str | None], SignOff]:
    """The sign-offs already committed, keyed by the study the row belongs to.

    Read out of the rendered decision table, because that markdown is what the owner
    edits (T043). The key is the same `(lever, provider, model)` triple `compare` groups
    studies by, recovered from the two cells this module rendered it into; two rows
    sharing one key is a corrupted table and is refused rather than guessed at.
    """
    lines = document.splitlines()
    header = next(
        (line for line in lines if _cells(line)[:2] == [LEVER_COLUMN, PROVIDER_MODEL_COLUMN]),
        None,
    )
    if header is None:
        return {}
    names = _cells(header)
    if SIGNED_OFF_COLUMN not in names:
        return {}
    start = lines.index(header) + 2
    found: dict[tuple[str, str | None, str | None], SignOff] = {}
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        values = _cells(line)
        if len(values) != len(names):
            continue
        row = dict(zip(names, values, strict=True))
        provider, _, model = row[PROVIDER_MODEL_COLUMN].partition(" ")
        key = (row[LEVER_COLUMN], _absent(provider), _absent(model))
        if key in found:
            raise CompareError(
                f"the committed ledger holds two rows for {key[0]}; a sign-off cannot be "
                f"carried forward onto a table whose rows are not unique"
            )
        found[key] = _sign_off(key[0], row)
    return found


def _sign_off(lever: str, row: dict[str, str]) -> SignOff:
    cell = row[SIGNED_OFF_COLUMN]
    if cell not in (SIGNED, UNSIGNED):
        raise CompareError(
            f"the committed ledger's {SIGNED_OFF_COLUMN} cell for {lever} reads {cell!r}; "
            f"it is {SIGNED!r} or {UNSIGNED!r} and nothing else"
        )
    at = _absent(row.get(SIGNED_OFF_AT_COLUMN, UNKNOWN))
    return SignOff(
        signed_off=cell == SIGNED,
        signed_off_at=date.fromisoformat(at) if at else None,
    )


def carry_sign_offs(ledger: Ledger, *documents: str) -> Ledger:
    """The freshly computed ledger with the committed sign-offs copied onto it.

    Nothing here is derived from a run: a row the owner never signed keeps its `False`
    default, and a signed row in the committed table that no compared study matches is
    simply not carried, because there is no row to carry it onto. Later documents win,
    which is how `--into` beats a stale `out/ledger.md`.
    """
    carried: dict[tuple[str, str | None, str | None], SignOff] = {}
    for document in documents:
        carried.update(read_sign_offs(document))
    return ledger.model_copy(
        update={
            "levers": [
                _with_sign_off(row, carried.get((row.lever, row.provider, row.model)))
                for row in ledger.levers
            ]
        }
    )


def _with_sign_off(row: LeverDecision, sign_off: SignOff | None) -> LeverDecision:
    if sign_off is None:
        return row
    return row.model_copy(
        update={
            "owner_signed_off": sign_off.signed_off,
            "owner_signed_off_at": sign_off.signed_off_at,
        }
    )


def committed_sign_off_sources(out: Path | None, into: Path | None) -> list[str]:
    """The already-committed ledgers this invocation is about to overwrite, in the order
    `carry_sign_offs` should apply them: the `--out` copy first, the `--into` document
    last, because the committed document is the one the owner signs."""
    sources: list[Path] = []
    if out is not None:
        sources.append(Path(out) / LEDGER_MD)
    if into is not None:
        sources.append(Path(into))
    return [path.read_text(encoding="utf-8") for path in sources if path.is_file()]
