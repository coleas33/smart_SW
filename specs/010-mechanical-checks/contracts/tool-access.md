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

1. the head code's `drive` from `fastener_names.yaml` (`hex_socket` → `hex_key`, `hex_head` →
   `socket`);
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
package holds is swept; a component whose body was never fetched is named, never assumed clear.

## 4. Head fit (`fastener.head_fit`)

| Recess | Diameter | Depth | Demonstrated when |
|---|---|---|---|
| counterbore instance | the instance's larger diameter (face) or `wizard.counterbore_diameter` | the counterbore face's axial extent (derived) or `wizard.counterbore_depth` | diameter `< dk_max`, or depth `< k_max` (the head stands proud) |
| countersink instance | `wizard.countersink_diameter` (US8) | - | diameter `< dk_max` of the countersunk head, or `countersink_angle` differs from the table's |

`dk_max` and `k_max` from `checks/head_dimensions.yaml` by head type and size, each row citing its
standard (ISO 4762 socket head cap, ISO 7380 button, ISO 10642 countersunk, ISO 4017/4014 hex).
A countersink before US8, a head type or size the table lacks, or an oblique counterbore extent
is unresolved naming it. A pass is checked within scope with both numbers.

## 5. Acceptance

On the big fixture: a screw head under an overhanging part's mesh is `fastener.head_clearance`
demonstrated naming that component; a clear head passes; a counterbore of 12.0 mm under a
13.0 mm M8 socket head is `fastener.head_fit` demonstrated; the 14.0 mm counterbore under the same
head passes.
