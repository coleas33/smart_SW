"""The model view changes what the model reads and nothing the review records (008 T072).

SC-007 and FR-015, end to end through `start_review`: the same scripted review played with
`MODEL_VIEW_OFF` and with `MODEL_VIEW_PANE` records the same findings, coverage, evidence
requests and step summaries, and writes the same `session.json` (apart from `model_view`
itself and what differs between any two runs - ids and clocks), `package.json`, `report.md`
and `attention.json`. The view is computed beside the payload, after the findings were
recorded, so it cannot reach any of them. `start_review` also tells a `ModelViewAware`
adapter the settings exactly once.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import run_review, start_review
from swreview.agent.settings import MODEL_VIEW_OFF, MODEL_VIEW_PANE, ModelViewSettings
from swreview.ir.loader import save_package
from swreview.report.attention import rank
from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession
from tests.support.prerun import CHECKS_FIRST, prerun_package


class ViewAwareFake(FakeProvider):
    """The scripted provider, recording what `use_model_view` was told."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.told: list[ModelViewSettings] = []

    def use_model_view(self, settings: ModelViewSettings) -> None:
        self.told.append(settings)


SCRIPT = ScriptedTurn(
    text="done",
    tool_calls=(
        ScriptedToolCall("get_package_summary"),
        ScriptedToolCall("list_components", {"parent_id": None, "include_suppressed": True}),
        ScriptedToolCall("list_gaps"),
        ScriptedToolCall("check_hole_alignment", {"hole_id_a": "hole:1", "hole_id_b": "hole:2"}),
        ScriptedToolCall(
            "request_evidence",
            {"what": "the drawing tolerance", "why": "hole.coaxiality", "entity_ids": ["hole:1"]},
        ),
        ScriptedToolCall("check_rms_part"),
    ),
)


def reviewed(tmp_path: Path, name: str, settings: ModelViewSettings | None) -> Path:
    folder = tmp_path / name
    save_package(prerun_package(), folder)
    options: dict[str, Any] = {} if settings is None else {"model_view": settings}
    session = run_review(
        folder,
        folder,
        provider=FakeProvider(script=[SCRIPT], model="fake-scripted", clock=lambda: 0.0),
        efficiency=CHECKS_FIRST,
        **options,
    )
    (folder / "report.md").write_text(render_report(session, ranking=rank(session)), "utf-8")
    return folder


def test_start_review_tells_a_view_aware_adapter_exactly_once(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    save_package(prerun_package(), folder)
    provider = ViewAwareFake(script=[ScriptedTurn(text="done")], model="fake")

    run = start_review(folder, folder, provider=provider, model_view=MODEL_VIEW_PANE)
    run.start()

    assert provider.told == [MODEL_VIEW_PANE]
    assert run.session.model_view == MODEL_VIEW_PANE


def test_start_review_tells_it_off_when_no_view_was_given(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    save_package(prerun_package(), folder)
    provider = ViewAwareFake(script=[ScriptedTurn(text="done")], model="fake")

    start_review(folder, folder, provider=provider)

    assert provider.told == [MODEL_VIEW_OFF]


VOLATILE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+00:00|Z)?"
    r"|\"(elapsed_s|unattended_runtime_minutes|latency_s)\": [0-9.e-]+"
    r"|- (Unattended runtime minutes|Started|Ended): .*"
    r"|\| (ok|error) \| [0-9.e-]+ \|$",
    re.MULTILINE,
)


def normalized(text: str) -> str:
    """Ids, clocks and wall times replaced: what differs between any two runs."""
    return VOLATILE.sub("<volatile>", text)


def without_model_view(folder: Path) -> str:
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    session.pop("model_view")
    return normalized(json.dumps(session, indent=2))


@pytest.fixture(scope="module")
def pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("views")
    return reviewed(root, "off", MODEL_VIEW_OFF), reviewed(root, "pane", MODEL_VIEW_PANE)


def load(folder: Path) -> ReviewSession:
    return ReviewSession.model_validate_json((folder / "session.json").read_bytes())


def test_the_session_records_what_ran(pair: tuple[Path, Path]) -> None:
    off, pane = pair

    assert load(off).model_view == MODEL_VIEW_OFF
    assert load(pane).model_view == MODEL_VIEW_PANE


def test_findings_coverage_requests_and_summaries_are_identical(pair: tuple[Path, Path]) -> None:
    off, pane = (load(folder) for folder in pair)

    assert [f.model_dump(mode="json") for f in off.findings] == [
        f.model_dump(mode="json") for f in pane.findings
    ]
    assert off.coverage == pane.coverage
    assert [(r.id, r.what, r.why, r.entity_ids) for r in off.evidence_requests] == [
        (r.id, r.what, r.why, r.entity_ids) for r in pane.evidence_requests
    ]
    assert [(s.tool, s.arguments, s.result_summary, s.status) for s in off.steps] == [
        (s.tool, s.arguments, s.result_summary, s.status) for s in pane.steps
    ]
    assert off.findings, "the review recorded findings to compare"


def test_the_written_files_are_byte_identical_apart_from_the_view(pair: tuple[Path, Path]) -> None:
    off, pane = pair

    assert without_model_view(off) == without_model_view(pane)
    for name in ("package.json", "report.md", "attention.json"):
        assert normalized((off / name).read_text(encoding="utf-8")) == normalized(
            (pane / name).read_text(encoding="utf-8")
        ), name
