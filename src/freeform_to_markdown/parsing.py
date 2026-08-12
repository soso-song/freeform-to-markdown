"""Small, dependency-free parsers for Freeform v16 protobuf/CRDT fragments."""

from __future__ import annotations

import re
import struct

from .models import Geometry

_STYLE_WORDS = {
    "basewritingdirection",
    "bold",
    "characterfill",
    "crdt",
    "fontname",
    "fontsize",
    "italic",
    "left",
    "link",
    "listend",
    "listlevel",
    "liststart",
    "liststyle",
    "listtype",
    "paragraphalignment",
    "paragraphlevel",
    "regular",
    "semibold",
    "strikethrough",
    "textcolor",
    "underline",
    "verticalalignment",
}
_PAIR = re.compile(b"\\x22\\x0a\\x0d(.{4})\\x15(.{4})", re.DOTALL)
_CRDT_HEADER_SIZE = 8


def read_varint(blob: bytes, offset: int) -> tuple[int, int]:
    """Read one unsigned protobuf varint, rejecting truncation and >64-bit input."""

    result = 0
    shift = 0
    for _ in range(10):
        if offset >= len(blob):
            raise ValueError("unterminated varint")
        byte = blob[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise ValueError("varint exceeds 64 bits")
        result |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return result, offset
        shift += 7
    raise ValueError("varint exceeds 64 bits")


def _is_message(blob: bytes) -> bool:
    if not blob:
        return False
    offset = 0
    fields = 0
    try:
        while offset < len(blob):
            tag, offset = read_varint(blob, offset)
            if tag == 0:
                return False
            wire = tag & 7
            if wire == 0:
                _, offset = read_varint(blob, offset)
            elif wire == 1:
                offset += 8
            elif wire == 2:
                length, offset = read_varint(blob, offset)
                offset += length
            elif wire == 5:
                offset += 4
            else:
                return False
            if offset > len(blob):
                return False
            fields += 1
    except (IndexError, ValueError):
        return False
    return fields > 0


def is_well_formed_protobuf(blob: bytes | None) -> bool:
    """Return whether a non-empty CRDT/protobuf payload can be traversed safely."""

    if not blob:
        return True
    body = (
        blob[_CRDT_HEADER_SIZE:]
        if blob.startswith(b"crdt") and len(blob) >= _CRDT_HEADER_SIZE
        else blob
    )
    return _is_message(body)


def protobuf_strings(
    blob: bytes | None,
    *,
    _depth: int = 0,
    _output: list[str] | None = None,
) -> list[str]:
    """Recursively extract UTF-8 leaves without pretending corrupt bytes are prose."""

    output = [] if _output is None else _output
    if not blob:
        return output
    body = (
        blob[_CRDT_HEADER_SIZE:]
        if blob.startswith(b"crdt") and len(blob) >= _CRDT_HEADER_SIZE
        else blob
    )
    offset = 0
    while offset < len(body):
        try:
            tag, offset = read_varint(body, offset)
            if tag == 0:
                return output
            wire = tag & 7
            if wire == 0:
                _, offset = read_varint(body, offset)
            elif wire == 1:
                offset += 8
            elif wire == 5:
                offset += 4
            elif wire == 2:
                length, offset = read_varint(body, offset)
                end = offset + length
                if end > len(body):
                    return output
                chunk = body[offset:end]
                offset = end
                if _depth < 8 and (chunk.startswith(b"crdt") or _is_message(chunk)):
                    protobuf_strings(chunk, _depth=_depth + 1, _output=output)
                else:
                    try:
                        value = chunk.decode("utf-8").strip()
                    except UnicodeDecodeError:
                        continue
                    if value:
                        output.append(value)
            else:
                return output
            if offset > len(body):
                return output
        except (IndexError, ValueError):
            return output
    return output


def extract_text(blob: bytes | None) -> str:
    """Extract de-duplicated user-looking text from a Freeform payload."""

    result: list[str] = []
    seen: set[str] = set()
    for candidate in protobuf_strings(blob):
        value = re.sub(r"[\x00-\x1f]+", " ", candidate).strip()
        if (
            not value
            or value.casefold() in _STYLE_WORDS
            or value.startswith(("com.apple", "&com", "public."))
        ):
            continue
        has_cjk = re.search(r"[\u3400-\u9fff]", value) is not None
        if not has_cjk and len(re.findall(r"[A-Za-z0-9]", value)) < 2:
            continue
        if re.fullmatch(r"[A-Za-z ]{1,3}", value) and " " in value:
            continue
        if value not in seen:
            result.append(value)
            seen.add(value)
    return "\n".join(result)


def extract_geometry(blob: bytes | None) -> Geometry | None:
    """Extract the position and size pairs observed in schema-v16 common_data."""

    if not blob:
        return None
    pairs = [
        (struct.unpack("<f", first)[0], struct.unpack("<f", second)[0])
        for first, second in _PAIR.findall(blob)
    ]
    if len(pairs) < 2:
        return None
    x, y = pairs[0]
    width, height = pairs[1]
    values = (x, y, width, height)
    if not all(float("-inf") < value < float("inf") for value in values):
        return None
    if width <= 0 or height <= 0:
        return None
    return Geometry(x, y, width, height)
