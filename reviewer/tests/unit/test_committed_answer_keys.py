"""The committed answer keys load, say what they key, and score as SC-001 and SC-002 require.

Feature 014 T039 (`contracts/answer-key.md` 7 and 9; `contracts/scoring.md` 9.2; FR-009, FR-010,
SC-001, SC-002; research AK-7, INT-15, RF-15, RF-58). Never skipped: the conftest's native-package
skip (`tests/conftest.py`) does not apply, since `rms-part` needs no package and `cover-blind-tap`'s
is committed.

1. Every key under `benchmarks/answer_keys/` loads through `load_answer_key`, against
   `benchmarks/packages/<its stem>/` when that folder holds a `package.json` and key-only
   otherwise: `cover-blind-tap` against its committed package, `rms-part` key-only.
2. `rms-part`, hand-kept: key-only, every defect produced by code at the status its rule's
   registered severity maps to through the RMS family, conditions `C-1` to `C-18` in file order,
   every entry tuned-on (AK-7), so the hand-kept key cannot drift from the rules.
3. `cover-blind-tap`, regenerated from its spec (FR-010, US5-4; T149 moved this test from the
   scorer slice's interim key): every entry tuned-on; `D-1` `fastener.bottoming`, model-produced,
   expected unresolved, over its four joints; `D-2` expected unresolved on the housing's drawing
   document; `C-1` the spigot fit, its bore and shaft references on both drawing documents.
4. SC-002 over every key: each oracle finding matches its own defect and no other, `rms-part`'s on
   its stand-in package (RF-15).
5. SC-001 over every key, on every column, through `assert_oracle_and_null`, the one assertion
   helper the golden scorecards read too; and, on every key holding no extension list (T085),
   every column the key-extensions slice adds reads `null` with its key-list reason, the two
   answer-log columns with theirs, and the call columns and tuned-on false alarms read empty, so
   a stream or a stored result the builder failed to write fails the test instead of reading "not
   assessed"; on such a key holding no correct condition either, the two condition columns read
   `null` with theirs, as `assert_oracle_and_null` expects (owner decision 65A). A key holding an
   extension list is read on those columns by `assert_oracle_and_null`, which holds each to its
   list.

Tests 4 and 5 build the oracle under the example profile (`config/standards.example.yaml`), the
profile the committed set is graded under: `mir-sitting`'s part-roles count rule (T143) has the
oracle classify its parts, and the profile moves nothing for a key with no such rule (T149).

Tests 1, 4 and 5 read every key the folder holds, so a key the generator adds is loaded, checked
and scored with no edit here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swreview.agent.checklist import load_checklist
from swreview.benchmark import runner, scorecard
from swreview.benchmark.answer_key import load_answer_key
from swreview.benchmark.answer_key_model import (
    AnswerKey,
    DimensionReference,
    FitReference,
    JointReference,
)
from swreview.checks.rms.registry import RMS_FAMILY, RULES
from swreview.checks.standards.profile import load_profile
from swreview.ir.models import EvidencePackage
from swreview.report.summary import load_words
from tests.benchmark_cases.designs import cover
from tests.support.scoring_probes import (
    COLUMNS_BY_KEY_LIST,
    NOT_ASSESSED_WITHOUT_EXTENSIONS,
    assert_oracle_and_null,
    assert_oracle_matches_only_its_own_defects,
    oracle_review,
    stand_in_package,
)

KEYS_DIR = runner.REPO_ROOT / "benchmarks" / "answer_keys"
PACKAGES_DIR = runner.REPO_ROOT / "benchmarks" / "packages"

COMMITTED_KEYS = sorted(KEYS_DIR.glob("*.json"))
"""Every committed key: the hand-kept `rms-part` and every key the generator writes."""

EXTENSION_LISTS: tuple[str, ...] = (
    "forbidden",
    "expected_coverage",
    "unanswerable_requests",
    "question_counts",
)
"""The key-extensions slice's four lists (T080)."""


def holds_an_extension_list(key_path: Path) -> bool:
    """Whether the key at `key_path`, as written, holds an entry of an extension list."""
    written = json.loads(key_path.read_text(encoding="utf-8"))
    return any(written.get(name) for name in EXTENSION_LISTS)


