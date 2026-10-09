"""The okta design (`cases.md` 6.2): a clevis, a pin through both legs, two bushings; a base with
three dowel-hole pairs.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom base, fixed, lies on z = -20 to 0; the custom clevis's foot sits on it, z = 0 to 12,
screwed down by four bought M5 socket head screws through the foot's M5 clearance holes into the
base's four blind M5x0.8 tapped holes, and its two legs rise from the foot. A bought Ø10 pin runs
along x through both legs' bores, and two bought bushings sit on it between the legs, one against
each leg's inner face, centring the mating eye, which is not in this assembly. The foot is each
screw's one clamped layer, a flat plate whose face boxes measure its 12 mm along the screw
(`tools/checks_fastener.py` `_bbox_extent_mm`): the legs' bores are cut, not Hole Wizard holes, so
no extracted face of the clevis stands above the foot. Three dowel-hole pairs, the base's Ø5.0
under the foot's Ø5.1, stand empty; the base is relieved 2 mm around its dowel holes, so their
faces stand 2 mm under the foot's, beyond the joint rules' 1 mm adjacency, and the joint map pairs
none (`joint_absent`; rule 6). Every name is the example profile's: the assembly, the base and the
clevis `EX-1103-..` with the data card, the revision, the hygiene number equal to the stem and a
summary unique in the package; the pin, the bushings and the screws bought, in the profile's
bought folder with a vendor property, each screw with its fastener row (GN-2). Each custom part
carries `spec.tree_specs`' compliant tree. No tolerance source anywhere (rule 4): the pin's fit in
each leg and the dowel holes' position tolerance are drawn on the assembly's ingested sheet only,
beside a note that the pin is a slip fit in both legs, the intent `fit_interference_unintended`'s
plant departs from. Leg A's bore locates the pin; leg B's is drawn free, so the legs need not be
bored in line, and it clears the pin whatever the pin's drawn limits, so planting leg A's fit
leaves leg B's clean (US5-16). The base's own drawing draws its tapped-hole callout alone (rule 5).
The interference rows are zero-volume contacts: the pin line to line in the legs and in each
bushing.

**Places** (rule 2): the documents `assy`, `base_doc`, `clevis_doc`, `pin_doc`, `bush_doc` (both
bushings'), `screw_doc` (the M5 x 20 screws'), `assy_drw` and `base_drw`; the components `base`,
`clevis`, `pin`, `bush_a` and `bush_b`; the Hole Wizard rows `taps` (the base's tapped holes)
under `clrs` (the foot's clearance holes), four instances each, and the three empty dowel-hole
pairs, each hole a one-instance row, `dowel_a` to `dowel_c` (the base's Ø5.0) under `cdowel_a` to
`cdowel_c` (the foot's Ø5.1), each pair the others' decoy pair (rule 6); the fasteners `screw_a` to
`screw_d`, one into each instance of `taps`, `screw_b` the sibling joint of `screw_a` (rule 6); the
contacts `pin_clevis`, `pin_bush_a` and `pin_bush_b`; on the assembly's sheet each leg's bore,
`leg_bore_a` and `leg_bore_b`, over the pin's diameter `pin_dia`, so each fit is the other's
sibling fit (rule 6), and `position`, the position tolerance governing the dowel holes; and
`callout`, the base drawing's tapped-hole callout.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `okta-1` (US5-16): `fit_interference_unintended` on the pin in leg A, its sibling fit in leg B
  clean, and `coaxiality_drawn` on the first dowel-hole pair, the foot's `cdowel_a` off the base's
  `dowel_a` by the whole drawn zone. Its decoys are the kinds' over the design's places: the other
  fit and the bore against itself; each other pair, with and without the tolerance, the third pair
  through the coaxiality kind's own decoys there.
- `okta-2`: `engagement_unplaced` on `screw_a`, and `callout_count_differs` on the base's own
  drawing.
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

ASSY_STEM, BASE_STEM, CLEVIS_STEM = "EX-1103-00", "EX-1103-01", "EX-1103-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the pin, the bushings and the screws bought (`generator.md`
5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

BASE_THICKNESS_MM = 20.0
FOOT_THICKNESS_MM = 12.0
"""The base lies from z = -20 to 0, the clevis's foot from 0 to 12: the foot is the stack each
screw clamps."""

RELIEF_MM = 2.0
"""How far the base is relieved around its dowel holes: their faces stop this far under the
foot's, more than the joint rules' 1 mm adjacency (`checks/joint_rules.yaml`
`adjacency_gap_mm`), so the joint map pairs no dowel hole (`joint_absent`, `generator.md` 3)."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary)
    "base_doc": (BASE_STEM, 120.0 * 80.0 * BASE_THICKNESS_MM, "okta base"),
    # an 80 x 60 mm foot and on it two 10 x 60 x 50 mm legs
    "clevis_doc": (
        CLEVIS_STEM,
        80.0 * 60.0 * FOOT_THICKNESS_MM + 2 * 10.0 * 60.0 * 50.0,
        "okta clevis",
    ),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

