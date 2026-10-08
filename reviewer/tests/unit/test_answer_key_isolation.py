"""Unit tests for T092: answer keys stay unreadable by the reviewer, at every layer.

`swreview.ir.loader.load_package` already refuses any path under
`benchmarks/answer_keys/` (tests/unit/test_ir_loader.py); this file covers the two
benchmark-harness layers built on top of it: `swreview.benchmark.sets.load_set` refuses
to reference an answer key as a package, and `swreview.benchmark.runner.run_benchmark`
never hands a package path under `benchmarks/answer_keys/` to its review function - both
through the set it loads and, defensively, on its own.

Feature 014 T093 adds the case file's half (`contracts/scripted-answers.md` 6 and 7; US4-9,
FR-030; QA-6), here in the unit file only, since the integration file is module-marked
`integration` (RF-26): the guard withholds a committed case file's folder,
`benchmarks/case_files/`, as it withholds the keys', and a private set whose package path is,
or lies under, its own case file's folder is refused at `load_set` by row 5, so that path
never reaches `load_package`.

Feature 014 T114 adds the key's half (`contracts/cases.md` 4.3 row 5 and 9; US5-11, FR-030;
CS-15): a key a private set names cannot reach `load_package` either, since a package folder at
the key's folder, and a key inside the package folder, are each refused at `load_set` by row 5.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from swreview.agent.checklist import load_checklist
from swreview.benchmark.runner import PreflightedSet, preflight_set, run_benchmark
from swreview.benchmark.sets import BenchmarkPackageRef, BenchmarkSet, SetError, load_set
from swreview.ir.loader import AnswerKeyAccessError, load_package
from tests.support.packages import build_package


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

    benchmark_set = load_set(set_path, root=tmp_path)

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
        load_set(set_path, root=tmp_path)


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
        load_set(set_path, root=tmp_path)


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
        attempt: object,
    ) -> None:
        calls.append((package_path, session_out_dir, provider, model, effort))

    out_dir = tmp_path / "out"
    run_benchmark(
        preflight_set(set_path, None, load_checklist(), root=tmp_path),
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
    tmp_path: Path,
) -> None:
    """Defense in depth: even if a `BenchmarkSet` is constructed directly - bypassing
    `load_set`'s own check - the runner refuses to call `review_fn` on a package path
    under `benchmarks/answer_keys/`. Since feature 014 T097 (RF-61) the smuggled set is held by
    a `PreflightedSet` built directly, bypassing `preflight_set` too.
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
    preflighted = PreflightedSet(benchmark_set=smuggled, root=tmp_path, case_files={"evil": None})
    calls: list[object] = []

    with pytest.raises(AnswerKeyAccessError):
        run_benchmark(
            preflighted,
            tmp_path / "out",
            provider="fake",
            model="m",
            effort="low",
            review_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []


# --- the case file's half (feature 014 T093) ------------------------------------------


@pytest.mark.parametrize(
    "folder",
    ["benchmarks/case_files", "benchmarks/case_files/pkg-1"],
    ids=["the case files' folder", "a folder in it"],
)
def test_load_package_refuses_a_path_under_case_files(tmp_path: Path, folder: str) -> None:
    """A real `package.json` lies there, so the refusal is the guard's and not a missing
    file's; its message names the segment it met (QA-6)."""
    package_dir = tmp_path / folder
    package_dir.mkdir(parents=True)
    (package_dir / "package.json").write_text(
        build_package().model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(AnswerKeyAccessError) as refused:
        load_package(package_dir)

    assert str(refused.value).startswith(
        f"{package_dir.resolve()} is inside benchmarks/case_files; "
    )


@pytest.mark.parametrize(
    "package",
    ["vault/answers", "vault/answers/pkg-1"],
    ids=["the case file's folder", "a folder under it"],
)
def test_a_private_set_whose_package_is_at_or_under_its_case_file_s_folder_is_refused_at_load_set(
    tmp_path: Path, package: str
) -> None:
    """Row 5 (`contracts/cases.md` 4.3): the set is refused as it loads, before any reader is
    handed the package path, so the case file never reaches `load_package` (US4-9). Every path
    is private: absolute, outside the root."""
    root = tmp_path / "checkout"
    case_file = tmp_path / "vault" / "answers" / "pkg-1.case.json"
    case_file.parent.mkdir(parents=True)
    case_file.write_text('{"case_file_version": 1}\n', encoding="utf-8")
    package_dir = tmp_path / package
    set_path = tmp_path / "vault" / "private.json"
    set_path.write_text(
        json.dumps(
            {
                "name": "private",
                "packages": [
                    {
                        "package_id": "pkg-1",
                        "path": str(package_dir),
                        "case_file": str(case_file),
                        "held_out": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SetError) as refused:
        load_set(set_path, root=root)

    message = str(refused.value)
    assert message.startswith("benchmark set private.json:")
    assert str(package_dir.resolve()) in message
    assert str(case_file.resolve()) in message
    assert message.endswith(
        "the reviewer reads the package folder; keep keys and case files outside it"
    )


# --- the key's half (feature 014 T114) ------------------------------------------------


@pytest.mark.parametrize(
    ("package", "key"),
    [("vault/keys", "vault/keys/pkg-1.json"), ("vault/pkg-1", "vault/pkg-1/pkg-1.json")],
    ids=["the package folder is the key's folder", "the key lies inside the package folder"],
)
def test_a_private_set_whose_key_is_at_or_inside_its_package_folder_is_refused_at_load_set(
    tmp_path: Path, package: str, key: str
) -> None:
    """Row 5 (`contracts/cases.md` 4.3): the set is refused as it loads, before any reader is
    handed the package path, so the key never reaches `load_package` (US5-11). Every path is
    private: absolute, outside the root."""
    root = tmp_path / "checkout"
    key_path = tmp_path / key
    key_path.parent.mkdir(parents=True)
    key_path.write_text('{"key_format": 2}\n', encoding="utf-8")
    package_dir = tmp_path / package
    set_path = tmp_path / "vault" / "private.json"
    set_path.write_text(
        json.dumps(
            {
                "name": "private",
                "packages": [
                    {
                        "package_id": "pkg-1",
                        "path": str(package_dir),
                        "key": str(key_path),
                        "held_out": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SetError) as refused:
        load_set(set_path, root=root)

    message = str(refused.value)
    assert message.startswith("benchmark set private.json:")
    assert str(package_dir.resolve()) in message
    assert str(key_path.resolve()) in message
    assert message.endswith(
        "the reviewer reads the package folder; keep keys and case files outside it"
    )
