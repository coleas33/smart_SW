"""One canonical JSON Schema per tool, and the two provider forms derived from it.

Feature 001 let the retired vendor SDK generate tool schemas from the function signature and
docstring. With the SDK gone (FR-026) this module does that job, and it does it once:
`canonical_schema(fn)` is the single provider-neutral form, and `strictify()` and
`gemini_adapt()` derive the OpenAI and Gemini forms from it. No tool module and no adapter
writes a schema by hand.

**Canonical** (`canonical_schema`): `pydantic.TypeAdapter(fn).json_schema()` for the types,
the Google-style `Args:` block of the docstring for the parameter descriptions, and every
`$def` inlined so no consumer has to resolve a `$ref`. A parameter the docstring does not
describe is a `ValueError`, not a schema with a blank description: the description is what
the model reads to decide whether the tool applies at all.

**OpenAI strict** (`strictify`): `additionalProperties: false` on every object, every
property in `required`, and an optional **top-level parameter** rewritten as
`{"type": ["T", "null"]}`. Four consequences are worth spelling out, because each is a
trap:

- the nullable rewrite stops at the top level, because that is as deep as its other half
  reaches: `tools/registry.py:_prepared` reads a null as "use the default" and drops it
  from the arguments object, and nowhere deeper. A nested field that is defaulted but not
  `| None` - `CoverageScope.component_ids: list[str] = []` - therefore just becomes
  mandatory, which is what `openai/lib/_pydantic.py:_ensure_strict_json_schema` does and
  what pydantic accepts; inventing a null for it would make the schema demand exactly the
  payload the tool layer then rejects. `tests/unit/test_provider_schema.py` round-trips
  both halves so they cannot drift apart again;

- a zero-property object and an `additionalProperties: true` object have no strict-mode
  form at all - closed and empty, an object accepts nothing and reports nothing, which is
  how a free-form `dict[str, Any]` parameter silently swallows every key the model sent.
  T005a replaced the two such parameters with explicit models; `tests/unit/
  test_provider_schema.py` asserts none ever comes back;
- an `anyOf` branch must itself be a valid schema in OpenAI's supported subset, so the
  constraint-only branches pydantic emits for `SourceRef`'s "at least one locator" rule
  (`{"required": ["sheet"]}`) are dropped. The rule is not lost: it is a pydantic model
  validator and still runs when `RecordedTool` validates the call;
- `default: null` is dropped (it says nothing once every property is required), while a
  default that is not null is kept, because it tells the model what to send for a
  parameter it does not care about. That is also what `openai/lib/_pydantic.py` does.

**The description has two halves** (lever 2, feature 005): `parse_docstring` returns the
docstring's `Notes:` block beside the description instead of discarding it, and
`ToolSpec.full_description` rejoins them byte-equal to the pre-split docstring body, so the
flag-off path sends exactly the bytes this tree sent before the split (FR-039). The caps
the split is measured at - `MAX_DESCRIPTION_LENGTH`, `MAX_PARAMETER_DESCRIPTION_LENGTH` -
are enforced by a test through `cap_violations` and never by truncating at run time.

**Gemini** (`gemini_adapt`): `types.FunctionDeclaration(parameters_json_schema=...)` takes
standard JSON Schema, so the canonical form goes across almost unchanged - only
`additionalProperties` and `$defs` come out. Nullable unions stay `anyOf` (research R3).
"""

from __future__ import annotations

import copy
import inspect
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_PARAMETER_DESCRIPTION_LENGTH",
    "ToolSpec",
    "canonical_schema",
    "cap_violations",
    "gemini_adapt",
    "parse_docstring",
    "strictify",
    "tool_spec",
]

REF_TEMPLATE = "#/$defs/{model}"
REF_PREFIX = "#/$defs/"

MAX_NAME_LENGTH = 60
TOOL_NAME = re.compile(rf"[a-z0-9_]{{1,{MAX_NAME_LENGTH}}}")
"""A tool name as every provider requires it (data-model section 1)."""

SECTION_HEADER = re.compile(
    r"^(Args|Arguments|Returns|Raises|Yields|Example|Examples|Note|Notes|Attributes):\s*$"
)
"""A Google-style section header, at column zero once the docstring is dedented."""

