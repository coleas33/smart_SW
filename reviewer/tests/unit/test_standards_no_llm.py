"""No language model on any standards path, proved on all three of them at once (T093).

FR-045 is a claim about the whole feature rather than about one module: the Standards tab
has to work on a workstation that has no API key, no network and no SDK configured, and a
release gate that calls `swreview check standards` from a build agent has to grade the same
design the same way. `test_standards_run.py` and `test_chat_standards_routes.py` each pin
that claim for the path they are about; this module is the cross-cutting proof, and it is
deliberately stronger than either in three ways:

1. **the real construction sites are left in place.** The backend here is built by
   `create_app` with its **own** defaults - `chat/server.py::build_provider` and
   `list_provider_models` - rather than with a test factory that raises, so what is being
   asserted is that the product's own factory is never reached, not that a substitute was
   never called. What raises instead is `agent.providers` itself: `get`, the single adapter
   lookup every real construction goes through, `call_tool`, the single place a turn
   dispatches a tool through an adapter, and `chat/server.py`'s direct `FakeProvider`, the
   one construction that does **not** go through `get`;
2. **the environment holds keys.** A workstation with no key at all proves less than one
   that has three: `EnvironmentWatch` replaces `os.environ` with a proxy that records every
   look-up of the three key variables the product names, so "no key was read" is measured
   rather than arranged. The proxy **records** rather than raising, because a read that a
   `try`/`except` swallowed would still be a read;
3. **the sockets are guarded.** `no_host_beyond_the_local_backend` refuses every connection
   and every name resolution that is not loopback, so "no call to any host beyond the local
   backend" is enforced for the duration of each guarded run rather than inferred from the
   absence of an SDK import.

**What "unchanged" means here.** Each path is run twice with identical arguments - once
ordinarily, once under the guard - and the two results are compared field for field. A
standards run is deterministic and writes into the folder it is given, so the second run
overwrites the first and an equal result is an exact statement: the guard changed nothing,
rather than merely not crashing.

The second proof T093 names, `extractor/SwReview.Extractor.Tests/StandardsGateLogTests.cs`
(FR-044, SC-010, quickstart gate 11), is the C# half of the same claim and lives with the
dumper it is about.

Every package here is the `standards-seeded` golden graded against a **fictional** fixture
profile (T002): no company value enters a test (FR-001).
"""

from __future__ import annotations

import os
import shutil
import socket
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from swreview.agent import providers
from swreview.chat import server as chat_server
from swreview.chat.server import KEY_VARIABLES as SERVER_KEY_VARIABLES
from swreview.chat.server import create_app
from swreview.checks.standards.report import verdict_json
from swreview.checks.standards.run import StandardsCheckRun, run_standards_check
from swreview.cli import KEY_ENV_VARS as CLI_KEY_VARIABLES
from swreview.ir.loader import PACKAGE_FILE_NAME
from tests.unit.test_cli import invoke, payload

ORIGIN = "https://swreview.invalid"
TOKEN = "the-per-launch-token"

FIXTURES = Path(__file__).resolve().parents[1]
SEEDED_PACKAGE = FIXTURES / "golden" / "fixtures" / "standards-seeded" / PACKAGE_FILE_NAME
"""The T053 golden: one seeded violation of each of the sixteen checks, over a drawing
root that references the assembly the model checks grade. Grading it exercises every check
and the finding path, so a guard that broke either would be visible here."""

PROFILE_A = FIXTURES / "fixtures" / "standards" / "profile-a.yaml"

CHECK_ID = "20260917-101532-mr-90001-standards"
"""The standards run folder's name, which is also its `check_id`."""

KEY_VARIABLES: tuple[str, ...] = tuple(
    dict.fromkeys((*SERVER_KEY_VARIABLES, *CLI_KEY_VARIABLES))
)
"""Every API-key variable this product names, taken from the two modules that name them
rather than restated here, so a fourth one is watched the day it is added."""

SENTINEL_KEY = "sk-a-key-this-run-must-not-read"
"""What each key variable holds while a guarded path runs: a workstation that *has* keys
is the case FR-045 is about, because one with none would pass by accident."""

LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})
"""The local backend, which the pane does talk to. Every other host is the failure."""


# --- the guard ----------------------------------------------------------------------------


