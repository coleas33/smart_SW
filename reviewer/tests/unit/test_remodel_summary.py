"""The plan summary, in one place: `remodel/summary.py` (T134b).

The per-part row `swreview remodel plan --json` prints is the same row the Remodel tab's
`POST /remodel/plan` answers with, so it is built once, here, and the CLI imports it. This
file pins that there is exactly one builder: the CLI keeps no private copy, and the row it
prints is the row this module produces for the same plan.

The row's **content** is pinned by `test_cli_remodel_plan.py` and by the remodel-plan
goldens, which are unchanged by the move and are not restated here.
"""

from __future__ import annotations

from typing import Any

from swreview import cli
from swreview.checks.rms_types import load_table
from swreview.remodel.plan import plan_reorganize
from swreview.remodel.summary import plan_lines, plan_refusals, plan_summary_row
from tests.support.remodel import dependency_chain_features, remodel_package

TABLE = load_table()
DOCUMENT = "doc:1"


def planned() -> tuple[Any, Any]:
    """One dry-run plan and the document row it was planned from."""
    package = remodel_package(dependency_chain_features(), name="bracket")
    plan = plan_reorganize(package, document_id=DOCUMENT, table=TABLE)
    document = next(row for row in package.documents if row.document_id == DOCUMENT)
    return plan, document


def test_the_row_carries_every_number_the_dry_run_prints() -> None:
    plan, document = planned()

    row = plan_summary_row(plan, document, TABLE)

    assert row["document_id"] == DOCUMENT
    assert row["file_name"] == document.file_name
    assert row["state"] == plan.state
    assert row["reorganizable_fraction"]["of"] == row["content_features"]
    assert row["refusals"] == plan_refusals(plan)
    assert set(row) >= {
        "move_count",
        "changes",
        "renames",
        "pins",
        "non_contiguous",
        "rebuild",
        "rebuild_by_reason",
        "folders",
        "scope",
        "coverage",
    }


def test_the_lines_print_the_fraction_with_its_denominator() -> None:
    plan, document = planned()

    lines = plan_lines(plan_summary_row(plan, document, TABLE))

    fraction = plan_summary_row(plan, document, TABLE)["reorganizable_fraction"]
    assert lines[0].startswith(f"{DOCUMENT} {document.file_name}: ")
    assert f"{fraction['reaching']} of {fraction['of']} content features" in lines[1]


def test_the_cli_keeps_no_second_copy_of_the_builder() -> None:
    """One builder, imported by both callers: a second copy is a second answer to "what
    does this part's row say", and the goldens would only pin one of them."""
    assert cli.plan_summary_row is plan_summary_row
    assert cli.plan_lines is plan_lines
    for private in ("_remodel_row", "_remodel_refusals", "_remodel_lines"):
        assert not hasattr(cli, private), f"swreview.cli still defines {private}"
