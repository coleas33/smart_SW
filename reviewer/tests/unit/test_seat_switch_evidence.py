"""The seat switches go on only with committed evidence (feature 004 T338; owner decision 166A).

Three constants decide what a build lets a seat do, and all three ship off:

- `RemodelStart.SeatValidated` (`extractor/SwReview.Extractor/Rms/RemodelStart.cs`; 004 research
  R13.3) lets Start run. It may be true only if a ledger committed under
  `benchmarks/native/capabilities/` is one `swreview remodel ledger` judges ready - PROBE-1, 2, 3, 4
  and 12 verified, each with a reason and no error - and the IDENTITY tolerance profile is
  calibrated in `remodel/tolerances.py` (decision 170A);
- `DrawingOpenScope.SeatValidated` (`extractor/SwReview.Extractor/Sw/DrawingOpenScope.cs`; 011
  T077) lets the product open a confirmed drawing read-only, on probe D14's record;
- `DRAWING_BINDING_VALIDATED` (`reviewer/src/swreview/drawings/binding.py`; 011 T066) lets a
  drawing callout bind to a tolerance subject, on probes D6 and D8's record.

Feature 011's probes print a report of lines, not a machine-readable record, and a D6 or D8 report
holds design names and stays out of the repository (011 `contracts/probes.md` sections 1 and 3); so
each drawing switch may be true only if its named evidence file is committed here, in the form 004
research R27.5 records. Each constant is read from its source, as `test_standards_profile.py` reads
the C#, so the pins run in CI with no build. While every switch is off they pass; flipping any one
of them turns its pin red (R27.5 records each mutation).

A committed ledger is also held to decision 171A: the reader reads it (no path, the frozen
version), the committable-path scanner finds nothing in it, and every exception text in it is a type
and an HRESULT.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from swreview.remodel.ledger import Ledger, load_ledger, start_readiness
from swreview.remodel.tolerances import IDENTITY, Tolerances
from tests.support import local_paths
from tests.support.remodel_ledger import GOLDEN_LEDGER
from tests.support.seat_tasks import REPO

CAPABILITIES = REPO / "benchmarks" / "native" / "capabilities"
START_SOURCE = REPO / "extractor" / "SwReview.Extractor" / "Rms" / "RemodelStart.cs"
DRAWING_OPEN_SOURCE = REPO / "extractor" / "SwReview.Extractor" / "Sw" / "DrawingOpenScope.cs"
BINDING_SOURCE = REPO / "reviewer" / "src" / "swreview" / "drawings" / "binding.py"

DRAWING_OPEN_EVIDENCE = CAPABILITIES / "drawing-open.md"
"""Probe D14's record, the evidence `DrawingOpenScope.SeatValidated` needs (R27.5)."""

DRAWING_BINDING_EVIDENCE = CAPABILITIES / "drawing-binding.md"
"""Probes D6 and D8's record, the evidence `DRAWING_BINDING_VALIDATED` needs (R27.5)."""

CSHARP_SWITCH = re.compile(r"public static bool SeatValidated => (true|false);")
PYTHON_SWITCH = re.compile(r"^DRAWING_BINDING_VALIDATED: bool = (True|False)$", re.MULTILINE)

FAILURE = re.compile(r"\w+ 0x[0-9A-F]{8}(?:; \w+ 0x[0-9A-F]{8})*")
"""`ProbeText.Failure`'s form, the only exception text a committable ledger carries (171A)."""

CALIBRATED = IDENTITY.model_copy(update={"calibrated": True, "calibration_ref": "fictional"})


def switch_in(text: str, pattern: re.Pattern[str]) -> bool:
    """The one switch `pattern` finds in `text`; anything but exactly one is a failure."""
    [value] = pattern.findall(text)
    return value in ("true", "True")


def committed_ledgers(root: Path = CAPABILITIES) -> list[Path]:
    """Every probe ledger under `root`, at any depth: each `probe remodel` run's folder may be
    kept whole, so two runs' ledgers can share a name."""
    return sorted(root.rglob("remodel-*.yaml")) if root.is_dir() else []


def ready_for_start(root: Path = CAPABILITIES, identity: Tolerances = IDENTITY) -> list[Path]:
    """The ledgers under `root` the reader judges ready for Start."""
    return [
        path for path in committed_ledgers(root)
        if start_readiness(load_ledger(path), identity).ready
    ]


def exception_keys() -> set[str]:
    """The `raw_result` keys the C# fills with an exception's text, read from the source: the
    runner's `error`, and every key a probe body sets through `ProbeText.Failure`."""
    rms = REPO / "extractor" / "SwReview.Extractor" / "Rms"
    executors = (rms / "RemodelProbeExecutors.cs").read_text(encoding="utf-8")
    runner = (rms / "RemodelProbe.cs").read_text(encoding="utf-8")
    keys = set(re.findall(r'raw\["(\w+)"\] = (?:"error: " \+ )?ProbeText\.Failure\(', executors))
    assert "[ErrorKey] = HostFailure(error)" in runner
    assert 'public const string ErrorKey = "error";' in runner
    return keys | {"error"}


