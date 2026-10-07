"""The scoring-rules version, and the one reader of `scorecard.json` (feature 014 T036, for T038).

`contracts/scoring.md` 8 (FR-008, SP-11, D14.2; plan decisions SR-18, INT-11). Any change to
matching or counting, and any new required scorecard field, bumps
`benchmark/scorecard.SCORING_RULES_VERSION`; the scorer slice writes 2, pinned here by value until
the validation slice's version record exists. A scorecard without the field was scored under
version 1.

`read_scorecard(run_dir)` is the one reader. It reads the version **before** validating, so a
folder scored before this feature meets the re-score line rather than a validation error naming a
field it could not have had, and a folder scored by a newer build is refused too; then it
validates, naming the folder and the first field. Compare's `_load_run` calls it before it loads a
session or runs a parity check. Re-scoring reads the saved session and re-runs nothing (US1-11).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from swreview import cli
from swreview.benchmark import scorecard as scorecard_module
from swreview.benchmark.compare import compare_runs
from swreview.benchmark.scorecard import score_run
from tests.support.answer_keys import write_key
from tests.support.prerun import CHECKS_FIRST, review
from tests.support.studies import RunSpec, write_run
from tests.unit.test_scorecard import build_scoring_fixture

SCORECARD_AT_BE01974 = (
    "run_id",
    "benchmark_set",
    "scored_at",
    "per_package",
    "aggregate",
    "distribution",
)
PACKAGE_SCORE_AT_BE01974 = (
    "package_id",
    "held_out",
    "session_id",
    "valid_findings",
    "missed_known_defects",
    "false_alarms",
    "unresolved_count",
    "baseline_minutes",
    "assisted_minutes",
    "unattended_runtime_minutes",
    "net_saved_minutes",
    "usage",
    "round_trips",
    "cached_input_share",
    "wall_clock_s",
    "seconds_to_first_finding",
    "carried_findings",
    "unresolved_because_withheld",
    "unresolved_other",
    "coverage_bucket_mix",
    "tool_calls_by_name",
    "matched_defect_ids",
    "missed_defect_ids",
    "false_alarm_finding_ids",
)
AGGREGATE_AT_BE01974 = (
    "packages",
    "held_out_packages",
    "valid_findings",
    "missed_known_defects",
    "false_alarms",
    "unresolved_count",
    "recall",
    "false_alarm_rate",
    "median_net_saved_minutes",
    "packages_with_timing",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "round_trips",
    "median_seconds_to_first_finding",
    "packages_with_usage",
)
"""The fields a `scorecard.json` held at `be01974` (`benchmark/scorecard.py:143-246`), the
shape a folder scored before this feature has."""


def re_score_line(run_dir: Path) -> str:
    """`scoring.md` 8's refusal of a scorecard scored under version 1, as fixed text."""
    return (
        f"{run_dir}: scorecard.json was scored under scoring rules version 1; this build scores "
        f"under 2. Re-score it: swreview benchmark score {run_dir} (add --answer-keys <dir> when "
        "its set names no keys; it reads the saved session; nothing is re-run)"
    )


