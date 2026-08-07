"""Non-moving Marlin preflight checks for Release 0.2."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .sender import MarlinSender


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    command: str
    passed: bool
    responses: list[str] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class PreflightReport:
    passed: bool
    checks: list[PreflightCheck]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checks": [asdict(check) for check in self.checks],
        }


def _contains(responses: list[str], needle: str) -> bool:
    lowered = needle.lower()
    return any(lowered in response.lower() for response in responses)


def run_preflight(sender: MarlinSender) -> PreflightReport:
    """Query Marlin without issuing homing or motion commands.

    This verifies communication, firmware identity, endstop reporting, current
    position reporting, and stored settings access. It does not prove that
    axes move in the correct direction or that Z pen heights are calibrated.
    """

    definitions = [
        ("firmware", "M115", "firmware_name", "Marlin firmware identity"),
        ("endstops", "M119", "reporting endstop status", "endstop report"),
        ("position", "M114", "x:", "current position"),
        ("settings", "M503", "m92", "stored steps-per-unit settings"),
    ]
    checks: list[PreflightCheck] = []

    for name, command, expected, note in definitions:
        try:
            responses = sender.send_command(command)
            passed = _contains(responses, expected)
            checks.append(
                PreflightCheck(
                    name=name,
                    command=command,
                    passed=passed,
                    responses=responses,
                    note=note if passed else f"Expected response containing '{expected}'.",
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    name=name,
                    command=command,
                    passed=False,
                    responses=[],
                    note=str(exc),
                )
            )
            break

    return PreflightReport(
        passed=len(checks) == len(definitions) and all(check.passed for check in checks),
        checks=checks,
    )
