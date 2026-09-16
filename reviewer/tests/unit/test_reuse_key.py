"""The package-reuse key, one test per row of the invalidation table (T087, for T089).

Lever 9 reuses a previous run's `package.json` instead of dumping again. The whole lever
rests on one question - *is this the same design, dumped the same way?* - and the key is
the only thing that answers it, so every row of the invalidation table
(data-model.md 9.3) gets its own test here.

**Half the baseline's premise is false today** (all VERIFIED, `ir/models.py:187-194`,
`Dump/ManifestBuilder.cs:28-65`): the manifest has seven fields, `document_id` is a SHA-1
of the lowercased normalized **path** and not of content, `vault_version` is null unless
a vault writes that property back, `revision` is null unless set, and `local_modified` is
**hardcoded null** with an `unsupported` gap on every document of every dump
(`ManifestBuilder.cs:57,92-98`). There is no modification time, no file size and no
content hash anywhere in the manifest, in `Document` or in `EvidencePackage`, so a key
built from "path, version and modification time" reduces today to **path and
configuration** - "the same files, in the same configurations", which says nothing about
whether they changed. `file_modified_utc` and `file_size_bytes` (schema 1.3.0, T089) are
what make the key an answer rather than a hope; until the C# writes them, an entry
reports **unknown**, and unknown refuses reuse (`test_reuse_refusals.py`).

Three assertions here are not about a single field and earn their own tests:

- **Every** manifest entry is in the key, not just the root, because
  `PackageWriter.DocumentPaths` (`:381-401`) collects every document the traversal
  referenced. That closes the named risk of a referenced part edited outside the assembly.
- The **profile** is in the key, because a `model_check` package has empty `holes[]`,
  `fasteners[]`, `faces[]` and `bodies[]` **by design** (`Dump/PackageWriter.cs:200-235`),
  so handing one to a Review that asked for `full` silently narrows the review.
- `package_id` and `created_at` are **not** in the key. `PackageWriter` assigns
  `Guid.NewGuid()` per dump (VERIFIED, `:136`), so a key that included either would never
  match anything and the lever could not work at all.

The key is a SHA-256 over the data-model.md 9.2 tuple, in that order, stored as a
top-level `reuse_key` on `EvidencePackage` so a reader can see what a package claims to
be. It decides **matching**; it never decides **safety** - what the key cannot catch is
refused explicitly, one refusal per hole, in `test_reuse_refusals.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from swreview.benchmark.reuse import (
    EQUATION_SCOPES,
    FACE_SCOPES,
    FEATURE_SCOPES,
    MESH_FORMATS,
    DumpOptions,
    canonical_form,
    key_parts,
    package_reuse_key,
)
from swreview.ir.models import EvidencePackage, ExtractorInfo, Manifest
from tests.support.packages import build_package
from tests.support.reuse import (
    MODIFIED,
    MODIFIED_PART,
    SIZE,
    SIZE_PART,
    reuse_entry,
    reuse_manifest,
    reuse_package,
)

OPTIONS = DumpOptions()
"""The shipped `dump` defaults: `--meshes glb --faces needed --features tree --equations on`
(VERIFIED, `SwReview.Extractor.Console/CommandLine.cs:151-210`)."""


def key(package: EvidencePackage, options: DumpOptions = OPTIONS) -> str:
    return package_reuse_key(package, options)


BASELINE = key(reuse_package())


def package_with_entry(existing_id: str, **changes: Any) -> EvidencePackage:
    """The baseline package with one manifest entry's fields replaced."""
    entries = [
        entry.model_copy(update=changes) if entry.document_id == existing_id else entry
        for entry in reuse_manifest().entries
    ]
    return reuse_package(manifest=reuse_manifest(entries))


def package_with_component(component_id: str, **changes: Any) -> EvidencePackage:
    """The baseline package with one component instance's fields replaced."""
    components = [
        component.model_copy(update=changes) if component.id == component_id else component
        for component in reuse_package().components
    ]
    return reuse_package(components=components)


def extractor(**changes: Any) -> ExtractorInfo:
    return reuse_package().extractor.model_copy(update=changes)


# --- The key itself --------------------------------------------------------------


def test_the_key_is_a_sha256_hex_digest() -> None:
    assert len(BASELINE) == 64
    assert set(BASELINE) <= set("0123456789abcdef")


