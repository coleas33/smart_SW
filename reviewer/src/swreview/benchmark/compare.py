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
   never conflated with `rounds`, the provenance columns and the profile and live tools are
   the provenance record's, the model view is the session's, and the outcome columns are the
   scorer's `PackageScore` (feature 014 `contracts/provenance.md` 5). A run folder inside the
   checkout is named relative to its root (section 6.3).
3. **The reader that asks `adoption.decide` for the `Decision` column** and never types
   one. The owner's approval is `owner_signed_off`, a separate field this module never
   *computes*: `carry_sign_offs` copies it, and `owner_signed_off_at`, off the committed
   ledger onto the matching row before rendering, so the hand-written sign-off the owner
   put there survives the next regeneration instead of being reset to `no`.

**`compare` never contacts a provider, never starts a run and reads no answer key.** It
reads the provenance record, `session.json`, the saved set and `scorecard.json`, so
Principle VI and FR-025 are untouched.

What is refused, and what is merely null:

- A scorecard scored under other scoring rules, or malformed: **refused** by
  `scorecard.read_scorecard` before anything else is read, with the command that re-scores it
  (feature 014 `scoring.md` 8).
- No `efficiency` on a session at all: **refused** - the run predates the flag carrier
  and cannot be attributed to an arm.
- The two records disagreeing, on the settings, the provider, the model, the effort, the
  model view, a standards finding's profile stamp, the saved set copy, or the arm against
  its settings: **refused**, naming it. A scorecard's served model outside the requested
  model's aliases is refused too. A saved set whose `held_out` flag disagrees with a
  package's scored items, or that does not hold a scored package: **refused**, naming the
  package (feature 014 `contracts/provenance.md` 2).
- Two runs of one study differing in any field of the record but the named exemptions
  (`MUST_MATCH`; feature 014 `contracts/provenance.md` 4): **refused**, naming the first such
  field. There is no declared exception; lever 2's off arm is its flag off, not an earlier
  commit. Two runs scored against two versions of one package's answer key
  (`Scorecard.key_sha256`): **refused**, naming the package (feature 014 INT-16).
- A run of a pane study with no arm, or a `pane_defaults` run not graded against the example
  profile: **refused**. Both pane studies render their raw rows and no decision row, under
  their own study keys (feature 014 `contracts/provenance.md` 3.2).
- A ledger written where the repository may commit it, holding a run graded against another
  profile than the fictional example, one whose saved set names an absolute path, or one from
  a folder the repository does not hold: **refused**, naming the run (FR-051;
  `contracts/provenance.md` 6.4).
- No provenance record at all: **not** refused. The row renders with `lever`, `arm`,
  `rep` and `commit` null, because a run made before the convention existed is still a
  real run.
- A study that can produce no recall number, or one carrying the too-small-set override:
  the **decision row** is refused (`decision: null` with the reason beside it) and the
  **raw rows still render**. `adoption.decide` owns that rule; the command exits non-zero.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PureWindowsPath

from pydantic import Field, ValidationError, model_serializer

from swreview.agent.providers import CACHED_SHARE_PUBLISHABLE
from swreview.agent.runner import SESSION_FILE_NAME
from swreview.agent.settings import (
    BETWEEN_TURN_SETTINGS,
    LEVER_NAMES,
    MODEL_VIEW_OFF,
    MODEL_VIEW_PANE,
    PANE_STUDY,
    PRIVATE_PANE_STUDY,
    ModelViewSettings,
)
from swreview.benchmark import digest as benchmark_digest
from swreview.benchmark import pilot, served, sets, simulate, verdict
from swreview.benchmark import stats as pane_stats
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
from swreview.benchmark.origins import Origin
from swreview.benchmark.runner import (
    REPO_ROOT,
    SAVED_SET_FILE,
    RunProvenance,
    committable,
    load_provenance,
    sha256_of,
)
from swreview.benchmark.scorecard import (
    SCORECARD_FILE,
    UNKNOWN,
    PackageScore,
    Scorecard,
    by_origin,
    false_alarm_origins,
    final_state_origins,
    fmt_assessed,
    fmt_origins,
    length_or_none,
    read_scorecard,
)
from swreview.checks.standards.profile import display_digest
from swreview.checks.standards.report import stamped_profile_digest
from swreview.exceptions import STANDARDS_CHECK_PREFIX
from swreview.findings import ReviewModel
from swreview.report.session import ReviewSession, load_session

LEDGER_SCHEMA = "1.1"
"""`ledger.json`'s schema (feature 014 `contracts/provenance.md` 5; plan decision INT-10): one bump
for the feature, with the run and decision columns in their final order. The 1.1 record also names
`pane_studies`, a key omitted when no pane study was compared and filled from the verdict slice,
so that slice moves neither this version nor the committed header."""

LEDGER_JSON = "ledger.json"
LEDGER_MD = "ledger.md"

LEDGER_BEGIN = "<!-- ledger:begin -->"
LEDGER_END = "<!-- ledger:end -->"
"""The markers `--into` writes between, so a committed document cannot drift from the
runs it claims to summarize (T045)."""

BASELINE_ARM = "baseline"
NO_LEVER = "none"

PANE_BASELINE_LABEL = "none (pane defaults)"
"""The pane baseline's study label (`--study none --arm baseline --pane-defaults`; feature 014
PP-4): its own study key beside the plain baseline's `none`, so it carries its own sign-off."""

BASELINE_LABELS: tuple[str, ...] = (NO_LEVER, PANE_BASELINE_LABEL)
"""The two baselines' study labels: each a distribution, and no decision."""

PANE_STUDIES: tuple[str, ...] = (PANE_STUDY, PRIVATE_PANE_STUDY)
"""The two pane studies (feature 014 `contracts/provenance.md` 3.1), each its own study key.

Compare routes them to `verdict` and never hands them to `_decision_row`: `decide` never applies
to a pane study (FR-045)."""

RUN_START_SCHEMA = 2
"""The first provenance schema to record the model view and the profile's digest (feature 014
`contracts/provenance.md` 1). An older record recorded neither, so no session is held against it
on either."""

STUDIES_DIR = REPO_ROOT / "benchmarks" / "studies"
"""Where the run directories the committed ledger is rendered from live.

The `## Results` table in `docs/llm-efficiency-options.md` is a rendering of exactly these
folders, and `--check` is what stops the document drifting from them (T045). The directory
does not exist until the first study is run, and an empty ledger is the honest rendering of
a feature that has measured nothing yet."""

PILOTS_DIR = REPO_ROOT / "benchmarks" / "pilots"

TRIM_LEVER = "trim_tool_descriptions"
"""Lever 2, whose counter is the tool-name histogram rather than one of `adoption.METRICS`."""

TIER_LEVER = "tool_tiers"
"""Lever 4, whose counter is the withheld half of the unresolved count (FR-054). Also not
one of `adoption.METRICS`: both halves are per package, and `Aggregate` carries neither."""

GATE_LEVERS: tuple[str, ...] = ("prerun_checks", "procedural_gate")
"""Levers 5 and 11, which share one counter because lever 11 implies lever 5.

An arm of either runs the deterministic checks before the first turn, so both carry the
same risk, and it is the one thing the token columns cannot show: a model handed a list of
what has already been checked stops reaching for the two tools no rule can enumerate
(feature 007 FR-034, SC-010)."""

GATE_TOOLS: tuple[str, ...] = ("check_fit", "check_axial_stack")
"""The two checks only the model can set up, and therefore the two it can quietly stop
setting up. Nothing enumerates a bore and a shaft, or an ordered stack with a target gap
(`contracts/levers.md` lever 5), so a run that stops calling them loses coverage that no
other column moves."""

GATE_COUNTER = "check_fit and check_axial_stack calls per run (must not fall)"

BASELINE_COUNTER = "none: a baseline study has no lever to counter"
"""Both baselines' counter: neither has a lever under test."""

LEVER_COUNTERS: dict[str, str] = {
    TRIM_LEVER: "distinct tool names called",
    "tool_tiers": "unresolved because withheld",
    "prompt_cache_key": "cache miss reasons and cache_missed_tokens (arrives with lever 3)",
    "gemini_explicit_cache": "cached-content hit rate (arrives with lever 3, Gemini)",
    "prerun_checks": GATE_COUNTER,
    "parallel_tool_calls": "tool calls beside round trips",
    "coverage_stop": "stop fire rate (arrives with lever 7)",
    "package_reuse": "dump wall clock, cold against reused (workstation harness)",
    "lazy_meshes": "bodies_swept per arm (workstation harness)",
    "carry_over_rms": "carried against re-run counts (workstation harness)",
    "procedural_gate": GATE_COUNTER,
    "compact_queries": "distinct tool names called (compact discovery and full detail)",
    "withhold_prerun_tools": "tool array per request, and calls answered already_run",
    "drop_prior_reasoning": "requested input per round after the first turn (replay estimate)",
    NO_LEVER: BASELINE_COUNTER,
    PANE_BASELINE_LABEL: BASELINE_COUNTER,
}
"""The number **this** lever's gate needs and no other's (ab-harness section 6).

Every lever is named here even when the counter itself lands with that lever's own task,
so the column says *which* number is missing rather than going blank. Levers 2 and 6 are
the two that compute today: lever 6's from `tool_calls`, lever 2's from the tool-name
histogram `PackageScore` carries (`_histogram_counter`). Lever 4's landed with it: the
withheld half of the unresolved count (`_withheld_counter`). Levers 5 and 11 landed with
lever 11, and lever 5's entry stopped being a placeholder in the same change: it named a
number nobody could compute, and it is the same number (`_gate_counter`)."""

COUNTER_METRIC: dict[str, str] = {"parallel_tool_calls": "tool_calls"}
"""The counters that are already a metric in `adoption.METRICS`; the rest render unknown
until their lever lands."""

# What must match across a study (feature 014 `contracts/provenance.md` 4): every field of the
# record but these named exemptions, each in exactly one set.

RUN_IDENTITY: tuple[str, ...] = ("rep", "started_at")
"""Which run this is: never compared."""

RECORD_ONLY: tuple[str, ...] = ("live_tools", "jobs")
"""Recorded and shown, never must-match (PP-9, owner decision 36A)."""

