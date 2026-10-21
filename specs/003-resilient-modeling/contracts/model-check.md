# Model Check Tab: Routes, Messages, Run Folder, Accept

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), landed by 2026-09-27 (013 T052):* a Model check folder's `report.md` is opened by "Findings by type", in place of "Start here"; the Model check page's five-row preview is unchanged and never shows a pass; see 013 `contracts/grouped-list.md` sections 1 and 6 (lands with 013 T052). *Amended 2026-09-27 by feature 013 (T147-T150; default taken 2026-09-27, the owner may revise; 013 research R2.43):* `POST /checks/rms` takes an optional `standards_profile` and the `CheckResult` then carries `bought_parts`, the root rule's label when the open part looks bought (sections 1 and 2).

The contract for User Story 6 (spec FR-022 to FR-033): the three backend routes the Model
check page calls, the two message tables between that page and `ModelCheckHost`, the check run
folder, and what the Accept control means. Tab 4 is Model check; feature 004's Remodel tab is
tab 5.

Everything here reuses the existing backend rules rather than restating them: the loopback
bind, the `Authorization: Bearer <token>` header on every request, the 401 on a missing or
wrong token, the `OPTIONS` preflight answered without a token, the exact virtual-host origin
echoed in `Access-Control-Allow-Origin` with a 403 for any other `Origin`, the `run_dir` path
rule (canonicalize, reject UNC and device paths, require a descendant of `--run-root`,
otherwise 400 `InvalidRunDir`), and the error body `{error_class, message, retryable}` with the
message redacted of any configured key.

The page calls these routes **itself**, with the token and origin it received in `init`, the
same way it already calls the message, evidence, disposition and event routes. The host does
the `POST /sessions` call for a review only because it must bind the run folder to a chat id it
tracks; a check has no chat. Keeping a potentially large result off the `postMessage` channel is
a secondary benefit.

The three route rows are added to feature 002's `contracts/chat-api.md` by T073, and the tab-4
message rows to feature 002's `contracts/pane-host-messages.md` by T085; this file is the
normative source for both.

