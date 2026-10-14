"""US4: a waiting review survives a restart (feature 015, `contracts/recheck.md`).

The carried live step (T092): a re-run of a not-sent review's checks carries the first run's
live interference outcome instead of asking SOLIDWORKS again, records one carried step where
the first run recorded its call, and carries the drawing-read capability onto its own record
(FR-028; SC-008; research R2.17). Every package, path and seat here is fictional.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from swreview import atomic
from swreview.agent import runner
from swreview.agent.providers import ProviderName
from swreview.agent.providers.deferred import DeferredProvider
from swreview.agent.settings import ProviderSettings, pane_defaults
from swreview.ir.loader import PACKAGE_FILE_NAME, load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import (
    CARRIED_LIVE_NOTE,
    INTERFERENCE_ROWS_NOT_CARRIED,
    INTERFERENCE_TOOL,
    LIVE_INTERFERENCE_TOOL,
    PRERUN_INTERFERENCE_SETTINGS,
)
from swreview.report.names import plural
from swreview.report.session import ReviewSession, load_session
from tests.support.prerun import LIVE_ROWS, live_prerun_package, prerun_package
from tests.support.questions_package import build_questions_package
from tests.support.review_bridge import VOLUME_UNIT_GAP, ScriptedReviewBridge

INTERFERENCE_CHECKS = frozenset({
    "interference",
    "coverage.prerun.interference",
    "coverage.prerun.interference_rows",
    f"tool.{LIVE_INTERFERENCE_TOOL}",
})


# --- the runner-level first run and re-run ------------------------------------------------


def checks_only(
    folder: Path,
    bridge: Any | None,
    *,
    earlier: ReviewSession | None = None,
    standards_profile: Path | None = None,
) -> runner.ReviewRun:
    """An unticked start in `folder`, as the pane makes one, with or without a seat."""
    provider = DeferredProvider.for_settings(
        ProviderSettings(provider=ProviderName.FAKE, model="fake-1")
    )
    defaults = pane_defaults(provider.name)
    seat: dict[str, Any] = {}
    if bridge is not None:
        seat = {"bridge": True, "bridge_factory": lambda pipe, secret: bridge}
    return runner.start_review(
        folder,
        folder,
        provider=provider,
        efficiency=defaults.efficiency,
        model_view=defaults.model_view,
        standards_profile=standards_profile,
        send_when_checked=False,
        earlier=earlier,
        **seat,
    )


def waited(run: runner.ReviewRun) -> ReviewSession:
    """Finalize the waiting run as `_open_waiting` does and read its record back."""
    try:
        run.close_waiting()
    finally:
        run.close()
    return load_session(run.session_path)


def set_aside(folder: Path) -> None:
    """What the re-run's rotation leaves: the earlier stream and results moved to index 1."""
    (folder / "events.jsonl").rename(folder / "events.1.jsonl")
    results = folder / "tool-results"
    if results.is_dir():
        results.rename(folder / "tool-results.1")
    shutil.copyfile(folder / "session.json", folder / "session.1.json")


def silent_seat() -> ScriptedReviewBridge:
    """A seat with no answers: any call it receives fails the test loudly."""
    return ScriptedReviewBridge()


def live_answer(rows: tuple[dict[str, Any], ...] = LIVE_ROWS) -> dict[str, Any]:
    return {"interferences": [dict(row) for row in rows], "gaps": [dict(VOLUME_UNIT_GAP)]}


def package_folder(tmp_path: Path, package: EvidencePackage) -> Path:
    folder = tmp_path / "run"
    save_package(package, folder)
    return folder


def interference_rows(session: ReviewSession) -> dict[str, list[dict[str, Any]]]:
    coverage = session.coverage.model_dump(mode="json")
    return {
        bucket: [item for item in items if item["check"] in INTERFERENCE_CHECKS]
        for bucket, items in coverage.items()
    }


def step_rows(session: ReviewSession) -> list[tuple[int, str, Any, str]]:
    return [
        (step.index, step.tool, step.arguments, step.status) for step in session.steps
    ]


def finding_rows(session: ReviewSession) -> list[tuple[str, str, list[int]]]:
    return [
        (finding.id, finding.check, list(finding.tool_result_ids)) for finding in session.findings
    ]


def first_and_rerun(
    folder: Path, first_seat: Any | None, rerun_seat: Any | None
) -> tuple[runner.ReviewRun, ReviewSession, runner.ReviewRun, dict[str, Any]]:
    """The first unticked run, finalized; then its re-run, prepared and not finalized.

    The last item is the first run's interference coverage as its pre-run left it, before
    the finalization added its not-sent rows: what the re-run's pre-run is compared with.
    """
    first = checks_only(folder, first_seat)
    rows = interference_rows(first.session)
    earlier = waited(first)
    set_aside(folder)
    rerun = checks_only(folder, rerun_seat, earlier=earlier)
    return first, earlier, rerun, rows


