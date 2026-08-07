#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MARLIN_ROOT="${1:-$HOME/Desktop/printrboard-marlin-2.1.2.8}"
ENV_NAME="at90usb1286_dfu"
OUT_NAME="printrbot-revf4-plotter-wifi-directions-fixed-marlin-2.1.2.8.hex"
HEX="$MARLIN_ROOT/build-artifacts/$OUT_NAME"

if [[ ! -f "$MARLIN_ROOT/Marlin/Configuration.h" ]]; then
  echo "Marlin tree not found: $MARLIN_ROOT" >&2
  exit 2
fi

if ! command -v pio >/dev/null 2>&1; then
  echo "PlatformIO 'pio' command not found." >&2
  exit 2
fi

if ! command -v dfu-programmer >/dev/null 2>&1; then
  echo "dfu-programmer not found. On macOS: brew install dfu-programmer" >&2
  exit 2
fi

echo "=== APPLY PROJECT CONFIG ==="
python3 "$SCRIPT_DIR/apply_project_config.py" "$MARLIN_ROOT"

echo
echo "=== BUILD ==="
"$SCRIPT_DIR/build_printrboard.sh" "$MARLIN_ROOT"

echo
echo "=== READY TO FLASH ==="
echo "HEX: $HEX"
shasum -a 256 "$HEX"

echo
cat <<'EOF'
Put the Printrboard Rev F4 into DFU mode now:
  1. Keep Printrboard powered and USB connected to the Mac.
  2. Install the BOOT jumper.
  3. Press and release RESET.
  4. Remove the BOOT jumper.
  5. Keep physical power removal reachable.
EOF

read -r -p "Press ENTER when the Printrboard is in DFU mode..."

echo
echo "=== FLASH ==="
"$SCRIPT_DIR/flash_printrboard.sh" "$MARLIN_ROOT" "$HEX" FLASH

echo
echo "=== COMPLETE ==="
echo "After Marlin restarts, use the ESP32 bridge and test:"
echo "  M115"
echo "  M119"
echo "Then home one axis at a time:"
echo "  G28 X    # must move toward X-min"
echo "  G28 Y    # must move toward Y-max"
echo "  G28 Z    # must move toward Z-min"
echo "Do not run full G28 until all three are individually correct."