## 1. Routes

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/checks/rms` | `{run_dir, scope: "part" \| "equations" \| "all", document_id: str \| null, standards_profile?: str \| null}` (`standards_profile` since feature 013 T148; below) | `201 CheckResult` (below). 400 when `run_dir` fails the path rule, when `run_dir/package.json` is missing or invalid, or when the package's `features` array is empty (`error_class: "EmptyFeatureTree"`); 400 with `error_class: "UnreadableExceptions"` when the carry-forward candidate exists and cannot be parsed. Runs synchronously: there is no provider, no network call and no turn. |
| GET | `/checks/{check_id}` | | `200 CheckResult` re-read from that check's run folder; 404 when no such check folder is under the run root. |
| POST | `/checks/{check_id}/exceptions/{finding_id}` | `{note, by}` | `200 {finding, exception_id}` with the finding re-rendered as checked within scope carrying the exception id; `400 EmptyNote` when the note is blank; `404` for an unknown check or finding; `409 RuleNotAcceptable` when the finding's rule severity is `warn` (FR-016); `409 AlreadyAccepted` when an active exception with the same bindings and check already exists. Re-renders `report.md`. |

`check_id` is the check run folder's name (`<yyyyMMdd-HHmmss>-<doc>-check`), so a check is
addressable after a restart without any server-side registry, and `GET` resolves it under the
configured run root through the same path rule the `run_dir` body field goes through.

`standards_profile` (*amended 2026-09-27, feature 013 T147-T150; FR-008, US1 scenario 6*) is the
path of the standards profile the Review tab uses (`UserSettings.StandardsProfilePath`), which the
host hands the page in `init` (section 2) and the page relays. Absent, null or blank, the body is
byte for byte what it was, with no `bought_parts` key; any other value that is not a string is a
400 naming the field. With a path, the backend loads it through the review's own loader
(`load_review_profile`, which never raises), classifies the dump's documents with the one
classifier (`checks/part_roles.classify_parts`), and the body carries **`bought_parts`**: the
part-roles sentence (`bought_parts_sentence`) - for the check's one part, the package's root and
the document under review, the root rule's clause "{file} looks bought ({reason}); graded because
it is the document under review" when the rules call it bought, the refusal's sentence naming no
path when the profile is refused ("Bought parts were not told apart: the standards profile was
refused (...)"), and null when there is nothing to say. The page prints it verbatim. The rules,
the findings and the grade do not move: the open part is always graded. `check.json` records the
path and the sentence (only when a profile was given, so a check without one writes the record it
always wrote), so `GET /checks/{check_id}` answers the line the POST did and an Accept re-grades
against the profile the check was graded with. No profile value and no path is in the body.

`scope` is one of `"part"`, `"equations"` and `"all"` - the three the route offers, as
`OFFERED_SCOPES` in `chat/server.py` names them; `"all"` means every offered family and not
every family in the catalogue. `"assembly"` is not offered by the tab until the assembly
rules have landed and been calibrated; a request naming it is answered 400 with
`error_class: "ScopeNotAvailable"` rather than silently evaluating nothing, and `"all"`
does not run it by alias. (The sentence used to read "`scope` is `"part"` in this
increment", which stopped being true when the equations family landed; feature 007 research
R3 named the drift and this is the correction.)

### `CheckResult`

```jsonc
{
  "check_id": "20260916-101532-bracket-check",
  "run_dir": "<run_root>/20260916-101532-bracket-check",
  "document": {"id": "doc:ab12", "path": "...", "configuration": "Default", "kind": "part"},
  "extracted_at": "2026-09-16T10:15:32Z",
  "profile": "model_check",
  "grade": {
    "failed": 3, "warned": 1, "checked": 22, "skipped": 4,
    "unresolved": 4, "out_of_scope": 6,
    "fraction": 0.81,
    "unresolved_rule_ids": ["rms.refs.direction", "..."]
  },
  "findings": [
    {
      "finding": { /* the Finding, contract unchanged from feature 001 */ },
      "rule_id": "rms.detail.holes_last",
      "severity": "fail",
      "statement": "Holes are the last features in the Detail group.",
      "observed": "...",
      "acceptable": true,
      "exception": {"id": "EX-001", "state": "active", "note": "..."}
    }
  ],
  "coverage": [
    {"bucket": "unresolved", "check": "rms.refs.direction",
     "scope": {"component_ids": ["cmp:0003"], "pairs": [], "configuration": "Default",
               "positions": [], "document_ids": ["doc:ab12"]},
     "reason": "reference directions are not in the evidence package", "error": null}
  ],
  "subjects": {
    "<finding_id>": [
      {"feature_id": "feat:0007", "name": "Cut-Extrude1", "type_name": "ICE",
       "group": "4-Detail", "persist_ref": "<base64>", "persist_ref_scope": "doc:ab12",
       "component_ids": ["cmp:0003", "cmp:0009"]}
    ]
  },
  "exceptions_carried_forward": {"from_run": "20260915-173001-bracket-check", "count": 2,
                                 "reason": null},
  "attention": { /* the Ranking of feature 007 `contracts/attention.md` section 4,
                    minus session_id: policy_version, rows, top_n, not_amplified,
                    coverage, empty_reason */ },
  "not_examined": null,  /* or {"sentence": "...", "headline": "...", "instances": [{"id":
                            "cmp:0002", "name": "DOWEL PIN", "state": "lightweight"}, ...]} */
  "rule_statements": {"rms.refs.direction": "Reference geometry follows the method's axes and planes.",
                      "rms.detail.holes_last": "Holes are the last features in the Detail group."},
  "bought_parts": "bracket.SLDPRT looks bought (a vendor property); graded because it is the document under review"
                  /* only when the request named a standards_profile; null when there is nothing
                     to say (feature 013 T148) */
}
```

Six points the shape exists to enforce:

- `grade` never carries a letter, and `fraction` is never the only number rendered. The
  unresolved rule ids travel with the counts so a page cannot show a score without them.
- `subjects` is keyed by finding id and lives **beside** the findings, not inside the `Finding`,
  so the feature 001 finding contract is unchanged. The same subject also appears as a source
  reference on the finding itself (`document_id` = the subject's persist-ref scope,
  `persist_ref` = the subject's reference), which is what makes Show work in the Review page as
  well. The page never parses a display string.
- `acceptable` is the rule's severity expressed for the button: `true` only for `fail` rules.
  `exception` is present only when one matched, and carries `active` or `needs_review`.
- A coverage item is the session's `CoverageItem` with its bucket in front of it, exactly as
  `coverage_rows` in `checks/rms/run.py` emits it, so the documents it covers are in its
  **`scope`** and not at the top level. `document` is null whenever the run graded more than
  one document, so a page that read the ids anywhere else would lose every coverage row in a
  multi-document check and show a grade counting rules it was no longer listing.
- `exceptions_carried_forward` carries a third field, **`reason`**: `null` when a store was
  carried, and the sentence saying why not - "no earlier run of this design", or "the folder
  already carries this check's own evidence" on a re-read - when none was. It has been in
  the payload since the route landed and was missing from this block; feature 007 research
  R3 named the drift and this is the correction. A count of zero with no reason beside it
  reads as a failure rather than as the ordinary first run of a design.
- `not_examined` is the lightweight warning of 2026-09-19 (`docs/feature-request-resolve-lightweight.md`): `null` when every component instance was read, otherwise one sentence naming each instance the extractor did not read with its recorded state (`lightweight`, `suppressed`, `unloaded`) and the families that therefore cannot see it, plus the instances behind it in package order. Composed by `reviewer/src/swreview/report/unexamined.py`, the same module that writes the report's `- Not examined:` Summary line, and identical on the Standards body. The page shows the sentence above "Start here" and computes nothing from it.
- `rule_statements` (feature 009 T064, FR-028) maps every rule the grade names - in its
  findings and its coverage rows, each once, first named first - to its `RULES` statement;
  an id the catalogue lacks is absent. The page's grade header prints "Not graded, evidence
  missing:" and each unresolved rule's statement, with the ids behind a fold, instead of the
  fraction line and the id list; `grade.fraction` and the report are unchanged. The
  `StandardsResult` carries no such key. `not_examined` gained `headline` (names, no ids)
  beside `sentence` in the same feature (T013).
- `attention` is feature 007's ranking of **this run's own session**, computed by
  `report/attention.rank` and carried so the tab can render the rows it should read first
  without computing an order of its own (feature 007 FR-022, FR-023). It is the
  `attention.json` block minus `session_id` - the body already names the check - and it is
  **identical to the `StandardsResult`'s**, which is why feature 006's difference table
  adds no row for it. It is present on the POST, on the `GET /checks/{check_id}` re-read
  (recomputed in memory, byte-equal to the POST's, and the folder including
  `attention.json` is not written by the read) and after an Accept, whose re-run of the
  check rewrites the record through the entry point. No path that produces it constructs a
  provider or reads a key.

## 2. Model check page to host

| type | payload | host action |
|------|---------|-------------|
| `ready` | `{}` | Reply `init` `{backend: {port, origin}, token, backend_start_failed: boolean, run_root, standards_profile: str \| null, document: {path, configuration, kind} \| null, latest_check: {run_dir, at} \| null}`. `standards_profile` (feature 013 T150) is the configured `StandardsProfilePath` - the Review tab's own setting, read fresh - or null when it is blank: a path, never a value; the page relays it on `POST /checks/rms` (section 1) and prints the body's `bought_parts` verbatim above the ranked rows. *Amended 2026-10-21 (feature 002, owner decision 160A):* `init` also carries `backend_start_failed: boolean`, true only while no backend is up and none is being started, after the last start or restart - the add-in's first or a save's - failed: false before the first start, while one is under way, and while a backend is up - the old one, too, when a restart failed before it stopped it. It is the review host's word, handed to this host by the add-in, and an `init` that names a backend never says it. A page that loads, or loads again, after the failure's `status`, which it never saw, and is told `true` says "Backend not running" on its strip, where it said "Backend starting", and, when its banner says nothing else, "The backend is not running. Save Settings on the Review tab to start it again." as the add-in's word on the backend (`lifecycle`), which an `init` that names a backend takes down; one that names none and says `false` leaves the page as it was told. |
| `check.start` | `{scope: "part"}` | Refuse with `error {error_class: "NoDocument"}`, `"NotAttached"`, or `"NotAPart"` as applicable. Otherwise create the check run folder, run the `ModelCheck` profile dump in process, register the folder as the pane's latest run, and reply `check.extracted {run_dir, document, configuration, counts: {documents, features, equations}, gaps}`. Progress via `status`. The host stops here: the page calls `POST /checks/rms` itself. *Amended 2026-10-20 (feature 002, owner decision 154A):* refused first, before every other refusal, `RunRootRefused`, not retryable, when the run root is on a network share, reached through a link or written as a device path, or could not be checked, in words the page prints whole - what the root is, that nothing was checked, and the way on, a local folder chosen for runs in the Review tab's Settings, and Model check pressed again - with no path; no check folder is made and nothing is extracted (002 `pane-host-messages.md`, "The run root rule"). *Amended 2026-10-21 (feature 002, owner decision 154A, with 153A's record of the settings in force):* refused first, before the run root is judged, `BackendUnavailable`, retryable, while a start of the backend under way would bring another run root into force, in words the page prints whole - the review backend is being started with another folder for runs, nothing was checked, and Model check pressed again in a moment - with nothing made; the run root is read once, so the one judged is the one the check folder is made under (002 `pane-host-messages.md`, "The run root rule"). *Amended on the reviews of owner decision 154A's merge (feature 002), 2026-10-21:* the run root is read again once the extraction is over, and a check whose folder it no longer holds is answered `RunRootChanged`, not retryable, in words the page prints whole - the run root changed while the feature tree was read, nothing was checked, Model check pressed again - or, while a start that would bring another in is under way, `BackendUnavailable`, retryable, rather than `check.extracted`; the folder is left and not registered (N6). A start refused for the run root in force while another folder chosen for runs is not in force is `RunRootChosenNotInForce`, whose way on is to save the settings again on the Review tab to retry the restart (N4; 002 `pane-host-messages.md`, "The run root rule"). |
| `entity.show` | `{persist_ref, persist_ref_scope, component_id}` | **Identical to the Review page's row**, delegated to `PaneActions`; reply `entity.shown {ok, state_code, message, full_path \| null}`. |
| `report.open` | `{run_id}` | Delegated to `PaneActions`; the path comes from the host's own record, never from the page. |
| `folder.open` | `{run_id}` | Delegated to `PaneActions`. |
| `log.open` | `{}` | Delegated to `PaneActions`. |

The last four rows are the reason `PaneActions` is extracted: they already exist in
`ReviewHost` with run-root containment and redaction, and a second host that copies them is the
duplication this feature would be judged on. Their tests are parameterized over both hosts so
the rows are proven identical rather than assumed.

## 3. Host to Model check page (unsolicited)

| type | payload |
|------|---------|
| `status` | `{stage: "extracting" \| "backend_starting" \| "ready" \| "error", message}`. *Amended 2026-10-19 (feature 002, owner decision 145A, found on review):* `error` also when a settings restart failed once the old backend had stopped, with the failure, masked, as a failed first start is told: no backend answers the token of the page's last `init`. *Amended on the third review the same day:* the add-in marks its own word on the backend - `backend_starting`, `ready`, and `error` for a failed start or restart - `lifecycle: true`, and the page takes down a banner it put up for such an `error` once a later `init` names a backend; no other banner *Amended 2026-10-20 (feature 002, owner decision 150A):* from such an `error` the page's backend strip says "Backend not running" until an `init` names a backend - through an `init` that names none, and whatever banner is put up meanwhile - where it followed `init` alone and said "Backend ready" under that banner; any other `error` leaves the strip as it was *Amended on the 150A review, 2026-10-20 (feature 002, owner decision 150A):* the add-in's `error` - a first start that failed, or a settings restart that failed once the old backend had stopped - ends with the way on, "Save Settings on the Review tab to start it again.": the failure is followed by a full stop when it does not end in one, then that sentence |
| `document.changed` | `{path, configuration, kind} \| null` when the active document changes |
| `backend.stopped` | `{exit_code, log_path}`. *Amended 2026-10-20 (feature 002, owner decision 150A):* the page says "The backend stopped. Save Settings on the Review tab to start it again.": the add-in starts the backend when it loads and a settings save, made on the Review tab, restarts it, so reopening the pane, which the sentence named before, starts nothing. No host posts it |
| `backend.restarted` | `{sentences}` - *added 2026-10-19 (feature 002, owner decision 145A):* the add-in restarted the backend with saved settings, a save's restart made at once or one made after it waited (feature 002 `pane-host-messages.md`, `settings.save`). `sentences` is empty: the Review tab's sentences about a restart that waited are shown there alone |

`kind` is what the page decides with - the Model check reads a part's feature tree, so the tab
says whether a check can run at all instead of offering a button the host will refuse.

`backend.restarted` is here for the reason the two backend stages are: the restarted backend
listens on another port with another token, and refuses the token of the page's last `init`. The
page sends `ready` again - once more after an `init` already on its way, which the host may have
read before the new backend was up - and takes the new port and token from the `init`. It keeps
the check on screen: it does not read its latest check again, since the restart changed the
backend and not the check, and a call already made with the old token is not made again.
*Amended 2026-10-19 (feature 002, owner decision 145A, found on review):* a call the page makes
while such an `init` is on its way waits for it - and for the one more ask after it - and carries
the token it leaves: the host answers that `ready` on this tab's pump, behind an extraction already
running there, so a check pressed as the backend restarted reaches its route only once the page
holds the new token, and its extraction is not wasted. And a latest check the page could not read,
the backend having refused the token as the one a restart replaced does, is read again by the next
`init`, a restart's included, so a tab opened during a restart does not stay blank. *Amended on the
third review the same day:* it is read again until it is read, or until a check is pressed, and a
read still out when a check is pressed is neither shown nor remembered. A call waits for an `init`
on its way whether that `init` is applied or refused. An Accept's re-read of its check is shown only
while that check is the one on screen: a newer check shown first, its call let go with the Accept's
since both waited for the same `init`, is not covered by the older check. *Amended 2026-10-20
(feature 002, owner decision 150A):* a re-read not shown is said in the banner, as a re-read that
failed is, with the exception the Accept wrote: "Accepted as {exception_id}, and the exception is saved; a newer check was pressed before this check was re-read. Press the check again to see where it stands."

The two backend stages are here because this page calls the check routes itself. A tab opened
while the backend was starting was given a null endpoint in `init`, so `status {stage: "ready"}`
is its cue to re-send `ready` and take the endpoint from the fresh `init`; the page re-asks only
while it holds no endpoint, so the host's own end-of-extraction `ready` does not re-initialise
it in the middle of a check.

## 4. The run folder rule

Each check creates `<run_root>/<yyyyMMdd-HHmmss>-<doc>-check` through `RunFolders`, the same
helper the review and the terminal use, with the same collision suffix. The `-check` suffix
means the folders sort beside the review they belong to and are obviously disposable.
*Amended 2026-10-20 (feature 011, owner decision 148A; its research R12.3 and R12.8):* the folder,
the collision suffix's too, is made in its full form - named under `Path.GetFullPath` of the run
root, whatever spelling the setting holds - and `RunFolders.NewestCheckFolder` answers in the same
form, so a folder made is spelled as the same folder found.

```
package.json      the ModelCheck-profile dump; extractor.profile == "model_check"
exceptions.json   carried forward from the newest same-design run, before the rules run
session.json      the recorded tool steps, so tool_result_ids name steps that exist
report.md         the rule-by-rule result, opened by the "Start here" section
                  ("Findings by type" since feature 013 T052)
