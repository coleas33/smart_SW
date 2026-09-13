"""Unit tests for the provider settings module (T021).

Four things this module owns, and the reason each one is tested the way it is:

1. **Precedence.** The pane's `settings.json` wins over the environment, and the run
   records *where* the key came from (`key_source`), because a session that cannot say
   which key it used cannot be reproduced. Env reading is exercised through an injected
   mapping so the tests never mutate the process environment - except one test, which
   proves `os.environ` is what the injected mapping replaces.
2. **Secrecy.** FR-015: a key never reaches `session.json`, a report, a log line or an
   error string. The assertions are all of the form "the literal key text is not in
   `x`", never "the field is a `SecretStr`": the former is the requirement, the latter
   is an implementation detail that could hold while the key still leaks.
3. **Defaults.** FR-026: no Claude model id may be reachable from any code path, so the
   default model is per provider and lives here. Each default is asserted literally, and
   every provider name is asserted to have one, so a fourth provider cannot be added
   without a default.
4. **Ceilings.** T018's adapter takes its `max_output_tokens` from here. The test pins
   the two invariants that matter to the truncation path: every provider has a positive
   ceiling, and OpenAI's is the larger one because reasoning tokens are drawn from the
   same budget there (verified in the installed SDK: `response_create_params.py` says
   "including visible output tokens and reasoning tokens"), while Gemini budgets
   thinking separately through `thinking_config`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, get_args

import pytest
from pydantic import SecretStr, ValidationError

from swreview.agent.providers import EffortLevel, ProviderName
from swreview.agent.settings import (
    DEFAULT_EFFORT,
    DEFAULT_MODELS,
    DEFAULT_PROVIDER,
    MASK,
    OUTPUT_CEILINGS,
    GeminiEnterprise,
    ProviderSettings,
    RedactingFilter,
    configure_logging_redaction,
    default_model,
    output_ceiling,
    redact,
)

KEY = "sk-settings-0123456789abcdef"
ENV_KEY = "sk-env-9876543210fedcba"
GOOGLE_KEY = "google-key-0123456789"
GEMINI_KEY = "gemini-key-9876543210"


# --- defaults -------------------------------------------------------------------


def test_key_source_matches_the_field_the_session_record_declares() -> None:
    """`report.session.KeySource` is the field written into `session.json`. The literal is
    restated here rather than imported, so the provider layer does not depend on the report
    layer; this assertion is what keeps the two from drifting apart."""
    from swreview.agent.settings import KeySource as SettingsKeySource
    from swreview.report.session import KeySource as SessionKeySource

    assert get_args(SettingsKeySource) == get_args(SessionKeySource)


def test_default_provider_and_effort_are_the_documented_ones() -> None:
    """`openai` and `high`: the settings contract's defaults (T026, contracts/cli.md)."""
    assert DEFAULT_PROVIDER is ProviderName.OPENAI
    assert DEFAULT_EFFORT == "high"
    assert DEFAULT_EFFORT in get_args(EffortLevel)


def test_default_model_per_provider_is_the_researched_id() -> None:
    """R3's verified ids, and the scripted id for the keyless development provider."""
    assert default_model(ProviderName.OPENAI) == "gpt-5.6"
    assert default_model(ProviderName.GEMINI) == "gemini-3.5-flash"
    assert default_model(ProviderName.FAKE) == "fake-scripted"


def test_every_provider_has_a_default_model_and_none_of_them_is_a_claude_id() -> None:
    """FR-026: no code path may write a Claude model id into `session.json`."""
    assert set(DEFAULT_MODELS) == set(ProviderName)
    for provider, model in DEFAULT_MODELS.items():
        assert model.strip(), provider
        assert "claude" not in model.lower()
        assert "anthropic" not in model.lower()


def test_default_model_accepts_the_provider_name_as_a_string() -> None:
    """The CLI and the pane both hand this module a plain string from user input."""
    assert default_model("gemini") == "gemini-3.5-flash"


def test_default_model_rejects_an_unknown_provider() -> None:
    with pytest.raises(ValueError, match="anthropic"):
        default_model("anthropic")


# --- output ceilings ------------------------------------------------------------


