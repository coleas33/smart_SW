"""The case spec, its places and its checks (feature 014 `generator.md` 2, 4 and 10; data-model
section 5; CS-1, GN-4, GN-8).

A committed case is written as a `CaseSpec`: a design (its clean base and places), seeds of the
kinds `seeds.py` defines, the key-only entries, scripted answers and the anchors it represents.
Nothing in a spec is an id: every id a seed, an entry, an answer, a correct call or a decoy
carries is written as a **place name** the design defines, and `render.py` resolves it to the id
the design's builders gave the place, so no id is typed twice and a builder that renumbers moves
every reference with it.

**Places are records.** A design names each component, document, hole, fastener, drawn dimension
and interference contact it builds, and holds a record for each: what a seed kind's forms read
and change there (a screw's thread and length, a hole's thread depth or offset, a dimension's
limits or text, a document's revision, a contact's volume), and the place names it links to (a
screw's hole and clamped stack, a dimension's drawing). A design's `lay` builds the package from
its records with the builders of `generator.md` 5.1, honouring every field; a seed's form
changes records, never ids, so `Design.build(variant, forms)` lays the clean base with every form
applied through the same builder calls.

**What the kind fixes.** A seed's check, producer, expected status and withheld evidence come
from its kind (`SeedKind`); its family is `families.family_of(check)`. The withheld evidence, the
correct calls and the decoys live in the specs only: no committed file holds them.

**The checks** (section 10). `check_specs` runs rows 1 to 7 and row 8's per-entry halves over any
list of specs, one spec at a time, rows in order, the first failing row ending the run;
`check_anchor_coverage` runs row 8's coverage half, which holds only over the whole set. Rows 9 to
11 need what was rendered and live in `render.py`. Every refusal is a `CaseSpecError` whose
message starts "case spec {case id}:".
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal
from uuid import UUID

from swreview.benchmark.answer_key_model import ExpectedStatus, Producer, Stamp
from swreview.benchmark.families import ANCHOR_FAMILY, Family, family_of
from swreview.ir.models import Document, EvidencePackage, ManifestEntry, SourceRef
from tests.benchmark_cases import stamps
from tests.benchmark_cases.vocabulary import CASE_VOCABULARY
from tests.support.drawings import Limits
from tests.support.features import (
    EquationSpec,
    FeatureSpec,
    equation,
    feature,
    fillet_feature,
    folder,
    sketch_feature,
)

CASE_NAMESPACE = UUID("01400000-0000-4000-8000-0000000c45e5")
"""The namespace of every generated package's IR `package_id`, `uuid5(CASE_NAMESPACE, case_id)`:
a UUID distinct from the set's and the key's `package_id`, which is the case id (`generator.md`
5.5; GN-4)."""


class CaseSpecError(ValueError):
    """A case spec the generator refuses (`generator.md` 10): "case spec {case id}: {detail}"."""

    def __init__(self, case_id: str, detail: str) -> None:
        super().__init__(f"case spec {case_id}: {detail}")
        self.case_id = case_id
        self.detail = detail


# --- section 2: tags, calls and place names --------------------------------------------------


@dataclass(frozen=True)
class HeldOut:
    stamp: Stamp
    """`stamps.CURRENT` (`cases.md` 5); row 4 refuses another."""


@dataclass(frozen=True)
class TunedOn:
    reason: str
    """"R-3", "prompt-encodes-cbt-answer", ...; row 4 refuses a blank one."""


Tag = HeldOut | TunedOn
Withheld = Literal["joint_placement", "joint_absent", "tolerance_source", "drawing_only"]


@dataclass(frozen=True)
class ToolCall:
    """A call a correct reviewer, or a decoy, makes (`cases.md` 7)."""

    tool: str
    """A registered tool's name."""
    arguments: Mapping[str, Any]
    """Its arguments by parameter name, `PlaceName`s resolved to ids at render."""


@dataclass(frozen=True)
class PlaceName:
    """A place name inside a reference element or a call's arguments, resolved at render
    (`render.resolve`) to the id the design gave the place: a component, document, hole,
    fastener or contact id, or a drawn dimension's `{document_id, sheet, annotation}`;
    with `instance`, a hole instance `"<hole id>#<n>"` as the joint map writes it."""

    name: str
    instance: int | None = None


# --- places ----------------------------------------------------------------------------------

PlaceKind = Literal["component", "document", "hole", "fastener", "dimension", "contact"]


@dataclass(frozen=True)
class ComponentPlace:
    """A component instance."""

    KIND: ClassVar[PlaceKind] = "component"
    document: str
    """The document place it is an instance of."""


@dataclass(frozen=True)
class Tree:
    """A custom part's feature tree, as `tree_specs` lays it: compliant unless a flag says
    otherwise. The four R-7 kinds (`seeds.py`) plant and clean these flags."""

    sketches_defined: bool = True
    """False: the Core sketch is under-defined (`rms.sketches.fully_defined`,
    `standards.part.sketches_fully_defined`)."""
    grouped: bool = True
    """False: twenty content features sit outside every group folder
    (`rms.grouping.all_features_in_a_group`)."""
    global_variable: bool = True
    """False: the equations hold no global variable, while one still drives a dimension
    (`rms.params.global_variables_present`)."""


