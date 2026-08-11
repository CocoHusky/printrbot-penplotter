from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.request import Request

import pytest

from printrbot_penplotter.esp32_client import BridgeError, Esp32BridgeClient
from printrbot_penplotter.job_validator import JobValidationError


class FakeTransport:
    def __init__(self, status: int = 200, payload: dict[str, object] | None = None) -> None:
        self.status = status
        self.payload = payload or {"ok": True}
        self.requests: list[Request] = []

    def __call__(self, request: Request, timeout: float) -> tuple[int, bytes]:
        assert timeout > 0
        self.requests.append(request)
        return self.status, json.dumps(self.payload).encode()


def _safe_plot_gcode() -> str:
    return "\n".join(
        [
            "G21",
            "G90",
            "M400",
            "G28",
            "M400",
            "G0 Z5 F120",
            "G0 X10 Y10 F1000",
            "G1 X20 Y20 F600",
            "G0 Z5 F120",
            "M400",
            "G28 X Y",
            "M400",
            "",
        ]
    )


def test_status_uses_expected_endpoint() -> None:
    transport = FakeTransport(payload={"firmware": "bridge", "job": {"state": "idle"}})
    client = Esp32BridgeClient("http://bridge.local/", transport=transport)
    result = client.status()
    assert result["firmware"] == "bridge"
    assert transport.requests[0].full_url == "http://bridge.local/api/status"
    assert transport.requests[0].method == "GET"


def test_credentials_are_added_to_every_request() -> None:
    transport = FakeTransport()
    client = Esp32BridgeClient(
        "http://bridge.local",
        transport=transport,
        username="admin",
        password="secret",
    )
    client.status()
    client.query("M119")
    expected = "Basic " + base64.b64encode(b"admin:secret").decode("ascii")
    assert [request.headers["Authorization"] for request in transport.requests] == [
        expected,
        expected,
    ]


def test_upload_builds_multipart_job_request(tmp_path: Path) -> None:
    gcode = tmp_path / "plot.gcode"
    gcode.write_text(_safe_plot_gcode(), encoding="utf-8")
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    client.upload(gcode)

    request = transport.requests[0]
    assert request.full_url.endswith("/api/job")
    assert request.method == "POST"
    assert request.headers["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="job"' in request.data
    assert b"G28\n" in request.data
    assert b"G1 X20 Y20 F600" in request.data
    assert b"G28 X Y" in request.data


def test_upload_rejects_plot_without_homing_before_network(tmp_path: Path) -> None:
    gcode = tmp_path / "unsafe.gcode"
    gcode.write_text("G21\nG90\nG0 Z5 F120\nG0 X10 Y10 F600\n", encoding="utf-8")
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    with pytest.raises(JobValidationError, match="G28 Z"):
        client.upload(gcode)
    assert transport.requests == []


def test_upload_rejects_plot_without_end_rehome_before_network(tmp_path: Path) -> None:
    gcode = tmp_path / "unsafe-end.gcode"
    gcode.write_text(
        "G21\nG90\nG28\nG0 Z5 F120\nG0 X10 Y10 F600\nG0 Z5 F120\n",
        encoding="utf-8",
    )
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    with pytest.raises(JobValidationError, match="re-homing X/Y"):
        client.upload(gcode)
    assert transport.requests == []


def test_upload_allows_home_only_diagnostic(tmp_path: Path) -> None:
    gcode = tmp_path / "home-x.gcode"
    gcode.write_text("G28 X\nM400\n", encoding="utf-8")
    transport = FakeTransport()
    client = Esp32BridgeClient(transport=transport)
    client.upload(gcode)
    assert len(transport.requests) == 1


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
