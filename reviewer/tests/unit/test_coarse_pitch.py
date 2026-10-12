"""The coarse pitch table and its classifier (feature 010 amendment 2026-10-08, T112;
`contracts/fasteners.md` sections 8.1, 8.3 and 8.9, `contracts/coarse-pitch.json`).

The shop uses coarse threads, so a fine pitch is flagged for the engineer to confirm (the
owner's decision 50A). Every thread designation lands in exactly one class of section 8.1:
unreadable, pipe, unknown size, fine-only size, coarse, fine or non-standard. Three rules carry
the traps the tests pin: the size is matched first and then the pitch, so `M10x1.25` is fine
although 1.25 is M8's coarse pitch; a metric thread written with no pitch is the coarse one,
by ISO 965-1's own designation rule; and an inch pitch compares as threads per inch within
0.01, never as rounded millimetres. The table is data, pinned key for key to the contract file
that the extractor's copy is pinned to as well once T115 lands it (research R2.26, the pattern
of R2.11).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from swreview.checks import coarse_pitch, fastener
from swreview.checks.coarse_pitch import (
    DEFAULT_COARSE_PITCH_PATH,
    CoarsePitchTable,
    PitchVerdict,
    classify_pitch,
    coarse_pitch_mm,
    load_coarse_pitch,
)
from swreview.checks.fastener import ThreadSpec, parse_thread
from swreview.ir.models import Quantity

REPO = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO / "specs" / "010-mechanical-checks" / "contracts" / "coarse-pitch.json"
CONTRACT: dict[str, Any] = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

OWNER_DECISION_50A = (
    "Owner decision 2026-10-08 (50A): the shop uses coarse threads; fine pitch must be confirmed"
)


# --- (1) the Python copy is pinned to the contract file -------------------------------------


def test_the_yaml_equals_the_contract_file_key_for_key_and_value_for_value() -> None:
    """FR-034's Python pin: a value changed in one and not the other fails here."""
    shipped = yaml.safe_load(DEFAULT_COARSE_PITCH_PATH.read_text(encoding="utf-8"))

    assert shipped == CONTRACT


def test_the_default_path_is_the_yaml_beside_the_loader() -> None:
    assert DEFAULT_COARSE_PITCH_PATH.name == "coarse_pitch.yaml"
    assert DEFAULT_COARSE_PITCH_PATH.parent == Path(coarse_pitch.__file__).parent
    assert DEFAULT_COARSE_PITCH_PATH.is_file()


def test_the_file_header_cites_the_standards_and_the_contract_it_is_pinned_to() -> None:
    """The numbers were transcribed, so the header says from what and asks for the check."""
    header = DEFAULT_COARSE_PITCH_PATH.read_text(encoding="utf-8").split("version:", 1)[0]

    for cited in ("ISO 261", "ISO 965-1", "ASME B1.1", "contracts/coarse-pitch.json"):
        assert cited in header
    assert "shop's copies" in header


# --- (2) the loader --------------------------------------------------------------------------


def test_the_shipped_table_holds_every_row_of_the_contract() -> None:
    table = load_coarse_pitch()

    assert isinstance(table, CoarsePitchTable)
    assert table.version == 1
    assert table.source == OWNER_DECISION_50A
    assert len(table.metric) == 40
    assert len(table.metric_fine_only_mm) == 15
    assert len(table.unified) == 25
    assert [row.size for row in table.unified_fine_only] == ["#0"]
    assert dict(table.standards) == CONTRACT["standards"]


def test_the_loaded_rows_are_the_contract_rows_in_order() -> None:
    table = load_coarse_pitch()

    assert [(row.size_mm, row.coarse_pitch_mm) for row in table.metric] == [
        (row["size_mm"], row["coarse_pitch_mm"]) for row in CONTRACT["metric"]
    ]
    assert list(table.metric_fine_only_mm) == CONTRACT["metric_fine_only_mm"]
    assert [(row.size, row.diameter_in, row.unc_tpi) for row in table.unified] == [
        (row["size"], row["diameter_in"], row["unc_tpi"]) for row in CONTRACT["unified"]
    ]
    assert [(row.size, row.diameter_in) for row in table.unified_fine_only] == [
        (row["size"], row["diameter_in"]) for row in CONTRACT["unified_fine_only"]
    ]


def test_a_metric_row_is_named_by_its_size() -> None:
    sizes = [row.size for row in load_coarse_pitch().metric]

    assert sizes[:3] == ["M1", "M1.1", "M1.2"]
    assert "M8" in sizes and "M3.5" in sizes
    assert sizes[-1] == "M68"


