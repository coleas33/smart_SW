"""Review receives the shared coverage warning before its first model turn completes."""

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.chat.server import create_app
from swreview.ir.loader import load_package, save_package
from swreview.ir.models import EvidencePackage
from swreview.report.unexamined import CANNOT_SEE, not_examined
from tests.support.packages import build_package
from tests.unit import test_chat_checks_routes as checks
from tests.unit import test_chat_standards_routes as standards
from tests.unit.test_chat_server import ORIGIN, TOKEN, ProviderControl, session_body
from tests.unit.test_unexamined import instance


@pytest.mark.parametrize("state", ["lightweight", "suppressed", "unloaded", "resolved"])
def test_review_start_returns_the_report_warning_before_the_model_finishes(
    tmp_path: Path, state: str
) -> None:
    package = build_package(
        components=[
            instance(1, "housing-1", "resolved"),
            instance(2, "DOWEL PIN-1", state),
            instance(3, "bracket-1", "resolved"),
            instance(4, "DOWEL PIN-2", state),
        ]
    )
    run_dir = tmp_path / "review"
    save_package(package, run_dir)
    provider = ProviderControl()
    provider.hold()
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=tmp_path,
        provider_factory=provider.factory,
        list_models=lambda _: [],
    )
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        try:
            response = client.post("/sessions", json=session_body(run_dir))
            assert response.status_code == 201, response.text
            block = response.json()["not_examined"]
            expected = not_examined(package)
            assert block == (expected.model_dump(mode="json") if expected else None)
            if state != "resolved":
                assert block["sentence"].startswith("2 of 4 component instances were not read:")
                assert block["headline"] == (
                    f"2 of 4 parts were not loaded: DOWEL PIN-1 and DOWEL PIN-2 ({state}). "
                    + CANNOT_SEE
                )
                assert [row["id"] for row in block["instances"]] == ["cmp:0002", "cmp:0004"]
        finally:
            provider.release()


def with_one_lightweight(package: EvidencePackage) -> EvidencePackage:
    """`package` with its second component instance lightweight."""
    first, second, *rest = package.components
    lightweight = second.model_copy(update={"suppression": "lightweight"})
    return package.model_copy(update={"components": [first, lightweight, *rest]})


def check_app(run_root: Path) -> Any:
    return create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=checks.refuse_provider,
        list_models=checks.refuse_provider,
    )


def test_the_model_check_body_carries_the_headline_beside_the_sentence(tmp_path: Path) -> None:
    package = with_one_lightweight(checks.model_check_package())
    check_dir = tmp_path / checks.CHECK_ID
    save_package(package, check_dir)
    expected = not_examined(package)
    assert expected is not None

    with TestClient(check_app(tmp_path), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        block = checks.start_check(client, check_dir)["not_examined"]

    assert block == expected.model_dump(mode="json")
    assert block["headline"] == expected.headline
    assert "cmp:" not in block["headline"]


def test_the_standards_body_carries_the_headline_beside_the_sentence(tmp_path: Path) -> None:
    package = with_one_lightweight(load_package(standards.SEEDED_PACKAGE.parent).package)
    check_dir = tmp_path / standards.STANDARDS_CHECK_ID
    save_package(package, check_dir)
    expected = not_examined(package)
    assert expected is not None

    with TestClient(check_app(tmp_path), headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        block = standards.start_standards(client, check_dir)["not_examined"]

    assert block == expected.model_dump(mode="json")
    assert block["headline"] == expected.headline
