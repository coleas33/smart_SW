"""The nine Remodel routes against `contracts/backend-remodel.md` (T134a).

Driven through Starlette's in-process client, exactly as `test_chat_checks_routes.py`
drives the Model check routes, so every assertion here is about the real application: the
same `Guard` middleware, the same path rule, the same error body. The seat is
`tests/support/remodel_bridge.py::FakeRemodelBridge` - the same fake the executor's own
tests run against - so no test here needs SOLIDWORKS, a provider or a key.

What the contract makes this module responsible for:

- **the contract is parsed, not restated.** `backend-remodel.md`'s two tables are read as
  data the way `RemodelPageContractTests` reads `pane-remodel-messages.md`: a route
  documented and not registered, a route registered and not documented, and an error class
  named on one side alone are each a failure. A hand-kept list here would drift.
- **every bridge `error_code` becomes a named refusal class.** The mapping is the one
  table of the contract, asserted token by token, and a token this build has never heard of
  becomes `RunFolderFailed` carrying the host's own sentence rather than being guessed into
  a nearer class.
- **`preexisting_rebuild_errors` is not an error body.** It answers `200` with
  `copy_present: false` and the count, because the host already has a path for it and the
  count is what the engineer reads.
- **the folder is the state.** `POST /remodel/open` writes `open.json` and
  `source-attestation.json`, and `POST /remodel/runs` rebuilds the runner's inputs from the
  folder alone - which is what lets the pane answer after a restart.
- **the secret never comes back.** It reaches the client factory and nothing else: no
  reply, no artifact, no error body carries it.
- **no provider on any route but `POST /remodel/runs`**, and there only through
  `remodel/runner.py`, which is the one construction site (FR-045, SC-009). The application
  is built with a provider factory that raises, and `TestNoLanguageModel` additionally makes
  the registry and the command line's factory raise while driving the other eight.
- **the source is named in no bridge call after `remodel.open`.** Asserted over a whole
  run's call log rather than command by command.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient

from swreview.agent import providers
from swreview.bridge.remodel_client import CircuitOpen, RemodelError, RemodelPreflightError
from swreview.chat import remodel as remodel_routes
from swreview.chat.server import ChatError, create_app
from swreview.exceptions import EXCEPTIONS_FILE_NAME
from swreview.ir.models import EvidencePackage
from swreview.remodel.apply_log import CHANGES_FILE_NAME, read_changes
from swreview.remodel.artifacts import PACKAGE_AFTER
from swreview.remodel.attestation import ATTESTATION_FILE_NAME, read_attestation
from swreview.remodel.plan import PACKAGE_BEFORE, Limits, RemodelPlan, plan_path
from swreview.remodel.scope import ScopeSignals
from swreview.remodel.tolerances import IDENTITY
from tests.support.features import equation, feature, fillet_feature, sketch_feature
from tests.support.remodel import UNKNOWN_TYPE_NAME, linked, remodel_package, scope_signals
from tests.support.remodel_bridge import FakeRemodelBridge, FakeTree

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = (
    REPO_ROOT / "specs" / "004-resilient-remodeler" / "contracts" / "backend-remodel.md"
)

ORIGIN = "https://swreview.invalid"
OTHER_ORIGIN = "https://evil.example"
TOKEN = "the-per-launch-token"

PIPE = "swreview-remodel-abc123"
SECRET = "the-remodel-bridge-secret-nobody-echoes"

RUN_ID = "20260916-142201-bracket-remodel"
PROBE_ID = "probe:1"
UNIT = "mm"
AT = datetime(2026, 9, 16, 14, 22, 1, tzinfo=UTC)
SOURCE_DESIGN_ID = "dsn:4f2a91c0d3b7"
SOURCE_CONTENT = b"the engineer's file, byte for byte"

OPEN_FILE_NAME = "open.json"

POLL_S = 0.02
WAIT_S = 20.0
"""How long a test waits for the worker thread. Long enough for a loaded CI box, and a
failure here is a hang rather than a flake because the predicate is asserted after."""


# --- the part, the seat and the run's inputs ------------------------------------------


def part() -> EvidencePackage:
    """The judgement-slot part of `test_remodel_runner.py`, so one fixture serves both.

    `Cut-Extrude1` sits above the core features it should follow, so the planner has a
    real move to make and the apply phase has something to write down.
    """
    specs = linked(
        [
            feature("Right Plane", "RefPlane"),
            sketch_feature("Sketch1"),
            feature("Cut-Extrude1", "Cut"),
            feature("Boss-Extrude1", "Extrusion", description=""),
            fillet_feature("Fillet1", radius_m=0.005),
            fillet_feature("Fillet2", radius_m=0.003),
            feature("Shell1", "Shell"),
            feature("Deform1", UNKNOWN_TYPE_NAME),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Fillet1"),
        ("Boss-Extrude1", "Fillet2"),
        ("Fillet2", "Shell1"),
    )
    return remodel_package(
        specs, equations=[equation('"width" = 100', is_global=True, value=0.1)]
    )


PACKAGE = part()


def seat(package: EvidencePackage) -> FakeTree:
    """The seat's tree, built from the package's own persistent references."""
    return FakeTree(
        order=[row.persist_ref for row in package.features],
        names={row.persist_ref: row.name for row in package.features},
        descriptions={row.persist_ref: "" for row in package.features},
        equations=[row.text for row in package.equations],
    )


def reading(**overrides: Any) -> dict[str, Any]:
    """One `remodel.geometry` reply, identical before and after: stage 1 creates no
    geometry, so any difference under `IDENTITY` is a defect."""
    return {
        "at": "2026-09-16T14:22:01Z",
        "source_sha256": "4c" * 32,
        "subject": "copy_at_open",
        "status": 0,
        "accuracy_level": 2,
        "recalculated": True,
        "volume_m3": 1.23456789e-3,
        "surface_area_m2": 4.56e-2,
        "center_of_mass_m": [0.01, 0.02, 0.03],
        "principal_moments": [1.1e-5, 2.2e-5, 3.3e-5],
        "mass_kg": 3.21,
        "density": 2600.0,
        "material_name": "1060 Alloy",
        "solid_body_count": 1,
        "sheet_body_count": 0,
        "face_count": 214,
        "edge_count": 642,
        "residual": None,
        **overrides,
    }


def _last_write_utc(path: Path) -> datetime:
    seconds, nanoseconds = divmod(path.stat().st_mtime_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanoseconds // 1000)


class ProbingBridge(FakeRemodelBridge):
    """`FakeRemodelBridge` plus the one command it has no need of in the executor's tests.

    `remodel.probe_scope` runs before the scope exists, so the executor never sends it and
    the shared fake does not model it; the routes do, because the pure gate is fed from it.
    The subclass also fills in the three blocks `remodel.open` answers with that the
    executor ignores - the copy's scope signals, the configuration list and the source
    attestation - because those are exactly what `open.json` is written from.
    """

    def __init__(
        self,
        tree: FakeTree,
        *,
        source: Path,
        copy_path: str,
        signals: Mapping[str, Any] | None = None,
        probe_raises: BaseException | None = None,
        probe_returns: CircuitOpen | None = None,
        open_raises: BaseException | None = None,
        open_returns: CircuitOpen | None = None,
    ) -> None:
        super().__init__(
            tree,
            copy_path=copy_path,
            source_path=str(source),
            readings=[reading(), reading()],
        )
        self.source = source
        self.signals = dict(signals if signals is not None else scope_signals())
        self.probe_raises = probe_raises
        self.probe_returns = probe_returns
        self.open_raises = open_raises
        self.open_returns = open_returns
        self.copy_exists = False
        """No copy until `remodel.open` makes one; the shared fake starts from an open run."""

    def probe_scope(self, source_path: str) -> Any:
        self.calls.append(("remodel.probe_scope", {"source_path": source_path}))
        if self.probe_returns is not None:
            return self.probe_returns
        if self.probe_raises is not None:
            raise self.probe_raises
        return {
            "probe_id": PROBE_ID,
            "source_path": source_path,
            "scope_signals": dict(self.signals),
        }

    def open(
        self, source_path: str, copy_path: str, run_id: str, probe_id: str
    ) -> dict[str, Any]:
        if self.open_returns is not None:
            self.calls.append(
                (
                    "remodel.open",
                    {
                        "source_path": source_path,
                        "copy_path": copy_path,
                        "run_id": run_id,
                        "probe_id": probe_id,
                    },
                )
            )
            return self.open_returns  # type: ignore[return-value]
        if self.open_raises is not None:
            self.calls.append(
                (
                    "remodel.open",
                    {
                        "source_path": source_path,
                        "copy_path": copy_path,
                        "run_id": run_id,
                        "probe_id": probe_id,
                    },
                )
            )
            raise self.open_raises
        reply = super().open(source_path, copy_path, run_id, probe_id)
        return {
            **reply,
            "scope_signals": dict(self.signals),
            "configurations": ["Default"],
            "document_length_unit": UNIT,
            "source_attestation": self.attestation(copy_path),
        }

    def attestation(self, copy_path: str) -> dict[str, Any]:
        """What the C# side measures before the copy exists (`data-model.md` section 5)."""
        return {
            "path": str(self.source),
            "length_bytes": self.source.stat().st_size,
            "last_write_utc": _last_write_utc(self.source)
            .isoformat()
            .replace("+00:00", "Z"),
            "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "source_design_id": SOURCE_DESIGN_ID,
            "recorded_at": AT.isoformat().replace("+00:00", "Z"),
            "vault_path": None,
            "vault_revision": None,
            "copy_path": copy_path,
        }


