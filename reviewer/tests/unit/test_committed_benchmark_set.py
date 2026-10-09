"""The committed benchmark set holds what the study needs (feature 014 T147; `cases.md` 4, 6 and 9;
FR-028, FR-029, FR-030; SC-004; US5-4, US5-10, US5-12).

Over `benchmarks/sets/committed.json`, `pilot.json` and `pane-smoke.json` and the keys they name,
each key read through `load_answer_key` against its committed package; never skipped.

1. **The set files** (US5-10, FR-030): no absolute path and no private entry; every entry carries
   `key`, `held_out` and `design`; every `held_out` flag is its key's `holds_held_out()` (4.5,
   US5-12's committed half).
2. **FR-028 and SC-004**: at least 34 held-out model-produced defects over at least 8 designs,
   no design over a fifth of them, no package over 2, never two of one judgement family
   (`family_of`) in a package, and every one with a clean twin, as `set_summary`'s twin column
   counts it.
3. **`cases.md` 6.1's exact counts**, pinned so that growth (T248) has a pin to move: 47 entries
   in `committed.json`, 36 held-out model-produced defects, 10 designs, and 4 in each of 6.2's
   nine core designs, none in `mir`.
4. **FR-029** (RF-80): every anchor R-1 to R-8 and analyst-found AF-1 to AF-3 in some
   `committed.json` entry's `represents`; every seed and key-only entry representing an anchor
   tuned-on, read from the case specs, since a key entry carries no `represents`. The three
   entries naming an anchor beside a held-out analyst-found item pass: the rule is the item's,
   not the entry's.
5. **`cover-blind-tap`** (US5-4): in `pilot.json` and not in `committed.json`, every item
   tuned-on, `D-1` and `D-2` expected unresolved, `D-2` on a drawing document.
6. **The drawing-document rule** (6.2; CS-8), from the keys: in every case of `committed.json`,
   no other known defect or condition names a drawing-family defect's document.
7. **CS-9**, which pins owner decision 30A (T103): no core case or twin names a case file.
8. **`pane-smoke.json`** (6.1; owner decision 35A): exactly `committed.json`'s `kalo-1` and
   `kalo-fit-1` entries, as it holds them and in its order: one held-out core case and the anchor
   with a case file.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

import pytest

from swreview.agent.checklist import load_checklist
from swreview.benchmark import set_summary
from swreview.benchmark.answer_key import load_answer_key
from swreview.benchmark.answer_key_model import AnswerKey, CorrectCondition, KnownDefect
from swreview.benchmark.families import ANCHOR_FAMILY, family_of
from swreview.benchmark.sets import (
    REPO_ROOT,
    BenchmarkPackageRef,
    checkout_relative,
    load_set,
    named_paths,
)
from swreview.ir.loader import load_package
from swreview.report.summary import load_words
from tests.benchmark_cases import generate
from tests.benchmark_cases.spec import TunedOn, key_only_entries

SETS_DIR = REPO_ROOT / "benchmarks" / "sets"
SET_NAMES: tuple[str, ...] = ("committed", "pilot", "pane-smoke")
"""The three committed set files (`cases.md` 6.1)."""

CORE_DESIGNS: tuple[str, ...] = (
    "kalo",
    "tessa",
    "okta",
    "brun",
    "pelin",
    "davo",
    "rusk",
    "lori",
    "venta",
)
"""`cases.md` 6.2's nine core designs, each holding two core cases."""

ANCHORS: frozenset[str] = frozenset(value for value in ANCHOR_FAMILY if value.startswith("R-"))
"""R-1 to R-8: anchors are tuned-on (15A); analyst-found items may be held out."""

HELD_OUT_FLOOR = 34
"""FR-028's floor."""


