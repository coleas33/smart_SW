"""Builders for the lever 5 pre-run tests (T075, T076).

Two test modules read this one - "the pre-run is the same session" and "the digest says
what was not evaluated" - and both need the same package: one whose four self-enumerating
checks all have something to say. Kept here rather than in either module so the *calls*
the pre-run makes and the calls a scripted model makes are provably the same list, which
is what makes the same-session comparison a statement about the pre-run rather than about
two fixtures that happen to agree.

`MODEL_DRIVEN_CALLS` is that list, written once as `ScriptedToolCall`s and turned into the
pre-run's own plan by `swreview.prerun`. If the two ever disagree the same-session test
fails, which is the point.
"""

from __future__ import annotations

from typing import Any

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import run_review
from swreview.agent.settings import EfficiencySettings
from swreview.ir.loader import save_package
from swreview.ir.models import (
    Axis,
    EvidencePackage,
    Fastener,
    Hole,
    Interference,
    InterferenceSettings,
    Quantity,
    Vec3,
    Volume,
)
from swreview.report.session import ReviewSession
from tests.support.features import AssemblySpec, InstanceSpec, PartSpec, feature, rms_package
from tests.support.packages import persist_ref

ON = EfficiencySettings(prerun_checks=True)
OFF = EfficiencySettings()
"""The lever under test, and the default every shipped run still has."""

GATE_ON = EfficiencySettings(procedural_gate=True)
"""Lever 11 **alone**: it implies the pre-run and refuses to share an arm with lever 5.

`efficiency_from_levers` rejects `procedural_gate` together with `prerun_checks` until each
has been gated by itself (`contracts/gate.md` section 1), so this is the only spelling of
"the gate is on" there is, and the gate arm's pre-run is the same pre-run lever 5 runs.
"""

PART_DOCUMENT = "doc:3"
FIRST_INSTANCE = "cmp:0002"
SECOND_INSTANCE = "cmp:0003"
GROUP_KEY = "cmp:0002|cmp:0003"

INTERFERENCE_SETTINGS = InterferenceSettings(
    treat_coincident_as_interference=False,
    treat_subassemblies_as_components=True,
    include_multibody=False,
    ignore_hidden=True,
    fastener_folder_treatment="include",
)

MODEL_DRIVEN_CALLS: tuple[ScriptedToolCall, ...] = (
    ScriptedToolCall("check_rms_part"),
    ScriptedToolCall("check_rms_equations"),
    ScriptedToolCall("check_rms_assembly"),
    ScriptedToolCall("check_interference_group", {"group_key": GROUP_KEY}),
)
"""What a model has to ask for to reach the state the pre-run reaches on its own."""


def _axis(z_origin: float, x_origin: float = 0.0) -> Axis:
    return Axis(
        origin=Vec3(x=x_origin, y=0.0, z=z_origin),
        direction=Vec3(x=0.0, y=0.0, z=1.0),
    )


def _hole(hole_id: str, component_id: str, axis: Axis) -> Hole:
    return Hole(
        id=hole_id,
        persist_ref=persist_ref(hole_id),
        persist_ref_scope=PART_DOCUMENT,
        component_id=component_id,
        feature_name="M6 Tapped Hole1",
        hole_type="tapped",
        standard="ISO",
        size="M6",
        thread_designation="M6x1.0",
        thread_depth=None,
        hole_depth=Quantity(value=12.0, unit="mm"),
        end_condition="blind",
        diameter=Quantity(value=5.0, unit="mm"),
        axis=axis,
        face_ids=[],
    )


def prerun_package() -> EvidencePackage:
    """An assembly with a graded part tree, one interference group, two holes and a screw.

    Every one of the four self-enumerating checks has something to say about it, and the
    two families that are never pre-run - fastener joints and hole alignment - have
    something to be counted in the digest: the two holes share an axis, so they are one
    candidate pair, and the screw is one fastener with no derivable clamped stack.
    """
    package = rms_package(
        parts=[
            PartSpec(
                document_id=PART_DOCUMENT,
                name="housing",
                features=[feature("Boss-Extrude1", "Extrusion")],
                instances=[InstanceSpec("housing-1"), InstanceSpec("housing-2")],
            )
        ],
        assembly=AssemblySpec(),
    )
    shared = _axis(0.01)
    return package.model_copy(
        update={
            "holes": [
                _hole("hole:1", FIRST_INSTANCE, shared),
                _hole("hole:2", SECOND_INSTANCE, shared),
            ],
            "fasteners": [
                Fastener(
                    id="fst:1",
                    persist_ref=persist_ref("fst:1"),
                    persist_ref_scope="doc:1",
                    component_id=FIRST_INSTANCE,
                    kind="screw",
                    identity_source="name_parse",
                    thread_designation="M6x1.0",
                    length=Quantity(value=20.0, unit="mm"),
                    head_type="socket head cap",
                    head_diameter=Quantity(value=10.0, unit="mm"),
                    head_height=Quantity(value=6.0, unit="mm"),
                    drive=None,
                    axis=shared,
                    material=None,
                )
            ],
            "interferences": [
                Interference(
                    id="int:1",
                    configuration="Default",
                    component_ids=[FIRST_INSTANCE, SECOND_INSTANCE],
                    volume=Volume(value=42.0, unit="mm3"),
                    settings=INTERFERENCE_SETTINGS,
                    status="computed",
                    error=None,
                    group_key=GROUP_KEY,
                    is_fastener=False,
                    is_possible=False,
                )
            ],
        }
    )


def empty_model_check_package() -> EvidencePackage:
    """The Model check tab's dump of a part nobody could read a tree out of.

    Every pre-run check has nothing to evaluate: no feature rows, no equations, no
    interference, no holes and no fasteners. `record_partial_evidence` has already written
    its own `skipped` item for the profile, and the digest must not write a second one.
    """
    package = rms_package(
        parts=[PartSpec(document_id=PART_DOCUMENT, name="housing", features=[])]
    )
    return package.model_copy(
        update={
            "extractor": package.extractor.model_copy(update={"profile": "model_check"}),
            "features": [],
            "equations": [],
        }
    )


def review(
    tmp_path: Any,
    out: str,
    *,
    package: EvidencePackage | None = None,
    calls: tuple[ScriptedToolCall, ...] = (),
    **options: Any,
) -> ReviewSession:
    """One scripted review of `package`, written under `tmp_path / out`.

    `calls` is what the scripted model asks for; the empty default is the arm where the
    pre-run is the only thing that calls a check tool.
    """
    package_dir = tmp_path / "package"
    if not package_dir.exists():
        save_package(package if package is not None else prerun_package(), package_dir)
    return run_review(
        package_dir,
        tmp_path / out,
        provider=FakeProvider(
            script=[ScriptedTurn(text="done", tool_calls=calls)], model="fake-scripted"
        ),
        **options,
    )
