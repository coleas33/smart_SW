"""The one offline re-render of a run folder (T005, research R2.7).

`swreview timing`, `swreview disposition` and `swreview exceptions accept-*` all re-render
a folder they did not run. Today each of them calls `render_report(session)` with no
package and no verdict header, which turns component names back into ids, degrades
Manifest Discrepancies to the "not supplied" placeholder, and deletes a standards folder's
verdict header outright. `rerender_run_folder` is the one function that reads the folder
for everything the renderer needs, so none of the three can lose any of it.

It writes `report.md` and `attention.json` (T028), both from one `Ranking`, so the section
the report opens its findings with and the record beside the session cannot disagree.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.checks.standards.run import CHECK_FILE_NAME, run_standards_check
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.report.attention import rank
from swreview.report.attention_record import ATTENTION_FILE_NAME, read_attention_record
from swreview.report.markdown import render_report
from swreview.report.rerender import render_folder_report, rerender_run_folder
from swreview.report.session import load_session
from tests.support.standards import (
    AssemblySpec,
    ComponentSpec,
    PartSpec,
    standards_package,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attention"
REVIEW_FOLDER = FIXTURES / "review-folder"
CHECK_FOLDER = FIXTURES / "check-folder"

STANDARDS_PROFILE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "profile-a.yaml"
)

PLACEHOLDER = "_The evidence package was not supplied to the renderer._"
REPORT_TITLE = "# Design Review Report"
NAMED_COMPONENT = "cmp:0003 (cover-assy-1/housing-1)"


def copied(source: Path, tmp_path: Path, name: str = "run") -> Path:
    """`source` under `tmp_path`, so a test may write into it."""
    target = tmp_path / name
    shutil.copytree(source, target)
    return target


def files_in(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def standards_run_folder(tmp_path: Path) -> Path:
    """A real standards check folder, written by `run_standards_check` itself."""
    from swreview.checks.standards.profile import load_profile

    package = standards_package(
        documents=[
            AssemblySpec(
                name="top",
                folder="jobs/mr-400",
                is_exploded=True,
                components=[ComponentSpec(name="plate-1", document="plate")],
            ),
            PartSpec(name="plate", folder="jobs/mr-400"),
        ],
        profile=load_profile(STANDARDS_PROFILE),
    )
    package_dir = tmp_path / "package"
    save_package(package, package_dir)
    run = run_standards_check(package_dir, STANDARDS_PROFILE, tmp_path / "standards-run")
    return run.report_file.parent


def standards_folder_holding_its_package(tmp_path: Path) -> Path:
    """`standards_run_folder` with the package beside the session, as a pane check's folder is."""
    run_dir = standards_run_folder(tmp_path)
    shutil.copy(tmp_path / "package" / PACKAGE_FILE_NAME, run_dir / PACKAGE_FILE_NAME)
    return run_dir


def claim_with_a_review(run_dir: Path) -> None:
    """Claim `run_dir` with a review, as the pane's backend does, and play the review in it.

    The claim is `chat/server.py`'s `_rotate_previous`: the folder's `session.json` and
    `attention.json` move aside to index 1, and `check.json` stays, still naming the check's
    session. The review is played in the folder with the scripted provider, and its report is
    written by `ReviewRun.write_views`, which the pane calls after every turn: `report.md` is
    then the review's report as it was first written.
    """
    for name in ("session.json", ATTENTION_FILE_NAME):
        current = run_dir / name
        current.rename(current.with_name(f"{current.stem}.1{current.suffix}"))
    run = start_review(
        run_dir,
        run_dir,
        provider=FakeProvider(
            script=[ScriptedTurn(text="nothing to report", tool_calls=())], model="fake-1"
        ),
    )
    try:
        run.start()
        run.write_views(save=False, best_effort=False)
    finally:
        run.close()


# --- 1. a review folder ----------------------------------------------------------------


def test_it_returns_the_report_path_it_wrote(tmp_path: Path) -> None:
    run_dir = copied(REVIEW_FOLDER, tmp_path)

    report_file = rerender_run_folder(run_dir)

    assert report_file == run_dir / "report.md"
    assert report_file.is_file()


def test_a_review_folder_with_a_package_renders_its_component_names(tmp_path: Path) -> None:
    """The defect this function removes: a re-render that drops the package (research R2.7)."""
    run_dir = copied(REVIEW_FOLDER, tmp_path)

    report = rerender_run_folder(run_dir).read_text(encoding="utf-8")

    assert NAMED_COMPONENT in report
    assert PLACEHOLDER not in report
    assert "No discrepancies between the manifest and the reviewed documents." in report
    session = load_session(run_dir / "session.json")
    assert report == render_report(session, load_package(run_dir).package, ranking=rank(session))


