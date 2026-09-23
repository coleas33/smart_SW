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

from pathlib import Path
from typing import Any

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import run_review
from swreview.agent.settings import EfficiencySettings
from swreview.ir.loader import save_package
from swreview.ir.models import (
    Axis,
    DumpPhase,
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

PART_NAME = "housing"
STANDARDS_PART_NAME = "MR-10042"
"""What the part document is called, and what it is called when the standards checks grade
it. The second is shaped like `STANDARDS_PROFILE`'s fictional part-number convention -
`MR-` and five digits - so `standards.document.data_card_complete` applies to the document
rather than recording it out of scope. Both are invented; neither is a company value."""

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
    ScriptedToolCall("check_joints"),
    ScriptedToolCall("check_mass_material"),
    ScriptedToolCall("check_hygiene"),
)
"""What a model has to ask for to reach the state the pre-run reaches on its own; feature
010's `check_joints`, `check_mass_material` and `check_hygiene` joined through
`CODE_FIRST_CHECKS`, in its order, after the interference groups."""


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


def prerun_package(part_name: str = PART_NAME) -> EvidencePackage:
    """An assembly with a graded part tree, one interference group, two holes and a screw.

    Every one of the four self-enumerating checks has something to say about it, and the
    two families that are never pre-run - fastener joints and hole alignment - have
    something to be counted in the digest: the two holes share an axis, so they are one
    candidate pair, and the screw is one fastener with no derivable clamped stack.

    `part_name` names the part document, and so its file name and its instances.
    `standards_prerun_package` passes `STANDARDS_PART_NAME`, which is shaped like
    `STANDARDS_PROFILE`'s part-number convention so the data-card check applies to it; every
    other caller takes the default and is unchanged by the parameter.
    """
    package = rms_package(
        parts=[
            PartSpec(
                document_id=PART_DOCUMENT,
                name=part_name,
                features=[feature("Boss-Extrude1", "Extrusion")],
                instances=[InstanceSpec(f"{part_name}-1"), InstanceSpec(f"{part_name}-2")],
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


STANDARDS_PROFILE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "profile-a.yaml"
)
"""The fictional standards profile feature 006's goldens are graded against (FR-001).

Reused rather than copied: every value in it - the vault root, the four data-card property
names, the part-number convention, the revision property, the export-control phrase - is
invented for the suite, and a second fixture profile here would be a second set of invented
values free to disagree with it.
"""

CUTLIST_PHASE = DumpPhase(name="cutlist", elapsed_ms=1, status="ok")
"""The row that tells a standards extract from a model-check one.

`run_standards_checks` refuses a package whose `cutlist` row is missing or `skipped`
(`checks/standards/run.py::_refuse_missing_phases`), which is the third of the gate's three
not-evaluated cases, so a fixture for the *happy* path has to carry it.
"""


def empty_model_check_package() -> EvidencePackage:
    """The Model check tab's dump of a part nobody could read a tree out of.

    Every pre-run check has nothing to evaluate: no feature rows, no equations, no
    interference, no holes and no fasteners. `record_partial_evidence` has already written
    its own `skipped` item for the profile, and the digest must not write a second one.
    """
    package = rms_package(parts=[PartSpec(document_id=PART_DOCUMENT, name="housing", features=[])])
    return package.model_copy(
        update={
            "extractor": package.extractor.model_copy(update={"profile": "model_check"}),
            "features": [],
            "equations": [],
        }
    )


def standards_prerun_package(*, cutlist: bool = True) -> EvidencePackage:
    """`prerun_package()` dumped by the `standards` profile, so the gate can grade it.

    The same assembly the four self-enumerating checks already have something to say about,
    plus the one thing the standards half needs: the `cutlist` phase row. With `cutlist`
    false the row is `skipped`, which is a package dumped by a profile that never ran the
    phase - the third of the gate's three not-evaluated cases, and the one a review of a
    `model_check` dump hits in real life.

    No value here is a company value. The documents keep the fixture's own fictional names
    and paths, and the profile they are graded against is `STANDARDS_PROFILE`, which owns
    every string the checks read.
    """
    package = prerun_package(STANDARDS_PART_NAME)
    phase = (
        CUTLIST_PHASE
        if cutlist
        else CUTLIST_PHASE.model_copy(update={"status": "skipped", "elapsed_ms": None})
    )
    return package.model_copy(
        update={
            "extractor": package.extractor.model_copy(
                update={"profile": "standards", "phases": [phase]}
            )
        }
    )


CHECKS_FIRST = EfficiencySettings(prerun_checks=True)
"""Checks first, the pane default since 2026-09-22 (feature 008): lever 5 under its new name."""

LIVE_ZERO_KEY = f"{FIRST_INSTANCE}|{SECOND_INSTANCE}"
LIVE_OVERLAP_KEY = f"{FIRST_INSTANCE}|{SECOND_INSTANCE}|overlap"


def _live_row(row_id: str, group_key: str, volume_mm3: float) -> dict[str, Any]:
    return {
        "id": row_id,
        "configuration": "Default",
        "component_ids": [FIRST_INSTANCE, SECOND_INSTANCE],
        "volume": {"value": volume_mm3, "unit": "mm3"},
        "settings": {
            "treat_coincident_as_interference": True,
            "treat_subassemblies_as_components": True,
            "include_multibody": True,
            "ignore_hidden": False,
            "fastener_folder_treatment": "include",
        },
        "status": "computed",
        "error": None,
        "group_key": group_key,
        "is_fastener": False,
        "is_possible": False,
    }


LIVE_ROWS: tuple[dict[str, Any], ...] = (
    _live_row("int:0001", LIVE_ZERO_KEY, 0.0),
    _live_row("int:0002", LIVE_OVERLAP_KEY, 42.0),
)
"""What a scripted live detection returns: two groups, one zero-volume (a contact since
feature 010) and one overlapping by 42 mm³ (a finding), in the IR's row shape and under the
settings checks first states (`prerun.PRERUN_INTERFERENCE_SETTINGS`)."""


def live_prerun_package() -> EvidencePackage:
    """`prerun_package()` with no interference rows: what a dump that never ran detection
    holds, so every group the pre-run judges came from the live call. An assembly root with
    two instances, which is what live detection needs."""
    return prerun_package().model_copy(update={"interferences": []})


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