def test_the_same_design_dumped_twice_gives_the_same_key() -> None:
    """The lever's precondition: two independent builds of one design agree."""
    assert key(reuse_package()) == key(reuse_package()) == BASELINE


# --- The cross-language pin -----------------------------------------------------------
#
# The other half is `extractor/SwReview.Extractor.Tests/ReuseKeyTests.cs`, which asserts
# these same two strings against `ReuseKey.CanonicalForm` and `ReuseKey.Of` over the same
# fixture. **The production key is computed in C# and the invalidation table above is
# tested in Python**, so nothing else makes the two ends agree: with the pin only on the
# C# side, every test here would stay green through a change to member order, to
# `_instant`'s rendering or to the JSON separators, and the two languages would quietly
# hash one package to two digests. Both sides pin, so either edit fails a gate.
#
# If these two change together on purpose, change them in both files in one commit.

CROSS_LANGUAGE_CANONICAL_FORM = (
    '{"extractor_name":"SwReview.Extractor","extractor_version":"0.1.0",'
    '"schema_version":"1.3.0","profile":"full","meshes":"glb","faces":"needed",'
    '"features":"tree","equations":"on","root_assembly_document_id":"doc:1",'
    '"active_configuration":"Default","documents":[{"document_id":"doc:1",'
    '"configuration":"Default","referenced_configurations":[],'
    '"file_modified_utc":"2026-09-10T08:30:00+00:00","file_size_bytes":262144},'
    '{"document_id":"doc:2","configuration":"Default",'
    '"referenced_configurations":["Default"],'
    '"file_modified_utc":"2026-09-09T17:05:00+00:00","file_size_bytes":98304}],'
    '"components":[{"component_id":"cmp:0001","suppression":"resolved"},'
    '{"component_id":"cmp:0002","suppression":"resolved"}]}'
)
"""`canonical_form(key_parts(reuse_package(), OPTIONS))`, character for character."""

CROSS_LANGUAGE_DIGEST = "35753b68428470782750128ffbfa09db185497d00cc320ddb297752b18d2a845"
"""`package_reuse_key(reuse_package(), OPTIONS)`, the SHA-256 of the text above."""


def test_the_canonical_form_is_the_text_both_languages_hash() -> None:
    assert canonical_form(key_parts(reuse_package(), OPTIONS)) == CROSS_LANGUAGE_CANONICAL_FORM


def test_the_digest_is_the_one_both_languages_compute() -> None:
    assert BASELINE == CROSS_LANGUAGE_DIGEST


def test_package_id_and_created_at_are_not_in_the_key() -> None:
    """`PackageWriter` assigns a fresh `Guid` and timestamp per dump (VERIFIED, `:136`)."""
    other = reuse_package(
        package_id="99999999-8888-4777-8666-555555555555",
        created_at=datetime(2027, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    assert key(other) == BASELINE


# --- Rows: the extractor and the schema ------------------------------------------


def test_the_extractor_name_changes_the_key() -> None:
    assert key(reuse_package(extractor=extractor(name="SwReview.Extractor.Fork"))) != BASELINE


def test_the_extractor_version_changes_the_key() -> None:
    """A package written by an older build may be missing a phase a newer reviewer wants."""
    assert key(reuse_package(extractor=extractor(version="0.2.0"))) != BASELINE


def test_the_schema_version_changes_the_key() -> None:
    assert key(reuse_package(schema_version="1.2.0")) != BASELINE


def test_the_profile_changes_the_key() -> None:
    """A `model_check` package must never match a Review that asked for `full`."""
    assert key(reuse_package(extractor=extractor(profile="model_check"))) != BASELINE


# --- Rows: the four dump options that change content ------------------------------


@pytest.mark.parametrize("meshes", [value for value in MESH_FORMATS if value != OPTIONS.meshes])
def test_the_mesh_format_changes_the_key(meshes: str) -> None:
    assert key(reuse_package(), DumpOptions(meshes=meshes)) != BASELINE


@pytest.mark.parametrize("faces", [value for value in FACE_SCOPES if value != OPTIONS.faces])
def test_the_face_scope_changes_the_key(faces: str) -> None:
    assert key(reuse_package(), DumpOptions(faces=faces)) != BASELINE


@pytest.mark.parametrize(
    "features", [value for value in FEATURE_SCOPES if value != OPTIONS.features]
)
def test_the_feature_scope_changes_the_key(features: str) -> None:
    """`--features none` writes an empty `features[]`; the RMS rules then read nothing."""
    assert key(reuse_package(), DumpOptions(features=features)) != BASELINE


@pytest.mark.parametrize(
    "equations", [value for value in EQUATION_SCOPES if value != OPTIONS.equations]
)
def test_the_equation_scope_changes_the_key(equations: str) -> None:
    assert key(reuse_package(), DumpOptions(equations=equations)) != BASELINE


def test_every_dump_option_is_in_the_key_exactly_once() -> None:
    """All four at once differ from each one alone: no option is silently dropped."""
    everything = DumpOptions(meshes="none", faces="all", features="none", equations="off")
    keys = {
        BASELINE,
        key(reuse_package(), DumpOptions(meshes="none")),
        key(reuse_package(), DumpOptions(faces="all")),
        key(reuse_package(), DumpOptions(features="none")),
        key(reuse_package(), DumpOptions(equations="off")),
        key(reuse_package(), everything),
    }
    assert len(keys) == 6


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meshes", "GLB"),
        ("faces", "some"),
        ("features", "trees"),
        ("equations", "true"),
    ],
)
def test_an_unknown_dump_option_is_refused(field: str, value: str) -> None:
    """A typo must not hash into a key nobody will ever match again."""
    with pytest.raises(ValueError, match=field):
        DumpOptions(**{field: value})


