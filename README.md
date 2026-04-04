# Zendure SolarFlow 800 Pro — Local Control for Home Assistant

Advanced local control for the Zendure SolarFlow 800 Pro, with extended monitoring of individual PV channels, per-battery pack diagnostics, and flash wear protection. No cloud, no MQTT, no HACS — just direct HTTP communication on your local network.

> **Based on the work by [zakazak / Utini2000](https://github.com/Utini2000/Zendure-Solarflow-Local-HomeAssistant)**
> ([original forum post](https://community.home-assistant.io/t/zendure-solarflow-800-pro-completely-local-zereo-feed-in-without-cloud-and-even-faster-no-mqtt-no-hacs-easy-mode/980110)).
> The core control logic — zero-export regulation, emergency charging, seasonal SoC management, calibration, and failsafe — is their design. This fork extends the sensor coverage, centralises the device IP, adds flash wear protection, aligns terminology with the [official zenSDK property reference](https://github.com/Zendure/zenSDK/blob/main/docs/en_properties.md), and translates all labels to English.

> [!IMPORTANT]
> **This has only been tested with the Zendure SolarFlow 800 Pro** (product ID `solarFlow800Pro`, 2 × AB2000 battery packs). The zenSDK API is shared across the SolarFlow 800, 800 Pro, and 2400 AC, so the sensors *should* work on those models too — but property availability, value ranges, and unit scaling may differ. The `packInputPower` / `outputPackPower` swap applied in the net flow sensors was verified on the 800 Pro and may not apply to other models or firmware versions. If you're running a different device, start by inspecting your raw API output (`curl -s http://YOUR_IP/properties/report | python3 -m json.tool`) and compare it against the assumptions documented in the YAML comments before enabling the control loop.

---

## What it does

The control loop runs every 5 seconds, reads the SolarFlow's state over HTTP, calculates the optimal output limit based on your Shelly 3EM grid meter, and writes it back — all locally.

### Control strategy

- **Zero-export with grid bias** — targets a small grid import (configurable, default 10 W in winter / 0 W in summer) instead of a hard zero, preventing expensive battery power from being exported during fluctuations.
- **Closed-loop without lag** — bases calculations on an internal memory of the last sent value, not on sluggish sensor feedback. Reacts within 5 seconds without oscillation.
- **Self-healing memory** — detects device reboots or drift (> 150 W divergence) and resynchronises automatically.
- **Seasonal logic** — switches SoC cutoff (winter 20 % / summer 8 %), grid bias, and saturation thresholds automatically.
- **Emergency charging & calibration** — forces AC grid charging at critical SoC or when the battery hasn't reached 100 % within a configurable number of days.
- **Bypass / conservation mode** — routes solar power directly to the house between the SoC cutoff and a configurable bypass threshold, reducing conversion losses.
- **Failsafe** — falls back to a fixed base load if the Shelly goes offline; requires valid serial number verification before every write.
- **Flash protection** — automatically sets `smartMode=1` (RAM writes) on startup to prevent wearing out the ESP32's flash from ~17 000 writes/day.

### Extended monitoring (this fork)

- **Per-panel PV power** — individual MPPT channels (`solarPower1`–`solarPower4`) with kWh energy integration.
- **Per-battery pack diagnostics** — SoC, power, state, temperature, voltage, current, max/min cell voltage, cell imbalance, heat state, and serial number for each pack.
- **Calculated sensors** — pack temperature delta, SoC delta between packs, system efficiency.
- **Device status** — WiFi signal strength, remaining charge/discharge time, fan mode & speed, AC/DC/PV/grid state, IoT connection state, error flag, pass-through state, enclosure temperature.
- **Configuration readback** — current values of AC mode, smart mode, max inverter output, AC charge limit, target SoC, min SoC, lamp state — useful for verifying that commands from HA were accepted.

All sensor comments reference the official zenSDK property name, access mode, and unit for easy cross-referencing with the [Zendure documentation](https://github.com/Zendure/zenSDK/blob/main/docs/en_properties.md).

---

## Requirements

| Component | Purpose |
|---|---|
| **Zendure SolarFlow 800 Pro** | Also compatible with Hyper 2000 and potentially Hub 2000 |
| **Shelly Pro 3EM** | Grid power measurement (import/export) |
| **Home Assistant** | Automation host |
| **Forecast.Solar** integration | Optional — enables smart emergency charge decisions based on tomorrow's forecast |

---

## File overview

| File | Description |
|---|---|
| `zendure.yaml` | Core package: helpers, REST sensor, template sensors, REST commands, control loop, state machine, logic manager, flash protection, monitoring |
| `zendure_extended.yaml` | Drop-in addon: 56 extended sensors for per-panel power, per-pack diagnostics, status flags, config readback, and calculated metrics |
| `energy_monitoring.yaml` | Shelly 3EM energy monitoring: 3-phase net import/export/consumption with daily & monthly utility meters. Configurable Shelly device ID. |

---

## Installation

### 1. Prepare the SolarFlow

- Connect the SolarFlow to your WiFi network. You can use the Zendure app, or — if you want a fully account-free setup — use **[Solarflow Web Bluetooth Manager](https://arselzer.github.io/solarflow-bluetooth/)** ([source](https://github.com/arselzer/solarflow-bluetooth)) to provision WiFi directly from your browser via Bluetooth, no app or Zendure account required.
- Set the Zendure to **base load mode** with **0 watts** (in the app's on-grid settings, or via BLE/HTTP).
- Set BMS minimum discharge to **5 %** and maximum charge to **100 %**.
- **Block the SolarFlow's internet access** (e.g. via router firewall). The device works fully offline once configured.
- Disable Shelly 3EM Pro cloud access.
- Note the SolarFlow's local IP address (check your router's DHCP table or use mDNS discovery).

### 2. Install the packages

Copy `zendure.yaml` and `zendure_extended.yaml` into a folder called `packages` inside your Home Assistant config directory:

```
config/
├── configuration.yaml
└── packages/
    ├── zendure.yaml
    ├── zendure_extended.yaml
    └── energy_monitoring.yaml    (optional, for Shelly 3EM)
```

### 3. Set the device IP

Open `zendure.yaml` and set the `initial` value of `input_text.zendure_device_ip` to your SolarFlow's IP address:

```yaml
input_text:
  zendure_device_ip:
    initial: "192.168.1.100"   # ← your SolarFlow IP here
```

After first startup, you can also change this from the HA UI under **Settings → Devices & Services → Helpers** without editing YAML.

### 3b. Set the Shelly device IDs

In `energy_monitoring.yaml`, set the two `input_text` helpers:

```yaml
input_text:
  shelly_3em_device_id:
    initial: "d890ewfh"        # ← your Shelly Pro 3EM device ID
  shelly_solar_entity:
    initial: "sensor.shellypmminig3_5432046f3b24_power"  # ← your solar sensor entity ID, or "none"
```

To find your Shelly 3EM device ID: go to **Settings → Devices → (your Shelly Pro 3EM) → Entities**. Your phase sensors will be named `sensor.shellypro3em_XXXXXXXX_phase_a_active_power` — the `XXXXXXXX` part is your device ID.

If you don't have a separate Shelly PM Mini for solar generation measurement, set `shelly_solar_entity` to `"none"`.

### 4. Update configuration.yaml

Add the following to your `configuration.yaml`:

```yaml
# Load packages from the packages/ folder
homeassistant:
  packages: !include_dir_named packages

# Exclude high-frequency automations from the database
recorder:
  exclude:
    entities:
      - automation.zendure_control_loop
      - automation.zendure_state_machine
      - input_number.zendure_last_sent_limit

# Exclude high-frequency automations from the logbook
logbook:
  exclude:
    entities:
      - automation.zendure_control_loop
      - automation.zendure_state_machine
```

### 5. Restart Home Assistant

After restart, the sensors will populate within 15 seconds (the polling interval). You'll see a persistent notification confirming flash protection is active if `smartMode` was previously set to 0.

---

## Exploring the API

To see every property your firmware version exposes:

```bash
curl -s http://YOUR_IP/properties/report | python3 -m json.tool
```

The response includes a `properties` object with device-level data and a `packData` array with per-battery diagnostics. The [zenSDK docs](https://github.com/Zendure/zenSDK/blob/main/docs/en_properties.md) describe each field.

To write a property:

```bash
curl -X POST http://YOUR_IP/properties/write \
  -H "Content-Type: application/json" \
  -d '{"sn": "YOUR_SERIAL", "properties": {"smartMode": 1}}'
```

---

## Unit conversions

These were verified against the actual API output and the [zenSDK property reference](https://github.com/Zendure/zenSDK/blob/main/docs/en_properties.md):

| Property | Raw example | Unit (zenSDK) | Conversion | Result |
|---|---|---|---|---|
| `hyperTmp` / `maxTemp` | 2971 | 0.1 K | `(val - 2731) / 10.0` | 24.0 °C |
| `BatVolt` | 4734 | 0.01 V | `val / 100` | 47.34 V |
| `totalVol` (pack) | 4730 | V (docs) / 0.01 V (actual) | `val / 100` | 47.30 V |
| `batcur` (pack) | 16 | A (raw ÷ 10) | `val / 10.0` | 1.6 A |
| `maxVol` / `minVol` | 315 | 0.01 V | `val / 100` | 3.15 V |
| `socSet` | 1000 | % (per-mille) | `val / 10` | 100.0 % |
| `minSoc` | 50 | % (per-mille) | `val / 10` | 5.0 % |

> **Note:** The zenSDK docs list `totalVol` with unit "V", but actual device values are clearly on a 0.01 V scale (4730 → 47.30 V, consistent with `BatVolt`). This appears to be a documentation error.

---

## Changes from the original

Compared to [Utini2000/Zendure-Solarflow-Local-HomeAssistant](https://github.com/Utini2000/Zendure-Solarflow-Local-HomeAssistant) (forum version V11.8):

| Change | Detail |
|---|---|
| **Centralised IP** | Single `input_text.zendure_device_ip` helper replaces hardcoded IPs. Editable from the HA UI. |
| **Modern REST integration** | Switched from `sensor: platform: rest` to the `rest:` integration with `resource_template` to support the templated IP. |
| **`packData` attribute** | Added to `json_attributes` so per-battery sensors can read pack-level diagnostics. |
| **Flash protection** | New automation sets `smartMode=1` (RAM writes) on startup, preventing ~17 000 flash writes/day from the 5-second control loop. |
| **Generic REST command** | Added `zendure_set_property` for arbitrary property writes. |
| **56 extended sensors** | Per-panel PV power (4 channels), per-pack diagnostics (2 packs), status flags, config readback, calculated metrics. |
| **Energy integration** | kWh tracking for each PV channel, output to home, and grid input. |
| **English translation** | All helper names, automation aliases, comments, and notification messages translated from German. |
| **zenSDK alignment** | Sensor names, unit conversions, and comments cross-referenced with the [official property docs](https://github.com/Zendure/zenSDK/blob/main/docs/en_properties.md). Temperature formula updated to match the official `(val - 2731) / 10.0`. |
| **Configurable Shelly IDs** | `energy_monitoring.yaml` uses `input_text` helpers for the Shelly 3EM device ID and solar sensor entity, replacing 6+ hardcoded entity references. |

---

## Sensor reference

<details>
<summary><strong>Core sensors</strong> (zendure.yaml) — 7 sensors</summary>

| Sensor | zenSDK property | Description |
|---|---|---|
| SolarFlow Status Raw | — | REST poll status (OK / unavailable) |
| SolarFlow Battery Level | `electricLevel` | Average SOC (%) |
| SolarFlow Output Limit | `outputLimit` | Current output limit (W) |
| SolarFlow Solar Input | `solarInputPower` | Total PV input (W) |
| SolarFlow Enclosure Temp | `hyperTmp` | Enclosure temperature (°C) |
| SolarFlow Pack Input Power | net(`outputPackPower`, `packInputPower`) | Net charge power (W) |
| SolarFlow Pack Output Power | net(`packInputPower`, `outputPackPower`) | Net discharge power (W) |

</details>

<details>
<summary><strong>PV channel sensors</strong> (zendure_extended.yaml) — 4 power + 4 energy</summary>

| Sensor | zenSDK property |
|---|---|
| SolarFlow Solar Power Panel 1–4 | `solarPower1`–`solarPower4` |
| SolarFlow Panel 1–4 Energy | Integration of above (kWh) |

</details>

<details>
<summary><strong>Power flow sensors</strong> — 3 power + 2 energy</summary>

| Sensor | zenSDK property | Description |
|---|---|---|
| SolarFlow Output Home Power | `outputHomePower` | Output to home (W) |
| SolarFlow Grid Input Power | `gridInputPower` | Grid input power for AC charging (W) |
| SolarFlow Off-Grid Power | `gridOffPower` | Off-grid power (W) |
| SolarFlow Output Home Energy | — | kWh integration |
| SolarFlow Grid Input Energy | — | kWh integration |

</details>

<details>
<summary><strong>Battery system sensors</strong> — 3 sensors</summary>

| Sensor | zenSDK property | Description |
|---|---|---|
| SolarFlow Battery Voltage | `BatVolt` | Battery voltage (V, raw × 0.01) |
| SolarFlow Pack Count | `packNum` | Number of connected packs |
| SolarFlow Pack State | `packState` | Standby / Charging / Discharging |

</details>

<details>
<summary><strong>Per-pack sensors</strong> — 11 per pack × 2 packs = 22</summary>

| Sensor | zenSDK property | Description |
|---|---|---|
| Pack N SoC | `socLevel` | State of charge (%) |
| Pack N Power | `power` | Pack power (W) |
| Pack N State | `state` | Standby / Charging / Discharging |
| Pack N Temperature | `maxTemp` | Pack temperature (°C) |
| Pack N Voltage | `totalVol` | Total voltage (V) |
| Pack N Current | `batcur` | Battery current (A) |
| Pack N Max Cell Voltage | `maxVol` | Highest cell voltage (V) |
| Pack N Min Cell Voltage | `minVol` | Lowest cell voltage (V) |
| Pack N Cell Imbalance | `maxVol` − `minVol` | Cell voltage spread (mV) |
| Pack N Serial | `sn` | Battery pack serial number |
| Pack N Heat State | `heatState` | Heating off / on |

</details>

<details>
<summary><strong>Device & status sensors</strong> — 13 sensors</summary>

| Sensor | zenSDK property | Description |
|---|---|---|
| WiFi Signal | `rssi` | Signal strength (dBm) |
| Remaining Discharge Time | `remainOutTime` | Minutes until empty |
| Remaining Charge Time | `remainInputTime` | Minutes until full |
| Fan Mode | `Fanmode` | Off / On |
| Fan Speed | `Fanspeed` | Auto / Gear 1 / Gear 2 |
| Error State | `is_error` | OK / Error |
| Heat State | `heatState` | Off / Heating |
| AC Status | `acStatus` | AC state (0–2) |
| DC Status | `dcStatus` | DC state (0–2) |
| PV Status | `pvStatus` | PV state (0–1) |
| Grid State | `gridState` | Off-Grid / On-Grid |
| IoT State | `IOTState` | IoT connection state |
| Pass-Through | `pass` | Off / On |

</details>

<details>
<summary><strong>Configuration readback sensors</strong> — 8 sensors</summary>

| Sensor | zenSDK property | Description |
|---|---|---|
| AC Mode | `acMode` | Charge or discharge mode (1–2) |
| Smart Mode | `smartMode` | Flash / RAM |
| Max Inverter Output | `inverseMaxPower` | Max inverter output (W) |
| AC Charge Limit | `inputLimit` | AC charge limit (W) |
| Max Charge Power | `chargeMaxLimit` | Max charge power (W) |
| SoC Set | `socSet` | Target SOC (%) |
| Min SoC | `minSoc` | Minimum SOC (%) |
| Lamp | `lampSwitch` | Lamp state (Off / On) |

</details>

<details>
<summary><strong>Calculated sensors</strong> — 3 sensors</summary>

| Sensor | Description |
|---|---|
| Pack Temperature Delta | Absolute temperature difference between pack 1 and 2 (°C) |
| Pack SoC Delta | Absolute SoC difference between pack 1 and 2 (%) |
| System Efficiency | (output + charge) / solar input × 100 (%) |

</details>

---

## See also

- **[Solarflow Web Bluetooth Manager](https://arselzer.github.io/solarflow-bluetooth/)** ([source](https://github.com/arselzer/solarflow-bluetooth)) — browser-based tool for connecting Zendure SolarFlow devices to WiFi over Bluetooth. No app, no account, no Python required. Includes WiFi provisioning, MQTT redirection, live telemetry, and device configuration. Supports SF 800 Pro.

---

## Credits

- **[zakazak / Utini2000](https://github.com/Utini2000/Zendure-Solarflow-Local-HomeAssistant)** — original control logic, zero-export strategy, and Home Assistant package architecture. Published under the [Home Assistant Community forum](https://community.home-assistant.io/t/zendure-solarflow-800-pro-completely-local-zereo-feed-in-without-cloud-and-even-faster-no-mqtt-no-hacs-easy-mode/980110).
- **[Zendure / zenSDK](https://github.com/Zendure/zenSDK)** — official local API documentation, property reference, and openHAB examples used to verify sensor definitions and unit conversions.
- **[epicRE / zendure_ble](https://github.com/epicRE/zendure_ble)** — Bluetooth protocol documentation with detailed property descriptions that helped identify `packData` fields and the input/output power semantics.

---

## License

The original work by Utini2000 does not specify a license. The extensions in this fork are provided as-is for personal use. If you redistribute, please credit the original authors listed above.

**Disclaimer:** This software is provided without warranty of any kind. It interacts directly with your solar hardware over HTTP. Misconfiguration could cause unexpected charging, discharging, or grid export behaviour. Use at your own risk, and always verify sensor readings against the device's actual state before relying on the control loop.
