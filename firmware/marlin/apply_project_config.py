#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

SETTINGS = {
    "EXTRUDERS": "0",
    "SERIAL_PORT": "0",
    "BAUDRATE": "115200",
    "SERIAL_PORT_2": "1",
    "BAUDRATE_2": "115200",
    "INVERT_X_DIR": "true",
    "INVERT_Y_DIR": "true",
    "INVERT_Z_DIR": "true",
    "X_HOME_DIR": "-1",
    "Y_HOME_DIR": "1",
    "Z_HOME_DIR": "-1",
}


def replace_define(text: str, name: str, value: str) -> str:
    pattern = re.compile(rf"^(\s*#define\s+{re.escape(name)}\s+).*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one active #define {name}, found {len(matches)}")
    return pattern.sub(rf"\g<1>{value}", text, count=1)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: apply_project_config.py /path/to/Marlin-2.1.2.8", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).expanduser().resolve()
    config = root / "Marlin" / "Configuration.h"
    if not config.is_file():
        raise SystemExit(f"Configuration.h not found: {config}")

    text = config.read_text()
    for name, value in SETTINGS.items():
        text = replace_define(text, name, value)

    config.write_text(text)

    print(f"updated {config}")
    print("project-controlled values:")
    for name, value in SETTINGS.items():
        print(f"  {name} = {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
