"""Compare an observed schema against the approved baseline and classify every difference.

Default severity rules (override any of them via `SeverityPolicy(overrides={...})`):

    rule                           severity   meaning
    field_removed.required         critical   a field present in every baseline instance is gone
    field_removed.optional         warning    a field that was only sometimes present is gone
    field_removed.now_optional     warning    a required field is now missing from some array items
    field_added                    info       a new field appeared
    type_changed.incompatible      critical   old and new types have nothing in common
    type_changed.partial           warning    the field sometimes has a new type (types overlap)
    nested_structure_changed       warning    an object/array field now sometimes has another shape
    array_item_type_changed        warning    the element type of an array changed
    nullability_changed.nullable   warning    a previously non-null field is now null
    nullability_changed.resolved   info       a field only ever seen as null now has a concrete type
    response_structure_changed     critical   the top-level JSON shape changed (e.g. object -> array)

Conservative choices: an empty array tells us nothing about item types, so it is never reported as
a change; a field only seen as `null` has an unknown type, so a later concrete value is `info`;
narrowing (e.g. "number|string" -> "number") is not considered breaking.
"""

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from app.models.enums import Severity
from app.monitoring.schema_inference import SchemaNode, type_names


class ChangeKind(StrEnum):
    FIELD_REMOVED = "field_removed"
    FIELD_ADDED = "field_added"
    TYPE_CHANGED = "type_changed"
    NESTED_STRUCTURE_CHANGED = "nested_structure_changed"
    ARRAY_ITEM_TYPE_CHANGED = "array_item_type_changed"
    NULLABILITY_CHANGED = "nullability_changed"
    RESPONSE_STRUCTURE_CHANGED = "response_structure_changed"


DEFAULT_SEVERITY_RULES: dict[str, Severity] = {
    "field_removed.required": Severity.CRITICAL,
    "field_removed.optional": Severity.WARNING,
    "field_removed.now_optional": Severity.WARNING,
    "field_added": Severity.INFO,
    "type_changed.incompatible": Severity.CRITICAL,
    "type_changed.partial": Severity.WARNING,
    "nested_structure_changed": Severity.WARNING,
    "array_item_type_changed": Severity.WARNING,
    "nullability_changed.nullable": Severity.WARNING,
    "nullability_changed.resolved": Severity.INFO,
    "response_structure_changed": Severity.CRITICAL,
}


class SeverityPolicy:
    def __init__(self, overrides: dict[str, Severity] | None = None):
        self.rules = {**DEFAULT_SEVERITY_RULES, **(overrides or {})}

    def severity(self, rule: str) -> Severity:
        return self.rules[rule]


@dataclass(frozen=True)
class SchemaChange:
    path: str
    kind: ChangeKind
    rule: str
    severity: Severity
    old: str | None
    new: str | None
    description: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"], data["severity"] = self.kind.value, self.severity.value
        return data


@dataclass
class SchemaDiff:
    changes: list[SchemaChange] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.changes)

    @property
    def max_severity(self) -> Severity | None:
        return max((c.severity for c in self.changes), key=lambda s: s.rank, default=None)

    def counts(self) -> dict[str, int]:
        result = {s.value: 0 for s in Severity}
        for change in self.changes:
            result[change.severity.value] += 1
        return result


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTAINERS = {"object", "array"}


def child_path(parent: str, key: str) -> str:
    return f"{parent}.{key}" if _IDENTIFIER.match(key) else f'{parent}["{key}"]'


def describe(node: SchemaNode | None) -> str:
    """Human-readable type, e.g. 'number', 'string | null', 'array<object>'."""
    if node is None:
        return "unknown"
    if node["type"] == "array":
        base = f"array<{describe(node['items']) if node['items'] else 'unknown'}>"
    elif node["type"] == "mixed":
        base = " | ".join(node["types"])
    else:
        base = node["type"]
    if node["nullable"] and node["type"] != "null":
        base += " | null"
    return base


