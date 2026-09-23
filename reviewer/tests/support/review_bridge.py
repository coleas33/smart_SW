"""A scripted SOLIDWORKS bridge for reviews that need one without a seat (008 research R2.50).

`ScriptedReviewBridge` is what `start_review(..., bridge=True, bridge_factory=lambda pipe,
secret: bridge)` builds instead of `swreview.bridge.client.BridgeClient`. It speaks the same
coarse calls with the same signatures - `ping`, `capture`, `measure`, `interference`,
`tessellate` - and answers from a script:

- `results={"interference": [answer, ...]}` answers each call of that command in order; an
  answer that is an exception is raised in its turn, and a callable answer is called with the
  call's named arguments. Running out of answers is a scripting mistake and fails loudly.
- `raises={"interference": BridgeError(...)}` raises on every call of that command.
- `supports=(...)` names the commands it has; the others are **absent** (no attribute at
  all), which is how an older host without live interference looks to a tool.

Every call is recorded in `calls` with its arguments by name before it is answered. A call
that starts while another is still in progress raises `AssertionError`: SOLIDWORKS answers on
one STA thread, and a review that re-entered the bridge would be one the real host serializes
differently (feature 008 T080 relies on this).

It lives in Setup rather than in User Story 2 because the fixture generator answers each
recording's live `bridge_interference` call with it. `interference_row` builds rows in the
IR's `Interference` shape and `VOLUME_UNIT_GAP` is the gap every live run carries until the
workstation verifies the volume unit.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "RECORDED_INTERFERENCE_SETTINGS",
    "VOLUME_UNIT_GAP",
    "ScriptedReviewBridge",
    "interference_row",
]

RECORDED_INTERFERENCE_SETTINGS: dict[str, Any] = {
    "treat_coincident_as_interference": True,
    "treat_subassemblies_as_components": True,
    "include_multibody": True,
    "ignore_hidden": False,
    "fastener_folder_treatment": "include",
}
"""The detection settings the recorded runs chose, all five stated (research R2.17)."""

VOLUME_UNIT_GAP: dict[str, Any] = {
    "kind": "unsupported",
    "entity_kind": "interference_volume_unit",
    "entity_id": None,
    "reason": "IInterference.Volume unit assumed m3; verify on workstation",
    "error": None,
}
"""The gap the host attaches to a live run while the volume unit is unverified."""

_SIGNATURES: dict[str, tuple[tuple[str, Any], ...]] = {
    "ping": (),
    "capture": (("persist_ref", None), ("view", "fit"), ("scope_document", None), ("note", "")),
    "measure": (
        ("persist_ref_a", None),
        ("persist_ref_b", None),
        ("scope_document_a", None),
        ("scope_document_b", None),
    ),
    "interference": (
        ("component_ids", None),
        ("configuration", None),
        ("settings", None),
        ("truncate_after", None),
    ),
    "tessellate": (("component_id", None),),
}
"""Each command's parameters and defaults, exactly as `BridgeClient` declares them."""

COMMANDS: tuple[str, ...] = tuple(_SIGNATURES)
DEFAULT_SUPPORTS: tuple[str, ...] = ("ping", "capture", "measure", "interference", "tessellate")


class ScriptedReviewBridge:
    """A bridge client answering from a script, recording every call, never re-entered."""

    def __init__(
        self,
        *,
        results: Mapping[str, Sequence[Any]] | None = None,
        raises: Mapping[str, BaseException] | None = None,
        supports: Iterable[str] = DEFAULT_SUPPORTS,
    ) -> None:
        supported = tuple(supports)
        unknown = [command for command in supported if command not in _SIGNATURES]
        if unknown:
            raise ValueError(f"a scripted bridge cannot support {unknown}; it knows {COMMANDS}")
        self.supports = supported
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.circuit_open = False
        self.last_error: str | None = None
        self.closed = False
        self._results = {command: deque(answers) for command, answers in (results or {}).items()}
        self._raises = dict(raises or {})
        self._busy: str | None = None

    def __getattribute__(self, name: str) -> Any:
        """Hide the commands this bridge was not given, so `hasattr` answers as a host would."""
        if name in _SIGNATURES and name not in object.__getattribute__(self, "supports"):
            raise AttributeError(f"this scripted bridge does not support {name!r}")
        return object.__getattribute__(self, name)

    # --- the coarse calls, with BridgeClient's signatures -----------------------------------

    def ping(self) -> Any:
        return self._call("ping", (), {})

    def capture(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("capture", args, kwargs)

    def measure(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("measure", args, kwargs)

    def interference(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("interference", args, kwargs)

    def tessellate(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("tessellate", args, kwargs)

    def close(self) -> None:
        self.closed = True

    # --- the script ------------------------------------------------------------------------

    def _call(self, command: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if self._busy is not None:
            raise AssertionError(
                f"{command!r} started while {self._busy!r} was still in progress; the live "
                "bridge answers one call at a time"
            )
        arguments = _named(command, args, kwargs)
        self.calls.append((command, arguments))
        self._busy = command
        try:
            return self._answer(command, arguments)
        finally:
            self._busy = None

    def _answer(self, command: str, arguments: dict[str, Any]) -> Any:
        failure = self._raises.get(command)
        if failure is not None:
            self.last_error = str(failure)
            raise failure
        answers = self._results.get(command)
        if not answers:
            raise AssertionError(
                f"the scripted bridge has no answer left for {command!r} (call "
                f"{sum(1 for name, _ in self.calls if name == command)})"
            )
        answer = answers.popleft()
        if isinstance(answer, BaseException):
            self.last_error = str(answer)
            raise answer
        if callable(answer):
            return answer(arguments)
        return answer


def _named(command: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """The call's arguments by name, with `BridgeClient`'s defaults filled in."""
    signature = _SIGNATURES[command]
    if len(args) > len(signature):
        raise TypeError(f"{command} takes {len(signature)} arguments, got {len(args)}")
    named = {name: default for name, default in signature}
    for (name, _), value in zip(signature, args, strict=False):
        named[name] = value
    unknown = set(kwargs) - set(named)
    if unknown:
        raise TypeError(f"{command} got unexpected arguments {sorted(unknown)}")
    named.update(kwargs)
    return named


def interference_row(
    id: str,
    pair: tuple[str, str] | Sequence[str],
    group_key: str,
    volume_mm3: float | None = None,
    *,
    is_possible: bool = False,
    status: str = "computed",
    configuration: str = "Default",
    volume_m3: float | None = None,
    settings: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """One interference row in the IR's `Interference` shape, as the host returns it.

    `volume_mm3` and `volume_m3` are the two units a row can be reported in; at most one is
    given, and neither means the host reported no volume. The settings default to the recorded
    runs' (`RECORDED_INTERFERENCE_SETTINGS`), because a row always carries the settings it
    was detected under.
    """
    if volume_mm3 is not None and volume_m3 is not None:
        raise ValueError("an interference row carries one volume: give volume_mm3 or volume_m3")
    volume: dict[str, Any] | None = None
    if volume_mm3 is not None:
        volume = {"value": volume_mm3, "unit": "mm3"}
    elif volume_m3 is not None:
        volume = {"value": volume_m3, "unit": "m3"}
    return {
        "id": id,
        "configuration": configuration,
        "component_ids": list(pair),
        "volume": volume,
        "settings": dict(settings if settings is not None else RECORDED_INTERFERENCE_SETTINGS),
        "status": status,
        "error": error,
        "group_key": group_key,
        "is_fastener": False,
        "is_possible": is_possible,
    }
