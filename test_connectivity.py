# test_connectivity.py

import yaml
from connectors.checkpoint_conn import CheckPointConnection
from connectors.aruba_conn import ArubaConnection

def load_inventory(filepath):
    with open(filepath, 'r') as file:
        inventory = yaml.safe_load(file)
    return inventory['devices']

def test_connectivity(inventory):
    for device in inventory:
        if device['role'] == "cp-cluster-member":
            conn = CheckPointConnection(device)
        elif device['role'] == "aruba-vsx-node":
            conn = ArubaConnection(device)
        else:
            print(f"Unknown role {device['role']} for device {device['name']}")
            continue

        if conn.connect():
            print(f"Successfully connected to {device['name']}")
        else:
            print(f"Failed to connect to {device['name']}")
        
        conn.disconnect()

if __name__ == "__main__":
    inventory = load_inventory("inventory.yaml")
    test_connectivity(inventory)