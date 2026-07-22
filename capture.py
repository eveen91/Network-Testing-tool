import os
import json
import yaml
from datetime import datetime
from connectors.checkpoint_conn import CheckPointConnection
from connectors.aruba_conn import ArubaConnection


def load_inventory(filepath):
    with open(filepath, 'r') as file:
        inventory = yaml.safe_load(file)
    return inventory['devices']


def load_commands(filepath):
    with open(filepath, 'r') as file:
        commands = yaml.safe_load(file)
    return commands or []


def load_scenario_params(filepath):
    with open(filepath, 'r') as file:
        scenario_params = yaml.safe_load(file)
    return scenario_params or {}


def render_command(command_template, params):
    """
    FIX #3: uses str.format() (matching the YAML's single-brace "{vlan_id}"
    syntax) instead of Jinja2, which only substitutes double-brace syntax.
    Raises a clear error on a missing param instead of silently doing
    nothing.
    """
    if "{" not in command_template:
        return command_template
    try:
        return command_template.format(**(params or {}))
    except KeyError as e:
        missing_key = str(e).strip("'\"")
        raise ValueError(
            f"Command '{command_template}' requires parameter '{missing_key}', "
            f"which is not defined in the scenario params file."
        )


def run_api_call(conn, api):
    if not hasattr(conn, "run_api"):
        msg = f"Connector for this device does not support API calls (api='{api}')."
        print(msg)
        return False, msg
    return conn.run_api(api)


def run_command(conn, command, params=None, mode="cli"):
    try:
        rendered = render_command(command, params) if params else command
    except ValueError as e:
        print(str(e))
        return False, str(e)
    try:
        return conn.run(rendered, mode=mode)
    except Exception as e:
        print(f"Failed to execute {rendered}: {e}")
        return False, str(e)


def run_debug_command(conn, command, params=None, mode="expert", max_duration_seconds=30):
    try:
        rendered = render_command(command, params) if params else command
    except ValueError as e:
        print(str(e))
        return False, str(e), True
    try:
        return conn.send_command_timing_debug(
            rendered, max_duration_seconds=max_duration_seconds, mode=mode
        )
    except TypeError:
        return conn.send_command_timing_debug(
            rendered, max_duration_seconds=max_duration_seconds
        )


def save_output(output_dir, device_name, test_id, timestamp, raw_output):
    file_name = f"{device_name}_{test_id}_{timestamp}.txt"
    file_path = os.path.join(output_dir, file_name)
    with open(file_path, 'w') as file:
        file.write(raw_output)
    return file_name


def consolidate_outputs(device_name, output_dir, timestamp):
    consolidated_file = os.path.join(output_dir, f"{device_name}_consolidated.txt")
    command_files = [
        f for f in os.listdir(output_dir)
        if device_name in f and f.endswith(".txt") and "consolidated" not in f
    ]
    with open(consolidated_file, 'w') as file:
        for cmd_file in sorted(command_files):
            with open(os.path.join(output_dir, cmd_file), 'r') as cmd_f:
                content = cmd_f.read()
                file.write(f"Command: {cmd_file}\n")
                file.write(content)
                file.write("\n\n")


def handle_manual_command(manifest, device_name, test_id, section="", description=""):
    """
    FIX #5: previously wrote to the flat, ticket-wide manifest["per_command"]
    dict, keyed only by test_id. Now writes into
    manifest["per_device"][device_name]["commands"][test_id], consistent
    with every other command result -- see capture_pre_post() below for why
    this matters (two Check Point cluster members, or two VSX nodes, running
    the same test_id would otherwise silently overwrite each other's
    result).
    """
    prompt = f"{test_id} — {description or 'Manual execution required'}. " \
             f"Confirm executed manually and add notes, or type 'skip': "
    response = input(prompt)
    entry = {"section": section, "description": description}
    if response.strip().lower() == "skip":
        entry.update({"status": "skipped", "reason": "manual execution skipped"})
    else:
        entry.update({"status": "executed manually", "notes": response})
    manifest["per_device"][device_name]["commands"][test_id] = entry


