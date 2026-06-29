# Architecture Overview

This document describes the technical architecture of the Napoleon Home custom component for Home Assistant.

## Directory Structure

```text
custom_components/napoleon_home/
├── __init__.py                   # Integration setup and unload; hub/subentry coordinator loop
├── config_flow.py                # Thin re-export required by hassfest
├── const.py                      # Constants, GATT UUIDs, Ayla credentials, timing constants
├── data.py                       # Type aliases and NapoleonHomeGrillState dataclass
├── diagnostics.py                # Diagnostic data redaction
├── manifest.json                 # Integration metadata
├── translations/
│   └── en.json                   # English translations
│
├── api/                          # Ayla cloud API client (setup time only)
│   ├── __init__.py
│   └── client.py                 # NapoleonHomeApiClient: auth, device list, local key fetch
│
├── bluetooth/                    # Ayla Local Control v2 BLE protocol (Napoleon Home addition)
│   ├── __init__.py
│   ├── errors.py                 # NapoleonHomeNotProvisionedError, NapoleonHomeAlreadyBondedError
│   ├── protocol.py               # Framing, HMAC-SHA256, JSON encode/decode
│   └── session.py                # NapoleonHomeBLESession (connect, auth, read_dsn)
│
├── coordinator/                  # BLE DataUpdateCoordinator
│   ├── __init__.py
│   ├── base.py                   # NapoleonHomeDataUpdateCoordinator class
│   └── listeners.py              # NapoleonHomeBLEMixin: connection lifecycle, auth, GATT routing
│
├── config_flow_handler/          # Config and options flows
│   ├── __init__.py               # Re-exports all flow handler classes
│   ├── config_flow.py            # Main flow: BLE discovery, user setup, reauth
│   ├── options_flow.py           # Options flow: poll interval
│   ├── subentry_flow.py          # Subentry flow: add grill to existing account hub
│   └── schemas/
│       ├── __init__.py
│       └── options.py            # Options flow Voluptuous schema
│
├── entity/                       # Base entity
│   ├── __init__.py
│   └── base.py                   # NapoleonHomeEntity: unique_id, device_info, coordinator binding
│
├── entity_utils/                 # Shared entity helpers
│   ├── __init__.py
│   └── device_info.py            # DeviceInfo builder for sub-entry devices
│
├── binary_sensor/
│   ├── __init__.py
│   ├── status.py                 # BLE connection state sensor
│   └── battery_saver_mode.py     # Battery saver mode diagnostic binary sensor
│
├── button/
│   ├── __init__.py
│   └── power_off.py              # Power off grill button (TOFF property)
│
├── light/
│   ├── __init__.py
│   └── knob_lights.py            # Knob lights on/off (LCD_OFF)
│
├── number/
│   ├── __init__.py
│   ├── automatic_shutoff.py      # Automatic shutoff timeout (AUTO_T_OUT, 1–24 h)
│   └── target_temp.py            # Target temperature per probe (TRGT_TMP_*)
│
├── select/
│   ├── __init__.py
│   ├── brightness.py             # Display brightness (BRT_LVL: low/medium/high)
│   ├── tank_unit.py              # Tank unit (GS_UNT: kg/lbs)
│   └── temperature_unit.py       # Temperature unit (TUNIT: °C/°F)
│
├── sensor/
│   ├── __init__.py
│   ├── battery.py                # Battery sensor
│   ├── firmware.py               # Firmware version sensor
│   ├── probe_temp.py             # Probe temperature sensors (PRB_TMP_ONE–FOUR)
│   └── tank_weight.py            # Tank weight sensor (TNK_WT)
```

## Hub and Sub-entry Architecture

> **Napoleon Home:** This integration uses a hub/sub-entry model rather than the single-coordinator
> pattern described in the blueprint template.

- **One config entry per Napoleon account** (the hub). Hub data: `{CONF_REGION, CONF_USERNAME}`.
- **One `ConfigSubentry` per grill**. Sub-entry data: `{CONF_MAC, CONF_DSN, CONF_LOCAL_KEY}`.