def test_the_loader_is_cached_per_resolved_path(tmp_path: Path) -> None:
    """Like `engagement_rules.load_rules`: the table is read once per file per process."""
    shipped = load_coarse_pitch()
    assert load_coarse_pitch(DEFAULT_COARSE_PITCH_PATH) is shipped
    assert load_coarse_pitch(str(DEFAULT_COARSE_PITCH_PATH)) is shipped

    copied = tmp_path / "table.yaml"
    copied.write_text(DEFAULT_COARSE_PITCH_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "sub").mkdir()

    first = load_coarse_pitch(copied)
    assert load_coarse_pitch(tmp_path / "sub" / ".." / "table.yaml") is first
    assert first is not shipped
    assert first == shipped


def _write(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "coarse.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


Mutation = Callable[[dict[str, Any]], None]


def _drop(key: str) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        del document[key]

    return mutate


def _set_row(key: str, index: int, field: str, value: object) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document[key][index][field] = value

    return mutate


def _drop_from_row(key: str, index: int, field: str) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        del document[key][index][field]

    return mutate


def _set_fine_only(index: int, value: object) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document["metric_fine_only_mm"][index] = value

    return mutate


def _swap(key: str, first: int, second: int) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        rows = document[key]
        rows[first], rows[second] = rows[second], rows[first]

    return mutate


def _repeat_row(key: str, index: int) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document[key].insert(index + 1, copy.deepcopy(document[key][index]))

    return mutate


def _add_fine_only_metric(size_mm: float) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document["metric_fine_only_mm"] = sorted([*document["metric_fine_only_mm"], size_mm])

    return mutate


def _add_fine_only_unified(size: str, diameter_in: float) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document["unified_fine_only"].append({"size": size, "diameter_in": diameter_in})

    return mutate


def _replace(key: str, value: object) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document[key] = value

    return mutate


def _drop_standard(name: str) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        del document["standards"][name]

    return mutate


POSITIVE = "must be a positive number"

# Index 16 of `metric` is M8, index 9 of `unified` is 1/4 (the contract file's order).
REFUSED: list[tuple[str, Mutation, str]] = [
    # A missing key, at the top, in `standards` and in a row. The look-behind keeps `metric`
    # from matching a message about `metric_fine_only_mm`, and `unified` likewise.
    *[(f"no {key}", _drop(key), rf"(?<!\w){key} is missing") for key in CONTRACT],
    ("no metric standard", _drop_standard("metric"), r"standards carries no metric$"),
    ("no unified standard", _drop_standard("unified"), r"standards carries no unified$"),
    (
        "a row with no pitch",
        _drop_from_row("metric", 16, "coarse_pitch_mm"),
        r"metric row 17 carries no coarse_pitch_mm",
    ),
    ("a row with no size", _drop_from_row("metric", 16, "size_mm"), r"metric row 17 .* size_mm"),
    ("no UNC", _drop_from_row("unified", 9, "unc_tpi"), r"unified row 10 carries no unc_tpi"),
    (
        "no diameter",
        _drop_from_row("unified", 9, "diameter_in"),
        r"unified row 10 carries no diameter_in",
    ),
    ("no size label", _drop_from_row("unified", 9, "size"), r"unified row 10 carries no size"),
    (
        "no fine-only diameter",
        _drop_from_row("unified_fine_only", 0, "diameter_in"),
        r"unified_fine_only row 1 carries no diameter_in",
    ),
    # A size label YAML read as a comment: `size: #1` unquoted is null.
    ("a null size label", _set_row("unified", 0, "size", None), r"unified row 1: size must"),
    ("a blank size label", _set_row("unified", 0, "size", " "), r"unified row 1: size must"),
    # A pitch, threads per inch or diameter that is not a positive number.
    (
        "a zero pitch",
        _set_row("metric", 16, "coarse_pitch_mm", 0),
        rf"metric row 17: coarse_pitch_mm {POSITIVE}, got 0$",
    ),
    (
        "a negative pitch",
        _set_row("metric", 16, "coarse_pitch_mm", -1.25),
        rf"metric row 17: coarse_pitch_mm {POSITIVE}, got -1\.25",
    ),
    (
        "a boolean pitch",
        _set_row("metric", 16, "coarse_pitch_mm", True),
        rf"metric row 17: coarse_pitch_mm {POSITIVE}, got True",
    ),
    (
        "a text pitch",
        _set_row("metric", 16, "coarse_pitch_mm", "1.25"),
        rf"metric row 17: coarse_pitch_mm {POSITIVE}, got '1\.25'",
    ),
    ("a zero size", _set_row("metric", 0, "size_mm", 0), rf"metric row 1: size_mm {POSITIVE}"),
    ("a zero UNC", _set_row("unified", 9, "unc_tpi", 0), rf"unified row 10: unc_tpi {POSITIVE}"),
    (
        "a negative diameter",
        _set_row("unified", 9, "diameter_in", -0.25),
        rf"unified row 10: diameter_in {POSITIVE}, got -0\.25",
    ),
    (
        "a zero fine-only diameter",
        _set_row("unified_fine_only", 0, "diameter_in", 0),
        rf"unified_fine_only row 1: diameter_in {POSITIVE}",
    ),
    (
        "a negative fine-only size",
        _set_fine_only(0, -5.5),
        rf"metric_fine_only_mm entry 1: {POSITIVE}, got -5\.5",
    ),
    (
        "a zero fine-only size",
        _set_fine_only(0, 0),
        rf"metric_fine_only_mm entry 1: {POSITIVE}, got 0$",
    ),
    # A size both coarse and fine-only.
    ("M8 in both", _add_fine_only_metric(8), r"M8 is in both metric and metric_fine_only_mm"),
    (
        "#10 in both",
        _add_fine_only_unified("#10", 0.19),
        r"unified_fine_only #10 \(0\.19 in\) is unified #10 \(0\.19 in\) too",
    ),
    (
        "#10's diameter in both",
        _add_fine_only_unified("No. 10", 0.1905),
        r"unified_fine_only No\. 10 \(0\.1905 in\) is unified #10 \(0\.19 in\) too",
    ),
    # 0.3 in is no row's diameter, so only the size label matches.
    (
        "#10's label in both",
        _add_fine_only_unified("#10", 0.3),
        r"unified_fine_only #10 \(0\.3 in\) is unified #10 \(0\.19 in\) too",
    ),
    # Rows out of ascending order, a repeated row among them.
    ("metric out of order", _swap("metric", 16, 17), r"metric must be in ascending .* 8 follows 9"),
    ("a repeated metric row", _repeat_row("metric", 16), r"metric must be .* 8 follows 8"),
    (
        "fine-only out of order",
        _swap("metric_fine_only_mm", 1, 2),
        r"metric_fine_only_mm must be in ascending .* 15 follows 17",
    ),
    (
        "unified out of order",
        _swap("unified", 9, 10),
        r"(?<!\w)unified must be in ascending .* 0\.25 follows 0\.3125",
    ),
    (
        "fine-only unified out of order",
        _replace(
            "unified_fine_only",
            [{"size": "FICT-A", "diameter_in": 0.0665}, {"size": "#0", "diameter_in": 0.06}],
        ),
        r"unified_fine_only must be in ascending .* 0\.06 follows 0\.0665",
    ),
    # The wrong shapes.
    (
        "a null metric size",
        _set_row("metric", 0, "size_mm", None),
        rf"metric row 1: size_mm {POSITIVE}, got None",
    ),
    ("metric not a list", _replace("metric", {"M8": 1.25}), r"(?<!\w)metric must be a list"),
    ("fine-only not a list", _replace("metric_fine_only_mm", 25), r"metric_fine_only_mm must be"),
    ("standards not a mapping", _replace("standards", "ISO 261"), r"standards must be a mapping"),
    ("a version that is no number", _replace("version", "one"), r"version must be a positive"),
    ("a zero version", _replace("version", 0), r"version must be a positive"),
    ("a blank source", _replace("source", " "), r"source must be a non-empty text"),
    (
        "a blank standard",
        _replace("standards", {"metric": "", "unified": "u"}),
        r"standards metric",
    ),
]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [(mutate, match) for _, mutate, match in REFUSED],
    ids=[name for name, _, _ in REFUSED],
)
def test_a_copy_with_a_broken_row_is_refused_naming_it(
    tmp_path: Path, mutate: Mutation, match: str
) -> None:
    document = copy.deepcopy(CONTRACT)
    mutate(document)

    with pytest.raises(ValueError, match=match):
        load_coarse_pitch(_write(tmp_path, document))


