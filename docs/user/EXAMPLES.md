# Examples

Ready-to-use automations and dashboard cards for Napoleon Home.

Replace `your_grill` in entity IDs with your grill's actual device name
(visible in **Settings** → **Devices & Services** → **Napoleon Home**).

## Automations

### Alert when a probe temperature exceeds a target

```yaml
automation:
  - alias: "Probe 1 reached target"
    trigger:
      - trigger: numeric_state
        entity_id: sensor.your_grill_probe_1_temperature
        above: 75
    action:
      - action: notify.notify
        data:
          title: "Grill ready"
          message: "Probe 1 has reached {{ states('sensor.your_grill_probe_1_temperature') }}°"
```

### Alert when grill goes offline

```yaml
automation:
  - alias: "Grill disconnected"
    trigger:
      - trigger: state
        entity_id: binary_sensor.your_grill_status
        to: "off"
        for:
          minutes: 2
    action:
      - action: notify.notify
        data:
          title: "Grill offline"
          message: "Napoleon grill is no longer reachable over Bluetooth."
```

### Power off the grill at a scheduled time

```yaml
automation:
  - alias: "Auto power off at midnight"
    trigger:
      - trigger: time
        at: "00:00:00"
    condition:
      - condition: state
        entity_id: binary_sensor.your_grill_status
        state: "on"
    action:
      - action: button.press
        target:
          entity_id: button.your_grill_power_off
```

### Turn on knob lights at sunset

```yaml
automation:
  - alias: "Knob lights at sunset"
    trigger:
      - trigger: sun
        event: sunset
    action:
      - action: light.turn_on
        target:
          entity_id: light.your_grill_knob_lights
```

## Dashboard Cards

### Temperature overview

```yaml
type: entities
title: Grill temperatures
entities:
  - entity: sensor.your_grill_grill_temperature
    name: Grill
  - entity: sensor.your_grill_probe_1_temperature
    name: Probe 1
  - entity: sensor.your_grill_probe_2_temperature
    name: Probe 2
  - entity: sensor.your_grill_probe_3_temperature
    name: Probe 3
```

### Temperature history graph

```yaml
type: history-graph
title: Grill temperatures (last 2 h)
entities:
  - entity: sensor.your_grill_grill_temperature
    name: Grill
  - entity: sensor.your_grill_probe_1_temperature
    name: Probe 1
  - entity: sensor.your_grill_probe_2_temperature
    name: Probe 2
  - entity: sensor.your_grill_probe_3_temperature
    name: Probe 3
hours_to_show: 2
```

### Full grill status card

```yaml
type: entities
title: Napoleon Prestige
entities:
  - entity: binary_sensor.your_grill_status
    name: Status
  - entity: sensor.your_grill_grill_temperature
    name: Grill temp
  - entity: sensor.your_grill_probe_1_temperature
    name: Probe 1
  - entity: sensor.your_grill_gas_tank_weight
    name: Gas remaining
  - entity: light.your_grill_knob_lights
    name: Knob lights
  - entity: select.your_grill_display_brightness
    name: Brightness
  - entity: button.your_grill_power_off
    name: Power off
```

## Related Documentation

- [Configuration Reference](./CONFIGURATION.md) — Available options
- [Getting Started](./GETTING_STARTED.md) — Installation and setup
- [GitHub Issues](https://github.com/jeverley/napoleon-home-ha/issues) — Report problems