# --- Rows: the design --------------------------------------------------------------


def test_the_root_assembly_document_id_changes_the_key() -> None:
    design = reuse_package().design.model_copy(update={"root_assembly_document_id": "doc:9"})
    assert key(reuse_package(design=design)) != BASELINE


def test_the_active_configuration_changes_the_key() -> None:
    """A configuration switch changes geometry without touching a file."""
    design = reuse_package().design.model_copy(update={"active_configuration": "Machined"})
    assert key(reuse_package(design=design)) != BASELINE


# --- Rows: the manifest entries -----------------------------------------------------


def test_a_manifest_entry_document_id_changes_the_key() -> None:
    assert key(package_with_entry("doc:2", document_id="doc:3")) != BASELINE


def test_a_manifest_entry_configuration_changes_the_key() -> None:
    assert key(package_with_entry("doc:2", configuration="Machined")) != BASELINE


def test_a_saved_file_changes_the_key() -> None:
    """The ordinary case: the root assembly is saved, so mtime and size both move."""
    saved = package_with_entry(
        "doc:1",
        file_modified_utc=MODIFIED + timedelta(minutes=3),
        file_size_bytes=SIZE + 512,
    )
    assert key(saved) != BASELINE


def test_file_modified_utc_alone_changes_the_key() -> None:
    """A save that happens to land on the same byte count is still a change."""
    touched = package_with_entry("doc:1", file_modified_utc=MODIFIED + timedelta(seconds=1))
    assert key(touched) != BASELINE


def test_file_size_bytes_alone_changes_the_key() -> None:
    """And a change the clock missed is still a change."""
    resized = package_with_entry("doc:1", file_size_bytes=SIZE + 1)
    assert key(resized) != BASELINE


def test_a_referenced_part_edited_outside_the_assembly_changes_the_key() -> None:
    """**Every** entry is in the key, not just the root: the input document's named risk.

    `PackageWriter.DocumentPaths` (`:381-401`) collects every document the traversal
    reached, so the part edited in its own window has a manifest entry of its own.
    """
    edited = package_with_entry(
        "doc:2",
        file_modified_utc=MODIFIED_PART + timedelta(hours=2),
        file_size_bytes=SIZE_PART + 4096,
    )
    assert key(edited) != BASELINE


def test_a_virtual_component_changes_the_key_through_its_parent() -> None:
    """A virtual component has no file: its bytes live in the parent, so the parent moves."""
    parent_saved = package_with_entry(
        "doc:1",
        file_modified_utc=MODIFIED + timedelta(minutes=1),
        file_size_bytes=SIZE + 8192,
    )
    assert key(parent_saved) != BASELINE


