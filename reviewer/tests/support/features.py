"""Builders for RMS feature-tree evidence packages (T003).

`packages.py` builds the fastener/interference package feature 001 tests share; this
module builds the feature-tree ones feature 003 needs, on top of it: `rms_package` calls
`build_package` with every RMS-relevant field replaced, so the schema version, package id,
creation time and extractor block stay in one place, and it reuses `persist_ref` for every
stand-in reference.

Two layers, deliberately:

1. **Specs** - frozen dataclasses (`FeatureSpec`, `EquationSpec`, `InstanceSpec`,
   `MateSpec`, `PartSpec`, `SubassemblySpec`, `AssemblySpec`) that say what a fixture
   contains, naming features and component instances by *name*.
2. **Layout** - `build_features` and `rms_package`, which allocate `feat:NNNN` and
   `cmp:NNNN` ids in traversal order, resolve every name to an id, and emit validated IR
   models.

The split exists because the same tree must be emitted in both traversal shapes of
`specs/003-resilient-modeling/contracts/rules.md` ("Group assignment"):

- ``"nested"``: a folder's contents are its sub-features - depth + 1, ``folder_id`` set;
- ``"flat"``: `IFeatureManager` reports no sub-features, so every row sits at depth 0 with
  ``folder_id`` null, a folder's contents simply follow it, and an end-tag marker
  (``<folder name>___EndTag___``, folder-typed) closes the folder.

Conventions: absence is `None` plus a `Gap`, never a favourable default (constitution
Principle I). `child_names=None` means "`GetChildren` failed" and produces `child_ids:
null`; `()` means "no dependents". A name that is not in the document is an error, not a
silently dropped reference.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from swreview.ir.models import (
    ComponentInstance,
    Design,
    Document,
    Equation,
    EvidencePackage,
    Feature,
    FilletInfo,
    Gap,
    Manifest,
    ManifestEntry,
    Mate,
    MateEntity,
    Quantity,
    SketchInfo,
    SuppressTestRow,
    SuppressTestRun,
)
from tests.support.packages import CREATED_AT, IDENTITY_TRANSFORM, build_package, persist_ref

# Kept in step with `swreview/checks/rms_types.yaml` by a test in
# `tests/unit/test_support_features.py`; hard-coded here so the fixtures do not depend on
# the loader they are used to test.
FOLDER_TYPE = "FtrFolder"
END_TAG_SUFFIX = "___EndTag___"

Shape = Literal["nested", "flat"]
Suppression = Literal["resolved", "lightweight", "suppressed", "unloaded"]


# --- 1. Specs ---------------------------------------------------------------------


@dataclass(frozen=True)
class SketchSpec:
    """`SketchInfo` before its consumer names are resolved to ids."""

    raw_status: int | None = 3
    consumer_names: Sequence[str] | None = ()
    text_segments: int | None = None
    """`SketchInfo.text_segment_count` (schema 1.4.0). Null by default, which is how a
    package written before that schema reads and how every feature 003 fixture stays
    byte-identical: the field is omitted when null."""


@dataclass(frozen=True)
class FeatureSpec:
    """One feature of a document's tree; `contents` makes it a folder's payload."""

    name: str
    type_name: str
    description: str | None = "intent"
    suppressed: bool | None = False
    error_code: int | None = 0
    child_names: Sequence[str] | None = ()
    parent_names: Sequence[str] | None = ()
    sketch: SketchSpec | None = None
    fillet: FilletInfo | None = None
    contents: tuple[FeatureSpec, ...] = ()
    end_tag: bool = True
    """Flat shape only: emit `<name>___EndTag___` after the contents of this folder."""


@dataclass(frozen=True)
class EquationSpec:
    text: str
    lhs: str
    is_global: bool | None = False
    value: float | None = None


@dataclass(frozen=True)
class InstanceSpec:
    """One `ComponentInstance` of a part or subassembly document."""

    name: str
    suppression: Suppression = "resolved"
    is_fixed: bool = False
    constrained_status_raw: int | None = None
    is_toolbox: bool = False
    parent_name: str | None = None
    """Another instance's name; `None` means the root assembly instance (`cmp:0001`)."""
    referenced_configuration: str | None = None
    """Defaults to the referenced document's configuration."""


