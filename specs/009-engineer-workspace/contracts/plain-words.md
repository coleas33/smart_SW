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

`tools/recording.title_from(observed, names=None)` returns the first sentence of `observed`
(split on ". "), trimmed, with every `cmp:` id whose name is non-blank replaced by the name
(`report/names.with_component_names`), and never cut. `TITLE_LENGTH` is removed. `result_to_finding`
and `record_drawing_finding` pass `component_names(context.ir)`. `observed` keeps its ids. The page's
two-line clamp is the only length limit. The golden baselines that held a cut title are regenerated
once; their diff touches `title:` lines only.

## 3. Names instead of ids

| Surface | Name | Id |
|---|---|---|
| finding title | backend (section 2) | `observed` and "Affects" in the fold |
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

The backend half is a Python test on the same fixture: no finding title holds a `cmp:` id whose
component has a non-blank name, and no summary word holds a check id or a raw token.
