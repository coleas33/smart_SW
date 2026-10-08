"""The case generator, its in-memory half (feature 014 T125; `generator.md` 2 to 4, 7, 10 and 11;
data-model section 5; CS-1, GN-1, GN-4, GN-8, GN-9; FR-027, FR-028, FR-029, FR-031, FR-048,
FR-051).

Every committed case is written by `tests.benchmark_cases` from one case spec, through the
formats' data-only models. This module drives the generator over a small fictional design
defined here, `quill` (a plate, a cover, two dowel pins, two screws, an assembly drawing and the
plate's drawing, built with the builders), and over seed kinds of its own where the machinery,
not a contract kind, is under test; T146 adds the tests over the committed tree.

1. **Refusals (section 10).** Each row is a `CaseSpecError`, a `ValueError` beginning
   "case spec {case id}:" with the row's gist, the first failing row ending the run before
   anything renders: rows 1 to 8's per-entry halves through `spec.check_specs`, row 8's coverage
   half through `spec.check_anchor_coverage` and `generate.render_all()`, rows 9 and 10 over
   what `render_all()` rendered, row 11 when a format model refuses what the spec built.
2. **Seed kinds (section 3).** `seeds.KINDS` holds exactly the contract's kinds; each row's
   check, producer, expected status and withheld evidence pinned; each family is
   `family_of(check)`; withheld evidence exactly when the model produces the defect (16A); every
   check exact (GN-9); a planted and a clean form, where both exist, key the same check, parts,
   documents and references on `quill`.
3. **Twins (section 4).** `spec.twin(spec)` is `<case>-twin` with the same design, variant and
   places, no seeds and no decoys, and one condition per seed carrying the kind's check, the
   seed's places, tag and stamp, described "clean twin of <case> D-<n>: <the clean form>", with
   the kind's correct call where it confirms the clean form: never a drawing kind's, nor, by
   owner decision 55A, `coaxiality_undrawn`'s.
4. **The render format (section 7).** A key, a case file and a set entry are UTF-8, LF, indented
   2, with a final newline and non-ASCII written as itself; they validate through `AnswerKey`,
   `CaseFile` and `BenchmarkSet.file_form`; the IR's identity is section 5.5's.
5. **The place-name resolver**, the one way a place becomes an id, and the calls it resolves.
6. **Stale files (section 1).** `generate.stale_files` names every file under the four generated
   folders that the render lacks, skips the hand-kept and the native-package slot, deletes
   nothing; `generate.main` writes the render's bytes and exits 1 on a stale file.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid5

import pytest

from swreview.benchmark import families
from swreview.benchmark.answer_key_model import AnswerKey, Stamp, is_family
from swreview.benchmark.case_file import CaseFile
from swreview.benchmark.sets import REPO_ROOT, BenchmarkSet
from swreview.checks.rms import registry as rms_registry
from swreview.checks.rms_types import load_table
from swreview.checks.standards import registry as standards_registry
from swreview.checks.standards.part import evaluate_part
from swreview.checks.standards.traversal import graded_documents
from swreview.ir.models import EvidencePackage, SourceRef
from swreview.tools import checks_fastener, rms_checks
from swreview.tools.context import context_for, use_context
from tests.benchmark_cases import designs, generate, render, seeds, spec, stamps, vocabulary
from tests.benchmark_cases.spec import (
    CASE_NAMESPACE,
    Answer,
    CaseSpec,
    CaseSpecError,
    ComponentPlace,
    Condition,
    ContactPlace,
    Coverage,
    Design,
    DimensionPlace,
    DocumentPlace,
    Forbidden,
    Form,
    HeldOut,
    HolePlace,
    Laid,
    Place,
    PlaceName,
    QuestionCount,
    ScrewPlace,
    Seed,
    SeedKind,
    ToolCall,
    Tree,
    TunedOn,
    Unanswerable,
)
from tests.support.drawings import SheetBuilder
from tests.support.features import PartSpec, part_trees
from tests.support.mechanical import (
    CREATED_AT,
    FICTIONAL_ROOT,
    Face,
    Instance,
    PackageBuilder,
    cylinder_mesh,
    transform,
)
from tests.support.standards import card

CURRENT = HeldOut(stamps.CURRENT)
PROFILE = vocabulary.EXAMPLE_PROFILE
Z = (0.0, 0.0, 1.0)

# --- the quill design ---------------------------------------------------------------------

ROOT_STEM, PLATE_STEM, COVER_STEM = "EX-1101-00", "EX-1101-01", "EX-1101-02"
PIN_STEM = "FICT-PIN-3X20-0001"
BOUGHT_FOLDER = PROFILE.part_roles.bought_folder_names[0]
VENDOR = PROFILE.part_roles.vendor_properties[0]
CLEARANCE_BORE = ("bilateral", 0.025, 0.0)
CLEARANCE_SHAFT = ("bilateral", -0.009, -0.025)

QUILL_PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "plate_doc": DocumentPlace(),
    "cover_doc": DocumentPlace(),
    "pin_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "plate_drw": DocumentPlace(),
    "plate": ComponentPlace(document="plate_doc"),
    "cover": ComponentPlace(document="cover_doc"),
    "pin_a": ComponentPlace(document="pin_doc"),
    "pin_b": ComponentPlace(document="pin_doc"),
    "tap_a": HolePlace(
        component="plate", thread="M5x0.8", thread_depth_mm=10.0, hole_depth_mm=12.0
    ),
    "tap_b": HolePlace(
        component="plate", thread="M5x0.8", thread_depth_mm=10.0, hole_depth_mm=12.0
    ),
    "clr_a": HolePlace(component="cover"),
    "clr_b": HolePlace(component="cover"),
    "dowel_a": HolePlace(component="plate"),
    "dowel_b": HolePlace(component="plate"),
    "cdowel_a": HolePlace(component="cover"),
    "cdowel_b": HolePlace(component="cover"),
    "pair_a": HolePlace(component="plate"),
    "pair_b": HolePlace(component="cover"),
    "other_a": HolePlace(component="plate"),
    "other_b": HolePlace(component="cover"),
    "screw_a": ScrewPlace(
        thread="M5-0.8", length_mm=12.0, hole="tap_a", clamped=("cover",), clamp_mm=4.0
    ),
    "screw_b": ScrewPlace(
        thread="M5-0.8", length_mm=12.0, hole="tap_b", clamped=("cover",), clamp_mm=4.0
    ),
    "bore": DimensionPlace(drawing="assy_drw", nominal_mm=3.0, limits=CLEARANCE_BORE, prefix="Ø"),
    "shaft": DimensionPlace(drawing="assy_drw", nominal_mm=3.0, limits=CLEARANCE_SHAFT, prefix="Ø"),
    "sibling_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=3.0, limits=CLEARANCE_BORE, prefix="Ø"
    ),
    "sibling_shaft": DimensionPlace(
        drawing="assy_drw", nominal_mm=3.0, limits=CLEARANCE_SHAFT, prefix="Ø"
    ),
    "tolerance": DimensionPlace(drawing="assy_drw", nominal_mm=0.1, limits=None, text="⌖ Ø0.1"),
    "enclosing": DimensionPlace(drawing="assy_drw", nominal_mm=21.0, limits=("symmetric", 0.05)),
    "inside_1": DimensionPlace(drawing="assy_drw", nominal_mm=16.0, limits=("symmetric", 0.05)),
    "inside_2": DimensionPlace(drawing="assy_drw", nominal_mm=4.0, limits=("symmetric", 0.05)),
    "target": DimensionPlace(drawing="assy_drw", nominal_mm=1.0, limits=("symmetric", 0.3)),
    "callout": DimensionPlace(
        drawing="plate_drw",
        nominal_mm=10.0,
        limits=None,
        text="1X M5x0.8 - 6H THREAD ↧ 10",
    ),
    "plate_dim": DimensionPlace(drawing="plate_drw", nominal_mm=3.0, limits=CLEARANCE_BORE),
    "pin_a_plate": ContactPlace(a="pin_a", b="plate"),
    "pin_b_cover": ContactPlace(a="pin_b", b="cover", overlap_mm3=1.237),
}
"""`quill`'s places: a fastener, hole, fit, stack, drawing and contact place for every kind of
section 3, and the siblings their decoys name."""

HOLES: dict[str, tuple[str, float, float, float, float, float, float]] = {
    # name: (hole type, size, diameter, x, y, face from, face to), z up from the joint face
    "tap_a": ("tapped", 0.0, 4.2, 20.0, 0.0, -12.0, 0.0),
    "tap_b": ("tapped", 0.0, 4.2, 60.0, 0.0, -12.0, 0.0),
    "clr_a": ("clearance", 5.5, 5.5, 20.0, 0.0, 0.0, 4.0),
    "clr_b": ("clearance", 5.5, 5.5, 60.0, 0.0, 0.0, 4.0),
    "dowel_a": ("clearance", 3.0, 3.0, 20.0, 30.0, -16.0, 0.0),
    "dowel_b": ("clearance", 3.0, 3.0, 60.0, 30.0, -16.0, 0.0),
    "cdowel_a": ("clearance", 3.1, 3.1, 20.0, 30.0, 0.0, 4.0),
    "cdowel_b": ("clearance", 3.1, 3.1, 60.0, 30.0, 0.0, 4.0),
    # The empty pairs' plate faces stop 2 mm short of the joint face, beyond the joint rules'
    # 1 mm adjacency, so the joint map pairs neither (`joint_absent`) and only
    # `check_hole_alignment` compares them.
    "pair_a": ("clearance", 4.0, 4.0, 40.0, 50.0, -16.0, -2.0),
    "pair_b": ("clearance", 4.0, 4.0, 40.0, 50.0, 0.0, 4.0),
    "other_a": ("clearance", 4.0, 4.0, 40.0, 70.0, -16.0, -2.0),
    "other_b": ("clearance", 4.0, 4.0, 40.0, 70.0, 0.0, 4.0),
}
DIMENSIONS = (
    "bore",
    "shaft",
    "sibling_bore",
    "sibling_shaft",
    "tolerance",
    "enclosing",
    "inside_1",
    "inside_2",
    "target",
    "callout",
    "plate_dim",
)


def custom_properties(place: Place, stem: str, summary: str) -> dict[str, str]:
    """A custom document's properties in the example profile's names (`generator.md` 5.2)."""
    assert isinstance(place, DocumentPlace)
    hygiene = PROFILE.hygiene
    assert hygiene is not None
    return {
        **card(PROFILE, revision="A" if place.revision else None),
        hygiene.part_number_property: stem,
        hygiene.description_property: summary,
    }


def lay_quill(variant: str | None, places: Mapping[str, Place]) -> Laid:
    """`quill`'s clean base with every form applied, through the builders (`generator.md` 5.1)."""
    summary = "quill zorbex plate" if variant == "named" else "quill plate"
    builder = PackageBuilder(
        ROOT_STEM, root_properties=custom_properties(places["assy"], ROOT_STEM, "quill assy")
    )
    ids: dict[str, str | SourceRef] = {"assy": builder.root_id}
    ids["plate_doc"] = builder.document(
        PLATE_STEM,
        "part",
        material="6061-T6",
        mass_kg=0.2592,
        volume_mm3=96000.0,
        properties=custom_properties(places["plate_doc"], PLATE_STEM, summary),
    )
    ids["cover_doc"] = builder.document(
        COVER_STEM,
        "part",
        material="6061-T6",
        mass_kg=0.0648,
        volume_mm3=24000.0,
        properties=custom_properties(places["cover_doc"], COVER_STEM, "quill cover"),
    )
    pin_doc = places["pin_doc"]
    assert isinstance(pin_doc, DocumentPlace)
    ids["pin_doc"] = builder.document(
        PIN_STEM,
        "part",
        material="Alloy Steel",
        mass_kg=0.00111,
        volume_mm3=141.372,
        properties={VENDOR: "FICT", "Description": "M3 X 20 - PIN"},
        opened=pin_doc.opened,
    )
    pins_state = "resolved" if pin_doc.opened else "lightweight"
    ids["plate"] = builder.component(str(ids["plate_doc"]))
    ids["cover"] = builder.component(str(ids["cover_doc"]))
    for pin, x in (("pin_a", 20.0), ("pin_b", 60.0)):
        ids[pin] = builder.component(
            str(ids["pin_doc"]), placement=transform((x, 30.0, -16.0)), suppression=pins_state
        )

    for name, (hole_type, size, diameter, x, y, lo, hi) in HOLES.items():
        record = places[name]
        assert isinstance(record, HolePlace)
        tapped = hole_type == "tapped"
        if tapped and record.hole_depth_mm is not None:
            lo = -record.hole_depth_mm
        ids[name] = builder.hole(
            str(ids[record.component]),
            hole_type=hole_type,  # type: ignore[arg-type]
            size=record.thread if tapped and record.thread else f"Ø{size:g}",
            thread=record.thread,
            thread_depth_mm=record.thread_depth_mm,
            hole_depth_mm=record.hole_depth_mm,
            end_condition="blind" if tapped else "through",
            instances=[Instance((x + record.offset_mm, y, 0.0), Z, (Face(diameter, lo, hi),))],
        )
        if tapped and record.thread_depth_mm is None:
            builder.gap(
                kind="not_extracted",
                entity_kind="hole",
                entity_id=ids[name],
                reason="usable thread depth not reported by the hole feature",
                error=None,
            )

    if pin_doc.opened:
        for pin, x in (("pin_a", 20.0), ("pin_b", 60.0)):
            builder.cylinder_face(
                str(ids[pin]),
                origin_mm=(x, 30.0, 0.0),
                direction=Z,
                diameter_mm=3.0,
                lo_mm=-16.0,
                hi_mm=4.0,
            )
            builder.mesh(str(ids[pin]), cylinder_mesh((x, 30.0, 0.0), Z, 3.0, -16.0, 4.0))

    screw_components: dict[str, str] = {}
    for serial, name in enumerate(("screw_a", "screw_b"), start=1):
        record = places[name]
        assert isinstance(record, ScrewPlace)
        _, _, _, x, y, _, _ = HOLES[record.hole]
        document = builder.screw_document(
            "SHC", record.thread, record.length_mm, serial=serial, properties={VENDOR: "FICT"}
        )
        off = 0.0 if record.seated else 1.0
        screw_components[name] = builder.screw(
            document,
            bearing_mm=(x + off, y + off, record.clamp_mm),
            direction=Z,
            fastener_row=True,
        )

    for name in ("pin_a_plate", "pin_b_cover"):
        record = places[name]
        assert isinstance(record, ContactPlace)
        if pin_doc.opened:
            ids[name] = builder.interference(
                str(ids[record.a]),
                str(ids[record.b]),
                volume_mm3=record.volume_mm3,
                is_possible=record.possible,
            )

    built = builder.build()
    package = built.package
    for name, component in screw_components.items():
        ids[name] = next(row.id for row in package.fasteners if row.component_id == component)
    bought = {
        str(ids["pin_doc"]),
        *(row.document_id for row in package.components if row.id in screw_components.values()),
    }
    documents = []
    for document in package.documents:
        path = document.path
        if document.document_id in bought:
            path = f"{FICTIONAL_ROOT}Vault\\{BOUGHT_FOLDER}\\{document.file_name}"
        if variant == "pathed" and document.document_id == ids["plate_doc"]:
            # every token is the vocabulary's, so the root check, not the names check, refuses
            path = f"D:\\Fictional\\Vault\\{document.file_name}"
        documents.append(document.model_copy(update={"path": path}))
    entries = [
        entry.model_copy(
            update={
                "vault_path": next(
                    row.path for row in documents if row.document_id == entry.document_id
                )
            }
        )
        for entry in package.manifest.entries
    ]
    components = [
        row.model_copy(update={"is_fixed": True}) if row.id == ids["plate"] else row
        for row in package.components
    ]
    trees = []
    for name, stem in (("plate_doc", PLATE_STEM), ("cover_doc", COVER_STEM)):
        record = places[name]
        assert isinstance(record, DocumentPlace)
        if record.tree is not None:
            features, equations = spec.tree_specs(record.tree)
            trees.append(
                PartSpec(
                    document_id=str(ids[name]), name=stem, features=features, equations=equations
                )
            )
    features, equations = part_trees(trees)
    package = package.model_copy(
        update={
            "documents": documents,
            "manifest": package.manifest.model_copy(update={"entries": entries}),
            "components": components,
            "features": features,
            "equations": equations,
        }
    )

    sheets = SheetBuilder(package)
    for name, stem in (("assy_drw", ROOT_STEM), ("plate_drw", PLATE_STEM)):
        ids[name] = sheets.drawing(
            stem, properties=custom_properties(places[name], stem, f"quill drawing {stem}")
        )
        sheets.sheet(str(ids[name]), page=1)
    for name in DIMENSIONS:
        record = places[name]
        assert isinstance(record, DimensionPlace)
        ids[name] = sheets.dimension(
            str(ids[record.drawing]),
            record.sheet,
            record.nominal_mm,
            limits=record.limits,
            text=record.as_read(),
        )
    return Laid(package=sheets.build(), meshes=built.meshes, ids=ids)


