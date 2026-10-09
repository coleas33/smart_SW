"""The pelin design (`cases.md` 6.2): a flange coupling: two flanges on a spigot, a bolt circle into
tapped holes.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom seat flange, fixed, a Ø100 disc on z = -20 to 0, sits on the end of a bought Ø20 shaft
in its hub bore and carries a Ø40 recess cut 8 mm down from its top face; the custom pilot flange,
a Ø100 disc on z = 0 to 12, locates on it by its Ø40 spigot, 5 mm long, in that recess, and is
screwed down by four bought M5 socket head screws through its M5 clearance holes into the seat
flange's four blind M5x0.8 tapped holes, on a bolt circle of Ø70. A bought Ø40 shim lies on the
recess floor, leaving the spigot 1 mm of end clearance over it, so the flanges seat face to face.
The recess, the spigot and the hub bore are cut and turned, not Hole Wizard holes. The pilot
flange is each screw's one clamped layer, a flat plate whose face boxes measure its 12 mm along
the screw (`tools/checks_fastener.py` `_bbox_extent_mm`): its only extracted faces, its clearance
holes', run through it from face to face, the spigot below it having none. Both flanges are
steel. Every name is the example profile's: the assembly and the two flanges `EX-1105-..` with
the data card, the revision, the hygiene number equal to the stem and a summary unique in the
package; the shaft, the shim and the screws bought, in the profile's bought folder with a vendor
property, each screw with its fastener row (GN-2). Each custom part carries `spec.tree_specs`'
compliant tree. No tolerance source anywhere (rule 4): the spigot's fit in the recess, the
shaft's in the hub bore and the spigot's end stack are drawn on the assembly's ingested sheet
only. The seat flange's own drawing draws its tapped-hole callout alone (rule 5). The
interference rows are zero-volume contacts: the shaft line to line in the hub bore, the shim on
the recess floor.

**Places** (rule 2): the documents `assy`, `seat_doc`, `pilot_doc`, `shaft_doc`, `shim_doc`,
`screw_doc` (the M5 x 20 screws'), `assy_drw` and `seat_drw`; the components `seat`, `pilot`,
`shaft` and `shim`; the Hole Wizard rows `taps` (the seat flange's tapped holes) under `clrs` (the
pilot flange's clearance holes), four instances each on the bolt circle; the fasteners `screw_a` to
`screw_d`, one into each instance of `taps`, `screw_b` the sibling joint of `screw_a` (rule 6); the
contacts `shaft_seat` and `shim_seat`; on the assembly's sheet the spigot fit, the recess
`recess_bore` over the spigot's diameter `spigot_dia`, and its sibling fit (rule 6), the hub bore
`hub_bore` over the shaft's diameter `shaft_dia`, drawn on two dimensions of their own, so a form
that strips the recess's tolerance leaves the sibling clean; the spigot's end stack: the recess's
depth `recess_depth`, the spigot's length `spigot_height` and the shim's width `shim_width` inside
it, and the end clearance `end_gap`, its target, the shim the contributor a decoy leaves out
(rule 6); and `callout`, the seat flange drawing's tapped-hole callout.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `pelin-1`: `thread_mismatch_unplaced` on `screw_a`, an M4-0.7 screw in the M5x0.8 `taps`, and
  `fit_limit_missing` on the spigot fit, the recess drawn with no tolerance over a toleranced
  spigot.
- `pelin-2`: `stack_out_of_gap` on the spigot's end stack, its three contributors toleranced wide
  enough that the worst-case band leaves the drawn end clearance, and `callout_thread_differs` on
  the seat flange's own drawing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from swreview.ir.models import SourceRef
from tests.benchmark_cases import seeds, stamps
from tests.benchmark_cases.spec import (
    CaseSpec,
    ComponentPlace,
    ContactPlace,
    Design,
    DimensionPlace,
    DocumentPlace,
    HeldOut,
    HolePlace,
    Laid,
    Place,
    Places,
    ScrewPlace,
    Seed,
    Tree,
    tree_specs,
)
from tests.benchmark_cases.vocabulary import EXAMPLE_PROFILE
from tests.support.drawings import Limits, SheetBuilder
from tests.support.features import PartSpec, part_trees
from tests.support.mechanical import (
    FICTIONAL_ROOT,
    STEEL_DENSITY_KG_M3,
    Face,
    Instance,
    PackageBuilder,
    cylinder_mesh,
    transform,
)
from tests.support.standards import card

# --- the shape -------------------------------------------------------------------------------

ASSY_STEM, SEAT_STEM, PILOT_STEM = "EX-1105-00", "EX-1105-01", "EX-1105-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the shaft, the shim and the screws bought (`generator.md`
5.2)."""

