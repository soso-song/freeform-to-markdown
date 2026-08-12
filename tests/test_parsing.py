from __future__ import annotations

import struct

import pytest

from freeform_to_markdown.parsing import (
    extract_geometry,
    extract_text,
    protobuf_strings,
    read_varint,
)

from .support import encode_varint, geometry_blob, protobuf_bytes, protobuf_text


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        (0, b"\x00"),
        (1, b"\x01"),
        (127, b"\x7f"),
        (128, b"\x80\x01"),
        (300, b"\xac\x02"),
        ((1 << 63) - 1, b"\xff\xff\xff\xff\xff\xff\xff\xff\x7f"),
    ],
)
def test_read_varint(value: int, encoded: bytes) -> None:
    assert encode_varint(value) == encoded
    assert read_varint(encoded, 0) == (value, len(encoded))


@pytest.mark.parametrize("payload", [b"\x80", b"\xff" * 11 + b"\x01"])
def test_read_varint_rejects_truncated_or_oversized_values(payload: bytes) -> None:
    with pytest.raises(ValueError):
        read_varint(payload, 0)


def test_protobuf_strings_recurses_and_preserves_unicode() -> None:
    payload = protobuf_bytes(
        1,
        protobuf_bytes(2, "café 图片".encode()) + protobuf_bytes(3, b"line two"),
    )
    strings = protobuf_strings(payload)
    assert "café 图片" in strings
    assert "line two" in strings


def test_protobuf_strings_recurses_into_nested_crdt_frames() -> None:
    framed = b"crdt\x06\x00\x00\x00" + protobuf_bytes(1, b"nested board text")
    payload = protobuf_bytes(2, framed)
    assert "nested board text" in protobuf_strings(payload)


def test_protobuf_strings_tolerates_unknown_wire_fields() -> None:
    fixed32 = encode_varint((8 << 3) | 5) + struct.pack("<I", 42)
    fixed64 = encode_varint((9 << 3) | 1) + struct.pack("<d", 3.5)
    payload = fixed32 + fixed64 + protobuf_bytes(10, b"visible")
    assert "visible" in protobuf_strings(payload)


def test_corrupt_crdt_blob_is_reported_without_inventing_text() -> None:
    assert protobuf_strings(b"\x0a\xff") == []
    assert extract_text(b"\x0a\xff") == ""


def test_extract_text_deduplicates_nested_crdt_fragments() -> None:
    repeated = protobuf_text("same note", "same note", "second note")
    text = extract_text(repeated)
    assert text.count("same note") == 1
    assert "second note" in text


def test_extract_geometry_reads_v16_point_and_size_pairs() -> None:
    geometry = extract_geometry(geometry_blob(10.0, -20.5, 320.0, 80.0))
    assert geometry is not None
    assert tuple(geometry) == pytest.approx((10.0, -20.5, 320.0, 80.0))


def test_extract_geometry_does_not_guess_from_unrelated_fixed_width_fields() -> None:
    unrelated = b"".join(
        encode_varint((field_number << 3) | 1) + struct.pack("<d", value)
        for field_number, value in enumerate((10.0, 20.0, 30.0, 40.0), start=1)
    )
    assert extract_geometry(unrelated) is None


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        geometry_blob(1.0, 2.0, -1.0, 20.0),
        b"not a protobuf payload",
    ],
)
def test_extract_geometry_returns_none_for_missing_or_invalid_bounds(payload: bytes) -> None:
    assert extract_geometry(payload) is None
