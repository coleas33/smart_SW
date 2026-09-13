"""Shared pytest configuration and fixtures.

Integration tests need a saved native evidence package produced on the SOLIDWORKS
workstation. They are skipped, not failed, when it is absent (plan.md, Testing).

`live` tests call a real provider API and are skipped, not failed, when that provider's
key is absent from the environment - the same convention, so a checkout with neither a
native package nor a key runs the whole suite green.
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skips: list[tuple[str, pytest.MarkDecorator]] = []
    if not NATIVE_PACKAGE.exists():
        reason = f"native package not present: {NATIVE_PACKAGE}"
        skips.append(("integration", pytest.mark.skip(reason=reason)))
    if not any(os.environ.get(name) for name in LIVE_KEYS):
        reason = f"no provider key set: {', '.join(LIVE_KEYS)}"
        skips.append(("live", pytest.mark.skip(reason=reason)))
    for item in items:
        for keyword, skip in skips:
            if keyword in item.keywords:
                item.add_marker(skip)


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
