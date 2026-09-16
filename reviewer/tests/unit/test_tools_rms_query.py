"""Unit tests for the RMS feature-tree query tools (T025).

One test per row of the query table in `specs/003-resilient-modeling/contracts/tools.md`,
plus the three rules that hold across both of them and are the reason these tools exist at
all rather than the model reading `package.json` itself:

- **every derived answer is the one the rules use.** `class`, `group`, `is_folder` and
  `is_end_tag` come from `checks/rms_types.py` and `checks/rms/groups.py`, so what the
  model is shown and what `check_rms_part` evaluated cannot disagree - which is also why
  the nested and the flat traversal shapes list the same features in the same groups;
- **an argument that names nothing comes back as an error result**, never an exception and
  never an empty list that reads like "there is nothing there";
- **unknown stays unknown.** A feature whose suppression state was not readable is not
  dropped by `include_suppressed=false`, and an id that resolves to no feature resolves to
  a `null` name rather than to a name someone invented.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from swreview.ir.models import EvidencePackage
from swreview.tools import rms_query
from swreview.tools.context import ToolContext, context_for, use_context
from swreview.tools.registry import RecordedTool, ToolRegistry
from tests.support.features import (
    END_TAG_SUFFIX,
    PartSpec,
    Shape,
    feature,
    folder,
    rms_package,
    sketch_feature,
)

ROW_KEYS: tuple[str, ...] = (
    "id",
    "name",
    "type_name",
    "class",
    "group",
    "folder_id",
    "depth",
    "suppressed",
    "description",
)
"""The columns `contracts/tools.md` gives `list_features`, in its order."""


def bracket(shape: Shape = "nested") -> PartSpec:
    """The part under test: three groups, a subfolder, and every awkward case.

    `Right Plane` is an excluded default name, `Boss-Extrude1` lost its `GetChildren`
    call, `Hole1` is suppressed, `Cut1`'s suppression state was unreadable, and
    `Widget1`'s type name is in no class set.
    """
    return PartSpec(
        document_id="doc:2",
        name="bracket",
        shape=shape,
        features=(
            folder("1-Ref", feature("Right Plane", "RefPlane", description=None)),
            folder(
                "3-Core",
                sketch_feature("Sketch1", consumers=("Boss-Extrude1",)),
                feature(
                    "Boss-Extrude1",
                    "Extrusion",
                    parent_names=("Sketch1",),
                    child_names=None,
                ),
            ),
            folder(
                "4-Detail",
                folder("hole-pair", feature("Hole1", "HoleWzd", suppressed=True)),
                feature("Cut1", "Cut", suppressed=None),
                feature("Widget1", "NoSuchType"),
            ),
        ),
    )


PLATE = PartSpec(
    document_id="doc:3",
    name="plate",
    features=(folder("3-Core", feature("Plate-Extrude1", "Extrusion")),),
)


def package(shape: Shape = "nested") -> EvidencePackage:
    return rms_package(parts=[bracket(shape), PLATE])


@pytest.fixture
def context() -> Iterator[ToolContext]:
    """The nested-shape package behind the contextvar the tools read."""
    tool_context = context_for(package())
    with use_context(tool_context):
        yield tool_context


def recorded(context: ToolContext, name: str) -> RecordedTool:
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]


def named(rows: list[dict[str, Any]]) -> list[str]:
    return [row["name"] for row in rows]


# --- list_features ------------------------------------------------------------------


def test_list_features_returns_the_contract_columns_in_index_order(
    context: ToolContext,
) -> None:
    rows = rms_query.list_features("doc:2")

    assert [list(row) for row in rows] == [list(ROW_KEYS)] * len(rows)
    assert named(rows) == [
        "1-Ref",
        "Right Plane",
        "3-Core",
        "Sketch1",
        "Boss-Extrude1",
        "4-Detail",
        "hole-pair",
        "Hole1",
        "Cut1",
        "Widget1",
    ]
    assert rows[1] == {
        "id": "feat:0002",
        "name": "Right Plane",
        "type_name": "RefPlane",
        "class": "reference",
        "group": "1-Ref",
        "folder_id": "feat:0001",
        "depth": 1,
        "suppressed": False,
        "description": None,
    }


def test_list_features_derives_the_class_and_the_group_of_every_row(
    context: ToolContext,
) -> None:
    """Including the two non-answers: a folder and an unrecognised type are `unknown`."""
    rows = rms_query.list_features("doc:2")

    assert {row["name"]: (row["class"], row["group"]) for row in rows} == {
        "1-Ref": ("unknown", "1-Ref"),
        "Right Plane": ("reference", "1-Ref"),
        "3-Core": ("unknown", "3-Core"),
        "Sketch1": ("sketch", "3-Core"),
        "Boss-Extrude1": ("solid", "3-Core"),
        "4-Detail": ("unknown", "4-Detail"),
        "hole-pair": ("unknown", "4-Detail"),
        "Hole1": ("hole", "4-Detail"),
        "Cut1": ("cut", "4-Detail"),
        "Widget1": ("unknown", "4-Detail"),
    }


def test_list_features_covers_one_document_only(context: ToolContext) -> None:
    assert named(rms_query.list_features("doc:3")) == ["3-Core", "Plate-Extrude1"]


def test_list_features_filters_by_group_name(context: ToolContext) -> None:
    rows = rms_query.list_features("doc:2", folder="4-Detail")

    assert named(rows) == ["4-Detail", "hole-pair", "Hole1", "Cut1", "Widget1"]


def test_list_features_filters_by_a_group_folders_feature_id(context: ToolContext) -> None:
    """A group folder names its group, so the id and the name select the same rows."""
    assert rms_query.list_features("doc:2", folder="feat:0006") == rms_query.list_features(
        "doc:2", folder="4-Detail"
    )


def test_list_features_filters_by_a_subfolders_feature_id(context: ToolContext) -> None:
    """A non-group folder selects its own members, not the whole group it sits in."""
    assert named(rms_query.list_features("doc:2", folder="feat:0007")) == ["Hole1"]


def test_list_features_without_include_suppressed_drops_the_suppressed_rows(
    context: ToolContext,
) -> None:
    rows = rms_query.list_features("doc:2", include_suppressed=False)

    assert "Hole1" not in named(rows)


def test_list_features_keeps_a_row_whose_suppression_state_was_unreadable(
    context: ToolContext,
) -> None:
    """`suppressed: null` is "nobody read it", which is not "it is suppressed"."""
    rows = rms_query.list_features("doc:2", include_suppressed=False)

    assert "Cut1" in named(rows)
    assert [row["suppressed"] for row in rows if row["name"] == "Cut1"] == [None]


def test_list_features_reads_the_flat_traversal_shape_the_same_way() -> None:
    """The shape `IFeatureManager` reported must not change which group a feature is in."""
    with use_context(context_for(package("flat"))):
        flat = [
            (row["name"], row["group"], row["class"])
            for row in rms_query.list_features("doc:2")
            if not row["name"].endswith(END_TAG_SUFFIX)
        ]
    with use_context(context_for(package("nested"))):
        nested = [
            (row["name"], row["group"], row["class"])
            for row in rms_query.list_features("doc:2")
        ]

    assert flat == nested


def test_list_features_refuses_a_document_the_package_does_not_carry(
    context: ToolContext,
) -> None:
    assert rms_query.list_features("doc:99") == {"error": "unknown document id 'doc:99'"}


def test_list_features_refuses_a_folder_that_names_nothing(context: ToolContext) -> None:
    result = rms_query.list_features("doc:2", folder="7-Nowhere")

    assert "7-Nowhere" in result["error"]
    assert "doc:2" in result["error"]


def test_list_features_refuses_a_feature_that_is_not_a_folder(context: ToolContext) -> None:
    """`feat:0008` is a hole, not a folder: filtering by it would report nothing at all."""
    assert "feat:0008" in rms_query.list_features("doc:2", folder="feat:0008")["error"]


def test_list_features_refuses_a_folder_of_another_document(context: ToolContext) -> None:
    """`feat:0011` is `doc:3`'s Core folder; naming it here is a mistake, not an empty group."""
    assert "feat:0011" in rms_query.list_features("doc:2", folder="feat:0011")["error"]