STUDY_KEY_FIELDS: tuple[str, ...] = ("lever", "provider", "model")
"""The study's key (`_study_key`): two runs differing in one are two studies, not a refusal."""

ACROSS_ARMS: tuple[str, ...] = ("arm",)
"""What names the arm, exempt across the arms of every study, lever and pane alike: a lever
study's off and on runs share one study key (plan decision RF-10)."""

ACROSS_PANE_ARMS: tuple[str, ...] = ("efficiency", "model_view", "pane_defaults")
"""What the pane study varies (D5), exempt across its two arms only. Across a lever study's arms
only the studied lever's own flag in `efficiency` is."""

MUST_MATCH: tuple[str, ...] = tuple(
    name
    for name in RunProvenance.model_fields
    if name not in (*RUN_IDENTITY, *RECORD_ONLY, *STUDY_KEY_FIELDS, *ACROSS_ARMS, *ACROSS_PANE_ARMS)
)
"""Every other field of the record, in its own order: a field added later must match until
someone exempts it by name."""

NOT_RECORDED_WHEN_ABSENT: tuple[str, ...] = (
    "max_answer_turns",
    # Slice 6's robustness fields (T202; provenance.md 4): absent only in an older record.
    "package_time_limit_s",
    "stream_activity_window_s",
    "stop_grace_s",
    "retry_policy",
)
"""The fields whose absence can only mean a record an older build wrote, so a refusal quotes an
absent one "not recorded" (owner decision 47A). Every other field's value is quoted as it is:
a schema-2 record's `profile_digest` of `None` means no profile, a `commit` of `None` that git
could not answer."""


class CompareError(ValueError):
    """A run, or a pair of runs, that may not be placed in a comparison."""


class RunRow(ReviewModel):
    """One row per run **per package**: the raw ledger, with one source per column."""

    run: str
    run_dir: str
    """The run folder as the ledger names it (feature 014 `contracts/provenance.md` 6.3):
    relative to the checkout's root with `/` inside it, as typed outside it."""

    commit: str | None
    lever: str | None
    arm: str | None
    rep: int | None
    provider: str | None
    model: str | None
    effort: str | None
    explanations_enabled: bool = False
    model_view: ModelViewSettings
    """The session's, which `_check_session` has held equal to a schema-2 record's;
    `MODEL_VIEW_OFF` for a session written before feature 008, which that constant defines as
    off."""

    profile_recorded: bool
    """Whether the record says which profile the run graded against, if any: false with no
    record, or with one older than `RUN_START_SCHEMA`, whose `profile_digest` is absent rather
    than none. The profile cell then reads unknown, never `none`."""

    profile_digest: str | None
    """The record's: the sha256 every standards finding of the run stamps; `None` with no
    profile, and with no record."""

    live_tools: bool | None
    """The record's; `None` with no record, or one that did not record it."""

    pane_defaults: bool | None
    """The record's marker (PP-3); `None` with no record."""

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
    flagged: int
    flagged_below_expected: int
    status_mismatches: int
    cleared: int
    """Four of the scorer's outcome lists, counted (feature 014 `scoring.md` 3.1): the defects
    detected through an unresolved finding only, those met only below their expected status,
    those credited above an expected unresolved, and those a `checked_within_scope` finding
    cleared."""

    false_alarms: int
    contradictions: int | None
    confirmations: int | None
    """The correct conditions contradicted and confirmed (`scoring.md` 3.2); `None`, rendered
    `not assessed`, when the package's key holds no correct condition."""

    unresolved_count: int
    unresolved_because_withheld: int
    unresolved_other: int
    """The unresolved **coverage** items read as the two numbers FR-054 requires, both from
    `PackageScore`. They sum to `coverage_bucket_mix["unresolved"]` beside them and never to
    `unresolved_count`, which counts findings: lever 4 is expected to raise the first and
    its gate is that the second does not move."""

    coverage_bucket_mix: dict[str, int]
    findings_by_origin: dict[Origin, int]
    false_alarms_by_origin: dict[Origin, int]
    """Every origin, zeros included, in `Origin`'s order, as the scorer's aggregate counts them
    (`scoring.md` 5.5); the cells leave the zeros out."""

    set_too_small_override: bool


