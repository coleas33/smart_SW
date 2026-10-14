"""Offline command boundary for engineer-owned sidecars."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from swreview.engineering_context import workflow
from swreview.ir.loader import AnswerKeyAccessError

app = typer.Typer(no_args_is_help=True, help="Engineering context for saved CAD evidence.")
Store = Annotated[
    Path, typer.Option("--store", help="Private sidecar directory outside CAD sources.")
]
Id = Annotated[str, typer.Option("--id", help="Stable record ID; repeat to edit.")]
Kind = Annotated[str, typer.Option("--kind", help="document, component or face.")]
Entity = Annotated[str, typer.Option("--entity", help="Exact entity ID in package.json.")]
Head = Annotated[
    str, typer.Option("--expected-head", help="Digest from the latest init/show result.")
]
Json = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]
Component = Annotated[str | None, typer.Option("--component", help="Owning occurrence for a face.")]
Provenance = Annotated[str, typer.Option("--provenance", help="engineer or ai_proposal.")]
Assumptions = Annotated[
    list[str] | None, typer.Option("--assumption", help="Repeatable assumption.")
]


@contextmanager
def _errors():
    try:
        yield
    except AnswerKeyAccessError as exc:
        typer.echo("context: withheld benchmark data cannot be used as evidence", err=True)
        raise typer.Exit(1) from exc
    except ValidationError as exc:
        typer.echo("context: invalid engineering input; check field types and units", err=True)
        raise typer.Exit(1) from exc
    except OSError as exc:
        typer.echo("context: unable to access the requested file or directory", err=True)
        raise typer.Exit(1) from exc
    except (ValueError, LookupError) as exc:
        typer.echo(f"context: {str(exc)[:400]}", err=True)
        raise typer.Exit(1) from exc


def _emit(payload: dict, json_output: bool):
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=None if json_output else 2))


def _vector(value: str | None) -> tuple[float, float, float] | None:
    if value is None:
        return None
    parts = value.split(",")
    if len(parts) != 3:
        raise ValueError("vector must have three comma-separated numeric values")
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError as exc:
        raise ValueError("vector must have three comma-separated numeric values") from exc


@app.command()
def init(package_dir: Path, store: Store, json_output: Json = False):
    """Initialize context against the exact saved extraction."""
    with _errors():
        _emit(workflow.publication(workflow.initialize(package_dir, store)), json_output)


@app.command()
def requirement(
    package_dir: Path,
    store: Store,
    record_id: Id,
    kind: Kind,
    entity_id: Entity,
    text: Annotated[str, typer.Option("--text")],
    expected_head: Head,
    component_id: Component = None,
    provenance: Provenance = "engineer",
    assumption: Assumptions = None,
    json_output: Json = False,
):
    """Add or revise a requirement; every edit requires fresh approval."""
    with _errors():
        artifact = workflow.enter_requirement(
            package_dir,
            store,
            record_id=record_id,
            kind=kind,
            entity_id=entity_id,
            text=text,
            expected_head=expected_head,
            component_id=component_id,
            provenance_kind=provenance,
            assumptions=tuple(assumption or ()),
        )
        _emit(workflow.publication(artifact), json_output)


@app.command()
def force(
    package_dir: Path,
    store: Store,
    record_id: Id,
    kind: Kind,
    entity_id: Entity,
    expected_head: Head,
    magnitude: Annotated[float | None, typer.Option("--magnitude")] = None,
    unit: Annotated[str, typer.Option("--unit", help="N, kN or lbf.")] = "N",
    direction: Annotated[str | None, typer.Option("--direction", help="Signed x,y,z.")] = None,
    unknown_reason: Annotated[str | None, typer.Option("--unknown-reason")] = None,
    frame_component: Annotated[
        str | None,
        typer.Option(
            "--frame-component", help="Occurrence-local axes; omitted uses root document axes."
        ),
    ] = None,
    point_m: Annotated[str | None, typer.Option("--point-m", help="Point x,y,z in metres.")] = None,
    component_id: Component = None,
    provenance: Provenance = "engineer",
    assumption: Assumptions = None,
    json_output: Json = False,
):
    """Add or revise a total applied force; no structural verdict is produced."""
    with _errors():
        artifact = workflow.enter_force(
            package_dir,
            store,
            record_id=record_id,
            kind=kind,
            entity_id=entity_id,
            magnitude=magnitude,
            unit=unit,
            direction=_vector(direction),
            expected_head=expected_head,
            unknown_reason=unknown_reason,
            frame_component_id=frame_component,
            point_m=_vector(point_m),
            component_id=component_id,
            provenance_kind=provenance,
            assumptions=tuple(assumption or ()),
        )
        _emit(workflow.publication(artifact), json_output)


@app.command()
def show(package_dir: Path, store: Store, json_output: Json = False):
    """Inspect exact private record contents and the digests required for approval."""
    with _errors():
        _emit(workflow.inspect_context(package_dir, store), json_output)


@app.command()
def confirm(
    package_dir: Path,
    store: Store,
    record_id: Id,
    expected_head: Head,
    actor: Annotated[str, typer.Option("--actor", help="Engineer responsible for approval.")],
    presented_record: Annotated[str, typer.Option("--record-digest")],
    presented_dependencies: Annotated[str, typer.Option("--dependency-digest")],
    json_output: Json = False,
):
    """Explicitly confirm the exact inputs inspected with show, for this saved snapshot."""
    with _errors():
        artifact = workflow.approve(
            package_dir,
            store,
            record_id=record_id,
            actor=actor,
            expected_head=expected_head,
            expected_record_digest=presented_record,
            expected_dependency_digest=presented_dependencies,
        )
        _emit(workflow.publication(artifact), json_output)
