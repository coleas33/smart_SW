"""Fictional strings for the replay fixtures (feature 008, research R2.10 and R2.11).

The replay fixtures are generated from recorded runs whose packages carry real document
paths, vault folders, people, project names and part numbers. `FictionalMap` replaces every
identifying string with a fictional one of the same shape, so the checks grade the fixture
exactly as they graded the recording while nothing real reaches this public repository.

**What it keeps.** Entity ids (`cmp:0001`), the IR's structural fields
(`PACKAGE_VERBATIM_KEYS`: type names, enums, units, ids, timestamps), whole values that are
only a number, a list of numbers, a fraction or a date, short digit tokens (`M8`,
`Sketch12`'s 12), the generic vocabulary in `ALLOWED_WORDS` - SOLIDWORKS default names, the
extractor's own sentence templates, ordinary engineering nouns - outside the strict fields
below, and the words the standards profile the fixtures are graded with names (`public`,
`profile_words`: that profile is committed, so its words are public). A recorded argument's
`check` and `bucket` stay verbatim too (`ARGUMENT_VERBATIM_KEYS`), because the checklist
matches them.

**What it scrambles.** Every other alphanumeric token: names, descriptions, gap reasons and
errors, equation text, configuration names, component paths, numbers of three digits or more
inside a name, and the model's prose in recorded arguments. Document ids (`doc:` and `dsn:`
plus twelve hex digits) get fictional hex. Persistent references are decoded, the names and
paths SOLIDWORKS embeds in them (UTF-16 and ASCII runs) are scrambled the same way, and they
are re-encoded, so every other byte - and so almost every token the model is billed for - is
unchanged.

**Property keys and values are strict** (2026-09-23: the generic words the allowlist kept
spelled out a company's property names, workflow states and export-control wording). Every
word of a custom or configuration property's key and value is mapped with no allowlist
(`property_text`), and is strict everywhere else too (`property_tokens`), so the same word in
a configuration name, a gap reason or the model's prose is mapped the same way. The only
words kept are a whole value of numbers, fractions or dates, a size, a one- or two-digit
number or a single character, the head of a SOLIDWORKS link (`SW-Density@`, the
configuration and document after it scrambled), and a word the standards profile names -
which the profile must still find (`strict_property_words`).

**Paths and names are strict** (the owner's review of 2026-09-23: kept generic folder words
rebuilt the vault layout). A Windows path lands under `C:\\FictionalVault\\` with its segment
count, lengths and character classes kept, and **every** folder between the root and the file
is scrambled with no allowlist - digits, sizes and generic words included. The file stem, a
component's name and path, a document's file name and a design name are scrambled with no
allowlist either, except for the three shapes that identify nothing: a size
(`M8`, `1.25X16`, `3MM`), a number of one or two digits, and a single character; the extension
is kept. Every token of those fields is **strict** everywhere else too, so a folder word or a
file-stem word that also appears in a description, a gap reason or the model's prose is
scrambled there as well and a component name and its file stem still agree. So is a supplier
code standing next to a catalogue number (`strict_tokens`). `package` finds the strict tokens
of the whole package before it maps anything; a caller scrambling other strings too (the
recorded arguments) passes theirs in as `strict`.

**How outputs are chosen.** A token's output keeps its length and the class of every
character (digit, upper, lower), its letters drawn from `SYLLABLES` and its digits from a
fixed generator seeded only by the token's **first-seen ordinal**, never by its content and
never by a secret. Two fresh maps fed the same strings in the same order therefore agree,
one input always has one output (so a file stem, a component name and a part-number
property that share a token still agree), and no two inputs share an output. An output of
three letters or more is never itself generic vocabulary, so a scrambled word cannot read as
a real one. `reserved` names strings an output may never be - the generator passes every
token of the recording.

`replaced` records every original token and its replacement, for the generator's leak check
and for the owner's denylist outside the repository. Nothing in this module is a recorded
string: the allowlist is generic vocabulary only.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from swreview.checks.hole_alignment import EXCLUDED_EFFECTS as HOLE_EXCLUDED_EFFECTS
from swreview.checks.standards.profile import load_profile

__all__ = [
    "ALLOWED_WORDS",
    "ARGUMENT_VERBATIM_KEYS",
    "FICTIONAL_ROOT",
    "PACKAGE_VERBATIM_KEYS",
    "SYLLABLES",
    "DENYLIST_FOLDER_PREFIX",
    "FictionalMap",
    "decoded_runs",
    "denylist_path",
    "folder_names",
    "folders_of",
    "is_allowed_token",
    "is_generic_shape",
    "letters",
    "path_values",
    "profile_words",
    "property_strings",
    "property_tokens",
    "split_extension",
    "read_denylist",
    "strict_property_words",
    "strict_tokens",
    "strings_of",
    "supplier_codes",
    "tokens_of",
    "without_reviewer_text",
    "write_denylist",
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
    item its joint joints judged keep keyed layers left length lights like limits
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
    doc cone carry carried records record recorded intended intent coaxiality coaxial
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
    ansi iso din inch metric cbore npt
    """.split()
)
"""Generic vocabulary a scrambled package keeps, compared case-insensitively.

SOLIDWORKS default names and folder types, the extractor's own sentence templates, and
ordinary engineering nouns. A camel-case token (`LocalCirPattern1`) is kept when every part is
here, and a token with a trailing counter (`Hole12`) when its stem is. It must never hold a
recorded name, and it does not need to be complete: a generic word missing from it is
scrambled, which costs readability and nothing else. Supplier codes, fastener head and finish
codes and folder words are deliberately absent, and paths, names and property keys and values
ignore it (`strict`).
"""

