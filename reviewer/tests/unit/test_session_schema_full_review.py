"""A real `session.json` from a full fixture review validates against 001's schema (decision 109A).

The verifier of 016 on 015 found that a pane review of the questions package fails
`review-session.schema.json`: the hygiene checks' findings about the root document
(`checks/hygiene.py`) carry no component and no drawing location, and the schema's `Finding`
required one of them. The schema now also accepts a finding that names its document scope in
`inputs`, beside its `provenance`. No finding reader or writer changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from tests.support.contracts import contract_validator
from tests.support.questions_package import build_questions_package
from tests.unit import test_chat_server as chat
from tests.unit import test_engineering_context_send_gate as gate

app = chat.app
client = chat.client
models = chat.models
provider_control = chat.provider_control
run_root = chat.run_root


def reviewed(app: Any, client: TestClient, folder: Path, *, ticked: bool, context: bool) -> Path:
    """A whole pane review of the questions package, ticked (one scripted turn) or unticked."""
    fixture = build_questions_package(folder)
    app.state.server.bridge_factory = lambda pipe, secret: fixture.bridge
    extra = {"engineering_context": gate.attachment_of(client, folder)} if context else {}
    started = chat.start_session(
        client,
        folder,
        send_when_checked=ticked,
        standards_profile=str(fixture.profile),
        bridge={"pipe": "FICT-pipe", "secret": "FICT-secret"},
        **extra,
    )
    chat.settle(client, started["chat_id"])
    return folder / "session.json"


@pytest.mark.parametrize("context", [False, True], ids=["plain", "context"])
@pytest.mark.parametrize("ticked", [True, False], ids=["ticked", "unticked"])
def test_a_full_review_session_validates_with_its_document_scoped_hygiene_findings(
    app: Any, client: TestClient, run_root: Path, ticked: bool, context: bool
) -> None:
    path = reviewed(app, client, run_root / "FICT-schema", ticked=ticked, context=context)
    written = json.loads(path.read_text(encoding="utf-8"))

    errors = list(contract_validator("review-session.schema.json").iter_errors(written))

    assert errors == [], [f"{list(e.absolute_path)}: {e.message[:200]}" for e in errors]
    scoped = [
        finding
        for finding in written["findings"]
        if not finding["component_ids"] and not finding["drawing_locations"]
    ]
    assert {finding["check"] for finding in scoped} >= {
        "hygiene.part_number_matches_file",
        "hygiene.revision_present",
    }
    assert all(finding["inputs"] and finding["provenance"] for finding in scoped)


def test_a_finding_with_no_component_drawing_or_document_scope_is_still_refused(
    app: Any, client: TestClient, run_root: Path
) -> None:
    path = reviewed(app, client, run_root / "FICT-schema-refused", ticked=False, context=False)
    written = json.loads(path.read_text(encoding="utf-8"))
    finding = next(f for f in written["findings"] if not f["component_ids"])
    finding["inputs"] = []

    errors = list(contract_validator("review-session.schema.json").iter_errors(written))

    assert [list(error.absolute_path)[:1] for error in errors] == [["findings"]]
