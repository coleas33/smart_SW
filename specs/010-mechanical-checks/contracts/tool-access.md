# Contract: Tool Access and Head Fit

Normative for FR-014, FR-015 and User Story 5. `checks/tool_access.py`.

## 1. The head

For a screw joint with a placed screw:

| Quantity | Rule |
|---|---|
| outward direction | along the reference axis, pointing away from the tapped instance (from the thread entry toward the screw's far end) |
| head plane | the far end of the screw's mesh extent (`mesh`); else the far end of its shank face plus `k_max` from the head table (`face_plus_k`, derived) |
| missing | a screw placed by origin with no mesh and no face; a head type the table lacks |

## 2. The tool

1. the head code's `drive` from `fastener_names.yaml`, mapped by `tool_envelopes.yaml`
   `drive_tools` (`hex_socket` → `hex_key`, `torx` → `torx_key`, `hex_head` → `socket`; the
   Torx key is a pilot-default envelope for FHT and BHT, owner answer 2026-09-23, and is the
   joint checks' own: `check_tool_envelope`'s `tool` argument is not widened);
2. else `tool_envelopes.yaml` `head_tools[head_type]` (`socket head cap`, `button head`,
   `socket countersunk head` → `hex_key`; `hex head` → `socket`);
3. else unresolved: `"the drive of head code <code> is not stated in fastener_names.yaml"`.

Radius: `envelope_diameter_ratio · d / 2 + clearance_mm` (existing). Reach:
`reach_diameter_ratio · d` (new, per tool, pilot default with its source line).

## 3. The sweep

`geometry.envelope_raycast(Axis(origin=head plane, direction=-outward), radius, reach, meshes)`
over every body of every other component, the screw's own excluded; `envelope_raycast`'s
convention (rays travel along `-direction`) makes them travel outward. The result feeds
`check_placed_screw(..., envelope=...)`, so `fastener.head_clearance` is decided by the existing
`_head_clearance`: a hit is demonstrated naming the blocking component and distance; an unloadable
mesh is unresolved naming it; no hit is checked within scope with the sampling limit. When the
package holds no body mesh at all, one `skipped` coverage item `fastener.head_clearance` covers
every joint instead of one unresolved finding each. Lever 10a's lazy meshes: whatever the
package holds is swept (the code-first pass makes no bridge call to fetch more); a part
component whose body was never fetched is named, never assumed clear. A body whose bounds the
envelope's box cannot reach is not cast against - it cannot be hit - which keeps the sweep
linear in the bodies near each head. The head-clearance finding carries the tool, its radius
and reach, the pilot-default source line and the head plane's source in its inputs; a screw
with no head plane or no tool is unresolved naming why (`HeadSweep.missing`).

## 4. Head fit (`fastener.head_fit`)

| Recess | Diameter | Depth | Demonstrated when |
|---|---|---|---|
| counterbore instance | the instance's larger diameter (face) or `wizard.counterbore_diameter` | the counterbore face's axial extent (derived) or `wizard.counterbore_depth` | diameter `< dk_max`, or depth `< k_max` (the head stands proud) |
| countersink instance | `wizard.countersink_diameter` (US8) | - | diameter `< dk_max` of the countersunk head, or `countersink_angle` differs from the table's |

`dk_max` and `k_max` from `checks/head_dimensions.yaml` by head type and size, each row citing its
standard (ISO 4762 socket head cap, ISO 7380 button, ISO 10642 countersunk, ISO 4017/4014 hex).
A countersink before US8, a head type or size the table lacks, or an oblique counterbore extent
is unresolved naming it. A pass is checked within scope with both numbers. A head that cannot
seat (diameter, or a countersink angle that differs) is `high`; a head standing proud of a
shallow counterbore is `medium`. The Hole Wizard sizes win over the face-derived ones when the
package carries them. Head fit runs for every placed screw with a counterbore or countersink,
tapped or not; its results fold by screw document and recessed part (`recess_group`). The
table carries ISO 4762, ISO 7380-1, ISO 10642 and ISO 4017/4014 (the hex head's `dk_max` the
across-corners bound `s max / cos 30`, derived and labelled); it carries nothing for the
`flat head` of the owner's FHT (flat head Torx, ISO 14581 would be its standard), so those
countersinks are unresolved naming the missing row until the owner adds one.

## 5. Acceptance

On the big fixture: a screw head under an overhanging part's mesh is `fastener.head_clearance`
demonstrated naming that component; a clear head passes; a counterbore of 12.0 mm under a
13.0 mm M8 socket head is `fastener.head_fit` demonstrated; the 14.0 mm counterbore under the same
head passes.
