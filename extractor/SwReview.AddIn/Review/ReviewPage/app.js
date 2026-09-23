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
  4. The backend is reached over `fetch` - messages, evidence answers, dispositions and Stop -
     at the `origin` the host sent in `init`, which is THIS PAGE'S OWN origin under
     `/__backend`. Nothing here crosses the network: the host answers that prefix itself and
     calls the backend from C#, because a Task Pane page is a browser process and an endpoint
     web filter that intercepts browser HTTP to loopback answers such a call with its own
     interstitial no `fetch` can click through (docs/pane-backend-proxy.md). The page's CSP is
     `connect-src 'self'` for the same reason, so a loopback URL is refused here before a
     socket is ever opened. The event stream is the one route that cannot be served that way -
     a `WebResourceRequested` response has to be complete before it is handed back, and a
     stream never is - so the HOST reads `GET /sessions/{chat_id}/events` and pushes each raw
     frame here as `events.frame` (chat-api.md "Reading the event stream"). This
     page asks with `events.open`, gives up with `events.close`, and parses what arrives with
     the same `onFrame` it always used - one SSE parser, and it lives here. Reconnect and its
     backoff stay here too, because this page is what knows which `seq` it has shown.
  5. The page names no path. `report.open` and `folder.open` carry the `chat_id` and the host
     resolves the folder from its own record.
*/

