# Hilo Band (Aktiia bracelet) — BLE protocol

Reverse-engineered from the official Android app `com.aktiia.android.production`
**v2.12.1 (versionCode 605)**, decompiled with jadx + apktool.

Primary sources inside the APK:

| Class | What it gave us |
|---|---|
| `com.aktiia.ble.pod.PodBleCharacteristicKt` | all service/characteristic UUIDs, control-point opcodes |
| `com.aktiia.ble.pod.PodBleImpl` | connect/pair/sync state machine, value parsing |
| `com.aktiia.ble.pod.BleControlPoint` | CCCD handling, control-point write/notify |
| `com.aktiia.ble.pod.PodTimestampPacketsKt` | time packet layout |
| `com.aktiia.ble.pod.PodQi` | calibration quality enum |
| `com.aktiia.ble.pod.PodConstantsKt` | timeouts |
| `com.aktiia.domain.constants.Constants$BLE` | advertising name prefixes |
| `com.aktiia.domain.ble.*` | `BleNotification`, `BleCharacteristic`, `BleFailureReason` enums |
| `com.aktiia.data.net.AktiiaApi` | cloud REST surface |

> Note: jadx fails on `PodBleImpl` and `CuffBleImpl` with default settings.
> Use `jadx --show-bad-code`, or read the smali from `apktool d`.

---

## 1. Advertising

| Constant | Value | Device |
|---|---|---|
| `POD_ADVERTISING_PREFIX_NORMAl_MODE` | `AKTIIA P` | **band / bracelet ("pod")** |
| `CUF_ADVERTISING_PREFIX_NORMAl_MODE` | `AKTIIA C` | cuff (out of scope) |
| `CUF_ADVERTISING_PREFIX_DFU_MODE` | `OTA_` | cuff bootloader |

`PodBleImpl.isMatchingPod()` does a **case-insensitive `startsWith`** on the
advertised local name. The app parses **no manufacturer-specific data** — the
advertisement carries the local name only. So passive scanning yields presence
and RSSI, nothing more.

Minimum cuff firmware the app accepts: `I1-1.2` (`CUF_FIRMWARE_REVISION_MIN_VERSION`).

---

## 2. GATT map

### 2.1 Standard Bluetooth SIG

| Characteristic | UUID | Access | Notes |
|---|---|---|---|
| Battery Level | `0x2A19` | read | parsed as unsigned big-endian int → 0–100 |
| Current Time | `0x2A2B` | read/write | legacy clock path |
| Manufacturer Name | `0x2A29` | read | |
| Model Number | `0x2A24` | read | |
| Serial Number | `0x2A25` | read | |
| Firmware Revision | `0x2A26` | read | app watches this for FW-change detection |
| Hardware Revision | `0x2A27` | read | |
| CCCD | `0x2902` | read/write | `01 00` to enable notifications |

Device Information Service = `0x180A`.

### 2.2 Token Authorization Service

| | UUID |
|---|---|
| Service | `3a350001-e7cc-4d7f-9683-ed4cb1001cd1` |
| Token Authorization | `3a350002-e7cc-4d7f-9683-ed4cb1001cd1` |

Used during pairing only:

* app **reads** it → the band's "secure token"
* app **writes** a hash of the username to it
* the token is then sent to the cloud: `POST device/api/v1/device/pair-pod`

It is **not** a challenge/response gate for telemetry. Battery and device-info
reads work over an ordinary bonded link without touching it.

### 2.3 Raw Data Service

| | UUID | Access |
|---|---|---|
| Service | `a6b41001-003d-4e65-9208-08f4db958863` | |
| Raw Data | `a6b41002-003d-4e65-9208-08f4db958863` | notify |
| Number of Frames | `a6b41003-003d-4e65-9208-08f4db958863` | read |
| Storage Level | `a6b41004-003d-4e65-9208-08f4db958863` | read |
| Raw Data Control Point | `a6b41005-003d-4e65-9208-08f4db958863` | write + notify |

`Storage Level` is declared in `PodBleCharacteristicKt` but **never read** by
v2.12.1 — the method `connectAndReadDeviceInfoBatteryAndStorageLevel` reads
battery only. Treat its encoding as unverified.

#### Control-point opcodes

| Opcode | Name | Effect |
|---|---|---|
| `0x00` | `OPCODE_NUMBER_OF_FRAMES` | ask for contextualisation frame count |
| `0x01` | `OPCODE_CONTEXTUALISATION_RAW_DATA` | start streaming ctx raw data |
| `0x07` | `OPCODE_DELETE_CONTEXTUALISATION_RAW_DATA` | **erase stored frames** |

