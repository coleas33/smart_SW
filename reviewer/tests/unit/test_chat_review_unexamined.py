"""Review receives the shared coverage warning before its first model turn completes."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from swreview.chat.server import create_app
from swreview.ir.loader import save_package
from swreview.report.unexamined import not_examined
from tests.support.packages import build_package
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
                assert [row["id"] for row in block["instances"]] == ["cmp:0002", "cmp:0004"]
        finally:
            provider.release()
