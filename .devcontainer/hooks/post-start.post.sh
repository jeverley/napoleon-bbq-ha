#!/usr/bin/env bash
# Kill any bluetoothd started by the bluez package installer inside the container.
# The WSL2 host's bluetoothd owns hci0 and is accessed via the bind-mounted
# /var/run/dbus/system_bus_socket — a second daemon in the container would
# conflict on L2CAP and prevent bleak from seeing the adapter.
if pgrep -x bluetoothd >/dev/null 2>&1; then
    echo "ℹ Stopping container bluetoothd (using WSL2 host daemon via D-Bus mount)"
    sudo pkill -x bluetoothd 2>/dev/null || true
fi
