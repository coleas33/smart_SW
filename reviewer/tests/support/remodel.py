"""Builders for the re-modeler's part fixtures (feature 004 T005).

`features.py` builds the feature-tree packages feature 003's rules are tested against;
this module builds the ones feature 004's planner is tested against, on top of it. It adds
three things and re-creates nothing:

1. `remodel_package` - one part, opened alone, stamped `extractor.profile: "model_check"`.
   That is the shape feature 003 US6's Model check produces and the shape
   `package-before.json` will carry, and it is the only shape the planner ever receives: a
   package built at IR 1.1.0 carries no `profile` field at all, and both serializers forbid
   unknown members, so there is no such thing as a 1.1.0 package with a profile.
2. `linked` - the dependency graph declared once, as `(parent, child)` edges, and stamped
   in **both** directions. The planner reads `parent_ids` to order and `child_ids` to
   decide what a move would break, so a fixture whose two directions disagreed would be
   grading the planner against a tree SOLIDWORKS cannot produce.
3. one builder per tree the planner has to survive: a clean dependency chain, duplicate
   feature names, a shared sketch, a variable-radius fillet, an unclassified type, an
   RMS-named folder holding the wrong members, and a derived subfolder.

`scope_signals` is the fourth: the rows of `specs/004-resilient-remodeler/data-model.md`
section 4.1 as a plain dict, because `ScopeSignals` itself is `remodel/scope.py`'s type
(T023) and a fixture module may not own a product type. A null row is an unreadable
signal, never a pass, so every default here is a readable, in-scope value and a test that
wants unreadable asks for it by name.

`stage_1_sources` and `code_lines` are the fifth: the file list every "nothing in stage 1
calls this member" assertion scans, kept here so the re-modeler's tests scan the same
surface rather than each keeping its own idea of what stage 1 is.

Convention, inherited from `features.py`: absence is `None` plus a gap, never a favourable
default (constitution Principle I). `child_names=None` still means "`GetChildren` failed",
and `linked` leaves such a direction alone rather than inventing the reading.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from swreview.ir.models import EvidencePackage, Gap
from tests.support.features import (
    EquationSpec,
    FeatureSpec,
    PartSpec,
    Shape,
    SketchSpec,
    feature,
    fillet_feature,
    folder,
    rms_package,
    sketch_feature,
)

MODEL_CHECK_PROFILE = "model_check"
"""The dump profile feature 003 US6 writes for a part opened alone."""

UNKNOWN_TYPE_NAME = "Deform"
"""A real `GetTypeName2` value that `rms_types.yaml` does not classify. The planner must
report a feature carrying it `unresolved` and never move it; the fixture asserts it is
still absent from the table, so calibrating the table fails this loudly rather than
quietly turning the unclassified case into a classified one."""

SCOPE_SIGNAL_FIELDS: tuple[str, ...] = (
    "document_type",
    "solid_body_count",
    "sheet_body_count",
    "is_weldment",
    "sheet_metal_folder_present",
    "mesh_body_present",
    "graphics_body_present",
    "is_3d_interconnect",
    "imported_file_names",
    "configuration_names",
    "rms_named_folders",
    "external_reference_count",
    "save_flag_dirty",
    "read_only",
    "rebuild_error_count",
    "vault",
)
"""Every row of `ScopeSignals` (data-model.md section 4.1), in the table's order."""


# --- 1. The package ---------------------------------------------------------------


def remodel_package(
    features: Sequence[FeatureSpec],
    *,
    document_id: str = "doc:1",
    name: str = "bracket",
    equations: Sequence[EquationSpec] = (),
    shape: Shape = "nested",
    configuration: str = "Default",
    configurations: Sequence[str] | None = None,
    gaps: Sequence[Gap] = (),
) -> EvidencePackage:
    """One part document, opened alone, at the profile the planner receives.

    `rms_package` builds the package (so the schema version, ids, creation time and
    manifest stay in one place) and the profile is stamped onto the extractor block
    afterwards, because `features.py` is feature 003's and the profile is feature 004's
    only requirement of it.
    """
    package = rms_package(
        parts=[
            PartSpec(
                document_id=document_id,
                name=name,
                features=features,
                equations=equations,
                shape=shape,
                configuration=configuration,
                configurations=configurations,
            )
        ],
        gaps=gaps,
    )
    return package.model_copy(
        update={
            "extractor": package.extractor.model_copy(
                update={"profile": MODEL_CHECK_PROFILE}
            )
        }
    )


# --- 2. The dependency graph ------------------------------------------------------


