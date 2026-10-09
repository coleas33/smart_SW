"""The venta design (`cases.md` 6.2): a two-piece clamp block: cap screws, a clamped bore.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The block's two halves meet at its split plane, z = 0, through the axis of the Ø20 bore they are
bored to together, which runs along x through the block's 50 mm length: the custom clamp base,
fixed, 50 x 70 mm in plan on z = -25 to 0, holds the bore's lower half, and the custom clamp top,
on z = 0 to 20, its upper half. Four bought M5 socket head cap screws draw the top down through
its M5 clearance holes into the base's four blind M5x0.8 tapped holes, two on each side of the
bore, and the top carries two blind M4x0.7 tapped holes, empty, in its top face for what it
carries. A bought Ø20 shaft is held in the clamped bore and runs out past both end faces of the
block; a bought spacer sits on it 2 mm clear of one. The bore is cut, not a Hole Wizard hole.
The top is each screw's one clamped layer, whose face boxes measure its 20 mm along the screw
(`tools/checks_fastener.py` `_bbox_extent_mm`): its clearance holes' faces run through it from
face to face, its tapped holes' lie inside it. Every name is the example profile's: the
assembly, the base and the top `EX-1109-..` with the data card, the revision, the hygiene number
equal to the stem and a summary unique in the package; the shaft, the spacer and the screws
bought, in the profile's bought folder with a vendor property, each screw with its fastener row
(GN-2). Each custom part carries `spec.tree_specs`' compliant tree. No tolerance source anywhere
(rule 4): the shaft's fit in the clamped bore and the spacer's on the shaft are drawn on the
assembly's ingested sheet only. The base's own drawing draws the callout of its tapped holes
alone, and the top's own drawing the callout of its own (rule 5). The interference rows are
zero-volume contacts: the shaft line to line in each half's bore, the spacer line to line on the
shaft.

**Places** (rule 2): the documents `assy`, `base_doc`, `top_doc`, `shaft_doc`, `spacer_doc`,
`screw_doc` (the M5 x 30 screws'), `assy_drw`, `base_drw` and `top_drw`; the components `base`,
`top`, `shaft` and `spacer`; the Hole Wizard rows `taps` (the base's tapped holes) under `clrs`
(the top's clearance holes), four instances each, and `top_taps` (the top's own tapped holes), two
instances; the fasteners `screw_a` to `screw_d`, one into each instance of `taps`, `screw_b` the
sibling joint of `screw_a` (rule 6); the contacts `shaft_base`, `shaft_top` and `spacer_shaft`; on
the assembly's sheet the clamped bore `clamp_bore` over the shaft's diameter `shaft_dia`, and its
sibling fit (rule 6), the spacer's bore `spacer_bore` over the shaft's spacer seat `spacer_seat`;
and the callouts `base_callout`, on the base's drawing, and `top_callout`, on the top's.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `venta-1`: `engagement_unplaced` on `screw_a`, an M5 screw reaching one diameter into the
  base's M5x0.8 `taps`, and `callout_thread_differs` on the base's own drawing.
- `venta-2`: `fit_limit_missing` on the clamped bore, drawn with no tolerance over a toleranced
  shaft, the spacer's fit staying clear, and `callout_count_differs` on the top's own drawing.
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

ASSY_STEM, BASE_STEM, TOP_STEM = "EX-1109-00", "EX-1109-01", "EX-1109-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the shaft, the spacer and the screws bought (`generator.md`
5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

BLOCK_LENGTH_MM, BLOCK_WIDTH_MM = 50.0, 70.0
BASE_HEIGHT_MM = 25.0
TOP_THICKNESS_MM = 20.0
"""The block is 50 mm along its bore and 70 mm across it; the base lies from z = -25 to 0, the
top from 0 to 20: the top is the stack each screw clamps."""

BORE_DIAMETER_MM = 20.0
HALF_BORE_MM3 = math.pi / 8.0 * BORE_DIAMETER_MM**2 * BLOCK_LENGTH_MM
"""The clamped bore, Ø20 through the block's length, split by the plane the halves meet at: each
half holds half its volume. Cut, not a Hole Wizard hole."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary), each half a block less its half of the bore
    "base_doc": (
        BASE_STEM,
        round(BLOCK_LENGTH_MM * BLOCK_WIDTH_MM * BASE_HEIGHT_MM - HALF_BORE_MM3, 6),
        "venta clamp base",
    ),
    "top_doc": (
        TOP_STEM,
        round(BLOCK_LENGTH_MM * BLOCK_WIDTH_MM * TOP_THICKNESS_MM - HALF_BORE_MM3, 6),
        "venta clamp top",
    ),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

