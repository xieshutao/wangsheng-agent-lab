import pytest

from wangsheng.models import Action
from wangsheng.tools import ToolRegistry


def test_registry_contains_exactly_eight_frozen_tools():
    assert ToolRegistry().names() == ("ask_through", "close", "listen_at", "move_to", "observe", "open", "report", "wait")


def test_every_tool_exports_function_schema_and_metadata():
    schemas = ToolRegistry().function_schemas()
    assert len(schemas) == 8
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["parameters"]["additionalProperties"] is False
        assert schema["x-wangsheng"]["timeout_seconds"] > 0
        assert isinstance(schema["x-wangsheng"]["cancellable"], bool)


@pytest.mark.parametrize("action", [
    Action("move_to", "door.front", {"acceptance_radius": "near"}),
    Action("observe", "door.front", {"extra": True}),
    Action("listen_at", None, {"duration": 1}),
    Action("ask_through", "visitor.xiaoman", {"barrier_id": "door.front"}),
    Action("report", "player", {"text": "hello", "facts": []}),
    Action("wait", parameters={"seconds": 61}),
])
def test_invalid_tool_arguments_are_rejected(action):
    failure = ToolRegistry().validate_action_arguments(action)
    assert failure is not None and failure.code == "INVALID_ARGUMENT"


def test_every_tool_declares_memory_and_schema_version_metadata():
    for schema in ToolRegistry().function_schemas():
        metadata = schema["x-wangsheng"]
        assert metadata["schema_version"] == "wangsheng.tool.v2"
        assert isinstance(metadata["produces_memory"], bool)
