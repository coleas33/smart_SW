"""Writing a live interference run into a run folder's `package.json` (feature 008 T039).

Checks first judges every group live detection found, and FR-009 wants the detected rows in
the run folder's package so a re-render reproduces the same findings. The write is the
reviewer's one write of `package.json`, so it is held to the strictest rules in the codebase
(research R2.18, RK-5):

- **the console's merge rule**: the rows of the reviewed configuration are replaced, every
  other configuration's are kept, new gaps are appended once;
- **values and key order kept**: a raw `json.loads` round trip, never a pydantic dump, so
  `created_at`'s seven-digit fraction survives and `reuse_key` stays in the first 8 KiB the
  package index reads;
- **re-validated before it is written**: the merged text must load as an `EvidencePackage`
  equal to the same merge done on the models;
- **atomic, or nothing**: a temporary file in the target folder and `os.replace`; any
  failure leaves every file byte-identical and no temporary file behind;
- **never the input folder of a command-line run**: with a different target the source is
  untouched and the merge lands in the target.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from swreview.ir import loader
from swreview.ir.loader import (
    PACKAGE_FILE_NAME,
    PackageAppendError,
    append_interference_run,
    load_package,
)
from swreview.ir.models import EvidencePackage, Gap, Interference
from tests.support.review_bridge import VOLUME_UNIT_GAP, interference_row

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "small-assembly-a"

NEW_GAP = Gap(
    kind="tool_error",
    entity_kind="interference",
    entity_id=None,
    reason="the host could not compute one pair of the run",
    error="a fictional host error",
)
"""A gap the fixture package does not already hold (it carries `VOLUME_UNIT_GAP`)."""


def test_the_fixture_already_carries_the_volume_unit_gap_so_a_live_run_adds_it_never() -> None:
    before = EvidencePackage.model_validate_json((FIXTURE / PACKAGE_FILE_NAME).read_bytes())

    assert Gap.model_validate(VOLUME_UNIT_GAP) in before.gaps


@pytest.fixture
def package_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "run"
    folder.mkdir()
    shutil.copyfile(FIXTURE / PACKAGE_FILE_NAME, folder / PACKAGE_FILE_NAME)
    return folder


def raw(folder: Path) -> dict[str, Any]:
    return json.loads((folder / PACKAGE_FILE_NAME).read_text(encoding="utf-8"))


def other_configuration_row(folder: Path) -> dict[str, Any]:
    """Append one row of another configuration to the copy, as a second dump would have."""
    data = raw(folder)
    first = data["interferences"][0]
    extra = {**first, "id": "int:0900", "configuration": "Other"}
    data["interferences"].append(extra)
    (folder / PACKAGE_FILE_NAME).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return extra


def new_rows(package: EvidencePackage) -> list[Interference]:
    a, b = package.components[0].id, package.components[1].id
    return [
        Interference.model_validate(interference_row("int:0001", (a, b), f"{a}|{b}", 0.0)),
        Interference.model_validate(interference_row("int:0002", (a, b), f"{a}|{b}", 42.0)),
    ]


def snapshot(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir())}


# --- the merge ---------------------------------------------------------------------------


def test_in_place_the_configuration_rows_are_replaced_and_the_others_kept(
    package_dir: Path,
) -> None:
    kept = other_configuration_row(package_dir)
    before = load_package(package_dir).package
    rows = new_rows(before)

    written = append_interference_run(
        package_dir, package_dir, "Default", rows, [NEW_GAP]
    )

    assert written == package_dir / PACKAGE_FILE_NAME
    after = load_package(package_dir).package
    assert [row.id for row in after.interferences] == [kept["id"], "int:0001", "int:0002"]
    assert after.interferences[1:] == rows
    assert NEW_GAP in after.gaps
    assert len(after.gaps) == len(before.gaps) + 1


def test_the_reloaded_package_equals_the_same_merge_done_on_the_models(
    package_dir: Path,
) -> None:
    before = load_package(package_dir).package
    rows = new_rows(before)
    gap = NEW_GAP

    append_interference_run(package_dir, package_dir, "Default", rows, [gap])

    expected = before.model_copy(
        update={
            "interferences": [i for i in before.interferences if i.configuration != "Default"]
            + rows,
            "gaps": [*before.gaps, gap],
        }
    )
    assert load_package(package_dir).package == expected


def test_an_identical_gap_is_not_appended_twice(package_dir: Path) -> None:
    before = load_package(package_dir).package
    gap = NEW_GAP

    append_interference_run(package_dir, package_dir, "Default", new_rows(before), [gap, gap])
    append_interference_run(package_dir, package_dir, "Default", new_rows(before), [gap])

    after = load_package(package_dir).package
    assert after.gaps.count(gap) == 1
    assert len(after.interferences) == 2, "a second run replaces, never grows"


def test_key_order_reuse_key_and_created_at_text_are_kept(package_dir: Path) -> None:
    original = (package_dir / PACKAGE_FILE_NAME).read_text(encoding="utf-8")
    created_at = json.loads(original)["created_at"]
    keys = list(json.loads(original))

    append_interference_run(
        package_dir, package_dir, "Default", new_rows(load_package(package_dir).package), []
    )

    text = (package_dir / PACKAGE_FILE_NAME).read_text(encoding="utf-8")
    assert list(json.loads(text)) == keys
    assert f'"created_at": "{created_at}"' in text
    assert len(created_at.split(".")[1].split("-")[0].split("+")[0]) == 7
    assert '"reuse_key"' in text.encode("utf-8")[:8192].decode("utf-8", errors="ignore")
    assert text.endswith("}\n")


def test_with_another_target_the_source_is_untouched_and_the_target_holds_the_merge(
    package_dir: Path, tmp_path: Path
) -> None:
    source_bytes = (package_dir / PACKAGE_FILE_NAME).read_bytes()
    target = tmp_path / "out"
    target.mkdir()
    rows = new_rows(load_package(package_dir).package)

    written = append_interference_run(package_dir, target, "Default", rows, [])

    assert (package_dir / PACKAGE_FILE_NAME).read_bytes() == source_bytes
    assert written == target / PACKAGE_FILE_NAME
    assert load_package(target).package.interferences == rows


# --- atomic, or nothing ------------------------------------------------------------------


def test_a_failed_replace_leaves_every_file_byte_identical_and_no_temporary_file(
    package_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = snapshot(package_dir)

    def refuse(*_: Any, **__: Any) -> None:
        raise PermissionError("the add-in holds package.json open")

    monkeypatch.setattr(loader.os, "replace", refuse)
    with pytest.raises(PermissionError):
        append_interference_run(
            package_dir,
            package_dir,
            "Default",
            new_rows(load_package(package_dir).package),
            [NEW_GAP],
        )

    assert snapshot(package_dir) == before


def test_a_row_that_fails_validation_raises_the_named_error_and_writes_nothing(
    package_dir: Path,
) -> None:
    before = snapshot(package_dir)
    bad = Interference.model_construct(
        **{**interference_row("int:0003", ("cmp:0001", "cmp:0002"), "k", 1.0), "status": "odd"}
    )

    with pytest.raises(PackageAppendError, match="int:0003|status"):
        append_interference_run(package_dir, package_dir, "Default", [bad], [])

    assert snapshot(package_dir) == before


def test_a_new_row_colliding_with_a_kept_rows_id_is_refused(package_dir: Path) -> None:
    kept = other_configuration_row(package_dir)
    before = snapshot(package_dir)
    package = load_package(package_dir).package
    a, b = package.components[0].id, package.components[1].id
    colliding = Interference.model_validate(interference_row(kept["id"], (a, b), f"{a}|{b}", 1.0))

    with pytest.raises(PackageAppendError, match=kept["id"]):
        append_interference_run(package_dir, package_dir, "Default", [colliding], [])

    assert snapshot(package_dir) == before


def test_a_missing_source_package_is_a_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        append_interference_run(tmp_path, tmp_path, "Default", [], [])
