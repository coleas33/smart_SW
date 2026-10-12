"""The set summary's family rule (T112, for T113) and the summary's own rows (T118, for T119).

`benchmark/families.py` is the one family rule (`cases.md` 8; `generator.md` 9): the generator's
spec check row 3, the committed-set test and `swreview benchmark set-summary` all read it, and
none restates it.

1. **`family_of(check)`** reads an exact id or an `x.*` family by its first segment: `fastener`
   and `hole` are `fastener`, `fit` and `stack` are `fit_and_stack`, `interference` and
   `drawing` are their own, and every other check is `other` (modelling practice, hygiene,
   standards, provenance). A first segment that merely starts with the same letters
   (`fasteners.x`) and a judgement word in a later segment (`standards.drawing.*`) are `other`.
2. **`part_role` is a `Family` value no check reaches.** The summary counts the part-roles
   question's count rule there, a rule that names no check; the part-roles coverage row
   (`checks/part_roles.PART_ROLES_CHECK`) is `other`.
3. **`ANCHOR_FAMILY`** maps exactly the anchors R-1 to R-8 and the analyst-found AF-1 to AF-3,
   in that order, each to its family; **`FAMILY_LABELS`** gives every family's printed label
   once, in the summary's row order.
4. **The module is data only**, the standard library alone, so the generator imports it without
   loading the runner, the agent or a check (`generator.md` 9; RF-48).

`benchmark/set_summary.py` is the summary (`cases.md` 8; data-model section 5; FR-033, US5-2,
US5-12; CS-18), read here over a synthetic set in a temporary checkout of fictional packages
(`build_package`, with one ingested drawing sheet) and keys (`write_key`), a private entry
outside the checkout among them:

5. **One row per family, five columns.** Held-out model-produced is
   `AnswerKey.held_out_model_defect_ids()` (RF-67); with a clean twin, those some entry whose
   `twin_of` is their package keys as a correct condition with the same check and references;
   code-produced guards, the known defects with `producer` `code`, either tag; tuned-on items,
   every entry tagged `tuned_on`; anchors and analyst-found, the set's `represents` ids through
   `ANCHOR_FAMILY`. An item counts once in each family it names, modelling practice, hygiene and
   standards share the one `other` row, and this task's reading puts an entry naming no check
   (expected coverage, an unanswerable request, an item's count rule) on `other` while the
   part-roles question's count rule, which the contract names, counts on `part role`.
6. **Then the set.** The total against the floor of 34, met or below by n, printed and never
   refused; the largest single design's share; the packages, held out and private; and each
   held-out item whose `held_out_against` differs from `current_stamp()`, through
   `set_summary.stale_items`, the one lister, in set and key order.
7. **Refusals, each exit 1 on one line.** A `held_out` flag its key does not back, with the
   scorer's own message (`scorecard.held_out_flag_error`); a keyed entry whose key names another
   package, naming both ids (`scorecard.key_package_error`, `answer-key.md` 4 row 2's set half);
   an unreadable set, key or package, naming it.
"""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.benchmark import families, scorecard, set_summary, sets
from swreview.benchmark.answer_key_model import AnswerKey, Stamp
from swreview.benchmark.set_summary import FamilyRow
from swreview.benchmark.sets import BenchmarkPackageRef, SetError
from swreview.checks.part_roles import PART_ROLES_CHECK
from swreview.ir.loader import PACKAGE_FILE_NAME, save_package
from swreview.ir.models import EvidencePackage, SourceRef
from tests.support.answer_keys import write_key
from tests.support.drawings import SheetBuilder
from tests.support.packages import build_package

# --- family_of: an exact id or an x.* family, by its first segment -------------------------


@pytest.mark.parametrize(
    ("check", "family"),
    [
        ("fastener.bottoming", "fastener"),
        ("fastener.head.fit", "fastener"),
        ("fastener.*", "fastener"),
        ("fastener.head.*", "fastener"),
        ("hole.nominal_alignment", "fastener"),
        ("hole.*", "fastener"),
        ("fit.size_only", "fit_and_stack"),
        ("fit.*", "fit_and_stack"),
        ("stack.worst_case", "fit_and_stack"),
        ("stack.*", "fit_and_stack"),
        ("interference.static", "interference"),
        ("interference.*", "interference"),
        ("drawing.manufacturing_inputs", "drawing"),
        ("drawing.*", "drawing"),
        ("drawing", "drawing"),
    ],
)
def test_a_judgement_check_or_family_maps_to_its_family_by_its_first_segment(
    check: str, family: str
) -> None:
    assert families.family_of(check) == family


@pytest.mark.parametrize(
    "check",
    [
        "rms.*",
        "rms.sketches.fully_defined",
        "hygiene.revision_present",
        "standards.part.sketches_fully_defined",
        "provenance.x",
    ],
)
def test_modelling_practice_hygiene_standards_and_provenance_are_other(check: str) -> None:
    assert families.family_of(check) == "other"


@pytest.mark.parametrize(
    "check",
    ["fasteners.x", "holes.x", "fits.x", "stacks.x", "interferences.x", "drawings.x"],
)
def test_a_first_segment_that_merely_starts_with_a_judgement_word_is_other(check: str) -> None:
    """The first segment is compared whole, as `answer_key_model.pattern_covers` compares a
    family: `fastener.*` never covers `fasteners.x`, and `fasteners.x` is no fastener check."""
    assert families.family_of(check) == "other"


