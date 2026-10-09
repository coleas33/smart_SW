"""The mir design (`cases.md` 6.3): the 2026-09-26 sitting in one package: a custom plate, a vendor
pin of two instances, a same-name drawing beside the assembly and the plate.

**The clean base** (`generator.md` 5.1 to 5.5; the design rules of `tasks.md`'s case-spec phase).
The custom plate, fixed, 100 x 60 x 10 mm, lies below z = 0 under the custom root assembly, and
two instances of one bought Ø3 x 20 dowel pin stand on its top face, 60 mm apart. Every name is
the example profile's: the assembly and the plate `EX-1110-..`, each with the data card, the
revision under the profile's `revision.property`, the hygiene number equal to the stem and a
summary unique in the package; the pin bought, in the profile's bought folder with a vendor
property, carrying its revision too. The plate carries `spec.tree_specs`' compliant tree. Beside
the assembly and beside the plate lies a same-name drawing (`DrawingBuilder.candidate`), their
stems distinct, so the two are two files and neither shares a part number (CS-10); no drawing
document, record or sheet is laid, so nothing of either can be read (R-2). The package holds no
hole, screw, face, mesh, interference row or drawn dimension: no anchor of the sitting needs one,
and with none there is no tolerance source (design rule 4) and nothing a joint, fit or
interference check could read wrong. `tests/support/sitting.py` gave the shape; it writes profile
A's names, so it is read, never imported (`generator.md` 5.2).

**Places** (rule 2): the documents `assy`, `plate_doc` and `pin_doc`; the components `plate`,
`pin_a` and `pin_b`, the pin's two instances.

**The variant**: `SITTING`, the sitting's documents as they were recorded: every model document's
revision under `Rev`, never the profile's `DocRev` (R-8), and the pin carrying a hygiene part
number with the company's custom prefix, against its bought folder and its vendor property
(R-1), which `_decide` leaves unclear by conflict (`checks/part_roles.py:600-608`).

**The anchor cases** (`cases.md` 6.3; FR-029; 15A; CS-10, INT-8, SR-22, RF-80): every item
tuned-on, no twin.

- `mir-sitting` (R-1, R-2, R-7, R-8), `SITTING`: the plate's tree non-compliant, R-7's four kinds
  each keyed on it (code, demonstrated); forbidden `rms.*` and `hygiene.*` on the pin and exactly
  one part-roles question (R-1); forbidden `drawing.*` on the three model documents, an
  unanswerable request for the pin's drawing and `drawing.manufacturing_inputs` expected
  unresolved (R-2); forbidden `hygiene.revision_present` on every model document (R-8), with no
  "profile likely wrong" line expected (SR-22); the engineer answers the part-roles question "All
  bought", and nothing answers the drawing candidate question, which an attempt never asks
  (INT-8).
- `mir-sitting-positive` (R-8, R-7, R-1): the base, clean but for `revision_missing` on the plate
  (code, demonstrated); R-7's four checks keyed as correct conditions on the plate's compliant
  tree; the pin decided bought, no custom signal against it, so no question is asked.
"""

from __future__ import annotations

import math

from swreview.ir.models import SourceRef
from tests.benchmark_cases import seeds
from tests.benchmark_cases.spec import (
    Answer,
    CaseSpec,
    ComponentPlace,
    Condition,
    Coverage,
    Design,
    DocumentPlace,
    Forbidden,
    Laid,
    Place,
    Places,
    QuestionCount,
    Seed,
    SeedKind,
    Tree,
    TunedOn,
    Unanswerable,
    tree_specs,
)
from tests.benchmark_cases.vocabulary import EXAMPLE_PROFILE
from tests.support.drawings import DrawingBuilder
from tests.support.features import PartSpec, part_trees
from tests.support.mechanical import (
    FICTIONAL_ROOT,
    STEEL_DENSITY_KG_M3,
    PackageBuilder,
    transform,
)
from tests.support.standards import card

# --- the shape -------------------------------------------------------------------------------

