# Bridge protocol (Python side)

**The authoritative protocol is
`extractor/SwReview.Extractor.Console/Serve/PROTOCOL.md`** (protocol version 1.2). That
file describes what `SwReview.Extractor.Console.exe serve --pipe <name>` speaks;
`swreview.bridge.client` is written against it, and
`reviewer/tests/unit/test_bridge_client.py` is the executable copy of what this client
sends and expects.

This file records only what is true of the Python end and is not in the host's contract.

## What the client sends

One JSON object per line, UTF-8, `\n`-terminated, over `\\.\pipe\<name>`:

```json
{"id": "1", "command": "capture", "params": {"persist_ref": "…", "view": "iso"}}
```

`id` is a string (a monotonic counter rendered as decimal), `params` is the command's
argument object, and `command` is one of `ping`, `capture`, `measure`, `interference`,
`tessellate` - the whole vocabulary. A client built with a `secret` adds one more
top-level field, `"secret": "<per-launch>"`, on every line; a client built without one **omits the field
entirely** rather than sending `""`, because an empty string is a wrong secret to the
in-process host and the console host asks for none. The secret is never written into an
error message, `last_error`, or a log line on this side either. `COMMANDS` in `client.py` is that allowlist and it is checked before
anything is written to the pipe, so no tool can ask SOLIDWORKS for a member, a macro or a
file (research R4, constitution Technical Constraints). The host applies its own read-only
guard on top.

## How failures come back to the review

Every non-`ok` response, every unreadable line, every response carrying another request's
id, a dead pipe and a timeout are one exception type, `BridgeError`. The tool that made
the call turns it into an error result, which `swreview.tools.registry` records as
`failed` coverage - so a bridge that stopped working appears in the report as checks that
did not run, never as checks that passed.

Where the host attaches a `Gap` to a failed `capture`, the client carries it on the
exception (`BridgeError.result`) and `swreview.tools.bridge` appends it to the package's
`gaps`: the request is visible as something extraction could not provide rather than being
lost with the error message.

## The two refusals the in-process host makes

`BridgeError` has two named subclasses, so the tool layer can say which refusal happened
instead of only that the bridge said no. Both are `BridgeError`, so a caller that catches
the base type cannot crash on either, and both become `failed` coverage the same way.

| Host answer | Raised | Effect on the breaker |
|-------------|--------|-----------------------|
| `error` whose text starts with `unauthorized` | `BridgeUnauthorizedError` | Opens the circuit at once |
| `error` whose text contains `no longer open` | `BridgeDocumentClosedError` | None: the count is left exactly where it was |

A refused secret never becomes accepted and every attempt is logged on the host side, so
two more round trips to reach `CIRCUIT_LIMIT` would buy nothing: the circuit opens on the
first `unauthorized`.

A closed document is a definite answer from a healthy host rather than a SOLIDWORKS
failure, so it neither trips the breaker on its own nor clears failures that came before
it. That is what keeps spec.md's promise that the review "continues on the extracted
package; any live action fails with a clear 'document no longer open' error and becomes
failed coverage" - a breaker message in its place would hide why the bridge went quiet.
The match is on `no longer open` as a case-insensitive substring, so the contract's
sentence and a fuller one around it are both recognised.

## Circuit breaker

`status: "circuit_open"` from the host, or `CIRCUIT_LIMIT` (3) consecutive failures of any
kind, opens the circuit locally: every further call raises `BridgeOpenError` naming the
last error without touching the pipe. The host does not recover without a restart, and the
review is better off continuing offline with honest `failed` coverage. One success resets
the count (a local trip only - a host that answered `circuit_open` will keep doing so).

## Known limitation: no read timeout

`pywin32` is deliberately not a dependency, so the client opens the pipe as an ordinary
byte stream (`open(r"\\.\pipe\swreview", "r+b", buffering=0)`) and **cannot set a read
timeout on the handle**. `timeout_s` is carried and reported but a blocking read on a host
that never answers will block. What bounds it in practice is that the bridge is only ever
started by an engineer at the workstation, plus the circuit breaker above.

If a real timeout is needed, replace the transport rather than this class: `BridgeClient`
accepts any object with `request(line) -> line` and `close()`. That is also how the tests
exercise the whole protocol with no pipe and no SOLIDWORKS.

## Views

The host frames a capture with `iso`, `front`, `top`, `right` or `fit` (`BRIDGE_VIEWS`).
The session tool `request_capture` accepts the wider `CaptureView` enum of
contracts/agent-tools.md; a view the bridge cannot frame comes back `unresolved` naming
the ones it can, rather than being quietly swapped for a different view.
