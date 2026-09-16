/*
  The Review page's script: the Settings section (T032) and the chat view (T041).

  Five rules hold everywhere in this file and are worth stating once:

  1. Markup is never assigned, and no handler is inline. Every string that reaches the DOM goes
     through `textContent` or `createTextNode` - here and in `render.js`, which builds every
     card - because assistant deltas, tool summaries, finding titles, drawing text and provider
     error messages are authored by a model or by a reviewed document (FR-029). The page's CSP
     (`script-src 'self'`) blocks inline script anyway; the rule here is what stops markup being
     *interpreted* rather than merely blocked.
  2. The key is write-only. The host never sends one and this page never asks: the key box is
     always blank on load, and a save that leaves it blank leaves the stored key alone. Only
     "Remove the stored key" clears it, by sending an explicit empty string.
  3. Every host message is `{type, id, payload}` and replies echo `id`
     (contracts/pane-host-messages.md). An object is posted rather than a string so the host
     reads it with `WebMessageAsJson`.
  4. The backend is talked to directly - messages, evidence answers, dispositions, Stop and the
     event stream - with the port, origin and token the host sent in `init`. The stream is read
     with `fetch` plus a `ReadableStream` reader and never with `EventSource`, which can set
     neither `Authorization` nor `Last-Event-ID`; the token travels in a header and never in a
     URL, because a URL reaches access logs, WebView2's history and every crash dump
     (chat-api.md, "Reading the event stream").
  5. The page names no path. `report.open` and `folder.open` carry the `chat_id` and the host
     resolves the folder from its own record.
*/

