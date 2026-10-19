"""The cover design (`cases.md` 6.4): `cover-blind-tap`, the PDF-ingest-shaped housing and
cover with four M6 screws in blind tapped holes.

**The package** (`cases.md` 6.4; `answer-key.md` 7.1; CS-19, RF-12, RF-75). The exported-files
package the case always was, rebuilt with the builders from the committed package's content at
`5cfb743` (`benchmarks/packages/cover-blind-tap/package.json`), in the example profile's names
(`generator.md` 5.2). The custom housing, fixed, and the custom cover, both 6061-T6 as their
recorded descriptions state, and four bought M6 x 20 socket head screws, each with its fastener
row (GN-2), in the profile's bought folder with a vendor property; each custom part carries
`spec.tree_specs`' compliant tree. Every component is BOM-shaped, as the ingest builds one from
the BOM: a placeholder `persist_ref`, base64 of "exported:<document_id>:<n>", and the identity
transform, with the one gap that says so, in the ingest's words (`PLACEHOLDER_REASON`). Nothing
is extracted geometry: no face and no mesh. The housing's four M6x1.0 tapped holes are one
Hole Wizard row with no face, so it states one axis, its first hole's, and the gap the builder
writes for a faceless row; it states its 14 mm drill depth and no usable thread depth, with the
gap that says so. The screws, at the identity transform, stand on the z axis through the origin,
more than the joint rules' 0.2 mm from the row's axis, so the joint map places none of them
(`joint_placement`, `generator.md` 3), while their fastener rows still address them.

**The drawings**, ingested sheets in mm (`SheetBuilder`; no tolerance source anywhere, rule 4):
the housing's own drawing, its sheet drawing the tapped holes' callout as a drill depth only,
"4X M6x1.0 - 6H DRILL ↧ 14", then the bore "Ø40 +0.025/0"; the cover's own drawing, its first
sheet drawing the spigot "Ø40 -0.009/-0.025", the thickness "8.0 ±0.1" and the counterbores
"4X ⌴ Ø11 ↧ 6.5", its second sheet unreadable (`no_text`, with its gap). The housing's sheet
carries both D-2's callout and C-1's bore, as the package always has: the drawing-document rule
does not apply to this pilot-only, all-tuned-on case (`generator.md` 10 row 5; RF-12).

**Places** (rule 2): the documents `assy`, `housing_doc`, `cover_doc`, `housing_drw` and
`cover_drw`; the components `housing` and `cover`; the Hole Wizard row `taps`, four instances;
the fasteners `screw_a` to `screw_d`, each into `taps`, clamping the cover; on the housing's
sheet the callout `callout` and the bore `bore`; on the cover's first sheet the spigot `spigot`,
the thickness `thickness` and the counterbores `counterbores`.

**The case** (`cases.md` 6.4; FR-010, US5-4; INT-15, RF-12, RF-75): `cover-blind-tap`, in
`pilot.json` only, every item tuned-on (prompt-encodes-cbt-answer, research §2), no twin, no
answers, no decoys. `D-1`, `bottoming_thread_depth_unknown` on `taps`: one joint element per
screw, model-produced, expected unresolved; `D-2`, `callout_drill_only` on the housing's drawing,
expected unresolved; `C-1`, the spigot fit, `slip_fit` at the housing's bore and the cover's
spigot, so its references name both drawings and its `document_ids` both drawing documents.
"""

from __future__ import annotations

from swreview.ir.models import Gap, SourceRef
from tests.benchmark_cases import seeds
from tests.benchmark_cases.spec import (
    CaseSpec,
    ComponentPlace,
    Condition,
    Design,
    DimensionPlace,
    DocumentPlace,
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
from tests.support.drawings import SheetBuilder
from tests.support.features import PartSpec, part_trees
from tests.support.mechanical import FICTIONAL_ROOT, Instance, PackageBuilder
from tests.support.packages import persist_ref
from tests.support.standards import card

# --- the shape -------------------------------------------------------------------------------

ASSY_STEM, HOUSING_STEM, COVER_STEM = "EX-1111-00", "EX-1111-01", "EX-1111-02"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2); each drawing takes its model's stem."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where the screws' document lies and the property that names its vendor: two strong bought
signals, so `part_roles` decides the screws bought (`generator.md` 5.2)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the custom parts' material."""

COVER_THICKNESS_MM = 8.0
"""The cover's thickness, which its drawing draws "8.0 ±0.1"."""

PARTS: dict[str, tuple[str, float, str]] = {
    # place: (stem, volume in mm3, summary), each part 100 x 100 mm in plan
    "housing_doc": (HOUSING_STEM, 100.0 * 100.0 * 30.0, "blind tap housing"),
    "cover_doc": (COVER_STEM, 100.0 * 100.0 * COVER_THICKNESS_MM, "blind tap cover"),
}
"""The custom parts, both 6061-T6, their masses from their volumes."""

