# Archive schema 1.0

This document defines the portable output contract for `freeform-to-markdown`. It describes what
consumers can rely on, not Freeform's private database schema.

## Design goals

- Preserve original attachment bytes and searchable representations.
- Separate observed facts from inferred spatial relationships.
- Keep every discovered object accountable.
- Make archives readable without this program.
- Support deterministic verification and forward-compatible extension.

## Directory contract

```text
<board-name>/
├── 00 Search Index.md
├── scene-map.yml
├── Board/
│   ├── board-preview.pdf       # optional user-supplied Freeform PDF
│   ├── layout.json
│   └── source-metadata.json
├── Scenes/
├── Originals/
├── Extracted/
└── Manifest/
    ├── archive.json
    ├── objects.jsonl
    ├── assets.jsonl
    ├── relations.jsonl
    ├── exceptions.jsonl
    ├── verification.json
    └── SHA256SUMS
```

Paths in manifests are slash-separated and relative to the archive root. Producers must not emit
absolute paths, `..` segments, or links that escape the archive.

`Board/board-preview.pdf` exists only when the operator supplies a Freeform PDF export with
`archive --board-preview`. The tool validates and copies the PDF; it does not generate one.
Absence is reported as an informational record in `exceptions.jsonl` and does not make the content
archive invalid. `layout.json` remains the machine-readable geometric baseline.

## Versioning

`archive.json` contains `archive_schema: "1.0"`. Additive optional fields may be introduced in a
minor release. Removing a field, changing its type or meaning, or changing required dispositions
requires a new archive-schema version and a documented migration.

Consumers must ignore unknown fields and reject an unsupported `archive_schema` major version.
Producers must emit UTF-8 JSON with stable key ordering and one complete object per JSONL line.

## `archive.json`

Required top-level metadata:

| Field | Type | Meaning |
| --- | --- | --- |
| `archive_schema` | string | Archive contract version; `1.0` for this release. |
| `board_title` | string | Filtered source board title retained for human navigation. |
| `generator` | object | Program name and version. |
| `created_at` | string | RFC 3339 timestamp. |
| `source` | object | Sanitized source kind, schema version, and structural fingerprint. |
| `board` | object | Stable source board key and filtered display title. |
| `counts` | object | Active objects, attachment references, tombstoned-object count, and dispositions. |
| `capabilities` | object | Features observed or successfully extracted. |
| `known_losses` | array | Explicit limitations for this archive. |

No source database path, device username, credential, or private temporary path belongs in this
file.

`Board/source-metadata.json` records the schema version, confirms that source paths were omitted,
and describes the visual baseline as `provided` (with archive path and SHA-256) or `not provided`.
`Board/layout.json` records the board key plus each active object's normalized type, parent,
bounds, initial automatic Scene, and stable source order. Reviewed Scene assignments live in
`objects.jsonl` and `scene-map.yml`; refinement does not rewrite the geometric baseline.

## Object records

Each line of `objects.jsonl` accounts for one discovered board object.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `object_id` | string | Yes | Stable source identity, normalized for the archive. |
| `type` | string | Yes | Observed or adapter-normalized object type. |
| `parent_id` | string/null | Yes | Parent/group identity when observed. |
| `bounds` | object/null | Yes | Canvas `x`, `y`, `width`, and `height` when available. |
| `text` | string/null | Yes | Extracted visible text after ordinary-output filtering. |
| `scene` | string | Yes | Scene key assigned by deterministic clustering or review. |
| `disposition` | string | Yes | One of the four values below. |
| `canonical_path` | string/null | Yes | Searchable record or original representing the object. |
| `verification` | object | Yes | Checks performed and their result. |
| `warnings` | array | Yes | Non-fatal limitations; empty when none. |
| `accepted_exception` | object | No | Review reason and `reviewed_via: scene-map.yml` for an explicitly accepted unresolved object. |

Allowed dispositions:

- `filed`: represented by a canonical original, searchable record, or both.
- `context-only`: preserved as layout/visual context without asserting business meaning.
- `duplicate`: intentionally points to an existing canonical record or asset.
- `unresolved`: could not be interpreted or recovered; the reason is recorded.

