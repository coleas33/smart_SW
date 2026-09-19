# Standards Tab: Routes, Messages, Run Folder, Accept

The contract for User Story 3 and User Story 4 (spec FR-034 to FR-043): the three backend
routes the Standards page calls, the two message tables between that page and
`StandardsHost`, the check run folder, and what the Accept control means. **Tab 6 is
Standards**; tab 4 is Model check and tab 5 is Remodel, and neither moves.

This file is written **against feature 003's `contracts/model-check.md`**, whose shape it
follows row for row. Where the behaviour is the same, the wording is the same deliberately, so
a reader comparing the two files sees only what differs. Every difference is marked **[D]**
and listed again in section 6.

Everything here reuses the existing backend rules rather than restating them: the loopback
bind, the `Authorization: Bearer <token>` header on every request, the 401 on a missing or
wrong token, the `OPTIONS` preflight answered without a token, the exact virtual-host origin
echoed in `Access-Control-Allow-Origin` with a 403 for any other `Origin`, the `run_dir` path
rule (canonicalize, reject UNC and device paths, require a descendant of `--run-root`,
otherwise 400 `InvalidRunDir`), and the error body `{error_class, message, retryable}` with
the message redacted of any configured key.

The page calls these routes **itself**, with the token and origin it received in `init`, the
same way the Model check page does. The host does the `POST /sessions` call for a review only
because it must bind the run folder to a chat id it tracks; a check has no chat. Keeping a
potentially large result off the `postMessage` channel is a secondary benefit, and it matters
more here than for the Model check: a standards result over a drawing-rooted run carries
sixteen check rows across every document a drawing reaches.

The three route rows are added to feature 002's `contracts/chat-api.md`, and the tab-6 message
rows to feature 002's `contracts/pane-host-messages.md`; this file is the normative source for
both.

