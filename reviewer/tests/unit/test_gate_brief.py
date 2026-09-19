"""The procedural gate's first user message (T045, `contracts/gate.md` section 3).

`gate_brief(prerun, ranking)` is lever 11's whole output. The gate runs the deterministic
checks before the first turn - lever 5 already does that - and then tells the model, in one
message, **what has already been decided and what is left**, so the rounds it has go on the
families no rule can reach rather than on re-deriving verdicts that are already in the
session.

Six parts, in this order, and the reason each one is there:

1. **the lever-5 digest, byte-identical.** The gate is lever 5 plus a brief, never a second
   pre-run with prose of its own, and FR-030 pins the digest for the off arm.
2. **`Start here:`** - the same lines `report.md` renders, from the same `Ranking`. The ids
   the model reads and the ids the engineer reads are one list in one order (FR-031), and
   they are one list *structurally*: both sides call `attention.start_here_lines`.
3. **`Needs your judgement:`** - key 2 of the policy, lifted out. A press fit that is a
   defect and a press fit that is intended are the same finding to every tool there is, so
   those rows are named again as the ones the model cannot settle either.
4. **`Not reached in this run:`** - `attention.coverage_line`, verbatim again.
5. **`Not visible to any rule:`** - one sentence per not-evaluated family, read from the
   policy file's `blind_spots`. These are the *structural* gaps, and each is backed by the
   `coverage.prerun.<family>` skipped item the same pre-run wrote, so the model and the
   report are reading one claim.
6. **the instruction**, verbatim, because the risk the whole gate carries is a model that
   reads "these checks are done" as "the review is done".

**Nothing here is re-derived.** Every row, sentence and count comes from `start_here_lines`,
`coverage_line` or the policy file; this module asserts the composition and the two lists
the brief owns, and pins no reason sentence of its own - a test that restated one would be
pinning the same words in two files.
"""

from __future__ import annotations

from typing import Any

from swreview.agent.runner import OPENING_MESSAGE
from swreview.ir.models import EvidencePackage
from swreview.prerun import (
    GATE_BLIND_SPOT_HEADER,
    GATE_INSTRUCTION,
    GATE_JUDGEMENT_HEADER,
    GATE_NONE,
    GATE_NOT_REACHED_HEADER,
    GATE_START_HERE_HEADER,
    PRERUN_CHECK_PREFIX,
    NotEvaluated,
    PrerunCall,
    PrerunResult,
    gate_brief,
    not_evaluated_families,
)
from swreview.report.attention import (
    MAX_NOT_CLOSED,
    TOP_N,
    coverage_line,
    load_policy,
    rank,
    start_here_lines,
)
from swreview.report.session import ReviewSession
from tests.support.attention import (
    PIN_ONE,
    PIN_TWO,
    CoverageRow,
    CoverageSpec,
    FindingSpec,
)
from tests.support.prerun import GATE_ON, prerun_package
from tests.unit.test_attention import session_of, spec
from tests.unit.test_prerun_digest import opening_of, started

HEADERS: tuple[str, ...] = (
    GATE_START_HERE_HEADER,
    GATE_JUDGEMENT_HEADER,
    GATE_NOT_REACHED_HEADER,
    GATE_BLIND_SPOT_HEADER,
)
"""The four headers the brief adds, in the order section 3 lists them."""

JUDGEMENT_CHECK = "interference.static"
"""A check the policy's `needs_judgement` prefixes name, so its rows carry key 2 == 0."""

RULE_CHECK = "rms.sketches.fully_defined"
"""One they do not, so its rows carry key 2 == 1."""

FIXTURE_FAMILIES: tuple[str, ...] = ("fastener_joint", "hole_alignment", "fit", "axial_stack")
"""The four families `prerun_package()` leaves unevaluated: it reports an interference, so
the conditional interference family is absent, and no standards run is attached here."""


# --- building one brief ----------------------------------------------------------------------


def empty_prerun() -> PrerunResult:
    """A pre-run that ran nothing and counted nothing: the parts that are not part 1."""
    return PrerunResult(calls=(), not_evaluated=())


def prerun_over(package: EvidencePackage | None = None) -> PrerunResult:
    """A pre-run carrying the package's real not-evaluated families and no calls."""
    return PrerunResult(
        calls=(),
        not_evaluated=not_evaluated_families(
            package if package is not None else prerun_package(), ()
        ),
    )


