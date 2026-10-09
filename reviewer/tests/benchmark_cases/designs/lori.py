"""The lori design (`cases.md` 6.2): a gear cover on a housing: dowels, screws, a shaft bore.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom housing, fixed, lies on z = -50 to 0, its Ø70 gear pocket cut 30 mm down from its top
face and, under the pocket, its Ø20 shaft bore through the floor; the custom gear cover, z = 0 to
12, closes the pocket, screwed down by four bought M5 socket head screws through its M5 clearance
holes into the housing's four blind M5x0.8 tapped holes, and carries four blind M4x0.7 tapped
holes, empty, in its top face for what it carries. A bought Ø20 shaft runs up through the shaft
bore and ends 2 mm under the cover; a bought Ø60 gear sits on it inside the pocket. The pocket and
the shaft bore are cut, not Hole Wizard holes. The cover is each screw's one clamped layer, a flat
plate whose face boxes measure its 12 mm along the screw (`tools/checks_fastener.py`
`_bbox_extent_mm`): its clearance and dowel holes' faces run through it from face to face, its
tapped holes' lie inside it. Two dowel-hole pairs, the housing's Ø5.0 under the cover's Ø5.1,
stand empty, the dowels going in at assembly; the housing is relieved 2 mm around its dowel
holes, so their faces stand 2 mm under the cover's, beyond the joint rules' 1 mm adjacency, and
the joint map pairs neither. Every name is the example profile's: the assembly, the housing and
the cover `EX-1108-..` with the data card, the revision, the hygiene number equal to the stem and
a summary unique in the package; the shaft, the gear and the screws bought, in the profile's
bought folder with a vendor property, each screw with its fastener row (GN-2). Each custom part
carries `spec.tree_specs`' compliant tree. No tolerance source anywhere (rule 4): the shaft's fit
in its bore and the gear's on the shaft are drawn on the assembly's ingested sheet only, beside a
note that the shaft turns and slides in its bore, the running intent `fit_transition`'s plant
departs from (`generator.md` 3). The housing's own drawing draws the callout of its tapped holes
alone, and the cover's own drawing the callout of its own (rule 5). The interference rows are
zero-volume contacts: the shaft line to line in its bore, the gear line to line on the shaft.

**Places** (rule 2): the documents `assy`, `housing_doc`, `cover_doc`, `shaft_doc`, `gear_doc`,
`screw_doc` (the M5 x 20 screws'), `assy_drw`, `housing_drw` and `cover_drw`; the components
`housing`, `cover`, `shaft` and `gear`; the Hole Wizard rows `taps` (the housing's tapped holes)
under `clrs` (the cover's clearance holes), four instances each, the empty dowel-hole pairs
`dowels` (the housing's Ø5.0) under `cdowels` (the cover's Ø5.1), two instances each, and
`top_taps` (the cover's own tapped holes), four instances; the fasteners `screw_a` to `screw_d`,
one into each instance of `taps`, `screw_b` the sibling joint of `screw_a` (rule 6); the contacts
`shaft_housing` and `gear_shaft`; on the assembly's sheet the shaft bore `shaft_bore` over the
shaft's diameter `shaft_dia`, and its sibling fit (rule 6), the gear's bore `gear_bore` over the
shaft's gear seat `gear_seat`; and the callouts `housing_callout`, on the housing's drawing, and
`cover_callout`, on the cover's.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `lori-1`: `thread_mismatch_unplaced` on `screw_a`, an M4-0.7 screw in the M5x0.8 `taps`, and
  `callout_count_differs` on the cover's own drawing.
- `lori-2`: `fit_transition` on the shaft in its bore, its sibling fit, the gear on the shaft,
  staying clear, and `callout_drill_only` on the housing's own drawing.
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
from tests.support.drawings import NoteKind, SheetBuilder
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

ASSY_STEM, HOUSING_STEM, COVER_STEM = "EX-1108-00", "EX-1108-01", "EX-1108-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the shaft, the gear and the screws bought (`generator.md`
5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

HOUSING_HEIGHT_MM = 50.0
COVER_THICKNESS_MM = 12.0
"""The housing lies from z = -50 to 0, the cover from 0 to 12: the cover is the stack each screw
clamps."""

POCKET_DIAMETER_MM, POCKET_DEPTH_MM = 70.0, 30.0
SHAFT_DIAMETER_MM = 20.0
"""The housing's gear pocket, Ø70 down to its floor 30 mm under the top face, and under it the
Ø20 shaft bore through the floor: both cut, not Hole Wizard holes."""

RELIEF_MM = 2.0
"""How far the housing is relieved around its dowel holes: their faces stop this far under the
cover's, more than the joint rules' 1 mm adjacency (`checks/joint_rules.yaml`
`adjacency_gap_mm`), so the joint map pairs no dowel hole."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary)
    # a 140 x 100 x 50 mm block less its gear pocket and the shaft bore under it
    "housing_doc": (
        HOUSING_STEM,
        round(
            140.0 * 100.0 * HOUSING_HEIGHT_MM
            - math.pi / 4.0 * POCKET_DIAMETER_MM**2 * POCKET_DEPTH_MM
            - math.pi / 4.0 * SHAFT_DIAMETER_MM**2 * (HOUSING_HEIGHT_MM - POCKET_DEPTH_MM),
            6,
        ),
        "lori housing",
    ),
    "cover_doc": (COVER_STEM, 140.0 * 100.0 * COVER_THICKNESS_MM, "lori gear cover"),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

