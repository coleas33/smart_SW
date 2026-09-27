"""`swreview profile upgrade`: a proposed version 4 profile, and nothing decided (feature 013 T015).

`specs/013-engineer-first-review/contracts/part-roles-profile.md` section 5 is normative. The
helper reads a version 3 profile, writes `--out` (never its input) as the input's text with
`version: 4` and a `part_roles` section in which every signal is unused, copies the library's
skip and sketch-exempt entries only as commented proposals, validates what it wrote, and prints
the path and its sha256 and nothing else - no profile value reaches the console.

Every input here is fictional profile A written back as the version it is tested at.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from swreview.checks.standards.profile import load_profile, propose_version_4
from tests.unit.test_cli import invoke

PROFILE_A = Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "profile-a.yaml"

ALL_SIGNALS_OFF: dict[str, Any] = {
    "bought_prefixes": [],
    "bought_folder_names": [],
    "switch": {"property": "", "bought_values": [], "custom_values": []},
    "vendor_properties": [],
    "distributor_block": {"properties": [], "min_valued": 0},
    "catalogue_numbers": {"shapes": [], "properties": []},
    "custom_prefixes": [],
    "bought_number_prefixes": [],
    "detail_properties": [],
}

SKIP_COMMENT = (
    "# Proposed from library.skip_prefixes, which means 'Standards skips this', not 'bought'. "
    "Uncomment what is bought."
)
SKETCH_COMMENT = (
    "# Proposed from library.sketch_exempt_prefixes, which means 'no sketch check here', not "
    "'bought'. Uncomment what is bought."
)


def raw_a() -> dict[str, Any]:
    data = yaml.safe_load(PROFILE_A.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def as_version(version: int) -> dict[str, Any]:
    """Profile A written back as the version 1, 2 or 3 profile it extends."""
    data = {key: value for key, value in raw_a().items() if key != "part_roles"}
    if version <= 2:
        data.pop("drawing")
    if version == 1:
        data.pop("general_tolerance")
        data.pop("hygiene")
    data["version"] = version
    return data


def write(path: Path, data: dict[str, Any], *, header: str = "") -> Path:
    path.write_text(header + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def version_3(tmp_path: Path) -> Path:
    return write(tmp_path / "standards.yaml", as_version(3), header="# the owner's profile\n")


def upgrade(source: Path, out: Path, *extra: str) -> Any:
    return invoke("profile", "upgrade", str(source), "--out", str(out), *extra)


def test_the_input_is_never_touched(tmp_path: Path) -> None:
    source = version_3(tmp_path)
    before = source.read_bytes()

    result = upgrade(source, tmp_path / "v4.yaml")

    assert result.exit_code == 0, result.output
    assert source.read_bytes() == before


def test_the_output_is_version_4_with_every_signal_unused(tmp_path: Path) -> None:
    out = tmp_path / "v4.yaml"

    assert upgrade(version_3(tmp_path), out).exit_code == 0

    profile = load_profile(out)
    assert profile.version == 4
    assert profile.part_roles is not None
    assert profile.part_roles.model_dump() == ALL_SIGNALS_OFF


def test_the_output_is_the_inputs_text_with_the_version_raised(tmp_path: Path) -> None:
    source = version_3(tmp_path)
    out = tmp_path / "v4.yaml"

    upgrade(source, out)

    text = source.read_text(encoding="utf-8")
    written = out.read_text(encoding="utf-8")
    kept, _, appended = written.partition("\npart_roles:\n")
    assert kept.rstrip("\n") == re.sub(r"(?m)^version: 3$", "version: 4", text).rstrip("\n")
    assert written.startswith("# the owner's profile\n"), "the owner's own comments are kept"
    assert appended, "the section is appended"


def test_the_library_entries_are_proposed_only_as_comments(tmp_path: Path) -> None:
    out = tmp_path / "v4.yaml"
    library = raw_a()["library"]

    upgrade(version_3(tmp_path), out)

    lines = out.read_text(encoding="utf-8").splitlines()
    stripped = [line.strip() for line in lines]
    skip_at, sketch_at = stripped.index(SKIP_COMMENT), stripped.index(SKETCH_COMMENT)
    assert skip_at < sketch_at
    proposed_skip = stripped[skip_at + 1 : sketch_at]
    proposed_sketch = [line for line in stripped[sketch_at + 1 :] if line.startswith("# - ")]
    assert proposed_skip == [f'# - "{entry}"' for entry in library["skip_prefixes"]]
    assert proposed_sketch[: len(library["sketch_exempt_prefixes"])] == [
        f'# - "{entry}"' for entry in library["sketch_exempt_prefixes"]
    ]
    assert load_profile(out).part_roles.bought_prefixes == []  # type: ignore[union-attr]


def test_uncommenting_a_proposal_as_the_comment_says_gives_a_valid_profile(
    tmp_path: Path,
) -> None:
    """The owner's edit: uncomment one entry and drop the empty list it replaces."""
    out = tmp_path / "v4.yaml"
    upgrade(version_3(tmp_path), out)
    entry = raw_a()["library"]["sketch_exempt_prefixes"][0]
    text = out.read_text(encoding="utf-8")

    edited = text.replace("  bought_prefixes: []\n", "  bought_prefixes:\n", 1).replace(
        f'    # - "{entry}"', f'    - "{entry}"', 1
    )
    out.write_text(edited, encoding="utf-8")

    assert load_profile(out).part_roles.bought_prefixes == [entry]  # type: ignore[union-attr]


