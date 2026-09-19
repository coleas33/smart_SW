"""`swreview attention <run_dir>`: the keyless reader of the ranking (T020, FR-017).

The command exists so the policy can be argued over a real run folder without a licence,
a key or a write. Four properties carry that, and each is a way the command could go
wrong:

- **it writes nothing.** The folder is hashed file by file before and after, the idiom
  `test_cli_remodel_plan.py` uses. A reader that re-rendered `report.md` or refreshed
  `attention.json` as a side effect would make "have a look at the ranking" an edit to the
  run, and the engineer would no longer be reading what the run recorded;
- **it constructs no provider.** Both routes to an adapter are monkeypatched to raise
  (`no_provider`), so a command that quietly built one fails here rather than on a
  workstation with no key;
- **it is the report's ranking, not a second one.** `--json`'s `attention` is compared
  against `rank(load_session(...))`'s own JSON, so the reader cannot drift from the
  section the report prints (the reason `contracts/cli.md` offers no `--top` and no
  `--class`);
- **a folder with no run is exit 1 naming the path.** `run_folder_session` owns both
  refusals - "this folder holds no run" and "this is a benchmark run root" - and the
  command only has to let them out.

The two committed fixtures are the subjects: the 2026-09-18 review folder, whose top row
is an `interference.static` finding, and the model-check folder, whose top row is the
under-defined sketch because no needs-judgement finding exists on that surface.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from swreview.agent import providers
from swreview.report.attention import coverage_line, rank, start_here_lines
from swreview.report.session import load_session
from tests.support.attention import CHECK_FOLDER, REVIEW_FOLDER
from tests.unit.test_attention import CHECK_ORDER, REVIEW_ORDER
from tests.unit.test_cli import invoke, payload


def digest(directory: Path) -> dict[str, str]:
    """Every file under `directory` with its content hash, so a write cannot hide."""
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every route to an adapter raises: the reader talks to no model at all."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("`swreview attention` must construct no provider")

    monkeypatch.setattr(providers, "get", refuse)
    monkeypatch.setattr("swreview.cli.provider_factory", refuse)


@pytest.fixture
def review_dir(tmp_path: Path) -> Path:
    """The committed review folder, copied so a write by the command would show."""
    target = tmp_path / "20260918-215755-review"
    shutil.copytree(REVIEW_FOLDER, target)
    return target


@pytest.fixture
def check_dir(tmp_path: Path) -> Path:
    target = tmp_path / "20260918-220310-check"
    shutil.copytree(CHECK_FOLDER, target)
    return target


# --- 1. what it prints ----------------------------------------------------------------


def test_it_prints_the_policy_version(review_dir: Path, no_provider: None) -> None:
    result = invoke("attention", str(review_dir))

    assert result.exit_code == 0, result.stdout
    assert "attention_policy_v1" in result.stdout


def test_it_prints_the_amplified_rows_and_the_coverage_block_the_report_prints(
    review_dir: Path, no_provider: None
) -> None:
    """The reader renders through the same two functions the report's section does, so a
    top five here and a different top five in `report.md` cannot happen."""
    ranking = rank(load_session(review_dir / "session.json"))

    stdout = invoke("attention", str(review_dir)).stdout

    for line in [*start_here_lines(ranking), *coverage_line(ranking)]:
        if line:
            assert line in stdout, line


def test_it_prints_every_row_in_order_with_its_nine_key_values(
    review_dir: Path, no_provider: None
) -> None:
    """Every row, not only the amplified five: this is the command an argument about a
    placement is settled with, and a placement is settled by reading the keys."""
    ranking = rank(load_session(review_dir / "session.json"))

    stdout = invoke("attention", str(review_dir)).stdout

    positions = [stdout.index(finding_id) for finding_id in REVIEW_ORDER]
    assert positions == sorted(positions), "the rows print in ranking order"
    for row in ranking.rows:
        assert row.reason in stdout
        for name, value in row.key.model_dump().items():
            assert f"{name} {value}" in stdout


def test_the_check_folder_leads_with_the_under_defined_sketch(
    check_dir: Path, no_provider: None
) -> None:
    body = payload(invoke("attention", str(check_dir), "--json"))

    assert [row["finding_id"] for row in body["attention"]["rows"]] == list(CHECK_ORDER)
    assert body["attention"]["rows"][0]["check"] == "rms.sketches.fully_defined"


def test_no_rendered_line_carries_a_percent_sign(review_dir: Path, no_provider: None) -> None:
    """Research R2.14: everything the ranking renders can reach the Standards tab, whose
    body scan forbids one."""
    assert "%" not in invoke("attention", str(review_dir)).stdout


# --- 2. the payload -------------------------------------------------------------------


def test_the_json_payload_is_the_run_the_session_and_the_ranking(
    review_dir: Path, no_provider: None
) -> None:
    body = payload(invoke("attention", str(review_dir), "--json"))

    assert set(body) == {"run_dir", "session_file", "attention"}
    assert body["run_dir"] == str(review_dir.resolve())
    assert body["session_file"] == str((review_dir / "session.json").resolve())


def test_the_payload_ranking_is_exactly_what_rank_produces(
    review_dir: Path, no_provider: None
) -> None:
    """`contracts/cli.md`: `attention` is the `Ranking` JSON, so the reader is the policy
    rather than a second rendering of it."""
    expected = json.loads(rank(load_session(review_dir / "session.json")).model_dump_json())

    body = payload(invoke("attention", str(review_dir), "--json"))

    assert body["attention"] == expected
    assert [row["finding_id"] for row in body["attention"]["rows"]] == list(REVIEW_ORDER)
    assert "session_id" not in body["attention"]


# --- 3. it writes nothing -------------------------------------------------------------


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_the_folder_is_byte_for_byte_what_it_was(
    review_dir: Path, no_provider: None, json_flag: list[str]
) -> None:
    before = digest(review_dir)

    assert invoke("attention", str(review_dir), *json_flag).exit_code == 0

    assert digest(review_dir) == before


def test_reading_a_check_folder_writes_no_record_over_the_one_the_check_wrote(
    check_dir: Path, no_provider: None
) -> None:
    """`GET` computes and never writes (contract section 4): the reader is a `GET`."""
    before = digest(check_dir)

    assert invoke("attention", str(check_dir), "--json").exit_code == 0

    assert digest(check_dir) == before


# --- 4. the refusals ------------------------------------------------------------------


def test_a_folder_with_no_session_exits_1_naming_the_path(
    tmp_path: Path, no_provider: None
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = invoke("attention", str(empty))

    assert result.exit_code == 1
    assert str(empty / "session.json") in result.stderr
    assert list(empty.iterdir()) == []


def test_a_benchmark_run_root_is_pointed_at_benchmark_time(
    tmp_path: Path, no_provider: None
) -> None:
    """The second refusal `run_folder_session` owns, inherited rather than restated."""
    root = tmp_path / "20260918-benchmark"
    (root / "pkg-1").mkdir(parents=True)
    shutil.copy(REVIEW_FOLDER / "session.json", root / "pkg-1" / "session.json")

    result = invoke("attention", str(root))

    assert result.exit_code == 1
    assert "swreview benchmark time" in result.stderr
