"""Custom, bought or unclear: the classifier (feature 013 T017).

`specs/013-engineer-first-review/contracts/part-roles.md` sections 1 to 4 and 9 are normative.
Every package here is fictional: the sitting-shaped fixture (T012) and small table-driven
packages built below, classified against fictional profile A (version 4) or copies of it with
one field changed. Profile A's values are read from the fixture file rather than typed out, so
no test here writes a profile value the reasons must not quote.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from swreview.checks.part_roles import (
    BOUGHT_REFUSAL,
    NO_CONVENTION_RULE,
    NO_SIGNAL,
    OPTION_ALL,
    OPTION_NONE,
    QUESTION,
    ROOT_LABEL,
    SIGNALS,
    STATE_NO_CONVENTION,
    STATE_NO_PROFILE,
    WHY,
    PartRoles,
    Vote,
    _decide,
    answered_roles,
    bought_parts_sentence,
    classify_parts,
    guard_sentence,
    maybe_bought_sentence,
    note_unclear,
    roles_question,
    unmatched_sentence,
)
from swreview.checks.result import CheckResult
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.ir.loader import load_package
from swreview.ir.models import (
    ComponentInstance,
    Design,
    Document,
    DrawingCandidate,
    EvidencePackage,
    Gap,
    Manifest,
)
from swreview.report.session import EvidenceRequest
from tests.support.packages import IDENTITY_TRANSFORM, build_package, persist_ref

TESTS = Path(__file__).resolve().parents[1]
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"
SITTING = TESTS / "fixtures" / "sitting" / "small-assembly"

JOB = "C:\\Fictional\\Vault\\arvo\\"
"""A plain project folder: no prefix and no folder name of profile A covers it."""


# --- profiles ---------------------------------------------------------------------------------


def raw_a() -> dict[str, Any]:
    data = yaml.safe_load(PROFILE_A.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


A = raw_a()
ROLES = A["part_roles"]
PATTERN = A["part_number"]["pattern"]
PART_NUMBER = A["hygiene"]["part_number_property"]
SWITCH = ROLES["switch"]["property"]
BOUGHT_VALUE = ROLES["switch"]["bought_values"][0]
CUSTOM_VALUE = ROLES["switch"]["custom_values"][0]
VENDOR = ROLES["vendor_properties"][0]
BLOCK = ROLES["distributor_block"]["properties"]
CATALOGUE_PROPERTY = ROLES["catalogue_numbers"]["properties"][0]
DETAIL = ROLES["detail_properties"][0]
FOLDER_NAME = ROLES["bought_folder_names"][0]
CUSTOM_PREFIX = ROLES["custom_prefixes"][0]
BOUGHT_PREFIX = ROLES["bought_number_prefixes"][0]
BOUGHT_FOLDER = f"{A['vault_root']}/{ROLES['bought_prefixes'][0]}"

CUSTOM_NAME = f"{CUSTOM_PREFIX}0042.SLDPRT"
"""A file name that follows profile A's convention with its custom prefix."""
BOUGHT_NAME = f"{BOUGHT_PREFIX}0042.SLDPRT"
"""A file name that follows the convention in a bought number range."""
CATALOGUE_TOKEN = "MX204-18P"
"""A token profile A's catalogue shape spells."""

assert PATTERN and CUSTOM_NAME.startswith(CUSTOM_PREFIX), "profile A must carry its convention"


def profile_a() -> StandardsProfile:
    return load_profile(PROFILE_A)


def profile_with(**part_roles: Any) -> StandardsProfile:
    """Profile A with `part_roles` fields replaced (a nested key written `switch__property`)."""
    data = raw_a()
    for name, value in part_roles.items():
        target = data["part_roles"]
        *heads, leaf = name.split("__")
        for head in heads:
            target = target[head]
        target[leaf] = value
    return StandardsProfile.model_validate(data)


def version_3(pattern: str | None = None) -> StandardsProfile:
    data = {key: value for key, value in raw_a().items() if key != "part_roles"}
    data["version"] = 3
    if pattern is not None:
        data["part_number"] = {"pattern": pattern}
    return StandardsProfile.model_validate(data)


# --- packages ---------------------------------------------------------------------------------


def document(
    document_id: str,
    file_name: str,
    *,
    kind: str = "part",
    folder: str = JOB,
    path: str | None = None,
    properties: dict[str, str] | None = None,
    per_configuration: dict[str, dict[str, str]] | None = None,
    configurations: Sequence[str] = ("Default",),
) -> Document:
    return Document(
        document_id=document_id,
        kind=kind,  # type: ignore[arg-type]
        file_name=file_name,
        path=f"{folder}{file_name}" if path is None else path,
        configurations=list(configurations),
        active_configuration=configurations[0] if configurations else "",
        custom_properties=dict(properties or {}),
        config_properties=dict(per_configuration or {}),
        material=None,
        mass=None,
    )


def instance(
    component_id: str,
    document_id: str,
    *,
    parent_id: str | None = "cmp:0001",
    configuration: str = "Default",
    toolbox: bool = False,
) -> ComponentInstance:
    return ComponentInstance(
        id=component_id,
        persist_ref=persist_ref(component_id),
        persist_ref_scope="doc:1",
        name=component_id,
        document_id=document_id,
        parent_id=parent_id,
        referenced_configuration=configuration,
        transform=IDENTITY_TRANSFORM,
        suppression="resolved",
        is_fixed=False,
        pattern_id=None,
        is_toolbox=toolbox,
        full_path=component_id,
    )


ROOT = document("doc:1", "arvo-kalo-frame.SLDASM", kind="assembly")
ROOT_INSTANCE = instance("cmp:0001", "doc:1", parent_id=None)


