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
| `zendure_device2.yaml` | *(optional, multi-device)* Second device: IP helper, enable flag, REST sensor, 6 core derived sensors, kWh integration, state machine, flash protection, per-device logic manager |
| `zendure_coordinator.yaml` | *(optional, multi-device)* Coordinator control loop + strategy selector + diagnostic sensors. Replaces the solo loop when `zendure_coordinator_enabled` is on. |
| `tools/generate_device.py` | *(optional, multi-device)* Generator for device 3+. Clones `zendure_device2.yaml` with the right prefixes / IP and prints the coordinator snippets to paste. |

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

## Multi-device setup *(optional)*

If you have more than one SolarFlow 800 Pro behind the same grid meter, enable the coordinator. It's fully opt-in — single-device users never touch it and see no behavior change.

### How it works

All devices share one grid. Running the existing loop per device would cause every device to try to cover 100 % of the grid imbalance, producing oscillation and over-export. The coordinator replaces the per-device loops with one loop that:

1. Reads each device's state (SoC, PV, output limit, SN, enclosure temp).
2. Computes the aggregate target the same way the solo loop does, but summed across all available devices.
3. Allocates the target across devices by the selected strategy (see **Allocation strategies** below). Empty, offline, cold (< 0 °C with low PV), or force-charging devices drop out of the active set.
4. Writes each device via a generic REST command with per-device IP and serial.
5. Applies per-device drift correction and hysteresis exactly as the solo loop does.

When the coordinator is enabled, the solo loop in `zendure.yaml` steps aside via a template gate. Flipping the coordinator off restores solo operation for device 1; device 2 holds its last output until the coordinator is re-enabled.

### Allocation strategies

Set via **Settings → Devices & Services → Helpers → Zendure: Allocation Strategy**. All three share one water-fill algorithm; the strategy only decides which devices are grouped to share equally within a "bucket". Within any bucket the weakest-cap device is filled first and surplus is redistributed to devices with more headroom, so a single capped device never strands capacity.

| Strategy | How it buckets | Best for |
|---|---|---|
| `priority_by_soc` | Each device gets a unique bucket; only true SoC ties share. | Maximising the effective capacity of one device before touching the next — e.g. if you prefer asymmetric wear. Some oscillation is expected when two devices' SoCs cross each other. |
| `priority_by_soc_bucketed` *(default)* | Devices within ~2 % SoC of the leader share equally; the next tier ~2 % lower shares among themselves; and so on. | Most users. Gives a soft priority to the fuller device without the hard cross-over flip that strict priority produces. |
| `equal_split` | All active devices in one bucket — equal share regardless of SoC. | Balanced wear; long-term SoC equalisation. A device in bypass / low SoC still drops out via its cap, so the other device picks up the slack automatically. |

Switching strategy is safe at runtime — it takes effect on the next 5-second tick.

### Adding a second device

1. Copy `zendure_device2.yaml` and `zendure_coordinator.yaml` into `packages/`.
2. Set the second device's IP in **Settings → Devices & Services → Helpers → Zendure 2: Device IP Address**, or edit the `initial` field in `zendure_device2.yaml`.
3. Add the new high-frequency entities to the recorder and logbook excludes. The coordinator ticks every 5 s and updates `input_datetime.zendure_last_tick` on each cycle; the aggregate target sensor has attribute churn on every tick too — both are noisy without exclusion:

   ```yaml
   recorder:
     exclude:
       entities:
         - automation.zendure_control_loop
         - automation.zendure_state_machine
         - automation.zendure_multi_device_coordinator
         - input_number.zendure_last_sent_limit
         - input_number.zendure_2_last_sent_limit
         - input_datetime.zendure_last_tick
         - sensor.zendure_coordinator_target
         # Optional — keep recording these if you want share-over-time graphs:
         # - sensor.zendure_1_coordinator_share
         # - sensor.zendure_2_coordinator_share
         # - sensor.zendure_seconds_since_last_tick

   logbook:
     exclude:
       entities:
         - automation.zendure_control_loop
         - automation.zendure_state_machine
         - automation.zendure_multi_device_coordinator
         - input_datetime.zendure_last_tick
         - sensor.zendure_coordinator_target
         - sensor.zendure_seconds_since_last_tick
   ```