QUILL = Design(name="quill", places=QUILL_PLACES, lay=lay_quill, variants=("named", "pathed"))

QUILL_TREED = dataclasses.replace(
    QUILL,
    places={
        **QUILL_PLACES,
        "plate_doc": DocumentPlace(tree=Tree()),
        "cover_doc": DocumentPlace(tree=Tree()),
    },
)
"""`quill` with the compliant feature tree of `spec.tree_specs` on each custom part, where the R-7
kinds sit."""


# --- seed kinds of this module's own ----------------------------------------------------------


def _replaced(places: Mapping[str, Place], name: str, **changes: Any) -> dict[str, Place]:
    return {name: dataclasses.replace(places[name], **changes)}  # type: ignore[type-var]


def _joint(at: Mapping[str, str], places: Mapping[str, Place]) -> ScrewPlace:
    record = places[at["fastener"]]
    assert isinstance(record, ScrewPlace)
    return record


LOCAL_JOINT = SeedKind(
    name="local_joint",
    check="fastener.thread_match",
    producer="model",
    expected_status="demonstrated",
    withheld=("joint_placement",),
    roles={"fastener": "fastener"},
    plant=Form(
        "a screw one size below its hole",
        lambda at, places: _replaced(places, at["fastener"], thread="M4-0.7", seated=False),
    ),
    clean=Form(
        "the screw's thread equals its hole's",
        lambda at, places: _replaced(places, at["fastener"], thread="M5-0.8", seated=False),
    ),
    references=lambda at, places: (
        {"fastener": PlaceName(at["fastener"]), "hole": PlaceName(_joint(at, places).hole)},
    ),
    correct_calls=lambda at, places: (
        ToolCall(
            "check_fastener_joint",
            {
                "fastener_id": PlaceName(at["fastener"]),
                "hole_id": PlaceName(_joint(at, places).hole),
                "clamped_component_ids": [PlaceName(name) for name in _joint(at, places).clamped],
            },
        ),
    ),
    decoys=lambda at, places: (ToolCall("list_fasteners", {"component_id": PlaceName("cover")}),),
)
LOCAL_FIT = SeedKind(
    name="local_fit",
    check="fit.size_only",
    producer="model",
    expected_status="suspected",
    withheld=("tolerance_source", "drawing_only"),
    roles={"bore": "dimension", "shaft": "dimension"},
    plant=Form(
        "limits that straddle zero clearance",
        lambda at, places: {
            **_replaced(places, at["bore"], limits=("bilateral", 0.010, 0.0)),
            **_replaced(places, at["shaft"], limits=("bilateral", 0.006, -0.004)),
        },
    ),
    clean=Form(
        "clearance limits",
        lambda at, places: {
            **_replaced(places, at["bore"], limits=CLEARANCE_BORE),
            **_replaced(places, at["shaft"], limits=CLEARANCE_SHAFT),
        },
    ),
    references=lambda at, places: (
        {"bore": PlaceName(at["bore"]), "shaft": PlaceName(at["shaft"])},
    ),
    correct_calls=lambda at, places: (
        ToolCall(
            "check_fit",
            {
                "bore_dimension_ref": PlaceName(at["bore"]),
                "shaft_dimension_ref": PlaceName(at["shaft"]),
            },
        ),
    ),
)


def _callout(at: Mapping[str, str], places: Mapping[str, Place]) -> DimensionPlace:
    record = places[at["callout"]]
    assert isinstance(record, DimensionPlace)
    return record


