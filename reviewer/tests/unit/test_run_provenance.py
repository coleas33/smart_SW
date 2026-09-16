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

No network: every command here runs `--provider fake`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import CHECKLIST_FILE
from swreview.agent.providers import ProviderName
from swreview.agent.runner import DEFAULT_MAX_STEPS
from swreview.agent.settings import LEVER_NAMES, EfficiencySettings, default_model
from swreview.benchmark.runner import (
    PROVENANCE_FILE,
    RunProvenance,
    current_commit,
    load_provenance,
    sha256_of,
    write_provenance,
)

runner = CliRunner()

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
    assert read_record(out)["efficiency"] == session["efficiency"]


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


def test_current_commit_is_none_outside_a_git_tree(tmp_path: Path) -> None:
    """Null, never a guess: a run whose commit we do not know renders as unknown."""
    assert current_commit(tmp_path) is None
