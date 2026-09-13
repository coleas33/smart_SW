"""Load an exported body mesh into a single trimesh in metres (research R7).

GLB is the interchange format the extractor writes: it carries the node transform in
metres, so a GLB with no declared unit is read as metres. STL carries no unit at all, so
an STL without an explicit `units` argument is refused rather than guessed - an STL read
as metres when it was written in millimetres is a silent factor-of-1000 error in every
clearance that follows (constitution Principle I).
"""

from __future__ import annotations

from pathlib import Path

import trimesh

from swreview.ir.models import LengthUnit, Quantity
from swreview.units import as_mm

__all__ = ["SUPPORTED_SUFFIXES", "load_mesh"]

SUPPORTED_SUFFIXES: tuple[str, ...] = (".glb", ".stl")
_UNITLESS_SUFFIXES: tuple[str, ...] = (".stl",)


def _scale_to_metres(units: LengthUnit) -> float:
    """Metres per `units`, obtained from the one unit registry the project allows."""
    return as_mm(Quantity(value=1.0, unit=units)) / 1000.0


def load_mesh(path: Path | str, units: LengthUnit | None = None) -> trimesh.Trimesh:
    """Load `path` as one `Trimesh` whose vertices are in metres.

    `units` names the unit the file's numbers are in. It may be omitted for GLB, which
    the extractor writes in metres; it is required for STL.

    Raises `FileNotFoundError` when the file is absent, and `ValueError` for an
    unsupported extension or an STL with no declared unit.
    """
    mesh_path = Path(path)
    suffix = mesh_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"{mesh_path.name}: unsupported mesh format {suffix!r}; "
            f"expected one of {SUPPORTED_SUFFIXES} (glb preferred)"
        )
    if not mesh_path.is_file():
        raise FileNotFoundError(f"no mesh file at {mesh_path}")
    if units is None and suffix in _UNITLESS_SUFFIXES:
        raise ValueError(
            f"{mesh_path.name}: an STL carries no unit; pass units='mm', 'in' or 'm' "
            "explicitly rather than assuming one"
        )

    loaded = trimesh.load(mesh_path, force="mesh")
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError(f"{mesh_path.name}: file holds no triangle mesh")

    if units is not None and units != "m":
        loaded.apply_scale(_scale_to_metres(units))
    return loaded