def test_list_features_is_registered_and_records_a_step(context: ToolContext) -> None:
    tool = recorded(context, "list_features")

    payload = tool.call({"document_id": "doc:3"}).payload

    assert named(payload["result"]) == ["3-Core", "Plate-Extrude1"]
    assert [step.tool for step in context.session.steps] == ["list_features"]


# --- get_feature --------------------------------------------------------------------


def test_get_feature_carries_the_whole_feature_and_the_derived_fields(
    context: ToolContext,
) -> None:
    result = rms_query.get_feature("feat:0008")

    assert result["id"] == "feat:0008"
    assert result["name"] == "Hole1"
    assert result["document_id"] == "doc:2"
    assert result["persist_ref"]
    assert result["persist_ref_scope"] == "doc:2"
    assert result["configuration"] == "Default"
    assert result["index"] == 7
    assert result["depth"] == 2
    assert result["folder_id"] == "feat:0007"
    assert result["suppressed"] is True
    assert result["error_code"] == 0
    assert result["class"] == "hole"
    assert result["group"] == "4-Detail"
    assert result["is_folder"] is False
    assert result["is_end_tag"] is False


def test_get_feature_resolves_children_parents_and_consumers_to_names(
    context: ToolContext,
) -> None:
    sketch = rms_query.get_feature("feat:0004")

    assert sketch["child_ids"] == ["feat:0005"]
    assert sketch["child_names"] == ["Boss-Extrude1"]
    assert sketch["sketch"]["consumer_ids"] == ["feat:0005"]
    assert sketch["consumer_names"] == ["Boss-Extrude1"]

    extrusion = rms_query.get_feature("feat:0005")

    assert extrusion["parent_ids"] == ["feat:0004"]
    assert extrusion["parent_names"] == ["Sketch1"]


