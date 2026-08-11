# ESP32 Bridge HTTP API

**API version:** local bridge 0.4.1

The bridge serves JSON endpoints from both its setup access point and, when configured, its station-mode address. The setup address is normally `http://192.168.4.1` and mDNS is `http://printrbot.local` where supported.

This API controls real hardware. It is intentionally narrow: the bridge accepts final G-code and does not render text, trace images, or alter machine-space geometry.

## Authentication status

Every dashboard and API request uses HTTP Basic authentication. On first boot,
the bridge generates a unique password, stores it in ESP32 Preferences, and
prints the username and password to the USB serial monitor at 115200 baud.

HTTP Basic authentication is not encryption. Use it with the bridge's WPA2
access point or a trusted local network; do not port-forward the bridge or put
it behind a public tunnel. Firmware updates are USB-only; OTA is not
implemented.

For the Python client, provide the printed credentials through environment
variables:

```bash
export PRINTRBOT_BRIDGE_USER=admin
export PRINTRBOT_BRIDGE_PASSWORD='paste-the-serial-password-here'
printrbot-bridge --url http://192.168.4.1 status
```

The command-line client also accepts `--username` and `--password` options.

## `GET /api/status`

Returns bridge, Wi-Fi, UART, and active-job state.

Example:

```json
{
  "firmware": "Printrbot Wi-Fi Bridge 0.4.1-local",
  "uptime_ms": 132922,
  "wifi_mode": "setup access point",
  "ip": "192.168.4.1",
  "ap_ip": "192.168.4.1",
  "printer_connected": true,
  "printer_pending": false,
  "last_printer_line": "ok",
  "job": {
    "state": "running",
    "total": 418,
    "completed": 121,
    "bytes": 16284,
    "progress": 28.95,
    "active": "G1 X52.120 Y46.330 F1200",
    "error": ""
  },
  "log": [
    "118220 TX G1 X52.120 Y46.330 F1200",
    "118244 RX ok"
  ]
}
```

Job states:

```text
idle
ready
running
paused
cancelling
cancelled
completed
failed
emergency
```

## `POST /api/job`

Uploads a multipart form file named `job`.

```bash
curl -u admin:'paste-the-serial-password-here' \
  -F 'job=@out/plot.gcode' http://192.168.4.1/api/job
```

The bridge streams the upload into LittleFS and then validates every executable line before returning success.

Current limits:

```text
maximum stored job: 512 KiB
maximum executable commands: 100,000
maximum command line: 256 characters
```

The upload is rejected while a job is running, paused, or cancelling.

Safety scanning rejects:

- heater commands;
- extrusion modes and extrusion-axis moves;
- tool changes;
- filament-change/load/unload commands;
- embedded `M112`;
- commands exceeding the configured line or job limits.

## `POST /api/job/start`

Starts the validated stored job from its first command.

```bash
curl -u admin:'paste-the-serial-password-here' \
  -X POST http://192.168.4.1/api/job/start
```

The job runner sends exactly one command, waits for a Marlin `ok`, records progress, and only then sends the next command.

## `POST /api/job/pause`

Requests a pause between acknowledged commands.

```bash
curl -X POST http://192.168.4.1/api/job/pause
```

This does not interrupt a command already accepted by Marlin. The state becomes `paused` after the current command returns `ok`.

## `POST /api/job/resume`

Resumes a paused job.

```bash
curl -X POST http://192.168.4.1/api/job/resume
```

## `POST /api/job/cancel`

Requests an orderly cancellation.

```bash
curl -X POST http://192.168.4.1/api/job/cancel
```

After the active command is acknowledged, the bridge attempts:

```text
M400
G0 Z<configured-safe-up> F300
M400
```

It then enters `cancelled`. This is not an emergency stop and relies on a calibrated safe Z-up value.

## `POST /api/emergency`

Immediately sends `M112` to Marlin and enters `emergency`.

```bash
curl -X POST http://192.168.4.1/api/emergency
```

The Printrboard may require a reset before further commands are accepted. This endpoint is deliberately separate from ordinary cancellation.

## `POST /api/printer/query`

Accepts form-encoded `command` and only permits the fixed non-moving query set:

```text
M114
M115
M119
M503
```

Example:

```bash
curl -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'command=M119' \
  http://192.168.4.1/api/printer/query
```

Queries are rejected while a job or another UART command is active. Read the response lines from `/api/status`.

## `POST /api/wifi`

Stores optional station-mode credentials in ESP32 Preferences and restarts the bridge.

```bash
curl -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'ssid=NetworkName' \
  --data-urlencode 'password=NetworkPassword' \
  http://192.168.4.1/api/wifi
```

An empty SSID clears station-mode configuration after restart. The setup access point remains enabled.

The endpoint rejects changes while a hardware job is active.

## Error format

```json
{
  "ok": false,
  "error": "Human-readable reason"
}
```

Typical HTTP status codes:

```text
200 request accepted
400 malformed or unsafe input
409 current job or UART state conflicts with the request
```

## Client integration rule

A desktop or mobile client should always:

1. generate and preview final paths outside the ESP32;
2. load the G-code as an editable draft through the browser or upload it directly;
3. review placement and save any edits;
4. validate and store the final job, then wait for `ready`;
5. start explicitly;
6. poll `/api/status`;
7. distinguish orderly cancellation from emergency stop;
8. treat `failed` and `emergency` as requiring operator inspection and, after `M112`, a Printrboard reset.
