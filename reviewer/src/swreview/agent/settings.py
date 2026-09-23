"""Which provider runs a turn, with what model and key, and how secrets stay out of text.

This module is the single place four decisions are made, so no other module has to make
them badly:

**The default model, per provider (FR-026).** Feature 001 kept `DEFAULT_MODEL` next to the
tool context, which meant a run started without `--model` wrote the id of a model this
product no longer supports into `session.json`. There is no module-level default model
anywhere else now; `DEFAULT_MODELS` here is it, and `ProviderSettings` itself refuses to be
built without a model so nothing can drift back to an implicit one.

**Where the key came from (FR-015).** The pane's `settings.json` wins over the process
environment, and the answer is recorded as `key_source` on the session, because a run that
cannot say which credential it used cannot be reproduced or revoked. The environment
variable names are the ones the installed SDKs document - `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and for Gemini `GOOGLE_API_KEY` ahead of `GEMINI_API_KEY`, the same
precedence `google.genai` applies itself.

**That the key never becomes text.** `api_key` is a `SecretStr` excluded from every dump,
so `session.json` and the report cannot carry it even by accident, and `redact()` plus
`configure_logging_redaction()` catch the harder case: an SDK exception that echoes the
request it failed on. Redaction is a substring replacement rather than a pattern, because
the thing we must not print is known exactly - guessing at key *shapes* would both miss
real keys and mangle innocent text.

**The output ceiling.** `max_output_tokens` is per provider because it means different
things per provider: OpenAI counts reasoning tokens against it ("including visible output
tokens and reasoning tokens", `openai/types/responses/response_create_params.py`), while
Gemini budgets thinking separately through `thinking_config`. Feature 001's `16000` is
deliberately not inherited: it was documented there as the retired SDK's *non-streaming*
ten-minute ceiling, and both adapters here stream.

The module imports no provider SDK. It is the thing a CLI, the chat backend and a test can
all read before deciding which SDK to import.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Self, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from swreview.agent.providers import EffortLevel, ProviderName

__all__ = [
    "ARMS",
    "DEFAULT_EFFORT",
    "DEFAULT_MODELS",
    "DEFAULT_PROVIDER",
    "ENTERPRISE_ENV",
    "LEVER_NAMES",
    "MASK",
    "MESH_MODES",
    "MODEL_OUTPUT_CEILINGS",
    "MODEL_VIEW_OFF",
    "MODEL_VIEW_PANE",
    "NO_STUDY",
    "OUTPUT_CEILINGS",
    "WORKSTATION_LEVERS",
    "EfficiencySettings",
    "ExtractionSettings",
    "GeminiEnterprise",
    "KeySource",
    "LogRecordRedactor",
    "MeshMode",
    "ModelViewSettings",
    "PaneDefaults",
    "ProviderSettings",
    "RedactingFilter",
    "check_study_arm",
    "checks_first",
    "configure_logging_redaction",
    "default_model",
    "efficiency_from_levers",
    "output_ceiling",
    "pane_defaults",
    "pane_efficiency",
    "redact",
]

KeySource = Literal["settings", "env", "none"]
"""Where the API key for this run came from. Mirrors `report.session.KeySource`, which is
the field on the session record; the two are asserted equal in the unit tests rather than
imported across the layer boundary, so the provider layer stays free of the report layer."""

DEFAULT_PROVIDER = ProviderName.OPENAI
"""What a settings file, a CLI invocation or a pane without a choice gets (FR-027)."""

DEFAULT_EFFORT: EffortLevel = "high"
"""A design review is worth thinking about; `--effort` lowers it deliberately."""

DEFAULT_MODELS: Mapping[ProviderName, str] = {
    ProviderName.OPENAI: "gpt-5.6",
    ProviderName.GEMINI: "gemini-3.5-flash",
    ProviderName.FAKE: "fake-scripted",
}
"""The model each provider runs when nobody chose one (research R3).

`fake-scripted` is the id the scripted provider reports and the one `GET /models` returns
for `fake`: it is not a model, and a session recording it is self-evidently a dry run.
"""

OUTPUT_CEILINGS: Mapping[ProviderName, int] = {
    ProviderName.OPENAI: 32000,
    ProviderName.GEMINI: 16000,
    ProviderName.FAKE: 16000,
}
"""`max_output_tokens` for one turn, per provider.

