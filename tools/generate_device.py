#!/usr/bin/env python3
"""Generate a Zendure device package for an additional SolarFlow device.

Usage:
    python3 tools/generate_device.py --n 3 --ip 192.168.30.93

Reads zendure_device2.yaml as the template, replaces the "2" prefixes with
your device number, substitutes the IP into input_text.zendure_device_N_ip's
`initial:` value, and writes zendure_deviceN.yaml into the repo root.

It also prints the two YAML snippets you need to paste into
zendure_coordinator.yaml:

  1. A new entry in the `devices:` list (section 2 — inside the coordinator
     automation's Phase 1 variables block).
  2. A per-device "coordinator share" diagnostic sensor (section 4).

After pasting and restarting Home Assistant, sensor.solarflow_N_status_raw
should report "OK" and the coordinator will start allocating to the device.

Only uses the Python standard library — no pip install needed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------

def _apply_prefix_substitutions(text: str, n: int) -> str:
    """Replace all "2"-suffixed tokens with N-suffixed equivalents.

    Order matters: more-specific patterns must run before the general
    ``zendure_2_`` prefix so they don't get double-substituted.
    """
    replacements = [
        # The IP helper's full name is the longest "_2" token; replace it
        # before the generic zendure_2_ prefix runs.
        ("zendure_device_2_ip", f"zendure_device_{n}_ip"),
        # Snake-case helper/entity prefixes
        ("zendure_2_", f"zendure_{n}_"),
        ("solarflow_2_", f"solarflow_{n}_"),
        # Display names, colon form
        ("Zendure 2:", f"Zendure {n}:"),
        # Display names, space form (notification titles, etc.)
        ("Zendure 2 ", f"Zendure {n} "),
        ("SolarFlow 2 ", f"SolarFlow {n} "),
        # Header comments
        ("DEVICE 2", f"DEVICE {n}"),
        ("Second SolarFlow device", f"SolarFlow device #{n}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _set_device_ip(text: str, n: int, ip: str) -> str:
    """Set the `initial:` IP on the device-N IP helper.

    Uses a regex anchored to ``zendure_device_N_ip:`` so we don't touch any
    other IP-shaped string in the file (like a comment example).
    """
    pattern = re.compile(
        rf"(zendure_device_{n}_ip:\s*(?:.*\n)*?\s*initial:\s*\")"
        r"[0-9.]+"
        r"(\")",
        re.MULTILINE,
    )
    new_text, count = pattern.subn(rf"\g<1>{ip}\g<2>", text, count=1)
    if count == 0:
        print(
            "WARNING: couldn't find the IP helper's initial field to patch; "
            f"set it manually in the generated file.",
            file=sys.stderr,
        )
    return new_text


def generate_device_file(n: int, ip: str, source: Path, out_dir: Path) -> Path:
    text = source.read_text()
    text = _apply_prefix_substitutions(text, n)
    text = _set_device_ip(text, n, ip)

    out_path = out_dir / f"zendure_device{n}.yaml"
    out_path.write_text(text)

    try:
        import yaml  # type: ignore
    except ImportError:
        pass
    else:
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:  # pragma: no cover
            print(f"WARNING: generated YAML does not parse: {e}", file=sys.stderr)

    return out_path


# ---------------------------------------------------------------------------
# Coordinator snippets
# ---------------------------------------------------------------------------

def coordinator_device_block(n: int) -> str:
    """Return the devices: list entry to paste into the coordinator."""
    return f"""\
            - id: {n}
              ip: "{{{{ states('input_text.zendure_device_{n}_ip') }}}}"
              sn: "{{{{ state_attr('sensor.solarflow_{n}_status_raw', 'sn') }}}}"
              ok: >-
                {{{{ states('sensor.solarflow_{n}_status_raw') == 'OK'
                   and state_attr('sensor.solarflow_{n}_status_raw', 'sn') is not none }}}}
              enabled: >-
                {{{{ is_state('input_boolean.zendure_{n}_enabled', 'on')
                   or not states('input_boolean.zendure_{n}_enabled') in ['on', 'off'] }}}}
              battery: "{{{{ states('sensor.solarflow_{n}_battery_level') | float(0) }}}}"
              current_limit: "{{{{ states('sensor.solarflow_{n}_output_limit') | float(0) }}}}"
              solar: "{{{{ states('sensor.solarflow_{n}_solar_input') | float(0) }}}}"
              temp: "{{{{ states('sensor.solarflow_{n}_enclosure_temp') | float(20) }}}}"
              last_sent: "{{{{ states('input_number.zendure_{n}_last_sent_limit') | int }}}}"
              force_charge: >-
                {{{{ is_state('input_boolean.zendure_{n}_emergency_charge', 'on')
                   or is_state('input_boolean.zendure_{n}_calibration_mode', 'on') }}}}
              last_sent_entity: "input_number.zendure_{n}_last_sent_limit"