def test_a_document_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mapping"):
        load_coarse_pitch(_write(tmp_path, [1, 2]))


def test_a_metric_row_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    document = copy.deepcopy(CONTRACT)
    document["metric"][0] = 1.25

    with pytest.raises(ValueError, match="metric row 1"):
        load_coarse_pitch(_write(tmp_path, document))


def test_an_unbroken_copy_loads(tmp_path: Path) -> None:
    """The refusals above are the mutation's, not the round trip's."""
    assert load_coarse_pitch(_write(tmp_path, copy.deepcopy(CONTRACT))) == load_coarse_pitch()


# --- (3) classify_pitch over section 8.9's first table ---------------------------------------

# (designation, class, size, coarse pitch mm, UNC threads per inch, coarse designation)
JUDGED: list[tuple[str, str, str, float | None, float | None, str | None]] = [
    # Coarse, metric: the pitch is the size's coarse pitch, or none is written (ISO 965-1).
    ("M8x1.25", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8 x 1.25", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8x1.25-6g", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8x1.25-6G", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8x1,25", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8-1.25", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M10-1.5-6H", "coarse", "M10", 1.5, None, "M10x1.5"),
    ("M4-0.7x12", "coarse", "M4", 0.7, None, "M4x0.7"),
    ("M8-1.25rh", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8-6H", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8-6g6h", "coarse", "M8", 1.25, None, "M8x1.25"),
    ("M8", "coarse", "M8", 1.25, None, "M8x1.25"),
    # M6's and M7's coarse pitch is 1: a 1 mm pitch is not fine on every size.
    ("M6x1", "coarse", "M6", 1, None, "M6x1"),
    ("M7x1", "coarse", "M7", 1, None, "M7x1"),
    ("M3.5x0.6", "coarse", "M3.5", 0.6, None, "M3.5x0.6"),
    # Non-standard, metric: coarser than the coarse pitch.
    ("M8x1.25 6H", "nonstandard", "M8", 1.25, None, "M8x1.25"),
    ("M8x1.5", "nonstandard", "M8", 1.25, None, "M8x1.25"),
    ("M10x35", "nonstandard", "M10", 1.5, None, "M10x1.5"),
    # Fine, metric.
    ("M8-1 x 20", "fine", "M8", 1.25, None, "M8x1.25"),
    ("M10-1.25LH", "fine", "M10", 1.5, None, "M10x1.5"),
    ("M8x1", "fine", "M8", 1.25, None, "M8x1.25"),
    ("m8x1", "fine", "M8", 1.25, None, "M8x1.25"),
    ("M8×1", "fine", "M8", 1.25, None, "M8x1.25"),
    ("M8-1", "fine", "M8", 1.25, None, "M8x1.25"),
    ("M8x1.0", "fine", "M8", 1.25, None, "M8x1.25"),
    ("M8x0.75", "fine", "M8", 1.25, None, "M8x1.25"),
    # The size is matched first: 1.25 is M8's coarse pitch, not M10's; 1.5 is M10's, not M12's.
    ("M10x1.25", "fine", "M10", 1.5, None, "M10x1.5"),
    ("M12x1.5", "fine", "M12", 1.75, None, "M12x1.75"),
    # A metric size with fine pitches only, with or without a pitch written.
    ("M25x1.5", "fine_only_size", "M25", None, None, None),
    ("M25", "fine_only_size", "M25", None, None, None),
    ("M5.5x0.5", "fine_only_size", "M5.5", None, None, None),
    # Coarse, unified: the threads per inch are the size's UNC. The letters are not read.
    ("1/4-20", "coarse", "1/4", None, 20, "1/4-20"),
    ("1/4-20 UNC-2B", "coarse", "1/4", None, 20, "1/4-20"),
    ("1/4-20 UNF", "coarse", "1/4", None, 20, "1/4-20"),
    ("0.250-20", "coarse", "1/4", None, 20, "1/4-20"),
    ("#6-32", "coarse", "#6", None, 32, "#6-32"),
    ("#10-24", "coarse", "#10", None, 24, "#10-24"),
    ("1.000-8", "coarse", "1", None, 8, "1-8"),
    # Fine, unified: UNF, UNEF and 8-UN.
    ("1/4-28", "fine", "1/4", None, 20, "1/4-20"),
    ("1/4-28 UNF-2A", "fine", "1/4", None, 20, "1/4-20"),
    ("1/4-32", "fine", "1/4", None, 20, "1/4-20"),
    ("#10-32", "fine", "#10", None, 24, "#10-24"),
    ("#10-32 UNF", "fine", "#10", None, 24, "#10-24"),
    ("0.190-32", "fine", "#10", None, 24, "#10-24"),
    ("1.125-8", "fine", "1-1/8", None, 7, "1-1/8-7"),
    # #0 has no UNC thread: a fine-only size, flagged like M25.
    ("#0-80", "fine_only_size", "#0", None, None, None),
    # Non-standard, unified: fewer threads per inch than UNC.
    ("1/4-18", "nonstandard", "1/4", None, 20, "1/4-20"),
    # A pipe size written with no pipe token reads as a unified thread, at #5's 0.125 in.
    ("1/8-27", "nonstandard", "#5", None, 40, "#5-40"),
]


