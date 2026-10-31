"""`swreview seat transparency`: PROBE-2's polarity from the probe's own lines (006 T111; 172A).

006 T102 asks the seat which recorded transparency value means transparent, and whether slot 7 is
the transparency slot on this build (research R2.8, R4). Decision 172A lets the engineer build a
tiny made-up assembly for it (`benchmarks/native/probe2-polarity/RECIPE.md`): one block inserted
three times, `PROBE2-BLOCK-1` made transparent and `-2` opaque with the same component-level
colour, `-3` left alone. `swreview-extract probe standards` prints the nine appearance slots of
each, and this decider reads only those lines:

- the two overrides must differ in slot 7 and nowhere else; the opaque one's slot 7 then names
  the polarity, `0` for `zero_is_opaque` and `1` for `one_is_opaque`;
- slot 7 equal while the colour is equal and another slot differs, or no slot 7 at all,
  **refutes slot 7**: the dump reads that slot (`ComponentTreeDumper.ReadTransparency`), so no
  flip of the constant could settle it;
- anything else - nothing differing (the transparency set on the part, not the component row), a
  colour that differs, a control that did not hold, a component missing, a read that failed, a
  difference beyond slot 7, an opaque reading that is neither 0 nor 1 - is inconclusive, never a
  guess (research R2.8), and never a refutation that would send the owner to the extractor for
  what an operator slip explains.

Every probe line here is fictional: one complete run in `tests/fixtures/seat/probe2/`, and its
PROBE-2 section rewritten per case.
"""

from __future__ import annotations

import codecs
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from swreview.checks.standards.assembly import ONE_IS_OPAQUE, ZERO_IS_OPAQUE
from tests.support.console import plain_words
from tests.unit.test_cli import invoke

PROBE2 = Path(__file__).resolve().parents[1] / "fixtures" / "seat" / "probe2"
SAMPLE = PROBE2 / "probe-standards.txt"
REVIEWER = Path(__file__).resolve().parents[2]
SECTION = "probe-2 appearance_overrides:\n"
NEXT_SECTION = "probe-3 component_visibility:\n"

COLOUR = (0, 0.501961, 1, 1, 1, 0.5, 0.3125)
"""Slots 0 to 6 of the colour both overrides share (recipe): RGB, then the lighting slots."""


def slots(seven: float, *, eighth: float = 0, colour: Sequence[float] = COLOUR) -> list[float]:
    return [*colour, seven, eighth]


def component(cid: str, key: str, has: str = "True", values: Any = None) -> str:
    """One PROBE-2 line as `Program.ProbeAppearanceOverrides` prints it."""
    if values is None:
        printed = "null"
    elif isinstance(values, str):
        printed = values
    else:
        printed = f"{len(values)} slots " + " ".join(
            f"[{index}]={value:g}" for index, value in enumerate(values)
        )
    return (
        f"  {cid} {key} HasMaterialPropertyValues={has} "
        f"GetMaterialPropertyValues2(1, null)={printed}\n"
    )


def seat(
    *, transparent: Any = None, opaque: Any = None, plain_has: str = "False", root: bool = True
) -> list[str]:
    """The recipe's three blocks, slot 7 at 0.5 and 0 unless a case says otherwise."""
    lines = [component("cmp:0001", "PROBE2-POLARITY", "False")] if root else []
    return [
        *lines,
        component("cmp:0002", "PROBE2-BLOCK-1", values=transparent or slots(0.5)),
        component("cmp:0003", "PROBE2-BLOCK-2", values=opaque or slots(0)),
        component("cmp:0004", "PROBE2-BLOCK-3", plain_has, slots(0, colour=(0.79, 0.82, 0.93))),
    ]


def probe_file(
    tmp_path: Path, lines: Sequence[str] | None = None, *, text: str | None = None
) -> Path:
    """The sample run with its PROBE-2 section's lines replaced by `lines`."""
    if text is None:
        sample = SAMPLE.read_text(encoding="utf-8")
        before, rest = sample.split(SECTION)
        _, after = rest.split(NEXT_SECTION)
        text = before + SECTION + "".join(seat() if lines is None else lines) + NEXT_SECTION + after
    path = tmp_path / "probe-standards.txt"
    path.write_text(text, encoding="utf-8")
    return path


