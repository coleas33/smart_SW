"""The one document-scope check: the data card (T046).

`standards.document.data_card_complete` is the only check of the sixteen that grades all
three document kinds, and the only one whose subjects are not IR rows: its subjects are the
profile's data-card property **names**, each carrying whether it was absent from the card or
present and blank, because the two have different remedies (difference m).

Four rules of `contracts/rules.md` shape it:

- **which documents it applies to.** Every part, assembly and drawing document whose file
  name matches `part_number.pattern`. The name is the one in `Document.path`, extension
  included; it is never matched against a window title, because SOLIDWORKS can be configured
  to hide extensions in titles and the macro's version of this check then switches itself
  off entirely (difference l, limitation L9). `CheckedDocument.matches_part_number` is where
  that match is made, once per document;
- **one finding per document**, whatever the number of absent or blank fields (difference n:
  the macro counts one defect per field and reports four for a blank card);
- **an empty setting is a skip, not a pass.** An empty `part_number.pattern` or an empty
  `data_card.properties` leaves nothing to test, so the check is skipped naming the setting
  and that count travels on the headline (FR-032). It is what keeps an unconfigured profile
  from silently passing a document;
- **`library.skip_prefixes` applies to part documents only.** An assembly under the same
  prefix is graded, as the macro graded it.

The property set read is the **configuration-independent** one, as the macro reads it. A
field that carries a value only in a configuration-specific property is reported absent, and
the observed text names that scope so the engineer can see why (spec Edge Cases).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from swreview.checks.standards.library import PrefixMatcher
from swreview.checks.standards.profile import StandardsProfile
from swreview.checks.standards.registry import RULES, bind, rules_in
from swreview.checks.standards.results import (
    RuleResult,
    Subject,
    document_evidence_unresolved,
    finding,
    passed,
    properties_gap,
    properties_gap_note,
    property_subject,
    skipped,
    unresolved,
)
from swreview.checks.standards.traversal import CheckedDocument
from swreview.ir.models import EvidencePackage

__all__ = [
    "DataCardFieldResult",
    "DataCardState",
    "data_card_complete",
    "evaluate_document",
    "read_card",
]

SCOPE = "document"
KINDS = ("part", "assembly", "drawing")

DATA_CARD_COMPLETE = "standards.document.data_card_complete"

PROPERTY_SCOPE = "the document's configuration-independent custom properties"
"""Named in the observed text: a value that lives only in a configuration-specific property
is reported absent, and a reader has to be told which set was read (spec Edge Cases)."""

DataCardState = Literal["present", "blank", "absent"]


@dataclass(frozen=True)
class DataCardFieldResult:
    """What one profile property resolved to on one document (data-model section 3).

    `absent` is a property the card does not carry at all and `blank` one it carries with an
    empty or whitespace-only value; the remedy differs, so the finding says which it was.
    `resolved_value` is the resolved reading - what a drawing or a BOM would show - and is
    `None` exactly when the property is absent.
    """

    property: str
    state: DataCardState
    resolved_value: str | None


def read_card(
    properties: Mapping[str, str], wanted: Sequence[str]
) -> tuple[DataCardFieldResult, ...]:
    """Each wanted property as it stands on this card, in profile order.

    Lookup is case-insensitive because SOLIDWORKS custom-property names are: the extractor
    reads them into an `OrdinalIgnoreCase` map, and a card written `PART NO` answers a
    profile that asks for `Part No`.
    """
    folded = {name.casefold(): value for name, value in properties.items()}
    results: list[DataCardFieldResult] = []
    for name in wanted:
        if name.casefold() not in folded:
            results.append(DataCardFieldResult(name, "absent", None))
            continue
        value = folded[name.casefold()]
        state: DataCardState = "blank" if not value.strip() else "present"
        results.append(DataCardFieldResult(name, state, value))
    return tuple(results)


def evaluate_document(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> list[RuleResult]:
    """The document-scope check over one graded document, whatever its kind."""
    if document.kind not in KINDS:
        raise ValueError(
            f"{document.document_id} has no recorded kind, so it is unresolved coverage for "
            "every check rather than a document to grade"
        )
    results: list[RuleResult] = []
    for rule in rules_in(SCOPE):
        results.extend(rule.fn(document, package, profile))
    return results


@bind(DATA_CARD_COMPLETE)
def data_card_complete(
    document: CheckedDocument, package: EvidencePackage, profile: StandardsProfile
) -> list[RuleResult]:
    """The data card is complete on every document that follows the convention (FR-022)."""
    rule = RULES[DATA_CARD_COMPLETE]
    document_id = document.document_id
    name = document.file_name or document_id

    missing = document_evidence_unresolved(document)
    if missing is not None:
        return [unresolved(rule, document_id, missing)]

    if not profile.part_number.pattern:
        return [
            skipped(
                rule,
                document_id,
                "the profile's part_number.pattern is empty, so there is no part-number "
                "convention to decide which documents carry a data card",
            )
        ]
    if not profile.data_card.properties:
        return [
            skipped(
                rule,
                document_id,
                "the profile's data_card.properties is empty, so there is no data-card field "
                "to test",
            )
        ]

    exempt = _library_skip(document, profile)
    if exempt is not None:
        return [skipped(rule, document_id, exempt)]

    if not document.matches_part_number:
        return [
            skipped(
                rule,
                document_id,
                f"the file name {_name_in_path(document) or name} does not follow the "
                "profile's part-number convention (part_number.pattern), so it carries no "
                "data card this check can test",
            )
        ]

    # The gap that says the PROPERTIES were not read, and not any `document`-kind gap: the
    # same kind carries four mass-property facts, and a surface-only part or one whose mass
    # was deliberately overridden carries one of them while its data card was read perfectly
    # well (`results.MASS_PROPERTY_GAP_MARKERS`).
    if properties_gap(package, document_id) is not None:
        return [
            unresolved(
                rule,
                document_id,
                f"the custom properties of {name} were not read, so the data card can be "
                "shown neither complete nor incomplete; "
                + properties_gap_note(package, document_id),
            )
        ]

    row = next(item for item in package.documents if item.document_id == document_id)
    card = read_card(row.custom_properties, profile.data_card.properties)
    offenders = [field for field in card if field.state != "present"]
    if not offenders:
        return [passed(rule, document_id)]

    subjects: list[Subject] = [
        property_subject(field.property, document) for field in offenders
    ]
    return [
        finding(
            rule,
            document_id,
            subjects,
            observed=(
                f"the data card of {name} is not complete, read from {PROPERTY_SCOPE}: "
                + "; ".join(_says(field) for field in offenders)
            ),
            recommended_action=(
                "Fill the data-card fields the release checklist requires, in the document's "
                "configuration-independent custom properties."
            ),
        )
    ]


def _says(field: DataCardFieldResult) -> str:
    """One offending property, saying which of the two states it was in."""
    if field.state == "absent":
        return f"{field.property!r} is absent from the card"
    return f"{field.property!r} is present and blank (its resolved value is whitespace only)"


def _library_skip(document: CheckedDocument, profile: StandardsProfile) -> str | None:
    """Why a **part** under a library skip prefix carries no data card to test.

    An assembly or a drawing under the same prefix is graded: `library.skip_prefixes`
    applies to part documents only (`contracts/rules.md`, library prefix effects).
    """
    if document.kind != "part":
        return None
    matched = PrefixMatcher.from_profile(profile).match(document.path or "").all_matches[
        "skip_prefixes"
    ]
    if not matched:
        return None
    return "the part's path matches library.skip_prefixes " + ", ".join(
        repr(entry) for entry in matched
    )


def _name_in_path(document: CheckedDocument) -> str | None:
    """The file name the path ends in - what the pattern was matched against."""
    if document.path is None:
        return None
    return document.path.replace("\\", "/").rsplit("/", 1)[-1]