class SchemaComparisonEngine:
    def __init__(self, policy: SeverityPolicy | None = None):
        self.policy = policy or SeverityPolicy()

    def compare(self, baseline: SchemaNode, observed: SchemaNode) -> SchemaDiff:
        diff = SchemaDiff()
        self._compare(baseline, observed, "$", diff, in_items=False)
        return diff

    def _add(
        self,
        diff: SchemaDiff,
        path: str,
        kind: ChangeKind,
        rule: str,
        old: str | None,
        new: str | None,
        description: str,
    ) -> None:
        severity = self.policy.severity(rule)
        diff.changes.append(SchemaChange(path, kind, rule, severity, old, new, description))

    def _compare(self, old: SchemaNode, new: SchemaNode, path: str, diff: SchemaDiff, in_items: bool) -> None:
        old_types, new_types = set(type_names(old)), set(type_names(new))

        if not old_types:  # baseline only ever saw null here: real type was unknown
            if new_types:
                self._add(
                    diff,
                    path,
                    ChangeKind.NULLABILITY_CHANGED,
                    "nullability_changed.resolved",
                    describe(old),
                    describe(new),
                    f"Previously only null; now observed as {describe(new)}",
                )
            return

        if new["nullable"] and not old["nullable"]:
            self._add(
                diff,
                path,
                ChangeKind.NULLABILITY_CHANGED,
                "nullability_changed.nullable",
                describe(old),
                describe(new),
                "Field was never null in the baseline but is now null",
            )
        if not new_types:  # only null observed now; nullability already reported above
            return

        if old_types != new_types:
            self._type_change(old, new, old_types, new_types, path, diff, in_items)
            return

        kind = next(iter(old_types)) if len(old_types) == 1 else None
        if kind == "object":
            self._compare_objects(old, new, path, diff)
        elif kind == "array" and old["items"] is not None and new["items"] is not None:
            self._compare(old["items"], new["items"], f"{path}[*]", diff, in_items=True)

    def _type_change(
        self,
        old: SchemaNode,
        new: SchemaNode,
        old_types: set[str],
        new_types: set[str],
        path: str,
        diff: SchemaDiff,
        in_items: bool,
    ) -> None:
        if new_types <= old_types:
            return  # narrowing: every value still has a type consumers already handle
        was, now = describe(old), describe(new)
        if path == "$":
            self._add(
                diff,
                path,
                ChangeKind.RESPONSE_STRUCTURE_CHANGED,
                "response_structure_changed",
                was,
                now,
                f"Top-level response changed from {was} to {now}",
            )
        elif in_items:
            self._add(
                diff,
                path,
                ChangeKind.ARRAY_ITEM_TYPE_CHANGED,
                "array_item_type_changed",
                was,
                now,
                f"Array items changed from {was} to {now}",
            )
        elif not old_types & new_types:
            self._add(
                diff,
                path,
                ChangeKind.TYPE_CHANGED,
                "type_changed.incompatible",
                was,
                now,
                f"Type changed from {was} to {now}",
            )
        elif old_types & _CONTAINERS:
            self._add(
                diff,
                path,
                ChangeKind.NESTED_STRUCTURE_CHANGED,
                "nested_structure_changed",
                was,
                now,
                f"Structure is now sometimes {now} (was {was})",
            )
        else:
            self._add(
                diff,
                path,
                ChangeKind.TYPE_CHANGED,
                "type_changed.partial",
                was,
                now,
                f"Field now sometimes has type {now} (was {was})",
            )

    def _compare_objects(self, old: SchemaNode, new: SchemaNode, path: str, diff: SchemaDiff) -> None:
        old_props, new_props = old["properties"], new["properties"]
        old_required, new_required = set(old["required"]), set(new["required"])
        for key in sorted(old_props.keys() | new_props.keys()):
            sub = child_path(path, key)
            if key not in new_props:
                required = key in old_required
                self._add(
                    diff,
                    sub,
                    ChangeKind.FIELD_REMOVED,
                    "field_removed.required" if required else "field_removed.optional",
                    describe(old_props[key]),
                    None,
                    "Previously observed field is missing"
                    + ("" if required else " (it was not always present)"),
                )
            elif key not in old_props:
                self._add(
                    diff,
                    sub,
                    ChangeKind.FIELD_ADDED,
                    "field_added",
                    None,
                    describe(new_props[key]),
                    "New field appeared",
                )
            else:
                if key in old_required and key not in new_required:
                    self._add(
                        diff,
                        sub,
                        ChangeKind.FIELD_REMOVED,
                        "field_removed.now_optional",
                        describe(old_props[key]),
                        describe(new_props[key]),
                        "Field is now missing from some array items",
                    )
                self._compare(old_props[key], new_props[key], sub, diff, in_items=False)
