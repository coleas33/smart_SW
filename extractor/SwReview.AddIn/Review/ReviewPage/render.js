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

  /** An element with an optional class and an optional run of literal text. */
  function el(tag, className, value) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (value !== undefined && value !== null && value !== '') {
      node.appendChild(document.createTextNode(String(value)));
    }
    return node;
  }

  /** Appends literal text to a node. The only way text ever enters this page. */
  function write(node, value) {
    node.appendChild(document.createTextNode(String(value === undefined || value === null ? '' : value)));
    return node;
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
    return node;
  }

  function append(parent, children) {
    for (var index = 0; index < children.length; index++) {
      if (children[index]) {
        parent.appendChild(children[index]);
      }
    }
    return parent;
  }

  function button(label, action, className) {
    var node = el('button', className || 'action', label);
    node.setAttribute('type', 'button');
    node.setAttribute('data-action', action);
    return node;
  }

  /** A labelled row in a card's detail list. Absent values are skipped by the caller. */
  function field(label, value) {
    var row = el('div', 'field-row');
    row.appendChild(el('span', 'field-label', label));
    row.appendChild(el('span', 'field-value', value));
    return row;
  }

  // ---- formatting ---------------------------------------------------------------------

  /**
   * Values are formatted rather than interpolated, so a card never shows `[object Object]`
   * and never shows `undefined` where a field was simply absent.
   */
  function list(values) {
    if (!values || !values.length) {
      return '';
    }
    var parts = [];
    for (var index = 0; index < values.length; index++) {
      parts.push(scalar(values[index]));
    }
    return parts.join(', ');
  }

  function scalar(value) {
    if (value === null || value === undefined) {
      return '';
    }
    if (typeof value === 'object') {
      return compact(value);
    }
    return String(value);
  }

  /** JSON, as text. Used for tool arguments and any nested object a card shows. */
  function compact(value) {
    try {
      return JSON.stringify(value);
    } catch (error) {
      return String(value);
    }
  }

  function seconds(value) {
    return typeof value === 'number' && isFinite(value) ? value.toFixed(2) + ' s' : '';
  }

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
   * One tool call: name, arguments, status, elapsed, and the model's one-line summary of
   * what came back (FR-002). `tool` is a `tool.started` body merged with its `tool.finished`
   * body, so the card can be built when the call starts and filled in when it ends.
   */
  function toolCard(tool) {
    var body = tool || {};
    var status = body.status || 'running';

    var card = el('article', 'card tool status-' + String(status));
    card.setAttribute('data-step-index', String(body.step_index === undefined ? '' : body.step_index));

    var head = el('header', 'card-head');
    head.appendChild(el('span', 'badge tool-status', status));
    head.appendChild(el('span', 'tool-name', body.tool || 'tool'));
    var elapsed = seconds(body.elapsed_s);
    if (elapsed) {
      head.appendChild(el('span', 'elapsed', elapsed));
    }
    card.appendChild(head);

    if (body.arguments && Object.keys(body.arguments).length) {
      card.appendChild(el('p', 'tool-arguments', compact(body.arguments)));
    }

    if (body.result_summary) {
      card.appendChild(el('p', 'tool-summary', body.result_summary));
    }

    if (body.error) {
      card.appendChild(el('p', 'tool-error', body.error));
    }

    return card;
  }

  /**
   * One finding: status, severity, title, affected components or drawing locations, Show in
   * SOLIDWORKS, an expandable body with every field feature 001 defines, and the three
   * dispositions with a note (FR-003, FR-004).
   */
  function findingCard(finding) {
    var body = finding || {};
    var card = el('article', 'card finding severity-' + String(body.severity || 'info'));
    card.setAttribute('data-finding-id', String(body.id || ''));

    var head = el('header', 'card-head');
    head.appendChild(el('span', 'badge severity', body.severity || 'info'));
    head.appendChild(el('span', 'badge status', body.status || 'unresolved'));
    head.appendChild(el('h3', 'title', body.title || '(untitled finding)'));
    card.appendChild(head);

    var where = list(body.component_ids) || locations(body.drawing_locations);
    if (where) {
      card.appendChild(field('Affects', where));
    }

    if (body.recommended_action) {
      card.appendChild(field('Recommended', body.recommended_action));
    }

    var actions = el('div', 'row card-actions');
    var show = button('Show in SOLIDWORKS', 'show', 'action show');
    if (!entityRequest(body)) {
      // Honest rather than hopeful: the finding carries no persistent reference, so the card
      // offers the component ids and the button explains itself instead of failing on press.
      show.setAttribute('data-reference', 'none');
    }
    actions.appendChild(show);
    actions.appendChild(button('Details', 'expand', 'action expand'));
    card.appendChild(actions);

    card.appendChild(details(body));

    var decide = el('div', 'row disposition');
    var note = el('input', 'note');
    note.setAttribute('type', 'text');
    note.setAttribute('placeholder', 'Note (optional)');
    decide.appendChild(note);
    decide.appendChild(button('Accept', 'accept', 'action accept'));
    decide.appendChild(button('Reject', 'reject', 'action reject'));
    decide.appendChild(button('Defer', 'defer', 'action defer'));
    card.appendChild(decide);

    card.appendChild(el('p', 'card-status', dispositionText(body.disposition)));
    return card;
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

  /** The expandable half of a finding card: every field feature 001 defines (FR-003). */
  function details(body) {
    var panel = el('div', 'details');
    panel.hidden = true;

    var rows = [
      ['Finding', body.id],
      ['Check', body.check],
      ['Configuration', body.configuration],
      ['Observed', body.observed],
      ['Requirement', body.requirement],
      ['Inputs', list(body.inputs)],
      ['Coverage limits', list(body.coverage_limits)],
      ['Drawing locations', locations(body.drawing_locations)],
      ['Tool results', list(body.tool_result_ids)],
      ['Captures', list(body.capture_ids)],
      ['Group', body.group ? body.group.key + ': ' + list(body.group.member_component_ids) : ''],
      ['Exception', body.exception_id],
      ['Provenance', provenance(body.provenance)]
    ];

    for (var index = 0; index < rows.length; index++) {
      var value = rows[index][1];
      if (value !== null && value !== undefined && value !== '') {
        panel.appendChild(field(rows[index][0], value));
      }
    }

    if (body.calculation) {
      panel.appendChild(calculation(body.calculation));
    }

    return panel;
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
   */
  function calculation(math) {
    var panel = el('div', 'calculation');
    panel.appendChild(field('Model', math.model));
    panel.appendChild(field('Function', String(math.function || '') + ' ' + String(math.function_version || '')));
    panel.appendChild(field('Inputs', compact(math.inputs)));
    panel.appendChild(field('Assumptions', list(math.assumptions)));
    panel.appendChild(field('Excluded effects', list(math.excluded_effects)));
    panel.appendChild(field('Result', scalar(math.result) + ' ' + String(math.units_out || '')));
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
    head.appendChild(el('span', 'badge evidence-status', body.status || 'open'));
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
    head.appendChild(el('span', 'badge error-class', body.error_class || 'Error'));
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

    var panel = el('section', 'coverage');
    panel.appendChild(el('h3', 'coverage-heading', 'Coverage'));

    var any = false;
    for (index = 0; index < order.length; index++) {
      var name = order[index];
      var items = buckets[name];
      if (!items.length) {
        continue;
      }
      any = true;
      panel.appendChild(coverageBucket(name, items));
    }

    if (!any) {
      panel.appendChild(el('p', 'coverage-empty', 'No coverage reported yet.'));
    }
    return panel;
  }

  function coverageBucket(name, items) {
    var group = el('div', 'coverage-bucket bucket-' + name);
    group.appendChild(el('h4', 'bucket-name', name + ' (' + items.length + ')'));

    var rows = el('ul', 'bucket-items');
    for (var index = 0; index < items.length; index++) {
      var item = items[index] || {};
      var row = el('li', 'bucket-item', String(item.check || ''));
      if (item.reason) {
        write(row, ' - ' + item.reason);
      }
      if (item.error) {
        write(row, ' [' + item.error + ']');
      }
      rows.appendChild(row);
    }

    group.appendChild(rows);
    return group;
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
    evidenceCard: evidenceCard,
    errorCard: errorCard,
    coverageSummary: coverageSummary,
    entityRequest: entityRequest
  };
})();
