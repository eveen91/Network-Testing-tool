import os
import re
import json
import time
import yaml
import requests
from datetime import datetime

from connectors.checkpoint_conn import CheckPointConnection
from connectors.aruba_conn import ArubaConnection


def load_config(filepath):
    with open(filepath, 'r') as file:
        return yaml.safe_load(file)


# --------------------------------------------------------------------------
# Alerting + audit trail (step 9.5)
# --------------------------------------------------------------------------

def send_alert(ticket_number, trigger_name, device, check_output, timestamp, webhook_url=None):
    """
    Sends an alert via webhook if configured, otherwise falls back to a
    local terminal bell + highlighted console line. Either way, the alert
    is ALSO always appended to triggers.log -- the console/webhook is the
    real-time notification, triggers.log is the durable record.
    """
    alert_message = {
        "ticket_number": ticket_number,
        "trigger_name": trigger_name,
        "device": device,
        "check_output": check_output,
        "timestamp": timestamp
    }

    if webhook_url:
        try:
            response = requests.post(webhook_url, json=alert_message, timeout=10)
            if response.status_code != 200:
                print(f"Failed to send alert via webhook (status {response.status_code}): {response.text}")
        except Exception as e:
            print(f"Error sending alert via webhook: {e}")
    else:
        print("\a")
        print(f"ALERT! Ticket: {ticket_number} | Trigger: {trigger_name} | Device: {device}")
        print(f"  Check Output: {check_output}")
        print(f"  Timestamp: {timestamp}")

    with open("triggers.log", 'a') as f:
        f.write(json.dumps(alert_message) + "\n")

    return alert_message


def log_audit_cycle(ticket_number, cycle_record, log_dir="monitor_logs"):
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{ticket_number}_monitor.log")
    with open(log_path, 'a') as f:
        f.write(json.dumps(cycle_record) + "\n")
    return log_path


# --------------------------------------------------------------------------
# Stateless checks (step 9.2)
# --------------------------------------------------------------------------

def check_cp_sync_errors(raw_output, sync_error_pattern=r'(?i)not sync|sync error|collision|lagging|never sync'):
    if re.search(sync_error_pattern, raw_output):
        return True, f"cphaprob syncstat matched sync-error pattern: {raw_output[:300]!r}"
    return False, "no sync error pattern matched"


def check_vsx_sync_status(raw_output):
    text = raw_output.lower()
    if "in-sync" in text or "in sync" in text:
        return False, "config-sync in-sync"
    return True, f"VSX config-sync not confirmed in-sync: {raw_output[:300]!r}"


def check_packet_loss_on_new_vip(raw_ping_output, loss_threshold_pct=0.5):
    match = re.search(r'(\d+(?:\.\d+)?)\s*%\s*(?:packet\s*)?loss', raw_ping_output, re.IGNORECASE)
    if not match:
        return False, "could not parse packet loss percentage from ping output"
    loss_pct = float(match.group(1))
    if loss_pct > loss_threshold_pct:
        return True, f"packet loss {loss_pct}% exceeds threshold {loss_threshold_pct}%"
    return False, f"packet loss {loss_pct}%, within threshold"


# --------------------------------------------------------------------------
# Stateful checks (step 9.3)
# --------------------------------------------------------------------------

def check_bgp_ospf_neighbors(device_name, bgp_output, ospf_output, state,
                              down_threshold_seconds=180, now=None):
    now = now if now is not None else time.time()
    established_count = len(re.findall(r'\bEstablished\b', bgp_output or ""))
    full_count = len(re.findall(r'\bFULL\b', ospf_output or "", re.IGNORECASE))
    current_total = established_count + full_count

    history = state.setdefault("neighbor_counts", {})
    device_state = history.get(device_name, {"max_seen": current_total, "first_drop_time": None})
    baseline = device_state["max_seen"]
    first_drop_time = device_state["first_drop_time"]

    triggers = []

    if current_total < baseline:
        if first_drop_time is None:
            first_drop_time = now
        elapsed = now - first_drop_time
        if elapsed >= down_threshold_seconds:
            triggers.append((
                "BGP/OSPF neighbor loss",
                f"{device_name}: peer count dropped from {baseline} to {current_total} "
                f"and has not recovered for {int(elapsed)}s (threshold {down_threshold_seconds}s)"
            ))
    else:
        first_drop_time = None
        baseline = max(baseline, current_total)

    history[device_name] = {"max_seen": baseline, "first_drop_time": first_drop_time}
    return triggers