def raw_set(name: str) -> dict[str, Any]:
    """A set file as written."""
    return json.loads((SETS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def entries(name: str) -> list[BenchmarkPackageRef]:
    """A set file's entries, read through `load_set` with the repository root."""
    return load_set(SETS_DIR / f"{name}.json", root=REPO_ROOT).packages


@pytest.fixture(scope="module")
def keys() -> dict[str, AnswerKey]:
    """Every key the three set files name, by package id, read through the key's one reader
    against its committed package."""
    checklist, words = load_checklist(), load_words()
    found: dict[str, AnswerKey] = {}
    for name in SET_NAMES:
        for entry in entries(name):
            if entry.package_id in found:
                continue
            assert entry.key is not None, entry.package_id
            package = load_package(entry.path).package
            found[entry.package_id] = load_answer_key(
                entry.key, package=package, checklist=checklist, words=words
            )
    return found


def held_out_model_defects(key: AnswerKey) -> list[KnownDefect]:
    """The key's held-out model-produced defects, as `held_out_model_defect_ids()` names them."""
    named = set(key.held_out_model_defect_ids())
    return [defect for defect in key.known_defects if defect.id in named]


def by_design(keys: dict[str, AnswerKey]) -> Counter[str]:
    """Each `committed.json` design's held-out model-produced defects, every design counted."""
    counted: Counter[str] = Counter()
    for entry in entries("committed"):
        assert entry.design is not None, entry.package_id
        counted[entry.design] += len(held_out_model_defects(keys[entry.package_id]))
    return counted


# --- 1: the set files ------------------------------------------------------------------------


def _absolute(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or bool(PureWindowsPath(path).anchor)


@pytest.mark.parametrize("name", SET_NAMES)
def test_a_committed_set_names_no_absolute_path_and_no_private_entry(name: str) -> None:
    written = raw_set(name)["packages"]

    assert written
    assert [path for entry in written for path in named_paths(entry) if _absolute(path)] == []
    assert [
        entry.package_id
        for entry in entries(name)
        if checkout_relative(entry.path, root=REPO_ROOT) is None
    ] == []
    assert [
        entry["package_id"]
        for entry in written
        if not {"key", "held_out", "design"} <= entry.keys()
    ] == []


@pytest.mark.parametrize("name", SET_NAMES)
def test_every_held_out_flag_is_its_key_s_derivation(name: str, keys: dict[str, AnswerKey]) -> None:
    assert [
        entry.package_id
        for entry in entries(name)
        if entry.held_out != keys[entry.package_id].holds_held_out()
    ] == []


# --- 2: FR-028 and SC-004 --------------------------------------------------------------------


def test_fr_028_the_floor_the_designs_and_the_caps(keys: dict[str, AnswerKey]) -> None:
    per_package = {
        entry.package_id: held_out_model_defects(keys[entry.package_id])
        for entry in entries("committed")
    }
    total = sum(len(defects) for defects in per_package.values())
    designs = by_design(keys)

    assert total >= HELD_OUT_FLOOR
    assert len([design for design, count in designs.items() if count]) >= 8
    assert [design for design, count in designs.items() if 5 * count > total] == []
    assert [package for package, defects in per_package.items() if len(defects) > 2] == []
    assert [
        package
        for package, defects in per_package.items()
        if len({family_of(defect.check) for defect in defects}) < len(defects)
    ] == []


def test_fr_028_every_held_out_model_produced_defect_has_a_clean_twin() -> None:
    summary = set_summary.summarize(SETS_DIR / "committed.json")

    twinned = sum(row.with_a_clean_twin for row in summary.rows.values())
    assert summary.held_out_model_produced >= HELD_OUT_FLOOR
    assert twinned == summary.held_out_model_produced


# --- 3: cases.md 6.1's exact counts ----------------------------------------------------------


def test_cases_md_6_1_s_counts(keys: dict[str, AnswerKey]) -> None:
    committed = entries("committed")
    designs = by_design(keys)

    assert len(committed) == 47
    assert sum(designs.values()) == 36
    assert len({entry.design for entry in committed}) == 10
    assert dict(designs) == {**{design: 4 for design in CORE_DESIGNS}, "mir": 0}


# --- 4: FR-029 -------------------------------------------------------------------------------


def test_fr_029_every_anchor_and_analyst_found_defect_is_represented() -> None:
    represented = {value for entry in entries("committed") for value in entry.represents or ()}

    assert sorted(set(ANCHOR_FAMILY) - represented) == []


def test_fr_029_every_seed_and_key_only_entry_representing_an_anchor_is_tuned_on() -> None:
    """Read from the case specs (RF-80): a key entry carries no `represents`."""
    held_out = []
    representing = 0
    for case in generate.every_spec():
        items = [
            (f"D-{number}", seed.tag, seed.represents)
            for number, seed in enumerate(case.seeds, start=1)
        ]
        items.extend(
            (entry_id, entry.tag, entry.represents) for _, entry_id, entry in key_only_entries(case)
        )
        for item_id, tag, represents in items:
            if represents in ANCHORS:
                representing += 1
                if not isinstance(tag, TunedOn):
                    held_out.append(f"{case.case_id} {item_id} ({represents})")

    assert representing
    assert held_out == []


@pytest.mark.parametrize(
    "case_id", ["kalo-contact-positive", "kalo-empty-positive", "tessa-groups"]
)
def test_fr_029_an_entry_may_name_an_anchor_beside_a_held_out_analyst_found_item(
    case_id: str, keys: dict[str, AnswerKey]
) -> None:
    (entry,) = [entry for entry in entries("committed") if entry.package_id == case_id]

    assert entry.represents is not None
    assert {value for value in entry.represents if value in ANCHORS}
    assert {value for value in entry.represents if value.startswith("AF-")}
    assert entry.held_out is True and keys[case_id].holds_held_out()


# --- 5: cover-blind-tap ----------------------------------------------------------------------


def test_cover_blind_tap_is_the_pilot_set_alone_every_item_tuned_on(
    keys: dict[str, AnswerKey],
) -> None:
    (entry,) = entries("pilot")
    key = keys["cover-blind-tap"]
    items = [
        *key.known_defects,
        *key.correct_conditions,
        *key.forbidden,
        *key.expected_coverage,
        *key.unanswerable_requests,
        *key.question_counts,
    ]
    drawings = {
        document.document_id
        for document in load_package(entry.path).package.documents
        if document.kind == "drawing"
    }

    assert entry.package_id == "cover-blind-tap"
    assert "cover-blind-tap" not in {item.package_id for item in entries("committed")}
    assert {item.tag for item in items} == {"tuned_on"}
    assert {defect.id: defect.expected_status for defect in key.known_defects} == {
        "D-1": "unresolved",
        "D-2": "unresolved",
    }
    (d_2,) = [defect for defect in key.known_defects if defect.id == "D-2"]
    assert d_2.document_ids and set(d_2.document_ids) <= drawings


# --- 6: the drawing-document rule ------------------------------------------------------------


def _reference_documents(value: Any) -> Iterator[str]:
    """Every `document_id` a reference element names, at any depth."""
    if isinstance(value, dict):
        for name, item in value.items():
            if name == "document_id" and isinstance(item, str):
                yield item
            else:
                yield from _reference_documents(item)
    elif isinstance(value, list):
        for item in value:
            yield from _reference_documents(item)


def named_documents(entry: KnownDefect | CorrectCondition) -> set[str]:
    """The documents an entry names: its `document_ids` and its references' `document_id`s."""
    named = set(entry.document_ids)
    for element in entry.references or ():
        named.update(_reference_documents(element.model_dump(mode="json")))
    return named


def test_no_other_entry_names_a_drawing_defect_s_document(keys: dict[str, AnswerKey]) -> None:
    drawing_defects = []
    broken = []
    for entry in entries("committed"):
        key = keys[entry.package_id]
        for defect in key.known_defects:
            if family_of(defect.check) != "drawing":
                continue
            drawing_defects.append(f"{entry.package_id} {defect.id}")
            for other in [*key.known_defects, *key.correct_conditions]:
                if other is defect:
                    continue
                shared = set(defect.document_ids) & named_documents(other)
                if shared:
                    broken.append(
                        f"{entry.package_id} {other.id} names {defect.id}'s document "
                        f"{', '.join(sorted(shared))}"
                    )

    assert drawing_defects
    assert broken == []


# --- 7: CS-9 ---------------------------------------------------------------------------------


def test_no_core_case_or_twin_names_a_case_file() -> None:
    committed = entries("committed")
    twinned = {entry.twin_of for entry in committed if entry.twin_of is not None}
    core = [
        entry for entry in committed if entry.twin_of is not None or entry.package_id in twinned
    ]

    assert core
    assert [entry.package_id for entry in core if entry.case_file is not None] == []


# --- 8: pane-smoke.json ----------------------------------------------------------------------


def test_pane_smoke_holds_committed_s_kalo_1_and_kalo_fit_1_as_it_holds_them() -> None:
    committed = raw_set("committed")["packages"]
    smoke = raw_set("pane-smoke")["packages"]

    assert [entry["package_id"] for entry in smoke] == ["kalo-1", "kalo-fit-1"]
    assert smoke == [
        entry for entry in committed if entry["package_id"] in ("kalo-1", "kalo-fit-1")
    ]
    kalo_1, kalo_fit_1 = smoke
    assert kalo_1["held_out"] is True and "case_file" not in kalo_1
    assert kalo_fit_1["held_out"] is False
    assert kalo_fit_1["case_file"] and kalo_fit_1["represents"] == ["R-3"]
