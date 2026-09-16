"""No lever is a pane setting while the levers are being measured (T019a, SC-008, FR-021).

The owner's rule this whole feature is built around has one failure it is guarding
against: an engineer flipping an experiment flag mid-pilot makes the pilot's own numbers
unreadable. An instruction in a task not to add a checkbox is not an assertion that none
was added, so this module is the assertion.

It iterates the ten field names off `EfficiencySettings` itself rather than a retyped
list, so a lever added later is covered without anyone remembering to extend this test,
and it looks in the two places a pane setting can exist:

1. `specs/002-task-pane-assistant/contracts/settings.schema.json`, the contract for
   `%APPDATA%\\SwReview\\settings.json`;
2. `extractor/SwReview.AddIn/Settings/UserSettings.cs`, the type the pane actually saves -
   the schema could stay clean while the writer grew a property.

Read as text on purpose. A name must not appear *anywhere* in either file, not merely as a
declared property: a lever mentioned in a description or a comment is a lever someone is
about to wire up, and this is cheaper to argue about now than after a pilot.

**An adopted lever becoming a default in code is a different thing and this test does not
stop it** (data-model.md section 7.2): the flag then disappears or flips its default in a
separate change with its own ledger row, and neither puts a checkbox in the pane.
"""

from __future__ import annotations

import json

import pytest

from swreview.agent.settings import LEVER_NAMES
from tests.support.contracts import REPO_ROOT, contract_path

PANE_SETTINGS_SCHEMA = contract_path("settings.schema.json")
PANE_SETTINGS_WRITER = REPO_ROOT / "extractor" / "SwReview.AddIn" / "Settings" / "UserSettings.cs"


def test_the_two_guarded_files_exist() -> None:
    """A guard over a file that moved would pass by reading nothing."""
    assert PANE_SETTINGS_SCHEMA.is_file()
    assert PANE_SETTINGS_WRITER.is_file()


def test_there_are_ten_levers_to_guard() -> None:
    assert len(LEVER_NAMES) == 10


@pytest.mark.parametrize("lever", LEVER_NAMES)
def test_no_lever_appears_in_the_pane_settings_schema(lever: str) -> None:
    text = PANE_SETTINGS_SCHEMA.read_text(encoding="utf-8")

    assert lever not in text, (
        f"{lever!r} appears in {PANE_SETTINGS_SCHEMA.name}: efficiency levers are not pane "
        f"settings while they are being measured (FR-021). An adopted lever becomes a "
        f"default in code, not a checkbox."
    )


@pytest.mark.parametrize("lever", LEVER_NAMES)
def test_no_lever_appears_in_the_settings_the_pane_saves(lever: str) -> None:
    text = PANE_SETTINGS_WRITER.read_text(encoding="utf-8")

    assert lever not in text, (
        f"{lever!r} appears in {PANE_SETTINGS_WRITER.name}: the pane must not be able to "
        f"write an efficiency lever into settings.json, whatever the schema says."
    )


def test_the_pane_schema_forbids_properties_it_does_not_declare() -> None:
    """The guard above is a text scan; this is why a lever cannot arrive unannounced."""
    schema = json.loads(PANE_SETTINGS_SCHEMA.read_text(encoding="utf-8"))

    assert schema["additionalProperties"] is False