class LeverCounter(ReviewModel):
    """The lever-specific counter column: the name is always there, the numbers may not
    be."""

    name: str
    off: float | None
    on: float | None

    dropped_tools: list[str] = Field(default_factory=list)
    """Lever 2 (T057, T059): every tool some off-run called that **no** on-run called.

    A list and not a count, because "the repertoire lost one tool" is not a sentence an
    owner can act on. Empty means measured and clean; an arm that never ran leaves `off`
    and `on` unknown and this empty too, which is why the gate reads all three."""

    fell_in_runs: list[str] = Field(default_factory=list)
    """Levers 5 and 11 (feature 007 FR-034): every on-run whose gate-tool count fell below
    the off arm's **minimum**.

    A worst case beside the two medians, because SC-010 is a worst-case statement: "per-run
    fit and axial-stack call counts do not fall" is failed by one run that stopped checking
    fits, whatever the arm median says and whatever the token saving is. Against the off
    arm's minimum rather than its median, so the comparison is "worse than the worst run
    that did not have the lever" and not "worse than average". Empty means measured and
    clean, the same way an empty `dropped_tools` does."""


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
    recall_held_out_model: OffOn
    recall_held_out_code: OffOn
    """Recall of each producer's held-out known defects (feature 014 SP-13 A): reported beside
    the overall recall, never gated on."""

    median_net_saved_minutes: OffOn
    """The number the pilot is judged on, across runs: the median of each run's own
    per-package median, with `n=` the runs that carried timing at all. Reported, never
    gated on - `decide` names its metrics and this is not one (feature 007 FR-006)."""

    worst_case_defects_lost: int | None
    """`adoption.Verdict.worst_case_defects_lost`: `0` where the comparison ran and found
    nothing, `None` where it never ran. Rendered through `format_count`, so an absent number
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
    """Each run folder as `RunRow.run_dir` names it."""


class Ledger(ReviewModel):
    ledger_schema: str = LEDGER_SCHEMA
    runs: list[RunRow]
    levers: list[LeverDecision]
    pane_studies: list[verdict.PaneStudy] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _omit_empty_pane_studies(self, handler):
        payload = handler(self)
        if not self.pane_studies:
            payload.pop("pane_studies", None)
        return payload


@dataclass(frozen=True)
class _LoadedRun:
    """One validated run directory, held once so nothing is read twice."""

    run: str
    run_dir: Path
    """As typed: what a refusal names."""

    ledger_dir: str
    """As the ledger names it (`_ledger_dir`)."""

    provenance: RunProvenance | None
    scorecard: Scorecard
    sessions: dict[str, ReviewSession]

    @property
    def tool_calls(self) -> int:
        return sum(len(session.steps) for session in self.sessions.values())


# --- reading and validating one run directory ------------------------------------


def _load_run(run_dir: Path, *, root: Path) -> _LoadedRun:
    scorecard_path = run_dir / SCORECARD_FILE
    if not scorecard_path.is_file():
        raise CompareError(
            f"{run_dir}: no {SCORECARD_FILE}; run `swreview benchmark score` on this run "
            f"before comparing it"
        )
    # Before any session or parity check (feature 014 `scoring.md` 8): a folder scored under
    # other rules meets the re-score line, never a refusal its old fields happen to trigger.
    scorecard = read_scorecard(run_dir)
    if scorecard.unscored_packages:
        packages = ", ".join(package.package_id for package in scorecard.unscored_packages)
        raise CompareError(
            f"{run_dir}: unscored packages: {packages}; run "
            f"`swreview benchmark resume {run_dir}` before comparing this run"
        )
    provenance = load_provenance(run_dir)
    _check_record(run_dir, provenance)
    _check_served_models(run_dir, scorecard, provenance)

    sessions: dict[str, ReviewSession] = {}
    for score in scorecard.per_package:
        session_path = run_dir / score.package_id / SESSION_FILE_NAME
        if not session_path.is_file():
            raise CompareError(f"{run_dir}: {score.package_id} has no {SESSION_FILE_NAME}")
        session = load_session(session_path)
        _check_session(run_dir, score.package_id, session, provenance)
        sessions[score.package_id] = session

    _check_saved_set(run_dir, provenance)
    _check_set_flags(run_dir, scorecard, root=root)
    return _LoadedRun(
        run=run_dir.name,
        run_dir=run_dir,
        ledger_dir=_ledger_dir(run_dir, root=root),
        provenance=provenance,
        scorecard=scorecard,
        sessions=sessions,
    )


def _ledger_dir(run_dir: Path, *, root: Path) -> str:
    """A run folder as the ledger names it (feature 014 `contracts/provenance.md` 6.3).

    Inside the checkout, relative to its root with `/` separators, however it was typed: the
    committed table is rendered from absolute paths under `benchmarks/studies/` and would
    otherwise carry the checkout's location. Outside it, as typed, which only a ledger written
    outside the repository can hold (`_refuse_for_the_committed_ledger`). Inside is
    `sets.checkout_relative`'s reading.
    """
    relative = sets.checkout_relative(run_dir, root=root)
    return relative.as_posix() if relative is not None else str(run_dir)


def _model_view_of(session: ReviewSession) -> ModelViewSettings:
    """The session's model view; a session written before feature 008 carries none, which
    means off (`MODEL_VIEW_OFF`)."""
    return session.model_view if session.model_view is not None else MODEL_VIEW_OFF


def _check_record(run_dir: Path, provenance: RunProvenance | None) -> None:
    """The pane studies' and the baselines' run-level refusals, read off the record alone, so they
    abort the ledger whatever the run scored (feature 014 `contracts/provenance.md` 3.2 and 3.3).

    A run of either pane study names its arm, and a `pane_defaults` run is graded against the
    checkout's example profile, which every committed case is keyed against (FR-027). The private
    study takes the real profile.

    Before them, a baseline's study (section 3.3): `_study_key` labels a baseline by its arm and
    its marker alone, so a record with arm baseline and a lever other than none is refused as
    inconsistent, as `check_study_arm` refuses `--arm baseline` with a study at run time. Labelled,
    the pane baseline would drop its lever and a plain baseline would join that lever's study.
    """
    if provenance is not None and provenance.arm == BASELINE_ARM and provenance.lever != NO_LEVER:
        raise CompareError(
            f"{run_dir}: arm baseline with lever {provenance.lever!r}: a baseline run is the study "
            "with no lever under test, so its lever is none; the record is inconsistent"
        )
    if provenance is None or provenance.lever not in PANE_STUDIES:
        return
    if provenance.arm is None:
        raise CompareError(
            f"{run_dir}: a run of the {provenance.lever} study has no arm; name the arm: on or off"
        )
    if provenance.lever == PANE_STUDY and provenance.profile_is_example is not True:
        raise CompareError(
            f"{run_dir}: a {PANE_STUDY} run grades against the checkout's example profile, and "
            f"this one recorded profile_is_example {provenance.profile_is_example!r}"
        )


def _check_served_models(
    run_dir: Path, scorecard: Scorecard, provenance: RunProvenance | None
) -> None:
    """RF-16's second check: the kept attempts' served ids, read from the scorecard only."""
    if provenance is None:
        return
    for score in scorecard.per_package:
        for model in score.served_models:
            if not served.aliases(provenance.provider, provenance.model, model):
                raise CompareError(
                    f"{run_dir} / {score.package_id}: scorecard.json names served model {model!r} "
                    f"outside the aliases of requested model {provenance.model!r}"
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

    if session.explanations_enabled != provenance.explanations_enabled:
        raise CompareError(
            f"{run_dir} / {package_id}: session.json and the provenance record "
            "disagree on explanations_enabled"
        )

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

    if provenance.provenance_schema >= RUN_START_SCHEMA:
        if session.model_view != provenance.model_view:
            raise CompareError(
                f"{run_dir} / {package_id}: session.json and the provenance record disagree "
                f"on model_view: {session.model_view!r} against {provenance.model_view!r}"
            )
        _check_profile_stamps(run_dir, package_id, session, provenance.profile_digest)

    _check_arm(
        run_dir, package_id, session.efficiency.model_dump(), _model_view_of(session), provenance
    )


def _check_profile_stamps(
    run_dir: Path, package_id: str, session: ReviewSession, profile_digest: str | None
) -> None:
    """Every standards finding's profile stamp against the record's `profile_digest` (US2-3).

    Read through `stamped_profile_digest`, the one parser of the stamp, in either form: the
    path-bearing one findings carried before feature 014's D12 and the file-name one after it. A
    stamp on a run that recorded no profile is refused too: the record says the review graded
    against none.
    """
    for finding in session.findings:
        if not finding.check.startswith(STANDARDS_CHECK_PREFIX):
            continue
        stamped = stamped_profile_digest(finding.coverage_limits)
        if stamped == profile_digest:
            continue
        where = f"{run_dir} / {package_id}: {finding.id} ({finding.check})"
        if profile_digest is None:
            raise CompareError(
                f"{where} stamps the profile {stamped!r}, but the provenance record recorded no "
                "profile"
            )
        raise CompareError(
            f"{where} and the provenance record disagree on profile_digest: {stamped!r} against "
            f"{profile_digest!r}"
        )


def _check_arm(
    run_dir: Path,
    package_id: str,
    flags: dict[str, bool],
    view: ModelViewSettings,
    provenance: RunProvenance,
) -> None:
    """The arm against its settings - a second clause, not a narrowing.

    A baseline run, `arm == "baseline"` and only that (feature 014 `contracts/provenance.md`
    3.3: a run with no arm is a raw row whatever it switched on), has no lever under test: the
    plain baseline is checked as every flag false and `MODEL_VIEW_OFF`, the pane baseline by its
    marker and settings that are not all off. A pane study's arm is `_check_pane_arm`'s; a lever
    study's is checked against the studied lever's own flag (contracts/ab-harness.md section 3).
    """
    on = sorted(name for name in LEVER_NAMES if flags[name])
    changes = [*on, *(["model_view"] if view != MODEL_VIEW_OFF else [])]
    if provenance.arm == BASELINE_ARM:
        if provenance.pane_defaults:
            if not changes:
                raise CompareError(
                    f"{run_dir} / {package_id}: a pane baseline carries pane_defaults, but "
                    "every lever and the model view are off: mislabelled, it would measure the "
                    "plain baseline"
                )
            return
        if on:
            raise CompareError(
                f"{run_dir} / {package_id}: a baseline run has every flag off, but "
                f"{', '.join(on)} is on"
            )
        if view != MODEL_VIEW_OFF:
            raise CompareError(
                f"{run_dir} / {package_id}: a baseline run has the model view off, but it is "
                f"{view!r}; the pane baseline is --arm baseline --pane-defaults"
            )
        return
    if provenance.arm is None:
        return
    if provenance.lever in PANE_STUDIES:
        _check_pane_arm(run_dir, package_id, changes, provenance)
        return
    if provenance.lever not in flags:
        raise CompareError(f"{run_dir}: provenance names an unknown lever {provenance.lever!r}")
    if flags[provenance.lever] != (provenance.arm == "on"):
        raise CompareError(
            f"{run_dir} / {package_id}: the provenance record says arm "
            f"{provenance.arm!r} while session.efficiency has {provenance.lever} "
            f"{flags[provenance.lever]}"
        )


def _check_pane_arm(
    run_dir: Path, package_id: str, changes: list[str], provenance: RunProvenance
) -> None:
    """A pane study's arm against the constants that define it (feature 014 PP-3).

    `changes` is every lever on, and `model_view` when the view is not `MODEL_VIEW_OFF`. The off
    arm has every change off and the marker false; the on arm carries the marker and settings
    that are not the off arm's, or it would measure nothing. Never re-derived from today's
    `pane_defaults()`: the run-time rule made the on arm's settings the pane's at the run's
    commit, and re-deriving them would refuse every recorded pane study the day the defaults
    change.
    """
    study = provenance.lever
    if provenance.arm == "off":
        found = [*changes, *(["pane_defaults"] if provenance.pane_defaults else [])]
        if found:
            raise CompareError(
                f"{run_dir} / {package_id}: the off arm of {study} has every change off, but "
                f"{', '.join(found)} is on"
            )
        return
    if not provenance.pane_defaults:
        raise CompareError(
            f"{run_dir} / {package_id}: the on arm of {study} is exactly --pane-defaults, but "
            "its record carries pane_defaults false"
        )
    if not changes:
        raise CompareError(
            f"{run_dir} / {package_id}: the on arm of {study} has every lever off and the model "
            "view off: mislabelled, it would measure nothing"
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


def _check_set_flags(run_dir: Path, scorecard: Scorecard, *, root: Path) -> None:
    """Each scored package's saved-set entry against its scored items (feature 014 FR-032's
    compare half; plan decisions RF-39, RF-62).

    The `held_out` flag is derived from the key: true exactly when some graded item is tagged
    held out. Compare reads no key, so it reads the scorecard's copy of its tags, `graded_items`;
    `score` made the same check against the key itself, a package that then failed included. A
    scored package the saved set does not hold is refused too. Only where the saved copy is
    there, as `_check_saved_set`; read through `load_saved_set`, whose relative entries resolve
    against `root`, the reader's checkout.
    """
    saved = run_dir / SAVED_SET_FILE
    if not saved.is_file():
        return
    flags = {ref.package_id: ref.held_out for ref in sets.load_saved_set(saved, root=root).packages}
    for score in scorecard.per_package:
        if score.package_id not in flags:
            raise CompareError(
                f"{run_dir}: {score.package_id} is scored but not in the run's saved set"
            )
        held = sum(1 for item in score.graded_items if item.tag == "held_out")
        flag = flags[score.package_id]
        if flag != (held > 0):
            raise CompareError(
                f"{run_dir}: the saved set marks {score.package_id} held_out={json.dumps(flag)}, "
                f"but its scored items hold {held} held-out items; the flag is derived from the "
                "key"
            )


def _refuse_for_the_committed_ledger(run: _LoadedRun, *, root: Path) -> None:
    """FR-051's compare half (feature 014 `contracts/provenance.md` 6.4; PROV-09; US2-10), for a
    ledger written where the repository may commit it: it holds only fictional-profile studies
    over committed cases, from run folders the repository holds.

    Refused: a run graded against a profile other than the fictional example
    (`profile_is_example` false), one whose saved set names an absolute path, and one whose
    folder is not committable (`runner.committable`: outside the checkout at `root`, or ignored
    there). A run that recorded no profile (`profile_is_example` null) is not refused: it graded
    against none.
    """
    provenance = run.provenance
    another_profile = provenance is not None and provenance.profile_is_example is False
    if (
        another_profile
        or _names_an_absolute_path(run.run_dir / SAVED_SET_FILE)
        or not committable(run.run_dir, root=root)
    ):
        raise CompareError(
            "the committed ledger holds only fictional-profile studies over committed cases, "
            f"from run folders the repository holds (FR-051): render {run.run_dir} with --out "
            "outside the repository"
        )


def _names_an_absolute_path(saved: Path) -> bool:
    """Whether the saved set at `saved` names a path absolutely, a package's, a key's or a case
    file's (every path `sets.named_paths` reads off an entry): a private entry, or a copy saved
    before feature 014, which resolved every path (`contracts/provenance.md` 6.1).

    Read off the saved bytes, since `load_saved_set` resolves every entry. Absolute in either
    platform's spelling, a drive, a share or a root, which is what a Windows path's anchor
    reads, so a copy saved on another platform is read alike. A run with no saved copy names
    none.
    """
    if not saved.is_file():
        return False
    entries = json.loads(saved.read_text(encoding="utf-8"))["packages"]
    return any(
        PureWindowsPath(named).anchor for entry in entries for named in sets.named_paths(entry)
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
    profile_recorded = provenance is not None and provenance.provenance_schema >= RUN_START_SCHEMA
    return RunRow(
        run=run.run,
        run_dir=run.ledger_dir,
        commit=provenance.commit if provenance is not None else None,
        lever=studied,
        arm=provenance.arm if provenance is not None else None,
        rep=provenance.rep if provenance is not None else None,
        provider=info.provider if info is not None else None,
        model=info.model if info is not None else session.model,
        effort=info.effort_mapping.requested if info is not None else None,
        explanations_enabled=session.explanations_enabled,
        model_view=_model_view_of(session),
        profile_recorded=profile_recorded,
        profile_digest=provenance.profile_digest if provenance is not None else None,
        live_tools=provenance.live_tools if provenance is not None else None,
        pane_defaults=provenance.pane_defaults if provenance is not None else None,
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
        flagged=len(score.flagged_defect_ids),
        flagged_below_expected=len(score.flagged_below_expected_defect_ids),
        status_mismatches=len(score.status_mismatch_defect_ids),
        cleared=len(score.cleared_defect_ids),
        false_alarms=score.false_alarms,
        contradictions=length_or_none(score.contradicted_condition_ids),
        confirmations=length_or_none(score.confirmed_condition_ids),
        unresolved_count=score.unresolved_count,
        unresolved_because_withheld=score.unresolved_because_withheld,
        unresolved_other=score.unresolved_other,
        coverage_bucket_mix={
            bucket: len(getattr(coverage, bucket))
            for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        },
        findings_by_origin=by_origin(final_state_origins(score)),
        false_alarms_by_origin=by_origin(false_alarm_origins(score)),
        set_too_small_override=(
            provenance.set_too_small_override if provenance is not None else False
        ),
    )


# --- the decision rows -------------------------------------------------------------


def _study_key(run: _LoadedRun) -> tuple[str, str | None, str | None] | None:
    """One study is one label, one provider and one model (feature 014
    `contracts/provenance.md` 3.1): the label is the lever, but the pane baseline's is
    `PANE_BASELINE_LABEL`. A run with no provenance, or no arm, belongs to none: it renders as a
    raw row and gates nothing."""
    provenance = run.provenance
    if provenance is None or provenance.arm is None:
        return None
    pane_baseline = provenance.arm == BASELINE_ARM and provenance.pane_defaults
    label = PANE_BASELINE_LABEL if pane_baseline else provenance.lever
    return (label, provenance.provider, provenance.model)


def _check_one_study(
    key: tuple[str, str | None, str | None], runs: Sequence[_LoadedRun]
) -> None:
    """Refuse to place two runs in one comparison when what was fixed was not.

    Every field of the record must be equal but the named exemptions (feature 014
    `contracts/provenance.md` 4): the run's identity, the record-only field and the study key
    always, so two models are two studies rather than one refusal; the arm across the arms; and
    across a pane study's arms what it varies, across a lever study's the studied lever's own
    flag. Each run is held against the first run of its own arm, and the first run of each arm
    against the study's first, so a difference within one arm is caught as well as one across
    them. There is no other exception.

    Then the repetitions, which is what stops a six-run set being one run counted six
    times: within an arm every `rep` is distinct, and a gated arm (`off` or `on`) has one
    at all. `adoption.MIN_REPS` counts runs, and without this it is satisfied by copies.
    A baseline arm is exempt from the second clause only: it gates nothing.
    """
    label = key[0]
    always = (*RUN_IDENTITY, *RECORD_ONLY, *STUDY_KEY_FIELDS)
    across = (*always, *ACROSS_ARMS, *(ACROSS_PANE_ARMS if label in PANE_STUDIES else ()))
    studied = label if label in LEVER_NAMES else None
    first_of_arm: dict[str | None, _LoadedRun] = {}
    for run in runs:
        assert run.provenance is not None
        arm = run.provenance.arm
        if arm in first_of_arm:
            _refuse_a_difference(first_of_arm[arm], run, exempt=always)
            continue
        first_of_arm[arm] = run
        if run is not runs[0]:
            _refuse_a_difference(runs[0], run, exempt=across, studied=studied)
    _check_key_digests(runs)
    _check_repetitions(runs)


def _refuse_a_difference(
    first: _LoadedRun,
    other: _LoadedRun,
    *,
    exempt: Sequence[str],
    studied: str | None = None,
) -> None:
    """Refuse `other` beside `first` on the first field of the record, in its own order, that
    differs and that `exempt` does not name.

    One loop over `RunProvenance.model_fields`, so a field added later must match until it is
    exempted by name. `efficiency` is compared flag by flag, so the refusal names the flag, and
    `studied`, the lever under test across a lever study's arms, is skipped. Each value is
    quoted by `_quoted`.
    """
    one, two = first.provenance, other.provenance
    assert one is not None and two is not None
    for name in RunProvenance.model_fields:
        if name in exempt:
            continue
        if name == "efficiency":
            pairs = [
                (f"efficiency.{flag}", getattr(one.efficiency, flag), getattr(two.efficiency, flag))
                for flag in LEVER_NAMES
                if flag != studied
            ]
        else:
            pairs = [(name, getattr(one, name), getattr(two, name))]
        for field, value, other_value in pairs:
            if value != other_value:
                raise CompareError(
                    f"{first.run_dir} and {other.run_dir} cannot be placed in one "
                    f"comparison: {field} differs ({_quoted(field, value)} against "
                    f"{_quoted(field, other_value)})"
                )


def _quoted(field: str, value: object) -> str:
    """A record's value as a must-match refusal quotes it: "not recorded" for an absent field
    `NOT_RECORDED_WHEN_ABSENT` names, its `repr` otherwise (owner decision 47A)."""
    if value is None and field in NOT_RECORDED_WHEN_ABSENT:
        return "not recorded"
    return repr(value)


def _check_key_digests(runs: Sequence[_LoadedRun]) -> None:
    """One key per package across a study (feature 014 INT-16): an arm scored against an
    edited key measures the edit, and a private key is not pinned by the commit."""
    seen: dict[str, tuple[str, Path]] = {}
    for run in runs:
        for package_id, digest in run.scorecard.key_sha256.items():
            first_digest, first_run = seen.setdefault(package_id, (digest, run.run_dir))
            if digest != first_digest:
                raise CompareError(
                    f"{first_run} and {run.run_dir} cannot be placed in one comparison: they "
                    f"were scored against two versions of {package_id}'s answer key "
                    f"(key_sha256 {first_digest} against {digest}); re-score both against one "
                    "key"
                )


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
    if lever in (TRIM_LEVER, "compact_queries"):
        return _histogram_counter(name, off, on)
    if lever == TIER_LEVER:
        return _withheld_counter(name, off, on)
    if lever in GATE_LEVERS:
        return _gate_counter(name, off, on)
    metric_name = COUNTER_METRIC.get(lever)
    if metric_name is None:
        return LeverCounter(name=name, off=None, on=None)
    stat = off_on(metric(off, metric_name), metric(on, metric_name))
    return LeverCounter(name=name, off=stat.off_median, on=stat.on_median)


def _withheld_total(run: ArmRun) -> float:
    """How many unresolved items withholding wrote across this run's packages."""
    return float(sum(score.unresolved_because_withheld for score in run.scorecard.per_package))


