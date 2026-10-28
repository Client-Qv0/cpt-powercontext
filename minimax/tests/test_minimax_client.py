"""HTTP-level tests for the MiniMax client using a local mock endpoint.

These do not call MiniMax; they verify the wire contract (path, auth header,
request body, response parsing, error handling) so the only untested step in a
real run is the remote model itself.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from specanchor.config import Settings
from specanchor.errors import MiniMaxError
from specanchor.minimax import MiniMaxClient

GOOD_RESPONSE = {
    "id": "mock-request-1",
    "model": "MiniMax-M3.1-Flash",
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-x\n+y"},
        }
    ],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    "base_resp": {"status_code": 0, "status_msg": ""},
}


class _Handler(BaseHTTPRequestHandler):
    payload: dict = GOOD_RESPONSE
    status = 200
    captured: dict = {}
    calls = 0

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).calls += 1
        type(self).captured = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": body,
        }
        data = json.dumps(self.payload).encode("utf-8")
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # silence the test server
        return


@pytest.fixture()
def mock_server():
    _Handler.payload = GOOD_RESPONSE
    _Handler.status = 200
    _Handler.calls = 0
    _Handler.captured = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _settings(base_url: str, *, api_key: str = "test-key") -> Settings:
    return dataclasses.replace(
        Settings.load(),
        minimax_api_key=api_key,
        minimax_base_url=base_url,
        minimax_model="MiniMax-M3.1-Flash",
        minimax_reasoning_effort="high",
    )


def test_posts_openai_compatible_request_and_parses_response(mock_server: str) -> None:
    client = MiniMaxClient(_settings(mock_server))
    result = client.chat(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ],
        max_completion_tokens=1234,
    )

    assert result.content.startswith("--- a/src/x.py")
    assert result.model == "MiniMax-M3.1-Flash"
    assert result.usage["total_tokens"] == 18
    assert result.request_id == "mock-request-1"
    assert result.finish_reason == "stop"

    captured = _Handler.captured
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "MiniMax-M3.1-Flash"
    assert captured["body"]["max_completion_tokens"] == 1234
    assert captured["body"]["reasoning_effort"] == "high"
    assert captured["body"]["messages"][1]["content"] == "user"


def test_missing_key_fails_before_http(mock_server: str) -> None:
    client = MiniMaxClient(_settings(mock_server, api_key=""))
    with pytest.raises(MiniMaxError):
        client.chat([{"role": "user", "content": "hi"}])
    assert _Handler.calls == 0


def test_base_resp_error_is_surfaced(mock_server: str) -> None:
    _Handler.payload = {
        **GOOD_RESPONSE,
        "base_resp": {"status_code": 1004, "status_msg": "invalid api key"},
    }
    client = MiniMaxClient(_settings(mock_server))
    with pytest.raises(MiniMaxError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])
    assert "1004" in str(excinfo.value)


def test_empty_content_is_rejected(mock_server: str) -> None:
    _Handler.payload = {
        **GOOD_RESPONSE,
        "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": ""}}],
    }
    client = MiniMaxClient(_settings(mock_server))
    with pytest.raises(MiniMaxError):
        client.chat([{"role": "user", "content": "hi"}])


def test_http_error_is_surfaced(mock_server: str) -> None:
    _Handler.status = 401
    _Handler.payload = {"error": "unauthorized"}
    client = MiniMaxClient(_settings(mock_server))
    with pytest.raises(MiniMaxError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])
    assert "401" in str(excinfo.value)
