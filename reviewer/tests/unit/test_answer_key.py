"""The answer key's format 2: its data-only model (T020, for T021) and its loader (T034, for T037).

`benchmark/answer_key_model.py` is the format's one definition (`answer-key.md` 1 to 5; plan
decisions RF-1, RF-67). The model's tests build `AnswerKey` from Python values, the generator's
path, never through the loader, and pin the model's own rows of section 4:

1. **Format and fields** (row 1). `key_format` is 2: a key without it was written before this
   feature and is refused with section 2.1's sentence; any other value is refused naming the
   field. The model is strict, so an unknown field is refused at the key and at an entry.
   `key_only` is `true` or absent.
2. **Ids** (row 3). `D-<n>` for known defects and `C-<n>` for correct conditions, each unique
   across the key; an id with the other list's prefix is refused naming the id.
3. **Producer, status and tag fields** (row 4), **parts or documents** (row 5), **the
   check-pattern grammar** (row 6's grammar, with AK-4's refusal of a family over a
   reference-keyed check) and **reference shapes** (row 7). Every refusal names the entry, so
   one written by the generator, with no loader to name it, still reads "D-3 ...".
4. **The two derivations** (`answer-key.md` 9's test 15): `holds_held_out()` and
   `held_out_model_defect_ids()`, the only ones there are.
5. **The four extension lists** (T079; `answer-key.md` 2.1, 2.2, 2.4, 2.6, 2.7; `questions.md`
   5.1 and 5.2's shapes): forbidden entries (`FB-<n>`, on parts or documents, never references,
   their `checks` each through section 3's grammar, AK-4's family refusal kept to known defects
   and correct conditions), expected coverage (`CV-<n>`, `statuses` non-empty from the four
   listable readings, none twice), unanswerable requests (`U-<n>`) and question-count rules
   (`Q-<n>`), each with the tag fields every entry has. The combinations `questions.md` 5.3
   refuses build here: they are the loader's row 11.

The loader's tests (T034, at the end of the file) read key files through
`answer_key.load_answer_key(path, *, package, checklist, words)`, the one reader (`answer-key.md` 1,
4 and 6): every refusal an `AnswerKeyError` starting "answer key {file name}:" and naming the entry;
the model's rows first, then row 2 (the stem), row 6's typo guard (every check under a report goal),
row 8 (overlaps, through `benchmark/matching.py`), row 12 (key-only), and with the package row 13
(ids resolve) and row 14 (references owned by the entry's parts and documents). US3's rows for
the four lists (T083, at the very end): every list loading, the typo guard and the overlaps on
forbidden entries, row 9 and row 10 on expected coverage, and row 11, `questions.md` 5.3's
refusals of the question entries, run through `benchmark/questions.py`. Every id and description
is fictional.
"""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Callable
from itertools import combinations
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from swreview import findings
from swreview.agent.checklist import load_checklist
from swreview.benchmark import answer_key, answer_key_model
from swreview.benchmark.answer_key_model import (
    KEY_FORMAT,
    REFERENCE_KEYED_CHECKS,
    AnswerKey,
    CorrectCondition,
    DimensionReference,
    FitReference,
    HolePairReference,
    JointInstancesReference,
    JointReference,
    KnownDefect,
    RecessReference,
    StackReference,
    Stamp,
    is_family,
    pattern_covers,
)
from swreview.drawings import binding
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.report.summary import load_words
from swreview.tools.refs import resolve_dimension
from tests.support.answer_keys import write_key

FORMAT_1_SENTENCE = (
    "written in key format 1; rewrite it in format 2 "
    "(specs/014-design-review-eval/contracts/answer-key.md)"
)
"""Section 2.1's refusal of a key with no `key_format`, spelled out as the contract has it."""

STAMP = {"prompt": "a" * 64, "checklist": "b" * 64, "tools": "c" * 64}
"""A well-formed `held_out_against`: three lower-case hex digests of 64 characters."""

SHEET_DIMENSION = {"document_id": "doc:0004", "sheet": "Sheet1", "annotation": "D3"}
OTHER_DIMENSION = {"document_id": "doc:0004", "sheet": "Sheet1", "annotation": "D4"}
THIRD_DIMENSION = {"document_id": "doc:0004", "sheet": "Sheet1", "annotation": "D5"}

ONE_ELEMENT_OF_EACH_KIND: dict[str, dict[str, Any]] = {
    "joint": {"fastener": "fst:0001", "hole": "hol:0001"},
    "recess": {"recess": "hol:0001#1"},
    "hole pair": {"holes": ["hol:0001", "hol:0002"]},
    "joint instances": {"hole_instances": ["hol:0001#1", "hol:0002#1"]},
    "fit": {"bore": SHEET_DIMENSION, "shaft": OTHER_DIMENSION},
    "stack": {"contributors": [SHEET_DIMENSION, OTHER_DIMENSION], "target": THIRD_DIMENSION},
}
"""One well-formed covered item per kind of `answer-key.md` section 2.5."""

ELEMENT_MODEL_OF_EACH_KIND = {
    "joint": JointReference,
    "recess": RecessReference,
    "hole pair": HolePairReference,
    "joint instances": JointInstancesReference,
    "fit": FitReference,
    "stack": StackReference,
}

SECTION_2_5_TABLE = {
    "fastener.bottoming": "joint",
    "fastener.engagement": "joint",
    "fastener.thread_match": "joint",
    "fastener.head_clearance": "joint",
    "fastener.unsupported": "joint",
    "fastener.head_fit": "recess",
    "hole.coaxiality": "hole pair",
    "hole.nominal_alignment": "joint instances",
    "hole.position_stack": "joint instances",
    "fit.size_only": "fit",
    "stack.worst_case": "stack",
}
"""`answer-key.md` section 2.5's eleven reference-keyed checks and their kinds, written out
here so the model's table is checked against the contract rather than against itself."""


# --- builders --------------------------------------------------------------------------------


def defect(**fields: Any) -> dict[str, Any]:
    """A well-formed known defect on one part, with `fields` replacing its defaults."""
    entry: dict[str, Any] = {
        "id": "D-1",
        "check": "hygiene.revision_present",
        "component_ids": ["cmp:0001"],
        "document_ids": [],
        "producer": "code",
        "expected_status": "demonstrated",
        "tag": "tuned_on",
        "description": "The fictional bracket's drawing carries no revision.",
    }
    entry.update(fields)
    return entry


def condition(**fields: Any) -> dict[str, Any]:
    """A well-formed correct condition on one part, with `fields` replacing its defaults."""
    entry: dict[str, Any] = {
        "id": "C-1",
        "check": "rms.folders.present",
        "component_ids": ["cmp:0002"],
        "document_ids": [],
        "tag": "tuned_on",
        "description": "The fictional plate's feature tree is foldered.",
    }
    entry.update(fields)
    return entry


def without(entry: dict[str, Any], name: str) -> dict[str, Any]:
    """`entry` with its field `name` removed."""
    return {field: value for field, value in entry.items() if field != name}


