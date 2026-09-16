"""Unit tests for `agent/providers/schema.py` (T006).

Three schema forms are under test, one per consumer:

- `canonical_schema(fn)` - the provider-neutral form built from the signature and the
  Google-style docstring, with every `$def` inlined so no consumer has to resolve refs;
- `strictify(schema)` - the OpenAI strict-mode form: `additionalProperties: false` on
  every object, every property in `required`, optionals as `["T", "null"]`, no `$defs`;
- `gemini_adapt(schema)` - the `FunctionDeclaration.parameters_json_schema` form:
  `additionalProperties` and `$defs` gone, nullable unions kept.

Two of the assertions here are the direct consequence of T005a and are the reason this
test exists at all: a strictified schema may contain **no object with
`additionalProperties: true`** and **no nested object with zero properties**. Both are
unrepresentable in OpenAI strict mode, and a zero-property object with
`additionalProperties: false` accepts nothing at all - which is how a free-form
`dict[str, Any]` parameter silently loses every key the model sent.

Tool enumeration: `swreview.tools.registry` is the source of truth. `TOOL_FUNCTIONS` and
`BRIDGE_TOOL_FUNCTIONS` are imported at module scope, so a registry that stops importing
is a collection error here rather than a green run against a stale hand-copied list. The
contract-table golden below is what keeps the registrations themselves honest.

The last section is the round trip that keeps `strictify` and `tools/registry.py` from
drifting apart. `strictify` may only introduce `null` where `RecordedTool._prepared` can
take it back out again - that is, on a **top-level** parameter, because `_prepared` strips
nulls from the arguments object and nowhere deeper. A nested field that is defaulted but
not `| None` therefore stays plainly required: that is what the OpenAI SDK's own
`_ensure_strict_json_schema` does, and pydantic accepts it.
"""

from __future__ import annotations

import copy
import inspect
import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from swreview.agent.providers.schema import (
    ToolSpec,
    canonical_schema,
    gemini_adapt,
    strictify,
    tool_spec,
)
from swreview.ir.models import EvidencePackage
from swreview.tools import checks_fastener, checks_fit, query, registry, session
from swreview.tools.context import ToolContext, context_for
from swreview.tools.registry import RecordedTool, ToolRegistry, _admits_null
from tests.support.contracts import CONTRACTS_DIR

MakePackage = Callable[..., EvidencePackage]

# --- tool enumeration -------------------------------------------------------------

TOOL_FUNCTIONS = registry.TOOL_FUNCTIONS
BRIDGE_TOOL_FUNCTIONS = registry.BRIDGE_TOOL_FUNCTIONS
ALL_TOOL_FUNCTIONS: tuple[Callable[..., Any], ...] = (*TOOL_FUNCTIONS, *BRIDGE_TOOL_FUNCTIONS)

NO_ARGUMENT_TOOLS: frozenset[str] = frozenset(
    {"get_package_summary", "list_gaps", "get_review_checklist", "check_rms_assembly"}
)
"""The four tools the contract gives no arguments at all. Their parameters object is
legitimately empty: "accepts nothing" is exactly right for a tool that takes nothing, and
it is the one place a zero-property object is allowed."""


def tool_ids(functions: tuple[Callable[..., Any], ...]) -> list[str]:
    return [function.__name__ for function in functions]


# --- schema walking ---------------------------------------------------------------


def subschemas(node: Any, path: str = "$") -> Iterator[tuple[str, dict[str, Any]]]:
    """Every dict node in a schema, with a readable path, parents before children."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from subschemas(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from subschemas(value, f"{path}[{index}]")


def object_subschemas(schema: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every node that declares itself an object, including `["object", "null"]` ones."""
    for path, node in subschemas(schema):
        declared = node.get("type")
        types = declared if isinstance(declared, list) else [declared]
        if "object" in types:
            yield path, node


# --- the feature 001 contract table (the golden) ----------------------------------

AGENT_TOOLS = CONTRACTS_DIR / "agent-tools.md"
BRIDGE_HEADING = "## Live SolidWorks bridge tools (optional, workstation only)"
TOOL_NAME = re.compile(r"^`([a-z0-9_]+)`$")
CODE_SPAN = re.compile(r"`([^`]+)`")


