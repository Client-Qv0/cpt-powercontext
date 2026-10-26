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

"""Self-describing context packs and the deltas that rebuild them."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, NoReturn

CONTEXT_PACK_SCHEMA = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
CONTEXT_PACK_CHUNK_BYTES = 512
_DIGEST_PREFIX = "sha256:"


class ContextPackError(ValueError):
    """Raised when a context pack or delta cannot be trusted."""


def _fail(message: str, /) -> NoReturn:
    raise ContextPackError(message)


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One immutable, digest-addressed sequence of UTF-8 content items."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...], /) -> ContextPack:
        encoded = [_encode(item) for item in items]
        digest = _digest(encoded)
        byte_count = 0
        while True:
            raw = _pack_bytes(encoded, digest, byte_count)
            if len(raw) == byte_count:
                return cls(tuple(items), digest, byte_count)
            byte_count = len(raw)

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> ContextPack:
        payload = _load_object(raw, "context pack")
        if set(payload) != {"schema", "items", "digest", "byte_count"}:
            _fail("context pack must declare exactly schema, items, digest and byte_count")
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            _fail(f"unsupported context pack schema {payload['schema']!r}")
        encoded = _decode_items(payload["items"])
        digest = payload["digest"]
        if not isinstance(digest, str):
            _fail("context pack digest must be a string")
        if digest != _digest(encoded):
            _fail("context pack digest does not match its items")
        byte_count = payload["byte_count"]
        if not _is_int(byte_count) or byte_count < 0:
            _fail("context pack byte_count must be a non-negative integer")
        if byte_count != len(raw):
            _fail("context pack byte_count does not match its encoding")
        return cls(tuple(base64.b64decode(value) for value in encoded), digest, byte_count)

    @classmethod
    def from_content(cls, content: str, /, *, chunk_bytes: int = CONTEXT_PACK_CHUNK_BYTES) -> ContextPack:
        if not _is_int(chunk_bytes) or chunk_bytes < 1:
            _fail("chunk_bytes must be a positive integer")
        return cls.build(_chunk_utf8(content, chunk_bytes))

    def to_bytes(self) -> bytes:
        return _pack_bytes([_encode(item) for item in self.items], self.digest, self.byte_count)


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """The shared prefix and appended tail that rebuild one pack from another."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        prefix = _common_prefix(base.items, target.items)
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> ContextPackDelta:
        payload = _load_object(raw, "context pack delta")
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            _fail("context pack delta must declare exactly its five fields")
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            _fail(f"unsupported context pack delta schema {payload['schema']!r}")
        base_digest = payload["base_digest"]
        target_digest = payload["target_digest"]
        if not isinstance(base_digest, str) or not isinstance(target_digest, str):
            _fail("context pack delta digests must be strings")
        prefix_items = payload["prefix_items"]
        if not _is_int(prefix_items) or prefix_items < 0:
            _fail("context pack delta prefix_items must be a non-negative integer")
        appended = tuple(base64.b64decode(value) for value in _decode_items(payload["appended"]))
        return cls(base_digest, target_digest, prefix_items, appended)

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        payload = {
            "schema": CONTEXT_PACK_DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": [_encode(item) for item in self.appended],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Rebuild the target pack, rejecting any delta that does not reproduce it."""

    if not _is_int(delta.prefix_items) or delta.prefix_items < 0:
        _fail("context pack delta prefix_items must be a non-negative integer")
    if delta.base_digest != base.digest:
        _fail("context pack delta was built for a different base pack")
    if delta.prefix_items > len(base.items):
        _fail("context pack delta prefix exceeds the base pack")
    rebuilt = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if rebuilt.digest != delta.target_digest:
        _fail("context pack delta does not rebuild its target digest")
    return rebuilt


def pack_for_content(content: str, /, *, chunk_bytes: int = CONTEXT_PACK_CHUNK_BYTES) -> ContextPack:
    return ContextPack.from_content(content, chunk_bytes=chunk_bytes)


def _pack_bytes(encoded: list[str], digest: str, byte_count: int, /) -> bytes:
    payload = {
        "schema": CONTEXT_PACK_SCHEMA,
        "items": encoded,
        "digest": digest,
        "byte_count": byte_count,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _digest(encoded: list[str], /) -> str:
    canonical = json.dumps(
        {"schema": CONTEXT_PACK_SCHEMA, "items": encoded},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"{_DIGEST_PREFIX}{hashlib.sha256(canonical).hexdigest()}"


def _encode(item: bytes, /) -> str:
    return base64.b64encode(item).decode("ascii")


def _decode_items(values: Any, /) -> list[str]:
    if not isinstance(values, list):
        _fail("context pack items must be a list")
    encoded: list[str] = []
    for value in values:
        if not isinstance(value, str):
            _fail("context pack items must be base64 strings")
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ContextPackError(f"context pack item is not valid base64: {error}") from error  # noqa: TRY003
        encoded.append(value)
    return encoded


def _load_object(raw: bytes, kind: str, /) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ContextPackError(f"{kind} is not JSON: {error}") from error  # noqa: TRY003
    if not isinstance(payload, dict):
        _fail(f"{kind} must be a JSON object")
    return payload


def _common_prefix(left: tuple[bytes, ...], right: tuple[bytes, ...], /) -> int:
    prefix = 0
    for first, second in zip(left, right, strict=False):
        if first != second:
            break
        prefix += 1
    return prefix


def _chunk_utf8(content: str, chunk_bytes: int, /) -> tuple[bytes, ...]:
    chunks: list[bytes] = []
    buffer: list[str] = []
    buffered = 0
    for character in content:
        size = len(character.encode("utf-8"))
        if size > chunk_bytes:
            _fail("chunk_bytes cannot hold one UTF-8 character")
        if buffered + size > chunk_bytes:
            chunks.append("".join(buffer).encode("utf-8"))
            buffer = []
            buffered = 0
        buffer.append(character)
        buffered += size
    if buffer:
        chunks.append("".join(buffer).encode("utf-8"))
    return tuple(chunks)


def _is_int(value: object, /) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "CONTEXT_PACK_CHUNK_BYTES",
    "CONTEXT_PACK_DELTA_SCHEMA",
    "CONTEXT_PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
    "pack_for_content",
]