PIN_CENTRE_MM = (60.0, 40.0, 45.0)
X = (1.0, 0.0, 0.0)
Z = (0.0, 0.0, 1.0)
"""The pin's centre and axis, along x through both legs; every hole's axis is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float, float]] = {
    # document place: (stem, description, outside and inside diameter, length) in mm
    "pin_doc": ("FICT-PIN-10X60-0001", "PIN, CLEVIS Ø10 X 60 MM, FICTIONAL", 10.0, 0.0, 60.0),
    "bush_doc": (
        "FICT-BUSHING-10X14X6-0001",
        "BUSHING, Ø10 X Ø14 X 6 MM, FICTIONAL",
        14.0,
        10.0,
        6.0,
    ),
}
"""The bought round parts, steel; each a mesh with no extracted face, so the joint map, which
reads faces in hole instances, takes none for a pin."""

ON_PIN: dict[str, float] = {"pin": 0.0, "bush_a": -7.0, "bush_b": 7.0}
"""Each round component's centre along the pin's axis from `PIN_CENTRE_MM`: the pin from x = 30
to 90 through the legs at x = 40 to 50 and 70 to 80, each bushing against a leg's inner face."""

ASSY_NOTES: tuple[tuple[str, NoteKind], ...] = (("THE PIN IS A SLIP FIT IN BOTH LEGS.", "other"),)
"""The assembly sheet's note: the pin's intent, which `fit_interference_unintended`'s plant
departs from (`generator.md` 3), in a sentence, since a summary is a name (`generator.md` 8)."""

