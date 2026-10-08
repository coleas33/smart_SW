"""The case file: its data-only model (T089) and its one reader (T090), for T088.

Feature 014 `contracts/scripted-answers.md` 2.2, 2.3 and 7's first bullets; data-model section 3
("CaseFile"); plan decisions INT-6, QA-5 and QA-11; FR-022, FR-051, US4-8.

- **The model** (`benchmark/case_file.py`, data only): `CaseFile` and `ScriptedAnswer`, strict,
  built from Python values with no loader and no agent module imported, the generator's path,
  and dumped in section 2.2's own shape. Its rows of section 2.3 refuse whenever a `CaseFile` is
  built, each naming the entry: row 1's version and unknown fields, row 3 (ids `A-<n>`, unique in
  the file; `part_roles: true` exactly when `item` and `ids` are absent, otherwise `item` stated,
  a string or `null`, with `ids` non-empty) and row 4 (an answer blank once trimmed).
- **The reader** (`benchmark/answers.load_case_file`): every refusal a `CaseFileError` of one
  line starting "case file {name}:" and naming the set entry it was loaded for, then, where there
  is one, the case-file entry. `{name}` is the file's path relative to `benchmark.sets.REPO_ROOT`
  when it lies in the checkout, its file name otherwise, so no local folder reaches the line
  (FR-051). Row 1's unreadable and not-JSON files and the model's rows first, then rows 2 and 5
  to 10 in order, the first failing row ending the load.

Every case file is fictional and written into `tmp_path`, over `tests/support/roles_review.py`'s
package and profile: the assembly `doc:0001`, the plate `doc:0002` with its instance `cmp:0001`,
the pin `doc:0003` with its two instances `cmp:0002` and `cmp:0003`, and the convention-only
version 3 profile under which the pin is unclear and the part-roles question is asked. Row 7's
hole and fastener are the questions reader's package's (`questions_package()`), the same ids plus
the plate's hole `hol:0001` and the pin's screw `fst:0001`, which the roles package has not.

The set-load bullet (a case file inside a package folder the set names, refused at set load) is
T093's, at the end of this file, and the before-any-review bullet (every refusal before the first
review) T095's.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.checklist import load_checklist
from swreview.benchmark import case_file, sets
from swreview.benchmark.answers import CaseFileError, load_case_file
from swreview.benchmark.case_file import CASE_FILE_VERSION, CaseFile, ScriptedAnswer
from swreview.benchmark.sets import BenchmarkPackageRef
from swreview.checks import part_roles
from swreview.checks.standards.profile import StandardsProfile, load_profile
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from tests.support.roles_review import PIN_ID, PLATE_ID, ROOT_ID, write_package, write_profile
from tests.unit.test_answer_key import messages
from tests.unit.test_benchmark_questions import questions_package

PACKAGE_ID = "fict-roles"
ENTRY = BenchmarkPackageRef(package_id=PACKAGE_ID, path=Path("benchmarks/packages/fict-roles"))
"""The set entry every case file here is loaded for."""

CHECKLIST = load_checklist()

CASE_NAME = "fict-roles.json"
PREFIX = f"case file {CASE_NAME}: set entry {PACKAGE_ID}: "
"""How every refusal of a case file lying outside the checkout starts: its file name, then the
set entry it was loaded for."""

PLATE_1 = "cmp:0001"
PIN_1 = "cmp:0002"
PIN_2 = "cmp:0003"
HOLE = "hol:0001"
SCREW = "fst:0001"

FIT = "interfaces.fit"
FASTENERS = "fasteners"

SECTION_2_2 = {
    "case_file_version": 1,
    "package_id": "fict-r3-press-fit-a",
    "answers": [
        {
            "id": "A-1",
            "item": "interfaces.fit",
            "ids": ["cmp:0001", "cmp:0002"],
            "answer": "press fit",
        },
        {
            "id": "A-2",
            "item": "fasteners",
            "ids": ["doc:0002"],
            "answer": "the screws are in a separate assembly",
        },
        {"id": "A-3", "part_roles": True, "answer": "All bought"},
    ],
}
"""`scripted-answers.md` 2.2's example, written out as the contract has it."""


# --- builders --------------------------------------------------------------------------------


