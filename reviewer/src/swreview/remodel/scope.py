"""The scope gate: what this run may be asked to re-model, decided before anything is copied.

`ScopeGate.evaluate(signals)` is a pure function of the rows `remodel.probe_scope` reads off
the engineer's already-open source (`data-model.md` section 4.1). It takes **one**
`ScopeSignals` and nothing else: no copy path, no `IModelDoc2`, no probe id. That is the
whole point of the split, and it is what FR-001 asks for - the run is refused *before any
copy is made and before any document handle to the source exists*, so a reason the gate
could only reach by opening something would arrive too late to be that refusal.

The measurement happens in C# because the calls are COM; the verdict happens here because a
verdict nobody can table-test on a machine without a SOLIDWORKS seat is a verdict nobody
re-checks (`research.md` R4.2).

**The refusal table** (`research.md` R4.1). A refusal costs nothing; a half-rebuilt
sheet-metal part costs the engineer their afternoon:

| Signal | Verdict |
|---|---|
| more than one solid body | refuse: the gate cannot pair bodies unambiguously |
| weldment | refuse |
| sheet-metal folder present | refuse: the six groups do not model bends, K-factor or flat pattern |
| mesh or graphics body | refuse: no B-rep, so no geometry gate |
| 3D Interconnect | refuse: editing fights the live link |
| a folder named for one of the six groups | refuse (v1): see below |
| imported dumb solid | allow, and report the reorganize stage as a no-op |
| surface bodies | allow, and report the surface coverage **uncovered**, never passed |
| configurations | record the count; it drives `which_configs` on every equation add |
| a derived or mirrored base feature | refuse (`derived_part`): the body is another part's |

The last row is decided from the package's feature rows by `derived_part_refusals`, not by
`ScopeGate.evaluate`: no signal carries the tree yet, so it lands after the copy, as the
cycle refusal does, until the probe reads the base feature (tasks.md T161, decision 17A).

**Absence is not emptiness.** A `null` signal is not a pass. An unreadable *refusing* signal
is `signal_unresolved` naming the signal and the verdict is `unresolved`, because a pass
asserted over data nobody read is exactly what Principle I exists to prevent. The signals
that are recorded rather than refused (the surface body count, the imported file listing,
the configuration names) report `unresolved` in their own field and add a note; they never
fall back to a favourable default.

**The RMS-named folder, and why presence is the v1 rule.** FR-007 refuses a part carrying a
folder named for one of the six groups whose members do not match that group, and it refuses
it *from this probe*, before the copy. At probe time the only reading of a folder is its name
and its members' persist refs: the evidence package that would say which group each member
belongs in is dumped from the copy, which does not exist yet. So the gate refuses on
**presence**, and its message says that v1 can neither verify nor repair the membership,
because `IModelDoc2.EditDelete` is not on the stage-1 allowlist and there is therefore no
dissolve path (owner decision, `research.md` R12 OQ-3). `remodel/folders.py` makes the finer
distinction - a folder holding exactly the right members is a no-op, a subset or a superset
is the same refusal - from the package, where member ids exist; that is the reading the
dry-run planner reports and the one FR-007's "naming the unexpected members" comes from. A
folder not named for one of the six is a derived subfolder: preserved, never dissolved, and
not a scope question at all.

**The code set is closed and shared with the bridge** (`data-model.md` section 4.2). Twelve
tokens, one vocabulary: a token that differed by an underscore would be a refusal that maps
to no Python class in `bridge/remodel_client.py`. Four of them the bridge raises before any
signal is returned (`not_a_part`, `source_dirty`, `external_refs`) or on the copy
(`preexisting_rebuild_errors`), so this gate never emits them even though the rows they are
decided from are in the table; they enter `ScopeReport.refusals` when the host records the
bridge's refusal. `rms_named_folder_wrong_members` is the one token the bridge spells and
this gate decides. `derived_part` is the one **tree** code: neither the gate nor the bridge
raises it yet, and `plan_reorganize` records it in `RemodelPlan.tree_refusals`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast, get_args

from pydantic import BaseModel, ConfigDict

from swreview.checks.rms_types import RmsTypeTable, load_table
from swreview.ir.models import Feature

__all__ = [
    "BRIDGE_ONLY_CODES",
    "DERIVED_PART",
    "GATE_CODES",
    "REFUSAL_CODES",
    "REFUSING_SIGNALS",
    "RMS_NAMED_FOLDER_WRONG_MEMBERS",
    "SIGNAL_UNRESOLVED",
    "TREE_CODES",
    "WHICH_CONFIGS_ALL",
    "WHICH_CONFIGS_THIS",
    "Refusal",
    "RefusalCode",
    "RmsNamedFolder",
    "ScopeGate",
    "ScopeGateResult",
    "ScopeSignals",
    "SignalRule",
    "VaultLocation",
    "derived_part_refusals",
]

RefusalCode = Literal[
    "not_a_part",
    "source_dirty",
    "external_refs",
    "multibody",
    "weldment",
    "sheet_metal",
    "mesh_or_graphics_body",
    "three_d_interconnect",
    "preexisting_rebuild_errors",
    "rms_named_folder_wrong_members",
    "signal_unresolved",
    "derived_part",
]
"""The closed `Refusal` code set of `data-model.md` section 4.2, in the order it lists them."""

REFUSAL_CODES: frozenset[str] = frozenset(get_args(RefusalCode))

BRIDGE_ONLY_CODES: frozenset[str] = frozenset(
    {"not_a_part", "source_dirty", "external_refs", "preexisting_rebuild_errors"}
)
"""The codes the bridge raises and this gate cannot reach from `ScopeSignals` alone: the
first three before any signal is returned, the fourth on the copy after a rollback and a
rebuild, which are writes and can therefore never touch the source (FR-004)."""

DERIVED_PART = "derived_part"
"""Named once, here: the part's body is another part's, brought in by a derived or mirrored
base feature (decision 17A)."""

TREE_CODES: frozenset[str] = frozenset({DERIVED_PART})
"""The codes decided from the package's feature rows rather than from `ScopeSignals`: after
the copy, the way the cycle refusal is, until the probe reads what they are decided from
(tasks.md T161)."""

GATE_CODES: frozenset[str] = REFUSAL_CODES - BRIDGE_ONLY_CODES - TREE_CODES

RMS_NAMED_FOLDER_WRONG_MEMBERS = "rms_named_folder_wrong_members"
"""Named once, here, so `folders.py` and the host cite the token rather than spelling it."""

SIGNAL_UNRESOLVED = "signal_unresolved"

WHICH_CONFIGS_THIS = 1
"""`swInConfigurationOpts_e.swThisConfiguration` (VERIFIED value)."""

WHICH_CONFIGS_ALL = 2
"""`swInConfigurationOpts_e.swAllConfiguration` (VERIFIED value)."""


class RmsNamedFolder(BaseModel):
    """One feature folder as the probe reads it: its name and its members' persist refs.

    The members are persist refs and not ids because the probe runs before any package is
    dumped; nothing here can say which group a member belongs in, which is why the v1
    refusal is on presence (see the module docstring).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    member_persist_refs: tuple[str, ...]