def contract_tables() -> dict[str, dict[str, tuple[str, ...]]]:
    """`{heading: {tool name: parameter names}}` read out of `contracts/agent-tools.md`.

    Every tool row spells each argument in its own code span (`` `component_id: str` ``),
    so the parameter names are recoverable exactly; `none` means no arguments.
    """
    tables: dict[str, dict[str, tuple[str, ...]]] = {}
    heading = ""
    for line in AGENT_TOOLS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            heading = line.strip()
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) < 2:
            continue
        name = TOOL_NAME.match(cells[0])
        if name is None:
            continue
        arguments = cells[1]
        parameters = (
            ()
            if arguments == "none"
            else tuple(span.split(":", 1)[0].strip() for span in CODE_SPAN.findall(arguments))
        )
        tables.setdefault(heading, {})[name.group(1)] = parameters
    return tables


CONTRACT_TABLES = contract_tables()
CONTRACT_BRIDGE_TOOLS = CONTRACT_TABLES[BRIDGE_HEADING]
CONTRACT_CURATED_TOOLS = {
    name: parameters
    for heading, rows in CONTRACT_TABLES.items()
    if heading != BRIDGE_HEADING
    for name, parameters in rows.items()
}


def test_the_contract_tables_parse() -> None:
    """Guard the parser itself: a silently empty golden would assert nothing below."""
    assert len(CONTRACT_CURATED_TOOLS) == 32
    assert CONTRACT_CURATED_TOOLS["list_components"] == ("parent_id", "include_suppressed")
    assert CONTRACT_CURATED_TOOLS["get_package_summary"] == ()
    assert CONTRACT_BRIDGE_TOOLS["bridge_interference"] == (
        "component_ids",
        "configuration",
        "settings",
    )


def test_registered_tools_are_exactly_the_contract_tables() -> None:
    """The golden: every tool in the tables is registered and nothing else is.

    The curated tables and the registration groups do not line up one to one -
    `record_drawing_finding` sits in the "Check tools" table but in `session_tools()` -
    so the comparison is over the union of the non-bridge tables.
    """
    assert set(tool_ids(TOOL_FUNCTIONS)) == set(CONTRACT_CURATED_TOOLS)
    assert tool_ids(BRIDGE_TOOL_FUNCTIONS) == list(CONTRACT_BRIDGE_TOOLS)


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_canonical_schema_parameters_match_the_contract_table(
    function: Callable[..., Any],
) -> None:
    """Every tool's canonical schema carries exactly the arguments the contract lists."""
    contract = {**CONTRACT_CURATED_TOOLS, **CONTRACT_BRIDGE_TOOLS}
    schema = canonical_schema(function)
    assert tuple(schema["properties"]) == contract[function.__name__]


# --- canonical_schema -------------------------------------------------------------


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_canonical_schema_is_a_closed_object(function: Callable[..., Any]) -> None:
    schema = canonical_schema(function)
    assert schema["type"] == "object"
    assert isinstance(schema["properties"], dict)
    assert isinstance(schema["required"], list)


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_canonical_schema_required_is_the_parameters_without_defaults(
    function: Callable[..., Any],
) -> None:
    expected = [
        name
        for name, parameter in inspect.signature(function).parameters.items()
        if parameter.default is inspect.Parameter.empty
    ]
    assert canonical_schema(function)["required"] == expected


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_canonical_schema_inlines_every_definition(function: Callable[..., Any]) -> None:
    """No `$defs` and no `$ref` survives: every consumer reads one self-contained tree."""
    schema = canonical_schema(function)
    assert "$defs" not in schema
    assert [path for path, node in subschemas(schema) if "$ref" in node] == []


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_every_parameter_carries_its_docstring_description(
    function: Callable[..., Any],
) -> None:
    for name, property_schema in canonical_schema(function)["properties"].items():
        assert property_schema.get("description"), f"{function.__name__}.{name}"


def test_parameter_descriptions_are_the_docstring_text() -> None:
    """Spot-check against the source, including a description that wraps two lines."""
    properties = canonical_schema(session.mark_coverage)["properties"]
    assert properties["bucket"]["description"] == (
        "One of checked, skipped, unresolved, out_of_scope."
    )
    assert properties["scope"]["description"] == (
        "What it covered: component_ids, pairs (two ids each), configuration, positions, "
        "document_ids. State the ones the check actually covered."
    )