_SIZE_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"M[0-9]+(?:[xX][0-9]+)?"),  # metric thread sizes: M8, M10x1
    re.compile(r"[0-9]+(?:mm|MM|cm|in|IN|deg)"),  # a number with its unit: 3MM
    re.compile(r"[0-9]+[xX][0-9]+"),  # a size pair: 7X14
)
"""Sizes, which identify nothing and are kept even in a strict name (never in a folder)."""

_ALLOWED_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"sw[A-Z][A-Za-z0-9]*"),  # SOLIDWORKS enum names: swMateCOINCIDENT
    *_SIZE_SHAPES,
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

_NAMED_PARENTS = frozenset({"components", "design"})
"""Whose `name` field is a strict name: a component's instance name and the design's name."""
_STRICT_NAME_KEYS = frozenset({"file_name"})
"""Keys whose values are file names, strict like a path's file segment. A face's `body_id` is
not one: its component part is strict through the components already, and the rest is a
SOLIDWORKS default body name (`Boss-Extrude3`) that identifies nothing."""
_SUPPLIER_CODE = re.compile(r"[A-Z]{2,4}")
_CATALOGUE_NUMBER = re.compile(
    r"(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{5,}|[0-9]{5,}"
)
_BETWEEN_CODE_AND_NUMBER = re.compile(r"[ ,_\-]+")

REVIEWER_OWN_TEXT: tuple[str, ...] = tuple(HOLE_EXCLUDED_EFFECTS)
"""Sentences the reviewer itself writes into findings that carry a word the leak checks deny.

The hole check names "material condition modifiers (MMC, LMC)" among what it did not consider:
maximum material condition, the product's own words, not a supplier's code. Read from the
product rather than retyped, so a change there is a change here; `without_reviewer_text`
removes exactly these sentences before a fixture is checked, and nothing else.
"""

DENYLIST_FOLDER_PREFIX = "folder: "
"""Marks a line of the owner's denylist that is a recorded folder name, not a token."""
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
_SW_LINK = re.compile(r'SW-(?P<name>[^@"]+)@')
"""A SOLIDWORKS property link's head: `SW-Mass@` in `"SW-Mass@@Default@part"`. What follows the
`@` - a configuration and a document - is a name like any other."""


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