def key(
    known_defects: list[dict[str, Any]] | None = None,
    correct_conditions: list[dict[str, Any]] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """A format 2 key holding the entries given, with `fields` added at the key's level."""
    payload: dict[str, Any] = {
        "key_format": 2,
        "package_id": "fict-key-a",
        "known_defects": known_defects if known_defects is not None else [],
        "correct_conditions": correct_conditions if correct_conditions is not None else [],
    }
    payload.update(fields)
    return payload


def messages(error: ValidationError) -> str:
    """`error`'s refusals, each `<location>: <message>`, joined by ` | `, and never the input
    pydantic echoes in `str(error)`: an entry's echo holds its id, so `"D-3" in str(error)`
    holds whatever the refusal says."""
    return " | ".join(
        f"{'.'.join(str(part) for part in line['loc'])}: {line['msg']}"
        if line["loc"]
        else line["msg"]
        for line in error.errors(include_url=False)
    )


def refusal(payload: dict[str, Any]) -> str:
    """The `messages` of the `ValidationError` building `payload` raises."""
    with pytest.raises(ValidationError) as caught:
        AnswerKey.model_validate(payload)
    return messages(caught.value)


def naming(entry_id: str) -> str:
    """A refusal naming the entry `entry_id`: a message that starts with the id, as the model
    raises it and pydantic words a `ValueError` (`"Value error, D-3 states no tag"`)."""
    return f"Value error, {entry_id} "


def keyed_defect(check: str, *references: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A known defect on `check` naming `references`, on the parts and document they need."""
    return defect(
        check=check,
        component_ids=["cmp:0001", "cmp:0002"],
        document_ids=["doc:0004"],
        references=list(references),
        **fields,
    )


# --- row 1: the format and its fields --------------------------------------------------------


def test_key_format_is_2() -> None:
    assert KEY_FORMAT == 2


def test_a_key_with_no_key_format_is_refused_with_section_2_1_s_sentence() -> None:
    """Today's shape: no format, no tags, a condition with no id. The format is named first."""
    format_1 = {
        "package_id": "fict-key-a",
        "known_defects": [
            {
                "id": "D-1",
                "check": "fastener.bottoming",
                "component_ids": ["cmp:0003"],
                "description": "The fictional screws may bottom in their tapped holes.",
            }
        ],
        "correct_conditions": [
            {
                "check": "fit.size_only",
                "component_ids": ["cmp:0001", "cmp:0002"],
                "description": "The fictional spigot is a clearance fit.",
            }
        ],
    }

    message = refusal(format_1)

    assert FORMAT_1_SENTENCE in message
    assert "known_defects" not in message


@pytest.mark.parametrize("value", [3, 1, "2", 2.0, True, None])
def test_a_key_format_other_than_2_is_refused_naming_the_field(value: object) -> None:
    message = refusal(key(key_format=value))

    assert "key_format" in message
    assert FORMAT_1_SENTENCE not in message


@pytest.mark.parametrize("field", ["answers", "forbidden_entries", "unanswerable", "coverage"])
def test_an_unknown_field_at_the_key_is_refused_naming_it(field: str) -> None:
    """Changed on purpose by T079: section 2.1's four other lists are fields now (the test
    below), so this one refuses a field no list has, `answers` and names close to the lists'."""
    message = refusal(key(**{field: []}))

    assert f"{field}: Extra inputs are not permitted" in message


@pytest.mark.parametrize(
    "field", ["forbidden", "expected_coverage", "unanswerable_requests", "question_counts"]
)
def test_each_of_the_four_extension_lists_is_a_field_of_the_key_default_empty(field: str) -> None:
    """Section 2.1: each optional, default empty."""
    assert getattr(AnswerKey.model_validate(key(**{field: []})), field) == []
    assert getattr(AnswerKey.model_validate(key()), field) == []


def test_an_unknown_field_at_an_entry_is_refused_naming_the_entry_and_the_field() -> None:
    message = refusal(key([defect(id="D-3", severity="high")]))

    assert naming("D-3") in message
    assert "severity" in message
    assert "Extra inputs are not permitted" in message


def test_key_only_true_is_accepted_and_absent_is_none() -> None:
    assert AnswerKey.model_validate(key(key_only=True)).key_only is True
    assert AnswerKey.model_validate(key()).key_only is None


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_key_only_other_than_true_is_refused_naming_the_field(value: object) -> None:
    assert "key_only" in refusal(key(key_only=value))


def test_an_explicit_null_key_only_is_refused_naming_the_field() -> None:
    """Section 2.1: optional, `true` only. An explicit JSON `null` is not absent."""
    message = refusal(json.loads('{"key_format": 2, "package_id": "fict-key-a", "key_only": null}'))

    assert message.startswith("key_only: "), message


def test_an_explicit_null_references_or_held_out_against_reads_as_absent() -> None:
    """The model's docstring: on a check that is not reference-keyed, `references: null` is no
    references, and on a tuned-on entry, `held_out_against: null` is no stamp."""
    explicit = AnswerKey.model_validate(key([defect(references=None, held_out_against=None)]))

    assert explicit == AnswerKey.model_validate(key([defect()]))


def test_a_key_with_known_defects_and_correct_conditions_builds() -> None:
    held_out = keyed_defect(
        "fit.size_only",
        ONE_ELEMENT_OF_EACH_KIND["fit"],
        id="D-2",
        producer="model",
        expected_status="suspected",
        tag="held_out",
        held_out_against=STAMP,
    )
    pair = condition(
        id="C-1",
        check="hole.coaxiality",
        component_ids=["cmp:0001", "cmp:0003"],
        references=[ONE_ELEMENT_OF_EACH_KIND["hole pair"]],
    )

    built = AnswerKey.model_validate(key([defect(), held_out], [pair, condition(id="C-2")]))

    assert built.key_format == 2
    assert built.package_id == "fict-key-a"
    assert [entry.id for entry in built.known_defects] == ["D-1", "D-2"]
    assert [entry.id for entry in built.correct_conditions] == ["C-1", "C-2"]
    assert all(isinstance(entry, KnownDefect) for entry in built.known_defects)
    assert all(isinstance(entry, CorrectCondition) for entry in built.correct_conditions)
    assert built.known_defects[0].references is None
    assert built.known_defects[1].held_out_against == Stamp(**STAMP)
    assert built.known_defects[1].references == [
        FitReference(
            bore=DimensionReference(**SHEET_DIMENSION),
            shaft=DimensionReference(**OTHER_DIMENSION),
        )
    ]
    assert built.correct_conditions[0].references == [
        HolePairReference(holes=["hol:0001", "hol:0002"])
    ]


def test_a_key_with_no_entries_builds_with_empty_lists() -> None:
    built = AnswerKey.model_validate({"key_format": 2, "package_id": "fict-key-a"})

    assert built.known_defects == []
    assert built.correct_conditions == []


def test_a_built_key_dumped_with_absent_fields_omitted_builds_again_as_itself() -> None:
    """The generator writes a key from the model; what it writes must read back the same."""
    built = AnswerKey.model_validate(
        key(
            [
                defect(),
                keyed_defect(
                    "stack.worst_case",
                    {"contributors": [SHEET_DIMENSION, OTHER_DIMENSION]},
                    id="D-2",
                    tag="held_out",
                    held_out_against=STAMP,
                ),
            ],
            [condition()],
            key_only=True,
        )
    )

    dumped = built.model_dump(mode="json", exclude_none=True)

    assert AnswerKey.model_validate(dumped) == built
    assert "references" not in dumped["known_defects"][0]
    assert "held_out_against" not in dumped["known_defects"][0]
    assert "target" not in dumped["known_defects"][1]["references"][0]


def test_the_model_s_producer_is_the_findings_source() -> None:
    """Written out in the model (it imports no `findings` name but `ReviewModel` and
    `field_refusals`, T021), pinned here."""
    assert set(get_args(answer_key_model.Producer)) == set(get_args(findings.Source))


def test_an_expected_status_is_a_finding_status_never_checked_within_scope() -> None:
    """13A: a defect is expected demonstrated, suspected or unresolved, never cleared."""
    assert set(get_args(answer_key_model.ExpectedStatus)) == (
        set(get_args(findings.FindingStatus)) - {"checked_within_scope"}
    )


def test_the_model_imports_pydantic_the_standard_library_and_two_findings_names() -> None:
    """RF-1: the format is data only, so the generator writes keys through it without the
    loader: from `swreview` it imports `findings.ReviewModel` and the entry refusals' one
    wording, `findings.field_refusals` (research 9.14). US5's
    `test_benchmark_generator_imports.py` pins the same transitively (T124)."""
    path = Path(answer_key_model.__file__)
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


# --- row 3: ids ------------------------------------------------------------------------------


def test_an_id_repeated_in_one_list_is_refused_naming_it() -> None:
    message = refusal(key([defect(id="D-7"), defect(id="D-7", component_ids=["cmp:0009"])]))

    assert naming("D-7") in message


def test_an_id_repeated_across_the_two_lists_is_refused_naming_it() -> None:
    message = refusal(key([defect(id="D-4")], [condition(id="D-4")]))

    assert naming("D-4") in message


@pytest.mark.parametrize(
    ("known_defects", "correct_conditions", "named"),
    [
        ([defect(id="C-2")], [], "C-2"),
        ([], [condition(id="D-2")], "D-2"),
    ],
)
def test_an_id_with_the_other_list_s_prefix_is_refused_naming_it(
    known_defects: list[dict[str, Any]],
    correct_conditions: list[dict[str, Any]],
    named: str,
) -> None:
    assert naming(named) in refusal(key(known_defects, correct_conditions))


@pytest.mark.parametrize("entry_id", ["D-", "D1", "d-1", "D-0", "D-01", "D-1a", "F-001", "FB-1"])
def test_a_known_defect_id_that_is_not_d_and_a_positive_number_is_refused_naming_it(
    entry_id: str,
) -> None:
    assert naming(entry_id) in refusal(key([defect(id=entry_id)]))


@pytest.mark.parametrize("entry_id", ["C-", "C-0", "c-3", "CV-1"])
def test_a_correct_condition_id_that_is_not_c_and_a_positive_number_is_refused(
    entry_id: str,
) -> None:
    assert naming(entry_id) in refusal(key([], [condition(id=entry_id)]))


def test_ids_of_several_digits_build() -> None:
    built = AnswerKey.model_validate(key([defect(id="D-10")], [condition(id="C-18")]))

    assert [built.known_defects[0].id, built.correct_conditions[0].id] == ["D-10", "C-18"]


# --- row 4: producer, expected status and the tag fields -------------------------------------


@pytest.mark.parametrize("field", ["expected_status", "producer"])
def test_a_known_defect_stating_no_producer_or_no_expected_status_is_refused_naming_it(
    field: str,
) -> None:
    message = refusal(key([without(defect(id="D-3"), field)]))

    assert "D-3 states no" in message
    assert field in message


def test_a_known_defect_expected_checked_within_scope_is_refused_naming_it() -> None:
    message = refusal(key([defect(id="D-3", expected_status="checked_within_scope")]))

    assert naming("D-3") in message
    assert "expected_status" in message


@pytest.mark.parametrize("value", ["cleared", "issues", None])
def test_an_expected_status_outside_the_three_is_refused_naming_the_entry(value: object) -> None:
    message = refusal(key([defect(id="D-3", expected_status=value)]))

    assert naming("D-3") in message
    assert "expected_status" in message


@pytest.mark.parametrize("value", ["human", "Code", None])
def test_a_producer_other_than_code_or_model_is_refused_naming_the_entry(value: object) -> None:
    message = refusal(key([defect(id="D-3", producer=value)]))

    assert naming("D-3") in message
    assert "producer" in message


@pytest.mark.parametrize("producer", ["code", "model"])
@pytest.mark.parametrize("status", ["demonstrated", "suspected", "unresolved"])
def test_every_producer_and_expected_status_builds(producer: str, status: str) -> None:
    built = AnswerKey.model_validate(key([defect(producer=producer, expected_status=status)]))

    assert (built.known_defects[0].producer, built.known_defects[0].expected_status) == (
        producer,
        status,
    )


@pytest.mark.parametrize(
    ("entries", "named"),
    [
        (key([without(defect(id="D-5"), "tag")]), "D-5"),
        (key([], [without(condition(id="C-5"), "tag")]), "C-5"),
    ],
)
def test_an_entry_with_no_tag_is_refused_naming_it(entries: dict[str, Any], named: str) -> None:
    message = refusal(entries)

    assert f"{named} states no tag" in message


@pytest.mark.parametrize("value", ["held-out", "tuned", None])
def test_a_tag_other_than_held_out_or_tuned_on_is_refused_naming_the_entry(value: object) -> None:
    message = refusal(key([defect(id="D-5", tag=value)]))

    assert naming("D-5") in message
    assert "tag" in message


@pytest.mark.parametrize(
    ("entries", "named"),
    [
        (key([defect(id="D-6", tag="held_out")]), "D-6"),
        (key([], [condition(id="C-6", tag="held_out")]), "C-6"),
    ],
)
def test_a_held_out_entry_with_no_held_out_against_is_refused_naming_it(
    entries: dict[str, Any], named: str
) -> None:
    message = refusal(entries)

    assert naming(named) in message
    assert "held_out_against" in message


@pytest.mark.parametrize(
    ("entries", "named"),
    [
        (key([defect(id="D-6", held_out_against=STAMP)]), "D-6"),
        (key([], [condition(id="C-6", held_out_against=STAMP)]), "C-6"),
    ],
)
def test_a_tuned_on_entry_with_held_out_against_is_refused_naming_it(
    entries: dict[str, Any], named: str
) -> None:
    message = refusal(entries)

    assert naming(named) in message
    assert "held_out_against" in message


@pytest.mark.parametrize("field", ["prompt", "checklist", "tools"])
@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "", " " + "a" * 63],
    ids=["63 characters", "65 characters", "upper-case", "not hex", "empty", "a space"],
)
def test_a_digest_that_is_not_64_lower_case_hex_characters_is_refused_naming_the_entry(
    field: str, digest: str
) -> None:
    stamp = {**STAMP, field: digest}

    message = refusal(key([defect(id="D-8", tag="held_out", held_out_against=stamp)]))

    assert naming("D-8") in message
    assert f"held_out_against.{field}" in message


def test_a_held_out_against_without_tools_is_refused_naming_the_entry() -> None:
    """25A adds `tools`: a stamp of the prompt and the checklist alone is a stamp of 2.1."""
    stamp = without(STAMP, "tools")

    message = refusal(key([defect(id="D-8", tag="held_out", held_out_against=stamp)]))

    assert "D-8 states no held_out_against.tools" in message


def test_a_held_out_against_with_an_unknown_field_is_refused_naming_the_entry() -> None:
    stamp = {**STAMP, "words": "d" * 64}

    message = refusal(key([defect(id="D-8", tag="held_out", held_out_against=stamp)]))

    assert naming("D-8") in message
    assert "words" in message


def test_a_held_out_entry_with_its_stamp_builds_on_both_lists() -> None:
    built = AnswerKey.model_validate(
        key(
            [defect(tag="held_out", held_out_against=STAMP)],
            [condition(tag="held_out", held_out_against=STAMP)],
        )
    )

    assert built.known_defects[0].held_out_against == Stamp(**STAMP)
    assert built.correct_conditions[0].held_out_against == Stamp(**STAMP)


@pytest.mark.parametrize("description", ["", "   ", "\n\t"])
def test_a_blank_description_is_refused_naming_the_entry(description: str) -> None:
    message = refusal(key([], [condition(id="C-4", description=description)]))

    assert naming("C-4") in message
    assert "description" in message


# --- row 5: parts or documents ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("entries", "named"),
    [
        (key([defect(id="D-9", component_ids=[], document_ids=[])]), "D-9"),
        (key([], [condition(id="C-9", component_ids=[], document_ids=[])]), "C-9"),
    ],
)
def test_an_entry_naming_neither_parts_nor_documents_is_refused_naming_it(
    entries: dict[str, Any], named: str
) -> None:
    message = refusal(entries)

    assert naming(named) in message
    assert "component_ids" in message
    assert "document_ids" in message


def test_an_entry_naming_only_parts_or_only_documents_builds() -> None:
    built = AnswerKey.model_validate(
        key(
            [defect(component_ids=["cmp:0001"], document_ids=[])],
            [condition(component_ids=[], document_ids=["doc:0002"])],
        )
    )

    assert built.known_defects[0].component_ids == ["cmp:0001"]
    assert built.correct_conditions[0].document_ids == ["doc:0002"]


# --- row 6: the check-pattern grammar --------------------------------------------------------


