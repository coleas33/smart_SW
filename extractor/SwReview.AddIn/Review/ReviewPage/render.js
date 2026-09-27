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

  /*
    `web/shared/attention.js` holds the check tabs' Start-here row and the pieces every tab that
    shows the ranking shares: the stripe map (`stripeOf`), the label lookup and the separator,
    loaded before this file. The Review tab shows no Start here since feature 013 - its grouped
    findings replaced it (contracts/grouped-list.md section 5) - and its grouped rows take their
    stripe from the same one map, so a row reads the same on every tab.
  */
  var attention = window.SwReviewAttention;
  var DOT = attention.DOT;

  /*
    The backend's card vocabulary (`GET /labels`, feature 009 FR-024) reaches these renderers as
    an argument - `labels` - and is looked up through the shared script's one prototype-guarded
    `labelOf`: no labels, a token they do not name, or a token naming something on
    `Object.prototype` prints what this page printed before, so an older backend renders exactly
    as it did (FR-030). This file holds no words of its own for any of them.
  */
  var labelOf = attention.labelOf;

  /**
   * What the coverage fold is called. Not "Coverage": the fold is closed until an engineer asks
   * for it, and the question it answers when they do is what the review did not reach.
   */
  var COVERAGE_HEADING = 'Not reached';

  /**
   * The free-text box's placeholder: the page's own word for a question with no offered answers,
   * and the fallback beside the buttons of a question that allows text when the backend's labels
   * carry no `questions.text_placeholder` (FR-030).
   */
  var ANSWER_PLACEHOLDER = 'Your answer';

  /** The unit a contact's overlap volume is recorded in (feature 010's `volume_mm3`), as an escape. */
  var CUBIC_MILLIMETRES = 'mm\u00b3';

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
   * Where a finding was recorded, as one line in the Transcript: "F-007 recorded: <title>"
   * (feature 009 User Story 5, contracts/views.md section 5). The finding's card lives in
   * Results; a card cannot stand in two places, so the chronology keeps this line where the
   * card used to interrupt the prose.
   */
  function findingMarker(finding) {
    var body = finding || {};
    return marker(String(body.id || ''), ' recorded: ' + String(body.title || ''));
  }

  /**
   * Where a finding left the session, as one line in the Transcript: "F-003 withdrawn: <reason>"
   * (feature 013, contracts/part-roles.md section 9). An answer regraded the review and no check
   * produces the finding any more; the line that recorded it stays, and this one says why it went,
   * in the backend's words.
   */
  function withdrawalMarker(withdrawal) {
    var body = withdrawal || {};
    return marker(String(body.finding_id || ''), ' withdrawn: ' + String(body.reason || ''));
  }

  /** One Transcript line about one finding: its id, then what happened to it. */
  function marker(findingId, words) {
    var block = textBlock('system marker', findingId + words);
    block.setAttribute('data-finding-id', findingId);
    return block;
  }

  /**
   * One follow-up and its answer, pinned in Results (FR-019, contracts/views.md section 4): the
   * question the engineer asked, then the answer once the turn's `text.done` arrives - or, until
   * then, that it is on its way. `answer` is the text itself, or the page's sentence for a turn
   * that ended without one.
   */
  function pinnedAnswer(pin) {
    var body = pin || {};
    var answered = typeof body.answer === 'string';
    var block = el('div', 'pinned');
    block.appendChild(el('p', 'pinned-question', body.question));
    block.appendChild(el(
      'p', answered ? 'pinned-answer' : 'pinned-answer waiting', answered ? body.answer : 'Waiting for the answer.'));
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
   * One finding: a headline and a fold (FR-003, FR-004).
   *
   * Tier two. The head is the line that states which finding it is, what the backend concluded
   * and how hard, and which check said so, and the title under it - and nothing else, so a
   * review reads as a list of headlines (U10, docs/pane-findings-2026-09-20-review-gui.md
   * section 3). Everything else - the observed evidence first, then every field feature 001
   * defines, Show in SOLIDWORKS, and the three dispositions - is inside the fold.
   *
   * Nothing the card used to show has gone; what moved, moved inward. `observed` was the one
   * fact printed before the fold until U10, and its first sentence is the title itself, so a
   * narrow pane stacked the same words twice under every headline and hid the next finding.
   */
  function findingCard(finding, labels) {
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
    // The words on the chips are the backend's labels for them (feature 009 FR-024).
    line.appendChild(el('span', 'chip status-' + status, labelOf(labels, 'status', status, status)));
    line.appendChild(el('span', 'chip sev-' + severity, labelOf(labels, 'severity', severity, severity)));
    // The check id is not on the line since feature 009 (FR-025): it is developer vocabulary, and
    // it is the fold's first labelled row, "Rule" - one press away, never gone.
    head.appendChild(line);
    head.appendChild(el('h3', 'title', body.title || '(untitled finding)'));
    card.appendChild(head);

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
   * The expandable half of a finding card: what was observed, every field feature 001 defines
   * (FR-003), then the two controls.
   *
   * `observed` is the first row, because it is the evidence the verdict rests on and the first
   * thing an engineer who opened the fold is looking for. (`app.js` puts the finding's U5
   * explanation above it once the ranking arrives: the plain-language sentence reads before the
   * evidence it explains.) The first labelled row is "Rule", the check id, which left the line
   * above with feature 009 (FR-025); `id` is not repeated - it is the first thing on the line.
   * Everything else the finding carries is here, including the two
   * carry-over fields: a verdict this run did not compute but carried over from an earlier
   * session is a different claim from one it computed, and an engineer reading a finding is
   * owed that in the same place as its provenance.
   */
  function details(body) {
    var panel = el('div', 'details');
    panel.hidden = true;

    append(panel, [
      body.observed ? el('p', 'facts', body.observed) : null,
      labelled([
        ['Rule', body.check],
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
   * An evidence request, as the transcript's record of it: the question, why it is being asked,
   * what it is about, and - once answered - the answer (FR-005).
   *
   * A record and no longer a form (feature 009 User Story 4, contracts/questions.md section 7):
   * the one way to answer is the questions panel above the findings, which sends every answer the
   * engineer gave in one submission and resumes the review once. A box on each card was a second
   * way in, and each answer through it cost a turn of its own.
   */
  function evidenceCard(request, labels) {
    var body = request || {};
    var lifecycle = String(body.status || 'open');
    var card = el('article', 'card evidence status-' + lifecycle);
    card.setAttribute('data-request-id', String(body.id || ''));

    var head = el('header', 'card-head');
    head.appendChild(el('span', 'chip evidence-status', labelOf(labels, 'evidence_status', lifecycle, lifecycle)));
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
    }
    return card;
  }

  // ---- questions for you (feature 009 User Story 4) ------------------------------------

  /**
   * One open question of the summary's list, asked on its own, with a pager over the rest
   * (contracts/questions.md section 4).
   *
   * `questions` is `summary.questions` - the open requests in the backend's order; the page
   * filters nothing, because which requests are still open is the backend's to say. `draft` is
   * what the engineer has typed, chosen and skipped for this chat, `{answers, skipped}` keyed by
   * request id; `position` is the question on screen. `extras` carries the two lines that are
   * not the question's own: the backend's `resume_text`, printed beside Send (FR-016), and the
   * sentence the last send left, if any.
   *
   * Pure, like every other renderer here: no handler, no state. The buttons declare what they
   * do with `data-action` and `app.js` listens once on the panel; which of them are enabled is
   * `app.js`'s to set, because it depends on the turn and on every question's draft.
   */
  function questionsPanel(questions, draft, position, extras) {
    var asked = questions || {};
    var items = asked.items || [];
    var item = items[position] || {};
    var answers = (draft && draft.answers) || {};
    var skipped = (draft && draft.skipped) || {};
    var more = extras || {};
    var id = String(item.id || '');

    var panel = el('div', 'questions');
    panel.setAttribute('data-request-id', id);

    var pager = el('div', 'question-pager');
    pager.appendChild(el('span', 'question-position', 'Question ' + (position + 1) + ' of ' + scalar(asked.count)));
    pager.appendChild(button('Previous', 'question-previous', 'action question-previous'));
    pager.appendChild(button('Next', 'question-next', 'action question-next'));
    panel.appendChild(pager);

    panel.appendChild(el('p', 'question-text', item.question));
    if (item.blocks_title) {
      panel.appendChild(el('p', 'question-blocks', 'Blocks: ' + item.blocks_title));
    }
    var about = aboutNames(item.about);
    if (about) {
      panel.appendChild(el('p', 'question-about', 'About: ' + about));
    }

    // Offered answers are buttons; a question with none gets one text box; and a question that
    // allows text (`allow_text`, feature 013's part-roles question) gets both - the buttons, then
    // a box whose placeholder is the backend's (contracts/part-roles.md section 8). The draft
    // holds one answer: the text of the button pressed, or what was typed. The box shows a typed
    // answer and stays empty while a button is the answer, so pressing one never copies its words
    // into the box.
    var chosen = ownText(answers, id);
    var options = item.options || [];
    var picked = false;
    if (options.length) {
      var row = el('div', 'question-options');
      for (var index = 0; index < options.length; index++) {
        var pressed = chosen === String(options[index]);
        picked = picked || pressed;
        var option = button(options[index], 'question-option', 'action question-option');
        option.setAttribute('data-option-index', String(index));
        option.setAttribute('aria-pressed', pressed ? 'true' : 'false');
        row.appendChild(option);
      }
      panel.appendChild(row);
    }
    var withText = item.allow_text === true;
    if (!options.length || withText) {
      var box = el('input', 'question-answer');
      box.setAttribute('type', 'text');
      box.setAttribute('placeholder', (options.length && withText)
        ? labelOf(more.labels, 'questions', 'text_placeholder', ANSWER_PLACEHOLDER)
        : ANSWER_PLACEHOLDER);
      box.setAttribute('data-request-id', id);
      box.value = (chosen === null || picked) ? '' : chosen;
      panel.appendChild(box);
    }

    if (Object.prototype.hasOwnProperty.call(skipped, id) && skipped[id] === true) {
      panel.appendChild(el('p', 'question-skipped', 'Skipped for now.'));
    }

    var fold = el('details', 'question-fold');
    fold.appendChild(el('summary', 'question-fold-head', 'Details'));
    append(fold, [
      item.what ? field('Asked', item.what) : null,
      item.why ? field('Why', item.why) : null,
      aboutIds(item.about) ? field('Ids', aboutIds(item.about)) : null
    ]);
    panel.appendChild(fold);

    var actions = el('div', 'row question-actions');
    actions.appendChild(button('Skip for now', 'question-skip', 'action question-skip'));
    actions.appendChild(button('Send answers', 'question-send', 'action primary question-send'));
    if (more.resumeText) {
      actions.appendChild(el('span', 'question-resume', more.resumeText));
    }
    panel.appendChild(actions);

    if (more.note && more.note.error) {
      panel.appendChild(append(el('div', 'question-status bad'), [plainError(more.note.error, more.labels)]));
    } else if (more.note && more.note.text) {
      panel.appendChild(el('p', more.note.bad ? 'question-status bad' : 'question-status', more.note.text));
    }
    return panel;
  }

  /** The draft answer for one request, or null: an own string property only. */
  function ownText(answers, id) {
    return (Object.prototype.hasOwnProperty.call(answers, id) && typeof answers[id] === 'string')
      ? answers[id]
      : null;
  }

  /** "Pin-A-1, Plate-1": each `about` entry by the name the backend gave it, its id where none. */
  function aboutNames(about) {
    var names = [];
    var entries = about || [];
    for (var index = 0; index < entries.length; index++) {
      var entry = entries[index] || {};
      names.push(entry.name ? entry.name : entry.id);
    }
    return list(names);
  }

  /** The ids behind the names, for the question's fold. */
  function aboutIds(about) {
    var ids = [];
    var entries = about || [];
    for (var index = 0; index < entries.length; index++) {
      ids.push((entries[index] || {}).id);
    }
    return list(ids);
  }

  /**
   * A failure the engineer can act on: what went wrong, and the three moves that ever help -
   * try the review again as a new session that says which one it replaces (FR-028), fix the
   * settings, or read the log.
   */
  function errorCard(error, labels) {
    var body = error || {};
    var card = el('article', 'card error');

    // With the backend's labels the card says what to do next and keeps the class and the
    // message in a fold (feature 009 FR-026); with none - an older backend - it reads exactly as
    // it did before, the class as a chip and the message under it (FR-030).
    var head = el('header', 'card-head');
    if (!labels) {
      head.appendChild(el('span', 'chip error-class', body.error_class || 'Error'));
    }
    head.appendChild(el('h3', 'title', 'The review stopped'));
    card.appendChild(head);

    card.appendChild(labels
      ? plainError(body, labels)
      : el('p', 'message', body.message || 'the backend reported an error'));

    var row = el('div', 'row card-actions');
    row.appendChild(button('Retry', 'retry', 'action retry'));
    row.appendChild(button('Open Settings', 'settings', 'action settings'));
    row.appendChild(button('View log', 'log', 'action log'));
    card.appendChild(row);

    card.appendChild(el('p', 'card-status', ''));
    return card;
  }

  /**
   * An error in plain words (feature 009 FR-026, contracts/plain-words.md section 5): the
   * sentence the backend's labels give its class - what the engineer can do next - or, for a
   * class they do not name, its message; and the class and the message behind a shut fold, where
   * they are still one press away. The one shape every error surface on this page uses when the
   * labels are there: the error card, a card's status line, the questions panel, the settings save.
   */
  function plainError(error, labels) {
    var body = error || {};
    var errorClass = String(body.error_class || 'Error');
    var message = String(body.message || '');

    var block = el('div', 'plain-error');
    block.appendChild(el('p', 'plain-error-text', labelOf(labels, 'errors', errorClass, message || errorClass)));

    var fold = el('details', 'error-fold');
    fold.appendChild(el('summary', 'error-fold-head', 'Details'));
    fold.appendChild(el('p', 'error-class mono', errorClass));
    if (message) {
      fold.appendChild(el('p', 'error-message', message));
    }
    block.appendChild(fold);
    return block;
  }

  /**
   * What the review did and did not look at, as one summary that is rebuilt on every
   * `coverage` event rather than appended to - a bucket's contents are the whole truth about
   * it, and a list that only grows would show a re-run's items twice (constitution Principle
   * III: silence is not coverage).
   */
  function coverageSummary(entries, labels) {
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
      counts.push(items.length + ' ' + bucketWord(name, labels));
      groups.push(coverageBucket(name, items, labels));
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

  /** The backend's word for a bucket (feature 009 FR-024), `bucketLabel`'s spacing when it has none. */
  function bucketWord(name, labels) {
    return labelOf(labels, 'bucket', name, bucketLabel(name));
  }

  /**
   * The findings, grouped by type (feature 013, contracts/grouped-list.md section 5): one fold per
   * group in the order the backend supplied them, then the checked fold. `byType` is the ranking's
   * `groups` (`FindingsByType`, section 3).
   *
   * A printer, like the summary. Every group, row, count, plural and word is the backend's - each
   * group's `text`, each row's `tail_text`, `reach_text` and `chip` - and the page prints each
   * verbatim or honours each flag (`open`, `hide_card_title`); nothing here sorts, counts or
   * compares, so a row whose words disagree with its members prints its words (FR-022). The rows'
   * bodies are empty: `app.js` moves the finding cards into them, in each row's member order.
   * Rebuilt whole from every ranking, like the coverage fold.
   */
  function typeGroups(byType, labels) {
    var body = byType || {};
    var root = el('div', 'type-groups');
    var groups = body.groups || [];
    for (var index = 0; index < groups.length; index++) {
      var group = groups[index] || {};
      root.appendChild(typeGroup('type-group', group.id, group, labels));
    }
    // The passes, in one fold last - "Checked, no issue" - collapsed as the backend says. It has
    // no id of its own; `data-group` names the fold for the stylesheet and the tests alike.
    if (body.checked) {
      root.appendChild(typeGroup('type-group checked-fold', 'checked', body.checked, labels));
    }
    return root;
  }

  /**
   * One group: a `<details>` open as the backend says, headed by its title and its `text`, then
   * its rows, then the goal lines of the goals mapped to it - a group with no row prints its
   * goals' state as its `text` and its goal lines alone.
   */
  function typeGroup(className, id, group, labels) {
    var fold = el('details', className);
    fold.setAttribute('data-group', String(id || ''));
    fold.open = group.open === true;
    fold.appendChild(append(el('summary', 'type-group-head'), [
      el('span', 'type-group-title', group.title),
      el('span', 'type-group-text', group.text)
    ]));

    var inside = el('div', 'type-group-body');
    var rows = group.rows || [];
    for (var index = 0; index < rows.length; index++) {
      inside.appendChild(typeRow(rows[index] || {}));
    }
    var goals = group.goals || [];
    if (goals.length) {
      var lines = el('ul', 'type-group-goals');
      for (var goal = 0; goal < goals.length; goal++) {
        lines.appendChild(goalLine(goals[goal] || {}, labels));
      }
      inside.appendChild(lines);
    }
    fold.appendChild(inside);
    return fold;
  }

  /**
   * One row, one line: a `<details>` whose head is the display title under a one-line clamp (the
   * stylesheet's), then `tail_text`, `reach_text` and `chip`, each printed verbatim and only when
   * the backend sent it; its body is where `app.js` moves the row's finding cards. The stripe is
   * the shared map's (`attention.stripeOf`); `hide-card-title` honours `hide_card_title`, so a
   * single-member row's card does not repeat the row's title.
   */
  function typeRow(row) {
    var className = 'type-row ' + attention.stripeOf(row) + (row.hide_card_title === true ? ' hide-card-title' : '');
    var fold = el('details', className);
    fold.setAttribute('data-finding-id', String(row.finding_id || ''));
    fold.appendChild(append(el('summary', 'type-row-head'), [
      el('span', 'type-row-title', row.title || ''),
      typeof row.tail_text === 'string' ? el('span', 'type-row-tail', row.tail_text) : null,
      typeof row.reach_text === 'string' ? el('span', 'type-row-reach', row.reach_text) : null,
      typeof row.chip === 'string' ? el('span', 'chip type-row-chip', row.chip) : null
    ]));
    fold.appendChild(el('div', 'type-row-body'));
    return fold;
  }

  /**
   * A persisted explanation of a finding, as the first line inside its card's fold (U5, U10): the
   * backend's text as sent, never derived here (feature 013 sources.md section 4).
   */
  function findingExplanation(text) {
    var line = el('p', 'finding-explanation');
    line.appendChild(el('span', 'explanation-text', text));
    return line;
  }

  // ---- the summary (feature 009 User Story 3) ------------------------------------------

  /**
   * The review in ten seconds, at the top of Results: the headline, the tally, the questions, the
   * parts not loaded, the drawings, the bought parts and the goals not reached
   * (contracts/review-summary.md section 5, as feature 013's contracts/grouped-list.md section 4
   * amends it: the goal lines live under their groups now).
   *
   * A printer and nothing more. Every number, every word and every order here is the
   * backend's: `report/summary.py` counts the findings and states each goal, and this prints what
   * it was handed, in the order it was handed it (FR-009). Each line is printed when the backend
   * sent it and left out when it did not.
   */
  function summaryBlock(summary) {
    var body = summary || {};
    var block = el('div', 'summary');
    block.appendChild(el('p', 'summary-headline', body.headline));

    // Decide, Fix and Verify in one line (feature 013): the kinds of action, independent of the
    // type the groups below sort findings into.
    if (body.tally && body.tally.text) {
      block.appendChild(el('p', 'summary-tally', body.tally.text));
    }
    if (body.questions && body.questions.text) {
      block.appendChild(el('p', 'summary-questions', body.questions.text));
    }
    if (body.not_loaded && body.not_loaded.text) {
      block.appendChild(el('p', 'summary-not-loaded', body.not_loaded.text));
    }
    // The one line about drawings (feature 009 T087, the owner's decision 10A): the backend's
    // text as sent, and nothing where a backend sends none.
    if (body.drawings && body.drawings.text) {
      block.appendChild(el('p', 'summary-drawings', body.drawings.text));
    }
    // The bought parts, named once (feature 013, contracts/part-roles.md section 7): the
    // backend's sentence as sent, and nothing where a backend sends none.
    if (body.bought_parts && body.bought_parts.text) {
      block.appendChild(el('p', 'summary-bought-parts', body.bought_parts.text));
    }
    // The goals the review did not reach, by title in goal order, so the first screen still names
    // the coverage gaps (feature 013); nothing when every goal was reached.
    if (body.not_reached && body.not_reached.text) {
      block.appendChild(el('p', 'summary-not-reached', body.not_reached.text));
    }
    return block;
  }

  /**
   * One check goal: its title, its state in words and the few words of its reason. The
   * sentence the run recorded behind that reason - a close-out row's reason can run to four
   * hundred characters, and is never cut (FR-027's own principle) - is behind a shut fold whose
   * head is the line itself, so the line reads the same whether or not there is one.
   */
  function goalLine(line) {
    var item = el('li', 'summary-goal goal-' + String(line.state || ''));
    var parts = [
      el('span', 'goal-title', line.title),
      el('span', 'goal-state', line.state_label),
      line.reason ? el('span', 'goal-reason', line.reason) : null
    ];

    if (typeof line.detail === 'string' && line.detail) {
      var fold = el('details', 'goal-fold');
      fold.appendChild(append(el('summary', 'goal-head'), parts));
      fold.appendChild(el('p', 'goal-detail', line.detail));
      item.appendChild(fold);
    } else {
      item.appendChild(append(el('div', 'goal-head'), parts));
    }
    return item;
  }

  /**
   * The not-loaded warning when the backend sent its names-only headline (feature 009 FR-012,
   * contracts/plain-words.md section 3): the headline, then each instance's id and state in a
   * shut fold beneath it, so the ids are one press away and off the default view. A warning
   * with no headline is printed by `app.js` as its sentence alone, exactly as before this
   * feature - the sentence already names the ids, and a fold would say them twice.
   */
  function notExaminedHeadline(warning) {
    var body = warning || {};
    var block = el('div', 'not-examined-body');
    block.appendChild(el('span', 'not-examined-headline', body.headline));

    var instances = body.instances || [];
    if (instances.length) {
      var fold = el('details', 'not-examined-fold');
      fold.appendChild(el('summary', 'not-examined-fold-head', 'Which ones'));
      var lines = el('ul', 'not-examined-ids');
      for (var index = 0; index < instances.length; index++) {
        var instance = instances[index] || {};
        lines.appendChild(el('li', 'mono', joined([
          instance.id,
          instance.state ? '(' + instance.state + ')' : ''
        ], ' ')));
      }
      fold.appendChild(lines);
      block.appendChild(fold);
    }
    return block;
  }

  /**
   * The size-for-size contacts, one shut fold apart from the findings (FR-011): its head the
   * backend's line ("2 size-for-size contacts"), one line per contact naming the two parts, the
   * kind in words and the configuration, and the component ids and the volume behind each
   * line's own fold. Every word is the summary's (`ContactView.text`, `kind_label`); the page
   * composes no name and computes no count.
   */
  function contactList(contacts) {
    var body = contacts || {};
    var fold = el('details', 'contacts');
    fold.appendChild(el('summary', 'contacts-head', body.text));

    var lines = el('ul', 'contact-lines');
    var items = body.items || [];
    for (var index = 0; index < items.length; index++) {
      lines.appendChild(contactLine(items[index] || {}));
    }
    fold.appendChild(lines);
    return fold;
  }

  function contactLine(contact) {
    var line = el('li', 'contact');
    var own = el('details', 'contact-fold');
    own.appendChild(append(el('summary', 'contact-head'), [
      el('span', 'contact-text', contact.text),
      el('span', 'contact-kind', contact.kind_label),
      contact.configuration ? el('span', 'contact-configuration', contact.configuration) : null
    ]));

    var ids = list(contact.component_ids);
    if (typeof contact.volume_mm3 === 'number' && isFinite(contact.volume_mm3)) {
      ids = joined([ids, contact.volume_mm3 + ' ' + CUBIC_MILLIMETRES], DOT);
    }
    own.appendChild(el('p', 'contact-ids mono', ids));
    line.appendChild(own);
    return line;
  }

  // ---- kept reviews (feature 009 User Story 6) -----------------------------------------

  /** What a chip says when neither the backend nor the run folder can bring its review back. */
  var GONE = 'This review can no longer be restored.';

  /**
   * One chip per kept review, in the host's order (contracts/sessions.md section 5): its file,
   * configuration and time as `app.js` labelled it, the one on screen `aria-current`. A review
   * that can no longer be restored says so, with a Remove that asks the host to forget it.
   * `chips` is `[{chat_id, label, current, gone}]`; the order is the host's and nothing here
   * changes it.
   */
  function reviewChips(chips) {
    var row = el('div', 'review-chip-row');
    var list = chips || [];
    for (var index = 0; index < list.length; index++) {
      var chip = list[index] || {};
      var chatId = String(chip.chat_id || '');
      if (chip.gone) {
        var gone = el('span', 'review-chip gone');
        gone.setAttribute('data-chat-id', chatId);
        append(gone, [
          el('span', 'review-chip-label', chip.label),
          el('span', 'review-chip-gone', GONE)
        ]);
        var remove = button('Remove', 'review-forget', 'action review-forget');
        remove.setAttribute('data-chat-id', chatId);
        gone.appendChild(remove);
        row.appendChild(gone);
        continue;
      }

      var node = button(chip.label, 'review-chip', 'review-chip');
      node.setAttribute('data-chat-id', chatId);
      node.setAttribute('aria-current', chip.current ? 'true' : 'false');
      row.appendChild(node);
    }
    return row;
  }

  /**
   * The Transcript of a review restored from its run folder (contracts/sessions.md section 8):
   * there is no live chat to replay, so it says where the transcript is, and offers the folder.
   */
  function restoredTranscript() {
    var block = textBlock(
      'system restored',
      'This review was restored from its run folder; its transcript is in events.jsonl there.');
    block.appendChild(button('Open run folder', 'open-folder', 'action open-folder'));
    return block;
  }

  function coverageBucket(name, items, labels) {
    var group = el('div', 'coverage-bucket bucket-' + name);
    group.appendChild(el('h4', 'bucket-name', bucketWord(name, labels) + DOT + items.length));

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
   * What this review has cost so far: the uncached and cached input, the tokens in all, the
   * round trips and the latency of the last round, from the `usage` events the page has already
   * received (specs/005-llm-efficiency/contracts/usage.md section 5).
   *
   * Pure, and it does the summing as well as the rendering, so the one rule that matters here
   * is testable inside the real page: **any null in a field makes that total null**, never a
   * partial sum, which is the arithmetic `SessionUsage.summed` defines rather than a second
   * rule (section 1). A field the endpoint omitted is unknown, not zero: "0 cached tokens" and
   * "the endpoint did not say" send an engineer to different places.
   *
   * The input is two numbers in the report's words (feature 008, contracts/cost.md section 4):
   * uncached is summed input minus summed cached - the rule `TokenUsage.uncached_input_tokens`
   * applies, over the totals - and only when every round reported both and the cached sum is
   * contained in the input sum; otherwise the line states the input it knows and says the cache
   * split was not reported. No percentage: the report prints no cached share while probe L1 is
   * unrecorded, and a share here would be a second, contradicting number.
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

    if (input !== null && cached !== null && cached <= input) {
      write(line, (input - cached) + ' uncached + ' + cached + ' cached input');
    } else {
      write(line, (input === null ? 'input unknown' : input + ' input') + ' (cache split not reported)');
    }
    write(line, ' - ' + (tokens === null ? 'tokens unknown' : tokens + ' tokens in all'));
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

  window.SwReviewRender = {
    el: el,
    write: write,
    clear: clear,
    append: append,
    field: field,
    list: list,
    textBlock: textBlock,
    findingMarker: findingMarker,
    withdrawalMarker: withdrawalMarker,
    pinnedAnswer: pinnedAnswer,
    toolCard: toolCard,
    findingCard: findingCard,
    dispositionText: dispositionText,
    dispositionClass: dispositionClass,
    evidenceCard: evidenceCard,
    questionsPanel: questionsPanel,
    errorCard: errorCard,
    plainError: plainError,
    coverageSummary: coverageSummary,
    typeGroups: typeGroups,
    findingExplanation: findingExplanation,
    summaryBlock: summaryBlock,
    contactList: contactList,
    notExaminedHeadline: notExaminedHeadline,
    reviewChips: reviewChips,
    restoredTranscript: restoredTranscript,
    entityRequest: entityRequest,
    usageLine: usageLine
  };
})();
