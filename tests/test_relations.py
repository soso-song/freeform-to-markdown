from __future__ import annotations

from freeform_to_markdown.models import BoardObject, Geometry
from freeform_to_markdown.relations import infer_relations


def _object(
    object_id: str,
    *,
    item_type: int = 5,
    geometry: Geometry | None = None,
    parent_id: str | None = None,
    text: str = "",
) -> BoardObject:
    return BoardObject(
        object_id=object_id,
        parent_id=parent_id,
        item_type=item_type,
        sub_item_type=None,
        common_data=b"",
        specific_data=b"",
        text=text,
        geometry=geometry,
    )


def test_group_membership_survives_missing_coordinates() -> None:
    group = _object("group", item_type=2)
    child = _object("child", item_type=3, parent_id="group", text="note")

    relations = infer_relations([child, group], {"group": "s1", "child": "s1"})

    assert relations == [
        {
            "relation_id": relations[0]["relation_id"],
            "source": "group",
            "target": "child",
            "relation_type": "group-membership",
            "type": "contains",
            "scene": "s1",
            "evidence": "Freeform parent identifier on the child object",
            "reason": "The source data explicitly records this parent-child membership.",
            "confidence": "observed",
            "distance": None,
        }
    ]


def test_overlap_is_observed_without_claiming_semantics() -> None:
    left = _object("a", geometry=Geometry(0, 0, 100, 100))
    right = _object("b", geometry=Geometry(50, 25, 100, 100))

    relations = infer_relations([right, left], {"a": "s1", "b": "s1"})

    overlap = next(record for record in relations if record["type"] == "overlaps")
    assert overlap["source"] == "a"
    assert overlap["target"] == "b"
    assert overlap["confidence"] == "observed"
    assert overlap["distance"] == 0.0
    assert "semantic association are not inferred" in overlap["reason"]
    assert not any(record["type"] == "near" for record in relations)


def test_near_requires_reciprocal_nearest_neighbours_and_same_scene() -> None:
    objects = [
        _object("a", geometry=Geometry(0, 0, 10, 10)),
        _object("b", geometry=Geometry(20, 0, 10, 10)),
        _object("c", geometry=Geometry(70, 0, 10, 10)),
        _object("d", geometry=Geometry(22, 0, 10, 10)),
    ]
    scenes = {"a": "one", "b": "one", "c": "one", "d": "other"}

    relations = infer_relations(objects, scenes, max_near_gap=100)
    near = [record for record in relations if record["type"] == "near"]

    assert [(record["source"], record["target"]) for record in near] == [("a", "b")]
    assert near[0]["confidence"] == "medium"
    assert "Proximity only" in near[0]["reason"]


def test_unique_nearest_text_may_be_comment_but_tie_is_not_guessed() -> None:
    unique = [
        _object("note", item_type=12, geometry=Geometry(0, 0, 10, 10), text="Check this"),
        _object("image", geometry=Geometry(20, 0, 10, 10)),
        _object("far", geometry=Geometry(100, 0, 10, 10)),
    ]
    relations = infer_relations(unique, {item.object_id: "s1" for item in unique})
    comment = next(record for record in relations if record["type"] == "possible-comment-for")
    assert (comment["source"], comment["target"]) == ("note", "image")
    assert comment["confidence"] == "low"
    assert "human review" in comment["reason"]

    tied = [
        _object("note", item_type=3, geometry=Geometry(50, 0, 10, 10), text="Ambiguous"),
        _object("left", geometry=Geometry(30, 0, 10, 10)),
        _object("right", geometry=Geometry(70, 0, 10, 10)),
    ]
    tied_relations = infer_relations(tied, {item.object_id: "s1" for item in tied})
    assert not any(record["type"] == "possible-comment-for" for record in tied_relations)
    assert {
        (record["source"], record["target"])
        for record in tied_relations
        if record["type"] == "near"
    } == {("left", "note"), ("note", "right")}


def test_output_and_relation_ids_are_deterministic() -> None:
    objects = [
        _object("b", geometry=Geometry(20, 0, 10, 10)),
        _object("a", geometry=Geometry(0, 0, 10, 10)),
    ]
    scenes = {"a": "s1", "b": "s1"}

    forward = infer_relations(objects, scenes)
    reverse = infer_relations(list(reversed(objects)), scenes)

    assert forward == reverse
    assert len({record["relation_id"] for record in forward}) == len(forward)


def test_direct_parent_pair_does_not_gain_spatial_or_comment_edges() -> None:
    container = _object("container", geometry=Geometry(0, 0, 100, 100))
    note = _object(
        "note",
        item_type=3,
        geometry=Geometry(10, 10, 20, 20),
        parent_id="container",
        text="Child note",
    )

    relations = infer_relations([container, note], {"container": "s1", "note": "s1"})

    assert [record["type"] for record in relations] == ["contains"]