def test_a_review_folder_without_a_package_renders_the_placeholder(tmp_path: Path) -> None:
    """What `swreview report <session.json>` also renders for a folder holding no package."""
    run_dir = copied(REVIEW_FOLDER, tmp_path)
    (run_dir / PACKAGE_FILE_NAME).unlink()

    report = rerender_run_folder(run_dir).read_text(encoding="utf-8")

    assert PLACEHOLDER in report
    assert NAMED_COMPONENT not in report
    session = load_session(run_dir / "session.json")
    assert report == render_report(session, ranking=rank(session))


def test_it_writes_the_report_and_the_record_and_nothing_else(tmp_path: Path) -> None:
    """Two files, and not one byte of the session, the package or the check record."""
    run_dir = copied(REVIEW_FOLDER, tmp_path)
    before = files_in(run_dir)

    rerender_run_folder(run_dir)

    after = files_in(run_dir)
    written = {"report.md", ATTENTION_FILE_NAME}
    assert set(after) - set(before) == written
    assert {name: body for name, body in after.items() if name not in written} == before


def test_the_folder_report_is_what_the_re_render_writes_and_it_writes_nothing(
    tmp_path: Path,
) -> None:
    """`render_folder_report` is the reading-and-rendering half `swreview report` calls: the
    same text and ranking the re-render writes, and not one byte written to the folder."""
    run_dir = copied(REVIEW_FOLDER, tmp_path)
    twin = copied(REVIEW_FOLDER, tmp_path, "twin")
    session = load_session(run_dir / "session.json")
    before = files_in(run_dir)

    report, ranking = render_folder_report(run_dir, session)

    assert files_in(run_dir) == before
    assert report == rerender_run_folder(twin).read_text(encoding="utf-8")
    assert ranking == rank(session)
    assert read_attention_record(twin).rows == ranking.rows


def test_the_folder_report_takes_the_caller_s_package_over_the_folder_s(tmp_path: Path) -> None:
    """The one caller holding a package (`cli._save_run`) is not overridden by the folder."""
    run_dir = copied(REVIEW_FOLDER, tmp_path)
    (run_dir / PACKAGE_FILE_NAME).unlink()
    package = load_package(REVIEW_FOLDER).package
    session = load_session(run_dir / "session.json")

    report, _ = render_folder_report(run_dir, session, package=package)

    assert NAMED_COMPONENT in report
    assert report == render_report(session, package, ranking=rank(session))


def test_the_record_it_writes_is_the_ranking_the_report_was_rendered_from(
    tmp_path: Path,
) -> None:
    """One `rank` call serves both writes; a record that named a different order from the
    section above `## Findings` is the defect a second call would eventually cause."""
    run_dir = copied(REVIEW_FOLDER, tmp_path)

    report = rerender_run_folder(run_dir).read_text(encoding="utf-8")

    session = load_session(run_dir / "session.json")
    record = read_attention_record(run_dir)
    assert record.session_id == session.session_id
    assert record.rows == rank(session).rows
    for row in record.rows[: record.top_n]:
        assert row.finding_id in report.split("## Findings\n")[0]


# --- 2. a check folder ------------------------------------------------------------------


def test_an_rms_check_folder_gets_no_verdict_header(tmp_path: Path) -> None:
    """`check.json` names the `rms` family, which writes no header of its own, and names the
    folder's session, so the body renders as a check's: no model ran (132A)."""
    run_dir = copied(CHECK_FOLDER, tmp_path)

    report = rerender_run_folder(run_dir).read_text(encoding="utf-8")

    assert report.startswith(REPORT_TITLE)
    session = load_session(run_dir / "session.json")
    assert report == render_report(
        session, load_package(run_dir).package, ranking=rank(session), check_run=True
    )


def test_a_standards_folder_keeps_its_verdict_header_byte_for_byte(tmp_path: Path) -> None:
    """The header `run_standards_check` prepended is rebuilt from `check.json`'s verdict."""
    run_dir = standards_run_folder(tmp_path)
    written = (run_dir / "report.md").read_text(encoding="utf-8")
    assert REPORT_TITLE in written

    report = rerender_run_folder(run_dir).read_text(encoding="utf-8")

    assert report.split(REPORT_TITLE)[0] == written.split(REPORT_TITLE)[0]
    assert "not_ready" in report.split(REPORT_TITLE)[0]


