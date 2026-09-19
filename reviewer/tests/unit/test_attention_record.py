"""`attention.json`: the ranking beside the session it was computed from (T027, FR-020).

The record exists so the order an engineer was shown can be read back later without
re-running anything, and so a disagreement about a placement is settled against the file
the run wrote rather than against today's policy. Three properties make it worth writing
at all, and each is tested from both directions here:

- **reproducible from the session alone.** `rank(load_session(...))` reproduces the record
  exactly. That is what makes the file evidence rather than a cache: a record that could
  not be recomputed would be a second source of truth about the same run;
- **stale when it names another session.** A review that claims a check folder rotates the
  check's session aside, and a record still naming it is no longer about the session that
  is in the folder. `read_attention_record` refuses it by name, the same rule `check.json`
  already follows through `recorded_session`;
- **not a session file.** It is written beside `session.json`, never into `SESSION_FILES`,
  so a folder holding only a record is not "a folder that already holds a review"
  (`test_chat_server.py` carries that half) and `is_check_folder` is still true for an RMS
  check folder that holds one (here).

Four writers put the record there, from the same `Ranking` the report was rendered from -
`ReviewRun.finalize` on the success and the failure path, the RMS check's `write_report`,
the standards check's `_write_report`, and `rerender_run_folder` for the offline commands
(research R2.7). Each of the four is exercised below against the one rule that matters:
the file it left behind reproduces from the session it left beside it.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from swreview.agent import runner
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.checks.rms.run import RmsScope, is_check_folder, run_rms_check
from swreview.ir.loader import save_package
from swreview.report.attention import Ranking, rank
from swreview.report.attention_record import (
    ATTENTION_FILE_NAME,
    AttentionRecord,
    StaleAttentionRecord,
    read_attention_record,
    write_attention_record,
)
from swreview.report.rerender import rerender_run_folder
from swreview.report.session import load_session, save_session
from tests.support.attention import CHECK_FOLDER, REVIEW_FOLDER
from tests.unit.test_attention import REVIEW_ORDER, session_of
from tests.unit.test_rerender import standards_run_folder
from tests.unit.test_rms_run import evidence as rms_evidence
from tests.unit.test_runner_provider import RaisingProvider

RECORD_KEYS: tuple[str, ...] = (
    "policy_version",
    "session_id",
    "rows",
    "top_n",
    "not_amplified",
    "coverage",
    "empty_reason",
)
"""`contracts/attention.md` section 4, in the order the contract writes them. Order is
asserted as well as membership: the record is read by a human arguing about a placement,
and `session_id` second is what tells them which run they are reading."""


def copied(source: Path, tmp_path: Path, name: str = "run") -> Path:
    target = tmp_path / name
    shutil.copytree(source, target)
    return target


def body_of(directory: Path) -> dict[str, Any]:
    """`attention.json` as raw JSON, so the file's own shape is what is asserted."""
    return json.loads((directory / ATTENTION_FILE_NAME).read_text(encoding="utf-8"))


def reproduces(directory: Path) -> None:
    """The one rule every writer owes: re-ranking the session beside it rebuilds the file."""
    session = load_session(directory / "session.json")
    expected = AttentionRecord.of(rank(session), session.session_id)

    assert read_attention_record(directory) == expected
    assert body_of(directory) == json.loads(expected.model_dump_json())


@pytest.fixture
def review_dir(tmp_path: Path) -> Path:
    return copied(REVIEW_FOLDER, tmp_path, "20260918-215755-review")


@pytest.fixture
def review_ranking(review_dir: Path) -> Ranking:
    return rank(load_session(review_dir / "session.json"))


@pytest.fixture
def review_session_id(review_dir: Path) -> UUID:
    return load_session(review_dir / "session.json").session_id


# --- 1. the file the writer leaves behind ---------------------------------------------