@pytest.mark.parametrize(
    "check",
    ["standards.drawing.revision_matches", "standards.drawing.*", "coverage.prerun.interference"],
)
def test_a_judgement_word_in_a_later_segment_is_other(check: str) -> None:
    """Only the first segment decides: a standards check about a drawing is a standards check."""
    assert families.family_of(check) == "other"


# --- part_role: a family no check reaches ----------------------------------------------------


def test_part_role_is_a_family_value() -> None:
    assert "part_role" in get_args(families.Family)


def test_the_part_roles_coverage_row_is_other_since_no_check_reaches_part_role() -> None:
    """The summary counts only the part-roles question's count rule on `part role` (T118); the
    part-roles coverage row is a check like any other, on the `other` row."""
    assert families.family_of(PART_ROLES_CHECK) == "other"


def test_the_families_are_the_six_in_the_summary_s_row_order() -> None:
    assert get_args(families.Family) == (
        "fastener",
        "fit_and_stack",
        "interference",
        "drawing",
        "part_role",
        "other",
    )


# --- ANCHOR_FAMILY and FAMILY_LABELS ---------------------------------------------------------


def test_anchor_family_maps_exactly_the_anchors_and_the_analyst_found_ids() -> None:
    """`cases.md` 8's anchors column: R-1 part role; R-2 drawing; R-3 fit and axial stack; R-4
    and R-5 interference; R-6, AF-1 and AF-2 fastener; R-7 and R-8 other; AF-3 interference."""
    assert families.ANCHOR_FAMILY == {
        "R-1": "part_role",
        "R-2": "drawing",
        "R-3": "fit_and_stack",
        "R-4": "interference",
        "R-5": "interference",
        "R-6": "fastener",
        "R-7": "other",
        "R-8": "other",
        "AF-1": "fastener",
        "AF-2": "fastener",
        "AF-3": "interference",
    }


def test_anchor_family_lists_r_1_to_r_8_then_af_1_to_af_3() -> None:
    assert list(families.ANCHOR_FAMILY) == [
        *(f"R-{n}" for n in range(1, 9)),
        *(f"AF-{n}" for n in range(1, 4)),
    ]


def test_family_labels_are_the_printed_labels_in_order() -> None:
    assert list(families.FAMILY_LABELS.values()) == [
        "fastener",
        "fit and axial stack",
        "interference",
        "drawing",
        "part role",
        "other",
    ]


def test_family_labels_label_every_family_once_in_the_family_order() -> None:
    assert list(families.FAMILY_LABELS) == list(get_args(families.Family))


# --- the module: data only, the standard library alone ---------------------------------------