LOCAL_DRAWING = SeedKind(
    name="local_drawing",
    check="drawing.manufacturing_inputs",
    producer="model",
    expected_status="unresolved",
    withheld=("drawing_only",),
    roles={"callout": "dimension"},
    plant=Form(
        "a callout stating the drill depth only",
        lambda at, places: _replaced(places, at["callout"], text="1X M5x0.8 - 6H DRILL ↧ 12"),
    ),
    clean=Form(
        "a callout stating the thread depth",
        lambda at, places: _replaced(places, at["callout"], text="1X M5x0.8 - 6H THREAD ↧ 10"),
    ),
    documents=lambda at, places: (_callout(at, places).drawing,),
    correct_calls=lambda at, places: (
        ToolCall(
            "record_drawing_finding",
            {
                "document_id": PlaceName(_callout(at, places).drawing),
                "sheet": _callout(at, places).sheet,
                "observed": f"The callout {_callout(at, places).as_read()!r} lacks a thread depth.",
                "requirement": "A blind tapped hole's thread depth is drawn.",
                "source_refs": [PlaceName(at["callout"])],
                "status": "unresolved",
                "recommended_action": "State the thread depth.",
            },
        ),
    ),
    confirms_clean=False,
)
LOCAL_CODE = SeedKind(
    name="local_code",
    check="interference.static",
    producer="code",
    expected_status="demonstrated",
    withheld=(),
    roles={"a": "component", "b": "component"},
    plant=Form(
        "a positive overlap",
        lambda at, places: _replaced(places, "pin_b_cover", volume_mm3=1.237),
    ),
    clean=None,
    parts=lambda at, places: (at["a"], at["b"]),
)
LOCAL_CLEAN_ONLY = SeedKind(
    name="local_clean_only",
    check="fit.size_only",
    producer="model",
    expected_status=None,
    withheld=("tolerance_source", "drawing_only"),
    roles={"bore": "dimension", "shaft": "dimension"},
    plant=None,
    clean=LOCAL_FIT.clean,
    references=LOCAL_FIT.references,
    correct_calls=LOCAL_FIT.correct_calls,
)

JOINT_A = Seed(LOCAL_JOINT, {"fastener": "screw_a"}, CURRENT)
FIT = Seed(LOCAL_FIT, {"bore": "bore", "shaft": "shaft"}, CURRENT)
DRAWING = Seed(LOCAL_DRAWING, {"callout": "callout"}, CURRENT)


def case(case_id: str = "quill-1", design: Design = QUILL, **fields: Any) -> CaseSpec:
    """A spec on `quill`, by default one case with no seed."""
    return CaseSpec(case_id=case_id, design=design, **fields)


def refused(specs: list[CaseSpec], pattern: str) -> str:
    """`check_specs(specs)` refuses with a message matching `pattern`; the message."""
    with pytest.raises(CaseSpecError) as raised:
        spec.check_specs(specs)
    message = str(raised.value)
    assert isinstance(raised.value, ValueError)
    assert re.search(pattern, message), message
    return message


def rendered_json(files: Mapping[str, bytes], path: str) -> Any:
    return json.loads(files[path].decode("utf-8"))


def key_of(files: Mapping[str, bytes], case_id: str) -> AnswerKey:
    return AnswerKey.model_validate_json(files[f"benchmarks/answer_keys/{case_id}.json"])


def package_of(files: Mapping[str, bytes], case_id: str) -> EvidencePackage:
    return EvidencePackage.model_validate_json(files[f"benchmarks/packages/{case_id}/package.json"])


# --- 1. refusals, section 10 ------------------------------------------------------------------


def test_a_spec_set_meeting_every_row_passes() -> None:
    spec.check_specs([case(seeds=(JOINT_A, FIT), twin=True), case("quill-2", seeds=(DRAWING,))])


def test_row_1_a_case_id_named_twice_is_refused() -> None:
    refused([case(), case()], r"^case spec quill-1: .*named twice")


@pytest.mark.parametrize("case_id", ["Quill-1", "quill_1", "quill--1", "quill-zorbex-1", "-1"])
def test_row_1_a_case_id_outside_the_grammar_is_refused(case_id: str) -> None:
    refused([case(case_id)], rf"^case spec {re.escape(case_id)}: .*cases\.md 2")


def test_row_1_a_case_id_ending_twin_is_refused() -> None:
    refused([case("quill-1-twin")], r"^case spec quill-1-twin: .*twin.*derived")


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"seeds": (Seed(LOCAL_JOINT, {"fastener": "screw_z"}, CURRENT),)}, r"D-1.*screw_z"),
        ({"seeds": (Seed(LOCAL_JOINT, {"fastener": "tap_a"}, CURRENT),)}, r"D-1.*tap_a.*hole"),
        ({"seeds": (Seed(LOCAL_JOINT, {}, CURRENT),)}, r"D-1.*fastener"),
        (
            {"seeds": (Seed(LOCAL_JOINT, {"fastener": "screw_a", "spare": "screw_b"}, CURRENT),)},
            r"D-1.*spare",
        ),
        (
            {
                "forbidden": (
                    Forbidden(
                        checks=("rms.*",),
                        component_ids=("plate_z",),
                        tag=TunedOn("R-1"),
                        description="No modelling finding.",
                    ),
                )
            },
            r"FB-1.*plate_z",
        ),
        (
            {"answers": (Answer(item="interfaces.fit", ids=("pin_z",), answer="press fit"),)},
            r"A-1.*pin_z",
        ),
        (
            {
                "conditions": (
                    Condition(
                        check="fit.size_only",
                        document_ids=("assy_drw",),
                        references=({"bore": PlaceName("bore"), "shaft": PlaceName("shaft")},),
                        correct_call=ToolCall(
                            "check_fit", {"bore_dimension_ref": PlaceName("bore_z")}
                        ),
                        tag=TunedOn("R-3"),
                        description="A slip fit.",
                    ),
                )
            },
            r"C-1.*bore_z",
        ),
        (
            {"decoys": (ToolCall("check_fit", {"bore_dimension_ref": PlaceName("bore_z")}),)},
            r"decoy 1.*bore_z",
        ),
        ({"variant": "tall"}, r"variant tall"),
    ],
)
def test_row_2_a_name_the_design_does_not_define_is_refused(
    fields: dict[str, Any], named: str
) -> None:
    refused([case(**fields)], rf"^case spec quill-1: .*{named}")


def test_row_3_three_held_out_model_produced_seeds_are_refused() -> None:
    refused([case(seeds=(JOINT_A, FIT, DRAWING))], r"^case spec quill-1: .*D-1, D-2 and D-3")


def test_row_3_two_held_out_model_produced_seeds_of_one_family_are_refused() -> None:
    joint_b = Seed(LOCAL_JOINT, {"fastener": "screw_b"}, CURRENT)
    refused([case(seeds=(JOINT_A, joint_b))], r"^case spec quill-1: .*D-1 and D-2.*fastener")


def test_row_3_counts_neither_a_code_produced_nor_a_tuned_on_seed() -> None:
    code = Seed(LOCAL_CODE, {"a": "pin_b", "b": "cover"}, CURRENT)
    tuned = Seed(LOCAL_JOINT, {"fastener": "screw_b"}, TunedOn("R-6"))
    spec.check_specs([case(seeds=(JOINT_A, FIT, code, tuned))])


def test_row_4_a_held_out_seed_with_another_stamp_is_refused() -> None:
    stale = HeldOut(Stamp(prompt="0" * 64, checklist="1" * 64, tools="2" * 64))
    seed = Seed(LOCAL_JOINT, {"fastener": "screw_a"}, stale)
    refused([case(seeds=(seed,))], r"^case spec quill-1: D-1 .*stamps\.CURRENT")


@pytest.mark.parametrize("reason", ["", "   "])
def test_row_4_a_tuned_on_seed_with_no_reason_is_refused(reason: str) -> None:
    seed = Seed(LOCAL_JOINT, {"fastener": "screw_a"}, TunedOn(reason))
    refused([case(seeds=(seed,))], r"^case spec quill-1: D-1 .*no reason")


def test_row_4_holds_a_key_only_entry_too() -> None:
    entry = Forbidden(
        checks=("rms.*",),
        component_ids=("pin_a",),
        tag=TunedOn(""),
        description="No modelling finding on the pin.",
    )
    refused([case(forbidden=(entry,))], r"^case spec quill-1: FB-1 .*no reason")


def test_row_5_a_drawing_seed_whose_document_carries_another_seed_s_reference() -> None:
    fit = Seed(LOCAL_FIT, {"bore": "plate_dim", "shaft": "shaft"}, CURRENT)
    refused([case(seeds=(DRAWING, fit))], r"^case spec quill-1: .*D-1.*plate_drw.*D-2")


def test_row_5_a_drawing_seed_whose_document_carries_a_condition_s_reference() -> None:
    condition = Condition(
        check="fit.size_only",
        document_ids=("plate_drw", "assy_drw"),
        references=({"bore": PlaceName("plate_dim"), "shaft": PlaceName("shaft")},),
        tag=TunedOn("R-3"),
        description="A slip fit across the two drawings.",
    )
    refused(
        [case(seeds=(DRAWING,), conditions=(condition,))],
        r"^case spec quill-1: .*D-1.*plate_drw.*C-1",
    )


def test_row_5_a_second_drawing_seed_is_refused() -> None:
    """The second tuned on, so row 3 (two held-out seeds of one family) does not fire first."""
    second = dataclasses.replace(DRAWING, tag=TunedOn("R-2"))
    refused([case(seeds=(DRAWING, second))], r"^case spec quill-1: .*second drawing seed")


def test_row_5_does_not_hold_a_pilot_only_case_whose_every_item_is_tuned_on() -> None:
    drawing = dataclasses.replace(DRAWING, tag=TunedOn("prompt-encodes-cbt-answer"))
    fit = Seed(LOCAL_FIT, {"bore": "plate_dim", "shaft": "shaft"}, TunedOn("R-3"))
    spec.check_specs([case(seeds=(drawing, fit), sets=("pilot",))])


def test_row_5_holds_a_pilot_only_case_holding_one_held_out_item() -> None:
    drawing = dataclasses.replace(DRAWING, tag=TunedOn("prompt-encodes-cbt-answer"))
    fit = Seed(LOCAL_FIT, {"bore": "plate_dim", "shaft": "shaft"}, CURRENT)
    refused([case(seeds=(drawing, fit), sets=("pilot",))], r"^case spec quill-1: .*plate_drw")


def test_row_5_a_kind_refusing_the_design_s_records_names_the_case() -> None:
    """Row 5 reads each seed's references on the design's records; a kind that cannot (no screw
    goes into the hole a `bottoming_thread_depth_unknown` seed names) refuses as a
    `CaseSpecError` naming the case (`generator.md` 10), never a bare `ValueError`."""
    drill_only = Seed(seeds.KINDS["callout_drill_only"], CALLOUT_AT, CURRENT)
    depth_unknown = Seed(
        seeds.KINDS["bottoming_thread_depth_unknown"], {"hole": "dowel_a"}, TunedOn("R-2")
    )

    refused(
        [case(seeds=(drill_only, depth_unknown))],
        r"^case spec quill-1: no screw place of the design goes into dowel_a$",
    )


