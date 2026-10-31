"""Read a `probe remodel` capabilities ledger and say what it lets the build switch on.

Feature 004 T337 (owner decisions 166A, 170A and 171A; research R27.4). `swreview-extract probe
remodel` writes `capabilities/remodel-<version>.yaml` with `RemodelProbeLedger.Render`; this module
reads exactly that shape - one golden fixture, `tests/fixtures/remodel/ledger/`, pins the C#
renderer and this parser together - and answers four things:

- each probe's verdict, with its reason, or the exception type it threw;
- the probes the run was asked for that have no row: the run stopped before they finished (T333);
- the type names in PROBE-11's census that `rms_types.yaml` does not know;
- per seat switch, ready or not, and why not. **Start** (`RemodelStart.SeatValidated`, research
  R13.3) needs PROBE-1, 2, 3, 4 and 12 verified, each with a reason and no error - decision 148A's
  rule, which the test plan states for PROBE-12's reopen and every probe body follows - and the
  IDENTITY tolerance profile calibrated (decision 170A: PROBE-8's numbers are the calibration input,
  T138 and T187).

It refuses, before judging anything, a ledger for another SOLIDWORKS version than the frozen
interop's, and a ledger any of whose strings looks like a path (decision 171A: a ledger from the
probe's own throwaway part may be committed, once nothing in it names a place on someone's
machine). A refusal names the field, never the value.

It judges and switches nothing: Start is set true in a commit of its own, which a CI pin
(`tests/unit/test_seat_switch_evidence.py`) holds to a committed ledger this module judges ready.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from swreview.checks.rms_types import RmsTypeTable, load_table
from swreview.remodel.tolerances import IDENTITY, Tolerances

__all__ = [
    "FROZEN_INTEROP_VERSION",
    "START_PROBES",
    "START_SWITCH",
    "SW_VERSIONS",
    "Ledger",
    "LedgerRefused",
    "ProbeRow",
    "SwitchReadiness",
    "load_ledger",
    "parse_ledger",
    "path_kind",
    "start_readiness",
    "summary",
    "summary_lines",
    "unknown_types",
]

FROZEN_INTEROP_VERSION = "32.5.0.48"
"""The SOLIDWORKS 2024 SP5 interop the build is frozen against (`remodel-interop-manifest.json`)."""

SW_VERSIONS: tuple[str, ...] = (FROZEN_INTEROP_VERSION, "32.5.0")
"""The `sw_version` a ledger may carry. A seat's ledger records `ISldWorks.RevisionNumber`, which
answers the release as major, service pack and minor - "32.5.0", as `SwSession.ReadVersion`
says and the recorded packages carry - so that spelling of the frozen release is read too."""

START_SWITCH = "RemodelStart.SeatValidated"
START_PROBES: tuple[str, ...] = ("PROBE-1", "PROBE-2", "PROBE-3", "PROBE-4", "PROBE-12")
"""The blocking probes Start waits on (research R13.3). PROBE-8 gates the calibration instead."""

ERROR_KEY = "error"
"""`RemodelProbeRunner.ErrorKey`: what a body that threw files instead of a reason."""

REASON_KEY = "reason"

_TYPE_KEY = re.compile(r"type\[.*\]")
_UNREADABLE_TYPE = "(unreadable)"

_FAILURE = re.compile(r"\w+ 0x[0-9A-F]{8}(?:; \w+ 0x[0-9A-F]{8})*")
"""`ProbeText.Failure`'s `<Type> 0x<HRESULT>`, one per exception, the only exception text a
ledger written since 004 T335 carries. Anything else in `error` is an earlier build's message."""

_PATH = re.compile(
    r"(?P<drive>(?<!\w)[A-Za-z]:[\\/]|[A-Za-z]:\\)"
    r"|(?P<unc>(?<!\w)\\\\)"
    r"|(?P<posix>(?<![\w:/.])/(?=[^\s>]))"
)
"""The committable-path scanner's anchors (`tests/support/local_paths.py`), which a product
module cannot import: a drive and either separator at a token boundary (a drive and its backslash
anywhere), a UNC share's two backslashes, and a `/` at a token boundary before a non-space - so
`n/a`, `1/2`, `a / b`, a relative `reviewer/src` and a URL's `//` are not paths. A test holds the
two to the same answer on every sample."""

_FIELDS = frozenset(
    {"sw_version", "generated_at", "requested", "probes", "probe_id", "question", "method",
     "blocking", "fallback", "verdict", "duration_ms", "interop_members", "raw_result"}
)
"""The renderer's own keys: the only keys a refusal names (a `raw_result` key is a reading)."""