def test_get_feature_leaves_an_unread_dependency_list_null(context: ToolContext) -> None:
    """`GetChildren` failed for this feature; `[]` would say it has no dependents."""
    extrusion = rms_query.get_feature("feat:0005")

    assert extrusion["child_ids"] is None
    assert extrusion["child_names"] is None


def test_get_feature_gives_a_feature_with_no_sketch_no_consumer_names(
    context: ToolContext,
) -> None:
    extrusion = rms_query.get_feature("feat:0005")

    assert extrusion["sketch"] is None
    assert extrusion["consumer_names"] is None


def test_get_feature_marks_a_group_folder_as_a_folder(context: ToolContext) -> None:
    result = rms_query.get_feature("feat:0006")

    assert result["is_folder"] is True
    assert result["is_end_tag"] is False
    assert result["group"] == "4-Detail"


def test_get_feature_marks_an_end_tag_marker(context: ToolContext) -> None:
    with use_context(context_for(package("flat"))):
        rows = rms_query.list_features("doc:2")
        markers = [row for row in rows if row["name"].endswith(END_TAG_SUFFIX)]
        assert markers, "the flat shape emits an end-tag marker per folder"
        result = rms_query.get_feature(markers[0]["id"])

    assert result["is_end_tag"] is True
    assert result["is_folder"] is False


def test_get_feature_refuses_an_id_the_package_does_not_carry(context: ToolContext) -> None:
    assert rms_query.get_feature("feat:9999") == {"error": "unknown feature id 'feat:9999'"}


def test_get_feature_is_registered_and_records_a_step(context: ToolContext) -> None:
    tool = recorded(context, "get_feature")

    payload = tool.call({"feature_id": "feat:0004"}).payload

    assert payload["name"] == "Sketch1"
    assert [step.tool for step in context.session.steps] == ["get_feature"]
