/*
  The Terminal page's script (T060): the CLI dropdown, Start/Stop, the install-steps view, and
  the pseudo-console's bytes in both directions.

  Five rules hold everywhere in this file.

  1. Markup is never assigned and no handler is inline. Every string that reaches the DOM goes
     through `textContent`, because a CLI's failure text, an install message and a path are all
     written by something other than this page (FR-029, contracts/pane-host-messages.md). The
     bytes the CLI draws never reach the DOM as markup at all: they go to xterm.js, which parses
     VT, not HTML.
  2. Every host message is `{type, id, payload}` and replies echo `id`. Two ways of sending one:
     `request` keeps the id and waits for the reply, `send` posts and forgets. Keystrokes and
     resizes go through `send` - the contract names no reply for them, and a page that waited for
     one would leak a pending entry per keypress.
  3. Output is bytes, not text. `terminal.output` carries base64 and it is decoded into a
     `Uint8Array` before it is written, never into a string: a UTF-8 sequence split across two
     chunks becomes two replacement characters the moment it is decoded as text, and a CLI's box
     drawing is nothing but multi-byte sequences.
  4. This page holds no credential of any kind. It never talks to the backend; the CLI's
     restriction profile and everything it needs travel in the child's environment block, which is
     the host's business and never the renderer's (FR-015).
  5. Nothing about a CLI is decided here. Whether one can be started, what version it is and what
     to do about it are the host's answers, carried in `init`; this page turns them into a
     sentence. A page that decided for itself would disagree with the host about which CLI the
     Start button starts.
*/

