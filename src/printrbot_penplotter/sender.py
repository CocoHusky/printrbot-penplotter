"""Guarded Marlin serial transport with cancellation and progress support."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO


class MarlinError(RuntimeError):
    """Raised when Marlin rejects a command or stops responding."""


class PlotCancelled(MarlinError):
    """Raised after a requested cancellation has been handled."""


class CancellationToken:
    """Thread-safe cancellation signal checked between acknowledged commands."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


ProgressCallback = Callable[[int, int, str], None]


class MarlinSender:
    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout_s: float = 15.0,
        *,
        serial_factory: Callable[..., Any] | None = None,
        startup_delay_s: float = 1.5,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.serial_factory = serial_factory
        self.startup_delay_s = startup_delay_s
        self._serial: Any | None = None

    def __enter__(self) -> "MarlinSender":
        if self.serial_factory is None:
            try:
                import serial
            except ImportError as exc:  # pragma: no cover - dependency error path
                raise RuntimeError("Serial sending requires pyserial.") from exc
            factory = serial.Serial
        else:
            factory = self.serial_factory

        self._serial = factory(
            self.port,
            self.baudrate,
            timeout=0.25,
            write_timeout=2.0,
        )
        if self.startup_delay_s > 0:
            time.sleep(self.startup_delay_s)
        reset = getattr(self._serial, "reset_input_buffer", None)
        if callable(reset):
            reset()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def _require_open(self) -> Any:
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
            # Marlin may emit 'busy:' or informational lines before the final ok.

        raise MarlinError(f"Timed out waiting for Marlin after '{clean}'.")

    def safe_stop(self, z_up_mm: float | None = None, log: TextIO | None = None) -> None:
        """Attempt an orderly stop between acknowledged commands.

        This is not an emergency stop. It stops adding new drawing commands,
        waits for already accepted motion, and raises the pen when a calibrated
        Z-up value is supplied. Failures are swallowed so the original error or
        cancellation remains visible to the caller.
        """

        try:
            self.send_command("M400", log=log)
            if z_up_mm is not None:
                self.send_command(f"G0 Z{z_up_mm:.3f} F300", log=log)
                self.send_command("M400", log=log)
        except Exception:
            return

    def send_gcode(
        self,
        gcode: str,
        log: TextIO | None = None,
        *,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        safe_z_up_mm: float | None = None,
    ) -> int:
        commands = [
            line.split(";", 1)[0].strip()
            for line in gcode.splitlines()
            if line.split(";", 1)[0].strip()
        ]
        sent = 0
        total = len(commands)
        try:
            for command in commands:
                if cancellation is not None and cancellation.cancelled:
                    raise PlotCancelled("Plot cancellation requested.")
                self.send_command(command, log=log)
                sent += 1
                if progress is not None:
                    progress(sent, total, command)
        except Exception:
            # Serial write/read failures, timeouts, Marlin errors, and normal
            # cancellation all stop new commands and attempt a calibrated
            # pen-up sequence. KeyboardInterrupt remains handled by the CLI.
            self.safe_stop(safe_z_up_mm, log=log)
            raise
        return sent

    def send_file(
        self,
        path: str | Path,
        log: TextIO | None = None,
        **kwargs: object,
    ) -> int:
        return self.send_gcode(
            Path(path).read_text(encoding="utf-8"),
            log=log,
            **kwargs,
        )

    def emergency_stop(self) -> None:
        """Immediately issue Marlin M112; controller reset may be required."""

        serial_port = self._require_open()
        serial_port.write(b"M112\n")
        serial_port.flush()
