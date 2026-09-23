"""Read and write evidence packages on disk.

Every path is resolved before use so a symlink or junction cannot smuggle the reviewer
into `benchmarks/answer_keys/`: answer keys are withheld from the reviewer by
construction, not by convention (benchmarks/README.md, FR of US6).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from swreview.ir.models import EvidencePackage, Gap, Interference

PACKAGE_FILE_NAME = "package.json"
ANSWER_KEY_SEGMENTS = ("benchmarks", "answer_keys")


class AnswerKeyAccessError(RuntimeError):
    """The reviewer tried to read or write inside `benchmarks/answer_keys/`."""


class PackageAppendError(ValueError):
    """A live interference run could not be merged into `package.json`; nothing was written."""


@dataclass(frozen=True)
class LoadedPackage:
    """A package with the directory its relative paths (meshes, captures) point into."""

    package: EvidencePackage
    base_dir: Path

    def resolve(self, relative_path: str) -> Path:
        """Return the absolute path of a package-relative file such as `mesh_file`."""
        return self.base_dir / Path(relative_path)


def reject_answer_key_path(path: Path | str, reason: str) -> Path:
    """`path` resolved, unless it lies under `benchmarks/answer_keys/`.

    The one place the answer-key rule is expressed. Every layer that handles a path on
    the reviewer's behalf - the package loader here, `swreview.benchmark.sets` and
    `swreview.benchmark.runner` - calls this with the `reason` its own caller needs to
    read, so the three layers cannot drift apart on what counts as an answer key.
    Resolution happens first, so a symlink or junction is caught too.
    """
    resolved = Path(path).resolve()
    parts = resolved.parts
    for index in range(len(parts) - 1):
        if (parts[index].lower(), parts[index + 1].lower()) == ANSWER_KEY_SEGMENTS:
            raise AnswerKeyAccessError(
                f"{resolved} is inside benchmarks/answer_keys; {reason}"
            )
    return resolved


def _checked_dir(directory: Path | str) -> Path:
    return reject_answer_key_path(
        directory, "answer keys are withheld from the reviewer"
    )


def load_package(directory: Path | str) -> LoadedPackage:
    """Load `package.json` from `directory`.

    Raises `AnswerKeyAccessError` for an answer-key path,
    `swreview.ir.models.UnsupportedSchemaVersionError` for a schema major this build
    cannot read, and `pydantic.ValidationError` for malformed or incomplete content.
    """
    base_dir = _checked_dir(directory)
    package_file = base_dir / PACKAGE_FILE_NAME
    if not package_file.is_file():
        raise FileNotFoundError(f"no {PACKAGE_FILE_NAME} in {base_dir}")
    package = EvidencePackage.model_validate_json(package_file.read_bytes())
    return LoadedPackage(package=package, base_dir=base_dir)


def save_package(package: EvidencePackage, directory: Path | str) -> Path:
    """Write `package.json` into `directory`, creating it when needed."""
    base_dir = _checked_dir(directory)
    base_dir.mkdir(parents=True, exist_ok=True)
    package_file = base_dir / PACKAGE_FILE_NAME
    package_file.write_text(package.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return package_file


def append_interference_run(
    source_dir: Path | str,
    target_dir: Path | str,
    configuration: str,
    rows: Sequence[Interference],
    gaps: Sequence[Gap],
) -> Path:
    """Merge one live interference run into `target_dir/package.json` (feature 008, FR-009).

    The rule the C# console's `PackageAppender.Merge` applies: the rows of `configuration`
    are replaced by `rows`, every other configuration's rows are kept, and each of `gaps`
    not already in the package is appended once. Done on the raw JSON of
    `source_dir/package.json` rather than through `save_package`, because a pydantic round
    trip changes a value - a .NET seven-digit `created_at` fraction is truncated - while a
    raw round trip keeps every value and the key order, so `reuse_key` stays in the first
    8 KiB `benchmark/package_index.py` reads (research R2.18). The bytes still change
    (line endings, float spelling); nothing in the product hashes them.

    Re-validated before anything is written: the merged text must load as an
    `EvidencePackage` equal to the same merge done on the models. It is then written to a
    temporary file in `target_dir` and `os.replace`d onto `package.json`, so a reader - the
    add-in, a pane Retry - sees the old file or the new one, never half of one.

    In the pane `source_dir == target_dir` and the run folder's package is updated in
    place; on the command line they differ, and the input folder is never written.

    Raises:
        FileNotFoundError: `source_dir` holds no `package.json`.
        PackageAppendError: a new row's id is already held by a kept row, or the merged
            package does not validate or does not equal the model merge.
        OSError: the temporary file or the replace failed.
        In every case no file is changed and no temporary file is left behind.
    """
    source_file = _checked_dir(source_dir) / PACKAGE_FILE_NAME
    target = _checked_dir(target_dir)
    if not source_file.is_file():
        raise FileNotFoundError(f"no {PACKAGE_FILE_NAME} in {source_file.parent}")
    text = source_file.read_text(encoding="utf-8")
    data = json.loads(text)
    before = EvidencePackage.model_validate_json(text)

    kept = [
        row for row in data.get("interferences", []) if row.get("configuration") != configuration
    ]
    kept_ids = {row.get("id") for row in kept}
    colliding = sorted(row.id for row in rows if row.id in kept_ids)
    if colliding:
        raise PackageAppendError(
            f"interference rows {colliding} collide with the ids of rows the package keeps "
            f"for another configuration than {configuration!r}; nothing was written"
        )
    new_gaps: list[Gap] = []
    for gap in gaps:
        if gap not in before.gaps and gap not in new_gaps:
            new_gaps.append(gap)
    data["interferences"] = [*kept, *(row.model_dump(mode="json") for row in rows)]
    data["gaps"] = [*data.get("gaps", []), *(gap.model_dump(mode="json") for gap in new_gaps)]
    merged_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    expected = before.model_copy(
        update={
            "interferences": [
                row for row in before.interferences if row.configuration != configuration
            ]
            + list(rows),
            "gaps": [*before.gaps, *new_gaps],
        }
    )
    try:
        merged = EvidencePackage.model_validate_json(merged_text)
    except ValidationError as exc:
        raise PackageAppendError(
            f"the merged package does not validate, so nothing was written: "
            f"{exc.errors(include_url=False)}"
        ) from exc
    if merged != expected:
        raise PackageAppendError(
            "the merged package does not equal the same merge done on the models, so "
            "nothing was written"
        )

    target.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target,
            prefix=f".{PACKAGE_FILE_NAME}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(merged_text)
        os.replace(temporary, target / PACKAGE_FILE_NAME)
        temporary = None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
    return target / PACKAGE_FILE_NAME
