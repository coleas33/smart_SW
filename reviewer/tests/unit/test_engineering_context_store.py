"""Private context storage cannot become a write alongside source CAD."""

# The persisted chain protects exact input revisions and decision history.
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from swreview.engineering_context.models import (
    AppliedForceRecord,
    ContextArtifact,
    CoordinateFrame,
    EvidenceBaseline,
    ForceQuantity,
    Provenance,
    RequirementRecord,
    TargetAnchor,
    context_digest,
    decision_state,
    dependency_digest,
    record_digest,
)
from swreview.engineering_context.store import (
    ContextStore,
    ContextStoreBusy,
    ContextStoreConflict,
    ContextStoreError,
    check_store_directory,
    confirm_record,
    next_artifact,
    put_record,
)


def test_private_directory_is_allowed_without_creation(tmp_path: Path) -> None:
    private = tmp_path / "review-run" / "context"
    assert check_store_directory(private) == private.resolve()
    assert not private.exists()


@pytest.mark.parametrize("suffix", [".SLDPRT", ".sldasm", ".SldDrw"])
def test_directory_containing_cad_is_refused_without_touching_source(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / f"FICT-SOURCE{suffix}"
    source.write_bytes(b"fictional CAD placeholder")
    before = source.stat()
    with pytest.raises(ContextStoreError, match="source CAD") as caught:
        check_store_directory(tmp_path)
    assert str(source) not in str(caught.value)
    assert source.read_bytes() == b"fictional CAD placeholder"
    assert source.stat().st_mtime_ns == before.st_mtime_ns


def test_context_below_declared_source_directory_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "engineering" / "FICT-SOURCE.sldprt"
    private = source.parent / "run" / "context"
    with pytest.raises(ContextStoreError, match="source CAD") as caught:
        check_store_directory(private, source_paths=(source,))
    assert str(source) not in str(caught.value)
    assert not private.exists()


def test_context_file_name_cannot_be_native_cad(tmp_path: Path) -> None:
    with pytest.raises(ContextStoreError, match="source CAD"):
        check_store_directory(tmp_path / "FICT-SOURCE.sldprt")


def test_private_directory_must_be_a_directory(tmp_path: Path) -> None:
    file = tmp_path / "occupied"
    file.write_bytes(b"existing")
    with pytest.raises(ContextStoreError, match="directory"):
        check_store_directory(file)
    assert file.read_bytes() == b"existing"


def _directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        import os
        import subprocess

        if os.name != "nt":
            pytest.skip("host cannot create a directory symlink")
        # Windows junctions do not require symlink privilege and are also reparse points.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
        )
        if result.returncode:
            pytest.skip("host cannot create a filesystem link")