class VaultLocation(BaseModel):
    """An EPDM source's vault path and revision: recorded, never a refusal reason (FR-006)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    revision: str


class ScopeSignals(BaseModel):
    """The rows of `data-model.md` section 4.1, in the table's order.

    Every field is a measurement, not a judgement: `null` means the call could not be read,
    and this type never fills one in. `extra="forbid"` is load-bearing - a row renamed in
    the data model cannot be silently accepted here under its old spelling, and a copy path
    or a document handle cannot be smuggled in beside the measurements.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_type: int | None
    solid_body_count: int | None
    sheet_body_count: int | None
    is_weldment: bool | None
    sheet_metal_folder_present: bool | None
    mesh_body_present: bool | None
    graphics_body_present: bool | None
    is_3d_interconnect: bool | None
    imported_file_names: tuple[str, ...] | None
    configuration_names: tuple[str, ...] | None
    rms_named_folders: tuple[RmsNamedFolder, ...] | None
    external_reference_count: int | None
    save_flag_dirty: bool | None
    read_only: bool | None
    rebuild_error_count: int | None
    vault: VaultLocation | None


class Refusal(BaseModel):
    """One reason this part is not re-modelable, naming the signal it was read from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: RefusalCode
    message: str
    signal: str


class ScopeGateResult(BaseModel):
    """What the gate decided, and everything the run and the report read from it.

    `verdict` is `refused` when any definite refusal fired, `unresolved` when the only
    refusals are unreadable signals, and `ok` otherwise. The three are not collapsed: a
    part refused for being a weldment is a different conversation from a part whose
    weldment flag could not be read.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["ok", "refused", "unresolved"]
    refusals: tuple[Refusal, ...]
    notes: tuple[str, ...]
    surface_coverage: Literal["covered", "uncovered", "unresolved"]
    reorganize_is_no_op: bool | None
    configuration_count: int | None
    which_configs: int | None

    @property
    def ok(self) -> bool:
        """Whether the run may proceed. Only `ok` does; `unresolved` does not."""
        return self.verdict == "ok"

    @property
    def message(self) -> str:
        """Every refusal in one sentence, because a message that names one of two reasons
        sends the engineer back twice (`research.md` R4.1)."""
        return "; ".join(refusal.message for refusal in self.refusals)

    @property
    def coverage(self) -> tuple[str, ...]:
        """The refusals and the notes as report lines: a refusal is a reported coverage
        gap, never a silent skip (Principle VI)."""
        return tuple(
            f"{refusal.code} ({refusal.signal}): {refusal.message}" for refusal in self.refusals
        ) + self.notes


