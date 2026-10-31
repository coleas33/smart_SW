"""`swreview seat`: what the engineer runs at the SOLIDWORKS seat, each offline and read-only.

Every command prints its answer and its reason, as JSON with `--json`, and exits 0 when the seat
proved what was asked and 1 when it did not (a FAIL, or a decider's inconclusive).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from swreview.seat import health

app = typer.Typer(
    no_args_is_help=True,
    help="Checks the engineer runs at the SOLIDWORKS seat: offline, read-only, no key.",
)
Json = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON only.")]


@app.command("health")
def health_command(
    logs: Annotated[
        Path | None,
        typer.Option(
            "--logs", help="The add-in's log folder. Default: %LOCALAPPDATA%\\SwReview\\logs."
        ),
    ] = None,
    repo: Annotated[
        Path | None,
        typer.Option("--repo", help="The checkout. Default: the one this command runs from."),
    ] = None,
    profile: Annotated[
        Path | None,
        typer.Option(
            "--profile",
            help="The standards profile. Default: %LOCALAPPDATA%\\SwReview\\standards.yaml.",
        ),
    ] = None,
    json_output: Json = False,
) -> None:
    """After starting SOLIDWORKS: PASS or FAIL for every health check a file can prove.

    Reads `addin.log` and the backend logs, the standards profile and the checkout (runbook
    section 6); the pane's own checks are listed as MANUAL. Starts nothing but two read-only `git`
    commands, reads no key and prints no path. Exit 1 on any FAIL.
    """
    checks = health.run(
        logs or health.default_logs(),
        repo or health.DEFAULT_REPO,
        profile or health.default_profile(),
    )
    failures = sum(check.status == "FAIL" for check in checks)
    if json_output:
        report = {
            "checks": [asdict(check) for check in checks],
            "failed": failures,
            "manual": list(health.MANUAL),
        }
        typer.echo(json.dumps(report, indent=2))
    else:
        for check in checks:
            typer.echo(f"{check.status} {check.check}: {check.reason}")
        for item in health.MANUAL:
            typer.echo(f"MANUAL {item}")
        typer.echo(
            f"health: {failures} of {len(checks)} checks failed; the pane's checks above are "
            "MANUAL, for the eye"
        )
    if failures:
        raise typer.Exit(1)