```text
ConfigEntry (hub — one per account)
├── ConfigSubentry (grill 1)  ← CONF_MAC, CONF_DSN, CONF_LOCAL_KEY
├── ConfigSubentry (grill 2)
└── ...
```

`entry.runtime_data` is `dict[str, NapoleonHomeDataUpdateCoordinator]` keyed by `subentry_id`.

Type aliases (in `data.py`):

```python
NapoleonHomeCoordinators = dict[str, NapoleonHomeDataUpdateCoordinator]
NapoleonHomeConfigEntry = ConfigEntry[NapoleonHomeCoordinators]
```

## Core Components

### Data Update Coordinator

**Directory:** `coordinator/`

> **Napoleon Home:** The coordinator holds a persistent BLE connection rather than polling an HTTP
> API. The `NapoleonHomeBLEMixin` in `listeners.py` owns the full BLE lifecycle; `base.py` owns
> the periodic poll.

**Package structure:**

- `base.py` — `NapoleonHomeDataUpdateCoordinator`: inherits from `DataUpdateCoordinator[NapoleonHomeGrillState]` and `NapoleonHomeBLEMixin`. Manages the complete grill lifecycle: initial setup, periodic property polling, and clean shutdown.
- `listeners.py` — `NapoleonHomeBLEMixin`: owns the entire BLE connection lifecycle (advertisement callback, connect, authenticate, GATT routing).

**Core functionality:**

- `async_config_entry_first_refresh()` returns empty state (no error) when the grill is offline
- `_async_update_data()` polls all properties via `Gpr` if BLE is authenticated
- `async_shutdown()` tears down BLE state cleanly on unload

**BLE connection details (`listeners.py`):**

- Startup always waits for a genuine advertisement — `_async_setup` calls `_register_bt_callback` directly (no cached-device fast-path); `_skip_history_replay` suppresses the synchronous history-replay that `async_register_callback` fires on registration
- `_connect_and_run`: connects via `bleak-retry-connector`, settles MTU, subscribes to outbox, authenticates; `BleakNotFoundError`/`TimeoutError` from `establish_connection` are caught cleanly and do not increment the failure counter
- `_connecting: bool` guard prevents concurrent connection attempts from rapid advertisements
- `MAX_CONNECT_FAILURES = 5` cap: after 5 consecutive post-connect failures, `_circuit_open` stops auto-reconnect; reload the entry to resume; counter resets on successful auth **and** on clean disconnect from an authenticated session
- `_authenticate()`: sends `Oac t:1`, awaits HMAC challenge, computes `Oac t:2`, waits for auth OK event; writes `_bsmode_desired` immediately after auth to restore display power-save state
- `_on_notification()`: routes `oac`, `gpr`, `Odp`, `opr`, `ukn` opcodes; re-asserts `_bsmode_desired` if grill pushes `BSMODE=0` via `Odp`
- `_send_msg()`: fragments payload, serialises concurrent writes through an `asyncio.Lock`

**Key class:** `NapoleonHomeDataUpdateCoordinator` (exported from `coordinator/__init__.py`)

### BLE Protocol

**Directory:** `bluetooth/`

> **Napoleon Home addition:** This package implements Ayla Local Control v2 over GATT and has no
> equivalent in the blueprint template.

Implements Ayla Local Control v2 over GATT:

- Inbox characteristic (write): `01000001-fe28-435b-991a-f1b21bb9bcd0`
- Outbox characteristic (notify): `01000002-fe28-435b-991a-f1b21bb9bcd0`
- Fragmentation: each chunk prefixed with a 1-byte header (last=`0x00`, more=`0x40|len`)
- Authentication: HMAC-SHA256 over the grill-supplied nonce using the Ayla `local_key`
- JSON envelope: `{"o": "<opcode>", "i": <seq>, "p": {<payload>}}`

**Key module:** `bluetooth/protocol.py`

### API Client

**Directory:** `api/`

> **Napoleon Home:** The API client is used **only at config-flow time**. At runtime the integration
> communicates exclusively over BLE.

Handles all communication with the Ayla cloud API. Implements:

- Async HTTP requests using `aiohttp`
- Authentication against the Ayla cloud and listing all Prestige grills in an account
- Per-device BLE `local_key` fetch (`async_get_local_key`, `async_refresh_local_keys`)
- Error translation to custom exceptions

**Key class:** `NapoleonHomeApiClient` (in `api/client.py`)

### Config Flow

**Directory:** `config_flow_handler/`

> **Napoleon Home:** Uses a hub/sub-entry model. Three flows are implemented rather than the single
> user+reauth pattern in the blueprint template.

Implements the configuration UI for adding and configuring the integration.

**Structure:**

- `config_flow.py`: Main flow — BLE-first discovery, reauth; creates the hub entry
- `options_flow.py`: Options flow for poll interval configuration
- `schemas/`: Voluptuous schemas for options forms
- `subentry_flow.py`: Sub-entry flow — adds a grill to an existing account hub

| Flow       | Handler                                 | Purpose                                  |
| ---------- | --------------------------------------- | ---------------------------------------- |
| Main setup | `NapoleonHomeConfigFlowHandler`         | Create hub entry + first grill sub-entry |
| Subentry   | `NapoleonHomeGrillSubentryFlowHandler`  | Add another grill to an existing hub     |
| Reauth     | Step in `NapoleonHomeConfigFlowHandler` | Refresh `local_key` for all sub-entries  |

Setup is **BLE-discovery only** (`async_step_user` aborts with `discovery_required`). The flow
probes provisioning state (`_async_probe_ble`) immediately on advertisement and routes through
`provision_guide` / `factory_reset_guide` before reaching `key_retrieval` (credentials form).
Device matching in `key_retrieval` uses the DSN read from the open GATT DUID characteristic
during `_async_probe_ble` (`session.read_dsn()`) when known. If the DSN is unknown or not found
in the account, every account device's key is tried in turn — `_async_finish` performs real BLE
authentication, so the grill itself decides the match rather than a MAC heuristic.

**Key classes:**

- `NapoleonHomeConfigFlowHandler` (main flow, in `config_flow_handler/config_flow.py`)
- `NapoleonHomeGrillSubentryFlowHandler` (sub-entry flow, in `config_flow_handler/subentry_flow.py`)
- `NapoleonHomeOptionsFlow` (options, in `config_flow_handler/options_flow.py`)

### Base Entity

**Package:** `entity/`

Provides common functionality for all entities in the integration:

- Device information (via `entity_utils/device_info.py`)
- Unique ID generation
- Coordinator integration
- Availability tracking

> **Napoleon Home:** Availability is gated on `coordinator.authenticated` (BLE authentication
> state), not `last_update_success`. Individual entities may add further conditions (e.g., probe
> connected bitmask).

**Key class:** `NapoleonHomeEntity` (in `entity/base.py`)

### Grill State

> **Napoleon Home addition:** Holds the live state received from the grill and has no equivalent in
> the blueprint template.

**File:** `data.py` — `NapoleonHomeGrillState`

Holds the live state received from the grill. Updated by both:

- **Push** — `Odp` notifications for state-change events (settings, probe connected bitmask, etc.)
- **Poll** — `Gpr` requests every 30 s for temperature values

When a grill has active WiFi/MQTT, it suppresses `PRB_TMP_*` temperature pushes over BLE (they go
via MQTT to the Ayla cloud instead). `Gpr` polling is therefore required for temperature readings
in normal home use.

## Platform Organization

Each platform (sensor, binary_sensor, switch, etc.) follows this pattern:

```text
<platform>/
├── __init__.py              # Platform setup: async_setup_entry()
└── <entity_name>.py         # Individual entity implementation
```

Platform entities inherit from both:

1. Home Assistant platform base (e.g., `SensorEntity`)
2. `NapoleonHomeEntity` for common functionality

Availability is gated on `coordinator.authenticated` (not `last_update_success`), with additional
entity-specific conditions (e.g., probe connected bitmask for probe sensors).

## Data Flow