def test_row_6_a_twin_of_a_kind_with_no_clean_form_is_refused() -> None:
    code = Seed(LOCAL_CODE, {"a": "pin_b", "b": "cover"}, TunedOn("R-4"))
    refused([case(seeds=(code,), twin=True)], r"^case spec quill-1: D-1 .*local_code.*no clean")


def test_row_6_a_seed_of_a_kind_with_no_planted_form_is_refused() -> None:
    seed = Seed(LOCAL_CLEAN_ONLY, {"bore": "bore", "shaft": "shaft"}, TunedOn("R-3"))
    refused([case(seeds=(seed,))], r"^case spec quill-1: D-1 .*local_clean_only.*no planted")


def test_row_7_a_held_out_seed_outside_the_committed_set_is_refused() -> None:
    refused([case(seeds=(JOINT_A,), sets=("pilot",))], r"^case spec quill-1: D-1 .*committed")


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"represents": ("AF-4",)}, r"AF-4"),
        ({"represents": ("r-1",)}, r"r-1"),
        (
            {"seeds": (Seed(LOCAL_JOINT, {"fastener": "screw_a"}, TunedOn("R-9"), "R-9"),)},
            r"D-1.*R-9",
        ),
        (
            {"seeds": (Seed(LOCAL_JOINT, {"fastener": "screw_a"}, CURRENT, "R-3"),)},
            r"D-1.*R-3.*tuned-on",
        ),
        (
            {
                "forbidden": (
                    Forbidden(
                        checks=("rms.*",),
                        component_ids=("pin_a",),
                        tag=CURRENT,
                        description="No modelling finding.",
                        represents="R-1",
                    ),
                )
            },
            r"FB-1.*R-1.*tuned-on",
        ),
        (
            {
                "expected_coverage": (
                    Coverage(
                        item="interference",
                        statuses=("skipped",),
                        tag=TunedOn("R-5"),
                        description="Not read.",
                        represents="AF-9",
                    ),
                )
            },
            r"CV-1.*AF-9",
        ),
    ],
)
def test_row_8_a_represents_value_outside_the_anchors_or_an_anchor_held_out(
    fields: dict[str, Any], named: str
) -> None:
    refused([case(**fields)], rf"^case spec quill-1: .*{named}")


def test_row_8_an_analyst_found_item_may_be_held_out() -> None:
    seed = Seed(LOCAL_JOINT, {"fastener": "screw_a"}, CURRENT, "AF-1")
    spec.check_specs([case(seeds=(seed,), represents=("R-6", "AF-1"))])


def test_row_8_coverage_names_every_missing_id_and_check_specs_passes_the_same_list() -> None:
    partial = [case(represents=("R-1", "R-2")), case("quill-2", represents=("AF-2",))]

    spec.check_specs(partial)
    with pytest.raises(CaseSpecError) as raised:
        spec.check_anchor_coverage(partial)

    message = str(raised.value)
    assert message.startswith("case spec quill-1:")
    missing = ["R-3", "R-4", "R-5", "R-6", "R-7", "R-8", "AF-1", "AF-3"]
    assert re.search(", ".join(missing), message), message
    assert "AF-2" not in message


def test_row_8_coverage_holds_over_every_design_s_specs_before_anything_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    def spy(variant: str | None, places: Mapping[str, Place]) -> Laid:
        calls.append(variant)
        return lay_quill(variant, places)

    spied = dataclasses.replace(QUILL, lay=spy)
    module = SimpleNamespace(DESIGN=spied, SPECS=(CaseSpec("quill-1", spied, represents=("R-1",)),))
    monkeypatch.setattr(designs, "DESIGNS", (module,))

    with pytest.raises(CaseSpecError, match=r"^case spec quill-1: .*R-2.*AF-3"):
        generate.render_all()
    assert calls == []


def test_the_first_failing_row_names_the_spec() -> None:
    """A spec failing rows 2 and 3 is named by row 2."""
    unknown = Seed(LOCAL_JOINT, {"fastener": "screw_z"}, CURRENT)
    refused([case(seeds=(unknown, FIT, DRAWING))], r"screw_z")


def _every_anchor() -> tuple[str, ...]:
    return tuple(families.ANCHOR_FAMILY)


def test_row_9_a_name_outside_the_case_vocabulary_names_case_file_pointer_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    named = case(variant="named", represents=_every_anchor())
    monkeypatch.setattr(designs, "DESIGNS", (SimpleNamespace(DESIGN=QUILL, SPECS=(named,)),))

    with pytest.raises(CaseSpecError) as raised:
        generate.render_all()

    message = str(raised.value)
    assert message.startswith("case spec quill-1: ")
    assert "benchmarks/packages/quill-1/package.json" in message
    assert "/documents/1/custom_properties/Fictional Summary" in message
    assert "zorbex" in message


def test_row_9_names_offences_lists_every_offence() -> None:
    files = render.render_spec(case(variant="named"))

    offences = render.names_offences(files)

    assert offences == [
        (
            "quill-1",
            "benchmarks/packages/quill-1/package.json "
            "/documents/1/custom_properties/Fictional Summary: 'zorbex' is not in the case "
            "vocabulary (generator.md 8)",
        )
    ]
    assert render.names_offences(render.render_spec(case())) == []


def test_the_rms_group_words_are_the_words_of_the_rms_table_s_group_names() -> None:
    """Owner decision 54A: every compliant tree (`generator.md` 5.3) and R-7 lay the six group
    folders under the names RMS matches exactly (`checks/rms_types.yaml` `groups`). The generator
    may not import checks (section 9), so its committed list is held to the table here."""
    table_words = {
        word.lower() for name in load_table().groups for word in re.findall(r"[A-Za-z]+", name)
    }

    assert vocabulary.RMS_GROUP_WORDS == table_words
    assert vocabulary.RMS_GROUP_WORDS <= vocabulary.CASE_VOCABULARY


def test_row_10_a_path_outside_the_fictional_roots_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pathed = case(variant="pathed", represents=_every_anchor())
    monkeypatch.setattr(designs, "DESIGNS", (SimpleNamespace(DESIGN=QUILL, SPECS=(pathed,)),))

    with pytest.raises(CaseSpecError) as raised:
        generate.render_all()

    message = str(raised.value)
    assert message.startswith("case spec quill-1: ")
    assert "benchmarks/packages/quill-1/package.json" in message
    assert "/documents/1/path" in message
    assert "D:\\Fictional\\Vault\\EX-1101-01.SLDPRT" in message


def test_row_11_a_key_its_model_refuses_names_the_case() -> None:
    forbidden = Forbidden(checks=("rms.*",), tag=TunedOn("R-1"), description="Nothing named.")

    with pytest.raises(CaseSpecError, match=r"^case spec quill-1: .*FB-1 names no parts"):
        render.render_spec(case(forbidden=(forbidden,)))


def test_a_condition_names_a_kind_or_a_check_never_both() -> None:
    with pytest.raises(ValueError, match="kind.*check"):
        Condition(
            kind=LOCAL_FIT,
            at={"bore": "bore", "shaft": "shaft"},
            check="fit.size_only",
            tag=TunedOn("R-3"),
            description="Both.",
        )
    with pytest.raises(ValueError, match="kind.*check"):
        Condition(tag=TunedOn("R-3"), description="Neither.")


# --- 2. seed kinds, section 3 -----------------------------------------------------------------

M, C = "model", "code"
DEM, SUS, UNR = "demonstrated", "suspected", "unresolved"
PLACEMENT, ABSENT, SOURCE, DRAWN = (
    "joint_placement",
    "joint_absent",
    "tolerance_source",
    "drawing_only",
)
KIND_ROWS: dict[str, tuple[str, str, str | None, tuple[str, ...]]] = {
    # the core kinds, generator.md 3's table
    "thread_mismatch_unplaced": ("fastener.thread_match", M, DEM, (PLACEMENT,)),
    "bottoming_unplaced": ("fastener.bottoming", M, DEM, (PLACEMENT,)),
    "engagement_unplaced": ("fastener.engagement", M, DEM, (PLACEMENT,)),
    "coaxiality_drawn": ("hole.coaxiality", M, DEM, (ABSENT, SOURCE)),
    "coaxiality_undrawn": ("hole.coaxiality", M, UNR, (ABSENT,)),
    "fit_transition": ("fit.size_only", M, SUS, (SOURCE, DRAWN)),
    "fit_interference_unintended": ("fit.size_only", M, SUS, (SOURCE, DRAWN)),
    "fit_limit_missing": ("fit.size_only", M, UNR, (SOURCE, DRAWN)),
    "stack_out_of_gap": ("stack.worst_case", M, DEM, (SOURCE, DRAWN)),
    "callout_drill_only": ("drawing.manufacturing_inputs", M, UNR, (DRAWN,)),
    "callout_thread_differs": ("drawing.manufacturing_inputs", M, SUS, (DRAWN,)),
    "callout_count_differs": ("drawing.manufacturing_inputs", M, SUS, (DRAWN,)),
    # the anchor kinds, as T129 fixes them
    "press_fit_drawn": ("fit.size_only", M, SUS, (SOURCE, DRAWN)),
    "press_fit_undrawn": ("fit.size_only", M, UNR, (SOURCE, DRAWN)),
    "slip_fit": ("fit.size_only", M, None, (SOURCE, DRAWN)),
    "interference_positive": ("interference.static", C, DEM, ()),
    "alignment_offset_placed": ("hole.nominal_alignment", C, DEM, ()),
    "thread_mismatch_placed": ("fastener.thread_match", C, DEM, ()),
    "revision_missing": ("hygiene.revision_present", C, DEM, ()),
    "component_lightweight": ("hygiene.component_not_resolved", C, DEM, ()),
    "rms.sketches.fully_defined": ("rms.sketches.fully_defined", C, DEM, ()),
    "standards.part.sketches_fully_defined": ("standards.part.sketches_fully_defined", C, DEM, ()),
    "rms.grouping.all_features_in_a_group": ("rms.grouping.all_features_in_a_group", C, DEM, ()),
    "rms.params.global_variables_present": ("rms.params.global_variables_present", C, DEM, ()),
    "bottoming_thread_depth_unknown": ("fastener.bottoming", M, UNR, (PLACEMENT,)),
}
"""Every kind of `generator.md` 3: its check, producer, expected status and withheld evidence."""

