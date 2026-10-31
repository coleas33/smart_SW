"""Per-round pricing against fictional tables and T186's sourced price table."""

from __future__ import annotations

import runpy
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import respx
import yaml
from pydantic import ValidationError

from swreview.agent import providers
from swreview.agent.providers import ProviderName, TokenUsage, usage_from_body
from tests.support.usage import (
    GEMINI_CACHED_CONTENT_TOKENS,
    GEMINI_CANDIDATES_TOKENS,
    GEMINI_PROMPT_TOKENS,
    GEMINI_THOUGHTS_TOKENS,
    GEMINI_TOOL_USE_PROMPT_TOKENS,
    OPENAI_CACHED_TOKENS,
    OPENAI_INPUT_TOKENS,
    OPENAI_OUTPUT_TOKENS,
    openai_usage,
)
from tests.unit.test_benchmark_attempts import driver_sleeps as driver_sleeps
from tests.unit.test_gemini_provider import FakeTool
from tests.unit.test_openai_provider import (
    RESPONSES_URL,
    completed,
    function_call_item,
    make_provider,
    message_item,
    stream_response,
)
from tests.unit.test_openai_provider import run as run_openai

if TYPE_CHECKING:
    from swreview.benchmark.prices import PriceTable, RoundFacts

OPENAI_MODEL = "fict-model-a"
GEMINI_MODEL = "fict-model-b"
# Owner decision 102A: the requested OpenAI default resolves to these served variants.
OPENAI_DEFAULT_VARIANTS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
INPUT_RATE, CACHED_RATE, OUTPUT_RATE = 2.37, 0.61, 11.43
PER_TOKENS = 1_000_000
UNCACHED_BASIS = "cached input priced as uncached: containment unverified (probe L1)"
CACHE_WRITE_BASIS = "cache-write tokens counted, not priced"
MISSING_CACHE_BASIS = "cached input not reported: all input priced as uncached"
GEMINI_ADDENDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "tool_result_input_tokens",
)


def _table_data() -> dict[str, Any]:
    return {
        "prices_version": 1,
        "currency": "USD",
        "per_tokens": PER_TOKENS,
        "models": [
            {
                "provider": provider,
                "model": model,
                **{
                    name: {
                        "price": rate,
                        "source": f"https://example.test/{provider}/pricing",
                        "date": date(2026, 10, 1),
                    }
                    for name, rate in zip(
                        ("input", "cached_input", "output"),
                        (INPUT_RATE, CACHED_RATE, OUTPUT_RATE),
                        strict=True,
                    )
                },
            }
            for provider, model in (("openai", OPENAI_MODEL), ("gemini", GEMINI_MODEL))
        ],
    }


def _table(tmp_path: Path, *, short_context_max_input_tokens: int | None = None) -> PriceTable:
    from swreview.benchmark.prices import load_prices

    data = _table_data()
    if short_context_max_input_tokens is not None:
        for entry in data["models"]:
            entry["short_context_max_input_tokens"] = short_context_max_input_tokens
    path = tmp_path / "fictional-prices.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_prices(path)


def _round(provider: str = "openai", **updates: Any) -> RoundFacts:
    from swreview.benchmark.prices import RoundFacts

    if provider == "gemini":
        counts = {
            "input_tokens": GEMINI_PROMPT_TOKENS,
            "cached_input_tokens": GEMINI_CACHED_CONTENT_TOKENS,
            "cache_write_tokens": None,
            "output_tokens": GEMINI_CANDIDATES_TOKENS,
            "reasoning_tokens": GEMINI_THOUGHTS_TOKENS,
            "tool_result_input_tokens": GEMINI_TOOL_USE_PROMPT_TOKENS,
            "total_tokens": sum(
                (
                    GEMINI_PROMPT_TOKENS,
                    GEMINI_CANDIDATES_TOKENS,
                    GEMINI_THOUGHTS_TOKENS,
                    GEMINI_TOOL_USE_PROMPT_TOKENS,
                )
            ),
        }
        model = GEMINI_MODEL
    else:
        counts = {
            "input_tokens": OPENAI_INPUT_TOKENS,
            "cached_input_tokens": OPENAI_CACHED_TOKENS,
            "cache_write_tokens": None,
            "output_tokens": OPENAI_OUTPUT_TOKENS,
            "reasoning_tokens": 448,
            "tool_result_input_tokens": None,
            "total_tokens": OPENAI_INPUT_TOKENS + OPENAI_OUTPUT_TOKENS,
        }
        model = OPENAI_MODEL
    counts.update(updates)
    return RoundFacts(
        usage=TokenUsage(**counts, latency_s=0.17),
        provider=provider,
        model=model,
        served_model=model,
        retries=None,
    )


