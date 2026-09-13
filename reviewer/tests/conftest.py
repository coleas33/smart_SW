"""Shared pytest configuration and fixtures.

Integration tests need a saved native evidence package produced on the SOLIDWORKS
workstation. They are skipped, not failed, when it is absent (plan.md, Testing).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage, Manifest
from tests.support.packages import build_manifest, build_package

REPO_ROOT = Path(__file__).resolve().parents[2]
NATIVE_PACKAGE = REPO_ROOT / "benchmarks" / "packages" / "bracket-assy" / "native" / "package.json"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if NATIVE_PACKAGE.exists():
        return
    skip = pytest.mark.skip(reason=f"native package not present: {NATIVE_PACKAGE}")
    for item in items:
        if "integration" in item.keywords:
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
