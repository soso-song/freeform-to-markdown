"""Deterministic verification for archive-schema 1.0."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import VerificationReport
from .privacy import redact_text, safe_join

_MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^)]+))\)")
_ABSOLUTE_PATH = re.compile(  # privacy-scan: allow
    r"(?:/Users/|/home/|[A-Za-z]:\\Users\\)"  # privacy-scan: allow
)


def _jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"invalid JSON in {path.name} line {number}")
            continue
        if not isinstance(value, dict):
            errors.append(f"non-object JSON in {path.name} line {number}")
            continue
        records.append(value)
    return records


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify_archive(archive: Path) -> VerificationReport:
    archive = Path(archive).resolve()
    errors: list[str] = []
    manifest = archive / "Manifest"
    required = [
        archive / "00 Search Index.md",
        archive / "Board" / "layout.json",
        manifest / "archive.json",
        manifest / "objects.jsonl",
        manifest / "assets.jsonl",
        manifest / "relations.jsonl",
        manifest / "exceptions.jsonl",
        manifest / "SHA256SUMS",
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing required archive file: {path.relative_to(archive)}")
    metadata: dict[str, Any] = {}
    archive_metadata_path = manifest / "archive.json"
    if archive_metadata_path.is_file():
        try:
            value = json.loads(archive_metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("invalid JSON in archive.json")
        else:
            if isinstance(value, dict):
                metadata = value
            else:
                errors.append("archive.json must contain one object")
    if metadata and metadata.get("archive_schema") != "1.0":
        errors.append("unsupported or missing archive_schema")
    layout_path = archive / "Board" / "layout.json"
    if layout_path.is_file():
        try:
            layout_value = json.loads(layout_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("invalid JSON in layout.json")
        else:
            if not isinstance(layout_value, dict):
                errors.append("layout.json must contain one object")
    objects = (
        _jsonl(manifest / "objects.jsonl", errors) if (manifest / "objects.jsonl").is_file() else []
    )
    assets = (
        _jsonl(manifest / "assets.jsonl", errors) if (manifest / "assets.jsonl").is_file() else []
    )
    relations = (
        _jsonl(manifest / "relations.jsonl", errors)
        if (manifest / "relations.jsonl").is_file()
        else []
    )
    if (manifest / "exceptions.jsonl").is_file():
        _jsonl(manifest / "exceptions.jsonl", errors)
    object_id_values = [str(record.get("object_id")) for record in objects]
    asset_id_values = [str(record.get("asset_id")) for record in assets]
    object_ids = set(object_id_values)
    asset_ids = set(asset_id_values)
    if len(object_ids) != len(object_id_values):
        errors.append("objects.jsonl contains duplicate object IDs")
    if len(asset_ids) != len(asset_id_values):
        errors.append("assets.jsonl contains duplicate asset IDs")
    counts = metadata.get("counts") if isinstance(metadata.get("counts"), dict) else {}
    if counts:
        if counts.get("objects") != len(objects):
            errors.append("archive object count does not match objects.jsonl")
        if counts.get("asset_references") != len(assets):
            errors.append("archive asset-reference count does not match assets.jsonl")
    allowed = {"filed", "context-only", "duplicate", "unresolved"}
    unresolved_count = 0
    accepted_unresolved_count = 0
    unreviewed_count = 0
    for record in objects:
        disposition = record.get("disposition")
        if disposition not in allowed:
            unreviewed_count += 1
            errors.append(f"invalid disposition for object {record.get('object_id')}")
        if disposition == "unresolved":
            accepted = record.get("accepted_exception")
            if (
                isinstance(accepted, dict)
                and accepted.get("reviewed_via") == "scene-map.yml"
                and isinstance(accepted.get("reason"), str)
                and accepted["reason"].strip()
            ):
                accepted_unresolved_count += 1
            else:
                unresolved_count += 1
        elif record.get("accepted_exception"):
            errors.append(
                f"non-unresolved object has an accepted exception: {record.get('object_id')}"
            )
        canonical = record.get("canonical_path")
        if canonical:
            try:
                target = safe_join(archive, str(canonical))
            except ValueError:
                errors.append(f"escaping canonical path for object {record.get('object_id')}")
            else:
                if not target.exists():
                    errors.append(f"missing canonical path for object {record.get('object_id')}")
    for record in assets:
        asset_id = str(record.get("asset_id"))
        object_id = str(record.get("object_id"))
        if object_id not in object_ids:
            errors.append(f"asset {asset_id} references an unknown object")
        value = record.get("archive_path")
        if value:
            try:
                target = safe_join(archive, str(value))
            except ValueError:
                errors.append(f"escaping archive path for asset {record.get('asset_id')}")
            else:
                if not target.is_file():
                    errors.append(f"missing original for asset {record.get('asset_id')}")
                elif record.get("sha256") and _digest(target) != record["sha256"]:
                    errors.append(f"asset SHA-256 mismatch for {record.get('asset_id')}")
        duplicate_of = record.get("duplicate_of")
        if duplicate_of:
            matches = [
                candidate for candidate in assets if candidate.get("asset_id") == duplicate_of
            ]
            if len(matches) != 1:
                errors.append(f"asset {asset_id} has an invalid duplicate target")
            else:
                canonical = matches[0]
                if record.get("sha256") != canonical.get("sha256") or record.get(
                    "archive_path"
                ) != canonical.get("archive_path"):
                    errors.append(f"asset {asset_id} does not match its duplicate target")
    scene_ids = {str(record.get("scene")) for record in objects if record.get("scene")}
    valid_relation_ids = object_ids | asset_ids | scene_ids
    relation_id_values = [str(relation.get("relation_id")) for relation in relations]
    if len(set(relation_id_values)) != len(relation_id_values):
        errors.append("relations.jsonl contains duplicate relation IDs")
    for relation in relations:
        source_id = str(relation.get("source"))
        target_id = str(relation.get("target"))
        if source_id not in valid_relation_ids or target_id not in valid_relation_ids:
            errors.append(f"relation has an unknown endpoint: {source_id} -> {target_id}")
        for field in ("relation_id", "type", "evidence", "reason", "confidence"):
            if not relation.get(field):
                errors.append(f"relation is missing {field}: {source_id} -> {target_id}")
    referenced_files = {
        str(record[field])
        for record in assets
        for field in ("archive_path", "extracted_path")
        if record.get(field)
    }
    for directory_name in ("Originals", "Extracted"):
        directory = archive / directory_name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.relative_to(archive).as_posix() not in referenced_files:
                errors.append(f"orphan archive file: {path.relative_to(archive).as_posix()}")
    checksum_failures = 0
    checksum_entries: set[str] = set()
    checksum_path = manifest / "SHA256SUMS"
    if checksum_path.is_file():
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            expected, separator, relative = line.partition("  ")
            if relative in checksum_entries:
                checksum_failures += 1
                errors.append(f"duplicate checksum entry: {relative}")
                continue
            checksum_entries.add(relative)
            try:
                target = safe_join(archive, relative)
            except ValueError:
                target = archive / "__invalid__"
            if not separator or not target.is_file() or _digest(target) != expected:
                checksum_failures += 1
                errors.append(f"checksum failed: {relative or '<malformed>'}")
    broken_links = 0
    privacy_findings = 0
    ordinary_paths = [archive / "00 Search Index.md", archive / "scene-map.yml"]
    for directory_name in ("Board", "Scenes", "Extracted", "Manifest"):
        directory = archive / directory_name
        if directory.is_dir():
            ordinary_paths += [
                path
                for path in directory.rglob("*")
                if path.is_file() and path.suffix.casefold() in {".json", ".jsonl", ".md", ".yml"}
            ]
    for path in ordinary_paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        privacy_findings += int(redact_text(text) != text)
        privacy_findings += len(_ABSOLUTE_PATH.findall(text))
        for angled, plain in _MARKDOWN_LINK.findall(text):
            target_text = angled or plain
            if not target_text or "://" in target_text or target_text.startswith("#"):
                continue
            target = (path.parent / target_text).resolve()
            if archive not in target.parents and target != archive:
                broken_links += 1
                errors.append(f"link escapes archive: {path.relative_to(archive)}")
            elif not target.exists():
                broken_links += 1
                errors.append(f"broken link: {path.relative_to(archive)} -> {target_text}")
    if privacy_findings:
        errors.append(f"ordinary output contains {privacy_findings} privacy finding(s)")
    if unresolved_count:
        errors.append(f"archive contains {unresolved_count} unresolved object(s)")
    report = VerificationReport(
        ok=not errors,
        object_count=len(objects),
        unresolved_count=unresolved_count,
        accepted_unresolved_count=accepted_unresolved_count,
        unreviewed_count=unreviewed_count,
        broken_link_count=broken_links,
        checksum_failure_count=checksum_failures,
        privacy_failure_count=privacy_findings,
        errors=tuple(errors),
    )
    manifest.mkdir(parents=True, exist_ok=True)
    (manifest / "verification.json").write_text(
        json.dumps(
            {
                "ok": report.ok,
                "object_count": report.object_count,
                "unresolved_count": report.unresolved_count,
                "accepted_unresolved_count": report.accepted_unresolved_count,
                "unreviewed_count": report.unreviewed_count,
                "broken_link_count": report.broken_link_count,
                "checksum_failure_count": report.checksum_failure_count,
                "privacy_finding_count": report.privacy_finding_count,
                "errors": list(report.errors),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report
