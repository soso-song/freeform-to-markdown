# Scene map format

`scene-map.yml` is the small, reviewable interface between deterministic spatial clustering and a
human-verified event structure. It changes labels and Scene membership without copying or editing
original attachments.

## Minimal example

```yaml
scenes:
  - id: research
    title: Research Notes
    object_ids:
      - 00000000-0000-4000-8000-000000000201
      - 00000000-0000-4000-8000-000000000202
accepted_exceptions:
  - object_id: 00000000-0000-4000-8000-000000000299
    reason: The referenced synthetic attachment is intentionally unavailable.
```

Each Scene contains:

| Scene field | Portable maps | Behavior |
| --- | --- | --- |
| `id` | Required | Normalized to a path-safe key; normalized keys must be unique. |
| `title` | Required | Filtered human-readable label used in indexes. |
| `object_ids` | Required | Source object identities already present in `objects.jsonl`. |

`refine` rejects unknown object identities, duplicate normalized Scene IDs, and assigning an object
to more than one reviewed Scene. Scene IDs are normalized rather than used as raw paths. The
regenerated index is ordered by normalized Scene ID, so YAML list order does not control navigation.

Objects omitted from the map retain their existing automatic Scene. Applying a map updates Scene
indexes, object `scene` values, text canonical paths, spatial relationships, checksums, and the
verification report; `Originals/` remains byte-identical.

## Accepted unresolved objects

`accepted_exceptions` is optional. Each entry has exactly two meaningful fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `object_id` | Yes | One known object whose disposition is still `unresolved`. |
| `reason` | Yes | A non-empty, filtered explanation of why the known gap is acceptable. |

An unresolved object may be accepted only once. Unknown IDs, non-unresolved objects, duplicate
acceptance, and empty reasons are rejected. Acceptance does not change the disposition or claim
that extraction succeeded. It adds review evidence to `objects.jsonl` and marks the related
exception as accepted.

The list is authoritative for that refinement run. If a previously accepted object is omitted,
its acceptance is removed. `verify` reports `accepted_unresolved_count` separately and passes the
unresolved-object check only when every unresolved object is accepted. Other verification failures
still fail.

Always run `verify` after refinement even though `refine` performs one verification pass itself.
