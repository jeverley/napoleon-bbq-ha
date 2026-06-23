# Architectural and Design Decisions

This document records significant architectural and design decisions made during the development of this integration.

## Format

Each decision is documented with:

- **Date:** When the decision was made
- **Context:** Why this decision was necessary
- **Decision:** What was decided
- **Rationale:** Why this approach was chosen
- **Consequences:** Expected impacts and trade-offs

---

## Decision Log

### Use DataUpdateCoordinator for All Data Fetching

**Date:** 2025-11-29 (Template initialization)

**Context:** The integration needs to fetch data from an external API and share it with multiple entities. Home Assistant provides several patterns for this.

**Decision:** Use `DataUpdateCoordinator` from `homeassistant.helpers.update_coordinator` as the central data management component.

**Rationale:**

- Provides built-in support for update intervals and error handling
- Automatic retry with exponential backoff
- Shared data access prevents duplicate API calls
- Standard pattern recommended by Home Assistant
- Entities automatically become unavailable when coordinator fails

**Consequences:**

- All entities must inherit from `CoordinatorEntity`
- Single update interval applies to all entities
- Data is fetched even if no entities are enabled
- Coordinator manages entity lifecycle and availability

---

### Separate API Client from Coordinator

**Date:** 2025-11-29 (Template initialization)

**Context:** The coordinator needs to fetch data, but business logic should be separated from data transport.

**Decision:** Implement API communication in separate `api/client.py` module, coordinator only orchestrates updates.

**Rationale:**

- Separation of concerns: transport vs. orchestration
- Easier to test API client in isolation
- Simpler to swap API implementation if needed
- Clearer error handling boundaries

**Consequences:**

- Additional abstraction layer
- Coordinator depends on API client
- API client raises custom exceptions for error translation

---

### Platform-Specific Directories

**Date:** 2025-11-29 (Template initialization)

**Context:** Integration supports multiple platforms (sensor, binary_sensor, switch, etc.).

**Decision:** Each platform gets its own directory with individual entity files.

**Rationale:**

- Clear organization as integration grows
- Easier to find specific entity implementations
- Supports multiple entities per platform cleanly
- Follows Home Assistant Core pattern

**Consequences:**

- More files/directories than single-file approach
- Platform `__init__.py` must import and register entities
- Slightly more initial setup overhead

---

### EntityDescription for Static Metadata

**Date:** 2025-11-29 (Template initialization)

**Context:** Entities have static metadata (name, icon, device class) that doesn't change.

**Decision:** Use `EntityDescription` dataclasses to define static entity metadata.

**Rationale:**

- Declarative and easy to read
- Type-safe with dataclasses
- Recommended Home Assistant pattern
- Separates static configuration from dynamic behavior

**Consequences:**

- Each entity type needs an EntityDescription
- Dynamic entities need custom handling
- Static and dynamic properties clearly separated

---

### Ayla BLE Local Control (not cloud polling)

**Date:** 2026-06-22

**Context:** Napoleon grills use the Ayla IoT platform. Two runtime communication paths exist:
Ayla cloud REST API (polling) or Ayla Local Control v2 directly over BLE (JSON/GATT, HMAC-SHA256).

**Decision:** Communicate directly over BLE at runtime. The Ayla cloud API is used only at
setup time to authenticate and fetch the per-device BLE `local_key`.

**Rationale:**

- Local-only after setup; no cloud dependency at runtime
- Faster state updates; works offline
- `bleak-retry-connector` handles BLE reconnection robustly
- Avoids polling the cloud for data the device will push over BLE

**Consequences:**

- `api/` package is setup-time only; not imported at runtime
- `bluetooth/` package added for Ayla Local Control v2 protocol framing and HMAC-SHA256 auth
- `coordinator/` holds a persistent BLE connection via `NapoleonBBQBLEMixin`
- `iot_class: local_polling` (polling required for temperatures; see Push + Poll Hybrid decision)

---

### Hub/Sub-entry Architecture (multi-grill support)

**Date:** 2026-06-22

**Context:** Users may own multiple Napoleon grills under one Ayla account. The template's
"Future Considerations" noted "Multi-Device Support" as not yet implemented.

**Decision:** One config entry per Napoleon account (the hub), one `ConfigSubentry` per grill.
`entry.runtime_data` is `dict[str, NapoleonBBQDataUpdateCoordinator]` keyed by `subentry_id`.

**Rationale:**

- Correct HA pattern for a hub-with-devices model
- Reauth refreshes `local_key` for all grills in a single sign-in round-trip
- `async_get_supported_subentry_types` allows adding grills post-setup without a full re-setup
- Sub-entry unique ID (lowercase MAC) prevents duplicate grill registration across entries

**Consequences:**

- Resolves "Multi-Device Support" future consideration (see below)
- Entities must pass `config_subentry_id=subentry_id` to `AddConfigEntryEntitiesCallback`
- `entry.runtime_data` is a dict, not a single coordinator — blueprint entity patterns need
  adaptation (iterate `runtime_data.items()` in platform `async_setup_entry`)

---

### Push + Poll Hybrid (BLE + WiFi coexistence)

**Date:** 2026-06-22

**Context:** The template's "Future Considerations" noted "Polling vs Push" as unresolved. The
grill supports both `Odp` push notifications over BLE and `Gpr` poll requests.

**Decision:** Use both: `Odp` push for state-change events; `Gpr` polling every 30 s for
temperature values.

**Rationale:**

- When a grill has active WiFi/MQTT, it suppresses `PRB_TMP_*` temperature pushes over BLE
  (temperatures go via MQTT to Ayla cloud instead). Polling is therefore required for reliable
  temperature readings in normal home use.
- State-change events (probe connected, settings changes) still arrive via `Odp` BLE push and
  do not need polling.

**Consequences:**

- Resolves "Polling vs Push" future consideration (see below)
- `iot_class: local_polling` rather than `local_push`
- 30 s poll interval is the effective temperature refresh rate

---

## Future Considerations

### State Restoration

**Status:** Not yet implemented

Consider implementing state restoration for switches and configurable settings to maintain state across Home Assistant restarts when the external device is unavailable.

### Multi-Device Support

**Status:** Resolved — see [Hub/Sub-entry Architecture](#hubsub-entry-architecture-multi-grill-support) decision (2026-06-22)

### Polling vs. Push

**Status:** Resolved — see [Push + Poll Hybrid](#push--poll-hybrid-ble--wifi-coexistence) decision (2026-06-22)

---

## Decision Review

These decisions should be reviewed periodically (suggested: quarterly or when major features are added) to ensure they still serve the integration's needs.
