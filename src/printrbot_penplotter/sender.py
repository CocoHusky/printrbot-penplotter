"""Minimal, guarded Marlin serial sender."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TextIO


class MarlinError(RuntimeError):
    """Raised when Marlin rejects a command or stops responding."""


class MarlinSender:
    def __init__(self, port: str, baudrate: int = 115200, timeout_s: float = 15.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self._serial = None

    def __enter__(self) -> "MarlinSender":
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("Serial sending requires pyserial.") from exc

        self._serial = serial.Serial(
            self.port,
            self.baudrate,
            timeout=0.25,
            write_timeout=2.0,
        )
        time.sleep(1.5)
        self._serial.reset_input_buffer()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def _require_open(self):
        if self._serial is None:
            raise RuntimeError("Serial connection is not open.")
        return self._serial

    def send_command(self, command: str, log: TextIO | None = None) -> list[str]:
        serial_port = self._require_open()
        clean = command.split(";", 1)[0].strip()
        if not clean:
            return []

        if log:
            log.write(f"> {clean}\n")
        serial_port.write((clean + "\n").encode("ascii", errors="strict"))
        serial_port.flush()

        responses: list[str] = []
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            raw = serial_port.readline()
            if not raw:
                continue
            response = raw.decode("utf-8", errors="replace").strip()
            if not response:
                continue
            responses.append(response)
            if log:
                log.write(f"< {response}\n")
            lower = response.lower()
            if lower.startswith("ok"):
                return responses
            if lower.startswith("error") or lower.startswith("!!"):
                raise MarlinError(f"Marlin rejected '{clean}': {response}")

        raise MarlinError(f"Timed out waiting for Marlin after '{clean}'.")

    def send_gcode(self, gcode: str, log: TextIO | None = None) -> int:
        sent = 0
        for line in gcode.splitlines():
            if line.split(";", 1)[0].strip():
                self.send_command(line, log=log)
                sent += 1
        return sent

    def send_file(self, path: str | Path, log: TextIO | None = None) -> int:
        return self.send_gcode(Path(path).read_text(encoding="utf-8"), log=log)

    def emergency_stop(self) -> None:
        serial_port = self._require_open()
        serial_port.write(b"M112\n")
        serial_port.flush()
