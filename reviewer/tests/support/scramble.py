"""Fictional strings for the replay fixtures (feature 008, research R2.10 and R2.11).

The replay fixtures are generated from recorded runs whose packages carry real document
paths, vault folders, people, project names and part numbers. `FictionalMap` replaces every
identifying string with a fictional one of the same shape, so the checks grade the fixture
exactly as they graded the recording while nothing real reaches this public repository.

**What it keeps.** Entity ids (`cmp:0001`), the IR's structural fields
(`PACKAGE_VERBATIM_KEYS`: type names, enums, units, ids, timestamps), property *keys* made of
generic words, whole values that are only a number, a list of numbers, a fraction or a date,
short digit tokens (`M8`, `Sketch12`'s 12), and the generic vocabulary in `ALLOWED_WORDS` -
SOLIDWORKS default names, the extractor's own sentence templates, ordinary engineering nouns.
A property key is scrambled token by token like any text, so a key that names a company
loses that name and a generic key (`Author`, `Part Number`) keeps every word. A recorded
argument's `check` and `bucket` stay verbatim too (`ARGUMENT_VERBATIM_KEYS`), because the
checklist matches them.

**What it scrambles.** Every other alphanumeric token: names, descriptions, custom and
configuration property values, gap reasons and errors, equation text, configuration names,
component paths, numbers of three digits or more inside a name, and the model's prose in
recorded arguments. Document ids (`doc:` and `dsn:` plus twelve hex digits) get fictional
hex. Windows paths keep their segment count and extension and land under
`C:\\FictionalVault\\`. Persistent references are decoded, the names and paths SOLIDWORKS
embeds in them (UTF-16 and ASCII runs) are scrambled the same way, and they are re-encoded,
so every other byte - and so almost every token the model is billed for - is unchanged.

**How outputs are chosen.** A token's output keeps its length and the class of every
character (digit, upper, lower), its letters drawn from `SYLLABLES` and its digits from a
fixed generator seeded only by the token's **first-seen ordinal**, never by its content and
never by a secret. Two fresh maps fed the same strings in the same order therefore agree,
one input always has one output (so a file stem, a component name and a part-number
property that share a token still agree), and no two inputs share an output. `reserved`
names strings an output may never be - the generator passes every token of the recording.

`replaced` records every original token and its replacement, for the generator's leak check
and for the owner's denylist outside the repository. Nothing in this module is a recorded
string: the allowlist is generic vocabulary only.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

__all__ = [
    "ALLOWED_WORDS",
    "ARGUMENT_VERBATIM_KEYS",
    "FICTIONAL_ROOT",
    "PACKAGE_VERBATIM_KEYS",
    "SYLLABLES",
    "FictionalMap",
    "is_allowed_token",
    "tokens_of",
]

FICTIONAL_ROOT = "C:\\FictionalVault\\"
"""Where every scrambled Windows path lands; the hygiene test holds every fixture path to it."""

_ROOT_SEGMENT = "FictionalVault"

SYLLABLES: tuple[str, ...] = tuple(
    consonant + vowel for consonant in "bdfgklmnprstvz" for vowel in "aeiou"
)
"""The only letters a scrambled token is made of: seventy consonant-vowel pairs."""

ALLOWED_WORDS: frozenset[str] = frozenset(
    """
    a about above absent accepted across active actual add added after against all alloy
    along also aluminum an analysis and angle annealed annotation annotations any api
    applicable are area arrow as assembled assembly assessment assy at available axes axial
    axis back base based be bearing because been bend between blind block bodies body bolt
    bolts boss both bottom bottoming bounding box bracket build built but by cable call
    came camera cameras can cannot cap caps carbon cast caveat caveats center chamfer
    change check checked checking checks cir circular clamped class clearance close closed
    closeout closes coating coincident collar com combine comment comments complete
    component components composite computed concentric condition config configuration
    configurations confirm confirmed conical contains contributing copy core cost could
    counterbore counterbores countersink cover covers coverage cross csk cup current
    curve cut cutlist cylinder cylinders cylindrical data datum default defined definitive
    delete demonstrated density depth derived design designation designed despite detail
    detection determined dia diameter did dimension dimensional dimensions direction
    directional discrepancies discrepancy distance do document documents double dowel draft
    drawing drawings drill drive due each edge edit editing end engagement engineering
    entity equation equations error errors evaluated every evidence exception exceptions
    exists explicit extension extract extracted extraction extractor extrude extrusion face
    faces fastener fasteners favorites feature features file files fillet finish fit
    fitting fits flange flat folder following for found from front full functional gap gaps
    gear gearbox general geometry governing group groups had hand has have head height
    helix hex hidden hinge history hole holes housing identified identify identities
    identity ids if in include included including inclusion initial input inputs inside
    instance instances interface interfaces interference interpretation inventory is it
    item its joint joints judged keep keyed layers left length library lights like limits
    line linear lines list live loaded local locally lock locking long looked low machine
    machined main manifest manufactured manufacturing many mapping markups mass mate mated
    mates material mating maximum measurements mechanism mesh meshes metal metric minimum
    mirror missing model modeled modelled modification modified motion motor mount mounting
    multibody named names naming native natively needs never no nominal none not note notes
    number nut nuts object obtained of off offset on one only open opened operation or
    order origin other out outer override overlaps pair pairs parallel parameters part
    parts pattern per perpendicular phase pin pins pipe pitch plain plane planes plate
    plated plug plus position positions preload presence present press pressure profile
    progress property properties provenance provide purchased read reads reference
    references reflected relative remain reported reports representative request requests
    required requirement resolution resolve resolved resolving returned rev revision
    revisions revolution revolve rib right ring rings run scope screw screws seal sealing
    second see selected selection sensor sensors session set sets several shaft sheet sheets
    shell shorter shows side simplified size sketch skipped slot so solid some source
    specification specified spiral split stack stacks stainless standard state stated
    static status steel stock stated such supplier supported suppressed surface surfaced
    sweep system tabs table tables tapped taper target template temper terms text than that
    the their them these they this thickness thread threads three through tie tied to
    tolerance tolerances tool toolbox top torx treated treatment tree trees truncated two
    type types unable under unit unknown unloaded unresolved unsupported usable value values
    vault verification verified version view volume was washer washers were where whether
    which whole width with without work workstation would written zero zinc
    package packages alignment aligned custom failed fails review reviewed reviews
    reviewing checklist item items coverage gap manufacturer standards example yaml
    lightweight unavailable readable subassemblies subassembly assemblies dependency
    dependencies parent parents child children treat detected detecting whose
    doc cone mmc carry carried records record recorded intended intent coaxiality coaxial
    ambient binder cabinet docs env eqn fav favorite ftr ink markup pos ref refs sw swsel
    comobject hresult iid imassproperty interop invalidcastexception nointerface
    queryinterface gettypename overridemass dumper sldworks solidworks
    exception object mate matereference matereferences matereferencegroupfolder posgroupfolder
    configtablefolder cutlistfolder solidbodyfolder surfacebodyfolder materialfolder
    endtag selectionsetfolder sensorfolder historyfolder favoritefolder docsfolder eqnfolder
    envfolder inkmarkupfolder commentsfolder detailcabinet originprofilefeature refplane
    refaxis profilefeature basebody compositecurve flatpattern sheetmetal smbaseflange
    cutextrude revcut sweepcut combinebodies mirrorpattern mirrorcomponent referencepattern
    derivedholepattern derivedlpattern localcirpattern lpattern cirpattern cylinderparams
    threaddepth transformation input bundles button
    sldprt sldasm slddrw step stp pdf glb stl dwg dxf
    epdm pdm mm cm in m deg x i l id od ok
    description author approved project name date latest requested initials controlled
    vendor measure unit of revision state finish notes surfacearea swmass swdensity
    ansi iso din inch metric shcs bhcs fhcs fhts bht fht cbore npt
    """.split()
)
"""Generic vocabulary a scrambled package keeps, compared case-insensitively.

