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
so a case file failing any row of section 2.3, row 10 read under the run's standards profile,
stops the run before the first review; the saved
set carries each case file's digest, so one changed byte moves `set_digest`; and the record holds
the answer-turn bound, read "not recorded" where a record lacks it.

Feature 014 T116 (`contracts/cases.md` 4.4 and 9; CS-16, INT-14; FR-030, FR-032; US5-3):
`preflight_set` checks the set's files exist after the profile preflight and before the case-file
checks: a package folder holding no `package.json`, committed or private, and a key that is not a
file are each refused in one line naming every missing one, before any review and with no package
folder created; and a run over a keyed set stats its keys and never opens one.
"""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import ProviderName
from swreview.agent.settings import DEFAULT_EFFORT, default_model
from swreview.benchmark import runner
from swreview.benchmark.answers import CaseFileError
from swreview.benchmark.case_file import CaseFile
from swreview.benchmark.runner import (
    PROVENANCE_FILE,
    PreflightedSet,
    load_provenance,
    preflight_set,
    run_benchmark,
)
from swreview.benchmark.sets import SetError, load_set
from swreview.checks.standards.profile import ProfileUnreadable, load_profile
from swreview.ir.loader import PACKAGE_FILE_NAME, save_package
from tests.support.packages import build_package
from tests.support.roles_review import write_profile
from tests.unit.test_benchmark_case_file import (
    BEFORE_ANY_REVIEW,
    CASE_NAME,
    PACKAGE_ID,
    PREFIX,
    case,
    case_file_set,
    item_answer,
    roles_answer,
)
from tests.unit.test_benchmark_run_options import one_line, refusal_line

FAKE_MODEL = default_model(ProviderName.FAKE)


@pytest.mark.parametrize("folder", [
    "../fict-outside", "/fict-outside", "C:/fict-outside", "C:\\fict-outside",
    "\\\\fict-host\\fict-share", "fict-a/../fict-b", "fict-a/", "./fict-a",
    "attempts/fict-a/0", "attempts/fict-a/01", "attempts/fict-a/١", "attempts/fict-a/-1",
])
def test_attempt_status_refuses_folders_outside_the_recorded_run(folder: str) -> None:
    from datetime import UTC, datetime

    with pytest.raises(ValueError, match="run-relative attempt folder"):
        runner.AttemptStatus(
            attempt=1, started_at=datetime(2026, 10, 15, tzinfo=UTC), folder=folder,
        )


def test_attempt_folder_resolution_refuses_a_symlink_outside_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = tmp_path / "run"
    outside = tmp_path / "fict-outside"
    real_resolve = Path.resolve

    def resolve(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path == run / "fict-a":
            return outside
        return real_resolve(path, *args, **kwargs)

    # Emulate the result of resolving a directory symlink on systems where
    # creating a symlink requires elevated Windows privileges.
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="outside the run"):
        runner.resolve_attempt_folder(run, "fict-a")


@pytest.mark.parametrize("custom_redactor", [False, True])
def test_library_run_benchmark_redacts_the_configured_key_from_status(
    tmp_path: Path, tmp_package_dir: Path, monkeypatch: pytest.MonkeyPatch, custom_redactor: bool,
) -> None:
    from swreview.agent.settings import MASK

    secret = "fict-library-openai-key"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    set_path = write_set(tmp_path / "sets/pilot.json", tmp_package_dir)
    out = tmp_path / "run"

    def review(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"fict failure includes {secret}; caller-value")

    options = {"redact": lambda text: text.replace("caller-value", "caller-redacted")} if (
        custom_redactor
    ) else {}
    run_benchmark(
        preflight_set(set_path, None, load_checklist()), out, provider="openai",
        model="fict-model-a", effort="low", review_fn=review,
        clock=lambda: 0.0, **options,
    )
    status = (out / runner.RUN_STATUS_FILE).read_text(encoding="utf-8")
    assert secret not in status
    assert MASK in status
    assert ("caller-redacted" if custom_redactor else "caller-value") in status


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
    `preflight_set` refuses it by row 1 naming it, before loading its package: here the package's
    `package.json` is no package either, which loading it would refuse, and the refusal is still
    the case file's, with no local folder in it. The file is there, since the existence checks
    before any case file refuse a folder holding none (T117, `cases.md` 4.4)."""
    set_path = case_file_set(tmp_path, None)
    (tmp_path / "packages" / PACKAGE_ID / PACKAGE_FILE_NAME).write_text(
        "{not a package", encoding="utf-8"
    )

    with pytest.raises(CaseFileError) as refused:
        preflight_set(set_path, None, load_checklist())

    message = str(refused.value)
    assert message.startswith(f"{PREFIX}cannot be read ("), message
    assert str(tmp_path) not in message