OpenAI's is the larger number because reasoning tokens are drawn from the same budget
there, so a turn that thinks hard about an interference has less room left for the answer;
Gemini's thinking is budgeted separately by `thinking_config`, so the same visible answer
fits in less. Both are *our* budget for one turn, not a claim about a model's maximum: the
runner's job is to notice the ceiling was hit and record `turn.ended {reason: "truncated"}`
with unresolved coverage, which it can only do if the ceiling is ours to set.
"""

MODEL_OUTPUT_CEILINGS: Mapping[str, int] = {}
"""Per-model overrides of `OUTPUT_CEILINGS`, keyed by model id.

Empty today: no model in `DEFAULT_MODELS` has an output window smaller than its provider's
budget. It exists because `output_ceiling` is asked for a *model*, and a smaller model
added later needs a smaller number here rather than a silent 400 from the provider.
"""

ENTERPRISE_ENV = ("GOOGLE_GENAI_USE_ENTERPRISE", "GOOGLE_GENAI_USE_VERTEXAI")
"""The enterprise switch and its legacy alias, in the precedence `google.genai` uses."""

_TRUE = ("true", "1")
"""What `google/genai/_api_client.py` accepts for those variables; matched exactly."""

MASK = "[redacted]"
"""What a secret becomes in log lines, error text and anything else headed for a human."""


def _provider(name: str | ProviderName) -> ProviderName:
    """`ProviderName` or a `ValueError` naming what was asked for and what exists."""
    try:
        return ProviderName(str(name))
    except ValueError:
        supported = ", ".join(member.value for member in ProviderName)
        raise ValueError(
            f"unknown provider {str(name)!r}; supported providers are {supported}"
        ) from None


def default_model(provider: str | ProviderName) -> str:
    """The model `provider` runs when the engineer named none."""
    return DEFAULT_MODELS[_provider(provider)]


def output_ceiling(provider: str | ProviderName, model: str) -> int:
    """`max_output_tokens` for one turn of `model` on `provider`.

    The model is consulted first so a model with a smaller output window can be given its
    own number; otherwise the provider's budget applies.
    """
    resolved = _provider(provider)
    return MODEL_OUTPUT_CEILINGS.get(model, OUTPUT_CEILINGS[resolved])


class GeminiEnterprise(BaseModel):
    """The Google Cloud project and location a Gemini Enterprise client is bound to.

    Both are required together: `enterprise=True` without a project fails inside the SDK
    on the first call, a long way from the settings file that caused it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project: str
    location: str

    @field_validator("project", "location")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ProviderSettings(BaseModel):
    """Everything one run needs to build a client, and nothing that may reach a file.

    Frozen on purpose: `key_source` is a statement about the key this object holds, and a
    settings object whose key can be swapped after the session recorded its source would
    make that statement false.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    provider: ProviderName
    model: str
    effort: EffortLevel = DEFAULT_EFFORT
    api_key: SecretStr | None = Field(default=None, exclude=True)
    key_source: KeySource = "none"
    base_url: str | None = None
    enterprise: GeminiEnterprise | None = None

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model must not be blank")
        return stripped

    @model_validator(mode="after")
    def _key_source_matches_the_key(self) -> Self:
        if self.api_key is None and self.key_source != "none":
            raise ValueError(f"key_source is {self.key_source!r} but no api_key is set")
        if self.api_key is not None and self.key_source == "none":
            raise ValueError("key_source is 'none' but an api_key is set")
        return self

    @model_validator(mode="after")
    def _enterprise_is_gemini_only(self) -> Self:
        if self.enterprise is not None and self.provider is not ProviderName.GEMINI:
            raise ValueError(
                f"enterprise settings apply to the gemini provider only, not "
                f"{self.provider.value!r}"
            )
        return self

    @property
    def secrets(self) -> tuple[str, ...]:
        """Every value that must never appear in a log line, an error or a file."""
        if self.api_key is None:
            return ()
        return (self.api_key.get_secret_value(),)

    def client_kwargs(self) -> dict[str, Any]:
        """The keyword arguments this provider's client constructor takes.

        `openai.OpenAI(api_key=..., base_url=...)` and `google.genai.Client(api_key=...)`
        or `Client(enterprise=True, project=..., location=...)`, whose `base_url` lives
        under `http_options` instead. Nothing that is unset is included, so the SDK's own
        environment fallbacks still apply to whatever we do not state.
        """
        key = self.api_key.get_secret_value() if self.api_key is not None else None
        if self.provider is ProviderName.GEMINI:
            kwargs: dict[str, Any] = {}
            if self.enterprise is not None:
                kwargs["enterprise"] = True
                kwargs["project"] = self.enterprise.project
                kwargs["location"] = self.enterprise.location
            if key is not None:
                kwargs["api_key"] = key
            if self.base_url is not None:
                kwargs["http_options"] = {"base_url": self.base_url}
            return kwargs
        kwargs = {}
        if key is not None:
            kwargs["api_key"] = key
        if self.base_url is not None:
            kwargs["base_url"] = self.base_url
        return kwargs

    @classmethod
    def from_env(
        cls,
        *,
        provider: str | ProviderName | None = None,
        model: str | None = None,
        effort: EffortLevel | None = None,
        api_key: str | SecretStr | None = None,
        base_url: str | None = None,
        enterprise: GeminiEnterprise | Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ProviderSettings:
        """Settings from the pane's saved values, falling back to the environment.

        Every argument is what `settings.json` (or a CLI flag) supplied; anything left
        `None` is looked for in `env`, which defaults to the process environment. The
        settings-over-environment order is the whole point: a workstation that exports a
        personal key must not quietly override the key the engineer entered in the pane.

        Args:
            provider: `openai`, `gemini` or `fake`; `DEFAULT_PROVIDER` when omitted.
            model: Model id; the provider's default when omitted.
            effort: Requested reasoning effort; `DEFAULT_EFFORT` when omitted.
            api_key: The key from settings. Blank is treated as absent.
            base_url: Endpoint override from settings.
            enterprise: Gemini project and location from settings.
            env: Environment to read; `os.environ` when omitted.

        Raises:
            ValueError: For an unknown provider name, or a Gemini enterprise environment
                that names a project without a location or the other way round.
        """
        source = os.environ if env is None else env
        resolved = _provider(provider) if provider is not None else DEFAULT_PROVIDER

        settings_key = _clean(_secret_text(api_key))
        env_key = _clean(_env_key(resolved, source))
        if settings_key is not None:
            key, key_source = settings_key, "settings"
        elif env_key is not None:
            key, key_source = env_key, "env"
        else:
            key, key_source = None, "none"

        return cls(
            provider=resolved,
            model=model if model is not None else default_model(resolved),
            effort=effort if effort is not None else DEFAULT_EFFORT,
            api_key=SecretStr(key) if key is not None else None,
            key_source=key_source,
            base_url=base_url if base_url is not None else _env_base_url(resolved, source),
            enterprise=enterprise if enterprise is not None else _env_enterprise(resolved, source),
        )


def _secret_text(value: str | SecretStr | None) -> str | None:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


def _clean(value: str | None) -> str | None:
    """A variable that is set but empty is not a value; that is the common Windows case."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_key(provider: ProviderName, env: Mapping[str, str]) -> str | None:
    """The key variable for this provider, or None - including for `fake`, which needs none.

    `GOOGLE_API_KEY` ahead of `GEMINI_API_KEY` is the precedence `google.genai` applies
    itself (it warns when both are set); resolving it here means the session records the
    key that was actually used rather than the one we assumed.
    """
    if provider is ProviderName.OPENAI:
        return env.get("OPENAI_API_KEY")
    if provider is ProviderName.GEMINI:
        return _clean(env.get("GOOGLE_API_KEY")) or env.get("GEMINI_API_KEY")
    return None