def item_answer(**fields: Any) -> dict[str, Any]:
    """A well-formed answer to the fit question naming the plate and the pin's first instance,
    with `fields` replacing its defaults."""
    entry: dict[str, Any] = {
        "id": "A-1",
        "item": FIT,
        "ids": [PLATE_1, PIN_1],
        "answer": "press fit",
    }
    entry.update(fields)
    return entry


def roles_answer(**fields: Any) -> dict[str, Any]:
    """A well-formed answer to the part-roles question, with `fields` replacing its defaults."""
    entry: dict[str, Any] = {"id": "A-3", "part_roles": True, "answer": "All bought"}
    entry.update(fields)
    return entry


def without(entry: dict[str, Any], name: str) -> dict[str, Any]:
    """`entry` with its field `name` removed."""
    return {field: value for field, value in entry.items() if field != name}


def case(*answers: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A version 1 case file for the set entry holding `answers`, with `fields` added or
    replaced at the file's level."""
    payload: dict[str, Any] = {
        "case_file_version": CASE_FILE_VERSION,
        "package_id": PACKAGE_ID,
        "answers": list(answers),
    }
    payload.update(fields)
    return payload


def write_case(folder: Path, content: dict[str, Any] | list[Any] | str | bytes) -> Path:
    """`content` written to `folder / CASE_NAME`: JSON for a value, as given for text or bytes."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / CASE_NAME
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return path


def load(
    path: Path, package: EvidencePackage, profile: StandardsProfile | None
) -> CaseFile:
    return load_case_file(
        path, entry=ENTRY, package=package, checklist=CHECKLIST, profile=profile
    )


def refusal(
    tmp_path: Path,
    content: dict[str, Any] | list[Any] | str | bytes,
    package: EvidencePackage,
    profile: StandardsProfile | None,
) -> str:
    """The one line `load_case_file` refuses `content` with, written outside the checkout: it
    starts with the file name and the set entry, and holds no local folder (FR-051)."""
    path = write_case(tmp_path / "case_files", content)
    with pytest.raises(CaseFileError) as caught:
        load(path, package, profile)
    message = str(caught.value)
    assert message.startswith(PREFIX), message
    assert "\n" not in message
    assert str(tmp_path) not in message and tmp_path.name not in message, message
    return message


def model_refusal(payload: dict[str, Any]) -> str:
    """The `messages` of the `ValidationError` building `payload` with no loader raises."""
    with pytest.raises(ValidationError) as caught:
        CaseFile.model_validate(payload)
    return messages(caught.value)


@pytest.fixture
def package(tmp_path: Path) -> EvidencePackage:
    """`roles_review.py`'s package: the assembly, the plate and the pin of two instances."""
    return load_package(write_package(tmp_path / "packages" / PACKAGE_ID)).package


@pytest.fixture
def profile(tmp_path: Path) -> StandardsProfile:
    """`roles_review.py`'s convention-only profile, under which the pin is unclear and the
    part-roles question is asked (QA-5)."""
    return load_profile(write_profile(tmp_path))


# --- a case file loads (FR-022) --------------------------------------------------------------


def test_a_case_file_with_an_item_answer_a_no_item_answer_and_a_part_roles_answer_loads(
    tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    payload = case(
        item_answer(),
        item_answer(
            id="A-2", item=None, ids=[PLATE_ID], answer="the screws are in a separate assembly"
        ),
        roles_answer(),
    )

    loaded = load_case_file(
        write_case(tmp_path / "case_files", payload),
        entry=ENTRY,
        package=package,
        checklist=load_checklist(),
        profile=profile,
    )

    assert isinstance(loaded, CaseFile)
    assert loaded.model_dump(mode="json") == payload
    assert [answer.part_roles for answer in loaded.answers] == [False, False, True]
    assert [answer.item for answer in loaded.answers] == [FIT, None, None]
    assert loaded.answers[0].ids == [PLATE_1, PIN_1]


def test_a_case_file_builds_in_memory_and_dumps_in_section_2_2_s_shape() -> None:
    """The generator's path (INT-6): built from Python values, no file and no loader. The
    part-roles answer dumps without `item` and `ids`, an item answer without `part_roles`, and
    a stated `item: null` is kept, so the dump builds again as itself."""
    built = CaseFile(
        case_file_version=CASE_FILE_VERSION,
        package_id="fict-r3-press-fit-a",
        answers=[
            ScriptedAnswer(
                id="A-1", item="interfaces.fit", ids=["cmp:0001", "cmp:0002"], answer="press fit"
            ),
            ScriptedAnswer(
                id="A-2",
                item="fasteners",
                ids=["doc:0002"],
                answer="the screws are in a separate assembly",
            ),
            ScriptedAnswer(id="A-3", part_roles=True, answer="All bought"),
        ],
    )
    no_item = ScriptedAnswer(id="A-4", item=None, ids=["doc:0003"], answer="bought")

    assert built.model_dump(mode="json") == SECTION_2_2
    assert CaseFile.model_validate_json(built.model_dump_json()).model_dump() == SECTION_2_2
    assert no_item.model_dump() == {
        "id": "A-4",
        "item": None,
        "ids": ["doc:0003"],
        "answer": "bought",
    }


def test_case_file_version_is_1() -> None:
    assert CASE_FILE_VERSION == 1


def test_the_case_file_module_imports_pydantic_the_stdlib_and_two_findings_names() -> None:
    """INT-6: the format is data only, so the generator writes case files through it without
    `benchmark/answers.py`: from `swreview` it imports `findings.ReviewModel` and the entry
    refusals' one wording, `findings.field_refusals` (research 9.14). US5's
    `test_benchmark_generator_imports.py` pins it transitively."""
    path = Path(case_file.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    from_findings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))
            if node.module == "swreview.findings":
                from_findings.update(alias.name for alias in node.names)

    outside = {
        module
        for module in modules
        if module.split(".")[0] not in sys.stdlib_module_names
        and module not in {"pydantic", "swreview.findings"}
    }
    assert outside == set()
    assert from_findings == {"ReviewModel", "field_refusals"}


GENERATOR_FORBIDDEN = ("swreview.agent", "swreview.tools", "swreview.checks")
"""What the generator's formats may never load, transitively (`generator.md` 9)."""


def test_building_a_case_file_loads_no_reader_and_no_agent_tools_or_checks_module() -> None:
    """The generator's path in a fresh interpreter: importing the model and building a case
    file leaves `benchmark.answers` and every `swreview.agent`, `swreview.tools` and
    `swreview.checks` module unloaded (`generator.md` 9)."""
    code = (
        "import sys\n"
        "from swreview.benchmark.case_file import CaseFile, ScriptedAnswer\n"
        "CaseFile(case_file_version=1, package_id='fict-a', answers=["
        "ScriptedAnswer(id='A-1', item=None, ids=['doc:0002'], answer='bought'), "
        "ScriptedAnswer(id='A-2', part_roles=True, answer='All bought')])\n"
        "print('\\n'.join(sorted(sys.modules)))\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    loaded = completed.stdout.split()
    assert "swreview.benchmark.case_file" in loaded, completed.stderr
    forbidden = sorted(
        name
        for name in loaded
        if name == "swreview.benchmark.answers"
        or any(name == prefix or name.startswith(f"{prefix}.") for prefix in GENERATOR_FORBIDDEN)
    )
    assert forbidden == []


# --- the model's rows: 1, 3 and 4, on the model and through the reader -----------------------

MODEL_ROWS = [
    # row 1: the version and unknown fields
    pytest.param(
        case(item_answer(), notes="fictional"), ("notes",), id="row1-unknown-field-on-the-file"
    ),
    pytest.param(
        case(item_answer(id="A-2", hint="fictional")),
        ("A-2", "hint"),
        id="row1-unknown-field-on-an-entry",
    ),
    pytest.param(
        case(item_answer(), case_file_version=2),
        ("case_file_version is 2",),
        id="row1-version-2",
    ),
    pytest.param(
        without(case(item_answer()), "case_file_version"),
        ("case_file_version",),
        id="row1-no-version",
    ),
    # row 3: ids and the entry's shape
    pytest.param(
        case(item_answer(), item_answer(item=FASTENERS, ids=[ROOT_ID])),
        ("A-1 names two entries",),
        id="row3-id-repeated",
    ),
    pytest.param(
        case(roles_answer(item=FIT)), ("A-3", "part_roles", "item"), id="row3-part-roles-and-item"
    ),
    pytest.param(
        case(roles_answer(item=None)),
        ("A-3", "part_roles", "item"),
        id="row3-part-roles-and-a-null-item",
    ),
    pytest.param(
        case(roles_answer(ids=[PIN_ID])), ("A-3", "part_roles", "ids"), id="row3-part-roles-and-ids"
    ),
    pytest.param(
        case({"id": "A-4", "answer": "bought"}),
        ("A-4", "neither part_roles nor item"),
        id="row3-neither",
    ),
    pytest.param(
        case({"id": "A-4", "ids": [PIN_ID], "answer": "bought"}),
        ("A-4", "neither part_roles nor item"),
        id="row3-ids-and-no-item",
    ),
    pytest.param(case(without(item_answer(), "ids")), ("A-1", "ids"), id="row3-an-item-and-no-ids"),
    pytest.param(case(item_answer(ids=[])), ("A-1", "ids"), id="row3-an-item-and-empty-ids"),
    pytest.param(
        case(item_answer(ids=None)), ("A-1", "ids"), id="row3-an-item-and-null-ids"
    ),
    pytest.param(
        case(roles_answer(part_roles=False)), ("A-3", "part_roles"), id="row3-part-roles-false"
    ),
    pytest.param(
        case(item_answer(part_roles=False)),
        ("A-1", "part_roles false"),
        id="row3-part-roles-false-with-an-item-and-ids",
    ),
    pytest.param(
        case(roles_answer(part_roles=None)), ("A-3", "part_roles"), id="row3-part-roles-null"
    ),
    pytest.param(case(roles_answer(part_roles=1)), ("A-3", "part_roles"), id="row3-part-roles-1"),
    pytest.param(case(item_answer(item=7)), ("A-1", "item"), id="row3-an-item-not-a-string"),
    *(
        pytest.param(case(item_answer(id=bad)), (bad, "A-<n>"), id=f"row3-id-{bad or 'empty'}")
        for bad in ("A1", "a-1", "A-0", "A-01", "B-1", "A-", "A-1x", "")
    ),
    # row 4: a blank answer, the pane route's rule
    *(
        pytest.param(case(item_answer(answer=blank)), ("A-1", "blank"), id=f"row4-{label}")
        for label, blank in (("empty", ""), ("spaces", "   "), ("whitespace", " \t\n "))
    ),
    pytest.param(
        case(without(item_answer(), "answer")), ("A-1", "answer"), id="row4-no-answer"
    ),
]


@pytest.mark.parametrize(("payload", "named"), MODEL_ROWS)
def test_the_model_refuses_rows_1_3_and_4_naming_the_entry(
    payload: dict[str, Any], named: tuple[str, ...]
) -> None:
    """T089's acceptance: the rows hold on the model, with no loader to name anything."""
    message = model_refusal(payload)

    for word in named:
        assert word in message, message


@pytest.mark.parametrize(("payload", "named"), MODEL_ROWS)
def test_the_reader_refuses_rows_1_3_and_4_naming_the_file_the_set_entry_and_the_entry(
    payload: dict[str, Any],
    named: tuple[str, ...],
    tmp_path: Path,
    package: EvidencePackage,
    profile: StandardsProfile,
) -> None:
    message = refusal(tmp_path, payload, package, profile)

    for word in named:
        assert word in message, message
    assert "Value error" not in message


def test_a_model_refusal_names_the_entry_first() -> None:
    """Pydantic's refusals inside an entry read as the model's own: the entry, then the field."""
    message = model_refusal(case(item_answer(id="A-2", hint="fictional")))

    assert "A-2 hint:" in message, message


@pytest.mark.parametrize("blank", ["", "  "], ids=["empty", "spaces"])
def test_a_blank_id_is_named_quoted_never_as_a_bare_space(
    blank: str, tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    """An entry whose id is blank is named by its quoted form, so the line names something
    where the id stands: row 3's refusal and pydantic's alike, on the model and through the
    reader."""
    quoted = repr(blank)
    for payload, reason in (
        (case(item_answer(id=blank)), "is not a scripted answer's id"),
        (case(without(item_answer(id=blank), "answer")), "states no answer"),
    ):
        assert f"{quoted} {reason}" in model_refusal(payload)
        message = refusal(tmp_path, payload, package, profile)
        assert f"{PREFIX}{quoted} {reason}" in message, message


# --- row 1: what the file is -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        pytest.param("{not json", "not JSON", id="not-json"),
        pytest.param("", "not JSON", id="empty"),
        pytest.param(b"\xff\xfe{}", "not UTF-8", id="not-utf-8"),
        pytest.param([], "", id="a-list-not-an-object"),
        pytest.param("null", "", id="null"),
    ],
)
def test_a_file_that_is_not_a_case_file_s_json_is_refused_by_row_1(
    content: str | bytes | list[Any],
    reason: str,
    tmp_path: Path,
    package: EvidencePackage,
    profile: StandardsProfile,
) -> None:
    message = refusal(tmp_path, content, package, profile)

    assert reason in message


def test_a_case_file_that_cannot_be_read_is_refused_naming_it_and_no_folder(
    tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    """A missing file: the reason is the error's own words, never its text, which carries the
    absolute path the read was given (FR-051)."""
    missing = tmp_path / "case_files" / CASE_NAME

    with pytest.raises(CaseFileError) as caught:
        load(missing, package, profile)

    message = str(caught.value)
    assert message.startswith(f"{PREFIX}cannot be read ("), message
    assert str(tmp_path) not in message and "case_files" not in message


def test_a_case_file_error_is_a_value_error() -> None:
    """So the command line prints it as one line and exits 1."""
    assert issubclass(CaseFileError, ValueError)


# --- {name}: relative inside the checkout, the file name outside it (FR-051) -----------------


def test_a_case_file_inside_the_checkout_is_named_by_its_checkout_relative_path(
    tmp_path: Path,
    package: EvidencePackage,
    profile: StandardsProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sets.REPO_ROOT` read at call time, as `benchmark run` reads it."""
    checkout = tmp_path / "checkout"
    monkeypatch.setattr(sets, "REPO_ROOT", checkout)
    path = write_case(checkout / "benchmarks" / "case_files", "{not json")

    with pytest.raises(CaseFileError) as caught:
        load(path, package, profile)

    message = str(caught.value)
    assert message.startswith(
        f"case file benchmarks/case_files/{CASE_NAME}: set entry {PACKAGE_ID}: not JSON"
    ), message
    assert str(tmp_path) not in message


def test_a_case_file_outside_the_checkout_is_named_by_its_file_name_alone(
    tmp_path: Path,
    package: EvidencePackage,
    profile: StandardsProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A neighbour of the checkout whose name only begins with the checkout's is outside it."""
    monkeypatch.setattr(sets, "REPO_ROOT", tmp_path / "checkout")
    path = write_case(tmp_path / "checkout-private", "{not json")

    with pytest.raises(CaseFileError) as caught:
        load(path, package, profile)

    message = str(caught.value)
    assert message.startswith(f"case file {CASE_NAME}: set entry {PACKAGE_ID}: not JSON"), message
    assert "checkout" not in message


# --- row 2: the package id -------------------------------------------------------------------


def test_a_package_id_other_than_the_set_entry_s_is_refused_naming_both(
    tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    message = refusal(tmp_path, case(item_answer(), package_id="fict-other"), package, profile)

    assert "fict-other" in message
    assert message.count(PACKAGE_ID) >= 2, message


# --- rows 5 and 6: the item ------------------------------------------------------------------


def test_an_item_not_in_the_checklist_is_refused_naming_the_entry_and_the_item(
    tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    message = refusal(tmp_path, case(item_answer(item="interfaces.fitt")), package, profile)

    assert "A-1" in message and "interfaces.fitt" in message


CODE_OWNED = ("provenance", "coverage.closeout")


def test_the_checklist_s_code_owned_items_are_the_two_row_6_is_tried_on() -> None:
    assert tuple(item.id for item in CHECKLIST.items if item.owner == "code") == CODE_OWNED


@pytest.mark.parametrize("item", CODE_OWNED)
def test_a_code_owned_item_is_refused_as_one_that_can_never_be_asked(
    item: str, tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    """`request_evidence` answers a code-owned item `closed_by_code` and records nothing, so its
    question can never be open (`tools/session.py:112`)."""
    message = refusal(tmp_path, case(item_answer(item=item)), package, profile)

    assert "A-1" in message and item in message
    assert "can never be asked" in message


# --- row 7: the ids --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [HOLE, SCREW, "cmp:0099", "doc:0099"])
def test_an_id_that_is_not_a_component_instance_or_a_document_is_refused_naming_it(
    bad: str, tmp_path: Path
) -> None:
    """A hole or a fastener of the package is refused too: a request naming one resolves to its
    instance (`questions.md` 2), so an entry never needs one."""
    message = refusal(
        tmp_path, case(item_answer(id="A-2", ids=[PLATE_1, bad])), questions_package(), None
    )

    assert "A-2" in message and bad in message


def test_component_instances_and_documents_the_root_assembly_among_them_load(
    tmp_path: Path,
) -> None:
    payload = case(
        item_answer(ids=[PLATE_1, PIN_2]),
        item_answer(id="A-2", item=FASTENERS, ids=[PLATE_ID, ROOT_ID]),
    )

    loaded = load(write_case(tmp_path, payload), questions_package(), None)

    assert loaded.model_dump(mode="json") == payload


# --- row 8: two entries a request could match both of (research §8.3; QA-11; RR3-4) -----------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(
            item_answer(ids=[PIN_ID]),
            item_answer(id="A-2", ids=[PIN_1], answer="slip fit"),
            id="one-item-a-document-and-one-of-its-instances",
        ),
        pytest.param(
            item_answer(item=None, ids=[PIN_ID]),
            item_answer(id="A-2", item=None, ids=[PIN_2], answer="bought"),
            id="no-item-a-document-and-one-of-its-instances",
        ),
        pytest.param(
            item_answer(ids=[PLATE_1, PIN_1]),
            item_answer(id="A-2", ids=[PIN_1, PIN_2], answer="slip fit"),
            id="one-item-a-shared-instance",
        ),
    ],
)
def test_two_entries_whose_resolved_ids_intersect_are_refused_naming_both(
    first: dict[str, Any],
    second: dict[str, Any],
    tmp_path: Path,
    package: EvidencePackage,
    profile: StandardsProfile,
) -> None:
    message = refusal(tmp_path, case(first, second), package, profile)

    assert "A-1" in message and "A-2" in message


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(
            item_answer(ids=[PIN_1]),
            item_answer(id="A-2", ids=[PIN_2], answer="slip fit"),
            id="one-item-the-pin-s-two-instances",
        ),
        pytest.param(
            item_answer(ids=[PIN_ID]),
            item_answer(id="A-2", item=FASTENERS, ids=[PIN_ID], answer="bought"),
            id="two-items-one-document",
        ),
        pytest.param(
            item_answer(ids=[PIN_ID]),
            item_answer(id="A-2", item=None, ids=[PIN_ID], answer="bought"),
            id="an-item-and-no-item-one-document",
        ),
    ],
)
def test_two_entries_no_request_could_match_both_of_load(
    first: dict[str, Any],
    second: dict[str, Any],
    tmp_path: Path,
    package: EvidencePackage,
    profile: StandardsProfile,
) -> None:
    """RR3-4: two disjoint entries on one item are two answers; entries on different items, or
    one on an item and one on none, never answer one request."""
    payload = case(first, second)

    loaded = load(write_case(tmp_path, payload), package, profile)

    assert loaded.model_dump(mode="json") == payload


# --- row 9: one part-roles answer ------------------------------------------------------------


def test_two_part_roles_entries_are_refused_naming_both(
    tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    message = refusal(
        tmp_path,
        case(roles_answer(), item_answer(), roles_answer(id="A-4", answer="None bought")),
        package,
        profile,
    )

    assert "A-3" in message and "A-4" in message


# --- row 10: a part-roles answer the run's profile would never ask (QA-5) --------------------


def test_a_part_roles_entry_with_no_profile_is_refused_naming_the_classifier_s_reason(
    tmp_path: Path, package: EvidencePackage
) -> None:
    message = refusal(tmp_path, case(item_answer(), roles_answer()), package, None)

    assert "A-3" in message
    assert part_roles.STATE_NO_PROFILE in message


def test_a_part_roles_entry_under_a_profile_in_the_absent_state_is_refused(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """A version 3 profile naming no part-number convention: the classifier's absent state
    (`checks/part_roles.py:725-738`), though a profile is attached."""
    folder = tmp_path / "absent"
    folder.mkdir()
    absent = load_profile(write_profile(folder, pattern=""))

    message = refusal(tmp_path, case(roles_answer()), package, absent)

    assert "A-3" in message
    assert part_roles.STATE_NO_CONVENTION in message


def test_a_part_roles_entry_when_the_zero_match_guard_fires_is_refused(
    tmp_path: Path, package: EvidencePackage
) -> None:
    """A convention matching none of the package's three documents would ask about every part,
    so the guard asks nothing (013 `contracts/part-roles.md` 2)."""
    folder = tmp_path / "guard"
    folder.mkdir()
    guarded = load_profile(write_profile(folder, pattern="FICT-ZZ-####.SLDPRT"))

    message = refusal(tmp_path, case(roles_answer()), package, guarded)

    assert "A-3" in message
    assert part_roles.GUARD_CONVENTION.format(count=3) in message


def test_a_part_roles_entry_on_a_package_whose_parts_are_all_decided_is_refused(
    tmp_path: Path, profile: StandardsProfile
) -> None:
    """With no pin, the convention decides the assembly and the plate: nothing is unclear."""
    decided = load_package(write_package(tmp_path / "packages" / "no-pin", pin=False)).package

    message = refusal(tmp_path, case(roles_answer()), decided, profile)

    assert "A-3" in message
    assert "no part is unclear" in message


def test_a_part_roles_entry_under_the_convention_only_profile_that_asks_loads(
    tmp_path: Path, package: EvidencePackage, profile: StandardsProfile
) -> None:
    """QA-5: the convention-only profile has no `part_roles` section, and its question is asked,
    so testing for the section instead would refuse this entry."""
    assert profile.part_roles is None
    roles = part_roles.classify_parts(package, profile, None, profile_refusal=None)
    assert part_roles.roles_question(roles, package) is not None

    loaded = load(write_case(tmp_path, case(roles_answer())), package, profile)

    assert [answer.id for answer in loaded.answers] == ["A-3"]


# --- the order: the first failing row ends the load ------------------------------------------


@pytest.mark.parametrize(
    ("payload", "profile_kind", "named", "unnamed"),
    [
        pytest.param(
            case(item_answer(item="interfaces.fitt"), package_id="fict-other"),
            "convention",
            "fict-other",
            "interfaces.fitt",
            id="row2-before-row5",
        ),
        pytest.param(
            case(item_answer(ids=[PLATE_1, "cmp:0099"]), item_answer(id="A-2", item="intrfaces")),
            "convention",
            "intrfaces",
            "cmp:0099",
            id="row5-before-row7-whatever-the-entry-order",
        ),
        pytest.param(
            case(item_answer(ids=["cmp:0099"]), item_answer(id="A-2", item="provenance")),
            "convention",
            "can never be asked",
            "cmp:0099",
            id="row6-before-row7",
        ),
        pytest.param(
            case(item_answer(ids=[PIN_1, "cmp:0099"]), item_answer(id="A-2", ids=[PIN_ID])),
            "convention",
            "cmp:0099",
            "A-2",
            id="row7-before-row8",
        ),
        pytest.param(
            case(roles_answer(), roles_answer(id="A-4")),
            "none",
            "A-4",
            part_roles.STATE_NO_PROFILE,
            id="row9-before-row10",
        ),
    ],
)
def test_the_first_failing_row_ends_the_load(
    payload: dict[str, Any],
    profile_kind: str,
    named: str,
    unnamed: str,
    tmp_path: Path,
    package: EvidencePackage,
    profile: StandardsProfile,
) -> None:
    message = refusal(
        tmp_path, payload, package, profile if profile_kind == "convention" else None
    )

    assert named in message, message
    assert unnamed not in message, message


# --- outside the package: refused at set load (FR-022; T093) ---------------------------------


@pytest.mark.parametrize(
    "folder",
    [f"benchmarks/packages/{PACKAGE_ID}", f"benchmarks/packages/{PACKAGE_ID}/answers"],
    ids=["in-the-package-folder", "below-it"],
)
def test_a_case_file_inside_a_package_folder_the_set_names_is_refused_at_set_load(
    folder: str, tmp_path: Path
) -> None:
    """`scripted-answers.md` 2.1: a case file that resolves inside any package folder the set
    names is refused as the set loads (`cases.md` 4.3 row 5), before `load_case_file` is ever
    asked, though the file itself would load (FR-022, "outside the package")."""
    checkout = tmp_path / "checkout"
    write_package(checkout / "benchmarks" / "packages" / PACKAGE_ID)
    case_path = write_case(checkout / folder, case(item_answer()))
    set_path = checkout / "benchmarks" / "sets" / "fict.json"
    set_path.parent.mkdir(parents=True)
    set_path.write_text(
        json.dumps(
            {
                "name": "fict",
                "packages": [
                    {
                        "package_id": PACKAGE_ID,
                        "path": f"benchmarks/packages/{PACKAGE_ID}",
                        "case_file": f"{folder}/{CASE_NAME}",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(sets.SetError) as refused:
        sets.load_set(set_path, root=checkout)

    message = str(refused.value)
    assert message.startswith("benchmark set fict.json:"), message
    assert str(case_path.resolve()) in message
    assert message.endswith(
        "the reviewer reads the package folder; keep keys and case files outside it"
    )


# --- every refusal before any review (US4-8; T095) -------------------------------------------


def case_file_set(
    folder: Path, content: dict[str, Any] | str | None, *others: dict[str, Any]
) -> Path:
    """A private set file at `folder / "sets" / "fict.json"`: the roles package, written under
    `folder / "packages"`, naming `content` as its case file under `folder / "case_files"`, then
    the entries `others`, every path absolute. `content` `None` names a case file that is not
    there. Outside the checkout, so a refusal names the case file by its file name (FR-051)."""
    package = write_package(folder / "packages" / PACKAGE_ID)
    case_path = folder / "case_files" / CASE_NAME
    if content is not None:
        write_case(case_path.parent, content)
    entry = {
        "package_id": PACKAGE_ID,
        "path": str(package),
        "case_file": str(case_path),
        "held_out": True,
    }
    set_path = folder / "sets" / "fict.json"
    set_path.parent.mkdir(parents=True, exist_ok=True)
    set_path.write_text(
        json.dumps({"name": "fict", "packages": [entry, *others]}, indent=2), encoding="utf-8"
    )
    return set_path


BEFORE_ANY_REVIEW = [
    pytest.param(None, "cannot be read (", id="row1-unreadable"),
    pytest.param("{not json", "not JSON", id="row1-not-json"),
    pytest.param(case(item_answer(), package_id="fict-other"), "fict-other", id="row2-package-id"),
    pytest.param(
        case(item_answer(), item_answer(item=FASTENERS, ids=[ROOT_ID])),
        "A-1 names two entries",
        id="row3-id-repeated",
    ),
    pytest.param(case(item_answer(answer="   ")), "A-1 states a blank answer", id="row4-blank"),
    pytest.param(
        case(item_answer(item="interfaces.fitt")), "interfaces.fitt", id="row5-not-an-item"
    ),
    pytest.param(
        case(item_answer(item="provenance")), "can never be asked", id="row6-code-owned"
    ),
    pytest.param(case(item_answer(ids=[PLATE_1, "cmp:0099"])), "cmp:0099", id="row7-unknown-id"),
    pytest.param(
        case(item_answer(ids=[PIN_ID]), item_answer(id="A-2", ids=[PIN_1], answer="slip fit")),
        "A-1 and A-2",
        id="row8-intersecting",
    ),
    pytest.param(
        case(roles_answer(), roles_answer(id="A-4", answer="None bought")),
        "A-3 and A-4",
        id="row9-two-part-roles",
    ),
    pytest.param(case(roles_answer()), part_roles.STATE_NO_PROFILE, id="row10-never-asked"),
]
"""A case file failing each row of section 2.3, for the set entry `PACKAGE_ID` with no profile,
and what its refusal names: row 1 twice, a file that is not there, of which the set loader took no
digest, and one that is not JSON."""


@pytest.mark.parametrize(("content", "named"), BEFORE_ANY_REVIEW)
def test_every_refusal_through_benchmark_run_comes_before_any_review(
    content: dict[str, Any] | str | None,
    named: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """US4-8: `benchmark run` refuses the case file with exit 1 and one line naming it and the
    set entry, before the first review: a spy review function is never called, and no package
    folder, nor anything else, is written."""
    reviewed: list[Path] = []

    def spy(package_dir: Path, session_out_dir: Path, **_keywords: Any) -> None:
        reviewed.append(package_dir)

    monkeypatch.setattr(cli, "_review_fn", spy)
    set_path = case_file_set(tmp_path, content)
    out = tmp_path / "runs" / "refused"

    result = CliRunner().invoke(
        cli.app,
        ["benchmark", "run", "--set", str(set_path), "--out", str(out), "--provider", "fake"],
    )

    assert result.exit_code == 1, result.stdout + result.stderr
    [line] = result.stderr.strip().splitlines()
    assert line.startswith(f"error: CaseFileError: {PREFIX}"), line
    assert named in line, line
    assert str(tmp_path) not in line
    assert reviewed == []
    assert not (out / PACKAGE_ID).exists()
    assert not out.exists()