def test_a_standards_folder_holding_its_package_re_renders_byte_for_byte(
    tmp_path: Path,
) -> None:
    """Header and body: with the package beside it, nothing about the file changes."""
    run_dir = standards_folder_holding_its_package(tmp_path)
    written = (run_dir / "report.md").read_text(encoding="utf-8")

    assert rerender_run_folder(run_dir).read_text(encoding="utf-8") == written


def test_a_review_that_claimed_a_standards_folder_re_renders_as_it_was_first_written(
    tmp_path: Path,
) -> None:
    """No verdict header, because the review's report was written without one (139A).

    `ReviewRun.write_views` renders a review's report with no header, and `check.json` still
    names the check's session, now `session.1.json`: the header is that session's alone, as
    the check's model line is (132A).
    """
    run_dir = standards_folder_holding_its_package(tmp_path)
    claim_with_a_review(run_dir)
    written = (run_dir / "report.md").read_text(encoding="utf-8")
    assert written.startswith(REPORT_TITLE)

    report = rerender_run_folder(run_dir).read_text(encoding="utf-8")

    assert report == written


def test_the_check_s_session_a_review_rotated_aside_keeps_its_verdict_header_byte_for_byte(
    tmp_path: Path,
) -> None:
    """`swreview report session.1.json`: `check.json` still names that session, so it renders
    as the check wrote it, header and body."""
    run_dir = standards_folder_holding_its_package(tmp_path)
    written = (run_dir / "report.md").read_text(encoding="utf-8")
    claim_with_a_review(run_dir)

    report, _ = render_folder_report(run_dir, load_session(run_dir / "session.1.json"))

    assert report == written


def test_an_unreadable_verdict_refuses_only_the_session_whose_header_it_rebuilds(
    tmp_path: Path,
) -> None:
    """The check's session is refused, as before; the review's re-renders, because its report
    never carried the header the verdict would have rebuilt (139A)."""
    run_dir = standards_folder_holding_its_package(tmp_path)
    claim_with_a_review(run_dir)
    written = (run_dir / "report.md").read_text(encoding="utf-8")
    check_file = run_dir / CHECK_FILE_NAME
    record = json.loads(check_file.read_text(encoding="utf-8"))
    del record["verdict"]
    check_file.write_text(json.dumps(record), encoding="utf-8")

    assert rerender_run_folder(run_dir).read_text(encoding="utf-8") == written
    with pytest.raises(ValueError, match=re.escape(str(check_file))):
        render_folder_report(run_dir, load_session(run_dir / "session.1.json"))


def test_a_check_record_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    """Rendering on over an unreadable record is how a verdict header goes missing."""
    run_dir = copied(CHECK_FOLDER, tmp_path)
    (run_dir / CHECK_FILE_NAME).write_text("{not json", encoding="utf-8")
    before = files_in(run_dir)

    with pytest.raises(ValueError, match=re.escape(str(run_dir / CHECK_FILE_NAME))):
        rerender_run_folder(run_dir)

    assert files_in(run_dir) == before


# --- 3. the two refusals ----------------------------------------------------------------


def test_a_folder_with_no_session_names_the_path_and_writes_nothing(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty"
    run_dir.mkdir()

    with pytest.raises(OSError, match=re.escape(str(run_dir / "session.json"))):
        rerender_run_folder(run_dir)

    assert list(run_dir.iterdir()) == []


def test_a_benchmark_run_root_names_the_command_for_it(tmp_path: Path) -> None:
    """`<run_root>/<package_id>/session.json` is `benchmark time`'s shape, not this one."""
    run_root = tmp_path / "20260918-benchmark"
    (run_root / "pkg-1").mkdir(parents=True)
    shutil.copy(REVIEW_FOLDER / "session.json", run_root / "pkg-1" / "session.json")
    before = files_in(run_root / "pkg-1")

    with pytest.raises(ValueError, match="swreview benchmark time"):
        rerender_run_folder(run_root)

    assert list(run_root.iterdir()) == [run_root / "pkg-1"]
    assert files_in(run_root / "pkg-1") == before


def test_the_benchmark_root_refusal_also_names_the_folder(tmp_path: Path) -> None:
    run_root = tmp_path / "20260918-benchmark"
    (run_root / "pkg-1").mkdir(parents=True)
    (run_root / "pkg-1" / "session.json").write_text(
        json.dumps({"not": "a session"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match=re.escape(str(run_root))):
        rerender_run_folder(run_root)
