"""Regression tests for the bounded automatic package context brief."""

from __future__ import annotations

from swreview.agent.package_brief import (
    MAX_BRIEF_BYTES,
    MAX_COMPONENT_ROWS,
    MAX_DOCUMENT_ROWS,
    MAX_MATE_ROWS,
    package_brief,
)
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import start_review
from swreview.ir.loader import save_package
from swreview.ir.models import DumpPhase, Mate, MateEntity
from swreview.report.session import load_session
from tests.support.packages import build_package, persist_ref


def test_brief_contains_context_without_paths_or_custom_properties() -> None:
    brief = package_brief(build_package())

    assert "root_kind=assembly" in brief
    assert "active_configuration=Default" in brief
    assert "revision=B" in brief
    assert "material=6061-T6" in brief
    assert "state=resolved" in brief
    assert "candidates: documents=2 components=2" in brief
    assert "/Designs/" not in brief
    assert "native/cover-assy.SLDASM" not in brief
    assert "Project" not in brief
    assert "pilot" not in brief


def test_brief_strips_windows_and_posix_prefixes_from_file_names() -> None:
    package = build_package()
    package.documents[0].file_name = r"C:\private\customer\cover-assy.SLDASM"
    package.documents[1].file_name = "/private/customer/housing.SLDPRT"

    brief = package_brief(package)

    assert "C:\\private\\customer\\cover-assy.SLDASM" not in brief
    assert "/private/customer/housing.SLDPRT" not in brief
    assert "cover-assy.SLDASM" in brief
    assert "housing.SLDPRT" in brief


def test_brief_prioritizes_unresolved_components_and_names_missing_evidence() -> None:
    package = build_package()
    package.components[1].suppression = "lightweight"
    package.gaps[0].kind = "unsupported"
    package.extractor.phases = [
        DumpPhase(name="hole", elapsed_ms=None, status="skipped"),
    ]

    brief = package_brief(package)

    assert "non_resolved=1 (1 shown below)" in brief
    assert "state=lightweight" in brief
    assert "gaps=1 (unsupported=1)" in brief
    assert "skipped_phases=hole" in brief


def test_brief_is_bounded_and_reports_row_omissions() -> None:
    package = build_package()
    for index in range(MAX_COMPONENT_ROWS + 9):
        package.components.append(
            package.components[0].model_copy(
                update={
                    "id": f"cmp:{index + 10:04d}",
                    "name": "component " + ("x" * 500),
                    "full_path": f"assembly/component-{index}",
                    "parent_id": None,
                }
            )
        )
    for index in range(MAX_DOCUMENT_ROWS + 4):
        package.documents.append(
            package.documents[1].model_copy(
                update={
                    "document_id": f"doc:{index + 10}",
                    "file_name": "part-" + ("y" * 500) + ".SLDPRT",
                }
            )
        )

    brief = package_brief(package)

    assert len(brief.encode("utf-8")) <= MAX_BRIEF_BYTES
    assert "component_rows: shown=" in brief
    assert f"total={len(package.components)}" in brief
    assert "document_rows: shown=" in brief
    assert f"total={len(package.documents)}" in brief
    assert "omitted=" in brief
    assert "full paths omitted" in brief


def test_explicit_standards_failure_is_visible_without_leaking_profile_path() -> None:
    class Gap:
        reason = "the profile at '/private/standards.yaml' could not be loaded: invalid"

    brief = package_brief(build_package(), standards_gap=Gap())

    assert "configured standards profile could not be loaded" in brief
    assert "/private/standards.yaml" not in brief


def test_start_review_surfaces_configured_standards_failure_when_gate_is_off(tmp_path) -> None:
    package_dir = tmp_path / "package"
    save_package(build_package(), package_dir)
    profile = tmp_path / "missing-standards.yaml"
    run = start_review(
        package_dir,
        tmp_path / "run",
        provider=FakeProvider(script=[ScriptedTurn(text="done")], model="fake-scripted"),
        standards_profile=profile,
    )
    run.start()

    opening = str(run.messages[0]["content"])
    assert "configured standards profile could not be loaded" in opening
    assert str(profile) not in opening
    session = load_session(tmp_path / "run" / "session.json")
    standards = [
        item
        for item in session.coverage.skipped
        if item.check == "coverage.prerun.standards"
    ]
    assert len(standards) == 1
    assert "could not be loaded" in standards[0].reason


def test_brief_is_deterministic_for_same_package() -> None:
    package = build_package()
    assert package_brief(package) == package_brief(package)


def test_brief_bounds_untrusted_identifiers_and_handles_parent_cycles() -> None:
    package = build_package()
    package.design.name = "design-" + ("x" * 500)
    package.design.root_assembly_document_id = "root-" + ("r" * 500)
    package.extractor.profile = "profile-" + ("p" * 500)
    package.components[0].parent_id = package.components[1].id
    package.components[1].parent_id = package.components[0].id

    brief = package_brief(package)

    assert len(brief.encode("utf-8")) <= MAX_BRIEF_BYTES
    assert len(max(brief.splitlines(), key=len)) < 500
    assert "design-" + ("x" * 100) not in brief


def test_non_resolved_count_reports_only_rows_that_fit() -> None:
    package = build_package()
    for index in range(MAX_COMPONENT_ROWS + 5):
        package.components.append(
            package.components[0].model_copy(
                update={
                    "id": f"lightweight:{index}",
                    "suppression": "lightweight",
                    "name": "long component name " + ("x" * 200),
                    "parent_id": None,
                }
            )
        )

    brief = package_brief(package)

    assert f"non_resolved={MAX_COMPONENT_ROWS + 5}" in brief
    assert "shown below)" in brief
    shown = int(brief.split("non_resolved=", 1)[1].split(" (", 1)[1].split(" ", 1)[0])
    assert 0 < shown <= MAX_COMPONENT_ROWS


def test_brief_includes_bounded_extracted_mate_connections() -> None:
    package = build_package()
    package.mates = [
        Mate(
            id=f"mate:{index:04d}",
            persist_ref=persist_ref(f"mate:{index}"),
            persist_ref_scope="doc:1",
            type="Concentric",
            entities=[
                MateEntity(
                    component_id="cmp:0001",
                    persist_ref=persist_ref(f"mate:{index}:a"),
                    entity_kind="face",
                ),
                MateEntity(
                    component_id="cmp:0002",
                    persist_ref=persist_ref(f"mate:{index}:b"),
                    entity_kind="face",
                ),
            ],
            alignment="aligned",
            suppressed=index == 1,
            distance=None,
            angle=None,
        )
        for index in range(MAX_MATE_ROWS + 2)
    ]

    brief = package_brief(package)

    assert "extracted mate connections (package scope only; no completeness implied):" in brief
    assert f"mate_rows: shown={MAX_MATE_ROWS} total={MAX_MATE_ROWS + 2} omitted=2" in brief
    assert "type=Concentric state=active entities=cmp:0001,cmp:0002" in brief
    assert "state=suppressed" in brief
    assert "cmp:0001,cmp:0002" in brief
    assert len(brief.encode("utf-8")) <= MAX_BRIEF_BYTES