def test_every_provider_has_a_positive_output_ceiling() -> None:
    assert set(OUTPUT_CEILINGS) == set(ProviderName)
    for provider, ceiling in OUTPUT_CEILINGS.items():
        assert ceiling > 0, provider


def test_openai_ceiling_exceeds_gemini_because_reasoning_shares_the_budget() -> None:
    """OpenAI counts reasoning tokens in `max_output_tokens`; Gemini budgets thinking
    separately through `thinking_config`, so the same visible answer needs less here."""
    assert output_ceiling(ProviderName.OPENAI, "gpt-5.6") > output_ceiling(
        ProviderName.GEMINI, "gemini-3.5-flash"
    )


def test_output_ceiling_is_not_the_inherited_anthropic_non_streaming_number() -> None:
    """16000 was feature 001's *non-streaming* ten-minute ceiling; these adapters stream."""
    assert output_ceiling(ProviderName.OPENAI, "gpt-5.6") != 16000


def test_output_ceiling_falls_back_to_the_provider_budget_for_an_unlisted_model() -> None:
    """A model we have no specific number for still gets its provider's budget, not None."""
    assert output_ceiling(ProviderName.OPENAI, "gpt-5.5") == OUTPUT_CEILINGS[ProviderName.OPENAI]


def test_output_ceiling_rejects_an_unknown_provider() -> None:
    with pytest.raises(ValueError, match="anthropic"):
        output_ceiling("anthropic", "claude-opus-5")


# --- construction and validation ------------------------------------------------


def test_settings_require_an_explicit_model() -> None:
    """There is no module-level default model on the type: the caller resolves it, so a
    session can never record a model nobody chose (data-model section 1)."""
    with pytest.raises(ValidationError):
        ProviderSettings(provider=ProviderName.OPENAI)  # type: ignore[call-arg]


def test_settings_reject_a_blank_model() -> None:
    with pytest.raises(ValidationError):
        ProviderSettings(provider=ProviderName.OPENAI, model="   ")


def test_settings_reject_an_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        ProviderSettings(provider="anthropic", model="claude-opus-5")


def test_settings_reject_an_unknown_effort_level() -> None:
    with pytest.raises(ValidationError):
        ProviderSettings(provider=ProviderName.OPENAI, model="gpt-5.6", effort="max")


def test_settings_reject_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ProviderSettings(provider=ProviderName.OPENAI, model="gpt-5.6", api_key_plain=KEY)


def test_settings_are_frozen() -> None:
    """One run, one settings object: a key that changes mid-run makes `key_source` a lie."""
    settings = ProviderSettings(provider=ProviderName.OPENAI, model="gpt-5.6")
    with pytest.raises(ValidationError):
        settings.model = "gpt-5.5"  # type: ignore[misc]


def test_key_source_must_be_none_when_no_key_is_held() -> None:
    """`key_source` describes the key that is present; without one it can only be `none`."""
    with pytest.raises(ValidationError, match="key_source"):
        ProviderSettings(provider=ProviderName.OPENAI, model="gpt-5.6", key_source="settings")


def test_key_source_must_not_be_none_when_a_key_is_held() -> None:
    with pytest.raises(ValidationError, match="key_source"):
        ProviderSettings(
            provider=ProviderName.OPENAI, model="gpt-5.6", api_key=KEY, key_source="none"
        )


def test_api_key_accepts_a_plain_string_and_wraps_it() -> None:
    settings = ProviderSettings(
        provider=ProviderName.OPENAI, model="gpt-5.6", api_key=KEY, key_source="settings"
    )
    assert isinstance(settings.api_key, SecretStr)
    assert settings.api_key.get_secret_value() == KEY


# --- enterprise (Gemini) --------------------------------------------------------


def test_enterprise_is_only_valid_for_gemini() -> None:
    """`enterprise=True, project=..., location=...` is a `genai.Client` argument; on any
    other provider it would be silently dropped, which is worse than a refusal."""
    with pytest.raises(ValidationError, match="gemini"):
        ProviderSettings(
            provider=ProviderName.OPENAI,
            model="gpt-5.6",
            enterprise=GeminiEnterprise(project="p", location="us-central1"),
        )


