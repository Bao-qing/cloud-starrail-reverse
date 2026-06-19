# Repository Guidelines

## Project Structure & Module Organization

This is a Python client for dispatching and connecting to a cloud game session.

- `ui.py` is the Tkinter desktop client entry point. It wires user settings, callbacks, keyboard/mouse translation, and preview state into `core.CloudGame`.
- `demo.py` contains runnable async examples for account checks, screenshots, input automation, and redeem-code flows.
- `client_profile.json` stores overridable device, browser, protocol, and session profiles.
- `credentials.json.example` is the local secret template. Real `credentials.json` is ignored by Git.

### Core Package Structure

`core/` is split by protocol boundary:

- `__init__.py` exports the public API: `CloudGame`, callback/state dataclasses, queue constants, config, and logging helpers.
- `cloud_game.py` is the high-level facade. `CloudGame` coordinates the two-stage flow: synchronous dispatch via `Dispatcher`, then async WebSocket/WebRTC connection via `GameSession`. It also caches latest UI-readable state, forwards callbacks, exposes `send_input()`, `capture_video_frame()`, `get_wallet_info()`, and `get_queue_estimate()`.
- `dispatcher.py` handles HTTP account sync, wallet/queue queries, polling, and final instance dispatch. `DispatchConfig` carries dispatch-only settings, cookies, queue type, node, and client profile data.
- `session.py` owns the live connection lifecycle. It creates WebSocket connections, negotiates WebRTC, handles SDK game-data callbacks, consumes video tracks, sends control actions, formats WebSocket payloads, and runs `GameSession`.
- `protocol.py` contains constants and binary protocol helpers: frame types, command IDs, protobuf-like encoding, packet/frame builders/parsers, SDK start parameter parsing, input packet encoding, and AES helpers.
- `models.py` contains shared dataclasses: `CloudGameConfig`, `GameTicket`, and `InputAction`. Prefer adding cross-layer configuration or value objects here instead of duplicating dict shapes.
- `config.py` defines default runtime profiles and comment-tolerant JSON loading. `CoreConfig` merges `client_profile.json`-style overrides and exposes them by attribute.
- `log.py` centralizes logger naming, console logging setup, noisy dependency suppression, and backward-compatible log callbacks.

There is no checked-in `tests/` directory yet. Add tests under `tests/` when introducing behavior that can be validated offline.

## Build, Test, and Development Commands

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the GUI client:

```bash
python ui.py
```

Run demo flows:

```bash
python demo.py
```

`demo.py` selects the active example in its `if __name__ == "__main__"` block. Edit that block intentionally before running automation that sends input or captures screenshots.

## Coding Style & Naming Conventions

Use Python 3.11+ style with type annotations where practical. Follow the existing 4-space indentation, dataclass-based models, and `snake_case` for functions, variables, and modules. Use `PascalCase` for classes and uppercase names for fixed protocol constants.

Keep user-facing logs concise. Prefer `core.log.get_logger()` and `configure_logging()` over ad hoc logging setup.

## Testing Guidelines

No test framework is configured yet. For new tests, prefer `pytest` and place files as `tests/test_<module>.py`. Focus offline tests on pure behavior such as config parsing, model conversion, input action serialization, and protocol helpers. Avoid tests that require live credentials or external cloud sessions unless they are clearly marked as integration tests.

Suggested command once tests exist:

```bash
pytest
```

## Commit & Pull Request Guidelines

This repository has no commit history yet, so use a simple convention going forward: short imperative commit subjects such as `Add queue estimate parsing` or `Fix Tkinter key mapping`.

Pull requests should include a brief description, test results or reason tests were not run, and notes for any credential, network, or GUI behavior changes. Include screenshots only when UI layout changes are visible.

## Security & Configuration Tips

Never commit `credentials.json`, cookies, tokens, screenshots containing account data, or generated session artifacts. Keep example config files sanitized and document any new required keys in `credentials.json.example`.