KINDS = list(KIND_ROWS)
R7_KINDS = [name for name in KINDS if name.startswith(("rms.", "standards."))]
NO_CLEAN_FORM = [
    "press_fit_drawn",
    "press_fit_undrawn",
    "interference_positive",
    "alignment_offset_placed",
    "thread_mismatch_placed",
    "revision_missing",
    "component_lightweight",
    "bottoming_thread_depth_unknown",
]
BOTH_FORMS = [name for name in KINDS if name not in NO_CLEAN_FORM and name != "slip_fit"]

FIT_AT = {"bore": "bore", "shaft": "shaft"}
SIBLING_FIT_AT = {**FIT_AT, "sibling_bore": "sibling_bore", "sibling_shaft": "sibling_shaft"}
JOINT_AT = {"fastener": "screw_a", "sibling": "screw_b"}
PAIR_AT = {"a": "pair_a", "b": "pair_b", "other_a": "other_a", "other_b": "other_b"}
CALLOUT_AT = {"callout": "callout", "hole": "tap_a"}
KIND_AT: dict[str, dict[str, str]] = {
    "thread_mismatch_unplaced": JOINT_AT,
    "bottoming_unplaced": JOINT_AT,
    "engagement_unplaced": JOINT_AT,
    "coaxiality_drawn": {**PAIR_AT, "tolerance": "tolerance"},
    "coaxiality_undrawn": PAIR_AT,
    "fit_transition": SIBLING_FIT_AT,
    "fit_interference_unintended": SIBLING_FIT_AT,
    "fit_limit_missing": SIBLING_FIT_AT,
    "stack_out_of_gap": {
        "enclosing": "enclosing",
        "inside_1": "inside_1",
        "inside_2": "inside_2",
        "target": "target",
    },
    "callout_drill_only": CALLOUT_AT,
    "callout_thread_differs": CALLOUT_AT,
    "callout_count_differs": CALLOUT_AT,
    "press_fit_drawn": FIT_AT,
    "press_fit_undrawn": FIT_AT,
    "slip_fit": FIT_AT,
    "interference_positive": {"a": "pin_b", "b": "cover"},
    "alignment_offset_placed": {"pin": "pin_b", "seat": "dowel_b", "hole": "cdowel_b"},
    "thread_mismatch_placed": {"fastener": "screw_a"},
    "revision_missing": {"component": "plate"},
    "component_lightweight": {"component": "pin_a"},
    **{name: {"component": "plate"} for name in R7_KINDS},
    "bottoming_thread_depth_unknown": {"hole": "tap_a"},
}
"""Where each kind sits on `quill`: its roles to `quill`'s places."""


def design_for(name: str) -> Design:
    """`quill`, or `QUILL_TREED` for a kind that changes a custom part's feature tree."""
    return QUILL_TREED if name in R7_KINDS else QUILL


def test_the_registry_holds_exactly_the_contract_s_kinds() -> None:
    assert sorted(seeds.KINDS) == sorted(KINDS)
    assert all(kind.name == name for name, kind in seeds.KINDS.items())


@pytest.mark.parametrize("name", KINDS)
def test_each_kind_s_check_producer_status_and_withheld_evidence(name: str) -> None:
    kind = seeds.KINDS[name]

    row = (kind.check, kind.producer, kind.expected_status, kind.withheld)

    assert row == KIND_ROWS[name]


@pytest.mark.parametrize("name", KINDS)
def test_each_kind_s_family_is_family_of_its_check(name: str) -> None:
    kind = seeds.KINDS[name]

    assert kind.family == families.family_of(kind.check)


@pytest.mark.parametrize("name", KINDS)
def test_a_kind_withholds_evidence_exactly_when_the_model_produces_it(name: str) -> None:
    kind = seeds.KINDS[name]

    assert bool(kind.withheld) == (kind.producer == "model")


@pytest.mark.parametrize("name", KINDS)
def test_a_kind_s_check_is_exact_never_a_family(name: str) -> None:
    kind = seeds.KINDS[name]

    assert not is_family(kind.check)
    assert re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)*", kind.check)


@pytest.mark.parametrize("name", NO_CLEAN_FORM)
def test_the_kinds_with_no_clean_form_say_so(name: str) -> None:
    kind = seeds.KINDS[name]

    assert kind.clean is None
    assert kind.plant is not None


def test_slip_fit_is_clean_only() -> None:
    kind = seeds.KINDS["slip_fit"]

    assert kind.plant is None
    assert kind.clean is not None


@pytest.mark.parametrize("name", R7_KINDS)
def test_the_r7_kinds_take_the_status_their_rule_s_registered_severity_maps_to(name: str) -> None:
    """`checks/rms/registry.py:72`; `checks/rules/results.py:67-68`; `answer-key.md` 7.2: the
    kinds are data, so this test holds them to the registries they cannot import."""
    registry = rms_registry if name.startswith("rms.") else standards_registry
    family = registry.RMS_FAMILY if name.startswith("rms.") else registry.STANDARDS_FAMILY
    rule = registry.RULES[name]
    assert rule.severity is not None

    status, _ = family.status_by_severity[rule.severity]

    assert seeds.KINDS[name].expected_status == status


@pytest.mark.parametrize("name", KINDS)
def test_each_kind_sits_on_quill_through_the_spec_checks(name: str) -> None:
    kind = seeds.KINDS[name]
    if kind.plant is None:
        condition = Condition(
            kind=kind,
            at=KIND_AT[name],
            tag=TunedOn("R-3"),
            description="A clean form keyed as a correct condition.",
        )
        spec.check_specs([case(design=design_for(name), conditions=(condition,))])
    else:
        seed = Seed(kind, KIND_AT[name], CURRENT)
        spec.check_specs([case(design=design_for(name), seeds=(seed,))])


@pytest.mark.parametrize("name", BOTH_FORMS)
def test_a_kind_s_planted_and_clean_forms_key_the_same_check_and_references(name: str) -> None:
    seed = Seed(seeds.KINDS[name], KIND_AT[name], CURRENT)
    files = render.render_spec(case(design=design_for(name), seeds=(seed,), twin=True))
    [defect] = key_of(files, "quill-1").known_defects
    [condition] = key_of(files, "quill-1-twin").correct_conditions

    def keyed(entry: Any) -> tuple[Any, ...]:
        references = (
            None
            if entry.references is None
            else [element.model_dump() for element in entry.references]
        )
        return (entry.check, entry.component_ids, entry.document_ids, references)

    assert keyed(condition) == keyed(defect)
    assert condition.description.startswith("clean twin of quill-1 D-1: ")


@pytest.mark.parametrize(
    ("flags", "fails"),
    [
        ({}, []),
        (
            {"sketches_defined": False},
            ["rms.sketches.fully_defined", "standards.part.sketches_fully_defined"],
        ),
        ({"grouped": False}, ["rms.grouping.all_features_in_a_group"]),
        ({"global_variable": False}, ["rms.params.global_variables_present"]),
    ],
)
def test_tree_specs_lays_a_compliant_tree_and_each_flag_fails_only_its_rule(
    flags: dict[str, bool], fails: list[str]
) -> None:
    """The R-7 kinds' forms are `Tree` flags, so what `spec.tree_specs` lays is their meaning:
    through the real RMS part and equation tools and the standards part checks over the example
    profile, the compliant tree raises nothing on the custom part (`generator.md` 5.3), and each
    flag cleared raises its rules, nothing beside them. Every sketch's text is read, so the
    standards sketch check decides it rather than leaving it unresolved."""
    places = {**QUILL_TREED.places, "plate_doc": DocumentPlace(tree=Tree(**flags))}
    laid = dataclasses.replace(QUILL_TREED, places=places).build(None, [])
    context = context_for(laid.package)
    [plate] = [
        document
        for document in graded_documents(laid.package, PROFILE)
        if document.document_id == laid.ids["plate_doc"]
    ]

    with use_context(context):
        rms_checks.check_rms_part()
        rms_checks.check_rms_equations()
    standards = evaluate_part(plate, laid.package, PROFILE)

    raised = sorted(
        [
            *(
                finding.check
                for finding in context.require_session().findings
                if laid.ids["plate"] in finding.component_ids
                and finding.status in ("demonstrated", "suspected")
            ),
            *(result.rule_id for result in standards if result.outcome == "fail"),
        ]
    )
    assert raised == fails
    sketches = {
        result.outcome
        for result in standards
        if result.rule_id == "standards.part.sketches_fully_defined"
    }
    assert sketches == ({"fail"} if "standards.part.sketches_fully_defined" in fails else {"pass"})


@pytest.mark.parametrize("name", R7_KINDS)
def test_a_treed_case_and_its_twin_pass_the_names_check(name: str) -> None:
    """Owner decision 54A: a custom part's tree, its group folders `1-Ref` to `6-Quarantine` and
    an R-7 form's features, carries names of the case vocabulary only, planted and clean."""
    seed = Seed(seeds.KINDS[name], KIND_AT[name], TunedOn("R-7"), represents="R-7")

    files = render.render_spec(
        case(design=QUILL_TREED, seeds=(seed,), represents=("R-7",), twin=True)
    )

    groups = {"1-Ref", "2-Construction", "3-Core", "4-Detail", "5-Modify", "6-Quarantine"}
    for case_id in ("quill-1", "quill-1-twin"):
        package = package_of(files, case_id)
        assert groups <= {row.name for row in package.features}
        # the names check reads no equation, so the trees' global variables are held here
        variables = [row.lhs for row in package.equations if row.is_global]
        assert variables
        assert [name for name in variables if vocabulary.name_offences(name)] == []
    assert render.names_offences(files) == []


def test_alignment_offset_placed_is_keyed_by_the_joint_s_hole_instances() -> None:
    """The joint map's alignment result names the joint's hole instances (`answer-key.md` 2.5):
    the pin's seat and the offset clearance hole, each a one-instance feature."""
    seed = Seed(seeds.KINDS["alignment_offset_placed"], KIND_AT["alignment_offset_placed"], CURRENT)

    files = render.render_spec(case(seeds=(seed,), represents=("AF-2",)))

    [defect] = key_of(files, "quill-1").known_defects
    package = package_of(files, "quill-1")
    seat, hole = package.holes[5].id, package.holes[7].id  # dowel_b, cdowel_b
    assert [element.model_dump() for element in defect.references or []] == [
        {"hole_instances": [f"{seat}#1", f"{hole}#1"]}
    ]
    assert package.holes[7].axis.origin.x * 1000 == pytest.approx(60.75)


