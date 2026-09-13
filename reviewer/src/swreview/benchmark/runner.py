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
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from swreview.benchmark.sets import BenchmarkSet, load_set
from swreview.ir.loader import reject_answer_key_path
from swreview.report.session import load_session, save_session

ReviewFn = Callable[..., Any]


def _default_review_fn(
    package_dir: Path, session_out_dir: Path, *, provider: str, model: str, effort: str
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

    return _review_fn(package_dir, session_out_dir, provider=provider, model=model, effort=effort)


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
) -> list[Path]:
    """Review every package of the benchmark set at `set_path` into `out_dir`.

    Calls `review_fn(package_dir, out_dir/package_id, provider=provider, model=model,
    effort=effort)` per package (default: `_default_review_fn`), then records unattended
    runtime for that package. Returns the list of per-package output directories, in
    benchmark-set order.

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
        active_review_fn(ref.path, package_out_dir, provider=provider, model=model, effort=effort)
        elapsed_minutes = (time.perf_counter() - started) / 60.0

        _record_unattended_runtime(package_out_dir, elapsed_minutes)
        package_dirs.append(package_out_dir)

    return package_dirs