@pytest.mark.parametrize(
    ("designation", "pitch_class", "size", "coarse_mm", "unc_tpi", "coarse_designation"),
    JUDGED,
    ids=[row[0] for row in JUDGED],
)
def test_a_judged_designation_gets_its_class_its_size_and_its_coarse_alternative(
    designation: str,
    pitch_class: str,
    size: str,
    coarse_mm: float | None,
    unc_tpi: float | None,
    coarse_designation: str | None,
) -> None:
    verdict = classify_pitch(designation)

    assert isinstance(verdict, PitchVerdict)
    assert verdict.pitch_class == pitch_class
    assert verdict.size == size
    assert verdict.coarse_pitch_mm == coarse_mm
    assert verdict.unc_tpi == unc_tpi
    assert verdict.coarse_designation == coarse_designation
    assert verdict.spec == parse_thread(designation)


UNKNOWN_SIZES = ["M2.3x0.4", "M70", "0.2-32"]


@pytest.mark.parametrize("designation", UNKNOWN_SIZES)
def test_a_size_in_no_table_is_an_unknown_size_and_never_judged(designation: str) -> None:
    verdict = classify_pitch(designation)

    assert verdict.pitch_class == "unknown_size"
    assert (verdict.size, verdict.coarse_pitch_mm, verdict.unc_tpi) == (None, None, None)
    assert verdict.coarse_designation is None
    assert verdict.spec == parse_thread(designation)


