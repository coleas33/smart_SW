"""The `remodel.*` bridge client (T072).

`specs/004-resilient-remodeler/contracts/bridge-remodel.md` is the wire contract: twelve
commands added to the 1.0 envelope of `SwReview.Extractor.Console/Serve/PROTOCOL.md`,
which goes to **1.1** additively. This module is the Python end of that page and nothing
more - it composes requests, names the reply, and turns a refusal into a class. Every
decision about *what* to ask for lives in `swreview.remodel.*`, which has no bridge in any
signature.

It is a subclass of `BridgeClient` rather than a second client because the framing, the id
sequencing, the per-launch secret, the transport and the circuit breaker are already there
and there is no second copy of any of them here. Three things are its own:

- **its own vocabulary.** `REMODEL_COMMANDS` is `ping` plus the twelve rows of the
  contract's command table, and it *replaces* the inherited allowlist rather than widening
  it: `capture`, `measure` and `interference` are refused on this side before a line is
  written, which is the client-side mirror of `RemodelSecret`'s scope. `COMMANDS` in
  `client.py` is untouched.
- **`error_code`, not prose.** On `status: "error"` a `remodel.*` reply carries
  `result: {"error_code": "<token>", "detail": {}}`. `ERROR_CLASSES` maps each of the
  contract's twenty-four tokens to one `RemodelError` subclass, all of them under
  `BridgeError`, so a caller that catches the base type cannot crash on any of them. A
  token this client has never heard of raises `RemodelError` itself carrying that token:
  an unknown code stays unknown and is never guessed into the nearest class. A failure
  with no token at all - a host still speaking 1.0, or one of the two refusals the
  envelope has always had - keeps the class `BridgeClient` already gives it
  (`BridgeUnauthorizedError`, `BridgeDocumentClosedError`, `BridgeError`).
- **an open circuit is returned, not raised.** Every command answers `CircuitOpen` once
  the breaker has tripped (three consecutive failures, or the host's own
  `status: "circuit_open"`). The run is run-to-completion and has to record "the bridge
  stopped answering" against the change it was making, in `changes.jsonl`, rather than
  unwind out of the loop; `BridgeOpenError` still exists and is still what the inherited
  call raises, this client just converts it into a value. Nothing is sent once it is open,
  and **the run never auto-resumes**.

**No command that writes names a document.** `RemodelScope` on the C# side holds the only
`IModelDoc2` the run can reach. Exactly two methods take a path - `probe_scope`, which
reads the engineer's already-open source, and `open`, which names the source to copy from
and the copy to create - and both run before that scope exists. `DOCUMENT_PARAM_NAMES` is
the set a test asserts the other ten never carry, so the property is checked over the whole
table rather than trusted command by command.

One name deviates from the command it sends: `remodel.close` is `close_document`, because
`BridgeClient.close` already means "close the pipe" and the two are not the same act - one
ends the document, the other ends the transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from swreview.bridge.client import (
    DEFAULT_PIPE_NAME,
    DEFAULT_TIMEOUT_S,
    BridgeClient,
    BridgeError,
    BridgeOpenError,
    Transport,
)

__all__ = [
    "DOCUMENT_PARAM_NAMES",
    "EQUATION_OPS",
    "ERROR_CLASSES",
    "FOLDER_OPS",
    "GATE_VERDICTS",
    "REMODEL_COMMANDS",
    "REMODEL_PROTOCOL_VERSION",
    "REORDER_LOCATIONS",
    "CircuitOpen",
    "RemodelAddressError",
    "RemodelChangeError",
    "RemodelClient",
    "RemodelContractError",
    "RemodelError",
    "RemodelGuardError",
    "RemodelLimitError",
    "RemodelNotInV1Error",
    "RemodelPreflightError",
    "RemodelRunInProgress",
    "RemodelSaveError",
    "RemodelTargetError",
]

REMODEL_PROTOCOL_VERSION = "1.1"
"""The envelope version this family needs from the host. 1.0 plus one addition: an error
reply carries `result.error_code`. The four commands of 1.0 are unchanged."""

REMODEL_COMMANDS: tuple[str, ...] = (
    "ping",
    "remodel.probe_scope",
    "remodel.open",
    "remodel.snapshot",
    "remodel.rename",
    "remodel.reorder",
    "remodel.folder",
    "remodel.describe",
    "remodel.equation",
    "remodel.rebuild",
    "remodel.geometry",
    "remodel.save",
    "remodel.close",
)
"""Everything `RemodelSecret` authorizes, in the contract's table order. Checked before the
request line is written, so a command outside it never reaches SOLIDWORKS."""

DOCUMENT_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "source_path",
        "copy_path",
        "path",
        "document",
        "document_path",
        "scope_document",
        "scope_document_a",
        "scope_document_b",
        "model",
    }
)
"""Every spelling of "a document" that has ever appeared in a bridge request, this family's
two included. Only `remodel.probe_scope` and `remodel.open` may carry any of them."""

REORDER_LOCATIONS: frozenset[str] = frozenset({"before", "after"})
"""`swMoveLocation_e.Before = 2` and `After = 3`. `swMoveToFolder = 5` is not in v1:
folders are created by wrapping a contiguous run, so nothing moves into an existing one."""

FOLDER_OPS: frozenset[str] = frozenset({"create", "rename", "dissolve"})
"""`dissolve` is sent and refused by the host with `not_in_v1`, never refused here: the
value stays in the protocol so stage 2 adds an allowlist entry and a handler branch rather
than a command."""

EQUATION_OPS: frozenset[str] = frozenset({"add", "set", "delete"})
"""`set` is FR-029's in-place repair and is its own inverse; `delete` is only ever the
inverse of an `add` this run made."""

GATE_VERDICTS: frozenset[str] = frozenset({"pass", "fail", "unresolved"})
"""`remodel/geometry.py`'s `Verdict`, as `remodel.save` reports it. The gate is decided
here and enforced there: the host refuses `Save3` with `gate_not_passed` on anything but
`pass`, so the constitution's "only after the geometry comparison has passed" is checked
beside the call it guards and not only by the caller that reports it."""


class RemodelError(BridgeError):
    """A `remodel.*` refusal that named its reason with a stable token.

    `error_code` is the token exactly as the host sent it and `detail` whatever it attached
    beside it. The class of the exception is derived from the token, never from the prose,
    and `message` still carries the sentence an engineer reads.
    """

    def __init__(
        self,
        message: str,
        error_code: str,
        detail: Any = None,
        result: Any = None,
    ) -> None:
        super().__init__(message, result)
        self.error_code = error_code
        self.detail = detail


class RemodelPreflightError(RemodelError):
    """The run was refused before it began. No copy exists, except for the one refusal
    that needs the copy to be taken (`preexisting_rebuild_errors`), whose handler deletes
    it and closes the document before answering."""


class RemodelContractError(RemodelError):
    """The caller asked for something the protocol says cannot happen: a bug here, not a
    condition in the part. The run stops and the copy is discarded."""


class RemodelTargetError(RemodelError):
    """The document being written is not provably the one this run created. The run aborts
    with the change log intact."""


class RemodelGuardError(RemodelError):
    """A member outside the stage-1 allowlist was reached. A bug, not a condition."""


class RemodelAddressError(RemodelError):
    """A persistent reference did not resolve. The change fails and the run stops: a tree
    this run cannot address is a tree it cannot reason about."""


class RemodelChangeError(RemodelError):
    """One change could not be proven to have landed, or raised the rebuild-error count.
    It is inverted; the run carries on."""


class RemodelLimitError(RemodelError):
    """A bound was hit - a rebuild longer than `max_rebuild_seconds`. The run finalizes as
    `truncated` rather than hanging."""


class RemodelSaveError(RemodelError):
    """`Save3` reported an error. A failed run, whatever else went right."""


class RemodelNotInV1Error(RemodelError):
    """A reserved stage-2 operation was requested."""


class RemodelRunInProgress(RemodelError):
    """A second run was started on the same host. One run at a time, per seat."""


ERROR_CLASSES: dict[str, type[RemodelError]] = {
    "not_a_part": RemodelPreflightError,
    "source_not_open": RemodelPreflightError,
    "scope_not_probed": RemodelContractError,
    "scope_changed": RemodelTargetError,
    "source_dirty": RemodelPreflightError,
    "external_refs": RemodelPreflightError,
    "copy_exists": RemodelPreflightError,
    "copy_failed": RemodelPreflightError,
    "open_failed": RemodelTargetError,
    "tag_failed": RemodelTargetError,
    "preexisting_rebuild_errors": RemodelPreflightError,
    "target_mismatch": RemodelTargetError,
    "guard_refused": RemodelGuardError,
    "persist_ref_unresolved": RemodelAddressError,
    "reorder_refused": RemodelContractError,
    "folder_members_not_contiguous": RemodelContractError,
    "equation_unverified": RemodelChangeError,
    "rebuild_regressed": RemodelChangeError,
    "rebuild_timeout": RemodelLimitError,
    "gate_not_passed": RemodelContractError,
    "save_failed": RemodelSaveError,
    "not_in_v1": RemodelNotInV1Error,
    "run_in_progress": RemodelRunInProgress,
    "bad_request": RemodelContractError,
}
"""The error table of `contracts/bridge-remodel.md`, token for token and in its order.