```text
BLE Advertisement (grill powers on)
         │
         ▼
NapoleonHomeBLEMixin._on_advertisement
         │ schedules
         ▼
_connect_and_run → establish_connection → start_notify → _authenticate
         │                                                     │
         │                                              auth OK event set
         ▼
_async_update_data (every 30 s)          _on_notification (push)
   sends Gpr for each prop                 routes Odp → updates state → ACKs
         │                                         │
         └──────────────┬──────────────────────────┘
                        ▼
              NapoleonHomeGrillState.update_from_property
                        │
              async_set_updated_data → entities update via coordinator
```

## AI Agent Instructions

This project includes comprehensive instruction files for AI coding assistants (GitHub Copilot,
Claude, etc.) to ensure consistent code generation that follows Home Assistant patterns and project
conventions.

### Instruction File Architecture

**Layered approach:**

1. **`AGENTS.md`** — High-level "survival guide" for all AI agents (project overview, workflow, validation)
2. **`.github/instructions/*.instructions.md`** — Detailed path-specific patterns (applied based on file being edited)
3. **`.github/copilot-instructions.md`** — GitHub Copilot-specific workflow guidance

### Available Instruction Files

| File                                           | Applies To                                            | Purpose                                                                        |
| ---------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------ |
| `blueprint.python.instructions.md`             | `**/*.py`                                             | Python code style, imports, type hints, async patterns, linting                |
| `blueprint.yaml.instructions.md`               | `**/*.yaml`, `**/*.yml`                               | YAML formatting, Home Assistant YAML conventions                               |
| `blueprint.json.instructions.md`               | `**/*.json`                                           | JSON formatting, schema validation, no trailing commas                         |
| `blueprint.markdown.instructions.md`           | `**/*.md`                                             | Markdown formatting, documentation structure, linting                          |
| `blueprint.shell.instructions.md`              | `**/*.sh`                                             | Shell script style and safety patterns                                         |
| `blueprint.commit-message.instructions.md`     | Commit messages                                       | Conventional Commits format                                                    |
| `blueprint.manifest.instructions.md`           | `**/manifest.json`                                    | Integration manifest requirements, quality scale, IoT class                    |
| `blueprint.configuration_yaml.instructions.md` | `**/configuration.yaml`                               | Home Assistant configuration patterns (deprecated for device integrations)     |
| `blueprint.config_flow.instructions.md`        | `**/config_flow_handler/**/*.py`, `**/config_flow.py` | Config flow patterns, discovery, reauth, reconfigure, unique IDs               |
| `blueprint.service_actions.instructions.md`    | `**/service_actions/**/*.py`                          | Service action implementation, registration in `async_setup()`, error handling |
| `blueprint.services_yaml.instructions.md`      | `**/services.yaml`                                    | Service action definitions, schema, descriptions, examples                     |
| `blueprint.entities.instructions.md`           | Entity platform files                                 | Entity implementation, EntityDescription, device info, state management        |
| `blueprint.coordinator.instructions.md`        | `**/coordinator/**/*.py`, `**/api/**/*.py`            | DataUpdateCoordinator patterns, error handling, caching, pull vs push          |
| `blueprint.api.instructions.md`                | `**/api/**/*.py`, `**/coordinator/**/*.py`            | API client implementation, exceptions, rate limiting, pagination               |
| `blueprint.diagnostics.instructions.md`        | `**/diagnostics.py`                                   | Diagnostics data collection, `async_redact_data()` for sensitive data          |
| `blueprint.repairs.instructions.md`            | `**/repairs.py`                                       | Repair flows, issue creation, severity levels, fix flows                       |
| `blueprint.translations.instructions.md`       | `**/translations/*.json`                              | Translation file structure, placeholders, nested keys                          |
| `blueprint.tests.instructions.md`              | `tests/**/*.py`                                       | Test patterns, fixtures, mocking, pytest conventions                           |

> [!NOTE]
> The `blueprint.*` instruction files use generic placeholders and are synced from the upstream
> template. Napoleon Home-specific patterns that diverge from the generic blueprint (BLE instead of
> HTTP, hub/subentry instead of single coordinator) are documented in `AGENTS.md`.

