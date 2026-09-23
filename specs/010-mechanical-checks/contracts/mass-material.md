# Contract: Mass and Material

Normative for FR-016 to FR-018, User Story 6 and SC-005.

## 1. The material classes (`checks/material_classes.yaml`)

```yaml
version: 1
default_class: unknown
no_material_density_kg_m3: 1000   # SOLIDWORKS' density for a part with no material
classes:
  steel:     {matches: [...], density_kg_m3: [7600, 8100], source: "..."}
  aluminum:  {matches: [...], density_kg_m3: [2600, 2850], source: "..."}
  cast_iron: {matches: [...], density_kg_m3: [6800, 7400], source: "..."}
  plastic:   {matches: [...], density_kg_m3: [850, 2200], source: "..."}
  unknown:   {matches: [], density_kg_m3: null, source: "No class; material not recognized"}
```

The match tokens are today's `engagement_rules.yaml` tokens, moved, not rewritten; the first
class whose token is a substring of the lower-cased material name wins; a class may be added
(brass, copper, titanium) with no engagement rule, which leaves engagement for it unresolved.
`EngagementRules.for_material` resolves the class through `material_classes.for_material` and
reads its ratio by class name.

## 2. The checks (`checks/mass.py`)

Per part document reached by the component tree (and the root when it is a part):

| Check | Condition | Status |
|---|---|---|
| `mass.material_assigned` | a material; or no material and `mass_overridden is True` | passes: counted in one `checked` item `mass.material_assigned` (a rule with no calculation records its passes as coverage, research R2.21) |
| | no material and `mass_overridden is False` | demonstrated |
| | no material and `mass_overridden is None` | unresolved, naming the `mass_override` gap |
| | the document was not opened (a `document` gap, or every instance lightweight or suppressed) | not checked; counted in section 3 |
| `mass.density` | a class with a range, a mass and a volume > 0: `mass_kg / volume_m3` outside the range | demonstrated, both numbers and the class row |
| | within 2 percent of `no_material_density_kg_m3` | demonstrated: `"the density is SOLIDWORKS' no-material default"` |
| | inside the range | checked within scope |
| | class `unknown` or no volume | not checked; counted in section 3 |

Per assembly document:

| Check | Condition | Status |
|---|---|---|
| `mass.assembly_override` | `mass_overridden is True` | suspected: `"the assembly mass is overridden; confirm <m> kg is intended"` |
| | `mass_overridden is None`, every child read: the mass differs from the sum of the children's masses by more than 0.1 percent | suspected, both numbers |
| | `mass_overridden is None`, a child unread, and the mass is a whole number of grams of at least 100 g | suspected: `"a round <m> kg while <n> children were never read"` |
| | otherwise | no finding |

Densities are never computed for an assembly. A part whose mass is overridden is not given a
density verdict (the mass is not the geometry's).

As landed (T065): the no-material-default sentence is added to a density **outside** the class
range; a density inside the range passes even near 1000 kg/m3, because a plastic class spans
it (SOLIDWORKS' ABS is 1020 kg/m3) and a real material there is not a default. In the
assembly sums, suppressed children are left out (SOLIDWORKS leaves them out of the mass) but
counted among the children "never read" in the round-mass sentence, and a child that was read
with no mass (a surface-only part) weighs nothing. Density findings are `medium`; the
assembly override suspicion is `low`. The root assembly, which has no component instance, is
bound to its document. `run_mass_checks(package)` returns a `MassChecks` - the findings with
the document and instances each binds to, the counted passes, the coverage item - rather
than a bare list, because the tool needs the binding.

## 3. Coverage

One `skipped` item `mass.coverage` per run: `"<n> components were not read (lightweight <a>,
suppressed <b>, not opened <c>); <m> bodies could not be read; <k> parts have no material class
with a density range or no volume"`, its scope the component ids. FR-018's count is this item,
from the existing `document` and `body` gaps. A run with nothing to count writes no item (a
family with nothing to report renders no line).

## 4. The extractor override read (seat-validated)

`PropertyDumper` reads the override through a second object,
`model.Extension.CreateMassProperty()`, as `((IMassProperty)obj).OverrideMass`; when that read
raises, through `((IMassProperty2)CreateMassProperty2()).GetOverrideOptions()`, recording which
path answered in the gap text on failure. Both are delegate reads, so
`PropertyDumper.ReadMassOverridden` and its tests keep their shape. `set_OverrideMass` and
`SetOverrideMassValue` are already denied (`Guard/ReadOnlyGuard.cs:116-118`).

## 5. Acceptance on the big fixture

A part with an aluminium material at 2700 kg/m3 passes; a part at 1000 kg/m3 is demonstrated; the
2.000 kg sub-assembly with unread children is suspected; the unread and surface-only parts are in
the coverage count; every part with a mass and a volume has a `mass.density` or
`mass.material_assigned` verdict (SC-005).
