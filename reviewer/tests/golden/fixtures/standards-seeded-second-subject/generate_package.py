"""Generate `standards-seeded-second-subject`: `standards-seeded` plus one subject (T090).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/standards-seeded-second-subject/generate_package.py

The re-review case of `contracts/standards-check.md` section 5, as a package: a design an
engineer has already accepted a check on, in which **the same check on the same document
now fails on a second subject**. The accepted exception still *matches* - same check, same
configuration, same document, same bindings - and its fingerprint no longer does, because
a standards fingerprint hashes every input the check read for that document. So the finding
**stands** and names the exception as needing re-review, which is the one behaviour SC-008
is about and the one a silenced waiver would hide.

**The second subject is a second cut-list item that is not excluded**, on `MR-10001`, the
part `standards-seeded` already fails `standards.part.cut_list_excluded` on. One check, one
document, two subjects: nothing else about the design moves, so a diff between the two
baselines is the re-review case and nothing else.

Built from the seeded generator's own package rather than from a second copy of its intent:
that generator says which document, component, feature and dimension seeds which check, and
a hand-maintained second copy of twenty specs would drift from it the first time either is
edited. What is written here is the one row that differs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.checks.standards_fixtures import write_fixture  # noqa: E402
from tests.support.packages import persist_ref  # noqa: E402

from swreview.ir.models import CutListItem, EvidencePackage  # noqa: E402

SEEDED_GENERATOR = FIXTURE_DIR.parent / "standards-seeded" / "generate_package.py"

SECOND_ITEM = "Tube 60 x 60 x 3"
"""The second cut-list item, and it is **not** excluded from the cut list, which is what
makes it a second subject of the same check rather than a second passing row."""

SECOND_FOLDER = "Cut-List-Item2"


def seeded() -> EvidencePackage:
    """The `standards-seeded` package, built by its own generator."""
    spec = importlib.util.spec_from_file_location(
        "standards_seeded_generator", SEEDED_GENERATOR
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


def build() -> EvidencePackage:
    package = seeded()
    first = next(item for item in package.cut_list_items if not item.excluded_from_cut_list)
    item_id = f"cut:{len(package.cut_list_items) + 1:04d}"
    second = CutListItem(
        id=item_id,
        document_id=first.document_id,
        configuration=first.configuration,
        folder_name=SECOND_FOLDER,
        folder_type_name=first.folder_type_name,
        name=SECOND_ITEM,
        body_count=first.body_count,
        excluded_from_cut_list=False,
        persist_ref=persist_ref(item_id),
        persist_ref_scope=first.persist_ref_scope,
    )
    return package.model_copy(
        update={"cut_list_items": [*package.cut_list_items, second]}
    )


def main() -> None:
    write_fixture(FIXTURE_DIR, build())


if __name__ == "__main__":
    main()
