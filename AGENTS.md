# AI Agent Instructions

This document provides guidance for AI coding agents working on this Home Assistant custom integration project.

## Project Overview

This is a Home Assistant custom integration for Napoleon Prestige BBQ grills. The integration uses Ayla Local Control v2 (JSON over GATT, HMAC-SHA256 authentication) for direct BLE communication with each grill; the Ayla cloud API is used only at setup time to fetch per-device BLE local keys. It follows Home Assistant Core development patterns and quality standards.

**Integration details:**

- **Domain:** `napoleon_home`
- **Title:** Napoleon Home
- **Repository:** jeverley/napoleon-home-ha

**Key directories:**

- `custom_components/napoleon_home/` - Main integration code
- `config/` - Home Assistant configuration for local testing
- `tests/` - Unit and integration tests
- `script/` - Development and validation scripts

**Local Home Assistant instance:**

**Always use the project's scripts** — do NOT craft your own `hass`, `pip`, `pytest`, or similar commands. The scripts handle environment setup, virtual environments, port management, and cleanup that raw commands miss. Agents that bypass scripts frequently break.

**Devcontainer CLI tools:** The devcontainer provides common agent-facing CLI tools including `bat`, `delta`/`git-delta`, `eza`, `fd`/`fdfind`, `fzf`, `http`/`httpie`, `hyperfine`, `ipython`, `jq`, `jo`, `mlr`/`miller`, `rg`/`ripgrep`, `shellcheck`, `shfmt`, `sponge`, `sqlite3`, `tree`, `yq`, and `yamllint`. Prefer these explicit container tools over assuming a VS Code extension exposes an equivalent CLI on `PATH`.

**CLI compatibility notes:** Some commands are available via compatibility aliases because Debian package names differ from what agents often expect. Prefer `bat`, `fd`, `git-delta`, `httpie`, `ipython`, `miller`, and `ripgrep` as stable spellings. `yq` is installed as the Mike Farah variant, so standard `yq eval`/`yq e` syntax is expected.

**Start Home Assistant:**

```bash
./script/develop
```

**Force restart (when HA is unresponsive or port conflicts):**

```bash
pkill -f "hass --config" || true && pkill -f "debugpy.*5678" || true && ./script/develop
```

- Kills any existing instance (hass + debugpy on port 5678) and starts fresh
- Avoids state confusion and port conflicts

**When to restart:** After modifying Python files, `manifest.json`, `services.yaml`, translations, or config flow changes

**Reading logs:**

- Live: Terminal where `./script/develop` runs
- File: `config/home-assistant.log` (most recent), `config/home-assistant.log.1` (previous)

**Adjusting log levels:**

- Integration logs: `custom_components.napoleon_home: debug` in `config/configuration.yaml`
- You can modify log levels when debugging - just restart HA after changes

**Context-specific instructions:**

If you're using GitHub Copilot, path-specific instructions in `.github/instructions/*.instructions.md` provide additional guidance for specific file types (Python, YAML, JSON, etc.). This document serves as the primary reference for all agents.

**Other agent entry points:**

- **Claude Code:** See [`CLAUDE.md`](CLAUDE.md) (pointer to this file)
- **Gemini:** See [`GEMINI.md`](GEMINI.md) (pointer to this file)
- **GitHub Copilot:** See [`.github/copilot-instructions.md`](.github/copilot-instructions.md) (compact version of this file)

## Working With Developers

**For workflow basics (small changes, translations, tests, session management):** See `.github/copilot-instructions.md` for quick-reference guidance.

### When Instructions Conflict With Requests

If a developer requests something that contradicts these instructions:

1. **Clarify the intent** - Ask if they want you to deviate from the documented guidelines
2. **Confirm understanding** - Restate what you understood to avoid misinterpretation
3. **Suggest instruction updates** - If this represents a permanent change in approach, offer to update these instructions
4. **Proceed once confirmed** - Follow the developer's explicit direction after clarification

### Maintaining These Instructions

**Keep these instructions current.** As the integration evolves:

- Refine guidelines based on actual project needs
- Remove outdated rules that no longer apply
- Consolidate redundant sections to prevent bloat
- Keep files focused - Move architectural decisions to `docs/development/`

**Propose updates when:**

- You notice repeated deviations from documented patterns
- Instructions become outdated or contradict actual code
- New patterns emerge that should be standardized

### Documentation vs. Instructions

**Three types of content with clear separation:**

1. **Agent Instructions** - How AI should write code (`.github/instructions/`, `AGENTS.md`)
2. **Developer Documentation** - Architecture and design decisions (`docs/development/`)
3. **User Documentation** - End-user guides (`docs/user/`)

**AI Planning:** Use `.ai-scratch/` for temporary notes (never committed)

**Rules:**

- ❌ **NEVER** create random markdown files in code directories
- ❌ **NEVER** create documentation in `.github/` unless it's a GitHub-specified file
- ✅ **ALWAYS ask first** before creating permanent documentation
- ✅ **Prefer module docstrings** over separate markdown files