def brief_of(session: ReviewSession, prerun: PrerunResult | None = None) -> str:
    return gate_brief(prerun if prerun is not None else empty_prerun(), rank(session))


def part_of(brief: str, header: str) -> list[str]:
    """The lines under one header, up to the next header or the instruction.

    Trailing blanks are dropped, because a blank line is what separates one part from the
    next; what is left is exactly what that part contributed.
    """
    lines = brief.splitlines()
    start = lines.index(header) + 1
    ends = {*HEADERS, GATE_INSTRUCTION}
    end = next((one for one in range(start, len(lines)) if lines[one] in ends), len(lines))
    part = lines[start:end]
    while part and not part[-1]:
        part.pop()
    return part


def numbered(lines: list[str]) -> list[str]:
    """The `1.`-style rows of a "Start here" block."""
    return [line for line in lines if line[:1].isdigit()]


# --- 1. the six parts, in order -----------------------------------------------------------


def test_the_brief_renders_the_six_parts_in_the_order_the_contract_lists_them() -> None:
    session = session_of("six-parts", [spec(JUDGEMENT_CHECK), spec(RULE_CHECK)])
    prerun = prerun_over()

    brief = gate_brief(prerun, rank(session))

    positions = [brief.index(marker) for marker in (*HEADERS, GATE_INSTRUCTION)]
    assert positions == sorted(positions)
    assert brief.endswith(GATE_INSTRUCTION)


def test_the_first_part_is_the_lever_5_digest_byte_for_byte() -> None:
    """The gate is lever 5 plus a brief; a second rendering of the digest would drift."""
    prerun = PrerunResult(
        calls=(
            PrerunCall(tool="check_rms_part", arguments={}, step_index=0, findings=(), error=None),
        ),
        not_evaluated=not_evaluated_families(prerun_package(), ()),
    )

    brief = gate_brief(prerun, rank(session_of("digest-part", [spec(RULE_CHECK)])))

    assert brief.startswith(f"{prerun.digest()}\n\n{GATE_START_HERE_HEADER}\n")


def test_every_part_is_separated_from_the_next_by_one_blank_line() -> None:
    brief = brief_of(session_of("spacing", [spec(RULE_CHECK)]), prerun_over())

    assert "\n\n\n" not in brief
    for header in HEADERS:
        assert f"\n\n{header}\n" in brief
    assert f"\n\n{GATE_INSTRUCTION}" in brief


# --- 2. Start here, from the same object the report renders -------------------------------


def test_the_start_here_part_is_attentions_own_lines_verbatim() -> None:
    session = session_of("start-here", [spec(JUDGEMENT_CHECK), spec(RULE_CHECK)])
    ranking = rank(session)

    part = part_of(gate_brief(empty_prerun(), ranking), GATE_START_HERE_HEADER)

    assert part == start_here_lines(ranking)
    assert numbered(part) == [line for line in start_here_lines(ranking) if line[:1].isdigit()]


SIX_ROWS: tuple[FindingSpec, ...] = (
    spec(JUDGEMENT_CHECK, component_ids=(PIN_ONE,)),
    spec(JUDGEMENT_CHECK, component_ids=(PIN_TWO,)),
    spec("rms.assembly.mates_to_reference_geometry"),
    spec("rms.sketches.fully_defined"),
    spec("rms.grouping.all_features_in_a_group"),
    spec("rms.params.global_variables_present"),
)
"""Six rows that stay six: a needs-judgement check never folds, and the four rms specs carry
four different checks. Five are amplified and the sixth is counted, never dropped."""


def test_six_rows_are_capped_at_five_and_the_sixth_is_counted() -> None:
    session = session_of("six-rows", list(SIX_ROWS))
    ranking = rank(session)

    part = part_of(gate_brief(empty_prerun(), ranking), GATE_START_HERE_HEADER)

    assert len(ranking.rows) == len(SIX_ROWS)
    assert len(numbered(part)) == TOP_N
    assert ranking.not_amplified.beyond_top_n == 1
    assert part[-1] == (
        "Not amplified: 1 finding (0 checked within scope, 0 already decided, "
        "0 informational, 1 beyond the top five)."
    )


