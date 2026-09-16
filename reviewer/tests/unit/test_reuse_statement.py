"""Reuse is stated in three places, never silent (T091, data-model.md 9.5).

Lever 9 copies an earlier run's `package.json` instead of dumping. The package that arrives
is then, in every other respect, an ordinary package - which is exactly why a reader has to
be told: a finding dated today, drawn from evidence extracted last Tuesday, is a different
claim from the same finding drawn from evidence extracted now.

So the fact is written where each of the three readers looks:

- on the **package**, as `reused_from` and `reused_at`, written by the extractor (schema
  1.3.0), which is the only place that knows;
- in **`session.json`**, mirrored off the package by `new_session`, which is what an
  engineer reads back weeks later;
- in the **report header**, beside the provider and the retry line, which is the first
  screen anyone sees.

The pane's status line is the fourth, and it is the extractor's own: `PackageReuse.StatusLine`
in C#.

Nothing here is on by default. A freshly dumped package has `reused_from = None`, the
session mirrors the `None`, and the report renders exactly as it did before this feature -
which is asserted, because the feature 001-003 goldens depend on it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swreview.report.markdown import render_report
from swreview.report.session import ReviewSession, load_session, save_session
from swreview.tools.context import new_session
from tests.support.packages import build_package

REUSED_FROM = "20260912-120000-cover-assy"
REUSED_AT = datetime(2026, 9, 12, 15, 0, 0, tzinfo=UTC)


def reused_package() -> object:
    return build_package(reused_from=REUSED_FROM, reused_at=REUSED_AT)


# --- the package ---------------------------------------------------------------------


def test_a_dumped_package_says_it_was_not_reused() -> None:
    package = build_package()

    assert package.reused_from is None
    assert package.reused_at is None


def test_a_reused_package_names_the_folder_and_the_moment() -> None:
    package = build_package(reused_from=REUSED_FROM, reused_at=REUSED_AT)

    assert package.reused_from == REUSED_FROM
    assert package.reused_at == REUSED_AT


# --- session.json ---------------------------------------------------------------------


def test_the_session_mirrors_the_packages_reuse(tmp_path) -> None:  # type: ignore[no-untyped-def]
    session = new_session(build_package(reused_from=REUSED_FROM, reused_at=REUSED_AT))

    assert session.reused_from == REUSED_FROM

    written = save_session(session, tmp_path / "session.json")

    assert load_session(written).reused_from == REUSED_FROM


def test_a_session_over_a_dumped_package_carries_no_reuse() -> None:
    assert new_session(build_package()).reused_from is None


def test_a_session_written_before_the_member_still_loads(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Optional, like `provider_info` and `retry_of` before it: a feature 001 session has no
    such member and must keep loading."""
    session = new_session(build_package())
    payload = session.model_dump(mode="json")
    payload.pop("reused_from")

    assert ReviewSession.model_validate(payload).reused_from is None


# --- the report header ------------------------------------------------------------------


def report(session: ReviewSession) -> str:
    session.ended_at = REUSED_AT
    return render_report(session)


def test_the_report_header_states_the_reuse() -> None:
    lines = report(new_session(build_package(reused_from=REUSED_FROM, reused_at=REUSED_AT)))

    assert f"- Evidence reused from run: {REUSED_FROM}" in lines


def test_a_report_over_a_dumped_package_is_unchanged() -> None:
    """The line appears only when there is something to say, which is what keeps a flag-off
    run rendering byte for byte as it did before lever 9 existed."""
    assert "reused" not in report(new_session(build_package()))