def test_the_committed_table_loads_and_every_price_has_a_source_and_a_date() -> None:
    from swreview.benchmark.prices import PRICES_FILE, load_prices

    table = load_prices()
    assert PRICES_FILE == Path(providers.__file__).parents[2] / "benchmark" / "prices.yaml"
    assert table.prices_version == 1
    assert table.currency == "USD"
    assert table.per_tokens == PER_TOKENS
    assert [(entry.provider, entry.model) for entry in table.models] == [
        ("openai", model) for model in OPENAI_DEFAULT_VARIANTS
    ]
    for entry, rates in zip(
        table.models, ((4.00, 0.40, 20.00), (2.00, 0.20, 12.00), (0.20, 0.02, 1.20)), strict=True
    ):
        assert entry.short_context_max_input_tokens == 272_000
        for price, rate in zip((entry.input, entry.cached_input, entry.output), rates, strict=True):
            assert price.price == rate
            assert price.source == "https://developers.openai.com/api/docs/pricing"
            assert price.date == date(2026, 10, 15)


def test_every_default_non_scripted_model_has_an_entry() -> None:
    """102A prices the OpenAI default's served variants; 94A defers Gemini's default."""
    from swreview.agent.settings import DEFAULT_MODELS
    from swreview.benchmark.prices import load_prices, price_entry

    table = load_prices()
    default = DEFAULT_MODELS[ProviderName.OPENAI]
    assert default == "gpt-5.6"
    assert price_entry(table, ProviderName.OPENAI, default) is None
    for model in OPENAI_DEFAULT_VARIANTS:
        entry = price_entry(table, ProviderName.OPENAI, model)
        assert entry is not None
        assert entry.model == model


def test_a_paid_test_run_names_a_priced_variant_never_an_alias_of_the_default() -> None:
    """174A: the served variants are not aliases of `gpt-5.6`, so a paid test run names one."""
    from swreview.agent.settings import DEFAULT_MODELS, PAID_TEST_MODEL
    from swreview.benchmark.prices import load_prices, price_entry
    from swreview.benchmark.served import aliases

    assert PAID_TEST_MODEL == "gpt-5.6-sol"
    entry = price_entry(load_prices(), ProviderName.OPENAI, PAID_TEST_MODEL)
    assert entry is not None
    assert entry.model == PAID_TEST_MODEL
    for variant in OPENAI_DEFAULT_VARIANTS:
        assert not aliases(ProviderName.OPENAI, DEFAULT_MODELS[ProviderName.OPENAI], variant)


