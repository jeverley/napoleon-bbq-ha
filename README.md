# Napoleon Home

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

A Home Assistant integration for **Napoleon Prestige grills**, providing direct local Bluetooth control. Uses your Napoleon app account credentials once at setup to retrieve the per-device BLE local key, then communicates directly with the grill over Bluetooth — no cloud dependency during normal operation.

## Features

- **Bluetooth auto-discovery** — grills advertising as `Prestige-*` are detected automatically
- **Multiple grills** — add as many grills as you like under a single account
- **Probe and grill temperatures** — monitor Probe 1–3 plus grill temperature with configurable targets
- **Gas tank weight** — track remaining gas level
- **Grill controls** — knob lights, display brightness, battery saver mode, temperature and tank units
- **Power off** — remotely power off the grill from Home Assistant

## Entities

Each configured grill exposes the following entities.

**Standard** entities appear on the main device page:

| Platform | Entity                   | Description                   |
| -------- | ------------------------ | ----------------------------- |
| `sensor` | Probe 1–3 + Grill        | Live temperature readings     |
| `sensor` | Tank weight              | Remaining gas (kg or lbs)     |
| `number` | Probe 1–3 + Grill target | Alert threshold per channel   |
| `light`  | Knob lights              | Illuminated knob rings on/off |
| `button` | Power off                | Remotely power off the grill  |

**Configuration** entities appear in the device's configuration section:

| Platform | Entity             | Description                              |
| -------- | ------------------ | ---------------------------------------- |
| `number` | Automatic shutoff  | Grill automatic shutoff timeout (1–24 h) |
| `number` | Empty tank weight  | Gas calibration: empty tank weight       |
| `number` | Full tank weight   | Gas calibration: full tank weight        |
| `select` | Temperature unit   | Celsius or Fahrenheit                    |
| `select` | Tank unit          | Kilograms or pounds                      |
| `select` | Display brightness | Low, Medium, or High                     |

**Diagnostic** entities appear in the device's diagnostic section:

| Platform        | Entity             | Description                                     |
| --------------- | ------------------ | ----------------------------------------------- |
| `binary_sensor` | Status             | Whether the grill is reachable over BLE         |
| `binary_sensor` | Battery saver mode | Display battery saver mode                      |
| `sensor`        | Battery            | Controller battery level                        |
| `sensor`        | Firmware           | Grill firmware version                          |
| `sensor`        | Tank name          | Ayla-registered tank type (disabled by default) |
| `sensor`        | Region             | Grill region setting (disabled by default)      |
| `sensor`        | Country            | Grill country setting (disabled by default)     |

## Requirements

- Home Assistant 2026.4.0 or later
- [HACS](https://hacs.xyz/) installed in Home Assistant
- A Napoleon app account with your Prestige grill registered
- A Bluetooth adapter reachable by Home Assistant (built-in, USB, or [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) with active connections enabled)

## Installation

Click the button below to open the integration directly in HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jeverley&repository=napoleon-home-ha&category=integration)

Then click **Download** and **restart Home Assistant**.

<details>
<summary><strong>Manual installation</strong></summary>

1. Download the `custom_components/napoleon_home/` folder from this repository
2. Copy it to your Home Assistant `custom_components/` directory
3. Restart Home Assistant

</details>

## Setup

This integration can only be added via Bluetooth discovery. Power on your grill and ensure it is within Bluetooth range — Home Assistant will detect it automatically and prompt you to set it up.

### During setup you will need

| Field    | Description                              |
| -------- | ---------------------------------------- |
| Email    | Your Napoleon app email address          |
| Password | Your Napoleon app password               |
| Region   | The region your account is registered in |

If your account has multiple grills, you will be prompted to select which one to configure. Additional grills can be added afterwards via **Add grill** on the integration page.

### Options

After setup, click **Configure** on the integration to adjust:

| Option        | Default | Description                                 |
| ------------- | ------- | ------------------------------------------- |
| Poll interval | 30 s    | How often to request a full property update |

## Troubleshooting

### Grill not discovered automatically

Ensure the grill is powered on and within Bluetooth range of your Home Assistant host. If using an ESPHome Bluetooth proxy, confirm it has active connections enabled. Discovery may take a minute or two after the grill powers on.

### Reauthentication

If the grill's local key expires, Home Assistant will prompt for your Napoleon app credentials. Go to **Settings → Devices & Services → Napoleon Home → Reconfigure** to re-enter them.

### Grill bonded to another device

Home Assistant will raise a repair issue if the grill rejects the Bluetooth bond. The grill must be factory reset to clear its existing bond before it will accept a new pairing. To resolve:

1. **Factory reset the grill controller** to clear its existing Bluetooth bond (refer to your grill's manual for the reset procedure).
2. Resolve the repair issue in Home Assistant — HA will re-pair and bond with the grill.
3. Open the Napoleon app and re-provision the grill to restore cloud/app control.

The grill accepts new BLE bonds before cloud provisioning is complete, so the Napoleon app can bond and provision in step 3. Once provisioned, the grill locks out further new bonds — both Home Assistant and the Napoleon app retain their existing bonds and coexist.

### Enable debug logging

```yaml
logger:
  default: info
  logs:
    custom_components.napoleon_home: debug
```

## Contributing

Contributions are welcome! Please open an issue or pull request.

**✨ Develop in the cloud:** Open this repository directly in GitHub Codespaces — no local setup required.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/jeverley/napoleon-home-ha?quickstart=1)

<details>
<summary><strong>Local development setup</strong></summary>

Both options provide the same fully-configured environment with Home Assistant, Python 3.14, Node.js LTS, and all necessary tools.

### Option 1: GitHub Codespaces ☁️

1. Click the green **"Code"** button in this repository
2. Switch to the **"Codespaces"** tab
3. Click **"Create codespace on main"**
4. Wait for setup (2–3 minutes first time)

### Option 2: VS Code Dev Container 💻

**Prerequisites:** Docker and the [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) VS Code extension.

- **🍎 macOS / 🐧 Linux:** Clone the repo, open in VS Code, click **"Reopen in Container"**
- **🪟 Windows:** `F1` → **"Dev Containers: Clone Repository in Named Container Volume..."**

Once inside the container:

```bash
script/develop  # Home Assistant at http://localhost:8123
script/check    # Type-check, lint, spell
script/test     # Run tests
```

</details>

> [!NOTE]
> **AI-assisted development:** This integration was developed with assistance from AI coding agents (Claude, GitHub Copilot).

---

## License

MIT — see [LICENSE](LICENSE).

---

**Made by [@jeverley][user_profile]**

---

[commits-shield]: https://img.shields.io/github/commit-activity/y/jeverley/napoleon-home-ha.svg?style=for-the-badge
[commits]: https://github.com/jeverley/napoleon-home-ha/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/jeverley/napoleon-home-ha.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40jeverley-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/jeverley/napoleon-home-ha.svg?style=for-the-badge
[releases]: https://github.com/jeverley/napoleon-home-ha/releases
[user_profile]: https://github.com/jeverley
