"""The run provenance record: what produced this run folder (T037, for T038).

A run folder is a measurement, and a measurement nobody can attribute to a configuration
is not evidence. `session.efficiency` records the settings the *runner* resolved;
this record is written by `cli.py` from the options actually typed, and the two together
are what `swreview benchmark compare` cross-checks (RK-20, contracts/ab-harness.md
section 3). Two independent writers is the whole point: one writer can only agree with
itself.

Three things this module pins.

1. **`--study`, `--arm` and `--rep` are typed, never derived.** Which lever a run is
   testing, which arm it is and which repetition it is are facts *across two run
   folders*, not inside one. A lever-6 off run (`--lever prompt_cache_key`), a lever-3 on
   run (`--lever prompt_cache_key`) and a baseline run are byte-identical in settings and
   in `session.efficiency`; nothing in the settings tells them apart, and nothing infers
   them from the folder name.
2. **The record is the complete settings dump, not a diff**, so a reader never has to
   reconstruct what the other nine flags were (contracts/ab-harness.md section 9, test 2).
3. **A run directory missing the record is still a real run.** `load_provenance` returns
   `None` rather than raising, because a run made before the convention existed renders
   as a row with those columns null (T041), not as an error.

Feature 014 (T045; `specs/014-design-review-eval/contracts/provenance.md` 1 and 8, data-model
section 7) adds schema 2, written before any review: the pane-defaults marker, the resolved model
view, the profile's digest and whether it is the checkout's example, the live tools, the inert
settings, the prompt's digest and whether the tracked tree was dirty. A record older than that
reads each new field as not recorded, and no record holds a path.

No network: every command here runs the scripted provider.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import CHECKLIST_FILE, SYSTEM_PROMPT_FILE
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import DEFAULT_MAX_STEPS
from swreview.agent.settings import (
    INERT_SETTINGS,
    LEVER_NAMES,
    MODEL_VIEW_PANE,
    EfficiencySettings,
    ProviderSettings,
    default_model,
    pane_defaults,
)
from swreview.benchmark import digest, sets
from swreview.benchmark import runner as benchmark_runner
from swreview.benchmark.runner import (
    PROVENANCE_FILE,
    RunProvenance,
    current_commit,
    load_provenance,
    profile_is_example,
    sha256_of,
    tree_dirty,
    write_provenance,
)
from swreview.checks.standards.profile import load_profile
from tests.unit.test_cli import PROVIDER_ENV

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"

FAKE_MODEL = default_model(ProviderName.FAKE)


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


def one_package_set(tmp_path: Path, package_dir: Path, *, held_out: bool = True) -> Path:
    set_path = tmp_path / "sets" / "study.json"
    set_path.parent.mkdir(parents=True, exist_ok=True)
    set_path.write_text(
        json.dumps(
            {
                "name": "study",
                "packages": [
                    {"package_id": "cover", "path": str(package_dir), "held_out": held_out}
                ],
            }
        ),
        encoding="utf-8",
    )
    return set_path


def run_arm(set_path: Path, out: Path, *extra: str) -> Any:
    return invoke(
        "benchmark",
        "run",
        "--set",
        str(set_path),
        "--out",
        str(out),
        "--provider",
        "fake",
        *extra,
    )


def read_record(out: Path) -> dict[str, Any]:
    return json.loads((out / PROVENANCE_FILE).read_text(encoding="utf-8"))


# --- what `benchmark run` writes -------------------------------------------------


def test_benchmark_run_writes_the_record_beside_the_saved_set(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "on-2"

    result = run_arm(
        set_path,
        out,
        "--lever",
        "tool_tiers",
        "--study",
        "tool_tiers",
        "--arm",
        "on",
        "--rep",
        "2",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (out / "benchmark-set.json").is_file()
    record = read_record(out)
    assert record["lever"] == "tool_tiers"
    assert record["arm"] == "on"
    assert record["rep"] == 2
    assert record["provider"] == ProviderName.FAKE.value
    assert record["model"] == FAKE_MODEL
    assert record["effort"] == "high"
    assert record["max_steps"] == DEFAULT_MAX_STEPS
    assert record["set_too_small_override"] is False
    assert record["started_at"]


def test_the_record_holds_the_complete_settings_dump_and_not_a_diff(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "on-1"

    result = run_arm(
        set_path,
        out,
        "--lever",
        "tool_tiers",
        "--study",
        "tool_tiers",
        "--arm",
        "on",
        "--rep",
        "1",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    efficiency = read_record(out)["efficiency"]
    assert set(efficiency) == set(LEVER_NAMES)
    assert efficiency["tool_tiers"] is True
    assert all(value is False for name, value in efficiency.items() if name != "tool_tiers")


def test_the_record_agrees_with_the_session_the_runner_wrote(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """The two independent writers, agreeing - which is what `compare` checks (RK-20)."""
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "off-1"

    result = run_arm(set_path, out, "--study", "tool_tiers", "--arm", "off", "--rep", "1")

    assert result.exit_code == 0, result.stdout + result.stderr
    session = json.loads((out / "cover" / "session.json").read_text(encoding="utf-8"))
    # The record names all fourteen levers; the session writes levers 13 and 14 only when on
    # (feature 008 amendment; feature 013 T121, edited deliberately), so an off arm's session
    # carries the other twelve, equal.
    assert "withhold_prerun_tools" not in session["efficiency"]
    assert "drop_prior_reasoning" not in session["efficiency"]
    assert read_record(out)["efficiency"] == {
        **session["efficiency"],
        "withhold_prerun_tools": False,
        "drop_prior_reasoning": False,
    }


def test_a_baseline_run_records_lever_none_and_arm_baseline(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "baseline-3"

    result = run_arm(set_path, out, "--study", "none", "--arm", "baseline", "--rep", "3")

    assert result.exit_code == 0, result.stdout + result.stderr
    record = read_record(out)
    assert record["lever"] == "none"
    assert record["arm"] == "baseline"
    assert record["rep"] == 3
    assert all(value is False for value in record["efficiency"].values())


def test_a_run_that_declares_no_study_still_gets_a_record_with_nulls(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """A smoke run is still a run: the record exists and says it belongs to no arm."""
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "smoke"

    result = run_arm(set_path, out)

    assert result.exit_code == 0, result.stdout + result.stderr
    record = read_record(out)
    assert record["lever"] == "none"
    assert record["arm"] is None
    assert record["rep"] is None


def test_the_too_small_set_override_is_written_into_the_record(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """So the rows it produces can never be read as a gate (FR-029, SC-011)."""
    set_path = one_package_set(tmp_path, tmp_package_dir, held_out=False)
    out = tmp_path / "runs" / "smoke-override"

    result = run_arm(
        set_path,
        out,
        "--study",
        "tool_tiers",
        "--arm",
        "off",
        "--rep",
        "1",
        "--i-know-the-set-is-too-small",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert read_record(out)["set_too_small_override"] is True


def test_the_digests_are_of_the_saved_set_copy_and_the_checklist(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    """Two of the four fields `compare` refuses a mismatched pair on.

    The **saved** copy rather than the file `--set` named, so the digest is of the
    canonical serialization sitting in the run directory and `compare` can check the two
    against each other without being handed the original file.
    """
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "off-1"

    result = run_arm(set_path, out, "--study", "tool_tiers", "--arm", "off", "--rep", "1")

    assert result.exit_code == 0, result.stdout + result.stderr
    record = read_record(out)
    saved = (out / "benchmark-set.json").read_bytes()
    assert record["set_digest"] == hashlib.sha256(saved).hexdigest()
    assert record["checklist_digest"] == hashlib.sha256(CHECKLIST_FILE.read_bytes()).hexdigest()


def test_the_commit_is_the_tree_the_run_was_made_from(
    tmp_path: Path, tmp_package_dir: Path
) -> None:
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "off-1"

    result = run_arm(set_path, out, "--study", "tool_tiers", "--arm", "off", "--rep", "1")

    assert result.exit_code == 0, result.stdout + result.stderr
    assert read_record(out)["commit"] == current_commit()


# --- the record itself -----------------------------------------------------------


def a_record(**overrides: Any) -> RunProvenance:
    fields: dict[str, Any] = {
        "commit": "5733efd",
        "lever": "parallel_tool_calls",
        "arm": "on",
        "rep": 2,
        "provider": "openai",
        "model": "gpt-5.6",
        "effort": "high",
        "max_steps": DEFAULT_MAX_STEPS,
        "checklist_digest": "a" * 64,
        "set_digest": "b" * 64,
        "started_at": "2026-09-16T09:00:00+00:00",
        "set_too_small_override": False,
        "efficiency": EfficiencySettings(parallel_tool_calls=True),
    }
    fields.update(overrides)
    return RunProvenance(**fields)


def test_the_record_round_trips_through_the_run_directory(tmp_path: Path) -> None:
    record = a_record()

    written = write_provenance(tmp_path, record)

    assert written == tmp_path / PROVENANCE_FILE
    assert load_provenance(tmp_path) == record


def test_a_directory_with_no_record_reads_as_none_rather_than_raising(tmp_path: Path) -> None:
    """A run made before the convention existed is still a real run (T041)."""
    assert load_provenance(tmp_path) is None


def test_a_record_carrying_an_unknown_field_fails_loudly(tmp_path: Path) -> None:
    """The same rule `EfficiencySettings` holds to: a record nobody can reconstruct is
    worse than an error."""
    write_provenance(tmp_path, a_record())
    path = tmp_path / PROVENANCE_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["arm_2"] = "on"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_provenance(tmp_path)


@pytest.mark.parametrize("rep", [0, -1])
def test_a_repetition_index_below_one_is_refused(rep: int) -> None:
    with pytest.raises(ValueError):
        a_record(rep=rep)


def test_an_unknown_arm_is_refused() -> None:
    with pytest.raises(ValueError):
        a_record(arm="control")


# --- the two inputs the record digests -------------------------------------------


def test_sha256_of_is_the_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "set.json"
    path.write_bytes(b'{"name": "study"}')

    assert sha256_of(path) == hashlib.sha256(b'{"name": "study"}').hexdigest()


def test_current_commit_matches_git(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[3],
    )
    expected = proc.stdout.strip() if proc.returncode == 0 else None

    assert current_commit() == expected


def test_current_commit_is_none_outside_a_git_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Null, never a guess: a run whose commit we do not know renders as unknown.

    `tmp_path` is not necessarily outside a git tree: CI runs pytest with
    `--basetemp=.pytest-tmp` inside the checkout, where `git rev-parse` walks up and
    finds this repository. `GIT_CEILING_DIRECTORIES` stops git from ascending past
    `tmp_path`, so the directory below it is outside any repository wherever it lives.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert current_commit(outside) is None


# --- schema 2, written before any review (feature 014 T045) ----------------------


def example_profile_copy(folder: Path) -> Path:
    """The checkout's example profile, its bytes copied under another name into `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / "standards-under-test.yaml"
    copy.write_bytes(EXAMPLE_PROFILE.read_bytes())
    return copy


