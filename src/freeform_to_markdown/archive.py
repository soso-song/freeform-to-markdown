"""Write and refine portable archive-schema 1.0 directories."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .extraction import ExtractionResult, apple_vision_available, extract_asset
from .models import BoardData, BoardObject, Geometry
from .privacy import redact_text, safe_join, sanitize_filename
from .relations import infer_relations
from .source import FreeformSource
from .spatial import cluster_objects

DISPOSITIONS = {"filed", "context-only", "duplicate", "unresolved"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _scene_key(index: int) -> str:
    return f"scene-{index:03d}"


ITEM_TYPES = {
    0: "shape",
    2: "group",
    3: "text",
    5: "image",
    6: "media",
    7: "file",
    8: "link",
    10: "drawing",
    12: "sticky",
}


def _item_type(item: BoardObject) -> str:
    return ITEM_TYPES.get(item.item_type, f"unknown-{item.item_type}")


def cluster_scenes(objects: tuple[BoardObject, ...] | list[BoardObject]) -> dict[str, str]:
    """Return the shared deterministic clusterer's object-to-Scene mapping."""
    return {
        object_id: scene.scene_id
        for scene in cluster_objects(objects)
        for object_id in scene.object_ids
    }


def _legacy_text_extraction(path: Path) -> ExtractionResult | None:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".html"}:
        try:
            return ExtractionResult(
                kind="text",
                method="utf-8",
                text=path.read_text(encoding="utf-8", errors="replace"),
                metadata={
                    "size_bytes": path.stat().st_size,
                    "media_type": mimetypes.guess_type(path.name)[0] or "text/plain",
                    "extension": suffix,
                },
            )
        except OSError as error:
            return ExtractionResult(
                kind="text",
                method="failed",
                warnings=(f"text extraction failed: {error.__class__.__name__}",),
            )
    return None


def _extract_asset(path: Path) -> ExtractionResult:
    return _legacy_text_extraction(path) or extract_asset(path)


def _sidecar_text(
    reference_id: str, source_name: str, digest: str, result: ExtractionResult
) -> str:
    lines = [
        "# Extracted asset",
        "",
        f"- Asset record: `{reference_id}`",
        f"- Source name: `{redact_text(source_name)}`",
        f"- SHA-256: `{digest}`",
        f"- Extraction: `{result.method}`",
    ]
    for key, value in sorted(result.metadata.items()):
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
        lines.append(f"- {key.replace('_', ' ').title()}: `{redact_text(serialized)}`")
    lines.extend(["", redact_text(result.text) or "No searchable text was extracted."])
    if result.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {redact_text(warning)}" for warning in result.warnings)
    return "\n".join(lines).rstrip() + "\n"


def _geometry_dict(value: Geometry | None) -> dict[str, float] | None:
    if value is None:
        return None
    return {"x": value.x, "y": value.y, "width": value.width, "height": value.height}


def _layout(board: BoardData, scenes: dict[str, str]) -> dict[str, Any]:
    return {
        "board_id": board.board_id,
        "coordinate_system": "Freeform canvas values as observed; units are application-private",
        "objects": [
            {
                "object_id": item.object_id,
                "parent_id": item.parent_id,
                "type": _item_type(item),
                "bounds": _geometry_dict(item.geometry),
                "scene": scenes[item.object_id],
                "stable_order": index,
            }
            for index, item in enumerate(board.objects, 1)
        ],
    }


