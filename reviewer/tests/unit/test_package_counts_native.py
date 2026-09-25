"""The native sheet counts, only when there are any (feature 011 T024, FR-037).

`get_package_summary` and the opening package brief count the PDF-ingested sheets only
(`drawing_sheet_count`, `drawing_sheets=`), so a package whose drawings were read natively
said "0 drawing sheets" to the model. Each gains a native count - `native_drawing_sheet_count`
and `native_drawing_sheets=` - **omitted when it is zero**, so every package that carries no
native sheet, feature 008's replay fixtures among them, produces the bytes it produced before
this feature. `TODAY` holds those bytes' digests, taken from the tree before the change: a
digest that moves is a payload that moved.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from swreview.agent.package_brief import package_brief
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.tools.query import package_summary

TESTS = Path(__file__).resolve().parents[1]
DRAWINGS = TESTS / "fixtures" / "drawings"

TODAY: dict[str, tuple[str, str, int]] = {
    # (sha256[:16] of the summary JSON, of the brief, native sheets), before feature 011 T025.
    "fixtures/attention/check-folder": ("071acee33067b52f", "68254c3010306b06", 0),
    "fixtures/attention/review-folder": ("071acee33067b52f", "68254c3010306b06", 0),
    "fixtures/mechanical/big-assembly": ("12fc49448100bea6", "6ea0efd2910b07b8", 0),
    "fixtures/mechanical/small-assembly": ("a31f65543114ae57", "af42373b31a1829f", 0),
    "fixtures/mechanical/tolerances": ("53d5957528f48318", "53cf0c871122b1f2", 0),
    "fixtures/replay/big-assembly": ("8bd2ac126bd459eb", "99ccced8ae40549d", 0),
    "fixtures/replay/small-assembly-a": ("2a3cfc66e10d6ed2", "728fe7c25f147e6e", 0),
    "fixtures/replay/small-assembly-b": ("06f016850e3565e1", "0554a3c26ba29f8b", 0),
    "golden/fixtures/_smoke": ("29a9cc9e297de535", "2a4ce199772a3295", 0),
    "golden/fixtures/angle-not-length": ("eab35adb4cb414ca", "78b3508649429ac5", 0),
    "golden/fixtures/bracket-assy-interference": ("0853d93d193a1583", "14d0ebf610c89b8d", 0),
    "golden/fixtures/cover-blind-tap": ("dbba4226c0e1f0f3", "87f179b06b456d65", 0),
    "golden/fixtures/joint-bottoming": ("f8df1ccf2825d9d0", "aa122112190cbca9", 0),
    "golden/fixtures/joint-ok": ("f8df1ccf2825d9d0", "aa122112190cbca9", 0),
    "golden/fixtures/joint-unsupported": ("f8df1ccf2825d9d0", "aa122112190cbca9", 0),
    "golden/fixtures/mixed-units": ("4c1160b5d03154da", "c017d61574ee9ede", 0),
    "golden/fixtures/plate-stack": ("eab35adb4cb414ca", "8fcd0a985a2654c7", 0),
    # Feature 004, decision 17A (T143): new with that round, pinned from its own output.
    "golden/fixtures/remodel-plan/remodel-absorbed-sketches": (
        "e1cd36bf8bce5dda",
        "1e2f59b5fda3685c",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-cycle": ("05e828b7970bac7c", "04b9e6251a5d064c", 0),
    "golden/fixtures/remodel-plan/remodel-duplicate-names": (
        "02986fe1795b0812",
        "07b2816010781685",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-ordered": ("02a6a2a8a8dc61bd", "d021d3ea821349fc", 0),
    "golden/fixtures/remodel-plan/remodel-pinned": ("f67057186d2b6bc4", "97706938210eb587", 0),
    "golden/fixtures/remodel-plan/remodel-refusal-3d-interconnect": (
        "a80fb53db738981e",
        "a0d22cafe2b20e23",
        0,
    ),
    # Feature 004, decision 17A (T147): new with that round, pinned from its own output.
    "golden/fixtures/remodel-plan/remodel-refusal-derived-part": (
        "7ebccbb3eda03d4b",
        "5130cf677d8e9814",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-refusal-mesh-body": (
        "2e275cf9428c6317",
        "0b58b731215ddee9",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-refusal-multibody": (
        "64bf31d8e320b181",
        "39b4577f2b4c240a",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-refusal-rms-folder": (
        "4683aa1049bce171",
        "d316ee54e65bb218",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-refusal-sheet-metal": (
        "e5e5a6c4c1d9359f",
        "b9de11dfae888057",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-refusal-two-signals": (
        "e148d98bf239c0fe",
        "b644234cbd77ad9e",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-refusal-weldment": (
        "82bc3d94351dfcdc",
        "33c5f9d2df12c2ee",
        0,
    ),
    "golden/fixtures/remodel-plan/remodel-reversed": ("643a6e2404418731", "464d70c897a7878c", 0),
    "golden/fixtures/remodel-plan/remodel-unplaceable": (
        "dd6b39390282043e",
        "9d9934a3e3e9911a",
        0,
    ),
    "golden/fixtures/rms-assembly": ("93f8bbac677353b1", "6bdc9213d06aed98", 0),
    "golden/fixtures/rms-equations": ("c02c3ff858a2543a", "d4b2ac8c9d8d1977", 0),
    "golden/fixtures/rms-exceptions": ("7de329cb021de932", "7e4157b79eeeeb5b", 0),
    "golden/fixtures/rms-part": ("ee9c3e0646b7e88a", "c3829f39828c861f", 0),
    "golden/fixtures/shaft-bore": ("eab35adb4cb414ca", "78b3508649429ac5", 0),
    "golden/fixtures/standards-compliant": ("e3deaa7067cd96ee", "cd538879da7f7712", 2),
    "golden/fixtures/standards-compliant-flat": ("44ceafd60ba2ecdf", "385209320bd30754", 1),
    "golden/fixtures/standards-drawings/standards-drawings-compliant": (
        "14989c4365bbe9f4",
        "2da9d17556c5e093",
        2,
    ),
    "golden/fixtures/standards-drawings/standards-drawings-ingested": (
        "6483ca3aebccd03e",
        "d585e048c7d3d078",
        0,
    ),
    "golden/fixtures/standards-drawings/standards-drawings-no-views": (
        "567ef7c350f8ef54",
        "7798595df89ece23",
        1,
    ),
    "golden/fixtures/standards-drawings/standards-drawings-seeded": (
        "a4fdd389ac46b4b9",
        "62d2e8b737b5dad5",
        3,
    ),
    "golden/fixtures/standards-drawings/standards-drawings-two-models": (
        "dc4ad9b1a3e01d13",
        "21e19653e6ec3bac",
        1,
    ),
    "golden/fixtures/standards-multiplicity": ("771d2ff983b8bd82", "45a7b91728797d81", 0),
    "golden/fixtures/standards-profile-a": ("6e58d535a1c5cedb", "20cff637736b7658", 2),
    "golden/fixtures/standards-profile-b": ("4bedf3c2f442920f", "5bced95ccdfe378d", 2),
    "golden/fixtures/standards-seeded": ("f08b79c40b1ac47f", "ae1d8fc9a257890e", 1),
    "golden/fixtures/standards-seeded-second-subject": (
        "f08b79c40b1ac47f",
        "ae1d8fc9a257890e",
        1,
    ),
    "golden/fixtures/standards-unknown": ("6f499317928b1485", "782822ee80b30573", 1),
    "golden/fixtures/thread-mismatch": ("f8df1ccf2825d9d0", "aa122112190cbca9", 0),
    "golden/fixtures/tool-envelope": ("f8df1ccf2825d9d0", "aa122112190cbca9", 0),
}

SUMMARY_KEY = "native_drawing_sheet_count"
BRIEF_TOKEN = "native_drawing_sheets="


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def summary_text(summary: dict[str, object]) -> str:
    return json.dumps(summary, ensure_ascii=False)


def committed() -> list[str]:
    return sorted(
        path.parent.relative_to(TESTS).as_posix()
        for path in TESTS.rglob("package.json")
        if not path.parent.relative_to(TESTS).as_posix().startswith("fixtures/drawings/")
    )


def load(relative: str) -> EvidencePackage:
    return load_package(TESTS / relative).package


def test_every_committed_package_is_pinned() -> None:
    """A package added to the tree after this test was written is pinned here, deliberately."""
    assert committed() == sorted(TODAY)


@pytest.mark.parametrize("relative", [name for name, pin in TODAY.items() if pin[2] == 0])
def test_a_package_without_native_sheets_reads_exactly_as_before(relative: str) -> None:
    package = load(relative)
    summary_digest, brief_digest, _ = TODAY[relative]

    summary = package_summary(package)
    brief = package_brief(package)

    assert SUMMARY_KEY not in summary
    assert BRIEF_TOKEN not in brief
    assert digest(summary_text(summary)) == summary_digest
    assert digest(brief) == brief_digest


@pytest.mark.parametrize("relative", [name for name, pin in TODAY.items() if pin[2] > 0])
def test_a_package_with_native_sheets_gains_the_count_and_nothing_else(relative: str) -> None:
    package = load(relative)
    summary_digest, brief_digest, count = TODAY[relative]

    summary = package_summary(package)
    brief = package_brief(package)

    assert summary[SUMMARY_KEY] == count
    keys = list(summary)
    assert keys[keys.index(SUMMARY_KEY) - 1] == "drawing_sheet_count"
    del summary[SUMMARY_KEY]
    assert digest(summary_text(summary)) == summary_digest
    token = f" {BRIEF_TOKEN}{count}"
    assert brief.count(token) == 1
    assert digest(brief.replace(token, "")) == brief_digest


@pytest.mark.parametrize(
    ("name", "count"), [("plate-drawing", 2), ("drawing-root", 3), ("assembly-drawings", 4)]
)
def test_the_drawing_fixtures_count_every_native_sheet(name: str, count: int) -> None:
    package = load_package(DRAWINGS / name).package

    brief = package_brief(package)

    assert package_summary(package)[SUMMARY_KEY] == count
    assert f" {BRIEF_TOKEN}{count}\n" in brief
    assert f" drawing_sheets={len(package.drawings)} " in brief


def test_the_count_sits_beside_the_ingested_count_in_the_brief() -> None:
    package = load_package(DRAWINGS / "plate-drawing").package

    [line] = [row for row in package_brief(package).splitlines() if row.startswith("candidates:")]

    assert line.endswith(" native_drawing_sheets=2")
