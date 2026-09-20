"""Run the reviewer over every package in a benchmark set (T096, runner half).

This module iterates `swreview.benchmark.sets.BenchmarkSet.packages` and calls a
review function per package, writing its output under `<out_dir>/<package_id>/`. It
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
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from swreview.agent.settings import EfficiencySettings
from swreview.benchmark.sets import BenchmarkSet, load_set
from swreview.findings import ReviewModel
from swreview.ir.loader import reject_answer_key_path
from swreview.report.session import load_session, save_session

ReviewFn = Callable[..., Any]

PROVENANCE_FILE = "run-provenance.json"
"""Where the provenance record sits: beside the `benchmark-set.json` the run already
saves, at the root of the run directory rather than inside a package folder, because it
describes the whole invocation."""

REPO_ROOT = Path(__file__).resolve().parents[4]
"""The tree `current_commit` asks git about, when this package is running from a
checkout. An installed copy has no repository above it and records no commit."""


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


def sha256_of(path: Path | str) -> str:
    """The sha256 of a file's bytes, for the set-file and checklist digests."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def current_commit(cwd: Path | str | None = None) -> str | None:
    """The short sha of `HEAD` in `cwd` (default: this checkout), or `None`.

    `None` rather than a placeholder whenever git cannot answer - no repository, no git
    on the path, a timeout: a commit we do not know renders as unknown in the ledger, and
    a guessed sha is worse than an absent one (Principle I).
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
            cwd=str(cwd) if cwd is not None else str(REPO_ROOT),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def write_provenance(run_dir: Path | str, provenance: RunProvenance) -> Path:
    """Write the record into `run_dir`, returning where it landed."""
    target = Path(run_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / PROVENANCE_FILE
    path.write_text(provenance.model_dump_json(indent=2) + "\n", encoding="utf-8")
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


def _default_review_fn(
    package_dir: Path,
    session_out_dir: Path,
    *,
    provider: str,
    model: str,
    effort: str,
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
    set_path: Path | str,
    out_dir: Path | str,
    provider: str,
    model: str,
    effort: str,
    review_fn: ReviewFn | None = None,
    efficiency: EfficiencySettings | None = None,
    explain_findings: bool = False,
) -> list[Path]:
    """Review every package of the benchmark set at `set_path` into `out_dir`.

    Calls `review_fn(package_dir, out_dir/package_id, provider=provider, model=model,
    effort=effort, efficiency=efficiency)` per package (default: `_default_review_fn`),
    then records unattended runtime for that package. Returns the list of per-package
    output directories, in benchmark-set order.

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
    benchmark_set: BenchmarkSet = load_set(set_path)
    active_review_fn = review_fn if review_fn is not None else _default_review_fn
    out_dir = Path(out_dir)

    package_dirs: list[Path] = []
    for ref in benchmark_set.packages:
        _reject_answer_key_path(ref.path)
        package_out_dir = out_dir / ref.package_id
        _reject_answer_key_path(package_out_dir)
        package_out_dir.mkdir(parents=True, exist_ok=True)

        started = time.perf_counter()
        active_review_fn(
            ref.path,
            package_out_dir,
            provider=provider,
            model=model,
            effort=effort,
            efficiency=efficiency,
            **({"explain_findings": True} if explain_findings else {}),
        )
        elapsed_minutes = (time.perf_counter() - started) / 60.0

        _record_unattended_runtime(package_out_dir, elapsed_minutes)
        package_dirs.append(package_out_dir)

    return package_dirs