SliceRun = tuple[list[str], dict[str, Any]]
"""One run of a slice's test: the options typed, and each field the slice lands with the value
that run writes."""


def slice_2_runs(tmp_path: Path) -> list[SliceRun]:
    """The parity slice's options, and every field it adds with the value it writes
    (`provenance.md` 1; data-model section 7)."""
    profile = example_profile_copy(tmp_path / "profiles")
    options = ["--pane-defaults", "--standards-profile", str(profile)]
    expected = {
        "provenance_schema": 2,
        "pane_defaults": True,
        "model_view": pane_defaults(ProviderName.FAKE).model_view.model_dump(mode="json"),
        "profile_digest": load_profile(profile).identity.sha256,
        "profile_is_example": True,
        "live_tools": False,
        "inert_settings": list(INERT_SETTINGS[ProviderName.FAKE]),
        "prompt_digest": digest.sha256_of(SYSTEM_PROMPT_FILE),
        "tree_dirty": tree_dirty(root=REPO_ROOT),
    }
    return [(options, expected)]


def slice_3_runs(tmp_path: Path) -> list[SliceRun]:
    """The scripted-answers slice's one field, the answer-turn bound (`scripted-answers.md` 4):
    as typed, and untyped as its default, 3."""
    return [(["--max-answer-turns", "0"], {"max_answer_turns": 0}), ([], {"max_answer_turns": 3})]