FLANGE_DIAMETER_MM = 100.0
SEAT_THICKNESS_MM = 20.0
PILOT_THICKNESS_MM = 12.0
"""The seat flange lies from z = -20 to 0, the pilot flange from 0 to 12: the pilot flange is the
stack each screw clamps."""

RECESS_DIAMETER_MM, RECESS_DEPTH_MM = 40.0, 8.0
SPIGOT_LENGTH_MM = 5.0
HUB_BORE_MM = 20.0
"""The seat flange's Ø40 recess, cut 8 mm down from its top face, and under it the Ø20 hub bore
the shaft sits in, through to its bottom face; the pilot flange's Ø40 spigot, 5 mm long below its
face. All cut or turned, not Hole Wizard holes."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary)
    # a Ø100 x 20 mm disc less its recess and the hub bore under it
    "seat_doc": (
        SEAT_STEM,
        round(
            math.pi
            / 4.0
            * (
                FLANGE_DIAMETER_MM**2 * SEAT_THICKNESS_MM
                - RECESS_DIAMETER_MM**2 * RECESS_DEPTH_MM
                - HUB_BORE_MM**2 * (SEAT_THICKNESS_MM - RECESS_DEPTH_MM)
            ),
            6,
        ),
        "pelin seat flange",
    ),
    # a Ø100 x 12 mm disc and its spigot under it
    "pilot_doc": (
        PILOT_STEM,
        round(
            math.pi
            / 4.0
            * (
                FLANGE_DIAMETER_MM**2 * PILOT_THICKNESS_MM
                + RECESS_DIAMETER_MM**2 * SPIGOT_LENGTH_MM
            ),
            6,
        ),
        "pelin pilot flange",
    ),
}
"""The custom parts, both steel, as a coupling's flanges are, their masses from their volumes."""

AXIS = (50.0, 50.0)
Z = (0.0, 0.0, 1.0)
"""The (x, y) of the coupling's axis; it, and every hole's axis, is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float]] = {
    # document place: (stem, description, diameter, length) in mm
    "shaft_doc": ("FICT-SHAFT-20X60-0001", "SHAFT, Ø20 X 60 MM, FICTIONAL", HUB_BORE_MM, 60.0),
    "shim_doc": ("FICT-SHIM-40X2-0001", "SHIM, Ø40 X 2 MM, FICTIONAL", RECESS_DIAMETER_MM, 2.0),
}
"""The bought round parts, steel; each a mesh with no extracted face, so the joint map, which
reads faces in hole instances, takes neither for a pin."""

ON_AXIS: dict[str, tuple[str, float]] = {
    # component place: (its document place, the z of its centre)
    "shaft": ("shaft_doc", -40.0),
    "shim": ("shim_doc", -7.0),
}
"""Each round component on the coupling's axis: the shaft from z = -70 to -10, up into the hub
bore, ending 2 mm under the recess floor; the shim on that floor, -8 to -6; the end clearance,
-6 to the spigot's end at -5."""

