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

2. **OpenAI or Gemini, and nothing else is reachable.** The remodel run reaches a provider
   through exactly one entry point, `remodel/runner.py::build_provider`, which refuses the
   scripted provider and hands every other name to `cli.provider_factory`, the one body that
   builds the review's and the pane's adapters too (contracts/tools.md "Providers",
   research.md R7, amended 2026-09-23 by the owner's decision 4A: the run's own copy of that
   body carried the original's wrong `redact=` keyword). Claude is not a provider in this
   product, and the registry is where that is decided: `ProviderName` has three members and
   `providers.get` raises `UnknownProviderError` for every other string, so there is no name
   a remodel run could be given that would reach one.

SC-009's runtime half - every `agent.providers` factory replaced by one that raises, and a
run with no judgement slots completing anyway - needs a run to execute and is T116's, beside
the `FakeProvider` scripts it shares a fixture with; what can be asserted without a run is
here.
"""

from __future__ import annotations

import ast
import inspect
import socket
from collections.abc import Callable
from pathlib import Path

import pytest

import swreview.agent
import swreview.cli
import swreview.remodel
from swreview.agent import providers
from swreview.agent.providers import AgentProvider, ProviderName, UnknownProviderError
from swreview.agent.providers.openai_provider import OpenAIProvider
from swreview.agent.settings import ProviderSettings
from swreview.remodel import runner

PROMPT_FILE = Path(swreview.agent.__file__).parent / "prompts" / "remodel_v1.md"

REMODEL_PACKAGE = Path(swreview.remodel.__file__).parent

KEY = "remodel-policy-test-key-not-real"

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


def runner_source() -> str:
    return (REMODEL_PACKAGE / "runner.py").read_text(encoding="utf-8")


def construction_sources() -> dict[str, str]:
    """Everything a remodel run's adapter is built by: its entry point and the one body."""
    return {
        "remodel/runner.py": runner_source(),
        "cli.provider_factory": inspect.getsource(swreview.cli.provider_factory),
    }


REMODEL_MODULE_PACKAGE = "swreview.remodel"
"""What a relative import in a scanned module is relative to: every module scanned here is
one of `remodel/`'s own (`construction_sources` scans the runner and the body by source, and
neither imports relatively)."""

FACTORY = "swreview.cli.provider_factory"
"""The one body that builds an adapter (owner decision 4A)."""

FACTORY_MODULES = ("swreview.cli", "swreview.chat.server")
"""The modules a way to an adapter lives in: the body itself, and the pane's entry point
`chat.server.build_provider`, which hands the body the pane's levers - lever 6 among them, which
a remodel run must never be built with."""

REGISTRY_GET = "swreview.agent.providers.get"
"""The registry's one door (`ADAPTER_MODULES` is what it consults; nothing else imports an
adapter module by name)."""


def _absolute(node: ast.ImportFrom) -> str:
    """The module a `from` import names, a relative one resolved against `remodel/`."""
    if node.level == 0:
        return node.module or ""
    parts = REMODEL_MODULE_PACKAGE.split(".")
    anchor = parts[: len(parts) - node.level + 1]
    return ".".join([*anchor, node.module] if node.module else anchor)


def _bindings(tree: ast.Module) -> dict[str, str]:
    """Every name an import in `tree` binds, at any depth, to the dotted name it stands for.

    `import a.b` binds `a` to `a`; `import a.b as c` binds `c` to `a.b`; `from a import b as c`
    binds `c` to `a.b`. Scopes are merged, which can only find more, never less.
    """
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    bound[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node)
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{base}.{alias.name}"
    return bound


def _dotted(node: ast.expr) -> str | None:
    """`a.b.c` for a chain of attributes on a name, else `None`."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def reached(source: str) -> set[str]:
    """Every dotted name `source` reaches: what each import names, and what each call names
    once its first name is resolved through the import that bound it.

    `swreview.cli` for `import swreview.cli` and for `from swreview import cli`;
    `swreview.cli.provider_factory` for `from ..cli import provider_factory` in a `remodel/`
    module and for `swreview.cli.provider_factory(...)` after `import swreview`.
    """
    tree = ast.parse(source)
    bound = _bindings(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node)
            names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            if dotted is None:
                continue
            head, _, rest = dotted.partition(".")
            if head in bound:
                names.add(f"{bound[head]}.{rest}" if rest else bound[head])
    return names


def _within(name: str, module: str) -> bool:
    return name == module or name.startswith(f"{module}.")


def reaches_the_factory(source: str) -> bool:
    """Does this module reach `cli.provider_factory` - imported at any depth, absolutely or
    relatively, or called through `swreview.cli` (`reached`)?

    At any depth because the one legitimate import is deferred into a function body: `cli`
    imports the `remodel` package, so a module-scope import would be circular.
    """
    return FACTORY in reached(source)


def reaches_a_factory_module(source: str) -> bool:
    """Does this module reach `swreview.cli` or `swreview.chat.server` in any form?

    Either puts an adapter in reach without naming the factory: `cli.provider_factory` after
    `from swreview import cli`, or the pane's `chat.server.build_provider`, which builds with
    the pane's levers. Imported absolutely or relatively, at any depth, or called through a
    parent package's attribute (`reached`).
    """
    return any(_within(name, module) for name in reached(source) for module in FACTORY_MODULES)


def constructs_a_provider(source: str) -> bool:
    """Does this module import or call the provider registry's `get`, however it bound it?

    `from ...providers import get`, and a call of `providers.get(...)`, a bare or aliased
    `get(...)` or the full dotted path, each resolved through the import that bound its first
    name - so a local called `providers`, or a dictionary's `get`, is not the registry.
    """
    return REGISTRY_GET in reached(source)


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


# --- 3. the one entry point and the one construction body -----------------------------------


def refuse_the_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("a unit test reached for the network")


def settings_for(provider: ProviderName | None = None) -> ProviderSettings:
    """What a remodel run is handed, resolved as `POST /remodel/runs` resolves it.

    `ProviderSettings.from_env` (contracts/backend-remodel.md), with a key typed into the
    settings and an empty environment, so nothing on the machine running the tests leaks in.
    `None` is a run that named no provider.
    """
    return ProviderSettings.from_env(provider=provider, api_key=KEY, env={})


def sites_other_than_the_runner(reaches: Callable[[str], bool]) -> list[str]:
    """Every `remodel/` module but `runner.py` whose source `reaches` a provider."""
    return sorted(
        path.name
        for path in REMODEL_PACKAGE.glob("*.py")
        if path.name != "runner.py" and reaches(path.read_text(encoding="utf-8"))
    )


class RecordingFactory:
    """Stands in for `cli.provider_factory`: keeps every call, builds nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.built = object()

    def __call__(self, *args: object, **kwargs: object) -> AgentProvider:
        self.calls.append((args, kwargs))
        return self.built  # type: ignore[return-value]


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> RecordingFactory:
    """`cli.provider_factory`, replaced where `runner.build_provider`'s deferred import reads it."""
    recording = RecordingFactory()
    monkeypatch.setattr(swreview.cli, "provider_factory", recording)
    return recording


@pytest.mark.parametrize(
    ("source", "factory", "factory_module"),
    [
        ("from swreview.cli import provider_factory", True, True),
        ("def build():\n    from swreview.cli import provider_factory\n", True, True),
        ("from swreview.cli import app", False, True),
        ("import swreview.cli", False, True),
        ("from swreview import cli", False, True),
        ("from swreview import remodel", False, False),
        ("from swreview.remodel.plan import plan_path", False, False),
        ("def run(provider_factory=None):\n    return provider_factory\n", False, False),
        ("from ..cli import provider_factory", True, True),
        ("from .. import cli", False, True),
        ("from swreview.chat.server import build_provider", False, True),
        ("def build():\n    from swreview.chat.server import build_provider\n", False, True),
        ("from swreview.chat import server", False, True),
        ("import swreview.chat.server", False, True),
        ("from ..chat.server import build_provider", False, True),
        ("from ..chat import server", False, True),
        ("import swreview\nswreview.cli.provider_factory(settings)\n", True, True),
        ("from . import plan", False, False),
        ("from .plan import plan_path", False, False),
        ("from swreview import chat", False, False),
    ],
)
def test_the_import_detectors_see_every_way_to_the_factory(
    source: str, factory: bool, factory_module: bool
) -> None:
    """A `sites == []` assertion is only as strong as the detector behind it: the deferred
    import counts, and a parameter that happens to be called `provider_factory` does not."""
    assert reaches_the_factory(source) is factory
    assert reaches_a_factory_module(source) is factory_module


@pytest.mark.parametrize(
    ("source", "constructs"),
    [
        ("from swreview.agent import providers\nproviders.get(name)\n", True),
        ("from swreview.agent.providers import get\nget(name)\n", True),
        ("def build():\n    from swreview.agent.providers import get\n    get(name)\n", True),
        ("from swreview.agent.providers import get as fetch\nfetch(name)\n", True),
        ("import swreview.agent.providers as registry\nregistry.get(name)\n", True),
        ("import swreview.agent.providers\nswreview.agent.providers.get(name)\n", True),
        ("from ..agent import providers\nproviders.get(name)\n", True),
        ("from ..agent.providers import get\nget(name)\n", True),
        ("from swreview.agent import providers\nproviders.ProviderName('openai')\n", False),
        ("from swreview.agent.providers import ProviderName\nProviderName('openai')\n", False),
        ("settings = {}\nsettings.get('provider')\n", False),
        ("providers = {}\nproviders.get('openai')\n", False),
    ],
)
def test_the_registry_detector_sees_every_way_to_providers_get(
    source: str, constructs: bool
) -> None:
    """The same rule for the registry: the call is resolved through the import that bound
    its name - aliased, deferred or relative - and a local that happens to be called
    `providers` or a dictionary's `get` is not the registry."""
    assert constructs_a_provider(source) is constructs


def test_no_apply_phase_module_constructs_a_provider() -> None:
    """SC-009's static half: the deterministic phases have no model in them at all.

    Asserted over the modules that exist today - the planner, the executor, the change
    log, the replay, the gate and the report - and it keeps holding beside the runner,
    which is the one module allowed to reach one, through `cli.provider_factory`.
    """
    sites = sites_other_than_the_runner(constructs_a_provider)
    assert sites == [], (
        f"a provider is constructed in {sites}; contracts/tools.md puts that in "
        "remodel/runner.py and nowhere else"
    )


def test_the_remodel_runner_is_the_one_entry_point() -> None:
    """`runner.build_provider` is the remodel run's one way to an adapter, and builds none.

    Owner decision 4A (2026-09-23, contracts/tools.md "Providers"): the runner delegates to
    `cli.provider_factory`, the one body that builds the review's and the pane's adapters
    too. So `runner.py` imports the factory and does not also reach the registry itself -
    that would be the second construction body the decision removed, the one that carried
    the original's wrong `redact=` keyword - and no other `remodel/` module reaches either.
    Neither directly nor through the pane's `chat.server.build_provider`, whose levers a remodel
    run must not be built with. That the import is used, and how, is asserted by behaviour in
    the next two tests.
    """
    source = runner_source()
    assert reaches_the_factory(source), (
        "remodel/runner.py must hand construction to cli.provider_factory, the one body"
    )
    assert not constructs_a_provider(source), (
        "remodel/runner.py reaches the provider registry itself: that is a second "
        "construction body beside cli.provider_factory, which decision 4A removed"
    )
    sites = sites_other_than_the_runner(
        lambda text: constructs_a_provider(text) or reaches_a_factory_module(text)
    )
    assert sites == [], (
        f"{sites} reach a provider; remodel/runner.py::build_provider is the remodel run's "
        "one entry point (contracts/tools.md)"
    )


@pytest.mark.parametrize("provider", [ProviderName.OPENAI, ProviderName.GEMINI])
def test_the_runner_hands_its_settings_and_nothing_else_to_the_one_body(
    provider: ProviderName, factory: RecordingFactory
) -> None:
    """The settings go through untouched and what the factory built comes back.

    No efficiency argument: a remodel run passes no levers, so every lever stays off, as it
    did before decision 4A. Lever 6 in particular is the pane's (feature 008).
    """
    settings = settings_for(provider)

    built = runner.build_provider(settings)

    assert built is factory.built
    assert factory.calls == [((settings,), {})]


def test_the_runner_refuses_the_scripted_provider_before_the_body_is_reached(
    factory: RecordingFactory,
) -> None:
    """The refusal is the remodel run's own decision; the factory would play the review's
    script, which belongs to the review, so it must never be asked."""
    with pytest.raises(ValueError, match="script"):
        runner.build_provider(settings_for(ProviderName.FAKE))

    assert factory.calls == []


def test_the_construction_site_defaults_to_openai_and_names_no_retired_vendor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that named no provider gets an OpenAI adapter, built for real through the runner
    and the body behind it: the client is constructed, nothing is sent. It is built with
    lever 6 off, as a remodel run's always was. Neither the entry point nor the body names a
    retired vendor."""
    monkeypatch.setattr(socket.socket, "connect", refuse_the_network)

    built = runner.build_provider(settings_for())

    assert isinstance(built, OpenAIProvider), "OpenAI is the default provider for a remodel run"
    assert built.parallel_tool_calls is False
    for where, source in construction_sources().items():
        lowered = source.lower()
        for retired in RETIRED:
            assert retired not in lowered, f"{where} names {retired!r}"
