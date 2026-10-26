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

"""Prefix-reusing Context Pack wire protocol for incremental context delivery."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass

from powercontext.errors import PowerContextError

CONTEXT_PACK_SCHEMA = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
CONTEXT_PACK_DEFAULT_CHUNK_BYTES = 512

_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(PowerContextError, ValueError):
    """Raised when a Context Pack or delta violates the wire protocol."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """One complete, independently decodable context payload."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: object, /) -> ContextPack:
        """Build a complete pack from already chunked bytes."""

        chunks = _normalize_items(items)
        digest = _pack_digest(chunks)
        return cls(chunks, digest, _wire_byte_count(chunks, digest))

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = CONTEXT_PACK_DEFAULT_CHUNK_BYTES) -> ContextPack:
        """Chunk text deterministically into bounded, independently valid UTF-8 pieces."""

        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")  # noqa: TRY003
        if isinstance(content, str):
            try:
                raw = content.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ContextPackError("content must be valid UTF-8 text") from error  # noqa: TRY003
        elif isinstance(content, (bytes, bytearray, memoryview)):
            raw = bytes(content)
        else:
            raise ContextPackError("content must be text or UTF-8 bytes")  # noqa: TRY003
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("content must be valid UTF-8 text") from error  # noqa: TRY003
        return cls.build(_chunk_text(text, chunk_bytes))

    def to_bytes(self) -> bytes:
        """Serialize this pack into its canonical UTF-8 wire form."""

        return _serialize_pack(self.items, self.digest, self.byte_count)

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> ContextPack:
        """Decode and fully validate one complete pack."""

        payload = _decode_json_object(raw)
        if set(payload) != _PACK_FIELDS:
            raise ContextPackError("pack payload must contain exactly schema, items, digest and byte_count")  # noqa: TRY003
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("pack schema is not supported")  # noqa: TRY003
        items = _decode_items(payload["items"])
        digest = payload["digest"]
        if not isinstance(digest, str):
            raise ContextPackError("pack digest must be a string")  # noqa: TRY003
        expected = _pack_digest(items)
        if digest != expected:
            raise ContextPackError("pack digest does not match its items")  # noqa: TRY003
        byte_count = payload["byte_count"]
        if type(byte_count) is not int or byte_count != len(raw):
            raise ContextPackError("pack byte_count does not match its wire bytes")  # noqa: TRY003
        return cls(items, digest, byte_count)


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """One prefix-reusing delta that reconstructs a target pack from a base pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @property
    def byte_count(self) -> int:
        """Return the exact wire size of this delta."""

        return len(self.to_bytes())

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        """Build a delta from any valid common prefix and the target suffix."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta endpoints must be complete Context Packs")  # noqa: TRY003
        prefix_items = _common_prefix_length(base.items, target.items)
        return cls(base.digest, target.digest, prefix_items, target.items[prefix_items:])

    def to_bytes(self) -> bytes:
        """Serialize this delta into its canonical UTF-8 wire form."""

        payload = {
            "appended": [base64.b64encode(item).decode("ascii") for item in self.appended],
            "base_digest": self.base_digest,
            "prefix_items": self.prefix_items,
            "schema": CONTEXT_PACK_DELTA_SCHEMA,
            "target_digest": self.target_digest,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes, /) -> ContextPackDelta:
        """Decode and validate one delta payload without requiring its base."""

        payload = _decode_json_object(raw)
        if set(payload) != _DELTA_FIELDS:
            raise ContextPackError("delta payload must contain exactly the protocol fields")  # noqa: TRY003
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("delta schema is not supported")  # noqa: TRY003
        base_digest = payload["base_digest"]
        target_digest = payload["target_digest"]
        if not isinstance(base_digest, str) or not isinstance(target_digest, str):
            raise ContextPackError("delta digests must be strings")  # noqa: TRY003
        prefix_items = payload["prefix_items"]
        if type(prefix_items) is not int or prefix_items < 0:
            raise ContextPackError("delta prefix_items must be a non-negative integer")  # noqa: TRY003
        appended = _decode_items(payload["appended"])
        return cls(base_digest, target_digest, prefix_items, appended)


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Reconstruct and verify the target pack from a base pack and one delta."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta application requires a pack and a delta")  # noqa: TRY003
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the base pack")  # noqa: TRY003
    prefix_items = delta.prefix_items
    if type(prefix_items) is not int or prefix_items < 0 or prefix_items > len(base.items):
        raise ContextPackError("delta prefix_items is outside the base pack")  # noqa: TRY003
    appended = _normalize_items(delta.appended)
    target = ContextPack.build((*base.items[:prefix_items], *appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")  # noqa: TRY003
    return target


def _normalize_items(items: object) -> tuple[bytes, ...]:
    if isinstance(items, (str, bytes, bytearray, memoryview)):
        raise ContextPackError("pack items must be an iterable of bytes chunks")  # noqa: TRY003
    try:
        values = tuple(items)  # type: ignore[arg-type]
    except TypeError as error:
        raise ContextPackError("pack items must be an iterable of bytes chunks") from error  # noqa: TRY003
    chunks: list[bytes] = []
    for item in values:
        if not isinstance(item, (bytes, bytearray, memoryview)):
            raise ContextPackError("every pack item must be bytes")  # noqa: TRY003
        chunks.append(bytes(item))
    return tuple(chunks)


def _chunk_text(text: str, chunk_bytes: int) -> tuple[bytes, ...]:
    chunks: list[bytes] = []
    current = bytearray()
    for character in text:
        encoded = character.encode("utf-8")
        if len(encoded) > chunk_bytes:
            raise ContextPackError("chunk_bytes is too small for one UTF-8 character")  # noqa: TRY003
        if len(current) + len(encoded) > chunk_bytes:
            chunks.append(bytes(current))
            current = bytearray()
        current.extend(encoded)
    if current:
        chunks.append(bytes(current))
    return tuple(chunks)


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {
        "items": [base64.b64encode(item).decode("ascii") for item in items],
        "schema": CONTEXT_PACK_SCHEMA,
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _serialize_pack(items: tuple[bytes, ...], digest: str, byte_count: int) -> bytes:
    payload = {
        "byte_count": byte_count,
        "digest": digest,
        "items": [base64.b64encode(item).decode("ascii") for item in items],
        "schema": CONTEXT_PACK_SCHEMA,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _wire_byte_count(items: tuple[bytes, ...], digest: str) -> int:
    size = 0
    for _ in range(8):
        new_size = len(_serialize_pack(items, digest, size))
        if new_size == size:
            return size
        size = new_size
    raise ContextPackError("pack byte_count did not converge")  # noqa: TRY003


def _common_prefix_length(base: tuple[bytes, ...], target: tuple[bytes, ...]) -> int:
    length = 0
    for base_item, target_item in zip(base, target, strict=False):
        if base_item != target_item:
            break
        length += 1
    return length


def _decode_json_object(raw: bytes) -> dict[str, object]:
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ContextPackError("wire payload must be UTF-8 bytes")  # noqa: TRY003
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContextPackError("wire payload must be valid UTF-8") from error  # noqa: TRY003
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise ContextPackError("wire payload must be valid JSON") from error  # noqa: TRY003
    if not isinstance(payload, dict):
        raise ContextPackError("wire payload must be a JSON object")  # noqa: TRY003
    return payload


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("wire items must be an array of Base64 strings")  # noqa: TRY003
    items: list[bytes] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ContextPackError("wire items must be Base64 strings")  # noqa: TRY003
        try:
            items.append(base64.b64decode(entry, validate=True))
        except (binascii.Error, ValueError) as error:
            raise ContextPackError("wire items must be valid Base64") from error  # noqa: TRY003
    return tuple(items)


__all__ = [
    "CONTEXT_PACK_DEFAULT_CHUNK_BYTES",
    "CONTEXT_PACK_DELTA_SCHEMA",
    "CONTEXT_PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
