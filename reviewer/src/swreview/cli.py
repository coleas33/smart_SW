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
(`ingest`, `agent.runner`, `report`, `tools`, `benchmark`). Two hooks make it testable
without a network: `provider_factory`, which turns the resolved `ProviderSettings` into
the one adapter a run talks to, and `_review_fn`, the per-package review the benchmark
runner calls.

`provider_factory` is also the only place in the product that constructs a provider SDK
client, and it is the reason `--provider`/`--model`/`--effort` mean the same thing to
`review` and to `benchmark run`: both resolve their flags through
`ProviderSettings.from_env`, so the model default is the per-provider one from
`agent/settings.py` and the key comes from the same place with the same precedence.

Sub-apps (`check`, `benchmark`, `exceptions`) are the extension points: one command per
deterministic check under `check_app`, and the two retained-exception commands under
`exceptions_app`.
"""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from swreview.agent import providers
from swreview.agent.checklist import load_checklist
from swreview.agent.providers import AgentProvider, EffortLevel, ProviderName
from swreview.agent.providers.fake import ScriptedToolCall, ScriptedTurn
from swreview.agent.runner import DEFAULT_MAX_STEPS, SESSION_FILE_NAME, run_review
from swreview.agent.settings import (
    DEFAULT_EFFORT,
    DEFAULT_PROVIDER,
    ProviderSettings,
    configure_logging_redaction,
    output_ceiling,
    redact,
)
from swreview.benchmark.runner import run_benchmark
from swreview.benchmark.scorecard import render_scorecard_md, score_run
from swreview.benchmark.sets import BenchmarkSet, load_set
from swreview.benchmark.timing import record_timing
from swreview.checks.golden_interference import interference_case
from swreview.exceptions import EXCEPTIONS_FILE_NAME, ExceptionStore
from swreview.ingest.package_builder import build_package
from swreview.ir.loader import AnswerKeyAccessError, load_package
from swreview.ir.models import UnsupportedSchemaVersionError
from swreview.ir.summary import summarize
from swreview.report.dispositions import REPORT_FILE_NAME, apply_disposition, find_finding
from swreview.report.markdown import render_report
from swreview.report.session import load_session, save_session
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
    help="Retained exceptions: accept a finding, list what is active.",
)
app.add_typer(check_app, name="check")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(exceptions_app, name="exceptions")

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
    FileNotFoundError,
    NotImplementedError,
    KeyError,
    ValueError,
    LookupError,
)
"""Everything the library raises for input it can describe. Each becomes exit 1 and one
line on stderr; anything else is a bug and keeps its traceback."""

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


# --- the provider one run talks to -----------------------------------------------


def provider_factory(settings: ProviderSettings) -> AgentProvider:
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
    """
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
    return adapter(model=settings.model, **settings.client_kwargs())


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
    json_output: JsonFlag = False,
) -> None:
    """Run the agent loop over a package; write session.json and report.md."""
    with _errors_as_exit_1():
        settings = _provider_settings(provider, model, effort)
        with _redacting(settings) as redactor:
            session = run_review(
                package_dir,
                out,
                provider=provider_factory(settings),
                model=settings.model,
                effort=settings.effort,
                key_source=settings.key_source,
                max_steps=max_steps,
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


def _context_for(package_dir: Path) -> ToolContext:
    """A tool context over the package in `package_dir`, with a session nothing saves."""
    return build_context(load_package(package_dir))


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


# --- exceptions accept | list ----------------------------------------------------


def _store_for(package_dir: Path) -> tuple[ExceptionStore, Any]:
    """The exception store beside a package, and the package itself."""
    loaded = load_package(package_dir)
    store = ExceptionStore(Path(loaded.base_dir) / EXCEPTIONS_FILE_NAME).load()
    return store, loaded.package


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
        save_session(session, session_file)
        report_file = Path(run_dir).resolve() / REPORT_FILE_NAME
        report_file.write_text(render_report(session, evidence), encoding="utf-8")

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
    package_dir: Path, session_out_dir: Path, *, provider: str, model: str, effort: str
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
            provider=provider_factory(settings),
            model=settings.model,
            effort=settings.effort,
            key_source=settings.key_source,
            redact=redactor,
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
    json_output: JsonFlag = False,
) -> None:
    """Review every package in the set, with answer keys unreadable."""
    with _errors_as_exit_1():
        benchmark_set = load_set(set_file)
        settings = _provider_settings(provider, model, effort)
        with _redacting(settings):
            package_dirs = run_benchmark(
                set_file,
                out,
                provider=settings.provider.value,
                model=settings.model,
                effort=settings.effort,
                review_fn=_review_fn,
            )
        saved_set = Path(out).resolve() / SAVED_SET_FILE
        saved_set.write_text(benchmark_set.model_dump_json(indent=2) + "\n", encoding="utf-8")

    payload = {
        "set": str(Path(set_file).resolve()),
        "benchmark_set": benchmark_set.name,
        "out_dir": str(Path(out).resolve()),
        "saved_set_file": str(saved_set),
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


if __name__ == "__main__":  # pragma: no cover
    app()
