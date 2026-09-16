/*
  The DOM helpers both Task Pane pages build every node with (T080).

  This file exists for one reason, and it is not tidiness. Every string these pages show was
  authored somewhere else - by a language model, by a reviewed document, by a feature name an
  engineer typed into SOLIDWORKS - and the rule for all of them is the same: it reaches the
  screen through `document.createTextNode` and through nothing else
  (contracts/pane-host-messages.md, "Rendering untrusted text"). A second page that copied
  these ten functions would be a second copy of that rule, and a rule with two copies has one
  that is out of date. So there is one copy, it is loaded by both pages from the same virtual
  host, and the injection tests of both pages render through it.

  Nothing here reads page state, the host bridge or the network. That is what lets a test call
  `SwReviewDom.field(...)` inside the real page, under the real CSP, and ask the browser what
  actually landed in the DOM.

  There is no `innerHTML` in this file, no adjacent-markup insertion, and no place where
  markup is assembled from a string. Adding one would defeat every page that loads it at once.
*/

(function () {
  'use strict';

  // ---- elements -------------------------------------------------------------------------

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

  /** Appends literal text to a node. The only way text ever enters a page. */
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

  /**
   * A button that declares what it does rather than carrying a handler: `data-action` is read
   * by one delegated listener per page. No inline handler anywhere, which the CSP would refuse
   * in any case, and a button built by a test behaves exactly like one built by the page.
   */
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

  // ---- formatting -------------------------------------------------------------------------

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

  window.SwReviewDom = {
    el: el,
    write: write,
    clear: clear,
    append: append,
    button: button,
    field: field,
    list: list,
    scalar: scalar,
    compact: compact,
    seconds: seconds
  };
})();
