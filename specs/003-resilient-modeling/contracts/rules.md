# RMS Rule Catalogue

Rule ids are stable and appear verbatim in findings (`check`), coverage, exceptions, waiver
files, and the checklist. `Severity` is the method's: `fail` → `demonstrated`, `warn` →
`suspected` (see data-model section 2 for the full mapping). `Subjects` names what a finding
points at. Every evaluable rule is evaluated once per subject document and produces one
`RuleResult` per outcome it reaches on that document, each naming the subjects that share
that outcome; one rule may therefore appear in more than one bucket (finding, checked,
skipped, unresolved) for a single document, and every rule appears in at least one. 34 ids
in total: 18 part, 2 equations, 4 evaluable assembly, 4 data-gap assembly, 1 drawing, 5
advisory.

## Class vocabulary

`classify(type_name)` returns exactly one of `sketch, solid, cut, hole, fillet, chamfer,
shell, draft, pattern, reference, construction`, or `unknown` (not listed) or `ambiguous`
(listed as ambiguous, currently `ICE`). "Material" below means `{solid, cut, hole,
ambiguous}`. A rule that needs a specific class reports a feature of class `unknown` as
unresolved; it reports `ambiguous` as unresolved unless the rule reads material. Rules that
need no class (grouping, description, references, sketches) treat an `unknown` feature like
any other content feature, as the source checker does.

## Part scope (one evaluation per part document; see "Unresolved part documents")

| Rule id | Severity | Statement (paraphrased from the method) | Subjects | Skip / unresolved conditions |
|---|---|---|---|---|
| `rms.folders.present` | warn | Every one of the six groups exists as a folder. | document | never skips |
| `rms.folders.ordered` | fail | Group folders appear once each, in the order Reference, Construction, Core, Detail, Modify, Quarantine. | folders out of order or duplicated | skip when fewer than two groups (reason `fewer than two groups`) |
| `rms.grouping.all_features_in_a_group` | fail | Every content feature lives inside a group. | loose content features | never skips: a part with no group folders fails, listing every content feature |
| `rms.groups.no_solids_in_ref_or_construction` | fail | Reference and Construction contain no material (solids, cuts, holes; `ambiguous` counts as material). | offending features | skip when neither group exists; unresolved per feature of class `unknown` in those groups |
| `rms.core.shell_last` | fail | The shell is the last feature in Core. | shell and later features | skip when no Core group or no shell |
| `rms.detail.holes_last` | warn | Holes are the trailing block of Detail (sketches ignored). | holes and later features | skip when no Detail group or no hole; unresolved per `ambiguous` or `unknown` feature in Detail |
| `rms.modify.transform_before_replicate` | warn | Drafts precede patterns in Modify. | draft and pattern | skip when no Modify group, no draft, or no pattern (reason names what is absent) |
| `rms.quarantine.chamfers_before_fillets` | fail | Chamfers precede fillets in Quarantine. | offending pair | skip when no Quarantine group (reason `no Quarantine group`) or it is empty |
| `rms.quarantine.largest_fillet_first` | fail | Fillet radii in Quarantine are non-increasing. | fillets out of order | skip when no Quarantine group (reason `no Quarantine group`) or with fewer than two readable radii (reason names the unreadable fillets) |
| `rms.quarantine.only_fillets_and_chamfers` | fail | Quarantine holds only fillets and chamfers. | offending features | skip when no Quarantine group (reason `no Quarantine group`) or it is empty; unresolved per `unknown` feature |
| `rms.refs.direction` | fail | No feature depends on a feature in a later group (a dependent lives in the same or a later group than what it depends on). | feature and dependent | unresolved per feature whose `child_ids` is null |
| `rms.refs.quarantine_has_no_children` | fail | Nothing depends on a Quarantine feature. | feature and dependent | skip when no Quarantine group (reason `no Quarantine group`); unresolved per Quarantine feature whose `child_ids` is null |
| `rms.detail.no_internal_references` | fail | Detail features do not depend on other Detail features, except (a) a sketch consumed by exactly one feature, and (b) a pair of features sharing the same derived subfolder inside Detail (the coupled-pair exception). | feature and dependent | skip when no Detail group; unresolved per Detail feature whose `child_ids` is null |
| `rms.intent.every_feature_described` | fail | Every content feature carries a description. | undescribed features | unresolved per feature whose `description` is null |
| `rms.sketches.fully_defined` | fail | Every sketch is fully defined. Only `under_defined` fails. | sketch and consumers | unresolved per sketch whose derived status is `unavailable` or `unknown` |
| `rms.sketches.not_over_defined` | fail | No sketch is over defined or in solver error. Only `over_defined` and `solver_error` fail. | sketch and consumers | unresolved per sketch whose derived status is `unavailable` or `unknown` |
| `rms.sketches.one_sketch_per_feature` | fail | No sketch is consumed by more than one feature. | sketch and consumers | unresolved per sketch whose `consumer_ids` is null; a sketch with no consumer passes |
| `rms.detail.individually_suppressible` | fail | Each Detail feature can be suppressed alone without rebuild errors. | feature | see the outcome table below |

