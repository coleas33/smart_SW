"""The rusk design (`cases.md` 6.2): a carriage on a rail: shim stack, screws into the rail.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom rail, fixed, a steel bar 240 x 40 mm in plan, lies on z = -20 to 0, a Ø32 recess cut
5 mm down from its top face under the carriage's middle; the custom carriage, a steel block 80 x 40
mm in plan on z = 0 to 12, sits on the rail's top face, screwed down by four bought M5 socket head
screws through its M5 clearance holes into the rail's four blind M5x0.8 tapped holes, and carries
four blind M6x1.0 tapped holes, empty, in its top face for what it carries. In the recess lies a
stack of two bought Ø30 shims, 2 mm each, leaving 1 mm of clearance under the carriage's
underside. The recess is cut, not a Hole Wizard hole. The carriage is each screw's one clamped
layer, a flat plate whose face boxes measure its 12 mm along the screw (`tools/checks_fastener.py`
`_bbox_extent_mm`): its clearance holes' faces run through it from face to face, its tapped holes'
lie inside it. Every name is the example profile's: the assembly, the rail and the carriage
`EX-1107-..` with the data card, the revision, the hygiene number equal to the stem and a summary
unique in the package; the shims and the screws bought, in the profile's bought folder with a
vendor property, each screw with its fastener row (GN-2). Each custom part carries
`spec.tree_specs`' compliant tree. No tolerance source anywhere (rule 4): the shim stack is drawn
on the assembly's ingested sheet only. The rail's own drawing draws the callout of its tapped holes
alone, and the carriage's own drawing the callout of its own (rule 5). The interference rows are
zero-volume contacts: the lower shim on the recess floor, the upper shim on the lower.

**Places** (rule 2): the documents `assy`, `rail_doc`, `carriage_doc`, `shim_doc`, `screw_doc`
(the M5 x 20 screws'), `assy_drw`, `rail_drw` and `carriage_drw`; the components `rail`,
`carriage`, `shim_a` (the lower shim) and `shim_b`; the Hole Wizard rows `taps` (the rail's tapped
holes) under `clrs` (the carriage's clearance holes), four instances each, and `top_taps` (the
carriage's own tapped holes), four instances; the fasteners `screw_a` to `screw_d`, one into each
instance of `taps`, `screw_b` the sibling joint of `screw_a` (rule 6); the contacts `shim_a_rail`
and `shims`; on the assembly's sheet the shim stack: the recess's depth `recess_depth`, the shims'
widths `shim_a_width` and `shim_b_width` inside it, and the clearance under the carriage
`carriage_gap`, its target, the upper shim the contributor a decoy leaves out (rule 6); and the
callouts `rail_callout`, on the rail's drawing, and `carriage_callout`, on the carriage's.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `rusk-1`: `bottoming_unplaced` on `screw_a`, an M5 screw reaching 2 mm past the rail's usable
  thread, and `callout_thread_differs` on the rail's own drawing.
- `rusk-2`: `stack_out_of_gap` on the shim stack, its three contributors toleranced wide enough
  that the worst-case band leaves the drawn clearance, and `callout_drill_only` on the carriage's
  own drawing.
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
    laid_after,
    set_aside,
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

ASSY_STEM, RAIL_STEM, CARRIAGE_STEM = "EX-1107-00", "EX-1107-01", "EX-1107-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the shims and the screws bought (`generator.md` 5.2)."""

RAIL_HEIGHT_MM = 20.0
CARRIAGE_THICKNESS_MM = 12.0
"""The rail lies from z = -20 to 0, the carriage from 0 to 12: the carriage is the stack each
screw clamps."""

