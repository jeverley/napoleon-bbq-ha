"""Constants for napoleon_home."""

from logging import Logger, getLogger
from typing import NamedTuple

LOGGER: Logger = getLogger(__package__)

# Integration metadata
DOMAIN = "napoleon_home"
MANUFACTURER = "Napoleon"
ATTRIBUTION = "Data provided by Napoleon Home"

# entry.data key for the per-device dict (keyed by mac.lower())
CONF_DEVICES = "devices"

# Platform parallel updates - applied to all platforms
PARALLEL_UPDATES = 1

# BLE characteristic UUIDs
INBOX_UUID = "01000001-fe28-435b-991a-f1b21bb9bcd0"
OUTBOX_UUID = "01000002-fe28-435b-991a-f1b21bb9bcd0"
DSN_UUID = "00000001-fe28-435b-991a-f1b21bb9bcd0"  # Ayla config service — requires encryption (bond first)
DISPLAY_NAME_UUID = (
    "00000006-fe28-435b-991a-f1b21bb9bcd0"  # User-configurable alias (read/write via app) — requires encryption
)
GATT_DEVICE_NAME_UUID = (
    "00002a00-0000-1000-8000-00805f9b34fb"  # Generic Access Device Name (0x2A00) — model string, e.g. "Prestige-1F2"
)

# Auth
AUTH_USER = "android.user@email.com"
BLE_AUTH_STATUS_REJECTED = 4  # s:4 on oac t:2 — wrong HMAC / rotated key
BLE_AUTH_STATUS_NOT_PROVISIONED = 6  # s:6 on oac t:1 — grill not provisioned via Napoleon app

# Custom config entry keys (use CONF_REGION from homeassistant.const for region)
CONF_LOCAL_KEY = "local_key"
CONF_LOCAL_KEY_ID = "local_key_id"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_EXPIRY = "token_expiry"
CONF_MAC = "mac_address"
CONF_DSN = "dsn"

# Timings (seconds)
AUTH_TIMEOUT = 15
MAX_CONNECT_FAILURES = 5
POLL_INTERVAL_S = 30

# Ayla property type codes
PROP_TYPE_INT = 0
PROP_TYPE_DECIMAL = 1
PROP_TYPE_BOOL = 3
PROP_TYPE_STRING = 4

# Property names
PROP_TUNIT = "TUNIT"
PROP_BSMODE = "BSMODE"
PROP_LCD_OFF = "LCD_OFF"
PROP_BRT_LVL = "BRT_LVL"
PROP_AUTO_T_OUT = "AUTO_T_OUT"
PROP_TOFF = "TOFF"
PROP_GS_UNT = "GS_UNT"
PROP_REGN = "REGN"
PROP_CNTRY = "CNTRY"
PROP_GS_TNK_NAME = "GS_TNK_NAME"
PROP_EMTY_TNK_W = "EMTY_TNK_W"
PROP_F_TNKWT = "F_TNKWT"
PROP_BT_LVL = "BT_LVL"
PROP_BATTERY_LOW_ALERT = "battery_low_alert"
PROP_TNK_WT = "TNK_WT"
PROP_NTC_VLU = "NTC_VLU"
PROP_PRB_STAT = "PRB_STAT"
PROP_VERSION = "version"

PROP_PRB_TEMPS: list[str] = ["PRB_TMP_ONE", "PRB_TMP_TWO", "PRB_TMP_THREE", "PRB_TMP_FOUR"]
PROP_TGT_TEMPS: list[str] = ["TRGT_TMP_ONE", "TRGT_TMP_TWO", "TRGT_TMP_THREE", "TRGT_TMP_FOUR"]

# Properties polled on every Gpr cycle
POLL_PROPS: list[str] = [
    PROP_TUNIT,
    PROP_BSMODE,
    PROP_LCD_OFF,
    PROP_BRT_LVL,
    PROP_AUTO_T_OUT,
    PROP_GS_UNT,
    PROP_REGN,
    PROP_CNTRY,
    PROP_GS_TNK_NAME,
    PROP_EMTY_TNK_W,
    PROP_F_TNKWT,
    PROP_PRB_STAT,
    PROP_BT_LVL,
    PROP_BATTERY_LOW_ALERT,
    PROP_TNK_WT,
    PROP_VERSION,
    *PROP_PRB_TEMPS,
    *PROP_TGT_TEMPS,
]

# Probe temperature sentinel — value returned when probe is not connected
PROBE_DISCONNECTED = 4095.0

# Napoleon/Ayla BLE device name prefixes from AppConstants.java.
# Unprovisioned grills advertise with a local name starting with one of these.
# Any FE28 advertisement WITH a local name that doesn't match is a non-Napoleon
# Ayla device sharing the service UUID.
NAPOLEON_NAME_PREFIXES: tuple[str, ...] = (
    "Prestige",
    "ProVX",
    "Pro",
    "AWS",
    "R365EQ",
    "Elevation",
    "Stylus",
    "Astound",
    "Luminex",
    "Rosedale",
    "Thermostat",
    "ACCU-PROBE",
    "ACCU-PRO",
    "MeatStick",
    "S25",
)

# Ayla cloud region identifiers
AYLA_REGION_EU = "eu"
AYLA_REGION_US = "us"
AYLA_DEFAULT_REGION = AYLA_REGION_EU

# Ayla OEM model identifiers for Napoleon Prestige grills (from APK decompile)
AYLA_OEM_MODEL_PRESTIGE_EU = "thermometer-mqtt-eu"
AYLA_OEM_MODEL_PRESTIGE = "thermometer-mqtt-us"


class _AylaRegion(NamedTuple):
    """Ayla cloud API endpoints and Napoleon application credentials for a region.

    These application credentials are embedded in the Napoleon mobile app APK
    and identify Napoleon's tenant in the Ayla IoT cloud per region. They are
    not user credentials — each user authenticates separately with their own
    email and password.

    Attributes:
        user_host: Hostname for the Ayla user auth API (sign-in).
        device_host: Hostname for the Ayla device API (device list, connection config).
        app_id: Napoleon application ID registered with Ayla for this region.
        app_secret: Napoleon application secret registered with Ayla for this region.
        prestige_oem_model: Ayla OEM model string used to filter Napoleon Prestige grills.

    """

    user_host: str
    device_host: str
    app_id: str
    app_secret: str
    prestige_oem_model: str


# Ayla cloud regions — used once at setup time to fetch the device localKey
AYLA_REGIONS: dict[str, _AylaRegion] = {
    AYLA_REGION_EU: _AylaRegion(
        user_host="user-field-eu.aylanetworks.com",
        device_host="ads-eu.aylanetworks.com",
        app_id="smarthome_eu-rA-hQ-id-5Q-id",
        app_secret="smarthome_eu-rA-hQ-id-gHzZGo5048znNn0F9nuyc_PSyBw",
        prestige_oem_model=AYLA_OEM_MODEL_PRESTIGE_EU,
    ),
    AYLA_REGION_US: _AylaRegion(
        user_host="user-field.aylanetworks.com",
        device_host="ads-field.aylanetworks.com",
        app_id="smarthome_dev-rA-hQ-id",
        app_secret="smarthome_dev-BBeF7xY8xfKBfNcFIx-rhQhA2YY-h64jEJ5ZhCy9GOaWiy0XkbnGc1g",
        prestige_oem_model=AYLA_OEM_MODEL_PRESTIGE,
    ),
}
