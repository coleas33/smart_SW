"""Unit tests for the IR addition `extractor.phases`: dump phase timing (005 T033).

**No dump timing exists today.** There is no `Stopwatch` and no elapsed field anywhere in
`Dump/PackageWriter.cs`, and `DumpSummary` carries counts only, so levers 9 (package
reuse) and 10 (lazy meshes) have no metric at all: "which phase actually costs the time"
is guessed rather than answered, and P1 - the question lever 10's whole premise rests on -
cannot be settled. One row per phase, `{name, elapsed_ms, status}`, is the shape
`SuppressTestRow.elapsed_ms` already set as the only elapsed precedent in a package.

Two rules, both Principle I:

- a phase that never ran has **no** elapsed time, so `elapsed_ms` is `None` and never `0`.
  A zero would read as a phase that ran and cost nothing, which is the one thing it did
  not do;
- `status` says which of the four things happened - it ran, it threw and the dump went on,
  SOLIDWORKS stopped answering, or it was never run - because an empty `holes[]` beside a
  timed `hole` row and an empty `holes[]` beside a skipped one are different packages.

The member is **additive**: optional, defaulting to no rows, and left out of the JSON
entirely when it is empty, so a package written before it existed round-trips to the bytes
that build wrote and the feature 001/002/003 goldens stay byte-identical (SC-007). 1.3.0
already carries the reuse fields, so this needs no further bump - only a regenerated
contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from swreview.ir.models import SCHEMA_VERSION, DumpPhase, EvidencePackage, ExtractorInfo
from swreview.ir.schema import export_schema
from tests.golden.test_golden import PRE_1_4_0_FIXTURE_DIRS
from tests.support.contracts import load_contract
from tests.support.packages import build_package

GOLDEN_FIXTURE_DIRS = PRE_1_4_0_FIXTURE_DIRS
"""Every golden written before 1.4.0. Feature 006's own `standards-*` goldens are written
*at* 1.4.0 and carry its evidence by design, so they are not packages the two gates below
can ask "does this predate the bump?" of (`tests/golden/test_golden.py`)."""

TIMED = [
    DumpPhase(name="document", elapsed_ms=41, status="ok"),
    DumpPhase(name="manifest", elapsed_ms=7, status="ok"),
    DumpPhase(name="mate", elapsed_ms=0, status="failed"),
    DumpPhase(name="body", elapsed_ms=None, status="skipped"),
]

PHASE_ORDER = [
    "document",
    "manifest",
    "mate",
    "feature",
    "equation",
    "cutlist",
    "drawing",
    "hole",
    "tolerance",
    "fastener",
    "face",
    "body",
]
"""Every phase of a dump, in the order `PackageWriter.PhaseOrder` runs them (schema 1.4.0,
006 `contracts/ir-additions.md` section 6; `tolerance` joined after `hole` at 1.5.0, feature
010 T091).

Pinned on this side as well as in `PackageWriterTests` because the two sides have to
describe the same phase vocabulary: `DumpPhase.name`'s field description feeds the
generated contract, and a stale description makes the 1.4.0 schema describe a dump that no
longer exists.
"""


def described_phases(description: str) -> list[str]:
    """The phase names out of `DumpPhase.name`'s description, which lists them verbatim."""
    return [name.strip() for name in description.split(":", 1)[1].split(",")]


def build_extractor(**overrides: object) -> ExtractorInfo:
    fields: dict[str, object] = {
        "name": "SwReview.Extractor",
        "version": "0.1.0",
        "sw_version": None,
        "machine": "test",
    }
    fields.update(overrides)
    return ExtractorInfo(**fields)  # type: ignore[arg-type]


