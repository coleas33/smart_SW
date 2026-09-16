"""The one place a metre becomes the number an equation carries (T088, research R3.6).

**The number in an equation text is in the DOCUMENT's length unit, not metres.** The IR
carries metres for every length; a part kept in millimetres takes `"plate_width" = 120` for
120 mm. Getting it backwards builds a 120-metre part that rebuilds cleanly and passes every
non-geometric check, which is why the conversion happens exactly once - here - and why the
evidence row records both numbers so the inversion is visible in the artifact.

FR-030 keeps dimensions out of v1: the IR carries none, the planner cannot name one, and a
v1 global therefore names a value and drives nothing. The only number this version writes
into an equation is the global's own literal, seeded from the feature-data reading that
justifies it (`GlobalCandidate.value_m`, metres).

Four rules hold here rather than at the call sites:

1. **no conversion factor lives in this module.** `swreview.units` is the only place in the
   reviewer that converts units (research R6, constitution Principle II), and this module
   asks it; a second factor spelled out here is the trap R3.6 names;
2. **a document unit that cannot be read refuses the change** rather than assuming metres
   (FR-027, constitution Principle I). `null` from the seat's `GetLengthUnit` is "unknown",
   and unknown is not a value to build a part from. So is a token outside the IR's own
   three: near-misses are refused by name rather than guessed at;
3. **the literal is the exact converted value.** It is written so that reading the text
   back gives that same number - no rounding, no formatting that loses a digit - because
   once the text is written it is the only carrier of the number;
4. **angles are degrees.** `swAngularEquationUnits_e.Degrees = 1` (VERIFIED) and the
   documented function set (`sin cos tan atn arcsin sqr`) reads degrees, so an angle the IR
   carries in radians is converted before it reaches an expression.

Everything here is pure: text in, text out, no document, no bridge, nothing that could
move a body. That is what makes the geometry snapshot after a global is added an identity
comparison rather than a tolerance question.
"""

from __future__ import annotations

import math
import re

from swreview import units as shared_units
from swreview.ir.models import Angle, LengthUnit, Quantity
from swreview.remodel.intent import GlobalCandidate
from swreview.remodel.plan import GLOBAL_NAME_PATTERN, GlobalEvidence

__all__ = [
    "DEGREES",
    "DOCUMENT_LENGTH_UNITS",
    "EQUATION_ANGLE_UNIT",
    "DocumentUnitError",
    "angle_degrees",
    "document_length",
    "global_equation_text",
    "global_evidence",
]

DOCUMENT_LENGTH_UNITS: tuple[LengthUnit, ...] = ("mm", "in", "m")
"""The document length units this version seeds a literal for: the IR's own `LengthUnit`
set, so the bridge's `document_length_unit` and the package's quantities share one
vocabulary. A document kept in anything else is refused, with its unit named, rather than
converted by a rule nobody wrote down."""

EQUATION_ANGLE_UNIT = "deg"
"""Every angle in an equation expression is in degrees."""

DEGREES = 1
"""`swAngularEquationUnits_e.Degrees` (VERIFIED). Recorded because it is what the equation
engine reads; v1 neither reads nor sets the document's setting - the member is not on the
stage-1 allowlist - so degrees is a property of the text this module writes."""

_NAME = re.compile(GLOBAL_NAME_PATTERN)


class DocumentUnitError(ValueError):
    """The document's unit does not let this change be made, so it is not made.

    Raised for a unit that could not be read, a unit this version does not convert, and a
    value that is not a number. Every one of them is a refusal and none of them is a
    fallback: the alternative to refusing is writing a number in a unit nobody confirmed.
    """


def document_length(value_m: float, document_length_unit: str | None) -> float:
    """`value_m` metres as the number a `document_length_unit` document's equation carries.

    Refuses an unreadable or unconvertible unit rather than assuming metres: a 120 mm value
    written as `0.12` is a part a thousand times too small, and nothing downstream says so.
    """
    unit = _length_unit(document_length_unit)
    _finite(value_m)
    return shared_units.convert(Quantity(value=value_m, unit="m"), unit).converted.value


def global_equation_text(name: str, value_document_units: float) -> str:
    """The equation row that declares `name` as a constant, in SOLIDWORKS syntax.

    A quoted left side with no `@` is what makes the row a global rather than an equation
    on a dimension (research R2), which is the same reading `checks/rms/equations.py`
    makes of it.
    """
    _finite(value_document_units)
    return f'"{_global_name(name)}" = {_literal(value_document_units)}'


def global_evidence(
    candidate: GlobalCandidate, *, name: str, document_length_unit: str | None
) -> GlobalEvidence:
    """The evidence row for one proposed global (`data-model.md` section 1.9).

    Both numbers are recorded - the package's metres and the document's own units - because
    the inversion of the two is the highest-risk single error in stage 1, and a row that
    carries only one of them cannot be audited for it afterwards.
    """
    unit = _length_unit(document_length_unit)
    value_document_units = document_length(candidate.value_m, unit)
    return GlobalEvidence(
        feature_id=candidate.feature_id,
        parameter=candidate.parameter,
        value_m=candidate.value_m,
        document_length_unit=unit,
        value_document_units=value_document_units,
        equation_text=global_equation_text(name, value_document_units),
    )


def angle_degrees(angle: Angle | Quantity) -> float:
    """An angle as the degrees an expression carries.

    Raises `pint.DimensionalityError` when handed a length: the one registry keeps lengths
    and angles from mixing (FR-022), and that separation is `swreview.units`' to enforce
    rather than something restated here.
    """
    return shared_units.as_degrees(angle)


def _length_unit(document_length_unit: str | None) -> LengthUnit:
    if document_length_unit is None:
        raise DocumentUnitError(
            "the document's length unit could not be read, so this change is refused: "
            "an unread unit is not metres, and seeding a literal from that assumption is "
            "how a part a thousand times off gets built"
        )
    if document_length_unit not in DOCUMENT_LENGTH_UNITS:
        raise DocumentUnitError(
            f"the document's length unit is {document_length_unit!r}, which this version "
            f"does not convert to; it seeds a literal only for a document kept in "
            f"{', '.join(DOCUMENT_LENGTH_UNITS)}"
        )
    return document_length_unit


def _global_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(
            f"{name!r} is not a global name this product writes ({GLOBAL_NAME_PATTERN}); "
            f"the same rule the plan refuses a proposal by"
        )
    return name


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise DocumentUnitError(f"{value!r} is not a number an equation can carry")
    return value


def _literal(value: float) -> str:
    """The value as text that reads back as exactly this value.

    An integral value loses its trailing `.0` - `"corner_radius" = 3`, as the contract's
    own example writes it - and every other value keeps the shortest spelling that parses
    back to the same float, so nothing is rounded on the way into the document.
    """
    return f"{value:.0f}" if value.is_integer() else repr(value)
