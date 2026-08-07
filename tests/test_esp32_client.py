from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pytest

from printrbot_penplotter.esp32_client import BridgeError, Esp32BridgeClient


class FakeTransport:
    def __init__(self, status: int = 200, payload: dict[str, object] | None = None) -> None:
        self.status = status
        self.payload = payload or {"ok": True}
        self.requests: list[Request] = []

    def __call__(self, request: Request, timeout: float) -> tuple[int, bytes]:
        assert timeout > 0
        self.requests.append(request)
        return self.status, json.dumps(self.payload).encode()


def test_status_uses_expected_endpoint() -> None:
    transport = FakeTransport(payload={"firmware": "bridge", "job": {"state": "idle"}})
    client = Esp32BridgeClient("http://bridge.local/", transport=transport)
    result = client.status()
    assert result["firmware"] == "bridge"
    assert transport.requests[0].full_url == "http://bridge.local/api/status"
    assert transport.requests[0].method == "GET"


def test_upload_builds_multipart_job_request(tmp_path: Path) -> None:
    gcode = tmp_path / "plot.gcode"
    gcode.write_text("G21\nG90\nG0 Z5\n", encoding="utf-8")
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    client.upload(gcode)

    request = transport.requests[0]
    assert request.full_url.endswith("/api/job")
    assert request.method == "POST"
    assert request.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="job"' in request.data
    assert b"G21\nG90\nG0 Z5" in request.data


def test_oversized_upload_is_rejected_before_network(tmp_path: Path) -> None:
    gcode = tmp_path / "too-large.gcode"
    gcode.write_bytes(b"X" * (512 * 1024 + 1))
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    with pytest.raises(ValueError, match="512 KiB"):
        client.upload(gcode)
    assert transport.requests == []


def test_job_actions_use_fixed_paths() -> None:
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    for action in ("start", "pause", "resume", "cancel"):
        client.action(action)
    assert [request.full_url.rsplit("/", 1)[-1] for request in transport.requests] == [
        "start",
        "pause",
        "resume",
        "cancel",
    ]


def test_unknown_action_is_rejected_locally() -> None:
    client = Esp32BridgeClient(transport=FakeTransport())
    with pytest.raises(ValueError, match="Unsupported"):
        client.action("erase")


def test_bridge_error_uses_json_error_message() -> None:
    transport = FakeTransport(status=409, payload={"ok": False, "error": "job is active"})
    client = Esp32BridgeClient(transport=transport)
    with pytest.raises(BridgeError, match="job is active"):
        client.action("start")


def test_query_is_form_encoded() -> None:
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    client.query("M119")
    request = transport.requests[0]
    assert request.data == b"command=M119"
    assert request.headers["Content-type"] == "application/x-www-form-urlencoded"


def test_emergency_uses_separate_endpoint() -> None:
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    client.emergency_stop()
    assert transport.requests[0].full_url.endswith("/api/emergency")
