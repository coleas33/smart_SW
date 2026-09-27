# Research: Engineer-First Review

**Feature**: `013-engineer-first-review` | **Date**: 2026-09-26 | **Plan**: [plan.md](plan.md)

Phase 0 output from: the 2026-09-26 sitting on the pilot workstation, the first on the checks-first
build (features 008 to 011 at `9edc36c`); its debrief, which is held outside the repository because
it carries company data (F1 to F8, U17 to U24), and from which nothing is copied; and six analysts'
reports of the same day, which read the sitting's run folders, logs and notes against the code. Their
causes are cited here at file and line. The seat ran `9edc36c`; `main` at `111bc82`, where this
package was written, differs from it in one test file only, so every line number below is the code
the seat ran. Line numbers drift; every task re-verifies before editing.

The owner asked on 2026-09-26 to proceed without questions unless blocked. Every question the
analysts raised is therefore settled by a default, recorded in R2 as **default taken 2026-09-26, the
owner may revise**. None of them is the owner's own words, and each can be changed by editing this
section and the one contract that carries it.

Parts are named by role (a vendor dowel pin, the custom plate, the small assembly); every example
value in this package is fictional (`FICT-`).

---

## R1. Sources and what is normative

| Source | What it is | Authority here |
|---|---|---|
| `spec.md` | Seven user stories, FR-001 to FR-055, SC-001 to SC-010 | Normative for what is built |
| The sitting's debrief (outside the repository) | The engineer's findings F1 to F8 and the update table U17 to U24 | Why; nothing is copied from it |
| Analyst "run evidence" | The review run turn by turn: tokens per round, the eight questions, the follow-up, Start here, the vendor part's signals | Causes of U17 to U21 and the token items |
| Analyst "U17 design" | Custom versus bought parts: profile version 4, one classifier, its consumers, one question | U17's design |
| Analyst "U18 and U21 design" | The grouped findings list; source labels; the answer basis; the explanation fallback | U18's and U21's design |
| Analyst "U19 and U20 design" | Provenance closed by code; the re-ask guard; the ping capability; drawing states | U19's and U20's design |
| Analyst "logs, runs and U24" | Logs clean; the revision-table miss; the doubled tree rows; the explanation pass; the probe 1 race | The readings (US7) and the test debt |
| Analyst "remodel scope" | Feature 004's lanes and T167 | **Out of this package** (below) |
| The defaults of 2026-09-26 | One default per analyst question | R2; each revisable by the owner |
| The constitution 1.1.0 | Principles I to VI, the read-only rule | The gate; this feature adds no exception |

**Out of this package.** The remodeler defaults of the same day - T167's teardown, T157 with T167,
the Start switch, planning again while a plan waits, `GetVault` answering null, T135's Part A - are
feature 004's. They are not recorded here, and `specs/004-resilient-remodeler/` is not touched. The
probe 1 watchdog (U24) is in scope as test debt in its C# code only (R2.41); the 004 task text that
mentions it (T033) is left for 004's own next edit, and nothing in this package contradicts it.
*Added 2026-09-26, after this package:* that edit has been made: 004 T171 and the amended 004 T033
carry the watchdog default (004 research R13.7), the same change as 013 T135 to T137, built once; no
task of 013 edits a 004 document.

---

## R2. Decisions (defaults taken 2026-09-26)

Each entry: the decision, the default tag, why, and the alternatives the analysts weighed.

### U17: custom and bought parts

#### R2.1 Profile version 4 with a `part_roles` section

