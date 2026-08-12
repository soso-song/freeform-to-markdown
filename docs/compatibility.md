# Compatibility

Support is declared by Freeform database schema fingerprint and demonstrated capability, not only
by the marketing name of macOS.

## Matrix

| Freeform source | Reported status | Baseline extraction | Notes |
| --- | --- | --- | --- |
| `user_version=16` with a verified structural fingerprint | `verified` | Objects, text, asset references, bounds, parent groups, and conservative spatial relations | Public synthetic fixtures exercise one verified fingerprint; maintainers may also run private local-only regression without uploading source data. |
| Structurally compatible v16 with an unrecognized fingerprint, without opt-in | `unsupported` | None | Disabled by default. Review the risk before using the experimental flag. |
| Structurally compatible v16 with an unrecognized fingerprint and `--allow-experimental-schema` | `experimental` | Same adapter, without a compatibility guarantee | The flag must be passed to each `doctor`, `boards`, or `archive` command that needs the source. |
| v16 missing a required table column | `unsupported` | None | The experimental flag cannot bypass a structural incompatibility. |
| Any other `user_version` | `unsupported` | None | The experimental flag cannot bypass an unsupported version. |
| Official Freeform PDF supplied by the user | Supplemental | Visual baseline only | `archive --board-preview FILE.pdf` copies it into the archive; it does not replace object or asset manifests. |

Run `freeform-to-markdown doctor` after every substantial macOS or Freeform update. A matching
`user_version` alone does not prove compatibility because tables and payload encodings may change
without that number changing.

## Capability reporting

`doctor` reports the platform, schema version and fingerprint, one of the statuses above,
database and Assets readability, local OCR availability, errors, and warnings. It creates a
stability-checked copy of the database and WAL before inspecting the copied database read-only;
it does not open the live SQLite database.

Each archive separately records whether text, geometry, assets, spatial relations, a visual
baseline, and local OCR are available, plus whether OCR was actually used. Individual asset
records carry extraction methods and warnings so consumers can distinguish absent searchable text
from an unavailable or failed extractor.

Status meanings:

- **Verified**: exercised by synthetic fixtures and integration tests for the exact fingerprint.
- **Experimental**: required columns are present on v16, but the exact fingerprint has not been
  verified. Export is allowed only after explicit operator opt-in.
- **Unsupported**: no safe adapter exists; export is refused.

## Adding support

Do not share a real database. Open a schema compatibility report containing only sanitized
`doctor` output and then contribute a fixture created from scratch. The fixture and golden output
must cover recognized fields, unknown fields, missing assets, and source-integrity checks. See
[CONTRIBUTING.md](../CONTRIBUTING.md#synthetic-fixture-rules).

## Inherent limitations

Apple does not publish a complete editable interchange specification for Freeform. Even on a
verified schema, the archive does not promise exact reconstruction of drawing strokes, stacking,
application-private state, or the original interactive board. Retain the source board and an
official PDF/Scene baseline when visual fidelity matters.