def test_the_live_attempt_runs_the_paid_test_model_unless_one_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """174A: T171's live test defaults to `gpt-5.6-sol`; `SWREVIEW_LIVE_MODEL` still overrides."""
    live = Path(__file__).resolve().parents[1] / "live" / "test_benchmark_live_attempt.py"
    monkeypatch.delenv("SWREVIEW_LIVE_MODEL", raising=False)
    assert runpy.run_path(str(live))["MODEL"] == "gpt-5.6-sol"
    monkeypatch.setenv("SWREVIEW_LIVE_MODEL", "fict-model-a")
    assert runpy.run_path(str(live))["MODEL"] == "fict-model-a"


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_a_round_above_the_short_context_threshold_is_cost_unknown_naming_the_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    from swreview.benchmark.prices import price_rounds

    monkeypatch.setattr(providers, "CACHED_SHARE_PUBLISHABLE", False)
    threshold = 20_017
    table = _table(tmp_path, short_context_max_input_tokens=threshold)
    unlimited = _table(tmp_path)
    below = _round(provider, input_tokens=threshold - 1)
    at = _round(provider, input_tokens=threshold)
    above = _round(provider, input_tokens=threshold + 1)
    for round_ in (below, at):
        cost = price_rounds([round_], table=table)
        assert cost.amount == price_rounds([round_], table=unlimited).amount
        assert cost.amount is not None
        assert cost.missing == []
    for rounds in ([above], [above, above], [below, above, at, above], [above, at, below]):
        cost = price_rounds(rounds, table=table)
        assert cost.amount is None
        assert cost.missing == [f"{above.served_model}: long-context tier, not priced"]
    snapshot = replace(
        above, served_model=above.model + ("-2026-10-01" if provider == "openai" else "-017")
    )
    assert price_rounds([snapshot], table=table).missing == [
        f"{snapshot.served_model}: long-context tier, not priced"
    ]
    missing_input = price_rounds([_round(provider, input_tokens=None)], table=table)
    assert missing_input.amount is None
    assert missing_input.missing == ["input_tokens not reported"]


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_an_entry_without_a_threshold_prices_every_round(tmp_path: Path, provider: str) -> None:
    from swreview.benchmark.prices import price_rounds

    table = _table(tmp_path)
    assert all(entry.short_context_max_input_tokens is None for entry in table.models)
    rounds = [_round(provider, input_tokens=count) for count in (272_000, 272_001, 1_000_003)]
    costs = [price_rounds([round_], table=table) for round_ in rounds]
    assert all(cost.amount is not None and cost.missing == [] for cost in costs)
    combined = price_rounds(rounds, table=table)
    assert combined.amount == pytest.approx(sum(cost.amount for cost in costs))
    assert combined.missing == []


def test_openai_cached_input_is_priced_as_uncached_until_probe_l1_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swreview.benchmark.prices import price_rounds

    table, round_ = _table(tmp_path), _round()
    monkeypatch.setattr(providers, "CACHED_SHARE_PUBLISHABLE", False)
    cost = price_rounds([round_, round_], table=table)
    assert cost.amount == pytest.approx(
        2 * (OPENAI_INPUT_TOKENS * INPUT_RATE + OPENAI_OUTPUT_TOKENS * OUTPUT_RATE) / PER_TOKENS
    )
    assert cost.missing == []
    assert cost.basis == [UNCACHED_BASIS]
    assert not cost.synthetic
    assert price_rounds([_round(cached_input_tokens=None)], table=table).amount is not None

    monkeypatch.setattr(providers, "CACHED_SHARE_PUBLISHABLE", True)
    verified = price_rounds([round_], table=table)
    assert verified.amount == pytest.approx(
        (
            (OPENAI_INPUT_TOKENS - OPENAI_CACHED_TOKENS) * INPUT_RATE
            + OPENAI_CACHED_TOKENS * CACHED_RATE
            + OPENAI_OUTPUT_TOKENS * OUTPUT_RATE
        )
        / PER_TOKENS
    )
    assert UNCACHED_BASIS not in verified.basis
    unknown = price_rounds([_round(cached_input_tokens=None)], table=table)
    assert unknown.amount is None
    assert unknown.missing == ["cached_input_tokens not reported"]


@pytest.mark.parametrize("cached", [GEMINI_CACHED_CONTENT_TOKENS, None])
def test_gemini_cached_input_is_priced_apart(tmp_path: Path, cached: int | None) -> None:
    from swreview.benchmark.prices import price_rounds

    round_ = _round("gemini", cached_input_tokens=cached)
    cost = price_rounds([round_], table=_table(tmp_path))
    assert cost.amount == pytest.approx(
        (
            (GEMINI_PROMPT_TOKENS - (cached or 0)) * INPUT_RATE
            + (cached or 0) * CACHED_RATE
            + GEMINI_TOOL_USE_PROMPT_TOKENS * INPUT_RATE
            + (GEMINI_CANDIDATES_TOKENS + GEMINI_THOUGHTS_TOKENS) * OUTPUT_RATE
        )
        / PER_TOKENS
    )
    assert cost.missing == []
    assert (MISSING_CACHE_BASIS in cost.basis) is (cached is None)


