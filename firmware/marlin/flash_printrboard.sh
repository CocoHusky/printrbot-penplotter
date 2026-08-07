#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$HOME/Desktop/printrboard-marlin-2.1.2.8}"
HEX="${2:-$ROOT/build-artifacts/printrbot-revf4-plotter-wifi-directions-fixed-marlin-2.1.2.8.hex}"
CONFIRM="${3:-}"
DEVICE="at90usb1286"

if [[ "$CONFIRM" != "FLASH" ]]; then
  cat <<EOF
Refusing to flash without explicit confirmation.

Usage:
  $0 /path/to/Marlin-2.1.2.8 /path/to/firmware.hex FLASH

Before running:
  1. Save/verify EEPROM settings with M503.
  2. Disconnect active jobs and remove the pen.
  3. Put the Printrboard Rev F4 into its AT90USB1286 DFU bootloader.
  4. Keep physical power removal reachable.
EOF
  exit 2
fi

if [[ ! -f "$HEX" ]]; then
  echo "HEX not found: $HEX" >&2
  exit 2
fi

if ! command -v dfu-programmer >/dev/null 2>&1; then
  echo "dfu-programmer not found. On macOS: brew install dfu-programmer" >&2
  exit 2
fi

echo "=== HEX ==="
ls -lh "$HEX"
shasum -a 256 "$HEX"

echo
echo "=== DFU FLASH ==="
echo "Device: $DEVICE"
dfu-programmer "$DEVICE" erase --force
dfu-programmer "$DEVICE" flash "$HEX"
dfu-programmer "$DEVICE" launch

echo
echo "Flash complete. Reconnect to Marlin and run M115, M119, M503, then home X/Y/Z individually."
