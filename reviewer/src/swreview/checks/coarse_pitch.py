"""The coarse pitch table and the thread pitch classifier (feature 010 amendment 2026-10-08,
T113; `contracts/fasteners.md` sections 8.1, 8.3 and 8.8, `contracts/coarse-pitch.json`).

The shop uses coarse threads, so a fine pitch is flagged for the engineer to confirm (the
owner's decision 50A). `classify_pitch` puts a thread designation in exactly one class of
section 8.1, in its order:

1. `unreadable`: no designation, or a blank one.
2. `pipe`: `is_pipe_thread` is true, whatever `parse_thread` reads (`1/8-27 NPT`).
3. `unreadable`: text `parse_thread` does not read (`3/8`, `M16xPh3P1.5`).
4. `unknown_size`: read, but its diameter is in no table (`M2.3x0.4`, `M70`).
5. `fine_only_size`: a metric diameter with fine pitches only (`M25`), or `#0`.
6. `coarse`: the size's coarse pitch, or no pitch written (`M8`, by ISO 965-1, which omits
   the coarse pitch from a designation).
7. `fine`: finer than the coarse pitch, or more threads per inch than UNC.
8. `nonstandard`: coarser than the coarse pitch, or fewer threads per inch than UNC.

Classes 1 to 3 come from the text; `CoarsePitchTable.classify` gives classes 4 to 8 for a
thread `parse_thread` read. The size is matched first and then the pitch, so `M10x1.25` is
fine although 1.25 is M8's coarse pitch: a pitch is never compared with the set of coarse
pitches. A unified thread compares as threads per inch within 0.01, never as millimetres
rounded to six places. The parser and the one list of pipe tokens are `checks/fastener.py`'s.

The table is `coarse_pitch.yaml`, pinned to `contracts/coarse-pitch.json`. It lives in its own
module, apart from the check (`checks/thread_pitch.py`), because the name grammar reads it
too, and the check imports the name grammar (research R2.26 D16).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from swreview import units
from swreview.checks.fastener import ThreadSpec, is_pipe_thread, parse_thread
from swreview.ir.models import Quantity

__all__ = [
    "DEFAULT_COARSE_PITCH_PATH",
    "CoarsePitchTable",
    "MetricRow",
    "PitchClass",
    "PitchVerdict",
    "UnifiedRow",
    "UnifiedSize",
    "classify_pitch",
    "coarse_pitch_mm",
    "load_coarse_pitch",
]

DEFAULT_COARSE_PITCH_PATH = Path(__file__).with_name("coarse_pitch.yaml")

PitchClass = Literal[
    "unreadable", "pipe", "unknown_size", "fine_only_size", "coarse", "fine", "nonstandard"
]

SIZE_EPS_MM = 1e-6
"""A metric diameter matches a row's `size_mm` within this (section 8.1)."""
PITCH_EPS_MM = 1e-6
"""A metric pitch equals the coarse pitch within this; beyond it, finer or coarser."""
SIZE_EPS_IN = 0.001
"""A unified diameter matches a row's `diameter_in` within this. Rows are 0.013 in apart."""
TPI_EPS = 0.01
"""Threads per inch equal UNC within this; beyond it, finer or coarser."""


# --- the table ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricRow:
    """One ISO 261 diameter and its coarse pitch."""

    size_mm: float
    coarse_pitch_mm: float

    @property
    def size(self) -> str:
        """The size as a designation names it: `M8`, `M3.5`."""
        return f"M{self.size_mm:g}"


@dataclass(frozen=True)
class UnifiedRow:
    """One ASME B1.1 size, its diameter in inches and its UNC threads per inch."""

    size: str
    diameter_in: float
    unc_tpi: float


@dataclass(frozen=True)
class UnifiedSize:
    """A unified size with no UNC thread (`#0`)."""

    size: str
    diameter_in: float


