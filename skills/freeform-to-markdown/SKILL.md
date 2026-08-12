---
name: freeform-to-markdown
description: Archive Apple Freeform boards into searchable Markdown, original attachments, OCR or extracted text, spatial Scenes, relationships, and verifiable manifests using the local freeform-to-markdown CLI. Use when a user asks to export, archive, digest, preserve, investigate, or convert a Freeform board into searchable folders; reconcile a board with an existing document archive; verify that board objects were not missed; or retain layout context while moving knowledge out of Freeform.
---

# Archive Freeform Boards

Use the deterministic `freeform-to-markdown` CLI as the implementation. Do not reimplement its
database parser or asset exporter in the agent workflow.

## 1. Preflight

1. Run `freeform-to-markdown doctor`.
2. Stop on missing source access, inconsistent snapshot support, or an unsupported schema.
   If `doctor` reports a structurally compatible but unverified v16 fingerprint, do not silently
   opt in. Explain the risk and use `--allow-experimental-schema` only after the operator explicitly
   accepts it; pass the flag again to `boards` and `archive`.
3. Explain how to grant macOS Full Disk Access when needed; do not bypass system permissions.
4. Run `freeform-to-markdown boards` and resolve the requested board by stable selector. If two
   titles match, use the selector rather than guessing.
5. Choose an explicit output directory outside Freeform's data container. Never overwrite a
   non-empty archive.

## 2. Create the baseline

Run:

```bash
freeform-to-markdown archive --board "BOARD_SELECTOR" --output "OUTPUT_DIRECTORY"
```

If the user already exported an official Freeform PDF, preserve it with
`--board-preview "PDF_PATH"`. The CLI copies and hashes the PDF; it does not generate one.

Treat the generated baseline as evidence:

- Never edit or move objects in the source board.
- Never write to `boards.db`, its WAL/SHM state, or the Freeform Assets directory.
- Keep original attachments byte-for-byte and let the CLI deduplicate by SHA-256.
- Never send board content to cloud OCR or an external service.
- Do not remove an `unresolved` record to make verification pass.

Review `00 Search Index.md`, `Manifest/archive.json`, `Manifest/exceptions.jsonl`, and the initial
verification report before semantic refinement.

## 3. Verify spatial Scenes

Use a user-provided official Freeform PDF or permitted UI view as the visual baseline. If neither
is available, retain the automatic Scenes and report that visual verification was not possible.
Do not claim exact editable-board reconstruction.

Work Scene by Scene:

1. Compare object count and type with the visual baseline.
2. Check visible text, OCR, image orientation, crop, and attachment readability.
3. Associate comments only when a connector, group, overlap, or clear proximity supports it.
4. Check Scene boundaries for small, distant, white, overlapped, or cross-Scene objects.
5. Confirm that decorative shapes remain `context-only`; do not turn them into facts.
6. Keep uncertain or missing content `unresolved`. Never edit a manifest to hide it.

After every three to five Scenes, search representative facts and reconcile object, asset, and
relation manifests. Preserve both observed relationships and the basis for spatial inferences.

Edit only the generated `scene-map.yml`, then apply the review:

```bash
freeform-to-markdown refine "ARCHIVE_DIRECTORY" --scene-map "scene-map.yml"
```

Use `accepted_exceptions` only for a known `unresolved` object that cannot be recovered and whose
gap the operator has reviewed. Each entry needs the exact object ID and a useful reason. Do not
accept an exception merely to make verification pass.

## 4. Verify and report

Run:

```bash
freeform-to-markdown verify "ARCHIVE_DIRECTORY"
```

Do not declare completion until:

- every discovered object is `filed`, `context-only`, `duplicate`, or `unresolved`;
- original assets pass SHA-256 checks and canonical object paths exist;
- required archive files, canonical object paths, checksums, and Markdown links pass verification;
- duplicate asset records reuse one canonical original and declare `duplicate-of` relations;
- ordinary indexes contain no recognized passwords, tokens, private session URLs, or sensitive
  identifiers; and
- every failure or known loss is visible in the archive, exception, or verification records.

Report the archive entry point, object/asset/disposition counts, unresolved and accepted-unresolved
counts, privacy findings, and whether Scene verification used a PDF, a live visual view, or no
baseline. State that the source board remains the visual source of truth for exact coordinates,
layers, drawing strokes, and application-private behavior.

## Integrate with an existing document archive

When the user already has an archive structure, read its local instructions before filing. Keep
one canonical original, link event notes back to it, and update existing indexes instead of
creating a parallel island. Preserve the generated manifest as the object-level audit trail.