@pytest.mark.parametrize("pattern", ["rms.*", "rms.sketches.*", "hygiene.*", "rms.folders.present"])
def test_an_exact_id_and_a_family_build_on_both_lists(pattern: str) -> None:
    built = AnswerKey.model_validate(key([defect(check=pattern)], [condition(check=pattern)]))

    assert built.known_defects[0].check == pattern
    assert built.correct_conditions[0].check == pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "*",
        "rms*",
        "rms.",
        "rms.*.sketches",
        "Rms.folders",
        "rms.Folders.present",
        "",
        ".rms",
        "rms..folders",
        "rms-folders",
        "rms.*.*",
        " rms.folders",
        "rms.folders ",
    ],
)
def test_a_pattern_outside_section_3_s_grammar_is_refused_naming_the_entry_and_the_pattern(
    pattern: str,
) -> None:
    for entries, named in (
        (key([defect(id="D-2", check=pattern)]), "D-2"),
        (key([], [condition(id="C-2", check=pattern)]), "C-2"),
    ):
        message = refusal(entries)

        assert naming(named) in message
        assert repr(pattern) in message


@pytest.mark.parametrize("family", ["fastener.*", "hole.*", "fit.*", "stack.*"])
def test_a_family_covering_a_reference_keyed_check_is_refused_on_both_lists(family: str) -> None:
    """AK-4: a pass on one rule would clear a defect of another, the sibling credit 19A
    removed."""
    for entries, named in (
        (key([defect(id="D-2", check=family)]), "D-2"),
        (key([], [condition(id="C-2", check=family)]), "C-2"),
    ):
        message = refusal(entries)

        assert naming(named) in message
        assert family in message


def test_a_family_covering_no_reference_keyed_check_builds_under_a_keyed_root() -> None:
    """`fastener.head.*` covers `fastener.head.fit`, never `fastener.head_fit` (section 3)."""
    built = AnswerKey.model_validate(key([defect(check="fastener.head.*")]))

    assert built.known_defects[0].check == "fastener.head.*"


@pytest.mark.parametrize(
    ("pattern", "check", "covered"),
    [
        ("fastener.*", "fastener.head_fit", True),
        ("fastener.*", "fastener.head.fit", True),
        ("fastener.*", "fastener.a.b.c", True),
        ("fastener.*", "fastener", False),
        ("fastener.*", "fasteners.x", False),
        ("fastener.*", "fastener_x.y", False),
        ("fastener.bottoming", "fastener.bottoming", True),
        ("fastener.bottoming", "fastener.thread_match", False),
        ("rms.folders.present", "rms.folders.ordered", False),
        ("rms", "rms.folders", False),
        ("rms.folders", "rms.folders.present", False),
    ],
)
def test_pattern_covers_an_exact_id_alone_and_a_family_at_any_depth_below_its_id(
    pattern: str, check: str, covered: bool
) -> None:
    assert pattern_covers(pattern, check) is covered


@pytest.mark.parametrize(
    ("pattern", "other", "covered"),
    [
        ("rms.*", "rms.sketches.*", True),
        ("rms.*", "rms.*", True),
        ("rms.sketches.*", "rms.*", False),
        ("rms.*", "rmsx.*", False),
        ("fastener", "fastener.*", False),
        ("fastener.*", "fastener", False),
    ],
)
def test_a_family_covers_a_family_whose_id_is_or_lies_under_its_own(
    pattern: str, other: str, covered: bool
) -> None:
    """The overlap of two families (`answer-key.md` 5, condition 1) reads the same rule."""
    assert pattern_covers(pattern, other) is covered


@pytest.mark.parametrize(
    ("pattern", "family"),
    [("rms.*", True), ("rms.sketches.*", True), ("rms.folders.present", False), ("rms", False)],
)
def test_is_family_reads_a_final_dot_star(pattern: str, family: bool) -> None:
    assert is_family(pattern) is family


# --- row 7: reference shapes -----------------------------------------------------------------


def test_reference_keyed_checks_hold_section_2_5_s_eleven_checks_and_their_kinds() -> None:
    assert dict(REFERENCE_KEYED_CHECKS) == SECTION_2_5_TABLE


@pytest.mark.parametrize(("check", "kind"), sorted(SECTION_2_5_TABLE.items()))
def test_each_kind_s_shape_builds_on_each_of_its_checks(check: str, kind: str) -> None:
    element = ONE_ELEMENT_OF_EACH_KIND[kind]

    keyed_condition = condition(
        check=check,
        component_ids=["cmp:0001", "cmp:0002"],
        document_ids=["doc:0004"],
        references=[element],
    )

    built = AnswerKey.model_validate(key([keyed_defect(check, element)], [keyed_condition]))

    for entry in (built.known_defects[0], built.correct_conditions[0]):
        (reference,) = entry.references or []
        assert type(reference) is ELEMENT_MODEL_OF_EACH_KIND[kind]
        assert reference.KIND == kind


def test_references_missing_on_a_reference_keyed_check_are_refused_naming_the_kind() -> None:
    message = refusal(key([without(keyed_defect("fit.size_only", id="D-2"), "references")]))

    assert naming("D-2") in message
    assert "a fit check" in message


def test_an_empty_references_list_is_refused_naming_the_entry_and_the_kind() -> None:
    message = refusal(key([], [condition(id="C-3", check="hole.coaxiality", references=[])]))

    assert naming("C-3") in message
    assert "hole pair" in message


@pytest.mark.parametrize("references", [[ONE_ELEMENT_OF_EACH_KIND["joint"]], []])
def test_references_on_a_check_that_is_not_reference_keyed_are_refused(
    references: list[dict[str, Any]],
) -> None:
    message = refusal(key([], [condition(id="C-3", references=references)]))

    assert naming("C-3") in message
    assert "rms.folders.present" in message
    assert "not a reference-keyed check" in message


def test_references_on_a_family_are_refused() -> None:
    message = refusal(key([defect(id="D-2", check="rms.*", references=[{"recess": "x#1"}])]))

    assert naming("D-2") in message
    assert "not a reference-keyed check" in message


def test_a_joint_element_on_hole_coaxiality_is_refused_naming_the_entry_and_the_kind() -> None:
    message = refusal(
        key([keyed_defect("hole.coaxiality", ONE_ELEMENT_OF_EACH_KIND["joint"], id="D-2")])
    )

    assert naming("D-2") in message
    assert "joint" in message
    assert "hole pair" in message


@pytest.mark.parametrize(
    ("check", "wrong_kind"),
    [
        ("fastener.bottoming", "recess"),
        ("fastener.head_fit", "joint"),
        ("hole.nominal_alignment", "hole pair"),
        ("fit.size_only", "stack"),
        ("stack.worst_case", "fit"),
    ],
)
def test_an_element_of_another_kind_is_refused_naming_both_kinds(
    check: str, wrong_kind: str
) -> None:
    message = refusal(key([keyed_defect(check, ONE_ELEMENT_OF_EACH_KIND[wrong_kind], id="D-2")]))

    assert naming("D-2") in message
    assert wrong_kind in message
    assert SECTION_2_5_TABLE[check] in message


@pytest.mark.parametrize(
    "holes", [["hol:0001"], ["hol:0001", "hol:0002", "hol:0003"], ["hol:0001", "hol:0001"], []]
)
def test_a_hole_pair_that_is_not_two_distinct_holes_is_refused_naming_the_kind(
    holes: list[str],
) -> None:
    message = refusal(key([keyed_defect("hole.coaxiality", {"holes": holes}, id="D-2")]))

    assert naming("D-2") in message
    assert "hole pair" in message


@pytest.mark.parametrize("instances", [[], ["hol:0001#1", "hol:0001#1"]])
def test_joint_instances_that_are_empty_or_repeat_one_are_refused_naming_the_kind(
    instances: list[str],
) -> None:
    message = refusal(
        key([keyed_defect("hole.position_stack", {"hole_instances": instances}, id="D-2")])
    )

    assert naming("D-2") in message
    assert "joint instances" in message


def test_a_stack_with_no_contributor_is_refused_naming_the_kind() -> None:
    element = {"contributors": [], "target": THIRD_DIMENSION}

    message = refusal(key([keyed_defect("stack.worst_case", element, id="D-2")]))

    assert naming("D-2") in message
    assert "stack" in message


def test_a_stack_with_no_target_builds() -> None:
    element = {"contributors": [SHEET_DIMENSION], "target": None}

    built = AnswerKey.model_validate(key([keyed_defect("stack.worst_case", element)]))

    (reference,) = built.known_defects[0].references or []
    assert isinstance(reference, StackReference)
    assert reference.target is None


def test_a_fit_naming_one_dimension_as_bore_and_shaft_is_refused_naming_the_kind() -> None:
    """The bore against itself is no fit (`scoring.md` 2.3, US5-16): its set of references
    would be one dimension, which a finding on that dimension alone would match."""
    element = {"bore": SHEET_DIMENSION, "shaft": dict(SHEET_DIMENSION)}

    message = refusal(key([keyed_defect("fit.size_only", element, id="D-2")]))

    assert naming("D-2") in message
    assert "fit" in message


def test_an_element_of_no_kind_s_shape_is_refused_naming_the_entry() -> None:
    message = refusal(key([keyed_defect("fastener.bottoming", {"bolt": "fst:0001"}, id="D-2")]))

    assert naming("D-2") in message
    assert "references.0" in message


@pytest.mark.parametrize(
    ("check", "first", "second"),
    [
        (
            "hole.coaxiality",
            {"holes": ["hol:0001", "hol:0002"]},
            {"holes": ["hol:0002", "hol:0001"]},
        ),
        (
            "fastener.thread_match",
            ONE_ELEMENT_OF_EACH_KIND["joint"],
            dict(ONE_ELEMENT_OF_EACH_KIND["joint"]),
        ),
        ("fastener.head_fit", {"recess": "hol:0001#2"}, {"recess": "hol:0001#2"}),
        (
            "hole.nominal_alignment",
            {"hole_instances": ["hol:0001#1", "hol:0002#1"]},
            {"hole_instances": ["hol:0002#1", "hol:0001#1"]},
        ),
        (
            "fit.size_only",
            {"bore": SHEET_DIMENSION, "shaft": OTHER_DIMENSION},
            {"bore": OTHER_DIMENSION, "shaft": SHEET_DIMENSION},
        ),
        (
            "stack.worst_case",
            {"contributors": [SHEET_DIMENSION, OTHER_DIMENSION]},
            {"contributors": [OTHER_DIMENSION, SHEET_DIMENSION], "target": None},
        ),
    ],
    ids=[
        "hole pair",
        "joint",
        "recess",
        "joint instances",
        "fit, roles swapped",
        "stack, reordered",
    ],
)
def test_two_elements_equal_as_the_set_of_their_references_are_refused_naming_the_kind(
    check: str, first: dict[str, Any], second: dict[str, Any]
) -> None:
    message = refusal(key([keyed_defect(check, first, second, id="D-2")]))

    assert naming("D-2") in message
    assert SECTION_2_5_TABLE[check] in message


def test_two_elements_with_different_references_build() -> None:
    first = {"fastener": "fst:0001", "hole": "hol:0001"}
    second = {"fastener": "fst:0002", "hole": "hol:0002"}

    built = AnswerKey.model_validate(key([keyed_defect("fastener.bottoming", first, second)]))

    assert len(built.known_defects[0].references or []) == 2


def test_an_element_s_reference_set_holds_its_references_and_never_their_roles() -> None:
    """The set `benchmark/matching.py` compares a finding's references with (`scoring.md`
    2.3): a dimension as its `(document_id, sheet, annotation)` triple."""
    bore = DimensionReference(**SHEET_DIMENSION)
    shaft = DimensionReference(**OTHER_DIMENSION)
    target = DimensionReference(**THIRD_DIMENSION)
    triple = ("doc:0004", "Sheet1", "D3")

    assert JointReference(fastener="fst:0001", hole="hol:0001").reference_set() == frozenset(
        {"fst:0001", "hol:0001"}
    )
    assert RecessReference(recess="hol:0001#2").reference_set() == frozenset({"hol:0001#2"})
    assert HolePairReference(holes=["hol:0002", "hol:0001"]).reference_set() == frozenset(
        {"hol:0001", "hol:0002"}
    )
    assert JointInstancesReference(hole_instances=["hol:0001#1"]).reference_set() == frozenset(
        {"hol:0001#1"}
    )
    assert bore.triple() == triple
    assert (
        FitReference(bore=bore, shaft=shaft).reference_set()
        == FitReference(bore=shaft, shaft=bore).reference_set()
    )
    assert FitReference(bore=bore, shaft=shaft).reference_set() == frozenset(
        {triple, ("doc:0004", "Sheet1", "D4")}
    )
    assert StackReference(contributors=[bore, shaft], target=target).reference_set() == frozenset(
        {bore.triple(), shaft.triple(), target.triple()}
    )
    assert StackReference(contributors=[bore]).reference_set() == frozenset({triple})