def decide(path: Path, *extra: str) -> Any:
    return invoke("seat", "transparency", str(path), *extra)


def report(path: Path, *extra: str) -> dict[str, Any]:
    result = decide(path, "--json", *extra)
    assert result.exit_code in (0, 1), result.output
    body: dict[str, Any] = json.loads(result.stdout)
    assert (result.exit_code == 1) == (body["verdict"] == "inconclusive")
    return body


# --- the two answers ---------------------------------------------------------------------------


def test_the_sample_run_shows_zero_is_opaque_and_exits_0(tmp_path: Path) -> None:
    result = decide(SAMPLE, "--json")

    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["verdict"] == ZERO_IS_OPAQUE
    assert body["slot_7_refuted"] is False


def test_an_opaque_override_reading_1_shows_one_is_opaque(tmp_path: Path) -> None:
    body = report(probe_file(tmp_path, seat(transparent=slots(0.5), opaque=slots(1))))

    assert body["verdict"] == ONE_IS_OPAQUE


def test_a_fully_transparent_reading_of_1_beside_an_opaque_0_is_zero_is_opaque(
    tmp_path: Path,
) -> None:
    body = report(probe_file(tmp_path, seat(transparent=slots(1), opaque=slots(0))))

    assert body["verdict"] == ZERO_IS_OPAQUE


def test_the_answer_names_the_one_edit_and_the_precomputed_goldens(tmp_path: Path) -> None:
    body = report(SAMPLE)

    assert f'TRANSPARENCY_POLARITY = "{ZERO_IS_OPAQUE}"' in body["next"]
    folder = f"tests/golden/test_transparency_polarity/{ZERO_IS_OPAQUE}"
    assert folder in body["next"]
    assert (REVIEWER / folder).is_dir()


def test_the_text_answer_leads_with_the_verdict_and_gives_each_reading(tmp_path: Path) -> None:
    result = decide(SAMPLE)

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"verdict: {ZERO_IS_OPAQUE}"
    assert any(line.startswith("transparent PROBE2-BLOCK-1") and "0.75" in line for line in lines)
    assert any(line.startswith("opaque PROBE2-BLOCK-2") for line in lines)
    assert any(line.startswith("plain PROBE2-BLOCK-3") for line in lines)
    assert "D:\\fict-seat" not in result.stdout


# --- slot 7 refuted ----------------------------------------------------------------------------


def test_slot_7_equal_with_another_slot_differing_refutes_slot_7_and_names_the_slot(
    tmp_path: Path,
) -> None:
    lines = seat(transparent=slots(0, eighth=0.5), opaque=slots(0, eighth=0))

    result = decide(probe_file(tmp_path, lines), "--json")

    assert result.exit_code == 1
    body = json.loads(result.stdout)
    assert body["verdict"] == "inconclusive"
    assert body["slot_7_refuted"] is True
    assert "slot 8" in body["reason"]
    assert body["next"] is None


def test_no_slot_differing_is_an_operator_slip_not_a_refutation(tmp_path: Path) -> None:
    """Transparency set on the part, a body or a face makes all three blocks look see-through
    and leaves the two component overrides identical: the recipe's step 4 was missed, and the
    answer is to set it on the component row and probe again, not an extractor change."""
    body = report(probe_file(tmp_path, seat(transparent=slots(0), opaque=slots(0))))

    assert body["verdict"] == "inconclusive"
    assert body["slot_7_refuted"] is False
    assert "step 4" in body["reason"]
    assert "component row" in body["reason"]
    assert body["next"] is None


