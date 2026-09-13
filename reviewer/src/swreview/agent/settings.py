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
from typing import Any, Literal, Self

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
    "DEFAULT_EFFORT",
    "DEFAULT_MODELS",
    "DEFAULT_PROVIDER",
    "ENTERPRISE_ENV",
    "MASK",
    "MODEL_OUTPUT_CEILINGS",
    "OUTPUT_CEILINGS",
    "GeminiEnterprise",
    "KeySource",
    "LogRecordRedactor",
    "ProviderSettings",
    "RedactingFilter",
    "configure_logging_redaction",
    "default_model",
    "output_ceiling",
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