RECESS_DIAMETER_MM, RECESS_DEPTH_MM = 32.0, 5.0
SHIM_DIAMETER_MM, SHIM_WIDTH_MM = 30.0, 2.0
"""The rail's Ø32 recess, cut 5 mm down from its top face, and the Ø30 x 2 shims stacked in it."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary)
    # a 240 x 40 x 20 mm bar less its recess
    "rail_doc": (
        RAIL_STEM,
        round(
            240.0 * 40.0 * RAIL_HEIGHT_MM - math.pi / 4.0 * RECESS_DIAMETER_MM**2 * RECESS_DEPTH_MM,
            6,
        ),
        "rusk rail",
    ),
    # an 80 x 40 x 12 mm block
    "carriage_doc": (CARRIAGE_STEM, 80.0 * 40.0 * CARRIAGE_THICKNESS_MM, "rusk block"),
}
"""The custom parts, both steel, as a rail and its carriage are, their masses from their
volumes."""

RECESS_AXIS = (120.0, 20.0)
Z = (0.0, 0.0, 1.0)
"""The (x, y) of the recess's axis, under the middle of the carriage's x = 80 to 160; it, and
every hole's axis, is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float]] = {
    # document place: (stem, description, diameter, length) in mm
    "shim_doc": (
        "FICT-SHIM-30X2-0001",
        "SHIM, Ø30 X 2 MM, FICTIONAL",
        SHIM_DIAMETER_MM,
        SHIM_WIDTH_MM,
    ),
}
"""The bought round part, steel; a mesh with no extracted face, so the joint map, which reads
faces in hole instances, takes it for no pin."""

ON_AXIS: dict[str, tuple[str, float]] = {
    # component place: (its document place, the z of its centre)
    "shim_a": ("shim_doc", -4.0),
    "shim_b": ("shim_doc", -2.0),
}
"""Each shim on the recess's axis: the lower on the recess floor, z = -5 to -3; the upper on it,
-3 to -1; the clearance, -1 to the carriage's underside at 0."""

