"""Read and write evidence packages on disk.

Every path is resolved before use so a symlink or junction cannot smuggle the reviewer
into `benchmarks/answer_keys/`: answer keys are withheld from the reviewer by
construction, not by convention (benchmarks/README.md, FR of US6).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from swreview.ir.models import EvidencePackage

PACKAGE_FILE_NAME = "package.json"
ANSWER_KEY_SEGMENTS = ("benchmarks", "answer_keys")


class AnswerKeyAccessError(RuntimeError):
    """The reviewer tried to read or write inside `benchmarks/answer_keys/`."""


@dataclass(frozen=True)
class LoadedPackage:
    """A package with the directory its relative paths (meshes, captures) point into."""

    package: EvidencePackage
    base_dir: Path

    def resolve(self, relative_path: str) -> Path:
        """Return the absolute path of a package-relative file such as `mesh_file`."""
        return self.base_dir / Path(relative_path)


def _checked_dir(directory: Path | str) -> Path:
    resolved = Path(directory).resolve()
    parts = resolved.parts
    for index in range(len(parts) - 1):
        if (parts[index].lower(), parts[index + 1].lower()) == ANSWER_KEY_SEGMENTS:
            raise AnswerKeyAccessError(
                f"{resolved} is inside benchmarks/answer_keys; answer keys are withheld "
                "from the reviewer"
            )
    return resolved


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