@dataclass(frozen=True)
class DocumentPlace:
    """A part, assembly or drawing document."""

    KIND: ClassVar[PlaceKind] = "document"
    revision: bool = True
    """It carries the example profile's revision property (`revision.property`)."""
    opened: bool = True
    """It was opened: its properties, material and mass were read, and every instance of it is
    resolved. False: `PackageBuilder.document(opened=False)`, every instance lightweight, no
    face, mesh or interference row of them."""
    tree: Tree | None = None
    """A custom part's feature tree, laid with `tree_specs`; `None` for every other document."""


@dataclass(frozen=True)
class HolePlace:
    """A Hole Wizard feature: one `Hole` row."""

    KIND: ClassVar[PlaceKind] = "hole"
    component: str
    """The component place it is cut in."""
    thread: str | None = None
    """A tapped hole's thread as the hole row writes it, "M5x0.8"; `None` for any other."""
    thread_depth_mm: float | None = None
    """A tapped hole's usable thread depth; `None` is not extracted, with the gap that says so."""
    hole_depth_mm: float | None = None
    """A blind hole's drill depth."""
    count: int = 1
    """Its instances: what a callout's "<n>X" counts."""
    offset_mm: float = 0.0
    """How far the design moves it off its own axis, at right angles to that axis: a hole pair's
    misalignment, a pin's offset from a clearance hole."""


@dataclass(frozen=True)
class ScrewPlace:
    """A screw, laid with `PackageBuilder.screw(..., fastener_row=True)` (GN-2): the place's id is
    its `Fastener` row's."""

    KIND: ClassVar[PlaceKind] = "fastener"
    thread: str
    """Its thread in the vendor name's form, "M5-0.8" (`PackageBuilder.screw_document`)."""
    length_mm: float
    hole: str
    """The hole place it goes into."""
    clamped: tuple[str, ...]
    """The component places it clamps, from the head down."""
    clamp_mm: float
    """The thickness of that stack as the design builds it, which `check_fastener_joint`
    measures from the clamped components' face boxes along the screw's axis; its reach past
    the stack is `length_mm - clamp_mm`."""
    seated: bool = True
    """On its hole's axis, so the joint map places it. False: on no extracted hole axis (more
    than the joint rules' 0.2 mm from every one) and no face of it a hole's member face, so the
    joint map leaves it unplaced (`joint_placement`, `generator.md` 3)."""


_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")
"""A nominal as a drawing writes it: digits, then a decimal point and digits or nothing."""


@dataclass(frozen=True)
class DimensionPlace:
    """A dimension drawn on an ingested sheet (`SheetBuilder.dimension`): the place's id is its
    `SourceRef`, the triple `resolve_dimension` matches."""

    KIND: ClassVar[PlaceKind] = "dimension"
    drawing: str
    """The drawing document place it is drawn on."""
    nominal_mm: float
    limits: Limits
    sheet: str = "Sheet1"
    prefix: str = ""
    """What its text says before the nominal: "Ø", "2X Ø"."""
    text: str | None = None
    """Its text as read, when it is not the prefix, nominal and limits (a callout, a position
    tolerance); a form that changes the limits clears it."""
    nominal_text: str | None = None
    """The nominal as the drawing writes it, "3.0" where `nominal_mm` would read "3" (`cases.md`
    6.3's "2X Ø3.0 +0.010/0"; owner decision 56A): plain decimal digits that read as
    `nominal_mm`. A form that moves the nominal clears it."""

    def __post_init__(self) -> None:
        if self.nominal_text is None:
            return
        written = self.nominal_text
        if _DECIMAL.fullmatch(written) is None or float(written) != self.nominal_mm:
            raise ValueError(
                f"dimension nominal_text {self.nominal_text!r} does not write its nominal "
                f"{self.nominal_mm:g} mm"
            )

    def as_read(self) -> str:
        """The text the sheet carries: `text`, or the prefix, the nominal (as written, where
        `nominal_text` says) and the limits as a drawing writes them ("Ø3 +0.025/0",
        "2X Ø3.0 +0.010/0", "8 ±0.1")."""
        if self.text is not None:
            return self.text
        nominal = self.nominal_text if self.nominal_text is not None else f"{self.nominal_mm:g}"
        return f"{self.prefix}{nominal}{_tolerance_text(self.limits)}"


def _tolerance_text(limits: Limits) -> str:
    if limits is None:
        return ""
    if limits[0] == "symmetric":
        return f" ±{limits[1]:g}"
    _, upper, lower = limits
    return f" {_deviation(upper)}/{_deviation(lower)}"


def _deviation(value: float) -> str:
    """A signed deviation as a drawing writes it: "0", "+0.010", "-0.025"."""
    return "0" if value == 0 else f"{value:+.3f}"


@dataclass(frozen=True)
class ContactPlace:
    """An interference row between two components (`PackageBuilder.interference`)."""

    KIND: ClassVar[PlaceKind] = "contact"
    a: str
    b: str
    """The two component places."""
    volume_mm3: float | None = 0.0
    """The row's volume: 0.0 a zero-volume contact, `None` a row with no volume."""
    overlap_mm3: float | None = None
    """The positive volume the design's geometry gives the pair when it overlaps, which
    `interference_positive` plants; `None` where no overlap is planted."""
    possible: bool = False
    """A "possible" row with no volume (R-4's third row)."""


