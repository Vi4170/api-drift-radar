"""Infer a normalised, value-independent schema from a parsed JSON document.

Schema nodes are plain JSON-serialisable dicts so they can be stored in MongoDB as-is:

    {"type": "null" | "boolean" | "number" | "string", "nullable": bool}
    {"type": "object", "nullable": bool, "properties": {name: node}, "required": [names]}
    {"type": "array",  "nullable": bool, "items": node | None}   # None = only empty arrays seen
    {"type": "mixed",  "nullable": bool, "types": [type names]}  # incompatible types merged

Integers and floats both map to "number" so value changes like 1 -> 1.5 never look like drift.
`bool` is checked before numbers because `isinstance(True, int)` is True in Python.
`required` lists keys present in *every* observed instance (relevant for arrays of objects).
"""

import hashlib
import json
from typing import Any

SchemaNode = dict[str, Any]

MAX_DEPTH = 64


class SchemaInferenceEngine:
    def infer(self, value: Any) -> SchemaNode:
        return self._infer(value, depth=0)

    def _infer(self, value: Any, depth: int) -> SchemaNode:
        if depth > MAX_DEPTH:
            # ponytail: deeper levels are summarised as "mixed" rather than walked; raise if needed
            return {"type": "mixed", "nullable": False, "types": ["too_deep"]}
        if value is None:
            return {"type": "null", "nullable": True}
        if isinstance(value, bool):
            return {"type": "boolean", "nullable": False}
        if isinstance(value, int | float):
            return {"type": "number", "nullable": False}
        if isinstance(value, str):
            return {"type": "string", "nullable": False}
        if isinstance(value, dict):
            return {
                "type": "object",
                "nullable": False,
                "properties": {str(k): self._infer(v, depth + 1) for k, v in value.items()},
                "required": sorted(str(k) for k in value),
            }
        if isinstance(value, list):
            items: SchemaNode | None = None
            for element in value:
                node = self._infer(element, depth + 1)
                items = node if items is None else self.merge(items, node)
            return {"type": "array", "nullable": False, "items": items}
        raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")

    def merge(self, a: SchemaNode, b: SchemaNode) -> SchemaNode:
        """Combine two observations of the same location into one schema node."""
        nullable = a["nullable"] or b["nullable"]
        if a["type"] == "null":
            return {**b, "nullable": True}
        if b["type"] == "null":
            return {**a, "nullable": True}
        if a["type"] != b["type"] or a["type"] == "mixed":
            types = sorted(set(type_names(a)) | set(type_names(b)))
            return {"type": "mixed", "nullable": nullable, "types": types}
        if a["type"] == "object":
            props: dict[str, SchemaNode] = dict(a["properties"])
            for key, node in b["properties"].items():
                props[key] = self.merge(props[key], node) if key in props else node
            required = sorted(set(a["required"]) & set(b["required"]))
            return {"type": "object", "nullable": nullable, "properties": props, "required": required}
        if a["type"] == "array":
            if a["items"] is None or b["items"] is None:
                items = a["items"] or b["items"]
            else:
                items = self.merge(a["items"], b["items"])
            return {"type": "array", "nullable": nullable, "items": items}
        return {"type": a["type"], "nullable": nullable}


def type_names(node: SchemaNode) -> list[str]:
    """The concrete (non-null) types a node can hold."""
    if node["type"] == "mixed":
        return list(node["types"])
    if node["type"] == "null":
        return []
    return [node["type"]]


def canonical_json(schema: SchemaNode) -> str:
    return json.dumps(schema, sort_keys=True, separators=(",", ":"))


def schema_hash(schema: SchemaNode) -> str:
    return hashlib.sha256(canonical_json(schema).encode()).hexdigest()
