"""Unit tests for T092: answer keys stay unreadable by the reviewer, at every layer.

`swreview.ir.loader.load_package` already refuses any path under
`benchmarks/answer_keys/` (tests/unit/test_ir_loader.py); this file covers the two
benchmark-harness layers built on top of it: `swreview.benchmark.sets.load_set` refuses
to reference an answer key as a package, and `swreview.benchmark.runner.run_benchmark`
never hands a package path under `benchmarks/answer_keys/` to its review function - both
through the set it loads and, defensively, on its own.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from swreview.benchmark.runner import run_benchmark
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet, load_set
from swreview.ir.loader import AnswerKeyAccessError


def write_set(directory: Path, name: str, packages: list[dict[str, object]]) -> Path:
    """Write a benchmark set file at `<directory>/benchmarks/sets/<name>.json`."""
    sets_dir = directory / "benchmarks" / "sets"
    sets_dir.mkdir(parents=True, exist_ok=True)
    set_path = sets_dir / f"{name}.json"
    set_path.write_text(json.dumps({"name": name, "packages": packages}), encoding="utf-8")
    return set_path


def test_load_set_reads_ordinary_packages(tmp_path: Path) -> None:
    set_path = write_set(
        tmp_path,
        "pilot",
        [
            {
                "package_id": "cover-blind-tap",
                "path": "benchmarks/packages/cover-blind-tap",
                "held_out": False,
            }
        ],
    )

    benchmark_set = load_set(set_path)

    assert benchmark_set.name == "pilot"
    assert benchmark_set.packages[0].package_id == "cover-blind-tap"
    expected_path = tmp_path / "benchmarks" / "packages" / "cover-blind-tap"
    assert benchmark_set.packages[0].path == expected_path
    assert benchmark_set.packages[0].held_out is False


def test_load_set_refuses_a_package_path_under_answer_keys(tmp_path: Path) -> None:
    set_path = write_set(
        tmp_path,
        "leaky",
        [
            {
                "package_id": "cover-blind-tap",
                "path": "benchmarks/answer_keys/cover-blind-tap",
                "held_out": False,
            }
        ],
    )

    with pytest.raises(AnswerKeyAccessError):
        load_set(set_path)


def test_load_set_refuses_a_junction_that_points_into_answer_keys(tmp_path: Path) -> None:
    real = tmp_path / "benchmarks" / "answer_keys" / "cover-blind-tap"
    real.mkdir(parents=True)
    link = tmp_path / "benchmarks" / "packages" / "sneaky-package"
    link.parent.mkdir(parents=True)
    if sys.platform == "win32":
        # A directory junction needs no privilege on Windows, unlike a symlink.
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(real)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"cannot create a junction here: {completed.stderr.strip()}")
    else:
        # The same rule must hold for a POSIX symlink: the loader resolves the path first.
        os.symlink(real, link, target_is_directory=True)
    set_path = write_set(
        tmp_path,
        "sneaky",
        [
            {
                "package_id": "sneaky-package",
                "path": "benchmarks/packages/sneaky-package",
                "held_out": False,
            }
        ],
    )

    with pytest.raises(AnswerKeyAccessError):
        load_set(set_path)


def test_run_benchmark_never_passes_an_answer_key_path(tmp_path: Path) -> None:
    package_dir = tmp_path / "benchmarks" / "packages" / "pkg-1"
    package_dir.mkdir(parents=True)
    set_path = write_set(
        tmp_path,
        "custom",
        [{"package_id": "pkg-1", "path": "benchmarks/packages/pkg-1", "held_out": False}],
    )
    calls: list[tuple[Path, Path, str, str, str]] = []

    def fake_review_fn(
        package_path: Path,
        session_out_dir: Path,
        *,
        provider: str,
        model: str,
        effort: str,
        efficiency: object,
    ) -> None:
        calls.append((package_path, session_out_dir, provider, model, effort))

    out_dir = tmp_path / "out"
    run_benchmark(
        set_path,
        out_dir,
        provider="openai",
        model="gpt-5.6",
        effort="high",
        review_fn=fake_review_fn,
    )

    assert len(calls) == 1
    package_path, session_out_dir, provider, model, effort = calls[0]
    assert "answer_keys" not in {part.lower() for part in package_path.parts}
    assert package_path == package_dir.resolve()
    assert session_out_dir == out_dir / "pkg-1"
    assert provider == "openai"
    assert model == "gpt-5.6"
    assert effort == "high"


def test_run_benchmark_refuses_an_answer_key_path_even_if_the_set_object_smuggles_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense in depth: even if a `BenchmarkSet` is constructed directly - bypassing
    `load_set`'s own check - the runner refuses to call `review_fn` on a package path
    under `benchmarks/answer_keys/`.
    """
    smuggled = BenchmarkSet(
        name="smuggled",
        packages=[
            BenchmarkPackageRef(
                package_id="evil",
                path=tmp_path / "benchmarks" / "answer_keys" / "evil",
                held_out=False,
            )
        ],
    )
    monkeypatch.setattr("swreview.benchmark.runner.load_set", lambda _path: smuggled)
    calls: list[object] = []

    with pytest.raises(AnswerKeyAccessError):
        run_benchmark(
            tmp_path / "unused-set.json",
            tmp_path / "out",
            provider="fake",
            model="m",
            effort="low",
            review_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []
