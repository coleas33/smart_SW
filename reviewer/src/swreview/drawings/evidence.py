"""Which drawing views show which document, and which of them a check may use (feature 011).

`contracts/drawing-source.md` section 1 is normative. `DrawingIndex.for_package` walks the
package's drawing records in document-id order, their sheets by index and their views by id,
and yields one `ViewEvidence` per view that shows a document of the package. A view of a model
outside the package, and the sheet-format pseudo-view, show no document of it and are not
evidence about one.

**Usable** is decided per component, because a view shows one configuration and a part may be
used in two (section 1's last paragraph). A view is usable for a component when, in this order:

1. its drawing is not in detailing mode, where views load no model;
2. its model is loaded;
3. it is not out of date with that model;
4. it shows the configuration the review read for that component.

The first condition that fails is the reason, and a condition that was **not read** fails with
words of its own: an unread flag is never a pass (constitution Principle I). `ViewEvidence`
carries the view-level answer - usable when conditions 1 to 3 hold and it shows a configuration
some instance of the document uses - and `DrawingIndex.why_not_for` gives the per-component
one the binding needs.

**The order is the package's ids, never its arrays'.** The extractor allocates every id in
traversal order, so ordering by id is traversal order, and a package whose arrays were written
in another order indexes identically (`id_order`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from swreview.ir.models import (
    DrawingCandidate,
    DrawingRecord,
    DrawingSheetRecord,
    DrawingView,
    EvidencePackage,
)

__all__ = ["DrawingIndex", "ViewEvidence", "id_order", "view_label"]


def id_order(identifier: str) -> tuple[str, int, str]:
    """The sort key of a package id: its prefix, then its number read as a number.

    `doc:2` sorts before `doc:10`, and `doc:0002` beside `doc:2`; an id whose tail is not a
    number sorts after every numbered one of its prefix, by its spelling.
    """
    prefix, _, tail = identifier.partition(":")
    if tail.isdigit():
        return prefix, int(tail), ""
    return prefix, 2**63, tail


def view_label(view: DrawingView) -> str:
    """What a sentence calls a view: its name, or its package id when the name was not read."""
    return view.name if view.name is not None else view.id


def _quoted(configurations: tuple[str, ...]) -> str:
    """`'Default'`, or `'Default' and 'FICT-VENTA'`."""
    return " and ".join(f"'{name}'" for name in configurations)


def _state_why(record: DrawingRecord, view: DrawingView) -> str | None:
    """Conditions 1 to 3 of section 1: why nothing this view shows can be used, or `None`."""
    drawing = record.document_id
    name = view_label(view)
    if record.is_detailing_mode is None:
        return f"whether drawing {drawing} is in detailing mode was not read"
    if record.is_detailing_mode:
        return f"drawing {drawing} is in detailing mode, so its views load no model"
    if view.is_model_loaded is None:
        return f"whether view {name} of {drawing} has its model loaded was not read"
    if not view.is_model_loaded:
        return f"view {name} of {drawing} shows a model that is not loaded"
    if view.is_model_out_of_date is None:
        return f"whether view {name} is up to date was not read"
    if view.is_model_out_of_date:
        return f"view {name} of {drawing} is out of date with its model"
    return None


@dataclass(frozen=True, eq=False)
class ViewEvidence:
    """One view that shows a document of the package, and whether a check may use it."""

    record: DrawingRecord
    sheet: DrawingSheetRecord
    view: DrawingView
    document_id: str
    """The package document the view shows."""
    state_why: str | None
    """Conditions 1 to 3: why nothing this view shows can be used, whatever the component."""
    usable: bool
    """Usable for at least one instance of the document (every condition holds for it)."""
    why: str | None
    """The first failing reason when not `usable`."""

    @property
    def drawing_id(self) -> str:
        """The drawing document the view is on."""
        return self.record.document_id

    @property
    def configuration(self) -> str | None:
        """The configuration the view shows, `None` when it was not read."""
        return self.view.referenced_configuration

    @property
    def name(self) -> str:
        return view_label(self.view)

    def why_not_in(self, configurations: tuple[str, ...]) -> str | None:
        """Why this view cannot be used for an instance read in one of `configurations`,
        or `None` when it can: conditions 1 to 3, then condition 4."""
        return _why_not_in(self.record, self.view, self.document_id, configurations)


def _why_not_in(
    record: DrawingRecord, view: DrawingView, document_id: str, configurations: tuple[str, ...]
) -> str | None:
    """Section 1's four conditions in order, the first failing one's reason, or `None`."""
    state = _state_why(record, view)
    if state is not None:
        return state
    name = view_label(view)
    shown = view.referenced_configuration
    if shown is None:
        return f"the configuration view {name} shows was not read"
    if not configurations:
        return f"the configuration the review read for {document_id} is not recorded"
    if shown in configurations:
        return None
    return (
        f"view {name} of {record.document_id} shows configuration '{shown}'; the review read "
        f"{_quoted(configurations)}"
    )


@dataclass(frozen=True)
class DrawingIndex:
    """Every view that shows a document of one package, in the fixed order, built once."""

    views: tuple[ViewEvidence, ...]
    """Drawing document id, then sheet index, then view id."""
    root_drawing_id: str | None
    """The design's root document when it is a drawing with a record: a drawing root."""
    candidates: tuple[DrawingCandidate, ...]
    """The package's drawing candidates, by document id."""
    records: Mapping[str, DrawingRecord] = field(repr=False)
    """Every drawing record by its document id."""
    _configurations: Mapping[str, tuple[str, ...]] = field(repr=False)
    """What the review read for each document: its instances' configurations, else its own."""
    _component_configurations: Mapping[str, str] = field(repr=False)

    @classmethod
    def for_package(cls, package: EvidencePackage) -> DrawingIndex:
        """The index of `package`. Never raises on a valid package, and records nothing."""
        documents = {document.document_id: document for document in package.documents}
        instances: dict[str, list[str]] = {}
        for component in sorted(package.components, key=lambda item: id_order(item.id)):
            instances.setdefault(component.document_id, []).append(
                component.referenced_configuration
            )
        configurations: dict[str, tuple[str, ...]] = {}
        for document_id, document in documents.items():
            read = instances.get(document_id)
            if read:
                configurations[document_id] = tuple(dict.fromkeys(read))
            elif document.active_configuration:
                configurations[document_id] = (document.active_configuration,)
            else:
                configurations[document_id] = ()

        views: list[ViewEvidence] = []
        records = sorted(package.drawing_records, key=lambda item: id_order(item.document_id))
        for record in records:
            for sheet in sorted(record.sheets, key=lambda item: item.index):
                for view in sorted(sheet.views, key=lambda item: id_order(item.id)):
                    shown = view.referenced_document_id
                    if shown is None or shown not in documents:
                        continue
                    state = _state_why(record, view)
                    why = _why_not_in(record, view, shown, configurations[shown])
                    views.append(
                        ViewEvidence(
                            record=record,
                            sheet=sheet,
                            view=view,
                            document_id=shown,
                            state_why=state,
                            usable=why is None,
                            why=why,
                        )
                    )

        root = package.design.root_assembly_document_id
        by_record = {record.document_id: record for record in records}
        root_document = documents.get(root)
        return cls(
            views=tuple(views),
            root_drawing_id=(
                root
                if root in by_record and root_document is not None
                and root_document.kind == "drawing"
                else None
            ),
            candidates=tuple(
                sorted(package.drawing_candidates, key=lambda item: id_order(item.document_id))
            ),
            records=by_record,
            _configurations=configurations,
            _component_configurations={
                component.id: component.referenced_configuration
                for component in package.components
            },
        )

    def views_of(self, document_id: str) -> tuple[ViewEvidence, ...]:
        """Every view that shows `document_id`, usable or not, in the fixed order."""
        return tuple(view for view in self.views if view.document_id == document_id)

    def drawings_of(self, document_id: str) -> tuple[str, ...]:
        """The drawings any view of which shows `document_id`, in document-id order."""
        return tuple(dict.fromkeys(view.drawing_id for view in self.views_of(document_id)))

    def candidate_of(self, document_id: str) -> DrawingCandidate | None:
        """The same-name drawing file beside `document_id`, when the extraction recorded one."""
        return next((item for item in self.candidates if item.document_id == document_id), None)

    def configurations_of(self, document_id: str) -> tuple[str, ...]:
        """The configurations the review read for `document_id` (its instances', else its own)."""
        return self._configurations.get(document_id, ())

    def why_not_for(self, view: ViewEvidence, component_id: str | None) -> str | None:
        """Why `view` cannot be used for `component_id`, or `None` when it can.

        A component the package does not hold, or none, is compared with every configuration
        the review read for the view's document - the view-level answer.
        """
        configuration = (
            self._component_configurations.get(component_id) if component_id is not None else None
        )
        if configuration is None:
            return view.why_not_in(self.configurations_of(view.document_id))
        return view.why_not_in((configuration,))
