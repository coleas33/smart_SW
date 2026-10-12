"""What the case generator may import (feature 014 T124; `generator.md` 9 and 11; SC-006; FR-027;
GN-5, RF-1, RF-48).

The generator writes every committed case from its specs, the fictional builders and the example
profile, and nothing derived from a check: so it may load the IR's models, the standards
profile's model and the three formats' data-only models it writes through, and no check, tool,
agent or key loader. Two halves:

1. **Direct imports, by `ast`.** Every module under `reviewer/tests/benchmark_cases/`, and every
   `tests.support` module they import (followed through `tests.support`'s own imports), imports
   no `swreview` module outside `ALLOWED` and nothing under `tests.checks`, whose
   `standards_fixtures` loads the standards check run (`tests/checks/golden_standards.py:39`).
   What the allowlisted `profile` module itself imports is allowed (research §8.9, settled). A
   planted import of a check, of the key's loader and of `tests.checks.standards_fixtures`, each
   in a temporary module the scan is pointed at, is named in its failure.
2. **The formats, transitively, by a fresh interpreter.** Each data-only format module the
   generator writes through, and `benchmark.digest`, imported alone, loads no `swreview.tools`,
   `swreview.agent` or `swreview.checks` module (RF-48); a temporary module importing
   `swreview.tools.refs` fails the same check, named with what it loaded (RF-1).
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REVIEWER = Path(__file__).resolve().parents[2]
"""`reviewer/`, the root `tests.*` module names resolve against."""

BENCHMARK_CASES = REVIEWER / "tests" / "benchmark_cases"

ALLOWED: frozenset[str] = frozenset(
    {
        "swreview.ir",
        "swreview.ir.models",
        "swreview.checks.standards.profile",
        "swreview.benchmark.answer_key_model",
        "swreview.benchmark.case_file",
        "swreview.benchmark.sets",
        "swreview.benchmark.families",
    }
)
"""`generator.md` 9's table: the only `swreview` modules a generator module may import."""

FORMAT_MODULES: tuple[str, ...] = (
    "swreview.benchmark.answer_key_model",
    "swreview.benchmark.case_file",
    "swreview.benchmark.sets",
    "swreview.benchmark.families",
    "swreview.benchmark.digest",
)
"""The data-only modules checked transitively: the four formats and `benchmark.digest`."""

FORBIDDEN_PREFIXES: tuple[str, ...] = ("swreview.tools", "swreview.agent", "swreview.checks")


def _is_module(name: str) -> bool:
    """Whether `name` is an importable module: `from a import b` imports the module `a.b`
    when there is one, and otherwise the name `b` out of `a`."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        # A parent that is a module, not a package, has no submodules to find.
        return False


def imports_of(path: Path) -> list[str]:
    """Every absolute module `path` imports, by `ast`: `import a.b` as `a.b`, and
    `from a import b` as `a.b` when that is a module and as `a` when `b` is a name in it, so
    `from swreview.ir import loader` is judged as `swreview.ir.loader`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                found.append(submodule if _is_module(submodule) else node.module)
    return list(dict.fromkeys(found))


def _support_file(module: str) -> Path | None:
    """The file of the `tests.support` module `module`, or `None` when it is none."""
    parts = module.split(".")
    candidate = REVIEWER.joinpath(*parts).with_suffix(".py")
    if parts[:2] == ["tests", "support"] and len(parts) > 2 and candidate.is_file():
        return candidate
    return None


def reach(paths: list[Path]) -> list[Path]:
    """`paths` and every `tests.support` module they import, followed through those modules'
    own imports, each once, in the order first reached."""
    reached: list[Path] = []
    queue = list(paths)
    while queue:
        path = queue.pop(0)
        if path in reached:
            continue
        reached.append(path)
        queue.extend(
            support
            for support in (_support_file(imported) for imported in imports_of(path))
            if support is not None
        )
    return reached


def scan(paths: list[Path]) -> list[str]:
    """Every offence of the modules `reach(paths)` reads, one line each naming the module (its
    path under `reviewer/`, or as given) and the import."""
    offences: list[str] = []
    for path in reach(paths):
        name = path.relative_to(REVIEWER).as_posix() if path.is_relative_to(REVIEWER) else path
        for imported in imports_of(path):
            if imported.startswith("tests.checks"):
                offences.append(f"{name} imports {imported}: no tests.checks module")
            elif imported.startswith("swreview") and imported not in ALLOWED:
                offences.append(f"{name} imports {imported}, outside generator.md 9's list")
    return offences


def generator_modules() -> list[Path]:
    return sorted(BENCHMARK_CASES.rglob("*.py"))


# --- 1. direct imports ---------------------------------------------------------------------


