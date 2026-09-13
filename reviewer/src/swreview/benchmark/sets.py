"""Benchmark sets: which packages belong to a run, and which are held out.

Mirrors `benchmarks/sets/pilot.json` (benchmarks/README.md): a name plus a list of
package references, each a `package_id`, a path (repo-root relative in the committed
file), and a `held_out` flag consumed by the scorer's recall calculation.

This module never reads an answer key. It does refuse, at load time, any package path
that resolves under `benchmarks/answer_keys/` - the same rule `swreview.ir.loader`
enforces when the reviewer actually opens a package, applied here so a misconfigured set
fails before a run ever starts (constitution Principle VI, FR-025).
"""

from __future__ import annotations

import json
from pathlib import Path

from swreview.findings import ReviewModel
from swreview.ir.loader import ANSWER_KEY_SEGMENTS, AnswerKeyAccessError


class BenchmarkPackageRef(ReviewModel):
    """One package entry in a benchmark set."""

    package_id: str
    path: Path
    held_out: bool = False


class BenchmarkSet(ReviewModel):
    name: str
    packages: list[BenchmarkPackageRef]


def _reject_answer_key_path(path: Path) -> Path:
    """Raise `AnswerKeyAccessError` if `path` resolves under `benchmarks/answer_keys/`."""
    resolved = path.resolve()
    parts = resolved.parts
    for index in range(len(parts) - 1):
        if (parts[index].lower(), parts[index + 1].lower()) == ANSWER_KEY_SEGMENTS:
            raise AnswerKeyAccessError(
                f"{resolved} is inside benchmarks/answer_keys; a benchmark set may not "
                "reference an answer key as a package"
            )
    return resolved


def load_set(path: Path | str) -> BenchmarkSet:
    """Read a benchmark set file such as `benchmarks/sets/pilot.json`.

    Package paths are resolved against the repo root, taken to be two directories above
    the set file (`benchmarks/sets/<name>.json` -> repo root), matching the layout
    documented in `benchmarks/README.md`. Raises `AnswerKeyAccessError` if any package
    path - directly, or through a symlink or junction - resolves under
    `benchmarks/answer_keys/`.
    """
    set_path = Path(path).resolve()
    repo_root = set_path.parents[2]
    payload = json.loads(set_path.read_text(encoding="utf-8"))

    packages = []
    for entry in payload["packages"]:
        raw_path = Path(entry["path"])
        candidate = raw_path if raw_path.is_absolute() else repo_root / raw_path
        resolved = _reject_answer_key_path(candidate)
        packages.append(
            BenchmarkPackageRef(
                package_id=entry["package_id"],
                path=resolved,
                held_out=bool(entry.get("held_out", False)),
            )
        )
    return BenchmarkSet(name=payload["name"], packages=packages)
