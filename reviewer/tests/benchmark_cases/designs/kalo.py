"""The kalo design (`cases.md` 6.2 and 6.3): a plate on two dowel pins, a cover screwed to it.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom plate, fixed, lies below z = 0 with two dowel pins line to line in its Ø3.0 holes and
two M5x0.8 blind tapped holes; the custom cover sits on it, over the pins through its Ø3.1 holes,
clamped by two bought M5 socket head screws through its M5 clearance holes into the plate's. The
pins and dowel holes follow `build_small_assembly`'s values (3 mm pins, dowel holes of 3.0 and
3.1 mm; `tests/fixtures/mechanical/generate_fixtures.py`), the base the kalo anchors vary. Every
name is the example profile's: the assembly, the plate and the cover `EX-1101-..` with the data
card, the revision, the hygiene number equal to the stem and a summary unique in the package;
the pins and the screws bought, in the profile's bought folder with a vendor property, each
screw with its fastener row (GN-2). Each custom part carries `spec.tree_specs`' compliant tree.
No tolerance source anywhere: every limit is drawn on an ingested sheet only, the assembly's,
which draws the pin's two fits (design rule 4), or the plate's own drawing, which draws its
tapped-hole callout alone (rule 5).

**Places** (rule 2): the documents `assy`, `plate_doc`, `cover_doc`, `pin_doc`, `assy_drw` and
`plate_drw`; the components `plate`, `cover`, `pin_a` and `pin_b`; the Hole Wizard rows `taps`
(the plate's two tapped holes), `clrs` (the cover's clearance holes over them), `dowels` (the
plate's Ø3.0 dowel holes) and `cdowels` (the cover's Ø3.1 ones), two instances each; the
fasteners `screw_a` and `screw_b`, one into each instance of `taps`, each the other's sibling
joint (rule 6); on the assembly's sheet the pin's diameter `pin_dia` over its two bores,
`plate_bore` and `cover_bore`, so each fit is the other's sibling fit (rule 6); and `callout`,
the plate drawing's tapped-hole callout.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `kalo-1`: `thread_mismatch_unplaced` on `screw_a`, and `fit_limit_missing` on the pin in the
  plate, the plate's bore drawn with no tolerance on the assembly's sheet.
- `kalo-2`: `bottoming_unplaced` on `screw_a`, and `callout_drill_only` on the plate's own drawing.
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
from tests.support.drawings import SheetBuilder
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

ASSY_STEM, PLATE_STEM, COVER_STEM = "EX-1101-00", "EX-1101-01", "EX-1101-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

PIN_STEM = "FICT-PIN-3X20-0001"
"""The bought dowel pin, Ø3 x 20: through the plate and the cover."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the pins and the screws bought (`generator.md` 5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

PLATE_THICKNESS_MM = 16.0
COVER_THICKNESS_MM = 4.0
"""The plate lies from z = -16 to 0, the cover from 0 to 4: the stack each screw clamps."""

PIN_DIAMETER_MM = 3.0

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary), each part 100 x 60 mm in plan
    "plate_doc": (PLATE_STEM, 100.0 * 60.0 * PLATE_THICKNESS_MM, "kalo plate"),
    "cover_doc": (COVER_STEM, 100.0 * 60.0 * COVER_THICKNESS_MM, "kalo cover"),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

