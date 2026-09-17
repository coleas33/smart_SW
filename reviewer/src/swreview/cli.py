"""The `swreview` command line (contracts/cli.md).

One command per row of the contract, and three rules that hold for all of them:

- exit 0 on success, 1 on a validation or runtime error, 2 on a usage error. Usage errors
  are Typer's own (a missing argument, an unknown `--effort`); everything the commands
  can fail on - an unreadable package, a schema this build cannot read, a finding id that
  is not in the session - is caught at the command boundary and printed as one line;
- `--json` prints machine-readable JSON on stdout and nothing else, so a caller can pipe
  it; without it the same information is printed for a human;
- diagnostics go to stderr. stdout carries the result and only the result.

This module holds no logic of its own: every command is a thin shell around the library
(`ingest`, `agent.runner`, `report`, `tools`, `benchmark`). The one exception is
`audit-secrets`, whose whole subject is this process's environment and the filesystem
under it - there is no library layer beneath it for a command to be a shell around, and
inventing one for a single caller would be the abstraction the constitution forbids. Two
hooks make it testable
without a network: `provider_factory`, which turns the resolved `ProviderSettings` into
the one adapter a run talks to, and `_review_fn`, the per-package review the benchmark
runner calls.

`provider_factory` is also the only place in the product that constructs a provider SDK
client, and it is the reason `--provider`/`--model`/`--effort` mean the same thing to
`review` and to `benchmark run`: both resolve their flags through
`ProviderSettings.from_env`, so the model default is the per-provider one from
`agent/settings.py` and the key comes from the same place with the same precedence.

Sub-apps (`check`, `benchmark`, `exceptions`, `rms`) are the extension points: one command
per deterministic check under `check_app`, the retained-exception commands under
`exceptions_app`, and under `rms_app` the Resilient Modeling commands that grade nothing -
they report what the shipped type table does not know, so an engineer can calibrate it,
and they write the plan the extractor's `suppress-test` is allowed to act on.
"""

from __future__ import annotations

import inspect
import json
import os
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, get_args

import typer
from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from swreview.agent import providers
from swreview.agent.checklist import CHECKLIST_FILE, load_checklist
from swreview.agent.providers import AgentProvider, EffortLevel, ProviderName
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import (
    DEFAULT_MAX_STEPS,
    SESSION_FILE_NAME,
    load_exceptions,
    run_review,
)
from swreview.agent.settings import (
    DEFAULT_EFFORT,
    DEFAULT_PROVIDER,
    LEVER_NAMES,
    NO_STUDY,
    EfficiencySettings,
    ProviderSettings,
    check_study_arm,
    configure_logging_redaction,
    efficiency_from_levers,
    output_ceiling,
    redact,
)
from swreview.benchmark.compare import (
    carry_sign_offs,
    committed_sign_off_sources,
    compare_runs,
    refused_decisions,
    render_ledger_md,
    splice_ledger,
    write_ledger,
)
from swreview.benchmark.runner import (
    RunProvenance,
    current_commit,
    run_benchmark,
    sha256_of,
    write_provenance,
)
from swreview.benchmark.scorecard import render_scorecard_md, score_run
from swreview.benchmark.sets import BenchmarkSet, load_set
from swreview.benchmark.timing import record_timing
from swreview.chat import DEFAULT_ALLOW_ORIGIN, DEFAULT_RUN_ROOT
from swreview.checks.golden_interference import interference_case
from swreview.checks.rms.plan import PLAN_FILE_NAME, build_plan
from swreview.checks.rms.registry import RULES
from swreview.checks.rms.run import RmsScope, run_rms_check
from swreview.checks.rms_types import load_table, unknown_types
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore, ReviewException
from swreview.findings import Finding
from swreview.ingest.package_builder import build_package
from swreview.ir.loader import AnswerKeyAccessError, load_package
from swreview.ir.models import EvidencePackage, UnsupportedSchemaVersionError
from swreview.ir.summary import summarize
from swreview.remodel.plan import part_document_ids, plan_reorganize
from swreview.remodel.summary import plan_lines, plan_summary_row
from swreview.report.dispositions import REPORT_FILE_NAME, apply_disposition, find_finding
from swreview.report.markdown import render_report
from swreview.report.session import CoverageBucket, ReviewSession, load_session, save_session
from swreview.tools import checks_fastener, checks_fit
from swreview.tools.context import ToolContext, build_context, use_context
from swreview.tools.query import ToolResult

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Agentic design review for SOLIDWORKS evidence packages.",
)
check_app = typer.Typer(
    no_args_is_help=True,
    help="Run one deterministic check without the agent and print the finding.",
)
benchmark_app = typer.Typer(
    no_args_is_help=True,
    help="Review a benchmark set, score it against answer keys, and record timing.",
)
exceptions_app = typer.Typer(
    no_args_is_help=True,
    help="Retained exceptions: accept a finding, import an RMS waiver file, list them.",
)
chat_app = typer.Typer(
    no_args_is_help=True,
    help="The loopback chat backend the SOLIDWORKS Task Pane talks to.",
)
rms_app = typer.Typer(
    no_args_is_help=True,
    help="Resilient Modeling helpers that grade nothing: calibration and plans.",
)
remodel_app = typer.Typer(
    no_args_is_help=True,
    help="The resilient re-modeler: plan the reorganize stage without SOLIDWORKS.",
)
app.add_typer(check_app, name="check")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(exceptions_app, name="exceptions")
app.add_typer(chat_app, name="chat")
app.add_typer(rms_app, name="rms")
app.add_typer(remodel_app, name="remodel")

FAKE_REVIEW_SCRIPT: tuple[ScriptedTurn, ...] = (
    ScriptedTurn(
        text=(
            "Dry run: --provider fake sends nothing to a model. It reads the package "
            "census and stops, so every checklist item is left unresolved."
        ),
        tool_calls=(ScriptedToolCall("get_package_summary"),),
    ),
)
"""What `--provider fake` reviews with: one turn, one read-only tool call, no key.

It exists so the whole command path - load, bind tools, run a turn, write `session.json`
and `events.jsonl` - is exercisable on a workstation with no credentials. The text says
so in the session, because a dry run that reads like a finished review is worse than no
run at all.
"""


SAVED_SET_FILE = "benchmark-set.json"
"""`benchmark run` writes the set it ran into the run directory, so `benchmark score`
can score it without being told twice which set this run was."""

HANDLED_ERRORS = (
    UnsupportedSchemaVersionError,
    AnswerKeyAccessError,
    ValidationError,
    OSError,
    NotImplementedError,
    KeyError,
    ValueError,
    LookupError,
)
"""Everything the library raises for input it can describe. Each becomes exit 1 and one
line on stderr; anything else is a bug and keeps its traceback. `OSError` covers every
path the filesystem refuses - missing, denied, or a directory where a file was named -
because a path is input to these commands and its refusal is an answer, not a crash."""

MESSAGE_LENGTH = 400


class Effort(StrEnum):
    """`output_config.effort` for a run (contracts/cli.md)."""

    low = "low"
    medium = "medium"
    high = "high"
    xhigh = "xhigh"


DEFAULT_EFFORT_CHOICE = Effort(DEFAULT_EFFORT)
"""`--effort`'s default as a Typer choice; `agent/settings.py` still decides what it is."""


class Decision(StrEnum):
    """An engineer's disposition of a finding (data-model.md section 5)."""

    accepted = "accepted"
    rejected = "rejected"
    deferred = "deferred"


# --- the option types every command shares ---------------------------------------

JsonFlag = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON on stdout.")]
ProviderOption = Annotated[
    ProviderName, typer.Option("--provider", help="Which provider runs the review.")
]
ModelOption = Annotated[
    str | None, typer.Option("--model", help="Model id; default: the provider's own.")
]
EffortOption = Annotated[Effort, typer.Option("--effort", help="Reasoning effort.")]
PackageOption = Annotated[Path, typer.Option("--package", help="Directory holding package.json.")]
LeverOption = Annotated[
    list[str] | None,
    typer.Option(
        "--lever",
        help=(
            "Turn an efficiency lever on for this run; repeatable. One of: "
            + ", ".join(LEVER_NAMES)
        ),
    ),
]


# --- the provider one run talks to -----------------------------------------------


def provider_factory(
    settings: ProviderSettings, efficiency: EfficiencySettings | None = None
) -> AgentProvider:
    """Build the adapter a review talks to. The single injection point for the tests.

    The adapter class comes from `providers.get`, which imports the module (and so the
    SDK) lazily, so a `fake` run loads neither `openai` nor `google.genai`. Only the
    construction differs per provider, and it differs because the SDKs do: OpenAI's
    adapter builds its own client from the key and base URL, Gemini's takes a client the
    caller configured (`client_kwargs()` covers the enterprise case too) plus the
    redactor that keeps the key out of any message it reports, and the scripted provider
    takes a script instead of a key.

    Tests replace this function wholesale rather than patching a client onto it, so no
    test needs to know how any SDK client is constructed.

    `efficiency` is here for the one lever that is decided at construction rather than at
    `start_review`: lever 6's `parallel_tool_calls`, which is an OpenAI request field.
    Omitted, every lever is off, which is what the pane and every library caller get.
    """
    levers = efficiency if efficiency is not None else EfficiencySettings()
    adapter = providers.get(settings.provider)
    if settings.provider is ProviderName.GEMINI:
        from google import genai

        return adapter(
            client=genai.Client(**settings.client_kwargs()),
            model=settings.model,
            redact=lambda text: redact(text, settings.secrets),
            max_output_tokens=output_ceiling(settings.provider, settings.model),
        )
    if settings.provider is ProviderName.FAKE:
        return adapter(script=FAKE_REVIEW_SCRIPT, model=settings.model)
    return adapter(
        model=settings.model,
        parallel_tool_calls=levers.parallel_tool_calls,
        **settings.client_kwargs(),
    )


