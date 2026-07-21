import json
from argparse import ArgumentParser
import glob
import os
import re

def load_capture_manifest(capture_path):
    with open(capture_path, 'r') as file:
        return json.load(file)

def load_diff_report(diff_path):
    with open(diff_path, 'r') as file:
        return json.load(file)

def evaluate_test_id(device_name, test_id, capture_manifest, diff_report, pass_pattern=None, fail_pattern=None):
    result = {}
    
    # Get command data
    device_commands = capture_manifest["per_command"].get(test_id)
    
    if not device_commands:
        raise ValueError(f"Test ID {test_id} not found in capture manifest for device {device_name}")

    risk_level = device_commands.get("risk", "unknown")
    
    # Determine verdict based on risk level
    if risk_level == "manual-only":
        result["verdict"] = "manual-review-required"
        result["manual_notes"] = device_commands.get("notes", "")
    elif risk_level == "read-only-debug":
        result["verdict"] = "manual-review-required"
        result["evidence"] = check_patterns(device_commands, pass_pattern=pass_pattern, fail_pattern=fail_pattern)
    elif risk_level == "read-only-safe":
        if not (pass_pattern and fail_pattern):
            result["verdict"] = "manual-review-required"
            result["raw_output"] = device_commands.get("output", "")
        else:
            pattern_check_result = check_patterns(device_commands, pass_pattern=pass_pattern, fail_pattern=fail_pattern)
            
            if "fail" in pattern_check_result:
                result["verdict"] = "fail"
            elif "pass" in pattern_check_result:
                result["verdict"] = "pass"
            else:
                result["verdict"] = "manual-review-required"

    # Cross-reference diff report
    diff_entry = next((entry for entry in diff_report if entry["test_id"] == test_id), None)
    if diff_entry and diff_entry.get("status") in ["only-in-pre", "only-in-post"]:
        result["verdict"] = "manual-review-required"

    return result

def check_patterns(device_commands, pass_pattern=None, fail_pattern=None):
    evidence = []

    output = device_commands.get("output", "")
    
    if fail_pattern:
        fail_match = re.search(fail_pattern, output)
        if fail_match:
            evidence.append(f"fail matched: {fail_match.group(0)}")
    
    if pass_pattern and "fail" not in evidence:
        pass_match = re.search(pass_pattern, output)
        if pass_match:
            evidence.append(f"pass matched: {pass_match.group(0)}")

    return ', '.join(evidence) or "no patterns matched"

def main():
    parser = ArgumentParser(description="Evaluate test results from a network baseline capture.")
    parser.add_argument("--ticket", required=True, help="Ticket number (e.g., CHG-12345)")
    
    args = parser.parse_args()

    pre_capture_manifest_path = f"captures/{args.ticket}/baseline/*/capture_manifest.json"
    post_capture_manifest_path = f"captures/{args.ticket}/post/*/capture_manifest.json"
    diff_report_path = "diff_report.json"

    # Load files
    capture_pre_paths = glob.glob(pre_capture_manifest_path)
    capture_post_paths = glob.glob(post_capture_manifest_path)

    if not capture_pre_paths or not capture_post_paths:
        raise ValueError("Capture manifest files not found")

    # Assume we only evaluate against the first pre and post manifest
    pre_manifest = load_capture_manifest(capture_pre_paths[0])
    post_manifest = load_capture_manifest(capture_post_paths[0])

    diff_report = load_diff_report(diff_report_path)

    evaluation_report = []

    for device in pre_manifest["per_device"].keys():
        if device not in post_manifest["per_device"]:
            continue

        test_ids = set(pre_manifest["per_command"].keys()) & set(post_manifest["per_command"].keys())
        
        for test_id in test_ids:
            section = (pre_manifest.get("sections") or {}).get(test_id, "")
            description = (pre_manifest.get("commands") or {}).get(test_id, {}).get("description", "")

            result_pre = evaluate_test_id(device, test_id, pre_manifest, diff_report)
            result_post = evaluate_test_id(device, test_id, post_manifest, diff_report)

            # Here you could combine results from pre and post manifests if needed
            # For simplicity, this example just takes the post manifest result

            evaluation_entry = {
                "device": device,
                "test_id": test_id,
                "section": section,
                "description": description,
                "verdict": result_post["verdict"],
                "evidence": result_post.get("evidence", ""),
                "manual_notes": result_post.get("manual_notes", ""),
            }

            evaluation_report.append(evaluation_entry)

    # Save evaluation report
    with open("evaluation_report.json", 'w') as file:
        json.dump(evaluation_report, file, indent=4)

if __name__ == "__main__":
    main()
