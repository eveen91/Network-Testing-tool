import os
import json
import re
import glob
from difflib import unified_diff

import yaml


def find_latest_run_dir(ticket, phase):
    """
    Picks the most recent captures/<ticket>/<phase>/<timestamp>/ directory.
    Timestamp format (YYYYMMDD-HHMMSS) sorts correctly as a plain string.
    """
    pattern = os.path.join("captures", ticket, phase, "*")
    candidates = [
        d for d in glob.glob(pattern)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "capture_manifest.json"))
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No completed capture run found for ticket='{ticket}' phase='{phase}' "
            f"(looked under {pattern})"
        )
    return sorted(candidates)[-1]


def load_manifest(run_dir):
    manifest_path = os.path.join(run_dir, "capture_manifest.json")
    with open(manifest_path, 'r') as file:
        return json.load(file)


def load_noise_filters(filepath="noise_filters.yaml"):
    if not os.path.exists(filepath):
        return {"global": [], "per_command": {}}
    with open(filepath, 'r') as file:
        data = yaml.safe_load(file) or {}
    return {
        "global": data.get("global", []) or [],
        "per_command": data.get("per_command", {}) or {},
    }


def noise_patterns_for(test_id, noise_filters):
    """
    FIX: the previous version did
        noise_patterns = noise_filters['global']
        noise_patterns.extend(per_command_patterns)
    which takes a REFERENCE to the global list and mutates it in place on
    every loop iteration -- so patterns from test #1 leaked into every
    subsequent test's filtering. This returns a fresh list every call.
    """
    global_patterns = list(noise_filters.get("global", []))
    per_command_patterns = list(noise_filters.get("per_command", {}).get(test_id, []))
    return global_patterns + per_command_patterns


def filter_noise(text, patterns):
    for pattern in patterns:
        text = re.sub(pattern, '', text)
    return text.strip()


def unified_text_diff(left_text, right_text, ignore_patterns):
    left_filtered = filter_noise(left_text, ignore_patterns)
    right_filtered = filter_noise(right_text, ignore_patterns)

    if left_filtered == right_filtered:
        return []

    return list(unified_diff(
        left_filtered.splitlines(), right_filtered.splitlines(),
        fromfile="pre", tofile="post", lineterm=""
    ))


def is_structured_capture(capture_file):
    return capture_file.endswith('.json')


def structured_json_diff(left_json, right_json):
    changes = []

    def compare_dicts(d1, d2, path=''):
        for key in sorted(set(d1.keys()).union(set(d2.keys()))):
            current_path = f"{path}.{key}" if path else key
            v1, v2 = d1.get(key), d2.get(key)
            if isinstance(v1, dict) and isinstance(v2, dict):
                compare_dicts(v1, v2, current_path)
            elif isinstance(v1, list) and isinstance(v2, list):
                compare_lists(v1, v2, current_path)
            elif v1 != v2:
                changes.append({"field": current_path, "before": v1, "after": v2})

    def compare_lists(l1, l2, path=''):
        for i in range(max(len(l1), len(l2))):
            if i < len(l1) and i < len(l2):
                if isinstance(l1[i], dict) and isinstance(l2[i], dict):
                    compare_dicts(l1[i], l2[i], f"{path}[{i}]")
                elif l1[i] != l2[i]:
                    changes.append({"field": f"{path}[{i}]", "before": l1[i], "after": l2[i]})
            elif i < len(l1):
                changes.append({"field": f"{path}[{i}]", "before": l1[i], "after": None})
            else:
                changes.append({"field": f"{path}[{i}]", "before": None, "after": l2[i]})

    compare_dicts(left_json, right_json)
    return changes


def load_capture(capture_path):
    with open(capture_path, 'r') as file:
        if capture_path.endswith('.json'):
            return json.load(file)
        return file.read()