@dataclass(frozen=True)
class PitchVerdict:
    """One thread designation's class (section 8.1) and the table row it was judged against."""

    pitch_class: PitchClass
    spec: ThreadSpec | None
    """`parse_thread`'s reading; `None` for no designation and for a pipe thread, which are
    classified before the text is parsed."""
    size: str | None = None
    """The table's size (`M8`, `1/4`, `#10`, `#0`) for classes 5 to 8; else `None`."""
    coarse_pitch_mm: float | None = None
    """A metric size's coarse pitch, for classes 6 to 8."""
    unc_tpi: float | None = None
    """A unified size's UNC threads per inch, for classes 6 to 8."""
    coarse_designation: str | None = None
    """The coarse thread of the size (`M8x1.25`, `M6x1`, `1/4-20`, `#10-24`), for classes 6 to
    8; a fine-only size has none."""
    no_pitch_written: bool = False
    """True when `parse_thread` read a metric size and no pitch (`M8`, `M8-6H`). A coarse
    verdict on such a thread rests on ISO 965-1, which omits the coarse pitch from a
    designation, and the check says so (section 8.6)."""


def _metric_verdict(pitch_class: PitchClass, spec: ThreadSpec, row: MetricRow) -> PitchVerdict:
    return PitchVerdict(
        pitch_class=pitch_class,
        spec=spec,
        size=row.size,
        coarse_pitch_mm=row.coarse_pitch_mm,
        coarse_designation=f"{row.size}x{row.coarse_pitch_mm:g}",
        no_pitch_written=spec.pitch_mm is None,
    )


def _unified_verdict(pitch_class: PitchClass, spec: ThreadSpec, row: UnifiedRow) -> PitchVerdict:
    return PitchVerdict(
        pitch_class=pitch_class,
        spec=spec,
        size=row.size,
        unc_tpi=row.unc_tpi,
        coarse_designation=f"{row.size}-{row.unc_tpi:g}",
    )


@dataclass(frozen=True)
class CoarsePitchTable:
    """`coarse_pitch.yaml`: the ISO 261 coarse pitches and the ASME B1.1 UNC threads per inch."""

    version: int
    source: str
    standards: Mapping[str, str]
    metric: tuple[MetricRow, ...]
    metric_fine_only_mm: tuple[float, ...]
    unified: tuple[UnifiedRow, ...]
    unified_fine_only: tuple[UnifiedSize, ...]

    def metric_row(self, diameter_mm: float) -> MetricRow | None:
        """The row of a metric diameter, matched within `SIZE_EPS_MM`, or `None` when the
        diameter has no coarse pitch (a fine-only or an unknown size)."""
        for row in self.metric:
            if abs(row.size_mm - diameter_mm) <= SIZE_EPS_MM:
                return row
        return None

    def classify(self, spec: ThreadSpec) -> PitchVerdict:
        """The table's verdict on a thread `parse_thread` read: classes 4 to 8 of section 8.1.

        Raises `ValueError` for a thread the parser did not read, whose class (3) is
        `classify_pitch`'s, and for a unified thread with no pitch, which `parse_thread` never
        gives: a unified designation always states its threads per inch.
        """
        if spec.series is None or spec.nominal_diameter is None:
            raise ValueError(f"{spec.text!r} is not a recognised thread, so no table judges it")
        if spec.series == "metric":
            return self._classify_metric(spec, units.as_mm(spec.nominal_diameter))
        return self._classify_unified(
            spec, units.convert(spec.nominal_diameter, "in").converted.value
        )

    def _classify_metric(self, spec: ThreadSpec, diameter_mm: float) -> PitchVerdict:
        no_pitch_written = spec.pitch_mm is None
        row = self.metric_row(diameter_mm)
        if row is None:
            for size_mm in self.metric_fine_only_mm:
                if abs(size_mm - diameter_mm) <= SIZE_EPS_MM:
                    return PitchVerdict(
                        pitch_class="fine_only_size",
                        spec=spec,
                        size=f"M{size_mm:g}",
                        no_pitch_written=no_pitch_written,
                    )
            return PitchVerdict(
                pitch_class="unknown_size", spec=spec, no_pitch_written=no_pitch_written
            )
        if spec.pitch_mm is None:
            # ISO 965-1 omits the coarse pitch from a designation: `M8` is M8x1.25 (50A).
            return _metric_verdict("coarse", spec, row)
        if abs(spec.pitch_mm - row.coarse_pitch_mm) <= PITCH_EPS_MM:
            return _metric_verdict("coarse", spec, row)
        if spec.pitch_mm < row.coarse_pitch_mm:
            return _metric_verdict("fine", spec, row)
        return _metric_verdict("nonstandard", spec, row)

    def _classify_unified(self, spec: ThreadSpec, diameter_in: float) -> PitchVerdict:
        if spec.pitch_mm is None:
            raise ValueError(
                f"{spec.text!r} is a unified thread with no threads per inch, which "
                "parse_thread never reads"
            )
        for row in self.unified:
            if abs(row.diameter_in - diameter_in) <= SIZE_EPS_IN:
                # Threads per inch, 25.4 / pitch_mm: one over the pitch in inches. More threads
                # per inch is a finer thread.
                pitch = Quantity(value=float(spec.pitch_mm), unit="mm")
                threads_per_inch = 1.0 / units.convert(pitch, "in").converted.value
                if abs(threads_per_inch - row.unc_tpi) <= TPI_EPS:
                    return _unified_verdict("coarse", spec, row)
                if threads_per_inch > row.unc_tpi:
                    return _unified_verdict("fine", spec, row)
                return _unified_verdict("nonstandard", spec, row)
        for fine_only in self.unified_fine_only:
            if abs(fine_only.diameter_in - diameter_in) <= SIZE_EPS_IN:
                return PitchVerdict(pitch_class="fine_only_size", spec=spec, size=fine_only.size)
        return PitchVerdict(pitch_class="unknown_size", spec=spec)