def test_enterprise_accepts_a_mapping_from_the_settings_file() -> None:
    settings = ProviderSettings(
        provider=ProviderName.GEMINI,
        model="gemini-3.5-flash",
        enterprise={"project": "acme-cad", "location": "us-central1"},
    )
    assert settings.enterprise == GeminiEnterprise(project="acme-cad", location="us-central1")


def test_enterprise_requires_both_project_and_location() -> None:
    with pytest.raises(ValidationError):
        GeminiEnterprise(project="acme-cad")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        GeminiEnterprise(project="  ", location="us-central1")


def test_enterprise_maps_to_the_genai_client_arguments() -> None:
    """The exact keyword names the installed `google.genai.Client` documents."""
    settings = ProviderSettings(
        provider=ProviderName.GEMINI,
        model="gemini-3.5-flash",
        enterprise={"project": "acme-cad", "location": "us-central1"},
    )
    assert settings.client_kwargs() == {
        "enterprise": True,
        "project": "acme-cad",
        "location": "us-central1",
    }


def test_client_kwargs_without_enterprise_carry_the_key_and_base_url() -> None:
    settings = ProviderSettings(
        provider=ProviderName.OPENAI,
        model="gpt-5.6",
        api_key=KEY,
        key_source="settings",
        base_url="https://proxy.internal/v1",
    )
    assert settings.client_kwargs() == {"api_key": KEY, "base_url": "https://proxy.internal/v1"}


def test_client_kwargs_omit_what_is_not_set() -> None:
    settings = ProviderSettings(provider=ProviderName.FAKE, model="fake-scripted")
    assert settings.client_kwargs() == {}


# --- precedence and key_source --------------------------------------------------


def test_settings_key_wins_over_the_environment() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.OPENAI, api_key=KEY, env={"OPENAI_API_KEY": ENV_KEY}
    )
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == KEY
    assert settings.key_source == "settings"


def test_environment_key_is_used_when_settings_hold_none() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.OPENAI, env={"OPENAI_API_KEY": ENV_KEY}
    )
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == ENV_KEY
    assert settings.key_source == "env"


def test_no_key_anywhere_reports_none() -> None:
    settings = ProviderSettings.from_env(provider=ProviderName.OPENAI, env={})
    assert settings.api_key is None
    assert settings.key_source == "none"


def test_a_blank_environment_key_is_not_a_key() -> None:
    """An exported-but-empty variable is the common Windows case and must not read as a key."""
    settings = ProviderSettings.from_env(provider=ProviderName.OPENAI, env={"OPENAI_API_KEY": "  "})
    assert settings.api_key is None
    assert settings.key_source == "none"


def test_environment_key_is_stripped() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.OPENAI, env={"OPENAI_API_KEY": f"  {ENV_KEY}\n"}
    )
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == ENV_KEY


def test_google_api_key_wins_over_gemini_api_key() -> None:
    """The installed `google.genai` does the same and warns; we resolve it explicitly (R3)."""
    settings = ProviderSettings.from_env(
        provider=ProviderName.GEMINI,
        env={"GOOGLE_API_KEY": GOOGLE_KEY, "GEMINI_API_KEY": GEMINI_KEY},
    )
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == GOOGLE_KEY
    assert settings.key_source == "env"


def test_gemini_api_key_is_used_when_google_api_key_is_absent() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.GEMINI, env={"GEMINI_API_KEY": GEMINI_KEY}
    )
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == GEMINI_KEY


def test_the_fake_provider_never_picks_up_a_key() -> None:
    """It reaches no network; a run that reports a key source it did not use is a lie."""
    settings = ProviderSettings.from_env(
        provider=ProviderName.FAKE,
        env={"OPENAI_API_KEY": ENV_KEY, "GOOGLE_API_KEY": GOOGLE_KEY},
    )
    assert settings.api_key is None
    assert settings.key_source == "none"


def test_a_provider_does_not_pick_up_the_other_providers_key() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.OPENAI, env={"GOOGLE_API_KEY": GOOGLE_KEY}
    )
    assert settings.api_key is None
    assert settings.key_source == "none"