Place = ComponentPlace | DocumentPlace | HolePlace | ScrewPlace | DimensionPlace | ContactPlace
Places = Mapping[str, Place]
At = Mapping[str, str]
"""A seed's or condition's roles, each to a place name."""


# --- section 3: seed kinds and their forms ----------------------------------------------------


@dataclass(frozen=True)
class Laid:
    """What a design's `lay` returns: the built package, its meshes and each place's id."""

    package: EvidencePackage
    meshes: Mapping[str, bytes]
    ids: Mapping[str, str | SourceRef]
    """Every place name to its id; a drawn dimension's is its `SourceRef`."""


@dataclass(frozen=True)
class Form:
    """A seed kind's planted or clean form: the records it replaces at a seed's places, and its
    words (a twin's condition reads "clean twin of <case> D-<n>: <words>")."""

    words: str
    apply: Callable[[At, Places], Mapping[str, Place]]
    """`(at, places)` to the replaced records, by place name; ids never change."""


def _nothing(at: At, places: Places) -> tuple[()]:
    return ()


@dataclass(frozen=True)
class SeedKind:
    """One kind of planted defect (`generator.md` 3): what it is keyed as, the evidence it
    withholds, its forms, and what a correct reviewer and a decoy call.

    `roles` are the places a seed names, each with the place kind it takes; `optional_roles` may
    be named. Every callable takes the seed's `at` and the design's records with every form
    applied: `references` the key's reference elements, with `PlaceName`s; `parts` and
    `documents` the component and document places the entry names beside its references' owners
    (`answer-key.md` 4 row 14, which `render.py` adds); `correct_calls` what a correct reviewer
    calls; `decoys` the calls on the places beside it that must not credit, flag or clear it.
    `confirms_clean` says whether those correct calls confirm the clean form, so that a condition
    of the kind carries them (`generator.md` 4).
    """

    name: str
    check: str
    producer: Producer
    expected_status: ExpectedStatus | None
    """`None` exactly for a kind with no planted form, which is never a defect."""
    withheld: tuple[Withheld, ...]
    roles: Mapping[str, PlaceKind]
    plant: Form | None
    clean: Form | None
    """`None` for a kind with no clean form, which no twin and no condition can take (row 6)."""
    references: Callable[[At, Places], Sequence[Mapping[str, Any]]] = _nothing
    parts: Callable[[At, Places], Sequence[str]] = _nothing
    documents: Callable[[At, Places], Sequence[str]] = _nothing
    correct_calls: Callable[[At, Places], Sequence[ToolCall]] = _nothing
    decoys: Callable[[At, Places], Sequence[ToolCall]] = _nothing
    optional_roles: Mapping[str, PlaceKind] = field(default_factory=dict)
    confirms_clean: bool = True
    """False where no correct call can confirm the clean form, so a condition of the kind
    (a twin's) carries none and validation leg (b) never asks it to confirm, while a finding
    contradicting it is still caught: a drawing kind, since a correct reviewer records nothing on
    a complete drawing, and `coaxiality_undrawn`, whose call writes unresolved on aligned holes
    with no tolerance drawn (owner decision 55A)."""

    def __post_init__(self) -> None:
        if (self.plant is None) != (self.expected_status is None):
            raise ValueError(
                f"seed kind {self.name}: an expected status exactly when it has a planted form"
            )
        if self.family == "drawing" and self.confirms_clean:
            raise ValueError(
                f"seed kind {self.name}: a drawing kind's correct call cannot confirm its clean "
                "form, a correct reviewer recording nothing on a complete drawing "
                "(confirms_clean=False; generator.md 4)"
            )

    @property
    def family(self) -> Family:
        """`families.family_of(check)`, never typed (`generator.md` 2)."""
        return family_of(self.check)


# --- designs ---------------------------------------------------------------------------------

Lay = Callable[[str | None, Places], Laid]


@dataclass(frozen=True)
class Design:
    """A design: its one-word name (the set entry's `design`), its places and its `lay`."""

    name: str
    places: Places
    lay: Lay
    """`(variant, places)` to the package: the clean base laid from the records with the
    builders of `generator.md` 5.1, every record's fields honoured."""
    variants: tuple[str, ...] = ()
    """The named variations of its base a spec may ask for (`kalo-fit-2`)."""

    def kind_of(self, place: str) -> PlaceKind | None:
        """The kind of `place`, or `None` when the design does not define it."""
        record = self.places.get(place)
        return None if record is None else record.KIND

    def formed(self, forms: Sequence[tuple[Form, At]]) -> dict[str, Place]:
        """The records with each form applied at its places, in order. A form replaces records
        of places the design defines, each by a record of the same kind."""
        places = dict(self.places)
        for form, at in forms:
            for name, record in form.apply(at, places).items():
                if name not in places or places[name].KIND != record.KIND:
                    raise ValueError(
                        f"the form {form.words!r} replaces {name}, which is no "
                        f"{record.KIND} place of design {self.name}"
                    )
                places[name] = record
        return places

    def build(self, variant: str | None, forms: Sequence[tuple[Form, At]]) -> Laid:
        """The clean base with every form applied, through the same builder calls."""
        return self.lay(variant, self.formed(forms))


