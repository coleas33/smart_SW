"""Grammar for SOLIDWORKS drawing dimension text (T034).

Drawing callouts are short, positional and unforgiving: `Ø10.00 ±0.02`,
`10.02/10.00`, `M6x1.0 - 6H ↧ 12`, `45° ±0°30'`. This module turns one callout
string into a `Dimension`, and refuses to turn anything else into one.

Three rules follow from the constitution (Principle I):

- a tolerance that is not written on the drawing is `kind="none"`, never zero and never
  looked up: a fit class such as `H7` is kept as read in `Callout.fit_class` and
  expanded by nobody;
- a length needs a unit, and the unit comes from the sheet's title block. With
  `sheet_units="unknown"` a length callout yields `None` (the caller records a `Gap`);
  an angle still parses, because degrees are written on the callout itself;
- `text_as_read` is the caller's string, byte for byte, so the engineer checks the
  parse against the sheet.

The grammar reads the callouts the pilot drawings contain. Metric threads are
understood; unified threads are not, and are reported as unparsed rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from swreview.ir.models import Angle, Dimension, Quantity, SourceRef, Tolerance

__all__ = [
    "Callout",
    "SheetUnits",
    "ThreadCallout",
    "ToleranceSpec",
    "looks_like_dimension",
    "normalize_text",
    "parse_callout",
    "parse_dimension_text",
    "parse_dimensions",
    "parse_thread_callout",
]

SheetUnits = Literal["mm", "in", "unknown"]
ToleranceKind = Literal["symmetric", "bilateral", "limits", "basic", "none"]
Feature = Literal[
    "linear", "diameter", "radius", "angular", "counterbore", "countersink", "thread"
]

DIAMETER = "Ø"  # LATIN CAPITAL LETTER O WITH STROKE, what SOLIDWORKS emits
DIAMETER_SIGN = "⌀"  # DIAMETER SIGN, what some PDF producers emit
DEPTH = "↧"  # DOWNWARDS ARROW FROM BAR
COUNTERBORE = "⌴"
COUNTERSINK = "⌵"
DEGREE = "°"
PLUS_MINUS = "±"

_NUM = r"(?:\d+(?:\.\d+)?|\.\d+)"
_ANGLE = rf"(?P<deg>{_NUM}){DEGREE}(?:\s*(?P<min>{_NUM})')?(?:\s*(?P<sec>{_NUM})\")?"

_COUNT = re.compile(r"^(\d+)\s*[X×]\s+")
_CHAMFER_TAIL = re.compile(rf"^{_NUM}\s*{DEGREE}")
_LIMITS = re.compile(rf"^({_NUM})\s*/\s*{DIAMETER}?\s*({_NUM})$")
_ANGULAR_NOMINAL = re.compile(rf"^({_NUM})\s*{DEGREE}")
_NOMINAL = re.compile(rf"^({_NUM})")
_DEPTH = re.compile(rf"{DEPTH}\s*({_NUM})")
_SYMMETRIC_ANGLE = re.compile(rf"{PLUS_MINUS}\s*{_ANGLE}")
_SYMMETRIC = re.compile(rf"{PLUS_MINUS}\s*({_NUM})")
_BILATERAL_SLASH = re.compile(rf"\+\s*({_NUM})\s*/\s*-\s*({_NUM})")
_BILATERAL_SPACED = re.compile(rf"\+\s*({_NUM})\s+-\s*({_NUM})")
_UPPER_ONLY = re.compile(rf"\+\s*({_NUM})")
_LOWER_ONLY = re.compile(rf"-\s*({_NUM})")
_THREAD = re.compile(
    r"^(?P<size>M\d+(?:\.\d+)?)(?:\s*[x×X]\s*(?P<pitch>\d+(?:\.\d+)?))?"
    r"(?:\s*-\s*(?P<cls>\d[A-Za-z]|[A-Za-z]\d))?(?P<rest>\b.*)$"
)
_FIT_CLASS = re.compile(r"^(?:[A-Za-z]{1,2}\d{1,2}|\d{1,2}[A-Za-z])$")

_MODIFIERS = frozenset(
    {"THRU", "THROUGH", "TYP", "REF", "MIN", "MAX", "PL", "PLACES", "NOM"}
)
_SYMBOL_FEATURES: dict[str, Feature] = {
    DIAMETER: "diameter",
    COUNTERBORE: "counterbore",
    COUNTERSINK: "countersink",
    "R": "radius",
}


@dataclass(frozen=True)
class ToleranceSpec:
    """A tolerance as written.

    For `symmetric` and `bilateral`, `upper` and `lower` are signed deviations from the
    nominal; for `limits` they are the limits themselves. `None` means that side was not
    written. `is_angular` marks values in degrees.
    """

    kind: ToleranceKind
    upper: float | None
    lower: float | None
    is_angular: bool = False


@dataclass(frozen=True)
class ThreadCallout:
    """A metric thread callout: `M6x1.0 - 6H ↧ 12`.

    `depth` is the number as written; its unit is the sheet's. `None` means the callout
    states no depth - the case the fastener checks must never fill in from a drill depth.
    """

    text: str
    designation: str
    thread_class: str | None
    depth: float | None


@dataclass(frozen=True)
class Callout:
    """One parsed drawing callout, before units are applied."""

    text: str
    count: int | None
    feature: Feature
    nominal: float | None
    is_angular: bool
    tolerance: ToleranceSpec
    depth: float | None
    fit_class: str | None
    modifiers: tuple[str, ...]
    thread: ThreadCallout | None


_NO_TOLERANCE = ToleranceSpec(kind="none", upper=None, lower=None)


def normalize_text(text: str) -> str:
    """Map ASCII fallbacks onto the drawing symbols and collapse whitespace.

    PDF producers emit either the symbol or its ASCII spelling: `DIA` for `Ø`, `+/-`
    for `±`, `DEG` for `°`, `DEPTH` for `↧`. Multi-line callouts arrive with
    newlines between the nominal and its tolerance.
    """
    normalized = text.replace(DIAMETER_SIGN, DIAMETER)
    normalized = re.sub(r"\bDIA\b\.?\s*", DIAMETER, normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("+/-", PLUS_MINUS).replace("+-", PLUS_MINUS)
    normalized = re.sub(r"\s*\bDEG(?:REES?)?\b\.?", DEGREE, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bDEPTH\b|\bDP\b", DEPTH, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bC'?BORE\b", COUNTERBORE, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bCSK\b", COUNTERSINK, normalized, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", normalized).strip()


def parse_callout(text: str) -> Callout | None:
    """Parse one callout string, or return `None` when it is not a dimension callout.

    Anything the grammar does not fully account for is rejected: a leftover token is a
    callout this build does not understand, and a partly-understood callout is worse
    than none.
    """
    body = normalize_text(text)
    if not body:
        return None

    count, body = _strip_count(body)
    thread = _parse_thread(body)
    if thread is not None:
        return Callout(
            text=text,
            count=count,
            feature="thread",
            nominal=thread.depth,
            is_angular=False,
            tolerance=_NO_TOLERANCE,
            depth=thread.depth,
            fit_class=None,
            modifiers=(),
            thread=thread,
        )

    feature, body = _strip_symbols(body)
    return _parse_value(text, count, feature, body)


def parse_thread_callout(text: str) -> ThreadCallout | None:
    """Parse a metric thread callout, or return `None` when `text` is not one."""
    body = normalize_text(text)
    _, body = _strip_count(body)
    return _parse_thread(body)


def looks_like_dimension(text: str) -> bool:
    """Whether `text` is a dimension callout, regardless of whether units are known.

    `pdf_drawing` uses this to tell "not a dimension" apart from "a dimension on a sheet
    whose units are unknown", which is a `Gap` rather than a silent drop.
    """
    return parse_callout(text) is not None


def parse_dimension_text(
    text: str, sheet_units: SheetUnits, source: SourceRef
) -> Dimension | None:
    """The primary `Dimension` of `text`, or `None` when there is none.

    `None` is returned for text that is not a dimension callout, for a callout with no
    numeric value (a thread with no depth), and for a length callout on a sheet whose
    units are unknown.
    """
    dimensions = parse_dimensions(text, sheet_units, source)
    return dimensions[0] if dimensions else None


def parse_dimensions(
    text: str, sheet_units: SheetUnits, source: SourceRef
) -> list[Dimension]:
    """Every `Dimension` stated by one callout, primary value first.

    A callout can state two: `4X ⌴ Ø11 ↧ 6.5` gives the counterbore diameter and
    its depth. Both carry the whole callout as `text_as_read`, because neither number
    means anything without the other.
    """
    callout = parse_callout(text)
    if callout is None:
        return []

    dimensions: list[Dimension] = []
    primary = _build(
        callout.nominal, callout.is_angular, callout.tolerance, text, sheet_units, source
    )
    if primary is not None:
        dimensions.append(primary)
    if callout.depth is not None and callout.depth != callout.nominal:
        depth = _build(callout.depth, False, _NO_TOLERANCE, text, sheet_units, source)
        if depth is not None:
            dimensions.append(depth)
    return dimensions


# --- parsing internals -------------------------------------------------------------


def _strip_count(body: str) -> tuple[int | None, str]:
    """Split a `4X ` instance count off the front of a callout.

    A space after the `X` is required, and a bare angle behind it is read as a chamfer
    (`2X 45°` is 2 mm at 45°, not two of something), so neither is taken as a count.
    """
    match = _COUNT.match(body)
    if match is None:
        return None, body
    rest = body[match.end() :]
    if _CHAMFER_TAIL.match(rest):
        return None, body
    return int(match.group(1)), rest


def _parse_thread(body: str) -> ThreadCallout | None:
    """Parse `M6x1.0 - 6H ↧ 12`; metric only."""
    match = _THREAD.match(body)
    if match is None:
        return None
    rest = match.group("rest").strip()
    depth_match = _DEPTH.search(rest)
    designation = match.group("size")
    if match.group("pitch"):
        designation = f"{designation}x{match.group('pitch')}"
    return ThreadCallout(
        text=body,
        designation=designation,
        thread_class=match.group("cls"),
        depth=float(depth_match.group(1)) if depth_match else None,
    )


def _strip_symbols(body: str) -> tuple[Feature, str]:
    """Consume leading `Ø`, `R`, `⌴`, `⌵`; the first one names the feature."""
    feature: Feature = "linear"
    while body:
        head = body[0]
        if head == "R" and not re.match(r"^R\s*(?:\d|\.\d)", body):
            break
        if head not in _SYMBOL_FEATURES:
            break
        if feature == "linear":
            feature = _SYMBOL_FEATURES[head]
        body = body[1:].lstrip()
    return feature, body


def _parse_value(raw: str, count: int | None, feature: Feature, body: str) -> Callout | None:
    """Nominal, tolerance, depth and modifiers of a non-thread callout."""
    limits = _LIMITS.match(body)
    if limits is not None:
        high, low = sorted((float(limits.group(1)), float(limits.group(2))), reverse=True)
        return Callout(
            text=raw,
            count=count,
            feature=feature,
            nominal=(high + low) / 2.0,
            is_angular=False,
            tolerance=ToleranceSpec(kind="limits", upper=high, lower=low),
            depth=None,
            fit_class=None,
            modifiers=(),
            thread=None,
        )

    is_angular = False
    match = _ANGULAR_NOMINAL.match(body)
    if match is not None:
        is_angular = True
        if feature == "linear":
            feature = "angular"
    else:
        match = _NOMINAL.match(body)
    if match is None:
        return None
    nominal = float(match.group(1))
    rest = body[match.end() :]

    depth_match = _DEPTH.search(rest)
    depth = float(depth_match.group(1)) if depth_match else None
    if depth_match is not None:
        rest = rest[: depth_match.start()] + rest[depth_match.end() :]

    tolerance, rest = _parse_tolerance(rest)
    tolerance = _reconcile(tolerance, is_angular)

    fit_class: str | None = None
    modifiers: list[str] = []
    for token in rest.split():
        upper = token.upper()
        if upper == "BSC":
            tolerance = ToleranceSpec(kind="basic", upper=None, lower=None)
        elif upper in _MODIFIERS:
            modifiers.append(upper)
        elif token == DIAMETER:
            feature = "diameter" if feature == "linear" else feature
        elif _FIT_CLASS.match(token):
            fit_class = token
        else:
            return None

    return Callout(
        text=raw,
        count=count,
        feature=feature,
        nominal=nominal,
        is_angular=is_angular,
        tolerance=tolerance,
        depth=depth,
        fit_class=fit_class,
        modifiers=tuple(modifiers),
        thread=None,
    )


def _parse_tolerance(rest: str) -> tuple[ToleranceSpec, str]:
    """Read the tolerance out of `rest` and return it with the text it consumed removed."""
    for pattern, build in (
        (_BILATERAL_SLASH, _bilateral),
        (_BILATERAL_SPACED, _bilateral),
        (_SYMMETRIC_ANGLE, _symmetric_angle),
        (_SYMMETRIC, _symmetric),
        (_UPPER_ONLY, _upper_only),
        (_LOWER_ONLY, _lower_only),
    ):
        match = pattern.search(rest)
        if match is not None:
            remainder = rest[: match.start()] + rest[match.end() :]
            return build(match), remainder
    return _NO_TOLERANCE, rest


def _bilateral(match: re.Match[str]) -> ToleranceSpec:
    return ToleranceSpec(
        kind="bilateral", upper=float(match.group(1)), lower=-float(match.group(2))
    )


def _symmetric(match: re.Match[str]) -> ToleranceSpec:
    value = float(match.group(1))
    return ToleranceSpec(kind="symmetric", upper=value, lower=-value)


def _symmetric_angle(match: re.Match[str]) -> ToleranceSpec:
    value = _degrees(match)
    return ToleranceSpec(kind="symmetric", upper=value, lower=-value, is_angular=True)


def _upper_only(match: re.Match[str]) -> ToleranceSpec:
    return ToleranceSpec(kind="bilateral", upper=float(match.group(1)), lower=None)


def _lower_only(match: re.Match[str]) -> ToleranceSpec:
    return ToleranceSpec(kind="bilateral", upper=None, lower=-float(match.group(1)))


def _degrees(match: re.Match[str]) -> float:
    """Degrees-minutes-seconds to decimal degrees."""
    total = float(match.group("deg"))
    if match.group("min"):
        total += float(match.group("min")) / 60.0
    if match.group("sec"):
        total += float(match.group("sec")) / 3600.0
    return total


def _reconcile(tolerance: ToleranceSpec, nominal_is_angular: bool) -> ToleranceSpec:
    """Keep the tolerance and its nominal in the same dimension.

    A bare tolerance on an angular nominal is in degrees, as drawings write it. An
    angular tolerance on a linear nominal is not a callout this grammar understands, so
    it is dropped to `kind="none"` rather than applied as millimetres.
    """
    if tolerance.kind == "none":
        return tolerance
    if nominal_is_angular:
        return ToleranceSpec(
            kind=tolerance.kind, upper=tolerance.upper, lower=tolerance.lower, is_angular=True
        )
    if tolerance.is_angular:
        return _NO_TOLERANCE
    return tolerance


def _build(
    value: float | None,
    is_angular: bool,
    tolerance: ToleranceSpec,
    text: str,
    sheet_units: SheetUnits,
    source: SourceRef,
) -> Dimension | None:
    """Apply the sheet's units; `None` when the callout has no value or no unit."""
    if value is None:
        return None
    if is_angular:
        nominal: Quantity | Angle = Angle(value=value, unit="deg")
    elif sheet_units in ("mm", "in"):
        nominal = Quantity(value=value, unit=sheet_units)
    else:
        return None

    return Dimension(
        nominal=nominal,
        tolerance=Tolerance(
            kind=tolerance.kind,
            upper=_value(tolerance.upper, tolerance.is_angular, sheet_units),
            lower=_value(tolerance.lower, tolerance.is_angular, sheet_units),
            source=source,
        ),
        source=source,
        text_as_read=text,
    )


def _value(
    value: float | None, is_angular: bool, sheet_units: SheetUnits
) -> Quantity | Angle | None:
    if value is None:
        return None
    if is_angular:
        return Angle(value=value, unit="deg")
    if sheet_units in ("mm", "in"):
        return Quantity(value=value, unit=sheet_units)
    return None
