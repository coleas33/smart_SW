"""What the reuse key cannot catch, one explicit refusal per hole (T088, for T089).

The key (`test_reuse_key.py`) answers "is this the same design, dumped the same way?".
Four things change what a review would see **without changing the key**, and each gets a
refusal here rather than a hope, because extraction is minutes and a wrong finding is
hours (data-model.md 9.3, levers.md lever 9):

1. **Unsaved in-memory edits.** `file_modified_utc` does not move until the document is
   saved, so the key of a dirty document is the key of the file on disk. `GetSaveFlag` is
   already consulted by `suppress-test`, so the live save state is available and is an
   argument to `reuse_refusals`: dirty refuses, and unreadable refuses too, because
   unknown stays unknown (constitution Principle I).
2. **A non-resolved component.** `MeshExporter` skips a suppressed or lightweight
   component with a gap (VERIFIED, `Dump/MeshExporter.cs:57-69`), so the package is thin
   in a way the next review cannot recover. Suppression state is in the key *and* a
   non-resolved component refuses reuse: the key catches the **transition**, the refusal
   catches the **state**.
3. **An aborted dump.** `PackageWriter.Build` continues past a failed phase and writes
   the package either way with gaps (VERIFIED, `:38-41,142-235`), and a phase-level
   failure is `GapKind.ToolError` with a null `entity_id` (`RunPhase`, `:429-450`;
   `GapCollector.Record`, `:72-80`). Nothing in the package says "this dump aborted", so
   the refusal reads those gaps - and honours `extractor.completed` when a 1.3.0 build
   writes it, which is the other half of the contract's "or".
4. **Per-instance referenced configurations.** The key carries the *sorted set* of
   configurations a document is referenced in, which is what makes a single instance's
   switch visible at all. A set cannot say **which** instance uses which, so two
   instances of one document swapping configurations hashes identically - asserted below,
   because a hole you cannot see is the one worth pinning. Any document referenced in
   more than one configuration therefore refuses reuse.

Clock skew is the fifth entry in that table and is deliberately **not** a refusal: mtime
can move backwards, the key is equality and not ordering, so skew produces a false
**miss** - one extra dump - which is the safe direction and is asserted as such.

Every refusal is reported, never just the first: the pane status line says why reuse did
not happen, and "and three other reasons" is not something a person can act on.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from swreview.benchmark.reuse import (
    ABORTED_DUMP,
    AMBIGUOUS_REFERENCED_CONFIGURATION,
    REFUSAL_CODES,
    SAVE_STATE_UNKNOWN,
    UNKNOWN_FILE_STAT,
    UNRESOLVED_COMPONENT,
    UNSAVED_CHANGES,
    DumpOptions,
    Refusal,
    may_reuse,
    package_reuse_key,
    reuse_refusals,
)
from swreview.ir.models import EvidencePackage, Gap
from tests.support.packages import build_package
from tests.support.reuse import (
    MODIFIED,
    ExtractorInfo13,
    reuse_entry,
    reuse_manifest,
    reuse_package,
)

OPTIONS = DumpOptions()


def codes(refusals: tuple[Refusal, ...]) -> set[str]:
    return {refusal.code for refusal in refusals}


def refusals_of(package: EvidencePackage, *, unsaved_changes: bool | None = False) -> set[str]:
    return codes(reuse_refusals(package, unsaved_changes=unsaved_changes))


def package_with_component(component_id: str, **changes: Any) -> EvidencePackage:
    components = [
        component.model_copy(update=changes) if component.id == component_id else component
        for component in reuse_package().components
    ]
    return reuse_package(components=components)


def phase_gap(entity_kind: str = "mate") -> Gap:
    """What `PackageWriter.RunPhase` writes when a whole phase threw: no `entity_id`."""
    return Gap(
        kind="tool_error",
        entity_kind=entity_kind,
        entity_id=None,
        reason="Failed to read the mates.",
        error="COMException: 0x80004005",
    )


# --- The clean case, so every refusal below is the only thing that changed -----------


def test_a_clean_saved_package_refuses_nothing() -> None:
    assert reuse_refusals(reuse_package(), unsaved_changes=False) == ()
    assert may_reuse(reuse_package(), unsaved_changes=False) is True


def test_may_reuse_is_exactly_the_absence_of_refusals() -> None:
    dirty = reuse_package()
    assert reuse_refusals(dirty, unsaved_changes=True) != ()
    assert may_reuse(dirty, unsaved_changes=True) is False


# --- 1. Unsaved in-memory edits --------------------------------------------------------


def test_an_unsaved_document_refuses_reuse() -> None:
    """mtime does not move until save, so the key alone would happily match."""
    assert refusals_of(reuse_package(), unsaved_changes=True) == {UNSAVED_CHANGES}


def test_the_unsaved_refusal_says_so_in_words() -> None:
    """The pane status line prints this instead of "Reusing the extraction from ..."."""
    (refusal,) = reuse_refusals(reuse_package(), unsaved_changes=True)
    assert "unsaved" in refusal.reason.lower()


def test_the_save_flag_changes_the_refusal_and_never_the_key() -> None:
    """The reason the refusal exists at all: an in-memory edit changes nothing on disk, so
    the key is the file's either way and the live flag has to be an argument."""
    package = reuse_package()
    assert package_reuse_key(package, OPTIONS) == package_reuse_key(reuse_package(), OPTIONS)
    assert may_reuse(package, unsaved_changes=False) is True
    assert may_reuse(package, unsaved_changes=True) is False