See `.github/copilot-instructions.md` for detailed documentation strategy.

### Session and Context Management

**Commit suggestions:**

When a task completes and the developer moves to a new topic, suggest committing changes. Offer a commit message based on the work done.

**Commit rules (CRITICAL):**

- **Never commit automatically** — only commit when the developer explicitly requests it
- A previous commit request is NOT a standing permission; each commit requires a fresh explicit instruction
- **Never ask about pushing** — the developer always handles `git push` themselves; do not offer or suggest it

**Commit message format:** Follow [Conventional Commits](https://www.conventionalcommits.org/) — see `.github/instructions/blueprint.commit-message.instructions.md` for full conventions, types, scopes, and examples.

## Custom Integration Flexibility

**This is a CUSTOM integration, not a Home Assistant Core integration.** While we follow Core patterns for quality and maintainability, we have more flexibility in implementation decisions:

**Third-party libraries (PyPI):**

- ✅ Prefer existing PyPI libraries when maintained and fit the use case
- ✅ Build custom API client when:
  - Device/service uses simple REST API or GraphQL (HTTP, JSON)
  - Available libraries are unmaintained, bloated, or poorly designed
  - Using aiohttp + json is more maintainable than a framework

**Decision process:**

1. Research available libraries (PyPI, GitHub)
2. Evaluate: Maintained? Async? Well-documented? Dependency footprint?
3. Consider protocol: Simple REST → aiohttp; Complex OAuth2 → library; Standard (MQTT) → industry library
4. Document decision in `docs/development/DECISIONS.md`

**Quality Scale expectations:**

As an AI agent, **aim for Silver or Gold Quality Scale** when generating code:

- ✅ **Always implement:** Type hints, async patterns, proper error handling, service registration in `async_setup()`, diagnostics with `async_redact_data()`, device info
- 🎯 **When applicable:** Config flow with validation, reauth flow, discovery support, repair flows
- 📋 **Can defer:** Advanced discovery, YAML import, extensive test coverage

**Developer expectation:** Generate production-ready code. Implement HA standards with reasonable effort.

**Other flexibility:** Discovery can be added later; breaking changes allowed with documentation; experimental features acceptable.

## Code Style and Quality

**Python:** 4 spaces, 120 char lines, double quotes, full type hints, async for all I/O

**YAML:** 2 spaces, modern HA syntax (no legacy `platform:` style)

**JSON:** 2 spaces, no trailing commas, no comments

**Validation:** Run `script/check` before committing (runs type-check + lint + spell)

**hassfest validation:** Run `script/hassfest` to validate against Home Assistant standards

- Validates manifest.json, translations, services.yaml, and integration structure
- Uses official Home Assistant Core validation scripts locally
- First run downloads ~27 MB, subsequent runs are fast with `--no-update`

**For comprehensive standards, see:**

- `.github/instructions/blueprint.python.instructions.md` - Python patterns, imports, type hints
- `.github/instructions/blueprint.yaml.instructions.md` - YAML structure and HA-specific patterns
- `.github/instructions/blueprint.json.instructions.md` - JSON formatting and schema validation
- `.github/instructions/blueprint.shell.instructions.md` - Shell script style, shfmt, shellcheck

**GitHub Copilot users:** These instruction files are automatically provided based on file type.

## Project-Specific Rules

### Integration Identifiers

This integration uses the following identifiers consistently:

- **Domain:** `napoleon_home`
- **Title:** Napoleon Home
- **Class prefix:** `NapoleonHome`

**When creating new files:**

- Use the domain `napoleon_home` for all DOMAIN references
- Prefix all integration-specific classes with `NapoleonHome`
- Use "Napoleon Home" as the display title
- Never hardcode different values

### Integration Structure

**Package organization (DO NOT create other packages):**

- `api/` — Ayla cloud API client and exceptions (`client.py`; used only at config-flow time to fetch `local_key`)
- `bluetooth/` — Ayla Local Control v2 BLE protocol helpers (`protocol.py`: framing, HMAC, JSON codec)
- `coordinator/` — BLE `DataUpdateCoordinator` (`base.py`: coordinator class; `listeners.py`: BLE mixin)
- `config_flow_handler/` — Config flow, options flow, subentry flow
  - `schemas/` — Voluptuous schemas for flow forms (`options.py`)
- `entity/` — Base entity class (`base.py`)
- `entity_utils/` — Entity helpers (`device_info.py`)
- `[platform]/` — Entity platforms (sensor, binary_sensor, switch, select, number, button)

**Create when needed (not yet present):**

- `service_actions/` — service action handlers, if service actions are added
- `utils/` — integration-wide utilities (MAC format helpers, input sanitisation, etc.)
- `config_flow_handler/validators/` — flow-specific validation functions, if validation logic grows too large to keep inline

**Do NOT create:**

- `helpers/`, `ha_helpers/`, or similar packages — use `utils/` or `entity_utils/` instead
- `common/`, `shared/`, `lib/` — use existing packages above
- New top-level packages without explicit approval

**Key patterns:**

- Entities → Coordinator → BLE client (never skip layers)
- Each platform in own directory with `__init__.py`
- One entity class per file for clarity
- Individual entity classes in separate files (e.g., `probe_temp.py`, `gas_tank_weight.py`)
- Use `EntityDescription` dataclasses for static entity metadata

**Code organization principles:**

- Keep files focused (200-400 lines per file)
- One class per file for entity implementations
- Split large modules into smaller ones when needed

**For detailed patterns, see:**

- `.github/instructions/blueprint.entities.instructions.md` - Entity platform patterns
- `.github/instructions/blueprint.coordinator.instructions.md` - Coordinator implementation
- `.github/instructions/blueprint.api.instructions.md` - API client patterns

### Hub and Sub-entry Architecture

This integration uses a hub/sub-entry model — **not** a single-config-entry-per-device model:

- **Hub entry** (one per Napoleon account) — stores `{CONF_REGION, CONF_USERNAME}`; unique ID is `f"{username.lower()}_{region_key}"` (e.g. `"user@example.com_eu"`)
- **Sub-entry** (one per grill) — stores `{CONF_MAC, CONF_DSN, CONF_LOCAL_KEY}`; unique ID is the BLE MAC address in lowercase (e.g. `"ff:ee:dd:cc:bb:aa"`)

**Type aliases (see `data.py`):**

- `NapoleonHomeConfigEntry = ConfigEntry[NapoleonHomeCoordinators]`
- `NapoleonHomeCoordinators = dict[str, NapoleonHomeDataUpdateCoordinator]` — keyed by `subentry_id` (not DSN, not MAC)

**`runtime_data`** is `NapoleonHomeCoordinators` (a plain `dict`). The `__init__.py` setup loop iterates `entry.subentries.items()` and filters by `subentry_type == SUBENTRY_TYPE_DEVICE`.

**Critical rules:**

- `ConfigSubentry.data` **must** be a `MappingProxyType` when constructing a `ConfigSubentry` for `async_add_subentry` directly
- `ConfigFlowHandler` **must** implement `async_get_supported_subentry_types()` returning `{SUBENTRY_TYPE_DEVICE: NapoleonHomeGrillSubentryFlowHandler}`
- When adding entities for a sub-entry, pass `config_subentry_id=subentry_id` to `AddConfigEntryEntitiesCallback` — omitting it silently attaches entities to the hub entry, breaking device attribution

**MAC casing convention:** stored uppercase everywhere — in config data (`CONF_DEVICES` keys: `"FF:EE:DD:CC:BB:AA"`) and in entity unique IDs (`unique_id="FF:EE:DD:CC:BB:AA_some_key"`).

### Device Info

All entities should provide consistent device info via the base entity class (manufacturer, model, serial number, configuration URL, firmware version).

### Integration Manifest

**Key fields in `manifest.json`:**

**integration_type** (CRITICAL):

- `hub` - Gateway to multiple devices/services (e.g., Philips Hue bridge)
- `device` - Single device per config entry (e.g., ESPHome device)
- `service` - Single service per config entry (e.g., DuckDNS)
- `helper` - Helper entity (e.g., input_boolean, group)
- `virtual` - Points to another integration/IoT standard (not for custom integrations)

**Rule:** Hub vs Service/Device is defined by nature: Hub = gateway to multiple devices/services; Service/Device = one per config entry.

**quality_scale:**

- Required for Core integrations (minimum `bronze`)
- Optional for custom integrations (not displayed in HA UI)
- Levels: `bronze`, `silver`, `gold`, `platinum`, `internal`
- If included, serves as self-documentation of code quality goals
- See [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale)

**iot_class:**

- `cloud_polling`, `cloud_push`, `local_polling`, `local_push`, `assumed_state`, `calculated`

**dependencies vs after_dependencies:**

- `dependencies` - Required, integration won't load without them
- `after_dependencies` - Optional, waits if configured

**Discovery methods:** `bluetooth`, `dhcp`, `homekit`, `mqtt`, `ssdp`, `usb`, `zeroconf`

- Define matchers in manifest
- Requires corresponding `async_step_<method>()` in config flow
- Unique ID required for discovery

**single_config_entry:** Set `true` to allow only one config entry per integration

See `.github/instructions/blueprint.manifest.instructions.md` for comprehensive manifest documentation.

### Config Flow Best Practices

**Reserved step names:**

- Discovery: `bluetooth`, `dhcp`, `homekit`, `mqtt`, `ssdp`, `usb`, `zeroconf`
- System: `user`, `reauth`, `reconfigure`, `import`

**Unique ID requirements (CRITICAL):**

- Acceptable: Serial number, MAC address, device ID, account ID
- Unacceptable: IP address, device name, hostname, URL

**Reconfigure vs Reauth:**

- `reconfigure` - Change config data (host, settings)
- `reauth` - Handle expired credentials

**Config entry migration:**

- Define `VERSION` and `MINOR_VERSION` in ConfigFlow
- Implement `async_migrate_entry()` in `__init__.py`
- Update entry with `hass.config_entries.async_update_entry()`
- Return `False` to reject downgrades

**Scaffold commands:**

```bash
python3 -m script.scaffold config_flow_discovery  # Discoverable, no auth
python3 -m script.scaffold config_flow_oauth2     # OAuth2 flow
```

## Home Assistant Patterns

**Config flow:**

- Implement in `config_flow_handler/` package
- Support user setup, discovery, reauth, reconfigure
- Always set unique_id for discovered entries
- **Design:** setup is BLE-discovery only — `async_step_user` aborts with `discovery_required`. The grill must be advertising when setup begins. The flow probes provisioning state via BLE (`_async_probe_ble`) and reads the DSN from the open GATT DUID characteristic (`00000001-fe28`) during the same connection. Routes through `provision_guide` / `factory_reset_guide` as needed before reaching `key_retrieval` (credentials form). Device matching uses DSN (from GATT read) when known; otherwise every account device's key is tried via real BLE auth until one is accepted by the grill.

See `.github/instructions/blueprint.config_flow.instructions.md` for comprehensive patterns.

**Coordinator:**

- Entities → Coordinator → BLE client (never skip layers)
- Uses persistent BLE connection (not poll-and-disconnect)
- Raise `ConfigEntryAuthFailed` (triggers reauth) or `UpdateFailed` (retry)
- Use `async_config_entry_first_refresh()` for first update — returns empty state if grill offline (no error)

**BLE / Bluetooth:**

- Protocol: Ayla Local Control v2 (JSON over GATT, HMAC-SHA256 auth) — see `bluetooth/protocol.py`
- Characteristics: Inbox `01000001-fe28-435b-991a-f1b21bb9bcd0` (write), Outbox `01000002-fe28-435b-991a-f1b21bb9bcd0` (notify)
- Auth flow: app sends `Oac t:1` with `"i":"android.user@email.com"` (fixed constant, not the account email), grill replies with nonce or `s:6` (not provisioned), app computes HMAC and sends `Oac t:2`, grill confirms (`oac t:2` with no `s` field = accepted; `s:4` = wrong HMAC)
- Poll: send `Gpr {"n": "<property>"}` → grill replies with `gpr {"n": ..., "v": ..., "t": <type>}` (type code also present in response; no ACK needed)
- Push: grill sends `Odp {"n": ..., "v": ..., "e": 1, "t": <type>}` → app ACKs with `odp` (same `i`, name only); coordinator calls `async_set_updated_data` immediately
- Write: send `Opr {"n": ..., "t": <type_code>, "v": <value>}` → grill replies with `opr`; `ukn {"o":"ukn","i":N,"s":3}` means invalid command (uses `s` not `p`)
- Ayla type codes for `t` field in `Opr`/`gpr`/`Odp`: `0`=int, `1`=decimal, `3`=bool, `4`=string
- **Odp/WiFi interaction (critical):** when grill has active WiFi/MQTT, it does NOT push `PRB_TMP_*` temperatures via BLE — they go via MQTT to Ayla cloud instead. State-change pushes (`PRB_STAT`, `TUNIT`, `LCD_OFF` etc.) still arrive over BLE. This is why `Gpr` polling at 30 s is required for temperature values in normal home use.
- Connection lifecycle: startup always waits for a genuine advertisement — `_async_setup` calls `_register_bt_callback` directly (no cached-device fast-path); `async_register_callback` fires immediately with HA's bluetooth history, so `_skip_history_replay` suppresses that synchronous replay and requires a real new advertisement to trigger a connect; `_connecting: bool` flag prevents concurrent `_connect_and_run` tasks from rapid re-advertisements; on disconnect `_on_disconnect` re-registers the advertisement callback; `_circuit_open: bool` is set after `MAX_CONNECT_FAILURES` to permanently suppress re-registration until entry reload
- Failure cap: `BleakNotFoundError`/`TimeoutError` from `establish_connection` (e.g. grill busy with another app) are caught before the outer failure counter and do not increment `_connect_failures`; `_connect_failures` resets to 0 after successful authentication **and** on clean disconnect from an authenticated session (so a powered-off grill doesn't accumulate failures toward the circuit breaker)
- Library: `bleak-retry-connector` (`establish_connection` with `max_attempts=1` + `BleakClientWithServiceCache`); `establish_connection` handles slot-draining via `wait_for_disconnect` and error classification before raising; outer retry is per-advertisement-event via `_connect_failures`
- `habluetooth` always injects FAST connection params (7.5 ms interval) via `HaBleakClient.connect()` regardless of the call path — this is expected HA behaviour, not a bug
- **BLE bonding required:** INBOX writes require an encrypted link from a bonded peer (ATT error 0x05 otherwise). The integration calls `client.pair()` before `start_notify`. On first connect this triggers Just Works LE Secure Connections pairing — BlueZ handles the USER_CONFIRM_REQUEST automatically without a registered NoInputNoOutput agent (confirmed on Linux/BlueZ with `bleak-retry-connector`). On subsequent connects BlueZ uses the stored LTK and `pair()` returns immediately. Non-rejection exceptions from `pair()` (e.g. "already bonded") are swallowed and the code proceeds; `start_notify` then confirms whether the link is actually encrypted. A genuine SMP rejection (grill bonded to another device) raises `org.bluez.Error.AuthenticationFailed` or `org.bluez.Error.AuthenticationRejected` and is caught by `_is_pairing_rejected` → `NapoleonHomeAlreadyBondedError`.
- **HMAC formula (confirmed by hardware test):** `HMAC-SHA256(key=local_key.encode("utf-8"), msg=b"response" + base64.b64decode(challenge_b64))`. The key is the raw local_key string encoded as UTF-8 — do NOT base64-decode it. A wrong HMAC causes the grill to return `s:4` on the `oac t:2` response and `s:3` on all subsequent `Gpr` requests.

**Prestige property sentinels and bitmasks:**

- `PRB_TMP_*` = `4095.0` when probe not connected; use `PRB_STAT` bitmask for `available` (more reliable than value sentinel)
- `PRB_STAT` bitmask: bit 0 = probe 1, bit 1 = probe 2, bit 2 = probe 3, bit 3 = probe 4
- `TNK_WT` = `-14400` when gas tank not configured
- `PRB_TMP_FOUR` quirk: Prestige IF2 has 3 physical probe sockets; probe 4 reads 0.0 at ambient while physical probes read ~24 °C — may be an internal grill thermistor that only reports values when the burner heats the hood above ambient (unconfirmed)

**GATT readable characteristics (service `0000fe28`):**

Requires bond (ATT 0x0F without an active encrypted session):

| Short UUID      | Name                         | Example value                                              |
| --------------- | ---------------------------- | ---------------------------------------------------------- |
| `00000001-fe28` | `GATT_CHAR_DUID`             | `"AC000W011111111"` (DSN / serial number)                  |
| `00000002-fe28` | `GATT_CHAR_OEM_ID`           | `"146516a1"` (Napoleon's Ayla OEM ID — not used in crypto) |
| `00000003-fe28` | `GATT_CHAR_OEM_MODEL`        | `"thermometer-mqtt-eu"` (EU); `"thermometer-mqtt-us"` (US) |
| `00000004-fe28` | `GATT_CHAR_TEMPLATE_VERSION` | `"v3.0.19"` (firmware)                                     |
| `00000006-fe28` | `GATT_CHAR_DISPLAY_NAME`     | user-configurable alias                                    |

Note: On provisioned hardware, both `GATT_CHAR_DUID` (DSN) and `GATT_CHAR_DISPLAY_NAME` require an encrypted (bonded) link — reads before `pair()` fail with ATT error 0x0F (Insufficient Encryption).

**Prestige property name reference:**

Temperature / sensors:

| Property                                   | Meaning                                               |
| ------------------------------------------ | ----------------------------------------------------- |
| `PRB_TMP_ONE` / `TWO` / `THREE` / `FOUR`   | Probe 1–4 temperature (4095.0 = disconnected)         |
| `PRB_STAT`                                 | Probe connected state bitmask (bits 0–3 = probes 1–4) |
| `TRGT_TMP_ONE` / `TWO` / `THREE` / `FOUR`  | Target temperature probe 1–4                          |
| `TRGT_STAT_ONE` / `TWO` / `THREE` / `FOUR` | Target temperature state probe 1–4                    |

Timers:

| Property                                      | Meaning               |
| --------------------------------------------- | --------------------- |
| `CKTIME`                                      | Cook time             |
| `TMR_STAT_ONE` / `TWO` / `THREE` / `FOUR`     | Timer state probe 1–4 |
| `TMR_ALRT_PRB_ONE` / `TWO` / `THREE` / `FOUR` | Timer alert probe 1–4 |
| `TMP_ALRT_PRB_ONE` / `TWO` / `THREE` / `FOUR` | Temp alert probe 1–4  |

Settings:

| Property     | Meaning                                     |
| ------------ | ------------------------------------------- |
| `TUNIT`      | Temperature unit (0=Celsius, 1=Fahrenheit)  |
| `BSMODE`     | Display power save (0=off, 1=on)            |
| `LCD_OFF`    | Knob lights off (0=on, 1=off)               |
| `BRT_LVL`    | Display brightness (1=low, 3=mid, 5=high)   |
| `AUTO_T_OUT` | Auto-shutoff timeout (grill stores minutes) |
| `DEVC_NME`   | Device name                                 |
| `TOFF`       | Turn off                                    |

Notes:

- `BSMODE`: grill resets to 0 on every **power cycle** (confirmed by hardware test); persists across BLE-only disconnects; coordinator stores `_bsmode_desired`, writes it post-auth, and re-asserts on `Odp BSMODE=0`
- `LCD_OFF`: logic inverted from name (0=on, 1=off)
- `BRT_LVL`: 0 is an invalid residual value — mapped to "low" on read, only 1/3/5 are written
- `AUTO_T_OUT`: stored in minutes by the grill; HA entity converts ÷60 on read, ×60 on write (range 1–24 h)

Gas tank:

| Property      | Meaning                                     |
| ------------- | ------------------------------------------- |
| `GS_UNT`      | Gas unit (0=kg, 1=lbs)                      |
| `GS_TNK_NAME` | Gas tank name                               |
| `TNK_WT`      | Tank weight (-14400 = not configured)       |
| `EMTY_TNK_W`  | Empty tank weight                           |
| `F_TNKWT`     | Full tank weight                            |
| `NTC_VLU`     | NTC thermistor reading (tank weight sensor) |

Probe / cook names:

| Property                                             | Meaning               |
| ---------------------------------------------------- | --------------------- |
| `PRB_ONE_NME` / `TWO_NME` / `THREE_NME` / `FOUR_NME` | Probe 1–4 custom name |
| `CKNME_PRB_ONE` / `TWO` / `THREE` / `FOUR`           | Cook name probe 1–4   |

System / misc:

| Property            | Meaning                          |
| ------------------- | -------------------------------- |
| `version`           | Firmware version                 |
| `oem_host_version`  | OEM host version                 |
| `RSSI`              | RSSI value                       |
| `BT_LVL`            | Battery level (0–5 bar; ×20 = %) |
| `RST_CNT`           | Reset count                      |
| `battery_low_alert` | Battery low alert                |

See `.github/instructions/blueprint.coordinator.instructions.md` and `.github/instructions/blueprint.api.instructions.md` for details.

**Service actions:**

- Define in `services.yaml` with full descriptions
- Implement handlers in `service_actions/` directory (create it when needed)
- **Register in `async_setup()`** — NOT in `async_setup_entry()` (Quality Scale!)
- Format: `<integration_domain>.<action_name>`

See `.github/instructions/blueprint.service_actions.instructions.md` for service patterns.

**Repairs:**

- Create `repairs.py` in integration root (Gold Quality Scale)
- Use `async_create_issue()` with severity levels (WARNING, ERROR, CRITICAL)
- Implement `RepairsFlow` for guided user fixes
- Delete issues after successful repair

See `.github/instructions/blueprint.repairs.instructions.md` for comprehensive patterns.

**Entities:**

- Inherit from platform base + `NapoleonHomeEntity`
- Read from `coordinator.data`, never call API directly
- Use `EntityDescription` for static metadata

See `.github/instructions/blueprint.entities.instructions.md` for entity patterns.

**Entity availability:**

- BLE entities must gate on `coordinator.authenticated`, **not** `coordinator.last_update_success`
- The coordinator stays alive (and `last_update_success` remains True) even when the grill is not connected; only `authenticated` reflects a live, authenticated BLE session
- Add entity-specific conditions on top (e.g. probe sensors also check `coordinator.data.probe_connected(probe)`)
- Don't raise exceptions from `@property` methods

**State updates:**

- Use `self.async_write_ha_state()` for immediate updates
- Let coordinator handle periodic updates
- Minimize API calls (batch requests when possible)

**Setup failure handling:**

- `ConfigEntryNotReady` - Device offline/timeout, auto-retry, don't log manually (HA logs at debug)
- `ConfigEntryAuthFailed` - Expired credentials, triggers reauth flow, alternative: `entry.async_start_reauth()`

**Diagnostics:**

- **CRITICAL:** Use `async_redact_data()` from `homeassistant.helpers.redact` to remove sensitive data
- Redact: Passwords, API keys, tokens, location data, personal information

**YAML Configuration:**

⚠️ **DEPRECATED** for integrations communicating with devices/services (ADR-0010)

- New integrations MUST use config flow
- Existing YAML integrations should migrate to config flow
- Only helpers and system integrations may use YAML

## Validation Scripts

**Before committing, always run the full suite:**

```bash
script/check      # Full validation: type-check + lint-check + spell-check
```

**After editing specific file types, use the targeted script — it is faster:**

| Changed files                          | Run this                              | Why faster                                        |
| -------------------------------------- | ------------------------------------- | ------------------------------------------------- |
| `*.py` only                            | `script/python` + `script/type-check` | Fixes + reports ruff; skips yaml, shell, markdown |
| `*.yaml` / `*.yml` only                | `script/yaml-check`                   | Skips Python, Shell, Markdown, types              |
| `*.md` only                            | `script/markdown`                     | Prettier + markdownlint only                      |
| `script/` or `.devcontainer/*.sh` only | `script/shell` + `script/shell-check` | Fixes shfmt, then checks shellcheck               |
| Multiple types or unsure               | `script/lint` + `script/type-check`   | Safe default for agents                           |

**Recommended agent workflow — fix scripts already show what they couldn't fix:**

Fix-mode scripts auto-heal files **and** print remaining unfixable errors in their output.
No separate check-run is needed after a fix-mode script — its exit code and output tell you
what still needs manual attention.

```bash
# Run this loop until both commands exit 0:
script/lint         # Fixes Python + shell + markdown formatting; checks yaml + shellcheck; shows all remaining
script/type-check   # Pyright type errors — no auto-fix ever, always a manual loop
# Then fix remaining issues from the output above and repeat.
```

> **Note:** `script/lint-check`, `script/python-check`, and `script/check` are **check-only**
> (read-only, no file writes). Use them in CI/CD pipelines where side effects are not desirable.
> AI agents should always use the fix-mode scripts to benefit from auto-healing.

**Fix / format scripts (apply changes automatically):**

```bash
script/lint         # Format + fix all types (Python, Shell, Markdown)
script/python       # Ruff format + ruff check --fix  (Python only)
script/shell        # shfmt -w                        (Shell only)
script/spell        # codespell --write-changes        (spelling)
script/markdown     # Prettier --write + markdownlint  (Markdown only)
```

**Check-only scripts (never modify files):**

```bash
script/lint-check   # Check all types without changes
script/python-check # Ruff format --check + ruff check  (Python only)
script/yaml-check   # yamllint                           (YAML only)
script/shell-check  # shfmt -d + shellcheck              (Shell only)
script/markdown-check # Prettier --check + markdownlint  (Markdown only)
script/type-check   # Pyright                            (types only)
script/spell-check  # codespell                          (spelling only)
script/test         # pytest                             (tests only)
```

**Configured tools:**

| Tool                  | Scope                        | Fixes?               |
| --------------------- | ---------------------------- | -------------------- |
| **Ruff**              | Python lint + format         | ✅ `script/python`   |
| **Pyright**           | Python type checking         | ❌ manual            |
| **yamllint**          | YAML structure + style       | ❌ manual            |
| **shfmt**             | Shell script formatting      | ✅ `script/shell`    |
| **shellcheck**        | Shell script static analysis | ❌ manual            |
| **Prettier**          | Markdown formatting          | ✅ `script/markdown` |
| **markdownlint-cli2** | Markdown structure + style   | ✅ `script/markdown` |
| **codespell**         | Spelling in code + docs      | ✅ `script/spell`    |
| **pytest**            | Unit + integration tests     | ❌ n/a               |

References: [Ruff rules](https://docs.astral.sh/ruff/rules/) · [Pyright docs](https://microsoft.github.io/pyright/)

**Generate code that passes these checks on first run.** As an AI agent, you should produce higher quality code than manual development:

- Type hints are trivial for you to generate
- Async patterns are well-known to you
- Import management is automatic for you
- Naming conventions can be applied consistently

Aim for zero validation errors in generated code. The developer expects production-ready output.

See `.github/instructions/blueprint.python.instructions.md` for linter overrides and error recovery strategies.

- You may use `# noqa: CODE` or `# type: ignore` when genuinely necessary
- Use sparingly and only with good reason (e.g., false positives, external library issues)

### Error Recovery Strategy

**When validation fails, run `script/lint` first** — it auto-fixes Python and shell formatting,
and its output already shows everything it could not fix automatically (yamllint, shellcheck,
unfixable ruff errors). No separate check-run is needed on top.

For Pyright type errors run `script/type-check` — there is no auto-fix for type errors ever.

After auto-fixes are applied, only manually edit files for errors that **remain in the output**.

**Iteration strategy for remaining errors:**

1. **First attempt** — Fix the specific error reported by the tool
2. **Second attempt** — If it fails again, reconsider your approach (maybe your understanding was wrong)
3. **Third attempt** — If still failing, ask for clarification rather than looping indefinitely
4. **After 3 failed attempts** — Stop and explain what you tried and why it's not working

**When tool operations fail:**

- **File read/write errors** - Verify path exists, check for typos, try once more
- **Terminal timeouts** - Don't retry automatically; inform the user and suggest manual intervention
- **API/network timeouts in tests** - Mention in response, don't silently ignore
- **Git operations fail** - Report the error immediately; don't attempt to work around it

**When gathering context:**

- Start with semantic_search (1-2 queries maximum)
- Read 3-5 most relevant files based on search results
- If still unclear, read 2-3 more specific files
- **After ~10 file reads, you should have enough context** - make a decision or ask for clarification
- Don't fall into infinite research loops

**Context gathering strategy:**

1. **First pass** - semantic_search to find relevant areas (1-2 queries)
2. **Second pass** - Read the 3-5 most relevant files identified
3. **Evaluate** - Do you have enough context to proceed? If yes, start implementation
4. **Third pass (if needed)** - Read 2-3 additional specific files for missing details
5. **Decision point** - After ~10 file reads total, you must either:
   - Proceed with implementation based on available context
   - Ask the developer specific questions about what's unclear
   - Never continue searching indefinitely without making progress

## Testing

**Test structure:**

- `tests/` mirrors `custom_components/napoleon_home/` structure
- Use fixtures for common setup (Home Assistant mock, coordinator, etc.)
- Mock external API calls

**Running tests:**

```bash
script/test                           # All tests
script/test --cov-html                # With coverage report
script/test --snapshot-update         # Update Syrupy snapshots
```

See `.github/instructions/blueprint.tests.instructions.md` for comprehensive testing patterns.

## Breaking Changes

**Always warn the developer before making changes that:**

- Change entity IDs or unique IDs (users' automations will break)
- Modify config entry data structure (existing installations will fail)
- Change state values or attributes format (dashboards and automations affected)
- Alter service call signatures (user scripts will break)
- Remove or rename config options (users must reconfigure)

**Never do without explicit approval:**

- Removing config options (even if "unused")
- Changing service parameters or return values
- Modifying how data is stored in config entries
- Renaming entities or changing their device classes
- Changing unique_id generation logic

**How to warn:**

> "⚠️ This change will modify the entity ID format from `sensor.device_name` to `sensor.device_name_sensor`. Existing users' automations and dashboards will break. Should I proceed, or would you prefer a migration path?"

**When breaking changes are necessary:**

- Document the breaking change in commit message (`BREAKING CHANGE:` footer)
- Consider providing migration instructions
- Suggest version bump (major version change)
- Update documentation if it exists

## File Changes

**Scope Management:**

**Single logical feature or fix:**

- Implement completely even if it spans 5-8 files
- Example: New sensor needs entity class + platform init + code → implement all together
- Example: Bug fix requires changes in coordinator + entity + error handling → do all at once

**Multiple independent features:**

- Implement one at a time
- After completing each feature, suggest committing before proceeding to the next

**Large refactoring (>10 files or architectural changes):**

- Propose a plan first before starting implementation
- Get explicit confirmation from developer

**Important: Do NOT create or modify tests unless explicitly requested.** Focus on implementing functionality. The developer decides when and if tests are needed.

**Translation strategy:**

- Use placeholders in code (e.g., `"config.step.user.title"`) - functionality works without translations
- Update `en.json` only when asked or at major feature completion
- NEVER update other language files automatically - extremely time-consuming
- Ask before updating multiple translation files
- Priority: Business logic first, translations later

See `.github/copilot-instructions.md` for detailed workflow guidance.

## Research and Validation

**When uncertain, consult official documentation:**

- **Always check current patterns** in [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- **Read the blog** at [Home Assistant Developer Blog](https://developers.home-assistant.io/blog/) for recent changes and best practices
- **Search for examples** using Google: `site:developers.home-assistant.io [your topic]`
- **Verify with tools** before assuming - run `script/check` to catch issues early

**Don't rely on assumptions:**

- Home Assistant APIs and patterns evolve frequently
- What worked in older versions may be deprecated
- Use official docs and working examples over guesswork
- When in doubt, search for recent integration examples in Home Assistant Core

**Tool documentation:**

- [Ruff Rules](https://docs.astral.sh/ruff/rules/) - Understand what each rule checks
- [Pyright Configuration](https://microsoft.github.io/pyright/#/configuration) - Type checking options
- Don't hesitate to look up specific error codes when validation fails

## Tool Parallelization

**Safe to call in parallel:**

- Multiple `read_file` operations (different files or different sections of same file)
- `file_search` + `read_file` + `grep_search` (independent read-only operations)
- `semantic_search` followed by parallel `read_file` of results (but only 1 semantic_search at a time)

**Never call in parallel:**

- Multiple `run_in_terminal` commands (execute sequentially, wait for output)
- Multiple `replace_string_in_file` on the same file (use `multi_replace_string_in_file` instead)
- `semantic_search` with other `semantic_search` (execute one at a time)

**Best practices:**

- Batch independent read operations together in one parallel call
- After gathering context in parallel, provide brief progress update before proceeding
- For file edits, use `multi_replace_string_in_file` when making multiple changes
- Terminal commands must always be sequential to see output before next command

## Additional Resources

- [Home Assistant Developer Docs](https://developers.home-assistant.io/) - Primary reference
- [Integration Quality Scale](https://developers.home-assistant.io/docs/integration_quality_scale_index)
- [Architecture Docs](https://developers.home-assistant.io/docs/architecture_index)
- [Ruff Rules](https://docs.astral.sh/ruff/rules/) - Linter documentation
- [Pyright Configuration](https://microsoft.github.io/pyright/#/configuration) - Type checker documentation
- [pytest Documentation](https://docs.pytest.org/) - Testing framework
- See `CONTRIBUTING.md` for contribution guidelines
