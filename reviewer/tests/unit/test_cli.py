"""Unit tests for the `swreview` command line (T043, T081 CLI half, T097).

Every command of contracts/cli.md is exercised on files this test makes: a written
evidence package, a manifest and BOM, a scripted-provider review, a synthetic benchmark
run. The three rules the contract states for all of them are asserted per command:

- exit 0 on success, 1 on a validation or runtime error, 2 on a usage error;
- `--json` prints machine-readable output on stdout and nothing else;
- diagnostics go to stderr, so a `--json` consumer never has to parse around them.

No network: `swreview.cli.provider_factory` is the injection point the review commands
build their adapter through (T023, replacing feature 001's `REVIEW_CLIENT`), and the
fixture below swaps it for one that returns a scripted `FakeProvider`. The settings the
CLI resolved reach the test on the provider it built, which is how `--provider`,
`--model` and `--effort` are asserted without sending anything anywhere.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from swreview import cli
from swreview.agent.providers import ProviderName
from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
from swreview.agent.settings import (
    ENTERPRISE_ENV,
    MASK,
    EfficiencySettings,
    GeminiEnterprise,
    ProviderSettings,
)
from swreview.checks.golden_interference import interference_case
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from tests.unit.test_tools_checks_fastener import joint_package
from tests.unit.test_tools_checks_fit import drawing_package

REPO_ROOT = Path(__file__).resolve().parents[3]
COVER_BLIND_TAP = REPO_ROOT / "benchmarks" / "packages" / "cover-blind-tap"

MakePackage = Callable[..., EvidencePackage]

runner = CliRunner()


# --- the environment these tests run in ------------------------------------------

PROVIDER_ENV: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    *ENTERPRISE_ENV,
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
)
"""Every variable `ProviderSettings.from_env` reads, including the ones it reads only for
the provider that was not asked for."""


@pytest.fixture(autouse=True)
def empty_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every command against an empty provider environment, not the developer's.

    The commands call `ProviderSettings.from_env` with no `env=`, so without this the
    settings object under assertion is whatever the workstation exports: a seat with
    `GOOGLE_GENAI_USE_VERTEXAI=true` and no `GOOGLE_CLOUD_LOCATION` - a Gemini Enterprise
    engineer, which is this product's audience - turns the two default-model tests red,
    and `OPENAI_API_KEY`, `OPENAI_BASE_URL` and the Google key variables change
    `key_source`, `base_url` and `enterprise` silently. A test that wants one of these set
    sets it itself, which is what makes the env-derived assertions below mean anything.
    """
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


# --- the scripted provider -------------------------------------------------------


class RecordingProvider(FakeProvider):
    """A scripted provider that keeps what the CLI resolved and what the runner bound.

    `settings` is the `ProviderSettings` the command built from `--provider`, `--model`
    and `--effort`; `efficiency` is what it built from `--lever`, which the real factory
    reads for the one lever decided at construction (lever 6); `tool_names` is what
    `start_review` handed the turn, which is how the `--bridge` tests see the three bridge
    tools appear and disappear.

    It reports the chosen provider's name rather than `fake`, because it stands in for
    whichever adapter the factory would have built: that is what makes `provider_info` in
    `session.json` an assertion about `--provider` reaching the session.
    """

    def __init__(
        self,
        *,
        settings: ProviderSettings,
        script: Sequence[ScriptedTurn],
        efficiency: EfficiencySettings | None = None,
    ) -> None:
        super().__init__(script=script, model=settings.model)
        self.name = settings.provider
        self.settings = settings
        self.efficiency = efficiency
        self.tool_names: tuple[str, ...] = ()

    def run(self, **kwargs: Any) -> Any:
        self.tool_names = tuple(tool.name for tool in kwargs["tools"])
        return super().run(**kwargs)


DRAWING_FINDING = ScriptedToolCall(
    "record_drawing_finding",
    {
        "document_id": "doc:2",
        "sheet": "Sheet1",
        "observed": "The tapped hole is called out without a thread depth",
        "requirement": "A tapped hole callout states the usable thread depth",
        "source_refs": [{"document_id": "doc:2", "sheet": "Sheet1"}],
        "status": "suspected",
        "recommended_action": "Add the tapped depth to the hole callout",
    },
)

SCRIPT: tuple[ScriptedTurn, ...] = (
    ScriptedTurn(
        text="One drawing finding recorded.",
        tool_calls=(ScriptedToolCall("get_package_summary"), DRAWING_FINDING),
    ),
)


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[RecordingProvider]]:
    """Swap `cli.provider_factory` for one that scripts every adapter the CLI asks for.

    The returned list fills in as reviews run - one entry per adapter built - so a test
    reads back the settings the command resolved without the CLI exposing them.
    """

    def install(script: Sequence[ScriptedTurn] = SCRIPT) -> list[RecordingProvider]:
        built: list[RecordingProvider] = []

        def factory(
            settings: ProviderSettings, efficiency: EfficiencySettings | None = None
        ) -> RecordingProvider:
            provider = RecordingProvider(
                settings=settings, script=script, efficiency=efficiency
            )
            built.append(provider)
            return provider

        monkeypatch.setattr(cli, "provider_factory", factory)
        return built

    return install


# --- helpers ---------------------------------------------------------------------


MANIFEST: dict[str, Any] = {
    "design": {
        "design_id": "dsn:1",
        "name": "cover-assy",
        "root_assembly_document_id": "ASM-1",
        "active_configuration": "Default",
        "drawing_document_ids": [],
    },
    "entries": [
        {
            "document_id": "ASM-1",
            "vault_path": "Projects/cover-assy.SLDASM",
            "vault_version": 7,
            "revision": "B",
            "configuration": "Default",
            "local_modified": False,
            "export_method": "manual",
        },
        {
            "document_id": "PRT-1",
            "vault_path": "Projects/housing.SLDPRT",
            "vault_version": 12,
            "revision": "C",
            "configuration": "Default",
            "local_modified": False,
            "export_method": "manual",
        },
    ],
}

BOM = (
    "item,part_number,document_id,description,quantity,configuration\n"
    "1,P-1,PRT-1,Housing 6061-T6,1,Default\n"
)


def invoke(*args: str) -> Any:
    """Run the app with `args` and return the click result."""
    return runner.invoke(cli.app, list(args))


def payload(result: Any) -> Any:
    """The `--json` stdout of a command, parsed."""
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    return json.loads(result.stdout)