# --- test 14: the model alone names the entry ------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        key([defect(id="D-3"), defect(id="D-3", component_ids=["cmp:0009"])]),
        key([defect(id="D-3", check="fastener.*")]),
        key([keyed_defect("hole.coaxiality", ONE_ELEMENT_OF_EACH_KIND["joint"], id="D-3")]),
    ],
    ids=["a repeated id", "a fastener.* defect", "a reference of the wrong kind's shape"],
)
def test_the_model_alone_raises_a_validation_error_naming_the_entry(
    payload: dict[str, Any],
) -> None:
    """The generator's path (RF-1): no loader is there to name the entry, so the model does."""
    assert naming("D-3") in refusal(payload)


def test_a_known_defect_built_alone_names_itself() -> None:
    with pytest.raises(ValidationError) as caught:
        KnownDefect.model_validate(without(defect(id="D-3"), "expected_status"))

    assert "D-3 states no expected_status" in messages(caught.value)


# --- test 15: the model's two derivations ----------------------------------------------------


def test_a_key_with_no_held_out_entry_holds_none_and_lists_no_model_defect() -> None:
    built = AnswerKey.model_validate(
        key([defect(), defect(id="D-2", producer="model")], [condition()])
    )

    assert built.holds_held_out() is False
    assert built.held_out_model_defect_ids() == []


def test_a_key_whose_only_held_out_entry_is_a_condition_holds_held_out_and_lists_no_defect() -> (
    None
):
    built = AnswerKey.model_validate(
        key(
            [defect(producer="model")],
            [condition(tag="held_out", held_out_against=STAMP)],
        )
    )

    assert built.holds_held_out() is True
    assert built.held_out_model_defect_ids() == []


def test_held_out_model_defect_ids_lists_held_out_model_defects_in_key_order() -> None:
    held_out = {"tag": "held_out", "held_out_against": STAMP}
    built = AnswerKey.model_validate(
        key(
            [
                defect(id="D-4", producer="model", **held_out),
                defect(id="D-2", producer="code", **held_out),
                defect(id="D-1", producer="model", **held_out),
                defect(id="D-3", producer="model"),
            ],
            [condition()],
        )
    )

    assert built.holds_held_out() is True
    assert built.held_out_model_defect_ids() == ["D-4", "D-1"]


# --- US3: the four extension lists, the model's half (T079, for T080) ------------------------


def forbidden(**fields: Any) -> dict[str, Any]:
    """A well-formed forbidden entry on the fictional bought pin, with `fields` replacing its
    defaults (`answer-key.md` 2's example)."""
    entry: dict[str, Any] = {
        "id": "FB-1",
        "checks": ["rms.*", "hygiene.*"],
        "component_ids": ["cmp:0002"],
        "document_ids": [],
        "tag": "tuned_on",
        "description": "No modelling-practice or hygiene finding on the fictional bought pin.",
    }
    entry.update(fields)
    return entry


def coverage(**fields: Any) -> dict[str, Any]:
    """A well-formed expected-coverage entry, with `fields` replacing its defaults."""
    entry: dict[str, Any] = {
        "id": "CV-1",
        "item": "interference",
        "statuses": ["unresolved", "skipped"],
        "tag": "tuned_on",
        "description": "Nothing of the fictional pins was read, so interference is not checked.",
    }
    entry.update(fields)
    return entry


def unanswerable(**fields: Any) -> dict[str, Any]:
    """A well-formed unanswerable request, with `fields` replacing its defaults."""
    entry: dict[str, Any] = {
        "id": "U-1",
        "documents": ["doc:0003"],
        "item": None,
        "tag": "tuned_on",
        "description": "The fictional bought pin has no drawing to supply.",
    }
    entry.update(fields)
    return entry


def count_rule(**fields: Any) -> dict[str, Any]:
    """A well-formed part-roles question-count rule, with `fields` replacing its defaults."""
    entry: dict[str, Any] = {
        "id": "Q-1",
        "part_roles": True,
        "min": 1,
        "max": 1,
        "tag": "tuned_on",
        "description": "The fictional part-roles question is asked exactly once.",
    }
    entry.update(fields)
    return entry


def item_rule(**fields: Any) -> dict[str, Any]:
    """A well-formed item question-count rule naming ids, with `fields` replacing its
    defaults."""
    entry: dict[str, Any] = {
        "id": "Q-2",
        "item": "interfaces.fit",
        "ids": ["cmp:0001", "cmp:0002"],
        "max": 1,
        "tag": "tuned_on",
        "description": "At most one question on the fictional pin's fit.",
    }
    entry.update(fields)
    return entry


EXTENSION_LISTS: dict[str, Callable[..., dict[str, Any]]] = {
    "forbidden": forbidden,
    "expected_coverage": coverage,
    "unanswerable_requests": unanswerable,
    "question_counts": count_rule,
}
"""Section 2.1's four other lists, each with its well-formed entry's builder."""

SIX_LISTS: dict[str, Callable[..., dict[str, Any]]] = {
    "known_defects": defect,
    "correct_conditions": condition,
    **EXTENSION_LISTS,
}


def test_a_key_holding_one_entry_of_each_of_the_six_lists_builds() -> None:
    built = AnswerKey.model_validate(
        key(
            [defect()],
            [condition()],
            forbidden=[forbidden()],
            expected_coverage=[coverage()],
            unanswerable_requests=[unanswerable()],
            question_counts=[count_rule(), item_rule()],
        )
    )

    assert [entry.id for entry in built.forbidden] == ["FB-1"]
    assert built.forbidden[0].checks == ["rms.*", "hygiene.*"]
    assert built.forbidden[0].component_ids == ["cmp:0002"]
    assert [(entry.id, entry.item, entry.statuses) for entry in built.expected_coverage] == [
        ("CV-1", "interference", ["unresolved", "skipped"])
    ]
    assert [(entry.id, entry.documents, entry.item) for entry in built.unanswerable_requests] == [
        ("U-1", ["doc:0003"], None)
    ]
    first, second = built.question_counts
    assert (first.id, first.part_roles, first.item, first.ids, first.min, first.max) == (
        "Q-1",
        True,
        None,
        [],
        1,
        1,
    )
    assert (second.id, second.part_roles, second.item, second.ids, second.min, second.max) == (
        "Q-2",
        None,
        "interfaces.fit",
        ["cmp:0001", "cmp:0002"],
        0,
        1,
    )


def test_a_key_of_six_lists_dumped_with_absent_fields_omitted_builds_again_as_itself() -> None:
    """The generator writes a key from the model: a null `item`, an absent `part_roles` or `max`
    and an empty `ids` are left out of what it writes, and what it writes reads back the same."""
    built = AnswerKey.model_validate(
        key(
            [defect()],
            [condition()],
            forbidden=[forbidden()],
            expected_coverage=[coverage()],
            unanswerable_requests=[unanswerable()],
            question_counts=[count_rule(), without(item_rule(ids=[]), "max")],
        )
    )

    dumped = built.model_dump(mode="json", exclude_none=True)

    assert AnswerKey.model_validate(dumped) == built
    assert "item" not in dumped["unanswerable_requests"][0]
    assert "ids" not in dumped["question_counts"][0]
    assert "item" not in dumped["question_counts"][0]
    assert "ids" not in dumped["question_counts"][1]
    assert "part_roles" not in dumped["question_counts"][1]
    assert "max" not in dumped["question_counts"][1]
    assert "references" not in dumped["forbidden"][0]
    assert dumped["question_counts"][0]["part_roles"] is True


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_an_unknown_field_on_each_new_entry_is_refused_naming_the_entry(name: str) -> None:
    entry = EXTENSION_LISTS[name](severity="high")

    message = refusal(key(**{name: [entry]}))

    assert naming(entry["id"]) in message
    assert "severity" in message
    assert "Extra inputs are not permitted" in message


def test_references_on_a_forbidden_entry_are_refused_naming_the_entry() -> None:
    """FR-003: a forbidden entry stays on parts or documents (section 2.4), so a forbidden
    `hole.*` on a plate covers every joint of the plate."""
    entry = forbidden(id="FB-3", references=[ONE_ELEMENT_OF_EACH_KIND["joint"]])

    message = refusal(key(forbidden=[entry]))

    assert naming("FB-3") in message
    assert "references" in message
    assert "Extra inputs are not permitted" in message


# row 3: ids and prefixes, over the six lists


@pytest.mark.parametrize(
    ("name", "entry_id"),
    [
        ("forbidden", "FB-1"),
        ("forbidden", "FB-27"),
        ("expected_coverage", "CV-1"),
        ("expected_coverage", "CV-12"),
        ("unanswerable_requests", "U-1"),
        ("unanswerable_requests", "U-30"),
        ("question_counts", "Q-1"),
        ("question_counts", "Q-11"),
    ],
)
def test_each_new_list_accepts_its_own_prefix_and_a_whole_number(name: str, entry_id: str) -> None:
    built = AnswerKey.model_validate(key(**{name: [EXTENSION_LISTS[name](id=entry_id)]}))

    assert [entry.id for entry in getattr(built, name)] == [entry_id]


@pytest.mark.parametrize(
    ("name", "entry_id"),
    [
        ("forbidden", "D-9"),
        ("forbidden", "F-1"),
        ("forbidden", "FB-0"),
        ("forbidden", "FB1"),
        ("expected_coverage", "FB-1"),
        ("expected_coverage", "C-1"),
        ("expected_coverage", "CV-01"),
        ("unanswerable_requests", "Q-1"),
        ("unanswerable_requests", "U-"),
        ("question_counts", "U-1"),
        ("question_counts", "Q-1a"),
    ],
)
def test_an_id_with_another_list_s_prefix_or_no_whole_number_is_refused_naming_it(
    name: str, entry_id: str
) -> None:
    assert naming(entry_id) in refusal(key(**{name: [EXTENSION_LISTS[name](id=entry_id)]}))


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_an_id_repeated_in_one_new_list_is_refused_naming_it(name: str) -> None:
    builder = EXTENSION_LISTS[name]
    first = builder()

    message = refusal(key(**{name: [first, builder(description="A second fictional entry.")]}))

    assert f"{first['id']} names two entries; an id is unique across the key" in message


@pytest.mark.parametrize(("first", "second"), list(combinations(SIX_LISTS, 2)))
def test_an_id_repeated_across_any_two_of_the_six_lists_is_refused_naming_it(
    first: str, second: str
) -> None:
    entry = SIX_LISTS[first]()
    repeated = SIX_LISTS[second](id=entry["id"])

    assert naming(entry["id"]) in refusal(key(**{first: [entry], second: [repeated]}))


# row 4: the tag fields on each new list


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_a_new_entry_with_no_tag_is_refused_naming_it(name: str) -> None:
    entry = without(EXTENSION_LISTS[name](), "tag")

    assert f"{entry['id']} states no tag" in refusal(key(**{name: [entry]}))


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_a_held_out_new_entry_with_no_held_out_against_is_refused_naming_it(name: str) -> None:
    entry = EXTENSION_LISTS[name](tag="held_out")

    message = refusal(key(**{name: [entry]}))

    assert naming(entry["id"]) in message
    assert "held_out_against" in message


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_a_tuned_on_new_entry_with_held_out_against_is_refused_naming_it(name: str) -> None:
    entry = EXTENSION_LISTS[name](held_out_against=STAMP)

    message = refusal(key(**{name: [entry]}))

    assert naming(entry["id"]) in message
    assert "held_out_against" in message


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_a_held_out_new_entry_with_its_stamp_builds(name: str) -> None:
    built = AnswerKey.model_validate(
        key(**{name: [EXTENSION_LISTS[name](tag="held_out", held_out_against=STAMP)]})
    )

    assert getattr(built, name)[0].held_out_against == Stamp(**STAMP)


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_a_new_entry_with_a_blank_description_is_refused_naming_it(name: str) -> None:
    entry = EXTENSION_LISTS[name](description="  ")

    message = refusal(key(**{name: [entry]}))

    assert naming(entry["id"]) in message
    assert "description" in message