def test_a_clean_only_kind_keys_its_clean_form_as_a_correct_condition() -> None:
    condition = Condition(
        kind=seeds.KINDS["slip_fit"],
        at=FIT_AT,
        tag=TunedOn("R-3"),
        description="A 3.0 mm pin in a 3.1 mm hole with slip-fit limits.",
    )

    files = render.render_spec(case(conditions=(condition,), represents=("R-3",)))

    [keyed] = key_of(files, "quill-1").correct_conditions
    package = package_of(files, "quill-1")
    drawing = package.design.drawing_document_ids[0]
    assert keyed.check == "fit.size_only"
    assert keyed.document_ids == [drawing]
    assert [element.model_dump() for element in keyed.references or []] == [
        {
            "bore": {"document_id": drawing, "sheet": "Sheet1", "annotation": "dim-1-1"},
            "shaft": {"document_id": drawing, "sheet": "Sheet1", "annotation": "dim-1-2"},
        }
    ]


CBT_ROW: dict[str, Place] = {
    **QUILL_PLACES,
    "tap_a": HolePlace(component="plate", thread="M6x1.0", hole_depth_mm=14.0, count=4),
}
"""`quill` with `cover-blind-tap`'s tapped-hole row in `tap_a` (`cases.md` 6.4): four M6x1.0
instances drilled 14 deep, no thread depth. Only the hole's record is `cover-blind-tap`'s: `quill`'s
lay keeps its own hole geometry and `screw_a`, which neither kind below reads the thread of."""


def test_a_drill_only_callout_sits_on_a_hole_row_with_no_thread_depth() -> None:
    """`cover-blind-tap`'s D-1 and D-2 on its one tapped-hole row (`cases.md` 6.4; T144): D-1's
    plant leaves the row's thread depth out, and D-2's callout, which reads only the row's thread,
    count and drill depth, states the drill depth alone; neither its words nor its call claim a
    thread depth the model does not carry."""
    tuned_on = TunedOn("prompt-encodes-cbt-answer")
    depth_unknown = Seed(seeds.KINDS["bottoming_thread_depth_unknown"], {"hole": "tap_a"}, tuned_on)
    drill_only = Seed(seeds.KINDS["callout_drill_only"], CALLOUT_AT, tuned_on)
    source = case(
        design=dataclasses.replace(QUILL, places=CBT_ROW),
        seeds=(depth_unknown, drill_only),
        sets=("pilot",),
    )

    spec.check_specs([source])
    files = render.render_spec(source)
    calls = render.correct_calls(source)

    package = package_of(files, "quill-1")
    texts = {
        (row.source.document_id, row.source.sheet, row.source.annotation): row.text_as_read
        for sheet in package.drawings
        for row in sheet.dimensions
    }
    assert package.holes[0].thread_depth is None
    assert "4X M6x1.0 - 6H DRILL ↧ 14" in texts.values()
    d1, d2 = key_of(files, "quill-1").known_defects
    assert (d1.check, d2.check) == ("fastener.bottoming", "drawing.manufacturing_inputs")
    assert d2.description == "the part drawing's tapped-hole callout states the drill depth only"
    assert [call.tool for call in calls] == ["check_fastener_joint", "record_drawing_finding"]
    record = calls[1].arguments
    [callout] = record["source_refs"]
    assert texts[(callout["document_id"], callout["sheet"], callout["annotation"])] == (
        "4X M6x1.0 - 6H DRILL ↧ 14"
    )
    assert record["document_id"] == callout["document_id"] == d2.document_ids[0]
    assert record["observed"] == (
        "The tapped-hole callout '4X M6x1.0 - 6H DRILL ↧ 14' states a drill depth and no thread "
        "depth."
    )
    assert record["status"] == "unresolved"


@pytest.mark.parametrize(
    "form",
    [seeds.FULL_CALLOUT, seeds.CALLOUT_THREAD_DIFFERS.plant, seeds.CALLOUT_COUNT_DIFFERS.plant],
    ids=["clean", "thread_differs", "count_differs"],
)
def test_a_callout_stating_a_thread_depth_refuses_a_hole_with_none(form: Form) -> None:
    """The callouts that state a thread depth (every drawing kind's clean form, and a thread or
    a count that differs) state the model hole's, so a hole row with none refuses them."""
    with pytest.raises(
        ValueError, match=r"^tap_a carries no usable thread depth for its callout to state$"
    ):
        form.apply(CALLOUT_AT, CBT_ROW)


def test_a_drill_only_twin_on_a_hole_with_no_thread_depth_is_refused_naming_the_twin() -> None:
    """A core case's twin states the thread depth, so a drill-only seed sits only on a hole row
    that carries one: the twin refuses, naming itself."""
    seed = Seed(seeds.KINDS["callout_drill_only"], CALLOUT_AT, CURRENT)

    with pytest.raises(
        CaseSpecError, match=r"^case spec quill-1-twin: tap_a carries no usable thread depth"
    ):
        render.render_spec(
            case(design=dataclasses.replace(QUILL, places=CBT_ROW), seeds=(seed,), twin=True)
        )


def test_a_callout_refuses_a_hole_with_no_thread() -> None:
    drill_only = seeds.KINDS["callout_drill_only"].plant
    assert drill_only is not None

    with pytest.raises(ValueError, match=r"^dowel_a is no tapped hole to call out$"):
        drill_only.apply({"callout": "callout", "hole": "dowel_a"}, QUILL_PLACES)


# --- 3. twins, section 4 ----------------------------------------------------------------------


def test_twin_derives_the_clean_case_with_one_condition_per_seed() -> None:
    source = case(
        seeds=(JOINT_A, FIT),
        twin=True,
        decoys=(
            ToolCall(
                "check_fit",
                {
                    "bore_dimension_ref": PlaceName("sibling_bore"),
                    "shaft_dimension_ref": PlaceName("sibling_shaft"),
                },
            ),
        ),
    )

    derived = spec.twin(source)

    assert derived.case_id == "quill-1-twin"
    assert derived.design is source.design
    assert derived.variant == source.variant
    assert derived.seeds == ()
    assert derived.decoys == ()
    assert derived.twin is False
    assert derived.sets == source.sets
    assert [(item.kind, dict(item.at), item.tag) for item in derived.conditions] == [
        (LOCAL_JOINT, {"fastener": "screw_a"}, CURRENT),
        (LOCAL_FIT, {"bore": "bore", "shaft": "shaft"}, CURRENT),
    ]
    assert [item.description for item in derived.conditions] == [
        "clean twin of quill-1 D-1: the screw's thread equals its hole's",
        "clean twin of quill-1 D-2: clearance limits",
    ]


def test_a_rendered_twin_keys_each_seed_s_check_references_tag_and_stamp() -> None:
    files = render.render_spec(case(seeds=(JOINT_A, FIT), twin=True))

    defects = key_of(files, "quill-1").known_defects
    twin = key_of(files, "quill-1-twin")
    assert twin.known_defects == []
    assert [item.id for item in twin.correct_conditions] == ["C-1", "C-2"]
    for defect, condition in zip(defects, twin.correct_conditions, strict=True):
        assert condition.check == defect.check
        assert condition.references == defect.references
        assert condition.component_ids == defect.component_ids
        assert condition.tag == "held_out"
        assert condition.held_out_against == stamps.CURRENT
    assert twin.holds_held_out()


def test_a_twin_carries_the_kind_s_correct_call_but_a_drawing_kind_s() -> None:
    joint_twin = spec.twin(case(seeds=(JOINT_A, DRAWING), twin=True))

    calls = render.correct_calls(joint_twin)

    assert [call.tool for call in calls] == ["check_fastener_joint"]


CONFIRMS_NOTHING = [
    "coaxiality_undrawn",
    "callout_drill_only",
    "callout_thread_differs",
    "callout_count_differs",
]
"""The kinds whose correct calls cannot confirm their clean form, so a condition of theirs carries
none (`generator.md` 4): the drawing kinds and, by owner decision 55A, `coaxiality_undrawn`."""


def test_the_kinds_whose_calls_cannot_confirm_their_clean_form_say_so() -> None:
    unconfirmed = [name for name, kind in seeds.KINDS.items() if not kind.confirms_clean]

    assert unconfirmed == CONFIRMS_NOTHING


def test_a_drawing_kind_confirming_its_clean_form_is_refused() -> None:
    """A correct reviewer records nothing on a complete drawing, so no drawing kind's call can
    confirm its clean form (`generator.md` 4)."""
    with pytest.raises(ValueError, match=r"seed kind local_drawing: .*drawing kind"):
        dataclasses.replace(LOCAL_DRAWING, confirms_clean=True)


def test_coaxiality_undrawn_s_call_writes_unresolved_on_its_clean_form() -> None:
    """Why it confirms nothing (55A): with no tolerance drawn, `check_hole_alignment` measures
    the offset and writes unresolved, on aligned holes too (`checks/hole_alignment.py:98-101`)."""
    clean = seeds.KINDS["coaxiality_undrawn"].clean
    assert clean is not None
    laid = QUILL.build(None, [(clean, PAIR_AT)])
    context = context_for(laid.package)

    with use_context(context):
        checks_fastener.check_hole_alignment(str(laid.ids["pair_a"]), str(laid.ids["pair_b"]))

    [finding] = context.require_session().findings
    assert (finding.check, finding.status) == ("hole.coaxiality", "unresolved")


def test_a_coaxiality_undrawn_twin_condition_carries_no_correct_call_and_is_still_keyed() -> None:
    """55A: the case's seed is called, its twin's condition is not, so validation leg (b) rule 4
    never asks the condition to confirm; it is keyed all the same, so a finding contradicting it
    is still caught."""
    seed = Seed(seeds.KINDS["coaxiality_undrawn"], PAIR_AT, CURRENT)
    source = case(seeds=(seed,), twin=True)

    assert [call.tool for call in render.correct_calls(source)] == ["check_hole_alignment"]
    assert render.correct_calls(spec.twin(source)) == []
    [condition] = key_of(render.render_spec(source), "quill-1-twin").correct_conditions
    assert condition.check == "hole.coaxiality"


def test_twin_refuses_a_kind_with_no_clean_form() -> None:
    code = Seed(LOCAL_CODE, {"a": "pin_b", "b": "cover"}, TunedOn("R-4"))

    with pytest.raises(CaseSpecError, match=r"^case spec quill-1: D-1 .*no clean form"):
        spec.twin(case(seeds=(code,), twin=True))


# --- 4. the render format, section 7 ----------------------------------------------------------