def test_the_families_module_imports_the_standard_library_only() -> None:
    path = Path(families.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add("." * node.level + (node.module or ""))

    outside = {module for module in modules if module.split(".")[0] not in sys.stdlib_module_names}
    assert outside == set()


# --- the synthetic set the summary is read over (T118) -----------------------------------------


def triple(source: SourceRef) -> dict[str, Any]:
    """A dimension's `(document_id, sheet, annotation)`, the reference a key names it by."""
    return {
        "document_id": source.document_id,
        "sheet": source.sheet,
        "annotation": source.annotation,
    }


def plate_package() -> tuple[EvidencePackage, dict[str, Any], dict[str, Any]]:
    """`build_package` with one ingested drawing, `plate`, drawing a bore and a pin: the package
    every case here is built from, and the two dimensions its fit is keyed by."""
    builder = SheetBuilder(build_package())
    plate = builder.drawing("plate")
    builder.sheet(plate, page=1)
    bore = builder.dimension(
        plate, "Sheet1", 3.0, limits=("bilateral", 0.010, 0.0), text="3.0 +0.010/0"
    )
    pin = builder.dimension(
        plate, "Sheet1", 3.0, limits=("bilateral", 0.020, 0.014), text="3.0 +0.020/+0.014"
    )
    return builder.build(), triple(bore), triple(pin)


PACKAGE, BORE, PIN = plate_package()
PLATE = BORE["document_id"]
"""The plate's drawing document, the third document of the package."""

JOINT = {"fastener": "fst:1", "hole": "hole:1"}
"""The support package's one joint: `fst:1` on `cmp:0002` into `hole:1` on `cmp:0001`."""

BOTH_PARTS = ["cmp:0001", "cmp:0002"]
FIT = {"bore": BORE, "shaft": PIN}
OLD_STAMP = {"prompt": "a" * 64, "checklist": "b" * 64, "tools": "c" * 64}
"""A stamp no checkout's prompt, checklist and tools digest to: an item held out against it is
stale."""

PACKAGES = Path("benchmarks", "packages")
ANSWER_KEYS = Path("benchmarks", "answer_keys")
CASE_FILES = Path("benchmarks", "case_files")

KeyLists = Mapping[str, Any]
"""A key's lists as `write_key` takes them, by keyword."""


def checkout_of(tmp_path: Path) -> Path:
    """The temporary checkout every set here is read under, its root."""
    return tmp_path / "checkout"


def committed_case(
    checkout: Path, package_id: str, key: KeyLists, *, design: str, held_out: bool, **fields: Any
) -> dict[str, Any]:
    """A committed case of `checkout`: `PACKAGE` written to `benchmarks/packages/<id>`, the key
    `key`'s lists make written to `benchmarks/answer_keys/<id>.json`, and the set entry naming
    both repository-relative, with `held_out`, `design` and `fields`."""
    save_package(PACKAGE, checkout / PACKAGES / package_id)
    write_key(checkout / ANSWER_KEYS, package_id, **key)
    return {
        "package_id": package_id,
        "path": (PACKAGES / package_id).as_posix(),
        "key": (ANSWER_KEYS / f"{package_id}.json").as_posix(),
        "held_out": held_out,
        "design": design,
        **fields,
    }


def private_case(
    vault: Path, package_id: str, key: KeyLists, *, design: str, held_out: bool, **fields: Any
) -> dict[str, Any]:
    """A private case kept in `vault`, outside the checkout: its package and its key, and the set
    entry naming both absolutely."""
    package_dir = vault / "packages" / package_id
    save_package(PACKAGE, package_dir)
    key_file = write_key(vault / "keys", package_id, **key)
    return {
        "package_id": package_id,
        "path": str(package_dir),
        "key": str(key_file),
        "held_out": held_out,
        "design": design,
        **fields,
    }


def write_set(checkout: Path, entries: list[dict[str, Any]], *, name: str = "synthetic") -> Path:
    """The set file `<name>.json` in `checkout`'s sets folder, whose relative paths resolve
    against the checkout."""
    set_file = checkout / "benchmarks" / "sets" / f"{name}.json"
    set_file.parent.mkdir(parents=True, exist_ok=True)
    set_file.write_text(json.dumps({"name": name, "packages": entries}), encoding="utf-8")
    return set_file


def synthetic_set(tmp_path: Path) -> Path:
    """The synthetic set, under `checkout_of(tmp_path)`, every column's counts written beside
    the entry that makes them:

    - `brun-1` (design brun, AF-2): held-out model-produced `fastener.bottoming` on the joint
      and `hole.nominal_alignment` on `hole:1#1` (fastener) and `drawing.manufacturing_inputs`
      on the plate's drawing (drawing); a tuned-on code-produced `interference.static`;
    - `brun-1-twin`, its twin: `fastener.bottoming` on the joint as a correct condition, so
      brun-1's D-1 has a clean twin, and `hole.nominal_alignment` on `hole:1#2`, the same check
      on another item, so its D-2 has none; nothing on the drawing;
    - `kalo-1` (design kalo, R-8): held-out model-produced `fit.size_only` (fit and axial stack)
      and `drawing.manufacturing_inputs`, the latter held out against `OLD_STAMP`, so stale; a
      held-out code-produced `hygiene.revision_present`;
    - `kalo-fit-1` (design kalo, R-1 and R-3, every item tuned on): kalo-1's fit as a correct
      condition, which is no clean twin since its entry is no twin of kalo-1; a forbidden entry
      on `fastener.*` and `rms.*` and one on `fastener.*` and `hole.*`; expected coverage, an
      unanswerable request, the part-roles question's count rule and an item's; and a case file
      that is no case file, which the summary never reads;
    - `small-assembly` (private, AF-1, R-3 and R-6): a held-out code-produced
      `fastener.thread_match`, and a held-out model-produced drawing defect, a correct condition
      and a forbidden entry, each held out against `OLD_STAMP`.
    """
    checkout = checkout_of(tmp_path)
    case_file = checkout / CASE_FILES / "kalo-fit-1.json"
    case_file.parent.mkdir(parents=True)
    case_file.write_bytes(b"not a case file\n")
    entries = [
        committed_case(
            checkout,
            "brun-1",
            {
                "known_defects": [
                    {
                        "check": "fastener.bottoming",
                        "component_ids": BOTH_PARTS,
                        "references": [JOINT],
                        "tag": "held_out",
                        "expected_status": "demonstrated",
                    },
                    {
                        "check": "hole.nominal_alignment",
                        "component_ids": ["cmp:0001"],
                        "references": [{"hole_instances": ["hole:1#1"]}],
                        "tag": "held_out",
                        "expected_status": "demonstrated",
                    },
                    {
                        "check": "drawing.manufacturing_inputs",
                        "document_ids": [PLATE],
                        "tag": "held_out",
                        "expected_status": "unresolved",
                    },
                    {
                        "check": "interference.static",
                        "component_ids": BOTH_PARTS,
                        "producer": "code",
                        "expected_status": "demonstrated",
                    },
                ]
            },
            design="brun",
            held_out=True,
            represents=["AF-2"],
        ),
        committed_case(
            checkout,
            "brun-1-twin",
            {
                "correct_conditions": [
                    {
                        "check": "fastener.bottoming",
                        "component_ids": BOTH_PARTS,
                        "references": [JOINT],
                        "tag": "held_out",
                    },
                    {
                        "check": "hole.nominal_alignment",
                        "component_ids": ["cmp:0001"],
                        "references": [{"hole_instances": ["hole:1#2"]}],
                    },
                ]
            },
            design="brun",
            held_out=True,
            twin_of="brun-1",
        ),
        committed_case(
            checkout,
            "kalo-1",
            {
                "known_defects": [
                    {
                        "check": "fit.size_only",
                        "component_ids": ["cmp:0001"],
                        "document_ids": [PLATE],
                        "references": [FIT],
                        "tag": "held_out",
                    },
                    {
                        "check": "drawing.manufacturing_inputs",
                        "document_ids": [PLATE],
                        "tag": "held_out",
                        "held_out_against": OLD_STAMP,
                    },
                    {
                        "check": "hygiene.revision_present",
                        "component_ids": ["cmp:0002"],
                        "producer": "code",
                        "tag": "held_out",
                        "expected_status": "demonstrated",
                    },
                ]
            },
            design="kalo",
            held_out=True,
            represents=["R-8"],
        ),
        committed_case(
            checkout,
            "kalo-fit-1",
            {
                "correct_conditions": [
                    {
                        "check": "fit.size_only",
                        "component_ids": ["cmp:0001"],
                        "document_ids": [PLATE],
                        "references": [FIT],
                    }
                ],
                "forbidden": [
                    {"checks": ["fastener.*", "rms.*"], "component_ids": ["cmp:0002"]},
                    {"checks": ["fastener.*", "hole.*"], "component_ids": ["cmp:0001"]},
                ],
                "expected_coverage": [{"item": "interference", "statuses": ["unresolved"]}],
                "unanswerable_requests": [{"documents": [PLATE]}],
                "question_counts": [
                    {"part_roles": True, "min": 1, "max": 1},
                    {"item": "interfaces.fit", "ids": ["cmp:0001"], "max": 1},
                ],
            },
            design="kalo",
            held_out=False,
            represents=["R-1", "R-3"],
            case_file=(CASE_FILES / "kalo-fit-1.json").as_posix(),
        ),
        private_case(
            tmp_path / "vault",
            "small-assembly",
            {
                "known_defects": [
                    {
                        "check": "fastener.thread_match",
                        "component_ids": BOTH_PARTS,
                        "references": [JOINT],
                        "producer": "code",
                        "tag": "held_out",
                        "expected_status": "demonstrated",
                    },
                    {
                        "check": "drawing.manufacturing_inputs",
                        "document_ids": [PLATE],
                        "tag": "held_out",
                        "held_out_against": OLD_STAMP,
                    },
                ],
                "correct_conditions": [
                    {
                        "check": "hygiene.revision_present",
                        "component_ids": ["cmp:0001"],
                        "tag": "held_out",
                        "held_out_against": OLD_STAMP,
                    }
                ],
                "forbidden": [
                    {
                        "checks": ["rms.*"],
                        "component_ids": ["cmp:0002"],
                        "tag": "held_out",
                        "held_out_against": OLD_STAMP,
                    }
                ],
            },
            design="small-assembly",
            held_out=True,
            represents=["AF-1", "R-3", "R-6"],
        ),
    ]
    return write_set(checkout, entries)


SYNTHETIC_BLOCK = [
    "benchmark set synthetic: 5 packages (4 held out, 1 private), 3 designs",
    "fastener: held-out model-produced 2, with a clean twin 1, code-produced guards 1, "
    "tuned-on items 3, anchors and analyst-found R-6, AF-1, AF-2",
    "fit and axial stack: held-out model-produced 1, with a clean twin 0, code-produced guards 0, "
    "tuned-on items 1, anchors and analyst-found R-3",
    "interference: held-out model-produced 0, with a clean twin 0, code-produced guards 1, "
    "tuned-on items 1, anchors and analyst-found none",
    "drawing: held-out model-produced 3, with a clean twin 0, code-produced guards 0, "
    "tuned-on items 0, anchors and analyst-found none",
    "part role: held-out model-produced 0, with a clean twin 0, code-produced guards 0, "
    "tuned-on items 1, anchors and analyst-found R-1",
    "other: held-out model-produced 0, with a clean twin 0, code-produced guards 1, "
    "tuned-on items 4, anchors and analyst-found R-8",
    "held-out model-produced defects: 6 against the floor of 34: below by 28",
    "largest design share: brun 3 of 6, 50%",
    "stale: kalo-1 D-2",
    "stale: small-assembly D-2",
    "stale: small-assembly C-1",
    "stale: small-assembly FB-1",
]
"""The synthetic set's printed block, line for line (this task's wording, from `cases.md` 8's
phrases); `test_cli.py` pins the command's stdout to it."""


def summary_of(set_file: Path, tmp_path: Path, **options: Any) -> set_summary.SetSummary:
    """`set_file` summarized under `checkout_of(tmp_path)`."""
    return set_summary.summarize(set_file, root=checkout_of(tmp_path), **options)


def column(summary: set_summary.SetSummary, name: str) -> dict[str, Any]:
    """One column of the summary, family by family."""
    return {family: getattr(row, name) for family, row in summary.rows.items()}


def no_counts(**counts: int) -> dict[str, int]:
    """A count column that is zero in every family but those `counts` names."""
    return {family: counts.get(family, 0) for family in families.FAMILY_LABELS}


def summarize_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, set_file: Path, *options: str
) -> Any:
    """`swreview benchmark set-summary <set_file>`, its root the temporary checkout, as
    `benchmark score` reads the root at call time."""
    monkeypatch.setattr(sets, "REPO_ROOT", checkout_of(tmp_path))
    return CliRunner().invoke(cli.app, ["benchmark", "set-summary", str(set_file), *options])