def test_source_ref_is_inlined_where_a_check_tool_takes_one() -> None:
    """`check_fit` takes two `SourceRef`s; both arrive as full objects, not refs."""
    properties = canonical_schema(checks_fit.check_fit)["properties"]
    bore = properties["bore_dimension_ref"]
    assert bore["type"] == "object"
    assert "document_id" in bore["properties"]
    assert bore["required"] == ["document_id"]
    assert bore["description"].startswith("Where the bore diameter is drawn")


def test_source_ref_is_inlined_inside_a_list_and_inside_a_nullable_union() -> None:
    refs = canonical_schema(session.record_drawing_finding)["properties"]["source_refs"]
    assert refs["type"] == "array"
    assert refs["items"]["type"] == "object"
    assert "annotation" in refs["items"]["properties"]

    tolerance = canonical_schema(checks_fastener.check_hole_alignment)["properties"]["tolerance"]
    branches = tolerance["anyOf"]
    assert [branch.get("type") for branch in branches] == ["object", "null"]
    assert "annotation" in branches[0]["properties"]


def test_canonical_schema_refuses_an_undocumented_parameter() -> None:
    def sample_tool(documented: str, undocumented: int) -> dict[str, Any]:
        """A tool whose docstring forgets one parameter.

        Args:
            documented: The one that is described.
        """
        return {}

    with pytest.raises(ValueError, match="undocumented"):
        canonical_schema(sample_tool)


# --- strictify --------------------------------------------------------------------


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_strictify_closes_every_object_and_requires_every_property(
    function: Callable[..., Any],
) -> None:
    schema = strictify(canonical_schema(function))
    for path, node in object_subschemas(schema):
        assert node.get("additionalProperties") is False, f"{function.__name__} {path}"
        assert node.get("required") == list(node.get("properties", {})), (
            f"{function.__name__} {path}"
        )


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_strictify_leaves_no_open_object(function: Callable[..., Any]) -> None:
    """T005a: `additionalProperties: true` has no strict-mode form at all."""
    for path, node in subschemas(strictify(canonical_schema(function))):
        assert node.get("additionalProperties") is not True, f"{function.__name__} {path}"


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_strictify_leaves_no_nested_object_without_properties(
    function: Callable[..., Any],
) -> None:
    """T005a: a closed object with no properties accepts nothing and reports nothing.

    The root parameters object of a no-argument tool is the single exempt case, and the
    next assertion pins exactly which tools that is.
    """
    schema = strictify(canonical_schema(function))
    for path, node in object_subschemas(schema):
        if path == "$":
            continue
        assert node.get("properties"), f"{function.__name__} {path}"


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_only_the_no_argument_tools_have_an_empty_parameters_object(
    function: Callable[..., Any],
) -> None:
    empty = not strictify(canonical_schema(function))["properties"]
    assert empty is (function.__name__ in NO_ARGUMENT_TOOLS)


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_strictify_has_no_defs_and_no_refs(function: Callable[..., Any]) -> None:
    schema = strictify(canonical_schema(function))
    assert "$defs" not in schema
    assert [path for path, node in subschemas(schema) if "$ref" in node] == []


def test_strictify_rewrites_optional_scalars_as_nullable_type_unions() -> None:
    properties = strictify(canonical_schema(query.list_components))["properties"]
    assert properties["parent_id"]["type"] == ["string", "null"]
    assert "anyOf" not in properties["parent_id"]
    # A default that is not None survives: it tells the model what to send.
    assert properties["include_suppressed"]["type"] == ["boolean", "null"]
    assert properties["include_suppressed"]["default"] is True


def test_strictify_makes_a_nested_defaulted_field_required_but_not_nullable() -> None:
    """`CoverageScope`'s four list fields default to empty but do not admit `null`.

    Strict mode says "you may leave this out" two ways: a nullable union, which only works
    when the annotation really takes `None`, and plain `required`, which is what the
    OpenAI SDK's own `_ensure_strict_json_schema` does for everything else. Only the first
    is reversible, and only at the top level, where `RecordedTool._prepared` strips the
    null again - so a nested `list[str]` field stays a plain required array and `[]` is
    how the model says "nothing here". `configuration` is genuinely `str | None` and keeps
    its null.
    """
    scope = strictify(canonical_schema(session.mark_coverage))["properties"]["scope"]
    assert scope["required"] == list(scope["properties"])
    for name in ("component_ids", "pairs", "positions", "document_ids"):
        assert scope["properties"][name]["type"] == "array", name
    assert scope["properties"]["configuration"]["type"] == ["string", "null"]