## 1. Routes

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/checks/standards` **[D]** | `{run_dir, profile_path: str}` **[D]** | `201 StandardsResult` (below). 400 when `run_dir` fails the path rule, or when `run_dir/package.json` is missing or invalid; 400 `error_class: "MissingStandardsPhases"` **[D]** when the package's phase rows show the phases the standards checks read did not run, naming the profile that produced it and the missing phases; 400 `error_class: "ProfileUnreadable"` **[D]** when `profile_path` is absent, unreadable or not configured; 400 `error_class: "ProfileInvalid"` **[D]** carrying the schema error when the file parses but fails the schema; 400 `error_class: "UnreadableExceptions"` when the carry-forward candidate exists and cannot be parsed. Runs synchronously: there is no provider, no network call and no turn. |
| GET | `/checks/{check_id}` | | `200` **the record's own family shape** **[D]**: a `StandardsResult` for a folder whose `check.json` carries `family: "standards"`, the feature 003 `CheckResult` for `family: "rms"` or for a record written before the field existed. 404 when no such check folder is under the run root. **Neither family answers for the other**: a `check_id` naming an rms folder requested by the Standards page returns the rms shape, and the Standards page renders nothing of it - each page reads back only the ids its own evaluation route produced, and renders nothing it cannot read. |
| POST | `/checks/{check_id}/exceptions/{finding_id}` | `{note, by}` | `200 {finding, exception_id}` with the finding re-rendered as checked within scope carrying the exception id; `400 EmptyNote` when the note is blank; `404` for an unknown check or finding; `409 RuleNotAcceptable` when the finding's check severity is `warning` (FR-041); `409 AlreadyAccepted` when an active exception with the same bindings and check already exists. Re-renders `report.md`. Dispatches on the record's `family`, so one route serves both. |

`check_id` is the check run folder's name (`<yyyyMMdd-HHmmss>-<doc>-standards` **[D]**), so a
check is addressable after a restart without any server-side registry, and `GET` resolves it
under the configured run root through the same path rule the `run_dir` body field goes
through.

**[D] There is no `scope` field.** The Model check route takes one because the RMS rules have
three families and only one of them is offered by the tab. Every standards check runs on every
run: the document kinds decide which apply, and a check that does not apply to any graded
document is an `out_of_scope` row (FR-033). A run that let an engineer switch checks off would
produce a verdict whose coverage depended on a control nobody recorded.

**[D] There is a `profile_path`.** The host supplies the configured path in `init`, having
already checked it is present and readable (FR-002), and **the page sends it on the request**,
the same way it sends the token and the origin it received in `init`; the backend reads and
validates the file, because the reasoning side owns the schema and expressing it twice is the
drift this design exists to avoid. FR-038 names `profile_path` among `init`'s fields for that
reason, and because the page shows which profile is in force. **No profile value travels
on this request or on any reply as a profile field.** A coverage reason may quote the one value a
check compared against where the spec requires the comparison to be named (FR-016's material
configuration); the profile itself is never reproduced.

### `StandardsResult`

```jsonc
{
  "check_id": "20260917-101532-top-plate-standards",
  "run_dir": "<run_root>/20260917-101532-top-plate-standards",
  "family": "standards",
  "document": {"id": "doc:ab12", "path": "...", "configuration": "AsBuilt", "kind": "assembly"},
  "extracted_at": "2026-09-17T10:15:32Z",
  "profile": {"path": "C:/Users/<user>/AppData/Local/SwReview/standards.yaml",
              "sha256": "9f2c..."},
  "extractor_profile": "standards",
  "documents_graded": [
    {"id": "doc:ab12", "kind": "assembly", "reached_by": "root"},
    {"id": "doc:cd34", "kind": "part", "reached_by": "component_tree"}
  ],
  "verdict": {
    "state": "ready_coverage_incomplete",
    // error/warning/waived count FINDINGS; the four coverage counts count
    // (check, document) pairs, so they do not sum to sixteen. Warning is 0 here
    // because the only two warning-severity checks are drawing-scope and this run
    // graded no drawing - they are out_of_scope rows.
    "counts": {"error": 0, "warning": 0, "checked": 9, "skipped": 4,
               "unresolved": 2, "out_of_scope": 4},
    "waived": 1,
    "unresolved_check_ids": ["standards.assembly.not_transparent",
                             "standards.assembly.mate_references"],
    "notes": ["1 finding waived by an accepted exception",
              "2 checks skipped because a profile list is empty",
              "no drawing graded"]
  },
  "checks": [
    {"check": "standards.assembly.not_exploded",
     "severity": "error",
     "statement": "An assembly is not left in an exploded state.",
     "worst_bucket": "checked",
     "buckets": [
       {"bucket": "checked", "document_ids": ["doc:ab12"], "reason": "1 document(s)"}
     ]}
  ],
  "findings": [
    {
      "finding": { /* the Finding, contract unchanged from feature 001 */ },
      "check": "standards.part.material_assigned",
      "severity": "error",
      "statement": "A part has a material assigned, or a deliberately overridden mass - and not both.",
      "observed": "...",
      "acceptable": true,
      "exception": {"id": "EX-004", "state": "active", "note": "..."}
    }
  ],
  "coverage": [
    {"bucket": "unresolved", "check": "standards.assembly.not_transparent",
     "scope": {"component_ids": ["cmp:0003"], "pairs": [], "configuration": "AsBuilt",
               "positions": [], "document_ids": ["doc:ab12"]},
     "reason": "1 document(s); doc:ab12: the transparency polarity is unsettled (PROBE-2)",
     "error": null}
  ],
  "subjects": {
    "<finding_id>": [
      {"kind": "component", "id": "cmp:0009", "name": "bracket-3",
       "persist_ref": "<base64>", "persist_ref_scope": "doc:ab12",
       "parent_chain": [], "showable": true}
    ]
  },
  "exceptions_carried_forward": {"from_run": "20260916-173001-top-plate-standards", "count": 2,
                                 "reason": null},
  "rebuilt": false,
  "attention": { /* the Ranking of feature 007 `contracts/attention.md` section 4,
                    minus session_id: policy_version, rows, top_n, not_amplified,
                    coverage, empty_reason */ }
}
```

**The unit of every count is stated, because the six do not share one** (`data-model.md`
section 3): `error`, `warning` and `waived` count **findings** - one per failing check per
document (FR-003) - and the four coverage counts count **(check, document) pairs** that reached
that bucket, so a check landing in two buckets over three documents contributes to both and the
four do not sum to sixteen. The page labels them so, and SC-002's and SC-003's "zero unresolved
checks" means zero checks with an `unresolved` pair.

Nine points the shape exists to enforce. The first three are feature 003's, unchanged, and
so are the last two.

- The result **never carries a letter grade**, and no single number stands alone. The
  unresolved check ids travel with the counts so a page cannot show a score without them.
- `subjects` is keyed by finding id and lives **beside** the findings, not inside the
  `Finding`, so the feature 001 finding contract is unchanged. The same subject also appears as
  a source reference on the finding itself, which is what makes Show work in the Review page as
  well. The page never parses a display string.
- A coverage item is the session's `CoverageItem` with its bucket in front of it, so the
  documents it covers are in its **`scope`** and not at the top level. `document` is the **root**
  document of the run, and `documents_graded` is the full list, because a standards run almost
  always grades more than one document and a page that read the ids anywhere else would lose
  every coverage row in a multi-document check.
- **[D] `verdict` replaces `grade`.** It carries `state`, the counts in every bucket, the
  waived count, the unresolved check ids and `notes`. `state` is computed from the error count
  and the unresolved coverage **alone** (FR-032), and `notes` is what stops a clean headline
  hiding a waiver, an empty profile list or a run that graded no drawing.
- **[D] `checks` is a required top-level array of all sixteen**, each with the buckets it
  landed in and a `worst_bucket` resolved in the order unresolved, failed, warned, skipped,
  checked, out of scope. A check that did not apply is **present** with an `out_of_scope`
  bucket, never absent. The Model check result leaves the page to derive its rule list from
  the coverage rows; a release gate must be able to say "all sixteen were accounted for" from
  one array. **`failed` and `warned` are derived, not read**: the review session has five
  coverage buckets and no `warned`, and this feature does not change that schema, so
  `checks/standards/report.py` computes them from the **findings** for that (check, document)
  pair - an `error`-severity finding renders `failed`, a `warning`-severity one `warned` - and
  reads the other four from `session.coverage`. **`standards.release` is not one of the sixteen
  and never appears in this array**: it is the family's summary coverage item
  (`contracts/rules.md`).
- **[D] `subjects[].showable`** says whether the page renders a Show control at all. A
  data-card property name, a note, a revision-table row, a cut-list item, a mate, and every
  drawing entity while the shared resolver reads model entities only, are `showable: false`,
  and the page renders **no** control rather than one that reports `ok: false` every time
  (FR-031).
- **[D] `rebuilt` is always `false`**, and it is in the payload rather than left implicit
  because the check it backs (`standards.assembly.rebuild_errors`,
  `standards.part.rebuild_errors`) reports counts the macro would have refreshed. The page
  renders it as a sentence beside those findings, and `report.md` carries the same sentence in
  its header (FR-033, difference g).
- `exceptions_carried_forward` carries a third field, **`reason`**: `null` when a store was
  carried, and the sentence saying why not - no earlier run of this design under the run
  root, or the folder already carrying this check's own evidence on a re-read - when none
  was. It has been in the payload since the route landed and was missing from this block, as
  it was from feature 003's; feature 007 research R3 named the drift and both are corrected
  in the same change. Not a difference: the two families answer identically.
- `attention` is feature 007's ranking of **this run's own session**, computed by
  `report/attention.rank` and carried so the Standards tab can render the rows an engineer
  should read first without computing an order of its own (feature 007 FR-022, FR-023). It
  is the `attention.json` block minus `session_id` - the body already names the check - and
  it is **byte-for-byte the block `CheckResult` carries**, which is why section 6 adds no
  difference row for it: one rule, one block, two tabs. Present on the POST, on the
  `GET /checks/{check_id}` re-read (recomputed in memory, byte-equal to the POST's, and the
  folder including `attention.json` is not written by the read) and after an Accept, whose
  re-run of the checks rewrites the record through the entry point. No path that produces
  it constructs a provider or reads a key (FR-045).

## 2. Standards page to host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` `{backend: {port, origin}, token, run_root, profile_path: str \| null, document: {path, configuration, kind} \| null, latest_check: {run_dir, at} \| null}`. **[D]** `profile_path` is the configured path or null; `latest_check` names only the newest **`-standards`** folder, never a model check folder (FR-034). |
| `standards.start` **[D]** | `{}` **[D]** | Refuse with `error {error_class: "NoDocument"}`, `"NotAttached"`, `"NeverSaved"` **[D]**, `"UnsupportedKind"` **[D]** (the document is not a part, an assembly or a drawing), or `"NoProfile"` **[D]** (no profile path is configured, or the file at it cannot be read) - **the profile check happens before anything is created or dumped, and a refusal writes no run folder** (FR-002). Otherwise create the check run folder, run the `Standards` profile dump in process, register the folder as the pane's latest run, and reply `standards.extracted {run_dir, document, configuration, counts: {documents, features, cut_list_items, drawing_sheets}, gaps}` **[D]**. Progress via `status`. The host stops here: the page calls `POST /checks/standards` itself. |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id}` | **Identical to the Review and Model check rows**, delegated to `PaneActions`; reply `entity.shown {ok, state_code, message, full_path \| null}`. |
| `report.open` | `{run_id}` | Delegated to `PaneActions`; the path comes from the host's own record, never from the page. |
| `folder.open` | `{run_id}` | Delegated to `PaneActions`. |
| `log.open` | `{}` | Delegated to `PaneActions`. |