BORE_AXIS = (35.0, 0.0)
X = (1.0, 0.0, 0.0)
Z = (0.0, 0.0, 1.0)
"""The (y, z) of the clamped bore's axis, which runs along x in the split plane, mid-width; every
hole's axis is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float, float]] = {
    # document place: (stem, description, outside and inside diameter, length) in mm
    "shaft_doc": (
        "FICT-SHAFT-20X90-0001",
        "SHAFT, Ø20 X 90 MM, FICTIONAL",
        BORE_DIAMETER_MM,
        0.0,
        90.0,
    ),
    "spacer_doc": (
        "FICT-SPACER-20X30X10-0001",
        "SPACER, Ø20 X Ø30 X 10 MM, FICTIONAL",
        30.0,
        BORE_DIAMETER_MM,
        10.0,
    ),
}
"""The bought round parts, steel; each a mesh with no extracted face, so the joint map, which
reads faces in hole instances, takes neither for a pin."""

ON_SHAFT: dict[str, tuple[str, float]] = {
    # component place: (its document place, the x of its centre)
    "shaft": ("shaft_doc", 35.0),
    "spacer": ("spacer_doc", 57.0),
}
"""Each round component on the bore's axis: the shaft from x = -10 to 80, through the block's
x = 0 to 50; the spacer on it, 52 to 62, 2 mm clear of the block's end face, so it touches the
shaft alone."""

DRAWINGS: dict[str, tuple[str, str]] = {
    "assy_drw": (ASSY_STEM, "venta assy drawing"),
    "base_drw": (BASE_STEM, "venta clamp base drawing"),
    "top_drw": (TOP_STEM, "venta clamp top drawing"),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary)."""