SOLIDWORKS default names and folder types, the extractor's own sentence templates, and
ordinary engineering nouns. A camel-case token (`LocalCirPattern1`) is kept when every part is
here, and a token with a trailing counter (`Hole12`) when its stem is. It must never hold a
recorded name, and it does not need to be complete: a generic word missing from it is
scrambled, which costs readability and nothing else.
"""

_ALLOWED_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"sw[A-Z][A-Za-z0-9]*"),  # SOLIDWORKS enum names: swMateCOINCIDENT
    re.compile(r"M[0-9]+(?:[xX][0-9]+)?"),  # metric thread sizes: M8, M10x1
    re.compile(r"[0-9]+(?:mm|MM|cm|in|IN|deg)"),  # a number with its unit: 3MM
    re.compile(r"[0-9]+[xX][0-9]+"),  # a size pair: 7X14
)
"""Engineering designations, which are shapes rather than words."""

PACKAGE_VERBATIM_KEYS: frozenset[str] = frozenset(
    {
        "alignment",
        "constrained_status_raw",
        "created_at",
        "drive",
        "end_condition",
        "entity_kind",
        "export_method",
        "fastener_folder_treatment",
        "file_modified_utc",
        "folder_type_name",
        "head_type",
        "hole_type",
        "identity_source",
        "kind",
        "mesh_file",
        "package_id",
        "profile",
        "resolution_status",
        "run_at",
        "schema_version",
        "size",
        "standard",
        "status",
        "suppression",
        "sw_version",
        "thread_designation",
        "type",
        "type_name",
        "unit",
        "version",
    }
)
"""Package fields read as structure - enums, SOLIDWORKS type names, units, ids, timestamps.