SHAFT_AXIS = (70.0, 50.0)
Z = (0.0, 0.0, 1.0)
"""The (x, y) of the pocket's and the shaft's axis; it, and every hole's axis, is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float, float]] = {
    # document place: (stem, description, outside and inside diameter, length) in mm
    "shaft_doc": (
        "FICT-SHAFT-20X70-0001",
        "SHAFT, Ø20 X 70 MM, FICTIONAL",
        SHAFT_DIAMETER_MM,
        0.0,
        70.0,
    ),
    "gear_doc": (
        "FICT-GEAR-20X60X15-0001",
        "GEAR, Ø20 X Ø60 X 15 MM, FICTIONAL",
        60.0,
        SHAFT_DIAMETER_MM,
        15.0,
    ),
}
"""The bought round parts, steel; each a mesh with no extracted face, so the joint map, which
reads faces in hole instances, takes neither for a pin."""

ON_SHAFT: dict[str, tuple[str, float]] = {
    # component place: (its document place, the z of its centre)
    "shaft": ("shaft_doc", -37.0),
    "gear": ("gear_doc", -15.0),
}
"""Each round component on the shaft's axis: the shaft from z = -72 to -2, up through the shaft
bore, -50 to -30, and the pocket, ending 2 mm under the cover; the gear on it, -22.5 to -7.5,
inside the pocket."""

ASSY_NOTES: tuple[tuple[str, NoteKind], ...] = (
    ("THE SHAFT TURNS AND SLIDES FREELY IN THE SHAFT BORE.", "other"),
)
"""The assembly sheet's note: the shaft's running intent, which `fit_transition`'s plant has the
package state (`generator.md` 3), in a sentence, since a summary is a name (`generator.md` 8)."""

DRAWINGS: dict[str, tuple[str, str, tuple[tuple[str, NoteKind], ...]]] = {
    "assy_drw": (ASSY_STEM, "lori assy drawing", ASSY_NOTES),
    "housing_drw": (HOUSING_STEM, "lori housing drawing", ()),
    "cover_drw": (COVER_STEM, "lori cover drawing", ()),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary, the sheet's notes)."""

TAP_AXES = ((15.0, 15.0), (125.0, 15.0), (15.0, 85.0), (125.0, 85.0))
DOWEL_AXES = ((15.0, 50.0), (125.0, 50.0))
TOP_AXES = ((40.0, 20.0), (100.0, 20.0), (40.0, 80.0), (100.0, 80.0))
"""The (x, y) of the screw holes', the dowel-hole pairs' and the cover's own tapped holes' axes,
all along z, inside the cover's 140 x 100 mm, each at least 25 mm from the nearest other and
clear of the pocket, x = 35 to 105."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 20.0
"""The cover's screws, all one document (`screw_doc`): M5 x 20 reaches 8 mm past the cover,
inside the 9 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives, so a twin's
screws are the base's."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""


@dataclass(frozen=True)
class HoleShape:
    """How the design lays a hole place's row: its Hole Wizard type and size (`None` for a
    tapped hole, whose size is its record's thread), each instance's face diameter and extent
    along z (`lo_mm` `None` for a blind hole, whose face runs down from `hi_mm`, the face it is
    drilled from, to its record's drill depth), and its instances' axes, as many as its record's
    `count`."""

    hole_type: Literal["tapped", "clearance"]
    size: str | None
    diameter_mm: float
    lo_mm: float | None
    hi_mm: float
    axes: tuple[tuple[float, float], ...]


