import os
from dotenv import load_dotenv
from netmiko import ConnectHandler
import time

class CheckPointConnection:
    def __init__(self, device):
        self.device = device
        self.connection = None

    def connect(self):
        load_dotenv()
        password = os.getenv(self.device['password_env_var'])
        if not password and not os.path.exists(self.device['ssh_key_path']):
            raise ValueError("Credentials not found for Check Point device")

        net_device = {
            'device_type': 'checkpoint',
            'host': self.device['ip'],
            'username': self.device['login'],
            'password': password,
            'key_filename': self.device['ssh_key_path'] if os.path.exists(self.device['ssh_key_path']) else None,
        }

        try:
            self.connection = ConnectHandler(**net_device)
            # Confirm prompt
            output = self.connection.send_command_timing('show version')
            if 'Check Point' in output:
                return True
        except Exception as e:
            print(f"Failed to connect to {self.device['name']}: {e}")
            return False

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()

    def send_command_timing_debug(self, command, max_duration_seconds=30):
        try:
            output = ""
            start_time = time.time()
            while True:
                char = self.connection.read_channel()
                output += char
                end_time = time.time()
                if end_time - start_time > max_duration_seconds or not char:
                    break
            return True, output
        except Exception as e:
            print(f"Failed to execute {command}: {e}")
            return False, str(e)