The last four rows are the reason `PaneActions` exists and is not edited by this feature.
Their tests are **added to the existing parameterization** so the four rows are proven
identical across three hosts rather than assumed - the same regression proof feature 003 used
for two.

**[D] `standards.start` takes no payload.** `check.start` carries `{scope: "part"}`; there is
no scope here (section 1).

**[D] `NeverSaved` and `UnsupportedKind` are named refusals.** A document that has never been
saved has no path to match against the profile's library prefixes or its part-number pattern,
so the run is refused naming the document. The macro is silent in exactly this case, because
it decides document kind from the last three characters of a path that is empty (difference k).

## 3. Host to Standards page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}` |
| `document.changed` | `{path, configuration, kind} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}` |

Identical to the Model check page's table, including the two backend stages and why they are
here: a tab opened while the backend was starting was given a null endpoint in `init`, so
`status {stage: "ready"}` is its cue to re-send `ready` and take the endpoint from the fresh
`init`; the page re-asks only while it holds no endpoint, so the host's own end-of-extraction
`ready` does not re-initialise it in the middle of a check.

`kind` is what the page decides with. **[D]** The Model check page uses it to say whether a
check can run at all, because only a part can be model-checked; here **all three kinds can be
graded**, and the page uses `kind` to say *what* will be graded ("this drawing and the models
its views reference", "this assembly and everything under it") so the engineer is not
surprised by a drawing-rooted fan-out.

## 4. The run folder rule

Each check creates `<run_root>/<yyyyMMdd-HHmmss>-<doc>-standards` **[D]** through
`RunFolders`, the same helper the review, the terminal and the model check use, with the same
collision suffix. Two runs in the same second on the same document get different ids from that
suffix, so two records never share an id and the page always reads back the run it asked for.

```
package.json      the Standards-profile dump; extractor.profile == "standards"
exceptions.json   carried forward from the newest same-design run, before the checks run
session.json      the recorded tool steps, so tool_result_ids name steps that exist
report.md         the check-by-check result, headed by the verdict and the no-rebuild
                  sentence, with "Start here" as the section above Findings
attention.json    the ranking the report was rendered from, and the session id it
                  describes (feature 007 `contracts/attention.md` section 4). Not a
                  session file, and identical in shape to the one a model check writes
check.json        the record, carrying family: "standards"
```

**[D] The suffix is `-standards`, not `-check`.** Both are created by the same helper and both
sort beside the review they belong to.

**The newest-run scan is added by this feature; it does not exist today.**
`ModelCheckHost.LatestCheck` is in-process state - set by `TrackCheck`, nulled in `Dispose` -
and nothing in the add-in enumerates the run root, so a check cannot be read back after a
restart at all right now. FR-034, AS-17 and SC-009 require it, so this feature adds
`RunFolders.NewestCheckFolder(runRoot, suffix)` and calls it on `init` from `StandardsHost`
(`-standards`) and from `ModelCheckHost` (`-check`). Given that scan, the suffix is what lets
one enumeration answer for each host **from the folder names alone**; the `family` field in
`check.json` is how the **backend** answers a read by an id it was handed. Two mechanisms, two
questions. The alternative - one suffix and a `check.json` read per sibling folder on every
`init` - is rejected because `init` runs on every tab activation, and a name comparison is free
where a file read is not.

**The check folder is registered as the pane's latest run**, exactly as a model check folder
is, and for the same reason: the add-in points `CurrentSessionRunDirectory` and
`RunPackageIndex` at the latest session's run directory, and `entity.show` resolves
`document_id` to a path through the package in that folder. A check that wrote somewhere else
would silently degrade Show to "no full path" for every finding, and the Ask (Terminal) tab
would open in an unrelated folder. `SessionRecord`'s nullable chat id already lets the host's
"is any turn running" scan skip check records; a standards record is one of those.

**[D] The step strip treats a standards package as partial evidence** (FR-037): the evidence
step names standards-only evidence and offers **Extract full evidence** before Review; a
standards run folder is never suggested as the Extract tab's output folder; and a review handed
a standards package records a coverage item naming the phases the profile skipped. This is
feature 003's rule for its own reduced profile, **generalized over the profile name** rather
than restated for a second one, and the generalization is three named sites, not a convention:
`TaskPaneControl`'s `checkOnly` flag becomes "is a **reduced** profile" rather than
`== DumpProfile.ModelCheck` (one boolean, from which the Extract-output suppression falls out),
`StepStrip.CheckOnlyEvidence` becomes a per-profile sentence with the existing model-check
wording **byte-identical**, and `agent/runner.py`'s `record_partial_evidence` widens its
`profile != "model_check"` guard and names the skipped phases **from the package's own phase
rows** rather than from a second literal list of profile names. It is written in
`agent/runner.py` rather than on the `POST /sessions` route so the command line gets it too.

The two alternatives feature 003 rejected are rejected here for the same reasons: writing into
the existing latest run folder (the exception-accept command reads `session.json` **by name**,
so a rotated check session would be unreachable from the command line, and the check's
`package.json` would overwrite a review's full package), and one reusable scratch folder (it
destroys the previous check's evidence, which is exactly what an engineer compares against
after an edit).

Accepted downside, unchanged: one folder per check, and a check is pressed before every
release. No "keep the last N check folders" sweep is built in this version.

## 5. The Accept control

`ExceptionStore.accept` binds an exception to the check id, the graded **document**, its
component instances, the configuration and a fingerprint of every input the check read. The
binding is therefore **the document**, which means an accepted exception waives a check **on a
document**, never a check on one subject.

**Three named changes in `exceptions.py` make the drawing case work at all**, and they are
listed in `data-model.md` section 5 rather than assumed here: `fingerprint` gains a
document-scoped path (today it raises when there are no component ids), `accept` gains a
document-bound target, and **`match` takes and compares `document_id`** - without which two
drawings both yield empty bindings and one drawing's waiver would answer for every other
drawing, which is exactly what SC-008 forbids.

| Property | Value | Why |
|---|---|---|
| Label | **[D]** "Accept this check for this document" | The Model check label says "for this part"; a standards run grades parts, assemblies **and drawings**, and an engineer who waives `standards.drawing.dimensions_not_overridden` because of one legacy dimension must see that every dimension on that drawing is covered, for as long as the fingerprint holds |
| Note | Required; an empty note is refused by the route with `400 EmptyNote` | An empty note is how waivers rot |
| Warning-level checks | The control is **absent**, not disabled with a tooltip | FR-041 makes the two warning checks unacceptable. A disabled control invites a request to enable it; an absent one states the rule |
| Placement | On the check row, not on the subject line | The binding is the check and the document; putting the control on the subject line would state a granularity the store does not have |
| After acceptance | The check renders as checked within scope carrying the exception id and the note, and the **waived count appears on the headline** **[D]** | Never hidden, per Principle VI - and FR-032 requires a `ready` verdict reached with waivers to say so |
| A changed fingerprint | The finding stands and is labelled as needing re-review, naming the exception | Already the behaviour of the store; the page surfaces it rather than re-deciding it |
| **[D]** A drawing finding | Bound by `document_id` alone, because a drawing has no component instances | The additive `ReviewException.document_id` (FR-041) exists for this case; without it a drawing waiver would have no bindings at all, which is the blanket exclusion the constitution prohibits |

## 6. Every difference from `contracts/model-check.md`, in one list

| # | Model check | Standards | Why |
|---|---|---|---|
| D1 | `POST /checks/rms` with `{run_dir, scope, document_id}` | `POST /checks/standards` with `{run_dir, profile_path}` | No scope: all sixteen checks run on every run and the document kinds decide which apply. A profile path: the reasoning side owns the schema |
| D2 | Four error classes | Three more: `MissingStandardsPhases`, `ProfileUnreadable`, `ProfileInvalid` | A package without the standards phases and a profile that cannot be used are distinct, nameable refusals - not sixteen unresolved checks that read as a broken model |
| D3 | `grade` with counts, a fraction and unresolved ids | `verdict` with a state, counts in every bucket, a waived count, unresolved ids and `notes` | The release verdict is the product; the third state and the notes are what stop a clean headline claiming more than the run checked |
| D4 | The page derives its rule list from coverage rows | A required `checks[]` array of all sixteen with `worst_bucket` | A release gate must be able to say all sixteen were accounted for, from one array |
| D5 | Every subject gets a Show control | `subjects[].showable` decides | A data-card property, a note, a revision row and every drawing entity have nothing to select; a control that always fails is worse than none |
| D6 | (absent) | `rebuilt: false` in the payload and a sentence in the report header | The macro force-rebuilt; the counts here are as the documents stood and that must be said, not implied |
| D7 | `check.start {scope}` -> `check.extracted` | `standards.start {}` -> `standards.extracted` with cut-list and drawing counts | No scope; the counts name what the two new phases produced |
| D8 | Refuses `NoDocument`, `NotAttached`, `NotAPart` | Refuses `NoDocument`, `NotAttached`, `NeverSaved`, `UnsupportedKind`, `NoProfile` | Three kinds are gradable; an unsaved document has no path to match; the profile is checked before anything is created |
| D9 | `init` carries `document` and `latest_check` | plus `profile_path`, and `latest_check` filtered to `-standards` folders | The page shows which profile is in force; neither tab's latest check is ever the other's |
| D10 | Folder suffix `-check`; no family field | Folder suffix `-standards`; `check.json` carries `family`, optional with the default `"rms"` | Each host finds its own newest run without a file read; the backend answers a read by an id it was handed |
| D11 | `kind` tells the page whether a check can run | `kind` tells the page **what** will be graded | All three kinds are gradable; a drawing-rooted run fans out and the engineer should not be surprised by it |
| D12 | Accept label "for this part" | "for this document"; and a drawing exception is bound by `document_id` alone | Drawings are graded and have no component instances |
| D13 | The reduced profile's partial-evidence rule is stated for `model_check` | The same rule, **generalized over the profile name** | Two reduced profiles now exist; a rule written per profile name would need a third copy next time |

**`attention` is deliberately not a row.** Feature 007 adds the key to both result bodies and
the two blocks are byte-for-byte identical - the same `report/attention.rank` over each run's
own session, the same fields, the same order rule. A difference row for it would record a
difference that does not exist, and the next reader would go looking for it (feature 007
`contracts/attention.md` section 5). The same is true of `exceptions_carried_forward.reason`,
which both bodies have always carried and neither block wrote down until now.

## 7. The family's one check tool

One tool, offered for a standards run and nothing else, and documented **here** rather than
in feature 001's `contracts/agent-tools.md`.

| Tool | Arguments | Offered when | Returns |
|------|-----------|--------------|---------|
| `check_standards` | none | the tool context carries a standards run, which only `checks/standards/run.py` arranges | every graded document's checks: one finding per failing (check, document) naming its subjects, one aggregated coverage item per bucket, and the `standards.release` summary carrying the verdict and the counts |

**Why there is one at all.** `checks/rules/run.py` dispatches through `ToolRegistry` with a
`SessionSink`, so a finding's `tool_result_ids` names an investigation step that exists in
the session it cites. **One tool and not one per scope**, which is where the rms family
landed: its three scopes read different evidence and are selectable from the command line,
while all sixteen checks here run on every run and the document kinds decide which apply
(section 1, D1). It takes **no argument** for the same reason - there is no choice to offer.

**Why not a row in `agent-tools.md`.** That file's curated tables are asserted **set-equal**
to `registry.TOOL_FUNCTIONS`, which is built from `REGISTRATIONS` alone, and this tool is
registered outside `REGISTRATIONS` - exactly as feature 004's five re-modeler tools are,
which is why they are written down in `specs/004-resilient-remodeler/contracts/tools.md`
instead. **No row is added there and no curated count is bumped**, and
`reviewer/tests/unit/test_provider_schema.py` passes unedited,
`test_registered_tools_are_exactly_the_contract_tables` included. It follows that the tool is
in neither `MCP_TOOL_FUNCTIONS` nor the terminal profile's `enabled_tools`: a review, a
general-chat session and every other tab carry no standards run, so none of them can see it
(FR-035).

No provider is constructed and no API key is read when it runs, on this path or any other
standards path (FR-045).
