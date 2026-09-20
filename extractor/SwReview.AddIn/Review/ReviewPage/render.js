/*
  The Review page's renderers (T041).

  Everything here builds DOM and nothing here talks to anything: no `window.chrome.webview`,
  no `fetch`, no page state. That is what lets the security test (T042a) call `findingCard`
  and `toolCard` inside the real page, with the real CSP, and ask the browser what actually
  landed in the DOM - and it is also why `app.js` renders its transcript through these same
  functions rather than through a second, untested copy of them.

  The one rule that matters more than any other in this file: every string that came from the
  model or from a reviewed document - a text delta, a tool's `result_summary`, a finding's
  `title` and `recommended_action`, drawing text read off a sheet, an evidence question, an
  error message - reaches the screen through `document.createTextNode` and through nothing
  else (FR-029). There is no `innerHTML` here and there is no place where markup is assembled
  from a string. A finding title is written by a language model reading a reviewed assembly;
  treating it as markup would make the Task Pane the most convenient injection point in the
  workstation.

  Actions are declared, not wired. Every button carries `data-action` (and the card carries
  `data-finding-id` / `data-request-id`), and `app.js` listens once on the transcript and reads
  those attributes. That keeps this file pure, keeps every handler in `addEventListener` (no
  inline handler anywhere, which the CSP would refuse in any case), and means a card built by
  a test behaves exactly like a card built by the page.
*/