def test_gemini_thoughts_and_tool_use_are_added(tmp_path: Path) -> None:
    from swreview.benchmark.prices import price_rounds

    table = _table(tmp_path)
    complete = price_rounds([_round("gemini")], table=table)
    no_extras = price_rounds(
        [_round("gemini", reasoning_tokens=0, tool_result_input_tokens=0, total_tokens=None)],
        table=table,
    )
    assert complete.amount - no_extras.amount == pytest.approx(
        (GEMINI_THOUGHTS_TOKENS * OUTPUT_RATE + GEMINI_TOOL_USE_PROMPT_TOKENS * INPUT_RATE)
        / PER_TOKENS
    )


@pytest.mark.parametrize("omitted", [*((name,) for name in GEMINI_ADDENDS), GEMINI_ADDENDS])
@pytest.mark.parametrize("total", ["agrees", "disagrees", "absent"])
def test_a_missing_gemini_addend_reads_zero_only_when_the_total_agrees(
    tmp_path: Path, omitted: tuple[str, ...], total: str
) -> None:
    from swreview.benchmark.prices import price_rounds

    table = _table(tmp_path)
    changes = dict.fromkeys(omitted)
    if "input_tokens" in omitted:
        changes["cached_input_tokens"] = None
    round_ = _round("gemini", **changes)
    reported_sum = sum(getattr(round_.usage, name) or 0 for name in GEMINI_ADDENDS)
    changes["total_tokens"] = {
        "agrees": reported_sum,
        "disagrees": reported_sum + 17,
        "absent": None,
    }[total]
    round_ = _round("gemini", **changes)
    cost = price_rounds([round_, round_], table=table)
    if total == "agrees":
        zeros = _round("gemini", **{**changes, **dict.fromkeys(omitted, 0)})
        assert cost.amount == price_rounds([zeros, zeros], table=table).amount
        assert cost.missing == []
    else:
        assert cost.amount is None
        expected = (
            ["no usage"]
            if set(omitted) == set(GEMINI_ADDENDS) and total == "absent"
            else [f"{name} not reported" for name in GEMINI_ADDENDS if name in omitted]
        )
        assert cost.missing == expected


@pytest.mark.parametrize("count", [1_803, 0, None])
def test_a_cache_write_count_is_named_in_the_basis_and_never_priced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int | None
) -> None:
    from swreview.benchmark.prices import price_rounds

    monkeypatch.setattr(providers, "CACHED_SHARE_PUBLISHABLE", False)
    table = _table(tmp_path)
    cost = price_rounds([_round(cache_write_tokens=count)], table=table)
    assert cost.amount == price_rounds([_round()], table=table).amount
    assert (CACHE_WRITE_BASIS in cost.basis) is bool(count)
    for model in (None, "fict-unpriced"):
        unknown = price_rounds(
            [replace(_round(cache_write_tokens=count), served_model=model)], table=table
        )
        assert unknown.amount is None
        assert (CACHE_WRITE_BASIS in unknown.basis) is bool(count)