def unlaid(name: str) -> Lay:
    """The `lay` of a design whose module is still a stub: it holds no spec, so nothing lays it."""

    def lay(variant: str | None, places: Places) -> Laid:
        raise NotImplementedError(f"design {name} is a stub: its case specs are not written yet")

    return lay


# --- a case's own documents, after the drawings (owner decision 64A) ---------------------------


@dataclass(frozen=True)
class SetAside:
    """Documents `set_aside` took out of a package, already under the ids they take after its
    drawings, with their manifest entries, for `laid_after` to append."""

    documents: tuple[Document, ...]
    entries: tuple[ManifestEntry, ...]


def set_aside(
    package: EvidencePackage, document_ids: Sequence[str], *, drawings: int
) -> tuple[EvidencePackage, SetAside]:
    """`package` less the documents `document_ids`, which must be its last, each renumbered as
    the documents that follow `drawings` drawings, every row naming it re-pointed: its manifest
    entry, set aside with it, its instances and its gaps (owner decision 64A).

    A case can lay a document its twin does not: a planted screw of another thread or length has
    a document of its own. Laid before the drawings, it would move every drawing's id, and the
    twin's conditions would name other documents than the case's defects (`generator.md` 4).
    Set aside while the drawings are laid and appended after them by `laid_after`, it leaves
    every document the case and its twin share under one id. Refused, naming the document: one
    that is not among the package's last, whose id the drawings would take out of order, and
    one another row names (a feature, the design, a persist ref's scope), which this does not
    re-point and which would come to name a drawing."""
    kept = len(package.documents) - len(document_ids)
    last = [document.document_id for document in package.documents[kept:]]
    for document_id in document_ids:
        if document_id not in last:
            raise ValueError(
                f"set_aside: {document_id} is not among the package's last documents "
                f"({_listed(last)}), so the drawings would take the ids around it"
            )
    dumped = package.model_dump(mode="json")
    for document_id in last:
        repointed = (
            2
            + sum(row.document_id == document_id for row in package.components)
            + sum(gap.entity_id == document_id for gap in package.gaps)
        )
        if _naming(dumped, document_id) != repointed:
            raise ValueError(
                f"set_aside: {document_id} is named by a row it does not re-point (only its "
                "document, its manifest entry, its instances and its gaps are)"
            )
    renamed = {
        document_id: f"doc:{kept + drawings + number:04d}"
        for number, document_id in enumerate(last, start=1)
    }
    aside = SetAside(
        documents=tuple(
            document.model_copy(update={"document_id": renamed[document.document_id]})
            for document in package.documents[kept:]
        ),
        entries=tuple(
            entry.model_copy(update={"document_id": renamed[entry.document_id]})
            for entry in package.manifest.entries
            if entry.document_id in renamed
        ),
    )
    remaining = package.model_copy(
        update={
            "documents": package.documents[:kept],
            "manifest": package.manifest.model_copy(
                update={
                    "entries": [
                        entry
                        for entry in package.manifest.entries
                        if entry.document_id not in renamed
                    ]
                }
            ),
            "components": [
                row.model_copy(update={"document_id": renamed[row.document_id]})
                if row.document_id in renamed
                else row
                for row in package.components
            ],
            "gaps": [
                gap.model_copy(update={"entity_id": renamed[gap.entity_id]})
                if gap.entity_id in renamed
                else gap
                for gap in package.gaps
            ],
        }
    )
    return remaining, aside


def laid_after(package: EvidencePackage, aside: SetAside) -> EvidencePackage:
    """`package`, its drawings laid, with the set-aside documents and their manifest entries
    appended after its own; refused, naming the first that does not, unless each takes the next
    id, which holds when exactly the drawings `set_aside` was told of were laid in between."""
    for number, document in enumerate(aside.documents, start=len(package.documents) + 1):
        if document.document_id != f"doc:{number:04d}":
            raise ValueError(
                f"laid_after: {document.document_id} does not follow the drawings, the next id "
                f"being doc:{number:04d}: set it aside for as many drawings as are laid"
            )
    return package.model_copy(
        update={
            "documents": [*package.documents, *aside.documents],
            "manifest": package.manifest.model_copy(
                update={"entries": [*package.manifest.entries, *aside.entries]}
            ),
        }
    )


def _naming(value: Any, document_id: str) -> int:
    """How many string values of a dumped package equal `document_id`, at any depth."""
    if isinstance(value, str):
        return int(value == document_id)
    if isinstance(value, Mapping):
        return sum(_naming(item, document_id) for item in value.values())
    if isinstance(value, list):
        return sum(_naming(item, document_id) for item in value)
    return 0


# --- section 2: the spec ---------------------------------------------------------------------


@dataclass(frozen=True)
class Seed:
    kind: SeedKind
    at: At
    """The kind's roles to the design's place names."""
    tag: Tag
    represents: str | None = None
    """An anchor (R-1 to R-8, then tuned-on) or analyst-found defect (AF-1 to AF-3) id."""


