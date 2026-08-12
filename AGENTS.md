# Repository instructions

This is a public, privacy-first macOS tool that exports Apple Freeform boards into searchable Markdown archives.

## Non-negotiable rules

- Never commit real Freeform databases, assets, board identifiers, user names, medical data, travel data, credentials, private URLs, or absolute paths from a developer machine.
- Use only synthetic fixtures created specifically for this repository.
- Open Freeform sources read-only. Never modify `boards.db`, its WAL/SHM files, or the Freeform Assets directory.
- Unknown schemas and missing assets must be reported, never silently guessed or skipped.
- Every board object must end as `filed`, `context-only`, `duplicate`, or `unresolved`.
- Keep the deterministic CLI independent from the optional Codex Skill.
- Use `apply_patch` for source and documentation edits.

## Architecture

- `src/freeform_to_markdown/`: CLI, source adapters, extraction, archive writer, verifier.
- `tests/`: synthetic SQLite/asset fixtures and golden outputs only.
- `skills/freeform-to-markdown/`: reusable Codex/Claude workflow; no duplicate implementation.
- `docs/`: archive schema, architecture, compatibility, and privacy details.

## Quality gate

Run `uv run ruff check .`, `uv run mypy src`, `uv run pytest`, `uv build`, and the skill validator before release. Public history must pass the repository privacy scanner.