UNREADABLE_TEXT = [
    # Read as M8-1.256G, and 1.256G is no tolerance class: a known limit (research R2.26).
    "M8-1.25 6g",
    "M10-1.25G",
    "M8-1x",
    "M16xPh3P1.5",
    "M8x",
    "MF8x1",
    # How a Hole Wizard pipe tap arrives: a size and no thread.
    "3/8",
    "1-8",
    "1-1/8-7",
    "10-32",
    "No. 10-32",
    # parse_thread reads whole threads per inch only, so 2 in UNC is unreadable as text.
    "2.000-4.5",
]


@pytest.mark.parametrize("designation", UNREADABLE_TEXT)
def test_text_parse_thread_does_not_read_is_unreadable_and_carries_its_parse(
    designation: str,
) -> None:
    verdict = classify_pitch(designation)

    assert verdict.pitch_class == "unreadable"
    assert verdict.spec == parse_thread(designation)
    assert verdict.spec is not None and verdict.spec.series is None
    assert (verdict.size, verdict.coarse_designation) == (None, None)


@pytest.mark.parametrize("designation", [None, "", " ", "\t"])
def test_no_designation_or_a_blank_one_is_unreadable_and_not_parsed(
    designation: str | None,
) -> None:
    verdict = classify_pitch(designation)

    assert verdict.pitch_class == "unreadable"
    assert verdict.spec is None
    assert verdict.no_pitch_written is False


PIPE_THREADS = [
    "1/8-27 NPT",
    "NPT 1/8",
    "1/2-14 NPTF",
    "3/4 NPSM",
    "1/2 NPS",
    "G1/4",
    "G 1/2 A",
    "R1/4",
    "Rc1/4",
    "Rp 1/2",
    "PT1/8",
    "PF1/4",
    "1/4 BSPP",
    "1/4 BSPT",
    "1/2 BSP",
]


@pytest.mark.parametrize("designation", [*PIPE_THREADS, "1/8-27 npt", "g1/4", "rc 1/4"])
def test_a_pipe_thread_is_pipe_whatever_parse_thread_reads(designation: str) -> None:
    """`1/8-27 NPT` reads as a unified thread to parse_thread; it is still never judged."""
    verdict = classify_pitch(designation)

    assert verdict.pitch_class == "pipe"
    assert verdict.spec is None
    assert (verdict.size, verdict.coarse_designation) == (None, None)