def package(
    *parts: Document,
    components: Sequence[ComponentInstance] | None = None,
    root: Document = ROOT,
    candidates: Sequence[str] = (),
    unread: Sequence[str] = (),
) -> EvidencePackage:
    """The root assembly, `parts` each instanced once under it unless `components` says
    otherwise, a same-name candidate row for each id in `candidates`, and the not-read gap
    for each id in `unread`."""
    if components is None:
        components = [
            instance(f"cmp:{index:04d}", part.document_id)
            for index, part in enumerate(parts, start=2)
        ]
    return build_package(
        manifest=Manifest(entries=[], discrepancies=[]),
        design=Design(
            design_id="dsn:fict",
            name="arvo",
            root_assembly_document_id=root.document_id,
            active_configuration="Default",
            drawing_document_ids=[],
        ),
        documents=[root, *parts],
        components=[ROOT_INSTANCE, *components],
        holes=[],
        fasteners=[],
        mates=[],
        drawing_candidates=[
            DrawingCandidate(
                document_id=document_id,
                path=f"{JOB}same.SLDDRW",
                reason="same_name_beside_model",
            )
            for document_id in candidates
        ],
        gaps=[
            Gap(
                kind="not_extracted",
                entity_kind="document",
                entity_id=document_id,
                reason="'fict.SLDPRT' is not open in SOLIDWORKS, so its properties were not read.",
                error=None,
            )
            for document_id in unread
        ],
    )


def role_of(subject: EvidencePackage, document_id: str = "doc:2", profile: Any = None) -> Any:
    roles = classify_parts(subject, profile_a() if profile is None else profile)
    return roles.by_document[document_id]


def signals(subject: EvidencePackage, document_id: str = "doc:2", profile: Any = None) -> set:
    return {
        (vote.signal, vote.role, vote.strength)
        for vote in role_of(subject, document_id, profile).votes
    }


READ = {"FICT Note": "fict"}
"""A read document's one neutral property, so it is not empty (and it is sparse)."""


# --- 1. each signal (section 2.1) -------------------------------------------------------------


def test_the_signal_table_is_the_contracts() -> None:
    assert [(signal, role, strength) for signal, role, strength, _ in SIGNALS] == [
        ("toolbox", "bought", "strong"),
        ("bought_path", "bought", "strong"),
        ("switch", "bought", "strong"),
        ("switch", "custom", "weak"),
        ("vendor_property", "bought", "strong"),
        ("distributor_block", "bought", "strong"),
        ("catalogue_number", "bought", "medium"),
        ("bought_number", "bought", "medium"),
        ("custom_prefix", "custom", "medium"),
        ("sparse", "custom", "weak"),
        ("same_name_drawing", "custom", "weak"),
    ]
    assert [words for *_, words in SIGNALS] == [
        "a Toolbox part",
        "a bought-parts folder",
        "marked bought by its make-or-buy property",
        "marked made here by its make-or-buy property",
        "a vendor property",
        "a distributor's property block",
        "a catalogue number",
        "a bought part-number range",
        "the company's part-number prefix",
        "few properties",
        "a drawing of the same name beside it",
    ]


def test_toolbox_true_votes_bought_and_false_is_no_evidence() -> None:
    part = document("doc:2", "fict-screw.SLDPRT", properties={DETAIL: ""})
    toolbox = package(part, components=[instance("cmp:0002", "doc:2", toolbox=True)])

    assert signals(toolbox) == {("toolbox", "bought", "strong")}
    assert signals(package(part)) == set()


@pytest.mark.parametrize(
    "path",
    [
        f"{BOUGHT_FOLDER}pin.SLDPRT",
        f"{BOUGHT_FOLDER}deeper/pin.SLDPRT",
        f"{JOB}{FOLDER_NAME}\\pin.SLDPRT",
        f"{JOB}{FOLDER_NAME.upper()}\\sub\\pin.SLDPRT",
    ],
    ids=["prefix", "under-prefix", "folder-name", "folder-name-any-case-any-depth"],
)
def test_a_bought_folder_votes_bought(path: str) -> None:
    part = document("doc:2", "pin.SLDPRT", path=path, properties={DETAIL: ""})

    assert signals(package(part)) == {("bought_path", "bought", "strong")}


@pytest.mark.parametrize(
    "path",
    [
        f"{JOB}{FOLDER_NAME} old\\pin.SLDPRT",
        f"{JOB}{FOLDER_NAME}.SLDPRT",
        f"{JOB}pin.SLDPRT",
        "",
    ],
    ids=["longer-folder", "file-named-like-the-folder", "plain-folder", "no-path"],
)
def test_no_bought_folder_no_vote(path: str) -> None:
    part = document("doc:2", "pin.SLDPRT", path=path, properties={DETAIL: ""})

    assert ("bought_path", "bought", "strong") not in signals(package(part))


def test_the_switch_bought_value_is_strong_and_its_custom_value_weak() -> None:
    bought = document("doc:2", "a.SLDPRT", properties={SWITCH: BOUGHT_VALUE, DETAIL: ""})
    custom = document("doc:2", "a.SLDPRT", properties={SWITCH: CUSTOM_VALUE, DETAIL: ""})

    assert signals(package(bought)) == {("switch", "bought", "strong")}
    assert signals(package(custom)) == {("switch", "custom", "weak")}


def test_the_switch_is_read_ignoring_case_and_spaces_in_its_name_and_value() -> None:
    squeezed = "".join(SWITCH.split()).lower()
    part = document("doc:2", "a.SLDPRT", properties={squeezed: f"  {BOUGHT_VALUE.upper()} "})

    assert ("switch", "bought", "strong") in signals(package(part))


def test_a_configurations_switch_value_wins_over_the_documents() -> None:
    part = document(
        "doc:2",
        "a.SLDPRT",
        properties={SWITCH: CUSTOM_VALUE, DETAIL: ""},
        per_configuration={"Default": {SWITCH: BOUGHT_VALUE}},
    )

    assert signals(package(part)) == {("switch", "bought", "strong")}


def test_two_configurations_that_disagree_cast_both_votes() -> None:
    part = document(
        "doc:2",
        "a.SLDPRT",
        properties={DETAIL: ""},
        configurations=("One", "Two"),
        per_configuration={"One": {SWITCH: BOUGHT_VALUE}, "Two": {SWITCH: CUSTOM_VALUE}},
    )
    components = [
        instance("cmp:0002", "doc:2", configuration="One"),
        instance("cmp:0003", "doc:2", configuration="Two"),
    ]

    assert signals(package(part, components=components)) == {
        ("switch", "bought", "strong"),
        ("switch", "custom", "weak"),
    }


