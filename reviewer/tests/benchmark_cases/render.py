"""The renderers of a case (feature 014 `generator.md` 7, 8 and 10; `cases.md` 4.2 and 6.1; GN-4).

`render_spec(spec)` is the one renderer of a case's files and `set_entries(spec)` of its set
entries: `generate.render_all()`, the validation (`tests/support/reachability.py`) and the
generator's tests call these two and no other renderer of a case. A case is laid by its design
with every seed's planted form and every condition kind's clean form applied, then written:

- **the package**: `mechanical.Built.render()`'s bytes, `package.json` and its meshes, with the
  identity of `generator.md` 5.5 set after the builders ran: IR `package_id`
  `uuid5(CASE_NAMESPACE, case_id)`, `design.design_id` the case id, schema `CASE_SCHEMA_VERSION`,
  `created_at` `mechanical.CREATED_AT`;
- **the key**: an `AnswerKey` of format 2, built through the model (RF-1): each seed a known
  defect `D-<n>` with its kind's check, producer and expected status, then the conditions,
  forbidden entries, expected coverage, unanswerable requests and question counts, each list
  numbered in spec order; every reference's owner among the entry's parts and documents
  (`answer-key.md` 4 row 14);
- **the case file**: a `CaseFile`, only for a spec with answers;
- and, when `spec.twin`, the same for `spec.twin(spec)`.

Every place name resolves through `resolve`, the one place-name resolver, which the validation
reads for correct calls and decoys (`correct_calls`, `decoy_calls`). `set_files` writes the three
committed set files through `BenchmarkSet.file_form`, the one serializer of the committed form
(RF-54). `names_offences` is section 8's names check and 5.5's fictional-roots check, rows 9 and
10; a format model refusing what a spec built is row 11. Every JSON file is UTF-8, LF, indented
2, with a final newline and non-ASCII written as itself.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid5

from pydantic import ValidationError

from swreview.benchmark.answer_key_model import KEY_FORMAT, AnswerKey
from swreview.benchmark.case_file import CASE_FILE_VERSION, CaseFile
from swreview.benchmark.sets import REPO_ROOT, BenchmarkPackageRef, BenchmarkSet
from swreview.ir.models import EvidencePackage, SourceRef
from tests.benchmark_cases.spec import (
    CASE_NAMESPACE,
    At,
    CaseSpec,
    CaseSpecError,
    Condition,
    Coverage,
    Forbidden,
    Form,
    HeldOut,
    KeyOnly,
    Laid,
    Place,
    PlaceName,
    Places,
    QuestionCount,
    SeedKind,
    Tag,
    ToolCall,
    Unanswerable,
    key_only_entries,
    twin,
)
from tests.benchmark_cases.vocabulary import EXAMPLE_PROFILE, name_offences
from tests.support.mechanical import CREATED_AT, FICTIONAL_ROOT, Built

PACKAGES = "benchmarks/packages"
ANSWER_KEYS = "benchmarks/answer_keys"
CASE_FILES = "benchmarks/case_files"
SETS = "benchmarks/sets"
"""The four folders the generator writes, repository-relative (`cases.md` 1)."""

CASE_SCHEMA_VERSION = "1.6.0"
"""Every generated package's IR version, set after the builders ran, so a case does not change
when the IR's minor does (`generator.md` 5.5)."""

PANE_SMOKE_CASES = ("kalo-1", "kalo-fit-1")
"""`pane-smoke.json`'s entries, each as `committed.json` holds it and in its order: one held-out
core case and the anchor with a case file (quickstart P0; owner decision 35A; RF-89)."""

FICTIONAL_ROOTS: tuple[str, ...] = (FICTIONAL_ROOT, "/Designs/", EXAMPLE_PROFILE.vault_root)
"""The named fictional roots every path lies under (`generator.md` 5.5; research §8.8)."""


# --- the place-name resolver -----------------------------------------------------------------