@pytest.mark.parametrize(
    "transparent",
    [
        slots(0, colour=(1, 0, 0, 1, 1, 0.5, 0.3125)),
        slots(0, eighth=0.5, colour=(1, 0, 0, 1, 1, 0.5, 0.3125)),
    ],
    ids=["only the colour", "the colour and slot 8"],
)
def test_a_colour_that_differs_with_slot_7_equal_is_not_a_refutation(
    tmp_path: Path, transparent: list[float]
) -> None:
    """Two colours mean the recipe's control did not hold, so nothing else the overrides show
    can refute slot 7: same colour, and probe again."""
    body = report(probe_file(tmp_path, seat(transparent=transparent, opaque=slots(0))))

    assert body["verdict"] == "inconclusive"
    assert body["slot_7_refuted"] is False
    assert "colour" in body["reason"]
    assert "steps 3 and 4" in body["reason"]


def test_fewer_than_eight_slots_refutes_slot_7(tmp_path: Path) -> None:
    short = [0, 0.5, 1, 1, 1, 0.5, 0.3125]
    body = report(probe_file(tmp_path, seat(transparent=short, opaque=[*short[:6], 0.2])))

    assert body["verdict"] == "inconclusive"
    assert body["slot_7_refuted"] is True


# --- inconclusive, and never a guess ----------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "lines", "named"),
    [
        (
            "the overrides differ in colour as well as slot 7",
            seat(transparent=slots(0.5), opaque=slots(0, colour=(1, 0, 0, 1, 1, 0.5, 0.3125))),
            "slots 0, 1, 2 and 7",
        ),
        ("the opaque reading is neither 0 nor 1", seat(opaque=slots(0.25)), "0.25"),
        ("the plain block reports an override", seat(plain_has="True"), "PROBE2-BLOCK-3"),
        (
            "the transparent block reports none",
            [
                component("cmp:0002", "PROBE2-BLOCK-1", "False", slots(0.5)),
                *seat()[2:],
            ],
            "PROBE2-BLOCK-1",
        ),
        (
            "the override read failed",
            [
                component("cmp:0002", "PROBE2-BLOCK-1", "!COMException: fictional"),
                *seat()[2:],
            ],
            "PROBE2-BLOCK-1",
        ),
        (
            "the slot read failed",
            [
                component("cmp:0002", "PROBE2-BLOCK-1", "True", "!COMException: fictional"),
                *seat()[2:],
            ],
            "PROBE2-BLOCK-1",
        ),
        ("the slot read answered null", seat(transparent="null"), "PROBE2-BLOCK-1"),
        (
            "the slot reads answered no slots",
            seat(transparent="0 slots", opaque="0 slots"),
            "PROBE2-BLOCK-1",
        ),
        (
            "the slots skip one",
            seat(transparent="9 slots [0]=0 [1]=0.5 [2]=1 [3]=1 [4]=1 [5]=0.5 [6]=0.3 [8]=0"),
            "PROBE2-BLOCK-1",
        ),
        (
            "the count disagrees with the slots listed",
            seat(transparent="9 slots [0]=0 [1]=0.5 [2]=1 [3]=1 [4]=1 [5]=0.5 [6]=0.3 [7]=0.75"),
            "PROBE2-BLOCK-1",
        ),
        ("the opaque block is missing", [*seat()[:2], seat()[3]], "PROBE2-BLOCK-2"),
        ("a block is listed twice", [*seat(), seat()[1]], "PROBE2-BLOCK-1"),
        (
            "the slot counts differ",
            seat(transparent=slots(0.5), opaque=[*slots(0), 0]),
            "slot",
        ),
        ("no live component", ["  (no live component on this document)\n"], "PROBE2-BLOCK-1"),
    ],
)
def test_inconclusive_names_what_did_not_hold(
    tmp_path: Path, case: str, lines: list[str], named: str
) -> None:
    result = decide(probe_file(tmp_path, lines), "--json")

    assert result.exit_code == 1, case
    body = json.loads(result.stdout)
    assert body["verdict"] == "inconclusive", case
    assert body["slot_7_refuted"] is False, case
    assert named in body["reason"], (case, body["reason"])


def printed(seven: str, *, eighth: str = "0") -> str:
    """The recipe's colour with slots 7 and 8 as given, printed as the probe prints a value
    (`G6`, invariant culture: `NaN`, `Infinity` and `-Infinity` included)."""
    values = [f"{value:g}" for value in COLOUR] + [seven, eighth]
    return f"{len(values)} slots " + " ".join(f"[{i}]={v}" for i, v in enumerate(values))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-1", "2"])