@pytest.mark.parametrize("value", ["", "   ", "FICT Other"], ids=["empty", "blank", "unknown"])
def test_a_blank_or_unknown_switch_value_casts_no_vote(value: str) -> None:
    part = document("doc:2", "a.SLDPRT", properties={SWITCH: value, DETAIL: ""})

    assert signals(package(part)) == set()


def test_a_switch_with_no_property_is_off() -> None:
    off = profile_with(switch={"property": "", "bought_values": [], "custom_values": []})
    part = document("doc:2", "a.SLDPRT", properties={SWITCH: BOUGHT_VALUE, DETAIL: ""})

    assert signals(package(part), profile=off) == set()


def test_a_vendor_property_with_a_value_votes_bought_at_either_level() -> None:
    own = document("doc:2", "a.SLDPRT", properties={VENDOR: "fict works"})
    per = document("doc:2", "a.SLDPRT", per_configuration={"Default": {VENDOR: "fict works"}})
    blank = document("doc:2", "a.SLDPRT", properties={VENDOR: "  "})

    assert ("vendor_property", "bought", "strong") in signals(package(own))
    assert ("vendor_property", "bought", "strong") in signals(package(per))
    assert ("vendor_property", "bought", "strong") not in signals(package(blank))


@pytest.mark.parametrize(
    ("valued", "min_valued", "votes"),
    [(3, 3, True), (2, 3, False), (2, 2, True), (1, 2, False), (0, 1, False)],
)
def test_the_distributor_block_votes_at_its_count(
    valued: int, min_valued: int, votes: bool
) -> None:
    properties = {name: ("fict" if index < valued else "") for index, name in enumerate(BLOCK)}
    part = document("doc:2", "a.SLDPRT", properties=properties)
    profile = profile_with(distributor_block={"properties": BLOCK, "min_valued": min_valued})

    cast = ("distributor_block", "bought", "strong") in signals(package(part), profile=profile)

    assert cast is votes


@pytest.mark.parametrize(
    ("file_name", "configurations", "properties", "votes"),
    [
        (f"{CATALOGUE_TOKEN}.SLDPRT", ("Default",), {}, True),
        (f"fict {CATALOGUE_TOKEN}, steel.SLDPRT", ("Default",), {}, True),
        (f"x{CATALOGUE_TOKEN}.SLDPRT", ("Default",), {}, False),
        (f"{CATALOGUE_TOKEN}x.SLDPRT", ("Default",), {}, False),
        ("fict-pin.SLDPRT", (CATALOGUE_TOKEN,), {}, True),
        ("fict-pin.SLDPRT", ("Default",), {CATALOGUE_PROPERTY: CATALOGUE_TOKEN}, True),
        ("fict-pin.SLDPRT", ("Default",), {"FICT Other": CATALOGUE_TOKEN}, False),
        ("fict-pin.SLDPRT", ("Default",), {CATALOGUE_PROPERTY: f"{CATALOGUE_TOKEN} x"}, False),
    ],
    ids=[
        "file-name",
        "a-token-of-the-file-name",
        "part-of-a-token-before",
        "part-of-a-token-after",
        "configuration-name",
        "listed-property-value",
        "unlisted-property",
        "value-is-more-than-the-number",
    ],
)
def test_a_catalogue_number_votes_bought(
    file_name: str, configurations: tuple[str, ...], properties: dict[str, str], votes: bool
) -> None:
    part = document(
        "doc:2", file_name, configurations=configurations, properties={**properties, DETAIL: ""}
    )
    components = [instance("cmp:0002", "doc:2", configuration=configurations[0])]

    cast = ("catalogue_number", "bought", "medium") in signals(package(part, components=components))

    assert cast is votes


def test_a_referenced_configuration_is_a_configuration_name() -> None:
    part = document("doc:2", "fict-pin.SLDPRT", configurations=(), properties={DETAIL: ""})
    components = [instance("cmp:0002", "doc:2", configuration=CATALOGUE_TOKEN)]

    assert ("catalogue_number", "bought", "medium") in signals(package(part, components=components))


@pytest.mark.parametrize(
    ("file_name", "properties", "expected"),
    [
        (CUSTOM_NAME, {}, {("custom_prefix", "custom", "medium")}),
        (BOUGHT_NAME, {}, {("bought_number", "bought", "medium")}),
        (f"{CUSTOM_PREFIX}0042-rev.SLDPRT", {}, set()),
        (
            "fict-plate.SLDPRT",
            {PART_NUMBER: f"{CUSTOM_PREFIX}0042"},
            {("custom_prefix", "custom", "medium")},
        ),
        (
            "fict-pin.SLDPRT",
            {"".join(PART_NUMBER.split()): f"{BOUGHT_PREFIX}0042"},
            {("bought_number", "bought", "medium")},
        ),
        ("fict-pin.SLDPRT", {"FICT Other": f"{BOUGHT_PREFIX}0042"}, set()),
    ],
    ids=[
        "custom-file-name",
        "bought-file-name",
        "file-name-off-the-convention",
        "custom-part-number",
        "bought-part-number-spelled-without-its-space",
        "not-the-part-number-property",
    ],
)
def test_a_numbers_prefix_votes(
    file_name: str, properties: dict[str, str], expected: set[tuple[str, str, str]]
) -> None:
    part = document("doc:2", file_name, properties={**properties, DETAIL: ""})

    assert signals(package(part)) == expected


def test_with_no_convention_every_file_name_is_a_number() -> None:
    data = raw_a()
    data["part_number"] = {"pattern": ""}
    profile = StandardsProfile.model_validate(data)
    part = document("doc:2", f"{CUSTOM_PREFIX}anything.SLDPRT", properties={DETAIL: ""})

    assert signals(package(part), profile=profile) == {("custom_prefix", "custom", "medium")}


def test_sparse_properties_vote_custom_weakly() -> None:
    assert signals(package(document("doc:2", "a.SLDPRT", properties=READ))) == {
        ("sparse", "custom", "weak")
    }


@pytest.mark.parametrize(
    "present", [DETAIL, VENDOR, BLOCK[0], "".join(DETAIL.split()).upper()], ids=repr
)
def test_a_catalogue_key_present_even_blank_is_not_sparse(present: str) -> None:
    part = document("doc:2", "a.SLDPRT", properties={present: ""})

    assert ("sparse", "custom", "weak") not in signals(package(part))