def one_case_set(tmp_path: Path, key: KeyLists, *, held_out: bool, **fields: Any) -> Path:
    """A set of one committed case, `brun-2` of design brun, its key `key`'s lists."""
    checkout = checkout_of(tmp_path)
    entry = committed_case(checkout, "brun-2", key, design="brun", held_out=held_out, **fields)
    return write_set(checkout, [entry], name="one-case")


# --- 5: one row per family, five columns ---------------------------------------------------


def test_the_summary_holds_one_row_per_family_in_the_label_order(tmp_path: Path) -> None:
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert list(summary.rows) == list(families.FAMILY_LABELS)
    assert summary.name == "synthetic"


def test_held_out_model_produced_is_each_key_s_held_out_model_defect_ids_by_family(
    tmp_path: Path,
) -> None:
    """brun-1's three, kalo-1's two (its stale drawing defect among them) and the private
    entry's drawing defect; never a code-produced defect, held out or not, and never a
    condition."""
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert column(summary, "held_out_model_produced") == no_counts(
        fastener=2, fit_and_stack=1, drawing=3
    )
    assert summary.held_out_model_produced == 6


def test_with_a_clean_twin_counts_a_held_out_defect_its_twin_keys_as_a_correct_condition(
    tmp_path: Path,
) -> None:
    """Only brun-1's D-1: its D-2's twin condition covers another hole instance, its D-3 has no
    twin condition, and kalo-1's fit is keyed as a condition by an entry that is no twin of
    kalo-1."""
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert column(summary, "with_a_clean_twin") == no_counts(fastener=1)