@pytest.mark.parametrize(
    ("role", "name"), [("transparent", "PROBE2-BLOCK-1"), ("opaque", "PROBE2-BLOCK-2")]
)
def test_a_slot_7_reading_that_is_no_transparency_settles_nothing(
    tmp_path: Path, role: str, name: str, value: str
) -> None:
    """Review round 2, F4: a transparency is a fraction from 0 to 1. A transparent block reading
    `NaN` or 2 beside an opaque 0 differs at slot 7 alone, but proves no polarity."""
    body = report(probe_file(tmp_path, seat(**{role: printed(value)})))

    assert body["verdict"] == "inconclusive"
    assert body["slot_7_refuted"] is False
    assert name in body["reason"], body["reason"]
    assert body["next"] is None


@pytest.mark.parametrize(
    ("transparent", "opaque"),
    [
        (printed("0", eighth="NaN"), printed("0")),
        (printed("2", eighth="0.5"), printed("2")),
    ],
    ids=["a slot that is no number beside an equal slot 7", "an equal slot 7 outside 0 to 1"],
)
def test_an_invalid_reading_never_refutes_slot_7(
    tmp_path: Path, transparent: str, opaque: str
) -> None:
    """A refutation sends the owner to change the extractor; a value no slot can hold says the
    read went wrong, not that slot 7 is not the transparency."""
    body = report(probe_file(tmp_path, seat(transparent=transparent, opaque=opaque)))

    assert body["verdict"] == "inconclusive"
    assert body["slot_7_refuted"] is False
    assert "PROBE2-BLOCK-1" in body["reason"], body["reason"]


def test_a_file_with_no_probe_2_section_is_inconclusive(tmp_path: Path) -> None:
    body = report(probe_file(tmp_path, text="probe: standards\nprobe-1 exploded_state:\n"))

    assert body["verdict"] == "inconclusive"
    assert "probe-2" in body["reason"]


def test_two_probe_2_sections_are_inconclusive(tmp_path: Path) -> None:
    once = SAMPLE.read_text(encoding="utf-8")

    body = report(probe_file(tmp_path, text=once + once))

    assert body["verdict"] == "inconclusive"
    assert "probe-2" in body["reason"]


# --- reading what the seat wrote ----------------------------------------------------------------


def test_a_windows_powershell_redirect_reads_the_same(tmp_path: Path) -> None:
    """`>` in Windows PowerShell 5.1 writes UTF-16 with a byte-order mark and CRLF."""
    text = SAMPLE.read_text(encoding="utf-8").replace("\n", "\r\n")
    path = tmp_path / "redirected.txt"
    path.write_bytes(codecs.BOM_UTF16_LE + text.encode("utf-16-le"))

    assert report(path)["verdict"] == ZERO_IS_OPAQUE


def test_a_utf8_file_with_a_byte_order_mark_reads_the_same(tmp_path: Path) -> None:
    path = tmp_path / "bom.txt"
    path.write_bytes(codecs.BOM_UTF8 + SAMPLE.read_bytes())

    assert report(path)["verdict"] == ZERO_IS_OPAQUE


def test_the_blocks_can_be_named_and_are_matched_by_their_own_name_in_a_nested_key(
    tmp_path: Path,
) -> None:
    lines = [
        component("cmp:0002", "SUB-1/CLEAR-1", values=slots(0.5)),
        component("cmp:0003", "SUB-1/SOLID-1", values=slots(1)),
        component("cmp:0004", "SUB-1/BARE-1", "False"),
    ]
    names = ["--transparent", "clear-1", "--opaque", "SOLID-1", "--plain", "Bare-1"]

    assert report(probe_file(tmp_path, lines), *names)["verdict"] == ONE_IS_OPAQUE


def test_a_missing_file_is_a_usage_error(tmp_path: Path) -> None:
    result = decide(tmp_path / "absent.txt")

    assert result.exit_code == 2
    assert "does not exist" in plain_words(result.output)
