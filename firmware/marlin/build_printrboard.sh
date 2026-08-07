#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$HOME/Desktop/printrboard-marlin-2.1.2.8}"
ENV_NAME="at90usb1286_dfu"
OUT_NAME="printrbot-revf4-plotter-wifi-directions-fixed-marlin-2.1.2.8.hex"

cd "$ROOT"

if [[ ! -f Marlin/Configuration.h ]]; then
  echo "Marlin/Configuration.h not found under $ROOT" >&2
  exit 2
fi

if ! command -v pio >/dev/null 2>&1; then
  echo "PlatformIO 'pio' command not found." >&2
  exit 2
fi

echo "=== CONFIG CHECK ==="
grep -nE 'INVERT_[XYZ]_DIR|[XYZ]_HOME_DIR|SERIAL_PORT|BAUDRATE|EXTRUDERS' Marlin/Configuration.h

echo
echo "=== BUILD $ENV_NAME ==="
pio run -e "$ENV_NAME"

SRC=".pio/build/$ENV_NAME/firmware.hex"
if [[ ! -f "$SRC" ]]; then
  echo "Expected HEX not found: $SRC" >&2
  exit 3
fi

mkdir -p build-artifacts
cp "$SRC" "build-artifacts/$OUT_NAME"

echo
echo "=== ARTIFACT ==="
ls -lh "build-artifacts/$OUT_NAME"

echo
echo "=== SHA256 ==="
shasum -a 256 "build-artifacts/$OUT_NAME"
