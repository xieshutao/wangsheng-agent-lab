from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Action
from .reason_codes import ReasonCode


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    target_required: bool
    permission: str
    parameters_schema: dict[str, Any]
    timeout_seconds: float
    cancellable: bool
    produces_memory: bool = False
    model_parameters_schema: dict[str, Any] | None = None
    schema_version: str = "wangsheng.tool.v3"

    def function_schema(self) -> dict[str, Any]:
        exposed_schema = self.model_parameters_schema or self.parameters_schema
        properties = dict(exposed_schema.get("properties", {}))
        required = list(exposed_schema.get("required", []))
        if self.target_required:
            properties = {"target_id": {"type": "string", "minLength": 1}, **properties}
            required = ["target_id", *required]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
            "x-wangsheng": {
                "timeout_seconds": self.timeout_seconds,
                "cancellable": self.cancellable,
                "permission": self.permission,
                "produces_memory": self.produces_memory,
                "schema_version": self.schema_version,
            },
        }


@dataclass(frozen=True, slots=True)
class ValidationFailure:
    code: str
    message: str


class ToolRegistry:
    def __init__(self, specs: tuple[ToolSpec, ...] | None = None) -> None:
        selected = specs or default_tool_specs()
        self._specs = {spec.name: spec for spec in selected}

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def function_schemas(
        self,
        allowed: set[str] | frozenset[str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        names = (
            self.names()
            if allowed is None
            else tuple(name for name in self.names() if name in allowed)
        )
        return tuple(self._specs[name].function_schema() for name in names)

    def validate_action_arguments(self, action: Action) -> ValidationFailure | None:
        spec = self.get(action.name)
        if spec is None:
            return ValidationFailure(
                ReasonCode.TOOL_NOT_FOUND.value,
                f"Unknown tool '{action.name}'.",
            )
        if spec.target_required and not action.target:
            return ValidationFailure(ReasonCode.INVALID_ARGUMENT.value, "target_id is required.")
        if not spec.target_required and action.target is not None:
            return ValidationFailure(
                ReasonCode.INVALID_ARGUMENT.value,
                "This tool does not accept target_id.",
            )
        problem = validate_json_object(action.parameters, spec.parameters_schema)
        if problem:
            return ValidationFailure(ReasonCode.INVALID_ARGUMENT.value, problem)
        if action.name == "report":
            has_ids = isinstance(action.parameters.get("fact_ids"), list)
            has_facts = isinstance(action.parameters.get("facts"), list)
            if has_ids == has_facts:
                return ValidationFailure(
                    ReasonCode.INVALID_ARGUMENT.value,
                    "report requires exactly one of fact_ids or legacy facts.",
                )
            selected = action.parameters.get("fact_ids") if has_ids else action.parameters.get("facts")
            if not selected:
                return ValidationFailure(
                    ReasonCode.INVALID_ARGUMENT.value,
                    "report requires at least one fact selection.",
                )
        return None


def validate_json_object(
    value: Any,
    schema: dict[str, Any],
    path: str = "parameters",
) -> str | None:
    if not isinstance(value, dict):
        return f"{path} must be an object."
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in value:
            return f"{path}.{key} is required."
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(value) - set(properties))
        if unknown:
            return f"{path} contains unknown fields: {unknown}."
    for key, item in value.items():
        item_schema = properties.get(key)
        if item_schema is None:
            continue
        problem = validate_value(item, item_schema, f"{path}.{key}")
        if problem:
            return problem
    return None


def validate_value(value: Any, schema: dict[str, Any], path: str) -> str | None:
    expected = schema.get("type")
    type_ok = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }.get(expected, True)
    if not type_ok:
        return f"{path} must be {expected}."
    if expected == "string":
        if len(value) < schema.get("minLength", 0):
            return f"{path} is too short."
        if "enum" in schema and value not in schema["enum"]:
            return f"{path} must be one of {schema['enum']}."
    if expected in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be >= {schema['minimum']}."
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be <= {schema['maximum']}."
    if expected == "object":
        return validate_json_object(value, schema, path)
    if expected == "array":
        if len(value) < schema.get("minItems", 0):
            return f"{path} must contain at least {schema['minItems']} item(s)."
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                problem = validate_value(item, item_schema, f"{path}[{index}]")
                if problem:
                    return problem
    return None


