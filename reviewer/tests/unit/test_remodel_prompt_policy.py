"""The judgement phase's prompt and its provider policy (T118).

Two commitments are pinned here, and neither is enforceable by the prompt alone:

1. **The model proposes and nothing else.** `agent/prompts/remodel_v1.md` loads and says,
   in words an engineer reading the prompt can check, that the model proposes intent into
   the plan and never decides an order, never moves a feature, never rolls anything back
   and never issues a verdict (spec.md US3, FR-017, contracts/tools.md "What these tools
   are for"). The *binding* version of that rule is the tool list - nothing on it can do
   any of those four things, which is what `test_tools_remodel_plan.py` and
   `test_remodel_runner.py` assert - so this file checks the prompt agrees with the tools
   rather than pretending the prompt is the control.

2. **OpenAI or Gemini, and nothing else is reachable.** The remodel run constructs a
   provider in exactly one place, `remodel/runner.py`, through the existing
   `agent/providers` layer (contracts/tools.md "Providers", research.md R7). Claude is not
   a provider in this product, and the registry is where that is decided: `ProviderName`
   has three members and `providers.get` raises `UnknownProviderError` for every other
   string, so there is no name a remodel run could be given that would reach one.

`remodel/runner.py` is written by T117 in Stage 2. The cases that need it **skip with a
reason that names the task** rather than being left out, so the policy arrives with the
module instead of after it. SC-009's runtime half - every `agent.providers` factory
replaced by one that raises, and a run with no judgement slots completing anyway - needs a
run to execute and is T116's, beside the `FakeProvider` scripts it shares a fixture with;
what can be asserted without a run is here, statically, and holds today.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import swreview.agent
import swreview.remodel
from swreview.agent import providers
from swreview.agent.providers import ProviderName, UnknownProviderError

PROMPT_FILE = Path(swreview.agent.__file__).parent / "prompts" / "remodel_v1.md"

REMODEL_PACKAGE = Path(swreview.remodel.__file__).parent

RUNNER_MODULE = "swreview.remodel.runner"

PROPOSAL_TOOLS = (
    "propose_description",
    "propose_global",
    "decide_fillet",
    "classify_unknown",
    "get_remodel_plan",
)
"""Every tool the judgement phase has (contracts/tools.md). The prompt names all five."""

PROHIBITIONS = (
    "never decide the order",
    "never move a feature",
    "never roll anything back",
    "never issue a verdict",
)
"""The four things the model must be told it does not do, in the spec's own vocabulary."""

RETIRED = ("claude", "anthropic")
"""Not a provider in this product. Absent from the prompt as well as from the registry."""


def runner_source() -> str | None:
    """`remodel/runner.py`'s source, or `None` while T117 has not written it yet."""
    path = REMODEL_PACKAGE / "runner.py"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def requires_runner() -> str:
    return (
        f"{RUNNER_MODULE} does not exist yet: T117 (Stage 2) writes the remodel run's "
        "phases A to D and with them the one provider construction site this asserts on"
    )


def constructs_a_provider(source: str) -> bool:
    """Does this module reach into the provider registry to build an adapter?

    `providers.get(...)` and a bare `get(...)` imported from the provider package are the
    only two ways in, because `ADAPTER_MODULES` is what `get` consults and nothing else
    imports an adapter module by name.
    """
    tree = ast.parse(source)
    imported_get = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "swreview.agent.providers"
        and any(alias.name == "get" for alias in node.names)
        for node in ast.walk(tree)
    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get":
            value = func.value
            if isinstance(value, ast.Name) and value.id == "providers":
                return True
        if imported_get and isinstance(func, ast.Name) and func.id == "get":
            return True
    return False


# --- 1. the prompt ----------------------------------------------------------------------


def test_the_remodel_prompt_loads() -> None:
    assert PROMPT_FILE.is_file(), f"{PROMPT_FILE} is missing"
    assert PROMPT_FILE.read_text(encoding="utf-8").strip(), "the remodel prompt is empty"


def test_the_prompt_says_the_model_proposes() -> None:
    text = PROMPT_FILE.read_text(encoding="utf-8").lower()
    assert "propose" in text
    assert "plan" in text


@pytest.mark.parametrize("prohibition", PROHIBITIONS)
def test_the_prompt_states_each_prohibition(prohibition: str) -> None:
    """Order, move, rollback, verdict: the four decisions that are not the model's."""
    assert prohibition in PROMPT_FILE.read_text(encoding="utf-8").lower()


def test_the_prompt_says_it_never_reaches_solidworks() -> None:
    """No tool names a document and none can cause a write (contracts/tools.md)."""
    text = PROMPT_FILE.read_text(encoding="utf-8").lower()
    assert "solidworks" in text
    assert "no tool" in text or "none of your tools" in text


@pytest.mark.parametrize("tool", PROPOSAL_TOOLS)
def test_the_prompt_names_every_tool_the_phase_has(tool: str) -> None:
    assert tool in PROMPT_FILE.read_text(encoding="utf-8")


def test_the_prompt_says_a_rejection_is_not_the_end_of_the_run() -> None:
    """A rejected proposal comes back as an error the model may correct (spec.md US3)."""
    assert "reject" in PROMPT_FILE.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("retired", RETIRED)
def test_the_prompt_names_no_retired_vendor(retired: str) -> None:
    """The prompt is provider-neutral; it is sent to OpenAI or to Gemini unchanged."""
    assert retired not in PROMPT_FILE.read_text(encoding="utf-8").lower()


# --- 2. the provider policy -------------------------------------------------------------


def test_openai_and_gemini_are_the_only_real_providers() -> None:
    """`fake` is the third member and is the offline test double, not a vendor."""
    assert {member.value for member in ProviderName} == {"openai", "gemini", "fake"}


@pytest.mark.parametrize("retired", ["claude", "anthropic", "Claude", "claude-opus-5"])
def test_no_claude_provider_is_reachable_through_the_registry(retired: str) -> None:
    with pytest.raises(UnknownProviderError):
        providers.get(retired)


def test_no_adapter_module_is_a_claude_adapter() -> None:
    modules = " ".join(providers.ADAPTER_MODULES.values()).lower()
    for retired in RETIRED:
        assert retired not in modules


# --- 3. the single construction site ----------------------------------------------------


def test_no_apply_phase_module_constructs_a_provider() -> None:
    """SC-009's static half: the deterministic phases have no model in them at all.

    Asserted over the modules that exist today - the planner, the executor, the change
    log, the replay, the gate and the report - and it keeps holding as T117 adds the
    runner beside them, which is the one module allowed to construct one.
    """
    sites = sorted(
        path.name
        for path in REMODEL_PACKAGE.glob("*.py")
        if path.name != "runner.py" and constructs_a_provider(path.read_text(encoding="utf-8"))
    )
    assert sites == [], (
        f"a provider is constructed in {sites}; contracts/tools.md puts that in "
        "remodel/runner.py and nowhere else"
    )


def test_the_remodel_runner_is_the_one_construction_site() -> None:
    source = runner_source()
    if source is None:
        pytest.skip(requires_runner())
    assert constructs_a_provider(source), (
        "remodel/runner.py is the only place a remodel run may construct a provider, "
        "so it is also the only place that can"
    )


def test_the_construction_site_defaults_to_openai_and_names_no_retired_vendor() -> None:
    source = runner_source()
    if source is None:
        pytest.skip(requires_runner())
    lowered = source.lower()
    assert "openai" in lowered, "OpenAI is the default provider for a remodel run"
    for retired in RETIRED:
        assert retired not in lowered
