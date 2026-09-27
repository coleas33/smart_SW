"""The sitting-shaped fixture carries no recorded string, and is exactly what its generator writes
(feature 013 T012).

The repository is public and `tests/fixtures/sitting/small-assembly/` is shaped like the small
assembly the 2026-09-26 sitting reviewed. It is built by `tests/support/sitting.py` from
fictional strings, and this module proves it the way feature 010's fictional-fixture test does:

1. **paths**: every document path, manifest vault path and drawing-candidate path starts with
   the fictional root;
2. **names**: every file name, configuration, property name and value, component name and
   path, feature name and description, gap reason and question string is built from the
   builder's vocabulary (its letter runs; digits identify nothing);
3. **the owner's denylist**: when `%LOCALAPPDATA%\\SwReview\\fixture-denylist.txt` exists, no
   token of it occurs in any string value; where it does not, which is every CI machine, that
   half is skipped naming the file;
4. **regeneration**: running the generator writes exactly the committed bytes.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from tests.support.fixture_denylist import (
    DENYLIST_PATH,
    json_strings,
    load_denylist,
    offending_tokens,
)
from tests.support.sitting import FICTIONAL_ROOT, fictional_offences, render

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sitting" / "small-assembly"


def package() -> EvidencePackage:
    return load_package(FIXTURE).package


def questions() -> dict[str, Any]:
    return json.loads((FIXTURE / "questions.json").read_text(encoding="utf-8"))


def named_strings(subject: EvidencePackage) -> Iterator[tuple[str, str]]:
    """`(where, text)` for every name and value the fixture composes."""
    yield "design.name", subject.design.name
    for document in subject.documents:
        yield f"{document.document_id}.file_name", document.file_name
        yield f"{document.document_id}.path", document.path
        for configuration in document.configurations:
            yield f"{document.document_id}.configuration", configuration
        for key, value in document.custom_properties.items():
            yield f"{document.document_id}.property", key
            yield f"{document.document_id}.value", value
        for configuration, properties in document.config_properties.items():
            yield f"{document.document_id}.configuration", configuration
            for key, value in properties.items():
                yield f"{document.document_id}.property", key
                yield f"{document.document_id}.value", value
    for component in subject.components:
        yield f"{component.id}.name", component.name
        yield f"{component.id}.full_path", component.full_path
        yield f"{component.id}.configuration", component.referenced_configuration
    for row in subject.features:
        yield f"{row.id}.name", row.name
        yield f"{row.id}.description", row.description or ""
    for entry in subject.manifest.entries:
        yield f"{entry.document_id}.vault_path", entry.vault_path
    for candidate in subject.drawing_candidates:
        yield f"{candidate.document_id}.candidate", candidate.path
    for gap in subject.gaps:
        yield f"gap {gap.entity_kind}", gap.reason
    for text in json_strings(questions()):
        yield "questions.json", text


def test_the_fixture_validates_as_a_package() -> None:
    subject = package()

    assert subject.design.root_assembly_document_id == "doc:1"
    assert {document.kind for document in subject.documents} == {"assembly", "part"}


def test_every_path_is_under_the_fictional_root() -> None:
    subject = package()
    paths = [
        *(document.path for document in subject.documents),
        *(entry.vault_path for entry in subject.manifest.entries),
        *(candidate.path for candidate in subject.drawing_candidates),
    ]

    assert paths
    assert [path for path in paths if not path.startswith(FICTIONAL_ROOT)] == []


def test_every_string_is_built_from_the_builders_vocabulary() -> None:
    offences = [
        f"{where}: {offence}"
        for where, text in named_strings(package())
        for offence in fictional_offences(text)
    ]

    assert offences == []


def test_no_denylisted_token_occurs_in_any_string() -> None:
    denylist = load_denylist()
    if denylist is None:
        pytest.skip(f"no fixture denylist at {DENYLIST_PATH}; the scan runs on the owner's machine")
    offending = [
        where for where, text in named_strings(package()) if offending_tokens(text, denylist)
    ]

    # Where only, never the token: a denylisted token is a recorded string.
    assert offending == []


def test_the_generator_reproduces_every_byte() -> None:
    # As git stores them: `.gitattributes` marks `*.json` as text, so a Windows checkout with
    # `core.autocrlf` may hand the files back with CRLF endings; the generator writes LF.
    written = {
        path.name: path.read_bytes().replace(b"\r\n", b"\n")
        for path in FIXTURE.iterdir()
        if path.is_file()
    }

    assert render() == written, "regenerate with generate_fixture.py; never edit it by hand"


def test_the_shape_the_part_role_tests_read() -> None:
    """The facts `test_part_roles.py` classifies, pinned where they are built."""
    subject = package()
    by_id = {document.document_id: document for document in subject.documents}
    assembly, plate, pin = by_id["doc:1"], by_id["doc:2"], by_id["doc:3"]

    assert assembly.file_name.rsplit(".", 1)[0] == plate.file_name.rsplit(".", 1)[0]
    assert [component.document_id for component in subject.components].count("doc:3") == 2
    assert "Meridian Part Ref" not in pin.custom_properties
    assert "MeridianPartRef" in pin.custom_properties
    assert {candidate.document_id for candidate in subject.drawing_candidates} == {"doc:1", "doc:2"}
    assert len({candidate.path for candidate in subject.drawing_candidates}) == 1
    assert all(
        entry.vault_version is None and entry.local_modified is None
        for entry in subject.manifest.entries
    )
    shaft = next(component for component in subject.components if component.document_id == "doc:6")
    drive = next(component for component in subject.components if component.document_id == "doc:5")
    assert shaft.parent_id == drive.id
    assert shaft.suppression == "lightweight"


def test_the_second_turn_repeats_its_requests_word_for_word() -> None:
    script = questions()
    first = [call["arguments"] for call in script["first_turn"]]

    assert len(first) == 5
    assert set(script["answers"]) == {f"ER-00{number}" for number in range(1, 6)}
    assert [call["repeats"] for call in script["second_turn"]] == ["ER-002", "ER-003", "ER-005"]
    for call in script["second_turn"]:
        assert call["arguments"] == first[int(call["repeats"][3:]) - 1]
