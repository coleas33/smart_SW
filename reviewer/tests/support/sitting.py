"""The sitting-shaped fixture: a small assembly like the one the 2026-09-26 sitting reviewed
(feature 013 T012).

Every string here is fictional and built from `VOCABULARY`; nothing comes from a recorded
package, a run folder or a real profile. What it reproduces is the **shape** the sitting
showed - the part-role signals a custom part, a vendor part and an undecided part carry, the
same-name drawing shared by an assembly and its part, the manifest's unknown vault facts and
the eight questions the model asked - in fictional profile A's names
(`tests/fixtures/standards/profile-a.yaml`), so a test classifies it with that profile.

`tests/fixtures/sitting/generate_fixture.py` writes `render()`'s bytes and
`test_sitting_fixture_is_fictional.py` holds them to the vocabulary and to regeneration.

The documents, and the role profile A gives each (`specs/013-engineer-first-review/contracts/
part-roles.md` section 2):

- `doc:1`, the assembly `MR-10420.SLDASM`, the root: the custom prefix, the switch's custom
  value, sparse properties and a same-name drawing - custom;
- `doc:2`, the custom plate `MR-10420.SLDPRT`, the same stem: the same signals - custom;
- `doc:3`, the vendor pin, two instances, in a bought-parts folder: the folder, the switch's
  bought value, a catalogue number and a bought part-number range, with sparse properties
  against them - bought;
- `doc:4`, a spacer no rule decides: only the switch's custom value (a detail property makes
  it not sparse) - unclear;
- `doc:5`, a vendor sub-assembly: a vendor property and a catalogue number in its property,
  with the switch's custom value against them - bought;
- `doc:6`, the sub-assembly's one child, lightweight and never read: nothing of its own -
  bought, inherited.

The pin's part-number property is spelled without its space, as real files spell it: only
a reader that compares names ignoring spaces finds it. The plate, the pin and the spacer each
carry one under-defined sketch, so each draws a modelling-practice finding before part roles
exist; the pin's two instances make its finding the family's representative until it is
bought (research R2.8).
"""

from __future__ import annotations

import json
import re
from typing import Any

from swreview.ir.models import DrawingCandidate, EvidencePackage
from tests.support.features import (
    AssemblySpec,
    InstanceSpec,
    MateSpec,
    PartSpec,
    SubassemblySpec,
    feature,
    rms_package,
    sketch_feature,
)
from tests.support.mechanical import FICTIONAL_ROOT
from tests.support.mechanical import fictional_offences as mechanical_offences

__all__ = [
    "DOCUMENTS",
    "DRAWING_PATH",
    "FICTIONAL_ROOT",
    "QUESTIONS",
    "VOCABULARY",
    "fictional_offences",
    "render",
    "sitting_package",
]

VOCABULARY: frozenset[str] = frozenset(
    {
        # profile A's fictional property names and values
        "meridian",
        "part",
        "ref",
        "summary",
        "rev",
        "sourcing",
        "fabricated",
        "procured",
        "supplied",
        "supplier",
        "thread",
        "note",
        "mr",
        "mx",
        # invented syllables and plain words the names are made of
        "fict",
        "fictional",
        "kalo",
        "tessa",
        "okta",
        "ven",
        "works",
        "frame",
        "plate",
        "dowel",
        "pin",
        "spacer",
        "drive",
        "shaft",
        "arvo",
        "vault",
        "sketch",
        "boss",
        "extrude",
        "default",
        "sldprt",
        "sldasm",
        "slddrw",
        "intent",
        # the words of the eight questions, their answers and the checklist ids they block
        "is",
        "the",
        "a",
        "for",
        "of",
        "in",
        "it",
        "to",
        "this",
        "latest",
        "version",
        "what",
        "fit",
        "does",
        "take",
        "there",
        "drawing",
        "no",
        "released",
        "slip",
        "press",
        "bought",
        "revision",
        "record",
        "check",
        "decide",
        "second",
        "instance",
        "assembly",
        "provenance",
        "interfaces",
        "manufacturing",
        "inputs",
        "hygiene",
        # the id prefixes the IR and the session allocate
        "doc",
        "cmp",
        "er",
        # the words the dump's gap reasons are written in
        "component",
        "lightweight",
        "feature",
        "tree",
        "not",
        "read",
        "open",
        "solidworks",
        "so",
        "its",
        "properties",
        "material",
        "and",
        "mass",
        "were",
    }
)
"""Every word a string of this fixture may contain (`fictional_offences` reads it)."""

_LETTER_RUN = re.compile(r"[A-Za-z]+")


def fictional_offences(text: str) -> list[str]:
    """The letter runs of `text` that are not built from `VOCABULARY`.

    Letter runs rather than `mechanical.fictional_offences`' letter-and-digit tokens, because a
    feature name (`Sketch1`) and a catalogue-shaped part name (`MX204-18P`) run letters and
    digits together: every letter run must still be vocabulary, and a digit identifies nothing.
    Each run is judged by the mechanical helper itself, so the compound rule is the same one.
    """
    return [
        offence
        for run in _LETTER_RUN.findall(text)
        for offence in mechanical_offences(run, VOCABULARY)
    ]