def test_strictify_rewrites_an_optional_object_parameter_as_a_nullable_object() -> None:
    tolerance = strictify(canonical_schema(checks_fastener.check_hole_alignment))["properties"][
        "tolerance"
    ]
    assert tolerance["type"] == ["object", "null"]
    assert "anyOf" not in tolerance
    assert tolerance["additionalProperties"] is False
    assert tolerance["required"] == list(tolerance["properties"])


def test_strictify_drops_null_defaults_and_keeps_the_nested_optionals_nullable() -> None:
    bore = strictify(canonical_schema(checks_fit.check_fit))["properties"]["bore_dimension_ref"]
    assert "default" not in bore["properties"]["sheet"]
    assert bore["properties"]["sheet"]["type"] == ["string", "null"]
    assert bore["properties"]["page"]["type"] == ["integer", "null"]
    assert bore["properties"]["bbox"]["type"] == ["array", "null"]


def test_strictify_drops_constraint_only_anyof_branches() -> None:
    """`SourceRef`'s "at least one locator" `anyOf` has no strict-mode form.

    Its branches are bare `{"required": [...]}` objects, and OpenAI requires every `anyOf`
    branch to be a valid schema in the supported subset. The rule is not lost: it is a
    pydantic model validator and still runs when the call is validated.
    """
    bore = strictify(canonical_schema(checks_fit.check_fit))["properties"]["bore_dimension_ref"]
    assert "anyOf" not in bore


def test_strictify_does_not_mutate_its_input() -> None:
    schema = canonical_schema(query.list_components)
    before = copy.deepcopy(schema)
    strictify(schema)
    assert schema == before


# --- gemini_adapt -----------------------------------------------------------------


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_gemini_adapt_removes_additional_properties_and_defs(
    function: Callable[..., Any],
) -> None:
    schema = gemini_adapt(canonical_schema(function))
    assert "$defs" not in schema
    for path, node in subschemas(schema):
        assert "additionalProperties" not in node, f"{function.__name__} {path}"
        assert "$ref" not in node, f"{function.__name__} {path}"


def test_gemini_adapt_keeps_nullable_unions_and_required() -> None:
    schema = gemini_adapt(canonical_schema(query.list_components))
    parent_id = schema["properties"]["parent_id"]
    assert [branch["type"] for branch in parent_id["anyOf"]] == ["string", "null"]
    assert schema["required"] == []

    fit = gemini_adapt(canonical_schema(checks_fit.check_fit))
    assert fit["required"] == ["bore_dimension_ref", "shaft_dimension_ref"]
    sheet = fit["properties"]["bore_dimension_ref"]["properties"]["sheet"]
    assert [branch["type"] for branch in sheet["anyOf"]] == ["string", "null"]


def test_gemini_adapt_does_not_mutate_its_input() -> None:
    schema = canonical_schema(checks_fit.check_fit)
    before = copy.deepcopy(schema)
    gemini_adapt(schema)
    assert schema == before


# --- tool_spec --------------------------------------------------------------------


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_tool_spec_names_and_schemas(function: Callable[..., Any]) -> None:
    spec = tool_spec(function)
    assert isinstance(spec, ToolSpec)
    assert spec.name == function.__name__
    assert re.fullmatch(r"[a-z0-9_]{1,60}", spec.name)
    assert spec.fn is function
    assert spec.schema == canonical_schema(function)


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_tool_spec_description_is_the_docstring_without_the_args_section(
    function: Callable[..., Any],
) -> None:
    spec = tool_spec(function)
    assert spec.description
    assert "Args:" not in spec.description
    summary = (function.__doc__ or "").strip().splitlines()[0]
    assert spec.description.startswith(summary)


def test_tool_spec_description_keeps_the_body_paragraphs() -> None:
    spec = tool_spec(query.get_component)
    assert spec.description == (
        "Everything the package holds about one component instance.\n\n"
        "Returns the instance itself plus the holes, fasteners, faces and mates that "
        "belong\nto it."
    )


def test_tool_spec_rejects_a_name_that_is_not_a_tool_name() -> None:
    def BadName() -> dict[str, Any]:  # noqa: N802 - the point of the test
        """A tool whose name is not `[a-z0-9_]`."""
        return {}

    with pytest.raises(ValueError, match="BadName"):
        tool_spec(BadName)


