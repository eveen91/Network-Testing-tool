````
# Network Validation Tool

## Prerequisites

1. **Python 3.11+**: Ensure you have Python 3.11 or later installed.
2. **Netmiko/Paramiko**: Install these libraries using pip:
   ```sh
   pip install netmiko paramiko
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
   python capture.py --ticket CHG-12345 --section 2,3,4 --params scenario_params.yaml
   ```

2. **Post-Change Baseline**:

   ```sh
   python capture.py --ticket CHG-12345 --section 2,3,4 --params scenario_params.yaml
   ```

3. **Optional Device Subset for Testing**:

   ```sh
   python capture.py --ticket CHG-12345 --section 2,3,4 --params scenario_params.yaml --devices CP-Cluster-01,Core-VSX-01
   ```

4. **Skip Manual Commands**:

   If you want to skip manual-only commands:

   ```sh
   python capture.py --ticket CHG-12345 --section 2,3,4 --params scenario_params.yaml --skip-manual
   ```

## Parameters

The scenario_params.yaml file contains parameters that will be substituted into the commands. Example:

```yaml
vlan_id: 200
subnet: "10.200.0.0/24"
vip: "10.200.0.1"
cp_member_1: "10.200.0.2"
cp_member_2: "10.200.0.3"
test_host_ip: "10.200.0.50"
dmz_db_target: "10.10.50.12"
dmz_db_port: 3306
mgmt_isolation_target: "10.0.0.15"
mgmt_isolation_port: 22
internet_target: "8.8.8.8"
```

## Manual Commands

Commands with risk: manual-only will prompt for interactive confirmation during the capture process.

## Generating Diff Report (Phase 3)

Compare Two Capture Runs:

```sh
python diff.py --left captures/CHG-12345/pre --right captures/CHG-12345/post
```

This will generate a diff_report.json file with the comparison results.

## Generating Human-Readable Summary (Phase 3)

Generate Markdown Table:

```sh
python report_summary.py --report diff_report.json
```

This will print a human-readable summary in Markdown format, which is suitable for quick skimming before further analysis.

## Troubleshooting

- **Connection Failures**: Ensure that SSH is enabled on the devices and that the IP addresses/hostnames, login credentials, and SSH keys are correct.
- **Environment Variables**: Double-check that the environment variables are set correctly in your `.env` file.

## Output Organization

The captures will be stored in the `captures/<ticket#>/<section>/<timestamp>/` directory structure. Each device's command output is saved as individual files and a consolidated file. The top-level `capture_manifest.json` contains metadata about each command execution.

### Example Directory Structure

```plaintext
captures/
├── CHG-12345/
│   ├── 2/
│   │   ├── 20230915-123045/
│   │   │   ├── device1_T-01_20230915-123045.txt
│   │   │   ├── device1_T-02_20230915-123045.txt
│   │   │   └── device1_consolidated.txt
│   │   └── capture_manifest.json
│   ├── 3/
│   │   ├── 20230915-130000/
│   │   │   ├── device1_T-06_20230915-130000.txt
│   │   │   └── device1_consolidated.txt
│   │   └── capture_manifest.json
│   └── 4/
│       ├── 20230915-140000/
│       │   ├── device1_T-16_20230915-140000.txt
│       │   └── device1_consolidated.txt
│       └── capture_manifest.json
```

### Command Library

The command library is organized in YAML files under the `commands/` directory:

- `commands/checkpoint.yaml`: Contains Section 2, 3, and 4 commands for Check Point devices.
- `commands/aruba.yaml`: Contains Section 2, 3, and 4 commands for Aruba devices.

## Architecture Overview

```plaintext
test-automation/
├── inventory.yaml              # devices, roles, connection params (NO plaintext secrets)
├── scenario_params.yaml          # parameters for command substitution
├── noise_filters.yaml            # noise filter patterns for CLI text diffing
├── commands/
│   ├── checkpoint.yaml         # command library, keyed by test ID / section
│   └── aruba.yaml
├── connectors/
│   ├── checkpoint_conn.py      # SSH session handling for Gaia clish + expert mode
│   └── aruba_conn.py           # Aruba AOS-CX (REST API preferred, CLI fallback)
├── capture.py                  # runs command set against a device, saves raw + structured output
├── diff.py                     # compares two capture runs and reports differences
├── report_summary.py             # generates human-readable summary from diff report
├── README.md                   # project documentation
└── captures/
    └── <ticket#>/2/, 3/, 4/   # timestamped raw output
```

## Project Constraints

1. **Read-Only Only**: The command library must never include configuration-changing commands.
2. **Bounded Debug Sessions**: Any Check Point debug command (fw ctl zdebug, fw monitor) must have a hard-coded timeout in the connection-handling code.
3. **No Hardcoded Credentials**: Device credentials come from environment variables or a secrets file that is git-ignored.
4. **No Auto-Remediation**: The tool observes and reports without executing corrective actions.
5. **Ticket-Scoped Captures**: Every capture is timestamped and organized by change ticket for traceability.

## Contact

If you encounter any issues or have questions, please reach out to the team.

Enjoy using your Network Validation Tool!

```

```
