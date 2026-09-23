"""No recorded string reaches the committed mechanical fixtures (feature 010 T004).

The repository is public, and the fixtures under `tests/fixtures/mechanical/` are shaped
like two recorded customer assemblies. They are built by code from fictional strings
(`tests/support/mechanical.py`), and this module is what proves it, three ways:

1. **paths**: every document `path` and manifest `vault_path` starts with the fictional
   root. `ComponentInstance.full_path` is not a file path - it is `IComponent2.Name2`, the
   instance path inside the assembly - so it is held to the stricter rule below instead:
   no drive, no backslash, vocabulary only;
2. **names**: every file name, description, component name, configuration, feature name
   and property value is built from the builders' vocabulary, or is a size, a number, an id
   or one of the two SOLIDWORKS library material names committed goldens already carry;
3. **the owner's denylist**: when `%LOCALAPPDATA%\\SwReview\\fixture-denylist.txt` exists -
   the tokens feature 008's scrambler replaced, kept outside the repository - no token of
   three or more characters from it occurs in any string the fixtures carry, in the JSON of
   any mesh, or in the fastener-name vector table once it exists. Where the file does not
   exist, which is every CI machine, that half is skipped naming the file.

**What the denylist scan reads, and why not every byte.** It reads string *values*: the
names above, every gap reason, group key, size and thread, and every persist ref decoded
back to the fictional id it encodes. It does not read JSON keys, schema enum values or
numbers, because those are the IR's own vocabulary and float digits - `counterbore`,
`reuse_key` and `-0.0011249...` are not recorded strings whatever tokens the denylist holds
- and a GLB's generator URL is `trimesh`'s. Nothing a fixture builder composes escapes it.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from swreview.ir.loader import load_package
from swreview.ir.models import EvidencePackage
from tests.support.fixture_denylist import (
    DENYLIST_PATH,
    glb_json,
    json_strings,
    load_denylist,
    offending_tokens,
)
from tests.support.mechanical import FICTIONAL_ROOT, fictional_offences

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mechanical"
VECTOR_TABLE = (
    REPO_ROOT / "specs" / "010-mechanical-checks" / "contracts" / "fastener-name-vectors.json"
)
PUBLISHED_HEAD_CODES: frozenset[str] = frozenset({"shc", "fht", "bht"})
"""Head codes `contracts/fasteners.md` prints as the vendor grammar the parser reads. A
denylist built from recorded names can hold one - the recorded screws were named with it -
but it names a screw style, it is already published in this repository's specs, and the
fixtures cannot exercise the parser without it."""


def packages() -> dict[str, EvidencePackage]:
    found = {
        path.parent.name: load_package(path.parent).package
        for path in sorted(FIXTURES.glob("*/package.json"))
    }
    assert set(found) >= {"big-assembly", "small-assembly"}, found
    return found


def names(package: EvidencePackage) -> list[str]:
    """Every name-bearing string a builder composed from the vocabulary."""
    texts = [package.design.name]
    for document in package.documents:
        texts.append(document.file_name)
        texts.extend(document.custom_properties.values())
        texts.extend(document.configurations)
        for properties in document.config_properties.values():
            texts.extend(properties.values())
        if document.material is not None:
            texts.append(document.material)
    texts.extend(component.name for component in package.components)
    texts.extend(component.full_path for component in package.components)
    texts.extend(component.referenced_configuration for component in package.components)
    texts.extend(hole.feature_name for hole in package.holes)
    return texts


def carried_strings(package: EvidencePackage) -> list[str]:
    """`names` plus every other free string the package carries, persist refs decoded."""
    texts = names(package)
    texts.extend(document.path for document in package.documents)
    texts.extend(entry.vault_path for entry in package.manifest.entries)
    texts.extend(gap.reason for gap in package.gaps)
    texts.extend(gap.error for gap in package.gaps if gap.error)
    texts.extend(item.group_key for item in package.interferences)
    texts.extend(hole.size or "" for hole in package.holes)
    texts.extend(hole.thread_designation or "" for hole in package.holes)
    refs = [
        item.persist_ref
        for item in (*package.components, *package.holes, *package.faces, *package.bodies)
    ]
    texts.extend(base64.b64decode(ref).decode("utf-8") for ref in refs)
    texts.extend(body.mesh_file for body in package.bodies)
    return texts


@pytest.mark.parametrize("name", ["big-assembly", "small-assembly"])
def test_every_file_path_starts_with_the_fictional_root(name: str) -> None:
    package = packages()[name]

    paths = [document.path for document in package.documents]
    paths += [entry.vault_path for entry in package.manifest.entries]
    assert paths
    assert [path for path in paths if not path.startswith(FICTIONAL_ROOT)] == []


@pytest.mark.parametrize("name", ["big-assembly", "small-assembly"])
def test_every_instance_path_is_a_fictional_name_and_no_file_path(name: str) -> None:
    package = packages()[name]

    offenders = [
        component.full_path
        for component in package.components
        if ":" in component.full_path or "\\" in component.full_path
    ]
    assert offenders == []


@pytest.mark.parametrize("name", ["big-assembly", "small-assembly"])
def test_every_name_and_property_value_is_built_from_the_vocabulary(name: str) -> None:
    package = packages()[name]

    offenders = {
        text: fictional_offences(text) for text in names(package) if fictional_offences(text)
    }
    assert offenders == {}


def test_the_vocabulary_check_refuses_a_word_it_does_not_know() -> None:
    """The check itself, so a vocabulary that silently accepted everything would fail here."""
    assert fictional_offences("FICT-KALOMIR-0001") == []
    assert fictional_offences("SHC_M4-0.7X12_FICT-0001.SLDPRT") == []
    assert fictional_offences("Alloy Steel") == []
    assert fictional_offences("FICT-HOUSING-0001") == ["HOUSING"]
    assert fictional_offences("Stainless Steel") == ["Stainless", "Steel"]


def test_the_denylist_reader_folds_case_and_drops_short_and_blank_lines(tmp_path: Path) -> None:
    listed = tmp_path / "fixture-denylist.txt"
    listed.write_text("Zorbex\n\n# a comment\nab\n  QUIMBY  \n", encoding="utf-8")

    denylist = load_denylist(listed)

    assert denylist == frozenset({"zorbex", "quimby"})
    assert offending_tokens("a ZORBEX-2 bracket", denylist) == {"zorbex"}
    assert offending_tokens("nothing here", denylist) == set()
    assert load_denylist(tmp_path / "absent.txt") is None


def test_a_glb_is_read_by_its_json_chunk() -> None:
    mesh = next(FIXTURES.glob("big-assembly/meshes/*.glb"))

    document = glb_json(mesh)

    assert document["asset"]["version"] == "2.0"
    assert "accessors" in document


def mesh_strings() -> list[str]:
    texts: list[str] = []
    for path in sorted(FIXTURES.glob("*/meshes/*.glb")):
        document = glb_json(path)
        document.get("asset", {}).pop("generator", None)
        texts.extend(json_strings(document))
    return texts


def test_no_token_of_the_owners_denylist_occurs_in_any_fixture_string() -> None:
    denylist = load_denylist()
    if denylist is None:
        pytest.skip(f"the owner's denylist is not on this machine ({DENYLIST_PATH})")
    checked = denylist - PUBLISHED_HEAD_CODES

    sources = {name: carried_strings(package) for name, package in packages().items()}
    sources["meshes"] = mesh_strings()
    if VECTOR_TABLE.exists():
        sources["fastener-name-vectors.json"] = list(
            json_strings(json.loads(VECTOR_TABLE.read_text(encoding="utf-8")))
        )

    offenders = sorted(
        source
        for source, texts in sources.items()
        if any(offending_tokens(text, checked) for text in texts)
    )
    # The tokens themselves are never printed: naming the source is enough to act on, and a
    # failure message is output that could end up in a public log.
    assert offenders == [], "denylisted tokens occur in these fixtures"