# row 5 and row 6's grammar: forbidden entries


def test_a_forbidden_entry_naming_neither_parts_nor_documents_is_refused_naming_it() -> None:
    message = refusal(key(forbidden=[forbidden(id="FB-2", component_ids=[], document_ids=[])]))

    assert naming("FB-2") in message
    assert "component_ids" in message
    assert "document_ids" in message


def test_a_forbidden_entry_naming_only_parts_or_only_documents_builds() -> None:
    built = AnswerKey.model_validate(
        key(
            forbidden=[
                forbidden(),
                forbidden(id="FB-2", component_ids=[], document_ids=["doc:0003"]),
            ]
        )
    )

    assert [entry.document_ids for entry in built.forbidden] == [[], ["doc:0003"]]


def test_a_forbidden_entry_with_empty_checks_is_refused_naming_it() -> None:
    message = refusal(key(forbidden=[forbidden(id="FB-2", checks=[])]))

    assert naming("FB-2") in message
    assert "checks" in message


@pytest.mark.parametrize("pattern", ["*", "rms*", "rms.", "rms.*.sketches", "Rms.folders", ""])
def test_each_forbidden_pattern_goes_through_the_grammar_naming_the_entry_and_the_pattern(
    pattern: str,
) -> None:
    """The bad pattern is the second of two, so every pattern is read, not only the first."""
    message = refusal(key(forbidden=[forbidden(id="FB-2", checks=["hygiene.*", pattern])]))

    assert naming("FB-2") in message
    assert repr(pattern) in message


@pytest.mark.parametrize("family", ["fastener.*", "hole.*", "fit.*", "stack.*"])
def test_a_family_over_a_reference_keyed_check_builds_on_a_forbidden_entry_only(
    family: str,
) -> None:
    """AK-4 is kept to known defects and correct conditions: a forbidden entry names no
    references, so its family covers every joint of its parts (section 2.4)."""
    built = AnswerKey.model_validate(key(forbidden=[forbidden(checks=[family])]))

    assert built.forbidden[0].checks == [family]
    for entries, named in (
        (key([defect(id="D-2", check=family)]), "D-2"),
        (key([], [condition(id="C-2", check=family)]), "C-2"),
    ):
        message = refusal(entries)

        assert naming(named) in message
        assert family in message


# expected coverage: the statuses (section 2.6)


@pytest.mark.parametrize(
    "statuses",
    [[], ["issues"], ["not_reported"], ["checked", "checked"], ["unresolved", "Checked"]],
    ids=["empty", "issues", "not reported", "one value twice", "upper-case"],
)
def test_expected_coverage_statuses_outside_section_2_6_are_refused_naming_the_entry(
    statuses: list[str],
) -> None:
    message = refusal(key(expected_coverage=[coverage(id="CV-2", statuses=statuses)]))

    assert naming("CV-2") in message
    assert "statuses" in message


def test_each_of_the_four_listable_readings_builds() -> None:
    every = ["checked", "unresolved", "skipped", "out_of_scope"]

    built = AnswerKey.model_validate(key(expected_coverage=[coverage(statuses=every)]))

    assert built.expected_coverage[0].statuses == every


# unanswerable requests and question counts: the shapes (questions.md 5.1, 5.2)


@pytest.mark.parametrize(
    ("builder", "field", "value"),
    [
        pytest.param(unanswerable, "documents", "doc:0003", id="documents a string"),
        pytest.param(unanswerable, "documents", [3], id="documents of a number"),
        pytest.param(unanswerable, "item", 3, id="item a number"),
        pytest.param(item_rule, "item", ["interfaces.fit"], id="a rule's item a list"),
        pytest.param(count_rule, "part_roles", False, id="part_roles false"),
        pytest.param(count_rule, "part_roles", 1, id="part_roles 1"),
        pytest.param(count_rule, "part_roles", "true", id="part_roles a string"),
        pytest.param(item_rule, "ids", "cmp:0001", id="ids a string"),
        pytest.param(item_rule, "min", "1", id="min a string"),
        pytest.param(item_rule, "min", 1.0, id="min a float"),
        pytest.param(count_rule, "max", True, id="max a boolean"),
    ],
)
def test_a_question_entry_of_the_wrong_shape_is_refused_naming_the_entry_and_the_field(
    builder: Callable[..., dict[str, Any]], field: str, value: object
) -> None:
    entry = builder(**{field: value})
    name = "unanswerable_requests" if builder is unanswerable else "question_counts"

    message = refusal(key(**{name: [entry]}))

    assert naming(entry["id"]) in message
    assert field in message


@pytest.mark.parametrize("value", [None, "drawing.manufacturing_inputs"])
def test_an_unanswerable_request_s_item_is_a_string_or_null(value: str | None) -> None:
    built = AnswerKey.model_validate(key(unanswerable_requests=[unanswerable(item=value)]))

    assert built.unanswerable_requests[0].item == value


def test_an_unanswerable_request_with_no_item_reads_as_null() -> None:
    built = AnswerKey.model_validate(
        key(unanswerable_requests=[without(unanswerable(), "item")])
    )

    assert built.unanswerable_requests[0].item is None


@pytest.mark.parametrize(
    ("name", "entry"),
    [
        pytest.param(
            "question_counts",
            item_rule(part_roles=True),
            id="a rule with both part_roles and item",
        ),
        pytest.param("question_counts", item_rule(min=2), id="min 2"),
        pytest.param("question_counts", item_rule(min=1, max=0), id="max below min"),
        pytest.param("question_counts", count_rule(ids=["cmp:0001"]), id="ids beside part_roles"),
        pytest.param(
            "question_counts", without(without(count_rule(), "min"), "max"), id="no bounds"
        ),
        pytest.param("unanswerable_requests", unanswerable(documents=[]), id="empty documents"),
    ],
)
def test_the_combinations_questions_md_5_3_refuses_still_build_here(
    name: str, entry: dict[str, Any]
) -> None:
    """They are the loader's row 11 (T083), run through `benchmark/questions.py`, never
    restated in the model."""
    built = AnswerKey.model_validate(key(**{name: [entry]}))

    assert [one.id for one in getattr(built, name)] == [entry["id"]]


# test 15 over the new lists


@pytest.mark.parametrize("name", EXTENSION_LISTS)
def test_a_key_whose_only_held_out_entry_is_a_new_list_s_holds_held_out(name: str) -> None:
    built = AnswerKey.model_validate(
        key(
            [defect(producer="model")],
            [condition()],
            **{name: [EXTENSION_LISTS[name](tag="held_out", held_out_against=STAMP)]},
        )
    )

    assert built.holds_held_out() is True
    assert built.held_out_model_defect_ids() == []


# --- the loader (T034, for T037): `answer-key.md` 1, 4 and 6 -------------------------------------

TESTS = Path(__file__).resolve().parents[1]

SHAFT_BORE = load_package(TESTS / "golden" / "fixtures" / "shaft-bore").package
"""`build_package`'s assembly with a drawing beside it: the housing `cmp:0001` holding the tapped
hole `hole:1`, the cover `cmp:0002` holding the screw `fst:1`, and the drawing `doc:3`, whose
Sheet1 carries two PDF-ingested dimensions, `DIM-BORE` and `DIM-SHAFT`."""

PLATE = load_package(TESTS / "fixtures" / "drawings" / "plate-drawing").package
"""A natively dumped drawing, `doc:0006`, whose Sheet1 holds the display dimensions `ddm:0001`
and `ddm:0002`: native references, which resolve only once the seat validation is recorded."""

CHECKLIST = load_checklist()
WORDS = load_words()

BORE = {"document_id": "doc:3", "sheet": "Sheet1", "annotation": "DIM-BORE"}
SHAFT = {"document_id": "doc:3", "sheet": "Sheet1", "annotation": "DIM-SHAFT"}
JOINT = {"fastener": "fst:1", "hole": "hole:1"}
BOTH_PARTS = ["cmp:0001", "cmp:0002"]
FOURTH_DIMENSION = {"document_id": "doc:0004", "sheet": "Sheet1", "annotation": "D6"}

FORMAT_1_KEY: dict[str, Any] = {
    "package_id": "cover-blind-tap",
    "known_defects": [
        {
            "id": "D-1",
            "check": "fastener.bottoming",
            "component_ids": ["cmp:0003", "cmp:0004", "cmp:0005", "cmp:0006"],
            "description": (
                "M6 x 20 screws into holes drilled 14 deep with a 1.5 mm clamped stack: bottoming "
                "risk. Expected pilot outcome: unresolved with an evidence request for usable "
                "thread depth (not cleared, not demonstrated)."
            ),
        },
        {
            "id": "D-2",
            "check": "drawing.manufacturing_inputs",
            "component_ids": ["cmp:0001"],
            "description": (
                "Housing drawing specifies drill depth only for the tapped holes; usable thread "
                "depth missing."
            ),
        },
    ],
    "correct_conditions": [
        {
            "check": "fit.size_only",
            "component_ids": ["cmp:0001", "cmp:0002"],
            "description": (
                "Cover-to-housing locating spigot Ø40 H7/g6 is a correct clearance fit."
            ),
        }
    ],
}
"""`benchmarks/answer_keys/cover-blind-tap.json` as committed at `be01974`, a key in format 1:
copied here rather than read from the tree, which T040 rewrites in format 2."""


def load(path: Path, package: EvidencePackage | None = SHAFT_BORE) -> AnswerKey:
    """`path` read through the loader against `package`, with the checklist and the words."""
    return answer_key.load_answer_key(path, package=package, checklist=CHECKLIST, words=WORDS)


def load_refusal(path: Path, package: EvidencePackage | None = SHAFT_BORE) -> str:
    """The loader's refusal of `path`: an `AnswerKeyError` starting with the file's name."""
    with pytest.raises(answer_key.AnswerKeyError) as caught:
        load(path, package)
    message = str(caught.value)
    assert message.startswith(f"answer key {path.name}: "), message
    return message


def written(directory: Path, payload: dict[str, Any], name: str | None = None) -> Path:
    """`payload` written as it is, for a key `write_key` cannot build: one the model refuses."""
    path = directory / f"{name or payload['package_id']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def resolve_refusal(package: EvidencePackage, reference: dict[str, str]) -> str:
    """What `tools/refs.resolve_dimension` says when it refuses `reference` in `package`."""
    with pytest.raises(LookupError) as caught:
        resolve_dimension(package, reference)
    return str(caught.value)


def fit_condition(bore: dict[str, str], shaft: dict[str, str], **fields: Any) -> dict[str, Any]:
    """A `fit.size_only` correct condition on the housing, keyed to `bore` and `shaft`."""
    return {
        "check": "fit.size_only",
        "component_ids": ["cmp:0001"],
        "document_ids": [bore["document_id"]],
        "references": [{"bore": bore, "shaft": shaft}],
        **fields,
    }


# --- row 1: the file, the format and the model's rows ----------------------------------------


def test_an_answer_key_error_is_a_value_error() -> None:
    """The command line turns a `ValueError` into one line and exit 1 (`cli.py:260-269`)."""
    assert issubclass(answer_key.AnswerKeyError, ValueError)


def test_a_key_in_format_1_is_refused_with_section_2_1_s_sentence(tmp_path: Path) -> None:
    path = written(tmp_path, FORMAT_1_KEY)

    assert load_refusal(path, None) == f"answer key cover-blind-tap.json: {FORMAT_1_SENTENCE}"


