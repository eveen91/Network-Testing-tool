import os
import json
import yaml
import time
from datetime import datetime
from connectors.checkpoint_conn import CheckPointConnection
from connectors.aruba_conn import ArubaConnection

def load_commands(filepath):
    with open(filepath, 'r') as file:
        commands = yaml.safe_load(file)
    return commands

def run_command(conn, command):
    try:
        output = conn.send_command_timing(command)
        return True, output
    except Exception as e:
        print(f"Failed to execute {command}: {e}")
        return False, str(e)

def save_output(output_dir, device_name, test_id, timestamp, raw_output):
    file_path = os.path.join(output_dir, f"{device_name}_{test_id}_{timestamp}.txt")
    with open(file_path, 'w') as file:
        file.write(raw_output)

def consolidate_outputs(device_name, output_dir, timestamp):
    consolidated_file = os.path.join(output_dir, f"{device_name}_consolidated.txt")
    command_files = [f for f in os.listdir(output_dir) if device_name in f and ".txt" in f]
    
    with open(consolidated_file, 'w') as file:
        for cmd_file in command_files:
            with open(os.path.join(output_dir, cmd_file), 'r') as cmd_f:
                content = cmd_f.read()
                file.write(f"Command: {cmd_file}\n")
                file.write(content)
                file.write("\n\n")

def capture_pre_post(ticket_number, phase, devices=None):
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
        "start_time": datetime.now().isoformat(),
        "per_command": {},
        "per_device": {}
    }

    for device in inventory:
        if devices and device['name'] not in devices:
            continue
        
        device_name = device['name']
        output_dir = os.path.join(run_dir, device_name)
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        manifest["per_device"][device_name] = {"connection_status": "connected"}

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
                test_id = cmd.get("test_id")
                description = cmd.get("description")
                command = cmd.get("command", "")
                api = cmd.get("api", None)
                mode = cmd.get("mode", "cli")
                risk = cmd.get("risk", "read-only-safe")

                if risk != "read-only-safe":
                    manifest["per_command"][test_id] = {"status": "skipped", "reason": "not read-only-safe"}
                    continue

                if api:
                    # Implement API call here
                    output_success, raw_output = run_api_call(conn, api)
                else:
                    output_success, raw_output = run_command(conn, command)

                manifest["per_command"][test_id] = {
                    "status": "captured successfully" if output_success else "attempted but failed",
                    "output": raw_output
                }

                save_output(output_dir, device_name, test_id, timestamp, raw_output)

            conn.disconnect()
        except Exception as e:
            manifest["per_device"][device_name]["connection_status"] = "disconnected with error"
            print(f"Error processing {device['name']}: {e}")

    consolidate_outputs(device_name, output_dir, timestamp)
    manifest_file = os.path.join(run_dir, "capture_manifest.json")
    with open(manifest_file, 'w') as file:
        json.dump(manifest, file, indent=4)

    print(f"Capture completed. Manifest saved to {manifest_file}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run network baseline capture.")
    parser.add_argument("--ticket", required=True, help="Ticket number (e.g., CHG-12345)")
    parser.add_argument("--phase", choices=["pre", "post"], required=True, help="Phase of the test (pre or post)")
    parser.add_argument("--devices", type=str, help="Comma-separated list of device names to capture")
    
    args = parser.parse_args()
    devices_list = None if not args.devices else args.devices.split(",")

    capture_pre_post(args.ticket, args.phase, devices=devices_list)