def test_from_env_defaults_to_the_default_provider_model_and_effort() -> None:
    settings = ProviderSettings.from_env(env={})
    assert settings.provider is DEFAULT_PROVIDER
    assert settings.model == default_model(DEFAULT_PROVIDER)
    assert settings.effort == DEFAULT_EFFORT


def test_from_env_uses_the_per_provider_default_model() -> None:
    assert ProviderSettings.from_env(provider="gemini", env={}).model == "gemini-3.5-flash"
    assert ProviderSettings.from_env(provider="fake", env={}).model == "fake-scripted"


def test_from_env_keeps_an_explicit_model_and_effort() -> None:
    settings = ProviderSettings.from_env(provider="openai", model="gpt-5.5", effort="low", env={})
    assert settings.model == "gpt-5.5"
    assert settings.effort == "low"


def test_base_url_comes_from_the_environment_when_settings_hold_none() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.OPENAI, env={"OPENAI_BASE_URL": "https://proxy.internal/v1"}
    )
    assert settings.base_url == "https://proxy.internal/v1"


def test_settings_base_url_wins_over_the_environment() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.OPENAI,
        base_url="https://chosen.internal/v1",
        env={"OPENAI_BASE_URL": "https://proxy.internal/v1"},
    )
    assert settings.base_url == "https://chosen.internal/v1"


def test_enterprise_comes_from_the_environment_for_gemini() -> None:
    """The variable names the installed `google.genai.Client` docstring names."""
    settings = ProviderSettings.from_env(
        provider=ProviderName.GEMINI,
        env={
            "GOOGLE_GENAI_USE_ENTERPRISE": "true",
            "GOOGLE_CLOUD_PROJECT": "acme-cad",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
        },
    )
    assert settings.enterprise == GeminiEnterprise(project="acme-cad", location="us-central1")


def test_enterprise_from_the_environment_needs_project_and_location() -> None:
    """Half a configuration is a misconfiguration; `enterprise=True` without a project
    would fail deep inside the SDK on the first call instead of here."""
    with pytest.raises(ValueError, match="GOOGLE_CLOUD_LOCATION"):
        ProviderSettings.from_env(
            provider=ProviderName.GEMINI,
            env={"GOOGLE_GENAI_USE_ENTERPRISE": "true", "GOOGLE_CLOUD_PROJECT": "acme-cad"},
        )


def test_the_incomplete_enterprise_error_names_the_switch_that_was_actually_set() -> None:
    """An engineer whose shell exports the legacy alias must be told about *that* one.

    Naming `GOOGLE_GENAI_USE_ENTERPRISE` unconditionally sends them looking for a variable
    that is not set anywhere on their machine, which is a worse position than no message.
    """
    with pytest.raises(ValueError, match="GOOGLE_GENAI_USE_VERTEXAI is set"):
        ProviderSettings.from_env(
            provider=ProviderName.GEMINI,
            env={"GOOGLE_GENAI_USE_VERTEXAI": "true", "GOOGLE_CLOUD_PROJECT": "acme-cad"},
        )


def test_enterprise_accepts_the_legacy_vertexai_switch() -> None:
    """`GOOGLE_GENAI_USE_VERTEXAI` is the alias the installed SDK still honours (R3)."""
    settings = ProviderSettings.from_env(
        provider=ProviderName.GEMINI,
        env={
            "GOOGLE_GENAI_USE_VERTEXAI": "1",
            "GOOGLE_CLOUD_PROJECT": "acme-cad",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
        },
    )
    assert settings.enterprise == GeminiEnterprise(project="acme-cad", location="us-central1")


def test_the_enterprise_switch_wins_over_its_legacy_alias() -> None:
    """The SDK warns and prefers `GOOGLE_GENAI_USE_ENTERPRISE`; so do we, silently."""
    settings = ProviderSettings.from_env(
        provider=ProviderName.GEMINI,
        env={
            "GOOGLE_GENAI_USE_ENTERPRISE": "false",
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            "GOOGLE_CLOUD_PROJECT": "acme-cad",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
        },
    )
    assert settings.enterprise is None


