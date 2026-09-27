"""Provenance is closed by code at setup, never asked (feature 013 T059).

`contracts/re-ask-guard.md` section 2. `checks/provenance.close_provenance(package)` is pure: with
no manifest discrepancy - always, on the native path - it gives one `checked` row, check
`provenance`, over every part and assembly document and the root's configuration, whose reason
counts the documents and the revisions read and says the open files are taken as the latest; with
discrepancies (only an ingested package has them) it gives one `provenance.<kind>` finding each, in
`DISCREPANCY_SEVERITY` order, and no row. It never writes a question. `start_review` records it
once, right after the partial-evidence row, whatever levers are on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from swreview.agent import runner
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.settings import EfficiencySettings
from swreview.checks.provenance import (
    CLOSED_REASON,
    DISCREPANCY_SEVERITY_OF,
    PROVENANCE_CHECK,
    close_provenance,
)
from swreview.ingest.manifest import DISCREPANCY_SEVERITY
from swreview.ir.loader import save_package
from swreview.ir.models import Discrepancy, Document, EvidencePackage
from tests.support.packages import build_package

EXPECTED_REASON = (
    "Reviewed as open in SOLIDWORKS: 2 documents, each at its own path in its active "
    "configuration; revision read on 2 of 2. The open files are taken as the latest: vault "
    "version and local modification are not read and never asked. A missing revision is "
    "reported by the hygiene checks."
)


def discrepancy(kind: str, document_id: str = "doc:2") -> Discrepancy:
    return Discrepancy(
        document_id=document_id, kind=kind, expected="7", actual="6", note=f"a fictional {kind}"
    )


def with_discrepancies(*kinds: str) -> EvidencePackage:
    package = build_package()
    manifest = package.manifest.model_copy(
        update={"discrepancies": [discrepancy(kind) for kind in kinds]}
    )
    return package.model_copy(update={"manifest": manifest})


# --- 1. the native path: one checked row -------------------------------------------------------


def test_a_native_package_gives_one_checked_row_and_no_finding() -> None:
    outcome = close_provenance(build_package())

    assert outcome.findings == ()
    assert outcome.coverage is not None
    assert outcome.coverage.check == PROVENANCE_CHECK == "provenance"
    assert outcome.coverage.reason == EXPECTED_REASON
    assert outcome.coverage.scope.document_ids == ["doc:1", "doc:2"]
    assert outcome.coverage.scope.configuration == "Default"
    assert outcome.coverage.source == "code"


def test_the_reason_is_the_contracts_sentence() -> None:
    assert CLOSED_REASON.format(documents="2 documents", n=2, k=2) == EXPECTED_REASON


def test_one_document_is_counted_in_the_singular() -> None:
    package = build_package()
    package = package.model_copy(update={"documents": package.documents[:1]})

    outcome = close_provenance(package)

    assert outcome.coverage is not None
    assert outcome.coverage.reason.startswith(
        "Reviewed as open in SOLIDWORKS: 1 document, each at its own path"
    )
    assert "revision read on 1 of 1." in outcome.coverage.reason


def test_a_document_with_no_manifest_entry_or_no_revision_is_counted_unread() -> None:
    package = build_package()
    entries = [
        package.manifest.entries[0].model_copy(update={"revision": None}),
    ]  # doc:2 has no entry at all
    package = package.model_copy(
        update={"manifest": package.manifest.model_copy(update={"entries": entries})}
    )

    outcome = close_provenance(package)

    assert outcome.coverage is not None
    assert "revision read on 0 of 2." in outcome.coverage.reason


def test_a_drawing_document_is_not_counted() -> None:
    package = build_package()
    drawing = Document(
        document_id="doc:9",
        kind="drawing",
        file_name="housing.SLDDRW",
        path="native/housing.SLDDRW",
        configurations=[],
        active_configuration="",
        custom_properties={},
        config_properties={},
        material=None,
        mass=None,
    )
    package = package.model_copy(update={"documents": [*package.documents, drawing]})

    outcome = close_provenance(package)

    assert outcome.coverage is not None
    assert outcome.coverage.scope.document_ids == ["doc:1", "doc:2"]
    assert "2 documents" in outcome.coverage.reason


def test_close_provenance_is_pure() -> None:
    package = build_package()
    before = package.model_dump(mode="json")

    assert close_provenance(package) == close_provenance(package)
    assert package.model_dump(mode="json") == before


# --- 2. an ingested package: one finding per discrepancy ---------------------------------------


def test_each_discrepancy_is_one_finding_in_severity_order() -> None:
    kinds = tuple(reversed(DISCREPANCY_SEVERITY))

    outcome = close_provenance(with_discrepancies(*kinds))

    assert outcome.coverage is None
    assert [item.result.check for item in outcome.findings] == [
        f"provenance.{kind}" for kind in DISCREPANCY_SEVERITY
    ]
    for item in outcome.findings:
        kind = item.result.check.removeprefix("provenance.")
        assert item.result.status == "demonstrated"
        assert item.result.severity == DISCREPANCY_SEVERITY_OF[kind]
        assert item.result.calculation is not None
        assert item.document_ids == ("doc:2",)


def test_every_discrepancy_kind_has_a_severity() -> None:
    assert set(DISCREPANCY_SEVERITY_OF) == set(DISCREPANCY_SEVERITY)
    severities = [DISCREPANCY_SEVERITY_OF[kind] for kind in DISCREPANCY_SEVERITY]
    order = ["high", "medium", "low", "info"]
    assert severities == sorted(severities, key=order.index)


def test_a_discrepancy_on_a_document_the_manifest_does_not_hold_binds_the_root() -> None:
    package = with_discrepancies("missing_document")
    manifest = package.manifest.model_copy(
        update={"discrepancies": [discrepancy("missing_document", "doc:7")]}
    )
    package = package.model_copy(update={"manifest": manifest})

    [item] = close_provenance(package).findings

    assert item.document_ids == ("doc:1",)
    assert "doc:7" in item.result.observed


# --- 3. start_review records it once, whatever the levers --------------------------------------


def review(tmp_path: Path, package: EvidencePackage | None = None, **options: Any) -> Any:
    folder = tmp_path / "run-0001"
    save_package(package or build_package(), folder)
    events: list[tuple[str, dict[str, Any]]] = []
    run = runner.start_review(
        folder,
        folder,
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        callbacks=[lambda event: events.append((event.type, dict(event.body)))],
        **options,
    )
    return run, events


def provenance_rows(run: Any) -> list[tuple[str, Any]]:
    return [
        (bucket, item)
        for bucket in ("checked", "skipped", "unresolved", "failed", "out_of_scope")
        for item in getattr(run.session.coverage, bucket)
        if item.check == PROVENANCE_CHECK
    ]


@pytest.mark.parametrize(
    "efficiency",
    [
        None,
        EfficiencySettings(prerun_checks=True),
        EfficiencySettings(procedural_gate=True),
        EfficiencySettings(prerun_checks=True, procedural_gate=True),
    ],
    ids=["plain", "checks-first", "gate", "checks-first-and-gate"],
)
def test_the_row_is_written_exactly_once_whatever_the_levers(
    tmp_path: Path, efficiency: EfficiencySettings | None
) -> None:
    run, _ = review(tmp_path, efficiency=efficiency)

    [(bucket, item)] = provenance_rows(run)
    assert bucket == "checked" and item.reason == EXPECTED_REASON


def test_the_row_is_announced_after_the_session_starts(tmp_path: Path) -> None:
    run, events = review(tmp_path)

    kinds = [kind for kind, _ in events]
    announced = [
        index
        for index, (kind, body) in enumerate(events)
        if kind == "coverage" and body["item"]["check"] == PROVENANCE_CHECK
    ]
    assert kinds[0] == "session.started"
    assert len(announced) == 1 and announced[0] > 0


def test_a_retry_writes_its_own_row_once(tmp_path: Path) -> None:
    first, _ = review(tmp_path / "first")
    retried, _ = review(tmp_path / "retry", retry_of=first.session.session_id)

    assert len(provenance_rows(retried)) == 1


def test_finishing_the_review_keeps_one_row_and_asks_nothing(tmp_path: Path) -> None:
    run, _ = review(tmp_path)

    run.start()
    run.finalize()

    assert len(provenance_rows(run)) == 1
    assert [request for request in run.session.evidence_requests
            if request.blocks == PROVENANCE_CHECK] == []


def test_a_command_line_review_writes_it_too(tmp_path: Path) -> None:
    folder = tmp_path / "run-0001"
    save_package(build_package(), folder)

    session = runner.run_review(
        folder,
        tmp_path / "out",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
    )

    assert [item.check for item in session.coverage.checked].count(PROVENANCE_CHECK) == 1


def test_an_ingested_package_records_its_discrepancies_as_findings_and_no_row(
    tmp_path: Path,
) -> None:
    run, events = review(tmp_path, with_discrepancies("version_mismatch", "local_modification"))

    checks = [finding.check for finding in run.session.findings]
    assert checks == ["provenance.local_modification", "provenance.version_mismatch"]
    assert provenance_rows(run) == []
    assert [kind for kind, _ in events].count("finding") == 2


def test_with_no_profile_the_row_is_still_written(tmp_path: Path) -> None:
    run, _ = review(tmp_path, standards_profile=None)

    assert len(provenance_rows(run)) == 1


def test_a_missing_revision_leaves_provenance_checked_and_names_the_hygiene_checks(
    tmp_path: Path,
) -> None:
    """The revision is hygiene's to report on a custom part (feature 010), never a question."""
    package = build_package()
    entries = [
        entry.model_copy(update={"revision": None}) if entry.document_id == "doc:2" else entry
        for entry in package.manifest.entries
    ]
    package = package.model_copy(
        update={"manifest": package.manifest.model_copy(update={"entries": entries})}
    )

    run, _ = review(tmp_path, package)

    [(bucket, item)] = provenance_rows(run)
    assert bucket == "checked"
    assert "revision read on 1 of 2." in item.reason
    assert item.reason.endswith("A missing revision is reported by the hygiene checks.")