@pytest.mark.parametrize(
    ("designation", "no_pitch_written"),
    [
        ("M8", True),
        ("M8-6H", True),
        ("M8-6g6h", True),
        ("M25", True),
        ("M70", True),
        ("M8x1.25", False),
        ("M8x1", False),
        ("M8-1.25", False),
        ("1/4-20", False),
        ("#10-24", False),
        ("3/8", False),
        ("1/8-27 NPT", False),
    ],
)
def test_no_pitch_written_says_whether_the_text_states_a_pitch(
    designation: str, no_pitch_written: bool
) -> None:
    """A coarse verdict that rests on it relies on ISO 965-1's omitted coarse pitch."""
    assert classify_pitch(designation).no_pitch_written is no_pitch_written


def test_the_classifier_reads_the_parser_and_the_pipe_helper_of_the_fastener_module() -> None:
    """One parser and one list of pipe tokens (DRY, `contracts/fasteners.md` 8.8)."""
    assert coarse_pitch.parse_thread is fastener.parse_thread
    assert coarse_pitch.is_pipe_thread is fastener.is_pipe_thread


def test_classify_pitch_reads_the_table_it_is_given(tmp_path: Path) -> None:
    """A made-up table where M8's coarse pitch is 1 judges M8x1 coarse and M8x1.25 coarser."""
    document = copy.deepcopy(CONTRACT)
    document["metric"][16]["coarse_pitch_mm"] = 1
    table = load_coarse_pitch(_write(tmp_path, document))

    assert classify_pitch("M8x1", table).pitch_class == "coarse"
    assert classify_pitch("M8x1.25", table=table).pitch_class == "nonstandard"
    assert classify_pitch("M8x1.25").pitch_class == "coarse"


# --- (4) the table's verdict on a parsed thread ----------------------------------------------


def unified(diameter_in: float, threads_per_inch: float) -> ThreadSpec:
    """A hand-made unified thread, its pitch not rounded as parse_thread rounds it."""
    return ThreadSpec(
        text=f"{diameter_in}-{threads_per_inch}",
        series="unified",
        nominal_diameter=Quantity(value=diameter_in * 25.4, unit="mm"),
        pitch_mm=25.4 / threads_per_inch,
        normalized=f"UN{diameter_in * 25.4}X{25.4 / threads_per_inch}",
    )


def metric(diameter_mm: float, pitch_mm: float | None) -> ThreadSpec:
    return ThreadSpec(
        text=f"M{diameter_mm}x{pitch_mm}",
        series="metric",
        nominal_diameter=Quantity(value=diameter_mm, unit="mm"),
        pitch_mm=pitch_mm,
        normalized=f"M{diameter_mm}X{pitch_mm}",
    )


@pytest.mark.parametrize(
    ("threads_per_inch", "pitch_class"),
    [
        (20.0, "coarse"),
        # Within 0.01 threads per inch is the UNC thread. As millimetres rounded to six
        # places, 25.4 / 20.005 is 1.269683, not 1.27: compared so it would read fine.
        (20.005, "coarse"),
        (19.995, "coarse"),
        (20.009, "coarse"),
        (19.991, "coarse"),
        (20.02, "fine"),
        (20.011, "fine"),
        (19.98, "nonstandard"),
        (19.989, "nonstandard"),
    ],
)
def test_a_unified_thread_compares_as_threads_per_inch_within_0_01(
    threads_per_inch: float, pitch_class: str
) -> None:
    verdict = load_coarse_pitch().classify(unified(0.25, threads_per_inch))

    assert verdict.pitch_class == pitch_class
    assert (verdict.size, verdict.unc_tpi, verdict.coarse_designation) == ("1/4", 20, "1/4-20")


@pytest.mark.parametrize(
    ("diameter_in", "size"),
    [(0.25, "1/4"), (0.2509, "1/4"), (0.2491, "1/4"), (0.2511, None), (0.2489, None)],
)
def test_a_unified_size_matches_within_0_001_in(diameter_in: float, size: str | None) -> None:
    verdict = load_coarse_pitch().classify(unified(diameter_in, 20))

    assert verdict.size == size
    assert verdict.pitch_class == ("coarse" if size else "unknown_size")


def test_a_unified_thread_given_in_inches_is_read_in_inches() -> None:
    spec = ThreadSpec(
        text="1/4-20",
        series="unified",
        nominal_diameter=Quantity(value=0.25, unit="in"),
        pitch_mm=1.27,
        normalized="UN6.35X1.27",
    )

    verdict = load_coarse_pitch().classify(spec)

    assert (verdict.pitch_class, verdict.size) == ("coarse", "1/4")


