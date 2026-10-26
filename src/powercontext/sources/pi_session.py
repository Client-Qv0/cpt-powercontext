# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Capture the selected Pi session branch as immutable event evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    SourceDefinition,
    TextEvidence,
)
from powercontext.sources.models import Source, SourceMaterialization

PI_EVENT_SOURCE_NAME = "pi-event"
PI_EVENT_SOURCE_VERSION = "1"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_CONNECTOR_VERSION = "1"
PI_SESSION_VERSION = 3
PI_EVENT_IDENTITY_PREFIX = "pi"

_NonEmptyText = Annotated[str, Field(min_length=1)]
_CONTROL_EVENT_TYPES = frozenset({"session", "model_change", "thinking_level_change"})


class PiSessionInput(BaseModel):
    """One Pi JSONL archive and the branch leaf to capture."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch together with its raw record."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Captured Pi event evidence that keeps the complete original record."""

    source_id: _NonEmptyText
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def parse_pi_session(value: PiSessionInput, /) -> tuple[PiEventInput, ...]:
    """Parse one archive and return the visible events of the selected branch."""

    header, records = _read_archive(value.content)
    session_id = header
    nodes = _build_nodes(records)
    leaf = _select_leaf(nodes, value.leaf_id)
    branch = _ancestor_chain(nodes, leaf)

    events: list[PiEventInput] = []
    for event_id in branch:
        record = nodes[event_id][1]
        visible = _visible_event(record, session_id, event_id)
        if visible is not None:
            events.append(visible)
    return tuple(events)


class PiSessionConnector:
    """Import the not-yet-captured visible events of one Pi session file."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_SESSION_CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = parse_pi_session(PiSessionInput(content=self._path.read_bytes(), leaf_id=self._leaf_id))
        imported = _checkpoint_events(session.checkpoint)
        pending: list[tuple[PiEventInput, str]] = []
        for event in events:
            digest = _record_digest(event.record)
            captured = imported.get(event.event_id)
            if captured is None:
                pending.append((event, digest))
            elif captured != digest:
                raise ValueError(f"imported Pi event {event.event_id!r} was rewritten")  # noqa: TRY003
        for event, digest in pending:
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            imported[event.event_id] = digest
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"events": dict(imported)},
        )


class PiEventSourceAdapter:
    """Resolve and read one captured Pi event."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one captured event as standard text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


def pi_event_source_id(session_id: str, event_id: str, /) -> str:
    """Build the stable identity shared by every captured event of one session."""

    for field, value in (("session_id", session_id), ("event_id", event_id)):
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{field} must be a non-empty trimmed string")  # noqa: TRY003
    source_id = f"{PI_EVENT_IDENTITY_PREFIX}:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(  # noqa: TRY003
            f"pi event identity must not exceed {MAX_SOURCE_ID_LENGTH} characters, got {len(source_id)}"
        )
    return source_id


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    version=PI_EVENT_SOURCE_VERSION,
    projections=(PiEventTextEvidenceProjection(),),
)


def _read_archive(content: bytes, /) -> tuple[str, list[dict[str, Any]]]:
    text = content.decode("utf-8-sig")
    rows: list[Any] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid Pi session JSON: {error.msg}") from error  # noqa: TRY003
    if not rows:
        raise ValueError("Pi session archive must not be empty")  # noqa: TRY003
    header = rows[0]
    if not isinstance(header, dict) or header.get("type") != "session":
        raise ValueError("first Pi session record must declare type=session")  # noqa: TRY003
    if header.get("version") != PI_SESSION_VERSION:
        raise ValueError(f"Pi session version must be {PI_SESSION_VERSION}")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session id must be a non-empty string")  # noqa: TRY003
    records: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not isinstance(row, dict):
            raise ValueError("Pi session records must be JSON objects")  # noqa: TRY003, TRY004
        records.append(row)
    return session_id.strip(), records


