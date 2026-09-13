"""Read drawing PDFs into `DrawingSheet`s (T035).

PyMuPDF gives every text span with its bounding box (research R8). A SOLIDWORKS
dimension is not one span: the nominal, its symbol and its tolerance are separate text
objects placed next to each other, and a bilateral tolerance is stacked above and below
the nominal's baseline. This module puts them back together by position, hands each
cluster to `dimension_grammar`, and reports what it could not read:

- a page with no text spans is `parse_status="no_text"` plus a `Gap`; it was exported
  flattened, and an empty sheet and an unreadable sheet must never look alike;
- a page whose title block states no units yields no dimensions and a `Gap`: a number
  with no unit is not evidence (constitution Principle I);
- any exception is `parse_status="failed"` plus a `Gap` carrying the error.

Every dimension and every note is given a stable `annotation` on its `SourceRef` -
`dim-<page>-<n>` and `note-<page>-<n>`, numbered from one in reading order down the page
- because that is the only way a check tool can name one: `check_fit` and
`check_axial_stack` address a dimension as `document_id:sheet:annotation`, and a parsed
sheet whose dimensions carry no annotation cannot be checked at all. The ids come from
position, not from content, so re-parsing the same PDF yields the same ids; editing the
drawing may renumber them, which is why a finding also records the callout it read.

`views` is left empty in this phase. Mapping spans to drawing views is a heuristic
(research R8) whose output would be `suspected` at best, and no check consumes it yet;
hole and BOM tables (pdfplumber) are likewise deferred until a check needs them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import pymupdf

from swreview.ingest.dimension_grammar import (
    SheetUnits,
    looks_like_dimension,
    normalize_text,
    parse_dimensions,
)
from swreview.ir.models import Dimension, DrawingSheet, Gap, Note, SourceRef

__all__ = ["NOTE_PREFIXES", "parse_drawing_pdf"]

PARSER = f"pymupdf/{pymupdf.pymupdf_version}"

NOTE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("UNLESS OTHERWISE SPECIFIED", "general_tolerance"),
    ("TOLERANCES", "general_tolerance"),
    ("MATERIAL:", "material"),
    ("FINISH:", "finish"),
    ("NOTES", "other"),
)
"""Line prefixes that make a line a general note, with the `Note.kind` each implies."""

_UNITS_STATEMENT = re.compile(
    r"\bUNITS?\b\s*[:=]?\s*(MILLIMET(?:ER|RE)S?|MM|INCH(?:ES)?|IN)\b"
)
_MILLIMETRES = re.compile(r"\bMILLIMET(?:ER|RE)S?\b|\bMM\b")
_INCHES = re.compile(r"\bINCH(?:ES)?\b")
_SCALE = re.compile(r"\bSCALE\b\s*[:=]?\s*(\d+\s*:\s*\d+)")
_TOLERANCE_FRAGMENT = re.compile(r"^[+\-±]")

_ROW_BASELINE = 0.35
"""Baselines within this fraction of the font size belong to the same row."""
_ROW_GAP = 1.5
"""A horizontal gap up to this many font sizes still joins one callout."""
_STACK_BASELINE = 1.6
"""A tolerance fragment may sit this many font sizes above or below its nominal."""
_STACK_GAP = 3.0
"""A stacked tolerance fragment starts within this many font sizes of the nominal."""


class _Cluster:
    """Text fragments that belong to one callout, with their combined bounding box."""

    def __init__(self, text: str, bbox: list[float], size: float, baseline: float) -> None:
        self.parts: list[tuple[float, float, str]] = [(bbox[0], baseline, text)]
        self.bbox = list(bbox)
        self.size = size
        self.baseline = baseline

    @property
    def text(self) -> str:
        ordered = sorted(self.parts, key=lambda part: (part[0], part[1]))
        return " ".join(part[2] for part in ordered)

    def absorb(self, other: _Cluster) -> None:
        self.parts.extend(other.parts)
        self.bbox = [
            min(self.bbox[0], other.bbox[0]),
            min(self.bbox[1], other.bbox[1]),
            max(self.bbox[2], other.bbox[2]),
            max(self.bbox[3], other.bbox[3]),
        ]
        self.size = max(self.size, other.size)


def parse_drawing_pdf(
    path: Path | str,
    document_id: str,
    sheet_units_hint: SheetUnits | None = None,
    gaps: list[Gap] | None = None,
) -> list[DrawingSheet]:
    """Parse every page of the drawing PDF at `path` into a `DrawingSheet`.

    `sheet_units_hint` is used only when the sheet's own title block states no units.
    `gaps`, when given, receives one `Gap` for every page that did not parse and for
    every page whose callouts had to be dropped for want of units; the sheets come back
    either way, so a caller that ignores gaps still sees `parse_status`.
    """
    collected: list[Gap] = [] if gaps is None else gaps
    drawing = Path(path)
    try:
        document = pymupdf.open(drawing)
    except Exception as exc:  # noqa: BLE001 - any failure is reported, never raised
        collected.append(_failure_gap(document_id, 1, drawing, exc))
        return [_empty_sheet(document_id, 1, "failed")]

    sheets: list[DrawingSheet] = []
    try:
        for number, page in enumerate(document, start=1):
            try:
                sheets.append(_parse_page(page, number, document_id, sheet_units_hint, collected))
            except Exception as exc:  # noqa: BLE001 - one bad page does not lose the rest
                collected.append(_failure_gap(document_id, number, drawing, exc))
                sheets.append(_empty_sheet(document_id, number, "failed"))
    finally:
        document.close()
    return sheets


def _parse_page(
    page: pymupdf.Page,
    number: int,
    document_id: str,
    sheet_units_hint: SheetUnits | None,
    gaps: list[Gap],
) -> DrawingSheet:
    """One page: units, notes, clustered dimensions, or a `no_text` sheet."""
    rows = _rows(page)
    if not rows:
        gaps.append(
            Gap(
                kind="no_text",
                entity_kind="drawing_sheet",
                entity_id=f"{document_id}:{number}",
                reason=(
                    f"page {number} of {document_id} has no text layer; it was exported "
                    "flattened and nothing on it could be read"
                ),
                error=None,
            )
        )
        return _empty_sheet(document_id, number, "no_text")

    sheet_name = f"Sheet{number}"
    page_text = "\n".join(row.text for row in rows).upper()
    units = _units(page_text, sheet_units_hint)
    scale = _scale(page_text)

    notes: list[Note] = []
    remaining: list[_Cluster] = []
    for row in rows:
        kind = _note_kind(row.text)
        if kind is None:
            remaining.append(row)
            continue
        notes.append(
            Note(
                text=row.text,
                source=_source(
                    document_id,
                    sheet_name,
                    number,
                    row.bbox,
                    annotation=f"note-{number}-{len(notes) + 1}",
                ),
                kind=kind,
            )
        )

    dimensions: list[Dimension] = []
    unreadable = 0
    for cluster in _reading_order(_stack(remaining)):
        source = _source(document_id, sheet_name, number, cluster.bbox)
        parsed = parse_dimensions(cluster.text, units, source)
        if parsed:
            first = len(dimensions) + 1
            dimensions.extend(
                _annotated(dimension, f"dim-{number}-{first + index}")
                for index, dimension in enumerate(parsed)
            )
        elif looks_like_dimension(cluster.text):
            unreadable += 1

    if unreadable:
        gaps.append(
            Gap(
                kind="not_extracted",
                entity_kind="dimension",
                entity_id=f"{document_id}:{number}",
                reason=(
                    f"{unreadable} callout(s) on page {number} of {document_id} state a "
                    f"length but the sheet states no unit; no unit was assumed for them"
                    if units == "unknown"
                    else f"{unreadable} callout(s) on page {number} of {document_id} "
                    "could not be read by the dimension grammar"
                ),
                error=None,
            )
        )

    return DrawingSheet(
        document_id=document_id,
        sheet_name=sheet_name,
        page=number,
        scale=scale,
        units=units,
        general_notes=notes,
        dimensions=dimensions,
        views=[],
        parse_status="text",
        parser=PARSER,
    )


def _rows(page: pymupdf.Page) -> list[_Cluster]:
    """Spans grouped into rows: same baseline, no more than `_ROW_GAP` font sizes apart."""
    fragments: list[_Cluster] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                fragments.append(
                    _Cluster(text, list(span["bbox"]), float(span["size"]), span["origin"][1])
                )

    fragments.sort(key=lambda fragment: (fragment.baseline, fragment.bbox[0]))
    rows: list[_Cluster] = []
    for fragment in fragments:
        for row in rows:
            same_row = abs(row.baseline - fragment.baseline) <= _ROW_BASELINE * row.size
            gap = fragment.bbox[0] - row.bbox[2]
            if same_row and gap <= _ROW_GAP * row.size:
                row.absorb(fragment)
                break
        else:
            rows.append(fragment)
    return rows


def _stack(rows: list[_Cluster]) -> list[_Cluster]:
    """Attach stacked `+x` / `-y` tolerance fragments to the nominal they belong to."""
    clusters: list[_Cluster] = []
    for row in sorted(rows, key=lambda row: (row.bbox[0], row.baseline)):
        if _TOLERANCE_FRAGMENT.match(row.text):
            anchor = _nearest_nominal(clusters, row)
            if anchor is not None:
                anchor.absorb(row)
                continue
        clusters.append(row)
    return clusters


def _nearest_nominal(clusters: list[_Cluster], fragment: _Cluster) -> _Cluster | None:
    """The closest cluster a tolerance fragment can belong to, or `None`."""
    best: _Cluster | None = None
    best_distance = float("inf")
    for cluster in clusters:
        if _TOLERANCE_FRAGMENT.match(cluster.text):
            continue
        size = max(cluster.size, fragment.size)
        vertical = abs(cluster.baseline - fragment.baseline)
        horizontal = max(
            cluster.bbox[0] - fragment.bbox[2], fragment.bbox[0] - cluster.bbox[2], 0.0
        )
        if vertical > _STACK_BASELINE * size or horizontal > _STACK_GAP * size:
            continue
        distance = vertical + horizontal
        if distance < best_distance:
            best, best_distance = cluster, distance
    return best


def _note_kind(text: str) -> Literal["general_tolerance", "material", "finish", "other"] | None:
    """The `Note.kind` a line's prefix implies, or `None` when it is not a note."""
    upper = text.upper().lstrip()
    for prefix, kind in NOTE_PREFIXES:
        if upper.startswith(prefix):
            return kind  # type: ignore[return-value]
    return None


