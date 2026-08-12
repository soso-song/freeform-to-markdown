from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from .support import SyntheticSource, build_synthetic_source


@pytest.fixture
def synthetic_source(tmp_path: Path) -> SyntheticSource:
    return build_synthetic_source(tmp_path)


@pytest.fixture
def adverse_source(tmp_path: Path) -> SyntheticSource:
    return build_synthetic_source(tmp_path, include_failures=True)


@pytest.fixture
def unknown_schema_source(tmp_path: Path) -> SyntheticSource:
    return build_synthetic_source(tmp_path, user_version=999)


@pytest.fixture
def wal_source(tmp_path: Path) -> Iterator[SyntheticSource]:
    """Keep a writer open so committed rows remain represented in the WAL."""

    source = build_synthetic_source(tmp_path)
    writer = sqlite3.connect(source.database)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "UPDATE boards SET owner_name = ? WHERE board_identifier = ?",
            ("Committed WAL Owner", source.board_uuid.bytes),
        )
        writer.commit()
        assert source.database.with_name("boards.db-wal").exists()
        yield source
    finally:
        writer.close()
