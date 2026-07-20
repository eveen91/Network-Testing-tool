# Network Validation Tool Connectivity Test

## Prerequisites

1. **Python 3.11+**: Ensure you have Python 3.11 or later installed.
2. **Netmiko/Paramiko**: Install these libraries using pip:
   ```sh
   pip install netmiko paramiko
   ```
3. **Dotenv**: Install the dotenv library for managing environment variables:
   ```sh
   pip install python-dotenv
   ```

## Setting Up Credentials

1. Create a `.env` file in your project root directory.
2. Add the following lines to the `.env` file, replacing placeholders with actual values:
   ```sh
   CHECKPOINT_PASSWORD=your_checkpoint_password
   ARUBA_PASSWORD=your_aruba_password
   ```

## Running the Connectivity Test

1. Ensure your `inventory.yaml` is correctly set up as described above.
2. Run the connectivity test script:
   ```sh
   python test_connectivity.py
   ```

This will attempt to connect to all devices listed in the inventory and print whether each connection was successful or not.

## Troubleshooting

- **Connection Failures**: Ensure that SSH is enabled on the devices and that the IP addresses/hostnames, login credentials, and SSH keys are correct.
- **Environment Variables**: Double-check that the environment variables are set correctly in your `.env` file.