ARGS_SECTIONS = ("Args", "Arguments")
NOTES_SECTIONS = ("Notes", "Note")
"""The section lever 2 moves the second and later paragraphs into, either spelling.

Both already ended the description, so collecting only one of them would drop the other's
text on the floor instead of moving it to the system prompt.
"""

ARG_ENTRY = re.compile(r"^(\w+)\s*:\s*(.*)$")

MAX_DESCRIPTION_LENGTH = 160
MAX_PARAMETER_DESCRIPTION_LENGTH = 90
"""The lever 2 caps, in characters, enforced by a test and never by truncation (T053).

These are the numbers `contracts/levers.md` measures its 23,834-byte / 30 percent row at,
so the cap the build enforces and the saving the ledger quotes are one number.
"""

SCHEMA_MAP_KEYWORDS = ("properties", "$defs", "definitions", "patternProperties")
"""Keywords whose value is a mapping of name to schema."""

SCHEMA_LIST_KEYWORDS = ("anyOf", "oneOf", "allOf", "prefixItems")
"""Keywords whose value is a list of schemas."""

SCHEMA_KEYWORDS = ("items", "not", "additionalProperties", "contains")
"""Keywords whose value is a single schema (or, for `additionalProperties`, a bool)."""

EXPRESSIBLE_KEYWORDS = ("type", "$ref", "enum", "const", "anyOf", "oneOf", "properties", "items")
"""What makes an `anyOf` branch a schema rather than a bare constraint."""


# --- docstrings -------------------------------------------------------------------


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str], str]:
    """`(description, {parameter: description}, notes)` from a Google-style docstring.

    The description is everything before the first section header, kept as written
    (paragraph breaks included). Each `Args:` entry is `name: text`, with continuation
    lines - indented further than the entry - joined onto it with a single space.

    The `Notes:` block comes back dedented to column zero rather than discarded, which is
    the whole of lever 2's split: the first paragraph stays on the tool and the rest moves
    under `Notes:` **in the same docstring**, so the text still lives in exactly one place.
    `ToolSpec.full_description` rejoins the two halves, and FR-039 pins that rejoin
    byte-equal to the pre-split docstring body.
    """
    text = inspect.cleandoc(doc or "")
    body: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        header = SECTION_HEADER.match(line)
        if header is not None:
            current = header.group(1)
            sections.setdefault(current, [])
            continue
        if current is None:
            body.append(line)
        else:
            sections[current].append(line)
    return (
        "\n".join(body).strip(),
        _parse_args_block(_section_lines(sections, ARGS_SECTIONS)),
        _dedent_block(_section_lines(sections, NOTES_SECTIONS)),
    )


def _section_lines(sections: dict[str, list[str]], names: Sequence[str]) -> list[str]:
    """The lines of every section spelled one of `names`, in the order `names` gives."""
    block: list[str] = []
    for name in names:
        block.extend(sections.get(name, []))
    return block


def _base_indent(lines: list[str]) -> int:
    """The indent a section block sits at: the least of its non-blank lines."""
    return min(len(line) - len(line.lstrip()) for line in lines)


def _dedent_block(block: list[str]) -> str:
    """A section block moved back to column zero, with its blank lines kept.

    Indentation *below* the block's own base survives, because a code sample or a nested
    list inside a `Notes:` block is part of the text the rejoin has to reproduce.
    """
    lines = [line for line in block if line.strip()]
    if not lines:
        return ""
    base = _base_indent(lines)
    return "\n".join(line[base:] if line.strip() else "" for line in block).strip()


def _parse_args_block(block: list[str]) -> dict[str, str]:
    """The `name: description` entries of an `Args:` block, continuations folded in."""
    lines = [line for line in block if line.strip()]
    if not lines:
        return {}
    base = _base_indent(lines)
    entries: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        indent = len(line) - len(line.lstrip())
        entry = ARG_ENTRY.match(line.strip())
        if indent == base and entry is not None:
            current = entry.group(1)
            entries[current] = [entry.group(2).strip()]
        elif current is not None:
            entries[current].append(line.strip())
        else:
            raise ValueError(f"Args: block starts with a continuation line: {line!r}")
    return {name: " ".join(parts).strip() for name, parts in entries.items()}


