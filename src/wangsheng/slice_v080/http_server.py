from __future__ import annotations

import argparse
import base64
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any

from .runtime import SliceProtocolError, XiaomanThreeDaySlice


class SliceRegistry:
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path
        self.sessions: dict[str, XiaomanThreeDaySlice] = {}
        self._lock = Lock()

    def create(self) -> XiaomanThreeDaySlice:
        with self._lock:
            runtime = XiaomanThreeDaySlice(self.fixture_path)
            self.sessions[runtime.session_id] = runtime
            return runtime

    def get(self, session_id: str) -> XiaomanThreeDaySlice:
        with self._lock:
            try:
                return self.sessions[session_id]
            except KeyError as exc:
                raise SliceProtocolError("SESSION_NOT_FOUND", session_id) from exc

    def load(self, payload: bytes) -> XiaomanThreeDaySlice:
        with self._lock:
            runtime = XiaomanThreeDaySlice.load_payload(self.fixture_path, payload)
            self.sessions[runtime.session_id] = runtime
            return runtime


class SliceRequestHandler(BaseHTTPRequestHandler):
    registry: SliceRegistry

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise SliceProtocolError("INVALID_BODY", "request body must be 1..1000000 bytes")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SliceProtocolError("INVALID_JSON", "body must be UTF-8 JSON") from exc
        if not isinstance(data, dict):
            raise SliceProtocolError("INVALID_JSON", "JSON body must be an object")
        return data

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path == "/health":
                self._send(HTTPStatus.OK, {"status": "ok", "schema_version": "0.8-slice"})
                return
            if self.path.startswith("/v0.8/session/"):
                session_id = self.path.rsplit("/", 1)[-1]
                runtime = self.registry.get(session_id)
                self._send(HTTPStatus.OK, {"status": "ok", "state": runtime.view()})
                return
            self._send(HTTPStatus.NOT_FOUND, {"status": "error", "reason_code": "NOT_FOUND"})
        except SliceProtocolError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"status": "error", "reason_code": exc.reason_code, "message": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/v0.8/session":
                runtime = self.registry.create()
                self._send(HTTPStatus.CREATED, {"status": "ok", "state": runtime.view()})
                return
            if self.path == "/v0.8/command":
                data = self._read_json()
                runtime = self.registry.get(str(data.get("session_id", "")))
                result = runtime.command(
                    action_id=str(data.get("action_id", "")),
                    command=str(data.get("command", "")),
                    parameters=data.get("parameters", {}),
                )
                self._send(HTTPStatus.OK, result.to_dict())
                return
            if self.path == "/v0.8/save":
                data = self._read_json()
                runtime = self.registry.get(str(data.get("session_id", "")))
                encoded = base64.b64encode(runtime.save_payload()).decode("ascii")
                self._send(HTTPStatus.OK, {"status": "ok", "session_id": runtime.session_id, "payload_b64": encoded})
                return
            if self.path == "/v0.8/load":
                data = self._read_json()
                try:
                    payload = base64.b64decode(str(data.get("payload_b64", "")), validate=True)
                except ValueError as exc:
                    raise SliceProtocolError("INVALID_SAVE_PAYLOAD", "payload_b64 is invalid") from exc
                runtime = self.registry.load(payload)
                self._send(HTTPStatus.OK, {"status": "ok", "state": runtime.view()})
                return
            self._send(HTTPStatus.NOT_FOUND, {"status": "error", "reason_code": "NOT_FOUND"})
        except SliceProtocolError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"status": "error", "reason_code": exc.reason_code, "message": str(exc)})
        except Exception as exc:  # defensive boundary: never expose traceback to UE
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"status": "error", "reason_code": "INTERNAL_ERROR", "message": type(exc).__name__})

    def log_message(self, format: str, *args: object) -> None:
        return


def run_server(*, fixture_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    registry = SliceRegistry(fixture_path)
    handler = type("ConfiguredSliceRequestHandler", (SliceRequestHandler,), {"registry": registry})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"WangSheng v0.8 slice server listening on http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("specs/v0.7/scenarios/xiaoman_three_day_kernel_fixture_v0.7.json"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run_server(fixture_path=args.fixture, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
