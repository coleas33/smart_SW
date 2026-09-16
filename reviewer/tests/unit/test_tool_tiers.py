"""Lever 4, tier selection: which tools each package class is offered (T060).

The whole lever is decidable from the package before the first turn, so every assertion
here is exact, deterministic and needs no provider and no key. Four things are pinned:

1. **The exact tool names**, spelled out per package class rather than derived from the
   registry, so a tier that quietly took `check_fit` with it goes red here.
2. **The rule is `features[]`, not the profile label.** A `full` dump of exported files
   carries no feature rows and loses the RMS tier; a `model_check` dump of a part carries
   them and keeps it.
3. **What the subset costs**, read from `tests/unit/test_tool_payload.py`'s computation
   through `measure` and `tier_delta` rather than restated - the figures are regenerated,
   never transcribed.
4. **Per-turn, never per-round, and never mid-session.** Both adapters build their tool
   encoding once per turn before the round loop, so a per-turn subset needs no adapter
   change at all: the dispatch simply yields fewer tools. Two turns of one session are
   handed the same ToolSet and encode a byte-identical array, which is what makes "no
   mid-session tools_changed" true by construction rather than by luck.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent.providers import ToolSet
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from swreview.tools.registry import RMS_TIER_TOOLS
from tests.support.tiers import (
    OFF,
    ON,
    dispatch_for,
    full_assembly_with_tree,
    full_assembly_without_tree,
    model_check_part_with_tree,
    offered,
    part_only_without_tree,
)
from tests.unit.test_tool_payload import (
    RMS_TIER_DELTA_BYTES,
    RMS_TIER_DELTA_PERCENT,
    RMS_TIER_KEPT_BYTES,
    RMS_TIER_KEPT_TOOLS,
    TOOL_OBJECT_CEILING,
    measure,
    tier_delta,
)

# --- the names, spelled out --------------------------------------------------------------

QUERY = (
    "get_package_summary",
    "list_components",
    "get_component",
    "find_components",
    "list_mates",
    "list_holes",
    "list_fasteners",
    "list_interferences",
    "get_drawing_sheet",
    "find_dimensions",
    "list_gaps",
    "get_exceptions",
    "list_features",
    "get_feature",
    "list_equations",
)
MEASUREMENT = (
    "measure_axis_distance",
    "measure_face_gap",
    "check_tool_envelope",
    "bounding_box",
)
CHECK = (
    "check_fit",
    "check_axial_stack",
    "check_fastener_joint",
    "check_hole_alignment",
    "check_interference_group",
    "check_rms_part",
    "check_rms_assembly",
    "check_rms_equations",
)
SESSION = (
    "request_evidence",
    "mark_coverage",
    "record_drawing_finding",
    "get_review_checklist",
    "request_capture",
)
BRIDGE = ("bridge_capture", "bridge_measure", "bridge_interference")

EVERY_TOOL = (*QUERY, *MEASUREMENT, *CHECK, *SESSION)
"""The 32 curated tools in registration order - the array a no-bridge run sends today."""

RMS_TIER = (
    "list_features",
    "get_feature",
    "list_equations",
    "check_rms_part",
    "check_rms_assembly",
    "check_rms_equations",
)
"""The six tools a package with no feature rows cannot use."""

WITHOUT_RMS_TIER = (
    "get_package_summary",
    "list_components",
    "get_component",
    "find_components",
    "list_mates",
    "list_holes",
    "list_fasteners",
    "list_interferences",
    "get_drawing_sheet",
    "find_dimensions",
    "list_gaps",
    "get_exceptions",
    "measure_axis_distance",
    "measure_face_gap",
    "check_tool_envelope",
    "bounding_box",
    "check_fit",
    "check_axial_stack",
    "check_fastener_joint",
    "check_hole_alignment",
    "check_interference_group",
    "request_evidence",
    "mark_coverage",
    "record_drawing_finding",
    "get_review_checklist",
    "request_capture",
)
"""The 26 the RMS tier leaves, written out rather than filtered: this list is the pin."""

GRADABLE: dict[str, Any] = {
    "full assembly, tree dumped": full_assembly_with_tree,
    "model_check part, tree dumped": model_check_part_with_tree,
}
NOT_GRADABLE: dict[str, Any] = {
    "full assembly, no part documents": full_assembly_without_tree,
    "part only, tree never read": part_only_without_tree,
}


def offered_functions(package: EvidencePackage) -> list[Any]:
    """The tool *functions* this run offers with the flag on, which is what `measure` weighs."""
    return [tool.spec.fn for tool in dispatch_for(package, efficiency=ON)]


# --- 1. the exact names, per package class ------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [*GRADABLE.values(), *NOT_GRADABLE.values()],
    ids=[*GRADABLE, *NOT_GRADABLE],
)
def test_the_flag_off_offers_every_curated_tool_whatever_the_package_carries(
    build: Any,
) -> None:
    """The lever is off in every shipped run, and off means the array of feature 001."""
    assert tuple(offered(build(), efficiency=OFF)) == EVERY_TOOL


@pytest.mark.parametrize("build", GRADABLE.values(), ids=list(GRADABLE))
def test_a_package_with_feature_rows_keeps_every_tool_with_the_flag_on(build: Any) -> None:
    """Nothing is withheld from a package the RMS rules can actually be graded against."""
    assert tuple(offered(build(), efficiency=ON)) == EVERY_TOOL


@pytest.mark.parametrize("build", NOT_GRADABLE.values(), ids=list(NOT_GRADABLE))
def test_a_package_with_no_feature_rows_loses_the_rms_tier_and_nothing_else(
    build: Any,
) -> None:
    """32 tools to 26, and the 26 are named here rather than derived from the registry."""
    assert tuple(offered(build(), efficiency=ON)) == WITHOUT_RMS_TIER


def test_the_withheld_set_is_the_rms_tier_the_registry_declares() -> None:
    """One declaration of the six names, in `tools/registry.py`; this is the pin on it."""
    assert set(RMS_TIER_TOOLS) == set(RMS_TIER)
    assert set(RMS_TIER) == set(EVERY_TOOL) - set(WITHOUT_RMS_TIER)


# --- 2. the rule reads the feature rows, not the profile label ----------------------------


def test_the_profile_label_alone_decides_nothing() -> None:
    """`model_check` skips the hole, fastener, face and body phases, not the feature tree.

    So the tier cannot key on the label: a `full` package can arrive with no feature rows
    (an assembly of exported files) and a `model_check` package normally arrives with them.
    """
    assert tuple(offered(model_check_part_with_tree(), efficiency=ON)) == EVERY_TOOL
    assert tuple(offered(full_assembly_without_tree(), efficiency=ON)) == WITHOUT_RMS_TIER


def test_session_tools_are_never_withheld_by_any_tier() -> None:
    """`mark_coverage` is how coverage stays honest and `get_review_checklist` is how the
    model knows what is still open. No tier may take either."""
    assert not set(SESSION) & set(RMS_TIER_TOOLS)
    for build in NOT_GRADABLE.values():
        assert set(SESSION) <= set(offered(build(), efficiency=ON))


# --- 3. the bridge tier, which was already implemented -------------------------------------


@pytest.mark.parametrize("efficiency", [OFF, ON], ids=["flag off", "flag on"])
def test_bridge_tools_are_offered_only_when_a_bridge_is_wired(efficiency: Any) -> None:
    """Tier B is `context.bridge is None` and predates this lever; lever 4 leaves it alone."""
    package = full_assembly_with_tree()

    assert set(BRIDGE) & set(offered(package, efficiency=efficiency)) == set()
    assert tuple(offered(package, efficiency=efficiency, bridge=object())) == (
        *EVERY_TOOL,
        *BRIDGE,
    )


def test_a_bridge_run_over_a_package_with_no_tree_loses_the_rms_tier_only() -> None:
    """The two tiers compose: the bridge is still offered, the six RMS tools are not."""
    names = offered(full_assembly_without_tree(), efficiency=ON, bridge=object())

    assert tuple(names) == (*WITHOUT_RMS_TIER, *BRIDGE)


# --- 4. what the subset costs, regenerated rather than transcribed --------------------------


def test_the_offered_array_weighs_what_the_measured_rms_tier_says_it_should() -> None:
    """The byte figures come from `test_tool_payload`'s computation, not from this file."""
    row = measure("rms tier withheld", offered_functions(full_assembly_without_tree()), "openai")
    delta = tier_delta()

    assert row.tools == delta.kept_tools == RMS_TIER_KEPT_TOOLS
    assert row.total_bytes == delta.kept_bytes == RMS_TIER_KEPT_BYTES
    assert delta.delta_bytes == RMS_TIER_DELTA_BYTES
    assert delta.delta_percent == RMS_TIER_DELTA_PERCENT
    assert row.largest_tool_bytes < TOOL_OBJECT_CEILING["openai"]


