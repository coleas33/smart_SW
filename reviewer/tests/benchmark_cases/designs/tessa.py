"""The tessa design (`cases.md` 6.2 and 6.3): a bracket on a base, screwed into the bracket's
M5x0.8 tapped holes and doweled to it (the big assembly's bracket region, in fictional values).

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The assembly is modelled base up: the custom base, fixed, lies on z = 0 to 12 and the custom
bracket's foot is screwed to its underside, z = -16 to 0, by four bought M5 socket head screws
that drop through the base's M5 clearance holes into the foot's four blind M5x0.8 tapped holes;
the bracket's upright, below the foot, carries a bought bushing in which a bought shaft slides.
The base is each screw's one clamped layer, a flat plate whose face boxes measure its 12 mm along
the screw (`tools/checks_fastener.py` `_bbox_extent_mm`), the reading that is right for a flat
layer the screw passes through squarely. Two dowel-hole pairs, AF-2's Ø3.0 in the base over Ø3.1
in the foot (`generate_fixtures.py:444-445`), stand empty; the foot is relieved 2 mm around its
dowel holes, so their faces stand 2 mm under the base's, beyond the joint rules' 1 mm adjacency,
and the joint map pairs neither (`joint_absent`; rule 6). Every name is the example profile's:
the assembly, the base and the bracket `EX-1102-..` with the data card, the revision, the hygiene
number equal to the stem and a summary unique in the package; the bushing, the shaft and the
screws bought, in the profile's bought folder with a vendor property, each screw with its
fastener row (GN-2). Each custom part carries `spec.tree_specs`' compliant tree. No tolerance
source anywhere (rule 4): the shaft's fit in the bushing and the bushing's in the bracket are
drawn on the assembly's ingested sheet only, beside a note that the shaft slides in the bushing,
which `fit_transition`'s plant has the package say; a summary cannot say it, a summary being a
name and the case vocabulary holding no word for sliding (`generator.md` 3 and 8). The bracket's
own drawing draws its tapped-hole callout alone (rule 5). The interference rows are zero-volume
contacts: `screw_a`'s head on the base, the shaft in the bushing, and the other three screws'
threads in the foot.

**Places** (rule 2): the documents `assy`, `base_doc`, `bracket_doc`, `bushing_doc`, `shaft_doc`,
`screw_doc` (the M5 x 20 screws'), `assy_drw` and `bracket_drw`; the components `base`,
`bracket`, `bushing` and `shaft`, and each screw's instance, `screw_a_part` to `screw_d_part`,
which the interference rows name; the Hole Wizard rows `clrs` (the base's clearance holes) over
`taps` (the foot's tapped holes), four instances each, and the empty dowel-hole pairs, each hole a
one-instance row, `dowel_a` and `dowel_b` (the base's Ø3.0) over `bdowel_a` and `bdowel_b` (the
foot's Ø3.1), each pair the other's decoy pair (rule 6); the fasteners `screw_a` to `screw_d`, one
into each instance of `taps`, `screw_b` the sibling joint of `screw_a` (rule 6); the contacts
`screw_a_base`, `shaft_bushing`, and `screw_b_bracket` to `screw_d_bracket`; on the assembly's
sheet the bushing's bore `bush_bore` over the shaft's diameter `shaft_dia`, and its sibling fit
(rule 6), the bracket's bore `bracket_bore` over the bushing's outside `bush_od`; and `callout`,
the bracket drawing's tapped-hole callout.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin; AF-1's and AF-2's model-produced forms (`cases.md` 6.3).

- `tessa-1` (AF-1): `thread_mismatch_unplaced` on `screw_a`, an M4-0.7 screw in the M5x0.8
  `taps`, and `fit_transition` on the shaft in the bushing.
- `tessa-2` (AF-2): `coaxiality_undrawn` on the first dowel-hole pair, the foot's `bdowel_a`
  0.750 mm off the base's `dowel_a`, and `callout_thread_differs` on the bracket's own drawing.

**The AF-3 anchor case** (`cases.md` 6.3; FR-029; 15A; RF-80): no twin.

- `tessa-groups` (AF-3, R-4): `interference_positive` on `screw_a`'s instance and the base and on
  the shaft and the bushing, about 250 mm3 each, two groups sharing no part (held out, AF-3);
  forbidden `interference.static` on the contacts' parts, the other three screws and the bracket
  (tuned-on, R-4), disjoint from both pairs, since a forbidden entry may not overlap a known defect
  (`answer-key.md` 5).
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
    Forbidden,
    HeldOut,
    HolePlace,
    Laid,
    Place,
    Places,
    ScrewPlace,
    Seed,
    Tree,
    TunedOn,
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

ASSY_STEM, BASE_STEM, BRACKET_STEM = "EX-1102-00", "EX-1102-01", "EX-1102-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where a bought document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the bushing, the shaft and the screws bought (`generator.md`
5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

BASE_THICKNESS_MM = 12.0
FOOT_THICKNESS_MM = 16.0
"""The base lies from z = 0 to 12, the bracket's foot from -16 to 0: the base is the stack each
screw clamps."""

RELIEF_MM = 2.0
"""How far the foot is relieved around its dowel holes: their faces stop this far under the
base's, more than the joint rules' 1 mm adjacency (`checks/joint_rules.yaml`
`adjacency_gap_mm`), so the joint map pairs no dowel hole (`joint_absent`, `generator.md` 3)."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary)
    "base_doc": (BASE_STEM, 120.0 * 80.0 * BASE_THICKNESS_MM, "tessa base"),
    # a 60 x 40 mm foot and, below it, a 60 x 12 x 50 mm upright
    "bracket_doc": (
        BRACKET_STEM,
        60.0 * 40.0 * FOOT_THICKNESS_MM + 60.0 * 12.0 * 50.0,
        "tessa bracket",
    ),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

