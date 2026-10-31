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
the C#, so the pins run in CI with no build: the C# with its comments stripped, the Python from its
syntax tree, each from exactly one declaration in the one form shipped, so a switch turned on in any
other form fails its reader rather than being read past (004 T345). While every switch is off they
pass; flipping any one of them turns its pin red (R27.5 and R27.9 record each mutation).

A committed ledger is also held to decision 171A: the reader reads it (no path, the frozen
version), the committable-path scanner finds nothing in it, and every exception text in it is a type
and an HRESULT.
"""

from __future__ import annotations

import ast
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from swreview.remodel.ledger import Ledger, load_ledger, start_readiness
from swreview.remodel.tolerances import IDENTITY, Tolerances
from tests.support import local_paths
from tests.support.remodel_ledger import CAPABILITIES, GOLDEN_LEDGER, committed_ledgers
from tests.support.seat_tasks import REPO

START_SOURCE = REPO / "extractor" / "SwReview.Extractor" / "Rms" / "RemodelStart.cs"
DRAWING_OPEN_SOURCE = REPO / "extractor" / "SwReview.Extractor" / "Sw" / "DrawingOpenScope.cs"
BINDING_SOURCE = REPO / "reviewer" / "src" / "swreview" / "drawings" / "binding.py"

DRAWING_OPEN_EVIDENCE = CAPABILITIES / "drawing-open.md"
"""Probe D14's record, the evidence `DrawingOpenScope.SeatValidated` needs (R27.5)."""

DRAWING_BINDING_EVIDENCE = CAPABILITIES / "drawing-binding.md"
"""Probes D6 and D8's record, the evidence `DRAWING_BINDING_VALIDATED` needs (R27.5)."""

CSHARP_SWITCH = re.compile(r"public static bool SeatValidated => (true|false);")
CSHARP_DECLARATION = re.compile(r"\bSeatValidated\s*(?:=>|\{|=(?!=))")
"""Any declaration of `SeatValidated`: an expression body, a getter or a field's value."""
CSHARP_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
CSHARP_OFF = "public static bool SeatValidated => false;"
PYTHON_NAME = "DRAWING_BINDING_VALIDATED"
PYTHON_OFF = f"{PYTHON_NAME}: bool = False"

FAILURE = re.compile(r"\w+ 0x[0-9A-F]{8}(?:; \w+ 0x[0-9A-F]{8})*")
"""`ProbeText.Failure`'s form, the only exception text a committable ledger carries (171A)."""

CALIBRATED = IDENTITY.model_copy(update={"calibrated": True, "calibration_ref": "fictional"})


def csharp_switch(text: str) -> bool:
    """`SeatValidated` as a C# source declares it, read from its code, never its comments: exactly
    one declaration, and that one `public static bool SeatValidated => true|false;`. A getter, a
    field or a second declaration under `#if` fails this reader rather than being read past (004
    T345: a getter turning the switch on beside the old line commented out read as off)."""
    code = CSHARP_COMMENT.sub("", text)
    found = CSHARP_SWITCH.findall(code)
    assert len(CSHARP_DECLARATION.findall(code)) == len(found) == 1, (
        "SeatValidated is read only from one `public static bool SeatValidated => true|false;` "
        "outside comments"
    )
    return found[0] == "true"


def python_switch(text: str) -> bool:
    """`DRAWING_BINDING_VALIDATED` as `binding.py` binds it, read from its syntax tree, so never
    from a comment or a docstring: bound once in the whole module, at its top level, to the
    literal `True` or `False`. Bound again, or to anything else, fails this reader (004 T345)."""
    tree = ast.parse(text)
    stores = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == PYTHON_NAME and isinstance(node.ctx, ast.Store)
    ]
    values = [
        statement.value.value
        for statement in tree.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == PYTHON_NAME
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, bool)
    ]
    assert len(stores) == len(values) == 1, (
        f"{PYTHON_NAME} is read only from one module-level `{PYTHON_NAME}: bool = True|False`"
    )
    return values[0]


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
    start = csharp_switch(START_SOURCE.read_text(encoding="utf-8"))

    assert not start or (IDENTITY.calibrated and ready_for_start()), (
        "RemodelStart.SeatValidated is true, but no ledger committed under "
        "benchmarks/native/capabilities/ is judged ready by swreview remodel ledger, or IDENTITY "
        "is not calibrated (004 research R13.3 and R27.5)"
    )