def slice_6_runs(tmp_path: Path) -> list[SliceRun]:
    """T201/T205: the clocks, retry policy and record-only package concurrency (36A)."""
    defaults = {
        "package_time_limit_s": 3600,
        "stream_activity_window_s": 600,
        "stop_grace_s": 900,
        "retry_policy": {"retries": 5, "initial_delay_s": 2.0, "max_delay_s": 60.0},
        "jobs": 1,
    }
    return [([], defaults), (["--jobs", "3"], {**defaults, "jobs": 3})]


SLICE_RUNS = {2: slice_2_runs, 3: slice_3_runs, 6: slice_6_runs}
"""Each slice's runs and the fields it lands, by slice number (T201 adds slice 6); each
slice asserts its own fields and nothing about another slice's."""


@pytest.mark.parametrize("slice_number", sorted(SLICE_RUNS))
def test_provenance_records_every_field_its_slice_adds(
    slice_number: int, tmp_path: Path, tmp_package_dir: Path
) -> None:
    """FR-013, FR-052, US2-3: every field a slice adds is in the record, with its value."""
    set_path = one_package_set(tmp_path, tmp_package_dir)
    for index, (options, expected) in enumerate(SLICE_RUNS[slice_number](tmp_path)):
        out = tmp_path / "runs" / f"slice-{slice_number}-{index}"

        result = run_arm(set_path, out, *options)

        assert result.exit_code == 0, result.stdout + result.stderr
        record = read_record(out)
        assert {name: record[name] for name in expected} == expected