@dataclass(frozen=True)
class MateSpec:
    """One mate of the root assembly; entities are `(instance name, entity kind)`."""

    entities: Sequence[tuple[str, str]]
    type: str = "COINCIDENT"
    alignment: Literal["aligned", "anti_aligned", "closest"] = "aligned"
    suppressed: bool = False
    suppression_gap: bool = False
    """Emit the `mate_suppression` gap: `IsSuppressed2` was unreadable for this mate."""

    entity_gap: bool = False
    """Emit the `mate` gap `MateDumper.ReadEntities` records when one entity could not be
    read: that entity is missing from `entities`, so the list here is incomplete and the
    entities that survived cannot answer for the one that did not."""


@dataclass(frozen=True)
class PartSpec:
    """One part document, its tree, its equations and its instances."""

    document_id: str
    name: str
    features: Sequence[FeatureSpec] = ()
    equations: Sequence[EquationSpec] = ()
    shape: Shape = "nested"
    configuration: str = "Default"
    configurations: Sequence[str] | None = None
    instances: Sequence[InstanceSpec] | None = None
    """Defaults to a single resolved instance named `<name>-1`."""
    material: str | None = None


@dataclass(frozen=True)
class SubassemblySpec:
    """A second assembly document under the root; its mates are not extracted."""

    document_id: str
    name: str
    instance: InstanceSpec | None = None


@dataclass(frozen=True)
class AssemblySpec:
    """The root assembly: instance `cmp:0001`, the mates, and one optional subassembly."""

    document_id: str = "doc:1"
    name: str = "cover-assy"
    configuration: str = "Default"
    mates: Sequence[MateSpec] = ()
    subassembly: SubassemblySpec | None = None


# --- 2. Feature builders ----------------------------------------------------------


def feature(name: str, type_name: str, **kwargs: Any) -> FeatureSpec:
    """One feature row. `description` defaults to a non-empty string, so a fixture is
    compliant unless it says otherwise; pass `""` for blank and `None` for the gap."""
    return FeatureSpec(name=name, type_name=type_name, **kwargs)


def sketch_feature(
    name: str,
    *,
    raw_status: int | None = 3,
    consumers: Sequence[str] | None = (),
    type_name: str = "ProfileFeature",
    text_segments: int | None = None,
    **kwargs: Any,
) -> FeatureSpec:
    """A sketch. `consumers` are its dependents: both `child_ids` and `consumer_ids`,
    which `GetChildren` reads as one call, unless `child_names` says otherwise."""
    kwargs.setdefault("child_names", consumers)
    return feature(
        name,
        type_name,
        sketch=SketchSpec(
            raw_status=raw_status, consumer_names=consumers, text_segments=text_segments
        ),
        **kwargs,
    )


def fillet_feature(
    name: str,
    *,
    radius_m: float | None = 0.005,
    type_name: str = "Fillet",
    **kwargs: Any,
) -> FeatureSpec:
    """A fillet with `DefaultRadius` in meters; `radius_m=None` is the unreadable case."""
    radius = None if radius_m is None else Quantity(value=radius_m, unit="m")
    return feature(name, type_name, fillet=FilletInfo(default_radius=radius), **kwargs)


def folder(name: str, *contents: FeatureSpec, **kwargs: Any) -> FeatureSpec:
    """A folder feature holding `contents`; pass `end_tag=False` to leave it unclosed."""
    return feature(name, FOLDER_TYPE, contents=tuple(contents), **kwargs)


def end_tag(folder_name: str, **kwargs: Any) -> FeatureSpec:
    """The end-tag marker of `folder_name`, placed by hand (the flat shape adds its own)."""
    return feature(f"{folder_name}{END_TAG_SUFFIX}", FOLDER_TYPE, description="", **kwargs)


