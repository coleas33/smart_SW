"""Generate the `package.json` and `case.json` of every remodel-plan fixture (T030).

Run once, from `reviewer/`, and commit what it writes:

    uv run python tests/golden/fixtures/remodel-plan/generate_packages.py

Then regenerate the baselines for these cases only and read every one of them:

    uv run pytest tests/golden/test_golden.py --force-regen -k remodel-

A script and not thirteen hand-written packages for the reason the rms-part fixture gives:
the shape of a feature tree in `package.json` - ids in traversal order, `folder_id`,
`depth`, resolved child, parent and consumer ids, one `persist_ref` per row - is what
`tests/support/features.py` and `tests/support/remodel.py` (T005) already know how to lay
out, and a second hand-maintained copy of that knowledge would drift from the builders the
unit tests use. The *intent* - what each fixture is a fixture of - lives here and is
readable without reading any JSON.

**Four golden plans**, named as `quickstart.md` scenario 1 names them:

| Fixture | What the plan must show |
|---|---|
| `remodel-ordered` | zero moves, the group folders already correct, an empty rebuild list |
| `remodel-reversed` | a full reorder of a tree with no dependencies, each folder created once |
| `remodel-pinned` | a Core chamfer held below the Detail cut it was made on, the |
| | blocking edge named, and both split groups named with their interlopers |
| `remodel-duplicate-names` | two features sharing a name, renamed first as a |
| | recorded, reversible `rename` change, before anything is reordered |

**One fixture per refusal category.** Five of them are scope signals no dump carries, so
the case file supplies the `ScopeSignals` the probe would have read; the sixth is the
existing group-named folder, which is decidable from the tree itself, and the seventh is a
part that trips two signals at once and must name both:

`remodel-refusal-multibody`, `remodel-refusal-weldment`, `remodel-refusal-sheet-metal`,
`remodel-refusal-mesh-body`, `remodel-refusal-3d-interconnect`,
`remodel-refusal-rms-folder`, `remodel-refusal-two-signals`.

**Two more**, because the rebuild list is the product of stage 1 and a reason that is only
ever asserted in a unit test is a reason no artifact has ever been read for:

| Fixture | Reasons it carries |
|---|---|
| `remodel-cycle` | `cycle`: no legal order exists, it is named, and the plan refuses |
| `remodel-unplaceable` | `radius_unreadable`, `unclassified`, `graph_unreadable` |
| | and `shared_sketch`, in one tree |

Every reason id in a baseline is hand-checked against the closed taxonomy of
`data-model.md` section 1.5 (`backward_reference`, `shared_sketch`, `splits_group`,
`cycle`, `radius_unreadable`, `ambiguous_name`, `unclassified`, `graph_unreadable`) and
every refusal code against the closed set of section 4.2.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[3]))

from tests.support.features import (  # noqa: E402
    FeatureSpec,
    feature,
    fillet_feature,
    folder,
    sketch_feature,
)
from tests.support.remodel import (  # noqa: E402
    UNKNOWN_TYPE_NAME,
    linked,
    remodel_package,
    scope_signals,
)

from swreview.checks.rms_types import load_table  # noqa: E402
from swreview.ir.loader import save_package  # noqa: E402

CALLABLE = "swreview.checks.golden_remodel:plan_case"
TABLE = load_table()
REF, CONSTRUCTION, CORE, DETAIL, MODIFY, QUARANTINE = TABLE.groups


# --- the four golden plans --------------------------------------------------------


def ordered() -> list[FeatureSpec]:
    """Already organized: every feature in the folder its target group names, in order.

    The sketches sit in the folders of the features that consume them, not in
    `2-Construction`: a consumed sketch follows its single consumer, and only an unconsumed
    one takes the construction default.
    """
    return linked(
        [
            folder(
                CORE,
                sketch_feature("Sketch1"),
                feature("Boss-Extrude1", "Extrusion"),
                feature("Shell1", "Shell"),
            ),
            folder(
                DETAIL,
                sketch_feature("Sketch2"),
                feature("Cut-Extrude1", "Cut"),
                feature("Hole1", "HoleWzd"),
            ),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Shell1"),
        ("Boss-Extrude1", "Sketch2"),
        ("Sketch2", "Cut-Extrude1"),
        ("Cut-Extrude1", "Hole1"),
    )


def reversed_tree() -> list[FeatureSpec]:
    """Every group in the wrong order and no dependency to stop any of it moving.

    The worst case for the edit script and the best case for the method: nothing is pinned,
    so the achievable order is the desired order and the script is the
    longest-increasing-subsequence minimum rather than one move per feature.
    """
    return [
        fillet_feature("Fillet1"),
        feature("Hole1", "HoleWzd"),
        feature("Cut-Extrude1", "Cut"),
        feature("Draft1", "Draft"),
        feature("Boss-Extrude1", "Extrusion"),
        sketch_feature("Sketch1"),
    ]


def pinned() -> list[FeatureSpec]:
    """A `3-Core` chamfer cut on an edge the `4-Detail` cut made.

    The chamfer cannot rise above the cut it depends on, so it is pinned by that edge; it
    then sits inside the Detail span while the Detail features sit inside the Core span, so
    neither group can be folded and every member of both is on the rebuild list with
    `splits_group`. This is `research.md` R6.5's example and the honest picture of stage 1:
    a legal order exists, and it is not the method's order.
    """
    return linked(
        [
            feature("Front Plane", "RefPlane"),
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            fillet_feature("Fillet1"),
            sketch_feature("Sketch2"),
            feature("Cut-Extrude1", "Cut"),
            feature("Hole1", "HoleWzd"),
            feature("Chamfer1", "Chamfer"),
            feature("Shell1", "Shell"),
        ],
        ("Front Plane", "Sketch1"),
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Fillet1"),
        ("Front Plane", "Sketch2"),
        ("Sketch2", "Cut-Extrude1"),
        ("Cut-Extrude1", "Hole1"),
        ("Cut-Extrude1", "Chamfer1"),
        ("Fillet1", "Shell1"),
    )


def duplicate_names() -> list[FeatureSpec]:
    """Two `Fillet1`s, one per derived subfolder, which SOLIDWORKS permits.

    `IModelDocExtension.ReorderFeature` is name-addressed and returns no error code that
    could say it moved the wrong one, so one of the two is renamed - recorded and
    reversible - before any reorder. The subfolders are derived and not group-named, so the
    tree exercises the rename without also tripping the v1 folder refusal.
    """
    return [
        feature("Cut-Extrude1", "Cut"),
        folder("Ribs", feature("Rib1", "Extrusion"), fillet_feature("Fillet1")),
        folder("Slots", feature("Rib2", "Extrusion"), fillet_feature("Fillet1")),
    ]


# --- the refusals -----------------------------------------------------------------


def plain() -> list[FeatureSpec]:
    """An ordinary little part: the subject of every signal-driven refusal fixture.

    The tree is beside the point in those fixtures - the refusal comes from a reading no
    dump carries - so it is the same tree in all of them, and a diff between two refusal
    baselines is the refusal and nothing else.
    """
    return linked(
        [
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            feature("Cut-Extrude1", "Cut"),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Cut-Extrude1"),
    )


def mis_membered() -> list[FeatureSpec]:
    """A folder already called `3-Core` holding two Detail features, with a Core fillet
    outside it.

    A superset and a subset at once. `IModelDoc2.EditDelete` is not in the stage-1
    allowlist, so there is no dissolve path and v1 refuses the whole part before anything
    is copied - which is a scope refusal, `rms_named_folder_wrong_members`, and never a
    ninth rebuild-list reason.
    """
    return linked(
        [
            sketch_feature("Sketch1"),
            folder(
                CORE,
                feature("Boss-Extrude1", "Extrusion"),
                feature("Cut-Extrude1", "Cut"),
                feature("Hole1", "HoleWzd"),
            ),
            fillet_feature("Fillet1"),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Cut-Extrude1"),
        ("Cut-Extrude1", "Hole1"),
        ("Boss-Extrude1", "Fillet1"),
    )


def cycle() -> list[FeatureSpec]:
    """Two features each declared a parent of the other: no topological order exists.

    The planner names the cycle and refuses. It never searches for a break, and the walk
    that finds it is bounded by the feature count, because a dry run that hangs is worse
    than a dry run that refuses.
    """
    return linked(
        [
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            feature("Cut-Extrude1", "Cut"),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Cut-Extrude1"),
        ("Cut-Extrude1", "Boss-Extrude1"),
    )


def unplaceable() -> list[FeatureSpec]:
    """Four reasons in one tree, each with its evidence.

    - `Fillet-Variable1` has no readable `DefaultRadius`, so `largest_fillet_first` cannot
      rank it: `radius_unreadable`, and it is blocked rather than given a position;
    - `Deform1` carries a `GetTypeName2` value `rms_types.yaml` does not classify:
      `unclassified`, reported unresolved and never "movable";
    - `Boss-Extrude2` had both `GetChildren` and `GetParents` fail: `graph_unreadable`, and
      a feature whose graph was never read is never moved;
    - `Sketch1` is consumed by two features, so it can be contiguous with only one of them:
      `shared_sketch`.
    """
    return linked(
        [
            sketch_feature("Sketch1", consumers=("Boss-Extrude1", "Cut-Extrude1")),
            feature("Boss-Extrude1", "Extrusion"),
            feature("Cut-Extrude1", "Cut"),
            fillet_feature("Fillet1"),
            fillet_feature("Fillet-Variable1", radius_m=None),
            feature("Deform1", UNKNOWN_TYPE_NAME),
            feature("Boss-Extrude2", "Extrusion", child_names=None, parent_names=None),
        ],
        ("Boss-Extrude1", "Fillet1"),
        ("Boss-Extrude1", "Fillet-Variable1"),
        ("Boss-Extrude1", "Deform1"),
    )


# --- the cases --------------------------------------------------------------------


def named_folder_signal(name: str) -> list[dict[str, Any]]:
    """The `rms_named_folders` row the probe would read for a group-named folder.

    The members are persist refs because the probe runs before any package is dumped; the
    refusal is on the folder's presence, so the list is what matters and not its contents.
    """
    return [{"name": name, "member_persist_refs": []}]


CASES: tuple[tuple[str, list[FeatureSpec], dict[str, Any] | None], ...] = (
    ("remodel-ordered", ordered(), None),
    ("remodel-reversed", reversed_tree(), None),
    ("remodel-pinned", pinned(), None),
    ("remodel-duplicate-names", duplicate_names(), None),
    ("remodel-refusal-multibody", plain(), scope_signals(solid_body_count=2)),
    ("remodel-refusal-weldment", plain(), scope_signals(is_weldment=True)),
    (
        "remodel-refusal-sheet-metal",
        plain(),
        scope_signals(sheet_metal_folder_present=True),
    ),
    ("remodel-refusal-mesh-body", plain(), scope_signals(mesh_body_present=True)),
    ("remodel-refusal-3d-interconnect", plain(), scope_signals(is_3d_interconnect=True)),
    (
        "remodel-refusal-rms-folder",
        mis_membered(),
        scope_signals(rms_named_folders=named_folder_signal(CORE)),
    ),
    (
        "remodel-refusal-two-signals",
        plain(),
        scope_signals(solid_body_count=3, is_weldment=True),
    ),
    ("remodel-cycle", cycle(), None),
    ("remodel-unplaceable", unplaceable(), None),
)
"""Every fixture: its directory name, its tree, and the scope signals the probe would have
read. `None` signals is the dry run's own answer - nothing was read, and the gate says so
of each signal in turn."""


def write(name: str, features: Sequence[FeatureSpec], signals: dict[str, Any] | None) -> None:
    directory = FIXTURE_DIR / name
    save_package(remodel_package(list(features), name=name), directory)
    case: dict[str, Any] = {"callable": CALLABLE}
    if signals is not None:
        case["kwargs"] = {"signals": signals, "probe_id": f"probe:{name}"}
    (directory / "case.json").write_text(
        json.dumps(case, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {directory}")


def main() -> None:
    for name, features, signals in CASES:
        write(name, features, signals)


if __name__ == "__main__":
    main()
