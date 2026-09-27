"""What the SOLIDWORKS host can do with a closed drawing, asked once (feature 013 T076).

`contracts/drawing-capability.md` section 2: `ToolContext.drawing_read_mode()` is lazy and cached -
the bridge is pinged at most once per review, through lane D's `BridgeClient.drawing_read_mode()`
(which never raises and answers `none` on any failure) - answers `none` with no bridge, and records
the value on `ReviewSession.drawing_read`, so a summary re-rendered later says the same. Nothing
asks it unless a custom or unclear document has a drawing candidate, so a package without
candidates never pings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.ir.loader import save_package
from swreview.tools.context import context_for
from tests.support.packages import build_package


class PingingBridge:
    """The bridge as lane D's client answers the capability: one mode, every ping counted."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.pings = 0

    def drawing_read_mode(self) -> str:
        self.pings += 1
        return self.mode

    def close(self) -> None:
        pass


@pytest.mark.parametrize("mode", ["none", "open_only", "opens_closed"])
def test_the_mode_is_the_hosts_and_is_recorded_on_the_session(mode: str) -> None:
    context = context_for(build_package())
    context.bridge = PingingBridge(mode)

    assert context.drawing_read_mode() == mode
    assert context.require_session().drawing_read == mode


def test_the_host_is_asked_once() -> None:
    context = context_for(build_package())
    bridge = PingingBridge("open_only")
    context.bridge = bridge

    first, second = context.drawing_read_mode(), context.drawing_read_mode()

    assert (first, second) == ("open_only", "open_only")
    assert bridge.pings == 1


def test_with_no_bridge_the_mode_is_none_and_nothing_is_asked() -> None:
    context = context_for(build_package())

    assert context.drawing_read_mode() == "none"
    assert context.require_session().drawing_read == "none"


def test_nothing_is_asked_until_something_needs_it() -> None:
    context = context_for(build_package())
    bridge = PingingBridge("opens_closed")
    context.bridge = bridge

    assert bridge.pings == 0
    assert context.require_session().drawing_read is None


def test_a_context_with_no_session_still_answers() -> None:
    from dataclasses import replace

    context = replace(context_for(build_package()), session=None)
    context.bridge = PingingBridge("open_only")

    assert context.drawing_read_mode() == "open_only"


def test_a_review_of_a_package_without_candidates_never_pings(tmp_path: Path) -> None:
    folder = tmp_path / "run-0001"
    save_package(build_package(), folder)
    bridge = PingingBridge("opens_closed")

    run = start_review(
        folder,
        folder,
        provider=FakeProvider(
            script=[ScriptedTurn(text="done", tool_calls=(ScriptedToolCall("list_gaps"),))],
            model="fake-scripted",
        ),
        bridge=True,
        bridge_factory=lambda pipe, secret: bridge,
    )
    run.start()

    assert bridge.pings == 0
    assert run.session.drawing_read is None