SCREW_AXES = ((12.0, 10.0), (38.0, 10.0), (12.0, 60.0), (38.0, 60.0))
TOP_AXES = ((25.0, 10.0), (25.0, 60.0))
"""The (x, y) of the screw holes' and the top's own tapped holes' axes, all along z: two screw
holes on each side of the bore, which spans y = 25 to 45, and a tapped hole between each side's
two, at least 13 mm from either."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 30.0
"""The top's screws, all one document (`screw_doc`): M5 x 30 reaches 10 mm past the top, inside
the 11 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives, so a twin's
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
    "taps": HoleShape("tapped", None, 4.2, None, 0.0, SCREW_AXES),
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, TOP_THICKNESS_MM, SCREW_AXES),
    "top_taps": HoleShape("tapped", None, 3.3, None, TOP_THICKNESS_MM, TOP_AXES),
}
"""The screw holes, each top hole over a base hole, coaxial and adjacent at the split plane
z = 0, as a joint is; and the top's own tapped holes, drilled down from its top face beside the
bore, to z = 12, over no other hole, so the joint map pairs none of them.
Every top face lies inside the top, so its face boxes measure the clamped 20 mm."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "base_doc": DocumentPlace(tree=Tree()),
    "top_doc": DocumentPlace(tree=Tree()),
    "shaft_doc": DocumentPlace(),
    "spacer_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "base_drw": DocumentPlace(),
    "top_drw": DocumentPlace(),
    "base": ComponentPlace(document="base_doc"),
    "top": ComponentPlace(document="top_doc"),
    **{name: ComponentPlace(document=document) for name, (document, _) in ON_SHAFT.items()},
    "taps": HolePlace(
        component="base",
        thread="M5x0.8",
        thread_depth_mm=11.0,
        hole_depth_mm=14.0,
        count=len(SCREW_AXES),
    ),
    "clrs": HolePlace(component="top", count=len(SCREW_AXES)),
    "top_taps": HolePlace(
        component="top",
        thread="M4x0.7",
        thread_depth_mm=6.0,
        hole_depth_mm=8.0,
        count=len(TOP_AXES),
    ),
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("top",),
            clamp_mm=TOP_THICKNESS_MM,
        )
        for screw in SCREWS
    },
    "shaft_base": ContactPlace(a="shaft", b="base"),
    "shaft_top": ContactPlace(a="shaft", b="top"),
    "spacer_shaft": ContactPlace(a="spacer", b="shaft"),
    # Both fits drawn for clearance (`seeds.CLEARANCE`, the clean fit), so nothing a correct
    # reviewer checks on the base is anything but clear.
    "clamp_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=BORE_DIAMETER_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "shaft_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=BORE_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    "spacer_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=BORE_DIAMETER_MM, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "spacer_seat": DimensionPlace(
        drawing="assy_drw", nominal_mm=BORE_DIAMETER_MM, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The complete callouts `seeds.FULL_CALLOUT` writes for `taps` and `top_taps`: count, thread,
    # thread depth.
    "base_callout": DimensionPlace(
        drawing="base_drw", nominal_mm=11.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 11"
    ),
    "top_callout": DimensionPlace(
        drawing="top_drw", nominal_mm=6.0, limits=None, text="2X M4x0.7 - 6H THREAD ↧ 6"
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
    """The centre of round component `component`, on the clamped bore's axis."""
    y, z = BORE_AXIS
    return (ON_SHAFT[component][1], y, z)


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the clamp base fixed); the hole rows
    with each record's thread, depths and offset; the round parts' meshes on the bore's axis; the
    screws with their fastener rows, seated unless a record says not, the M5 x 30 document laid
    first as `screw_doc` and another thread or length given a document of its own; the contacts'
    interference rows. Then the bought documents moved into the bought folder and the custom
    parts' trees laid; then the three ingested drawings and every drawn dimension, in place
    order. Every document is laid opened: no venta case leaves one unread, and a record that asks
    it is refused."""
    if variant is not None:
        raise ValueError(f"design venta has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design venta lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "venta assy")
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
    for name in ("base", "top", *ON_SHAFT):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=transform(_on_shaft(name), X) if name in ON_SHAFT else None,
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
            cylinder_mesh(_on_shaft(name), X, outside_mm, -length_mm / 2.0, length_mm / 2.0),
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
        row.model_copy(update={"is_fixed": row.id == ids["base"]}) for row in package.components
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


DESIGN = Design(name="venta", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
"""A joint planted on `screw_a`, its decoy the sibling joint on `screw_b`: an M5 screw reaching one
diameter into the base's M5x0.8 tapped hole, as `engagement_unplaced` plants it."""

BASE_CALLOUT = {"callout": "base_callout", "hole": "taps"}
"""The base drawing's callout of the tapped holes the cap screws go into."""

CLAMP_FIT = {
    "bore": "clamp_bore",
    "shaft": "shaft_dia",
    "sibling_bore": "spacer_bore",
    "sibling_shaft": "spacer_seat",
}
"""The shaft in the clamped bore; its sibling the spacer's bore on the shaft's spacer seat, drawn
on the same sheet from dimensions of its own, so the clamped bore drawn with no tolerance leaves
it clear."""

TOP_CALLOUT = {"callout": "top_callout", "hole": "top_taps"}
"""The top drawing's callout of the top's own tapped holes."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="venta-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.ENGAGEMENT_UNPLACED, JOINT, CURRENT),
            Seed(seeds.CALLOUT_THREAD_DIFFERS, BASE_CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="venta-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.FIT_LIMIT_MISSING, CLAMP_FIT, CURRENT),
            Seed(seeds.CALLOUT_COUNT_DIFFERS, TOP_CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin."""