def generate_diff_report(pre_run_dir, post_run_dir, noise_filters):
    """
    Rewritten against the new per-device manifest schema (capture.py fix
    #5). Device names and roles now come directly from each manifest's own
    per_device keys instead of a broken external inventory.yaml lookup, and
    per-command file lookup uses the manifest's exact output_file field
    instead of a glob pattern that could never match.
    """
    diff_report = []
    pre_manifest = load_manifest(pre_run_dir)
    post_manifest = load_manifest(post_run_dir)

    pre_devices = pre_manifest.get("per_device", {})
    post_devices = post_manifest.get("per_device", {})
    all_device_names = sorted(set(pre_devices.keys()) | set(post_devices.keys()))

    for device_name in all_device_names:
        pre_device = pre_devices.get(device_name)
        post_device = post_devices.get(device_name)

        if pre_device is None or post_device is None:
            diff_report.append({
                "device": device_name, "test_id": None, "comparison_type": None,
                "status": "only-in-pre" if post_device is None else "only-in-post",
                "changes": [], "caveats": ["device missing from one of the two runs entirely"]
            })
            continue

        pre_commands = pre_device.get("commands", {})
        post_commands = post_device.get("commands", {})
        all_test_ids = sorted(set(pre_commands.keys()) | set(post_commands.keys()))

        for test_id in all_test_ids:
            pre_cmd = pre_commands.get(test_id)
            post_cmd = post_commands.get(test_id)

            if pre_cmd is None or post_cmd is None:
                diff_report.append({
                    "device": device_name, "test_id": test_id, "comparison_type": None,
                    "status": "only-in-pre" if post_cmd is None else "only-in-post",
                    "changes": [], "caveats": []
                })
                continue

            caveats = []

            if "output_file" not in pre_cmd or "output_file" not in post_cmd:
                diff_report.append({
                    "device": device_name, "test_id": test_id, "comparison_type": None,
                    "status": "not-diffable-manual",
                    "changes": [],
                    "caveats": [
                        f"pre: {pre_cmd.get('status', 'unknown')}"
                        + (f" -- {pre_cmd['notes']}" if pre_cmd.get("notes") else ""),
                        f"post: {post_cmd.get('status', 'unknown')}"
                        + (f" -- {post_cmd['notes']}" if post_cmd.get("notes") else ""),
                    ]
                })
                continue

            if pre_cmd.get("truncated") or post_cmd.get("truncated"):
                caveats.append(
                    "debug-capture-caveat: one or both captures were time-bounded and may "
                    "be truncated -- not a reliable basis for 'nothing changed' on its own"
                )

            if pre_cmd.get("status") != "captured successfully" or post_cmd.get("status") != "captured successfully":
                caveats.append(
                    f"capture status: pre='{pre_cmd.get('status')}', post='{post_cmd.get('status')}'"
                )

            pre_path = os.path.join(pre_run_dir, device_name, pre_cmd["output_file"])
            post_path = os.path.join(post_run_dir, device_name, post_cmd["output_file"])

            if not os.path.exists(pre_path) or not os.path.exists(post_path):
                diff_report.append({
                    "device": device_name, "test_id": test_id, "comparison_type": None,
                    "status": "capture-file-missing",
                    "changes": [],
                    "caveats": caveats + ["manifest referenced an output file that doesn't exist on disk"]
                })
                continue

            patterns = noise_patterns_for(test_id, noise_filters)

            if is_structured_capture(pre_path) and is_structured_capture(post_path):
                comparison_type = "structured"
                changes = structured_json_diff(load_capture(pre_path), load_capture(post_path))
            else:
                comparison_type = "text"
                diff_lines = unified_text_diff(load_capture(pre_path), load_capture(post_path), patterns)
                changes = [{"diff": "\n".join(diff_lines)}] if diff_lines else []

            status = "changed" if changes else "unchanged"

            diff_report.append({
                "device": device_name,
                "test_id": test_id,
                "comparison_type": comparison_type,
                "status": status,
                "changes": changes,
                "caveats": caveats,
            })

    return diff_report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate a diff report between two capture runs.")
    parser.add_argument("--ticket", required=False, help="Ticket number -- auto-resolves latest pre/post run")
    parser.add_argument("--pre-phase", default="pre", help="Phase name to treat as 'pre' (default: pre)")
    parser.add_argument("--post-phase", default="post", help="Phase name to treat as 'post' (default: post)")
    parser.add_argument("--left", required=False, help="Explicit path to a pre-change run directory")
    parser.add_argument("--right", required=False, help="Explicit path to a post-change run directory")
    parser.add_argument("--output", default="diff_report.json", help="Output path for the diff report")

    args = parser.parse_args()

    if args.left and args.right:
        pre_run_dir, post_run_dir = args.left, args.right
    elif args.ticket:
        pre_run_dir = find_latest_run_dir(args.ticket, args.pre_phase)
        post_run_dir = find_latest_run_dir(args.ticket, args.post_phase)
    else:
        parser.error("Provide either --ticket, or both --left and --right")

    print(f"Comparing:\n  pre:  {pre_run_dir}\n  post: {post_run_dir}")

    noise_filters = load_noise_filters("noise_filters.yaml")
    diff_report = generate_diff_report(pre_run_dir, post_run_dir, noise_filters)

    with open(args.output, 'w') as file:
        json.dump(diff_report, file, indent=4)

    print(f"Diff report generated. Saved to {args.output}")