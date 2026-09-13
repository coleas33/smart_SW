"""Loader for `tool_envelopes.yaml`, the cylinder each driving tool sweeps (T090).

The same shape as `engagement_rules.py` and for the same reason: the number that decides
whether a driver fits is data an engineer can read and change, and every result cites the
row it used. The table ships as pilot defaults, which the `source` line of every row says
out loud - a clearance cleared against a guessed tool size would be exactly the kind of
unearned pass the constitution forbids (Principle I).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

__all__ = [
    "DEFAULT_ENVELOPES_PATH",
    "ToolEnvelope",
    "ToolEnvelopes",
    "envelope_radius_mm",
    "load_envelopes",
]

DEFAULT_ENVELOPES_PATH = Path(__file__).with_name("tool_envelopes.yaml")


@dataclass(frozen=True)
class ToolEnvelope:
    """One tool: how wide it is as a multiple of d, and where that number came from."""

    name: str
    envelope_diameter_ratio: float
    source: str


@dataclass(frozen=True)
class ToolEnvelopes:
    """The whole table, plus the one clearance every tool gets."""

    version: int
    clearance_mm: float
    tools: dict[str, ToolEnvelope]

    def radius_mm(self, tool: str, nominal_diameter_mm: float) -> float:
        """The swept radius for `tool` on a fastener of diameter `nominal_diameter_mm`.

        `envelope_diameter_ratio` is a diameter multiple, so the radius is half of it,
        plus the table's clearance. Raises `KeyError` for a tool the table does not
        carry and `ValueError` for a non-positive diameter: a zero-radius envelope would
        sweep nothing and report "clear".
        """
        if tool not in self.tools:
            raise KeyError(
                f"no tool envelope for {tool!r}; the table carries {sorted(self.tools)}"
            )
        if nominal_diameter_mm <= 0.0:
            raise ValueError(
                f"nominal diameter must be positive, got {nominal_diameter_mm}"
            )
        ratio = self.tools[tool].envelope_diameter_ratio
        return ratio * nominal_diameter_mm / 2.0 + self.clearance_mm


def _parse(document: object, path: Path) -> ToolEnvelopes:
    if not isinstance(document, dict):
        raise ValueError(f"{path}: tool envelopes must be a mapping")

    tools: dict[str, ToolEnvelope] = {}
    for name, row in document["tools"].items():
        ratio = float(row["envelope_diameter_ratio"])
        if ratio <= 0.0:
            raise ValueError(
                f"{path}: envelope_diameter_ratio for {name!r} must be positive, got {ratio}"
            )
        tools[name] = ToolEnvelope(
            name=name, envelope_diameter_ratio=ratio, source=row["source"]
        )
    if not tools:
        raise ValueError(f"{path}: the table carries no tools")

    clearance = float(document["clearance_mm"])
    if clearance < 0.0:
        raise ValueError(f"{path}: clearance_mm must not be negative, got {clearance}")
    return ToolEnvelopes(
        version=int(document["version"]), clearance_mm=clearance, tools=tools
    )


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> ToolEnvelopes:
    return _parse(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_envelopes(path: Path | str | None = None) -> ToolEnvelopes:
    """Read the tool envelope table, defaulting to the one that ships with the package."""
    return _load_cached(Path(path) if path is not None else DEFAULT_ENVELOPES_PATH)


def envelope_radius_mm(
    tool: str, nominal_diameter_mm: float, envelopes: ToolEnvelopes | None = None
) -> float:
    """The swept radius for one tool on one fastener size, from the shipped table."""
    return (envelopes or load_envelopes()).radius_mm(tool, nominal_diameter_mm)
