# Contributing

Thanks for helping improve this project.

## Before you start

- Open an issue for larger changes before starting work.
- Keep changes focused and easy to review.
- Do not commit secrets, credentials, private URLs, or local machine files.

## Pull requests

Use the pull request template and include:

- What changed
- Why it changed
- How it was tested

## Local checks

Before opening a pull request:

- Install the development dependencies: `python -m pip install -e '.[dev]'`.
- Run `python -m pytest -q` and `python -m compileall -q src tests`.
- For ESP32 changes, run `pio test -d firmware/esp32 -e native` and
  `pio run -d firmware/esp32 -e esp32-c3-devkitc-02`.
- Update README or docs when behavior changes.

## Commit style

Use short, direct commit messages:

```text
Add setup instructions
Fix build command
Update wiring diagram
```