def equation(
    text: str,
    *,
    is_global: bool | None = False,
    value: float | None = None,
    lhs: str | None = None,
) -> EquationSpec:
    """One equation row; `lhs` defaults to the text left of the first `=`, unquoted."""
    return EquationSpec(
        text=text,
        lhs=text.split("=", 1)[0].strip().strip('"') if lhs is None else lhs,
        is_global=is_global,
        value=value,
    )


# --- 3. Layout --------------------------------------------------------------------


@dataclass(frozen=True)
class _Placed:
    spec: FeatureSpec
    id: str
    depth: int
    folder_id: str | None


def build_features(
    specs: Sequence[FeatureSpec],
    *,
    document_id: str,
    shape: Shape = "nested",
    configuration: str = "Default",
    start: int = 1,
) -> list[Feature]:
    """Lay `specs` out as `Feature` rows in traversal order.

    `start` is the first `feat:NNNN` number, so one package can number several documents
    in one sequence. Names are how a spec points at children, parents and sketch
    consumers, so a name used twice cannot be pointed at: a repeated name builds (a
    duplicate group folder is normative, `rules.md` "Group assignment") but referencing it
    is refused.
    """
    if shape not in ("nested", "flat"):
        raise ValueError(f"unknown traversal shape {shape!r}: use 'nested' or 'flat'")

    placed: list[_Placed] = []
    counter = start

    def place(spec: FeatureSpec, depth: int, folder_id: str | None) -> None:
        nonlocal counter
        feature_id = f"feat:{counter:04d}"
        counter += 1
        placed.append(_Placed(spec=spec, id=feature_id, depth=depth, folder_id=folder_id))
        for child in spec.contents:
            if shape == "nested":
                place(child, depth + 1, feature_id)
            else:
                place(child, depth, folder_id)
        if shape == "flat" and _is_folder(spec) and spec.end_tag:
            place(end_tag(spec.name), depth, folder_id)

    for spec in specs:
        place(spec, 0, None)

    ids_by_name: dict[str, str] = {}
    occurrences: dict[str, int] = {}
    refs: list[str] = []
    for item in placed:
        seen = occurrences.get(item.spec.name, 0)
        occurrences[item.spec.name] = seen + 1
        ids_by_name.setdefault(item.spec.name, item.id)
        # Two rows may legitimately share a name (a re-opened group folder and, in the flat
        # shape, its end-tag marker); SOLIDWORKS still gives each row its own reference.
        suffix = "" if seen == 0 else f"#{seen + 1}"
        refs.append(persist_ref(f"{document_id}/{item.spec.name}{suffix}"))
    ambiguous = {name for name, count in occurrences.items() if count > 1}

    def resolve(names: Sequence[str] | None, whose: str) -> list[str] | None:
        if names is None:
            return None
        resolved: list[str] = []
        for name in names:
            if name in ambiguous:
                raise ValueError(
                    f"{whose} names {name!r}, which is the name of {occurrences[name]} "
                    f"features of {document_id}: rename one or drop the reference"
                )
            if name not in ids_by_name:
                raise ValueError(f"{whose} names {name!r}, which is not a feature of {document_id}")
            resolved.append(ids_by_name[name])
        return resolved

    rows: list[Feature] = []
    for index, item in enumerate(placed):
        spec = item.spec
        sketch = None
        if spec.sketch is not None:
            sketch = SketchInfo(
                raw_status=spec.sketch.raw_status,
                consumer_ids=resolve(spec.sketch.consumer_names, f"{spec.name} consumers"),
                text_segment_count=spec.sketch.text_segments,
            )
        rows.append(
            Feature(
                id=item.id,
                persist_ref=refs[index],
                persist_ref_scope=document_id,
                document_id=document_id,
                configuration=configuration,
                name=spec.name,
                type_name=spec.type_name,
                description=spec.description,
                index=index,
                depth=item.depth,
                folder_id=item.folder_id,
                suppressed=spec.suppressed,
                error_code=spec.error_code,
                child_ids=resolve(spec.child_names, f"{spec.name} children"),
                parent_ids=resolve(spec.parent_names, f"{spec.name} parents"),
                sketch=sketch,
                fillet=spec.fillet,
            )
        )
    return rows