(function () {
  'use strict';

  var bridge = (window.chrome && window.chrome.webview) ? window.chrome.webview : null;
  var render = window.SwReviewRender;
  var docs = window.SwReviewDocument;

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

  /**
   * How long a finding card stays lit after a ranked row was followed into the transcript.
   * Long enough to find with the eye after the scroll, short enough that the transcript is not
   * left with a permanently highlighted row nobody asked about any more.
   */
  var FLASH_MS = 2000;

  /**
   * The separator between the facts that share the transcript header's one line. An escape
   * rather than the character itself, so this file stays ASCII like every other page file in
   * the pane.
   */
  var DOT = ' · ';

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
    preparationAvailable: false,
    preparation: null,
    preparationEpoch: 0,
    attentionEpoch: 0,

    // ---- the chat ----
    chatId: null,
    runDir: null,
    turnRunning: false,

    // The document the review on screen is of, as `review.started` named it, and whether the
    // document on screen is some other one (U8). Stale results are hidden, not discarded: the
    // reviewed document coming back shows them again.
    reviewed: null,
    resultsStale: false,

    // Whether a `review.start` is in flight. Kept apart from `turnRunning` because the two
    // disable the Review button for different reasons and end at different moments: the
    // request ends when the host replies, the turn ends at `turn.ended`.
    startPending: false,
    lastSeq: 0,
    events: [],
    // The reasons this page has already said it dropped something from the stream, so a
    // whole review of one kind of unreadable frame is one card rather than thousands.
    unreadable: Object.create(null),
    coverage: [],

    // One entry per model round trip, as the `usage` events carry them. The running usage
    // line is summed from this array rather than read off the session, so it moves while the
    // turn is still running (feature 005 T016a, contracts/usage.md section 6).
    usage: [],
    findings: Object.create(null),
    evidence: Object.create(null),
    tools: Object.create(null),

    // What the transcript's own header says about itself: how many calls have finished, and
    // which one is running right now. The rounds are `state.usage.length` and are not counted
    // twice here.
    toolsFinished: 0,
    runningTool: '',

    // Whether the transcript is folded to its header. It starts folded - index.html says so -
    // because the tool calls and the model's prose are the record of how the review reached
    // its findings rather than the findings themselves.
    transcriptFolded: true,
    followUpPending: false,
    notExamined: null,
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

  /**
   * One message the host does not reply to (`events.open`, `events.close`).
   *
   * Posted with no `id`, so nothing is left waiting for an answer that is never coming: a
   * stream that is reopened on every reconnect would otherwise leave one pending promise per
   * attempt for the life of the page. A refusal still arrives - as an unsolicited `error`,
   * which reaches the banner.
   */
  function post(type, payload) {
    if (!bridge) {
      return;
    }
    bridge.postMessage({ type: type, id: null, payload: payload || {} });
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
        clearPreparation();
        state.documentInfo = payload && payload.path ? payload : null;
        renderDocument();
        renderBinding();
        return;
      case 'backend.stopped':
        state.backend = null;
        state.token = null;
        closeStream();
        setTurnRunning(false);
        renderBackendState('The backend stopped. Reopen the pane to start it again.', true);
        return;
      case 'events.frame':
        // One raw SSE frame, read by the host. Frames for a chat this page is no longer
        // showing are dropped: a reconnect or a second review replaces the transcript, and a
        // late frame from the stream before it belongs to a session that is gone.
        if (payload.chat_id === state.chatId) {
          // A frame is the only proof this side of the channel has that the stream really
          // connected: `events.open` is a request, and the host does not answer it. So this is
          // where the backoff resets. Resetting it in `openStream` - which is exactly what the
          // reconnect timer calls - undoes the doubling on every retry, and a backend that is
          // down is then reopened once a second for the life of the pane.
          state.reconnectDelay = RECONNECT_MIN;
          // The stream state is not written here: "Streaming." means an event was read, not
          // that bytes arrived, and `onFrame` is where that is known. A keep-alive comment
          // proves the socket and nothing else, and a page that said "Streaming." on any
          // frame looked healthy for three whole reviews in which it understood nothing
          // (docs/pane-findings-2026-09-18.md).
          onFrame(payload.frame || '');
        }
        return;
      case 'events.closed':
        if (payload.chat_id === state.chatId) {
          scheduleReconnect(payload.reason || 'The event stream closed.');
        }
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
   * Asks the host to read `GET /sessions/{chat_id}/events` and push the frames here.
   *
   * The page does not make this call itself, and it could not be proxied like the others
   * either: a `WebResourceRequested` response must be complete before the host hands it back,
   * which a stream never is. The host reads it instead, from C#, where no endpoint web filter
   * intercepts it (docs/pane-backend-proxy.md). `last_event_id` carries the
   * highest `seq` already on screen, so a reconnect replays what was missed from
   * `events.jsonl` and nothing that was not - the same rule as before, on the other side of
   * the channel.
   */
  function openStream() {
    if (!state.chatId) {
      return;
    }

    closeStream();

    state.stream = state.chatId;
    post('events.open', {
      chat_id: state.chatId,
      last_event_id: state.lastSeq > 0 ? String(state.lastSeq) : null
    });
  }

  /** One SSE frame: `id:`, `data:` (possibly several lines), and comments to ignore. */
  /**
   * One SSE frame, the text between blank lines, as `_sse` in chat/server.py writes it and
   * the host hands it on: `id` is the `seq`, `event` is the `type` and `data` is the body
   * alone (contracts/chat-api.md, the events row). The `{seq, type, body}` envelope the
   * transcript keeps is built here from those three fields - it is not in the frame. Until
   * 2026-09-18 this parser expected the envelope inside `data` and threw `event:` away, so
   * every real frame read as an event with no type and fell through `onChatEvent`.
   *
   * "Streaming." is written here, once a chat event has been read out of the frame and before
   * it is handled, so a handler that has something more specific to say ("The session
   * ended.") has the last word. A keep-alive comment, a frame with no `data`, and data that
   * is not JSON leave the stream state alone.
   */
  function onFrame(frame) {
    var lines = frame.split(/\r?\n/);
    var data = [];
    var id = null;
    var type = null;

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
      } else if (name === 'event') {
        type = value;
      } else if (name === 'data') {
        data.push(value);
      }
    }

    if (!data.length) {
      return;
    }

    var body;
    try {
      body = JSON.parse(data.join('\n'));
    } catch (error) {
      reportUnreadable('the data of an event, which was not JSON');
      return;
    }

    var seq = parseInt(id || '0', 10);
    if (!(seq > 0)) {
      seq = 0;
    }
    if (seq > state.lastSeq) {
      state.lastSeq = seq;
    }

    var event = { seq: seq, type: type, body: body };
    state.events.push(event);
    if (state.events.length > EVENT_LIMIT) {
      state.events.splice(0, state.events.length - EVENT_LIMIT);
    }

    showStreamState('Streaming.');
    onChatEvent(event);
  }

  function scheduleReconnect(why) {
    if (!state.stream) {
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
      state.stream = null;
      post('events.close', {});
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
        reportUnreadable('an event of type "' + (event.type || '') + '"');
        return;
    }
  }

  /**
   * One card per distinct reason, saying the page dropped something from the stream. A
   * review whose every event is dropped must not look like a healthy one: that is how the
   * envelope mismatch fixed on 2026-09-18 shipped past three workstation runs.
   */
  function reportUnreadable(what) {
    if (state.unreadable[what]) {
      return;
    }
    state.unreadable[what] = true;
    appendCard(render.textBlock(
      'system',
      'This page could not read ' + what + ' from the event stream and ignored it. '
        + 'report.md in the run folder is written by the backend and is unaffected.'));
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
    var completed = state.textBlock;
    render.clear(completed);
    render.write(completed, text || '');
    state.textBlock = null;
    scrollToEnd();
    if (state.followUpPending) {
      state.followUpPending = false;
      completed.parentNode.scrollIntoView({ block: 'nearest' });
    }
  }

  function startTool(body) {
    var card = appendCard(render.toolCard(body));
    state.tools['s' + body.step_index] = { body: body, card: card };
    // Folded, the transcript's header is the only place a running call is visible at all.
    state.runningTool = body.tool || '';
    renderTranscriptHead();
  }

  /** The finished body is merged onto the started one, so the card shows the whole call. */
  function finishTool(body) {
    state.toolsFinished += 1;
    state.runningTool = '';
    renderTranscriptHead();

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
    showDisposition(entry.card, body.disposition);
  }

  /**
   * The disposition sentence on one card, and the class that says there is one.
   *
   * Both writers go through here - the `disposition` event from the stream and the reply to the
   * engineer's own press - so a decided finding looks the same whichever recorded it, and the
   * "decided" class agrees with the one `render.findingCard` puts on a card it builds fresh.
   */
  function showDisposition(card, disposition) {
    var status = card ? card.querySelector('.card-status') : null;
    if (!status) {
      return;
    }
    var text = render.dispositionText(disposition);
    status.className = render.dispositionClass(text);
    status.textContent = text;
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
    // A round trip is one of the two numbers the transcript's header counts.
    renderTranscriptHead();
  }

  // ---- the transcript's header (the fold) ----------------------------------------------------

  /**
   * What the folded transcript says about itself: how many tool calls have finished, how many
   * model round trips there have been, and - while one is in flight - which tool is running.
   *
   * The count is the whole point of the fold. A transcript folded to nothing would be a
   * transcript an engineer could not tell from an empty one, and "a hung review looks exactly
   * like a finished one" is the complaint this page already has on record
   * (docs/pane-findings-2026-09-18.md).
   */
  function renderTranscriptHead() {
    var tools = state.toolsFinished;
    var rounds = state.usage.length;

    var counted = tools + ' tool call' + (tools === 1 ? '' : 's')
      + DOT + rounds + ' round' + (rounds === 1 ? '' : 's');
    if (state.runningTool) {
      counted += DOT + state.runningTool;
    }

    render.clear(ui.transcriptToggle);
    ui.transcriptToggle.appendChild(render.el('span', 'eyebrow', 'Transcript'));
    ui.transcriptToggle.appendChild(render.el('span', 'fold-count', counted));
  }

  /**
   * Folds or unfolds the transcript. A class rather than the `hidden` property, because the
   * findings, the evidence requests and the error cards stay on screen inside a folded
   * transcript - what folds is the model's prose and its tool calls.
   */
  function foldTranscript(folded) {
    state.transcriptFolded = folded;
    ui.transcript.className = folded ? 'transcript folded' : 'transcript';
    ui.transcriptToggle.setAttribute('aria-expanded', folded ? 'false' : 'true');
    if (!folded) {
      scrollToEnd();
    }
  }

  function endTurn(body) {
    setTurnRunning(false);
    state.textBlock = null;
    state.runningTool = '';
    renderTranscriptHead();
    if (body.reason && body.reason !== 'end') {
      appendCard(render.textBlock('system', 'The turn ended: ' + body.reason + '.'));
    }
  }

  function endSession(body) {
    setTurnRunning(false);
    state.textBlock = null;
    state.runningTool = '';
    renderTranscriptHead();
    appendCard(render.textBlock('system', 'The session ended at ' + (body.ended_at || 'now') + '.'));
    // Nothing further will be streamed; a follow-up reopens the stream from the same seq.
    closeStream();
    showStreamState('The session ended.');
    loadAttention();
  }

  /**
   * What to start with, read once the session has ended.
   *
   * The ranking is not on the stream and not on the session view: it is computed from the
   * finished session by `GET /sessions/{chat_id}/attention`, which writes nothing, so the page
   * asks for it here rather than accumulating anything of its own (contracts/attention.md
   * section 5, research R2.8). Nothing is ranked or reordered on this side - the rows are
   * rendered in the order they arrive.
   *
   * Two rules, and both are about a page that has moved on.
   *
   * The chat is captured before the call and checked after it. `sessionPath` reads
   * `state.chatId`, and it is read here, synchronously, so the path and `chatId` name the same
   * chat; what can change while the request is in flight is `state.chatId`, and an answer for a
   * chat that is no longer on screen belongs to a transcript `resetTranscript` has already
   * cleared. Showing it would open a fresh review under the previous review's rows.
   *
   * A failed read shows nothing new. The rows amplify findings that are already in the
   * transcript and in `report.md`, so a banner about them at the moment the session ends would
   * be noise about a panel nobody has missed. The rejection handler is the second argument of
   * `then` rather than a `catch` after it, so it answers the fetch and only the fetch: a throw
   * inside the render is a defect and is not swallowed here.
   */
  function loadAttention() {
    var chatId = state.chatId;
    var epoch = state.attentionEpoch;
    if (!chatId) {
      return;
    }

    call(sessionPath('/attention'), 'GET').then(
      function (ranking) {
        if (!ranking || state.chatId !== chatId || state.attentionEpoch !== epoch) {
          return;
        }

        render.clear(ui.attention);
        ui.attention.appendChild(render.attentionPanel(ranking));
        syncFindingExplanations(ranking);
        ui.attention.hidden = false;
      },
      function () {
        // Nothing new: the panel stays as it is, which for a review that has just ended is
        // hidden.
      });
  }

  // ---- the review ----------------------------------------------------------------------------

  /**
   * Press Review, or Retry on an error card. `retryOf` names the chat this one replaces, which
   * the backend records on the session so the pair can be read back in the run folder (FR-028).
   */
  function clearPreparation() {
    state.preparation = null;
    state.preparationEpoch++;
    ui.preparation.hidden = true;
    renderStartReview();
  }

  function syncFindingExplanations(ranking) {
    // Text is persisted by the backend and repeated verbatim on both surfaces. Never derive
    // an explanation, a verdict, or an order from the finding on the page. On the card it is
    // the first line inside the fold (U10): the headline stays one line, and the sentence that
    // explains the finding reads before the evidence it explains.
    var previous = ui.transcript.querySelectorAll('.finding-explanation');
    for (var index = 0; index < previous.length; index++) {
      previous[index].parentNode.removeChild(previous[index]);
    }
    if (ranking.empty_reason) {
      return;
    }
    var rows = ranking.rows || [];
    var count = typeof ranking.top_n === 'number' ? ranking.top_n : rows.length;
    for (var rowIndex = 0; rowIndex < rows.length && rowIndex < count; rowIndex++) {
      var row = rows[rowIndex];
      var members = row.member_finding_ids || [row.finding_id];
      for (var memberIndex = 0; memberIndex < members.length; memberIndex++) {
        var entry = state.findings[members[memberIndex]];
        if (entry && typeof row.explanation === 'string' && row.explanation) {
          var fold = entry.card.querySelector('.details');
          fold.insertBefore(render.el('p', 'finding-explanation', row.explanation), fold.firstChild);
        }
      }
    }
  }

  function prepareReview(retryOf) {
    if (!state.preparationAvailable) {
      startReview(retryOf);
      return;
    }
    if (state.startPending || state.turnRunning) {
      return;
    }
    clearPreparation();
    var epoch = state.preparationEpoch;
    state.startPending = true;
    renderStartReview();
    send('review.prepare', {}).then(function (payload) {
      state.startPending = false;
      renderStartReview();
      if (state.preparationEpoch !== epoch) {
        return;
      }
      if (!payload.requires_attention) {
        startReview(retryOf, payload.preparation_id);
        return;
      }
      state.preparation = { payload: payload, retryOf: retryOf };
      renderStartReview();
      ui.preparationSummary.textContent = String(payload.unread_count || 0) + ' of '
        + String(payload.component_count || 0) + ' component instances are not resolved. '
        + String(payload.gap_count || 0) + ' gaps were recorded while reading the tree. '
        + 'No review tokens have been used.';
      render.clear(ui.preparationInstances);
      var instances = payload.instances || [];
      for (var index = 0; index < instances.length; index++) {
        var item = instances[index];
        ui.preparationInstances.appendChild(render.el('li', '',
          (item.instance || item.name || 'Unnamed component') + ' (' + item.state + ')'));
      }
      if (payload.omitted_instances) {
        ui.preparationInstances.appendChild(render.el('li', '',
          String(payload.omitted_instances) + ' additional unread instances are not listed here.'));
      }
      ui.preparation.hidden = false;
    }).catch(function (error) {
      state.startPending = false;
      renderStartReview();
      if (state.preparationEpoch === epoch) {
        appendCard(render.errorCard({
          error_class: error.errorClass, message: error.message, retryable: error.retryable
        }));
      }
    });
  }

  function startReview(retryOf, preparationId) {
    if (state.startPending || state.turnRunning) {
      return;
    }

    clearPreparation();

    closeStream();
    state.lastSeq = 0;
    state.reconnectDelay = RECONNECT_MIN;
    state.startPending = true;
    // A new extraction may fail before the review.started reply. Do not leave the previous
    // session's component warning presented as if it described this attempt.
    state.notExamined = null;
    renderNotExamined();
    renderStartReview();
    showStreamState('');

    var request = retryOf ? { retry_of: retryOf } : {};
    if (preparationId) {
      request.preparation_id = preparationId;
    }
    send('review.start', request).then(function (payload) {
      resetTranscript();
      state.chatId = payload.chat_id;
      state.runDir = payload.run_dir;
      state.reviewed = payload.document || null;
      state.notExamined = payload.not_examined || null;
      renderNotExamined();
      renderSession();
      renderBinding();
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
    var followupDisabled = state.startPending || state.turnRunning || !!state.preparation
      || !state.chatId || state.resultsStale;
    ui.followupText.disabled = followupDisabled;
    ui.followupSend.disabled = followupDisabled;
    ui.clearReview.disabled = !canClearReview();
  }

  /**
   * Clear review is for a review that has finished: there has to be one, and no turn or start
   * may be in flight. Clearing a running turn would orphan it - its stream closed, its Stop
   * pointing at nothing - while the backend goes on spending tokens on it.
   */
  function canClearReview() {
    return !!state.chatId && !state.turnRunning && !state.startPending;
  }

  /**
   * Clear review (U8): the pane back to "no review", without opening another document and
   * without spending a token. The chat is forgotten here only - the backend and the run folder
   * keep it, and report.md is where it is read from now on.
   */
  function clearReview() {
    if (!canClearReview()) {
      return;
    }
    closeStream();
    resetTranscript();
    state.chatId = null;
    state.runDir = null;
    state.reviewed = null;
    state.lastSeq = 0;
    showStreamState('');
    renderBinding();
  }

  /**
   * Whether the review on screen is of the document on screen, and what the page does when it
   * is not (U8, docs/pane-findings-2026-09-20-review-gui.md section 1).
   *
   * Re-judged whenever either side moves: a review starts or is cleared, or the host says the
   * document changed. The rule is `web/shared/document.js`'s, shared with the check tabs, and a
   * review whose `review.started` named no document is never taken for the open one.
   *
   * Stale results are hidden by one class on the body rather than removed, so a finding that
   * streams in while another document is open is hidden like the rest and every card comes back
   * when the reviewed document does. What acts on the review - Open report, Open run folder,
   * the follow-up - is disabled while it is hidden; Stop is not, because a running turn spends
   * tokens whatever document is on screen (FR-030).
   */
  function renderBinding() {
    state.resultsStale = !!state.chatId && !docs.same(state.reviewed, state.documentInfo);
    document.body.classList.toggle('results-stale', state.resultsStale);

    render.clear(ui.staleReview);
    if (state.resultsStale) {
      render.write(ui.staleReview, staleSentence());
    }
    ui.staleReview.hidden = !state.resultsStale;

    renderSession();
    renderStartReview();
  }

  /** The one line a hidden review leaves: whose review it is, and what to press instead. */
  function staleSentence() {
    var sentence = 'This review is of ' + (docs.label(state.reviewed) || 'another document') + '.';
    return state.documentInfo
      ? sentence + ' Press Review to review ' + docs.label(state.documentInfo) + '.'
      : sentence + ' No document is open.';
  }

  function resetTranscript() {
    render.clear(ui.transcript);
    render.clear(ui.coverage);
    ui.coverage.hidden = true;
    render.clear(ui.attention);
    ui.attention.hidden = true;
    state.events = [];
    state.unreadable = Object.create(null);
    state.coverage = [];
    state.usage = [];
    renderUsage();
    state.findings = Object.create(null);
    state.evidence = Object.create(null);
    state.tools = Object.create(null);
    state.toolsFinished = 0;
    state.runningTool = '';
    state.followUpPending = false;
    state.notExamined = null;
    renderNotExamined();
    renderTranscriptHead();
    state.textBlock = null;
  }

  function renderSession() {
    ui.runDir.textContent = state.runDir || '';
    ui.openReport.disabled = !state.chatId || state.resultsStale;
    ui.openFolder.disabled = !state.chatId || state.resultsStale;
  }

  /** The follow-up box and Stop follow the turn: one running turn per chat (chat-api.md). */
  function setTurnRunning(running) {
    if (running) {
      state.attentionEpoch++;
    }
    state.turnRunning = running;
    renderStartReview();
    ui.stop.disabled = !running || !state.chatId;
  }

  function sendFollowUp() {
    var text = ui.followupText.value.trim();
    if (!text || !state.chatId || state.turnRunning || state.startPending || state.preparation
        || state.resultsStale) {
      return;
    }

    // Follow-up prose is useful output, not part of the collapsed tool trace. Open the
    // transcript before posting so both the question and the answer are visible even when the
    // engineer never opened Transcript manually.
    foldTranscript(false);
    state.followUpPending = true;
    setTurnRunning(true);
    appendCard(render.textBlock('engineer', text));
    ui.followupText.value = '';

    call(sessionPath('/messages'), 'POST', { text: text }).then(function () {
      if (!state.stream) {
        // The previous turn ended and the stream was closed; pick it up from the same seq.
        openStream();
      }
    }).catch(function (error) {
      state.followUpPending = false;
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
        expand(card);
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
        prepareReview(state.chatId);
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

  /**
   * A ranked row is a way into the transcript.
   *
   * The Start here panel amplifies findings that are already below it; until now the rows were
   * inert, so an engineer read "F-007, interference.static, needs your judgement" and then went
   * looking for F-007 by eye through a whole review's transcript. One listener on the panel,
   * matching `render.js`'s one listener on the transcript, so a rebuilt panel keeps working.
   *
   * Nothing here ranks, filters or reorders: it scrolls to a card that is already on screen.
   */
  function onAttentionClick(event) {
    var target = event.target;
    var row = (target && target.closest) ? target.closest('.attention-row') : null;
    if (!row) {
      return;
    }
    revealFinding(row.getAttribute('data-finding-id'));
  }

  /**
   * Scrolls a finding's headline into view and lights the card up. The fold stays as it was.
   *
   * Until U10 this opened the fold as well, so every ranked row followed left one more finding
   * open at full length and the next click opened another (docs/pane-findings-2026-09-20-
   * review-gui.md section 3). A row leads to a headline; opening it is the engineer's press.
   *
   * A row whose finding is not in the transcript does nothing rather than scrolling somewhere
   * arbitrary: a ranking is read once the session ends and the transcript holds every finding
   * of that session, but a reconnect that missed a `finding` event is exactly the case where
   * the page must not pretend.
   */
  function revealFinding(findingId) {
    var entry = findingId ? state.findings[findingId] : null;
    var card = entry ? entry.card : null;
    if (!card) {
      return;
    }

    card.querySelector('.card-head').scrollIntoView({ block: 'start' });
    flash(card);
  }

  /** Collapse all: every finding back to its headline, every button back to "Details". */
  function collapseFindings() {
    for (var findingId in state.findings) {
      setDetails(state.findings[findingId].card, false);
    }
  }

  /** Lights a card for a moment, then puts its classes back exactly as they were. */
  function flash(card) {
    var settled = card.className.replace(/\s*\bflash\b/g, '');
    card.className = settled + ' flash';
    window.setTimeout(function () {
      card.className = settled;
    }, FLASH_MS);
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

  /**
   * The card's own Details press. An opened fold is brought into view: it can be much taller
   * than what is left of a docked 300 px transcript, and a fold that opened below the viewport
   * reads as a button that did nothing. `nearest` shows a fold that fits whole, and puts the top
   * of one that does not at the top of the transcript (the 2026-09-20 narrow-pane regression).
   */
  function expand(card) {
    var details = card && card.querySelector('.details');
    if (!details) {
      return;
    }
    var open = details.hidden;
    setDetails(card, open);
    if (open) {
      details.scrollIntoView({ block: 'nearest' });
    }
  }

  /**
   * Opens or closes one card's fold and says so on its button. One function, because the
   * button's label and the panel's state are one fact: Collapse all shutting a fold without
   * flipping its label would leave a card reading "Hide details" over a shut one.
   */
  function setDetails(card, open) {
    var details = card.querySelector('.details');
    if (!details) {
      return;
    }
    details.hidden = !open;

    var toggle = card.querySelector('[data-action="expand"]');
    if (toggle) {
      toggle.textContent = open ? 'Hide details' : 'Details';
    }
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
      showDisposition(card, finding && finding.disposition);
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

  function renderNotExamined() {
    var warning = state.notExamined;
    var sentence = warning && warning.sentence ? warning.sentence : '';
    ui.notExamined.textContent = sentence;
    ui.notExamined.hidden = !sentence;
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

  /**
   * The header names the file and its configuration, with the full path in the title: a path
   * clipped at the end of a 300 px strip loses exactly the part that says which model it is.
   */
  function renderDocument() {
    var info = state.documentInfo;
    if (!info) {
      ui.documentName.textContent = 'No document open';
      ui.documentName.removeAttribute('title');
      renderStartReview();
      return;
    }
    ui.documentName.textContent = docs.label(info);
    ui.documentName.setAttribute('title', String(info.path));
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
      state.preparationAvailable = payload.review_preparation === true;
      renderSettings(payload.settings, payload.key_source);
      renderDocument();
      renderBinding();
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
    ui.clearReview = document.getElementById('clear-review');
    ui.staleReview = document.getElementById('stale-review');
    ui.openReport = document.getElementById('open-report');
    ui.openFolder = document.getElementById('open-folder');
    ui.openLog = document.getElementById('open-log');
    ui.runDir = document.getElementById('run-dir');
    ui.streamState = document.getElementById('stream-state');
    ui.usage = document.getElementById('usage-line');
    ui.attention = document.getElementById('attention-panel');
    ui.notExamined = document.getElementById('not-examined');
    ui.preparation = document.getElementById('review-preparation');
    ui.preparationSummary = document.getElementById('preparation-summary');
    ui.preparationInstances = document.getElementById('preparation-instances');
    ui.transcriptToggle = document.getElementById('transcript-toggle');
    ui.collapseFindings = document.getElementById('collapse-findings');
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
      prepareReview(null);
    });
    document.getElementById('preparation-check').addEventListener('click', function () {
      prepareReview(state.preparation ? state.preparation.retryOf : null);
    });
    document.getElementById('preparation-continue').addEventListener('click', function () {
      if (state.preparation) {
        startReview(state.preparation.retryOf, state.preparation.payload.preparation_id);
      }
    });
    document.getElementById('preparation-cancel').addEventListener('click', clearPreparation);
    ui.stop.addEventListener('click', stopTurn);
    ui.clearReview.addEventListener('click', clearReview);
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
    ui.transcriptToggle.addEventListener('click', function () {
      foldTranscript(!state.transcriptFolded);
    });
    ui.collapseFindings.addEventListener('click', collapseFindings);
    ui.attention.addEventListener('click', onAttentionClick);

    // The header states its counts before a single event has arrived, so a pane that has just
    // opened says "0 tool calls" rather than showing a control with no label on it.
    renderTranscriptHead();
    foldTranscript(state.transcriptFolded);

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
