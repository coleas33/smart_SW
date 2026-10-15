"""Run the reviewer over every package in a benchmark set (T096, runner half).

This module iterates `swreview.benchmark.sets.BenchmarkSet.packages` and calls a
review function per attempt under `attempts/<package_id>/<n>/`, promoting kept output
to `<out_dir>/<package_id>/`. It
never opens an answer key, and it refuses - a second time, on top of
`swreview.benchmark.sets.load_set` - to pass a package path that resolves under
`benchmarks/answer_keys/` (constitution Principle VI, FR-025): defense in depth, not
trust in a single check.

The provider is chosen once, for the whole set, and forwarded to every package as a
name (`openai`, `gemini`, `fake`) rather than as a built adapter: this module knows
nothing about provider SDKs, and a set of many packages must not share one adapter's
per-turn state. `swreview.cli` builds the adapter per package through its
`provider_factory` hook, which is also what the default `review_fn` below defers to
rather than duplicating the wiring.

## The run provenance record (feature 005)

`RunProvenance` is the second, independent record of what produced a run folder
(contracts/ab-harness.md sections 2 and 3). The runner writes `session.efficiency` from
the settings it resolved; `swreview.cli` writes this record from the `--lever`,
`--study`, `--arm` and `--rep` options actually typed, and `swreview benchmark compare`
refuses a run whose two records disagree. One writer can only agree with itself, which is
why the shape lives here beside the runner and the values come from the command line.

Feature 014 (`specs/014-design-review-eval/contracts/provenance.md` 1; data-model section 7)
adds schema 2, written before any review rather than after the set: what the run was started
with (the pane-defaults marker, the model view, the profile's digest, whether it is the
checkout's example, the live tools, the inert settings, the prompt's digest, whether the
tracked tree was dirty, the answer-turn bound), and never a path. A field a record older than
that lacks reads as "not recorded".

## Refusals before any review (feature 014 INT-14)

`preflight_set` reads the set and checks it, that its packages and keys exist, and every case
file it names, before the first review (`contracts/benchmark-run.md` 3 row 4; `cases.md` 4.4;
`scripted-answers.md` 2.3), and `run_benchmark` takes only the `PreflightedSet` it returns, so a
library caller meets the same refusals as the command line, which writes the provenance record
between the two.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from pydantic import ConfigDict, Field

from swreview import atomic
from swreview.agent import checklist as agent_checklist
from swreview.agent import events
from swreview.agent.providers.retry import BENCHMARK_RETRY, RetryPolicy
from swreview.agent.settings import MODEL_VIEW_OFF, EfficiencySettings, ModelViewSettings
from swreview.benchmark import answers, prices, scrub
from swreview.benchmark import attempt as attempt_driver
from swreview.benchmark.attempt import AttemptClass, AttemptKind, AttemptListener
from swreview.benchmark.case_file import CaseFile
from swreview.benchmark.digest import sha256_of as sha256_of
from swreview.benchmark.sets import (
    REPO_ROOT,
    BenchmarkSet,
    SetError,
    checkout_relative,
    load_saved_set,
    load_set,
    path_form,
)
from swreview.checks.standards.profile import display_digest, load_profile
from swreview.findings import ReviewModel
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, reject_answer_key_path
from swreview.report.session import load_session, save_session

if TYPE_CHECKING:
    from swreview.agent.checklist import Checklist
    from swreview.agent.providers import AgentProvider
    from swreview.checks.standards.profile import StandardsProfile

ReviewFn = Callable[..., Any]


class PackageDoneCallback(Protocol):
    """The facts printed after one attempt, including a kept folder's failed rename."""

    def __call__(
        self, *, package_id: str, kind: AttemptKind, class_: AttemptClass | None,
        stop_reason: str | None, error_class: str | None, retries: int,
        promotion_error: str | None,
    ) -> None: ...


PROVENANCE_FILE = "run-provenance.json"
"""Where the provenance record sits: beside the `benchmark-set.json` the run already
saves, at the root of the run directory rather than inside a package folder, because it
describes the whole invocation."""

SAVED_SET_FILE = "benchmark-set.json"
"""`benchmark run` writes the set it ran into the run directory, so `benchmark score`
can score it without being told twice which set this run was. The one definition of the
name, which `cli`, `compare` and `handoff` import (feature 014 research 9.14)."""

PROVENANCE_SCHEMA = 2
"""The schema `benchmark run` writes (feature 014 `contracts/provenance.md` 1). A record
without the field predates it and reads as 1."""

EXAMPLE_PROFILE = Path("config") / "standards.example.yaml"
"""The fictional example profile every checkout ships, relative to the checkout's root: the
profile every committed case is keyed against (feature 014 FR-027)."""


