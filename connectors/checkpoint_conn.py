import os
import time
from dotenv import load_dotenv
from netmiko import ConnectHandler


class CheckPointConnection:
    """
    SSH connector for Check Point Gaia (ClusterXL).

    Fix log:
      - #1: device_type corrected from the invalid 'checkpoint' to the real
        Netmiko-supported 'checkpoint_gaia'.
      - #1: added real expert-mode elevation. Gaia drops you into clish by
        default; most commands in commands/checkpoint.yaml (cphaprob, fw,
        cplic, cpstat, etc.) only work in expert (bash) mode. We elevate once
        per session and remember whether we're in expert mode so we don't
        re-elevate every command.
      - #2: send_command_timing_debug now actually WRITES the command to the
        channel before reading, and explicitly sends Ctrl+C to kill the
        remote process when the timeout is hit -- it no longer just polls an
        empty buffer and returns instantly.
    """

    def __init__(self, device):
        self.device = device
        self.connection = None
        self.in_expert_mode = False

    def connect(self):
        load_dotenv()
        password = os.getenv(self.device["password_env_var"])
        ssh_key_path = os.path.expanduser(self.device.get("ssh_key_path", "") or "")
        key_exists = bool(ssh_key_path) and os.path.exists(ssh_key_path)

        if not password and not key_exists:
            raise ValueError(
                f"Credentials not found for Check Point device {self.device.get('name')}: "
                f"no password in ${self.device['password_env_var']} and no SSH key at "
                f"{ssh_key_path or '(not set)'}"
            )

        net_device = {
            "device_type": "checkpoint_gaia",  # FIX #1: was the invalid 'checkpoint'
            "host": self.device["ip"],
            "username": self.device["login"],
            "password": password,
            "key_file": ssh_key_path if key_exists else None,
        }

        try:
            self.connection = ConnectHandler(**net_device)
            output = self.connection.send_command_timing("show version all")
            if "version" not in output.lower() and "gaia" not in output.lower():
                print(f"[{self.device.get('name')}] Connected, but 'show version all' "
                      f"output was unexpected: {output[:200]!r}")
            return True
        except Exception as e:
            print(f"Failed to connect to {self.device.get('name')}: {e}")
            self.connection = None
            return False

    def _enter_expert_mode(self):
        """Elevate to expert (bash) mode. Required for most commands in the library."""
        if self.in_expert_mode:
            return True

        expert_password = os.getenv(
            self.device.get("expert_password_env_var", ""), None
        )
        if not expert_password:
            raise ValueError(
                f"Expert-mode password not found for {self.device.get('name')}. "
                f"Set env var referenced by 'expert_password_env_var' in inventory.yaml."
            )

        self.connection.write_channel("expert\n")
        time.sleep(0.5)
        prompt_output = self.connection.read_channel()

        if "password" in prompt_output.lower():
            self.connection.write_channel(expert_password + "\n")
            time.sleep(0.5)
            result = self.connection.read_channel()
            if "wrong" in result.lower() or "incorrect" in result.lower():
                raise ValueError(f"Expert-mode password rejected for {self.device.get('name')}")

        self.in_expert_mode = True
        return True

    def run(self, command, mode="clish"):
        """
        Execute a single non-debug command in the requested mode.
        Returns (success: bool, output: str).
        """
        try:
            if mode == "expert":
                self._enter_expert_mode()
            output = self.connection.send_command_timing(command)
            return True, output
        except Exception as e:
            print(f"Failed to execute '{command}' on {self.device.get('name')}: {e}")
            return False, str(e)

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()

    def send_command_timing_debug(self, command, max_duration_seconds=30, mode="expert"):
        """
        FIX #2: bounded debug execution.

        Previous version never sent `command` to the device at all -- it just
        polled read_channel() in a loop, which returned empty immediately and
        exited the loop on the first read. This version:
          1. actually elevates to expert mode if requested (debug commands
             like `fw ctl zdebug` / `fw monitor` require it),
          2. actually writes the command to the channel,
          3. reads output until either max_duration_seconds elapses or the
             channel goes quiet for a full second,
          4. sends Ctrl+C to terminate the remote process before returning,
             so a debug filter is never left running on the device after
             this function returns.

        Returns (success: bool, output: str, truncated: bool)
        """
        try:
            if mode == "expert":
                self._enter_expert_mode()

            self.connection.write_channel(command + "\n")

            output = ""
            start_time = time.time()
            last_data_time = time.time()
            truncated = False

            while True:
                elapsed = time.time() - start_time
                if elapsed > max_duration_seconds:
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

            self.connection.write_channel("\x03")  # Ctrl+C
            time.sleep(0.5)
            leftover = self.connection.read_channel()
            if leftover:
                output += leftover

            return True, output, truncated

        except Exception as e:
            print(f"Failed to execute bounded debug command '{command}' "
                  f"on {self.device.get('name')}: {e}")
            return False, str(e), True