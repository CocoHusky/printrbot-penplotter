from __future__ import annotations

from collections import deque

import pytest

from printrbot_penplotter.preflight import run_preflight
from printrbot_penplotter.sender import (
    CancellationToken,
    MarlinError,
    MarlinSender,
    PlotCancelled,
)


class FakeSerial:
    def __init__(self, *args, **kwargs) -> None:
        self.responses: deque[bytes] = deque()
        self.commands: list[str] = []
        self.closed = False

    def reset_input_buffer(self) -> None:
        self.responses.clear()

    def write(self, data: bytes) -> int:
        command = data.decode("ascii").strip()
        self.commands.append(command)
        scripted = {
            "M115": ["FIRMWARE_NAME:Marlin 2.1.2.8", "ok"],
            "M119": ["Reporting endstop status", "x_min: open", "y_max: open", "ok"],
            "M114": ["X:0.00 Y:0.00 Z:5.00", "ok"],
            "M503": ["M92 X80.00 Y80.00 Z2020.00", "ok"],
            "FAIL": ["Error: deliberate failure"],
        }
        for response in scripted.get(command, ["ok"]):
            self.responses.append((response + "\n").encode())
        return len(data)

    def flush(self) -> None:
        return None

    def readline(self) -> bytes:
        return self.responses.popleft() if self.responses else b""

    def close(self) -> None:
        self.closed = True


def factory(*args, **kwargs) -> FakeSerial:
    return FakeSerial(*args, **kwargs)


def test_preflight_queries_only_non_moving_commands() -> None:
    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        report = run_preflight(sender)
        commands = sender._serial.commands
    assert report.passed
    assert commands == ["M115", "M119", "M114", "M503"]
    assert all(not command.startswith(("G0", "G1", "G28")) for command in commands)


def test_marlin_error_attempts_orderly_safe_stop() -> None:
    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        with pytest.raises(MarlinError):
            sender.send_gcode("G21\nFAIL\nG1 X10 Y10", safe_z_up_mm=5.0)
        commands = sender._serial.commands
    assert commands[:2] == ["G21", "FAIL"]
    assert commands[-3:] == ["M400", "G0 Z5.000 F300", "M400"]
    assert "G1 X10 Y10" not in commands


def test_cancellation_stops_before_next_command_and_raises_pen() -> None:
    cancellation = CancellationToken()

    def progress(sent: int, total: int, command: str) -> None:
        if sent == 1:
            cancellation.cancel()

    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        with pytest.raises(PlotCancelled):
            sender.send_gcode(
                "G21\nG90\nG1 X10 Y10",
                cancellation=cancellation,
                progress=progress,
                safe_z_up_mm=4.5,
            )
        commands = sender._serial.commands

    assert commands[0] == "G21"
    assert "G90" not in commands
    assert commands[-3:] == ["M400", "G0 Z4.500 F300", "M400"]