@dataclass(frozen=True)
class Condition:
    """A correct condition (`answer-key.md` 2.3): a seed kind at its places, whose check and
    references come from the kind and whose clean form `render.py` builds there (a twin's, a
    `slip_fit`), or a check, its places and references directly on the clean base. A kind's
    condition carries the kind's correct calls where they confirm its clean form
    (`SeedKind.confirms_clean`); a direct one the `correct_call` it names."""

    tag: Tag
    description: str
    kind: SeedKind | None = None
    at: At = field(default_factory=dict)
    check: str | None = None
    component_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    references: tuple[Mapping[str, Any], ...] = ()
    correct_call: ToolCall | None = None
    represents: str | None = None

    def __post_init__(self) -> None:
        if (self.kind is None) == (self.check is None):
            raise ValueError(
                "a condition names a seed kind and its places, or a check and its places, "
                "never both and never neither"
            )


@dataclass(frozen=True)
class Forbidden:
    """A forbidden entry (`answer-key.md` 2.4)."""

    checks: tuple[str, ...]
    tag: Tag
    description: str
    component_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    represents: str | None = None


@dataclass(frozen=True)
class Coverage:
    """An expected-coverage entry (`answer-key.md` 2.6)."""

    item: str
    statuses: tuple[str, ...]
    tag: Tag
    description: str
    represents: str | None = None


@dataclass(frozen=True)
class Unanswerable:
    """An unanswerable request (`questions.md` 5.1); `item` `None` is any item."""

    documents: tuple[str, ...]
    tag: Tag
    description: str
    item: str | None = None
    represents: str | None = None


@dataclass(frozen=True)
class QuestionCount:
    """A question-count rule (`questions.md` 5.2)."""

    tag: Tag
    description: str
    part_roles: bool | None = None
    item: str | None = None
    ids: tuple[str, ...] = ()
    min: int = 0
    max: int | None = None
    represents: str | None = None


@dataclass(frozen=True)
class Answer:
    """A scripted answer (`scripted-answers.md` 2.2): to the part-roles question, or to the
    questions on `item` (`None` for none) asked within `ids`."""

    answer: str
    part_roles: bool = False
    item: str | None = None
    ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    """`cases.md` 2."""
    design: Design
    variant: str | None = None
    seeds: tuple[Seed, ...] = ()
    """Keyed D-1, D-2, ... in this order."""
    conditions: tuple[Condition, ...] = ()
    """Correct conditions a twin does not supply."""
    forbidden: tuple[Forbidden, ...] = ()
    expected_coverage: tuple[Coverage, ...] = ()
    unanswerable_requests: tuple[Unanswerable, ...] = ()
    question_counts: tuple[QuestionCount, ...] = ()
    answers: tuple[Answer, ...] = ()
    represents: tuple[str, ...] = ()
    decoys: tuple[ToolCall, ...] = ()
    """`cases.md` 7, beside the decoys its seeds' kinds name."""
    twin: bool = False
    """Derive `<case_id>-twin` (section 4)."""
    sets: tuple[Literal["committed", "pilot"], ...] = ("committed",)


KeyOnly = Condition | Forbidden | Coverage | Unanswerable | QuestionCount


def key_only_entries(case: CaseSpec) -> list[tuple[str, str, KeyOnly]]:
    """Every key-only entry as (the key's list, the id `render.py` gives it, the entry), in
    section 2.1's order, each list numbered from 1 in spec order."""
    lists: list[tuple[str, str, Sequence[KeyOnly]]] = [
        ("correct_conditions", "C", case.conditions),
        ("forbidden", "FB", case.forbidden),
        ("expected_coverage", "CV", case.expected_coverage),
        ("unanswerable_requests", "U", case.unanswerable_requests),
        ("question_counts", "Q", case.question_counts),
    ]
    return [
        (key_list, f"{prefix}-{number}", entry)
        for key_list, prefix, entries in lists
        for number, entry in enumerate(entries, start=1)
    ]


def _seeds(case: CaseSpec) -> list[tuple[str, Seed]]:
    return [(f"D-{number}", seed) for number, seed in enumerate(case.seeds, start=1)]


# --- section 4: twins ------------------------------------------------------------------------


def twin(case: CaseSpec) -> CaseSpec:
    """`<case_id>-twin`: the same design, variant and sets, no seeds and no decoys, and each seed
    as a correct condition in seed order, `C-1` onward, carrying the kind and the seed's places
    and tag, described "clean twin of <case> D-<n>: <the clean form>" (twin rule B, 24A; GN-8).
    The case's other entries stay with the case."""
    conditions = []
    for seed_id, seed in _seeds(case):
        if seed.kind.clean is None:
            raise CaseSpecError(case.case_id, _no_clean_form(seed_id, seed))
        conditions.append(
            Condition(
                kind=seed.kind,
                at=seed.at,
                tag=seed.tag,
                description=f"clean twin of {case.case_id} {seed_id}: {seed.kind.clean.words}",
            )
        )
    return CaseSpec(
        case_id=f"{case.case_id}-twin",
        design=case.design,
        variant=case.variant,
        conditions=tuple(conditions),
        sets=case.sets,
    )


