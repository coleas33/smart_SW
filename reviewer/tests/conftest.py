"""Shared pytest configuration and fixtures.

Integration tests need a saved native evidence package produced on the SOLIDWORKS
workstation. They are skipped, not failed, when it is absent (plan.md, Testing).

`live` tests call a real provider API and are skipped, not failed, when that provider's
key is absent from the environment - the same convention, so a checkout with neither a
native package nor a key runs the whole suite green.

`perf` tests are the exception to that convention: they are not collected at all unless
the run asks for them by marker. See `pytest_ignore_collect` below.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage, Manifest
from tests.support.packages import build_manifest, build_package

REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_PACKAGE = REPO_ROOT / "benchmarks" / "packages" / "bracket-assy" / "native" / "package.json"

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


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Keep `tests/perf/` out of every run whose `-m` expression does not name `perf`.

    A perf test asserts a wall-clock budget, so it measures the machine as much as the
    code: on a loaded laptop or a shared runner it goes red with no commit at fault. It
    is therefore out of the default run (`uv run pytest -m "not live"`) and out of CI.

    Not *collected*, rather than skipped the way `integration` and `live` are: those two
    skip because this checkout is missing an input, and the skip line is the useful
    report that it is. A budget reported as "skipped" on every run would instead read as
    a measurement that was considered, which it was not. Run them deliberately:

        uv run pytest -m perf -s
    """
    if collection_path.resolve() == PERF_DIR and "perf" not in config.getoption("markexpr"):
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