def test_the_generator_package_holds_modules_to_scan() -> None:
    """A scan over nothing would pass; the package and its modules must exist."""
    assert BENCHMARK_CASES.is_dir(), f"{BENCHMARK_CASES} does not exist"
    assert generator_modules(), f"{BENCHMARK_CASES} holds no module"


def test_no_generator_module_imports_a_check_a_tool_the_agent_or_the_key_loader() -> None:
    modules = generator_modules()
    assert modules, f"{BENCHMARK_CASES} holds no module"

    assert scan(modules) == []


def test_the_scan_follows_the_support_modules_the_generator_imports(tmp_path: Path) -> None:
    """A generator module importing `tests.support.drawings` brings `drawings`, and through it
    `mechanical` and `packages`, into the scan: each is read, and none offends."""
    module = tmp_path / "uses_sheets.py"
    module.write_text("from tests.support.drawings import SheetBuilder\n", encoding="utf-8")
    support = REVIEWER / "tests" / "support"

    assert reach([module]) == [
        module,
        support / "drawings.py",
        support / "mechanical.py",
        support / "packages.py",
    ]
    assert scan([module]) == []


def test_a_support_module_reached_is_held_to_the_same_list(tmp_path: Path) -> None:
    """`from tests.support import <module>` reaches the module as `import` does."""
    module = tmp_path / "uses_features.py"
    module.write_text("from tests.support import features\n", encoding="utf-8")

    assert REVIEWER / "tests" / "support" / "features.py" in reach([module])


@pytest.mark.parametrize(
    ("planted", "named"),
    [
        ("from swreview.tools import checks_fit\n", "swreview.tools.checks_fit"),
        ("import swreview.tools.checks_fit\n", "swreview.tools.checks_fit"),
        (
            "from swreview.benchmark.answer_key import load_answer_key\n",
            "swreview.benchmark.answer_key",
        ),
        ("from swreview.benchmark import answer_key\n", "swreview.benchmark.answer_key"),
        ("from tests.checks.standards_fixtures import card\n", "tests.checks.standards_fixtures"),
        # A module read out of an allowed package is judged as itself, not as the package.
        ("from swreview.ir import loader\n", "swreview.ir.loader"),
    ],
)
def test_a_planted_import_is_named_in_its_failure(tmp_path: Path, planted: str, named: str) -> None:
    module = tmp_path / "planted.py"
    module.write_text(planted, encoding="utf-8")

    offences = scan([module])

    assert len(offences) == 1, offences
    assert "planted.py" in offences[0]
    assert named in offences[0]


def test_the_allowed_imports_pass_and_only_the_offending_one_is_named(tmp_path: Path) -> None:
    """The allowlisted `profile` module and every format model pass; the scan names only the
    offending line."""
    module = tmp_path / "mixed.py"
    module.write_text(
        "from swreview.checks.standards.profile import load_profile\n"
        "from swreview.benchmark.answer_key_model import AnswerKey\n"
        "from swreview.benchmark import case_file, families, sets\n"
        "from swreview.ir.models import EvidencePackage\n"
        "from swreview.tools.refs import resolve_dimension\n",
        encoding="utf-8",
    )

    assert scan([module]) == [
        f"{module} imports swreview.tools.refs, outside generator.md 9's list"
    ]


# --- 2. the formats, transitively ----------------------------------------------------------


def loaded_forbidden(module: str, *, extra_path: Path | None = None) -> list[str]:
    """`module` imported alone in a fresh interpreter: one line per `swreview.tools`,
    `swreview.agent` or `swreview.checks` module it loaded, naming both."""
    code = (
        "import importlib, sys\n"
        f"importlib.import_module({module!r})\n"
        f"prefixes = {FORBIDDEN_PREFIXES!r}\n"
        "print('\\n'.join(sorted(name for name in sys.modules if name.startswith(prefixes))))\n"
    )
    env = dict(os.environ)
    if extra_path is not None:
        env["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(extra_path), env.get("PYTHONPATH")) if item
        )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REVIEWER,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return [f"{module} loads {name}" for name in completed.stdout.split()]


@pytest.mark.parametrize("module", FORMAT_MODULES)
def test_each_format_module_alone_loads_no_check_tool_or_agent_module(module: str) -> None:
    assert loaded_forbidden(module) == []


def test_a_module_importing_the_dimension_resolver_fails_naming_it(tmp_path: Path) -> None:
    (tmp_path / "planted_refs.py").write_text(
        "from swreview.tools.refs import resolve_dimension\n", encoding="utf-8"
    )

    offences = loaded_forbidden("planted_refs", extra_path=tmp_path)

    assert "planted_refs loads swreview.tools.refs" in offences