def test_a_format_2_key_with_defects_and_conditions_loads_against_its_package(
    tmp_path: Path,
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[
            {
                "check": "fastener.bottoming",
                "component_ids": BOTH_PARTS,
                "references": [JOINT],
                "expected_status": "unresolved",
            },
            {"check": "drawing.manufacturing_inputs", "document_ids": ["doc:3"]},
        ],
        correct_conditions=[fit_condition(BORE, SHAFT)],
    )

    loaded = load(path)

    assert [defect.id for defect in loaded.known_defects] == ["D-1", "D-2"]
    assert [condition.id for condition in loaded.correct_conditions] == ["C-1"]
    assert loaded.known_defects[0].references == [JointReference(**JOINT)]
    assert loaded.ids_unchecked is None


def test_a_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "fict-key-a.json"
    path.write_text('{"key_format": 2,', encoding="utf-8")

    assert load_refusal(path).startswith("answer key fict-key-a.json: not JSON")


def test_a_missing_key_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "fict-key-a.json"

    message = load_refusal(path)

    assert message.startswith("answer key fict-key-a.json: cannot be read (")
    assert "No such file or directory" in message
    assert_names_no_folder(message, tmp_path)


def test_a_key_file_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    """A folder where the file should be: reading it raises an `OSError` on every platform
    (`IsADirectoryError`, or `PermissionError` on Windows)."""
    path = tmp_path / "fict-key-a.json"
    path.mkdir()

    message = load_refusal(path)

    assert message.startswith("answer key fict-key-a.json: cannot be read (")
    assert_names_no_folder(message, tmp_path)


def assert_names_no_folder(message: str, folder: Path) -> None:
    """The refusal names the key's file and never its folder: `str(OSError)` carries the
    absolute path the read was given, so the loader names the error by its `strerror`."""
    assert str(folder) not in message, message
    assert folder.name not in message, message


def test_a_key_file_that_is_not_utf_8_is_refused(tmp_path: Path) -> None:
    """A key saved in a legacy code page: the tolerance sign is one byte that is not UTF-8."""
    path = tmp_path / "fict-key-a.json"
    payload = key([defect(description="The fictional bore is drawn 40 ±0.01.")])
    path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("cp1252"))

    assert load_refusal(path).startswith("answer key fict-key-a.json: not UTF-8 (")


def test_a_model_row_s_refusal_is_re_raised_naming_the_entry(tmp_path: Path) -> None:
    path = written(tmp_path, key([without(defect(id="D-3"), "expected_status")]))

    assert load_refusal(path) == "answer key fict-key-a.json: D-3 states no expected_status"


def test_the_loader_refuses_an_unknown_field_at_the_key_naming_it(tmp_path: Path) -> None:
    path = written(tmp_path, key(surplus=True))

    assert load_refusal(path) == (
        "answer key fict-key-a.json: surplus: Extra inputs are not permitted"
    )


# --- row 2: the stem (its set half is slice 4's, T118 and T120) ------------------------------


def test_a_package_id_that_differs_from_the_file_s_stem_is_refused_naming_both(
    tmp_path: Path,
) -> None:
    path = write_key(tmp_path, "fict-key-a").rename(tmp_path / "fict-key-b.json")

    assert load_refusal(path) == (
        "answer key fict-key-b.json: package_id fict-key-a differs from the file's stem "
        "fict-key-b"
    )


def test_the_model_s_rows_run_before_row_2(tmp_path: Path) -> None:
    """Test 14's order (RF-1): a repeated id and a mismatched stem, named by the repeated id."""
    path = written(
        tmp_path,
        key([defect(id="D-3"), defect(id="D-3", component_ids=["cmp:0002"])]),
        name="fict-key-b",
    )

    assert load_refusal(path) == (
        "answer key fict-key-b.json: D-3 names two entries; an id is unique across the key"
    )


# --- row 6: the typo guard (AK-6) ------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        "hygeine.*",
        "hygeine.revision_present",
        "rms_.*",
        # A family's id is read with its trailing dot: `fasteners` is a goal's item, while
        # `fasteners.` starts with no goal's prefix.
        "fasteners.*",
    ],
)
@pytest.mark.parametrize("entries", ["known_defects", "correct_conditions"])
def test_a_check_under_no_report_goal_is_refused_naming_the_entry_and_the_pattern(
    tmp_path: Path, pattern: str, entries: str
) -> None:
    path = write_key(
        tmp_path, "fict-key-a", **{entries: [{"check": pattern, "component_ids": ["cmp:0001"]}]}
    )
    named = "D-1" if entries == "known_defects" else "C-1"

    assert load_refusal(path) == (
        f"answer key fict-key-a.json: {named} checks {pattern}, which falls under no goal of the "
        "report's words file, so it would grade nothing: a typo? (answer-key.md 3)"
    )


@pytest.mark.parametrize(
    "pattern",
    [
        "hygiene.*",
        "hygiene.revision_present",
        "rms.sketches.*",
        "fastener.head.*",
        "drawing.manufacturing_inputs",
        "fasteners",
    ],
)
def test_a_check_under_a_report_goal_loads(tmp_path: Path, pattern: str) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[{"check": pattern, "component_ids": ["cmp:0001"]}],
        correct_conditions=[{"check": pattern, "component_ids": ["cmp:0002"]}],
    )

    assert load(path).known_defects[0].check == pattern


# --- row 8: overlaps, through the matcher's primitives (US1-15, SC-002) ----------------------
#
# Key-only keys read with no package, so rows 13 and 14 do not run: an overlap is a property of
# two entries, whatever package they are keyed to.

FIRST_SCREW = {"fastener": "fst:0001", "hole": "hol:0001"}
SECOND_SCREW = {"fastener": "fst:0002", "hole": "hol:0002"}


@pytest.mark.parametrize(
    ("known_defects", "correct_conditions", "first", "second"),
    [
        pytest.param(
            [{"check": "hygiene.*", "component_ids": BOTH_PARTS}],
            [{"check": "hygiene.revision_present", "component_ids": ["cmp:0002"]}],
            "D-1",
            "C-1",
            id="a hygiene.* defect and a hygiene.revision_present condition on one part",
        ),
        pytest.param(
            [
                {
                    "check": "fastener.bottoming",
                    "component_ids": BOTH_PARTS,
                    "references": [FIRST_SCREW],
                },
                {
                    "check": "fastener.bottoming",
                    "component_ids": BOTH_PARTS,
                    "references": [SECOND_SCREW, FIRST_SCREW],
                },
            ],
            [],
            "D-1",
            "D-2",
            id="two bottoming defects covering one joint",
        ),
        pytest.param(
            [
                {"check": "rms.*", "component_ids": ["cmp:0001"]},
                {"check": "rms.sketches.*", "component_ids": ["cmp:0001"]},
            ],
            [],
            "D-1",
            "D-2",
            id="rms.* and rms.sketches.* defects on one part",
        ),
        pytest.param(
            [{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}],
            [{"check": "hygiene.*", "component_ids": ["cmp:0001"]}],
            "D-1",
            "C-1",
            id="a family condition against an exact defect it covers",
        ),
        pytest.param(
            [
                {
                    "check": "hygiene.revision_present",
                    "component_ids": ["cmp:0001"],
                    "document_ids": ["doc:2"],
                },
                {
                    "check": "hygiene.revision_present",
                    "component_ids": ["cmp:0002"],
                    "document_ids": ["doc:2"],
                },
            ],
            [],
            "D-1",
            "D-2",
            id="two entries sharing only a document",
        ),
    ],
)
def test_two_entries_that_overlap_are_refused_naming_both(
    tmp_path: Path,
    known_defects: list[dict[str, Any]],
    correct_conditions: list[dict[str, Any]],
    first: str,
    second: str,
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=known_defects,
        correct_conditions=correct_conditions,
        key_only=True,
    )

    assert load_refusal(path, None) == (
        f"answer key fict-key-a.json: {first} and {second} overlap: one finding could match "
        "both (answer-key.md 5)"
    )


@pytest.mark.parametrize(
    ("known_defects", "correct_conditions"),
    [
        pytest.param(
            [
                {
                    "check": "fastener.thread_match",
                    "component_ids": BOTH_PARTS,
                    "references": [FIRST_SCREW],
                },
                {
                    "check": "fastener.thread_match",
                    "component_ids": BOTH_PARTS,
                    "references": [SECOND_SCREW],
                },
            ],
            [],
            id="two thread-match defects on different pairs between the same parts",
        ),
        pytest.param(
            [
                {
                    "check": "fit.size_only",
                    "document_ids": ["doc:0004"],
                    "references": [{"bore": SHEET_DIMENSION, "shaft": OTHER_DIMENSION}],
                },
            ],
            [
                {
                    "check": "fit.size_only",
                    "document_ids": ["doc:0004"],
                    "references": [{"bore": THIRD_DIMENSION, "shaft": FOURTH_DIMENSION}],
                },
            ],
            id="a fit defect and a fit condition on one sheet with different dimension pairs",
        ),
        pytest.param(
            [
                {"check": "fastener.head", "component_ids": ["cmp:0001"]},
                {"check": "fastener.head.*", "component_ids": ["cmp:0001"]},
            ],
            [],
            id="fastener.head beside the family fastener.head.*",
        ),
        pytest.param(
            [{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}],
            [{"check": "hygiene.revision_present", "component_ids": ["cmp:0002"]}],
            id="one check on two parts",
        ),
    ],
)
def test_entries_that_do_not_overlap_load(
    tmp_path: Path,
    known_defects: list[dict[str, Any]],
    correct_conditions: list[dict[str, Any]],
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=known_defects,
        correct_conditions=correct_conditions,
        key_only=True,
    )

    assert len(load(path, None).known_defects) == len(known_defects)


# --- row 12: key-only keys (section 6; US1-16, AK-3) -----------------------------------------

RMS_PART_SHAPED: dict[str, Any] = {
    "known_defects": [
        {
            "check": "rms.grouping.all_features_in_a_group",
            "component_ids": ["cmp:0002"],
            "producer": "code",
            "expected_status": "suspected",
        },
        {
            "check": "rms.core.shell_last",
            "component_ids": ["cmp:0007"],
            "producer": "code",
            "expected_status": "demonstrated",
        },
    ],
    "correct_conditions": [{"check": "rms.folders.present", "component_ids": ["cmp:0009"]}],
}
"""A key shaped as `rms-part`'s: code-produced RMS defects and conditions on parts, its ids
naming parts no package on disk holds."""


def test_a_key_only_key_with_no_package_loads_with_its_ids_unchecked_naming_the_package(
    tmp_path: Path,
) -> None:
    path = write_key(tmp_path, "fict-rms-part", key_only=True, **RMS_PART_SHAPED)

    loaded = load(path, None)

    assert loaded.key_only is True
    assert loaded.ids_unchecked == (
        "the package fict-rms-part is not built, so this key's ids were not checked against "
        "it (answer-key.md 6)"
    )


def test_ids_unchecked_is_never_read_from_the_file(tmp_path: Path) -> None:
    path = written(tmp_path, key(key_only=True, ids_unchecked="nothing to check"))

    assert "ids_unchecked: Extra inputs are not permitted" in load_refusal(path, None)


def test_a_key_only_key_whose_package_now_exists_is_refused(tmp_path: Path) -> None:
    path = write_key(tmp_path, "fict-rms-part", key_only=True, **RMS_PART_SHAPED)

    assert load_refusal(path) == (
        "answer key fict-rms-part.json: the package now exists; remove key_only so its ids "
        "are checked"
    )


def test_a_key_without_the_marker_whose_package_is_missing_is_refused_naming_it(
    tmp_path: Path,
) -> None:
    path = write_key(tmp_path, "fict-rms-part", **RMS_PART_SHAPED)

    assert load_refusal(path, None) == (
        "answer key fict-rms-part.json: the package fict-rms-part is missing, and the key is "
        'not marked "key_only": true; a missing package is never read as an unbuilt one '
        "(answer-key.md 6)"
    )