def test_the_largest_unc_row_is_reachable_through_the_table() -> None:
    """`2.000-4.5` does not parse (whole threads per inch only), but the row is the table's."""
    table = load_coarse_pitch()

    assert table.classify(unified(2.0, 4.5)).pitch_class == "coarse"
    assert table.classify(unified(2.0, 4.5)).coarse_designation == "2-4.5"
    assert table.classify(unified(2.0, 4)).pitch_class == "nonstandard"
    assert table.classify(unified(2.0, 5)).pitch_class == "fine"


@pytest.mark.parametrize(
    ("pitch_mm", "pitch_class"),
    [
        (1.25, "coarse"),
        (1.2500009, "coarse"),
        (1.2499991, "coarse"),
        (1.25001, "nonstandard"),
        (1.24999, "fine"),
        (None, "coarse"),
    ],
)
def test_a_metric_pitch_compares_within_1e_6_mm(pitch_mm: float | None, pitch_class: str) -> None:
    verdict = load_coarse_pitch().classify(metric(8.0, pitch_mm))

    assert verdict.pitch_class == pitch_class
    assert verdict.no_pitch_written is (pitch_mm is None)


@pytest.mark.parametrize(
    ("diameter_mm", "size"), [(8.0, "M8"), (8.0000009, "M8"), (7.9999991, "M8"), (8.00001, None)]
)
def test_a_metric_size_matches_within_1e_6_mm(diameter_mm: float, size: str | None) -> None:
    verdict = load_coarse_pitch().classify(metric(diameter_mm, 1.25))

    assert verdict.size == size
    assert verdict.pitch_class == ("coarse" if size else "unknown_size")


def test_a_fine_only_metric_size_is_judged_whatever_its_pitch() -> None:
    table = load_coarse_pitch()

    for pitch_mm in (None, 0.5, 1.5, 3.0):
        verdict = table.classify(metric(25.0, pitch_mm))
        assert (verdict.pitch_class, verdict.size) == ("fine_only_size", "M25")
        assert (verdict.coarse_pitch_mm, verdict.coarse_designation) == (None, None)


def test_the_table_refuses_a_thread_the_parser_did_not_read() -> None:
    """Classes 1 to 3 are `classify_pitch`'s; the table judges a recognised thread only."""
    with pytest.raises(ValueError, match="not a recognised thread"):
        load_coarse_pitch().classify(parse_thread("3/8"))


def test_the_table_refuses_a_unified_thread_with_no_pitch() -> None:
    spec = ThreadSpec(
        text="1/4",
        series="unified",
        nominal_diameter=Quantity(value=6.35, unit="mm"),
        pitch_mm=None,
        normalized="UN6.35",
    )

    with pytest.raises(ValueError, match="threads per inch"):
        load_coarse_pitch().classify(spec)


# --- (5) the metric coarse pitch the name grammar reads ---------------------------------------


@pytest.mark.parametrize(
    ("size_mm", "pitch_mm"),
    [(row["size_mm"], row["coarse_pitch_mm"]) for row in CONTRACT["metric"]],
)
def test_coarse_pitch_mm_gives_every_metric_row(size_mm: float, pitch_mm: float) -> None:
    assert coarse_pitch_mm(size_mm) == pitch_mm


@pytest.mark.parametrize("size_mm", [*CONTRACT["metric_fine_only_mm"], 2.3, 70, 0, 8.00001, 69])
def test_coarse_pitch_mm_is_none_for_a_fine_only_or_an_unknown_size(size_mm: float) -> None:
    assert coarse_pitch_mm(size_mm) is None


def test_coarse_pitch_mm_matches_within_1e_6_mm_and_reads_the_table_it_is_given(
    tmp_path: Path,
) -> None:
    assert coarse_pitch_mm(8.0000009) == 1.25
    document = copy.deepcopy(CONTRACT)
    document["metric"][16]["coarse_pitch_mm"] = 1

    assert coarse_pitch_mm(8, table=load_coarse_pitch(_write(tmp_path, document))) == 1


# --- (6) every row of the contract file, judged through the classifier -----------------------
#
# The pin in (1) proves the YAML is the contract; these prove each row is judged as its size
# reads. A unified size's diameter comes from parse_thread's reading of the size label (`#8`
# is 0.060 + 0.013 x 8 in), not from the table, so a diameter slipped in both files (#8 at
# 0.146 in instead of 0.164) turns `#8-32` into an unknown size and fails here.

