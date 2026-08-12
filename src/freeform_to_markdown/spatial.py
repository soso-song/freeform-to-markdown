"""Deterministic, conservative scene clustering."""

from __future__ import annotations

from collections import defaultdict

from .models import BoardObject, Geometry, Scene


def _gap(left: Geometry, right: Geometry) -> float:
    horizontal = max(left.x - (right.x + right.width), right.x - (left.x + left.width), 0.0)
    vertical = max(left.y - (right.y + right.height), right.y - (left.y + left.height), 0.0)
    return float((horizontal * horizontal + vertical * vertical) ** 0.5)


def cluster_objects(objects: tuple[BoardObject, ...] | list[BoardObject]) -> list[Scene]:
    """Group nearby rectangles, then inherit a parent's scene for coordinate-less children."""

    ordered = sorted(objects, key=lambda item: item.object_id)
    by_id = {item.object_id: item for item in ordered}
    geometric = [item for item in ordered if item.geometry is not None]
    parent: dict[str, str] = {item.object_id: item.object_id for item in geometric}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for index, left in enumerate(geometric):
        assert left.geometry is not None
        for right in geometric[index + 1 :]:
            assert right.geometry is not None
            scale = max(
                120.0,
                min(
                    600.0,
                    (
                        left.geometry.width
                        + left.geometry.height
                        + right.geometry.width
                        + right.geometry.height
                    )
                    / 4,
                ),
            )
            if _gap(left.geometry, right.geometry) <= scale:
                union(left.object_id, right.object_id)

    groups: dict[str, list[str]] = defaultdict(list)
    for item in geometric:
        groups[find(item.object_id)].append(item.object_id)
    coordinate_less = [item for item in ordered if item.geometry is None]
    leftovers: list[str] = []
    for item in coordinate_less:
        ancestor = item.parent_id
        visited: set[str] = set()
        while ancestor and ancestor not in visited:
            visited.add(ancestor)
            if ancestor in parent:
                groups[find(ancestor)].append(item.object_id)
                break
            ancestor_item = by_id.get(ancestor)
            ancestor = ancestor_item.parent_id if ancestor_item is not None else None
        else:
            leftovers.append(item.object_id)
    if leftovers:
        groups["~fallback"] = leftovers

    def group_position(ids: list[str]) -> tuple[float, float, str]:
        bounds = [by_id[value].geometry for value in ids if by_id[value].geometry is not None]
        return (
            min((geometry.y for geometry in bounds if geometry is not None), default=float("inf")),
            min((geometry.x for geometry in bounds if geometry is not None), default=float("inf")),
            min(ids),
        )

    result: list[Scene] = []
    for number, ids in enumerate(sorted(groups.values(), key=group_position), start=1):
        result.append(
            Scene(
                scene_id=f"scene-{number:03d}",
                title=f"Scene {number}",
                object_ids=tuple(sorted(set(ids))),
            )
        )
    return result
