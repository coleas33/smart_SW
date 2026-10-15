"""Authenticated pane entry into the existing saved-snapshot context workflow.

Run IDs select fixed private stores. These routes neither inspect native CAD nor
manufacture confirmations; the engineer explicitly presents each approval digest.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from swreview.chat.server import PACKAGE_ERRORS, ChatError
from swreview.chat.sessions import ChatState
from swreview.engineering_context import workflow
from swreview.engineering_context.binding import (
    anchor_from_package,
    assess_binding,
    baseline_from_package,
)
from swreview.engineering_context.brief import _NATIVE_REF, _PATH, _QUOTED_PATH
from swreview.engineering_context.models import (
    ContextArtifact,
    ContextModel,
    Digest,
    Identifier,
    Label,
    Text,
    Vector3,
    context_digest,
)
from swreview.engineering_context.store import (
    ContextStoreBusy,
    ContextStoreConflict,
    ContextStoreError,
    _reject_link,
)
from swreview.ir.loader import (
    PACKAGE_FILE_NAME,
    AnswerKeyAccessError,
    LoadedPackage,
    load_package,
    reject_answer_key_path,
)

TARGET_LIMIT = 500
CONTEXT_READ_ERRORS = (*PACKAGE_ERRORS, AnswerKeyAccessError)
_WINDOWS_ALIAS = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


def _public_id(value: str) -> str:
    if _PATH.search(value) or _NATIVE_REF.search(value):
        raise ValueError("a public engineering identifier is required")
    return value


PublicIdentifier = Annotated[Identifier, AfterValidator(_public_id)]


class ContextEntryRefused(ChatError):
    error_class = "EngineeringContextRefused"


class ContextEntryConflict(ContextEntryRefused):
    status = 409
    error_class = "EngineeringContextConflict"


class UnknownContextRun(ContextEntryRefused):
    status = 404
    error_class = "UnknownEngineeringContextRun"


class InitInput(ContextModel):
    pass


class RecordInput(ContextModel):
    expected_head: Digest
    record_id: PublicIdentifier
    kind: Literal["document", "component", "face"]
    entity_id: Label
    component_id: Label | None = None
    provenance_kind: Literal["engineer", "ai_proposal"] = "engineer"
    assumptions: tuple[Text, ...] = Field(default=(), max_length=20)


class RequirementInput(RecordInput):
    text: Text


class ForceInput(RecordInput):
    kind: Literal["component", "face"]
    magnitude: float | None = None
    unit: Literal["N", "kN", "lbf"]
    direction: Vector3 | None = None
    unknown_reason: Text | None = None
    frame_component_id: Label | None = None
    point_m: Vector3 | None = None


class ConfirmInput(ContextModel):
    expected_head: Digest
    record_id: PublicIdentifier
    actor: Label
    expected_record_digest: Digest
    expected_dependency_digest: Digest


class ContextAttachment(ContextModel):
    context_id: UUID
    head_digest: Digest
    package_sha256: Digest


def _typed(model: type[ContextModel], value: Any) -> ContextModel:
    try:
        return model.model_validate_json(json.dumps(value, allow_nan=False))
    except (ValidationError, TypeError, ValueError):
        # ValidationError includes rejected inputs, which may contain private paths.
        raise ContextEntryRefused("Invalid engineering context input.") from None


def _text(value: str | None) -> str | None:
    """Retain complete engineering prose while omitting private source references."""
    if value is None:
        return None
    result = _NATIVE_REF.sub("[native reference omitted]", value)
    result = _QUOTED_PATH.sub("[private path omitted]", result)
    return _PATH.sub("[private path omitted]", result)


def _identifier(value: str | None) -> str | None:
    if value is None or _PATH.search(value) or _NATIVE_REF.search(value):
        return None
    return value


def _file_name(value: str) -> str:
    return _text(PureWindowsPath(value).name) or "Unknown document"


def _target_label(
    loaded: LoadedPackage,
    kind: str,
    entity_id: str,
    component_id: str | None,
    *,
    documents: dict[str, Any] | None = None,
    components: dict[str, Any] | None = None,
) -> str:
    package = loaded.package
    if documents is None:
        documents = {row.document_id: row for row in package.documents}
    if components is None:
        components = {row.id: row for row in package.components}
    if kind == "document":
        document = documents.get(entity_id)
        if document is not None:
            return f"{_file_name(document.file_name)} [{_text(document.active_configuration)}]"
    component = components.get(entity_id if kind == "component" else component_id)
    if component is None:
        return "Unavailable saved target"
    document = documents.get(component.document_id)
    file_name = _file_name(document.file_name) if document else "Unknown document"
    occurrence = _text(component.full_path or component.name)
    config = _text(component.referenced_configuration)
    label = f"{occurrence} — {file_name} [{config}]"
    return label if kind == "component" else f"{label} / {_identifier(entity_id) or 'face'}"


def _targets(
    loaded: LoadedPackage,
    *,
    documents: dict[str, Any] | None = None,
    components: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if documents is None:
        documents = {row.document_id: row for row in loaded.package.documents}
    if components is None:
        components = {row.id: row for row in loaded.package.components}
    candidates: list[tuple[str, str, str | None, str | None, str | None]] = []
    for row in loaded.package.documents:
        if row.kind != "drawing":
            candidates.append(
                ("document", row.document_id, row.document_id, row.active_configuration, None)
            )
    for row in loaded.package.components:
        candidates.append(
            ("component", row.id, row.document_id, row.referenced_configuration, row.id)
        )
    for row in loaded.package.faces:
        component = components.get(row.component_id)
        candidates.append(
            (
                "face",
                row.id,
                component.document_id if component else None,
                component.referenced_configuration if component else None,
                row.component_id,
            )
        )
    public = []
    omitted = 0
    for kind, entity_id, document_id, configuration, component_id in candidates:
        if not _identifier(entity_id) or len(public) == TARGET_LIMIT:
            omitted += 1
            continue
        public.append(
            {
                "kind": kind,
                "entity_id": entity_id,
                "document_id": _identifier(document_id),
                "configuration": _text(configuration),
                "component_id": _identifier(component_id),
                "label": _target_label(
                    loaded,
                    kind,
                    entity_id,
                    component_id,
                    documents=documents,
                    components=components,
                ),
            }
        )
    return public, omitted


def _operator_record(
    row: dict[str, Any],
    loaded: LoadedPackage,
    *,
    documents: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    private = row["record"]
    anchor = private["anchor"]
    target = {
        key: _identifier(anchor.get(key)) for key in ("entity_id", "document_id", "component_id")
    }
    # Package-local IDs may name other occurrences after extraction. Display the
    # historical anchor's occurrence/configuration, never a new package's ID match.
    document = documents.get(anchor.get("document_id"))
    file_name = _file_name(document.file_name) if document else "Unavailable saved document"
    configuration = _text(anchor.get("configuration"))
    label = f"{file_name} [{configuration}]"
    if anchor["kind"] != "document":
        occurrence = _text(anchor.get("full_path")) or _identifier(anchor.get("component_id"))
        label = f"{occurrence or 'Unavailable saved occurrence'} — {label}"
    if anchor["kind"] == "face":
        label += f" / {_identifier(anchor['entity_id']) or 'Unavailable saved face'}"
    target.update(kind=anchor["kind"], configuration=configuration, label=label)
    record = {
        "kind": private["kind"],
        "record_id": _identifier(private["record_id"]),
        "revision": private["revision"],
        "anchor": target,
        "provenance": {"kind": private["provenance"]["kind"]},
        "assumptions": [_text(value) for value in private["assumptions"]],
    }
    if private["kind"] == "requirement":
        record["text"] = _text(private["text"])
    else:
        record.update({key: private[key] for key in ("direction", "application", "point_m")})
        record["magnitude"] = {
            **private["magnitude"],
            "reason": _text(private["magnitude"]["reason"]),
        }
        frame = private["frame"]
        record["frame"] = None
        if frame:
            component_id = frame["component_id"]
            record["frame"] = {
                "frame_id": _identifier(frame["frame_id"]),
                "document_id": _identifier(frame["document_id"]),
                "component_id": _identifier(component_id),
                "transform": frame["transform"],
                "label": _target_label(
                    loaded,
                    "component" if component_id else "document",
                    component_id or frame["document_id"],
                    component_id,
                    documents=documents,
                    components=components,
                ),
            }
            if row["binding"]["status"] != "matched_snapshot":
                record["frame"]["label"] = "Recorded frame " + (
                    _identifier(component_id or frame["document_id"]) or "unknown"
                )
    public = {
        key: row[key]
        for key in ("record_digest", "dependency_digest", "decision", "binding", "freshness")
    }
    public["record"] = record
    if "resolved_force" in row:
        public["resolved_force"] = row["resolved_force"]
    return public


class EngineeringContextServer:
    def __init__(self, server: Any):
        self.server = server
        self._lock = threading.RLock()
        self._preparing: set[Path] = set()

    def _run_dir(self, run_id: Any) -> Path:
        if (
            not isinstance(run_id, str)
            or not run_id
            or len(run_id) > 128
            or run_id.startswith(".")
            or run_id.endswith((".", " "))
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in run_id)
            or _WINDOWS_ALIAS.match(run_id)
        ):
            raise UnknownContextRun("No saved engineering context run.")
        try:
            _reject_link(self.server.run_root)
            root = reject_answer_key_path(self.server.run_root, "public context evidence")
            directory = root / run_id
            _reject_link(directory)
            _reject_link(directory / PACKAGE_FILE_NAME)
            if directory.resolve().parent != root or not directory.is_dir():
                raise UnknownContextRun("No saved engineering context run.")
            reject_answer_key_path(directory, "public context evidence")
        except (AnswerKeyAccessError, ValueError, OSError):
            raise UnknownContextRun("No saved engineering context run.") from None
        return directory

    def _load(self, run_id: Any) -> tuple[Path, LoadedPackage]:
        directory = self._run_dir(run_id)
        try:
            loaded = load_package(directory)
            baseline_from_package(loaded)
            # Validates the fixed private store without creating it.
            workflow.store_for_package(self._store_dir(directory), loaded)
            return directory, loaded
        except CONTEXT_READ_ERRORS:
            raise ContextEntryRefused("Saved engineering evidence is unavailable.") from None

    def _store_dir(self, directory: Path) -> Path:
        return self.server.run_root / ".engineering-context" / directory.name

    def _busy(self, directory: Path) -> None:
        busy_states = {ChatState.EXTRACTING, ChatState.RUNNING, ChatState.WAITING_ENGINEER}
        if directory.resolve() in self._preparing or any(
            chat.run_dir.resolve() == directory.resolve() and chat.state in busy_states
            for chat in tuple(self.server.chats.values())
        ):
            raise ContextEntryConflict("Engineering context is in use by a running review.")

    def _inspect(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            directory, loaded = self._load(run_id)
            try:
                baseline = baseline_from_package(loaded)
                store = workflow.store_for_package(self._store_dir(directory), loaded)
                current = store.load()
                documents = {row.document_id: row for row in loaded.package.documents}
                components = {row.id: row for row in loaded.package.components}
                targets, omitted = _targets(loaded, documents=documents, components=components)
                result = {
                    "initialized": current is not None,
                    "run_id": directory.name,
                    "package_sha256": baseline.package_sha256,
                    "context_id": None,
                    "revision": None,
                    "head_digest": None,
                    "scope": "saved_snapshot",
                    "native_model_state": "not_observed",
                    "records": [],
                    "targets": targets,
                    "targets_omitted": omitted,
                }
                if current is not None:
                    private = workflow.inspect_context(directory, store.directory)
                    result.update(
                        {key: private[key] for key in ("context_id", "revision", "head_digest")}
                    )
                    result["records"] = [
                        _operator_record(row, loaded, documents=documents, components=components)
                        for row in private["records"]
                    ]
                return result
            except CONTEXT_READ_ERRORS:
                raise ContextEntryRefused("Saved engineering context is unavailable.") from None

    async def inspect(self, request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(self._inspect, request.path_params["run_id"]))

    def _mutate(self, run_id: str, body: ContextModel, operation: Callable) -> dict[str, Any]:
        with self._lock:
            directory, loaded = self._load(run_id)
            self._busy(directory)
            try:
                store = workflow.store_for_package(self._store_dir(directory), loaded)
                current = store.load()
                baseline = baseline_from_package(loaded)
                if isinstance(body, InitInput):
                    if current is not None:
                        raise ContextEntryConflict("Engineering context is already initialized.")
                else:
                    if current is None:
                        raise ContextEntryRefused(
                            "Initialize engineering context before entering inputs."
                        )
                    if (
                        current.baseline != baseline
                        or context_digest(current) != body.expected_head
                    ):
                        raise ContextEntryConflict(
                            "Saved engineering context changed; inspect it again."
                        )
                    if isinstance(body, RecordInput):
                        anchor = anchor_from_package(
                            loaded, "anchor:entry", body.kind, body.entity_id, body.component_id
                        )
                        if assess_binding(anchor, baseline, loaded).needs_review:
                            raise ContextEntryRefused(
                                "The saved target is unavailable or ambiguous."
                            )
                artifact = operation(directory, store.directory, **body.model_dump())
                return {
                    **workflow.publication(artifact),
                    "run_id": directory.name,
                    "package_sha256": baseline.package_sha256,
                }
            except (ContextStoreConflict, ContextStoreBusy):
                raise ContextEntryConflict(
                    "Engineering context changed or is busy; inspect it again."
                ) from None
            except (ContextStoreError, *CONTEXT_READ_ERRORS):
                raise ContextEntryRefused("Engineering context input could not be saved.") from None

    async def _write(
        self, request: Request, model: type[ContextModel], operation: Callable, *, status: int = 200
    ) -> Response:
        body = _typed(model, await self.server._json(request))
        result = await run_in_threadpool(
            self._mutate, request.path_params["run_id"], body, operation
        )
        return JSONResponse(result, status_code=status)

    async def initialize(self, request: Request) -> Response:
        return await self._write(request, InitInput, workflow.initialize, status=201)

    async def requirement(self, request: Request) -> Response:
        return await self._write(request, RequirementInput, workflow.enter_requirement)

    async def force(self, request: Request) -> Response:
        return await self._write(request, ForceInput, workflow.enter_force)

    async def confirm(self, request: Request) -> Response:
        return await self._write(request, ConfirmInput, workflow.approve)

    def _attached(
        self, directory: Path, attachment: ContextAttachment, *, same_package: bool, conflict: str
    ) -> ContextArtifact:
        """The fixed store's head, when it is exactly `attachment`'s; the one validator.

        `same_package` also requires the run folder's package to be the saved baseline, as a
        new review's start does. A waiting review's re-run (owner decision 99A) leaves it out:
        its own live checks may have appended evidence to the package since the start, which
        the summary marks as needing review rather than refusing.
        """
        safe_dir, loaded = self._load(directory.name)
        if safe_dir.resolve() != directory.resolve():
            raise ContextEntryRefused("The context attachment does not name this saved run.")
        try:
            artifact = workflow.store_for_package(self._store_dir(safe_dir), loaded).load()
            if (
                artifact is None
                or artifact.context_id != attachment.context_id
                or context_digest(artifact) != attachment.head_digest
                or artifact.baseline.package_sha256 != attachment.package_sha256
                or (same_package and baseline_from_package(loaded) != artifact.baseline)
            ):
                raise ContextEntryConflict(conflict)
        except CONTEXT_READ_ERRORS:
            raise ContextEntryRefused("Saved context attachment is unavailable.") from None
        return artifact

    def begin_review(self, directory: Path, raw: Any, *, requested: bool) -> ContextArtifact | None:
        """Reserve entry before provider setup, validating an explicit exact attachment."""
        with self._lock:
            self._busy(directory)
            artifact = None
            if requested:
                artifact = self._attached(
                    directory,
                    _typed(ContextAttachment, raw),
                    same_package=True,
                    conflict="Context attachment changed; inspect it again.",
                )
            self._preparing.add(directory.resolve())
            return artifact

    def begin_recheck(self, directory: Path, recorded: Mapping[str, Any]) -> ContextArtifact:
        """Reserve entry for a waiting review's re-run and reload the context its record names.

        Owner decision 99A: the re-run carries the attachment its waiting record names. A head
        changed since then refuses the re-run before anything in the folder moves.
        """
        with self._lock:
            self._busy(directory)
            artifact = self._attached(
                directory,
                _typed(ContextAttachment, dict(recorded)),
                same_package=False,
                conflict=(
                    "Saved engineering context changed since this review was checked; "
                    "start a new review with the saved context."
                ),
            )
            self._preparing.add(directory.resolve())
            return artifact

    def end_review_preparation(self, directory: Path) -> None:
        with self._lock:
            self._preparing.discard(directory.resolve())

    def validate_prepared_review(
        self, directory: Path, artifact: ContextArtifact, *, same_package: bool = True
    ) -> None:
        """Recheck the saved package immediately before constructing a provider."""
        with self._lock:
            self._attached(
                directory,
                ContextAttachment(
                    context_id=artifact.context_id,
                    head_digest=context_digest(artifact),
                    package_sha256=artifact.baseline.package_sha256,
                ),
                same_package=same_package,
                conflict="Saved context changed; prepare the review again.",
            )


def engineering_context_routes(server: EngineeringContextServer) -> list[Route]:
    prefix = "/engineering-context/{run_id}"
    return [
        Route(prefix, server.inspect, methods=["GET"]),
        Route(prefix + "/init", server.initialize, methods=["POST"]),
        Route(prefix + "/requirement", server.requirement, methods=["POST"]),
        Route(prefix + "/force", server.force, methods=["POST"]),
        Route(prefix + "/confirm", server.confirm, methods=["POST"]),
    ]