# --- 3. Needs your judgement ---------------------------------------------------------------


def test_needs_your_judgement_lists_exactly_the_rows_with_judgement_key_zero() -> None:
    session = session_of(
        "judgement",
        [
            spec(JUDGEMENT_CHECK, component_ids=(PIN_ONE,)),
            spec(JUDGEMENT_CHECK, component_ids=(PIN_TWO,)),
            spec(RULE_CHECK),
        ],
    )
    ranking = rank(session)

    part = part_of(gate_brief(empty_prerun(), ranking), GATE_JUDGEMENT_HEADER)

    judged = [row for row in ranking.rows if row.key.judgement == 0]
    assert len(judged) == 2
    assert part == [f"  {row.finding_id} `{row.check}` - {row.title}" for row in judged]
    rest = [row.finding_id for row in ranking.rows if row.key.judgement]
    assert rest and all(finding_id not in "\n".join(part) for finding_id in rest)


def test_needs_your_judgement_says_none_when_no_row_needs_any() -> None:
    part = part_of(brief_of(session_of("no-judgement", [spec(RULE_CHECK)])), GATE_JUDGEMENT_HEADER)

    assert part == [GATE_NONE]


# --- 4. Not reached in this run -------------------------------------------------------------

SIX_CLOSE_OUT: tuple[CoverageRow, ...] = (
    CoverageRow(check="provenance", reason="Provenance: no manifest was read."),
    CoverageRow(check="drawing.manufacturing_inputs", reason="Drawings: no sheet was read."),
    CoverageRow(check="interfaces.fit", reason="Fits: no interface was named."),
    CoverageRow(check="interfaces.stack", reason="Stacks: no stack was named."),
    CoverageRow(check="fasteners", reason="Fasteners: no joint was named."),
    CoverageRow(check="holes.alignment", reason="Holes: no pair was named."),
)
"""Six close-out rows, one more than the block prints, so the cap is exercised."""


def test_not_reached_is_the_coverage_block_verbatim() -> None:
    session = session_of(
        "not-reached",
        [spec(RULE_CHECK)],
        CoverageSpec(
            checked=2,
            skipped=1,
            unresolved=[
                *SIX_CLOSE_OUT,
                CoverageRow(check="coverage.evidence_request", reason="ER-001 is still open."),
            ],
        ),
    )
    ranking = rank(session)

    part = part_of(gate_brief(empty_prerun(), ranking), GATE_NOT_REACHED_HEADER)

    assert part == coverage_line(ranking)
    assert part[0].startswith("What this run could not reach: 7 unresolved, 1 skipped,")
    assert part[-1] == "- 1 evidence request is still open; 0 rules unresolved and 1 skipped."


def test_a_close_out_row_beyond_the_cap_is_counted_in_the_line_above_it() -> None:
    """The cap drops sentences, never the count: the sixth row is still one of the six."""
    session = session_of(
        "close-out-cap", [spec(RULE_CHECK)], CoverageSpec(unresolved=list(SIX_CLOSE_OUT))
    )

    part = part_of(brief_of(session), GATE_NOT_REACHED_HEADER)

    assert part[0].startswith("What this run could not reach: 6 unresolved,")
    assert len([line for line in part if line.startswith("- ")]) == MAX_NOT_CLOSED
    assert SIX_CLOSE_OUT[-1].reason not in "\n".join(part)


# --- 5. Not visible to any rule --------------------------------------------------------------


def test_every_blind_spot_sentence_comes_from_the_policy_file() -> None:
    prerun = prerun_over()
    blind_spots = load_policy().blind_spots

    part = part_of(
        gate_brief(prerun, rank(session_of("blind-spots", [spec(RULE_CHECK)]))),
        GATE_BLIND_SPOT_HEADER,
    )

    families = [family.check.removeprefix(PRERUN_CHECK_PREFIX) for family in prerun.not_evaluated]
    assert families == list(FIXTURE_FAMILIES)
    assert part == [
        f"  {family.label}: {blind_spots[name]}"
        for family, name in zip(prerun.not_evaluated, families, strict=True)
    ]


