from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from freeform_to_markdown.source import FreeformSource, UnsupportedSchemaError

from .support import (
    BOARD_TITLE,
    BOARD_UUID,
    TOMBSTONE_UUID,
    SyntheticSource,
    tree_digest,
)


def _source(bundle: SyntheticSource) -> FreeformSource:
    return FreeformSource(db_path=bundle.database, assets_path=bundle.assets)


def test_doctor_recognizes_supported_synthetic_v16(synthetic_source: SyntheticSource) -> None:
    report = _source(synthetic_source).doctor()
    assert report.schema_version == 16
    assert report.supported is True
    assert report.database_readable is True
    assert report.assets_readable is True
    assert not report.errors


def test_list_boards_reads_title_identifier_and_counts_active_objects(
    synthetic_source: SyntheticSource,
) -> None:
    boards = _source(synthetic_source).list_boards()
    assert len(boards) == 1
    board = boards[0]
    assert board.title == BOARD_TITLE
    assert board.board_id == str(BOARD_UUID)
    assert board.object_count == 6
    assert board.asset_reference_count == 2


@pytest.mark.parametrize("selector", [str(BOARD_UUID), BOARD_TITLE])
def test_load_board_supports_id_and_exact_title(
    synthetic_source: SyntheticSource, selector: str
) -> None:
    board = _source(synthetic_source).load_board(selector)
    assert board.board_id == str(BOARD_UUID)
    assert board.title == BOARD_TITLE
    assert len(board.objects) == 6
    assert {item.object_id for item in board.objects}.isdisjoint({str(TOMBSTONE_UUID)})
    assert len(board.asset_references) == 2


def test_uuid_blobs_become_canonical_lowercase_strings(synthetic_source: SyntheticSource) -> None:
    board = _source(synthetic_source).load_board(BOARD_TITLE)
    identifiers = {item.object_id for item in board.objects}
    assert all(identifier == identifier.lower() for identifier in identifiers)
    assert all(len(identifier) == 36 for identifier in identifiers)


def test_unknown_schema_is_diagnosed_and_fails_closed(
    unknown_schema_source: SyntheticSource,
) -> None:
    source = _source(unknown_schema_source)
    report = source.doctor()
    assert report.schema_version == 999
    assert report.supported is False
    with pytest.raises(UnsupportedSchemaError, match="999"):
        source.list_boards()
    with pytest.raises(UnsupportedSchemaError, match="999"):
        source.load_board(BOARD_TITLE)


def test_unrecognized_v16_fingerprint_requires_explicit_opt_in(
    synthetic_source: SyntheticSource,
) -> None:
    connection = sqlite3.connect(synthetic_source.database)
    try:
        connection.execute("ALTER TABLE boards ADD COLUMN future_field TEXT")
        connection.commit()
    finally:
        connection.close()

    source = _source(synthetic_source)
    report = source.doctor()
    assert report.schema_status == "unsupported"
    assert any("unrecognized" in error.lower() for error in report.errors)
    with pytest.raises(UnsupportedSchemaError, match="unrecognized"):
        source.list_boards()

    experimental = FreeformSource(
        db_path=synthetic_source.database,
        assets_path=synthetic_source.assets,
        allow_experimental_schema=True,
    )
    report = experimental.doctor()
    assert report.supported is True
    assert report.schema_status == "experimental"
    assert report.warnings
    assert experimental.list_boards()[0].title == BOARD_TITLE


def test_asset_symlink_outside_source_root_is_not_followed(
    synthetic_source: SyntheticSource, tmp_path: Path
) -> None:
    board = _source(synthetic_source).load_board(BOARD_TITLE)
    original = next(reference for reference in board.asset_references if reference.source_path)
    assert original.source_path is not None
    asset_id = original.asset_id
    outside = tmp_path / "outside.png"
    outside.write_bytes(original.source_path.read_bytes())
    direct = synthetic_source.assets / f"{asset_id}.png"
    bundled = synthetic_source.assets / asset_id.upper() / "primary.png"
    direct.unlink()
    bundled.unlink()
    bundled.symlink_to(outside)

    reloaded = _source(synthetic_source).load_board(BOARD_TITLE)
    matching = next(
        reference for reference in reloaded.asset_references if reference.asset_id == asset_id
    )
    assert matching.source_path is None


def test_read_operations_do_not_modify_source_tree(synthetic_source: SyntheticSource) -> None:
    before = tree_digest(synthetic_source.root)
    source = _source(synthetic_source)
    source.doctor()
    source.list_boards()
    source.load_board(BOARD_TITLE)
    after = tree_digest(synthetic_source.root)
    assert after == before


def test_snapshot_reads_committed_wal_without_modifying_it(wal_source: SyntheticSource) -> None:
    wal_path = wal_source.database.with_name("boards.db-wal")
    assert wal_path.exists()
    before = tree_digest(wal_source.root)
    source = _source(wal_source)
    assert source.list_boards()[0].title == BOARD_TITLE
    assert source.load_board(BOARD_TITLE).title == BOARD_TITLE
    after = tree_digest(wal_source.root)
    assert after == before


def test_fixture_provenance_explicitly_denies_real_data(synthetic_source: SyntheticSource) -> None:
    provenance = json.loads(
        (synthetic_source.root / "SYNTHETIC_FIXTURE.json").read_text(encoding="utf-8")
    )
    assert provenance == {
        "synthetic": True,
        "schema_user_version": 16,
        "contains_real_user_data": False,
    }