def test_it_returns_the_path_it_wrote(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    written = write_attention_record(review_dir, review_ranking, review_session_id)

    assert written == review_dir / ATTENTION_FILE_NAME
    assert written.is_file()


def test_the_file_is_indented_by_two_and_ends_in_one_newline(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    """`save_session`'s spelling, so the two files beside each other read the same way and
    a diff of a run folder is a diff of what changed rather than of the formatting."""
    text = write_attention_record(review_dir, review_ranking, review_session_id).read_text(
        encoding="utf-8"
    )

    assert text.endswith("}\n")
    assert not text.endswith("}\n\n")
    assert '\n  "policy_version"' in text
    assert text == json.dumps(json.loads(text), indent=2) + "\n"


def test_the_record_carries_the_seven_keys_of_the_contract_in_order(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    write_attention_record(review_dir, review_ranking, review_session_id)

    assert tuple(body_of(review_dir)) == RECORD_KEYS


def test_the_record_is_the_ranking_plus_the_session_it_was_computed_from(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    write_attention_record(review_dir, review_ranking, review_session_id)

    body = body_of(review_dir)

    assert body["session_id"] == str(review_session_id)
    assert [row["finding_id"] for row in body["rows"]] == list(REVIEW_ORDER)
    ranking_json = json.loads(review_ranking.model_dump_json())
    assert {key: body[key] for key in ranking_json} == ranking_json


def test_writing_the_same_ranking_twice_is_byte_identical(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    """Every turn of the pane re-renders and re-records; a record that differed run to run
    over one session would make `git status` on a run folder meaningless."""
    first = write_attention_record(review_dir, review_ranking, review_session_id).read_bytes()

    assert write_attention_record(review_dir, review_ranking, review_session_id).read_bytes() == (
        first
    )


def test_no_percent_sign_reaches_the_record(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    """Research R2.14: the record's rows are what the two check bodies carry to a page
    whose body scan forbids one."""
    text = write_attention_record(review_dir, review_ranking, review_session_id).read_text(
        encoding="utf-8"
    )

    assert "%" not in text


def test_a_record_of_a_session_with_no_findings_keeps_its_reason(tmp_path: Path) -> None:
    """The empty case is the one a reader is most likely to mis-handle as "no record"."""
    session = session_of("a run that found nothing", [])
    directory = tmp_path / "quiet"
    save_session(session, directory / "session.json")
    ranking = rank(session)

    write_attention_record(directory, ranking, session.session_id)

    assert body_of(directory)["rows"] == []
    assert body_of(directory)["empty_reason"] == ranking.empty_reason
    assert read_attention_record(directory).empty_reason == ranking.empty_reason


# --- 2. reading it back ---------------------------------------------------------------


def test_the_record_round_trips(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    write_attention_record(review_dir, review_ranking, review_session_id)

    record = read_attention_record(review_dir)

    assert record.session_id == review_session_id
    assert record.rows == review_ranking.rows
    assert record.policy_version == review_ranking.policy_version
    assert record.top_n == review_ranking.top_n
    assert record.not_amplified == review_ranking.not_amplified
    assert record.coverage == review_ranking.coverage


def test_re_ranking_the_session_reproduces_the_record_exactly(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    """FR-020. A record that could not be recomputed would be a second source of truth."""
    write_attention_record(review_dir, review_ranking, review_session_id)

    reproduces(review_dir)


def test_a_record_naming_another_session_is_refused_as_stale(
    review_dir: Path, review_ranking: Ranking
) -> None:
    """A review that claims a check folder rotates the check's session aside; a record
    still naming it describes a run this folder no longer holds."""
    other = uuid4()
    write_attention_record(review_dir, review_ranking, other)
    session_id = load_session(review_dir / "session.json").session_id

    with pytest.raises(StaleAttentionRecord) as refusal:
        read_attention_record(review_dir)

    assert str(other) in str(refusal.value)
    assert str(session_id) in str(refusal.value)
    assert ATTENTION_FILE_NAME in str(refusal.value)


def test_a_folder_with_no_record_names_the_file_it_wanted(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(OSError, match=ATTENTION_FILE_NAME):
        read_attention_record(empty)


def test_a_record_that_is_not_json_is_refused_naming_the_path(
    review_dir: Path, review_ranking: Ranking, review_session_id: UUID
) -> None:
    write_attention_record(review_dir, review_ranking, review_session_id)
    (review_dir / ATTENTION_FILE_NAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match=ATTENTION_FILE_NAME):
        read_attention_record(review_dir)


def test_a_record_beside_no_session_is_refused_rather_than_read_as_fresh(
    tmp_path: Path, review_ranking: Ranking
) -> None:
    """Staleness is a comparison, so a folder with nothing to compare against is a refusal
    rather than a record that passes by default."""
    alone = tmp_path / "alone"
    alone.mkdir()
    write_attention_record(alone, review_ranking, uuid4())

    with pytest.raises(OSError, match="session.json"):
        read_attention_record(alone)


# --- 3. the record is not a session file ----------------------------------------------


def test_an_rms_check_folder_holding_the_record_is_still_a_check_folder(
    tmp_path: Path,
) -> None:
    """`is_check_folder` is what `POST /sessions` asks before refusing a folder; a fourth
    file in the folder must not change its answer (FR-021)."""
    check_dir = copied(CHECK_FOLDER, tmp_path, "20260918-220310-check")
    session = load_session(check_dir / "session.json")
    assert is_check_folder(check_dir)

    write_attention_record(check_dir, rank(session), session.session_id)

    assert is_check_folder(check_dir)


# --- 4. the four writers --------------------------------------------------------------


def rms_run_folder(tmp_path: Path) -> Path:
    """A real RMS check folder, written by `run_rms_check` itself."""
    package_dir = tmp_path / "package"
    save_package(rms_evidence(), package_dir)
    run = run_rms_check(package_dir, scope=RmsScope.all, out_dir=tmp_path / "rms")
    return run.session_file.parent


def test_the_rms_check_writes_a_record_beside_its_session(tmp_path: Path) -> None:
    reproduces(rms_run_folder(tmp_path))


def test_the_standards_check_writes_a_record_beside_its_session(tmp_path: Path) -> None:
    reproduces(standards_run_folder(tmp_path))


def test_the_offline_re_render_writes_a_record(review_dir: Path) -> None:
    (review_dir / ATTENTION_FILE_NAME).unlink(missing_ok=True)

    rerender_run_folder(review_dir)

    reproduces(review_dir)


def played(
    tmp_package_dir: Path, out_dir: Path, script: Sequence[ScriptedTurn], **kwargs: Any
) -> runner.ReviewRun:
    run = runner.start_review(
        tmp_package_dir,
        out_dir,
        provider=kwargs.pop("provider", None) or FakeProvider(script=script, model="fake-1"),
        **kwargs,
    )
    try:
        run.start()
    finally:
        run.close()
    return run


def test_a_finished_review_writes_a_record_beside_its_session(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "review"

    played(tmp_package_dir, out_dir, [ScriptedTurn(text="nothing to report", tool_calls=())])

    reproduces(out_dir)


def test_a_review_whose_provider_failed_writes_a_record_too(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """`finalize` runs on the failure path (`_run_turn`), and a half-finished run is
    exactly the one an engineer needs the ranking of."""
    out_dir = tmp_path / "failed"

    with pytest.raises(RuntimeError, match="connection dropped"):
        played(tmp_package_dir, out_dir, [], provider=RaisingProvider())

    reproduces(out_dir)


def test_re_recording_a_finished_folder_leaves_its_session_and_record_untouched(
    tmp_path: Path,
) -> None:
    """Amplify, never write: ranking a session must not edit it, so an offline re-render
    over a folder a check just wrote leaves both files byte for byte what they were."""
    directory = rms_run_folder(tmp_path)
    before = {
        path.name: path.read_bytes() for path in sorted(directory.iterdir()) if path.is_file()
    }

    rerender_run_folder(directory)

    after = {path.name: path.read_bytes() for path in sorted(directory.iterdir()) if path.is_file()}
    assert set(after) == set(before)
    assert after["session.json"] == before["session.json"]
    assert after[ATTENTION_FILE_NAME] == before[ATTENTION_FILE_NAME]
