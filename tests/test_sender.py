from __future__ import annotations

from collections import deque

import pytest

from printrbot_penplotter.preflight import run_preflight
from printrbot_penplotter.sender import (
    CancellationToken,
    MarlinError,
    MarlinSender,
    PlotCancelled,
    UnsafeGcodeError,
)


def _safe_plot_gcode(*, failing_move: bool = False) -> str:
    draw = "G1 X21 Y21 F600" if failing_move else "G1 X20 Y20 F600"
    return "\n".join(
        [
            "G21",
            "G90",
            "M400",
            "G28",
            "M400",
            "G0 Z5 F120",
            "G0 X10 Y10 F1000",
            draw,
            "G0 Z5 F120",
            "M400",
            "G28 X Y",
            "M400",
            "",
        ]
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
            "G1 X21 Y21 F600": ["Error: deliberate failure"],
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


def test_direct_usb_rejects_xy_plot_without_guarded_homing_before_writing() -> None:
    unsafe = "G21\nG90\nG0 Z5 F120\nG0 X10 Y10 F600\n"
    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        with pytest.raises(UnsafeGcodeError, match="G28 Z"):
            sender.send_gcode(unsafe)
        assert sender._serial.commands == []


def test_direct_usb_accepts_complete_guarded_plot() -> None:
    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        count = sender.send_gcode(_safe_plot_gcode())
        commands = sender._serial.commands
    assert count == 12
    assert commands[:5] == ["G21", "G90", "M400", "G28", "M400"]
    assert "G1 X20 Y20 F600" in commands
    assert commands[-2:] == ["G28 X Y", "M400"]


def test_marlin_error_attempts_orderly_safe_stop() -> None:
    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        with pytest.raises(MarlinError):
            sender.send_gcode(_safe_plot_gcode(failing_move=True), safe_z_up_mm=5.0)
        commands = sender._serial.commands
    assert "G1 X21 Y21 F600" in commands
    assert commands[-3:] == ["M400", "G0 Z5.000 F300", "M400"]
    assert "G28 X Y" not in commands


def test_cancellation_stops_before_next_command_and_raises_pen() -> None:
    cancellation = CancellationToken()

    def progress(sent: int, total: int, command: str) -> None:
        if sent == 1:
            cancellation.cancel()

    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        with pytest.raises(PlotCancelled):
            sender.send_gcode(
                _safe_plot_gcode(),
                cancellation=cancellation,
                progress=progress,
                safe_z_up_mm=4.5,
            )
        commands = sender._serial.commands

    assert commands[0] == "G21"
    assert "G90" not in commands
    assert commands[-3:] == ["M400", "G0 Z4.500 F300", "M400"]


@pytest.mark.parametrize(
    "unsafe_command",
    [
        "M104 S200",
        "M109 S200",
        "M140 S60",
        "M190 S60",
        "M302 S0",
        "T0",
        "G1 X10 Y10 E2.5",
    ],
)
def test_heater_extrusion_and_tool_commands_are_blocked(unsafe_command: str) -> None:
    with MarlinSender("fake", serial_factory=factory, startup_delay_s=0) as sender:
        with pytest.raises(UnsafeGcodeError):
            sender.send_gcode(unsafe_command)
        assert sender._serial.commands == []