def _no_clean_form(seed_id: str, seed: Seed) -> str:
    return (
        f"{seed_id} ({seed.kind.name}) is a kind with no clean form, so the case can have no "
        "twin (generator.md 4)"
    )


# --- section 10: the spec checks -------------------------------------------------------------

_CASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def check_specs(specs: Sequence[CaseSpec]) -> None:
    """Rows 1 to 7 and row 8's per-entry halves, over any list of specs: one spec at a time, its
    rows in the table's order, the first failing row ending the run."""
    seen: set[str] = set()
    for case in specs:
        _row_1_case_id(case, seen)
        seen.add(case.case_id)
        _row_2_names(case)
        _row_3_held_out_model_seeds(case)
        _row_4_tags(case)
        _row_5_drawing_documents(case)
        _row_6_forms(case)
        _row_7_held_out_outside_committed(case)
        _row_8_represents(case)


def check_anchor_coverage(specs: Sequence[CaseSpec]) -> None:
    """Row 8's coverage half: every anchor and analyst-found id is represented by some spec. It
    holds only over the whole set, so only `generate.render_all()` calls it."""
    represented = {value for case in specs for value in case.represents}
    missing = [anchor for anchor in ANCHOR_FAMILY if anchor not in represented]
    if missing:
        raise CaseSpecError(
            specs[0].case_id if specs else "(none)",
            f"no case represents {', '.join(missing)}: every anchor and analyst-found defect is "
            "represented by some case (FR-029)",
        )


def _row_1_case_id(case: CaseSpec, seen: set[str]) -> None:
    case_id = case.case_id
    if case_id in seen:
        raise CaseSpecError(case_id, f"case id {case_id} is named twice (cases.md 2)")
    words_known = all(word.isdigit() or word in CASE_VOCABULARY for word in case_id.split("-"))
    if _CASE_ID.fullmatch(case_id) is None or not words_known:
        raise CaseSpecError(
            case_id,
            f"case id {case_id!r} is not lower-case words of the case vocabulary and numbers "
            "joined by hyphens (cases.md 2)",
        )
    if case_id.endswith("-twin"):
        raise CaseSpecError(
            case_id,
            f"case id {case_id} names a twin, which is derived from its case, never written "
            "(generator.md 4)",
        )


def _row_2_names(case: CaseSpec) -> None:
    design = case.design

    def refuse(detail: str) -> None:
        raise CaseSpecError(case.case_id, detail)

    def named(where: str, place: str, kinds: tuple[PlaceKind, ...] | None) -> None:
        actual = design.kind_of(place)
        if actual is None:
            refuse(f"{where} names {place}, which design {design.name} does not define")
        if kinds is not None and actual not in kinds:
            refuse(
                f"{where} names {place}, a {actual} place, where a {' or '.join(kinds)} place "
                "is named"
            )

    def placed(where: str, kind: SeedKind, at: At) -> None:
        for role in kind.roles:
            if role not in at:
                refuse(f"{where} names no place for role {role}")
        for role, place in at.items():
            expected = kind.roles.get(role) or kind.optional_roles.get(role)
            if expected is None:
                refuse(f"{where} names role {role}, which {kind.name} does not have")
            named(where, place, (expected,))

    def called(where: str, value: Any) -> None:
        for place in _place_names(value):
            named(where, place.name, None)

    if case.variant is not None and case.variant not in design.variants:
        refuse(
            f"variant {case.variant} is not one design {design.name} defines "
            f"({', '.join(design.variants) or 'none'})"
        )
    for seed_id, seed in _seeds(case):
        placed(f"{seed_id} ({seed.kind.name})", seed.kind, seed.at)
    for _, entry_id, entry in key_only_entries(case):
        if isinstance(entry, Condition):
            if entry.kind is not None:
                placed(f"{entry_id} ({entry.kind.name})", entry.kind, entry.at)
            for place in entry.component_ids:
                named(entry_id, place, ("component",))
            for place in entry.document_ids:
                named(entry_id, place, ("document",))
            called(entry_id, entry.references)
            if entry.correct_call is not None:
                called(entry_id, entry.correct_call.arguments)
        elif isinstance(entry, Forbidden):
            for place in entry.component_ids:
                named(entry_id, place, ("component",))
            for place in entry.document_ids:
                named(entry_id, place, ("document",))
        elif isinstance(entry, Unanswerable):
            for place in entry.documents:
                named(entry_id, place, ("document",))
        elif isinstance(entry, QuestionCount):
            for place in entry.ids:
                named(entry_id, place, ("component", "document"))
    for number, answer in enumerate(case.answers, start=1):
        for place in answer.ids:
            named(f"A-{number}", place, ("component", "document"))
    for number, decoy in enumerate(case.decoys, start=1):
        called(f"decoy {number}", decoy.arguments)