def test_an_unreadable_save_flag_refuses_reuse() -> None:
    """`GetSaveFlag` unreadable is not "saved": unknown stays unknown (Principle I)."""
    assert refusals_of(reuse_package(), unsaved_changes=None) == {SAVE_STATE_UNKNOWN}


# --- 2. A non-resolved component --------------------------------------------------------


@pytest.mark.parametrize("suppression", ["suppressed", "lightweight", "unloaded"])
def test_a_non_resolved_component_refuses_reuse(suppression: str) -> None:
    """`MeshExporter` skipped it, so the package is thin in a way reuse would inherit."""
    package = package_with_component("cmp:0002", suppression=suppression)
    assert refusals_of(package) == {UNRESOLVED_COMPONENT}


def test_the_non_resolved_refusal_names_the_component() -> None:
    package = package_with_component("cmp:0002", suppression="suppressed")
    (refusal,) = reuse_refusals(package, unsaved_changes=False)
    assert "cmp:0002" in refusal.reason


def test_every_non_resolved_component_is_named_once() -> None:
    components = [
        component.model_copy(update={"suppression": "suppressed"})
        for component in reuse_package().components
    ]
    refusals = reuse_refusals(reuse_package(components=components), unsaved_changes=False)
    assert [refusal.code for refusal in refusals] == [UNRESOLVED_COMPONENT] * 2
    reasons = " ".join(refusal.reason for refusal in refusals)
    assert "cmp:0001" in reasons
    assert "cmp:0002" in reasons


# --- 3. An aborted dump ------------------------------------------------------------------


def test_a_phase_level_tool_error_gap_refuses_reuse() -> None:
    """Nothing else in the package says "this dump aborted"."""
    assert refusals_of(reuse_package(gaps=[phase_gap()])) == {ABORTED_DUMP}


def test_the_aborted_dump_refusal_names_the_phase() -> None:
    (refusal,) = reuse_refusals(reuse_package(gaps=[phase_gap("face")]), unsaved_changes=False)
    assert "face" in refusal.reason


def test_a_per_entity_tool_error_gap_does_not_refuse_reuse() -> None:
    """One hole that would not read is an ordinary unknown, carried in `gaps[]` and
    reviewed as such; it is a *phase* that threw that makes the package partial."""
    entity_gap = phase_gap().model_copy(update={"entity_id": "hole:1"})
    assert refusals_of(reuse_package(gaps=[entity_gap])) == set()


@pytest.mark.parametrize("kind", ["not_extracted", "unsupported", "no_text"])
def test_the_other_gap_kinds_do_not_refuse_reuse(kind: str) -> None:
    """`local_modified` alone writes an `unsupported` gap on every document of every dump
    (VERIFIED, `ManifestBuilder.cs:57,92-98`); refusing on those would refuse everything."""
    gap = phase_gap().model_copy(update={"kind": kind, "error": None})
    assert refusals_of(reuse_package(gaps=[gap])) == set()


def test_extractor_completed_false_refuses_reuse() -> None:
    """The other half of the contract's "or": a 1.3.0 build states it outright."""
    extractor = ExtractorInfo13(
        **reuse_package().extractor.model_dump(),
        completed=False,
    )
    assert refusals_of(reuse_package(extractor=extractor)) == {ABORTED_DUMP}


def test_extractor_completed_true_does_not_refuse_reuse() -> None:
    extractor = ExtractorInfo13(**reuse_package().extractor.model_dump(), completed=True)
    assert refusals_of(reuse_package(extractor=extractor)) == set()


def test_an_absent_completed_field_leaves_the_gap_rule_to_decide() -> None:
    """1.2.0 packages have no `completed`, and refusing all of them would make the lever
    untestable before T089; the phase-level gap rule is what carries those."""
    assert refusals_of(reuse_package()) == set()
    assert refusals_of(reuse_package(gaps=[phase_gap()])) == {ABORTED_DUMP}


# --- 4. Per-instance referenced configurations ---------------------------------------------


def swapped_pair() -> tuple[EvidencePackage, EvidencePackage]:
    """Two instances of `doc:2`, their configurations exchanged between the packages."""
    first, second = reuse_package().components
    one = reuse_package(
        components=[
            first.model_copy(update={"referenced_configuration": "Default"}),
            second.model_copy(update={"referenced_configuration": "Machined"}),
        ]
    )
    other = reuse_package(
        components=[
            first.model_copy(update={"referenced_configuration": "Machined"}),
            second.model_copy(update={"referenced_configuration": "Default"}),
        ]
    )
    return one, other