# --- canonical ---------------------------------------------------------------------


def canonical_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """The provider-neutral JSON Schema for one tool function's arguments.

    `type: object`, one property per parameter with its docstring description, `required`
    listing the parameters that have no default, and no `$defs` or `$ref` left anywhere.

    Raises `ValueError` when the docstring describes a parameter the function does not
    have, or leaves one of its parameters undescribed.
    """
    schema = TypeAdapter(fn).json_schema(ref_template=REF_TEMPLATE)
    definitions = schema.pop("$defs", {})
    schema = _inline(schema, definitions, ())
    schema.setdefault("type", "object")
    properties: dict[str, Any] = schema.setdefault("properties", {})
    schema.setdefault("required", [])

    _, descriptions, _ = parse_docstring(fn.__doc__)
    undocumented = [name for name in properties if name not in descriptions]
    if undocumented:
        raise ValueError(
            f"{fn.__name__} has undocumented parameter(s) {undocumented}: every tool "
            "parameter needs an Args: entry, which is what the model reads"
        )
    unknown = [name for name in descriptions if name not in properties]
    if unknown:
        raise ValueError(f"{fn.__name__} documents parameter(s) {unknown} it does not take")
    for name, description in descriptions.items():
        properties[name]["description"] = description
    return schema


def _inline(node: Any, definitions: dict[str, Any], seen: tuple[str, ...]) -> Any:
    """`node` with every `$ref` replaced by the definition it names.

    Keys that sit beside a `$ref` win over the definition's own, which is how a
    `description` on the reference survives inlining. A definition that refers to itself
    raises rather than recursing forever.
    """
    if isinstance(node, list):
        return [_inline(item, definitions, seen) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if ref is None:
        return {key: _inline(value, definitions, seen) for key, value in node.items()}
    name = _definition_name(ref)
    if name in seen:
        raise ValueError(f"recursive schema definition {name!r}: {' -> '.join((*seen, name))}")
    if name not in definitions:
        raise ValueError(f"$ref {ref!r} names no definition; have {sorted(definitions)}")
    target = _inline(definitions[name], definitions, (*seen, name))
    beside = {
        key: _inline(value, definitions, seen) for key, value in node.items() if key != "$ref"
    }
    return {**target, **beside}


def _definition_name(ref: str) -> str:
    if not ref.startswith(REF_PREFIX):
        raise ValueError(f"unexpected $ref {ref!r}; expected one under {REF_PREFIX!r}")
    return ref[len(REF_PREFIX) :]


# --- OpenAI strict mode -------------------------------------------------------------


def strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """A copy of `schema` in the form OpenAI's `strict: true` requires.

    Children are rewritten before their parent, so a nullable object parameter is already
    closed by the time its union is folded into `{"type": ["object", "null"], ...}`.
    """
    return _strict_node(copy.deepcopy(schema), top=True)


def _strict_node(node: Any, *, top: bool = False) -> Any:
    if isinstance(node, list):
        return [_strict_node(item) for item in node]
    if not isinstance(node, dict):
        return node

    result = dict(node)
    for keyword in SCHEMA_MAP_KEYWORDS:
        value = result.get(keyword)
        if isinstance(value, dict):
            result[keyword] = {name: _strict_node(item) for name, item in value.items()}
    for keyword in SCHEMA_LIST_KEYWORDS:
        value = result.get(keyword)
        if isinstance(value, list):
            result[keyword] = [_strict_node(item) for item in value]
    for keyword in SCHEMA_KEYWORDS:
        value = result.get(keyword)
        if isinstance(value, dict):
            result[keyword] = _strict_node(value)

    result = _fold_nullable_union(result)
    result = _drop_constraint_only_branches(result)
    if "default" in result and result["default"] is None:
        del result["default"]
    if "object" in _declared_types(result):
        properties = result.get("properties")
        if top and isinstance(properties, dict):
            mandatory = result.get("required", [])
            result["properties"] = {
                name: item if name in mandatory else _make_nullable(name, item)
                for name, item in properties.items()
            }
        result["additionalProperties"] = False
        result["required"] = list(result.get("properties", {}))
    return result


def _make_nullable(name: str, node: Any) -> Any:
    """`node` with `null` admitted, which is how strict mode says "optional".

    Every property has to be in `required`, so the only way left to say a parameter may be
    left out is to let it be null. `parent_id: str | None` is already nullable; a default
    that is not null - `include_suppressed: bool = True` - is not, and gets `null` added
    here. The caller side of that bargain belongs to `tools/registry.py`: a null for a
    parameter whose annotation does not admit one means "use the default", so
    `RecordedTool` drops it before validating.

    Which is exactly why this applies to top-level parameters only. `_prepared` strips
    nulls from the arguments object and no deeper, so a null invented for a nested field
    reaches `pydantic.validate_call` as a real `None` and fails. A nested defaulted field
    stays plainly required instead.
    """
    if not isinstance(node, dict):
        return node
    types = _declared_types(node)
    if "null" in types:
        return node
    if types:
        return {**node, "type": [*types, "null"]}
    branches = node.get("anyOf")
    if isinstance(branches, list):
        return {**node, "anyOf": [*branches, {"type": "null"}]}
    raise ValueError(
        f"optional property {name!r} declares no type and no anyOf, so strict mode has no "
        "way to say it may be left out"
    )


def _declared_types(node: dict[str, Any]) -> tuple[str, ...]:
    declared = node.get("type")
    if isinstance(declared, list):
        return tuple(item for item in declared if isinstance(item, str))
    return (declared,) if isinstance(declared, str) else ()


def _fold_nullable_union(node: dict[str, Any]) -> dict[str, Any]:
    """`anyOf: [T, null]` folded into `{"type": ["T", "null"], ...T}`.

    Left alone when the union is anything else - two real types, say - because strict mode
    supports `anyOf` and only the nullable case has a shorter form.
    """
    branches = node.get("anyOf")
    if not isinstance(branches, list) or len(branches) != 2:
        return node
    nulls = [item for item in branches if _declared_types(item) == ("null",)]
    others = [item for item in branches if _declared_types(item) != ("null",)]
    if len(nulls) != 1 or len(others) != 1:
        return node
    other = others[0]
    if not isinstance(other, dict) or len(_declared_types(other)) != 1:
        return node
    folded = {key: value for key, value in node.items() if key != "anyOf"}
    for key, value in other.items():
        if key != "type":
            folded.setdefault(key, value)
    folded["type"] = [_declared_types(other)[0], "null"]
    return folded


def _drop_constraint_only_branches(node: dict[str, Any]) -> dict[str, Any]:
    """Remove `anyOf` branches that state a constraint without being a schema.

    Pydantic emits `{"required": ["sheet"]}` and friends for `SourceRef`'s "at least one
    locator" rule. OpenAI requires every branch to be a valid schema in its supported
    subset, and once strict mode has put every property in `required` the branches are
    vacuous anyway. The rule itself still runs: it is a pydantic model validator.
    """
    branches = node.get("anyOf")
    if not isinstance(branches, list):
        return node
    kept = [item for item in branches if _is_expressible(item)]
    if len(kept) == len(branches):
        return node
    result = dict(node)
    if kept:
        result["anyOf"] = kept
    else:
        del result["anyOf"]
    return result


def _is_expressible(branch: Any) -> bool:
    return isinstance(branch, dict) and any(key in branch for key in EXPRESSIBLE_KEYWORDS)


# --- Gemini --------------------------------------------------------------------------


def gemini_adapt(schema: dict[str, Any]) -> dict[str, Any]:
    """A copy of `schema` for `FunctionDeclaration(parameters_json_schema=...)`.

    `additionalProperties` and `$defs` come out; everything else - `required`, enums and
    the nullable `anyOf` unions - goes across as standard JSON Schema.
    """
    return _gemini_node(copy.deepcopy(schema))


def _gemini_node(node: Any) -> Any:
    if isinstance(node, list):
        return [_gemini_node(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {
        key: value for key, value in node.items() if key not in ("additionalProperties", "$defs")
    }
    for keyword in SCHEMA_MAP_KEYWORDS:
        value = result.get(keyword)
        if isinstance(value, dict):
            result[keyword] = {name: _gemini_node(item) for name, item in value.items()}
    for keyword in SCHEMA_LIST_KEYWORDS:
        value = result.get(keyword)
        if isinstance(value, list):
            result[keyword] = [_gemini_node(item) for item in value]
    for keyword in SCHEMA_KEYWORDS:
        value = result.get(keyword)
        if isinstance(value, dict):
            result[keyword] = _gemini_node(value)
    return result


# --- the tool spec -------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One tool as every provider sees it: name, description, canonical schema, function.

    Built once per tool by `tool_spec` and wrapped by `tools/registry.py`'s `RecordedTool`,
    which is what actually validates, records and calls.

    `description` is the docstring's first section - after lever 2's split, its first
    paragraph - and `notes` is its `Notes:` block, the half that belongs in the system
    prompt rather than on every tool object of every request. Which of the two strings
    reaches a provider is the `trim_tool_descriptions` flag's decision, and it is taken
    **after** `spec_for`, because `_SPECS` is process-global and a flag read while
    building the spec would let one run's setting leak into the next one in the process.
    """

    name: str
    description: str
    notes: str
    schema: dict[str, Any]
    fn: Callable[..., Any]

    @property
    def full_description(self) -> str:
        """Both halves rejoined: the string the flag-off path sends (FR-039).

        One blank line between them and nothing appended when there are no notes, which
        is what keeps this byte-equal to the pre-split docstring body.
        """
        return f"{self.description}\n\n{self.notes}" if self.notes else self.description

    def wire_description(self, *, trim: bool) -> str:
        """Which half of the docstring an arm of lever 2 puts on a tool object.

        The one place the flag's meaning is written down: `tools/registry.py`'s
        `RecordedTool.description` calls it for a run, and the payload measurement calls
        it for a table, so a measured arm and a sent arm cannot drift apart. *Where* the
        flag is read is the registry's business, and deliberately not this module's:
        `spec_for` caches by function across runs (`registry.py`).
        """
        return self.description if trim else self.full_description


def tool_spec(fn: Callable[..., Any]) -> ToolSpec:
    """The `ToolSpec` for one tool function.

    Raises `ValueError` when the function name is not a legal tool name (`[a-z0-9_]`, at
    most 60 characters) or when its docstring has no description above the `Args:` block.
    """
    name = fn.__name__
    if TOOL_NAME.fullmatch(name) is None:
        raise ValueError(
            f"tool name {name!r} is not a legal tool name: at most {MAX_NAME_LENGTH} "
            "characters of [a-z0-9_]"
        )
    description, _, notes = parse_docstring(fn.__doc__)
    if not description:
        raise ValueError(f"tool {name!r} has no description: the docstring is what the model reads")
    return ToolSpec(
        name=name,
        description=description,
        notes=notes,
        schema=canonical_schema(fn),
        fn=fn,
    )


def cap_violations(spec: ToolSpec) -> list[str]:
    """Every description on this tool that is over the lever 2 cap, one message each.

    Characters, not bytes, and the caps are inclusive. The cap is enforced from a test and
    never at run time on purpose: truncating a description mid-sentence produces "...and
    never used as o", and the model reads the fragment as a complete sentence. A docstring
    that cannot be split under the cap without rewording is a **named lever 2 exception
    recorded in the ledger row**, not a silent rewrite.

    Every offender is listed rather than the first, because a build that fails one
    docstring at a time is a build nobody finishes fixing.
    """
    messages: list[str] = []
    if len(spec.description) > MAX_DESCRIPTION_LENGTH:
        messages.append(
            f"{spec.name}: description is {len(spec.description)} characters, over the "
            f"{MAX_DESCRIPTION_LENGTH}-character cap"
        )
    for parameter, schema in spec.schema.get("properties", {}).items():
        text = schema.get("description", "")
        if len(text) > MAX_PARAMETER_DESCRIPTION_LENGTH:
            messages.append(
                f"{spec.name}.{parameter}: description is {len(text)} characters, over the "
                f"{MAX_PARAMETER_DESCRIPTION_LENGTH}-character cap"
            )
    return messages
