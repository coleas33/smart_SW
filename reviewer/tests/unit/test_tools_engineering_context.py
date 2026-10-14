"""Engineering context is an explicit, recorded, read-only addition to a run (016)."""

from __future__ import annotations

import inspect
from pathlib import Path
from uuid import UUID

import pytest

from swreview.agent.settings import MODEL_VIEW_PANE, EfficiencySettings
from swreview.engineering_context.brief import build_record_detail, build_summary
from swreview.ir.loader import LoadedPackage
from swreview.mcp.server import MCP_TOOL_FUNCTIONS
from swreview.tools import engineering_context
from swreview.tools.context import context_for, use_context
from swreview.tools.registry import TOOL_FUNCTIONS, ToolRegistry, engineering_context_tools
from tests.support.packages import build_package
from tests.unit.test_engineering_context_brief import (
    FORCE_ID,
    REQUIREMENT_ID,
    confirmed,
    example_context,
)
from tests.unit.test_tool_payload import encoding_digests
from tests.unit.test_tools_registry_view import encoded_hashes

CONTEXT_TOOLS = {
    "get_engineering_context_summary",
    "get_engineering_context_record",
}


def test_without_explicit_context_the_default_surface_and_wire_bytes_are_unchanged() -> None:
    context = context_for(build_package())

    dispatch = ToolRegistry().dispatch(context)

    assert context.engineering_context is None
    assert CONTEXT_TOOLS.isdisjoint(dispatch.by_name)
    assert tuple(tool.name for tool in dispatch) == tuple(fn.__name__ for fn in TOOL_FUNCTIONS)
    assert encoded_hashes(dispatch) == encoding_digests()
    assert CONTEXT_TOOLS.isdisjoint(fn.__name__ for fn in MCP_TOOL_FUNCTIONS)


def test_optional_existing_surfaces_do_not_add_context_tools_without_a_snapshot() -> None:
    context = context_for(build_package())

    dispatch = ToolRegistry().dispatch(
        context,
        efficiency=EfficiencySettings(tool_tiers=True, compact_queries=True),
        model_view=MODEL_VIEW_PANE,
    )

    assert CONTEXT_TOOLS.isdisjoint(dispatch.by_name)


def test_injected_context_adds_only_two_read_tools_and_records_their_calls(tmp_path: Path) -> None:
    artifact, loaded = example_context(tmp_path)
    context = context_for(loaded.package, base_dir=loaded.base_dir)
    original = ToolRegistry().dispatch(context)
    context.engineering_context = artifact
    before = artifact.model_dump_json()

    dispatch = ToolRegistry().dispatch(context)
    summary = dispatch.call("get_engineering_context_summary", {})
    detail = dispatch.call(
        "get_engineering_context_record",
        {"context_id": str(artifact.context_id), "record_id": REQUIREMENT_ID},
    )

    assert set(dispatch.by_name) - set(original.by_name) == CONTEXT_TOOLS
    assert {fn.__name__ for fn in engineering_context_tools()} == CONTEXT_TOOLS
    assert summary.is_error is False and detail.is_error is False
    assert summary.payload == build_summary(artifact, loaded)
    assert detail.payload == build_record_detail(artifact, REQUIREMENT_ID, loaded)
    assert [step.tool for step in context.require_session().steps] == [
        "get_engineering_context_summary", "get_engineering_context_record",
    ]
    assert not context.require_session().findings
    assert not context.require_session().evidence_requests
    assert artifact.model_dump_json() == before
    assert detail.payload["record"]["decision"] == "draft"


def test_slim_and_plain_models_get_the_same_bounded_truth(tmp_path: Path) -> None:
    artifact, loaded = example_context(tmp_path)
    context = context_for(loaded.package, base_dir=loaded.base_dir)
    context.engineering_context = artifact
    plain = ToolRegistry().dispatch(context)
    slim = ToolRegistry().dispatch(context, model_view=MODEL_VIEW_PANE)
    arguments = {"context_id": str(artifact.context_id), "record_id": FORCE_ID}

    off = plain.call("get_engineering_context_record", arguments)
    on = slim.call("get_engineering_context_record", arguments)

    assert on.payload == off.payload == on.view
    assert off.view is None
    assert on.payload["native_model_state"] == "not_observed"
    assert on.payload["structural_assessment"] == "not_performed"
    assert on.payload["record"]["magnitude"]["value"] is None


def test_tools_accept_ids_without_hidden_context_or_write_arguments() -> None:
    assert not inspect.signature(engineering_context.get_engineering_context_summary).parameters
    parameters = inspect.signature(engineering_context.get_engineering_context_record).parameters
    assert tuple(parameters) == ("context_id", "record_id")


def test_package_refresh_reassesses_binding_without_creating_a_confirmation(tmp_path: Path) -> None:
    artifact, loaded = example_context(tmp_path)
    artifact = confirmed(artifact)
    context = context_for(loaded.package, base_dir=loaded.base_dir)
    context.engineering_context = artifact
    dispatch = ToolRegistry().dispatch(context)
    arguments = {"context_id": str(artifact.context_id), "record_id": REQUIREMENT_ID}

    before = dispatch.call("get_engineering_context_record", arguments)
    refreshed = loaded.package.model_copy(
        update={"package_id": UUID("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff")}
    )
    context.reload_package(LoadedPackage(package=refreshed, base_dir=loaded.base_dir))
    after = dispatch.call("get_engineering_context_record", arguments)

    assert before.payload["record"]["binding"]["status"] == "matched_snapshot"
    assert before.payload["record"]["decision"] == "confirmed"
    assert after.payload["record"]["binding"]["status"] == "unresolved"
    assert after.payload["record"]["needs_review"] is True
    assert after.payload["record"]["decision"] == "confirmed"  # original historical decision
    assert after.payload["record"]["confirmation_history"] == before.payload["record"][
        "confirmation_history"
    ]
    assert before.payload["native_model_state"] == after.payload["native_model_state"] == (
        "not_observed"
    )


def test_no_snapshot_returns_a_descriptive_refusal_for_direct_calls() -> None:
    context = context_for(build_package())
    with use_context(context):
        result = engineering_context.get_engineering_context_summary()
        detail = engineering_context.get_engineering_context_record("unknown", "unknown")

    assert result == detail == {"error": "no engineering context was supplied for this run"}


def test_wrong_context_and_unknown_record_refuse_without_echoing_a_private_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, loaded = example_context(tmp_path)
    context = context_for(loaded.package, base_dir=loaded.base_dir)
    context.engineering_context = artifact
    dispatch = ToolRegistry().dispatch(context)
    path = "C:/private/FICT-context.json"

    unknown = dispatch.call(
        "get_engineering_context_record",
        {"context_id": str(artifact.context_id), "record_id": path},
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a wrong context ID must refuse before any projection")

    monkeypatch.setattr(engineering_context, "build_record_detail", forbidden)
    wrong = dispatch.call(
        "get_engineering_context_record", {"context_id": path, "record_id": REQUIREMENT_ID}
    )
    assert unknown.is_error is True and wrong.is_error is True
    assert path not in unknown.payload["error"] and path not in wrong.payload["error"]
