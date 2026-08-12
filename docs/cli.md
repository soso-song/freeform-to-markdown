# CLI reference

Both executable names are equivalent:

```bash
freeform-to-markdown --help
ff2md --help
```

## `doctor`

```bash
ff2md doctor [--allow-experimental-schema]
```

Reports the platform and checks Freeform source discovery, read permissions, a stability-checked
database/WAL snapshot, schema version and fingerprint, Assets readability, and Apple Vision OCR
availability. It does not create an archive. Paths and board content are excluded from normal
output.

Exit status is zero when baseline export requirements are satisfied and non-zero when permission,
source integrity, or schema support blocks a safe export.

For a structurally compatible v16 schema whose exact fingerprint is not verified, the default
status is `unsupported`. Pass `--allow-experimental-schema` only after reviewing the compatibility
risk; the resulting status is `experimental`. The flag does not bypass missing columns or a
different `user_version`.

## `boards`

```bash
ff2md boards [--allow-experimental-schema]
```

Lists board titles, stable selectors, active object counts, and attachment-reference counts from a
temporary read-only snapshot. Use a reported selector with `archive` when titles are duplicated.

## `archive`

```bash
ff2md archive [--board ID_OR_TITLE] [--output DIRECTORY] \
  [--board-preview OFFICIAL_FREEFORM_EXPORT.pdf] \
  [--allow-experimental-schema]
```

Creates a new archive-schema 1.0 directory. With no `--board`, an interactive terminal prompts for
a board. The default output is a new directory below the current working directory. Existing
non-empty output is not overwritten.

The command fails closed for an unsupported schema. Extraction-level problems are recorded as
warnings or `unresolved`; source-snapshot or path-safety failures stop the operation. The archive
directory remains available for review, but the command exits non-zero when its verification pass
finds an unresolved object or another failed invariant.

`--board-preview` accepts an existing PDF exported by Freeform. The command validates the PDF
header, copies the file byte-for-byte to `Board/board-preview.pdf`, records its SHA-256 in source
metadata, and includes it in `SHA256SUMS`. The exporter does not generate this PDF. Without the
option, `layout.json` remains the baseline and an informational exception records the omission.

## `refine`

```bash
ff2md refine ARCHIVE --scene-map scene-map.yml
```

Applies reviewed Scene labels and membership plus explicitly accepted unresolved objects. Object
and asset identity remain stable. Original attachments are not copied or rewritten. Unknown
object IDs, duplicate normalized Scene IDs, cross-Scene duplicate membership, malformed accepted
exceptions, and empty acceptance reasons are rejected. Spatial relations and text canonical paths
are recalculated for the reviewed Scenes.

An accepted exception must name one known `unresolved` object exactly once and include a reason.
The Scene map is the complete reviewed exception set: omitting a previously accepted object removes
its acceptance. See [Scene map format](scene-map.md).

## `verify`

```bash
ff2md verify ARCHIVE
```

Rechecks required archive files, allowed object dispositions, canonical object paths, asset object
references and relation endpoints, duplicate targets, orphan originals/extractions, original asset
SHA-256 values, `SHA256SUMS`, internal Markdown links, leaked absolute user paths, ordinary-output
credential findings, and unresolved items. Accepted unresolved objects are counted separately and
do not fail the unresolved-object check. The command rewrites only
`Manifest/verification.json` and exits non-zero when a checked invariant fails.

## `install-skill`

```bash
ff2md install-skill --target codex|claude|both
```

Installs the bundled agent workflow. `both` keeps one canonical Skill and uses a relative symlink
for the second tool when the target layout supports it. Existing divergent Skill files are not
silently overwritten; the command reports the conflict and requires the operator to resolve it.
