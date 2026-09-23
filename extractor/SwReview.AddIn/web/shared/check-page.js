/*
  The family-neutral half of a check page (T030), extracted from `Model/ModelCheckPage/check.js`.

  Two Task Pane tabs grade a document against a family of deterministic rules and show the
  result: the Model check tab against the RMS rules, the Standards check tab against the
  release checklist. Everything below is what they do the same way - the host channel, the
  authenticated call to the backend, the check that a previous press left behind, the bucket
  chips, the coverage and finding renderers, the Show and Accept flows, and the page's chrome.
  What differs is a header (a grade, a verdict), a start verb, the sentence each page prints
  about its own counts, and the wording of the Accept control - which names what a waiver binds
  to, and the two families do not grade the same kinds of document. Those are what a page
  supplies to `create` below.

  It is one file rather than two copies for the same reason `dom.js` is one file: a second copy
  of "which rules an engineer is allowed not to see" and "which strings reach the DOM as text"
  is one copy that is out of date the first time either is fixed.

  Five rules hold everywhere in this file, unchanged by the move:

  1. Markup is never assigned and no handler is inline. Every node is built through
     `shared/dom.js` (T080), which is the single place the "insert every untrusted string with
     createTextNode" rule lives. The untrusted text here is a feature name and an `observed`
     string assembled out of feature names - authored by whoever last renamed a feature in the
     document, which on a supplied model is not anyone this workstation knows.
  2. Every host message is `{type, id, payload}` and replies echo `id`. An object is posted
     rather than a string so the host reads it with `WebMessageAsJson`.
  3. The page calls the backend itself, with the origin and token the host sent in `init`. The
     token travels in the `Authorization` header and never in a URL, because a URL reaches
     access logs, WebView2's history and every crash dump (chat-api.md).
  4. The page names no path. `report.open` and `folder.open` carry the `run_id` - the check
     folder's name, which is also the backend's `check_id` - and the host resolves the folder
     from its own record.
  5. Rendering is a function of the check result and the chip state, and of nothing else.
     `renderResult` is handed back to the page, which exports it for its own tests; the tab
     renders through the same function, so a row a test built behaves exactly like a row the
     tab built.

  It names no family: no route, no scope and no start type is written down here.
*/