def check_interface_error_spike(device_name, raw_output, state, error_delta_threshold=50):
    error_numbers = [int(n) for n in re.findall(r'(?:CRC|error|drop)\D{0,10}?(\d+)', raw_output, re.IGNORECASE)]
    current_total = sum(error_numbers)

    baselines = state.setdefault("interface_error_baseline", {})
    if device_name not in baselines:
        baselines[device_name] = current_total
        return False, f"baseline established: {current_total} cumulative errors"

    delta = current_total - baselines[device_name]
    if delta > error_delta_threshold:
        return True, f"interface error count increased by {delta} since monitoring started (threshold {error_delta_threshold})"
    return False, f"error delta {delta}, within threshold"


# --------------------------------------------------------------------------
# Split-brain / flapping (step 9.4)
# --------------------------------------------------------------------------

def _extract_own_state(raw_output):
    for line in raw_output.splitlines():
        if "(local)" in line.lower():
            if re.search(r'\bactive\b', line, re.IGNORECASE):
                return "active"
            if re.search(r'\bstandby\b', line, re.IGNORECASE):
                return "standby"
            if re.search(r'\bdown\b', line, re.IGNORECASE):
                return "down"

    text = raw_output.lower()
    if re.search(r'\bdown\b|\bproblem\b', text):
        return "down"
    if re.search(r'\bactive\b', text):
        return "active"
    if re.search(r'\bstandby\b', text):
        return "standby"
    return "unknown"


def check_clusterxl_split_brain(cp_outputs, state, flap_window_seconds=120,
                                 flap_count_threshold=2, now=None):
    now = now if now is not None else time.time()
    own_states = {}

    for device_name, raw in cp_outputs.items():
        own_state = _extract_own_state(raw)
        own_states[device_name] = own_state

        history = state.setdefault("cp_state_history", {}).setdefault(device_name, [])
        if not history or history[-1][1] != own_state:
            history.append((now, own_state))
        state["cp_state_history"][device_name] = [
            (t, label) for (t, label) in history if now - t <= flap_window_seconds
        ]

    triggers = []
    active_devices = [d for d, s in own_states.items() if s == "active"]
    down_devices = [d for d, s in own_states.items() if s == "down"]

    if len(active_devices) > 1:
        triggers.append((
            "ClusterXL split-brain",
            f"Multiple members report themselves as Active simultaneously: {active_devices}"
        ))

    if down_devices and len(down_devices) == len(cp_outputs):
        triggers.append((
            "ClusterXL all members down",
            f"All CP cluster members report Down/problem: {down_devices}"
        ))

    for device_name, history in state.get("cp_state_history", {}).items():
        if len(history) > flap_count_threshold:
            triggers.append((
                "ClusterXL state flapping",
                f"{device_name} changed state {len(history)} times in the last "
                f"{flap_window_seconds}s: {[label for _, label in history]}"
            ))

    return triggers


# --------------------------------------------------------------------------
# Bounded debug check (step 9.5)
# --------------------------------------------------------------------------

def check_asymmetric_routing_burst(conn, max_duration_seconds=10,
                                    fail_pattern=r"(?i)out of state|first packet (is not|isn'?t) syn"):
    success, output, truncated = conn.send_command_timing_debug(
        'fw ctl zdebug + drop | grep -iE "out of state|first packet is not syn"',
        max_duration_seconds=max_duration_seconds,
        mode="expert",
    )
    if not success:
        return False, f"debug capture failed to run: {output}"

    detail_suffix = " (capture was time-bounded and may be truncated)" if truncated else ""

    if re.search(fail_pattern, output):
        return True, f"asymmetric routing / out-of-state drops detected{detail_suffix}: {output[:300]!r}"
    return False, f"no out-of-state/asymmetric-routing drops observed in bounded capture{detail_suffix}"


