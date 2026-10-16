"""Price recorded rounds using the served model and a sourced, dated table."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from swreview.agent import providers
from swreview.agent.providers import ProviderName, TokenUsage
from swreview.benchmark import served

PRICES_FILE = Path(__file__).with_name("prices.yaml")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Price(_StrictModel):
    """One price with the public source and the day it was read."""

    price: float = Field(ge=0)
    source: str = Field(min_length=1)
    date: Date


class PriceEntry(_StrictModel):
    """Three prices for a served model, optionally limited to short-context input."""

    provider: str
    model: str
    input: Price
    cached_input: Price
    output: Price
    short_context_max_input_tokens: int | None = Field(default=None, ge=1, strict=True)


class PriceTable(_StrictModel):
    """A versioned table, loaded only when a caller asks for it."""

    prices_version: int
    currency: str
    per_tokens: int = Field(gt=0)
    models: list[PriceEntry]


def load_prices(path: Path = PRICES_FILE) -> PriceTable:
    """Read YAML, preserving dates, and refuse unknown fields at every level."""
    with path.open(encoding="utf-8") as stream:
        return PriceTable.model_validate(yaml.safe_load(stream))


def price_entry(table: PriceTable, provider: ProviderName | str, model: str) -> PriceEntry | None:
    """Find the entry whose base id covers this provider's served model."""
    return next(
        (
            entry
            for entry in table.models
            if entry.provider == provider and served.aliases(provider, entry.model, model)
        ),
        None,
    )


@dataclass(frozen=True)
class RoundFacts:
    """One usage event, beside the requested and reported model ids."""

    usage: TokenUsage
    provider: str
    model: str
    served_model: str | None = None
    retries: int | None = None


class Cost(_StrictModel):
    """An unrounded amount or the distinct reasons that it is unknown."""

    amount: float | None
    missing: list[str]
    basis: list[str]
    synthetic: bool


SYNTHETIC_COST = Cost(amount=None, missing=[], basis=[], synthetic=True)
"""Oracle, null and scripted reviews have no monetary price (FR-042)."""


_OPENAI_ADDENDS = ("input_tokens", "output_tokens")
_GEMINI_ADDENDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "tool_result_input_tokens",
)


def price_rounds(rounds: Sequence[RoundFacts], *, table: PriceTable) -> Cost:
    """Price every round; any unknown round makes the whole amount unknown."""
    missing: list[str] = []
    basis: list[str] = []
    numerator = 0.0
    synthetic = bool(rounds) and all(round_.provider == ProviderName.FAKE for round_ in rounds)
    if synthetic:
        return SYNTHETIC_COST
    if not rounds:
        missing.append("no usage")

    for round_ in rounds:
        if round_.provider == ProviderName.FAKE:
            continue
        usage = round_.usage
        if round_.provider == ProviderName.OPENAI and usage.cache_write_tokens:
            basis.append("cache-write tokens counted, not priced")
        if all(value is None for name, value in usage if name != "latency_s"):
            missing.append("no usage")
            continue
        if round_.served_model is None:
            missing.append("responding model not reported")
            continue
        entry = price_entry(table, round_.provider, round_.served_model)
        if entry is None:
            missing.append(f"{round_.served_model} has no price")
            continue
        if (
            entry.short_context_max_input_tokens is not None
            and usage.input_tokens is not None
            and usage.input_tokens > entry.short_context_max_input_tokens
        ):
            missing.append(f"{round_.served_model}: long-context tier, not priced")
            continue

        if round_.provider == ProviderName.OPENAI:
            required = _OPENAI_ADDENDS
            if providers.CACHED_SHARE_PUBLISHABLE:
                required += ("cached_input_tokens",)
            else:
                basis.append("cached input priced as uncached: containment unverified (probe L1)")
            absent = [name for name in required if getattr(usage, name) is None]
            if absent:
                missing.extend(f"{name} not reported" for name in absent)
                continue
            cached = usage.cached_input_tokens if providers.CACHED_SHARE_PUBLISHABLE else 0
            numerator += (
                (usage.input_tokens - cached) * entry.input.price
                + cached * entry.cached_input.price
                + usage.output_tokens * entry.output.price
            )
        elif round_.provider == ProviderName.GEMINI:
            counts = {name: getattr(usage, name) for name in _GEMINI_ADDENDS}
            absent = [name for name, value in counts.items() if value is None]
            reported_sum = sum(value for value in counts.values() if value is not None)
            if absent and usage.total_tokens != reported_sum:
                missing.extend(f"{name} not reported" for name in absent)
                continue
            cached = usage.cached_input_tokens
            if cached is None:
                basis.append("cached input not reported: all input priced as uncached")
                cached = 0
            numerator += (
                ((usage.input_tokens or 0) - cached) * entry.input.price
                + cached * entry.cached_input.price
                + (usage.tool_result_input_tokens or 0) * entry.input.price
                + ((usage.output_tokens or 0) + (usage.reasoning_tokens or 0)) * entry.output.price
            )

    return Cost(
        amount=None if missing or synthetic else numerator / table.per_tokens,
        missing=list(dict.fromkeys(missing)),
        basis=list(dict.fromkeys(basis)),
        synthetic=synthetic,
    )
