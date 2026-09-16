/*
  The Model check page (T082, contracts/model-check.md).

  Five rules hold everywhere in this file:

  1. Markup is never assigned and no handler is inline. Every node is built through
     `shared/dom.js` (T080), which is the single place the "insert every untrusted string with
     createTextNode" rule lives. The untrusted text here is a feature name and an `observed`
     string assembled out of feature names - authored by whoever last renamed a feature in the
     part, which on a supplied model is not anyone this workstation knows.
  2. Every host message is `{type, id, payload}` and replies echo `id`. An object is posted
     rather than a string so the host reads it with `WebMessageAsJson`.
  3. The page calls the backend itself, with the port, origin and token the host sent in
     `init`. The token travels in the `Authorization` header and never in a URL, because a URL
     reaches access logs, WebView2's history and every crash dump (chat-api.md).
  4. The page names no path. `report.open` and `folder.open` carry the `run_id` - the check
     folder's name, which is also the backend's `check_id` - and the host resolves the folder
     from its own record.
  5. Rendering is a function of the `CheckResult` and the chip state, and of nothing else.
     `renderResult` is exported for the page tests, which call it inside the real page under the
     real CSP; the tab renders through the same function, so a row a test built behaves exactly
     like a row the tab built.
*/

(function () {
  'use strict';

  var dom = window.SwReviewDom;
  var bridge = (window.chrome && window.chrome.webview) ? window.chrome.webview : null;

  /** The grade's buckets, in the order the grade states them: what to act on first. */
  var BUCKETS = ['failed', 'warned', 'checked', 'skipped', 'unresolved', 'out_of_scope'];

  /** What each bucket is called on screen. The token stays the machine-readable one. */
  var BUCKET_LABELS = {
    failed: 'failed',
    warned: 'warned',
    checked: 'checked',
    skipped: 'skipped',
    unresolved: 'unresolved',
    out_of_scope: 'out of scope'
  };

  /**
   * The buckets the page opens on. A model check is pressed to find what to fix, and the other
   * four buckets are one press away rather than absent - "silence is not coverage" cuts both
   * ways, and a page that hid them would be claiming the rules it skipped had passed.
   */
  var OPEN_BUCKETS = ['failed', 'warned'];

  /** The only scope this increment evaluates (contracts/model-check.md). */
  var SCOPE = 'part';

  /** The heading of the section holding rules that named no document. */
  var UNGROUPED_LABEL = 'Rules that name no document';

  var pending = Object.create(null);
  var nextId = 0;
  var nextSubject = 0;

  var state = {
    backend: null,
    token: null,
    runRoot: null,
    documentInfo: null,
    latestCheck: null,
    result: null,
    checking: false,

    /** Whether a `ready` is in flight, so a second status does not ask again on top of it. */
    initPending: false,

    /** Which buckets are showing, by bucket name. */
    buckets: Object.create(null),

    /** Every rendered subject line by its key, with which instance Show will select. */
    subjects: Object.create(null)
  };

  var ui = {};

  // ---- transport: the host ----------------------------------------------------------------

  function send(type, payload) {
    var id = 'm' + (++nextId);
    var message = { type: type, id: id, payload: payload || {} };
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      if (!bridge) {
        delete pending[id];
        reject(new Error('this page is not hosted in the SwReview task pane'));
        return;
      }
      bridge.postMessage(message);
    });
  }

  function onHostMessage(event) {
    var message = event.data;
    if (!message || typeof message.type !== 'string') {
      return;
    }

    var waiting = (typeof message.id === 'string') ? pending[message.id] : null;
    if (waiting) {
      delete pending[message.id];
      if (message.type === 'error') {
        waiting.reject(asError(message.payload));
      } else {
        waiting.resolve(message.payload || {});
      }
      return;
    }

    handleUnsolicited(message);
  }

  function asError(payload) {
    var error = new Error((payload && payload.message) || 'the host reported an error');
    error.errorClass = (payload && payload.error_class) || 'HostError';
    error.retryable = !!(payload && payload.retryable);
    return error;
  }

  function handleUnsolicited(message) {
    var payload = message.payload || {};
    switch (message.type) {
      case 'status':
        showStatus(payload);
        return;
      case 'document.changed':
        state.documentInfo = (payload && payload.path) ? payload : null;
        renderDocument();
        return;
      case 'backend.stopped':
        state.backend = null;
        state.token = null;
        renderBackendState('The backend stopped. Reopen the pane to start it again.', true);
        return;
      case 'error':
        showBanner(asError(message.payload).message);
        return;
      default:
        return;
    }
  }

  // ---- transport: the backend ---------------------------------------------------------------

  /**
   * One authenticated call to the loopback backend, rejecting with the backend's own
   * `{error_class, message, retryable}` so "this scope is not offered yet" can be said
   * differently from "the backend is gone".
   */
  function call(path, method, body) {
    if (!state.backend || !state.token) {
      return Promise.reject(backendError(
        'BackendUnavailable', 'the reviewer backend is not running.', true));
    }

    var headers = { Authorization: 'Bearer ' + state.token, Accept: 'application/json' };
    var request = { method: method || 'GET', headers: headers, cache: 'no-store' };
    if (body !== undefined && body !== null) {
      headers['Content-Type'] = 'application/json';
      request.body = JSON.stringify(body);
    }

    return fetch(state.backend.origin + path, request).then(function (response) {
      return response.text().then(function (text) {
        var parsed = null;
        if (text) {
          try {
            parsed = JSON.parse(text);
          } catch (error) {
            parsed = null;
          }
        }

        if (!response.ok) {
          throw backendError(
            (parsed && parsed.error_class) || 'HttpError',
            (parsed && parsed.message) || ('the backend answered ' + response.status),
            !!(parsed && parsed.retryable));
        }

        return parsed;
      });
    });
  }

  function backendError(errorClass, message, retryable) {
    var error = new Error(message);
    error.errorClass = errorClass;
    error.retryable = retryable;
    return error;
  }

  // ---- the check ------------------------------------------------------------------------------

  /**
   * One press of Model check: the host extracts, the page grades.
   *
   * The split is the contract's. The host owns the run folder and the in-process dump because
   * only it can reach SOLIDWORKS; the page owns `POST /checks/rms` because there is exactly one
   * evaluation entry point and it is in the backend, and because a graded part's findings and
   * subjects are more than a `postMessage` channel should carry.
   */
  function startCheck() {
    if (state.checking) {
      return;
    }

    setChecking(true);
    hideBanner();
    setCheckState('Reading the feature tree...');

    send('check.start', { scope: SCOPE })
      .then(function (extracted) {
        setRunDirectory(extracted.run_dir);
        setCheckState('Checking the model...');
        return call('/checks/rms', 'POST', {
          run_dir: extracted.run_dir,
          scope: SCOPE,
          document_id: null
        });
      })
      .then(function (result) {
        renderResult(result);
        setCheckState('Checked ' + describeCounts(result));
      })
      .catch(function (error) {
        showBanner(error.message);
        setCheckState('');
      })
      .then(function () {
        setChecking(false);
      });
  }

  /** The check a previous press left behind, re-read so the tab is not blank on reload. */
  function loadLatestCheck() {
    var latest = state.latestCheck;
    if (!latest || !latest.run_dir) {
      return;
    }

    var checkId = folderName(latest.run_dir);
    if (!checkId) {
      return;
    }

    setRunDirectory(latest.run_dir);
    refreshResult(checkId)
      .then(function () {
        setCheckState('The check from this session, as it stands now.');
      })
      .catch(function () {
        // A check folder that has been tidied away is not an error the engineer has to read;
        // the tab simply has nothing to show until the next press.
        setCheckState('');
      });
  }

  /**
   * Accept a rule for this part. The note is required here as well as at the route, so the
   * refusal arrives before the round trip and beside the box it is about.
   */
  function acceptRule(row) {
    var findingId = row.getAttribute('data-finding-id');
    var note = row.querySelector('.note');
    var by = row.querySelector('.by');
    var said = row.querySelector('.accept-state');
    var result = state.result;

    if (!findingId || !result || !result.check_id) {
      return;
    }

    if (!note || !note.value || !note.value.trim()) {
      dom.clear(said);
      dom.write(said, 'A note is required: an unexplained waiver is a blanket exclusion.');
      if (note) {
        note.focus();
      }
      return;
    }

    dom.clear(said);
    dom.write(said, 'Accepting...');

    var checkId = result.check_id;
    call(
      '/checks/' + encodeURIComponent(checkId)
        + '/exceptions/' + encodeURIComponent(findingId),
      'POST',
      { note: note.value.trim(), by: by ? by.value.trim() : '' })
      .then(function (answer) {
        var exceptionId = (answer && answer.exception_id) ? String(answer.exception_id) : '';

        // An accepted rule renders as `checked`, and that chip starts off. Without this the
        // rule the engineer just accepted would be re-rendered into a hidden group - it would
        // disappear as they accepted it, which `contracts/model-check.md` section 5 forbids
        // ("Never hidden, per Principle VI").
        state.buckets.checked = true;

        return refreshResult(checkId)
          .then(function () {
            markAccepted(findingId, exceptionId);
          })
          .catch(function (error) {
            // The exception is written; only the re-read failed. Both are said, because a page
            // that reported only the failure would invite a second acceptance of the same rule.
            showBanner(
              'Accepted as ' + (exceptionId || 'a new exception')
                + ', but the check could not be re-read: ' + error.message
                + ' Press Model check again to see where it stands.');
          });
      })
      .catch(function (error) {
        sayOnRule(findingId, error.message);
      });
  }

  /**
   * The whole result, re-read from the route that has just recomputed it.
   *
   * Not a local edit of `state.result`: the grade is the rule layer's (there is one evaluation
   * entry point, FR-024), so a page that moved the counts itself would be a second opinion
   * about the score, and the headline number and the list would drift apart. Accepting re-ran
   * the rules and re-rendered `report.md` before it answered, so this reads what that run wrote.
   */
  function refreshResult(checkId) {
    return call('/checks/' + encodeURIComponent(checkId), 'GET', null).then(renderResult);
  }

  /** Points at the row that was just accepted, and names the exception that covers it. */
  function markAccepted(findingId, exceptionId) {
    var row = renderedRule(findingId);
    if (row) {
      row.classList.add('just-accepted');
      if (row.scrollIntoView) {
        row.scrollIntoView();
      }
    }

    setCheckState(
      (exceptionId ? 'Accepted as ' + exceptionId + '. ' : 'Accepted. ')
        + describeCounts(state.result));
  }

  /** Says <var>text</var> on the row for <var>findingId</var>, or out loud if it has no line. */
  function sayOnRule(findingId, text) {
    var row = renderedRule(findingId);
    var said = row ? row.querySelector('.accept-state') : null;
    if (!said) {
      showBanner(text);
      return;
    }

    dom.clear(said);
    dom.write(said, text);
  }

  /**
   * The rendered row for a finding id, or null.
   *
   * Walked rather than selected: a finding id is the backend's, and splicing it into a CSS
   * selector would be one more place a string has to be escaped correctly.
   */
  function renderedRule(findingId) {
    var rows = ui.rules.querySelectorAll('.rule');
    for (var index = 0; index < rows.length; index++) {
      if (rows[index].getAttribute('data-finding-id') === String(findingId)) {
        return rows[index];
      }
    }
    return null;
  }

  // ---- Show in SOLIDWORKS ----------------------------------------------------------------------

  function showSubject(line) {
    var entry = state.subjects[line.getAttribute('data-subject-key')];
    if (!entry) {
      return;
    }

    var subject = entry.subject;
    var components = subject.component_ids || [];
    send('entity.show', {
      persist_ref: String(subject.persist_ref),
      persist_ref_scope: subject.persist_ref_scope ? String(subject.persist_ref_scope) : null,
      component_id: components.length ? String(components[entry.instance]) : null
    })
      .then(function (shown) {
        if (!shown.ok) {
          showBanner(shown.message || 'that feature could not be selected.');
        }
      })
      .catch(function (error) {
        showBanner(error.message);
      });
  }

  /** The next instance of a part that is in the assembly more than once. */
  function cycleSubject(line) {
    var key = line.getAttribute('data-subject-key');
    var entry = state.subjects[key];
    if (!entry) {
      return;
    }

    var count = (entry.subject.component_ids || []).length;
    entry.instance = count ? (entry.instance + 1) % count : 0;

    var show = line.querySelector('[data-action="show"]');
    if (show) {
      dom.clear(show);
      dom.write(show, showLabel(entry));
    }
  }

  function showLabel(entry) {
    var count = (entry.subject.component_ids || []).length;
    return count > 1
      ? 'Show (instance ' + (entry.instance + 1) + ' of ' + count + ')'
      : 'Show';
  }

  // ---- rendering: the grade ----------------------------------------------------------------------

  /**
   * The whole result: the grade, the chips, and the rules grouped by document and then by
   * bucket. Called by the tab and by the page tests, and it reads nothing but its argument.
   */
  function renderResult(result) {
    state.result = result || null;
    state.subjects = Object.create(null);

    renderGrade(state.result);
    var rows = rowsOf(state.result);
    renderFilters(rows);
    renderRules(rows);
    renderCarriedForward(state.result);
  }

  function renderGrade(result) {
    dom.clear(ui.grade);
    if (!result || !result.grade) {
      return;
    }

    var grade = result.grade;
    ui.grade.appendChild(dom.el('h2', 'grade-heading', gradeHeading(result)));

    var total = 0;
    var counts = dom.el('ul', 'counts');
    for (var index = 0; index < BUCKETS.length; index++) {
      var bucket = BUCKETS[index];
      var count = Number(grade[bucket] || 0);
      total += count;
      var item = dom.el('li', 'count', count + ' ' + BUCKET_LABELS[bucket]);
      item.setAttribute('data-bucket', bucket);
      counts.appendChild(item);
    }
    ui.grade.appendChild(counts);

    if (total === 0) {
      // Not a perfect score: nothing reached a bucket at all (T068).
      ui.grade.appendChild(dom.el('p', 'nothing-evaluated', 'Nothing was evaluated.'));
      return;
    }

    ui.grade.appendChild(dom.el(
      'p',
      'fraction',
      typeof grade.fraction === 'number'
        ? grade.fraction.toFixed(2) + ' of the rules that reached a verdict were checked'
        : 'No fraction: no rule reached a verdict.'));

    // The unresolved rules travel with the counts, by name. A score with the missing rules
    // named beside it is a grade; a score on its own is a claim.
    var unresolved = grade.unresolved_rule_ids || [];
    ui.grade.appendChild(dom.el(
      'p',
      'unresolved-rules',
      unresolved.length
        ? 'Unresolved, so not graded: ' + dom.list(unresolved)
        : 'Every rule reached a verdict.'));
  }

  function gradeHeading(result) {
    var document_ = result.document;
    return document_ && document_.path
      ? 'Grade: ' + fileName(document_.path)
        + (document_.configuration ? ' [' + document_.configuration + ']' : '')
      : 'Grade';
  }

  function renderCarriedForward(result) {
    dom.clear(ui.carried);
    var carried = result && result.exceptions_carried_forward;
    if (!carried) {
      return;
    }

    if (carried.count) {
      dom.write(
        ui.carried,
        carried.count + ' accepted rule(s) carried forward from ' + (carried.from_run || 'the last check') + '.');
      return;
    }

    dom.write(ui.carried, carried.reason ? 'Nothing carried forward: ' + carried.reason : '');
  }

  // ---- rendering: the rule list ---------------------------------------------------------------------

  /**
   * Every rule the check reached, as one flat row list.
   *
   * Two sources, and they are not overlapping: a rule that failed or warned produced a finding,
   * and a rule that passed, was skipped, was unresolved or is out of scope produced a coverage
   * item. Both are rules with a verdict, and a page that showed only the findings would be the
   * silence the constitution forbids.
   */
  function rowsOf(result) {
    if (!result) {
      return [];
    }

    var rows = [];
    var fallback = (result.document && result.document.id) ? [String(result.document.id)] : [];
    var index;

    var findings = result.findings || [];
    for (index = 0; index < findings.length; index++) {
      var row = findings[index] || {};
      var finding = row.finding || {};
      var subjects = (result.subjects && result.subjects[finding.id]) || [];
      rows.push({
        ruleId: String(row.rule_id || finding.check || ''),
        bucket: bucketOfFinding(row, finding),
        statement: row.statement || '',
        observed: row.observed || finding.observed || '',
        reason: finding.recommended_action || '',
        findingId: finding.id ? String(finding.id) : '',
        acceptable: !!row.acceptable,
        exception: row.exception || null,
        subjects: subjects,
        documents: documentsOfSubjects(subjects, fallback)
      });
    }

    var coverage = result.coverage || [];
    for (index = 0; index < coverage.length; index++) {
      var item = coverage[index] || {};
      rows.push({
        ruleId: String(item.check || ''),
        bucket: String(item.bucket || ''),
        statement: '',
        observed: '',
        reason: item.reason || item.error || '',
        findingId: '',
        acceptable: false,
        exception: null,
        subjects: [],
        documents: documentsOfCoverage(item, fallback)
      });
    }

    return rows;
  }

  /**
   * Which documents a coverage item covers.
   *
   * The ids are in the item's `scope`, where `coverage_rows` in `checks/rms/run.py` puts them
   * ({bucket, check, scope: {component_ids, pairs, configuration, positions, document_ids},
   * reason, error}). Read off the top level they are always undefined, and every coverage row
   * falls back - to nothing at all when the check graded more than one document, because then
   * the result names no single document. That is how every skipped, unresolved and out-of-scope
   * rule used to disappear while the grade header went on counting them.
   */
  function documentsOfCoverage(item, fallback) {
    var scope = item.scope;
    return (scope && scope.document_ids && scope.document_ids.length)
      ? scope.document_ids.map(String)
      : fallback;
  }

  /**
   * Which bucket a finding's rule landed in.
   *
   * An accepted rule is `checked`, not `failed`: the rule layer turned the condition into a
   * finding that is checked within scope, and the page reports that rather than re-deciding it.
   */
  function bucketOfFinding(row, finding) {
    if (finding.status === 'checked_within_scope') {
      return 'checked';
    }
    return row.severity === 'warn' ? 'warned' : 'failed';
  }

  function documentsOfSubjects(subjects, fallback) {
    var found = [];
    for (var index = 0; index < subjects.length; index++) {
      var scope = subjects[index] && subjects[index].persist_ref_scope;
      if (scope && found.indexOf(String(scope)) < 0) {
        found.push(String(scope));
      }
    }
    return found.length ? found : fallback;
  }

  function renderFilters(rows) {
    dom.clear(ui.filters);

    var counted = countByBucket(rows);
    for (var index = 0; index < BUCKETS.length; index++) {
      var bucket = BUCKETS[index];
      if (!counted[bucket]) {
        continue;
      }

      var chip = dom.button(
        BUCKET_LABELS[bucket] + ' (' + counted[bucket] + ')', 'filter', 'chip');
      chip.setAttribute('data-bucket', bucket);
      chip.setAttribute('aria-pressed', state.buckets[bucket] ? 'true' : 'false');
      ui.filters.appendChild(chip);
    }
  }

  function countByBucket(rows) {
    var counted = Object.create(null);
    for (var index = 0; index < rows.length; index++) {
      var bucket = rows[index].bucket;
      counted[bucket] = (counted[bucket] || 0) + 1;
    }
    return counted;
  }

  function renderRules(rows) {
    dom.clear(ui.rules);

    var documents = documentOrder(rows);
    for (var d = 0; d < documents.length; d++) {
      ui.rules.appendChild(documentSection(
        documents[d], documentLabel(documents[d]), rows.filter(inDocument(documents[d]))));
    }

    // A row that named no document is rendered under a section that says so, never dropped:
    // a rule that is missing from the list reads exactly like a rule that was never run, and
    // the grade header is still counting it.
    var ungrouped = rows.filter(function (row) {
      return !row.documents.length;
    });
    if (ungrouped.length) {
      ui.rules.appendChild(documentSection(null, UNGROUPED_LABEL, ungrouped));
    }
  }

  /** One document's rules, in bucket order. `documentId` null is the ungrouped section. */
  function documentSection(documentId, label, rows) {
    var group = dom.el('section', documentId ? 'document-group' : 'document-group ungrouped');
    if (documentId) {
      group.setAttribute('data-document-id', documentId);
    }
    group.appendChild(dom.el('h2', 'document-name', label));

    for (var index = 0; index < BUCKETS.length; index++) {
      var bucket = BUCKETS[index];
      var matching = rows.filter(ofBucket(bucket));
      if (!matching.length) {
        continue;
      }
      group.appendChild(bucketGroup(bucket, matching));
    }

    return group;
  }

  function inDocument(documentId) {
    return function (row) {
      return row.documents.indexOf(documentId) >= 0;
    };
  }

  function ofBucket(bucket) {
    return function (row) {
      return row.bucket === bucket;
    };
  }

  function documentOrder(rows) {
    var order = [];
    for (var index = 0; index < rows.length; index++) {
      var documents = rows[index].documents;
      for (var d = 0; d < documents.length; d++) {
        if (order.indexOf(documents[d]) < 0) {
          order.push(documents[d]);
        }
      }
    }
    return order;
  }

  function documentLabel(documentId) {
    var open = state.result && state.result.document;
    return (open && open.id === documentId && open.path) ? fileName(open.path) : documentId;
  }

  function bucketGroup(bucket, rows) {
    var group = dom.el('section', 'bucket-group bucket-' + bucket);
    group.setAttribute('data-bucket', bucket);
    group.hidden = !state.buckets[bucket];
    group.appendChild(dom.el(
      'h3', 'bucket-name', BUCKET_LABELS[bucket] + ' (' + rows.length + ')'));

    var list = dom.el('ul', 'bucket-rules');
    for (var index = 0; index < rows.length; index++) {
      list.appendChild(ruleRow(rows[index]));
    }

    group.appendChild(list);
    return group;
  }

  function ruleRow(row) {
    var item = dom.el('li', 'rule');
    item.setAttribute('data-rule-id', row.ruleId);
    item.setAttribute('data-bucket', row.bucket);
    if (row.findingId) {
      item.setAttribute('data-finding-id', row.findingId);
    }

    var head = dom.el('div', 'rule-head');
    head.appendChild(dom.el('span', 'badge bucket', BUCKET_LABELS[row.bucket] || row.bucket));
    head.appendChild(dom.el('span', 'rule-id', row.ruleId));
    item.appendChild(head);

    if (row.statement) {
      item.appendChild(dom.el('p', 'statement', row.statement));
    }
    if (row.observed) {
      item.appendChild(dom.el('p', 'observed', row.observed));
    }
    if (row.reason) {
      item.appendChild(dom.el('p', 'reason', row.reason));
    }
    if (row.subjects.length) {
      item.appendChild(subjectList(row));
    }
    if (row.exception) {
      item.appendChild(dom.el('p', 'exception', exceptionText(row.exception)));
    }
    if (row.acceptable && !row.exception) {
      item.appendChild(acceptRow());
    }

    return item;
  }

  function exceptionText(exception) {
    var text = exception.state === 'needs_review'
      ? 'Accepted as ' + exception.id + ', and the feature tree has changed since: re-review it.'
      : 'Accepted as ' + exception.id + '.';
    return exception.note ? text + ' ' + exception.note : text;
  }

  /**
   * The Accept control, on the rule row and not on a subject line.
   *
   * The exception binds to the rule, the part's component instances, the configuration and a
   * feature-tree fingerprint, so accepting waives the rule **on the part** - which is why the
   * label says so, and why putting this on a subject line would state a granularity the store
   * does not have (contracts/model-check.md section 5). A `warn` rule has no control at all
   * rather than a disabled one: FR-016 makes them unacceptable, and a disabled control invites
   * a request to enable it.
   */
  function acceptRow() {
    var row = dom.el('div', 'row accept');

    var note = dom.el('input', 'note');
    note.setAttribute('type', 'text');
    note.setAttribute('placeholder', 'Why this is acceptable on this part (required)');
    note.required = true;
    row.appendChild(note);

    var by = dom.el('input', 'by');
    by.setAttribute('type', 'text');
    by.setAttribute('placeholder', 'Accepted by');
    row.appendChild(by);

    row.appendChild(dom.button('Accept this rule for this part', 'accept', 'action accept'));
    row.appendChild(dom.el('span', 'accept-state', ''));
    return row;
  }

  function subjectList(row) {
    var list = dom.el('ul', 'subjects');
    for (var index = 0; index < row.subjects.length; index++) {
      list.appendChild(subjectLine(row, row.subjects[index]));
    }
    return list;
  }

  function subjectLine(row, subject) {
    var key = 's' + (++nextSubject);
    var entry = { subject: subject, instance: 0 };
    state.subjects[key] = entry;

    var line = dom.el('li', 'subject');
    line.setAttribute('data-subject-key', key);
    line.setAttribute('data-feature-id', String(subject.feature_id || ''));

    var components = subject.component_ids || [];
    var name = String(subject.name || subject.feature_id || '(unnamed feature)');
    if (components.length > 1) {
      // Several instances of this part in the assembly, so which one Show selects is a choice
      // the engineer makes rather than one the page makes for them.
      line.appendChild(dom.button(name, 'cycle', 'subject-name'));
    } else {
      line.appendChild(dom.el('span', 'subject-name', name));
    }

    line.appendChild(dom.el('span', 'subject-meta', subjectMeta(subject)));

    if (subject.persist_ref) {
      line.appendChild(dom.button(showLabel(entry), 'show', 'action show'));
    } else {
      // Honest rather than hopeful: with no persistent reference the host has nothing to
      // select, so the line says why instead of offering a button that cannot work.
      line.appendChild(dom.el(
        'span',
        'subject-note',
        subject.reason || 'no persistent reference, so this cannot be shown'));
    }

    return line;
  }

  function subjectMeta(subject) {
    var parts = [];
    if (subject.type_name) {
      parts.push(String(subject.type_name));
    }
    if (subject.group) {
      parts.push(String(subject.group));
    }
    return parts.join(' - ');
  }

  // ---- the chips -------------------------------------------------------------------------------

  function toggleBucket(chip) {
    var bucket = chip.getAttribute('data-bucket');
    state.buckets[bucket] = !state.buckets[bucket];
    chip.setAttribute('aria-pressed', state.buckets[bucket] ? 'true' : 'false');
    applyFilter();
  }

  /**
   * Shown or hidden, never re-rendered: the rows carry which instance Show will select, and a
   * re-render would put every one of them back to the first instance because a chip was pressed.
   */
  function applyFilter() {
    var groups = ui.rules.querySelectorAll('.bucket-group');
    for (var index = 0; index < groups.length; index++) {
      groups[index].hidden = !state.buckets[groups[index].getAttribute('data-bucket')];
    }
  }

  // ---- the page's own chrome ----------------------------------------------------------------------

  function renderDocument() {
    dom.clear(ui.documentName);
    var open = state.documentInfo;
    dom.write(
      ui.documentName,
      open && open.path
        ? fileName(open.path) + (open.configuration ? ' [' + open.configuration + ']' : '')
        : 'No document open');
    ui.runCheck.disabled = state.checking || !open || !open.path;
  }

  function renderBackendState(text, warn) {
    dom.clear(ui.backendState);
    dom.write(ui.backendState, text);
    ui.backendState.className = warn ? 'badge warn' : 'badge';
  }

  function showStatus(payload) {
    if (payload && payload.stage === 'error') {
      showBanner(payload.message || 'the check stopped');
      return;
    }

    if (payload && payload.stage === 'ready' && !state.backend) {
      // The backend finished starting after this page was given its `init`, so the endpoint it
      // holds is null and every check call would be refused for the life of the page. Ask
      // again, as `app.js` already does for the Review page. Guarded on `state.backend` so the
      // host's own end-of-extraction `status {stage: "ready"}` does not re-initialise the page
      // in the middle of a check.
      requestInit(false);
    }

    setCheckState((payload && payload.message) || '');
  }

  function setCheckState(text) {
    dom.clear(ui.checkState);
    dom.write(ui.checkState, text);
  }

  function setRunDirectory(runDirectory) {
    dom.clear(ui.runDir);
    dom.write(ui.runDir, runDirectory || '');
    var known = !!runDirectory;
    ui.openReport.disabled = !known;
    ui.openFolder.disabled = !known;
    state.runDirectory = runDirectory || null;
  }

  function setChecking(running) {
    state.checking = running;
    renderDocument();
  }

  function showBanner(message) {
    dom.clear(ui.banner);
    dom.write(ui.banner, message || '');
    ui.banner.hidden = !message;
  }

  function hideBanner() {
    dom.clear(ui.banner);
    ui.banner.hidden = true;
  }

  function describeCounts(result) {
    var grade = (result && result.grade) || {};
    return Number(grade.failed || 0) + ' failed, ' + Number(grade.warned || 0) + ' warned, '
      + Number(grade.checked || 0) + ' checked.';
  }

  /** The last segment of a Windows or POSIX path; the page shows names, not paths. */
  function fileName(path) {
    var text = String(path || '');
    var cut = Math.max(text.lastIndexOf('\\'), text.lastIndexOf('/'));
    return cut >= 0 ? text.substring(cut + 1) : text;
  }

  /** A run folder's own name, which is also the backend's `check_id`. */
  function folderName(runDirectory) {
    var text = String(runDirectory || '').replace(/[\\/]+$/, '');
    return fileName(text);
  }

  // ---- wiring ---------------------------------------------------------------------------------------

  function byId(name) {
    return document.getElementById(name);
  }

  function start() {
    ui.documentName = byId('document-name');
    ui.backendState = byId('backend-state');
    ui.banner = byId('banner');
    ui.runCheck = byId('run-check');
    ui.openReport = byId('open-report');
    ui.openFolder = byId('open-folder');
    ui.openLog = byId('open-log');
    ui.runDir = byId('run-dir');
    ui.checkState = byId('check-state');
    ui.carried = byId('carried-forward');
    ui.grade = byId('grade');
    ui.filters = byId('filters');
    ui.rules = byId('rules');

    for (var index = 0; index < OPEN_BUCKETS.length; index++) {
      state.buckets[OPEN_BUCKETS[index]] = true;
    }

    ui.runCheck.addEventListener('click', startCheck);
    ui.openReport.addEventListener('click', function () {
      openRun('report.open');
    });
    ui.openFolder.addEventListener('click', function () {
      openRun('folder.open');
    });
    ui.openLog.addEventListener('click', function () {
      send('log.open', {}).catch(function (error) {
        showBanner(error.message);
      });
    });

    // One listener each for the chips and the rules, reading `data-action` off whatever was
    // pressed: no inline handler anywhere, which the CSP would refuse in any case.
    ui.filters.addEventListener('click', onFilterClick);
    ui.rules.addEventListener('click', onRuleClick);

    if (bridge) {
      bridge.addEventListener('message', onHostMessage);
    }

    renderDocument();
    renderBackendState('Backend starting');

    requestInit(true);
  }

  function openRun(type) {
    var result = state.result;
    var runId = (result && result.check_id) || folderName(state.runDirectory);
    if (!runId) {
      return;
    }

    send(type, { run_id: runId }).catch(function (error) {
      showBanner(error.message);
    });
  }

  /**
   * Ask the host for `init` and apply it.
   *
   * `loadLatest` is false when the page is re-asking because the backend has only just started:
   * the first `init` already loaded whatever check this session left behind, and re-reading it
   * would race whatever the page is rendering now. `initPending` keeps two statuses in quick
   * succession from producing two in-flight asks.
   */
  function requestInit(loadLatest) {
    if (state.initPending) {
      return;
    }

    state.initPending = true;
    send('ready', {})
      .then(function (payload) {
        applyInit(payload, loadLatest);
      })
      .catch(function (error) {
        showBanner(error.message);
      })
      .then(function () {
        state.initPending = false;
      });
  }

  function applyInit(payload, loadLatest) {
    state.backend = payload.backend || null;
    state.token = payload.token || null;
    state.runRoot = payload.run_root || null;
    state.documentInfo = payload.document || null;
    state.latestCheck = payload.latest_check || null;

    renderDocument();
    renderBackendState(state.backend ? 'Backend ready' : 'Backend starting', !state.backend);
    if (loadLatest) {
      loadLatestCheck();
    }
  }

  function onFilterClick(event) {
    var chip = closestAction(event.target, 'filter');
    if (chip) {
      toggleBucket(chip);
    }
  }

  function onRuleClick(event) {
    var pressed = closestAction(event.target, null);
    if (!pressed) {
      return;
    }

    var action = pressed.getAttribute('data-action');
    if (action === 'show') {
      showSubject(closestClass(pressed, 'subject'));
    } else if (action === 'cycle') {
      cycleSubject(closestClass(pressed, 'subject'));
    } else if (action === 'accept') {
      acceptRule(closestClass(pressed, 'rule'));
    }
  }

  function closestAction(node, action) {
    while (node && node !== document) {
      if (node.getAttribute && node.getAttribute('data-action')) {
        return (!action || node.getAttribute('data-action') === action) ? node : null;
      }
      node = node.parentNode;
    }
    return null;
  }

  function closestClass(node, className) {
    while (node && node !== document) {
      if (node.classList && node.classList.contains(className)) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  window.SwReviewCheck = {
    renderResult: renderResult
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