def _env_base_url(provider: ProviderName, env: Mapping[str, str]) -> str | None:
    if provider is ProviderName.OPENAI:
        return _clean(env.get("OPENAI_BASE_URL"))
    return None


def _env_enterprise(provider: ProviderName, env: Mapping[str, str]) -> GeminiEnterprise | None:
    """Gemini enterprise from the environment, only when its switch is explicitly on.

    `GOOGLE_CLOUD_PROJECT` is set on plenty of corporate workstations for unrelated
    tools, so the project alone must not route a review at Vertex; the switch is what
    says so. Once it is on, a missing project or location is an error rather than a
    half-configured client that fails on the first call.
    """
    if provider is not ProviderName.GEMINI:
        return None
    switch = _enterprise_switch(env)
    if switch is None:
        return None
    project = _clean(env.get("GOOGLE_CLOUD_PROJECT"))
    location = _clean(env.get("GOOGLE_CLOUD_LOCATION"))
    missing = [
        name
        for name, value in (("GOOGLE_CLOUD_PROJECT", project), ("GOOGLE_CLOUD_LOCATION", location))
        if value is None
    ]
    if project is None or location is None:
        raise ValueError(
            f"{switch} is set but {' and '.join(missing)} is not; "
            "Gemini Enterprise needs both a project and a location"
        )
    return GeminiEnterprise(project=project, location=location)