> ⚠️ `0x01` and `0x07` are destructive in effect: the app only sends `0x07`
> after the Aktiia cloud has acknowledged persistence
> (`confirmRawDataPersisted(type, persisted=true)`). Anything else sending them
> makes measurements unrecoverable.

### 2.4 HBS Service (utils control point)

| | UUID |
|---|---|
| Service | `a6b41010-003d-4e65-9208-08f4db958863` |
| Utils Control Point | `a6b41030-003d-4e65-9208-08f4db958863` |

`PodBleImpl.isHbsAvailable()` checks for this service to decide whether to set
the clock via UCP instead of the legacy Current Time characteristic.

| Opcode | Meaning |
|---|---|
| `02 00` | set current time (followed by the 9-byte time payload) |
| `02 01` | get current time |

### 2.5 Calibration ("initialization")

| | UUID | Access |
|---|---|---|
| Calibration 1 | `dd890004-bce5-4d8a-8af8-9b2125d125a5` | notify |
| Calibration 2 | `dd890005-bce5-4d8a-8af8-9b2125d125a5` | notify |

Driven by `triggerInitializationFirstPart()` / `triggerInitializationSecondPart()`.
Note the different UUID base — this is a separate vendor block from `a6b4xxxx`.

---

## 3. Payload formats

### 3.1 Time packet — `PodTimestampPacketsKt`

Nine bytes, matching the BLE Current Time layout:

```
year   uint16 little-endian
month  uint8   (1-12)
day    uint8   (1-31)
hour   uint8   (0-23)
minute uint8   (0-59)
second uint8   (0-59)
dow    uint8   (1 = Monday .. 7 = Sunday, Joda getDayOfWeek)
```

* via UCP: `02 00` ++ `<9 bytes>`
* via CTS characteristic: `<9 bytes>` ++ `00 02`
  (`fractions256 = 0`, `adjustReason = 2` → "external reference time update")

The app always builds this in **UTC** (`DateTime().withZone(DateTimeZone.UTC)`).

### 3.2 Battery level / frame count

Both are parsed as `Integer.parseInt(byteArrayToHex(bytes), 16)` — i.e. an
unsigned **big-endian** integer over however many bytes arrive.

### 3.3 Contextualisation frame count

`handleContextualisationFrameCount()` **drops the first byte** (the echoed
opcode) and parses the remainder as an unsigned big-endian integer.

### 3.4 Raw data stream

* Contextualisation notifications are prefixed with opcode byte `0x02`.
* The end of a measurement stream is marked by `MEASUREMENT_END_COMMAND` =
  `93ce580dde`.
* Frames are written verbatim to a temp file and uploaded to the cloud; the app
  never interprets them.

---

## 4. Enums

### `PodQi` — calibration quality

| Value | Name |
|---|---|
| 0 | `NO_CALIBRATION_DONE` |
| 1 | `CALIBRATION_IN_PROGRESS` |
| 2 | `CALIBRATION_DONE` |
| 3 | `ERROR` |
| 4 | `MOVEMENT_DETECTED` |
| 5 | `BAD_PPG_QUALITY` |

### `BleNotification`

`HAS_BP_DATA`, `HAS_CTX_DATA`, `NO_BP_DATA`, `NO_CTX_DATA`

### `BleCharacteristic`

`CALIB_1`, `CALIB_2`, `CONTROL_POINT`, `CUFF_MEASUREMENT`, `CUFF_STATUS`,
`RAW_DATA`, `READ_DEVICE_INFO`

### `BleFailureReason`

`BONDING_TIMEOUT`, `CHARACTERISTIC_NOT_AVAILABLE`, `CONNECTION_FAILURE`,
`CUFF_1_3_ERROR`, `CUFF_ERROR`, `CUFF_IS_IN_DFU`, `CUFF_MEASUREMENT_ERROR`,
`CUFF_MOVE_ERROR`, `FW_UPDATE_ERROR`, `NO_DATA`, `PAIRING_FAILURE`,
`POD_BONDED_ELSEWHERE`, `POD_CALIBRATION_IN_PROGRESS`, `POD_MEASUREMENT_ERROR`,
`POD_QI_BAD_PPG`, `POD_QI_ERROR`, `POD_QI_MOVEMENT`, `SCAN_FAILURE`,
`SYNC_ERROR`, `TIMEOUT`, `UNDOCUMENTED_SCAN_THROTTLE`

`POD_BONDED_ELSEWHERE` is the one you hit when a second central (e.g. Home
Assistant) tries to use a band already bonded to a phone.

---

## 5. Timings and status codes

From `PodBleImpl` / `PodConstantsKt`:

| Constant | Value |
|---|---|
| `SCAN_TIMEOUT_SECONDS` | 8 |
| `SYNC_CONNECT_TIMEOUT_SECONDS` | 5 |
| `PAIR_CONNECT_TIMEOUT_SECONDS` | 10 |
| `BONDING_TIMEOUT_SECONDS` | 30 |
| `GATT_CONN_RETRY_DELAY_MS` | 2000 |
| `MAX_RECONNECT_ATTEMPTS` | 5 |
| `PERSIST_ACK_TIMEOUT_MS` | 10000 |
| `AFTER_FW_UPDATE_DELAY_FOR_RECONNECTION` | 5000 |
| `FIRST/SECOND_PHASE_INITIALIZATION_TIME_OUT` | 40 |

GATT/ATT status codes the app special-cases:

| Code | Meaning |
|---|---|
| 5 | insufficient authentication |
| 15 | insufficient encryption |
| 133 | generic GATT error |
| 137 | auth fail |
| 128 | app error: unknown opcode |
| 132 | app error: busy |

5 / 15 / 137 all mean "bonded to a different central".

---

## 6. Sync state machine

```
scan (name startsWith "AKTIIA P")
  → connect
  → discoverServices
  → readTokenAuthorization        (pairing only)
  → readDeviceInfo                (DIS, ensureBonded)
  → readBatteryLevel              (0x2A19)
  → writeTimestamp                (UCP 02 00, else CTS 0x2A2B)
  → readNumberOfFrames            (a6b41003)
        > 0 → BleNotification.HAS_BP_DATA
              → readInitializationRawData  (notify a6b41002)
              → upload to cloud
              → await PERSIST_ACK from cloud
              → control point 0x07  (erase)
        = 0 → readNumberOfFramesContextualisation
              → control point 0x00 → frame count
              → control point 0x01 → stream ctx data
              → upload, ack, 0x07
  → finishSync
```

**Bonding is required.** `ensureBonded()` waits up to 30 s for
`BOND_BONDED`; encrypted characteristics fail until it completes.

---

## 7. Where blood pressure actually comes from

The band has **no blood-pressure characteristic**. It stores raw PPG /
accelerometer frames and hands them to the phone, which uploads them to Aktiia's
cloud. Blood pressure is computed server-side and read back over REST.

Base URL (production EU): `https://prod001-eu.aktiia.io/`
OAuth2 password grant, client credentials in `ApiConstantKt.BASIC_AUTHORIZATION`.

Relevant endpoints (from `com.aktiia.data.net.AktiiaApi`):

| Endpoint | Purpose |
|---|---|
| `POST oauth/api/v1/token` | login / refresh |
| `GET physiological/api/v2/measurements/latest` | latest BP |
| `GET physiological/api/v2/all-measurements` | full history |
| `GET /physiological/api/v2/daily` · `monthly` · `day-night` | aggregates |
| `GET /physiological/api/v2/ttr` · `daily/ttr` · `monthly/ttr` | time-in-target-range |
| `GET physiological/api/v2/cuff` · `POST` | cuff measurements |
| `GET /context-data/api/v1/insights/sleep` · `insights/steps` | sleep / steps |
| `GET /context-data/api/v1/daily-summary/sleep` | sleep summary |
| `POST initialization/api/v2/initialization` | calibration |
| `POST initialization/api/v2/quality` | calibration quality |
| `GET /physiological/api/v2/initializations` · `v1/latest-initialization` | calibration state |
| `POST device/api/v1/device/pair-pod` · `DELETE unpair-pod` | pair the band |
| `GET device/api/v2/device/check-pod` | verify band |
| `POST device/api/v1/device/generate-url` | S3 upload URL for raw frames |
| `GET /device/api/v1/firmware/pod/{firmwareVersion}` | OTA firmware |

Custom headers: `Version-Code`, `Platform`, `Time-Zone`, `X-Device-Id`,
`X-Device-Model`, `X-Device-Os`, `X-Correlation-Id`, `X-Product`.
Server error 406 = `BRACELET_BLOCKED`, 426 = `UPGRADE_REQUIRED`.

---

## 8. Calibration

Calibration ("initialization") needs **all three**: the app, the Hilo cuff, and
the cloud.

1. App tells the band to start: `triggerInitializationFirstPart()`, subscribing
   to `CALIBRATION_1` (`dd890004`).
2. Band reports progress via `PodQi` (see enum above); the app surfaces
   `POD_QI_MOVEMENT` / `POD_QI_BAD_PPG` / `POD_QI_ERROR` failures.
3. Simultaneous cuff reading is taken over the cuff's own BLE service.
4. Second phase: `triggerInitializationSecondPart()` on `CALIBRATION_2`
   (`dd890005`).
5. Results are posted to `initialization/api/v2/initialization` and
   `initialization/api/v2/quality`; the cloud decides whether calibration
   succeeded.

There is no local-only calibration path — the cloud produces the calibration
coefficients. Keep using the official Hilo app for this.
