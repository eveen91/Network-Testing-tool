Sure! Below is a comprehensive `README.md` that includes all necessary information for setting up and using your Network Validation Tool.

````markdown
# Network Validation Tool

## Prerequisites

1. **Python 3.11+**: Ensure you have Python 3.11 or later installed.
2. **Netmiko/Paramiko**: Install these libraries using pip:
   ```sh
   pip install netmiko paramiko
   ```
````

3. **Dotenv**: Install the dotenv library for managing environment variables:
   ```sh
   pip install python-dotenv
   ```

## Setting Up Credentials

1. Create a `.env` file in your project root directory.
2. Add the following lines to the `.env` file, replacing placeholders with actual values for each device:

   ```sh
   CHECKPOINT_DEVICE1_PASSWORD=your_device1_password
   ARUBA_DEVICE2_PASSWORD=your_device2_password
   # Add more device-specific passwords as needed...
   ```

3. Ensure your `inventory.yaml` is correctly set up to reference these environment variables.

## Running the Connectivity Test

1. Run the connectivity test script:
   ```sh
   python test_connectivity.py
   ```

This will attempt to connect to all devices listed in the inventory and print whether each connection was successful or not.

## Baseline Capture (Phase 2)

1. **Pre-Change Baseline**:

   ```sh
   python capture.py --ticket CHG-12345 --phase pre
   ```

2. **Post-Change Baseline**:

   ```sh
   python capture.py --ticket CHG-12345 --phase post
   ```

3. **Optional Device Subset for Testing**:
   ```sh
   python capture.py --ticket CHG-12345 --phase pre --devices CP-Cluster-01,Core-VSX-01
   ```

## Troubleshooting

- **Connection Failures**: Ensure that SSH is enabled on the devices and that the IP addresses/hostnames, login credentials, and SSH keys are correct.
- **Environment Variables**: Double-check that the environment variables are set correctly in your `.env` file.

## Output Organization

The captures will be stored in the `captures/<ticket#>/<phase>/<timestamp>/` directory structure. Each device's command output is saved as individual files and a consolidated file. The top-level `capture_manifest.json` contains metadata about each command execution.

### Example Directory Structure

```
captures/
├── CHG-12345/
│   ├── pre/
│   │   ├── 20230915-123045/
│   │   │   ├── device1_BASE-CP-01_20230915-123045.txt
│   │   │   ├── device1_BASE-CP-02_20230915-123045.txt
│   │   │   └── device1_consolidated.txt
│   │   └── capture_manifest.json
│   └── post/
│       ├── 20230915-130000/
│       │   ├── device1_BASE-CP-01_20230915-130000.txt
│       │   ├── device1_BASE-CP-02_20230915-130000.txt
│       │   └── device1_consolidated.txt
│       └── capture_manifest.json
```

### Command Library

The command library is organized in YAML files under the `commands/` directory:

- `commands/checkpoint.yaml`: Contains Section 1 commands for Check Point devices.
- `commands/aruba.yaml`: Contains Section 1 commands for Aruba devices.

## Architecture Overview

```
test-automation/
├── inventory.yaml              # devices, roles, connection params (NO plaintext secrets)
├── commands/
│   ├── checkpoint.yaml         # command library, keyed by test ID / section
│   └── aruba.yaml
├── connectors/
│   ├── checkpoint_conn.py      # SSH session handling for Gaia clish + expert mode
│   └── aruba_conn.py           # Aruba AOS-CX (REST API preferred, CLI fallback)
├── capture.py                  # runs command set against a device, saves raw + structured output
├── README.md                   # project documentation
└── captures/
    └── <ticket#>/pre/, post/   # timestamped raw output
```

## Project Constraints

1. **Read-Only Only**: The command library must never include configuration-changing commands.
2. **Bounded Debug Sessions**: Any Check Point debug command (fw ctl zdebug, fw monitor) must have a hard-coded timeout in the connection-handling code.
3. **No Hardcoded Credentials**: Device credentials come from environment variables or a secrets file that is git-ignored.
4. **No Auto-Remediation**: The tool observes and reports without executing corrective actions.
5. **Ticket-Scoped Captures**: Every capture is timestamped and organized by change ticket for traceability.

## Contact

If you encounter any issues or have questions, please reach out to the team at [email@example.com].

Enjoy using your Network Validation Tool!

```

Save this content to the `README.md` file in your project directory. This README now provides comprehensive instructions for setting up and using your network validation tool.
```
