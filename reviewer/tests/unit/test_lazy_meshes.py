"""Unit tests for lever 10a, lazy meshes (T098).

A package extracted without meshes has nothing for `check_tool_envelope` to sweep, so with
`extraction.meshes = "lazy"` the check fetches each component's bodies over the bridge
first. Everything that can go wrong with that fetch has one answer, and these tests are
what pin it: **the body is named in `unresolved`**, never dropped, and the check never
comes back `checked` over a sweep that tested nothing (constitution Principle I; FR-088,
SC-021).

The four failures the contract names, one test each:

- a body whose mesh could not be loaded after the fetch - the path
  `tools/measure.py` already takes for a missing mesh file;
- a bridge that refuses, which arrives as a `BridgeError` and becomes the reason;
- reaching `extraction.lazy_fetch_body_limit`, which is **unresolved coverage, not a
  stop**: the check finishes, naming what it did not pull back;
- **off the workstation there is no bridge at all**, so a lazily extracted package
  reviewed later on a machine with no SOLIDWORKS cannot answer a tool-access question.
  That is acceptable only because the zero-bodies guard already makes that answer
  `unresolved` with a reason instead of silence.

`eager` is the default here as it is everywhere else: the flag that reduces evidence is the
one that is opted into.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import trimesh

from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.agent.settings import EfficiencySettings, ExtractionSettings
from swreview.bridge.client import BridgeError, BridgeUnauthorizedError
from swreview.ir.models import EvidencePackage, Quantity
from swreview.tools import measure
from swreview.tools.context import ToolContext, context_for, use_context

MakePackage = Callable[..., EvidencePackage]

MESH_DIR = "meshes"
LENGTH = Quantity(value=40.0, unit="mm")


def body_row(component_id: str, body_id: str, mesh_file: str) -> dict[str, Any]:
    """One `BodyRef` as the host sends it (Serve/PROTOCOL.md, `tessellate`)."""
    return {
        "id": body_id,
        "persist_ref": "Qm9keQ==",
        "persist_ref_scope": "doc:2",
        "component_id": component_id,
        "mesh_file": mesh_file,
        "triangle_count": 12,
        "is_solid": True,
    }


class FakeBridge:
    """A host that writes a mesh where it says it did, and records what it was asked.

    `refuse` makes every call raise, which is how a refused secret, a closed document and
    an open circuit all arrive at the tool layer.
    """

    def __init__(
        self,
        package_dir: Path,
        *,
        refuse: Exception | None = None,
        write_file: bool = True,
        bodies_per_component: int = 1,
    ) -> None:
        self.package_dir = package_dir
        self.refuse = refuse
        self.write_file = write_file
        self.bodies_per_component = bodies_per_component
        self.asked: list[str] = []

    def tessellate(self, component_id: str) -> dict[str, Any]:
        self.asked.append(component_id)
        if self.refuse is not None:
            raise self.refuse

        rows: list[dict[str, Any]] = []
        paths: list[str] = []
        for index in range(self.bodies_per_component):
            name = f"{component_id.replace(':', '-')}-bod-{index:04d}.glb"
            relative = f"{MESH_DIR}/{name}"
            if self.write_file:
                self._write(name)
            rows.append(body_row(component_id, f"bod:{component_id[-1]}{index}", relative))
            paths.append(str(self.package_dir / MESH_DIR / name))
        return {"bodies": rows, "paths": paths, "gaps": []}

    def _write(self, name: str) -> None:
        meshes = self.package_dir / MESH_DIR
        meshes.mkdir(parents=True, exist_ok=True)
        # A box well clear of the sweep: what is asserted here is which bodies were swept,
        # not what they hit.
        trimesh.creation.box(bounds=[[0.2, 0.2, 0.2], [0.3, 0.3, 0.3]]).export(meshes / name)


def lazy_context(
    make_package: MakePackage,
    package_dir: Path,
    bridge: Any,
    *,
    meshes: str = "lazy",
    limit: int = 200,
) -> ToolContext:
    """A context over a package extracted without meshes, with `bridge` wired."""
    context = context_for(make_package(), base_dir=package_dir)
    context.bridge = bridge
    context.extraction = ExtractionSettings(meshes=meshes, lazy_fetch_body_limit=limit)
    return context


def envelope(context: ToolContext) -> dict[str, Any]:
    with use_context(context):
        return measure.check_tool_envelope("fst:1", "socket", LENGTH)


# --- the settings ------------------------------------------------------------------


def test_eager_is_the_default() -> None:
    settings = ExtractionSettings()

    assert settings.meshes == "eager"
    assert settings.lazy_fetch_body_limit > 0


def test_the_flag_off_leaves_extraction_eager() -> None:
    """A lazily extracted package is a package with less evidence, so it is opted into."""
    assert ExtractionSettings.for_efficiency(EfficiencySettings()).meshes == "eager"
    assert ExtractionSettings.for_efficiency(None).meshes == "eager"


def test_the_flag_on_makes_the_extraction_lazy() -> None:
    settings = ExtractionSettings.for_efficiency(EfficiencySettings(lazy_meshes=True))

    assert settings.meshes == "lazy"


def test_the_settings_refuse_an_unknown_mesh_mode() -> None:
    with pytest.raises(ValueError):
        ExtractionSettings(meshes="sometimes")


def test_the_settings_refuse_a_negative_limit() -> None:
    with pytest.raises(ValueError):
        ExtractionSettings(lazy_fetch_body_limit=-1)


def test_start_review_hands_the_context_the_extraction_the_lever_asks_for(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The lever reaches the check through the context, and through nothing else."""
    off = start_review(
        tmp_package_dir,
        tmp_path / "off",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=EfficiencySettings(),
    )
    on = start_review(
        tmp_package_dir,
        tmp_path / "on",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        efficiency=EfficiencySettings(lazy_meshes=True),
    )

    assert off.context.extraction.meshes == "eager"
    assert on.context.extraction.meshes == "lazy"