DRAWINGS: dict[str, tuple[str, str]] = {
    "assy_drw": (ASSY_STEM, "pelin assy drawing"),
    "seat_drw": (SEAT_STEM, "pelin seat flange drawing"),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary)."""

BOLT_AXES = ((85.0, 50.0), (50.0, 85.0), (15.0, 50.0), (50.0, 15.0))
"""The (x, y) of the bolt circle's four hole axes, all along z: 90 degrees apart on Ø70 about
the coupling's axis, clear of the recess's 20 mm radius and inside the flanges' 50 mm."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 20.0
"""The pilot flange's screws, all one document (`screw_doc`): M5 x 20 reaches 8 mm past the
flange, inside the 9 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives, so
a twin's screws are the base's."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""

STACK_LIMITS: Limits = ("symmetric", 0.05)
"""Each end-stack contributor's drawn tolerance in the base: three of them hold the end
clearance to 1 ± 0.15 mm, inside its drawn 1 ± 0.5 mm, so the stack is clean wherever no form
tolerances it (`seeds.STACK_OUT_OF_GAP` draws ± 0.34 mm each to plant, ± 0.083 mm in its clean
form)."""


@dataclass(frozen=True)
class HoleShape:
    """How the design lays a hole place's row: its Hole Wizard type and size (`None` for a
    tapped hole, whose size is its record's thread), each instance's face diameter and extent
    along z (`lo_mm` `None` for a blind hole, whose face runs down to its record's drill depth),
    and its instances' axes, as many as its record's `count`."""

    hole_type: Literal["tapped", "clearance"]
    size: str | None
    diameter_mm: float
    lo_mm: float | None
    hi_mm: float
    axes: tuple[tuple[float, float], ...]


HOLES: dict[str, HoleShape] = {
    "taps": HoleShape("tapped", None, 4.2, None, 0.0, BOLT_AXES),
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, PILOT_THICKNESS_MM, BOLT_AXES),
}
"""The bolt circle's holes, each pilot flange hole over a seat flange hole, coaxial and adjacent
at the joint face z = 0, as a joint is. Every pilot flange face lies inside the flange, so its
face boxes measure the clamped 12 mm."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "seat_doc": DocumentPlace(tree=Tree()),
    "pilot_doc": DocumentPlace(tree=Tree()),
    "shaft_doc": DocumentPlace(),
    "shim_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "seat_drw": DocumentPlace(),
    "seat": ComponentPlace(document="seat_doc"),
    "pilot": ComponentPlace(document="pilot_doc"),
    **{name: ComponentPlace(document=document) for name, (document, _) in ON_AXIS.items()},
    "taps": HolePlace(
        component="seat",
        thread="M5x0.8",
        thread_depth_mm=9.0,
        hole_depth_mm=12.0,
        count=len(BOLT_AXES),
    ),
    "clrs": HolePlace(component="pilot", count=len(BOLT_AXES)),
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("pilot",),
            clamp_mm=PILOT_THICKNESS_MM,
        )
        for screw in SCREWS
    },
    "shaft_seat": ContactPlace(a="shaft", b="seat"),
    "shim_seat": ContactPlace(a="shim", b="seat"),
    # Both fits drawn for clearance (`seeds.CLEARANCE`, the clean fit), so nothing a correct
    # reviewer checks on the base is anything but clear.
    "recess_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=RECESS_DIAMETER_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "spigot_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=RECESS_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    "hub_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=HUB_BORE_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "shaft_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=HUB_BORE_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The spigot's end stack, 8 - 5 - 2 = 1 mm nominal, strictly inside its target.
    "recess_depth": DimensionPlace(
        drawing="assy_drw", nominal_mm=RECESS_DEPTH_MM, limits=STACK_LIMITS
    ),
    "spigot_height": DimensionPlace(
        drawing="assy_drw", nominal_mm=SPIGOT_LENGTH_MM, limits=STACK_LIMITS
    ),
    "shim_width": DimensionPlace(drawing="assy_drw", nominal_mm=2.0, limits=STACK_LIMITS),
    "end_gap": DimensionPlace(drawing="assy_drw", nominal_mm=1.0, limits=("symmetric", 0.5)),
    # The complete callout `seeds.FULL_CALLOUT` writes for `taps`: count, thread, thread depth.
    "callout": DimensionPlace(
        drawing="seat_drw", nominal_mm=9.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 9"
    ),
}


# --- laying it -------------------------------------------------------------------------------


def _custom(place: Place, stem: str, summary: str) -> dict[str, str]:
    """A custom document's properties in the example profile's names (`generator.md` 5.2): the
    data card, the revision where its record carries one, the hygiene number equal to the stem
    and the summary."""
    assert isinstance(place, DocumentPlace)
    hygiene = EXAMPLE_PROFILE.hygiene
    assert hygiene is not None
    return {
        **card(EXAMPLE_PROFILE, revision="A" if place.revision else None),
        hygiene.part_number_property: stem,
        hygiene.description_property: summary,
    }