def spellings(path: Path) -> set[str]:
    """Every way a record could hold `path`: either separator, raw and JSON-escaped."""
    native = str(path)
    forms = {native, native.replace("\\", "/"), native.replace("/", "\\")}
    return forms | {json.dumps(form)[1:-1] for form in forms}


def test_provenance_holds_no_path(tmp_path: Path, tmp_package_dir: Path) -> None:
    """FR-013, FR-051: neither the profile's path nor its folder, the set file's, a package's
    nor the output folder's - a run folder is committed, and a path names a user's machine."""
    profile = example_profile_copy(tmp_path / "profiles")
    set_path = one_package_set(tmp_path, tmp_package_dir)
    out = tmp_path / "runs" / "no-path"

    result = run_arm(set_path, out, "--pane-defaults", "--standards-profile", str(profile))

    assert result.exit_code == 0, result.stdout + result.stderr
    text = (out / PROVENANCE_FILE).read_text(encoding="utf-8")
    for path in (profile, profile.parent, set_path, tmp_package_dir, out):
        for form in spellings(path) | spellings(path.resolve()):
            assert form not in text, f"the record names {form}"


SCHEMA_2_FIELDS: dict[str, Any] = {
    "provenance_schema": 2,
    "pane_defaults": True,
    "model_view": MODEL_VIEW_PANE,
    "profile_digest": "c" * 64,
    "profile_is_example": True,
    "live_tools": False,
    "inert_settings": ("parallel_tool_calls", "drop_prior_reasoning"),
    "prompt_digest": "d" * 64,
    "tree_dirty": False,
}
"""Every field schema 2 adds, each with a value other than its "not recorded" default."""

NOT_RECORDED: tuple[str, ...] = (
    "model_view",
    "profile_digest",
    "profile_is_example",
    "live_tools",
    "inert_settings",
    "prompt_digest",
    "tree_dirty",
    "package_time_limit_s",
    "stream_activity_window_s",
    "stop_grace_s",
    "retry_policy",
    "jobs",
)
"""The new fields a record older than feature 014 reads as `None`, "not recorded"."""


def test_a_record_older_than_this_feature_reads_the_new_fields_not_recorded(
    tmp_path: Path,
) -> None:
    """A record exactly as `be01974` wrote it: schema 1, no pane-defaults marker, and every
    other new field not recorded rather than guessed."""
    written_before = {
        "commit": "5733efd",
        "lever": "parallel_tool_calls",
        "arm": "on",
        "rep": 2,
        "provider": "openai",
        "model": "gpt-5.6",
        "effort": "high",
        "max_steps": DEFAULT_MAX_STEPS,
        "checklist_digest": "a" * 64,
        "set_digest": "b" * 64,
        "started_at": "2026-09-16T09:00:00Z",
        "set_too_small_override": False,
        "efficiency": EfficiencySettings(parallel_tool_calls=True).model_dump(mode="json"),
        "explanations_enabled": False,
    }
    (tmp_path / PROVENANCE_FILE).write_text(json.dumps(written_before, indent=2), encoding="utf-8")

    record = load_provenance(tmp_path)

    assert record is not None
    assert record.provenance_schema == 1
    assert record.pane_defaults is False
    assert {name: getattr(record, name) for name in NOT_RECORDED} == dict.fromkeys(NOT_RECORDED)


def test_an_unknown_field_still_fails_loudly(tmp_path: Path) -> None:
    """A schema-2 record reads back whole, and one field more than this build knows fails it,
    as before (`benchmark/runner.py`'s strict model)."""
    record = a_record(**SCHEMA_2_FIELDS)
    write_provenance(tmp_path, record)
    assert load_provenance(tmp_path) == record

    path = tmp_path / PROVENANCE_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["profile_path"] = "standards.yaml"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_provenance(tmp_path)


def test_the_record_is_utf8_with_lf_line_endings(tmp_path: Path) -> None:
    """Written as bytes through the one atomic writer, so a record is the same bytes on every
    platform (`benchmark-run.md` section 4)."""
    write_provenance(tmp_path, a_record(**SCHEMA_2_FIELDS))

    written = (tmp_path / PROVENANCE_FILE).read_bytes()
    assert b"\r" not in written
    assert written.endswith(b"}\n")


