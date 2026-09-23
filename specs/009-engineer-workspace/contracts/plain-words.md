# Contract: Plain Words Everywhere the Engineer Looks

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
| `report.md`: each finding's heading and Start here's titled rows (`render_report`, every caller) | `display_title`, and `with_display_titles` on the ranking it is given |

`with_display_titles` replaces the title of every row with its survivor's (`row.finding_id`)
display title; a folded family's row keeps its family title, and a row whose finding is not among
`findings` keeps its title. Order, keys, reasons and every other field are the ranking's own, and
applying it twice changes nothing. The page prints `title` verbatim wherever it arrives; it builds
no title. `observed` keeps its ids everywhere. No golden baseline moves: they pin recorded titles.

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

*Landed as* (T065, `test_plain_words_fixture.py`): the page scan runs the last three checks and the
backend test the summary half; the `cmp:` checks on both sides wait for T062 (section 2), and a
probe of the page check on this tree finds exactly the interference titles it would change.