def unscrubbed(ledger: Ledger) -> list[str]:
    """`PROBE-n.key` for each exception text in `ledger` that is more than a type and an HRESULT;
    a call that answered (PROBE-5's `True`) is no exception text."""
    keys = exception_keys()
    return [
        f"{row.probe_id}.{key}"
        for row in ledger.probes
        for key, value in row.raw_result.items()
        if key in keys
        and not FAILURE.fullmatch(value.removeprefix("error: "))
        and not (key != "error" and value in ("True", "False"))
    ]


# --- the three switches -----------------------------------------------------------------------


def test_start_is_on_only_with_a_committed_ledger_judged_ready_and_identity_calibrated() -> None:
    start = switch_in(START_SOURCE.read_text(encoding="utf-8"), CSHARP_SWITCH)

    assert not start or (IDENTITY.calibrated and ready_for_start()), (
        "RemodelStart.SeatValidated is true, but no ledger committed under "
        "benchmarks/native/capabilities/ is judged ready by swreview remodel ledger, or IDENTITY "
        "is not calibrated (004 research R13.3 and R27.5)"
    )


def test_the_drawing_open_is_on_only_with_probe_d14s_committed_record() -> None:
    opens = switch_in(DRAWING_OPEN_SOURCE.read_text(encoding="utf-8"), CSHARP_SWITCH)

    assert not opens or DRAWING_OPEN_EVIDENCE.is_file(), (
        f"DrawingOpenScope.SeatValidated is true without {DRAWING_OPEN_EVIDENCE.name} "
        "(011 T077, 004 research R27.5)"
    )


def test_the_drawing_binding_is_on_only_with_probes_d6_and_d8s_committed_record() -> None:
    binds = switch_in(BINDING_SOURCE.read_text(encoding="utf-8"), PYTHON_SWITCH)

    assert not binds or DRAWING_BINDING_EVIDENCE.is_file(), (
        f"DRAWING_BINDING_VALIDATED is true without {DRAWING_BINDING_EVIDENCE.name} "
        "(011 T066, 004 research R27.5)"
    )


@pytest.mark.parametrize(
    ("source", "pattern", "off", "on"),
    [
        (START_SOURCE, CSHARP_SWITCH, "=> false;", "=> true;"),
        (DRAWING_OPEN_SOURCE, CSHARP_SWITCH, "=> false;", "=> true;"),
        (BINDING_SOURCE, PYTHON_SWITCH, "bool = False", "bool = True"),
    ],
    ids=["start", "drawing-open", "drawing-binding"],
)
def test_each_switch_ships_off_and_its_reader_sees_it_flipped(
    source: Path, pattern: re.Pattern[str], off: str, on: str
) -> None:
    """The reader finds each switch exactly once, off, and reads a flipped copy as on - so a flip
    reaches the pin above rather than slipping past a pattern that no longer matches."""
    text = source.read_text(encoding="utf-8")
    line = pattern.search(text)
    assert line is not None

    flipped = text[: line.start()] + line.group().replace(off, on) + text[line.end() :]

    assert (switch_in(text, pattern), switch_in(flipped, pattern)) == (False, True)


def test_the_readme_names_both_drawing_evidence_files() -> None:
    readme = (CAPABILITIES / "README.md").read_text(encoding="utf-8")

    for evidence in (DRAWING_OPEN_EVIDENCE, DRAWING_BINDING_EVIDENCE):
        assert f"`{evidence.name}`" in readme, evidence.name


# --- what a committed ledger holds (decision 171A) --------------------------------------------


def test_every_committed_ledger_is_read_scanned_clean_and_scrubbed() -> None:
    for path in committed_ledgers():
        ledger = load_ledger(path)

        assert local_paths.scan_file(path) == [], path.name
        assert unscrubbed(ledger) == [], path.name


def test_the_start_pin_judges_a_committed_folder_by_the_reader(tmp_path: Path) -> None:
    """The pin's own helpers on a folder like `benchmarks/native/capabilities/`: a run's folder
    kept whole, the golden ledger in it (which needs only IDENTITY), and a README beside it."""
    run = tmp_path / "2026-10-31-first-run" / "capabilities"
    run.mkdir(parents=True)
    shutil.copy(GOLDEN_LEDGER, run / GOLDEN_LEDGER.name)
    (tmp_path / "README.md").write_text("not a ledger\n", encoding="utf-8")

    assert committed_ledgers(tmp_path) == [run / GOLDEN_LEDGER.name]
    assert ready_for_start(tmp_path) == []
    assert ready_for_start(tmp_path, CALIBRATED) == [run / GOLDEN_LEDGER.name]
    assert committed_ledgers(tmp_path / "absent") == []


def test_the_scrub_check_finds_an_exception_message_and_passes_a_type(tmp_path: Path) -> None:
    golden = load_ledger(GOLDEN_LEDGER)
    message = tmp_path / GOLDEN_LEDGER.name
    message.write_text(
        GOLDEN_LEDGER.read_text(encoding="utf-8").replace(
            '"error": "COMException 0x80004005"', '"error": "Could not open the part."'
        ).replace(
            '"file_copy_error": "IOException 0x80070020"',
            '"file_copy_error": "The process cannot access the file."',
        ),
        encoding="utf-8",
    )

    assert exception_keys() == {
        "error", "reorder_to_folder", "move_to_folder", "make_sub_feature", "file_copy_error",
        "fallback_error",
    }
    assert unscrubbed(golden) == []
    assert unscrubbed(load_ledger(message)) == ["PROBE-13.file_copy_error", "PROBE-20.error"]
