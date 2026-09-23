"""SC-005: no company value from the release-checklist macro reaches this repository (T001).

SC-005 is measured three ways (`contracts/profile.md`, "How SC-005 measures this"). Two of
them live here; the third is the matched-pair run of `quickstart.md` scenario 6 (T098), which
is the only measurement that catches a value compiled into the source under a *different*
spelling.

**What `research.md` R5 still pins, and what it does not.** R5 records the **shape** of each
macro value and the constant it came from, not the value itself: the concrete values were
handed to the owner separately, because this repository is public. So "compare every
configured field against the R5 value" can only be taken literally for the two fields whose
shape still determines the value exactly - `part_number.pattern` (a digit/character grammar)
and `revision.cell` ("last row, column 0"). Those two are rebuilt from R5's prose here, at
run time, and compared; they are deliberately **not** written down in this file, because
writing them down is the leak this file exists to prevent.

For the eleven fields whose shape does not determine a value, the field-by-field half is what
the shape permits and what `contracts/profile.md` states: the three shipped profiles - the
example, `profile-a` and `profile-b` - must differ from **each other** in every value-bearing
field, and the YAML block in `contracts/profile.md` must be exactly what the example ships,
because the block is what a reviewer reads and copies. Three independent sets of fictional
values that agree nowhere cannot all be the macro's, and a leak into any one of them shows up
as an agreement with another.

The literal-scan half enforces the placeholder-vs-real rule `contracts/profile.md` states, in
the two places a real value could land:

1. **A census of profile-shaped data.** A populated `vault_root:` line may appear in exactly
   four files - the example, the two fixtures and the contract's own block. A real
   `standards.yaml` copied into the tree (the likeliest leak of all) is a fifth, and fails.
   The census reads YAML, Markdown, JSON and text only, so that the schema owner
   (`checks/standards/profile.py`) may keep declaring `vault_root` as a *field*; values in
   code are the next test's business.
2. **No profile value in the shipped source.** Every distinctive value of all three profiles -
   the vault root, the library folder names, the part-number pattern, the export-control
   phrase and the qualified data-card property names - must appear nowhere under
   `reviewer/src/` or the C# projects. The run learns all of it from the profile, so a value
   in the source is either a leak or a fallback, and there are no fallbacks (FR-002).

`specs/006-standards-check/research.md` is excluded from every scan as the single documented
exception (FR-001, SC-005, RK-1).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = REPO_ROOT / "specs" / "006-standards-check"
RESEARCH = SPEC_DIR / "research.md"
CONTRACT = SPEC_DIR / "contracts" / "profile.md"
EXAMPLE = REPO_ROOT / "config" / "standards.example.yaml"
FIXTURE_DIR = TESTS_ROOT / "fixtures" / "standards"
PROFILE_A = FIXTURE_DIR / "profile-a.yaml"
PROFILE_B = FIXTURE_DIR / "profile-b.yaml"

RESEARCH_REL = "specs/006-standards-check/research.md"
"""The single documented exception; excluded from every scan below."""

PROFILE_SOURCES: frozenset[str] = frozenset(
    {
        "config/standards.example.yaml",
        "reviewer/tests/fixtures/standards/profile-a.yaml",
        "reviewer/tests/fixtures/standards/profile-b.yaml",
        "specs/006-standards-check/contracts/profile.md",
    }
)
"""Every file in the tree that may carry profile *values*, as a set the census compares to."""

SOURCE_ROOTS: tuple[str, ...] = (
    "reviewer/src/",
    "extractor/SwReview.Extractor/",
    "extractor/SwReview.Extractor.Console/",
    "extractor/SwReview.AddIn/",
)
"""The shipped source. A profile value here is a leak or a fallback; both are refused."""


# --- R5: parsing the table, and rebuilding the two values its shapes still pin ---------

R5_HEADING = "## R5. The values the macro carried"
R5_HEADER: tuple[str, ...] = (
    "Profile field",
    "Shape of the value the macro carried",
    "Macro constant",
    "Note",
)

NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
PUNCTUATION_WORDS: dict[str, str] = {
    "a hyphen": "-",
    "a dash": "-",
    "an underscore": "_",
    "a period": ".",
    "a dot": ".",
}


def _table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
    return rows


@lru_cache(maxsize=1)
def r5_shapes() -> dict[str, str]:
    """`{profile field -> the shape R5 records}`, or a loud failure.

    Every assertion here exists so that a change to R5's shape is a red test rather than a
    silently empty map: a scan that matches nothing passes for the wrong reason.
    """
    text = RESEARCH.read_text(encoding="utf-8")
    start = text.find(R5_HEADING)
    assert start != -1, f"{RESEARCH_REL} no longer carries the heading {R5_HEADING!r}"
    end = text.find("\n## ", start + len(R5_HEADING))
    section = text[start:] if end == -1 else text[start:end]

    rows = _table_rows(section)
    assert len(rows) >= 3, f"R5 in {RESEARCH_REL} no longer carries a table"
    header, separator, *body = rows
    assert tuple(header) == R5_HEADER, (
        f"R5's table header is {header}, expected {list(R5_HEADER)}; this parser reads the "
        "first column as the profile field and the second as the shape"
    )
    assert all(set(cell) <= set(":-") and cell for cell in separator), (
        f"R5's table has no separator row under its header: {separator}"
    )

    shapes: dict[str, str] = {}
    for cells in body:
        assert len(cells) == len(R5_HEADER), f"R5 row {cells} does not have four cells"
        field = re.match(r"`([^`]+)`", cells[0])
        assert field is not None, f"R5 row {cells[0]!r} does not start with a profile field"
        assert field.group(1) not in shapes, f"R5 names {field.group(1)} twice"
        shapes[field.group(1)] = cells[1]

    assert len(shapes) >= 13, f"R5 lists only {len(shapes)} profile fields"
    return shapes


def macro_part_number_pattern(shape: str) -> str:
    """Rebuild the macro's part-number pattern from R5's prose.

    The pattern is a grammar, not a value - `#` is one digit and `?` is one character - so
    R5's shape sentence determines it exactly. It is rebuilt at run time and never written
    into this file.
    """
    out: list[str] = []
    for raw in re.split(r",| and ", shape):
        chunk = re.sub(r"^(?:then|and) ", "", raw.strip())
        if not chunk:
            continue
        if chunk in PUNCTUATION_WORDS:
            out.append(PUNCTUATION_WORDS[chunk])
            continue
        literal = re.fullmatch(r"`([^`]+)`", chunk)
        if literal is not None:
            out.append(literal.group(1))
            continue
        counted = re.fullmatch(r"(?:any )?([a-z]+) (digits?|characters?)", chunk)
        assert counted is not None, (
            f"R5's part_number.pattern shape no longer parses: {chunk!r} in {shape!r}"
        )
        count = NUMBER_WORDS.get(counted.group(1))
        assert count is not None, f"R5 spells a count this parser does not know: {chunk!r}"
        out.append(("#" if counted.group(2).startswith("digit") else "?") * count)

    pattern = "".join(out)
    assert len(pattern) >= 4, f"R5's part_number.pattern shape rebuilt to {pattern!r}"
    return pattern


def macro_revision_cell(shape: str) -> dict[str, int]:
    """Rebuild the macro's revision cell from R5's prose: a row from the end and a column."""
    parsed = re.fullmatch(r"(last|first) row, column ([0-9]+)", shape.strip())
    assert parsed is not None, f"R5's revision.cell shape no longer parses: {shape!r}"
    assert parsed.group(1) == "last", (
        f"R5's revision.cell shape says {parsed.group(1)!r} row, which this parser cannot "
        "express as a row counted from the end without the table's row count"
    )
    return {"row_from_end": 0, "column": int(parsed.group(2))}


# --- the profiles -----------------------------------------------------------------------


def load_yaml(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"{path} does not exist; SC-005 is measured over the three profiles"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} is not a YAML mapping"
    return data


@lru_cache(maxsize=1)
def contract_block() -> dict[str, Any]:
    """The example profile as `contracts/profile.md` prints it, which is what a reader copies."""
    blocks = re.findall(r"```yaml\n(.*?)```", CONTRACT.read_text(encoding="utf-8"), re.S)
    assert len(blocks) == 1, (
        f"{CONTRACT} carries {len(blocks)} YAML blocks; SC-005 reads the one schema example"
    )
    data = yaml.safe_load(blocks[0])
    assert isinstance(data, dict), "the YAML block in contracts/profile.md is not a mapping"
    return data


def profiles() -> dict[str, dict[str, Any]]:
    """The three profiles this repository ships, by the name a failure should name."""
    return {
        "config/standards.example.yaml": load_yaml(EXAMPLE),
        "tests/fixtures/standards/profile-a.yaml": load_yaml(PROFILE_A),
        "tests/fixtures/standards/profile-b.yaml": load_yaml(PROFILE_B),
    }


def leaves(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(leaves(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def value_bearing(data: Mapping[str, Any]) -> dict[str, Any]:
    """Every leaf but `version`, which the schema pins in every profile (1 or 2)."""
    return {name: value for name, value in leaves(data).items() if name != "version"}


def r5_field(leaf: str) -> str:
    """R5 names `revision.cell` as one value; the schema splits it into two integers."""
    return "revision.cell" if leaf.startswith("revision.cell.") else leaf


def _folded(value: Any) -> set[Any]:
    """A value as a set, so a list field and a scalar field compare the same way.

    A list of mappings - version 2's `general_tolerance.linear` bands - compares band by
    band: two profiles agree when they declare the same band, key for key.
    """
    items = value if isinstance(value, list) else [value]
    return {
        item.casefold()
        if isinstance(item, str)
        else tuple(sorted(item.items()))
        if isinstance(item, Mapping)
        else item
        for item in items
    }


def agree(left: Any, right: Any) -> bool:
    """True when two configured values share anything - equality, or a common list element."""
    return bool(_folded(left) & _folded(right))


# --- the tree ---------------------------------------------------------------------------

PRUNED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        # Claude Code's own folder: skills and workflows, and under `worktrees/` a whole second
        # checkout per background agent, which made the scan find every profile fixture twice.
        ".claude",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "bin",
        "obj",
        "dist",
        "build",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".vs",
        ".idea",
        "TestResults",
    }
)
TEXT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".md",
        ".yaml",
        ".yml",
        ".json",
        ".txt",
        ".cs",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".csproj",
        ".sln",
        ".props",
        ".targets",
        ".toml",
        ".cfg",
        ".ini",
        ".ps1",
        ".sh",
        ".xml",
    }
)
DATA_SUFFIXES: frozenset[str] = frozenset({".yaml", ".yml", ".md", ".json", ".txt"})
MAX_BYTES = 2_000_000


@lru_cache(maxsize=1)
def repository_files() -> tuple[tuple[str, str], ...]:
    """`(repo-relative posix path, text)` for every readable text file but the exception."""
    found: list[tuple[str, str]] = []
    stack = [REPO_ROOT]
    while stack:
        for entry in sorted(stack.pop().iterdir()):
            if entry.is_dir():
                if entry.name in PRUNED_DIRS or entry.name.startswith(".pytest-tmp"):
                    continue
                stack.append(entry)
                continue
            if entry.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if entry.stat().st_size > MAX_BYTES:
                continue
            relative = entry.relative_to(REPO_ROOT).as_posix()
            if relative == RESEARCH_REL:
                continue
            found.append((relative, entry.read_text(encoding="utf-8", errors="replace")))
    assert len(found) > 100, "the repository scan found almost nothing; the walk is wrong"
    return tuple(sorted(found))


POPULATED_VAULT_ROOT = re.compile(r"^[ \t]*vault_root[ \t]*:[ \t]*\S", re.M)


def distinctive_values(data: Mapping[str, Any]) -> set[str]:
    """The values `contracts/profile.md` calls distinctive enough for a literal scan.

    The vault root, the library folder names, the part-number pattern, the export-control
    phrase and the **qualified** data-card property names. The rest of the schema is single
    characters, small integers and ordinary English words (`revision.initial`,
    `material.configuration`), which a repository-wide scan would match everywhere.
    """
    flat = value_bearing(data)
    values: set[str] = set()
    for name in ("vault_root", "part_number.pattern", "export_control.phrase"):
        value = flat.get(name)
        if isinstance(value, str) and value:
            values.add(value)
    for name, value in flat.items():
        if name.startswith("library.") and isinstance(value, list):
            values.update(item for item in value if isinstance(item, str) and item)
    for item in flat.get("data_card.properties", []) or []:
        if isinstance(item, str) and " " in item:
            values.add(item)
    return {value for value in values if len(value) >= 6}


# --- (a) the field-by-field comparison ---------------------------------------------------


def test_the_r5_table_parses_and_names_exactly_the_profile_fields() -> None:
    """The parser's own gate: R5 must still name every field the schema carries."""
    fields = {r5_field(name) for name in value_bearing(load_yaml(EXAMPLE))}

    assert set(r5_shapes()) == fields, (
        "R5's table and the profile schema have drifted apart; a field with no R5 row is a "
        "field nobody checked for a leak"
    )