DRAWINGS: dict[str, tuple[str, str, tuple[tuple[str, NoteKind], ...]]] = {
    "assy_drw": (ASSY_STEM, "okta assy drawing", ASSY_NOTES),
    "base_drw": (BASE_STEM, "okta base drawing", ()),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary, the sheet's notes)."""

TAP_AXES = ((30.0, 20.0), (90.0, 20.0), (30.0, 60.0), (90.0, 60.0))
DOWEL_AXES = ((30.0, 40.0), (90.0, 40.0), (60.0, 20.0))
"""The (x, y) of the screw holes' and the dowel-hole pairs' axes, all along z, inside the foot's
x = 20 to 100 and y = 10 to 70 and clear of its legs, x = 40 to 50 and 70 to 80."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 20.0
"""The base's screws, all one document (`screw_doc`): M5 x 20 reaches 8 mm past the foot, inside
the 9 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives, so a twin's
screws are the base's."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""

FREE_BORE: Limits = ("bilateral", 0.076, 0.040)
"""Leg B's bore, a free running fit: its lowest size clears the pin's highest under the clean
limits (`seeds.CLEARANCE`) and under the interfering ones `fit_interference_unintended` draws
(`seeds.INTERFERENCE`), so leg B's fit stays clean in every form."""


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
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, FOOT_THICKNESS_MM, TAP_AXES),
    "dowel_a": HoleShape(
        "clearance", "Ø5.0", 5.0, -BASE_THICKNESS_MM, -RELIEF_MM, (DOWEL_AXES[0],)
    ),
    "dowel_b": HoleShape(
        "clearance", "Ø5.0", 5.0, -BASE_THICKNESS_MM, -RELIEF_MM, (DOWEL_AXES[1],)
    ),
    "dowel_c": HoleShape(
        "clearance", "Ø5.0", 5.0, -BASE_THICKNESS_MM, -RELIEF_MM, (DOWEL_AXES[2],)
    ),
    "cdowel_a": HoleShape("clearance", "Ø5.1", 5.1, 0.0, FOOT_THICKNESS_MM, (DOWEL_AXES[0],)),
    "cdowel_b": HoleShape("clearance", "Ø5.1", 5.1, 0.0, FOOT_THICKNESS_MM, (DOWEL_AXES[1],)),
    "cdowel_c": HoleShape("clearance", "Ø5.1", 5.1, 0.0, FOOT_THICKNESS_MM, (DOWEL_AXES[2],)),
}
"""The screw holes, each foot hole over a base hole, coaxial and adjacent at the joint face
z = 0, as a joint is; and the dowel holes, each a feature of its own, one instance, so
`coaxiality_drawn`'s form moves one hole alone (`seeds._offset`). Every clevis face lies inside
the foot, so the foot's face boxes measure the clamped 12 mm."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "base_doc": DocumentPlace(tree=Tree()),
    "clevis_doc": DocumentPlace(tree=Tree()),
    "pin_doc": DocumentPlace(),
    "bush_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "base_drw": DocumentPlace(),
    "base": ComponentPlace(document="base_doc"),
    "clevis": ComponentPlace(document="clevis_doc"),
    "pin": ComponentPlace(document="pin_doc"),
    "bush_a": ComponentPlace(document="bush_doc"),
    "bush_b": ComponentPlace(document="bush_doc"),
    "taps": HolePlace(
        component="base",
        thread="M5x0.8",
        thread_depth_mm=9.0,
        hole_depth_mm=12.0,
        count=len(TAP_AXES),
    ),
    "clrs": HolePlace(component="clevis", count=len(TAP_AXES)),
    "dowel_a": HolePlace(component="base"),
    "dowel_b": HolePlace(component="base"),
    "dowel_c": HolePlace(component="base"),
    "cdowel_a": HolePlace(component="clevis"),
    "cdowel_b": HolePlace(component="clevis"),
    "cdowel_c": HolePlace(component="clevis"),
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("clevis",),
            clamp_mm=FOOT_THICKNESS_MM,
        )
        for screw in SCREWS
    },
    "pin_clevis": ContactPlace(a="pin", b="clevis"),
    "pin_bush_a": ContactPlace(a="pin", b="bush_a"),
    "pin_bush_b": ContactPlace(a="pin", b="bush_b"),
    # Leg A's fit drawn for clearance (`seeds.CLEARANCE`, the clean fit), leg B's free, so
    # nothing a correct reviewer checks on the base is anything but clear.
    "leg_bore_a": DimensionPlace(
        drawing="assy_drw", nominal_mm=10.0, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "leg_bore_b": DimensionPlace(drawing="assy_drw", nominal_mm=10.0, limits=FREE_BORE, prefix="Ø"),
    "pin_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=10.0, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The dowel holes' position tolerance, a Ø0.1 zone: `coaxiality_drawn` reads its nominal.
    "position": DimensionPlace(drawing="assy_drw", nominal_mm=0.1, limits=None, text="⌖ Ø0.1"),
    # The complete callout `seeds.FULL_CALLOUT` writes for `taps`: count, thread, thread depth.
    "callout": DimensionPlace(
        drawing="base_drw", nominal_mm=9.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 9"
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


def _on_pin(component: str) -> tuple[float, float, float]:
    """The centre of round component `component`, on the pin's axis."""
    x, y, z = PIN_CENTRE_MM
    return (x + ON_PIN[component], y, z)


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the base fixed); the hole rows with
    each record's thread, depths and offset; the round parts' meshes on the pin's axis; the
    screws with their fastener rows, seated unless a record says not, the M5 x 20 document laid
    first as `screw_doc` and another thread or length given a document of its own; the contacts'
    interference rows. Then the bought documents moved into the bought folder and the custom
    parts' trees laid; then the two ingested drawings, the assembly's with its note, and every
    drawn dimension, in place order. Every document is laid opened: no okta case leaves one
    unread, and a record that asks it is refused."""
    if variant is not None:
        raise ValueError(f"design okta has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design okta lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "okta assy")
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
    for name in ("base", "clevis", *ON_PIN):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=transform(_on_pin(name), X) if name in ON_PIN else None,
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
    for name in ON_PIN:
        record = places[name]
        assert isinstance(record, ComponentPlace)
        _, _, outside_mm, _, length_mm = ROUND_PARTS[record.document]
        builder.mesh(
            str(ids[name]),
            cylinder_mesh(_on_pin(name), X, outside_mm, -length_mm / 2.0, length_mm / 2.0),
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


DESIGN = Design(name="okta", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

PIN_FIT = {
    "bore": "leg_bore_a",
    "shaft": "pin_dia",
    "sibling_bore": "leg_bore_b",
    "sibling_shaft": "pin_dia",
}
"""The pin in leg A, which must slip; its sibling the pin in leg B: one drawn pin over two drawn
bores (US5-16)."""

DOWEL_PAIR = {
    "a": "dowel_a",
    "b": "cdowel_a",
    "other_a": "dowel_b",
    "other_b": "cdowel_b",
    "tolerance": "position",
}
"""The first dowel-hole pair, the foot's hole moved off the base's by the drawn zone; its decoy
the second pair between the same parts, with and without the tolerance."""

THIRD_PAIR_DECOYS = tuple(
    seeds.COAXIALITY_DRAWN.decoys(
        {**DOWEL_PAIR, "other_a": "dowel_c", "other_b": "cdowel_c"}, PLACES
    )
)
"""The third pair's decoys, with and without the tolerance: the coaxiality kind's own decoys at
that pair, so each other pair is a decoy (US5-16) while the kind names one."""

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
"""A joint planted on `screw_a`, its decoy the sibling joint on `screw_b`."""

CALLOUT = {"callout": "callout", "hole": "taps"}
"""The base drawing's callout of the tapped holes the screws go into."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="okta-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.FIT_INTERFERENCE_UNINTENDED, PIN_FIT, CURRENT),
            Seed(seeds.COAXIALITY_DRAWN, DOWEL_PAIR, CURRENT),
        ),
        decoys=THIRD_PAIR_DECOYS,
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="okta-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.ENGAGEMENT_UNPLACED, JOINT, CURRENT),
            Seed(seeds.CALLOUT_COUNT_DIFFERS, CALLOUT, CURRENT),
        ),
        twin=True,
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin."""
