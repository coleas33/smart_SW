"""Read a `probe remodel` capabilities ledger (feature 004 T336; not written yet, T337)."""

from __future__ import annotations

from typing import Any

FROZEN_INTEROP_VERSION = ""
SW_VERSIONS: tuple[str, ...] = ()
START_SWITCH = ""
START_PROBES: tuple[str, ...] = ("PROBE-1", "PROBE-2", "PROBE-3", "PROBE-4", "PROBE-12")


class LedgerRefused(ValueError):
    """A ledger this reader will not judge."""


def parse_ledger(text: str) -> Any:
    raise NotImplementedError("004 T337")


def load_ledger(path: Any) -> Any:
    raise NotImplementedError("004 T337")


def path_kind(text: str) -> str | None:
    raise NotImplementedError("004 T337")


def start_readiness(ledger: Any, identity: Any = None) -> Any:
    raise NotImplementedError("004 T337")


def unknown_types(ledger: Any, table: Any = None) -> list[str]:
    raise NotImplementedError("004 T337")