def test_sparse_is_off_when_the_profile_names_no_catalogue_key() -> None:
    off = profile_with(
        vendor_properties=[],
        distributor_block={"properties": [], "min_valued": 0},
        detail_properties=[],
    )

    assert signals(package(document("doc:2", "a.SLDPRT", properties=READ)), profile=off) == set()


def test_a_same_name_drawing_votes_custom_and_its_absence_is_nothing() -> None:
    part = document("doc:2", "a.SLDPRT", properties={DETAIL: ""})

    assert signals(package(part, candidates=["doc:2"])) == {("same_name_drawing", "custom", "weak")}
    assert signals(package(part)) == set()


def test_an_attached_drawing_of_the_same_folder_and_stem_votes_custom() -> None:
    part = document("doc:2", "fict-plate.SLDPRT", properties={DETAIL: ""})
    beside = document(
        "doc:3",
        "FICT-PLATE.SLDDRW",
        kind="drawing",
        path=f"{JOB.lower()}FICT-PLATE.SLDDRW".replace("\\", "/"),
    )
    elsewhere = document("doc:3", "fict-plate.SLDDRW", kind="drawing", folder=f"{JOB}other\\")

    assert ("same_name_drawing", "custom", "weak") in signals(
        package(part, beside, components=[instance("cmp:0002", "doc:2")])
    )
    assert ("same_name_drawing", "custom", "weak") not in signals(
        package(part, elsewhere, components=[instance("cmp:0002", "doc:2")])
    )


# --- 2. an unread document and one with no path (section 2.1) --------------------------------


def test_an_unread_document_is_decided_from_its_path_name_configurations_and_toolbox() -> None:
    part = document(
        "doc:2",
        f"{CATALOGUE_TOKEN}.SLDPRT",
        path=f"{JOB}{FOLDER_NAME}\\{CATALOGUE_TOKEN}.SLDPRT",
        properties={SWITCH: CUSTOM_VALUE, VENDOR: "fict", PART_NUMBER: f"{CUSTOM_PREFIX}1"},
    )

    role = role_of(package(part, unread=["doc:2"]))

    assert {(vote.signal, vote.role) for vote in role.votes} == {
        ("bought_path", "bought"),
        ("catalogue_number", "bought"),
    }
    assert role.properties_read is False
    assert role.role == "bought"
    assert (
        role.reason == "a bought-parts folder and a catalogue number; its properties were not read"
    )


def test_an_unread_document_with_no_evidence_says_both() -> None:
    role = role_of(package(document("doc:2", "fict-shaft.SLDPRT"), unread=["doc:2"]))

    assert (role.role, role.decision) == ("unclear", "no_evidence")
    assert role.reason == f"{NO_SIGNAL}; its properties were not read"


def test_a_document_with_no_path_casts_no_name_vote_and_says_so() -> None:
    part = document("doc:2", CUSTOM_NAME, path="", properties={DETAIL: ""})

    role = role_of(package(part, candidates=["doc:2"]))

    assert role.votes == ()
    assert role.reason == f"{NO_SIGNAL}; no path was recorded"


# --- 3. the decision (section 2.2) ---------------------------------------------------------------


def vote(signal: str, role: str, strength: str) -> Vote:
    return Vote(signal, role, strength)  # type: ignore[arg-type]


FOLDER = vote("bought_path", "bought", "strong")
SWITCH_BOUGHT = vote("switch", "bought", "strong")
SWITCH_CUSTOM = vote("switch", "custom", "weak")
CATALOGUE = vote("catalogue_number", "bought", "medium")
PREFIX = vote("custom_prefix", "custom", "medium")
SPARSE = vote("sparse", "custom", "weak")
DRAWING = vote("same_name_drawing", "custom", "weak")
STRONG_CUSTOM = vote("switch", "custom", "strong")
"""No custom signal is strong today; this synthetic vote exercises the rule that strong votes
which conflict are unclear, which a future strong custom signal would reach."""


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        ((FOLDER, SWITCH_BOUGHT, CATALOGUE), ("bought", "strong")),
        ((FOLDER, SPARSE, SWITCH_CUSTOM), ("bought", "strong")),
        ((FOLDER, PREFIX), ("unclear", "conflict")),
        ((FOLDER, STRONG_CUSTOM), ("unclear", "conflict")),
        ((PREFIX, SPARSE), ("custom", "agreement")),
        ((PREFIX, SWITCH_CUSTOM, SPARSE, DRAWING), ("custom", "agreement")),
        ((SWITCH_CUSTOM, SPARSE), ("unclear", "too_little")),
        ((CATALOGUE,), ("unclear", "too_little")),
        ((PREFIX,), ("unclear", "too_little")),
        ((CATALOGUE, SPARSE), ("unclear", "conflict")),
        ((CATALOGUE, PREFIX, SPARSE), ("unclear", "conflict")),
        ((), ("unclear", "no_evidence")),
    ],
    ids=[
        "strong-agreeing",
        "strong-with-weak-against",
        "strong-with-medium-against",
        "strong-votes-that-conflict",
        "two-agreeing-one-medium",
        "four-agreeing",
        "two-weak",
        "one-medium-bought",
        "one-medium-custom",
        "both-ways-without-strong",
        "medium-both-ways",
        "no-vote",
    ],
)
def test_each_row_of_the_decision(votes: tuple[Vote, ...], expected: tuple[str, str]) -> None:
    role, decision, _ = _decide(votes)

    assert (role, decision) == expected


def test_the_decision_reasons_name_every_side() -> None:
    assert _decide((FOLDER, SPARSE))[2] == "a bought-parts folder; against it: few properties"
    assert _decide((FOLDER, PREFIX))[2] == (
        "the signals disagree: bought - a bought-parts folder; custom - the company's "
        "part-number prefix"
    )
    assert _decide((SWITCH_CUSTOM, SPARSE))[2] == (
        "too little evidence: only marked made here by its make-or-buy property and few properties"
    )
    assert _decide((PREFIX, SPARSE))[2] == "the company's part-number prefix and few properties"
    assert _decide(())[2] == "no signal decides it"


