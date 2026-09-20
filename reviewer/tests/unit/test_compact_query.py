"""Focused tests for the opt-in bounded package discovery experiment."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

from swreview.agent.settings import EfficiencySettings
from swreview.ir.models import (
    BBox3D,
    FaceGeometry,
    Mate,
    MateEntity,
    Vec3,
)
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.query import COMPACT_RESPONSE_BYTES, compact_query
from swreview.tools.registry import ToolRegistry
from tests.support.packages import build_package, persist_ref


@contextmanager
def active(context: ToolContext) -> Iterator[None]:
    with use_context(context):
        yield


def test_components_are_stable_pages_with_complete_omission_metadata() -> None:
    base = build_package()
    components = [
        base.components[0].model_copy(
            update={"id": f"cmp:{1000 + index:04d}", "name": f"part-{index}"}
        )
        for index in range(25)
    ]
    context = context_for(base.model_copy(update={"components": components}))

    with active(context):
        first = compact_query("components", limit=7)
        second = compact_query("components", cursor=7, limit=7)

    assert first["total"] == 25
    assert first["shown"] == 7
    assert first["omitted"] == 18
    assert first["next_cursor"] == 7
    assert second["items"][0]["id"] == "cmp:1007"
    assert second["omitted_before"] == 7
    assert second["next_cursor"] == 14
    assert all(item["detail_tool"] == "get_component" for item in first["items"])

    seen: list[str] = []
    cursor = 0
    while True:
        with active(context):
            page = compact_query("components", cursor=cursor, limit=20)
        seen.extend(item["id"] for item in page["items"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    assert seen == [item.id for item in components]


def test_scope_uses_mate_entities_and_unknown_scope_is_an_error() -> None:
    base = build_package(
        mates=[
            Mate(
                id="mate:1",
                persist_ref=persist_ref("mate:1"),
                persist_ref_scope="doc:1",
                type="coincident",
                entities=[
                    MateEntity(
                        component_id="cmp:0001",
                        persist_ref=None,
                        entity_kind="face",
                    )
                ],
                alignment="aligned",
                suppressed=False,
                distance=None,
                angle=None,
            )
        ]
    )
    context = context_for(base)

    with active(context):
        scoped = compact_query("mates", scope_id="cmp:0001")
        missing = compact_query("mates", scope_id="cmp:9999")

    assert scoped["total"] == 1
    assert scoped["items"][0]["detail_tool"] == "list_mates"
    assert scoped["items"][0]["detail_component_id"] == "cmp:0001"
    assert missing == {"error": "unknown component id 'cmp:9999'"}


def test_hole_and_fastener_pages_keep_detail_pointers_and_unknown_values() -> None:
    context = context_for(build_package())

    with active(context):
        holes = compact_query("holes", scope_id="cmp:0001")
        fasteners = compact_query("fasteners", scope_id="cmp:0002")

    assert holes["items"][0]["thread_depth"] is None
    assert holes["items"][0]["thread_depth_note"] == "unknown"
    assert holes["items"][0]["detail_tool"] == "get_component"
    assert holes["items"][0]["detail_id"] == "cmp:0001"
    assert fasteners["items"][0]["identity_source"] == "name_parse"
    assert fasteners["items"][0]["detail_tool"] == "list_fasteners"
    assert fasteners["items"][0]["detail_component_id"] == "cmp:0002"


def test_large_descriptive_values_are_clipped_and_response_has_a_byte_ceiling() -> None:
    base = build_package()
    component = base.components[0].model_copy(update={"name": "x" * 50_000})
    context = context_for(base.model_copy(update={"components": [component]}))

    with active(context):
        result = compact_query("components")

    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= COMPACT_RESPONSE_BYTES
    item = result["items"][0]
    assert len(item["name"]) == 120
    assert item["truncated_fields"] == ["name"]


def test_budget_omitted_counts_all_candidates_after_the_page_boundary() -> None:
    base = build_package()
    components = [
        base.components[0].model_copy(
            update={"id": f"cmp:{2000 + index:04d}", "name": "x" * 120}
        )
        for index in range(20)
    ]
    context = context_for(base.model_copy(update={"components": components}))

    with active(context):
        result = compact_query("components", limit=20)

    assert 0 < result["shown"] < 20
    assert result["omitted_by_budget"] == 20 - result["shown"]


def test_an_oversized_identifier_advances_with_a_bounded_refusal() -> None:
    base = build_package()
    huge_id = "cmp:" + ("7" * 10_000)
    component = base.components[0].model_copy(update={"id": huge_id})
    context = context_for(base.model_copy(update={"components": [component]}))

    with active(context):
        result = compact_query("components")

    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= COMPACT_RESPONSE_BYTES
    assert result["shown"] == 0
    assert result["next_cursor"] is None
    assert result["oversized_item"]["detail_tool"] == "get_component"
    assert result["oversized_item"]["detail_id_omitted"] is True
    assert result["oversized_item"]["fallback_tool"] == "list_components"
    assert result["oversized_item"]["fallback_arguments"] == {"parent_id": None}


def test_default_registry_is_unchanged_and_opt_in_exposes_one_tool() -> None:
    context = context_for(build_package())
    off = {tool.name for tool in ToolRegistry().build(context)}
    on = {
        tool.name
        for tool in ToolRegistry().build(
            context, efficiency=EfficiencySettings(compact_queries=True)
        )
    }

    assert "compact_query" not in off
    assert "compact_query" in on
    assert on - off == {"compact_query"}

    tool = next(item for item in ToolRegistry().build(
        context, efficiency=EfficiencySettings(compact_queries=True)
    ) if item.name == "compact_query")
    invalid = tool.call({"kind": "components", "limit": 21})
    assert invalid.is_error is True
    assert "less than or equal to 20" in invalid.payload["error"]


def test_face_projection_keeps_exact_detail_component_pointer() -> None:
    base = build_package(
        faces=[
            FaceGeometry(
                id="face:1",
                persist_ref=persist_ref("face:1"),
                persist_ref_scope="doc:2",
                component_id="cmp:0001",
                body_id="body:1",
                kind="plane",
                cylinder=None,
                plane=None,
                bbox=BBox3D(
                    min=Vec3(x=0.0, y=0.0, z=0.0),
                    max=Vec3(x=1.0, y=1.0, z=1.0),
                ),
                area_m2=1.0,
            )
        ]
    )
    context = context_for(base)

    with active(context):
        result = compact_query("faces")

    assert result["items"][0]["detail_tool"] == "get_component"
    assert result["items"][0]["detail_id"] == "cmp:0001"
