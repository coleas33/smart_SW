"""One scripted review of the sitting-shaped fixture, for the tests that read its outcome (013).

`tests/fixtures/sitting/small-assembly/` (T012) reviewed by `start_review` with checks first, as
the pane runs it, and the scripted provider closing the turn at once: the pre-run grades every
part and assembly document with the part roles attached, so a test reads what the review raised
after classification - with fictional profile A (version 4: the pin and the vendor sub-assembly
bought, the spacer unclear) or with no profile at all (every part graded, as before feature 013).
The run is closed before it is returned; its session and its package stay readable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.agent.settings import EfficiencySettings
from tests.support.sitting import DOCUMENTS

TESTS = Path(__file__).resolve().parents[1]
SITTING = TESTS / "fixtures" / "sitting" / "small-assembly"
PROFILE_A = TESTS / "fixtures" / "standards" / "profile-a.yaml"

__all__ = ["DOCUMENTS", "PROFILE_A", "SITTING", "documents_of", "sitting_review"]


def sitting_review(tmp_path: Path, *, profile: Path | None = PROFILE_A) -> ReviewRun:
    """The sitting's small assembly reviewed with checks first and `profile`, the turn over."""
    folder = tmp_path / "sitting-run"
    shutil.copytree(SITTING, folder)
    run = start_review(
        folder,
        folder,
        provider=FakeProvider(script=[ScriptedTurn(text="reviewed")], model="fake-scripted"),
        standards_profile=profile,
        efficiency=EfficiencySettings(prerun_checks=True),
    )
    try:
        run.start()
    finally:
        run.close()
    return run


def documents_of(run: ReviewRun, finding_ids: list[str]) -> set[str]:
    """The documents the components of `finding_ids` are instances of."""
    documents = {item.id: item.document_id for item in run.context.ir.components}
    findings = {finding.id: finding for finding in run.session.findings}
    return {
        documents[component]
        for finding_id in finding_ids
        for component in findings[finding_id].component_ids
        if component in documents
    }
