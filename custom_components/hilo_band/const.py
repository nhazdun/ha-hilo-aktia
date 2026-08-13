"""Constants and BLE protocol map for the Hilo Band (Aktiia bracelet / "pod").

Everything in this module was reverse-engineered from the official Android app
``com.aktiia.android.production`` v2.12.1 (versionCode 605), primarily from:

  * ``com.aktiia.ble.pod.PodBleCharacteristicKt``  - service/characteristic UUIDs
  * ``com.aktiia.ble.pod.PodBleImpl``              - connection + read/sync flow
  * ``com.aktiia.ble.pod.BleControlPoint``         - control-point notify/write
  * ``com.aktiia.ble.pod.PodTimestampPacketsKt``   - time packet layout
  * ``com.aktiia.ble.pod.PodQi``                   - calibration quality enum
  * ``com.aktiia.domain.constants.Constants$BLE``  - advertising name prefixes

The band is a *raw data* device: it streams PPG/accelerometer frames which the
phone uploads to Aktiia's cloud, where blood pressure is actually computed.
There is no blood-pressure characteristic on the device. See README.md.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hilo_band"
MANUFACTURER: Final = "Aktiia SA"
MODEL: Final = "Hilo Band"

# --------------------------------------------------------------------------
# Advertising
# --------------------------------------------------------------------------
# Constants$BLE.POD_ADVERTISING_PREFIX_NORMAl_MODE (sic - typo is in the app)
POD_ADV_PREFIX: Final = "AKTIIA P"
# Constants$BLE.CUF_ADVERTISING_PREFIX_NORMAl_MODE - the cuff, NOT handled here
CUFF_ADV_PREFIX: Final = "AKTIIA C"
# Constants$BLE.CUF_ADVERTISING_PREFIX_DFU_MODE - bootloader / OTA mode
DFU_ADV_PREFIX: Final = "OTA_"

# The app matches with startsWith(name, prefix, ignoreCase = true).
# No manufacturer-specific advertising payload is parsed by the app: the
# advertisement carries only the local name, so passive mode yields
# presence + RSSI only.

# --------------------------------------------------------------------------
# Standard Bluetooth SIG services / characteristics used by the band
# --------------------------------------------------------------------------
DEVICE_INFORMATION_SERVICE: Final = "0000180a-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE: Final = "0000180f-0000-1000-8000-00805f9b34fb"
CURRENT_TIME_SERVICE: Final = "00001805-0000-1000-8000-00805f9b34fb"

CHAR_MANUFACTURER_NAME: Final = "00002a29-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER: Final = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_SERIAL_NUMBER: Final = "00002a25-0000-1000-8000-00805f9b34fb"
CHAR_FIRMWARE_REVISION: Final = "00002a26-0000-1000-8000-00805f9b34fb"
CHAR_HARDWARE_REVISION: Final = "00002a27-0000-1000-8000-00805f9b34fb"
CHAR_BATTERY_LEVEL: Final = "00002a19-0000-1000-8000-00805f9b34fb"
CHAR_CURRENT_TIME: Final = "00002a2b-0000-1000-8000-00805f9b34fb"

CCCD_UUID: Final = "00002902-0000-1000-8000-00805f9b34fb"

# --------------------------------------------------------------------------
# Aktiia proprietary services
# --------------------------------------------------------------------------

# Token authorization. The app *reads* this characteristic to obtain the
# band's "secure token", which it then presents to the Aktiia cloud when
# pairing (POST device/api/v1/device/pair-pod). It also writes a hash of the
# username to it during pairing. This is NOT a challenge/response gate for
# reading telemetry - battery/device-info reads work over a normal bonded
# link without touching it.
TOKEN_AUTHORIZATION_SERVICE: Final = "3a350001-e7cc-4d7f-9683-ed4cb1001cd1"
CHAR_TOKEN_AUTHORIZATION: Final = "3a350002-e7cc-4d7f-9683-ed4cb1001cd1"

# Raw data service - the PPG/accelerometer frame pipeline.
RAW_DATA_SERVICE: Final = "a6b41001-003d-4e65-9208-08f4db958863"
CHAR_RAW_DATA: Final = "a6b41002-003d-4e65-9208-08f4db958863"  # notify
CHAR_NO_OF_FRAMES: Final = "a6b41003-003d-4e65-9208-08f4db958863"  # read
CHAR_STORAGE_LEVEL: Final = "a6b41004-003d-4e65-9208-08f4db958863"  # read
CHAR_RAW_DATA_CONTROL_POINT: Final = "a6b41005-003d-4e65-9208-08f4db958863"  # write/notify

# "HBS" service. In v2.12.1 it is used purely as the container for the utils
# control point (the app checks for its presence to decide whether it can set
# the clock via UCP instead of the legacy Current Time characteristic).
HBS_SERVICE: Final = "a6b41010-003d-4e65-9208-08f4db958863"
CHAR_UTILS_CONTROL_POINT: Final = "a6b41030-003d-4e65-9208-08f4db958863"

# Calibration ("initialization") notify characteristics. Driven by the
# official app together with the Hilo cuff and the Aktiia cloud.
CHAR_CALIBRATION_1: Final = "dd890004-bce5-4d8a-8af8-9b2125d125a5"
CHAR_CALIBRATION_2: Final = "dd890005-bce5-4d8a-8af8-9b2125d125a5"

# --------------------------------------------------------------------------
# Control point opcodes
# --------------------------------------------------------------------------

# RAW_DATA_CONTROL_POINT (a6b41005) - PodBleCharacteristicKt
OPCODE_NUMBER_OF_FRAMES: Final = 0x00  # request contextualisation frame count
OPCODE_CONTEXTUALISATION_RAW_DATA: Final = 0x01  # start ctx raw data streaming
OPCODE_DELETE_CONTEXTUALISATION_RAW_DATA: Final = 0x07  # DESTRUCTIVE - erases band data

# UTILS_CONTROL_POINT (a6b41030) - PodBleCharacteristicKt
UCP_OPCODE_SET_CURRENT_TIME: Final = bytes([0x02, 0x00])
UCP_OPCODE_GET_CURRENT_TIME: Final = bytes([0x02, 0x01])

# Marker that terminates a raw-data measurement stream.
MEASUREMENT_END_COMMAND: Final = "93ce580dde"

# Contextualisation raw-data notifications are prefixed with this opcode byte.
CTX_RAW_DATA_PREFIX: Final = 0x02

ENABLE_NOTIFICATIONS: Final = bytes([0x01, 0x00])

# --------------------------------------------------------------------------
# Opcodes that must never be sent by this integration
# --------------------------------------------------------------------------
# Writing these makes the band hand over and then ERASE stored frames. If Home
# Assistant did that, the measurements would never reach the phone app and
# would be lost forever, because only Aktiia's cloud can turn them into blood
# pressure values.
DESTRUCTIVE_OPCODES: Final = frozenset(
    {OPCODE_CONTEXTUALISATION_RAW_DATA, OPCODE_DELETE_CONTEXTUALISATION_RAW_DATA}
)

# --------------------------------------------------------------------------
# Enums mirrored from the app
# --------------------------------------------------------------------------

# com.aktiia.ble.pod.PodQi - calibration quality indicator
POD_QI: Final = {
    0: "no_calibration_done",
    1: "calibration_in_progress",
    2: "calibration_done",
    3: "error",
    4: "movement_detected",
    5: "bad_ppg_quality",
}

# com.aktiia.domain.ble.BleNotification
BLE_NOTIFICATIONS: Final = ("HAS_BP_DATA", "HAS_CTX_DATA", "NO_BP_DATA", "NO_CTX_DATA")

# com.aktiia.domain.ble.BleCharacteristic
BLE_CHARACTERISTIC_LABELS: Final = (
    "CALIB_1",
    "CALIB_2",
    "CONTROL_POINT",
    "CUFF_MEASUREMENT",
    "CUFF_STATUS",
    "RAW_DATA",
    "READ_DEVICE_INFO",
)

# --------------------------------------------------------------------------
# Timing / GATT behaviour, mirrored from PodBleImpl + PodConstantsKt
# --------------------------------------------------------------------------
SCAN_TIMEOUT_SECONDS: Final = 8
SYNC_CONNECT_TIMEOUT_SECONDS: Final = 5
PAIR_CONNECT_TIMEOUT_SECONDS: Final = 10
BONDING_TIMEOUT_SECONDS: Final = 30
GATT_CONN_RETRY_DELAY_MS: Final = 2000
MAX_RECONNECT_ATTEMPTS: Final = 5
PERSIST_ACK_TIMEOUT_MS: Final = 10000
AFTER_FW_UPDATE_DELAY_FOR_RECONNECTION: Final = 5000
FIRST_PHASE_INITIALIZATION_TIME_OUT: Final = 40
SECOND_PHASE_INITIALIZATION_TIME_OUT: Final = 40

# GATT / ATT status codes the app treats specially
GATT_INSUFFICIENT_AUTHENTICATION: Final = 5
GATT_INSUFFICIENT_ENCRYPTION: Final = 15
GATT_ERROR: Final = 133
GATT_AUTH_FAIL: Final = 137
ATT_APP_ERROR_UNKNOWN_OPCODE: Final = 128
ATT_APP_ERROR_BUSY: Final = 132

# Status codes that mean "the band is bonded to another central" (the phone).
AUTH_ERROR_STATUSES: Final = frozenset(
    {GATT_INSUFFICIENT_AUTHENTICATION, GATT_INSUFFICIENT_ENCRYPTION, GATT_AUTH_FAIL}
)

# --------------------------------------------------------------------------
# Config-entry keys
# --------------------------------------------------------------------------
CONF_ADDRESS: Final = "address"
CONF_MODE: Final = "mode"
CONF_SCAN_INTERVAL: Final = "scan_interval"

MODE_PASSIVE: Final = "passive"
MODE_ACTIVE: Final = "active"
DEFAULT_MODE: Final = MODE_PASSIVE

# How long without an advertisement before we call the band "away".
DEFAULT_AWAY_TIMEOUT: Final = 300  # seconds
# Active-mode poll interval. Kept deliberately long: every connection attempt
# competes with the phone for the band's single peripheral link.
DEFAULT_ACTIVE_INTERVAL: Final = 3600  # seconds
MIN_ACTIVE_INTERVAL: Final = 600

# --------------------------------------------------------------------------
# Aktiia cloud (documentation only - this integration does not call it)
# --------------------------------------------------------------------------
# Blood pressure, heart rate, sleep and step data live here, not on the band.
CLOUD_BASE_URL: Final = "https://prod001-eu.aktiia.io/"
CLOUD_MEASUREMENTS_LATEST: Final = "physiological/api/v2/measurements/latest"
CLOUD_ALL_MEASUREMENTS: Final = "physiological/api/v2/all-measurements"