# --------------------------------------------------------------------------
# Step 9.6: integration -- one polling cycle, fully testable in isolation
# --------------------------------------------------------------------------

def poll_once(ticket_number, config, state, last_asym_check, now=None,
              connector_factory=None):
    """
    Runs exactly one polling cycle across all configured devices, applies
    every check, sends alerts for anything that trips, and writes one
    audit-trail record. Returns the updated `last_asym_check` timestamp.

    Split out from main()'s infinite loop specifically so it can be called
    repeatedly with controlled `now` values and mock connectors in tests,
    without needing a real event loop or real time.sleep().

    `connector_factory(device_dict) -> connector instance` defaults to the
    real CheckPointConnection/ArubaConnection classes, but tests can inject
    mocks here.
    """
    now = now if now is not None else time.time()
    devices = config["devices"]
    webhook_url = config.get("webhook_url") or None
    vip = config.get("vip")
    thresholds = config.get("thresholds", {})
    asym_interval = config.get("asymmetric_routing_burst_interval_seconds", 300)
    asym_max_duration = config.get("asymmetric_routing_burst_max_duration_seconds", 10)

    def default_factory(device):
        if device["role"] == "cp-cluster-member":
            return CheckPointConnection(device)
        elif device["role"] == "aruba-vsx-node":
            return ArubaConnection(device)
        return None

    factory = connector_factory or default_factory

    cp_outputs = {}
    cycle_record = {"timestamp": datetime.fromtimestamp(now).isoformat(), "devices": {}}
    run_asym_this_cycle = (now - last_asym_check) >= asym_interval

    for device in devices:
        device_name = device["name"]
        cycle_record["devices"][device_name] = {}

        try:
            conn = factory(device)
            if conn is None:
                print(f"Unknown role for device {device_name}")
                continue

            if not conn.connect():
                # Device unreachability IS the "loss of management access"
                # trigger itself, not a failure to swallow silently.
                send_alert(ticket_number, "Loss of Management Access", device_name,
                           "Failed to connect", cycle_record["timestamp"], webhook_url)
                cycle_record["devices"][device_name]["connection_status"] = "failed to connect"
                continue

            cycle_record["devices"][device_name]["connection_status"] = "connected"

            if device["role"] == "cp-cluster-member":
                _, cphaprob_out = conn.run("cphaprob stat", mode="expert")
                _, syncstat_out = conn.run("cphaprob syncstat", mode="expert")
                cp_outputs[device_name] = cphaprob_out
                cycle_record["devices"][device_name]["cphaprob_stat"] = cphaprob_out
                cycle_record["devices"][device_name]["syncstat"] = syncstat_out

                sync_triggered, sync_detail = check_cp_sync_errors(syncstat_out)
                if sync_triggered:
                    send_alert(ticket_number, "CP sync error", device_name, sync_detail,
                               cycle_record["timestamp"], webhook_url)

                if run_asym_this_cycle:
                    asym_triggered, asym_detail = check_asymmetric_routing_burst(
                        conn, max_duration_seconds=asym_max_duration
                    )
                    cycle_record["devices"][device_name]["asymmetric_routing_check"] = asym_detail
                    if asym_triggered:
                        send_alert(ticket_number, "Asymmetric routing / kernel drops", device_name,
                                   asym_detail, cycle_record["timestamp"], webhook_url)

            elif device["role"] == "aruba-vsx-node":
                _, bgp_out = conn.run("show bgp all summary")
                _, ospf_out = conn.run("show ip ospf neighbor")
                _, vsx_out = conn.run("show vsx status config-sync")
                _, iface_out = conn.run("show interface error-statistics")
                cycle_record["devices"][device_name].update({
                    "bgp_summary": bgp_out, "ospf_neighbors": ospf_out,
                    "vsx_config_sync": vsx_out, "interface_errors": iface_out,
                })

                for trig_name, detail in check_bgp_ospf_neighbors(
                    device_name, bgp_out, ospf_out, state,
                    down_threshold_seconds=thresholds.get("neighbor_loss_grace_seconds", 180), now=now
                ):
                    send_alert(ticket_number, trig_name, device_name, detail, cycle_record["timestamp"], webhook_url)

                vsx_triggered, vsx_detail = check_vsx_sync_status(vsx_out)
                if vsx_triggered:
                    send_alert(ticket_number, "VSX out-of-sync", device_name, vsx_detail,
                               cycle_record["timestamp"], webhook_url)

                iface_triggered, iface_detail = check_interface_error_spike(
                    device_name, iface_out, state,
                    error_delta_threshold=thresholds.get("interface_error_delta_threshold", 50)
                )
                if iface_triggered:
                    send_alert(ticket_number, "Interface error spike", device_name, iface_detail,
                               cycle_record["timestamp"], webhook_url)

                if vip:
                    _, ping_out = conn.run(f"ping {vip} repetitions 5")
                    cycle_record["devices"][device_name]["vip_ping"] = ping_out
                    loss_triggered, loss_detail = check_packet_loss_on_new_vip(
                        ping_out, loss_threshold_pct=thresholds.get("vip_packet_loss_pct_threshold", 0.5)
                    )
                    if loss_triggered:
                        send_alert(ticket_number, "Packet loss on new VIP", device_name, loss_detail,
                                   cycle_record["timestamp"], webhook_url)

            conn.disconnect()

        except Exception as e:
            print(f"Error processing {device_name}: {e}")
            cycle_record["devices"][device_name]["error"] = str(e)

    # Cross-device split-brain/flapping analysis needs all CP outputs from
    # this cycle at once -- this is why it happens after the device loop,
    # not inside it.
    if cp_outputs:
        flap_thresholds = config.get("thresholds", {})
        for trig_name, detail in check_clusterxl_split_brain(
            cp_outputs, state,
            flap_window_seconds=flap_thresholds.get("clusterxl_flap_window_seconds", 120),
            flap_count_threshold=flap_thresholds.get("clusterxl_flap_max_changes", 2),
            now=now,
        ):
            send_alert(ticket_number, trig_name, ",".join(cp_outputs.keys()), detail,
                       cycle_record["timestamp"], webhook_url)

    if run_asym_this_cycle:
        last_asym_check = now

    log_audit_cycle(ticket_number, cycle_record)
    return last_asym_check


