#!/usr/bin/env python3
"""Generate a Zendure device package for an additional SolarFlow device.

Usage:
    # Device 3 core package (+ coordinator snippets printed to stdout):
    python3 tools/generate_device.py --n 3 --ip 192.168.30.93

    # Device 3 with the 56 extended sensors as well:
    python3 tools/generate_device.py --n 3 --ip 192.168.30.93 --extended

    # Extended sensors only for an existing device (e.g. device 2):
    python3 tools/generate_device.py --n 2 --extended

Reads zendure_device2.yaml as the core template and zendure_extended.yaml
as the extended-sensor template, replaces the "2" prefixes with your
device number, and writes zendure_deviceN.yaml / zendure_deviceN_extended.yaml
into the repo root.

It also prints the two YAML snippets you need to paste into
zendure_coordinator.yaml (for a new core device):

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
    _verify_yaml(text, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Extended-sensor substitution (for zendure_extended.yaml → zendure_deviceN_extended.yaml)
# ---------------------------------------------------------------------------

def _apply_extended_substitutions(text: str, n: int) -> str:
    """Retarget zendure_extended.yaml at sensor.solarflow_N_status_raw.

    Targets only the three functional patterns — not general prose — so
    comments that mention "SolarFlow 800 Pro" as the device model stay
    intact instead of becoming "SolarFlow 2 800 Pro".
    """
    replacements = [
        # Source of truth for every template's state_attr(...)
        ("sensor.solarflow_status_raw",
         f"sensor.solarflow_{n}_status_raw"),
        # Every unique_id starts with solarflow_<something>
        ("unique_id: solarflow_",
         f"unique_id: solarflow_{n}_"),
        # Friendly names are all "SolarFlow <something>"
        ('name: "SolarFlow ',
         f'name: "SolarFlow {n} '),
        # Integration sensors at the bottom of the file reference upstream
        # power sensors via `source:` — those entity IDs also need the
        # device-N prefix, otherwise the kWh integrations would silently
        # accumulate against device 1's panel-power sensors.
        ("source: sensor.solarflow_",
         f"source: sensor.solarflow_{n}_"),
        # File header banner (cosmetic, but helps users tell files apart)
        ("ZENDURE SOLARFLOW - EXTENDED SENSORS ADDON",
         f"ZENDURE SOLARFLOW DEVICE {n} - EXTENDED SENSORS ADDON"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def generate_extended_file(n: int, source: Path, out_dir: Path) -> Path:
    text = source.read_text()
    text = _apply_extended_substitutions(text, n)

    out_path = out_dir / f"zendure_device{n}_extended.yaml"
    out_path.write_text(text)
    _verify_yaml(text, out_path)
    return out_path


def _verify_yaml(text: str, path: Path) -> None:
    try:
        import yaml  # type: ignore
    except ImportError:
        return
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as e:  # pragma: no cover
        print(f"WARNING: {path} does not parse as YAML: {e}", file=sys.stderr)


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
                        help="Device number (>= 3 for a new core package; "
                             ">= 2 when --extended is the only output)")
    parser.add_argument("--ip",
                        help="Local IPv4 address of the new device "
                             "(required when generating the core package)")
    parser.add_argument("--extended", action="store_true",
                        help="Also generate zendure_deviceN_extended.yaml "
                             "from zendure_extended.yaml. For an existing "
                             "device (typically N=2) where the core file is "
                             "already installed, this can be the sole output.")
    parser.add_argument("--source", default="zendure_device2.yaml",
                        help="Core template (default: zendure_device2.yaml)")
    parser.add_argument("--extended-source", default="zendure_extended.yaml",
                        help="Extended-sensor template "
                             "(default: zendure_extended.yaml)")
    parser.add_argument("--output-dir", default=".",
                        help="Where to write the generated file (default: cwd)")
    args = parser.parse_args(argv)

    n = args.n
    needs_core = n >= 3
    if n < 2:
        parser.error(
            "--n must be >= 2. Device 1 lives in zendure.yaml."
        )
    if n == 2 and not args.extended:
        parser.error(
            "--n 2 is only meaningful with --extended (the core file "
            "is already zendure_device2.yaml). Pass --extended to produce "
            "zendure_device2_extended.yaml."
        )
    if needs_core and not args.ip:
        parser.error(
            "--ip is required when generating a core package (--n >= 3)."
        )
    if needs_core and not _IPV4_RE.match(args.ip):
        parser.error(f"--ip {args.ip!r} doesn't look like an IPv4 address")

    out_dir = Path(args.output_dir)
    if not out_dir.is_dir():
        parser.error(f"output directory not found: {out_dir}")

    # Core package (only for N >= 3; N == 2's core is zendure_device2.yaml itself).
    if needs_core:
        source = Path(args.source)
        if not source.is_file():
            parser.error(f"source template not found: {source}")
        core_out = out_dir / f"zendure_device{n}.yaml"
        if core_out.exists():
            parser.error(
                f"output file already exists: {core_out} (move it aside first)"
            )
        generate_device_file(n, args.ip, source, out_dir)
        print(f"Wrote {core_out}")

    # Extended sensors.
    if args.extended:
        ext_source = Path(args.extended_source)
        if not ext_source.is_file():
            parser.error(
                f"extended-sensor template not found: {ext_source}"
            )
        ext_out = out_dir / f"zendure_device{n}_extended.yaml"
        if ext_out.exists():
            parser.error(
                f"output file already exists: {ext_out} (move it aside first)"
            )
        generate_extended_file(n, ext_source, out_dir)
        print(f"Wrote {ext_out}")

    if needs_core:
        print()
        print("=== Append to the `devices:` list in zendure_coordinator.yaml ===")
        print("    (inside the 'Zendure: Multi-Device Coordinator' automation,")
        print("     in Phase 1's variables block)")
        print()
        print(coordinator_device_block(n))
        print("=== Append to section 4's trigger-based template sensors ===")
        print("    (the `sensor:` list under the zendure_coordinator_tick trigger)")
        print()
        print(coordinator_share_sensor(n))
        print("=== Update fleet sensors in section 4 (the non-trigger sensor list) ===")
        print()
        print(fleet_sensor_updates(n))
        print()
        print(
            f"Then restart Home Assistant. sensor.solarflow_{n}_status_raw should "
            f"turn 'OK' once the device responds, and the coordinator will include "
            f"it from the next 5-second tick."
        )
    elif args.extended:
        print()
        print(
            f"Restart Home Assistant (or reload template entities) to pick up "
            f"the new sensors. They all read from sensor.solarflow_{n}_status_raw, "
            f"which your existing zendure_device{n}.yaml already defines."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