# --- the loader --------------------------------------------------------------------------------

_KEYS = (
    "version",
    "source",
    "standards",
    "metric",
    "metric_fine_only_mm",
    "unified",
    "unified_fine_only",
)
_STANDARDS = ("metric", "unified")


# Known repetition: `_positive` is `checks/tool_access.py`'s word for word. Each loader keeps
# its parse helpers private; one shared loader helper would be its own change, touching both.
def _positive(value: object, name: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{path}: {name} must be a positive number, got {value!r}")
    return float(value)


def _text(value: object, name: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {name} must be a non-empty text, got {value!r}")
    return value


def _list(document: Mapping[str, object], key: str, path: Path) -> Sequence[object]:
    value = document[key]
    if not isinstance(value, list):
        raise ValueError(f"{path}: {key} must be a list, got {value!r}")
    return value


def _rows(
    document: Mapping[str, object], key: str, fields: tuple[str, ...], path: Path
) -> list[tuple[str, Mapping[str, object]]]:
    """Each row of `key`, named `{key} row {n}` from 1, once it carries every field."""
    rows = []
    for number, row in enumerate(_list(document, key, path), start=1):
        name = f"{key} row {number}"
        if not isinstance(row, Mapping):
            raise ValueError(f"{path}: {name} must be a mapping, got {row!r}")
        for field in fields:
            if field not in row:
                raise ValueError(f"{path}: {name} carries no {field}")
        rows.append((name, row))
    return rows


def _ascending(values: Sequence[float], key: str, path: Path) -> None:
    for previous, current in zip(values, values[1:], strict=False):
        if current <= previous:
            raise ValueError(
                f"{path}: {key} must be in ascending order, each size once: "
                f"{current:g} follows {previous:g}"
            )


def _parse(document: object, path: Path) -> CoarsePitchTable:
    if not isinstance(document, Mapping):
        raise ValueError(f"{path}: the coarse pitch table must be a mapping")
    for key in _KEYS:
        if key not in document:
            raise ValueError(f"{path}: {key} is missing")

    version = document["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise ValueError(f"{path}: version must be a positive whole number, got {version!r}")
    standards = document["standards"]
    if not isinstance(standards, Mapping):
        raise ValueError(f"{path}: standards must be a mapping, got {standards!r}")
    for name in _STANDARDS:
        if name not in standards:
            raise ValueError(f"{path}: standards carries no {name}")

    metric = tuple(
        MetricRow(
            size_mm=_positive(row["size_mm"], f"{name}: size_mm", path),
            coarse_pitch_mm=_positive(row["coarse_pitch_mm"], f"{name}: coarse_pitch_mm", path),
        )
        for name, row in _rows(document, "metric", ("size_mm", "coarse_pitch_mm"), path)
    )
    metric_fine_only_mm = tuple(
        _positive(size, f"metric_fine_only_mm entry {number}:", path)
        for number, size in enumerate(_list(document, "metric_fine_only_mm", path), start=1)
    )
    unified = tuple(
        UnifiedRow(
            size=_text(row["size"], f"{name}: size", path),
            diameter_in=_positive(row["diameter_in"], f"{name}: diameter_in", path),
            unc_tpi=_positive(row["unc_tpi"], f"{name}: unc_tpi", path),
        )
        for name, row in _rows(document, "unified", ("size", "diameter_in", "unc_tpi"), path)
    )
    unified_fine_only = tuple(
        UnifiedSize(
            size=_text(row["size"], f"{name}: size", path),
            diameter_in=_positive(row["diameter_in"], f"{name}: diameter_in", path),
        )
        for name, row in _rows(document, "unified_fine_only", ("size", "diameter_in"), path)
    )

    _ascending([row.size_mm for row in metric], "metric", path)
    _ascending(metric_fine_only_mm, "metric_fine_only_mm", path)
    _ascending([row.diameter_in for row in unified], "unified", path)
    _ascending([row.diameter_in for row in unified_fine_only], "unified_fine_only", path)

    # A size both coarse and fine-only would have two classes; the sizes are matched as the
    # classifier matches them.
    for size_mm in metric_fine_only_mm:
        for row in metric:
            if abs(row.size_mm - size_mm) <= SIZE_EPS_MM:
                raise ValueError(f"{path}: {row.size} is in both metric and metric_fine_only_mm")
    for fine_only in unified_fine_only:
        for row in unified:
            same_diameter = abs(row.diameter_in - fine_only.diameter_in) <= SIZE_EPS_IN
            if row.size == fine_only.size or same_diameter:
                raise ValueError(
                    f"{path}: unified_fine_only {fine_only.size} ({fine_only.diameter_in:g} in) "
                    f"is unified {row.size} ({row.diameter_in:g} in) too"
                )

    return CoarsePitchTable(
        version=version,
        source=_text(document["source"], "source", path),
        standards={name: _text(standards[name], f"standards {name}", path) for name in _STANDARDS},
        metric=metric,
        metric_fine_only_mm=metric_fine_only_mm,
        unified=unified,
        unified_fine_only=unified_fine_only,
    )


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> CoarsePitchTable:
    return _parse(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_coarse_pitch(path: Path | str | None = None) -> CoarsePitchTable:
    """Read the coarse pitch table; `path` defaults to the one beside this module.

    Results are cached per resolved path: the table is read once per process.
    """
    return _load_cached(Path(path or DEFAULT_COARSE_PITCH_PATH).resolve())


# --- the classifier ----------------------------------------------------------------------------


def classify_pitch(designation: str | None, table: CoarsePitchTable | None = None) -> PitchVerdict:
    """The class of a thread designation (section 8.1), against the shipped table by default.

    Classes 1 to 3 come from the text: no designation or a blank one is `unreadable`; a pipe
    thread (`is_pipe_thread`) is `pipe` whatever `parse_thread` reads; text `parse_thread` does
    not read is `unreadable`, carrying its parse. Every other designation's parse goes to
    `CoarsePitchTable.classify`.
    """
    if designation is None or not designation.strip():
        return PitchVerdict(pitch_class="unreadable", spec=None)
    if is_pipe_thread(designation):
        return PitchVerdict(pitch_class="pipe", spec=None)
    spec = parse_thread(designation)
    if not spec.recognized:
        return PitchVerdict(pitch_class="unreadable", spec=spec)
    return (table or load_coarse_pitch()).classify(spec)


def coarse_pitch_mm(diameter_mm: float, table: CoarsePitchTable | None = None) -> float | None:
    """A metric diameter's coarse pitch, or `None` for a fine-only or an unknown size: what the
    name grammar reads to tell a pitch from a length (section 8.8)."""
    row = (table or load_coarse_pitch()).metric_row(diameter_mm)
    return None if row is None else row.coarse_pitch_mm