def _withheld_counter(
    name: str, off: Sequence[ArmRun], on: Sequence[ArmRun]
) -> LeverCounter:
    """Lever 4's counter: the median withheld half of the unresolved count, per arm (FR-054).

    The half the lever is *expected* to raise. The half it must not - `unresolved_other` -
    is a raw-row column rather than a counter, because it is read per package against the
    off arm's own row and an arm median would hide one package losing coverage while
    another gained it.
    """
    stat = off_on([_withheld_total(run) for run in off], [_withheld_total(run) for run in on])
    return LeverCounter(name=name, off=stat.off_median, on=stat.on_median)


def _repertoire(runs: Sequence[ArmRun]) -> set[str]:
    """Every tool name any run of this arm called, over every package it scored."""
    return {
        name
        for run in runs
        for score in run.scorecard.per_package
        for name in score.tool_calls_by_name
    }


def _histogram_counter(
    name: str, off: Sequence[ArmRun], on: Sequence[ArmRun]
) -> LeverCounter:
    """Lever 2's counter, read from `PackageScore.tool_calls_by_name` (T057).

    The number is how many distinct tools each arm called; the list beside it is what
    T059's gate actually reads. Both are taken over the **arm**, not over a run: a tool
    one on-run skipped and another called is still in the repertoire, and the worst case
    the ledger cares about is a tool the whole arm stopped picking.
    """
    off_tools = _repertoire(off)
    on_tools = _repertoire(on)
    return LeverCounter(
        name=name,
        off=float(len(off_tools)) if off else None,
        on=float(len(on_tools)) if on else None,
        dropped_tools=sorted(off_tools - on_tools) if off and on else [],
    )


def _gate_calls(run: ArmRun) -> float:
    """How many `check_fit` and `check_axial_stack` calls one run made, over its packages.

    Read from `PackageScore.tool_calls_by_name`, the same histogram lever 2's counter
    reads, so the gate's number and the repertoire's come from one record of what the model
    picked rather than from two.
    """
    return float(
        sum(
            count
            for score in run.scorecard.per_package
            for tool, count in score.tool_calls_by_name.items()
            if tool in GATE_TOOLS
        )
    )


def _gate_counter(name: str, off: Sequence[ArmRun], on: Sequence[ArmRun]) -> LeverCounter:
    """Levers 5 and 11: the arm medians, and the on-runs that fell below the off arm's floor.

    Both halves are needed and neither is the other. The medians say what the lever did to
    the two arms; `fell_in_runs` is the gate, because a lever that leaves the median alone
    and costs one run its fit checks has cost coverage the report cannot get back
    (feature 007 FR-034, SC-010).
    """
    off_totals = [_gate_calls(run) for run in off]
    on_totals = [_gate_calls(run) for run in on]
    stat = off_on(list(off_totals), list(on_totals))
    floor = min(off_totals) if off_totals else None
    return LeverCounter(
        name=name,
        off=stat.off_median,
        on=stat.on_median,
        fell_in_runs=(
            [run.run for run, total in zip(on, on_totals, strict=True) if total < floor]
            if floor is not None
            else []
        ),
    )