# --- row 13: ids resolve against the package (FR-009) ----------------------------------------


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        pytest.param(
            {"check": "hygiene.revision_present", "component_ids": ["cmp:0009"]},
            "D-1 names the component cmp:0009, which is not in the package",
            id="an unknown component",
        ),
        pytest.param(
            {
                "check": "hygiene.revision_present",
                "component_ids": ["cmp:0001"],
                "document_ids": ["doc:9"],
            },
            "D-1 names the document doc:9, which is not in the package",
            id="an unknown document",
        ),
        pytest.param(
            # A document id is not a component id, as `ToolContext.entity_kind` reads it.
            {"check": "hygiene.revision_present", "component_ids": ["doc:2"]},
            "D-1 names the component doc:2, which is not in the package",
            id="a document named as a component",
        ),
        pytest.param(
            {
                "check": "fastener.bottoming",
                "component_ids": BOTH_PARTS,
                "references": [{"fastener": "fst:1", "hole": "hole:9"}],
            },
            "D-1 names the hole hole:9, which is not in the package",
            id="an unknown hole",
        ),
        pytest.param(
            {
                "check": "fastener.bottoming",
                "component_ids": BOTH_PARTS,
                "references": [{"fastener": "fst:9", "hole": "hole:1"}],
            },
            "D-1 names the fastener fst:9, which is not in the package",
            id="an unknown fastener",
        ),
        pytest.param(
            {
                "check": "hole.coaxiality",
                "component_ids": BOTH_PARTS,
                "references": [{"holes": ["hole:1", "fst:1"]}],
            },
            "D-1 names the hole fst:1, which is not in the package",
            id="a fastener named as a hole",
        ),
        pytest.param(
            {
                "check": "fastener.head_fit",
                "component_ids": ["cmp:0001"],
                "references": [{"recess": "hole:9#1"}],
            },
            "D-1 names the hole instance hole:9#1, whose hole hole:9 is not in the package",
            id="a hole instance with an unknown hole id",
        ),
        pytest.param(
            {
                "check": "hole.nominal_alignment",
                "component_ids": ["cmp:0001"],
                "references": [{"hole_instances": ["hole:1#0"]}],
            },
            "D-1 names the hole instance hole:1#0, which is not <hole id>#<n> with n a whole "
            "number from 1",
            id="a hole instance with the suffix #0",
        ),
        pytest.param(
            {
                "check": "fastener.head_fit",
                "component_ids": ["cmp:0001"],
                "references": [{"recess": "hole:1"}],
            },
            "D-1 names the hole instance hole:1, which is not <hole id>#<n> with n a whole "
            "number from 1",
            id="a hole instance with no suffix",
        ),
    ],
)
def test_an_id_the_package_does_not_hold_is_refused_naming_the_entry_and_the_id(
    tmp_path: Path, entry: dict[str, Any], reason: str
) -> None:
    path = write_key(tmp_path, "fict-key-a", known_defects=[entry])

    assert load_refusal(path) == f"answer key fict-key-a.json: {reason}"


def test_a_dimension_reference_naming_nothing_is_refused_with_resolve_dimension_s_message(
    tmp_path: Path,
) -> None:
    nothing = {**BORE, "annotation": "DIM-NONE"}
    path = write_key(tmp_path, "fict-key-a", correct_conditions=[fit_condition(nothing, SHAFT)])

    message = load_refusal(path)

    assert message.startswith("answer key fict-key-a.json: C-1 ")
    assert message.endswith(resolve_refusal(SHAFT_BORE, nothing))


def test_a_dimension_reference_naming_two_dimensions_is_refused_with_its_message(
    tmp_path: Path,
) -> None:
    doubled = SHAFT_BORE.model_copy(update={"drawings": [*SHAFT_BORE.drawings] * 2})
    path = write_key(tmp_path, "fict-key-a", correct_conditions=[fit_condition(BORE, SHAFT)])

    message = load_refusal(path, doubled)

    assert message.startswith("answer key fict-key-a.json: C-1 ")
    assert message.endswith(resolve_refusal(doubled, BORE))
    assert "ambiguous" in message


def test_a_native_dimension_reference_is_refused_while_the_seat_validation_is_not_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", False)
    bore = {"document_id": "doc:0006", "sheet": "Sheet1", "annotation": "ddm:0001"}
    shaft = {"document_id": "doc:0006", "sheet": "Sheet1", "annotation": "ddm:0002"}
    path = write_key(tmp_path, "fict-key-a", correct_conditions=[fit_condition(bore, shaft)])

    message = load_refusal(path, PLATE)

    assert message.startswith("answer key fict-key-a.json: C-1 ")
    assert message.endswith(resolve_refusal(PLATE, bore))
    assert binding.NOT_VALIDATED in message


# --- row 14: references owned by the entry's parts and documents (FR-003) --------------------


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        pytest.param(
            {"check": "fastener.bottoming", "component_ids": ["cmp:0002"], "references": [JOINT]},
            "D-1 references the hole hole:1, whose component cmp:0001 it does not name in "
            "component_ids",
            id="a hole whose component the entry does not name",
        ),
        pytest.param(
            {"check": "fastener.bottoming", "component_ids": ["cmp:0001"], "references": [JOINT]},
            "D-1 references the fastener fst:1, whose component cmp:0002 it does not name in "
            "component_ids",
            id="a fastener whose component the entry does not name",
        ),
        pytest.param(
            {
                "check": "fastener.head_fit",
                "component_ids": ["cmp:0002"],
                "references": [{"recess": "hole:1#1"}],
            },
            "D-1 references the hole instance hole:1#1, whose component cmp:0001 it does not "
            "name in component_ids",
            id="a hole instance whose component the entry does not name",
        ),
        pytest.param(
            {
                "check": "fit.size_only",
                "component_ids": ["cmp:0001"],
                "document_ids": ["doc:2"],
                "references": [{"bore": BORE, "shaft": SHAFT}],
            },
            "D-1 references the dimension doc:3 Sheet1 DIM-BORE, whose document doc:3 it does "
            "not name in document_ids",
            id="a dimension on a document the entry does not name",
        ),
    ],
)
def test_a_reference_whose_owner_the_entry_does_not_name_is_refused(
    tmp_path: Path, entry: dict[str, Any], reason: str
) -> None:
    path = write_key(tmp_path, "fict-key-a", known_defects=[entry])

    assert load_refusal(path) == f"answer key fict-key-a.json: {reason}"


# --- the order of the loader's rows: the first failing row ends the load ---------------------


def test_the_stem_is_named_before_a_typo(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[{"check": "hygeine.*", "component_ids": ["cmp:0001"]}],
    ).rename(tmp_path / "fict-key-b.json")

    assert "differs from the file's stem" in load_refusal(path)


def test_a_typo_is_named_before_an_overlap(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[
            {"check": "hygiene.*", "component_ids": ["cmp:0001"]},
            {"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]},
            {"check": "hygeine.*", "component_ids": ["cmp:0002"]},
        ],
    )

    assert "D-3 checks hygeine.*" in load_refusal(path)


def test_an_overlap_is_named_before_the_package_s_rows(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[
            {"check": "hygiene.*", "component_ids": ["cmp:0009"]},
            {"check": "hygiene.revision_present", "component_ids": ["cmp:0009"]},
        ],
    )

    assert "D-1 and D-2 overlap" in load_refusal(path)


def test_an_unknown_id_is_named_before_an_unowned_reference(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[
            {"check": "fastener.bottoming", "component_ids": ["cmp:0002"], "references": [JOINT]},
            {"check": "hygiene.revision_present", "component_ids": ["cmp:0009"]},
        ],
    )

    assert load_refusal(path) == (
        "answer key fict-key-a.json: D-2 names the component cmp:0009, which is not in the "
        "package"
    )


# --- US3: the loader's rows for the four lists (T083, for T084) ------------------------------
#
# Over `SHAFT_BORE`: the housing part `doc:2` with its two instances `cmp:0001` (holding
# `hole:1`) and `cmp:0002` (holding `fst:1`), the assembly `doc:1` and the drawing `doc:3`.

FIT = "interfaces.fit"


def test_a_format_2_key_with_every_list_loads_against_its_package(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[
            {
                "check": "fastener.bottoming",
                "component_ids": BOTH_PARTS,
                "references": [JOINT],
                "expected_status": "unresolved",
            }
        ],
        correct_conditions=[fit_condition(BORE, SHAFT)],
        forbidden=[{"checks": ["rms.*", "hygiene.*"], "component_ids": ["cmp:0002"]}],
        expected_coverage=[{"item": "interference", "statuses": ["unresolved", "skipped"]}],
        unanswerable_requests=[{"documents": ["doc:2"]}],
        question_counts=[
            {"part_roles": True, "min": 1, "max": 1},
            {"item": FIT, "ids": ["cmp:0001"], "max": 1},
        ],
    )

    loaded = load(path)

    assert [entry.id for entry in loaded.forbidden] == ["FB-1"]
    assert [entry.id for entry in loaded.expected_coverage] == ["CV-1"]
    assert [entry.id for entry in loaded.unanswerable_requests] == ["U-1"]
    assert [entry.id for entry in loaded.question_counts] == ["Q-1", "Q-2"]
    assert loaded.ids_unchecked is None


# row 6's typo guard over every forbidden pattern (AK-6)


def test_a_forbidden_pattern_under_no_report_goal_is_refused_by_the_typo_guard(
    tmp_path: Path,
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        forbidden=[{"checks": ["rms.*", "hygeine.*"], "component_ids": ["cmp:0002"]}],
    )

    assert load_refusal(path) == (
        "answer key fict-key-a.json: FB-1 checks hygeine.*, which falls under no goal of the "
        "report's words file, so it would grade nothing: a typo? (answer-key.md 3)"
    )


@pytest.mark.parametrize("checks", [["hygiene.*"], ["rms.*"], ["hygiene.*", "rms.*"]])
def test_a_forbidden_pattern_under_a_report_goal_loads(tmp_path: Path, checks: list[str]) -> None:
    path = write_key(
        tmp_path, "fict-key-a", forbidden=[{"checks": checks, "component_ids": ["cmp:0002"]}]
    )

    assert load(path).forbidden[0].checks == checks


# row 8's forbidden half: through `matching.entries_overlap` (US1-15, US3-1, SC-002)


def test_a_forbidden_family_against_a_reference_keyed_defect_on_the_same_plate_is_refused(
    tmp_path: Path,
) -> None:
    """A forbidden entry names no references, so against a joint-keyed defect only checks and
    targets are compared (`answer-key.md` 5)."""
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[
            {
                "check": "fastener.thread_match",
                "component_ids": BOTH_PARTS,
                "references": [FIRST_SCREW],
            }
        ],
        forbidden=[{"checks": ["fastener.*"], "component_ids": ["cmp:0001"]}],
        key_only=True,
    )

    assert load_refusal(path, None) == (
        "answer key fict-key-a.json: FB-1 and D-1 overlap: one finding could match both "
        "(answer-key.md 5)"
    )


def test_a_forbidden_entry_and_a_known_defect_sharing_only_a_document_are_refused(
    tmp_path: Path,
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[
            {
                "check": "hygiene.revision_present",
                "component_ids": ["cmp:0001"],
                "document_ids": ["doc:2"],
            }
        ],
        forbidden=[
            {"checks": ["hygiene.*"], "component_ids": ["cmp:0002"], "document_ids": ["doc:2"]}
        ],
        key_only=True,
    )

    assert "FB-1 and D-1 overlap" in load_refusal(path, None)


