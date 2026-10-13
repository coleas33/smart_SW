"""Write US1 waiting page fixtures through the real unticked backend, with fictional clocks.

Run from reviewer/:
    uv run python tests/fixtures/pane/generate_waiting_fixtures.py --write

The small package is T006's shared questions package. Its fictional paths are rebound before
the checks to the replay fixtures' public root, so the existing hygiene scan needs no exception.
The big package is the committed, fictional big-assembly replay evidence, including its meshes.
Both are new live checks-only reviews, not edited snapshots of earlier sessions. Each fixture
contains only labels and the actual GET /sessions/{chat_id}/snapshot response. No provider,
recording, key, SOLIDWORKS seat or network request is used.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

REVIEWER = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REVIEWER))

from starlette.testclient import TestClient  # noqa: E402
from tests.support.questions_package import build_questions_package  # noqa: E402
from tests.support.scramble import FICTIONAL_ROOT  # noqa: E402

from swreview.agent import events, runner  # noqa: E402
from swreview.agent.settings import ProviderSettings  # noqa: E402
from swreview.chat import server  # noqa: E402
from swreview.chat.server import create_app  # noqa: E402
from swreview.ir.loader import load_package, save_package  # noqa: E402
from swreview.ir.models import EvidencePackage  # noqa: E402
from swreview.report.summary import load_words  # noqa: E402
from swreview.tools import context  # noqa: E402

PINNED = datetime(2026, 10, 9, 12, tzinfo=UTC)
NAMES = ("waiting", "waiting-big-assembly")
SOURCE = REVIEWER / "tests/fixtures/replay/big-assembly"
TARGETS = {
    name: REVIEWER.parent / "extractor/SwReview.AddIn.Tests/Fixtures" / f"review-{name}.json"
    for name in NAMES
}
WRITE_COMMAND = "uv run python tests/fixtures/pane/generate_waiting_fixtures.py --write"
TOKEN = "fict-waiting-fixture-token"
ORIGIN = "https://swreview.invalid"
ProviderFactory = Callable[[ProviderSettings], Any]
Observer = Callable[[str, Path, Any], None]


class ClockDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return PINNED.astimezone(tz) if tz is not None else PINNED.replace(tzinfo=None)


@contextmanager
def pinned_clocks():
    """Every clock used by setup, the runner, the event sink and finalization is fictional."""
    with ExitStack() as stack:
        for module in (runner, context, server):
            stack.enter_context(patch.object(module, "datetime", ClockDatetime))
        for module, member in (
            (events, "utc_now"), (runner, "utc_now"), (events, "local_now")
        ):
            stack.enter_context(patch.object(module, member, lambda: PINNED))
        yield


def public_paths(value: Any) -> Any:
    """Rebind the shared builder's fictional root before review, preserving all evidence."""
    if isinstance(value, str):
        return value.replace("C:\\Fictional\\", FICTIONAL_ROOT)
    if isinstance(value, dict):
        return {key: public_paths(member) for key, member in value.items()}
    if isinstance(value, list):
        return [public_paths(member) for member in value]
    return value


def forbidden_provider(settings: ProviderSettings) -> Any:
    raise AssertionError(f"Waiting fixture tried to build a {settings.provider.value} provider")


def waiting_fixtures(
    *, provider_factory: ProviderFactory = forbidden_provider, observe: Observer | None = None
) -> dict[str, dict[str, Any]]:
    """Fresh live snapshots; observe inspects the actual completed run before temp cleanup."""
    result: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as temporary, pinned_clocks():
        root = Path(temporary)
        for name in NAMES:
            folder = root / f"fict-{name}"
            profile: Path | None = None
            bridge: Any = None
            if name == "waiting":
                source = build_questions_package(folder)
                document = public_paths(load_package(folder).package.model_dump(mode="json"))
                save_package(EvidencePackage.model_validate_json(json.dumps(document)), folder)
                profile, bridge = source.profile, source.bridge
            else:
                # Copy the evidence and its sidecars, never the recorded session or events.
                shutil.copytree(SOURCE, folder, ignore=shutil.ignore_patterns(
                    "session.json", "events.jsonl", "report.md", "attention.json", "tool-results"
                ))
            app = create_app(
                token=TOKEN, allow_origin=ORIGIN, run_root=root, development=True,
                provider_factory=provider_factory,
                bridge_factory=(lambda pipe, secret, seat=bridge: seat) if bridge else None,
            )
            with TestClient(app) as client:
                headers = {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
                body: dict[str, Any] = {
                    "run_dir": str(folder), "provider": "fake", "model": "fake-1",
                    "effort": "high", "send_when_checked": False,
                }
                if profile is not None:
                    body["standards_profile"] = str(profile)
                if bridge is not None:
                    body["bridge"] = {"pipe": "fict-waiting-pipe", "secret": "fict-seat-token"}
                response = client.post("/sessions", json=body, headers=headers)
                if response.status_code != 201:
                    raise AssertionError(f"Waiting fixture start failed: {response.text}")
                chat_id = response.json()["chat_id"]
                snapshot = client.get(f"/sessions/{chat_id}/snapshot", headers=headers)
                if snapshot.status_code != 200:
                    raise AssertionError(f"Waiting fixture snapshot failed: {snapshot.text}")
                if observe is not None:
                    observe(name, folder, app)
                result[name] = {
                    "labels": load_words().labels.model_dump(mode="json"),
                    "waiting": snapshot.json(),
                }
    return result


def render_bytes(fixture: dict[str, Any]) -> bytes:
    """The exact UTF-8 bytes written on this platform, including its native newlines."""
    return (json.dumps(fixture, indent=2, ensure_ascii=False) + "\n").replace(
        "\n", os.linesep
    ).encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write both waiting fixtures")
    options = parser.parse_args(argv)
    if not options.write:
        print(f"usage: {WRITE_COMMAND}", file=sys.stderr)
        return 2
    for name, fixture in waiting_fixtures().items():
        TARGETS[name].write_bytes(render_bytes(fixture))
        print(f"wrote {TARGETS[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