def test_a_package_with_a_tree_saves_nothing() -> None:
    """The asymmetry stated rather than averaged away: this class pays the full array."""
    kept = measure("gradable", offered_functions(full_assembly_with_tree()), "openai")
    withheld = measure(
        "not gradable", offered_functions(full_assembly_without_tree()), "openai"
    )

    assert kept.total_bytes == tier_delta().full_bytes
    assert kept.total_bytes - withheld.total_bytes == RMS_TIER_DELTA_BYTES


# --- 5. per turn, never per round, and never mid-session ------------------------------------


class RecordingFake(FakeProvider):
    """A `FakeProvider` that also writes down the tool array it was handed, turn by turn."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.handed: list[ToolSet] = []
        self.encoded: list[int] = []
        self.names: list[tuple[str, ...]] = []

    def run(self, *, tools: ToolSet, **options: Any) -> Any:
        self.handed.append(tools)
        self.names.append(tuple(tool.name for tool in tools))
        self.encoded.append(
            measure("turn", [tool.spec.fn for tool in tools], "openai").total_bytes
        )
        return super().run(tools=tools, **options)


def test_two_turns_of_one_session_encode_a_byte_identical_tool_array(
    tmp_path: Path,
) -> None:
    """The tier is decided once, when the dispatch is built, and never again.

    A tool array that changed between turn 1 and turn 2 would be a `tools_changed` cache
    miss for the rest of the session on OpenAI. The package-decidable scope rules that
    out by construction: the same `ToolSet` object is handed to every turn, which is also
    why a per-turn subset needs no adapter change at all.
    """
    package_dir = tmp_path / "package"
    save_package(full_assembly_without_tree(), package_dir)
    provider = RecordingFake(
        script=[ScriptedTurn(text="one"), ScriptedTurn(text="two")], model="fake-scripted"
    )

    run = start_review(package_dir, tmp_path / "out", provider=provider, efficiency=ON)
    run.start()
    run.continue_session("and the drawing?")

    assert len(provider.handed) == 2
    assert provider.handed[0] is provider.handed[1] is run.tools
    assert provider.names[0] == provider.names[1] == WITHOUT_RMS_TIER
    assert provider.encoded[0] == provider.encoded[1] == RMS_TIER_KEPT_BYTES