def test_enterprise_environment_is_ignored_without_the_use_flag() -> None:
    """`GOOGLE_CLOUD_PROJECT` is set on many corporate workstations for other tools."""
    settings = ProviderSettings.from_env(
        provider=ProviderName.GEMINI,
        env={"GOOGLE_CLOUD_PROJECT": "acme-cad", "GOOGLE_CLOUD_LOCATION": "us-central1"},
    )
    assert settings.enterprise is None


def test_settings_enterprise_wins_over_the_environment() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.GEMINI,
        enterprise={"project": "chosen", "location": "europe-west4"},
        env={
            "GOOGLE_GENAI_USE_ENTERPRISE": "true",
            "GOOGLE_CLOUD_PROJECT": "acme-cad",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
        },
    )
    assert settings.enterprise == GeminiEnterprise(project="chosen", location="europe-west4")


def test_enterprise_environment_is_ignored_for_openai() -> None:
    settings = ProviderSettings.from_env(
        provider=ProviderName.OPENAI,
        env={
            "GOOGLE_GENAI_USE_ENTERPRISE": "true",
            "GOOGLE_CLOUD_PROJECT": "acme-cad",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
        },
    )
    assert settings.enterprise is None


def test_from_env_reads_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The injected mapping in every other test stands in for exactly this."""
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    settings = ProviderSettings.from_env(provider=ProviderName.OPENAI)
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == ENV_KEY
    assert settings.key_source == "env"


# --- secrecy --------------------------------------------------------------------


def settings_with_key() -> ProviderSettings:
    return ProviderSettings(
        provider=ProviderName.OPENAI, model="gpt-5.6", api_key=KEY, key_source="settings"
    )


def test_model_dump_excludes_the_key_entirely() -> None:
    dumped = settings_with_key().model_dump()
    assert "api_key" not in dumped
    assert KEY not in json.dumps(dumped)


def test_model_dump_json_excludes_the_key_entirely() -> None:
    """`session.json` is written from a dump like this one (FR-015)."""
    dumped = settings_with_key().model_dump_json()
    assert "api_key" not in dumped
    assert KEY not in dumped


def test_model_dump_still_carries_what_a_session_must_record() -> None:
    dumped = settings_with_key().model_dump(mode="json")
    assert dumped["provider"] == "openai"
    assert dumped["model"] == "gpt-5.6"
    assert dumped["effort"] == DEFAULT_EFFORT
    assert dumped["key_source"] == "settings"


def test_repr_and_str_redact_the_key() -> None:
    settings = settings_with_key()
    assert KEY not in repr(settings)
    assert KEY not in str(settings)


def test_the_key_is_absent_from_a_formatted_exception_carrying_the_settings() -> None:
    """The realistic leak: an SDK error whose message interpolates the config it got."""
    settings = settings_with_key()
    error = RuntimeError(f"client construction failed: {settings!r}")
    assert KEY not in str(error)


def test_secrets_lists_every_value_that_must_never_be_printed() -> None:
    assert settings_with_key().secrets == (KEY,)
    assert ProviderSettings(provider=ProviderName.FAKE, model="fake-scripted").secrets == ()


# --- redact ---------------------------------------------------------------------


def test_redact_masks_a_single_secret() -> None:
    assert redact(f"Authorization: Bearer {KEY}", [KEY]) == f"Authorization: Bearer {MASK}"


def test_redact_masks_every_occurrence() -> None:
    text = f"{KEY} then {KEY}"
    assert redact(text, [KEY]) == f"{MASK} then {MASK}"


def test_redact_masks_every_configured_key() -> None:
    text = f"openai={KEY} google={GOOGLE_KEY} gemini={GEMINI_KEY}"
    masked = redact(text, [KEY, GOOGLE_KEY, GEMINI_KEY])
    for secret in (KEY, GOOGLE_KEY, GEMINI_KEY):
        assert secret not in masked
    assert masked == f"openai={MASK} google={MASK} gemini={MASK}"


def test_redact_masks_an_embedded_secret_with_no_delimiters() -> None:
    assert redact(f"url=https://x/{KEY}?a=1", [KEY]) == f"url=https://x/{MASK}?a=1"


def test_redact_masks_the_longest_overlapping_secret_whole() -> None:
    """Two configured keys where one contains the other: masking the short one first
    would leave the tail of the long one in the text."""
    short = "abc123def456"
    long = f"{short}-suffix-7890"
    assert redact(f"key={long}", [short, long]) == f"key={MASK}"


def test_redact_masks_a_secret_inside_json_escaped_text() -> None:
    """Error bodies reach the pane as JSON; the key survives `json.dumps` unchanged."""
    body = json.dumps({"error": {"message": f"bad key {KEY}"}})
    assert KEY not in redact(body, [KEY])


def test_redact_leaves_text_without_secrets_alone() -> None:
    assert redact("no secret here", [KEY]) == "no secret here"


def test_redact_with_no_secrets_is_the_identity() -> None:
    assert redact("anything at all", []) == "anything at all"


def test_redact_ignores_empty_and_blank_secrets() -> None:
    """An unset key must not turn every character of the text into a mask."""
    assert redact("hello", ["", "   ", None]) == "hello"


def test_redact_accepts_secretstr_values() -> None:
    assert redact(f"key={KEY}", [SecretStr(KEY)]) == f"key={MASK}"


def test_redact_accepts_a_settings_object_secrets_tuple() -> None:
    settings = settings_with_key()
    assert redact(f"key={KEY}", settings.secrets) == f"key={MASK}"


def test_redact_coerces_a_non_string_subject() -> None:
    """Callers hand it exception objects as often as strings."""
    assert redact(RuntimeError(f"boom {KEY}"), [KEY]) == f"boom {MASK}"


# --- logging redaction ----------------------------------------------------------


class Capture(logging.Handler):
    """Holds the fully formatted line, which is what a log file would receive."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter("%(message)s"))
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def root_capture() -> Any:
    """A handler on the *root* logger, plus a guaranteed restore of the record factory.

    Root is where the SDK loggers' records land: `openai`, `google_genai`, `httpx` and
    `uvicorn` all log through their own loggers and propagate. A fixture that captured on
    a private logger would only ever prove the one case that already worked.
    """
    root = logging.getLogger()
    factory = logging.getLogRecordFactory()
    level = root.level
    capture = Capture()
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    try:
        yield capture
    finally:
        root.removeHandler(capture)
        root.setLevel(level)
        logging.setLogRecordFactory(factory)