def _render_scene_map(archive: Path, records: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["scene"])].append(record)
    payload = {
        "scenes": [
            {
                "id": scene,
                "title": scene.replace("-", " ").title(),
                "object_ids": [str(record["object_id"]) for record in members],
            }
            for scene, members in sorted(grouped.items())
        ]
    }
    (archive / "scene-map.yml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _write_indexes(archive: Path, object_records: list[dict[str, Any]]) -> None:
    scenes_root = archive / "Scenes"
    if scenes_root.exists():
        for child in scenes_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in object_records:
        grouped[str(record["scene"])].append(record)
    index = ["# Search Index", "", "Generated searchable view of this Freeform archive.", ""]
    titles: dict[str, str] = {}
    scene_map_path = archive / "scene-map.yml"
    if scene_map_path.exists():
        data = yaml.safe_load(scene_map_path.read_text(encoding="utf-8")) or {}
        for scene in data.get("scenes", []):
            titles[str(scene.get("id"))] = str(scene.get("title") or scene.get("id"))
    for scene, members in sorted(grouped.items()):
        title = titles.get(scene, scene.replace("-", " ").title())
        directory = scenes_root / sanitize_filename(scene)
        directory.mkdir(parents=True, exist_ok=True)
        scene_md = [f"# {title}", ""]
        for record in sorted(members, key=lambda value: str(value["object_id"])):
            scene_md.append(f"## {record['type']} · `{record['object_id']}`")
            scene_md.append("")
            if record.get("text"):
                scene_md.append(str(record["text"]))
                scene_md.append("")
            canonical = record.get("canonical_path")
            if canonical:
                relative = os.path.relpath(archive / str(canonical), directory).replace(os.sep, "/")
                scene_md.append(f"[Open canonical record](<{relative}>)")
                scene_md.append("")
            if record.get("warnings"):
                scene_md.extend(f"- Warning: {warning}" for warning in record["warnings"])
                scene_md.append("")
        (directory / "00 Scene.md").write_text(
            "\n".join(scene_md).rstrip() + "\n", encoding="utf-8"
        )
        index.extend([f"## [{title}](<Scenes/{sanitize_filename(scene)}/00 Scene.md>)", ""])
        for record in members:
            snippet = str(record.get("text") or record["type"]).splitlines()[0]
            index.append(f"- `{record['object_id']}` — {snippet}")
        index.append("")
    (archive / "00 Search Index.md").write_text("\n".join(index).rstrip() + "\n", encoding="utf-8")


def _checksums(archive: Path) -> None:
    included: list[Path] = []
    for base in (archive / "Originals", archive / "Extracted", archive / "Board"):
        if base.exists():
            included.extend(path for path in base.rglob("*") if path.is_file())
    for name in (
        "archive.json",
        "objects.jsonl",
        "assets.jsonl",
        "relations.jsonl",
        "exceptions.jsonl",
    ):
        path = archive / "Manifest" / name
        if path.is_file():
            included.append(path)
    lines = [f"{sha256(path)}  {path.relative_to(archive).as_posix()}" for path in sorted(included)]
    (archive / "Manifest" / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def archive_board(
    source: FreeformSource,
    selector: str,
    output: Path,
    *,
    board_preview: Path | None = None,
) -> Path:
    board = source.load_board(selector)
    public_board_title = redact_text(board.title)
    title = sanitize_filename(public_board_title, fallback=f"board-{board.board_id[:8]}")
    output = Path(output)
    archive = output if output.name == title and not output.exists() else output / title
    if archive.exists() and any(archive.iterdir()):
        raise FileExistsError(f"archive destination is not empty: {archive}")
    with tempfile.TemporaryDirectory(
        prefix="ff2md-build-", dir=output.parent if output.parent.exists() else None
    ) as temporary:
        stage = Path(temporary) / title
        for name in ("Board", "Scenes", "Originals", "Extracted", "Manifest"):
            (stage / name).mkdir(parents=True, exist_ok=True)
        scenes = cluster_scenes(board.objects)
        asset_records: list[dict[str, Any]] = []
        exceptions: list[dict[str, Any]] = []
        canonical_by_hash: dict[str, dict[str, Any]] = {}
        refs_by_object: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for reference_index, reference in enumerate(board.asset_references, 1):
            reference_id = f"asset-ref-{reference_index:06d}"
            record: dict[str, Any] = {
                "asset_id": reference_id,
                "source_asset_id": reference.asset_id,
                "object_id": reference.object_id,
                "role": reference.role,
                "source_name": redact_text(reference.original_name),
                "media_type": mimetypes.guess_type(reference.original_name)[0]
                or "application/octet-stream",
                "sha256": None,
                "size": None,
                "archive_path": None,
                "extracted_path": None,
                "duplicate_of": None,
                "verification": {
                    "source_exists": reference.source_path is not None,
                    "sha256": False,
                },
                "warnings": [] if reference.source_path else ["source asset is missing"],
            }
            if reference.source_path:
                digest = sha256(reference.source_path)
                record["sha256"] = digest
                record["size"] = reference.source_path.stat().st_size
                canonical = canonical_by_hash.get(digest)
                if canonical:
                    record["duplicate_of"] = canonical["asset_id"]
                    record["archive_path"] = canonical["archive_path"]
                    record["extracted_path"] = canonical["extracted_path"]
                    record["verification"] = {"source_exists": True, "sha256": True}
                else:
                    filename = sanitize_filename(redact_text(reference.original_name))
                    destination = safe_join(
                        stage, Path("Originals") / f"{reference.asset_id}-{filename}"
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(reference.source_path, destination, follow_symlinks=False)
                    if sha256(destination) != digest:
                        raise OSError("copied asset failed SHA-256 verification")
                    record["archive_path"] = destination.relative_to(stage.resolve()).as_posix()
                    extraction = _extract_asset(destination)
                    record["warnings"].extend(extraction.warnings)
                    record["extraction_method"] = extraction.method
                    record["technical_metadata"] = extraction.metadata
                    sidecar = (
                        stage
                        / "Extracted"
                        / f"{reference.asset_id}-{Path(filename).stem}_extracted.md"
                    )
                    sidecar.write_text(
                        _sidecar_text(
                            reference_id,
                            reference.original_name,
                            digest,
                            extraction,
                        ),
                        encoding="utf-8",
                    )
                    record["extracted_path"] = sidecar.relative_to(stage).as_posix()
                    record["verification"] = {"source_exists": True, "sha256": True}
                    canonical_by_hash[digest] = record
            else:
                exceptions.append(
                    {
                        "severity": "error",
                        "code": "missing-asset",
                        "object_id": reference.object_id,
                        "asset_id": reference_id,
                        "message": "A referenced source asset could not be found.",
                    }
                )
            asset_records.append(record)
            refs_by_object[reference.object_id].append(record)
        object_records: list[dict[str, Any]] = []
        for item in board.objects:
            references = refs_by_object.get(item.object_id, [])
            warnings = list(item.warnings)
            for reference_record in references:
                warnings.extend(str(value) for value in reference_record.get("warnings", []))
            normalized_type = _item_type(item)
            if "unknown" in normalized_type:
                disposition = "unresolved"
                warnings.append("unsupported object type")
            elif any(record["archive_path"] is None for record in references):
                disposition = "unresolved"
            elif any(record["duplicate_of"] for record in references) and references:
                disposition = "duplicate"
            elif (normalized_type in {"text", "sticky", "link"} and item.text) or references:
                disposition = "filed"
            elif normalized_type in {"group", "shape", "drawing"}:
                disposition = "context-only"
            elif normalized_type in {"text", "sticky"} and item.warnings:
                disposition = "unresolved"
            else:
                disposition = "context-only"
            canonical_path = references[0].get("archive_path") if references else None
            if item.text:
                canonical_path = f"Scenes/{scenes[item.object_id]}/00 Scene.md"
            object_record = {
                "object_id": item.object_id,
                "type": normalized_type,
                "parent_id": item.parent_id,
                "bounds": _geometry_dict(item.geometry),
                "text": redact_text(item.text) or None,
                "scene": scenes[item.object_id],
                "disposition": disposition,
                "canonical_path": canonical_path,
                "verification": {"classified": disposition in DISPOSITIONS},
                "warnings": warnings,
            }
            object_records.append(object_record)
            if disposition == "unresolved":
                exceptions.append(
                    {
                        "severity": "error",
                        "code": "unresolved-object",
                        "object_id": item.object_id,
                        "message": "; ".join(warnings) or "Object could not be represented.",
                    }
                )
        relations: list[dict[str, Any]] = [
            dict(relation) for relation in infer_relations(board.objects, scenes)
        ]
        for record in asset_records:
            if record["duplicate_of"]:
                relation_identity = (
                    f"duplicate-of\0{record['asset_id']}\0{record['duplicate_of']}".encode()
                )
                relations.append(
                    {
                        "relation_id": (
                            "relation-duplicate-of-"
                            + hashlib.sha256(relation_identity).hexdigest()[:16]
                        ),
                        "source": record["asset_id"],
                        "target": record["duplicate_of"],
                        "relation_type": "duplicate-of",
                        "type": "duplicate-of",
                        "scene": None,
                        "evidence": "identical SHA-256",
                        "reason": "Both asset references resolve to byte-identical content.",
                        "confidence": "observed",
                        "distance": None,
                    }
                )
        _write_json(stage / "Board" / "layout.json", _layout(board, scenes))
        preview_metadata: dict[str, Any]
        if board_preview is not None:
            preview_source = Path(board_preview)
            if not preview_source.is_file():
                raise FileNotFoundError("the supplied board preview is not readable")
            with preview_source.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("the supplied board preview is not a PDF")
            preview_destination = stage / "Board" / "board-preview.pdf"
            shutil.copyfile(preview_source, preview_destination)
            preview_metadata = {
                "status": "provided",
                "archive_path": "Board/board-preview.pdf",
                "sha256": sha256(preview_destination),
            }
        else:
            preview_metadata = {"status": "not provided"}
        _write_json(
            stage / "Board" / "source-metadata.json",
            {
                "kind": "Apple Freeform local SQLite snapshot",
                "schema_user_version": board.schema_version,
                "source_paths_included": False,
                "visual_baseline": preview_metadata,
            },
        )
        if board_preview is None:
            exceptions.append(
                {
                    "severity": "info",
                    "code": "visual-baseline-unavailable",
                    "message": (
                        "No official Freeform PDF was supplied; layout.json is the baseline."
                    ),
                }
            )
        archive_metadata = {
            "archive_schema": "1.0",
            "board_title": public_board_title,
            "generator": {"name": "freeform-to-markdown", "version": __version__},
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "kind": "freeform-snapshot",
                "schema_user_version": board.schema_version,
                "schema_fingerprint": board.schema_fingerprint,
            },
            "board": {"key": board.board_id, "title": public_board_title},
            "counts": {
                "objects": len(object_records),
                "asset_references": len(asset_records),
                "tombstoned_objects": board.tombstoned_object_count,
                "dispositions": {
                    name: sum(record["disposition"] == name for record in object_records)
                    for name in sorted(DISPOSITIONS)
                },
            },
            "capabilities": {
                "text": True,
                "geometry": True,
                "assets": True,
                "local_ocr_available": apple_vision_available(),
                "local_ocr_used": any(
                    record.get("extraction_method")
                    in {"apple-vision", "pdf-text-layer+apple-vision"}
                    for record in asset_records
                ),
                "spatial_relations": True,
                "visual_baseline": board_preview is not None,
            },
            "known_losses": [
                "Exact editable layers, drawing strokes, stacking, and private app state "
                "are not reconstructed."
            ],
        }
        _write_json(stage / "Manifest" / "archive.json", archive_metadata)
        _write_jsonl(stage / "Manifest" / "objects.jsonl", object_records)
        _write_jsonl(stage / "Manifest" / "assets.jsonl", asset_records)
        _write_jsonl(stage / "Manifest" / "relations.jsonl", relations)
        _write_jsonl(stage / "Manifest" / "exceptions.jsonl", exceptions)
        _render_scene_map(stage, object_records)
        _write_indexes(stage, object_records)
        _checksums(stage)
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage), archive)
    from .verify import verify_archive

    verify_archive(archive)
    return archive