def test_every_shipped_profile_carries_exactly_the_same_fields() -> None:
    sources = {**profiles(), "contracts/profile.md": contract_block()}
    fields = {name: sorted(value_bearing(data)) for name, data in sources.items()}

    assert len(set(map(tuple, fields.values()))) == 1, f"the profiles disagree on fields: {fields}"


def test_the_contract_block_is_what_the_example_file_ships() -> None:
    """The block is what a reviewer reads and copies, so it is scanned as a profile too."""
    assert contract_block() == load_yaml(EXAMPLE)


def test_the_three_profiles_differ_in_every_value_bearing_field() -> None:
    sources = profiles()
    agreements: list[str] = []
    names = sorted(sources)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            left_fields, right_fields = value_bearing(sources[left]), value_bearing(sources[right])
            for field, value in left_fields.items():
                if agree(value, right_fields[field]):
                    agreements.append(f"{field}: {left} and {right} agree on {value!r}")

    assert agreements == [], (
        "three independent sets of fictional values must agree nowhere; an agreement is "
        "either a copied value or a real one"
    )


def test_no_profile_carries_the_macros_part_number_pattern() -> None:
    macro = macro_part_number_pattern(r5_shapes()["part_number.pattern"])
    sources = {**profiles(), "contracts/profile.md": contract_block()}

    offenders = [
        name
        for name, data in sources.items()
        if str(value_bearing(data)["part_number.pattern"]).casefold() == macro.casefold()
    ]

    assert offenders == [], f"{offenders} carry the macro's own part-number pattern"


