# Introduction

This is a basic server for the Mictrack MT710 GPS tracker. It receives the
device's UDP reports, parses them, and publishes the data to MQTT for Home
Assistant.

For more information on the MT710 tracker see:

    https://shop.mictrack.com/product/catm1-nbiot-gps-tracker-mt710/

The protocol and user manual PDFs are in `docs/`.

# Components

- `config.py` — one-off tool to configure the MT710 (APN, server IP/port, mode)
  over the serial port. Settings come from `config.yaml` (see
  `config.yaml.template`).
- `tracker.py` — the UDP server. Listens on port `7700`, parses each report and
  publishes to MQTT.

# What the server handles

The parser is driven by what the device actually sends in practice (captured
from real traffic), not by the full protocol spec. Two report types are
handled:

- **GPS reports** (`$GPRMC`) — latitude/longitude, speed, course, UTC time and
  date, status (`A` valid / `V` invalid / `L` last-known). Only a valid (`A`)
  fix is published as a position.
- **WiFi reports** (`$WIFI`) — these carry **no** latitude/longitude, so the
  server does **not** fabricate a position. Instead it exposes what the report
  genuinely contains: battery, status, the nearby access-point list
  (`RSSI`/`MAC` pairs, strongest first), the strongest RSSI, and the device
  timestamp. WiFi reports with an empty UTC time and/or empty date are tolerated
  (the device does send these).

Both report types carry the **Report Event Status** (e.g. `TOWED`, `HT`,
`AUTO`, `PLUG`, `UNPLUG`, `FULL`) and the backup battery voltage.

## Charging (plug/unplug)

The `PLUG` / `FULL` / `UNPLUG` event statuses are mapped to a charging state and
exposed as a Home Assistant **binary sensor** (`device_class: battery_charging`):

- `PLUG` or `FULL` → `ON` (charging)
- `UNPLUG` → `OFF` (not charging)
- any other event (`TOWED`, `HT`, `AUTO`, ...) → charging state left unchanged

# Home Assistant MQTT Discovery

On the first report received, the server publishes
[MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery)
config for each entity. All entities share one `device` block (so they group
under a single "Belle Tracker" device in Home Assistant) and each has a stable
`unique_id`. Discovery configs are published with `retain` set.

Entities created:

| Entity | Component | Topic (state) |
|---|---|---|
| Device tracker | `device_tracker` | `belletracker/attributes` (JSON) |
| Charging | `binary_sensor` (`battery_charging`) | `belletracker/charging` |
| Battery | `sensor` (`battery`, %) | `belletracker/batteryPercent` |
| Battery voltage | `sensor` (`voltage`, V) | `belletracker/batteryVoltage` |
| Speed | `sensor` (`speed`, mph) | `belletracker/speedmph` |
| Course | `sensor` (°) | `belletracker/course` |
| Report event | `sensor` | `belletracker/reportEventStatus` |
| WiFi RSSI | `sensor` (`signal_strength`, dBm) | `belletracker/rssi` |

Battery percentage is scaled from voltage (3.59 V = 0 %, 4.19 V = 100 %).

# Setup

Configure the tracker (serial) using `config.py` and `config.yaml`, then run the
server:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python tracker.py
```

> Note: `venv_config/` in this repo was created for a different project and is
> not used here. Create a fresh `venv` as above (both are gitignored).

# Tests

`parse_line` and the discovery/helper functions are covered by a pytest suite
built from real observed payloads (GPS, single/multi-AP WiFi, empty time/date,
plug/unplug):

```bash
./venv/bin/python -m pytest tests/ -q
```