JOB = f"{FICTIONAL_ROOT}Vault\\arvo\\kalo\\"
BOUGHT_FOLDER = f"{JOB}Meridian Supplied\\"
"""A folder profile A's `part_roles.bought_folder_names` names, inside a project folder."""
SUB_FOLDER = f"{JOB}okta\\"

PART_NUMBER = "Meridian Part Ref"
SUMMARY = "Meridian Summary"
REVISION = "MeridianRev"
SWITCH = "Meridian Sourcing"
BUILT, BOUGHT = "Fabricated", "Procured"
SUPPLIER, SUPPLIER_REF = "Meridian Supplier", "Meridian Supplier Ref"
THREAD_NOTE = "Meridian Thread Note"

STEM = "MR-10420"
PIN = "MX204-18P"
SPACER = "tessa-spacer"
DRIVE = "ven-okta-drive"
SHAFT = "ven-okta-shaft"

DOCUMENTS: dict[str, str] = {
    "assembly": "doc:1",
    "plate": "doc:2",
    "pin": "doc:3",
    "spacer": "doc:4",
    "drive": "doc:5",
    "shaft": "doc:6",
}
"""Each document's id, by role in the table above."""

DRAWING_PATH = f"{JOB}{STEM}.SLDDRW"
"""The one same-name drawing beside both stem documents: one file, two documents."""


def _under_defined(prefix: str) -> list[Any]:
    """One sketch the solver reports under-defined, and the boss that consumes it."""
    sketch, boss = f"{prefix} Sketch1", f"{prefix} Boss-Extrude1"
    return [
        sketch_feature(sketch, raw_status=2, consumers=(boss,)),
        feature(boss, "Extrusion", parent_names=(sketch,)),
    ]


def _base() -> EvidencePackage:
    """Documents, instances, features and mates, laid out by `rms_package`."""
    return rms_package(
        assembly=AssemblySpec(
            document_id=DOCUMENTS["assembly"],
            name=STEM,
            mates=(
                # The sitting's shape: the plate's plane mated to the pin's face.
                MateSpec(entities=(("plate-1", "swSelDATUMPLANES"), ("pin-1", "swSelFACES"))),
                # A face-to-face mate between two graded parts, which stays a finding.
                MateSpec(entities=(("plate-1", "swSelFACES"), ("spacer-1", "swSelFACES"))),
            ),
            subassembly=SubassemblySpec(
                document_id=DOCUMENTS["drive"], name=DRIVE, instance=InstanceSpec("drive-1")
            ),
        ),
        parts=(
            PartSpec(
                document_id=DOCUMENTS["plate"],
                name=STEM,
                features=_under_defined("plate"),
                instances=[InstanceSpec("plate-1", is_fixed=True)],
            ),
            PartSpec(
                document_id=DOCUMENTS["pin"],
                name=PIN,
                features=_under_defined("pin"),
                instances=[InstanceSpec("pin-1"), InstanceSpec("pin-2")],
            ),
            PartSpec(
                document_id=DOCUMENTS["spacer"],
                name=SPACER,
                features=_under_defined("spacer"),
                instances=[InstanceSpec("spacer-1")],
            ),
            PartSpec(
                document_id=DOCUMENTS["shaft"],
                name=SHAFT,
                instances=[
                    InstanceSpec("shaft-1", suppression="lightweight", parent_name="drive-1")
                ],
            ),
        ),
    )


def _properties() -> dict[str, tuple[str, dict[str, str], dict[str, dict[str, str]]]]:
    """Each document's folder, document-level properties and configuration properties."""
    return {
        DOCUMENTS["assembly"]: (
            JOB,
            {PART_NUMBER: STEM, SUMMARY: "kalo frame", REVISION: "A", SWITCH: BUILT},
            {},
        ),
        DOCUMENTS["plate"]: (
            JOB,
            {PART_NUMBER: STEM, SUMMARY: "kalo plate", REVISION: "A", SWITCH: BUILT},
            {},
        ),
        DOCUMENTS["pin"]: (
            BOUGHT_FOLDER,
            # The part-number property spelled without its spaces, a number in a bought
            # range that is not the file name, and the switch set on purpose at both levels.
            {"MeridianPartRef": "MR-80311", SUMMARY: "fict dowel pin", SWITCH: BOUGHT},
            {"Default": {SWITCH: BOUGHT}},
        ),
        DOCUMENTS["spacer"]: (
            JOB,
            {SUMMARY: "tessa spacer", REVISION: "A", SWITCH: BUILT, THREAD_NOTE: ""},
            {},
        ),
        DOCUMENTS["drive"]: (
            JOB,
            {
                SUPPLIER: "fict okta works",
                SUPPLIER_REF: "MX310-22D",
                SUMMARY: "okta drive",
                SWITCH: BUILT,
            },
            {},
        ),
        # Never read: the builder's lightweight child has no properties at all.
        DOCUMENTS["shaft"]: (SUB_FOLDER, {}, {}),
    }


