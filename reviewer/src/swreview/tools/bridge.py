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
  returned, so the request survives as something extraction could not provide.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from swreview.bridge.client import BRIDGE_VIEWS, BridgeError
from swreview.ir.models import Capture, Gap, Interference
from swreview.tools.context import (
    ToolContext,
    current_context,
    error_result,
    not_one_of,
)
from swreview.tools.query import ToolResult, as_json

__all__ = [
    "bridge_capture",
    "bridge_interference",
    "bridge_measure",
    "capture_through_bridge",
]

CAPTURE_ID_PREFIX = "cap"


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
    """Append a `Gap` the host attached to a failure; returns its reason, or `None`."""
    if not isinstance(raw, dict):
        return None
    try:
        gap = Gap.model_validate(raw)
    except ValidationError:
        return None
    context.ir.gaps.append(gap)
    return gap.reason


def _bridge_failure(context: ToolContext, exc: BridgeError, what: str) -> ToolResult:
    """A bridge failure as an error result, with any `Gap` the host sent recorded first."""
    attached = exc.result.get("gap") if isinstance(exc.result, dict) else None
    reason = _record_gap(context, attached)
    message = f"{type(exc).__name__}: {exc}"
    if reason is not None:
        message = f"{message} (recorded as a gap: {reason})"
    return error_result(f"{what}: {message}")


def capture_through_bridge(
    context: ToolContext,
    persist_ref: str,
    view: str,
    component_ids: list[str] | None = None,
) -> ToolResult:
    """Ask the bridge for a capture, record it in the package copy, return its path.

    Shared by `bridge_capture` and by `request_capture`, which routes through the bridge
    when one is wired: both must record the same `Capture` and refuse the same paths.
    """
    if context.bridge is None:
        return error_result("no live SOLIDWORKS bridge is wired to this run")
    try:
        result = context.bridge.capture(persist_ref, view)
    except BridgeError as exc:
        return _bridge_failure(context, exc, f"capturing {persist_ref!r}")

    payload: dict[str, Any] = result if isinstance(result, dict) else {}
    row = payload.get("capture")
    if not isinstance(row, dict) or not row.get("file"):
        return error_result(
            f"the bridge captured {persist_ref!r} but its result names no file: {result!r}"
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


def bridge_capture(persist_ref: str, view: str) -> ToolResult:
    """Render one entity in the open SOLIDWORKS document and save a PNG.

    The host frames the entity the persistent reference resolves to, applies the view, and
    saves an image; it chooses where, so no path is ever sent. The capture is added to the
    package so the report can show it, and the result carries its package-relative path.

    Args:
        persist_ref: The entity's persistent reference, as the package records it.
        view: One of iso, front, top, right, fit.
    """
    context = current_context()
    if view not in BRIDGE_VIEWS:
        return not_one_of("view", str(view), BRIDGE_VIEWS)
    return capture_through_bridge(context, persist_ref, view)


def bridge_measure(persist_ref_a: str, persist_ref_b: str) -> ToolResult:
    """SOLIDWORKS' own Measure between two entities, with the units it reports.

    This is the live counterpart of `measure_axis_distance` and `measure_face_gap`: it
    measures what the open document holds rather than what the package recorded, which is
    the point of running with the bridge at all. The result is the host's, unaltered -
    note that it answers in **metres**, not the millimetres the offline tools report.

    Args:
        persist_ref_a: First entity's persistent reference.
        persist_ref_b: Second entity's persistent reference.
    """
    context = current_context()
    if context.bridge is None:
        return error_result("no live SOLIDWORKS bridge is wired to this run")
    try:
        result = context.bridge.measure(persist_ref_a, persist_ref_b)
    except BridgeError as exc:
        return _bridge_failure(
            context, exc, f"measuring between {persist_ref_a!r} and {persist_ref_b!r}"
        )
    return {
        "status": "measured",
        "persist_ref_a": persist_ref_a,
        "persist_ref_b": persist_ref_b,
        "measurement": result,
        "source": "SOLIDWORKS Measure through the live bridge; lengths are in metres",
    }


def bridge_interference(
    component_ids: list[str], configuration: str, settings: dict[str, Any]
) -> ToolResult:
    """Run interference detection live and add the results to the package.

    The results come back in the IR's own shape and are appended to the package under
    review, so `list_interferences` and `check_interference_group` work on them exactly as
    they work on results the extractor dumped. A result whose id the package already holds
    is not added twice. Every `Gap` the host reports - the volume-unit caveat among them -
    is appended to the package's gaps, because it bounds what the results mean.

    Each row carries its own status: a `truncated` or `failed` row is unresolved coverage,
    never a pass.

    Args:
        component_ids: Components to test, or an empty list for the whole assembly.
        configuration: Configuration to compute in.
        settings: Detection settings: treat_coincident_as_interference,
            treat_subassemblies_as_components, include_multibody, ignore_hidden,
            fastener_folder_treatment.
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
            list(component_ids), configuration, dict(settings)
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
