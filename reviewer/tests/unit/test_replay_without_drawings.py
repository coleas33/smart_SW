"""SC-007: every recorded review replays exactly as before with feature 011 registered (T049).

Feature 008's three replay fixtures carry no drawing evidence - no drawing record, no candidate
- so feature 011 must be invisible to them: no drawing tool offered, no `check_drawings`
planned, no recorded finding lost or unreplayable or reclassified, the contact groups each
fixture records (3, 2 and 0) reproduced exactly, and every request the replay plays - the tool
array, the opening message and every round's payloads - byte for byte what it is with the
drawing family patched out of the registry (FR-037, FR-051). Test only: nothing in the replay
code moves.

Two requested arms: the recording's own settings, under which the contact groups must equal the
recording's exactly, and the pane defaults (checks first, slimming, pruning, lever 13), under
which the pre-run judges every group and may add contacts but never lose one.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from swreview.agent.settings import MODEL_VIEW_OFF, EfficiencySettings
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import PlayedReview, ReplayPasses, replay_passes, report_of
from swreview.report.session import ReviewSession
from swreview.tools import registry
from swreview.tools.drawings import DRAWINGS_TOOL
from tests.unit.test_replay_fixtures import (
    EXAMPLE_PROFILE,
    FIXTURES,
    NAMES,
    RECORDED_CONTACTS,
    no_recorded_finding_lost,
    pane_request,
)

pytestmark = pytest.mark.usefixtures("vocabulary")

ARMS = ("recorded", "pane")


def requested(name: str, arm: str) -> Any:
    return (EfficiencySettings(), MODEL_VIEW_OFF) if arm == "recorded" else pane_request(name)


def played(name: str, arm: str, scratch: Path) -> ReplayPasses:
    return replay_passes(
        read_recording(FIXTURES / name),
        scratch,
        requested=requested(name, arm),
        standards_profile=EXAMPLE_PROFILE,
    )


def contact_groups(session: ReviewSession) -> Counter[tuple[str, str]]:
    return Counter((contact.group_key, contact.configuration) for contact in session.contacts)


def request_bytes(review: PlayedReview) -> str:
    """Everything the replay sent its provider: the prefix (system prompt, tool schemas and
    opening message), the offered names and every round's history, as one string."""
    return json.dumps(
        {
            "prefix": review.prefix,
            "opening": review.opening,
            "offered": sorted(review.offered),
            "setup_steps": review.setup_steps,
            "rounds": [
                {
                    "turn": item.turn,
                    "index": item.index,
                    "prior_rounds": item.prior_rounds,
                    "history": list(item.history),
                }
                for item in review.rounds
            ],
        },
        sort_keys=True,
        default=str,
    )


@pytest.fixture(scope="module", params=[(name, arm) for name in NAMES for arm in ARMS],
                ids=lambda value: f"{value[0]}-{value[1]}")
def both(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[ReplayPasses, ReplayPasses, str, str]:
    """One fixture replayed with the drawing family registered, and with it patched out."""
    name, arm = request.param
    registered = played(name, arm, tmp_path_factory.mktemp(f"{name}-{arm}-registered"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(registry, "drawing_tools", lambda: ())
        patched = played(name, arm, tmp_path_factory.mktemp(f"{name}-{arm}-patched"))
    return registered, patched, name, arm


def test_no_drawing_tool_is_offered_and_none_is_planned(both: Any) -> None:
    registered, _, _, _ = both

    for review in (registered.first, registered.second):
        assert DRAWINGS_TOOL not in review.offered
        assert DRAWINGS_TOOL not in {step.tool for step in review.session.steps}
        assert DRAWINGS_TOOL not in review.opening


def test_no_recorded_finding_is_lost_unreplayable_or_reclassified(both: Any) -> None:
    registered, patched, _, _ = both

    no_recorded_finding_lost(report_of(registered).findings)
    assert report_of(registered).findings == report_of(patched).findings


def test_the_recorded_contact_groups_are_replayed_and_never_reclassified(both: Any) -> None:
    registered, _, name, arm = both
    recorded = contact_groups(registered.recording.session)

    assert sum(recorded.values()) == RECORDED_CONTACTS[name]
    assert contact_groups(registered.first.session) == recorded
    if arm == "recorded":
        assert contact_groups(registered.second.session) == recorded
    else:
        assert recorded - contact_groups(registered.second.session) == Counter()
    assert report_of(registered).findings.reclassified == []


def test_every_request_is_byte_identical_with_the_family_patched_out(both: Any) -> None:
    registered, patched, _, _ = both

    assert request_bytes(registered.first) == request_bytes(patched.first)
    assert request_bytes(registered.second) == request_bytes(patched.second)
    assert report_of(registered).rounds == report_of(patched).rounds