@pytest.mark.parametrize(
    ("correct_conditions", "forbidden"),
    [
        pytest.param(
            [{"check": "rms.folders.present", "component_ids": ["cmp:0002"]}],
            [{"checks": ["rms.*"], "component_ids": ["cmp:0002"]}],
            id="a forbidden rms.* against an rms.folders.present condition on one part (US3-1)",
        ),
        pytest.param(
            [],
            [
                {"checks": ["rms.*", "hygiene.*"], "component_ids": ["cmp:0002"]},
                {"checks": ["rms.sketches.*"], "component_ids": ["cmp:0002"]},
            ],
            id="two overlapping forbidden entries",
        ),
    ],
)
def test_a_forbidden_entry_may_overlap_a_condition_or_another_forbidden_entry(
    tmp_path: Path,
    correct_conditions: list[dict[str, Any]],
    forbidden: list[dict[str, Any]],
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        correct_conditions=correct_conditions,
        forbidden=forbidden,
        key_only=True,
    )

    assert len(load(path, None).forbidden) == len(forbidden)


def test_a_forbidden_family_beside_a_defect_on_other_parts_loads(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}],
        forbidden=[{"checks": ["hygiene.*"], "component_ids": ["cmp:0002"]}],
        key_only=True,
    )

    assert [entry.id for entry in load(path, None).forbidden] == ["FB-1"]


# row 9: expected coverage, one entry per goal (FR-018)


@pytest.mark.parametrize(
    ("entries", "named", "item"),
    [
        pytest.param(
            [{"item": "interference.static", "statuses": ["checked"]}],
            "CV-1",
            "interference.static",
            id="an item not in the checklist",
        ),
        pytest.param(
            [{"item": "coverage.closeout", "statuses": ["checked"]}],
            "CV-1",
            "coverage.closeout",
            id="coverage.closeout, which no goal reads",
        ),
        pytest.param(
            [
                {"item": "interfaces.fit", "statuses": ["checked"]},
                {"item": "interfaces.stack", "statuses": ["unresolved"]},
            ],
            "CV-2",
            "interfaces.stack",
            id="interfaces.fit and interfaces.stack, one goal",
        ),
    ],
)
def test_an_expected_coverage_entry_row_9_refuses_names_the_entry_and_the_item(
    tmp_path: Path, entries: list[dict[str, Any]], named: str, item: str
) -> None:
    path = write_key(tmp_path, "fict-key-a", expected_coverage=entries)

    message = load_refusal(path)

    assert f": {named} " in message and item in message, message


def test_two_entries_on_items_of_different_goals_load(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        expected_coverage=[
            {"item": "interference", "statuses": ["unresolved"]},
            {"item": "interfaces.stack", "statuses": ["skipped", "out_of_scope"]},
        ],
    )

    assert [entry.item for entry in load(path).expected_coverage] == [
        "interference",
        "interfaces.stack",
    ]


# row 10: a goal holding a known defect reads checked (FR-018, SC-001)


def test_a_goal_reading_a_known_defect_s_check_expecting_only_unresolved_is_refused(
    tmp_path: Path,
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}],
        expected_coverage=[{"item": "hygiene", "statuses": ["unresolved"]}],
    )

    message = load_refusal(path)

    assert message.endswith(
        "a goal holding a finding reads as checked (state issues); expect checked, or drop CV-1"
    ), message


def test_a_goal_reading_a_family_defect_s_check_is_refused_too(tmp_path: Path) -> None:
    """The family's id is read with its trailing dot, as the typo guard reads it."""
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[{"check": "rms.sketches.*", "component_ids": ["cmp:0001"]}],
        expected_coverage=[{"item": "modeling.resilience", "statuses": ["skipped"]}],
    )

    assert "drop CV-1" in load_refusal(path)


def test_a_goal_reading_a_known_defect_s_check_expecting_checked_too_loads(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}],
        expected_coverage=[{"item": "hygiene", "statuses": ["checked", "unresolved"]}],
    )

    assert load(path).expected_coverage[0].statuses == ["checked", "unresolved"]


def test_a_goal_reading_only_a_condition_s_check_may_expect_unresolved(tmp_path: Path) -> None:
    """A correct condition asks for no finding: row 10 reads known defects only."""
    path = write_key(
        tmp_path,
        "fict-key-a",
        correct_conditions=[{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}],
        expected_coverage=[{"item": "hygiene", "statuses": ["unresolved"]}],
    )

    assert load(path).expected_coverage[0].statuses == ["unresolved"]


# row 11: `questions.md` 5.3's refusals, through `benchmark/questions.py` (FR-019, FR-060)


@pytest.mark.parametrize(
    ("unanswerable_requests", "question_counts", "named"),
    [
        pytest.param(
            [{"documents": []}], [], ["U-1", "documents is empty"], id="U empty documents"
        ),
        pytest.param(
            [{"documents": ["cmp:0001"]}],
            [],
            ["U-1", "cmp:0001", "not a document of the package"],
            id="U an id that is not a document",
        ),
        pytest.param(
            [{"documents": ["doc:2"], "item": "fit.size_only"}],
            [],
            ["U-1", "fit.size_only", "not a checklist item"],
            id="U an item not in the checklist",
        ),
        pytest.param(
            [{"documents": ["doc:2", "doc:3", "doc:2"]}],
            [],
            ["U-1", "doc:2 twice"],
            id="U an id repeated",
        ),
        pytest.param(
            [{"documents": ["doc:2"]}, {"documents": ["doc:2", "doc:3"], "item": FIT}],
            [],
            ["U-1 and U-2", "doc:2", "count twice"],
            id="U two entries on one document, one with no item",
        ),
        pytest.param(
            [{"documents": ["doc:2"], "item": FIT}, {"documents": ["doc:2"], "item": FIT}],
            [],
            ["U-1 and U-2", "count twice"],
            id="U two entries on one document and one item",
        ),
        pytest.param(
            [], [{"max": 1}], ["Q-1", "name exactly one"], id="Q neither part_roles nor item"
        ),
        pytest.param(
            [],
            [{"part_roles": True, "item": FIT, "max": 1}],
            ["Q-1", "name exactly one"],
            id="Q both part_roles and item",
        ),
        pytest.param(
            [],
            [{"part_roles": True, "ids": ["cmp:0001"], "max": 1}],
            ["Q-1", "ids beside part_roles"],
            id="Q ids beside part_roles",
        ),
        pytest.param(
            [], [{"part_roles": True}], ["Q-1", "neither min nor max"], id="Q neither min nor max"
        ),
        pytest.param([], [{"item": FIT, "min": 2}], ["Q-1", "min 2"], id="Q min 2"),
        pytest.param(
            [], [{"item": FIT, "min": 1, "max": 0}], ["Q-1", "max 0", "below"], id="Q max below min"
        ),
        pytest.param(
            [],
            [{"item": "fit.size_only", "max": 1}],
            ["Q-1", "fit.size_only", "not a checklist item"],
            id="Q an item not in the checklist",
        ),
        pytest.param(
            [],
            [{"item": FIT, "ids": ["hole:1"], "max": 1}],
            ["Q-1", "hole:1", "not a component instance or a document"],
            id="Q an id that is not an instance or a document",
        ),
        pytest.param(
            [],
            [{"part_roles": True, "min": 1}, {"part_roles": True, "max": 1}],
            ["Q-1 and Q-2", "part-roles question"],
            id="Q two part_roles rules",
        ),
        pytest.param(
            [],
            [
                {"item": FIT, "ids": ["cmp:0001"], "max": 1},
                {"item": FIT, "ids": ["doc:2"], "max": 2},
            ],
            ["Q-1 and Q-2", FIT],
            id="Q two rules on one item whose resolved ids intersect",
        ),
        pytest.param(
            [],
            [{"item": FIT, "ids": ["cmp:0001"], "max": 1}, {"item": FIT, "max": 2}],
            ["Q-1 and Q-2", FIT],
            id="Q two rules on one item, one naming no ids",
        ),
        pytest.param(
            [{"documents": ["doc:2"]}],
            [{"item": FIT, "ids": ["cmp:0001"], "min": 1}],
            ["Q-1", "U-1", "unanswerable"],
            id="Q a min-1 rule whose oracle question an unanswerable entry matches",
        ),
    ],
)
def test_each_question_entry_refusal_of_questions_md_5_3_is_row_11(
    tmp_path: Path,
    unanswerable_requests: list[dict[str, Any]],
    question_counts: list[dict[str, Any]],
    named: list[str],
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        unanswerable_requests=unanswerable_requests,
        question_counts=question_counts,
    )

    message = load_refusal(path)

    assert all(part in message for part in named), message


@pytest.mark.parametrize(
    ("unanswerable_requests", "question_counts"),
    [
        pytest.param(
            [{"documents": ["doc:2"], "item": FIT}, {"documents": ["doc:2"], "item": "fasteners"}],
            [],
            id="two entries on one document and two items",
        ),
        pytest.param(
            [],
            [
                {"item": FIT, "ids": ["cmp:0001"], "max": 1},
                {"item": FIT, "ids": ["cmp:0002"], "max": 1},
            ],
            id="two rules on one item on disjoint instances",
        ),
        pytest.param(
            [{"documents": ["doc:2"]}],
            [{"item": FIT, "min": 1}, {"part_roles": True, "min": 1}],
            id="min-1 rules whose oracle questions no unanswerable entry matches",
        ),
        pytest.param(
            [{"documents": ["doc:2"], "item": "fasteners"}],
            [{"item": FIT, "ids": ["cmp:0001"], "min": 1}],
            id="a min-1 rule on another item than the unanswerable entry's",
        ),
    ],
)
def test_question_entries_section_5_3_allows_load(
    tmp_path: Path,
    unanswerable_requests: list[dict[str, Any]],
    question_counts: list[dict[str, Any]],
) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        unanswerable_requests=unanswerable_requests,
        question_counts=question_counts,
    )

    loaded = load(path)

    assert len(loaded.unanswerable_requests) == len(unanswerable_requests)
    assert len(loaded.question_counts) == len(question_counts)


def test_row_9_is_named_before_row_11(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        expected_coverage=[{"item": "coverage.closeout", "statuses": ["checked"]}],
        unanswerable_requests=[{"documents": []}],
    )

    message = load_refusal(path)

    assert "CV-1" in message and "U-1" not in message, message


def test_row_11_is_named_before_the_package_s_rows(tmp_path: Path) -> None:
    path = write_key(
        tmp_path,
        "fict-key-a",
        known_defects=[{"check": "hygiene.revision_present", "component_ids": ["cmp:0009"]}],
        question_counts=[{"item": FIT, "min": 2}],
    )

    message = load_refusal(path)

    assert "Q-1" in message and "cmp:0009" not in message, message


def test_question_entries_naming_ids_on_a_key_only_key_load_with_their_ids_unresolved(
    tmp_path: Path,
) -> None:
    """D7: with no package, row 11's resolution is skipped, as row 13 is."""
    path = write_key(
        tmp_path,
        "fict-rms-part",
        key_only=True,
        known_defects=RMS_PART_SHAPED["known_defects"],
        unanswerable_requests=[{"documents": ["doc:0099"]}],
        question_counts=[{"item": FIT, "ids": ["cmp:0099"], "min": 1}],
    )

    loaded = load(path, None)

    assert loaded.unanswerable_requests[0].documents == ["doc:0099"]
    assert loaded.question_counts[0].ids == ["cmp:0099"]
    assert loaded.ids_unchecked is not None


# row 13 on forbidden entries (FR-009)


@pytest.mark.parametrize(
    ("targets", "reason"),
    [
        pytest.param(
            {"component_ids": ["cmp:0009"]},
            "FB-1 names the component cmp:0009, which is not in the package",
            id="an unknown component",
        ),
        pytest.param(
            {"component_ids": [], "document_ids": ["doc:9"]},
            "FB-1 names the document doc:9, which is not in the package",
            id="an unknown document",
        ),
    ],
)
def test_a_forbidden_entry_naming_an_id_the_package_does_not_hold_is_refused(
    tmp_path: Path, targets: dict[str, list[str]], reason: str
) -> None:
    path = write_key(tmp_path, "fict-key-a", forbidden=[{"checks": ["hygiene.*"], **targets}])

    assert load_refusal(path) == f"answer key fict-key-a.json: {reason}"
