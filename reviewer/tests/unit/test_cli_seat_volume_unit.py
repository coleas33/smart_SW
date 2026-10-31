"""`swreview seat volume-unit`: the unit of `IInterference.Volume`, judged (001 T106; 172A).

`IInterference.Volume`'s unit is undocumented (001 research R12, open question 5), so
`InterferenceRunner` records it as m3 with a gap until a seat measures it (`VolumeUnitVerified`,
001 T069). Decision 172A lets the engineer build two made-up cubes that overlap by a known volume
(`benchmarks/native/interference-volume/RECIPE.md`: 10 x 10 x 10 mm, 1000 mm3), dump them, run
interference, and hand the package to this judge with the known volume. It compares the recorded
number, whatever the package labels it, with the known overlap in m3 and in mm3, within 1 per cent:
one match is the answer; none is inconclusive, and says so when the number is the overlap in
cubic inches, a document's own unit.

Every package and record here is fictional and made in the test's temp folder.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from swreview.ir.loader import save_package
from swreview.ir.models import Volume
from tests.support.console import plain_words
from tests.unit.test_checks_interference import interference, package_with
from tests.unit.test_cli import invoke

OVERLAP_MM3 = 1000.0


def package_dir(tmp_path: Path, *rows: Any) -> Path:
    directory = tmp_path / "package"
    save_package(package_with(list(rows)), directory)
    return directory


def row(
    value: float | None, *, unit: str = "m3", status: str = "computed", name: str = "int:1"
) -> Any:
    volume = None if value is None else Volume(value=value, unit=unit)
    return interference(name, "cmp:0002", "cmp:0003", volume=volume, status=status)


def judge(path: Path, *extra: str, expected: str = "1000") -> Any:
    return invoke("seat", "volume-unit", str(path), "--expected-mm3", expected, *extra)


def answer(path: Path, *extra: str, expected: str = "1000") -> dict[str, Any]:
    result = judge(path, "--json", *extra, expected=expected)
    assert result.exit_code in (0, 1), result.output
    body: dict[str, Any] = json.loads(result.stdout)
    assert (result.exit_code == 1) == (body["unit"] == "inconclusive")
    return body


# --- the two answers ---------------------------------------------------------------------------


def test_the_overlap_recorded_in_cubic_metres_is_m3(tmp_path: Path) -> None:
    body = answer(package_dir(tmp_path, row(1e-6)))

    assert body["unit"] == "m3"
    assert body["recorded"] == {"value": 1e-6, "unit": "m3"}
    assert body["expected_mm3"] == OVERLAP_MM3
    assert "VolumeUnitVerified = true" in body["next"]
    assert "AssumedVolumeUnit" not in body["next"]


def test_the_overlap_recorded_in_cubic_millimetres_is_mm3_and_the_label_must_change(
    tmp_path: Path,
) -> None:
    body = answer(package_dir(tmp_path, row(1000.0)))

    assert body["unit"] == "mm3"
    assert "AssumedVolumeUnit = VolumeUnit.Mm3" in body["next"]
    assert "VolumeUnitVerified = true" in body["next"]


@pytest.mark.parametrize(("value", "unit"), [(1.009e-6, "m3"), (991.0, "mm3")])
def test_within_one_per_cent_is_a_match(tmp_path: Path, value: float, unit: str) -> None:
    assert answer(package_dir(tmp_path, row(value)))["unit"] == unit


@pytest.mark.parametrize("value", [1.02e-6, 980.0])
def test_beyond_one_per_cent_is_inconclusive(tmp_path: Path, value: float) -> None:
    body = answer(package_dir(tmp_path, row(value)))

    assert body["unit"] == "inconclusive"
    assert body["next"] is None


def test_another_known_overlap_is_judged_against_its_own_volume(tmp_path: Path) -> None:
    """A 10 x 10 x 5 mm overlap is 500 mm3: 5e-7 m3."""
    assert answer(package_dir(tmp_path, row(5e-7)), expected="500")["unit"] == "m3"


def test_the_text_answer_leads_with_the_unit(tmp_path: Path) -> None:
    result = judge(package_dir(tmp_path, row(1e-6)))

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "unit: m3"
    assert any(line.startswith("reason: ") for line in lines)
    assert any(line.startswith("next: ") for line in lines)
    assert str(tmp_path) not in result.stdout


# --- inconclusive -------------------------------------------------------------------------------


def test_the_overlap_in_cubic_inches_is_inconclusive_and_says_so(tmp_path: Path) -> None:
    """1000 mm3 is 0.0610237 in3: an assembly built from an inch template, not the recipe's."""
    body = answer(package_dir(tmp_path, row(0.0610237)))

    assert body["unit"] == "inconclusive"
    assert "in3" in body["reason"]


