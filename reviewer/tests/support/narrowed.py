"""Recordings made by an older type table, for the narrowed outcome (008 T124, owner decision 23A).

`contracts/replay.md` section 5: a recorded `rms.*` finding is narrowed when it lost only the
subjects the current type table stopped counting as content. The replay's tests and the fixture
generator's both need the same recording: a part with a system row loose above its one group,
recorded by a copy of the shipped table that still counted that row's type as content, and
replayed - or regenerated - by the shipped table, which tolerates it. That is the shape of every
recording made before a table change, feature 003's decision 20A among them.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from swreview.agent.providers.fake import ScriptedToolCall
from swreview.benchmark.replay import TurnPlan
from swreview.checks import rms_types
from swreview.checks.rms_types import DEFAULT_TYPES_PATH
from swreview.findings import Finding
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage, Feature
from swreview.report.session import load_session
from tests.support.features import AssemblySpec, PartSpec, feature, folder, rms_package
from tests.support.replay import record_scripted_review

__all__ = [
    "BOSS",
    "CORE",
    "HISTORY",
    "LOOSE",
    "PART",
    "RMS_PART",
    "SCRIPT",
    "SENSORS",
    "SUMMARY",
    "SYSTEM_TYPE",
    "WIDGET",
    "loose_findings",
    "older_table",
    "part_package",
    "record",
    "row_named",
]

SYSTEM_TYPE = "SensorFolder"
"""Tolerated by the shipped table (feature 003); content to the older table the recordings are
made with."""
PART = "doc:3"
SENSORS = "Sensors"
"""The system row: a loose subject when recorded, not content today."""
WIDGET = "Widget1"
"""A type no table knows: content to both tables, so loose in both."""
HISTORY = "History"
"""Another system row (`HistoryFolder`), tolerated by both tables: never a subject."""
BOSS = "Boss1"
"""Content inside the core group: never loose."""
CORE = "3-Core"
LOOSE = "rms.grouping.all_features_in_a_group"
SUMMARY = ScriptedToolCall("get_package_summary")
RMS_PART = ScriptedToolCall("check_rms_part", {"document_id": None})
SCRIPT = [TurnPlan(rounds=((SUMMARY,), (RMS_PART,)), text="Done.")]
"""The part check at step 1, after a summary that records no finding."""


def part_package(
    share: tuple[str, str] | None = None, document_id: str = PART
) -> EvidencePackage:
    """A part with a system row and an unknown row loose above its one group.

    `share=(name, other)` gives the row `name` the persistent reference of the row `other`, as
    real packages share one reference between system folders. `document_id` names the part.
    """
    package = rms_package(
        parts=[
            PartSpec(
                document_id=document_id,
                name="housing",
                features=[
                    feature(SENSORS, SYSTEM_TYPE),
                    feature(WIDGET, "Frobnicate"),
                    feature(HISTORY, "HistoryFolder"),
                    folder(CORE, feature(BOSS, "Extrusion")),
                ],
            )
        ],
        assembly=AssemblySpec(),
    )
    if share is None:
        return package
    name, other = share
    reference = row_named(package, other).persist_ref
    return package.model_copy(
        update={
            "features": [
                row.model_copy(update={"persist_ref": reference}) if row.name == name else row
                for row in package.features
            ]
        }
    )


def row_named(package: EvidencePackage, name: str) -> Feature:
    [row] = [row for row in package.features if row.name == name]
    return row


def older_table(directory: Path, counted: Sequence[str] = (SYSTEM_TYPE,)) -> Path:
    """A copy of the shipped type table that still counts each of `counted` as content."""
    document = yaml.safe_load(DEFAULT_TYPES_PATH.read_text(encoding="utf-8"))
    missing = sorted(set(counted) - set(document["tolerated_loose"]))
    assert not missing, f"the shipped table does not tolerate {missing}"
    document["tolerated_loose"] = [
        name for name in document["tolerated_loose"] if name not in counted
    ]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "rms_types.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def record(
    out: Path,
    package: EvidencePackage,
    table: Path | None = None,
    turns: Sequence[TurnPlan] = SCRIPT,
) -> Path:
    """A scripted recording of `package` in the new folder `out`, made by `table` (the shipped
    one when `None`) playing `turns`. The package is saved beside `out`, in `<out>-package`."""
    package_dir = out.with_name(f"{out.name}-package")
    save_package(package, package_dir)
    with pytest.MonkeyPatch.context() as patched:
        if table is not None:
            patched.setattr(rms_types, "DEFAULT_TYPES_PATH", table)
        return record_scripted_review(out, package_dir, turns)


def loose_findings(run: Path) -> list[Finding]:
    """The recorded `rms.grouping.all_features_in_a_group` findings of `run`."""
    return [f for f in load_session(run / "session.json").findings if f.check == LOOSE]
