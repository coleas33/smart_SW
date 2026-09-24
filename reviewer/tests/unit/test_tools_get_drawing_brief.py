"""The brief as a tool and as a command, one answer for one set of inputs (feature 011 T052).

`contracts/brief.md` section 1: `get_drawing_brief(document_id)` - in the drawing family, so
offered only with drawing evidence - builds the brief with the context's session and the
attached standards run's profile, and never loads a profile; its refusals are error results
naming the documents that can be briefed. `swreview drawing brief --package DIR --document ID
[--run RUN_DIR] [--profile PATH]` prints the same JSON for the same inputs, and exits 2 on a
refusal.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from swreview.checks.standards import profile as profile_module
from swreview.checks.standards.profile import load_profile
from swreview.checks.standards.traversal import graded_documents
from swreview.cli import app
from swreview.drawings.brief import build_brief
from swreview.ir.loader import load_package
from swreview.report.session import load_session, save_session
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.drawings import get_drawing_brief
from swreview.tools.registry import ToolRegistry, drawing_tools
from swreview.tools.session import request_evidence
from swreview.tools.standards_checks import StandardsRun, attach_standards_run

TESTS = Path(__file__).resolve().parents[1]
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"


def reviewed(with_profile: bool = True) -> ToolContext:
    """A review context over plate-drawing: one answered question about the plate, and a
    standards run over profile A when asked for."""
    context = context_for(load_package(PLATE_DRAWING).package)
    with use_context(context):
        request_evidence("the plate's finish", "sets the fit", ["doc:0002"],
                         question="Which finish does the plate take?", options=["A", "B"])
    request = context.require_session().evidence_requests[0]
    request.status, request.answer = "answered", "A"
    if with_profile:
        profile = load_profile(PROFILE_A)
        attach_standards_run(
            context,
            StandardsRun(profile=profile, documents=graded_documents(context.ir, profile)),
        )
    return context


def test_the_tool_is_in_the_drawing_family_and_takes_one_document_id() -> None:
    assert get_drawing_brief in drawing_tools()
    assert list(inspect.signature(get_drawing_brief).parameters) == ["document_id"]


def test_through_the_dispatch_it_returns_the_brief_of_the_contexts_session_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = reviewed()
    expected = build_brief(
        context.ir, context.session, load_profile(PROFILE_A), "doc:0002"
    ).content

    def no_loading(*_: object, **__: object) -> None:
        raise AssertionError("the tool reads the attached profile and never loads one")

    monkeypatch.setattr(profile_module, "load_profile", no_loading)
    result = ToolRegistry().dispatch(context).call("get_drawing_brief", {"document_id": "doc:0002"})

    assert result.is_error is False
    assert result.payload == expected
    assert result.payload["answers"][0]["answer"] == "A"
    assert result.payload["conformance"]["profile"].startswith("sha256 ")


def test_without_a_standards_run_the_brief_has_no_profile() -> None:
    context = reviewed(with_profile=False)

    result = ToolRegistry().dispatch(context).call("get_drawing_brief", {"document_id": "doc:0002"})

    assert result.payload["conformance"]["profile"] is None
    assert result.payload["document"]["description"] is None


@pytest.mark.parametrize(
    ("document", "start"),
    [
        ("doc:9999", "document doc:9999 is not in this package; the documents that can be "
                     "briefed are: doc:0001"),
        ("doc:0006", "doc:0006 is a drawing; a brief is of a part or assembly."),
    ],
)
def test_a_refusal_is_an_error_result_naming_the_documents(document: str, start: str) -> None:
    context = reviewed()

    result = ToolRegistry().dispatch(context).call("get_drawing_brief", {"document_id": document})

    assert result.is_error is True
    assert result.payload["error"].startswith(start)


# --- the command ---------------------------------------------------------------------------------


def test_the_command_prints_the_same_json_for_the_same_inputs(tmp_path: Path) -> None:
    context = reviewed()
    run = tmp_path / "run"
    run.mkdir()
    session = context.require_session()
    save_session(session, run / "session.json")
    tool = ToolRegistry().dispatch(context).call("get_drawing_brief", {"document_id": "doc:0002"})

    result = CliRunner().invoke(
        app,
        [
            "drawing", "brief", "--package", str(PLATE_DRAWING), "--document", "doc:0002",
            "--run", str(run), "--profile", str(PROFILE_A),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == tool.payload
    assert result.stdout.strip() == build_brief(
        context.ir, load_session(run / "session.json"), load_profile(PROFILE_A), "doc:0002"
    ).to_json()


def test_the_command_writes_the_briefs_utf8_bytes_whatever_the_consoles_encoding() -> None:
    """A Windows console or redirect in cp1252 cannot spell the diameter sign every hole callout
    carries; the command writes the brief's own UTF-8 bytes, the ones its 6,000-byte bound counts,
    rather than failing with a `UnicodeEncodeError` (found running quickstart Scenario 9, T059)."""
    package = load_package(PLATE_DRAWING).package
    expected = build_brief(package, None, load_profile(PROFILE_A), "doc:0002").to_json()
    assert "⌀" in expected, "the plate's brief names a diameter"

    result = CliRunner(charset="cp1252").invoke(
        app,
        ["drawing", "brief", "--package", str(PLATE_DRAWING), "--document", "doc:0002",
         "--profile", str(PROFILE_A)],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == expected.encode("utf-8") + b"\n"


def test_the_command_needs_neither_a_run_nor_a_profile() -> None:
    result = CliRunner().invoke(
        app, ["drawing", "brief", "--package", str(PLATE_DRAWING), "--document", "doc:0003"]
    )

    assert result.exit_code == 0, result.output
    brief = json.loads(result.stdout)
    assert brief["drawing"]["candidates"] == ["FICT-TULMSORN-3002.SLDDRW"]
    assert brief["answers"] == [] and brief["conformance"]["profile"] is None


@pytest.mark.parametrize("document", ["doc:9999", "doc:0006"])
def test_the_command_exits_2_on_a_refusal(document: str) -> None:
    result = CliRunner().invoke(
        app, ["drawing", "brief", "--package", str(PLATE_DRAWING), "--document", document]
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert document in result.stderr


def test_a_run_folder_without_a_session_is_refused_naming_it(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["drawing", "brief", "--package", str(PLATE_DRAWING), "--document", "doc:0002",
         "--run", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "session.json" in result.stderr