def test_an_answer_decides_over_every_signal() -> None:
    bought = document(
        "doc:2", "a.SLDPRT", path=f"{BOUGHT_FOLDER}a.SLDPRT", properties={VENDOR: "x"}
    )
    custom = document("doc:3", CUSTOM_NAME, properties=READ)
    subject = package(bought, custom)

    roles = classify_parts(subject, profile_a(), {"doc:2": "custom", "doc:3": "bought"})

    assert (roles.by_document["doc:2"].role, roles.by_document["doc:2"].reason) == (
        "custom",
        "you answered it is ours",
    )
    assert (roles.by_document["doc:3"].role, roles.by_document["doc:3"].reason) == (
        "bought",
        "you answered it is bought",
    )
    assert roles.by_document["doc:2"].decision == "answer"


# --- 4. inheritance (section 2.3) ---------------------------------------------------------------


def vendor_tree(child: Document, grandchild: Document | None = None) -> EvidencePackage:
    drive = document("doc:5", "fict-drive.SLDASM", kind="assembly", properties={VENDOR: "fict"})
    parts = [drive, child, *([grandchild] if grandchild else [])]
    components = [
        instance("cmp:0005", "doc:5"),
        instance("cmp:0006", child.document_id, parent_id="cmp:0005"),
    ]
    if grandchild is not None:
        components.append(instance("cmp:0007", grandchild.document_id, parent_id="cmp:0006"))
    return package(*parts, components=components)


def test_a_child_of_a_bought_assembly_inherits_bought() -> None:
    child = document("doc:6", "fict-shaft.SLDPRT", properties={DETAIL: ""})

    role = role_of(vendor_tree(child), "doc:6")

    assert (role.role, role.decision, role.reason) == (
        "bought",
        "inherited",
        "inside a bought assembly",
    )


def test_inheritance_passes_through_every_level() -> None:
    child = document("doc:6", "fict-gear.SLDASM", kind="assembly", properties={DETAIL: ""})
    grandchild = document("doc:7", "fict-tooth.SLDPRT", properties={DETAIL: ""})

    roles = classify_parts(vendor_tree(child, grandchild), profile_a())

    assert roles.by_document["doc:6"].decision == "inherited"
    assert roles.by_document["doc:7"].decision == "inherited"


def test_a_child_whose_own_evidence_says_custom_keeps_it() -> None:
    custom = document("doc:6", CUSTOM_NAME, properties=READ)
    medium_only = document("doc:6", CUSTOM_NAME, properties={DETAIL: ""})

    assert role_of(vendor_tree(custom), "doc:6").role == "custom"
    kept = role_of(vendor_tree(medium_only), "doc:6")
    assert (kept.role, kept.decision) == ("unclear", "too_little")


def test_a_weak_custom_vote_does_not_block_inheritance() -> None:
    child = document("doc:6", "fict-shaft.SLDPRT", properties={SWITCH: CUSTOM_VALUE, DETAIL: ""})

    assert role_of(vendor_tree(child), "doc:6").decision == "inherited"


def test_an_answer_is_never_overridden_by_inheritance() -> None:
    child = document("doc:6", "fict-shaft.SLDPRT", properties={DETAIL: ""})

    roles = classify_parts(vendor_tree(child), profile_a(), {"doc:6": "custom"})

    assert roles.by_document["doc:6"].role == "custom"


def test_a_part_with_one_instance_outside_the_bought_assembly_does_not_inherit() -> None:
    child = document("doc:6", "fict-shaft.SLDPRT", properties={DETAIL: ""})
    subject = vendor_tree(child)
    subject = subject.model_copy(
        update={"components": [*subject.components, instance("cmp:0008", "doc:6")]}
    )

    assert role_of(subject, "doc:6").role == "unclear"


def test_inheritance_is_not_in_force_outside_the_configured_state() -> None:
    child = document("doc:6", "fict-shaft.SLDPRT")
    drive = document("doc:5", "fict-drive.SLDASM", kind="assembly")
    components = [
        instance("cmp:0005", "doc:5", toolbox=True),
        instance("cmp:0006", "doc:6", parent_id="cmp:0005"),
    ]

    roles = classify_parts(package(drive, child, components=components), version_3())

    assert roles.by_document["doc:5"].role == "bought"
    assert roles.by_document["doc:6"].role == "unclear"


# --- 5. the root rule, unknown ids, states and the guard (section 1, 2) ------------------------


def test_the_root_is_graded_with_a_label_when_it_looks_bought() -> None:
    root = document("doc:1", "fict-drive.SLDASM", kind="assembly", properties={VENDOR: "fict"})

    roles = classify_parts(package(root=root), profile_a())
    role = roles.by_document["doc:1"]

    assert (role.role, role.reason, role.graded) == ("bought", "a vendor property", True)
    assert role.label == ROOT_LABEL.format(reason="a vendor property")
    assert role.label == (
        "looks bought (a vendor property); graded because it is the document under review"
    )
    assert roles.bought() == ()


def test_an_unknown_document_id_is_graded() -> None:
    roles = classify_parts(package(), profile_a())

    assert roles.graded("doc:9999") is True


def test_drawings_are_never_classified() -> None:
    drawing = document("doc:3", "fict.SLDDRW", kind="drawing")

    roles = classify_parts(package(drawing, components=[]), profile_a())

    assert "doc:3" not in roles.by_document


def test_the_absent_state_decides_toolbox_only_and_asks_nothing() -> None:
    screw = document("doc:2", "fict-screw.SLDPRT")
    plate = document("doc:3", CUSTOM_NAME)
    components = [instance("cmp:0002", "doc:2", toolbox=True), instance("cmp:0003", "doc:3")]
    subject = package(screw, plate, components=components)

    roles = classify_parts(subject, None)

    assert (roles.state, roles.state_reason) == ("absent", STATE_NO_PROFILE)
    assert roles.by_document["doc:2"].reason == "a Toolbox part"
    assert roles.by_document["doc:3"].role == "unclear"
    assert roles.by_document["doc:3"].reason == STATE_NO_PROFILE
    assert roles.by_document["doc:3"].graded is True
    assert roles_question(roles, subject) is None
    assert roles.asking("ER-001").note_for("doc:3") is None
    assert bought_parts_sentence(roles, subject) == (
        "Bought parts were not told apart: no standards profile is attached; Toolbox parts were "
        "not graded: fict-screw.SLDPRT"
    )