### Suppress-test outcome table (`rms.detail.individually_suppressible`)

Evaluated over the Detail content features of the document (the same set
`swreview rms suppress-plan` writes) against `package.rms_suppress_test`.

| Condition | Result |
|---|---|
| no run in the package, or its `document_id` is another document | unresolved for every Detail content feature (reason `no suppress-test run`) |
| run `configuration` differs from the review configuration | unresolved for every row (reason names both configurations) |
| run `restore_verified` is false | unresolved for every row (reason `restore not verified`) |
| row `rebuild_errors` (post-rebuild count above the run's baseline) | fail; observed carries the counts and messages |
| row `ok` | pass |
| row `already_suppressed`, `truncated` | skip with the outcome as reason |
| row `not_applied`, `aborted` | unresolved with the outcome and error as reason |
| a Detail content feature with no row | unresolved (reason `not tested`) |
| a row whose feature is not a Detail content feature in this package | ignored; named in the coverage reason as unused |
| coverage reason | always names `<tested>/<present>` features |

## Equation scope (per part document; see "Unresolved part documents")

| Rule id | Severity | Statement | Subjects | Skip / unresolved |
|---|---|---|---|---|
| `rms.params.global_variables_present` | fail | At least one global variable exists. | document | unresolved when the `equations` gap is recorded or any `is_global` is null |
| `rms.params.dimensions_driven_by_equations` | warn | At least one dimension is driven by an equation. | document | unresolved when the `equations` gap is recorded or any `is_global` is null |

## Assembly scope (root assembly document only)

The extractor reads the root assembly's mates only and `Mate` carries no owning document,
so the four evaluable assembly rules run on the root assembly document (`design.root_assembly_document_id`,
instance `cmp:0001`). Subassembly documents are covered by the data-gap rule
`rms.assembly.subassemblies` below.

| Rule id | Severity | Statement | Subjects | Skip / unresolved |
|---|---|---|---|---|
| `rms.assembly.mates_to_reference_geometry` | fail | Mates reference planes, axes, points, or coordinate systems, not faces, edges, or vertices. | mate and its components | skip when the root assembly has no mates; unresolved per mate with an entity kind in neither list (including `unknown(<n>)` and sketch entities) |
| `rms.assembly.first_component_fixed` | fail | The first component is fixed, or fully constrained. | the first `ComponentInstance` whose `parent_id` is `cmp:0001`, in package order | skip when the root has no child components; unresolved when not fixed and the constrained status is `unknown` or `unavailable`; fail when not fixed and `under_defined`, `over_defined`, or `solver_error` |
| `rms.assembly.mate_chain_depth` | warn | No component is more than `limit` mates from the fixed root (default 3). | the chain | skip when no mates; unresolved when no fixed child of `cmp:0001` exists, and per component unreachable from the root; the graph's nodes are every component instance and its edges the unsuppressed root mates (a mate's entities name the instances it joins); several fixed children: the first is the root, the rest are named in observed |
| `rms.assembly.toolbox_parts_not_configurations` | warn | Toolbox hardware is inserted as parts, not as configurations of one file. | document and instances | skip when every component is readable and none is Toolbox; unresolved per component with a Toolbox-identity gap |

## Data not yet extracted (unresolved coverage, once per review)