def _build_nodes(records: list[dict[str, Any]], /) -> dict[str, tuple[str | None, Any]]:
    nodes: dict[str, tuple[str | None, Any]] = {}
    for record in records:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Pi session record id must be a non-empty string")  # noqa: TRY003
        if event_id in nodes:
            raise ValueError(f"duplicate Pi session record id {event_id!r}")  # noqa: TRY003
        if "parentId" not in record:
            raise ValueError(f"Pi session record {event_id!r} must declare parentId")  # noqa: TRY003
        parent_id = record["parentId"]
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in nodes):
            raise ValueError(f"Pi session record {event_id!r} has an unknown parent")  # noqa: TRY003
        nodes[event_id] = (parent_id, record)
    return nodes


def _select_leaf(nodes: dict[str, tuple[str | None, Any]], leaf_id: str | None, /) -> str:
    if leaf_id is None:
        if not nodes:
            raise ValueError("Pi session archive has no records to select as leaf")  # noqa: TRY003
        return next(reversed(nodes))
    if leaf_id not in nodes:
        raise ValueError(f"Pi session leaf {leaf_id!r} does not exist")  # noqa: TRY003
    return leaf_id


def _ancestor_chain(nodes: dict[str, tuple[str | None, Any]], leaf: str, /) -> list[str]:
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = leaf
    while current is not None:
        if current in seen:
            raise ValueError(f"Pi session graph contains a cycle at {current!r}")  # noqa: TRY003
        seen.add(current)
        chain.append(current)
        current = nodes[current][0]
    chain.reverse()
    return chain


def _visible_event(record: dict[str, Any], session_id: str, event_id: str, /) -> PiEventInput | None:
    event_type = record.get("type")
    if not isinstance(event_type, str):
        raise ValueError(f"Pi session record {event_id!r} must declare a type")  # noqa: TRY003, TRY004
    if event_type in _CONTROL_EVENT_TYPES:
        return None
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError(f"Pi message record {event_id!r} must contain a message")  # noqa: TRY003
        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"Pi message record {event_id!r} must declare a role")  # noqa: TRY003
        body = _message_body(role, message)
    elif event_type in {"compaction", "branch_summary"}:
        role = event_type
        summary = record.get("summary")
        body = summary if isinstance(summary, str) else None
    elif event_type == "custom_message":
        role = "custom"
        body = _text_blocks(record.get("content"))
    else:
        return None
    if body is None or not body.strip():
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=event_id,
        parent_id=record.get("parentId"),
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _message_body(role: str, message: dict[str, Any], /) -> str | None:
    if role == "toolResult":
        header = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}]"
        text = _text_blocks(message.get("content"))
        return f"{header} {text}" if text else header
    if role == "bashExecution":
        command = message.get("command")
        if not isinstance(command, str) or not command:
            return None
        body = f"$ {command}"
        output = message.get("output")
        if isinstance(output, str) and output:
            body = f"{body}\n{output}"
        return body
    content = message.get("content")
    if isinstance(content, str):
        return content
    return _text_blocks(content)


def _text_blocks(content: object, /) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block_type == "toolCall":
            name = block.get("name", "")
            call_id = block.get("id", "")
            arguments = block.get("arguments", {})
            encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            parts.append(f"[tool_call {name} {call_id}] {encoded}")
    if not parts:
        return None
    return "\n".join(parts)


def _checkpoint_events(checkpoint: JsonValue | None, /) -> dict[str, str]:
    if checkpoint is None:
        return {}
    if not isinstance(checkpoint, dict):
        raise ValueError("Pi session checkpoint must be a JSON object")  # noqa: TRY003, TRY004
    events = checkpoint.get("events", {})
    if not isinstance(events, dict):
        raise ValueError("Pi session checkpoint events must be a JSON object")  # noqa: TRY003, TRY004
    imported: dict[str, str] = {}
    for event_id, digest in events.items():
        if not isinstance(event_id, str) or not isinstance(digest, str):
            raise ValueError("Pi session checkpoint entries must be strings")  # noqa: TRY003, TRY004
        imported[event_id] = digest
    return imported


def _record_digest(record: dict[str, JsonValue], /) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