def _enterprise_switch(env: Mapping[str, str]) -> str | None:
    """The name of the enterprise variable that is set and on, or None.

    The name and not a bool, because it is the variable the engineer has to go and fix:
    telling someone whose shell exports `GOOGLE_GENAI_USE_VERTEXAI` that
    `GOOGLE_GENAI_USE_ENTERPRISE` is set sends them after a variable that does not exist
    on their machine. The first variable that is *present* decides, on or off, which is
    the precedence `google.genai` applies: the new name set to `false` turns the feature
    off even when the legacy alias is on.
    """
    for name in ENTERPRISE_ENV:
        value = env.get(name)
        if value is not None:
            return name if value.strip().lower() in _TRUE else None
    return None


# --- the efficiency levers ------------------------------------------------------


class EfficiencySettings(BaseModel):
    """Which efficiency levers this run has on. Every field defaults to off.

    One object for all thirteen flags rather than one plumbed argument per lever (OQ-1):
    threaded as one keyword argument through `start_review`, `ReviewRun`, `run_benchmark`
    and `cli._review_fn` exactly as `effort` and `max_steps` already are, and recorded
    whole on `session.efficiency`. Without that record no results row can be attributed to
    a configuration and the A/B table cannot be rebuilt from the run folder.

    Frozen, because `session.efficiency` is a statement about the run that produced it,
    and `extra="forbid"`, because a session carrying a flag a later build removed must
    fail loudly rather than be silently ignored: a results row attributed to a
    configuration nobody can reconstruct is worse than an error (data-model.md 7.3).

    Every field is off here and stays off. A lever is adopted by becoming a default in
    code, never by flipping a default in this class quietly, and never by a checkbox in the
    pane (data-model.md 7.2): the pane's defaults are `pane_efficiency(provider)`, the one
    function that decides them (feature 008 research R2.14).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trim_tool_descriptions: bool = False
    """Lever 2: tool descriptions are the first paragraph only."""

    tool_tiers: bool = False
    """Lever 4: the package-decidable tool tiers are applied."""

    prompt_cache_key: bool = False
    """Lever 3, OpenAI: `prompt_cache_key` is sent on every request."""

    gemini_explicit_cache: bool = False
    """Lever 3, Gemini: an explicit `CachedContent` is created and referenced."""

    prerun_checks: bool = False
    """Checks first, lever 5, pane default since 2026-09-22: every argument-free check runs
    before the first turn (feature 008). Off here; the pane turns it on through
    `pane_efficiency`, and `checks_first` is what every reader asks."""

    parallel_tool_calls: bool = False
    """Lever 6, OpenAI: the request stops pinning `parallel_tool_calls: False`. Pane default
    for OpenAI since 2026-09-22 (feature 008); off here, and the pane turns it on through
    `pane_efficiency`."""

    coverage_stop: bool = False
    """Lever 7: the stop predicate issues the next round with tool calls disabled."""

    package_reuse: bool = False
    """Lever 9, workstation: an unchanged package is reused instead of dumped."""

    lazy_meshes: bool = False
    """Lever 10a, workstation: meshes are fetched on demand over the bridge."""

    carry_over_rms: bool = False
    """Lever 11a, workstation: unchanged `rms.*` findings are carried over."""

    procedural_gate: bool = False
    """Lever 11: the deterministic checks run first and the model opens on their brief.

    Appended last, and appended rather than inserted, because `LEVER_NAMES` is the field
    order and a name in the middle would reorder every refusal message that iterates it
    (feature 007 research R2.10). It **implies** lever 5: the pre-run runs when either
    flag is on, which is why the two never share an arm."""

    compact_queries: bool = False
    """Experimental bounded package discovery pages; opt-in and default-off."""

    withhold_prerun_tools: bool = False
    """Lever 13, pane default since 2026-09-23: a check tool checks first ran to completion
    leaves the tool array for the rest of the session (feature 008 FR-030,
    `contracts/checks-first.md` section 7). Inert without a pre-run, which is why
    `efficiency_from_levers` refuses it without lever 5 or lever 11. Appended last, for the
    reason lever 11 was."""


def checks_first(efficiency: EfficiencySettings | None) -> bool:
    """Does this run run its argument-free checks before the first turn? (feature 008)

    Lever 5 or lever 11: the gate implies the pre-run and only changes what the model opens
    on (research R2.13). The one place the "or" is written, so the pre-run, the standards
    attach and the fold marker cannot disagree about it. `None` - every caller that
    predates feature 005 - is every lever off.
    """
    return efficiency is not None and (efficiency.prerun_checks or efficiency.procedural_gate)


def pane_efficiency(provider: ProviderName) -> EfficiencySettings:
    """The levers every pane review runs with: the one place the pane's defaults are decided.

    Checks first on every provider, since the owner's decision of 2026-09-22 (feature 008
    User Story 2); parallel tool calls on OpenAI only, from the same decision (User Story 4,
    research R2.14, R2.40): Gemini has no switch and already makes parallel calls, and the
    scripted provider reads no request field, so both record the lever off; and the tools
    checks first ran leaving the array, for every provider, since 2026-09-23 (lever 13,
    research R2.53). The command line and `benchmark run` stay all off; `swreview review
    --pane-defaults` reproduces this.
    """
    return EfficiencySettings(
        prerun_checks=True,
        withhold_prerun_tools=True,
        parallel_tool_calls=provider is ProviderName.OPENAI,
    )


class ModelViewSettings(BaseModel):
    """What the model reads of each tool result (feature 008 User Story 3).

    Settings, not levers: they change what the model *reads*, never what the review records -
    the session, the package, the report and every stored result keep the full payload - so
    they are not in `LEVER_NAMES` and move no lever-count pin (research R2.32). Frozen and
    closed for the reason `EfficiencySettings` is: the session records what ran. The two
    booleans have no default on purpose, so a caller states both; `MODEL_VIEW_OFF` and
    `MODEL_VIEW_PANE` are the two values every surface uses.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_slimming: bool
    """The view: references stripped, check results as digests with `get_finding`, gap rows
    grouped, compact JSON (`tools/model_view.py`)."""

    history_pruning: bool
    """Results older than `prune_after_rounds` rounds reach the model as deterministic stubs
    (`agent/providers/pruning.py`)."""

    prune_after_rounds: int = Field(default=2, ge=1)
    """How many rounds a result stays in the model's view in full. Two, the safer of the one
    or two rounds the owner allowed (research R2.37)."""


