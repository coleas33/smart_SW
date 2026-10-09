"""The davo design (`cases.md` 6.2): a motor-mount plate: pilot bore, four tapped holes, two dowels.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom mount plate, fixed, lies on z = -15 to 0, its Ø40 pilot bore cut 6 mm down from its top
face and under it a Ø20 hole the motor's shaft passes through; the custom flange that carries the
motor, z = 0 to 12, locates on the plate by its Ø40 spigot, 4 mm long, in the pilot bore, and is
screwed down by four bought M5 socket head screws through its M5 clearance holes into the plate's
four blind M5x0.8 tapped holes. A bought Ø40 shim lies on the pilot bore's floor, leaving the
spigot 1 mm of end clearance over it, so the flange seats face to face on the plate. The pilot
bore, the spigot and the shaft holes are cut and turned, not Hole Wizard holes. The flange is each
screw's one clamped layer, a flat plate whose face boxes measure its 12 mm along the screw
(`tools/checks_fastener.py` `_bbox_extent_mm`): its only extracted faces, its clearance and dowel
holes', run through it from face to face, the spigot below it having none. The two dowels' hole
pairs, the plate's Ø5.0 under the flange's Ø5.1, stand empty, the dowels going in at assembly; the
plate is relieved 2 mm around its dowel holes, so their faces stand 2 mm under the flange's, beyond
the joint rules' 1 mm adjacency, and the joint map pairs neither (`joint_absent`; rule 6). Every
name is the example profile's: the assembly, the plate and the flange `EX-1106-..` with the data
card, the revision, the hygiene number equal to the stem and a summary unique in the package; the
shim and the screws bought, in the profile's bought folder with a vendor property, each screw with
its fastener row (GN-2). Each custom part carries `spec.tree_specs`' compliant tree. No tolerance
source anywhere (rule 4): the pilot bore's fits, the spigot's end stack and the dowel holes'
position tolerance are drawn on the assembly's ingested sheet only, beside a note that the spigot
is a slip fit in the pilot bore, the intent `fit_interference_unintended`'s plant departs from. The
plate's own drawing draws its tapped-hole callout alone (rule 5). The interference row is a
zero-volume contact: the shim on the pilot bore's floor.

**Places** (rule 2): the documents `assy`, `plate_doc`, `flange_doc`, `shim_doc`, `screw_doc`
(the M5 x 20 screws'), `assy_drw` and `plate_drw`; the components `plate`, `flange` and `shim`; the
Hole Wizard rows `taps` (the plate's tapped holes) under `clrs` (the flange's clearance holes), four
instances each, and the two empty dowel-hole pairs, each hole a one-instance row, `dowel_a` and
`dowel_b` (the plate's Ø5.0) under `cdowel_a` and `cdowel_b` (the flange's Ø5.1), each pair the
other's decoy pair (rule 6); the fasteners `screw_a` to `screw_d`, one into each instance of
`taps`; the contact `shim_plate`; on the assembly's sheet the pilot bore `pilot_bore` over the
spigot's diameter `spigot_dia` and the shim's outside `shim_od`, so each fit is the other's sibling
fit (rule 6), `position`, the position tolerance governing the dowel holes, and the spigot's end
stack: the pilot bore's depth `pilot_depth`, the spigot's length `spigot_height` and the shim's
width `shim_width` inside it, and the end clearance `end_gap`, its target, the shim the contributor
a decoy leaves out (rule 6); and `callout`, the plate drawing's tapped-hole callout.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `davo-1`: `coaxiality_drawn` on the first dowel-hole pair, the flange's `cdowel_a` off the
  plate's `dowel_a` by the whole drawn zone, and `fit_interference_unintended` on the spigot in the
  pilot bore, its sibling fit, the shim in the same bore, staying clear.
- `davo-2`: `stack_out_of_gap` on the spigot's end stack, its three contributors toleranced wide
  enough that the worst-case band leaves the drawn end clearance, and `callout_count_differs` on the
  plate's own drawing.
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
from tests.support.drawings import Limits, NoteKind, SheetBuilder
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

ASSY_STEM, PLATE_STEM, FLANGE_STEM = "EX-1106-00", "EX-1106-01", "EX-1106-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the shim and the screws bought (`generator.md` 5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

PLATE_THICKNESS_MM = 15.0
FLANGE_THICKNESS_MM = 12.0
"""The plate lies from z = -15 to 0, the flange from 0 to 12: the flange is the stack each screw
clamps."""

PILOT_DIAMETER_MM, PILOT_DEPTH_MM = 40.0, 6.0
SPIGOT_LENGTH_MM = 4.0
SHAFT_HOLE_MM = 20.0
"""The plate's Ø40 pilot bore, cut 6 mm down from its top face, and under it the Ø20 hole the
motor's shaft passes through, to its bottom face; the flange's Ø40 spigot, 4 mm long below its
face, and the same Ø20 hole through both. All cut or turned, not Hole Wizard holes."""

RELIEF_MM = 2.0
"""How far the plate is relieved around its dowel holes: their faces stop this far under the
flange's, more than the joint rules' 1 mm adjacency (`checks/joint_rules.yaml`
`adjacency_gap_mm`), so the joint map pairs no dowel hole (`joint_absent`, `generator.md` 3)."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary)
    # a 120 x 120 x 15 mm plate less its pilot bore and the shaft hole under it
    "plate_doc": (
        PLATE_STEM,
        round(
            120.0 * 120.0 * PLATE_THICKNESS_MM
            - math.pi / 4.0 * PILOT_DIAMETER_MM**2 * PILOT_DEPTH_MM
            - math.pi / 4.0 * SHAFT_HOLE_MM**2 * (PLATE_THICKNESS_MM - PILOT_DEPTH_MM),
            6,
        ),
        "davo mount plate",
    ),
    # a 100 x 100 x 12 mm flange and its spigot under it, less the shaft hole through both
    "flange_doc": (
        FLANGE_STEM,
        round(
            100.0 * 100.0 * FLANGE_THICKNESS_MM
            + math.pi / 4.0 * PILOT_DIAMETER_MM**2 * SPIGOT_LENGTH_MM
            - math.pi / 4.0 * SHAFT_HOLE_MM**2 * (FLANGE_THICKNESS_MM + SPIGOT_LENGTH_MM),
            6,
        ),
        "davo flange",
    ),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