DRAWINGS: dict[str, tuple[str, str]] = {
    "assy_drw": (ASSY_STEM, "rusk assy drawing"),
    "rail_drw": (RAIL_STEM, "rusk rail drawing"),
    "carriage_drw": (CARRIAGE_STEM, "rusk block drawing"),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary)."""

TAP_AXES = ((90.0, 8.0), (150.0, 8.0), (90.0, 32.0), (150.0, 32.0))
TOP_AXES = ((105.0, 8.0), (135.0, 8.0), (105.0, 32.0), (135.0, 32.0))
"""The (x, y) of the screw holes' and of the carriage's own tapped holes' axes, all along z,
inside the carriage's x = 80 to 160 and y = 0 to 40, each 15 mm from the nearest other, the screw
holes clear of the recess, x = 104 to 136."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 20.0
"""The carriage's screws, all one document (`screw_doc`): M5 x 20 reaches 8 mm past the carriage,
inside the 9 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives, so a twin's
screws are the base's."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""

STACK_LIMITS: Limits = ("symmetric", 0.05)
"""Each shim-stack contributor's drawn tolerance in the base: three of them hold the clearance to
1 ± 0.15 mm, inside its drawn 1 ± 0.5 mm, so the stack is clean wherever no form tolerances it
(`seeds.STACK_OUT_OF_GAP` draws ± 0.34 mm each to plant, ± 0.083 mm in its clean form)."""


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
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, CARRIAGE_THICKNESS_MM, TAP_AXES),
    "top_taps": HoleShape("tapped", None, 5.0, None, CARRIAGE_THICKNESS_MM, TOP_AXES),
}
"""The screw holes, each carriage hole over a rail hole, coaxial and adjacent at the joint face
z = 0, as a joint is; and the carriage's own tapped holes, drilled down from its top face, over
no other hole, so the joint map pairs none of them. Every carriage face lies inside the carriage,
so its face boxes measure the clamped 12 mm."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "rail_doc": DocumentPlace(tree=Tree()),
    "carriage_doc": DocumentPlace(tree=Tree()),
    "shim_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "rail_drw": DocumentPlace(),
    "carriage_drw": DocumentPlace(),
    "rail": ComponentPlace(document="rail_doc"),
    "carriage": ComponentPlace(document="carriage_doc"),
    **{name: ComponentPlace(document=document) for name, (document, _) in ON_AXIS.items()},
    "taps": HolePlace(
        component="rail",
        thread="M5x0.8",
        thread_depth_mm=9.0,
        hole_depth_mm=12.0,
        count=len(TAP_AXES),
    ),
    "clrs": HolePlace(component="carriage", count=len(TAP_AXES)),
    "top_taps": HolePlace(
        component="carriage",
        thread="M6x1.0",
        thread_depth_mm=8.0,
        hole_depth_mm=10.0,
        count=len(TOP_AXES),
    ),
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("carriage",),
            clamp_mm=CARRIAGE_THICKNESS_MM,
        )
        for screw in SCREWS
    },
    "shim_a_rail": ContactPlace(a="shim_a", b="rail"),
    "shims": ContactPlace(a="shim_a", b="shim_b"),
    # The shim stack, 5 - 2 - 2 = 1 mm nominal, strictly inside its target.
    "recess_depth": DimensionPlace(
        drawing="assy_drw", nominal_mm=RECESS_DEPTH_MM, limits=STACK_LIMITS
    ),
    "shim_a_width": DimensionPlace(
        drawing="assy_drw", nominal_mm=SHIM_WIDTH_MM, limits=STACK_LIMITS
    ),
    "shim_b_width": DimensionPlace(
        drawing="assy_drw", nominal_mm=SHIM_WIDTH_MM, limits=STACK_LIMITS
    ),
    "carriage_gap": DimensionPlace(drawing="assy_drw", nominal_mm=1.0, limits=("symmetric", 0.5)),
    # The complete callouts `seeds.FULL_CALLOUT` writes for `taps` and `top_taps`: count, thread,
    # thread depth.
    "rail_callout": DimensionPlace(
        drawing="rail_drw", nominal_mm=9.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 9"
    ),
    "carriage_callout": DimensionPlace(
        drawing="carriage_drw", nominal_mm=8.0, limits=None, text="4X M6x1.0 - 6H THREAD ↧ 8"
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
    """The centre of round component `component`, on the recess's axis."""
    x, y = RECESS_AXIS
    return (x, y, ON_AXIS[component][1])


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the rail fixed); the hole rows with
    each record's thread, depths and offset; the shims' meshes on the recess's axis; the screws
    with their fastener rows, seated unless a record says not, the M5 x 20 document laid first as
    `screw_doc` and another thread or length given a document of its own; the contacts'
    interference rows. Then the bought documents moved into the bought folder and the custom
    parts' trees laid; then the three ingested drawings and every drawn dimension, in place
    order, a planted screw's document after them (owner decision 64A). Every document is laid
    opened: no rusk case leaves one unread, and a record that asks it is refused."""
    if variant is not None:
        raise ValueError(f"design rusk has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design rusk lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "rusk assy")
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
    for name in ("rail", "carriage", *ON_AXIS):
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
        row.model_copy(update={"is_fixed": row.id == ids["rail"]}) for row in package.components
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

    # A planted screw's document is the case's alone: set aside while the drawings are laid and
    # laid after them, the case and its twin lay every document they share under one id (owner
    # decision 64A).
    planted = [
        document
        for drawn, document in screw_documents.items()
        if drawn != (SCREW_THREAD, SCREW_LENGTH_MM)
    ]
    package, aside = set_aside(package, planted, drawings=len(DRAWINGS))
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
    return Laid(package=laid_after(sheets.build(), aside), meshes=built.meshes, ids=ids)


DESIGN = Design(name="rusk", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
"""A joint planted on `screw_a`, its decoy the sibling joint on `screw_b`: an M5 screw reaching
past the rail's usable thread, as `bottoming_unplaced` plants it."""

RAIL_CALLOUT = {"callout": "rail_callout", "hole": "taps"}
"""The rail drawing's callout of the tapped holes the screws go into."""

SHIM_STACK = {
    "enclosing": "recess_depth",
    "inside_1": "shim_a_width",
    "inside_2": "shim_b_width",
    "target": "carriage_gap",
}
"""The clearance under the carriage: the recess's depth less the two shims, against the drawn
clearance; its decoy the stack with the upper shim left out."""

CARRIAGE_CALLOUT = {"callout": "carriage_callout", "hole": "top_taps"}
"""The carriage drawing's callout of its own tapped holes."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="rusk-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.BOTTOMING_UNPLACED, JOINT, CURRENT),
            Seed(seeds.CALLOUT_THREAD_DIFFERS, RAIL_CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="rusk-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.STACK_OUT_OF_GAP, SHIM_STACK, CURRENT),
            Seed(seeds.CALLOUT_DRILL_ONLY, CARRIAGE_CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin."""
