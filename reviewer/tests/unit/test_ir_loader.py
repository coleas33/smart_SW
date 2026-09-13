"""Unit tests for the evidence package loader (T011).

The loader is the reviewer's only door into a package, so it is also where the answer
keys are kept out (FR, benchmarks/README.md) and where a newer schema major has to be
distinguishable from a corrupt file.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from swreview.ir.loader import AnswerKeyAccessError, load_package, save_package
from swreview.ir.models import BodyRef, Capture, UnsupportedSchemaVersionError
from tests.support.packages import build_package, persist_ref


def write_package(directory: Path, **overrides: object) -> Path:
    """Write a package file directly, so answer-key directories can be set up too."""
    directory.mkdir(parents=True, exist_ok=True)
    text = build_package(**overrides).model_dump_json(indent=2)
    (directory / "package.json").write_text(text + "\n", encoding="utf-8")
    return directory


def test_loads_package_json_from_a_directory(tmp_path: Path) -> None:
    write_package(tmp_path)

    loaded = load_package(tmp_path)

    assert loaded.package.design.name == "cover-assy"
    assert loaded.base_dir == tmp_path.resolve()


def test_missing_package_json_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_package(tmp_path)


def test_resolves_mesh_and_capture_relative_paths(tmp_path: Path) -> None:
    body = BodyRef(
        id="bdy:1",
        persist_ref=persist_ref("bdy:1"),
        persist_ref_scope="doc:2",
        component_id="cmp:0001",
        mesh_file="meshes/housing-1.glb",
        triangle_count=120,
        is_solid=True,
    )
    capture = Capture(
        id="cap:1",
        persist_ref=persist_ref("cmp:0001"),
        component_ids=["cmp:0001"],
        file="captures/hole.png",
        view="Isometric",
        note="tapped hole",
    )
    write_package(tmp_path, bodies=[body], captures=[capture])

    loaded = load_package(tmp_path)

    base = tmp_path.resolve()
    assert loaded.resolve(loaded.package.bodies[0].mesh_file) == base / "meshes" / "housing-1.glb"
    assert loaded.resolve(loaded.package.captures[0].file) == base / "captures" / "hole.png"


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    original = build_package()

    save_package(original, tmp_path)
    loaded = load_package(tmp_path)

    assert loaded.package.model_dump(mode="json") == original.model_dump(mode="json")
    assert loaded.package.holes[0].thread_depth is None


def test_refuses_a_directory_under_benchmarks_answer_keys(tmp_path: Path) -> None:
    answer_keys = tmp_path / "benchmarks" / "answer_keys" / "cover-blind-tap"
    write_package(answer_keys)

    with pytest.raises(AnswerKeyAccessError):
        load_package(answer_keys)
    with pytest.raises(AnswerKeyAccessError):
        save_package(build_package(), answer_keys)


def test_allows_benchmarks_packages(tmp_path: Path) -> None:
    packages = tmp_path / "benchmarks" / "packages" / "cover-blind-tap"
    write_package(packages)

    assert load_package(packages).package.package_id


def test_refuses_a_junction_that_points_into_answer_keys(tmp_path: Path) -> None:
    real = tmp_path / "benchmarks" / "answer_keys" / "cover-blind-tap"
    write_package(real)
    link = tmp_path / "sneaky-package"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"cannot create a junction here: {completed.stderr.strip()}")

    with pytest.raises(AnswerKeyAccessError):
        load_package(link)


def test_unsupported_major_is_distinct_from_malformed_json(tmp_path: Path) -> None:
    newer = tmp_path / "newer"
    write_package(newer)
    payload = json.loads((newer / "package.json").read_text(encoding="utf-8"))
    payload["schema_version"] = "2.0.0"
    (newer / "package.json").write_text(json.dumps(payload), encoding="utf-8")

    broken = tmp_path / "broken"
    write_package(broken)
    (broken / "package.json").write_text('{"schema_version": "1.0.0", ', encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError):
        load_package(newer)
    with pytest.raises(ValidationError):
        load_package(broken)


def test_missing_required_field_is_a_validation_error(tmp_path: Path) -> None:
    directory = write_package(tmp_path)
    payload = json.loads((directory / "package.json").read_text(encoding="utf-8"))
    del payload["design"]
    (directory / "package.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_package(directory)