class RunProvenance(ReviewModel):
    """What produced one run directory, written by `cli.py` from what was typed.

    `lever`, `arm` and `rep` are **typed, never derived**: which lever a run is testing,
    which arm it is and which repetition it is are facts across two run folders, not
    inside one. A lever-6 off run, a lever-3 on run and a baseline run are byte-identical
    in `efficiency`, so nothing in the settings distinguishes them and nothing infers
    them from the folder name (contracts/ab-harness.md section 2).

    `efficiency` is the **complete** settings dump and not a diff, so a reader never has
    to reconstruct what the other nine flags were.
    """

    commit: str | None
    """The tree's commit sha at run time, or `None` outside a checkout. Load-bearing
    rather than decoration: `compare` refuses to place two runs of differing commits in
    one comparison, with no exception."""

    lever: str
    """The lever under test, from `--study`; `"none"` for a baseline or a smoke run."""

    arm: Literal["off", "on", "baseline"] | None
    """From `--arm`; `None` for a run that claims no arm at all."""

    rep: Annotated[int, Field(ge=1)] | None
    """From `--rep`. Which repetition of this arm; **not** read off the folder name."""

    provider: str
    model: str
    effort: str
    max_steps: int = Field(ge=1)
    checklist_digest: str
    set_digest: str
    started_at: datetime = Field(strict=False)
    set_too_small_override: bool = False
    """Whether `--i-know-the-set-is-too-small` was passed. Carried into every ledger row
    this run produces, so the row can never be read as a gate (FR-029)."""

    efficiency: EfficiencySettings
    explanations_enabled: bool = False
    """Presentation setting independent of efficiency flags; old runs did not enable it."""

    provenance_schema: int = 1
    """`PROVENANCE_SCHEMA` (2) when `benchmark run` wrote the record; absent, it predates
    feature 014's fields and reads 1."""

    pane_defaults: bool = False
    """Whether `--pane-defaults` was typed: the marker a pane study's arms are read by
    (PP-3). Absent reads false, since the option did not exist."""

    model_view: ModelViewSettings | None = None
    """The model view the run resolved; `None`, "not recorded", in an older record."""

    profile_digest: str | None = None
    """The sha256 of the standards profile every review graded against, the digest each
    standards finding stamps; `None` with no profile. Never the profile's path."""

    profile_is_example: bool | None = None
    """Whether the profile's bytes equal the checkout's `config/standards.example.yaml` at
    run time, recorded because the example may change after the study ran; `None` with no
    profile."""

    live_tools: bool | None = None
    """Whether the live SOLIDWORKS tools were offered: false from `benchmark run`, always.
    Recorded and shown, never must-match (PP-9)."""

    inert_settings: tuple[str, ...] | None = None
    """`agent.settings.INERT_SETTINGS[provider]`: the recorded settings that do not act on
    this provider (FR-052)."""

    prompt_digest: str | None = None
    """The sha256 of the system prompt's raw bytes, beside the checklist's."""

    tree_dirty: bool | None = None
    """Whether the checkout's tracked files differed from `commit`; `None` when git cannot
    answer."""

    max_answer_turns: int | None = None
    """How many answer turns each review could take after its opening turn
    (`contracts/scripted-answers.md` 4); `None`, "not recorded", in a record older than the
    field, never the default 3."""

    package_time_limit_s: int | None = None
    """The per-package wall clock W; absent means "not recorded", never the default."""

    stream_activity_window_s: int | None = None
    """The stream activity window A at the wall-clock limit; absent means "not recorded"."""

    stop_grace_s: int | None = None
    """The stop grace G before an unresponsive worker is abandoned; absent means "not recorded"."""

    retry_policy: RetryPolicy | None = None
    """The request retry policy applied to every attempt; absent means "not recorded"."""


@dataclass(frozen=True)
class AttemptFacts:
    """What one attempt's stream recorded, including usage before a failure."""

    rounds: tuple[prices.RoundFacts, ...]
    served_models: list[str]
    retries: int
    stop_reasons: list[str]
    paid: bool


def attempt_facts(folder: Path) -> AttemptFacts:
    """Replay an attempt once, keeping the facts before any unreadable tail."""
    ledger = events.UsageLedger()
    usage_bodies: list[Mapping[str, Any]] = []
    served_models: list[str] = []
    retries = 0
    stop_reasons: list[str] = []
    for event in events.replay_events(events.event_stream(folder)):
        ledger(event)
        body = event.body
        if event.type == "usage":
            usage_bodies.append(body)
            served_model = body.get("served_model")
            if served_model is not None and served_model not in served_models:
                served_models.append(served_model)
        if event.type in ("usage", "error"):
            reported_retries = body.get("retries")
            if reported_retries is not None:
                retries += reported_retries
        if event.type == "error":
            stop_reason = body.get("stop_reason")
            if stop_reason is not None:
                stop_reasons.append(stop_reason)

    rounds = tuple(
        prices.RoundFacts(
            usage=usage,
            provider=body["provider"],
            model=body["model"],
            served_model=body.get("served_model"),
            retries=body.get("retries"),
        )
        for usage, body in zip(ledger.rounds(), usage_bodies, strict=True)
    )
    return AttemptFacts(
        rounds=rounds, served_models=served_models, retries=retries,
        stop_reasons=stop_reasons, paid=bool(rounds),
    )


