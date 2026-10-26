from app.monitoring.schema_inference import SchemaInferenceEngine, schema_hash

engine = SchemaInferenceEngine()


def test_scalars_and_numeric_normalisation() -> None:
    assert engine.infer(1)["type"] == "number"
    assert engine.infer(1.5)["type"] == "number"
    assert engine.infer("x")["type"] == "string"
    assert engine.infer(None) == {"type": "null", "nullable": True}


def test_booleans_are_not_numbers() -> None:
    # isinstance(True, int) is True in Python - the engine must not fall for it.
    assert engine.infer(True)["type"] == "boolean"
    assert engine.infer(False)["type"] == "boolean"


def test_nested_object() -> None:
    schema = engine.infer({"user": {"id": 1, "tags": ["a"]}})
    user = schema["properties"]["user"]
    assert user["type"] == "object"
    assert user["required"] == ["id", "tags"]
    assert user["properties"]["tags"]["items"]["type"] == "string"


def test_empty_array_has_unknown_items() -> None:
    assert engine.infer([])["items"] is None


def test_array_items_are_merged_with_optional_fields_and_nullability() -> None:
    schema = engine.infer([{"id": 1, "nick": "a"}, {"id": 2, "nick": None}, {"id": 3}])
    items = schema["items"]
    assert items["required"] == ["id"]  # "nick" missing from one element
    assert items["properties"]["nick"] == {"type": "string", "nullable": True}


def test_mixed_array_items() -> None:
    items = engine.infer([1, "two", None])["items"]
    assert items == {"type": "mixed", "nullable": True, "types": ["number", "string"]}


def test_int_and_float_items_merge_to_number() -> None:
    assert engine.infer([1, 2.5])["items"] == {"type": "number", "nullable": False}


def test_hash_ignores_values_but_not_structure() -> None:
    a = schema_hash(engine.infer({"id": 1, "name": "Alex"}))
    b = schema_hash(engine.infer({"name": "Sam", "id": 99.5}))
    c = schema_hash(engine.infer({"id": "1", "name": "Alex"}))
    assert a == b
    assert a != c