def test_a_refused_profile_says_why() -> None:
    roles = classify_parts(package(), None, profile_refusal="fict.yaml is not a valid profile")

    assert (
        roles.state_reason == "the standards profile was refused (fict.yaml is not a valid profile)"
    )
    assert bought_parts_sentence(roles, package()) == (
        "Bought parts were not told apart: the standards profile was refused (fict.yaml is not a "
        "valid profile)"
    )


def test_a_version_3_profile_with_no_convention_is_absent() -> None:
    roles = classify_parts(package(), version_3(pattern=""))

    assert (roles.state, roles.state_reason) == ("absent", STATE_NO_CONVENTION)


def test_the_convention_only_state_reads_the_answer_toolbox_and_the_convention() -> None:
    plate = document("doc:2", CUSTOM_NAME)
    screw = document("doc:3", "fict-screw.SLDPRT")
    spacer = document("doc:4", "fict-spacer.SLDPRT", path=f"{BOUGHT_FOLDER}fict-spacer.SLDPRT")
    components = [
        instance("cmp:0002", "doc:2"),
        instance("cmp:0003", "doc:3", toolbox=True),
        instance("cmp:0004", "doc:4"),
    ]
    subject = package(plate, screw, spacer, components=components, candidates=["doc:4"])

    roles = classify_parts(subject, version_3())

    assert roles.state == "convention_only"
    assert [(item.role, item.decision) for item in roles.by_document.values()] == [
        ("unclear", "no_evidence"),
        ("custom", "convention"),
        ("bought", "toolbox"),
        ("unclear", "no_evidence"),
    ]
    assert roles.by_document["doc:4"].reason == NO_CONVENTION_RULE
    assert all(item.votes == () for item in roles.by_document.values())
    question = roles_question(roles, subject)
    assert question is not None and "doc:4" in question.entity_ids


def test_the_guard_fires_when_no_rule_decides_anything() -> None:
    subject = package(document("doc:2", "fict-a.SLDPRT", properties={DETAIL: ""}))

    configured = classify_parts(subject, profile_a())
    convention = classify_parts(subject, version_3())

    assert configured.guard_fired and convention.guard_fired
    assert guard_sentence(configured) == (
        "no part-role rule decided any of the 2 documents; check the profile's part_roles section"
    )
    assert guard_sentence(convention) == (
        "the part-number convention matched none of the 2 documents; check part_number.pattern"
    )
    assert roles_question(configured, subject) is None
    assert configured.asking("ER-001").note_for("doc:2") is None


def test_the_guard_does_not_fire_when_one_document_is_decided() -> None:
    subject = package(document("doc:2", CUSTOM_NAME, properties=READ))

    roles = classify_parts(subject, profile_a())

    assert not roles.guard_fired
    assert guard_sentence(roles) is None


# --- 6. the sitting-shaped fixture (T012) ---------------------------------------------------------


def sitting() -> EvidencePackage:
    return load_package(SITTING).package


def test_the_sitting_fixture_takes_the_roles_its_builder_names() -> None:
    roles = classify_parts(sitting(), profile_a())

    assert {key: (item.role, item.decision) for key, item in roles.by_document.items()} == {
        "doc:1": ("custom", "agreement"),
        "doc:5": ("bought", "strong"),
        "doc:2": ("custom", "agreement"),
        "doc:3": ("bought", "strong"),
        "doc:4": ("unclear", "too_little"),
        "doc:6": ("bought", "inherited"),
    }
    assert roles.by_document["doc:3"].reason == (
        "a bought-parts folder, marked bought by its make-or-buy property, a catalogue number and "
        "a bought part-number range; against it: few properties"
    )
    assert roles.by_document["doc:6"].reason == (
        "inside a bought assembly; its properties were not read"
    )
    assert [item.document_id for item in roles.bought()] == ["doc:5", "doc:3", "doc:6"]
    assert [item.document_id for item in roles.unclear()] == ["doc:4"]


def test_the_sitting_question_and_its_lines() -> None:
    subject = sitting()
    roles = classify_parts(subject, profile_a())

    question = roles_question(roles, subject)

    assert question is not None
    assert question.key == "part_roles"
    assert question.question == QUESTION
    assert len(question.question) == 93 <= 140
    assert question.options == (OPTION_ALL, OPTION_NONE) == ("All bought", "None bought")
    assert question.what == "Parts no rule tells apart: tessa-spacer.SLDPRT"
    assert question.why == WHY
    assert question.entity_ids == ("doc:4",)
    assert question.blocks is None
    # Integration of lanes P and S (2026-09-27): section 8's `allow_text` is the spec's own, so
    # the one writer (`tools/session.record_question`) passes it on and nothing re-adds it.
    assert question.allow_text is True
    assert maybe_bought_sentence(roles, subject) is None
    asked = roles.asking("ER-001")
    assert asked.note_for("doc:4") == (
        "may be a bought part: too little evidence: only marked made here by its make-or-buy "
        "property; asked in ER-001"
    )
    assert asked.note_for("doc:2") is None
    assert maybe_bought_sentence(asked, subject) == (
        "tessa-spacer.SLDPRT graded; each finding says it may be bought; asked in ER-001; do not "
        "ask for their drawings"
    )
    assert bought_parts_sentence(roles, subject) == (
        "3 parts not graded for modelling practice or hygiene (bought): ven-okta-drive.SLDASM (a "
        "vendor property and a catalogue number; against it: marked made here by its make-or-buy "
        "property), MX204-18P.SLDPRT (a bought-parts folder, marked bought by its make-or-buy "
        "property, a catalogue number and a bought part-number range; against it: few "
        "properties), ven-okta-shaft.SLDPRT (inside a bought assembly; its properties were not "
        "read)"
    )