def _decision_row(
    key: tuple[str, str | None, str | None], runs: Sequence[_LoadedRun]
) -> LeverDecision:
    lever, provider, model = key
    arms = [(run, run.provenance.arm) for run in runs if run.provenance is not None]
    off = [_arm_run(run) for run, arm in arms if arm != "on"]
    on = [_arm_run(run) for run, arm in arms if arm == "on"]
    baseline = lever in BASELINE_LABELS

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
        recall_held_out_model=stats["recall_held_out_model"],
        recall_held_out_code=stats["recall_held_out_code"],
        median_net_saved_minutes=stats["median_net_saved_minutes"],
        worst_case_defects_lost=verdict.worst_case_defects_lost,
        lost_defect_ids=verdict.lost_defect_ids,
        lever_counter=_counter(lever, off, on),
        decision=verdict.decision,
        decision_reason=verdict.reason,
        run_dirs=[run.ledger_dir for run in runs],
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


# --- what a pane study's arms differed in (feature 014 `contracts/provenance.md` 3.5) ------


@dataclass(frozen=True)
class SettingsDiffered:
    """What a pane study's two arms differed in, and which recorded settings act on nothing on
    its provider (FR-052). The verdict prints both (US2-8)."""

    arms_differed_in: tuple[str, ...]
    """The efficiency and model-view fields whose values differ between the arms, in the
    record's field order."""

    inert: tuple[str, ...]
    """The settings the record names inert, whether or not the arms differed in them: Gemini's
    parallel calls are recorded off in both arms and made in parallel in both."""


def settings_differed(off: RunProvenance, on: RunProvenance) -> SettingsDiffered:
    """The settings the off and the on arm's records differ in, and the inert ones the record
    names (`inert_settings` matches across a study, so either arm's is the study's)."""
    off_settings, on_settings = _settings_of(off), _settings_of(on)
    return SettingsDiffered(
        arms_differed_in=tuple(
            name for name, value in on_settings.items() if value != off_settings[name]
        ),
        inert=on.inert_settings if on.inert_settings is not None else (),
    )


def _settings_of(record: RunProvenance) -> dict[str, object]:
    """A record's efficiency flags and model-view fields by name; a model view the record did
    not record reads each field unknown (`None`), which differs from any recorded value."""
    view = (
        record.model_view.model_dump()
        if record.model_view is not None
        else dict.fromkeys(ModelViewSettings.model_fields)
    )
    return {**record.efficiency.model_dump(), **view}


# --- the ledger --------------------------------------------------------------------


def _study_run(loaded: _LoadedRun) -> verdict.StudyRun:
    """The single conversion from compare's validated run to the shared verdict input."""
    assert loaded.provenance is not None
    return verdict.StudyRun(
        run=loaded.run, arm=loaded.provenance.arm, scorecard=loaded.scorecard,
    )


def _pane_refusal(
    key: tuple[str, str | None, str | None],
    runs: Sequence[_LoadedRun],
    saved_sets: Sequence[tuple[sets.BenchmarkSet, Path]],
    measurements: Sequence[tuple[Path, pilot.PilotMeasurement | _RefusedMeasurement]],
) -> str | None:
    """Read verdict.md section 7 in order, after all run-level checks have passed."""
    arms = {run.provenance.arm for run in runs if run.provenance is not None}
    missing = set(verdict.ARMS) - arms
    if missing:
        return f"arm {', '.join(sorted(arms))} present; arm {', '.join(sorted(missing))} has no run"
    if key[0] == PANE_STUDY:
        private = sorted({
            f"{ref.package_id} ({sets.path_form(ref.path, root=checkout)})"
            for saved, checkout in saved_sets for ref in saved.packages
            if sets.checkout_relative(ref.path, root=checkout) is None
        })
        if private:
            return (
                f"private entries: {', '.join(private)}; a pane study's set holds committed "
                "cases only; the private slice is its own study, `pane_defaults_private`"
            )
    for run in runs:
        rerun = f"re-run `swreview benchmark run` for {run.run_dir}"
        for score in run.scorecard.per_package:
            where = f"{run.run_dir} / {score.package_id}"
            if run.sessions[score.package_id].origin_marks is None:
                return f"{where}: session has no origin-marks record; {rerun}"
            for finding in score.false_alarm_finding_ids:
                if score.finding_origins.get(finding, "unknown") == "unknown":
                    return f"{where}: false alarm {finding} has origin unknown; {rerun}"
            if score.run_status.kind == "not_recorded":
                return f"{where}: run_status is not_recorded; {rerun}"
    if key[0] == PRIVATE_PANE_STUDY:
        return None
    count = min(run.scorecard.aggregate.held_out_model_defects for run in runs)
    if count < verdict.FLOOR:
        return f"keys name {count} held-out model-produced defects; the floor is {verdict.FLOOR}"
    if len(measurements) != 1:
        files = ", ".join(str(path) for path, _ in measurements) or "none"
        return (
            f"study {key}: expected one matching measurement with --pilot; "
            f"found {len(measurements)} ({files})"
        )
    path, measurement = measurements[0]
    digest_matches = (
        measurement.digest_matches if isinstance(measurement, _RefusedMeasurement)
        else pilot.sizing_digest(measurement) == measurement.sizing_digest
    )
    if not digest_matches:
        return f"{path}: the sizing was edited by hand; re-run `swreview benchmark pilot`"
    if isinstance(measurement, _RefusedMeasurement):
        return measurement.refusal
    if measurement.approval.approved is not True:
        return f"{path}: approval.approved is not true"
    approved_at = measurement.approval.approved_at
    if not approved_at or not approved_at.strip():
        return f"{path}: approval.approved_at is empty"
    try:
        approved_date = date.fromisoformat(approved_at)
        if approved_date.isoformat() != approved_at:
            raise ValueError("expected YYYY-MM-DD")
    except ValueError:
        return f"{path}: approval.approved_at {approved_at!r} is not a YYYY-MM-DD date"
    result = measurement.sizing.result
    if result.alpha is None:
        return (f"{path}: sizing.result.alpha reached no level; "
                "the approved sizing cannot set the rule")
    for field, value in result.simulated.model_dump().items():
        if value is None or not math.isfinite(value) or not 0 <= value <= 1:
            return (f"{path}: sizing.result.simulated.{field} is {value!r}; "
                    "the approved sizing requires a known rate in [0, 1]")
    earliest = min(run.provenance.started_at.date() for run in runs)
    if approved_date > earliest:
        return (
            f"{path}: approval.approved_at {approved_at} is later than earliest study run "
            f"{earliest.isoformat()}; levels chosen after the paid runs void the 5% bounds"
        )
    sizing = measurement.sizing
    if count < sizing.result.held_out_model_defects:
        return (
            f"keys name {count} held-out model-produced defects; approval requires "
            f"{sizing.result.held_out_model_defects}"
        )
    for arm in verdict.ARMS:
        reps = {run.provenance.rep for run in runs if run.provenance.arm == arm}
        if len(reps) < sizing.result.reps:
            return (f"arm {arm} has {len(reps)} distinct repetitions; approval requires "
                    f"{sizing.result.reps}")
    pilot_packages = set(sizing.pilot_packages)
    if (pilot_packages or sizing.growth_units) and len(saved_sets) < len(runs):
        missing_sets = ", ".join(run.run for run in runs
                                 if not (run.run_dir / SAVED_SET_FILE).is_file())
        return (f"{missing_sets}: missing saved set; approval requires every pilot package "
                f"and {sizing.growth_units} growth units")
    core = {
        score.package_id for run in runs for score in run.scorecard.per_package
        if any(item.kind == "known_defect" and item.tag == "held_out"
               for item in score.graded_items)
    }
    for saved, _ in saved_sets:
        ids = {ref.package_id for ref in saved.packages}
        missing_packages = sorted(pilot_packages - ids)
        growth = len((ids & core) - pilot_packages)
        if missing_packages or growth < sizing.growth_units:
            return (
                f"saved set missing pilot packages: {', '.join(missing_packages) or 'none'}; "
                f"found {growth} growth units; approval requires {sizing.growth_units}"
            )
    return None


def _pane_noise_floor(key, runs, records, notes) -> verdict.NoiseFloor:
    matching = [(path, record) for path, record in records
                if (record.study, record.provider, record.model) == key]
    if len(matching) != 1:
        if matching:
            notes.append(f"study {key}: multiple noise-floor records: "
                         + ", ".join(str(path) for path, _ in matching))
        return verdict.NoiseFloor(state="not_computed", points=None, seed=None, numpy=None)
    path, record = matching[0]
    current = simulate.runs_digest([run.run_dir for run in runs], relative_to=path.parent)
    return verdict.NoiseFloor(
        state="computed" if current == record.runs_digest else "stale",
        points=record.result, seed=record.seed, numpy=record.numpy_version,
    )


@dataclass(frozen=True)
class _RefusedMeasurement:
    """Valid routing/raw-row metadata beside an invalid approval or sizing result."""

    identity: pilot.PilotIdentity
    pilot_runs: list[pilot.PilotRun]
    digest_matches: bool
    refusal: str


def _read_measurement_for_compare(path: Path) -> pilot.PilotMeasurement | _RefusedMeasurement:
    try:
        return pilot.read_measurement(path)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        # These are verdict-only inputs. Other malformed measurement data still
        # use the strict reader's ordinary error, without inventing a study key.
        if any(error["loc"][:1] != ("approval",)
               and error["loc"][:2] != ("sizing", "result") for error in errors):
            raise
        record = json.loads(path.read_bytes())
        computed = {
            name: record[name]
            for name in ("identity", "pilot_runs", "smoke_runs", "measured", "sizing")
        }
        fields = "; ".join(
            f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in errors
        )
        return _RefusedMeasurement(
            identity=pilot.PilotIdentity.model_validate(record["identity"]),
            pilot_runs=[pilot.PilotRun.model_validate(row) for row in record["pilot_runs"]],
            digest_matches=benchmark_digest.canonical_sha256(computed) == record["sizing_digest"],
            refusal=f"{path}: {fields}",
        )


def _measurement_key(
    measurement: pilot.PilotMeasurement | _RefusedMeasurement,
) -> tuple[str, str, str]:
    identity = measurement.identity
    return identity.study, identity.provider, identity.model