(function () {
  'use strict';

  var bridge = (window.chrome && window.chrome.webview) ? window.chrome.webview : null;
  var render = window.SwReviewRender;

  /**
   * How many chat events are kept in memory (T041). The transcript on screen is built as the
   * events arrive, so this is a bounded history for the reconnect and for diagnostics, not the
   * display: a long review streams tens of thousands of deltas, and keeping all of them would
   * grow the renderer process without bound for no one's benefit.
   */
  var EVENT_LIMIT = 500;

  /** Reconnect backoff for the event stream, in milliseconds. */
  var RECONNECT_MIN = 1000;
  var RECONNECT_MAX = 15000;

  var pending = Object.create(null);
  var nextId = 0;

  var state = {
    providers: ['openai', 'gemini'],
    settings: null,
    keySource: 'none',
    models: [],
    backend: null,
    token: null,
    runRoot: null,
    documentInfo: null,

    // ---- the chat ----
    chatId: null,
    runDir: null,
    turnRunning: false,

    // Whether a `review.start` is in flight. Kept apart from `turnRunning` because the two
    // disable the Review button for different reasons and end at different moments: the
    // request ends when the host replies, the turn ends at `turn.ended`.
    startPending: false,
    lastSeq: 0,
    events: [],
    coverage: [],

    // One entry per model round trip, as the `usage` events carry them. The running usage
    // line is summed from this array rather than read off the session, so it moves while the
    // turn is still running (feature 005 T016a, contracts/usage.md section 6).
    usage: [],
    findings: Object.create(null),
    evidence: Object.create(null),
    tools: Object.create(null),
    textBlock: null,
    stream: null,
    reconnectTimer: null,
    reconnectDelay: RECONNECT_MIN,
    initPending: false
  };

  var ui = {};

  // ---- transport: the host --------------------------------------------------------------

  function send(type, payload) {
    var id = 'p' + (++nextId);
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
        state.documentInfo = payload && payload.path ? payload : null;
        renderDocument();
        return;
      case 'backend.stopped':
        state.backend = null;
        state.token = null;
        closeStream();
        setTurnRunning(false);
        renderBackendState('The backend stopped. Reopen the pane to start it again.', true);
        return;
      case 'models':
        // Pushed with an `UnknownModel` refusal so the picker re-renders without asking.
        if (!payload.provider || payload.provider === currentProvider()) {
          setModels(payload.models || []);
        }
        return;
      case 'error':
        showBanner(asError(payload).message);
        return;
      default:
        return;
    }
  }

  // ---- transport: the backend ------------------------------------------------------------

  function backendUrl(path) {
    return state.backend.origin + path;
  }

  function sessionPath(suffix) {
    return '/sessions/' + encodeURIComponent(state.chatId) + suffix;
  }

  /**
   * One authenticated call to the loopback backend. Rejects with the backend's own
   * `{error_class, message, retryable}` so a card can say "no key" differently from "the
   * backend is gone".
   */
  function call(path, method, body) {
    if (!state.backend || !state.token) {
      return Promise.reject(backendError(
        'BackendUnavailable', 'the review backend is not running.', true));
    }

    var headers = { Authorization: 'Bearer ' + state.token, Accept: 'application/json' };
    var request = { method: method || 'GET', headers: headers, cache: 'no-store' };
    if (body !== undefined && body !== null) {
      headers['Content-Type'] = 'application/json';
      request.body = JSON.stringify(body);
    }

    return fetch(backendUrl(path), request).then(function (response) {
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

  // ---- the event stream -------------------------------------------------------------------

  /**
   * Reads `GET /sessions/{chat_id}/events` with `fetch` and a `ReadableStream` reader.
   *
   * `EventSource` cannot set `Authorization` and cannot set `Last-Event-ID` on a first
   * connection, and putting the token in the query string is forbidden (chat-api.md), so the
   * frames are parsed here. `Last-Event-ID` carries the highest `seq` already on screen, so a
   * reconnect replays what was missed from `events.jsonl` and nothing that was not.
   */
  function openStream() {
    if (!state.chatId || !state.backend || !state.token) {
      return;
    }

    closeStream();

    var controller = new AbortController();
    state.stream = controller;

    var headers = { Authorization: 'Bearer ' + state.token, Accept: 'text/event-stream' };
    if (state.lastSeq > 0) {
      headers['Last-Event-ID'] = String(state.lastSeq);
    }

    fetch(backendUrl(sessionPath('/events')), {
      method: 'GET',
      headers: headers,
      cache: 'no-store',
      signal: controller.signal
    }).then(function (response) {
      if (!response.ok || !response.body) {
        throw new Error('the event stream answered ' + response.status);
      }
      state.reconnectDelay = RECONNECT_MIN;
      showStreamState('Streaming.');
      return read(response.body.getReader(), controller);
    }).then(function () {
      // The server closed the stream. Nothing is lost - every event is in events.jsonl and
      // `Last-Event-ID` asks for what came after the last one shown.
      scheduleReconnect(controller, 'The event stream closed.');
    }).catch(function (error) {
      scheduleReconnect(controller, error && error.message ? error.message : 'the event stream failed');
    });
  }

  function read(reader, controller) {
    var decoder = new TextDecoder();
    var buffer = '';

    function step() {
      return reader.read().then(function (chunk) {
        if (chunk.done) {
          return undefined;
        }
        if (controller !== state.stream) {
          // A newer stream took over (a retry, or a second review). Stop feeding this one.
          return undefined;
        }

        buffer += decoder.decode(chunk.value, { stream: true });

        // SSE frames are separated by a blank line; the tail is a partial frame.
        var frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop();
        for (var index = 0; index < frames.length; index++) {
          onFrame(frames[index]);
        }
        return step();
      });
    }

    return step();
  }

  /** One SSE frame: `id:`, `data:` (possibly several lines), and comments to ignore. */
  function onFrame(frame) {
    var lines = frame.split(/\r?\n/);
    var data = [];
    var id = null;

    for (var index = 0; index < lines.length; index++) {
      var line = lines[index];
      if (!line || line.charAt(0) === ':') {
        continue;
      }
      var colon = line.indexOf(':');
      var name = colon < 0 ? line : line.substring(0, colon);
      var value = colon < 0 ? '' : line.substring(colon + 1).replace(/^ /, '');
      if (name === 'id') {
        id = value;
      } else if (name === 'data') {
        data.push(value);
      }
      // `event:` is ignored on purpose: the body carries its own `type` and one source of
      // truth for what an event is beats two that can disagree.
    }

    if (!data.length) {
      return;
    }

    var event;
    try {
      event = JSON.parse(data.join('\n'));
    } catch (error) {
      // A frame this page cannot parse is a frame it cannot act on; the stream continues.
      return;
    }

    var seq = typeof event.seq === 'number' ? event.seq : parseInt(id || '0', 10);
    if (seq > state.lastSeq) {
      state.lastSeq = seq;
    }

    state.events.push(event);
    if (state.events.length > EVENT_LIMIT) {
      state.events.splice(0, state.events.length - EVENT_LIMIT);
    }

    onChatEvent(event);
  }

  function scheduleReconnect(controller, why) {
    if (controller !== state.stream) {
      return;
    }

    state.stream = null;
    if (!state.chatId || !state.backend) {
      return;
    }

    var delay = state.reconnectDelay;
    state.reconnectDelay = Math.min(delay * 2, RECONNECT_MAX);
    showStreamState(why + ' Reconnecting...');

    state.reconnectTimer = window.setTimeout(function () {
      state.reconnectTimer = null;
      openStream();
    }, delay);
  }

  function closeStream() {
    if (state.reconnectTimer !== null) {
      window.clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
    if (state.stream) {
      var controller = state.stream;
      state.stream = null;
      controller.abort();
    }
  }

  // ---- the transcript ----------------------------------------------------------------------

  function onChatEvent(event) {
    var body = event.body || {};
    switch (event.type) {
      case 'session.started':
        appendCard(render.textBlock('system', describeStart(body)));
        return;
      case 'text.delta':
        writeDelta(body.text);
        return;
      case 'text.done':
        finishDelta(body.text);
        return;
      case 'tool.started':
        startTool(body);
        return;
      case 'tool.finished':
        finishTool(body);
        return;
      case 'finding':
        showFinding(body);
        return;
      case 'evidence.requested':
        showEvidence(body);
        return;
      case 'evidence.answered':
        answerEvidence(body);
        return;
      case 'disposition':
        applyDisposition(body);
        return;
      case 'coverage':
        state.coverage.push(body);
        renderCoverage();
        return;
      case 'usage':
        state.usage.push(body);
        renderUsage();
        return;
      case 'turn.ended':
        endTurn(body);
        return;
      case 'session.ended':
        endSession(body);
        return;
      case 'error':
        setTurnRunning(false);
        appendCard(render.errorCard(body));
        return;
      default:
        return;
    }
  }

  function describeStart(body) {
    var line = 'Review started with ' + (body.provider || '?') + ' ' + (body.model || '?');
    if (body.effort_mapping) {
      line += ' (' + body.effort_mapping.requested + ' -> '
        + body.effort_mapping.provider_param + '=' + body.effort_mapping.provider_value + ')';
    }
    return line;
  }

  function appendCard(node) {
    ui.transcript.appendChild(node);
    scrollToEnd();
    return node;
  }

  function scrollToEnd() {
    ui.transcript.scrollTop = ui.transcript.scrollHeight;
  }

  /** The assistant's text, streamed. One block per turn, filled in delta by delta. */
  function writeDelta(text) {
    if (!state.textBlock) {
      var block = render.textBlock('assistant', '');
      appendCard(block);
      state.textBlock = block.querySelector('.text');
    }
    render.write(state.textBlock, text || '');
    scrollToEnd();
  }

  /**
   * `text.done` carries everything the turn said, so the streamed block is replaced by it
   * rather than appended to: after a reconnect the deltas may be partial and the done body
   * never is.
   */
  function finishDelta(text) {
    if (!state.textBlock) {
      writeDelta('');
    }
    render.clear(state.textBlock);
    render.write(state.textBlock, text || '');
    state.textBlock = null;
    scrollToEnd();
  }

  function startTool(body) {
    var card = appendCard(render.toolCard(body));
    state.tools['s' + body.step_index] = { body: body, card: card };
  }

  /** The finished body is merged onto the started one, so the card shows the whole call. */
  function finishTool(body) {
    var entry = state.tools['s' + body.step_index];
    if (!entry) {
      appendCard(render.toolCard(body));
      return;
    }

    var merged = {
      step_index: body.step_index,
      tool: entry.body.tool,
      arguments: entry.body.arguments,
      status: body.status,
      result_summary: body.result_summary,
      elapsed_s: body.elapsed_s,
      error: body.error
    };

    var card = render.toolCard(merged);
    entry.card.parentNode.replaceChild(card, entry.card);
    entry.card = card;
    entry.body = merged;
  }

  function showFinding(body) {
    var existing = state.findings[body.id];
    var card = render.findingCard(body);
    if (existing) {
      // A re-run replaces its verdict rather than showing two (data-model, resume semantics).
      existing.card.parentNode.replaceChild(card, existing.card);
    } else {
      appendCard(card);
    }
    state.findings[body.id] = { body: body, card: card };
  }

  function showEvidence(body) {
    var card = appendCard(render.evidenceCard(body));
    state.evidence[body.id] = { body: body, card: card };
  }

  function answerEvidence(body) {
    var entry = state.evidence[body.request_id];
    if (!entry) {
      return;
    }
    var answered = render.evidenceCard({
      id: body.request_id,
      what: entry.body.what,
      why: entry.body.why,
      entity_ids: entry.body.entity_ids,
      status: 'answered',
      answer: body.answer
    });
    entry.card.parentNode.replaceChild(answered, entry.card);
    entry.card = answered;
  }

  function applyDisposition(body) {
    var entry = state.findings[body.finding_id];
    if (!entry) {
      return;
    }
    var status = entry.card.querySelector('.card-status');
    if (status) {
      status.className = 'card-status';
      status.textContent = render.dispositionText(body.disposition);
    }
  }

  function renderCoverage() {
    render.clear(ui.coverage);
    ui.coverage.appendChild(render.coverageSummary(state.coverage));
    ui.coverage.hidden = false;
  }

  /**
   * The running usage line, repainted on every `usage` event so it moves during the turn
   * rather than at `session.ended`. The summing is `render.usageLine`'s, in one place, with
   * one null rule (feature 005 T016a).
   */
  function renderUsage() {
    render.clear(ui.usage);
    ui.usage.appendChild(render.usageLine(state.usage));
  }

  function endTurn(body) {
    setTurnRunning(false);
    state.textBlock = null;
    if (body.reason && body.reason !== 'end') {
      appendCard(render.textBlock('system', 'The turn ended: ' + body.reason + '.'));
    }
  }

  function endSession(body) {
    setTurnRunning(false);
    state.textBlock = null;
    appendCard(render.textBlock('system', 'The session ended at ' + (body.ended_at || 'now') + '.'));
    // Nothing further will be streamed; a follow-up reopens the stream from the same seq.
    closeStream();
    showStreamState('The session ended.');
  }

  // ---- the review ----------------------------------------------------------------------------

  /**
   * Press Review, or Retry on an error card. `retryOf` names the chat this one replaces, which
   * the backend records on the session so the pair can be read back in the run folder (FR-028).
   */
  function startReview(retryOf) {
    if (state.startPending || state.turnRunning) {
      return;
    }

    closeStream();
    state.lastSeq = 0;
    state.reconnectDelay = RECONNECT_MIN;
    state.startPending = true;
    renderStartReview();
    showStreamState('');

    send('review.start', retryOf ? { retry_of: retryOf } : {}).then(function (payload) {
      resetTranscript();
      state.chatId = payload.chat_id;
      state.runDir = payload.run_dir;
      renderSession();
      setTurnRunning(true);
      openStream();
    }).catch(function (error) {
      appendCard(render.errorCard({
        error_class: error.errorClass,
        message: error.message,
        retryable: error.retryable
      }));
    }).then(function () {
      state.startPending = false;
      renderStartReview();
    });
  }

  /**
   * Whether Review can be pressed. One review at a time, for as long as its turn runs: a second
   * press throws the first chat away - `resetTranscript` clears its transcript and findings,
   * `chat_id` and `run_dir` are overwritten and its stream is closed - while its turn keeps
   * running in the backend with no Stop pointing at it, and a second extraction starts on the
   * SOLIDWORKS application thread on top of the first. Stop ends the turn; then Review is
   * pressable again (FR-030).
   */
  function renderStartReview() {
    ui.startReview.disabled = state.startPending || state.turnRunning || !state.documentInfo;
  }

  function resetTranscript() {
    render.clear(ui.transcript);
    render.clear(ui.coverage);
    ui.coverage.hidden = true;
    state.events = [];
    state.coverage = [];
    state.usage = [];
    renderUsage();
    state.findings = Object.create(null);
    state.evidence = Object.create(null);
    state.tools = Object.create(null);
    state.textBlock = null;
  }

  function renderSession() {
    ui.runDir.textContent = state.runDir || '';
    ui.openReport.disabled = !state.chatId;
    ui.openFolder.disabled = !state.chatId;
  }

  /** The follow-up box and Stop follow the turn: one running turn per chat (chat-api.md). */
  function setTurnRunning(running) {
    state.turnRunning = running;
    renderStartReview();
    ui.stop.disabled = !running || !state.chatId;
    ui.followupText.disabled = running || !state.chatId;
    ui.followupSend.disabled = running || !state.chatId;
  }

  function sendFollowUp() {
    var text = ui.followupText.value.trim();
    if (!text || !state.chatId || state.turnRunning) {
      return;
    }

    setTurnRunning(true);
    appendCard(render.textBlock('engineer', text));
    ui.followupText.value = '';

    call(sessionPath('/messages'), 'POST', { text: text }).then(function () {
      if (!state.stream) {
        // The previous turn ended and the stream was closed; pick it up from the same seq.
        openStream();
      }
    }).catch(function (error) {
      setTurnRunning(false);
      appendCard(render.errorCard({
        error_class: error.errorClass,
        message: error.message,
        retryable: error.retryable
      }));
    });
  }

  /** FR-030: a running turn is interruptible from the pane. */
  function stopTurn() {
    if (!state.chatId) {
      return;
    }
    ui.stop.disabled = true;
    call(sessionPath('/stop'), 'POST', {}).then(function () {
      showStreamState('Stop requested; the turn ends at the next tool boundary.');
    }).catch(function (error) {
      ui.stop.disabled = !state.turnRunning;
      appendCard(render.errorCard({
        error_class: error.errorClass,
        message: error.message,
        retryable: error.retryable
      }));
    });
  }

  // ---- card actions ---------------------------------------------------------------------------

  /**
   * One listener for the whole transcript. `render.js` declares what a button does with
   * `data-action` and this decides what that means, so no card carries a handler of its own and
   * a card rebuilt after an update keeps working.
   */
  function onTranscriptClick(event) {
    var target = event.target;
    if (!target || !target.getAttribute) {
      return;
    }

    var action = target.getAttribute('data-action');
    if (!action) {
      return;
    }

    var card = target.closest('.card');
    switch (action) {
      case 'show':
        showInSolidWorks(card);
        return;
      case 'expand':
        expand(card, target);
        return;
      case 'accept':
        decide(card, 'accepted');
        return;
      case 'reject':
        decide(card, 'rejected');
        return;
      case 'defer':
        decide(card, 'deferred');
        return;
      case 'answer':
        answer(card);
        return;
      case 'retry':
        startReview(state.chatId);
        return;
      case 'settings':
        ui.settings.hidden = false;
        ui.settings.scrollIntoView();
        return;
      case 'log':
        send('log.open', {}).catch(function (error) {
          cardStatus(card, error.message, true);
        });
        return;
      default:
        return;
    }
  }

  function cardStatus(card, message, bad) {
    if (!card) {
      return;
    }
    var status = card.querySelector('.card-status');
    if (!status) {
      return;
    }
    status.className = bad ? 'card-status bad' : 'card-status';
    status.textContent = message;
  }

  function expand(card, target) {
    var details = card && card.querySelector('.details');
    if (!details) {
      return;
    }
    details.hidden = !details.hidden;
    target.textContent = details.hidden ? 'Details' : 'Hide details';
  }

  function showInSolidWorks(card) {
    var entry = card ? state.findings[card.getAttribute('data-finding-id')] : null;
    if (!entry) {
      return;
    }

    var request = render.entityRequest(entry.body);
    if (!request) {
      cardStatus(
        card,
        'This finding carries no persistent reference. Affected components: '
          + (render.list(entry.body.component_ids) || 'none named') + '.',
        true);
      return;
    }

    cardStatus(card, 'Selecting in SOLIDWORKS...', false);
    send('entity.show', request).then(function (payload) {
      if (payload.ok) {
        cardStatus(card, 'Selected ' + (payload.full_path || 'the entity') + '.', false);
        return;
      }
      // An unresolvable reference is an answer, not a failure: the state code and the
      // component's full path are what let the engineer find it by hand (spec Edge Cases).
      cardStatus(
        card,
        'Not selected (state ' + payload.state_code + '): ' + (payload.message || 'no reason given')
          + (payload.full_path ? ' Look for ' + payload.full_path + ' in the tree.' : ''),
        true);
    }).catch(function (error) {
      cardStatus(card, error.message, true);
    });
  }

  function decide(card, decision) {
    var findingId = card ? card.getAttribute('data-finding-id') : null;
    if (!findingId || !state.chatId) {
      return;
    }

    var note = card.querySelector('.note');
    cardStatus(card, 'Recording ' + decision + '...', false);

    // `by` is left to the backend, which attributes the disposition to the session's engineer:
    // the page has no idea who is at the workstation and must not invent one.
    call(
      sessionPath('/findings/' + encodeURIComponent(findingId) + '/disposition'),
      'POST',
      { decision: decision, note: note ? note.value : '' }
    ).then(function (finding) {
      cardStatus(card, render.dispositionText(finding && finding.disposition), false);
    }).catch(function (error) {
      cardStatus(card, error.errorClass + ': ' + error.message, true);
    });
  }

  function answer(card) {
    var requestId = card ? card.getAttribute('data-request-id') : null;
    var box = card ? card.querySelector('.answer') : null;
    if (!requestId || !box || !state.chatId) {
      return;
    }

    var text = box.value.trim();
    if (!text) {
      cardStatus(card, 'Type an answer first.', true);
      return;
    }

    cardStatus(card, 'Sending...', false);
    setTurnRunning(true);
    call(sessionPath('/evidence/' + encodeURIComponent(requestId)), 'POST', { answer: text })
      .then(function () {
        if (!state.stream) {
          openStream();
        }
      })
      .catch(function (error) {
        setTurnRunning(false);
        cardStatus(card, error.errorClass + ': ' + error.message, true);
      });
  }

  // ---- settings rendering ---------------------------------------------------------------------

  function option(value, label) {
    var element = document.createElement('option');
    element.value = value;
    element.appendChild(document.createTextNode(label));
    return element;
  }

  function showBanner(text) {
    ui.banner.textContent = text || '';
    ui.banner.hidden = !text;
  }

  function showStreamState(text) {
    ui.streamState.textContent = text || '';
  }

  function showStatus(payload) {
    var message = (payload && payload.message) || '';
    var stage = payload && payload.stage;
    if (stage === 'error') {
      showBanner(message);
      renderBackendState('Error', true);
      return;
    }
    if (stage === 'ready') {
      showBanner('');
      if (!state.backend) {
        // The backend finished starting after this page loaded, so the `init` it was given
        // carried no endpoint. Ask again rather than leaving Review unusable until a reload.
        requestInit(true);
      }
    }
    renderBackendState(message || stage || '', false);
  }

  function renderBackendState(text, bad) {
    ui.backendState.textContent = text || (state.backend ? 'Backend ready' : 'Backend starting');
    ui.backendState.className = 'badge' + (bad ? ' bad' : (state.backend ? ' ready' : ''));
  }

  function renderDocument() {
    var info = state.documentInfo;
    if (!info) {
      ui.documentName.textContent = 'No document open';
      renderStartReview();
      return;
    }
    var name = info.path;
    if (info.configuration) {
      name = name + '  [' + info.configuration + ']';
    }
    ui.documentName.textContent = name;
    renderStartReview();
  }

  function renderProviders() {
    render.clear(ui.provider);
    state.providers.forEach(function (name) {
      ui.provider.appendChild(option(name, name === 'fake' ? 'fake (scripted, development)' : name));
    });
    if (state.settings && state.providers.indexOf(state.settings.provider) >= 0) {
      ui.provider.value = state.settings.provider;
    }
    applyProviderFields();
  }

  // The two provider-specific rows, shown only for the provider that reads them: the backend
  // reads OPENAI_BASE_URL for openai only, and Gemini Enterprise for gemini only, so offering
  // either anywhere else is offering a setting that would be refused or ignored.
  function applyProviderFields() {
    ui.enterprise.hidden = currentProvider() !== 'gemini';
    ui.baseUrlField.hidden = currentProvider() !== 'openai';
  }

  function setModels(models) {
    state.models = models || [];
    var chosen = ui.model.value || (state.settings ? state.settings.model : '');
    render.clear(ui.model);
    state.models.forEach(function (model) {
      ui.model.appendChild(option(model.id, model.label || model.id));
    });
    if (chosen && !state.models.some(function (model) { return model.id === chosen; })) {
      // Keep what is configured visible even when the provider no longer lists it, rather
      // than silently switching the engineer to a different model.
      ui.model.appendChild(option(chosen, chosen + ' (not offered)'));
    }
    if (chosen) {
      ui.model.value = chosen;
    }
    ui.modelNote.textContent = state.models.length ? '' : 'No model list yet. Press Refresh.';
  }

  function renderSettings(settings, keySource) {
    state.settings = settings || state.settings;
    state.keySource = keySource || state.keySource;
    if (!state.settings) {
      return;
    }

    renderProviders();
    ui.effort.value = state.settings.effort;
    ui.baseUrl.value = state.settings.base_url || '';
    ui.project.value = state.settings.gemini_enterprise ? state.settings.gemini_enterprise.project : '';
    ui.location.value = state.settings.gemini_enterprise ? state.settings.gemini_enterprise.location : '';
    ui.apiKey.value = '';
    ui.clearKey.checked = false;
    ui.keySource.textContent = describeKeySource(state.keySource);
    setModels(state.models);
  }

  function describeKeySource(source) {
    if (source === 'settings') {
      return 'A key is stored for this Windows account. Leave this blank to keep it.';
    }
    if (source === 'env') {
      return 'No stored key; the key in this workstation environment will be used.';
    }
    return 'No key is stored. Reviews will fail until one is entered.';
  }

  // A key is a credential for one vendor, and there is one key slot: saving a different
  // provider without typing a new key retires the stored one rather than sending it to the
  // other vendor's endpoint. The engineer is told before pressing Save, not after.
  function warnAboutTheStoredKey() {
    if (state.keySource === 'settings' && state.settings
        && currentProvider() !== state.settings.provider) {
      ui.keySource.textContent =
        'Saving removes the stored key: it belongs to ' + state.settings.provider
        + '. Enter a ' + currentProvider() + ' key to keep reviewing.';
      return;
    }
    ui.keySource.textContent = describeKeySource(state.keySource);
  }

  function currentProvider() {
    return ui.provider.value || (state.settings ? state.settings.provider : 'openai');
  }

  // ---- settings actions -------------------------------------------------------------------

  function refreshModels() {
    var provider = currentProvider();
    ui.modelNote.className = 'note';
    ui.modelNote.textContent = 'Loading models...';
    ui.refreshModels.disabled = true;
    send('models.list', { provider: provider }).then(function (payload) {
      setModels(payload.models || []);
    }).catch(function (error) {
      ui.modelNote.className = 'note bad';
      ui.modelNote.textContent = error.message;
    }).then(function () {
      ui.refreshModels.disabled = false;
    });
  }

  function saveSettings() {
    var payload = {
      provider: currentProvider(),
      model: ui.model.value,
      effort: ui.effort.value,
      // null keeps the stored key; '' removes it; a typed value replaces it.
      api_key: ui.clearKey.checked ? '' : (ui.apiKey.value ? ui.apiKey.value : null),
      base_url: currentProvider() === 'openai' && ui.baseUrl.value.trim()
        ? ui.baseUrl.value.trim()
        : null,
      gemini_enterprise: null
    };

    if (currentProvider() === 'gemini' && ui.project.value.trim() && ui.location.value.trim()) {
      payload.gemini_enterprise = {
        project: ui.project.value.trim(),
        location: ui.location.value.trim()
      };
    }

    ui.save.disabled = true;
    ui.saveState.className = 'note';
    ui.saveState.textContent = 'Saving...';
    showBanner('');

    send('settings.save', payload).then(function (reply) {
      // The key box is cleared by renderSettings: the typed key is now in the settings store
      // and there is no reason for it to stay in the renderer process.
      renderSettings(reply.settings, reply.key_source);
      ui.saveState.textContent = 'Saved.';
      // The save restarted the backend, so the port and the token this page holds are the old
      // child's. Nothing else tells the page that.
      requestInit(false);
    }).catch(function (error) {
      ui.saveState.className = 'note bad';
      ui.saveState.textContent = error.errorClass === 'TurnRunning'
        ? error.message
        : (error.errorClass + ': ' + error.message);
    }).then(function () {
      ui.save.disabled = false;
    });
  }

  function start() {
    requestInit(true);
  }

  /**
   * Asks the host for `init` and applies it.
   *
   * It is sent more than once on purpose. The pane opens before the backend has finished
   * starting, so the first `init` usually carries `backend: null`, and a save that restarts the
   * backend gives the new child a new port and a new token; in both cases the page's only way
   * to learn where the backend now is, is to ask again. `init` is the row that answers that
   * (contracts/pane-host-messages.md), and asking is cheap: the host builds the reply from
   * state it already holds and the page's transcript is left alone.
   */
  function requestInit(loadModels) {
    if (state.initPending) {
      return;
    }

    state.initPending = true;
    send('ready', {}).then(function (payload) {
      state.providers = payload.providers || state.providers;
      state.backend = payload.backend || null;
      state.token = payload.token || null;
      state.runRoot = payload.run_root || null;
      state.documentInfo = payload.document || null;
      renderSettings(payload.settings, payload.key_source);
      renderDocument();
      renderBackendState(state.backend ? 'Backend ready' : 'Backend starting', false);
      if (loadModels && state.backend) {
        refreshModels();
      }
    }).catch(function (error) {
      showBanner(error.message);
    }).then(function () {
      state.initPending = false;
    });
  }

  // ---- wiring -------------------------------------------------------------------------

  function bind() {
    ui.banner = document.getElementById('banner');
    ui.backendState = document.getElementById('backend-state');
    ui.documentName = document.getElementById('document-name');
    ui.settings = document.getElementById('settings');
    ui.toggleSettings = document.getElementById('toggle-settings');
    ui.provider = document.getElementById('provider');
    ui.model = document.getElementById('model');
    ui.modelNote = document.getElementById('model-note');
    ui.refreshModels = document.getElementById('refresh-models');
    ui.effort = document.getElementById('effort');
    ui.apiKey = document.getElementById('api-key');
    ui.clearKey = document.getElementById('clear-key');
    ui.keySource = document.getElementById('key-source');
    ui.baseUrl = document.getElementById('base-url');
    ui.enterprise = document.getElementById('enterprise');
    ui.baseUrlField = document.getElementById('base-url-field');
    ui.project = document.getElementById('gcp-project');
    ui.location = document.getElementById('gcp-location');
    ui.save = document.getElementById('save-settings');
    ui.saveState = document.getElementById('save-state');

    ui.startReview = document.getElementById('start-review');
    ui.stop = document.getElementById('stop-turn');
    ui.openReport = document.getElementById('open-report');
    ui.openFolder = document.getElementById('open-folder');
    ui.openLog = document.getElementById('open-log');
    ui.runDir = document.getElementById('run-dir');
    ui.streamState = document.getElementById('stream-state');
    ui.usage = document.getElementById('usage-line');
    ui.transcript = document.getElementById('transcript');
    ui.coverage = document.getElementById('coverage-panel');
    ui.followup = document.getElementById('followup');
    ui.followupText = document.getElementById('followup-text');
    ui.followupSend = document.getElementById('followup-send');

    ui.toggleSettings.addEventListener('click', function () {
      ui.settings.hidden = !ui.settings.hidden;
    });
    ui.provider.addEventListener('change', function () {
      applyProviderFields();
      warnAboutTheStoredKey();
      setModels([]);
      ui.model.value = '';
      refreshModels();
    });
    ui.refreshModels.addEventListener('click', refreshModels);
    ui.save.addEventListener('click', saveSettings);
    ui.clearKey.addEventListener('change', function () {
      ui.apiKey.disabled = ui.clearKey.checked;
      if (ui.clearKey.checked) {
        ui.apiKey.value = '';
      }
    });

    ui.startReview.addEventListener('click', function () {
      startReview(null);
    });
    ui.stop.addEventListener('click', stopTurn);
    ui.openReport.addEventListener('click', function () {
      send('report.open', { chat_id: state.chatId }).catch(function (error) {
        showBanner(error.message);
      });
    });
    ui.openFolder.addEventListener('click', function () {
      send('folder.open', { chat_id: state.chatId }).catch(function (error) {
        showBanner(error.message);
      });
    });
    ui.openLog.addEventListener('click', function () {
      send('log.open', {}).catch(function (error) {
        showBanner(error.message);
      });
    });
    ui.followup.addEventListener('submit', function (event) {
      event.preventDefault();
      sendFollowUp();
    });
    ui.transcript.addEventListener('click', onTranscriptClick);

    if (bridge) {
      bridge.addEventListener('message', onHostMessage);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      bind();
      start();
    });
  } else {
    bind();
    start();
  }
})();