class EnvironmentWatch(MutableMapping[str, str]):
    """`os.environ`, delegating everything, recording each look-up of a key variable.

    Only `__getitem__` records, and that is enough: `Mapping.get` and `Mapping.__contains__`
    are both defined in terms of it, and `os.environ.get(...)` is how every one of this
    product's six environment reads is written.
    """

    def __init__(self, source: MutableMapping[str, str], watched: tuple[str, ...]) -> None:
        self._source = source
        self._watched = frozenset(watched)
        self.read: list[str] = []

    def __getitem__(self, key: str) -> str:
        if key in self._watched:
            self.read.append(key)
        return self._source[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._source[key] = value

    def __delitem__(self, key: str) -> None:
        del self._source[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._source)

    def __len__(self) -> int:
        return len(self._source)


def refuse_provider(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("a standards path must never construct a provider (FR-045)")


def no_host_beyond_the_local_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every connection and name resolution that is not loopback.

    `socket.socket.connect`, `connect_ex` and `create_connection` cover a client built by
    any SDK, and `getaddrinfo` covers the resolution one would make first; loopback stays
    open because the pane's own backend is on it and this is the claim being made, not a
    stricter one.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def host_of(address: Any) -> str:
        return str(address[0]) if isinstance(address, tuple) and address else ""

    def refuse(host: str) -> None:
        if host not in LOOPBACK:
            raise AssertionError(f"a standards path must reach no host but the backend: {host!r}")

    def connect(self: socket.socket, address: Any) -> Any:
        refuse(host_of(address))
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> Any:
        refuse(host_of(address))
        return real_connect_ex(self, address)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        refuse(host_of(address))
        return real_create_connection(address, *args, **kwargs)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        refuse("" if host is None else str(host))
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@contextmanager
def guarded() -> Iterator[EnvironmentWatch]:
    """Every provider factory raising, every key variable watched, every host refused.

    Yields the watch, so a test asserts what was read rather than trusting that nothing
    was. Its own `MonkeyPatch` rather than the fixture's, so the guard is lifted at the end
    of the `with` and the comparison run either side of it is an ordinary one.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(providers, "get", refuse_provider)
        patch.setattr(providers, "call_tool", refuse_provider)
        patch.setattr(chat_server, "FakeProvider", refuse_provider)
        for name in KEY_VARIABLES:
            patch.setenv(name, SENTINEL_KEY)
        watch = EnvironmentWatch(os.environ, KEY_VARIABLES)
        patch.setattr(os, "environ", watch)
        no_host_beyond_the_local_backend(patch)
        yield watch


# --- what the three paths are run against ---------------------------------------------------


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def standards_dir(run_root: Path) -> Path:
    """The run folder the pane dumped the `standards` profile into."""
    directory = run_root / CHECK_ID
    directory.mkdir(parents=True)
    shutil.copy2(SEEDED_PACKAGE, directory / PACKAGE_FILE_NAME)
    return directory


@pytest.fixture
def client(run_root: Path) -> Iterator[TestClient]:
    """The pane's client, against the backend built with the product's own factories."""
    app = create_app(token=TOKEN, allow_origin=ORIGIN, run_root=run_root)
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as test_client:
        yield test_client


def evaluation_of(run: StandardsCheckRun) -> dict[str, Any]:
    """Everything one run graded, with nothing that is a measurement of the machine.

    The session is left out on purpose: it carries wall-clock timings, which differ between
    two runs of the same package and say nothing about whether a provider was reached.
    """
    return {
        "documents": run.documents,
        "document_kinds": run.document_kinds,
        "document_reached_by": run.document_reached_by,
        "verdict": verdict_json(run.verdict),
        "findings": run.findings,
        "subjects": run.subjects,
        "coverage": run.coverage,
        "checks": run.checks,
        "unavailable_checks": run.unavailable_checks,
    }


# --- 1. the check path ----------------------------------------------------------------------


class TestTheCheckPath:
    def test_the_evaluation_entry_point_grades_the_same_design_under_the_guard(
        self, standards_dir: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "check-out"

        ordinary = evaluation_of(
            run_standards_check(standards_dir, PROFILE_A, out, run_root=tmp_path)
        )
        with guarded() as watch:
            guarded_run = run_standards_check(
                standards_dir, PROFILE_A, out, run_root=tmp_path
            )

        assert evaluation_of(guarded_run) == ordinary
        assert watch.read == []
        # The workload, without which an equal result would mean nothing.
        assert guarded_run.findings
        assert len(guarded_run.checks) == 16


# --- 2. the tab path, through the route ------------------------------------------------------


class TestTheTabPath:
    def test_the_route_answers_the_same_result_under_the_guard(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """The backend here is the product's own: `build_provider` and
        `list_provider_models` are wired in, and neither is reached."""
        ordinary = self._post(client, standards_dir)

        with guarded() as watch:
            answered = self._post(client, standards_dir)
            read_back = client.get(f"/checks/{CHECK_ID}")

        assert answered == ordinary
        assert read_back.status_code == 200
        assert read_back.json()["verdict"] == ordinary["verdict"]
        assert watch.read == []
        assert answered["findings"]

    @staticmethod
    def _post(client: TestClient, run_dir: Path) -> dict[str, Any]:
        response = client.post(
            "/checks/standards",
            json={"run_dir": str(run_dir), "profile_path": str(PROFILE_A)},
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    def test_a_standards_check_opens_no_chat_session(
        self, client: TestClient, standards_dir: Path
    ) -> None:
        """Nothing on this path reaches the runner, so there is nothing to talk to."""
        with guarded():
            self._post(client, standards_dir)

        assert client.app.state.server.chats == {}  # type: ignore[attr-defined]


# --- 3. the command line ---------------------------------------------------------------------


class TestTheCommandLine:
    def test_check_standards_prints_the_same_run_under_the_guard(
        self, standards_dir: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "cli-runs" / "standards"
        arguments = (
            "check",
            "standards",
            "--package",
            str(standards_dir),
            "--out",
            str(out),
            "--profile",
            str(PROFILE_A),
            "--json",
        )

        ordinary = payload(invoke(*arguments))
        with guarded() as watch:
            result = invoke(*arguments)

        assert payload(result) == ordinary
        assert watch.read == []
        assert ordinary["findings"]
        assert len(ordinary["checks"]) == 16
