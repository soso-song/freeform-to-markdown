# Privacy model

Freeform boards often mix documents, photographs, identifiers, and informal notes. The project
treats privacy as an archive invariant rather than an optional post-processing step.

## Local-only baseline

The core exporter does not send board content to a network service. Database parsing, hashing,
PDF text extraction, Apple Vision OCR, manifest generation, and verification run locally. There is
no telemetry, analytics, account login, or cloud-AI dependency.

The optional Codex/Claude Skill invokes this same CLI. An agent or third-party environment may have
its own data-handling policy; review that policy before allowing it to inspect a sensitive archive.

## Source safety

- Source discovery and checks happen before extraction.
- Database and WAL files are copied only after before/after stability signatures match. If they
  keep changing, the operation stops.
- The live SQLite database is never opened. Only the temporary copy is opened, with SQLite
  read-only and query-only controls.
- Asset reads accept only regular, non-symlink files that resolve inside Freeform's Assets
  directory.
- Original asset bytes are copied without transformation and checked with SHA-256.
- Integration tests compare the complete synthetic source tree before and after read operations;
  runtime extraction never opens a source file for writing.
- Temporary working data is placed in a restrictive directory and removed on normal completion.

No tool can replace a backup. Keep valuable source boards backed up before using any archival
workflow.

## Ordinary output versus originals

Generated indexes, OCR, filenames, selected manifest values, and exception messages are ordinary
output. During generation, common credentials, sensitive URL parameters, private test URLs, and
selected identifier patterns are filtered. `verify` also scans generated Markdown, JSON, JSONL,
and YAML for recognized credential assignments and absolute user-home paths; a finding fails
verification and cannot be waived by accepting an unresolved object.

Original attachments are evidence and remain unmodified. They may still contain sensitive visual
or embedded information. Store the entire archive with access controls appropriate for the most
sensitive original it contains.

Filtering reduces accidental disclosure; it is not guaranteed anonymization. Review generated
text before sharing an archive.

## Network and extension behavior

Baseline archive creation does not fetch link cards, remote images, or external metadata. Original
URL strings already present in a decoded link object may be preserved only after ordinary-output
filtering. Version 0.1 has no network-backed extractor; image OCR, PDF extraction, and media
metadata collection are local.

## Public contribution boundary

Never publish a real board or a transformed copy of one to this repository. Redaction may miss
deleted pages, EXIF fields, thumbnails, SQLite freelists, WAL records, embedded text, or private
identifiers. Public fixtures must be authored from scratch with synthetic databases and generated
assets.

Use GitHub private vulnerability reporting for suspected data exposure. See
[SECURITY.md](../SECURITY.md).