def is_generic_shape(token: str) -> bool:
    """A size, a number of one or two digits, or a single character: kept in a strict name."""
    if len(token) == 1 or (token.isdigit() and len(token) < 3):
        return True
    return any(shape.fullmatch(token) for shape in _SIZE_SHAPES)


def split_extension(value: str) -> tuple[str, str | None]:
    """`(everything but the extension, the extension)` when the value ends in a file type."""
    last = re.split(r"[\\/]", value)[-1]
    if "." in last:
        extension = last.rsplit(".", 1)[1]
        if extension.isalnum() and is_allowed_token(extension):
            return value[: -len(extension) - 1], extension
    return value, None


def is_path_key(key: str | None) -> bool:
    """Whether a field holds a path: any key containing `path` (`vault_path`, `full_path`)."""
    return key is not None and "path" in key


def _is_strict_field(key: str | None, parent: str | None) -> bool:
    return (
        is_path_key(key) or key in _STRICT_NAME_KEYS or (key == "name" and parent in _NAMED_PARENTS)
    )


def _fields(
    node: Any, key: str | None = None, parent: str | None = None
) -> Iterator[tuple[str | None, str | None, str]]:
    """`(key, parent key, value)` for every string value of a JSON-shaped node."""
    if isinstance(node, Mapping):
        for name, item in node.items():
            yield from _fields(item, name, key)
    elif isinstance(node, list):
        for item in node:
            yield from _fields(item, key, parent)
    elif isinstance(node, str):
        yield key, parent, node


def supplier_codes(text: str) -> set[str]:
    """Two to four capitals standing next to a catalogue number: a supplier's code (`QRZ`)."""
    tokens = list(_WORD.finditer(text))
    found: set[str] = set()
    for left, right in zip(tokens, tokens[1:], strict=False):
        if not _BETWEEN_CODE_AND_NUMBER.fullmatch(text[left.end() : right.start()]):
            continue
        for code, number in ((left, right), (right, left)):
            if _SUPPLIER_CODE.fullmatch(code.group(0)) and _CATALOGUE_NUMBER.fullmatch(
                number.group(0)
            ):
                found.add(code.group(0))
    return found


def path_values(node: Any) -> Iterator[str]:
    """Every path-valued string: fields whose key holds `path`, file names, and the Windows
    paths SOLIDWORKS embeds in persistent references."""
    for key, _, value in _fields(node):
        if is_path_key(key) or key == "file_name":
            yield value
        elif key == "persist_ref":
            yield from (run for run in decoded_runs(value) if _WINDOWS_ANCHOR.match(run))


def folders_of(path: str) -> list[str]:
    """A Windows path's folder segments after its anchor, root included, file excluded."""
    anchor = _WINDOWS_ANCHOR.match(path)
    if anchor is None:
        return []
    return path[anchor.end() :].split("\\")[:-1]


def folder_names(*nodes: Any) -> set[str]:
    """Every folder name the Windows paths of `nodes` carry: for the owner's denylist only."""
    return {folder for node in nodes for value in path_values(node) for folder in folders_of(value)}


def strict_tokens(*nodes: Any) -> set[str]:
    """The tokens no allowlist may keep anywhere: those of paths and names, and supplier codes.

    Every token of a path-valued field, a file name, a component's or the design's name, and a
    Windows path inside a persistent reference - sizes, one- or two-digit numbers and single
    characters apart - and every supplier code next to a catalogue number in any string.
    `FictionalMap` maps each of them wherever it appears.
    """
    found: set[str] = set()
    for node in nodes:
        for key, parent, value in _fields(node):
            if key in PACKAGE_VERBATIM_KEYS:
                continue
            texts = [value] if _is_strict_field(key, parent) else []
            if key == "persist_ref":
                texts = [run for run in decoded_runs(value) if _WINDOWS_ANCHOR.match(run)]
            for text in texts:
                stem, _ = split_extension(text)
                found.update(token for token in tokens_of(stem) if not is_generic_shape(token))
            found.update(supplier_codes(value))
    return found