def sitting_package() -> EvidencePackage:
    """The sitting-shaped package, validated."""
    base = _base()
    placed = _properties()
    documents = []
    for document in base.documents:
        folder, custom, per_configuration = placed[document.document_id]
        documents.append(
            document.model_copy(
                update={
                    "path": f"{folder}{document.file_name}",
                    "custom_properties": custom,
                    "config_properties": per_configuration,
                }
            )
        )
    entries = [
        entry.model_copy(
            update={
                "vault_path": next(
                    item.path for item in documents if item.document_id == entry.document_id
                ),
                "vault_version": None,
                "local_modified": None,
            }
        )
        for entry in base.manifest.entries
    ]
    shaft = DOCUMENTS["shaft"]
    gaps = [
        *base.gaps,
        {
            "kind": "not_extracted",
            "entity_kind": "document",
            "entity_id": shaft,
            "reason": (
                f"'{SHAFT}.SLDPRT' is not open in SOLIDWORKS, so its properties, material "
                "and mass were not read."
            ),
            "error": None,
        },
    ]
    data = base.model_dump(mode="json")
    data.update(
        {
            "design": {**data["design"], "design_id": "dsn:kalo", "name": STEM},
            "manifest": {
                "entries": [entry.model_dump(mode="json") for entry in entries],
                "discrepancies": [],
            },
            "documents": [document.model_dump(mode="json") for document in documents],
            "drawing_candidates": [
                DrawingCandidate(
                    document_id=document_id, path=DRAWING_PATH, reason="same_name_beside_model"
                ).model_dump(mode="json")
                for document_id in (DOCUMENTS["assembly"], DOCUMENTS["plate"])
            ],
            "gaps": [gap if isinstance(gap, dict) else gap.model_dump(mode="json") for gap in gaps],
        }
    )
    return EvidencePackage.model_validate_json(json.dumps(data))


def _question(
    what: str, why: str, entity_ids: list[str], question: str, blocks: str
) -> dict[str, Any]:
    return {
        "what": what,
        "why": why,
        "entity_ids": entity_ids,
        "question": question,
        "blocks": blocks,
    }


PIN_1, PIN_2 = "cmp:0003", "cmp:0004"
PLATE_1, SPACER_1 = "cmp:0002", "cmp:0005"

QUESTIONS: dict[str, Any] = {
    "first_turn": [
        _question(
            "the fit of the pin in the plate",
            "to decide the fit check for the pin",
            [PIN_1, PLATE_1],
            "What fit does the pin take in the plate?",
            "interfaces.fit",
        ),
        _question(
            "the revision of the assembly",
            "to record the provenance check",
            [DOCUMENTS["assembly"]],
            "Is this the latest version of the assembly?",
            "provenance",
        ),
        _question(
            "a drawing for the pin",
            "to check the drawing of the pin",
            [DOCUMENTS["pin"]],
            "Is there a drawing for the pin?",
            "drawing.manufacturing_inputs",
        ),
        _question(
            "the revision of the spacer",
            "to record the revision check",
            [DOCUMENTS["spacer"]],
            "Is the spacer released?",
            "hygiene",
        ),
        _question(
            "the fit of the second pin instance in the spacer",
            "to decide the fit check for the second instance",
            [PIN_2, SPACER_1],
            "What fit does the second pin instance take?",
            "interfaces.fit",
        ),
    ],
    "answers": {
        "ER-001": "slip fit",
        "ER-002": "latest version",
        "ER-003": "no drawing, it is bought",
        "ER-004": "released",
        "ER-005": "press fit",
    },
    "second_turn": [
        {"repeats": "ER-002"},
        {"repeats": "ER-003"},
        {"repeats": "ER-005"},
    ],
}
"""The sitting's eight `request_evidence` calls, with fictional ids: `first_turn`'s five are
ER-001 to ER-005, the engineer answers them, and `second_turn`'s three repeat the arguments of
the request each names word for word - ER-006 to ER-008 today, and `already_answered` citing
ER-002, ER-003 and ER-005 once feature 013's re-ask guard lands (T063 replays them)."""


def _second_turn() -> list[dict[str, Any]]:
    first = QUESTIONS["first_turn"]
    return [
        {"repeats": call["repeats"], "arguments": first[int(call["repeats"][3:]) - 1]}
        for call in QUESTIONS["second_turn"]
    ]


def render() -> dict[str, bytes]:
    """`{relative path: bytes}` of `tests/fixtures/sitting/small-assembly/`."""
    package = sitting_package()
    questions = {
        "first_turn": [{"arguments": call} for call in QUESTIONS["first_turn"]],
        "answers": QUESTIONS["answers"],
        "second_turn": _second_turn(),
    }
    return {
        "package.json": (package.model_dump_json(indent=2) + "\n").encode("utf-8"),
        "questions.json": (json.dumps(questions, indent=2) + "\n").encode("utf-8"),
    }
