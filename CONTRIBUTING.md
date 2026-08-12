# Contributing

Thank you for helping make Freeform archives more portable, searchable, and verifiable.

## Privacy is part of correctness

Do not upload, commit, paste, or link to real Freeform data. This prohibition includes:

- `boards.db`, WAL/SHM files, and files copied from Freeform's Assets directory;
- board identifiers, screenshots, exported boards, or object payloads from a real board;
- names, addresses, medical or travel details, credentials, private URLs, and account numbers;
- a "redacted" real fixture whose original bytes or metadata may still reveal private data.

Issues and pull requests must use fixtures generated from scratch for this project. If a bug only
occurs with private data, reduce it locally to a minimal synthetic fixture before reporting it.
Maintainers will close reports that place someone's data at risk.

## Set up a development environment

Requirements: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and macOS for Freeform and
Apple Vision integration tests. Platform-independent parser and manifest tests run on Linux.

```bash
git clone https://github.com/soso-song/freeform-to-markdown.git
cd freeform-to-markdown
uv sync --all-extras
uv run ruff check .
uv run mypy src
uv run pytest
uv run pip-audit
uv build
uv run python scripts/privacy_scan.py
```

Run the Skill validator after changing the bundled Skill:

```bash
make skill-check
```

## Choose the right contribution

- Use a bug report for reproducible incorrect output from a supported schema.
- Use a schema compatibility report when `doctor` identifies an experimental or unsupported
  fingerprint.
- Use a feature request for new output, extractor, or workflow behavior.
- Start a Discussion for design questions before a large architectural change.
- Report security and privacy vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Synthetic fixture rules

A schema or parser change must include a minimal synthetic fixture and deterministic golden
output. Build both from invented content—never by sanitizing a real database.

1. Create the smallest database, WAL state, and asset set that exercises the behavior.
2. Use plainly fictional text, local example-domain URLs, and generated media.
3. Avoid realistic personal identifiers, secrets, or full random identifiers copied from a device.
4. Document which schema fingerprint and capability the fixture represents.
5. Add golden `objects`, `assets`, `relations`, index, and verification outputs as applicable.
6. Confirm the test covers failure behavior for missing or malformed input.
7. Run the privacy scanner before committing.

Unknown fields must remain opaque or unresolved until their meaning is demonstrated by a
synthetic fixture. Never infer a field's semantics from a single private board.

## Implementation expectations

- Keep the Freeform source strictly read-only and prove that source hashes do not change.
- Route schema-specific behavior through an adapter selected by a fingerprint.
- Make extraction deterministic; optional enhancements must not change baseline identity fields.
- Preserve original asset bytes and deduplicate by SHA-256.
- Account for every object with one of the four dispositions: `filed`, `context-only`,
  `duplicate`, or `unresolved`.
- Fail closed on unknown schemas. Surface missing assets and decode errors.
- Keep the CLI independent from the bundled agent Skill.
- Update the archive schema and compatibility documentation with behavior changes.
- Add a migration note when a change affects existing archives.

## Pull request process

1. Keep each pull request focused and explain the user-visible behavior.
2. Add or update tests and documentation.
3. Run all local quality gates relevant to your platform.
4. Complete the privacy and source-integrity checklist in the pull request template.
5. Allow maintainers to edit the branch when practical.
6. Address review comments with new commits; maintainers squash on merge.

All required CI checks must pass. At least one maintainer approval is required. A pull request may
be declined when it creates privacy risk, weakens fail-closed behavior, lacks synthetic evidence,
or expands the public archive contract without a migration path.

By contributing, you license your contribution under Apache-2.0. This project does not require a
separate contributor license agreement or Developer Certificate of Origin sign-off.