def _provider_settings(
    provider: ProviderName, model: str | None, effort: Effort
) -> ProviderSettings:
    """What `--provider`, `--model` and `--effort` resolve to for one run.

    `--model` is deliberately optional: the default belongs to the provider and lives in
    `agent/settings.py`, so no command line and no session can end up naming a model this
    product does not run (FR-026).
    """
    effort_level: EffortLevel = effort.value  # type: ignore[assignment]
    return ProviderSettings.from_env(provider=provider, model=model, effort=effort_level)


def _efficiency(
    levers: Sequence[str] | None,
    *,
    provider: ProviderName,
    study: str = NO_STUDY,
    arm: str | None = None,
    allow_workstation_levers: bool = True,
) -> EfficiencySettings:
    """What `--lever`, `--study` and `--arm` resolve to for one run, or a usage error.

    Every refusal `agent/settings.py` states is about what was typed on this command line,
    so each is a usage error - exit 2 - and each happens here, before an adapter is built
    or a package is read. That is the whole reason the study refusals live on the command
    that chooses the lever rather than on `benchmark compare`: a refusal after six paid
    runs is worthless (contracts/ab-harness.md section 2).
    """
    try:
        efficiency = efficiency_from_levers(
            levers or (),
            provider=provider,
            allow_workstation_levers=allow_workstation_levers,
        )
        check_study_arm(study=study, arm=arm, efficiency=efficiency)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return efficiency


@contextmanager
def _redacting(settings: ProviderSettings) -> Iterator[Callable[[str], str]]:
    """Keep this run's key out of every log line, and hand back the redactor for the rest.

    Two halves of FR-015, because a key leaks by two routes and neither covers the other.
    `configure_logging_redaction` masks every log record in the process - the SDKs log
    through their own loggers, which a filter on the root logger never sees - and the
    yielded callable is what the runner applies to provider error text before writing it
    into the run folder, where no log handler is involved at all.

    The install is taken off when the command ends: a redactor still masking the key of a
    finished run is dead weight, and `remove()` is written to be safe if something else
    installed on top of it.
    """
    redactor = configure_logging_redaction(settings.secrets)
    try:
        yield lambda text: redact(text, settings.secrets)
    finally:
        redactor.remove()


# --- output and error handling ---------------------------------------------------


def _one_line(exc: BaseException) -> str:
    """An exception as a single, bounded line: stderr stays greppable."""
    text = " ".join(str(exc).split())
    if isinstance(exc, KeyError):
        text = text.strip("'")
    if len(text) > MESSAGE_LENGTH:
        text = text[: MESSAGE_LENGTH - 1] + "…"
    return f"{type(exc).__name__}: {text}"


@contextmanager
def _errors_as_exit_1() -> Iterator[None]:
    """Turn anything in `HANDLED_ERRORS` into one line on stderr and exit code 1."""
    try:
        yield
    except HANDLED_ERRORS as exc:
        typer.echo(f"error: {_one_line(exc)}", err=True)
        raise typer.Exit(1) from exc


def _emit(payload: dict[str, Any], lines: list[str], json_output: bool) -> None:
    """The result on stdout: JSON when asked for, the same facts as text otherwise."""
    if json_output:
        typer.echo(json.dumps(to_jsonable_python(payload), indent=2))
        return
    for line in lines:
        typer.echo(line)


def _counts_line(counts: dict[str, int]) -> str:
    return ", ".join(f"{name}: {count}" for name, count in counts.items())


# --- validate --------------------------------------------------------------------


@app.command()
def validate(
    package_dir: Annotated[Path, typer.Argument(help="Directory holding package.json.")],
    json_output: JsonFlag = False,
) -> None:
    """Load package.json against the IR schema and print gaps and discrepancies."""
    with _errors_as_exit_1():
        loaded = load_package(package_dir)

    package = loaded.package
    counts = summarize(package)
    discrepancies = package.manifest.discrepancies
    payload = {
        "package_dir": str(loaded.base_dir),
        "package_id": str(package.package_id),
        "schema_version": package.schema_version,
        "design_id": package.design.design_id,
        "design_name": package.design.name,
        "configuration": package.design.active_configuration,
        "counts": counts,
        "gaps": [to_jsonable_python(gap) for gap in package.gaps],
        "discrepancies": [to_jsonable_python(item) for item in discrepancies],
    }
    lines = [
        f"{package.design.design_id} ({package.design.name}), "
        f"configuration {package.design.active_configuration}",
        f"schema {package.schema_version}, package {package.package_id}",
        _counts_line(counts),
        f"discrepancies: {len(discrepancies)}",
    ]
    lines += [f"  {item.kind} {item.document_id}: {item.note}" for item in discrepancies]
    lines.append(f"gaps: {len(package.gaps)}")
    lines += [
        f"  {gap.kind} {gap.entity_kind} {gap.entity_id}: {gap.reason}" for gap in package.gaps
    ]
    _emit(payload, lines, json_output)


# --- ingest ----------------------------------------------------------------------