MODEL_VIEW_OFF = ModelViewSettings(payload_slimming=False, history_pruning=False)
"""Every result in full, every round: the command line's and `benchmark run`'s default, and
what a session written before feature 008 means."""

MODEL_VIEW_PANE = ModelViewSettings(payload_slimming=True, history_pruning=True)
"""What every pane review reads: slim views, and stubs after two rounds."""


@dataclass(frozen=True)
class PaneDefaults:
    """Everything a pane review runs with that the command line leaves off."""

    efficiency: EfficiencySettings
    model_view: ModelViewSettings


def pane_defaults(provider: ProviderName) -> PaneDefaults:
    """The pane's levers and model view: read by the pane, `--pane-defaults` and the replay."""
    return PaneDefaults(pane_efficiency(provider), MODEL_VIEW_PANE)


MeshMode = Literal["eager", "lazy", "off"]
"""Where a body's mesh comes from: the package, the bridge, or nowhere."""

MESH_MODES: tuple[str, ...] = get_args(MeshMode)

DEFAULT_LAZY_FETCH_BODY_LIMIT = 200
"""How many bodies one review may pull back over the bridge before it stops asking.

A bound rather than a budget: one STA worker answers every bridge call in arrival order,
so a review that fetched a thousand bodies would stall the application thread for minutes
(RK-14). Reaching it is unresolved coverage naming what was not fetched, never a stop, so
the number only decides how much of an answer a runaway still gives.
"""