ASSY_STEM, PLATE_STEM = "EX-1110-00", "EX-1110-01"
"""The custom documents' stems, the example profile's part-number shape with a custom prefix
(`generator.md` 5.2), distinct so each has a same-name drawing of its own (CS-10)."""

PIN_STEM = "FICT-PIN-3X20-0001"
"""The bought dowel pin, Ø3 x 20, in the vendor file shape."""

PIN_NUMBER = "EX-1110-02"
"""The hygiene part number the sitting's pin carries under `SITTING`: the company's custom prefix
(medium, custom; `config/standards.example.yaml` `custom_prefixes`), no other document's number."""

BOUGHT_FOLDER = EXAMPLE_PROFILE.part_roles.bought_folder_names[0]
VENDOR = EXAMPLE_PROFILE.part_roles.vendor_properties[0]
"""Where the pin lies and the property that names its vendor: two strong bought signals
(`generator.md` 5.2)."""

RECORDED_REVISION = "Rev"
"""The property the sitting's documents carry their revision under, a near-synonym of the example
profile's `DocRev` (`config/standards.example.yaml:57-60`; research §3 R-8)."""

SITTING = "sitting"
"""The sitting's documents as recorded (`mir-sitting`): every model document's revision under
`RECORDED_REVISION`, and the pin's hygiene part number `PIN_NUMBER`."""

VARIANTS = (SITTING,)
"""The design's variants (`Design.variants`)."""

ALUMINIUM_DENSITY_KG_M3 = 2700.0
"""6061-T6's density, the plate's material."""

PLATE_MM = (100.0, 60.0, 10.0)
"""The plate's length, width and thickness: it lies from z = -10 to 0."""

PIN_DIAMETER_MM, PIN_LENGTH_MM = 3.0, 20.0

PINS: dict[str, tuple[float, float]] = {"pin_a": (20.0, 30.0), "pin_b": (80.0, 30.0)}
"""Each pin instance's (x, y) on the plate's top face, its axis along z."""

# --- the places ------------------------------------------------------------------------------

PLACES: dict[str, Place] = {
    "assy": DocumentPlace(),
    "plate_doc": DocumentPlace(tree=Tree()),
    "pin_doc": DocumentPlace(),
    "plate": ComponentPlace(document="plate_doc"),
    "pin_a": ComponentPlace(document="pin_doc"),
    "pin_b": ComponentPlace(document="pin_doc"),
}


# --- laying it -------------------------------------------------------------------------------


def _revision(place: Place, variant: str | None) -> dict[str, str]:
    """The document's revision where its record carries one: under the profile's
    `revision.property`, or under `RECORDED_REVISION` as the sitting's documents carry it."""
    assert isinstance(place, DocumentPlace)
    if not place.revision:
        return {}
    name = RECORDED_REVISION if variant == SITTING else EXAMPLE_PROFILE.revision.property
    return {name: "A"}


def _custom(place: Place, stem: str, summary: str, variant: str | None) -> dict[str, str]:
    """A custom document's properties in the example profile's names (`generator.md` 5.2): the
    data card, the revision where its record carries one, the hygiene number equal to the stem
    and the summary."""
    hygiene = EXAMPLE_PROFILE.hygiene
    assert hygiene is not None
    return {
        **card(EXAMPLE_PROFILE),
        **_revision(place, variant),
        hygiene.part_number_property: stem,
        hygiene.description_property: summary,
    }


def _pin(place: Place, variant: str | None) -> dict[str, str]:
    """The bought pin's properties: its vendor and description, its revision, and under `SITTING`
    the hygiene part number with the custom prefix (R-1)."""
    hygiene = EXAMPLE_PROFILE.hygiene
    assert hygiene is not None
    number = {hygiene.part_number_property: PIN_NUMBER} if variant == SITTING else {}
    return {
        VENDOR: "FICT",
        "Description": "PIN, DOWEL Ø3 X 20 MM, FICTIONAL",
        **_revision(place, variant),
        **number,
    }


