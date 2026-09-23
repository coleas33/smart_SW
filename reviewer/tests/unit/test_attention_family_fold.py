"""The folded rule family: every modelling-practice finding is one ranking row (feature 008 T031).

Checks first records dozens of `rms.*` findings before the model speaks, and a ranking that
gave each rule its own row would bury the handful of interference and joint findings the
engineer has to judge under seven rows of tree hygiene. `ReviewSession.folded_families`
names the families that fold; `rank()` reads that plain session value and never a setting,
so this module never imports one (FR-014, research R2.21, `contracts/checks-first.md`
section 6).

What is pinned, in the order the contract states it:

- **one row, every member.** Every finding of the family - any status, any severity,
  shared components, waived - is in the one row, its members sorted, its reach the union;
- **the best member lifts it.** The representative is the member whose own key sorts first,
  so a rebuild-breaking member beats a hygiene one and a high-severity member lifts the row;
- **nothing else moves.** The other rows keep their relative order, an unfolded session
  ranks byte-identically, a check folder never folds, and the record's bytes are unchanged
  when nothing folds;
- **the record reproduces.** `rank(load_session(path))` equals what was written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from swreview.findings import Disposition
from swreview.report.attention import (
    FAMILY_TITLES,
    AttentionRow,
    Ranking,
    family_of,
    family_title,
    fold,
    load_policy,
    rank,
    start_here_lines,
)
from swreview.report.attention_record import (
    ATTENTION_FILE_NAME,
    AttentionRecord,
    write_attention_record,
)
from swreview.report.session import ReviewSession, load_session, save_session
from tests.support.attention import (
    CHECK_SESSION_FILE,
    PART_COMPONENT,
    PIN_ONE,
    PIN_TWO,
    REVIEW_SESSION_FILE,
    CoverageSpec,
    FindingSpec,
    build_attention_session,
)

NAMESPACE = UUID("7a1e6d64-1f2b-4c3a-9d5e-000000000008")
FOLDED = ["rms"]


def spec(check: str, **fields: Any) -> FindingSpec:
    fields.setdefault("component_ids", (PART_COMPONENT,))
    fields.setdefault("tool_result_ids", (0,))
    fields.setdefault("coverage_limits", ("measured in the Default configuration only.",))
    return FindingSpec(check=check, **fields)


def session_of(name: str, specs: list[FindingSpec], *, folded: bool = True) -> ReviewSession:
    session = build_attention_session(
        session_id=uuid5(NAMESPACE, name),
        findings=specs,
        coverage=CoverageSpec(),
        steps=("check_rms_part", "check_rms_assembly"),
    )
    return session.model_copy(update={"folded_families": FOLDED if folded else []})


def review(*, folded: bool) -> ReviewSession:
    session = load_session(REVIEW_SESSION_FILE)
    return session.model_copy(update={"folded_families": FOLDED if folded else []})


def family_rows(ranking: Ranking) -> list[AttentionRow]:
    return [row for row in ranking.rows if row.family is not None]


def waived() -> Disposition:
    return Disposition(
        decision="accepted",
        note="the engineer accepted this finding",
        by="engineer@example.com",
        at="2026-09-23T09:00:00+00:00",  # type: ignore[arg-type]
    )


MIXED: list[FindingSpec] = [
    spec("rms.folders.present", status="suspected", severity="low"),
    spec("rms.sketches.fully_defined", status="demonstrated", severity="medium"),
    spec("rms.grouping.all_features_in_a_group", severity="medium", component_ids=(PIN_ONE,)),
    spec("rms.params.global_variables_present", disposition=waived()),
    spec("rms.folders.present", status="suspected", severity="low", component_ids=(PIN_TWO,)),
    spec("interference.static", component_ids=(PIN_ONE, PART_COMPONENT)),
    spec("hole.coaxiality", status="suspected", severity="low", component_ids=(PIN_TWO,)),
]
"""Five `rms.*` findings of four rules - mixed status and severity, two sharing a component,
one waived - beside two findings of other families."""


# --- one row, every member ----------------------------------------------------------------


def test_every_family_finding_is_in_one_row_with_every_id_sorted() -> None:
    session = session_of("mixed", MIXED)
    ranking = rank(session)

    [row] = family_rows(ranking)
    family_ids = sorted(f.id for f in session.findings if f.check.startswith("rms."))
    assert row.member_finding_ids == family_ids
    assert row.family == "rms"
    assert row.check == "rms"
    assert row.rule_count == 4
    assert row.title == "Modelling practice: 5 findings across 4 rules"
    assert row.component_ids == sorted({PART_COMPONENT, PIN_ONE, PIN_TWO})
    assert row.key.check == "rms"


def test_the_family_row_and_the_other_rows_account_for_every_finding_once() -> None:
    session = session_of("mixed", MIXED)
    ranking = rank(session)

    members = [member for row in ranking.rows for member in row.member_finding_ids]
    assert sorted(members) == sorted(f.id for f in session.findings)
    assert len(ranking.rows) == 3


def test_the_title_is_one_function_and_counts_in_english() -> None:
    assert FAMILY_TITLES == {"rms": "Modelling practice"}
    assert family_title("rms", 85, 7) == "Modelling practice: 85 findings across 7 rules"
    assert family_title("rms", 1, 1) == "Modelling practice: 1 finding across 1 rule"
    assert family_title("unknown", 2, 1) == "unknown: 2 findings across 1 rule"


def test_family_of_is_a_prefix_match_on_the_families_named() -> None:
    assert family_of("rms.folders.present", ("rms",)) == "rms"
    assert family_of("rms.folders.present", ()) is None
    assert family_of("rmsx.other", ("rms",)) is None
    assert family_of("interference.static", ("rms",)) is None


# --- the best member lifts it -------------------------------------------------------------


def test_a_rebuild_breaker_member_beats_a_hygiene_one() -> None:
    session = session_of(
        "breaker",
        [
            spec("rms.folders.present", status="suspected", severity="low"),
            spec("rms.sketches.fully_defined"),
        ],
    )
    [row] = family_rows(rank(session))

    breaker = next(f for f in session.findings if f.check == "rms.sketches.fully_defined")
    assert row.finding_id == breaker.id
    assert row.consequence_class == "rebuild_breaker"
    assert row.status == "demonstrated"


def test_a_high_severity_refs_member_lifts_the_row() -> None:
    session = session_of(
        "refs",
        [
            spec("rms.sketches.fully_defined", severity="medium"),
            spec("rms.refs.direction", severity="high"),
        ],
    )
    [row] = family_rows(rank(session))

    high = next(f for f in session.findings if f.check == "rms.refs.direction")
    assert row.finding_id == high.id
    assert row.severity == "high"


def test_an_all_suppressed_family_gives_a_suppressed_row() -> None:
    session = session_of(
        "suppressed",
        [
            spec("rms.folders.present", disposition=waived()),
            spec("rms.sketches.fully_defined", status="checked_within_scope"),
        ],
    )
    [row] = family_rows(rank(session))

    assert row.key.suppressed == 1


# --- nothing else moves -------------------------------------------------------------------


def test_the_other_rows_keep_their_relative_order() -> None:
    folded = rank(review(folded=True))
    unfolded = rank(review(folded=False))

    rest = [row.finding_id for row in folded.rows if row.family is None]
    assert rest == [
        row.finding_id for row in unfolded.rows if not row.check.startswith("rms.")
    ]
    assert len(folded.rows) == 3


def test_without_the_field_the_ranking_is_todays_byte_for_byte() -> None:
    session = load_session(REVIEW_SESSION_FILE)

    assert session.folded_families == []
    assert rank(session).model_dump_json() == rank(review(folded=False)).model_dump_json()
    assert not family_rows(rank(session))
    assert fold(session.findings) == fold(session.findings, load_policy(), ())


def test_the_check_folder_fixture_never_folds() -> None:
    ranking = rank(load_session(CHECK_SESSION_FILE))

    assert not family_rows(ranking)
    assert all(row.check.startswith("rms.") for row in ranking.rows)


def test_an_unfolded_row_omits_both_new_fields() -> None:
    row = rank(review(folded=False)).rows[0]
    dumped = json.loads(row.model_dump_json())

    assert "family" not in dumped
    assert "rule_count" not in dumped


def test_an_unfolded_record_carries_neither_new_key_anywhere(tmp_path: Path) -> None:
    """No `attention.json` is committed, so the byte claim is made the way it can be: the
    record of an unfolded session holds no key this feature added, at any depth, and every
    row serializes to exactly the keys it had before (the twelve of `contracts/attention.md`
    section 4, `explanation` omitted when absent)."""
    session = load_session(REVIEW_SESSION_FILE)

    written = write_attention_record(tmp_path, rank(session), session.session_id)

    text = written.read_text(encoding="utf-8")
    assert '"family"' not in text
    assert '"rule_count"' not in text
    for row in json.loads(text)["rows"]:
        assert set(row) == {
            "finding_id",
            "member_finding_ids",
            "check",
            "title",
            "status",
            "severity",
            "component_ids",
            "consequence_class",
            "key",
            "reason",
        }


# --- the record, and "Start here" ---------------------------------------------------------


def test_the_ranking_of_the_loaded_session_equals_the_written_record(tmp_path: Path) -> None:
    session = review(folded=True)
    save_session(session, tmp_path / "session.json")
    write_attention_record(tmp_path, rank(session), session.session_id)

    record = AttentionRecord.model_validate_json((tmp_path / ATTENTION_FILE_NAME).read_bytes())
    again = rank(load_session(tmp_path / "session.json"))
    assert record == AttentionRecord.of(again, session.session_id)
    [row] = [row for row in record.rows if row.family == "rms"]
    assert row.rule_count == 6


def test_the_family_takes_one_start_here_slot_and_prints_its_title() -> None:
    ranking = rank(review(folded=True))
    lines = start_here_lines(ranking)

    numbered = [line for line in lines if line[:2] in {"1.", "2.", "3.", "4.", "5."}]
    assert len(numbered) == 3
    family_lines = [line for line in numbered if "`rms`" in line]
    assert len(family_lines) == 1
    assert "Modelling practice: 6 findings across 6 rules" in family_lines[0]


def test_no_percent_sign_anywhere_in_a_folded_ranking() -> None:
    ranking = rank(session_of("mixed", MIXED))

    assert "%" not in ranking.model_dump_json()
    assert "%" not in "\n".join(start_here_lines(ranking))
