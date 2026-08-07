# Release 0.4 — ESP32 Wi-Fi Transport

Release 0.4 moves reviewed G-code between the software application and Marlin over a small ESP32-C3 network bridge. The ESP32 remains a transport and job-control layer; it does not replace the Printrboard motion planner or duplicate the Python geometry engine.

## Release goal

A user can connect to the ESP32, upload final G-code, validate it, start one hardware job, see live acknowledgement-based progress, pause or resume between commands, cancel with a pen-up attempt, and issue a separate emergency stop.

## Implemented in the first Release 0.4 increment

### Firmware foundation

- [x] Add a reproducible PlatformIO project for `esp32-c3-devkitc-02`.
- [x] Pin PlatformIO Espressif 32 platform `7.0.1`.
- [x] Map Marlin UART to ESP32 GPIO6 RX and GPIO7 TX at 115200 baud.
- [x] Keep font rendering, tracing, layout, preview, and G-code generation outside the ESP32.
- [x] Add a setup access point and captive-portal redirects.
- [x] Add optional station-mode credentials stored in Preferences.
- [x] Add `printrbot.local` mDNS.
- [x] Add onboard RGB status indication.

### Upload and validation

- [x] Stream multipart G-code uploads to LittleFS.
- [x] Limit jobs to 512 KiB and 100,000 executable commands.
- [x] Validate the complete stored job before enabling start.
- [x] Strip comments and empty lines before transmission.
- [x] Reject heater, extrusion, tool-change, filament, embedded emergency-stop, and `E`-axis commands.
- [x] Reject uploads while a hardware job is active.
- [x] Add native tests for the shared safety filter.

### Marlin transport

- [x] Send one command at a time.
- [x] Wait for Marlin `ok` before sending the next command.
- [x] Track timeout, error, active command, and recent UART lines.
- [x] Query `M115` on bridge startup.
- [x] Add a fixed non-moving query endpoint for `M114`, `M115`, `M119`, and `M503`.
- [x] Keep the Printrboard as the real-time motion controller.

### Job state and controls

- [x] Add idle, ready, running, paused, cancelling, cancelled, completed, failed, and emergency states.
- [x] Enforce one active hardware job at a time.
- [x] Pause only between acknowledged commands.
- [x] Resume a paused file from its current LittleFS position.
- [x] Add acknowledgement-based progress.
- [x] Add orderly cancellation after the active command completes.
- [x] Attempt `M400 → pen up → M400` during ordinary cancellation.
- [x] Add a separate immediate `M112` endpoint.
- [x] Expose all controls through a responsive browser dashboard.
- [x] Document the HTTP API.

## Remaining before Release 0.4 is complete

### Hardware and end-to-end validation

- [ ] Install the UART level translator and verify both rail voltages before data connection.
- [ ] Verify Printrboard TX1 reaches ESP32 GPIO6 without exceeding the 3.3 V domain.
- [ ] Verify ESP32 GPIO7 reaches Printrboard RX1 reliably at 115200 baud.
- [ ] Run `M115`, `M119`, `M114`, and `M503` through the browser.
- [ ] Upload a no-motion query-only test file and verify all acknowledgements.
- [ ] Upload the Release 0.2 air-plot calibration file.
- [ ] Pause and resume the air plot between strokes.
- [ ] Orderly-cancel the air plot and confirm the configured Z-up move.
- [ ] Test physical emergency stop with the pen safely clear and document the required reset behavior.
- [ ] Measure Wi-Fi range and reconnect behavior in the intended installation.
- [ ] Verify final 5 V power stability during Wi-Fi transmit and stepper motion.

### Security and provisioning

- [ ] Replace the shared development access-point password before final installation.
- [ ] Add authenticated API sessions or a per-device API token.
- [ ] Add CSRF protection for browser control actions.
- [ ] Add first-run credential rotation.
- [ ] Add a physical-button recovery path for lost credentials.
- [ ] Add secure credential clearing without reflashing.
- [ ] Decide whether station mode should be disabled by default in final builds.

### Reliability and recovery

- [ ] Persist last completed command and job identity across ESP32 reset.
- [ ] Add an explicit controller-reset/reconnect workflow after `M112`.
- [ ] Add periodic Marlin heartbeat when idle.
- [ ] Detect Printrboard startup banners and reset events.
- [ ] Distinguish UART electrical failure from Marlin command rejection.
- [ ] Add controlled retry rules for queries; never blindly retry movement commands.
- [ ] Add brownout and watchdog reset reporting.
- [ ] Add filesystem integrity and free-space reporting.
- [ ] Add upload checksum and job metadata sidecar.
- [ ] Add resumability policy after power loss; default must remain operator-confirmed, not automatic.

### API and desktop integration

- [ ] Add a Python ESP32 transport client implementing the same job-sender boundary as USB serial.
- [ ] Add bridge discovery through mDNS and direct IP configuration.
- [ ] Upload generated G-code from the desktop browser UI.
- [ ] Display ESP32 job progress inside the Python web application.
- [ ] Add a transport selector: download, USB serial, or ESP32.
- [ ] Preserve the exact preview/job metadata beside the uploaded G-code.
- [ ] Add explicit air-plot and physical-plot labels to uploaded jobs.

### Firmware delivery

- [ ] Produce downloadable firmware artifacts from CI.
- [ ] Add version, Git commit, build time, and configuration hash to `/api/status`.
- [ ] Add signed OTA updates or document a USB-only update policy.
- [ ] Add release binaries and SHA-256 values.
- [ ] Add a factory image and recovery procedure.

### Tests and quality

- [ ] Add native tests for job-state transitions.
- [ ] Add simulated Marlin tests for `ok`, `busy`, `error`, timeout, and reset banners.
- [ ] Add multipart upload boundary and oversized-file tests.
- [ ] Add LittleFS failure tests.
- [ ] Add API contract tests against a hardware-in-loop or emulator target.
- [ ] Add static analysis and formatting for firmware code.
- [ ] Track firmware flash and RAM use in CI.

## Required validation order

1. Build firmware in CI.
2. Flash ESP32 over USB with Printrboard UART disconnected.
3. Verify access point, dashboard, file upload, and unsafe-command rejection.
4. Measure level-shifter rails with all power off during wiring changes.
5. Connect common ground and translated UART.
6. Run non-moving Marlin queries.
7. Upload a query-only file.
8. Upload the Release 0.2 calibration air plot.
9. Test pause and resume.
10. Test orderly cancel and confirm pen-up behavior.
11. Test emergency stop under controlled conditions.
12. Only after Release 0.2 physical acceptance, test a pen-down drawing.

## Release acceptance criteria

Release 0.4 is complete only when:

- the firmware builds reproducibly for the exact ESP32-C3 board;
- the translated UART exchanges repeated Marlin commands without corruption;
- unsafe G-code is rejected before the job reaches `ready`;
- each movement command is gated by the previous Marlin acknowledgement;
- pause, resume, orderly cancel, and emergency stop are physically validated;
- a dropped UART or Wi-Fi connection cannot silently start or continue a new job;
- only one hardware job can run at once;
- the desktop application can upload and monitor the exact G-code represented by its preview;
- API authentication or a documented trusted-network restriction is in place;
- firmware binaries, hashes, and recovery instructions are published;
- Release 0.2 machine calibration is still enforced before pen-down use.