def as_at_be01974(payload: dict[str, Any]) -> dict[str, Any]:
    """`payload` cut to the fields a scorecard held at `be01974`: no version and none of this
    feature's fields."""

    def kept(value: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
        return {name: value[name] for name in names}

    old = kept(payload, SCORECARD_AT_BE01974)
    old["per_package"] = [kept(score, PACKAGE_SCORE_AT_BE01974) for score in old["per_package"]]
    old["aggregate"] = kept(old["aggregate"], AGGREGATE_AT_BE01974)
    return old


def rewrite_scorecard(run_dir: Path, edit: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Rewrite `run_dir`'s `scorecard.json` through `edit`, as a hand or an older build would."""
    path = run_dir / "scorecard.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(edit(payload), indent=2) + "\n", encoding="utf-8")


def with_fields(**fields: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda payload: {**payload, **fields}


def refusal(run_dir: Path) -> ValueError:
    """What compare raises over `run_dir`, which must be a `ValueError` and never pydantic's
    bare validation error."""
    with pytest.raises(ValueError) as caught:
        compare_runs([run_dir])
    assert not isinstance(caught.value, ValidationError), caught.value
    return caught.value


# --- 1. score_run writes the version ---------------------------------------------------------


def test_the_scoring_rules_version_is_2_and_score_run_writes_it(tmp_path: Path) -> None:
    """Pinned by value until the version record exists (INT-11)."""
    assert scorecard_module.SCORING_RULES_VERSION == 2

    scorecard = score_run(*build_scoring_fixture(tmp_path))

    assert scorecard.scoring_rules_version == 2


# --- 2. an old scorecard meets the re-score line, before any session or parity check ---------


def test_compare_refuses_a_scorecard_written_before_this_feature_with_the_re_score_line(
    tmp_path: Path,
) -> None:
    """The run's session carries no `efficiency` and its saved set no longer matches its record,
    two refusals compare would otherwise raise first: the version is read before either."""
    run_dir = write_run(tmp_path, RunSpec(run="off-1"), session_edit={"efficiency": None})
    (run_dir / "benchmark-set.json").write_text('{"name": "edited", "packages": []}\n', "utf-8")
    with pytest.raises(ValueError, match="predates the flag carrier"):
        compare_runs([run_dir])

    rewrite_scorecard(run_dir, as_at_be01974)

    assert str(refusal(run_dir)) == re_score_line(run_dir)


def test_read_scorecard_is_the_reader_that_refuses_it(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, RunSpec(run="off-1"))
    rewrite_scorecard(run_dir, as_at_be01974)

    with pytest.raises(ValueError) as caught:
        scorecard_module.read_scorecard(run_dir)

    assert str(caught.value) == re_score_line(run_dir)


def test_a_scorecard_stating_version_1_meets_the_same_line(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, RunSpec(run="off-1"))
    rewrite_scorecard(run_dir, with_fields(scoring_rules_version=1))

    assert str(refusal(run_dir)) == re_score_line(run_dir)


# --- 3. a newer version --------------------------------------------------------------------


def test_compare_refuses_a_scorecard_of_a_newer_version(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, RunSpec(run="off-1"))
    rewrite_scorecard(run_dir, with_fields(scoring_rules_version=3))

    assert str(refusal(run_dir)) == (
        f"{run_dir}: scorecard.json was scored by a newer build (version 3); compare it with "
        "that build, or re-score it with this one"
    )


# --- 4. a malformed scorecard of this version ------------------------------------------------


def test_an_unknown_field_is_refused_naming_the_folder_and_the_field(tmp_path: Path) -> None:
    run_dir = write_run(tmp_path, RunSpec(run="off-1"))
    rewrite_scorecard(run_dir, with_fields(surplus=1))

    message = str(refusal(run_dir))

    assert message.startswith(f"{run_dir}: scorecard.json ")
    assert "surplus" in message


def test_a_missing_required_field_is_refused_naming_the_folder_and_the_field(
    tmp_path: Path,
) -> None:
    """Every new field is required, never defaulted (SR-17)."""
    run_dir = write_run(tmp_path, RunSpec(run="off-1"))

    def without_cleared(payload: dict[str, Any]) -> dict[str, Any]:
        del payload["per_package"][0]["cleared_defect_ids"]
        return payload

    rewrite_scorecard(run_dir, without_cleared)

    message = str(refusal(run_dir))

    assert message.startswith(f"{run_dir}: scorecard.json ")
    assert "per_package.0.cleared_defect_ids" in message


# --- 5. re-scoring reads the saved session and re-runs nothing (US1-11) ----------------------


def test_re_scoring_an_old_folder_writes_the_current_version_and_compare_accepts_it(
    tmp_path: Path,
) -> None:
    """A checks-first review whose session was written before the origin marks (no
    `origin_marks` record), scored before this feature: compare refuses it; `benchmark score`
    re-scores it from the saved session, and its code findings read `unknown` (5.3 rule 3)."""
    review(tmp_path, "run/pkg-a", efficiency=CHECKS_FIRST)
    run_dir = tmp_path / "run"
    session_file = run_dir / "pkg-a" / "session.json"
    session = json.loads(session_file.read_text(encoding="utf-8"))
    del session["origin_marks"]
    session_file.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    keys = tmp_path / "answer_keys"
    write_key(keys, "pkg-a")
    set_file = tmp_path / "sets" / "study.json"
    set_file.parent.mkdir()
    set_file.write_text(
        json.dumps(
            {
                "name": "study",
                "packages": [
                    {"package_id": "pkg-a", "path": str(tmp_path / "package"), "held_out": False}
                ],
            }
        ),
        encoding="utf-8",
    )
    score = ["benchmark", "score", str(run_dir), "--answer-keys", str(keys), "--set", str(set_file)]
    first = CliRunner().invoke(cli.app, score)
    assert first.exit_code == 0, first.stdout + first.stderr
    rewrite_scorecard(run_dir, as_at_be01974)
    assert "Re-score it" in str(refusal(run_dir))

    rescored = CliRunner().invoke(cli.app, score)

    assert rescored.exit_code == 0, rescored.stdout + rescored.stderr
    payload = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert payload["scoring_rules_version"] == 2
    assert [row.package_id for row in compare_runs([run_dir]).runs] == ["pkg-a"]
    origins = payload["per_package"][0]["finding_origins"]
    assert origins
    assert set(origins.values()) == {"unknown"}
