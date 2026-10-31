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
version), the committable-path scanner finds nothing in it, every feature name in it is one the
probe gives what it builds, one of SOLIDWORKS's default part-template names or a placeholder (the
name scan, 004 T349), and every exception text in it is a type and an HRESULT. Every file under the
folder is scanned for a local folder and for a design named in a probe's printed forms.
"""

from __future__ import annotations

import ast
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from swreview.checks.rms_types import load_table
from swreview.remodel.ledger import FAILURE, Ledger, load_ledger, parse_ledger, start_readiness
from swreview.remodel.tolerances import IDENTITY, Tolerances
from tests.support import local_paths
from tests.support.remodel_ledger import (
    CALIBRATED,
    CAPABILITIES,
    GOLDEN_LEDGER,
    committed_ledgers,
    rendered_ledger,
)
from tests.support.seat_tasks import REPO

RMS = REPO / "extractor" / "SwReview.Extractor" / "Rms"
START_SOURCE = RMS / "RemodelStart.cs"
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
    executors = (RMS / "RemodelProbeExecutors.cs").read_text(encoding="utf-8")
    runner = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")
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


END_TAG = load_table().end_tag_suffix
"""What SOLIDWORKS names the marker after a folder's members in a flat walk, `<folder>___EndTag___`
(`rms_types.yaml`; PROBE-10's question)."""

PLACEHOLDER = r"<template feature \d+>"
"""What the person committing a ledger writes for each name the scan does not list, one number per
name, so PROBE-11's census keys stay distinct (the README's checklist; 004 T348)."""

TEMPLATE_NAMES = frozenset({
    "Favorites", "History", "Selection Sets", "Sensors", "Design Binder", "Annotations", "Notes",
    "Notes Area", "Markups", "Lights, Cameras and Scene", "Ambient", "Directional1",
    "Directional2", "Directional3", "Solid Bodies", "Surface Bodies", "Comments", "Equations",
    "Material <not specified>", "Front Plane", "Top Plane", "Right Plane", "Origin",
})
"""SOLIDWORKS's own English names for what a new part from its default template holds, as a walk
from `FirstFeature` lists them: the product's names, never a company's, so none needs scrubbing.
A template's own names - a renamed plane, a logo sketch, a company folder - are not here and fail
the scan. Not confirmed on the seat (004 research R27.10): a default this list lacks fails closed,
and is replaced by a placeholder or added here in a commit of its own."""

MARKER_REASON = re.compile(r"a marker-like name \('(.*)'\) was found but names neither")
"""PROBE-10's one reason that quotes a feature's name (`RemodelProbe10Logic.Decide`)."""

DESIGN_NAME = re.compile(
    r'name "[^"\n]*", view "|[^\s"\'`<>|/\\]+\.(?:sldprt|sldasm|slddrw)\b', re.IGNORECASE
)
"""The two forms in which a probe prints a design's name: a SOLIDWORKS document's file name, and
D6's and D8's dimension line, `name "D1@Sketch2", view "Drawing View1", value ...` (011
`contracts/probes.md` section 1). A space before the extension (`a .SLDPRT`) names no document,
nor does `<drawing>.SLDDRW`."""


def recipe_names() -> set[str]:
    """The names `probe remodel` gives what it builds, read from the C#: each step of
    `RemodelProbePartRecipe.Default()`, and the name PROBE-10 renames the recipe's folder to."""
    probe = (RMS / "RemodelProbe.cs").read_text(encoding="utf-8")
    executors = (RMS / "RemodelProbeExecutors.cs").read_text(encoding="utf-8")
    recipe = probe[probe.index("public static RemodelProbePartRecipe Default()"):]
    recipe = recipe[: recipe.index("\n    }\n")]
    return {
        *re.findall(r'const string \w+ = "([^"]+)";', recipe),
        *re.findall(r'new RemodelProbeFeatureStep\(\s*"([^"]+)"', recipe),
        *re.findall(r'const string renamed = "([^"]+)";', executors),
    }


def tree_keys() -> set[str]:
    """The `raw_result` keys the C# fills with a walk of the part's feature names joined by commas;
    and a check that the other readings that name a feature are the ones `unlisted_names` reads:
    PROBE-10's marker and its reason, and PROBE-11's census keys."""
    executors = (RMS / "RemodelProbeExecutors.cs").read_text(encoding="utf-8")
    assert '["marker_name_after"] = markerAfter ?? "(none)"' in executors
    assert "$\"a marker-like name ('{markerNameAfter}') was found but names neither" in executors
    assert 'raw[$"type[{name}]"] = typeName' in executors
    return set(re.findall(r'\["(\w+)"\] = string\.Join\(",", ', executors))


def unlisted_names(ledger: Ledger) -> list[str]:
    """`PROBE-n.key` for each reading in `ledger` that names a feature the probe did not build and
    SOLIDWORKS's default part template does not hold (decision 171A's name scan): the walked
    trees, PROBE-10's marker and the reason that quotes it, and PROBE-11's census keys, each given
    by its place among its row's readings, `type[#n]`, never by its name. Each name is matched
    whole: listed, a placeholder, or either with the end-tag marker after it."""
    listed = "|".join(re.escape(name) for name in sorted(recipe_names() | TEMPLATE_NAMES))
    name = f"(?:{listed}|{PLACEHOLDER})(?:{re.escape(END_TAG)})?"
    trees = tree_keys()
    found = []
    for row in ledger.probes:
        for place, (key, value) in enumerate(row.raw_result.items(), start=1):
            marker = MARKER_REASON.search(value) if key == "reason" else None
            if key in trees:
                text, pattern, label = value, f"(?:{name}(?:,{name})*)?", key
            elif key == "marker_name_after":
                text, pattern, label = value, rf"\(none\)|{name}", key
            elif key.startswith("type[") and key.endswith("]"):
                text, pattern, label = key[len("type["):-1], name, f"type[#{place}]"
            elif marker:
                text, pattern, label = marker.group(1), name, key
            else:
                continue
            if not re.fullmatch(pattern, text):
                found.append(f"{row.probe_id}.{label}")
    return found


def design_names(root: Path = CAPABILITIES) -> list[str]:
    """`<file>:<line>` for each line of a file under `root` that names a design in one of
    `DESIGN_NAME`'s forms."""
    return [
        f"{path.relative_to(root).as_posix()}:{number}"
        for path in sorted(root.rglob("*"))
        if path.is_file()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if DESIGN_NAME.search(line)
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


def lines(*code: str) -> str:
    """C# lines in place of the shipped declaration, each indented as it is."""
    return "\n    ".join(code)


UNREAD = {
    "start-a-getter-and-the-shipped-line-in-a-nested-class": (
        START_SOURCE,
        lines(
            "public static bool SeatValidated { get { return true; } }",
            f"public static class FictNested {{ {CSHARP_OFF} }}",
        ),
    ),
    "start-a-string-holding-a-line-comment-mark-and-a-declaration-under-if": (
        START_SOURCE,
        lines(
            f'private const string FictNote = "//"; {CSHARP_ON}',
            "#if FICT_NEVER", CSHARP_OFF, "#endif",
        ),
    ),
    "start-comment-marks-in-skipped-if-sections": (
        START_SOURCE,
        lines(
            "#if FICT_NEVER", "/*", "#endif", CSHARP_ON,
            "#if FICT_NEVER", "*/", CSHARP_OFF, "#endif",
        ),
    ),
    "start-raw-strings-holding-comment-marks": (
        START_SOURCE,
        lines(
            'private const string FictA = """', '    /*', '    """;', CSHARP_ON,
            'private const string FictB = """', f"    */ {CSHARP_OFF}", '    """;',
        ),
    ),
    "start-interpolation-holes-holding-strings": (
        START_SOURCE,
        lines(
            f'private const string FictA = $"{{"//"}}"; {CSHARP_ON}',
            rf'private const string FictB = $"{{"\""}} {CSHARP_OFF} {{"\""}}";',
        ),
    ),
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
on; and the third round's F2 and F3: a literal or a skipped `#if` section that a reader blind to
literals takes for a comment, and a getter beside the shipped line moved into a nested class).
Each must fail the reader, never read as off."""


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


READ_ON = {
    "strings-holding-comment-marks": lines(
        'private const string FictA = "/*";',
        CSHARP_ON,
        f'private const string FictB = "*/ {CSHARP_OFF}";',
    ),
    "a-region-name-holding-a-comment-mark": lines(
        "#region FICT /*", CSHARP_ON, "#endregion", f"// */ {CSHARP_OFF}"
    ),
    "a-character-literal-holding-a-quote": lines(
        f"""private const char FictQ = '"'; {CSHARP_ON} """
        f'private const string FictB = " {CSHARP_OFF} ";'
    ),
    "a-verbatim-string-ending-in-a-backslash": lines(
        rf'private const string FictA = @"\"; {CSHARP_ON} '
        f'private const string FictB = " {CSHARP_OFF} ";'
    ),
    "strings-holding-escaped-quotes": lines(
        rf'private const string FictA = "\"//"; {CSHARP_ON}',
        rf'private const string FictB = "\" {CSHARP_OFF} \"";',
    ),
}
"""Start's declaration turned on beside text that only looks like a comment or a declaration to
a reader that does not lex literals (the third round's review finding F2): the compiler reads
each as `true`, so the reader must too, and the Start pin goes red."""


@pytest.mark.parametrize("case", sorted(READ_ON))
def test_a_literal_or_a_directive_that_looks_like_a_comment_hides_no_declaration(case: str) -> None:
    text = START_SOURCE.read_text(encoding="utf-8")

    mutated = text.replace(CSHARP_OFF, READ_ON[case])

    assert mutated != text
    assert csharp_switch(mutated) is True


def test_the_readme_names_both_drawing_evidence_files() -> None:
    readme = (CAPABILITIES / "README.md").read_text(encoding="utf-8")

    for evidence in (DRAWING_OPEN_EVIDENCE, DRAWING_BINDING_EVIDENCE):
        assert f"`{evidence.name}`" in readme, evidence.name


# --- what a committed ledger holds (decision 171A) --------------------------------------------


def test_every_committed_ledger_is_read_scanned_clean_and_scrubbed() -> None:
    """*Changed on purpose by 004 T348*: the name scan joins the path scan, as 171A asks."""
    for path in committed_ledgers():
        ledger = load_ledger(path)

        assert local_paths.scan_file(path) == [], path.name
        assert unlisted_names(ledger) == [], path.name
        assert unscrubbed(ledger) == [], path.name


def test_nothing_committed_under_capabilities_names_a_local_folder() -> None:
    """Every file there, not only the ledgers: the drawing records, the README and a stray copy
    (004 T344, review finding F4: `scan_committable` does not reach `benchmarks/native`)."""
    assert local_paths.scan_folder(CAPABILITIES) == []


def test_nothing_committed_under_capabilities_names_a_design() -> None:
    """The drawing records too, which the README says hold never a name (004 T348)."""
    assert design_names() == []


# --- the name scan (decision 171A; 004 T348, the second review round's F1) ---------------------

FICT_NAME = "FICT-Corp Datum A"
"""A company template's own feature, which a public commit must never carry."""


def test_the_recipe_names_and_the_walked_trees_are_read_from_the_csharp() -> None:
    assert recipe_names() == {
        "Boss-Extrude1", "Cut-Extrude1", "Fillet1", "Shell1", "Folder1", "w",
        "Probe10RenamedFolder",
    }
    assert tree_keys() == {"tree_before", "tree_after_illegal", "tree_after_rename"}


def test_the_name_scan_finds_each_reading_naming_a_feature_neither_built_nor_default(
    tmp_path: Path,
) -> None:
    """The golden ledger with a company template's feature in each reading that names one; then
    with that name replaced by a placeholder. A census key is reported by its place among its
    row's readings, never by its name; the golden's own `FICT-Feature1` is one."""
    marker = FICT_NAME + END_TAG
    named = tmp_path / GOLDEN_LEDGER.name
    named.write_text(
        GOLDEN_LEDGER.read_text(encoding="utf-8")
        .replace('"tree_before": "', f'"tree_before": "Comments,{FICT_NAME},')
        .replace(
            '"marker_name_after": "(none)"',
            f'"marker_name_after": "{marker}"\n      "tree_after_rename": "Origin,{marker}"',
        )
        .replace(
            "no ___EndTag___ marker appeared on 2024, before or after the rename.",
            f"a marker-like name ('{marker}') was found but names neither the default nor the "
            "renamed folder.",
        )
        .replace('"type[Origin]"', f'"type[{FICT_NAME}]": "RefPlane"\n      "type[Origin]"'),
        encoding="utf-8",
    )

    assert unlisted_names(load_ledger(GOLDEN_LEDGER)) == ["PROBE-11.type[#9]"]
    assert unlisted_names(load_ledger(named)) == [
        "PROBE-3.tree_before",
        "PROBE-10.marker_name_after",
        "PROBE-10.tree_after_rename",
        "PROBE-10.reason",
        "PROBE-11.type[#3]",
        "PROBE-11.type[#10]",
    ]

    named.write_text(
        named.read_text(encoding="utf-8").replace(FICT_NAME, "<template feature 1>"),
        encoding="utf-8",
    )
    assert unlisted_names(load_ledger(named)) == ["PROBE-11.type[#10]"]


@pytest.mark.parametrize(
    ("tree", "listed"),
    [
        ("Comments,Front Plane,Boss-Extrude1,Fillet1,Fillet1,Folder1___EndTag___", True),
        ("Lights, Cameras and Scene,Material <not specified>,Origin,Probe10RenamedFolder", True),
        ("<template feature 1>,<template feature 12>,Shell1", True),
        ("", True),
        (f"Front Plane,{FICT_NAME}", False),
        ("Front Plane FICT", False),
        ("Lights,Origin", False),
        ("Front Plane,", False),
        ("<template feature>,Origin", False),
        ("FICT-Folder___EndTag___", False),
    ],
)
def test_a_walked_tree_names_only_the_recipe_the_default_template_and_placeholders(
    tree: str, listed: bool
) -> None:
    """Each name whole: a name with a comma in it is one name, a piece of a listed name or a
    listed name with more after it is none, and a marker is a listed name's."""
    ledger = parse_ledger(
        rendered_ledger([("PROBE-3", True, "verified", {"tree_before": tree, "reason": "r"})])
    )

    assert unlisted_names(ledger) == ([] if listed else ["PROBE-3.tree_before"])


def test_the_design_name_scan_finds_a_document_and_a_dimension_line(tmp_path: Path) -> None:
    (tmp_path / "drawing-open.md").write_text(
        "D14 outcome: opened and closed <drawing>\n"
        "D14 open: <drawing>.SLDDRW, type 3\n"
        "D14 left loaded: FICT-Bracket.SLDDRW\n",
        encoding="utf-8",
    )
    (tmp_path / "drawing-binding.md").write_text(
        "callout 3: face reference equal true, name shape matches true\n"
        'D8 dimension 3: sheet 1, name "D1@FICT-Sketch2", view "FICT View1", value 10.0000 mm;\n',
        encoding="utf-8",
    )
    shutil.copy(GOLDEN_LEDGER, tmp_path / GOLDEN_LEDGER.name)
    shutil.copy(CAPABILITIES / "README.md", tmp_path / "README.md")

    assert design_names(tmp_path) == ["drawing-binding.md:2", "drawing-open.md:3"]


def test_the_readme_gives_the_placeholder_the_name_scan_reads() -> None:
    readme = (CAPABILITIES / "README.md").read_text(encoding="utf-8")

    assert "`<template feature 1>`" in readme
    assert re.fullmatch(PLACEHOLDER, "<template feature 1>")


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