DRAWINGS: dict[str, tuple[str, str]] = {
    "housing_drw": (HOUSING_STEM, "blind tap housing drawing"),
    "cover_drw": (COVER_STEM, "blind tap cover drawing"),
}
"""The ingested drawings, each a sheet `Sheet1` on page 1: (stem, summary). The cover's has a
second page, unreadable (`UNREADABLE_SHEET`)."""

UNREADABLE_SHEET = ("cover_drw", "Sheet2", 2)
"""The cover drawing's second sheet: (drawing place, sheet, page), exported flattened, so the
ingest read nothing on it (`parse_status` `no_text`, with its gap)."""

SCREWS = ("screw_a", "screw_b", "screw_c", "screw_d")
SCREW_THREAD, SCREW_LENGTH_MM = "M6-1.0", 20.0
"""The four M6 x 20 screws, all one document as the BOM lists them."""

CLAMP_MM = 1.5
"""What each screw clamps: the cover's 8.0 mm under its 6.5 mm deep counterbores, the stack the
key at `5cfb743` states. The package lays no face and the cover states no `Thickness`, so nothing
measures it: `check_fastener_joint` reports the cover's layer unknown and, the row carrying no
usable thread depth, leaves bottoming and engagement unresolved."""

TAPS_AXIS = (20.0, 20.0)
"""The (x, y) of the tapped-hole row's one axis, its first hole's, along z: the row has no face
(`PackageBuilder.hole`'s `faceless_axis`), so it states no other."""

ORIGIN = (0.0, 0.0, 0.0)
Z = (0.0, 0.0, 1.0)
"""Where every screw's head bears and its axis: the identity transform's, as the BOM places it."""