(function () {
  'use strict';

  // ---- DOM helpers --------------------------------------------------------------------

  /*
    `el`, `write`, `clear`, `append`, `button`, `field`, `list`, `scalar`, `compact` and
    `seconds` live in `web/shared/dom.js`, loaded by index.html before this file and shared
    with the Model check page (T080). They are not copied here: they are the single
    enforcement point for "every untrusted string reaches the screen through
    createTextNode", and a rule with two copies has one that is out of date.
  */
  var dom = window.SwReviewDom;
  var el = dom.el;
  var write = dom.write;
  var clear = dom.clear;
  var append = dom.append;
  var button = dom.button;
  var field = dom.field;
  var list = dom.list;
  var scalar = dom.scalar;
  var compact = dom.compact;
  var seconds = dom.seconds;

  /**
   * The heading over the ranked rows. The same words the report's own section uses, and the
   * same words the two check tabs print, because it is the same ranking: an engineer who reads
   * the pane and then opens `report.md` must find the same rows under the same name
   * (contracts/attention.md section 3).
   */
  var ATTENTION_HEADING = 'Start here';

  /**
   * The fallback when a ranking arrives with no rows and no sentence of its own. The backend
   * always sends one (FR-024); this is what the panel says rather than standing empty if it
   * ever does not.
   */
  var NOTHING_TO_START_WITH = 'Nothing to start with.';

  /**
   * What the coverage fold is called. Not "Coverage": the fold is closed until an engineer asks
   * for it, and the question it answers when they do is what the review did not reach.
   */
  var COVERAGE_HEADING = 'Not reached';

  /**
   * The separator between the small facts that share a line, as an escape rather than as the
   * character itself: every other page file in the pane is ASCII, and a source file that is
   * the only one carrying a byte above 127 is the one an editor re-saves in the wrong codepage.
   */
  var DOT = ' · ';

  /**
   * The stripe a ranked row carries, by the consequence class the backend already assigned it
   * (contracts/attention.md section 1, key 3). An object literal rather than an array: this is
   * a map from a class the policy named to a hue, and it puts nothing before anything - the
   * order of the rows is the ranking's and is never touched here. `PageRuleScanTests` scans
   * array literals for exactly that reason.
   */
  var CONSEQUENCE_STRIPE = {
    rebuild_breaker: 'stripe-critical',
    manufacturing: 'stripe-critical',
    interface: 'stripe-judge',
    discipline: 'stripe-warn',
    hygiene: 'stripe-quiet',
    unclassified: 'stripe-quiet'
  };

  /**
   * The stripe for a row only an engineer can settle. It is read off the ranking's own key -
   * `key.judgement`, contracts/attention.md section 1 key 2, where 0 means "needs your
   * judgement" - and not off the row's severity or status, which this page never compares.
   */
  var JUDGEMENT_STRIPE = 'stripe-judge';

  /** A consequence class the table above does not name still gets a stripe, the quietest one. */
  var DEFAULT_STRIPE = 'stripe-quiet';

  // ---- formatting ---------------------------------------------------------------------

  function location(reference) {
    if (!reference) {
      return '';
    }
    var parts = [];
    if (reference.document_id) {
      parts.push(String(reference.document_id));
    }
    if (reference.sheet) {
      parts.push('sheet ' + reference.sheet);
    }
    if (reference.view) {
      parts.push('view ' + reference.view);
    }
    if (reference.annotation) {
      parts.push(String(reference.annotation));
    }
    if (typeof reference.page === 'number') {
      parts.push('page ' + reference.page);
    }
    return parts.join(' ');
  }

  function locations(references) {
    if (!references || !references.length) {
      return '';
    }
    var parts = [];
    for (var index = 0; index < references.length; index++) {
      var described = location(references[index]);
      if (described) {
        parts.push(described);
      }
    }
    return parts.join('; ');
  }

  /**
   * A tool's arguments, indented. `dom.compact` is the one-line form every other card uses and
   * is shared with the Model check page; a call's arguments are the one place on this page
   * where the shape matters more than the width, and they are inside a fold, so they are
   * printed rather than crammed.
   */
  function pretty(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }

  /**
   * One line built out of the small facts that are worth having but not worth a row each.
   * Absent ones are skipped, so a line never reads "demonstrated, then nothing, then nothing"
   * and a result with no units never reads "0.012 " with a space hanging off it.
   */
  function joined(values, separator) {
    var parts = [];
    for (var index = 0; index < values.length; index++) {
      var value = values[index];
      if (value !== null && value !== undefined && value !== '') {
        parts.push(String(value));
      }
    }
    return parts.join(separator);
  }

  // ---- what Show in SOLIDWORKS can ask for ---------------------------------------------

  /**
   * The `entity.show` payload for a finding, or null when the finding carries no persistent
   * reference.
   *
   * Findings name components by id; the persistent reference travels on the finding's
   * `drawing_locations` (`SourceRef.persist_ref` with the `document_id` that produced it,
   * ir.schema.json), which is the only place in the event stream a reference appears. A
   * finding with no reference is a normal outcome - a check that reasoned over the IR alone -
   * and the card says so with the component ids instead of sending the host a request it has
   * already documented it will refuse.
   */
  function entityRequest(finding) {
    var references = (finding && finding.drawing_locations) || [];
    for (var index = 0; index < references.length; index++) {
      var reference = references[index];
      if (reference && reference.persist_ref) {
        return {
          persist_ref: String(reference.persist_ref),
          persist_ref_scope: reference.document_id ? String(reference.document_id) : null,
          component_id: firstComponent(finding)
        };
      }
    }
    return null;
  }

  function firstComponent(finding) {
    var components = (finding && finding.component_ids) || [];
    return components.length ? String(components[0]) : null;
  }

  // ---- cards ---------------------------------------------------------------------------

  /** A run of assistant or engineer text. `role` styles it; `value` is never trusted. */
  function textBlock(role, value) {
    var block = el('div', 'block ' + role);
    block.appendChild(el('p', 'text', value));
    return block;
  }

  /**
   * One tool call, on one line: how it went, what it was, what came back and how long it took
   * (FR-002). `tool` is a `tool.started` body merged with its `tool.finished` body, so the card
   * can be built when the call starts and filled in when it ends.
   *
   * Tier three. A review makes a dozen of these and none of them is a finding, so the line is
   * as short as it can be and the arguments and the error text fold: the status is a glyph the
   * stylesheet draws from `status-<status>` on the card (an inline &lt;svg&gt; is what the
   * injection test refuses and the CSP would in any case not let an icon file load), and the
   * two paragraphs that used to stand under every call are behind one `<details>`.
   */
  function toolCard(tool) {
    var body = tool || {};
    var status = body.status || 'running';

    var card = el('article', 'card tool status-' + String(status));
    card.setAttribute('data-step-index', String(body.step_index === undefined ? '' : body.step_index));

    var head = el('header', 'card-head');
    head.appendChild(el('span', 'tool-status'));
    head.appendChild(el('span', 'tool-name mono', body.tool || 'tool'));
    head.appendChild(el('span', 'tool-summary', body.result_summary));
    var elapsed = seconds(body.elapsed_s);
    if (elapsed) {
      head.appendChild(el('span', 'elapsed', elapsed));
    }
    card.appendChild(head);

    var told = el('details', 'tool-fold');
    var any = false;
    told.appendChild(el('summary', 'tool-fold-head', 'Call detail'));

    if (body.arguments && Object.keys(body.arguments).length) {
      told.appendChild(el('p', 'tool-arguments', pretty(body.arguments)));
      any = true;
    }

    if (body.error) {
      told.appendChild(el('p', 'tool-error', body.error));
      any = true;
    }

    if (any) {
      card.appendChild(told);
    }

    return card;
  }

  /**
   * One finding: one line and a fold (FR-003, FR-004).
   *
   * Tier two. The line states which finding it is, what the backend concluded and how hard, and
   * which check said so; the title is the sentence under it; the observed evidence, when the
   * finding carries any, is the one fact printed before the fold. Everything else - every field
   * feature 001 defines, Show in SOLIDWORKS, and the three dispositions - is inside the fold.
   *
   * Nothing the card used to show has gone; what moved, moved inward. A review that records
   * eight findings printed eight paragraphs of grey pills before this, and an engineer reading
   * the pane could not see where one finding ended and the next began.
   */
  function findingCard(finding) {
    var body = finding || {};
    var severity = String(body.severity || 'info');
    var status = String(body.status || 'unresolved');

    var card = el('article', 'card finding severity-' + severity);
    card.setAttribute('data-finding-id', String(body.id || ''));

    var head = el('header', 'card-head');
    var line = el('div', 'card-line');
    line.appendChild(el('span', 'finding-id mono', body.id));
    // The status and the severity reach a class name by interpolation, never by comparison:
    // the hue is the stylesheet's business and the page compares neither (PageRuleScanTests).
    line.appendChild(el('span', 'chip status-' + status, status));
    line.appendChild(el('span', 'chip sev-' + severity, severity));
    line.appendChild(el('span', 'finding-check mono', body.check));
    head.appendChild(line);
    head.appendChild(el('h3', 'title', body.title || '(untitled finding)'));
    card.appendChild(head);

    if (body.observed) {
      card.appendChild(el('p', 'facts', body.observed));
    }

    var actions = el('div', 'row card-actions');
    actions.appendChild(button('Details', 'expand', 'action expand'));
    card.appendChild(actions);

    card.appendChild(details(body));
    return card;
  }

  /**
   * The two controls a finding carries and the sentence they write, at the bottom of the fold.
   *
   * The three dispositions are one choice, so they are one bordered group rather than three
   * loose buttons beside a text box, and the note travels with them.
   */
  function decisions(body) {
    var tools = el('div', 'row card-tools');

    var show = button('Show in SOLIDWORKS', 'show', 'action show');
    if (!entityRequest(body)) {
      // Honest rather than hopeful: the finding carries no persistent reference, so the button
      // is drawn as the refusal it would be and the fold names the components instead.
      show.setAttribute('data-reference', 'none');
    }
    tools.appendChild(show);

    var note = el('input', 'note');
    note.setAttribute('type', 'text');
    note.setAttribute('placeholder', 'Note (optional)');
    tools.appendChild(note);

    var group = el('span', 'seg');
    group.appendChild(button('Accept', 'accept', 'action accept'));
    group.appendChild(button('Reject', 'reject', 'action reject'));
    group.appendChild(button('Defer', 'defer', 'action defer'));
    tools.appendChild(group);

    return tools;
  }

  /**
   * The disposition sentence, and the class that says there is one. `app.js` rewrites both when
   * a decision is recorded, so the two agree about what a settled finding looks like.
   */
  function dispositionClass(text) {
    return text ? 'card-status decided' : 'card-status';
  }

  function dispositionText(disposition) {
    if (!disposition || !disposition.decision) {
      return '';
    }
    var text = 'Disposition: ' + disposition.decision;
    if (disposition.by) {
      text += ' by ' + disposition.by;
    }
    if (disposition.at) {
      text += ' at ' + disposition.at;
    }
    if (disposition.note) {
      text += ' - ' + disposition.note;
    }
    return text;
  }

  /**
   * The expandable half of a finding card: every field feature 001 defines (FR-003), then the
   * two controls.
   *
   * `id` and `check` are not repeated here - they are the first two things on the line above -
   * and `observed` is not repeated either when the card already printed it as its facts line.
   * Everything else the finding carries is here, including the two carry-over fields, which
   * this card dropped until now: a verdict this run did not compute but carried over from an
   * earlier session is a different claim from one it computed, and an engineer reading a
   * finding is owed that in the same place as its provenance.
   */
  function details(body) {
    var panel = el('div', 'details');
    panel.hidden = true;

    append(panel, [
      labelled([
        ['Affects', list(body.component_ids) || locations(body.drawing_locations)],
        ['Requirement', body.requirement],
        ['Recommended', body.recommended_action],
        ['Inputs', list(body.inputs)],
        ['Configuration', body.configuration]
      ]),
      body.calculation ? calculation(body.calculation) : null,
      labelled([
        ['Coverage limits', list(body.coverage_limits)],
        ['Drawing locations', locations(body.drawing_locations)],
        ['Tool results', list(body.tool_result_ids)],
        ['Captures', list(body.capture_ids)],
        ['Group', body.group ? body.group.key + ': ' + list(body.group.member_component_ids) : ''],
        ['Exception', body.exception_id],
        ['Provenance', provenance(body.provenance)],
        ['Carried over from', body.carried_over_from],
        ['Carried over at', body.carried_over_at]
      ]),
      decisions(body)
    ]);

    var text = dispositionText(body.disposition);
    panel.appendChild(el('p', dispositionClass(text), text));
    return panel;
  }

  /**
   * A run of labelled rows as one two-column list, or nothing at all when every value is empty.
   * A `<dl>` rather than the flex rows `dom.field` builds because these are a definition list
   * and a grid can hold the label column to one width whatever the label says - "Drawing
   * locations" used to overflow its 90 px gutter and push its value onto a second line.
   */
  function labelled(pairs) {
    var kv = el('dl', 'kv');
    var any = false;

    for (var index = 0; index < pairs.length; index++) {
      var value = pairs[index][1];
      if (value === null || value === undefined || value === '') {
        continue;
      }
      kv.appendChild(el('dt', '', pairs[index][0]));
      kv.appendChild(el('dd', '', value));
      any = true;
    }

    return any ? kv : null;
  }

  function provenance(entries) {
    if (!entries || !entries.length) {
      return '';
    }
    var parts = [];
    for (var index = 0; index < entries.length; index++) {
      var entry = entries[index] || {};
      var line = String(entry.vault_path || entry.document_id || '');
      if (entry.revision) {
        line += ' rev ' + entry.revision;
      }
      if (entry.vault_version !== null && entry.vault_version !== undefined) {
        line += ' v' + entry.vault_version;
      }
      if (entry.configuration) {
        line += ' [' + entry.configuration + ']';
      }
      if (entry.local_modified) {
        line += ' (modified locally)';
      }
      parts.push(line);
    }
    return parts.join('; ');
  }

  /**
   * The calculation behind a finding, shown in full: the model, its inputs, what it assumed
   * and what it left out. A number with no assumptions beside it is the thing the constitution
   * forbids (Principle II).
   *
   * An empty row is skipped here as it is everywhere else in the fold. This block used to print
   * all six whatever the calculation carried, so a finding computed by a model with nothing
   * excluded showed "Excluded effects" against a blank - which reads as a claim that the
   * question was asked and answered with nothing, not as a field the calculation never filled.
   */
  function calculation(math) {
    var panel = el('div', 'calculation');
    var kv = labelled([
      ['Model', math.model],
      ['Function', joined([math.function, math.function_version], ' ')],
      ['Inputs', math.inputs ? compact(math.inputs) : ''],
      ['Assumptions', list(math.assumptions)],
      ['Excluded effects', list(math.excluded_effects)],
      ['Result', joined([scalar(math.result), math.units_out], ' ')]
    ]);

    if (kv) {
      panel.appendChild(kv);
    }
    return panel;
  }

  /**
   * An evidence request: the question, why it is being asked, and a box to answer it in
   * (FR-005). An answered request keeps the answer on the card.
   */
  function evidenceCard(request) {
    var body = request || {};
    var card = el('article', 'card evidence status-' + String(body.status || 'open'));
    card.setAttribute('data-request-id', String(body.id || ''));

    var head = el('header', 'card-head');
    head.appendChild(el('span', 'chip evidence-status', body.status || 'open'));
    head.appendChild(el('h3', 'title', 'The review needs an input'));
    card.appendChild(head);

    card.appendChild(el('p', 'question', body.what));
    if (body.why) {
      card.appendChild(field('Why', body.why));
    }
    if (body.entity_ids && body.entity_ids.length) {
      card.appendChild(field('About', list(body.entity_ids)));
    }

    if (body.status === 'answered') {
      card.appendChild(field('Answer', body.answer));
      return card;
    }

    var row = el('div', 'row answer-row');
    var answer = el('input', 'answer');
    answer.setAttribute('type', 'text');
    answer.setAttribute('placeholder', 'Your answer');
    row.appendChild(answer);
    row.appendChild(button('Send answer', 'answer', 'action answer-send'));
    card.appendChild(row);

    card.appendChild(el('p', 'card-status', ''));
    return card;
  }

  /**
   * A failure the engineer can act on: what went wrong, and the three moves that ever help -
   * try the review again as a new session that says which one it replaces (FR-028), fix the
   * settings, or read the log.
   */
  function errorCard(error) {
    var body = error || {};
    var card = el('article', 'card error');

    var head = el('header', 'card-head');
    head.appendChild(el('span', 'chip error-class', body.error_class || 'Error'));
    head.appendChild(el('h3', 'title', 'The review stopped'));
    card.appendChild(head);

    card.appendChild(el('p', 'message', body.message || 'the backend reported an error'));

    var row = el('div', 'row card-actions');
    row.appendChild(button('Retry', 'retry', 'action retry'));
    row.appendChild(button('Open Settings', 'settings', 'action settings'));
    row.appendChild(button('View log', 'log', 'action log'));
    card.appendChild(row);

    card.appendChild(el('p', 'card-status', ''));
    return card;
  }

  /**
   * What the review did and did not look at, as one summary that is rebuilt on every
   * `coverage` event rather than appended to - a bucket's contents are the whole truth about
   * it, and a list that only grows would show a re-run's items twice (constitution Principle
   * III: silence is not coverage).
   */
  function coverageSummary(entries) {
    var order = ['checked', 'skipped', 'unresolved', 'failed', 'out_of_scope'];
    var buckets = {};
    var index;

    for (index = 0; index < order.length; index++) {
      buckets[order[index]] = [];
    }
    for (index = 0; index < (entries || []).length; index++) {
      var entry = entries[index] || {};
      var bucket = buckets[entry.bucket] || (buckets[entry.bucket] = []);
      bucket.push(entry.item || {});
    }

    // Tier three: 62 rows of "the run did not reach this" is a true and unreadable list, so the
    // whole of it folds behind the one line that says how much of it there is. The counts and
    // the groups below are both walked in `order`, which is the display order this page has
    // always used and the one PageRuleScanTests pins by its words.
    var counts = [];
    var groups = [];
    for (index = 0; index < order.length; index++) {
      var name = order[index];
      var items = buckets[name];
      if (!items.length) {
        continue;
      }
      counts.push(items.length + ' ' + bucketLabel(name));
      groups.push(coverageBucket(name, items));
    }

    var panel = el('section', 'coverage');
    var fold = el('details', 'coverage-fold');

    var head = el('summary', 'coverage-head');
    head.appendChild(el('h3', 'eyebrow coverage-heading', COVERAGE_HEADING));
    head.appendChild(el('span', 'fold-count', counts.join(DOT)));
    fold.appendChild(head);

    var body = el('div', 'fold-body');
    if (groups.length) {
      append(body, groups);
    } else {
      body.appendChild(el('p', 'coverage-empty', 'No coverage reported yet.'));
    }

    fold.appendChild(body);
    panel.appendChild(fold);
    return panel;
  }

  /** A bucket's name as a reader says it: `out_of_scope` is three words on screen. */
  function bucketLabel(name) {
    return String(name).replace(/_/g, ' ');
  }

  /**
   * What to start with: the rows the backend ranked, in the order it supplied them.
   *
   * Rebuilt from the whole ranking on every call, like `coverageSummary` beside it and for the
   * same reason - the ranking is the whole truth about what to look at first, and a panel that
   * only grew would show a re-run's rows twice.
   *
   * This amplifies; it never filters. Every finding is still in the transcript above and in
   * `report.md`, and the rows here are the ones `report/attention.py` placed first, with the
   * same ids and the same reasons the report's "Start here" section prints
   * (contracts/attention.md sections 3 and 6). So nothing here reads a severity, compares two
   * rows or knows how many there ought to be: it reads `rows`, takes the first `top_n`, and
   * prints three of each row's fields. `PageRuleScanTests` is the test that keeps it that way.
   *
   * The same three states the two check tabs render, deliberately built the same way in the
   * same words. They cannot be one function: this page loads `render.js` and `shared/dom.js`
   * and the check tabs load `shared/check-page.js`, which is the larger half of a check page
   * and has no business on a chat transcript. What is shared is `dom.js` - the one place a
   * string becomes a text node - and the class names, so the two look alike because they are
   * styled from the same vocabulary rather than because someone matched them by eye.
   */
  function attentionPanel(ranking) {
    var panel = el('section', 'attention');
    panel.appendChild(el('h3', 'eyebrow attention-heading', ATTENTION_HEADING));

    var rows = (ranking && !ranking.empty_reason) ? amplified(ranking) : [];
    if (!rows.length) {
      panel.appendChild(el(
        'p', 'attention-empty', (ranking && ranking.empty_reason) || NOTHING_TO_START_WITH));
      return panel;
    }

    var list = el('ol', 'attention-rows');
    for (var index = 0; index < rows.length; index++) {
      list.appendChild(attentionRow(rows[index] || {}));
    }
    panel.appendChild(list);
    return panel;
  }

  /**
   * The first `top_n` rows. `rows` holds every row the policy ranked, suppressed ones last,
   * and `top_n` is how many of them it chose to amplify - a page that printed the whole array
   * would be overruling that choice. A ranking carrying no usable `top_n` prints what it was
   * given rather than nothing.
   */
  function amplified(ranking) {
    var rows = ranking.rows || [];
    var count = ranking.top_n;
    return (typeof count === 'number' && count >= 0 && count < rows.length)
      ? rows.slice(0, count)
      : rows;
  }

  /**
   * One ranked row: which finding, the reason the policy placed it, what it says, which check
   * said it, and the state it is in.
   *
   * Tier one, and the widest card on the page. Until now the row printed three fields out of
   * the ten the backend sends (contracts/attention.md section 4), so the panel that is supposed
   * to be the first thing read said less about a finding than the finding's own card did.
   *
   * The stripe is the one piece of colour here, and it restates a field rather than adding a
   * judgement of its own: `consequence_class` through a map, or the judgement key when the
   * policy marked the row as one only an engineer can settle. Nothing reads a severity, nothing
   * compares two rows, and nothing sorts - the order is the ranking's whole statement.
   */
  function attentionRow(row) {
    var item = el('li', 'attention-row ' + stripeOf(row));
    item.setAttribute('data-finding-id', String(row.finding_id || ''));
    append(item, [
      el('span', 'attention-id', row.finding_id || ''),
      el('span', 'attention-reason', row.reason || ''),
      el('span', 'attention-title', row.title || ''),
      el('span', 'attention-check', row.check || ''),
      attentionMeta(row)
    ]);
    if (typeof row.explanation === 'string' && row.explanation) {
      item.appendChild(el('p', 'finding-explanation', row.explanation));
    }
    return item;
  }

  /**
   * The state a ranked row is in, as the backend already reported it: the status and the
   * severity as words, and the components the row reaches in the face an id is read in. Read,
   * never compared - the words are printed as they arrived.
   */
  function attentionMeta(row) {
    var meta = el('span', 'attention-meta', joined([row.status, row.severity], DOT));
    var components = list(row.component_ids);
    if (components) {
      if (meta.firstChild) {
        write(meta, DOT);
      }
      meta.appendChild(el('span', 'mono', components));
    }
    return meta;
  }

  /**
   * Which stripe a ranked row carries. `key.judgement` is the ranking's own second key and it
   * is 0 for the rows the policy says only an engineer can settle, which is the one thing about
   * a row that outranks what kind of consequence it has (contracts/attention.md section 1).
   *
   * A consequence class that is not in the map - one the policy file added, or a value that
   * happens to name something on `Object.prototype` - falls back to the quiet stripe rather
   * than to whatever the prototype chain answers with.
   */
  function stripeOf(row) {
    var key = row.key || {};
    if (key.judgement === 0) {
      return JUDGEMENT_STRIPE;
    }

    var stripe = CONSEQUENCE_STRIPE[row.consequence_class];
    return (typeof stripe === 'string') ? stripe : DEFAULT_STRIPE;
  }

  function coverageBucket(name, items) {
    var group = el('div', 'coverage-bucket bucket-' + name);
    group.appendChild(el('h4', 'bucket-name', bucketLabel(name) + DOT + items.length));

    var lines = el('ul', 'bucket-items');
    for (var index = 0; index < items.length; index++) {
      var item = items[index] || {};
      var line = el('li', 'bucket-item', String(item.check || ''));
      if (item.reason) {
        write(line, ' - ' + item.reason);
      }
      if (item.error) {
        write(line, ' [' + item.error + ']');
      }
      lines.appendChild(line);
    }

    group.appendChild(lines);
    return group;
  }

  // ---- the running usage line (feature 005 T016a) --------------------------------------

  /**
   * What this review has cost so far: the tokens, the cached share, the round trips and the
   * latency of the last round, from the `usage` events the page has already received
   * (specs/005-llm-efficiency/contracts/usage.md section 5).
   *
   * Pure, and it does the summing as well as the rendering, so the one rule that matters here
   * is testable inside the real page: **any null in a field makes that total null**, never a
   * partial sum, which is the arithmetic `SessionUsage.summed` defines rather than a second
   * rule (section 1). A field the endpoint omitted is unknown, not zero: "0 cached tokens" and
   * "the endpoint did not say" send an engineer to different places, and the cached share is
   * the second of those until the provider reports one (FR-047).
   *
   * It is fed the event bodies as they arrive rather than the session's own total, so the line
   * moves while the turn is still running - which is the whole point of it - and
   * `GET /sessions/{chat_id}` is left alone.
   */
  function usageLine(rounds) {
    var list = rounds || [];
    var line = el('span', 'usage');

    if (!list.length) {
      write(line, 'No model round trips yet.');
      return line;
    }

    var tokens = totalOf(list, function (round) { return round.total_tokens; });
    var input = totalOf(list, function (round) { return round.input_tokens; });
    var cached = totalOf(list, function (round) { return round.cached_input_tokens; });
    var round = list[list.length - 1] || {};
    var latency = seconds(round.latency_s);

    write(line, tokens === null ? 'tokens unknown' : tokens + ' tokens');
    write(line, ' - cached ' + (share(cached, input) === null ? 'unknown' : share(cached, input) + '%'));
    write(line, ' - ' + list.length + ' round trip' + (list.length === 1 ? '' : 's'));
    write(line, ' - last round ' + (latency === '' ? 'unknown' : latency));
    return line;
  }

  /** The sum of one field over every round, or null if any round did not report it. */
  function totalOf(rounds, read) {
    var sum = 0;
    for (var index = 0; index < rounds.length; index++) {
      var value = read(rounds[index] || {});
      if (typeof value !== 'number' || !isFinite(value)) {
        return null;
      }
      sum += value;
    }
    return sum;
  }

  /** The cached percentage, or null when either side is unknown or there is nothing to divide. */
  function share(cached, input) {
    if (cached === null || input === null || input <= 0) {
      return null;
    }
    return Math.round((cached / input) * 100);
  }

  window.SwReviewRender = {
    el: el,
    write: write,
    clear: clear,
    append: append,
    field: field,
    list: list,
    textBlock: textBlock,
    toolCard: toolCard,
    findingCard: findingCard,
    dispositionText: dispositionText,
    dispositionClass: dispositionClass,
    evidenceCard: evidenceCard,
    errorCard: errorCard,
    coverageSummary: coverageSummary,
    attentionPanel: attentionPanel,
    entityRequest: entityRequest,
    usageLine: usageLine
  };
})();