def test_profile_is_example_is_true_only_for_the_checkouts_example_bytes(tmp_path: Path) -> None:
    """Compared against the `config/standards.example.yaml` of the root given, byte for byte;
    the profile's file name and folder play no part."""
    checkout = tmp_path / "checkout"
    example = checkout / "config" / "standards.example.yaml"
    example.parent.mkdir(parents=True)
    example_bytes = EXAMPLE_PROFILE.read_bytes() + b"# this checkout's own example\n"
    example.write_bytes(example_bytes)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    renamed = profiles / "renamed.yaml"
    renamed.write_bytes(example_bytes)
    one_byte_changed = profiles / "one-byte.yaml"
    one_byte_changed.write_bytes(example_bytes[:-2] + b"!\n")

    assert profile_is_example(renamed, root=checkout) is True
    assert profile_is_example(one_byte_changed, root=checkout) is False
    assert profile_is_example(EXAMPLE_PROFILE, root=checkout) is False
    assert profile_is_example(renamed, root=tmp_path / "no-example-here") is False
    assert profile_is_example(None, root=checkout) is None


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=30)


def test_tree_dirty_reads_tracked_changes_only_and_is_null_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git status --porcelain --untracked-files=no`: an untracked file is not a change to the
    code a run measured, a modified tracked file is, and git that cannot answer is `None`."""
    if shutil.which("git") is None:
        pytest.skip("git is not on the path")
    repository = tmp_path / "repository"
    repository.mkdir()
    git(repository, "init", "-q")
    tracked = repository / "tracked.txt"
    tracked.write_bytes(b"one\n")
    git(repository, "add", "tracked.txt")
    git(
        repository,
        "-c",
        "user.name=Fictional Tester",
        "-c",
        "user.email=tester@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "first",
    )

    assert tree_dirty(root=repository) is False
    (repository / "untracked.txt").write_bytes(b"new\n")
    assert tree_dirty(root=repository) is False
    tracked.write_bytes(b"two\n")
    assert tree_dirty(root=repository) is True

    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert tree_dirty(root=outside) is None

    def no_git(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("git is not on the path")

    monkeypatch.setattr("swreview.benchmark.runner.subprocess.run", no_git)
    assert tree_dirty(root=repository) is None


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (benchmark_runner, "committable"),
        (benchmark_runner, "tree_dirty"),
        (benchmark_runner, "profile_is_example"),
        (sets, "checkout_relative"),
    ],
    ids=["committable", "tree_dirty", "profile_is_example", "checkout_relative"],
)
def test_the_checkout_predicates_take_the_root_by_keyword_with_no_default(
    module: Any, name: str
) -> None:
    """One signature for the runner's three predicates on a checkout and the rule they share:
    `root` by keyword, with no default. `benchmark run` reads `sets.REPO_ROOT` once per
    invocation and passes it on (T051), while a default is bound once, at import, so a call that
    left the root out would ask about the import-time checkout rather than the one the command
    read; with no default it fails instead."""
    root = inspect.signature(getattr(module, name)).parameters["root"]

    assert root.kind is inspect.Parameter.KEYWORD_ONLY
    assert root.default is inspect.Parameter.empty


def test_inert_settings_name_parallel_calls_and_dropped_reasoning_on_gemini_only(
    tmp_path: Path, tmp_package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-052: Gemini makes parallel calls whatever the flag and sends no reasoning items for
    lever 14 to drop; OpenAI's and the scripted provider's lists are empty. Each run records
    its own provider's list, here over a scripted adapter standing in for every provider."""
    assert INERT_SETTINGS[ProviderName.GEMINI] == ("parallel_tool_calls", "drop_prior_reasoning")
    assert INERT_SETTINGS[ProviderName.OPENAI] == ()
    assert INERT_SETTINGS[ProviderName.FAKE] == ()
    assert set(INERT_SETTINGS) == set(ProviderName)

    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)

    def scripted(
        settings: ProviderSettings, efficiency: EfficiencySettings | None = None
    ) -> FakeProvider:
        return FakeProvider(script=[ScriptedTurn(text="done")], model=settings.model)

    monkeypatch.setattr(cli, "provider_factory", scripted)
    set_path = one_package_set(tmp_path, tmp_package_dir)

    for provider in ProviderName:
        out = tmp_path / "runs" / provider.value
        result = invoke(
            "benchmark",
            "run",
            "--set",
            str(set_path),
            "--out",
            str(out),
            "--provider",
            provider.value,
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert read_record(out)["inert_settings"] == list(INERT_SETTINGS[provider]), provider