def _is_folder(spec: FeatureSpec) -> bool:
    return spec.type_name == FOLDER_TYPE and not spec.name.endswith(END_TAG_SUFFIX)


# --- 4. The suppress-test run -----------------------------------------------------


def suppress_row(
    row_feature: Feature,
    outcome: Literal[
        "ok", "rebuild_errors", "already_suppressed", "not_applied", "truncated", "aborted"
    ],
    *,
    whats_wrong_count: int | None = None,
    messages: Sequence[str] = (),
    messages_truncated: int = 0,
    error: str | None = None,
    elapsed_ms: int | None = 120,
) -> SuppressTestRow:
    """One row of a run, identified by the built `Feature` it tested."""
    return SuppressTestRow(
        feature_id=row_feature.id,
        persist_ref=row_feature.persist_ref,
        persist_ref_scope=row_feature.persist_ref_scope,
        name=row_feature.name,
        outcome=outcome,
        whats_wrong_count=whats_wrong_count,
        messages=list(messages),
        messages_truncated=messages_truncated,
        error=error,
        elapsed_ms=elapsed_ms,
    )


def suppress_run(
    *,
    document_id: str,
    rows: Sequence[SuppressTestRow],
    configuration: str = "Default",
    group: str = "4-Detail",
    plan_file: str = "suppress-plan.json",
    run_at: datetime = CREATED_AT,
    baseline_whats_wrong_count: int = 0,
    limit: int = 50,
    timeout_seconds: int = 600,
    features_present: int | None = None,
    restore_verified: bool = True,
    unrestored_feature_ids: Sequence[str] = (),
) -> SuppressTestRun:
    """One `suppress-test` run; `features_present` defaults to the number of rows."""
    return SuppressTestRun(
        document_id=document_id,
        configuration=configuration,
        group=group,
        plan_file=plan_file,
        run_at=run_at,
        acknowledged=True,
        baseline_whats_wrong_count=baseline_whats_wrong_count,
        limit=limit,
        timeout_seconds=timeout_seconds,
        features_present=len(rows) if features_present is None else features_present,
        restore_verified=restore_verified,
        unrestored_feature_ids=list(unrestored_feature_ids),
        rows=list(rows),
    )


# --- 5. The gaps the dumpers record -----------------------------------------------

# One home for the two gap reasons a rule matches on prose, because prose is all the
# dumper leaves behind: the reason is the only link back to the subject. A fixture and a
# unit test that each spell the sentence themselves agree with each other and with nothing
# (constitution Principle V), so they call these instead. The C# side is still unpinned -
# reword `ComponentTreeDumper.ReadIsToolbox` or `MateDumper.ReadEntities` and these go
# stale silently.


def toolbox_identity_gap(full_path: str) -> Gap:
    """`ComponentTreeDumper.ReadIsToolbox` verbatim: no `entity_id`, and the component's
    `IComponent2.Name2` key - its `full_path` - quoted in the reason, which is the only
    link back to the instance. `is_toolbox` is false-on-failure, so a rule that misses
    this gap reads an unreadable component as "not Toolbox"."""
    return Gap(
        kind="not_extracted",
        entity_kind="component",
        entity_id=None,
        reason=f"'{full_path}' has no loaded model document, so Toolbox identity "
        "could not be read.",
        error=None,
    )


def mate_entity_gap(mate_id: str, index: int, mate_name: str = "Coincident1") -> Gap:
    """`MateDumper.ReadEntities` verbatim: each entity read is wrapped in
    `Gaps.TryStep("mate", <mate id>, "read entity <i> of mate '<name>'")`, so a failed
    read drops that entity from `Mate.entities` and records this gap against the mate."""
    return Gap(
        kind="tool_error",
        entity_kind="mate",
        entity_id=mate_id,
        reason=f"read entity {index} of mate '{mate_name}'",
        error="System.Runtime.InteropServices.COMException: the entity was not readable",
    )


# --- 6. The package ---------------------------------------------------------------