**Decision**: the standards profile goes to version 4 with one new required section, `part_roles`:
`bought_prefixes` (folder or file prefixes, relative to `vault_root` or absolute, matched by the
existing prefix rules), `purchased_property` and `purchased_values` (a property that marks a part
purchased, and the values that mean so), and `bought_name_patterns` (vendor catalogue name patterns).
Name patterns use `part_number.pattern`'s vocabulary (`#` a digit, `?` any one character, all else
literal, whole file name with extension, case-insensitive) extended with `@` (one letter) and `*`
(any run, empty included). Versions 1 to 3 stay valid. (`contracts/part-roles-profile.md`.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: the loader requires every key, refuses unknown keys and has no defaults
(`checks/standards/profile.py:283-336`), so a key added to version 3 would either refuse the owner's
real version 3 file or need a default; a new version keeps that file loading. The real version 3
profile cannot express "bought": its library skip list does not cover the vendor pin (it is on the
sketch-exempt and two-mate lists only), its part-number pattern has no literal to tell the company's
own prefix, and the vendor pin carries a company part-number property as well
(`checks/standards/library.py:75-113`; offline probe of the analysts). One vocabulary, extended by two
letters, keeps one matcher and no regular-expression pitfalls.

**Alternatives**: a key under version 3 (refused by the loader's rules, or a silent default);
regular expressions for vendor names (a second matcher, and a syntax the owner does not write today);
a separate `custom_name_patterns` list (not needed: the part-number pattern already says custom, and
a second list could disagree with it).

**Revised 2026-09-26, before any code** (the owner's guidance and the census, R2.4 "Revised"): the
section names every signal the census found, not three bought rules - `bought_prefixes` and
`bought_folder_names`; the make-or-buy `switch` (property, bought values, custom values);
`vendor_properties`; `distributor_block` (properties and `min_valued`); `catalogue_numbers` (shapes
and the properties whose values they are tested on); `custom_prefixes` and `bought_number_prefixes`;
`detail_properties` (`contracts/part-roles-profile.md` section 1). `purchased_property`,
`purchased_values` and `bought_name_patterns` are gone: the switch replaces the first two and reads
both of its values, and the catalogue shapes replace the name patterns and are tested on tokens,
configuration names and property values rather than on the whole file name. The one matcher and its
vocabulary are unchanged. The owner's words ask for the custom prefix, so a `custom_prefixes` list is
added after all; it narrows the part-number pattern rather than competing with it (a file name counts
only when it follows the pattern).

#### R2.2 The upgrade helper proposes, the owner confirms

**Decision**: `swreview profile upgrade <in> --out <out>` writes a proposed version 4 profile from a
version 3 file, never over its input: the new `part_roles` section with empty lists, and the
library skip list's entries copied under `bought_prefixes` as **commented** lines, marked as a
proposal to confirm. It validates what it writes. It prints no profile value to the console. A
version 1 or 2 file is refused naming the sections it lacks.

**Default taken 2026-09-26, the owner may revise.** Refusing a version 1 or 2 file is this plan's
reading of the default (stated on review, 2026-09-26): version 4 is version 3 plus one section, so
the helper would otherwise have to invent the drawing and general-tolerance values the owner has
not written (`contracts/part-roles-profile.md` section 5). The owner's seat profile and the shipped
example are version 3.

**Why**: the owner already writes the profile by hand on the seat; a helper that writes the section
saves typing without deciding anything. The skip list means "Standards skips this", not "bought"
(R2.5), so it can only be offered, never applied.

**Alternatives**: no helper (the owner writes the section from the contract); a helper that
pre-fills live entries (it would decide what is bought from a list that means something else).

#### R2.3 One pure classifier

**Decision**: one pure function, `checks/part_roles.classify_parts(package, profile, answers)`,
classifies every part and assembly document as custom, bought or unclear, each with the rule that
decided it and a reason in words that never quote a profile value (feature 006 FR-034: the words reach
the model provider). It is computed once per review, attached to the review's context before the
carry-over and the pre-run, and read by every consumer. (`contracts/part-roles.md`.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: nothing in the code tells a bought part from a custom one today; the RMS part and equation
grading select every part document (`tools/rms_checks.py:253-269`), hygiene grades every reached
model (`checks/hygiene.py:309-315`), and only the Standards checks read the library prefixes
(`checks/standards/part.py:233`, `checks/standards/document.py:241`). One function, one reading.

**Alternatives**: a flag on each finding (an "is bought" test in every renderer); letting each
check filter on its own (several readings that can disagree).

#### R2.4 The signals, and their order

**Decision**, first match wins (`contracts/part-roles.md` section 2): the engineer's answer to the
part-roles question in this session; Toolbox (bought); a bought prefix (bought); the purchased
property holding a purchased value (bought); a vendor pattern together with the part-number
convention (unclear); a vendor pattern (bought); the part-number convention (custom); a same-name
drawing beside it (custom, reason shown); inside a bought assembly (bought); otherwise unclear.

**Default taken 2026-09-26, the owner may revise.** The last-but-one rule (inside a bought assembly)
is this plan's addition for an edge the defaults did not name: a vendor sub-assembly's children
follow no company rule and would otherwise all be asked about. It sits after the custom rules, so a
part that follows the convention inside a vendor assembly stays custom.

**Why this order**: a path and a property are the company's own filing, the strongest evidence; a
name pattern is weaker, so a vendor pattern that also matches the company convention is a conflict
worth asking about. The same-name drawing rule turns the engineer's "drawings only exist for custom
parts" into code. The folder winning over the convention is noted in the reason ("although its name
follows the part-number convention"), so a misfiled custom part is visible.

**Alternatives**: the convention winning over a folder (a vendor file renamed to a company number
would be graded); every conflict unclear (more questions for the common case of a library part
carrying a company number, which the sitting's pin does).

**Revised 2026-09-26, before any code: votes with strengths replace the first-match table.** From
the owner's guidance of the same day - "The custom properties should also hint at whether the part is
custom or [bought off the shelf]; the purchased vs built switch can be flipped by the user; also look for part numbers,
vendors, etc. Custom parts usually have little detail: the custom-prefix file name or the
custom-prefix part number." - and a census of every recorded package on the development machine
(33 part and assembly documents after de-duplication by path, 14 carrying the custom prefix; the
census and its values stay outside the repository, and only its generic findings are recorded here):

- the make-or-buy switch's **bought** value is set on purpose, written at the document and the
  configuration level: **strong** bought evidence. Its **custom** value behaves like the part
  template's default, written at document level only, and was visibly wrong on 2 of 16 documents:
  **weak** custom evidence. A skeptical re-count showed that counting it strong would have called 6
  of 15 bought documents custom without asking once they were moved out of the library, which is why
  it is weak;
- part-number ranges outside the custom prefixes appear on bought documents: a profile list of
  **bought number prefixes**, **medium** bought evidence;
- vendor-type properties carrying a value, and a distributor-download block of properties, appear
  only on bought documents: **strong** bought evidence;
- catalogue-number shapes in file-name tokens, configuration names and property values: **medium**
  bought evidence. The census found most of its shapes fitted to one document each, so the owner's
  profile keeps only general shapes, and a shape made only of wildcards is refused;
- the custom prefix in the file name or the part-number property: **medium** custom evidence (the
  part-number pattern alone is not: bought documents carry the same shape in their part-number
  property);
- sparse properties (no vendor or catalogue detail) and a same-name drawing: **weak** custom
  evidence; a missing drawing is no evidence;
- a child of a bought assembly inherits bought unless its own evidence says custom;
- property names must be compared ignoring case **and** spaces: real files spell the part-number
  property both with and without its space, and the hygiene checks had missed it;
- the decision: an answer decides; strong votes that all agree, with no medium vote against, win;
  strong votes that conflict are unclear and asked; with no strong vote a role needs two agreeing
  votes, at least one of them medium, and none against; with no votes the part is unclear;
- a document that was never read (lightweight or suppressed) is decided only from its path, name,
  configurations and Toolbox, and says so.

The strengths are fixed in `contracts/part-roles.md` section 2.1, not in the profile: the owner names
what each signal looks for, and the evidence's weight is this feature's decision, tested once. Every
company value lives in the owner's `part_roles` section. The census's own tally under its first
draft, where the custom value was strong, was 14 custom, 16 bought and 3 unclear; with the custom
value weak, as decided here, its two switch conflicts (a vendor sub-assembly and a gearbox, both in a
bought folder, both carrying the template's custom value) resolve to bought. T018's local validation
(uncommitted; the owner's draft merged into a copy of the real profile, the 27 recorded packages,
documents de-duplicated by path, a read occurrence preferred) gives **14 custom, 18 bought, 1
unclear** - the unclear one is the part that was never read and carries no signal; the same run with
the custom value strong reproduces the census's 14, 16 and 3, and without the bought folder name its
14, 14 and 5. One custom-prefixed part is read in some packages and not in others: read, it is
custom; unread, its file name is one medium vote and it is asked. The version 1 to 3 rule (R2.5) and the no-profile rule (R2.6) are unchanged.

#### R2.5 Version 1 to 3 profiles: the convention, Toolbox, then ask

**Decision**: with a version 1 to 3 profile, a document that follows `part_number.pattern` is custom,
a Toolbox document is bought, and every other one is unclear and asked about. `library.skip_prefixes`
is never read as bought. An empty pattern makes the state `absent` (R2.6). So the same-name drawing
rule and the bought-assembly rule of R2.4 are not in force with a version 1 to 3 profile
(`contracts/part-roles.md` section 1, state `convention_only`: rules A, B, G and J); stated on
review, 2026-09-26, where the contract had run them too.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the skip list's meaning is "Standards skips this" (feature 006 `contracts/profile.md`,
"Prefix semantics"); coupling a second rule to it would change what the owner's list does. An empty
pattern gives no convention, and a question listing every part is noise.

**Alternatives**: treat the skip list as bought (couples two rules, and misses the sitting's pin
anyway); with an empty pattern, ask about everything.

#### R2.6 No profile: only Toolbox, and nothing asked

**Decision**: with no profile, or an unreadable or invalid one, only Toolbox parts are skipped, no
question is asked, and the bought-parts line says bought parts were not told apart and why. The four
existing standards refusal reasons are unchanged.

**Default taken 2026-09-26, the owner may revise.**

**Why**: without a convention the question would list every part.

**Alternatives**: ask about every non-Toolbox part; grade everything including Toolbox.

#### R2.7 The reviewed document is always graded

**Decision**: the root document is always graded; when the rules say bought, it carries the label
"looks bought ({reason}); graded because it is the document under review". The Model check tab's open
part is its root, so it follows with no change.

**Default taken 2026-09-26, the owner may revise.**

**Why**: an engineer who reviews a document wants it graded; the rule also removes the "zero
documents graded" edge and any Model check change.

**Alternatives**: skip a bought root (a review that grades nothing and says so).

#### R2.8 Modelling practice and hygiene grade custom and unclear parts only

**Decision**: RMS part and equation rules and the four hygiene property checks (part number matches
file, duplicate description, duplicate part number, revision present) grade custom and unclear
documents; duplicates compare graded documents with each other only. Bought documents are listed once
as not graded because bought (the words: `contracts/part-roles.md` section 7), in one summary line counted in no group, goal or headline, and in one
coverage row `coverage.prerun.bought_parts` built from the same sentence.
`hygiene.component_not_resolved` keeps every document.

**Default taken 2026-09-26, the owner may revise.**

**Why**: five of the sitting's findings (four RMS, one hygiene) and a pass were on the pin; the
family's representative was the pin's finding because the pin's two instances won the reach key
(`report/attention.py:497`, `:525`). With the pin out of the grading the representative comes from
graded parts by construction, so attention needs no key change (a regression test only).
`component_not_resolved` says what the other checks could not see, which matters for interference and
mass on bought parts too. Under the real version 3 profile, `hygiene.part_number_matches_file` would
flag the pin (its company number is not its file name), swapping one false finding for another unless
hygiene is covered.

**Alternatives**: grade bought parts and demote their findings (they would still be counted and
read); a Finding field "on a bought part" read by the ranking (an "is bought" check in many places).

#### R2.9 Checks that still include bought parts; mates on the custom side

**Decision**: interference, fit, fasteners, mass and material, component resolution and the RMS
assembly rules keep including bought parts; drawings are looked for for custom documents only (US4).
`rms.assembly.mates_to_reference_geometry` requires reference geometry only on the custom (or
unclear) side of a mate, and a mate between two bought parts is not graded against the assembly.

**Default taken 2026-09-26, the owner may revise.**

**Why**: a bought part still collides, fits and weighs; mating to a vendor part's faces is the only
way to mate to it, so holding it against the assembly's modelling is a false finding (the sitting's
F-010 mated to the pin's faces).

**Alternatives**: exempt every mate touching a bought part (a custom face mated to a pin would pass
unseen).

#### R2.10 One question, with buttons and a text box

**Decision**: one code-written question lists the unclear documents: "Are these bought parts? Until
you answer, they are graded for modelling practice and hygiene." with buttons "All bought" and "None
bought" and a text box to name the bought ones ("Or name the bought ones, separated by commas").
`what` names up to ten file names, then "and {n} more". It blocks no checklist item. The session and
schema gain `allow_text` on `EvidenceRequest`, and the page draws the options and a text box when it
is set.

**Default taken 2026-09-26, the owner may revise.**

**Why**: most unclear lists are all one way; a mixed list needs names, and fixing it in the profile
mid-review is slower. `allow_text` is the smallest change to feature 009's panel, which today shows
either buttons or a text box.

**Alternatives**: two buttons only, a mixed case fixed in the profile; one question per part (the
sitting would have asked once; a big assembly dozens of times).

#### R2.11 Answers regrade in the same session, for the session only

**Decision**: an answer regrades before the review resumes: the roles are reclassified with the
answer and the pre-run's `check_rms_part`, `check_rms_equations`, `check_rms_assembly`,
`check_hygiene` and `check_drawings` are restated through one general `_restate` (replacing
`_restate_drawing_check`, `agent/runner.py:902`), after any confirmed drawing read of the same batch
(R3 C16). A finding judged again keeps its id (the existing `_verdict_key` reconcile,
`agent/runner.py:623`, run by `_restate` over its own calls); one no longer produced is withdrawn by
a new `ToolContext.withdraw_findings`, which emits `finding.withdrawn`. The answer lives in the session
only. Unanswered, unclear documents are graded and each of their findings says it may be bought.

**Default taken 2026-09-26, the owner may revise.**

**Why**: an answer that changes nothing until the next review is the failure the sitting showed
(answers that changed no evidence). This is the first time a finding leaves a session, so it gets its
own event and page handling; events keep the history.

**Alternatives**: regrade at the next review only (the engineer reads findings that the answer
already made moot); keep answers across reviews now (the pane never passes the previous session to
`start_review`, `chat/server.py:2092-2111`, so that needs its own lookup - R2.23).

### U18: findings grouped by type

#### R2.12 One grouped list replaces Start here, "Show all" and the flat list on the Review tab

**Decision**: one `<section id="findings-by-type">` replaces the Review tab's five-row Start here,
its "Show all" control and the flat card list. (`contracts/grouped-list.md`.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: the tab showed the same findings three ways (the Decide/Fix/Verify counts per goal, Start
here with Show all, and the cards in arrival order: `report/summary.py:523-553`,
`Review/ReviewPage/render.js:794-896`, `index.html:203-207`), and the five-row slice took passes
(`report/attention.py:464`, `:472`).

**Alternatives**: keep Start here above the list (a fourth rendering); keep the flat list below the
groups (the third copy stays).

#### R2.13 Seven groups in a fixed order

**Decision**: Interference and fit, Fasteners, Drawings, Standards, Modelling practice, Hygiene,
Mass and material; "Other checks" last and only when it holds something. `standards.drawing.*` is
under Drawings.

**Default taken 2026-09-26, the owner may revise.** Mass and material is a seventh group by default;
the owner may fold it into Hygiene by changing its goal's `group` in the words file (a group left
with no goal and no row is not rendered, so that one edit is enough; stated on review, 2026-09-26).

**Why**: the engineer's list named six groups; mass and material still apply to bought parts
(R2.9), which argues they are not hygiene. `standards.drawing.*` speaks for drawings under feature
009's goal decision (`specs/009-engineer-workspace/contracts/review-summary.md` section 3).

**Alternatives**: six groups with mass under Hygiene; `standards.drawing.*` under Standards (keeps
one run's findings together, splits the drawing view).

#### R2.14 One prefix-to-group table, shared with the goals

**Decision**: every goal in `report/review_words_v1.yaml` gains `group:`; a new goal `standards`
(items `standards.release`, `coverage.prerun.standards`; prefix `standards.`) is split out of
`hygiene` (today `review_words_v1.yaml:121-124`), making ten goals. A finding's group is its goal's
group (`summary.goal_of`, longest prefix). Goal state lines sit under their group.

**Default taken 2026-09-26, the owner may revise.**

**Why**: one taxonomy; a second table would drift from the goals (the analysts found every check id
in `attention_policy_v1.yaml` already maps to a goal).

**Alternatives**: a separate group table (two tables to keep in step).

#### R2.15 Order within a group, headlines, folds

**Decision**: rows come from the attention policy's own order (`report/attention.py`'s rank keys),
with the modelling-practice family unfolded - the group is the fold now - and the same-check fold of
disjoint subjects kept ("xN"). Rows are one-line headlines; groups are collapsible (Modelling practice
arrives collapsed, feature 009 FR-010's precedent); passes go in one "Checked, no issue" fold; accepted
and rejected rows sit at the end of their group; a waived pass carries "within an accepted exception".

**Default taken 2026-09-26, the owner may revise.**

**Why**: one ordering rule only; where "demonstrated high first" and the policy's classes disagree,
the policy wins, so nothing is ranked twice.

**Alternatives**: a per-group severity sort (a second rule the page might be tempted to compute).

#### R2.16 No surface amplifies a pass

**Decision**: `rank()` sets `top_n = min(TOP_N, rows not suppressed)`. Every surface that slices
`rows[0:top_n]` - the check tabs, the gate brief, the explanation pass - stops showing or paying for
passes, and `not_amplified` counts them as checked within scope.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the sitting's `attention.json` reported `not_amplified.total` 0 with three passes shown,
and two of the four explained rows were passes (`agent/runner.py:940`). `top_n` keeps its documented
meaning, "how many rows the section amplifies" (`report/attention.py:136-139`).

**Alternatives**: fix only the grouped view (passes still reach the check tabs, the gate brief and
the explanation pass).

#### R2.17 The check tabs keep their preview

**Decision**: the Model check and Standards tabs keep their five-row preview, pass-free by R2.16;
their rule list below it, grouped by bucket, is already each tab's complete list.

**Default taken 2026-09-26, the owner may revise.**

**Alternatives**: the grouped list on the check tabs too (one group per tab, repeating the failing
bucket).

#### R2.18 The report gets "Findings by type"

**Decision**: `report.md`'s "Start here" becomes "Findings by type", built by the same function as the
pane. The model-facing five-row Start here stays in the gate brief (`prerun.py:641`) and in
`swreview attention` (`cli.py:943`). Feature 007's parity rule becomes: each of the gate's ids appears
in the report's index, in the same order within its group.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the report and the pane should agree; the gate brief is the model's budgeted view (007
FR-029).

**Alternatives**: keep the report's five rows (it and the pane disagree).

#### R2.19 The backend supplies every group, order and word

**Decision**: `ReviewRanking.groups` carries the groups, rows, counts and words; the page moves the
existing finding cards into rows in the order given and never sorts, compares or counts
(`PageRuleScanTests` unchanged, no new allowlist entry).

**Default taken 2026-09-26, the owner may revise.**

### U19: questions

#### R2.20 Code closes provenance at setup

**Decision**: a pure `checks/provenance.close_provenance(package)` runs in `start_review` right after
`record_partial_evidence` (`agent/runner.py:1241`), for every lever combination: with no manifest
discrepancy, one `checked` row "Reviewed as open in SOLIDWORKS: {n} documents, each at its own path in
its active configuration; revision read on {k} of {n}. The open files are taken as the latest: vault
version and local modification are not read and never asked. A missing revision is reported by the
hygiene checks."; with discrepancies, one `provenance.<kind>` finding each. The checklist item gains
`owner: code`; `mark_coverage` and `request_evidence` naming it answer `closed_by_code` (non-error)
and record nothing. The brief prints `vault_version=` and `local_modified=` only when known.
(`contracts/re-ask-guard.md` sections 1 and 2.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: four things invited the vault question - the checklist text (`agent/checklist_v1.yaml:6-12`),
the brief's `vault_version=? local_modified=?` on every document (`agent/package_brief.py:69-85`), the
extractor's two gaps per document (`ManifestBuilder.cs:126-157`) with `coverage.closeout` asking every
gap to be reflected, and no code closing provenance at all. All three recorded replay fixtures asked
it too. Non-error answers because any `error` payload becomes failed coverage
(`tools/registry.py:366-377`).

**Alternatives**: reword the checklist only (the brief and the gaps still invite it); refuse with an
error (a failed row per attempt).

#### R2.21 The extractor stops writing the two per-document gaps, separately

**Decision**: `ManifestBuilder.RecordGaps` stops writing the unconditional local-modification gap and
the vault-version gap when the build reads no vault (today always); every other manifest gap stays.
A separate change, after R2.20.

**Default taken 2026-09-26, the owner may revise.**

**Why**: R2.20's row states the fact once; the gaps cost about 310 bytes per document on every
`list_gaps` call (the model called it four times). Separate because it moves the carry-over key's gap
digest (carried findings do not carry for one run) and the pane's gap count.

**Alternatives**: keep the gaps (the model keeps reading them).

#### R2.22 The re-ask guard

**Decision**: `request_evidence` answers `already_answered` - with the earlier request's id,
question, answer and time - a question whose `blocks` equals an answered model-written request's
(null equals null) and whose entity ids are a non-empty subset of that request's, or empty against an
empty set when both name a checklist item (the two exclusions revised below); the most recent answer
wins. It includes follow-ups ("press fit" answered, numeric limits wanted):
the answer stands, and at finalization the item, if still open, is unresolved quoting the answer. A
repeat of a question still open is answered `already_asked`. Nothing is recorded, no id allocated, no
event written. (`contracts/re-ask-guard.md` section 3.)

**Default taken 2026-09-26, the owner may revise.** The `already_asked` half is this plan's addition
for an edge the defaults did not name.

**Revised on review, 2026-09-26 (default taken 2026-09-26, the owner may revise; put to the owner as
a revision of this U19 default):** the key as first written would misfire two ways. Two questions with no checklist item
and no ids counted as the same question, so a general question about load after an answered one
about temperature came back `already_answered`; and the code-written part-roles question, which has
no checklist item and names the unclear parts, covered any later model question about one of those
parts with no checklist item, answering it "All bought". So a question with no checklist item and
no ids is never covered, and a code-written request covers only itself: the guard compares a model
question with earlier model-written requests only, and a code question (the drawing check's, the
part-roles question) is recorded unless an identical one is on the session - the drawing check's
exact duplicate test (`tools/drawings.py:68-74`), kept exact and moved to `checks/questions.py`
rather than widened to the subset rule. Left for the owner: a model question with no checklist item
that names a subset of an answered model question's parts, also with no item, is still covered
(pinned by a test); excluding every question with no checklist item would be the stricter choice.

**Why**: three of the sitting's eight questions re-asked answered ones (the provenance, drawing and
fit questions, each with the same ids); simulated on the three recorded replay fixtures the key
catches nothing, so replays do not move (the revision only narrows the key, so it catches nothing
there either). Ids are compared raw: turning an instance into its document
would merge two instances of one screw.

**Alternatives**: refuse only exact repeats (misses a re-ask over fewer parts); allow a follow-up
that asks for "more detail" (the model re-asks in other words, as the sitting showed); normalise ids
to documents (merges distinct instances).

#### R2.23 Carrying answers into the next review is a later item

**Decision**: answers are not carried into the next review of the same document in this feature.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the pane never passes the previous session to `start_review` (`chat/server.py:2092-2111`),
and component and hole ids carry only when the models are unchanged; that needs its own design.
"Press Review again" (R2.25) therefore asks again what was answered; carrying answers is a later,
separate item (default taken 2026-09-26, the owner may revise).

### U20: drawings

#### R2.24 The host reports the seat switch on ping

**Decision**: `IConfirmedDrawingSource` gains `bool OpensClosedDrawings`, backed by
`DrawingOpenScope.SeatValidated` (`Sw/DrawingOpenScope.cs:130`); `PingResult` gains `drawing_read`:
`none` (no confirmed-drawing source: the console host, an add-in with no review lookup),
`open_only` (switch off) or `opens_closed` (switch on). Protocol minor version, additive. The backend
pings lazily, once per review, only when a custom document has a candidate, and records the value as
an optional `session.drawing_read`. An absent field, an older protocol, an unknown value or any
bridge error reads as `none` and never raises. (`contracts/drawing-capability.md` sections 1 and 2.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: the backend built the offer with no knowledge of the switch
(`checks/drawing_context.py:77-85`, `:224-255`); the switch reaches only the host's reader, `ping`
does not report it (`Bridge/BridgeDispatcher.cs:27-50`, `:456-462`), and the backend never pings.
Read from the object that answers `drawing.read`, it cannot disagree with it. When 011 T077 sets the
switch, `ping` changes and the backend needs no edit.

**Alternatives**: the add-in sends it on `POST /sessions` (a second copy of the truth); a package
field (a seat's runtime ability written into design evidence, and a schema bump).

#### R2.25 While the switch is off: an instruction line, no question

**Decision**: no candidate question; the candidate's coverage reason and the summary's drawings line
say "Open {drawing} in SOLIDWORKS, then press Review again with {model} active", once per drawing
file.

**Default taken 2026-09-26, the owner may revise.** The words "with {model} active" are this plan's
addition to the default's sentence: Review refuses a drawing as the active document
(`AddIn/Review/ReviewHost.cs:1074-1077`, `:1150-1153`), so an engineer who opened the drawing and
pressed Review at once would first meet that refusal.

**Why**: a question whose answer cannot act is the failure the engineer met; an open drawing is read
by this build (feature 011's attach), as the Standards run on the drawing showed.

**Alternatives**: a question with "I opened it, read it now" (reading an already-open drawing in place
with the window switching is not seat-validated).

#### R2.26 Drawings for custom documents only; a missing one is coverage

**Decision**: drawings exist for custom parts and custom assemblies only, in the same folder with the
same name. One function, `drawing_states(index, roles, mode)`, gives each reviewed part or assembly
document `attached`, `candidate`, `absent` or `bought`; unclear documents are treated as custom with
"(may be a bought part)". A custom document with no same-name drawing is `absent`: unresolved
coverage naming the missing file, never a finding.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the model asked for the vendor pin's drawing (ER-003, ER-007 in the sitting), and nothing
limited drawing questions to custom documents (`tools/session.py:60-102`). "Custom documents", not
"custom parts": the same-name drawing beside the plate is the assembly's (13 of its 14 views show the
assembly). A missing drawing is coverage because drawings may be named differently or cover several
documents, and in-work designs would flood findings; a "released custom part has a drawing" rule can
come later through the profile, gated on lifecycle.

**Alternatives**: a finding for every missing drawing; parts only (would ignore the drawing this
sitting needed).

#### R2.27 Code answers the model's drawing requests; refusals reach the model

**Decision**: `request_evidence` with `blocks == "drawing.manufacturing_inputs"` maps each entity id to
its document (a component to its document, a hole or fastener to its component's) and, when any has
no attached drawing, answers `closed_by_code` with each document's drawing state and reason, recording
nothing. When no attached drawing shows any custom document, `check_drawings` closes the item by code
(unresolved with a candidate or absent document, skipped when every subject is bought), and
`mark_coverage` on it answers `closed_by_code` in that state only. Every code-run read's outcome,
refusals included, goes into the resumed message and the drawing brief.

**Default taken 2026-09-26, the owner may revise.** Closing the item by code when nothing is attached
is this plan's reading of "code answers": the sitting's session held three model-written unresolved
drawing rows for the item.

**Why**: the refusal never reached the model - it was recorded only as coverage, and the resume
message asked it to re-run "the check you named in that request's why", which a code-written question
never named (`agent/runner.py:209-214`, `:888-900`; `tools/drawings.py:283-296`;
`drawings/brief.py:346-353`); the answer turn then spent four rounds, 109,611 input tokens, re-reading
unchanged evidence.

**Alternatives**: refuse drawing requests with an error (a failed row each time); leave the item to
the model.

#### R2.28 One read per distinct candidate path

**Decision**: candidates are grouped by drawing file with one `_file_key`, moved from
`report/summary.py:706-709` to `drawings/evidence.py` and used by its four callers; the question names
each file once, its `entity_ids` keep every document so the confirmed-candidate match holds; the
confirmed read asks the bridge once per file and writes each document's outcome from it; the host's
`MergeDrawing` removes every candidate row of the path it merged.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the plate and the assembly share a stem, so one file was two candidates, named twice and read
twice (`checks/drawing_context.py:231-255`, `tools/drawings.py:261`); with the switch on, the second
read would be refused as already a document of the review (`ConfirmedDrawingRead.cs:141-146`,
`PackageAppender.cs:232-240`). Four places computed the list and one deduplicated it.

### U21: sources

#### R2.29 A backend-supplied source on every record

**Decision**: optional `source: "code" | "model"` on `Finding`, `EvidenceRequest` and `CoverageItem`,
omitted from `session.json` at each kind's usual author: findings and coverage default `code` (only
`record_drawing_finding` and `mark_coverage` write `model`); evidence requests default `model` (the
drawing check and the part-roles question write `code`). Bodies sent to the pane always state it;
the two tool results that echo a model-written record (`mark_coverage`, `record_drawing_finding`)
echo it without the field (this plan's reading, added on review 2026-09-26: they return the whole
record, so the omit rule alone would move their bytes). Words: `labels.source: {code: "Checked by
code", model: "AI guidance"}`. (`contracts/sources.md`.)

**Default taken 2026-09-26, the owner may revise.**

**Why**: no record carries its author (`report/session.py:88-132`), and the drawing check and
`request_evidence` share one writer, so a page cannot derive the source. The defaults differ by kind
so that no byte the model reads moves and an older session shows the safe label (an old code question
reads as AI guidance, never the reverse).

**Alternatives**: derive the source when rendering (works for findings by check id only); label only
the model's prose (model questions and drawing findings stay unlabelled).

#### R2.30 A deterministic first line on every model answer

**Decision**: `text.done` gains `basis`, built by a pure `report/sources.answer_basis(steps, package)`
from the turn's successful steps whose tool is not a writer or bookkeeping tool (`request_evidence`,
`mark_coverage`, `record_drawing_finding`, `get_review_checklist`): none - "No evidence was read for
this answer: this is general guidance."; one - "Based on 1 result read for this answer."; many -
"Based on {n} results read for this answer."; and, when no drawing was read in the review, "No drawing
was read in this review." It never reads the model's text. The page prints the "AI guidance" chip, the
basis, then the answer.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the sitting's follow-up turn called no tool (`events.jsonl`: no `tool.started` between the
third turn's end and the fourth's text), yet read as a drawing review. One event, stored and
replayed.

**Alternatives**: a new `answer.basis` event (a second event type); a page-side line (the page
deciding).

#### R2.31 The empty-explanation line goes

**Decision**: `fill_fallbacks` becomes `keep_explained`, which only prunes the map to the explained
rows; `EXPLANATION_UNAVAILABLE` stays only as a legacy constant filtered out when rows are ranked, so
older run folders stop showing it; real explanations are labelled "AI guidance" in the card fold and
the report.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the fallback was persisted and rendered as if it were an explanation
(`report/explanations.py:34-36`, `:276-281`; `agent/runner.py:967`; `report/attention.py:463-467`,
`:657-660`; `web/shared/attention.js:115-117`).

### Tokens

#### R2.32 Code closes the coverage close-out

**Decision**: `coverage.closeout` becomes code-owned; `finalize_session` writes exactly one `checked`
row for it, its reason counting the open requests (each already its own
`coverage.evidence_request` row) and the package's gaps by kind; `mark_coverage` on it answers
`closed_by_code`. `was_cut_short`'s two reasons are untouched.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the model marked the close-out by hand every turn (steps 41, 69, 83 of the sitting) while
finalization already enumerated the open requests and items (`agent/runner.py:465-477`): a DRY
violation that cost a round each turn.

#### R2.33 Coverage results list the open items

**Decision**: the results of `mark_coverage` and `request_evidence` gain `open_items`, the model-owned
checklist item ids still open, in checklist order.

**Default taken 2026-09-26, the owner may revise.**

**Why**: rounds whose only call re-read the checklist or the gaps cost 102.5k tokens across the
session (`get_review_checklist` was called six times).

#### R2.34 The re-ask guard, for tokens

**Decision**: R2.22. Counted here because each re-ask cost a round and, in the third turn, three
questions.

**Default taken 2026-09-26, the owner may revise.**

#### R2.35 Refusal reasons reach the model

**Decision**: R2.27's outcome lines in the resumed message and the brief.

**Default taken 2026-09-26, the owner may revise.**

#### R2.36 Lever 14: earlier turns' reasoning items leave the request view

**Decision**: `EfficiencySettings.drop_prior_reasoning` (lever 14, default off). At the turn
boundary, the OpenAI adapter's request view leaves out reasoning items of earlier turns and keeps the
current turn's; the stored history is untouched, as pruning leaves it. Gemini sends no reasoning items
and is unaffected. It becomes a pane default only if the replay shows no lost finding and a cut in
requested input, in a commit of its own; otherwise it stays off, with the figures and the reason in
feature 005's ledger. (`contracts/tokens.md` section 4.)

**Default taken 2026-09-26, the owner may revise.** It is a lever, not a model-view setting like
pruning, because model-view settings are held to be quality-neutral (feature 008 research R2.32) and
dropping the model's own earlier thinking may not be; a lever is what the adoption rule measures.

**Why**: the adapter echoes `response.output` verbatim, reasoning included
(`agent/providers/openai_provider.py:3-8`, `:697-713`); the usage arithmetic puts earlier turns'
reasoning at about 89k of the 391k input after the first pass.

**Alternatives**: a model-view setting (no adoption gate); `previous_response_id` (server-side state,
against the adapter's stateless design); a seat A/B before adoption (the defaults ask for the replay
only).

### Correctness

#### R2.37 The drawing phase reads each sheet's own view; the revision check stays honest

**Decision**: the drawing phase takes per-sheet views from `IDrawingDoc.GetViews()`, whose first
element per sheet is the sheet's own (type 1) view - the member discovery already uses
(`SwOpenDrawingReader.cs:55-58`, `:68`) - matched to a sheet by index and confirmed by type 1 and the
sheet's name; a mismatch is a named gap and today's `ISheet.GetViews` reading is kept. Revision
tables join the table de-duplication. `revision_matches` never claims absence on a sheet with a
`revision_table_read` gap or no sheet view: unresolved, citing the gap.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the plate's drawing recorded the extractor's own warning that the sheet reports a revision
table the view walk did not find (`DrawingDumper.cs:1935-1956`), none of the 14 views was the sheet
view, and the checker counted only `drawing_sheet_views` gaps as unreadable
(`checks/standards/drawing.py:353-357`), so it asserted absence (`:656-674`), against feature 006's
own rule (`contracts/ir-additions.md:138`). Feature 006's T103 names this fallback and is still open.

#### R2.38 One tree reading for every check

**Decision**: `tree_nodes`, `MergedRow` and `CarriedRow` move from `remodel/nodes.py` to
`checks/feature_nodes.py`; `remodel/nodes.py` re-exports them, so the planner and feature 004's
contract are unchanged. The RMS part tree (`checks/rms/part.py:175-206`), grouping (`:358-375`), the
sketch rules (`:884-927`, `:933` onward) and the Standards part scope (`checks/standards/part.py:211-235`,
`:269-339`) read it. An absorbed sketch is not its own loose row: it moves with the feature that
consumes it. What was merged or carried is counted in a coverage note.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the Model check counted 48 loose features on a part with 22 (each absorbed sketch twice, the
Hole Wizard's profile sketches once more), and one under-defined sketch was named twice in each of two
families; the merge rule already existed for the planner only (`remodel/nodes.py:1-60`, used at
`remodel/plan.py:61`, `:862`).

**Alternatives**: count an absorbed sketch as its own loose row (the engineer moves it with its
feature, never alone).

#### R2.39 The explanation pass logs and keeps what is valid

**Decision**: `parse_explanations` keeps each valid item and returns the rejections (finding id or
position, and the rule: unknown id, repeated id, too long, not valid JSON); `generate_explanations`
logs them and any provider error, never the model's text. The request asks for 300 characters or
fewer, so the 480-character cap has margin.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the sitting's explanation round ran (1,811 in, 603 out) and all four rows got the fallback:
one bad item rejects the whole batch (`report/explanations.py:84-120`), every exception is swallowed
without a log (`:256-257`), and one attempt per fingerprint kept the fallback for four turns.

#### R2.40 `request_evidence` accepts the ids the tools hand the model

**Decision**: `ToolContext.entity_kind` (`tools/context.py:387-412`) knows `joint` (from the
session's joint map, `jnt:`), `feature` (`feat:`), and the drawing entities of the package
(`dsh:`, `dvw:`, `ddm:`, `dan:`, `dnt:`).

**Default taken 2026-09-26, the owner may revise.**

**Why**: F-011 and the drawing brief cited `jnt:0001`, and `request_evidence` refused it
(`tools/session.py:93-95`), writing failed coverage and costing a round.

#### R2.41 Probe 1's watchdog is deterministic, and runs flag-set first

**Decision**: `RemodelProbeWatchdog.Run(call, deadline, startBound)` starts the call on its own thread
(`TaskCreationOptions.LongRunning`), waits at most `startBound` for a "started" signal, then starts the deadline and waits
on whichever finishes first, rethrowing the host's own exception; `RunWithTimeout` stays as the
production wrapper over `Task.Delay`. Probe 1 runs the flag-set attempt first, then the flag-clear
attempt; `RemodelProbe1Logic.Decide` is unchanged. Tests control the deadline ("attempt k parked" or
"never") and release parked threads in `Dispose`.

**Default taken 2026-09-26, the owner may revise.**

**Why**: the verdict came from a wall-clock race: `Task.Run` then `Wait(500 ms)`
(`Rms/RemodelProbeWatchdog.cs:65-72`) counts thread-pool queueing as blocking, and sibling tests park
pool threads forever (`RemodelProbeExecutorsTests.cs:60`, `:77`; `RemodelProbeWatchdogTests.cs:49`);
`Refuted` needs both attempts timed out (`RemodelProbeExecutors.cs:350-360`), which fits a loaded
suite, not the lambda. Flag-set first means a message box left open by the flag-clear attempt cannot
spoil the reading that matters. A host throw also lost its message ("One or more errors occurred.",
`RemodelProbe.cs:833-837`).

### Follow-ups (defaults taken 2026-09-27)

What the integration and the review of 2026-09-27 left for a default (tasks T145 to T158).

#### R2.42 The replay reads a finding the tree reading narrowed (T134-Q1)

**Decision**: decision 23A's `narrowed` outcome (feature 008 `contracts/replay.md` section 5,
`benchmark/replay.compare_finding_keys`, which the fixture generator imports) is extended for
`rms.*` findings. Over the recording's own package, read by `checks/feature_nodes.tree_nodes` one
document at a time under the current type table, a location may also be removed:

- every occurrence of a location whose `(scope, persist_ref)` names only rows the reading carries
  as a sub-feature, merges as a second listing, or the table does not count as content - 23A's
  clause widened by the reading's two shapes;
- of a location naming a depth-0 row the reading keeps together with the second listing merged into
  it, the occurrences beyond the number of rows the reading keeps there, at most one per second
  listing: the second listing's own occurrence goes and the depth-0 row's stays.

Everything else stays exact: the family, the one-to-one matching in recorded order onto a finding
nothing else matched, the remaining locations compared reference by reference (decision 25A), the
carried-finding comparison (008 T129), and a narrowed finding listed with the locations removed.

**Default taken 2026-09-27, the owner may revise.** It answers T134-Q1 as the question put it, for
`rms.*` findings.

**Why**: with T133's reading the real recordings' replay lost 25, 3 and 2 `rms.*` findings, and
the scratch measurement of 2026-09-27 shows the shape exactly: every one comes back as one added
finding on the same part, configuration, components and inputs, its locations a sub-multiset of
the recorded ones, and every location it dropped is one of three kinds - a reference naming only
rows the table does not count (on the recordings, system rows carried under a feature: 101, 10 and
5 occurrences), a reference naming only carried content rows (29, 4 and 4), or a reference naming
one depth-0 row and its one second listing, recorded twice and named once now (148, 15 and 12;
never both occurrences dropped). A second listing is not a second feature: SOLIDWORKS lists an
absorbed sketch in both walks with one persistent reference, and the reading that grades it once
is the one the planner already uses (R2.38).

**How it stays strict**: the de-duplication is counted, never assumed - a recorded location named
once is kept, so a finding whose depth-0 row is no longer named at all is lost, as a real subject
dropped must be; a reference any kept content row carries is never removed wholesale; a tree with
neither shape folds nothing, so every decision 23A case reads as before.

**Alternatives**: a new outcome beside `narrowed` (a second list with the same meaning); removing
every occurrence of a merged pair's reference (it would hide the depth-0 row dropped); a hand list of
the 30 findings (it drifts); regenerating the fixtures with T133 and accepting the recordings' loss
(the rule that no recorded finding is lost is absolute).

#### R2.43 The Model check says its open part looks bought (FR-008, US1 scenario 6)

**Decision**: `POST /checks/rms` takes an optional `standards_profile` path, the same setting the
Review tab uses (`UserSettings.StandardsProfilePath`), which `ModelCheckHost` passes to the page in
`init` and the page relays in its request. With it the backend loads the profile through the
review's own loader (`load_review_profile`), classifies the dump's documents with the one classifier
(`classify_parts`), and the `CheckResult` carries `bought_parts`: the part-roles sentence
(`bought_parts_sentence`), whose root-rule clause reads "{file} looks bought ({reason}); graded
because it is the document under review" when the rules call the open part bought, or null when
there is nothing to say. Without it the body is unchanged, with no `bought_parts` key. The page prints
the line verbatim. The rules and the grade are the same either way: the Model check's part is its
document under review, always graded.

**Default taken 2026-09-27, the owner may revise.**

**Why**: 013 T030 put the root rule's label on the review's surfaces and deferred the Model check's
half because its route took no profile; the spec says the Model check tab behaves the same for its
open part.

**Alternatives**: the host reading the profile and sending roles (the reasoning side owns the file,
feature 006 FR-002); a words-file sentence of the page's own (a second author of the label).

#### R2.44 Lever 14 falls back once when the real endpoint refuses its request

**Decision**: the OpenAI adapter sends a request that left earlier turns' reasoning out; if the
endpoint refuses it with an invalid-request error (`400`) about a missing reasoning item or a
linked item, it sends that same request again at once with every reasoning item kept, turns lever 14
off for the rest of that adapter's session, and logs one plain line. Any other refusal, a request
that left nothing out, and a refusal of the resent request are raised as before. `session.efficiency`
keeps the lever as requested; the log line says it fell back. The key-gated live test fails when the
adapter fell back, so the seat's run of it (T153, test-plan step 2.7) says whether the endpoint
accepts the request.

**Default taken 2026-09-27, the owner may revise.**

**Why**: the real endpoint has not seen lever 14's request shape, the development machine has no
key, and lever 14 is a pane default (T125): a refusal would stop every review's second turn. The
resent request is the one every review sent before lever 14, so the fallback costs one refused
request, once.

**Alternatives**: turning lever 14 off until the seat proves it (loses the measured cut); retrying
without turning it off (a refused request every turn); failing the turn (stops the review).

#### R2.45 A refused profile's reason names no path

**Decision**: the classifier's `absent` state quotes a refusal's kind and cause - the field the
profile got wrong, or that the file is missing or unreadable - and never the profile's path, its
folder or its file name. `ProfileError` carries its message without the path beside the message
with it; `profile_refusal_of` reads the first.

**Default taken 2026-09-27, the owner may revise.**

**Why**: `profile_refusal_of` was `str(ProfileError)`, and every loader message begins with the path,
a local user folder, which then rode the bought-parts line into the digest, the coverage row, the
summary and the report.

#### R2.46 The checklist says only what is true of every code-owned item

**Decision**: a code-owned item renders "Closed by code; never ask about it or mark it." in place
of "Closed by code before your first turn; never ask about it or mark it.". Each item's own
description says when: `provenance` "from the package before your first turn", `coverage.closeout`
when the review ends (its row, "Closed by code when the review ended: ...").

**Default taken 2026-09-27, the owner may revise.**

**Why**: `coverage.closeout` is written at finalization (`contracts/tokens.md` section 1), so the
shared line told the model something false of it. The line moves the checklist the model reads, so
the replay gate runs (T158).

**Alternatives**: a line per item naming its moment (a second field for one word); writing a
close-out row at setup (a row that says nothing true yet).

---

## R3. Design choices of this plan

Choices the defaults leave open, made here and changeable in review:

| # | Choice | Reason |
|---|---|---|
| C1 | Module and field names: `checks/part_roles.py`, `checks/provenance.py`, `checks/feature_nodes.py`, `report/finding_groups.py`, `report/sources.py`; `source`, `allow_text`, `basis`, `drawing_read`, `drop_prior_reasoning` | One name per concept, matching the analysts' designs where they agreed |
| C2 | The `part_roles` keys: `bought_prefixes`, `bought_folder_names`, `switch`, `vendor_properties`, `distributor_block`, `catalogue_numbers`, `custom_prefixes`, `bought_number_prefixes`, `detail_properties` (revised 2026-09-26 from `bought_prefixes`, `purchased_property`, `purchased_values`, `bought_name_patterns`) | One key per signal of `contracts/part-roles.md` section 2.1, spelled as the profile spells its other lists |
| C3 | A purchased property with no values, or values with no property, is refused | "Every key required, every value may be empty" is about statements; a half-written signal is neither |
| C4 | The part-number convention matching no document at all asks nothing and writes one unresolved line | Feature 006's zero-match precedent (`checks/standards/document.py:171`); a misconfigured profile (the fictional example on the seat until 2026-09-26) would otherwise ask about everything |
| C5 | The page's text box has a placeholder from the words file, not a field on the request | The page prints words it is given; the request says only that text is allowed |
| C6 | `finding.withdrawn {finding_id, reason}` is a new event; the page drops the card and reloads the summary | The first time a finding leaves a session; events keep the history |
| C7 | The summary block keeps the headline, one tally line, questions, parts not loaded, drawings, bought parts and one "Not reached" line; `SummaryGroup.by_goal`, `modelling_practice` and the top-level goal list go | Goal lines live under their group now (R2.14); the analysts' option A, which avoids a second copy of the taxonomy |
| C8 | `within_scope`'s label becomes "Checked, no issue" | One word for the tally and the fold |
| C9 | Question checks in `request_evidence`, in order: ids (refusal), short form (refusal), code-owned item (`closed_by_code`), drawing states (`closed_by_code`), covering request (`already_answered` / `already_asked`), record | Refusals first, as today; the non-error answers after the arguments are known to be valid |
| C10 | `QuestionSpec` and the duplicate test move to `checks/questions.py` | The drawing and part-roles questions share one shape and one test |
| C11 | `PrefixList` and `name_matches(pattern, name, *, wildcards)` come out of `checks/standards/library.py` and `traversal.py` | One prefix matcher and one pattern matcher; the data-card check keeps `wildcards=False` |
| C12 | The replay gate is one task per story, run on `main` after that story's lanes merge, in merge order; each regeneration is a commit of its own; from a story's last merge until its gate commit no other change that moves what the model reads merges (the freeze, added on review 2026-09-26) | Regenerations cannot run in parallel lanes; without the freeze, lane S's queue (US1, US3 to US6) could put two stories' moves on `main` before one gate, which could then not say which change moved a fixture |
| C13 | Lever 14's replay pricing subtracts each earlier turn's recorded reasoning output tokens from every later-turn round | The usage events record reasoning tokens per round; the replay has no other trace of them |
| C14 | No tool signature or docstring changes; every new behaviour reaches the model as a status or a field of a result | `test_docstring_split.py` and `test_tool_payload.py` pin both |

Choices made on review of this package, 2026-09-26 (changeable in review like those above):

| # | Choice | Reason |
|---|---|---|
| C15 | `mark_coverage` and `record_drawing_finding` echo their record without `source`, through `as_json(record, exclude={"source"})` (`contracts/sources.md` section 1) | They return the whole record, and both write `model`, the value the omit rule keeps; otherwise every recorded result would move and the US5 gate (T115) would blame T097 |
| C16 | In `answer_evidence_batch`: the confirmed read first, then the roles, then one `_restate` of the union, which reconciles its own restated calls before the resumed turn's `before` index is taken (`contracts/part-roles.md` section 9) | A withdrawal taken after that index would shift restated findings into the list's earlier part as duplicates; roles changed before the read would make the rebuilt candidate question miss |
| C17 | The part-roles model-facing sentences are constants of `checks/part_roles.py`; the words file carries only pane words (`contracts/part-roles.md` section 3) | Lanes P and S need them before lane R's words file lands, and the `Words` model refuses unknown keys; like every model-facing sentence, editing one needs the replay gate |
| C18 | `bought_parts` is read from the persisted coverage rows, never classified again (`contracts/part-roles.md` section 7) | The disk route and the re-render have no profile and no roles |
| C19 | `GroupRow` carries `tail_text`, `reach_text`, `hide_card_title` and `chip`; a type group with neither a row nor a goal is left out (`contracts/grouped-list.md` section 3) | The page may not count, pluralise or compare (FR-022), and folding a goal away stays one edit |
| C20 | The generated goldens regenerate in the order T014, T060, T129 (with T127), T133; the pane drawing fixture is lane R's (T093) (`plan.md`) | Files generated whole cannot be regenerated in parallel lanes; the drawing fixture plays no recording |

## R4. Verified causes the tasks cite

The analysts' causes, by item (VERIFIED against the code at `9edc36c`, which `111bc82` equals outside
one test file):

| Item | Cause | Where |
|---|---|---|
| U17 | Every part document graded by RMS; every reached model by hygiene; only Standards reads library prefixes | `tools/rms_checks.py:253-269`; `checks/hygiene.py:309-315`; `checks/standards/part.py:233`, `document.py:241` |
| U17 | The family representative is the member with the lowest key; reach counts instances | `report/attention.py:497`, `:525` |
| U17 | The profile loader requires every key and refuses unknown ones; the later-section check lists versions by name | `checks/standards/profile.py:283-336`, `:317-321` |
| U18 | Start here slices `rows[:TOP_N]` without leaving out suppressed rows; the empty reason fires only when every row is suppressed | `report/attention.py:136`, `:464`, `:472`, `:576-582`, `:655`; `web/shared/attention.js:70-76`; `render.js:805` |
| U18 | The pass-aware grouping in the summary is not reused | `report/summary.py:510-520`, `:563` |
| U18 | Three renderings of the same findings on the Review tab | `report/summary.py:523-553`; `render.js:794-896`, `:945-963`; `index.html:203-207`; `app.js:1118-1147` |
| U19 | The checklist asks for vault version and local modification; the brief prints unknowns; the extractor writes two gaps per document; nothing closes provenance | `agent/checklist_v1.yaml:6-12`, `:58-62`; `agent/package_brief.py:69-85`; `ManifestBuilder.cs:75-78`, `:126-157` |
| U19 | `request_evidence` checks ids and the short form only, and always records | `tools/session.py:60-102`, `:105-138`; `prompts/system_v1.md:41-45` |
| U20 | The offer ignores the switch; the switch is not on ping; the backend never pings | `checks/drawing_context.py:77-85`, `:224-255`; `Sw/DrawingOpenScope.cs:130`; `Bridge/BridgeDispatcher.cs:27-50`, `:173-176`, `:456-462` |
| U20 | The refusal reaches only coverage; the resume message names no check for a code question | `agent/runner.py:209-214`, `:888-900`; `tools/drawings.py:283-296`; `drawings/brief.py:346-353` |
| U20 | Candidates not deduplicated by file; one read per document; the merge removes one row | `checks/drawing_context.py:231-255`; `tools/drawings.py:261`; `report/summary.py:687-694`, `:706-709`; `PackageAppender.cs:232-240`; `ConfirmedDrawingRead.cs:141-146` |
| U21 | No record carries its author; `text.done` carries text only; the fallback is persisted | `report/session.py:88-132`; `chat-events.schema.json:22-23`; `report/explanations.py:34-36`, `:276-281`; `agent/runner.py:967` |
| Tokens | Reasoning items echoed; the pane's levers; single-purpose rounds | `agent/providers/openai_provider.py:3-8`, `:697-713`; `agent/settings.py:494-509` |
| Tokens | Close-out done twice | `agent/runner.py:465-477` |
| Readings | The revision check ignores the extractor's cross-check gap | `checks/standards/drawing.py:353-357`, `:656-674`; `DrawingDumper.cs:1678-1711`, `:1935-1956` |
| Readings | Each absorbed sketch graded twice | `checks/rms/part.py:188-200`; `checks/standards/part.py:277`; `remodel/nodes.py` |
| Readings | The explanation batch all-or-nothing and silent | `report/explanations.py:73-121`, `:252-257` |
| Readings | `jnt:` unknown to the entity lookup | `tools/context.py:387-412`; `tools/session.py:93-95` |
| U24 | The watchdog counts queue time | `Rms/RemodelProbeWatchdog.cs:65-72`; `RemodelProbeExecutors.cs:344-372`; `RemodelProbeExecutorsTests.cs:42-96` |

## R5. The replay gate, and what moves it

Feature 008's replay (`specs/008-checks-first-review/contracts/replay.md`) holds every change that
moves what a tool returns, the system prompt, the checklist, the opening message or a resumed message.
Under the owner's decision 3A (2026-09-23) the fixtures follow the code: the three are regenerated by
the change that moves them, with section 8's commands, then the pane fixture; section 9's figures are
re-measured and recorded with their reason; the real recordings are held to their drift (section 10,
residual zero on every round). No recorded finding may be lost or become unreplayable - an absolute
rule.

| Story | What moves | Gate |
|---|---|---|
| US1 | `check_rms_part`, `check_rms_equations`, `check_rms_assembly`, `check_hygiene` results; the pre-run digest's two lines; the brief's `role=`; the checklist's RMS and hygiene sentence | Regenerate |
| US2 | The gate brief (lever 11) and `attention.json` for sessions with fewer than five undecided rows; the explanation pass's rows | Run; regenerate if a fixture moves |
| US3 | The checklist's provenance item and its render; the brief; the system prompt; `request_evidence` and `mark_coverage` statuses; one new coverage row per session | Regenerate |
| US4 | `check_drawings`' payload and wording; the checklist's drawing item; the system prompt; the resumed message after a confirmed read | Regenerate (the fixtures carry no drawing evidence, so the family stays unoffered; the checklist and prompt still move) |
| US5 | Nothing the model reads (the fields are omitted at their defaults; the results of `mark_coverage` and `record_drawing_finding` echo their record without `source`; `text.done` is not in the prompt) | Run, to prove nothing moved |
| US6 | The checklist's close-out render; `mark_coverage` and `request_evidence` results; the request view under lever 14 | Regenerate; lever 14 priced off and on |
| US7 | `check_rms_part` results and observed text (fewer rows, each sketch once) | Regenerate; carried-finding comparisons (008 T128, T129) re-read |

Recorded model calls that the new code answers differently (a recorded `mark_coverage` on
`provenance` or `coverage.closeout` now answered `closed_by_code`, a recorded re-ask now answered
`already_answered`) are the replay's "changed" class; the drift rule accounts for each by its result's
size change.

## R6. Found and not in this package

Recorded for the owner; nothing here is built by this feature.

| # | Finding | Why not here |
|---|---|---|
| N1 | `mark_coverage` appends and never withdraws the model's earlier row for the same check; readers take the first row, so goal details can show a turn-1 sentence after an answer closed the item (the model told the engineer the row was replaced) | Not decided by a default; a candidate for the owner, and it matters for the goal lines under groups |
| N2 | One defect reported by two families (the plate's under-defined sketch as an RMS and a Standards finding), now in two groups | Cross-referencing or de-duplicating families is an owner decision |
| N3 | The joint rules pass a line-to-line dowel pin as a floating fastener with a zero allowance, though the engineer called it a press fit | Needs the owner's read of the joint rules |
| N4 | The revision is read from two sources: the manifest hard-codes two property names, hygiene reads the profile's | Not decided by a default |
| N5 | The vendor pin's tolerance was in the package as a configuration property; no check used it | A tolerance-source change for feature 010 |
| N6 | `GetSystemValue3(swThisConfiguration, null)` returned no number for every display dimension on the plate's drawing; the view's referenced configuration is probably needed | A probe line at the next sitting (feature 011's D-series) |
| N7 | The RMS type table's `tolerated_loose` lacks three folder types; once bought parts are skipped, a custom part with mate references or a configuration table will get false loose rows | Likely to surface after US1; a feature 003 type-table change |
| N8 | A part-only Model check writes the four assembly coverage-only rules as unresolved; code-only reports print a model id; a drawing-rooted Standards run skips `one_fixed` and `fully_mated` when component rows were dropped | Small fixes the defaults did not take |
| N9 | Palette views (`*Front`, `*Top`) are recorded as drawing views, most flagged out of date | A reader change for feature 011 |
| N10 | The engineer's follow-up text is recorded nowhere (no event type for an engineer message) | An events change for features 002 and 009 |
| N11 | History pruning replaces results mid-prompt, so the cached prefix breaks at the oldest newly pruned result; the prompt cache key (lever 3) is off | An A/B for feature 005 |
| N12 | Answer turns offered the full tool list (lever 4) | An owner A/B decision |
| N13 | Running no model turn when an answer changes no evidence | Not a default; with the switch off (US4) the sitting's case no longer arises |
| N14 | Weak add-in tests that sleep and assert that nothing arrived | Test debt outside U24 |

## R7. Relation to the features around it

| Feature | What 013 changes in its contracts | Note line added |
|---|---|---|
| 001 | `review-session.schema.json` (`allow_text`, `source`, `drawing_read`); `agent-tools.md` (`request_evidence` and `mark_coverage` answers); `cli.md` (`swreview attention` mirrors no report section) | `contracts/README.md`, `agent-tools.md`, `cli.md` (added on review) |
| 002 | `chat-events.schema.json` (`text.done.basis`, `finding.withdrawn`); `chat-api.md` (`not_examined` above the grouped list) | `contracts/README.md`, `chat-api.md` (added on review) |
| 003 | `rules.md` (grading scope; the mates rule's custom side; content features read through the shared tree); `tools.md` (a bought id refused); `model-check.md` (the report's "Findings by type") | all three (`model-check.md` added on review) |
| 005 | `levers.md` (lever 14) | `levers.md` |
| 006 | `profile.md` (version 4, `part_roles`, the name vocabulary); `rules.md` (`revision_matches`; the sketch check's tree); `ir-additions.md` (the sheet view); `standards-check.md` (the report's "Findings by type"); spec FR-020 and FR-024 | all four (`standards-check.md` added on review); a pointer above the spec's requirements |
| 007 | `attention.md` (sections 3, 4 and 6: `top_n`, the Review tab's groups, the fallback); `gate.md` section 3 (the brief's own Start here; the parity rule); `cli.md` (`report.md`'s "Findings by type"); spec FR-013, FR-023, FR-031, SC-004, SC-006, SC-009 | all three (`gate.md` and `cli.md` added on review); a pointer above the spec's requirements |
| 008 | `checks-first.md` (roles attached before the pre-run; two digest lines; provenance at setup); `answer-batch.md` (the regrade step, the outcome lines, `finding.withdrawn`); `model-view.md` (lever 14 beside pruning); `replay.md` (section 9 rows per regeneration) | all four |
| 009 | `questions.md` (sections 1 to 4: the new answers, `allow_text`, `source`); `review-summary.md` (groups, goals, lines); `views.md` (Results); `plain-words.md` (source labels, the one-line row); spec FR-007, FR-009, FR-010, FR-019, SC-001 | all four; a pointer above the spec's requirements (added on review) |
| 010 | `hygiene.md` (section 1: graded documents); `code-first.md` (hygiene reads the attached roles) | both |
| 011 | `questions.md` (sections 3, 4, 5, 6); `confirmed-open.md` (sections 1, 2, 4); `brief.md` (section 2); `native-evidence.md` ("Tables": the sheet's own view); `profile.md` section 1 (the known versions) | all five (`profile.md` added on review) |

Feature 012 stays reserved for drawing creation and is not touched. Feature 004 is not touched by
this package. *Added 2026-09-26, after this package:* feature 004 records the probe 1 watchdog
default itself, as 004 T171 and in its amended T033 (004 research R13.7); no task of 013 edits a 004
document.