def linked(specs: Sequence[FeatureSpec], *edges: tuple[str, str]) -> list[FeatureSpec]:
    """Stamp `(parent name, child name)` edges onto `specs` in both directions.

    The parent gains the child in `child_names`, the child gains the parent in
    `parent_names`, and a sketch's `consumer_names` gains every dependent its
    `child_names` gains - they are one `GetChildren` call in the dumper, so a fixture
    where they differ is one no dump produces. Names already declared are kept, in the
    order they were declared, and never duplicated.

    Refused rather than guessed: an edge naming a feature that is not in `specs`, an edge
    from a feature to itself, and an edge naming a name two features share - the same
    ambiguity that makes a name-addressed `ReorderFeature` undecidable, and the reason the
    plan renames duplicates before it reorders anything.

    A direction that is `None` (`GetChildren` or `GetParents` failed, the
    `graph_unreadable` case) stays `None`: the edge is dropped on that end only.
    """
    occurrences: dict[str, int] = {}
    for spec in _walk(specs):
        occurrences[spec.name] = occurrences.get(spec.name, 0) + 1

    children: dict[str, list[str]] = {}
    parents: dict[str, list[str]] = {}
    for parent, child in edges:
        if parent == child:
            raise ValueError(f"edge ({parent!r}, {child!r}) names one feature twice")
        for name in (parent, child):
            count = occurrences.get(name, 0)
            if count == 0:
                raise ValueError(
                    f"edge ({parent!r}, {child!r}) names {name!r}, which is not one of "
                    "these features"
                )
            if count > 1:
                raise ValueError(
                    f"edge ({parent!r}, {child!r}) names {name!r}, which {count} features "
                    "share: a name-addressed reorder cannot say which one is meant"
                )
        children.setdefault(parent, []).append(child)
        parents.setdefault(child, []).append(parent)

    return [_link(spec, children, parents) for spec in specs]


def _walk(specs: Sequence[FeatureSpec]) -> list[FeatureSpec]:
    """Every spec, folder contents included, in traversal order."""
    walked: list[FeatureSpec] = []
    for spec in specs:
        walked.append(spec)
        walked.extend(_walk(spec.contents))
    return walked


def _link(
    spec: FeatureSpec, children: dict[str, list[str]], parents: dict[str, list[str]]
) -> FeatureSpec:
    added_children = children.get(spec.name, [])
    sketch = spec.sketch
    if sketch is not None and sketch.consumer_names is not None:
        sketch = SketchSpec(
            raw_status=sketch.raw_status,
            consumer_names=_extend(sketch.consumer_names, added_children),
        )
    return replace(
        spec,
        child_names=_extend(spec.child_names, added_children),
        parent_names=_extend(spec.parent_names, parents.get(spec.name, [])),
        sketch=sketch,
        contents=tuple(_link(child, children, parents) for child in spec.contents),
    )


def _extend(declared: Sequence[str] | None, added: Sequence[str]) -> tuple[str, ...] | None:
    if declared is None:
        return None
    names = list(declared)
    for name in added:
        if name not in names:
            names.append(name)
    return tuple(names)


# --- 3. The trees the planner has to survive --------------------------------------