def letters(token: str) -> int:
    """How many letters a token has: the property checks police words of three or more."""
    return sum(1 for character in token if character.isalpha())


def property_strings(node: Any) -> Iterator[str]:
    """Every key and every string value of every custom-property and configuration-property
    map in a JSON-shaped node. A configuration's own name is not one of them."""
    if isinstance(node, Mapping):
        for name, item in node.items():
            if name in _PROPERTY_MAP_KEYS and isinstance(item, Mapping):
                yield from _keys_and_values(item)
            elif name in _CONFIGURATION_MAP_KEYS and isinstance(item, Mapping):
                for properties in item.values():
                    if isinstance(properties, Mapping):
                        yield from _keys_and_values(properties)
            else:
                yield from property_strings(item)
    elif isinstance(node, list):
        for item in node:
            yield from property_strings(item)


def _keys_and_values(properties: Mapping[str, Any]) -> Iterator[str]:
    for key, value in properties.items():
        yield str(key)
        yield from strings_of(value)


def _link_pieces(value: str) -> list[tuple[str, bool]]:
    """A property string cut into `(text, is a kept SOLIDWORKS link head)` pieces, in order.

    A link head (`SW-Density@`) is kept verbatim only when every word of its name is generic
    SOLIDWORKS vocabulary; any other `SW-...@` is scrambled like the rest of the string.
    """
    pieces: list[tuple[str, bool]] = []
    last = 0
    for match in _SW_LINK.finditer(value):
        if not all(is_allowed_token(token) for token in tokens_of(match.group("name"))):
            continue
        pieces += [(value[last : match.start()], False), (match.group(0), True)]
        last = match.end()
    pieces.append((value[last:], False))
    return pieces


def strict_property_words(value: str, public: frozenset[str] = frozenset()) -> list[str]:
    """The words of one property key or value that are scrambled, wherever else they appear.

    Every token, except: a whole value that is only numbers, fractions or dates; a size, a
    number of one or two digits and a single character (`is_generic_shape`); the head of a
    SOLIDWORKS link (`SW-Density@`); and a word the standards profile names (`public`,
    case-folded, `profile_words`).
    """
    if _ENTITY_ID.fullmatch(value) or is_plain_number(value):
        return []
    return [
        token
        for piece, kept in _link_pieces(value)
        if not kept
        for token in tokens_of(piece)
        if not is_generic_shape(token) and token.casefold() not in public
    ]


def property_tokens(*nodes: Any, public: frozenset[str] = frozenset()) -> set[str]:
    """Every strict word of every property key and value in `nodes` (`strict_property_words`)."""
    return {
        token
        for node in nodes
        for text in property_strings(node)
        for token in strict_property_words(text, public)
    }


def profile_words(path: Path | str) -> frozenset[str]:
    """Every word, case-folded, of the names and values a standards profile compares with a
    package, read from the profile itself: its data-card property names, its part-number
    pattern, its revision property, initial value and header text, its material
    configuration and its export-control phrase.

    Not its vault root or its library prefixes: those are folders, and no folder word is kept.
    A profile committed to this repository is public, so its words may stay in a property
    key or value - and must, for the profile the fixtures are graded with to find what it
    requires.
    """
    profile = load_profile(path)
    texts = [
        *profile.data_card.properties,
        profile.part_number.pattern,
        profile.revision.property,
        profile.revision.initial,
        profile.revision.header_text,
        profile.material.configuration,
        profile.export_control.phrase,
    ]
    return frozenset(token.casefold() for text in texts for token in tokens_of(text))


def without_reviewer_text(value: str) -> str:
    """`value` with every sentence of `REVIEWER_OWN_TEXT` taken out, for the leak checks."""
    for sentence in REVIEWER_OWN_TEXT:
        value = value.replace(sentence, "")
    return value


def denylist_path() -> Path:
    """The owner's denylist, outside the repository: `%LOCALAPPDATA%\\SwReview\\...`."""
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "SwReview" / "fixture-denylist.txt"