KEYS_WITHOUT_EXTENSIONS = [path for path in COMMITTED_KEYS if not holds_an_extension_list(path)]
"""The committed keys holding no entry of any extension list, which test 5's second half reads."""

EXAMPLE_PROFILE = load_profile(runner.REPO_ROOT / "config" / "standards.example.yaml")
"""The profile the committed set is graded under, which the oracle classifies parts with."""


def key_id(path: Path) -> str:
    return path.stem


def committed_package(key_path: Path) -> EvidencePackage | None:
    """The package a committed key is read against: `benchmarks/packages/<its stem>/` when that
    folder holds a `package.json`, or `None`, as `score_run` reads a set entry's."""
    return scorecard._package_on_disk(PACKAGES_DIR / key_path.stem)


def load_committed(key_path: Path) -> AnswerKey:
    return load_answer_key(
        key_path,
        package=committed_package(key_path),
        checklist=load_checklist(),
        words=load_words(),
    )


def review_package(key_path: Path, key: AnswerKey) -> EvidencePackage:
    """The package the oracle and null reviews are built on: the committed one, or the key-only
    key's stand-in (RF-15)."""
    package = committed_package(key_path)
    return package if package is not None else stand_in_package(key)


# --- 1: every key loads ----------------------------------------------------------------------


@pytest.mark.parametrize("key_path", COMMITTED_KEYS, ids=key_id)
def test_every_committed_key_loads_against_its_package_or_key_only(key_path: Path) -> None:
    package = committed_package(key_path)

    key = load_committed(key_path)

    assert key.package_id == key_path.stem
    assert (key.ids_unchecked is None) == (package is not None)


def test_cover_blind_tap_is_read_against_its_committed_package_and_rms_part_key_only() -> None:
    """Today's two keys are among those test 1 reads, so an empty glob cannot pass it."""
    against_a_package = {path.stem: committed_package(path) is not None for path in COMMITTED_KEYS}

    assert against_a_package["cover-blind-tap"] is True
    assert against_a_package["rms-part"] is False


# --- 2: rms-part, hand-kept and key-only -----------------------------------------------------


def test_rms_part_is_key_only() -> None:
    key = load_committed(KEYS_DIR / "rms-part.json")

    assert key.key_only is True


def test_every_rms_part_defect_is_code_produced_at_its_rule_s_registered_severity() -> None:
    key = load_committed(KEYS_DIR / "rms-part.json")

    assert [defect.id for defect in key.known_defects] == [f"D-{n}" for n in range(1, 21)]
    for defect in key.known_defects:
        severity = RULES[defect.check].severity
        assert severity is not None, f"{defect.id}: {defect.check} is coverage-only"
        status, _ = RMS_FAMILY.status_by_severity[severity]
        assert (defect.producer, defect.expected_status) == ("code", status), defect.id


def test_rms_part_s_conditions_are_c_1_to_c_18_in_file_order() -> None:
    key = load_committed(KEYS_DIR / "rms-part.json")

    assert [condition.id for condition in key.correct_conditions] == [
        f"C-{n}" for n in range(1, 19)
    ]


def test_every_rms_part_entry_is_tuned_on() -> None:
    key = load_committed(KEYS_DIR / "rms-part.json")

    entries = [*key.known_defects, *key.correct_conditions]
    assert {entry.tag for entry in entries} == {"tuned_on"}
    assert all(entry.held_out_against is None for entry in entries)


# --- 3: cover-blind-tap, regenerated from its spec -------------------------------------------


def cover_blind_tap_drawing(stem: str) -> str:
    """The id of `cover-blind-tap`'s ingested drawing named `<stem>.SLDDRW`."""
    package = committed_package(KEYS_DIR / "cover-blind-tap.json")
    assert package is not None
    (document_id,) = [
        document.document_id
        for document in package.documents
        if document.kind == "drawing" and document.file_name == f"{stem}.SLDDRW"
    ]
    return document_id


def test_cover_blind_tap_s_key_holds_d_1_d_2_and_c_1_every_entry_tuned_on() -> None:
    key = load_committed(KEYS_DIR / "cover-blind-tap.json")

    assert [defect.id for defect in key.known_defects] == ["D-1", "D-2"]
    assert [condition.id for condition in key.correct_conditions] == ["C-1"]
    assert {entry.tag for entry in [*key.known_defects, *key.correct_conditions]} == {"tuned_on"}