DRAWINGS: dict[str, tuple[str, str]] = {
    "assy_drw": (ASSY_STEM, "kalo assy drawing"),
    "plate_drw": (PLATE_STEM, "kalo plate drawing"),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary)."""

SCREW_AXES = ((20.0, 15.0), (80.0, 15.0))
DOWEL_AXES = ((20.0, 45.0), (80.0, 45.0))
"""The (x, y) of the screw holes' and the dowel holes' axes, all along z."""

PINS: dict[str, tuple[float, float]] = {"pin_a": DOWEL_AXES[0], "pin_b": DOWEL_AXES[1]}
"""Each pin's axis: one in each instance of `dowels` and `cdowels`."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1}
"""Each screw's instance of the hole its record names."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""

Z = (0.0, 0.0, 1.0)


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
    "taps": HoleShape("tapped", None, 4.2, None, 0.0, SCREW_AXES),
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, COVER_THICKNESS_MM, SCREW_AXES),
    "dowels": HoleShape("clearance", "Ø3.0", 3.0, -PLATE_THICKNESS_MM, 0.0, DOWEL_AXES),
    "cdowels": HoleShape("clearance", "Ø3.1", 3.1, 0.0, COVER_THICKNESS_MM, DOWEL_AXES),
}
"""The two hole pairs: each coaxial and adjacent at the joint face z = 0, as a joint is."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "plate_doc": DocumentPlace(tree=Tree()),
    "cover_doc": DocumentPlace(tree=Tree()),
    "pin_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "plate_drw": DocumentPlace(),
    "plate": ComponentPlace(document="plate_doc"),
    "cover": ComponentPlace(document="cover_doc"),
    "pin_a": ComponentPlace(document="pin_doc"),
    "pin_b": ComponentPlace(document="pin_doc"),
    "taps": HolePlace(
        component="plate",
        thread="M5x0.8",
        thread_depth_mm=9.0,
        hole_depth_mm=12.0,
        count=len(SCREW_AXES),
    ),
    "clrs": HolePlace(component="cover", count=len(SCREW_AXES)),
    "dowels": HolePlace(component="plate", count=len(DOWEL_AXES)),
    "cdowels": HolePlace(component="cover", count=len(DOWEL_AXES)),
    # M5 x 12 reaches 8 mm past the cover: inside the 9 mm thread, above the rule's 7.5 mm, the
    # length `seeds.CLEAN_JOINT` gives, so a twin's screws are the base's.
    "screw_a": ScrewPlace(
        thread="M5-0.8",
        length_mm=12.0,
        hole="taps",
        clamped=("cover",),
        clamp_mm=COVER_THICKNESS_MM,
    ),
    "screw_b": ScrewPlace(
        thread="M5-0.8",
        length_mm=12.0,
        hole="taps",
        clamped=("cover",),
        clamp_mm=COVER_THICKNESS_MM,
    ),
    # Both fits drawn for clearance (`seeds.CLEARANCE`, the clean fit), so nothing a correct
    # reviewer checks on the base is anything but clear.
    "plate_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=3.0, limits=seeds.CLEARANCE[0], prefix="2X Ø"
    ),
    "cover_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=3.1, limits=seeds.CLEARANCE[0], prefix="2X Ø"
    ),
    "pin_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=PIN_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The complete callout `seeds.FULL_CALLOUT` writes for `taps`: count, thread, thread depth.
    "callout": DimensionPlace(
        drawing="plate_drw", nominal_mm=9.0, limits=None, text="2X M5x0.8 - 6H THREAD ↧ 9"
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


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents, the components (the plate fixed), the hole rows with
    each record's thread, depths and offset, the pins' faces and meshes, the screws with their
    fastener rows, seated unless a record says not; the bought documents moved into the bought
    folder and the custom parts' trees laid; then the two ingested drawings and every drawn
    dimension, in place order."""
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "kalo assy")
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
    pin_volume_mm3 = round(
        math.pi / 4.0 * PIN_DIAMETER_MM**2 * (PLATE_THICKNESS_MM + COVER_THICKNESS_MM), 6
    )
    ids["pin_doc"] = builder.document(
        PIN_STEM,
        "part",
        material="Alloy Steel",
        mass_kg=_mass_kg(pin_volume_mm3, STEEL_DENSITY_KG_M3),
        volume_mm3=pin_volume_mm3,
        properties={VENDOR: "FICT", "Description": "PIN, DOWEL Ø3 X 20 MM, FICTIONAL"},
    )
    for name in ("plate", "cover", *PINS):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        axis = PINS.get(name)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=None if axis is None else transform((*axis, -PLATE_THICKNESS_MM)),
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
    for name, (x, y) in PINS.items():
        builder.cylinder_face(
            str(ids[name]),
            origin_mm=(x, y, 0.0),
            direction=Z,
            diameter_mm=PIN_DIAMETER_MM,
            lo_mm=-PLATE_THICKNESS_MM,
            hi_mm=COVER_THICKNESS_MM,
        )
        builder.mesh(
            str(ids[name]),
            cylinder_mesh((x, y, 0.0), Z, PIN_DIAMETER_MM, -PLATE_THICKNESS_MM, COVER_THICKNESS_MM),
        )

    # One screw document per thread and length, as a vendor's part is, each screw an instance.
    screw_documents: dict[tuple[str, float], str] = {}
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

    built = builder.build()
    package = built.package
    for name, component in screws.items():
        ids[name] = next(row.id for row in package.fasteners if row.component_id == component)
    bought = {str(ids["pin_doc"]), *screw_documents.values()}
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


DESIGN = Design(name="kalo", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
"""A joint planted on `screw_a`, its decoy the sibling joint on `screw_b`."""

PIN_FIT = {
    "bore": "plate_bore",
    "shaft": "pin_dia",
    "sibling_bore": "cover_bore",
    "sibling_shaft": "pin_dia",
}
"""The pin in the plate, its sibling the pin in the cover: one drawn pin over two drawn bores."""

CALLOUT = {"callout": "callout", "hole": "taps"}
"""The plate drawing's callout of the tapped holes the screws go into."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="kalo-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.THREAD_MISMATCH_UNPLACED, JOINT, CURRENT),
            Seed(seeds.FIT_LIMIT_MISSING, PIN_FIT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.BOTTOMING_UNPLACED, JOINT, CURRENT),
            Seed(seeds.CALLOUT_DRILL_ONLY, CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin; the anchor cases follow (T133, T134)."""
