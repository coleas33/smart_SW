"""Unit tests for the IR 1.3.0 additions: the file stat and the reuse key (T089).

Lever 9 reuses a previous run's `package.json` instead of dumping again, and the only
thing that can say "this is the same design, dumped the same way" is the key over the
manifest. VERIFIED that the 1.2.0 manifest holds no modification time, no file size and
no content hash (`ir/models.py:187-194`, `Dump/ManifestBuilder.cs:28-65`): `document_id`
is a SHA-1 of the lowercased normalized **path**, `vault_version` and `revision` are null
unless a vault writes them, and `local_modified` is hardcoded null with an `unsupported`
gap on every document of every dump. So a key without `file_modified_utc` and
`file_size_bytes` reduces to path and configuration, which says nothing about whether
anything changed (data-model.md 9.1, OQ-6).

Three members arrive here, all optional with a `None` default:

- `ManifestEntry.file_modified_utc` and `ManifestEntry.file_size_bytes`, written from
  `FileInfo.LastWriteTimeUtc` and `FileInfo.Length`, `None` **plus a gap** when the path
  cannot be stat'ed. Never `0` and never "now" (constitution Principle I);
- `EvidencePackage.reuse_key`, the SHA-256 of `benchmark/reuse.py`'s canonical form,
  written near the top of the file so a bounded head read can find it without parsing
  tens of megabytes (the `RunFolders.ProfileOf` technique, VERIFIED).

1.3.0 is a **minor** bump: every 1.0.0, 1.1.0 and 1.2.0 package predates these members and
must still load unchanged, and feature 001's schema-major gate is untouched, so 2.0.0
still raises. The key's own invalidation table is `test_reuse_key.py`; this file is about
the shape of the package that carries it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from swreview.ir.models import (
    SCHEMA_VERSION,
    EvidencePackage,
    ManifestEntry,
    UnsupportedSchemaVersionError,
)
from swreview.ir.schema import export_schema
from tests.golden.test_golden import case_dirs
from tests.support.contracts import load_contract
from tests.support.packages import build_package

GOLDEN_FIXTURES = Path(__file__).resolve().parents[1] / "golden" / "fixtures"
GOLDEN_FIXTURE_DIRS = case_dirs(GOLDEN_FIXTURES)

MODIFIED = datetime(2026, 9, 10, 8, 30, 0, tzinfo=UTC)
REUSE_KEY = "a" * 64


def build_entry(**overrides: object) -> ManifestEntry:
    fields: dict[str, object] = {
        "document_id": "doc:1",
        "vault_path": "/Designs/cover-assy.SLDASM",
        "vault_version": None,
        "revision": None,
        "configuration": "Default",
        "local_modified": None,
        "export_method": "native",
    }
    fields.update(overrides)
    return ManifestEntry(**fields)  # type: ignore[arg-type]


def contract_validator() -> Draft202012Validator:
    return Draft202012Validator(
        load_contract("ir.schema.json"),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


# --- the version bump -------------------------------------------------------------


def test_schema_version_is_one_four_zero() -> None:
    """1.3.0 is where these members arrived; 006 T013 bumped the minor again beside them
    and left them exactly as they were."""
    assert SCHEMA_VERSION == "1.4.0"
    assert build_package().schema_version == "1.4.0"


def test_the_schema_major_gate_is_unchanged() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "2.0.0"

    with pytest.raises(UnsupportedSchemaVersionError):
        EvidencePackage.model_validate_json(json.dumps(payload))


# --- the two manifest fields --------------------------------------------------------


def test_the_file_stat_defaults_to_unknown() -> None:
    """A path that could not be stat'ed is `None` and a gap says so; it is never `0`."""
    entry = build_entry()

    assert entry.file_modified_utc is None
    assert entry.file_size_bytes is None


def test_an_entry_that_knows_neither_stat_serializes_without_them() -> None:
    """The 1.3.0 additions are optional, so an unknown one is left out rather than written
    as a null: a 1.2.0 entry round-trips to the bytes a 1.2.0 build wrote, which is what
    keeps the feature 001/002/003 tool-payload goldens unchanged (SC-007,
    `ir.models.omit_when_null`). A known stat is written, nulls are what is dropped.
    """
    unknown = json.loads(build_entry().model_dump_json())
    known = json.loads(
        build_entry(file_modified_utc=MODIFIED, file_size_bytes=0).model_dump_json()
    )

    assert "file_modified_utc" not in unknown
    assert "file_size_bytes" not in unknown
    assert known["file_size_bytes"] == 0
    assert known["file_modified_utc"] is not None


def test_a_stat_round_trips_through_json() -> None:
    package = build_package(
        manifest=build_package().manifest.model_copy(
            update={"entries": [build_entry(file_modified_utc=MODIFIED, file_size_bytes=262_144)]}
        )
    )

    restored = EvidencePackage.model_validate_json(package.model_dump_json())

    assert restored.manifest.entries[0].file_modified_utc == MODIFIED
    assert restored.manifest.entries[0].file_size_bytes == 262_144
    assert restored == package


