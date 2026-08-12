"""Builders for privacy-safe, from-scratch Freeform test inputs.

Nothing in this module is copied from a Freeform database.  The identifiers,
protobuf fragments, image bytes, URLs, and credentials are deliberately fake.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

BOARD_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000101")
TEXT_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000201")
IMAGE_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000202")
DUPLICATE_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000203")
SHAPE_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000204")
NO_COORDS_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000205")
TOMBSTONE_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000206")
CORRUPT_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000207")
MISSING_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000208")
GROUP_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000209")
ASSET_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000301")
DUPLICATE_ASSET_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000302")
MISSING_ASSET_UUID: Final = uuid.UUID("00000000-0000-4000-8000-000000000399")

BOARD_TITLE: Final = "Synthetic 研究 Board"
PUBLIC_NOTE: Final = "Launch checklist — café and 图片"
FAKE_SECRET: Final = "synthetic-token-not-real"
FAKE_PRIVATE_URL: Final = "https://private.invalid/session?token=synthetic-token-not-real"
PNG_BYTES: Final = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def encode_varint(value: int) -> bytes:
    """Encode a non-negative integer using protobuf varint encoding."""

    if value < 0:
        raise ValueError("varints in synthetic fixtures must be non-negative")
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def protobuf_bytes(field_number: int, value: bytes) -> bytes:
    """Build a length-delimited protobuf field without generated classes."""

    key = encode_varint((field_number << 3) | 2)
    return key + encode_varint(len(value)) + value


def protobuf_text(*values: str) -> bytes:
    """Build nested string fields similar to text found in CRDT payloads."""

    fields = b"".join(
        protobuf_bytes(index + 1, value.encode()) for index, value in enumerate(values)
    )
    return protobuf_bytes(1, fields)


def geometry_blob(x: float, y: float, width: float, height: float) -> bytes:
    """Create a synthetic fragment shaped like Freeform v16 point/size pairs."""

    return b"".join(
        b"\x22\x0a\x0d" + struct.pack("<f", first) + b"\x15" + struct.pack("<f", second)
        for first, second in ((x, y), (width, height))
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> dict[str, str]:
    """Hash every regular source file, excluding transient SQLite sidecars."""

    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith("-shm")
    }


@dataclass(frozen=True)
class SyntheticSource:
    root: Path
    database: Path
    assets: Path
    board_uuid: uuid.UUID = BOARD_UUID


def _schema(connection: sqlite3.Connection, user_version: int) -> None:
    connection.executescript(
        f"""
        PRAGMA user_version={user_version};
        CREATE TABLE boards (
            board_identifier BLOB PRIMARY KEY,
            owner_name TEXT,
            container_uuid BLOB,
            alternate_container_uuid BLOB,
            data BLOB,
            last_activity_time REAL,
            tombstoned INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE board_items (
            item_uuid BLOB PRIMARY KEY,
            parent_uuid BLOB,
            board_identifier BLOB NOT NULL,
            item_type INTEGER NOT NULL,
            common_data BLOB,
            specific_data BLOB,
            tombstoned INTEGER NOT NULL DEFAULT 0,
            sub_item_type INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE asset_references (
            referrer_identifier BLOB NOT NULL,
            board_identifier BLOB NOT NULL,
            referrer_asset_name TEXT,
            asset_uuid BLOB NOT NULL,
            referrer_type INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE assets (
            asset_uuid BLOB PRIMARY KEY,
            extension TEXT,
            tombstone_date REAL
        );
        """
    )


def build_synthetic_source(
    root: Path,
    *,
    user_version: int = 16,
    include_failures: bool = False,
    use_wal: bool = False,
) -> SyntheticSource:
    """Build a minimal Freeform-shaped source entirely from synthetic values."""

    source_root = root / "synthetic-freeform"
    assets_root = source_root / "Assets"
    assets_root.mkdir(parents=True)
    database = source_root / "boards.db"

    connection = sqlite3.connect(database)
    try:
        if use_wal:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
        _schema(connection, user_version)
        connection.execute(
            "INSERT INTO boards VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                BOARD_UUID.bytes,
                "Fixture Owner",
                uuid.UUID("00000000-0000-4000-8000-000000000111").bytes,
                None,
                protobuf_text(BOARD_TITLE),
                12345.0,
                0,
            ),
        )

        items = [
            (
                TEXT_UUID.bytes,
                None,
                BOARD_UUID.bytes,
                3,
                geometry_blob(10.0, 20.0, 320.0, 80.0),
                protobuf_text(PUBLIC_NOTE, f"token={FAKE_SECRET}", FAKE_PRIVATE_URL),
                0,
                0,
            ),
            (
                IMAGE_UUID.bytes,
                None,
                BOARD_UUID.bytes,
                5,
                geometry_blob(20.0, 140.0, 200.0, 120.0),
                protobuf_text("Primary synthetic image"),
                0,
                0,
            ),
            (
                DUPLICATE_UUID.bytes,
                IMAGE_UUID.bytes,
                BOARD_UUID.bytes,
                5,
                geometry_blob(240.0, 140.0, 200.0, 120.0),
                protobuf_text("Duplicate image bytes"),
                0,
                0,
            ),
            (
                SHAPE_UUID.bytes,
                None,
                BOARD_UUID.bytes,
                0,
                geometry_blob(800.0, 900.0, 100.0, 100.0),
                protobuf_text("Decorative divider"),
                0,
                0,
            ),
            (
                GROUP_UUID.bytes,
                None,
                BOARD_UUID.bytes,
                2,
                geometry_blob(0.0, 0.0, 480.0, 300.0),
                protobuf_text("Synthetic group"),
                0,
                0,
            ),
            (
                NO_COORDS_UUID.bytes,
                GROUP_UUID.bytes,
                BOARD_UUID.bytes,
                3,
                b"",
                protobuf_text("Fallback child without coordinates"),
                0,
                0,
            ),
            (
                TOMBSTONE_UUID.bytes,
                None,
                BOARD_UUID.bytes,
                3,
                geometry_blob(0.0, 0.0, 10.0, 10.0),
                protobuf_text("Deleted object must never be archived"),
                1,
                0,
            ),
        ]
        if include_failures:
            items.extend(
                [
                    (
                        CORRUPT_UUID.bytes,
                        None,
                        BOARD_UUID.bytes,
                        3,
                        geometry_blob(500.0, 500.0, 10.0, 10.0),
                        b"\x0a\xff",
                        0,
                        0,
                    ),
                    (
                        MISSING_UUID.bytes,
                        None,
                        BOARD_UUID.bytes,
                        5,
                        geometry_blob(520.0, 500.0, 10.0, 10.0),
                        protobuf_text("Missing synthetic attachment"),
                        0,
                        0,
                    ),
                ]
            )
        connection.executemany("INSERT INTO board_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", items)

        references = [
            (
                IMAGE_UUID.bytes,
                BOARD_UUID.bytes,
                "研究 图片 (final).png",
                ASSET_UUID.bytes,
                0,
            ),
            (
                DUPLICATE_UUID.bytes,
                BOARD_UUID.bytes,
                "duplicate.png",
                DUPLICATE_ASSET_UUID.bytes,
                0,
            ),
        ]
        if include_failures:
            references.append(
                (
                    MISSING_UUID.bytes,
                    BOARD_UUID.bytes,
                    "missing.png",
                    MISSING_ASSET_UUID.bytes,
                    0,
                )
            )
        connection.executemany("INSERT INTO asset_references VALUES (?, ?, ?, ?, ?)", references)
        connection.executemany(
            "INSERT INTO assets VALUES (?, ?, ?)",
            [
                (ASSET_UUID.bytes, "png", None),
                (DUPLICATE_ASSET_UUID.bytes, "png", None),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    # Place equivalent synthetic files in the two layouts adapters commonly see.
    # This deliberately tests lookup without relying on a real application's layout.
    for asset_uuid, label in (
        (ASSET_UUID, "primary"),
        (DUPLICATE_ASSET_UUID, "duplicate"),
    ):
        (assets_root / f"{asset_uuid}.png").write_bytes(PNG_BYTES)
        bundle = assets_root / str(asset_uuid).upper()
        bundle.mkdir()
        (bundle / f"{label}.png").write_bytes(PNG_BYTES)

    # Human-readable provenance makes accidental replacement with real data obvious.
    (source_root / "SYNTHETIC_FIXTURE.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "schema_user_version": user_version,
                "contains_real_user_data": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return SyntheticSource(root=source_root, database=database, assets=assets_root)