Every other string field is scrambled (deny by default), so a field this list forgets is
scrambled rather than leaked; a structural field it forgets shows up as a validation error
or a changed finding in the generator's self-check.
"""

ARGUMENT_VERBATIM_KEYS: frozenset[str] = frozenset({"check", "bucket"})
"""Recorded argument fields read as structure: the checklist matches `check` and `bucket`."""

_SPELLED_OUT = {"\u00a9": "(c)", "\u00ae": "(r)", "\u2122": "(tm)"}
"""Signs a vendor's notice carries, spelled out: the fixture hygiene test forbids the
copyright sign itself, and a notice that survived as one would name its owner by shape."""

_PATH_KEYS = frozenset({"path", "vault_path"})
_PROPERTY_MAP_KEYS = frozenset({"custom_properties"})
_CONFIGURATION_MAP_KEYS = frozenset({"config_properties"})

_WORD = re.compile(r"[A-Za-z0-9]+")
_HEX_ID = re.compile(r"\b(doc|dsn):([0-9a-f]{12})\b")
_ENTITY_ID = re.compile(r"\b[a-z]{3,4}:[0-9]{4,}\b")
_TEXT_PIECE = re.compile(
    r"(?P<hex>\b(?:doc|dsn):[0-9a-f]{12}\b)|(?P<entity>\b[a-z]{3,4}:[0-9]{4,}\b)|(?P<word>[A-Za-z0-9]+)"
)
_CAMEL_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9:.+\-Z]*)?")
_FRACTION = re.compile(r"[0-9]+/[0-9]+")
_WINDOWS_ANCHOR = re.compile(r"(?:[A-Za-z]:\\|\\\\)")
_FULL_HEX = re.compile(r"[0-9a-f]{16,}")
_UTF16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){3,}")
_ASCII_RUN = re.compile(rb"[\x20-\x7e]{4,}")


def is_allowed_token(token: str) -> bool:
    """Whether one alphanumeric token is generic and passes through unscrambled."""
    if token.isdigit():
        return len(token) < 3
    if len(token) < 3 and any(character.isdigit() for character in token):
        return True
    if any(shape.fullmatch(token) for shape in _ALLOWED_SHAPES):
        return True
    stem = token.rstrip("0123456789")
    if not stem or any(character.isdigit() for character in stem):
        return False
    if stem.lower() in ALLOWED_WORDS:
        return True
    parts = _CAMEL_PART.findall(stem)
    if "".join(parts) != stem or len(parts) < 2:
        return False
    return all(part.lower() in ALLOWED_WORDS or len(part) == 1 for part in parts) and any(
        len(part) > 1 for part in parts
    )


def is_plain_number(value: str) -> bool:
    """A value that is only numbers, fractions or dates, one per line: kept verbatim.

    A mass, a tolerance pair, a thread fraction or a date identifies nobody. A part number
    written only in digits and hyphens is none of these shapes, so it is scrambled.
    """
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return bool(lines) and all(
        _NUMBER.fullmatch(line) or _DATE.fullmatch(line) or _FRACTION.fullmatch(line)
        for line in lines
    )


def tokens_of(text: str) -> list[str]:
    """The alphanumeric tokens of `text`, as the map and the leak checks both split it."""
    return _WORD.findall(text)


class _Draws:
    """A fixed pseudo-random stream seeded by an ordinal: no content, no secret."""

    def __init__(self, seed: int) -> None:
        self._state = seed % 2**31

    def next(self) -> int:
        self._state = (self._state * 1_103_515_245 + 12_345) % 2**31
        return self._state >> 8


class FictionalMap:
    """One scrambling of one recording: every identifying token to one fictional token."""

    def __init__(self, *, reserved: Iterable[str] = (), keep: Iterable[str] = ()) -> None:
        self.replaced: dict[str, str] = {}
        """Original token -> its fictional replacement, in first-seen order."""
        self._reserved = frozenset(reserved)
        self._keep = frozenset(keep)
        """Tokens this recording's own structure names as vocabulary - its SOLIDWORKS type
        names - kept wherever else they are quoted, such as a gap listing skipped types."""
        self._used: set[str] = set()
        self._hex: dict[str, str] = {}
        self._ordinal = 0

    # --- one token ---------------------------------------------------------------------

    def token(self, token: str) -> str:
        """`token` itself when generic, else its fictional replacement (assigned once)."""
        if token in self._keep or is_allowed_token(token):
            return token
        known = self.replaced.get(token)
        if known is not None:
            return known
        fictional = self._fictional(token)
        self.replaced[token] = fictional
        return fictional

    def _fictional(self, token: str) -> str:
        ordinal = self._ordinal
        self._ordinal += 1
        attempt = 0
        while True:
            candidate = self._draw(token, ordinal, attempt)
            if (
                candidate != token
                and candidate not in self._used
                and candidate not in self._reserved
                and not is_allowed_token(candidate)
            ):
                self._used.add(candidate)
                return candidate
            attempt += 1

    @staticmethod
    def _draw(token: str, ordinal: int, attempt: int) -> str:
        draws = _Draws(ordinal * 2_654_435_761 + attempt * 40_503 + 1)
        letters: list[str] = []
        out: list[str] = []
        for character in token:
            if character.isdigit():
                out.append(str(draws.next() % 10))
                continue
            if not letters:
                letters.extend(SYLLABLES[draws.next() % len(SYLLABLES)])
            letter = letters.pop(0)
            out.append(letter.upper() if character.isupper() else letter)
        return "".join(out)

    def _hex_part(self, original: str) -> str:
        known = self._hex.get(original)
        if known is not None:
            return known
        ordinal = len(self._hex)
        attempt = 0
        while True:
            draws = _Draws(ordinal * 97_531 + attempt * 7_919 + 17)
            candidate = "".join("0123456789abcdef"[draws.next() % 16] for _ in original)
            taken = candidate in self._hex.values()
            if candidate != original and not taken and not candidate.isdigit():
                self._hex[original] = candidate
                return candidate
            attempt += 1

    # --- strings -----------------------------------------------------------------------

    def text(self, value: str) -> str:
        """Free text: entity ids kept, document ids re-hexed, every other token mapped."""

        def piece(match: re.Match[str]) -> str:
            if match.group("hex"):
                prefix, digits = match.group("hex").split(":")
                return f"{prefix}:{self._hex_part(digits)}"
            if match.group("entity"):
                return match.group("entity")
            return self.token(match.group("word"))

        scrambled = _TEXT_PIECE.sub(piece, value)
        for sign, spelled in _SPELLED_OUT.items():
            scrambled = scrambled.replace(sign, spelled)
        return scrambled

    def value(self, value: str) -> str:
        """One field value: an id, a number or a date as it is; a path as a path; else text."""
        if _ENTITY_ID.fullmatch(value):
            return value
        if is_plain_number(value):
            return value
        if _WINDOWS_ANCHOR.match(value):
            return self.path(value)
        return self.text(value)

    def path(self, value: str) -> str:
        """A Windows path under `FICTIONAL_ROOT`, keeping its segment count and extension.

        The anchor (a drive, or a UNC server) and the first folder become the fictional root;
        every later folder and the file stem are scrambled as text, and the extension is kept
        when it is a known file type. A path of one segment keeps that segment under the root.
        """
        anchor = _WINDOWS_ANCHOR.match(value)
        if anchor is None:
            return self.text(value)
        segments = value[anchor.end() :].split("\\")
        kept = segments[1:] if len(segments) >= 2 else segments
        if len(segments) >= 2:
            # The first folder is replaced by the fictional root rather than scrambled, but its
            # tokens are still recorded in `replaced`: a vault root names its owner, and the
            # leak check and the denylist must know that name wherever else it turns up.
            self.text(segments[0])
        last = len(kept) - 1
        return FICTIONAL_ROOT + "\\".join(
            self._segment(segment, is_file=index == last) for index, segment in enumerate(kept)
        )

    def _segment(self, segment: str, *, is_file: bool) -> str:
        if is_file and "." in segment:
            stem, extension = segment.rsplit(".", 1)
            if is_allowed_token(extension) and extension.isalnum():
                return f"{self.text(stem)}.{extension}"
        return self.text(segment)

    def persist_ref(self, value: str) -> str:
        """A base64 persistent reference with the names and paths inside it scrambled.

        Only the printable runs change (UTF-16 runs of three characters or more, ASCII runs
        of four or more), each through `value`; every other byte is kept, and a reference
        that carries no string comes back byte-identical. A value that is not base64 is
        scrambled as text rather than passed through.
        """
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return self.text(value)
        changed = _UTF16_RUN.sub(
            lambda match: self.value(match.group(0).decode("utf-16-le")).encode("utf-16-le"),
            raw,
        )
        changed = _ASCII_RUN.sub(
            lambda match: self.value(match.group(0).decode("ascii")).encode("ascii"), changed
        )
        if changed == raw:
            return value
        return base64.b64encode(changed).decode("ascii")

    def full_hex(self, value: str) -> str:
        """A bare hex digest (the package's `reuse_key`) as fictional hex of the same length."""
        if not _FULL_HEX.fullmatch(value):
            return self.text(value)
        return self._hex_part(value)

    # --- structures ----------------------------------------------------------------------

    def properties(self, properties: Mapping[str, Any]) -> dict[str, Any]:
        """A property map: generic key words kept, every string value scrambled."""
        return {self.text(key): self._walk(item, None) for key, item in properties.items()}

    def arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """A recorded call's arguments: `check` and `bucket` kept, every other string mapped."""
        return self._walk_arguments(arguments)

    def _walk_arguments(self, node: Any, key: str | None = None) -> Any:
        if isinstance(node, Mapping):
            return {name: self._walk_arguments(item, name) for name, item in node.items()}
        if isinstance(node, list):
            return [self._walk_arguments(item, key) for item in node]
        if isinstance(node, str) and key not in ARGUMENT_VERBATIM_KEYS:
            return self.value(node)
        return node

    def package(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        """A raw `package.json` object, scrambled field by field (deny by default)."""
        return self._walk(raw, None)

    def _walk(self, node: Any, key: str | None) -> Any:
        if isinstance(node, Mapping):
            out: dict[str, Any] = {}
            for name, item in node.items():
                if name in _PROPERTY_MAP_KEYS and isinstance(item, Mapping):
                    out[name] = self.properties(item)
                elif name in _CONFIGURATION_MAP_KEYS and isinstance(item, Mapping):
                    out[name] = {
                        self.value(configuration): self.properties(properties)
                        for configuration, properties in item.items()
                    }
                else:
                    out[name] = self._walk(item, name)
            return out
        if isinstance(node, list):
            return [self._walk(item, key) for item in node]
        if not isinstance(node, str) or key in PACKAGE_VERBATIM_KEYS:
            return node
        if key == "persist_ref":
            return self.persist_ref(node)
        if key == "reuse_key":
            return self.full_hex(node)
        if key in _PATH_KEYS:
            return self.path(node)
        return self.value(node)


def strings_of(node: Any) -> Iterator[str]:
    """Every string in a JSON-shaped value, keys included, depth first."""
    if isinstance(node, Mapping):
        for name, item in node.items():
            yield str(name)
            yield from strings_of(item)
    elif isinstance(node, list):
        for item in node:
            yield from strings_of(item)
    elif isinstance(node, str):
        yield node


def decoded_runs(value: str) -> list[str]:
    """The printable strings a base64 value carries, as `persist_ref` finds them."""
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return []
    runs = [match.group(0).decode("utf-16-le") for match in _UTF16_RUN.finditer(raw)]
    runs += [match.group(0).decode("ascii") for match in _ASCII_RUN.finditer(raw)]
    return runs
