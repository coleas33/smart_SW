"""Shared pytest configuration and fixtures.

Integration tests need a saved native evidence package produced on the SOLIDWORKS
workstation. They are skipped, not failed, when it is absent (plan.md, Testing).

`live` tests call a real provider API and are skipped, not failed, when that provider's
key is absent from the environment - the same convention, so a checkout with neither a
native package nor a key runs the whole suite green.

`perf` and `simulation` tests are the exception to that convention: they are not collected
at all unless the run asks for them by marker. See `pytest_ignore_collect` below.

Two properties of the environment are settled here, once, for every test (see
`COLOUR_FORCING_ENV` and `pytest_configure`): Typer's help is rendered without colour even
where CI forces it, and a run whose temporary folder lies inside the checkout is refused.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage, Manifest
from tests.support.packages import build_manifest, build_package

REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_PACKAGE = REPO_ROOT / "benchmarks" / "packages" / "bracket-assy" / "native" / "package.json"

COLOUR_FORCING_ENV: tuple[str, ...] = ("GITHUB_ACTIONS", "FORCE_COLOR", "PY_COLORS")
"""Variables that make Typer's Rich console a colour terminal; removed before Typer loads.

`typer.rich_utils` reads them once, at import, and any one set makes every `--help` and usage
error interleave ANSI codes, often one per dash of an option name, so `"--jobs" in output`
fails under GitHub Actions and passes in a developer's shell. Removing them here, before any
test module imports `swreview.cli`, gives every help-text assertion the plain text a local
run sees - the one fix, so a new help test cannot regress it. (`tests/support/console.py`'s
`plain` helpers predate it and still do no harm.) Nothing in `src` or `tests` reads these
variables for any other purpose; subprocesses the tests start inherit the cleaned
environment too. `tests/unit/test_conftest_environment.py` pins both halves.
"""

for _name in COLOUR_FORCING_ENV:
    os.environ.pop(_name, None)
if "typer.rich_utils" in sys.modules and sys.modules["typer.rich_utils"].FORCE_TERMINAL:
    # A plugin imported Typer before this file ran, so its console already forces colour.
    raise RuntimeError(
        "typer.rich_utils was imported before tests/conftest.py could remove "
        f"{', '.join(COLOUR_FORCING_ENV)}; help-text tests would see ANSI codes"
    )


def basetemp_inside_checkout(
    basetemp: str | os.PathLike[str] | None, temproot: str | os.PathLike[str], root: Path
) -> Path | None:
    """The run's temporary folder, resolved, when it lies inside the checkout at `root`.

    `basetemp` is `--basetemp` (None when not given), in which case pytest uses a folder under
    `temproot` (`PYTEST_DEBUG_TEMPROOT` or the system temporary folder), so that is the folder
    tested. Resolved, as `benchmark.sets.checkout_relative` resolves, so a relative path, `..`
    or symlink counts where it leads; a sibling whose name only begins with the root's is
    outside.
    """
    folder = Path(basetemp if basetemp is not None else temproot).resolve()
    return folder if folder.is_relative_to(root.resolve()) else None


def pytest_configure(config: pytest.Config) -> None:
    """Refuse a run whose `tmp_path` folders would lie inside this checkout.

    The benchmark code names a path inside the checkout relative to it and refuses or
    reroutes some that lie inside it (`benchmark/sets.checkout_relative`: case-file names,
    `runner.committable`, compare's ledger folder, FR-051). That is the product behaving as
    specified, but every test that builds a fictional set under `tmp_path` assumes `tmp_path`
    is *outside* the checkout, so `--basetemp=.pytest-tmp` turned ~90 of them red with
    messages about path spellings. One usage error here names the cause instead; skipping
    those tests would hide them. The default (no `--basetemp`) is the system temporary
    folder, outside any ordinary checkout.
    """
    temproot = os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()
    inside = basetemp_inside_checkout(config.option.basetemp, temproot, REPO_ROOT)
    if inside is not None:
        raise pytest.UsageError(
            f"the pytest temporary folder {inside} lies inside the checkout {REPO_ROOT}; "
            "the benchmark tests need tmp_path outside it (benchmark/sets.checkout_relative). "
            "Pass --basetemp=<a folder outside the checkout>, or omit it."
            + ("" if config.option.basetemp else f" (The system temporary folder is {temproot}.)")
        )


LIVE_KEYS: tuple[str, ...] = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
"""Every environment variable a `live` test may need; collection runs them only if one is set.

This gate is deliberately coarse - it answers "is this checkout wired to any provider at
all?". Which *particular* key a live module needs is that module's own business, and each
one skips itself when its provider's key is the one that is missing, so a seat holding
only an OpenAI key does not turn the Gemini live test red and vice versa.
"""


PERF_DIR = (Path(__file__).parent / "perf").resolve()
"""Collected only on request; see `pytest_ignore_collect`.

Resolved, and compared against a resolved `collection_path`, because the comparison fails
*open*: a symlinked checkout or a rootdir pytest never resolved would hand the hook a path
that names this directory without being `==` to it, and the budgets would quietly rejoin
the default run. `tests/unit/test_perf_collection_gate.py` pins that case.
"""

SIMULATION_DIR = (Path(__file__).parent / "simulation").resolve()
"""The reference sweep, collected only on request with the same resolved-path rule."""


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Keep perf and simulation folders out unless `-m` names their respective marker.

    A perf test asserts a wall-clock budget, so it measures the machine as much as the
    code: on a loaded laptop or a shared runner it goes red with no commit at fault. It
    is therefore out of the default run (`uv run pytest -m "not live"`) and out of CI.
    The simulation reference sweep takes several minutes and is also run deliberately.

    Not *collected*, rather than skipped the way `integration` and `live` are: those two
    skip because this checkout is missing an input, and the skip line is the useful
    report that it is. A budget reported as "skipped" on every run would instead read as
    a measurement that was considered, which it was not. Run them deliberately:

        uv run pytest -m perf -s
        uv run pytest -m simulation -s
    """
    resolved = collection_path.resolve()
    for directory, marker in ((PERF_DIR, "perf"), (SIMULATION_DIR, "simulation")):
        if resolved == directory and marker not in config.getoption("markexpr"):
            return True
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skips: list[tuple[str, pytest.MarkDecorator]] = []
    if not NATIVE_PACKAGE.exists():
        reason = f"native package not present: {NATIVE_PACKAGE}"
        skips.append(("integration", pytest.mark.skip(reason=reason)))
    if not any(os.environ.get(name) for name in LIVE_KEYS):
        reason = f"no provider key set: {', '.join(LIVE_KEYS)}"
        skips.append(("live", pytest.mark.skip(reason=reason)))
    for item in items:
        for marker, skip in skips:
            # The applied marker, not `item.keywords`, which also holds the directory name:
            # a test that lives in `tests/integration/` but needs no native package - the
            # lever 7 stop, replayed through `respx` - would otherwise never run anywhere.
            if item.get_closest_marker(marker) is not None:
                item.add_marker(skip)


REQUIRE_TOKENIZER_ENV = "SWREVIEW_REQUIRE_TOKENIZER"
"""Set to `1` by CI and `update-workstation.ps1`: a missing vocabulary fails, not skips."""


@pytest.fixture
def vocabulary() -> Path:
    """The folder holding the `o200k_base` vocabulary, loaded and hash-checked.

    The file is not in the repository (008 `contracts/tokenizer.md` section 2): each machine
    fetches it once with `swreview tokenizer fetch`. Where it is absent, a test that needs an
    exact token count is **skipped** with that command in the reason - unless
    `SWREVIEW_REQUIRE_TOKENIZER=1`, which CI and the workstation update script set so that a
    missing file is a failure there rather than a silently thinner run.
    """
    from swreview.tokens import TokenizerUnavailable, encoding, tokenizer_dir

    try:
        encoding()
    except TokenizerUnavailable as exc:
        if os.environ.get(REQUIRE_TOKENIZER_ENV) == "1":
            pytest.fail(f"{REQUIRE_TOKENIZER_ENV}=1 and the tokenizer is unavailable: {exc}")
        pytest.skip(str(exc))
    return tokenizer_dir()


@pytest.fixture
def validated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Feature 011's drawing binding switch on, as T066 will set it once a seat validates it.

    `drawings/binding.DRAWING_BINDING_VALIDATED` ships false (FR-024). The binding's tests set
    it with this fixture, and the tests of the switch-off behaviour set it off with
    `not_validated` rather than reading the shipped value, so T066's flip is one edit that turns
    exactly one test red by design: `test_drawing_binding.test_the_switch_ships_off`, the pin
    (011 T096; `tests/unit/test_binding_switch_flip.py` holds the rule).
    """
    from swreview.drawings import binding

    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", True)


@pytest.fixture
def not_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Feature 011's drawing binding switch off, whatever the shipped value (see `validated`)."""
    from swreview.drawings import binding

    monkeypatch.setattr(binding, "DRAWING_BINDING_VALIDATED", False)


@pytest.fixture
def make_package() -> Callable[..., EvidencePackage]:
    """Build a minimal valid `EvidencePackage`; keyword arguments replace top-level fields."""
    return build_package


@pytest.fixture
def fake_manifest() -> Manifest:
    """The manifest of `make_package`: one entry per document, no discrepancies."""
    return build_manifest()


@pytest.fixture
def tmp_package_dir(tmp_path: Path) -> Path:
    """A directory holding a written `package.json` from `make_package`."""
    directory = tmp_path / "package"
    save_package(build_package(), directory)
    return directory