def test_two_instances_swapping_configurations_hash_identically() -> None:
    """The hole itself: the key carries a *set*, and a set cannot say which instance is
    which. The geometry differs; the key does not."""
    one, other = swapped_pair()
    assert package_reuse_key(one, OPTIONS) == package_reuse_key(other, OPTIONS)


def test_a_document_referenced_in_two_configurations_refuses_reuse() -> None:
    for package in swapped_pair():
        assert refusals_of(package) == {AMBIGUOUS_REFERENCED_CONFIGURATION}


def test_the_ambiguous_configuration_refusal_names_the_document() -> None:
    one, _ = swapped_pair()
    (refusal,) = reuse_refusals(one, unsaved_changes=False)
    assert "doc:2" in refusal.reason


def test_one_configuration_per_document_does_not_refuse_reuse() -> None:
    """Two instances of a part in the same configuration is the ordinary assembly."""
    assert refusals_of(reuse_package()) == set()


# --- 5. Unknown file stats: every package that exists today ----------------------------------


def test_a_pre_1_3_0_package_refuses_reuse() -> None:
    """`file_modified_utc` and `file_size_bytes` arrive in T089. Until then every entry is
    unknown, and a key that cannot see a change must not be reused on."""
    assert refusals_of(build_package()) == {UNKNOWN_FILE_STAT}


def test_a_missing_modification_time_alone_refuses_reuse() -> None:
    """The gap the C# writes when a path cannot be stat'ed is one field at a time."""
    entries = [
        reuse_entry("doc:1", "/Designs/cover-assy.SLDASM", file_modified_utc=None),
        reuse_entry("doc:2", "/Designs/housing.SLDPRT"),
    ]
    assert refusals_of(reuse_package(manifest=reuse_manifest(entries))) == {UNKNOWN_FILE_STAT}


def test_a_missing_file_size_alone_refuses_reuse() -> None:
    entries = [
        reuse_entry("doc:1", "/Designs/cover-assy.SLDASM"),
        reuse_entry("doc:2", "/Designs/housing.SLDPRT", file_size_bytes=None),
    ]
    assert refusals_of(reuse_package(manifest=reuse_manifest(entries))) == {UNKNOWN_FILE_STAT}


def test_the_unknown_stat_refusal_names_the_document() -> None:
    entries = [
        reuse_entry("doc:1", "/Designs/cover-assy.SLDASM"),
        reuse_entry("doc:2", "/Designs/housing.SLDPRT", file_size_bytes=None),
    ]
    (refusal,) = reuse_refusals(
        reuse_package(manifest=reuse_manifest(entries)), unsaved_changes=False
    )
    assert "doc:2" in refusal.reason


# --- Clock skew: a false miss, which is the safe direction -------------------------------------


def test_clock_skew_produces_a_different_key_and_no_refusal() -> None:
    """A file restored from backup can carry an *older* mtime. The key is equality, not
    ordering, so this is one wasted dump - never a stale package accepted as fresh."""
    entries = [
        reuse_entry(
            "doc:1", "/Designs/cover-assy.SLDASM", file_modified_utc=MODIFIED - timedelta(days=30)
        ),
        *reuse_manifest().entries[1:],
    ]
    restored = reuse_package(manifest=reuse_manifest(entries))
    assert package_reuse_key(restored, OPTIONS) != package_reuse_key(reuse_package(), OPTIONS)
    assert refusals_of(restored) == set()


# --- The shape of a refusal ----------------------------------------------------------------------


def test_every_refusal_carries_a_known_code_and_a_sentence() -> None:
    components = [
        component.model_copy(update={"suppression": "suppressed"})
        for component in reuse_package().components
    ]
    package = reuse_package(components=components, gaps=[phase_gap()])
    refusals = reuse_refusals(package, unsaved_changes=None)
    for refusal in refusals:
        assert refusal.code in REFUSAL_CODES
        assert refusal.reason.endswith(".")


def test_all_the_reasons_are_reported_not_only_the_first() -> None:
    """A status line that names one of four reasons sends someone round the loop again."""
    components = [
        component.model_copy(update={"suppression": "suppressed"})
        for component in reuse_package().components
    ]
    entries = [
        reuse_entry("doc:1", "/Designs/cover-assy.SLDASM", file_size_bytes=None),
        *reuse_manifest().entries[1:],
    ]
    package = reuse_package(
        components=components, manifest=reuse_manifest(entries), gaps=[phase_gap()]
    )
    assert codes(reuse_refusals(package, unsaved_changes=True)) == {
        UNSAVED_CHANGES,
        UNRESOLVED_COMPONENT,
        ABORTED_DUMP,
        UNKNOWN_FILE_STAT,
    }


def test_the_refusal_codes_are_a_closed_list() -> None:
    assert set(REFUSAL_CODES) == {
        UNSAVED_CHANGES,
        SAVE_STATE_UNKNOWN,
        UNRESOLVED_COMPONENT,
        ABORTED_DUMP,
        AMBIGUOUS_REFERENCED_CONFIGURATION,
        UNKNOWN_FILE_STAT,
    }
    assert len(set(REFUSAL_CODES)) == len(REFUSAL_CODES)