def test_no_reason_or_sentence_carries_a_profile_value() -> None:
    subject = sitting()
    roles = classify_parts(subject, profile_a()).asking("ER-001")
    texts = [
        *(item.reason for item in roles.by_document.values()),
        *(item.label or "" for item in roles.by_document.values()),
        bought_parts_sentence(roles, subject) or "",
        maybe_bought_sentence(roles, subject) or "",
        *(roles.note_for(key) or "" for key in roles.by_document),
    ]
    question = roles_question(roles, subject)
    assert question is not None
    texts.extend([question.question, question.why, question.what.split(": ", 1)[0]])

    values = _profile_values(raw_a())
    leaked = [value for value in values for text in texts if value.casefold() in text.casefold()]

    assert leaked == []


def _profile_values(data: Any) -> list[str]:
    if isinstance(data, dict):
        return [item for value in data.values() for item in _profile_values(value)]
    if isinstance(data, list):
        return [item for value in data for item in _profile_values(value)]
    return [data] if isinstance(data, str) and len(data) >= 4 else []


def test_twelve_unclear_parts_are_listed_ten_then_counted() -> None:
    parts = [document(f"doc:{index}", f"fict-{index}.SLDPRT") for index in range(2, 14)]
    subject = package(
        *parts,
        root=document(
            "doc:1", CUSTOM_NAME.replace(".SLDPRT", ".SLDASM"), kind="assembly", properties=READ
        ),
    )

    roles = classify_parts(subject, profile_a())
    question = roles_question(roles, subject)

    assert question is not None
    assert question.what.endswith("fict-11.SLDPRT, and 2 more")
    assert len(question.entity_ids) == 12


# --- 7. answers (section 9) -----------------------------------------------------------------


def answered(reply: str, **changes: Any) -> tuple[EvidenceRequest, Any, EvidencePackage]:
    subject = sitting()
    roles = classify_parts(subject, profile_a())
    spec = roles_question(roles, subject)
    assert spec is not None
    request = EvidenceRequest(
        id="ER-001",
        what=spec.what,
        why=spec.why,
        entity_ids=list(spec.entity_ids),
        status="answered",
        answer=reply,
        answered_at=None,
        question=spec.question,
        options=list(spec.options),
    )
    return request.model_copy(update=changes), spec, subject


def two_unclear() -> tuple[EvidencePackage, Any]:
    spacer = document("doc:2", "fict-spacer.SLDPRT", properties={DETAIL: ""})
    shim = document("doc:3", "fict-shim.SLDPRT", properties={DETAIL: ""})
    root = document(
        "doc:1", CUSTOM_NAME.replace(".SLDPRT", ".SLDASM"), kind="assembly", properties=READ
    )
    subject = package(spacer, shim, root=root)
    spec = roles_question(classify_parts(subject, profile_a()), subject)
    assert spec is not None and spec.entity_ids == ("doc:2", "doc:3")
    return subject, spec


def text_answer(subject: EvidencePackage, spec: Any, text: str) -> Any:
    request = EvidenceRequest(
        id="ER-001",
        what=spec.what,
        why=spec.why,
        entity_ids=list(spec.entity_ids),
        status="answered",
        answer=text,
        answered_at=None,
        question=spec.question,
        options=list(spec.options),
    )
    return answered_roles(request, spec, subject)


def test_all_bought_and_none_bought() -> None:
    request, spec, subject = answered("All bought")
    assert answered_roles(request, spec, subject).answers == {"doc:4": "bought"}

    request, spec, subject = answered("None bought")
    assert answered_roles(request, spec, subject).answers == {"doc:4": "custom"}


@pytest.mark.parametrize(
    ("typed", "role"),
    [
        ("all bought", "bought"),
        ("ALL BOUGHT", "bought"),
        ("All bought.", "bought"),
        ("  All   bought!  ", "bought"),
        ("none bought", "custom"),
        ("None Bought.", "custom"),
    ],
)
def test_an_option_typed_in_the_text_box_reads_as_the_option(typed: str, role: str) -> None:
    """The review of 2026-09-27: "all bought" typed into the text box read as a part name that
    matched nothing, so every listed part was graded as custom - the opposite of what the
    engineer meant, on a question that cannot be answered twice. An option typed in another case,
    with other spacing or a closing full stop or exclamation mark, is that option."""
    request, spec, subject = answered(typed)

    result = answered_roles(request, spec, subject)

    assert result is not None
    assert result.answers == {"doc:4": role}
    assert result.unmatched == ()


def test_an_option_inside_a_longer_answer_is_not_the_option() -> None:
    """Only the whole answer is read as an option: a sentence that contains the words is a list
    of names, and names none here."""
    request, spec, subject = answered("all bought except the spacer")

    result = answered_roles(request, spec, subject)

    assert result.answers == {"doc:4": "custom"}
    assert result.unmatched == ("all bought except the spacer",)


def test_a_typed_list_names_the_bought_ones_by_file_name_or_stem() -> None:
    subject, spec = two_unclear()

    result = text_answer(subject, spec, " FICT-SHIM ;\n")

    assert result.answers == {"doc:2": "custom", "doc:3": "bought"}
    assert result.unmatched == ()
    both = text_answer(subject, spec, "fict-spacer.SLDPRT, fict-shim")
    assert both.answers == {"doc:2": "bought", "doc:3": "bought"}


def test_a_piece_that_names_no_listed_part_is_quoted_and_changes_nothing() -> None:
    subject, spec = two_unclear()

    result = text_answer(subject, spec, "fict-shim, fict-washer, arvo-kalo-frame")

    assert result.answers == {"doc:2": "custom", "doc:3": "bought"}
    assert result.unmatched == ("fict-washer", "arvo-kalo-frame")
    assert unmatched_sentence(result.unmatched) == (
        "'fict-washer' and 'arvo-kalo-frame' name none of the listed parts"
    )
    assert unmatched_sentence(("x",)) == "'x' names none of the listed parts"
    assert unmatched_sentence(()) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"question": "Are these parts bought?"},
        {"options": ["All bought"]},
        {"entity_ids": ["doc:4", "doc:3"]},
        {"status": "open", "answer": None},
    ],
    ids=["other-question", "other-options", "other-ids", "unanswered"],
)
def test_a_look_alike_or_open_request_does_nothing(changes: dict[str, Any]) -> None:
    request, spec, subject = answered("All bought", **changes)

    assert answered_roles(request, spec, subject) is None