(function () {
  'use strict';

  var dom = window.SwReviewDom;
  var docs = window.SwReviewDocument;

  /*
    The Start-here row - heading, stripe map, `amplified`, the row and its meta line - is
    `web/shared/attention.js`'s, loaded before this file and by the Review page, so the three
    tabs render the same row from one copy (feature 009 increment 3).
  */
  var attention = window.SwReviewAttention;
  var bridge = (window.chrome && window.chrome.webview) ? window.chrome.webview : null;

  /** The buckets, in the order a header states them: what to act on first. */
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
   * The buckets a page opens on. A check is pressed to find what to fix, and the other four
   * buckets are one press away rather than absent - "silence is not coverage" cuts both ways,
   * and a page that hid them would be claiming the rules it skipped had passed.
   */
  var OPEN_BUCKETS = ['failed', 'warned'];

  /** The heading of the section holding rules that named no document. */
  var UNGROUPED_LABEL = 'Rules that name no document';

  /** How long a pointed-at row stays lit, in milliseconds. */
  var FLASH_MS = 1500;

  /** A run folder's own name, which is also the backend's `check_id`. */
  function folderName(runDirectory) {
    var text = String(runDirectory || '').replace(/[\\/]+$/, '');
    return docs.fileName(text);
  }

  /**
   * One check page.
   *
   * `page` is the family's half:
   *   - `headerId`: the element the header renders into.
   *   - `renderHeader(result, node, api)`: the grade, or the verdict. The node is cleared first.
   *   - `startCheck(api)`: the verb the button presses, which owns its own message type, its
   *     own scope and its own evaluation route.
   *   - `acceptLabel` and `acceptNoteHint`: the Accept control's wording, which names the thing
   *     a waiver is bound to - a part for one family, any graded document for the other.
   *   - `describeCounts(result)`: the one-line sentence about the counts, printed after a check
   *     and after an accept. The buckets it reads are the family's, so the family writes it.
   *
   * And two hooks, both optional, for the facts one family's `init` carries and the other's
   * does not. A page that defines neither behaves exactly as it did before they existed:
   *   - `onInit(payload, api)`: the whole `init`, after it has been applied. One family's page
   *     shows which profile file is in force and relays its path on its own request; the other
   *     has no such field at all, and a shared half that read one would be reading a family's.
   *   - `onDocument(documentInfo, api)`: the open document, whenever it changes. One family can
   *     grade only a part and the button says so; the other grades three kinds and says what
   *     each of them would pull in. Called last, so the page decides after the chrome has.
   */
  function create(page) {
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
      runDirectory: null,

      /**
       * Whether the host has said which document is open - in `init` or in `document.changed`,
       * either of which may say "none". Until it has, a result is not judged against the open
       * document: "no answer yet" is not "no document open" (U8).
       */
      documentKnown: false,

      /** Whether the result on screen is for another document than the open one (U8). */
      resultStale: false,

      /** Whether a `ready` is in flight, so a second status does not ask again on top of it. */
      initPending: false,

      /** Which buckets are showing, by bucket name. */
      buckets: Object.create(null),

      /** The row a ranked line last pointed at, and the timer that will unlight it. */
      flashing: null,

      /** Every rendered subject line by its key, with which instance Show will select. */
      subjects: Object.create(null)
    };

    var ui = {};
    var api;

    // ---- transport: the host --------------------------------------------------------------

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
          state.documentKnown = true;
          renderDocument();
          renderBinding();
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

    // ---- transport: the backend -------------------------------------------------------------

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

    // ---- the check ----------------------------------------------------------------------------

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
     * Accept a rule for this document. The note is required here as well as at the route, so the
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
                  + ' Press the check again to see where it stands.');
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
          + page.describeCounts(state.result));
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

    // ---- rendering ----------------------------------------------------------------------------------

    /**
     * The whole result: the page's own header, the chips, and the rules grouped by document and
     * then by bucket. Called by the tab and by the page tests, and it reads nothing but its
     * argument.
     */
    function renderResult(result) {
      state.result = result || null;
      state.subjects = Object.create(null);

      dom.clear(ui.header);
      page.renderHeader(state.result, ui.header, api);

      renderNotExamined(state.result);
      renderAttention(state.result);

      var rows = rowsOf(state.result);
      renderFilters(rows);
      renderRules(rows);
      renderCarriedForward(state.result);
      renderBinding();
    }

    // ---- rendering: whose result this is ------------------------------------------------------

    /**
     * Whether the result on screen is for the document on screen, and what the page does when it
     * is not (U8, docs/pane-findings-2026-09-20-review-gui.md section 1).
     *
     * Both tabs restore the newest check folder on init whatever is open, and both used to keep
     * the previous result after `document.changed` - with Show in SOLIDWORKS and Accept live
     * against a model that was no longer the open one. Now the result is hidden, one line says
     * whose it is, and Open report and Open check folder are disabled, until the graded document
     * is open again. The rule is `web/shared/document.js`'s, the one the Review tab uses, and a
     * result that names no document is never taken for the open one.
     *
     * What counts as the result is marked `check-result` in each page's own `index.html`, because
     * the two tabs do not show the same blocks (the Standards tab has its sixteen-check roster);
     * it is hidden by one class on the body, so a re-render while it is hidden stays hidden.
     */
    function renderBinding() {
      var result = state.result;
      state.resultStale = !!(state.documentKnown && result
        && !docs.same(result.document || null, state.documentInfo));
      document.body.classList.toggle('result-stale', state.resultStale);

      dom.clear(ui.staleResult);
      if (state.resultStale) {
        dom.write(ui.staleResult, staleSentence(result));
      }
      ui.staleResult.hidden = !state.resultStale;

      renderRunButtons();
    }

    /** The one line a hidden result leaves: whose it is, and what is open instead. */
    function staleSentence(result) {
      var sentence = 'This result is for ' + (docs.label(result.document) || 'another document') + '.';
      var open = docs.label(state.documentInfo);
      return open
        ? sentence + ' The open document is ' + open + '.'
        : sentence + ' No document is open.';
    }

    // ---- rendering: what was never read -----------------------------------------------------

    /**
     * The sentence naming the component instances the check never read - lightweight or
     * suppressed, so the extractor never opened them and interference, fit and the feature-tree
     * rules cannot see them either (docs/feature-request-resolve-lightweight.md). `null` means
     * every instance was read, and a body from before this feature carries no key at all, which
     * reads the same way: the block says nothing and stays hidden, exactly as it did before the
     * key existed.
     */
    function renderNotExamined(result) {
      dom.clear(ui.notExamined);

      var notExamined = result && result.not_examined;
      if (!notExamined) {
        ui.notExamined.hidden = true;
        return;
      }

      dom.write(ui.notExamined, notExamined.sentence || '');
      ui.notExamined.hidden = false;
    }

    // ---- rendering: what to start with -----------------------------------------------------------

    /**
     * The rows the backend ranked, above the chips, exactly as it supplied them.
     *
     * This block amplifies; it never filters. Every finding is still in the rule list below in
     * full, in its own bucket - the rows here are the ones `report/attention.py` placed first,
     * with the same ids and the same reasons the report's "Start here" section prints
     * (contracts/attention.md sections 3 and 6). A tab that ranked for itself would be a second
     * policy, arguable from nothing, disagreeing with the report an engineer opens beside it.
     *
     * So nothing here reads a severity, compares two rows, or knows how many there ought to be:
     * it reads `rows` and renders the first `top_n` of them through `web/shared/attention.js`,
     * the same row the Review tab renders. `PageRuleScanTests` is the test that keeps it that
     * way. (The Review tab also shows the rows beyond `top_n` behind "Show all"; the check tabs
     * do not, yet - contracts/attention.md section 6.)
     *
     * Three states, and the third is the one that matters on an older check folder: a body from
     * before this feature carries no ranking at all, and the section stays empty rather than
     * printing a heading over nothing.
     */
    function renderAttention(result) {
      dom.clear(ui.attention);

      var ranking = result && result.attention;
      if (!ranking) {
        return;
      }

      ui.attention.appendChild(dom.el('h2', 'attention-heading', attention.HEADING));

      if (ranking.empty_reason) {
        ui.attention.appendChild(dom.el('p', 'attention-empty', ranking.empty_reason));
        return;
      }

      ui.attention.appendChild(attention.rowList(attention.amplified(ranking)));
    }

    /**
     * A ranked row points at its rule.
     *
     * The two blocks already carry the same finding id and the engineer was already reading the
     * top one, so the press that used to do nothing now scrolls the matching row into view and
     * lights it. It amplifies and it still does not filter: the rule list is untouched, except
     * that a bucket hiding the row is turned back on - a press that scrolled to something
     * invisible would read as a broken page.
     */
    function onAttentionClick(event) {
      var row = closestClass(event.target, 'attention-row');
      if (!row) {
        return;
      }

      var rule = renderedRule(row.getAttribute('data-finding-id'));
      if (!rule) {
        return;
      }

      revealRule(rule);
      if (rule.scrollIntoView) {
        rule.scrollIntoView();
      }
      flashRule(rule);
    }

    /** Turns the bucket holding <var>rule</var> back on, chip and all, if a chip had hidden it. */
    function revealRule(rule) {
      var group = closestClass(rule, 'bucket-group');
      if (!group || !group.hidden) {
        return;
      }

      var bucket = group.getAttribute('data-bucket');
      state.buckets[bucket] = true;

      var chips = ui.filters.querySelectorAll('.chip');
      for (var index = 0; index < chips.length; index++) {
        if (chips[index].getAttribute('data-bucket') === bucket) {
          chips[index].setAttribute('aria-pressed', 'true');
        }
      }

      applyFilter();
    }

    /**
     * Lights one row for a moment. One at a time: a second press unlights the first row rather
     * than leaving two rows claiming to be the one that was pointed at.
     */
    function flashRule(rule) {
      if (state.flashing) {
        window.clearTimeout(state.flashing.timer);
        state.flashing.rule.classList.remove('flash');
      }

      var entry = { rule: rule, timer: 0 };
      state.flashing = entry;
      rule.classList.add('flash');
      entry.timer = window.setTimeout(function () {
        rule.classList.remove('flash');
        if (state.flashing === entry) {
          state.flashing = null;
        }
      }, FLASH_MS);
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
     * The ids are in the item's `scope`, where `coverage_rows` puts them ({bucket, check,
     * scope: {component_ids, pairs, configuration, positions, document_ids}, reason, error}).
     * Read off the top level they are always undefined, and every coverage row falls back - to
     * nothing at all when the check graded more than one document, because then the result names
     * no single document. That is how every skipped, unresolved and out-of-scope rule used to
     * disappear while the header went on counting them.
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

      // The two families spell the advisory severity differently - `warn` in one catalogue,
      // `warning` in the other - and both mean the row is advice rather than a failure. Read as
      // a failure, an advisory row would contradict the same check's own bucket in the header.
      return (row.severity === 'warn' || row.severity === 'warning') ? 'warned' : 'failed';
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

    /**
     * One chip per bucket the result actually carries, in bucket order.
     *
     * The count leads, in its own element, because the number is what an engineer reads off the
     * tab before deciding what to open - "2 failed" rather than "failed (2)". The bucket's name
     * is also a class, which is what lets a pressed chip be filled in that bucket's own colour
     * without any script setting one.
     */
    function renderFilters(rows) {
      dom.clear(ui.filters);

      var counted = countByBucket(rows);
      for (var index = 0; index < BUCKETS.length; index++) {
        var bucket = BUCKETS[index];
        if (!counted[bucket]) {
          continue;
        }

        var chip = dom.button('', 'filter', 'chip bucket-' + bucket);
        dom.append(chip, [
          dom.el('b', 'chip-count', counted[bucket]),
          dom.el('span', 'chip-label', BUCKET_LABELS[bucket])
        ]);
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
      // the header is still counting it.
      var ungrouped = rows.filter(function (row) {
        return !row.documents.length;
      });
      if (ungrouped.length) {
        ui.rules.appendChild(documentSection(null, UNGROUPED_LABEL, ungrouped));
      }

      countShown();
    }

    /**
     * How much of each document is on screen, beside its name.
     *
     * Counted off the DOM after every render and again after every chip, because a chip hides
     * rows rather than re-rendering them: a number that only moved on a render would be wrong
     * the moment one was pressed, and a wrong count beside a document heading reads as the
     * document having fewer rules than it has.
     */
    function countShown() {
      var documents = ui.rules.querySelectorAll('.document-group');
      for (var index = 0; index < documents.length; index++) {
        var group = documents[index];
        var node = group.querySelector('.document-count');
        if (!node) {
          continue;
        }

        var all = group.querySelectorAll('.rule').length;
        var shown = group.querySelectorAll('.bucket-group:not([hidden]) .rule').length;
        dom.clear(node);
        dom.write(node, shown + ' of ' + all + ' shown');
      }
    }

    /** One document's rules, in bucket order. `documentId` null is the ungrouped section. */
    function documentSection(documentId, label, rows) {
      var group = dom.el('section', documentId ? 'document-group' : 'document-group ungrouped');
      if (documentId) {
        group.setAttribute('data-document-id', documentId);
      }

      var heading = dom.el('h2', 'document-name', label);
      heading.appendChild(dom.el('span', 'document-count', ''));
      group.appendChild(heading);

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
      return (open && open.id === documentId && open.path) ? docs.fileName(open.path) : documentId;
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

    /**
     * One rule: a line, and a fold.
     *
     * The line is what the rule is and what was seen - a bucket badge in the bucket's own colour,
     * the check id, the statement as the title, and the observed string as the facts under it.
     * What an engineer does about it - the recommended action, the note an acceptance left, and
     * the Accept control itself - is one press away, because a list where every row states its
     * remedy in full is a list nobody skims, and the four paragraphs used to be
     * indistinguishable from one another.
     *
     * Nothing is dropped: everything that was on the row before is still on the row, and the
     * fold is in the DOM whether it is open or not.
     */
    function ruleRow(row) {
      var item = dom.el('li', 'rule bucket-' + row.bucket);
      item.setAttribute('data-rule-id', row.ruleId);
      item.setAttribute('data-bucket', row.bucket);
      if (row.findingId) {
        item.setAttribute('data-finding-id', row.findingId);
      }

      var head = dom.el('div', 'rule-head');
      head.appendChild(dom.el(
        'span',
        'badge bucket bucket-' + row.bucket,
        BUCKET_LABELS[row.bucket] || row.bucket));
      head.appendChild(dom.el('span', 'rule-id', row.ruleId));
      item.appendChild(head);

      if (row.statement) {
        item.appendChild(dom.el('p', 'statement', row.statement));
      }
      if (row.observed) {
        item.appendChild(dom.el('p', 'observed', row.observed));
      }

      // A coverage row carries no statement and no observed, so its reason IS the row: folded
      // away it would leave a check id and nothing else, which is how a skipped rule reads
      // exactly like a rule that was never run. A finding's reason is the recommended action,
      // and that goes under the fold with the acceptance.
      var stated = !!(row.statement || row.observed);
      if (row.reason && !stated) {
        item.appendChild(dom.el('p', 'reason', row.reason));
      }

      if (row.subjects.length) {
        item.appendChild(subjectList(row));
      }

      var fold = ruleFold(row, stated);
      if (fold) {
        item.appendChild(fold);
      }

      return item;
    }

    /**
     * What one press on a rule opens, or null when the row has nothing to keep behind one: the
     * recommended action, the note an acceptance left, and the Accept control.
     */
    function ruleFold(row, stated) {
      var recommended = !!(row.reason && stated);
      var acceptable = !!(row.acceptable && !row.exception);
      if (!recommended && !row.exception && !acceptable) {
        return null;
      }

      var fold = dom.el('details', 'rule-fold');
      fold.appendChild(dom.el(
        'summary', 'rule-fold-summary', foldLabel(recommended, !!row.exception, acceptable)));

      if (recommended) {
        fold.appendChild(dom.el('p', 'reason', row.reason));
      }
      if (row.exception) {
        fold.appendChild(dom.el('p', 'exception', exceptionText(row.exception)));
      }
      if (acceptable) {
        fold.appendChild(acceptRow());
      }

      return fold;
    }

    /** What the press says it opens, named after what is actually behind it. */
    function foldLabel(recommended, accepted, acceptable) {
      if (recommended && acceptable) {
        return 'Recommended, and accept';
      }
      if (recommended && accepted) {
        return 'Recommended, and what was accepted';
      }
      if (recommended) {
        return 'Recommended';
      }
      if (acceptable) {
        return 'Accept';
      }
      return 'What was accepted';
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
     * The exception binds to the rule, the document's component instances, the configuration and
     * a feature-tree fingerprint, so accepting waives the rule on the whole graded document -
     * which is why putting this on a subject line would state a granularity the store does not
     * have. The two strings say which document that is, and they are the page's because the
     * families do not grade the same kinds: one grades parts, the other grades parts, assemblies
     * and drawings (contracts/model-check.md section 5, contracts/standards-check.md section 5).
     * A `warn` rule has no control at all rather than a disabled one: FR-016 makes them
     * unacceptable, and a disabled control invites a request to enable it.
     */
    function acceptRow() {
      var row = dom.el('div', 'row accept');

      var note = dom.el('input', 'note');
      note.setAttribute('type', 'text');
      note.setAttribute('placeholder', page.acceptNoteHint);
      note.required = true;
      row.appendChild(note);

      var by = dom.el('input', 'by');
      by.setAttribute('type', 'text');
      by.setAttribute('placeholder', 'Accepted by');
      row.appendChild(by);

      row.appendChild(dom.button(page.acceptLabel, 'accept', 'action accept'));
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

      if (subject.showable === false) {
        // The result said outright that there is nothing to select: a data-card property name,
        // a note, a revision-table row, a cut-list item, a mate, and every drawing entity while
        // the resolver reads model entities only. The reference such a subject carries would
        // make a button that reported failure every single time, which is worse than no button
        // at all. Only `false` counts: a family whose subjects do not answer the question is
        // decided by the reference below, exactly as it always was.
        line.appendChild(dom.el(
          'span',
          'subject-note',
          subject.reason || 'there is nothing in SOLIDWORKS to select'));
      } else if (subject.persist_ref) {
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

      countShown();
    }

    // ---- the page's own chrome ----------------------------------------------------------------------

    function renderDocument() {
      dom.clear(ui.documentName);
      var open = state.documentInfo;
      dom.write(ui.documentName, docs.label(open) || 'No document open');
      ui.runCheck.disabled = state.checking || !open || !open.path;

      // Last, so a page that can say more about this document than "there is one" - which kinds
      // it grades, and what each of them pulls in - decides after the chrome has.
      if (page.onDocument) {
        page.onDocument(open, api);
      }
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
      state.runDirectory = runDirectory || null;
      renderRunButtons();
    }

    /** Open report and Open check folder: there is a folder, and its result is the open document's. */
    function renderRunButtons() {
      var usable = !!state.runDirectory && !state.resultStale;
      ui.openReport.disabled = !usable;
      ui.openFolder.disabled = !usable;
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
      ui.staleResult = byId('stale-result');
      ui.carried = byId('carried-forward');
      ui.notExamined = byId('not-examined');
      ui.attention = byId('attention');
      ui.filters = byId('filters');
      ui.rules = byId('rules');

      // The one element whose id belongs to the page rather than to this file: a grade on one
      // tab, a verdict on the other.
      ui.header = byId(page.headerId);

      for (var index = 0; index < OPEN_BUCKETS.length; index++) {
        state.buckets[OPEN_BUCKETS[index]] = true;
      }

      ui.runCheck.addEventListener('click', function () {
        page.startCheck(api);
      });
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

      // One listener each for the ranked rows, the chips and the rules, reading what was pressed
      // off the DOM: no inline handler anywhere, which the CSP would refuse in any case.
      ui.attention.addEventListener('click', onAttentionClick);
      ui.filters.addEventListener('click', onFilterClick);
      ui.rules.addEventListener('click', onRuleClick);

      if (bridge) {
        bridge.addEventListener('message', onHostMessage);
      }

      renderDocument();

      // `warn` from the first paint, because there is no backend yet: the strip's dot says what
      // the sentence beside it says, and a ready-coloured dot over "Backend starting" would be
      // the pane's own fourth false status line.
      renderBackendState('Backend starting', true);

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
      state.documentKnown = true;
      state.latestCheck = payload.latest_check || null;

      renderDocument();
      renderBinding();
      renderBackendState(state.backend ? 'Backend ready' : 'Backend starting', !state.backend);
      if (page.onInit) {
        page.onInit(payload, api);
      }
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

    /**
     * What a page's own script gets: its renderer, the two transports its start verb needs, and
     * the chrome that start verb moves. Nothing else, so a page cannot quietly acquire a second
     * opinion about the result or the chip state.
     */
    api = {
      renderResult: renderResult,
      send: send,
      call: call,
      checking: function () {
        return state.checking;
      },
      setChecking: setChecking,
      setCheckState: setCheckState,
      setRunDirectory: setRunDirectory,
      showBanner: showBanner,
      hideBanner: hideBanner
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', start);
    } else {
      start();
    }

    return api;
  }

  window.SwReviewCheckPage = {
    create: create,
    BUCKETS: BUCKETS,
    BUCKET_LABELS: BUCKET_LABELS,
    fileName: docs.fileName,
    folderName: folderName
  };
})();
