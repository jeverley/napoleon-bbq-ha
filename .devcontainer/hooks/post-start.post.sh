#!/usr/bin/env bash
# Kill any bluetoothd started by the bluez package installer inside the container.
# The WSL2 host's bluetoothd owns hci0 and is accessed via the bind-mounted
# /var/run/dbus/system_bus_socket — a second daemon in the container would
# conflict on L2CAP and prevent bleak from seeing the adapter.
if pgrep -x bluetoothd >/dev/null 2>&1; then
    echo "ℹ Stopping container bluetoothd (using WSL2 host daemon via D-Bus mount)"
    sudo pkill -x bluetoothd 2>/dev/null || true
fi

# Configure BLE security settings — btmgmt discovers the default adapter automatically,
# handles the MGMT response loop internally, and avoids the hardcoded-index-0 issue.
#   bondable=on  — allow Just Works bonding so BlueZ can pair with the grill on first connect.
#   secure-conn=on — negotiate LE Secure Connections with grill if it supports them.
timeout 3 btmgmt bondable on 2>/dev/null || true
timeout 3 btmgmt secure-conn on 2>/dev/null || true
# Keep adapter permanently pairable (PairableTimeout=0) so BlueZ doesn't revert
# bondable to off after the default 180-second countdown.
bluetoothctl -- pairable on 2>/dev/null | grep -E "Changing|error" || true

# Grant NET_ADMIN and NET_RAW to the real Python binary so Home Assistant
# (running as vscode, not root) can open the Bluetooth management socket.
# Docker's capAdd only grants capabilities to root; setcap propagates them
# to non-root processes that exec the binary directly.
# The venv uses symlinks; resolve to the actual executable for setcap.
_py="$(readlink -f "$HOME/ha-venv/bin/python3" 2>/dev/null)"
if [[ -f "$_py" ]] && ! getcap "$_py" 2>/dev/null | grep -q "net_admin"; then
    echo "ℹ Granting cap_net_admin+cap_net_raw to $_py for HA Bluetooth management"
    sudo setcap 'cap_net_admin,cap_net_raw+eip' "$_py"
fi
unset _py