def rms_package(
    *,
    parts: Sequence[PartSpec] = (),
    assembly: AssemblySpec | None = None,
    suppress_test: SuppressTestRun | None = None,
    gaps: Sequence[Gap] = (),
) -> EvidencePackage:
    """An `EvidencePackage` carrying feature trees, equations, instances and mates.

    Documents are emitted root assembly, subassembly, then the parts in `parts` order;
    component instances are emitted root (`cmp:0001`), then each part's instances in
    `parts` order, then the subassembly's, so the *first child of the root* - what
    `rms.assembly.first_component_fixed` reports on - is the first instance of the first
    part. Without an `assembly` the package has no assembly document and `design`
    points at the first part (a part-only review); instances then have no parent.

    Non-resolved instances carry their `feature_tree_unavailable` gap, mates with
    `suppression_gap` their `mate_suppression` gap; `gaps` adds any others verbatim.
    """
    if not parts and assembly is None:
        raise ValueError("rms_package needs at least one part or an assembly")

    documents: list[Document] = []
    entries: list[ManifestEntry] = []
    components: list[ComponentInstance] = []
    built_gaps: list[Gap] = []

    if assembly is not None:
        documents.append(
            _document(assembly.document_id, assembly.name, "assembly", assembly.configuration)
        )
        entries.append(_entry(documents[-1]))
        if assembly.subassembly is not None:
            sub = assembly.subassembly
            documents.append(
                _document(sub.document_id, sub.name, "assembly", assembly.configuration)
            )
            entries.append(_entry(documents[-1]))
    for part in parts:
        documents.append(
            _document(
                part.document_id,
                part.name,
                "part",
                part.configuration,
                configurations=part.configurations,
                material=part.material,
            )
        )
        entries.append(_entry(documents[-1]))

    # Instances: names first (a parent may be emitted after its children), then the rows.
    instance_specs: list[tuple[InstanceSpec, str, str]] = []  # spec, document_id, configuration
    for part in parts:
        specs = part.instances if part.instances is not None else [InstanceSpec(f"{part.name}-1")]
        for spec in specs:
            instance_specs.append((spec, part.document_id, part.configuration))
    if assembly is not None and assembly.subassembly is not None:
        sub = assembly.subassembly
        sub_instance = sub.instance if sub.instance is not None else InstanceSpec(f"{sub.name}-1")
        instance_specs.append((sub_instance, sub.document_id, assembly.configuration))

    root_id = "cmp:0001" if assembly is not None else None
    ids_by_name: dict[str, str] = {}
    if assembly is not None:
        ids_by_name[assembly.name] = "cmp:0001"
    for number, (spec, _, _) in enumerate(instance_specs, start=2 if assembly is not None else 1):
        if spec.name in ids_by_name:
            raise ValueError(f"duplicate component instance name {spec.name!r}")
        ids_by_name[spec.name] = f"cmp:{number:04d}"

    if assembly is not None:
        components.append(
            ComponentInstance(
                id="cmp:0001",
                persist_ref=persist_ref("cmp:0001"),
                persist_ref_scope=assembly.document_id,
                name=assembly.name,
                full_path=assembly.name,
                document_id=assembly.document_id,
                parent_id=None,
                referenced_configuration=assembly.configuration,
                transform=IDENTITY_TRANSFORM,
                suppression="resolved",
                is_fixed=True,
                pattern_id=None,
                is_toolbox=False,
                constrained_status_raw=None,
            )
        )

    for spec, document_id, configuration in instance_specs:
        instance_id = ids_by_name[spec.name]
        if spec.parent_name is None:
            parent_id = root_id
            full_path = spec.name
        else:
            if spec.parent_name not in ids_by_name:
                raise ValueError(
                    f"{spec.name!r} names parent {spec.parent_name!r}, "
                    "which is not a component instance of this package"
                )
            parent_id = ids_by_name[spec.parent_name]
            full_path = f"{spec.parent_name}/{spec.name}"
        components.append(
            ComponentInstance(
                id=instance_id,
                persist_ref=persist_ref(instance_id),
                persist_ref_scope=assembly.document_id if assembly is not None else document_id,
                name=spec.name,
                full_path=full_path,
                document_id=document_id,
                parent_id=parent_id,
                referenced_configuration=spec.referenced_configuration or configuration,
                transform=IDENTITY_TRANSFORM,
                suppression=spec.suppression,
                is_fixed=spec.is_fixed,
                pattern_id=None,
                is_toolbox=spec.is_toolbox,
                constrained_status_raw=spec.constrained_status_raw,
            )
        )
        if spec.suppression != "resolved":
            built_gaps.append(
                Gap(
                    kind="not_extracted",
                    entity_kind="feature_tree_unavailable",
                    entity_id=instance_id,
                    reason=f"component {full_path} is {spec.suppression}; feature tree not read",
                    error=None,
                )
            )

    mates: list[Mate] = []
    if assembly is not None:
        for number, mate_spec in enumerate(assembly.mates, start=1):
            mate_id = f"mate:{number:04d}"
            mates.append(
                Mate(
                    id=mate_id,
                    persist_ref=persist_ref(mate_id),
                    persist_ref_scope=assembly.document_id,
                    type=mate_spec.type,
                    entities=[
                        MateEntity(
                            component_id=_instance_id(ids_by_name, name, mate_id),
                            persist_ref=persist_ref(f"{mate_id}/{name}"),
                            entity_kind=kind,
                        )
                        for name, kind in mate_spec.entities
                    ],
                    alignment=mate_spec.alignment,
                    suppressed=mate_spec.suppressed,
                    distance=None,
                    angle=None,
                )
            )
            if mate_spec.suppression_gap:
                built_gaps.append(
                    Gap(
                        kind="not_extracted",
                        entity_kind="mate_suppression",
                        entity_id=mate_id,
                        reason="mate suppression state not readable",
                        error=None,
                    )
                )
            if mate_spec.entity_gap:
                built_gaps.append(mate_entity_gap(mate_id, len(mate_spec.entities)))

    features: list[Feature] = []
    equations: list[Equation] = []
    for part in parts:
        features.extend(
            build_features(
                part.features,
                document_id=part.document_id,
                shape=part.shape,
                configuration=part.configuration,
                start=len(features) + 1,
            )
        )
        for index, spec in enumerate(part.equations):
            equations.append(
                Equation(
                    document_id=part.document_id,
                    index=index,
                    text=spec.text,
                    lhs=spec.lhs,
                    is_global=spec.is_global,
                    value=spec.value,
                )
            )

    root_document = assembly.document_id if assembly is not None else parts[0].document_id
    design_name = assembly.name if assembly is not None else parts[0].name
    configuration = assembly.configuration if assembly is not None else parts[0].configuration
    return build_package(
        manifest=Manifest(entries=entries, discrepancies=[]),
        design=Design(
            design_id="dsn:1",
            name=design_name,
            root_assembly_document_id=root_document,
            active_configuration=configuration,
            drawing_document_ids=[],
        ),
        documents=documents,
        components=components,
        mates=mates,
        holes=[],
        fasteners=[],
        features=features,
        equations=equations,
        rms_suppress_test=suppress_test,
        gaps=[*built_gaps, *gaps],
    )


def _instance_id(ids_by_name: dict[str, str], name: str, mate_id: str) -> str:
    if name not in ids_by_name:
        raise ValueError(f"{mate_id} names {name!r}, which is not a component instance")
    return ids_by_name[name]


def _document(
    document_id: str,
    name: str,
    kind: Literal["part", "assembly"],
    configuration: str,
    *,
    configurations: Sequence[str] | None = None,
    material: str | None = None,
) -> Document:
    file_name = f"{name}.{'SLDPRT' if kind == 'part' else 'SLDASM'}"
    return Document(
        document_id=document_id,
        kind=kind,
        file_name=file_name,
        path=f"native/{file_name}",
        configurations=list(configurations) if configurations is not None else [configuration],
        active_configuration=configuration,
        custom_properties={},
        config_properties={},
        material=material,
        mass=None,
    )


def _entry(document: Document) -> ManifestEntry:
    return ManifestEntry(
        document_id=document.document_id,
        vault_path=f"/Designs/{document.file_name}",
        vault_version=1,
        revision="A",
        configuration=document.active_configuration,
        local_modified=False,
        export_method="native",
    )
