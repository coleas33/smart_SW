"""The brun design (`cases.md` 6.2): a shaft in a bearing housing: seat bore, spacer stack, cover
screws.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom housing, fixed, lies on z = -60 to 0, its Ø42 seat bore cut down from its top face to a
shoulder 30 mm deep; the custom cover, z = 0 to 12, closes the bore, screwed down by four bought
M5 socket head screws through its M5 clearance holes into the housing's four blind M5x0.8 tapped
holes. In the seat, from the shoulder up, sit a bought bearing (12 mm wide), a bought spacer
(15 mm) and a bought shim (2 mm), leaving the bearing 1 mm of axial float under the cover; a
bought Ø20 shaft runs up through the housing's bottom and the bearing and ends under the cover.
The seat and the shaft's bore are cut, not Hole Wizard holes. The cover is each screw's one
clamped layer, a flat plate whose face boxes measure its 12 mm along the screw
(`tools/checks_fastener.py` `_bbox_extent_mm`): its only extracted faces, its clearance and dowel
holes', run through it from face to face. Two dowel-hole pairs, the housing's Ø5.0 under the
cover's Ø5.1, stand empty; the housing is relieved 2 mm around its dowel holes, so their faces
stand 2 mm under the cover's, beyond the joint rules' 1 mm adjacency, and the joint map pairs
neither (`joint_absent`; rule 6). Every name is the example profile's: the assembly, the
housing and the cover `EX-1104-..` with the data card, the revision, the hygiene number equal to
the stem and a summary unique in the package; the shaft, the bearing, the spacer, the shim and the
screws bought, in the profile's bought folder with a vendor property, each screw with its fastener
row (GN-2). Each custom part carries `spec.tree_specs`' compliant tree. No tolerance source
anywhere (rule 4): the seat's fits, the spacer stack and the dowel holes' position tolerance are
drawn on the assembly's ingested sheet only, beside a note that the bearing slides in the seat
bore, the floating bearing's intent `fit_transition`'s plant departs from (`generator.md` 3). The
housing's own drawing draws its tapped-hole callout alone (rule 5). The interference rows are
zero-volume contacts: the shaft line to line in the bearing, the bearing line to line in the
housing.

**Places** (rule 2): the documents `assy`, `housing_doc`, `cover_doc`, `shaft_doc`,
`bearing_doc`, `spacer_doc`, `shim_doc`, `screw_doc` (the M5 x 20 screws'), `assy_drw` and
`housing_drw`; the components `housing`, `cover`, `shaft`, `bearing`, `spacer` and `shim`; the
Hole Wizard rows `taps` (the housing's tapped holes) under `clrs` (the cover's clearance holes),
four instances each, and the two empty dowel-hole pairs, each hole a one-instance row, `dowel_a`
and `dowel_b` (the housing's Ø5.0) under `cdowel_a` and `cdowel_b` (the cover's Ø5.1), each pair
the other's decoy pair (rule 6); the fasteners `screw_a` to `screw_d`, one into each instance of
`taps`; the contacts `shaft_bearing` and `bearing_housing`; on the assembly's sheet the seat bore
`seat_bore` over the bearing's outside `bearing_od` and the spacer's `spacer_od`, so each fit is
the other's sibling fit (rule 6), `position`, the position tolerance governing the dowel holes,
and the spacer stack: the seat's depth `seat_depth`, the widths `bearing_width`, `spacer_width`
and `shim_width` inside it, and the float under the cover `float_gap`, its target, the shim the
contributor a decoy leaves out (rule 6); and `callout`, the housing drawing's tapped-hole
callout.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin. `brun-1`'s seeds stand in the order `cases.md` 7's example
message names them, "(a) brun-1 D-2 (hole.coaxiality, model-produced) ...".

- `brun-1`: `stack_out_of_gap` on the spacer stack, its four contributors toleranced wide enough
  that the worst-case band leaves the drawn float, and `coaxiality_drawn` on the first dowel-hole
  pair, the cover's `cdowel_a` off the housing's `dowel_a` by the whole drawn zone.
- `brun-2`: `fit_transition` on the bearing in the seat bore, its sibling fit, the spacer in the
  same bore, staying clear, and `callout_drill_only` on the housing's own drawing.
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

ASSY_STEM, HOUSING_STEM, COVER_STEM = "EX-1104-00", "EX-1104-01", "EX-1104-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the shaft, the bearing, the spacer, the shim and the screws
bought (`generator.md` 5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

HOUSING_HEIGHT_MM = 60.0
COVER_THICKNESS_MM = 12.0
"""The housing lies from z = -60 to 0, the cover from 0 to 12: the cover is the stack each screw
clamps."""

SEAT_DIAMETER_MM, SEAT_DEPTH_MM = 42.0, 30.0
SHAFT_BORE_MM = 24.0
"""The housing's seat bore, Ø42 down to its shoulder 30 mm under the top face, and under it the
Ø24 bore the shaft runs up through: both cut, not Hole Wizard holes."""

RELIEF_MM = 2.0
"""How far the housing is relieved around its dowel holes: their faces stop this far under the
cover's, more than the joint rules' 1 mm adjacency (`checks/joint_rules.yaml`
`adjacency_gap_mm`), so the joint map pairs no dowel hole (`joint_absent`, `generator.md` 3)."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary)
    # a 120 x 80 x 60 mm block less its seat bore and the shaft's bore under it
    "housing_doc": (
        HOUSING_STEM,
        round(
            120.0 * 80.0 * HOUSING_HEIGHT_MM
            - math.pi / 4.0 * SEAT_DIAMETER_MM**2 * SEAT_DEPTH_MM
            - math.pi / 4.0 * SHAFT_BORE_MM**2 * (HOUSING_HEIGHT_MM - SEAT_DEPTH_MM),
            6,
        ),
        "brun housing",
    ),
    "cover_doc": (COVER_STEM, 120.0 * 80.0 * COVER_THICKNESS_MM, "brun cover"),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