AXIS = (60.0, 60.0)
Z = (0.0, 0.0, 1.0)
"""The (x, y) of the pilot bore's axis; it, and every hole's axis, is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float, float]] = {
    # document place: (stem, description, outside and inside diameter, length) in mm
    "shim_doc": (
        "FICT-SHIM-20X40X1-0001",
        "SHIM, Ø20 X Ø40 X 1 MM, FICTIONAL",
        PILOT_DIAMETER_MM,
        SHAFT_HOLE_MM,
        1.0,
    ),
}
"""The bought round part, steel; a mesh with no extracted face, so the joint map, which reads
faces in hole instances, takes it for no pin."""

ON_AXIS: dict[str, tuple[str, float]] = {
    # component place: (its document place, the z of its centre)
    "shim": ("shim_doc", -5.5),
}
"""Each round component on the pilot bore's axis: the shim on the bore's floor, z = -6 to -5; the
end clearance, -5 to the spigot's end at -4."""

ASSY_NOTES: tuple[tuple[str, NoteKind], ...] = (
    ("THE SPIGOT IS A SLIP FIT IN THE PILOT HOLE.", "other"),
)
"""The assembly sheet's note: the spigot's intent, which `fit_interference_unintended`'s plant
departs from (`generator.md` 3), in a sentence, since a summary is a name (`generator.md` 8)."""