def test_no_question_spec_means_no_answer_is_read() -> None:
    request, _, subject = answered("All bought")

    assert answered_roles(request, None, subject) is None


def test_answering_reclassifies_and_drops_the_note() -> None:
    request, spec, subject = answered("All bought")
    answer = answered_roles(request, spec, subject)
    assert answer is not None

    roles = classify_parts(subject, profile_a(), answer.answers).asking("ER-001")

    assert roles.by_document["doc:4"].role == "bought"
    assert roles.note_for("doc:4") is None
    assert roles.unclear() == ()


# --- 8. the consumers' helpers (section 4, 6) -----------------------------------------------


def result(limits: list[str]) -> CheckResult:
    return CheckResult(
        check="rms.fict",
        status="demonstrated",
        severity="low",
        observed="fict",
        requirement="fict",
        inputs=[],
        calculation=None,
        coverage_limits=limits,
        recommended_action="fict",
    )


def test_note_unclear_appends_the_note_once() -> None:
    noted = note_unclear(result(["earlier"]), "may be a bought part: x; asked in ER-001")

    assert noted.coverage_limits == ["earlier", "may be a bought part: x; asked in ER-001"]
    assert note_unclear(noted, "may be a bought part: x; asked in ER-001") == noted
    assert note_unclear(result([]), None).coverage_limits == []


def test_the_refusal_for_a_bought_id_names_the_reason_not_the_value() -> None:
    assert BOUGHT_REFUSAL == "a bought part: not graded for modelling practice"


def test_part_roles_is_frozen_and_asking_copies() -> None:
    roles = classify_parts(package(), profile_a())

    asked = roles.asking("ER-007")

    assert isinstance(asked, PartRoles)
    assert (roles.asked_in, asked.asked_in) == (None, "ER-007")
    with pytest.raises(AttributeError):
        roles.asked_in = "ER-001"  # type: ignore[misc]


def test_the_roles_ride_on_the_context_under_one_attribute() -> None:
    from swreview.checks.part_roles import PART_ROLES_ATTRIBUTE
    from swreview.tools.checks_mechanical import attach_part_roles, review_roles
    from swreview.tools.context import context_for

    context = context_for(sitting())
    assert review_roles(context) is None

    roles = classify_parts(context.ir, profile_a())
    attach_part_roles(context, roles)

    assert review_roles(context) is roles
    assert getattr(context, PART_ROLES_ATTRIBUTE) is roles
    assert PART_ROLES_ATTRIBUTE == "part_roles"


# --- 9. more edges -----------------------------------------------------------------------------


def test_a_document_no_instance_references_is_read_in_its_active_configuration() -> None:
    """A model a drawing references, say, with no component instance of it."""
    part = document(
        "doc:2",
        "fict-drive.SLDPRT",
        configurations=("Shipped", "Other"),
        properties={SWITCH: CUSTOM_VALUE, DETAIL: ""},
        per_configuration={"Shipped": {SWITCH: BOUGHT_VALUE}, "Other": {SWITCH: CUSTOM_VALUE}},
    )

    assert signals(package(part, components=[])) == {("switch", "bought", "strong")}


def test_one_property_spelled_two_ways_on_one_level_is_read_from_both() -> None:
    squeezed = "".join(PART_NUMBER.split())
    part = document(
        "doc:2",
        "fict-pin.SLDPRT",
        properties={PART_NUMBER: "", squeezed: f"{BOUGHT_PREFIX}0042", DETAIL: ""},
    )

    assert signals(package(part)) == {("bought_number", "bought", "medium")}


def test_a_blank_part_number_is_no_number() -> None:
    part = document("doc:2", "fict-pin.SLDPRT", properties={PART_NUMBER: "   ", DETAIL: ""})

    assert signals(package(part)) == set()


def test_a_cycle_in_the_instance_tree_ends_the_ancestor_walk() -> None:
    """A defective dump whose instances name each other as parents: no inheritance, no hang."""
    child = document("doc:6", "fict-shaft.SLDPRT", properties={DETAIL: ""})
    drive = document("doc:5", "fict-drive.SLDASM", kind="assembly", properties={DETAIL: ""})
    components = [
        instance("cmp:0005", "doc:5", parent_id="cmp:0006"),
        instance("cmp:0006", "doc:6", parent_id="cmp:0005"),
    ]

    roles = classify_parts(package(drive, child, components=components), profile_a())

    assert roles.by_document["doc:6"].role == "unclear"


def test_an_empty_package_of_models_fires_no_guard() -> None:
    drawing_root = document("doc:1", "fict.SLDDRW", kind="drawing")

    roles = classify_parts(package(root=drawing_root, components=[]), profile_a())

    assert roles.by_document == {}
    assert roles.guard_fired is False


# --- integration of lanes P and S (2026-09-27): the rows a regrade restates ------------------


def test_the_row_checks_are_the_three_coverage_checks_the_classifier_writes() -> None:
    """What `start_review` and a regrade withdraw before they record the rows again."""
    from swreview.checks.part_roles import (
        BOUGHT_PARTS_CHECK,
        MAYBE_BOUGHT_CHECK,
        PART_ROLES_CHECK,
        ROW_CHECKS,
    )

    assert ROW_CHECKS == (BOUGHT_PARTS_CHECK, MAYBE_BOUGHT_CHECK, PART_ROLES_CHECK)


def test_a_restated_bought_parts_sentence_names_the_findings_the_answer_withdrew() -> None:
    """Section 9: "The bought-parts row is restated naming the withdrawn ids"."""
    subject = sitting()
    roles = classify_parts(subject, profile_a())
    plain = bought_parts_sentence(roles, subject)

    restated = bought_parts_sentence(roles, subject, withdrawn=("F-002", "F-005"))

    assert plain is not None
    assert restated == f"{plain}; withdrew F-002, F-005"
    assert bought_parts_sentence(roles, subject, withdrawn=()) == plain


def test_the_absent_state_never_names_a_withdrawal() -> None:
    """Nothing is bought by an answer in the absent state (no question is asked), so no tail."""
    subject = sitting()
    roles = classify_parts(subject, None)

    assert bought_parts_sentence(roles, subject, withdrawn=("F-002",)) == bought_parts_sentence(
        roles, subject
    )