def _place_names(value: Any) -> Iterator[PlaceName]:
    """Every `PlaceName` inside `value`, at any depth."""
    if isinstance(value, PlaceName):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _place_names(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _place_names(item)


def _listed(ids: Sequence[str]) -> str:
    """`D-1`, `D-1 and D-2`, `D-1, D-2 and D-3`."""
    return ids[0] if len(ids) == 1 else f"{', '.join(ids[:-1])} and {ids[-1]}"


def _row_3_held_out_model_seeds(case: CaseSpec) -> None:
    held = [
        (seed_id, seed)
        for seed_id, seed in _seeds(case)
        if isinstance(seed.tag, HeldOut) and seed.kind.producer == "model"
    ]
    if len(held) > 2:
        raise CaseSpecError(
            case.case_id,
            f"{_listed([seed_id for seed_id, _ in held])} are held-out model-produced seeds; a "
            "case holds at most two (FR-028)",
        )
    if len(held) == 2 and held[0][1].kind.family == held[1][1].kind.family:
        raise CaseSpecError(
            case.case_id,
            f"{_listed([seed_id for seed_id, _ in held])} are held-out model-produced seeds of "
            f"one judgement family, {held[0][1].kind.family}; a case's two are of two (FR-028)",
        )


def _tagged(case: CaseSpec) -> list[tuple[str, Tag, str | None]]:
    """Every tagged item, seeds first, as (where, tag, represents)."""
    items: list[tuple[str, Tag, str | None]] = [
        (f"{seed_id} ({seed.kind.name})", seed.tag, seed.represents)
        for seed_id, seed in _seeds(case)
    ]
    items.extend(
        (entry_id, entry.tag, entry.represents) for _, entry_id, entry in key_only_entries(case)
    )
    return items


def _row_4_tags(case: CaseSpec) -> None:
    for where, tag, _ in _tagged(case):
        if isinstance(tag, HeldOut) and tag.stamp != stamps.CURRENT:
            raise CaseSpecError(
                case.case_id,
                f"{where} is held out against a stamp that is not stamps.CURRENT (cases.md 5)",
            )
        if isinstance(tag, TunedOn) and not tag.reason.strip():
            raise CaseSpecError(case.case_id, f"{where} is tuned on with no reason (FR-031)")


def _row_5_drawing_documents(case: CaseSpec) -> None:
    """A drawing seed's drawing document carries no other seed's and no condition's reference,
    and a case holds one drawing seed (`cases.md` 6.2; CS-8). Not held for a pilot-only case
    whose every item is tuned on (RF-12)."""
    every_tuned_on = all(isinstance(tag, TunedOn) for _, tag, _ in _tagged(case))
    if case.sets == ("pilot",) and every_tuned_on:
        return
    drawings = [(seed_id, seed) for seed_id, seed in _seeds(case) if seed.kind.family == "drawing"]
    if len(drawings) > 1:
        raise CaseSpecError(
            case.case_id,
            f"{_listed([seed_id for seed_id, _ in drawings])}: a second drawing seed; a case "
            "holds one (cases.md 6.2)",
        )
    if not drawings:
        return
    [(drawing_id, drawing)] = drawings
    places = case.design.places
    try:
        keyed = set(drawing.kind.documents(drawing.at, places))
        others: list[tuple[str, set[str]]] = [
            (seed_id, _seed_documents(seed, places))
            for seed_id, seed in _seeds(case)
            if seed_id != drawing_id
        ]
        others.extend(
            (entry_id, _condition_documents(entry, places))
            for _, entry_id, entry in key_only_entries(case)
            if isinstance(entry, Condition)
        )
    except ValueError as error:
        # A kind that cannot read the design's records (a fact it needs is missing) refuses
        # naming the case, as `render._laid` does.
        if isinstance(error, CaseSpecError):
            raise
        raise CaseSpecError(case.case_id, str(error)) from None
    for other_id, documents in others:
        shared = sorted(keyed & documents)
        if shared:
            raise CaseSpecError(
                case.case_id,
                f"{drawing_id} ({drawing.kind.name}), a drawing seed, is keyed to {shared[0]}, "
                f"which also carries {other_id}'s reference: a drawing seed's document carries no "
                "other seed and no condition (cases.md 6.2)",
            )


def _drawings_of(value: Any, places: Places) -> set[str]:
    """The drawing places of the dimension places `value` names as `PlaceName`s."""
    found = set()
    for place in _place_names(value):
        record = places.get(place.name)
        if isinstance(record, DimensionPlace):
            found.add(record.drawing)
    return found


def _seed_documents(seed: Seed, places: Places) -> set[str]:
    """The documents a seed reaches: its kind's documents, and the drawings of every dimension it
    names, as a role or in a reference."""
    dimensions = [PlaceName(place) for place in seed.at.values()]
    return (
        set(seed.kind.documents(seed.at, places))
        | _drawings_of(dimensions, places)
        | _drawings_of(list(seed.kind.references(seed.at, places)), places)
    )


def _condition_documents(condition: Condition, places: Places) -> set[str]:
    if condition.kind is not None:
        return _seed_documents(Seed(condition.kind, condition.at, condition.tag), places)
    return set(condition.document_ids) | _drawings_of(list(condition.references), places)


def _row_6_forms(case: CaseSpec) -> None:
    for seed_id, seed in _seeds(case):
        if seed.kind.plant is None:
            raise CaseSpecError(
                case.case_id,
                f"{seed_id} ({seed.kind.name}) is a kind with no planted form: key its clean "
                "form as a correct condition",
            )
        if case.twin and seed.kind.clean is None:
            raise CaseSpecError(case.case_id, _no_clean_form(seed_id, seed))
    for _, entry_id, entry in key_only_entries(case):
        if isinstance(entry, Condition) and entry.kind is not None and entry.kind.clean is None:
            raise CaseSpecError(
                case.case_id,
                f"{entry_id} ({entry.kind.name}) is a kind with no clean form, which no condition "
                "can take",
            )


def _row_7_held_out_outside_committed(case: CaseSpec) -> None:
    if "committed" in case.sets:
        return
    for where, tag, _ in _tagged(case):
        if isinstance(tag, HeldOut):
            raise CaseSpecError(
                case.case_id,
                f"{where} is held out in a case outside the committed set; only committed cases "
                "hold items out (US5-4)",
            )


def _row_8_represents(case: CaseSpec) -> None:
    """Row 8's per-entry halves (RF-80): each `represents` value an anchor R-1 to R-8 or an
    analyst-found defect AF-1 to AF-3, the case's each once; an item representing an anchor is
    tuned-on (15A)."""
    seen: set[str] = set()
    for value in case.represents:
        _anchor_id(case, "the case", value)
        if value in seen:
            raise CaseSpecError(case.case_id, f"the case represents {value} twice")
        seen.add(value)
    for where, tag, value in _tagged(case):
        if value is None:
            continue
        _anchor_id(case, where, value)
        if value.startswith("R-") and not isinstance(tag, TunedOn):
            raise CaseSpecError(
                case.case_id,
                f"{where} represents the anchor {value} but is not tuned-on; anchors are tuned-on "
                "(15A; RF-80)",
            )


def _anchor_id(case: CaseSpec, where: str, value: str) -> None:
    if value not in ANCHOR_FAMILY:
        raise CaseSpecError(
            case.case_id,
            f"{where} represents {value}, which is neither an anchor R-1 to R-8 nor an "
            "analyst-found defect AF-1 to AF-3 (FR-029)",
        )


# --- the custom part's feature tree -----------------------------------------------------------

UNDER_DEFINED = 2
"""`swConstrainedStatus_e`'s under-defined raw value, as `checks/rms_types.yaml` maps it; a
fully defined sketch is `features.SketchSpec`'s default, 3."""

LOOSE_FEATURES = 20
"""How many content features an ungrouped tree carries outside every group folder: about the 22
of R-7's recorded plate (research §3 R-7)."""


def tree_specs(tree: Tree) -> tuple[tuple[FeatureSpec, ...], tuple[EquationSpec, ...]]:
    """A custom part's feature rows and equations, for `features.part_trees` (`generator.md` 5.1
    and 5.3): the six Resilient Modeling groups in the method's order (`checks/rms_types.yaml`),
    every content feature described, every sketch fully defined, consumed once and read with no
    sketch text (so `standards.part.sketches_fully_defined` decides it rather than leaving it
    unresolved), a global variable driving a dimension, unless `tree` says otherwise. The names
    are vocabulary words and numbers, the global variable's too; the group folders carry the
    method's own names, which RMS matches exactly and whose words the vocabulary holds
    (`RMS_GROUP_WORDS`, owner decision 54A).

    The dump lists an absorbed sketch twice (`tests/support/remodel.py` `absorbed_twice`); this
    tree lists the Core sketch once, so R-7's two families still each name it once."""
    status = 3 if tree.sketches_defined else UNDER_DEFINED
    loose = (
        ()
        if tree.grouped
        else tuple(
            feature(f"Block-{number}", "Extrusion") for number in range(100, 100 + LOOSE_FEATURES)
        )
    )
    # Groups are sticky (`checks/rms/groups.py`): a feature after a group folder is in that group,
    # so the loose features come before the first one, where no group is open.
    features = (
        *loose,
        folder("1-Ref", feature("Datum-1", "RefAxis")),
        folder(
            "2-Construction",
            sketch_feature("Block-1", consumers=("Block-2",), text_segments=0),
            feature("Block-2", "SurfaceExtrude", parent_names=("Block-1",)),
        ),
        folder(
            "3-Core",
            sketch_feature("Block-3", raw_status=status, consumers=("Block-4",), text_segments=0),
            feature("Block-4", "Extrusion", parent_names=("Block-3",)),
        ),
        folder(
            "4-Detail",
            sketch_feature("Block-5", consumers=("Block-6",), text_segments=0),
            feature("Block-6", "Cut", parent_names=("Block-5",)),
            feature("Block-7", "HoleWzd"),
        ),
        folder("5-Modify", feature("Block-8", "Draft"), feature("Block-9", "LPattern")),
        folder(
            "6-Quarantine",
            feature("Block-10", "Chamfer"),
            fillet_feature("Block-11", radius_m=0.003),
        ),
    )
    if tree.global_variable:
        equations = (
            equation('"Size" = 40mm', is_global=True, value=0.04),
            equation('"D1@Block-3" = "Size"', value=0.04),
        )
    else:
        # A dimension is still driven, so only the global-variable rule fails.
        equations = (equation('"D1@Block-3" = 40mm', value=0.04),)
    return features, equations
