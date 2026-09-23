"""Generate the two synthetic packages feature 010's acceptance tests read (T003).

Run from `reviewer/` and commit what it writes:

    uv run python tests/fixtures/mechanical/generate_fixtures.py

`tests/unit/test_support_mechanical.py` re-runs `render_all()` and compares every byte with
the tree, so a fixture is changed here, regenerated and committed - never edited by hand.

**Nothing here comes from a recorded package.** Both fixtures are built from
`tests/support/mechanical.py` and fictional strings; what they reproduce are the *counts*
and the *geometry cases* research R3 verified on the recorded runs, and the numbers the
contracts pin (`contracts/fixtures.md` section 2, `joint-map.md` section 9, `fasteners.md`
section 6, `tool-access.md` section 5, `mass-material.md` section 5, `hygiene.md` section 5).
No name, path or property value of either recorded package is in this file or in what it
writes; `test_mechanical_fixtures_are_fictional.py` holds the output to that.

## big-assembly (shaped like 830-02342)

26 documents (23 parts, 3 assemblies), 89 components (86 resolved, 2 lightweight, 1
suppressed), 27 hole rows with 132 instances, 68 screws over 9 vendor-named documents, 2 pins
with no face, 113 interference groups. The hole ids are the recorded ones, so the contracts'
sentences read against this package; the component ids research names are pinned too
(`cmp:0004` the clevis, `cmp:0007`, `cmp:0008`, `cmp:0016`, `cmp:0017`, `cmp:0018`,
`cmp:0024`, `cmp:0027` the screws the engagement table names). Each region below sits far
from every other, so the only pairs the joint gates see are the ones designed here.

- **A, z 200**: `hol:0016` M2x0.4 tapped x16 under `hol:0023` countersink x16. Sixteen screw
  joints; `cmp:0017` engages 2.205 mm of a blind 6 mm thread.
- **B1, z 51**: `hol:0014` M3 tapped x15 under `hol:0019` countersink x15. Fifteen screw
  joints; `cmp:0027` engages 5.133 mm; `hol:0019`'s instances are numbered one place round, so
  the first instances are not the pair.
- **B2, z -96.5**: `hol:0015` M3 tapped x4 under `hol:0020` countersink x4. Four screw joints;
  `cmp:0024` engages 5.883 mm.
- **The A-B stack**: `hol:0014#1` is 1.576 mm beside `hol:0023#1` and `hol:0015#1` 3.950 mm
  beside `hol:0019#1`, 149.0 and 147.5 mm away along the axis: overlapping axes that are no
  joint and no candidate.
- **C, x 300**: `hol:0017` and `hol:0018` on the clevis `cmp:0004`, `hol:0027` on the dowel
  plate, `hol:0024` M8 counterbore x4 over `hol:0012` M8 tapped x4. The 0.000 and 0.750 mm
  dowel joints, the `assigned_elsewhere` and `overlap_near` candidates, four screw joints, the
  M8 head (a 13.0 mm face) in the 14.0 mm counterbore, and the clevis leg over `hol:0024#1`'s
  head.
- **D, y 600, along x**: `hol:0010` M8 counterbore x3 over `hol:0004` M8 tapped x3. Three
  screw joints whose first instances are 25.0 mm apart and at 90 degrees to `hol:0024`;
  `cmp:0016` engages 14.375 mm of a 16 mm thread.
- **E, x 900**: `hol:0011` M10 counterbore x3 over `hol:0006` M10x1.5 tapped x3. Three screw
  joints; `cmp:0018` (an 8.5 mm face) engages 10.225 mm of a 12 mm thread.
- **F, x 1200, at 30 degrees**: `hol:0013` M5x0.8 tapped, oblique; `cmp:0007`, named M4-0.7,
  in the M5 thread through a 4.5 mm plain bore of the bracket.
- **G, x 1500**: `hol:0021` M3 through-tapped in a 1.725 mm sheet; `cmp:0008`, an M3x4,
  engages 1.394 mm.
- **H, x 1800**: `hol:0025` M8 counterbore of 12.0 mm; a 6.75 mm screw face in `hol:0025#2`,
  the unclassified joint, whose head cannot seat.
- **I, x 2100**: `hol:0022` M5x0.8 tapped and `hol:0005` M4 tapped x4; the second M4 screw on
  an M5 thread, placed by its origin only.
- **J, x 2400**: `hol:0003` M5 clearance x8, `hol:0008` x9, `hol:0002` x4, `hol:0001` x4;
  seven screws and the screw named M5 whose 3.3 mm shank lies below the plate, on clearance
  axes whose tapped part has no extracted hole.
- **K, x 3000 onward**: eleven screws on no extracted axis.

`hol:0007` and `hol:0009` have no cylinder face. Thirteen free faces sit on four parts that
have holes of their own and three on two parts that have none. The masses give densities of
2700 (aluminium), 7850 (steel) and 1000 kg/m3 (steel named, the no-material default), a
2.000 kg sub-assembly whose three children were never opened, and one surface-only part. The
hygiene cases are one part number that is not its file name, two documents sharing a summary
and one model without a revision, in profile A's fictional property names.

## small-assembly (shaped like 810-11249)

3 documents, 4 components, 4 hole rows with 16 instances on one plate, a 3.0 mm pin face in
a 3.0 mm hole at 0.000 mm overlapping it by 8.475 mm, two zero-volume interference rows
between that pin and the plate, and an assembly weighing its plate plus two pins.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURE_DIR.parents[2]))

from tests.support.mechanical import (  # noqa: E402
    HYGIENE_PROPERTIES,
    Built,
    Face,
    Instance,
    PackageBuilder,
    box_mesh,
    cylinder_mesh,
    transform,
)

Z = (0.0, 0.0, 1.0)
X = (1.0, 0.0, 0.0)
TILT = (math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0)))

PART_NUMBER, SUMMARY, REVISION = HYGIENE_PROPERTIES


def house(
    stem: str, summary: str, *, part_number: str | None = None, revision: str | None = "A"
) -> dict[str, str]:
    """The three house properties a document carries, in profile A's fictional names."""
    properties = {PART_NUMBER: part_number or stem, SUMMARY: summary}
    if revision is not None:
        properties[REVISION] = revision
    return properties