@dataclass(frozen=True)
class SignalRule:
    """One row of the refusal table: which signal, which code, and how it fails.

    `fails` is only ever asked about a signal that was read; the unreadable case is decided
    once, for every rule, by `ScopeGate.evaluate`.
    """

    signal: str
    code: RefusalCode
    describe: str
    """The sentence, formatted with the value that was read."""


def _rms_named_group_folders(
    folders: Sequence[RmsNamedFolder], table: RmsTypeTable
) -> tuple[RmsNamedFolder, ...]:
    """The folders carrying one of the six group names; the rest are derived subfolders."""
    groups = set(table.groups)
    return tuple(folder for folder in folders if folder.name in groups)


class ScopeGate:
    """The pure verdict. `evaluate` is the whole surface; `RULES` is the table it reads."""

    RULES: tuple[SignalRule, ...] = (
        SignalRule(
            signal="solid_body_count",
            code="multibody",
            describe=(
                "solid_body_count is {value}: the geometry gate cannot pair bodies "
                "unambiguously across a change, so a multibody part is refused"
            ),
        ),
        SignalRule(
            signal="is_weldment",
            code="weldment",
            describe=(
                "is_weldment is true: a weldment's cut list and structural members are not "
                "modelled by the six groups"
            ),
        ),
        SignalRule(
            signal="sheet_metal_folder_present",
            code="sheet_metal",
            describe=(
                "sheet_metal_folder_present is true: the six groups do not model bends, "
                "K-factor or a flat pattern"
            ),
        ),
        SignalRule(
            signal="mesh_body_present",
            code="mesh_or_graphics_body",
            describe="mesh_body_present is true: a mesh body has no B-rep, so there is no gate",
        ),
        SignalRule(
            signal="graphics_body_present",
            code="mesh_or_graphics_body",
            describe=(
                "graphics_body_present is true: a graphics body has no B-rep, so there is no gate"
            ),
        ),
        SignalRule(
            signal="is_3d_interconnect",
            code="three_d_interconnect",
            describe=(
                "is_3d_interconnect is true: re-modelling fights the live link to the "
                "external file"
            ),
        ),
        SignalRule(
            signal="rms_named_folders",
            code=RMS_NAMED_FOLDER_WRONG_MEMBERS,
            describe=(
                "this part already carries the group-named folder(s) {value}. This version "
                "can neither verify nor repair their membership before the copy exists, and "
                "it has no dissolve path, so the part is refused: fix the folders by hand, "
                "or wait for the rebuild stage"
            ),
        ),
    )

    REFUSING_SIGNALS: tuple[str, ...] = tuple(dict.fromkeys(rule.signal for rule in RULES))
    """The signals whose failure, or whose unreadability, stops the run."""

    @classmethod
    def evaluate(cls, signals: ScopeSignals) -> ScopeGateResult:
        """Decide this part's scope from the probe's readings and nothing else.

        Every failing signal is reported, in the table's order, so a two-signal part names
        both reasons in one message.
        """
        table = load_table()
        refusals: list[Refusal] = []
        notes: list[str] = []

        for rule in cls.RULES:
            value = getattr(signals, rule.signal)
            if value is None:
                refusals.append(
                    Refusal(
                        code=SIGNAL_UNRESOLVED,
                        message=(
                            f"{rule.signal} could not be read, so the {rule.code} question is "
                            f"unresolved; an unread signal is never a pass"
                        ),
                        signal=rule.signal,
                    )
                )
                continue
            failing = cls._failing_value(rule, value, table)
            if failing is not None:
                refusals.append(
                    Refusal(
                        code=rule.code,
                        message=rule.describe.format(value=failing),
                        signal=rule.signal,
                    )
                )

        surface_coverage, surface_note = _surface_coverage(signals.sheet_body_count)
        no_op, imported_note = _reorganize_no_op(signals.imported_file_names)
        count, which_configs, config_note = _configurations(signals.configuration_names)
        notes.extend(note for note in (surface_note, imported_note, config_note) if note)

        return ScopeGateResult(
            verdict=_verdict(refusals),
            refusals=tuple(refusals),
            notes=tuple(notes),
            surface_coverage=surface_coverage,
            reorganize_is_no_op=no_op,
            configuration_count=count,
            which_configs=which_configs,
        )

    @staticmethod
    def _failing_value(rule: SignalRule, value: object, table: RmsTypeTable) -> str | None:
        """What this rule refuses about `value`, or `None` when it does not refuse it.

        `value` is the row `ScopeSignals` validated, so the two rules that read something
        other than a boolean flag narrow it rather than re-checking its type.
        """
        if rule.signal == "solid_body_count":
            count = cast(int, value)
            return str(count) if count > 1 else None
        if rule.signal == "rms_named_folders":
            named = _rms_named_group_folders(cast("Sequence[RmsNamedFolder]", value), table)
            return ", ".join(folder.name for folder in named) if named else None
        return "" if value is True else None


