# Contract: Plain Words Everywhere the Engineer Looks

*Amended 2026-09-26 by feature 013 (`specs/013-engineer-first-review/`), landed by 2026-09-27 (013 T054, T101):* `labels.source` ("Checked by code", "AI guidance"); rows are one-line headlines; the default-view scan covers group headings and rows; see 013 `contracts/sources.md` section 2 and `contracts/grouped-list.md` section 5.

Normative for FR-012 (titles), FR-024 to FR-029 and SC-003.

## 1. `GET /labels`

`GET /labels` (bearer token required; `OPTIONS` answered without one, as every route) → `200` with
the words file's `labels` block (data-model section 7): `{version, status, severity, bucket,
evidence_status, contact_kind, errors}`. It reads no session and writes nothing.

The page asks for it after every `init` that names a backend (a settings save restarts the backend
and re-inits the page) and keeps it in `state.labels`. It passes the labels into the renderers as an
argument; `render.js` and `web/shared/attention.js` hold no labels of their own. A lookup whose value
is not a string - an absent key, a 404 from an older backend, a token that names something on
`Object.prototype` - prints the raw token as before this feature.

| Surface | Word from |
|---|---|
| finding card status chip, severity chip | `status`, `severity` |
| Start-here meta (Review tab) | `status`, `severity` |
| coverage fold bucket names and counts | `bucket` |
| evidence record chip | `evidence_status` |
| contacts fold | `contact_kind` (also carried as `kind_label` on the summary) |
| error card, card status lines, settings save line | `errors` |

*Amended 2026-09-26 (feature 013 T101, its `contracts/sources.md` section 2):* the block gains
`source: {code: "Checked by code", model: "AI guidance"}`, before `errors` (which stays last). The
page prints `labelOf(labels, "source", token, "")`: a chip on the finding card's line, on the
question pager and the evidence card head; on a grouped row it prints `GroupRow.chip` verbatim (the
backend's word for a model row, `null` for a code row); a goal detail or coverage row shows a label
only when its body carries `detail_source` or `NotClosed.source`, which are sent for `model` only.
`report.md` uses the same two words: "Source: AI guidance" on a model finding, a Source column in the
evidence requests table, and "(AI guidance)" after a close-out sentence the model wrote.

*Amended 2026-11-01 (feature 002, owner decision 185A; its FR-031):* the block gains `triage`, the
words of a finding's four triage outcomes, after `contact_kind` and before `source`, so `source`
still comes just before `errors`, which stays last: `{new_and_real: "new and real", already_known:
"real but already known", wrong: "wrong", not_worth_flagging: "true but not worth flagging"}`, keyed
by the tokens of `findings.TRIAGES` in their order, and `errors` gains `InvalidTriage`'s sentence. The page prints `labelOf(labels, "triage", token, token)`, the raw
token with no labels; `report.md` prints the same words under a finding's decision and in its "By
triage" count.

| Surface | Word from |
|---|---|
| the four triage buttons beside Accept, Reject and Defer, and the card's disposition sentence | `triage` |
| `report.md`'s triage line under a decision, and its "By triage" line | `triage` |

*Amended 2026-11-01 (feature 002, roadmap hole H-g-012; owner decision 185A unchanged):* `errors`
gains `TriageAlreadyRecorded`'s sentence, "That finding already has a triage, and a triage is
recorded only once. The one recorded stands and is shown again.", for the class the disposition
route refuses a second triage with (002 `contracts/chat-api.md`, the disposition route), which was
`IllegalTransition`, whose sentence reads as a refused decision. `errors` stays last, `source` just
before it.

*Amended 2026-11-01 (feature 002, roadmap hole H-d-008; owner decisions 189A and 191A; 002 T329):*
a finding card's status line also prints the line of a `disposition.cleared` event, which the
backend sends when a check run again after an answer changed a decided finding's status or
severity and so cleared its decision and triage: "The check ran again after your answer and its
verdict changed, so your Accept (real but already known) was cleared. Decide again." The backend
words it from the words file's `rerun` block (data-model section 1), naming the decision and the
triage, so the page prints it as sent, in the hue of what only the engineer can settle, and looks
nothing up: `labels` gains nothing, and with no labels the line is the same (FR-030). The
engineer's next decision writes its own sentence there; a replay leaves it out, as Results are the
snapshot.

*Amended 2026-11-01 (feature 002, owner decision 187A; 002 T333):* the block gains `pass_triage`,
after `triage` and before `source`, so `source` still comes just before `errors`: `{wrong:
"wrong: a miss"}`, keyed by `findings.MISS`, the one outcome a pass takes. A pass's card, in the
Checked, no issue fold, prints `labelOf(labels, "pass_triage", "wrong", "wrong")` on its one
triage button, the raw token with no labels; its disposition sentence and `report.md` name the
triage by `triage`'s word, as for any finding. `errors`' `InvalidTriage` sentence says what a pass
takes: "Pick one of the four triage outcomes, or none, then press the decision again. A finding in
Checked, no issue takes only wrong: a miss."

| Surface | Word from |
|---|---|
| a pass's one triage button | `pass_triage` |

*Amended 2026-11-02 (feature 002, roadmap hole H-c-008; 002 T353 and T356):* the block gains
`no_triage`, after `pass_triage` and before `source`: what a flagged finding's card head says until
its triage is recorded, one sentence keyed `undecided`, one for each decision recorded without a
triage (`accepted`, `rejected`, `deferred`), each of those naming the repair, and one keyed
`read_only`, what such a card says while its review is read-only, whatever its decision, naming
no press. The page prints `labelOf(labels, "no_triage", key, "")` under the title - the key
`read_only` while the review is read-only, else the decision, `undecided` for none - and nothing
on a pass; with no labels there are no words and the head is as before (FR-030), as with `source`.

| Surface | Word from |
|---|---|
| a flagged finding's card head, until its triage is recorded | `no_triage` |

*Amended 2026-11-02 (feature 002, owner decision 198A; its cycle 11's Tier 2 review, 002 T368):*
the block gains `note`, after `no_triage` and before `source`: `{not_kept: "The note recorded first
stays."}`, what a finding card says when a decision's reply keeps the note recorded first in place
of another one the press sent, as a late triage does (198A). The page compares the note its press
sent, when not blank, with the reply's, both trimmed, and prints
`labelOf(labels, "note", "not_kept", "")` on the card's status line after the reply's sentence,
until the status is next written; with no labels it prints nothing (FR-030).

| Surface | Word from |
|---|---|
| a finding card's status line, after a reply that kept the note recorded first in place of the one sent | `note` |

*Amended 2026-11-03 (feature 002, roadmap hole H-c-010; 002 T377):* `errors` gains
`OutcomeNeeded`'s sentence, "Pick an outcome first, then press the same button again.", for the
class the disposition route answers when a flagged finding's decision recorded without a triage is
sent again with none (002 `contracts/chat-api.md`, the disposition route). That press was
`IllegalTransition`, whose sentence says to reload the review, and a reload draws the card's note
box from the record, so a note typed for the retry was lost. The sentence takes no placeholder, so
it names the same button; a flagged finding's card has a `no_triage` line, which names the
decision. A pass has none, and its press is `IllegalTransition` as before (cycle 15's Tier 2
review). `errors` stays last.

*Amended 2026-11-03 (feature 002, roadmap hole H-a-009; 002 cycle 17):* the block gains
`first_shown`, after `note` and before `source`: `{earlier: "First shown in the review of
{date}."}`, what a finding card says when an earlier review of the same document first showed the
finding, for owner decision 188A's date. The page prints `labelOf(labels, "first_shown",
"earlier", "")` under the title with `{date}` replaced by the `finding` body's `first_shown`, as
text, and nothing for a body without one or with no labels (FR-030); `report.md` prints the same
words under the finding's heading.

| Surface | Word from |
|---|---|
| a finding card's head, when an earlier review first showed the finding | `first_shown` |

## 2. Titles

*Amended 2026-09-23 by the owner (decision 2A, research R2.28).* A finding has two titles, and
each is built for its reader:

- **The recorded title**, `Finding.title`, is what the model reads. It is exactly what it was
  before this feature: `title_from(observed)` - the first sentence of `observed` (split on ". "),
  trimmed, its closing period dropped, cut at `TITLE_LENGTH` (80) with an ellipsis, component ids
  as written. It is in every check tool's result, so it costs no token and moves no replayed
  round. It stays in `session.json`, `attention.json`, every tool result and its slim view
  (`tools/model_view.py`), the gate brief (`prerun.gate_brief`), the explanation pass's prompt
  (`report/explanations.py`) and `swreview attention`.
- **The display title** is what a person reads. `report/titles.display_title(finding, names)`
  returns, for a title this product recorded from `observed` (`finding.title ==
  title_from(finding.observed)`, cut or not), the whole first sentence of `observed`; for any
  other title - one written by hand, or by an older build with another rule - the title as
  written. Either way every `cmp:` id whose name is non-blank is replaced by the name
  (`report/names.with_component_names`); `names` is `component_names(package)`, empty when there
  is no package. It is never cut: the page's two-line clamp is the only length limit.

`report/titles.py` holds both, so the display title undoes exactly the cut the recorded title
made; `tools/recording.title_from` and `TITLE_LENGTH` are that module's, re-exported unchanged.
Every surface a person reads calls `display_title`, through one of two helpers or directly:

| Surface | How |
|---|---|
| the `finding` event (`ToolContext.record_finding`, and the runner's re-run announcement after an answer batch) | `pane_finding(finding, names)`: the `Finding` body with `title` replaced |
| the snapshot's `findings` (`report/snapshot.review_snapshot`: both restore routes and the pane fixture) | `pane_finding` |
| the Review tab's ranking rows (`review_ranking`: the attention route, the snapshot, the disk route), which Start here and "Show all" print | `with_display_titles(ranking, findings, names)` |
| both check bodies' `attention` rows (`check_result`, `standards_result`), which the check tabs' Start here prints | `with_display_titles` |
| `report.md`: each finding's heading and Start here's titled rows (`render_report`, every caller; `swreview report` passes the package beside the session through `report/rerender.render_folder_report`, corrected 2026-09-23 on review) | `display_title`, and `with_display_titles` on the ranking it is given |

*Amended 2026-09-26 by feature 013 T054:* the Review tab prints no Start here or "Show all"; its
grouped rows (`ReviewRanking.groups`, 013 `contracts/grouped-list.md` section 3) carry the display
titles, which the page prints verbatim under a one-line clamp - the row's only length limit, the
card inside keeping its two-line clamp.

`with_display_titles` replaces the title of every row with its survivor's (`row.finding_id`)
display title; a folded family's row keeps its family title, and a row whose finding is not among
`findings` keeps its title. Order, keys, reasons and every other field are the ranking's own, and
applying it twice changes nothing. The page prints `title` verbatim wherever it arrives; it builds
no title. `observed` keeps its ids everywhere. No golden baseline moves: they pin recorded titles.

**One model-facing surface carries display titles, deliberately** (recorded 2026-09-23 on review;
no behaviour changed). The MCP resource `swreview://report` (`mcp/server.py`, `_read_resource`)
serves `report.md` as written (`test_mcp_server.py` pins it verbatim), so the terminal's model -
the Codex or Gemini command line through MCP - reads each finding's heading with its display title
there, and the recorded title in every tool result it fetches. The report is the engineer's
document, read only when the model asks for it; a second, model-facing copy would be a second
report to keep in step. Every heading starts with the finding's id (`#### F-nnn: ...`), and the id
is how a heading and a tool result's finding are matched, never the title. The resource is priced
nowhere (it is not a tool payload and feature 008's replay does not read it). Serving recorded
titles there instead would be an owner decision; the default is the report as written.

## 3. Names instead of ids

| Surface | Name | Id |
|---|---|---|
| finding title | backend, the display title (section 2) | `observed` and "Affects" in the fold |
| Start-here meta, Review tab | `summary.component_names` | "Affects" in the finding card's fold, which the row scrolls to |
| question panel "about" | `QuestionView.about[].name` | the question's fold |
| not-loaded warning | `not_examined.headline` | the warning's fold lists `instances` ids |
| contacts fold | `ContactView.text` | each line's fold |

`NotExamined.headline` is composed in `report/unexamined.py` (data-model section 5); `sentence` stays
for `report.md` and the check bodies.

## 4. Check ids into folds

- The finding card's line holds the id, the status chip and the severity chip; the check id is the
  first labelled row of the fold, "Rule".
- The shared Start-here row (`web/shared/attention.js`) shows no check id on any tab; the row carries
  it as `data-check`. `attentionMeta(row, labels, names)` prints status and severity through
  `labels` and components through `names` when given, ids when not (the check tabs pass neither).
- The shared rule row (`web/shared/check-page.js`) shows the statement as its title and moves the
  rule id into the row's fold, so every rule row has a fold.
- The coverage fold keeps its check ids: it is a fold.

## 5. Errors

Every error the Review tab shows - an `error` event, a refused `review.start` or `review.prepare`, a
refused backend call, a refused disposition or answer, a refused settings save - prints
`labels.errors[error_class]` (the error's message when there is no label) as its sentence, with the
class and the message behind a fold. The words file has a sentence for every `ChatError` subclass,
for every class the Review host and `PaneActions` send, and for the classes `app.js` makes
(`BackendUnavailable`, `HttpError`, `HostError`).

*Amended 2026-10-21 (feature 002, owner decision 160A):* the Review host sends `AddInStopping`
too - a settings save written while the add-in unloads - whose sentence is "The settings are
saved. The add-in is stopping; nothing else needs doing."; with no labels the save's line prints
the message whole, as it does for `BackendNotRestarted`, rather than the class and the message.

*Amended 2026-11-01 (feature 002, roadmap hole H-g-012):* a refused disposition keeps the record
in view. The finding card's status line shows the recorded disposition's sentence on a line of its
own, in the settled colour, above the refusal's sentence and its fold; with no labels, above the
class and the message. The triage row presses the recorded triage, or none, in place of the
refused pick. A finding with no disposition shows the refusal alone, as before. The page reads the
record from its own memory of what was recorded and decides nothing about which press is refused.

## 6. Model check

`check_result` carries `rule_statements` (data-model section 10). The grade header prints the counts
as today, then - instead of the fraction line and the unresolved rule ids - "Not graded, evidence
missing:" and the statement of each unresolved rule (`rule_statements[id]`, the id when the
catalogue lacks it), with the ids behind a shut fold, or "Every rule reached a verdict." The body's
`grade.fraction` and the report are unchanged. The Standards header is unchanged.

*Landed as* (T067, T069, T071, T073): the lookup is one prototype-guarded `labelOf(labels,
group, token, fallback)` in `web/shared/attention.js`, which `render.js` reuses; the shared meta
line is `attentionMeta(row, options)` with `options.labels` and `options.names` (tasks.md's
signature); `render.plainError(error, labels)` is the one error shape, used only when labels are
present - with none, the error card keeps its class chip and message, a card's status line
"Class: message", and the settings save line its old wording (FR-030); the check tabs' rule id is
`p.rule-line > span.rule-id` first inside the row's fold, whose summary reads "Rule" when nothing
else is behind it; Model check's ids are in `details.unresolved-ids`. `ErrorLabelsCoverTheHostTests`
reads the words file by indentation; it was skipped until the py lane's T008 wrote the file, and
runs since.

## 7. The default-view scan (SC-003)

*Amended 2026-09-26 (feature 013 T101):* the scan also finds no raw `code` or `model` source token
visible, and the backend half scans the grouped list's headings, count lines and row words beside the
summary block (`test_plain_words_fixture.py`).

A WebView2 test loads the big-assembly pane fixture with its labels, finishes the review, and reads
the visible text of Results - skipping the contents of shut `<details>` and of hidden finding folds
- and asserts it holds:

- no `cmp:` id whose component has a name in `summary.component_names`;
- no raw status or bucket token (`checked_within_scope`, `out_of_scope`) and no underscore-joined
  token of the status and bucket vocabularies;
- no check id (a token matching `^[a-z]+(\.[a-z0-9_]+)+$` that is a check of the fixture's
  findings or coverage);
- no error class name (any key of `labels.errors`).

The backend half is a Python test on the same fixture: no display title (section 2) holds a
`cmp:` id whose component has a non-blank name, and no summary word holds a check id or a raw token.

*Landed as* (T065, `test_plain_words_fixture.py`): the page scan runs all four checks and the
backend test both halves. The `cmp:` checks read the display titles (section 2, decision 2A of
2026-09-23): on the page, `NoPartIdOfANamedPartIsVisible`, guarded by a fixture finding's
`observed` naming a named part so it proves something; in Python, no display title of the
snapshot or heading of `report.md` names a named part by id or is cut, where the recorded titles
did both. `EveryTitleIsTheBackendsStringVerbatim` adds that every card, Start-here row and line
behind "Show all" prints the fixture's `title` character for character - the page builds no
title.

*Amended 2026-09-26 by feature 013 T054:* the Review tab has no Start here, so the scan looks for
none. `EveryCardTitleIsTheBackendsStringVerbatim` checks every card's title wherever the card
stands - its row or the holding list; `EveryRowTitleAndGroupHeadingIsTheBackendsStringVerbatim`
and `TheDefaultViewShowsTheGroupHeadingsAndTheRowsOfEveryOpenGroup` check the grouped rows' titles
and the group headings against the fixture's own groups, and are skipped until 013 T056
regenerates the fixture with them.
