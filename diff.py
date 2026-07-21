import os
import json
import re
from difflib import unified_diff
import yaml
import glob

def load_inventory(filepath):
    with open(filepath, 'r') as file:
        inventory = yaml.safe_load(file)
    return inventory['devices']

def load_commands(manifest_path):
    manifest_data = {}
    with open(manifest_path, 'r') as file:
        manifest = json.load(file)
    for device in manifest.get('per_device', {}).values():
        if 'connection_status' not in device or device['connection_status'] != 'connected':
            continue
        for command in manifest.get('per_command', {}):
            if manifest['per_command'][command]['status'] == 'captured successfully':
                manifest_data[command] = manifest['per_command'][command]
    return manifest_data

def is_structured_capture(capture_file):
    return capture_file.endswith('.json')

def load_noise_filters(filepath):
    with open(filepath, 'r') as file:
        noise_filters = yaml.safe_load(file)
    return noise_filters

def filter_noise(text, patterns):
    for pattern in patterns:
        text = re.sub(pattern, '', text)
    return text.strip()  # Remove leading/trailing whitespace

def unified_text_diff(left_text, right_text, ignore_patterns):
    left_filtered = filter_noise(left_text, ignore_patterns)
    right_filtered = filter_noise(right_text, ignore_patterns)
    
    if left_filtered == "" and right_filtered == "":
        return ""
    
    diff = list(unified_diff(left_filtered.splitlines(), right_filtered.splitlines()))
    return '\n'.join(diff)

def structured_json_diff(left_json, right_json):
    changes = []

    def compare_dicts(d1, d2, path=''):
        for key in sorted(set(d1.keys()).union(set(d2.keys()))):
            current_path = f"{path}.{key}" if path else key
            v1 = d1.get(key)
            v2 = d2.get(key)

            if isinstance(v1, dict) and isinstance(v2, dict):
                changes.extend(compare_dicts(v1, v2, current_path))
            elif isinstance(v1, list) and isinstance(v2, list):
                changes.extend(compare_lists(v1, v2, current_path))
            else:
                if v1 != v2:
                    changes.append({"field": current_path, "before": v1, "after": v2})
        return changes

    def compare_lists(l1, l2, path=''):
        for i in range(max(len(l1), len(l2))):
            if i < len(l1) and i < len(l2):
                if isinstance(l1[i], dict) and isinstance(l2[i], dict):
                    changes.extend(compare_dicts(l1[i], l2[i], f"{path}[{i}]"))
                else:
                    if l1[i] != l2[i]:
                        changes.append({"field": f"{path}[{i}]", "before": l1[i], "after": l2[i]})
            elif i < len(l1):
                changes.append({"field": f"{path}[{i}]", "before": l1[i], "after": None})
            else:
                changes.append({"field": f"{path}[{i}]", "before": None, "after": l2[i]})
        return changes

    return compare_dicts(left_json, right_json)

def generate_diff_report(pre_capture_dir, post_capture_dir, pre_manifest_path, post_manifest_path, noise_filters):
    diff_report = []
    
    pre_inventory = load_inventory(os.path.join(pre_capture_dir, "..", "inventory.yaml"))
    post_inventory = load_inventory(os.path.join(post_capture_dir, "..", "inventory.yaml"))

    for device in pre_inventory:
        device_name = device['name']
        pre_device_dir = os.path.join(pre_capture_dir, device_name)
        post_device_dir = os.path.join(post_capture_dir, device_name)

        if not os.path.exists(pre_device_dir) or not os.path.exists(post_device_dir):
            continue

        pre_commands = load_commands(os.path.join(pre_manifest_path))
        post_commands = load_commands(os.path.join(post_manifest_path))

        all_test_ids = set(pre_commands.keys()).union(set(post_commands.keys()))

        for test_id in all_test_ids:
            pre_command = pre_commands.get(test_id)
            post_command = post_commands.get(test_id)

            if not pre_command or not post_command:
                status = "only-in-pre" if not post_command else "only-in-post"
                diff_report.append({
                    "device": device_name,
                    "test_id": test_id,
                    "comparison_type": None,
                    "status": status,
                    "changes": [],
                    "caveats": []
                })
                continue

            pre_capture_paths = glob.glob(os.path.join(pre_device_dir, f"{test_id}_*.txt"))
            post_capture_paths = glob.glob(os.path.join(post_device_dir, f"{test_id}_*.txt"))

            if not pre_capture_paths or not post_capture_paths:
                continue

            pre_capture_path = pre_capture_paths[0]
            post_capture_path = post_capture_paths[0]

            noise_patterns = noise_filters['global']
            per_command_patterns = noise_filters['per_command'].get(test_id, [])
            noise_patterns.extend(per_command_patterns)

            if is_structured_capture(pre_capture_path) and is_structured_capture(post_capture_path):
                pre_json = load_capture(pre_capture_path)
                post_json = load_capture(post_capture_path)
                comparison_type = "structured"
                changes = structured_json_diff(pre_json, post_json)
            else:
                pre_text = load_capture(pre_capture_path)
                post_text = load_capture(post_capture_path)
                comparison_type = "text"
                changes_content = unified_text_diff(pre_text, post_text, noise_patterns)
                if changes_content.strip():
                    changes = [{"diff": changes_content}]
                else:
                    changes = []

            status = "changed" if changes else "unchanged"

            diff_report.append({
                "device": device_name,
                "test_id": test_id,
                "comparison_type": comparison_type,
                "status": status,
                "changes": changes,
                "caveats": []
            })

    return diff_report

def load_capture(capture_path):
    with open(capture_path, 'r') as file:
        if capture_path.endswith('.json'):
            return json.load(file)
        else:
            return file.read()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate a diff report between two capture runs.")
    parser.add_argument("--left", required=True, help="Left capture directory")
    parser.add_argument("--right", required=True, help="Right capture directory")

    args = parser.parse_args()

    noise_filters = load_noise_filters("noise_filters.yaml")

    diff_report = generate_diff_report(args.left, args.right, os.path.join(args.left, "capture_manifest.json"), os.path.join(args.right, "capture_manifest.json"), noise_filters)

    with open("diff_report.json", 'w') as file:
        json.dump(diff_report, file, indent=4)

    print(f"Diff report generated. Saved to diff_report.json")