def _git_process(cwd: Path | str, *args: str) -> subprocess.CompletedProcess[str] | None:
    """`git <args>` run in `cwd`, or `None` when git could not be run at all: no git on the
    path, a folder that is gone, a timeout."""
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            cwd=str(cwd),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git(cwd: Path | str, *args: str) -> str | None:
    """`git <args>`'s standard output in `cwd`, or `None` whenever git cannot answer.

    No repository, no git on the path, a timeout: `None` rather than a placeholder, because
    a fact about the tree we do not know renders as unknown, and a guess is worse than an
    absent value (Principle I).
    """
    proc = _git_process(cwd, *args)
    return proc.stdout if proc is not None and proc.returncode == 0 else None


def current_commit(cwd: Path | str | None = None) -> str | None:
    """The short sha of `HEAD` in `cwd` (default: this checkout), or `None`.

    `None` rather than a placeholder whenever git cannot answer - no repository, no git
    on the path, a timeout: a commit we do not know renders as unknown in the ledger, and
    a guessed sha is worse than an absent one (Principle I).
    """
    output = _git(cwd if cwd is not None else REPO_ROOT, "rev-parse", "--short", "HEAD")
    return (output.strip() or None) if output is not None else None


def tree_dirty(*, root: Path) -> bool | None:
    """Whether the checkout at `root` holds a tracked change, or `None` when git cannot say.

    `git status --porcelain --untracked-files=no`: a modified or staged tracked file is a
    change to the code a run measured, an untracked file is not (feature 014
    `contracts/provenance.md` 1). `None` by `current_commit`'s rule.
    """
    output = _git(root, "status", "--porcelain", "--untracked-files=no")
    return bool(output.strip()) if output is not None else None


def committable(path: Path | str, *, root: Path) -> bool:
    """Whether the repository at `root` could commit `path`: it lies inside `root` and git
    does not report it ignored (feature 014 `contracts/provenance.md` 6.4).

    `git check-ignore -q -- <path>` exits 0 for an ignored path and 1 for one git would track,
    the `--` keeping a folder named like an option (`-x`, `--stdin`) a path; any other
    exit, or no git at all, is git that cannot answer, and inside `root` that counts as
    committable: the side that refuses. A folder not made yet that only a directory pattern
    (`runs/`) ignores reads as committable for the same reason, since git cannot tell that a
    name it has never seen is a folder; one inside an ignored folder reads ignored. The one
    reading `benchmark run`'s row 5 and compare's ledger guard share; inside `root` is
    `sets.checkout_relative`'s reading.
    """
    relative = checkout_relative(path, root=root)
    if relative is None:
        return False
    proc = _git_process(Path(root).resolve(), "check-ignore", "-q", "--", relative.as_posix())
    ignored = proc is not None and proc.returncode == 0
    return not ignored


def profile_is_example(profile_path: Path | str | None, *, root: Path) -> bool | None:
    """Whether the profile's bytes equal `root`'s `config/standards.example.yaml`.

    Byte for byte: the profile's file name and folder play no part. `None` with no profile;
    false when `root` ships no example, since then no profile can be it.
    """
    if profile_path is None:
        return None
    example = root / EXAMPLE_PROFILE
    return example.is_file() and Path(profile_path).read_bytes() == example.read_bytes()