def _mass_kg(volume_mm3: float, density_kg_m3: float) -> float:
    return round(volume_mm3 * 1e-9 * density_kg_m3, 9)


def _on_axis(component: str) -> tuple[float, float, float]:
    """The centre of round component `component`, on the coupling's axis."""
    x, y = AXIS
    return (x, y, ON_AXIS[component][1])


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the seat flange fixed); the hole
    rows with each record's thread, depths and offset; the round parts' meshes on the coupling's
    axis; the screws with their fastener rows, seated unless a record says not, the M5 x 20
    document laid first as `screw_doc` and another thread or length given a document of its own;
    the contacts' interference rows. Then the bought documents moved into the bought folder and
    the custom parts' trees laid; then the two ingested drawings and every drawn dimension, in
    place order. Every document is laid opened: no pelin case leaves one unread, and a record
    that asks it is refused."""
    if variant is not None:
        raise ValueError(f"design pelin has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design pelin lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "pelin assy")
    )
    ids: dict[str, str | SourceRef] = {"assy": builder.root_id}
    for name, (stem, volume_mm3, summary) in PARTS.items():
        ids[name] = builder.document(
            stem,
            "part",
            material="Alloy Steel",
            mass_kg=_mass_kg(volume_mm3, STEEL_DENSITY_KG_M3),
            volume_mm3=volume_mm3,
            properties=_custom(places[name], stem, summary),
        )
    bought: set[str] = set()
    for name, (stem, description, diameter_mm, length_mm) in ROUND_PARTS.items():
        volume_mm3 = round(math.pi / 4.0 * diameter_mm**2 * length_mm, 6)
        document = builder.document(
            stem,
            "part",
            material="Alloy Steel",
            mass_kg=_mass_kg(volume_mm3, STEEL_DENSITY_KG_M3),
            volume_mm3=volume_mm3,
            properties={VENDOR: "FICT", "Description": description},
        )
        ids[name] = document
        bought.add(document)
    for name in ("seat", "pilot", *ON_AXIS):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=transform(_on_axis(name), Z) if name in ON_AXIS else None,
        )

    for name, shape in HOLES.items():
        record = places[name]
        assert isinstance(record, HolePlace)
        size, lo_mm = shape.size, shape.lo_mm
        if size is None:
            assert record.thread is not None
            size = record.thread
        if lo_mm is None:
            assert record.hole_depth_mm is not None
            lo_mm = -record.hole_depth_mm
        ids[name] = builder.hole(
            str(ids[record.component]),
            hole_type=shape.hole_type,
            size=size,
            thread=record.thread,
            thread_depth_mm=record.thread_depth_mm,
            hole_depth_mm=record.hole_depth_mm,
            end_condition="blind" if record.hole_depth_mm is not None else "through",
            instances=[
                Instance(
                    (x + record.offset_mm, y, 0.0),
                    Z,
                    (Face(shape.diameter_mm, lo_mm, shape.hi_mm),),
                )
                for x, y in shape.axes
            ],
        )
    for name in ON_AXIS:
        record = places[name]
        assert isinstance(record, ComponentPlace)
        _, _, diameter_mm, length_mm = ROUND_PARTS[record.document]
        builder.mesh(
            str(ids[name]),
            cylinder_mesh(_on_axis(name), Z, diameter_mm, -length_mm / 2.0, length_mm / 2.0),
        )

    # One screw document per thread and length, as a vendor's part is, each screw an instance.
    screw_documents: dict[tuple[str, float], str] = {
        (SCREW_THREAD, SCREW_LENGTH_MM): builder.screw_document(
            "SHC", SCREW_THREAD, SCREW_LENGTH_MM, serial=1, properties={VENDOR: "FICT"}
        )
    }
    ids["screw_doc"] = screw_documents[(SCREW_THREAD, SCREW_LENGTH_MM)]
    screws: dict[str, str] = {}
    for name, index in SCREWS.items():
        record = places[name]
        assert isinstance(record, ScrewPlace)
        hole = places[record.hole]
        assert isinstance(hole, HolePlace)
        x, y = HOLES[record.hole].axes[index]
        off = 0.0 if record.seated else UNSEATED_MM
        drawn = (record.thread, record.length_mm)
        if drawn not in screw_documents:
            screw_documents[drawn] = builder.screw_document(
                "SHC",
                record.thread,
                record.length_mm,
                serial=len(screw_documents) + 1,
                properties={VENDOR: "FICT"},
            )
        screws[name] = builder.screw(
            screw_documents[drawn],
            bearing_mm=(x + hole.offset_mm + off, y + off, record.clamp_mm),
            direction=Z,
            fastener_row=True,
        )

    for name, record in places.items():
        if not isinstance(record, ContactPlace):
            continue
        ids[name] = builder.interference(
            str(ids[record.a]),
            str(ids[record.b]),
            volume_mm3=record.volume_mm3,
            is_possible=record.possible and record.volume_mm3 is None,
        )

    built = builder.build()
    package = built.package
    for name, component in screws.items():
        ids[name] = next(row.id for row in package.fasteners if row.component_id == component)
    bought.update(screw_documents.values())
    documents = [
        document.model_copy(
            update={"path": f"{FICTIONAL_ROOT}Vault\\{BOUGHT_FOLDER}\\{document.file_name}"}
        )
        if document.document_id in bought
        else document
        for document in package.documents
    ]
    paths = {document.document_id: document.path for document in documents}
    entries = [
        entry.model_copy(update={"vault_path": paths[entry.document_id]})
        for entry in package.manifest.entries
    ]
    components = [
        row.model_copy(update={"is_fixed": row.id == ids["seat"]}) for row in package.components
    ]
    trees = []
    for name, (stem, _, _) in PARTS.items():
        record = places[name]
        assert isinstance(record, DocumentPlace) and record.tree is not None
        part_features, part_equations = tree_specs(record.tree)
        trees.append(
            PartSpec(
                document_id=str(ids[name]),
                name=stem,
                features=part_features,
                equations=part_equations,
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
    for name, (stem, summary) in DRAWINGS.items():
        ids[name] = sheets.drawing(stem, properties=_custom(places[name], stem, summary))
        sheets.sheet(str(ids[name]), page=1)
    for name, record in places.items():
        if isinstance(record, DimensionPlace):
            ids[name] = sheets.dimension(
                str(ids[record.drawing]),
                record.sheet,
                record.nominal_mm,
                limits=record.limits,
                text=record.as_read(),
            )
    return Laid(package=sheets.build(), meshes=built.meshes, ids=ids)


DESIGN = Design(name="pelin", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
"""A joint planted on `screw_a`, its decoy the sibling joint on `screw_b`: an M4-0.7 screw in an
M5x0.8 tapped hole, as `thread_mismatch_unplaced` plants it."""

SPIGOT_FIT = {
    "bore": "recess_bore",
    "shaft": "spigot_dia",
    "sibling_bore": "hub_bore",
    "sibling_shaft": "shaft_dia",
}
"""The spigot in the recess, which locates the pilot flange; its sibling the shaft in the hub
bore, drawn on its own two dimensions, so the recess drawn with no tolerance leaves it clear."""

END_STACK = {
    "enclosing": "recess_depth",
    "inside_1": "spigot_height",
    "inside_2": "shim_width",
    "target": "end_gap",
}
"""The spigot's end clearance: the recess's depth less the spigot and the shim, against the drawn
clearance over the shim; its decoy the stack with the shim left out."""

CALLOUT = {"callout": "callout", "hole": "taps"}
"""The seat flange drawing's callout of the tapped holes the screws go into."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="pelin-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.THREAD_MISMATCH_UNPLACED, JOINT, CURRENT),
            Seed(seeds.FIT_LIMIT_MISSING, SPIGOT_FIT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="pelin-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.STACK_OUT_OF_GAP, END_STACK, CURRENT),
            Seed(seeds.CALLOUT_THREAD_DIFFERS, CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin."""