def read_denylist(path: Path) -> tuple[set[str], set[str]]:
    """`(tokens, folder names)` from the owner's denylist; `(set(), set())` when absent."""
    if not path.is_file():
        return set(), set()
    tokens: set[str] = set()
    folders: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(DENYLIST_FOLDER_PREFIX):
            folders.add(line[len(DENYLIST_FOLDER_PREFIX) :])
        elif line.strip():
            tokens.add(line.strip())
    return tokens, folders


def write_denylist(path: Path, tokens: Iterable[str], folders: Iterable[str]) -> None:
    """Write the owner's denylist: one token per line, then one folder name per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = sorted(set(tokens)) + [
        DENYLIST_FOLDER_PREFIX + folder for folder in sorted(set(folders))
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Draws:
    """A fixed pseudo-random stream seeded by an ordinal: no content, no secret."""

    def __init__(self, seed: int) -> None:
        self._state = seed % 2**31

    def next(self) -> int:
        self._state = (self._state * 1_103_515_245 + 12_345) % 2**31
        return self._state >> 8


class FictionalMap:
    """One scrambling of one recording: every identifying token to one fictional token."""

    def __init__(
        self,
        *,
        reserved: Iterable[str] = (),
        keep: Iterable[str] = (),
        strict: Iterable[str] = (),
        public: Iterable[str] = (),
    ) -> None:
        self.replaced: dict[str, str] = {}
        """Original token -> its fictional replacement, in first-seen order."""
        self._reserved = frozenset(reserved)
        self._keep = frozenset(keep)
        """Tokens this recording's own structure names as vocabulary - its SOLIDWORKS type
        names - kept wherever else they are quoted, such as a gap listing skipped types."""
        self._strict = set(strict)
        """Tokens mapped even when the allowlist would keep them: the words of paths and names,
        supplier codes (`strict_tokens`) and the words of property keys and values
        (`property_tokens`). It grows as paths, names and properties are scrambled."""
        self._public = frozenset(word.casefold() for word in public)
        """Words, case-folded, the standards profile the fixtures are graded with names
        (`profile_words`): public, so kept like generic vocabulary, property keys and values
        included - unless a path or a name made them strict."""
        self._used: set[str] = set()
        self._hex: dict[str, str] = {}
        self._local: dict[str, str] = {}
        """Folder-only replacements of tokens kept everywhere else (sizes, short numbers)."""
        self._ordinal = 0

    # --- one token ---------------------------------------------------------------------

    def token(self, token: str) -> str:
        """`token` itself when generic, else its fictional replacement (assigned once)."""
        if token in self._keep:
            return token
        if token not in self._strict and (
            is_allowed_token(token) or token.casefold() in self._public
        ):
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
            # A replacement never reads as generic vocabulary, a strict generic word's included:
            # only a generic token of fewer than three letters (`A1`) may land on another one,
            # since every token of its shape is generic.
            if (
                candidate != token
                and candidate not in self._used
                and candidate not in self._reserved
                and (
                    not is_allowed_token(candidate)
                    or (is_allowed_token(token) and letters(token) < 3)
                )
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
        return self._scrambled(value, self.token)

    def name(self, value: str) -> str:
        """A strict name - a file stem, a component's name or path: no allowlist applies.

        Every token but a size, a one- or two-digit number and a single character is mapped,
        and becomes strict everywhere else, so the same word in a description or a gap reason
        is mapped the same way.
        """
        return self._scrambled(value, self._strict_token)

    def _strict_token(self, token: str) -> str:
        if token in self._keep or is_generic_shape(token):
            return token
        self._strict.add(token)
        return self.token(token)

    def _folder_token(self, token: str) -> str:
        """A folder admits nothing: what a name would keep is replaced here, and here only."""
        if token in self._keep or is_generic_shape(token):
            return self._folder_only(token)
        return self._strict_token(token)

    def _folder_only(self, token: str) -> str:
        known = self._local.get(token)
        if known is not None:
            return known
        ordinal = len(self._local)
        attempt = 0
        while True:
            candidate = self._draw(token, ordinal + 7_919, attempt)
            if candidate != token:
                self._local[token] = candidate
                return candidate
            attempt += 1

    def _scrambled(self, value: str, token: Callable[[str], str]) -> str:
        def piece(match: re.Match[str]) -> str:
            if match.group("hex"):
                prefix, digits = match.group("hex").split(":")
                return f"{prefix}:{self._hex_part(digits)}"
            if match.group("entity"):
                return match.group("entity")
            return token(match.group("word"))

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

        The anchor (a drive, or a UNC server) and the first folder become the fictional root.
        Every later folder is scrambled whole, with no allowlist at all (`_folder_token`); the
        file is scrambled as a strict name (`file_name`) with its extension kept. A path of one
        segment keeps that segment, as a file, under the root.
        """
        anchor = _WINDOWS_ANCHOR.match(value)
        if anchor is None:
            return self.name(value)
        segments = value[anchor.end() :].split("\\")
        if len(segments) >= 2:
            # The first folder is replaced by the fictional root rather than scrambled, but its
            # tokens are still mapped: a vault root names its owner, and the leak check and the
            # denylist must know that name wherever else it turns up.
            self._scrambled(segments[0], self._folder_token)
            segments = segments[1:]
        folders = [self._scrambled(folder, self._folder_token) for folder in segments[:-1]]
        return FICTIONAL_ROOT + "\\".join([*folders, self.file_name(segments[-1])])

    def file_name(self, value: str) -> str:
        """A file name: the stem a strict name, the extension kept when it is a file type."""
        stem, extension = split_extension(value)
        return self.name(stem) if extension is None else f"{self.name(stem)}.{extension}"

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
        """A property map: every key and every string value strict (`property_text`)."""
        return {
            self.property_text(key): self.property_text(item)
            if isinstance(item, str)
            else self._walk(item, None, None)
            for key, item in properties.items()
        }

    def property_text(self, value: str) -> str:
        """One property key or value, strict like a name: no allowlist applies.

        Every word is mapped, and becomes strict everywhere else, so a word of a property that
        reappears in a gap reason, a configuration name or the model's prose is mapped there
        the same way. Kept: an id, or a whole value of numbers, fractions or dates; a size, a
        one- or two-digit number and a single character; the head of a SOLIDWORKS link
        (`SW-Density@`, around a scrambled configuration and document); and a word the
        standards profile names (`public`). A Windows path is a path.
        """
        if _ENTITY_ID.fullmatch(value) or is_plain_number(value):
            return value
        if _WINDOWS_ANCHOR.match(value):
            return self.path(value)
        return "".join(
            piece if kept else self._scrambled(piece, self._property_token)
            for piece, kept in _link_pieces(value)
        )

    def _property_token(self, token: str) -> str:
        if token not in self._strict and token.casefold() in self._public:
            return token
        return self._strict_token(token)

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
        """A raw `package.json` object, scrambled field by field (deny by default).

        The package's strict tokens are found first (`strict_tokens`, `property_tokens`), so a
        word that is a folder, a file stem or a property word anywhere is mapped everywhere,
        whatever order the fields come in.
        """
        self._strict |= strict_tokens(raw) | property_tokens(raw, public=self._public)
        return self._walk(raw, None, None)

    def _walk(self, node: Any, key: str | None, parent: str | None) -> Any:
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
                    out[name] = self._walk(item, name, key)
            return out
        if isinstance(node, list):
            return [self._walk(item, key, parent) for item in node]
        if not isinstance(node, str) or key in PACKAGE_VERBATIM_KEYS:
            return node
        if key == "persist_ref":
            return self.persist_ref(node)
        if key == "reuse_key":
            return self.full_hex(node)
        if is_path_key(key):
            return self.path(node) if _WINDOWS_ANCHOR.match(node) else self.name(node)
        if key == "file_name":
            return self.file_name(node)
        if _is_strict_field(key, parent):
            return self.name(node)
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