def write_provenance(run_dir: Path | str, provenance: RunProvenance) -> Path:
    """Write the record into `run_dir`, returning where it landed.

    UTF-8 bytes with `\\n` line endings through the one atomic writer, so the record is the
    same bytes on every platform and a reader never sees half of it.
    """
    target = Path(run_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / PROVENANCE_FILE
    atomic.write_atomic(path, (provenance.model_dump_json(indent=2) + "\n").encode("utf-8"))
    return path


def load_provenance(run_dir: Path | str) -> RunProvenance | None:
    """The record in `run_dir`, or `None` when there is none.

    `None` rather than an error: a run made before this convention existed is still a
    real run, and `compare` renders it as a row with its four provenance columns null
    (contracts/ab-harness.md section 3). A record that *is* there but carries a field
    this build does not know fails loudly, for the reason `EfficiencySettings` does.
    """
    path = Path(run_dir) / PROVENANCE_FILE
    if not path.is_file():
        return None
    return RunProvenance.model_validate_json(path.read_bytes())


@dataclass(frozen=True)
class AttemptRequest:
    """What one attempt needs that the review function's other keywords do not carry.

    `run_benchmark` hands it to the review function as its one keyword `attempt`, beside
    `provider`, `model`, `effort`, `efficiency` and `explain_findings` (feature 014 plan
    decision RF-44; `contracts/benchmark-run.md` 5.1). One value rather than one keyword per
    input, so an injected review function needs one keyword more whatever the values, and
    the keywords it receives never vary with them. The robustness slice adds the attempt's
    stop (lane B6).
    """

    model_view: ModelViewSettings
    """What the model reads of each tool result, as the run resolved it."""

    standards_profile: Path | None
    """The standards profile every review grades against; `None` grades none."""

    case_file: CaseFile | None
    """This package's scripted answers as `preflight_set` loaded them, or `None` for a set
    entry naming no case file, whose questions are all unscripted."""

    max_answer_turns: int
    """How many answer turns the review may take after its opening turn, the same for every
    package (`contracts/scripted-answers.md` 4)."""

    stop: threading.Event
    listener: AttemptListener
    run_dir: Path
    root: Path = REPO_ROOT
    retry_policy: RetryPolicy = BENCHMARK_RETRY
    max_steps: int | None = None
    adapter: AgentProvider | None = None


RUN_STATUS_FILE = "run-status.json"


class AttemptStatus(ReviewModel):
    """The driver's facts about one attempt; stream facts stay in its event stream."""

    model_config = ConfigDict(populate_by_name=True)

    attempt: int = Field(ge=1)
    started_at: datetime
    ended_at: datetime | None = None
    resumed: bool = False
    kind: AttemptKind | None = None
    class_: AttemptClass | None = Field(default=None, alias="class")
    stop_reason: str | None = None
    error_class: str | None = None
    message: str | None = None
    stream_active_at_limit: bool | None = None
    folder: str


class PackageStatus(ReviewModel):
    kept_attempt: int | None = Field(default=None, ge=1)
    attempts: list[AttemptStatus] = Field(default_factory=list)


class RunStatus(ReviewModel):
    run_status_version: Literal[1] = 1
    packages: dict[str, PackageStatus] = Field(default_factory=dict)


def load_run_status(run_dir: Path | str) -> RunStatus | None:
    """Read the driver's record, or return None for a folder predating attempts."""
    path = Path(run_dir) / RUN_STATUS_FILE
    return RunStatus.model_validate_json(path.read_bytes()) if path.is_file() else None


def _write_run_status(run_dir: Path, status: RunStatus) -> None:
    atomic.write_atomic(
        run_dir / RUN_STATUS_FILE,
        (status.model_dump_json(indent=2, by_alias=True) + "\n").encode("utf-8"),
    )


@dataclass(frozen=True)
class PreflightedSet:
    """A benchmark set every refusal before the first review has passed: what `preflight_set`
    returns and the one thing `run_benchmark` reviews (feature 014 INT-14; data-model section 4).

    `benchmark_set` is the set as `load_set` read it against `root`, the checkout its relative
    entries resolved against, every package's `package.json` and every key it names there (the
    key stat-ed, never opened), and `case_files` holds, by package id, the `CaseFile` loaded and
    checked for an entry naming one and `None` for an entry naming none.
    """

    benchmark_set: BenchmarkSet
    root: Path
    case_files: Mapping[str, CaseFile | None]


ATTEMPTS_FOLDER = "attempts"
"""The run folder's `attempts/`, where every attempt of every package runs
(`contracts/benchmark-run.md` 4): a package whose id names it would have no folder of its own."""


def preflight_set(
    set_path: Path | str | BenchmarkSet,
    profile: StandardsProfile | None,
    checklist: Checklist,
    *,
    root: Path = REPO_ROOT,
) -> PreflightedSet:
    """Read the set at `set_path` and refuse it, or a case file it names, before any review
    (`contracts/benchmark-run.md` 3 row 4; `scripted-answers.md` 2.3; INT-14).

    In order, the first refusal ending the run with one line: `load_set`'s refusals against
    `root`; a package id equal to `attempts` ignoring case, a `SetError` naming it, since Windows
    and macOS fold case and its folder would be the run's `attempts/` (owner decision 48A); the
    existence checks (`contracts/cases.md` 4.4; plan decision CS-16), a package folder holding
    no `package.json` and then a key that is not a file, each a `SetError` naming every missing
    one; then each entry naming a case file, in set order. A case file the set loader could take
    no digest of is refused by row 1 before its package is read; any other is checked by
    `answers.load_case_file` against the package, `checklist` and `profile`, the profile the
    reviews will grade against or `None`, which the command line has loaded, or refused, first.
    """
    benchmark_set = (
        set_path if isinstance(set_path, BenchmarkSet) else load_set(set_path, root=root)
    )
    set_name = SAVED_SET_FILE if isinstance(set_path, BenchmarkSet) else Path(set_path).name
    for ref in benchmark_set.packages:
        if ref.package_id.casefold() == ATTEMPTS_FOLDER:
            raise SetError(
                f"benchmark set {set_name}: package id {ref.package_id} would share "
                f"the run folder's {ATTEMPTS_FOLDER}/ folder, where every attempt runs; ids are "
                "compared ignoring case, as Windows and macOS compare folder names: choose "
                "another id"
            )
    _refuse_missing(
        benchmark_set,
        "package",
        [
            (ref.package_id, ref.path)
            for ref in benchmark_set.packages
            if not (ref.path / PACKAGE_FILE_NAME).is_file()
        ],
        root=root,
    )
    _refuse_missing(
        benchmark_set,
        "key",
        [
            (ref.package_id, ref.key)
            for ref in benchmark_set.packages
            if ref.key is not None and not ref.key.is_file()
        ],
        root=root,
    )
    case_files: dict[str, CaseFile | None] = {}
    for ref in benchmark_set.packages:
        if ref.case_file is None:
            case_files[ref.package_id] = None
            continue
        if ref.case_file_sha256 is None:
            raise answers.unreadable_case_file(ref.case_file, entry=ref)
        case_files[ref.package_id] = answers.load_case_file(
            ref.case_file,
            entry=ref,
            package=load_package(ref.path).package,
            checklist=checklist,
            profile=profile,
        )
    return PreflightedSet(
        benchmark_set=benchmark_set, root=root, case_files=MappingProxyType(case_files)
    )


def _refuse_missing(
    benchmark_set: BenchmarkSet, kind: str, missing: list[tuple[str, Path]], *, root: Path
) -> None:
    """One existence check's refusal (`contracts/cases.md` 4.4): every `(package id, path)` in
    `missing`, in set order, in one line, "benchmark set {name}: {n} {kind}(s) missing: {id} at
    {path}; ...", each path as the set's entry names it (`sets.path_form`), so a committed
    entry's names no local folder. Nothing when nothing is missing."""
    if not missing:
        return
    named = "; ".join(f"{package_id} at {path_form(path, root)}" for package_id, path in missing)
    raise SetError(f"benchmark set {benchmark_set.name}: {len(missing)} {kind}(s) missing: {named}")


def _default_review_fn(
    package_dir: Path,
    session_out_dir: Path,
    *,
    provider: str,
    model: str,
    effort: str,
    attempt: AttemptRequest,
    efficiency: EfficiencySettings | None = None,
    explain_findings: bool = False,
) -> Any:
    """One package, reviewed on a freshly built adapter.

    Imported lazily, and from `swreview.cli` deliberately: that module owns the
    `provider_factory` hook every other review goes through and the key redaction that
    goes with it, and a second copy of the "settings in, adapter out" wiring is the thing
    most likely to drift from it - so this defers to `cli._review_fn` rather than
    restating it. Every CLI run injects its own `review_fn`, so this path is for a caller
    that wanted the default.
    """
    from swreview.cli import _review_fn

    return _review_fn(
        package_dir,
        session_out_dir,
        provider=provider,
        model=model,
        effort=effort,
        efficiency=efficiency,
        explain_findings=explain_findings,
        attempt=attempt,
    )


def _reject_answer_key_path(path: Path) -> None:
    reject_answer_key_path(
        path, "the benchmark runner never passes an answer-key path to the reviewer"
    )


def _record_unattended_runtime(session_out_dir: Path, elapsed_minutes: float) -> None:
    """Set `Timing.unattended_runtime_minutes` on the package's `session.json`, if any.

    A `review_fn` that has not written a session yet (as in unit tests with a fake
    `review_fn`) leaves nothing to update; that is not this function's problem to solve.
    """
    session_path = session_out_dir / "session.json"
    if not session_path.is_file():
        return
    session = load_session(session_path)
    session.timing = session.timing.replace(unattended_runtime_minutes=elapsed_minutes)
    save_session(session, session_path)


def run_benchmark(
    preflighted: PreflightedSet,
    out_dir: Path | str,
    provider: str,
    model: str,
    effort: str,
    review_fn: ReviewFn | None = None,
    efficiency: EfficiencySettings | None = None,
    explain_findings: bool = False,
    *,
    model_view: ModelViewSettings = MODEL_VIEW_OFF,
    standards_profile: Path | None = None,
    max_answer_turns: int = answers.DEFAULT_MAX_ANSWER_TURNS,
    package_time_limit_s: float = 3600,
    stream_activity_window_s: float = attempt_driver.STREAM_ACTIVITY_WINDOW_S,
    stop_grace_s: float = attempt_driver.STOP_GRACE_S,
    redact: Callable[[str], str] = events.no_redaction,
    on_package_done: PackageDoneCallback | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[Path]:
    """Review every package of the preflighted set into `out_dir`.

    Calls `review_fn(package_dir, out_dir/attempts/package_id/1, provider=provider, model=model,
    effort=effort, efficiency=efficiency, attempt=AttemptRequest(...))` per package
    (default: `_default_review_fn`), then records unattended runtime for that package.
    Returns the list of per-package output directories, in benchmark-set order.

    `preflighted` is what `preflight_set` returned, never a set path, so no review starts on a
    set or a case file it would refuse (feature 014 INT-14, RF-61).

    `attempt` carries what the call's other keywords do not: `model_view`,
    `standards_profile` and `max_answer_turns`, the same for every package, and the package's
    `case_file` as `preflight_set` loaded it (feature 014 RF-44).

    `explain_findings=True` adds the pane's presentation request, including its usage and
    runtime. The keyword is forwarded to injected review functions only when enabled,
    preserving the existing default-off callback contract.

    `efficiency` is one object carrying all ten lever flags rather than one argument per
    lever, forwarded unchanged to every package of the set: an arm of an A/B study is one
    settings object applied to the whole set, and the reviewer records it on each
    package's session so the run folder can be attributed to a configuration afterwards.

    `provider` and `model` are passed through unresolved - the review function decides
    what a name means (FR-016), so scoring a set on OpenAI and on Gemini differs by one
    argument and nothing else.
    """
    if not isinstance(preflighted, PreflightedSet):
        raise TypeError(
            "run_benchmark reviews the PreflightedSet that preflight_set returns, not a "
            f"{type(preflighted).__name__}: a set's refusals come before any review"
        )
    return _run_packages(
        preflighted, Path(out_dir), provider, model, effort, review_fn, efficiency,
        explain_findings, model_view=model_view, standards_profile=standards_profile,
        max_answer_turns=max_answer_turns, package_time_limit_s=package_time_limit_s,
        stream_activity_window_s=stream_activity_window_s, stop_grace_s=stop_grace_s,
        redact=redact, on_package_done=on_package_done, clock=clock, status=RunStatus(),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _run_packages(
    preflighted: PreflightedSet,
    out_dir: Path,
    provider: str,
    model: str,
    effort: str,
    review_fn: ReviewFn | None,
    efficiency: EfficiencySettings | None,
    explain_findings: bool,
    *,
    model_view: ModelViewSettings,
    standards_profile: Path | None,
    max_answer_turns: int,
    package_time_limit_s: float,
    stream_activity_window_s: float,
    stop_grace_s: float,
    redact: Callable[[str], str],
    on_package_done: PackageDoneCallback | None,
    clock: Callable[[], float],
    status: RunStatus,
    resumed: bool = False,
    run_served_models: tuple[str, ...] = (),
    now: Callable[[], datetime] = _utc_now,
    retry_policy: RetryPolicy = BENCHMARK_RETRY,
    max_steps: int | None = None,
    initial_adapter: AgentProvider | None = None,
) -> list[Path]:
    """The same sequential attempt driver for a new run and a resumed run."""
    active_review_fn = review_fn if review_fn is not None else _default_review_fn

    def sanitize_message(text: str) -> str:
        return scrub.one_line(scrub.without_local_paths(
            redact(text), run_dir=out_dir, root=preflighted.root,
        ))

    provenance = load_provenance(out_dir)
    profile_digest = (
        provenance.profile_digest if provenance is not None else None
    )
    if standards_profile is not None and profile_digest is None:
        profile_digest = sha256_of(standards_profile)
    package_dirs: list[Path] = []
    for ref in preflighted.benchmark_set.packages:
        package_status = status.packages.get(ref.package_id)
        if package_status is not None and package_status.kept_attempt is not None:
            kept = next(
                row for row in package_status.attempts
                if row.attempt == package_status.kept_attempt
            )
            folder = _kept_folder(out_dir, ref.package_id, kept)
            if folder == out_dir / ref.package_id:
                package_dirs.append(folder)
                continue
            promoted, promotion_error = _promote_attempt(
                out_dir, ref.package_id, folder, kept, status, sanitize_message,
            )
            if promoted is not None:
                package_dirs.append(promoted)
            elif on_package_done is not None:
                on_package_done(
                    package_id=ref.package_id, kind=kept.kind, class_=kept.class_,
                    stop_reason=kept.stop_reason, error_class=kept.error_class,
                    retries=attempt_facts(folder).retries, promotion_error=promotion_error,
                )
            continue
        if standards_profile is not None:
            current_digest = sha256_of(standards_profile)
            if current_digest != profile_digest:
                raise ValueError(
                    "standards profile changed: recorded "
                    f"{display_digest(profile_digest)}, current {display_digest(current_digest)}"
                )
        _reject_answer_key_path(ref.path)
        if package_status is None:
            package_status = PackageStatus()
            status.packages[ref.package_id] = package_status
        for prior in package_status.attempts:
            if prior.kind is None:
                prior.kind = "infrastructure"
                prior.class_ = "interrupted"
                prior.ended_at = now()
                _write_run_status(out_dir, status)
        number = max((row.attempt for row in package_status.attempts), default=0) + 1
        package_out_dir = out_dir / ATTEMPTS_FOLDER / ref.package_id / str(number)
        _reject_answer_key_path(package_out_dir)
        package_out_dir.mkdir(parents=True, exist_ok=True)

        stop = threading.Event()
        listener = AttemptListener(
            stop, provider=provider, requested_model=model, clock=clock,
            run_served_models=run_served_models,
        )
        request = AttemptRequest(
            model_view=model_view,
            standards_profile=standards_profile,
            case_file=preflighted.case_files[ref.package_id],
            max_answer_turns=max_answer_turns,
            stop=stop,
            listener=listener,
            run_dir=out_dir,
            root=preflighted.root,
            retry_policy=retry_policy,
            max_steps=max_steps,
            adapter=initial_adapter,
        )
        initial_adapter = None
        row = AttemptStatus(
            attempt=number, started_at=now(), resumed=resumed,
            folder=package_out_dir.relative_to(out_dir).as_posix(),
        )
        package_status.attempts.append(row)
        _write_run_status(out_dir, status)

        def body(
            package_dir: Path = ref.path,
            folder: Path = package_out_dir,
            request: AttemptRequest = request,
        ) -> Any:
            # Bind per-attempt inputs: an abandoned daemon may outlive this loop iteration.
            return active_review_fn(
                package_dir, folder, provider=provider, model=model, effort=effort,
                efficiency=efficiency,
                **({"explain_findings": True} if explain_findings else {}),
                attempt=request,
            )

        started = clock()
        try:
            outcome = attempt_driver.run_attempt(
                body, stop=stop, listener=listener, limit_s=package_time_limit_s,
                activity_window_s=stream_activity_window_s, grace_s=stop_grace_s,
                clock=clock,
            )
        except KeyboardInterrupt:
            stop.set()
            row.kind = "infrastructure"
            row.class_ = "interrupted"
            row.ended_at = now()
            _write_run_status(out_dir, status)
            raise

        row.ended_at = now()
        row.kind = outcome.kind
        row.class_ = outcome.class_
        row.stop_reason = outcome.stop_reason
        row.error_class = outcome.error_class
        row.message = sanitize_message(outcome.message) if outcome.message is not None else None
        row.stream_active_at_limit = outcome.stream_active_at_limit
        facts_folder = package_out_dir
        promotion_error: str | None = None
        if outcome.kind in ("completed", "behavioural"):
            _record_unattended_runtime(package_out_dir, (clock() - started) / 60.0)
            package_status.kept_attempt = row.attempt
            promoted, promotion_error = _promote_attempt(
                out_dir, ref.package_id, package_out_dir, row, status, sanitize_message,
            )
            if promoted is not None:
                facts_folder = promoted
                package_dirs.append(promoted)
        else:
            _write_run_status(out_dir, status)
        if on_package_done is not None:
            on_package_done(
                package_id=ref.package_id, kind=row.kind, class_=row.class_,
                stop_reason=row.stop_reason, error_class=row.error_class,
                retries=attempt_facts(facts_folder).retries,
                promotion_error=promotion_error,
            )
        if row.class_ == "served_model_changed":
            break

    return package_dirs


def _kept_folder(run_dir: Path, package_id: str, row: AttemptStatus) -> Path:
    """Find either side of the rename, including a crash after recording its destination."""
    promoted = run_dir / package_id
    return (
        promoted if promoted.is_dir()
        else run_dir / ATTEMPTS_FOLDER / package_id / str(row.attempt)
    )


def _promote_attempt(
    run_dir: Path, package_id: str, folder: Path, row: AttemptStatus, status: RunStatus,
    sanitize: Callable[[str], str],
) -> tuple[Path | None, str | None]:
    """Record the kept destination before the one rename; leave any refusal recoverable."""
    row.folder = package_id
    _write_run_status(run_dir, status)
    promoted = run_dir / package_id
    try:
        folder.rename(promoted)
    except OSError as error:
        row.folder = folder.relative_to(run_dir).as_posix()
        promotion_error = sanitize(str(error))
        row.message = "; ".join(
            message for message in (row.message, f"promotion failed: {promotion_error}")
            if message is not None
        )
        _write_run_status(run_dir, status)
        return None, promotion_error
    return promoted, None


def _digest_or_none(path: Path) -> str | None:
    try:
        return sha256_of(path)
    except OSError:
        return None


def _resume_inputs(
    run_dir: Path, *, root: Path, standards_profile: Path | None,
    now: Callable[[], datetime],
) -> tuple[RunProvenance, PreflightedSet, RunStatus]:
    """Section 11's refusals, in order, without changing a byte of the recorded run."""
    provenance = load_provenance(run_dir)
    if provenance is None or provenance.provenance_schema < PROVENANCE_SCHEMA:
        raise ValueError("made before runs recorded their status; start a new run")
    status = load_run_status(run_dir)
    if status is None and any(run_dir.rglob("session.json")):
        raise ValueError("made before runs recorded their status; start a new run")
    if status is None:
        status = RunStatus()
    limit = provenance.package_time_limit_s
    grace = provenance.stop_grace_s
    safe_after_s = (3600 if limit is None else limit) + (
        attempt_driver.STOP_GRACE_S if grace is None else grace
    )
    current_time = now()
    for package_id, package in status.packages.items():
        for row in package.attempts:
            wait_until = row.started_at + timedelta(seconds=safe_after_s)
            if row.kind is None and current_time < wait_until:
                raise ValueError(
                    f"attempt {row.attempt} of {package_id} may still be running; "
                    f"wait until {wait_until.isoformat()}"
                )

    commit = current_commit(root)
    if provenance.commit is None or commit is None or provenance.commit != commit:
        raise ValueError(
            f"commit differs: recorded {provenance.commit or 'unknown'}, "
            f"current {commit or 'unknown'}"
        )
    for field, path in (
        ("checklist_digest", agent_checklist.CHECKLIST_FILE),
        ("prompt_digest", agent_checklist.SYSTEM_PROMPT_FILE),
    ):
        recorded, current = getattr(provenance, field), _digest_or_none(path)
        if recorded != current:
            raise ValueError(f"{field} differs: recorded {recorded}, current {current}")

    saved_set = run_dir / SAVED_SET_FILE
    set_digest = _digest_or_none(saved_set)
    if provenance.set_digest != set_digest:
        raise ValueError(
            f"{SAVED_SET_FILE} set_digest differs: recorded {provenance.set_digest}, "
            f"current {set_digest}"
        )
    benchmark_set = load_saved_set(saved_set, root=root)
    for ref in benchmark_set.packages:
        if ref.case_file is not None:
            current = _digest_or_none(ref.case_file)
            if ref.case_file_sha256 != current or current is None:
                raise ValueError(
                    f"case file {path_form(ref.case_file, root)} sha256 differs: "
                    f"recorded {ref.case_file_sha256}, current {current}"
                )

    recorded_profile = provenance.profile_digest
    if recorded_profile is None and standards_profile is not None:
        raise ValueError("standards profile differs: none recorded, but one was named")
    if recorded_profile is not None:
        shown = display_digest(recorded_profile)
        if standards_profile is None:
            raise ValueError(f"standards profile {shown} was recorded, but none was named")
        current_profile = _digest_or_none(standards_profile)
        if current_profile != recorded_profile:
            current_shown = (
                display_digest(current_profile) if current_profile is not None else "unknown"
            )
            raise ValueError(
                f"standards profile differs: recorded {shown}, current {current_shown}"
            )
    profile = load_profile(standards_profile) if standards_profile is not None else None
    preflighted = preflight_set(
        benchmark_set, profile, agent_checklist.load_checklist(), root=root,
    )

    # Reuse the parity slice's rules, including its exact clean-tree and CR sentences.
    from swreview.cli import _refuse_a_pane_study_breaking_its_file_rules

    _refuse_a_pane_study_breaking_its_file_rules(
        provenance.lever, standards_profile=standards_profile,
        is_example=profile_is_example(standards_profile, root=root),
        benchmark_set=benchmark_set, commit=commit, dirty=tree_dirty(root=root),
        digested=(
            agent_checklist.SYSTEM_PROMPT_FILE, agent_checklist.CHECKLIST_FILE,
            standards_profile, saved_set, *(ref.case_file for ref in benchmark_set.packages),
        ),
        root=root,
    )
    return provenance, preflighted, status


def resume_benchmark(
    run_dir: Path | str,
    *,
    review_fn: ReviewFn | None = None,
    root: Path = REPO_ROOT,
    standards_profile: Path | None = None,
    now: Callable[[], datetime] = _utc_now,
    clock: Callable[[], float] = time.monotonic,
    redact: Callable[[str], str] = events.no_redaction,
    on_package_done: PackageDoneCallback | None = None,
    on_preflight: Callable[[RunProvenance], None] | None = None,
) -> list[Path]:
    """Continue only missing/infrastructure attempts, from the run's recorded settings.

    `on_preflight` resolves the CLI's provider after every other refusal, before any
    attempt folder or status is written. Its adapter belongs to the first new attempt.
    Kept attempts are immutable, apart from completing an interrupted promotion.
    """
    run_dir = Path(run_dir)
    provenance, preflighted, status = _resume_inputs(
        run_dir, root=root, standards_profile=standards_profile, now=now,
    )
    run_served_models: list[str] = []
    for package_id, package in status.packages.items():
        if package.kept_attempt is None:
            continue
        kept = next(row for row in package.attempts if row.attempt == package.kept_attempt)
        for served in attempt_facts(_kept_folder(run_dir, package_id, kept)).served_models:
            if served not in run_served_models:
                run_served_models.append(served)
    with ExitStack() as stack:
        initial_adapter = None
        if on_preflight is not None:
            on_preflight(provenance)
        else:
            # Library callers get the same provider refusal and first-attempt adapter.
            from swreview import cli

            settings = cli.ProviderSettings.from_env(
                provider=provenance.provider, model=provenance.model, effort=provenance.effort,
            )
            key_redactor = stack.enter_context(cli._redacting(settings))
            initial_adapter = cli.provider_factory(settings, provenance.efficiency)
            initial_adapter.effort_mapping(settings.effort)
            caller_redactor = redact

            def redact(text: str) -> str:
                return caller_redactor(key_redactor(text))
        return _run_packages(
            preflighted, run_dir, provenance.provider, provenance.model, provenance.effort,
            review_fn, provenance.efficiency, provenance.explanations_enabled,
            model_view=provenance.model_view or MODEL_VIEW_OFF,
            standards_profile=standards_profile,
            max_answer_turns=(
                answers.DEFAULT_MAX_ANSWER_TURNS if provenance.max_answer_turns is None
                else provenance.max_answer_turns
            ),
            package_time_limit_s=(
                3600 if provenance.package_time_limit_s is None else provenance.package_time_limit_s
            ),
            stream_activity_window_s=(
                attempt_driver.STREAM_ACTIVITY_WINDOW_S
                if provenance.stream_activity_window_s is None
                else provenance.stream_activity_window_s
            ),
            stop_grace_s=(
                attempt_driver.STOP_GRACE_S if provenance.stop_grace_s is None
                else provenance.stop_grace_s
            ),
            retry_policy=provenance.retry_policy or BENCHMARK_RETRY,
            max_steps=provenance.max_steps,
            redact=redact, on_package_done=on_package_done, clock=clock, status=status,
            resumed=True, run_served_models=tuple(run_served_models), now=now,
            initial_adapter=initial_adapter,
        )