def test_a_twin_condition_naming_the_fit_s_dimensions_the_other_way_round_is_its_clean_twin(
    tmp_path: Path,
) -> None:
    """A fit's roles are never compared (`scoring.md` 2.3): bore and shaft swapped name the same
    item, so the twin keys the same references."""
    checkout = checkout_of(tmp_path)
    fit = {
        "check": "fit.size_only",
        "component_ids": ["cmp:0001"],
        "document_ids": [PLATE],
        "tag": "held_out",
    }
    entries = [
        committed_case(
            checkout,
            "pelin-1",
            {"known_defects": [{**fit, "references": [FIT]}]},
            design="pelin",
            held_out=True,
        ),
        committed_case(
            checkout,
            "pelin-1-twin",
            {"correct_conditions": [{**fit, "references": [{"bore": PIN, "shaft": BORE}]}]},
            design="pelin",
            held_out=True,
            twin_of="pelin-1",
        ),
    ]

    summary = summary_of(write_set(checkout, entries), tmp_path)

    assert column(summary, "with_a_clean_twin") == no_counts(fit_and_stack=1)


def test_code_produced_guards_count_known_defects_of_producer_code_either_tag(
    tmp_path: Path,
) -> None:
    """brun-1's tuned-on interference, kalo-1's held-out hygiene defect and the private
    entry's held-out thread match."""
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert column(summary, "code_produced_guards") == no_counts(
        fastener=1, interference=1, other=1
    )


def test_tuned_on_items_count_every_entry_tagged_tuned_on_in_each_family_it_names(
    tmp_path: Path,
) -> None:
    """brun-1's interference defect, the twin's other-instance condition, and kalo-fit-1's
    seven entries: its fit condition, its two forbidden entries (fastener and other; fastener
    once), its coverage, unanswerable request and item count rule (other) and its part-roles
    count rule (part role). A held-out item is never tuned on."""
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert column(summary, "tuned_on_items") == no_counts(
        fastener=3, fit_and_stack=1, interference=1, part_role=1, other=4
    )


def test_anchors_and_analyst_found_are_the_set_s_represents_ids_by_family_each_once(
    tmp_path: Path,
) -> None:
    """In `ANCHOR_FAMILY`'s order, whatever the set's: R-3, named by two entries, once."""
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert column(summary, "anchors") == {
        "fastener": ("R-6", "AF-1", "AF-2"),
        "fit_and_stack": ("R-3",),
        "interference": (),
        "drawing": (),
        "part_role": ("R-1",),
        "other": ("R-8",),
    }


def test_the_rows_are_family_rows(tmp_path: Path) -> None:
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert summary.rows["fastener"] == FamilyRow(
        held_out_model_produced=2,
        with_a_clean_twin=1,
        code_produced_guards=1,
        tuned_on_items=3,
        anchors=("R-6", "AF-1", "AF-2"),
    )


def test_an_item_naming_two_families_is_counted_once_in_each(tmp_path: Path) -> None:
    """A forbidden entry on `fastener.*` and `rms.*` counts in fastener and in other; one on
    `fastener.*` and `hole.*` names one family twice and counts there once."""
    set_file = one_case_set(
        tmp_path,
        {
            "forbidden": [
                {"checks": ["fastener.*", "rms.*"], "component_ids": ["cmp:0002"]},
                {"checks": ["fastener.*", "hole.*"], "component_ids": ["cmp:0001"]},
            ]
        },
        held_out=False,
    )

    summary = summary_of(set_file, tmp_path)

    assert column(summary, "tuned_on_items") == no_counts(fastener=2, other=1)