def test_existing_symlink_parent_cannot_redirect_context_storage(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    link = tmp_path / "linked"
    _directory_link(link, target)
    with pytest.raises(ContextStoreError, match="link"):
        check_store_directory(link / "context")
    assert not (target / "context").exists()


NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
PACKAGE_ID = UUID("00000000-0000-4000-8000-000000000016")
CONTEXT_ID = UUID("00000000-0000-4000-8000-000000000017")
IDENTITY = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _anchor(kind: str = "component") -> TargetAnchor:
    return TargetAnchor(
        anchor_id="anchor.one",
        package_id=PACKAGE_ID,
        kind=kind,
        entity_id="component.one",
        document_id="document.one",
        configuration="Default",
        component_id="component.one",
        full_path="FICT-ROOT/FICT-PART-1",
        referenced_configuration="Default",
    )


def _requirement(*, revision: int = 1, text: str = "Protect the functional interface."):
    return RequirementRecord(
        record_id="requirement.one",
        revision=revision,
        anchor=_anchor(),
        text=text,
        provenance=Provenance(kind="engineer", source="Fictional engineer input"),
    )


def _force() -> AppliedForceRecord:
    return AppliedForceRecord(
        record_id="force.one",
        revision=1,
        anchor=_anchor(),
        magnitude=ForceQuantity(state="known", value=12.0, unit="N"),
        direction=(0.0, -1.0, 0.0),
        frame=CoordinateFrame(
            frame_id="frame.root", document_id="document.one", transform=IDENTITY
        ),
        application="component_total",
        provenance=Provenance(kind="ai_proposal", source="Fictional proposed operating load"),
    )


def _context(records: tuple | None = None) -> ContextArtifact:
    return ContextArtifact(
        context_id=CONTEXT_ID,
        revision=1,
        baseline=EvidenceBaseline(
            package_id=PACKAGE_ID,
            package_sha256="a" * 64,
            schema_version="1.0.0",
            root_document_id="document.one",
            configuration="Default",
        ),
        records=(_requirement(),) if records is None else records,
        updated_at=NOW,
    )


def _confirm(context: ContextArtifact, record_id: str | None = None) -> ContextArtifact:
    record = (
        next(r for r in context.records if r.record_id == record_id)
        if record_id
        else (context.records[0])
    )
    return confirm_record(
        context,
        record.record_id,
        actor="Fictional engineer",
        expected_record_digest=record_digest(record),
        expected_dependency_digest=dependency_digest(context.baseline, record),
        now=NOW,
    )


def test_context_round_trip_publishes_immutable_first_revision(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    assert store.load() is None
    assert store.publish(initial, expected_head=None) == initial
    assert store.load() == initial
    assert store.load_revision(1) == initial
    assert (store.directory / "revisions" / "00000001.json").is_file()
    assert not store.lock_path.exists()


def test_confirmed_input_then_edit_preserves_old_receipt_as_history(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    confirmed = _confirm(initial)
    assert decision_state(confirmed, confirmed.records[0]) == "confirmed"
    assert confirmed.revision == 2
    assert confirmed.previous_digest == context_digest(initial)
    assert confirmed.confirmations[0].record_revision == 1
    edited = put_record(
        confirmed, _requirement(revision=2, text="Protect both interfaces."), now=NOW
    )
    assert decision_state(edited, edited.records[0]) == "needs_review"
    assert edited.confirmations == confirmed.confirmations
    for candidate, previous in ((initial, None), (confirmed, initial), (edited, confirmed)):
        store.publish(candidate, expected_head=context_digest(previous) if previous else None)
    assert store.load() == edited
    historical = store.load_revision(2)
    assert historical == confirmed
    assert decision_state(historical, historical.records[0]) == "confirmed"


def test_stale_expected_head_cannot_overwrite_existing_context(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    store.publish(initial, expected_head=None)
    before = store.head_path.read_bytes()
    with pytest.raises(ContextStoreConflict, match="head"):
        store.publish(_confirm(initial), expected_head="f" * 64)
    assert store.head_path.read_bytes() == before
    assert not (store.directory / "revisions" / "00000002.json").exists()


def test_live_and_stale_locks_are_never_broken_automatically(tmp_path: Path) -> None:
    import os

    store = ContextStore(tmp_path / "private")
    store.directory.mkdir()
    store.lock_path.write_bytes(b"held by another process")
    os.utime(store.lock_path, (1, 1))
    with pytest.raises(ContextStoreBusy, match="lock"):
        store.publish(_context(), expected_head=None)
    assert store.lock_path.read_bytes() == b"held by another process"
    assert store.lock_path.stat().st_mtime_ns == 1_000_000_000
    assert not store.head_path.exists()


def test_independent_process_lock_refuses_publication(tmp_path: Path) -> None:
    import subprocess
    import sys

    store = ContextStore(tmp_path / "private")
    store.directory.mkdir()
    script = (
        "import os,sys; "
        "fd=os.open(sys.argv[1], os.O_WRONLY|os.O_CREAT|os.O_EXCL); "
        "print('locked',flush=True); sys.stdin.readline(); os.close(fd); os.unlink(sys.argv[1])"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(store.lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(ContextStoreBusy, match="lock"):
            store.publish(_context(), expected_head=None)
        assert not store.head_path.exists()
        process.communicate("release\n", timeout=10)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.parametrize(
    "broken",
    [
        b"{invalid",
        b'{"schema_version":"9.0.0"}',
        b'{"schema_version":"1.0.0","schema_version":"9.0.0"}',
    ],
)
def test_malformed_or_unsupported_head_is_not_overwritten(tmp_path: Path, broken: bytes) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    store.publish(initial, expected_head=None)
    historical = (store.directory / "revisions" / "00000001.json").read_bytes()
    store.head_path.write_bytes(broken)
    with pytest.raises(ContextStoreError):
        store.load()
    with pytest.raises(ContextStoreError):
        store.publish(_confirm(initial), expected_head=context_digest(initial))
    assert store.head_path.read_bytes() == broken
    assert (store.directory / "revisions" / "00000001.json").read_bytes() == historical
    assert not store.lock_path.exists()


def test_changed_record_requires_the_next_revision(tmp_path: Path) -> None:
    initial = _context()
    with pytest.raises(ContextStoreError, match="revision"):
        put_record(initial, _requirement(text="An edited intent."), now=NOW)
    with pytest.raises(ContextStoreError, match="revision"):
        put_record(initial, _requirement(revision=3, text="An edited intent."), now=NOW)


def test_new_record_begins_at_revision_one() -> None:
    initial = _context()
    wrong = _requirement(revision=2).model_copy(update={"record_id": "requirement.two"})
    with pytest.raises(ContextStoreError, match="revision"):
        put_record(initial, wrong, now=NOW)


@pytest.mark.parametrize("digest_name", ["expected_record_digest", "expected_dependency_digest"])
def test_confirmation_requires_exact_presented_digests(digest_name: str) -> None:
    initial = _context()
    record = initial.records[0]
    arguments = dict(
        expected_record_digest=record_digest(record),
        expected_dependency_digest=dependency_digest(initial.baseline, record),
    )
    arguments[digest_name] = "f" * 64
    with pytest.raises(ContextStoreConflict, match="digest"):
        confirm_record(initial, record.record_id, actor="Fictional engineer", now=NOW, **arguments)
    assert initial.confirmations == ()


def test_confirmation_preserves_ai_proposal_provenance() -> None:
    initial = _context((_force(),))
    confirmed = _confirm(initial)
    assert confirmed.records[0].provenance.kind == "ai_proposal"
    assert decision_state(confirmed, confirmed.records[0]) == "confirmed"


@pytest.mark.parametrize(
    "change",
    [
        {"magnitude": ForceQuantity(state="unknown", unit="N", reason="Await engineer input")},
        {"direction": None},
        {"frame": None},
        {"provenance": Provenance(kind="unknown", source="Unavailable", reason="No source")},
    ],
)
def test_incomplete_force_cannot_be_confirmed(change: dict) -> None:
    force = _force().model_copy(update=change)
    initial = _context((force,))
    with pytest.raises(ContextStoreError, match="incomplete"):
        _confirm(initial)
    assert initial.confirmations == ()


def test_invalid_frame_cannot_be_confirmed() -> None:
    scaled = ((2.0, 0.0, 0.0, 0.0), *IDENTITY[1:])
    force = _force().model_copy(
        update={"frame": _force().frame.model_copy(update={"transform": scaled})}
    )
    with pytest.raises(ContextStoreError, match="invalid|Invalid"):
        _confirm(_context((force,)))


def test_empty_actor_cannot_issue_confirmation() -> None:
    initial = _context()
    record = initial.records[0]
    with pytest.raises(ContextStoreError, match="actor"):
        confirm_record(
            initial,
            record.record_id,
            actor="  ",
            now=NOW,
            expected_record_digest=record_digest(record),
            expected_dependency_digest=dependency_digest(initial.baseline, record),
        )


def test_removing_or_altering_historical_receipt_is_refused(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    confirmed = _confirm(initial)
    store.publish(initial, expected_head=None)
    store.publish(confirmed, expected_head=context_digest(initial))
    deleted = next_artifact(confirmed, confirmations=(), now=NOW)
    altered = next_artifact(
        confirmed,
        confirmations=(confirmed.confirmations[0].model_copy(update={"actor": "Different actor"}),),
        now=NOW,
    )
    for candidate in (deleted, altered):
        with pytest.raises(ContextStoreError, match="receipt"):
            store.publish(candidate, expected_head=context_digest(confirmed))
    assert store.load() == confirmed


def test_removing_record_is_refused_in_first_slice(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    store.publish(initial, expected_head=None)
    with pytest.raises(ContextStoreError, match="record"):
        store.publish(
            next_artifact(initial, records=(), now=NOW), expected_head=context_digest(initial)
        )
    assert store.load() == initial


def test_forged_confirmation_cannot_enter_history(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    store.publish(initial, expected_head=None)
    receipt = _confirm(initial).confirmations[0].model_copy(update={"record_digest": "f" * 64})
    forged = next_artifact(initial, confirmations=(receipt,), now=NOW)
    with pytest.raises(ContextStoreError, match="receipt"):
        store.publish(forged, expected_head=context_digest(initial))
    assert store.load() == initial


def test_restoring_old_input_cannot_resurrect_old_decision(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    confirmed = _confirm(initial)
    edited = put_record(confirmed, _requirement(revision=2, text="Changed requirement."), now=NOW)
    for previous, context in ((None, initial), (initial, confirmed), (confirmed, edited)):
        store.publish(context, expected_head=context_digest(previous) if previous else None)
    rollback = next_artifact(edited, records=initial.records, now=NOW)
    with pytest.raises(ContextStoreError, match="revision"):
        store.publish(rollback, expected_head=context_digest(edited))
    assert decision_state(store.load(), store.load().records[0]) == "needs_review"


def test_model_copy_cannot_bypass_schema_validation(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    invalid = _context().model_copy(update={"schema_version": "9.0.0"})
    with pytest.raises(ContextStoreError, match="version|invalid"):
        store.publish(invalid, expected_head=None)
    assert not store.head_path.exists()


def test_head_write_failure_keeps_old_valid_revision_and_allows_exact_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from swreview import atomic

    store = ContextStore(tmp_path / "private")
    initial = _context()
    store.publish(initial, expected_head=None)
    candidate = _confirm(initial)
    previous_bytes = store.head_path.read_bytes()
    real_replace = atomic.os.replace

    def failed_head_replace(source, destination):
        if Path(destination) == store.head_path:
            raise OSError("fictional head replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(atomic.os, "replace", failed_head_replace)
    with pytest.raises(ContextStoreError, match="publish"):
        store.publish(candidate, expected_head=context_digest(initial))
    assert store.head_path.read_bytes() == previous_bytes
    assert store.load() == initial
    assert not store.lock_path.exists()
    with pytest.raises(ContextStoreError, match="published"):
        store.load_revision(2)
    monkeypatch.setattr(atomic.os, "replace", real_replace)
    assert store.publish(candidate, expected_head=context_digest(initial)) == candidate
    assert store.load() == candidate


def test_different_orphan_revision_is_never_overwritten(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    store.publish(initial, expected_head=None)
    orphan = _confirm(initial)
    from swreview.engineering_context.models import canonical_bytes

    history = store.directory / "revisions" / "00000002.json"
    history.write_bytes(canonical_bytes(orphan))
    changed = put_record(initial, _requirement(revision=2, text="Different revision."), now=NOW)
    with pytest.raises(ContextStoreConflict, match="revision"):
        store.publish(changed, expected_head=context_digest(initial))
    assert history.read_bytes() == canonical_bytes(orphan)
    assert store.load() == initial


def test_tampered_published_history_is_not_silently_repaired(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    store.publish(initial, expected_head=None)
    confirmed = _confirm(initial)
    store.publish(confirmed, expected_head=context_digest(initial))
    history = store.directory / "revisions" / "00000001.json"
    history.write_bytes(b"{}")
    before = store.head_path.read_bytes()
    with pytest.raises(ContextStoreError):
        store.load()
    with pytest.raises(ContextStoreError):
        store.publish(next_artifact(confirmed, now=NOW), expected_head=context_digest(confirmed))
    assert store.head_path.read_bytes() == before
    assert history.read_bytes() == b"{}"


def test_baseline_change_cannot_allow_old_approval_to_revive(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "private")
    initial = _context()
    confirmed = _confirm(initial)
    store.publish(initial, expected_head=None)
    store.publish(confirmed, expected_head=context_digest(initial))
    newer_baseline = confirmed.baseline.model_copy(update={"package_sha256": "b" * 64})
    changed = confirmed.model_copy(
        update={
            "revision": 3,
            "previous_digest": context_digest(confirmed),
            "baseline": newer_baseline,
        }
    )
    with pytest.raises(ContextStoreError, match="baseline"):
        store.publish(changed, expected_head=context_digest(confirmed))
    with pytest.raises(ContextStoreError, match="baseline"):
        next_artifact(confirmed, baseline=newer_baseline, now=NOW)
    assert store.load() == confirmed
    assert not (store.history_directory / "00000003.json").exists()


def test_invalid_copied_values_emit_no_private_serialization_warning(tmp_path: Path) -> None:
    import warnings

    private_source = str(tmp_path / "FICT-SOURCE.sldprt")
    malformed_force = _force().model_copy(update={"direction": (private_source, 0.0, 0.0)})
    invalid = _context().model_copy(update={"records": (malformed_force,)})
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        with pytest.raises(ContextStoreError, match="Invalid") as caught:
            ContextStore(tmp_path / "private").publish(invalid, expected_head=None)
    assert emitted == []
    assert private_source not in str(caught.value)


def test_cli_does_not_echo_private_path_in_malformed_direction(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from swreview.engineering_context.cli import app

    private_source = str(tmp_path / "FICT-SOURCE.sldprt")
    result = CliRunner().invoke(
        app,
        [
            "force",
            str(tmp_path / "package"),
            "--store",
            str(tmp_path / "private"),
            "--id",
            "force.one",
            "--kind",
            "component",
            "--entity",
            "component.one",
            "--expected-head",
            "a" * 64,
            "--direction",
            private_source + ",0,0",
        ],
    )
    assert result.exit_code == 1
    assert private_source not in result.output


def test_invalid_copied_receipt_actor_cannot_enter_storage(tmp_path: Path) -> None:
    initial = _context()
    confirmed = _confirm(initial)
    bad_receipt = confirmed.confirmations[0].model_copy(update={"actor": "  "})
    malformed = confirmed.model_copy(update={"confirmations": (bad_receipt,)})
    store = ContextStore(tmp_path / "private")
    store.publish(initial, expected_head=None)
    with pytest.raises(ContextStoreError, match="Invalid"):
        store.publish(malformed, expected_head=context_digest(initial))
    assert store.load() == initial


def test_nonrepresentable_canonical_force_stays_a_draft(tmp_path: Path) -> None:
    force = _force().model_copy(
        update={
            "magnitude": ForceQuantity(state="known", value=1e308, unit="kN"),
        }
    )
    initial = _context((force,))
    store = ContextStore(tmp_path / "private")
    store.publish(initial, expected_head=None)
    with pytest.raises(ContextStoreError, match="canonical"):
        _confirm(initial)
    assert store.load() == initial
    assert decision_state(store.load(), store.load().records[0]) == "draft"


@pytest.mark.parametrize("segment", ["answer_keys", "case_files"])
def test_withheld_directory_is_refused_before_read_or_creation(
    tmp_path: Path, segment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "benchmarks" / segment / "fictional-context"
    reads = []

    def unexpected_read(path: Path) -> bytes:
        reads.append(path)
        raise AssertionError("withheld contents must not be read")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    with pytest.raises(ContextStoreError, match="withheld") as caught:
        ContextStore(private).load()
    assert str(private) not in str(caught.value)
    assert reads == []
    assert not private.exists()


@pytest.mark.parametrize("segment", ["answer_keys", "case_files"])
def test_link_to_withheld_directory_is_refused_without_private_path_output(
    tmp_path: Path, segment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    withheld = tmp_path / "benchmarks" / segment / "fictional-target"
    withheld.mkdir(parents=True)
    link = tmp_path / "ordinary-link"
    _directory_link(link, withheld)
    reads = []

    def unexpected_read(path: Path) -> bytes:
        reads.append(path)
        raise AssertionError("withheld contents must not be read")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    with pytest.raises(ContextStoreError, match="withheld") as caught:
        ContextStore(link / "context").load()
    assert str(withheld) not in str(caught.value)
    assert str(link) not in str(caught.value)
    assert reads == []
    assert not (withheld / "context").exists()