ProbeId = Annotated[str, StringConstraints(pattern=r"^PROBE-\d+$")]
Verdict = Literal["verified", "refuted", "unresolved"]


class LedgerRefused(ValueError):
    """A ledger this reader will not judge. The message names the field, never its value."""


class _Shape(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ProbeRow(_Shape):
    """One row, as `RemodelProbeLedger.Render` writes it."""

    probe_id: ProbeId
    question: str
    method: str
    blocking: bool
    fallback: str
    verdict: Verdict
    sw_version: str
    duration_ms: int = Field(ge=0)
    interop_members: list[str]
    raw_result: dict[str, str]


class Ledger(_Shape):
    """The whole file: its version, when it was written, what was asked for, and the rows."""

    sw_version: str
    generated_at: str
    requested: list[ProbeId]
    probes: list[ProbeRow]

    def row(self, probe_id: str) -> ProbeRow | None:
        return next((row for row in self.probes if row.probe_id == probe_id), None)

    @property
    def unfinished(self) -> list[str]:
        """The probes asked for with no row: the run stopped before each of them ended."""
        return [probe for probe in self.requested if self.row(probe) is None]


@dataclass(frozen=True)
class SwitchReadiness:
    """Whether a ledger lets the build switch `switch` on, and every reason it does not."""

    switch: str
    ready: bool
    reasons: tuple[str, ...]


def path_kind(text: str) -> str | None:
    """`drive`, `UNC` or `POSIX` for the first thing in `text` that looks like a path, or None."""
    found = _PATH.search(text)
    if found is None:
        return None
    return {"drive": "drive", "unc": "UNC", "posix": "POSIX"}[found.lastgroup or "posix"]


def load_ledger(path: Path | str) -> Ledger:
    """The ledger at `path`. The renderer writes a byte-order mark, which is not the text's."""
    return parse_ledger(Path(path).read_text(encoding="utf-8-sig"))


def parse_ledger(text: str) -> Ledger:
    """The ledger `text` holds, or `LedgerRefused`: not the renderer's shape, a path anywhere in
    it (checked first, on every key and value, so no later message can repeat one), or another
    version than the frozen interop's."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise LedgerRefused(_shape_refusal(f"it is not valid YAML{where}")) from None
    if not isinstance(document, dict):
        raise LedgerRefused(_shape_refusal("it is not a mapping"))

    for where, string in _strings(document, ""):
        kind = path_kind(string)
        if kind is not None:
            raise LedgerRefused(
                f"a string in {where or 'a key'} looks like a {kind} path; a ledger that names a "
                "path is not read, nor committed (decision 171A)"
            )

    try:
        ledger = Ledger.model_validate(document)
    except ValidationError as exc:
        fields = sorted({f"{_named(error['loc'])} ({error['type']})" for error in exc.errors()})
        raise LedgerRefused(
            _shape_refusal("these fields are missing or malformed: " + ", ".join(fields))
        ) from None

    if ledger.sw_version not in SW_VERSIONS:
        raise LedgerRefused(
            f"this ledger is for SOLIDWORKS {ledger.sw_version!r}; only the frozen interop's "
            f"version is judged ({' or '.join(SW_VERSIONS)})"
        )
    for row in ledger.probes:
        if row.sw_version != ledger.sw_version:
            raise LedgerRefused(f"{row.probe_id}'s row is for another version than its ledger")
    _refuse_inconsistent(ledger)
    return ledger


def start_readiness(ledger: Ledger, identity: Tolerances = IDENTITY) -> SwitchReadiness:
    """Whether `ledger` lets the build set `RemodelStart.SeatValidated`, and every reason not."""
    reasons: list[str] = []
    for probe in START_PROBES:
        row = ledger.row(probe)
        if row is None:
            reasons.append(
                f"{probe} did not finish" if probe in ledger.requested else f"{probe} was not run"
            )
        elif ERROR_KEY in row.raw_result:
            reasons.append(f"{probe} threw {_shown_error(row.raw_result[ERROR_KEY])}")
        elif row.verdict != "verified":
            reasons.append(f"{probe} is {row.verdict}")
        elif REASON_KEY not in row.raw_result:
            reasons.append(
                f"{probe} gives no reason (decision 148A: a verdict with a reason and no error)"
            )
    if not identity.calibrated:
        reasons.append(
            "the IDENTITY tolerance profile is not calibrated: T138 freezes it against PROBE-8's "
            "numbers (decision 170A)"
        )
    return SwitchReadiness(START_SWITCH, not reasons, tuple(reasons))


def unknown_types(ledger: Ledger, table: RmsTypeTable | None = None) -> list[str]:
    """PROBE-11's type names the RMS table does not know, once each, in the census's order.

    Known is classified (a class or `ambiguous`), the folder type, a tolerated type or a derived
    part's base; an unreadable answer is PROBE-11's own `unresolved`, not a name."""
    row = ledger.row("PROBE-11")
    if row is None:
        return []
    resolved = table or load_table()
    names: list[str] = []
    for key, name in row.raw_result.items():
        if (
            _TYPE_KEY.fullmatch(key)
            and name != _UNREADABLE_TYPE
            and name not in names
            and resolved.classify(name) == "unknown"
            and name != resolved.folder_type
            and name not in resolved.tolerated_loose
            and name not in resolved.derived_base
        ):
            names.append(name)
    return names


def summary(
    ledger: Ledger, name: str, identity: Tolerances = IDENTITY, table: RmsTypeTable | None = None
) -> dict[str, Any]:
    """What `swreview remodel ledger --json` prints; `summary_lines` says the same in words.
    `name` is the file's name only: its folder may name the user."""
    start = start_readiness(ledger, identity)
    return {
        "ledger": name,
        "sw_version": ledger.sw_version,
        "generated_at": ledger.generated_at,
        "requested": list(ledger.requested),
        "probes": [
            {
                "probe_id": row.probe_id,
                "blocking": row.blocking,
                "verdict": row.verdict,
                "reason": row.raw_result.get(REASON_KEY),
                "error": (
                    _shown_error(row.raw_result[ERROR_KEY])
                    if ERROR_KEY in row.raw_result else None
                ),
            }
            for row in ledger.probes
        ],
        "unfinished": ledger.unfinished,
        "unknown_types": unknown_types(ledger, table),
        "switches": [
            {"switch": start.switch, "ready": start.ready, "reasons": list(start.reasons)}
        ],
    }


def summary_lines(payload: dict[str, Any]) -> list[str]:
    """One line for the file, one per probe in the requested order, the unknown type names,
    and one per switch."""
    rows = {row["probe_id"]: row for row in payload["probes"]}
    lines = [
        f"{payload['ledger']}: SOLIDWORKS {payload['sw_version']}, written "
        f"{payload['generated_at']}; {len(rows)} of {len(payload['requested'])} requested "
        "probes finished"
    ]
    for probe in payload["requested"]:
        row = rows.get(probe)
        if row is None:
            lines.append(f"{probe}: not finished - the run stopped before this probe ended")
            continue
        label = f"{probe} (blocking)" if row["blocking"] else probe
        why = f"threw {row['error']}" if row["error"] is not None else row["reason"] or "no reason"
        lines.append(f"{label}: {row['verdict']} - {why}")
    if payload["unknown_types"]:
        lines.append(
            "PROBE-11 type names rms_types.yaml does not know: "
            + ", ".join(payload["unknown_types"])
        )
    for switch in payload["switches"]:
        state = "ready" if switch["ready"] else "not ready - " + "; ".join(switch["reasons"])
        lines.append(f"{switch['switch']}: {state}")
    return lines


def _shown_error(error: str) -> str:
    return error if _FAILURE.fullmatch(error) else "(its message is not shown)"


def _shape_refusal(why: str) -> str:
    return f"not a ledger RemodelProbeLedger.Render writes: {why}"


def _strings(node: Any, where: str) -> Iterator[tuple[str, str]]:
    """Every key and string value of the parsed YAML, each with where it sits, named by the
    renderer's own keys and list positions only."""
    if isinstance(node, str):
        yield where, node
    elif isinstance(node, dict):
        for key, value in node.items():
            inner = f"{where}.{key}".lstrip(".") if key in _FIELDS else where
            if isinstance(key, str):
                yield where, key
            yield from _strings(value, inner)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _strings(item, f"{where}[{index}]")


def _named(location: tuple[int | str, ...]) -> str:
    """A validation error's location by the renderer's keys and list positions; any other key,
    which may be a reading or a stranger's field, is `<key>`."""
    return "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" if part in _FIELDS else ".<key>"
        for part in location
    ).lstrip(".")


def _refuse_inconsistent(ledger: Ledger) -> None:
    """A probe asked for twice, a row twice, or a row nobody asked for is not what `probe remodel`
    writes."""
    if len(set(ledger.requested)) != len(ledger.requested):
        raise LedgerRefused(_shape_refusal("a probe is requested twice"))
    ids = [row.probe_id for row in ledger.probes]
    if len(set(ids)) != len(ids):
        raise LedgerRefused(_shape_refusal("a probe has two rows"))
    if not set(ids) <= set(ledger.requested):
        raise LedgerRefused(_shape_refusal("a row's probe was not requested"))