def test_modelling_practice_hygiene_and_standards_share_the_one_other_row(tmp_path: Path) -> None:
    set_file = one_case_set(
        tmp_path,
        {
            "known_defects": [
                {"check": check, "component_ids": ["cmp:0001"], "producer": "code"}
                for check in (
                    "rms.sketches.fully_defined",
                    "hygiene.revision_present",
                    "standards.part.sketches_fully_defined",
                )
            ]
        },
        held_out=False,
    )

    summary = summary_of(set_file, tmp_path)

    assert column(summary, "code_produced_guards") == no_counts(other=3)
    assert column(summary, "tuned_on_items") == no_counts(other=3)


def test_an_entry_naming_no_check_counts_on_other_while_a_part_roles_count_rule_counts_on_part_role(
    tmp_path: Path,
) -> None:
    """`cases.md` 8 names only the part-roles question's count rule, on `part role`; this
    task's reading puts expected coverage, an unanswerable request and an item's count rule,
    which name no check, on `other`, never on the family their item's words might suggest."""
    set_file = one_case_set(
        tmp_path,
        {
            "expected_coverage": [{"item": "interfaces.fit", "statuses": ["unresolved"]}],
            "unanswerable_requests": [{"documents": [PLATE], "item": "interfaces.fit"}],
            "question_counts": [
                {"item": "fasteners", "ids": ["cmp:0001"], "max": 1},
                {"part_roles": True, "min": 1, "max": 1},
            ],
        },
        held_out=False,
    )

    summary = summary_of(set_file, tmp_path)

    assert column(summary, "tuned_on_items") == no_counts(other=3, part_role=1)


@pytest.mark.parametrize(("anchor", "family"), list(families.ANCHOR_FAMILY.items()))
def test_an_anchor_maps_to_its_family(tmp_path: Path, anchor: str, family: str) -> None:
    set_file = one_case_set(
        tmp_path,
        {"forbidden": [{"checks": ["rms.*"], "component_ids": ["cmp:0002"]}]},
        held_out=False,
        represents=[anchor],
    )

    summary = summary_of(set_file, tmp_path)

    assert column(summary, "anchors") == {
        row: (anchor,) if row == family else () for row in families.FAMILY_LABELS
    }


# --- 6: the floor, the largest design, the packages and the stale items -----------------------


@pytest.mark.parametrize(
    ("defects", "line"),
    [
        (33, "held-out model-produced defects: 33 against the floor of 34: below by 1"),
        (34, "held-out model-produced defects: 34 against the floor of 34: met"),
        (35, "held-out model-produced defects: 35 against the floor of 34: met"),
    ],
)
def test_the_total_is_read_against_the_floor_of_34(
    tmp_path: Path, defects: int, line: str
) -> None:
    set_file = one_case_set(
        tmp_path,
        {
            "known_defects": [
                {"check": f"hygiene.rule_{n}", "component_ids": ["cmp:0001"], "tag": "held_out"}
                for n in range(1, defects + 1)
            ]
        },
        held_out=True,
    )

    summary = summary_of(set_file, tmp_path)

    assert summary.held_out_model_produced == defects
    assert line in set_summary.render_summary(summary).splitlines()


def test_set_summary_s_floor_is_34() -> None:
    assert set_summary.HELD_OUT_FLOOR == 34


def test_a_count_below_the_floor_is_printed_and_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compare refuses the verdict below the floor (`verdict.md` 7 row 4); the summary only
    prints the shortfall."""
    result = summarize_cli(monkeypatch, tmp_path, synthetic_set(tmp_path))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert (
        "held-out model-produced defects: 6 against the floor of 34: below by 28"
        in result.stdout.splitlines()
    )


def test_the_largest_single_design_s_share_of_held_out_model_produced_defects(
    tmp_path: Path,
) -> None:
    """brun's three of six; kalo's two and the private design's one are smaller."""
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert summary.designs == {"brun": 3, "kalo": 2, "small-assembly": 1}
    assert summary.largest_design == ("brun", 3)
    assert "largest design share: brun 3 of 6, 50%" in set_summary.render_summary(
        summary
    ).splitlines()


def test_two_designs_holding_the_most_name_the_first_in_set_order(tmp_path: Path) -> None:
    checkout = checkout_of(tmp_path)
    defect = {
        "known_defects": [
            {"check": "hygiene.rule_1", "component_ids": ["cmp:0001"], "tag": "held_out"}
        ]
    }
    entries = [
        committed_case(checkout, "venta-1", defect, design="venta", held_out=True),
        committed_case(checkout, "lori-1", defect, design="lori", held_out=True),
    ]

    summary = summary_of(write_set(checkout, entries), tmp_path)

    assert summary.largest_design == ("venta", 1)
    assert "largest design share: venta 1 of 2, 50%" in set_summary.render_summary(
        summary
    ).splitlines()


