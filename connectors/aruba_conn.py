# connectors/aruba_conn.py

from netmiko import ConnectHandler
import os
from dotenv import load_dotenv

class ArubaConnection:
    def __init__(self, device):
        self.device = device
        self.connection = None

    def connect(self):
        load_dotenv()
        password = os.getenv(self.device['password_env_var'])
        if not password and not os.path.exists(self.device['ssh_key_path']):
            raise ValueError("Credentials not found for Aruba device")

        net_device = {
            'device_type': 'aruba_aoscx',
            'host': self.device['ip'],
            'username': self.device['login'],
            'password': password,
            'key_filename': self.device['ssh_key_path'] if os.path.exists(self.device['ssh_key_path']) else None,
        }

        try:
            self.connection = ConnectHandler(**net_device)
            # Confirm prompt
            output = self.connection.send_command_timing('show version')
            if 'Aruba' in output:
                return True
        except Exception as e:
            print(f"Failed to connect to {self.device['name']}: {e}")
            return False

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()