@app.command()
def ingest(
    package_dir: Annotated[Path, typer.Argument(help="Directory package.json is written to.")],
    manifest: Annotated[Path, typer.Option("--manifest", help="manifest.json of the export.")],
    bom: Annotated[Path, typer.Option("--bom", help="bom.csv of the export.")],
    pdf: Annotated[
        list[Path] | None, typer.Option("--pdf", help="Drawing PDF; repeatable.")
    ] = None,
    step: Annotated[
        list[Path] | None, typer.Option("--step", help="STEP file; repeatable.")
    ] = None,
    native: Annotated[
        Path | None,
        typer.Option("--native", help="A package.json dumped on the workstation; it wins."),
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Build or augment package.json from exported files (drawing parse, BOM, manifest)."""
    if step:
        typer.echo(
            "note: STEP geometry is not read by this build; "
            f"ignored: {', '.join(str(path) for path in step)}",
            err=True,
        )
    with _errors_as_exit_1():
        package = build_package(
            package_dir,
            manifest,
            bom,
            pdf_paths=list(pdf) if pdf else None,
            native_package_path=native,
        )

    counts = summarize(package)
    package_file = Path(package_dir).resolve() / "package.json"
    payload = {
        "package_dir": str(Path(package_dir).resolve()),
        "package_file": str(package_file),
        "design_id": package.design.design_id,
        "counts": counts,
        "gaps": [to_jsonable_python(gap) for gap in package.gaps],
        "discrepancies": [
            to_jsonable_python(item) for item in package.manifest.discrepancies
        ],
    }
    lines = [
        f"wrote {package_file}",
        _counts_line(counts),
        f"discrepancies: {len(package.manifest.discrepancies)}, gaps: {len(package.gaps)}",
    ]
    _emit(payload, lines, json_output)


# --- review ----------------------------------------------------------------------


def _checklist_kwargs(checklist: Path | None) -> dict[str, Any]:
    """`--checklist` as a `run_review` keyword, or a refusal if the runner has no such hook.

    The contract lists `--checklist`; `swreview.agent.runner.run_review` does not take one
    yet. Silently ignoring the file would review against the built-in checklist while the
    engineer believed theirs was used, so this refuses instead, and starts forwarding the
    file the moment the runner grows the parameter.
    """
    if checklist is None:
        return {}
    loaded = load_checklist(checklist)
    if "checklist" not in inspect.signature(run_review).parameters:
        raise ValueError(
            "--checklist is not available in this build: swreview.agent.runner.run_review "
            "takes no checklist argument, so the file would be ignored"
        )
    return {"checklist": loaded}


@app.command()
def review(
    package_dir: Annotated[Path, typer.Argument(help="Directory holding package.json.")],
    out: Annotated[Path, typer.Option("--out", help="Directory session.json and report.md go in.")],
    provider: ProviderOption = DEFAULT_PROVIDER,
    model: ModelOption = None,
    effort: EffortOption = DEFAULT_EFFORT_CHOICE,
    bridge: Annotated[
        bool, typer.Option("--bridge", help="Use the live SOLIDWORKS bridge (US3).")
    ] = False,
    checklist: Annotated[
        Path | None, typer.Option("--checklist", help="A checklist YAML file.")
    ] = None,
    fail_tool: Annotated[
        list[str] | None,
        typer.Option("--fail-tool", help="Force a tool to fail; test hook. Repeatable."),
    ] = None,
    max_steps: Annotated[
        int, typer.Option("--max-steps", help="Tool-call budget.")
    ] = DEFAULT_MAX_STEPS,
    lever: LeverOption = None,
    json_output: JsonFlag = False,
) -> None:
    """Run the agent loop over a package; write session.json and report.md."""
    efficiency = _efficiency(lever, provider=provider)
    with _errors_as_exit_1():
        settings = _provider_settings(provider, model, effort)
        with _redacting(settings) as redactor:
            session = run_review(
                package_dir,
                out,
                provider=provider_factory(settings, efficiency),
                model=settings.model,
                effort=settings.effort,
                key_source=settings.key_source,
                max_steps=max_steps,
                efficiency=efficiency,
                fail_tool=tuple(fail_tool or ()),
                bridge=bridge,
                redact=redactor,
                **_checklist_kwargs(checklist),
            )
            package = load_package(package_dir).package
            report_file = Path(out).resolve() / REPORT_FILE_NAME
            report_file.write_text(render_report(session, package), encoding="utf-8")

    coverage = session.coverage
    payload = {
        "package_dir": str(Path(package_dir).resolve()),
        "out_dir": str(Path(out).resolve()),
        "session_file": str(Path(out).resolve() / SESSION_FILE_NAME),
        "report_file": str(report_file),
        "provider": settings.provider.value,
        "model": session.model,
        "findings": len(session.findings),
        "evidence_requests": len(session.evidence_requests),
        "steps": len(session.steps),
        "coverage": {
            bucket: len(getattr(coverage, bucket))
            for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        },
    }
    lines = [
        f"reviewed {package.design.design_id} with {settings.provider.value} {session.model}",
        f"{len(session.findings)} findings, {len(session.evidence_requests)} evidence requests, "
        f"{len(session.steps)} tool calls",
        f"session: {payload['session_file']}",
        f"report: {payload['report_file']}",
    ]
    _emit(payload, lines, json_output)


# --- report ----------------------------------------------------------------------


@app.command()
def report(
    session_file: Annotated[Path, typer.Argument(help="The session.json to render.")],
    out: Annotated[
        Path | None, typer.Option("--out", help="Markdown file; default report.md beside it.")
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Re-render the Markdown report from a session."""
    target = Path(out) if out is not None else Path(session_file).parent / REPORT_FILE_NAME
    with _errors_as_exit_1():
        session = load_session(session_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_report(session), encoding="utf-8")

    payload = {
        "session_file": str(session_file),
        "report_file": str(target),
        "findings": len(session.findings),
    }
    _emit(payload, [f"wrote {target} ({len(session.findings)} findings)"], json_output)


# --- disposition -----------------------------------------------------------------


def _default_user() -> str:
    """Who to attribute a disposition to when `--by` is not given."""
    return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


@app.command()
def disposition(
    run_dir: Annotated[Path, typer.Argument(help="Directory holding session.json.")],
    finding_id: Annotated[str, typer.Argument(help="Finding id, for example F-001.")],
    decision: Annotated[
        Decision, typer.Option("--decision", help="accepted, rejected or deferred.")
    ],
    note: Annotated[str, typer.Option("--note", help="Why, in the engineer's words.")] = "",
    by: Annotated[
        str | None, typer.Option("--by", help="Who decided; defaults to the current user.")
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Record an engineer's decision on a finding and re-render the report."""
    decided_by = by if by else _default_user()
    with _errors_as_exit_1():
        apply_disposition(run_dir, finding_id, decision.value, note, decided_by)

    run_dir = Path(run_dir).resolve()
    payload = {
        "run_dir": str(run_dir),
        "finding_id": finding_id,
        "decision": decision.value,
        "by": decided_by,
        "note": note,
        "session_file": str(run_dir / SESSION_FILE_NAME),
        "report_file": str(run_dir / REPORT_FILE_NAME),
    }
    lines = [
        f"{finding_id}: {decision.value} by {decided_by}",
        f"report: {payload['report_file']}",
    ]
    _emit(payload, lines, json_output)


# --- check fit | stack -----------------------------------------------------------


def _parse_ref(option: str, text: str) -> dict[str, str]:
    """`document_id:sheet:annotation` as a SourceRef dict.

    Split from the right: a document id carries a colon of its own (`doc:3`), so only the
    last two colons separate fields.
    """
    parts = [part.strip() for part in text.rsplit(":", 2)]
    if len(parts) != 3 or not all(parts):
        raise typer.BadParameter(
            f"{text!r} is not document_id:sheet:annotation, for example "
            "DRW-2001:Sheet1:DIM-BORE",
            param_hint=option,
        )
    document_id, sheet, annotation = parts
    return {"document_id": document_id, "sheet": sheet, "annotation": annotation}


def _parse_signed_ref(option: str, text: str) -> tuple[dict[str, str], int]:
    """`document_id:sheet:annotation:+1` as a SourceRef dict and its sign."""
    ref_text, _, sign_text = text.rpartition(":")
    if sign_text.strip() not in ("+1", "1", "-1"):
        raise typer.BadParameter(
            f"{text!r} does not end in a sign: append ':+1' to add the dimension to the "
            "stack or ':-1' to subtract it",
            param_hint=option,
        )
    return _parse_ref(option, ref_text), int(sign_text)


def _context_for(package_dir: Path, *, exceptions: bool = False) -> ToolContext:
    """A tool context over the package in `package_dir`, with a session nothing saves.

    `exceptions` loads `exceptions.json` from beside the package and refreshes it in
    memory, so a waiver whose evidence has moved reads `needs_review` and silences
    nothing. Nothing is written back: grading a package must never edit it. The checks
    that consult no exception at all leave it off rather than reading a file they would
    then ignore.
    """
    loaded = load_package(package_dir)
    store = load_exceptions(loaded) if exceptions else None
    if store is not None:
        store.refresh(loaded.package)
    return build_context(loaded, exceptions=store)


def _finding_lines(finding: dict[str, Any]) -> list[str]:
    """One finding as the human output: verdict, evidence, and what it did not cover."""
    lines = [
        f"{finding['check']}: {finding['status']} ({finding['severity']})",
        f"observed: {finding['observed']}",
        f"requirement: {finding['requirement']}",
    ]
    calculation = finding.get("calculation")
    if calculation is not None:
        lines.append(
            "result: "
            + ", ".join(f"{name}={value}" for name, value in calculation["result"].items())
        )
        lines.append("excluded: " + "; ".join(calculation["excluded_effects"]))
    lines += [f"coverage limit: {limit}" for limit in finding["coverage_limits"]]
    lines.append(f"recommended action: {finding['recommended_action']}")
    return lines


def _emit_check(result: ToolResult, json_output: bool) -> None:
    """Print what a check tool produced, or its error result and exit 1.

    A check tool returns one finding (`fit`, `stack`, `alignment`), several (a fastener
    joint is four), or no finding at all when the condition is out of scope - which is
    coverage, and is printed as such rather than being mistaken for a pass.
    """
    error = result.get("error")
    if error is not None:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1)

    if result.get("status") == "out_of_scope":
        item = result["coverage_item"]
        _emit(
            result,
            [f"{item['check']}: out_of_scope", f"reason: {item['reason']}"],
            json_output,
        )
        return

    findings = result.get("findings")
    if findings is None:
        findings = [result["finding"]]
    lines: list[str] = []
    for index, finding in enumerate(findings):
        if index:
            lines.append("")
        lines += _finding_lines(finding)
    for layer in result.get("clamped", []):
        thickness = layer["thickness"]
        stated = "unknown" if thickness is None else f"{thickness['value']} {thickness['unit']}"
        lines.append(f"clamped {layer['component_id']}: {stated} ({layer['source']})")
    _emit(result, lines, json_output)


@check_app.command("fit")
def check_fit_command(
    package: PackageOption,
    bore: Annotated[
        str, typer.Option("--bore", help="document_id:sheet:annotation of the bore diameter.")
    ],
    shaft: Annotated[
        str, typer.Option("--shaft", help="document_id:sheet:annotation of the shaft diameter.")
    ],
    json_output: JsonFlag = False,
) -> None:
    """Size-only fit of a shaft in a bore, from two drawn diameters."""
    bore_ref = _parse_ref("--bore", bore)
    shaft_ref = _parse_ref("--shaft", shaft)

    with _errors_as_exit_1():
        context = _context_for(package)
    with use_context(context):
        result = checks_fit.check_fit(bore_ref, shaft_ref)
    _emit_check(result, json_output)


@check_app.command("stack")
def check_stack_command(
    package: PackageOption,
    dims: Annotated[
        list[str],
        typer.Option("--dims", help="document_id:sheet:annotation:+1 or :-1; repeatable."),
    ],
    target: Annotated[
        str | None, typer.Option("--target", help="document_id:sheet:annotation of the gap.")
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Worst-case axial stack of drawn dimensions, against a target gap."""
    parsed = [_parse_signed_ref("--dims", text) for text in dims]
    target_ref = None if target is None else _parse_ref("--target", target)

    with _errors_as_exit_1():
        context = _context_for(package)
    with use_context(context):
        result = checks_fit.check_axial_stack(
            [ref for ref, _ in parsed], [sign for _, sign in parsed], target_ref
        )
    _emit_check(result, json_output)


@check_app.command("fastener")
def check_fastener_command(
    package: PackageOption,
    fastener: Annotated[str, typer.Option("--fastener", help="Fastener id, e.g. fst:1.")],
    hole: Annotated[str, typer.Option("--hole", help="Tapped hole id, e.g. hole:1.")],
    clamped: Annotated[
        str,
        typer.Option(
            "--clamped",
            help="Component ids the screw clamps, from the head down: id,id",
        ),
    ] = "",
    json_output: JsonFlag = False,
) -> None:
    """One screw joint: bottoming, engagement, thread match and head clearance."""
    clamped_ids = [item.strip() for item in clamped.split(",") if item.strip()]

    with _errors_as_exit_1():
        context = _context_for(package)
    with use_context(context):
        result = checks_fastener.check_fastener_joint(fastener, hole, clamped_ids)
    _emit_check(result, json_output)


@check_app.command("alignment")
def check_alignment_command(
    package: PackageOption,
    hole_a: Annotated[str, typer.Option("--hole-a", help="First hole id.")],
    hole_b: Annotated[str, typer.Option("--hole-b", help="Second hole id.")],
    tolerance: Annotated[
        str | None,
        typer.Option("--tolerance", help="document_id:sheet:annotation of the tolerance."),
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Coaxiality of two holes against a tolerance read off a drawing."""
    tolerance_ref = None if tolerance is None else _parse_ref("--tolerance", tolerance)

    with _errors_as_exit_1():
        context = _context_for(package)
    with use_context(context):
        result = checks_fastener.check_hole_alignment(hole_a, hole_b, tolerance_ref)
    _emit_check(result, json_output)


# --- check interference ----------------------------------------------------------


@check_app.command("interference")
def check_interference_command(
    package: PackageOption,
    json_output: JsonFlag = False,
) -> None:
    """Every grouped interference condition in a package, with its retained exceptions.

    Read-only, unlike `exceptions list`: `interference_case` refreshes the store in memory
    so a stale exception is reported as `needs_review` and silences nothing, but neither it
    nor this command writes `exceptions.json` back. Grading a package must not edit it.
    """
    with _errors_as_exit_1():
        case = interference_case(package)

    lines = [f"{len(case['groups'])} interference condition(s)"]
    for group in case["groups"]:
        lines.append("")
        lines.append(
            f"{group['group_key']} ({group['configuration']}): "
            f"detection {group['detection_status']}, "
            f"{len(group['member_interference_ids'])} pair(s)"
        )
        lines += _finding_lines(group["result"])
    lines.append("")
    lines.append(f"{len(case['exceptions'])} exception(s) after refresh")
    lines += [f"  {item['id']} {item['status']} {item['check']}" for item in case["exceptions"]]
    lines.append(f"unresolved coverage: {len(case['unresolved_coverage'])} item(s)")
    for item in case["unresolved_coverage"]:
        error = item["error"]
        lines.append(f"  {item['reason']}" + ("" if error is None else f" ({error})"))
    _emit(case, lines, json_output)


# --- check rms -------------------------------------------------------------------


@check_app.command("rms")
def check_rms_command(
    package: PackageOption,
    out: Annotated[
        Path,
        typer.Option("--out", help="Run directory session.json, report.md and check.json go in."),
    ],
    document: Annotated[
        list[str] | None,
        typer.Option("--document", help="Part document id to grade; repeatable."),
    ] = None,
    scope: Annotated[
        RmsScope, typer.Option("--scope", help="part, assembly, equations, or all.")
    ] = RmsScope.all,
    json_output: JsonFlag = False,
) -> None:
    """Grade a package against the Resilient Modeling rules, without the agent.

    A thin shell around `checks/rms/run.py::run_rms_check`, which is the same entry point
    the Model check tab's `POST /checks/rms` calls (FR-024), so the findings and the
    aggregated coverage printed here are what the tab shows and what a review would
    record - not a second evaluation that could drift from either.

    `--out` is required and is the run folder: `session.json`, `report.md` and `check.json`
    go there, as they do for `review --out`, and the package directory is only read.
    Grading a package must not edit it - the rule `check interference` already holds to -
    and a default write target is how three untracked files ended up inside a golden
    fixture, which is this project's regression baseline.

    Before the rules run, the entry point carries forward the newest `exceptions.json`
    under the run root whose package carries the same `design_id` (`contracts/cli.md`),
    into the run folder. The run root this command names is `--out`'s own parent. A
    candidate is a sibling that is its own package - the pane's check folders are, and so
    is the package itself when `--out` is pointed beside it - so a run folder *this*
    command wrote is never one: it holds `session.json`, `report.md` and `check.json` and
    no `package.json`, and nothing is carried from one command-line run to the next.

    What makes an acceptance survive the next check here is the other half of the rule:
    `swreview exceptions accept-rms` writes `exceptions.json` beside the package, and that
    file is read and refreshed in memory when the run folder carries none, so a waiver
    whose feature tree has moved reads `needs_review` and silences nothing. Neither file
    is ever rewritten.

    Violations are output, not an exit code: this exits 1 only when the package cannot be
    read, its feature array is empty, an argument names something the package does not
    carry, or a carried-forward exception store cannot be parsed.
    """
    document_ids = list(document) if document else None
    out_dir = Path(out).resolve()
    with _errors_as_exit_1():
        run = run_rms_check(
            package,
            out_dir=out_dir,
            scope=scope,
            document_id=document_ids,
            run_root=out_dir.parent,
        )

    payload = {
        "package": str(Path(package).resolve()),
        "out_dir": str(out_dir),
        "session_file": str(run.session_file),
        "report_file": str(run.report_file),
        "check_file": str(run.check_file),
        "scope": scope.value,
        "documents": run.documents,
        "assembly_document": run.assembly_document,
        "findings": run.findings,
        "coverage": run.coverage,
        "unavailable_scopes": run.unavailable_scopes,
    }
    lines = [
        f"{len(run.documents)} part document(s)"
        + (f": {', '.join(run.documents)}" if run.documents else "")
    ]
    if run.assembly_document is not None:
        lines.append(f"root assembly document: {run.assembly_document}")
    for finding in run.findings:
        lines.append("")
        lines += _finding_lines(finding)
    lines.append("")
    lines.append(f"coverage: {_counts_line(_coverage_counts(run.coverage))}")
    lines += [f"scope {item['scope']}: {item['reason']}" for item in run.unavailable_scopes]
    lines.append(f"session: {run.session_file}")
    lines.append(f"report: {run.report_file}")
    _emit(payload, lines, json_output)


def _coverage_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many items landed in each bucket, in the buckets' own order."""
    counts = {bucket: 0 for bucket in get_args(CoverageBucket)}
    for row in rows:
        counts[row["bucket"]] += 1
    return counts


# --- rms types -------------------------------------------------------------------


@rms_app.command("types")
def rms_types_command(
    package: PackageOption,
    json_output: JsonFlag = False,
) -> None:
    """Name the feature type names in a package that the RMS table does not classify.

    Calibration, not grading: `GetTypeName2` returns a string SOLIDWORKS promises nothing
    about, so a name the shipped `rms_types.yaml` does not carry is neither a pass nor a
    fail - it is a hole in the table an engineer closes with evidence. This command is
    that evidence: every unclassified name, how many content features carry it, and which
    documents they are in. It reads the package and writes nothing.
    """
    with _errors_as_exit_1():
        package_ir = load_package(package).package
        rows = unknown_types(package_ir.features)

    payload = {
        "package": str(Path(package).resolve()),
        "types": [
            {
                "type_name": row.type_name,
                "count": row.count,
                "documents": list(row.document_ids),
            }
            for row in rows
        ],
    }
    lines = [f"{len(rows)} type name(s) the table does not classify"]
    lines += [
        f"  {row.type_name} x{row.count}: {', '.join(row.document_ids)}" for row in rows
    ]
    _emit(payload, lines, json_output)


# --- rms suppress-plan -----------------------------------------------------------


@rms_app.command("suppress-plan")
def rms_suppress_plan_command(
    package: PackageOption,
    document: Annotated[
        str, typer.Option("--document", help="Part document id to plan the test for.")
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", help=f"Where to write the plan; default <package>/{PLAN_FILE_NAME}."),
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Write the suppress-test plan for one part document: what `suppress-test` may touch.

    The plan is the reviewer's half of the one mutation path in this product. It names
    the review configuration, the Detail group, and the Detail content features in tree
    order with the persistent reference the extractor resolves each one by, derived from
    `features[]` through the group assigner and the type table - so `swreview-extract
    suppress-test` decides nothing about folders, groups or content, and the rule grades
    exactly the set that was planned.

    Exits 1 when the document has no `features[]` rows (its tree was never dumped, or the
    id names an assembly) or its tree has no Detail group: an empty plan would read as
    "nothing to suppress" rather than "we never looked". A Detail group that holds no
    content feature is a different answer and does write an empty plan.

    It reads the package and writes only the plan file.
    """
    with _errors_as_exit_1():
        package_ir = load_package(package).package
        plan = build_plan(package_ir, document, load_table())
        plan_file = (Path(package) / PLAN_FILE_NAME if out is None else Path(out)).resolve()
        body = plan.as_dict()
        try:
            plan_file.parent.mkdir(parents=True, exist_ok=True)
            plan_file.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            # The path the engineer typed is the thing they can fix, and `strerror` alone
            # does not name it.
            raise OSError(f"cannot write the plan to {plan_file}: {exc}") from exc

    payload = {"package": str(Path(package).resolve()), "out": str(plan_file), **body}
    lines = [
        f"wrote {plan_file}",
        f"{len(plan.features)} {plan.group} feature(s) of {plan.document_id} "
        f"in configuration {plan.configuration}",
    ]
    lines += [
        f"  {item.feature_id} {item.name} [{item.type_name}]" for item in plan.features
    ]
    _emit(payload, lines, json_output)


# --- remodel plan ----------------------------------------------------------------


@remodel_app.command("plan")
def remodel_plan_command(
    package: PackageOption,
    document: Annotated[
        list[str] | None,
        typer.Option("--document", help="Part document id to plan; repeatable."),
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Plan the reorganize stage for a package's part documents, with no SOLIDWORKS.

    The dry run, and the deliverable Phase 0 decides on: per part it prints how many
    content features reach their target group, how many are pinned and by which dependency
    edge, which groups come out non-contiguous and what splits them, and the rebuild list
    with one reason each from the closed taxonomy. The fraction is printed with its
    numerator and its denominator, because stage 1's output is a partition with reasons and
    a bare percentage would read as a score.

    It reads the package and writes nothing - no plan file, no session, no report - and
    constructs no provider: every decision here comes from `rms_types.yaml` and the
    dependency graph, so the same package plans the same way on a machine with no key.

    The scope gate is **unresolved** on every dry run and says so: multibody, weldment,
    sheet metal, mesh and 3D Interconnect are COM readings `remodel.probe_scope` takes from
    the engineer's open document, and a package carries none of them. An unread signal is
    never a pass.

    Exit 1 when a part is refused - a scope signal that refuses it, an existing group-named
    folder holding the wrong members, or a dependency cycle - and the output names every
    reason, not the first. The numbers are printed first: a refused part is still a part
    the owner has numbers for.
    """
    with _errors_as_exit_1():
        package_ir = load_package(package).package
        table = load_table()
        document_ids = part_document_ids(package_ir, list(document) if document else None)
        documents = {row.document_id: row for row in package_ir.documents}
        rows = [
            plan_summary_row(
                plan_reorganize(package_ir, document_id=document_id, table=table),
                documents[document_id],
                table,
            )
            for document_id in document_ids
        ]

    payload = {"package": str(Path(package).resolve()), "parts": rows}
    lines: list[str] = []
    for row in rows:
        lines += plan_lines(row)
    _emit(payload, lines, json_output)
    if any(row["state"] == "failed" for row in rows):
        raise typer.Exit(1)


# --- exceptions accept | list | accept-rms ---------------------------------------


def _store_for(package_dir: Path) -> tuple[ExceptionStore, Any]:
    """The exception store beside a package, and the package itself."""
    loaded = load_package(package_dir)
    store = ExceptionStore(Path(loaded.base_dir) / EXCEPTIONS_FILE_NAME).load()
    return store, loaded.package


def _save_run(run_dir: Path, session: ReviewSession, evidence: EvidencePackage) -> Path:
    """Write `session` back to its run directory, re-render its report, and name the file.

    Both acceptance commands end here. An exception recorded on a finding but not written
    back to `session.json`, or written back without the report being re-rendered, leaves
    one run saying two different things about the same finding.
    """
    resolved = Path(run_dir).resolve()
    save_session(session, resolved / SESSION_FILE_NAME)
    report_file = resolved / REPORT_FILE_NAME
    report_file.write_text(render_report(session, evidence), encoding="utf-8")
    return report_file


@exceptions_app.command("accept")
def exceptions_accept(
    run_dir: Annotated[Path, typer.Argument(help="Directory holding session.json.")],
    finding_id: Annotated[str, typer.Argument(help="Finding id, for example F-001.")],
    package: Annotated[
        Path,
        typer.Option("--package", help="Package directory the finding was reviewed from."),
    ],
    note: Annotated[
        str, typer.Option("--note", help="Why this condition is accepted.")
    ] = "",
    by: Annotated[
        str | None, typer.Option("--by", help="Who accepted it; defaults to the current user.")
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Accept a finding: bind an exception to its components, geometry and configuration.

    The exception is written to `exceptions.json` beside the package, and the finding
    records its id. It silences that condition only while the geometry and configuration
    it was accepted for are unchanged; `exceptions list` shows when that stops being true.
    """
    accepted_by = by if by else _default_user()
    with _errors_as_exit_1():
        session_file = Path(run_dir).resolve() / SESSION_FILE_NAME
        session = load_session(session_file)
        finding = find_finding(session, finding_id)
        store, evidence = _store_for(package)
        exception = store.accept(finding, evidence, by=accepted_by, note=note)
        store.save()
        finding.exception_id = exception.id
        report_file = _save_run(run_dir, session, evidence)

    payload = {
        "run_dir": str(Path(run_dir).resolve()),
        "package_dir": str(Path(package).resolve()),
        "finding_id": finding_id,
        "exceptions_file": str(store.path),
        "report_file": str(report_file),
        "exception": to_jsonable_python(exception),
    }
    lines = [
        f"{exception.id}: {finding_id} ({exception.check}) accepted by {accepted_by} "
        f"for configuration {exception.configuration}",
        f"bound to {len(exception.component_persist_refs)} component(s), "
        f"fingerprint {exception.geometry_fingerprint[:12]}…",
        f"wrote {store.path}",
    ]
    _emit(payload, lines, json_output)


# --- exceptions accept-rms: the checker's flat file as an import ------------------

RMS_WAIVER_UNKNOWN = "invalid (unknown rule)"
"""A listed id that is not a rule of `contracts/rules.md` at all."""

RMS_WAIVER_INVALID: dict[str, str] = {
    "warn": "invalid (warn rule)",
    "unresolved": "invalid (data-gap rule)",
    "out_of_scope": "invalid (out-of-scope rule)",
}
"""Why a known rule cannot be waived, keyed by the rule's own severity when it has one
and by its coverage bucket when it has not.

`contracts/rules.md` ("Waivable rules") names exactly these three kinds - "a waiver naming
a `warn`, data-gap, or out-of-scope rule is reported invalid and changes nothing" - and
each is reported as itself rather than folded into the `warn` label `contracts/cli.md`
abbreviates them to: a waiver for `rms.assembly.mates_described` is refused because the
data is not extracted, and telling an engineer it is a `warn` rule would send them looking
for a severity to argue with."""

_ACCEPTABLE_STATUS = "demonstrated"
"""The one finding status an import accepts. A `suspected` finding is a `warn` rule's and
is not waivable; a `checked_within_scope` one is already waived by an exception, and
accepting it again would write a second exception for one condition.

The status is necessary and not sufficient: a `demonstrated` finding can also be one an
exception already covers - one this command wrote itself on an earlier run, which re-reads
the session it wrote back and finds it still `demonstrated` because only a fresh
`check rms` reclassifies a finding, or one the store holds as `needs_review`. `_uncovered`
is what decides between them."""


def _rms_waiver_invalidity(rule_id: str) -> str | None:
    """Why `rule_id` cannot be waived, or `None` when it is a waivable `fail` rule."""
    rule = RULES.get(rule_id)
    if rule is None:
        return RMS_WAIVER_UNKNOWN
    if rule.severity == "fail":
        return None
    key = rule.severity if rule.coverage is None else rule.coverage[0]
    return RMS_WAIVER_INVALID[key]


def _flat_waivers(path: Path) -> dict[str, str]:
    """The checker's `{ "<rule_id>": "<reason>" }` file, refusing every other shape.

    A waiver with no reason is refused rather than accepted with an empty note: an
    unexplained exception is the blanket exclusion the constitution (Principle VI) does
    not allow, and a note is the one thing the file carries that the run cannot derive.
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(
            f"{path}: the waiver file is a JSON object of rule id to reason, not a "
            f"{type(document).__name__}"
        )
    unexplained = sorted(
        key
        for key, value in document.items()
        if not isinstance(value, str) or not value.strip()
    )
    if unexplained:
        raise ValueError(
            f"{path}: every waiver states why it is accepted; "
            f"{', '.join(unexplained)} state(s) nothing"
        )
    return document


def _uncovered(
    store: ExceptionStore, evidence: EvidencePackage, findings: Iterable[Finding]
) -> list[tuple[Finding, ReviewException | None]]:
    """The findings this import still has something to do about, each with the retained
    exception for its condition when there is one.

    A finding an `active` exception already covers is dropped rather than accepted again:
    the store was refreshed against this package, so `active` means that record still
    binds, and a second record for one condition would be unreachable as well as untrue -
    `ExceptionStore.match` returns the first non-retired match, so everything written
    after it is dead. A `needs_review` one is kept, because that is the exception whose
    finding the run reports as standing: re-binding it is the only thing that clears it.
    """
    pending: list[tuple[Finding, ReviewException | None]] = []
    for finding in findings:
        retained = store.match(
            evidence, finding.component_ids, finding.configuration, check=finding.check
        )
        if retained is not None and retained.status == "active":
            continue
        pending.append((finding, retained))
    return pending


def _accept_or_reaccept(
    store: ExceptionStore,
    evidence: EvidencePackage,
    finding: Finding,
    retained: ReviewException | None,
    *,
    by: str,
    note: str,
) -> ReviewException:
    """The exception covering `finding` after the import: a new one, or `retained` re-bound.

    Re-accepting rewrites the acceptor, the date and the note as well as the digest. The
    tree the flagged record was accepted for is not the tree that is here, so the person
    running this import is accepting something the original acceptor never saw, and a
    fresh fingerprint under their name and their reason would say otherwise.
    """
    if retained is None:
        return store.accept(finding, evidence, by=by, note=note)
    exception = store.reaccept(retained.id, evidence)
    exception.accepted_by = by
    exception.accepted_at = datetime.now(UTC)
    exception.note = note
    return exception


@exceptions_app.command("accept-rms")
def exceptions_accept_rms(
    run_dir: Annotated[Path, typer.Argument(help="Directory holding session.json.")],
    package: Annotated[
        Path,
        typer.Option("--package", help="Package directory the run was graded from."),
    ],
    file: Annotated[
        Path,
        typer.Option("--file", help="The checker's flat waiver file: rule id to reason."),
    ],
    by: Annotated[
        str | None, typer.Option("--by", help="Who accepted them; defaults to the current user.")
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Import the checker's flat waiver file against one `check rms` run.

    The file is an import and never a store: `{ "<rule_id>": "<reason>" }` says nothing
    about which condition was accepted, and keeping it would silence its rules on every
    document forever. Read against a run it says enough - every `demonstrated` finding of
    a listed `fail` rule becomes one exception bound to that finding's components, its
    configuration and a feature-tree fingerprint, with the reason as the note - and the
    exceptions are what is kept.

    A condition one exception already covers never gets a second. The store is refreshed
    against the package first, exactly as the run that produced the session was graded, so
    an `active` exception means the condition is covered and its finding is reported
    `unused`; a `needs_review` one - the tree it was accepted for has moved, which is why
    its finding still stands - is re-bound to the tree that is here rather than duplicated,
    and counts as accepted, because that is what clears the finding. An import that writes
    writes that refreshed store, as `exceptions list` does: a waiver the package has
    outgrown is recorded `needs_review` rather than left reading `active` on disk.

    Per listed id one status is reported, in the file's order: `accepted <n>`,
    `unused` (the rule left this import nothing to do - it passed, it never ran, or every
    finding it reported is already covered), or invalid. An invalid id refuses the whole
    import: the statuses are printed, exit is 1, and nothing is written, so the ids that
    would have been accepted read `would accept <n>` rather than claiming an acceptance
    that did not happen. A half-applied import is worse than a refused one.
    """
    accepted_by = by if by else _default_user()
    with _errors_as_exit_1():
        waivers = _flat_waivers(file)
        session = load_session(Path(run_dir).resolve() / SESSION_FILE_NAME)
        store, evidence = _store_for(package)
        store.refresh(evidence)

    plan: list[tuple[str, str, str | None, list[tuple[Finding, ReviewException | None]]]] = []
    for rule_id, reason in waivers.items():
        invalidity = _rms_waiver_invalidity(rule_id)
        pending = (
            []
            if invalidity is not None
            else _uncovered(
                store,
                evidence,
                [
                    finding
                    for finding in session.findings
                    if finding.check == rule_id and finding.status == _ACCEPTABLE_STATUS
                ],
            )
        )
        plan.append((rule_id, reason, invalidity, pending))

    refused = [
        (rule_id, invalidity)
        for rule_id, _, invalidity, _ in plan
        if invalidity is not None
    ]
    accepted: dict[str, list[ReviewException]] = {rule_id: [] for rule_id, *_ in plan}
    report_file: Path | None = None
    if not refused:
        with _errors_as_exit_1():
            for rule_id, reason, _, findings in plan:
                for finding, retained in findings:
                    exception = _accept_or_reaccept(
                        store, evidence, finding, retained, by=accepted_by, note=reason
                    )
                    finding.exception_id = exception.id
                    accepted[rule_id].append(exception)
            if any(accepted.values()):
                store.save()
                report_file = _save_run(run_dir, session, evidence)

    rules = [
        {
            "rule_id": rule_id,
            "reason": reason,
            "status": _rms_waiver_status(invalidity, len(findings), refused=bool(refused)),
            "count": len(findings),
            "finding_ids": [finding.id for finding, _ in findings],
            "exception_ids": [exception.id for exception in accepted[rule_id]],
        }
        for rule_id, reason, invalidity, findings in plan
    ]
    payload = {
        "run_dir": str(Path(run_dir).resolve()),
        "package_dir": str(Path(package).resolve()),
        "waiver_file": str(Path(file).resolve()),
        "accepted_by": accepted_by,
        "exceptions_file": str(store.path),
        "report_file": None if report_file is None else str(report_file),
        "rules": rules,
        "exceptions": [
            to_jsonable_python(exception)
            for exceptions in accepted.values()
            for exception in exceptions
        ],
    }
    lines = [f"{row['rule_id']}: {row['status']}" for row in rules]
    if refused:
        lines.append(f"nothing written: {len(refused)} invalid rule id(s)")
    elif report_file is None:
        lines.append("nothing written: no listed rule left this import a finding to accept")
    else:
        lines.append(f"wrote {store.path}")
    _emit(payload, lines, json_output)

    if refused:
        typer.echo(
            "error: nothing was written; "
            + ", ".join(f"{rule_id} is {why}" for rule_id, why in refused),
            err=True,
        )
        raise typer.Exit(1)


def _rms_waiver_status(invalidity: str | None, count: int, *, refused: bool) -> str:
    """One listed id's status: why it is invalid, or what happened to its findings."""
    if invalidity is not None:
        return invalidity
    if count == 0:
        return "unused"
    return f"would accept {count}" if refused else f"accepted {count}"


@exceptions_app.command("list")
def exceptions_list(
    package_dir: Annotated[Path, typer.Argument(help="Directory holding package.json.")],
    json_output: JsonFlag = False,
) -> None:
    """Show the exceptions retained for a package, re-checked against its geometry.

    Every `active` exception is re-checked against the package as it stands now: one whose
    components, geometry or configuration have moved comes back `needs_review` and no
    longer silences anything (FR-013). Nothing here ever returns an exception to `active`;
    only an engineer does that.
    """
    with _errors_as_exit_1():
        store, package = _store_for(package_dir)
        flagged = store.refresh(package)
        if flagged:
            store.save()

    counts = {
        status: sum(1 for item in store.exceptions if item.status == status)
        for status in ("active", "needs_review", "retired")
    }
    payload = {
        "package_dir": str(Path(package_dir).resolve()),
        "exceptions_file": str(store.path),
        "configuration": package.design.active_configuration,
        "counts": counts,
        "flagged_now": [item.id for item in flagged],
        "exceptions": [to_jsonable_python(item) for item in store.exceptions],
    }
    lines = [
        f"{len(store.exceptions)} exception(s) in {store.path}",
        _counts_line(counts),
    ]
    lines += [
        f"  {item.id} {item.status} {item.check} ({item.configuration}) "
        f"by {item.accepted_by}: {item.note}"
        for item in store.exceptions
    ]
    if flagged:
        lines.append(
            "needs review now: "
            + ", ".join(item.id for item in flagged)
            + " - the geometry or configuration they were accepted for has changed"
        )
    _emit(payload, lines, json_output)


# --- benchmark -------------------------------------------------------------------


def _review_fn(
    package_dir: Path,
    session_out_dir: Path,
    *,
    provider: str,
    model: str,
    effort: str,
    efficiency: EfficiencySettings | None = None,
) -> Any:
    """One package of a benchmark set, reviewed through the same hooks as `review`.

    A fresh adapter per package on purpose: adapters carry per-turn state (step indices,
    a client), and a set of twenty packages sharing one would interleave their traces.

    The redaction is per package too, rather than left to `benchmark_run`: a library
    caller that reaches this through `benchmark.runner`'s default `review_fn` gets the
    same guarantee as one that came through the command line (FR-015).
    """
    settings = ProviderSettings.from_env(provider=provider, model=model, effort=effort)
    with _redacting(settings) as redactor:
        return run_review(
            package_dir,
            session_out_dir,
            provider=provider_factory(settings, efficiency),
            model=settings.model,
            effort=settings.effort,
            key_source=settings.key_source,
            efficiency=efficiency,
            redact=redactor,
        )


def _refuse_a_set_too_small_to_gate(benchmark_set: BenchmarkSet, override: bool) -> None:
    """Precondition P-3: a study gated on a set with no held-out package decides nothing.

    One package with two known defects and no geometry means one lost defect is a 50
    percent regression and `recall` never computes at all (`scorecard.py:200-204`), so
    this is a refusal rather than a warning. `--i-know-the-set-is-too-small` is accepted
    for a smoke test and is recorded in the run's provenance, so the row it produces can
    never be read as a gate.

    It applies to a run that declares itself part of a study - one that typed `--lever`,
    `--study` or `--arm`. A plain `benchmark run` over a small set is a smoke test and is
    not held to a gate's precondition; it produces no arm and gates nothing.
    """
    if override or any(ref.held_out for ref in benchmark_set.packages):
        return
    raise typer.BadParameter(
        f"benchmark set {benchmark_set.name!r} holds no held_out: true package, so recall "
        f"never computes and this study can gate nothing; pass "
        f"--i-know-the-set-is-too-small for a smoke test, which is recorded with the run"
    )


@benchmark_app.command("run")
def benchmark_run(
    set_file: Annotated[Path, typer.Option("--set", help="Benchmark set JSON.")],
    out: Annotated[
        Path, typer.Option("--out", help="Run directory; one subdirectory per package.")
    ],
    provider: ProviderOption = DEFAULT_PROVIDER,
    model: ModelOption = None,
    effort: EffortOption = DEFAULT_EFFORT_CHOICE,
    lever: LeverOption = None,
    study: Annotated[
        str,
        typer.Option("--study", help="The lever this run is an arm of, or none."),
    ] = NO_STUDY,
    arm: Annotated[
        str | None,
        typer.Option("--arm", help="Which arm of the study this run is: off, on or baseline."),
    ] = None,
    rep: Annotated[
        int | None,
        typer.Option("--rep", min=1, help="Which repetition of this arm the run is."),
    ] = None,
    set_too_small_override: Annotated[
        bool,
        typer.Option(
            "--i-know-the-set-is-too-small",
            help="Run a study over a set with no held-out package; recorded with the run.",
        ),
    ] = False,
    json_output: JsonFlag = False,
) -> None:
    """Review every package in the set, with answer keys unreadable."""
    declares_a_study = bool(lever) or study != NO_STUDY or arm is not None
    efficiency = _efficiency(
        lever,
        provider=provider,
        study=study,
        arm=arm,
        allow_workstation_levers=False,
    )
    with _errors_as_exit_1():
        benchmark_set = load_set(set_file)
        if declares_a_study:
            _refuse_a_set_too_small_to_gate(benchmark_set, set_too_small_override)
        settings = _provider_settings(provider, model, effort)
        started_at = datetime.now(UTC)
        with _redacting(settings):
            package_dirs = run_benchmark(
                set_file,
                out,
                provider=settings.provider.value,
                model=settings.model,
                effort=settings.effort,
                review_fn=_review_fn,
                efficiency=efficiency,
            )
        saved_set = Path(out).resolve() / SAVED_SET_FILE
        saved_set.write_text(benchmark_set.model_dump_json(indent=2) + "\n", encoding="utf-8")
        provenance_file = write_provenance(
            Path(out).resolve(),
            RunProvenance(
                commit=current_commit(),
                lever=study,
                arm=arm,
                rep=rep,
                provider=settings.provider.value,
                model=settings.model,
                effort=settings.effort,
                max_steps=DEFAULT_MAX_STEPS,
                checklist_digest=sha256_of(CHECKLIST_FILE),
                set_digest=sha256_of(saved_set),
                started_at=started_at,
                set_too_small_override=set_too_small_override,
                efficiency=efficiency,
            ),
        )

    payload = {
        "set": str(Path(set_file).resolve()),
        "benchmark_set": benchmark_set.name,
        "out_dir": str(Path(out).resolve()),
        "saved_set_file": str(saved_set),
        "provenance_file": str(provenance_file),
        "provider": settings.provider.value,
        "model": settings.model,
        "packages": [
            {"package_id": ref.package_id, "out_dir": str(directory)}
            for ref, directory in zip(benchmark_set.packages, package_dirs, strict=True)
        ],
    }
    lines = [f"reviewed {len(package_dirs)} packages of set {benchmark_set.name} into {out}"]
    lines += [f"  {ref.package_id}" for ref in benchmark_set.packages]
    _emit(payload, lines, json_output)


def _benchmark_set_for(run_dir: Path, set_file: Path | None) -> BenchmarkSet:
    """The set a run was made from: `--set` if given, else the copy the run saved."""
    path = Path(set_file) if set_file is not None else Path(run_dir) / SAVED_SET_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"no benchmark set to score against at {path}: pass --set, or score a run made "
            f"by `swreview benchmark run`, which saves {SAVED_SET_FILE} in the run directory"
        )
    return load_set(path)


@benchmark_app.command("score")
def benchmark_score(
    run_dir: Annotated[Path, typer.Argument(help="A benchmark run directory.")],
    answer_keys: Annotated[
        Path, typer.Option("--answer-keys", help="Directory of answer keys.")
    ],
    set_file: Annotated[
        Path | None,
        typer.Option("--set", help="Benchmark set JSON; default: the copy the run saved."),
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Score a run against its answer keys; write scorecard.json and scorecard.md."""
    with _errors_as_exit_1():
        benchmark_set = _benchmark_set_for(run_dir, set_file)
        scorecard = score_run(run_dir, answer_keys, benchmark_set)
        scorecard_json = Path(run_dir).resolve() / "scorecard.json"
        scorecard_md = Path(run_dir).resolve() / "scorecard.md"
        scorecard_json.write_text(scorecard.model_dump_json(indent=2) + "\n", encoding="utf-8")
        scorecard_md.write_text(render_scorecard_md(scorecard), encoding="utf-8")

    aggregate = scorecard.aggregate
    payload = {
        "run_dir": str(Path(run_dir).resolve()),
        "benchmark_set": scorecard.benchmark_set,
        "scorecard_file": str(scorecard_json),
        "scorecard_md_file": str(scorecard_md),
        "aggregate": to_jsonable_python(aggregate),
    }
    lines = [
        f"scored {aggregate.packages} packages of set {scorecard.benchmark_set}",
        f"valid findings: {aggregate.valid_findings}, missed: {aggregate.missed_known_defects}, "
        f"false alarms: {aggregate.false_alarms}, unresolved: {aggregate.unresolved_count}",
        f"wrote {scorecard_json} and {scorecard_md}",
    ]
    _emit(payload, lines, json_output)


@benchmark_app.command("time")
def benchmark_time(
    run_dir: Annotated[Path, typer.Argument(help="A benchmark run directory.")],
    package_id: Annotated[str, typer.Argument(help="Which package of the run.")],
    baseline: Annotated[
        float | None, typer.Option("--baseline", help="Unassisted review minutes.")
    ] = None,
    supervision: Annotated[
        float | None, typer.Option("--supervision", help="Minutes spent supervising the run.")
    ] = None,
    verification: Annotated[
        float | None, typer.Option("--verification", help="Minutes spent verifying findings.")
    ] = None,
    false_alarms: Annotated[
        float | None, typer.Option("--false-alarms", help="Minutes spent on false alarms.")
    ] = None,
    json_output: JsonFlag = False,
) -> None:
    """Record human timing against one package of a run, for net-savings computation."""
    with _errors_as_exit_1():
        timing = record_timing(
            run_dir,
            package_id,
            baseline=baseline,
            supervision=supervision,
            verification=verification,
            false_alarms=false_alarms,
        )

    payload = {
        "run_dir": str(Path(run_dir).resolve()),
        "package_id": package_id,
        "timing": to_jsonable_python(timing),
    }
    lines = [
        f"{package_id}: baseline {timing.baseline_minutes}, "
        f"supervision {timing.assisted_supervision_minutes}, "
        f"verification {timing.assisted_verification_minutes}, "
        f"false alarms {timing.false_alarm_handling_minutes}",
        f"net saved: {timing.net_saved_minutes}",
    ]
    _emit(payload, lines, json_output)


@benchmark_app.command("compare")
def benchmark_compare(
    run_dirs: Annotated[
        list[Path] | None,
        typer.Argument(
            help="The run directories of one or more studies; none renders an empty ledger."
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write ledger.json and ledger.md into this directory."),
    ] = None,
    into: Annotated[
        Path | None,
        typer.Option("--into", help="Markdown file whose ledger section is regenerated."),
    ] = None,
    check: Annotated[
        bool,
        typer.Option("--check", help="With --into: verify it is current, write nothing."),
    ] = False,
    json_output: JsonFlag = False,
) -> None:
    """Render the results ledger from scored run directories; contacts no provider.

    Two exits are not the same thing. A **refused run** - two records that disagree, a
    session with no `efficiency`, two runs of one study at different commits - stops the
    whole ledger, because such a run may not be placed in a comparison at all. A
    **refused decision row** (FR-029, SC-011) still writes the ledger with the raw rows
    in it and exits 1, because the runs are real and only the gate is unreadable.

    The owner's `Owner signed off` and `Owner signed off at` cells are read back off the
    ledger this invocation is about to overwrite and re-rendered unchanged, so a
    hand-written sign-off survives regeneration and does not read as drift (FR-027).
    """
    with _errors_as_exit_1():
        ledger = carry_sign_offs(
            compare_runs(run_dirs or []), *committed_sign_off_sources(out, into)
        )
        rendered = render_ledger_md(ledger)
        written: list[str] = []
        if out is not None:
            written += [str(path) for path in write_ledger(ledger, out)]
        drifted = False
        if into is not None:
            current = Path(into).read_text(encoding="utf-8")
            spliced = splice_ledger(current, rendered)
            if check:
                drifted = spliced != current
            elif spliced != current:
                Path(into).write_text(spliced, encoding="utf-8")
                written.append(str(Path(into).resolve()))

    refused = refused_decisions(ledger)
    payload = {
        "runs": len(ledger.runs),
        "levers": len(ledger.levers),
        "written": written,
        "refused_decisions": [
            {"lever": row.lever, "reason": row.decision_reason} for row in refused
        ],
        "drifted": drifted,
    }
    lines = [f"compared {len(ledger.runs)} run rows over {len(ledger.levers)} studies"]
    lines += [f"wrote {path}" for path in written]
    lines += [f"no decision for {row.lever}: {row.decision_reason}" for row in refused]
    if drifted:
        lines.append(f"{into} is out of date: re-run without --check to regenerate it")
    _emit(payload, lines, json_output)
    if refused or drifted:
        raise typer.Exit(1)


# --- chat serve ------------------------------------------------------------------


@chat_app.command("serve")
def chat_serve(
    port: Annotated[
        int, typer.Option("--port", help="TCP port; 0 lets the OS pick a free one.")
    ] = 0,
    allow_origin: Annotated[
        str, typer.Option("--allow-origin", help="The page origin allowed to call it.")
    ] = DEFAULT_ALLOW_ORIGIN,
    run_root: Annotated[
        Path | None,
        typer.Option("--run-root", help="Run folders live here; a run_dir must be inside it."),
    ] = None,
    fail_bridge: Annotated[
        int,
        typer.Option("--fail-bridge", help="Force the first N bridge calls to fail; test hook."),
    ] = 0,
    dev: Annotated[
        bool, typer.Option("--dev", help="Development build: offer the scripted provider.")
    ] = False,
) -> None:
    """Serve the Task Pane chat backend on 127.0.0.1 and print `{port, token}` once.

    The first line on stdout is the handshake and nothing else is ever printed there; the
    add-in reads it to reach the backend (`contracts/chat-api.md`). Everything this command
    does lives in `swreview.chat.__main__`, which `python -m swreview.chat` runs with the
    same arguments - one implementation, two ways in.

    The import is deliberately inside the function: `starlette`, `uvicorn` and the chat
    backend are not loaded by `swreview review` or by any check command.
    """
    from swreview.chat.__main__ import serve

    serve(
        port=port,
        allow_origin=allow_origin,
        run_root=run_root if run_root is not None else DEFAULT_RUN_ROOT,
        fail_bridge=fail_bridge,
        development=dev,
    )


# --- mcp ---------------------------------------------------------------------------


@app.command("mcp")
def mcp_server(
    run_dir: Annotated[
        Path,
        typer.Option("--run-dir", help="The run folder whose package the tools read."),
    ],
    bridge_pipe: Annotated[
        str | None,
        typer.Option("--bridge-pipe", help="Tool service pipe; without one, no bridge tools."),
    ] = None,
    bridge_secret_env: Annotated[
        str | None,
        typer.Option(
            "--bridge-secret-env",
            help="Environment variable holding the general-chat bridge secret.",
        ),
    ] = None,
) -> None:
    """Serve the read-only general-chat toolset on stdio (`contracts/mcp-toolset.md`).

    This is the command the generated CLI profiles start, and the only spelling of it:
    there is no `swreview.mcp.__main__`, so `-m swreview.mcp` is not a thing
    (`contracts/cli-profiles.md`).

    The bridge secret is named, never given: a value on a command line is visible to every
    process on the workstation, so the add-in puts it in the child's environment block and
    passes the variable's name here.

    stdout is the MCP transport, so this command prints nothing of its own; a failure to
    start is one line on stderr and exit 1.
    """
    from swreview.mcp import server as mcp

    with _errors_as_exit_1():
        secret = mcp.resolve_bridge_secret(bridge_secret_env)
        mcp.serve(run_dir, bridge_pipe=bridge_pipe, bridge_secret=secret)


# --- audit-secrets ----------------------------------------------------------------


KEY_ENV_VARS: tuple[str, ...] = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
"""Every variable a provider key can be configured in - all of them, deliberately.

`ProviderSettings.from_env` resolves `GOOGLE_API_KEY` ahead of `GEMINI_API_KEY` because a
run needs exactly one key; an audit wants the opposite, so this list is not built from
that precedence. A key sitting in the variable the last run did not pick is still a key
that must not be in a file.
"""

KEY_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shape:openai-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("shape:google-key", re.compile(r"AIza[A-Za-z0-9_-]{35}")),
)
"""What a provider key looks like, for the run this command was made for.

On the workstation the key is DPAPI-protected under `%APPDATA%` and is decrypted into the
backend child's environment block only, so an audit started from a separate shell has no
key to search for and an environment-only scan would report "none" no matter what is in
the files. These two patterns are what carry the check there: `sk-` plus at least twenty
key characters covers both OpenAI key formats, and `AIza` plus thirty-five is the shape
Google issues. They are a safety net over the verbatim search, not a replacement for it -
a key from a settings file this shell cannot see has no verbatim value to match.
"""


def _secret_env_names(bridge_secret_env: str | None) -> list[str]:
    """The variables this audit reads a secret from: the key ones, plus the bridge one.

    The bridge secret is named by its variable rather than passed as a value because a
    secret on a command line is visible in the process list.
    """
    names = [*KEY_ENV_VARS]
    if bridge_secret_env is not None and bridge_secret_env not in names:
        names.append(bridge_secret_env)
    return names


def _configured_secrets(bridge_secret_env: str | None) -> list[tuple[str, str]]:
    """`(source, value)` for every secret this shell actually holds.

    A variable that is set but blank is not a secret - that is the common Windows case,
    and treating `""` as a value would both match every line of every file and make a
    vacuous run look armed.
    """
    found = []
    for name in _secret_env_names(bridge_secret_env):
        value = os.environ.get(name, "").strip()
        if value:
            found.append((f"env:{name}", value))
    return found


def _files_under(paths: Sequence[Path]) -> list[Path]:
    """Every file under each argument, de-duplicated and in a stable order.

    A file given directly is itself, so a single log can be audited without its folder.

    Raises:
        FileNotFoundError: naming the argument that is neither a file nor a directory.
    """
    files: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved.is_file():
            files.append(resolved)
            continue
        if not resolved.is_dir():
            raise FileNotFoundError(f"{path} is not a file or a directory")
        files.extend(sorted(child for child in resolved.rglob("*") if child.is_file()))
    return list(dict.fromkeys(files))


def _scan_file(
    path: Path,
    secrets: Sequence[tuple[str, str]],
    shapes: Sequence[tuple[str, re.Pattern[str]]],
) -> list[dict[str, Any]]:
    """Every hit in one file, as `{file, line, source}`; the value itself is never kept.

    Read a line at a time and decoded leniently: a run folder holds screenshots and a log
    folder holds whatever a crash wrote, and one byte that is not UTF-8 is no reason to
    stop looking at the rest of the file. A secret never spans a newline, so a line is a
    safe unit and keeps the whole of a long `events.jsonl` out of memory.

    Raises:
        OSError: if the file cannot be opened or read; the caller reports it as coverage
            the audit does not have rather than skipping it.
    """
    hits: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            for source, value in secrets:
                if value in line:
                    hits.append({"file": str(path), "line": number, "source": source})
            for source, pattern in shapes:
                if pattern.search(line):
                    hits.append({"file": str(path), "line": number, "source": source})
    return hits


@app.command("audit-secrets")
def audit_secrets(
    paths: Annotated[
        list[Path], typer.Argument(help="Directories (or single files) to scan, recursively.")
    ],
    bridge_secret_env: Annotated[
        str | None,
        typer.Option("--bridge-secret-env", help="Variable name holding the bridge secret."),
    ] = None,
    detectors: Annotated[
        bool,
        typer.Option("--detectors/--no-detectors", help="Also flag provider-shaped keys."),
    ] = True,
    json_output: JsonFlag = False,
) -> None:
    """Report any configured secret that reached a file under `paths` (FR-015).

    Exit 1 and name the file and line for every hit, exit 0 when there is none, and exit 1
    without scanning anything when the command has *nothing to detect with* - no key in
    the environment, no bridge secret, and `--no-detectors`. That last case is the one
    worth being loud about: a green "none" from a run that never had a value to search for
    says only that it did not look, and the quickstart reads it as proof that the key
    stayed out of the run folder.

    A file that cannot be read is reported and exits 1 for the same reason: it is coverage
    the audit does not have, and reporting "none" over it is the false green the whole
    command exists to prevent.

    Neither the secret nor the line it was found on is ever printed. The output names the
    variable or the pattern that matched, which is what an engineer needs to go and fix it,
    and nothing that copies the leak into a terminal history or a CI log.
    """
    with _errors_as_exit_1():
        secrets = _configured_secrets(bridge_secret_env)
        shapes = KEY_SHAPES if detectors else ()
        if not secrets and not shapes:
            searched = ", ".join(_secret_env_names(bridge_secret_env))
            raise ValueError(
                f"nothing to detect with: none of {searched} is set and --no-detectors was "
                "given, so this scan could only report what it did not look for"
            )
        files = _files_under(paths)
        leaks: list[dict[str, Any]] = []
        unreadable: list[str] = []
        for file in files:
            try:
                leaks.extend(_scan_file(file, secrets, shapes))
            except OSError:
                unreadable.append(str(file))

    sources = [source for source, _ in secrets] + [source for source, _ in shapes]
    payload = {
        "paths": [str(path.resolve()) for path in paths],
        "sources": sources,
        "files_scanned": len(files),
        "leaks": leaks,
        "unreadable": unreadable,
    }
    lines = [f"{leak['file']}:{leak['line']}: {leak['source']}" for leak in leaks]
    lines += [f"could not read {path}" for path in unreadable]
    if not lines:
        lines = [
            f"none: no configured secret appears in {len(files)} files "
            f"(sources: {', '.join(sources)})"
        ]
    _emit(payload, lines, json_output)
    if leaks or unreadable:
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