def at(
    point: tuple[float, float],
    *faces: Face,
    direction: tuple[float, float, float] = Z,
    z: float = 0.0,
) -> Instance:
    return Instance(origin_mm=(point[0], point[1], z), direction=direction, faces=faces)


# --- the big assembly --------------------------------------------------------------------

B1_ENTRY, A_ENTRY, B2_ENTRY = 51.0, 200.0, -96.5
"""Tapped entries of the stacked regions: A sits 149.0 mm above B1's tapped face and B2's
tapped face stops 147.5 mm below B1's countersink face."""

A_POINTS = [(8.0 * i, 8.0 * j) for j in range(4) for i in range(4)]
B1_POINTS = [(1.576 + 10.0 * i, 10.0 * j) for j in range(3) for i in range(5)]
B2_POINTS = [(15.526 + 12.0 * i, 0.0) for i in range(4)]
C_BORES = [(307.756, 40.0 * k) for k in range(4)]
D_POINTS = [(600.0, 0.0), (600.0, 25.0), (600.0, 50.0)]
E_POINTS = [(900.0, 40.0 * k) for k in range(3)]
J_POINTS = [(2400.0 + 15.0 * k, 0.0) for k in range(8)]


def rotated(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The same positions numbered one place round: instance 1 is the second position."""
    return points[1:] + points[:1]


def build_big_assembly() -> Built:
    builder = PackageBuilder(
        design_stem="FICT-KALOMIR-0000", root_properties=house("FICT-KALOMIR-0000", "KALO MIR")
    )
    root = builder.root_id

    def part(
        stem: str,
        summary: str,
        material: str | None,
        density: float | None,
        volume: float | None,
        **house_options: object,
    ) -> str:
        mass = None if density is None or volume is None else round(volume * 1e-9 * density, 9)
        return builder.document(
            stem,
            "part",
            material=material,
            mass_kg=mass,
            volume_mm3=volume,
            properties=house(stem, summary, **house_options),  # type: ignore[arg-type]
        )

    base = part("FICT-BRUNKALO-1001", "BRUN KALO", "Alloy Steel", 7850.0, 500_000.0)
    cover = part(
        "FICT-VENTAMIR-1002",
        "VENTA MIR",
        "6061-T6",
        2700.0,
        120_000.0,
        part_number="FICT-VENTAMIR-1092",
    )
    bracket = part("FICT-DAVORUSK-1003", "DAVO RUSK", "Alloy Steel", 7850.0, 300_000.0)
    clevis = part(
        "FICT-PELINSORN-1004", "PELIN SORN", "Alloy Steel", 7850.0, 40_000.0, revision=None
    )
    dowel_plate = part("FICT-QUILLHASK-1005", "QUILL HASK", "6061-T6", 2700.0, 60_000.0)
    block = part("FICT-FENNARVO-1006", "FENN ARVO", "Alloy Steel", 1000.0, 80_000.0)
    sheet = part("FICT-TULMZEPH-1007", "VENTA LORI", "Alloy Steel", 7850.0, 20_000.0)
    rail = part("FICT-OMBRANIXA-1008", "VENTA LORI", "6061-T6", 2700.0, 250_000.0)
    hood = part("FICT-KALOVENTA-1009", "KALO VENTA", "6061-T6", 2700.0, 50_000.0)
    skin = part("FICT-LORITESSA-1010", "LORI TESSA", None, None, None)
    unread = [
        builder.document(stem, "part", opened=False)
        for stem in ("FICT-OKTABRUN-1011", "FICT-OKTAPELIN-1012", "FICT-OKTADAVO-1013")
    ]
    sub_unread = builder.document(
        "FICT-OKTAVEN-0100",
        "assembly",
        mass_kg=2.0,
        volume_mm3=491_642.0,
        properties=house("FICT-OKTAVEN-0100", "OKTA VEN"),
    )
    sub_enclosure = builder.document(
        "FICT-TESSALORI-0200", "assembly", properties=house("FICT-TESSALORI-0200", "TESSA LORI")
    )
    pin_document = builder.document(
        "FICT-PIN-3X12-0301",
        "part",
        material="Alloy Steel",
        mass_kg=round(math.pi / 4 * 9.0 * 12.0 * 1e-9 * 7850.0, 9),
        volume_mm3=round(math.pi / 4 * 9.0 * 12.0, 6),
        properties=house("FICT-PIN-3X12-0301", "PIN KALO 0301"),
    )

    screw_documents = {}
    for serial, (head, thread, length, parses, configurations) in enumerate(
        (
            ("SHC", "M8-1.25", 16.0, True, ("Default",)),
            ("SHC", "M10-1.5", 12.0, True, ("Default",)),
            ("SHC", "M4-0.7", 12.0, True, ("Default",)),
            ("SHC", "M3-0.5", 4.0, False, ("Default", "KALO")),
            ("SHC", "M5-0.8", 16.0, False, ("Default",)),
            ("SHC", "M5-0.8", 20.0, False, ("Default",)),
            ("FHT", "M3-0.5", 10.0, True, ("Default", "KALO")),
            ("FHT", "M2-0.4", 6.0, True, ("Default", "KALO")),
            ("BHT", "M5-0.8", 10.0, False, ("Default",)),
        ),
        start=1,
    ):
        stem = f"{head}_{thread}X{length:g}_FICT-{serial:04d}"
        screw_documents[serial] = builder.screw_document(
            head,
            thread,
            length,
            serial=serial,  # type: ignore[arg-type]
            description=None
            if parses
            else f"FICT SCREW {'KALO MIR TESSA BRUN'.split()[serial % 4]}",
            configurations=configurations,
            properties=house(stem, f"SCREW KALO {serial:04d}"),
        )
    m8, m10, m4, m3_short, m5, m5_named, fht_m3, fht_m2, bht_m5 = (
        screw_documents[serial] for serial in range(1, 10)
    )

    # Components: parts and assemblies at their pinned ids; screws follow.
    def put(document: str, component_id: str, **options: object) -> str:
        return builder.component(document, component_id=component_id, **options)  # type: ignore[arg-type]

    put(base, "cmp:0001")
    put(cover, "cmp:0002")
    put(bracket, "cmp:0003")
    put(clevis, "cmp:0004")
    put(dowel_plate, "cmp:0005")
    put(block, "cmp:0006")
    put(sheet, "cmp:0009")
    put(sheet, "cmp:0010")
    put(rail, "cmp:0011")
    put(sub_unread, "cmp:0012")
    put(unread[0], "cmp:0013", parent_id="cmp:0012", suppression="lightweight")
    put(unread[1], "cmp:0014", parent_id="cmp:0012", suppression="lightweight")
    put(unread[2], "cmp:0015", parent_id="cmp:0012", suppression="suppressed")
    put(sub_enclosure, "cmp:0019")
    put(hood, "cmp:0020", parent_id="cmp:0019")
    put(hood, "cmp:0021", parent_id="cmp:0019")
    put(skin, "cmp:0022", parent_id="cmp:0019")
    put(pin_document, "cmp:0023", placement=transform((300.0, 0.0, 6.0)))
    put(pin_document, "cmp:0025", placement=transform((340.0, 0.0, 0.0)))
    put(hood, "cmp:0026", parent_id="cmp:0019")
    put(skin, "cmp:0028", parent_id="cmp:0019")

    # --- hole rows, in id order ------------------------------------------------------
    hole = builder.hole
    hole(
        "cmp:0011",
        hole_type="clearance",
        size="M8",
        end_condition="through",  # hol:0001
        instances=[at((2400.0 + 20.0 * k, 120.0), Face(9.0, 0.0, 6.0)) for k in range(4)],
    )
    hole(
        "cmp:0011",
        hole_type="counterbore",
        size="M6",
        end_condition="through",  # hol:0002
        instances=[
            at((2400.0 + 15.0 * k, 80.0), Face(6.6, 0.0, 1.5), Face(11.0, 1.5, 6.0))
            for k in range(4)
        ],
    )
    hole(
        "cmp:0011",
        hole_type="clearance",
        size="M5",
        end_condition="through",  # hol:0003
        instances=[at(point, Face(5.5, 0.0, 6.0)) for point in J_POINTS],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M8x1.25",
        thread="M8x1.25",  # hol:0004
        thread_depth_mm=16.0,
        hole_depth_mm=20.0,
        end_condition="blind",
        instances=[Instance((0.0, y, z), X, (Face(6.8, -20.0, 0.0),)) for y, z in D_POINTS],
    )
    hole(
        "cmp:0006",
        hole_type="tapped",
        size="M4x0.7",
        thread="M4x0.7",  # hol:0005
        thread_depth_mm=8.0,
        hole_depth_mm=10.0,
        end_condition="blind",
        instances=[at((2100.0 + 20.0 * k, 60.0), Face(3.3, -10.0, 0.0)) for k in range(4)],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M10x1.5",
        thread="M10x1.5",  # hol:0006
        thread_depth_mm=12.0,
        hole_depth_mm=16.0,
        end_condition="blind",
        instances=[at(point, Face(8.5, -16.0, 0.0)) for point in E_POINTS],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M6x1.0",
        thread="M6x1.0",  # hol:0007
        hole_depth_mm=12.0,
        end_condition="blind",
        instances=[],
        faceless_axis=at((1000.0, -300.0), Face(5.0, -12.0, 0.0)),
    )
    hole(
        "cmp:0011",
        hole_type="clearance",
        size="M4",
        end_condition="through",  # hol:0008
        instances=[at((2400.0 + 15.0 * k, 40.0), Face(4.5, 0.0, 6.0)) for k in range(9)],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M6x1.0",
        thread="M6x1.0",  # hol:0009
        hole_depth_mm=12.0,
        end_condition="blind",
        instances=[],
        faceless_axis=at((1030.0, -300.0), Face(5.0, -12.0, 0.0)),
    )
    hole(
        "cmp:0003",
        hole_type="counterbore",
        size="M8",
        end_condition="through",  # hol:0010
        instances=[
            Instance((0.0, y, z), X, (Face(9.0, 0.0, 1.625), Face(14.0, 1.625, 10.0)))
            for y, z in (D_POINTS[1], D_POINTS[0], D_POINTS[2])
        ],
    )
    hole(
        "cmp:0003",
        hole_type="counterbore",
        size="M10",
        end_condition="through",  # hol:0011
        instances=[
            at(point, Face(11.0, 0.0, 1.775), Face(17.5, 1.775, 12.0)) for point in E_POINTS
        ],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M8x1.25",
        thread="M8x1.25",  # hol:0012
        thread_depth_mm=16.0,
        hole_depth_mm=20.0,
        end_condition="blind",
        instances=[at(point, Face(6.8, -36.0, -16.0)) for point in C_BORES],
    )
    hole(
        "cmp:0006",
        hole_type="tapped",
        size="M5x0.8",
        thread="M5x0.8",  # hol:0013
        thread_depth_mm=10.0,
        hole_depth_mm=12.0,
        end_condition="blind",
        instances=[at((1200.0, 0.0), Face(4.2, -12.0, 0.0), direction=TILT)],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",  # hol:0014
        thread_depth_mm=6.0,
        hole_depth_mm=8.0,
        end_condition="blind",
        instances=[at(point, Face(2.5, B1_ENTRY - 8.0, B1_ENTRY)) for point in B1_POINTS],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",  # hol:0015
        thread_depth_mm=6.0,
        hole_depth_mm=8.0,
        end_condition="blind",
        instances=[at(point, Face(2.5, B2_ENTRY - 8.0, B2_ENTRY)) for point in B2_POINTS],
    )
    hole(
        "cmp:0001",
        hole_type="tapped",
        size="M2x0.4",
        thread="M2x0.4",  # hol:0016
        thread_depth_mm=6.0,
        hole_depth_mm=8.0,
        end_condition="blind",
        instances=[at(point, Face(1.6, A_ENTRY - 8.0, A_ENTRY)) for point in A_POINTS],
    )
    hole(
        "cmp:0004",
        hole_type="clearance",
        size="Ø3.0",
        end_condition="through",  # hol:0017
        instances=[at((300.0, 0.0), Face(3.0, 6.0, 12.0))],
    )
    hole(
        "cmp:0004",
        hole_type="clearance",
        size="Ø3.0",
        end_condition="through",  # hol:0018
        instances=[
            at((340.75, 0.0), Face(3.1, -6.0, 0.0)),
            at((300.75, 0.0), Face(3.1, -6.0, 0.0)),
        ],
    )
    hole(
        "cmp:0002",
        hole_type="countersink",
        size="M3",
        end_condition="through",  # hol:0019
        instances=[at(point, Face(3.4, B1_ENTRY, B1_ENTRY + 2.5)) for point in rotated(B1_POINTS)],
    )
    hole(
        "cmp:0002",
        hole_type="countersink",
        size="M3",
        end_condition="through",  # hol:0020
        instances=[at(point, Face(3.4, B2_ENTRY, B2_ENTRY + 2.5)) for point in rotated(B2_POINTS)],
    )
    hole(
        "cmp:0009",
        hole_type="tapped",
        size="M3x0.5",
        thread="M3x0.5",  # hol:0021
        end_condition="through",
        instances=[at((1500.0, 0.0), Face(2.5, 0.0, 1.725))],
    )
    hole(
        "cmp:0006",
        hole_type="tapped",
        size="M5x0.8",
        thread="M5x0.8",  # hol:0022
        thread_depth_mm=10.0,
        hole_depth_mm=12.0,
        end_condition="blind",
        instances=[at((2100.0, 0.0), Face(4.2, -12.0, 0.0))],
    )
    hole(
        "cmp:0002",
        hole_type="countersink",
        size="M2",
        end_condition="through",  # hol:0023
        instances=[at(point, Face(2.4, A_ENTRY, A_ENTRY + 2.5)) for point in A_POINTS],
    )
    hole(
        "cmp:0003",
        hole_type="counterbore",
        size="M8",
        end_condition="through",  # hol:0024
        instances=[
            at(point, Face(9.0, -16.0, -14.6), Face(14.0, -14.6, -6.0)) for point in C_BORES
        ],
    )
    hole(
        "cmp:0011",
        hole_type="counterbore",
        size="M8",
        end_condition="through",  # hol:0025
        instances=[
            at((1800.0, 40.0 * k), Face(9.0, 0.0, 1.4), Face(12.0, 1.4, 10.0)) for k in range(2)
        ],
    )
    hole(
        "cmp:0005",
        hole_type="clearance",
        size="Ø2.0",
        end_condition="through",  # hol:0026
        instances=[at((300.0 + 10.0 * k, 60.0), Face(2.0, 0.0, 6.0)) for k in range(3)],
    )
    hole(
        "cmp:0005",
        hole_type="clearance",
        size="Ø3.0",
        end_condition="through",  # hol:0027
        instances=[at((300.0, 0.0), Face(3.0, 0.0, 6.0)), at((340.0, 0.0), Face(3.0, 0.0, 6.0))],
    )

    # --- screws ------------------------------------------------------------------------
    spare = iter(f"cmp:{number:04d}" for number in range(29, 90))

    def screw(
        document: str,
        bearing: tuple[float, float, float],
        direction: tuple[float, float, float] = Z,
        component_id: str | None = None,
        **faces: object,
    ) -> str:
        return builder.screw(
            document,
            bearing_mm=bearing,
            direction=direction,
            component_id=component_id or next(spare),
            **faces,
        )  # type: ignore[arg-type]

    region_a = [
        screw(
            fht_m2,
            (x, y, A_ENTRY + 3.795),
            component_id="cmp:0017" if index == 0 else None,
            **({"shank_face_mm": 2.0} if index == 0 else {}),
        )
        for index, (x, y) in enumerate(A_POINTS)
    ]
    region_b1 = [
        screw(
            fht_m3,
            (x, y, B1_ENTRY + 4.867),
            component_id="cmp:0027" if index == 0 else None,
            **({"shank_face_mm": 3.0} if index == 0 else {}),
        )
        for index, (x, y) in enumerate(B1_POINTS)
    ]
    region_b2 = [
        screw(
            fht_m3,
            (x, y, B2_ENTRY + 4.117),
            component_id="cmp:0024" if index == 0 else None,
            **({"shank_face_mm": 3.0} if index == 0 else {}),
        )
        for index, (x, y) in enumerate(B2_POINTS)
    ]
    region_c = [
        screw(
            m8,
            (x, y, -14.6),
            **({"shank_face_mm": 8.0, "head_face_mm": 13.0} if index == 0 else {}),
        )
        for index, (x, y) in enumerate(C_BORES)
    ]
    region_d = [
        screw(
            m8,
            (1.625, y, z),
            X,
            component_id="cmp:0016" if index == 0 else None,
            **({"shank_face_mm": 8.0} if index == 0 else {}),
        )
        for index, (y, z) in enumerate(D_POINTS)
    ]
    region_e = [
        screw(
            m10,
            (x, y, 1.775),
            component_id="cmp:0018" if index == 0 else None,
            **({"shank_face_mm": 8.5} if index == 0 else {}),
        )
        for index, (x, y) in enumerate(E_POINTS)
    ]
    oblique = screw(
        m4,
        (1200.0 + 5.0 * TILT[0], 0.0, 5.0 * TILT[2]),
        TILT,
        component_id="cmp:0007",
        shank_face_mm=3.3,
    )
    sheet_screw = screw(m3_short, (1500.0, 0.0, 4.331), component_id="cmp:0008", shank_face_mm=3.0)
    unclassified = screw(m8, (1800.0, 40.0, 10.0), shank_face_mm=6.75)
    second_m4 = screw(m4, (2100.0, 0.0, 5.0))
    region_j = [screw(m5, (x, y, 6.0)) for x, y in J_POINTS[:7]]
    named_m5 = screw(
        m5_named,
        (J_POINTS[7][0], J_POINTS[7][1], 6.0),
        shank_face_mm=3.3,
        shank_face_span=(-20.0, -8.0),
    )
    loose = [screw(m5, (3000.0 + 20.0 * k, 0.0, 0.0)) for k in range(10)]
    loose.append(screw(bht_m5, (3300.0, 0.0, 0.0), shank_face_mm=5.0))

    # --- free faces: 13 on parts with holes, 3 on parts without -----------------------
    def free(
        component_id: str,
        point: tuple[float, float],
        diameter: float,
        lo: float,
        hi: float,
        direction: tuple[float, float, float] = Z,
    ) -> None:
        builder.cylinder_face(
            component_id,
            origin_mm=(point[0], point[1], 0.0),
            direction=direction,
            diameter_mm=diameter,
            lo_mm=lo,
            hi_mm=hi,
        )

    free("cmp:0003", (1200.0, 0.0), 4.5, 0.0, 5.0, TILT)  # the plain bore over hol:0013
    for y in (150.0, 170.0, 190.0):
        free("cmp:0003", (900.0, y), 6.0, 12.0, 18.0)
        free("cmp:0005", (360.0, y), 5.0, 0.0, 6.0)
    for x in (900.0, 920.0, 940.0):
        free("cmp:0001", (x, -150.0), 12.0, -20.0, 0.0)
    for x in (2400.0, 2420.0, 2440.0):
        free("cmp:0011", (x, 200.0), 7.0, 0.0, 6.0)
    free("cmp:0021", (4050.0, 0.0), 4.0, 0.0, 5.0)
    free("cmp:0021", (4070.0, 0.0), 4.0, 0.0, 5.0)
    free("cmp:0022", (4200.0, 0.0), 10.0, 0.0, 20.0)

    # --- meshes the frames do not give ----------------------------------------------------
    builder.mesh("cmp:0023", cylinder_mesh((300.0, 0.0, 0.0), Z, 3.0, 0.5, 11.5))
    builder.mesh("cmp:0025", cylinder_mesh((340.0, 0.0, 0.0), Z, 3.0, -5.5, 5.5))
    builder.mesh(
        "cmp:0010",
        box_mesh((1790.0, -10.0, -10.0), (1810.0, 50.0, 0.0)),
        box_mesh((2390.0, -10.0, -6.0), (2520.0, 130.0, 0.0)),
    )
    builder.mesh("cmp:0020", box_mesh((4000.0, 100.0, 0.0), (4020.0, 120.0, 5.0)))
    builder.mesh("cmp:0021", box_mesh((4040.0, -10.0, 0.0), (4080.0, 10.0, 5.0)))
    builder.mesh("cmp:0026", box_mesh((4100.0, 100.0, 0.0), (4120.0, 120.0, 5.0)))
    builder.mesh("cmp:0022", box_mesh((4190.0, -10.0, 0.0), (4210.0, 10.0, 0.5)), is_solid=False)
    builder.mesh("cmp:0028", box_mesh((4300.0, -10.0, 0.0), (4320.0, 10.0, 0.5)), is_solid=False)
    builder.gap(
        kind="not_extracted",
        entity_kind="hole",
        entity_id="cmp:0010",
        reason="no Hole Wizard feature of this component could be read",
        error=None,
    )

    # --- interference: 113 groups, 8 of them with a positive volume ------------------------
    contact_units = {**dict.fromkeys(region_a[:2], "m3"), **dict.fromkeys(region_b2, "in3")}
    for screw_id in [*region_a, *region_b1, *region_b2]:
        builder.interference(screw_id, "cmp:0002", unit=contact_units.get(screw_id, "mm3"))
    for screw_id in [*region_c, *region_d, *region_e, oblique]:
        builder.interference(screw_id, "cmp:0003")
    builder.interference(unclassified, "cmp:0011")
    builder.interference(second_m4, "cmp:0006")
    builder.interference(sheet_screw, "cmp:0009")
    for screw_id in [*region_j, named_m5]:
        builder.interference(screw_id, "cmp:0011")
    for screw_id in loose:
        builder.interference(screw_id, "cmp:0010", volume_mm3=None, is_possible=True)
    builder.interference("cmp:0023", "cmp:0005")
    builder.interference("cmp:0023", "cmp:0004")
    builder.interference("cmp:0025", "cmp:0005")
    builder.interference("cmp:0025", "cmp:0004", volume_mm3=1.237)  # the 0.750 mm offset

    parts = [
        "cmp:0001",
        "cmp:0002",
        "cmp:0003",
        "cmp:0004",
        "cmp:0005",
        "cmp:0006",
        "cmp:0009",
        "cmp:0010",
        "cmp:0011",
        "cmp:0020",
        "cmp:0021",
        "cmp:0022",
        "cmp:0026",
        "cmp:0028",
    ]
    positive = {
        ("cmp:0001", "cmp:0003"): 12.5,
        ("cmp:0002", "cmp:0004"): 0.42,
        ("cmp:0010", "cmp:0011"): 3.75,
        ("cmp:0001", "cmp:0006"): 0.8,
        ("cmp:0003", "cmp:0005"): 2.2,
        ("cmp:0009", "cmp:0011"): 5.0,
    }
    for (first, second), volume in positive.items():
        builder.interference(first, second, volume_mm3=volume)
    builder.interference("cmp:0021", "cmp:0003", volume_mm3=3.5, group_key="pat:fict|cmp:0003")
    builder.interference("cmp:0026", "cmp:0003", volume_mm3=0.0, group_key="pat:fict|cmp:0003")
    taken = {*positive, ("cmp:0003", "cmp:0021"), ("cmp:0003", "cmp:0026")}
    pairs = [
        (first, second)
        for index, first in enumerate(parts)
        for second in parts[index + 1 :]
        if (first, second) not in taken
    ][:34]
    for index, (first, second) in enumerate(pairs):
        if index % 3 == 2:
            builder.interference(first, second, volume_mm3=None, is_possible=True)
        else:
            builder.interference(first, second)

    # --- masses that depend on the tree ----------------------------------------------------
    enclosure_children = builder.children_of("cmp:0019")
    enclosure_masses = [builder.mass_of(child) for child in enclosure_children]
    builder.set_mass(sub_enclosure, round(sum(m for m in enclosure_masses if m), 9), 150_000.0)
    top = builder.children_of(None)
    builder.set_mass(
        root, round(sum(builder.mass_of(child) or 0.0 for child in top), 9), 2_000_000.0
    )
    return builder.build()


# --- the small assembly ------------------------------------------------------------------


def build_small_assembly() -> Built:
    builder = PackageBuilder(
        design_stem="FICT-ARVOSORN-0000", root_properties=house("FICT-ARVOSORN-0000", "ARVO SORN")
    )
    plate = builder.document(
        "FICT-ARVOQUILL-2001",
        "part",
        material="6061-T6",
        mass_kg=0.35,
        volume_mm3=round(0.35 / 2700.0 * 1e9, 6),
        properties=house("FICT-ARVOQUILL-2001", "ARVO QUILL"),
    )
    pin = builder.document(
        "FICT-PIN-3X12-2002",
        "part",
        material="Alloy Steel",
        mass_kg=0.0111,
        volume_mm3=round(0.0111 / 7850.0 * 1e9, 6),
        properties=house("FICT-PIN-3X12-2002", "PIN ARVO 2002"),
    )
    builder.component(plate, component_id="cmp:0001")
    builder.component(pin, component_id="cmp:0002", placement=transform((0.0, 40.0, 0.0)))
    builder.component(pin, component_id="cmp:0003", placement=transform((0.0, 60.0, 0.0)))
    builder.component(pin, component_id="cmp:0004", suppression="suppressed")

    builder.hole(
        "cmp:0001",
        hole_type="tapped",
        size="M5x0.8",
        thread="M5x0.8",  # hol:0001
        thread_depth_mm=6.0,
        hole_depth_mm=8.0,
        end_condition="blind",
        instances=[at((20.0 * k, 0.0), Face(4.2, 2.0, 10.0)) for k in range(4)],
    )
    builder.hole(
        "cmp:0001",
        hole_type="clearance",
        size="M5",
        end_condition="through",  # hol:0002
        instances=[at((20.0 * k, 20.0), Face(5.5, 0.0, 10.0)) for k in range(4)],
    )
    for y in (40.0, 60.0):  # hol:0003, and hol:0004 whose first instance holds the pin
        builder.hole(
            "cmp:0001",
            hole_type="clearance",
            size="Ø3.0",
            end_condition="through",
            instances=[at((20.0 * k, y), Face(3.0, 0.0, 10.0)) for k in range(4)],
        )
    builder.cylinder_face(
        "cmp:0003",
        origin_mm=(0.0, 60.0, 0.0),
        direction=Z,
        diameter_mm=3.0,
        lo_mm=1.525,
        hi_mm=12.0,
    )
    builder.mesh("cmp:0002", cylinder_mesh((0.0, 40.0, 0.0), Z, 3.0, 0.0, 12.0))
    builder.mesh("cmp:0003", cylinder_mesh((0.0, 60.0, 0.0), Z, 3.0, 0.0, 12.0))
    builder.interference("cmp:0003", "cmp:0001")
    builder.interference("cmp:0003", "cmp:0001")
    resolved = [item for item in ("cmp:0001", "cmp:0002", "cmp:0003")]
    builder.set_mass(
        builder.root_id,
        round(sum(builder.mass_of(item) or 0.0 for item in resolved), 9),
        round(0.35 / 2700.0 * 1e9 + 2 * 0.0111 / 7850.0 * 1e9, 6),
    )
    return builder.build()


FIXTURES = {
    "big-assembly": build_big_assembly,
    "small-assembly": build_small_assembly,
}


def render_all() -> dict[str, bytes]:
    """`{<fixture>/<relative path>: bytes}` for every file this script writes."""
    return {
        f"{name}/{relative}": content
        for name, build in FIXTURES.items()
        for relative, content in build().render().items()
    }


def main() -> None:
    for relative, content in render_all().items():
        path = FIXTURE_DIR / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        print(f"wrote {path.relative_to(FIXTURE_DIR)}")


if __name__ == "__main__":
    main()