def _pane_study(key, runs, matching, noise_floors, *, root, notes) -> verdict.PaneStudy:
    saved_sets = [
        (sets.load_saved_set(run.run_dir / SAVED_SET_FILE, root=root), root)
        for run in runs if (run.run_dir / SAVED_SET_FILE).is_file()
    ]
    refusal = _pane_refusal(key, runs, saved_sets, matching)
    record = runs[0].provenance
    private = key[0] == PRIVATE_PANE_STUDY
    block = verdict.PaneStudy(
        study=key[0], provider=key[1], model=key[2], commit=record.commit or UNKNOWN,
        slice="private" if private else "committed", run_dirs=[run.ledger_dir for run in runs],
        reps=verdict.Repetitions(**{
            arm: len({run.provenance.rep for run in runs if run.provenance.arm == arm})
            for arm in verdict.ARMS
        }),
        verdict=None, reasons=[], refusal=refusal, approval=None, figures=None,
        code_guard=None, cleared_guard=None,
        noise_floor=verdict.NoiseFloor(state="not_computed", points=None, seed=None, numpy=None),
        arms_differed_in=[], inert=[], untested_between_turns=[], shown=[],
    )
    if refusal:
        return block
    rules = verdict.VerdictRules(alpha=0.025, cleared_guard_decides=False)
    if not private:
        path, measurement = matching[0]
        result = measurement.sizing.result
        rules = verdict.VerdictRules(result.alpha, result.cleared_guard_decides)
        block.approval = verdict.StudyApproval(
            file_sha256=benchmark_digest.sha256_of(path),
            approved_at=measurement.approval.approved_at,
            alpha=result.alpha, held_out_model_defects=result.held_out_model_defects,
            reps=result.reps, cleared_guard_decides=result.cleared_guard_decides,
            seed=measurement.sizing.seed, simulated=result.simulated.model_dump(),
        )
    judged = verdict.judge(verdict.study_stats([_study_run(run) for run in runs]), rules)[0]
    block.figures = judged.figures
    block.code_guard = judged.code_guard
    block.cleared_guard = judged.cleared_guard
    block.verdict = None if private else judged.verdict
    block.reasons = ([
        "private slice (23A): shown beside the pane study's verdict, never deciding"
    ] if private else judged.reasons)
    block.shown = _pane_shown(runs, judged)
    block.noise_floor = _pane_noise_floor(key, runs, noise_floors, notes)
    off, on = (next(run.provenance for run in runs if run.provenance.arm == arm)
               for arm in verdict.ARMS)
    settings = settings_differed(off, on)
    block.arms_differed_in = list(settings.arms_differed_in)
    block.inert = list(settings.inert)
    answer_turns = any(ref.held_out and ref.case_file is not None
                       for saved, _ in saved_sets for ref in saved.packages)
    if not answer_turns:
        block.untested_between_turns = [verdict.UntestedSetting(
            setting=name, reason="acts only between turns; no held-out case takes an answer "
            "turn, so the verdict does not test it; the anchors show it",
        ) for name in settings.arms_differed_in
            if name in BETWEEN_TURN_SETTINGS and name not in settings.inert]
    return block


def load_runs(
    run_dirs: Sequence[Path | str], *, root: Path | None = None,
    committed_ledger: bool = False,
) -> list[_LoadedRun]:
    """Read run folders in order and apply compare's run and study checks once.

    With ``committed_ledger``, each run is first held to the committed ledger's
    refusal, which comes before any study check (FR-051).
    """
    checkout = sets.REPO_ROOT if root is None else root
    loaded = [_load_run(path, root=checkout) for path in distinct_run_dirs(run_dirs)]
    if committed_ledger:
        for run in loaded:
            _refuse_for_the_committed_ledger(run, root=checkout)
    studies: dict[tuple[str, str | None, str | None], list[_LoadedRun]] = {}
    for run in loaded:
        key = _study_key(run)
        if key is not None:
            studies.setdefault(key, []).append(run)
    for key, runs in studies.items():
        _check_one_study(key, runs)
    return loaded


def run_records(
    run_dirs: Sequence[Path | str], *, root: Path | None = None,
) -> list[pilot.RunRecord]:
    """Expose loaded off/on runs through the shared verdict converter and saved-set reader."""
    checkout = sets.REPO_ROOT if root is None else root
    records: list[pilot.RunRecord] = []
    for run in load_runs(run_dirs, root=checkout):
        if run.provenance is None:
            raise CompareError(
                f"{run.run_dir}: no provenance record; the pilot and the noise floor "
                "read benchmark run folders only",
            )
        records.append(pilot.RunRecord(
            study_run=_study_run(run),
            folder=run.run_dir,
            provenance=run.provenance,
            sessions=run.sessions,
            saved_set=sets.load_saved_set(run.run_dir / SAVED_SET_FILE, root=checkout),
        ))
    return records


def compare_runs(
    run_dirs: Sequence[Path | str],
    *,
    root: Path | None = None,
    committed_ledger: bool = False,
    pilots: Sequence[Path | str] = (),
    noise_floors: Sequence[Path | str] = (),
    notes: list[str] | None = None,
) -> Ledger:
    """Read N run directories and build the ledger. Contacts nothing and starts nothing.

    `root` is the checkout a saved set's relative entries resolve against and a run folder
    inside it is named relative to: `sets.REPO_ROOT`, read at call time, unless the caller names
    another (feature 014 `contracts/provenance.md` 6.1, 6.3). `committed_ledger` says the ledger
    is written where the repository may commit it, which refuses every run
    `_refuse_for_the_committed_ledger` names (6.4). Every study is checked; a pane study renders
    its raw rows and the shared judge's block, with no lever decision row.
    """
    checkout = sets.REPO_ROOT if root is None else root
    loaded = load_runs(run_dirs, root=checkout, committed_ledger=committed_ledger)
    rows = [_row(run, score) for run in loaded for score in run.scorecard.per_package]

    studies: dict[tuple[str, str | None, str | None], list[_LoadedRun]] = {}
    for run in loaded:
        key = _study_key(run)
        if key is not None:
            studies.setdefault(key, []).append(run)
    messages = [] if notes is None else notes
    measurements = [(Path(path), _read_measurement_for_compare(Path(path))) for path in pilots]
    floors = [(Path(path), simulate.read_noise_floor(path)) for path in noise_floors]
    matched: dict[
        tuple[str, str, str], list[tuple[Path, pilot.PilotMeasurement | _RefusedMeasurement]],
    ] = {}
    for path, measurement in measurements:
        key = _measurement_key(measurement)
        matched.setdefault(key, []).append((path, measurement))
        if key not in studies or key[0] not in PANE_STUDIES:
            messages.append(f"{path}: pilot measurement matches no compared study {key}")
    pane_studies = [
        _pane_study(key, runs, matched.get(key, []), floors, root=checkout, notes=messages)
        for key, runs in studies.items() if key[0] in PANE_STUDIES
    ]
    for key in studies:
        matching = matched.get(key, [])
        if key[0] not in PANE_STUDIES or len(matching) != 1:
            continue
        path, measurement = matching[0]
        for listed in measurement.pilot_runs:
            folder = (path.parent / listed.folder).resolve()
            try:
                loaded_pilot = _load_run(folder, root=checkout)
            except CompareError as exc:
                messages.append(f"pilot {folder}: {' '.join(str(exc).splitlines())}")
                continue
            if committed_ledger:
                _refuse_for_the_committed_ledger(loaded_pilot, root=checkout)
            rows.extend(_row(loaded_pilot, score).model_copy(update={"arm": "off (pilot)"})
                        for score in loaded_pilot.scorecard.per_package)

    return Ledger(
        runs=rows,
        pane_studies=pane_studies,
        levers=[
            _decision_row(key, runs)
            for key, runs in studies.items()
            if key[0] not in PANE_STUDIES
        ],
    )


def distinct_run_dirs(run_dirs: Sequence[Path | str]) -> list[Path]:
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


def recorded_pilots(pilots_dir: Path | str = PILOTS_DIR) -> list[Path]:
    """Every stored pilot measurement, apart from the study run tree."""
    return sorted(Path(pilots_dir).rglob("pilot-measurement.json"))


def recorded_noise_floors(studies_dir: Path | str = STUDIES_DIR) -> list[Path]:
    """Every stored noise-floor record, without running a simulation."""
    return sorted(Path(studies_dir).rglob("noise-floor.json"))


def refused_pane_studies(ledger: Ledger) -> list[verdict.PaneStudy]:
    return [study for study in ledger.pane_studies if study.refusal is not None]


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


def format_count(value: float | None) -> str:
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
        f"{format_count(stat.off_median)} ({format_count(stat.off_min)}-"
        f"{format_count(stat.off_max)}, n={stat.off_rows}) -> {format_count(stat.on_median)} "
        f"({format_count(stat.on_min)}-{format_count(stat.on_max)}, n={stat.on_rows}), {delta}"
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
    "explanations",
    "model view",
    "profile",
    "live tools",
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
    "flagged",
    "below expected",
    "status mismatch",
    "cleared",
    "false alarms",
    "contradicted",
    "confirmed",
    "unresolved",
    "unresolved withheld",
    "unresolved other",
    "coverage bucket mix",
    "findings by origin",
    "false alarms by origin",
)
"""The run table's final order, fixed up front (feature 014 `contracts/provenance.md` 5; plan
decision INT-10), so the committed header is regenerated once. No run-status column: its source
arrives with the robustness slice, and a column added then would regenerate it a second time."""

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
    "Recall by producer (held out) off -> on",
    "Median net saved minutes off -> on",
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


def _mix(counts: Mapping[str, int]) -> str:
    """A mix, `name count / name count / ...`, in the order `counts` holds."""
    return " / ".join(f"{name} {count}" for name, count in counts.items())


def _model_view_cell(view: ModelViewSettings) -> str:
    """`pane` for `MODEL_VIEW_PANE`, otherwise the switches that are on, `slimming`, `pruning
    after N` or both, and `off` with neither: `MODEL_VIEW_OFF`, and a view whose prune count
    differs with pruning itself off (feature 014 `contracts/provenance.md` 5)."""
    if view == MODEL_VIEW_PANE:
        return "pane"
    switches = [
        *(["slimming"] if view.payload_slimming else []),
        *([f"pruning after {view.prune_after_rounds}"] if view.history_pruning else []),
    ]
    return ", ".join(switches) or "off"


def _profile_cell(row: RunRow) -> str:
    """The profile's digest through `display_digest`, the one 12-character reading (plan decision
    RF-5); `none` with no profile, and `unknown` where the record does not say."""
    if not row.profile_recorded:
        return UNKNOWN
    return "none" if row.profile_digest is None else display_digest(row.profile_digest)