@pytest.mark.parametrize(
    "location",
    [
        "table",
        "entry",
        "price",
        "fourth",
        "tiers",
        "threshold-zero",
        "threshold-negative",
        "threshold-bool",
        "threshold-false",
        "threshold-string",
        "threshold-float",
        "threshold-fraction",
        "threshold-list",
        "threshold-mapping",
    ],
)
def test_the_table_refuses_a_fourth_price_field_and_a_tiers_block(
    tmp_path: Path, location: str
) -> None:
    from swreview.benchmark.prices import load_prices

    data = deepcopy(_table_data())
    entry = data["models"][0]
    path = tmp_path / "invalid-prices.yaml"
    for threshold in (1, 20_017, None):
        entry["short_context_max_input_tokens"] = threshold
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        assert load_prices(path).models[0].short_context_max_input_tokens == threshold

    expected_error = "extra_forbidden"
    if location == "table":
        data["unexpected"] = True
    elif location == "entry":
        entry["unexpected"] = True
    elif location == "price":
        entry["input"]["unexpected"] = True
    elif location == "fourth":
        entry["cache_write"] = deepcopy(entry["input"])
    elif location == "tiers":
        entry["tiers"] = [{"over_tokens": 2_017, "input": deepcopy(entry["input"])}]
    else:
        entry["short_context_max_input_tokens"] = {
            "threshold-zero": 0,
            "threshold-negative": -1,
            "threshold-bool": True,
            "threshold-false": False,
            "threshold-string": "20017",
            "threshold-float": 20_017.0,
            "threshold-fraction": 1.5,
            "threshold-list": [],
            "threshold-mapping": {},
        }[location]
        expected_error = (
            "greater_than_equal"
            if location in ("threshold-zero", "threshold-negative")
            else "int_type"
        )
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        load_prices(path)
    assert expected_error in {error["type"] for error in caught.value.errors()}


def test_a_model_without_an_entry_is_cost_unknown_naming_it(tmp_path: Path) -> None:
    from swreview.benchmark.prices import price_entry, price_rounds

    table = _table(tmp_path)
    unknown = replace(_round(), served_model="fict-unpriced-a")
    missing_served = replace(_round(), served_model=None)
    other = replace(_round(), served_model="fict-unpriced-b")
    cost = price_rounds([unknown, missing_served, unknown, other, missing_served], table=table)
    assert cost.amount is None
    assert cost.missing == [
        "fict-unpriced-a has no price",
        "responding model not reported",
        "fict-unpriced-b has no price",
    ]
    assert price_entry(table, "gemini", OPENAI_MODEL) is None
    assert price_entry(table, "unknown-provider", OPENAI_MODEL) is None
    assert not cost.synthetic


@pytest.mark.parametrize("with_round", [False, True])
def test_no_usage_is_cost_unknown_never_zero(tmp_path: Path, with_round: bool) -> None:
    from swreview.benchmark.prices import price_rounds

    unknown = _round(**dict.fromkeys(TokenUsage.model_fields.keys() - {"latency_s"}))
    cost = price_rounds([unknown] if with_round else [], table=_table(tmp_path))
    assert cost.amount is None
    assert cost.missing == ["no usage"]
    assert not cost.synthetic


def test_a_served_snapshot_is_priced_by_its_base_model(tmp_path: Path) -> None:
    from swreview.benchmark import served
    from swreview.benchmark.prices import price_entry, price_rounds

    table = _table(tmp_path)
    for provider, suffix in ((ProviderName.OPENAI, "-2024-02-29"), (ProviderName.GEMINI, "-017")):
        for provider_name in (provider, provider.value):
            assert served.aliases(provider_name, "fict.model+a", "fict.model+a")
            assert served.aliases(provider_name, "fict.model+a", "fict.model+a" + suffix)
            for invalid in (
                "fictXmodel+a" + suffix,
                "fict.model+a" + suffix + "x",
                "fict.model+a" + suffix + "\n",
                "prefix-fict.model+a" + suffix,
            ):
                assert not served.aliases(provider_name, "fict.model+a", invalid)
        round_ = _round(provider)
        snapshot = replace(round_, served_model=round_.model + suffix)
        assert price_entry(table, provider, snapshot.served_model) is price_entry(
            table, provider, round_.model
        )
        assert (
            price_rounds([snapshot], table=table).amount
            == price_rounds([round_], table=table).amount
        )
        assert price_rounds([replace(snapshot, model="fict-other-request")], table=table).amount
    for invalid in ("-2026-02-29", "-2026-13-01", "-2026-10-1", "-017", "-0000-01-01"):
        assert not served.aliases("openai", OPENAI_MODEL, OPENAI_MODEL + invalid)
    for invalid in ("-17", "-0017", "-2026-10-01", "-\u0660\u0661\u0667"):
        assert not served.aliases("gemini", GEMINI_MODEL, GEMINI_MODEL + invalid)
    for provider in (ProviderName.FAKE, "fake", "unknown-provider"):
        assert served.aliases(provider, OPENAI_MODEL, OPENAI_MODEL) is (
            provider != "unknown-provider"
        )
        assert not served.aliases(provider, OPENAI_MODEL, OPENAI_MODEL + "-017")
        assert not served.aliases(provider, OPENAI_MODEL, OPENAI_MODEL + "-2026-10-01")
    with pytest.raises(FrozenInstanceError):
        snapshot.model = "fict-mutation"