# --- the fetch ---------------------------------------------------------------------


def test_eager_never_asks_the_bridge_for_a_mesh(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """With the flag off nothing about the check changes, bridge or no bridge."""
    bridge = FakeBridge(tmp_path)
    context = lazy_context(make_package, tmp_path, bridge, meshes="eager")

    result = envelope(context)

    assert bridge.asked == []
    assert result["status"] == "unresolved"
    assert result["bodies_swept"] == 0


def test_lazy_fetches_every_component_but_the_fasteners_own(
    make_package: MakePackage, tmp_path: Path
) -> None:
    bridge = FakeBridge(tmp_path)
    context = lazy_context(make_package, tmp_path, bridge)

    result = envelope(context)

    # fst:1 is on cmp:0002, whose own bodies the sweep excludes anyway.
    assert bridge.asked == ["cmp:0001"]
    assert result["status"] == "checked"
    assert result["bodies_swept"] == 1
    assert result["unresolved"] == []
    assert [body.component_id for body in context.ir.bodies] == ["cmp:0001"]


def test_a_second_check_does_not_fetch_the_same_component_twice(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """The rows land in the package, so the second check reads them like any dumped row."""
    bridge = FakeBridge(tmp_path)
    context = lazy_context(make_package, tmp_path, bridge)

    envelope(context)
    envelope(context)

    assert bridge.asked == ["cmp:0001"]


def test_a_body_whose_mesh_did_not_arrive_is_named_in_unresolved(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """The host answered with a row and no file: the body is named, never dropped."""
    bridge = FakeBridge(tmp_path, write_file=False)
    context = lazy_context(make_package, tmp_path, bridge)

    result = envelope(context)

    assert result["status"] == "unresolved"
    assert result["bodies_swept"] == 0
    assert any("cmp:0001" in reason for reason in result["unresolved"])


def test_a_component_that_comes_back_with_no_body_is_named_in_unresolved(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """An empty answer is not "nothing is in the way"; it is a body that was not tested."""
    bridge = FakeBridge(tmp_path, bodies_per_component=0)
    context = lazy_context(make_package, tmp_path, bridge)

    result = envelope(context)

    assert result["status"] == "unresolved"
    assert any("cmp:0001" in reason for reason in result["unresolved"])


@pytest.mark.parametrize(
    "refusal",
    [
        BridgeUnauthorizedError("the bridge returned status 'error': unauthorized"),
        BridgeError("the bridge on \\\\.\\pipe\\swreview could not be reached"),
    ],
)
def test_a_bridge_that_refuses_is_unresolved_with_the_reason(
    make_package: MakePackage, tmp_path: Path, refusal: Exception
) -> None:
    bridge = FakeBridge(tmp_path, refuse=refusal)
    context = lazy_context(make_package, tmp_path, bridge)

    result = envelope(context)

    assert result["status"] == "unresolved"
    assert result["bodies_swept"] == 0
    assert any("cmp:0001" in reason for reason in result["unresolved"])
    assert any(str(refusal)[:20] in reason for reason in result["unresolved"])


def test_reaching_the_fetch_limit_is_unresolved_coverage_not_a_stop(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """The check still answers; it names the component it did not pull back.

    The limit bounds how much one review may fetch so a runaway does not stall the
    application thread - one STA worker answers every bridge call in arrival order.
    """
    bridge = FakeBridge(tmp_path)
    context = lazy_context(make_package, tmp_path, bridge, limit=0)

    result = envelope(context)

    assert result["status"] == "unresolved"
    assert bridge.asked == []
    assert any(
        "cmp:0001" in reason and "limit" in reason for reason in result["unresolved"]
    )


def test_off_the_workstation_there_is_no_bridge_and_the_answer_says_so(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """A lazily extracted package reviewed where there is no SOLIDWORKS.

    Acceptable only because the answer is `unresolved` with a reason rather than silence,
    which is what the zero-bodies guard (T032) made true.
    """
    context = lazy_context(make_package, tmp_path, None)

    result = envelope(context)

    assert result["status"] == "unresolved"
    assert result["bodies_swept"] == 0
    assert any("bridge" in reason for reason in result["unresolved"])
    assert any("swept no body" in reason for reason in result["unresolved"])


def test_meshes_off_fetches_nothing_and_is_still_not_a_clear(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """`off` is "this package has no meshes and none are coming", not "all clear"."""
    bridge = FakeBridge(tmp_path)
    context = lazy_context(make_package, tmp_path, bridge, meshes="off")

    result = envelope(context)

    assert bridge.asked == []
    assert result["status"] == "unresolved"
    assert result["bodies_swept"] == 0


def test_a_mesh_path_outside_the_package_is_refused(
    make_package: MakePackage, tmp_path: Path
) -> None:
    """The host is trusted to run SOLIDWORKS, not to choose where the reviewer reads."""

    class EscapingBridge(FakeBridge):
        def tessellate(self, component_id: str) -> dict[str, Any]:
            self.asked.append(component_id)
            return {
                "bodies": [
                    body_row(component_id, "bod:1", "../outside/cmp-0001-bod-0001.glb")
                ],
                "paths": [r"C:\somewhere-else\cmp-0001-bod-0001.glb"],
                "gaps": [],
            }

    context = lazy_context(make_package, tmp_path, EscapingBridge(tmp_path))

    result = envelope(context)

    assert result["status"] == "unresolved"
    assert context.ir.bodies == []
    assert any("outside the package" in reason for reason in result["unresolved"])