DRAWINGS: dict[str, tuple[str, str, tuple[tuple[str, NoteKind], ...]]] = {
    "assy_drw": (ASSY_STEM, "davo assy drawing", ASSY_NOTES),
    "plate_drw": (PLATE_STEM, "davo mount plate drawing", ()),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary, the sheet's notes)."""

TAP_AXES = ((25.0, 25.0), (95.0, 25.0), (25.0, 95.0), (95.0, 95.0))
DOWEL_AXES = ((25.0, 60.0), (95.0, 60.0))
"""The (x, y) of the screw holes' and the dowel-hole pairs' axes, all along z, inside the
flange's x and y = 10 to 110 and clear of the pilot bore, x and y = 40 to 80."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 20.0
"""The flange's screws, all one document (`screw_doc`): M5 x 20 reaches 8 mm past the flange,
inside the 9 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives."""

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
    "taps": HoleShape("tapped", None, 4.2, None, 0.0, TAP_AXES),
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, FLANGE_THICKNESS_MM, TAP_AXES),
    "dowel_a": HoleShape(
        "clearance", "Ø5.0", 5.0, -PLATE_THICKNESS_MM, -RELIEF_MM, (DOWEL_AXES[0],)
    ),
    "dowel_b": HoleShape(
        "clearance", "Ø5.0", 5.0, -PLATE_THICKNESS_MM, -RELIEF_MM, (DOWEL_AXES[1],)
    ),
    "cdowel_a": HoleShape("clearance", "Ø5.1", 5.1, 0.0, FLANGE_THICKNESS_MM, (DOWEL_AXES[0],)),
    "cdowel_b": HoleShape("clearance", "Ø5.1", 5.1, 0.0, FLANGE_THICKNESS_MM, (DOWEL_AXES[1],)),
}
"""The screw holes, each flange hole over a plate hole, coaxial and adjacent at the joint face
z = 0, as a joint is; and the dowel holes, each a feature of its own, one instance, so
`coaxiality_drawn`'s form moves one hole alone (`seeds._offset`), the plate's from its relief
floor through to its bottom face. Every flange face lies inside the flange, so its face boxes
measure the clamped 12 mm."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "plate_doc": DocumentPlace(tree=Tree()),
    "flange_doc": DocumentPlace(tree=Tree()),
    "shim_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "plate_drw": DocumentPlace(),
    "plate": ComponentPlace(document="plate_doc"),
    "flange": ComponentPlace(document="flange_doc"),
    **{name: ComponentPlace(document=document) for name, (document, _) in ON_AXIS.items()},
    "taps": HolePlace(
        component="plate",
        thread="M5x0.8",
        thread_depth_mm=9.0,
        hole_depth_mm=12.0,
        count=len(TAP_AXES),
    ),
    "clrs": HolePlace(component="flange", count=len(TAP_AXES)),
    "dowel_a": HolePlace(component="plate"),
    "dowel_b": HolePlace(component="plate"),
    "cdowel_a": HolePlace(component="flange"),
    "cdowel_b": HolePlace(component="flange"),
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("flange",),
            clamp_mm=FLANGE_THICKNESS_MM,
        )
        for screw in SCREWS
    },
    "shim_plate": ContactPlace(a="shim", b="plate"),
    # The pilot bore's two fits drawn for clearance (`seeds.CLEARANCE`, the clean fit), so
    # nothing a correct reviewer checks on the base is anything but clear.
    "pilot_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=PILOT_DIAMETER_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "spigot_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=PILOT_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    "shim_od": DimensionPlace(
        drawing="assy_drw", nominal_mm=PILOT_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The dowel holes' position tolerance, a Ø0.1 zone: `coaxiality_drawn` reads its nominal.
    "position": DimensionPlace(drawing="assy_drw", nominal_mm=0.1, limits=None, text="⌖ Ø0.1"),
    # The spigot's end stack, 6 - 4 - 1 = 1 mm nominal, strictly inside its target.
    "pilot_depth": DimensionPlace(
        drawing="assy_drw", nominal_mm=PILOT_DEPTH_MM, limits=STACK_LIMITS
    ),
    "spigot_height": DimensionPlace(
        drawing="assy_drw", nominal_mm=SPIGOT_LENGTH_MM, limits=STACK_LIMITS
    ),
    "shim_width": DimensionPlace(drawing="assy_drw", nominal_mm=1.0, limits=STACK_LIMITS),
    "end_gap": DimensionPlace(drawing="assy_drw", nominal_mm=1.0, limits=("symmetric", 0.5)),
    # The complete callout `seeds.FULL_CALLOUT` writes for `taps`: count, thread, thread depth.
    "callout": DimensionPlace(
        drawing="plate_drw", nominal_mm=9.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 9"
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
    """The centre of round component `component`, on the pilot bore's axis."""
    x, y = AXIS
    return (x, y, ON_AXIS[component][1])


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the plate fixed); the hole rows with
    each record's thread, depths and offset; the shim's mesh on the pilot bore's axis; the screws
    with their fastener rows, seated unless a record says not, the M5 x 20 document laid first as
    `screw_doc` and another thread or length given a document of its own; the contact's
    interference row. Then the bought documents moved into the bought folder and the custom
    parts' trees laid; then the two ingested drawings, the assembly's with its note, and every
    drawn dimension, in place order. Every document is laid opened: no davo case leaves one
    unread, and a record that asks it is refused."""
    if variant is not None:
        raise ValueError(f"design davo has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design davo lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "davo assy")
    )
    ids: dict[str, str | SourceRef] = {"assy": builder.root_id}
    for name, (stem, volume_mm3, summary) in PARTS.items():
        ids[name] = builder.document(
            stem,
            "part",
            material="6061-T6",
            mass_kg=_mass_kg(volume_mm3, ALUMINIUM_DENSITY_KG_M3),
            volume_mm3=volume_mm3,
            properties=_custom(places[name], stem, summary),
        )
    bought: set[str] = set()
    for name, (stem, description, outside_mm, inside_mm, length_mm) in ROUND_PARTS.items():
        volume_mm3 = round(math.pi / 4.0 * (outside_mm**2 - inside_mm**2) * length_mm, 6)
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
    for name in ("plate", "flange", *ON_AXIS):
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
        _, _, outside_mm, _, length_mm = ROUND_PARTS[record.document]
        builder.mesh(
            str(ids[name]),
            cylinder_mesh(_on_axis(name), Z, outside_mm, -length_mm / 2.0, length_mm / 2.0),
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
        row.model_copy(update={"is_fixed": row.id == ids["plate"]}) for row in package.components
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
    for name, (stem, summary, notes) in DRAWINGS.items():
        ids[name] = sheets.drawing(stem, properties=_custom(places[name], stem, summary))
        sheets.sheet(str(ids[name]), page=1, notes=notes)
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


DESIGN = Design(name="davo", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

DOWEL_PAIR = {
    "a": "dowel_a",
    "b": "cdowel_a",
    "other_a": "dowel_b",
    "other_b": "cdowel_b",
    "tolerance": "position",
}
"""The first dowel-hole pair, the flange's hole moved off the plate's by the drawn zone; its decoy
the second pair between the same parts, with and without the tolerance."""

PILOT_FIT = {
    "bore": "pilot_bore",
    "shaft": "spigot_dia",
    "sibling_bore": "pilot_bore",
    "sibling_shaft": "shim_od",
}
"""The spigot in the pilot bore, which must slip; its sibling the shim in the same bore: one drawn
bore over two drawn outsides. The planted bore's limits still clear the shim's outside
(`seeds.INTERFERENCE` against `seeds.CLEARANCE`), so the sibling fit stays clean in every form."""

PILOT_STACK = {
    "enclosing": "pilot_depth",
    "inside_1": "spigot_height",
    "inside_2": "shim_width",
    "target": "end_gap",
}
"""The spigot's end clearance: the pilot bore's depth less the spigot and the shim, against the
drawn clearance over the shim; its decoy the stack with the shim left out."""

CALLOUT = {"callout": "callout", "hole": "taps"}
"""The plate drawing's callout of the tapped holes the flange's screws go into."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="davo-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.COAXIALITY_DRAWN, DOWEL_PAIR, CURRENT),
            Seed(seeds.FIT_INTERFERENCE_UNINTENDED, PILOT_FIT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="davo-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.STACK_OUT_OF_GAP, PILOT_STACK, CURRENT),
            Seed(seeds.CALLOUT_COUNT_DIFFERS, CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin."""
