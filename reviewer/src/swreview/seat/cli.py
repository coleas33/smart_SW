"""`swreview seat`: what the engineer runs at the SOLIDWORKS seat, each offline and read-only.

Every command prints its answer and its reason, as JSON with `--json`, and exits 0 when the seat
proved what was asked and 1 when it did not (a FAIL, or a decider's inconclusive).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from swreview.checks.standards.profile import DEFAULT_PATH
from swreview.seat import INCONCLUSIVE, health, transparency, volume_unit

app = typer.Typer(
    no_args_is_help=True,
    help="Checks the engineer runs at the SOLIDWORKS seat: offline, read-only, no key.",
)
Json = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON only.")]
SeatFile = Annotated[
    Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="What the seat saved.")
]


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
        typer.Option("--profile", help=f"The standards profile. Default: {DEFAULT_PATH}."),
    ] = None,
    json_output: Json = False,
) -> None:
    """After starting SOLIDWORKS: PASS or FAIL for every health check a file can prove.

    Reads `addin.log` and the backend logs, the standards profile and the checkout (runbook
    section 6); the pane's own checks are listed as MANUAL. Run it right after a start: a latest
    load more than two hours old fails. Starts nothing but two read-only `git` commands, writes
    nothing, reads no key and prints no path. Exit 1 on any FAIL.
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


def _name(role: str) -> Any:
    default = transparency.DEFAULT_NAMES[role]
    return typer.Option(f"--{role}", help=f"The {role} block's component name. Default: {default}.")


@app.command("transparency")
def transparency_command(
    probe_output: SeatFile,
    transparent: Annotated[str, _name("transparent")] = transparency.DEFAULT_NAMES["transparent"],
    opaque: Annotated[str, _name("opaque")] = transparency.DEFAULT_NAMES["opaque"],
    plain: Annotated[str, _name("plain")] = transparency.DEFAULT_NAMES["plain"],
    json_output: Json = False,
) -> None:
    """Which transparency polarity PROBE-2 showed, from a saved `probe standards` run (006 T102).

    Reads only the PROBE-2 lines of the recipe's three blocks
    (benchmarks/native/probe2-polarity/RECIPE.md). Prints zero_is_opaque or one_is_opaque and the
    one edit, or inconclusive with what did not hold, slot 7 refuted among them. Exit 1 when
    inconclusive.
    """
    names = {"transparent": transparent, "opaque": opaque, "plain": plain}
    decision = transparency.decide(transparency.read_text(probe_output), names)
    if json_output:
        typer.echo(json.dumps(asdict(decision), indent=2))
    else:
        typer.echo(f"verdict: {decision.verdict}")
        typer.echo(f"reason: {decision.reason}")
        for reading in decision.readings:
            line = f"{reading.role} {reading.name}: "
            line += f"HasMaterialPropertyValues={reading.has_override}"
            if reading.slots is not None and len(reading.slots) > transparency.SLOT:
                line += f", slot 7 = {reading.slots[transparency.SLOT]:g}"
            typer.echo(line)
        if decision.next:
            typer.echo(f"next: {decision.next}")
    if decision.verdict == INCONCLUSIVE:
        raise typer.Exit(1)


@app.command("volume-unit")
def volume_unit_command(
    package: Annotated[
        Path,
        typer.Argument(
            exists=True, help="The package folder, its package.json, or one interference record."
        ),
    ],
    expected_mm3: Annotated[
        float,
        typer.Option("--expected-mm3", help="The known overlap in mm3; the recipe's is 1000."),
    ],
    json_output: Json = False,
) -> None:
    """Whether the recorded interference volume is in m3 or mm3, against a known overlap (001 T069).

    Judges the one computed interference of the recipe's two cubes
    (benchmarks/native/interference-volume/RECIPE.md) within 1 per cent, and names the extractor
    change it asks for; inconclusive otherwise. Exit 1 when inconclusive.
    """
    if not expected_mm3 > 0:
        raise typer.BadParameter("must be a volume above zero", param_hint="'--expected-mm3'")
    try:
        rows = volume_unit.interferences(package)
    except (OSError, ValueError) as error:
        first = str(error).splitlines()[0] if str(error) else type(error).__name__
        typer.echo(f"error: neither a package nor an interference record: {first}", err=True)
        raise typer.Exit(1) from error
    judgement = volume_unit.judge(rows, expected_mm3)
    if json_output:
        typer.echo(json.dumps(asdict(judgement), indent=2))
    else:
        typer.echo(f"unit: {judgement.unit}")
        typer.echo(f"reason: {judgement.reason}")
        if judgement.next:
            typer.echo(f"next: {judgement.next}")
    if judgement.unit == INCONCLUSIVE:
        raise typer.Exit(1)