def test_a_set_holding_no_held_out_model_produced_defect_names_no_largest_share(
    tmp_path: Path,
) -> None:
    """A set of tuned-on items only, as `pilot.json` is: no share to divide, so none is named."""
    set_file = one_case_set(
        tmp_path,
        {"forbidden": [{"checks": ["rms.*"], "component_ids": ["cmp:0002"]}]},
        held_out=False,
    )

    summary = summary_of(set_file, tmp_path)
    lines = set_summary.render_summary(summary).splitlines()

    assert summary.largest_design is None
    assert "held-out model-produced defects: 0 against the floor of 34: below by 34" in lines
    assert "largest design share: none" in lines


def test_the_packages_held_out_and_private_the_private_entry_counted(tmp_path: Path) -> None:
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert (summary.packages, summary.held_out, summary.private) == (5, 4, 1)
    assert set_summary.render_summary(summary).splitlines()[0] == (
        "benchmark set synthetic: 5 packages (4 held out, 1 private), 3 designs"
    )


def test_each_held_out_item_off_the_current_stamp_is_listed_stale(tmp_path: Path) -> None:
    """kalo-1's drawing defect, then the private entry's defect, condition and forbidden entry:
    every held-out item, in set and key order; a held-out item stamped now is not stale."""
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert summary.stale == [
        "kalo-1 D-2",
        "small-assembly D-2",
        "small-assembly C-1",
        "small-assembly FB-1",
    ]
    assert set_summary.render_summary(summary).splitlines()[-4:] == [
        f"stale: {item}" for item in summary.stale
    ]


def test_the_rendered_block_is_the_synthetic_block(tmp_path: Path) -> None:
    summary = summary_of(synthetic_set(tmp_path), tmp_path)

    assert set_summary.render_summary(summary).splitlines() == SYNTHETIC_BLOCK


def test_stale_items_lists_package_and_id_in_set_and_key_order_over_defects_and_conditions(
    tmp_path: Path,
) -> None:
    """Keys in the order given, the set's; each key's defects before its conditions; only an
    item held out against another stamp than the one given, never a tuned-on one."""
    other = {"prompt": "d" * 64, "checklist": "e" * 64, "tools": "f" * 64}

    def item(check: str, against: dict[str, str] | None = None) -> dict[str, Any]:
        """An entry on the housing, held out against `against`, or tuned on without one."""
        tag = {} if against is None else {"tag": "held_out", "held_out_against": against}
        return {"check": check, "component_ids": ["cmp:0001"], **tag}

    lists = {
        "known_defects": [
            item("hygiene.rule_1", OLD_STAMP),
            item("hygiene.rule_2"),
            item("hygiene.rule_3", other),
        ],
        "correct_conditions": [item("hygiene.rule_4", OLD_STAMP)],
    }
    keys = [
        AnswerKey.model_validate_json(write_key(tmp_path, package_id, **lists).read_text("utf-8"))
        for package_id in ("tessa-1", "okta-1")
    ]

    assert set_summary.stale_items(keys, Stamp.model_validate(other)) == [
        "tessa-1 D-1",
        "tessa-1 C-1",
        "okta-1 D-1",
        "okta-1 C-1",
    ]
    assert set_summary.stale_items(keys, Stamp.model_validate(OLD_STAMP)) == [
        "tessa-1 D-3",
        "okta-1 D-3",
    ]


# --- 7: the refusals, each exit 1 on one line ---------------------------------------------------


def test_a_flag_that_disagrees_with_its_key_exits_1_with_the_scorer_s_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`test_scorecard.py` 10's message, one writer (`scorecard.held_out_flag_error`), naming
    the package (US5-12)."""
    set_file = one_case_set(
        tmp_path,
        {"known_defects": [{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}]},
        held_out=True,
    )
    message = (
        "brun-2: the set marks it held_out=true, but its key holds 0 held-out items; the flag "
        "is derived from the key"
    )

    with pytest.raises(ValueError) as caught:
        summary_of(set_file, tmp_path)
    result = summarize_cli(monkeypatch, tmp_path, set_file)

    assert str(caught.value) == message
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"error: ValueError: {message}\n"


def key_naming_another_package(tmp_path: Path, *, held_out: bool) -> Path:
    """A keyed set whose one entry, `kalo-2`, names as its key `brun-2.json`, whose
    `package_id` is `brun-2`: its own stem, so the key loader's stem half passes."""
    checkout = checkout_of(tmp_path)
    save_package(PACKAGE, checkout / PACKAGES / "kalo-2")
    write_key(
        checkout / ANSWER_KEYS,
        "brun-2",
        known_defects=[{"check": "hygiene.revision_present", "component_ids": ["cmp:0001"]}],
    )
    entry = {
        "package_id": "kalo-2",
        "path": (PACKAGES / "kalo-2").as_posix(),
        "key": (ANSWER_KEYS / "brun-2.json").as_posix(),
        "held_out": held_out,
        "design": "kalo",
    }
    return write_set(checkout, [entry], name="crossed")


ANOTHER_PACKAGE = "kalo-2: its key brun-2.json names package brun-2, not the set entry's kalo-2"
"""`answer-key.md` 4 row 2's set half: both ids and the key file's name, never its folder."""