def test_no_profile_carries_the_macros_revision_cell() -> None:
    macro = macro_revision_cell(r5_shapes()["revision.cell"])
    sources = {**profiles(), "contracts/profile.md": contract_block()}

    offenders = [
        name
        for name, data in sources.items()
        if {key: value_bearing(data)[f"revision.cell.{key}"] for key in macro} == macro
    ]

    assert offenders == [], (
        f"{offenders} carry the macro's own revision cell; contracts/profile.md's example is "
        "deliberately neither the last row nor column 0"
    )


# --- (b) the literal repository scan -----------------------------------------------------


def test_the_macros_part_number_pattern_appears_nowhere_in_the_tree() -> None:
    """The one distinctive macro value R5's shape still pins, scanned for literally."""
    macro = macro_part_number_pattern(r5_shapes()["part_number.pattern"])

    offenders = [name for name, text in repository_files() if macro in text]

    assert offenders == [], f"{offenders} carry the macro's part-number pattern {macro!r}"


def test_only_the_documented_files_carry_a_populated_standards_profile() -> None:
    """A real `standards.yaml` copied into the tree is a fifth carrier, and fails here."""
    carriers = {
        name
        for name, text in repository_files()
        if Path(name).suffix.lower() in DATA_SUFFIXES and POPULATED_VAULT_ROOT.search(text)
    }

    assert carriers == PROFILE_SOURCES


def test_no_profile_value_is_written_into_the_shipped_source() -> None:
    """Every value reaches the run from the profile; there is no fallback to compile in."""
    by_profile = {name: distinctive_values(data) for name, data in profiles().items()}
    for name, values in by_profile.items():
        assert len(values) >= 6, f"{name} yields too few distinctive values to scan for: {values}"
    values = set().union(*by_profile.values())

    offenders = [
        f"{name}: {value!r}"
        for name, text in repository_files()
        if name.startswith(SOURCE_ROOTS)
        for value in sorted(values)
        if value in text
    ]

    assert offenders == []
