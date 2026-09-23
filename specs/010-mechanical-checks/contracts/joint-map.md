# Contract: The Joint Map

Normative for FR-004 to FR-006 and User Story 2. `build_joint_map(package, rules=None,
fasteners=None) -> JointMap` in `checks/joints.py`; types in `data-model.md` section 1.

## 1. Hole instances

For each `Hole`, its faces with `kind == "cylinder"` and a `cylinder` are grouped: two faces are
one instance when their axes are parallel within 0.01 degrees and coaxial within 0.001 mm. Groups
are ordered by their smallest face id; instance `n` is `<hole id>#<n>`. A hole whose component
is not `resolved`, whose faces are missing, or whose axes are zero-length yields a `JointMapGap`
naming it and no instance. `size_mm` is the native size when present (`Hole.diameter`; from US8
`wizard.thru_hole_diameter` or `wizard.tap_drill_diameter` by hole type), else the bore from the
faces with `size_source = "face"`.

## 2. The gates

For two instances `a`, `b` on different components, measured along `a`'s axis:

| Gate | Passes when | Value recorded |
|---|---|---|
| parallel | `angle <= parallel_deg` | `angle_deg` |
| overlap | `offset < bore_a/2 + bore_b/2` | `offset_mm`, `radius_sum_mm` |
| adjacent | `gap < adjacency_gap_mm`, `gap = max(lo_a, lo_b) - min(hi_a, hi_b)` over the face extents (negative when they overlap) | `gap_mm` |

Extents come from `geometry.axial_extent` over the members' face boxes. The gates use extents on
any axis; a joint check that needs an exact axial length requires `axis_aligned` (engagement,
head plane from a face), and says so when it is not.

## 3. Assignment and clusters

A pair passing all three gates is kept unless one of its instances already keeps a partner on
the other's component with a smaller offset (ties: the lower instance id); the loser is a
`Candidate(reason="assigned_elsewhere")`. Joints are the connected components of kept pairs.
A pair failing exactly one gate by no more than `candidate_margin` is a `Candidate` with
`angle_near`, `overlap_near` or `gap_near`. Pairs on the same component are never considered.

## 4. Cylinder members

A free cylinder face (in no `Hole.face_ids`) joins an instance when its component has **no**
`Hole` row, it is on another component than the instance, parallel within `parallel_deg`,
coaxial within `member_coaxial_mm`, its extent overlaps the instance's (overlap > 0), and its
diameter is `<= bore + member_diameter_allowance_mm` - for a tapped instance
`<= max(bore, thread nominal major diameter) + member_diameter_allowance_mm` - (`in_bore`), or,
for an instance with two diameters, `<= counterbore diameter` while overlapping the counterbore
face's extent (`in_counterbore`). A face that passes the geometric tests but sits on a component
with Hole rows is not a member (the package does not say whether it is a bore or a boss): one
`JointMapGap` per such component, with the count. A member coaxial with two instances of one
joint is counted once. A cylinder that joins an instance with no partner forms a one-instance
joint.

## 5. Placing recognised fasteners (from US4)

`build_joint_map(package, rules=None, fasteners=None)`. With `fasteners` (US4), each recognised
fastener is placed, in order: by face (a member face on the fastener's component); by origin (the
transform's translation within `origin_on_axis_mm` of an instance axis and one basis vector
parallel within `parallel_deg`); otherwise unplaced. A fastener placed on an instance in no joint
forms a one-instance joint with it. A fastener whose origin lies on two instances' axes of
different joints is placed on the one with a tapped instance, else left unplaced with both named.
A second fastener landing in a joint that already holds one is unplaced naming the first (a face
placement taking precedence over an origin one). Placement is decided before any lone instance
joins the map, so the order fasteners are placed in cannot change where any lands; the map with
fasteners is identical under any order of the package's arrays, as the foundational map is.
The map without `fasteners` (the foundational map) and the map with them are pinned by separate
goldens (`test_joint_map_acceptance/big-assembly.yml`, `test_fastener_identity/
big-assembly-with-fasteners.yml`). A joint whose only members are one clearance instance and a
screw placed by its origin has no second measured axis: alignment names it once in a skipped
item rather than passing it vacuously.