An exporter must never omit a discovered object because it is blank, distant, hidden, malformed,
or unfamiliar.

## Asset records

Each line of `assets.jsonl` represents one source attachment reference. Its stable baseline fields
are `asset_id`, `source_asset_id`, `object_id`, `role`, `source_name`, `media_type`, `sha256`,
`size`, `archive_path`, `extracted_path`, `duplicate_of`, `verification`, and `warnings`.
Canonical records may also include `extraction_method` and `technical_metadata`; duplicate records
reuse the canonical paths and identify that record with `duplicate_of`.

- `archive_path` points to unmodified bytes in `Originals/`.
- `extracted_path` points to Markdown or text in `Extracted/`, or is `null` with a warning.
- `duplicate_of` points to the canonical asset record when bytes share the same SHA-256.
- Multiple object references may point to one canonical original without copying it.

## Relationship records

Each line of `relations.jsonl` contains:

| Field | Meaning |
| --- | --- |
| `relation_id` | Stable key derived from relation type, source, and target. |
| `source` | Object, asset, or Scene key where the relation starts. |
| `target` | Object, asset, or Scene key where the relation ends. |
| `relation_type` | Specific producer type such as `group-membership` or `spatial-near`. |
| `type` | Portable type: `contains`, `overlaps`, `near`, `possible-comment-for`, or `duplicate-of`. |
| `scene` | Related Scene when applicable. |
| `evidence` | Source field, geometry, distance, or identical hash supporting the record. |
| `reason` | Human-readable statement of what is and is not asserted. |
| `confidence` | `observed`, `medium`, or `low`. |
| `distance` | Canvas edge gap for spatial records; otherwise `null`. |

Parent membership and geometric overlap are observations. `near` is limited to reciprocal nearest
neighbours within one Scene. `possible-comment-for` is a low-confidence candidate emitted only
when a text/sticky object has one unique nearest non-text neighbour; ties are not guessed. Spatial
proximity must never be presented as an observed semantic fact.

## Scenes and extracted files

Each `Scenes/<scene-key>/00 Scene.md` identifies member objects, their searchable text, warnings,
and canonical-record links. Relationship evidence remains in `relations.jsonl`. Scene keys are
stable within an archive unless a reviewed `scene-map.yml` changes membership. Human labels may
change through `refine` without changing object or asset identities.

Extracted sidecars use the same safe basename as their original plus `_extracted.md`. They identify
the source asset record, original hash, extraction method, local technical metadata, searchable
text, and warnings. Images use local Apple Vision OCR when available. PDFs use their text layer
first and local OCR only for pages without searchable text. Audio and video sidecars contain local
technical metadata but are not transcribed in archive-schema 1.0.

## Exceptions and verification

`exceptions.jsonl` records missing assets, unresolved objects, decode limitations, unsupported
object types, and absence of a supplied visual baseline. Each record contains severity, a
machine-readable code, related record keys when applicable, and a human-readable message without
secret values.

When a reviewer accepts an unresolved object in `scene-map.yml`, the related exception receives
`accepted: true` and a filtered `acceptance_reason`. The object remains `unresolved`; acceptance
records a reviewed limitation instead of pretending that extraction succeeded.

`verification.json` records overall status, failure messages, and counts for checks including:

- required archive files;
- object disposition coverage;
- canonical object-path existence;
- asset-to-object references and relation endpoints;
- duplicate targets and hash/path agreement;
- orphan files below `Originals/` and `Extracted/`;
- original asset SHA-256;
- entries in `SHA256SUMS`;
- archive-internal Markdown links;
- absolute user-path and credential scanning in ordinary generated text;

`verify` exits non-zero for a failed invariant or any remaining `unresolved` object unless the user
explicitly accepts that exception in a reviewed Scene map.

`SHA256SUMS` covers every file below `Originals/`, `Extracted/`, and `Board/`, plus
`archive.json`, `objects.jsonl`, `assets.jsonl`, `relations.jsonl`, and `exceptions.jsonl`.
Search indexes, `scene-map.yml`, `verification.json`, and the checksum file itself are excluded.