def test_a_keyed_entry_whose_key_names_another_package_exits_1_naming_both_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_file = key_naming_another_package(tmp_path, held_out=False)

    with pytest.raises(ValueError) as caught:
        summary_of(set_file, tmp_path)
    result = summarize_cli(monkeypatch, tmp_path, set_file)

    assert str(caught.value) == ANOTHER_PACKAGE
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"error: ValueError: {ANOTHER_PACKAGE}\n"


def test_the_key_s_package_is_checked_before_the_flag(tmp_path: Path) -> None:
    """Once the key loads, its package first: a flag read against another package's key would
    name the wrong refusal."""
    set_file = key_naming_another_package(tmp_path, held_out=True)

    with pytest.raises(ValueError) as caught:
        summary_of(set_file, tmp_path)

    assert str(caught.value) == ANOTHER_PACKAGE


def test_key_package_error_is_none_when_the_key_names_the_entry_s_package(tmp_path: Path) -> None:
    key_file = write_key(tmp_path / "keys", "kalo-2", known_defects=[])
    key = AnswerKey.model_validate_json(key_file.read_text("utf-8"))
    keyed = BenchmarkPackageRef(package_id="kalo-2", path=tmp_path / "kalo-2", key=key_file)
    keyless = BenchmarkPackageRef(package_id="kalo-2", path=tmp_path / "kalo-2")

    assert scorecard.key_package_error(keyed, key) is None
    assert scorecard.key_package_error(keyless, key) is None
    assert scorecard.key_package_error(keyed.model_copy(update={"package_id": "kalo-3"}), key) == (
        "kalo-3: its key kalo-2.json names package kalo-2, not the set entry's kalo-3"
    )


def unreadable_set(tmp_path: Path) -> Path:
    return checkout_of(tmp_path) / "benchmarks" / "sets" / "missing.json"


def unreadable_key(tmp_path: Path) -> Path:
    set_file = one_case_set(tmp_path, {}, held_out=False)
    (checkout_of(tmp_path) / ANSWER_KEYS / "brun-2.json").write_text("not json", "utf-8")
    return set_file


def malformed_package(tmp_path: Path) -> Path:
    set_file = one_case_set(tmp_path, {}, held_out=False)
    (checkout_of(tmp_path) / PACKAGES / "brun-2" / PACKAGE_FILE_NAME).write_text("{}", "utf-8")
    return set_file


def missing_package(tmp_path: Path) -> Path:
    set_file = one_case_set(tmp_path, {}, held_out=False)
    (checkout_of(tmp_path) / PACKAGES / "brun-2" / PACKAGE_FILE_NAME).unlink()
    return set_file


@pytest.mark.parametrize(
    ("make", "line"),
    [
        (unreadable_set, "error: SetError: benchmark set missing.json: cannot be read ("),
        (unreadable_key, "error: AnswerKeyError: answer key brun-2.json: not JSON ("),
        (malformed_package, "error: ValueError: brun-2: its package cannot be read ("),
        (missing_package, "error: ValueError: brun-2: its package cannot be read (no package.json"),
    ],
    ids=["set", "key", "malformed package", "missing package"],
)
def test_an_unreadable_set_key_or_package_exits_1_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make: Any, line: str
) -> None:
    result = summarize_cli(monkeypatch, tmp_path, make(tmp_path))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith(line)
    assert result.stderr.count("\n") == 1


# --- keyless sets: their keys through --answer-keys -------------------------------------------


def keyless_set(tmp_path: Path) -> tuple[Path, Path]:
    """A set written before feature 014: one entry, `brun-3`, naming no key and no design, and
    the directory its key lies in, `<keys>/brun-3.json`."""
    checkout = checkout_of(tmp_path)
    save_package(PACKAGE, checkout / PACKAGES / "brun-3")
    keys = tmp_path / "keys"
    write_key(
        keys,
        "brun-3",
        known_defects=[
            {"check": "drawing.manufacturing_inputs", "document_ids": [PLATE], "tag": "held_out"}
        ],
    )
    entry = {"package_id": "brun-3", "path": (PACKAGES / "brun-3").as_posix(), "held_out": True}
    return write_set(checkout, [entry], name="keyless"), keys


def test_a_keyless_set_reads_its_keys_from_answer_keys_and_an_entry_naming_no_design_is_its_own(
    tmp_path: Path,
) -> None:
    """`sets.key_path`'s rule (T115): `<answer_keys>/<package_id>.json`. A set written before
    this feature names no design, so each entry stands for its own, by its package id."""
    set_file, keys = keyless_set(tmp_path)

    summary = summary_of(set_file, tmp_path, answer_keys=keys)

    assert column(summary, "held_out_model_produced") == no_counts(drawing=1)
    assert summary.designs == {"brun-3": 1}
    assert "largest design share: brun-3 1 of 1, 100%" in set_summary.render_summary(
        summary
    ).splitlines()


def test_a_keyless_set_given_no_answer_keys_is_refused_naming_the_option(tmp_path: Path) -> None:
    set_file, _ = keyless_set(tmp_path)

    with pytest.raises(SetError) as caught:
        summary_of(set_file, tmp_path)

    assert "--answer-keys" in str(caught.value)
