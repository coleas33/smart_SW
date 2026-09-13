"""Run the reviewer over every package in a benchmark set (T096, runner half).

This module iterates `swreview.benchmark.sets.BenchmarkSet.packages` and calls a
review function per package, writing its output under `<out_dir>/<package_id>/`. It
never opens an answer key, and it refuses - a second time, on top of
`swreview.benchmark.sets.load_set` - to pass a package path that resolves under
`benchmarks/answer_keys/` (constitution Principle VI, FR-025): defense in depth, not
trust in a single check.

This is a skeleton: the real per-package review call lives in
`swreview.agent.runner.run_review`, imported lazily (it may not exist yet while that
module is under development elsewhere) and only used as the default `review_fn`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from swreview.benchmark.sets import BenchmarkSet, load_set
from swreview.ir.loader import ANSWER_KEY_SEGMENTS, AnswerKeyAccessError
from swreview.report.session import load_session, save_session

ReviewFn = Callable[..., Any]


def _default_review_fn(package_dir: Path, session_out_dir: Path, *, model: str, effort: str) -> Any:
    from swreview.agent.runner import run_review

    return run_review(package_dir, session_out_dir, model=model, effort=effort)


def _reject_answer_key_path(path: Path) -> None:
    resolved = Path(path).resolve()
    parts = resolved.parts
    for index in range(len(parts) - 1):
        if (parts[index].lower(), parts[index + 1].lower()) == ANSWER_KEY_SEGMENTS:
            raise AnswerKeyAccessError(
                f"{resolved} is inside benchmarks/answer_keys; the benchmark runner never "
                "passes an answer-key path to the reviewer"
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
    current = session.timing
    session.timing = current.__class__(
        baseline_minutes=current.baseline_minutes,
        assisted_supervision_minutes=current.assisted_supervision_minutes,
        assisted_verification_minutes=current.assisted_verification_minutes,
        false_alarm_handling_minutes=current.false_alarm_handling_minutes,
        unattended_runtime_minutes=elapsed_minutes,
    )
    save_session(session, session_path)


def run_benchmark(
    set_path: Path | str,
    out_dir: Path | str,
    model: str,
    effort: str,
    review_fn: ReviewFn | None = None,
) -> list[Path]:
    """Review every package of the benchmark set at `set_path` into `out_dir`.

    Calls `review_fn(package_dir, out_dir/package_id, model=model, effort=effort)` per
    package (default: `swreview.agent.runner.run_review`), then records unattended
    runtime for that package. Returns the list of per-package output directories, in
    benchmark-set order.
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
        active_review_fn(ref.path, package_out_dir, model=model, effort=effort)
        elapsed_minutes = (time.perf_counter() - started) / 60.0

        _record_unattended_runtime(package_out_dir, elapsed_minutes)
        package_dirs.append(package_out_dir)

    return package_dirs
