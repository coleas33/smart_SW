"""Unit tests for the `swreview` command line (T043, T081 CLI half, T097).

Every command of contracts/cli.md is exercised on files this test makes: a written
evidence package, a manifest and BOM, a fake-client review, a synthetic benchmark run.
The three rules the contract states for all of them are asserted per command:

- exit 0 on success, 1 on a validation or runtime error, 2 on a usage error;
- `--json` prints machine-readable output on stdout and nothing else;
- diagnostics go to stderr, so a `--json` consumer never has to parse around them.

No network: `swreview.cli.REVIEW_CLIENT` is the injection point the review commands hand
to `swreview.agent.runner.run_review`, and the fake below is the same shape as the one in
`test_agent_runner.py` - the SDK contract the runner depends on and nothing more.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from anthropic.lib.tools import ToolError
from typer.testing import CliRunner

from swreview import cli
from swreview.ir.loader import save_package
from swreview.ir.models import EvidencePackage
from tests.unit.test_tools_checks_fit import drawing_package

REPO_ROOT = Path(__file__).resolve().parents[3]
COVER_BLIND_TAP = REPO_ROOT / "benchmarks" / "packages" / "cover-blind-tap"

MakePackage = Callable[..., EvidencePackage]

runner = CliRunner()


# --- the fake Anthropic client ---------------------------------------------------


ToolCall = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class Turn:
    """One assistant turn: why it stopped, and what it asked the tools to do."""

    stop_reason: str
    calls: tuple[ToolCall, ...] = ()


class FakeMessage:
    role = "assistant"

    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason


@dataclass
class FakeToolRunner:
    tools: dict[str, Any]
    script: list[Turn]
    pending: list[ToolCall] = field(default_factory=list)

    def __iter__(self) -> Iterator[FakeMessage]:
        for turn in self.script:
            self.pending = list(turn.calls)
            yield FakeMessage(turn.stop_reason)

    def generate_tool_call_response(self) -> None:
        for name, arguments in self.pending:
            try:
                self.tools[name].call(arguments)
            except ToolError:
                pass
        self.pending = []


class FakeMessages:
    def __init__(self, script: Sequence[Turn]) -> None:
        self.script = list(script)
        self.kwargs: dict[str, Any] = {}

    def tool_runner(self, **kwargs: Any) -> FakeToolRunner:
        self.kwargs = kwargs
        return FakeToolRunner(
            tools={tool.name: tool for tool in kwargs["tools"]}, script=self.script
        )


class FakeBeta:
    def __init__(self, script: Sequence[Turn]) -> None:
        self.messages = FakeMessages(script)


class FakeClient:
    """`client.beta.messages.tool_runner(...)`, and nothing else."""

    def __init__(self, script: Sequence[Turn]) -> None:
        self.beta = FakeBeta(script)


DRAWING_FINDING: ToolCall = (
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

SCRIPT: tuple[Turn, ...] = (
    Turn("tool_use", (("get_package_summary", {}), DRAWING_FINDING)),
    Turn("end_turn"),
)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeClient]:
    """Install a scripted fake client as the one `swreview.cli` hands to `run_review`."""

    def install(script: Sequence[Turn] = SCRIPT) -> FakeClient:
        client = FakeClient(script)
        monkeypatch.setattr(cli, "REVIEW_CLIENT", client)
        return client

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
def run_dir(tmp_path: Path, tmp_package_dir: Path, fake_client: Callable[..., FakeClient]) -> Path:
    """A finished review: `session.json` with one finding, and `report.md`."""
    fake_client()
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
    tmp_package_dir: Path, tmp_path: Path, fake_client: Callable[..., FakeClient]
) -> None:
    fake_client()
    out = tmp_path / "run"

    body = payload(invoke("review", str(tmp_package_dir), "--out", str(out), "--json"))

    session = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert session["design_id"] == "dsn:1"
    assert session["model"] == "claude-opus-5"
    assert [finding["id"] for finding in session["findings"]] == ["F-001"]
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "F-001" in report
    assert body["findings"] == 1
    assert body["session_file"].endswith("session.json")
    assert body["report_file"].endswith("report.md")


def test_review_passes_the_model_and_effort_through(
    tmp_package_dir: Path, tmp_path: Path, fake_client: Callable[..., FakeClient]
) -> None:
    client = fake_client()

    result = invoke(
        "review",
        str(tmp_package_dir),
        "--out",
        str(tmp_path / "run"),
        "--model",
        "claude-sonnet-4-5",
        "--effort",
        "medium",
        "--max-steps",
        "5",
    )

    assert result.exit_code == 0
    kwargs = client.beta.messages.kwargs
    assert kwargs["model"] == "claude-sonnet-4-5"
    assert kwargs["output_config"] == {"effort": "medium"}


def test_review_fail_tool_keeps_the_run_alive_and_records_the_failure(
    tmp_package_dir: Path, tmp_path: Path, fake_client: Callable[..., FakeClient]
) -> None:
    fake_client()
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
    tmp_package_dir: Path, tmp_path: Path, fake_client: Callable[..., FakeClient]
) -> None:
    fake_client()

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


def test_review_with_the_bridge_exits_1(
    tmp_package_dir: Path, tmp_path: Path, fake_client: Callable[..., FakeClient]
) -> None:
    fake_client()

    result = invoke("review", str(tmp_package_dir), "--out", str(tmp_path / "run"), "--bridge")

    assert result.exit_code == 1
    assert "US3" in result.stderr


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
            "cole",
            "--json",
        )
    )

    session = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    disposition = session["findings"][0]["disposition"]
    assert disposition["decision"] == "accepted"
    assert disposition["note"] == "reviewed, ok"
    assert disposition["by"] == "cole"
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
    tmp_path: Path, benchmark_set: Path, fake_client: Callable[..., FakeClient]
) -> Path:
    fake_client()
    out = tmp_path / "runs" / "benchmark-2026-09-12"
    result = invoke("benchmark", "run", "--set", str(benchmark_set), "--out", str(out))
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


def test_benchmark_run_reviews_every_package_in_the_set(benchmark_run_dir: Path) -> None:
    assert (benchmark_run_dir / "cover" / "session.json").is_file()
    session = json.loads((benchmark_run_dir / "cover" / "session.json").read_text("utf-8"))
    assert session["timing"]["unattended_runtime_minutes"] >= 0


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