def _object_schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def default_tool_specs() -> tuple[ToolSpec, ...]:
    fact_schema = _object_schema(
        {
            "subject": {"type": "string", "minLength": 1},
            "predicate": {"type": "string", "minLength": 1},
            "value": {"type": "string", "minLength": 1},
            "certainty": {
                "type": "string",
                "enum": ["TRUE", "FALSE", "UNKNOWN", "CLAIMED", "CONFLICTED"],
            },
            "source": {"type": "string", "minLength": 1},
        },
        ("subject", "predicate", "value", "certainty", "source"),
    )
    ask_runtime_schema = _object_schema(
        {
            "barrier_id": {"type": "string", "minLength": 1},
            "topic": {"type": "string", "minLength": 1},
        },
        ("barrier_id", "topic"),
    )
    ask_model_schema = _object_schema(
        {
            "barrier_id": {"type": "string", "minLength": 1},
            "topic": {
                "type": "string",
                "enum": ["identity", "purpose", "request", "door_state"],
            },
        },
        ("barrier_id", "topic"),
    )
    report_runtime_schema = _object_schema(
        {
            "text": {"type": "string", "minLength": 1},
            "fact_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "facts": {"type": "array", "minItems": 1, "items": fact_schema},
        },
        ("text",),
    )
    report_model_schema = _object_schema(
        {
            "text": {"type": "string", "minLength": 1},
            "fact_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
        ("text", "fact_ids"),
    )
    return (
        ToolSpec(
            "move_to",
            "Move to a known object or the player. Use this before proximity-dependent "
            "actions when current_affordances reports TOO_FAR.",
            True,
            "navigate",
            _object_schema({"acceptance_radius": {"type": "number", "minimum": 0, "maximum": 500}}),
            20.0,
            True,
            False,
        ),
        ToolSpec(
            "observe",
            "Inspect a currently observable known target without changing it. An entity "
            "behind a closed opaque door is not directly observable.",
            True,
            "perceive",
            _object_schema({}),
            5.0,
            True,
            True,
        ),
        ToolSpec(
            "listen_at",
            "Listen at a known barrier without opening it. Requires the actor to already "
            "be near the target; use move_to first when TOO_FAR.",
            True,
            "perceive",
            _object_schema({"duration": {"type": "number", "minimum": 0, "maximum": 30}}),
            10.0,
            True,
            True,
        ),
        ToolSpec(
            "ask_through",
            "Ask one structured question through a closed barrier. Select exactly one "
            "topic enum: identity, purpose, request, or door_state. Repeating the same "
            "topic without new evidence is not progress.",
            True,
            "communicate",
            ask_runtime_schema,
            15.0,
            True,
            True,
            ask_model_schema,
        ),
        ToolSpec(
            "open",
            "Open a nearby door only when permitted, unlocked and not forbidden by "
            "the active task.",
            True,
            "manipulate",
            _object_schema({}),
            8.0,
            True,
            True,
        ),
        ToolSpec(
            "close",
            "Close a nearby door that is currently open.",
            True,
            "manipulate",
            _object_schema({}),
            8.0,
            True,
            True,
        ),
        ToolSpec(
            "report",
            "Report grounded information to a nearby target. Select only fact_ids from "
            "world.reportable_facts; do not create predicates, values, certainty labels, "
            "or sources. Use completion_progress to select the facts that finish the task.",
            True,
            "communicate",
            report_runtime_schema,
            15.0,
            True,
            True,
            report_model_schema,
        ),
        ToolSpec(
            "wait",
            "Wait for a bounded duration only when completion_progress is not ready and "
            "no action can currently create new evidence.",
            False,
            "wait",
            _object_schema(
                {"seconds": {"type": "number", "minimum": 0, "maximum": 60}},
                ("seconds",),
            ),
            60.0,
            True,
            False,
        ),
    )
