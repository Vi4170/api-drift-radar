from app.models.enums import Severity
from app.monitoring.schema_comparison import ChangeKind, SchemaComparisonEngine, SeverityPolicy
from app.monitoring.schema_inference import SchemaInferenceEngine

infer = SchemaInferenceEngine().infer
compare = SchemaComparisonEngine().compare


def changes(old: object, new: object) -> dict[str, tuple[ChangeKind, Severity]]:
    return {c.path: (c.kind, c.severity) for c in compare(infer(old), infer(new)).changes}


def test_readme_example_type_change_and_missing_field() -> None:
    diff = compare(
        infer({"user_id": 101, "name": "Alex", "active": True}), infer({"user_id": "101", "active": True})
    )
    found = {c.path: c for c in diff.changes}
    assert found["$.user_id"].kind == ChangeKind.TYPE_CHANGED
    assert (found["$.user_id"].old, found["$.user_id"].new) == ("number", "string")
    assert found["$.name"].kind == ChangeKind.FIELD_REMOVED
    assert diff.max_severity == Severity.CRITICAL
    assert diff.counts() == {"info": 0, "warning": 0, "critical": 2}


def test_no_change_for_value_variation() -> None:
    assert not compare(infer({"a": 1, "b": [1, 2]}), infer({"a": 2.75, "b": [9]})).has_drift


def test_new_field_is_informational() -> None:
    assert changes({"a": 1}, {"a": 1, "b": "x"}) == {"$.b": (ChangeKind.FIELD_ADDED, Severity.INFO)}


def test_nested_missing_and_added_fields_are_recursive() -> None:
    result = changes(
        {"user": {"profile": {"age": 1, "city": "x"}}}, {"user": {"profile": {"age": 1, "zip": "y"}}}
    )
    assert result == {
        "$.user.profile.city": (ChangeKind.FIELD_REMOVED, Severity.CRITICAL),
        "$.user.profile.zip": (ChangeKind.FIELD_ADDED, Severity.INFO),
    }


def test_boolean_to_number_is_a_type_change() -> None:
    assert changes({"flag": True}, {"flag": 1}) == {"$.flag": (ChangeKind.TYPE_CHANGED, Severity.CRITICAL)}


def test_object_to_scalar_is_incompatible() -> None:
    assert changes({"a": {"b": 1}}, {"a": "b"})["$.a"] == (ChangeKind.TYPE_CHANGED, Severity.CRITICAL)


def test_array_item_type_change() -> None:
    assert changes({"ids": [1, 2]}, {"ids": ["1"]}) == {
        "$.ids[*]": (ChangeKind.ARRAY_ITEM_TYPE_CHANGED, Severity.WARNING)
    }


def test_empty_arrays_are_never_drift() -> None:
    assert not compare(infer({"ids": [1]}), infer({"ids": []})).has_drift
    assert not compare(infer({"ids": []}), infer({"ids": ["x"]})).has_drift


def test_fields_inside_array_items() -> None:
    result = changes({"items": [{"id": 1, "sku": "a"}]}, {"items": [{"id": "1", "sku": "a"}]})
    assert result == {"$.items[*].id": (ChangeKind.TYPE_CHANGED, Severity.CRITICAL)}


def test_required_field_becoming_optional_in_array_items() -> None:
    result = changes({"items": [{"id": 1, "sku": "a"}]}, {"items": [{"id": 1, "sku": "a"}, {"id": 2}]})
    assert result == {"$.items[*].sku": (ChangeKind.FIELD_REMOVED, Severity.WARNING)}


def test_became_nullable_is_warning() -> None:
    assert changes({"a": "x"}, {"a": None}) == {"$.a": (ChangeKind.NULLABILITY_CHANGED, Severity.WARNING)}


def test_null_only_baseline_is_conservative() -> None:
    # The baseline never saw a real value, so the type was unknown: informational only.
    assert changes({"a": None}, {"a": "x"}) == {"$.a": (ChangeKind.NULLABILITY_CHANGED, Severity.INFO)}


def test_nullable_baseline_accepts_non_null() -> None:
    old = infer([{"a": None}, {"a": "x"}])
    assert not compare(old, infer([{"a": "y"}])).has_drift


def test_partial_type_overlap_is_warning() -> None:
    old, new = infer({"a": 1}), infer([{"a": 1}, {"a": "x"}])["items"]
    diff = compare(old, new)
    assert [(c.path, c.kind, c.severity) for c in diff.changes] == [
        ("$.a", ChangeKind.TYPE_CHANGED, Severity.WARNING)
    ]


def test_object_sometimes_another_shape_is_nested_structure_change() -> None:
    old = infer([{"meta": {"v": 1}}])["items"]
    new = infer([{"meta": {"v": 1}}, {"meta": "none"}])["items"]
    assert compare(old, new).changes[0].kind == ChangeKind.NESTED_STRUCTURE_CHANGED


def test_type_narrowing_is_not_drift() -> None:
    old = infer([{"a": 1}, {"a": "x"}])["items"]
    assert not compare(old, infer({"a": 2})).has_drift


def test_top_level_structure_change() -> None:
    assert changes({"a": 1}, [1]) == {"$": (ChangeKind.RESPONSE_STRUCTURE_CHANGED, Severity.CRITICAL)}


def test_unusual_keys_use_bracket_paths() -> None:
    assert '$["x-y"]' in changes({"x-y": 1}, {})


def test_severity_policy_is_extensible() -> None:
    lenient = SchemaComparisonEngine(SeverityPolicy({"field_added": Severity.WARNING}))
    assert lenient.compare(infer({}), infer({"b": 1})).max_severity == Severity.WARNING