def test_a_toolbox_part_regenerated_in_place_changes_the_key() -> None:
    """Caught if and only if its own file mtime moved - which is why the part's entry is in."""
    regenerated = package_with_entry("doc:2", file_modified_utc=MODIFIED_PART + timedelta(days=1))
    assert key(regenerated) != BASELINE


def test_an_added_manifest_entry_changes_the_key() -> None:
    added = reuse_manifest(
        [*reuse_manifest().entries, reuse_entry("doc:3", "/Designs/cover.SLDPRT")]
    )
    assert key(reuse_package(manifest=added)) != BASELINE


def test_a_removed_manifest_entry_changes_the_key() -> None:
    fewer = reuse_manifest(reuse_manifest().entries[:1])
    assert key(reuse_package(manifest=fewer)) != BASELINE


def test_the_manifest_entry_order_does_not_change_the_key() -> None:
    """Entries are sorted by `document_id`: the dump's traversal order is not a change."""
    reversed_entries = reuse_manifest(list(reversed(reuse_manifest().entries)))
    assert key(reuse_package(manifest=reversed_entries)) == BASELINE


# --- Rows: the components ------------------------------------------------------------


def test_a_referenced_configuration_switch_changes_the_key() -> None:
    """`ManifestEntry.configuration` is the *document's* active configuration, while
    `ComponentInstance.referenced_configuration` is per instance (VERIFIED,
    `ir/models.py:245`), so a per-instance switch is invisible without the per-document
    sorted set. What that set still cannot see is asserted in `test_reuse_refusals.py`.
    """
    switched = package_with_component("cmp:0001", referenced_configuration="Machined")
    assert key(switched) != BASELINE


@pytest.mark.parametrize("suppression", ["suppressed", "lightweight", "unloaded"])
def test_a_component_resolved_state_changes_the_key(suppression: str) -> None:
    """`MeshExporter` skips non-resolved components with a gap (`Dump/MeshExporter.cs:57-69`),
    so resolving one changes what a review can see with **no file change**."""
    assert key(package_with_component("cmp:0002", suppression=suppression)) != BASELINE


def test_the_component_order_does_not_change_the_key() -> None:
    """Components are sorted by id for the same reason entries are."""
    components = list(reversed(reuse_package().components))
    assert key(reuse_package(components=components)) == BASELINE


def test_a_removed_component_changes_the_key() -> None:
    assert key(reuse_package(components=reuse_package().components[:1])) != BASELINE


# --- What the key deliberately ignores -------------------------------------------------


def test_the_same_instant_in_another_timezone_does_not_change_the_key() -> None:
    """`file_modified_utc` is an instant, not a rendering: `+00:00` and `-05:00` of the
    same moment are the same file, and a false miss here costs a whole dump."""
    elsewhere = package_with_entry(
        "doc:1", file_modified_utc=MODIFIED.astimezone(timezone(timedelta(hours=-5)))
    )
    assert key(elsewhere) == BASELINE


def test_a_gap_does_not_change_the_key() -> None:
    """Gaps are evidence about the dump, not about the design; the aborted-dump case is a
    refusal (`test_reuse_refusals.py`), not a key part."""
    assert key(reuse_package(gaps=[])) == BASELINE


# --- The 1.2.0 packages that exist today ------------------------------------------------


def test_a_pre_1_3_0_entry_reports_an_unknown_file_stat() -> None:
    """Until T089 writes the two fields, every entry is unknown - and unknown refuses
    reuse (`test_reuse_refusals.py`). The key still computes, so a 1.2.0 package can be
    read and reported on; it is the refusal that stops it being trusted."""
    parts = key_parts(build_package(), OPTIONS)
    assert [(part.file_modified_utc, part.file_size_bytes) for part in parts.documents] == [
        (None, None),
        (None, None),
    ]
    assert len(package_reuse_key(build_package(), OPTIONS)) == 64


def test_an_unknown_stat_is_not_the_same_key_as_a_known_one() -> None:
    """Unknown is a value in the key, never a wildcard that matches everything."""
    unknown = Manifest(
        entries=[
            reuse_entry("doc:1", "/Designs/cover-assy.SLDASM", file_modified_utc=None),
            reuse_entry(
                "doc:2", "/Designs/housing.SLDPRT", file_modified_utc=None, file_size_bytes=None
            ),
        ],
        discrepancies=[],
    )
    assert key(reuse_package(manifest=unknown)) != BASELINE