IDENTITY_TRANSFORM: list[list[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
"""The transform the ingest gives a component built from the BOM."""

PLACEHOLDER_REASON = (
    "component instances built from the BOM carry placeholder persist_refs "
    "(base64 of 'exported:<document_id>:<n>'), an identity transform, resolved "
    "suppression and is_toolbox=False; the exported files state none of these, so no "
    "finding may navigate to a SOLIDWORKS entity or rely on component position until a "
    "native extraction replaces them"
)
"""The placeholder `persist_ref` gap's reason, in `swreview.ingest.package_builder`'s words,
which the generator may not import (`generator.md` 9)."""

THREAD_DEPTH_REASON = "usable thread depth not reported by the hole feature"
"""The reason of the gap a tapped hole with no usable thread depth carries
(`tests/support/packages.py`)."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "housing_doc": DocumentPlace(tree=Tree()),
    "cover_doc": DocumentPlace(tree=Tree()),
    "housing_drw": DocumentPlace(),
    "cover_drw": DocumentPlace(),
    "housing": ComponentPlace(document="housing_doc"),
    "cover": ComponentPlace(document="cover_doc"),
    # Drilled 14 deep; no usable thread depth, as the row always was (`cases.md` 6.4).
    "taps": HolePlace(component="housing", thread="M6x1.0", hole_depth_mm=14.0, count=4),
    # BOM-shaped: placed on no hole's axis.
    **{
        screw: ScrewPlace(
            thread=SCREW_THREAD,
            length_mm=SCREW_LENGTH_MM,
            hole="taps",
            clamped=("cover",),
            clamp_mm=CLAMP_MM,
            seated=False,
        )
        for screw in SCREWS
    },
    # The callout `seeds.CALLOUT_DRILL_ONLY` writes for `taps`: count, thread and drill depth.
    "callout": DimensionPlace(
        drawing="housing_drw", nominal_mm=14.0, limits=None, text="4X M6x1.0 - 6H DRILL ↧ 14"
    ),
    # The spigot fit drawn for clearance (`seeds.CLEARANCE`, the 40 H7/g6 limits).
    "bore": DimensionPlace(
        drawing="housing_drw", nominal_mm=40.0, limits=seeds.CLEARANCE[0], prefix="Ø"
    ),
    "spigot": DimensionPlace(
        drawing="cover_drw", nominal_mm=40.0, limits=seeds.CLEARANCE[1], prefix="Ø"
    ),
    "thickness": DimensionPlace(
        drawing="cover_drw",
        nominal_mm=COVER_THICKNESS_MM,
        limits=("symmetric", 0.1),
        nominal_text="8.0",
    ),
    "counterbores": DimensionPlace(
        drawing="cover_drw", nominal_mm=11.0, limits=None, text="4X ⌴ Ø11 ↧ 6.5"
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
    (`generator.md` 5.1): the documents and the components; the tapped-hole row with its record's
    thread, depths and offset, faceless, and the gap of a thread depth it does not state; the
    screws with their fastener rows at the origin, one document per thread and length. Then the
    package made BOM-shaped (`PackageBuilder.screw` meshes every screw, and the ingest reads no
    body, so the bodies and meshes are dropped; every component given its placeholder reference
    and the identity transform, the housing fixed, and the placeholder gap), the screws'
    document moved into the bought folder and the custom parts' trees laid; then the two
    ingested drawings, the cover's second sheet unreadable, and every drawn dimension, in place
    order. Every document is laid opened and every screw unseated: a record that asks otherwise
    is refused, since the BOM places nothing."""
    if variant is not None:
        raise ValueError(f"design cover has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design cover lays every document opened, not {', '.join(unopened)}")
    seated = [
        name for name, record in places.items() if isinstance(record, ScrewPlace) and record.seated
    ]
    if seated:
        raise ValueError(
            "design cover lays every component where the BOM puts it, at the identity transform, "
            f"so no screw sits on its hole's axis: not {', '.join(seated)}"
        )
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "blind tap assy")
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
    for name in ("housing", "cover"):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        ids[name] = builder.component(str(ids[record.document]))

    taps = places["taps"]
    assert isinstance(taps, HolePlace) and taps.thread is not None
    x, y = TAPS_AXIS
    hole_id = builder.hole(
        str(ids[taps.component]),
        hole_type="tapped",
        size=taps.thread,
        thread=taps.thread,
        thread_depth_mm=taps.thread_depth_mm,
        hole_depth_mm=taps.hole_depth_mm,
        end_condition="blind" if taps.hole_depth_mm is not None else "through",
        instances=(),
        faceless_axis=Instance((x + taps.offset_mm, y, 0.0), Z, ()),
    )
    ids["taps"] = hole_id
    if taps.thread_depth_mm is None:
        builder.gap(
            kind="not_extracted",
            entity_kind="hole",
            entity_id=hole_id,
            reason=THREAD_DEPTH_REASON,
            error=None,
        )

    # One screw document per thread and length, as a vendor's part is, each screw an instance.
    screw_documents: dict[tuple[str, float], str] = {}
    screws: dict[str, str] = {}
    for name in SCREWS:
        record = places[name]
        assert isinstance(record, ScrewPlace)
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
            screw_documents[drawn], bearing_mm=ORIGIN, direction=Z, fastener_row=True
        )

    built = builder.build()
    package = built.package
    for name, component in screws.items():
        ids[name] = next(row.id for row in package.fasteners if row.component_id == component)
    bought = set(screw_documents.values())
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
    instances: dict[str, int] = {}
    components = []
    for row in package.components:
        instances[row.document_id] = instances.get(row.document_id, 0) + 1
        placeholder = f"exported:{row.document_id}:{instances[row.document_id]}"
        components.append(
            row.model_copy(
                update={
                    "persist_ref": persist_ref(placeholder),
                    "transform": IDENTITY_TRANSFORM,
                    "is_fixed": row.id == ids["housing"],
                }
            )
        )
    gaps = [
        *package.gaps,
        Gap(
            kind="not_extracted",
            entity_kind="persist_ref",
            entity_id=None,
            reason=PLACEHOLDER_REASON,
            error=None,
        ),
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
            "bodies": [],
            "gaps": gaps,
            "features": features,
            "equations": equations,
        }
    )

    sheets = SheetBuilder(package)
    for name, (stem, summary) in DRAWINGS.items():
        ids[name] = sheets.drawing(stem, properties=_custom(places[name], stem, summary))
        sheets.sheet(str(ids[name]), page=1)
    drawing, sheet, page = UNREADABLE_SHEET
    sheets.sheet(str(ids[drawing]), sheet, page=page, readable=False)
    for name, record in places.items():
        if isinstance(record, DimensionPlace):
            ids[name] = sheets.dimension(
                str(ids[record.drawing]),
                record.sheet,
                record.nominal_mm,
                limits=record.limits,
                text=record.as_read(),
            )
    return Laid(package=sheets.build(), meshes={}, ids=ids)


DESIGN = Design(name="cover", places=PLACES, lay=lay)

# --- the case --------------------------------------------------------------------------------

CBT = TunedOn("prompt-encodes-cbt-answer")
"""Every item is tuned-on: the prompt, checklist and tool docstrings state the product's
unknown-thread-depth policy, so the case cannot count as held out (research §2; FR-010)."""

CALLOUT = {"callout": "callout", "hole": "taps"}
"""The housing drawing's callout of the tapped holes the screws go into."""

SPIGOT_FIT = {"bore": "bore", "shaft": "spigot"}
"""The cover's spigot in the housing's bore: the bore on the housing's drawing, the spigot on the
cover's."""

SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="cover-blind-tap",
        design=DESIGN,
        seeds=(
            Seed(seeds.BOTTOMING_THREAD_DEPTH_UNKNOWN, {"hole": "taps"}, CBT),
            Seed(seeds.CALLOUT_DRILL_ONLY, CALLOUT, CBT),
        ),
        conditions=(
            Condition(
                tag=CBT,
                description=(
                    "The cover's locating spigot, Ø40 -0.009/-0.025, in the housing's hole, "
                    "Ø40 +0.025/0: a correct clearance fit."
                ),
                kind=seeds.SLIP_FIT,
                at=SPIGOT_FIT,
            ),
        ),
        sets=("pilot",),
    ),
)
"""`cover-blind-tap` (`cases.md` 6.4; `answer-key.md` 7.1), in `pilot.json` only."""
