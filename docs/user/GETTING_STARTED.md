# Getting Started with Napoleon Home

This guide walks you through installing and setting up the Napoleon Home integration for Home Assistant.

## Prerequisites

- Home Assistant 2026.4.0 or later
- [HACS](https://hacs.xyz/) installed in Home Assistant
- A Napoleon app account with your Prestige grill registered
- A Bluetooth adapter reachable by Home Assistant (built-in, USB, or
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
  with active connections enabled)

## Installation

### Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jeverley&repository=napoleon-home-ha&category=integration)

Click the button above, then click **Download** and restart Home Assistant.

<details>
<summary>Manual HACS steps</summary>

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three-dot menu → **Custom repositories**
4. Add `https://github.com/jeverley/napoleon-home-ha` as an **Integration**
5. Find **Napoleon Home** and click **Download**
6. Restart Home Assistant

</details>

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/jeverley/napoleon-home-ha/releases)
2. Copy the `custom_components/napoleon_home/` folder to your Home Assistant
   `custom_components/` directory
3. Restart Home Assistant

## Setup

This integration is added via **Bluetooth discovery only** — there is no manual
"Add Integration" search path. Power on your grill and bring it within Bluetooth
range. Home Assistant will detect it automatically and show a notification to
begin setup.

During setup you will be asked for:

| Field    | Description                              |
| -------- | ---------------------------------------- |
| Email    | Your Napoleon app email address          |
| Password | Your Napoleon app password               |
| Region   | The region your account is registered in |

Your credentials are used once to retrieve the grill's BLE local key from the
Ayla cloud. After setup, the integration communicates directly with the grill
over Bluetooth — no cloud dependency during normal operation.

If your account has multiple grills, you will be prompted to select which one to
configure. Additional grills can be added afterwards via **Add grill** on the
integration page.

## Entities

Each configured grill exposes the following entities:

| Platform        | Entity                   | Description                              |
| --------------- | ------------------------ | ---------------------------------------- |
| `binary_sensor` | Status                   | Whether the grill is reachable over BLE  |
| `binary_sensor` | Battery saver mode       | Display battery saver mode (diagnostic)  |
| `sensor`        | Probe 1–3 + Grill        | Live temperature readings                |
| `sensor`        | Battery                  | Controller battery level                 |
| `sensor`        | Gas tank weight          | Remaining gas (kg or lbs)                |
| `sensor`        | Firmware                 | Grill firmware version (diagnostic)      |
| `number`        | Automatic shutoff        | Grill automatic shutoff timeout (1–24 h) |
| `number`        | Probe 1–3 + Grill target | Alert threshold per temperature channel  |
| `number`        | Empty / Full tank weight | Gas calibration weights                  |
| `light`         | Knob lights              | Illuminated knob rings on/off            |
| `select`        | Temperature unit         | Celsius or Fahrenheit                    |
| `select`        | Tank unit                | Kilograms or Pounds                      |
| `select`        | Display brightness       | Low, Medium, or High                     |
| `button`        | Power off                | Remotely power off the grill             |

## Next Steps

- See [CONFIGURATION.md](./CONFIGURATION.md) for available options after setup
- See [EXAMPLES.md](./EXAMPLES.md) for automation and dashboard examples
- Report issues at [GitHub Issues](https://github.com/jeverley/napoleon-home-ha/issues)