def test_the_modification_time_keeps_the_instant_it_was_given() -> None:
    """`FileInfo.LastWriteTimeUtc` is an instant. A naive value would be a local time
    pretending to be UTC, so the offset survives the round trip rather than being dropped."""
    dumped = json.loads(
        build_entry(file_modified_utc=MODIFIED, file_size_bytes=1).model_dump_json()
    )

    assert dumped["file_modified_utc"] == "2026-09-10T08:30:00Z"


def test_a_negative_file_size_is_rejected() -> None:
    """A size is a count of bytes; a negative one is a bug upstream, not an unknown."""
    with pytest.raises(ValidationError):
        build_entry(file_size_bytes=-1)


def test_an_empty_file_is_a_size_and_not_an_unknown() -> None:
    assert build_entry(file_size_bytes=0).file_size_bytes == 0


# --- the reuse key ------------------------------------------------------------------


def test_the_reuse_key_defaults_to_none() -> None:
    """A package written by a build that does not compute one says so, rather than
    carrying a key nothing can be checked against."""
    assert build_package().reuse_key is None


def test_the_reuse_key_round_trips_through_json() -> None:
    package = build_package(reuse_key=REUSE_KEY)

    restored = EvidencePackage.model_validate_json(package.model_dump_json())

    assert restored.reuse_key == REUSE_KEY
    assert restored == package


def test_the_reuse_key_is_written_before_the_bulk_of_the_package() -> None:
    """`RunFolders.ProfileOf` reads only the first 8 KiB of a package because a full one is
    tens of megabytes and the read happens on the SOLIDWORKS application thread (VERIFIED,
    `Review/RunFolders.cs:52,125-186`). The fallback head scan finds `reuse_key` the same
    way, which only works while it is written near the top."""
    keys = list(json.loads(build_package(reuse_key=REUSE_KEY).model_dump_json()))

    assert keys.index("reuse_key") < keys.index("extractor")


# --- what still loads ----------------------------------------------------------------


def test_a_one_two_zero_package_without_the_new_members_loads() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["schema_version"] = "1.2.0"
    payload.pop("reuse_key")
    for entry in payload["manifest"]["entries"]:
        # Already absent: an entry that knows neither stat serializes without them
        # (`ir.models.omit_when_null`, feature 005 SC-007), which is exactly the shape a
        # 1.2.0 writer produced. Popped defensively so this test says what it is about -
        # a payload with no such members loads - and not how they came to be missing.
        entry.pop("file_modified_utc", None)
        entry.pop("file_size_bytes", None)

    package = EvidencePackage.model_validate_json(json.dumps(payload))

    assert package.schema_version == "1.2.0"
    assert package.reuse_key is None
    assert [entry.file_modified_utc for entry in package.manifest.entries] == [None, None]


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURE_DIRS, ids=lambda path: path.name)
def test_every_shipped_golden_fixture_still_loads(fixture: Path) -> None:
    """Every fixture in the tree was written at 1.2.0 or earlier. A minor bump that made
    one of them unreadable would be a major bump wearing a minor's number."""
    text = (fixture / "package.json").read_text(encoding="utf-8")

    package = EvidencePackage.model_validate_json(text)

    assert package.reuse_key is None


def test_an_unknown_member_is_still_forbidden() -> None:
    payload = json.loads(build_package().model_dump_json())
    payload["reuse_digest"] = REUSE_KEY

    with pytest.raises(ValidationError):
        EvidencePackage.model_validate_json(json.dumps(payload))


# --- the generated contract ----------------------------------------------------------


def test_the_generated_schema_makes_all_three_members_optional() -> None:
    schema = export_schema()
    entry = schema["$defs"]["ManifestEntry"]

    assert "file_modified_utc" not in entry["required"]
    assert "file_size_bytes" not in entry["required"]
    assert "reuse_key" not in schema["required"]


def test_the_generated_schema_keeps_a_file_size_at_or_above_zero() -> None:
    entry = export_schema()["$defs"]["ManifestEntry"]["properties"]["file_size_bytes"]

    assert any(option.get("minimum") == 0 for option in entry["anyOf"])


def test_a_package_carrying_the_new_members_validates_against_the_contract() -> None:
    package = build_package(reuse_key=REUSE_KEY)
    package.manifest.entries[0].file_modified_utc = MODIFIED
    package.manifest.entries[0].file_size_bytes = 262_144
    sample = package.model_dump(mode="json")

    errors = sorted(
        contract_validator().iter_errors(sample), key=lambda error: list(error.absolute_path)
    )

    assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]


def test_the_committed_contract_rejects_a_negative_file_size() -> None:
    sample = build_package().model_dump(mode="json")
    sample["manifest"]["entries"][0]["file_size_bytes"] = -1

    assert list(contract_validator().iter_errors(sample)) != []
