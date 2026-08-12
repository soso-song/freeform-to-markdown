from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pypdf import PdfWriter

from freeform_to_markdown.archive import archive_board, refine_archive
from freeform_to_markdown.source import FreeformSource
from freeform_to_markdown.verify import verify_archive

from .support import (
    BOARD_TITLE,
    DUPLICATE_UUID,
    FAKE_PRIVATE_URL,
    FAKE_SECRET,
    GROUP_UUID,
    IMAGE_UUID,
    MISSING_UUID,
    NO_COORDS_UUID,
    PUBLIC_NOTE,
    SHAPE_UUID,
    TEXT_UUID,
    TOMBSTONE_UUID,
    SyntheticSource,
    tree_digest,
)


def _source(bundle: SyntheticSource) -> FreeformSource:
    return FreeformSource(db_path=bundle.database, assets_path=bundle.assets)


def _json_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _manifest(archive: Path, name: str) -> list[dict[str, Any]]:
    return _json_lines(archive / "Manifest" / name)


def _by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record["object_id"]): record for record in records}


@pytest.fixture
def synthetic_archive(tmp_path: Path, synthetic_source: SyntheticSource) -> Path:
    return archive_board(_source(synthetic_source), BOARD_TITLE, tmp_path / "output")


def test_archive_matches_golden_contract(synthetic_archive: Path) -> None:
    golden = json.loads(
        (Path(__file__).parent / "golden" / "minimal_archive.json").read_text(encoding="utf-8")
    )
    archive_metadata = json.loads(
        (synthetic_archive / "Manifest" / "archive.json").read_text(encoding="utf-8")
    )
    objects = _manifest(synthetic_archive, "objects.jsonl")
    assets = _manifest(synthetic_archive, "assets.jsonl")

    assert archive_metadata["archive_schema"] == golden["archive_schema"]
    assert archive_metadata["board_title"] == golden["board_title"]
    assert len(objects) == golden["active_object_count"]
    assert len(assets) == golden["asset_reference_count"]
    for directory in golden["required_directories"]:
        assert (synthetic_archive / directory).is_dir()
    for filename in golden["required_manifest_files"]:
        assert (synthetic_archive / "Manifest" / filename).is_file()
    assert (synthetic_archive / "00 Search Index.md").is_file()
    assert {record["disposition"] for record in objects} <= set(golden["allowed_dispositions"])


def test_every_active_object_is_classified_and_tombstone_is_excluded(
    synthetic_archive: Path,
) -> None:
    records = _by_id(_manifest(synthetic_archive, "objects.jsonl"))
    assert set(records) == {
        str(TEXT_UUID),
        str(IMAGE_UUID),
        str(DUPLICATE_UUID),
        str(SHAPE_UUID),
        str(NO_COORDS_UUID),
        str(GROUP_UUID),
    }
    assert str(TOMBSTONE_UUID) not in records
    assert records[str(SHAPE_UUID)]["disposition"] == "context-only"
    assert records[str(DUPLICATE_UUID)]["disposition"] == "duplicate"
    assert all(record["verification"] for record in records.values())


def test_archive_is_searchable_but_does_not_index_secrets(synthetic_archive: Path) -> None:
    searchable_files = [
        synthetic_archive / "00 Search Index.md",
        *sorted((synthetic_archive / "Scenes").rglob("*.md")),
        *sorted((synthetic_archive / "Extracted").rglob("*.md")),
    ]
    ordinary_text = "\n".join(path.read_text(encoding="utf-8") for path in searchable_files)
    assert PUBLIC_NOTE in ordinary_text
    assert FAKE_SECRET not in ordinary_text
    assert FAKE_PRIVATE_URL not in ordinary_text
    assert "REDACTED" in ordinary_text.upper()


def test_unicode_asset_names_are_safe_and_duplicate_bytes_are_declared(
    synthetic_archive: Path,
) -> None:
    assets = _manifest(synthetic_archive, "assets.jsonl")
    assert len(assets) == 2
    assert any("研究 图片 (final)" in record["archive_path"] for record in assets)
    assert all(".." not in Path(record["archive_path"]).parts for record in assets)
    duplicate = next(record for record in assets if record.get("duplicate_of"))
    canonical = next(record for record in assets if record["asset_id"] == duplicate["duplicate_of"])
    assert duplicate["sha256"] == canonical["sha256"]
    assert (synthetic_archive / canonical["archive_path"]).read_bytes() == (
        synthetic_archive / duplicate["archive_path"]
    ).read_bytes()


def test_parent_and_fallback_relationships_are_preserved(synthetic_archive: Path) -> None:
    objects = _by_id(_manifest(synthetic_archive, "objects.jsonl"))
    relations = _manifest(synthetic_archive, "relations.jsonl")
    assert objects[str(NO_COORDS_UUID)]["scene"]
    assert any(
        relation["source"] == str(GROUP_UUID)
        and relation["target"] == str(NO_COORDS_UUID)
        and relation["type"] == "contains"
        for relation in relations
    )
    assert any(
        warning.lower().find("coordinate") >= 0
        for warning in objects[str(NO_COORDS_UUID)]["warnings"]
    )


