import os
from dotenv import load_dotenv
from netmiko import ConnectHandler

# Related fix: commands/aruba.yaml uses dot-notation `api:` keys like
# "vsx.status" that were previously fed straight into f"show {api}",
# producing an invalid command ("show vsx.status" is not real AOS-CX CLI
# syntax). This is a minimal, correct fix so `api:` entries resolve to real,
# valid AOS-CX CLI commands today, without doing the full pyaoscx REST
# migration (that's separate, larger work).
API_TO_CLI = {
    "system.resource_utilization": "show system resource-utilization",
    "system.firmware_version": "show version",
    "vsx.status": "show vsx status",
    "interfaces.summary": "show interface brief",
    "lldp.neighbors": "show lldp neighbor-info",
    "vlans.all": "show vlan",
    "routing.ipv4_routes": "show ip route",
}


class ArubaConnection:
    def __init__(self, device):
        self.device = device
        self.connection = None

    def connect(self):
        load_dotenv()
        password = os.getenv(self.device["password_env_var"])
        ssh_key_path = os.path.expanduser(self.device.get("ssh_key_path", "") or "")
        key_exists = bool(ssh_key_path) and os.path.exists(ssh_key_path)

        if not password and not key_exists:
            raise ValueError(
                f"Credentials not found for Aruba device {self.device.get('name')}: "
                f"no password in ${self.device['password_env_var']} and no SSH key at "
                f"{ssh_key_path or '(not set)'}"
            )

        net_device = {
            "device_type": "aruba_aoscx",
            "host": self.device["ip"],
            "username": self.device["login"],
            "password": password,
            "key_file": ssh_key_path if key_exists else None,
        }

        try:
            self.connection = ConnectHandler(**net_device)
            output = self.connection.send_command_timing("show version")
            if "aruba" not in output.lower():
                print(f"[{self.device.get('name')}] Connected, but 'show version' "
                      f"output was unexpected: {output[:200]!r}")
            return True
        except Exception as e:
            print(f"Failed to connect to {self.device.get('name')}: {e}")
            self.connection = None
            return False

    def run(self, command, mode="cli"):
        """Matches CheckPointConnection.run()'s interface so capture.py can
        dispatch to either connector identically."""
        try:
            output = self.connection.send_command_timing(command)
            return True, output
        except Exception as e:
            print(f"Failed to execute '{command}' on {self.device.get('name')}: {e}")
            return False, str(e)

    def run_api(self, api_key):
        """Resolves a dot-notation api: key to a real CLI command via
        API_TO_CLI before sending, instead of blindly prefixing "show "."""
        command = API_TO_CLI.get(api_key)
        if command is None:
            msg = (f"No CLI mapping known for api key '{api_key}'. "
                   f"Add it to API_TO_CLI in connectors/aruba_conn.py.")
            print(msg)
            return False, msg
        return self.run(command)

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()

    def send_command_timing_debug(self, command, max_duration_seconds=30):
        """
        Symmetric bounded-debug method for Aruba, added for forward
        compatibility even though no current commands/aruba.yaml entry uses
        risk: read-only-debug. Mirrors CheckPointConnection's implementation:
        actually sends the command, reads until timeout or quiet, then
        interrupts (Ctrl+C) before returning so nothing is left running.
        Returns (success, output, truncated).
        """
        import time
        try:
            self.connection.write_channel(command + "\n")
            output = ""
            start_time = time.time()
            last_data_time = time.time()
            truncated = False
            while True:
                if time.time() - start_time > max_duration_seconds:
                    truncated = True
                    break
                chunk = self.connection.read_channel()
                if chunk:
                    output += chunk
                    last_data_time = time.time()
                else:
                    if output and (time.time() - last_data_time) > 1.0:
                        break
                    time.sleep(0.1)
            self.connection.write_channel("\x03")
            time.sleep(0.5)
            leftover = self.connection.read_channel()
            if leftover:
                output += leftover
            return True, output, truncated
        except Exception as e:
            print(f"Failed to execute bounded debug command '{command}' "
                  f"on {self.device.get('name')}: {e}")
            return False, str(e), True