class ExtractionSettings(BaseModel):
    """Where this run's evidence comes from. Lever 10a is the only reader today.

    Separate from `EfficiencySettings` because these are not flags: `meshes` is a three-way
    statement about the package under review, and a package extracted with `--meshes none`
    is described by `off` whether or not any lever is on. `for_efficiency` is the one place
    the lever and the statement are tied together, so nothing else has to know that
    `lazy_meshes` means `meshes="lazy"`.

    Frozen and `extra="forbid"` for the same reasons `EfficiencySettings` is: it is a
    statement about a run, and a field a later build removed must fail loudly rather than
    be ignored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    meshes: MeshMode = "eager"
    """`eager`: the dump wrote them. `lazy`: fetch one over the bridge when a check needs
    it. `off`: there are none and none are coming, which is unresolved coverage wherever a
    check needed one.

    **`eager` is the default, and that is the constitution's position rather than a
    preference**: a lazily extracted package reviewed off the workstation is a package with
    less evidence, and the flag that reduces evidence is the one that is opted into."""

    lazy_fetch_body_limit: int = Field(default=DEFAULT_LAZY_FETCH_BODY_LIMIT, ge=0)
    """How many bodies one review may fetch; reaching it is unresolved, not a stop."""

    @classmethod
    def for_efficiency(cls, efficiency: EfficiencySettings | None) -> ExtractionSettings:
        """The extraction this run's levers ask for. `None` is every lever off."""
        if efficiency is not None and efficiency.lazy_meshes:
            return cls(meshes="lazy")
        return cls()


LEVER_NAMES: tuple[str, ...] = tuple(EfficiencySettings.model_fields)
"""The thirteen lever names, taken from the model so nothing has to retype them.

Every refusal message below, the `--lever` option and the pane guard iterate this, so a
lever added to the model is covered by all of them without a second edit anywhere.
"""

WORKSTATION_LEVERS: tuple[str, ...] = ("package_reuse", "lazy_meshes", "carry_over_rms")
"""The three levers `swreview benchmark run` cannot see.

It iterates pre-built package directories and never dumps, so these three change nothing
it does. They are measured by the workstation harness, which writes a run directory of
the same shape (contracts/ab-harness.md section 2, FR-030).
"""

ARMS: tuple[str, ...] = ("off", "on", "baseline")
"""What `--arm` may say about a run. `baseline` is the study with no lever under test."""

NO_STUDY = "none"
"""What `--study` says when a run is testing no lever at all."""


def _levers_sentence() -> str:
    return "the thirteen levers are " + ", ".join(LEVER_NAMES)


GATED_ALONE: tuple[tuple[str, int, str, int], ...] = (
    ("coverage_stop", 7, "prerun_checks", 5),
    ("procedural_gate", 11, "prerun_checks", 5),
    ("procedural_gate", 11, "coverage_stop", 7),
)
"""The lever pairs no arm may carry together, each with the two lever numbers.

All three share one failure and therefore one sentence: a pre-run that closes every
checklist item, combined with a stop predicate or with a second pre-run, ends the review
before the first turn, and the arm measures nothing that can be attributed to either lever
(contracts/ab-harness.md section 2, feature 007 contracts/gate.md section 1). Written as a
table rather than as three hand-typed `raise`s so the three messages cannot drift apart.
"""