def test_the_profile_given_reaches_each_case_file_s_part_roles_row(tmp_path: Path) -> None:
    """Row 10 (`scripted-answers.md` 2.3; QA-5) asks the classifier over the profile the reviews
    will grade against: `preflight_set` holds a part-roles answer under the convention-only
    profile, which asks the part-roles question, and refuses the same set with no profile,
    naming the entry."""
    payload = case(roles_answer())
    set_path = case_file_set(tmp_path, payload)
    profile = load_profile(write_profile(tmp_path))

    preflighted = preflight_set(set_path, profile, load_checklist())

    assert dict(preflighted.case_files) == {PACKAGE_ID: CaseFile.model_validate(payload)}
    with pytest.raises(CaseFileError) as refused:
        preflight_set(set_path, None, load_checklist())
    message = str(refused.value)
    assert message.startswith(f"{PREFIX}A-3 answers the part-roles question"), message


def test_benchmark_run_checks_each_case_file_against_its_standards_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`benchmark-run.md` 3 row 4: the run's `--standards-profile` is the one row 10 reads, so a
    part-roles answer that profile asks for runs, while the same set with no profile is refused
    before any review."""
    set_path = case_file_set(tmp_path, case(roles_answer()))
    profile = write_profile(tmp_path)
    reviewed: list[Path] = []

    def spy(package_dir: Path, session_out_dir: Path, **_keywords: Any) -> None:
        reviewed.append(package_dir)

    monkeypatch.setattr(cli, "_review_fn", spy)

    def run(out: str, *options: str) -> Any:
        return CliRunner().invoke(
            cli.app,
            [
                "benchmark", "run", "--set", str(set_path), "--out", str(tmp_path / "runs" / out),
                "--provider", "fake", *options,
            ],
        )

    graded = run("graded", "--standards-profile", str(profile))
    assert graded.exit_code == 0, graded.stdout + graded.stderr
    assert len(reviewed) == 1

    ungraded = run("ungraded")
    assert ungraded.exit_code == 1, ungraded.stdout + ungraded.stderr
    assert f"{PREFIX}A-3 answers the part-roles question" in ungraded.stderr
    assert len(reviewed) == 1


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


# --- the set's files exist before any review (US5-3, FR-030, FR-032; `cases.md` 4.4) ---------


def checkout_set(root: Path, *entries: dict[str, Any]) -> Path:
    """A set named `pilot` in the file `<root>/benchmarks/sets/study.json`, so a relative entry
    resolves against `root` and a refusal's `{name}` is the set's name, not the file's."""
    set_path = root / "benchmarks" / "sets" / "study.json"
    set_path.parent.mkdir(parents=True, exist_ok=True)
    set_path.write_text(
        json.dumps({"name": "pilot", "packages": list(entries)}, indent=2), encoding="utf-8"
    )
    return set_path


def committed_case(root: Path, package_id: str) -> dict[str, Any]:
    """A committed entry of a keyed set: its package written under `<root>/benchmarks/packages/`
    and its key under `<root>/benchmarks/answer_keys/`, both named root-relative. The key's bytes
    are never read, so they need not be a key."""
    save_package(build_package(), root / "benchmarks" / "packages" / package_id)
    key = root / "benchmarks" / "answer_keys" / f"{package_id}.json"
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text('{"key_format": 2}\n', encoding="utf-8")
    return {
        "package_id": package_id,
        "path": f"benchmarks/packages/{package_id}",
        "key": f"benchmarks/answer_keys/{package_id}.json",
        "held_out": True,
    }