def test_each_sentence_is_backed_by_that_familys_skipped_coverage_item() -> None:
    """One claim, two renderings: the sentence the model reads and the coverage item the
    report carries name the same family (the digest's own rule, FR-010)."""
    prerun = prerun_over()

    part = part_of(
        gate_brief(prerun, rank(session_of("backed", [spec(RULE_CHECK)]))),
        GATE_BLIND_SPOT_HEADER,
    )

    items = [family.coverage_item().check for family in prerun.not_evaluated]
    assert items == [f"{PRERUN_CHECK_PREFIX}{name}" for name in FIXTURE_FAMILIES]
    assert len(part) == len(items)


def test_a_family_the_policy_names_no_blind_spot_for_writes_no_sentence() -> None:
    """A tier that withheld a pre-run tool is a *this run* gap, not a structural one: its
    sentence is the tier's own and is already in the digest (contracts/levers.md, lever 4)."""
    withheld = NotEvaluated(
        check=f"{PRERUN_CHECK_PREFIX}check_rms_part",
        label="check_rms_part",
        reason="the package carries no feature rows, so the tier withheld this tool.",
    )
    prerun = PrerunResult(calls=(), not_evaluated=(withheld, *prerun_over().not_evaluated))

    part = part_of(
        gate_brief(prerun, rank(session_of("withheld", [spec(RULE_CHECK)]))),
        GATE_BLIND_SPOT_HEADER,
    )

    assert withheld.reason not in "\n".join(part)
    assert len(part) == len(prerun.not_evaluated) - 1


def test_a_pre_run_that_counted_no_family_says_none() -> None:
    brief = brief_of(session_of("no-families", [spec(RULE_CHECK)]))

    assert part_of(brief, GATE_BLIND_SPOT_HEADER) == [GATE_NONE]


# --- 6. the instruction, and where the brief sits -------------------------------------------


def test_the_instruction_is_verbatim_and_last() -> None:
    brief = brief_of(session_of("instruction", [spec(RULE_CHECK)]), prerun_over())

    assert GATE_INSTRUCTION == (
        "These verdicts are computed from checked code. Do not re-derive them; spend your "
        "rounds on what was not reached."
    )
    assert brief.splitlines()[-1] == GATE_INSTRUCTION


def test_the_first_user_message_is_the_brief_and_then_the_opening_instruction(
    tmp_path: Any,
) -> None:
    """The brief goes where the digest goes - the first **user** message - and the opening
    instruction still closes it, so the model is told what to do after it is told what is
    known (FR-029, and lever 3's rule about what may never enter the system prompt)."""
    run, session = started(tmp_path, "gated", efficiency=GATE_ON)

    message = opening_of(run)

    assert session.findings, "the fixture must produce findings for the brief to rank"
    assert message.endswith(f"\n\n{OPENING_MESSAGE}")
    for header in HEADERS:
        assert f"\n{header}\n" in message
    assert f"\n{GATE_INSTRUCTION}\n" in message


def test_the_brief_never_prints_a_percent_sign() -> None:
    """Everything the ranking renders can reach the Standards tab, whose body scan forbids
    one (research R2.14), and the brief renders the same strings."""
    brief = brief_of(session_of("no-percent", list(SIX_ROWS)), prerun_over())

    assert "%" not in brief


def test_the_brief_is_reproducible_from_the_same_session() -> None:
    """Two calls over one session produce one string: the ranking is a pure function of the
    session and so is this (FR-014)."""
    session = session_of("reproducible", list(SIX_ROWS))
    prerun = prerun_over()

    assert gate_brief(prerun, rank(session)) == gate_brief(prerun, rank(session))


def test_a_session_with_no_findings_still_renders_all_six_parts() -> None:
    """Nothing to start with is a thing to say, and everything else still has to be said."""
    session = session_of("empty", [], CoverageSpec(unresolved=list(SIX_CLOSE_OUT)))
    ranking = rank(session)

    brief = gate_brief(prerun_over(), ranking)

    assert ranking.empty_reason is not None
    assert part_of(brief, GATE_START_HERE_HEADER) == start_here_lines(ranking)
    assert part_of(brief, GATE_JUDGEMENT_HEADER) == [GATE_NONE]
    assert part_of(brief, GATE_NOT_REACHED_HEADER) == coverage_line(ranking)
    assert brief.endswith(GATE_INSTRUCTION)
