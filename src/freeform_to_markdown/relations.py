"""Conservative relation inference from explicit parents and canvas geometry.

The module deliberately separates observations (parent fields and overlap) from
inferences (nearby or possible-comment relationships).  Proximity is evidence,
not proof that two Freeform objects share a semantic meaning.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict

from .models import BoardObject, Geometry


class RelationRecord(TypedDict):
    """Portable relation record suitable for ``relations.jsonl``."""

    relation_id: str
    source: str
    target: str
    relation_type: str
    type: str
    scene: str | None
    evidence: str
    reason: str
    confidence: Literal["observed", "medium", "low"]
    distance: float | None


def _relation_id(relation_type: str, source: str, target: str) -> str:
    identity = "\0".join((relation_type, source, target)).encode("utf-8")
    return f"relation-{relation_type}-{hashlib.sha256(identity).hexdigest()[:16]}"


def _record(
    *,
    relation_type: str,
    portable_type: str,
    source: str,
    target: str,
    scene: str | None,
    evidence: str,
    reason: str,
    confidence: Literal["observed", "medium", "low"],
    distance: float | None = None,
) -> RelationRecord:
    return {
        "relation_id": _relation_id(relation_type, source, target),
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "type": portable_type,
        "scene": scene,
        "evidence": evidence,
        "reason": reason,
        "confidence": confidence,
        "distance": round(distance, 6) if distance is not None else None,
    }


def _edge_gap(left: Geometry, right: Geometry) -> float:
    horizontal = max(
        left.x - (right.x + right.width),
        right.x - (left.x + left.width),
        0.0,
    )
    vertical = max(
        left.y - (right.y + right.height),
        right.y - (left.y + left.height),
        0.0,
    )
    return math.hypot(horizontal, vertical)


def _overlap_area(left: Geometry, right: Geometry) -> float:
    width = max(
        0.0,
        min(left.x + left.width, right.x + right.width) - max(left.x, right.x),
    )
    height = max(
        0.0,
        min(left.y + left.height, right.y + right.height) - max(left.y, right.y),
    )
    return width * height


def _same_scene(
    left: BoardObject,
    right: BoardObject,
    scene_by_object: Mapping[str, str],
) -> str | None:
    left_scene = scene_by_object.get(left.object_id)
    right_scene = scene_by_object.get(right.object_id)
    if left_scene is None or left_scene != right_scene:
        return None
    return left_scene


def infer_relations(
    objects: Sequence[BoardObject],
    scene_by_object: Mapping[str, str],
    *,
    max_near_gap: float = 120.0,
    tie_tolerance: float = 1e-6,
) -> list[RelationRecord]:
    """Infer deterministic parent, overlap, near, and possible-comment records.

    Spatial records are limited to objects assigned to the same Scene. ``near``
    requires reciprocal nearest-neighbour evidence, while ``possible-comment-for``
    requires a text or sticky object to have one unique nearest non-text object.
    A tie never becomes a possible-comment relationship.
    """

    if not math.isfinite(max_near_gap) or max_near_gap < 0:
        raise ValueError("max_near_gap must be a finite non-negative number")
    if not math.isfinite(tie_tolerance) or tie_tolerance < 0:
        raise ValueError("tie_tolerance must be a finite non-negative number")

    ordered = sorted(objects, key=lambda item: item.object_id)
    by_id = {item.object_id: item for item in ordered}
    if len(by_id) != len(ordered):
        raise ValueError("object identifiers must be unique")

    records: list[RelationRecord] = []
    direct_parent_pairs: set[frozenset[str]] = set()
    for item in ordered:
        if item.parent_id is None or item.parent_id not in by_id:
            continue
        parent = by_id[item.parent_id]
        relation_type = "group-membership" if parent.item_type == 2 else "parent-membership"
        records.append(
            _record(
                relation_type=relation_type,
                portable_type="contains",
                source=parent.object_id,
                target=item.object_id,
                scene=scene_by_object.get(item.object_id),
                evidence="Freeform parent identifier on the child object",
                reason="The source data explicitly records this parent-child membership.",
                confidence="observed",
            )
        )
        direct_parent_pairs.add(frozenset((parent.object_id, item.object_id)))

    # Groups usually enclose their children and would create a noisy overlap
    # edge to every member. Preserve their explicit membership above instead.
    geometric = [item for item in ordered if item.geometry is not None and item.item_type != 2]
    pair_distance: dict[tuple[str, str], float] = {}
    nearest: dict[str, float] = {}
    overlap_pairs: set[tuple[str, str]] = set()
    for index, left in enumerate(geometric):
        assert left.geometry is not None
        for right in geometric[index + 1 :]:
            assert right.geometry is not None
            scene = _same_scene(left, right, scene_by_object)
            if scene is None:
                continue
            pair = (left.object_id, right.object_id)
            if frozenset(pair) in direct_parent_pairs:
                continue
            area = _overlap_area(left.geometry, right.geometry)
            if area > 0:
                overlap_pairs.add(pair)
                records.append(
                    _record(
                        relation_type="spatial-overlap",
                        portable_type="overlaps",
                        source=left.object_id,
                        target=right.object_id,
                        scene=scene,
                        evidence=f"axis-aligned bounds overlap by {area:.6f} square canvas units",
                        reason=(
                            "Geometry overlaps; stacking order and semantic association are not "
                            "inferred."
                        ),
                        confidence="observed",
                        distance=0.0,
                    )
                )
            distance = _edge_gap(left.geometry, right.geometry)
            if distance <= max_near_gap:
                pair_distance[pair] = distance
                nearest[left.object_id] = min(nearest.get(left.object_id, math.inf), distance)
                nearest[right.object_id] = min(nearest.get(right.object_id, math.inf), distance)

    for (left_id, right_id), distance in sorted(pair_distance.items()):
        if (left_id, right_id) in overlap_pairs:
            continue
        if not (
            math.isclose(distance, nearest[left_id], abs_tol=tie_tolerance, rel_tol=0.0)
            and math.isclose(distance, nearest[right_id], abs_tol=tie_tolerance, rel_tol=0.0)
        ):
            continue
        scene = scene_by_object[left_id]
        records.append(
            _record(
                relation_type="spatial-near",
                portable_type="near",
                source=left_id,
                target=right_id,
                scene=scene,
                evidence=(
                    f"edge gap {distance:.6f} canvas units; reciprocal nearest neighbours "
                    f"within Scene {scene!r}"
                ),
                reason="Proximity only; no semantic association is asserted.",
                confidence="medium",
                distance=distance,
            )
        )

    # A comment candidate is intentionally directional and weaker than a near
    # record. Equal-distance candidates are ambiguous and therefore omitted.
    text_types = {3, 12}
    for source in geometric:
        if source.item_type not in text_types or not source.text.strip():
            continue
        candidates: list[tuple[float, str]] = []
        for target in geometric:
            if target.object_id == source.object_id or target.item_type in {*text_types, 2}:
                continue
            if _same_scene(source, target, scene_by_object) is None:
                continue
            if frozenset((source.object_id, target.object_id)) in direct_parent_pairs:
                continue
            assert source.geometry is not None and target.geometry is not None
            distance = _edge_gap(source.geometry, target.geometry)
            if distance <= max_near_gap:
                candidates.append((distance, target.object_id))
        candidates.sort(key=lambda value: (value[0], value[1]))
        if not candidates:
            continue
        best_distance = candidates[0][0]
        tied = [
            candidate
            for candidate in candidates
            if math.isclose(candidate[0], best_distance, abs_tol=tie_tolerance, rel_tol=0.0)
        ]
        if len(tied) != 1:
            continue
        target_id = tied[0][1]
        scene = scene_by_object[source.object_id]
        records.append(
            _record(
                relation_type="possible-comment-for",
                portable_type="possible-comment-for",
                source=source.object_id,
                target=target_id,
                scene=scene,
                evidence=(
                    f"text/sticky object has one nearest non-text neighbour at edge gap "
                    f"{best_distance:.6f} canvas units"
                ),
                reason="Candidate comment relationship from proximity; human review is required.",
                confidence="low",
                distance=best_distance,
            )
        )

    return sorted(
        records,
        key=lambda record: (
            record["relation_type"],
            record["source"],
            record["target"],
            record["relation_id"],
        ),
    )
