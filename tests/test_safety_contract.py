from __future__ import annotations

import pytest

from printrbot_penplotter.gcode import polylines_to_gcode
from printrbot_penplotter.job_validator import JobValidationError, validate_hardware_job
from printrbot_penplotter.models import MachineConfig, PageConfig, PenConfig


POLYLINES = [[(10.0, 10.0), (20.0, 20.0), (30.0, 15.0)]]


def _generated(*, home: bool = True) -> str:
    return polylines_to_gcode(
        POLYLINES,
        PageConfig(),
        PenConfig(
            home_before_plot=home,
            z_up_mm=5.0,
            z_down_mm=0.0,
            travel_feed_mm_min=1000.0,
            draw_feed_mm_min=600.0,
            corner_feed_mm_min=300.0,
            z_feed_mm_min=120.0,
        ),
        MachineConfig(),
        title="Safety contract fixture",
    )


def _commands(gcode: str) -> list[str]:
    return [
        line.split(";", 1)[0].strip()
        for line in gcode.splitlines()
        if line.split(";", 1)[0].strip()
    ]


def test_generated_hardware_job_has_canonical_start_and_end_envelope() -> None:
    commands = _commands(_generated(home=True))
    assert commands[:6] == ["G21", "G90", "M400", "G28", "M400", "G0 Z5.000 F120.0"]
    assert commands[-5:] == [
        "M400",
        "G0 Z5.000 F120.0",
        "M400",
        "G28 X Y",
        "M400",
    ]
    validate_hardware_job(_generated(home=True))


def test_diagonal_xy_is_explicitly_valid() -> None:
    gcode = _generated(home=True)
    assert "G1 X20.000 Y20.000" in gcode
    validate_hardware_job(gcode)


def test_offline_job_without_homing_is_not_hardware_runnable() -> None:
    gcode = _generated(home=False)
    assert "G28" not in gcode
    with pytest.raises(JobValidationError, match="G28 Z"):
        validate_hardware_job(gcode)


def test_hardware_job_must_finish_pen_up_and_rehome_xy() -> None:
    unsafe = "\n".join(
        [
            "G21",
            "G90",
            "G28",
            "G0 Z5 F120",
            "G0 X10 Y10 F1000",
            "G1 X20 Y20 F600",
            "G0 Z5 F120",
            "M400",
            "",
        ]
    )
    with pytest.raises(JobValidationError, match="re-homing X/Y"):
        validate_hardware_job(unsafe)


def test_post_plot_z_rehome_is_rejected() -> None:
    unsafe = "\n".join(
        [
            "G21",
            "G90",
            "G28",
            "G0 Z5 F120",
            "G0 X10 Y10 F1000",
            "G1 X20 Y20 F600",
            "G0 Z5 F120",
            "G28",
            "",
        ]
    )
    with pytest.raises(JobValidationError, match="Z must remain safely raised"):
        validate_hardware_job(unsafe)


def test_simultaneous_xy_and_z_is_rejected_but_xy_diagonal_is_not() -> None:
    safe_diagonal = "\n".join(
        [
            "G21",
            "G90",
            "G28",
            "G0 Z5 F120",
            "G1 X20 Y20 F600",
            "G0 Z5 F120",
            "G28 X Y",
            "",
        ]
    )
    validate_hardware_job(safe_diagonal)

    unsafe_xyz = safe_diagonal.replace("G1 X20 Y20 F600", "G1 X20 Y20 Z5 F600")
    with pytest.raises(JobValidationError, match="simultaneous XY and Z"):
        validate_hardware_job(unsafe_xyz)


def test_out_of_bounds_and_excessive_feed_are_rejected() -> None:
    base = "\n".join(
        [
            "G21",
            "G90",
            "G28",
            "G0 Z5 F120",
            "G0 X10 Y10 F1000",
            "G1 X20 Y20 F600",
            "G0 Z5 F120",
            "G28 X Y",
            "",
        ]
    )
    with pytest.raises(JobValidationError, match="X coordinate"):
        validate_hardware_job(base.replace("X20 Y20", "X200 Y20"))
    with pytest.raises(JobValidationError, match="XY feed"):
        validate_hardware_job(base.replace("F600", "F8000"))