def efficiency_from_levers(
    levers: Iterable[str],
    *,
    provider: ProviderName | None = None,
    allow_workstation_levers: bool = True,
) -> EfficiencySettings:
    """Resolve the `--lever` names typed on one command line into settings.

    The refusals live here, where the lever is chosen, rather than on `benchmark compare`,
    because a refusal after six paid runs is worthless (contracts/ab-harness.md section
    2). Each names the rule it is enforcing.

    Args:
        levers: The `--lever` names, in the order they were typed. Repeats are harmless.
        provider: The provider this run will use, when the caller knows it. Only lever 6
            depends on it.
        allow_workstation_levers: False for a caller that never dumps a package - the
            benchmark runner - so the three dump levers are refused there rather than
            producing an arm that measures nothing.

    Raises:
        ValueError: For an unknown name, or a combination the study protocol forbids.
    """
    chosen = list(levers)
    unknown = sorted({name for name in chosen if name not in LEVER_NAMES})
    if unknown:
        raise ValueError(f"unknown lever(s) {', '.join(unknown)}: {_levers_sentence()}")

    for first, first_number, second, second_number in GATED_ALONE:
        if first in chosen and second in chosen:
            low, high = sorted((first_number, second_number))
            raise ValueError(
                f"--lever {first} with --lever {second}: levers {low} and {high} never "
                f"share an arm until each has been gated alone"
            )

    if "parallel_tool_calls" in chosen and provider is ProviderName.GEMINI:
        raise ValueError(
            "--lever parallel_tool_calls with --provider gemini: Gemini already makes "
            "parallel tool calls and has no disable switch, so this arm would measure "
            "nothing"
        )

    if (
        "withhold_prerun_tools" in chosen
        and "prerun_checks" not in chosen
        and "procedural_gate" not in chosen
    ):
        raise ValueError(
            "--lever withhold_prerun_tools without --lever prerun_checks or --lever "
            "procedural_gate: lever 13 withholds only the tools checks first ran, and "
            "without a pre-run this arm would measure nothing"
        )

    if not allow_workstation_levers:
        refused = sorted({name for name in chosen if name in WORKSTATION_LEVERS})
        if refused:
            raise ValueError(
                f"--lever {', '.join(refused)}: `swreview benchmark run` iterates "
                f"pre-built package directories and never dumps, so these levers are "
                f"invisible to it; measure them with the workstation harness, which "
                f"writes a run directory of the same shape"
            )

    return EfficiencySettings(**{name: True for name in chosen})


def check_study_arm(*, study: str, arm: str | None, efficiency: EfficiencySettings) -> None:
    """Refuse a run whose `--study`, `--arm` and `--lever` contradict each other.

    Which lever a run is testing and which arm it is are facts *about the study*, not
    about the settings: they exist across two run folders, not inside one, which is why
    they are typed rather than derived. A run mislabelled in its own provenance record is
    worse than no run, because it renders without complaint in the wrong arm.

    Args:
        study: A lever name, or `none` for a run that is testing no lever.
        arm: `off`, `on`, `baseline`, or None when the run claims no arm.
        efficiency: The settings `--lever` resolved to.

    Raises:
        ValueError: For any of the four contradictions of contracts/ab-harness.md
            section 2.
    """
    if study != NO_STUDY and study not in LEVER_NAMES:
        raise ValueError(f"unknown --study {study!r}: {_levers_sentence()}, or none")
    if arm is None:
        return
    if arm not in ARMS:
        raise ValueError(f"unknown --arm {arm!r}: one of {', '.join(ARMS)}")

    on_levers = sorted(name for name in LEVER_NAMES if getattr(efficiency, name))

    if arm == "baseline":
        if study != NO_STUDY:
            raise ValueError(
                f"--arm baseline with --study {study}: a baseline run is the study with "
                f"no lever under test, so its study is none"
            )
        if on_levers:
            raise ValueError(
                f"--arm baseline with --lever {', '.join(on_levers)}: a baseline run has "
                f"every lever off"
            )
        return

    if study == NO_STUDY:
        raise ValueError(
            f"--study none with --arm {arm}: an off or on arm is an arm of some study, so "
            f"name the lever under test"
        )
    if arm == "on" and not getattr(efficiency, study):
        raise ValueError(
            f"--arm on with {study} absent from --lever: the on arm of a study is the run "
            f"with the studied lever on"
        )
    if arm == "off" and getattr(efficiency, study):
        raise ValueError(
            f"--arm off with --lever {study}: the off arm of a study is the run with the "
            f"studied lever off"
        )


# --- redaction ------------------------------------------------------------------


def _secret_values(secrets: Iterable[str | SecretStr | None]) -> tuple[str, ...]:
    """The non-empty secrets, longest first.

    Longest first matters when one configured key is a prefix of another: masking the
    short one first would leave the tail of the long one in the text.
    """
    values = {text for text in (_clean(_secret_text(item)) for item in secrets) if text}
    return tuple(sorted(values, key=len, reverse=True))


