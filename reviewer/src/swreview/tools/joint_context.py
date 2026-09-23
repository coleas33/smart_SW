"""What the joint checks read off the tool context (feature 010 US4, T049).

Two tool modules need the same two things: `check_joints` and the interference tool's
thread-model rule both read **one** joint map with the recognised fasteners placed in it,
built once per context and kept there; and both load body meshes from the package folder,
which the pure checks never do themselves. They live here, apart from both tools, so neither
tool imports the other.
"""

from __future__ import annotations

from dataclasses import dataclass

import trimesh

from swreview.checks.fastener_identity import RecognisedFastener, joint_map_with_fasteners
from swreview.checks.joints import JointMap
from swreview.tools.context import ToolContext
from swreview.tools.measure import load_body_mesh

__all__ = ["BodyMeshes", "JointAnalysis", "joint_analysis"]


@dataclass(frozen=True)
class JointAnalysis:
    """The recognised fasteners and the joint map they are placed in."""

    recognised: tuple[RecognisedFastener, ...]
    joint_map: JointMap


def joint_analysis(context: ToolContext) -> JointAnalysis:
    """The context's joint analysis, built on first use and kept on the context (T049), so
    `check_joints` and the interference tool's thread-model rule read one map, built once."""
    if context.joint_analysis is None:
        recognised, joint_map = joint_map_with_fasteners(context.ir)
        context.joint_analysis = JointAnalysis(recognised=recognised, joint_map=joint_map)
    analysis: JointAnalysis = context.joint_analysis
    return analysis


class BodyMeshes:
    """The package's body meshes by component, each loaded at most once per tool call.

    The tool layer's half of "pure but for the mesh load": the checks take a `mesh_of`
    callable and never open a file. A component whose bodies are absent, or any of whose
    bodies could not be loaded, reads as `None`, and the check that needed it says so.
    """

    def __init__(self, context: ToolContext) -> None:
        self._context = context
        self._meshes: dict[str, trimesh.Trimesh | None] = {}

    def mesh_of(self, component_id: str) -> trimesh.Trimesh | None:
        if component_id not in self._meshes:
            loaded = []
            for body in self._context.ir.bodies:
                if body.component_id != component_id:
                    continue
                mesh, _reason = load_body_mesh(self._context, body)
                if mesh is None:
                    loaded = []
                    break
                loaded.append(mesh)
            self._meshes[component_id] = trimesh.util.concatenate(loaded) if loaded else None
        return self._meshes[component_id]