def _yes_no(value: bool | None) -> str:
    return UNKNOWN if value is None else ("yes" if value else "no")


def _run_line(row: RunRow) -> str:
    cells = (
        row.run,
        _text(row.commit),
        _text(row.lever),
        _text(row.arm),
        _text(row.rep),
        _text(row.provider),
        _text(row.model),
        _text(row.effort),
        "on" if row.explanations_enabled else "off",
        _model_view_cell(row.model_view),
        _profile_cell(row),
        _yes_no(row.live_tools),
        row.package_id,
        format_count(row.input_tokens),
        format_count(row.cached_input_tokens),
        format_count(row.uncached_input_tokens),
        format_count(row.output_tokens),
        format_count(row.reasoning_tokens),
        format_count(row.tool_result_input_tokens),
        format_count(row.total_tokens),
        format_count(row.rounds),
        format_count(row.tool_calls),
        _share(row.cached_input_share),
        format_count(row.wall_clock_s),
        format_count(row.seconds_to_first_finding),
        format_count(row.valid_findings),
        format_count(row.missed_known_defects),
        format_count(row.flagged),
        format_count(row.flagged_below_expected),
        format_count(row.status_mismatches),
        format_count(row.cleared),
        format_count(row.false_alarms),
        fmt_assessed(row.contradictions),
        fmt_assessed(row.confirmations),
        format_count(row.unresolved_count),
        format_count(row.unresolved_because_withheld),
        format_count(row.unresolved_other),
        _mix(row.coverage_bucket_mix),
        fmt_origins(row.findings_by_origin, separator=" / "),
        fmt_origins(row.false_alarms_by_origin, separator=" / "),
    )
    return "| " + " | ".join(cells) + " |"


def _counter_cell(counter: LeverCounter) -> str:
    """The counter column: the name, the two numbers, then whichever worst case applies.

    Lever 2's is the tools the on arm stopped calling; levers 5 and 11's is the runs whose
    fit and stack counts fell. Both render the same way - after the medians, by name - so
    a reader scanning the column sees the gate's verdict without opening the JSON.
    """
    cell = f"{counter.name}: {format_count(counter.off)} -> {format_count(counter.on)}"
    if counter.dropped_tools:
        cell += "; no longer called: " + ", ".join(counter.dropped_tools)
    if counter.fell_in_runs:
        cell += "; fell below the off arm in: " + ", ".join(counter.fell_in_runs)
    return cell


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


def _recall_by_producer(row: LeverDecision) -> str:
    """Each producer's held-out recall, named, off -> on (feature 014 SP-13 A)."""
    return (
        f"model: {_off_on(row.recall_held_out_model)} ; "
        f"code: {_off_on(row.recall_held_out_code)}"
    )


def _lever_line(row: LeverDecision) -> str:
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
        _recall_by_producer(row),
        _off_on(row.median_net_saved_minutes),
        format_count(row.worst_case_defects_lost),
        _counter_cell(row.lever_counter),
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
        "",
        "`tool calls` is `len(session.steps)`, every step of the review: the pre-run's and the "
        "regrade's steps are counted with the model's, not split by the step mark.",
    ]
    if ledger.pane_studies:
        lines += _render_pane_studies(ledger)
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


def _pane_measure(
    runs: Sequence[_LoadedRun],
    name: str,
    reading: Callable[[PackageScore, _LoadedRun], float | None],
    *,
    units: Callable[[PackageScore], int] | None = None,
    completed: bool = False,
) -> verdict.ShownMeasure:
    """Average repetitions within packages before making the shown paired interval.

    Defect rates carry the package's number of graded defects as their weight;
    counts carry one package. An unassessed value supplies neither a zero nor a
    package to the interval.
    """
    samples: dict[str, dict[str, list[tuple[float, float]]]] = {"off": {}, "on": {}}
    for run in runs:
        assert run.provenance is not None
        arm = run.provenance.arm
        assert arm in samples
        unscored = {row.package_id for row in run.scorecard.unscored_packages}
        for score in run.scorecard.per_package:
            if score.package_id in unscored:
                continue
            if completed and score.run_status.kind != "completed":
                continue
            value = reading(score, run)
            weight = units(score) if units is not None else 1
            if value is None or weight == 0:
                continue
            samples[arm].setdefault(score.package_id, []).append((float(value), float(weight)))
    means = {
        arm: {
            package: (
                sum(value for value, _ in values) / len(values),
                sum(weight for _, weight in values) / len(values),
            )
            for package, values in packages.items()
        }
        for arm, packages in samples.items()
    }

    def arm_value(arm: str) -> float | None:
        total = sum(weight for _, weight in means[arm].values())
        return sum(value for value, _ in means[arm].values()) / total if total else None

    differences, weights = [], []
    for package in sorted(means["off"].keys() & means["on"].keys()):
        off, off_units = means["off"][package]
        on, on_units = means["on"][package]
        weight = min(off_units, on_units)
        differences.append((on / on_units - off / off_units) * weight)
        weights.append(weight)
    interval = pane_stats.package_interval(differences, weights, alpha=0.05, sides=2)
    return verdict.ShownMeasure(
        name=name,
        off=arm_value("off"),
        on=arm_value("on"),
        estimate=interval.estimate,
        lower=interval.lower,
        upper=interval.upper,
        excludes_zero=(
            interval.lower is not None and interval.upper is not None
            and (interval.lower > 0 or interval.upper < 0)
        ),
    )


def _pane_defect_ids(score: PackageScore, producer: str, tag: str | None = None) -> set[str]:
    return {
        item.id for item in score.graded_items
        if item.kind == "known_defect" and item.producer == producer
        and (tag is None or item.tag == tag)
    }


def _pane_detection_history(
    runs: Sequence[_LoadedRun], producer: str, tag: str | None = None,
) -> dict[tuple[str, str], dict[str, list[bool]]]:
    """The completed-run observations needed to name descriptive defect groups."""
    history: dict[tuple[str, str], dict[str, list[bool]]] = {}
    for run in runs:
        assert run.provenance is not None
        arm = run.provenance.arm
        assert arm in ("off", "on")
        for score in run.scorecard.per_package:
            if score.run_status.kind != "completed":
                continue
            detected = verdict.detected_ids(score)
            for defect in _pane_defect_ids(score, producer, tag):
                history.setdefault((score.package_id, defect), {"off": [], "on": []})[
                    arm
                ].append(defect in detected)
    return history