def test_the_drawing_open_is_on_only_with_probe_d14s_committed_record() -> None:
    opens = csharp_switch(DRAWING_OPEN_SOURCE.read_text(encoding="utf-8"))

    assert not opens or DRAWING_OPEN_EVIDENCE.is_file(), (
        f"DrawingOpenScope.SeatValidated is true without {DRAWING_OPEN_EVIDENCE.name} "
        "(011 T077, 004 research R27.5)"
    )


def test_the_drawing_binding_is_on_only_with_probes_d6_and_d8s_committed_record() -> None:
    binds = python_switch(BINDING_SOURCE.read_text(encoding="utf-8"))

    assert not binds or DRAWING_BINDING_EVIDENCE.is_file(), (
        f"DRAWING_BINDING_VALIDATED is true without {DRAWING_BINDING_EVIDENCE.name} "
        "(011 T066, 004 research R27.5)"
    )


@pytest.mark.parametrize(
    ("source", "read", "off", "on"),
    [
        (START_SOURCE, csharp_switch, CSHARP_OFF, CSHARP_OFF.replace("false", "true")),
        (DRAWING_OPEN_SOURCE, csharp_switch, CSHARP_OFF, CSHARP_OFF.replace("false", "true")),
        (BINDING_SOURCE, python_switch, PYTHON_OFF, PYTHON_OFF.replace("False", "True")),
    ],
    ids=["start", "drawing-open", "drawing-binding"],
)
def test_each_switch_ships_off_and_its_reader_sees_it_flipped(
    source: Path, read: Callable[[str], bool], off: str, on: str
) -> None:
    """The reader finds each switch exactly once, off, and reads a flipped copy as on - so a flip
    reaches the pin above rather than slipping past a pattern that no longer matches.
    *Changed on purpose by 004 T344*: each switch's reader is named by its language rather than
    by a pattern."""
    text = source.read_text(encoding="utf-8")
    assert text.count(off) == 1

    assert (read(text), read(text.replace(off, on))) == (False, True)


CSHARP_ON = CSHARP_OFF.replace("false", "true")

UNREAD = {
    "start-a-block-getter-beside-the-old-line-commented": (
        START_SOURCE,
        f"// {CSHARP_OFF}\n    public static bool SeatValidated {{ get {{ return true; }} }}",
    ),
    "start-a-second-declaration": (
        START_SOURCE, f"#if FICT\n    {CSHARP_ON}\n#else\n    {CSHARP_OFF}\n#endif"
    ),
    "drawing-open-a-getter-beside-the-old-line-in-a-block-comment": (
        DRAWING_OPEN_SOURCE,
        f"/* {CSHARP_OFF} */\n    public static bool SeatValidated {{ get => true; }}",
    ),
    "drawing-open-a-field-beside-the-old-line-commented": (
        DRAWING_OPEN_SOURCE,
        f"// {CSHARP_OFF}\n    public static readonly bool SeatValidated = true;",
    ),
    "binding-bound-again-below": (
        BINDING_SOURCE, f"{PYTHON_OFF}\nDRAWING_BINDING_VALIDATED = True"
    ),
    "binding-not-a-literal": (
        BINDING_SOURCE, PYTHON_OFF.replace("= False", "= not False")
    ),
}
"""Each switch's declaration replaced by a form its reader does not read (review finding F5 of the
second reviewer: a commented old line kept the pin green while a new getter turned the switch
on). Each must fail the reader, never read as off."""


@pytest.mark.parametrize("case", sorted(UNREAD))
def test_a_switch_in_a_form_its_reader_does_not_read_fails_closed(case: str) -> None:
    source, replacement = UNREAD[case]
    binding = source == BINDING_SOURCE
    read, off = (python_switch, PYTHON_OFF) if binding else (csharp_switch, CSHARP_OFF)
    text = source.read_text(encoding="utf-8")

    mutated = text.replace(off, replacement)

    assert mutated != text
    with pytest.raises(AssertionError, match="read only"):
        read(mutated)


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


def test_nothing_committed_under_capabilities_names_a_local_folder() -> None:
    """Every file there, not only the ledgers: the drawing records, the README and a stray copy
    (004 T344, review finding F4: `scan_committable` does not reach `benchmarks/native`)."""
    assert local_paths.scan_folder(CAPABILITIES) == []


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
