"""Read-only, schema-aware access to Apple Freeform's local database."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import AssetReference, BoardData, BoardObject, BoardSummary, DoctorReport
from .parsing import extract_geometry, extract_text, is_well_formed_protobuf, protobuf_strings

SUPPORTED_SCHEMA_VERSIONS = frozenset({16})
VERIFIED_SCHEMA_FINGERPRINTS = frozenset(
    {
        # Public, from-scratch synthetic fixture used by this repository.
        "596c0d913e104d58171fda789bc3dec224b75a658f970cd007370f769e23fe4f",
        # Freeform schema v16 observed by the private local-only regression gate.
        "9779e44561b358eedbc680e5614064613effa309b88a019699399f095585122e",
    }
)
_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "boards": {"board_identifier", "owner_name", "data", "last_activity_time", "tombstoned"},
    "board_items": {
        "item_uuid",
        "parent_uuid",
        "board_identifier",
        "item_type",
        "common_data",
        "specific_data",
        "tombstoned",
        "sub_item_type",
    },
    "asset_references": {
        "referrer_identifier",
        "board_identifier",
        "referrer_asset_name",
        "asset_uuid",
    },
    "assets": {"asset_uuid", "extension", "tombstone_date"},
}


class FreeformError(RuntimeError):
    """Base exception for expected, user-facing source failures."""


class UnsupportedSchemaError(FreeformError):
    """Raised when a source schema has not been explicitly verified."""


class BoardNotFoundError(FreeformError):
    """Raised when an exact title or identifier does not select one board."""


def _uuid_text(value: bytes | None) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(bytes=value))
    except (TypeError, ValueError) as error:
        raise FreeformError("invalid UUID blob in Freeform database") from error


class FreeformSource:
    """A reader that copies the SQLite source set before inspecting records."""

    def __init__(
        self,
        db_path: Path | None = None,
        assets_path: Path | None = None,
        *,
        allow_experimental_schema: bool = False,
    ) -> None:
        default_root = (
            Path.home() / "Library" / "Group Containers" / "group.com.apple.freeform" / "Boards"
        )
        database_value = db_path or os.environ.get("FREEFORM_DB_PATH") or default_root / "boards.db"
        assets_value = (
            assets_path or os.environ.get("FREEFORM_ASSETS_PATH") or default_root / "Assets"
        )
        self.db_path = Path(database_value).expanduser()
        self.assets_path = Path(assets_value).expanduser()
        self.allow_experimental_schema = allow_experimental_schema

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _copy_source_set(self, destination: Path, *, attempts: int = 5) -> Path:
        """Copy database and WAL without opening anything in Freeform's live directory."""

        source_wal = self.db_path.with_name(f"{self.db_path.name}-wal")
        destination_db = destination / "boards.snapshot.db"
        destination_wal = destination / "boards.snapshot.db-wal"
        for attempt in range(attempts):
            before = (
                self._file_signature(self.db_path),
                self._file_signature(source_wal),
            )
            if before[0] is None:
                raise FreeformError(
                    "Freeform database is not readable; grant Full Disk Access or set "
                    "FREEFORM_DB_PATH."
                )
            try:
                shutil.copyfile(self.db_path, destination_db, follow_symlinks=False)
                if before[1] is not None:
                    shutil.copyfile(source_wal, destination_wal, follow_symlinks=False)
                elif destination_wal.exists():
                    destination_wal.unlink()
            except OSError as error:
                raise FreeformError(
                    "Freeform could not be snapshotted; check Full Disk Access and available "
                    "temporary storage."
                ) from error
            after = (
                self._file_signature(self.db_path),
                self._file_signature(source_wal),
            )
            copied = (
                self._file_signature(destination_db),
                self._file_signature(destination_wal),
            )
            stable_sizes = (
                copied[0] is not None
                and before == after
                and copied[0][1] == before[0][1]
                and (before[1] is None or (copied[1] is not None and copied[1][1] == before[1][1]))
            )
            if stable_sizes:
                return destination_db
            if attempt + 1 < attempts:
                time.sleep(0.05)
        raise FreeformError("Freeform changed while it was being snapshotted; try again.")

    @contextmanager
    def _snapshot(self) -> Iterator[sqlite3.Connection]:
        """Yield a consistent temporary database including committed WAL content."""

        if not self.db_path.is_file():
            raise FreeformError(
                "Freeform database is not readable; grant Full Disk Access or set FREEFORM_DB_PATH."
            )
        with tempfile.TemporaryDirectory(prefix="ff2md-snapshot-") as temporary:
            snapshot_path = self._copy_source_set(Path(temporary))
            snapshot = sqlite3.connect(f"{snapshot_path.as_uri()}?mode=ro", uri=True)
            snapshot.row_factory = sqlite3.Row
            snapshot.execute("PRAGMA query_only=ON")
            try:
                yield snapshot
            finally:
                snapshot.close()

    @staticmethod
    def _schema_details(connection: sqlite3.Connection) -> tuple[int, str, tuple[str, ...]]:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        definitions: list[str] = []
        errors: list[str] = []
        for table, required in sorted(_REQUIRED_COLUMNS.items()):
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            columns = {str(row[1]) for row in rows}
            definitions.append(f"{table}:" + ",".join(sorted(columns)))
            missing = sorted(required - columns)
            if missing:
                errors.append(f"{table} missing columns: {', '.join(missing)}")
        fingerprint = hashlib.sha256("\n".join(definitions).encode()).hexdigest()
        return version, fingerprint, tuple(errors)

    def doctor(self) -> DoctorReport:
        errors: list[str] = []
        warnings: list[str] = []
        readable = self.db_path.is_file() and os.access(self.db_path, os.R_OK)
        assets_readable = self.assets_path.is_dir() and os.access(self.assets_path, os.R_OK)
        version = -1
        fingerprint = ""
        if not readable:
            errors.append(
                "Freeform database is not readable; grant Full Disk Access or set FREEFORM_DB_PATH."
            )
        else:
            try:
                with self._snapshot() as connection:
                    version, fingerprint, schema_errors = self._schema_details(connection)
                    errors.extend(schema_errors)
            except FreeformError as error:
                errors.append(str(error))
            except OSError:
                errors.append(
                    "Freeform could not be snapshotted; check Full Disk Access and available "
                    "temporary storage."
                )
            except sqlite3.Error:
                errors.append("The copied Freeform database could not be read as SQLite.")
        if not assets_readable:
            errors.append(
                "Freeform Assets directory is not readable; grant Full Disk Access or set "
                "FREEFORM_ASSETS_PATH."
            )
        compatible = version in SUPPORTED_SCHEMA_VERSIONS and not any(
            "missing columns" in error for error in errors
        )
        verified = compatible and fingerprint in VERIFIED_SCHEMA_FINGERPRINTS
        if compatible and not verified:
            message = (
                "Schema fingerprint is unrecognized. Export is disabled by default; use "
                "--allow-experimental-schema only after reviewing the compatibility risk."
            )
            if self.allow_experimental_schema:
                warnings.append(message)
            else:
                errors.append(message)
        supported = compatible and (verified or self.allow_experimental_schema)
        schema_status = "verified" if verified else "experimental" if supported else "unsupported"
        return DoctorReport(
            schema_version=version,
            schema_fingerprint=fingerprint,
            supported=supported,
            database_readable=readable,
            assets_readable=assets_readable,
            ocr_available=shutil.which("swift") is not None and os.uname().sysname == "Darwin",
            schema_status=schema_status,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def _require_supported(self) -> tuple[int, str]:
        report = self.doctor()
        if report.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaError(
                f"Freeform schema user_version {report.schema_version} is unsupported; "
                "this tool has only verified version 16"
            )
        if not report.supported:
            raise UnsupportedSchemaError(
                "incompatible Freeform schema: " + "; ".join(report.errors)
            )
        return report.schema_version, report.schema_fingerprint

    @staticmethod
    def _title(data: bytes | None, owner: str | None, board_id: str) -> str:
        candidates = extract_text(data).splitlines()
        if candidates:
            return candidates[0]
        if owner and owner.strip():
            return owner.strip()
        return f"Untitled {board_id[:8]}"

    def list_boards(self) -> list[BoardSummary]:
        self._require_supported()
        with self._snapshot() as connection:
            rows = connection.execute(
                """
                SELECT b.board_identifier,b.owner_name,b.data,b.last_activity_time,
                  (SELECT count(*) FROM board_items bi
                   WHERE bi.board_identifier=b.board_identifier AND bi.tombstoned=0) object_count,
                  (SELECT count(*) FROM asset_references ar JOIN board_items bi
                   ON bi.item_uuid=ar.referrer_identifier
                   WHERE ar.board_identifier=b.board_identifier AND bi.tombstoned=0) ref_count
                FROM boards b WHERE b.tombstoned=0
                ORDER BY b.last_activity_time DESC,b.board_identifier
                """
            ).fetchall()
        summaries: list[BoardSummary] = []
        for row in rows:
            board_id = _uuid_text(row["board_identifier"])
            if board_id is None:
                continue
            summaries.append(
                BoardSummary(
                    board_id=board_id,
                    title=self._title(row["data"], row["owner_name"], board_id),
                    object_count=int(row["object_count"]),
                    asset_reference_count=int(row["ref_count"]),
                    last_activity_time=(
                        float(row["last_activity_time"])
                        if row["last_activity_time"] is not None
                        else None
                    ),
                )
            )
        return summaries

    def _resolve_board(self, connection: sqlite3.Connection, selector: str) -> sqlite3.Row:
        active = connection.execute(
            "SELECT board_identifier,owner_name,data,last_activity_time FROM boards "
            "WHERE tombstoned=0 ORDER BY board_identifier"
        ).fetchall()
        normalized = selector.strip().lower()
        matches: list[sqlite3.Row] = []
        for row in active:
            board_id = _uuid_text(row["board_identifier"])
            if board_id is None:
                continue
            title = self._title(row["data"], row["owner_name"], board_id)
            if normalized in {board_id, board_id.replace("-", ""), title.casefold()}:
                matches.append(row)
        if len(matches) != 1:
            detail = "not found" if not matches else "ambiguous"
            raise BoardNotFoundError(f"board selector is {detail}")
        return matches[0]

    def _asset_path(self, asset_id: str, extension: str) -> Path | None:
        suffix = f".{extension}" if extension else ""
        candidates = [
            self.assets_path / f"{asset_id.upper()}{suffix}",
            self.assets_path / f"{asset_id}{suffix}",
            self.assets_path / asset_id.upper(),
            self.assets_path / asset_id,
        ]
        assets_root = self.assets_path.resolve()

        def safe_source_file(path: Path) -> bool:
            try:
                resolved = path.resolve(strict=True)
            except (FileNotFoundError, OSError):
                return False
            current = path
            while current != self.assets_path and current != current.parent:
                if current.is_symlink():
                    return False
                current = current.parent
            return path.is_file() and (resolved == assets_root or assets_root in resolved.parents)

        for candidate in candidates[:2]:
            if safe_source_file(candidate):
                return candidate
        for directory in candidates[2:]:
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                matches = sorted(
                    path
                    for path in directory.iterdir()
                    if safe_source_file(path)
                    and (not extension or path.suffix.casefold() == suffix.casefold())
                )
            except OSError:
                continue
            if matches:
                return matches[0]
        return None

    @staticmethod
    def _asset_identity(
        raw_name: str | None, extension: str, specific_data: bytes, item_type: int
    ) -> tuple[str, str]:
        ref_name = (raw_name or "asset").strip()
        known_roles = {
            "image",
            "file",
            "media",
            "movie",
            "thumbnail",
            "linkMetadata",
            "preview",
        }
        if ref_name in known_roles:
            role = ref_name
            suffix = f".{extension.casefold()}" if extension else ""
            names = [
                value
                for value in protobuf_strings(specific_data)
                if suffix and value.casefold().endswith(suffix)
            ]
            original_name = Path(names[-1]).name if names else f"{role}{suffix}"
        else:
            role = {5: "image", 6: "media", 7: "file", 8: "linkMetadata"}.get(item_type, "asset")
            original_name = Path(ref_name).name
            if extension and not original_name.casefold().endswith(f".{extension.casefold()}"):
                original_name += f".{extension}"
        return role, original_name

    def load_board(self, selector: str) -> BoardData:
        version, fingerprint = self._require_supported()
        with self._snapshot() as connection:
            board = self._resolve_board(connection, selector)
            board_blob = board["board_identifier"]
            board_id = _uuid_text(board_blob)
            if board_id is None:
                raise FreeformError("selected board has no identifier")
            title = self._title(board["data"], board["owner_name"], board_id)
            item_rows = connection.execute(
                "SELECT item_uuid,parent_uuid,item_type,sub_item_type,common_data,specific_data "
                "FROM board_items WHERE board_identifier=? AND tombstoned=0 ORDER BY rowid",
                (board_blob,),
            ).fetchall()
            tombstoned_count = int(
                connection.execute(
                    "SELECT count(*) FROM board_items WHERE board_identifier=? AND tombstoned!=0",
                    (board_blob,),
                ).fetchone()[0]
            )
            objects: list[BoardObject] = []
            item_type_by_id: dict[bytes, int] = {}
            specific_by_id: dict[bytes, bytes] = {}
            for row in item_rows:
                item_uuid = bytes(row["item_uuid"])
                item_type = int(row["item_type"])
                common = bytes(row["common_data"] or b"")
                specific = bytes(row["specific_data"] or b"")
                warnings: list[str] = []
                geometry = extract_geometry(common)
                if geometry is None:
                    warnings.append("coordinates unavailable; parent/order fallback used")
                text = extract_text(specific) if item_type in {3, 8, 12} else ""
                if item_type in {3, 8, 12} and specific and not is_well_formed_protobuf(specific):
                    warnings.append("corrupt text/CRDT payload")
                object_id = _uuid_text(item_uuid)
                if object_id is None:
                    raise FreeformError("board item has no identifier")
                objects.append(
                    BoardObject(
                        object_id=object_id,
                        parent_id=_uuid_text(row["parent_uuid"]),
                        item_type=item_type,
                        sub_item_type=(
                            int(row["sub_item_type"]) if row["sub_item_type"] is not None else None
                        ),
                        common_data=common,
                        specific_data=specific,
                        text=text,
                        geometry=geometry,
                        warnings=tuple(warnings),
                    )
                )
                item_type_by_id[item_uuid] = item_type
                specific_by_id[item_uuid] = specific
            ref_rows = connection.execute(
                """
                SELECT ar.referrer_identifier,ar.referrer_asset_name,ar.asset_uuid,a.extension
                FROM asset_references ar
                JOIN board_items bi ON bi.item_uuid=ar.referrer_identifier AND bi.tombstoned=0
                LEFT JOIN assets a ON a.asset_uuid=ar.asset_uuid
                WHERE ar.board_identifier=?
                ORDER BY bi.rowid,ar.referrer_asset_name,ar.asset_uuid
                """,
                (board_blob,),
            ).fetchall()
            references: list[AssetReference] = []
            for row in ref_rows:
                referrer = bytes(row["referrer_identifier"])
                asset_id = _uuid_text(row["asset_uuid"])
                object_id = _uuid_text(referrer)
                if asset_id is None or object_id is None:
                    continue
                extension = str(row["extension"] or "").lstrip(".").casefold()
                if not extension and row["referrer_asset_name"]:
                    extension = Path(str(row["referrer_asset_name"])).suffix.lstrip(".").casefold()
                role, original_name = self._asset_identity(
                    str(row["referrer_asset_name"] or "asset"),
                    extension,
                    specific_by_id.get(referrer, b""),
                    item_type_by_id.get(referrer, -1),
                )
                references.append(
                    AssetReference(
                        object_id=object_id,
                        asset_id=asset_id,
                        role=role,
                        original_name=original_name,
                        extension=extension,
                        source_path=self._asset_path(asset_id, extension),
                    )
                )
        return BoardData(
            board_id=board_id,
            title=title,
            objects=tuple(objects),
            asset_references=tuple(references),
            tombstoned_object_count=tombstoned_count,
            schema_version=version,
            schema_fingerprint=fingerprint,
            last_activity_time=(
                float(board["last_activity_time"])
                if board["last_activity_time"] is not None
                else None
            ),
        )