# --- the round trip: strictify and tools/registry.py must not drift ---------------


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_strictify_adds_null_only_where_the_registry_can_take_it_back_out(
    function: Callable[..., Any],
) -> None:
    """The invariant that ties the two halves together.

    `RecordedTool._prepared` drops nulls from the arguments object and nowhere deeper, so
    a null `strictify` invents below the top level has nobody to undo it and reaches
    `pydantic.validate_call` as a real `None`. Every nested property that admits null in
    the strict schema must therefore already admit it in the canonical one.
    """
    canonical = canonical_schema(function)
    strict = strictify(canonical)
    for path, node in object_subschemas(strict):
        if path == "$":
            continue
        original = _canonical_node_at(canonical, path)
        for name, property_schema in node.get("properties", {}).items():
            if _admits_null(property_schema):
                assert _admits_null(original["properties"][name]), (
                    f"{function.__name__} {path}.{name} is nullable only in the strict "
                    "schema, and _prepared strips nulls at the top level only"
                )


@pytest.mark.parametrize("function", ALL_TOOL_FUNCTIONS, ids=tool_ids(ALL_TOOL_FUNCTIONS))
def test_every_top_level_property_is_nullable_and_the_registry_undoes_it(
    function: Callable[..., Any],
) -> None:
    """The other half: at the top level every optional parameter *is* nullable.

    That is what lets the model leave a parameter out under strict mode at all, and
    `_prepared` is what turns the null back into "use the default".
    """
    canonical = canonical_schema(function)
    strict = strictify(canonical)
    mandatory = canonical["required"]
    for name, property_schema in strict["properties"].items():
        assert _admits_null(property_schema) is (name not in mandatory), (
            f"{function.__name__}.{name}"
        )


def _canonical_node_at(schema: dict[str, Any], path: str) -> dict[str, Any]:
    """The canonical node the strict node at `path` was derived from.

    `strictify` folds `anyOf: [T, null]` into `{"type": ["T", "null"], ...T}`, so a path
    through the strict tree is one `anyOf` hop shorter than the canonical one wherever an
    optional model parameter sits. `_unfold` puts that hop back.
    """
    node: Any = schema
    for step in path.split(".")[1:]:
        node = _unfold(node)
        if step.endswith("]"):
            key, _, index = step[:-1].partition("[")
            node = node[key][int(index)]
        else:
            node = node[step]
    return _unfold(node)


def _unfold(node: Any) -> Any:
    """The non-null branch of an `anyOf: [T, null]` union, or `node` unchanged."""
    branches = node.get("anyOf") if isinstance(node, dict) else None
    if not isinstance(branches, list) or len(branches) != 2:
        return node
    others = [branch for branch in branches if branch.get("type") != "null"]
    return others[0] if len(others) == 1 else node


def test_a_strict_mode_coverage_call_validates_through_the_registry(
    make_package: MakePackage,
) -> None:
    """Feed `mark_coverage` exactly what its strict schema demands; it must not be an error.

    This is the failure the invariant above prevents, spelled out end to end: a coverage
    call that names the components it covered and nothing else. Before the fix, the four
    `CoverageScope` list fields were `["array", "null"]`, `_prepared` left the nested
    nulls alone, and every such call was recorded as `failed` coverage instead of
    `checked` - silent loss of the record constitution VI requires.
    """
    context = context_for(make_package())
    tool = _tool_named(context, "mark_coverage")
    strict = strictify(tool.schema)
    scope_properties = strict["properties"]["scope"]["properties"]
    assert set(strict["properties"]["scope"]["required"]) == set(scope_properties)
    # Exactly what a model filling only the field it covered would send back.
    scope: dict[str, Any] = {
        name: None if _admits_null(property_schema) else []
        for name, property_schema in scope_properties.items()
    }
    scope["component_ids"] = ["cmp:0001"]
    arguments = {
        "check": "interference",
        "bucket": "checked",
        "scope": scope,
        "reason": "Swept the top-level instances.",
    }
    assert set(arguments) == set(strict["required"])

    result = tool.call(arguments, "call_1")

    assert result.is_error is False, result.payload
    assert [item.check for item in context.session.coverage.checked] == ["interference"]
    assert context.session.coverage.checked[0].scope.component_ids == ["cmp:0001"]
    assert context.session.coverage.failed == []


def _tool_named(context: ToolContext, name: str) -> RecordedTool:
    tools = {tool.name: tool for tool in ToolRegistry().build(context)}
    assert name in tools, f"{name} is not registered; known: {sorted(tools)}"
    return tools[name]