# --- the application -------------------------------------------------------------------


def refuse_provider(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("no remodel route may construct a provider")


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def run_dir(run_root: Path) -> Path:
    """The run folder the host created before it asked the backend for anything."""
    directory = run_root / RUN_ID
    directory.mkdir()
    return directory


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """The engineer's file, which phase D re-reads to re-check the attestation."""
    path = tmp_path / "work" / "bracket.SLDPRT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(SOURCE_CONTENT)
    return path


def copy_path_of(run_dir: Path) -> str:
    """`<run>/copy/<name>-RMS.SLDPRT` (`Rms/RemodelCopy.cs::CopyPathFor`)."""
    return str(run_dir / "copy" / "bracket-RMS.SLDPRT")


@pytest.fixture
def bridge(source: Path, run_dir: Path) -> ProbingBridge:
    return ProbingBridge(seat(PACKAGE), source=source, copy_path=copy_path_of(run_dir))


@pytest.fixture
def asked(bridge: ProbingBridge) -> list[tuple[str, str | None]]:
    """Every `{pipe, secret}` the routes built a client from, in order."""
    return []


@pytest.fixture
def app(
    run_root: Path, bridge: ProbingBridge, asked: list[tuple[str, str | None]]
) -> Any:
    """The backend with a provider factory that raises and the fake seat behind it."""

    def factory(pipe: str, secret: str | None) -> Any:
        asked.append((pipe, secret))
        return bridge

    return create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=refuse_provider,
        list_models=refuse_provider,
        remodel_bridge_factory=factory,
    )


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as test_client:
        yield test_client


# --- talking to the routes --------------------------------------------------------------


BRIDGE = {"pipe": PIPE, "secret": SECRET}


def probe(client: TestClient, source: Path, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "source_path": str(source),
        "configuration": "Default",
        "bridge": dict(BRIDGE),
    }
    body.update(overrides)
    return client.post("/remodel/probe", json=body)


def open_copy(client: TestClient, run_dir: Path, source: Path, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "run_dir": str(run_dir),
        "source_path": str(source),
        "configuration": "Default",
        "probe_id": PROBE_ID,
        "bridge": dict(BRIDGE),
    }
    body.update(overrides)
    return client.post("/remodel/open", json=body)


def plan(client: TestClient, run_dir: Path, **overrides: Any) -> Any:
    body: dict[str, Any] = {"run_dir": str(run_dir)}
    body.update(overrides)
    return client.post("/remodel/plan", json=body)


def start(client: TestClient, run_dir: Path, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "run_dir": str(run_dir),
        "bridge": dict(BRIDGE),
        "provider": "fake",
        "model": "fake-scripted",
    }
    body.update(overrides)
    return client.post("/remodel/runs", json=body)


def close(client: TestClient, run_dir: Path, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "run_dir": str(run_dir),
        "bridge": dict(BRIDGE),
        "discard_copy": False,
    }
    body.update(overrides)
    return client.post("/remodel/close", json=body)


