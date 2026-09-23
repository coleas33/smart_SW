"""The documents a component tree reaches, and what was read of them (feature 010).

The mass checks and the hygiene checks both walk the same set: the root document and every
document a component instantiates, each once, in document id order. One walk, so the two
families cannot disagree about which documents a review covered.
"""

from __future__ import annotations

from swreview.ir.models import ComponentInstance, Document, EvidencePackage

__all__ = ["DocumentTree"]


class DocumentTree:
    """The documents the component tree reaches, their instances, and which were read."""

    def __init__(self, package: EvidencePackage) -> None:
        self.package = package
        self.documents = {item.document_id: item for item in package.documents}
        self.not_opened = {
            gap.entity_id
            for gap in package.gaps
            if gap.entity_kind == "document" and gap.kind == "not_extracted"
        }
        """Documents the dump says it never opened: nothing was read of them."""
        self.instances: dict[str, list[ComponentInstance]] = {}
        for component in sorted(package.components, key=lambda item: item.id):
            self.instances.setdefault(component.document_id, []).append(component)
        self.root_id = package.design.root_assembly_document_id
        reached = {self.root_id, *self.instances}
        self.reached = [self.documents[key] for key in sorted(reached) if key in self.documents]

    def read(self, component: ComponentInstance) -> bool:
        """The instance was read: resolved, and its document opened."""
        return (
            component.suppression == "resolved"
            and component.document_id not in self.not_opened
        )

    def opened(self, document: Document) -> bool:
        """The document was opened: not flagged unread, and the root or some instance read."""
        if document.document_id in self.not_opened:
            return False
        if document.document_id == self.root_id:
            return True
        return any(self.read(item) for item in self.instances.get(document.document_id, ()))

    def component_ids(self, document: Document) -> tuple[str, ...]:
        return tuple(item.id for item in self.instances.get(document.document_id, ()))

    def children(self, document: Document) -> list[ComponentInstance]:
        """The direct children of the document's first instance (or of the root)."""
        if document.document_id == self.root_id:
            parent = None
        else:
            owners = self.instances.get(document.document_id)
            if not owners:
                return []
            parent = owners[0].id
        return [item for item in self.package.components if item.parent_id == parent]