def test_a_number_matching_neither_is_inconclusive_and_names_it(tmp_path: Path) -> None:
    body = answer(package_dir(tmp_path, row(123.0)))

    assert body["unit"] == "inconclusive"
    assert "123" in body["reason"]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [row(None)],
        [row(None, status="failed")],
        [row(1e-6, status="truncated")],
    ],
    ids=["no rows", "no volume", "failed", "truncated"],
)
def test_no_computed_volume_is_inconclusive(tmp_path: Path, rows: list[Any]) -> None:
    body = answer(package_dir(tmp_path, *rows))

    assert body["unit"] == "inconclusive"
    assert "computed" in body["reason"]


def test_two_computed_volumes_are_inconclusive(tmp_path: Path) -> None:
    body = answer(package_dir(tmp_path, row(1e-6), row(1e-6, name="int:2")))

    assert body["unit"] == "inconclusive"
    assert "2 computed" in body["reason"]


# --- what it reads ------------------------------------------------------------------------------


def test_the_package_json_itself_reads_as_its_folder(tmp_path: Path) -> None:
    directory = package_dir(tmp_path, row(1e-6))

    assert answer(directory / "package.json")["unit"] == "m3"


def test_one_interference_record_reads_on_its_own(tmp_path: Path) -> None:
    record = tmp_path / "interference.json"
    record.write_text(row(1000.0).model_dump_json(), encoding="utf-8")

    assert answer(record)["unit"] == "mm3"


def test_a_file_that_is_neither_a_package_nor_a_record_is_an_error(tmp_path: Path) -> None:
    other = tmp_path / "other.json"
    other.write_text('{"fictional": true}', encoding="utf-8")

    result = judge(other)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "neither a package nor an interference record" in result.stderr


def test_an_error_names_the_path_as_it_was_given_and_no_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder with no `package.json`, passed relative: the message names `made-up-folder`,
    never the folders above it, which hold the user's name."""
    (tmp_path / "made-up-folder").mkdir()
    monkeypatch.chdir(tmp_path)

    result = invoke("seat", "volume-unit", "made-up-folder", "--expected-mm3", "1000")

    assert result.exit_code == 1
    assert "made-up-folder" in result.stderr
    assert "package.json" in result.stderr
    assert str(tmp_path) not in result.output


@pytest.mark.parametrize("kind", ["record", "package"])
def test_nothing_under_the_answer_keys_is_read(tmp_path: Path, kind: str) -> None:
    """`reject_answer_key_path`, the guard every reviewer read goes through, holds for a single
    record as for a package: refused before it is opened, in one sentence, with no traceback."""
    withheld = tmp_path / "benchmarks" / "answer_keys"
    if kind == "record":
        withheld.mkdir(parents=True)
        target = withheld / "interference.json"
        target.write_text(row(1e-6).model_dump_json(), encoding="utf-8")
    else:
        shutil.copytree(package_dir(tmp_path, row(1e-6)), withheld / "package")
        target = withheld / "package"

    result = judge(target)

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    assert "answer_keys" in result.stderr
    assert "neither a package" not in result.stderr


@pytest.mark.parametrize("expected", ["0", "-1000"])
def test_a_known_volume_that_is_not_positive_is_a_usage_error(
    tmp_path: Path, expected: str
) -> None:
    result = judge(package_dir(tmp_path, row(1e-6)), expected=expected)

    assert result.exit_code == 2
    assert "--expected-mm3" in plain_words(result.output)


def test_the_known_volume_is_required(tmp_path: Path) -> None:
    result = invoke("seat", "volume-unit", str(package_dir(tmp_path, row(1e-6))))

    assert result.exit_code == 2
    assert "--expected-mm3" in plain_words(result.output)
