# Hilo Band (Aktiia) — Home Assistant integration

Brings your **Hilo Band** (Aktiia bracelet) data into Home Assistant: blood
pressure, heart rate, time in target range, sleep, steps and calibration
status — plus optional Bluetooth presence.

Both the cloud API and the BLE protocol were reverse-engineered from the
official Android app `com.aktiia.android.production` v2.12.1. The full map is in
[`docs/PROTOCOL.md`](docs/PROTOCOL.md).

---

## Why this talks to the cloud, not the band

The band has **no blood-pressure characteristic over Bluetooth**. It stores raw
PPG/accelerometer frames; the phone app uploads them to Aktiia's cloud, which
runs the algorithm and returns the actual numbers. Blood pressure simply does
not exist on the device.

So this integration signs in to your Hilo account and reads the same API the
app does. Bluetooth is still used, but only for one thing it is genuinely good
at: telling you whether the band is physically nearby.

| Source | Gives you |
|---|---|
| Aktiia cloud | blood pressure, heart rate, daily averages, time in range, sleep, steps, calibration, firmware/serial |
| Bluetooth (optional, passive) | in-range presence, signal strength |

## Entities

| Entity | Notes |
|---|---|
| `sensor.*_systolic` / `sensor.*_diastolic` | latest measurement, mmHg |
| `sensor.*_heart_rate` | latest measurement, bpm |
| `sensor.*_last_measurement` | when it was taken |
| `sensor.*_average_systolic_today` / `_diastolic` / `_heart_rate` | today's averages |
| `sensor.*_measurements_today` | how many measurements today |
| `sensor.*_time_in_optimal_range` | % of time in range (normal/elevated/high disabled by default) |
| `sensor.*_sleep_duration`, `sensor.*_time_asleep` | last night |
| `sensor.*_steps_today`, `sensor.*_average_daily_steps` | steps |
| `sensor.*_last_calibration` | when the band was last calibrated |
| `binary_sensor.*_calibrated` | on when a full calibration exists |
| `binary_sensor.*_in_range` | Bluetooth presence (optional) |
| `sensor.*_signal_strength` | RSSI, disabled by default |

Some are disabled by default to keep the device page readable — enable them in
the entity settings.

## Install

### HACS

1. HACS → three-dot menu → **Custom repositories**
2. Repository `https://github.com/nhazdun/ha-hilo-aktia`, type **Integration**
3. Install **Hilo Band (Aktiia)**, restart Home Assistant

### Manual

Copy `custom_components/hilo_band` into `config/custom_components/` and restart.

## Configure

**Settings → Devices & Services → Add Integration → Hilo Band (Aktiia)**, then
sign in with the same email and password you use in the Hilo app.

Home Assistant stores the resulting tokens, not your password. When the session
eventually expires you will get a normal re-authentication prompt.

Options (the **Configure** button) let you set the poll interval and turn
Bluetooth presence off. The default interval is 30 minutes — the band only
syncs to your phone a few times a day, so polling faster does not give you
fresher numbers.

Bluetooth presence needs no setup: the cloud reports the band's MAC address, so
if Home Assistant can see it (a local adapter or an ESPHome Bluetooth proxy) the
presence sensors attach to the same device automatically.

## History and long-term statistics

Measurements arrive with timestamps in the past — on a first sync, potentially
months of them. Sensor states cannot express that, because the recorder
timestamps a state when it *sees* it. So history is written as **external
statistics** instead, which is Home Assistant's supported way to backfill a
series from an outside source.

Three streams are imported, bucketed hourly with mean/min/max:

* `hilo_band:<serial>_systolic`
* `hilo_band:<serial>_diastolic`
* `hilo_band:<serial>_heart_rate`

Add them to a dashboard with a **Statistics graph** card, or browse them under
Developer tools → Statistics.

The first import runs in the background right after setup and reaches back to
your first-ever measurement (or a year, if the account does not report one).
Every later poll resumes from the last written hour, so routine updates are
cheap.

To re-import manually — for example after a long outage, or to rebuild
everything from scratch:

```yaml
action: hilo_band.import_history
data:
  full: true
```

Leave `full` off (or `false`) to just top up from where it left off.

These statistics are deliberately separate from the live sensors' own
statistics, so the backfill and the recorder never fight over the same
statistic id.

## Safety and privacy

* **Read-only.** After signing in, the integration only issues GET requests. It
  never writes to your Hilo account and never touches the band over Bluetooth.
* **Bluetooth is passive.** It listens for advertisements and never connects,
  so it cannot interfere with the Hilo app on your phone. This matters: the
  band's raw-data control point has opcodes that hand over and then *erase*
  stored measurements, and only Aktiia's cloud can turn those raw frames into
  blood pressure. Those opcodes are marked `DESTRUCTIVE_OPCODES` in `const.py`
  and are never written.
* Diagnostics output redacts tokens, device id, MAC and serial number.

## Calibration

Calibration ("initialization") is not implemented here and does not need to be —
keep doing it in the official Hilo app. It needs the app, the Hilo cuff and
Aktiia's cloud together, because the cloud is what produces the calibration
coefficients. This integration just reports *when* it last happened and whether
it completed. Details in [`docs/PROTOCOL.md`](docs/PROTOCOL.md) §8.

## Upgrading from 0.1.x

0.1.x was Bluetooth-only and could not report blood pressure. Its config entries
are not migratable — remove the old **Hilo Band** entry and add the integration
again with your Hilo account.

## Licence

MIT. Not affiliated with, endorsed by, or supported by Aktiia SA / Hilo.
This is not a medical device; do not use it for clinical decisions.