SHAFT_AXIS_MM = (60.0, 40.0, -45.0)
Y = (0.0, 1.0, 0.0)
Z = (0.0, 0.0, 1.0)
"""The shaft's axis, along y through the bracket's upright; every hole's axis is along z."""

ROUND_PARTS: dict[str, tuple[str, str, float, float, float]] = {
    # component place: (stem, description, outside and inside diameter, length) in mm
    "bushing": (
        "FICT-BUSHING-8X12X20-0001",
        "BUSHING, Ø8 X Ø12 X 20 MM, FICTIONAL",
        12.0,
        8.0,
        20.0,
    ),
    "shaft": ("FICT-SHAFT-8X60-0001", "SHAFT, Ø8 X 60 MM, FICTIONAL", 8.0, 0.0, 60.0),
}
"""The bought round parts, steel, centred on the shaft's axis; each a mesh with no extracted
face, so the joint map, which reads faces in hole instances, takes neither for a pin."""

ASSY_NOTES: tuple[tuple[str, NoteKind], ...] = (("THE SHAFT SLIDES IN THE BUSHING.", "other"),)
"""The assembly sheet's note: the shaft's intent, which `fit_transition`'s plant has the package
state (`generator.md` 3), in a sentence, since a summary is a name (`generator.md` 8)."""