def main(ticket_number, config_file):
    config = load_config(config_file)
    interval = config.get("interval", 60)
    if interval < 10:
        print(f"WARNING: poll interval of {interval}s is aggressive for control-plane "
              f"polling during a live change window. Recommended minimum is 30s.")

    print("Automated checks in this monitor: ClusterXL split-brain/flapping, CP sync errors, "
          "BGP/OSPF neighbor loss, VSX out-of-sync, interface error spike (delta-based proxy), "
          "VIP packet loss, asymmetric-routing kernel drops (bounded, own interval), and loss of "
          "management access.")
    print("NOT automated by this tool (per the Test Plan, these stay manual): throughput "
          "degradation, security policy bypass (SmartConsole log review), global policy push "
          "failure, and the maintenance-window time-limit trigger -- set a personal timer for that one.")
    print("This monitor NEVER takes corrective action. It only alerts. Rollback is always a human decision.")

    state = {}
    last_asym_check = 0.0

    while True:
        last_asym_check = poll_once(ticket_number, config, state, last_asym_check)
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Live-monitor abort-criteria triggers during a change window.")
    parser.add_argument("--ticket", required=True, help="Ticket number (e.g., CHG-12345)")
    parser.add_argument("--config", required=True, help="Path to monitor_thresholds.yaml file")

    args = parser.parse_args()
    main(args.ticket, args.config)