@pytest.mark.parametrize("reported", [False, True])
def test_scripted_runs_are_synthetic_and_unpriced(tmp_path: Path, reported: bool) -> None:
    from swreview.benchmark.prices import price_rounds

    round_ = (
        _round("fake")
        if reported
        else _round("fake", **dict.fromkeys(TokenUsage.model_fields.keys() - {"latency_s"}))
    )
    cost = price_rounds([replace(round_, served_model=None)], table=_table(tmp_path))
    assert cost.synthetic
    assert cost.amount is None
    assert cost.missing == []
    assert cost.basis == []


@respx.mock
def test_recorded_responses_price_every_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """94A keeps the OpenAI recorded case; Gemini's served model is deferred."""
    from swreview.benchmark.prices import RoundFacts, price_rounds

    monkeypatch.setattr(providers, "CACHED_SHARE_PUBLISHABLE", False)
    replies = [completed(function_call_item()), completed(message_item("fict answer"))]
    usages = [openai_usage(), openai_usage(input_tokens=13_079, output_tokens=617)]
    for reply, usage in zip(replies, usages, strict=True):
        reply["response"]["model"] = OPENAI_MODEL + "-2026-10-01"
        reply["response"]["usage"] = usage.model_dump()
    respx.post(RESPONSES_URL).mock(side_effect=[stream_response(reply) for reply in replies])
    _, sink = run_openai(make_provider(model=OPENAI_MODEL), tools=[FakeTool("get_component")])
    expected = (
        sum(usage.input_tokens * INPUT_RATE + usage.output_tokens * OUTPUT_RATE for usage in usages)
        / PER_TOKENS
    )
    bodies = sink.bodies("usage")
    assert len(bodies) == 2
    rounds = [
        RoundFacts(
            usage=usage_from_body(body),
            provider=body["provider"],
            model=body["model"],
            served_model=body.get("served_model"),
            retries=body.get("retries"),
        )
        for body in bodies
    ]
    table = _table(tmp_path)
    for round_ in rounds:
        assert round_.served_model
        assert round_.usage.input_tokens > 0
        assert round_.usage.output_tokens > 0
        assert price_rounds([round_], table=table).amount > 0
    cost = price_rounds(rounds, table=table)
    assert cost.amount == pytest.approx(expected)
    assert cost.missing == []
    assert not cost.synthetic


# --- T207: saved run spend, its price sources and synthetic direct reviews -----------------


