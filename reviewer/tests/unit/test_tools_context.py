"""Unit tests for the model a tool context's session records (T023).

`tools/context.py` no longer holds a model constant: feature 001's `DEFAULT_MODEL` there
is what wrote a retired vendor's id into `session.json`, and the id a session records when
nobody chose one now comes from `agent/settings.py` (FR-026). Every `check` subcommand,
every tool test and every golden fixture builds a context without passing a model, so that
fallback is what most session records in this product are stamped with - and no other test
exercises it, because the CLI review path always passes a model explicitly.

The expected value is imported rather than spelled out, so these assertions track the
single source of truth instead of restating `gpt-5.6` in a fourth place.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from swreview.agent.settings import DEFAULT_PROVIDER, default_model
from swreview.ir.loader import LoadedPackage
from swreview.ir.models import EvidencePackage
from swreview.tools.context import build_context, context_for, new_session

MakePackage = Callable[..., EvidencePackage]

CHOSEN_MODEL = "gemini-3.5-flash"
"""Any id that is not the default: these tests assert *which* id wins, not what it is."""


def test_new_session_without_a_model_records_the_default_providers_default(
    make_package: MakePackage,
) -> None:
    assert new_session(make_package()).model == default_model(DEFAULT_PROVIDER)


def test_new_session_with_a_model_records_that_model(make_package: MakePackage) -> None:
    assert new_session(make_package(), CHOSEN_MODEL).model == CHOSEN_MODEL


def test_build_context_without_a_model_records_the_default_providers_default(
    make_package: MakePackage, tmp_path: Path
) -> None:
    loaded = LoadedPackage(package=make_package(), base_dir=tmp_path)

    context = build_context(loaded)

    assert context.session is not None
    assert context.session.model == default_model(DEFAULT_PROVIDER)


def test_build_context_with_a_model_records_that_model(
    make_package: MakePackage, tmp_path: Path
) -> None:
    loaded = LoadedPackage(package=make_package(), base_dir=tmp_path)

    context = build_context(loaded, model=CHOSEN_MODEL)

    assert context.session is not None
    assert context.session.model == CHOSEN_MODEL


def test_context_for_without_a_model_records_the_default_providers_default(
    make_package: MakePackage,
) -> None:
    context = context_for(make_package())

    assert context.session is not None
    assert context.session.model == default_model(DEFAULT_PROVIDER)


def test_context_for_with_a_model_records_that_model(make_package: MakePackage) -> None:
    context = context_for(make_package(), model=CHOSEN_MODEL)

    assert context.session is not None
    assert context.session.model == CHOSEN_MODEL