## 6. Kinds

First rule that matches:

1. any tapped instance, with any other instance, cylinder member or placed fastener → `screw`;
2. no tapped instance and a recognised screw or bolt placed (US4) → `screw` (its tapped part is
   not in the map, and the checks that need it say so);
3. no tapped instance, two or more clearance-type instances or one with a cylinder member, and the
   clearance instances' Hole Wizard `size` a plain diameter (`Ø3.0`) → `pin`;
4. no tapped instance, two or more clearance-type instances, the size a thread designation →
   `through_bolt`;
5. otherwise → `unclassified`.

## 7. What `check_joints` records for the map

| Item | Bucket | Check | Scope | Reason |
|---|---|---|---|---|
| one per pattern group | `checked` | `joint.map` | component ids; pairs of member components | `"<n> <kind> joints: <instance ids>"` |
| one per candidate | `skipped` | `joint.map` | the two components | `"not a joint: <reason> (<values>); listed for the engineer"` |
| one per gap | `skipped` | `joint.map` | the component | the gap's reason |
| one per unplaced fastener (US4) | `skipped` | `joint.map` | the component | `"<designation> was not placed: <why>"` |
| a package with no hole row, or a `model_check` package | `skipped` | `joint.map` | none | `"no hole was extracted"` / `"the hole phase did not run (profile model_check)"` |

`joint.map` is not a checklist item id, so none of these rows closes `holes.alignment` or
`fasteners`; the findings of US3 to US5 do, by prefix.

## 8. Thresholds (`checks/joint_rules.yaml`)

```yaml
version: 1
parallel_deg: 1.0            # spec Assumptions
adjacency_gap_mm: 1.0        # spec Assumptions
member_coaxial_mm: 0.2
member_diameter_allowance_mm: 0.05
origin_on_axis_mm: 0.2
axis_aligned_deg: 0.1        # bounding-box extent error at most r*sin(0.1 deg), recorded
candidate_margin: {angle_deg: 1.0, overlap_mm: 1.0, gap_mm: 1.0}
```

Every value non-negative and every angle below 90 degrees, or the loader refuses naming it.

## 9. The acceptance numbers (the big fixture, shaped like 830-02342)

The foundational map (no `fasteners`): 132 instances from 27 rows; 2 rows with no instance
(gaps); 47 kept hole pairs; **50 joints in 11 pattern groups** - 45 screw joints from hole pairs
(`hol:0014`/`hol:0019` x15, `hol:0016`/`hol:0023` x16, `hol:0015`/`hol:0020` x4,
`hol:0012`/`hol:0024` x4, `hol:0004`/`hol:0010` x3, `hol:0006`/`hol:0011` x3), 2 screw joints of a
screw face in a lone tapped instance (`hol:0013#1`, `hol:0021#1`), 2 pin joints
(`hol:0017`/`hol:0027` at 0.000 mm, `hol:0018`/`hol:0027` at 0.750 mm) and 1 unclassified
(`hol:0025#2` with a 6.75 mm cylinder); 2 candidates - `hol:0018#2`/`hol:0024#1` `overlap_near`
(7.006 mm against 6.05 mm) and `hol:0018#2`/`hol:0027#1` `assigned_elsewhere` (0.750 mm); 13 free
faces on parts with holes excluded; the first-instance pairs 1.576 and 3.950 mm apart are not
joints and not candidates. The small fixture (810-11249 shape): one `pin` joint, a 3.0 mm pin in a
3.0 mm hole at 0.000 mm, and no hole pair. The map with `fasteners` adds the joints of section 5
and is pinned by its own golden (US4).