def _mass_kg(volume_mm3: float, density_kg_m3: float) -> float:
    return round(volume_mm3 * 1e-9 * density_kg_m3, 9)


def lay(variant: str | None, places: Places) -> Laid:
    """The base with every form applied, laid from `places` through the builders
    (`generator.md` 5.1): the documents and the components (the plate fixed, each pin instance on
    its axis); then the pin moved into the bought folder and the plate's tree laid; then the
    same-name drawing beside the assembly and beside the plate. Every document is laid opened: no
    mir case leaves one unread, and a record that asks it is refused."""
    if variant not in (None, *VARIANTS):
        raise ValueError(f"design mir has no variant {variant}")
    unopened = [
        name
        for name, record in places.items()
        if isinstance(record, DocumentPlace) and not record.opened
    ]
    if unopened:
        raise ValueError(f"design mir lays every document opened, not {', '.join(unopened)}")
    builder = PackageBuilder(
        ASSY_STEM, root_properties=_custom(places["assy"], ASSY_STEM, "mir assy", variant)
    )
    ids: dict[str, str | SourceRef] = {"assy": builder.root_id}
    length_mm, width_mm, thickness_mm = PLATE_MM
    plate_volume_mm3 = length_mm * width_mm * thickness_mm
    ids["plate_doc"] = builder.document(
        PLATE_STEM,
        "part",
        material="6061-T6",
        mass_kg=_mass_kg(plate_volume_mm3, ALUMINIUM_DENSITY_KG_M3),
        volume_mm3=plate_volume_mm3,
        properties=_custom(places["plate_doc"], PLATE_STEM, "mir plate", variant),
    )
    pin_volume_mm3 = round(math.pi / 4.0 * PIN_DIAMETER_MM**2 * PIN_LENGTH_MM, 6)
    ids["pin_doc"] = builder.document(
        PIN_STEM,
        "part",
        material="Alloy Steel",
        mass_kg=_mass_kg(pin_volume_mm3, STEEL_DENSITY_KG_M3),
        volume_mm3=pin_volume_mm3,
        properties=_pin(places["pin_doc"], variant),
    )
    for name in ("plate", *PINS):
        record = places[name]
        assert isinstance(record, ComponentPlace)
        axis = PINS.get(name)
        ids[name] = builder.component(
            str(ids[record.document]),
            placement=None if axis is None else transform((*axis, 0.0)),
        )

    built = builder.build()
    package = built.package
    documents = [
        document.model_copy(
            update={"path": f"{FICTIONAL_ROOT}Vault\\{BOUGHT_FOLDER}\\{document.file_name}"}
        )
        if document.document_id == ids["pin_doc"]
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
    plate_doc = places["plate_doc"]
    assert isinstance(plate_doc, DocumentPlace) and plate_doc.tree is not None
    plate_features, plate_equations = tree_specs(plate_doc.tree)
    features, equations = part_trees(
        [
            PartSpec(
                document_id=str(ids["plate_doc"]),
                name=PLATE_STEM,
                features=plate_features,
                equations=plate_equations,
            )
        ]
    )
    package = package.model_copy(
        update={
            "documents": documents,
            "manifest": package.manifest.model_copy(update={"entries": entries}),
            "components": components,
            "features": features,
            "equations": equations,
        }
    )

    drawings = DrawingBuilder(package)
    for name in ("assy", "plate_doc"):
        drawings.candidate(str(ids[name]))
    return Laid(package=drawings.build(), meshes=built.meshes, ids=ids)


DESIGN = Design(name="mir", places=PLACES, lay=lay, variants=VARIANTS)

# --- the cases -------------------------------------------------------------------------------

R1, R2, R7, R8 = TunedOn("R-1"), TunedOn("R-2"), TunedOn("R-7"), TunedOn("R-8")
"""Every mir item is tuned-on: the anchors were recorded on the sitting (15A)."""

PLATE = {"component": "plate"}
"""R-7's and R-8's kinds on the custom plate."""

R7_KINDS = (
    seeds.RMS_SKETCHES_FULLY_DEFINED,
    seeds.STANDARDS_SKETCHES_FULLY_DEFINED,
    seeds.RMS_GROUPING,
    seeds.RMS_GLOBAL_VARIABLES,
)
"""R-7's four kinds, each its own entry: the under-defined sketch as the two families list it,
the loose features and the missing global variable (`cases.md` 6.3)."""

MODEL_DOCUMENTS = ("assy", "plate_doc", "pin_doc")
"""The model documents, each of which R-2's and R-8's forbidden entries name."""


def _compliant(kind: SeedKind) -> Condition:
    """R-7's kind `kind` as a correct condition on the plate's compliant tree, its clean form."""
    assert kind.clean is not None
    return Condition(
        tag=R7,
        description=f"The plate's tree is compliant: {kind.clean.words} (R-7's clean case).",
        kind=kind,
        at=PLATE,
        represents="R-7",
    )


SPECS: tuple[CaseSpec, ...] = (
    CaseSpec(
        case_id="mir-sitting",
        design=DESIGN,
        variant=SITTING,
        seeds=tuple(Seed(kind, PLATE, R7, represents="R-7") for kind in R7_KINDS),
        forbidden=(
            Forbidden(
                checks=("rms.*", "hygiene.*"),
                tag=R1,
                description=(
                    "The pin is a vendor part: its modelling practice and hygiene are not graded, "
                    "however its own signals disagree about its role (R-1)."
                ),
                component_ids=("pin_a", "pin_b"),
                document_ids=("pin_doc",),
                represents="R-1",
            ),
            Forbidden(
                checks=("drawing.*",),
                tag=R2,
                description=(
                    "No drawing was read: the same-name drawings beside the assembly and the "
                    "plate were not opened, and the pin has none, so no drawing finding stands "
                    "on any of them (R-2)."
                ),
                document_ids=MODEL_DOCUMENTS,
                represents="R-2",
            ),
            Forbidden(
                checks=("hygiene.revision_present",),
                tag=R8,
                description=(
                    "Every document carries its revision under Rev, a property the profile does "
                    "not name: the profile is wrong, not the documents (R-8)."
                ),
                component_ids=("plate", "pin_a", "pin_b"),
                document_ids=MODEL_DOCUMENTS,
                represents="R-8",
            ),
        ),
        expected_coverage=(
            Coverage(
                item="drawing.manufacturing_inputs",
                statuses=("unresolved",),
                tag=R2,
                description=(
                    "The drawings beside the assembly and the plate were found and not read: the "
                    "drawing inputs stay unresolved, never checked (R-2)."
                ),
                represents="R-2",
            ),
        ),
        unanswerable_requests=(
            Unanswerable(
                documents=("pin_doc",),
                tag=R2,
                description=(
                    "A vendor pin's drawing can never be supplied: a request for it cannot be "
                    "answered (R-2)."
                ),
                represents="R-2",
            ),
        ),
        question_counts=(
            QuestionCount(
                tag=R1,
                description=(
                    "Code asks once which parts are bought, the pin's signals disagreeing; it is "
                    "asked exactly once (R-1)."
                ),
                part_roles=True,
                min=1,
                max=1,
                represents="R-1",
            ),
        ),
        answers=(Answer(answer="All bought", part_roles=True),),
        represents=("R-1", "R-2", "R-7", "R-8"),
        sets=("committed",),
    ),
    CaseSpec(
        case_id="mir-sitting-positive",
        design=DESIGN,
        seeds=(Seed(seeds.REVISION_MISSING, PLATE, R8, represents="R-8"),),
        conditions=tuple(_compliant(kind) for kind in R7_KINDS),
        represents=("R-8", "R-7", "R-1"),
        sets=("committed",),
    ),
)
"""The anchor cases (`cases.md` 6.3): the sitting as it happened, then its positive form."""