@pytest.mark.parametrize("unknown", [None, "failed", "kept"])
def test_run_spend_includes_failed_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float],
    unknown: str | None,
) -> None:
    """D2 and 94A: an offline OpenAI adapter prices every failure and only the kept review."""
    from typer.testing import CliRunner

    from swreview import cli
    from swreview.agent import events
    from swreview.agent.providers.fake import (
        FakeProvider,
        ScriptedRound,
        ScriptedToolCall,
        ScriptedTurn,
    )
    from swreview.benchmark import prices, scorecard, sets
    from tests.support.answer_keys import write_key
    from tests.unit.test_benchmark_attempts import (
        TransientError,
        install_driver_providers,
        prepare_driver_set,
    )
    from tests.unit.test_benchmark_resume import resume_command

    class OfflineOpenAI(FakeProvider):
        name = ProviderName.OPENAI

    monkeypatch.setenv("OPENAI_API_KEY", "fict-offline-key")
    monkeypatch.setattr(providers, "CACHED_SHARE_PUBLISHABLE", False)
    prepare_driver_set(tmp_path, ("fict-a", "fict-b"))
    first, second, kept, last = [
        _round(
            input_tokens=count, output_tokens=count // 7, total_tokens=count + count // 7,
        ).usage
        for count in (2_003, 3_011, 5_009, 7_001)
    ]
    call = ScriptedToolCall("list_components")

    def failed(usage: TokenUsage | None) -> ScriptedTurn:
        return ScriptedTurn(
            text="", rounds=(ScriptedRound((call,), usage),),
            served_model=OPENAI_MODEL + "-2026-10-01",
            fails=TransientError("fict exhausted request"),
        )

    install_driver_providers(monkeypatch, [[failed(first)], [failed(second)]], kind=OfflineOpenAI)
    out = tmp_path / "run"
    result = CliRunner().invoke(cli.app, [
        "benchmark", "run", "--set", str(tmp_path / "set.json"), "--out", str(out),
        "--provider", "openai", "--model", OPENAI_MODEL,
    ])
    assert result.exit_code == 1, result.stdout + result.stderr
    install_driver_providers(monkeypatch, [
        [ScriptedTurn(
            text="A fresh successful review.", usage=None if unknown == "kept" else kept,
            served_model=OPENAI_MODEL + "-2026-10-02",
        )],
        [failed(None if unknown == "failed" else last)],
    ], kind=OfflineOpenAI)
    resumed = resume_command(out)
    assert resumed.exit_code == 1, resumed.stdout + resumed.stderr
    keys = tmp_path / "answer_keys"
    for package_id in ("fict-a", "fict-b"):
        write_key(keys, package_id)
    benchmark_set = sets.load_saved_set(out / "benchmark-set.json")
    table = _table(tmp_path)

    def amount(usage: TokenUsage) -> float:
        return (usage.input_tokens * INPUT_RATE + usage.output_tokens * OUTPUT_RATE) / PER_TOKENS

    snapshots: list[tuple[TokenUsage, ...]] = []

    class SpyLedger(events.UsageLedger):
        def rounds(self) -> tuple[TokenUsage, ...]:
            snapshot = super().rounds()
            snapshots.append(snapshot)
            return snapshot

    received: list[TokenUsage] = []
    real_price_rounds = prices.price_rounds

    def price_spy(rounds: Any, *, table: PriceTable) -> Any:
        received.extend(round_.usage for round_ in rounds)
        return real_price_rounds(rounds, table=table)

    monkeypatch.setattr(events, "UsageLedger", SpyLedger)
    monkeypatch.setattr(prices, "price_rounds", price_spy)
    card = scorecard.score_run(out, keys, benchmark_set, prices=table)
    payload = card.model_dump(mode="json", by_alias=True)

    assert [score.package_id for score in card.per_package] == ["fict-a"]
    assert len(snapshots) == 4, "each kept or infrastructure attempt is replayed once"
    ledger_usages = [usage for snapshot in snapshots for usage in snapshot]
    assert received
    assert {id(usage) for usage in received} == {id(usage) for usage in ledger_usages}
    assert all(any(usage is from_ledger for from_ledger in ledger_usages) for usage in received)
    assert sorted(usage.input_tokens for usage in ledger_usages) == sorted([
        first.input_tokens, second.input_tokens,
        *([] if unknown == "kept" else [kept.input_tokens]),
        *([] if unknown == "failed" else [last.input_tokens]),
    ])
    rows = payload["failed_attempts"]
    assert [(row["package_id"], row["attempt"], row["folder"]) for row in rows] == [
        ("fict-a", 1, "attempts/fict-a/1"),
        ("fict-b", 1, "attempts/fict-b/1"),
        ("fict-b", 2, "attempts/fict-b/2"),
    ]
    assert all((out / row["folder"]).is_dir() for row in rows)
    assert all(row["retries"] == 5 for row in rows)
    assert [row["cost"]["amount"] for row in rows[:2]] == pytest.approx([
        amount(first), amount(second),
    ])
    if unknown == "failed":
        assert rows[2]["cost"]["amount"] is None
        assert card.aggregate.failed_attempts_cost.amount is None
        assert any("1 of 3" in reason for reason in card.aggregate.failed_attempts_cost.missing)
    else:
        assert rows[2]["cost"]["amount"] == pytest.approx(amount(last))
        assert card.aggregate.failed_attempts_cost.amount == pytest.approx(
            amount(first) + amount(second) + amount(last),
        )
    if unknown == "kept":
        assert card.per_package[0].cost.amount is None
        assert card.aggregate.cost.amount is None
        assert any("1 of 1" in reason for reason in card.aggregate.cost.missing)
    else:
        assert card.per_package[0].cost.amount == pytest.approx(amount(kept))
        assert card.aggregate.cost.amount == pytest.approx(amount(kept))
    assert payload["unscored_packages"] == [{
        "package_id": "fict-b", "kind": "infrastructure", "class": "provider_error",
        "error_class": "TransientError", "attempts": 2, "folder": "attempts/fict-b/2",
        "graded_items": [],
    }]