def _verdict(refusals: Sequence[Refusal]) -> Literal["ok", "refused", "unresolved"]:
    """A definite refusal outranks an unreadable signal; both are still reported."""
    codes = {refusal.code for refusal in refusals}
    if codes - {SIGNAL_UNRESOLVED}:
        return "refused"
    if codes:
        return "unresolved"
    return "ok"


def _surface_coverage(
    sheet_body_count: int | None,
) -> tuple[Literal["covered", "uncovered", "unresolved"], str | None]:
    """Surface bodies are allowed, and what the gate cannot see about them is reported."""
    if sheet_body_count is None:
        return "unresolved", (
            "sheet_body_count could not be read, so whether this part carries surface bodies "
            "the mass-property gate cannot see is unresolved, not covered"
        )
    if sheet_body_count > 0:
        return "uncovered", (
            f"{sheet_body_count} surface body/bodies present: allowed, and the gate's surface "
            "coverage is reported uncovered, never passed"
        )
    return "covered", None


def _reorganize_no_op(
    imported_file_names: tuple[str, ...] | None,
) -> tuple[bool | None, str | None]:
    """An imported dumb solid is allowed; it just has nothing for the reorganize stage to do."""
    if imported_file_names is None:
        return None, (
            "imported_file_names could not be read, so whether the reorganize stage is a no-op "
            "over an imported dumb solid is unresolved"
        )
    if imported_file_names:
        return True, (
            f"imported dumb solid ({', '.join(imported_file_names)}): allowed, and the "
            "reorganize stage is a no-op, because an imported body carries no feature tree to "
            "reorganize"
        )
    return False, None


def _configurations(
    configuration_names: tuple[str, ...] | None,
) -> tuple[int | None, int | None, str | None]:
    """Record the configuration count; it is what drives `which_configs` on an equation add.

    A single-configuration part writes `swThisConfiguration`; more than one writes
    `swAllConfiguration`, because a global added to one configuration only would be invisible
    in the others. An unreadable or empty listing drives nothing: `which_configs` stays
    `None` and every equation add is blocked rather than guessed into one configuration
    (`contracts/bridge-remodel.md`: the single-configuration assumption is checked, never
    assumed).
    """
    if not configuration_names:
        return None, None, (
            "the configuration names could not be read, so which_configs is unknown and no "
            "equation may be added until it is"
        )
    count = len(configuration_names)
    return count, (WHICH_CONFIGS_THIS if count == 1 else WHICH_CONFIGS_ALL), None


def derived_part_refusals(rows: Sequence[Feature], table: RmsTypeTable) -> tuple[Refusal, ...]:
    """One `derived_part` refusal per derived or mirrored base feature in one part's tree.

    Read off every row the dump listed, not only the planned ones, so a base feature the
    walk found under another is still found. Every one is reported, as every failing signal
    is (`research.md` R4.1). The reason is what is true of such a part: its body is another
    part's geometry brought in by that feature, so the features the six groups organize do
    not build it, and a re-model would have to start from the part it came from.
    """
    return tuple(
        Refusal(
            code=DERIVED_PART,
            message=(
                f"{row.id} is a {row.type_name}: this part's body is another part's geometry, "
                "brought in whole by that feature from the part it was derived or mirrored "
                "from, so the features the six groups organize do not build it and a "
                "re-model would have to start from that part; a derived or mirrored part is "
                "refused"
            ),
            signal="features[].type_name",
        )
        for row in rows
        if table.is_derived_base(row)
    )


REFUSING_SIGNALS: tuple[str, ...] = ScopeGate.REFUSING_SIGNALS
"""Module-level alias of the gate's own table, for callers that only need the names."""