DRAWINGS: dict[str, tuple[str, str, tuple[tuple[str, NoteKind], ...]]] = {
    "assy_drw": (ASSY_STEM, "tessa assy drawing", ASSY_NOTES),
    "bracket_drw": (BRACKET_STEM, "tessa bracket drawing", ()),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary, the sheet's notes)."""

TAP_AXES = ((40.0, 28.0), (80.0, 28.0), (40.0, 52.0), (80.0, 52.0))
DOWEL_AXES = ((34.0, 40.0), (86.0, 40.0))
"""The (x, y) of the screw holes' and the dowel holes' axes, all along z, inside the foot's
60 x 40 mm."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1, "screw_c": 2, "screw_d": 3}
"""Each screw's instance of the hole its record names."""

SCREW_THREAD, SCREW_LENGTH_MM = "M5-0.8", 20.0
"""The base's screws, all one document (`screw_doc`): M5 x 20 reaches 8 mm past the base, inside
the 9 mm thread, above the rule's 7.5 mm, the length `seeds.CLEAN_JOINT` gives, so a twin's
screws are the base's."""

THREAD_CONTACTS = ("screw_b", "screw_c", "screw_d")
"""The screws whose threads touch the foot at nominal: zero-volume contacts (R-4)."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""


def _part(screw: str) -> str:
    """The component place of `screw`'s instance: the screw place names its fastener row, which
    the joints name, and an interference row names the instance (`spec.ScrewPlace`)."""
    return f"{screw}_part"


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
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, BASE_THICKNESS_MM, TAP_AXES),
    "taps": HoleShape("tapped", None, 4.2, None, 0.0, TAP_AXES),
    "dowel_a": HoleShape("clearance", "Ø3.0", 3.0, 0.0, BASE_THICKNESS_MM, (DOWEL_AXES[0],)),
    "dowel_b": HoleShape("clearance", "Ø3.0", 3.0, 0.0, BASE_THICKNESS_MM, (DOWEL_AXES[1],)),
    "bdowel_a": HoleShape(
        "clearance", "Ø3.1", 3.1, -FOOT_THICKNESS_MM, -RELIEF_MM, (DOWEL_AXES[0],)
    ),
    "bdowel_b": HoleShape(
        "clearance", "Ø3.1", 3.1, -FOOT_THICKNESS_MM, -RELIEF_MM, (DOWEL_AXES[1],)
    ),
}
"""The screw holes, each base hole over a foot hole, coaxial and adjacent at the joint face
z = 0, as a joint is; and the dowel holes, each a feature of its own, one instance, so
`coaxiality_undrawn`'s form moves one hole alone (`seeds._offset`)."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "base_doc": DocumentPlace(tree=Tree()),
    "bracket_doc": DocumentPlace(tree=Tree()),
    "bushing_doc": DocumentPlace(),
    "shaft_doc": DocumentPlace(),
    "screw_doc": DocumentPlace(),
    "assy_drw": DocumentPlace(),
    "bracket_drw": DocumentPlace(),
    "base": ComponentPlace(document="base_doc"),
    "bracket": ComponentPlace(document="bracket_doc"),
    "bushing": ComponentPlace(document="bushing_doc"),
    "shaft": ComponentPlace(document="shaft_doc"),
    **{_part(screw): ComponentPlace(document="screw_doc") for screw in SCREWS},
    "clrs": HolePlace(component="base", count=len(TAP_AXES)),
    "taps": HolePlace(
        component="bracket",
        thread="M5x0.8",
        thread_depth_mm=9.0,
        hole_depth_mm=12.0,
        count=len(TAP_AXES),
    ),
    "dowel_a": HolePlace(component="base"),
    "dowel_b": HolePlace(component="base"),
    "bdowel_a": HolePlace(component="bracket"),
    "bdowel_b": HolePlace(component="bracket"),
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("base",),
            clamp_mm=BASE_THICKNESS_MM,
        )
        for screw in SCREWS
    },
    # Zero-volume contacts, each stating the overlap `interference_positive` plants on it for
    # AF-3, about 250 mm3: `screw_a`'s socket head (Ø8.5) sunk 4.4 mm into the base where no
    # counterbore was cut, and the shaft modelled Ø8.95 in the bushing's Ø8 bore along its
    # 20 mm. The interference check reads a row's volume, never the meshes (`checks/
    # interference.py`).
    "screw_a_base": ContactPlace(a=_part("screw_a"), b="base", overlap_mm3=249.678),
    "shaft_bushing": ContactPlace(a="shaft", b="bushing", overlap_mm3=252.937),
    **{f"{screw}_bracket": ContactPlace(a=_part(screw), b="bracket") for screw in THREAD_CONTACTS},
    # Both fits drawn for clearance (`seeds.CLEARANCE`, the clean fit), so nothing a correct
    # reviewer checks on the base is anything but clear.
    "bush_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=8.0, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "shaft_dia": DimensionPlace(
        drawing="assy_drw", nominal_mm=8.0, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    "bracket_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=12.0, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "bush_od": DimensionPlace(
        drawing="assy_drw", nominal_mm=12.0, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    # The complete callout `seeds.FULL_CALLOUT` writes for `taps`: count, thread, thread depth.
    "callout": DimensionPlace(
        drawing="bracket_drw", nominal_mm=9.0, limits=None, text="4X M5x0.8 - 6H THREAD ↧ 9"
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
    (`generator.md` 5.1): the documents and the components (the base fixed); the hole rows with
    each record's thread, depths and offset; the round parts' meshes; the screws with their
    fastener rows, seated unless a record says not, the M5 x 20 document laid first as
    `screw_doc` and another thread or length given a document of its own; the contacts'
    interference rows. Then the bought documents moved into the bought folder and the custom
    parts' trees laid; then the two ingested drawings, the assembly's with its note, and every
    drawn dimension, in place order. Every document is laid opened: no tessa case leaves one
    unread, and a record that asks it is refused."""
    if variant is not None:
        raise ValueError(f"design tessa has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design tessa lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "tessa assy")
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
        record = places[name]
        assert isinstance(record, ComponentPlace)
        volume_mm3 = round(math.pi / 4.0 * (outside_mm**2 - inside_mm**2) * length_mm, 6)
        document = builder.document(
            stem,
            "part",
            material="Alloy Steel",
            mass_kg=_mass_kg(volume_mm3, STEEL_DENSITY_KG_M3),
            volume_mm3=volume_mm3,
            properties={VENDOR: "FICT", "Description": description},
        )
        ids[record.document] = document
        bought.add(document)
    for name in ("base", "bracket", *ROUND_PARTS):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=transform(SHAFT_AXIS_MM, Y) if name in ROUND_PARTS else None,
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
    for name, (_, _, outside_mm, _, length_mm) in ROUND_PARTS.items():
        builder.mesh(
            str(ids[name]),
            cylinder_mesh(SHAFT_AXIS_MM, Y, outside_mm, -length_mm / 2.0, length_mm / 2.0),
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
        ids[_part(name)] = screws[name]

    for name, record in places.items():
        if not isinstance(record, ContactPlace):
            continue
        # A possible row is one with no volume: the overlap `interference_positive` plants on
        # it is measured.
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


DESIGN = Design(name="tessa", places=PLACES, lay=lay)

# --- the cases -------------------------------------------------------------------------------

CURRENT = HeldOut(stamps.CURRENT)

JOINT = {"fastener": "screw_a", "sibling": "screw_b"}
"""A joint planted on `screw_a`, its decoy the sibling joint on `screw_b`: AF-1's M4-0.7 screw in
an M5x0.8 tapped hole, as `thread_mismatch_unplaced` plants it."""

SHAFT_FIT = {
    "bore": "bush_bore",
    "shaft": "shaft_dia",
    "sibling_bore": "bracket_bore",
    "sibling_shaft": "bush_od",
}
"""The shaft in the bushing, which must slide; its sibling the bushing in the bracket, drawn on
its own two dimensions, so the planted limits leave it clear."""

DOWEL_PAIR = {"a": "dowel_a", "b": "bdowel_a", "other_a": "dowel_b", "other_b": "bdowel_b"}
"""AF-2's empty dowel-hole pair, the foot's hole moved 0.750 mm off the base's; its decoy the
other pair between the same parts."""

CALLOUT = {"callout": "callout", "hole": "taps"}
"""The bracket drawing's callout of the tapped holes the screws go into."""

HEAD_IN_BASE = {"a": _part("screw_a"), "b": "base"}
SHAFT_IN_BUSHING = {"a": "shaft", "b": "bushing"}
"""AF-3's two positive groups, sharing no part."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="tessa-1",
        design=DESIGN,
        seeds=(
            Seed(seeds.THREAD_MISMATCH_UNPLACED, JOINT, CURRENT, represents="AF-1"),
            Seed(seeds.FIT_TRANSITION, SHAFT_FIT, CURRENT),
        ),
        represents=("AF-1",),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="tessa-2",
        design=DESIGN,
        seeds=(
            Seed(seeds.COAXIALITY_UNDRAWN, DOWEL_PAIR, CURRENT, represents="AF-2"),
            Seed(seeds.CALLOUT_THREAD_DIFFERS, CALLOUT, CURRENT),
        ),
        represents=("AF-2",),
        twin=True,
        sets=("committed",),
    ),
    CaseSpec(
        case_id="tessa-groups",
        design=DESIGN,
        seeds=(
            Seed(seeds.INTERFERENCE_POSITIVE, HEAD_IN_BASE, CURRENT, represents="AF-3"),
            Seed(seeds.INTERFERENCE_POSITIVE, SHAFT_IN_BUSHING, CURRENT, represents="AF-3"),
        ),
        forbidden=(
            Forbidden(
                checks=("interference.static",),
                tag=TunedOn("R-4"),
                description=(
                    "Three screws' threads touch the bracket's tapped holes at nominal: "
                    "zero-volume contacts, never interference findings (R-4)."
                ),
                component_ids=(*(_part(screw) for screw in THREAD_CONTACTS), "bracket"),
                represents="R-4",
            ),
        ),
        represents=("AF-3", "R-4"),
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin, then the anchor case (`cases.md` 6.3)."""
