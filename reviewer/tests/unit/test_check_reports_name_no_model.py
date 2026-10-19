"""A report from a run with no model names no model (owner decision 132A).

A Model check, a Standards check and the re-modeler's grades run code and construct no
provider (003 FR-024, 006 FR-043), yet every `report.md` they wrote said "- Model: gpt-5.6":
`new_session` stamps the default model id on every session, because the field is required,
and the report header printed it as the model that ran. The header of a check's own session
now says what a review that was never sent says (feature 015), and names no provider: 015
`contracts/records.md` section 4, amended for 132A.

Every path that writes one is driven here:

- `swreview check standards` and `swreview check rms`, whose functions, `run_standards_check`
  and `run_rms_check`, are also what the pane's `POST /checks/standards` and `POST /checks/rms`
  run on a check folder that is its own package, and what the re-modeler's grades run;
- the offline re-render of a check folder (`report/rerender.py`), which `swreview report`,
  `timing`, `disposition` and `exceptions accept-*` share.

A review's report still names its model, including a review that claimed a check's folder: a
folder holds a check's session only while its `check.json` names that session.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from swreview.agent.providers import EffortMapping
from swreview.checks.rms.run import run_rms_check
from swreview.checks.standards.run import run_standards_check
from swreview.ir.loader import save_package
from swreview.report.markdown import render_report
from swreview.report.rerender import rerender_run_folder
from swreview.report.session import ProviderInfo, ReviewSession, load_session
from tests.support.attention import CHECK_FOLDER, REVIEW_FOLDER
from tests.unit.test_cli import invoke
from tests.unit.test_cli_check_standards import PROFILE_PATH, exploded_package
from tests.unit.test_rms_run import evidence as rms_evidence
from tests.unit.test_session import build_session

NO_MODEL = "- Model: not sent to the model (checked by code only)"
"""Feature 015's line for a review that was not sent to the model (`records.md` section 4)."""

TITLE = "# Design Review Report: "


def title_block(report: str) -> list[str]:
    """The report's title block: its title line down to the line before its first section.

    Found by its title rather than by being first, because a standards report opens with the
    verdict header.
    """
    return report[report.index(TITLE) :].split("\n\n## ", 1)[0].splitlines()


def stamp(value: datetime | None) -> str:
    assert value is not None, "a check's session is closed before its report is written"
    return value.isoformat()


def check_title_block(session: ReviewSession) -> list[str]:
    """A check's title block: the session, feature 015's line, the times; no provider."""
    return [
        f"{TITLE}{session.design_id}",
        "",
        f"- Session: {session.session_id}",
        NO_MODEL,
        f"- Started: {stamp(session.started_at)}",
        f"- Ended: {stamp(session.ended_at)}",
    ]


def report_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def claimed_check_folder(tmp_path: Path) -> Path:
    """A check folder a review claimed: the check's session rotated aside to `session.2.json`,
    as `chat/server.py` rotates it, and the review's `session.json` in its place."""
    folder = tmp_path / "20260918-220310-check"
    shutil.copytree(CHECK_FOLDER, folder)
    (folder / "session.json").rename(folder / "session.2.json")
    shutil.copy(REVIEW_FOLDER / "session.json", folder / "session.json")
    return folder


# --- 1. the header ------------------------------------------------------------------------


def test_a_check_s_own_session_names_no_model_and_no_provider() -> None:
    """No provider line even for a session that carries one, as the committed check-folder
    fixture's does: no report of a check names a model or a provider as having run."""
    info = ProviderInfo(
        provider="openai",
        model="FICT-model",
        effort_mapping=EffortMapping(
            requested="high", provider_param="reasoning.effort", provider_value="high"
        ),
        key_source="none",
    )
    session = build_session(model="FICT-model", provider_info=info)

    report = render_report(session, check_run=True)

    assert title_block(report) == check_title_block(session)


# --- 2. the runs that write a check's report -----------------------------------------------


def test_check_standards_writes_a_report_that_names_no_model(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    save_package(exploded_package(), package_dir)
    out = tmp_path / "runs" / "20261019-101500-standards"

    result = invoke(
        "check", "standards",
        "--package", str(package_dir), "--out", str(out), "--profile", str(PROFILE_PATH),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    session = load_session(out / "session.json")
    assert title_block(report_of(out / "report.md")) == check_title_block(session)


def test_check_rms_writes_a_report_that_names_no_model(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    save_package(rms_evidence(), package_dir)
    out = tmp_path / "runs" / "20261019-101500-check"

    result = invoke("check", "rms", "--package", str(package_dir), "--out", str(out))

    assert result.exit_code == 0, result.stdout + result.stderr
    session = load_session(out / "session.json")
    assert title_block(report_of(out / "report.md")) == check_title_block(session)


def test_the_model_check_tab_s_run_writes_a_report_that_names_no_model(tmp_path: Path) -> None:
    """What `POST /checks/rms` runs: the check folder is its own package and run folder."""
    folder = tmp_path / "runs" / "20261019-101500-check"
    save_package(rms_evidence(), folder)

    run = run_rms_check(folder)

    assert title_block(report_of(run.report_file)) == check_title_block(run.session)


def test_the_standards_tab_s_run_writes_a_report_that_names_no_model(tmp_path: Path) -> None:
    """What `POST /checks/standards` runs, with the same folder as package and run folder."""
    folder = tmp_path / "runs" / "20261019-101500-standards"
    save_package(exploded_package(), folder)

    run = run_standards_check(folder, PROFILE_PATH, folder)

    assert title_block(report_of(run.report_file)) == check_title_block(run.session)


# --- 3. the offline re-render ------------------------------------------------------------


def test_an_rms_check_folder_re_rendered_offline_still_names_no_model(tmp_path: Path) -> None:
    """`swreview timing`, `disposition` and `exceptions accept-*` re-render through
    `rerender_run_folder`, and the committed folder's session carries a provider."""
    folder = tmp_path / "20260918-220310-check"
    shutil.copytree(CHECK_FOLDER, folder)

    report = report_of(rerender_run_folder(folder))

    assert title_block(report) == check_title_block(load_session(folder / "session.json"))


def test_a_standards_folder_re_rendered_offline_still_names_no_model(tmp_path: Path) -> None:
    folder = tmp_path / "runs" / "20261019-101500-standards"
    save_package(exploded_package(), folder)
    run_standards_check(folder, PROFILE_PATH, folder)

    report = report_of(rerender_run_folder(folder))

    assert title_block(report) == check_title_block(load_session(folder / "session.json"))


def test_a_check_session_a_review_rotated_aside_still_renders_as_the_check_s(
    tmp_path: Path,
) -> None:
    """`swreview report` on the rotated `session.2.json`: `check.json` still names it."""
    folder = claimed_check_folder(tmp_path)
    out = tmp_path / "check-report.md"

    result = invoke("report", str(folder / "session.2.json"), "--out", str(out))

    assert result.exit_code == 0, result.stdout + result.stderr
    check = load_session(folder / "session.2.json")
    assert title_block(report_of(out)) == check_title_block(check)


def test_a_review_that_claimed_a_check_folder_still_names_its_model(tmp_path: Path) -> None:
    """The folder's `check.json` names another session, so this one is the review's own."""
    folder = claimed_check_folder(tmp_path)
    review = load_session(folder / "session.json")
    assert review.provider_info is not None

    block = title_block(report_of(rerender_run_folder(folder)))

    assert f"- Model: {review.model}" in block
    assert any(line.startswith("- Provider: ") for line in block)
    assert NO_MODEL not in block