def test_cover_blind_tap_s_d_1_is_an_unresolved_model_bottoming_defect_over_four_joints() -> None:
    defect = load_committed(KEYS_DIR / "cover-blind-tap.json").known_defects[0]

    assert defect.check == "fastener.bottoming"
    assert (defect.expected_status, defect.producer) == ("unresolved", "model")
    assert defect.references is not None and len(defect.references) == 4
    assert all(isinstance(element, JointReference) for element in defect.references)
    assert len({element.fastener for element in defect.references}) == 4


def test_cover_blind_tap_s_d_2_is_an_unresolved_model_drawing_defect_on_the_housing_drawing() -> (
    None
):
    defect = load_committed(KEYS_DIR / "cover-blind-tap.json").known_defects[1]

    assert defect.check == "drawing.manufacturing_inputs"
    assert (defect.expected_status, defect.producer) == ("unresolved", "model")
    assert (defect.component_ids, defect.document_ids) == (
        [],
        [cover_blind_tap_drawing(cover.HOUSING_STEM)],
    )


def test_cover_blind_tap_s_c_1_is_the_spigot_fit_across_both_drawing_documents() -> None:
    (condition,) = load_committed(KEYS_DIR / "cover-blind-tap.json").correct_conditions
    housing = cover_blind_tap_drawing(cover.HOUSING_STEM)
    cover_drawing = cover_blind_tap_drawing(cover.COVER_STEM)

    assert condition.check == "fit.size_only"
    assert condition.references == [
        FitReference(
            bore=DimensionReference(document_id=housing, sheet="Sheet1", annotation="dim-1-2"),
            shaft=DimensionReference(
                document_id=cover_drawing, sheet="Sheet1", annotation="dim-1-1"
            ),
        )
    ]
    assert condition.document_ids == [housing, cover_drawing]


# --- 4: SC-002 -------------------------------------------------------------------------------


@pytest.mark.parametrize("key_path", COMMITTED_KEYS, ids=key_id)
def test_sc_002_each_oracle_finding_matches_its_own_defect_and_no_other(
    key_path: Path, tmp_path: Path
) -> None:
    key = load_committed(key_path)

    oracle = oracle_review(
        key, review_package(key_path, key), tmp_path / "oracle", profile=EXAMPLE_PROFILE
    )

    assert_oracle_matches_only_its_own_defects(key, oracle)


# --- 5: SC-001 -------------------------------------------------------------------------------


@pytest.mark.parametrize("key_path", COMMITTED_KEYS, ids=key_id)
def test_sc_001_the_oracle_scores_full_marks_and_the_null_review_none(
    key_path: Path, tmp_path: Path
) -> None:
    key = load_committed(key_path)

    assert_oracle_and_null(key, review_package(key_path, key), tmp_path, profile=EXAMPLE_PROFILE)


@pytest.mark.parametrize("key_path", KEYS_WITHOUT_EXTENSIONS, ids=key_id)
def test_sc_001_a_key_with_no_extension_list_reads_the_new_columns_not_assessed(
    key_path: Path, tmp_path: Path
) -> None:
    key = load_committed(key_path)
    assert not (
        key.forbidden or key.expected_coverage or key.unanswerable_requests or key.question_counts
    ), f"{key_path.stem} holds an extension list: test 5 reads it through assert_oracle_and_null"

    reviews = assert_oracle_and_null(
        key, review_package(key_path, key), tmp_path, profile=EXAMPLE_PROFILE
    )

    # A key holding no correct condition, a core case's among them, does not assess the two
    # condition columns either (owner decision 65A).
    expected = dict(NOT_ASSESSED_WITHOUT_EXTENSIONS)
    if not key.correct_conditions:
        expected.update(
            {
                column: scorecard.NO_CORRECT_CONDITION
                for column in COLUMNS_BY_KEY_LIST["correct_conditions"]
            }
        )
    for review, score in zip(("oracle", "null"), reviews, strict=True):
        assert score.not_assessed == expected, review
        for column in expected:
            assert getattr(score, column) is None, (review, column)
        for column in (
            "re_asks",
            "open_repeats",
            "unmatched_requests",
            "tuned_on_false_alarm_finding_ids",
        ):
            assert getattr(score, column) == [], (review, column)