ANSWERED = case(
    seeds=(JOINT_A, FIT),
    twin=True,
    forbidden=(
        Forbidden(
            checks=("rms.*", "hygiene.*"),
            component_ids=("pin_a", "pin_b"),
            tag=TunedOn("R-1"),
            description="No modelling finding on the bought pin.",
        ),
    ),
    expected_coverage=(
        Coverage(
            item="interference",
            statuses=("unresolved", "skipped"),
            tag=TunedOn("R-5"),
            description="Nothing of the pins was read.",
        ),
    ),
    unanswerable_requests=(
        Unanswerable(
            documents=("pin_doc",), tag=TunedOn("R-2"), description="The bought pin has no drawing."
        ),
    ),
    question_counts=(
        QuestionCount(
            part_roles=True,
            min=1,
            max=1,
            tag=TunedOn("R-1"),
            description="The part-roles question is asked once.",
        ),
        QuestionCount(
            item="interfaces.fit",
            ids=("pin_a",),
            max=1,
            tag=TunedOn("R-3"),
            description="The fit question is asked at most once, Ø3.",
        ),
    ),
    answers=(
        Answer(part_roles=True, answer="All bought"),
        Answer(item="interfaces.fit", ids=("pin_a", "plate"), answer="press fit"),
        Answer(item=None, ids=("plate_doc",), answer="no drawing ±"),
    ),
    represents=("R-1", "R-3"),
)


def test_render_spec_writes_the_case_s_and_its_twin_s_files_at_their_paths() -> None:
    files = render.render_spec(ANSWERED)

    for case_id in ("quill-1", "quill-1-twin"):
        assert f"benchmarks/packages/{case_id}/package.json" in files
        assert f"benchmarks/answer_keys/{case_id}.json" in files
        meshes = [
            path for path in files if path.startswith(f"benchmarks/packages/{case_id}/meshes/")
        ]
        assert meshes and all(path.endswith(".glb") for path in meshes)
    assert "benchmarks/case_files/quill-1.json" in files
    assert "benchmarks/case_files/quill-1-twin.json" not in files
    assert all("\\" not in path and not path.startswith("/") for path in files)


def test_a_case_with_no_answers_has_no_case_file() -> None:
    files = render.render_spec(case(seeds=(JOINT_A,)))

    assert not [path for path in files if path.startswith("benchmarks/case_files/")]


@pytest.mark.parametrize(
    "path",
    [
        "benchmarks/packages/quill-1/package.json",
        "benchmarks/answer_keys/quill-1.json",
        "benchmarks/case_files/quill-1.json",
        "benchmarks/answer_keys/quill-1-twin.json",
    ],
)
def test_every_rendered_json_is_utf8_lf_indented_2_with_a_final_newline(path: str) -> None:
    content = render.render_spec(ANSWERED)[path]

    text = content.decode("utf-8")
    assert b"\r" not in content
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text.startswith('{\n  "')
    if path.endswith("package.json"):
        # `Built.render()`'s bytes, pydantic's own JSON, as the mechanical fixtures are committed
        package = EvidencePackage.model_validate_json(text)
        assert package.model_dump_json(indent=2) + "\n" == text
    else:
        assert json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n" == text


def test_non_ascii_is_written_as_itself() -> None:
    files = render.render_spec(ANSWERED)

    assert "Ø3" in files["benchmarks/answer_keys/quill-1.json"].decode("utf-8")
    assert "±" in files["benchmarks/case_files/quill-1.json"].decode("utf-8")
    assert b"\\u00" not in files["benchmarks/answer_keys/quill-1.json"]
    assert b"\\u00" not in files["benchmarks/case_files/quill-1.json"]


def test_the_key_validates_through_its_model_with_every_list_in_spec_order() -> None:
    files = render.render_spec(ANSWERED)

    key = key_of(files, "quill-1")
    package = package_of(files, "quill-1")
    ids = {component.name: component.id for component in package.components}
    assert key.key_format == 2
    assert key.package_id == "quill-1"
    assert [item.id for item in key.known_defects] == ["D-1", "D-2"]
    assert [(item.check, item.producer, item.expected_status) for item in key.known_defects] == [
        ("fastener.thread_match", "model", "demonstrated"),
        ("fit.size_only", "model", "suspected"),
    ]
    assert all(item.held_out_against == stamps.CURRENT for item in key.known_defects)
    assert [item.id for item in key.forbidden] == ["FB-1"]
    assert key.forbidden[0].component_ids == [
        ids["FICT-PIN-3X20-0001-1"],
        ids["FICT-PIN-3X20-0001-2"],
    ]
    assert key.forbidden[0].held_out_against is None
    assert [item.id for item in key.expected_coverage] == ["CV-1"]
    assert [item.id for item in key.unanswerable_requests] == ["U-1"]
    assert [item.id for item in key.question_counts] == ["Q-1", "Q-2"]
    assert key.question_counts[1].ids == [ids["FICT-PIN-3X20-0001-1"]]


def test_a_reference_s_owner_is_among_the_entry_s_parts_and_documents() -> None:
    """`answer-key.md` 4 row 14: a joint names the screw's and the hole's components, a fit the
    drawing document its dimensions sit on."""
    files = render.render_spec(case(seeds=(JOINT_A, FIT)))
    package = package_of(files, "quill-1")
    joint, fit = key_of(files, "quill-1").known_defects

    [element] = joint.references or []
    fastener = next(row for row in package.fasteners if row.id == element.fastener)  # type: ignore[union-attr]
    hole = next(row for row in package.holes if row.id == element.hole)  # type: ignore[union-attr]
    assert joint.component_ids == [fastener.component_id, hole.component_id]
    assert joint.document_ids == []
    assert fit.component_ids == []
    assert fit.document_ids == [package.design.drawing_document_ids[0]]


def test_the_case_file_validates_through_its_model_in_each_entry_s_own_shape() -> None:
    files = render.render_spec(ANSWERED)
    package = package_of(files, "quill-1")
    ids = {component.name: component.id for component in package.components}

    written = rendered_json(files, "benchmarks/case_files/quill-1.json")
    case_file = CaseFile.model_validate(written)

    assert case_file.package_id == "quill-1"
    assert written["answers"] == [
        {"id": "A-1", "part_roles": True, "answer": "All bought"},
        {
            "id": "A-2",
            "item": "interfaces.fit",
            "ids": [ids["FICT-PIN-3X20-0001-1"], ids["EX-1101-01-1"]],
            "answer": "press fit",
        },
        {
            "id": "A-3",
            "item": None,
            "ids": [package.documents[1].document_id],
            "answer": "no drawing ±",
        },
    ]


def test_the_ir_identity_is_the_case_s() -> None:
    files = render.render_spec(ANSWERED)

    for case_id in ("quill-1", "quill-1-twin"):
        package = package_of(files, case_id)
        assert package.package_id == uuid5(CASE_NAMESPACE, case_id)
        assert package.design.design_id == case_id
        assert package.schema_version == render.CASE_SCHEMA_VERSION == "1.6.0"
        assert package.created_at == CREATED_AT
        assert package.design.name == ROOT_STEM


def test_set_entries_name_key_and_design_with_held_out_derived_from_the_key() -> None:
    entries = render.set_entries(ANSWERED)
    files = render.render_spec(ANSWERED)

    entry, twin = entries
    assert entry.package_id == "quill-1"
    assert entry.path == REPO_ROOT / "benchmarks" / "packages" / "quill-1"
    assert entry.key == REPO_ROOT / "benchmarks" / "answer_keys" / "quill-1.json"
    assert entry.case_file == REPO_ROOT / "benchmarks" / "case_files" / "quill-1.json"
    assert entry.design == "quill"
    assert entry.represents == ["R-1", "R-3"]
    assert entry.twin_of is None
    assert entry.held_out is key_of(files, "quill-1").holds_held_out() is True
    assert twin.package_id == "quill-1-twin"
    assert twin.twin_of == "quill-1"
    assert twin.case_file is None
    assert twin.represents is None
    assert twin.held_out is key_of(files, "quill-1-twin").holds_held_out() is True


def test_a_set_entry_of_a_case_holding_nothing_out_is_not_held_out() -> None:
    tuned = dataclasses.replace(JOINT_A, tag=TunedOn("R-6"))

    [entry] = render.set_entries(case(seeds=(tuned,)))

    assert entry.held_out is False


def test_set_entries_through_file_form_omit_absent_fields_and_hold_no_digest() -> None:
    written = json.loads(
        BenchmarkSet(name="committed", packages=render.set_entries(ANSWERED)).file_form()
    )

    assert written["packages"] == [
        {
            "package_id": "quill-1",
            "path": "benchmarks/packages/quill-1",
            "key": "benchmarks/answer_keys/quill-1.json",
            "case_file": "benchmarks/case_files/quill-1.json",
            "held_out": True,
            "design": "quill",
            "represents": ["R-1", "R-3"],
        },
        {
            "package_id": "quill-1-twin",
            "path": "benchmarks/packages/quill-1-twin",
            "key": "benchmarks/answer_keys/quill-1-twin.json",
            "held_out": True,
            "design": "quill",
            "twin_of": "quill-1",
        },
    ]


def test_set_files_write_committed_pilot_and_pane_smoke_in_spec_order() -> None:
    kalo_1 = case("kalo-1", seeds=(JOINT_A,), twin=True)
    kalo_fit_1 = case("kalo-fit-1", represents=("R-3",))
    tuned = dataclasses.replace(JOINT_A, tag=TunedOn("prompt-encodes-cbt-answer"))
    cover = case("cover-blind-tap", seeds=(tuned,), sets=("pilot",))
    specs = [kalo_1, kalo_fit_1, cover]

    files = render.set_files([(item, render.set_entries(item)) for item in specs])

    assert sorted(files) == [
        "benchmarks/sets/committed.json",
        "benchmarks/sets/pane-smoke.json",
        "benchmarks/sets/pilot.json",
    ]
    committed = json.loads(files["benchmarks/sets/committed.json"])
    smoke = json.loads(files["benchmarks/sets/pane-smoke.json"])
    pilot = json.loads(files["benchmarks/sets/pilot.json"])
    assert committed["name"] == "committed"
    assert [item["package_id"] for item in committed["packages"]] == [
        "kalo-1",
        "kalo-1-twin",
        "kalo-fit-1",
    ]
    assert smoke["name"] == "pane-smoke"
    assert smoke["packages"] == [committed["packages"][0], committed["packages"][2]]
    assert render.PANE_SMOKE_CASES == ("kalo-1", "kalo-fit-1")
    assert pilot == {
        "name": "pilot",
        "packages": [
            {
                "package_id": "cover-blind-tap",
                "path": "benchmarks/packages/cover-blind-tap",
                "key": "benchmarks/answer_keys/cover-blind-tap.json",
                "held_out": False,
                "design": "quill",
            }
        ],
    }
    for content in files.values():
        assert content.endswith(b"}\n") and b"\r" not in content
        assert b"case_file_sha256" not in content