"""


def coordinator_share_sensor(n: int) -> str:
    """Return the share sensor entry for section 4 of the coordinator."""
    return f"""\
      - name: "Zendure {n} Coordinator Share"
        unique_id: zendure_{n}_coordinator_share
        unit_of_measurement: "W"
        device_class: power
        state: >
          {{% set m = trigger.event.data.allocations
                     | selectattr('id', 'eq', {n}) | list %}}
          {{{{ m[0].limit if m else 0 }}}}
"""


def fleet_sensor_updates(n: int) -> str:
    """Instructions for adding device N to each fleet aggregate sensor."""
    lines = [
        "Each fleet sensor in section 4 has an `ids:` list — append one entry",
        "to each list so the fleet totals include the new device:",
        "",
        "  Fleet Solar Input                  add 'sensor.solarflow_{n}_solar_input'",
        "  Fleet Battery Charging Power       add 'sensor.solarflow_{n}_pack_input_power'",
        "  Fleet Battery Discharging Power    add 'sensor.solarflow_{n}_pack_output_power'",
        "  Fleet Output Power                 add 'sensor.solarflow_{n}_output_limit'",
        "  Fleet SoC Average                  add 'sensor.solarflow_{n}_battery_level'",
        "  Fleet Active Count                 add 'sensor.solarflow_{n}_status_raw'",
    ]
    return "\n".join(line.format(n=n) for line in lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, required=True,
                        help="Device number (must be >= 3)")
    parser.add_argument("--ip", required=True,
                        help="Local IPv4 address of the new device")
    parser.add_argument("--source", default="zendure_device2.yaml",
                        help="Template to clone (default: zendure_device2.yaml)")
    parser.add_argument("--output-dir", default=".",
                        help="Where to write the generated file (default: cwd)")
    args = parser.parse_args(argv)

    if args.n < 3:
        parser.error(
            "--n must be >= 3. Device 1 lives in zendure.yaml; "
            "device 2 lives in zendure_device2.yaml."
        )

    if not _IPV4_RE.match(args.ip):
        parser.error(f"--ip {args.ip!r} doesn't look like an IPv4 address")

    source = Path(args.source)
    if not source.is_file():
        parser.error(f"source template not found: {source}")

    out_dir = Path(args.output_dir)
    if not out_dir.is_dir():
        parser.error(f"output directory not found: {out_dir}")

    out_path = out_dir / f"zendure_device{args.n}.yaml"
    if out_path.exists():
        parser.error(f"output file already exists: {out_path} (move it aside first)")

    generate_device_file(args.n, args.ip, source, out_dir)
    n = args.n

    print(f"Wrote {out_path}")
    print()
    print(f"=== Append to the `devices:` list in zendure_coordinator.yaml ===")
    print(f"    (inside the 'Zendure: Multi-Device Coordinator' automation,")
    print(f"     in Phase 1's variables block)")
    print()
    print(coordinator_device_block(n))
    print(f"=== Append to section 4's trigger-based template sensors ===")
    print(f"    (the `sensor:` list under the zendure_coordinator_tick trigger)")
    print()
    print(coordinator_share_sensor(n))
    print(f"=== Update fleet sensors in section 4 (the non-trigger sensor list) ===")
    print()
    print(fleet_sensor_updates(n))
    print()
    print(
        f"Then restart Home Assistant. sensor.solarflow_{n}_status_raw should "
        f"turn 'OK' once the device responds, and the coordinator will include "
        f"it from the next 5-second tick."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