def dumped(run_dir: Path, name: str, package: EvidencePackage = PACKAGE) -> Path:
    """The dump the add-in writes in process, under the contract's name."""
    path = run_dir / name
    path.write_text(package.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def planned(client: TestClient, run_dir: Path, source: Path) -> dict[str, Any]:
    """Probe, open, dump and plan: the whole of `remodel.plan`, as the host runs it."""
    assert probe(client, source).status_code == 200
    assert open_copy(client, run_dir, source).status_code == 200
    dumped(run_dir, PACKAGE_BEFORE)
    response = plan(client, run_dir)
    assert response.status_code == 200, response.text
    return dict(response.json())


def status_of(client: TestClient, job_id: str) -> dict[str, Any]:
    response = client.get(f"/remodel/runs/{job_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


def wait_for(
    client: TestClient, job_id: str, ready: Callable[[Mapping[str, Any]], bool]
) -> dict[str, Any]:
    """Poll the status route until `ready`, exactly as the pipeline's poll loop does."""
    deadline = time.monotonic() + WAIT_S
    state = status_of(client, job_id)
    while not ready(state) and time.monotonic() < deadline:
        time.sleep(POLL_S)
        state = status_of(client, job_id)
    assert ready(state), f"the run never reached the expected state: {state}"
    return state


def deliver_package_after(
    client: TestClient, job_id: str, run_dir: Path, **overrides: Any
) -> Any:
    dumped(run_dir, PACKAGE_AFTER)
    body: dict[str, Any] = {"path": str(run_dir / PACKAGE_AFTER)}
    body.update(overrides)
    return client.post(f"/remodel/runs/{job_id}/package-after", json=body)


def calibrated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the geometry gate decide, which FR-036 forbids until PROBE-8 measures it.

    The route names the stage-1 profile it decides under rather than taking the default,
    so a test can hand it the profile PROBE-8 will leave behind; without this the run
    ends where `require_calibrated` stops it, which is asserted on its own below.
    """
    monkeypatch.setattr(
        remodel_routes,
        "IDENTITY",
        IDENTITY.model_copy(
            update={"calibrated": True, "calibration_ref": "PROBE-8 2026-09-16"}
        ),
    )


def run_to_completion(
    client: TestClient, run_dir: Path, source: Path
) -> tuple[str, dict[str, Any]]:
    """Plan, start, answer the package-after rendezvous, and wait for the run to end."""
    planned(client, run_dir, source)
    started = start(client, run_dir)
    assert started.status_code == 201, started.text
    job_id = str(started.json()["job_id"])
    wait_for(client, job_id, lambda state: state["awaiting"] == "package_after")
    assert deliver_package_after(client, job_id, run_dir).status_code == 200
    return job_id, wait_for(
        client, job_id, lambda state: state["state"] in {"finished", "failed"}
    )


# --- 1. the contract, read as data ------------------------------------------------------


def _rows(heading: str) -> list[list[str]]:
    """Every markdown table row under one `##` section of the contract, split on `|`."""
    rows: list[list[str]] = []
    section: str | None = None
    for raw in CONTRACT.read_text(encoding="utf-8").splitlines():
        if raw.startswith("#"):
            section = raw[3:].strip() if raw.startswith("## ") else None
            continue
        if section != heading or not raw.startswith("|"):
            continue
        cells = raw.split("|")
        if len(cells) >= 3:
            rows.append([cell.strip() for cell in cells])
    return rows


def _backticked(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def documented_routes() -> set[tuple[str, str]]:
    """The `(method, path)` pairs of the contract's route table."""
    found: set[tuple[str, str]] = set()
    for cells in _rows("Routes"):
        for token in _backticked(cells[1]):
            method, _, path = token.partition(" ")
            if method in {"GET", "POST"} and path.startswith("/remodel"):
                found.add((method, path))
    return found


def documented_errors() -> dict[str, int]:
    """The error class table: class name to HTTP status."""
    found: dict[str, int] = {}
    for cells in _rows("Error classes"):
        names = [
            token for token in _backticked(cells[1]) if re.fullmatch(r"[A-Z][A-Za-z]+", token)
        ]
        if not names or not cells[2].isdigit():
            continue
        found[names[0]] = int(cells[2])
    return found


DOCUMENTED_ROUTES = documented_routes()
DOCUMENTED_ERRORS = documented_errors()


def registered_routes(app: Any) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        if isinstance(route, Route) and route.path.startswith("/remodel")
        for method in (route.methods or ())
        if method in {"GET", "POST"}
    }


class TestTheContract:
    def test_the_two_tables_parse(self) -> None:
        """A parser that quietly matched nothing would make every test below vacuous."""
        assert len(DOCUMENTED_ROUTES) == 9, DOCUMENTED_ROUTES
        assert len(DOCUMENTED_ERRORS) >= 13, DOCUMENTED_ERRORS

    def test_every_documented_route_is_registered(self, app: Any) -> None:
        missing = sorted(DOCUMENTED_ROUTES - registered_routes(app))

        assert not missing, (
            f"documented in backend-remodel.md and not registered in create_app: {missing}"
        )

    def test_every_registered_remodel_route_is_documented(self, app: Any) -> None:
        """The other direction: a route nobody documented is one nobody can call."""
        extra = sorted(registered_routes(app) - DOCUMENTED_ROUTES)

        assert not extra, f"registered and not documented in backend-remodel.md: {extra}"

    def test_every_documented_error_class_exists_with_its_status(self) -> None:
        for name, status in sorted(DOCUMENTED_ERRORS.items()):
            error = getattr(remodel_routes, name, None)
            assert error is not None, f"{name} is documented and is defined nowhere"
            assert issubclass(error, ChatError), f"{name} is not a ChatError"
            assert error.error_class == name
            assert error.status == status, f"{name} answers {error.status}, not {status}"

    def test_every_error_class_the_module_defines_is_documented(self) -> None:
        """A refusal the page could meet and the contract does not name is undocumented
        surface, which is the drift the parser exists to catch."""
        defined = {
            name
            for name, value in vars(remodel_routes).items()
            if isinstance(value, type)
            and issubclass(value, ChatError)
            and value.__module__ == remodel_routes.__name__
        }

        assert defined <= set(DOCUMENTED_ERRORS), sorted(defined - set(DOCUMENTED_ERRORS))


# --- 2. POST /remodel/probe -------------------------------------------------------------


class TestProbe:
    def test_an_in_scope_part_answers_the_probe_id_the_signals_and_no_refusal(
        self, client: TestClient, source: Path
    ) -> None:
        body = probe(client, source).json()

        assert body["probe_id"] == PROBE_ID
        assert body["refusals"] == []
        assert ScopeSignals(**body["signals"]) == ScopeSignals(**scope_signals())

    def test_the_gate_and_not_the_bridge_decides(
        self, client: TestClient, source: Path, bridge: ProbingBridge
    ) -> None:
        """`remodel.probe_scope` reads; `remodel/scope.py` decides. The bridge answered
        `ok` here and the part is still refused, which is the whole division."""
        bridge.signals = scope_signals(is_weldment=True, solid_body_count=3)

        body = probe(client, source).json()

        assert len(body["refusals"]) == 2, body["refusals"]
        assert any("weldment" in sentence for sentence in body["refusals"])
        assert any("solid_body_count" in sentence for sentence in body["refusals"])

    def test_an_unreadable_signal_refuses_rather_than_passing(
        self, client: TestClient, source: Path, bridge: ProbingBridge
    ) -> None:
        """An unread signal is never a pass (`scope.py`), and the route reports it as a
        refusal like any other because an empty `refusals` is the only ok."""
        bridge.signals = scope_signals(is_weldment=None)

        [refusal] = probe(client, source).json()["refusals"]

        assert "is_weldment" in refusal

    def test_the_probe_names_the_source_and_nothing_else(
        self, client: TestClient, source: Path, bridge: ProbingBridge
    ) -> None:
        probe(client, source)

        assert bridge.commands == ("remodel.probe_scope",)
        assert bridge.calls[0][1] == {"source_path": str(source)}

    def test_the_bridge_secret_is_never_echoed(
        self, client: TestClient, source: Path, asked: list[tuple[str, str | None]]
    ) -> None:
        response = probe(client, source)

        assert asked == [(PIPE, SECRET)]
        assert SECRET not in response.text

    def test_a_probe_of_an_unknown_source_is_refused_before_anything_is_copied(
        self, client: TestClient, source: Path, bridge: ProbingBridge
    ) -> None:
        bridge.probe_raises = RemodelPreflightError(
            "C:\\work\\bracket.SLDASM is not a part", "not_a_part", {}
        )

        response = probe(client, source)

        assert response.status_code == 400
        assert response.json()["error_class"] == "NotAPart"
        assert bridge.opens == 0


# --- 3. the bridge error table --------------------------------------------------------


REFUSALS: tuple[tuple[str, str], ...] = (
    ("not_a_part", "NotAPart"),
    ("source_dirty", "DocumentDirty"),
    ("external_refs", "ExternalReferences"),
    ("scope_not_probed", "ScopeRefused"),
    ("scope_changed", "ScopeRefused"),
    ("copy_failed", "RunFolderFailed"),
    ("copy_exists", "RunFolderFailed"),
    ("tag_failed", "RunFolderFailed"),
    ("a_token_from_a_later_host", "RunFolderFailed"),
)
"""The contract's mapping, token by token, plus a token this build has never heard of."""


class TestTheRefusalMapping:
    @pytest.mark.parametrize(("code", "error_class"), REFUSALS)
    def test_every_bridge_error_code_becomes_a_named_refusal(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        bridge: ProbingBridge,
        code: str,
        error_class: str,
    ) -> None:
        sentence = f"the host refused with {code}"
        bridge.open_raises = RemodelError(sentence, code, {})

        response = open_copy(client, run_dir, source)

        assert response.status_code == 400, response.text
        body = response.json()
        assert body["error_class"] == error_class
        assert sentence in body["message"], "the host's own sentence is what the page reads"

    def test_an_open_circuit_is_a_retryable_bridge_failure(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        """An open circuit is returned by the client, not raised, and nothing was sent."""
        bridge.open_returns = CircuitOpen(
            command="remodel.open", last_error="the bridge stopped answering"
        )

        response = open_copy(client, run_dir, source)

        assert response.status_code == 502
        assert response.json()["error_class"] == "BridgeUnavailable"
        assert response.json()["retryable"] is True

    def test_a_probe_on_an_open_circuit_is_the_same_failure(
        self, client: TestClient, source: Path, bridge: ProbingBridge
    ) -> None:
        bridge.probe_returns = CircuitOpen(command="remodel.probe_scope", last_error=None)

        assert probe(client, source).json()["error_class"] == "BridgeUnavailable"


# --- 4. POST /remodel/open --------------------------------------------------------------


class TestOpen:
    def test_the_copy_is_reported_present_with_a_clean_baseline(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        body = open_copy(client, run_dir, source).json()

        assert body == {
            "copy_path": copy_path_of(run_dir),
            "rebuild_error_count": 0,
            "copy_present": True,
        }

    def test_the_copy_path_is_derived_from_the_run_folder(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        """`<run>/copy/<name>-RMS.SLDPRT`, the convention `Rms/RemodelCopy.cs` writes.
        The copy lives only in the run folder: it never sits beside the source."""
        open_copy(client, run_dir, source)

        [(_, params)] = [call for call in bridge.calls if call[0] == "remodel.open"]
        assert params["copy_path"] == copy_path_of(run_dir)
        assert params["run_id"] == RUN_ID
        assert params["probe_id"] == PROBE_ID

    def test_open_writes_the_attestation_and_the_open_record(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """Both files exist so `POST /remodel/runs` can rebuild the runner's inputs from
        the folder alone, which is what lets the pane answer after a restart."""
        open_copy(client, run_dir, source)

        attestation = read_attestation(run_dir)
        assert attestation.path == str(source)
        assert attestation.source_design_id == SOURCE_DESIGN_ID
        assert attestation.matches is None, "the re-check is phase D's, not this route's"

        record = json.loads((run_dir / OPEN_FILE_NAME).read_text(encoding="utf-8"))
        assert set(record) == {
            "copy_path",
            "rebuild_error_count",
            "document_length_unit",
            "which_configs",
            "scope_signals",
            "probe_id",
            "geometry_before",
            "configuration",
        }
        assert record["document_length_unit"] == UNIT
        assert record["probe_id"] == PROBE_ID
        assert record["geometry_before"]["subject"] == "copy_at_open"
        assert ScopeSignals(**record["scope_signals"]) == ScopeSignals(**scope_signals())

    def test_the_baseline_geometry_is_read_from_the_copy_at_open(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        """FR-037: the source is never opened for the comparison in any mode, so the
        reading taken here is what stands for it."""
        open_copy(client, run_dir, source)

        assert bridge.geometry_readings == 1
        assert bridge.commands == ("remodel.open", "remodel.geometry")

    def test_preexisting_rebuild_errors_answers_the_count_and_no_copy(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        """The one refusal that happens after a copy exists. The bridge has already
        deleted it, so the host takes its own `PreexistingRebuildErrors` path from a 200
        rather than from an error body."""
        bridge.open_raises = RemodelPreflightError(
            "the part already has 3 rebuild errors",
            "preexisting_rebuild_errors",
            {"rebuild_error_count": 3},
        )

        response = open_copy(client, run_dir, source)

        assert response.status_code == 200
        assert response.json() == {
            "copy_path": copy_path_of(run_dir),
            "rebuild_error_count": 3,
            "copy_present": False,
        }

    def test_a_count_the_refusal_does_not_carry_stays_unknown(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        """Unknown is not zero: a baseline nobody could read is null, and the host's own
        handler says so rather than reporting a clean part."""
        bridge.open_raises = RemodelPreflightError(
            "the count could not be read", "preexisting_rebuild_errors", {}
        )

        body = open_copy(client, run_dir, source).json()

        assert body["rebuild_error_count"] is None
        assert body["copy_present"] is False

    def test_the_secret_reaches_the_client_and_no_artifact(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        response = open_copy(client, run_dir, source)

        assert SECRET not in response.text
        assert SECRET not in (run_dir / OPEN_FILE_NAME).read_text(encoding="utf-8")
        assert SECRET not in (run_dir / ATTESTATION_FILE_NAME).read_text(encoding="utf-8")

    def test_a_run_dir_outside_the_run_root_is_refused_by_the_path_rule(
        self, client: TestClient, tmp_path: Path, source: Path
    ) -> None:
        response = open_copy(client, tmp_path / "elsewhere", source)

        assert response.status_code == 400
        assert response.json()["error_class"] == "InvalidRunDir"


# --- 5. POST /remodel/plan --------------------------------------------------------------


class TestPlan:
    def test_a_folder_with_no_dump_is_refused(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        assert probe(client, source).status_code == 200
        assert open_copy(client, run_dir, source).status_code == 200

        response = plan(client, run_dir)

        assert response.status_code == 400
        assert response.json()["error_class"] == "PackageMissing"

    def test_a_dump_at_the_wrong_profile_is_refused(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """The plan is made over a ModelCheck dump of the copy and over nothing else: a
        design-review dump carries different evidence and would plan a different part."""
        assert probe(client, source).status_code == 200
        assert open_copy(client, run_dir, source).status_code == 200
        wrong = PACKAGE.model_copy(
            update={"extractor": PACKAGE.extractor.model_copy(update={"profile": "review"})}
        )
        dumped(run_dir, PACKAGE_BEFORE, wrong)

        response = plan(client, run_dir)

        assert response.status_code == 400
        assert response.json()["error_class"] == "NotModelCheck"

    def test_the_plan_summary_is_the_row_the_command_line_prints(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        summary = planned(client, run_dir, source)["plan_summary"]

        assert summary["document_id"] == PACKAGE.documents[0].document_id
        assert summary["state"] == "planned"
        assert set(summary) >= {
            "file_name",
            "content_features",
            "reaching_target_group",
            "reorganizable_fraction",
            "move_count",
            "changes",
            "pins",
            "rebuild",
            "rebuild_by_reason",
            "folders",
            "scope",
            "refusals",
            "coverage",
        }
        assert summary["reorganizable_fraction"]["of"] >= 1

    def test_the_plan_records_the_copy_and_the_source_together(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """A plan that knew the copy's path but not what it was copied from is one nobody
        could attest, so `RemodelPlan` refuses the three apart."""
        planned(client, run_dir, source)

        written = RemodelPlan.model_validate_json(
            plan_path(run_dir).read_text(encoding="utf-8")
        )
        assert written.run_id == RUN_ID
        assert written.copy_path == copy_path_of(run_dir)
        assert written.source is not None
        assert written.source.path == str(source)
        assert written.state == "planned"
        assert written.plan_revision == 1

    def test_the_scope_signals_planned_from_are_the_copys(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """`open.json` carries the signals measured on the copy at step 12, and the plan
        describes the document the run actually changes."""
        planned(client, run_dir, source)

        written = RemodelPlan.model_validate_json(
            plan_path(run_dir).read_text(encoding="utf-8")
        )
        assert written.scope.probe_id == PROBE_ID

    def test_an_earlier_runs_waivers_are_carried_forward(
        self, client: TestClient, run_root: Path, run_dir: Path, source: Path
    ) -> None:
        """The grades before and after are measured against the same waivers, so the
        newest same-source store is copied in before the plan is written."""
        _earlier_run(run_root, store='{"exceptions": []}')

        planned(client, run_dir, source)

        assert (run_dir / EXCEPTIONS_FILE_NAME).is_file()

    def test_a_candidate_store_that_will_not_parse_refuses_the_run(
        self, client: TestClient, run_root: Path, run_dir: Path, source: Path
    ) -> None:
        """FR-029: a candidate that exists and cannot be read is a refusal and not a
        skip. Both grades of this run are measured against those waivers, and measuring
        them against a store nobody could read would be two measurements reported as one.
        """
        _earlier_run(run_root, store="{ not json")
        assert probe(client, source).status_code == 200
        assert open_copy(client, run_dir, source).status_code == 200
        dumped(run_dir, PACKAGE_BEFORE)

        response = plan(client, run_dir)

        assert response.status_code == 400
        assert response.json()["error_class"] == "RunFolderFailed"

    def test_planning_sends_no_bridge_call_at_all(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        """Phase A is pure: it reads the dump and the folder and asks the seat nothing."""
        assert probe(client, source).status_code == 200
        assert open_copy(client, run_dir, source).status_code == 200
        dumped(run_dir, PACKAGE_BEFORE)
        before = len(bridge.calls)

        assert plan(client, run_dir).status_code == 200

        assert bridge.calls[before:] == []


def _earlier_run(run_root: Path, *, store: str) -> Path:
    """A Model check of the same source, holding the waivers this run inherits."""
    earlier = run_root / "20260915-090000-bracket-check"
    earlier.mkdir()
    (earlier / ATTESTATION_FILE_NAME).write_text(
        json.dumps({"source_design_id": SOURCE_DESIGN_ID}), encoding="utf-8"
    )
    (earlier / EXCEPTIONS_FILE_NAME).write_text(store, encoding="utf-8")
    return earlier


def _limit_to_one_change(run_dir: Path) -> None:
    """Bound the planned run at one change, so the run truncates without a race.

    The bound is the executor's own and is read between changes, exactly where the
    engineer's stop is read, so this drives the truncated finish deterministically and
    without a second thread to time.
    """
    path = plan_path(run_dir)
    plan = RemodelPlan.model_validate_json(path.read_text(encoding="utf-8"))
    bounded = plan.model_copy(update={"limits": Limits(max_changes=1)})
    path.write_text(bounded.model_dump_json(indent=2) + "\n", encoding="utf-8")


# --- 6. POST /remodel/runs and the job ---------------------------------------------------


class TestStartingARun:
    def test_a_folder_with_no_plan_is_refused(
        self, client: TestClient, run_dir: Path
    ) -> None:
        response = start(client, run_dir)

        assert response.status_code == 409
        assert response.json()["error_class"] == "RunNotPlanned"

    def test_a_folder_holding_a_change_log_is_never_auto_resumed(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """FR-031: after a lost session the copy and the log survive on disk and recovery
        is manual. A resumed run over a tree nobody re-verified is the wrong risk."""
        planned(client, run_dir, source)
        (run_dir / CHANGES_FILE_NAME).write_text("{}\n", encoding="utf-8")

        response = start(client, run_dir)

        assert response.status_code == 409
        assert response.json()["error_class"] == "ResumeRefused"

    def test_a_second_run_on_a_folder_a_live_run_holds_is_refused_as_in_progress(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One run per folder, said of a run that is genuinely under way.

        The live job is the most specific fact and outranks the other two refusals, which
        a run past its first few milliseconds makes true of its own folder: `judge` moves
        the plan off `planned` and the apply phase opens a change log. Answering
        `RunNotPlanned` here would tell an engineer to plan a part a run is writing to.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])
        wait_for(client, job_id, lambda state: state["awaiting"] == "package_after")

        second = start(client, run_dir)

        assert second.status_code == 409
        assert second.json()["error_class"] == "RunInProgress"
        assert job_id in second.json()["message"]
        deliver_package_after(client, job_id, run_dir)

    def test_a_second_run_pressed_straight_after_the_first_is_refused_the_same_way(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The fast path: the second press lands before the worker has touched anything,
        and the answer is the same one, because it is decided by the job registry rather
        than by how far the run has got."""
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        first = start(client, run_dir)
        assert first.status_code == 201

        second = start(client, run_dir)

        assert second.status_code == 409
        assert second.json()["error_class"] == "RunInProgress"
        job_id = str(first.json()["job_id"])
        wait_for(client, job_id, lambda state: state["awaiting"] == "package_after")
        deliver_package_after(client, job_id, run_dir)

    def test_the_reply_names_the_job_as_the_chat(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """The pane addresses a remodel run the way it addresses a chat, so the pipeline
        has one id to poll, to stream and to stop."""
        planned(client, run_dir, source)

        body = start(client, run_dir).json()

        assert body["job_id"] == body["chat_id"]

    def test_an_unknown_job_is_a_404_on_every_job_route(
        self, client: TestClient
    ) -> None:
        for response in (
            client.get("/remodel/runs/nobody"),
            client.get("/remodel/runs/nobody/events"),
            client.post("/remodel/runs/nobody/stop", json={}),
            client.post("/remodel/runs/nobody/package-after", json={"path": "x"}),
        ):
            assert response.status_code == 404, response.text
            assert response.json()["error_class"] == "UnknownJob"


class TestARunToCompletion:
    def test_the_run_reaches_its_terminal_state_with_every_artifact(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calibrated(monkeypatch)

        job_id, state = run_to_completion(client, run_dir, source)

        assert state["state"] == "finished", state
        assert state["plan_state"] in {"saved", "truncated"}
        assert state["error"] is None
        assert state["changes_applied"] == state["changes_total"]
        assert (run_dir / CHANGES_FILE_NAME).is_file()
        assert (run_dir / "events.jsonl").is_file()
        assert status_of(client, job_id)["awaiting"] is None

    def test_the_progress_counts_come_off_the_change_log(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calibrated(monkeypatch)
        job_id, _ = run_to_completion(client, run_dir, source)

        state = status_of(client, job_id)

        records = read_changes(run_dir / CHANGES_FILE_NAME)
        landed = [row for row in records if row.status == "applied" and row.kind != "save"]
        assert state["changes_total"] == len(
            RemodelPlan.model_validate_json(
                plan_path(run_dir).read_text(encoding="utf-8")
            ).changes
        )
        assert state["changes_applied"] == len(landed)
        # The save is the last line of every run that passed the gate, and it is not a
        # planned change: its `seq` is the next free one in the log, so reporting it as
        # `current` would name a planned change nothing attempted.
        assert records[-1].kind == "save"
        assert state["current"] is None

    def test_the_current_change_is_the_last_line_while_the_run_is_working(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])
        state = wait_for(client, job_id, lambda s: s["awaiting"] == "package_after")

        records = read_changes(run_dir / CHANGES_FILE_NAME)
        assert state["current"]["seq"] == records[-1].seq
        assert state["current"]["kind"] == records[-1].kind
        deliver_package_after(client, job_id, run_dir)

    def test_a_truncated_run_reports_the_changes_that_landed_and_not_the_whole_plan(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A run stopped short still writes the `save` line, and `changes_applied` counts
        what landed rather than reading that line as "all of them".

        `truncated` is never silent (data-model.md section 11): a pane told `3 of 3` about
        a run that applied one would be a truncated run reported as a completed one.
        """
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        _limit_to_one_change(run_dir)
        job_id = str(start(client, run_dir).json()["job_id"])
        wait_for(client, job_id, lambda s: s["awaiting"] == "package_after")
        assert deliver_package_after(client, job_id, run_dir).status_code == 200

        state = wait_for(client, job_id, lambda s: s["state"] in {"finished", "failed"})

        records = read_changes(run_dir / CHANGES_FILE_NAME)
        assert state["plan_state"] == "truncated"
        assert state["changes_total"] > 1
        assert state["changes_applied"] == 1
        assert [row.seq for row in records if row.status == "applied"] == [1, 2]
        assert records[-1].kind == "save"
        assert state["current"] is None

    def test_the_events_route_replays_the_run_after_a_sequence_number(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calibrated(monkeypatch)
        job_id, _ = run_to_completion(client, run_dir, source)

        whole = client.get(f"/remodel/runs/{job_id}/events").json()
        rest = client.get(f"/remodel/runs/{job_id}/events?after=1").json()

        assert whole["events"], "a run that judged and applied writes events"
        assert whole["next"] == whole["events"][-1]["seq"]
        assert [event["seq"] for event in rest["events"]] == [
            event["seq"] for event in whole["events"] if event["seq"] > 1
        ]

    def test_the_source_is_named_in_no_bridge_call_after_the_open(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        bridge: ProbingBridge,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`RemodelScope` holds the only document the run can reach after `remodel.open`,
        and this is that property asserted over a whole run's call log."""
        calibrated(monkeypatch)
        run_to_completion(client, run_dir, source)

        opened = [index for index, call in enumerate(bridge.calls) if call[0] == "remodel.open"]
        after = bridge.calls[opened[-1] + 1 :]
        assert after, "a run that applied changes sent something after the open"
        assert str(source) not in json.dumps(after)

    def test_the_delivered_dump_is_the_one_the_run_graded(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The rendezvous is not a formality: what the add-in posted is what phase D
        graded, which is why `rms-after.json` and `grades.json` exist at all."""
        calibrated(monkeypatch)
        run_to_completion(client, run_dir, source)

        assert (run_dir / "rms-after.json").is_file()
        assert (run_dir / "grades.json").is_file()

    def test_the_run_stops_where_fr_036_stops_it_when_the_profile_is_uncalibrated(
        self, client: TestClient, run_dir: Path, source: Path
    ) -> None:
        """The shipped profile is `IDENTITY`, uncalibrated until PROBE-8 measures it, and
        a profile nobody calibrated may not decide a run. The job reports that failure
        before the provider, bridge, or package-after rendezvous is entered."""
        planned(client, run_dir, source)
        started = start(client, run_dir)
        assert started.status_code == 201, started.text
        job_id = str(started.json()["job_id"])
        state = wait_for(client, job_id, lambda item: item["state"] == "failed")

        assert state["state"] == "failed"
        assert "calibrat" in (state["error"] or "")
        assert state["plan_state"] == "planned"
        assert not (run_dir / CHANGES_FILE_NAME).exists()


class TestThePackageAfterRendezvous:
    def test_any_path_but_the_run_folders_after_dump_is_refused(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])
        wait_for(client, job_id, lambda state: state["awaiting"] == "package_after")

        elsewhere = tmp_path / "somebody-elses-dump.json"
        elsewhere.write_text(PACKAGE.model_dump_json(indent=2), encoding="utf-8")
        response = deliver_package_after(client, job_id, run_dir, path=str(elsewhere))

        assert response.status_code == 400
        assert response.json()["error_class"] == "PackageAfterRefused"
        assert deliver_package_after(client, job_id, run_dir).status_code == 200

    def test_a_file_that_is_not_a_model_check_dump_is_refused(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calibrated(monkeypatch)
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])
        wait_for(client, job_id, lambda state: state["awaiting"] == "package_after")
        (run_dir / PACKAGE_AFTER).write_text("{}", encoding="utf-8")

        response = client.post(
            f"/remodel/runs/{job_id}/package-after",
            json={"path": str(run_dir / PACKAGE_AFTER)},
        )

        assert response.status_code == 400
        assert response.json()["error_class"] == "PackageAfterRefused"
        assert deliver_package_after(client, job_id, run_dir).status_code == 200

    def test_a_dump_that_never_arrives_fails_the_run_with_the_log_intact(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The rendezvous has a timeout because the dumper is another process's thread.
        On expiry the run finalizes as `failed`, the reason is on the plan, and the
        changes that were applied are still on disk."""
        calibrated(monkeypatch)
        app.state.remodel.package_after_timeout = 0.05
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])

        state = wait_for(client, job_id, lambda state: state["state"] == "failed")

        assert "package-after" in (state["error"] or "").lower()
        assert read_changes(run_dir / CHANGES_FILE_NAME), "the changes applied are kept"
        assert state["plan_state"] == "failed"


class TestStop:
    def test_stop_is_idempotent_and_sets_the_runs_flag(
        self, client: TestClient, run_dir: Path, source: Path, app: Any
    ) -> None:
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])

        first = client.post(f"/remodel/runs/{job_id}/stop", json={})
        second = client.post(f"/remodel/runs/{job_id}/stop", json={})

        assert first.json() == {"stopping": True}
        assert second.json() == {"stopping": True}
        assert app.state.remodel.jobs[job_id].stop.is_set()
        assert deliver_package_after(client, job_id, run_dir).status_code in {200, 409}

    def test_the_stop_flag_is_the_one_the_executor_reads(
        self, client: TestClient, run_dir: Path, source: Path, app: Any
    ) -> None:
        """`apply_changes` reads it between changes, so what the route sets and what the
        run asks are one flag and not two."""
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])
        job = app.state.remodel.jobs[job_id]

        assert job.stop.is_set() is False
        client.post(f"/remodel/runs/{job_id}/stop", json={})
        assert job.stop.is_set() is True

        deliver_package_after(client, job_id, run_dir)


# --- 7. POST /remodel/close ---------------------------------------------------------------


class TestClose:
    def test_closing_answers_closed_and_keeps_the_copy(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        """The host is the one deleter of `copy/`, so the route closes the document and
        discards nothing unless it is asked to."""
        assert open_copy(client, run_dir, source).status_code == 200

        response = close(client, run_dir)

        assert response.json() == {"closed": True}
        assert bridge.closed is True
        assert bridge.discards == 0

    def test_discarding_deletes_the_copy_and_nothing_else(
        self, client: TestClient, run_dir: Path, source: Path, bridge: ProbingBridge
    ) -> None:
        assert open_copy(client, run_dir, source).status_code == 200

        assert close(client, run_dir, discard_copy=True).json() == {"closed": True}

        assert bridge.discards == 1
        assert bridge.copy_exists is False

    def test_a_copy_that_is_not_open_is_a_no_op(
        self, client: TestClient, run_dir: Path, bridge: ProbingBridge
    ) -> None:
        """Closing twice, or closing after the bridge already closed the document on a
        refusal, is not an error: there is nothing left to do and nothing to report."""
        from swreview.bridge.client import BridgeDocumentClosedError

        bridge.closed = True

        def refuse(discard_copy: bool) -> Any:
            raise BridgeDocumentClosedError("no document is open on this bridge")

        bridge.close_document = refuse  # type: ignore[method-assign]

        assert close(client, run_dir).json() == {"closed": True}


# --- 8. the door, and no language model ---------------------------------------------------


class TestTheDoor:
    def test_a_request_with_no_token_is_401(self, app: Any, source: Path) -> None:
        with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
            response = probe(anonymous, source)

        assert response.status_code == 401
        assert response.json()["error_class"] == "Unauthorized"

    def test_a_request_from_another_origin_is_403(self, app: Any, source: Path) -> None:
        with TestClient(
            app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": OTHER_ORIGIN}
        ) as stranger:
            response = probe(stranger, source)

        assert response.status_code == 403
        assert response.json()["error_class"] == "ForbiddenOrigin"

    def test_a_preflight_is_answered_without_a_token(self, app: Any) -> None:
        with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
            response = anonymous.options("/remodel/probe")

        assert response.status_code == 204
        assert response.headers["access-control-allow-origin"] == ORIGIN


class TestNoLanguageModel:
    def test_the_eight_other_routes_run_with_every_provider_factory_raising(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SC-009: the deterministic half of this feature must work on a workstation with
        no key at all, so nothing but the judgement phase may look one up."""
        import swreview.cli as cli_module

        monkeypatch.setattr(providers, "get", refuse_provider)
        monkeypatch.setattr(cli_module, "provider_factory", refuse_provider)
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(name, raising=False)

        assert probe(client, source).status_code == 200
        assert open_copy(client, run_dir, source).status_code == 200
        dumped(run_dir, PACKAGE_BEFORE)
        assert plan(client, run_dir).status_code == 200
        assert close(client, run_dir).status_code == 200

    def test_the_run_route_builds_its_provider_only_through_the_runner(
        self,
        client: TestClient,
        run_dir: Path,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`remodel/runner.py::build_provider` is the one construction site, and a run
        whose adapter cannot be built records the absence and applies the plan anyway."""
        import swreview.cli as cli_module

        monkeypatch.setattr(cli_module, "provider_factory", refuse_provider)
        calibrated(monkeypatch)

        _, state = run_to_completion(client, run_dir, source)

        assert state["state"] == "finished", state


def test_no_module_of_the_routes_names_a_vendor_this_product_does_not_use() -> None:
    """The owner decision, asserted rather than remembered: OpenAI and Gemini only."""
    text = Path(remodel_routes.__file__).read_text(encoding="utf-8").lower()

    assert "anthropic" not in text
    assert "claude" not in text


def test_the_job_registry_is_empty_until_a_run_is_started(app: Any) -> None:
    assert app.state.remodel.jobs == {}


def test_the_package_after_timeout_defaults_to_the_documented_ten_minutes(
    app: Any,
) -> None:
    assert app.state.remodel.package_after_timeout == 600.0


def test_a_waiting_job_is_released_when_the_backend_shuts_down(
    run_root: Path,
    run_dir: Path,
    source: Path,
    bridge: ProbingBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job blocked on the rendezvous must not outlive the process that owns it: the
    shutdown that finalizes every chat releases every waiting run as well."""

    calibrated(monkeypatch)
    app = create_app(
        token=TOKEN,
        allow_origin=ORIGIN,
        run_root=run_root,
        provider_factory=refuse_provider,
        list_models=refuse_provider,
        remodel_bridge_factory=lambda pipe, secret: bridge,
    )
    with TestClient(
        app, headers={"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    ) as client:
        planned(client, run_dir, source)
        job_id = str(start(client, run_dir).json()["job_id"])
        wait_for(client, job_id, lambda state: state["awaiting"] == "package_after")
        job = app.state.remodel.jobs[job_id]

    deadline = time.monotonic() + WAIT_S
    while job.live and time.monotonic() < deadline:
        time.sleep(POLL_S)
    assert job.state == "failed"


def test_the_stop_event_and_the_arrival_event_are_distinct(app: Any) -> None:
    """Two flags, two questions: one ends the apply loop, the other ends the wait."""
    job = remodel_routes.RemodelJob(job_id="j", run_dir=Path("."))

    assert isinstance(job.stop, threading.Event)
    assert job.stop is not job.arrived


def test_the_documented_error_classes_carry_their_sentences(
    client: TestClient, run_dir: Path
) -> None:
    """Every refusal body is the contract's `{error_class, message, retryable}`."""
    body = start(client, run_dir).json()

    assert set(body) == {"error_class", "message", "retryable"}
    assert isinstance(body["message"], str) and body["message"]


def test_the_run_root_is_the_servers_own(app: Any, run_root: Path) -> None:
    assert Path(app.state.remodel.run_root) == run_root


def test_every_route_of_the_contract_answers_something(
    client: TestClient, run_dir: Path
) -> None:
    """A smoke pass over the nine paths: none of them 404s as an unrouted path would."""
    seen: set[tuple[str, str]] = set()
    for method, path in sorted(DOCUMENTED_ROUTES):
        concrete = path.replace("{job_id}", "nobody")
        response = (
            client.get(concrete)
            if method == "GET"
            else client.post(concrete, json={"run_dir": str(run_dir)})
        )
        assert response.headers["content-type"].startswith("application/json")
        seen.add((method, path))
    assert seen == DOCUMENTED_ROUTES
