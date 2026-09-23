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

    // What the Transcript's own head says about it: how many calls have finished, and which one
    // is running right now. The rounds are `state.usage.length` and are not counted twice here.
    toolsFinished: 0,
    runningTool: '',

    // Which view owns the pane (feature 009 User Story 5): 'results', on every load, or
    // 'transcript'. One class on the body says which; index.html starts it on Results.
    view: 'results',

    // Whether the last follow-up is still waiting for its `text.done`, which fills its pin.
    followUpPending: false,

    // The follow-ups and their answers pinned in Results, per chat id: `[{question, answer}]`,
    // `answer` null while it is on its way. Page memory only - the answers themselves stay in
    // the transcript and events.jsonl (contracts/views.md section 4).
    pinned: Object.create(null),

    // The kept reviews (feature 009 User Story 6): the host's `sessions` items as last received,
    // in its order; the ones whose run folder answered that it is gone; the reason the review on
    // screen is read-only, or null; whether it was restored from its run folder; the snapshot's
    // last seq, which a replay of its transcript runs up to; the seq a replay in progress stops
    // at, 0 when none runs; whether the Transcript of the chat on screen has been built; and an
    // epoch, so a restore that answers after another was chosen is dropped.
    reviews: [],
    unrestorable: Object.create(null),
    readOnly: null,
    restoredFromFolder: false,
    snapshotLastSeq: 0,
    replayUntil: 0,
    transcriptLoaded: true,
    restoreEpoch: 0,
    notExamined: null,

    // The summary the backend sent beside the last ranking for the chat on screen (feature 009
    // User Story 3), or null: from a backend that sends none, or before the first ranking. Every
    // number and word in it is the backend's; the page prints it and slices it.
    summary: null,

    // The backend's card vocabulary (`GET /labels`, feature 009 User Story 7), read after every
    // `init` that names a backend, or null: an older backend, or before the first read. Handed to
    // the renderers as an argument; null prints the tokens exactly as before (FR-030).
    labels: null,

    // Questions for you (feature 009 User Story 4): what the engineer has typed, chosen and
    // skipped, per chat id - `{answers: {request id: text}, skipped: {request id: true}}` - kept in
    // page memory while the page lives, so choosing another review and coming back keeps them;
    // the question on screen; and the sentence the last send left, if any.
    drafts: Object.create(null),
    questionIndex: 0,
    questionNote: null,
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
        followActiveDocument();
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
          var refusal = backendError(
            (parsed && parsed.error_class) || 'HttpError',
            (parsed && parsed.message) || ('the backend answered ' + response.status),
            !!(parsed && parsed.retryable));
          // The two evidence refusals name the request they are about (feature 009 T042), so
          // the questions panel can say which question without reading the English message.
          if (parsed && typeof parsed.request_id === 'string') {
            refusal.requestId = parsed.request_id;
          }
          throw refusal;
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
    renderResultsState();
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
    renderResultsState();
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
    renderResultsState();
  }

  // ---- the transcript ----------------------------------------------------------------------

  /**
   * One chat event. While a replay runs (a restored review's Transcript, being built from the
   * stream's start), every event up to the snapshot's last seq builds the Transcript only - see
   * `onReplayedEvent` - and the one that reaches it ends the replay.
   */
  function onChatEvent(event) {
    if (state.replayUntil > 0) {
      onReplayedEvent(event);
      if (event.seq >= state.replayUntil) {
        finishReplay();
      }
      return;
    }
    onLiveEvent(event);
  }

  function onLiveEvent(event) {
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
        unansweredFollowUp('failed');
        showError(body);
        return;
      default:
        reportUnreadable('an event of type "' + (event.type || '') + '"');
        return;
    }
  }

  /**
   * An event replayed into the Transcript of a restored review (contracts/sessions.md section
   * 8). Results already hold the snapshot, so nothing here touches them: a finding adds its
   * marker and never a second card, a coverage or disposition event is already in the snapshot,
   * and the turn's and the session's end are lines in the chronology - neither closes the stream
   * nor reads the ranking again. The prose, the tool calls, the evidence records and the usage
   * build the Transcript and its head exactly as live.
   */
  function onReplayedEvent(event) {
    var body = event.body || {};
    switch (event.type) {
      case 'finding':
        appendCard(render.findingMarker(body));
        return;
      case 'coverage':
      case 'disposition':
        return;
      case 'turn.ended':
        state.textBlock = null;
        state.runningTool = '';
        renderTranscriptHead();
        if (body.reason && body.reason !== 'end') {
          appendCard(render.textBlock('system', 'The turn ended: ' + body.reason + '.'));
        }
        return;
      case 'session.ended':
        state.textBlock = null;
        appendCard(render.textBlock('system', 'The session ended at ' + (body.ended_at || 'now') + '.'));
        return;
      case 'error':
        appendCard(errorLine(body));
        return;
      default:
        onLiveEvent(event);
        return;
    }
  }

  /**
   * The replay has reached the snapshot's last seq: the Transcript is scrolled to its end once,
   * and - the chat having ended - the stream is given up. A running chat would keep it: from
   * here on the stream behaves as live.
   */
  function finishReplay() {
    state.replayUntil = 0;
    scrollToEnd();
    if (!state.turnRunning) {
      closeStream();
      showStreamState('');
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

  /**
   * Appends one record to the Transcript and keeps the Transcript at its end. The one scroll on
   * the page that follows new content, and it is the Transcript's alone: Results never moves
   * under the reader (contracts/views.md section 5).
   */
  function appendCard(node) {
    ui.transcript.appendChild(node);
    scrollToEnd();
    return node;
  }

  /** To the Transcript's end - except while a replay runs, which scrolls once, when it ends. */
  function scrollToEnd() {
    if (state.replayUntil > 0) {
      return;
    }
    ui.transcript.scrollTop = ui.transcript.scrollHeight;
  }

  /**
   * A failure, in both views (contracts/views.md section 5): the card in Results, where the
   * engineer acts on it, and one line in the Transcript naming its class and its message, where
   * the chronology keeps it. Every error the page shows comes through here - an `error` event, a
   * refused start or preparation, a refused follow-up or Stop.
   */
  function showError(error) {
    var body = error || {};
    ui.errors.appendChild(render.errorCard(body, state.labels));
    appendCard(errorLine(body));
  }

  /** The Transcript's line for an error: its class and its message - transcript vocabulary. */
  function errorLine(body) {
    return render.textBlock('error', String(body.error_class || 'Error') + ': ' + String(body.message || ''));
  }

  /**
   * An error into a status line (feature 009 FR-026): the backend's sentence for its class with
   * the class and the message in a fold, through `render.plainError` - or, with no labels (an
   * older backend), `legacy`, the words that line always printed (FR-030).
   */
  function errorInto(node, error, legacy) {
    render.clear(node);
    if (state.labels) {
      node.appendChild(render.plainError(errorBody(error), state.labels));
      return;
    }
    render.write(node, legacy);
  }

  /** A card's own refusal (a decision, Show, the log), on its status line and in the card's hue. */
  function cardError(card, error, legacy) {
    var status = card ? card.querySelector('.card-status') : null;
    if (!status) {
      return;
    }
    status.className = 'card-status bad';
    errorInto(status, error, legacy);
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
      answerFollowUp(text || '');
    }
  }

  // ---- follow-ups pinned in Results (FR-019) --------------------------------------------------

  /** This chat's pins, made on first use. */
  function pinsOf(chatId) {
    var key = String(chatId || '');
    if (!state.pinned[key]) {
      state.pinned[key] = [];
    }
    return state.pinned[key];
  }

  /**
   * The pinned answers of the chat on screen, rebuilt from page memory - so a chat shown again
   * shows its pins again (contracts/views.md section 4).
   */
  function renderAnswers() {
    render.clear(ui.answers);
    var pins = state.chatId ? pinsOf(state.chatId) : [];
    for (var index = 0; index < pins.length; index++) {
      ui.answers.appendChild(render.pinnedAnswer(pins[index]));
    }
  }

  /**
   * The answer to the follow-up that is waiting: into its pin, which is then brought into view
   * inside Results. The view is not changed - the answer comes to the engineer, not the other
   * way round.
   */
  function answerFollowUp(text) {
    state.followUpPending = false;
    var pins = pinsOf(state.chatId);
    if (!pins.length) {
      return;
    }
    pins[pins.length - 1].answer = text;
    renderAnswers();
    var last = ui.answers.lastChild;
    if (last) {
      last.scrollIntoView({ block: 'nearest' });
    }
  }

  /** A follow-up turn that ended without a `text.done` says so in its pin, and why. */
  function unansweredFollowUp(reason) {
    if (state.followUpPending) {
      answerFollowUp('No answer: the turn ended (' + reason + ').');
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

  /**
   * A finding: its card into Results' list (feature 009 User Story 5), and a one-line marker
   * into the Transcript where it was recorded. Results is not scrolled: a card arriving never
   * moves what the engineer is reading.
   */
  function showFinding(body) {
    placeFinding(body);
    appendCard(render.findingMarker(body));
  }

  /**
   * A finding's card into Results' list, replacing the card of the same id in place - the half
   * of `showFinding` a restore shares, since a restored review's Transcript is built only when it
   * is chosen (contracts/sessions.md section 8).
   */
  function placeFinding(body) {
    var existing = state.findings[body.id];
    var card = render.findingCard(body, state.labels);
    if (existing) {
      // A re-run replaces its verdict rather than showing two (data-model, resume semantics).
      existing.card.parentNode.replaceChild(card, existing.card);
    } else {
      ui.findings.appendChild(card);
      ui.findingsHead.hidden = false;
    }
    state.findings[body.id] = { body: body, card: card };
  }

  function showEvidence(body) {
    var card = appendCard(render.evidenceCard(body, state.labels));
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
    }, state.labels);
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
    ui.coverage.appendChild(render.coverageSummary(state.coverage, state.labels));
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

  // ---- the Transcript's head, and the two views ----------------------------------------------

  /**
   * What the Transcript's head says about it: how many tool calls have finished, how many model
   * round trips there have been, and - while one is in flight - which tool is running.
   *
   * "A hung review looks exactly like a finished one" is the complaint this page already has on
   * record (docs/pane-findings-2026-09-18.md), and these counts are the answer to it. They are
   * transcript vocabulary, so they live in the Transcript's head and nowhere in Results (FR-018).
   */
  function renderTranscriptHead() {
    var tools = state.toolsFinished;
    var rounds = state.usage.length;

    var counted = tools + ' tool call' + (tools === 1 ? '' : 's')
      + DOT + rounds + ' round' + (rounds === 1 ? '' : 's');
    if (state.runningTool) {
      counted += DOT + state.runningTool;
    }

    ui.transcriptCounts.textContent = counted;
  }

  /**
   * Results or Transcript (contracts/views.md section 1): one class on the body, `aria-pressed`
   * on the chosen button, and the other view not displayed. Choosing the Transcript brings it to
   * its end, where its newest record is.
   */
  function setView(view) {
    state.view = view === 'transcript' ? 'transcript' : 'results';
    var transcript = state.view === 'transcript';
    document.body.classList.toggle('view-transcript', transcript);
    document.body.classList.toggle('view-results', !transcript);
    ui.viewTranscript.setAttribute('aria-pressed', transcript ? 'true' : 'false');
    ui.viewResults.setAttribute('aria-pressed', transcript ? 'false' : 'true');
    if (!transcript) {
      return;
    }
    // A review restored from its live chat has no Transcript until it is asked for; then it is
    // replayed from the stream (contracts/sessions.md section 8).
    if (!state.transcriptLoaded && state.chatId && !state.restoredFromFolder && !state.turnRunning) {
      replayTranscript();
    }
    scrollToEnd();
  }

  /**
   * Where the review stands, in one line of page words at the top of Results (contracts/views.md
   * section 3), read from page state alone: reconnecting, running, waiting for the engineer's
   * answers, or finished - and nothing at all when no chat is shown.
   */
  function renderResultsState() {
    if (!ui.resultsState) {
      return;
    }
    var questions = state.summary ? state.summary.questions : null;
    var sentence = '';
    if (!state.chatId) {
      sentence = '';
    } else if (state.reconnectTimer !== null) {
      sentence = 'Reconnecting to the review.';
    } else if (state.turnRunning) {
      sentence = 'The review is running.';
    } else if (questions && questions.count > 0) {
      sentence = 'Waiting for your answers.';
    } else {
      sentence = 'The review has finished.';
    }
    ui.resultsState.textContent = sentence;
    ui.resultsState.hidden = !sentence;
  }

  function endTurn(body) {
    setTurnRunning(false);
    state.textBlock = null;
    state.runningTool = '';
    renderTranscriptHead();
    unansweredFollowUp(body.reason || 'ended');
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
        applyRanking(ranking);
      },
      function () {
        // Nothing new: the panel stays as it is, which for a review that has just ended is
        // hidden.
      });
  }

  /**
   * A ranking and its summary into Results: Start here, the explanations, the summary, the
   * questions, the modelling-practice group, the contacts and the status line. One path for the
   * end of a live turn and for a restored review (contracts/sessions.md section 5), so the two
   * cannot render the same review differently.
   */
  function applyRanking(ranking) {
    render.clear(ui.attention);
    ui.attention.appendChild(render.attentionPanel(ranking, state.labels));
    syncFindingExplanations(ranking);
    ui.attention.hidden = false;

    state.summary = ranking.summary || null;
    renderSummary();
    renderQuestions();
    groupModellingPractice(state.summary && state.summary.modelling_practice);
    renderContacts();
    renderResultsState();
    syncReadOnlyControls();
  }

  /**
   * The summary block, rebuilt whole from `state.summary` (contracts/review-summary.md section
   * 5). Rebuilt rather than appended to, like Start here, so a second ranking - the end of a
   * follow-up turn - replaces the block. No summary, no block: a backend that sends none leaves
   * the section hidden and empty (FR-030).
   */
  function renderSummary() {
    render.clear(ui.summary);
    if (state.summary) {
      ui.summary.appendChild(render.summaryBlock(state.summary));
    }
    ui.summary.hidden = !state.summary;
  }

  /**
   * The modelling-practice findings as one collapsed group (FR-010, contracts/review-summary.md
   * section 5): the cards the summary names move, in the order they arrived, into one shut fold
   * placed where the first of them was.
   *
   * Which cards is the backend's answer (`modelling_practice.finding_ids`, from feature 008's
   * family row), read as a set; their order is the order they already stand in, which is the
   * order they arrived. Nothing here decides membership or order. Any group a previous ranking
   * made is taken apart first, so the end of a follow-up turn regroups rather than nesting or
   * duplicating a card - and a ranking with no family leaves every card where it arrived.
   */
  function groupModellingPractice(practice) {
    ungroupFindings();
    var ids = (practice && practice.finding_ids) || [];
    if (!ids.length) {
      return;
    }

    var named = Object.create(null);
    for (var index = 0; index < ids.length; index++) {
      named[String(ids[index])] = true;
    }

    var members = [];
    var cards = ui.findings.querySelectorAll('.card.finding');
    for (var card = 0; card < cards.length; card++) {
      if (named[cards[card].getAttribute('data-finding-id')] === true) {
        members.push(cards[card]);
      }
    }
    if (!members.length) {
      return;
    }

    var group = render.findingGroup(practice.title);
    members[0].parentNode.insertBefore(group, members[0]);
    var body = group.querySelector('.finding-group-body');
    for (var member = 0; member < members.length; member++) {
      body.appendChild(members[member]);
    }
  }

  /**
   * The size-for-size contacts, one shut fold after the findings (FR-011), from the summary's
   * `contacts`: rebuilt whole with the summary, and nothing at all when there are none - every
   * review before feature 010 records them.
   */
  function renderContacts() {
    var contacts = state.summary ? state.summary.contacts : null;
    render.clear(ui.contacts);
    if (contacts) {
      ui.contacts.appendChild(render.contactList(contacts));
    }
    ui.contacts.hidden = !contacts;
  }

  /** Every group back to loose cards, in their order, where the group stood. */
  function ungroupFindings() {
    var groups = ui.findings.querySelectorAll('.finding-group');
    for (var index = 0; index < groups.length; index++) {
      var group = groups[index];
      var cards = group.querySelectorAll('.card.finding');
      for (var card = 0; card < cards.length; card++) {
        group.parentNode.insertBefore(cards[card], group);
      }
      group.parentNode.removeChild(group);
    }
  }

  // ---- the backend's words (feature 009 User Story 7) --------------------------------------

  /**
   * `GET /labels`: the status, severity, bucket, evidence and error words the cards print
   * (contracts/plain-words.md section 1). Read after every `init` that names a backend - a
   * settings save restarts the backend and re-inits the page - and kept only when the answer is
   * an object; anything else, a 404 from an older backend included, leaves the page on its raw
   * tokens (FR-030).
   */
  function loadLabels() {
    call('/labels', 'GET').then(function (labels) {
      state.labels = (labels && typeof labels === 'object') ? labels : null;
    }, function () {
      state.labels = null;
    });
  }

  // ---- kept reviews (feature 009 User Story 6) ---------------------------------------------

  /**
   * Asks the host for the reviews it kept (`sessions.list`) and redraws the chips. After `init`
   * the document rule runs once the list is in, so a reloaded page shows the open document's
   * review. A host that does not know the row answers an error, and the page simply has no chips.
   */
  function requestSessions(thenFollow) {
    send('sessions.list', {}).then(function (payload) {
      applySessions(payload);
      if (thenFollow) {
        followActiveDocument();
      }
    }).catch(function () {
      // An older host: no kept reviews to offer, and nothing else changes.
    });
  }

  function applySessions(payload) {
    state.reviews = (payload && payload.items) || [];
    renderChips();
  }

  /** The chips, one per kept review in the host's order, the review on screen marked. */
  function renderChips() {
    var chips = [];
    for (var index = 0; index < state.reviews.length; index++) {
      var item = state.reviews[index] || {};
      var chatId = String(item.chat_id || '');
      chips.push({
        chat_id: chatId,
        label: chipLabel(item),
        current: chatId === state.chatId,
        gone: state.unrestorable[chatId] === true
      });
    }
    render.clear(ui.chips);
    if (chips.length) {
      ui.chips.appendChild(render.reviewChips(chips));
    }
    ui.chips.hidden = !chips.length;
  }

  /** "bracket.sldasm [Default] 10:15": the file and configuration, then the page's own clock. */
  function chipLabel(item) {
    var label = docs.label(reviewDocument(item)) || String(item.run_id || '');
    var clock = clockOf(item.started_at);
    return clock ? label + ' ' + clock : label;
  }

  function clockOf(startedAt) {
    var when = startedAt ? new Date(String(startedAt)) : null;
    if (!when || isNaN(when.getTime())) {
      return '';
    }
    return twoDigits(when.getHours()) + ':' + twoDigits(when.getMinutes());
  }

  function twoDigits(value) {
    return (value < 10 ? '0' : '') + value;
  }

  /** A kept review's document, in the shape `web/shared/document.js` compares. */
  function reviewDocument(item) {
    return item && item.path ? { path: item.path, configuration: item.configuration } : null;
  }

  function keptReview(chatId) {
    for (var index = 0; index < state.reviews.length; index++) {
      if (String((state.reviews[index] || {}).chat_id) === chatId) {
        return state.reviews[index];
      }
    }
    return null;
  }

  /**
   * Returning to a document shows its newest kept review (contracts/sessions.md section 6): when
   * no turn runs and no start is in flight, the review on screen is not of the active document,
   * and the host kept one that is, the last such in the host's order is shown. Otherwise the
   * landed binding stands - a review of another document hides behind the stale line, with Stop
   * still live while a turn runs. "Newest" is the last match in the supplied order: a scan, not
   * a sort.
   */
  function followActiveDocument() {
    if (state.turnRunning || state.startPending) {
      return;
    }
    if (state.chatId && docs.same(state.reviewed, state.documentInfo)) {
      return;
    }

    var newest = null;
    for (var index = 0; index < state.reviews.length; index++) {
      var item = state.reviews[index] || {};
      if (docs.same(reviewDocument(item), state.documentInfo) && state.unrestorable[String(item.chat_id)] !== true) {
        newest = item;
      }
    }
    if (newest) {
      showReview(String(newest.chat_id));
    }
  }

  /**
   * Brings a kept review back (contracts/sessions.md section 5), refused while a turn runs or a
   * start is in flight. The drafts and pins of the review on screen stay in page memory; Results
   * and the Transcript are cleared; the chat, its folder and its document are set from the host's
   * item; then one `GET /sessions/{chat}/snapshot` - or, when the backend no longer holds the
   * chat, `GET /reviews/{run_id}` from its run folder, read-only. No `POST` and no `review.start`:
   * returning costs no token (SC-005). A run folder that is gone too marks the chip, and the pane
   * shows no review.
   */
  function showReview(chatId) {
    if (state.turnRunning || state.startPending) {
      return;
    }
    var item = keptReview(chatId);
    if (!item) {
      return;
    }

    closeStream();
    resetTranscript();
    state.chatId = chatId;
    state.runDir = item.run_dir || null;
    state.reviewed = reviewDocument(item);
    state.lastSeq = 0;
    state.transcriptLoaded = false;
    state.restoreEpoch++;
    var epoch = state.restoreEpoch;
    showStreamState('');
    renderSession();
    renderBinding();
    renderAnswers();
    renderChips();

    call(sessionPath('/snapshot'), 'GET').then(function (snapshot) {
      if (epoch === state.restoreEpoch) {
        restore(snapshot, false);
      }
    }, function (error) {
      if (epoch !== state.restoreEpoch) {
        return;
      }
      if (error.errorClass !== 'UnknownChat') {
        showError(errorBody(error));
        return;
      }
      call('/reviews/' + encodeURIComponent(String(item.run_id || '')), 'GET').then(function (snapshot) {
        if (epoch === state.restoreEpoch) {
          restore(snapshot, true);
        }
      }, function (failure) {
        if (epoch !== state.restoreEpoch) {
          return;
        }
        if (failure.errorClass === 'UnknownReview') {
          cannotRestore(chatId);
          return;
        }
        showError(errorBody(failure));
      });
    });
  }

  /**
   * A snapshot into the pane: Results through the same functions a live turn's end uses, the
   * read-only state and its reason, and - for a chat still running, which is a page reloaded
   * mid-turn - the turn and the stream, reopened from the snapshot's last seq.
   */
  function restore(snapshot, fromFolder) {
    var body = snapshot || {};
    state.restoredFromFolder = fromFolder;
    state.readOnly = body.read_only ? String(body.read_only_reason || '') : null;
    state.snapshotLastSeq = typeof body.last_seq === 'number' ? body.last_seq : 0;
    renderResults(body);
    renderReadOnly();

    if (fromFolder) {
      state.transcriptLoaded = true;
      appendCard(render.restoredTranscript());
    } else if (body.chat_state === 'running') {
      state.transcriptLoaded = true;
      state.lastSeq = state.snapshotLastSeq;
      setTurnRunning(true);
      openStream();
    }
    renderStartReview();
    renderResultsState();
  }

  /**
   * One snapshot's results: every finding's card in session order (dispositions included), the
   * coverage fold, the not-loaded warning, and the ranking with its summary - `placeFinding`,
   * `renderCoverage`, `renderNotExamined` and `applyRanking`, the functions the live review
   * renders through.
   */
  function renderResults(snapshot) {
    var findings = snapshot.findings || [];
    for (var index = 0; index < findings.length; index++) {
      placeFinding(findings[index] || {});
    }
    state.coverage = (snapshot.coverage || []).slice();
    if (state.coverage.length) {
      renderCoverage();
    }
    state.notExamined = snapshot.not_examined || null;
    renderNotExamined();
    if (snapshot.ranking) {
      applyRanking(snapshot.ranking);
    }
    syncReadOnlyControls();
  }

  /** The reason a restored review is read-only, under the status line, while it is (FR-021). */
  function renderReadOnly() {
    ui.readOnly.textContent = state.readOnly === null ? '' : state.readOnly;
    ui.readOnly.hidden = state.readOnly === null;
    syncReadOnlyControls();
  }

  /**
   * Every disposition control of a read-only review is off, and the note boxes with them; Show
   * in SOLIDWORKS, Open report and Open run folder stay on, because the host still holds the
   * review's record (contracts/sessions.md section 5).
   */
  function syncReadOnlyControls() {
    var locked = state.readOnly !== null;
    var controls = ui.findings.querySelectorAll(
      '[data-action="accept"], [data-action="reject"], [data-action="defer"], .card-tools input.note');
    for (var index = 0; index < controls.length; index++) {
      controls[index].disabled = locked;
    }
    syncQuestionControls();
  }

  /** Neither the chat nor its run folder can bring the review back: the chip says so, and the pane shows none. */
  function cannotRestore(chatId) {
    state.unrestorable[chatId] = true;
    resetTranscript();
    state.chatId = null;
    state.runDir = null;
    state.reviewed = null;
    renderBinding();
    renderChips();
  }

  /** Remove on a chip that cannot be restored: the host forgets the record and answers the list. */
  function forgetReview(chatId) {
    send('session.forget', { chat_id: chatId }).then(function (payload) {
      delete state.unrestorable[chatId];
      applySessions(payload);
    }).catch(function (error) {
      showBanner(error.message);
    });
  }

  function onChipClick(event) {
    var target = event.target;
    var action = (target && target.getAttribute) ? target.getAttribute('data-action') : null;
    var chatId = target && target.getAttribute ? String(target.getAttribute('data-chat-id') || '') : '';
    if (action === 'review-chip' && chatId && chatId !== state.chatId) {
      showReview(chatId);
    } else if (action === 'review-forget' && chatId) {
      forgetReview(chatId);
    }
  }

  /**
   * The Transcript of a review restored from its live chat, built on demand: the stream is read
   * from its start, in replay mode, up to the snapshot's last seq (contracts/sessions.md section
   * 8). A snapshot with nothing on its stream has nothing to replay.
   */
  function replayTranscript() {
    state.transcriptLoaded = true;
    if (!(state.snapshotLastSeq > 0)) {
      return;
    }
    state.replayUntil = state.snapshotLastSeq;
    state.lastSeq = 0;
    openStream();
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
    var previous = ui.findings.querySelectorAll('.finding-explanation');
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
        showError(errorBody(error));
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
      renderAnswers();
      setTurnRunning(true);
      openStream();
      // The host has just kept this review: ask for the list again, so its chip appears.
      requestSessions(false);
    }).catch(function (error) {
      showError(errorBody(error));
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
      || !state.chatId || state.resultsStale || state.readOnly !== null;
    ui.followupText.disabled = followupDisabled;
    ui.followupSend.disabled = followupDisabled;
    ui.clearReview.disabled = !canClearReview();
    syncQuestionControls();
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
    renderResultsState();
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
    render.clear(ui.findings);
    ui.findingsHead.hidden = true;
    render.clear(ui.errors);
    render.clear(ui.answers);
    render.clear(ui.coverage);
    ui.coverage.hidden = true;
    render.clear(ui.attention);
    ui.attention.hidden = true;
    state.summary = null;
    state.questionIndex = 0;
    state.questionNote = null;
    state.readOnly = null;
    state.restoredFromFolder = false;
    state.snapshotLastSeq = 0;
    state.replayUntil = 0;
    state.transcriptLoaded = true;
    state.restoreEpoch++;
    renderReadOnly();
    renderSummary();
    renderQuestions();
    renderContacts();
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
    renderResultsState();
  }

  /**
   * A follow-up: pinned in Results at once, waiting for its answer, and written into the
   * Transcript as the engineer's prose (FR-019, contracts/views.md section 4). The view is left
   * alone - until feature 009 this unfolded the whole transcript so the answer would not be
   * hidden behind tool chrome; the pin is where the answer lands now.
   */
  function sendFollowUp() {
    var text = ui.followupText.value.trim();
    if (!text || !state.chatId || state.turnRunning || state.startPending || state.preparation
        || state.resultsStale || state.readOnly !== null) {
      return;
    }

    state.followUpPending = true;
    pinsOf(state.chatId).push({ question: text, answer: null });
    renderAnswers();
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
      unansweredFollowUp('refused');
      showError(errorBody(error));
    });
  }

  /** The `{error_class, message, retryable}` an error card is built from, for an error the page caught. */
  function errorBody(error) {
    return { error_class: error.errorClass, message: error.message, retryable: error.retryable };
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
      showError(errorBody(error));
    });
  }

  // ---- card actions ---------------------------------------------------------------------------

  /**
   * One listener for every card in Results - the finding cards and the error cards. `render.js`
   * declares what a button does with `data-action` and this decides what that means, so no card
   * carries a handler of its own and a card rebuilt after an update keeps working. (Until feature
   * 009 the cards lived in the transcript and this listened there; the Transcript's records carry
   * no button now.)
   */
  function onCardClick(event) {
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
      case 'retry':
        prepareReview(state.chatId);
        return;
      case 'settings':
        ui.settings.hidden = false;
        ui.settings.scrollIntoView();
        return;
      case 'log':
        send('log.open', {}).catch(function (error) {
          cardError(card, error, error.message);
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
   * A Start-here card and a one-line row behind "Show all" are both a finding id to follow
   * (U12); the "Show all" control itself carries none, and folds natively.
   *
   * Nothing here ranks, filters or reorders: it scrolls to a card that is already on screen.
   */
  function onAttentionClick(event) {
    var target = event.target;
    var row = (target && target.closest) ? target.closest('[data-finding-id]') : null;
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

    // A card inside the modelling-practice group is behind that group's fold: open it first,
    // or the scroll lands on a card with no box (FR-010).
    var group = card.closest('.finding-group');
    if (group) {
      group.open = true;
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

    // The chat on screen, so the host looks the ids up in this review's package rather than in
    // whichever run is the pane's latest (feature 009 FR-023). An id, never a path.
    request.chat_id = state.chatId;
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
      cardError(card, error, error.message);
    });
  }

  function decide(card, decision) {
    var findingId = card ? card.getAttribute('data-finding-id') : null;
    if (!findingId || !state.chatId || state.readOnly !== null) {
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
      cardError(card, error, error.errorClass + ': ' + error.message);
    });
  }

  // ---- questions for you (feature 009 User Story 4) -------------------------------------------

  /**
   * The questions panel, rebuilt from the summary's open questions and this chat's draft
   * (contracts/questions.md section 4). Shown when the summary counts at least one open
   * question; hidden - and empty - otherwise, including for a backend that sends no summary.
   */
  function renderQuestions() {
    var items = currentQuestions();
    var questions = state.summary ? state.summary.questions : null;
    render.clear(ui.questions);
    if (!questions || !(questions.count > 0) || !items.length) {
      ui.questions.hidden = true;
      return;
    }

    state.questionIndex = Math.max(0, Math.min(state.questionIndex, items.length - 1));
    ui.questions.appendChild(render.questionsPanel(
      questions,
      draftOf(state.chatId),
      state.questionIndex,
      { resumeText: state.summary.resume_text, note: state.questionNote, labels: state.labels }));
    ui.questions.hidden = false;
    syncQuestionControls();
  }

  /** The open questions in the backend's order: the summary's list, never a filter of our own. */
  function currentQuestions() {
    var questions = state.summary ? state.summary.questions : null;
    return (questions && questions.items) || [];
  }

  /** This chat's draft, made on first use: what was typed or chosen, and what was skipped. */
  function draftOf(chatId) {
    var key = String(chatId || '');
    if (!state.drafts[key]) {
      state.drafts[key] = { answers: Object.create(null), skipped: Object.create(null) };
    }
    return state.drafts[key];
  }

  /**
   * The answers one Send carries: every question with a non-blank answer that was not skipped,
   * in the order the summary supplied them, trimmed. A skipped or unanswered question is absent,
   * so nothing is ever filled in for it (FR-015).
   */
  function answersToSend() {
    var items = currentQuestions();
    var draft = draftOf(state.chatId);
    var answers = [];
    for (var index = 0; index < items.length; index++) {
      var id = String((items[index] || {}).id || '');
      var text = draft.answers[id];
      if (typeof text === 'string' && text.trim() && draft.skipped[id] !== true) {
        answers.push({ request_id: id, answer: text.trim() });
      }
    }
    return answers;
  }

  /** The panel is locked while a turn runs or a start is in flight, and for a hidden or read-only review. */
  function questionsLocked() {
    return state.turnRunning || state.startPending || state.resultsStale || !state.chatId
      || state.readOnly !== null;
  }

  /**
   * Which of the panel's controls may be pressed, set on the panel as it stands rather than by
   * rebuilding it, so a turn starting or ending never takes the text box out from under the
   * engineer's cursor.
   */
  function syncQuestionControls() {
    if (!ui.questions) {
      return;
    }
    var locked = questionsLocked();
    var controls = ui.questions.querySelectorAll('button, input');
    for (var index = 0; index < controls.length; index++) {
      controls[index].disabled = locked;
    }
    if (locked) {
      return;
    }

    var last = currentQuestions().length - 1;
    setActionDisabled('question-previous', state.questionIndex <= 0);
    setActionDisabled('question-next', state.questionIndex >= last);
    setActionDisabled('question-send', !answersToSend().length);
  }

  function setActionDisabled(action, disabled) {
    var control = ui.questions.querySelector('[data-action="' + action + '"]');
    if (control) {
      control.disabled = disabled;
    }
  }

  /** One listener for the panel, reading what each button declares (`render.questionsPanel`). */
  function onQuestionsClick(event) {
    var target = event.target;
    var action = (target && target.getAttribute) ? target.getAttribute('data-action') : null;
    if (!action || target.disabled || questionsLocked()) {
      return;
    }

    var items = currentQuestions();
    var item = items[state.questionIndex] || {};
    var id = String(item.id || '');
    var draft = draftOf(state.chatId);

    switch (action) {
      case 'question-previous':
        state.questionIndex -= 1;
        renderQuestions();
        return;
      case 'question-next':
        state.questionIndex += 1;
        renderQuestions();
        return;
      case 'question-option':
        // The answer is the offered text verbatim; one option at a time.
        draft.answers[id] = String((item.options || [])[parseInt(target.getAttribute('data-option-index'), 10)]);
        delete draft.skipped[id];
        renderQuestions();
        return;
      case 'question-skip':
        // Skipped stays open and unresolved in the backend: nothing is sent for it, and
        // nothing is filled in (FR-015).
        delete draft.answers[id];
        draft.skipped[id] = true;
        if (state.questionIndex < items.length - 1) {
          state.questionIndex += 1;
        }
        renderQuestions();
        return;
      case 'question-send':
        sendAnswers();
        return;
      default:
        return;
    }
  }

  /** Typing into a free-text answer: the draft follows the box, and a typed answer un-skips. */
  function onQuestionsInput(event) {
    var box = event.target;
    if (!box || !box.classList || !box.classList.contains('question-answer')) {
      return;
    }
    var id = String(box.getAttribute('data-request-id') || '');
    var draft = draftOf(state.chatId);
    draft.answers[id] = box.value;
    if (box.value.trim() && draft.skipped[id] === true) {
      delete draft.skipped[id];
      var note = ui.questions.querySelector('.question-skipped');
      if (note) {
        note.parentNode.removeChild(note);
      }
    }
    syncQuestionControls();
  }

  /**
   * Send answers: one `POST /sessions/{chat_id}/evidence` carrying every answered question
   * (feature 008's batch route, contracts/questions.md section 4), which records them and
   * resumes the review once. The turn runs and the stream reopens as a follow-up's does.
   *
   * A refusal records nothing - the batch is validated whole before anything is written - so
   * the drafts stay. When it names the request it is about (`request_id`, on the two evidence
   * refusals), the pane says which question by its number and its words and reads the summary
   * again, because that question is no longer open.
   */
  function sendAnswers() {
    var answers = answersToSend();
    if (!answers.length || questionsLocked()) {
      return;
    }

    var chatId = state.chatId;
    var items = currentQuestions();
    state.questionNote = { text: 'Sending your answers...', bad: false };
    setTurnRunning(true);
    renderQuestions();

    call(sessionPath('/evidence'), 'POST', { answers: answers }).then(function () {
      var draft = draftOf(chatId);
      for (var index = 0; index < answers.length; index++) {
        delete draft.answers[answers[index].request_id];
      }
      if (state.chatId !== chatId) {
        return;
      }
      state.questionNote = null;
      renderQuestions();
      if (!state.stream) {
        openStream();
      }
    }).catch(function (error) {
      setTurnRunning(false);
      if (state.chatId !== chatId) {
        return;
      }
      var answered = questionNumbered(items, error.requestId);
      if (answered) {
        delete draftOf(chatId).answers[error.requestId];
        state.questionNote = {
          text: 'Question ' + answered.number + ' (' + answered.question + ') was answered elsewhere, so nothing was sent.',
          bad: true
        };
        renderQuestions();
        loadAttention();
        return;
      }
      // Any other refusal: the backend's sentence for its class, the class and the message in a
      // fold (feature 009 FR-026) - or, with no labels, its message as before.
      state.questionNote = state.labels ? { error: errorBody(error) } : { text: error.message, bad: true };
      renderQuestions();
    });
  }

  /** The question a refusal names, with its number on screen, or null when it names none. */
  function questionNumbered(items, requestId) {
    if (typeof requestId !== 'string') {
      return null;
    }
    for (var index = 0; index < items.length; index++) {
      var item = items[index] || {};
      if (String(item.id) === requestId) {
        return { number: index + 1, question: item.question };
      }
    }
    return null;
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

  /**
   * The not-loaded warning. The backend's names-only headline when it sent one, with the
   * instances' ids in a fold beneath it (feature 009 FR-012); the sentence otherwise, exactly as
   * every backend before this feature had it printed (FR-030).
   */
  function renderNotExamined() {
    var warning = state.notExamined;
    var headline = warning && warning.headline ? warning.headline : '';
    var sentence = warning && warning.sentence ? warning.sentence : '';
    render.clear(ui.notExamined);
    if (headline) {
      ui.notExamined.appendChild(render.notExaminedHeadline(warning));
    } else {
      render.write(ui.notExamined, sentence);
    }
    ui.notExamined.hidden = !(headline || sentence);
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
      errorInto(ui.saveState, error, error.errorClass === 'TurnRunning'
        ? error.message
        : (error.errorClass + ': ' + error.message));
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
      if (state.backend) {
        loadLabels();
      }
      // The reviews the host kept for this SOLIDWORKS session, and - a page reloaded with one of
      // them open - that review shown again (contracts/sessions.md sections 5 and 6).
      requestSessions(true);
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
    ui.summary = document.getElementById('summary');
    ui.questions = document.getElementById('questions');
    ui.contacts = document.getElementById('contacts');
    ui.notExamined = document.getElementById('not-examined');
    ui.preparation = document.getElementById('review-preparation');
    ui.preparationSummary = document.getElementById('preparation-summary');
    ui.preparationInstances = document.getElementById('preparation-instances');
    ui.chips = document.getElementById('review-chips');
    ui.readOnly = document.getElementById('read-only');
    ui.viewResults = document.getElementById('view-results');
    ui.viewTranscript = document.getElementById('view-transcript');
    ui.results = document.getElementById('results');
    ui.resultsState = document.getElementById('results-state');
    ui.findingsHead = document.getElementById('findings-head');
    ui.findings = document.getElementById('findings');
    ui.errors = document.getElementById('errors');
    ui.answers = document.getElementById('answers');
    ui.transcriptCounts = document.getElementById('transcript-counts');
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
    ui.results.addEventListener('click', onCardClick);
    ui.chips.addEventListener('click', onChipClick);
    ui.transcript.addEventListener('click', function (event) {
      // The one button a Transcript holds: Open run folder, on a review restored from its folder.
      var target = event.target;
      if (target && target.getAttribute && target.getAttribute('data-action') === 'open-folder') {
        ui.openFolder.click();
      }
    });
    ui.viewResults.addEventListener('click', function () {
      setView('results');
    });
    ui.viewTranscript.addEventListener('click', function () {
      setView('transcript');
    });
    ui.collapseFindings.addEventListener('click', collapseFindings);
    ui.attention.addEventListener('click', onAttentionClick);
    ui.questions.addEventListener('click', onQuestionsClick);
    ui.questions.addEventListener('input', onQuestionsInput);

    // The head states its counts before a single event has arrived, so a pane that has just
    // opened says "0 tool calls" rather than a head with nothing in it.
    renderTranscriptHead();
    setView(state.view);

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
