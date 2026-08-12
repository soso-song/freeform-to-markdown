"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .archive import archive_board, refine_archive
from .skill import install_skill
from .source import BoardNotFoundError, FreeformSource, UnsupportedSchemaError
from .verify import verify_archive


def _source(*, allow_experimental_schema: bool = False) -> FreeformSource:
    return FreeformSource(allow_experimental_schema=allow_experimental_schema)


def _add_experimental_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-experimental-schema",
        action="store_true",
        help="Explicitly allow a compatible but unverified schema fingerprint",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freeform-to-markdown",
        description="Archive Apple Freeform boards into searchable, verifiable files.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="Check source access and compatibility")
    _add_experimental_flag(doctor)
    boards = subparsers.add_parser("boards", help="List available Freeform boards")
    _add_experimental_flag(boards)
    archive = subparsers.add_parser("archive", help="Create an archive-schema 1.0 directory")
    _add_experimental_flag(archive)
    archive.add_argument("--board", help="Exact board title or stable board UUID")
    archive.add_argument("--output", "-o", type=Path, default=Path.cwd())
    archive.add_argument(
        "--board-preview",
        type=Path,
        help="Optional official Freeform PDF export used as the visual baseline",
    )
    refine = subparsers.add_parser("refine", help="Apply a reviewed Scene map")
    refine.add_argument("archive", type=Path)
    refine.add_argument("--scene-map", required=True, type=Path)
    verify = subparsers.add_parser("verify", help="Verify an existing archive")
    verify.add_argument("archive", type=Path)
    install = subparsers.add_parser("install-skill", help="Install the bundled agent Skill")
    install.add_argument("--target", choices=("codex", "claude", "both"), default="codex")
    return parser


def _select_interactive(source: FreeformSource) -> str:
    boards = source.list_boards()
    if not boards:
        raise BoardNotFoundError("no Freeform boards found")
    if not sys.stdin.isatty():
        if len(boards) == 1:
            return boards[0].board_id
        raise BoardNotFoundError("--board is required when input is not interactive")
    for index, board in enumerate(boards, 1):
        print(f"{index}. {board.title} ({board.object_count} objects)")
    selected = input("Select a board number: ").strip()
    try:
        return boards[int(selected) - 1].board_id
    except (IndexError, ValueError) as error:
        raise BoardNotFoundError("invalid board selection") from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = _source(allow_experimental_schema=args.allow_experimental_schema).doctor()
            print(
                json.dumps(
                    {
                        "platform": platform.system(),
                        "schema_user_version": report.schema_version,
                        "schema_fingerprint": report.schema_fingerprint,
                        "status": report.schema_status,
                        "database_readable": report.database_readable,
                        "assets_readable": report.assets_readable,
                        "local_ocr_available": report.ocr_available,
                        "errors": list(report.errors),
                        "warnings": list(report.warnings),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return (
                0 if report.supported and report.database_readable and report.assets_readable else 1
            )
        if args.command == "boards":
            source = _source(allow_experimental_schema=args.allow_experimental_schema)
            for board in source.list_boards():
                print(
                    f"{board.board_id}\t{board.object_count} objects\t"
                    f"{board.asset_reference_count} asset refs\t{board.title}"
                )
            return 0
        if args.command == "archive":
            source = _source(allow_experimental_schema=args.allow_experimental_schema)
            selector = args.board or _select_interactive(source)
            archive = archive_board(
                source,
                selector,
                args.output,
                board_preview=args.board_preview,
            )
            print(archive)
            archive_verification = verify_archive(archive)
            if not archive_verification.ok:
                print(
                    "archive created, but verification failed; review Manifest/verification.json",
                    file=sys.stderr,
                )
                return 1
            return 0
        if args.command == "refine":
            print(refine_archive(args.archive, args.scene_map))
            return 0
        if args.command == "verify":
            verification = verify_archive(args.archive)
            print("verified: PASS" if verification.ok else "verified: FAIL")
            for error in verification.errors:
                print(f"- {error}")
            return 0 if verification.ok else 1
        if args.command == "install-skill":
            for destination in install_skill(args.target):
                print(destination)
            return 0
    except (
        BoardNotFoundError,
        FileExistsError,
        FileNotFoundError,
        OSError,
        UnsupportedSchemaError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
