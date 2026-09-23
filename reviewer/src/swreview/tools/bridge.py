"""Live SOLIDWORKS bridge tools, registered only with `--bridge` (T073).

The three rows of the "Live SOLIDWORKS bridge tools" table in contracts/agent-tools.md.
Each is one coarse call to `SwReview.Extractor.Console.exe serve` through
`swreview.bridge.client`, and each writes what came back into the session's copy of the
package so the rest of the review can use it: a capture becomes a `Capture` the report can
show, live interference results become `Interference`s `check_interference_group` can
judge, and the `Gap`s the host reports become gaps of the package.

The host's result shapes are its own (`Serve/PROTOCOL.md`): rows in the IR's shape, so
nothing here reformats a value. The rules that keep this side honest:

- these tools exist only when a bridge is wired. `swreview.tools.registry` adds them when
  `ToolContext.bridge` is set, which only `--bridge` does, so a package reviewed offline
  cannot even see them (contracts/agent-tools.md, "workstation only");
- a path the host returns must be relative and inside the package directory. The reviewer
  never reads or writes outside the package, however the bridge answers (research R4);
- a `BridgeError` - including the open circuit after three consecutive failures - is an
  error result, which the registry turns into `failed` coverage. A bridge that stopped
  working shows up in the report as checks that did not run, never as checks that passed.
  Where the host attached a `Gap` to the failure, that gap is recorded before the error is
  returned, so the request survives as something extraction could not provide;
- the two refusals the in-process tool service makes - `unauthorized` for a secret that
  does not carry this command, and `document no longer open` once the engineer closes the
  model - arrive as the named `BridgeError` subclasses and are answered the same way, with
  a sentence saying which of the two it was. The secret itself is the client's business:
  nothing here reads or forwards it.

`fetch_bodies_through_bridge` is not an agent tool at all: lever 10a has
`check_tool_envelope` pull a body's mesh back over the same bridge when the package was
extracted without meshes, so the model never asks for a tessellation and never chooses when
one happens. It lives here rather than in `tools/measure.py` because everything that makes
a bridge call honest - the package-relative path check, the host's gaps, the one exception
type - is already in this module.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from swreview.bridge.client import (
    BRIDGE_VIEWS,
    BridgeDocumentClosedError,
    BridgeError,
    BridgeUnauthorizedError,
)
from swreview.ir.models import (
    BodyRef,
    Capture,
    Gap,
    Interference,
    InterferenceSettings,
)
from swreview.tools.context import (
    ToolContext,
    current_context,
    error_result,
    not_one_of,
)
from swreview.tools.query import ToolResult, as_json
from swreview.tools.refs import EntityRefRefused, resolve_entity_ref

__all__ = [
    "bridge_capture",
    "bridge_interference",
    "bridge_measure",
    "capture_through_bridge",
    "fetch_bodies_through_bridge",
]

CAPTURE_ID_PREFIX = "cap"

REFUSALS: dict[type[BridgeError], str] = {
    BridgeUnauthorizedError: (
        "the tool service refused the secret this run carries for that command, so "
        "nothing ran in SOLIDWORKS"
    ),
    BridgeDocumentClosedError: (
        "the document is no longer open in SOLIDWORKS; the review continues on the "
        "extracted package and this call is failed coverage"
    ),
}
"""What each named refusal means, added to the error result so the report says which of
the two happened rather than only that the bridge said no. Keyed by the exact type: a
`BridgeError` that is neither gets no note."""


def _relative_inside_package(context: ToolContext, file: str) -> str | None:
    """`file` as a package-relative POSIX path, or `None` when it escapes the package.

    The host is trusted to run SOLIDWORKS, not to choose where the reviewer writes; an
    absolute path or one that climbs out of the package directory is refused here.
    """
    candidate = PurePosixPath(str(file).replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    base = Path(context.package.base_dir).resolve()
    resolved = (base / Path(str(candidate))).resolve()
    if base not in resolved.parents and resolved != base:
        return None
    return str(candidate)


def _unique_capture_id(context: ToolContext, proposed: str | None) -> str:
    """The host's capture id when this package does not already use it, else a fresh one.

    The host numbers captures within its own session; a package that already holds
    `cap:0001` from an earlier dump would otherwise end up with two rows sharing an id.
    """
    used = {capture.id for capture in context.ir.captures}
    if proposed and proposed not in used:
        return proposed
    index = len(used) + 1
    while f"{CAPTURE_ID_PREFIX}:{index}" in used:
        index += 1
    return f"{CAPTURE_ID_PREFIX}:{index}"


def _record_gap(context: ToolContext, raw: Any) -> str | None:
    """Append a `Gap` the host attached to a failure; returns its reason, or `None`.

    `None` means the host attached nothing. A gap the host did send but that does not
    parse is still recorded, as a `tool_error` gap carrying the raw payload and the
    validation error, so that a failure the host reported can never vanish from coverage.
    """
    if raw is None:
        return None
    try:
        if not isinstance(raw, dict):
            raise TypeError(f"gap payload is {type(raw).__name__}, not an object")
        gap = Gap.model_validate(raw)
    except (ValidationError, TypeError) as exc:
        gap = Gap(
            kind="tool_error",
            entity_kind="bridge_gap",
            entity_id=None,
            reason="the bridge host attached a gap that could not be parsed; raw payload: "
            + json.dumps(raw, default=str)[:500],
            error=str(exc)[:500],
        )
    context.ir.gaps.append(gap)
    return gap.reason


def _bridge_failure(context: ToolContext, exc: BridgeError, what: str) -> ToolResult:
    """A bridge failure as an error result, with any `Gap` the host sent recorded first."""
    attached = exc.result.get("gap") if isinstance(exc.result, dict) else None
    reason = _record_gap(context, attached)
    message = f"{type(exc).__name__}: {exc}"
    if reason is not None:
        message = f"{message} (recorded as a gap: {reason})"
    note = REFUSALS.get(type(exc))
    if note is not None:
        message = f"{message}; {note}"
    return error_result(f"{what}: {message}")


def capture_through_bridge(
    context: ToolContext,
    persist_ref: str,
    view: str,
    component_ids: list[str] | None = None,
    *,
    subject: str | None = None,
) -> ToolResult:
    """Ask the bridge for a capture, record it in the package copy, return its path.

    Shared by `bridge_capture` and by `request_capture`, which routes through the bridge
    when one is wired: both must record the same `Capture` and refuse the same paths.
    `subject` is what the messages call the entity - the id the model sent, so an error it
    reads never quotes a reference it was not shown (feature 008) - and defaults to the
    reference for a caller that has no id.
    """
    label = subject if subject is not None else persist_ref
    if context.bridge is None:
        return error_result("no live SOLIDWORKS bridge is wired to this run")
    try:
        result = context.bridge.capture(persist_ref, view)
    except BridgeError as exc:
        return _bridge_failure(context, exc, f"capturing {label!r}")

    payload: dict[str, Any] = result if isinstance(result, dict) else {}
    row = payload.get("capture")
    if not isinstance(row, dict) or not row.get("file"):
        return error_result(
            f"the bridge captured {label!r} but its result names no file: {result!r}"
        )
    relative = _relative_inside_package(context, str(row["file"]))
    if relative is None:
        return error_result(
            f"the bridge returned a capture path outside the package directory: "
            f"{row['file']!r}"
        )

    try:
        capture = Capture(
            id=_unique_capture_id(context, row.get("id")),
            persist_ref=row.get("persist_ref") or persist_ref,
            component_ids=(
                list(component_ids)
                if component_ids is not None
                else list(row.get("component_ids", []))
            ),
            file=relative,
            view=str(row.get("view", view)),
            note=str(row.get("note") or "captured through the live SOLIDWORKS bridge"),
        )
    except ValidationError as exc:
        return error_result(
            f"the bridge returned a capture this package cannot hold: "
            f"{exc.errors(include_url=False)}"
        )

    context.ir.captures.append(capture)
    return {
        "status": "captured",
        "file": capture.file,
        "host_path": payload.get("path"),
        "capture": as_json(capture),
    }


def fetch_bodies_through_bridge(context: ToolContext, *, exclude_component_id: str) -> list[str]:
    """Lever 10a. Fetch every component's bodies over the bridge; return what could not be.

    The reviewer's only mesh reader is `check_tool_envelope`, and with `extraction.meshes`
    set to `lazy` the package it reads carries no `bodies` at all: they are written on
    demand here, by the host, through the same export the dump uses, so a clearance answer
    never depends on how the mesh arrived (FR-090).

    Every way this can fail has one answer: **the component is named in the list this
    returns**, which the caller reports as `unresolved`. A body that was not fetched is a
    body the sweep did not test, and a sweep that did not test a body has not established
    that it is out of the way (constitution Principle I). Nothing here raises and nothing
    here stops the check:

    - no bridge at all - the ordinary case off the workstation - is one reason saying so;
    - a `BridgeError`, which is every refusal, dead pipe and open circuit, is that
      component's reason, and the next component is still attempted: the circuit breaker
      in the client is what stops the asking, not a decision taken here;
    - reaching `extraction.lazy_fetch_body_limit` is that component's reason too. It is
      **unresolved coverage, not a stop**, because one STA worker answers every bridge call
      in arrival order and a runaway fetch would stall the application thread (RK-14);
    - a row naming a path outside the package directory is refused before anything is read.

    A component whose bodies are already in the package is skipped, so two checks in one
    review fetch it once.

    Args:
        context: The run's context; `context.ir.bodies` grows by what came back.
        exclude_component_id: The component the caller is not sweeping - the fastener's
            own - which is not worth a round trip.
    """
    unresolved: list[str] = []
    if context.extraction.meshes != "lazy":
        return unresolved
    if context.bridge is None:
        return [
            "this package was extracted without meshes and this run has no live "
            "SOLIDWORKS bridge, so no body could be fetched to sweep"
        ]

    fetched = {body.component_id for body in context.ir.bodies}
    limit = context.extraction.lazy_fetch_body_limit
    for component in context.ir.components:
        if component.id == exclude_component_id or component.id in fetched:
            continue
        if context.lazy_bodies_fetched >= limit:
            unresolved.append(
                f"{component.id}: this review has already fetched "
                f"{context.lazy_bodies_fetched} bodies, which is its "
                f"extraction.lazy_fetch_body_limit ({limit}), so no mesh was fetched for it"
            )
            continue
        unresolved.extend(_fetch_component(context, component.id))
    return unresolved


def _fetch_component(context: ToolContext, component_id: str) -> list[str]:
    """One `tessellate` round trip, as rows on the package and reasons for what is missing."""
    try:
        result = context.bridge.tessellate(component_id)
    except BridgeError as exc:
        note = REFUSALS.get(type(exc))
        reason = f"{component_id}: {type(exc).__name__}: {exc}"
        return [reason if note is None else f"{reason}; {note}"]

    payload: dict[str, Any] = result if isinstance(result, dict) else {}
    gaps = [
        reason
        for reason in (_record_gap(context, item) for item in payload.get("gaps", []) or [])
        if reason is not None
    ]

    rows = payload.get("bodies")
    if not isinstance(rows, list):
        return [
            f"{component_id}: the bridge returned {type(rows).__name__} where a list of "
            f"bodies was expected"
        ]

    bodies: list[BodyRef] = []
    unresolved: list[str] = []
    for row in rows:
        try:
            body = BodyRef.model_validate(row)
        except ValidationError as exc:
            unresolved.append(
                f"{component_id}: the bridge returned a body this package cannot hold: "
                f"{exc.errors(include_url=False)}"
            )
            continue
        relative = _relative_inside_package(context, body.mesh_file)
        if relative is None:
            unresolved.append(
                f"{component_id} body {body.id}: the bridge returned a mesh path outside "
                f"the package directory: {body.mesh_file!r}"
            )
            continue
        bodies.append(body.model_copy(update={"mesh_file": relative}))

    if not bodies and not unresolved:
        # Never a silent clear: a component that answered with no body is a component
        # whose bodies were not tested, whatever the host's reason was.
        unresolved.append(
            f"{component_id}: the bridge fetched no body for it"
            + (f" ({'; '.join(gaps)})" if gaps else "")
        )

    context.ir.bodies.extend(bodies)
    context.lazy_bodies_fetched += len(bodies)
    return unresolved


def bridge_capture(entity_id: str, view: str) -> ToolResult:
    """Render one entity in the open SOLIDWORKS document and save a PNG.

    Args:
        entity_id: The entity's id as a query tool returned it; resolved server-side.
        view: One of iso, front, top, right, fit.

    Notes:
        The host frames the entity the persistent reference resolves to, applies the view, and
        saves an image; it chooses where, so no path is ever sent. The capture is added to the
        package so the report can show it, and the result carries its package-relative path.
    """
    context = current_context()
    if view not in BRIDGE_VIEWS:
        return not_one_of("view", str(view), BRIDGE_VIEWS)
    try:
        persist_ref, _ = resolve_entity_ref(context.ir, entity_id)
    except EntityRefRefused as refused:
        return error_result(str(refused))
    return capture_through_bridge(context, persist_ref, view, subject=entity_id)


def bridge_measure(entity_id_a: str, entity_id_b: str) -> ToolResult:
    """SOLIDWORKS' own Measure between two entities, with the units it reports.

    Args:
        entity_id_a: First entity's id as a query tool returned it; resolved server-side.
        entity_id_b: Second entity's id as a query tool returned it; resolved server-side.

    Notes:
        This is the live counterpart of `measure_axis_distance` and `measure_face_gap`: it
        measures what the open document holds rather than what the package recorded, which is
        the point of running with the bridge at all. The result is the host's, unaltered -
        note that it answers in **metres**, not the millimetres the offline tools report.
    """
    context = current_context()
    if context.bridge is None:
        return error_result("no live SOLIDWORKS bridge is wired to this run")
    try:
        persist_ref_a, _ = resolve_entity_ref(context.ir, entity_id_a)
        persist_ref_b, _ = resolve_entity_ref(context.ir, entity_id_b)
    except EntityRefRefused as refused:
        return error_result(str(refused))
    try:
        result = context.bridge.measure(persist_ref_a, persist_ref_b)
    except BridgeError as exc:
        return _bridge_failure(
            context, exc, f"measuring between {entity_id_a!r} and {entity_id_b!r}"
        )
    return {
        "status": "measured",
        "entity_id_a": entity_id_a,
        "entity_id_b": entity_id_b,
        "measurement": result,
        "source": "SOLIDWORKS Measure through the live bridge; lengths are in metres",
    }


def bridge_interference(
    component_ids: list[str], configuration: str, settings: InterferenceSettings
) -> ToolResult:
    """Run interference detection live and add the results to the package.

    Args:
        component_ids: Components to test, or an empty list for the whole assembly.
        configuration: Configuration to compute in.
        settings: Detection settings, all five stated: treat_coincident_as_interference,
            treat_subassemblies_as_components, include_multibody, ignore_hidden (all
            booleans) and fastener_folder_treatment (include, exclude or only). They are
            the settings the results are then read under, so none of them is assumed
            here.

    Notes:
        The results come back in the IR's own shape and are appended to the package under
        review, so `list_interferences` and `check_interference_group` work on them exactly as
        they work on results the extractor dumped. A result whose id the package already holds
        is not added twice. Every `Gap` the host reports - the volume-unit caveat among them -
        is appended to the package's gaps, because it bounds what the results mean.

        Each row carries its own status: a `truncated` or `failed` row is unresolved coverage,
        never a pass.
    """
    context = current_context()
    if context.bridge is None:
        return error_result("no live SOLIDWORKS bridge is wired to this run")
    unknown = [
        component_id
        for component_id in component_ids
        if context.component(component_id) is None
    ]
    if unknown:
        return error_result(f"component_ids not in this package: {unknown}")

    try:
        result = context.bridge.interference(
            list(component_ids), configuration, settings.model_dump()
        )
    except BridgeError as exc:
        return _bridge_failure(context, exc, "running interference detection")

    payload: dict[str, Any] = result if isinstance(result, dict) else {}
    raw = payload.get("interferences", result if isinstance(result, list) else None)
    if not isinstance(raw, list):
        return error_result(
            f"the bridge returned {type(raw).__name__} where a list of interferences was "
            "expected"
        )
    try:
        interferences = [Interference.model_validate(item) for item in raw]
    except ValidationError as exc:
        return error_result(
            f"the bridge returned an interference this package cannot hold: "
            f"{exc.errors(include_url=False)}"
        )

    known = {item.id for item in context.ir.interferences}
    added = [item for item in interferences if item.id not in known]
    context.ir.interferences.extend(added)
    gaps = [
        reason
        for reason in (_record_gap(context, item) for item in payload.get("gaps", []) or [])
        if reason is not None
    ]
    return {
        "status": "computed",
        "configuration": configuration,
        "interferences": [as_json(item) for item in interferences],
        "added_to_package": len(added),
        "gaps": gaps,
    }