HOLES: dict[str, HoleShape] = {
    "taps": HoleShape("tapped", None, 4.2, None, 0.0, TAP_AXES),
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, COVER_THICKNESS_MM, TAP_AXES),
    "dowels": HoleShape("clearance", "Ø5.0", 5.0, -20.0, -RELIEF_MM, DOWEL_AXES),
    "cdowels": HoleShape("clearance", "Ø5.1", 5.1, 0.0, COVER_THICKNESS_MM, DOWEL_AXES),
    "top_taps": HoleShape("tapped", None, 3.3, None, COVER_THICKNESS_MM, TOP_AXES),
}
"""The screw holes, each cover hole over a housing hole, coaxial and adjacent at the joint face
z = 0, as a joint is; the dowel holes, the housing's from its relief floor down to z = -20; and
the cover's own tapped holes, drilled down from its top face, over no other hole, so the joint
map pairs none of them. Every cover face lies inside the cover, so its face boxes measure the
clamped 12 mm."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "housing_doc": DocumentPlace(tree=Tree()),
    "cover_doc": DocumentPlace(tree=Tree()),
    "shaft_doc": DocumentPlace(),
    "gear_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "housing_drw": DocumentPlace(),
    "cover_drw": DocumentPlace(),
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
    "dowels": HolePlace(component="housing", count=len(DOWEL_AXES)),
    "cdowels": HolePlace(component="cover", count=len(DOWEL_AXES)),
    "top_taps": HolePlace(
        component="cover",
        thread="M4x0.7",
        thread_depth_mm=8.0,
        hole_depth_mm=10.0,
        count=len(TOP_AXES),
    ),
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
    "shaft_housing": ContactPlace(a="shaft", b="housing"),
    "gear_shaft": ContactPlace(a="gear", b="shaft"),
    # Both fits drawn for clearance (`seeds.CLEARANCE`, the clean fit), so nothing a correct
    # reviewer checks on the base is anything but clear.
    "shaft_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=SHAFT_DIAMETER_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "shaft_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=SHAFT_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    "gear_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=SHAFT_DIAMETER_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "gear_seat": DimensionPlace(
        drawing="assy_drw", nominal_mm=SHAFT_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The complete callouts `seeds.FULL_CALLOUT` writes for `taps` and `top_taps`: count, thread,
    # thread depth.
    "housing_callout": DimensionPlace(
        drawing="housing_drw", nominal_mm=9.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 9"
    ),
    "cover_callout": DimensionPlace(
        drawing="cover_drw", nominal_mm=8.0, limits=None, text="4X M4x0.7 - 6H THREAD ↧ 8"
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
    """The centre of round component `component`, on the shaft's axis."""
    x, y = SHAFT_AXIS
    return (x, y, ON_SHAFT[component][1])


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the housing fixed); the hole rows
    with each record's thread, depths and offset; the round parts' meshes on the shaft's axis;
    the screws with their fastener rows, seated unless a record says not, the M5 x 20 document
    laid first as `screw_doc` and another thread or length given a document of its own; the
    contacts' interference rows. Then the bought documents moved into the bought folder and the
    custom parts' trees laid; then the three ingested drawings, the assembly's with its note, and
    every drawn dimension, in place order. Every document is laid opened: no lori case leaves one
    unread, and a record that asks it is refused."""
    if variant is not None:
        raise ValueError(f"design lori has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design lori lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "lori assy")
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
            lo_mm = shape.hi_mm - record.hole_depth_mm
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


DESIGN = Design(name="lori", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
"""A joint planted on `screw_a`, its decoy the sibling joint on `screw_b`: an M4 screw in the
housing's M5x0.8 tapped hole, as `thread_mismatch_unplaced` plants it."""

COVER_CALLOUT = {"callout": "cover_callout", "hole": "top_taps"}
"""The cover drawing's callout of the cover's own tapped holes."""

SHAFT_FIT = {
    "bore": "shaft_bore",
    "shaft": "shaft_dia",
    "sibling_bore": "gear_bore",
    "sibling_shaft": "gear_seat",
}
"""The shaft in its bore, which must turn and slide; its sibling the gear's bore on the shaft's
gear seat, drawn on the same sheet from dimensions of its own, so the sibling fit stays clean in
every form."""

HOUSING_CALLOUT = {"callout": "housing_callout", "hole": "taps"}
"""The housing drawing's callout of the tapped holes the cover screws go into."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="lori-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.THREAD_MISMATCH_UNPLACED, JOINT, CURRENT),
            Seed(seeds.CALLOUT_COUNT_DIFFERS, COVER_CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="lori-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.FIT_TRANSITION, SHAFT_FIT, CURRENT),
            Seed(seeds.CALLOUT_DRILL_ONLY, HOUSING_CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin."""