def _pane_shown(
    runs: Sequence[_LoadedRun], result: verdict.StudyVerdict,
) -> list[verdict.ShownMeasure]:
    """Section 6's descriptive columns, kept separate from the shared judge."""
    shown: list[verdict.ShownMeasure] = []

    def add(name, reading, **kwargs):
        shown.append(_pane_measure(runs, name, reading, **kwargs))

    for name, producer, tag in (
        ("recall on tuned-on model-produced defects", "model", "tuned_on"),
        ("detection of code-produced defects", "code", None),
    ):
        add(
            name,
            lambda score, run, producer=producer, tag=tag: len(
                _pane_defect_ids(score, producer, tag)
                & verdict.detected_ids(score)
            ),
            units=lambda score, producer=producer, tag=tag: len(
                _pane_defect_ids(score, producer, tag)
            ),
            completed=True,
        )
    add(
        "hits on tuned-on forbidden entries",
        lambda score, run: (
            len(set(score.forbidden_hit_finding_ids) & set(score.tuned_on_false_alarm_finding_ids))
            if score.forbidden_hit_finding_ids is not None and any(
                item.kind == "forbidden_entry" and item.tag == "tuned_on"
                for item in score.graded_items
            ) else None
        ),
    )
    for name, column in (
        ("contradicted correct conditions", "contradicted_condition_ids"),
        ("confirmed correct conditions", "confirmed_condition_ids"),
    ):
        add(name, lambda score, run, column=column: length_or_none(getattr(score, column)))
    for origin in by_origin(()):
        add(
            f"false alarms: {origin}",
            lambda score, run, origin=origin: by_origin(false_alarm_origins(score))[origin],
        )
    add("false alarms", lambda score, run: score.false_alarms)
    for origin in by_origin(()):
        add(
            f"findings: {origin}",
            lambda score, run, origin=origin: by_origin(final_state_origins(score))[origin],
        )
    add("valid findings", lambda score, run: score.valid_findings)
    add("detected defects", lambda score, run: len(
        verdict.detected_ids(score)
    ))
    for name, column in (
        ("flagged defects", "flagged_defect_ids"),
        ("missed known defects", "missed_defect_ids"),
    ):
        add(name, lambda score, run, column=column: len(getattr(score, column)))
    add("carried findings", lambda score, run: score.carried_findings)
    for name, column in (
        ("flagged below expected", "flagged_below_expected_defect_ids"),
        ("status mismatches", "status_mismatch_defect_ids"),
        ("forbidden hits", "forbidden_hit_finding_ids"),
        ("withdrawn forbidden hits", "withdrawn_forbidden_hit_finding_ids"),
        ("coverage mismatches", "coverage_mismatches"),
    ):
        add(name, lambda score, run, column=column: length_or_none(getattr(score, column)))
    add("unresolved findings", lambda score, run: score.unresolved_count)
    add("unresolved coverage", lambda score, run: score.coverage_bucket_mix.get(
        "unresolved", score.unresolved_because_withheld + score.unresolved_other,
    ))
    add("unresolved because withheld", lambda score, run: score.unresolved_because_withheld)
    add("unresolved other", lambda score, run: score.unresolved_other)
    buckets = sorted({
        bucket for run in runs for score in run.scorecard.per_package
        for bucket in score.coverage_bucket_mix
    })
    for bucket in buckets:
        add(
            f"coverage: {bucket}",
            lambda score, run, bucket=bucket: score.coverage_bucket_mix.get(bucket, 0),
        )
    add("unanswerable requests", lambda score, run: length_or_none(score.unanswerable_requests))
    for name, seen in (("re-asks seen", True), ("re-asks refused", False)):
        add(name, lambda score, run, seen=seen: (
            sum((row.outcome == "recorded") == seen for row in score.re_asks)
            if score.re_asks is not None else None
        ))
    add("repeats of open questions", lambda score, run: length_or_none(score.open_repeats))
    add("unmatched requests", lambda score, run: length_or_none(score.unmatched_requests))
    add("question-count misses", lambda score, run: (
        sum(row.missed for row in score.question_counts)
        if score.question_counts is not None else None
    ))
    add("unscripted questions", lambda score, run: length_or_none(score.unscripted_questions))
    add("bound-reached reviews", lambda score, run: (
        int(score.bound_reached) if score.bound_reached is not None else None
    ))
    add("fit and axial-stack calls per run", lambda score, run: sum(
        count for tool, count in score.tool_calls_by_name.items() if tool in GATE_TOOLS
    ))
    failure_classes = sorted({
        attempt.class_ or UNKNOWN for run in runs for attempt in run.scorecard.failed_attempts
    } | {
        package.class_ or UNKNOWN for run in runs for package in run.scorecard.unscored_packages
    })
    for failure_class in failure_classes:
        add(
            f"failures: infrastructure/{failure_class}",
            lambda score, run, failure_class=failure_class: sum(
                attempt.package_id == score.package_id
                and (attempt.class_ or UNKNOWN) == failure_class
                for attempt in run.scorecard.failed_attempts
            ),
        )
    stop_classes = sorted({
        score.run_status.class_ or UNKNOWN for run in runs for score in run.scorecard.per_package
        if score.run_status.kind == "behavioural"
    })
    for stop_class in stop_classes:
        add(
            f"behavioural stops: {stop_class}",
            lambda score, run, stop_class=stop_class: int(
                score.run_status.kind == "behavioural"
                and (score.run_status.class_ or UNKNOWN) == stop_class
            ),
        )

    code_history = _pane_detection_history(runs, "code")
    sometimes = {
        (ref.package_id, ref.defect_id) for ref in result.code_guard.off_only_sometimes
    } | {
        key for key, arms in code_history.items()
        if arms["off"] and any(arms["off"]) and not all(arms["off"])
    }
    sometimes_name = "code-produced defects detected only sometimes by off arm"
    add(sometimes_name, lambda score, run: (
        sum((score.package_id, defect) in sometimes for defect in
            verdict.detected_ids(score))
        if score.run_status.kind == "completed" else 0
    ))
    add("cleared defects", lambda score, run: len(score.cleared_defect_ids))
    held_history = _pane_detection_history(runs, "model", "held_out")
    every = {
        key for key, arms in held_history.items()
        if arms["off"] and arms["on"] and all(arms["off"]) and all(arms["on"])
    }
    never = {
        key for key, arms in held_history.items()
        if arms["off"] and arms["on"] and not any(arms["off"]) and not any(arms["on"])
    }
    every_name = "held-out model-produced defects detected on every counted run of both arms"
    never_name = "held-out model-produced defects detected on no counted run"
    for name, selected in ((every_name, every), (never_name, never)):
        add(name, lambda score, run, selected=selected: sum(
            package == score.package_id for package, _ in selected
        ))

    # Names carry the descriptive identities: ShownMeasure deliberately has only
    # numeric cells, while the judge's separate guards retain their strict models.
    for package, defect in sorted(sometimes):
        add(
            f"{sometimes_name}: {package}/{defect}; the off arm detected it only sometimes",
            lambda score, run, package=package, defect=defect: (
                int(defect in verdict.detected_ids(score))
                if score.package_id == package and score.run_status.kind == "completed"
                else (0 if score.package_id == package else None)
            ),
        )
    cleared = sorted({
        (score.package_id, defect) for run in runs for score in run.scorecard.per_package
        for defect in score.cleared_defect_ids
    })
    for package, defect in cleared:
        arm_runs = {
            arm: sorted({
                run.run for run in runs if run.provenance is not None
                and run.provenance.arm == arm for score in run.scorecard.per_package
                if score.package_id == package and defect in score.cleared_defect_ids
            }) for arm in ("off", "on")
        }
        add(
            f"cleared defects: {package}/{defect}; runs off: "
            f"{', '.join(arm_runs['off']) or 'none'}; on: {', '.join(arm_runs['on']) or 'none'}",
            lambda score, run, package=package, defect=defect: (
                int(defect in score.cleared_defect_ids) if score.package_id == package else None
            ),
        )
    for name, selected in ((every_name, every), (never_name, never)):
        for package, defect in sorted(selected):
            add(
                f"{name}: {package}/{defect}",
                lambda score, run, package=package: 1 if score.package_id == package else None,
            )
    return shown


def _pane_points(value: float | None) -> str:
    return UNKNOWN if value is None else f"{value * 100:.1f} points"


def _pane_reference(reference: verdict.DefectRef) -> str:
    return f"{reference.package_id}/{reference.defect_id}"


def _pane_runs(reference: verdict.DefectRuns) -> str:
    return f"{_pane_reference(reference)}; runs {', '.join(reference.runs) or 'none'}"


def _render_pane_studies(ledger: Ledger) -> list[str]:
    """Render the data-only pane blocks without evaluating any verdict rule."""
    if not ledger.pane_studies:
        return []
    lines = ["", "### Pane study", ""]
    for pane in ledger.pane_studies:
        lines += [
            f"#### {pane.study}: {pane.provider} {pane.model}", "",
            f"Verdict: {_text(pane.verdict)}.",
            "Reasons: " + ("; ".join(pane.reasons) or "none") + ".",
        ]
        if pane.refusal is not None:
            lines.append(f"Refusal: {pane.refusal}")
        lines += ["", *_header((
            "Paired rule", "Estimate (points)", "Interval (points)", "Level",
            "Packages", "Retained defects", "Result",
        ))]
        if pane.figures is not None:
            for figure_name in verdict.FIGURES:
                figure = getattr(pane.figures, figure_name)
                for rule_name, rule in (
                    ("recall", figure.recall), ("false alarms", figure.false_alarms),
                ):
                    level = 0.95 if pane.slice == "private" else 1 - rule.alpha
                    state = "loss" if rule.loss else (
                        "no loss" if rule.computable else "not computable"
                    )
                    cells = (
                        f"{figure_name} {rule_name}", _pane_points(rule.estimate),
                        f"{_pane_points(rule.lower)} to {_pane_points(rule.upper)}", f"{level:.1%}",
                        str(rule.packages), str(figure.retained_defects), state,
                    )
                    lines.append("| " + " | ".join(cells) + " |")
        else:
            lines.append(f"| {UNKNOWN} | {UNKNOWN} | {UNKNOWN} | {UNKNOWN} | "
                         f"{UNKNOWN} | {UNKNOWN} | {UNKNOWN} |")
        code = pane.code_guard
        cleared = pane.cleared_guard
        lines += [
            "", "Code guard: " + (
                "lost: " + ("; ".join(_pane_runs(ref) for ref in code.lost) or "none")
                + "; off only sometimes: "
                + ("; ".join(f"{_pane_reference(ref)}: {ref.reason}"
                             for ref in code.off_only_sometimes) or "none")
                + "; skipped: "
                + ("; ".join(f"{_pane_reference(ref)}: {ref.reason}"
                             for ref in code.skipped) or "none")
                if code is not None else UNKNOWN
            ),
            "Cleared guard: " + (
                f"decides {_yes_no(cleared.decides)}; "
                + ("; ".join(_pane_runs(ref) for ref in cleared.named) or "none")
                if cleared is not None else UNKNOWN
            ),
            "", "Dropped:",
        ]
        if pane.figures is not None:
            for name in verdict.FIGURES:
                figure = getattr(pane.figures, name)
                defects = ", ".join(
                    _pane_reference(ref) for ref in figure.dropped_defects
                ) or "none"
                packages = ", ".join(figure.dropped_packages) or "none"
                lines.append(f"- {name}: defects {defects}; packages {packages}.")
        else:
            lines.append(UNKNOWN)
        approval = pane.approval
        lines += ["", "Approval: " + (
            f"{approval.approved_at}; size {approval.held_out_model_defects}; "
            f"repetitions {approval.reps}; alpha {approval.alpha:g}; "
            f"cleared guard {_yes_no(approval.cleared_guard_decides)}; seed {approval.seed}; "
            "simulated " + ", ".join(
                f"{name}={value:g}" for name, value in approval.simulated.model_dump().items()
            ) if approval is not None else UNKNOWN
        )]
        noise = pane.noise_floor
        if noise.state == "stale":
            noise_text = "stale: computed over other runs"
        elif noise.state == "not_computed":
            noise_text = "not computed: run swreview benchmark noise-floor"
        else:
            points = noise.points if isinstance(noise.points, str) else (
                UNKNOWN if noise.points is None else f"{format_count(noise.points)} points"
            )
            noise_text = f"{points}; seed {_text(noise.seed)}; numpy {_text(noise.numpy)}"
        lines += [
            "", f"Noise floor: {noise_text}.",
            "", "Settings the arms differed in: "
            + (", ".join(pane.arms_differed_in) or "none") + ".",
            "Recorded inert: " + (", ".join(pane.inert) or "none") + ".",
            "Settings the verdict does not test: " + (
                "; ".join(f"{item.setting}: {item.reason}" for item in pane.untested_between_turns)
                or "none"
            ) + ".",
            "", "Shown (per package, or defect rate where named; two-sided 95% intervals):", "",
            *_header(("Measure", "Off", "On", "Difference", "95% interval", "Excludes zero")),
        ]
        rate_names = {
            "recall on tuned-on model-produced defects", "detection of code-produced defects",
        }
        for measure in pane.shown:
            number = _pane_points if measure.name in rate_names else format_count
            absent = measure.off is None and measure.on is None
            cells = (
                measure.name,
                "not assessed" if absent else number(measure.off),
                "not assessed" if absent else number(measure.on),
                number(measure.estimate), f"{number(measure.lower)} to {number(measure.upper)}",
                _yes_no(measure.excludes_zero),
            )
            lines.append("| " + " | ".join(cells) + " |")
        changes = [
            f"{measure.name} {'fell' if measure.estimate < 0 else 'rose'}"
            for measure in pane.shown if measure.excludes_zero and measure.estimate is not None
        ]
        if changes:
            lines += ["", "Shown changes whose interval excludes zero: " + "; ".join(changes) + "."]
        lines.append("")
    return lines
