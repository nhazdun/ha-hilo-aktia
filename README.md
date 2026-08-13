# Hilo Band (Aktiia) — Home Assistant integration

Local Bluetooth LE integration for the **Hilo Band** (Aktiia bracelet, the
device that advertises as `AKTIIA P…`). The Hilo **cuff** is a different device
and is deliberately not handled here.

The BLE protocol was reverse-engineered from the official Android app
`com.aktiia.android.production` v2.12.1 — see [`docs/PROTOCOL.md`](docs/PROTOCOL.md)
for the full map of services, characteristics, opcodes and payload formats.

---

## ⚠️ Read this first: no blood pressure over Bluetooth

**The band does not expose blood pressure over BLE.** There is no BP
characteristic in its GATT table.

The band stores raw PPG/accelerometer frames. The phone app pulls those frames
and uploads them to Aktiia's cloud, which computes blood pressure and hands it
back over REST. The algorithm is entirely server-side.

So a local-only integration can give you:

| ✅ Available locally | ❌ Not available locally |
|---|---|
| presence / in-range | blood pressure |
| signal strength (RSSI) | heart rate |
| battery level | sleep, steps |
| pending frame count | time in target range |
| storage level | calibration state |
| firmware / hardware / serial / model | |
| band clock | |

If you want blood pressure in Home Assistant, it has to come from Aktiia's
cloud API (documented in [`docs/PROTOCOL.md`](docs/PROTOCOL.md) §7), not from
this integration.

---

## Two modes

### Passive (default, recommended)

Listens for the band's advertisements. **Never connects**, so it cannot
interfere with your phone's link to the band and can never touch stored data.

Gives you: `In range`, `Signal strength`, `Last seen`.

### Active (opt-in)

Additionally connects on a slow interval (default: 1 hour) and reads battery,
frame count, storage level, device info and the band clock.

**Active mode usually will not work while the band is bonded to your phone.**
The band bonds with exactly one central. When Home Assistant is not that
central, encrypted reads fail with an authentication error — the integration
detects this, logs it once, and keeps serving passive data.

Active mode is realistically useful only if the band is **not** paired to a
phone (e.g. a spare band, or one you have unpaired).

---

## Safety

This integration is **read-only by construction**. It never writes to the band.

That matters because the raw-data control point (`a6b41005`) has opcodes `0x01`
(stream) and `0x07` (erase). The official app only sends `0x07` after Aktiia's
cloud confirms the frames were stored. If Home Assistant sent those opcodes, it
would pull measurements off the band and erase them — and since only the cloud
can turn raw frames into blood pressure, those measurements would be gone for
good. `const.py` marks them `DESTRUCTIVE_OPCODES` and nothing in the code path
writes them.

---

## Requirements

* Home Assistant 2024.12 or newer (developed against 2026.7)
* A Bluetooth adapter or an ESPHome Bluetooth proxy in range of the band

> **ESPHome proxies:** advertisement monitoring (passive mode) works fine.
> Active mode needs `active: true` on the proxy and a free connection slot, and
> even then ESP32 proxies do not support BLE bonding — so encrypted reads on a
> phone-bonded band will still fail. Passive mode is the realistic option with
> proxies.

## Install

### HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**
2. Repository: `https://github.com/nhazdun/ha-hilo-aktia`, type **Integration**
3. Install **Hilo Band (Aktiia)**, then restart Home Assistant

### Manual

Copy `custom_components/hilo_band` into your `config/custom_components/`
directory and restart Home Assistant.

## Configure

The band is auto-discovered when it advertises — look for a **Hilo Band**
discovery card under Settings → Devices & Services. You can also add it
manually with **Add Integration → Hilo Band (Aktiia)**.

If nothing is found, the band is not advertising. It advertises when it is
awake and not already connected to a phone; try moving it near a proxy, or
briefly turning off Bluetooth on your phone.

Mode and the active-read interval can be changed later under the integration's
**Configure** button.

## Entities

| Entity | Mode | Notes |
|---|---|---|
| `binary_sensor.*_in_range` | passive | on while the band advertised in the last 5 min |
| `sensor.*_signal_strength` | passive | RSSI, disabled by default |
| `sensor.*_last_seen` | passive | timestamp of last advertisement |
| `sensor.*_battery` | active | 0–100 % |
| `sensor.*_frames_pending_upload` | active | raw frames waiting to sync to the phone |
| `sensor.*_storage_used` | active | encoding unverified — see PROTOCOL.md §2.3 |
| `sensor.*_band_clock` | active | disabled by default |
| `sensor.*_last_successful_read` | active | disabled by default |

Firmware, hardware, serial and model land on the **device** record rather than
as separate entities.

## Calibration

Calibration ("initialization") is not implemented here, and does not need to be:
keep doing it in the official Hilo app. It requires the app, the Hilo cuff and
Aktiia's cloud together — the cloud is what produces the calibration
coefficients, so there is no local-only path. Protocol details are in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md) §8.

## Licence

MIT. Not affiliated with, endorsed by, or supported by Aktiia SA / Hilo.
This is not a medical device; do not use it for clinical decisions.