@pytest.mark.parametrize("priced", [True, False])
def test_the_scorecard_records_the_price_tables_sources_and_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver_sleeps: list[float], priced: bool,
) -> None:
    """RF-45 and 94A: only the used offline OpenAI entry is copied; scripted is unpriced."""
    from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
    from swreview.benchmark import scorecard
    from tests.support.answer_keys import write_key
    from tests.unit.test_benchmark_attempts import (
        driver_run,
        install_driver_providers,
        prepare_driver_set,
    )

    class OfflineOpenAI(FakeProvider):
        name = ProviderName.OPENAI

    monkeypatch.setattr(providers, "CACHED_SHARE_PUBLISHABLE", False)
    prepared = prepare_driver_set(tmp_path)
    install_driver_providers(monkeypatch, [[ScriptedTurn(
        text="Reviewed.", usage=_round().usage, served_model=OPENAI_MODEL,
    )]], kind=OfflineOpenAI if priced else FakeProvider)
    out = tmp_path / "run"
    driver_run(prepared, out, model=OPENAI_MODEL)
    keys = tmp_path / "answer_keys"
    write_key(keys, "fict-a")
    table = _table(tmp_path)
    card = scorecard.score_run(out, keys, prepared.benchmark_set, prices=table)
    recorded = card.model_dump(mode="json", by_alias=True)["price_table"]

    if priced:
        assert recorded == {
            "prices_version": table.prices_version,
            "models": [{
                "provider": "openai", "model": OPENAI_MODEL,
                **{
                    field: {"source": "https://example.test/openai/pricing", "date": "2026-10-01"}
                    for field in ("input", "cached_input", "output")
                },
            }],
        }
    else:
        assert recorded is None
        assert card.per_package[0].cost.synthetic


@pytest.mark.parametrize("review", ["oracle", "null"])
def test_the_oracle_and_null_reviews_are_synthetic_and_unpriced(
    tmp_path: Path, review: str,
) -> None:
    from swreview.agent import events
    from swreview.agent.checklist import load_checklist
    from swreview.benchmark import prices, scorecard
    from swreview.benchmark.answer_key import load_answer_key
    from swreview.report.summary import load_words
    from tests.support.answer_keys import write_key
    from tests.support.packages import build_package
    from tests.support.scoring_probes import null_review, oracle_review

    package = build_package()
    key = load_answer_key(
        write_key(tmp_path / "answer_keys", "fict-synthetic", known_defects=[{
            "check": "hygiene.revision_present", "component_ids": ["cmp:0001"],
        }]),
        package=package, checklist=load_checklist(), words=load_words(),
    )
    folder = tmp_path / review
    if review == "oracle":
        oracle_review(key, package, folder)
    else:
        null_review(package, folder)
    assert [event.type for event in events.replay_events(events.event_stream(folder))] == [
        "session.started",
    ]

    score = scorecard._score_package(
        folder, package_id=key.package_id, held_out=False, answer_key=key, package=package,
        words=load_words(), run_status={"kind": "completed", "class": None, "stop_reason": None},
        cost=prices.SYNTHETIC_COST, served_models=[],
    )

    assert score.cost.synthetic
    assert score.cost.amount is None
    assert score.cost.missing == []
    assert score.cost == prices.SYNTHETIC_COST
