"""No recorded string reaches the committed drawing fixtures (feature 011 T011).

The repository is public, and no recorded package carries a drawing, so the fixtures under
`tests/fixtures/drawings/` are built by code from fictional strings (`tests/support/drawings.py`,
on feature 010's builders). This module proves it three ways, as feature 010's
`test_mechanical_fixtures_are_fictional.py` does for its own fixtures:

1. **paths**: every document path, manifest vault path, candidate path, view model path,
   sheet format path and unresolved bill-of-materials path starts with the fictional root;
2. **strings**: every name the drawing builders compose - file names, property values,
   configurations, sheet, view and orientation names, format and standard names, dimension
   names and text parts, hole-callout variables, frame symbols and values, datum labels,
   surface-finish texts, notes, table titles and cells - is built from the drawing vocabulary
   (feature 010's, extended with drawing words), or is a number or an id;
3. **the owner's denylist**, through the same reader feature 010 uses, skipped naming the file
   where it is absent (every CI machine).
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import DrawingView, EvidencePackage
from tests.support.drawings import drawing_fictional_offences
from tests.support.fixture_denylist import (
    DENYLIST_PATH,
    PUBLISHED_HEAD_CODES,
    load_denylist,
    offending_tokens,
)
from tests.support.mechanical import FICTIONAL_ROOT

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "drawings"
NAMES = ("plate-drawing", "drawing-root", "assembly-drawings")


def package(name: str) -> EvidencePackage:
    return load_package(FIXTURES / name).package


def views(item: EvidencePackage) -> list[DrawingView]:
    return [
        view for record in item.drawing_records for sheet in record.sheets for view in sheet.views
    ]


def paths(item: EvidencePackage) -> list[str]:
    found = [document.path for document in item.documents]
    found += [entry.vault_path for entry in item.manifest.entries]
    found += [candidate.path for candidate in item.drawing_candidates]
    found += [view.referenced_model_path for view in views(item) if view.referenced_model_path]
    for record in item.drawing_records:
        for sheet in record.sheets:
            if sheet.sheet_format_path:
                found.append(sheet.sheet_format_path)
            for table in sheet.tables:
                found += [path for row in table.bom_rows for path in row.unresolved_paths]
    return found


def names(item: EvidencePackage) -> list[str]:
    """Every name-bearing string the drawing builders compose."""
    texts = [item.design.name]
    for document in item.documents:
        texts.append(document.file_name)
        texts.extend(document.custom_properties.values())
        texts.extend(document.configurations)
    texts.extend(component.name for component in item.components)
    texts.extend(component.referenced_configuration for component in item.components)
    for record in item.drawing_records:
        texts.extend(
            text for text in (record.active_sheet_name, record.drafting_standard_name) if text
        )
        for sheet in record.sheets:
            texts.append(sheet.name)
            texts.extend(text for text in (sheet.sheet_format_name,) if text)
            for table in sheet.tables:
                texts.extend(text for text in (table.title,) if text)
                texts.extend(cell for row in table.rows for cell in row.cells if cell)
            for revision in sheet.revision_tables:
                texts.extend(cell for row in revision.rows for cell in row.cells if cell)
    for view in views(item):
        texts.extend(
            text
            for text in (view.name, view.orientation_name, view.referenced_configuration)
            if text
        )
        for dimension in view.display_dimensions:
            texts.extend(
                text
                for text in (
                    dimension.name,
                    dimension.text_prefix,
                    dimension.text_suffix,
                    dimension.text_above,
                    dimension.text_below,
                    dimension.fit_hole_class,
                    dimension.fit_shaft_class,
                )
                if text
            )
            texts.extend(dimension.hole_callout_variables_raw)
        for annotation in view.annotations:
            texts.extend(
                text
                for text in (
                    annotation.name,
                    annotation.datum_label,
                    annotation.datum_identifier_raw,
                )
                if text
            )
            texts.extend(annotation.surface_finish_texts_raw)
            for frame in annotation.gtol_frames:
                texts.extend(value for value in (*frame.symbols_raw, *frame.values_raw) if value)
        texts.extend(note.text for note in view.notes if note.text)
    return texts


def carried_strings(item: EvidencePackage) -> list[str]:
    """`names` and `paths` plus every gap reason and every drawing persist ref decoded."""
    texts = names(item) + paths(item)
    texts.extend(gap.reason for gap in item.gaps)
    refs = [view.persist_ref for view in views(item) if view.persist_ref]
    refs += [
        face.persist_ref
        for view in views(item)
        for record in (*view.display_dimensions, *view.annotations)
        for face in record.attached_faces
    ]
    texts.extend(base64.b64decode(ref).decode("utf-8") for ref in refs)
    return texts


@pytest.mark.parametrize("name", NAMES)
def test_every_path_starts_with_the_fictional_root(name: str) -> None:
    found = paths(package(name))

    assert found
    assert [path for path in found if not path.startswith(FICTIONAL_ROOT)] == []


@pytest.mark.parametrize("name", NAMES)
def test_every_string_is_built_from_the_drawing_vocabulary(name: str) -> None:
    offenders = {
        text: drawing_fictional_offences(text)
        for text in names(package(name))
        if drawing_fictional_offences(text)
    }
    assert offenders == {}


def test_the_vocabulary_check_refuses_what_it_does_not_know() -> None:
    """The check itself, so a vocabulary that accepted everything would fail here."""
    assert drawing_fictional_offences("GENERAL TOLERANCE FICTIONAL") == []
    assert drawing_fictional_offences("<GTOL-POSI>") == []
    assert drawing_fictional_offences("UNLESS NOTED") == ["UNLESS", "NOTED"]


def test_no_token_of_the_owners_denylist_occurs_in_any_fixture_string() -> None:
    denylist = load_denylist()
    if denylist is None:
        pytest.skip(f"the owner's denylist is not on this machine ({DENYLIST_PATH})")
    # Feature 010's screw names carry a published head code, as its own scan allows.
    checked = denylist - PUBLISHED_HEAD_CODES

    offenders = sorted(
        name
        for name in NAMES
        if any(offending_tokens(text, checked) for text in carried_strings(package(name)))
    )
    # The tokens themselves are never printed: a failure message can reach a public log.
    assert offenders == [], "denylisted tokens occur in these fixtures"