def redact(text: object, secrets: Iterable[str | SecretStr | None]) -> str:
    """`str(text)` with every secret replaced by `MASK` (FR-015).

    Exceptions are passed in as often as strings, so the subject is coerced rather than
    typed to `str`. Substring replacement, not a pattern: what must not be printed is
    known exactly, and a key-shaped regex would both miss real keys and mangle innocent
    text. An empty or blank secret is ignored - an unset key must not mask every
    character of the line.
    """
    result = str(text)
    for secret in _secret_values(secrets):
        result = result.replace(secret, MASK)
    return result


def _mask_record(record: logging.LogRecord, secrets: Sequence[str]) -> None:
    """Rewrite one record's message, traceback and stack in place. Never drops it.

    A log line that mentioned a key is still a line we want, with the key gone. The
    *formatted* message replaces `msg` (and `args` is cleared) so the substitution
    survives lazy `%s` formatting; `exc_text` is filled in with the redacted traceback so
    the handler's formatter uses that cached text instead of re-rendering the exception
    with the key back in it.

    A record whose `%`-formatting is already broken cannot be formatted here either. That
    is logging's own error to report at format time, so only `msg` is masked and `args` is
    left exactly as the caller passed it - swallowing the record, or clearing its args,
    would turn a redaction concern into a lost diagnostic.
    """
    if not secrets:
        return
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001 - broken %-formatting, reported by logging itself
        record.msg = redact(record.msg, secrets)
    else:
        masked = redact(message, secrets)
        if masked != message:
            record.msg = masked
            record.args = ()
    if record.exc_info is not None and record.exc_text is None:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    if record.exc_text:
        record.exc_text = redact(record.exc_text, secrets)
    if record.stack_info:
        record.stack_info = redact(record.stack_info, secrets)


class RedactingFilter(logging.Filter):
    """A logging filter that rewrites the message and traceback of every record.

    Scoped to the records emitted *through* the logger (or handler) it is attached to.
    That scope is the reason it is not what `configure_logging_redaction` installs: see
    `LogRecordRedactor`.
    """

    def __init__(self, secrets: Iterable[str | SecretStr | None]) -> None:
        super().__init__()
        self.secrets = _secret_values(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        _mask_record(record, self.secrets)
        return True


class LogRecordRedactor:
    """Process-wide log redaction, installed as the `logging` record factory.

    A `logging.Filter` is the obvious mechanism and the wrong one. A logger consults its
    own filters only for records emitted through *that* logger: `Logger.callHandlers`
    walks the ancestors and invokes their **handlers** without re-running their
    **filters**. So a filter on the root logger never sees a line from
    `logging.getLogger("openai")`, `google_genai`, `httpx` or `uvicorn` - which are
    exactly the loggers a leaked key would come out of.

    The record factory is the one place every record in the process is born, whatever
    logger emitted it and whatever handlers are attached before or after this install, so
    masking there is the only install that cannot be routed around.
    """

    def __init__(self, secrets: Iterable[str | SecretStr | None]) -> None:
        self.secrets = _secret_values(secrets)
        self._previous: Callable[..., logging.LogRecord] | None = None

    def install(self) -> None:
        """Take over the record factory, keeping the one replaced so it still runs."""
        self._previous = logging.getLogRecordFactory()
        logging.setLogRecordFactory(self)

    def remove(self) -> None:
        """Put the previous factory back, if this one is still the installed factory.

        Removal is expected to be last-in-first-out (the backend installs one redactor per
        launch). When it is not - another redactor was installed on top of this one -
        restoring would tear that later one off the chain, so this one stays where it is
        and simply stops masking instead.
        """
        if self._previous is None:
            return
        if logging.getLogRecordFactory() is self:
            logging.setLogRecordFactory(self._previous)
            self._previous = None
        self.secrets = ()

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        previous = self._previous if self._previous is not None else logging.LogRecord
        record = previous(*args, **kwargs)
        _mask_record(record, self.secrets)
        return record


def configure_logging_redaction(
    secrets: Iterable[str | SecretStr | None],
) -> LogRecordRedactor:
    """Mask every secret out of every log record in this process, and return the install.

    The install is returned so the caller can take it off again - the pane restarts the
    backend when the key changes, and a redactor still masking the old key would be dead
    weight. A run with no secrets installs one too, so a keyless (`fake`) run takes exactly
    the same logging path as a real one.
    """
    redactor = LogRecordRedactor(secrets)
    redactor.install()
    return redactor