def test_refine_applies_human_scene_map_without_copying_originals(
    tmp_path: Path, synthetic_archive: Path
) -> None:
    originals_before = tree_digest(synthetic_archive / "Originals")
    mapping = tmp_path / "scene-map.yml"
    mapping.write_text(
        yaml.safe_dump(
            {
                "scenes": [
                    {
                        "id": "research",
                        "title": "Research Notes",
                        "object_ids": [str(TEXT_UUID), str(IMAGE_UUID)],
                    }
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    refine_archive(synthetic_archive, mapping)
    objects = _by_id(_manifest(synthetic_archive, "objects.jsonl"))
    assert objects[str(TEXT_UUID)]["scene"] == "research"
    assert objects[str(IMAGE_UUID)]["scene"] == "research"
    assert objects[str(TEXT_UUID)]["canonical_path"] == "Scenes/research/00 Scene.md"
    assert "Research Notes" in (synthetic_archive / "00 Search Index.md").read_text(
        encoding="utf-8"
    )
    assert tree_digest(synthetic_archive / "Originals") == originals_before


def test_verify_passes_clean_archive_and_detects_tampering(synthetic_archive: Path) -> None:
    clean = verify_archive(synthetic_archive)
    assert clean.ok is True
    assert clean.unreviewed_count == 0
    assert clean.broken_link_count == 0
    assert clean.checksum_failure_count == 0

    original = next((synthetic_archive / "Originals").rglob("*.png"))
    original.write_bytes(original.read_bytes() + b"tampered")
    tampered = verify_archive(synthetic_archive)
    assert tampered.ok is False
    assert tampered.checksum_failure_count >= 1


def test_verify_detects_private_url_tokens_in_ordinary_output(synthetic_archive: Path) -> None:
    index = synthetic_archive / "00 Search Index.md"
    index.write_text(
        index.read_text(encoding="utf-8")
        + "\nhttps://example.com/share/00000000-0000-4000-8000-000000000123\n",
        encoding="utf-8",
    )
    report = verify_archive(synthetic_archive)
    assert report.ok is False
    assert report.privacy_finding_count >= 1


def test_verify_reports_malformed_manifest_without_crashing(synthetic_archive: Path) -> None:
    objects = synthetic_archive / "Manifest" / "objects.jsonl"
    objects.write_text(objects.read_text(encoding="utf-8") + "{not-json}\n", encoding="utf-8")
    report = verify_archive(synthetic_archive)
    assert report.ok is False
    assert any("invalid JSON in objects.jsonl" in error for error in report.errors)


def test_missing_asset_and_corrupt_blob_are_explicitly_unresolved(
    tmp_path: Path, adverse_source: SyntheticSource
) -> None:
    archive = archive_board(_source(adverse_source), BOARD_TITLE, tmp_path / "adverse-output")
    objects = _by_id(_manifest(archive, "objects.jsonl"))
    exceptions = _manifest(archive, "exceptions.jsonl")
    assert objects[str(MISSING_UUID)]["disposition"] == "unresolved"
    assert objects[str(MISSING_UUID)]["warnings"]
    assert any(record["object_id"] == str(MISSING_UUID) for record in exceptions)
    assert any("corrupt" in json.dumps(record).lower() for record in exceptions)
    report = verify_archive(archive)
    assert report.ok is False
    assert report.unresolved_count >= 2


def test_reviewed_scene_map_can_accept_explained_unresolved_objects(
    tmp_path: Path, adverse_source: SyntheticSource
) -> None:
    archive = archive_board(_source(adverse_source), BOARD_TITLE, tmp_path / "review-output")
    unresolved = [
        record
        for record in _manifest(archive, "objects.jsonl")
        if record["disposition"] == "unresolved"
    ]
    mapping = tmp_path / "review.yml"
    mapping.write_text(
        yaml.safe_dump(
            {
                "scenes": [],
                "accepted_exceptions": [
                    {
                        "object_id": record["object_id"],
                        "reason": "Source content is unavailable; the manifest preserves the gap.",
                    }
                    for record in unresolved
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    refine_archive(archive, mapping)
    report = verify_archive(archive)
    assert report.ok is True
    assert report.unresolved_count == 0
    assert report.accepted_unresolved_count == len(unresolved)
    reviewed = _manifest(archive, "objects.jsonl")
    assert sum("accepted_exception" in record for record in reviewed) == len(unresolved)


def test_full_archive_operation_leaves_source_unchanged(
    tmp_path: Path, synthetic_source: SyntheticSource
) -> None:
    before = tree_digest(synthetic_source.root)
    archive_board(_source(synthetic_source), BOARD_TITLE, tmp_path / "archive-output")
    assert tree_digest(synthetic_source.root) == before


def test_optional_board_preview_is_copied_and_checksummed(
    tmp_path: Path, synthetic_source: SyntheticSource
) -> None:
    preview = tmp_path / "official-export.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with preview.open("wb") as stream:
        writer.write(stream)

    archive = archive_board(
        _source(synthetic_source),
        BOARD_TITLE,
        tmp_path / "preview-output",
        board_preview=preview,
    )
    copied = archive / "Board" / "board-preview.pdf"
    assert copied.read_bytes() == preview.read_bytes()
    metadata = json.loads((archive / "Board" / "source-metadata.json").read_text())
    assert metadata["visual_baseline"]["archive_path"] == "Board/board-preview.pdf"
    assert (
        "visual-baseline-unavailable" not in (archive / "Manifest" / "exceptions.jsonl").read_text()
    )
    assert verify_archive(archive).ok