# --- no new bridge call, one carried step ---------------------------------------------------


@pytest.fixture
def carried(tmp_path: Path) -> Any:
    folder = package_folder(tmp_path, live_prerun_package())
    seat = silent_seat()
    first, earlier, rerun, _ = first_and_rerun(
        folder, ScriptedReviewBridge(results={"interference": [live_answer()]}), seat
    )
    yield folder, seat, first, earlier, rerun
    rerun.close()


def test_a_re_run_asks_solidworks_nothing_before_its_first_request(carried: Any) -> None:
    _, seat, _, earlier, rerun = carried

    assert seat.calls == []
    assert earlier.live_detection is not None and earlier.live_detection.step_index == 0
    assert rerun.session.live_detection == earlier.live_detection


def test_the_carried_step_is_recorded_where_the_first_run_recorded_its_call(
    carried: Any,
) -> None:
    folder, _, _, earlier, rerun = carried
    live = earlier.live_detection
    assert live is not None and live.step_index is not None
    step = rerun.session.steps[live.step_index]

    assert step.tool == LIVE_INTERFERENCE_TOOL
    assert step.arguments == {
        "component_ids": [],
        "configuration": live.configuration,
        "settings": PRERUN_INTERFERENCE_SETTINGS,
    }
    assert step.status == "ok"
    assert step.origin_mark == "prerun"
    stored = json.loads(
        (folder / "tool-results" / f"step-{live.step_index}.json").read_text(encoding="utf-8")
    )
    assert stored["payload"] == {
        "status": "carried",
        "note": CARRIED_LIVE_NOTE,
        "outcome": live.model_dump(mode="json"),
    }
    started = [
        json.loads(line)
        for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    tool_events = [
        event["body"] for event in started if event["type"] in {"tool.started", "tool.finished"}
    ]
    assert tool_events[0]["step_index"] == live.step_index
    assert tool_events[0]["tool"] == LIVE_INTERFERENCE_TOOL


def test_every_later_step_and_finding_citation_is_the_first_runs(carried: Any) -> None:
    _, _, _, earlier, rerun = carried

    assert step_rows(rerun.session) == step_rows(earlier)
    assert finding_rows(rerun.session) == finding_rows(earlier)
    assert [s.tool for s in rerun.session.steps].count(INTERFERENCE_TOOL) == 2


def test_a_repeated_live_call_is_answered_naming_the_carried_step(carried: Any) -> None:
    _, seat, _, earlier, rerun = carried
    live = earlier.live_detection
    assert live is not None

    answer = rerun.tools.call(
        LIVE_INTERFERENCE_TOOL,
        {
            "component_ids": [],
            "configuration": live.configuration,
            "settings": dict(PRERUN_INTERFERENCE_SETTINGS),
        },
        "call-FICT-1",
    )

    assert answer.payload["status"] == "already_run"
    assert answer.payload["ran_at_step"] == live.step_index
    assert seat.calls == []


# --- every outcome carried ------------------------------------------------------------------


def _collided_package() -> EvidencePackage:
    other = prerun_package().interferences[0].model_copy(
        update={"id": "int:0002", "configuration": "Other"}
    )
    return live_prerun_package().model_copy(update={"interferences": [other]})


def _part_root_package() -> EvidencePackage:
    package = live_prerun_package()
    root = package.design.root_assembly_document_id
    return package.model_copy(
        update={
            "documents": [
                d.model_copy(update={"kind": "part"}) if d.document_id == root else d
                for d in package.documents
            ]
        }
    )


OUTCOMES: dict[str, tuple[Any, Any]] = {
    "clean": (live_prerun_package, lambda: {"interference": [live_answer(rows=())]}),
    "rows": (live_prerun_package, lambda: {"interference": [live_answer()]}),
    "collided": (_collided_package, lambda: {"interference": [live_answer()]}),
    "failed": (prerun_package, lambda: {"interference": [_bridge_error()]}),
    "no-bridge": (prerun_package, None),
    "not-an-assembly": (_part_root_package, lambda: {}),
}


def _bridge_error() -> Exception:
    from swreview.bridge.client import BridgeError

    return BridgeError("FICT the host lost the document")


@pytest.mark.parametrize("case", sorted(OUTCOMES))
def test_every_live_outcome_is_carried_as_the_first_run_had_it(
    tmp_path: Path, case: str
) -> None:
    make_package, script = OUTCOMES[case]
    folder = package_folder(tmp_path, make_package())
    first_seat = ScriptedReviewBridge(results=script()) if script is not None else None
    rerun_seat = silent_seat() if script is not None else None

    first, earlier, rerun, first_rows = first_and_rerun(folder, first_seat, rerun_seat)
    try:
        assert rerun.opening_message == first.opening_message
        assert interference_rows(rerun.session) == first_rows
        assert rerun._prerun is not None and first._prerun is not None
        assert rerun._prerun.withheld == first._prerun.withheld
        assert step_rows(rerun.session) == step_rows(earlier)
        assert finding_rows(rerun.session) == finding_rows(earlier)
        if rerun_seat is not None:
            assert rerun_seat.calls == []
        live = earlier.live_detection
        assert live is not None
        if case in {"no-bridge", "not-an-assembly"}:
            assert live.step_index is None
            assert LIVE_INTERFERENCE_TOOL not in [s.tool for s in rerun.session.steps]
        if case == "failed":
            assert live.error is not None
            [failed] = [
                item for item in rerun.session.coverage.failed
                if item.check == f"tool.{LIVE_INTERFERENCE_TOOL}"
            ]
            assert failed.error == live.error
            assert rerun.session.steps[live.step_index].status == "error"
            assert [
                s.arguments["group_key"]
                for s in rerun.session.steps if s.tool == INTERFERENCE_TOOL
            ] == [prerun_package().interferences[0].group_key]
    finally:
        rerun.close()


# --- rows the first run could not write -----------------------------------------------------


def test_rows_the_first_run_could_not_write_are_not_judged_from_the_stale_dump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = package_folder(tmp_path, prerun_package())
    stale = {row.id for row in prerun_package().interferences}
    real_replace = atomic.os.replace

    def refuse(source: Any, target: Any) -> None:
        if Path(target).name == PACKAGE_FILE_NAME:
            raise PermissionError("FICT package.json is locked")
        real_replace(source, target)

    monkeypatch.setattr(atomic.os, "replace", refuse)
    first = checks_only(folder, ScriptedReviewBridge(results={"interference": [live_answer()]}))
    earlier = waited(first)
    monkeypatch.setattr(atomic.os, "replace", real_replace)
    assert earlier.live_detection is not None
    assert earlier.live_detection.persist_error is not None
    assert {row.id for row in load_package(folder).package.interferences} == stale
    set_aside(folder)

    rerun = checks_only(folder, silent_seat(), earlier=earlier)
    try:
        assert not [s for s in rerun.session.steps if s.tool == INTERFERENCE_TOOL]
        assert not [f for f in rerun.session.findings if f.check == "interference.static"]
        assert not rerun.context.ir.interferences
        [row] = [
            item for item in rerun.session.coverage.unresolved
            if item.check == "coverage.prerun.interference_rows"
        ]
        assert row.reason == INTERFERENCE_ROWS_NOT_CARRIED.format(
            rows=plural(earlier.live_detection.rows_added, "row")
        )
        assert f"  interference: {row.reason}" in rerun.opening_message.splitlines()
        assert "could not be written" not in rerun.opening_message
    finally:
        rerun.close()


# --- the drawing-read capability ------------------------------------------------------------


def test_the_drawing_read_capability_is_carried_onto_the_re_runs_record(
    tmp_path: Path,
) -> None:
    fixture = build_questions_package(tmp_path / "run")
    first = checks_only(fixture.folder, fixture.bridge, standards_profile=fixture.profile)
    earlier = waited(first)
    assert earlier.drawing_read == "opens_closed"
    assert ("ping", {}) in fixture.bridge.calls
    set_aside(fixture.folder)

    seat = silent_seat()
    rerun = checks_only(fixture.folder, seat, earlier=earlier, standards_profile=fixture.profile)
    assert seat.calls == []
    assert rerun.session.drawing_read == "opens_closed"
    assert rerun.context.drawing_read_mode() == "opens_closed"
    assert seat.calls == []
    assert [q.question for q in rerun.session.evidence_requests] == [
        q.question for q in earlier.evidence_requests
    ]
    second_earlier = waited(rerun)
    assert second_earlier.drawing_read == "opens_closed"
    for name in ("events.1.jsonl", "session.1.json"):
        (fixture.folder / name).rename(fixture.folder / name.replace(".1.", ".2."))
    shutil.rmtree(fixture.folder / "tool-results.1")
    set_aside(fixture.folder)

    again = silent_seat()
    second = checks_only(
        fixture.folder, again, earlier=second_earlier, standards_profile=fixture.profile
    )
    try:
        assert again.calls == []
        assert second.session.drawing_read == "opens_closed"
    finally:
        second.close()