def _units(page_text: str, hint: SheetUnits | None) -> SheetUnits:
    """Units from the title block; the hint only when the sheet states nothing."""
    statement = _UNITS_STATEMENT.search(page_text)
    if statement is not None:
        return "mm" if statement.group(1).startswith(("MILLIMET", "MM")) else "in"
    if _MILLIMETRES.search(page_text):
        return "mm"
    if _INCHES.search(page_text):
        return "in"
    return hint if hint is not None else "unknown"


def _scale(page_text: str) -> str | None:
    match = _SCALE.search(page_text)
    return normalize_text(match.group(1)).replace(" ", "") if match else None


def _reading_order(clusters: list[_Cluster]) -> list[_Cluster]:
    """Clusters down the page and then across it, which is how the ids are numbered.

    `_stack` works left to right so a stacked tolerance finds the nominal beside it;
    that is an internal order, not the order an engineer reads the sheet in.
    """
    return sorted(clusters, key=lambda cluster: (cluster.baseline, cluster.bbox[0]))


def _annotated(dimension: Dimension, annotation: str) -> Dimension:
    """`dimension` with `annotation` on its source, so a check tool can address it.

    A tolerance read from the same callout carries the same source and is re-stamped with
    it; a tolerance that came from somewhere else - a general note - keeps its own.
    """
    source = dimension.source.model_copy(update={"annotation": annotation})
    tolerance = dimension.tolerance
    if tolerance.source == dimension.source:
        tolerance = tolerance.model_copy(update={"source": source})
    return dimension.model_copy(update={"source": source, "tolerance": tolerance})


def _source(
    document_id: str,
    sheet_name: str,
    page: int,
    bbox: list[float],
    annotation: str | None = None,
) -> SourceRef:
    return SourceRef(
        document_id=document_id,
        sheet=sheet_name,
        page=page,
        annotation=annotation,
        bbox=[float(value) for value in bbox],
    )


def _empty_sheet(
    document_id: str, page: int, status: Literal["no_text", "failed"]
) -> DrawingSheet:
    return DrawingSheet(
        document_id=document_id,
        sheet_name=f"Sheet{page}",
        page=page,
        scale=None,
        units="unknown",
        general_notes=[],
        dimensions=[],
        views=[],
        parse_status=status,
        parser=PARSER,
    )


def _failure_gap(document_id: str, page: int, path: Path, exc: Exception) -> Gap:
    return Gap(
        kind="tool_error",
        entity_kind="drawing_sheet",
        entity_id=f"{document_id}:{page}",
        reason=f"{path.name} could not be parsed; nothing on page {page} was read",
        error=f"{type(exc).__name__}: {exc}",
    )
