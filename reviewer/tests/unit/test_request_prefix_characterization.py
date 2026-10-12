"""Pin the pane's request prefix before feature 015 moves its rendering into the runner.

Each committed replay is played once with its provider's pane defaults. The prefix comes
from the replay's PlayedReview, which renders it before the first model turn; this test
never reconstructs the system prompt, tool schemas or opening message itself. The digest and
length both describe its UTF-8 bytes, so non-ASCII text contributes its full byte length. The
three committed values are captured on the accepted pre-015 product baseline and are not
refreshed by later feature tasks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pytest_regressions.data_regression import DataRegressionFixture

from swreview.agent.providers import ProviderName
from swreview.agent.settings import pane_defaults
from swreview.benchmark.recording import read_recording
from swreview.benchmark.replay import play_review, turn_plans

pytestmark = pytest.mark.usefixtures("vocabulary")

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "reviewer" / "tests" / "fixtures" / "replay"
EXAMPLE_PROFILE = REPO_ROOT / "config" / "standards.example.yaml"
NAMES = ("big-assembly", "small-assembly-a", "small-assembly-b")


@pytest.mark.parametrize("name", NAMES)
def test_first_request_prefix_matches_pre_feature_code(
    name: str, tmp_path: Path, data_regression: DataRegressionFixture
) -> None:
    recording = read_recording(FIXTURES / name)
    defaults = pane_defaults(ProviderName(recording.provider))
    first = play_review(
        recording.run_dir,
        tmp_path / "first",
        turn_plans(recording),
        model=recording.session.model,
        efficiency=defaults.efficiency,
        model_view=defaults.model_view,
        standards_profile=EXAMPLE_PROFILE,
    )
    prefix = first.prefix.encode("utf-8")
    assert prefix

    data_regression.check(
        {"sha256": hashlib.sha256(prefix).hexdigest(), "byte_length": len(prefix)},
        basename=name,
    )