def dependency_chain_features() -> list[FeatureSpec]:
    """A plain part, already in RMS order, with every edge declared.

    The baseline: the planner should find nothing to move here, so a plan with moves over
    this tree is a defect in the planner and not in the part.
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


def duplicate_name_features() -> list[FeatureSpec]:
    """Two features called `Fillet1`, one per folder, which SOLIDWORKS permits.

    `IModelDocExtension.ReorderFeature` is name-addressed and reports no error code that
    could tell you it moved the wrong one, so this tree must be renamed before it is
    reordered. Neither duplicate carries an edge: `build_features` resolves references by
    name and refuses to point at an ambiguous one, which is the same ambiguity stated in
    the fixture rather than worked around.
    """
    return [
        folder(
            "3-Core",
            feature("Boss-Extrude1", "Extrusion"),
            fillet_feature("Fillet1"),
        ),
        folder(
            "4-Detail",
            feature("Cut-Extrude1", "Cut"),
            fillet_feature("Fillet1"),
        ),
    ]


def shared_sketch_features() -> list[FeatureSpec]:
    """One sketch consumed by two features: the `shared_sketch` rebuild-list case."""
    return linked(
        [
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            feature("Cut-Extrude1", "Cut"),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Sketch1", "Cut-Extrude1"),
    )


def variable_radius_fillet_features() -> list[FeatureSpec]:
    """A fillet whose `DefaultRadius` is unreadable, beside one that is readable.

    `largest_fillet_first` cannot rank the unreadable one, so it is blocked with reason
    `radius_unreadable` rather than given an arbitrary position.
    """
    return linked(
        [
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            fillet_feature("Fillet1", radius_m=0.005),
            fillet_feature("Fillet-Variable1", radius_m=None),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Fillet1"),
        ("Boss-Extrude1", "Fillet-Variable1"),
    )


def unknown_type_features() -> list[FeatureSpec]:
    """A feature whose `GetTypeName2` the type table does not carry.

    It is content - a feature nobody recognises is exactly one a reviewer must look at -
    and it is never moved: `unresolved` is terminal (Principle I).
    """
    return linked(
        [
            sketch_feature("Sketch1"),
            feature("Boss-Extrude1", "Extrusion"),
            feature("Deform1", UNKNOWN_TYPE_NAME),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Deform1"),
    )


def mis_membered_group_folder_features() -> list[FeatureSpec]:
    """A folder already called `3-Core` that holds two features belonging in `4-Detail`,
    while a fillet that belongs in it sits outside.

    Both halves matter: the folder is a superset (it holds what it should not) and a
    subset (it lacks what it should hold). `IModelDoc2.EditDelete` is not in the stage-1
    allowlist, so there is no dissolve path and v1 refuses the whole part with
    `rms_named_folder_wrong_members` before anything is copied.
    """
    return linked(
        [
            sketch_feature("Sketch1"),
            folder(
                "3-Core",
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


def derived_subfolder_features() -> list[FeatureSpec]:
    """A folder inside a group folder, which the plan preserves and never dissolves."""
    return linked(
        [
            sketch_feature("Sketch1"),
            folder(
                "3-Core",
                feature("Boss-Extrude1", "Extrusion"),
                folder(
                    "Ribs",
                    feature("Rib1", "Extrusion"),
                    feature("Rib2", "Extrusion"),
                ),
            ),
        ],
        ("Sketch1", "Boss-Extrude1"),
        ("Boss-Extrude1", "Rib1"),
        ("Boss-Extrude1", "Rib2"),
    )


# --- 4. Scope signals -------------------------------------------------------------


def scope_signals(**overrides: Any) -> dict[str, Any]:
    """The `ScopeSignals` rows of data-model.md section 4.1, as a plain dict.

    A dict rather than a model because `ScopeSignals` belongs to `remodel/scope.py`
    (T023); the gate's own tests construct it from this.

    Every default is a readable, in-scope value - one solid body, no weldment, no
    sheet-metal folder, no mesh or graphics body, no 3D Interconnect, one configuration -
    so a signal that is `None` in a test is one the test asked to be unreadable. `vault`
    is the single exception: no vault is `None`, and it is recorded, never refused.

    A name the table does not carry is refused, so a signal renamed in the data model
    cannot be silently added here as a second spelling.
    """
    unknown = sorted(set(overrides) - set(SCOPE_SIGNAL_FIELDS))
    if unknown:
        raise ValueError(
            f"{unknown} {'are' if len(unknown) > 1 else 'is'} not a scope signal; the "
            f"rows are {list(SCOPE_SIGNAL_FIELDS)}"
        )
    signals: dict[str, Any] = {
        "document_type": 1,
        "solid_body_count": 1,
        "sheet_body_count": 0,
        "is_weldment": False,
        "sheet_metal_folder_present": False,
        "mesh_body_present": False,
        "graphics_body_present": False,
        "is_3d_interconnect": False,
        "imported_file_names": [],
        "configuration_names": ["Default"],
        "rms_named_folders": [],
        "external_reference_count": 0,
        "save_flag_dirty": False,
        "read_only": False,
        "rebuild_error_count": 0,
        "vault": None,
    }
    signals.update(overrides)
    return signals


# --- 5. The stage-1 source scan ---------------------------------------------------

STAGE_1_SOURCE_DIRS: tuple[tuple[str, str], ...] = (
    ("reviewer/src/swreview/remodel", "*.py"),
    ("extractor/SwReview.Extractor/Rms", "*.cs"),
    ("extractor/SwReview.Extractor/Guard", "*.cs"),
)
"""Every directory the re-modeler's stage-1 surface is written in, Python and C#. A member
can only be called from one of these, so scanning them is what makes "nothing calls it" a
claim about stage 1 rather than about two modules that could never have named it."""

_COMMENT_PREFIXES = ("#", "//", "/*", "*")


def code_lines(path: Path) -> list[str]:
    """The file's lines with whole-line comments dropped, so prose about a member the
    guard refuses does not read as a call to it."""
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith(_COMMENT_PREFIXES)
    ]


def stage_1_sources() -> list[Path]:
    """Every stage-1 source file, refusing a directory that matched nothing: a scan over
    an empty list passes vacuously, which is the one way this assertion could rot."""
    root = Path(__file__).resolve().parents[3]
    files: list[Path] = []
    for directory, pattern in STAGE_1_SOURCE_DIRS:
        found = sorted((root / directory).glob(pattern))
        assert found, f"{directory} matched no {pattern}: this scan would pass vacuously"
        files.extend(found)
    return files