attention.json    the ranking the report was rendered from, and the session id it
                  describes (feature 007 `contracts/attention.md` section 4). Not a
                  session file: a folder holding only this one is not "a folder that
                  already holds a review"
check.json        the check record, carrying family: "rms"
```

`check.json` now carries a **`family`** field, written first and `"rms"` for these runs, so a
backend handed a run folder knows whose check it is holding before it answers a read of it; a
record written before the field existed is read as `"rms"` too, which is why the default is
named rather than the folder refused (feature 006
`specs/006-standards-check/contracts/standards-check.md` section 1 and D10).

**The check folder is registered as the pane's latest run.** The add-in points
`CurrentSessionRunDirectory` and `RunPackageIndex` at the latest session's run directory, and
`entity.show` resolves `document_id` to a path through the package in that folder. A check that
wrote somewhere else would silently degrade Show to "no full path" for every finding, and the
Ask (Terminal) tab would open in an unrelated folder. So `RunFolders.CreateForCheck` registers
it, and `SessionRecord` gains a nullable chat id (or an `IsCheck` flag) so the host's
"is any turn running" scan skips check records instead of asking the backend about a chat id
that does not exist. That scan currently swallows the exception, so a fake id would appear to
work, at the cost of one HTTP round trip per settings save and a record that lies. It is made
explicit instead.

Two alternatives are rejected and the reasons belong in the contract, because both look
cheaper: writing into the existing latest run folder (the exception-accept command reads
`session.json` **by name**, so a rotated check session would be unreachable from the command
line, and the check's `package.json` would overwrite a review's full package), and one reusable
`<run_root>/model-check` scratch folder (it destroys the previous check's evidence, which is
exactly what an engineer compares against after an edit).

Accepted downside: one folder per check, and a check is pressed after every edit. No "keep the
last N check folders" sweep is built in this version.

## 5. The Accept button

`ExceptionStore.accept` binds an exception to the check (the rule id), the part's component
instances, the configuration, and a feature-tree fingerprint. The binding is therefore **the
document's instances**, which means an accepted exception waives a rule **on a part**, never a
rule on one feature. That is correct for the method, because a rule statement is about the tree
and not about one feature, but it is not what an engineer will assume from a button sitting on a
per-feature line.

| Property | Value | Why |
|---|---|---|
| Label | "Accept this rule for this part" | An engineer who waives `rms.detail.holes_last` because of one legacy hole must see that every hole in that part is covered, for as long as the fingerprint holds. |
| Note | Required; an empty note is refused by the route with `400 EmptyNote` | An empty note is how waivers rot. |
| Warning-level rules | The button is **absent**, not disabled with a tooltip | FR-016 makes `warn` rules unacceptable. A disabled control invites a request to enable it; an absent one states the rule. |
| Placement | On the rule row, not on the subject line | The binding is the rule and the part; putting the control on the subject line would state a granularity the store does not have. |
| After acceptance | The rule renders as checked within scope carrying the exception id and the note | Never hidden, per Principle VI. |
| A changed fingerprint | The finding stands and is labelled as needing re-review, naming the exception | Already the behavior of the store; the page surfaces it rather than re-deciding it. |

*Amended 2026-10-21 (feature 002, owner decision 160A):* `check.start` refuses a run root no folder can be made
under - a character no folder can have, or a folder name longer than 255 characters - as it refuses every run root
the rule refuses, before anything is made or extracted; and the check's run folder is made, and the newest check
found, under the run root's long-name form (002 [pane-host-messages.md](../../002-task-pane-assistant/contracts/pane-host-messages.md),
"The run root rule").