4. Restart Home Assistant.
5. Flip **Zendure: Multi-Device Coordinator Active** to **on** in the HA UI.

The coordinator takes over. You'll get a persistent notification confirming the switch.

### Adding a third device (or more)

The `devices` list in `zendure_coordinator.yaml` is the single source of truth and the allocation logic is N-agnostic. Use the generator:

```bash
python3 tools/generate_device.py --n 3 --ip 192.168.30.93
```

This writes `zendure_device3.yaml` (a copy of the device-2 package with `_2` → `_3` everywhere and the IP set) and prints two small YAML snippets to stdout: a new `devices:` list entry and a new coordinator-share sensor. Paste both into `zendure_coordinator.yaml` at the locations indicated in the output, then restart Home Assistant.

No changes to the allocation algorithm, drift recovery, saturation, failsafe, or hysteresis are needed — the logic scales automatically with every device you add. The generator only uses the Python standard library (plus PyYAML if available, for a post-generation parse check), so no `pip install` required.

### Per-device enable flag

Each device has its own `input_boolean.zendure_N_enabled` (default on). Flip it off to temporarily remove that device from the coordinator's active set — useful for:

- Taking one device offline for maintenance without changing its IP.
- Testing "what does the system do without this device" without pulling cables.
- Forcing a single-device cycle while troubleshooting.

A disabled device is invisible to the coordinator — its SoC doesn't influence priority, it receives no writes, and the other devices treat any residual grid load from it as an external consumer. The device's own state machine (emergency charge, calibration, flash protection) still fires on manual toggles; `enabled` only gates the 5-second allocation loop.

### Coordinator diagnostics

Once the coordinator is enabled, three sensors populate on each tick:

| Sensor | State | Attributes |
|---|---|---|
| `sensor.zendure_coordinator_target` | Aggregate W target for this tick | `strategy`, `is_failsafe`, `shelly_ok`, `grid_power`, `adjusted_grid_power`, `active_count`, `force_charge_count`, `allocations` (list of `{id, limit, base}`), `devices` (list of `{id, battery, cap, bucket, …}`) |
| `sensor.zendure_1_coordinator_share` | Device 1's allocated W this tick | — |
| `sensor.zendure_2_coordinator_share` | Device 2's allocated W this tick | — |

These are fed by a `zendure_coordinator_tick` event the coordinator fires each cycle, consumed by trigger-based template sensors. Good places to pin these sensors:

- **A dashboard card** showing the target and each device's share side-by-side to verify the allocation matches what you expect.
- **Developer Tools → States** for on-the-spot inspection of the `allocations` / `devices` attributes, which include the per-device bucket keys and caps — useful when debugging why a device isn't getting what you think it should.
- **Long-term history** (if you remove these sensors from the recorder exclude list) for post-hoc analysis of allocation decisions over time.

### Fleet aggregate sensors

When the coordinator is active, these sum across devices automatically:

| Sensor | Meaning |
|---|---|
| `sensor.zendure_fleet_solar_input` | Total PV across all devices (W) |
| `sensor.zendure_fleet_output_power` | Total output-to-home limit across devices (W) |
| `sensor.zendure_fleet_battery_charging_power` | Combined charging into batteries (W) |
| `sensor.zendure_fleet_battery_discharging_power` | Combined discharge from batteries (W) |
| `sensor.zendure_fleet_soc_average` | Mean SoC over available devices (%) |
| `sensor.zendure_fleet_active_count` | Devices reporting `OK` |
| `sensor.zendure_fleet_solar_energy_total` | Fleet solar kWh — register this in **Settings → Energy** |
| `sensor.zendure_fleet_battery_energy_charged` | Fleet charging kWh — register as **Battery storage** in **Energy** |
| `sensor.zendure_fleet_battery_energy_discharged` | Fleet discharge kWh — register as **Battery storage** in **Energy** |

The fleet templates use hardcoded two-device lists; when you add device 3+ with `tools/generate_device.py`, the script prints the exact entries to append to each list.

### Device offline alerts

Each device has a paired pair of automations that:

- Fire a persistent notification after its REST sensor stays non-`OK` for 30 seconds (*"Zendure Device N Offline"* with the device's IP in the body).
- Dismiss the notification after the sensor returns to `OK` for 10 seconds.

Behaviour matches the existing Shelly offline notice. In coordinator mode, an offline device is automatically excluded from allocation and its share is redistributed to the remaining devices.

### Dry-run mode

Flip **Zendure: Dry-Run Mode** to **on** before enabling the coordinator on a live multi-device install. The coordinator will:

- Compute allocations on every 5-second tick as normal.
- Fire the `zendure_coordinator_tick` event, so `sensor.zendure_coordinator_target`, the per-device share sensors, and the `allocations` attribute all reflect what *would* have been written.
- **Skip** the REST write and the `last_sent_limit` update.

Useful workflows:

- **Initial multi-device validation.** Flip coordinator on + dry-run on, then watch the share sensors respond to real grid/SoC changes over ~30 minutes. If the allocation matches your expectation across a range of conditions (morning solar ramp-up, cloud pass, evening discharge), flip dry-run off.
- **Strategy comparison.** Switch `zendure_allocation_strategy` between options in dry-run and see how each would allocate under the current load — without any writes committing to devices.
- **Debugging weird behaviour.** If you suspect a device is getting the wrong share, enable dry-run, check `allocations` in Developer Tools → States, and confirm whether the issue is in the coordinator's decision or in a downstream write.

`sensor.zendure_coordinator_target`'s `dry_run` attribute surfaces the current state on dashboards.

State machines — emergency charge, calibration, flash protection — are **not** gated by dry-run. Those respond to explicit user toggles, so flipping `zendure_emergency_charge` while dry-run is on still force-charges the device. Dry-run only silences the autonomous 5-second write loop.

### Coordinator heartbeat

The coordinator stamps `input_datetime.zendure_last_tick` at the end of every cycle. Two derived signals make a frozen loop visible:

- **`sensor.zendure_seconds_since_last_tick`** — time since the last stamp, updated every 10 seconds by a trigger-based template sensor (so it keeps counting up even when no new tick arrives). `-1` means the coordinator hasn't ticked since HA startup.
- **Notification *"Zendure Coordinator Frozen"*** — fires when the gap exceeds 15 s *for 30 seconds* while the coordinator is enabled. Dismisses automatically when a fresh tick arrives or the coordinator is disabled.

Typical causes when this fires:
- A Jinja template error inside the coordinator — check the automation trace for the failing step.
- A missing helper (happens if you enabled the coordinator before installing `zendure_device2.yaml`).
- HA restarting or reloading automations — the notification clears as soon as the first post-restart tick lands.

### Example Lovelace dashboard

<details>
<summary><strong>Copy-paste dashboard YAML</strong> (built-in cards only — no HACS)</summary>

Drop this into a new dashboard via **Settings → Dashboards → Add dashboard → Start with empty dashboard → ⋮ → Raw configuration editor**. Assumes you have two devices with the coordinator + diagnostics + fleet sensors installed. For a solo setup, remove the Device 2 column and the Coordinator card.

```yaml
title: Zendure SolarFlow
views:
  - title: Overview
    path: overview
    icon: mdi:solar-power-variant
    cards:
      - type: horizontal-stack
        cards:
          - type: entities
            title: Grid
            icon: mdi:transmission-tower
            entities:
              - entity: sensor.power_import
                name: Importing
              - entity: sensor.power_export
                name: Exporting
              - entity: sensor.power_consumption
                name: House Consumption
              - type: divider
              - entity: sensor.energy_import_daily
                name: Imported Today
              - entity: sensor.energy_export_daily
                name: Exported Today
          - type: entities
            title: Coordinator
            icon: mdi:lan-connect
            entities:
              - input_boolean.zendure_coordinator_enabled
              - input_boolean.zendure_auto_mode
              - input_boolean.zendure_dry_run
              - input_select.zendure_allocation_strategy
              - type: divider
              - entity: sensor.zendure_coordinator_target
                name: Target Total
              - type: attribute
                entity: sensor.zendure_coordinator_target
                attribute: active_count
                name: Active devices
              - type: attribute
                entity: sensor.zendure_coordinator_target
                attribute: is_failsafe
                name: Failsafe
              - entity: sensor.zendure_seconds_since_last_tick
                name: Heartbeat (s since tick)

      - type: entities
        title: Fleet
        icon: mdi:battery-high
        entities:
          - sensor.zendure_fleet_solar_input
          - sensor.zendure_fleet_output_power
          - sensor.zendure_fleet_battery_charging_power
          - sensor.zendure_fleet_battery_discharging_power
          - sensor.zendure_fleet_soc_average
          - sensor.zendure_fleet_active_count

      - type: horizontal-stack
        cards:
          - type: entities
            title: Device 1
            icon: mdi:battery
            entities:
              - input_boolean.zendure_enabled
              - entity: sensor.solarflow_battery_level
                name: SoC
              - entity: sensor.zendure_1_coordinator_share
                name: Allocated
              - entity: sensor.solarflow_output_limit
                name: Actual output
              - entity: sensor.solarflow_solar_input
                name: Solar
              - entity: sensor.solarflow_enclosure_temp
                name: Temperature
              - type: divider
              - input_boolean.zendure_emergency_charge
              - input_boolean.zendure_calibration_mode
          - type: entities
            title: Device 2
            icon: mdi:battery
            entities:
              - input_boolean.zendure_2_enabled
              - entity: sensor.solarflow_2_battery_level
                name: SoC
              - entity: sensor.zendure_2_coordinator_share
                name: Allocated
              - entity: sensor.solarflow_2_output_limit
                name: Actual output
              - entity: sensor.solarflow_2_solar_input
                name: Solar
              - entity: sensor.solarflow_2_enclosure_temp
                name: Temperature
              - type: divider
              - input_boolean.zendure_2_emergency_charge
              - input_boolean.zendure_2_calibration_mode

      - type: history-graph
        title: Last 24 hours
        hours_to_show: 24
        entities:
          - sensor.power_import
          - sensor.power_export
          - sensor.zendure_fleet_solar_input
          - sensor.zendure_fleet_output_power
          - sensor.zendure_fleet_soc_average
```

</details>

### Core vs extended sensors for additional devices

The second-device package ships with 6 core derived sensors — enough for the coordinator and a reasonable dashboard:

- battery level, output limit, solar input, enclosure temperature, pack input power, pack output power

The full 56-sensor extended set from `zendure_extended.yaml` (per-panel PV, per-pack cell diagnostics, config readback, status flags) is **device-1 only** by default. If you want the same depth on device 2, copy `zendure_extended.yaml` to `zendure_device2_extended.yaml` and do a find-and-replace of:

- `solarflow_status_raw` → `solarflow_2_status_raw`
- every `unique_id: solarflow_…` → `solarflow_2_…`
- every `name: "SolarFlow …"` → `"SolarFlow 2 …"`

This is mechanical but tedious — a generator script is a possible future addition.

### Behavioral notes

- **Failsafe.** If the Shelly goes offline, each active device is set to the configured failsafe base load. Total grid intake is `failsafe_watt × active_device_count`; size your failsafe accordingly.
- **Force-charge compensation.** When one device is in emergency charge or calibration, its AC draw is subtracted from the grid reading that the remaining devices see, so they don't chase a "phantom" grid import. Force-charging devices are handled entirely by their own state machines; they contribute nothing to the allocation.
- **Seasonal SoC / bias / saturation.** These settings live in device 1's Logic Manager and are applied globally across all devices. There's no per-device override today.
- **Emergency charge & calibration triggers.** Each device has its own `input_boolean.zendure_N_emergency_charge`, `zendure_N_calibration_mode`, and `input_datetime.zendure_N_last_full_charge`. Each device's Logic Manager independently decides when to enter / exit these modes based on its own SoC history.
- **Single-device safety.** If `zendure_coordinator_enabled` is on but device 2's REST sensor is unavailable (helper unset, device offline, or `zendure_device2.yaml` not installed), device 2 drops out of the active set and the coordinator collapses to single-device behaviour equivalent to the solo loop.

### Tested scope

The coordinator has been designed and YAML-lint-verified. Like the rest of this project, **it has only been tested with SF 800 Pro hardware**. Multi-device deployment has not been field-tested; if you install this, watch the grid meter for a few cycles and verify writes land on the correct devices before trusting unattended operation.

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
| **Multi-device coordinator** *(opt-in)* | `zendure_coordinator.yaml` + `zendure_device2.yaml` add coordination for N ≥ 2 SolarFlow devices sharing one grid meter. Three allocation strategies (`priority_by_soc`, `priority_by_soc_bucketed`, `equal_split`) with water-fill redistribution, per-device enable flag, force-charge grid compensation, and the same drift/hysteresis/failsafe semantics as the solo loop. Solo users see zero behavior change. |
| **Coordinator observability** *(opt-in)* | Diagnostic sensors (`sensor.zendure_coordinator_target` + per-device `…_coordinator_share`) fed by a `zendure_coordinator_tick` event each cycle. Fleet aggregate sensors summing across devices. Dry-run mode for pre-deployment validation. Heartbeat sensor and frozen-loop alert. Per-device offline notifications. |
| **Device generator** *(opt-in)* | `tools/generate_device.py` clones `zendure_device2.yaml` into `zendure_deviceN.yaml` with correct prefixes + IP and prints the coordinator snippets to paste. Stdlib-only. |

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

<details>
<summary><strong>Device 2 sensors</strong> (zendure_device2.yaml) — 6 core + 3 energy</summary>

Mirror of the core / power-flow sets above, with `_2` / `SolarFlow 2 ` prefixes. Reads from `sensor.solarflow_2_status_raw`.

| Sensor | Notes |
|---|---|
| SolarFlow 2 Battery Level | `electricLevel`, % |
| SolarFlow 2 Output Limit | `outputLimit`, W |
| SolarFlow 2 Solar Input | `solarInputPower`, W |
| SolarFlow 2 Enclosure Temp | `hyperTmp`, °C |
| SolarFlow 2 Pack Input Power | Net charge (W) |
| SolarFlow 2 Pack Output Power | Net discharge (W) |
| SolarFlow 2 Solar Energy Total | kWh |
| SolarFlow 2 Battery Energy Charged | kWh |
| SolarFlow 2 Battery Energy Discharged | kWh |

Additional devices (3+) follow the same pattern via `tools/generate_device.py`. Device-2's extended sensors (the 56-sensor set from `zendure_extended.yaml`) are *not* shipped by default — see **Core vs extended sensors for additional devices**.

</details>

<details>
<summary><strong>Coordinator sensors</strong> (zendure_coordinator.yaml) — 4 + N share + 3 fleet-kWh</summary>

Trigger-based diagnostic sensors populated by the `zendure_coordinator_tick` event fired at the end of each tick.

| Sensor | Notes |
|---|---|
| Zendure Coordinator Target | Aggregate target for this tick (W). Attributes: `strategy`, `is_failsafe`, `dry_run`, `shelly_ok`, `grid_power`, `adjusted_grid_power`, `active_count`, `force_charge_count`, `allocations`, `devices` |
| Zendure 1 Coordinator Share | Device 1's allocated limit this tick (W) |
| Zendure 2 Coordinator Share | Device 2's allocated limit this tick (W) |
| Zendure Seconds Since Last Tick | Time since the last coordinator cycle (s). `-1` = no tick since HA startup. Re-evaluates every 10 s via a time-pattern trigger so it keeps counting between ticks |

Fleet aggregates (state-based — update when underlying device sensors change):

| Sensor | Notes |
|---|---|
| Zendure Fleet Solar Input | Σ device solar inputs (W) |
| Zendure Fleet Output Power | Σ device output limits (W) |
| Zendure Fleet Battery Charging Power | Σ net charge (W) |
| Zendure Fleet Battery Discharging Power | Σ net discharge (W) |
| Zendure Fleet SoC Average | Mean SoC over available devices (%) |
| Zendure Fleet Active Count | Devices reporting `OK` |
| Zendure Fleet Solar Energy Total | kWh integration — register in **Settings → Energy** |
| Zendure Fleet Battery Energy Charged | kWh — Battery storage (in) |
| Zendure Fleet Battery Energy Discharged | kWh — Battery storage (out) |

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
