"""Unit tests for the benchmark runner's own default review function (T023).

Every other test that reaches `run_benchmark` injects a `review_fn`, and so does
`swreview.cli.benchmark_run`, which means `_default_review_fn` - the wiring a caller gets
when it asks for none - has never been executed by the suite. A wrong keyword there (the
runner takes `key_source=`, not `key=`) would ship green. `--provider fake` needs no
credential, so exercising it costs nothing but still runs the whole path: settings,
adapter, turn, `session.json`.

Feature 014 T095 (`contracts/scripted-answers.md` 2.3, 6 and 7; `benchmark-run.md` 3 row 4;
`provenance.md` 1; INT-14, QA-7; FR-013, US4-6, US4-8): `run_benchmark` takes the
`PreflightedSet` that `preflight_set` returns, the loaded set and each entry's loaded case file,
so a case file failing any row of section 2.3 stops the run before the first review; the saved
set carries each case file's digest, so one changed byte moves `set_digest`; and the record holds
the answer-turn bound, read "not recorded" where a record lacks it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import ProviderName
from swreview.agent.settings import DEFAULT_EFFORT, default_model
from swreview.benchmark.answers import CaseFileError
from swreview.benchmark.case_file import CaseFile
from swreview.benchmark.runner import (
    PROVENANCE_FILE,
    PreflightedSet,
    load_provenance,
    preflight_set,
    run_benchmark,
)
from swreview.benchmark.sets import load_set
from tests.unit.test_benchmark_case_file import (
    BEFORE_ANY_REVIEW,
    CASE_NAME,
    PACKAGE_ID,
    PREFIX,
    case,
    case_file_set,
    item_answer,
)

FAKE_MODEL = default_model(ProviderName.FAKE)


def write_set(path: Path, package_dir: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": "pilot",
                "packages": [{"package_id": "cover", "path": str(package_dir), "held_out": True}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_benchmark_without_a_review_fn_reviews_the_set_on_the_named_provider(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = write_set(tmp_path / "sets" / "pilot.json", tmp_package_dir)
    out_dir = tmp_path / "runs" / "default-review-fn"

    package_dirs = run_benchmark(
        preflight_set(set_path, None, load_checklist()),
        out_dir,
        provider=ProviderName.FAKE.value,
        model=FAKE_MODEL,
        effort=DEFAULT_EFFORT,
    )

    assert package_dirs == [out_dir / "cover"]
    session = json.loads((out_dir / "cover" / "session.json").read_text(encoding="utf-8"))
    assert session["model"] == FAKE_MODEL
    assert session["provider_info"]["provider"] == ProviderName.FAKE.value
    assert session["provider_info"]["key_source"] == "none"
    assert session["timing"]["unattended_runtime_minutes"] >= 0
    assert (out_dir / "cover" / "events.jsonl").is_file()


# --- the preflighted set (INT-14; `scripted-answers.md` 2.3) ----------------------------------


def cover_entry(package_dir: Path) -> dict[str, Any]:
    """A set entry naming no case file: every question of its reviews is unscripted."""
    return {"package_id": "cover", "path": str(package_dir), "held_out": True}


def test_preflight_set_holds_the_loaded_set_and_each_entrys_case_file(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """A frozen value: the set as `load_set` reads it against the root given, that root, and per
    package id the `CaseFile` loaded for an entry naming one, `None` for an entry naming none."""
    payload = case(item_answer())
    set_path = case_file_set(tmp_path, payload, cover_entry(tmp_package_dir))

    preflighted = preflight_set(set_path, None, load_checklist(), root=tmp_path)

    assert isinstance(preflighted, PreflightedSet)
    assert preflighted.benchmark_set == load_set(set_path, root=tmp_path)
    assert preflighted.root == tmp_path
    assert dict(preflighted.case_files) == {
        PACKAGE_ID: CaseFile.model_validate(payload),
        "cover": None,
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        preflighted.root = tmp_package_dir  # type: ignore[misc]


@pytest.mark.parametrize(("content", "named"), BEFORE_ANY_REVIEW)
def test_a_case_file_failing_any_row_stops_preflight_before_any_review(
    content: dict[str, Any] | str | None, named: str, tmp_path: Path
) -> None:
    """US4-8: `preflight_set` refuses with the case file's one line, so the spy review function
    handed to `run_benchmark` after it is never called and no package folder is created."""
    set_path = case_file_set(tmp_path, content)
    out_dir = tmp_path / "runs" / "refused"
    calls: list[object] = []

    with pytest.raises(CaseFileError) as refused:
        run_benchmark(
            preflight_set(set_path, None, load_checklist()),
            out_dir,
            provider="fake",
            model="m",
            effort="low",
            review_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    message = str(refused.value)
    assert message.startswith(PREFIX), message
    assert named in message, message
    assert calls == []
    assert not out_dir.exists()


def test_a_case_file_that_cannot_be_read_is_refused_by_row_1_before_its_package_loads(
    tmp_path: Path,
) -> None:
    """The set loader took no digest of a case file it could not read (`benchmark/sets.py`), and
    `preflight_set` refuses it by row 1 naming it, before loading its package: here the package
    folder is gone too, and the refusal is still the case file's, with no local folder in it."""
    set_path = case_file_set(tmp_path, None)
    shutil.rmtree(tmp_path / "packages" / PACKAGE_ID)

    with pytest.raises(CaseFileError) as refused:
        preflight_set(set_path, None, load_checklist())

    message = str(refused.value)
    assert message.startswith(f"{PREFIX}cannot be read ("), message
    assert str(tmp_path) not in message


