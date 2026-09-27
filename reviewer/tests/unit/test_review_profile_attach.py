"""The profile a review loads once, and what every check reads it from (feature 013 T019).

`specs/013-engineer-first-review/contracts/part-roles.md` section 5 is normative.
`attach_standards` takes the profile `start_review` loaded (`ReviewProfile`) instead of loading
it again, and its four refusal reasons stay byte-identical to the path form's. It records the
loaded profile on the context whether or not the standards run attaches, and
`review_profile(context)` - which replaces `_attached_profile` - returns it: before this, a valid
profile made hygiene say "no standards profile is attached" whenever the standards phases were
not dumped, because the profile was only reachable through the standards run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swreview.checks.hygiene import CHECK_PART_NUMBER
from swreview.checks.standards.profile import load_profile, load_review_profile
from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from swreview.prerun import attach_standards
from swreview.tools.checks_mechanical import check_hygiene, review_profile
from swreview.tools.context import context_for, use_context
from swreview.tools.standards_checks import standards_run
from tests.support.prerun import STANDARDS_PROFILE

TESTS = Path(__file__).resolve().parents[1]
PLATE_DRAWING = TESTS / "fixtures" / "drawings" / "plate-drawing"


def dumped() -> EvidencePackage:
    """A package the standards phases ran on."""
    return load_package(PLATE_DRAWING).package


def not_dumped() -> EvidencePackage:
    """The same package with no phase row: every standards phase reads as never run."""
    package = dumped()
    return package.model_copy(
        update={"extractor": package.extractor.model_copy(update={"phases": []})}
    )


def rootless() -> EvidencePackage:
    """The same package whose root document was never saved: the traversal refuses it."""
    package = dumped()
    root = package.design.root_assembly_document_id
    return package.model_copy(
        update={
            "documents": [
                document.model_copy(update={"path": ""})
                if document.document_id == root
                else document
                for document in package.documents
            ]
        }
    )


def reason(package: EvidencePackage, profile: object) -> str | None:
    gap = attach_standards(context_for(package), profile)  # type: ignore[arg-type]
    return None if gap is None else gap.reason


# --- the four refusal reasons are the path form's, byte for byte --------------------------------


def test_no_profile_gives_the_same_reason(tmp_path: Path) -> None:
    assert reason(dumped(), load_review_profile(None)) == reason(dumped(), None)
    assert reason(dumped(), None) == "no profile was configured for this review"


def test_an_unreadable_profile_gives_the_same_reason(tmp_path: Path) -> None:
    missing = tmp_path / "absent.yaml"

    loaded = reason(dumped(), load_review_profile(missing))

    assert loaded == reason(dumped(), missing)
    assert loaded is not None and loaded.startswith(f"the profile at {missing} could not be loaded")


def test_phases_not_dumped_give_the_same_reason() -> None:
    loaded = reason(not_dumped(), load_review_profile(STANDARDS_PROFILE))

    assert loaded == reason(not_dumped(), STANDARDS_PROFILE)
    assert loaded is not None and loaded.startswith("the package was not dumped")


def test_an_ungradable_root_gives_the_same_reason() -> None:
    loaded = reason(rootless(), load_review_profile(STANDARDS_PROFILE))

    assert loaded == reason(rootless(), STANDARDS_PROFILE)
    assert loaded is not None and loaded.startswith("the root document cannot be graded")


def test_a_loaded_profile_attaches_the_run_exactly_as_a_path_does() -> None:
    by_loaded = context_for(dumped())
    by_path = context_for(dumped())

    assert attach_standards(by_loaded, load_review_profile(STANDARDS_PROFILE)) is None
    assert attach_standards(by_path, STANDARDS_PROFILE) is None

    loaded_run, path_run = standards_run(by_loaded), standards_run(by_path)
    assert loaded_run is not None and path_run is not None
    assert loaded_run.profile.identity == path_run.profile.identity
    assert loaded_run.documents == path_run.documents


# --- review_profile ------------------------------------------------------------------------------


def test_the_profile_is_there_even_when_the_standards_phases_were_not_dumped() -> None:
    context = context_for(not_dumped())

    assert attach_standards(context, load_review_profile(STANDARDS_PROFILE)) is not None

    profile = review_profile(context)
    assert standards_run(context) is None
    assert profile is not None
    assert profile.identity == load_profile(STANDARDS_PROFILE).identity


@pytest.mark.parametrize("given", ["none", "refused"])
def test_no_profile_or_a_refused_one_reads_as_none(tmp_path: Path, given: str) -> None:
    context = context_for(dumped())
    loaded = load_review_profile(None if given == "none" else tmp_path / "absent.yaml")

    attach_standards(context, loaded)

    assert review_profile(context) is None


def test_a_context_nobody_attached_a_profile_to_reads_as_none() -> None:
    assert review_profile(context_for(dumped())) is None


def test_a_standards_run_attached_directly_is_still_read() -> None:
    """A check run attaches the standards run itself; its profile is the review's."""
    from swreview.checks.standards.traversal import graded_documents
    from swreview.tools.standards_checks import StandardsRun, attach_standards_run

    context = context_for(dumped())
    profile = load_profile(STANDARDS_PROFILE)
    attach_standards_run(context, StandardsRun(profile, graded_documents(context.ir, profile)))

    assert review_profile(context) is profile


def test_hygiene_reads_the_profile_when_the_standards_phases_were_not_dumped() -> None:
    """The latent coupling: hygiene said "no standards profile is attached" here."""
    context = context_for(not_dumped())
    attach_standards(context, load_review_profile(STANDARDS_PROFILE))

    with use_context(context):
        result = check_hygiene()

    assert result["profile"] == "attached"
    skipped = context.require_session().coverage.skipped
    assert not any(
        item.check == CHECK_PART_NUMBER and "no standards profile is attached" in item.reason
        for item in skipped
    )