def private_case(vault: Path, package_id: str) -> dict[str, Any]:
    """A private entry of a keyed set: its package under `<vault>/packages/` and its key under
    `<vault>/keys/`, both named absolutely, outside the checkout."""
    package = save_package(build_package(), vault / "packages" / package_id).parent
    key = vault / "keys" / f"{package_id}.json"
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text('{"key_format": 2}\n', encoding="utf-8")
    return {"package_id": package_id, "path": str(package), "key": str(key), "held_out": True}


def test_a_set_naming_missing_packages_is_refused_before_any_review_naming_every_one(
    tmp_path: Path,
) -> None:
    """US5-3: a committed folder holding no `package.json` and a private folder that is not there
    are named in one line, in set order, the committed one root-relative as the entry serializer
    writes it and the private one absolute; the package that is there is not named, the review
    function is never called and no folder is created under the run's folder."""
    root = tmp_path / "checkout"
    save_package(build_package(), root / "benchmarks" / "packages" / "kept")
    (root / "benchmarks" / "packages" / "hollow").mkdir(parents=True)
    away = tmp_path / "vault" / "packages" / "away"
    set_path = checkout_set(
        root,
        {"package_id": "kept", "path": "benchmarks/packages/kept", "held_out": True},
        {"package_id": "hollow", "path": "benchmarks/packages/hollow", "held_out": True},
        {"package_id": "away", "path": str(away), "held_out": True},
    )
    out_dir = tmp_path / "runs" / "refused"
    calls: list[object] = []

    with pytest.raises(SetError) as refused:
        run_benchmark(
            preflight_set(set_path, None, load_checklist(), root=root),
            out_dir,
            provider="fake",
            model="m",
            effort="low",
            review_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert str(refused.value) == (
        "benchmark set pilot: 2 package(s) missing: hollow at benchmarks/packages/hollow; "
        f"away at {away.resolve().as_posix()}"
    )
    assert calls == []
    assert not out_dir.exists()


def test_a_keyed_set_naming_missing_keys_is_refused_before_any_review_naming_every_one(
    tmp_path: Path,
) -> None:
    """CS-16: a key that is not there and a key path that is a folder, not a file, are named in
    one line the same way, before any review: a missing private key found by `benchmark score`
    after the paid runs would waste them."""
    root = tmp_path / "checkout"
    vault = tmp_path / "vault"
    lost = committed_case(root, "lost")
    away = private_case(vault, "away")
    set_path = checkout_set(root, committed_case(root, "kept"), lost, away)
    (root / lost["key"]).unlink()
    away_key = Path(away["key"])
    away_key.unlink()
    away_key.mkdir()
    out_dir = tmp_path / "runs" / "refused"
    calls: list[object] = []

    with pytest.raises(SetError) as refused:
        run_benchmark(
            preflight_set(set_path, None, load_checklist(), root=root),
            out_dir,
            provider="fake",
            model="m",
            effort="low",
            review_fn=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert str(refused.value) == (
        "benchmark set pilot: 2 key(s) missing: lost at benchmarks/answer_keys/lost.json; "
        f"away at {away_key.resolve().as_posix()}"
    )
    assert calls == []
    assert not out_dir.exists()


def test_the_package_check_ends_the_preflight_before_the_key_check(tmp_path: Path) -> None:
    """Each check ends the preflight: a set missing one entry's `package.json` and another's key
    is named by the missing package alone."""
    root = tmp_path / "checkout"
    hollow = committed_case(root, "hollow")
    lost = committed_case(root, "lost")
    set_path = checkout_set(root, hollow, lost)
    (root / hollow["path"] / PACKAGE_FILE_NAME).unlink()
    (root / lost["key"]).unlink()

    with pytest.raises(SetError) as refused:
        preflight_set(set_path, None, load_checklist(), root=root)

    assert str(refused.value) == (
        "benchmark set pilot: 1 package(s) missing: hollow at benchmarks/packages/hollow"
    )


def test_a_run_over_a_keyed_set_stats_its_keys_and_never_opens_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-032: the preflight and the run over a keyed set whose keys are there review every
    package, and a spy on both ways a file is opened fails the test on any open of a key; the
    stat that checks a key is there is allowed."""
    root = tmp_path / "checkout"
    kept = committed_case(root, "kept")
    away = private_case(tmp_path / "vault", "away")
    set_path = checkout_set(root, kept, away)
    keys = {(root / kept["key"]).resolve(), Path(away["key"]).resolve()}
    real_open, real_path_open = builtins.open, Path.open

    def refuse_a_key(file: object) -> None:
        if isinstance(file, str | os.PathLike) and Path(file).resolve() in keys:
            pytest.fail(f"the run opened the key {file}")

    def spied_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        refuse_a_key(file)
        return real_open(file, *args, **kwargs)

    def spied_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        refuse_a_key(self)
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spied_open)
    monkeypatch.setattr(Path, "open", spied_path_open)
    reviewed: list[Path] = []

    run_benchmark(
        preflight_set(set_path, None, load_checklist(), root=root),
        tmp_path / "runs" / "keyed",
        provider="fake",
        model="m",
        effort="low",
        review_fn=lambda package_dir, _out, **_keywords: reviewed.append(package_dir),
    )

    assert reviewed == [
        (root / kept["path"]).resolve(),
        (tmp_path / "vault" / "packages" / "away").resolve(),
    ]


def test_a_missing_package_is_named_before_any_case_file_is_checked(tmp_path: Path) -> None:
    """The existence checks come before the case-file checks (`cases.md` 4.4): the first entry's
    case file is not JSON and the second entry's package is not there, and the refusal names the
    missing package."""
    gone = tmp_path / "vault" / "gone"
    set_path = case_file_set(
        tmp_path, "{not json", {"package_id": "gone", "path": str(gone), "held_out": True}
    )

    with pytest.raises(SetError) as refused:
        preflight_set(set_path, None, load_checklist())

    assert str(refused.value) == (
        f"benchmark set fict: 1 package(s) missing: gone at {gone.resolve().as_posix()}"
    )


def test_benchmark_run_refuses_an_unreadable_profile_before_a_missing_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The existence checks come after the profile preflight (`cases.md` 4.4; FR-050): over a set
    naming a missing package, an unreadable `--standards-profile` is the one line printed; with no
    profile, the missing package is, each with exit 1, no review and no run folder."""
    gone = tmp_path / "vault" / "gone"
    set_path = write_set(tmp_path / "sets" / "pilot.json", gone)
    missing = tmp_path / "profiles" / "absent.yaml"
    reviewed: list[Path] = []
    monkeypatch.setattr(
        cli, "_review_fn", lambda package_dir, _out, **_keywords: reviewed.append(package_dir)
    )

    def run(out: Path, *options: str) -> Any:
        return CliRunner().invoke(
            cli.app,
            [
                "benchmark", "run", "--set", str(set_path), "--out", str(out),
                "--provider", "fake", *options,
            ],
        )

    profiled = run(tmp_path / "runs" / "profiled", "--standards-profile", str(missing))
    assert profiled.exit_code == 1, profiled.stdout + profiled.stderr
    assert one_line(profiled) == refusal_line(ProfileUnreadable, missing)

    unprofiled = run(tmp_path / "runs" / "unprofiled")
    assert unprofiled.exit_code == 1, unprofiled.stdout + unprofiled.stderr
    assert one_line(unprofiled).startswith(
        "error: SetError: benchmark set pilot: 1 package(s) missing: cover at "
    )

    assert reviewed == []
    assert not (tmp_path / "runs").exists()


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