| Rule id | Scope | Statement | Coverage reason |
|---|---|---|---|
| `rms.assembly.no_sibling_in_context_refs` | assembly | No in-context references between sibling parts. | `external references not extracted` |
| `rms.assembly.positions_driven_by_globals` | assembly | Component positions are driven by assembly global variables where they are parametric. | `assembly equations not extracted` |
| `rms.assembly.mates_described` | assembly | Mates are named for intent through their description. | `mate descriptions not extracted` |
| `rms.assembly.subassemblies` | assembly | The assembly rules hold for each subassembly as for the root. | `subassembly mates not extracted; assembly rules evaluated for the root document only` (the item's `scope.document_ids` lists the subassembly documents) |

## Out of scope in this version (`out_of_scope` coverage, once per review)

| Rule id | Scope | Statement | Coverage reason |
|---|---|---|---|
| `rms.drawing.model_items_preferred` | drawing | Drawings use model items; the scheme is not re-dimensioned in the drawing. | `drawing-owned vs model dimensions not extracted; advisory by decision` |
| `rms.advisory.structural_vs_cosmetic_fillets` | advisory | Structural fillets belong in Core or Detail; cosmetic fillets in Quarantine. | `judgement-only; not decidable from extracted data` |
| `rms.advisory.core_shaping_cuts` | advisory | A cut in Core shapes the core; a cut that adds detail belongs in Detail. | `judgement-only; not decidable from extracted data` |
| `rms.advisory.description_quality` | advisory | Descriptions state intent, not the feature type. | `judgement-only; not decidable from extracted data` |
| `rms.advisory.sketch_plane_choice` | advisory | Sketches sit on reference planes, not on model faces. | `judgement-only; sketch planes not extracted` |
| `rms.advisory.avoid_multibody` | advisory | Parts stay single-body unless multibody is the intent. | `judgement-only; body intent not decidable` |

## Group assignment (normative)

Walk the tree in `index` order. A folder (a feature whose `type_name` is `folder_type` and
whose name does not end with `end_tag_suffix`) named exactly one of the six group names sets
the current group; everything after it belongs to that group until the next group folder,
whether it is nested under the folder (depth 1, nested shape) or follows it at depth 0 (flat
shape). Features before the first group folder have no group. A group folder nested inside
another folder sets the current group exactly as a top-level one does. A group name
appearing a second time re-opens that group and is recorded as a duplicate, which fails
`rms.folders.ordered` naming both occurrences. Content features after a group's end-tag
marker still belong to that group. End-tag markers never change the group and are never
subjects.

A non-group folder opens a derived subfolder: in the nested shape its members are the
features whose `folder_id` is the folder; in the flat shape its members are the features
that follow it until its own end-tag marker (the folder-typed feature named
`<folder name>___EndTag___`). The coupled-pair exception compares the derived subfolder id,
never `Feature.folder_id` directly.

## Content features (normative)

A feature is content when it is not a folder, not an end-tag, its name is not one of the
excluded default names, and its type is not in `tolerated_loose`. A feature of class
`unknown` is content (it must be grouped and described); rules that need its class report it
unresolved, and its type name is reported once per review in `rms.types.unknown`.

*Amended 2026-09-25 (owner decision 20A; decided, not yet in effect - see the status below):*
`tolerated_loose` also holds the eleven system types the real 2024 SP5 dumps carry (research R3):
the annotations container's folders and view, the scene's lights, a derived part's body and
reference folders, and the cosmetic thread. A row of one of them is not content wherever it sits -
never loose, never asked for a description, never named in `rms.types.unknown`, and never a
subject of a rule that grades content features - and it stays unclassified.
Feature 004's planner reads the same list; the table keeps no second list of types that are
content to one feature and not to the other.

*Status 2026-09-25 (review of decision 20A): not yet in effect.* The decision is recorded and its
code is not: tasks T090 and T091 land with T092 in one commit, and T092 stopped on verification
and waits on the owner's question 20A-Q1 (how feature 008's replay reads a recorded finding the
table has narrowed). Until they land, the shipped `rms_types.yaml` holds the eleven only in
decision 17A's planner-only key `remodel_not_content`, which `RmsTypeTable.planner_view()`
tolerates for feature 004's planner alone. These rules still read them as content of unknown
class: loose outside a group, asked for a description, and named in `rms.types.unknown`.

## Unresolved part documents (normative)

A part document with no `features[]` rows whose every `ComponentInstance` has `suppression`
other than `resolved` (each carrying a `feature_tree_unavailable` gap) is never evaluated
feature by feature: every part-scope and every equation-scope rule yields `unresolved` for
that document, reason `component <full_path> <suppression>; tree not read`. A document with
at least one resolved instance is evaluated normally, even when another instance is
lightweight, suppressed, or unloaded.

## Suppressed features (normative)

Suppressed features are evaluated as present in the tree. Every finding naming a suppressed
feature carries `suppressed in <configuration>` in its observed text and in
`coverage_limits`.

## Waivable rules

Only `fail`-severity rules are acceptable as exceptions; a waiver naming a `warn`, data-gap,
or out-of-scope rule is reported invalid and changes nothing.