> [!NOTE]
> Entity platform files include: `alarm_control_panel/**/*.py`, `binary_sensor/**/*.py`,
> `button/**/*.py`, `camera/**/*.py`, `climate/**/*.py`, `cover/**/*.py`, `fan/**/*.py`,
> `humidifier/**/*.py`, `light/**/*.py`, `lock/**/*.py`, `number/**/*.py`, `select/**/*.py`,
> `sensor/**/*.py`, `siren/**/*.py`, `switch/**/*.py`, `vacuum/**/*.py`, `water_heater/**/*.py`,
> `entity/**/*.py`, `entity_utils/**/*.py`

### Instruction File Application

**GitHub Copilot:**

Uses frontmatter `applyTo` patterns to automatically apply instructions based on file being edited:

```yaml
---
applyTo:
  - "**/*.py"
---
```

**Other AI Agents:**

Typically read `AGENTS.md` for project overview and may use path-specific instructions when available.

### Maintaining Instructions

- Keep `AGENTS.md` concise (high-level guidance only, ~30,000 ft view)
- Put detailed patterns in path-specific `.instructions.md` files
- Update instructions when patterns change or new conventions emerge
- Remove outdated rules to prevent bloat
- Document major architectural decisions in `DECISIONS.MD`

### Using GitHub Copilot Coding Agent

**GitHub Copilot Coding Agent** can autonomously implement features and raise pull requests.

Once the project is set up, Copilot Coding Agent:

- Automatically reads all instruction files (`AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`)
- Runs validation scripts (`script/check`) to verify changes
- Creates pull requests with comprehensive implementations
- Can iterate based on test failures and linter errors

See [COPILOT_AGENT.md](./COPILOT_AGENT.md) for detailed usage instructions, example prompts, and troubleshooting.

## Key Design Decisions

See [DECISIONS.md](./DECISIONS.md) for architectural and design decisions made during development.

## Extension Points

### Adding a New Platform

1. Create directory: `custom_components/napoleon_home/<platform>/`
2. Implement `__init__.py` with `async_setup_entry()` — iterate `entry.runtime_data.items()` and call `async_add_entities(..., config_subentry_id=subentry_id)` for each coordinator
3. Create entity classes inheriting from platform base + `NapoleonHomeEntity`
4. Add platform to `PLATFORMS` in `const.py`

### Adding a New Service Action

1. Create service action handler in `service_actions/<service_name>.py`
2. Define service action in `services.yaml` with schema
3. Register service action in `__init__.py:async_setup()` (NOT `async_setup_entry`)

### Modifying Data Structure

1. Update `NapoleonHomeGrillState` in `data.py`
2. Update `_on_notification()` in `coordinator/listeners.py` to handle the new property opcode
3. Add the property key to the `Gpr` poll list in `_async_update_data()` if polling is needed
4. Update entity property implementations to read from the new state fields

### Modifying the BLE Protocol

> **Napoleon Home addition:** Guidance for changes to the Ayla Local Control v2 BLE layer.

1. **New opcode** — Add a handler branch in `NapoleonHomeBLEMixin._on_notification()` in `coordinator/listeners.py`
2. **New GATT characteristic** — Add the UUID constant to `const.py`; update `_connect_and_run()` in `coordinator/listeners.py` to subscribe or write to it
3. **Framing or authentication changes** — Update `bluetooth/protocol.py`; the `_send_msg()` and `_on_notification()` methods in `coordinator/listeners.py` call into the protocol module
4. **New property** — Add the property key constant to `const.py`; extend `NapoleonHomeGrillState` in `data.py`; follow "Modifying Data Structure" above

## Testing Strategy

- **Unit tests:** Test individual functions and classes in isolation
- **Integration tests:** Test coordinator with mocked BLE connection
- **Fixtures:** Shared test fixtures in `tests/conftest.py`

Tests mirror the source structure under `tests/`.

## Dependencies

Core dependencies (see `manifest.json`):

- `bleak` — Async BLE client library
- `bleak-retry-connector` — Robust BLE connection management with auto-retry
- `aiohttp` — Async HTTP client (Ayla cloud API, setup time only)
- Home Assistant 2025.7.0+ — Platform requirements

Development dependencies (see `requirements_dev.txt`, `requirements_test.txt`).
