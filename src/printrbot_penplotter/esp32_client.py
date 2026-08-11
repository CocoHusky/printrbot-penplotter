"""HTTP client for the Release 0.4 ESP32-C3 plotter bridge."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .job_validator import JobValidationError, validate_hardware_job

Transport = Callable[[Request, float], tuple[int, bytes]]


class BridgeError(RuntimeError):
    """Raised when the bridge is unavailable or rejects a request."""


class Esp32BridgeClient:
    """Small standard-library client for the embedded HTTP API."""

    def __init__(
        self,
        base_url: str = "http://192.168.4.1",
        *,
        timeout_s: float = 15.0,
        transport: Transport | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport
        self._authorization = None
        if username is not None and password is not None:
            credentials = f"{username}:{password}".encode("utf-8")
            self._authorization = "Basic " + base64.b64encode(credentials).decode("ascii")

    def _send(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = dict(headers or {})
        if self._authorization is not None and not any(
            key.lower() == "authorization" for key in request_headers
        ):
            request_headers["Authorization"] = self._authorization
        request = Request(
            self.base_url + path,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            if self._transport is not None:
                status, response_body = self._transport(request, self.timeout_s)
            else:
                with urlopen(request, timeout=self.timeout_s) as response:
                    status = response.status
                    response_body = response.read()
        except HTTPError as exc:
            response_body = exc.read()
            message = self._decode_error(response_body, f"HTTP {exc.code}")
            raise BridgeError(message) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BridgeError(f"ESP32 bridge request failed: {exc}") from exc

        if not 200 <= status < 300:
            raise BridgeError(self._decode_error(response_body, f"HTTP {status}"))

        try:
            result = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeError("ESP32 bridge returned invalid JSON.") from exc
        if not isinstance(result, dict):
            raise BridgeError("ESP32 bridge returned a non-object JSON response.")
        if result.get("ok") is False:
            raise BridgeError(str(result.get("error", "Bridge rejected the request.")))
        return result

    @staticmethod
    def _decode_error(body: bytes, fallback: str) -> str:
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                return str(payload.get("error") or payload.get("message") or fallback)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return fallback

    def status(self) -> dict[str, Any]:
        return self._send("GET", "/api/status")

    def upload(self, gcode_path: str | Path) -> dict[str, Any]:
        path = Path(gcode_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        if not data:
            raise ValueError("G-code file is empty.")
        if len(data) > 512 * 1024:
            raise ValueError("G-code file exceeds the bridge's 512 KiB limit.")
        try:
            gcode = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("G-code file must be UTF-8 text.") from exc

        # Fail locally before network upload. The ESP32 independently repeats
        # guarded validation so bypassing this client does not bypass safety.
        validate_hardware_job(gcode)

        boundary = "----PrintrbotBoundary" + secrets.token_hex(12)
        content_type = mimetypes.guess_type(path.name)[0] or "text/plain"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="job"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        return self._send(
            "POST",
            "/api/job",
            body=prefix + data + suffix,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def action(self, action: str) -> dict[str, Any]:
        if action not in {"start", "pause", "resume", "cancel"}:
            raise ValueError(f"Unsupported bridge action: {action}")
        return self._send("POST", f"/api/job/{action}")

    def emergency_stop(self) -> dict[str, Any]:
        return self._send("POST", "/api/emergency")

    def query(self, command: str) -> dict[str, Any]:
        body = urlencode({"command": command}).encode("ascii")
        return self._send(
            "POST",
            "/api/printer/query",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="printrbot-bridge")
    parser.add_argument("--url", default="http://192.168.4.1")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--username",
        default=os.environ.get("PRINTRBOT_BRIDGE_USER", "admin"),
        help="HTTP Basic auth username (default: PRINTRBOT_BRIDGE_USER or admin)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("PRINTRBOT_BRIDGE_PASSWORD"),
        help="HTTP Basic auth password (default: PRINTRBOT_BRIDGE_PASSWORD)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")
    upload = subparsers.add_parser("upload")
    upload.add_argument("gcode")
    for action in ("start", "pause", "resume", "cancel"):
        subparsers.add_parser(action)
    query = subparsers.add_parser("query")
    query.add_argument("gcode_command", choices=("M114", "M115", "M119", "M503"))
    emergency = subparsers.add_parser("emergency")
    emergency.add_argument(
        "--confirm",
        required=True,
        help="Must be exactly STOP because this sends Marlin M112 immediately.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = Esp32BridgeClient(
        args.url,
        timeout_s=args.timeout,
        username=args.username if args.password is not None else None,
        password=args.password,
    )

    try:
        if args.command == "status":
            result = client.status()
        elif args.command == "upload":
            result = client.upload(args.gcode)
        elif args.command in {"start", "pause", "resume", "cancel"}:
            result = client.action(args.command)
        elif args.command == "query":
            result = client.query(args.gcode_command)
        elif args.command == "emergency":
            if args.confirm != "STOP":
                raise BridgeError("Refusing emergency stop: --confirm must be exactly STOP.")
            result = client.emergency_stop()
        else:  # pragma: no cover
            raise BridgeError("Unknown command.")
    except (BridgeError, JobValidationError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