def test_run_benchmark_requires_a_preflighted_set(tmp_path: Path, tmp_package_dir: Path) -> None:
    """INT-14: a set path is not enough, so a library caller cannot skip the refusals."""
    set_path = write_set(tmp_path / "sets" / "pilot.json", tmp_package_dir)
    calls: list[object] = []

    with pytest.raises(TypeError) as refused:
        run_benchmark(
            set_path,  # type: ignore[arg-type]
            tmp_path / "out",
            provider="fake",
            model="m",
            effort="low",
            review_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert "preflight_set" in str(refused.value)
    assert calls == []
    assert not (tmp_path / "out").exists()


# --- what a run records of its case files and bound (US4-6, QA-7, FR-013) ---------------------


def fake_run(set_path: Path, out: Path) -> dict[str, Any]:
    """`benchmark run --provider fake` of `set_path` into `out`, its record as written."""
    result = CliRunner().invoke(
        cli.app,
        ["benchmark", "run", "--set", str(set_path), "--out", str(out), "--provider", "fake"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    return json.loads((out / PROVENANCE_FILE).read_text(encoding="utf-8"))


def test_the_saved_set_carries_each_case_files_digest_and_one_changed_byte_moves_set_digest(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """US4-6, QA-7: both arms get the same answers because a study whose arms read different
    case-file bytes records two `set_digest`s, which compare already holds equal."""
    set_path = case_file_set(tmp_path, case(item_answer()), cover_entry(tmp_package_dir))
    case_path = tmp_path / "case_files" / CASE_NAME
    read = case_path.read_bytes()

    first = fake_run(set_path, tmp_path / "runs" / "first")
    case_path.write_bytes(read.replace(b"press fit", b"press fix"))
    second = fake_run(set_path, tmp_path / "runs" / "second")

    saved = json.loads((tmp_path / "runs" / "first" / "benchmark-set.json").read_bytes())
    entries = {entry["package_id"]: entry for entry in saved["packages"]}
    assert entries[PACKAGE_ID]["case_file_sha256"] == hashlib.sha256(read).hexdigest()
    assert "case_file_sha256" not in entries["cover"]
    for record, run in ((first, "first"), (second, "second")):
        saved_bytes = (tmp_path / "runs" / run / "benchmark-set.json").read_bytes()
        assert record["set_digest"] == hashlib.sha256(saved_bytes).hexdigest()
    assert first["set_digest"] != second["set_digest"]


def test_the_record_holds_the_answer_turn_bound_and_one_without_it_reads_none(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """FR-013: `max_answer_turns` as the run used it, 3 untyped; a record written before the
    field reads `None`, "not recorded", never 3."""
    out = tmp_path / "runs" / "bound"
    record = fake_run(write_set(tmp_path / "sets" / "pilot.json", tmp_package_dir), out)

    assert record["max_answer_turns"] == 3
    loaded = load_provenance(out)
    assert loaded is not None and loaded.max_answer_turns == 3

    del record["max_answer_turns"]
    (out / PROVENANCE_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    older = load_provenance(out)
    assert older is not None
    assert older.max_answer_turns is None