def test_configure_logging_redaction_masks_a_key_logged_by_an_sdk_logger(
    root_capture: Capture,
) -> None:
    """The case the install exists for: `openai`'s own logger, not the one we installed on.

    A `logging.Filter` on the root logger cannot do this - `Logger.callHandlers` walks the
    ancestors and runs their *handlers* without re-running their *filters* - so a filter
    install would let this line through with the key in it.
    """
    configure_logging_redaction([KEY])
    sdk = logging.getLogger("openai")
    assert sdk.propagate, "the SDK loggers reach root by propagation, not by a handler"
    sdk.error("auth failed for %s", KEY)
    assert root_capture.lines == [f"auth failed for {MASK}"]


@pytest.mark.parametrize("name", ["openai", "google_genai", "httpx", "uvicorn.error"])
def test_configure_logging_redaction_masks_every_sdk_logger_named_in_the_module(
    name: str, root_capture: Capture
) -> None:
    configure_logging_redaction([KEY])
    logging.getLogger(name).warning("request with key=%s failed", KEY)
    assert root_capture.lines == [f"request with key={MASK} failed"]


def test_configure_logging_redaction_masks_for_a_handler_added_afterwards(
    root_capture: Capture,
) -> None:
    """Handlers are configured whenever the app feels like it; order must not matter."""
    configure_logging_redaction([KEY])
    late = Capture()
    logging.getLogger().addHandler(late)
    try:
        logging.getLogger("openai").error("key %s", KEY)
    finally:
        logging.getLogger().removeHandler(late)
    assert late.lines == [f"key {MASK}"]


def test_configure_logging_redaction_masks_a_logged_key(root_capture: Capture) -> None:
    configure_logging_redaction([KEY])
    logging.getLogger("swreview.test.redaction").warning("calling with %s", KEY)
    assert root_capture.lines == [f"calling with {MASK}"]