def refine_archive(archive: Path, scene_map: Path) -> Path:
    archive = Path(archive).resolve()
    mapping = yaml.safe_load(Path(scene_map).read_text(encoding="utf-8")) or {}
    scenes = mapping.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("scene map must contain a scenes list")
    objects_path = archive / "Manifest" / "objects.jsonl"
    records = [
        json.loads(line) for line in objects_path.read_text(encoding="utf-8").splitlines() if line
    ]
    known = {str(record["object_id"]) for record in records}
    records_by_id = {str(record["object_id"]): record for record in records}
    assignments: dict[str, str] = {}
    clean_scenes: list[dict[str, Any]] = []
    seen_scene_ids: set[str] = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("each Scene must be a mapping")
        scene_id = sanitize_filename(str(scene.get("id", "")), fallback="scene")
        if scene_id in seen_scene_ids:
            raise ValueError("Scene identifiers must be unique")
        seen_scene_ids.add(scene_id)
        title = redact_text(str(scene.get("title") or scene_id))
        object_ids = [str(value) for value in scene.get("object_ids", [])]
        if not set(object_ids) <= known:
            raise ValueError("scene map references an unknown object")
        if set(object_ids) & set(assignments):
            raise ValueError("an object appears in more than one reviewed Scene")
        assignments.update({object_id: scene_id for object_id in object_ids})
        clean_scenes.append({"id": scene_id, "title": title, "object_ids": object_ids})
    accepted_values = mapping.get("accepted_exceptions", [])
    if not isinstance(accepted_values, list):
        raise ValueError("accepted_exceptions must be a list")
    accepted_exceptions: list[dict[str, str]] = []
    accepted_ids: set[str] = set()
    for value in accepted_values:
        if not isinstance(value, dict):
            raise ValueError("each accepted exception must be a mapping")
        object_id = str(value.get("object_id", ""))
        reason = redact_text(str(value.get("reason", "")).strip())
        if object_id not in known:
            raise ValueError("accepted exception references an unknown object")
        if records_by_id[object_id].get("disposition") != "unresolved":
            raise ValueError("only unresolved objects can be accepted as exceptions")
        if not reason:
            raise ValueError("accepted exceptions require a reason")
        if object_id in accepted_ids:
            raise ValueError("an unresolved object is accepted more than once")
        accepted_ids.add(object_id)
        accepted_exceptions.append({"object_id": object_id, "reason": reason})
    for record in records:
        object_id = str(record["object_id"])
        if object_id in assignments:
            scene_id = assignments[object_id]
            record["scene"] = scene_id
            canonical_path = record.get("canonical_path")
            if record.get("text") and isinstance(canonical_path, str):
                record["canonical_path"] = f"Scenes/{scene_id}/00 Scene.md"
        record.pop("accepted_exception", None)
        if object_id in accepted_ids:
            reason = next(
                value["reason"] for value in accepted_exceptions if value["object_id"] == object_id
            )
            record["accepted_exception"] = {
                "reason": reason,
                "reviewed_via": "scene-map.yml",
            }
    (archive / "scene-map.yml").write_text(
        yaml.safe_dump(
            {
                "scenes": clean_scenes,
                "accepted_exceptions": accepted_exceptions,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    _write_jsonl(objects_path, records)
    relation_path = archive / "Manifest" / "relations.jsonl"
    previous_relations = [
        json.loads(line) for line in relation_path.read_text(encoding="utf-8").splitlines() if line
    ]
    duplicate_relations = [
        relation for relation in previous_relations if relation.get("type") == "duplicate-of"
    ]
    item_type_by_name = {name: number for number, name in ITEM_TYPES.items()}
    reconstructed: list[BoardObject] = []
    scene_by_object: dict[str, str] = {}
    for record in records:
        bounds = record.get("bounds")
        geometry = None
        if isinstance(bounds, dict):
            geometry = Geometry(
                float(bounds["x"]),
                float(bounds["y"]),
                float(bounds["width"]),
                float(bounds["height"]),
            )
        object_id = str(record["object_id"])
        scene_by_object[object_id] = str(record["scene"])
        reconstructed.append(
            BoardObject(
                object_id=object_id,
                parent_id=(str(record["parent_id"]) if record.get("parent_id") else None),
                item_type=item_type_by_name.get(str(record["type"]), -1),
                sub_item_type=None,
                common_data=b"",
                specific_data=b"",
                text=str(record.get("text") or ""),
                geometry=geometry,
            )
        )
    refreshed_relations: list[dict[str, Any]] = [
        dict(relation) for relation in infer_relations(reconstructed, scene_by_object)
    ]
    refreshed_relations.extend(duplicate_relations)
    _write_jsonl(relation_path, refreshed_relations)
    exceptions_path = archive / "Manifest" / "exceptions.jsonl"
    exceptions = [
        json.loads(line)
        for line in exceptions_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    acceptance_by_id = {value["object_id"]: value["reason"] for value in accepted_exceptions}
    for exception in exceptions:
        object_id = str(exception.get("object_id") or "")
        exception.pop("accepted", None)
        exception.pop("acceptance_reason", None)
        if object_id in acceptance_by_id:
            exception["accepted"] = True
            exception["acceptance_reason"] = acceptance_by_id[object_id]
    _write_jsonl(exceptions_path, exceptions)
    _write_indexes(archive, records)
    _checksums(archive)
    from .verify import verify_archive

    verify_archive(archive)
    return archive
