"""What a fastener's name says: kind, head, size, pitch, length (feature 010 US4, T039).

`contracts/fasteners.md` sections 1 and 2 are normative. The recorded big assembly held 68
screws named in a vendor shape - `SHC_M4-0.7X12_...`, described `SCREW, SOC M4-0.7 X 12 MM,
...` - and none was a fastener to the reviewer, because the only name reader was the
extractor's and it ran for Toolbox parts only (research R2.11). This module reads the same
grammar in Python, from the three places a name can be:

1. the document's **file name** (a SOLIDWORKS extension dropped, nothing else);
2. its **Description** property;
3. the component's **referenced configuration** name, where Toolbox writes the size.

`read_fastener_names` takes them in that order: the first that names a size is the name,
and every later one that also parses cross-checks it. Two stated values that differ are a
*conflict*, named and never reconciled - which size the screw really is, the evidence does
not say.

Two rules outrank the rest (constitution Principle I). **An unreadable part of a readable
name is a null field, never a guess**: a length that is not a number is unknown, a head code
the table lacks leaves kind, head and drive null. And **a text that names no size is not a
fastener name** (`None`): a bracket with tapped holes is not a screw.

The grammar is the C# `FastenerNameParser`'s, form for form, and both parsers answer every
row of `specs/010-mechanical-checks/contracts/fastener-name-vectors.json`, so they cannot
drift. The words - head codes, kinds, heads - are data in `fastener_names.yaml`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from swreview.checks.fastener import ThreadSpec, parse_thread
from swreview.checks.result import round_length

__all__ = [
    "DEFAULT_NAMES_PATH",
    "NAME_SOURCES",
    "SOURCE_LABELS",
    "FastenerNames",
    "HeadCode",
    "NameReading",
    "NameSource",
    "ParsedName",
    "load_fastener_names",
    "parse_fastener_name",
    "read_fastener_names",
    "same_thread",
]

DEFAULT_NAMES_PATH = Path(__file__).with_name("fastener_names.yaml")

NameSource = Literal["file_name", "description", "configuration"]
NAME_SOURCES: tuple[NameSource, ...] = ("file_name", "description", "configuration")
"""The places a name is read from, in the order `read_fastener_names` takes them."""

SOURCE_LABELS: dict[NameSource, str] = {
    "file_name": "the file name",
    "description": "the description",
    "configuration": "the configuration name",
}

FastenerKind = Literal["screw", "bolt", "nut", "washer", "pin", "other"]

_MM_PER_INCH = 25.4
_EQUAL_MM = 1e-6

_DOCUMENT_EXTENSIONS: tuple[str, ...] = (".sldprt", ".sldasm", ".slddrw")
"""Only these are dropped: a vendor name has a dot inside its pitch (`M4-0.7X12`), so
"everything after the last dot" would cut the size in half."""


# --- the data file ----------------------------------------------------------------------------


@dataclass(frozen=True)
class HeadCode:
    """One vendor head code: the kind, the head and the drive it names (drive may be null)."""

    code: str
    kind: FastenerKind
    head_type: str
    drive: str | None


@dataclass(frozen=True)
class FastenerNames:
    """`fastener_names.yaml`: head codes by upper-case code, and the two vocabularies."""

    version: int
    head_codes: Mapping[str, HeadCode]
    kinds: tuple[str, ...]
    heads: tuple[str, ...]


def _parse_names(document: object, path: Path) -> FastenerNames:
    if not isinstance(document, Mapping):
        raise ValueError(f"{path}: the fastener name table must be a mapping")
    for key in ("version", "head_codes", "kinds", "heads"):
        if key not in document:
            raise ValueError(f"{path}: {key} is missing")
    kinds = tuple(str(word).lower() for word in document["kinds"])
    heads = tuple(str(phrase).lower() for phrase in document["heads"])
    if not kinds or not heads:
        raise ValueError(f"{path}: kinds and heads must each name at least one word")

    codes: dict[str, HeadCode] = {}
    for code, row in (document["head_codes"] or {}).items():
        if not isinstance(row, Mapping) or set(row) != {"kind", "head_type", "drive"}:
            raise ValueError(
                f"{path}: head code {code} must carry exactly kind, head_type and drive "
                "(a drive that is not known is written null)"
            )
        if row["kind"] not in kinds:
            raise ValueError(f"{path}: head code {code} names kind {row['kind']!r}, not in kinds")
        drive = row["drive"]
        if drive is not None and (not isinstance(drive, str) or not drive.strip()):
            raise ValueError(f"{path}: head code {code} drive must be a word or null")
        codes[str(code).upper()] = HeadCode(
            code=str(code).upper(),
            kind=row["kind"],
            head_type=str(row["head_type"]).lower(),
            drive=drive,
        )
    return FastenerNames(
        version=int(document["version"]), head_codes=codes, kinds=kinds, heads=heads
    )


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> FastenerNames:
    return _parse_names(yaml.safe_load(path.read_text(encoding="utf-8")), path)


def load_fastener_names(path: Path | str | None = None) -> FastenerNames:
    """Read the head-code table; `path` defaults to the one beside this module. Cached per
    resolved path, like the other `checks/` tables."""
    return _load_cached(Path(path or DEFAULT_NAMES_PATH).resolve())


# --- the grammar ------------------------------------------------------------------------------

_NUMBER = r"\d+(?:\.\d+)?"
_VENDOR_FILE_NAME = re.compile(
    rf"^(?P<code>[a-z]+) m(?P<size>{_NUMBER})-(?P<pitch>{_NUMBER})x(?P<length>{_NUMBER})(?: .*)?$"
)
"""`shc m4-0.7x12 fict-0001`: a head code, the metric size with a hyphen pitch, the length."""

_VENDOR_DESCRIPTION = re.compile(
    rf"^[a-z]+, .*?\bm(?P<size>{_NUMBER})-(?P<pitch>{_NUMBER}) x (?P<length>{_NUMBER}) mm\b"
)
"""`screw, soc m4-0.7 x 12 mm, fictional`: a word and a comma, the size, the length in mm."""

_METRIC_SIZE = re.compile(rf"^m({_NUMBER})(?:-({_NUMBER}))?$")
_INCH_SIZE = re.compile(r"^(?:#?\d+(?:/\d+)?|\d*\.\d+)-\d+$")
_SIZE_SEPARATOR = re.compile(r"(?<=[\d./])\s*x\s*(?=[#\d.\-])")
"""The `x` between size, pitch and length; only between numbers, so `hex` never splits."""

_MIXED_FRACTION = re.compile(r"^(\d+)-(\d+)/(\d+)$")
_FRACTION = re.compile(r"^(\d+)/(\d+)$")
_DECIMAL = re.compile(r"^-?\d+(?:\.\d+)?$")


def _normalize(text: str | None) -> str:
    """Lower case, `_` and runs of whitespace to one space, `×` to `x`."""
    if text is None or not text.strip():
        return ""
    lowered = text.lower().replace("_", " ").replace("×", "x")
    return re.sub(r"\s+", " ", lowered).strip()


def _without_extension(text: str) -> str:
    trimmed = text.strip()
    for extension in _DOCUMENT_EXTENSIONS:
        if trimmed.lower().endswith(extension):
            return trimmed[: -len(extension)]
    return trimmed


def _number(token: str) -> float | None:
    mixed = _MIXED_FRACTION.match(token)
    if mixed:
        denominator = float(mixed.group(3))
        if denominator == 0:
            return None
        return float(mixed.group(1)) + float(mixed.group(2)) / denominator
    fraction = _FRACTION.match(token)
    if fraction:
        denominator = float(fraction.group(2))
        return None if denominator == 0 else float(fraction.group(1)) / denominator
    if _DECIMAL.match(token):
        return float(token)
    return None


def _length_mm(token: str, inches: bool) -> float | None:
    value = _number(token)
    if value is None or value <= 0.0:
        return None
    return round_length(value * _MM_PER_INCH) if inches else value


def _size_and_length(text: str) -> tuple[str | None, float | None]:
    """The Toolbox and unified forms: a size first, then a pitch and a length."""
    suffix = text.find(" - ")
    core = text[:suffix].strip() if suffix >= 0 else text
    tokens = _SIZE_SEPARATOR.split(core)

    metric = _METRIC_SIZE.match(tokens[0])
    if metric:
        designation = f"M{metric.group(1)}"
        if metric.group(2) is not None:
            # "M4-0.7 x 12": the hyphen gave the pitch, so what follows is the length.
            designation += f"x{metric.group(2)}"
            length = _length_mm(tokens[1], inches=False) if len(tokens) >= 2 else None
            return designation, length
        if len(tokens) == 1:
            return designation, None
        if len(tokens) >= 3:
            return f"{designation}x{tokens[1]}", _length_mm(tokens[2], inches=False)
        # One value after the size: a decimal is a pitch ("M6x1.0"), a whole number a
        # length ("M10x35"); guessing the other way round turns a 35 mm screw into a pitch.
        if "." in tokens[1]:
            return f"{designation}x{tokens[1]}", None
        return designation, _length_mm(tokens[1], inches=False)

    if _INCH_SIZE.match(tokens[0]):
        length = _length_mm(tokens[1], inches=True) if len(tokens) >= 2 else None
        return tokens[0], length
    return None, None


def _head(text: str, names: FastenerNames) -> str | None:
    return next((phrase for phrase in names.heads if phrase in text), None)


def _kind(text: str, names: FastenerNames) -> str | None:
    return next(
        (word for word in names.kinds if re.search(rf"\b{re.escape(word)}s?\b", text)), None
    )


@dataclass(frozen=True)
class ParsedName:
    """What one text says about a fastener. Every field it does not say is null."""

    text: str
    source: NameSource
    kind: FastenerKind | None
    head_code: str | None
    """The vendor head code, when the table knows it."""
    head_type: str | None
    drive: str | None
    """From the head code only: a head named in words names no drive."""
    designation: str
    """The size as written, `M4x0.7`, `M6`, `1/4-20`: what `thread` was parsed from."""
    thread: ThreadSpec
    length_mm: float | None


def parse_fastener_name(
    text: str | None, source: NameSource, names: FastenerNames | None = None
) -> ParsedName | None:
    """Read one text with the whole grammar, or `None` when it names no size.

    The two vendor forms first, whose shapes cannot be mistaken for a Toolbox name, then
    the Toolbox and unified forms. The head and the kind come from the vocabulary first and
    a vendor head code second. Raises `ValueError` for a `source` that is not one of the
    three a name is read from.
    """
    if source not in NAME_SOURCES:
        raise ValueError(f"source must be one of {NAME_SOURCES}, got {source!r}")
    if text is None:
        return None
    names = names or load_fastener_names()
    normalized = _normalize(_without_extension(text) if source == "file_name" else text)
    if not normalized:
        return None

    code: HeadCode | None = None
    vendor_file = _VENDOR_FILE_NAME.match(normalized)
    vendor_text = None if vendor_file else _VENDOR_DESCRIPTION.match(normalized)
    if vendor_file or vendor_text:
        match = vendor_file or vendor_text
        assert match is not None
        designation: str | None = f"M{match.group('size')}x{match.group('pitch')}"
        length = _length_mm(match.group("length"), inches=False)
        if vendor_file:
            code = names.head_codes.get(vendor_file.group("code").upper())
    else:
        designation, length = _size_and_length(normalized)
    if designation is None:
        return None

    worded_head = _head(normalized, names)
    worded_kind = _kind(normalized, names)
    return ParsedName(
        text=text,
        source=source,
        kind=(worded_kind or (code.kind if code else None)),  # type: ignore[arg-type]
        head_code=None if code is None else code.code,
        head_type=worded_head or (code.head_type if code else None),
        drive=None if code is None else code.drive,
        designation=designation,
        thread=parse_thread(designation),
        length_mm=length,
    )


# --- the three sources together ----------------------------------------------------------------


@dataclass(frozen=True)
class NameReading:
    """A fastener's three names read in order: the first that names a size, the later ones
    that also do, and every stated value on which a later one disagrees with the first."""

    name: ParsedName | None
    others: tuple[ParsedName, ...]
    conflicts: tuple[str, ...]


def same_thread(a: ThreadSpec, b: ThreadSpec) -> bool:
    """Whether two threads state the same size: series and diameter, and the pitch when both
    state one. A pitch given on one side only is silence, not a disagreement."""
    if not (a.recognized and b.recognized):
        return a.normalized == b.normalized
    assert a.nominal_diameter is not None and b.nominal_diameter is not None
    if a.series != b.series:
        return False
    if abs(a.nominal_diameter.value - b.nominal_diameter.value) > _EQUAL_MM:
        return False
    return a.pitch_mm is None or b.pitch_mm is None or abs(a.pitch_mm - b.pitch_mm) <= _EQUAL_MM


def _conflicts(first: ParsedName, other: ParsedName) -> list[str]:
    found = []
    if not same_thread(first.thread, other.thread):
        found.append(
            f"{SOURCE_LABELS[other.source]} reads {other.designation} where "
            f"{SOURCE_LABELS[first.source]} reads {first.designation}"
        )
    if (
        first.length_mm is not None
        and other.length_mm is not None
        and abs(first.length_mm - other.length_mm) > _EQUAL_MM
    ):
        found.append(
            f"{SOURCE_LABELS[other.source]} reads a length of {other.length_mm!r} mm where "
            f"{SOURCE_LABELS[first.source]} reads {first.length_mm!r} mm"
        )
    return found


def read_fastener_names(
    file_name: str | None,
    description: str | None,
    configuration: str | None,
    names: FastenerNames | None = None,
) -> NameReading:
    """The file name, then the description, then the configuration name (FR-011).

    A later source silent on a field - no pitch, no length - does not disagree; only two
    stated values that differ are a conflict.
    """
    names = names or load_fastener_names()
    parsed = [
        item
        for item in (
            parse_fastener_name(file_name, "file_name", names),
            parse_fastener_name(description, "description", names),
            parse_fastener_name(configuration, "configuration", names),
        )
        if item is not None
    ]
    if not parsed:
        return NameReading(name=None, others=(), conflicts=())
    first, *others = parsed
    conflicts = tuple(text for other in others for text in _conflicts(first, other))
    return NameReading(name=first, others=tuple(others), conflicts=conflicts)