METRIC_SIZES = [(row["size_mm"], row["coarse_pitch_mm"]) for row in CONTRACT["metric"]]

# (the pitch written, as a multiple of the size's coarse pitch, None for no pitch; its class)
METRIC_PITCHES: list[tuple[float | None, str]] = [
    (1.0, "coarse"),
    (None, "coarse"),
    (0.8, "fine"),
    (1.2, "nonstandard"),
]


@pytest.mark.parametrize(
    ("factor", "pitch_class"), METRIC_PITCHES, ids=["at", "none", "finer", "coarser"]
)
@pytest.mark.parametrize(
    ("size_mm", "pitch_mm"), METRIC_SIZES, ids=[f"M{size_mm:g}" for size_mm, _ in METRIC_SIZES]
)
def test_every_metric_row_is_coarse_at_its_pitch_or_none_fine_below_and_nonstandard_above(
    size_mm: float, pitch_mm: float, factor: float | None, pitch_class: str
) -> None:
    size = f"M{size_mm:g}"
    designation = size if factor is None else f"{size}x{pitch_mm * factor:g}"

    verdict = classify_pitch(designation)

    assert (verdict.pitch_class, verdict.size) == (pitch_class, size)
    assert verdict.coarse_pitch_mm == pitch_mm
    assert verdict.coarse_designation == f"{size}x{pitch_mm:g}"
    assert verdict.no_pitch_written is (factor is None)
    assert verdict.spec == parse_thread(designation)


@pytest.mark.parametrize("pitch", [None, 1.5], ids=["none", "1.5"])
@pytest.mark.parametrize("size_mm", CONTRACT["metric_fine_only_mm"], ids=lambda d: f"M{d:g}")
def test_every_fine_only_metric_size_is_judged_with_or_without_a_pitch(
    size_mm: float, pitch: float | None
) -> None:
    size = f"M{size_mm:g}"
    designation = size if pitch is None else f"{size}x{pitch:g}"

    verdict = classify_pitch(designation)

    assert (verdict.pitch_class, verdict.size) == ("fine_only_size", size)
    assert (verdict.coarse_pitch_mm, verdict.coarse_designation) == (None, None)


# How parse_thread reads a size whose label it does not: a whole or a mixed number of inches as
# a decimal (`1-1/8-7` is unreadable as text, `1.125-7` is read). `#N` and `a/b` read as written.
AS_DECIMAL_INCHES = {
    "1": "1.000",
    "1-1/8": "1.125",
    "1-1/4": "1.250",
    "1-3/8": "1.375",
    "1-1/2": "1.500",
    "1-3/4": "1.750",
    "2": "2.000",
}


def _judge_unified(size: str, threads_per_inch: float) -> PitchVerdict:
    """The verdict on a unified size at a number of threads per inch, read by parse_thread.

    parse_thread reads whole threads per inch only, so a fractional count (2-4.5) is judged by
    the table on a hand-made thread of the size's decimal diameter.
    """
    written = AS_DECIMAL_INCHES.get(size, size)
    if float(threads_per_inch).is_integer():
        designation = f"{written}-{threads_per_inch:g}"
        verdict = classify_pitch(designation)
        assert verdict.spec == parse_thread(designation)
        return verdict
    return load_coarse_pitch().classify(unified(float(written), threads_per_inch))


UNIFIED_ROWS = [(row["size"], row["unc_tpi"]) for row in CONTRACT["unified"]]


@pytest.mark.parametrize(
    ("more_threads_per_inch", "pitch_class"),
    [(0, "coarse"), (4, "fine"), (-1, "nonstandard")],
    ids=["UNC", "UNC+4", "UNC-1"],
)
@pytest.mark.parametrize(("size", "unc_tpi"), UNIFIED_ROWS, ids=[size for size, _ in UNIFIED_ROWS])
def test_every_unified_row_is_coarse_at_unc_fine_above_and_nonstandard_below(
    size: str, unc_tpi: float, more_threads_per_inch: int, pitch_class: str
) -> None:
    verdict = _judge_unified(size, unc_tpi + more_threads_per_inch)

    assert (verdict.pitch_class, verdict.size) == (pitch_class, size)
    assert verdict.unc_tpi == unc_tpi
    assert verdict.coarse_designation == f"{size}-{unc_tpi:g}"
    assert verdict.no_pitch_written is False
