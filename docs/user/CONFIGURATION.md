# Configuration Reference

## Options

After setup, click **Configure** on the Napoleon Home integration card to adjust:

| Option        | Default | Description                                 |
| ------------- | ------- | ------------------------------------------- |
| Poll interval | 30 s    | How often to request a full property update |

The poll interval controls how frequently the integration requests a full state
refresh from the grill over BLE. Lower values give more responsive entity
updates; higher values reduce Bluetooth traffic.

## Adding More Grills

Additional grills can be added at any time:

1. Go to **Settings** → **Devices & Services** → **Napoleon Home**
2. Click **Add grill**
3. Power on the grill and wait for discovery
4. Follow the same setup flow (credentials are reused)

## Reauthentication

If the grill's local key expires (rare), Home Assistant will prompt for your
Napoleon app credentials. Go to **Settings** → **Devices & Services** →
**Napoleon Home** → **Reconfigure** to re-enter them.

## Removing a Grill

To remove a single grill without uninstalling the integration:

1. Go to **Settings** → **Devices & Services** → **Napoleon Home**
2. Click the grill device
3. Click the three-dot menu → **Delete**

## Diagnostic Data

To help with troubleshooting, you can download diagnostic data:

1. Go to **Settings** → **Devices & Services** → **Napoleon Home**
2. Click the grill device
3. Click **Download Diagnostics**

Review the data before sharing — it includes entity states and connection
information but not your Napoleon app credentials.

## Related Documentation

- [Getting Started](./GETTING_STARTED.md) — Installation and initial setup
- [Examples](./EXAMPLES.md) — Automation and dashboard examples
- [GitHub Issues](https://github.com/jeverley/napoleon-home-ha/issues) — Report problems