def contract_validator() -> Draft202012Validator:
    return Draft202012Validator(
        load_contract("ir.schema.json"),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


# --- the rows themselves ------------------------------------------------------------


def test_a_package_that_was_not_timed_carries_no_rows() -> None:
    """The default is "nobody timed this dump", not "every phase took nothing"."""
    assert build_extractor().phases == []


def test_the_phases_member_needs_no_new_schema_version() -> None:
    """1.3.0 is where the reuse fields and this member arrived; the minor has moved again
    since (1.4.0, the standards evidence; 1.5.0, the tolerance evidence) and this member
    was not what moved it."""
    assert SCHEMA_VERSION == "1.5.0"
    assert build_package().schema_version == "1.5.0"


def test_the_field_description_names_every_phase_the_dump_runs_in_order() -> None:
    """`cutlist` and `drawing` joined the dump in 1.4.0, and this description is where the
    generated contract learns the vocabulary. Leaving it stale would ship a schema that
    describes nine phases while `PackageWriter.PhaseOrder` runs eleven - and, because the
    description is generated rather than hand-written into the contract, nothing else would
    notice."""
    description = DumpPhase.model_fields["name"].description

    assert description is not None
    assert described_phases(description) == PHASE_ORDER


def test_the_committed_contract_names_the_same_phases() -> None:
    """The committed contract is what the C# extractor validates against, so a vocabulary
    the models know and the committed file does not is a dump the extractor cannot
    describe."""
    described = load_contract("ir.schema.json")["$defs"]["DumpPhase"]["properties"]["name"]

    assert described_phases(described["description"]) == PHASE_ORDER


def test_the_generated_schema_names_the_same_phases() -> None:
    generated = export_schema()["$defs"]["DumpPhase"]["properties"]["name"]

    assert described_phases(generated["description"]) == PHASE_ORDER


def test_the_two_new_phases_are_named_after_the_five_a_model_check_runs() -> None:
    """Order is not decoration: `standards` extends `model_check`, and a consumer reading
    the rows top-down sees the five shared phases, then the two this feature adds, then the
    geometry phases no standards check reads - with 1.5.0's `tolerance` read after `hole`."""
    assert PHASE_ORDER[:5] == ["document", "manifest", "mate", "feature", "equation"]
    assert PHASE_ORDER[5:7] == ["cutlist", "drawing"]
    assert PHASE_ORDER[7:] == ["hole", "tolerance", "fastener", "face", "body"]


def test_a_phase_that_never_started_is_recorded_skipped_with_no_elapsed_time() -> None:
    """The fact a reader needs most when a package comes back thin, and the one FR-043
    refuses a standards run on: `swreview check standards` reads the `cutlist` row rather
    than the profile name, so a phase that never started has to be a row and not an
    absence. Every phase is present; the two this feature adds carry no elapsed time
    because a `model_check` dump never ran them, and 0 would say they ran and cost
    nothing."""
    rows = [
        DumpPhase(name=name, elapsed_ms=3, status="ok")
        if name in {"document", "manifest", "mate", "feature", "equation"}
        else DumpPhase(name=name, elapsed_ms=None, status="skipped")
        for name in PHASE_ORDER
    ]

    restored = EvidencePackage.model_validate_json(
        build_package(extractor=build_extractor(phases=rows)).model_dump_json()
    )

    assert [phase.name for phase in restored.extractor.phases] == PHASE_ORDER
    skipped = {phase.name: phase for phase in restored.extractor.phases
               if phase.status == "skipped"}
    assert set(skipped) == {"cutlist", "drawing", "hole", "tolerance", "fastener", "face", "body"}
    assert all(phase.elapsed_ms is None for phase in skipped.values())


def test_a_phase_that_never_ran_has_no_elapsed_time() -> None:
    """Unknown stays unknown. `0` would say the phase ran and cost nothing."""
    skipped = DumpPhase(name="body", elapsed_ms=None, status="skipped")

    assert skipped.elapsed_ms is None


def test_a_phase_that_cost_nothing_measurable_is_zero_and_not_unknown() -> None:
    """The inverse of the rule above: a phase that ran and came back inside the clock's
    resolution is `0`, which is a measurement and not an absence."""
    assert DumpPhase(name="manifest", elapsed_ms=0, status="ok").elapsed_ms == 0


def test_a_negative_elapsed_time_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DumpPhase(name="mate", elapsed_ms=-1, status="ok")


def test_an_unknown_status_is_rejected() -> None:
    """Four outcomes, spelled the way `PackageWriter` spells them. A fifth word would be a
    status no reader has a rule for."""
    with pytest.raises(ValidationError):
        DumpPhase(name="mate", elapsed_ms=1, status="done")  # type: ignore[arg-type]


@pytest.mark.parametrize("status", ["ok", "failed", "aborted", "skipped"])
def test_every_status_the_writer_can_record_is_accepted(status: str) -> None:
    row = DumpPhase(name="mate", elapsed_ms=None, status=status)  # type: ignore[arg-type]

    assert row.status == status


# --- additive: what the JSON looks like ---------------------------------------------


def test_an_untimed_extractor_block_serializes_without_the_member() -> None:
    """The member is left out when it is empty, so a package from a build that predates it
    round-trips to the bytes that build wrote and the shipped goldens stay byte-identical
    (SC-007). This is the whole reason it is omitted rather than written as `[]`."""
    assert "phases" not in json.loads(build_extractor().model_dump_json())


def test_a_timed_extractor_block_serializes_the_rows() -> None:
    written = json.loads(build_extractor(phases=TIMED).model_dump_json())

    assert written["phases"][0] == {"name": "document", "elapsed_ms": 41, "status": "ok"}
    assert written["phases"][3] == {"name": "body", "elapsed_ms": None, "status": "skipped"}


def test_the_rows_round_trip_through_json() -> None:
    package = build_package(extractor=build_extractor(phases=TIMED))

    restored = EvidencePackage.model_validate_json(package.model_dump_json())

    assert restored.extractor.phases == TIMED
    assert restored == package


def test_the_rows_keep_the_order_the_dump_ran_them_in() -> None:
    """The order is the answer to "what ran before the phase that died", so the member is
    a list and not a map keyed by name."""
    restored = EvidencePackage.model_validate_json(
        build_package(extractor=build_extractor(phases=TIMED)).model_dump_json()
    )

    assert [phase.name for phase in restored.extractor.phases] == [
        "document",
        "manifest",
        "mate",
        "body",
    ]


def test_a_package_written_before_the_member_existed_still_loads() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["extractor"].pop("phases", None)

    package = EvidencePackage.model_validate_json(json.dumps(payload))

    assert package.extractor.phases == []


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURE_DIRS, ids=lambda path: path.name)
def test_every_shipped_golden_fixture_still_loads_and_is_untimed(fixture: Path) -> None:
    """Every fixture in the tree predates this member. A package that no longer loaded, or
    one that came back claiming timings nobody measured, would both be a major bump wearing
    a minor's number."""
    text = (fixture / "package.json").read_text(encoding="utf-8")

    package = EvidencePackage.model_validate_json(text)

    assert package.extractor.phases == []