(function () {
  'use strict';

  var bridge = (window.chrome && window.chrome.webview) ? window.chrome.webview : null;

  /**
   * How the host's CLI statuses read on screen. `ready` has nothing to add - the dropdown says
   * the CLI's name and version and that is the whole story - and an unknown status falls through
   * to the host's own message rather than being invented here.
   */
  var STATUS_TEXT = {
    ready: null,
    deferred: 'deferred in this version',
    not_installed: 'not installed',
    unsupported: 'cannot be started',
    too_old: 'too old',
    version_unreadable: 'version unreadable'
  };

  var pending = Object.create(null);
  var nextId = 0;

  var state = {
    clis: [],

    /** True between `terminal.started` and `terminal.exited`/`terminal.stopped`. */
    running: false,

    /** True while a `terminal.start` is in flight, so Start cannot be pressed twice. */
    starting: false,

    cwd: null,

    /**
     * What `init.evidence` said about this session's run folder, kept up to date by
     * `evidence.extract`. `{present, run_dir}`; the host is the only thing that decides it.
     */
    evidence: { present: false, run_dir: null },

    /** True while an `evidence.extract` is in flight. */
    extracting: false
  };

  var ui = {};
  var term = null;
  var fit = null;

  // ---- transport: the host ------------------------------------------------------------------

  function envelope(type, payload) {
    return { type: type, id: 'p' + (++nextId), payload: payload || {} };
  }

  /** Posts and forgets. For the messages the contract gives no reply. */
  function send(type, payload) {
    if (!bridge) {
      return;
    }

    bridge.postMessage(envelope(type, payload));
  }

  /** Posts and waits for the reply that echoes the id. */
  function request(type, payload) {
    var message = envelope(type, payload);
    return new Promise(function (resolve, reject) {
      if (!bridge) {
        reject(new Error('this page is not hosted in the SwReview task pane'));
        return;
      }

      pending[message.id] = { resolve: resolve, reject: reject };
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
    error.installSteps = (payload && payload.install_steps) || null;
    return error;
  }

  function handleUnsolicited(message) {
    var payload = message.payload || {};
    switch (message.type) {
      case 'terminal.output':
        write(payload.data_base64);
        return;
      case 'terminal.exited':
        sessionEnded(payload.exit_code);
        return;
      case 'chatlog.count':
        renderChatLog(payload.count);
        return;
      case 'error':
        showBanner(asError(payload).message);
        return;
      default:
        return;
    }
  }

  // ---- the screen ---------------------------------------------------------------------------

  /**
   * Base64 to bytes. Deliberately not `TextDecoder`: see rule 3. `charCodeAt` is a byte here
   * because `atob` returns one character per byte by definition.
   */
  function decode(base64) {
    var binary = window.atob(base64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i) & 0xff;
    }

    return bytes;
  }

  function write(base64) {
    if (!term || typeof base64 !== 'string' || base64.length === 0) {
      return;
    }

    try {
      term.write(decode(base64));
    } catch (error) {
      // A chunk that is not base64 is the host's bug, not the engineer's problem: the terminal
      // keeps running and the next chunk is unaffected.
      showBanner('Some terminal output could not be decoded and was dropped.');
    }
  }

  /** A line from the pane rather than from the CLI. Written into the VT stream, not the DOM. */
  function note(text) {
    if (term) {
      term.write('\r\n[2m' + text + '[0m\r\n');
    }
  }

  function fitScreen() {
    if (!fit) {
      return;
    }

    try {
      fit.fit();
    } catch (error) {
      // The pane can be dragged narrower than one cell, and the addon measures a box that is
      // then zero. The old size stays; the next resize fixes it.
    }
  }

  // ---- the evidence package -------------------------------------------------------------------

  /**
   * What the footer of the header area says before Start: whether there is anything in this
   * run folder for the CLI to read, and - when there is not - the button that writes it.
   *
   * The sentence is here rather than in the host because it is a sentence about this page's
   * own buttons. What it is a sentence *about* - present or not, and which folder - is the
   * host's answer, exactly like the CLI rows.
   */
  function renderEvidence() {
    if (state.extracting) {
      ui.evidenceText.textContent = 'Extracting evidence from the open document...';
      ui.extract.hidden = false;
      ui.extract.disabled = true;
      return;
    }

    if (state.evidence.present) {
      ui.evidenceText.textContent = 'This session folder holds an evidence package.';
      ui.extract.hidden = true;
      return;
    }

    ui.evidenceText.textContent =
      'No evidence for this session yet, so the CLI has nothing to read about the model.';
    ui.extract.hidden = false;
    ui.extract.disabled = false;
  }

  /**
   * Press Extract evidence: the host runs the same dump the Review tab runs, into this
   * session's run folder. The CLI does not have to be restarted for it - the MCP server
   * re-reads the package - so the terminal keeps whatever is on it and gets a line saying so.
   */
  function extractEvidence() {
    if (state.extracting) {
      return;
    }

    showBanner(null);
    state.extracting = true;
    renderEvidence();

    request('evidence.extract', {})
      .then(function (payload) {
        state.extracting = false;
        state.evidence = { present: true, run_dir: payload.run_dir || null };
        renderEvidence();
        note('[extracted ' + counted(payload.counts) + ' into ' + (payload.run_dir || 'the run folder') + ']');
      })
      .catch(function (error) {
        state.extracting = false;
        renderEvidence();
        showBanner(error.message);
      });
  }

  /** `evidence.extracted.counts` as a phrase, or nothing when the host sent none. */
  function counted(counts) {
    if (!counts || typeof counts.components !== 'number') {
      return 'the evidence package';
    }

    return counts.components + ' components and ' + (counts.gaps || 0) + ' gaps';
  }

  // ---- the CLI list -------------------------------------------------------------------------

  function findCli(name) {
    for (var i = 0; i < state.clis.length; i++) {
      if (state.clis[i] && state.clis[i].name === name) {
        return state.clis[i];
      }
    }

    return null;
  }

  /**
   * Whether Start may be pressed for this row. `status` when the host sent one, `found`
   * otherwise: the contract's row is `{name, found, version, path, minimum}` and a host that
   * says nothing more is taken at its word.
   */
  function canStart(cli) {
    if (!cli) {
      return false;
    }

    if (typeof cli.status === 'string') {
      return cli.status === 'ready';
    }

    return !!cli.found;
  }

  function displayName(cli) {
    return (cli && (cli.display_name || cli.name)) || 'the CLI';
  }

  /** What the dropdown says: the CLI, its version, and why it cannot be started if it cannot. */
  function optionText(cli) {
    var text = displayName(cli);
    if (cli.version) {
      text += ' ' + cli.version;
    }

    var why = statusText(cli);
    return why ? text + ' - ' + why : text;
  }

  function statusText(cli) {
    if (typeof cli.status === 'string') {
      return Object.prototype.hasOwnProperty.call(STATUS_TEXT, cli.status)
        ? STATUS_TEXT[cli.status]
        : cli.status;
    }

    return cli.found ? null : 'not installed';
  }

  function renderClis(lastChoice) {
    while (ui.cli.firstChild) {
      ui.cli.removeChild(ui.cli.firstChild);
    }

    for (var i = 0; i < state.clis.length; i++) {
      var cli = state.clis[i];
      if (!cli || typeof cli.name !== 'string') {
        continue;
      }

      var option = document.createElement('option');
      option.value = cli.name;
      option.textContent = optionText(cli);
      ui.cli.appendChild(option);
    }

    if (lastChoice && findCli(lastChoice)) {
      ui.cli.value = lastChoice;
    }

    onCliChosen();
  }

  /**
   * The install-steps view for the CLI in the dropdown, or nothing when it is startable. Also
   * reached from a failed `terminal.start`, where the host's message and steps are better than
   * the ones the listing carried.
   */
  function onCliChosen() {
    var cli = findCli(ui.cli.value);
    if (canStart(cli)) {
      hideInstall();
    } else {
      showInstall(cli, null);
    }

    renderControls();
  }

  function showInstall(cli, error) {
    ui.installTitle.textContent = displayName(cli) + ' cannot be started';

    var message = (error && error.message) || (cli && cli.message) || '';
    if (!message && cli) {
      message = statusText(cli) ? displayName(cli) + ' is ' + statusText(cli) + '.' : '';
    }

    if (cli && cli.minimum) {
      message += (message ? ' ' : '') + displayName(cli) + ' ' + cli.minimum
        + ' or newer is required.';
    }

    ui.installMessage.textContent = message;

    var steps = (error && error.installSteps) || (cli && cli.install_steps) || '';
    ui.installSteps.textContent = steps;
    ui.installSteps.hidden = steps.length === 0;
    ui.install.hidden = false;
  }

  function hideInstall() {
    ui.install.hidden = true;
  }

  // ---- the session --------------------------------------------------------------------------

  function startSession() {
    var cli = findCli(ui.cli.value);
    if (!canStart(cli) || state.running || state.starting) {
      return;
    }

    showBanner(null);
    state.starting = true;
    renderControls();
    fitScreen();

    request('terminal.start', { cli: cli.name, cols: term.cols, rows: term.rows })
      .then(function (payload) {
        state.starting = false;
        state.running = true;
        state.cwd = payload.cwd || null;
        hideInstall();
        renderCwd();
        renderControls();
        term.focus();
      })
      .catch(function (error) {
        state.starting = false;
        state.running = false;
        renderControls();
        showInstall(cli, error);
      });
  }

  function stopSession() {
    if (!state.running) {
      return;
    }

    ui.stop.disabled = true;
    request('terminal.stop', {})
      .then(function () {
        sessionEnded(null);
      })
      .catch(function (error) {
        showBanner(error.message);
        sessionEnded(null);
      });
  }

  /**
   * One end for both ways a session ends - the CLI exited, or Stop was pressed. Idempotent,
   * because `terminal.exited` and the reply to `terminal.stop` both arrive for a stop.
   */
  function sessionEnded(exitCode) {
    if (state.running && typeof exitCode === 'number') {
      note('[the CLI exited with code ' + exitCode + ']');
    }

    state.running = false;
    state.starting = false;
    state.cwd = null;
    renderCwd();
    renderControls();
  }

  // ---- rendering ----------------------------------------------------------------------------

  function renderControls() {
    var cli = findCli(ui.cli.value);
    ui.start.disabled = state.running || state.starting || !canStart(cli);
    ui.stop.disabled = !state.running;
    ui.cli.disabled = state.running || state.starting;
  }

  function renderCwd() {
    ui.cwd.textContent = state.cwd || '';
  }

  function renderChatLog(count) {
    var total = (typeof count === 'number' && count >= 0) ? count : 0;
    ui.chatlog.textContent = total === 0
      ? 'No tool calls yet'
      : (total === 1 ? '1 tool call logged' : total + ' tool calls logged');
  }

  function showBanner(message) {
    if (!message) {
      ui.banner.hidden = true;
      ui.banner.textContent = '';
      return;
    }

    ui.banner.textContent = message;
    ui.banner.hidden = false;
  }

  // ---- start ---------------------------------------------------------------------------------

  function buildTerminal() {
    term = new window.Terminal({
      cursorBlink: true,
      convertEol: false,
      scrollback: 5000,
      fontFamily: 'Consolas, "Cascadia Mono", "Lucida Console", monospace',
      fontSize: 12
    });

    fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(ui.screen);
    fitScreen();

    term.onData(function (data) {
      if (state.running) {
        send('terminal.input', { data: data });
      }
    });

    term.onResize(function (size) {
      if (state.running) {
        send('terminal.resize', { cols: size.cols, rows: size.rows });
      }
    });
  }

  function start() {
    buildTerminal();
    renderChatLog(0);
    renderEvidence();

    // The size goes out with `ready` so the first CLI is started at the size it will be drawn
    // at: a CLI that lays its screen out at 80x24 and is then resized redraws, and the redraw
    // is the first thing the engineer sees.
    request('ready', { cols: term.cols, rows: term.rows })
      .then(function (payload) {
        state.clis = payload.clis || [];
        state.evidence = payload.evidence || { present: false, run_dir: null };
        renderEvidence();
        renderClis(payload.last_choice || null);
      })
      .catch(function (error) {
        showBanner(error.message);
      });
  }

  function bind() {
    ui.cli = document.getElementById('cli');
    ui.start = document.getElementById('start');
    ui.stop = document.getElementById('stop');
    ui.banner = document.getElementById('banner');
    ui.evidenceText = document.getElementById('evidence-text');
    ui.extract = document.getElementById('extract');
    ui.install = document.getElementById('install');
    ui.installTitle = document.getElementById('install-title');
    ui.installMessage = document.getElementById('install-message');
    ui.installSteps = document.getElementById('install-steps');
    ui.screen = document.getElementById('screen');
    ui.cwd = document.getElementById('cwd');
    ui.chatlog = document.getElementById('chatlog');

    ui.cli.addEventListener('change', onCliChosen);
    ui.start.addEventListener('click', startSession);
    ui.extract.addEventListener('click', extractEvidence);
    ui.stop.addEventListener('click', stopSession);

    // The pane is dragged wider and narrower all day. The fit addon recomputes the cell grid;
    // `onResize` above is what tells the pseudo-console about it, so the CLI re-wraps rather
    // than drawing to a width that is no longer there.
    window.addEventListener('resize', fitScreen);

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