SHAFT_AXIS = (60.0, 40.0)
Z = (0.0, 0.0, 1.0)
"""The (x, y) of the seat's and the shaft's axis; it, and every hole's axis, is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float, float]] = {
    # document place: (stem, description, outside and inside diameter, length) in mm
    "shaft_doc": ("FICT-SHAFT-20X80-0001", "SHAFT, Ø20 X 80 MM, FICTIONAL", 20.0, 0.0, 80.0),
    "bearing_doc": (
        "FICT-BEARING-20X42X12-0001",
        "BEARING, Ø20 X Ø42 X 12 MM, FICTIONAL",
        SEAT_DIAMETER_MM,
        20.0,
        12.0,
    ),
    "spacer_doc": (
        "FICT-SPACER-30X42X15-0001",
        "SPACER, Ø30 X Ø42 X 15 MM, FICTIONAL",
        SEAT_DIAMETER_MM,
        30.0,
        15.0,
    ),
    "shim_doc": (
        "FICT-SHIM-30X42X2-0001",
        "SHIM, Ø30 X Ø42 X 2 MM, FICTIONAL",
        SEAT_DIAMETER_MM,
        30.0,
        2.0,
    ),
}
"""The bought round parts, steel; each a mesh with no extracted face, so the joint map, which
reads faces in hole instances, takes none for a pin."""

ON_SHAFT: dict[str, tuple[str, float]] = {
    # component place: (its document place, the z of its centre)
    "shaft": ("shaft_doc", -50.0),
    "bearing": ("bearing_doc", -24.0),
    "spacer": ("spacer_doc", -10.5),
    "shim": ("shim_doc", -2.0),
}
"""Each round component on the seat's axis: the shaft from z = -90 to -10, up through the
housing's bottom and the bearing; the bearing on the shoulder, z = -30 to -18; the spacer on it,
-18 to -3; the shim on that, -3 to -1; the float, -1 to the cover's face at 0."""

ASSY_NOTES: tuple[tuple[str, NoteKind], ...] = (("THE BEARING SLIDES IN THE SEAT BORE.", "other"),)
"""The assembly sheet's note: the floating bearing's intent, which `fit_transition`'s plant has
the package state (`generator.md` 3), in a sentence, since a summary is a name (`generator.md`
8)."""

