"""Host-side validation for G-code that may be sent to real plotter hardware.

The ESP32 performs the same class of checks again when a job is uploaded. This
module gives desktop clients an earlier, human-readable failure instead of
letting an unsafe or incomplete job reach the bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

MACHINE_X_MIN_MM = 0.0
MACHINE_X_MAX_MM = 152.4
MACHINE_Y_MIN_MM = 0.0
MACHINE_Y_MAX_MM = 152.4
MACHINE_Z_MIN_MM = 0.0
MACHINE_Z_MAX_MM = 152.4
MAXIMUM_XY_FEED_MM_MIN = 7500.0
MAXIMUM_Z_FEED_MM_MIN = 300.0
SAFE_Z_UP_MM = 5.0
TOLERANCE_MM = 0.01

_ALLOWED_JOB_TOKENS = {"G0", "G00", "G1", "G01", "G21", "G28", "G90", "M400"}
_FORBIDDEN_TOKENS = {
    "M82", "M83", "M104", "M109", "M140", "M141", "M190", "M191",
    "M200", "M221", "M302", "M303", "M600", "M701", "M702", "M112",
}
_QUERY_TOKENS = {"M105", "M114", "M115", "M119", "M503"}
_TOKEN_RE = re.compile(r"^\s*([GMT]\d+)", re.IGNORECASE)


class JobValidationError(ValueError):
    """Raised when a stored hardware job violates guarded plotter rules."""


@dataclass
class _State:
    millimeters: bool = False
    absolute_positioning: bool = False
    homed_x: bool = False
    homed_y: bool = False
    homed_z: bool = False
    z_known: bool = False
    z_mm: float = 0.0
    saw_xy_motion: bool = False
    rehomed_x_after_motion: bool = False
    rehomed_y_after_motion: bool = False


def _strip_comments(line: str) -> str:
    line = line.split(";", 1)[0]
    out: list[str] = []
    in_parenthetical = False
    for char in line:
        if char == "(":
            in_parenthetical = True
            continue
        if char == ")":
            in_parenthetical = False
            continue
        if not in_parenthetical:
            out.append(char)
    return "".join(out).strip()


def _token(command: str) -> str:
    match = _TOKEN_RE.match(command)
    return match.group(1).upper() if match else ""


def _has_word(command: str, letter: str) -> bool:
    upper = command.upper()
    letter = letter.upper()
    for index, char in enumerate(upper):
        if char != letter:
            continue
        if index > 0 and upper[index - 1].isalpha():
            continue
        return True
    return False


def _parameter(command: str, letter: str) -> float:
    match = re.search(
        rf"{re.escape(letter)}\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))",
        command,
        re.IGNORECASE,
    )
    if not match:
        raise JobValidationError(f"{letter.upper()} parameter is missing a finite numeric value")
    value = float(match.group(1))
    if not math.isfinite(value):
        raise JobValidationError(f"{letter.upper()} parameter is missing a finite numeric value")
    return value


def _fail(line_number: int, message: str) -> None:
    raise JobValidationError(f"Line {line_number} rejected: {message}")


def validate_hardware_job(gcode: str) -> None:
    """Validate a complete guarded plotter job.

    Home-only diagnostic jobs remain valid. Any job that performs XY motion
    must establish X/Y/Z home in the same file, raise the pen before first XY,
    remain inside the configured machine envelope, finish pen-up, and re-home
    X/Y after the final XY movement. Diagonal X+Y movement is explicitly valid;
    only simultaneous XY+Z movement is rejected.
    """

    if not gcode.strip():
        raise JobValidationError("G-code file is empty.")

    state = _State()
    command_count = 0

    for line_number, raw_line in enumerate(gcode.splitlines(), start=1):
        command = _strip_comments(raw_line)
        if not command:
            continue
        command_count += 1
        if len(command) > 256:
            _fail(line_number, "command exceeds 256 characters")

        token = _token(command)
        if not token:
            _fail(line_number, "missing or unsupported G-code command")
        if token in _FORBIDDEN_TOKENS or token.startswith("T"):
            _fail(line_number, f"forbidden heater, extrusion, emergency, or tool command: {token}")
        if token in _QUERY_TOKENS:
            _fail(line_number, "status queries are not allowed inside a stored motion job")
        if token not in _ALLOWED_JOB_TOKENS:
            _fail(line_number, f"unsupported command in guarded plot job: {token}")

        if token == "G21":
            state.millimeters = True
            continue
        if token == "G90":
            state.absolute_positioning = True
            continue
        if token == "M400":
            continue

        if token == "G28":
            specifies_x = _has_word(command, "X")
            specifies_y = _has_word(command, "Y")
            specifies_z = _has_word(command, "Z")
            homes_all = not specifies_x and not specifies_y and not specifies_z

            if state.saw_xy_motion and (homes_all or specifies_z):
                _fail(
                    line_number,
                    "after XY plotting motion, end homing may home X/Y only; Z must remain safely raised",
                )
            if homes_all or specifies_x:
                state.homed_x = True
                if state.saw_xy_motion:
                    state.rehomed_x_after_motion = True
            if homes_all or specifies_y:
                state.homed_y = True
                if state.saw_xy_motion:
                    state.rehomed_y_after_motion = True
            if homes_all or specifies_z:
                state.homed_z = True
                state.z_known = True
                state.z_mm = MACHINE_Z_MIN_MM
            continue

        is_move = token in {"G0", "G00", "G1", "G01"}
        if not is_move:
            _fail(line_number, f"unsupported command in guarded plot job: {token}")

        if not state.millimeters:
            _fail(line_number, "G21 millimeter mode is required before coordinate motion")
        if not state.absolute_positioning:
            _fail(line_number, "G90 absolute positioning is required before coordinate motion")

        has_x = _has_word(command, "X")
        has_y = _has_word(command, "Y")
        has_z = _has_word(command, "Z")
        has_f = _has_word(command, "F")
        if not has_x and not has_y and not has_z:
            _fail(line_number, "motion command must contain X, Y, or Z")
        if has_z and (has_x or has_y):
            _fail(line_number, "simultaneous XY and Z motion is not allowed in guarded plot jobs")

        x = _parameter(command, "X") if has_x else None
        y = _parameter(command, "Y") if has_y else None
        z = _parameter(command, "Z") if has_z else None
        feed = _parameter(command, "F") if has_f else None
        if feed is not None and feed <= 0:
            _fail(line_number, "feed parameter F must be a finite positive value")

        if x is not None and not MACHINE_X_MIN_MM - TOLERANCE_MM <= x <= MACHINE_X_MAX_MM + TOLERANCE_MM:
            _fail(line_number, "X coordinate is outside configured machine limits")
        if y is not None and not MACHINE_Y_MIN_MM - TOLERANCE_MM <= y <= MACHINE_Y_MAX_MM + TOLERANCE_MM:
            _fail(line_number, "Y coordinate is outside configured machine limits")
        if z is not None and not MACHINE_Z_MIN_MM - TOLERANCE_MM <= z <= MACHINE_Z_MAX_MM + TOLERANCE_MM:
            _fail(line_number, "Z coordinate is outside configured machine limits")

        if has_x and not state.homed_x:
            _fail(line_number, "X motion requires G28 X or G28 earlier in the same job")
        if has_y and not state.homed_y:
            _fail(line_number, "Y motion requires G28 Y or G28 earlier in the same job")
        if has_z and not state.homed_z:
            _fail(line_number, "Z motion requires G28 Z or G28 earlier in the same job")
        if (has_x or has_y) and not state.homed_z:
            _fail(line_number, "XY motion requires Z homing earlier in the same job")

        if feed is not None:
            maximum_feed = MAXIMUM_Z_FEED_MM_MIN if has_z else MAXIMUM_XY_FEED_MM_MIN
            if feed > maximum_feed + TOLERANCE_MM:
                _fail(
                    line_number,
                    "Z feed exceeds configured machine maximum"
                    if has_z
                    else "XY feed exceeds configured machine maximum",
                )

        if (has_x or has_y) and not state.saw_xy_motion:
            if not state.z_known or state.z_mm < SAFE_Z_UP_MM - TOLERANCE_MM:
                _fail(
                    line_number,
                    "first XY motion requires the pen to be raised to the configured safe Z first",
                )

        if z is not None:
            state.z_known = True
            state.z_mm = z
        if has_x or has_y:
            state.rehomed_x_after_motion = False
            state.rehomed_y_after_motion = False
            state.saw_xy_motion = True

    if command_count == 0:
        raise JobValidationError("Job contains no executable commands.")

    if state.saw_xy_motion:
        if not state.homed_x or not state.homed_y or not state.homed_z:
            raise JobValidationError("Job rejected: plotting motion requires X, Y, and Z to be homed in the same job")
        if not state.z_known or state.z_mm < SAFE_Z_UP_MM - TOLERANCE_MM:
            raise JobValidationError("Job rejected: plotting job must finish with the pen at or above the configured safe Z")
        if not state.rehomed_x_after_motion or not state.rehomed_y_after_motion:
            raise JobValidationError("Job rejected: plotting job must finish by re-homing X/Y after the final XY motion")