`bad_request` is the last row for the reason the contract gives: the host raises it for a
request it cannot honour as sent - a missing parameter, an op aimed at a feature that is not
a folder, a description it cannot read and therefore cannot invert - all of which are bugs in
the caller rather than conditions of the part. It is a `RemodelContractError` for the same
reason `scope_not_probed` is, so the executor can tell "the caller sent junk" from "the change
failed, invert it" instead of meeting a bare `RemodelError`."""


@dataclass(frozen=True)
class CircuitOpen:
    """The bridge has stopped answering, and this call was not sent.

    A value and not an exception: the executor records it against the change it was making
    and finalizes the run, and a caller catching `BridgeError` cannot swallow it by
    accident. `last_error` is the message of the failure that tripped the breaker, which is
    built from the host's own error text and never from a request line, so the secret is
    not in it.
    """

    command: str
    last_error: str | None
    status: Literal["circuit_open"] = "circuit_open"


class RemodelClient(BridgeClient):
    """The twelve `remodel.*` commands, or an honest failure."""

    def __init__(
        self,
        pipe_name: str = DEFAULT_PIPE_NAME,
        secret: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(
            pipe_name=pipe_name,
            secret=secret,
            timeout_s=timeout_s,
            transport=transport,
        )
        self.commands = REMODEL_COMMANDS

    # --- the one call ------------------------------------------------------------

    def _remodel_call(
        self, command: str, params: dict[str, Any]
    ) -> Any | CircuitOpen:
        """Send one command; return its `result`, or `CircuitOpen`, or raise its class."""
        try:
            return self.call(command, params)
        except BridgeOpenError as exc:
            return CircuitOpen(command=command, last_error=str(exc))
        except BridgeError as exc:
            raise _classify(exc) from exc

    @staticmethod
    def _closed(name: str, value: Any, allowed: frozenset[str]) -> None:
        """Refuse a value outside a closed set before the line goes out.

        The closed sets of the contract are checked here rather than only on the host
        because an out-of-set value is a bug in the planner, and a bug in the planner should
        not become a write attempt on a document.
        """
        if value not in allowed:
            raise BridgeError(
                f"{name}={value!r} is not one of {sorted(allowed)}; nothing was sent"
            )

    # --- before the scope exists: the only two commands that name a path ----------

    def probe_scope(self, source_path: str) -> Any | CircuitOpen:
        """Read the scope signals off the engineer's already-open source. Read-only, and
        it runs before anything is copied, which is what makes FR-001's refusal true."""
        return self._remodel_call("remodel.probe_scope", {"source_path": source_path})

    def open(
        self, source_path: str, copy_path: str, run_id: str, probe_id: str
    ) -> Any | CircuitOpen:
        """Copy the source and open the copy. The only command that creates a document
        handle, and the last one that names a path."""
        return self._remodel_call(
            "remodel.open",
            {
                "source_path": source_path,
                "copy_path": copy_path,
                "run_id": run_id,
                "probe_id": probe_id,
            },
        )

    # --- after the scope exists: nothing names a document -------------------------

    def snapshot(self) -> Any | CircuitOpen:
        """The tree as it stands: order, names, descriptions, equations, error count."""
        return self._remodel_call("remodel.snapshot", {})

    def rename(self, persist_ref: str, new_name: str) -> Any | CircuitOpen:
        """Repair a duplicate feature name, or name a folder this run just created."""
        return self._remodel_call(
            "remodel.rename", {"persist_ref": persist_ref, "new_name": new_name}
        )

    def reorder(
        self, feature_persist_ref: str, anchor_persist_ref: str, location: str
    ) -> Any | CircuitOpen:
        """Move one feature to one anchor. Legality was decided from the dependency graph
        before the call, so a `false` from the host is `reorder_refused` and a stop."""
        self._closed("location", location, REORDER_LOCATIONS)
        return self._remodel_call(
            "remodel.reorder",
            {
                "feature_persist_ref": feature_persist_ref,
                "anchor_persist_ref": anchor_persist_ref,
                "location": location,
            },
        )

    def folder(
        self,
        op: str,
        name: str | None = None,
        member_persist_refs: list[str] | None = None,
        folder_persist_ref: str | None = None,
    ) -> Any | CircuitOpen:
        """Create a folder around a contiguous run, or rename one. `dissolve` is sent and
        the host refuses it with `not_in_v1`."""
        self._closed("op", op, FOLDER_OPS)
        return self._remodel_call(
            "remodel.folder",
            {
                "op": op,
                "name": name,
                "member_persist_refs": list(member_persist_refs or []),
                "folder_persist_ref": folder_persist_ref,
            },
        )

    def describe(self, persist_ref: str, text: str) -> Any | CircuitOpen:
        """Write a feature description. A previous text that reads back as `null` is
        refused by the planner, never overwritten with `""` here."""
        return self._remodel_call(
            "remodel.describe", {"persist_ref": persist_ref, "text": text}
        )

    def equation(
        self,
        op: str,
        index: int | None = None,
        text: str | None = None,
        which_configs: int | None = None,
    ) -> Any | CircuitOpen:
        """Add, repair in place, or delete one equation. The number in `text` is already in
        the document's length unit: `remodel.open` returned it and the executor converted."""
        self._closed("op", op, EQUATION_OPS)
        return self._remodel_call(
            "remodel.equation",
            {
                "op": op,
                "index": index,
                "text": text,
                "which_configs": which_configs,
            },
        )

    def rebuild(self, force: bool = False) -> Any | CircuitOpen:
        """`ForceRebuild3(force)` and the error reading. `feature_errors[]` is the primary
        one; `whats_wrong[]` corroborates it."""
        return self._remodel_call("remodel.rebuild", {"force": force})

    def geometry(self) -> Any | CircuitOpen:
        """One `GeometryReading` of the copy. It takes no parameters because there is
        nothing to name: the C# side stamps the subject from the run's own phase."""
        return self._remodel_call("remodel.geometry", {})

    def save(self, verdict: str) -> Any | CircuitOpen:
        """Save the copy, once, at the end.

        `verdict` is `evaluate()`'s `GateResult.verdict` for this run. The host refuses
        with `gate_not_passed` on anything but `pass`, and refuses a `pass` from a run it
        did not take both geometry readings for: the measurement is the bridge's and the
        decision is this side's, so the decision is reported rather than trusted to have
        been made.
        """
        self._closed("verdict", verdict, GATE_VERDICTS)
        return self._remodel_call("remodel.save", {"verdict": verdict})

    def close_document(self, discard_copy: bool) -> Any | CircuitOpen:
        """`remodel.close`. Named for what it closes, because `close()` closes the pipe.

        `discard_copy` deletes `copy/` and nothing else: every other artifact of the run
        stays, so "what did it propose" is still answerable after the engineer says no.
        """
        return self._remodel_call("remodel.close", {"discard_copy": discard_copy})


def _classify(exc: BridgeError) -> BridgeError:
    """The host's `error_code` as a class, or the exception exactly as it arrived.

    `BridgeUnauthorizedError` and `BridgeDocumentClosedError` carry no token and keep their
    meaning and their class, and so does a plain `BridgeError` from a host still answering
    in 1.0. A token with no row in `ERROR_CLASSES` becomes `RemodelError` carrying that
    token: unknown stays unknown.
    """
    result = exc.result
    if not isinstance(result, dict):
        return exc
    error_code = result.get("error_code")
    if not isinstance(error_code, str) or not error_code:
        return exc
    cls = ERROR_CLASSES.get(error_code, RemodelError)
    return cls(str(exc), error_code, result.get("detail"), result)
