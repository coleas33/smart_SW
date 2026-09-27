"""A fictional review shaped like the 2026-09-26 sitting, for lane S's part-roles tests (013).

An assembly (`doc:0001`) and a custom plate (`doc:0002`) that follow the fictional part-number
convention, and a pin no rule decides (`doc:0003`, two instances): with a version 3 profile
whose `part_number.pattern` is the convention, the review is in the `convention_only` state and
the pin is unclear, so the part-roles question lists it (`contracts/part-roles.md` sections 1, 2
and 8). The profile is written from fictional profile A with its version set to 3 and any
version 4 section dropped, so the state does not move when lane P raises profile A to version 4
(T014). Every name is fictional.

T012's sitting-shaped fixture is lane P's and was not on this branch when these tests were
written; the integrator may point them at it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

from swreview.agent.package_brief import package_brief
from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
from swreview.agent.runner import ReviewRun, start_review
from swreview.tools.registry import PART_ROLES_ATTRIBUTE
from tests.support.mechanical import PackageBuilder

PROFILE_A = Path(__file__).resolve().parents[1] / "fixtures" / "standards" / "profile-a.yaml"

CONVENTION = "FICT-####.SLD???"
ROOT_STEM = "FICT-7000"
PLATE_STEM = "FICT-7001"
PIN_STEM = "FICT-KALO-PIN"

ROOT_ID = "doc:0001"
PLATE_ID = "doc:0002"
PIN_ID = "doc:0003"


def write_profile(folder: Path, *, pattern: str = CONVENTION) -> Path:
    """A version 3 profile with `pattern` as its part-number convention."""
    document = yaml.safe_load(PROFILE_A.read_text(encoding="utf-8"))
    document["version"] = 3
    document.pop("part_roles", None)
    document["part_number"]["pattern"] = pattern
    path = folder / "profile-v3.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def write_package(folder: Path, *, pin: bool = True) -> Path:
    """The assembly, the plate and (unless `pin` is false) the unclear pin, written to
    `folder`."""
    builder = PackageBuilder(design_stem=ROOT_STEM)
    plate = builder.document(PLATE_STEM, "part")
    builder.component(plate)
    if pin:
        pin_document = builder.document(PIN_STEM, "part")
        builder.component(pin_document)
        builder.component(pin_document)
    builder.build().write(folder)
    return folder


def review_brief(run: ReviewRun) -> str:
    """The package brief a review's opening message carries: its package, with its roles."""
    return package_brief(run.context.ir, roles=getattr(run.context, PART_ROLES_ATTRIBUTE))


def roles_review(
    tmp_path: Path,
    *,
    turns: Sequence[ScriptedTurn] = (ScriptedTurn(text="done"),),
    profile: Path | None | str = "convention",
    pin: bool = True,
    events: list[tuple[str, dict[str, Any]]] | None = None,
    **options: Any,
) -> ReviewRun:
    """`start_review` over the fictional package; `profile="convention"` writes the version 3
    profile, `None` reviews with none, and a path is used as given."""
    folder = write_package(tmp_path / "run-0001", pin=pin)
    if profile == "convention":
        profile = write_profile(tmp_path)
    callbacks: list[Callable[[Any], None]] = []
    if events is not None:
        callbacks.append(lambda event: events.append((event.type, dict(event.body))))
    return start_review(
        folder,
        folder,
        provider=FakeProvider(script=list(turns), model="fake-scripted"),
        standards_profile=profile,
        callbacks=callbacks,
        **options,
    )