def test_configure_logging_redaction_masks_a_key_in_the_format_string(
    root_capture: Capture,
) -> None:
    configure_logging_redaction([KEY])
    logging.getLogger("swreview.test.redaction").error(f"raw key {KEY} in the message")
    assert root_capture.lines == [f"raw key {MASK} in the message"]


def test_configure_logging_redaction_masks_a_key_in_a_traceback(
    root_capture: Capture,
) -> None:
    """SDK exceptions are the likeliest carrier: the key is in the request they echo.

    The default `logging.Formatter` appends the traceback to the line, so the assertion
    is over exactly the text a log file would hold.
    """
    configure_logging_redaction([KEY])
    logger = logging.getLogger("openai")
    try:
        raise RuntimeError(f"auth failed for {KEY}")
    except RuntimeError:
        logger.exception("provider call failed")
    assert root_capture.lines
    assert KEY not in "\n".join(root_capture.lines)
    assert MASK in "\n".join(root_capture.lines)


def test_configure_logging_redaction_leaves_clean_lines_untouched(
    root_capture: Capture,
) -> None:
    configure_logging_redaction([KEY])
    logging.getLogger("swreview.test.redaction").info("step %d of %d", 2, 5)
    assert root_capture.lines == ["step 2 of 5"]


def test_configure_logging_redaction_survives_a_broken_format_string() -> None:
    """A mis-formatted line is logging's own error to report; the key still goes.

    The factory is called directly because *emitting* such a record makes every handler
    raise at format time - behaviour this install deliberately leaves alone. What it owes
    here is that it neither raises itself nor lets the key through.
    """
    install = configure_logging_redaction([KEY])
    try:
        record = logging.getLogRecordFactory()(
            "openai", logging.ERROR, __file__, 1, f"too few args {KEY} %s %s", ("one",), None
        )
    finally:
        install.remove()
    assert KEY not in str(record.msg)
    assert MASK in str(record.msg)
    assert record.args == ("one",), "a broken line keeps its args for logging to report on"


def test_configure_logging_redaction_returns_a_removable_install(
    root_capture: Capture,
) -> None:
    """The pane restarts the backend when the key changes; the old install must come off."""
    install = configure_logging_redaction([KEY])
    logging.getLogger("openai").info(KEY)
    install.remove()
    logging.getLogger("openai").info("after removal")
    assert root_capture.lines == [MASK, "after removal"]
    assert logging.getLogRecordFactory() is not install


def test_removing_an_install_that_is_no_longer_the_factory_masks_nothing_further(
    root_capture: Capture,
) -> None:
    """Removal out of order must not tear a later install off the chain."""
    outer = configure_logging_redaction([KEY])
    inner = configure_logging_redaction([ENV_KEY])
    outer.remove()
    logging.getLogger("openai").info("%s and %s", KEY, ENV_KEY)
    assert logging.getLogRecordFactory() is inner
    assert root_capture.lines == [f"{KEY} and {MASK}"]


def test_configure_logging_redaction_accepts_settings_secrets(
    root_capture: Capture,
) -> None:
    configure_logging_redaction(settings_with_key().secrets)
    logging.getLogger("openai").info("key is %s", KEY)
    assert root_capture.lines == [f"key is {MASK}"]


def test_configure_logging_redaction_with_no_secrets_still_installs(
    root_capture: Capture,
) -> None:
    """A keyless (fake-provider) run must not take a different logging path."""
    install = configure_logging_redaction([])
    assert logging.getLogRecordFactory() is install
    logging.getLogger("openai").info("nothing to hide")
    assert root_capture.lines == ["nothing to hide"]


def test_the_redacting_filter_still_masks_records_of_the_logger_it_is_on() -> None:
    """The per-logger tool stays public; it is just not what the process-wide install uses."""
    logger = logging.getLogger("swreview.test.filter")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    capture = Capture()
    logger.addHandler(capture)
    log_filter = RedactingFilter([KEY])
    logger.addFilter(log_filter)
    try:
        logger.warning("calling with %s", KEY)
    finally:
        logger.handlers.clear()
        logger.filters.clear()
    assert capture.lines == [f"calling with {MASK}"]