def test_empty_library_lists_propose_nothing(tmp_path: Path) -> None:
    data = as_version(3)
    data["library"]["skip_prefixes"] = []
    data["library"]["sketch_exempt_prefixes"] = []
    out = tmp_path / "v4.yaml"

    assert upgrade(write(tmp_path / "standards.yaml", data), out).exit_code == 0

    text = out.read_text(encoding="utf-8")
    assert "Proposed from" not in text
    assert load_profile(out).part_roles.model_dump() == ALL_SIGNALS_OFF  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("version", "lacks"),
    [(1, "general_tolerance, hygiene and drawing"), (2, "drawing")],
)
def test_a_version_1_or_2_input_is_refused_naming_what_it_lacks(
    tmp_path: Path, version: int, lacks: str
) -> None:
    out = tmp_path / "v4.yaml"

    result = upgrade(write(tmp_path / "standards.yaml", as_version(version)), out)

    assert result.exit_code == 1
    assert lacks in result.output
    assert not out.exists()


def test_a_version_4_input_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "v4.yaml"

    result = upgrade(PROFILE_A, out)

    assert result.exit_code == 1
    assert "already version 4" in result.output
    assert not out.exists()


def test_a_refused_input_refuses_the_upgrade_with_the_loaders_reason(tmp_path: Path) -> None:
    data = as_version(3)
    del data["library"]
    out = tmp_path / "v4.yaml"

    result = upgrade(write(tmp_path / "standards.yaml", data), out)

    assert result.exit_code == 1
    assert "library" in result.output
    assert not out.exists()


def test_an_existing_out_is_refused_unless_forced(tmp_path: Path) -> None:
    source = version_3(tmp_path)
    out = tmp_path / "v4.yaml"
    out.write_text("kept\n", encoding="utf-8")

    refused = upgrade(source, out)

    assert refused.exit_code == 1
    assert "--force" in refused.output
    assert out.read_text(encoding="utf-8") == "kept\n"
    assert upgrade(source, out, "--force").exit_code == 0
    assert load_profile(out).version == 4


def test_the_input_itself_is_never_the_out(tmp_path: Path) -> None:
    source = version_3(tmp_path)
    before = source.read_bytes()

    result = upgrade(source, source, "--force")

    assert result.exit_code == 1
    assert "its input" in result.output
    assert source.read_bytes() == before


def test_stdout_carries_only_the_path_and_its_sha256(tmp_path: Path) -> None:
    out = tmp_path / "v4.yaml"

    result = upgrade(version_3(tmp_path), out)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    assert result.stdout.strip() == f"{out} sha256:{digest}"


def test_a_crlf_profile_keeps_its_line_endings(tmp_path: Path) -> None:
    source = version_3(tmp_path)
    source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    out = tmp_path / "v4.yaml"

    assert upgrade(source, out).exit_code == 0

    written = out.read_bytes()
    assert b"\r\n" in written and b"\n" not in written.replace(b"\r\n", b"")
    assert load_profile(out).version == 4


def test_a_version_line_with_a_comment_is_raised(tmp_path: Path) -> None:
    source = version_3(tmp_path)
    text = source.read_text(encoding="utf-8").replace("version: 3", "version: 3  # the owner's")
    source.write_text(text, encoding="utf-8")
    out = tmp_path / "v4.yaml"

    assert upgrade(source, out).exit_code == 0
    assert load_profile(out).version == 4


def test_propose_version_4_is_pure_text_in_text_out(tmp_path: Path) -> None:
    source = version_3(tmp_path)
    text = source.read_text(encoding="utf-8")

    proposed = propose_version_4(text, load_profile(source))

    assert proposed == propose_version_4(text, load_profile(source))
    assert "version: 4" in proposed and "version: 3" not in proposed


def test_the_unfilled_output_classifies_as_its_version_3_input(tmp_path: Path) -> None:
    """The review of 2026-09-27: pointed at the pane before the owner fills it, the helper's
    output decides exactly what its version 3 input decides (the convention-only state), rather
    than firing the zero-match guard with every signal off."""
    from swreview.checks.part_roles import classify_parts
    from swreview.checks.standards.profile import load_profile, propose_version_4
    from tests.support.sitting import sitting_package

    source = tmp_path / "v3.yaml"
    source.write_text(yaml.safe_dump(as_version(3), sort_keys=False), encoding="utf-8")
    version_3 = load_profile(source)
    proposed = tmp_path / "v4.yaml"
    text = propose_version_4(source.read_text(encoding="utf-8"), version_3)
    proposed.write_text(text, encoding="utf-8")
    version_4 = load_profile(proposed)
    subject = sitting_package()

    assert version_4.version == 4 and version_4.part_roles is not None
    assert version_4.part_roles.signals_unused
    assert classify_parts(subject, version_4) == classify_parts(subject, version_3)
    assert classify_parts(subject, version_4).state == "convention_only"