def write_inputs(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")
    bom_path = directory / "bom.csv"
    bom_path.write_text(BOM, encoding="utf-8")
    return manifest_path, bom_path


@pytest.fixture
def fit_package_dir(tmp_path: Path, make_package: MakePackage) -> Path:
    """A written package carrying the drawing dimensions the check commands resolve."""
    directory = tmp_path / "fit-package"
    save_package(drawing_package(make_package), directory)
    return directory


@pytest.fixture
def joint_package_dir(tmp_path: Path, make_package: MakePackage) -> Path:
    """A written package carrying the joint the fastener and alignment commands check."""
    directory = tmp_path / "joint-package"
    save_package(joint_package(make_package), directory)
    return directory


JOINT_SCRIPT: tuple[ScriptedTurn, ...] = (
    ScriptedTurn(
        text="One joint checked.",
        tool_calls=(
            ScriptedToolCall(
                "check_fastener_joint",
                {
                    "fastener_id": "fst:1",
                    "hole_id": "hole:1",
                    "clamped_component_ids": ["cmp:0002"],
                },
            ),
        ),
    ),
)


@pytest.fixture
def joint_run_dir(
    tmp_path: Path, tmp_package_dir: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> Path:
    """A finished review whose findings name components, so they can be excepted."""
    fake_provider(JOINT_SCRIPT)
    out = tmp_path / "joint-run"
    result = invoke("review", str(tmp_package_dir), "--out", str(out))
    assert result.exit_code == 0, result.stdout
    return out


@pytest.fixture
def run_dir(
    tmp_path: Path, tmp_package_dir: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> Path:
    """A finished review: `session.json` with one finding, and `report.md`."""
    fake_provider()
    out = tmp_path / "run"
    result = invoke("review", str(tmp_package_dir), "--out", str(out))
    assert result.exit_code == 0, result.stdout
    return out


# --- validate --------------------------------------------------------------------


def test_validate_prints_the_census_gaps_and_discrepancies(tmp_package_dir: Path) -> None:
    result = invoke("validate", str(tmp_package_dir))

    assert result.exit_code == 0
    assert "dsn:1" in result.stdout
    assert "usable thread depth not reported" in result.stdout


def test_validate_json_is_machine_readable(tmp_package_dir: Path) -> None:
    body = payload(invoke("validate", str(tmp_package_dir), "--json"))

    assert body["design_id"] == "dsn:1"
    assert body["counts"]["holes"] == 1
    assert body["gaps"][0]["entity_id"] == "hole:1"
    assert body["discrepancies"] == []


def test_validate_on_a_missing_package_exits_1(tmp_path: Path) -> None:
    result = invoke("validate", str(tmp_path / "nowhere"))

    assert result.exit_code == 1
    assert "package.json" in result.stderr
    assert result.stdout == ""


def test_validate_on_a_malformed_package_exits_1(tmp_path: Path) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "package.json").write_text('{"schema_version": "1.0.0"}', encoding="utf-8")

    result = invoke("validate", str(directory))

    assert result.exit_code == 1
    assert result.stderr.strip().count("\n") == 0


def test_validate_without_a_package_dir_is_a_usage_error() -> None:
    assert invoke("validate").exit_code == 2


@pytest.mark.skipif(
    not (COVER_BLIND_TAP / "package.json").is_file(),
    reason=f"benchmark package not assembled: {COVER_BLIND_TAP}",
)
def test_validate_reads_the_committed_benchmark_package() -> None:
    body = payload(invoke("validate", str(COVER_BLIND_TAP), "--json"))

    assert body["design_id"] == "cover-blind-tap"
    assert body["counts"]["components"] > 0


# --- ingest ----------------------------------------------------------------------


def test_ingest_builds_a_package_from_exported_files(tmp_path: Path) -> None:
    manifest_path, bom_path = write_inputs(tmp_path / "inputs")
    package_dir = tmp_path / "package"

    body = payload(
        invoke(
            "ingest",
            str(package_dir),
            "--manifest",
            str(manifest_path),
            "--bom",
            str(bom_path),
            "--json",
        )
    )

    assert (package_dir / "package.json").is_file()
    assert body["counts"]["documents"] == 2
    assert body["package_file"].endswith("package.json")


def test_ingest_without_a_manifest_is_a_usage_error(tmp_path: Path) -> None:
    _, bom_path = write_inputs(tmp_path / "inputs")

    result = invoke("ingest", str(tmp_path / "package"), "--bom", str(bom_path))

    assert result.exit_code == 2


def test_ingest_with_a_missing_bom_exits_1(tmp_path: Path) -> None:
    manifest_path, _ = write_inputs(tmp_path / "inputs")

    result = invoke(
        "ingest",
        str(tmp_path / "package"),
        "--manifest",
        str(manifest_path),
        "--bom",
        str(tmp_path / "nowhere.csv"),
    )

    assert result.exit_code == 1
    assert result.stderr


# --- review ----------------------------------------------------------------------


def test_review_writes_a_session_and_a_report(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    fake_provider()
    out = tmp_path / "run"

    body = payload(invoke("review", str(tmp_package_dir), "--out", str(out), "--json"))

    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert session["design_id"] == "dsn:1"
    assert [finding["id"] for finding in session["findings"]] == ["F-001"]
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "F-001" in report
    assert body["findings"] == 1
    assert body["session_file"].endswith("session.json")
    assert body["report_file"].endswith("report.md")


def test_review_without_a_provider_runs_openai_on_its_default_model(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    """FR-026: no flag means OpenAI and the model `agent/settings.py` names for it - the
    retired vendor's id is not written into `session.json` by any path."""
    built = fake_provider()
    out = tmp_path / "run"

    body = payload(invoke("review", str(tmp_package_dir), "--out", str(out), "--json"))

    assert built[0].settings.provider is ProviderName.OPENAI
    assert built[0].settings.model == "gpt-5.6"
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert session["model"] == "gpt-5.6"
    assert session["provider_info"]["provider"] == "openai"
    assert body["model"] == "gpt-5.6"


def test_review_without_a_model_takes_the_chosen_providers_default(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    built = fake_provider()
    out = tmp_path / "run"

    result = invoke("review", str(tmp_package_dir), "--out", str(out), "--provider", "gemini")

    assert result.exit_code == 0, result.stdout + result.stderr
    assert built[0].settings.model == "gemini-3.5-flash"
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert session["model"] == "gemini-3.5-flash"
    assert session["provider_info"]["provider"] == "gemini"


def test_review_with_the_fake_provider_needs_no_key_and_writes_a_session(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """The real `cli.provider_factory`, not the fixture: `--provider fake` is the dry run
    a workstation with no credentials can take, and it still writes both output files."""
    out = tmp_path / "run"

    result = invoke("review", str(tmp_package_dir), "--out", str(out), "--provider", "fake")

    assert result.exit_code == 0, result.stdout + result.stderr
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert session["model"] == "fake-scripted"
    assert session["provider_info"] == {
        "provider": "fake",
        "model": "fake-scripted",
        "effort_mapping": {
            "requested": "high",
            "provider_param": "fake.effort",
            "provider_value": "high",
        },
        "key_source": "none",
    }
    assert (out / "events.jsonl").is_file()


def test_review_on_openai_without_a_key_exits_1(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real factory again: a missing key is one line on stderr, not a traceback."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = invoke("review", str(tmp_package_dir), "--out", str(tmp_path / "run"))

    assert result.exit_code == 1
    assert "api_key" in result.stderr
    assert result.stdout == ""


# --- what the environment contributes, set deliberately --------------------------


def test_review_takes_the_openai_key_from_the_environment_and_records_its_source(
    tmp_package_dir: Path,
    tmp_path: Path,
    fake_provider: Callable[..., list[RecordingProvider]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-015: the key the run used is resolved here, recorded as `env`, and never written.

    The provider environment is empty for every test in this module, so this is the only
    place `key_source == "env"` can come from - and the session must say so without saying
    what the key was.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")
    built = fake_provider()
    out = tmp_path / "run"

    result = invoke("review", str(tmp_package_dir), "--out", str(out))

    assert result.exit_code == 0, result.stdout + result.stderr
    settings = built[0].settings
    assert settings.key_source == "env"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "sk-from-the-environment"
    session_text = (out / "session.json").read_text(encoding="utf-8")
    assert json.loads(session_text)["provider_info"]["key_source"] == "env"
    assert "sk-from-the-environment" not in session_text


def test_review_takes_the_openai_base_url_from_the_environment(
    tmp_package_dir: Path,
    tmp_path: Path,
    fake_provider: Callable[..., list[RecordingProvider]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`OPENAI_BASE_URL` is how a seat behind a gateway reaches OpenAI at all."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-gateway")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.internal/v1")
    built = fake_provider()

    result = invoke("review", str(tmp_package_dir), "--out", str(tmp_path / "run"))

    assert result.exit_code == 0, result.stdout + result.stderr
    assert built[0].settings.base_url == "https://gateway.internal/v1"


def test_review_on_gemini_resolves_enterprise_from_the_environment(
    tmp_package_dir: Path,
    tmp_path: Path,
    fake_provider: Callable[..., list[RecordingProvider]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switch plus a project plus a location routes the run at Gemini Enterprise."""
    monkeypatch.setenv("GOOGLE_API_KEY", "g-from-the-environment")
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "acme-cad")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    built = fake_provider()

    result = invoke(
        "review", str(tmp_package_dir), "--out", str(tmp_path / "run"), "--provider", "gemini"
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    settings = built[0].settings
    assert settings.enterprise == GeminiEnterprise(project="acme-cad", location="us-central1")
    assert settings.key_source == "env"


def test_a_provider_error_that_echoes_the_key_is_redacted_in_the_event_stream(
    tmp_package_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-015: the run folder cannot receive the key, whatever raised.

    Each adapter redacts the errors it wraps, but a failure outside the classes it maps -
    an SDK-internal error, a transport error, a client constructed with a bad argument -
    reaches the runner unwrapped, and the runner writes `str(exc)` into `events.jsonl`.
    So the masking has to be the runner's too, not each adapter's alone.
    """
    key = "sk-echoed-back-in-the-error"
    monkeypatch.setenv("OPENAI_API_KEY", key)

    class LeakingProvider(FakeProvider):
        """An adapter whose failure quotes the request it failed on, key included."""

        def run(self, **kwargs: Any) -> Any:
            raise RuntimeError(f"401 Unauthorized: api_key={key} was rejected")

    monkeypatch.setattr(
        cli,
        "provider_factory",
        lambda settings, efficiency=None: LeakingProvider(script=SCRIPT, model=settings.model),
    )
    out = tmp_path / "run"

    result = invoke("review", str(tmp_package_dir), "--out", str(out))

    assert isinstance(result.exception, RuntimeError)
    events = (out / "events.jsonl").read_text(encoding="utf-8")
    assert key not in events
    assert MASK in events
    error = next(
        json.loads(line) for line in events.splitlines() if json.loads(line)["type"] == "error"
    )
    assert error["body"]["message"] == f"401 Unauthorized: api_key={MASK} was rejected"


def test_the_key_is_masked_out_of_log_records_while_the_review_runs(
    tmp_package_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FR-015 again, for the other half: an SDK that logs the request it is about to make.

    `openai`, `google_genai` and `httpx` log through their own loggers, which a filter on
    the root logger never sees, so the run installs a record factory instead. It is taken
    off again when the command ends - a redactor still masking a key the next command does
    not use is dead weight - which is what the second assertion pins down.
    """
    key = "sk-written-to-a-log-line"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    sdk_logger = logging.getLogger("openai")

    class LoggingProvider(FakeProvider):
        def run(self, **kwargs: Any) -> Any:
            sdk_logger.error("POST /v1/responses with api_key=%s", key)
            return super().run(**kwargs)

    monkeypatch.setattr(
        cli,
        "provider_factory",
        lambda settings, efficiency=None: LoggingProvider(script=SCRIPT, model=settings.model),
    )

    with caplog.at_level(logging.ERROR, logger="openai"):
        result = invoke("review", str(tmp_package_dir), "--out", str(tmp_path / "run"))
        assert result.exit_code == 0, result.stdout + result.stderr
        during = caplog.text
        sdk_logger.error("POST /v1/responses with api_key=%s", key)
        after = caplog.text[len(during) :]

    assert key not in during
    assert f"api_key={MASK}" in during
    assert key in after


def test_review_with_a_half_configured_enterprise_environment_exits_1(
    tmp_package_dir: Path,
    tmp_path: Path,
    fake_provider: Callable[..., list[RecordingProvider]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And names the switch that is actually set, not the one it would have preferred."""
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    fake_provider()

    result = invoke(
        "review", str(tmp_package_dir), "--out", str(tmp_path / "run"), "--provider", "gemini"
    )

    assert result.exit_code == 1
    assert "GOOGLE_GENAI_USE_VERTEXAI" in result.stderr
    assert result.stdout == ""


def test_review_passes_the_provider_model_and_effort_through(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    built = fake_provider()
    out = tmp_path / "run"

    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(out),
        "--provider",
        "fake",
        "--model",
        "gpt-5.5",
        "--effort",
        "medium",
        "--max-steps",
        "5",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    settings = built[0].settings
    assert settings.provider is ProviderName.FAKE
    assert settings.model == "gpt-5.5"
    assert settings.effort == "medium"
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert session["model"] == "gpt-5.5"
    assert session["provider_info"]["effort_mapping"]["requested"] == "medium"


def test_review_hands_the_levers_it_resolved_to_the_adapter_factory(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    """Lever 6 is decided when the adapter is built, so `--lever` has to reach the factory.

    Every other lever is read at `start_review` off `session.efficiency`, which the
    provenance tests already pin; this one is an OpenAI request field set in the
    constructor, and the factory is the only place that can set it.
    """
    built = fake_provider()

    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(tmp_path / "run"),
        "--provider",
        "fake",
        "--lever",
        "parallel_tool_calls",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert built[0].efficiency == EfficiencySettings(parallel_tool_calls=True)


def test_review_without_a_lever_hands_the_factory_settings_with_every_lever_off(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    built = fake_provider()

    result = invoke(
        "review", str(tmp_package_dir), "--out", str(tmp_path / "run"), "--provider", "fake"
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert built[0].efficiency == EfficiencySettings()


def test_review_with_an_unknown_provider_is_a_usage_error(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    """`anthropic` is not a spelling the CLI accepts any more (FR-026)."""
    result = invoke(
        "review", str(tmp_package_dir), "--out", str(tmp_path / "run"), "--provider", "anthropic"
    )

    assert result.exit_code == 2


def test_review_fail_tool_keeps_the_run_alive_and_records_the_failure(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    fake_provider()
    out = tmp_path / "run"

    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(out),
        "--fail-tool",
        "get_package_summary",
    )

    assert result.exit_code == 0
    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    failed = session["coverage"]["failed"]
    assert [item["check"] for item in failed] == ["tool.get_package_summary"]


def test_review_with_an_unknown_fail_tool_exits_1(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    fake_provider()

    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(tmp_path / "run"),
        "--fail-tool",
        "list_everything",
    )

    assert result.exit_code == 1
    assert "fail_tool" in result.stderr


def test_review_with_an_unknown_effort_is_a_usage_error(
    tmp_package_dir: Path, tmp_path: Path
) -> None:
    result = invoke(
        "review", str(tmp_package_dir), "--out", str(tmp_path / "run"), "--effort", "turbo"
    )

    assert result.exit_code == 2


def test_review_with_the_bridge_adds_the_bridge_tools(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    """`--bridge` wires a client and the three bridge tools; nothing opens the pipe."""
    built = fake_provider()

    result = invoke("review", str(tmp_package_dir), "--out", str(tmp_path / "run"), "--bridge")

    assert result.exit_code == 0, result.stdout + result.stderr
    names = set(built[0].tool_names)
    assert {"bridge_capture", "bridge_measure", "bridge_interference"} <= names


def test_review_without_the_bridge_has_no_bridge_tools(
    tmp_package_dir: Path, tmp_path: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    built = fake_provider()

    result = invoke("review", str(tmp_package_dir), "--out", str(tmp_path / "run"))

    assert result.exit_code == 0
    names = set(built[0].tool_names)
    assert not names & {"bridge_capture", "bridge_measure", "bridge_interference"}


# --- report ----------------------------------------------------------------------


def test_report_rerenders_the_markdown(run_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "again.md"

    body = payload(
        invoke("report", str(run_dir / "session.json"), "--out", str(target), "--json")
    )

    assert target.is_file()
    assert "F-001" in target.read_text(encoding="utf-8")
    assert body["report_file"] == str(target)


def test_report_defaults_to_report_md_beside_the_session(run_dir: Path) -> None:
    (run_dir / "report.md").unlink()

    result = invoke("report", str(run_dir / "session.json"))

    assert result.exit_code == 0
    assert (run_dir / "report.md").is_file()


def test_report_on_a_missing_session_exits_1(tmp_path: Path) -> None:
    result = invoke("report", str(tmp_path / "nowhere.json"))

    assert result.exit_code == 1


# --- disposition -----------------------------------------------------------------


def test_disposition_records_the_decision_and_rerenders(run_dir: Path) -> None:
    body = payload(
        invoke(
            "disposition",
            str(run_dir),
            "F-001",
            "--decision",
            "accepted",
            "--note",
            "reviewed, ok",
            "--by",
            "engineer",
            "--json",
        )
    )

    session = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    disposition = session["findings"][0]["disposition"]
    assert disposition["decision"] == "accepted"
    assert disposition["note"] == "reviewed, ok"
    assert disposition["by"] == "engineer"
    assert "accepted" in (run_dir / "report.md").read_text(encoding="utf-8")
    assert body["decision"] == "accepted"


def test_a_terminal_disposition_cannot_be_changed(run_dir: Path) -> None:
    first = invoke("disposition", str(run_dir), "F-001", "--decision", "accepted")
    assert first.exit_code == 0

    second = invoke("disposition", str(run_dir), "F-001", "--decision", "rejected")

    assert second.exit_code == 1
    assert "terminal" in second.stderr


def test_disposition_on_an_unknown_finding_exits_1(run_dir: Path) -> None:
    result = invoke("disposition", str(run_dir), "F-404", "--decision", "accepted")

    assert result.exit_code == 1
    assert "F-404" in result.stderr


def test_disposition_with_an_unknown_decision_is_a_usage_error(run_dir: Path) -> None:
    result = invoke("disposition", str(run_dir), "F-001", "--decision", "maybe")

    assert result.exit_code == 2


# --- check fit / stack -----------------------------------------------------------


def test_check_fit_prints_the_finding(fit_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "fit",
            "--package",
            str(fit_package_dir),
            "--bore",
            "doc:3:Sheet1:DIM-BORE",
            "--shaft",
            "doc:3:Sheet1:DIM-SHAFT",
            "--json",
        )
    )

    finding = body["finding"]
    assert finding["check"] == "fit.size_only"
    assert finding["calculation"]["result"]["min_clearance_mm"] == 0.009


def test_check_fit_human_output_names_the_check_and_the_status(fit_package_dir: Path) -> None:
    result = invoke(
        "check",
        "fit",
        "--package",
        str(fit_package_dir),
        "--bore",
        "doc:3:Sheet1:DIM-BORE",
        "--shaft",
        "doc:3:Sheet1:DIM-SHAFT",
    )

    assert result.exit_code == 0
    assert "fit.size_only" in result.stdout
    assert "checked_within_scope" in result.stdout


def test_check_fit_with_an_unknown_reference_exits_1(fit_package_dir: Path) -> None:
    result = invoke(
        "check",
        "fit",
        "--package",
        str(fit_package_dir),
        "--bore",
        "doc:3:Sheet1:DIM-NOWHERE",
        "--shaft",
        "doc:3:Sheet1:DIM-SHAFT",
    )

    assert result.exit_code == 1
    assert "no drawing dimension at" in result.stderr


def test_check_fit_with_a_malformed_reference_is_a_usage_error(fit_package_dir: Path) -> None:
    result = invoke(
        "check",
        "fit",
        "--package",
        str(fit_package_dir),
        "--bore",
        "DIM-BORE",
        "--shaft",
        "doc:3:Sheet1:DIM-SHAFT",
    )

    assert result.exit_code == 2


def test_check_stack_sums_the_dimensions_against_the_target(fit_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "stack",
            "--package",
            str(fit_package_dir),
            "--dims",
            "doc:3:Sheet1:DIM-A:+1",
            "--dims",
            "doc:3:Sheet1:DIM-B:-1",
            "--target",
            "doc:3:Sheet1:DIM-GAP",
            "--json",
        )
    )

    finding = body["finding"]
    assert finding["check"] == "stack.worst_case"
    assert finding["status"] == "demonstrated"
    assert finding["calculation"]["result"]["violates_target"] is True


def test_check_stack_without_a_target_reports_the_band(fit_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "stack",
            "--package",
            str(fit_package_dir),
            "--dims",
            "doc:3:Sheet1:DIM-A:+1",
            "--dims",
            "doc:3:Sheet1:DIM-B:-1",
            "--json",
        )
    )

    assert body["finding"]["status"] == "checked_within_scope"


def test_check_stack_with_a_bad_sign_is_a_usage_error(fit_package_dir: Path) -> None:
    result = invoke(
        "check",
        "stack",
        "--package",
        str(fit_package_dir),
        "--dims",
        "doc:3:Sheet1:DIM-A:+2",
    )

    assert result.exit_code == 2


def test_check_stack_on_a_missing_package_exits_1(tmp_path: Path) -> None:
    result = invoke(
        "check",
        "stack",
        "--package",
        str(tmp_path / "nowhere"),
        "--dims",
        "doc:3:Sheet1:DIM-A:+1",
    )

    assert result.exit_code == 1


# --- check fastener | alignment --------------------------------------------------


def test_check_fastener_prints_every_finding_of_the_joint(joint_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "fastener",
            "--package",
            str(joint_package_dir),
            "--fastener",
            "fst:screw",
            "--hole",
            "hole:tapped",
            "--clamped",
            "cmp:0003",
            "--json",
        )
    )

    checks = [finding["check"] for finding in body["findings"]]
    assert checks == [
        "fastener.bottoming",
        "fastener.engagement",
        "fastener.thread_match",
        "fastener.head_clearance",
    ]
    assert body["clamped"][0]["thickness"]["value"] == 8.0


def test_check_fastener_human_output_names_each_check(joint_package_dir: Path) -> None:
    result = invoke(
        "check",
        "fastener",
        "--package",
        str(joint_package_dir),
        "--fastener",
        "fst:screw",
        "--hole",
        "hole:tapped",
        "--clamped",
        "cmp:0003",
    )

    assert result.exit_code == 0
    assert "fastener.bottoming" in result.stdout
    assert "fastener.engagement" in result.stdout


def test_check_fastener_takes_several_clamped_components(joint_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "fastener",
            "--package",
            str(joint_package_dir),
            "--fastener",
            "fst:screw",
            "--hole",
            "hole:tapped",
            "--clamped",
            "cmp:0003,cmp:0006",
            "--json",
        )
    )

    assert [layer["component_id"] for layer in body["clamped"]] == ["cmp:0003", "cmp:0006"]


def test_check_fastener_reports_an_out_of_scope_joint(joint_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "fastener",
            "--package",
            str(joint_package_dir),
            "--fastener",
            "fst:pin",
            "--hole",
            "hole:tapped",
            "--clamped",
            "cmp:0003",
            "--json",
        )
    )

    assert body["status"] == "out_of_scope"
    assert "pin" in body["coverage_item"]["reason"]


def test_check_fastener_with_an_unknown_id_exits_1(joint_package_dir: Path) -> None:
    result = invoke(
        "check",
        "fastener",
        "--package",
        str(joint_package_dir),
        "--fastener",
        "fst:nope",
        "--hole",
        "hole:tapped",
        "--clamped",
        "cmp:0003",
    )

    assert result.exit_code == 1
    assert "fst:nope" in result.stderr


def test_check_alignment_against_a_drawn_tolerance(joint_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "alignment",
            "--package",
            str(joint_package_dir),
            "--hole-a",
            "hole:tapped",
            "--hole-b",
            "hole:far",
            "--tolerance",
            "doc:9:Sheet1:dim-1-1",
            "--json",
        )
    )

    finding = body["finding"]
    assert finding["check"] == "hole.coaxiality"
    assert finding["status"] == "demonstrated"
    assert finding["calculation"]["result"]["tolerance_mm"] == 0.2


def test_check_alignment_without_a_tolerance_is_unresolved(joint_package_dir: Path) -> None:
    body = payload(
        invoke(
            "check",
            "alignment",
            "--package",
            str(joint_package_dir),
            "--hole-a",
            "hole:tapped",
            "--hole-b",
            "hole:far",
            "--json",
        )
    )

    assert body["finding"]["status"] == "unresolved"


def test_check_alignment_with_a_malformed_tolerance_is_a_usage_error(
    joint_package_dir: Path,
) -> None:
    result = invoke(
        "check",
        "alignment",
        "--package",
        str(joint_package_dir),
        "--hole-a",
        "hole:tapped",
        "--hole-b",
        "hole:far",
        "--tolerance",
        "dim-1-1",
    )

    assert result.exit_code == 2


def test_check_alignment_with_an_unknown_hole_exits_1(joint_package_dir: Path) -> None:
    result = invoke(
        "check",
        "alignment",
        "--package",
        str(joint_package_dir),
        "--hole-a",
        "hole:tapped",
        "--hole-b",
        "hole:nope",
    )

    assert result.exit_code == 1
    assert "hole:nope" in result.stderr


# --- check interference ----------------------------------------------------------


INTERFERENCE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "golden" / "fixtures" / "bracket-assy-interference"
)
"""The golden interference package: three conditions, one grouped over six pairs, one
excepted, one truncated. Every test below runs on a copy, so nothing can write beside it."""


@pytest.fixture
def interference_package_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "bracket-assy-interference"
    shutil.copytree(INTERFERENCE_FIXTURE, directory)
    return directory


def test_check_interference_json_is_the_library_case(interference_package_dir: Path) -> None:
    body = payload(
        invoke("check", "interference", "--package", str(interference_package_dir), "--json")
    )

    assert body == interference_case(interference_package_dir)


def test_check_interference_json_grades_every_condition(interference_package_dir: Path) -> None:
    body = payload(
        invoke("check", "interference", "--package", str(interference_package_dir), "--json")
    )

    assert [(group["group_key"], group["result"]["status"]) for group in body["groups"]] == [
        ("cmp:0001|pat:screws", "demonstrated"),
        ("cmp:0002|cmp:0003", "checked_within_scope"),
        ("cmp:0001|cmp:0005", "unresolved"),
    ]
    assert body["groups"][0]["member_interference_ids"] == [
        "int:001",
        "int:002",
        "int:003",
        "int:004",
        "int:005",
        "int:006",
    ]
    assert body["exceptions"] == [
        {"id": "EX-001", "check": "interference.static", "status": "active"}
    ]
    assert [item["scope"]["pairs"] for item in body["unresolved_coverage"]] == [
        [["cmp:0001", "cmp:0005"]]
    ]


def test_check_interference_human_output_names_each_group_and_its_status(
    interference_package_dir: Path,
) -> None:
    result = invoke("check", "interference", "--package", str(interference_package_dir))

    assert result.exit_code == 0
    assert "3 interference condition(s)" in result.stdout
    assert "cmp:0001|pat:screws (Default): detection computed, 6 pair(s)" in result.stdout
    assert "interference.static: demonstrated (high)" in result.stdout
    assert "interference.static: checked_within_scope (info)" in result.stdout
    assert "interference.static: unresolved (medium)" in result.stdout


def test_check_interference_human_output_lists_exceptions_and_unresolved_coverage(
    interference_package_dir: Path,
) -> None:
    result = invoke("check", "interference", "--package", str(interference_package_dir))

    assert result.exit_code == 0
    assert "1 exception(s) after refresh" in result.stdout
    assert "EX-001 active interference.static" in result.stdout
    assert "unresolved coverage: 1 item(s)" in result.stdout
    assert "interference detection truncated for cmp:0001+cmp:0005" in result.stdout
    assert "detection stopped after 7 pairs (--truncate-after 7)" in result.stdout


def test_check_interference_leaves_the_exceptions_file_byte_for_byte(
    interference_package_dir: Path,
) -> None:
    exceptions_file = interference_package_dir / "exceptions.json"
    before = exceptions_file.read_bytes()

    result = invoke("check", "interference", "--package", str(interference_package_dir))

    assert result.exit_code == 0
    assert exceptions_file.read_bytes() == before


def test_check_interference_reports_a_moved_exception_without_writing_it(
    interference_package_dir: Path,
) -> None:
    """`refresh` flips a stale exception in memory; the command must not persist that."""
    exceptions_file = interference_package_dir / "exceptions.json"
    stored = json.loads(exceptions_file.read_text(encoding="utf-8"))
    stored["exceptions"][0]["configuration"] = "Alternate"
    exceptions_file.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    before = exceptions_file.read_bytes()

    body = payload(
        invoke("check", "interference", "--package", str(interference_package_dir), "--json")
    )

    assert body["exceptions"] == [
        {"id": "EX-001", "check": "interference.static", "status": "needs_review"}
    ]
    assert body["groups"][1]["result"]["status"] == "demonstrated"
    assert exceptions_file.read_bytes() == before


def test_check_interference_on_a_package_with_no_exceptions_file(
    interference_package_dir: Path,
) -> None:
    """A fresh dump carries no `exceptions.json`; an absent file silences nothing."""
    (interference_package_dir / "exceptions.json").unlink()

    result = invoke("check", "interference", "--package", str(interference_package_dir))
    body = payload(
        invoke("check", "interference", "--package", str(interference_package_dir), "--json")
    )

    assert result.exit_code == 0
    assert "0 exception(s) after refresh" in result.stdout
    assert body["exceptions"] == []
    assert body["groups"][1]["result"]["status"] == "demonstrated"


def test_check_interference_on_a_missing_package_exits_1(tmp_path: Path) -> None:
    result = invoke("check", "interference", "--package", str(tmp_path / "nowhere"))

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")


def test_check_interference_with_a_corrupt_exceptions_file_exits_1(
    interference_package_dir: Path,
) -> None:
    (interference_package_dir / "exceptions.json").write_text("{ not json", encoding="utf-8")

    result = invoke("check", "interference", "--package", str(interference_package_dir))

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert result.stdout == ""


# --- check rms -------------------------------------------------------------------

RMS_FRAME = "doc:2"
"""The compliant part of the `check rms` package."""

RMS_COVER = "doc:3"
"""The part that fails `rms.intent.every_feature_described` and, with an equation manager
that holds nothing, `rms.params.global_variables_present`."""

RMS_GLOBALS_RULE = "rms.params.global_variables_present"

RMS_ASSEMBLY = "doc:1"
"""The root assembly document: the only document the assembly family grades."""

RMS_SUBASSEMBLY = "doc:5"
"""The subassembly the assembly family does not reach, named in its coverage item."""


def check_rms(package_dir: str, *args: str, out: Path) -> Any:
    """`swreview check rms` over `package_dir`, writing its run folder into `out`.

    `--out` is required and is spelled here once rather than in thirty invocations: every
    case below grades a package the command must not write into, which is the whole point
    of the option, so a case that passed something else would be saying something this
    helper's absence would hide. The three cases that are *about* `--out` - it is
    required, what it writes, and which run root it implies - call `invoke` directly.
    """
    return invoke("check", "rms", "--package", package_dir, "--out", str(out), *args)


@pytest.fixture
def rms_out(tmp_path: Path) -> Path:
    """The run folder a check writes into: under its own run root, never the package.

    Its own root, because the run root the command derives from `--out` is that folder's
    parent: a run folder dropped beside the package would make the package a sibling run
    of itself, and the carry-forward would read it as an earlier run of this design.
    """
    return tmp_path / "runs" / "20260916-101532-check"


@pytest.fixture
def rms_dir(tmp_path: Path) -> Path:
    """A written package with one compliant part, one failing part, and an assembly."""
    from tests.support.features import (
        AssemblySpec,
        PartSpec,
        equation,
        feature,
        folder,
        rms_package,
    )

    package = rms_package(
        parts=[
            PartSpec(
                document_id=RMS_FRAME,
                name="frame",
                equations=(
                    equation('"thickness" = 3mm', is_global=True, value=0.003),
                    equation('"D1@Sketch1" = "thickness" * 2', value=0.006),
                ),
                features=(
                    folder("1-Ref", feature("Plane1", "RefPlane")),
                    folder("2-Construction", feature("Surface1", "SurfaceExtrude")),
                    folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
                    folder("4-Detail", feature("Hole1", "HoleWzd")),
                    folder("5-Modify", feature("Draft1", "Draft")),
                    folder("6-Quarantine", feature("Chamfer1", "Chamfer")),
                ),
            ),
            PartSpec(
                document_id=RMS_COVER,
                name="cover",
                features=(
                    folder("3-Core", feature("Boss-Extrude2", "Extrusion", description="")),
                    folder("4-Detail", feature("Hole2", "HoleWzd")),
                ),
            ),
        ],
        assembly=AssemblySpec(document_id=RMS_ASSEMBLY, name="cover-assy"),
    )
    directory = tmp_path / "rms-package"
    save_package(package, directory)
    return directory


@pytest.fixture
def rms_assembly_dir(tmp_path: Path) -> Path:
    """A written package whose root assembly breaks two of the four assembly rules.

    `frame-1` is the first child of the root instance and is neither fixed nor fully
    constrained, and the one mate sits on faces. The parts carry no feature trees and no
    equations on purpose: a part or equation rule that ran here would have nothing to
    read, so its coverage showing up is proof that `--scope assembly` graded more than it
    was asked to.
    """
    from tests.support.features import (
        AssemblySpec,
        InstanceSpec,
        MateSpec,
        PartSpec,
        SubassemblySpec,
        rms_package,
    )

    under_defined = 2  # swConstrainedStatus_e.swUnderConstrained
    face = "swSelFACES"
    package = rms_package(
        parts=[
            PartSpec(
                document_id=RMS_FRAME,
                name="frame",
                instances=(InstanceSpec("frame-1", constrained_status_raw=under_defined),),
            ),
            PartSpec(
                document_id=RMS_COVER,
                name="cover",
                instances=(InstanceSpec("cover-1", is_fixed=True),),
            ),
        ],
        assembly=AssemblySpec(
            document_id=RMS_ASSEMBLY,
            name="cover-assy",
            mates=(MateSpec(entities=(("frame-1", face), ("cover-1", face))),),
            subassembly=SubassemblySpec(document_id=RMS_SUBASSEMBLY, name="gearbox"),
        ),
    )
    directory = tmp_path / "rms-assembly-package"
    save_package(package, directory)
    return directory


def test_check_rms_grades_every_part_document_by_default(rms_dir: Path, rms_out: Path) -> None:
    body = payload(check_rms(str(rms_dir), "--json", out=rms_out))

    assert body["scope"] == "all"
    assert body["documents"] == [RMS_FRAME, RMS_COVER]
    assert "rms.intent.every_feature_described" in [
        finding["check"] for finding in body["findings"]
    ]


def test_check_rms_document_limits_the_run_to_that_document(rms_dir: Path, rms_out: Path) -> None:
    body = payload(
        check_rms(str(rms_dir), "--document", RMS_FRAME, "--json", out=rms_out)
    )

    assert body["documents"] == [RMS_FRAME]
    assert body["findings"] == []


def test_check_rms_document_is_repeatable(rms_dir: Path, rms_out: Path) -> None:
    """`--document` selects part documents, in the caller's order, and narrows only them.

    The default scope still runs the assembly family, which has no document to narrow -
    the root assembly document is the only one whose mates are extracted - so it is the
    one other document the coverage names.
    """
    body = payload(
        check_rms(
            str(rms_dir),
            "--document",
            RMS_COVER,
            "--document",
            RMS_FRAME,
            "--json",
            out=rms_out,
        )
    )

    assert body["documents"] == [RMS_COVER, RMS_FRAME]
    assert body["assembly_document"] == RMS_ASSEMBLY
    assert {
        document for item in body["coverage"] for document in item["scope"]["document_ids"]
    } == {RMS_FRAME, RMS_COVER, RMS_ASSEMBLY}


def test_check_rms_reports_coverage_as_well_as_findings(rms_dir: Path, rms_out: Path) -> None:
    body = payload(check_rms(str(rms_dir), "--json", out=rms_out))

    buckets = {item["bucket"] for item in body["coverage"]}
    assert {"checked", "unresolved", "out_of_scope"} <= buckets
    assert "modeling.resilience" in [item["check"] for item in body["coverage"]]


def test_check_rms_human_output_names_the_findings_and_the_coverage(
    rms_dir: Path, rms_out: Path
) -> None:
    result = check_rms(str(rms_dir), out=rms_out)

    assert result.exit_code == 0
    assert "2 part document(s)" in result.stdout
    assert "rms.intent.every_feature_described: demonstrated (medium)" in result.stdout
    assert "coverage: " in result.stdout


def test_check_rms_scope_part_runs_the_part_rules(rms_dir: Path, rms_out: Path) -> None:
    body = payload(
        check_rms(str(rms_dir), "--scope", "part", "--json", out=rms_out)
    )

    assert body["scope"] == "part"
    assert body["unavailable_scopes"] == []
    assert body["findings"]


def test_check_rms_scope_assembly_runs_the_assembly_rules(
    rms_assembly_dir: Path,
    rms_out: Path,
) -> None:
    body = payload(
        check_rms(str(rms_assembly_dir), "--scope", "assembly", "--json", out=rms_out)
    )

    assert body["scope"] == "assembly"
    assert body["unavailable_scopes"] == []
    assert body["assembly_document"] == RMS_ASSEMBLY
    assert {finding["check"] for finding in body["findings"]} == {
        "rms.assembly.first_component_fixed",
        "rms.assembly.mates_to_reference_geometry",
    }


def test_check_rms_scope_assembly_grades_no_part_document(
    rms_assembly_dir: Path, rms_out: Path
) -> None:
    """`--document` narrows the part families; the assembly family has one subject document.

    So an assembly-only run reports no part document and writes no part-scope coverage -
    the two families are separate, and a run that had quietly graded the trees as well
    would make `--scope` mean nothing.
    """
    body = payload(
        check_rms(str(rms_assembly_dir), "--scope", "assembly", "--json", out=rms_out)
    )

    assert body["documents"] == []
    checks = {item["check"] for item in body["coverage"]}
    assert "rms.intent.every_feature_described" not in checks
    assert "rms.assembly.mate_chain_depth" in checks


def test_check_rms_scope_assembly_human_output_names_the_root_assembly_document(
    rms_assembly_dir: Path,
    rms_out: Path,
) -> None:
    result = check_rms(str(rms_assembly_dir), "--scope", "assembly", out=rms_out)

    assert result.exit_code == 0
    assert f"root assembly document: {RMS_ASSEMBLY}" in result.stdout
    assert "rms.assembly.first_component_fixed: demonstrated (medium)" in result.stdout
    assert "not yet available in this build" not in result.stdout


def test_check_rms_scope_assembly_names_the_subassembly_it_did_not_reach(
    rms_assembly_dir: Path,
    rms_out: Path,
) -> None:
    body = payload(
        check_rms(str(rms_assembly_dir), "--scope", "assembly", "--json", out=rms_out)
    )

    subassemblies = [
        item for item in body["coverage"] if item["check"] == "rms.assembly.subassemblies"
    ]
    assert len(subassemblies) == 1
    assert subassemblies[0]["bucket"] == "unresolved"
    assert subassemblies[0]["scope"]["document_ids"] == [RMS_SUBASSEMBLY]


@pytest.fixture
def rms_part_only_dir(tmp_path: Path) -> Path:
    """A written package with no assembly document at all.

    `design.root_assembly_document_id` then names the part the dump was rooted at, which
    is what a part-only dump writes. `--scope all` still runs the assembly family over it,
    so this is what keeps the default scope from claiming a part is the root assembly.
    """
    from tests.support.features import PartSpec, feature, folder, rms_package

    package = rms_package(
        parts=[
            PartSpec(
                document_id=RMS_FRAME,
                name="frame",
                features=(folder("3-Core", feature("Boss-Extrude1", "Extrusion")),),
            )
        ]
    )
    directory = tmp_path / "rms-part-only-package"
    save_package(package, directory)
    return directory


def test_check_rms_scope_all_on_a_part_only_package_names_no_root_assembly(
    rms_part_only_dir: Path,
    rms_out: Path,
) -> None:
    body = payload(check_rms(str(rms_part_only_dir), "--json", out=rms_out))

    assert body["scope"] == "all"
    assert body["assembly_document"] is None
    assert body["documents"] == [RMS_FRAME]
    unresolved = {
        item["check"]
        for item in body["coverage"]
        if item["bucket"] == "unresolved"
    }
    assert "rms.assembly.mates_to_reference_geometry" in unresolved
    assert "rms.assembly.first_component_fixed" in unresolved


def test_check_rms_scope_all_on_a_part_only_package_still_exits_zero(
    rms_part_only_dir: Path,
    rms_out: Path,
) -> None:
    """A part-only dump is a package, not a bad argument: the run reports what it could
    not grade instead of failing."""
    result = check_rms(str(rms_part_only_dir), out=rms_out)

    assert result.exit_code == 0
    assert "root assembly document:" not in result.stdout


def test_check_rms_scope_equations_runs_the_equation_rules(rms_dir: Path, rms_out: Path) -> None:
    body = payload(
        check_rms(str(rms_dir), "--scope", "equations", "--json", out=rms_out)
    )

    assert body["scope"] == "equations"
    assert body["unavailable_scopes"] == []
    assert body["documents"] == [RMS_FRAME, RMS_COVER]
    assert [finding["check"] for finding in body["findings"]] == [
        RMS_GLOBALS_RULE,
        "rms.params.dimensions_driven_by_equations",
    ]


def test_check_rms_scope_equations_does_not_run_the_part_rules(
    rms_dir: Path, rms_out: Path
) -> None:
    """The scopes are separate: `--scope equations` grades the managers, not the trees."""
    body = payload(
        check_rms(str(rms_dir), "--scope", "equations", "--json", out=rms_out)
    )

    checks = {item["check"] for item in body["coverage"]}
    assert "rms.intent.every_feature_described" not in checks
    assert RMS_GLOBALS_RULE in checks


def test_check_rms_scope_equations_honours_document(rms_dir: Path, rms_out: Path) -> None:
    body = payload(
        check_rms(
            str(rms_dir),
            "--scope",
            "equations",
            "--document",
            RMS_FRAME,
            "--json",
            out=rms_out,
        )
    )

    assert body["documents"] == [RMS_FRAME]
    assert body["findings"] == []


def test_check_rms_scope_all_runs_every_family(rms_dir: Path, rms_out: Path) -> None:
    result = check_rms(str(rms_dir), out=rms_out)
    body = payload(check_rms(str(rms_dir), "--json", out=rms_out))

    assert result.exit_code == 0
    assert body["unavailable_scopes"] == []
    assert body["documents"] == [RMS_FRAME, RMS_COVER]
    assert body["assembly_document"] == RMS_ASSEMBLY
    assert {"rms.intent.every_feature_described", RMS_GLOBALS_RULE} <= {
        finding["check"] for finding in body["findings"]
    }
    assert "rms.assembly.mate_chain_depth" in {item["check"] for item in body["coverage"]}
    assert "not yet available in this build" not in result.stdout


def test_check_rms_scope_part_reports_no_assembly_document(rms_dir: Path, rms_out: Path) -> None:
    """The key says what was graded, so a family that did not run leaves it null."""
    body = payload(
        check_rms(str(rms_dir), "--scope", "part", "--json", out=rms_out)
    )

    assert body["assembly_document"] is None


def test_check_rms_reads_the_exceptions_file_beside_the_package(
    rms_dir: Path, rms_out: Path
) -> None:
    """An accepted exception waives the failing rule, exactly as it does for the tool."""
    from datetime import UTC, datetime

    from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
    from swreview.ir.loader import load_package
    from tests.unit.test_tools_rms_checks import AcceptedFinding

    package = load_package(rms_dir).package
    store = ExceptionStore(rms_dir / EXCEPTIONS_FILE_NAME)
    store.accept(
        AcceptedFinding(
            check="rms.intent.every_feature_described",
            component_ids=["cmp:0003"],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note="legacy tree, accepted by the owner",
        at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store.save()

    body = payload(check_rms(str(rms_dir), "--json", out=rms_out))

    described = next(
        finding
        for finding in body["findings"]
        if finding["check"] == "rms.intent.every_feature_described"
    )
    assert described["status"] == "checked_within_scope"
    assert described["exception_id"] == "EX-001"


def test_check_rms_leaves_the_exceptions_file_byte_for_byte(rms_dir: Path, rms_out: Path) -> None:
    exceptions_file = rms_dir / "exceptions.json"
    exceptions_file.write_text('{"exceptions": []}\n', encoding="utf-8")
    before = exceptions_file.read_bytes()

    assert check_rms(str(rms_dir), out=rms_out).exit_code == 0
    assert exceptions_file.read_bytes() == before


def test_check_rms_with_an_unknown_document_exits_1(rms_dir: Path, rms_out: Path) -> None:
    result = check_rms(str(rms_dir), "--document", "doc:99", out=rms_out)

    assert result.exit_code == 1
    assert "doc:99" in result.stderr
    assert result.stdout == ""


def test_check_rms_with_an_assembly_document_exits_1(rms_dir: Path, rms_out: Path) -> None:
    result = check_rms(str(rms_dir), "--document", "doc:1", out=rms_out)

    assert result.exit_code == 1
    assert "doc:1" in result.stderr


def test_check_rms_with_an_unknown_scope_is_a_usage_error(rms_dir: Path, rms_out: Path) -> None:
    assert check_rms(str(rms_dir), "--scope", "drawing", out=rms_out).exit_code == 2


def test_check_rms_on_a_missing_package_exits_1(tmp_path: Path, rms_out: Path) -> None:
    result = check_rms(str(tmp_path / "nowhere"), out=rms_out)

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")


def test_check_rms_reports_a_rule_that_cannot_grade_as_an_error_not_a_traceback(
    tmp_path: Path, rms_out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raise out of the rule layer is exit 1 and one line on stderr, not a crash.

    The command dispatches through `run_rms_check`, which dispatches the check tools
    through the tool registry, so a raise out of the rule layer comes back as an error
    result and `run_rms_check` re-raises it as an `RmsRunError` that `HANDLED_ERRORS`
    covers. It must leave the same one-line `error: ...` on stderr as an unreadable
    package does. Since T057 no package reaches such a raise - the one that did was the
    `rms.detail.individually_suppressible` stub, and `part_tree`'s remaining
    `ValueError`s are about rows the loader cannot produce - so the raise is injected
    where the tool reaches the rule layer rather than built out of a fixture.
    """
    from swreview.tools import rms_checks
    from tests.support.features import AssemblySpec, PartSpec, feature, folder, rms_package

    package = rms_package(
        parts=[
            PartSpec(
                document_id=RMS_FRAME,
                name="frame",
                features=(
                    folder("3-Core", feature("Boss-Extrude1", "Extrusion")),
                    folder("4-Detail", feature("Hole1", "HoleWzd")),
                ),
            )
        ],
        assembly=AssemblySpec(document_id="doc:1", name="cover-assy"),
    )
    directory = tmp_path / "rms-raising-rule"
    save_package(package, directory)

    def raising(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("the shipped type table names 5 groups; the method has 6")

    monkeypatch.setattr(rms_checks, "run_part_checks", raising)

    result = check_rms(str(directory), "--scope", "part", out=rms_out)

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert "the method has 6" in result.stderr
    assert "Traceback" not in result.stderr


RMS_PART_FIXTURE = REPO_ROOT / "reviewer" / "tests" / "golden" / "fixtures" / "rms-part"
"""The golden fixture the command used to write into (docs/pane-findings-2026-09-16.md)."""


def git_status_of(directory: Path) -> str:
    """`git status --short` for one directory of this checkout, skipping when git cannot.

    Skipped rather than failed when git has nothing to say: a source tree unpacked
    without its repository is not a failing regression, it is a tree this test cannot
    ask the question in.
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--short", "--", str(directory)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - no git here
        pytest.skip(f"git cannot be run here: {exc}")
    if proc.returncode != 0:  # pragma: no cover - not a checkout
        pytest.skip(f"git cannot read {REPO_ROOT}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def test_check_rms_without_out_is_a_usage_error(rms_dir: Path) -> None:
    """`--out` is required and not defaulted. A grading command that defaults its write
    target to the package is the one an engineer runs against a golden fixture without
    meaning to, which is how three untracked files landed in one."""
    result = invoke("check", "rms", "--package", str(rms_dir))

    assert result.exit_code == 2
    assert sorted(item.name for item in rms_dir.iterdir()) == ["package.json"]


def test_check_rms_writes_the_run_folder_into_out_and_not_the_package(
    rms_dir: Path, rms_out: Path
) -> None:
    body = payload(
        invoke("check", "rms", "--package", str(rms_dir), "--out", str(rms_out), "--json")
    )

    assert sorted(item.name for item in rms_out.iterdir()) == [
        "attention.json",
        "check.json",
        "report.md",
        "session.json",
    ]
    assert sorted(item.name for item in rms_dir.iterdir()) == ["package.json"]
    assert body["out_dir"] == str(rms_out)
    assert body["session_file"] == str(rms_out / "session.json")
    assert body["report_file"] == str(rms_out / "report.md")
    assert body["check_file"] == str(rms_out / "check.json")


def test_check_rms_human_output_names_the_run_folder(rms_dir: Path, rms_out: Path) -> None:
    result = check_rms(str(rms_dir), out=rms_out)

    assert result.exit_code == 0
    assert f"session: {rms_out / 'session.json'}" in result.stdout
    assert f"report: {rms_out / 'report.md'}" in result.stdout


def test_check_rms_carries_forward_from_the_runs_beside_out(
    rms_dir: Path, rms_out: Path
) -> None:
    """The run root is `--out`'s parent: a sibling of the run folder that is *its own
    package* and names this design carries its `exceptions.json` into this check (FR-029),
    and nothing is written into the package being graded.

    The sibling is built here as a copy of the package, because that is the shape a
    candidate has to have - `carry_forward` reads a candidate's design from the
    `package.json` in it - and it is the shape the pane's `POST /checks/rms` check folders
    have, a check folder being its own package directory. It is deliberately *not* a shape
    `check rms --out` produces: the test below pins that a run folder this command wrote is
    never a candidate, and the one after it pins what does make a command-line acceptance
    survive."""
    from datetime import UTC, datetime

    from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
    from swreview.ir.loader import load_package
    from tests.unit.test_tools_rms_checks import AcceptedFinding

    earlier = rms_out.parent / "20260915-090000-check"
    shutil.copytree(rms_dir, earlier)
    package = load_package(earlier).package
    store = ExceptionStore(earlier / EXCEPTIONS_FILE_NAME)
    store.accept(
        AcceptedFinding(
            check="rms.intent.every_feature_described",
            component_ids=["cmp:0003"],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note="legacy tree, accepted by the owner",
        at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store.save()

    body = payload(check_rms(str(rms_dir), "--scope", "part", "--json", out=rms_out))

    described = next(
        finding
        for finding in body["findings"]
        if finding["check"] == "rms.intent.every_feature_described"
    )
    assert described["status"] == "checked_within_scope"
    assert described["exception_id"] == "EX-001"
    assert (rms_out / EXCEPTIONS_FILE_NAME).is_file()
    assert not (rms_dir / EXCEPTIONS_FILE_NAME).exists()


def test_check_rms_does_not_carry_forward_from_a_sibling_run_folder_of_its_own(
    rms_dir: Path, rms_out: Path
) -> None:
    """A folder holding only a check run's artifacts is not a carry-forward candidate.

    This is the boundary the test above sits on the far side of, and it is the one this
    command's own run folders fall on: `carry_forward` reads a candidate's design from a
    `package.json`, and `check rms --out` writes `session.json`, `report.md` and
    `check.json` and nothing else. So an `exceptions.json` left in an earlier run folder
    is not carried into the next run however new it is - which is why the contract does
    not promise a CLI run-to-run chain, and why what actually carries an acceptance
    forward is the file beside the package (the test below)."""
    from datetime import UTC, datetime

    from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
    from swreview.ir.loader import load_package
    from tests.unit.test_tools_rms_checks import AcceptedFinding

    earlier = rms_out.parent / "20260915-090000-check"
    assert check_rms(str(rms_dir), "--scope", "part", out=earlier).exit_code == 0
    assert sorted(item.name for item in earlier.iterdir()) == [
        "attention.json",
        "check.json",
        "report.md",
        "session.json",
    ], "a run folder this command wrote is the subject; a package copy is the test above"
    package = load_package(rms_dir).package
    store = ExceptionStore(earlier / EXCEPTIONS_FILE_NAME)
    store.accept(
        AcceptedFinding(
            check="rms.intent.every_feature_described",
            component_ids=["cmp:0003"],
            configuration=package.design.active_configuration,
        ),
        package,
        by="owner",
        note="legacy tree, accepted by the owner",
        at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    store.save()

    body = payload(check_rms(str(rms_dir), "--scope", "part", "--json", out=rms_out))

    described = next(
        finding
        for finding in body["findings"]
        if finding["check"] == "rms.intent.every_feature_described"
    )
    assert described["status"] == "demonstrated"
    assert described["exception_id"] is None
    assert not (rms_out / EXCEPTIONS_FILE_NAME).exists()
    carried = json.loads((rms_out / "check.json").read_text(encoding="utf-8"))
    assert carried["exceptions_carried_forward"]["from_run"] is None
    assert carried["exceptions_carried_forward"]["count"] == 0


def test_check_rms_grades_the_acceptance_accept_rms_wrote_beside_the_package(
    rms_dir: Path, rms_out: Path, tmp_path: Path
) -> None:
    """`check rms` -> `exceptions accept-rms` -> `check rms`: the loop an engineer walks.

    The acceptance survives the second check, and it survives through `exceptions.json`
    beside the package - which is where `accept-rms --package` writes it and what a run
    whose run folder carries no store grades against - not through one run folder carrying
    it to the next, which the test above shows cannot happen. The second run folder is
    asserted empty of a store for the same reason: nothing was carried, and nothing needed
    to be."""
    from swreview.exceptions import EXCEPTIONS_FILE_NAME

    first = rms_out.parent / "20260916-090000-check"
    assert check_rms(str(rms_dir), "--scope", "part", out=first).exit_code == 0

    waivers = tmp_path / "rms_exceptions.json"
    waivers.write_text(
        json.dumps({"rms.intent.every_feature_described": "legacy tree, accepted by owner"}),
        encoding="utf-8",
    )
    imported = invoke(
        "exceptions",
        "accept-rms",
        str(first),
        "--package",
        str(rms_dir),
        "--file",
        str(waivers),
        "--by",
        "owner",
    )
    assert imported.exit_code == 0, imported.stdout
    assert (rms_dir / EXCEPTIONS_FILE_NAME).is_file(), "accept-rms writes beside the package"

    body = payload(check_rms(str(rms_dir), "--scope", "part", "--json", out=rms_out))

    described = next(
        finding
        for finding in body["findings"]
        if finding["check"] == "rms.intent.every_feature_described"
    )
    assert described["status"] == "checked_within_scope"
    assert described["exception_id"] == "EX-001"
    assert not (rms_out / EXCEPTIONS_FILE_NAME).exists()


def test_check_rms_leaves_a_golden_fixture_it_graded_untouched(rms_out: Path) -> None:
    """The defect `--out` exists for: grading `tests/golden/fixtures/rms-part` in place
    left `session.json`, `report.md` and `check.json` inside the fixture, and the fixtures
    are this project's regression baseline (docs/pane-findings-2026-09-16.md item 2)."""
    assert git_status_of(RMS_PART_FIXTURE) == "", "the fixture was already dirty"

    result = check_rms(str(RMS_PART_FIXTURE), "--scope", "part", out=rms_out)

    assert result.exit_code == 0
    assert git_status_of(RMS_PART_FIXTURE) == ""
    assert (rms_out / "session.json").is_file()


# --- exceptions accept | list ----------------------------------------------------


def accept(run_dir: Path, package_dir: Path, finding_id: str = "F-001", *extra: str) -> Any:
    return invoke(
        "exceptions",
        "accept",
        str(run_dir),
        finding_id,
        "--package",
        str(package_dir),
        "--note",
        "press fit, intended",
        "--by",
        "engineer",
        *extra,
    )


def test_exceptions_accept_writes_an_exception_bound_to_the_finding(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    body = payload(accept(joint_run_dir, tmp_package_dir, "F-001", "--json"))

    assert body["exception"]["id"] == "EX-001"
    assert body["exception"]["check"] == "fastener.bottoming"
    assert body["exception"]["configuration"] == "Default"
    assert body["exception"]["note"] == "press fit, intended"
    assert body["exception"]["accepted_by"] == "engineer"
    assert body["exception"]["geometry_fingerprint"]

    stored = json.loads((tmp_package_dir / "exceptions.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in stored["exceptions"]] == ["EX-001"]


def test_exceptions_accept_records_the_exception_on_the_finding(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    accept(joint_run_dir, tmp_package_dir)

    session = json.loads((joint_run_dir / "session.json").read_text(encoding="utf-8"))
    assert session["findings"][0]["exception_id"] == "EX-001"
    assert (joint_run_dir / "report.md").is_file()


def test_exceptions_accept_re_renders_the_start_here_section_and_the_record(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    """FR-019: the waiver path re-renders through `rerender_run_folder` like the other two
    offline commands, so the report it leaves behind still opens its findings with the
    ranking and `attention.json` beside it describes the session as it now stands."""
    from swreview.report.attention import rank
    from swreview.report.attention_record import read_attention_record
    from swreview.report.session import load_session

    accept(joint_run_dir, tmp_package_dir)

    report = (joint_run_dir / "report.md").read_text(encoding="utf-8")
    assert "## Start here" in report
    assert report.index("## Start here") < report.index("## Findings")
    session = load_session(joint_run_dir / "session.json")
    record = read_attention_record(joint_run_dir)
    assert record.session_id == session.session_id
    assert [row.finding_id for row in record.rows] == [
        row.finding_id for row in rank(session).rows
    ]


def test_exceptions_accept_re_renders_with_the_package_it_was_pointed_at(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    """A review run folder holds no `package.json`, so the folder cannot supply it.

    `--package` is where this command was told to find the evidence, and the re-render is
    handed it: reading the folder instead would turn every component name back into an id
    and degrade Manifest Discrepancies to the placeholder (research R2.7).
    """
    assert not (joint_run_dir / "package.json").exists()

    accept(joint_run_dir, tmp_package_dir)

    report = (joint_run_dir / "report.md").read_text(encoding="utf-8")
    assert "_The evidence package was not supplied to the renderer._" not in report


def test_a_second_acceptance_gets_the_next_id(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    accept(joint_run_dir, tmp_package_dir, "F-001")

    body = payload(accept(joint_run_dir, tmp_package_dir, "F-002", "--json"))

    assert body["exception"]["id"] == "EX-002"


def test_exceptions_accept_refuses_a_finding_that_names_no_component(
    run_dir: Path, tmp_package_dir: Path
) -> None:
    """A drawing finding is not geometry; there is nothing to bind an exception to."""
    result = accept(run_dir, tmp_package_dir, "F-001")

    assert result.exit_code == 1
    assert "component" in result.stderr


def test_exceptions_accept_on_an_unknown_finding_exits_1(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    result = accept(joint_run_dir, tmp_package_dir, "F-404")

    assert result.exit_code == 1
    assert "F-404" in result.stderr


def test_exceptions_list_shows_what_is_active(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    accept(joint_run_dir, tmp_package_dir)

    body = payload(invoke("exceptions", "list", str(tmp_package_dir), "--json"))

    assert [item["id"] for item in body["exceptions"]] == ["EX-001"]
    assert body["exceptions"][0]["status"] == "active"
    assert body["counts"] == {"active": 1, "needs_review": 0, "retired": 0}


def test_exceptions_list_human_output_names_the_check_and_the_note(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    accept(joint_run_dir, tmp_package_dir)

    result = invoke("exceptions", "list", str(tmp_package_dir))

    assert result.exit_code == 0
    assert "EX-001" in result.stdout
    assert "press fit, intended" in result.stdout


def test_exceptions_list_flags_one_whose_geometry_moved(
    joint_run_dir: Path, tmp_package_dir: Path
) -> None:
    accept(joint_run_dir, tmp_package_dir)
    package = json.loads((tmp_package_dir / "package.json").read_text(encoding="utf-8"))
    package["design"]["active_configuration"] = "Machining"
    (tmp_package_dir / "package.json").write_text(json.dumps(package), encoding="utf-8")

    body = payload(invoke("exceptions", "list", str(tmp_package_dir), "--json"))

    assert body["exceptions"][0]["status"] == "needs_review"
    assert body["counts"]["needs_review"] == 1


def test_exceptions_list_on_a_package_with_none(tmp_package_dir: Path) -> None:
    body = payload(invoke("exceptions", "list", str(tmp_package_dir), "--json"))

    assert body["exceptions"] == []


def test_exceptions_list_on_a_missing_package_exits_1(tmp_path: Path) -> None:
    result = invoke("exceptions", "list", str(tmp_path / "nowhere"))

    assert result.exit_code == 1


# --- benchmark -------------------------------------------------------------------


@pytest.fixture
def benchmark_set(tmp_path: Path, tmp_package_dir: Path) -> Path:
    """A one-package benchmark set pointing at the written test package."""
    sets_dir = tmp_path / "sets"
    sets_dir.mkdir()
    set_path = sets_dir / "pilot.json"
    set_path.write_text(
        json.dumps(
            {
                "name": "pilot",
                "packages": [
                    {
                        "package_id": "cover",
                        "path": str(tmp_package_dir),
                        "held_out": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return set_path


@pytest.fixture
def answer_keys(tmp_path: Path) -> Path:
    directory = tmp_path / "answer_keys"
    directory.mkdir()
    (directory / "cover.json").write_text(
        json.dumps(
            {
                "package_id": "cover",
                "known_defects": [
                    {
                        "id": "D-1",
                        "check": "drawing.manufacturing_inputs",
                        "component_ids": [],
                        "description": "The tapped hole callout omits the thread depth",
                    }
                ],
                "correct_conditions": [],
            }
        ),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def benchmark_run_dir(
    tmp_path: Path, benchmark_set: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> Path:
    fake_provider()
    out = tmp_path / "runs" / "benchmark-2026-09-12"
    result = invoke("benchmark", "run", "--set", str(benchmark_set), "--out", str(out))
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


def test_benchmark_run_reviews_every_package_in_the_set(benchmark_run_dir: Path) -> None:
    assert (benchmark_run_dir / "cover" / "session.json").is_file()
    session = json.loads((benchmark_run_dir / "cover" / "session.json").read_text("utf-8"))
    assert session["timing"]["unattended_runtime_minutes"] >= 0


def test_benchmark_run_passes_the_provider_and_model_to_every_package(
    tmp_path: Path, benchmark_set: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    """FR-016: the benchmark runner takes the same `--provider`/`--model` as `review`."""
    built = fake_provider()

    result = invoke(
        "benchmark",
        "run",
        "--set",
        str(benchmark_set),
        "--out",
        str(tmp_path / "runs" / "provider"),
        "--provider",
        "fake",
        "--model",
        "gemini-3.5-flash",
        "--effort",
        "low",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [provider.settings.provider for provider in built] == [ProviderName.FAKE]
    assert [provider.settings.model for provider in built] == ["gemini-3.5-flash"]
    assert [provider.settings.effort for provider in built] == ["low"]
    session = json.loads(
        (tmp_path / "runs" / "provider" / "cover" / "session.json").read_text("utf-8")
    )
    assert session["model"] == "gemini-3.5-flash"


def test_benchmark_run_without_a_model_takes_the_providers_default(
    tmp_path: Path, benchmark_set: Path, fake_provider: Callable[..., list[RecordingProvider]]
) -> None:
    built = fake_provider()

    result = invoke(
        "benchmark",
        "run",
        "--set",
        str(benchmark_set),
        "--out",
        str(tmp_path / "runs" / "default-model"),
        "--provider",
        "gemini",
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [provider.settings.model for provider in built] == ["gemini-3.5-flash"]


def test_benchmark_run_on_a_missing_set_exits_1(tmp_path: Path) -> None:
    result = invoke(
        "benchmark", "run", "--set", str(tmp_path / "nowhere.json"), "--out", str(tmp_path / "o")
    )

    assert result.exit_code == 1


def test_benchmark_score_writes_a_scorecard(benchmark_run_dir: Path, answer_keys: Path) -> None:
    body = payload(
        invoke(
            "benchmark",
            "score",
            str(benchmark_run_dir),
            "--answer-keys",
            str(answer_keys),
            "--json",
        )
    )

    scorecard = json.loads((benchmark_run_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["benchmark_set"] == "pilot"
    assert [score["package_id"] for score in scorecard["per_package"]] == ["cover"]
    assert scorecard["aggregate"]["packages"] == 1
    assert (benchmark_run_dir / "scorecard.md").is_file()
    assert body["aggregate"]["packages"] == 1


def test_benchmark_score_without_a_set_to_score_against_exits_1(
    tmp_path: Path, answer_keys: Path
) -> None:
    empty = tmp_path / "empty-run"
    empty.mkdir()

    result = invoke("benchmark", "score", str(empty), "--answer-keys", str(answer_keys))

    assert result.exit_code == 1
    assert "--set" in result.stderr


def test_benchmark_time_records_the_human_minutes(benchmark_run_dir: Path) -> None:
    body = payload(
        invoke(
            "benchmark",
            "time",
            str(benchmark_run_dir),
            "cover",
            "--baseline",
            "90",
            "--supervision",
            "10",
            "--verification",
            "5",
            "--false-alarms",
            "2",
            "--json",
        )
    )

    session = json.loads((benchmark_run_dir / "cover" / "session.json").read_text("utf-8"))
    timing = session["timing"]
    assert timing["baseline_minutes"] == 90
    assert timing["assisted_supervision_minutes"] == 10
    assert timing["net_saved_minutes"] == 73
    assert body["timing"]["net_saved_minutes"] == 73


def test_benchmark_time_for_an_unknown_package_exits_1(benchmark_run_dir: Path) -> None:
    result = invoke("benchmark", "time", str(benchmark_run_dir), "nope", "--baseline", "10")

    assert result.exit_code == 1


# --- the command surface ---------------------------------------------------------


def test_the_top_level_help_lists_every_command_group() -> None:
    result = invoke("--help")

    assert result.exit_code == 0
    for command in (
        "validate",
        "ingest",
        "review",
        "report",
        "disposition",
        "timing",
        "attention",
        "check",
        "exceptions",
        "benchmark",
    ):
        assert command in result.stdout


def test_exceptions_is_a_placeholder_group_with_no_commands() -> None:
    result = invoke("exceptions")

    assert result.exit_code == 2


def test_an_unknown_command_is_a_usage_error() -> None:
    assert invoke("simulate").exit_code == 2