def test_an_unknown_member_on_a_row_is_forbidden() -> None:
    payload = json.loads(
        build_package(extractor=build_extractor(phases=TIMED)).model_dump_json()
    )
    payload["extractor"]["phases"][0]["cpu_ms"] = 12

    with pytest.raises(ValidationError):
        EvidencePackage.model_validate_json(json.dumps(payload))


# --- the generated contract ----------------------------------------------------------


def test_the_contract_says_which_minor_introduced_the_member() -> None:
    """Every other member of the contract carries the minor it arrived in - `profile` says
    "(schema 1.2.0)", the reuse fields beside this one say "(schema 1.3.0)". Without that
    marker a reader of the committed contract cannot tell when `phases` appeared, and two
    1.3.0 packages, one from the build before this member and one from the build after,
    are indistinguishable by version alone."""
    contract = load_contract("ir.schema.json")

    assert (
        "(schema 1.3.0"
        in contract["$defs"]["ExtractorInfo"]["properties"]["phases"]["description"]
    )
    assert "(schema 1.3.0" in contract["$defs"]["DumpPhase"]["description"]


def test_the_generated_schema_carries_the_same_marker() -> None:
    """The contract is generated, never hand-edited, so the marker has to live on the
    models or the next regeneration drops it."""
    schema = export_schema()

    assert (
        "(schema 1.3.0"
        in schema["$defs"]["ExtractorInfo"]["properties"]["phases"]["description"]
    )
    assert "(schema 1.3.0" in schema["$defs"]["DumpPhase"]["description"]


def test_the_generated_schema_makes_the_member_optional() -> None:
    schema = export_schema()

    assert "phases" not in schema["$defs"]["ExtractorInfo"]["required"]


def test_the_generated_schema_keeps_an_elapsed_time_at_or_above_zero() -> None:
    elapsed = export_schema()["$defs"]["DumpPhase"]["properties"]["elapsed_ms"]

    assert any(option.get("minimum") == 0 for option in elapsed["anyOf"])


def test_a_timed_package_validates_against_the_committed_contract() -> None:
    """The committed contract is what the C# extractor validates against, so a member the
    generated schema knows and the committed file does not is a package the extractor
    cannot write."""
    sample = build_package(extractor=build_extractor(phases=TIMED)).model_dump(mode="json")

    errors = sorted(
        contract_validator().iter_errors(sample), key=lambda error: list(error.absolute_path)
    )

    assert errors == []