DRAWINGS: dict[str, tuple[str, str, tuple[tuple[str, NoteKind], ...]]] = {
    "assy_drw": (ASSY_STEM, "brun assy drawing", ASSY_NOTES),
    "housing_drw": (HOUSING_STEM, "brun housing drawing", ()),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary, the sheet's notes)."""

TAP_AXES = ((20.0, 15.0), (100.0, 15.0), (20.0, 65.0), (100.0, 65.0))
DOWEL_AXES = ((20.0, 40.0), (100.0, 40.0))
"""The (x, y) of the screw holes' and the dowel-hole pairs' axes, all along z, inside the
cover's 120 x 80 mm and clear of the seat, x = 39 to 81."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 20.0
"""The cover's screws, all one document (`screw_doc`): M5 x 20 reaches 8 mm past the cover,
inside the 9 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""

STACK_LIMITS: Limits = ("symmetric", 0.05)
"""Each spacer-stack contributor's drawn tolerance in the base: four of them hold the float to
1 ± 0.2 mm, inside its drawn 1 ± 0.5 mm, so the stack is clean wherever no form tolerances it
(`seeds.STACK_OUT_OF_GAP` draws ± 0.25 mm each to plant, ± 0.062 mm in its clean form)."""


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
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, COVER_THICKNESS_MM, TAP_AXES),
    "dowel_a": HoleShape("clearance", "Ø5.0", 5.0, -20.0, -RELIEF_MM, (DOWEL_AXES[0],)),
    "dowel_b": HoleShape("clearance", "Ø5.0", 5.0, -20.0, -RELIEF_MM, (DOWEL_AXES[1],)),
    "cdowel_a": HoleShape("clearance", "Ø5.1", 5.1, 0.0, COVER_THICKNESS_MM, (DOWEL_AXES[0],)),
    "cdowel_b": HoleShape("clearance", "Ø5.1", 5.1, 0.0, COVER_THICKNESS_MM, (DOWEL_AXES[1],)),
}
"""The screw holes, each cover hole over a housing hole, coaxial and adjacent at the joint face
z = 0, as a joint is; and the dowel holes, each a feature of its own, one instance, so
`coaxiality_drawn`'s form moves one hole alone (`seeds._offset`), the housing's from its relief
floor down to z = -20. Every cover face lies inside the cover, so its face boxes measure the
clamped 12 mm."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "housing_doc": DocumentPlace(tree=Tree()),
    "cover_doc": DocumentPlace(tree=Tree()),
    "shaft_doc": DocumentPlace(),
    "bearing_doc": DocumentPlace(),
    "spacer_doc": DocumentPlace(),
    "shim_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "housing_drw": DocumentPlace(),
    "housing": ComponentPlace(document="housing_doc"),
    "cover": ComponentPlace(document="cover_doc"),
    **{name: ComponentPlace(document=document) for name, (document, _) in ON_SHAFT.items()},
    "taps": HolePlace(
        component="housing",
        thread="M5x0.8",
        thread_depth_mm=9.0,
        hole_depth_mm=12.0,
        count=len(TAP_AXES),
    ),
    "clrs": HolePlace(component="cover", count=len(TAP_AXES)),
    "dowel_a": HolePlace(component="housing"),
    "dowel_b": HolePlace(component="housing"),
    "cdowel_a": HolePlace(component="cover"),
    "cdowel_b": HolePlace(component="cover"),
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("cover",),
            clamp_mm=COVER_THICKNESS_MM,
        )
        for screw in SCREWS
    },
    "shaft_bearing": ContactPlace(a="shaft", b="bearing"),
    "bearing_housing": ContactPlace(a="bearing", b="housing"),
    # The seat's two fits drawn for clearance (`seeds.CLEARANCE`, the clean fit), so nothing a
    # correct reviewer checks on the base is anything but clear.
    "seat_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=SEAT_DIAMETER_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "bearing_od": DimensionPlace(
        drawing="assy_drw", nominal_mm=SEAT_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    "spacer_od": DimensionPlace(
        drawing="assy_drw", nominal_mm=SEAT_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The dowel holes' position tolerance, a Ø0.1 zone: `coaxiality_drawn` reads its nominal.
    "position": DimensionPlace(drawing="assy_drw", nominal_mm=0.1, limits=None, text="⌖ Ø0.1"),
    # The spacer stack, 30 - 12 - 15 - 2 = 1 mm nominal, strictly inside its target.
    "seat_depth": DimensionPlace(drawing="assy_drw", nominal_mm=SEAT_DEPTH_MM, limits=STACK_LIMITS),
    "bearing_width": DimensionPlace(drawing="assy_drw", nominal_mm=12.0, limits=STACK_LIMITS),
    "spacer_width": DimensionPlace(drawing="assy_drw", nominal_mm=15.0, limits=STACK_LIMITS),
    "shim_width": DimensionPlace(drawing="assy_drw", nominal_mm=2.0, limits=STACK_LIMITS),
    "float_gap": DimensionPlace(drawing="assy_drw", nominal_mm=1.0, limits=("symmetric", 0.5)),
    # The complete callout `seeds.FULL_CALLOUT` writes for `taps`: count, thread, thread depth.
    "callout": DimensionPlace(
        drawing="housing_drw", nominal_mm=9.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 9"
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


def _on_shaft(component: str) -> tuple[float, float, float]:
    """The centre of round component `component`, on the seat's axis."""
    x, y = SHAFT_AXIS
    return (x, y, ON_SHAFT[component][1])


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the housing fixed); the hole rows
    with each record's thread, depths and offset; the round parts' meshes on the seat's axis; the
    screws with their fastener rows, seated unless a record says not, the M5 x 20 document laid
    first as `screw_doc` and another thread or length given a document of its own; the contacts'
    interference rows. Then the bought documents moved into the bought folder and the custom
    parts' trees laid; then the two ingested drawings, the assembly's with its note, and every
    drawn dimension, in place order. Every document is laid opened: no brun case leaves one
    unread, and a record that asks it is refused."""
    if variant is not None:
        raise ValueError(f"design brun has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design brun lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "brun assy")
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
    for name in ("housing", "cover", *ON_SHAFT):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=transform(_on_shaft(name), Z) if name in ON_SHAFT else None,
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
    for name in ON_SHAFT:
        record = places[name]
        assert isinstance(record, ComponentPlace)
        _, _, outside_mm, _, length_mm = ROUND_PARTS[record.document]
        builder.mesh(
            str(ids[name]),
            cylinder_mesh(_on_shaft(name), Z, outside_mm, -length_mm / 2.0, length_mm / 2.0),
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
        row.model_copy(update={"is_fixed": row.id == ids["housing"]}) for row in package.components
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


DESIGN = Design(name="brun", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

SPACER_STACK = {
    "enclosing": "seat_depth",
    "inside_1": "bearing_width",
    "inside_2": "spacer_width",
    "inside_3": "shim_width",
    "target": "float_gap",
}
"""The bearing's float: the seat's depth less the bearing, the spacer and the shim, against the
drawn gap under the cover; its decoy the stack with the shim left out."""

DOWEL_PAIR = {
    "a": "dowel_a",
    "b": "cdowel_a",
    "other_a": "dowel_b",
    "other_b": "cdowel_b",
    "tolerance": "position",
}
"""The first dowel-hole pair, the cover's hole moved off the housing's by the drawn zone; its
decoy the second pair between the same parts, with and without the tolerance."""

SEAT_FIT = {
    "bore": "seat_bore",
    "shaft": "bearing_od",
    "sibling_bore": "seat_bore",
    "sibling_shaft": "spacer_od",
}
"""The bearing in the seat bore, which must slide; its sibling the spacer in the same bore: one
drawn bore over two drawn outsides. The planted bore's limits still clear the spacer's outside
(`seeds.TRANSITION` against `seeds.CLEARANCE`), so the sibling fit stays clean in every form."""

CALLOUT = {"callout": "callout", "hole": "taps"}
"""The housing drawing's callout of the tapped holes the cover screws go into."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="brun-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.STACK_OUT_OF_GAP, SPACER_STACK, CURRENT),
            Seed(seeds.COAXIALITY_DRAWN, DOWEL_PAIR, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="brun-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.FIT_TRANSITION, SEAT_FIT, CURRENT),
            Seed(seeds.CALLOUT_DRILL_ONLY, CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin."""
