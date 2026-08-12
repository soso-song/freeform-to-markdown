"""Typed records shared by the Freeform reader and archive writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple


class Geometry(NamedTuple):
    """An axis-aligned board item rectangle."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class DoctorReport:
    schema_version: int
    schema_fingerprint: str
    supported: bool
    database_readable: bool
    assets_readable: bool
    ocr_available: bool
    schema_status: str = "unsupported"
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoardSummary:
    board_id: str
    title: str
    object_count: int
    asset_reference_count: int
    last_activity_time: float | None


@dataclass(frozen=True)
class BoardObject:
    object_id: str
    parent_id: str | None
    item_type: int
    sub_item_type: int | None
    common_data: bytes
    specific_data: bytes
    text: str
    geometry: Geometry | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetReference:
    object_id: str
    asset_id: str
    role: str
    original_name: str
    extension: str
    source_path: Path | None


@dataclass(frozen=True)
class BoardData:
    board_id: str
    title: str
    objects: tuple[BoardObject, ...]
    asset_references: tuple[AssetReference, ...]
    tombstoned_object_count: int
    schema_version: int
    schema_fingerprint: str
    last_activity_time: float | None = None


@dataclass(frozen=True)
class Scene:
    scene_id: str
    title: str
    object_ids: tuple[str, ...]


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    object_count: int = 0
    unresolved_count: int = 0
    accepted_unresolved_count: int = 0
    unreviewed_count: int = 0
    broken_link_count: int = 0
    checksum_failure_count: int = 0
    privacy_failure_count: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def privacy_finding_count(self) -> int:
        return self.privacy_failure_count
