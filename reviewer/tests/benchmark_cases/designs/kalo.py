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
tapped-hole callout alone (rule 5). The interference rows are R-4's, as `build_small_assembly`
writes them: each pin's zero-volume contact with the plate and one possible row, all contacts.

**Places** (rule 2): the documents `assy`, `plate_doc`, `cover_doc`, `pin_doc`, `assy_drw` and
`plate_drw`; the components `plate`, `cover`, `pin_a` and `pin_b`; the Hole Wizard rows `taps`
(the plate's two tapped holes) and `clrs` (the cover's clearance holes over them), two instances
each, and each pin's own one-instance dowel holes, `dowel_a` and `dowel_b` (the plate's Ø3.0)
under `cdowel_a` and `cdowel_b` (the cover's Ø3.1); R-6's `mounts` and `tap6`, laid under
`SCREWS_ELSEWHERE` only; the fasteners `screw_a` and `screw_b`, one into each instance of `taps`,
each the other's sibling joint (rule 6); the contacts `pin_a_plate` and `pin_b_plate`, and
`pin_b_cover`, the possible row; on the assembly's sheet the pin's diameter `pin_dia` over its two
bores, `plate_bore` and `cover_bore`, so each fit is the other's sibling fit (rule 6), the pin and
the plate's bore written "Ø3.0" as R-3's sheet writes them (owner decision 56A); and `callout`,
the plate drawing's tapped-hole callout.

**The variants**: `OVERSIZE_TEXT` (R-3's variant B), the pin's oversize written only as free
text, a configuration property of the pin's document that no check reads (research §3 R-3);
`UNDRAWN` (R-4's and R-5's package), no drawing ingested; `SCREWS_ELSEWHERE` (R-6's package), no
screw laid, the plate carrying M8 counterbored through holes and an M6x1.0 tapped hole, empty.

**The core cases** (`cases.md` 6.2; rule 7): each two held-out model-produced seeds of two
judgement families, with its twin.

- `kalo-1`: `thread_mismatch_unplaced` on `screw_a`, and `fit_limit_missing` on the pin in the
  plate, the plate's bore drawn with no tolerance on the assembly's sheet.
- `kalo-2`: `bottoming_unplaced` on `screw_a`, and `callout_drill_only` on the plate's own drawing.

**The R-3 anchor cases** (`cases.md` 6.3; FR-029; 15A): each tuned-on, representing R-3, with no
twin. The pins sit line to line in the plate's Ø3.0 clearance holes with no tolerance source, so
the joint map's floating-fastener pass stands, left ungraded (SR-21).

- `kalo-fit-1`, variant A: `press_fit_drawn` on the pin in the plate, "2X Ø3.0 +0.010/0" over
  "Ø3.0 +0.020/+0.014", one reference element covering both pins; at most one question on
  `interfaces.fit`, answered "press fit".
- `kalo-fit-2`, variant B (`OVERSIZE_TEXT`): `press_fit_undrawn`, both drawn Ø3.0 with no
  tolerance; the same question rule and answer.
- `kalo-fit-clean`: the pin in the cover's Ø3.1 hole with slip-fit limits, `slip_fit` a correct
  condition on the two dimensions.

**The R-4 to R-6 anchor cases** (`cases.md` 6.3; FR-029; 15A; CS-7, CS-11, RF-80): no twin; the
anchors' items tuned-on, their analyst-found forms held out.

- `kalo-contact` (R-4, and R-5's twin), `UNDRAWN`: the base's contacts; forbidden
  `interference.static` on the pins and the plate.
- `kalo-contact-positive` (R-4, AF-2), `UNDRAWN`: the cover's `cdowel_b` 0.750 mm off the axis of
  `pin_b`, line to line in the plate's `dowel_b`, the possible row an overlap of 1.237 mm3
  (`generate_fixtures.py:444-445, 679`): `interference_positive` on the pin and the cover (R-4)
  and `alignment_offset_placed` on that joint (AF-2), both code-produced and demonstrated.
- `kalo-lightweight` (R-5), `UNDRAWN`: `component_lightweight` on `pin_a`, the pin document not
  opened, both pins lightweight with no face, mesh or interference row; expected coverage
  `interference` unresolved or skipped and `interfaces.fit` unresolved.
- `kalo-empty` (R-6), `SCREWS_ELSEWHERE`: forbidden `fastener.*` and `hole.*` on the plate; at most
  one question on `fasteners`, answered "screws go in a seperate assy"; expected coverage
  `fasteners` unresolved or out of scope.
- `kalo-empty-positive` (R-6, AF-1): `thread_mismatch_placed` on `screw_a`, an M4-0.7 screw
  seated on the axis of the M5x0.8 `taps`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from swreview.ir.models import SourceRef
from tests.benchmark_cases import seeds, stamps
from tests.benchmark_cases.spec import (
    Answer,
    CaseSpec,
    ComponentPlace,
    Condition,
    ContactPlace,
    Coverage,
    Design,
    DimensionPlace,
    DocumentPlace,
    Forbidden,
    HeldOut,
    HolePlace,
    Laid,
    Place,
    Places,
    QuestionCount,
    ScrewPlace,
    Seed,
    Tree,
    TunedOn,
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

MOUNT_AXES = ((50.0, 15.0), (50.0, 45.0))
TAP6_AXIS = (50.0, 30.0)
"""Under `SCREWS_ELSEWHERE`, the (x, y) of the plate's M8 counterbored through holes and of its
M6x1.0 tapped hole, clear of every other hole."""

PINS: dict[str, tuple[float, float]] = {"pin_a": DOWEL_AXES[0], "pin_b": DOWEL_AXES[1]}
"""Each pin's axis: `pin_a` in `dowel_a` and `cdowel_a`, `pin_b` in `dowel_b` and `cdowel_b`."""

SCREWS: dict[str, int] = {"screw_a": 0, "screw_b": 1}
"""Each screw's instance of the hole its record names."""

UNSEATED_MM = 1.0
"""How far an unseated screw stands off its hole's axis, along x and y: more than the joint
rules' 0.2 mm from every extracted axis, so the joint map leaves it unplaced (`joint_placement`,
`generator.md` 3)."""

OVERSIZE_TEXT = "oversize_text"
"""R-3's variant B (`kalo-fit-2`): the pin's oversize only as free text, in a configuration
property of the pin's document that no check reads (research §3 R-3)."""

UNDRAWN = "undrawn"
"""R-4's and R-5's package (`kalo-contact`, `kalo-contact-positive`, `kalo-lightweight`): no
drawing ingested, as the anchors' small assembly had none, so no drawn limit can check the pins'
fit (research §3 R-5)."""

SCREWS_ELSEWHERE = "screws_elsewhere"
"""R-6's package (`kalo-empty`): its screws belong to another assembly, so none is laid, and the
plate carries `mounts` and `tap6`, empty, beside its empty `taps` (research §3 R-6)."""

VARIANTS = (OVERSIZE_TEXT, UNDRAWN, SCREWS_ELSEWHERE)
"""The design's variants (`Design.variants`)."""

TOLERANCE_PROPERTY = "Tolerance"
PIN_TOLERANCE_TEXT = "Ø3.0 +0.020/+0.014"
"""That property and its text: the pin's diameter as its vendor states it, the limits variant A
draws."""

Z = (0.0, 0.0, 1.0)


@dataclass(frozen=True)
class HoleShape:
    """How the design lays a hole place's row: its Hole Wizard type and size (`None` for a
    tapped hole, whose size is its record's thread), each instance's face diameter and extent
    along z (`lo_mm` `None` for a blind hole, whose face runs down to its record's drill depth),
    and its instances' axes, as many as its record's `count`; a counterbored hole's counterbore
    as its diameter and its depth down from `hi_mm`."""

    hole_type: Literal["tapped", "clearance", "counterbore"]
    size: str | None
    diameter_mm: float
    lo_mm: float | None
    hi_mm: float
    axes: tuple[tuple[float, float], ...]
    counterbore_mm: tuple[float, float] | None = None

    def faces(self, lo_mm: float) -> tuple[Face, ...]:
        """One instance's faces, its bore from `lo_mm` up, under its counterbore if it has one."""
        if self.counterbore_mm is None:
            return (Face(self.diameter_mm, lo_mm, self.hi_mm),)
        diameter_mm, depth_mm = self.counterbore_mm
        seat_mm = self.hi_mm - depth_mm
        return (Face(self.diameter_mm, lo_mm, seat_mm), Face(diameter_mm, seat_mm, self.hi_mm))


HOLES: dict[str, HoleShape] = {
    "taps": HoleShape("tapped", None, 4.2, None, 0.0, SCREW_AXES),
    "clrs": HoleShape("clearance", "M5", 5.5, 0.0, COVER_THICKNESS_MM, SCREW_AXES),
    "dowel_a": HoleShape("clearance", "Ø3.0", 3.0, -PLATE_THICKNESS_MM, 0.0, (DOWEL_AXES[0],)),
    "dowel_b": HoleShape("clearance", "Ø3.0", 3.0, -PLATE_THICKNESS_MM, 0.0, (DOWEL_AXES[1],)),
    "cdowel_a": HoleShape("clearance", "Ø3.1", 3.1, 0.0, COVER_THICKNESS_MM, (DOWEL_AXES[0],)),
    "cdowel_b": HoleShape("clearance", "Ø3.1", 3.1, 0.0, COVER_THICKNESS_MM, (DOWEL_AXES[1],)),
}
"""The screw holes and each pin's dowel holes, each pair coaxial and adjacent at the joint face
z = 0, as a joint is. Each pin's holes are features of their own, one instance each, so the
joint map names a pin's joint by `#1` of each (`seeds.ALIGNMENT_OFFSET_PLACED`)."""

EMPTY_HOLES: dict[str, HoleShape] = {
    # ISO 4762 M8: a 9.0 mm medium-fit through hole under a 14.0 mm counterbore 8.6 deep.
    "mounts": HoleShape(
        "counterbore", "M8", 9.0, -PLATE_THICKNESS_MM, 0.0, MOUNT_AXES, counterbore_mm=(14.0, 8.6)
    ),
    "tap6": HoleShape("tapped", None, 5.0, None, 0.0, (TAP6_AXIS,)),
}
"""R-6's holes, laid under `SCREWS_ELSEWHERE` only: the plate's alone, no cover hole over them,
so the joint map pairs none."""

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
    "dowel_a": HolePlace(component="plate"),
    "dowel_b": HolePlace(component="plate"),
    "cdowel_a": HolePlace(component="cover"),
    "cdowel_b": HolePlace(component="cover"),
    "mounts": HolePlace(component="plate", count=len(MOUNT_AXES)),
    "tap6": HolePlace(component="plate", thread="M6x1.0", thread_depth_mm=10.0, hole_depth_mm=12.0),
    # R-4's rows, as `build_small_assembly` writes them: each pin's size-for-size contact with
    # the plate it sits in line to line, and one possible row, the second pin in the cover's
    # Ø3.1 hole, which is the overlap `generate_fixtures.py:679` measures (1.237 mm3) once that
    # hole stands 0.750 mm off the pin's axis (`seeds.INTERFERENCE_POSITIVE`).
    "pin_a_plate": ContactPlace(a="pin_a", b="plate"),
    "pin_b_plate": ContactPlace(a="pin_b", b="plate"),
    "pin_b_cover": ContactPlace(
        a="pin_b", b="cover", volume_mm3=None, possible=True, overlap_mm3=1.237
    ),
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
    # reviewer checks on the base is anything but clear. The 3 mm nominals are written "3.0", as
    # R-3's sheet writes them (`cases.md` 6.3; owner decision 56A).
    "plate_bore": DimensionPlace(
        drawing="assy_drw",
        nominal_mm=3.0,
        limits=seeds.CLEARANCE[0],
        prefix="2X Ø",
        nominal_text="3.0",
    ),
    "cover_bore": DimensionPlace(
        drawing="assy_drw", nominal_mm=3.1, limits=seeds.CLEARANCE[0], prefix="2X Ø"
    ),
    "pin_dia": DimensionPlace(
        drawing="assy_drw",
        nominal_mm=PIN_DIAMETER_MM,
        limits=seeds.CLEARANCE[1],
        prefix="Ø",
        nominal_text="3.0",
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


def _opened(places: Places, component: str) -> bool:
    """Whether the document `component` is an instance of was opened: its instances are then
    resolved, their faces, meshes and interference rows laid (`DocumentPlace.opened`)."""
    record = places[component]
    assert isinstance(record, ComponentPlace)
    document = places[record.document]
    assert isinstance(document, DocumentPlace)
    return document.opened


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents, opened unless a record says not, and the components (the
    plate fixed), an unopened document's instances lightweight; the hole rows with each record's
    thread, depths and offset (R-6's too, under `SCREWS_ELSEWHERE`); the pins' faces and meshes;
    the screws with their fastener rows, seated unless a record says not (none under
    `SCREWS_ELSEWHERE`); the contacts' interference rows; nothing of an unopened document's
    instances. Then the bought documents moved into the bought folder, the pin's free-text
    tolerance written under `OVERSIZE_TEXT`, and the custom parts' trees laid; then, unless
    `UNDRAWN`, the two ingested drawings and every drawn dimension, in place order."""
    if variant not in (None, *VARIANTS):
        raise ValueError(f"design kalo has no variant {variant}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "kalo assy")
    )
    ids: dict[str, str | SourceRef] = {"assy": builder.root_id}
    for name, (stem, volume_mm3, summary) in PARTS.items():
        record = places[name]
        assert isinstance(record, DocumentPlace)
        ids[name] = builder.document(
            stem,
            "part",
            material="6061-T6",
            mass_kg=_mass_kg(volume_mm3, ALUMINIUM_DENSITY_KG_M3),
            volume_mm3=volume_mm3,
            properties=_custom(record, stem, summary),
            opened=record.opened,
        )
    pin_volume_mm3 = round(
        math.pi / 4.0 * PIN_DIAMETER_MM**2 * (PLATE_THICKNESS_MM + COVER_THICKNESS_MM), 6
    )
    pin_doc = places["pin_doc"]
    assert isinstance(pin_doc, DocumentPlace)
    ids["pin_doc"] = builder.document(
        PIN_STEM,
        "part",
        material="Alloy Steel",
        mass_kg=_mass_kg(pin_volume_mm3, STEEL_DENSITY_KG_M3),
        volume_mm3=pin_volume_mm3,
        properties={VENDOR: "FICT", "Description": "PIN, DOWEL Ø3 X 20 MM, FICTIONAL"},
        opened=pin_doc.opened,
    )
    for name in ("plate", "cover", *PINS):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        axis = PINS.get(name)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=None if axis is None else transform((*axis, -PLATE_THICKNESS_MM)),
            suppression="resolved" if _opened(places, name) else "lightweight",
        )

    holes = {**HOLES, **(EMPTY_HOLES if variant == SCREWS_ELSEWHERE else {})}
    for name, shape in holes.items():
        record = places[name]
        assert isinstance(record, HolePlace)
        if not _opened(places, record.component):
            continue
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
                Instance((x + record.offset_mm, y, 0.0), Z, shape.faces(lo_mm))
                for x, y in shape.axes
            ],
        )
    for name, (x, y) in PINS.items():
        if not _opened(places, name):
            continue
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
    for name, index in SCREWS.items() if variant != SCREWS_ELSEWHERE else ():
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
        if not (_opened(places, record.a) and _opened(places, record.b)):
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
    bought = {str(ids["pin_doc"]), *screw_documents.values()}
    documents = [
        document.model_copy(
            update={"path": f"{FICTIONAL_ROOT}Vault\\{BOUGHT_FOLDER}\\{document.file_name}"}
        )
        if document.document_id in bought
        else document
        for document in package.documents
    ]
    if variant == OVERSIZE_TEXT:
        documents = [
            document.model_copy(
                update={
                    "config_properties": {
                        document.active_configuration: {TOLERANCE_PROPERTY: PIN_TOLERANCE_TEXT}
                    }
                }
            )
            if document.document_id == ids["pin_doc"]
            else document
            for document in documents
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
    if variant == UNDRAWN:
        return Laid(package=package, meshes=built.meshes, ids=ids)

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


DESIGN = Design(name="kalo", places=PLACES, lay=lay, variants=VARIANTS)

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

R3 = TunedOn("R-3")
"""R-3's items are tuned-on: feature 013's prompt and checklist were written around them (15A)."""

PIN_IN_PLATE = {"bore": "plate_bore", "shaft": "pin_dia"}
"""R-3's joint, the pin line to line in the plate: the "2X" bore draws both pins' bores, so one
reference element covers both pins (research §3 R-3)."""

PIN_IN_COVER = {"bore": "cover_bore", "shaft": "pin_dia"}
"""The 3.0 mm pin in the cover's 3.1 mm hole: R-3's clean case."""

FIT_QUESTIONS = QuestionCount(
    tag=R3,
    description=(
        "At most one question on the pin's fit: once the engineer has answered it, a request "
        "for numeric limits asks it again (R-3)."
    ),
    item="interfaces.fit",
    max=1,
    represents="R-3",
)

PRESS_FIT_ANSWER = Answer(
    answer="press fit", item="interfaces.fit", ids=("pin_a", "pin_b", "plate")
)
"""The engineer's answer to the fit question on the pins and the plate."""

R4, R5, R6 = TunedOn("R-4"), TunedOn("R-5"), TunedOn("R-6")
"""The R-4 to R-6 anchors' items are tuned-on (15A); their analyst-found forms are held out."""

OFFSET_CONTACT = {"a": "pin_b", "b": "cover"}
"""R-4's positive pair: the second pin and the cover whose Ø3.1 hole stands 0.750 mm off its
axis, the overlap the possible row between them becomes."""

OFFSET_JOINT = {"pin": "pin_b", "seat": "dowel_b", "hole": "cdowel_b"}
"""AF-2's placed joint: the second pin line to line in the plate's hole, the cover's Ø3.1 hole
moved off its axis; each a one-instance feature, so the key names `#1` of each."""

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
    CaseSpec(
        case_id="kalo-fit-1",
        design=DESIGN,
        seeds=(Seed(seeds.PRESS_FIT_DRAWN, PIN_IN_PLATE, R3, represents="R-3"),),
        question_counts=(FIT_QUESTIONS,),
        answers=(PRESS_FIT_ANSWER,),
        represents=("R-3",),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-fit-2",
        design=DESIGN,
        variant=OVERSIZE_TEXT,
        seeds=(Seed(seeds.PRESS_FIT_UNDRAWN, PIN_IN_PLATE, R3, represents="R-3"),),
        question_counts=(FIT_QUESTIONS,),
        answers=(PRESS_FIT_ANSWER,),
        represents=("R-3",),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-fit-clean",
        design=DESIGN,
        conditions=(
            Condition(
                tag=R3,
                description=(
                    "The pin in the cover's 3.1 mm hole, drawn with slip-fit limits: a clearance "
                    "fit, where the joint's alignment pass is right (R-3's clean case)."
                ),
                kind=seeds.SLIP_FIT,
                at=PIN_IN_COVER,
                represents="R-3",
            ),
        ),
        represents=("R-3",),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-contact",
        design=DESIGN,
        variant=UNDRAWN,
        forbidden=(
            Forbidden(
                checks=("interference.static",),
                tag=R4,
                description=(
                    "The pins sit line to line in the plate: their zero-volume rows and the "
                    "possible row are contacts, never interference findings (R-4)."
                ),
                component_ids=("pin_a", "pin_b", "plate"),
                represents="R-4",
            ),
        ),
        represents=("R-4", "R-5"),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-contact-positive",
        design=DESIGN,
        variant=UNDRAWN,
        seeds=(
            Seed(seeds.INTERFERENCE_POSITIVE, OFFSET_CONTACT, R4, represents="R-4"),
            Seed(seeds.ALIGNMENT_OFFSET_PLACED, OFFSET_JOINT, CURRENT, represents="AF-2"),
        ),
        represents=("R-4", "AF-2"),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-lightweight",
        design=DESIGN,
        variant=UNDRAWN,
        seeds=(Seed(seeds.COMPONENT_LIGHTWEIGHT, {"component": "pin_a"}, R5, represents="R-5"),),
        expected_coverage=(
            Coverage(
                item="interference",
                statuses=("unresolved", "skipped"),
                tag=R5,
                description=(
                    "The pins are lightweight and the package reports no interference: "
                    "interference was not checked, never checked and clean (R-5)."
                ),
                represents="R-5",
            ),
            Coverage(
                item="interfaces.fit",
                statuses=("unresolved",),
                tag=R5,
                description=(
                    "The pins' bodies were not read and no drawing gives the fit's limits: the "
                    "fit stays unresolved (R-5)."
                ),
                represents="R-5",
            ),
        ),
        represents=("R-5",),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-empty",
        design=DESIGN,
        variant=SCREWS_ELSEWHERE,
        forbidden=(
            Forbidden(
                checks=("fastener.*", "hole.*"),
                tag=R6,
                description=(
                    "The plate's holes are empty by design, its screws in another assembly: no "
                    "fastener or hole finding on the plate (R-6)."
                ),
                component_ids=("plate",),
                represents="R-6",
            ),
        ),
        expected_coverage=(
            Coverage(
                item="fasteners",
                statuses=("unresolved", "out_of_scope"),
                tag=R6,
                description=(
                    "The package holds no screw, so no fastener joint can be checked (R-6)."
                ),
                represents="R-6",
            ),
        ),
        question_counts=(
            QuestionCount(
                tag=R6,
                description=(
                    "At most one question on which fasteners go in the plate's holes: once the "
                    "engineer has answered it, asking again is a re-ask (R-6)."
                ),
                item="fasteners",
                max=1,
                represents="R-6",
            ),
        ),
        answers=(Answer(answer="screws go in a seperate assy", item="fasteners", ids=("plate",)),),
        represents=("R-6",),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="kalo-empty-positive",
        design=DESIGN,
        seeds=(
            Seed(seeds.THREAD_MISMATCH_PLACED, {"fastener": "screw_a"}, CURRENT, represents="AF-1"),
        ),
        represents=("R-6", "AF-1"),
        sets=("committed",),
    ),
)
"""The core cases (`cases.md` 6.2), each with its twin, then the anchor cases (`cases.md` 6.3):
R-3's, then R-4's, R-5's and R-6's with their analyst-found forms."""