def resolve(value: Any, ids: Mapping[str, str | SourceRef]) -> Any:
    """`value` with every `PlaceName` replaced by its place's id, at any depth: a drawn
    dimension's as `{document_id, sheet, annotation}`, the JSON a model sends, and a hole
    instance as `"<hole id>#<n>"`. Mappings come back as dicts and sequences as lists."""
    if isinstance(value, PlaceName):
        if value.name not in ids:
            raise ValueError(f"{value.name} is no place the design laid")
        target = ids[value.name]
        if isinstance(target, SourceRef):
            if value.instance is not None:
                raise ValueError(f"{value.name} is a drawn dimension, which has no instance")
            return {
                "document_id": target.document_id,
                "sheet": target.sheet,
                "annotation": target.annotation,
            }
        return target if value.instance is None else f"{target}#{value.instance}"
    if isinstance(value, Mapping):
        return {key: resolve(item, ids) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [resolve(item, ids) for item in value]
    return value


def _resolve_call(call: ToolCall, ids: Mapping[str, str | SourceRef]) -> ToolCall:
    return ToolCall(call.tool, resolve(call.arguments, ids))


# --- laying a case ---------------------------------------------------------------------------


def _forms(case: CaseSpec) -> list[tuple[Form, At]]:
    """Each seed's planted form, then each condition kind's clean form, at its places."""
    forms: list[tuple[Form, At]] = []
    for seed in case.seeds:
        if seed.kind.plant is None:
            raise CaseSpecError(case.case_id, f"{seed.kind.name} has no planted form")
        forms.append((seed.kind.plant, seed.at))
    for condition in case.conditions:
        if condition.kind is not None:
            if condition.kind.clean is None:
                raise CaseSpecError(case.case_id, f"{condition.kind.name} has no clean form")
            forms.append((condition.kind.clean, condition.at))
    return forms


def _laid(case: CaseSpec) -> tuple[dict[str, Place], Laid]:
    """The case's records with every form applied, and its design laid from them. A form that
    cannot apply on the design (a design fact it needs is missing), or a builder refusing what
    the design lays, refuses naming the case."""
    try:
        places = case.design.formed(_forms(case))
        return places, case.design.lay(case.variant, places)
    except ValueError as error:
        if isinstance(error, CaseSpecError):
            raise
        raise CaseSpecError(case.case_id, str(error)) from None


def _condition_calls(condition: Condition, places: Places) -> Sequence[ToolCall]:
    """A condition's correct calls: the one it names, or its kind's where they confirm its clean
    form (`SeedKind.confirms_clean`: never a drawing kind's or `coaxiality_undrawn`'s,
    `generator.md` 4)."""
    if condition.correct_call is not None:
        return (condition.correct_call,)
    if condition.kind is not None and condition.kind.confirms_clean:
        return condition.kind.correct_calls(condition.at, places)
    return ()


def correct_calls(case: CaseSpec) -> list[ToolCall]:
    """Every correct call of `case`, resolved, in order: its seeds' kinds', then its
    conditions' (FR-054 (b), `cases.md` 7)."""
    places, laid = _laid(case)
    calls = [call for seed in case.seeds for call in seed.kind.correct_calls(seed.at, places)]
    calls.extend(
        call for condition in case.conditions for call in _condition_calls(condition, places)
    )
    return [_resolve_call(call, laid.ids) for call in calls]


def decoy_calls(case: CaseSpec) -> list[ToolCall]:
    """Every decoy of `case`, resolved, in order: its seeds' kinds', then its own
    (`cases.md` 7)."""
    places, laid = _laid(case)
    calls = [call for seed in case.seeds for call in seed.kind.decoys(seed.at, places)]
    calls.extend(case.decoys)
    return [_resolve_call(call, laid.ids) for call in calls]


# --- the key and the case file ---------------------------------------------------------------


def _json(data: Any) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _refusal(error: ValidationError) -> str:
    """A format model's refusals as one line: its own rows' sentences, which name the entry, and
    pydantic's as `<field>: <message>` (the readers' wording, `findings.model_refusals`, which
    the generator may not import)."""
    clauses = []
    for line in error.errors(include_url=False):
        if line["type"] == "value_error":
            clauses.append(line["msg"].removeprefix("Value error, "))
        else:
            location = ".".join(str(part) for part in line["loc"])
            clauses.append(f"{location}: {line['msg']}")
    return "; ".join(clauses)


def _tag_fields(tag: Tag) -> dict[str, Any]:
    """`tag`, and `held_out_against` exactly when held out (data-model section 2)."""
    if isinstance(tag, HeldOut):
        return {"tag": "held_out", "held_out_against": tag.stamp.model_dump()}
    return {"tag": "tuned_on"}


def _unique(ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _owners(references: Sequence[Any], package: EvidencePackage) -> tuple[list[str], list[str]]:
    """The components owning the holes and fasteners `references` name, and the documents its
    dimensions lie on (`answer-key.md` 4 row 14)."""
    holes = {row.id: row.component_id for row in package.holes}
    fasteners = {row.id: row.component_id for row in package.fasteners}
    components: list[str] = []
    documents: list[str] = []

    def owner(table: Mapping[str, str], value: str, what: str) -> str:
        if value not in table:
            raise ValueError(f"a reference names {value}, which is no {what} of the package")
        return table[value]

    def visit(value: Any, role: str | None) -> None:
        if isinstance(value, Mapping):
            if set(value) == {"document_id", "sheet", "annotation"}:
                documents.append(value["document_id"])
                return
            for key, item in value.items():
                visit(item, key)
        elif isinstance(value, list):
            for item in value:
                visit(item, role)
        elif isinstance(value, str) and role == "fastener":
            components.append(owner(fasteners, value, "fastener"))
        elif isinstance(value, str) and role in ("hole", "holes", "hole_instances", "recess"):
            components.append(owner(holes, value.split("#", 1)[0], "hole"))

    for element in references:
        visit(element, None)
    return components, documents


def _targets(
    references: list[Any],
    parts: Sequence[str],
    documents: Sequence[str],
    package: EvidencePackage,
    ids: Mapping[str, str | SourceRef],
) -> dict[str, Any]:
    """An entry's `component_ids`, `document_ids` and `references`: the places it names, then
    its references' owners not yet named; `references` only when there are some."""
    components, owner_documents = _owners(references, package)
    fields: dict[str, Any] = {
        "component_ids": _unique([resolve(PlaceName(name), ids) for name in parts] + components),
        "document_ids": _unique(
            [resolve(PlaceName(name), ids) for name in documents] + owner_documents
        ),
    }
    if references:
        fields["references"] = references
    return fields


def _kind_entry(
    kind: SeedKind, at: At, places: Places, package: EvidencePackage, ids: Mapping[str, Any]
) -> dict[str, Any]:
    """What a kind keys at its places: its check and its targets."""
    references = resolve(list(kind.references(at, places)), ids)
    return {
        "check": kind.check,
        **_targets(references, kind.parts(at, places), kind.documents(at, places), package, ids),
    }


def _key_only(
    entry_id: str,
    entry: KeyOnly,
    places: Places,
    package: EvidencePackage,
    ids: Mapping[str, str | SourceRef],
) -> dict[str, Any]:
    """A key-only entry's fields, its place names resolved; never its `represents`, which the
    set entry carries (a key entry carries none, `cases.md` 9)."""
    fields: dict[str, Any] = {"id": entry_id}
    if isinstance(entry, Condition):
        if entry.kind is not None:
            fields.update(_kind_entry(entry.kind, entry.at, places, package, ids))
        else:
            fields["check"] = entry.check
            fields.update(
                _targets(
                    resolve(list(entry.references), ids),
                    entry.component_ids,
                    entry.document_ids,
                    package,
                    ids,
                )
            )
    elif isinstance(entry, Forbidden):
        fields["checks"] = list(entry.checks)
        fields.update(_targets([], entry.component_ids, entry.document_ids, package, ids))
    elif isinstance(entry, Coverage):
        fields.update(item=entry.item, statuses=list(entry.statuses))
    elif isinstance(entry, Unanswerable):
        fields["documents"] = [resolve(PlaceName(name), ids) for name in entry.documents]
        fields["item"] = entry.item
    elif isinstance(entry, QuestionCount):
        if entry.part_roles is not None:
            fields["part_roles"] = entry.part_roles
        fields.update(
            item=entry.item,
            ids=[resolve(PlaceName(name), ids) for name in entry.ids],
            min=entry.min,
            max=entry.max,
        )
    return {**fields, **_tag_fields(entry.tag), "description": entry.description}


def _key(case: CaseSpec, places: Places, laid: Laid, package: EvidencePackage) -> AnswerKey:
    """The case's key, built through the `AnswerKey` model; a refusal names the case (row 11)."""
    defects = []
    for number, seed in enumerate(case.seeds, start=1):
        assert seed.kind.plant is not None and seed.kind.expected_status is not None
        defects.append(
            {
                "id": f"D-{number}",
                **_kind_entry(seed.kind, seed.at, places, package, laid.ids),
                "producer": seed.kind.producer,
                "expected_status": seed.kind.expected_status,
                **_tag_fields(seed.tag),
                "description": seed.kind.plant.words,
            }
        )
    lists: dict[str, list[dict[str, Any]]] = {}
    for key_list, entry_id, entry in key_only_entries(case):
        lists.setdefault(key_list, []).append(_key_only(entry_id, entry, places, package, laid.ids))
    try:
        return AnswerKey.model_validate(
            {
                "key_format": KEY_FORMAT,
                "package_id": case.case_id,
                "known_defects": defects,
                **lists,
            }
        )
    except ValidationError as error:
        raise CaseSpecError(case.case_id, _refusal(error)) from None


def _case_file(case: CaseSpec, ids: Mapping[str, str | SourceRef]) -> CaseFile:
    """The case's scripted answers through the `CaseFile` model, each entry in its own shape."""
    answers = []
    for number, answer in enumerate(case.answers, start=1):
        if answer.part_roles:
            answers.append({"id": f"A-{number}", "part_roles": True, "answer": answer.answer})
        else:
            answers.append(
                {
                    "id": f"A-{number}",
                    "item": answer.item,
                    "ids": [resolve(PlaceName(name), ids) for name in answer.ids],
                    "answer": answer.answer,
                }
            )
    try:
        return CaseFile.model_validate(
            {"case_file_version": CASE_FILE_VERSION, "package_id": case.case_id, "answers": answers}
        )
    except ValidationError as error:
        raise CaseSpecError(case.case_id, _refusal(error)) from None


# --- one case's files and set entry ----------------------------------------------------------


@dataclass(frozen=True)
class _Rendered:
    files: dict[str, bytes]
    key: AnswerKey


def _render(case: CaseSpec) -> _Rendered:
    """One case, never its twin: its package, key and case file, and its key for its entry."""
    places, laid = _laid(case)
    package = laid.package.model_copy(
        update={
            "schema_version": CASE_SCHEMA_VERSION,
            "package_id": uuid5(CASE_NAMESPACE, case.case_id),
            "created_at": CREATED_AT,
            "design": laid.package.design.model_copy(update={"design_id": case.case_id}),
        }
    )
    try:
        key = _key(case, places, laid, package)
    except ValueError as error:
        if isinstance(error, CaseSpecError):
            raise
        raise CaseSpecError(case.case_id, str(error)) from None
    files = {
        f"{PACKAGES}/{case.case_id}/{path}": content
        for path, content in Built(package=package, meshes=dict(laid.meshes)).render().items()
    }
    files[f"{ANSWER_KEYS}/{case.case_id}.json"] = _json(
        key.model_dump(mode="json", exclude_none=True)
    )
    if case.answers:
        files[f"{CASE_FILES}/{case.case_id}.json"] = _json(
            _case_file(case, laid.ids).model_dump(mode="json")
        )
    return _Rendered(files=files, key=key)


def _cases(case: CaseSpec) -> list[tuple[CaseSpec, str | None]]:
    """`case`, and its twin after it when it has one, each with the case it is the twin of."""
    return [(case, None), (twin(case), case.case_id)] if case.twin else [(case, None)]


def render_spec(case: CaseSpec) -> dict[str, bytes]:
    """Every file of `case`, and of its twin when `case.twin`, by repository-relative POSIX path."""
    files: dict[str, bytes] = {}
    for rendered, _ in _cases(case):
        files.update(_render(rendered).files)
    return files


def set_entries(case: CaseSpec) -> list[BenchmarkPackageRef]:
    """`case`'s set entry, and its twin's after it: paths at `sets.REPO_ROOT`, `key` and `design`
    on every entry, `held_out` the rendered key's `holds_held_out()` (RF-67), `twin_of` on a
    twin, `represents` only where the case names some."""
    entries = []
    for rendered, twin_of in _cases(case):
        key = _render(rendered).key
        entries.append(
            BenchmarkPackageRef(
                package_id=rendered.case_id,
                path=REPO_ROOT / PACKAGES / rendered.case_id,
                key=REPO_ROOT / ANSWER_KEYS / f"{rendered.case_id}.json",
                case_file=(
                    REPO_ROOT / CASE_FILES / f"{rendered.case_id}.json"
                    if rendered.answers
                    else None
                ),
                held_out=key.holds_held_out(),
                design=rendered.design.name,
                twin_of=twin_of,
                represents=list(rendered.represents) or None,
            )
        )
    return entries


def set_files(cased: Sequence[tuple[CaseSpec, list[BenchmarkPackageRef]]]) -> dict[str, bytes]:
    """`committed.json`, `pilot.json` and `pane-smoke.json` (`cases.md` 6.1) from each spec's
    entries, in spec order, written by `BenchmarkSet.file_form` (RF-54): `pane-smoke.json`
    holds `committed.json`'s entries for `PANE_SMOKE_CASES`, as it holds them and in its order
    (that it holds both is the committed-set test's, `cases.md` 9)."""
    committed = [entry for case, entries in cased if "committed" in case.sets for entry in entries]
    pilot = [entry for case, entries in cased if "pilot" in case.sets for entry in entries]
    smoke = [entry for entry in committed if entry.package_id in PANE_SMOKE_CASES]
    return {
        f"{SETS}/{name}.json": BenchmarkSet(name=name, packages=entries).file_form(root=REPO_ROOT)
        for name, entries in (("committed", committed), ("pilot", pilot), ("pane-smoke", smoke))
    }


# --- rows 9 and 10: names and fictional roots -------------------------------------------------


def _pointer(*parts: object) -> str:
    """An RFC 6901 JSON pointer."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _property_names(
    base: tuple[object, ...], properties: Mapping[str, str]
) -> Iterator[tuple[str, str, bool]]:
    for name, value in properties.items():
        yield _pointer(*base, name), name, False
        yield _pointer(*base, name), value, False


def _package_names(data: Mapping[str, Any]) -> Iterator[tuple[str, str, bool]]:
    """Every name `package.json` carries, as (pointer, text, is a path) (`generator.md` 8)."""
    yield _pointer("design", "name"), data["design"]["name"], False
    for index, document in enumerate(data.get("documents", [])):
        base = ("documents", index)
        yield _pointer(*base, "file_name"), document["file_name"], False
        yield _pointer(*base, "path"), document["path"], True
        for number, configuration in enumerate(document.get("configurations", [])):
            yield _pointer(*base, "configurations", number), configuration, False
        yield _pointer(*base, "active_configuration"), document["active_configuration"], False
        yield from _property_names((*base, "custom_properties"), document["custom_properties"])
        for configuration, properties in document["config_properties"].items():
            yield _pointer(*base, "config_properties", configuration), configuration, False
            yield from _property_names((*base, "config_properties", configuration), properties)
        if document.get("material") is not None:
            yield _pointer(*base, "material"), document["material"], False
    for index, component in enumerate(data.get("components", [])):
        for name in ("name", "full_path", "referenced_configuration"):
            yield _pointer("components", index, name), component[name], False
    for index, hole in enumerate(data.get("holes", [])):
        yield _pointer("holes", index, "feature_name"), hole["feature_name"], False
    for index, row in enumerate(data.get("features", [])):
        yield _pointer("features", index, "name"), row["name"], False
    for index, entry in enumerate(data["manifest"]["entries"]):
        yield _pointer("manifest", "entries", index, "vault_path"), entry["vault_path"], True
        yield _pointer("manifest", "entries", index, "configuration"), entry["configuration"], False
    for index, sheet in enumerate(data.get("drawings", [])):
        yield _pointer("drawings", index, "sheet_name"), sheet["sheet_name"], False
        for number, dimension in enumerate(sheet["dimensions"]):
            pointer = _pointer("drawings", index, "dimensions", number, "text_as_read")
            yield pointer, dimension["text_as_read"], False
    for index, candidate in enumerate(data.get("drawing_candidates", [])):
        yield _pointer("drawing_candidates", index, "path"), candidate["path"], True


def _set_names(data: Mapping[str, Any]) -> Iterator[tuple[str, str, bool]]:
    yield _pointer("name"), data["name"], False
    for index, entry in enumerate(data["packages"]):
        for name in ("package_id", "design", "twin_of"):
            if entry.get(name) is not None:
                yield _pointer("packages", index, name), entry[name], False


def _named(path: str, data: Any) -> tuple[str, Iterator[tuple[str, str, bool]]]:
    """The case a rendered file belongs to, and the names it carries."""
    if path.startswith(f"{SETS}/"):
        return data["name"], _set_names(data)
    if path.startswith(f"{PACKAGES}/"):
        return path.split("/")[2], _package_names(data)
    return data["package_id"], iter([(_pointer("package_id"), data["package_id"], False)])


def names_offences(rendered: Mapping[str, bytes]) -> list[tuple[str, str]]:
    """Every offence of rows 9 and 10 over `rendered`, as (case id, detail), names first: a token
    of a name outside `CASE_VOCABULARY` (`generator.md` 8), then a path outside the named
    fictional roots (5.5). Names are held to the vocabulary, never sentences; a GLB is the
    denylist test's (`test_benchmark_cases_are_fictional.py`)."""
    names: list[tuple[str, str]] = []
    roots: list[tuple[str, str]] = []
    for path, content in rendered.items():
        if not path.endswith(".json"):
            continue
        case_id, carried = _named(path, json.loads(content))
        for pointer, text, is_path in carried:
            names.extend(
                (
                    case_id,
                    f"{path} {pointer}: {token!r} is not in the case vocabulary (generator.md 8)",
                )
                for token in name_offences(text)
            )
            if is_path and not text.startswith(FICTIONAL_ROOTS):
                roots.append(
                    (
                        case_id,
                        f"{path} {pointer}: {text} lies under none of the fictional roots "
                        f"{', '.join(FICTIONAL_ROOTS)} (generator.md 5.5)",
                    )
                )
    return names + roots