def test_render_spec_is_deterministic() -> None:
    """Two renders of one spec are byte-equal; the regeneration test (T146) holds the clock."""
    assert render.render_spec(ANSWERED) == render.render_spec(ANSWERED)


# --- 5. the place-name resolver ----------------------------------------------------------------


def test_the_resolver_turns_every_kind_of_place_into_its_id() -> None:
    laid = QUILL.build(None, [])
    package = laid.package

    resolved = render.resolve(
        {
            "component": PlaceName("plate"),
            "document": PlaceName("plate_doc"),
            "hole": PlaceName("tap_a"),
            "instance": PlaceName("tap_a", instance=1),
            "fastener": PlaceName("screw_a"),
            "dimension": [PlaceName("bore")],
            "words": "kept as written",
        },
        laid.ids,
    )

    assert resolved["component"] == package.components[0].id
    assert resolved["document"] == "doc:0002"
    assert resolved["hole"] == package.holes[0].id
    assert resolved["instance"] == f"{package.holes[0].id}#1"
    assert resolved["fastener"] == package.fasteners[0].id
    assert resolved["dimension"] == [
        {
            "document_id": package.design.drawing_document_ids[0],
            "sheet": "Sheet1",
            "annotation": "dim-1-1",
        }
    ]
    assert resolved["words"] == "kept as written"


def test_the_resolver_refuses_an_unknown_place_and_an_instance_of_a_dimension() -> None:
    laid = QUILL.build(None, [])

    with pytest.raises(ValueError, match="screw_z"):
        render.resolve(PlaceName("screw_z"), laid.ids)
    with pytest.raises(ValueError, match="bore.*instance"):
        render.resolve(PlaceName("bore", instance=1), laid.ids)


def test_correct_calls_and_decoys_resolve_in_seed_then_spec_order() -> None:
    spec_decoy = ToolCall(
        "check_fit",
        {"bore_dimension_ref": PlaceName("bore"), "shaft_dimension_ref": PlaceName("bore")},
    )
    source = case(seeds=(JOINT_A, FIT), decoys=(spec_decoy,))
    laid = QUILL.build(None, [])

    calls = render.correct_calls(source)
    decoys = render.decoy_calls(source)

    assert [call.tool for call in calls] == ["check_fastener_joint", "check_fit"]
    assert calls[0].arguments["clamped_component_ids"] == [laid.ids["cover"]]
    assert calls[1].arguments["bore_dimension_ref"]["annotation"] == "dim-1-1"
    assert [call.tool for call in decoys] == ["list_fasteners", "check_fit"]
    assert decoys[0].arguments == {"component_id": laid.ids["cover"]}
    assert decoys[1].arguments["shaft_dimension_ref"]["annotation"] == "dim-1-1"


def test_forms_apply_in_order_and_change_only_their_places() -> None:
    planted = QUILL.formed([(LOCAL_JOINT.plant, {"fastener": "screw_a"})])  # type: ignore[list-item]

    assert planted["screw_a"] == dataclasses.replace(
        QUILL_PLACES["screw_a"], thread="M4-0.7", seated=False
    )
    assert {name: record for name, record in planted.items() if name != "screw_a"} == {
        name: record for name, record in QUILL_PLACES.items() if name != "screw_a"
    }


def test_a_dimension_place_reads_as_drawn() -> None:
    assert (
        DimensionPlace(drawing="d", nominal_mm=3.0, limits=CLEARANCE_BORE, prefix="2X Ø").as_read()
        == "2X Ø3 +0.025/0"
    )
    assert (
        DimensionPlace(drawing="d", nominal_mm=40.0, limits=("bilateral", -0.009, -0.025)).as_read()
        == "40 -0.009/-0.025"
    )
    assert (
        DimensionPlace(drawing="d", nominal_mm=8.0, limits=("symmetric", 0.1)).as_read() == "8 ±0.1"
    )
    assert DimensionPlace(drawing="d", nominal_mm=3.0, limits=None, prefix="Ø").as_read() == "Ø3"
    assert (
        DimensionPlace(
            drawing="d", nominal_mm=14.0, limits=None, text="4X M6x1.0 - 6H DRILL ↧ 14"
        ).as_read()
        == "4X M6x1.0 - 6H DRILL ↧ 14"
    )


def test_an_as_written_nominal_keeps_the_drawing_s_digits() -> None:
    """Owner decision 56A: `nominal_text` writes the nominal as the drawing does, "3.0" where
    `:g` writes "3"; `text` still reads before it; it must read as the nominal, and a form that
    moves the nominal clears it."""
    bore = DimensionPlace(
        drawing="d", nominal_mm=3.0, limits=CLEARANCE_BORE, prefix="2X Ø", nominal_text="3.0"
    )

    assert bore.as_read() == "2X Ø3.0 +0.025/0"
    assert dataclasses.replace(bore, text="⌖ Ø0.1").as_read() == "⌖ Ø0.1"
    for written in ("3.5", "three", "", " 3.0", "+3.0", "3e0", "nan"):
        with pytest.raises(ValueError, match=r"nominal_text .* does not write its nominal 3 mm"):
            DimensionPlace(drawing="d", nominal_mm=3.0, limits=None, nominal_text=written)
    drill_only = seeds.KINDS["callout_drill_only"].plant
    assert drill_only is not None
    callout = dataclasses.replace(QUILL_PLACES["callout"], nominal_text="10.0")  # type: ignore[type-var]
    planted = drill_only.apply(CALLOUT_AT, {**QUILL_PLACES, "callout": callout})["callout"]
    assert isinstance(planted, DimensionPlace)
    assert (planted.nominal_mm, planted.nominal_text) == (12.0, None)


def test_the_kalo_fit_anchor_s_sheet_text_renders_exactly() -> None:
    """`cases.md` 6.3 pins `kalo-fit-1`'s sheet: a "2X Ø3.0 +0.010/0" bore over a pin
    "Ø3.0 +0.020/+0.014". `press_fit_drawn` rebuilds each text from its limits, and the
    as-written nominal keeps "3.0" (owner decision 56A)."""
    places = {
        **QUILL_PLACES,
        "bore": DimensionPlace(
            drawing="assy_drw",
            nominal_mm=3.0,
            limits=CLEARANCE_BORE,
            prefix="2X Ø",
            nominal_text="3.0",
        ),
        "shaft": DimensionPlace(
            drawing="assy_drw",
            nominal_mm=3.0,
            limits=CLEARANCE_SHAFT,
            prefix="Ø",
            nominal_text="3.0",
        ),
    }
    seed = Seed(seeds.KINDS["press_fit_drawn"], FIT_AT, TunedOn("R-3"), represents="R-3")

    files = render.render_spec(
        case(design=dataclasses.replace(QUILL, places=places), seeds=(seed,), represents=("R-3",))
    )

    [defect] = key_of(files, "quill-1").known_defects
    [element] = [item.model_dump() for item in defect.references or []]
    texts = {
        (row.source.document_id, row.source.sheet, row.source.annotation): row.text_as_read
        for sheet in package_of(files, "quill-1").drawings
        for row in sheet.dimensions
    }

    def drawn(ref: Mapping[str, str]) -> str:
        return texts[(ref["document_id"], ref["sheet"], ref["annotation"])]

    assert drawn(element["bore"]) == "2X Ø3.0 +0.010/0"
    assert drawn(element["shaft"]) == "Ø3.0 +0.020/+0.014"
    assert render.names_offences(files) == []


# --- 6. stale files and main, section 1 --------------------------------------------------------


def _checkout(root: Path, *paths: str) -> None:
    for path in paths:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"{}\n")


def test_stale_files_names_what_the_render_lacks_and_deletes_nothing(tmp_path: Path) -> None:
    _checkout(
        tmp_path,
        "benchmarks/packages/quill-1/package.json",
        "benchmarks/packages/gone-1/package.json",
        "benchmarks/packages/gone-1/meshes/bod-0001.glb",
        "benchmarks/answer_keys/gone-1.json",
        "benchmarks/answer_keys/rms-part.json",
        "benchmarks/packages/bracket-assy/package.json",
        "benchmarks/case_files/gone-1.json",
        "benchmarks/sets/old.json",
        "benchmarks/README.md",
        "benchmarks/native/rms-part/RECIPE.md",
    )
    before = sorted(path for path in tmp_path.rglob("*") if path.is_file())

    stale = generate.stale_files(tmp_path, {"benchmarks/packages/quill-1/package.json": b"{}\n"})

    assert stale == [
        f"stale: {path}: delete it or restore its spec"
        for path in [
            "benchmarks/answer_keys/gone-1.json",
            "benchmarks/case_files/gone-1.json",
            "benchmarks/packages/gone-1/meshes/bod-0001.glb",
            "benchmarks/packages/gone-1/package.json",
            "benchmarks/sets/old.json",
        ]
    ]
    assert sorted(path for path in tmp_path.rglob("*") if path.is_file()) == before


def test_main_writes_the_render_s_bytes_and_prints_each_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rendered = {"benchmarks/sets/pilot.json": b'{\n  "name": "pilot"\n}\n'}
    monkeypatch.setattr(generate, "render_all", lambda: rendered)

    assert generate.main(root=tmp_path) == 0

    assert (tmp_path / "benchmarks/sets/pilot.json").read_bytes() == rendered[
        "benchmarks/sets/pilot.json"
    ]
    assert capsys.readouterr().out.splitlines() == ["benchmarks/sets/pilot.json"]


def test_main_exits_1_on_a_stale_file_and_keeps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _checkout(tmp_path, "benchmarks/answer_keys/gone-1.json")
    monkeypatch.setattr(generate, "render_all", lambda: {"benchmarks/sets/pilot.json": b"{}\n"})

    assert generate.main(root=tmp_path) == 1

    assert capsys.readouterr().out.splitlines() == [
        "benchmarks/sets/pilot.json",
        "stale: benchmarks/answer_keys/gone-1.json: delete it or restore its spec",
    ]
    assert (tmp_path / "benchmarks/answer_keys/gone-1.json").exists()


def test_main_writes_nothing_when_a_spec_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> dict[str, bytes]:
        raise CaseSpecError("quill-1", "refused before anything renders")

    monkeypatch.setattr(generate, "render_all", refuse)

    with pytest.raises(CaseSpecError):
        generate.main(root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_designs_are_listed_in_order_each_a_stub_or_a_design() -> None:
    names = [module.DESIGN.name for module in designs.DESIGNS]

    assert names == [
        "kalo",
        "tessa",
        "okta",
        "brun",
        "pelin",
        "davo",
        "rusk",
        "lori",
        "venta",
        "mir",
        "cover",
    ]
    assert all(isinstance(module.SPECS, tuple) for module in designs.DESIGNS)
