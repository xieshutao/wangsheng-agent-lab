from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

PROTOCOL_VERSION = "0.6"
SAVE_SCHEMA_VERSION = "wangsheng.headless_save.v0.6"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(value: bytes | str) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def gameplay_digest(state: dict[str, Any]) -> str:
    return f"sha256:{sha256_hex(canonical_bytes(state))}"


def content_fingerprint(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _unescape_pointer(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def json_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Return deterministic RFC6902-like add/remove/replace operations."""
    if type(before) is not type(after):
        return [{"op": "replace", "path": path, "value": deepcopy(after)}]
    if isinstance(before, dict):
        operations: list[dict[str, Any]] = []
        before_keys = set(before)
        after_keys = set(after)
        for key in sorted(before_keys - after_keys):
            operations.append({"op": "remove", "path": f"{path}/{_escape_pointer(str(key))}"})
        for key in sorted(after_keys - before_keys):
            operations.append(
                {
                    "op": "add",
                    "path": f"{path}/{_escape_pointer(str(key))}",
                    "value": deepcopy(after[key]),
                }
            )
        for key in sorted(before_keys & after_keys):
            operations.extend(
                json_diff(
                    before[key],
                    after[key],
                    f"{path}/{_escape_pointer(str(key))}",
                )
            )
        return operations
    if isinstance(before, list):
        if before == after:
            return []
        return [{"op": "replace", "path": path, "value": deepcopy(after)}]
    if before != after:
        return [{"op": "replace", "path": path, "value": deepcopy(after)}]
    return []


def apply_json_operations(state: Any, operations: list[dict[str, Any]]) -> Any:
    result = deepcopy(state)
    for operation in operations:
        op = operation["op"]
        path = operation["path"]
        if path == "":
            if op not in {"add", "replace"}:
                raise ValueError("Root operation must add or replace.")
            result = deepcopy(operation["value"])
            continue
        tokens = [_unescape_pointer(token) for token in path.lstrip("/").split("/")]
        parent = result
        for token in tokens[:-1]:
            parent = parent[int(token)] if isinstance(parent, list) else parent[token]
        last = tokens[-1]
        if isinstance(parent, list):
            index = int(last)
            if op == "remove":
                parent.pop(index)
            elif op == "add":
                parent.insert(index, deepcopy(operation["value"]))
            else:
                parent[index] = deepcopy(operation["value"])
        else:
            if op == "remove":
                parent.pop(last, None)
            else:
                parent[last] = deepcopy(operation["value"])
    return result