def capture_pre_post(ticket_number, phase, sections, devices=None, params=None, skip_manual=False):
    """
    FIX #4: `phase` ("pre"/"post") is now a real part of the output path
    (captures/<ticket>/<phase>/<timestamp>/...), instead of always writing
    to a folder literally named "baseline". consolidate_outputs() now runs
    once per device inside the loop, not once after it using leftover loop
    variables.
    """
    if not os.path.exists("captures"):
        os.makedirs("captures")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join("captures", ticket_number, phase, timestamp)

    if not os.path.exists(run_dir):
        os.makedirs(run_dir)

    inventory = load_inventory("inventory.yaml")
    commands_checkpoint = load_commands("commands/checkpoint.yaml")
    commands_aruba = load_commands("commands/aruba.yaml")

    manifest = {
        "ticket": ticket_number,
        "phase": phase,
        "sections": sections,
        "start_time": datetime.now().isoformat(),
        "per_device": {}
        # FIX #5: the previous schema also had a flat, top-level
        # "per_command" dict keyed only by test_id and shared across every
        # device in the run. Since ClusterXL and VSX are inherently pairs of
        # devices, two devices running the same test_id (e.g. two CP cluster
        # members both running T-01) would silently overwrite each other's
        # result in that shared dict -- only the raw per-device .txt files
        # on disk were safe; the manifest's convenience metadata was not.
        # All command results now live under per_device[<name>]["commands"],
        # so there is no shared key space between devices.
    }

    for device in inventory:
        if devices and device['name'] not in devices:
            continue

        device_name = device['name']
        output_dir = os.path.join(run_dir, device_name)

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        manifest["per_device"][device_name] = {
            "role": device.get("role"),
            "connection_status": "connected",
            "commands": {}
        }

        try:
            if device['role'] == "cp-cluster-member":
                conn = CheckPointConnection(device)
            elif device['role'] == "aruba-vsx-node":
                conn = ArubaConnection(device)
            else:
                manifest["per_device"][device_name]["connection_status"] = "unknown role"
                continue

            if not conn.connect():
                manifest["per_device"][device_name]["connection_status"] = "failed to connect"
                continue

            commands = commands_checkpoint if device['role'] == "cp-cluster-member" else commands_aruba
            for cmd in commands:
                section = cmd.get("section")
                test_id = cmd.get("test_id")
                description = cmd.get("description")
                command = cmd.get("command", "")
                api = cmd.get("api", None)
                mode = cmd.get("mode", "cli")
                risk = cmd.get("risk", "read-only-safe")
                max_duration = cmd.get("max_duration_seconds", 30)

                if section not in sections:
                    continue

                if risk == "manual-only":
                    if skip_manual:
                        manifest["per_device"][device_name]["commands"][test_id] = {
                            "section": section, "description": description,
                            "status": "skipped", "reason": "marked as manual-only"
                        }
                    else:
                        handle_manual_command(manifest, device_name, test_id, section, description)
                    continue

                if risk == "read-only-debug" and api is None:
                    output_success, raw_output, truncated = run_debug_command(
                        conn, command, params=params, mode=mode, max_duration_seconds=max_duration
                    )
                elif api:
                    output_success, raw_output = run_api_call(conn, api)
                    truncated = False
                else:
                    output_success, raw_output = run_command(conn, command, params=params, mode=mode)
                    truncated = False

                output_file = save_output(output_dir, device_name, test_id, timestamp, raw_output)

                manifest["per_device"][device_name]["commands"][test_id] = {
                    "section": section,
                    "description": description,
                    "risk": risk,
                    "status": "captured successfully" if output_success else "attempted but failed",
                    "truncated": truncated,
                    "output_file": output_file,
                }

            consolidate_outputs(device_name, output_dir, timestamp)
            conn.disconnect()
        except Exception as e:
            manifest["per_device"][device_name]["connection_status"] = "disconnected with error"
            print(f"Error processing {device['name']}: {e}")

    manifest["end_time"] = datetime.now().isoformat()
    manifest_file = os.path.join(run_dir, "capture_manifest.json")
    with open(manifest_file, 'w') as file:
        json.dump(manifest, file, indent=4)

    print(f"Capture completed. Manifest saved to {manifest_file}")
    return manifest_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run network baseline capture.")
    parser.add_argument("--ticket", required=True, help="Ticket number (e.g., CHG-12345)")
    parser.add_argument("--phase", required=True, choices=["pre", "post"],
                         help="Whether this is the pre-change or post-change capture run")
    parser.add_argument("--section", required=True, help="Comma-separated list of sections to run")
    parser.add_argument("--params", required=True, help="Path to scenario_params.yaml file")
    parser.add_argument("--devices", required=False, default=None,
                         help="Optional comma-separated subset of device names to run against")
    parser.add_argument("--skip-manual", action='store_true', help="Skip manual-only commands")

    args = parser.parse_args()
    section_list = args.section.split(",")
    devices_list = None if not args.devices else args.devices.split(",")
    params = load_scenario_params(args.params)

    capture_pre_post(
        args.ticket, args.phase, section_list,
        devices=devices_list, params=params, skip_manual=args.skip_manual
    )